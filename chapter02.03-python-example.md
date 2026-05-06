# Recipe 2.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 2.3. It shows one way you could translate those CDI concepts into working Python code using Amazon Bedrock. It is not production-ready. There's no EHR integration, no real-time streaming, no compliance-reviewed query templates. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a CDI workqueue on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline follows the six steps from the main recipe: receive a clinical note, extract clinical elements via LLM, retrieve coding guidelines from a knowledge base, generate CDI suggestions, prioritize and filter, then store results. Each step maps 1:1 to the pseudocode.

---

## Setup

You'll need the AWS SDK for Python and a JSON parsing library:

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
from decimal import Decimal

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

