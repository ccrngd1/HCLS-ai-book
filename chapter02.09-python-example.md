# Recipe 2.9: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 2.9. It shows one way you could translate the clinical-decision-support-synthesis concepts into working Python using Amazon Bedrock, Amazon OpenSearch Service, Amazon Aurora PostgreSQL (pgvector), Amazon HealthLake, Amazon Comprehend Medical, S3, DynamoDB, and Step Functions. It is not production-ready. There is no corpus ingestion pipeline (that's a significant project on its own), no drug-database license integration, no Step Functions orchestration wired end-to-end, no SMART-on-FHIR EHR launch, no CDS Hooks integration, no clinician-facing UI, no validated regulatory posture documentation, and no post-market surveillance plumbing. Think of it as a sketchpad: useful for understanding the shape of the synthesis pipeline, not something you'd route an ICU order through on Monday morning.
>
> The pipeline maps to the eleven pseudocode steps from the main recipe: trigger and fetch patient context, normalize and structure patient facts, scope determination, deterministic safety checks, scenario classification and retrieval planning, multi-source retrieval, rank and filter, grounded synthesis, post-generation validation, tier and suppress, and archive and log. Validation failures trigger regeneration up to a cap, then route to human review.
>
> All clinical content in examples below is SYNTHETIC. The patient context, drug dosing recommendations, guideline citations, sources, scores, and numerical findings are illustrative only. Do not treat any specific recommendation, dose, or citation in this file as real clinical guidance. A production system grounds every claim in actual retrieved chunks from a real, current, licensed authoritative corpus.

---

## Setup

You'll need the AWS SDK for Python and a few utility libraries:

```bash
pip install boto3 opensearch-py requests-aws4auth psycopg2-binary
```

Your environment needs credentials configured (environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` (for scenario classification, retrieval planning, synthesis generation, and embeddings)
- `bedrock:ApplyGuardrail` (if you configure a Bedrock Guardrail with contextual grounding, which you should for clinician-facing synthesis)
- `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM`, `comprehendmedical:InferSNOMEDCT` (for patient-context and query-time entity extraction)
- `es:ESHttpPost`, `es:ESHttpGet` (for OpenSearch hybrid retrieval of guideline and protocol content; `aoss:*` equivalents if using OpenSearch Serverless)
- `rds-data:ExecuteStatement` for Aurora Data API (or database credentials via Secrets Manager for direct psycopg2 connections) to the structured drug-interaction, renal-dosing, and contraindication tables
- `healthlake:ReadResource`, `healthlake:SearchWithGet` (for FHIR patient-context retrieval; skip if querying the EHR FHIR API directly with OAuth2)
- `s3:GetObject`, `s3:PutObject` (for the per-synthesis archive and retrieval traces)
- `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:UpdateItem`, `dynamodb:Query` (for synthesis state, per-patient synthesis history for alert-fatigue suppression, and clinician engagement tracking)
- `secretsmanager:GetSecretValue` (commercial drug-database API credentials, EHR FHIR credentials)
- `kms:Decrypt`, `kms:GenerateDataKey` (customer-managed keys for all PHI at rest)
- `states:StartExecution` (if you wire this into Step Functions, which you should for anything real)
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`, `cloudwatch:PutMetricData` (operational metrics and HIPAA audit logs)

You also need Bedrock model access enabled in the Bedrock console for three roles: a smaller, cheaper model for scenario classification and retrieval planning (Claude Haiku or Nova Lite); an embedding model for guideline and query-side vectorization (Titan Text Embeddings v2 or Cohere Embed English v3); and a capable generation model for synthesis where citation discipline, reasoning visibility, and preserved uncertainty all matter (Claude Sonnet or equivalent). Scope `bedrock:InvokeModel` to specific model ARNs in production, not a wildcard.

A few things worth knowing upfront:

- **Bedrock model IDs change over time** and the set available in your region depends on your account's model access. Cross-region inference profiles are now the recommended path in many regions (IDs prefixed with `us.` or `eu.`). The IDs in this example are reasonable defaults at the time of writing; verify in the Bedrock console and adjust for your region before running.
- **The OpenSearch index used here is assumed to already exist** and to contain your chunked, embedded guideline corpus. Building that corpus (parsing guideline PDFs, chunking by recommendation, embedding, loading into OpenSearch with the right field mappings and metadata tags) is a project in its own right. This example focuses on the synthesis-time pipeline, which is what the recipe teaches.
- **The Aurora drug database is assumed to exist** with tables for drug interactions, renal dosing, and contraindications. Populating it from licensed sources (Lexicomp, First Databank) or open sources (DDInter, FDA SPLs) is its own ingestion project. The SQL calls below reference table structures that your ingestion pipeline has to produce.
- **Comprehend Medical's per-call limit for `DetectEntitiesV2` is enforced in bytes**, not characters. Patient contexts with long problem lists or medication narratives can exceed the limit; the helper below encodes to utf-8 and slices by byte length defensively.
- **All clinical content in the example output is SYNTHETIC.** Do not treat any specific dose, interaction, source, or recommendation in this file as real. A production system grounds every claim in actual retrieved content from a real corpus with verified licensing.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, retrieval sizing, suppression windows, validation thresholds, and resource names are the knobs you'll change most often between environments.

```python
import hashlib
import json
import logging
import re
import time
import uuid
import datetime
from datetime import timezone
from decimal import Decimal
from collections import defaultdict

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Structured logging. In production, ship JSON-formatted records to CloudWatch
# Logs Insights for query-friendly analysis. The patient context and the
# synthesized recommendation contain PHI; never log them in plain text. The
# audit trail for clinical content lives in S3 and DynamoDB under KMS
# encryption with CloudTrail data events enabled.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles Bedrock throttling. CDS workload is naturally
# bursty (morning rounds, admission spikes, shift change). Adaptive mode
# uses exponential backoff with jitter so retry storms don't pile on.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
comprehend_medical = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
cloudwatch = boto3.client("cloudwatch", config=BOTO3_RETRY_CONFIG)
# HealthLake, Aurora Data API, and Secrets Manager clients are conditionally
# created in the functions that use them so the example runs without those
# services configured.

# --- Model Configuration ---
# Three roles. Classification and retrieval planning are cheap per-synthesis
# tasks where a smaller model earns its keep. Embeddings have to match
# whatever embedder indexed the guideline corpus (critical: do NOT mix
# embedders between indexing and query time). Generation is where citation
# discipline, reasoning visibility, preserved uncertainty, and framing-as-
# options all matter, so use a capable model.
#
# If your region requires cross-region inference, use the inference profile ID:
#   e.g., "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
# TODO: verify the exact model IDs available in your region and account.
SMALL_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"
GENERATION_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"

# Optional Bedrock Guardrail for the generation step. Configure one in the
# Bedrock console with the contextual grounding check enabled. For clinician-
# facing CDS, the grounding check is the feature that matters most. Set a
# high threshold (0.85+) to reject responses that drift from the retrieved
# sources. Leaving these None disables the Guardrail; do NOT ship without one.
GUARDRAIL_ID = None        # e.g., "abc123xyz"
GUARDRAIL_VERSION = None   # e.g., "DRAFT" or a numbered version string

# --- OpenSearch Configuration ---
# The guidelines-and-protocols index is assumed to exist with these fields:
#   chunk_id (keyword)              - unique per chunk
#   source_id (keyword)             - parent source document
#   source_type (keyword)           - guideline | protocol | package_insert | ...
#   issuing_body (keyword)          - AHA | NCCN | IDSA | InstitutionName | ...
#   publication_year (integer)      - for recency ranking
#   clinical_domain (keyword)       - infectious_disease | cardiology | oncology | ...
#   population_tags (keyword[])     - adult | pediatric | pregnancy | geriatric | ...
#   evidence_tier (keyword)         - A | B | C | ungraded
#   section (keyword)               - the source's section heading
#   recommendation_text (text)      - for BM25 and display
#   embedding (knn_vector, 1024)    - Titan v2 is 1024 dimensions
#   source_url (keyword)            - link target for the rendered citation
OPENSEARCH_ENDPOINT = "your-cds-opensearch-domain.us-east-1.es.amazonaws.com"
OPENSEARCH_GUIDELINES_INDEX = "cds-guidelines"
OPENSEARCH_PROTOCOLS_INDEX = "cds-institutional-protocols"
OPENSEARCH_REGION = "us-east-1"

# --- Aurora Configuration (structured drug database) ---
# Aurora PostgreSQL with pgvector hosts the structured drug tables:
#   drug_interactions (rxnorm_a, rxnorm_b, severity, mechanism, clinical_effect,
#                      management, source_citation, source_url)
#   renal_dosing       (rxnorm_code, egfr_lower, egfr_upper, recommended_dose,
#                       contraindicated, notes, source_citation)
#   contraindications  (rxnorm_code, snomed_code, type, rationale,
#                       source_citation, source_url)
# Populate from a licensed source (Lexicomp, First Databank) or open data
# (DDInter, FDA SPLs) per your institution's licensing posture.
AURORA_CLUSTER_ARN = "arn:aws:rds:us-east-1:123456789012:cluster:cds-drugdb"
AURORA_DATABASE = "cds_drugdb"
AURORA_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:cds-drugdb-creds"

# --- HealthLake Configuration ---
# HealthLake datastore for FHIR patient context. Alternatively, query the
# EHR's FHIR endpoint directly with OAuth2/SMART-on-FHIR. The helper in this
# example uses HealthLake; swap for direct FHIR if that's your integration.
HEALTHLAKE_DATASTORE_ID = "your-healthlake-datastore-id"

# --- Storage Configuration ---
# One bucket for per-synthesis archives and retrieval traces. In production
# these are typically separate prefixes with different lifecycle policies:
# traces purged at 90 days, full synthesis records retained per the
# institution's regulatory and medical-record retention policy.
SYNTHESIS_ARCHIVE_BUCKET = "your-cds-synthesis-archive-bucket"
SYNTHESIS_ARCHIVE_CMK_ARN = "arn:aws:kms:us-east-1:123456789012:key/abcd1234-cds"

# DynamoDB tables. Partition keys noted in parentheses.
SYNTHESES_TABLE = "cds-syntheses"              # (synthesis_id)
PATIENT_HISTORY_TABLE = "cds-patient-history"  # (patient_id, synthesis_id GSI)

# --- Pipeline Tuning ---
# How many chunks to retrieve per query variant before fusion. Broader
# initial retrieval gives the ranker more to work with; too broad and
# downstream cost climbs.
GUIDELINE_RETRIEVAL_SIZE = 30
PROTOCOL_RETRIEVAL_SIZE = 10

# After ranking, keep this many chunks for the synthesis prompt.
TOP_GUIDELINE_CHUNKS = 15
TOP_PROTOCOL_CHUNKS = 10

# Max generation+validation retries. If we can't produce a validated
# synthesis within this budget, escalate to human review rather than loop.
MAX_GENERATION_ATTEMPTS = 3

# Comprehend Medical DetectEntitiesV2 has a per-call byte limit (~20,000
# bytes for synchronous calls). Patient contexts usually fit, but truncate
# defensively.
COMPREHEND_MEDICAL_MAX_BYTES = 19500

# Suppression window for alert-fatigue control. If an identical-signature
# synthesis was delivered for this patient within this many minutes, suppress.
SUPPRESSION_WINDOW_MINUTES = 180  # 3 hours default; tune per scenario

# Minimum eGFR at which we treat a drug as having "renal dosing implications"
# even if we don't have a specific table row. Triggers conservative review.
CONSERVATIVE_RENAL_EGFR = 60

# --- Source Authority Ranking ---
# Higher number = higher authority. Used in rank-and-filter.
SOURCE_AUTHORITY_SCORE = {
    "institutional_protocol": 5,
    "society_guideline":      4,
    "drug_database":          4,  # structured, authoritative by definition
    "package_insert":         3,
    "systematic_review":      3,
    "narrative_review":       2,
    "expert_opinion":         1,
}

# High-alert medication classes. Orders in these classes always warrant CDS
# review even in "routine" scenarios. Source: ISMP High-Alert Medication List
# (institutional policies typically extend this; keep the list data-driven
# in production rather than hard-coded here).
HIGH_ALERT_DRUG_CLASSES = {
    "anticoagulant", "antiarrhythmic", "chemotherapy", "insulin",
    "opioid_iv", "neuromuscular_blocker", "sedative_iv", "sodium_chloride_hypertonic",
    "potassium_iv", "magnesium_iv",
}

# Scenarios considered out-of-scope for this CDS surface (medical
# management). Recommendations that propose actions in these scopes should
# be flagged by the validator and suppressed.
OUT_OF_SCOPE_PATTERNS = [
    r"\bsurgical (consult|intervention|repair)\b",
    r"\bprocedural anesthesia\b",
    r"\brefer(ral)? to (cardiothoracic|neurosurg|orthopedic) surgery\b",
]

# Directive language in the model's own voice (not inside a quoted
# guideline) is a regulatory-posture concern. The validator strips verbatim
# guideline quotes before scanning, then flags any of these.
DIRECTIVE_PHRASES = [
    "you should", "you must", "administer", "give", "prescribe now",
    "start immediately", "stop immediately", "switch to",
]
```

---

## Shared Helpers

A few utilities used across steps. Keeping them together so each step stays focused on the pattern it's teaching.

```python
def _now_iso() -> str:
    """UTC ISO timestamp for audit fields."""
    return datetime.datetime.now(timezone.utc).isoformat()

def _build_event_key(trigger: dict) -> str:
    """
    Build a deterministic event key from the trigger so that duplicate
    EventBridge deliveries produce the same synthesis_id and get rejected
    by the DynamoDB conditional write.

    Key construction per trigger type:
      admission:          "{patient_id}:{encounter_id}:admission_synthesis"
      medication_order:   "{patient_id}:{order_id}:med_order_review"
      lab_result:         "{patient_id}:{observation_id}:lab_triggered"
      clinician_request:  "{patient_id}:{request_uuid}:clinician_request"
    """
    patient_id = trigger.get("patient_id", "unknown")
    trigger_type = trigger.get("trigger_type", "clinician_request")
    payload = trigger.get("payload") or {}

    if trigger_type == "admission":
        encounter_id = trigger.get("encounter_id", "no_enc")
        return f"{patient_id}:{encounter_id}:admission_synthesis"
    elif trigger_type == "medication_order":
        order_id = payload.get("order_id", trigger.get("encounter_id", "no_order"))
        return f"{patient_id}:{order_id}:med_order_review"
    elif trigger_type == "lab_result":
        obs_id = payload.get("observation_id", "no_obs")
        return f"{patient_id}:{obs_id}:lab_triggered"
    else:
        # clinician_request: the UI must supply a unique request_uuid
        request_uuid = payload.get("request_uuid", str(uuid.uuid4()))
        return f"{patient_id}:{request_uuid}:clinician_request"

def _get_opensearch_client() -> OpenSearch:
    """
    Build an IAM-authenticated OpenSearch client.

    Uses the current boto3 session's credentials. In production, the Lambda
    execution role should have least-privilege OpenSearch access scoped to
    the specific domain and the two indexes we query.
    """
    session = boto3.Session()
    credentials = session.get_credentials()
    awsauth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        OPENSEARCH_REGION,
        "es",  # use "aoss" if targeting OpenSearch Serverless
        session_token=credentials.token,
    )
    return OpenSearch(
        hosts=[{"host": OPENSEARCH_ENDPOINT, "port": 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )

def _embed_text(text: str) -> list:
    """
    Embed a single string with the configured embedding model.

    CRITICAL: this must match whatever embedder indexed the guideline
    corpus. If the corpus was indexed with Titan v2 and this function
    uses Titan v1, retrieval quality will be garbage and you won't get
    an error. Pin the embedding model ID in config and verify it matches
    the index at startup.
    """
    body = json.dumps({"inputText": text})
    response = bedrock_runtime.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    payload = json.loads(response["body"].read())
    return payload["embedding"]

def _parse_json_response(raw_text: str) -> dict:
    """
    Parse JSON from a model response, stripping common markdown wrappers.

    Claude sometimes wraps JSON in markdown code fences even when told
    not to. Defensive parsing keeps the pipeline robust to that.
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
        logger.warning("Failed to parse JSON response; returning empty dict")
        return {}

def _safe_utf8_truncate(text: str, max_bytes: int) -> str:
    """
    Truncate text to at most max_bytes when encoded as utf-8.

    Slicing a string by character count can still blow past the byte
    limit for multi-byte characters. Encoding, slicing, and decoding with
    errors='ignore' is the safe pattern.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")

def _to_decimal_safe(value):
    """
    Convert floats to Decimal for DynamoDB. Going through str avoids the
    binary-precision issues that Decimal(float_value) introduces.

    DynamoDB raises TypeError on Python floats. This helper is the muscle
    memory that prevents that.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_decimal_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_decimal_safe(v) for v in value]
    return value

def _execute_aurora_sql(sql: str, parameters: list) -> list:
    """
    Execute a parameterized SQL statement against the Aurora drug database
    via the Data API.

    In production, some teams prefer a direct psycopg2 connection for
    performance and richer SQL support. The Data API is convenient for
    serverless Lambda since it avoids VPC-bound connection management.
    Either works; pick one and be consistent.

    Args:
        sql:        Parameterized SQL with :name placeholders.
        parameters: List of dicts with name/value/typeHint per the Data API.

    Returns:
        List of row dicts (column name -> value).
    """
    rds_data = boto3.client("rds-data", config=BOTO3_RETRY_CONFIG)
    try:
        response = rds_data.execute_statement(
            resourceArn=AURORA_CLUSTER_ARN,
            secretArn=AURORA_SECRET_ARN,
            database=AURORA_DATABASE,
            sql=sql,
            parameters=parameters,
            includeResultMetadata=True,
        )
    except ClientError as exc:
        logger.warning("Aurora query failed: %s", exc)
        return []

    # Convert Data API's column-metadata + records format to a list of dicts.
    column_names = [c["name"] for c in response.get("columnMetadata", [])]
    rows = []
    for record in response.get("records", []):
        row = {}
        for col_name, cell in zip(column_names, record):
            row[col_name] = _data_api_cell_value(cell)
        rows.append(row)
    return rows

def _data_api_cell_value(cell: dict):
    """Unwrap the Data API's typed-cell format into a plain Python value."""
    if cell.get("isNull"):
        return None
    for key, value in cell.items():
        if key != "isNull":
            return value
    return None
```

---

## Step 1: Trigger and Fetch Patient Context

*The pseudocode calls this `trigger_synthesis(trigger)`. A clinical event (admission, medication order, lab result) arrives through EventBridge, or a clinician submits an explicit request. The first job is to pull the patient's current state as a FHIR bundle. The bundle is the input to every downstream stage, so we record a synthesis record early with enough audit metadata that any failure is traceable.*

```python
def trigger_synthesis(trigger: dict) -> dict:
    """
    Initialize a synthesis, persist initial state, and fetch the patient
    context as a FHIR bundle from HealthLake (or the EHR's FHIR API).

    Args:
        trigger: Dict with:
            - trigger_type:   "admission" | "medication_order" | "lab_result"
                              | "clinician_request"
            - patient_id:     FHIR Patient.id
            - encounter_id:   FHIR Encounter.id (when applicable)
            - clinician_id:   Cognito identity for audit trail
            - payload:        trigger-specific details (e.g., proposed med,
                              abnormal lab value)

    Returns:
        Dict with synthesis_id, status, and the fetched FHIR bundle.
    """
    # Derive synthesis_id deterministically from an event key so that
    # EventBridge at-least-once redelivery does not produce duplicate
    # synthesis runs. The DynamoDB conditional write below is the
    # idempotency gate; a duplicate trigger fails the condition and
    # short-circuits before any downstream work runs.
    event_key = _build_event_key(trigger)
    synthesis_id = hashlib.sha256(event_key.encode()).hexdigest()[:32]
    now_iso = _now_iso()

    # Persist the synthesis record early. If any later step fails, we have
    # a record of what was triggered and for whom. The synthesis record
    # carries PHI (patient_id), so the table should use KMS CMK encryption.
    # The ConditionExpression rejects duplicate deliveries.
    syntheses_table = dynamodb.Table(SYNTHESES_TABLE)
    try:
        syntheses_table.put_item(
            Item=_to_decimal_safe({
                "synthesis_id":  synthesis_id,
                "trigger_type":  trigger.get("trigger_type"),
                "patient_id":    trigger.get("patient_id"),
                "encounter_id":  trigger.get("encounter_id", ""),
                "clinician_id":  trigger.get("clinician_id"),
                "status":        "FETCHING_CONTEXT",
                "initiated_at":  now_iso,
                "trigger_payload": trigger.get("payload", {}),
            }),
            ConditionExpression="attribute_not_exists(synthesis_id)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info("Duplicate trigger suppressed: %s", synthesis_id)
            return {"status": "DUPLICATE_SUPPRESSED",
                    "synthesis_id": synthesis_id}
        raise

    # Determine which FHIR resources to pull. A broad synthesis (admission,
    # general decision support) pulls broadly; a scoped synthesis (drug
    # interaction check for one order) can pull narrowly. Resource choice
    # materially affects downstream cost and latency.
    trigger_type = trigger.get("trigger_type", "clinician_request")
    resource_types = _resource_types_for_trigger(trigger_type)

    # Pull the FHIR bundle. HealthLake's search API returns FHIR Bundle
    # resources; in production you typically make one search per resource
    # type with patient= and status/date filters to bound the size.
    try:
        patient_bundle = _fetch_fhir_bundle_from_healthlake(
            patient_id=trigger["patient_id"],
            resource_types=resource_types,
        )
    except ClientError as exc:
        logger.error("HealthLake fetch failed for synthesis %s: %s",
                     synthesis_id, exc)
        syntheses_table.update_item(
            Key={"synthesis_id": synthesis_id},
            UpdateExpression="SET #s = :s, failure_reason = :r",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "CONTEXT_FETCH_FAILED",
                                       ":r": str(exc)},
        )
        return {"status": "FAILED", "stage": "step_1",
                "synthesis_id": synthesis_id}

    syntheses_table.update_item(
        Key={"synthesis_id": synthesis_id},
        UpdateExpression="SET #s = :s, context_resource_count = :n",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "CONTEXT_FETCHED",
            ":n": len(patient_bundle.get("entry", [])),
        },
    )

    logger.info(
        "Synthesis %s: fetched %d FHIR resources for patient %s",
        synthesis_id, len(patient_bundle.get("entry", [])),
        trigger["patient_id"],
    )
    return {
        "synthesis_id":  synthesis_id,
        "status":        "CONTEXT_FETCHED",
        "patient_bundle": patient_bundle,
        "trigger":       trigger,
    }

def _resource_types_for_trigger(trigger_type: str) -> list:
    """
    Pick which FHIR resource types to pull based on the trigger.

    Broader triggers (admission, general request) pull a wider set.
    Narrower triggers (single med order) could pull less, but in practice
    safety checks need the full medication and allergy list regardless.
    """
    base = [
        "Patient", "Encounter", "Condition", "MedicationRequest",
        "AllergyIntolerance", "Observation", "Procedure",
    ]
    if trigger_type in ("admission", "clinician_request"):
        base.append("DocumentReference")  # recent notes for context
    return base

def _fetch_fhir_bundle_from_healthlake(patient_id: str,
                                       resource_types: list) -> dict:
    """
    Query HealthLake for the named FHIR resource types scoped to a patient.

    HealthLake's FHIR endpoint is an HTTPS API requiring SigV4 signing.
    Most teams use the `requests` library plus `botocore.auth.SigV4Auth`
    or a FHIR client library to make these calls. The sketch below uses
    boto3's generic `healthlake` client, which in current SDK versions
    does not expose a `search_fhir_resources` method; swap in the
    SigV4-signed-HTTPS pattern when wiring up real integration.

    TODO (TechCodeReviewer): replace this stub with the real HealthLake
    SigV4 HTTPS integration. The current code returns a minimal synthetic
    bundle so the example runs end-to-end without a live datastore.
    """
    # Synthetic bundle for illustration; REPLACE with real HealthLake call.
    return {
        "resourceType": "Bundle",
        "type":         "collection",
        "entry":        _synthetic_patient_bundle_entries(patient_id),
    }

def _synthetic_patient_bundle_entries(patient_id: str) -> list:
    """
    Return a small synthetic FHIR bundle for a 74-year-old male with CKD,
    AF on apixaban, HFrEF, sulfa allergy, and prior C. diff. Purely
    illustrative so the downstream pipeline has input to operate on.
    """
    return [
        {"resource": {
            "resourceType": "Patient",
            "id": patient_id,
            "gender": "male",
            "birthDate": "1951-06-14",
        }},
        {"resource": {
            "resourceType": "Condition",
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "code": {
                "text": "Chronic kidney disease, stage 4",
                "coding": [{"system": "http://snomed.info/sct",
                            "code": "431857002"}],
            },
        }},
        {"resource": {
            "resourceType": "Condition",
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "code": {"text": "Atrial fibrillation",
                     "coding": [{"system": "http://snomed.info/sct",
                                 "code": "49436004"}]},
        }},
        {"resource": {
            "resourceType": "Condition",
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "code": {"text": "Heart failure with reduced ejection fraction"},
        }},
        {"resource": {
            "resourceType": "MedicationRequest",
            "status": "active",
            "medicationCodeableConcept": {
                "text": "apixaban 5 mg",
                "coding": [{"system":
                            "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "1364430"}],
            },
            "dosageInstruction": [{"text": "5 mg PO BID"}],
        }},
        {"resource": {
            "resourceType": "AllergyIntolerance",
            "code": {"text": "Sulfa"},
            "reaction": [{"severity": "mild",
                          "manifestation": [{"text": "rash"}]}],
        }},
        {"resource": {
            "resourceType": "Observation",
            "code": {"coding": [{"system": "http://loinc.org",
                                 "code": "2160-0",
                                 "display": "Creatinine"}]},
            "valueQuantity": {"value": 2.4, "unit": "mg/dL"},
            "effectiveDateTime": "2026-05-10T02:00:00Z",
        }},
    ]
```

---

## Step 2: Normalize and Structure Patient Facts

*The pseudocode calls this `normalize_patient_context(patient_bundle)`. Turn the raw FHIR bundle into a compact structured object with standardized terminology bindings and derived values (eGFR, BMI, Child-Pugh). Normalization is deterministic; do it in Lambda with a clear schema. The structured context is what every downstream stage actually reads.*

```python
def normalize_patient_context(patient_bundle: dict) -> dict:
    """
    Flatten the FHIR bundle into a structured dict with standardized codes
    and derived values. Deterministic; no ML involved.

    The output schema is the contract for every downstream step. Keep it
    stable across versions.
    """
    entries = patient_bundle.get("entry", []) or []
    resources_by_type = defaultdict(list)
    for e in entries:
        res = e.get("resource", {})
        rtype = res.get("resourceType")
        if rtype:
            resources_by_type[rtype].append(res)

    patient = (resources_by_type.get("Patient") or [{}])[0]

    demographics = {
        "age":           _calculate_age_years(patient.get("birthDate")),
        "sex_assigned":  patient.get("gender"),
        "weight_kg":     _most_recent_observation_value(
                             resources_by_type.get("Observation", []),
                             loinc="29463-7"),
        "height_cm":     _most_recent_observation_value(
                             resources_by_type.get("Observation", []),
                             loinc="8302-2"),
        "pregnancy":     _infer_pregnancy_status(resources_by_type),
    }

    active_conditions = []
    for cond in resources_by_type.get("Condition", []):
        if _is_active_condition(cond):
            active_conditions.append({
                "display":     (cond.get("code") or {}).get("text"),
                "snomed_code": _extract_coding_code(cond.get("code"),
                                                    "http://snomed.info/sct"),
                "icd10_code":  _extract_coding_code(cond.get("code"),
                                                    "http://hl7.org/fhir/sid/icd-10-cm"),
                "onset":       cond.get("onsetDateTime"),
            })

    current_medications = []
    for med_req in resources_by_type.get("MedicationRequest", []):
        if med_req.get("status") == "active":
            med_code = med_req.get("medicationCodeableConcept", {})
            dosage = (med_req.get("dosageInstruction") or [{}])[0]
            current_medications.append({
                "display":     med_code.get("text"),
                "rxnorm_code": _extract_coding_code(
                                   med_code,
                                   "http://www.nlm.nih.gov/research/umls/rxnorm"),
                "dose_text":   dosage.get("text"),
                "prescribed_on": med_req.get("authoredOn"),
            })

    allergies = []
    for allergy in resources_by_type.get("AllergyIntolerance", []):
        reaction = (allergy.get("reaction") or [{}])[0]
        manifestations = reaction.get("manifestation") or []
        allergies.append({
            "display":          (allergy.get("code") or {}).get("text"),
            "substance_rxnorm": _extract_coding_code(
                                    allergy.get("code"),
                                    "http://www.nlm.nih.gov/research/umls/rxnorm"),
            "reaction_severity": reaction.get("severity"),
            "reaction_manifestation": [m.get("text") for m in manifestations],
        })

    # Recent labs: the set keyed on by many guidelines. Expand per use case.
    observations = resources_by_type.get("Observation", [])
    relevant_loincs = {
        "creatinine":      "2160-0",
        "ast":             "1920-8",
        "alt":             "1742-6",
        "total_bilirubin": "1975-2",
        "sodium":          "2951-2",
        "potassium":       "2823-3",
        "hemoglobin":      "718-7",
        "platelets":       "777-3",
        "inr":             "6301-6",
    }
    recent_labs = {
        name: _most_recent_observation_value(observations, loinc=code)
        for name, code in relevant_loincs.items()
    }

    # Derived values. Many guidelines key on these rather than raw labs.
    derived = {
        "egfr_ckd_epi_2021": _calculate_egfr_ckd_epi_2021(
                                 demographics, recent_labs.get("creatinine")),
        "bmi":               _calculate_bmi(demographics.get("weight_kg"),
                                            demographics.get("height_cm")),
    }

    structured = {
        "demographics":        demographics,
        "active_conditions":   active_conditions,
        "current_medications": current_medications,
        "allergies":           allergies,
        "recent_labs":         recent_labs,
        "derived":             derived,
    }
    logger.info(
        "Normalized patient context: %d conditions, %d meds, %d allergies, "
        "eGFR=%s",
        len(active_conditions), len(current_medications), len(allergies),
        derived["egfr_ckd_epi_2021"],
    )
    return structured

def _calculate_age_years(birth_date_str: str | None) -> int | None:
    """Age in years from a YYYY-MM-DD birthdate. None if invalid."""
    if not birth_date_str:
        return None
    try:
        bd = datetime.date.fromisoformat(birth_date_str)
        today = datetime.date.today()
        return today.year - bd.year - (
            (today.month, today.day) < (bd.month, bd.day)
        )
    except ValueError:
        return None

def _is_active_condition(cond: dict) -> bool:
    """True if the Condition.clinicalStatus includes 'active'."""
    status = cond.get("clinicalStatus") or {}
    for coding in status.get("coding", []) or []:
        if coding.get("code", "").lower() == "active":
            return True
    return False

def _extract_coding_code(coded: dict | None, system: str) -> str | None:
    """Pick the code from a CodeableConcept matching the requested system."""
    if not coded:
        return None
    for coding in coded.get("coding", []) or []:
        if coding.get("system") == system:
            return coding.get("code")
    return None

def _most_recent_observation_value(observations: list, loinc: str):
    """Return the numeric value of the most recent Observation with this LOINC."""
    candidates = []
    for obs in observations:
        if _extract_coding_code(obs.get("code"), "http://loinc.org") == loinc:
            eff = obs.get("effectiveDateTime")
            value = (obs.get("valueQuantity") or {}).get("value")
            if eff and value is not None:
                candidates.append((eff, value))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]

def _infer_pregnancy_status(resources_by_type: dict) -> bool:
    """
    Conservative pregnancy check: look for any active pregnancy-coded
    condition. Real systems also inspect SocialHistory, recent hCG, and
    EHR-specific flags. Default to False when unknown (for non-female
    demographics; adjust per clinical logic).
    """
    for cond in resources_by_type.get("Condition", []) or []:
        display = ((cond.get("code") or {}).get("text") or "").lower()
        if "pregnan" in display and _is_active_condition(cond):
            return True
    return False

def _calculate_egfr_ckd_epi_2021(demographics: dict,
                                 serum_creatinine_mg_dl) -> float | None:
    """
    CKD-EPI 2021 eGFR calculation (race-free). Returns mL/min/1.73 m^2.

    Formula reference: Inker LA et al. New Creatinine- and Cystatin C-Based
    Equations to Estimate GFR without Race. NEJM 2021. Verify against your
    institutional formulary/coding before production.

    TODO (TechCodeReviewer): confirm the exact CKD-EPI 2021 coefficients
    and unit handling match the institutional lab convention (mg/dL vs
    umol/L) before using in any real deployment.
    """
    if not serum_creatinine_mg_dl:
        return None
    age = demographics.get("age")
    sex = demographics.get("sex_assigned")
    if not age or sex not in ("male", "female"):
        return None

    # CKD-EPI 2021 race-free constants
    if sex == "female":
        kappa = 0.7
        alpha = -0.241
        sex_coef = 1.012
    else:
        kappa = 0.9
        alpha = -0.302
        sex_coef = 1.0

    scr = float(serum_creatinine_mg_dl)
    ratio = scr / kappa
    min_term = min(ratio, 1.0) ** alpha
    max_term = max(ratio, 1.0) ** -1.200
    age_term = 0.9938 ** age

    egfr = 142.0 * min_term * max_term * age_term * sex_coef
    return round(egfr, 1)

def _calculate_bmi(weight_kg, height_cm):
    """BMI from weight and height. None if either is missing."""
    if not weight_kg or not height_cm:
        return None
    try:
        h_m = float(height_cm) / 100.0
        return round(float(weight_kg) / (h_m * h_m), 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
```

---

## Step 3: Scope Determination

*The pseudocode calls this `determine_scope(trigger, structured_context, recent_synthesis_history)`. Not every trigger should produce a synthesis. A refill of chronic metformin usually does not; an admission with multiple active comorbidities does. The scope gate is cheap, runs before any expensive retrieval, and is the biggest lever against alert fatigue.*

```python
def determine_scope(trigger: dict,
                    structured_context: dict,
                    recent_synthesis_history: list) -> dict:
    """
    Decide whether this trigger warrants a synthesis, and if so, which
    clinical scenarios the synthesis should address.

    Args:
        trigger:                  The trigger dict from Step 1.
        structured_context:       The normalized patient context from Step 2.
        recent_synthesis_history: Recent synthesis records for the same
                                  patient and encounter, used for
                                  suppression.

    Returns:
        Dict with synthesize (bool), scenarios (list), reason (str),
        intended_scope (str), and a trigger_signature used for
        duplicate-suppression comparisons.
    """
    decision = {
        "synthesize":       False,
        "scenarios":        [],
        "reason":           "",
        "intended_scope":   "medical_management",
        "trigger_signature": _compute_trigger_signature(trigger,
                                                        structured_context),
    }

    # Duplicate suppression: if an identical-signature synthesis was
    # produced recently for this patient-encounter, skip.
    now = datetime.datetime.now(timezone.utc)
    for prior in recent_synthesis_history:
        if prior.get("trigger_signature") == decision["trigger_signature"]:
            delivered_at = prior.get("delivered_at")
            if delivered_at:
                try:
                    prior_dt = datetime.datetime.fromisoformat(delivered_at)
                    age_minutes = (now - prior_dt).total_seconds() / 60.0
                    if age_minutes < SUPPRESSION_WINDOW_MINUTES:
                        decision["reason"] = "recently_synthesized_identical"
                        return decision
                except ValueError:
                    pass

    trigger_type = trigger.get("trigger_type", "")

    # Trigger-type-specific scope rules.
    if trigger_type == "admission":
        complex_enough = (
            len(structured_context.get("active_conditions", [])) >= 2
            or len(structured_context.get("current_medications", [])) >= 5
        )
        if complex_enough:
            decision["synthesize"] = True
            decision["scenarios"] = _derive_admission_scenarios(
                structured_context, trigger)
            decision["reason"] = "new_admission_with_clinical_complexity"

    elif trigger_type == "medication_order":
        proposed = (trigger.get("payload") or {}).get("proposed_medication")
        if proposed:
            proposed_class = _classify_drug(proposed)
            patient_relevance = _patient_has_relevant_conditions_for_drug(
                structured_context, proposed)
            if (proposed_class in HIGH_ALERT_DRUG_CLASSES
                    or patient_relevance):
                decision["synthesize"] = True
                decision["scenarios"] = [{
                    "scenario_type":   "new_medication_review",
                    "clinical_domain": _drug_class_to_domain(proposed_class),
                    "key_entities":    [proposed],
                    "retrieval_queries": [
                        f"appropriate use of {proposed.get('display')} "
                        f"in patient with relevant comorbidities",
                    ],
                }]
                decision["reason"] = "high_alert_or_context_relevant_order"

    elif trigger_type == "lab_result":
        lab = (trigger.get("payload") or {}).get("lab")
        if lab and _is_critical_lab(lab, structured_context):
            decision["synthesize"] = True
            decision["scenarios"] = _derive_lab_triggered_scenarios(
                lab, structured_context)
            decision["reason"] = "critical_lab_change"

    elif trigger_type == "clinician_request":
        question = (trigger.get("payload") or {}).get("question", "")
        decision["synthesize"] = True
        decision["scenarios"] = [{
            "scenario_type":     "clinician_requested",
            "clinical_domain":   "general",
            "key_entities":      [],
            "retrieval_queries": [question] if question else [],
        }]
        decision["reason"] = "explicit_clinician_request"

    return decision

def _compute_trigger_signature(trigger: dict, context: dict) -> str:
    """
    Stable hash-ish signature for duplicate-suppression comparisons.

    Two triggers with the same signature represent "the same synthesis
    question." Tune the inputs per scenario: the patient's medication
    list changes should produce a new signature; the current time should
    not.
    """
    key_parts = [
        trigger.get("trigger_type", ""),
        trigger.get("patient_id", ""),
        trigger.get("encounter_id", ""),
        str(sorted([m.get("rxnorm_code") or m.get("display") or ""
                    for m in context.get("current_medications", [])])),
        str(sorted([c.get("snomed_code") or c.get("display") or ""
                    for c in context.get("active_conditions", [])])),
    ]
    proposed = (trigger.get("payload") or {}).get("proposed_medication")
    if proposed:
        key_parts.append(proposed.get("rxnorm_code")
                         or proposed.get("display") or "")
    return "|".join(key_parts)[:250]  # cap length for DynamoDB index efficiency

def _derive_admission_scenarios(context: dict, trigger: dict) -> list:
    """
    Produce starter scenarios on admission based on active problems.

    Real implementations use a scenario-classification model (Step 5) on
    top of this; the rule-based starter here covers common cases.
    """
    scenarios = []
    for cond in context.get("active_conditions", []):
        display = (cond.get("display") or "").lower()
        if "sepsis" in display or "septic" in display:
            scenarios.append({
                "scenario_type":   "empiric_antibiotic",
                "clinical_domain": "infectious_disease",
                "key_entities":    [cond],
                "retrieval_queries": [
                    "empiric antibiotic selection for suspected sepsis"
                    " in patient with renal dysfunction",
                ],
            })
        if "heart failure" in display:
            scenarios.append({
                "scenario_type":   "chronic_disease_management",
                "clinical_domain": "cardiology",
                "key_entities":    [cond],
                "retrieval_queries": [
                    "guideline-directed medical therapy for HFrEF",
                ],
            })
    if not scenarios:
        scenarios.append({
            "scenario_type":     "medication_review",
            "clinical_domain":   "hospital_medicine",
            "key_entities":      context.get("current_medications", [])[:5],
            "retrieval_queries": ["medication reconciliation on admission"],
        })
    return scenarios

def _classify_drug(drug: dict) -> str | None:
    """
    Map a drug to a coarse therapeutic class. Production uses a drug
    database lookup (FDB or similar) keyed on RxNorm. This stub uses a
    name match for illustration.
    """
    name = ((drug.get("display") or "") + " "
            + (drug.get("class") or "")).lower()
    if any(k in name for k in ["warfarin", "apixaban", "rivaroxaban",
                               "dabigatran", "heparin"]):
        return "anticoagulant"
    if any(k in name for k in ["insulin"]):
        return "insulin"
    if any(k in name for k in ["morphine", "hydromorphone", "fentanyl"]):
        return "opioid_iv"
    return drug.get("class")

def _drug_class_to_domain(drug_class: str | None) -> str:
    """Map a drug class to a clinical domain for retrieval tagging."""
    mapping = {
        "anticoagulant":       "hematology",
        "chemotherapy":        "oncology",
        "insulin":             "endocrinology",
        "opioid_iv":           "pain_management",
        "antiarrhythmic":      "cardiology",
    }
    return mapping.get(drug_class or "", "general")

def _patient_has_relevant_conditions_for_drug(context: dict,
                                              drug: dict) -> bool:
    """
    Coarse relevance check: does the patient have conditions that make
    this drug's selection decision non-trivial? Real systems use a
    contraindication/relevance database; stub returns True for patients
    with CKD or elderly status as a conservative default.
    """
    age = (context.get("demographics") or {}).get("age")
    if age and age >= 75:
        return True
    egfr = (context.get("derived") or {}).get("egfr_ckd_epi_2021")
    if egfr is not None and egfr < CONSERVATIVE_RENAL_EGFR:
        return True
    return False

def _is_critical_lab(lab: dict, context: dict) -> bool:
    """
    Is this lab value clinically meaningful enough to warrant synthesis?

    Starter logic: common critical thresholds. Real systems tune per lab,
    per institution, and per patient (e.g., K+ 3.2 is concerning in
    general, but may not be in a chronic-hypokalemia patient already
    being repleted).
    """
    name = (lab.get("name") or "").lower()
    value = lab.get("value")
    if value is None:
        return False
    thresholds = {
        "potassium":   lambda v: v < 3.0 or v > 5.8,
        "sodium":      lambda v: v < 130 or v > 150,
        "creatinine":  lambda v: v > 2.5,
        "troponin_high_sens": lambda v: v > 52,
        "hemoglobin":  lambda v: v < 7.5,
    }
    check = thresholds.get(name)
    return bool(check and check(value))

def _derive_lab_triggered_scenarios(lab: dict, context: dict) -> list:
    """Starter lab-triggered scenarios; map labs to clinical questions."""
    name = (lab.get("name") or "").lower()
    mapping = {
        "potassium":  ("electrolyte_management", "hospital_medicine"),
        "sodium":     ("electrolyte_management", "hospital_medicine"),
        "creatinine": ("renal_injury_workup", "nephrology"),
        "troponin_high_sens": ("acs_workup", "cardiology"),
        "hemoglobin": ("anemia_workup", "hospital_medicine"),
    }
    scenario_type, domain = mapping.get(
        name, ("lab_result_review", "general"))
    return [{
        "scenario_type":   scenario_type,
        "clinical_domain": domain,
        "key_entities":    [lab],
        "retrieval_queries": [
            f"management of abnormal {name} = {lab.get('value')} "
            f"{lab.get('unit', '')} in hospitalized patient",
        ],
    }]
```

---

## Step 4: Deterministic Safety Checks

*The pseudocode calls this `run_deterministic_safety_checks(...)`. Before the LLM touches anything, do the checks that do not need an LLM: drug-drug interactions, allergy screens, renal and hepatic dosing flags, contraindications, duplicate therapy. These are structured-data queries against the Aurora drug database. Their outputs become hard inputs to the generation step; the model's job is to communicate them, not to derive them. Leaving safety to the model is how teams ship systems that miss interactions the model happened not to know about.*

```python
def run_deterministic_safety_checks(structured_context: dict,
                                     proposed_medications: list) -> dict:
    """
    Query the structured drug database for interactions, allergy
    conflicts, renal-dose flags, contraindications, and duplicate therapy.

    The findings returned here MUST appear in the final synthesis. Step 9
    (validation) enforces this. Do not rely on the model to derive safety
    findings from unstructured text.

    Args:
        structured_context:    The normalized patient context from Step 2.
        proposed_medications:  Drugs being proposed in this clinical
                               scenario; may be empty for a general
                               synthesis, populated for med-order triggers.

    Returns:
        Dict with lists of interactions, allergy_conflicts, renal_dose_flags,
        hepatic_dose_flags, contraindications, and duplicate_therapy.
    """
    findings = {
        "interactions":      [],
        "allergy_conflicts": [],
        "renal_dose_flags":  [],
        "hepatic_dose_flags": [],
        "contraindications": [],
        "duplicate_therapy": [],
    }

    current_meds = structured_context.get("current_medications", []) or []
    all_meds = current_meds + (proposed_medications or [])

    # --- 1. Drug-drug interactions: every pair in (current + proposed) ---
    for i in range(len(all_meds)):
        for j in range(i + 1, len(all_meds)):
            drug_a = all_meds[i]
            drug_b = all_meds[j]
            rx_a = drug_a.get("rxnorm_code")
            rx_b = drug_b.get("rxnorm_code")
            if not (rx_a and rx_b):
                continue
            rows = _execute_aurora_sql(
                sql=(
                    "SELECT rxnorm_a, rxnorm_b, severity, mechanism, "
                    "clinical_effect, management, source_citation, source_url "
                    "FROM drug_interactions "
                    "WHERE (rxnorm_a = :a AND rxnorm_b = :b) "
                    "   OR (rxnorm_a = :b AND rxnorm_b = :a)"
                ),
                parameters=[
                    {"name": "a", "value": {"stringValue": rx_a}},
                    {"name": "b", "value": {"stringValue": rx_b}},
                ],
            )
            for row in rows:
                findings["interactions"].append({
                    "drug_a":          drug_a,
                    "drug_b":          drug_b,
                    "severity":        row.get("severity"),
                    "mechanism":       row.get("mechanism"),
                    "clinical_effect": row.get("clinical_effect"),
                    "management":      row.get("management"),
                    "source":          row.get("source_citation"),
                    "source_url":      row.get("source_url"),
                })

    # --- 2. Allergy conflicts: each proposed drug vs allergy list ---
    for proposed in proposed_medications or []:
        for allergy in structured_context.get("allergies", []) or []:
            match = _drug_allergy_match(proposed, allergy)
            if match:
                findings["allergy_conflicts"].append({
                    "drug":         proposed,
                    "allergy":      allergy,
                    "match_type":   match,  # "exact" | "class" | "cross"
                    "severity":     allergy.get("reaction_severity"),
                })

    # --- 3. Renal dosing: each proposed drug vs current eGFR ---
    egfr = (structured_context.get("derived") or {}).get("egfr_ckd_epi_2021")
    if egfr is not None:
        for proposed in proposed_medications or []:
            rx = proposed.get("rxnorm_code")
            if not rx:
                continue
            rows = _execute_aurora_sql(
                sql=(
                    "SELECT rxnorm_code, egfr_lower, egfr_upper, "
                    "recommended_dose, contraindicated, notes, source_citation "
                    "FROM renal_dosing "
                    "WHERE rxnorm_code = :rx "
                    "  AND egfr_lower <= :egfr AND egfr_upper > :egfr"
                ),
                parameters=[
                    {"name": "rx", "value": {"stringValue": rx}},
                    {"name": "egfr", "value": {"doubleValue": float(egfr)}},
                ],
            )
            for row in rows:
                flag = {
                    "drug":              proposed,
                    "current_egfr":      egfr,
                    "recommended_dose":  row.get("recommended_dose"),
                    "contraindicated":   bool(row.get("contraindicated")),
                    "notes":             row.get("notes"),
                    "source":            row.get("source_citation"),
                }
                findings["renal_dose_flags"].append(flag)

    # --- 4. Contraindications: each proposed drug vs active problems ---
    active_conditions = structured_context.get("active_conditions", []) or []
    for proposed in proposed_medications or []:
        rx = proposed.get("rxnorm_code")
        if not rx:
            continue
        for cond in active_conditions:
            snomed = cond.get("snomed_code")
            if not snomed:
                continue
            rows = _execute_aurora_sql(
                sql=(
                    "SELECT rxnorm_code, snomed_code, type, rationale, "
                    "source_citation, source_url "
                    "FROM contraindications "
                    "WHERE rxnorm_code = :rx AND snomed_code = :snomed"
                ),
                parameters=[
                    {"name": "rx", "value": {"stringValue": rx}},
                    {"name": "snomed", "value": {"stringValue": snomed}},
                ],
            )
            for row in rows:
                findings["contraindications"].append({
                    "drug":               proposed,
                    "condition":          cond,
                    "contraindication_type": row.get("type"),
                    "rationale":          row.get("rationale"),
                    "source":             row.get("source_citation"),
                    "source_url":         row.get("source_url"),
                })

    # --- 5. Duplicate therapy: multiple drugs in the same class ---
    class_to_drugs = defaultdict(list)
    for m in all_meds:
        cls = _classify_drug(m)
        if cls:
            class_to_drugs[cls].append(m)
    for cls, drugs in class_to_drugs.items():
        if len(drugs) > 1:
            findings["duplicate_therapy"].append({
                "class": cls,
                "drugs": drugs,
            })

    logger.info(
        "Safety checks: %d interactions, %d allergy conflicts, "
        "%d renal flags, %d contraindications, %d duplicate-therapy",
        len(findings["interactions"]),
        len(findings["allergy_conflicts"]),
        len(findings["renal_dose_flags"]),
        len(findings["contraindications"]),
        len(findings["duplicate_therapy"]),
    )
    return findings

def _drug_allergy_match(drug: dict, allergy: dict) -> str | None:
    """
    Decide whether a drug conflicts with an allergy.

    Match types:
      - "exact": same RxNorm code
      - "class": same therapeutic class
      - "cross": known cross-reactivity (e.g., penicillin-cephalosporin)

    Real systems use a cross-reactivity table. This stub does a
    string-match fallback plus an exact RxNorm match.
    """
    drug_rx = drug.get("rxnorm_code")
    allergy_rx = allergy.get("substance_rxnorm")
    if drug_rx and allergy_rx and drug_rx == allergy_rx:
        return "exact"

    drug_name = (drug.get("display") or "").lower()
    allergy_name = (allergy.get("display") or "").lower()
    if allergy_name and allergy_name in drug_name:
        return "class"

    # Cross-reactivity stub: penicillin allergy + cephalosporin
    if "penicillin" in allergy_name and "cef" in drug_name:
        return "cross"
    return None
```

---

## Step 5: Scenario Classification and Retrieval Planning

*The pseudocode calls this `classify_and_plan(...)`. Given the patient state, the scope decision, and the safety findings, classify each scenario more precisely and build a retrieval plan: which queries to issue against guidelines and protocols, which structured lookups to do against the drug database, which metadata filters apply. A small model does the classification; a deterministic builder constructs the plan.*

```python
def classify_and_plan(structured_context: dict,
                      scope_decision: dict,
                      safety_findings: dict) -> list:
    """
    Classify each scenario and produce a structured retrieval plan.

    Returns:
        List of retrieval plans, one per refined scenario. Each plan has
        a scenario dict plus lists of guideline_queries, drug_db_lookups,
        protocol_searches, and a metadata_filters block.
    """
    scenarios_in = scope_decision.get("scenarios", []) or []
    if not scenarios_in:
        return []

    # Small-model classification refines the starter scenarios. The model
    # is constrained to return a JSON array matching the requested shape.
    classification_system = """You refine starter clinical scenarios for a CDS retrieval planner.

Return ONLY a JSON array. Each element refines one input scenario:
{
  "scenario_type": one of [empiric_antibiotic, chronic_disease_management,
                            oncology_therapy_selection, anticoagulation_management,
                            medication_review, dose_adjustment, diagnostic_workup,
                            preventive_care, perioperative_management,
                            electrolyte_management, acs_workup, renal_injury_workup,
                            anemia_workup, clinician_requested, other],
  "clinical_domain": one of [infectious_disease, cardiology, oncology, nephrology,
                              endocrinology, primary_care, hospital_medicine,
                              emergency, surgery, pediatrics, obstetrics,
                              psychiatry, pain_management, general],
  "key_entities": list of short labels for drugs, conditions, or findings central
                  to this scenario (strings),
  "retrieval_queries": 2-5 search-style queries a clinical reference librarian
                       would use to find the right guidelines or protocols
}"""

    user_prompt = (
        f"PATIENT CONTEXT:\n{json.dumps(structured_context, default=str)[:3000]}\n\n"
        f"STARTER SCENARIOS:\n{json.dumps(scenarios_in, default=str)}\n\n"
        f"SAFETY FINDINGS SUMMARY: "
        f"{len(safety_findings.get('interactions', []))} interactions, "
        f"{len(safety_findings.get('renal_dose_flags', []))} renal dose flags, "
        f"{len(safety_findings.get('contraindications', []))} contraindications.\n\n"
        f"Refine each starter scenario and return the JSON array."
    )

    classification_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens":        1500,
        "temperature":       0.0,
        "system":            classification_system,
        "messages":          [{"role": "user", "content": user_prompt}],
    })

    refined = scenarios_in  # fall-back
    try:
        response = bedrock_runtime.invoke_model(
            modelId=SMALL_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=classification_body,
        )
        payload = json.loads(response["body"].read())
        parsed = _parse_json_response(payload["content"][0]["text"])
        if isinstance(parsed, list) and parsed:
            refined = parsed
        elif isinstance(parsed, dict) and "scenarios" in parsed:
            refined = parsed["scenarios"]
    except ClientError as exc:
        logger.warning("Scenario refinement failed; using starter scenarios: %s",
                       exc)

    # Build a retrieval plan per refined scenario.
    plans = []
    population_tags = _derive_population_tags(structured_context)
    for scenario in refined:
        plan = {
            "scenario":          scenario,
            "guideline_queries": list(scenario.get("retrieval_queries") or []),
            "protocol_searches": list(scenario.get("retrieval_queries") or []),
            "drug_db_lookups":   _derive_drug_db_lookups(scenario,
                                                          structured_context,
                                                          safety_findings),
            "metadata_filters":  {
                "clinical_domain": scenario.get("clinical_domain", "general"),
                "population_tags": population_tags,
                "recency_years":   7,
                "preferred_authority_tiers": [
                    "institutional_protocol", "society_guideline",
                    "drug_database",
                ],
            },
        }
        plans.append(plan)

    logger.info("Built %d retrieval plans", len(plans))
    return plans

def _derive_population_tags(context: dict) -> list:
    """Infer population tags from demographics for metadata filtering."""
    tags = []
    demographics = context.get("demographics") or {}
    age = demographics.get("age")
    if isinstance(age, (int, float)):
        if age < 18:
            tags.append("pediatric")
        elif age >= 75:
            tags.extend(["geriatric", "adult"])
        elif age >= 65:
            tags.extend(["geriatric", "adult"])
        else:
            tags.append("adult")
    if demographics.get("pregnancy"):
        tags.append("pregnancy")
    egfr = (context.get("derived") or {}).get("egfr_ckd_epi_2021")
    if egfr is not None and egfr < 60:
        tags.append("ckd")
    return tags

def _derive_drug_db_lookups(scenario: dict, context: dict,
                            safety_findings: dict) -> list:
    """
    Build structured drug-DB lookups the retrieval step will run against
    Aurora. Interactions, renal dosing, and contraindications already ran
    in Step 4; this hook lets the planner request additional scenario-
    specific lookups (e.g., pediatric weight-based dosing tables for a
    pediatric scenario).
    """
    lookups = []
    scenario_type = scenario.get("scenario_type", "")
    if scenario_type == "empiric_antibiotic":
        # Pull renal dosing tables for common empiric antibiotics; the
        # retrieval step uses these to enrich the context for the model.
        for drug_name in ("piperacillin-tazobactam", "cefepime",
                          "ceftriaxone", "vancomycin", "meropenem"):
            lookups.append({
                "type":       "renal_dosing_lookup",
                "drug_name":  drug_name,
                "egfr":       (context.get("derived") or {}).get(
                                  "egfr_ckd_epi_2021"),
            })
    return lookups
```

---

## Step 6: Multi-Source Retrieval

*The pseudocode calls this `multi_source_retrieval(retrieval_plans)`. Parallel retrieval across the source stores. Hybrid search against guidelines and protocols on OpenSearch (dense vector plus BM25), structured queries against Aurora for drug-database records. Metadata filters drop out-of-population and stale sources before similarity computation.*

```python
def multi_source_retrieval(retrieval_plans: list) -> dict:
    """
    Run hybrid retrieval for each plan and return results keyed by
    scenario.

    Hybrid retrieval runs three retrieval modes:
      - Dense vector search against guideline embeddings
      - BM25 keyword search driven by scenario key entities
      - Structured SQL against the drug database for named lookups

    In production, the retrieval fan-out runs as a Step Functions Map
    state with bounded concurrency. The sequential Python loop here is
    fine for understanding the pattern.
    """
    client = _get_opensearch_client()
    results_per_scenario = {}

    for idx, plan in enumerate(retrieval_plans):
        scenario_id = f"scenario_{idx}"
        scenario = plan["scenario"]
        filters = plan["metadata_filters"]

        # --- Guideline retrieval: hybrid search ---
        guideline_chunks = _hybrid_search_index(
            client=client,
            index=OPENSEARCH_GUIDELINES_INDEX,
            queries=plan["guideline_queries"],
            entity_terms=scenario.get("key_entities", []),
            filters=filters,
            size=GUIDELINE_RETRIEVAL_SIZE,
        )

        # --- Protocol retrieval: hybrid search (smaller size) ---
        protocol_chunks = _hybrid_search_index(
            client=client,
            index=OPENSEARCH_PROTOCOLS_INDEX,
            queries=plan["protocol_searches"],
            entity_terms=scenario.get("key_entities", []),
            filters=filters,
            size=PROTOCOL_RETRIEVAL_SIZE,
        )

        # --- Structured drug-DB lookups requested by the plan ---
        drug_db_records = []
        for lookup in plan["drug_db_lookups"]:
            if lookup["type"] == "renal_dosing_lookup":
                egfr = lookup.get("egfr")
                drug_name = lookup.get("drug_name", "")
                if egfr is None:
                    continue
                # In production, drug_name -> rxnorm_code happens upstream.
                rows = _execute_aurora_sql(
                    sql=(
                        "SELECT rd.rxnorm_code, rd.egfr_lower, rd.egfr_upper, "
                        "rd.recommended_dose, rd.contraindicated, rd.notes, "
                        "rd.source_citation, d.display_name "
                        "FROM renal_dosing rd "
                        "JOIN drugs d ON d.rxnorm_code = rd.rxnorm_code "
                        "WHERE lower(d.display_name) LIKE :name_pattern "
                        "  AND rd.egfr_lower <= :egfr "
                        "  AND rd.egfr_upper > :egfr"
                    ),
                    parameters=[
                        {"name": "name_pattern",
                         "value": {"stringValue": f"%{drug_name.lower()}%"}},
                        {"name": "egfr",
                         "value": {"doubleValue": float(egfr)}},
                    ],
                )
                for row in rows:
                    row["_source_type"]    = "drug_database"
                    row["_record_type"]    = "renal_dosing"
                    drug_db_records.append(row)

        results_per_scenario[scenario_id] = {
            "scenario":         scenario,
            "guideline_chunks": guideline_chunks,
            "protocol_chunks":  protocol_chunks,
            "drug_db_records":  drug_db_records,
        }

    total_guidelines = sum(len(r["guideline_chunks"])
                           for r in results_per_scenario.values())
    total_protocols  = sum(len(r["protocol_chunks"])
                           for r in results_per_scenario.values())
    logger.info(
        "Retrieval: %d scenarios, %d guideline chunks, %d protocol chunks",
        len(results_per_scenario), total_guidelines, total_protocols,
    )
    return results_per_scenario

def _hybrid_search_index(client, index: str, queries: list,
                         entity_terms: list, filters: dict, size: int) -> list:
    """
    Run dense-vector and BM25 searches against a single OpenSearch index,
    then fuse results with reciprocal rank fusion.
    """
    if not queries:
        return []

    base_filter = _build_opensearch_filters(filters)

    ranked_lists = []

    # Dense-vector: one search per query variant.
    for query_text in queries:
        try:
            query_vector = _embed_text(query_text)
        except ClientError as exc:
            logger.warning("Embedding failed for '%s': %s", query_text, exc)
            continue

        knn_query = {
            "size": size,
            "query": {
                "bool": {
                    "must": [{"knn": {"embedding": {"vector": query_vector,
                                                     "k": size}}}],
                    "filter": base_filter,
                }
            },
            "_source": {"excludes": ["embedding"]},
        }
        try:
            resp = client.search(index=index, body=knn_query)
            hits = resp.get("hits", {}).get("hits", [])
            ranked_lists.append(
                [{**h["_source"],
                  "_score":           h["_score"],
                  "_retrieval_mode":  f"vector:{query_text[:40]}"}
                 for h in hits]
            )
        except Exception as exc:  # Don't let one failure blow up the pipeline
            logger.warning("kNN search on %s failed: %s", index, exc)

    # BM25: driven by entity terms.
    entity_text_tokens = []
    for e in entity_terms or []:
        if isinstance(e, dict):
            entity_text_tokens.append(e.get("display") or e.get("text") or "")
        else:
            entity_text_tokens.append(str(e))
    entity_text = " ".join(t for t in entity_text_tokens if t).strip()

    if entity_text:
        bm25_query = {
            "size": size,
            "query": {
                "bool": {
                    "must": [{
                        "multi_match": {
                            "query":  entity_text,
                            "fields": ["recommendation_text^2",
                                       "section^1.5", "issuing_body"],
                            "type":   "best_fields",
                        }
                    }],
                    "filter": base_filter,
                }
            },
            "_source": {"excludes": ["embedding"]},
        }
        try:
            resp = client.search(index=index, body=bm25_query)
            hits = resp.get("hits", {}).get("hits", [])
            ranked_lists.append(
                [{**h["_source"],
                  "_score":          h["_score"],
                  "_retrieval_mode": "bm25:entities"}
                 for h in hits]
            )
        except Exception as exc:
            logger.warning("BM25 search on %s failed: %s", index, exc)

    # Reciprocal rank fusion across all ranked lists.
    fused_scores = defaultdict(float)
    seen = {}
    K = 60
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            cid = hit.get("chunk_id")
            if not cid:
                continue
            fused_scores[cid] += 1.0 / (K + rank)
            if cid not in seen:
                seen[cid] = hit

    sorted_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)
    fused = []
    for cid in sorted_ids:
        doc = dict(seen[cid])
        doc["_rrf_score"] = fused_scores[cid]
        fused.append(doc)
    return fused

def _build_opensearch_filters(filters: dict) -> list:
    """Translate our filters dict into OpenSearch filter clauses."""
    clauses = []

    clinical_domain = filters.get("clinical_domain")
    if clinical_domain and clinical_domain != "general":
        clauses.append({"term": {"clinical_domain": clinical_domain}})

    population_tags = filters.get("population_tags") or []
    if population_tags:
        clauses.append({"terms": {"population_tags": population_tags}})

    recency_years = filters.get("recency_years")
    if recency_years:
        now_year = datetime.datetime.now(timezone.utc).year
        clauses.append({
            "range": {"publication_year": {"gte": now_year - recency_years}}
        })

    return clauses
```

---

## Step 7: Rank and Filter

*The pseudocode calls this `rank_and_filter(results_per_scenario, structured_context)`. Rank retrieved guideline and protocol chunks by a combination of source authority, recency, patient-specificity, and retrieval score. Structured drug-DB records flow through unranked since they are deterministic lookups.*

```python
def rank_and_filter(results_per_scenario: dict,
                    structured_context: dict) -> dict:
    """
    Rank guideline and protocol chunks; trim to top-K for generation.

    Structured drug-DB records pass through unranked; they are
    authoritative by construction and must all reach the generation step.
    """
    population_tags = _derive_population_tags(structured_context)

    for scenario_id, results in results_per_scenario.items():
        for chunk in results.get("guideline_chunks", []):
            chunk["_combined_score"] = _score_chunk(chunk, population_tags)
        for chunk in results.get("protocol_chunks", []):
            chunk["_combined_score"] = _score_chunk(chunk, population_tags)

        results["guideline_chunks"] = sorted(
            results.get("guideline_chunks", []),
            key=lambda c: c.get("_combined_score", 0),
            reverse=True,
        )[:TOP_GUIDELINE_CHUNKS]
        results["protocol_chunks"] = sorted(
            results.get("protocol_chunks", []),
            key=lambda c: c.get("_combined_score", 0),
            reverse=True,
        )[:TOP_PROTOCOL_CHUNKS]

    logger.info("Ranked and trimmed retrieval results per scenario")
    return results_per_scenario

def _score_chunk(chunk: dict, population_tags: list) -> float:
    """
    Weight authority, recency, population specificity, and retrieval score
    into a single combined score. Tune weights based on clinical feedback.
    """
    authority = SOURCE_AUTHORITY_SCORE.get(chunk.get("source_type", ""), 1)

    now_year = datetime.datetime.now(timezone.utc).year
    pub_year = chunk.get("publication_year") or now_year - 10
    try:
        recency = max(0.0, 1.0 - (now_year - int(pub_year)) / 10.0)
    except (TypeError, ValueError):
        recency = 0.3

    # Population specificity: match is better than no match; unknown is neutral.
    chunk_pops = set(chunk.get("population_tags") or [])
    if population_tags and chunk_pops:
        if any(tag in chunk_pops for tag in population_tags):
            population_match = 1.0
        else:
            population_match = 0.3  # mismatch; de-prioritize
    else:
        population_match = 0.6

    rrf = float(chunk.get("_rrf_score", 0.0))

    return (
        3.0 * authority
        + 1.5 * recency
        + 1.2 * population_match
        + 10.0 * rrf
    )
```

---

## Step 8: Grounded Synthesis

*The pseudocode calls this `generate_synthesis(...)`. Build the generation prompt with the patient context, the retrieved sources with stable identifiers, and the deterministic safety findings. The prompt enforces citation discipline, forces options-not-directives framing, requires every safety finding to appear in the output, and instructs the model to surface contradictions honestly. Apply a Bedrock Guardrail with contextual grounding as the outer safety net; the validator in Step 9 is the inner check.*

````python
def generate_synthesis(structured_context: dict,
                      retrieval_results: dict,
                      safety_findings: dict,
                      scope_decision: dict,
                      regeneration_hint: str = "") -> dict:
    """
    Produce the synthesized recommendation set via the generation model.

    Returns:
        Dict with status (GENERATED | GROUNDING_REJECTED | PARSE_FAILED |
        GENERATION_FAILED), the parsed synthesis, and an id_to_source map
        the validator will use to confirm citations.
    """
    # Build the sources block with stable [src_N] identifiers.
    sources_block, id_to_source = _build_sources_block(retrieval_results)
    if not id_to_source:
        return {
            "status": "NO_EVIDENCE",
            "synthesis": {
                "overall_assessment": (
                    "No relevant guideline or protocol content was retrieved "
                    "for this scenario. The corpus may not cover this topic "
                    "or the scope may need refinement. Clinician judgment is "
                    "required; this CDS surface cannot propose options "
                    "without retrieved evidence."
                ),
                "recommendations": [],
                "safety_findings_included": [],
                "overall_uncertainty":  "high",
                "uncertainty_rationale": "No retrieved evidence.",
            },
            "id_to_source": {},
        }

    safety_block = _format_safety_findings_for_prompt(safety_findings,
                                                      id_to_source)

    intended_scope = scope_decision.get("intended_scope", "medical_management")

    synthesis_system = f"""You are producing a clinical decision support synthesis for a practicing clinician.
The clinician is the decision-maker; your output describes options, evidence, and considerations.
You do not prescribe or direct.

HARD REQUIREMENTS:
- Every recommendation or factual claim must cite at least one source by identifier
  (e.g., [src_5]). Do not invent citations. Do not use sources not listed in the
  RETRIEVED SOURCES block.
- Preserve exact wording for drug names, doses, frequencies, and numerical thresholds.
  Do not paraphrase dosing. Quote it verbatim from the cited source.
- Include every item from the SAFETY FINDINGS block in the output. None may be
  omitted. If a safety finding applies to a recommendation you make, surface it
  next to that recommendation in the "relevant_safety_findings" field.
- Frame recommendations as options with clear trade-offs, not as directives.
  Use language like "Option A involves...", "Consider...", "The guideline supports..."
  Do NOT use these phrases in your own voice (outside of quoted guideline text):
  "you should", "administer", "give", "prescribe", "start immediately",
  "stop immediately", "switch to". Verbatim quotes from guidelines may contain
  directive language; quote them with quotation marks if so.
- When sources disagree, surface the disagreement. List each position separately
  in the "competing_recommendations" field. Do not collapse to a false consensus.
- When the retrieved sources do not directly address a scenario, say so explicitly
  in the "insufficient_evidence_items" field. Do not extrapolate beyond what the
  sources support.
- Include an uncertainty assessment for each recommendation: how directly the
  retrieved evidence addresses this specific patient.
- Do not recommend actions outside the intended CDS scope: {intended_scope}.
- Indicate population alignment ("matches" | "partial" | "mismatch" | "unknown")
  for each recommendation based on whether cited sources' study populations
  reflect this patient.

OUTPUT FORMAT: Return ONLY a valid JSON object (no markdown code fences) with:
{{
  "overall_assessment": "2-4 sentence summary of the clinical situation",
  "recommendations": [
    {{
      "title": "short title of the option",
      "recommendation_text": "description of the option with citations",
      "reasoning": "why this option is supported by the sources",
      "source_citations": ["src_N", ...],
      "relevant_safety_findings": ["text of the safety finding(s) represented here"],
      "evidence_directness": "direct" | "extrapolated" | "insufficient",
      "population_alignment": "matches" | "partial" | "mismatch" | "unknown",
      "tier": "critical" | "important" | "informational",
      "caveats": "specific caveats, trade-offs, prerequisites"
    }}
  ],
  "safety_findings_included": [
    {{
      "finding": "verbatim or near-verbatim description of the safety finding",
      "source_citations": ["src_N", ...],
      "where_in_output": "which recommendation(s) it appears in, or 'standalone'"
    }}
  ],
  "competing_recommendations": [
    {{
      "description": "short description of the disagreement",
      "position_a": {{"text": "...", "sources": ["src_N", ...]}},
      "position_b": {{"text": "...", "sources": ["src_N", ...]}}
    }}
  ],
  "what_to_ask_or_check": ["clinician-facing questions to consider"],
  "insufficient_evidence_items": ["things the retrieved sources don't address"],
  "overall_uncertainty": "low" | "moderate" | "high",
  "uncertainty_rationale": "brief explanation of uncertainty level"
}}"""

    synthesis_user = f"""PATIENT CONTEXT:
{json.dumps(structured_context, default=str)[:4000]}

SCENARIOS IN SCOPE:
{json.dumps(scope_decision.get('scenarios', []), default=str)}

SAFETY FINDINGS (must all appear in output):
{safety_block}

RETRIEVED SOURCES:
{sources_block}

{('REGENERATION HINT: ' + regeneration_hint) if regeneration_hint else ''}

Produce the synthesis now. Output ONLY the JSON object."""

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens":        5000,
        # Low temperature: we want faithful, conservative synthesis, not
        # creative variation. CDS is not a brainstorming task.
        "temperature":       0.1,
        "system":            synthesis_system,
        "messages":          [{"role": "user", "content": synthesis_user}],
    }

    invoke_kwargs = {
        "modelId":     GENERATION_MODEL_ID,
        "contentType": "application/json",
        "accept":      "application/json",
        "body":        json.dumps(request_body),
    }

    if GUARDRAIL_ID and GUARDRAIL_VERSION:
        invoke_kwargs["guardrailIdentifier"] = GUARDRAIL_ID
        invoke_kwargs["guardrailVersion"]    = GUARDRAIL_VERSION

    try:
        response = bedrock_runtime.invoke_model(**invoke_kwargs)
        payload = json.loads(response["body"].read())
    except ClientError as exc:
        logger.error("Synthesis generation failed: %s", exc)
        return {"status": "GENERATION_FAILED", "error": str(exc),
                "synthesis": {}, "id_to_source": id_to_source}

    # Guardrail intervention check. Field shape varies with Guardrail
    # configuration; check both common patterns defensively.
    guardrail_action = (
        payload.get("amazon-bedrock-guardrailAction")
        or payload.get("stop_reason")
    )
    if guardrail_action in ("INTERVENED", "guardrail_intervened"):
        logger.warning("Guardrail intervened on synthesis")
        return {"status": "GROUNDING_REJECTED",
                "synthesis": {}, "id_to_source": id_to_source}

    raw_text = payload["content"][0]["text"]
    synthesis = _parse_json_response(raw_text)
    if not synthesis:
        return {"status": "PARSE_FAILED",
                "synthesis": {},
                "id_to_source": id_to_source,
                "raw_text_snippet": raw_text[:500]}

    logger.info(
        "Generated synthesis: %d recommendations, %d safety findings, "
        "%d competing, uncertainty=%s",
        len(synthesis.get("recommendations", [])),
        len(synthesis.get("safety_findings_included", [])),
        len(synthesis.get("competing_recommendations", [])),
        synthesis.get("overall_uncertainty"),
    )
    return {
        "status":       "GENERATED",
        "synthesis":    synthesis,
        "id_to_source": id_to_source,
    }

def _build_sources_block(retrieval_results: dict) -> tuple[str, dict]:
    """
    Build the prompt's sources block and an id_to_source mapping the
    validator later uses to confirm citations. Source IDs are stable
    within a single generation call.
    """
    lines = []
    id_to_source = {}
    source_id = 1

    for scenario_id, results in retrieval_results.items():
        for chunk in results.get("guideline_chunks", []):
            tag = f"src_{source_id}"
            lines.append(
                f"[{tag}] (Type: Guideline, Issuer: "
                f"{chunk.get('issuing_body', 'unknown')}, "
                f"Year: {chunk.get('publication_year', 'unknown')}, "
                f"Section: {chunk.get('section', 'unknown')}, "
                f"Tier: {chunk.get('evidence_tier', 'ungraded')})\n"
                f"Content: {chunk.get('recommendation_text', '')}"
            )
            id_to_source[tag] = {**chunk, "_kind": "guideline"}
            source_id += 1

        for chunk in results.get("protocol_chunks", []):
            tag = f"src_{source_id}"
            lines.append(
                f"[{tag}] (Type: Institutional Protocol, Name: "
                f"{chunk.get('source_id', 'unknown')}, Version: "
                f"{chunk.get('publication_year', 'unknown')})\n"
                f"Content: {chunk.get('recommendation_text', '')}"
            )
            id_to_source[tag] = {**chunk, "_kind": "protocol"}
            source_id += 1

        for record in results.get("drug_db_records", []):
            tag = f"src_{source_id}"
            lines.append(
                f"[{tag}] (Type: Drug Database, Record: "
                f"{record.get('_record_type', 'unknown')})\n"
                f"Content: {json.dumps(record, default=str)}"
            )
            id_to_source[tag] = {**record, "_kind": "drug_db"}
            source_id += 1

    return "\n\n".join(lines), id_to_source

def _format_safety_findings_for_prompt(safety_findings: dict,
                                        id_to_source: dict) -> str:
    """Human-readable flat list of safety findings for the prompt."""
    lines = []
    for item in safety_findings.get("interactions", []):
        lines.append(
            f"- Interaction: {item['drug_a'].get('display')} + "
            f"{item['drug_b'].get('display')} | severity="
            f"{item.get('severity')} | effect={item.get('clinical_effect')} | "
            f"management={item.get('management')}"
        )
    for item in safety_findings.get("allergy_conflicts", []):
        lines.append(
            f"- Allergy conflict: {item['drug'].get('display')} vs allergy "
            f"'{item['allergy'].get('display')}' ({item.get('match_type')})"
        )
    for item in safety_findings.get("renal_dose_flags", []):
        contraind = " (CONTRAINDICATED)" if item.get("contraindicated") else ""
        lines.append(
            f"- Renal dose flag: {item['drug'].get('display')} at eGFR="
            f"{item.get('current_egfr')} | recommended dose: "
            f"{item.get('recommended_dose')}{contraind}"
        )
    for item in safety_findings.get("contraindications", []):
        lines.append(
            f"- Contraindication: {item['drug'].get('display')} in "
            f"{item['condition'].get('display')} "
            f"({item.get('contraindication_type')})"
        )
    for item in safety_findings.get("duplicate_therapy", []):
        drug_names = ", ".join(d.get("display") or "" for d in item.get("drugs", []))
        lines.append(f"- Duplicate therapy in class {item.get('class')}: {drug_names}")

    if not lines:
        return "(no deterministic safety findings for this scenario)"
    return "\n".join(lines)
```

---

## Step 9: Post-Generation Validation

*The pseudocode calls this `validate_synthesis(...)`. Belt-and-suspenders on top of Guardrails. For every recommendation, verify citations exist in the retrieved set. For every dose quoted, verify it appears verbatim in a structured drug-DB record. Every safety finding from Step 4 must be represented in the synthesis. No recommendation may propose a drug that contradicts a contraindication from Step 4. No directive phrases in the model's own voice. No out-of-scope recommendations. Validation failures trigger regeneration or escalation.*

```python
def validate_synthesis(synthesis: dict,
                       id_to_source: dict,
                       safety_findings: dict,
                       structured_context: dict,
                       scope_decision: dict,
                       retry_count: int = 0) -> dict:
    """
    Run the layered validation checks on the generated synthesis.

    Returns:
        Dict with status (VALIDATED | RETRY_NEEDED | REVIEW_REQUIRED),
        the list of unverified issues, and a regeneration hint if
        retrying.
    """
    unverified = []
    recommendations = synthesis.get("recommendations") or []

    # --- 1. Citation existence and coverage ---
    for rec in recommendations:
        citations = rec.get("source_citations") or []
        for cit in citations:
            if cit not in id_to_source:
                unverified.append({
                    "rec":      rec.get("title"),
                    "issue":    "citation_not_in_retrieved_set",
                    "citation": cit,
                    "severity": "HIGH",
                })
        if not citations:
            unverified.append({
                "rec":      rec.get("title"),
                "issue":    "recommendation_without_citations",
                "severity": "HIGH",
            })

    # --- 2. Dose verbatim check ---
    # Any numeric dose in the recommendation text should appear verbatim
    # in at least one cited source. Real validators also handle unit
    # normalization (mg vs milligram) and trailing-zero variants.
    dose_regex = re.compile(
        r"\d+(?:\.\d+)?\s*(?:mg|g|mcg|units|mL|IU)"
        r"(?:\s+(?:IV|PO|IM|SC))?"
        r"(?:\s+(?:q\d+h|daily|BID|TID|QID))?",
        flags=re.IGNORECASE,
    )
    for rec in recommendations:
        text = rec.get("recommendation_text", "")
        doses_in_rec = dose_regex.findall(text)
        citations = rec.get("source_citations") or []
        for dose in doses_in_rec:
            found = False
            for cit in citations:
                source = id_to_source.get(cit, {})
                if source.get("_kind") != "drug_db":
                    continue
                source_serialized = json.dumps(source, default=str)
                if dose in source_serialized:
                    found = True
                    break
                # Whitespace-normalized fallback
                if re.sub(r"\s+", "", dose) in re.sub(r"\s+", "",
                                                      source_serialized):
                    found = True
                    break
            if not found:
                unverified.append({
                    "rec":      rec.get("title"),
                    "issue":    "dose_not_in_structured_source",
                    "dose":     dose,
                    "severity": "HIGH",
                })

    # --- 3. Every safety finding must be represented ---
    all_safety_items = (
        safety_findings.get("interactions", [])
        + safety_findings.get("allergy_conflicts", [])
        + safety_findings.get("renal_dose_flags", [])
        + safety_findings.get("hepatic_dose_flags", [])
        + safety_findings.get("contraindications", [])
        + safety_findings.get("duplicate_therapy", [])
    )
    representations = _flatten_safety_representations(synthesis)
    for item in all_safety_items:
        signature = _safety_finding_signature(item)
        if not any(signature in rep for rep in representations):
            unverified.append({
                "issue":    "safety_finding_not_represented",
                "finding":  signature,
                "severity": "HIGH",
            })

    # --- 4. No recommendation contradicts a contraindication/allergy ---
    drugs_flagged_contra = {
        (item["drug"].get("display") or "").lower()
        for item in safety_findings.get("contraindications", [])
        if item.get("contraindication_type") == "absolute"
    }
    drugs_flagged_allergy = {
        (item["drug"].get("display") or "").lower()
        for item in safety_findings.get("allergy_conflicts", [])
    }
    for rec in recommendations:
        rec_text_lower = (rec.get("recommendation_text") or "").lower()
        for drug_name in drugs_flagged_contra:
            if drug_name and drug_name in rec_text_lower:
                safety_acks = " ".join(
                    rec.get("relevant_safety_findings") or []
                ).lower()
                if "contraindicat" not in safety_acks:
                    unverified.append({
                        "rec":      rec.get("title"),
                        "issue":    "contradicts_contraindication",
                        "drug":     drug_name,
                        "severity": "HIGH",
                    })
        for drug_name in drugs_flagged_allergy:
            if drug_name and drug_name in rec_text_lower:
                safety_acks = " ".join(
                    rec.get("relevant_safety_findings") or []
                ).lower()
                if "allerg" not in safety_acks:
                    unverified.append({
                        "rec":      rec.get("title"),
                        "issue":    "contradicts_allergy",
                        "drug":     drug_name,
                        "severity": "HIGH",
                    })

    # --- 5. Directive language in the model's own voice ---
    for rec in recommendations:
        text = rec.get("recommendation_text") or ""
        unquoted = _strip_quoted_passages(text)
        for phrase in DIRECTIVE_PHRASES:
            if re.search(rf"\b{re.escape(phrase)}\b", unquoted,
                         flags=re.IGNORECASE):
                unverified.append({
                    "rec":      rec.get("title"),
                    "issue":    "directive_language_in_model_voice",
                    "phrase":   phrase,
                    "severity": "MEDIUM",  # regulatory-posture concern
                })

    # --- 6. Scope compliance ---
    for rec in recommendations:
        text = rec.get("recommendation_text") or ""
        for pattern in OUT_OF_SCOPE_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                unverified.append({
                    "rec":      rec.get("title"),
                    "issue":    "out_of_scope",
                    "pattern":  pattern,
                    "severity": "MEDIUM",
                })

    high_count = sum(1 for u in unverified if u["severity"] == "HIGH")
    medium_count = sum(1 for u in unverified if u["severity"] == "MEDIUM")

    if high_count == 0 and medium_count <= max(1, len(recommendations) // 5):
        logger.info("Validation PASSED (0 high, %d medium)", medium_count)
        return {"status": "VALIDATED", "unverified": unverified}

    if retry_count < MAX_GENERATION_ATTEMPTS - 1:
        hint = _build_validation_hint(unverified)
        logger.info(
            "Validation flagged %d HIGH / %d MEDIUM; requesting retry",
            high_count, medium_count,
        )
        return {"status": "RETRY_NEEDED",
                "unverified": unverified,
                "suggested_prompt_augmentation": hint}

    logger.warning(
        "Validation exhausted retries; routing to review "
        "(%d HIGH, %d MEDIUM)", high_count, medium_count,
    )
    return {"status": "REVIEW_REQUIRED", "unverified": unverified}

def _flatten_safety_representations(synthesis: dict) -> list:
    """
    Collect all text that could represent a safety finding in the output:
    the dedicated safety_findings_included list and the per-recommendation
    relevant_safety_findings list.
    """
    representations = []
    for item in synthesis.get("safety_findings_included") or []:
        representations.append((item.get("finding") or "").lower())
    for rec in synthesis.get("recommendations") or []:
        for f in rec.get("relevant_safety_findings") or []:
            representations.append((f or "").lower())
    return representations

def _safety_finding_signature(item: dict) -> str:
    """
    Short, searchable string that must appear (possibly paraphrased) in
    the synthesis output. Conservative: we look for key drug names or
    condition names and trust the representation check to be fuzzy.
    """
    if "drug_a" in item and "drug_b" in item:
        return (
            (item["drug_a"].get("display") or "").lower()
            + " " + (item["drug_b"].get("display") or "").lower()
        )
    if "drug" in item and "allergy" in item:
        return (
            (item["drug"].get("display") or "").lower() + " "
            + (item["allergy"].get("display") or "").lower()
        )
    if "drug" in item and "condition" in item:
        return (
            (item["drug"].get("display") or "").lower() + " "
            + (item["condition"].get("display") or "").lower()
        )
    if "drug" in item:
        return (item["drug"].get("display") or "").lower()
    if "class" in item:
        return (item.get("class") or "").lower()
    return json.dumps(item, default=str).lower()[:60]

def _strip_quoted_passages(text: str) -> str:
    """
    Remove content inside double-quotes so the directive-phrase scan
    doesn't flag verbatim guideline quotes.
    """
    return re.sub(r'"[^"]*"', "", text)

def _build_validation_hint(unverified: list) -> str:
    """Compact hint for the next regeneration attempt."""
    issue_types = set()
    lines = ["The previous draft had validation failures. Fix these specifically:"]
    for u in unverified:
        key = u.get("issue")
        if key in issue_types:
            continue
        issue_types.add(key)
        if key == "citation_not_in_retrieved_set":
            lines.append(
                "- You cited source IDs not in the retrieved set. Only cite "
                "sources that appear with a [src_N] tag in the RETRIEVED "
                "SOURCES block."
            )
        elif key == "recommendation_without_citations":
            lines.append(
                "- Every recommendation must cite at least one source. No "
                "uncited recommendations allowed."
            )
        elif key == "dose_not_in_structured_source":
            lines.append(
                "- Doses in recommendations must appear verbatim in a "
                "cited drug-database record. Do not paraphrase dosing; "
                "quote it exactly from the structured source."
            )
        elif key == "safety_finding_not_represented":
            lines.append(
                "- Every item in the SAFETY FINDINGS block must appear in "
                "the output (either in safety_findings_included or in a "
                "recommendation's relevant_safety_findings). Do not omit any."
            )
        elif key == "contradicts_contraindication":
            lines.append(
                "- You proposed a drug that is contraindicated for this "
                "patient without acknowledging the contraindication. Either "
                "remove the recommendation or make the contraindication "
                "explicit in relevant_safety_findings."
            )
        elif key == "contradicts_allergy":
            lines.append(
                "- You proposed a drug that conflicts with a documented "
                "allergy without acknowledging the allergy. Either remove "
                "the recommendation or make the allergy explicit in "
                "relevant_safety_findings."
            )
        elif key == "directive_language_in_model_voice":
            lines.append(
                "- Remove directive language in your own voice ('administer', "
                "'you should', 'give', 'start', 'switch to'). Frame as "
                "options: 'Consider', 'Option A involves', 'The guideline "
                "supports'. Verbatim guideline quotes may include directives "
                "but must be inside double quotes."
            )
        elif key == "out_of_scope":
            lines.append(
                "- Remove recommendations outside this CDS surface's scope "
                "(medical management). Surgical and procedural recommendations "
                "do not belong here; suggest consultation instead if relevant."
            )
    return "\n".join(lines)
```

---

## Step 10: Tier, Suppress, and Render

*The pseudocode calls this `tier_suppress_render(...)`. Score each recommendation against the patient's prior engagement history for this encounter. Suppress or downgrade recommendations already acknowledged or previously rejected. If nothing material is new, suppress the whole synthesis. Otherwise render with reasoning foregrounded, sources clickable, uncertainty explicit, and options framed as options.*

```python
def tier_suppress_render(synthesis: dict,
                          structured_context: dict,
                          patient_id: str,
                          encounter_id: str,
                          id_to_source: dict,
                          synthesis_id: str) -> dict:
    """
    Apply tiering, suppression, and rendering. Returns the rendered
    payload for clinician delivery, or a suppression record if nothing
    material is new.
    """
    # Look up this patient+encounter's recent synthesis history for
    # suppression/engagement context.
    prior = _query_patient_history(patient_id, encounter_id)

    active_recs = []
    for rec in synthesis.get("recommendations", []) or []:
        rec["_delivery_tier"] = _determine_delivery_tier(rec, prior)
        if rec["_delivery_tier"] not in ("acknowledged", "rejected"):
            active_recs.append(rec)

    if not active_recs:
        logger.info("All recommendations in suppressed tiers; suppressing synthesis")
        return {"status": "SUPPRESSED", "reason": "no_new_material"}

    # Replace source_id citations with display numbers and build the bibliography.
    numbered = {}
    bibliography = []
    next_num = 1

    def _replace_citations(text: str) -> str:
        nonlocal next_num
        for cit in re.findall(r"\[src_\d+\]|src_\d+", text):
            # Normalize to canonical form with brackets
            cit_bare = cit.strip("[]")
            if cit_bare not in id_to_source:
                continue
            if cit_bare not in numbered:
                numbered[cit_bare] = next_num
                source = id_to_source[cit_bare]
                bibliography.append({
                    "number":              next_num,
                    "formatted":           _format_source_for_bibliography(source),
                    "source_type":         source.get("_kind"),
                    "source_url":          source.get("source_url")
                                           or source.get("source_citation"),
                    "evidence_tier":       source.get("evidence_tier"),
                    "publication_year":    source.get("publication_year"),
                })
                next_num += 1
            text = text.replace(f"[{cit_bare}]", f"[{numbered[cit_bare]}]")
            text = text.replace(cit_bare, f"[{numbered[cit_bare]}]")
        return text

    rendered_recs = []
    for rec in active_recs:
        rec_rendered = dict(rec)
        for field in ("recommendation_text", "reasoning", "caveats"):
            rec_rendered[field] = _replace_citations(rec_rendered.get(field) or "")
        rec_rendered.pop("source_citations", None)  # replaced by numbered refs
        rendered_recs.append(rec_rendered)

    # Also rewrite the competing-recommendations citations to numbered refs
    rendered_competing = []
    for entry in synthesis.get("competing_recommendations", []) or []:
        e = dict(entry)
        for side in ("position_a", "position_b"):
            if side in e and isinstance(e[side], dict):
                e[side] = dict(e[side])
                e[side]["text"] = _replace_citations(e[side].get("text") or "")
                e[side].pop("sources", None)
        rendered_competing.append(e)

    rendered_safety = []
    for item in synthesis.get("safety_findings_included", []) or []:
        rendered_safety.append({
            "finding":         _replace_citations(item.get("finding") or ""),
            "where_in_output": item.get("where_in_output"),
        })

    rendered = {
        "synthesis_id":          synthesis_id,
        "patient_id":            patient_id,
        "encounter_id":          encounter_id,
        "overall_assessment":    synthesis.get("overall_assessment"),
        "recommendations":       rendered_recs,
        "safety_findings":       rendered_safety,
        "competing_recommendations": rendered_competing,
        "what_to_ask_or_check":  synthesis.get("what_to_ask_or_check") or [],
        "insufficient_evidence_items":
            synthesis.get("insufficient_evidence_items") or [],
        "overall_uncertainty":   synthesis.get("overall_uncertainty"),
        "uncertainty_rationale": synthesis.get("uncertainty_rationale"),
        "bibliography":          bibliography,
        "disclaimer": (
            "This is a decision support synthesis. Review the sources "
            "before acting. The clinician is the decision-maker."
        ),
    }

    return {"status": "RENDERED", "rendered": rendered}

def _determine_delivery_tier(rec: dict, prior: list) -> str:
    """
    Compare this recommendation to prior engagement history and assign a
    delivery tier.

    Tiers:
      - "new_critical":  critical, not previously surfaced
      - "new_important": important, not previously surfaced
      - "changed":       previously surfaced, material change
      - "acknowledged":  previously acknowledged; suppress unless changed
      - "rejected":      previously rejected with reason; suppress
    """
    base_tier = rec.get("tier") or "informational"
    rec_signature = (rec.get("title") or "").lower()

    for p in prior:
        for prior_rec in p.get("recommendations", []) or []:
            prior_sig = (prior_rec.get("title") or "").lower()
            if prior_sig and prior_sig == rec_signature:
                engagement = prior_rec.get("engagement") or {}
                if engagement.get("rejected"):
                    return "rejected"
                if engagement.get("acknowledged"):
                    return "acknowledged"
                return "changed"

    if base_tier == "critical":
        return "new_critical"
    if base_tier == "important":
        return "new_important"
    return "informational"

def _format_source_for_bibliography(source: dict) -> str:
    """Produce a human-readable bibliography entry for a source."""
    kind = source.get("_kind")
    if kind == "guideline":
        return (
            f"{source.get('issuing_body', 'Unknown issuer')}. "
            f"{source.get('section', 'Guideline section')}. "
            f"{source.get('publication_year', 'n.d.')}."
        )
    if kind == "protocol":
        return (
            f"Institutional Protocol: {source.get('source_id', 'unnamed')}, "
            f"rev. {source.get('publication_year', 'n.d.')}."
        )
    if kind == "drug_db":
        return (
            f"Drug Database Record ({source.get('_record_type', 'unknown')}) "
            f"- {source.get('source_citation') or source.get('display_name') or ''}"
        )
    return "Source"

def _query_patient_history(patient_id: str, encounter_id: str) -> list:
    """
    Pull recent synthesis records for this patient+encounter from
    DynamoDB.

    In production, index the table with a GSI on (patient_id,
    encounter_id, delivered_at). This stub returns an empty list so the
    example runs without pre-populated history.
    """
    # TODO: implement the real GSI query; stub returns empty.
    return []
```

---

## Step 11: Archive and Log

*The pseudocode calls this `archive_and_log(...)`. Persist the complete provenance: trigger, patient context snapshot, retrieval trace, safety findings, generation prompt version, raw model output, validation result, final rendering, and delivery metadata. Emit CloudWatch metrics. Issue a feedback token for clinician engagement capture.*

```python
def archive_and_log(synthesis_id: str,
                     rendered: dict,
                     trace: dict,
                     clinician_id: str,
                     patient_id: str) -> dict:
    """
    Persist the full trace to S3 and update the DynamoDB synthesis record.

    The archive is the authoritative record for compliance, auditability,
    and iteration. Retain per your institution's medical-record and
    regulatory retention policy (typically years).
    """
    now_iso = _now_iso()

    rendered_key = f"syntheses/{synthesis_id}/rendered.json"
    s3_client.put_object(
        Bucket=SYNTHESIS_ARCHIVE_BUCKET,
        Key=rendered_key,
        Body=json.dumps(rendered, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=SYNTHESIS_ARCHIVE_CMK_ARN,
    )

    trace_key = f"syntheses/{synthesis_id}/trace.json"
    trace_payload = {
        "synthesis_id":        synthesis_id,
        "trigger":             trace.get("trigger"),
        "scope_decision":      trace.get("scope_decision"),
        "retrieval_plan_summary": [
            {"scenario": p["scenario"],
             "filters":  p["metadata_filters"]}
            for p in trace.get("retrieval_plans", [])
        ],
        "retrieved_source_ids": trace.get("retrieved_source_ids", []),
        "safety_findings":     trace.get("safety_findings"),
        "prompt_version":      trace.get("prompt_version", "v1"),
        "generation_model":    GENERATION_MODEL_ID,
        "small_model":         SMALL_MODEL_ID,
        "embedding_model":     EMBEDDING_MODEL_ID,
        "raw_generation_output": trace.get("raw_generation_output"),
        "validation_result":   trace.get("validation_result"),
        "attempts":            trace.get("attempts", 1),
        "clinician_id":        clinician_id,
        "patient_id":          patient_id,
        "generated_at":        now_iso,
    }
    s3_client.put_object(
        Bucket=SYNTHESIS_ARCHIVE_BUCKET,
        Key=trace_key,
        Body=json.dumps(trace_payload, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=SYNTHESIS_ARCHIVE_CMK_ARN,
    )

    syntheses_table = dynamodb.Table(SYNTHESES_TABLE)
    syntheses_table.update_item(
        Key={"synthesis_id": synthesis_id},
        UpdateExpression=(
            "SET #s = :s, rendered_s3_key = :rk, trace_s3_key = :tk, "
            "delivered_at = :d, uncertainty = :u, "
            "num_recommendations = :nr"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s":  "DELIVERED",
            ":rk": rendered_key,
            ":tk": trace_key,
            ":d":  now_iso,
            ":u":  rendered.get("overall_uncertainty") or "unknown",
            ":nr": len(rendered.get("recommendations", [])),
        },
    )

    # Emit CloudWatch metrics.
    try:
        cloudwatch.put_metric_data(
            Namespace="ClinicalDecisionSupport",
            MetricData=[
                {
                    "MetricName": "SynthesisDelivered",
                    "Dimensions": [
                        {"Name": "UncertaintyTier",
                         "Value": rendered.get("overall_uncertainty", "unknown")},
                    ],
                    "Value": 1.0,
                    "Unit":  "Count",
                },
                {
                    "MetricName": "RecommendationsDelivered",
                    "Value":      float(len(rendered.get("recommendations",
                                                         []))),
                    "Unit":       "Count",
                },
                {
                    "MetricName": "SafetyFindingsSurfaced",
                    "Value":      float(len(rendered.get("safety_findings",
                                                         []))),
                    "Unit":       "Count",
                },
            ],
        )
    except ClientError as exc:
        logger.warning("Metric emission failed: %s", exc)

    feedback_token = str(uuid.uuid4())
    logger.info(
        "Synthesis %s archived (DELIVERED, %d recommendations)",
        synthesis_id, len(rendered.get("recommendations", [])),
    )
    return {
        "status":         "DELIVERED",
        "rendered_key":   rendered_key,
        "trace_key":      trace_key,
        "feedback_token": feedback_token,
    }
```

---

## Putting It All Together

Here is the full pipeline assembled into a single callable function. Runs all eleven steps sequentially for one trigger. In production, each step is a Step Functions state with its own retry policy; deterministic safety checks fan out via a parallel Map state; multi-source retrieval fans out per scenario; the generation-validation retry loop is a proper state-machine loop with a bounded counter. The sequential Python version below is fine for understanding the flow.

```python
def run_cds_synthesis(trigger: dict,
                      proposed_medications: list | None = None) -> dict:
    """
    Run the full CDS synthesis pipeline for one trigger.

    Steps (matching the Recipe 2.9 pseudocode):
      1.  Trigger and fetch patient context
      2.  Normalize and structure patient facts
      3.  Scope determination
      4.  Deterministic safety checks
      5.  Scenario classification and retrieval planning
      6.  Multi-source retrieval
      7.  Rank and filter
      8.  Grounded synthesis (with 8+9 loop on validation failure)
      9.  Post-generation validation
      10. Tier, suppress, render
      11. Archive and log

    Args:
        trigger:              Trigger dict (see Step 1).
        proposed_medications: Optional list of drugs being proposed in
                              this scenario. Empty for general syntheses,
                              populated for medication-order triggers.

    Returns:
        Dict with pipeline status, synthesis_id, and the rendered payload
        (or a suppression/failure record).
    """
    start = time.time()

    # Step 1
    print("Step 1: Triggering synthesis and fetching patient context...")
    s1 = trigger_synthesis(trigger)
    synthesis_id = s1["synthesis_id"]
    if s1["status"] == "DUPLICATE_SUPPRESSED":
        return {"status": "DUPLICATE_SUPPRESSED", "synthesis_id": synthesis_id}
    if s1["status"] != "CONTEXT_FETCHED":
        return {"status": "FAILED", "stage": "step_1", "synthesis_id": synthesis_id,
                "detail": s1}
    print(f"  synthesis_id={synthesis_id}, "
          f"{len(s1['patient_bundle'].get('entry', []))} resources fetched")

    # Step 2
    print("Step 2: Normalizing patient context...")
    structured_context = normalize_patient_context(s1["patient_bundle"])

    # Step 3
    print("Step 3: Determining scope...")
    prior_history = _query_patient_history(
        trigger.get("patient_id", ""),
        trigger.get("encounter_id", ""),
    )
    scope_decision = determine_scope(trigger, structured_context,
                                     prior_history)
    if not scope_decision["synthesize"]:
        syntheses_table = dynamodb.Table(SYNTHESES_TABLE)
        syntheses_table.update_item(
            Key={"synthesis_id": synthesis_id},
            UpdateExpression="SET #s = :s, suppression_reason = :r",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "SUPPRESSED_BY_SCOPE",
                ":r": scope_decision.get("reason", "unknown"),
            },
        )
        print(f"  Scope determined: no synthesis "
              f"(reason={scope_decision.get('reason')})")
        return {"status": "SUPPRESSED", "synthesis_id": synthesis_id,
                "reason": scope_decision.get("reason")}
    print(f"  {len(scope_decision['scenarios'])} scenarios in scope: "
          f"{scope_decision.get('reason')}")

    # Step 4
    print("Step 4: Running deterministic safety checks...")
    safety_findings = run_deterministic_safety_checks(
        structured_context, proposed_medications or [],
    )

    # Step 5
    print("Step 5: Classifying scenarios and planning retrieval...")
    retrieval_plans = classify_and_plan(structured_context, scope_decision,
                                        safety_findings)

    # Step 6
    print("Step 6: Running multi-source retrieval...")
    retrieval_results = multi_source_retrieval(retrieval_plans)

    # Step 7
    print("Step 7: Ranking and filtering retrieval results...")
    retrieval_results = rank_and_filter(retrieval_results, structured_context)

    # Steps 8-9: generation + validation loop
    generation_result = None
    validation_result = None
    regeneration_hint = ""
    attempts = 0

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        attempts = attempt
        print(f"Step 8 (attempt {attempt}): Generating synthesis...")
        generation_result = generate_synthesis(
            structured_context=structured_context,
            retrieval_results=retrieval_results,
            safety_findings=safety_findings,
            scope_decision=scope_decision,
            regeneration_hint=regeneration_hint,
        )

        if generation_result["status"] == "GROUNDING_REJECTED":
            regeneration_hint = (
                "The previous draft was rejected by the grounding check. "
                "Stick strictly to content explicitly present in the "
                "retrieved sources. Do not add facts beyond what the "
                "sources support."
            )
            continue
        if generation_result["status"] == "NO_EVIDENCE":
            # Render the no-evidence synthesis directly.
            rendered = generation_result["synthesis"]
            break
        if generation_result["status"] != "GENERATED":
            break

        print(f"  Generated synthesis with "
              f"{len(generation_result['synthesis'].get('recommendations', []))} "
              f"recommendations")

        print(f"Step 9 (attempt {attempt}): Validating synthesis...")
        validation_result = validate_synthesis(
            synthesis=generation_result["synthesis"],
            id_to_source=generation_result["id_to_source"],
            safety_findings=safety_findings,
            structured_context=structured_context,
            scope_decision=scope_decision,
            retry_count=attempt - 1,
        )
        print(f"  Validation status: {validation_result['status']}")

        if validation_result["status"] == "VALIDATED":
            break
        if validation_result["status"] == "REVIEW_REQUIRED":
            break
        regeneration_hint = validation_result.get(
            "suggested_prompt_augmentation", "",
        )

    if not generation_result or generation_result["status"] not in (
        "GENERATED", "NO_EVIDENCE",
    ):
        syntheses_table = dynamodb.Table(SYNTHESES_TABLE)
        syntheses_table.update_item(
            Key={"synthesis_id": synthesis_id},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "GENERATION_FAILED"},
        )
        return {"status": "GENERATION_FAILED",
                "synthesis_id": synthesis_id}

    # --- Orchestration gate (Step 9.5 in the recipe pseudocode) ---
    # If validation exhausted retries, route to human review.
    # This synthesis does NOT proceed to tiering, rendering, or delivery.
    # The clinician UI never sees it. A clinical reviewer triages offline.
    if validation_result and validation_result["status"] == "REVIEW_REQUIRED":
        syntheses_table = dynamodb.Table(SYNTHESES_TABLE)
        syntheses_table.update_item(
            Key={"synthesis_id": synthesis_id},
            UpdateExpression="SET #s = :s, review_reason = :r",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "ROUTED_TO_REVIEW",
                ":r": json.dumps(validation_result.get("unverified", [])),
            },
        )
        # Archive the trace for audit under a distinct S3 prefix
        review_trace_key = f"review-queue/{synthesis_id}/trace.json"
        s3_client.put_object(
            Bucket=SYNTHESIS_ARCHIVE_BUCKET,
            Key=review_trace_key,
            Body=json.dumps({
                "synthesis_id":        synthesis_id,
                "trigger":             trigger,
                "validation_result":   validation_result,
                "raw_generation":      generation_result.get("synthesis"),
                "routed_at":           _now_iso(),
            }, default=str).encode(),
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=SYNTHESIS_ARCHIVE_CMK_ARN,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        logger.warning(
            "Synthesis %s routed to human review (%d unverified findings)",
            synthesis_id, len(validation_result.get("unverified", [])),
        )
        return {"status": "ROUTED_TO_REVIEW",
                "synthesis_id": synthesis_id,
                "unverified": validation_result.get("unverified", []),
                "processing_time_ms": elapsed_ms}

    if generation_result["status"] == "NO_EVIDENCE":
        # Skip tiering; render the no-evidence placeholder directly.
        rendered = {
            "synthesis_id":       synthesis_id,
            "patient_id":         trigger.get("patient_id"),
            "encounter_id":       trigger.get("encounter_id"),
            "overall_assessment": generation_result["synthesis"].get("overall_assessment"),
            "recommendations":    [],
            "safety_findings":    [],
            "competing_recommendations": [],
            "what_to_ask_or_check": [],
            "insufficient_evidence_items": [],
            "overall_uncertainty": "high",
            "uncertainty_rationale": "No retrieved evidence.",
            "bibliography":       [],
            "disclaimer":         "No evidence retrieved; clinician judgment required.",
        }
    else:
        # Step 10
        print("Step 10: Tiering and rendering...")
        tier_result = tier_suppress_render(
            synthesis=generation_result["synthesis"],
            structured_context=structured_context,
            patient_id=trigger.get("patient_id", ""),
            encounter_id=trigger.get("encounter_id", ""),
            id_to_source=generation_result["id_to_source"],
            synthesis_id=synthesis_id,
        )
        if tier_result["status"] == "SUPPRESSED":
            syntheses_table = dynamodb.Table(SYNTHESES_TABLE)
            syntheses_table.update_item(
                Key={"synthesis_id": synthesis_id},
                UpdateExpression="SET #s = :s, suppression_reason = :r",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": "SUPPRESSED_MINOR_UPDATE",
                    ":r": tier_result.get("reason", "unknown"),
                },
            )
            elapsed_ms = int((time.time() - start) * 1000)
            print(f"  Suppressed: {tier_result.get('reason')}")
            return {"status": "SUPPRESSED", "synthesis_id": synthesis_id,
                    "reason": tier_result.get("reason"),
                    "processing_time_ms": elapsed_ms}
        rendered = tier_result["rendered"]

    # Step 11
    print("Step 11: Archiving and logging...")
    trace = {
        "trigger":         trigger,
        "scope_decision":  scope_decision,
        "retrieval_plans": retrieval_plans,
        "retrieved_source_ids": list(
            generation_result.get("id_to_source", {}).keys()
        ),
        "safety_findings": safety_findings,
        "prompt_version":  "v1",
        "raw_generation_output": generation_result.get("synthesis"),
        "validation_result": validation_result,
        "attempts":        attempts,
    }
    archive_result = archive_and_log(
        synthesis_id=synthesis_id,
        rendered=rendered,
        trace=trace,
        clinician_id=trigger.get("clinician_id", "unknown"),
        patient_id=trigger.get("patient_id", "unknown"),
    )

    elapsed_ms = int((time.time() - start) * 1000)
    print(f"\nDone. Processing time: {elapsed_ms} ms")

    return {
        "status":            "DELIVERED",
        "synthesis_id":      synthesis_id,
        "rendered":          rendered,
        "rendered_key":      archive_result["rendered_key"],
        "trace_key":         archive_result["trace_key"],
        "feedback_token":    archive_result["feedback_token"],
        "attempts":          attempts,
        "processing_time_ms": elapsed_ms,
    }

# --- Example usage ---
if __name__ == "__main__":
    # All clinical content below is SYNTHETIC. Do not use real patient data
    # in development or testing. This example assumes:
    #   - OpenSearch index cds-guidelines with guideline chunks and
    #     embeddings, and cds-institutional-protocols with protocol content
    #   - Aurora PostgreSQL drug database with drug_interactions,
    #     renal_dosing, contraindications tables populated
    #   - DynamoDB tables cds-syntheses and cds-patient-history created
    #   - An S3 bucket for the synthesis archive with SSE-KMS configured
    #   - A HealthLake datastore with FHIR patient resources (or the
    #     _fetch_fhir_bundle_from_healthlake stub returning synthetic data)
    #
    # Without these preconditions, the pipeline will either return
    # NO_EVIDENCE from retrieval or fail at the first AWS call.

    trigger = {
        "trigger_type": "clinician_request",
        "patient_id":   "pt_illustrative_74m",
        "encounter_id": "enc_illustrative_2amidiocu",
        "clinician_id": "CLN-HOSPITALIST-042",
        "payload": {
            "question": (
                "Empiric antibiotic selection for 74-year-old man with "
                "presumed urinary source sepsis, CKD stage 4 (eGFR 28), "
                "atrial fibrillation on apixaban, HFrEF, sulfa allergy "
                "(rash), history of C. diff 2 years ago."
            ),
        },
    }

    # A proposed_medications list is appropriate for medication-order
    # triggers; for this clinician_request we leave it empty and let the
    # model's synthesis propose options.
    result = run_cds_synthesis(trigger, proposed_medications=[])

    print("\n" + "=" * 60)
    print("RESULT SUMMARY:")
    print("=" * 60)
    print(json.dumps({
        "status":            result.get("status"),
        "synthesis_id":      result.get("synthesis_id"),
        "attempts":          result.get("attempts"),
        "processing_time_ms": result.get("processing_time_ms"),
    }, indent=2, default=str))

    if result.get("rendered"):
        print("\n" + "-" * 60)
        print("ASSESSMENT:")
        print("-" * 60)
        print(result["rendered"].get("overall_assessment", ""))

        print("\n" + "-" * 60)
        print("RECOMMENDATIONS:")
        print("-" * 60)
        for rec in result["rendered"].get("recommendations", [])[:3]:
            print(f"\n- {rec.get('title')} "
                  f"[tier={rec.get('tier')}, "
                  f"uncertainty={rec.get('evidence_directness')}]")
            print(f"  {rec.get('recommendation_text', '')[:400]}")

        print("\n" + "-" * 60)
        print("BIBLIOGRAPHY:")
        print("-" * 60)
        for entry in result["rendered"].get("bibliography", []):
            print(f"  [{entry['number']}] ({entry.get('source_type')}) "
                  f"{entry['formatted']}")
```

---

## The Gap Between This and Production

Run this end-to-end against populated OpenSearch and Aurora stores, a HealthLake datastore, and a test Bedrock model, and you'll see the shape: trigger received, patient context fetched, normalized, scope checked, safety findings computed deterministically, scenarios classified, multi-source retrieval fanned out, synthesis generated with citation discipline, validated for citations and safety coverage, tiered against prior engagement, rendered with numbered citations, archived with full provenance. The distance between this and a real hospital deployment is substantial. Here's where the gap lives.

**Corpus ingestion is where the real work starts.** This example assumes the OpenSearch guidelines and protocols indexes already exist and the Aurora drug database already has interaction, renal-dosing, and contraindication tables populated. Building those corpora is 50-70% of the total effort. Guideline ingestion involves parsing long PDF documents into recommendation-grained chunks, tagging each chunk with population, evidence tier, clinical domain, and issuing body, embedding with a medical-aware embedder, and keeping up with guideline updates (annual to biennial cycles with interim updates). Drug database ingestion involves licensing negotiations with commercial vendors, ETL pipelines from licensed data feeds, and ongoing sync as new drugs, new interactions, and new package-insert updates publish. Build ingestion as a separate Step Functions workflow with EventBridge-scheduled rebuilds, and budget generously.

**Source licensing compliance.** Lexicomp, Micromedex, First Databank, and Clinical Pharmacology drug databases have expensive licenses with specific redistribution and API-use terms. Society guidelines from NCCN, UpToDate, DynaMed, and some specialty societies require member or institutional subscriptions and restrict redistribution. FDA structured product labels and USPSTF recommendations are public. Maintain a license registry for every source, enforce redistribution constraints at retrieval time (rendering licensed content to a clinician inside the institution may be allowed; syndicating through a third-party product usually is not), and audit quarterly.

**FDA CDS exemption documentation.** The four-part exemption in the 21st Century Cures Act is the regulatory posture this CDS surface is built for. The exemption relies on the clinician being able to independently review the basis for each recommendation. Concretely, the UI has to foreground reasoning and sources, not conclusions; single-click acceptance with hidden reasoning is a regulatory risk. Retain documentation that describes scope, source transparency, UI design, clinician acceptance workflow, and the exemption determination. If a prompt change or scope expansion later narrows the clinician-review posture, re-run the regulatory review. This is not optional.

**HealthLake integration is a stub.** The `_fetch_fhir_bundle_from_healthlake` helper returns a synthetic bundle. A real integration uses SigV4-signed HTTPS requests to the HealthLake datastore endpoint (or a FHIR client library), handles authorization via the EHR's OAuth2 flow if querying EHR FHIR directly, copes with FHIR resource dialects (Epic and Cerner disagree on status codes and code systems), and has retry logic for transient failures. Build a FHIR-client service with explicit timeouts, structured error handling, and observability.

**The scope gate needs clinical ownership.** The rule-based scope logic here is a starter. Clinical leadership has to own the scope policy: which scenarios deserve synthesis, what the per-patient trigger cap is, which encounter types are explicitly out of scope, which critical labs fire the pipeline. Build the scope policy as a data-driven configuration (DynamoDB table or parameter store) that clinical leadership can maintain without engineering deploys. Review and adjust quarterly.

**The drug-interaction SQL is the floor, not the ceiling.** Real drug databases have richer schemas: pharmacogenomic context, disease-state modifiers, dose-dependent interaction severity, temporal profiles (a new interaction that became relevant last month), and management recommendations with grade levels. Your queries should take advantage of the schema. For cross-reactivity (penicillin-cephalosporin, sulfa-sulfa-hypoglycemic), use a cross-reactivity table, not a string-match. The stub in this example is illustrative only.

**Bedrock Guardrails contextual grounding is non-optional.** The example sets `GUARDRAIL_ID = None`. For production, configure a Guardrail with contextual grounding enabled at a strict threshold (0.85+) using the combined sources+safety block as the grounding context. Pair the Guardrail with the validator in Step 9 as defense in depth: the Guardrail catches gross hallucination; the validator catches precise citation and numeric mismatches that the Guardrail's soft scoring sometimes misses.

**The validator upgrades.** The validator uses substring checks for numerics and naive safety-finding signature matching. Upgrade to embedding-based semantic similarity for representation checks (a safety finding may be paraphrased; token-level matching misses paraphrases). Add unit-aware numeric comparison (mg vs milligram vs μg). Add temporal logic for "recent" vs "prior" guidelines. Every validator upgrade should be accompanied by a regression suite of labeled examples so improvements don't cause regressions in unrelated failure modes.

**Step Functions orchestration.** The sequential Python in this example is a learning artifact. Production pipelines run each step as a Step Functions state; the deterministic safety checks fan out via a parallel Branch state; multi-source retrieval fans out per scenario via a Map state; the generation-validation loop is a proper state-machine loop with a bounded counter. The human-review escalation is a wait-for-task-token state. Step Functions makes the flow debuggable, resumable, and auditable; retrofitting onto a tangled Python orchestration is a rewrite.

**Prompt versioning from day one.** The generation prompt in Step 8 is version 1. It will evolve as you encounter failure modes. Store the prompt text in SSM Parameter Store or AppConfig with versioning, stamp every delivered synthesis with the prompt version that produced it, and run regression tests before promoting a new prompt version. Prompt changes that affect clinical recommendations need clinical review; build the review workflow explicitly.

**PHI minimization in prompts.** The prompts here include the patient context verbatim. Bedrock under BAA is HIPAA-eligible so this is compliant, but the minimum-necessary principle argues for sending less. Redact patient name, MRN, and other direct identifiers before sending; the model does not need them to synthesize recommendations. Substitute back during rendering if needed. This narrows the blast radius if Bedrock model-invocation logging is enabled for quality monitoring; ensure log destinations use the same KMS-encryption and retention policies as the archive.

**Feedback and post-market surveillance.** The `feedback_token` in Step 11 is the seed for a feedback workflow that does not exist in this example. Production needs: clinician-facing feedback capture (viewed, read the reasoning, accepted, modified, rejected with documented reason), clinical-reviewer triage of flagged syntheses, categorization of failure modes (retrieval miss, synthesis error, irrelevance, wrong tier), and a prioritized improvement backlog with visible closure to clinicians. Without this loop, feedback accumulates and the system plateaus. For a regulatory-exempt CDS, the surveillance data is also the basis for demonstrating that the system is performing as claimed.

**EHR workflow integration.** CDS that lives in a separate browser tab is CDS that doesn't get read. SMART on FHIR (EHR-launched apps) and CDS Hooks (EHR-triggered CDS calls at specific workflow points) are the integration standards that work across major EHRs. Plan integration as a first-class project. An excellent synthesis pipeline wired to a second-screen review UI underperforms a mediocre synthesis wired into the order-entry flow, because workflow beats accuracy for adoption.

**Alert fatigue calibration.** The suppression logic uses a fixed `SUPPRESSION_WINDOW_MINUTES`. Real suppression tuning requires per-scenario analysis of which recommendations help vs annoy, A/B testing of trigger thresholds, and ongoing engagement metrics (are clinicians reading recommendations we surface, are the suppressed cases ones that would have helped, etc.). Monitor engagement metrics per recommendation type and adjust suppression thresholds continuously. The day you stop watching alert fatigue is the day it starts growing.

**Clinical validation studies before broad deployment.** Before widescale deployment, a CDS system needs clinical validation. Build a curated set of patient-scenario pairs with expert-reviewed right-answer ranges. Run the system; have clinicians review outputs; quantify agreement; iterate on retrieval, ranking, prompts, and validation until agreement is acceptable. This is slow, expensive, non-negotiable, and takes 4-8 weeks of clinical expert time per major scenario category. Budget clinical-reviewer time as an ongoing cost, not a one-time validation.

**Cost monitoring and runaway loops.** `MAX_GENERATION_ATTEMPTS` caps the retry loop at the code level. Add per-user/per-patient-day rate limits at the API Gateway layer to prevent a misconfigured client or looping trigger from burning through budget. Track cost per scenario category, per clinical domain, and per encounter-day in CloudWatch. A steady-state cost of $0.15-$1.20 per synthesis is fine; a runaway scenario that produces 20 syntheses for one patient in a day at $0.80 each is a budget-model failure, not a quality signal.

**DynamoDB Decimal gotcha.** The `_to_decimal_safe` helper routes floats through `Decimal(str(value))` to avoid binary-precision issues and the `TypeError: Float types are not supported` that DynamoDB raises on Python floats. Muscle memory: every `put_item` and `update_item` with numeric fields goes through it. The first time you forget, you get an opaque error in production that's embarrassing to debug.

**JSON parsing resilience.** The `_parse_json_response` helper strips common markdown wrappers. In production, on a hard parse failure, the correct fallback is to send the raw model output back to the model with a "fix the JSON structure; preserve content" instruction. Models are good at self-correcting structural errors, and this saves a full regeneration cycle for recoverable formatting issues.

**VPC, encryption, and audit.** This example calls AWS APIs without VPC configuration. Production Lambda runs in private subnets with interface endpoints for Bedrock Runtime, Bedrock Agent Runtime (if using Knowledge Bases), Comprehend Medical, HealthLake, Step Functions, KMS, Secrets Manager, CloudWatch Logs, and EventBridge; gateway endpoints for S3 and DynamoDB; and VPC-only OpenSearch and Aurora. All S3 buckets use SSE-KMS with customer-managed keys (distinct CMKs for corpus vs PHI archive). DynamoDB encryption at rest uses a CMK. CloudTrail data events are enabled for every Bedrock invocation, every S3 object access, every DynamoDB read/write, and every Secrets Manager retrieval. The audit requirement is non-negotiable; the storage cost is meaningful at volume.

**Testing with synthetic data.** There are no tests in this example. A production pipeline has unit tests for FHIR parsing, eGFR and BMI calculation, normalization, validator logic, and JSON parsing; integration tests against test OpenSearch and Aurora instances with small synthetic corpora; regression tests that hold known-good syntheses stable through prompt and model changes; and clinical-validation tests against an expert-curated patient scenario set. Never use real patient audio, PHI, or live EHR data in development environments. Synthea-generated FHIR bundles are the standard synthetic source.

**Observability and SLOs.** Reasonable targets for production: 95th-percentile end-to-end latency under 25 seconds, validation pass rate above 90% first attempt, safety-finding coverage at 100% (every deterministic finding appears in every delivered synthesis), fraction of syntheses routed to human review below 10%, citation fidelity at 1.0 (every rendered citation exists in the retrieved set), and clinician acceptance rate tracked and reviewed monthly. Publish these as CloudWatch SLOs, alert on drift, and close the loop back to pipeline improvements. Without SLOs, problems surface as clinician complaints, and by then the trust is already damaged.

**Model-ID lifecycle.** The Bedrock model IDs in this example will be replaced as newer versions launch. Store model IDs in SSM Parameter Store or AppConfig, not in code. Before flipping production, run the full regression suite (unit tests + clinical validation set) against the new model. Skipping this is how teams discover at 2 AM that the new model version interprets a critical prompt instruction differently. Cross-region inference profile IDs (prefixed `us.` or `eu.`) are increasingly required in many regions; plan for it.

**The clinician is the decision-maker.** This point appears throughout the recipe and throughout this code. The AI synthesizes options, surfaces sources, presents reasoning, and flags safety findings. The clinician reviews, audits, and decides. Never build a UI that hides the reasoning behind a single-click "accept." Never build a prompt that shifts from options language to directives. Never let prompt iteration drift toward the prescriptive. Every line of this code assumes the clinician sits between the synthesis and the patient. Every deployment must enforce it.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 2.9: Clinical Decision Support Synthesis](chapter02.09-clinical-decision-support-synthesis) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
