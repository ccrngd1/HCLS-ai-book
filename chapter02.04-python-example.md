# Recipe 2.4: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 2.4. It shows one way you could translate those prior authorization letter generation concepts into working Python using Amazon Bedrock, Bedrock Knowledge Bases, and DynamoDB. It is not production-ready. There's no EHR integration, no real payer policy ingestion pipeline, no physician review UI, and no submission integration. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd wire up to a medical practice on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps 1:1 to the seven pseudocode steps from the main recipe: receive the PA request, extract payer criteria, extract patient facts, map facts to criteria, retrieve supporting evidence, generate the letter, then validate the generated claims against sources.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` (for the letter generation and extraction models)
- `bedrock:Retrieve` (for Knowledge Base queries against both the payer policy KB and the clinical evidence KB)
- `s3:GetObject`, `s3:PutObject` (for draft letter storage and audit trail)
- `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:GetItem` (for PA case lifecycle tracking)
- `healthlake:SearchWithGet`, `healthlake:ReadResource` (if you're using HealthLake as your FHIR cache; not used in this illustrative example)
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` (for CloudWatch Logs)

You also need model access enabled in the Bedrock console for the Claude model you choose. Letter generation benefits from a capable model, so pick Claude Sonnet or equivalent rather than the smallest tier. Scope `bedrock:InvokeModel` to the specific model ARN in production, and scope `bedrock:Retrieve` to the specific knowledge base ARNs. The broad wildcards in a tutorial are fine for learning but will fail any serious IAM review.

One thing worth knowing upfront: there are two Bedrock service endpoints involved here, and they are easy to confuse. `bedrock-runtime` is what you call for model inference (`invoke_model`). `bedrock-agent-runtime` is what you call for knowledge base retrieval (`retrieve`). Both need VPC endpoints in production. The code below uses both.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. The two knowledge base IDs, the model choice, and the S3 bucket names are the knobs you'll change most often between environments.

```python
import hashlib
import json
import logging
import time
import uuid
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records to CloudWatch
# Logs Insights for query-friendly analysis. Never log PHI: no patient names,
# no member IDs, no clinical note text, no generated letter bodies.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles Bedrock throttling during bursty traffic. Practices
# tend to process prior auths in waves (mornings, end of clinic), so you will
# see ThrottlingException at scale. Adaptive mode uses exponential backoff
# with jitter so the retry storm doesn't make things worse.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
# bedrock-runtime is for model inference (invoke_model).
# bedrock-agent-runtime is for knowledge base retrieval (retrieve).
# These are separate service endpoints and need separate VPC endpoints
# in production. Easy one to miss during VPC setup.
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
# Reserved for the Step Functions orchestration shown commented-out in Step 1.
stepfunctions_client = boto3.client("stepfunctions", config=BOTO3_RETRY_CONFIG)

# --- Model Configuration ---
# Letter generation needs a capable model because it's a synthesis task across
# multiple sources with strict grounding constraints. Don't use the cheapest
# tier here; the bad output isn't worth the savings. Claude Sonnet is the
# sweet spot: smart enough to follow complex structural prompts, fast enough
# for interactive use.
#
# If your region requires cross-region inference, use the inference profile ID:
#   MODEL_ID = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
# TODO: verify the exact model ID available in your region and account.
MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# --- Knowledge Base Configuration ---
# Two separate knowledge bases. Keep them separate. They have different update
# cadences (payer policies change quarterly or more, clinical guidelines change
# annually), different content owners (operations vs. clinical), and different
# access patterns (narrow by payer+service vs. broad by condition).
#
# Populate the payer policies KB from Textract-extracted PDFs of payer
# medical policies. Populate the clinical evidence KB from vetted guideline
# sources (ACR, ASMBS, NCCN, etc.) with proper bibliographic metadata.
PAYER_POLICIES_KB_ID = "YOUR_PAYER_POLICIES_KB_ID"        # Replace with your KB ID
CLINICAL_EVIDENCE_KB_ID = "YOUR_CLINICAL_EVIDENCE_KB_ID"  # Replace with your KB ID

# --- Storage Configuration ---
# Three logical destinations: letter drafts (working), signed letters (archive),
# and audit data (everything else). In a real deployment these are likely
# three separate buckets with different lifecycle policies: drafts purged at
# 30 days, archives retained for 6+ years per HIPAA retention requirements,
# audit data intermediate.
PA_BUCKET = "your-pa-letter-bucket"  # Replace with your bucket

# DynamoDB table for PA case state tracking. Partition key: case_id (string).
# Add GSIs for provider_id and payer_id access patterns in production.
PA_CASES_TABLE = "pa-cases"  # Replace with your table name

# --- Pipeline Tuning ---
# Minimum validation rate below which we send the letter back for regeneration
# instead of presenting to the physician. A rate of 1.0 means every factual
# claim traced to a source; lower values mean the model hallucinated something.
# Don't set this below 0.95 in production. A letter with fabricated facts is
# worse than no letter at all.
MIN_VALIDATION_RATE_FOR_REVIEW = 1.0

# How far back to pull patient clinical data. 2 years covers most PA scenarios.
# For some services (bariatric surgery, complex oncology), you may need longer.
PATIENT_DATA_LOOKBACK_DAYS = 730

# Maximum number of policy chunks to retrieve. Payer policies can be long;
# pulling 10 chunks gives you enough context without overwhelming the prompt.
MAX_POLICY_CHUNKS = 10

# Maximum number of evidence citations to retrieve. More than 5-8 citations
# clutters the letter and dilutes the argument.
MAX_EVIDENCE_CITATIONS = 8
```

---

## Step 1: Receive the Prior Auth Request and Initialize State

*The pseudocode calls this `receive_pa_request(request)`. In production, this is invoked by an EHR integration or a practice management webhook when a clinician orders a service that requires prior auth. For this example, we accept a dict and create the initial case record in DynamoDB.*

```python
def receive_pa_request(request: dict) -> str:
    """
    Initialize a new PA case and return the case_id for downstream processing.

    The request is the trigger for the entire pipeline. We persist the intake
    state immediately so that if any later step fails, we have a record of
    what was requested. This is also the hook for your workflow orchestrator
    (Step Functions, SQS, or similar) to pick up the case.

    Args:
        request: Dict with the PA request details. Expected keys:
                 - patient_id:        internal identifier for the patient
                 - payer_id:          identifier for the payer (plan)
                 - service_code:      CPT, HCPCS, or drug code being requested
                 - service_description: human-readable service name
                 - diagnosis_code:    ICD-10 code supporting the request
                 - provider_id:       ordering physician identifier
                 - urgency:           "standard" or "expedited"

    Returns:
        The generated case_id (a UUID string).
    """
    # Idempotency check: duplicate PA submissions happen (EHR retries on
    # perceived timeout, user double-click, duplicate HL7 ADT events).
    # Derive a deterministic fingerprint from the request's natural key
    # and use a conditional write to prevent duplicate pipeline runs.
    fingerprint_input = "|".join([
        request["patient_id"],
        request["payer_id"],
        request["service_code"],
        request["diagnosis_code"],
        request.get("order_datetime", ""),
    ])
    fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()

    fingerprint_table = dynamodb.Table("pa-request-fingerprints")
    try:
        fingerprint_table.put_item(
            Item={
                "fingerprint": fingerprint,
                "case_id": "pending",  # placeholder until we have the real case_id
                "created_at": datetime.datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_not_exists(fingerprint)",
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        # This exact request already exists. Return the existing case_id.
        existing = fingerprint_table.get_item(Key={"fingerprint": fingerprint})
        existing_case_id = existing["Item"]["case_id"]
        logger.info(
            "Duplicate PA request detected (fingerprint=%s). Returning existing case_id=%s",
            fingerprint[:12], existing_case_id,
        )
        return existing_case_id

    case_id = str(uuid.uuid4())
    now = datetime.datetime.now(timezone.utc)

    # Update the fingerprint record with the real case_id
    fingerprint_table.update_item(
        Key={"fingerprint": fingerprint},
        UpdateExpression="SET case_id = :cid",
        ExpressionAttributeValues={":cid": case_id},
    )

    # Expedited cases have tighter deadlines under most payer contracts
    # (24-48 hours vs. 72 hours for standard). CMS-0057-F tightens this
    # further for Medicare Advantage starting 2027. Track deadlines
    # explicitly so your ops team can prioritize.
    deadline_hours = 24 if request.get("urgency") == "expedited" else 72
    target_deadline = now + datetime.timedelta(hours=deadline_hours)

    case_record = {
        "case_id": case_id,
        "status": "INITIATED",
        "patient_id": request["patient_id"],
        "payer_id": request["payer_id"],
        "service_code": request["service_code"],
        "service_description": request.get("service_description", ""),
        "diagnosis_code": request["diagnosis_code"],
        "provider_id": request["provider_id"],
        "urgency": request.get("urgency", "standard"),
        "created_at": now.isoformat(),
        "target_deadline": target_deadline.isoformat(),
    }

    cases_table = dynamodb.Table(PA_CASES_TABLE)
    cases_table.put_item(Item=case_record)

    # In production, this is where you'd kick off a Step Functions execution
    # to orchestrate the rest of the pipeline. That gives you retries per
    # step, visibility into stuck cases, and the ability to pause for the
    # physician review step without holding a Lambda open. Keeping it
    # sequential here for clarity.
    #
    # stepfunctions_client.start_execution(
    #     stateMachineArn=PA_LETTER_STATE_MACHINE_ARN,
    #     name=f"pa-case-{case_id}",
    #     input=json.dumps({"case_id": case_id}),
    # )

    logger.info(
        "Initialized PA case %s for payer=%s service=%s urgency=%s",
        case_id, request["payer_id"], request["service_code"],
        request.get("urgency", "standard"),
    )
    return case_id
```

---

## Step 2: Retrieve Payer Coverage Policy and Extract Criteria

*The pseudocode calls this `retrieve_and_extract_criteria(payer_id, service_code, diagnosis_code)`. This step turns the payer's PDF medical policy into a structured checklist of criteria. The retrieval pulls from the payer policies knowledge base; the extraction uses the LLM to parse narrative policy text into discrete, checkable criteria.*

```python
def retrieve_and_extract_criteria(
    payer_id: str,
    service_code: str,
    diagnosis_code: str,
) -> dict:
    """
    Retrieve the payer's coverage policy and extract a structured criteria list.

    The knowledge base has the current policies for contracted payers. The
    retrieval query narrows to the specific payer, service, and diagnosis.
    The extraction prompt converts policy prose ("the member must have tried
    at least one non-biologic DMARD for a minimum of twelve weeks") into
    structured criteria the downstream pipeline can iterate over.

    Args:
        payer_id:       The payer's identifier.
        service_code:   CPT/HCPCS/drug code for the requested service.
        diagnosis_code: ICD-10 code for the supporting diagnosis.

    Returns:
        Dict with:
        - criteria:      list of structured criterion dicts
        - policy_found:  True if a matching policy was retrieved
        - policy_chunks: the raw retrieval results (for audit)
    """
    # Build a focused retrieval query. The knowledge base documents should be
    # tagged with payer and service metadata so filters narrow correctly.
    # Vector similarity on the prose alone is less reliable than filter +
    # similarity combined.
    query_text = (
        f"Coverage policy for payer {payer_id}, "
        f"service code {service_code}, "
        f"diagnosis {diagnosis_code}. "
        f"Medical necessity criteria and documentation requirements."
    )

    retrieval_response = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=PAYER_POLICIES_KB_ID,
        retrievalQuery={"text": query_text},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": MAX_POLICY_CHUNKS,
                # In production, add metadata filters here to narrow by payer:
                # "filter": {"equals": {"key": "payer_id", "value": payer_id}},
            }
        },
    )

    policy_chunks = retrieval_response.get("retrievalResults", [])

    if not policy_chunks:
        logger.warning(
            "No policy found for payer=%s service=%s. Knowledge base may be "
            "stale or this service may not require PA for this payer.",
            payer_id, service_code,
        )
        return {"criteria": [], "policy_found": False, "policy_chunks": []}

    # Concatenate retrieved policy text for the extraction prompt.
    policy_text = "\n\n---\n\n".join(
        chunk.get("content", {}).get("text", "") for chunk in policy_chunks
    )

    # The extraction prompt. Deterministic (temperature=0) because we want
    # the same policy to produce the same criteria list every time. Any
    # randomness here would create audit headaches.
    extraction_system = """You are a clinical policy analyst. Extract the specific medical necessity criteria a patient must meet for coverage approval from the provided payer policy text.

Return ONLY valid JSON in this exact structure:
{
  "criteria": [
    {
      "criterion_id": "C1",
      "description": "the criterion stated in plain clinical language",
      "evidence_type": "lab value | medication history | diagnostic finding | clinical assessment | demographic | procedure history",
      "required": true,
      "source_section": "brief reference to the policy section this came from"
    }
  ],
  "policy_structure_notes": "any notes about 'meet N of M' alternative structures or conditional logic in the policy"
}

Extract every criterion explicitly. Do NOT combine criteria. Do NOT infer criteria that aren't in the text. If the policy has 'meet at least N of the following' structure, mark those criteria as required=false and note the N-of-M requirement in policy_structure_notes."""

    request_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "temperature": 0.0,  # Deterministic extraction
        "system": extraction_system,
        "messages": [
            {
                "role": "user",
                "content": f"POLICY TEXT:\n\n{policy_text}\n\nExtract the criteria as JSON.",
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
    raw_text = response_body["content"][0]["text"]

    criteria_data = _parse_json_response(raw_text)
    criteria = criteria_data.get("criteria", [])

    logger.info(
        "Extracted %d criteria from policy for payer=%s service=%s",
        len(criteria), payer_id, service_code,
    )

    return {
        "criteria": criteria,
        "policy_found": True,
        "policy_chunks": policy_chunks,
        "policy_structure_notes": criteria_data.get("policy_structure_notes", ""),
    }

def _parse_json_response(raw_text: str) -> dict:
    """
    Parse JSON from the model's response, stripping common markdown wrappers.

    Claude sometimes wraps JSON in markdown code fences even when instructed
    not to. This helper is defensive so the pipeline doesn't crash on that.
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return json.loads(cleaned.strip())
```

---

## Step 3: Retrieve Patient Clinical Data and Extract Relevant Facts

*The pseudocode calls this `retrieve_patient_facts(patient_id, criteria, diagnosis_code)`. This step pulls the patient's clinical data and extracts discrete facts that could satisfy each criterion. In production, the data comes from an EHR via FHIR, HealthLake, or a clinical data platform. For this example we accept the patient data as a dict parameter to keep the focus on the AI pattern.*

```python
def retrieve_patient_facts(
    patient_id: str,
    criteria: list,
    patient_clinical_data: dict,
) -> list:
    """
    Extract clinical facts from the patient's record, organized by criterion.

    For each criterion, the LLM examines the patient's structured data and
    unstructured notes to find facts that either support or contradict it.
    Every extracted fact has a verbatim quote from the source so downstream
    validation can verify it wasn't fabricated.

    In a real deployment, patient_clinical_data comes from HealthLake, Epic's
    FHIR API, Oracle Health, or wherever your clinical data lives. This
    example takes it as a parameter so the PHI retrieval step isn't mixed
    with the AI pipeline demo.

    Args:
        patient_id:            The patient's identifier (used for logging only).
        criteria:              List of criterion dicts from Step 2.
        patient_clinical_data: Dict with the patient's clinical info.
                               Expected keys: conditions, medications,
                               observations, procedures, notes.

    Returns:
        List of per-criterion fact sets. Each entry has criterion_id and
        a list of extracted facts with provenance.
    """
    structured_data_json = json.dumps(patient_clinical_data, indent=2, default=str)

    facts_by_criterion = []

    # One LLM call per criterion. More expensive than batching all criteria
    # into one call, but gives clean audit trails (we know exactly which
    # facts the model extracted for which criterion) and prevents the model
    # from getting confused when criteria have overlapping evidence
    # requirements. For production, you might batch when you have many
    # criteria and latency matters; start here for clarity.
    for criterion in criteria:
        criterion_id = criterion.get("criterion_id", "unknown")
        description = criterion.get("description", "")
        evidence_type = criterion.get("evidence_type", "")

        extraction_system = """You are extracting clinical facts from a patient record to assess whether they satisfy a specific coverage criterion.

Return ONLY valid JSON in this exact structure:
{
  "facts": [
    {
      "fact": "the clinical finding or observation",
      "value": "the specific clinical value (e.g., 'DAS28 score 5.8', 'methotrexate 25mg weekly for 16 weeks')",
      "date": "YYYY-MM-DD or date range when documented",
      "source": "which resource or note this came from",
      "supports": true,
      "verbatim_quote": "the EXACT text from the source (not paraphrased)"
    }
  ]
}

Critical rules:
- Only extract facts that are ACTUALLY PRESENT in the provided data. Do not infer, extrapolate, or use prior knowledge.
- The verbatim_quote must be copied character-for-character from the source. It will be verified against the source data later.
- Set supports=false for facts that contradict the criterion (e.g., a positive TB test for a criterion requiring negative TB).
- If no relevant facts exist in the patient data for this criterion, return an empty facts list."""

        user_message = f"""CRITERION: {description}
EVIDENCE TYPE REQUIRED: {evidence_type}

PATIENT CLINICAL DATA:
{structured_data_json}

Extract all facts relevant to this criterion."""

        request_body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "temperature": 0.0,
            "system": extraction_system,
            "messages": [{"role": "user", "content": user_message}],
        })

        response = bedrock_runtime.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=request_body,
        )

        response_body = json.loads(response["body"].read())
        raw_text = response_body["content"][0]["text"]
        # _parse_json_response is the shared helper defined at the end of Step 2.
        criterion_result = _parse_json_response(raw_text)

        # Assign a stable fact_id to each fact for later provenance tracking.
        # The letter will reference these IDs, and validation checks that
        # every claim in the letter maps to one of these facts.
        facts = criterion_result.get("facts", [])
        for idx, fact in enumerate(facts):
            fact["fact_id"] = f"{criterion_id}-F{idx + 1}"

        facts_by_criterion.append({
            "criterion_id": criterion_id,
            "criterion_description": description,
            "facts": facts,
        })

    total_facts = sum(len(entry["facts"]) for entry in facts_by_criterion)
    logger.info(
        "Extracted %d total facts across %d criteria for patient=%s",
        total_facts, len(criteria), patient_id,
    )
    return facts_by_criterion
```

---

## Step 4: Map Facts to Criteria and Identify Gaps

*The pseudocode calls this `map_facts_to_criteria(criteria, facts)`. For each criterion, assess whether the available facts are sufficient. If any required criterion is unmet or contradicted, flag the case as not ready for letter generation. This is the gate: don't generate letters for cases that can't succeed.*

```python
def map_facts_to_criteria(criteria: list, facts_by_criterion: list) -> dict:
    """
    Assess each criterion against the extracted facts and determine readiness.

    For each criterion, classify as SATISFIED, PARTIAL, UNMET, or CONTRADICTED.
    If any required criterion lands in UNMET or CONTRADICTED, the case isn't
    ready for letter generation. Generating a letter with known unmet criteria
    is worse than not generating one at all: it wastes the physician's review
    time and ends in a denial.

    Args:
        criteria:             List of criterion dicts from Step 2.
        facts_by_criterion:   List of fact sets from Step 3.

    Returns:
        Dict with:
        - mappings:       list of per-criterion assessments
        - ready_to_draft: True if all required criteria are satisfied or partial
        - blocking_gaps:  list of criteria blocking letter generation
    """
    # Index facts by criterion_id for quick lookup.
    facts_index = {
        entry["criterion_id"]: entry["facts"]
        for entry in facts_by_criterion
    }

    mappings = []
    blocking_gaps = []

    for criterion in criteria:
        criterion_id = criterion.get("criterion_id", "unknown")
        description = criterion.get("description", "")
        required = criterion.get("required", True)
        relevant_facts = facts_index.get(criterion_id, [])

        supporting = [f for f in relevant_facts if f.get("supports")]
        contradicting = [f for f in relevant_facts if not f.get("supports")]

        # Assessment call. Low temperature because we want consistent judgments.
        # Non-zero because there is legitimate clinical reasoning here (e.g.,
        # was a 10-week methotrexate trial "adequate" when the policy says
        # 12 weeks? A rigid yes/no misses the clinical nuance).
        assessment_system = """You are a clinical reviewer assessing whether a coverage criterion is satisfied by the available patient facts.

Return ONLY valid JSON:
{
  "status": "SATISFIED | PARTIAL | UNMET | CONTRADICTED",
  "rationale": "one or two sentences explaining the assessment",
  "key_fact_ids": ["list of fact_id values that drive the assessment"],
  "evidence_gap": "if PARTIAL or UNMET, what additional evidence would satisfy the criterion"
}

Status definitions:
- SATISFIED: the facts clearly meet the criterion
- PARTIAL: the facts partially meet the criterion but some element is missing (e.g., trial duration is short, or the date is outside the required window)
- UNMET: no facts in the record support the criterion
- CONTRADICTED: the facts directly contradict the criterion (e.g., positive TB test when criterion requires negative)"""

        user_message = f"""CRITERION: {description}
REQUIRED: {required}

SUPPORTING FACTS:
{json.dumps(supporting, indent=2)}

CONTRADICTING FACTS:
{json.dumps(contradicting, indent=2)}

Assess whether this criterion is satisfied."""

        request_body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "temperature": 0.1,
            "system": assessment_system,
            "messages": [{"role": "user", "content": user_message}],
        })

        response = bedrock_runtime.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=request_body,
        )

        response_body = json.loads(response["body"].read())
        assessment = _parse_json_response(response_body["content"][0]["text"])

        mapping_entry = {
            "criterion_id": criterion_id,
            "criterion_description": description,
            "required": required,
            "status": assessment.get("status", "UNKNOWN"),
            "rationale": assessment.get("rationale", ""),
            "key_fact_ids": assessment.get("key_fact_ids", []),
            "evidence_gap": assessment.get("evidence_gap", ""),
            "supporting_facts": supporting,
            "contradicting_facts": contradicting,
        }
        mappings.append(mapping_entry)

        if required and assessment.get("status") in ("UNMET", "CONTRADICTED"):
            blocking_gaps.append(mapping_entry)

    ready = len(blocking_gaps) == 0

    logger.info(
        "Criteria mapping: %d total, %d blocking gaps, ready_to_draft=%s",
        len(mappings), len(blocking_gaps), ready,
    )
    return {
        "mappings": mappings,
        "ready_to_draft": ready,
        "blocking_gaps": blocking_gaps,
    }
```

---

## Step 5: Retrieve Supporting Evidence for Citations

*The pseudocode calls this `retrieve_supporting_evidence(diagnosis_code, service_code, key_facts)`. Pull clinical guidelines and literature from the evidence knowledge base to cite in the letter. Critical architectural rule: every citation comes from retrieval, never from the model's training data. LLMs happily fabricate plausible-looking citations, which is a problem when a payer checks them.*

```python
def retrieve_supporting_evidence(
    diagnosis_code: str,
    service_description: str,
    mappings: list,
) -> list:
    """
    Retrieve clinical guidelines and literature supporting the requested service.

    The evidence knowledge base should contain professional society guidelines
    (ACR, ASMBS, NCCN, AHA, etc.), peer-reviewed literature, and any
    organizational treatment protocols. Each piece of content in the KB must
    have proper bibliographic metadata (author, title, journal, year, DOI,
    URL) so citations are verifiable.

    Args:
        diagnosis_code:      ICD-10 code for the supporting diagnosis.
        service_description: Human-readable name of the requested service.
        mappings:            Criteria mappings from Step 4 (used to build
                             a query that reflects the distinctive clinical
                             features of this case).

    Returns:
        List of citation dicts with text, bibliographic info, and citation_id
        for downstream provenance tracking.
    """
    # Build a query that includes the distinctive clinical features of this
    # case. A generic query ("rheumatoid arthritis treatment") pulls broad
    # literature. A specific query ("rheumatoid arthritis biologic therapy
    # after inadequate methotrexate response") pulls the guidelines that
    # actually support this specific request.
    distinctive_features = []
    for mapping in mappings:
        if mapping.get("status") == "SATISFIED":
            for fact in mapping.get("supporting_facts", [])[:2]:  # Top 2 per criterion
                value = fact.get("value", "")
                if value:
                    distinctive_features.append(value)

    query_parts = [
        f"Clinical guidelines for {service_description}",
        f"diagnosis {diagnosis_code}",
        "treatment recommendations",
    ]
    query_parts.extend(distinctive_features[:4])  # Cap to keep query focused
    query_text = ". ".join(query_parts)

    evidence_response = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=CLINICAL_EVIDENCE_KB_ID,
        retrievalQuery={"text": query_text},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": MAX_EVIDENCE_CITATIONS,
            }
        },
    )

    citations = []
    for idx, result in enumerate(evidence_response.get("retrievalResults", [])):
        content_text = result.get("content", {}).get("text", "")
        metadata = result.get("metadata", {})

        # Only include results that have proper citation metadata. Results
        # without bibliographic info are unusable for a PA letter (we can't
        # cite them). The KB ingestion pipeline is responsible for tagging
        # each document chunk with citation metadata at ingest time.
        citation_text = metadata.get("citation")
        if not citation_text:
            logger.warning(
                "Retrieved evidence chunk missing citation metadata; skipping. "
                "Check your KB ingestion pipeline."
            )
            continue

        citations.append({
            "citation_id": f"CITE-{idx + 1}",
            "citation_text": citation_text,
            "source_url": metadata.get("url", ""),
            "content": content_text,
            "relevance_score": result.get("score", 0.0),
        })

    logger.info(
        "Retrieved %d citations for diagnosis=%s service=%s",
        len(citations), diagnosis_code, service_description,
    )
    return citations
```

---

## Step 6: Generate the Letter Narrative

*The pseudocode calls this `generate_letter(case, mappings, citations, ...)`. This is the step everyone thinks is the hard part, but by now most of the work is done. All inputs are structured: criteria with satisfaction status, facts with provenance, citations with verified references. The prompt enforces grounding: use only provided facts, cite only provided references, map each claim to its source.*

```python
def generate_letter(
    case: dict,
    mappings: list,
    citations: list,
    patient_info: dict,
    provider_info: dict,
    payer_info: dict,
) -> dict:
    """
    Generate the prior auth letter narrative with full provenance.

    The model's job is prose composition, not fact retrieval. Every factual
    claim in the output must map to a fact_id from the mappings. Every
    citation must map to a citation_id from the retrieved evidence. The
    validation step (Step 7) enforces this.

    Args:
        case:          The PA case record from DynamoDB.
        mappings:      Criteria mappings from Step 4.
        citations:     Citations from Step 5.
        patient_info:  Administrative patient info (name, DOB, member ID).
        provider_info: Prescriber info (name, NPI, credentials).
        payer_info:    Payer name and contact info.

    Returns:
        Dict with:
        - letter:     the generated letter text
        - provenance: structured map of claims to source fact_ids
                      and citations used
    """
    generation_system = """You are drafting a letter of medical necessity for a prior authorization submission to a health plan's medical review team.

STRICT RULES:
1. Use ONLY the facts provided in the 'mappings' input. Do NOT introduce outside clinical information, patient details, or treatment history.
2. Every factual claim you make in the letter must reference a specific fact_id from the mappings. Track these in the provenance output.
3. Every citation you use in the letter must be one of the provided citations, referenced by citation_id. Do NOT fabricate references or add citations from your general knowledge.
4. If a required criterion is not fully satisfied, state honestly what additional documentation would strengthen the case rather than making unsupported claims.
5. Write in professional clinical prose appropriate for payer medical review. Assertive about medical necessity, but factual.

LETTER STRUCTURE (follow this order):
1. Header (to payer, from provider, re: patient and service)
2. Opening paragraph summarizing the request
3. Clinical background (diagnosis and how established, per the facts)
4. Treatment history to date (medications tried, outcomes, per the facts)
5. Clinical rationale for requested service
6. Explicit mapping to coverage criteria (one brief paragraph per criterion, stating which fact satisfies it)
7. Supporting evidence paragraph with citations
8. Closing with provider attestation

OUTPUT FORMAT:
Return ONLY valid JSON in this exact structure:
{
  "letter_text": "the full letter as a single string with appropriate line breaks",
  "provenance": {
    "factual_claims": [
      {
        "claim": "a factual assertion made in the letter",
        "source_fact_id": "the fact_id from the mappings that supports this claim",
        "asserted_value": "the specific value claimed in the letter"
      }
    ],
    "citations_used": [
      {"citation_id": "CITE-N from the citations list", "context": "brief note on where/why cited"}
    ]
  }
}"""

    user_message = f"""CASE:
{json.dumps({
    "service_code": case.get("service_code"),
    "service_description": case.get("service_description"),
    "diagnosis_code": case.get("diagnosis_code"),
    "urgency": case.get("urgency"),
}, indent=2)}

PATIENT INFO (administrative):
{json.dumps(patient_info, indent=2, default=str)}

REQUESTING PROVIDER:
{json.dumps(provider_info, indent=2)}

PAYER:
{json.dumps(payer_info, indent=2)}

COVERAGE CRITERIA AND FACT MAPPING:
{json.dumps(mappings, indent=2, default=str)}

AVAILABLE CITATIONS:
{json.dumps(citations, indent=2)}

Generate the letter of medical necessity."""

    # Slightly higher temperature than extraction steps because we want
    # natural prose variation. Too low and the letter reads as mechanical.
    # Too high and the model may drift from the grounding constraints.
    request_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 6000,
        "temperature": 0.2,
        "system": generation_system,
        "messages": [{"role": "user", "content": user_message}],
    })

    response = bedrock_runtime.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=request_body,
    )

    response_body = json.loads(response["body"].read())
    raw_text = response_body["content"][0]["text"]
    result = _parse_json_response(raw_text)

    letter_text = result.get("letter_text", "")
    provenance = result.get("provenance", {})

    # Persist the draft for audit. Every letter the system ever generates
    # should be retrievable years later along with the inputs that produced
    # it. HIPAA retention is typically 6 years minimum, sometimes longer
    # depending on state law and payer contract.
    draft_key = f"letter-drafts/{case['case_id']}/draft-{uuid.uuid4().hex[:8]}.json"
    draft_payload = {
        "case_id": case["case_id"],
        "letter_text": letter_text,
        "provenance": provenance,
        "inputs": {
            "mappings": mappings,
            "citations": citations,
            "patient_info": patient_info,
            "provider_info": provider_info,
            "payer_info": payer_info,
        },
        "generated_at": datetime.datetime.now(timezone.utc).isoformat(),
    }
    s3_client.put_object(
        Bucket=PA_BUCKET,
        Key=draft_key,
        Body=json.dumps(draft_payload, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
        # ServerSideEncryption is assumed to be set at the bucket default
        # with an SSE-KMS customer-managed key. If not:
        # ServerSideEncryption="aws:kms",
        # SSEKMSKeyId="your-cmk-arn",
    )

    logger.info(
        "Generated letter for case=%s (%d factual claims, %d citations used)",
        case["case_id"],
        len(provenance.get("factual_claims", [])),
        len(provenance.get("citations_used", [])),
    )

    return {
        "letter_text": letter_text,
        "provenance": provenance,
        "draft_key": draft_key,
    }
```

---

## Step 7: Validate Claims Against Sources

*The pseudocode calls this `validate_letter(letter, provenance, inputs)`. Before the letter reaches the physician, every factual claim gets traced back to a source fact. Every citation gets matched to the retrieved evidence. This is the hallucination detector. A letter with fabricated facts is a legal liability, not just a denied claim.*

```python
def validate_letter(
    case_id: str,
    letter_result: dict,
    mappings: list,
    citations: list,
) -> dict:
    """
    Verify that every factual claim and citation traces to an authorized source.

    This is a post-generation check. Despite the prompt rules in Step 6, LLMs
    sometimes paraphrase facts in ways that distort them, or inject small
    details ('the patient has been stable for six months') that weren't in
    the input data. This step catches those.

    Args:
        case_id:       The PA case identifier.
        letter_result: The output from generate_letter.
        mappings:      The criteria mappings used for generation.
        citations:     The citations used for generation.

    Returns:
        Dict with validation status, validation_rate, and any unverified items.
    """
    provenance = letter_result.get("provenance", {})
    factual_claims = provenance.get("factual_claims", [])
    citations_used = provenance.get("citations_used", [])

    # Build a flat index of all valid fact_ids from the mappings.
    valid_fact_ids = set()
    fact_values_by_id = {}
    for mapping in mappings:
        for fact in mapping.get("supporting_facts", []):
            fact_id = fact.get("fact_id")
            if fact_id:
                valid_fact_ids.add(fact_id)
                fact_values_by_id[fact_id] = fact.get("value", "")
        for fact in mapping.get("contradicting_facts", []):
            fact_id = fact.get("fact_id")
            if fact_id:
                valid_fact_ids.add(fact_id)
                fact_values_by_id[fact_id] = fact.get("value", "")

    valid_citation_ids = {c["citation_id"] for c in citations}

    # Check each factual claim against the source fact index.
    unverified_claims = []
    for claim in factual_claims:
        source_fact_id = claim.get("source_fact_id")
        if source_fact_id not in valid_fact_ids:
            # The model cited a fact_id that doesn't exist in our inputs.
            # This is either a fabrication or a broken reference.
            unverified_claims.append({
                "claim": claim.get("claim"),
                "issue": "source_fact_id not found in inputs",
                "cited_id": source_fact_id,
            })
            continue

        # More subtle check: did the model distort the fact's value? A weak
        # string-similarity check can catch gross paraphrase drift. A stronger
        # check would use semantic similarity (another embedding call) but
        # that adds cost. Start with the simple check.
        asserted = (claim.get("asserted_value") or "").lower()
        true_value = fact_values_by_id.get(source_fact_id, "").lower()
        if asserted and true_value and asserted not in true_value and true_value not in asserted:
            # The asserted value doesn't overlap with the source value at all.
            # Flag for review. Don't auto-fail; paraphrase can be legitimate
            # (e.g., "high disease activity" for a DAS28 of 5.8).
            unverified_claims.append({
                "claim": claim.get("claim"),
                "issue": "asserted_value differs substantively from source fact",
                "cited_id": source_fact_id,
                "source_value": fact_values_by_id.get(source_fact_id, ""),
                "asserted_value": claim.get("asserted_value"),
            })

    # Check citations.
    unverified_citations = []
    for cite in citations_used:
        cid = cite.get("citation_id")
        if cid not in valid_citation_ids:
            unverified_citations.append({
                "citation_id": cid,
                "issue": "citation_id not found in retrieved evidence",
            })

    total_claims = len(factual_claims) or 1  # avoid division by zero
    verified_claims = total_claims - len(unverified_claims)
    validation_rate = verified_claims / total_claims

    if validation_rate >= MIN_VALIDATION_RATE_FOR_REVIEW and not unverified_citations:
        status = "APPROVED_FOR_REVIEW"
    else:
        status = "REQUIRES_REGENERATION"

    # Update the case record. In production, REQUIRES_REGENERATION would
    # trigger a retry with adjusted prompting, or an escalation to a human
    # reviewer if retries don't resolve it.
    cases_table = dynamodb.Table(PA_CASES_TABLE)
    cases_table.update_item(
        Key={"case_id": case_id},
        UpdateExpression=(
            "SET #status = :status, "
            "validation_rate = :vr, "
            "unverified_claims = :uc, "
            "unverified_citations = :ucit, "
            "draft_key = :dk, "
            "letter_ready_at = :lra"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": status,
            # DynamoDB needs Decimal for numerics, not float.
            ":vr": Decimal(str(round(validation_rate, 4))),
            ":uc": unverified_claims,
            ":ucit": unverified_citations,
            ":dk": letter_result.get("draft_key", ""),
            ":lra": datetime.datetime.now(timezone.utc).isoformat(),
        },
    )

    logger.info(
        "Validation for case=%s: status=%s rate=%.2f unverified_claims=%d",
        case_id, status, validation_rate, len(unverified_claims),
    )

    return {
        "status": status,
        "validation_rate": validation_rate,
        "unverified_claims": unverified_claims,
        "unverified_citations": unverified_citations,
    }
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This runs all seven steps sequentially for one PA case. In production, each step becomes a Step Functions state with its own retry policy and error handling.

```python
def process_pa_request(
    request: dict,
    patient_clinical_data: dict,
    patient_info: dict,
    provider_info: dict,
    payer_info: dict,
) -> dict:
    """
    Run the full PA letter generation pipeline for one request.

    Steps (matching the Recipe 2.4 pseudocode):
      1. Receive and initialize the case
      2. Retrieve policy and extract criteria
      3. Extract patient facts per criterion
      4. Map facts to criteria
      5. Retrieve supporting evidence
      6. Generate the letter
      7. Validate claims

    Args:
        request:               PA request dict (see receive_pa_request).
        patient_clinical_data: Patient's clinical record snapshot
                               (in production, retrieved from EHR/HealthLake).
        patient_info:          Administrative patient info for the letter.
        provider_info:         Prescribing provider details.
        payer_info:            Payer name and contact info.

    Returns:
        Dict with case_id, status, and the letter draft if generation succeeded.
    """
    start = time.time()

    # Step 1
    print(f"Step 1: Receiving PA request for service {request['service_code']}...")
    case_id = receive_pa_request(request)
    print(f"  case_id: {case_id}")

    # Step 2
    print("Step 2: Retrieving payer policy and extracting criteria...")
    policy_result = retrieve_and_extract_criteria(
        payer_id=request["payer_id"],
        service_code=request["service_code"],
        diagnosis_code=request["diagnosis_code"],
    )
    if not policy_result["policy_found"]:
        print("  No policy found. Aborting.")
        return {"case_id": case_id, "status": "NO_POLICY_FOUND"}
    criteria = policy_result["criteria"]
    print(f"  Extracted {len(criteria)} criteria")

    # Step 3
    print("Step 3: Extracting patient facts per criterion...")
    facts_by_criterion = retrieve_patient_facts(
        patient_id=request["patient_id"],
        criteria=criteria,
        patient_clinical_data=patient_clinical_data,
    )
    total_facts = sum(len(entry["facts"]) for entry in facts_by_criterion)
    print(f"  Extracted {total_facts} facts total")

    # Step 4
    print("Step 4: Mapping facts to criteria...")
    mapping_result = map_facts_to_criteria(criteria, facts_by_criterion)
    print(
        f"  {len(mapping_result['mappings'])} criteria assessed, "
        f"ready_to_draft={mapping_result['ready_to_draft']}"
    )

    if not mapping_result["ready_to_draft"]:
        # Don't generate a letter we know will fail. Surface the gaps to
        # the physician so they can decide: document more, pursue an alternative
        # service, or accept the likely denial.
        print(f"  Blocking gaps: {len(mapping_result['blocking_gaps'])}")
        cases_table = dynamodb.Table(PA_CASES_TABLE)
        cases_table.update_item(
            Key={"case_id": case_id},
            UpdateExpression="SET #status = :s, blocking_gaps = :bg",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":s": "BLOCKED_INSUFFICIENT_EVIDENCE",
                ":bg": mapping_result["blocking_gaps"],
            },
        )
        return {
            "case_id": case_id,
            "status": "BLOCKED_INSUFFICIENT_EVIDENCE",
            "blocking_gaps": mapping_result["blocking_gaps"],
        }

    # Step 5
    print("Step 5: Retrieving supporting evidence...")
    citations = retrieve_supporting_evidence(
        diagnosis_code=request["diagnosis_code"],
        service_description=request.get("service_description", ""),
        mappings=mapping_result["mappings"],
    )
    print(f"  Retrieved {len(citations)} citations")

    # Step 6
    print("Step 6: Generating letter...")
    case_record = {
        "case_id": case_id,
        "service_code": request["service_code"],
        "service_description": request.get("service_description", ""),
        "diagnosis_code": request["diagnosis_code"],
        "urgency": request.get("urgency", "standard"),
    }
    letter_result = generate_letter(
        case=case_record,
        mappings=mapping_result["mappings"],
        citations=citations,
        patient_info=patient_info,
        provider_info=provider_info,
        payer_info=payer_info,
    )
    print(f"  Letter generated ({len(letter_result['letter_text'])} chars)")

    # Step 7
    print("Step 7: Validating claims against sources...")
    validation = validate_letter(
        case_id=case_id,
        letter_result=letter_result,
        mappings=mapping_result["mappings"],
        citations=citations,
    )
    print(
        f"  status={validation['status']} "
        f"rate={validation['validation_rate']:.2%}"
    )

    elapsed_ms = int((time.time() - start) * 1000)
    print(f"\nDone. Processing time: {elapsed_ms}ms")

    return {
        "case_id": case_id,
        "status": validation["status"],
        "letter_text": letter_result["letter_text"],
        "draft_key": letter_result["draft_key"],
        "validation_rate": validation["validation_rate"],
        "unverified_claims": validation["unverified_claims"],
        "processing_time_ms": elapsed_ms,
    }

# --- Example usage ---
if __name__ == "__main__":
    # All data below is SYNTHETIC. Do not use real patient data in development.
    # Any resemblance to real patients, providers, or payers is coincidental.

    sample_request = {
        "patient_id": "PAT-SYNTH-00042",
        "payer_id": "PAYER-EXAMPLE-BCBS",
        "service_code": "J0135",  # Adalimumab HCPCS code
        "service_description": "Adalimumab (Humira) 40mg SQ every other week",
        "diagnosis_code": "M05.79",  # Seropositive RA, multiple sites
        "provider_id": "PRV-00891",
        "urgency": "standard",
    }

    # In production this comes from HealthLake / EHR FHIR queries. Structured
    # data plus any clinical notes relevant to the criteria.
    sample_patient_data = {
        "conditions": [
            {
                "code": "M05.79",
                "display": "Seropositive rheumatoid arthritis",
                "onset_date": "2024-11-03",
                "evidence": "RF 142 IU/mL (ref <14), anti-CCP >250 (ref <20)",
            }
        ],
        "medications": [
            {
                "name": "methotrexate",
                "dose": "25mg weekly",
                "start_date": "2025-01-15",
                "end_date": "2025-05-20",
                "status": "discontinued_inadequate_response",
            }
        ],
        "observations": [
            {
                "code": "DAS28",
                "value": 5.8,
                "date": "2025-05-10",
                "interpretation": "high_disease_activity",
            },
            {
                "code": "QuantiFERON-TB",
                "value": "negative",
                "date": "2026-02-15",
            },
        ],
        "notes_excerpts": [
            "Patient with 18 weeks of methotrexate 25mg weekly with persistent "
            "synovitis and DAS28 5.8 indicating high disease activity. QuantiFERON "
            "negative on 2026-02-15. Plan: initiate adalimumab per ACR guidelines."
        ],
    }

    sample_patient_info = {
        "name": "Jane Doe",  # Synthetic
        "dob": "1972-04-15",
        "member_id": "SYN123456789",
    }

    sample_provider_info = {
        "name": "Dr. Example Rheumatologist, MD",
        "npi": "1234567890",
        "specialty": "Rheumatology",
        "license": "MD-XX-00000",
    }

    sample_payer_info = {
        "name": "Blue Cross Blue Shield of Example State",
        "review_department": "Medical Review Department",
        "fax": "555-555-5555",
    }

    result = process_pa_request(
        request=sample_request,
        patient_clinical_data=sample_patient_data,
        patient_info=sample_patient_info,
        provider_info=sample_provider_info,
        payer_info=sample_payer_info,
    )

    print("\n" + "=" * 60)
    print("RESULT SUMMARY:")
    print("=" * 60)
    print(json.dumps(
        {
            "case_id": result["case_id"],
            "status": result["status"],
            "validation_rate": result.get("validation_rate"),
            "processing_time_ms": result.get("processing_time_ms"),
            "unverified_claims_count": len(result.get("unverified_claims", [])),
            "draft_key": result.get("draft_key"),
        },
        indent=2,
        default=str,
    ))
```

---

## The Gap Between This and Production

Run this end-to-end against synthetic inputs and you'll see the full pattern: policy extracted, facts mapped, letter generated, claims validated. The distance between this and a real deployment is substantial. Here's where the gap lives.

**Payer policy ingestion is where the project actually succeeds or fails.** This example assumes the payer policies knowledge base is populated. Populating and maintaining it is the single biggest operational challenge in PA automation. Most payers do not expose policies via API. You will be writing scrapers for provider portals, handling authentication (which sometimes requires per-staff credentials), dealing with portal changes that break your scrapers, and pulling updated PDFs through Textract into your KB on a recurring schedule. Plan for a dedicated person owning policy ingestion, especially past 20 payer contracts. When the knowledge base goes stale, letters cite outdated criteria and denials climb. The AI part works; the policy freshness problem is what kills projects.

**EHR integration for patient data retrieval.** This example accepts `patient_clinical_data` as a parameter. In reality, getting structured clinical data out of Epic, Oracle Health (Cerner), Meditech, Allscripts, or athenahealth in real time involves FHIR R4 APIs with vendor-specific quirks, inconsistent resource support, and authentication flows that differ per vendor. SMART on FHIR helps for the embedded workflow, but coverage varies. Budget 40-60% of your implementation timeline for EHR integration alone. A working AI pipeline with no data in front of it is useless.

**Physician review UI.** The pipeline outputs a draft letter plus unverified claims. A physician has to review it, edit if needed, and sign. This is where time savings evaporate if the UI is bad. Open a separate web app, log in, read the letter, sign it, upload to the payer portal? You just lost the savings. The review has to happen inside the physician's normal workflow, ideally embedded via SMART on FHIR or an EHR-native extension. Surface the claims with their source facts visible so physicians can audit quickly. Make the sign-off meaningful but not tedious. This is at least as much engineering work as the pipeline itself.

**Step Functions orchestration.** The sequential function here is a learning artifact. A real pipeline uses Step Functions to orchestrate: retrievals in parallel (policy and patient data can fetch concurrently), per-step retries with different backoff policies, pause-for-human-review states, and payer-specific branches at submission time. Step Functions also gives you observability: ops staff can see exactly where a case is stuck. Redrive failed executions without rebuilding state.

**Error handling and dead letter queues.** None of the code here handles partial failures, malformed model outputs that break JSON parsing, or transient Bedrock throttling past the adaptive retries. A production pipeline wraps each step in try/except, publishes failures to a DLQ (SQS), and alerts on queue depth. For the JSON parsing specifically, build a repair loop: if the first parse fails, send the raw output back to the model with "fix this JSON" instructions before giving up. Models are usually good at self-correction.

**Hallucination mitigation beyond validation.** The validation step catches references to non-existent facts. It doesn't catch paraphrase drift (subtle shifts in meaning) reliably. For higher safety, add a second-pass semantic check: embed each factual claim and each source fact, compute similarity, flag claims below a similarity threshold for physician review. This is extra latency and cost but catches a class of issues that string matching misses. For truly high-stakes letters (oncology, rare diseases, appeals), consider a third-pass review by a different model with different training to catch biases in the primary model.

**PHI minimization in prompts.** The prompts here include patient_info (name, DOB, member ID) and full clinical data. Bedrock under BAA is HIPAA-eligible, so this is compliant, but the minimum-necessary principle argues for sending less. Consider: redact names, replace with pronouns or role labels ("the patient") before sending to the model, then substitute back the real names when formatting the final letter. You lose nothing in letter quality (the model doesn't need the name to compose the argument) and reduce your PHI exposure surface.

**Appeals workflow.** When the initial PA is denied, the appeal needs a different approach: address the specific denial reasons, cite precedent decisions if available, present additional evidence. Build an appeal workflow as a sibling to this pipeline, not a variant. It has different inputs (the denial rationale from the payer), different retrieval needs (case law, appeal precedents), and different rhetorical goals.

**Submission automation.** The example ends at a validated draft. Actual submission to the payer varies: PDF portal upload (most common), fax (shockingly still common), HL7 DaVinci PAS for payers that support FHIR-based PA, or email with attachments for small payers. Build the PDF-over-portal path first since it works for virtually every payer, then add FHIR PAS for the handful of early adopters. Submission status tracking feeds back into the case record so the ops team knows what's approved, denied, or pending.

**Attestation and provider accountability.** Every letter is submitted under a physician's name and license. They are legally responsible for its contents. The review step is load-bearing. Design the UI to make the review meaningful (surface the claims and sources) without being unusable (don't force re-reading every word). Track who signed which letter, when, and what (if anything) they edited. Audit trails matter when a payer disputes a submission.

**Denial rate measurement.** The metric that matters is not "letter quality" (subjective) but payer approval rate. Track approval rate for AI-generated letters vs. hand-composed letters for the same service and payer combination. If generated letters get denied more, something is wrong with your criteria extraction, your fact mapping, or your prose. If they get approved at the same rate, you've saved time. If they get approved at a higher rate, your structured criteria mapping is outperforming unstructured human writing. All three outcomes happen, and you need the measurement to know which one you're in.

**VPC, encryption, and audit.** This example makes API calls without VPC configuration. A production Lambda runs in private subnets with VPC endpoints for S3, Bedrock Runtime, Bedrock Agent Runtime (yes, both endpoints), KMS, Textract, HealthLake, CloudWatch Logs, CloudWatch Monitoring, Secrets Manager, Step Functions, and DynamoDB. S3 buckets use SSE-KMS with customer-managed keys. DynamoDB uses a CMK for encryption at rest. If Bedrock model-invocation-logging is enabled (recommended for quality monitoring), the log destination must be KMS-encrypted and access-controlled equivalently to your primary PHI stores, since logged prompts contain extracted clinical facts. Every Bedrock invocation and every KB retrieval gets logged to CloudTrail with data events enabled, because an audit will eventually ask "what did the model see for case X?" and you need to answer that definitively. Key lifecycle policies and rotation belong in your security design from day one, not retrofitted.

**Testing with synthetic cases.** There are no tests here. A production pipeline has: unit tests for validation logic (hallucination detection must be reliable), integration tests with synthetic patient cases covering your top 20 services by volume, regression tests ensuring known-good policies still produce correct criteria extractions after prompt changes, and load tests validating throughput against realistic burst patterns (mornings, end-of-clinic). Generate synthetic patient records using tools like Synthea so the test corpus never contains real PHI.

**Cost monitoring.** At ~$1.50-2.50 per letter (22+ Bedrock calls for a typical 10-criterion PA) and a mid-sized practice processing 600 letters per week, you're looking at $900-1,500/week in direct model costs. Meaningful enough to want visibility. Set CloudWatch billing alarms on Bedrock usage, track cost per case in the DynamoDB record, and watch for runaway loops (validation failing, triggering regeneration, triggering validation failing) that multiply the cost per case. One buggy prompt can 10x your costs overnight if you're not watching.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 2.4: Prior Authorization Letter Generation](chapter02.04-prior-auth-letter-generation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
