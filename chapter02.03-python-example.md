# Recipe 2.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 2.3. It shows one way you could translate those CDI concepts into working Python code using Amazon Bedrock. It is not production-ready. There's no EHR integration, no real-time streaming, no compliance-reviewed query templates. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a CDI workqueue on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline follows the six steps from the main recipe: receive a clinical note, extract clinical elements via LLM, retrieve coding guidelines from a knowledge base, generate CDI suggestions, prioritize and filter, then store results. Each step maps 1:1 to the pseudocode.

---

## Setup

You'll need the AWS SDK for Python. JSON handling is in the standard library, so `boto3` is the only install:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `bedrock:InvokeModel` (for Claude model access)
- `bedrock:Retrieve` (for Knowledge Base queries)
- `s3:GetObject` and `s3:PutObject` (note storage and audit trail)
- `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` (suggestion lifecycle)
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` (CloudWatch Logs)

You also need model access enabled in the Bedrock console for your chosen Claude model. This is a one-time manual step per account per region.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. The confidence thresholds and max suggestions per note are the knobs you'll tune most during pilot. Start conservative (high thresholds, low max) and loosen as you build physician trust.

```python
import json
import logging
import uuid
import datetime
from datetime import timezone
from decimal import Decimal  # Imported for when you add numeric confidence/impact scores to DynamoDB items. DynamoDB requires Decimal for numbers, not Python float.

import boto3
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI (note content,
# patient identifiers, diagnosis text).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles Bedrock throttling during burst traffic.
# Bedrock has per-model, per-account token-per-minute limits.
# Adaptive mode uses exponential backoff with jitter automatically.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# --- Model Configuration ---
# Claude 3 Sonnet balances speed and accuracy well for CDI analysis.
# Claude 3 Haiku is faster and cheaper but less accurate on nuanced clinical reasoning.
# Claude 3 Opus is more accurate but slower and more expensive per token.
# For CDI, Sonnet is the sweet spot: fast enough for near-real-time, smart enough
# for clinical reasoning about specificity gaps.
MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

# --- Knowledge Base Configuration ---
# This is the Bedrock Knowledge Base ID containing your ICD-10-CM guidelines,
# organizational CDI query templates, and payer-specific documentation requirements.
# Create this via the Bedrock console or CloudFormation. The knowledge base should
# be populated with current-year ICD-10-CM Official Guidelines (updated each October).
KNOWLEDGE_BASE_ID = "YOUR_KNOWLEDGE_BASE_ID"  # Replace with your actual KB ID

# --- Suggestion Thresholds ---
# Maximum suggestions per note. More than this causes alert fatigue.
# Start at 3 during pilot, increase to 5 once physicians trust the system.
# (The main recipe's pseudocode uses 5 as the eventual target; we deliberately
# start lower here to model a conservative pilot configuration.)
MAX_SUGGESTIONS_PER_NOTE = 3

# Minimum confidence level to surface a suggestion.
# "high" = only high-confidence suggestions (conservative, fewer false positives)
# "medium" = medium and high (balanced)
# "low" = everything (aggressive, more noise)
CONFIDENCE_THRESHOLD = "medium"

# Confidence level ordering for comparison and sorting.
CONFIDENCE_LEVELS = {"high": 3, "medium": 2, "low": 1}

# Impact level ordering for prioritization.
IMPACT_LEVELS = {"high": 3, "medium": 2, "low": 1}

# Suggestion expiration: hours after which an unacted suggestion expires.
# 72 hours is typical for inpatient CDI. Outpatient might be shorter (48h)
# because the coding window is tighter.
SUGGESTION_EXPIRY_HOURS = 72

# --- Storage Configuration ---
# S3 bucket for clinical notes and audit trail.
NOTES_BUCKET = "your-cdi-notes-bucket"  # Replace with your bucket name

# DynamoDB table for suggestion lifecycle tracking.
SUGGESTIONS_TABLE = "cdi-suggestions"  # Replace with your table name
```

---

## Step 1: Receive and Parse the Clinical Note

*The pseudocode calls this `receive_note(note_content, metadata)`. In production, notes arrive via EHR integration (HL7 FHIR, ADT feeds, or direct API). For this example, we accept the note as a string and store it in S3 for audit trail before processing.*

```python
def receive_note(note_content: str, metadata: dict) -> str:
    """
    Store a clinical note in S3 and return the storage key for downstream processing.

    Every note that enters the CDI pipeline gets stored before analysis begins.
    This serves two purposes: (1) audit trail showing exactly what the system
    analyzed, and (2) reprocessing capability if you update your model or guidelines
    and want to re-run historical notes.

    Args:
        note_content: The full text of the clinical note.
        metadata:     Context about the note. Expected keys:
                      - encounter_id: unique encounter identifier
                      - provider_id:  who wrote the note
                      - note_type:    "progress_note", "h_and_p", "discharge_summary", etc.
                      - timestamp:    when the note was authored (ISO format)

    Returns:
        The S3 object key where the note was stored.
    """
    encounter_id = metadata.get("encounter_id", "unknown")
    note_type = metadata.get("note_type", "clinical_note")
    timestamp = metadata.get("timestamp", datetime.datetime.now(timezone.utc).isoformat())

    # Build a predictable key structure for easy retrieval and lifecycle policies.
    # Pattern: notes-inbox/{encounter_id}/{timestamp}-{note_type}.txt
    note_key = f"notes-inbox/{encounter_id}/{timestamp}-{note_type}.txt"

    s3_client.put_object(
        Bucket=NOTES_BUCKET,
        Key=note_key,
        Body=note_content.encode("utf-8"),
        ContentType="text/plain",
        # ServerSideEncryption with KMS is configured at the bucket level via
        # bucket default encryption. If your bucket doesn't have this, add:
        # ServerSideEncryption="aws:kms",
        # SSEKMSKeyId="your-kms-key-id",
        Metadata={
            "encounter_id": encounter_id,
            "provider_id": metadata.get("provider_id", "unknown"),
            "note_type": note_type,
        },
    )

    logger.info(
        "Stored note for encounter %s, type=%s, length=%d chars",
        encounter_id, note_type, len(note_content),
    )
    return note_key
```

---

## Step 2: Extract Clinical Elements

*The pseudocode calls this `extract_clinical_elements(note_content)`. This step uses the LLM to identify what the note actually contains: diagnoses, medications, lab values, and procedures. The output becomes the "what's documented" baseline that we compare against coding requirements in Step 4.*

```python
def extract_clinical_elements(note_content: str) -> dict:
    """
    Use Bedrock (Claude) to extract structured clinical elements from a note.

    This is a structured extraction task: we want JSON output, not prose.
    Low temperature (0.1) keeps the model factual and deterministic.
    The model identifies diagnoses, medications, labs, and procedures,
    along with any specificity qualifiers already present in the documentation.

    Args:
        note_content: The full text of the clinical note.

    Returns:
        A dict with keys: diagnoses, medications, lab_values, procedures.
        Each contains a list of extracted elements with their context.
    """
    # The system prompt establishes the extraction task and output format.
    # We explicitly tell the model to note what qualifiers ARE present
    # and what common qualifiers are MISSING. This pre-work makes Step 4 easier.
    extraction_prompt = """You are a clinical documentation analyst. Extract structured clinical elements from the following note.

For each diagnosis found, note:
- The diagnosis name as documented
- Any specificity qualifiers already present (type, acuity, laterality, causative organism, stage)
- Common ICD-10-CM qualifiers that are NOT documented but typically required

For medications, note the drug name, dose (if stated), and route (if stated).
For lab values, note the test name and result (if stated).
For procedures, note the procedure name and any relevant details.

Return ONLY valid JSON in this exact structure:
{
  "diagnoses": [
    {
      "name": "diagnosis as documented",
      "qualifiers_present": ["list of specificity qualifiers found"],
      "qualifiers_missing": ["common qualifiers not documented"],
      "supporting_context": "relevant text from the note that relates to this diagnosis"
    }
  ],
  "medications": [
    {"name": "drug name", "dose": "dose if stated", "route": "route if stated"}
  ],
  "lab_values": [
    {"test": "test name", "result": "value if stated", "interpretation": "normal/abnormal if clear"}
  ],
  "procedures": [
    {"name": "procedure name", "details": "relevant details"}
  ]
}"""

    # Build the Bedrock request body for Claude's Messages API.
    request_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "temperature": 0.1,  # Low temperature for factual extraction
        "system": extraction_prompt,
        "messages": [
            {
                "role": "user",
                "content": f"Extract clinical elements from this note:\n\n{note_content}",
            }
        ],
    })

    response = bedrock_runtime.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=request_body,
    )

    response_body = json.loads(response["body"].read())

    # Claude's response is in content[0].text for the Messages API.
    raw_text = response_body["content"][0]["text"]

    # Parse the JSON from the model's response.
    # The model sometimes wraps JSON in markdown code fences. Strip those.
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    clinical_elements = json.loads(cleaned)

    diagnosis_count = len(clinical_elements.get("diagnoses", []))
    med_count = len(clinical_elements.get("medications", []))
    logger.info(
        "Extracted %d diagnoses, %d medications from note",
        diagnosis_count, med_count,
    )

    return clinical_elements
```

---

## Step 3: Retrieve Relevant Coding Guidelines

*The pseudocode calls this `retrieve_guidelines(diagnoses)`. This step queries the Bedrock Knowledge Base to pull ICD-10-CM guidelines and organizational query templates relevant to the diagnoses found in Step 2. This is the RAG piece: grounding the LLM's suggestions in authoritative, current coding rules rather than relying on potentially outdated training data.*

```python
def retrieve_guidelines(diagnoses: list) -> dict:
    """
    Query the Bedrock Knowledge Base for coding guidelines relevant to each diagnosis.

    For each diagnosis extracted in Step 2, we retrieve:
    - ICD-10-CM specificity requirements (what qualifiers are needed for a complete code)
    - Organizational CDI query templates (approved phrasing for physician queries)
    - Any payer-specific documentation requirements

    The knowledge base should contain current-year ICD-10-CM Official Guidelines
    (CMS publishes these annually each October) and your organization's approved
    CDI query templates.

    Args:
        diagnoses: List of diagnosis dicts from extract_clinical_elements.
                   Each has "name", "qualifiers_present", "qualifiers_missing".

    Returns:
        A dict with:
        - coding_guidelines: list of retrieved guideline passages per diagnosis
        - query_templates: list of retrieved organizational query templates
    """
    all_guidelines = []

    for diagnosis in diagnoses:
        diagnosis_name = diagnosis.get("name", "")
        missing_qualifiers = diagnosis.get("qualifiers_missing", [])

        if not diagnosis_name:
            continue

        # Build a retrieval query focused on this diagnosis and its coding requirements.
        # Including the missing qualifiers in the query helps the vector search find
        # the most relevant guideline sections.
        query_text = (
            f"ICD-10-CM coding guidelines and specificity requirements for "
            f"{diagnosis_name}. Required qualifiers: {', '.join(missing_qualifiers)}"
        )

        # Retrieve from the knowledge base using Bedrock Agent Runtime.
        response = bedrock_agent_runtime.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={"text": query_text},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": 5,  # Top 5 most relevant passages
                }
            },
        )

        # Extract the text content from retrieval results.
        results = response.get("retrievalResults", [])
        for result in results:
            content = result.get("content", {}).get("text", "")
            score = result.get("score", 0.0)
            if content:
                all_guidelines.append({
                    "diagnosis": diagnosis_name,
                    "guideline_text": content,
                    "relevance_score": score,
                })

    # Also retrieve organizational query templates.
    # These are the pre-approved phrasings your compliance team has reviewed.
    diagnosis_names = [d.get("name", "") for d in diagnoses if d.get("name")]
    template_query = (
        f"CDI query templates for documentation improvement queries about: "
        f"{', '.join(diagnosis_names)}"
    )

    template_response = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": template_query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": 10,
            }
        },
    )

    query_templates = []
    for result in template_response.get("retrievalResults", []):
        content = result.get("content", {}).get("text", "")
        if content:
            query_templates.append(content)

    logger.info(
        "Retrieved %d guideline passages and %d query templates",
        len(all_guidelines), len(query_templates),
    )

    return {
        "coding_guidelines": all_guidelines,
        "query_templates": query_templates,
    }
```

---

## Step 4: Identify Specificity Gaps and Generate Suggestions

*The pseudocode calls this `generate_cdi_suggestions(note_content, clinical_elements, guidelines)`. This is the core CDI step. The LLM receives the clinical note, the extracted elements from Step 2, and the retrieved coding guidelines from Step 3. It identifies where documentation falls short of coding specificity requirements and generates physician-friendly suggestions.*

```python
def generate_cdi_suggestions(
    note_content: str,
    clinical_elements: dict,
    guidelines: dict,
) -> list:
    """
    Use the LLM to identify specificity gaps and generate CDI suggestions.

    This is the heart of the pipeline. The model compares what's documented
    (clinical_elements) against what's required (guidelines) and generates
    suggestions for each genuine gap. The key constraints:

    - Suggestions must be phrased as questions, never assertions
    - Only suggest clarifications supported by evidence IN the note
    - Never assert clinical findings the physician didn't document
    - Include the clinical evidence supporting each suggestion

    Args:
        note_content:      The full clinical note text.
        clinical_elements: Structured extraction from Step 2.
        guidelines:        Retrieved coding guidelines and templates from Step 3.

    Returns:
        A list of suggestion dicts, each containing:
        - diagnosis, current_documentation, gap_description
        - clinical_evidence, suggested_query
        - confidence (high/medium/low), estimated_impact (high/medium/low)
        - icd10_current, icd10_potential
    """
    # Format the guidelines into a readable block for the prompt.
    guidelines_text = ""
    for g in guidelines.get("coding_guidelines", []):
        guidelines_text += f"\n[{g['diagnosis']}]: {g['guideline_text']}\n"

    templates_text = "\n".join(guidelines.get("query_templates", []))

    # The CDI analysis prompt. This is where prompt engineering matters most.
    # Physician acceptance rates correlate more with suggestion phrasing than
    # with gap detection accuracy. Invest time here.
    cdi_prompt = """You are a Clinical Documentation Improvement (CDI) specialist with deep knowledge of ICD-10-CM coding guidelines. Analyze the clinical note below for documentation specificity gaps.

CRITICAL RULES:
1. Only suggest clarifications where coding guidelines REQUIRE more specificity
2. Only suggest clarifications supported by clinical evidence IN the note
3. NEVER assert clinical findings. Always phrase as questions to the physician.
4. Include the specific clinical evidence that supports each suggestion
5. Rate each suggestion's confidence (high/medium/low) and estimated impact (high/medium/low)
6. Do NOT suggest clarifications for information already documented elsewhere in the note
7. Be respectful and collegial in query phrasing. You are helping, not auditing.

CONFIDENCE DEFINITIONS:
- high: Clear specificity gap with strong clinical evidence supporting clarification
- medium: Likely gap, but clinical evidence is indirect or the guideline requirement is nuanced
- low: Possible gap, but uncertain whether the physician intentionally left it unspecified

IMPACT DEFINITIONS:
- high: Likely affects DRG assignment or significantly changes code specificity (e.g., unspecified to specific organism)
- medium: Affects code specificity but unlikely to change DRG (e.g., adding laterality)
- low: Minor specificity improvement with minimal coding impact

Return ONLY valid JSON as a list of suggestions:
[
  {
    "diagnosis": "the condition lacking specificity",
    "current_documentation": "what the note currently says",
    "gap_description": "what specificity is missing per coding guidelines",
    "clinical_evidence": "what in the note supports a more specific diagnosis",
    "suggested_query": "physician-friendly question requesting clarification",
    "confidence": "high|medium|low",
    "estimated_impact": "high|medium|low",
    "icd10_current": "likely current code (e.g., J18.9)",
    "icd10_potential": "likely code if clarified (e.g., J15.1)"
  }
]

If no genuine specificity gaps exist, return an empty list: []"""

    # Assemble the user message with all context.
    user_message = f"""CLINICAL NOTE:
{note_content}

EXTRACTED CLINICAL ELEMENTS:
{json.dumps(clinical_elements, indent=2)}

RELEVANT CODING GUIDELINES:
{guidelines_text}

APPROVED QUERY TEMPLATES:
{templates_text}

Identify all documentation specificity gaps and generate CDI suggestions."""

    request_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "temperature": 0.2,  # Slightly higher than extraction for natural phrasing
        "system": cdi_prompt,
        "messages": [
            {"role": "user", "content": user_message},
        ],
    })

    response = bedrock_runtime.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=request_body,
    )

    response_body = json.loads(response["body"].read())
    raw_text = response_body["content"][0]["text"]

    # Parse JSON from response, handling markdown code fences.
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    suggestions = json.loads(cleaned)

    logger.info("Generated %d raw CDI suggestions", len(suggestions))
    return suggestions
```

---

## Step 5: Prioritize and Filter Suggestions

*The pseudocode calls this `prioritize_suggestions(suggestions)`. Not every gap is worth querying. This step applies confidence thresholds, sorts by impact, and caps the total to avoid alert fatigue. The thresholds are the most important tuning knobs in the system.*

```python
def prioritize_suggestions(suggestions: list) -> dict:
    """
    Filter and rank CDI suggestions by confidence and impact.

    The filtering logic:
    1. Remove suggestions below CONFIDENCE_THRESHOLD
    2. Sort remaining by impact (high first), then confidence (high first)
    3. Cap at MAX_SUGGESTIONS_PER_NOTE
    4. Track what was suppressed and why (for audit and threshold tuning)

    Args:
        suggestions: Raw suggestion list from generate_cdi_suggestions.

    Returns:
        A dict with:
        - active_suggestions: the suggestions to surface to the CDI specialist/physician
        - suppressed: list of filtered-out suggestions, each with a "reason" explaining why
    """
    threshold_value = CONFIDENCE_LEVELS.get(CONFIDENCE_THRESHOLD, 2)

    # Filter by confidence threshold.
    filtered = []
    suppressed_low_confidence = []

    for suggestion in suggestions:
        suggestion_confidence = CONFIDENCE_LEVELS.get(
            suggestion.get("confidence", "low"), 1
        )
        if suggestion_confidence >= threshold_value:
            filtered.append(suggestion)
        else:
            suppressed_low_confidence.append({
                "suggestion": suggestion,
                "reason": f"confidence '{suggestion.get('confidence')}' below threshold '{CONFIDENCE_THRESHOLD}'",
            })

    # Sort by impact (descending), then confidence (descending).
    filtered.sort(
        key=lambda s: (
            IMPACT_LEVELS.get(s.get("estimated_impact", "low"), 1),
            CONFIDENCE_LEVELS.get(s.get("confidence", "low"), 1),
        ),
        reverse=True,
    )

    # Cap at maximum suggestions per note.
    active = filtered[:MAX_SUGGESTIONS_PER_NOTE]
    suppressed_over_limit = []

    if len(filtered) > MAX_SUGGESTIONS_PER_NOTE:
        for s in filtered[MAX_SUGGESTIONS_PER_NOTE:]:
            suppressed_over_limit.append({
                "suggestion": s,
                "reason": f"exceeded max {MAX_SUGGESTIONS_PER_NOTE} suggestions per note",
            })

    all_suppressed = suppressed_low_confidence + suppressed_over_limit

    logger.info(
        "Prioritization: %d active, %d suppressed (%d low confidence, %d over limit)",
        len(active),
        len(all_suppressed),
        len(suppressed_low_confidence),
        len(suppressed_over_limit),
    )

    return {
        "active_suggestions": active,
        "suppressed": all_suppressed,
    }
```

---

## Step 6: Store Results and Notify

*The pseudocode calls this `store_and_notify(encounter_id, suggestions, suppressed)`. Each suggestion gets a unique ID and a lifecycle status in DynamoDB. Suppressed suggestions go to S3 for audit. In production, this step also triggers notification to the CDI specialist's workqueue or the physician's EHR inbox.*

```python
def store_and_notify(encounter_id: str, prioritized: dict, note_key: str) -> list:
    """
    Write suggestions to DynamoDB for lifecycle tracking and store audit trail in S3.

    Each suggestion becomes a separate DynamoDB item so it can be individually
    accepted, rejected, or expired. The lifecycle states are:
    - GENERATED: suggestion created, not yet shown to anyone
    - PRESENTED: shown to CDI specialist or physician
    - ACCEPTED: physician agreed and updated documentation
    - REJECTED: physician declined (optionally with reason)
    - EXPIRED: not acted on within SUGGESTION_EXPIRY_HOURS

    Args:
        encounter_id: The encounter this note belongs to.
        prioritized:  Output from prioritize_suggestions (active + suppressed).
        note_key:     S3 key of the stored note (for audit linkage).

    Returns:
        List of suggestion IDs that were stored as active.
    """
    suggestions_table = dynamodb.Table(SUGGESTIONS_TABLE)
    now = datetime.datetime.now(timezone.utc)
    expires_at = now + datetime.timedelta(hours=SUGGESTION_EXPIRY_HOURS)

    stored_ids = []

    for suggestion in prioritized["active_suggestions"]:
        suggestion_id = str(uuid.uuid4())

        # DynamoDB requires Decimal for numeric values. Confidence and impact
        # are strings here, but if you add numeric scores later, wrap them.
        item = {
            "suggestion_id": suggestion_id,
            "encounter_id": encounter_id,
            "status": "GENERATED",
            "diagnosis": suggestion.get("diagnosis", ""),
            "current_documentation": suggestion.get("current_documentation", ""),
            "gap_description": suggestion.get("gap_description", ""),
            "clinical_evidence": suggestion.get("clinical_evidence", ""),
            "suggested_query": suggestion.get("suggested_query", ""),
            "confidence": suggestion.get("confidence", "unknown"),
            "estimated_impact": suggestion.get("estimated_impact", "unknown"),
            "icd10_current": suggestion.get("icd10_current", ""),
            "icd10_potential": suggestion.get("icd10_potential", ""),
            "source_note_key": note_key,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        suggestions_table.put_item(Item=item)
        stored_ids.append(suggestion_id)

    # Store suppressed suggestions in S3 for audit and threshold tuning.
    # These are not surfaced to users but are valuable for understanding
    # what the system is filtering out. If your acceptance rate is too low,
    # review suppressed suggestions to see if the threshold is too aggressive.
    if prioritized["suppressed"]:
        audit_key = f"cdi-audit/{encounter_id}/suppressed-{now.isoformat()}.json"
        s3_client.put_object(
            Bucket=NOTES_BUCKET,
            Key=audit_key,
            Body=json.dumps(prioritized["suppressed"], indent=2).encode("utf-8"),
            ContentType="application/json",
        )

    logger.info(
        "Stored %d active suggestions for encounter %s. %d suppressed (audit stored).",
        len(stored_ids), encounter_id, len(prioritized["suppressed"]),
    )

    # In production, this is where you'd notify the CDI workqueue:
    # - SNS topic for CDI specialist notification
    # - SQS queue for batch processing
    # - Direct EHR API call for concurrent CDI (real-time physician alerts)
    #
    # Example (uncomment and configure for your environment).
    # Requires an SNS client at module scope:
    #     sns_client = boto3.client("sns", config=BOTO3_RETRY_CONFIG)
    #
    # sns_client.publish(
    #     TopicArn="arn:aws:sns:us-east-1:123456789012:cdi-notifications",
    #     Message=json.dumps({
    #         "encounter_id": encounter_id,
    #         "suggestion_count": len(stored_ids),
    #         "highest_impact": prioritized["active_suggestions"][0].get("estimated_impact")
    #             if prioritized["active_suggestions"] else "none",
    #     }),
    # )

    return stored_ids
```

---

## Putting It All Together

Here's the full CDI pipeline assembled into a single function. This runs all six steps sequentially for one clinical note.

```python
def analyze_note_for_cdi(note_content: str, metadata: dict) -> dict:
    """
    Run the full CDI analysis pipeline for one clinical note.

    Covers all six steps from the Recipe 2.3 pseudocode:
      1. Receive and store the clinical note
      2. Extract clinical elements (diagnoses, meds, labs, procedures)
      3. Retrieve relevant coding guidelines from the knowledge base
      4. Generate CDI suggestions using LLM with RAG context
      5. Prioritize and filter suggestions
      6. Store results and notify

    Args:
        note_content: The full text of the clinical note.
        metadata:     Context dict with encounter_id, provider_id, note_type, timestamp.

    Returns:
        A dict with the analysis results: suggestions, suppressed count, timing.
    """
    import time
    start_time = time.time()

    encounter_id = metadata.get("encounter_id", "unknown")

    # Step 1: Store the note for audit trail.
    print(f"Step 1: Storing note for encounter {encounter_id}...")
    note_key = receive_note(note_content, metadata)
    print(f"  Stored at: {note_key}")

    # Step 2: Extract clinical elements from the note.
    print("Step 2: Extracting clinical elements...")
    clinical_elements = extract_clinical_elements(note_content)
    diagnoses = clinical_elements.get("diagnoses", [])
    print(f"  Found {len(diagnoses)} diagnoses, "
          f"{len(clinical_elements.get('medications', []))} medications")

    # Step 3: Retrieve coding guidelines for the identified diagnoses.
    print("Step 3: Retrieving coding guidelines from knowledge base...")
    guidelines = retrieve_guidelines(diagnoses)
    print(f"  Retrieved {len(guidelines['coding_guidelines'])} guideline passages, "
          f"{len(guidelines['query_templates'])} query templates")

    # Step 4: Generate CDI suggestions.
    print("Step 4: Generating CDI suggestions...")
    raw_suggestions = generate_cdi_suggestions(note_content, clinical_elements, guidelines)
    print(f"  Generated {len(raw_suggestions)} raw suggestions")

    # Step 5: Prioritize and filter.
    print("Step 5: Prioritizing and filtering...")
    prioritized = prioritize_suggestions(raw_suggestions)
    print(f"  Active: {len(prioritized['active_suggestions'])}, "
          f"Suppressed: {len(prioritized['suppressed'])}")

    # Step 6: Store and notify.
    print("Step 6: Storing results...")
    suggestion_ids = store_and_notify(encounter_id, prioritized, note_key)
    print(f"  Stored {len(suggestion_ids)} suggestion(s)")

    elapsed_ms = int((time.time() - start_time) * 1000)
    print(f"\nDone. Processing time: {elapsed_ms}ms")

    return {
        "encounter_id": encounter_id,
        "note_key": note_key,
        "suggestions": prioritized["active_suggestions"],
        "suggestion_ids": suggestion_ids,
        "suppressed_count": len(prioritized["suppressed"]),
        "processing_time_ms": elapsed_ms,
    }


# --- Example usage ---
if __name__ == "__main__":
    # A synthetic clinical note with intentional specificity gaps.
    # This is NOT a real patient note. Never use real PHI in development.
    sample_note = """
    PROGRESS NOTE - Day 3 of Admission

    Subjective: Patient reports improved breathing since yesterday. Still has
    productive cough with yellow sputum. Denies chest pain. Reports mild nausea
    with antibiotics.

    Objective:
    Vitals: T 99.2F, HR 88, BP 132/78, RR 18, SpO2 94% on 2L NC
    Lungs: Decreased breath sounds left lower lobe, scattered rhonchi bilaterally
    Heart: Regular rate and rhythm, no murmurs
    Ext: 1+ bilateral lower extremity edema

    Labs:
    WBC 14.2 (down from 18.1 on admission)
    Sputum culture: growing Klebsiella pneumoniae
    BNP: 1240
    Echo (yesterday): EF 30%, moderate mitral regurgitation

    Assessment/Plan:
    1. Pneumonia - improving on current antibiotics (Zosyn). Will continue
       current regimen. Repeat chest X-ray tomorrow.
    2. Heart failure - continue diuresis with IV Lasix 40mg BID.
       Volume status improving based on I/Os.
    3. Diabetes - continue home insulin regimen. A1c was 8.2 on admission.
       Will adjust basal dose if needed.
    4. Hypertension - hold lisinopril given acute illness. Resume at discharge.
    """

    sample_metadata = {
        "encounter_id": "ENC-2026-05-06-00312",
        "provider_id": "PRV-00891",
        "note_type": "progress_note",
        "timestamp": "2026-05-06T09:30:00-04:00",
    }

    result = analyze_note_for_cdi(sample_note, sample_metadata)
    print("\n" + "=" * 60)
    print("RESULTS:")
    print("=" * 60)
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

Run this end to end against a synthetic note and you'll get the full CDI pattern in motion: clinical elements extracted, guidelines retrieved, suggestions generated, results stored. The distance between this and a production CDI deployment is significant. Here's where the gap lives.

**EHR integration is the hardest part of the entire project.** This example accepts a note as a string. In reality, getting clinical notes out of an EHR in real time requires HL7 FHIR subscriptions, ADT event feeds, or vendor-specific APIs (Epic's CDS Hooks, Oracle Health's SMART on FHIR). The integration layer is often more complex than the AI pipeline itself. Budget 40-60% of your implementation timeline for EHR integration alone.

**Knowledge base population and maintenance.** The example assumes a populated Bedrock Knowledge Base. Building one requires: downloading the current ICD-10-CM Official Guidelines from CMS (updated every October), chunking them appropriately for vector search, writing organizational CDI query templates (compliance-reviewed), and adding payer-specific documentation requirements. This knowledge base needs annual maintenance at minimum, and more frequent updates when CMS publishes mid-year corrections.

**Context window management for long notes.** Hospital notes can be long. A multi-day admission with daily progress notes, consult notes, and procedure notes can exceed 50,000 tokens. This example sends the full note to the model. A production system needs a strategy for notes that exceed the context window: summarize older notes, analyze the most recent note in full with references to prior notes, or chunk with overlap and deduplicate suggestions across chunks.

**Feedback loop for continuous improvement.** When physicians accept or reject suggestions, that signal is gold. Accepted suggestions validate the model's reasoning. Rejected suggestions (especially with physician comments) are training data for prompt refinement. This example has no feedback mechanism. A production system tracks acceptance rates per suggestion type, per diagnosis category, and per physician, then uses that data to tune confidence thresholds and prompt phrasing.

**Compliance review of generated queries.** Every CDI query phrasing should be reviewed by your compliance team before going live. The line between "asking for documentation clarification" and "telling physicians what to document for revenue" is one that OIG auditors care about. In production, you'd validate generated queries against a library of compliance-approved templates and flag any that deviate significantly for human review before surfacing them.

**Concurrent vs. retrospective CDI.** This example is retrospective: the note is complete, then analyzed. Concurrent CDI (suggestions while the physician is still writing) has higher impact but requires streaming note content, incremental analysis, and tight EHR UI integration. The architecture changes significantly: you'd use WebSocket connections or server-sent events rather than S3 event triggers, and you'd need to handle partial notes gracefully.

**Hallucination detection.** The most dangerous failure mode is the model suggesting a specificity improvement based on clinical information that isn't in the chart. "Your labs suggest E. coli" when no culture results exist. A production system cross-references every piece of clinical evidence cited in a suggestion against the actual note content. If the evidence text doesn't appear in (or closely paraphrase) the source note, suppress the suggestion. This is a post-generation validation step that this example doesn't include.

**Rate limiting and cost management.** Each note requires two Bedrock invocations (extraction + suggestion generation) plus knowledge base retrieval calls. At scale (hundreds of notes per day for a mid-size hospital), you need to manage Bedrock token-per-minute limits, implement queuing for burst traffic, and monitor costs. The per-note cost ($0.02-0.08) is low, but at 500 notes/day that's $10-40/day in model costs alone. Set up CloudWatch billing alarms.

**Multi-note context and deduplication.** A patient's encounter generates multiple notes (admission H&P, daily progress notes, consult notes, discharge summary). This example analyzes each note independently. A production system should track which gaps have already been queried for this encounter and avoid re-querying the same gap on subsequent notes. It should also recognize when a later note addresses a gap identified in an earlier note and auto-resolve the suggestion.

**DynamoDB table design.** The example uses a simple single-table design with suggestion_id as the partition key. In production, you need efficient access patterns: query all suggestions for an encounter, query all open suggestions for a CDI specialist's workqueue, query acceptance rates by diagnosis category. Design your GSIs (Global Secondary Indexes) around these access patterns before you go live.

**VPC and encryption.** This example makes API calls without VPC configuration. A production Lambda handling clinical notes runs inside a VPC with private subnets and VPC endpoints for S3, Bedrock Runtime (for model invocation), Bedrock Agent Runtime (for knowledge base retrieval), DynamoDB, and CloudWatch Logs. The two Bedrock endpoints are easy to miss: Bedrock Runtime and Bedrock Agent Runtime are separate service endpoints, so you need both even though the code uses a single "Bedrock" concept. Clinical notes are PHI. S3 SSE-KMS with a customer-managed key. DynamoDB encryption at rest with a customer-managed KMS key (not the AWS-owned default, which isn't auditable in CloudTrail). All calls over TLS. Bedrock encrypts data in transit and at rest by default, but verify your BAA covers the specific models you're using.

**Testing with synthetic notes.** There are no tests here. A production pipeline has: unit tests for the prioritization and filtering logic, integration tests against Bedrock with synthetic notes covering common diagnosis categories, regression tests ensuring known specificity gaps are consistently detected, and load tests validating throughput at expected note volumes. Generate synthetic notes covering your top 20 DRGs for test fixtures. Never use real patient notes in non-production environments.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 2.3: Clinical Documentation Improvement (CDI) Suggestions](chapter02.03-clinical-documentation-improvement) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
