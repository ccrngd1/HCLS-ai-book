# Recipe 2.6: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 2.6. It shows one way you could translate those clinical note summarization concepts into working Python using Amazon Bedrock, Amazon Comprehend Medical, S3, and DynamoDB. It is not production-ready. There's no EHR integration, no HealthLake FHIR pulls, no Step Functions orchestration, no clinician review UI, no provenance-link rendering, and no real parallelism for chunk extraction. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd wire up to a health system on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the nine pseudocode steps from the main recipe: receive the summary request, retrieve source documents, chunk and preprocess, extract per-chunk facts (parallelizable), aggregate and deduplicate, apply the must-include checklist, generate section-wise prose, validate claims against the aggregated facts, then render and archive with provenance.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` (for per-chunk extraction and prose generation models)
- `bedrock:ApplyGuardrail` (if you configure a Bedrock Guardrail with contextual grounding, which you should for clinician-facing summaries)
- `comprehendmedical:DetectEntitiesV2` (for the negation-aware cross-check on medications, conditions, and allergies)
- `s3:GetObject`, `s3:PutObject` (for source snapshots, per-chunk extractions, aggregations, and final summaries)
- `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:UpdateItem` (for summary state and provenance maps)
- `healthlake:SearchWithGet`, `healthlake:ReadResource` (if HealthLake is your FHIR store; this example takes clinical data as a parameter to keep the AI pattern clear)
- `states:StartExecution`, `states:SendTaskSuccess` (if you wire this into Step Functions, which you should for anything real)
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` (for CloudWatch Logs)

You also need model access enabled in the Bedrock console. This pipeline uses two model tiers: a smaller, cheaper model for per-chunk extraction and a stronger model for the final prose generation where section structure, attribution, and preserved negations all matter. Extraction is a narrow task where a Haiku-class model earns its keep; generation benefits from a Sonnet-class model. Scope `bedrock:InvokeModel` to specific model ARNs in production, not a wildcard. The tutorial-level permissions below are fine for learning and will fail any serious IAM review.

One thing worth knowing upfront: Bedrock model IDs change over time and the set available in your region depends on your account's model access. In many regions, cross-region inference profiles are now the recommended path (IDs prefixed with `us.` or `eu.`). The IDs in this example are reasonable defaults at the time of writing; verify in the Bedrock console and adjust for your region before running.

Another thing worth knowing: Comprehend Medical's per-call limit for `DetectEntitiesV2` is enforced in bytes, not characters. If you pass multilingual or heavily-accented clinical text, encode to utf-8 and slice by byte length before the call. The code below handles that explicitly because getting this wrong produces confusing 400 errors on some inputs and silent truncation on others.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, chunk sizing, validation thresholds, must-include checklists, and the S3/DynamoDB resource names are the knobs you'll change most often between environments.

```python
import json
import logging
import re
import time
import uuid
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records to CloudWatch
# Logs Insights for query-friendly analysis. Never log PHI: no patient names,
# no MRNs, no note content, no generated summary bodies. The audit trail for
# summaries themselves lives in S3 with access-controlled retrieval.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles Bedrock throttling. Summarization is bursty because
# shift changes and discharge times cluster. Adaptive mode uses exponential
# backoff with jitter so retry storms don't pile on during those bursts.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
# Two Bedrock endpoints matter:
#   bedrock-runtime: model inference (invoke_model). What we use below.
#   bedrock-agent-runtime: knowledge base retrieval. Not used here since
#   clinical note summarization is encounter or patient scoped (no KB).
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
comprehend_medical = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# --- Model Configuration ---
# Two tiers. Extraction is a well-bounded per-chunk task where a smaller model
# is usually sufficient. Generation is where section structure, specialty
# emphasis, attribution of consult recommendations, and (critically)
# preservation of negations all matter, so use a capable model.
#
# If your region requires cross-region inference, use the inference profile ID:
#   e.g., "us.anthropic.claude-3-5-haiku-20241022-v1:0"
# TODO: verify the exact model IDs available in your region and account.
EXTRACTION_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"
GENERATION_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# Optional Bedrock Guardrail for the generation step. Configure one in the
# Bedrock console with the contextual grounding check enabled; for clinician-
# facing summaries the grounding check is the feature that matters most. Set
# a high threshold (0.85+) to reject responses that drift from the aggregated
# facts. Leaving these None means no guardrail is applied. Don't ship without
# this in production.
GUARDRAIL_ID = None        # e.g., "abc123xyz"
GUARDRAIL_VERSION = None   # e.g., "DRAFT" or a numbered version

# --- Storage Configuration ---
# One bucket for source snapshots, per-chunk extractions, aggregations, and
# final summaries. In production these are typically separate prefixes or
# buckets with different lifecycle policies: intermediates purged at 30-90
# days, final summaries retained 6+ years per HIPAA requirements.
SUMMARIES_BUCKET = "your-clinical-summaries-bucket"  # Replace with your bucket

# DynamoDB tables. In production, use separate tables for request state and
# the provenance map, with GSIs for access patterns (by patient, by requesting
# user, by status). Keeping them separate here so the shapes stay obvious.
SUMMARY_REQUESTS_TABLE = "summary-requests"        # Partition key: summary_id
SUMMARY_PROVENANCE_TABLE = "summary-provenance"    # Partition key: summary_id

# --- Pipeline Tuning ---
# Target tokens per chunk for the extraction step. Too small and you make
# too many calls; too large and extraction quality drops on the middle
# content. 3000 is a reasonable balance for Haiku-class models. Tune per
# model family if you change models.
TARGET_CHUNK_TOKENS = 3000

# Comprehend Medical's DetectEntitiesV2 has a per-call limit enforced in
# bytes (~20,000 for synchronous calls). Leave headroom because utf-8
# encoding can expand character counts for non-ASCII text.
COMPREHEND_MEDICAL_MAX_BYTES = 19500

# Minimum semantic-overlap threshold for validating claims that aren't
# exact numeric matches. The validator falls back to substring and token
# overlap; production systems should add embedding-based similarity.
MIN_CLAIM_OVERLAP = 0.6

# Max attempts at the generation + validation loop. If we can't produce a
# validated summary after this many tries, escalate for clinician review
# rather than loop forever.
MAX_GENERATION_ATTEMPTS = 3

# Must-include categories per use case. The aggregation step populates
# these from structured FHIR data; the checklist enforces that the final
# summary reflects them. Missing a category is a pipeline failure, not an
# acceptable content absence. Content absence gets a "none documented"
# explicit statement instead.
MUST_INCLUDE_BY_USE_CASE = {
    "handoff": [
        "allergies", "active_problems", "current_medications",
        "code_status", "recent_critical_events", "active_devices_lines",
        "consult_recs",
    ],
    "consult": [
        "allergies", "active_problems", "current_medications",
        "relevant_history",
    ],
    "pre_visit": [
        "allergies", "active_problems", "current_medications",
        "recent_labs",
    ],
    "discharge_summary": [
        "admission_reason", "hospital_course", "discharge_meds",
        "discharge_instructions", "follow_up",
    ],
}

# Section headers per use case. Drives the final-generation prompt. Order
# matters; clinicians scan top-down and expect predictable layout.
SECTIONS_BY_USE_CASE = {
    "handoff": [
        "one_liner", "active_issues", "medications", "allergies",
        "code_status", "recent_significant_events", "pending_workup",
        "consults_and_recs", "devices_and_lines", "disposition_plan",
    ],
    "consult": [
        "one_liner", "reason_for_consult", "relevant_history",
        "active_medications", "recent_findings", "allergies",
    ],
    "pre_visit": [
        "one_liner", "active_problems", "medications", "allergies",
        "recent_labs", "interval_changes",
    ],
    "discharge_summary": [
        "admission_reason", "hospital_course", "discharge_diagnoses",
        "discharge_meds", "follow_up", "discharge_instructions",
    ],
}

# Specialty emphasis hints. Drive prompt instructions for which facts to
# foreground. Kept short on purpose; each specialty lead should own and
# iterate their own template, and templates evolve with clinician feedback.
SPECIALTY_EMPHASIS = {
    "hospitalist": (
        "Balance all active issues. No particular specialty dominance. "
        "Problem-oriented structure with one line per active issue."
    ),
    "cardiology": (
        "Foreground cardiac history, current rhythm, troponin trend, BNP "
        "trend, ejection fraction if recent, anticoagulation status."
    ),
    "nephrology": (
        "Foreground baseline and current creatinine, fluid status, "
        "nephrotoxic medications, renal dosing notes, dialysis status."
    ),
    "oncology": (
        "Foreground cancer diagnosis, staging, treatment history, recent "
        "imaging response, cytopenias, and supportive care issues."
    ),
    "general": (
        "Balanced summary for a general clinician audience. Cover active "
        "problems comprehensively; no specialty dominance."
    ),
}
```

---

## Step 1: Receive the Summary Request and Resolve Context

*The pseudocode calls this `receive_summary_request(request)`. In production, a clinician triggers a summary from inside the EHR (sidebar button, handoff tool, pre-visit review) or an EventBridge rule fires on admission or shift-change. The request carries patient, scope, requesting user, specialty, use case, and format. This step authorizes, logs the access, and persists initial state.*

```python
def receive_summary_request(request: dict) -> str:
    """
    Initialize a new summary case and return the summary_id for downstream processing.

    The request is the trigger for the entire pipeline. We persist the initial
    state immediately so that if any later step fails, we have a record of
    what was requested and by whom. That record is part of the audit trail
    because summaries influence clinical decisions.

    Args:
        request: Dict with request details. Expected keys:
                 - patient_id:           FHIR Patient ID
                 - scope:                "current_encounter" | "last_6_months" | "all_time"
                 - encounter_id:         required if scope == "current_encounter"
                 - requesting_user:      user identity from the calling application
                 - requesting_specialty: "hospitalist" | "cardiology" | "nephrology" | ...
                 - use_case:             "handoff" | "consult" | "pre_visit" | "discharge_summary"
                 - format:               "narrative" | "problem_oriented" | "sbar" | "ap_only"
                 - destination:          "ehr_sidebar" | "handoff_tool" | "pdf"

    Returns:
        The generated summary_id (a UUID string).
    """
    summary_id = str(uuid.uuid4())
    now = datetime.datetime.now(timezone.utc)

    # Authorization check. In production, this calls into the EHR's context
    # or your internal ACL to confirm the user has access to this patient.
    # Stubbed here; never ship this as an auto-approve.
    if not _user_has_access(request["requesting_user"], request["patient_id"]):
        logger.warning(
            "Access denied for user=%s patient=%s",
            request["requesting_user"], request["patient_id"],
        )
        raise PermissionError("User lacks access to this patient's records")

    summary_record = {
        "summary_id": summary_id,
        "status": "INITIATED",
        "patient_id": request["patient_id"],
        "scope": request.get("scope", "current_encounter"),
        "encounter_id": request.get("encounter_id"),
        "requesting_user": request["requesting_user"],
        "requesting_specialty": request.get("requesting_specialty", "general"),
        "use_case": request.get("use_case", "handoff"),
        "format": request.get("format", "problem_oriented"),
        "destination": request.get("destination", "ehr_sidebar"),
        "requested_at": now.isoformat(),
    }

    requests_table = dynamodb.Table(SUMMARY_REQUESTS_TABLE)
    requests_table.put_item(Item=summary_record)

    # In production this is where you'd kick off a Step Functions execution.
    # That gives you per-step retries, a parallel Map state for chunk
    # extraction, a validation-failure regeneration loop, and observability
    # into stuck cases. Keeping it sequential here for clarity.
    #
    # stepfunctions_client = boto3.client("stepfunctions")
    # stepfunctions_client.start_execution(
    #     stateMachineArn=SUMMARIZATION_STATE_MACHINE_ARN,
    #     name=f"summary-{summary_id}",
    #     input=json.dumps({"summary_id": summary_id}),
    # )

    logger.info(
        "Initialized summary %s for patient=%s use_case=%s specialty=%s",
        summary_id, request["patient_id"],
        request.get("use_case"), request.get("requesting_specialty"),
    )
    return summary_id


def _user_has_access(user_id: str, patient_id: str) -> bool:
    """
    Stub for the authorization check. Replace with a call into the EHR's
    context-of-care API or your internal ACL. Never return True by default
    in production: access control is a compliance requirement, not a nice-to-have.
    """
    # Example pattern (not executed): call EHR's authorization endpoint,
    # or look up a break-the-glass record, or check a care-team membership
    # table. Do NOT pretend to authorize in a real deployment.
    return True
```

---

## Step 2: Retrieve Source Documents

*The pseudocode calls this `retrieve_source_documents(patient_id, scope, encounter_id)`. In production, this queries HealthLake (or the EHR's FHIR API) for DocumentReferences in scope plus the always-needed structured resources: AllergyIntolerance, Condition, MedicationRequest, code-status observations. For this example we accept the retrieved data as a parameter to keep the focus on the AI pattern and snapshot it to S3 for audit.*

```python
def retrieve_source_documents(
    summary_id: str,
    patient_id: str,
    scope: str,
    encounter_id: str | None,
    retrieved_clinical_data: dict,
) -> dict:
    """
    Gather everything needed to generate a clinical summary.

    Scope narrows the note set to what's relevant for the use case. Narrow
    scope keeps latency and cost down and satisfies HIPAA's minimum-necessary
    principle. Allergies, active problems, and current meds are pulled
    regardless of scope; they belong in every summary.

    Args:
        summary_id:              The summary identifier (for audit logging).
        patient_id:              The patient's FHIR ID.
        scope:                   current_encounter | last_6_months | all_time.
        encounter_id:            Required when scope == "current_encounter".
        retrieved_clinical_data: Dict of already-retrieved FHIR resources.
                                 Expected keys: notes (list of dicts),
                                 allergies (list), active_problems (list),
                                 current_meds (list), code_status (list).

    Returns:
        Dict with the clinical data and an S3 pointer to the source snapshot.
    """
    # In production, this is where the HealthLake calls live. Rough shapes:
    #
    # healthlake_client = boto3.client("healthlake")
    # note_filter = {"subject": patient_id}
    # if scope == "current_encounter":
    #     note_filter["encounter"] = encounter_id
    # elif scope == "last_6_months":
    #     cutoff = (now - timedelta(days=180)).date().isoformat()
    #     note_filter["date"] = f"ge{cutoff}"
    # notes = healthlake_client.search_with_get(
    #     DatastoreId=HEALTHLAKE_DATASTORE_ID,
    #     ResourceType="DocumentReference",
    #     SearchParameters=_format_fhir_search_params(note_filter),
    # )
    # Similar calls for AllergyIntolerance, Condition, MedicationRequest,
    # Observation (code status).
    notes = retrieved_clinical_data.get("notes", [])
    allergies = retrieved_clinical_data.get("allergies", [])
    active_problems = retrieved_clinical_data.get("active_problems", [])
    current_meds = retrieved_clinical_data.get("current_meds", [])
    code_status_observations = retrieved_clinical_data.get("code_status", [])

    # Snapshot the entire source set. This is the "what did the summary see?"
    # record. A clinician who acted on a summary may need to audit the input
    # weeks later; the snapshot makes that possible.
    snapshot = {
        "summary_id": summary_id,
        "patient_id": patient_id,
        "scope": scope,
        "encounter_id": encounter_id,
        "retrieved_at": datetime.datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "allergies": allergies,
        "active_problems": active_problems,
        "current_meds": current_meds,
        "code_status_observations": code_status_observations,
    }
    snapshot_key = f"source-snapshots/{summary_id}/source.json"
    s3_client.put_object(
        Bucket=SUMMARIES_BUCKET,
        Key=snapshot_key,
        Body=json.dumps(snapshot, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
        # Bucket defaults should enforce SSE-KMS with a customer-managed key.
        # If not, set explicitly:
        # ServerSideEncryption="aws:kms",
        # SSEKMSKeyId="your-cmk-arn",
    )

    logger.info(
        "Retrieved sources for %s: %d notes, %d allergies, %d problems, %d meds",
        summary_id, len(notes), len(allergies),
        len(active_problems), len(current_meds),
    )
    return {
        "notes": notes,
        "allergies": allergies,
        "active_problems": active_problems,
        "current_meds": current_meds,
        "code_status_observations": code_status_observations,
        "snapshot_key": snapshot_key,
    }
```

---

## Step 3: Chunk and Preprocess Notes

*The pseudocode calls this `chunk_and_preprocess(notes)`. Flat list of notes in, processable chunks out. One note is often a reasonable chunk; long notes (H&P, multi-page consult) get sub-chunked. Preprocessing strips boilerplate so the extraction prompt doesn't waste tokens on EHR-generated headers.*

```python
def chunk_and_preprocess(notes: list) -> list:
    """
    Turn a flat list of notes into extraction-ready chunks.

    Each chunk carries metadata that travels through extraction and
    aggregation: note_id, date, type, service, author. That metadata is
    what lets the aggregation step attribute content ("Cardiology on day 4
    recommended X") and what drives provenance linking at the end.

    Args:
        notes: List of note dicts. Each dict should have at minimum:
               id, date, type, service, author, text.

    Returns:
        List of chunk dicts with 'text' and 'metadata' keys.
    """
    chunks = []
    for note in notes:
        text = note.get("text", "")
        if not text:
            continue

        # Strip EHR-generated boilerplate. This is a light version;
        # production pipelines have per-EHR regex libraries to remove
        # standard headers, copy-forward markers, signature blocks, and
        # macro-expanded content that adds no signal.
        text = _remove_boilerplate(text)

        chunk_metadata = {
            "note_id": note.get("id"),
            "note_date": note.get("date"),
            "note_type": note.get("type", ""),       # H&P, Progress Note, Consult, etc.
            "author": note.get("author", ""),
            "service": note.get("service", ""),      # Hospitalist, Cardiology, etc.
        }

        # Token counting proxy: 4 characters per token is a rough rule for
        # English clinical text. Production code should use the model's
        # actual tokenizer (tiktoken for OpenAI-family, Anthropic's count_tokens
        # endpoint for Claude). Good enough for chunk sizing here.
        approx_tokens = len(text) // 4

        if approx_tokens > TARGET_CHUNK_TOKENS:
            sub_chunks = _split_by_headers_then_length(text, TARGET_CHUNK_TOKENS)
            for sub_chunk in sub_chunks:
                chunks.append({"text": sub_chunk, "metadata": chunk_metadata})
        else:
            chunks.append({"text": text, "metadata": chunk_metadata})

    logger.info("Chunked %d notes into %d chunks", len(notes), len(chunks))
    return chunks


def _remove_boilerplate(text: str) -> str:
    """
    Strip common EHR-generated boilerplate that adds no clinical signal.

    Production pipelines carry per-EHR libraries of these patterns; this is
    a minimal starter. Don't over-strip; losing a section header can confuse
    the extraction prompt.
    """
    # Trailing Epic-style disclaimer block. Very common, very noisy.
    # Use MULTILINE so $ matches end-of-line, not end-of-string; avoids
    # stripping content after mid-note "electronically signed by" phrases
    # in copy-forwarded notes.
    text = re.sub(
        r"(?im)^\s*electronically signed by.*$", "", text,
    )
    # Telephone disclaimer footers.
    text = re.sub(
        r"(?is)this (?:message|document) may contain confidential.*$", "", text,
    )
    # Collapse whitespace.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_by_headers_then_length(text: str, target_tokens: int) -> list:
    """
    Split a long note by section headers first, then by length if still too big.

    Clinical notes have reasonably predictable section headers (HPI,
    Assessment, Plan, Review of Systems, etc.). Splitting on those first
    preserves semantic boundaries; falling back to length-based splits is
    a safety net.
    """
    # Heuristic header markers. Add to this as you learn your notes.
    header_pattern = re.compile(
        r"^(?:\s*\*+\s*)?"
        r"(HPI|History of Present Illness|ROS|Review of Systems|PMH|"
        r"Past Medical History|Medications|Allergies|Assessment|Plan|"
        r"Assessment and Plan|Physical Exam|Vital Signs|Labs|Imaging|"
        r"Impression|Hospital Course|Discharge Instructions)\s*:?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    # If we find headers, split on them.
    sections = []
    positions = [m.start() for m in header_pattern.finditer(text)]
    if positions:
        positions.append(len(text))
        for i in range(len(positions) - 1):
            section = text[positions[i]:positions[i + 1]].strip()
            if section:
                sections.append(section)
    else:
        sections = [text]

    # Further split any section that's still too big by character count.
    target_chars = target_tokens * 4
    final_chunks = []
    for section in sections:
        if len(section) <= target_chars:
            final_chunks.append(section)
            continue
        for start in range(0, len(section), target_chars):
            final_chunks.append(section[start:start + target_chars])
    return final_chunks
```

---

## Step 4: Extract Structured Facts Per Chunk

*The pseudocode calls this `extract_chunk_facts(chunk)`. Per-chunk extraction produces a fielded structured object. Run in parallel across chunks in production (Step Functions Map state). Comprehend Medical runs alongside the LLM to cross-check medications, conditions, and allergies with negation-aware NLP.*

```python
def extract_chunk_facts(summary_id: str, chunk: dict) -> dict:
    """
    Extract structured facts from a single chunk.

    The LLM does broad clinical extraction into a fielded schema.
    Comprehend Medical runs in parallel as a cross-check on the highest-risk
    categories (medications, conditions, allergies) because its negation and
    certainty handling is a well-understood piece of kit. The aggregation
    step reconciles the two.

    The extraction prompt is specialty-neutral on purpose; we want every
    fact in the chunk, and specialty filtering happens at generation time.

    Args:
        summary_id: The summary identifier (for audit).
        chunk:      One chunk from chunk_and_preprocess.

    Returns:
        Dict with llm_extracted and cm_entities, plus chunk metadata.
    """
    chunk_id = str(uuid.uuid4())
    metadata = chunk["metadata"]

    # --- LLM extraction ---
    extraction_system = """You are extracting clinical facts from a single clinical note for use in a summarization pipeline.

Return ONLY valid JSON in this exact structure:
{
  "active_problems": [
    {"name": "problem name", "certainty": "confirmed|possible|ruled_out", "is_new_in_this_note": true}
  ],
  "medications_mentioned": [
    {"name": "drug name", "dose_if_stated": "", "route_if_stated": "",
     "action": "continued|started|stopped|dose_changed|discussed"}
  ],
  "allergies_mentioned": [
    {"substance": "allergen", "reaction_if_stated": "", "severity_if_stated": ""}
  ],
  "key_findings": ["clinically significant findings, preserve original wording"],
  "negative_findings": ["explicit negatives: ruled out, no evidence of, denied"],
  "procedures_performed": [{"name": "procedure", "date_if_stated": ""}],
  "labs_imaging_mentioned": [
    {"test": "test name", "result_summary": "result", "date_if_stated": "", "is_critical": false}
  ],
  "consults_or_recs": [
    {"specialty": "service", "recommendation": "what they said", "date_if_stated": ""}
  ],
  "follow_up_plan": "text as written, or empty string",
  "code_status_mentioned": "exact text if present, or empty string",
  "devices_or_lines": ["active lines, tubes, drains, implants mentioned"],
  "critical_events": ["adverse events, rapid responses, code blues, etc."]
}

STRICT RULES:
- Use ONLY what is explicitly documented in THIS note. Do not infer across visits or dates.
- Preserve negation language exactly. "No evidence of X" must NOT become "X."
- Preserve uncertainty language. "Possible sepsis" is NOT "sepsis."
- Preserve temporal qualifiers. "History of" stays "history of." "This admission" stays "this admission."
- If a field has no content in this note, return an empty list or empty string.
- Do NOT add general medical knowledge or infer facts not in the note."""

    extraction_user = (
        f"Note date: {metadata.get('note_date', 'unknown')}\n"
        f"Note type: {metadata.get('note_type', 'unknown')}\n"
        f"Service:   {metadata.get('service', 'unknown')}\n"
        f"Author:    {metadata.get('author', 'unknown')}\n\n"
        f"CLINICAL NOTE:\n\n{chunk['text']}\n\n"
        "Extract the structured fields as JSON."
    )

    extraction_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "temperature": 0.0,  # Deterministic extraction
        "system": extraction_system,
        "messages": [{"role": "user", "content": extraction_user}],
    })

    try:
        extraction_response = bedrock_runtime.invoke_model(
            modelId=EXTRACTION_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=extraction_body,
        )
        extraction_payload = json.loads(extraction_response["body"].read())
        llm_extracted = _parse_json_response(extraction_payload["content"][0]["text"])
    except Exception as exc:
        # Don't let one chunk failure kill the run; aggregate step tolerates
        # missing chunks. Log loudly so ops knows the per-chunk success rate.
        logger.warning("LLM extraction failed for chunk %s: %s", chunk_id, exc)
        llm_extracted = _empty_extraction()

    # --- Comprehend Medical cross-check ---
    # Enforce the byte limit. Encoding to utf-8 and slicing bytes is the
    # correct pattern; slicing the string works only for pure ASCII text.
    cm_entities = []
    try:
        text_bytes = chunk["text"].encode("utf-8")
        if len(text_bytes) > COMPREHEND_MEDICAL_MAX_BYTES:
            text_bytes = text_bytes[:COMPREHEND_MEDICAL_MAX_BYTES]
            # Trim any partial trailing multi-byte char so decode succeeds
            text_for_cm = text_bytes.decode("utf-8", errors="ignore")
        else:
            text_for_cm = chunk["text"]

        cm_response = comprehend_medical.detect_entities_v2(Text=text_for_cm)
        for entity in cm_response.get("Entities", []):
            traits = [t.get("Name") for t in entity.get("Traits", [])]
            cm_entities.append({
                "text": entity.get("Text"),
                "category": entity.get("Category"),    # MEDICATION, MEDICAL_CONDITION, etc.
                "type": entity.get("Type"),
                "score": entity.get("Score"),
                "is_negated": "NEGATION" in traits,
                "is_hypothetical": "HYPOTHETICAL" in traits,
                "is_historical": "PAST_HISTORY" in traits,
                "attributes": [
                    {"type": a.get("Type"), "text": a.get("Text"),
                     "score": a.get("Score")}
                    for a in entity.get("Attributes", [])
                ],
            })
    except Exception as exc:
        # CM failure also shouldn't block the pipeline. The LLM extraction
        # is the primary source; CM is a cross-check.
        logger.warning("Comprehend Medical failed for chunk %s: %s", chunk_id, exc)

    structured_chunk = {
        "chunk_id": chunk_id,
        "note_id": metadata.get("note_id"),
        "note_date": metadata.get("note_date"),
        "note_type": metadata.get("note_type"),
        "service": metadata.get("service"),
        "author": metadata.get("author"),
        "llm_extracted": llm_extracted,
        "cm_entities": cm_entities,
    }

    # Persist per-chunk extraction for auditability. If a claim in the final
    # summary is challenged later, the trail is: final -> aggregated -> this.
    s3_client.put_object(
        Bucket=SUMMARIES_BUCKET,
        Key=f"extractions/{summary_id}/{chunk_id}.json",
        Body=json.dumps(structured_chunk, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
    )

    return structured_chunk


def _empty_extraction() -> dict:
    """Shape-compatible empty extraction for error fallbacks."""
    return {
        "active_problems": [], "medications_mentioned": [],
        "allergies_mentioned": [], "key_findings": [], "negative_findings": [],
        "procedures_performed": [], "labs_imaging_mentioned": [],
        "consults_or_recs": [], "follow_up_plan": "",
        "code_status_mentioned": "", "devices_or_lines": [],
        "critical_events": [],
    }


def _parse_json_response(raw_text: str) -> dict:
    """
    Parse JSON from a model response, stripping common markdown wrappers.

    Claude sometimes wraps JSON in markdown code fences even when told not to.
    Defensive parsing keeps the pipeline robust to that.
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        # Fall back to empty shape rather than crashing the run.
        logger.warning("Failed to parse JSON response; returning empty extraction")
        return _empty_extraction()
```

---

## Step 5: Aggregate and Deduplicate

*The pseudocode calls this `aggregate_facts(structured_chunks, retrieved_structured_data)`. Structured FHIR data is ground truth for categories like allergies, active problems, and current meds; LLM-extracted content from chunks supplements. Merging is order-sensitive: process chunks chronologically so timelines build correctly, and track mention counts so "mentioned in one out of forty notes" is distinguishable from "mentioned in thirty-eight of forty notes."*

```python
def aggregate_facts(
    summary_id: str,
    structured_chunks: list,
    retrieved: dict,
) -> dict:
    """
    Combine per-chunk extractions with ground-truth FHIR data.

    Structured FHIR data (AllergyIntolerance, Condition, MedicationRequest)
    seeds the aggregated object and is treated as authoritative. Per-chunk
    LLM extractions add mention counts, timelines, and content categories
    that don't live in structured FHIR fields (key findings, consult recs,
    critical events, code status).

    Args:
        summary_id:        The summary identifier.
        structured_chunks: List of chunk extractions from Step 4.
        retrieved:         Retrieved structured FHIR data from Step 2.

    Returns:
        Dict with the aggregated structured summary object.
    """
    aggregated = {
        "active_problems": {},       # keyed by normalized problem name
        "medications": {},           # keyed by normalized drug name
        "allergies": [],
        "key_findings_timeline": [],
        "negative_findings": [],
        "procedures": [],
        "labs_imaging": [],
        "consult_recs": [],
        "code_status": None,
        "devices_lines": {},
        "critical_events": [],
        "explicit_empties": [],
        "conflicts": [],
    }

    # --- Seed from FHIR structured data (authoritative) ---
    for allergy in retrieved.get("allergies", []):
        aggregated["allergies"].append({
            "substance": allergy.get("substance") or allergy.get("code", {}).get("display"),
            "reaction": allergy.get("reaction", ""),
            "severity": allergy.get("severity", ""),
            "source": "fhir_allergyintolerance",
            "source_id": allergy.get("id"),
        })

    for problem in retrieved.get("active_problems", []):
        name = problem.get("name") or problem.get("code", {}).get("display", "")
        key = _normalize_key(name)
        if not key:
            continue
        aggregated["active_problems"][key] = {
            "name": name,
            "icd10": problem.get("icd10"),
            "first_recorded": problem.get("recordedDate"),
            "source": "fhir_condition",
            "source_id": problem.get("id"),
            "mention_count": 0,
            "mention_dates": [],
        }

    for med in retrieved.get("current_meds", []):
        name = med.get("name") or med.get("medication", {}).get("display", "")
        key = _normalize_key(name)
        if not key:
            continue
        aggregated["medications"][key] = {
            "name": name,
            "dose": med.get("dose"),
            "frequency": med.get("frequency"),
            "source": "fhir_medicationrequest",
            "source_id": med.get("id"),
            "most_recent_action": "active_per_fhir",
            "mention_dates": [],
            "actions": [],
        }

    for obs in retrieved.get("code_status_observations", []):
        # Most recent code status observation wins.
        obs_date = obs.get("effective_datetime") or obs.get("date")
        if aggregated["code_status"] is None or (
            obs_date and obs_date > (aggregated["code_status"].get("date") or "")
        ):
            aggregated["code_status"] = {
                "text": obs.get("value") or obs.get("display", ""),
                "date": obs_date,
                "source": "fhir_observation",
                "source_id": obs.get("id"),
            }

    # --- Merge per-chunk LLM extractions (chronological) ---
    sorted_chunks = sorted(
        structured_chunks,
        key=lambda c: c.get("note_date") or "",
    )

    for chunk in sorted_chunks:
        extracted = chunk.get("llm_extracted", {})
        note_date = chunk.get("note_date")
        note_id = chunk.get("note_id")
        service = chunk.get("service")

        for problem in extracted.get("active_problems", []):
            key = _normalize_key(problem.get("name", ""))
            if not key:
                continue
            if key in aggregated["active_problems"]:
                aggregated["active_problems"][key]["mention_count"] += 1
                aggregated["active_problems"][key]["mention_dates"].append(note_date)
            else:
                aggregated["active_problems"][key] = {
                    "name": problem.get("name"),
                    "first_mention": note_date,
                    "last_mention": note_date,
                    "mention_count": 1,
                    "mention_dates": [note_date],
                    "certainty": problem.get("certainty", "confirmed"),
                    "source": f"note:{note_id}",
                }

        for med_mention in extracted.get("medications_mentioned", []):
            key = _normalize_key(med_mention.get("name", ""))
            if not key:
                continue
            if key not in aggregated["medications"]:
                aggregated["medications"][key] = {
                    "name": med_mention.get("name"),
                    "mention_dates": [],
                    "actions": [],
                    "source": f"note:{note_id}",
                }
            aggregated["medications"][key]["mention_dates"].append(note_date)
            aggregated["medications"][key]["actions"].append({
                "date": note_date,
                "action": med_mention.get("action"),
                "dose": med_mention.get("dose_if_stated"),
                "source_note_id": note_id,
            })

        for finding in extracted.get("key_findings", []):
            aggregated["key_findings_timeline"].append({
                "date": note_date,
                "text": finding,
                "source_note_id": note_id,
                "service": service,
            })

        for neg in extracted.get("negative_findings", []):
            aggregated["negative_findings"].append({
                "date": note_date, "text": neg, "source_note_id": note_id,
            })

        for proc in extracted.get("procedures_performed", []):
            aggregated["procedures"].append({
                "name": proc.get("name"),
                "date": proc.get("date_if_stated") or note_date,
                "source_note_id": note_id,
            })

        for lab in extracted.get("labs_imaging_mentioned", []):
            aggregated["labs_imaging"].append({
                "test": lab.get("test"),
                "result": lab.get("result_summary"),
                "date": lab.get("date_if_stated") or note_date,
                "is_critical": lab.get("is_critical", False),
                "source_note_id": note_id,
            })

        for rec in extracted.get("consults_or_recs", []):
            aggregated["consult_recs"].append({
                "specialty": rec.get("specialty"),
                "recommendation": rec.get("recommendation"),
                "date": rec.get("date_if_stated") or note_date,
                "source_note_id": note_id,
            })

        # Code status: LLM-extracted overrides only if newer than FHIR obs.
        code_text = extracted.get("code_status_mentioned", "")
        if code_text:
            existing_date = (aggregated["code_status"] or {}).get("date") or ""
            if not aggregated["code_status"] or (note_date and note_date > existing_date):
                aggregated["code_status"] = {
                    "text": code_text,
                    "date": note_date,
                    "source_note_id": note_id,
                }

        for device in extracted.get("devices_or_lines", []):
            key = _normalize_key(device)
            aggregated["devices_lines"][key] = {
                "device": device,
                "last_mentioned": note_date,
                "source_note_id": note_id,
            }

        for event in extracted.get("critical_events", []):
            aggregated["critical_events"].append({
                "date": note_date, "text": event, "source_note_id": note_id,
            })

    # --- Conflict detection (lightweight) ---
    # Example: a medication mentioned as both "started" and "stopped" within
    # the same day across different notes. Real conflict detection is
    # richer; this is a starter.
    for key, med in aggregated["medications"].items():
        actions = med.get("actions", [])
        if len({a.get("action") for a in actions if a.get("action") in ("started", "stopped")}) > 1:
            aggregated["conflicts"].append({
                "type": "medication_action_conflict",
                "medication": med.get("name"),
                "actions": actions,
            })

    # Persist for auditability.
    s3_client.put_object(
        Bucket=SUMMARIES_BUCKET,
        Key=f"aggregations/{summary_id}/aggregated.json",
        Body=json.dumps(aggregated, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
    )

    logger.info(
        "Aggregated %s: %d problems, %d meds, %d findings, %d consult recs",
        summary_id, len(aggregated["active_problems"]),
        len(aggregated["medications"]),
        len(aggregated["key_findings_timeline"]),
        len(aggregated["consult_recs"]),
    )
    return aggregated


def _normalize_key(text: str) -> str:
    """Lowercased, punctuation-stripped key for dedup across notes."""
    if not text:
        return ""
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()
```

---

## Step 6: Apply the Must-Include Checklist

*The pseudocode calls this `apply_must_include_checklist(aggregated, use_case, retrieved_structured_data)`. Verifies that every required category for the summary type has content, or is explicitly marked as empty. Missing categories (required, source has data, aggregation dropped it) indicate pipeline failures and should block generation.*

```python
def apply_must_include_checklist(
    aggregated: dict,
    use_case: str,
    retrieved: dict,
) -> dict:
    """
    Verify required categories are populated or explicitly marked empty.

    Three outcomes per category:
      - Content present: fine.
      - Source has data but aggregated object is empty: aggregation gap
        (pipeline failure). Try backfill; escalate if backfill doesn't work.
      - Source genuinely has no data: mark as explicit_empty so the generated
        prose says "Allergies: none documented" rather than silently omitting
        the section.

    Args:
        aggregated: The aggregated structured object from Step 5.
        use_case:   handoff | consult | pre_visit | discharge_summary.
        retrieved:  Retrieved structured FHIR data from Step 2.

    Returns:
        Dict with status (READY_FOR_GENERATION or AGGREGATION_GAP),
        the aggregated object (possibly with explicit_empties populated),
        and any gaps found.
    """
    required = MUST_INCLUDE_BY_USE_CASE.get(use_case, [])
    gaps = []

    for category in required:
        if _category_has_content(aggregated, category):
            continue

        # Empty. Is the source genuinely empty, or did aggregation drop it?
        source_has_data = _source_has_data_for_category(retrieved, category)

        if source_has_data:
            # Aggregation gap: source has content but aggregated object is
            # empty. Attempt backfill from structured data.
            backfilled = _attempt_backfill(aggregated, category, retrieved)
            if not backfilled:
                gaps.append({
                    "category": category,
                    "reason": "source_has_data_but_aggregation_empty",
                })
        else:
            # Source genuinely empty. Mark as explicit empty so generation
            # includes an explicit "none documented" statement.
            if category not in aggregated["explicit_empties"]:
                aggregated["explicit_empties"].append(category)

    if gaps:
        logger.warning(
            "Must-include checklist failed for use_case=%s: %d gaps",
            use_case, len(gaps),
        )
        return {
            "status": "AGGREGATION_GAP",
            "gaps": gaps,
            "aggregated": aggregated,
        }

    logger.info(
        "Must-include checklist passed for use_case=%s (%d explicit empties)",
        use_case, len(aggregated["explicit_empties"]),
    )
    return {
        "status": "READY_FOR_GENERATION",
        "aggregated": aggregated,
    }


def _category_has_content(aggregated: dict, category: str) -> bool:
    """Check whether a named category has content in the aggregated object."""
    mapping = {
        "allergies": lambda a: bool(a.get("allergies")),
        "active_problems": lambda a: bool(a.get("active_problems")),
        "current_medications": lambda a: bool(a.get("medications")),
        "code_status": lambda a: a.get("code_status") is not None,
        "recent_critical_events": lambda a: bool(a.get("critical_events")),
        "active_devices_lines": lambda a: bool(a.get("devices_lines")),
        "consult_recs": lambda a: bool(a.get("consult_recs")),
        "relevant_history": lambda a: bool(a.get("key_findings_timeline")),
        "recent_labs": lambda a: bool(a.get("labs_imaging")),
        "admission_reason": lambda a: bool(a.get("key_findings_timeline")),
        "hospital_course": lambda a: bool(a.get("key_findings_timeline")),
        "discharge_meds": lambda a: bool(a.get("medications")),
        "discharge_instructions": lambda a: bool(a.get("key_findings_timeline")),
        "follow_up": lambda a: bool(a.get("consult_recs") or a.get("key_findings_timeline")),
    }
    check = mapping.get(category)
    return check(aggregated) if check else False


def _source_has_data_for_category(retrieved: dict, category: str) -> bool:
    """Determine whether the retrieved source has data for this category."""
    mapping = {
        "allergies": bool(retrieved.get("allergies")),
        "active_problems": bool(retrieved.get("active_problems")),
        "current_medications": bool(retrieved.get("current_meds")),
        "code_status": bool(retrieved.get("code_status_observations")),
        # Note-derived categories: the presence of notes implies we had
        # something to look at; true absence means the aggregation dropped it.
        "recent_critical_events": bool(retrieved.get("notes")),
        "active_devices_lines": bool(retrieved.get("notes")),
        "consult_recs": bool(retrieved.get("notes")),
        "relevant_history": bool(retrieved.get("notes")),
        "recent_labs": bool(retrieved.get("notes")),
        "admission_reason": bool(retrieved.get("notes")),
        "hospital_course": bool(retrieved.get("notes")),
        "discharge_meds": bool(retrieved.get("current_meds")),
        "discharge_instructions": bool(retrieved.get("notes")),
        "follow_up": bool(retrieved.get("notes")),
    }
    return mapping.get(category, False)


def _attempt_backfill(aggregated: dict, category: str, retrieved: dict) -> bool:
    """
    Attempt to populate a missing category from retrieved FHIR data.

    Only works for categories where the structured FHIR data is the
    authoritative source. Returns True if backfill succeeded, False otherwise.
    """
    if category == "allergies" and retrieved.get("allergies"):
        for allergy in retrieved["allergies"]:
            aggregated["allergies"].append({
                "substance": allergy.get("substance"),
                "reaction": allergy.get("reaction", ""),
                "source": "fhir_allergyintolerance_backfill",
                "source_id": allergy.get("id"),
            })
        return True

    if category == "active_problems" and retrieved.get("active_problems"):
        for problem in retrieved["active_problems"]:
            key = _normalize_key(problem.get("name", ""))
            if key and key not in aggregated["active_problems"]:
                aggregated["active_problems"][key] = {
                    "name": problem.get("name"),
                    "source": "fhir_condition_backfill",
                    "source_id": problem.get("id"),
                    "mention_count": 0,
                    "mention_dates": [],
                }
        return True

    if category == "current_medications" and retrieved.get("current_meds"):
        for med in retrieved["current_meds"]:
            key = _normalize_key(med.get("name", ""))
            if key and key not in aggregated["medications"]:
                aggregated["medications"][key] = {
                    "name": med.get("name"),
                    "dose": med.get("dose"),
                    "source": "fhir_medicationrequest_backfill",
                    "source_id": med.get("id"),
                    "actions": [],
                    "mention_dates": [],
                }
        return True

    return False
```

---

## Step 7: Generate the Summary Prose

*The pseudocode calls this `generate_summary_prose(aggregated, request_params)`. The model now has a clean, fielded input. The prompt enforces section structure, specialty emphasis, and preserves negations and temporal qualifiers. The output carries both readable prose and a provenance map of factual claims to source notes.*

```python
def generate_summary_prose(
    aggregated: dict,
    request_params: dict,
    regeneration_hint: str = "",
) -> dict:
    """
    Generate the clinician-facing summary with section structure and provenance.

    The aggregated structured object is the only source of facts. The prompt
    hard-requires grounded generation, preserved negations, preserved
    uncertainty, preserved temporal qualifiers, and explicit empty-category
    statements (rather than silent omission).

    Args:
        aggregated:        The aggregated structured object.
        request_params:    Dict with use_case, format, specialty, destination.
        regeneration_hint: Extra instruction for retries. Populated by the
                           validation step on failure.

    Returns:
        Dict with summary_markdown and provenance.factual_claims list.
    """
    use_case = request_params.get("use_case", "handoff")
    specialty = request_params.get("requesting_specialty", "general")
    output_format = request_params.get("format", "problem_oriented")

    sections = SECTIONS_BY_USE_CASE.get(use_case, SECTIONS_BY_USE_CASE["handoff"])
    specialty_instructions = SPECIALTY_EMPHASIS.get(
        specialty, SPECIALTY_EMPHASIS["general"],
    )

    generation_system = f"""You are drafting a clinician-facing summary for a {specialty} {use_case} review.
The reader is a busy clinician who needs to make clinical decisions in minutes.

HARD REQUIREMENTS:
1. Use ONLY the facts in the structured summary object provided. Do not add diagnoses,
   medications, findings, dates, or recommendations that are not in the input.
2. Preserve negation language EXACTLY. If the input has "no evidence of PE," the summary
   must also say "no evidence of PE" or equivalent preserved negation. Never drop negations.
3. Preserve uncertainty language. "Possible sepsis" is NOT "sepsis." "Rule out PE" is NOT "PE."
4. Preserve temporal qualifiers. "History of" stays "history of." "This admission" stays
   "this admission."
5. When a required section has no content (check the explicit_empties field), say so
   explicitly ("Allergies: none documented") rather than omitting the section.
6. Attribute consultant recommendations to the consulting service. "Cardiology recommends X"
   never becomes "X is recommended."
7. When the input shows conflicting information in the conflicts field, surface the conflict
   rather than picking one side.

SPECIALTY EMPHASIS FOR {specialty}:
{specialty_instructions}

STRUCTURE ({output_format} format):
Use the following section headers in this order. Skip a section only if both the underlying
data is empty AND the category is not in the explicit_empties list:
{json.dumps(sections, indent=2)}

OUTPUT FORMAT: Return ONLY valid JSON:
{{
  "summary_markdown": "the full summary as markdown with section headers and bullet lists",
  "provenance": {{
    "factual_claims": [
      {{
        "claim": "the specific factual assertion in the summary text",
        "source_field": "path into the aggregated object, e.g. 'medications.apixaban.actions[0].dose'",
        "source_note_id": "the note ID this claim comes from, or 'fhir_condition' / 'fhir_allergyintolerance' / etc.",
        "asserted_value": "the specific value claimed in the summary"
      }}
    ]
  }}
}}"""

    user_parts = [
        f"STRUCTURED SUMMARY OBJECT (your only source of facts):\n{json.dumps(aggregated, indent=2, default=str)}"
    ]
    if regeneration_hint:
        user_parts.append(f"REGENERATION HINT: {regeneration_hint}")
    user_parts.append("Generate the clinical summary as JSON.")
    user_message = "\n\n".join(user_parts)

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 6000,
        # Slightly above zero: we want natural prose, not robotic output.
        # Too high and the model drifts from the grounding constraints.
        "temperature": 0.2,
        "system": generation_system,
        "messages": [{"role": "user", "content": user_message}],
    }

    invoke_kwargs = {
        "modelId": GENERATION_MODEL_ID,
        "contentType": "application/json",
        "accept": "application/json",
        "body": json.dumps(request_body),
    }

    # Apply the Bedrock Guardrail with contextual grounding if configured.
    # For clinician-facing summarization, the grounding check is the single
    # most valuable feature: it compares the model's output against a
    # reference context (here, the aggregated object serialized) and
    # rejects responses that score below your configured threshold. Don't
    # ship to production without this.
    #
    # IMPORTANT: The contextual grounding check requires the aggregated object
    # to be explicitly tagged as grounding source in the model invocation.
    # Using the Converse API, wrap the aggregated JSON in a guardContent block
    # so Guardrails knows what to compare the output against. Using InvokeModel,
    # supply the grounding source via the Guardrails policy configuration.
    # Without this tagging, the contextual grounding check returns SAFE
    # regardless of actual fidelity. This example sets the IDs but does NOT
    # tag the grounding source; the Step 8 validator is the active faithfulness
    # guard. Production deployments should add guardContent tags around the
    # aggregated object.
    if GUARDRAIL_ID and GUARDRAIL_VERSION:
        invoke_kwargs["guardrailIdentifier"] = GUARDRAIL_ID
        invoke_kwargs["guardrailVersion"] = GUARDRAIL_VERSION

    response = bedrock_runtime.invoke_model(**invoke_kwargs)
    response_payload = json.loads(response["body"].read())

    # Detect Guardrail intervention via the documented response field.
    # Anthropic Claude's stop_reason values are "end_turn", "stop_sequence",
    # "max_tokens", "tool_use", etc. Guardrail intervention is signaled
    # separately via "amazon-bedrock-guardrailAction" in the response body.
    guardrail_action = response_payload.get("amazon-bedrock-guardrailAction")
    if guardrail_action == "INTERVENED":
        logger.warning("Guardrail intervened on generation; returning rejection")
        return {
            "status": "GROUNDING_REJECTED",
            "summary_markdown": "",
            "provenance": {"factual_claims": []},
        }

    raw_text = response_payload["content"][0]["text"]
    result = _parse_json_response(raw_text)

    logger.info(
        "Generated summary (%d chars, %d factual claims)",
        len(result.get("summary_markdown", "")),
        len(result.get("provenance", {}).get("factual_claims", [])),
    )
    return {
        "status": "GENERATED",
        "summary_markdown": result.get("summary_markdown", ""),
        "provenance": result.get("provenance", {"factual_claims": []}),
    }
```

---

## Step 8: Validate Claims and Attach Provenance

*The pseudocode calls this `validate_and_attach_provenance(summary_text, provenance, aggregated)`. Belt-and-suspenders alongside the Guardrails grounding check. Every specific claim in the summary gets traced back to the aggregated object. Value mismatches and missing source references trigger regeneration or escalation. The provenance map becomes the data that powers click-through-to-source in the UI.*

```python
def validate_and_attach_provenance(
    summary_id: str,
    provenance: dict,
    aggregated: dict,
) -> dict:
    """
    Verify each factual claim against the aggregated structured object.

    For each claim, resolve its source_field path into the aggregated object
    and confirm the asserted_value matches. Numeric claims (doses, counts,
    dates) require exact match after normalization; text claims require
    substantive overlap. Unverified claims go on the return list; the
    caller decides whether to regenerate or escalate.

    Args:
        summary_id:  The summary identifier.
        provenance:  The factual_claims map from the generation step.
        aggregated:  The aggregated structured object the model was supposed
                     to use as its sole source of facts.

    Returns:
        Dict with validation status, unverified claims, and provenance map
        (persisted to DynamoDB for UI consumption).
    """
    claims = provenance.get("factual_claims", [])
    if not claims:
        # A summary with zero tracked claims is either empty or the model
        # ignored the provenance instruction. Either way, don't deliver it.
        return {
            "status": "REQUIRES_REGENERATION",
            "unverified_claims": [],
            "reason": "no_claims_tracked",
            "provenance_map": {},
        }

    unverified = []
    provenance_map = {}

    for claim in claims:
        source_field = claim.get("source_field", "")
        source_note_id = claim.get("source_note_id", "")
        asserted_value = (claim.get("asserted_value") or "").strip()
        claim_text = claim.get("claim", "")

        # Resolve the source_field path into the aggregated object.
        source_value = _resolve_json_path(aggregated, source_field)

        if source_value is None:
            unverified.append({
                "claim": claim_text,
                "source_field": source_field,
                "asserted_value": asserted_value,
                "issue": "source_field_not_in_aggregated_object",
                "severity": "HIGH",
            })
            continue

        # Normalize for match
        asserted_norm = _normalize_for_match(asserted_value)
        source_norm = _normalize_for_match(str(source_value))

        if not asserted_norm or not source_norm:
            unverified.append({
                "claim": claim_text,
                "source_field": source_field,
                "asserted_value": asserted_value,
                "source_value": str(source_value),
                "issue": "empty_value",
                "severity": "MEDIUM",
            })
            continue

        # Bidirectional substring check: forgiving (accepts "5 mg" vs source
        # "apixaban 5 mg twice daily"), strict enough to catch a dose flip.
        if asserted_norm in source_norm or source_norm in asserted_norm:
            provenance_map[claim_text] = {
                "source_field": source_field,
                "source_note_id": source_note_id,
                "verified": True,
            }
            continue

        # Fall back to token-overlap for longer phrasings.
        overlap = _token_overlap_ratio(asserted_norm, source_norm)
        if overlap >= MIN_CLAIM_OVERLAP:
            provenance_map[claim_text] = {
                "source_field": source_field,
                "source_note_id": source_note_id,
                "verified": True,
                "match_type": "overlap",
                "overlap": Decimal(str(round(overlap, 2))),
            }
            continue

        unverified.append({
            "claim": claim_text,
            "source_field": source_field,
            "asserted_value": asserted_value,
            "source_value": str(source_value),
            "issue": "value_mismatch",
            "severity": "HIGH",
            "overlap": Decimal(str(round(overlap, 2))),
        })

    total = len(claims)
    high_severity_count = sum(1 for u in unverified if u["severity"] == "HIGH")
    verified_count = total - len(unverified)
    validation_rate = verified_count / total if total else 0.0

    if high_severity_count > 0:
        status = "REQUIRES_REGENERATION"
    elif validation_rate >= 0.95:
        status = "VALIDATED"
    else:
        status = "NEEDS_CLINICIAN_REVIEW"

    # Persist the provenance map for the UI layer. Store validation_rate as
    # Decimal; DynamoDB doesn't accept Python float. Going through str
    # avoids binary-precision issues.
    provenance_table = dynamodb.Table(SUMMARY_PROVENANCE_TABLE)
    provenance_table.put_item(Item={
        "summary_id": summary_id,
        "provenance_map": provenance_map,
        "validation_rate": Decimal(str(round(validation_rate, 4))),
        "verified_at": datetime.datetime.now(timezone.utc).isoformat(),
        "status": status,
    })

    logger.info(
        "Validation for %s: %d/%d verified (rate=%.2f) status=%s",
        summary_id, verified_count, total, validation_rate, status,
    )
    return {
        "status": status,
        "validation_rate": validation_rate,
        "unverified_claims": unverified,
        "provenance_map": provenance_map,
    }


def _resolve_json_path(obj: dict, path: str):
    """
    Walk a dot-and-bracket path into a nested dict/list structure.

    Supports:
      - "medications.apixaban.dose"       (dict traversal with dots)
      - "allergies[0].substance"           (list indexing)
      - "key_findings_timeline[2].text"    (mixed)

    Returns None for any path that doesn't exist.
    """
    if not path:
        return None
    current = obj
    for segment in path.split("."):
        match = re.match(r"^([^\[]+)(?:\[(\d+)\])?$", segment)
        if not match:
            return None
        key, idx = match.group(1), match.group(2)
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
        if idx is not None:
            idx_int = int(idx)
            if not isinstance(current, list) or idx_int >= len(current):
                return None
            current = current[idx_int]
    return current


def _normalize_for_match(text: str) -> str:
    """Lowercase, strip, collapse whitespace for tolerant matching."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _token_overlap_ratio(a: str, b: str) -> float:
    """
    Jaccard-like token overlap as a fallback comparison.

    Production systems should layer on embedding-based semantic similarity
    for a better signal. This is a simple alternative that catches
    paraphrases with high lexical overlap.
    """
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0
```

---

## Step 9: Render and Deliver

*The pseudocode calls this `render_and_deliver(summary_id, summary_text, provenance_map, request_params)`. Same summary content, different rendering per destination. EHR sidebar gets compact markdown; handoff tool gets structured sections; PDF gets a print layout with provenance footnotes. Real portal integrations are stubbed; this example focuses on the archive write and state update.*

```python
def render_and_deliver(
    summary_id: str,
    summary_markdown: str,
    provenance_map: dict,
    request_params: dict,
    validation_status: str,
) -> dict:
    """
    Archive the final summary and route for delivery.

    The archive is the authoritative record; rendering is per-destination.
    In a real system, each destination has its own rendering and delivery
    path (EHR sidebar document API, handoff-tool inbox, PDF service, etc.).
    Stubbed here to keep the example focused on the AI pattern.

    Args:
        summary_id:        The summary identifier.
        summary_markdown:  The generated summary body.
        provenance_map:    Claim-to-source mapping from validation step.
        request_params:    Originating request, for destination and context.
        validation_status: VALIDATED | NEEDS_CLINICIAN_REVIEW | REQUIRES_REGENERATION |
                           GROUNDING_REJECTED | NO_VALIDATION_COMPLETED.

    Returns:
        Dict with final status, archive keys, and the render payload shape.
    """
    destination = request_params.get("destination", "ehr_sidebar")
    # Route to clinician review if validation did not fully pass.
    # A summary never auto-ships to the EHR without passing validation.
    requires_review = validation_status in (
        "NEEDS_CLINICIAN_REVIEW",
        "REQUIRES_REGENERATION",
        "GROUNDING_REJECTED",
        "NO_VALIDATION_COMPLETED",
    )

    # Archive the raw summary and the provenance map. Both are PHI and must
    # be stored with SSE-KMS encryption (bucket defaults should enforce this)
    # and access-controlled retrieval. HIPAA retention applies (6+ years typical).
    summary_key = f"final-summaries/{summary_id}/summary.md"
    s3_client.put_object(
        Bucket=SUMMARIES_BUCKET,
        Key=summary_key,
        Body=summary_markdown.encode("utf-8"),
        ContentType="text/markdown; charset=utf-8",
    )

    provenance_key = f"final-summaries/{summary_id}/provenance.json"
    s3_client.put_object(
        Bucket=SUMMARIES_BUCKET,
        Key=provenance_key,
        Body=json.dumps(provenance_map, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
    )

    # --- Destination rendering (stubbed) ---
    # In a real deployment each destination renders differently.
    if requires_review:
        final_status = "PENDING_CLINICIAN_REVIEW"
        rendered_payload = {
            "for_review": True,
            "markdown": summary_markdown,
            "provenance_map": provenance_map,
        }
        logger.info(
            "Summary %s routed for clinician review before delivery",
            summary_id,
        )
    else:
        if destination == "ehr_sidebar":
            # Stub: in production, POST to the EHR's context-sensitive sidebar
            # document API with compact markdown and clickable provenance.
            rendered_payload = {
                "destination": "ehr_sidebar",
                "markdown": summary_markdown,
                "provenance_map": provenance_map,
            }
        elif destination == "handoff_tool":
            # Stub: structured handoff tool typically wants sections parsed
            # into fielded data. Real implementation parses the markdown.
            rendered_payload = {
                "destination": "handoff_tool",
                "markdown": summary_markdown,
                "provenance_map": provenance_map,
            }
        elif destination == "pdf":
            # Stub: render markdown -> HTML -> PDF with provenance footnotes.
            # Common approach: WeasyPrint or a Lambda with a PDF library.
            rendered_payload = {
                "destination": "pdf",
                "markdown": summary_markdown,
                "provenance_map": provenance_map,
                "render_note": "PDF rendering stubbed in this example",
            }
        else:
            rendered_payload = {
                "destination": destination,
                "markdown": summary_markdown,
                "render_note": "Unknown destination; falling back to markdown",
            }
        final_status = "DELIVERED"

    # Update request state.
    requests_table = dynamodb.Table(SUMMARY_REQUESTS_TABLE)
    requests_table.update_item(
        Key={"summary_id": summary_id},
        UpdateExpression=(
            "SET #status = :status, "
            "summary_key = :sk, "
            "provenance_key = :pk, "
            "delivered_at = :da, "
            "validation_status = :vs"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": final_status,
            ":sk": summary_key,
            ":pk": provenance_key,
            ":da": datetime.datetime.now(timezone.utc).isoformat(),
            ":vs": validation_status,
        },
    )

    # Emit a CloudWatch metric so dashboards track success rates per use case
    # and specialty. Uncomment in a real deployment.
    # cloudwatch = boto3.client("cloudwatch")
    # cloudwatch.put_metric_data(
    #     Namespace="ClinicalSummarization",
    #     MetricData=[{
    #         "MetricName": "SummariesDelivered",
    #         "Dimensions": [
    #             {"Name": "Specialty", "Value": request_params.get("requesting_specialty", "general")},
    #             {"Name": "UseCase", "Value": request_params.get("use_case", "handoff")},
    #         ],
    #         "Value": 1.0,
    #         "Unit": "Count",
    #     }],
    # )

    logger.info(
        "Summary %s status=%s destination=%s",
        summary_id, final_status, destination,
    )
    return {
        "status": final_status,
        "summary_key": summary_key,
        "provenance_key": provenance_key,
        "rendered_payload": rendered_payload,
    }
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. Runs all nine steps sequentially for one summary request. In production, each step becomes a Step Functions state with its own retry policy, Step 4 fans out via a parallel Map state, and the validation-failure regeneration loop is a proper state-machine loop. The sequential version below is fine for understanding the flow.

```python
def summarize_clinical_notes(
    request: dict,
    retrieved_clinical_data: dict,
) -> dict:
    """
    Run the full clinical-note summarization pipeline for one request.

    Steps (matching the Recipe 2.6 pseudocode):
      1. Receive and authorize the summary request
      2. Retrieve source documents (and snapshot for audit)
      3. Chunk and preprocess notes
      4. Extract structured facts per chunk (parallelizable)
      5. Aggregate and deduplicate across chunks
      6. Apply the must-include checklist
      7. Generate section-wise prose (with grounding check)
      8. Validate claims against aggregated facts, attach provenance
      9. Render and deliver (or route for clinician review)

    Args:
        request:                 Summary request dict.
        retrieved_clinical_data: Dict of FHIR resources to summarize.
                                 In production, fetched from HealthLake/FHIR;
                                 passed in here to keep the example focused
                                 on the AI pattern.

    Returns:
        Dict with summary_id, final status, summary text, and key counts.
    """
    start = time.time()

    # Step 1
    print(f"Step 1: Receiving summary request for patient {request['patient_id']}...")
    summary_id = receive_summary_request(request)
    print(f"  summary_id: {summary_id}")

    # Step 2
    print("Step 2: Retrieving source documents...")
    retrieved = retrieve_source_documents(
        summary_id=summary_id,
        patient_id=request["patient_id"],
        scope=request.get("scope", "current_encounter"),
        encounter_id=request.get("encounter_id"),
        retrieved_clinical_data=retrieved_clinical_data,
    )
    print(
        f"  {len(retrieved['notes'])} notes, "
        f"{len(retrieved['allergies'])} allergies, "
        f"{len(retrieved['current_meds'])} meds"
    )

    # Step 3
    print("Step 3: Chunking and preprocessing notes...")
    chunks = chunk_and_preprocess(retrieved["notes"])
    print(f"  {len(chunks)} chunks ready for extraction")

    # Step 4 (parallel in production; sequential here)
    print(f"Step 4: Extracting facts from {len(chunks)} chunks...")
    structured_chunks = []
    for i, chunk in enumerate(chunks, start=1):
        structured_chunks.append(extract_chunk_facts(summary_id, chunk))
        if i % 10 == 0:
            print(f"  {i}/{len(chunks)} chunks extracted")
    print(f"  Completed {len(structured_chunks)} chunk extractions")

    # Step 5
    print("Step 5: Aggregating facts across chunks...")
    aggregated = aggregate_facts(summary_id, structured_chunks, retrieved)
    print(
        f"  Aggregated: {len(aggregated['active_problems'])} problems, "
        f"{len(aggregated['medications'])} meds, "
        f"{len(aggregated['consult_recs'])} consult recs"
    )

    # Step 6
    use_case = request.get("use_case", "handoff")
    print(f"Step 6: Applying must-include checklist for '{use_case}'...")
    checklist_result = apply_must_include_checklist(aggregated, use_case, retrieved)
    if checklist_result["status"] == "AGGREGATION_GAP":
        print(f"  Checklist FAILED: {len(checklist_result['gaps'])} gaps")
        _update_status(summary_id, "AGGREGATION_GAP")
        return {
            "summary_id": summary_id,
            "status": "AGGREGATION_GAP",
            "gaps": checklist_result["gaps"],
        }
    aggregated = checklist_result["aggregated"]
    print(f"  Checklist passed ({len(aggregated['explicit_empties'])} explicit empties)")

    # Steps 7-8: generation + validation loop
    generation_result = None
    # Initialize to a sentinel so exhausted-retry paths don't crash Step 9.
    validation_result = {
        "status": "NO_VALIDATION_COMPLETED",
        "validation_rate": 0.0,
        "unverified_claims": [],
        "provenance_map": {},
    }
    regeneration_hint = ""

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        print(f"Step 7 (attempt {attempt}): Generating summary prose...")
        generation_result = generate_summary_prose(
            aggregated=aggregated,
            request_params=request,
            regeneration_hint=regeneration_hint,
        )

        if generation_result["status"] == "GROUNDING_REJECTED":
            print("  Grounding check rejected the output")
            regeneration_hint = (
                "The previous draft was rejected by the grounding check. "
                "Stick strictly to values in the structured summary object. "
                "Do not add details beyond what the input provides."
            )
            continue

        print(
            f"  Generated {len(generation_result['summary_markdown'])} chars, "
            f"{len(generation_result['provenance']['factual_claims'])} claims"
        )

        print("Step 8: Validating claims against aggregated facts...")
        validation_result = validate_and_attach_provenance(
            summary_id=summary_id,
            provenance=generation_result["provenance"],
            aggregated=aggregated,
        )
        print(
            f"  status={validation_result['status']} "
            f"rate={validation_result['validation_rate']:.2f}"
        )

        if validation_result["status"] == "REQUIRES_REGENERATION":
            unverified = validation_result["unverified_claims"][:3]
            issues = "; ".join(
                f"{u['issue']}: claimed '{u.get('asserted_value')}' "
                f"for {u.get('source_field')}"
                for u in unverified
            )
            regeneration_hint = (
                f"The previous draft had validation failures: {issues}. "
                f"Use only values explicitly present in the structured summary object."
            )
            continue

        # VALIDATED or NEEDS_CLINICIAN_REVIEW: acceptable end states.
        break
    else:
        # Exhausted attempts.
        print(f"  Gave up after {MAX_GENERATION_ATTEMPTS} attempts; routing to review")

    # Step 9
    print("Step 9: Rendering and delivering...")
    delivery = render_and_deliver(
        summary_id=summary_id,
        summary_markdown=generation_result["summary_markdown"],
        provenance_map=validation_result.get("provenance_map", {}),
        request_params=request,
        validation_status=validation_result["status"],
    )

    elapsed_ms = int((time.time() - start) * 1000)
    print(f"\nDone. Processing time: {elapsed_ms}ms")

    return {
        "summary_id": summary_id,
        "status": delivery["status"],
        "summary_markdown": generation_result["summary_markdown"],
        "validation_rate": validation_result["validation_rate"],
        "chunks_processed": len(structured_chunks),
        "claims_verified": len(validation_result.get("provenance_map", {})),
        "unverified_claims": len(validation_result.get("unverified_claims", [])),
        "summary_key": delivery["summary_key"],
        "provenance_key": delivery["provenance_key"],
        "processing_time_ms": elapsed_ms,
    }


def _update_status(summary_id: str, status: str) -> None:
    """Update a summary's status field in DynamoDB. Used for early exits."""
    requests_table = dynamodb.Table(SUMMARY_REQUESTS_TABLE)
    requests_table.update_item(
        Key={"summary_id": summary_id},
        UpdateExpression="SET #status = :s",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":s": status},
    )


# --- Example usage ---
if __name__ == "__main__":
    # All identifiers, dates, provider names, and clinical content below are
    # SYNTHETIC. Do not use real patient data in development or testing.

    sample_request = {
        "patient_id": "PAT-SYNTH-00042",
        "scope": "current_encounter",
        "encounter_id": "ENC-SYNTH-00812",
        "requesting_user": "USR-HOSPITALIST-091",
        "requesting_specialty": "hospitalist",
        "use_case": "handoff",
        "format": "problem_oriented",
        "destination": "ehr_sidebar",
    }

    # In production, retrieved_clinical_data comes from HealthLake FHIR queries.
    # For this example, we use a small synthetic encounter with three notes.
    sample_clinical_data = {
        "notes": [
            {
                "id": "note-admission-hp",
                "date": "2026-05-04T10:30:00Z",
                "type": "H&P",
                "service": "Hospitalist",
                "author": "Dr. Nguyen",
                "text": (
                    "72 yo M with CHF (EF 30%, last TTE 2025) and ESRD on HD MWF, "
                    "presents with 3 days of worsening shortness of breath and lower "
                    "extremity edema. Admission BNP 3200 (baseline ~800). ECG with "
                    "no acute ST changes. Troponin mildly elevated at 0.42. "
                    "Concerned for acute on chronic CHF exacerbation plus possible "
                    "NSTEMI. Cardiology consulted. Started IV furosemide 80 mg BID. "
                    "Code status: full code, confirmed with patient and daughter. "
                    "Allergies: sulfa (rash). No evidence of active infection. "
                    "Home meds continued except lisinopril held given renal function."
                ),
            },
            {
                "id": "note-cards-consult",
                "date": "2026-05-05T14:15:00Z",
                "type": "Consult Note",
                "service": "Cardiology",
                "author": "Dr. Patel",
                "text": (
                    "Cardiology consulted for troponin elevation. Troponin trended "
                    "0.42 -> 4.2 -> 3.8 -> 1.9 over 24 hours. Consistent with NSTEMI. "
                    "Recommend cardiac catheterization. Started aspirin 81 mg daily "
                    "and clopidogrel 75 mg daily. Heparin drip per protocol. No "
                    "contraindications to DAPT. Cath scheduled for 5/7."
                ),
            },
            {
                "id": "note-cath-report",
                "date": "2026-05-07T11:00:00Z",
                "type": "Procedure Note",
                "service": "Cardiology",
                "author": "Dr. Patel",
                "text": (
                    "Cardiac catheterization performed. Findings: 90% stenosis of "
                    "proximal LAD. Drug-eluting stent placed successfully. No "
                    "complications. Small groin hematoma post-procedure, stable. "
                    "Continue DAPT for minimum 12 months. Continue heparin drip "
                    "pending transition plan."
                ),
            },
        ],
        "allergies": [
            {
                "id": "allergy-sulfa-001",
                "substance": "Sulfa",
                "reaction": "Rash",
                "severity": "mild",
            }
        ],
        "active_problems": [
            {
                "id": "cond-chf",
                "name": "Congestive heart failure",
                "icd10": "I50.9",
                "recordedDate": "2023-01-15",
            },
            {
                "id": "cond-esrd",
                "name": "End-stage renal disease on dialysis",
                "icd10": "N18.6",
                "recordedDate": "2022-03-10",
            },
        ],
        "current_meds": [
            {
                "id": "med-metoprolol",
                "name": "metoprolol succinate",
                "dose": "50 mg",
                "frequency": "daily",
            },
            {
                "id": "med-atorvastatin",
                "name": "atorvastatin",
                "dose": "40 mg",
                "frequency": "nightly",
            },
        ],
        "code_status": [
            {
                "id": "obs-code-status-001",
                "value": "Full code",
                "effective_datetime": "2026-05-04T10:45:00Z",
            }
        ],
    }

    result = summarize_clinical_notes(
        request=sample_request,
        retrieved_clinical_data=sample_clinical_data,
    )

    print("\n" + "=" * 60)
    print("RESULT SUMMARY:")
    print("=" * 60)
    print(json.dumps(
        {
            "summary_id": result["summary_id"],
            "status": result["status"],
            "validation_rate": result["validation_rate"],
            "chunks_processed": result["chunks_processed"],
            "claims_verified": result["claims_verified"],
            "unverified_claims": result["unverified_claims"],
            "processing_time_ms": result["processing_time_ms"],
        },
        indent=2,
        default=str,
    ))
    print("\n" + "-" * 60)
    print("GENERATED SUMMARY:")
    print("-" * 60)
    print(result["summary_markdown"])
```

---

## The Gap Between This and Production

Run this end-to-end against a small synthetic encounter and you'll see the pattern: source snapshot captured, chunks extracted, facts aggregated, checklist applied, prose generated with provenance, claims validated, summary archived. The distance between this and a real health-system deployment is substantial. Here's where the gap lives.

**FHIR retrieval is where the real work starts.** This example takes clinical data as a parameter. In reality, pulling DocumentReference, Condition, MedicationRequest, AllergyIntolerance, Observation, and Encounter resources from HealthLake (or directly from the EHR's FHIR API) is 40-60% of the implementation. Each resource type has its own search parameters, pagination behavior, and vendor-specific quirks. SMART on FHIR authentication for context-of-care launches adds another layer. Budget generously; "the AI part" is usually the easy part compared to the data plumbing.

**Step Functions orchestration and parallel chunk extraction.** The sequential Python loop in Step 4 is a learning artifact. Real pipelines use a Step Functions Map state to fan out per-chunk extractions with a tunable concurrency cap (respect Bedrock account-level quotas). Map state also gives you per-chunk retries, error isolation, and observability into which chunks failed. For a 100-chunk chart with per-chunk extraction at 1-2 seconds, serial execution is 100-200 seconds; parallel with concurrency 10 is 10-20 seconds. Users notice the difference.

**Bedrock Guardrails configuration matters.** The example sets `GUARDRAIL_ID` to None, which disables it. For clinician-facing output, configure a Guardrail with the contextual grounding check enabled and a strict threshold (0.85+). The grounding check compares generated output against a reference context; the aggregated object is exactly that reference. Pair this with the validator in Step 8 as defense in depth: the Guardrail catches obvious hallucination, the validator catches precise value mismatches that the Guardrail's softer scoring might miss.

**Clinician review UI is make-or-break.** The pipeline emits a markdown summary and a provenance map. A clinician has to see both in context, click through claims to source notes, edit if needed, and approve. If review happens outside the EHR, context-switch eats the time savings. The review UI has to be embedded (SMART on FHIR or EHR-native extension) and has to render provenance as clickable inline references. This is at least as much engineering as the AI pipeline, and it's where adoption lives or dies.

**Provenance rendering is a first-class concern.** The provenance_map in Step 8 is the data; rendering it is another problem. In the EHR sidebar, each claim with a source_note_id should be a clickable link that opens the source note. For claims that aggregate across multiple notes (a problem mentioned in 12 of 15 notes), the UI should let the user see all contributing sources. When provenance degrades (validator flagged an overlap match at 0.6), the UI should show that lower confidence visually. Don't just display markdown; make it auditable.

**Must-include categories need specialty-specific tuning.** The example uses one checklist per use case, but real deployments have per-specialty variations. A nephrology pre-visit summary needs baseline and current creatinine as must-includes. An oncology consult needs staging. A pediatric handoff needs weight, dosing, and growth parameters. Checklists should be editable by clinical leadership without engineering changes; move them into a config store (SSM, DynamoDB, or AppConfig) and version them.

**Semantic validation beats substring matching.** The validator catches gross mismatches (asserting "10 mg" against source "5 mg") and fabrications (claims referencing fields that don't exist). It misses subtle paraphrase drift (claiming "high risk of stroke" against source "moderate risk"). For high-stakes summaries, add an embedding-based similarity check: embed each claim and each source value, compute cosine similarity, flag claims below a threshold for review. Bedrock Titan Embeddings or Cohere Embed both work well on clinical text. This adds latency and cost but catches a class of errors substring matching can't.

**Handling Part 2 and confidential content.** Behavioral health, substance use treatment records (42 CFR Part 2), HIV-related content, genetic test results, and adolescent confidential sections all have specific disclosure rules. The retrieval step in Step 2 has to respect those. A summary that pulls from a Part 2 note without the right consent is a compliance problem, not just a quality problem. Access control must be enforced at retrieval, not bolted on downstream. Ask your privacy office what's covered and where in the source data those flags live before building.

**Conflict surfacing, not smoothing.** The aggregation step in this example does lightweight conflict detection and writes conflicts into the aggregated object. The generation prompt tells the model to surface conflicts rather than pick a side. That instruction isn't always obeyed; the default behavior of LLMs is to smooth. Add an explicit post-generation check: for every entry in `aggregated['conflicts']`, verify the summary mentions it. If not, regenerate with a stronger instruction or escalate for clinician review.

**Feedback loops for corrections.** When a clinician finds an error in a summary, that finding has to get back to the team. Build a one-click "this summary is wrong" mechanism that captures the specific claim, the correction, and routes to a review queue. Use the corrections to iterate on prompts, chunking strategies, and must-include checklists. This is the difference between a tool that gets better over time and one that plateaus. Most teams under-budget this; it's operations, not code.

**Evaluation methodology is its own project.** ROUGE and BLEU scores are weakly correlated with clinical usefulness. The real evaluation involves blinded clinician review: pick a sample of summaries, have a clinician rate them for accuracy, completeness, omission severity, and actionability. Track these scores over time. Run the evaluation on new model versions before flipping production configs. Build the evaluation pipeline before you scale; without it, you're shipping without knowing what you're shipping.

**Cost monitoring and regeneration caps.** At ~$0.05-$0.25 per inpatient summary and a 500-bed facility generating handoff summaries twice daily, steady-state spend is meaningful. Monitor via CloudWatch billing alarms and per-summary cost tracking in DynamoDB. Watch for runaway regeneration loops (a bug where validation keeps failing can 10x your costs overnight). `MAX_GENERATION_ATTEMPTS` in the config caps this at the code level; also set account-level Bedrock quotas as a belt-and-suspenders.

**PHI minimization in prompts.** The prompts here include full clinical data including names and MRNs. Bedrock under BAA is HIPAA-eligible so this is compliant, but the minimum-necessary principle argues for sending less. Consider: redact patient names and MRNs before sending to the model, then substitute back during rendering. The model doesn't need the patient's actual name to compose the summary. This also narrows the blast radius if Bedrock model-invocation-logging is enabled for quality monitoring.

**VPC, encryption, and audit.** This example calls APIs without VPC configuration. A production Lambda runs in private subnets with interface endpoints for Bedrock Runtime, Comprehend Medical, Step Functions, KMS, CloudWatch Logs, and (if used) HealthLake; gateway endpoints for S3 and DynamoDB. S3 buckets use SSE-KMS with customer-managed keys. DynamoDB uses CMK for encryption at rest. CloudTrail data events enabled for every Bedrock invocation and every S3 object access. A clinician audit will eventually ask "what did the model see for summary X on date Y?" and you need to answer definitively.

**Model-ID lifecycle.** The model IDs in this example will be replaced over time as newer versions launch. Store model IDs in configuration (SSM Parameter Store or AppConfig), not in code. When you update, rerun your regression suite before flipping production. Skipping this is how teams discover at 2 AM that the new model version ignores a critical section of their prompt. Also: cross-region inference profile IDs (prefixed `us.` or `eu.`) are increasingly required in many regions, not optional.

**DynamoDB Decimal gotcha.** The validation_rate in Step 8 is stored as `Decimal(str(round(validation_rate, 4)))` because DynamoDB doesn't accept Python floats. The example handles this correctly; the common trap on first deployments is passing the float directly and getting `TypeError: Float types are not supported`. Always wrap via `Decimal(str(...))`; going through `str` avoids binary-precision issues of `Decimal(float_value)`.

**JSON parsing resilience.** The `_parse_json_response` helper strips markdown code fences but otherwise does a strict parse. In production, when parsing fails, send the raw output back to the model with "fix this JSON; preserve all content" instructions. Models are usually good at self-correction on structural errors and this saves a full regeneration cycle for recoverable formatting issues.

**Testing with synthetic data.** There are no tests in this example. A production pipeline has unit tests for the JSON path resolver and normalization helpers, integration tests with synthetic Synthea or MIMIC-IV charts for each use case, regression tests ensuring known-good charts still produce expected summaries after prompt changes, and load tests validating throughput against realistic burst patterns (end-of-clinic, shift-change waves). Synthea produces synthetic FHIR data so the test corpus never contains real PHI. MIMIC-IV (credentialed access through PhysioNet) provides realistic longer notes for chart-size stress tests but is not PHI-free in the open-access sense; treat it accordingly.

**Observability and SLOs.** Reasonable targets: 95th-percentile end-to-end latency under 60 seconds for inpatient summaries, under 2 minutes for longitudinal; validation pass rate above 0.9 for current-encounter summaries; regeneration rate under 15%; must-include checklist pass rate above 0.95. Publish these as CloudWatch SLOs. Alert on drift. Without these, problems surface as clinician complaints rather than dashboard anomalies, and by then trust is already damaged.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 2.6: Clinical Note Summarization](chapter02.06-clinical-note-summarization) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
