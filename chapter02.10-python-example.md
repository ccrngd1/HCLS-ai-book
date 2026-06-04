# Recipe 2.10: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative sketch of the pseudocode walkthrough from Recipe 2.10. It shows one way you could translate the multi-modal clinical reasoning pipeline into working Python using Amazon Bedrock, Amazon HealthLake, Amazon HealthImaging, Amazon Comprehend Medical, Amazon OpenSearch Service, Amazon Aurora PostgreSQL (pgvector), S3, DynamoDB, and Step Functions. It is NOT production-ready. There is no cleared imaging AI vendor integration, no ECG foundation model endpoint, no real HealthImaging DICOM workflow, no Step Functions orchestration wired end-to-end, no SMART-on-FHIR EHR launch, no PACS deep-linking, no validated regulatory posture, no clinical validation against expert-reviewed scenarios, and no post-market surveillance plumbing. Think of it as a whiteboard diagram in code: useful for seeing the shape of the reasoning pipeline, not something you'd route real ED patients through.
>
> The pipeline maps to the nine pseudocode steps from the main recipe: start the reasoning run, parallel modality ingestion (imaging, ECG, labs+vitals, notes, structured context), normalize and build the modality inventory, scope gate, deterministic safety checks (reused from Recipe 2.9's pattern), multi-source retrieval, the reasoning layer with grounded multi-hypothesis synthesis, post-generation validation, and tier+render+archive. Validation failures trigger regeneration up to a cap, then route to human review.
>
> All clinical content in the examples below is SYNTHETIC. The patient context, imaging reports, ECG findings, lab values, guideline citations, and reasoning outputs are illustrative only. Do not treat any specific finding, differential, or next-step recommendation in this file as real clinical guidance. A production system grounds every claim in actual retrieved content from the patient's real longitudinal record plus a current, licensed authoritative corpus, then routes the output through validated clinical review before any clinician sees it.
>
> Because this is a capstone recipe, many of the patterns here (deterministic safety checks, structured drug data, grounded synthesis with citation discipline, validation of numeric verbatim preservation) are the same patterns from Recipe 2.9. Where that's the case, this file references 2.9 rather than duplicating the code. The new material here is about the modality-specific ingestion, the modality inventory and scope gate, the cross-modality reasoning prompt, and the multi-modal-specific validations (missing modality acknowledgment, cross-modality contradiction detection, graded-term preservation).

---

## Setup

You'll need the AWS SDK for Python and a few utility libraries:

```bash
pip install boto3 opensearch-py requests-aws4auth psycopg2-binary
```

Your environment needs credentials configured (environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` (reasoning generation, auxiliary small-model tasks, embeddings)
- `bedrock:ApplyGuardrail` (contextual grounding check on the reasoning output; non-optional for clinician-facing multi-modal output)
- `healthlake:ReadResource`, `healthlake:SearchWithGet` (FHIR patient context, observations, notes as DocumentReferences, imaging as DocumentReferences with study instance UID)
- `medical-imaging:GetImageSetMetadata`, `medical-imaging:SearchImageSets` (HealthImaging DICOM metadata)
- `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM`, `comprehendmedical:InferSNOMEDCT` (entity extraction on notes, radiology reports, ECG reports, pathology reports)
- `es:ESHttpPost`, `es:ESHttpGet` (OpenSearch hybrid retrieval for guidelines, protocols, case analogs; `aoss:*` equivalents for OpenSearch Serverless)
- `rds-data:ExecuteStatement` for Aurora Data API (drug interactions, renal dosing, contraindications per Recipe 2.9)
- `sagemaker:InvokeEndpoint` (optional: self-hosted modality models for imaging, ECG, or pathology foundation models)
- `s3:GetObject`, `s3:PutObject` (per-run archive with full provenance trace)
- `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:UpdateItem`, `dynamodb:Query` (run state, per-patient reasoning history for suppression, clinician engagement)
- `secretsmanager:GetSecretValue` (cleared imaging AI vendor API keys, ECG model API keys, drug-database credentials)
- `kms:Decrypt`, `kms:GenerateDataKey` (customer-managed keys for all PHI at rest; distinct keys per modality if retention policies differ)
- `states:StartExecution` (Step Functions orchestration for parallel modality ingestion)
- `logs:*`, `cloudwatch:PutMetricData` (operational metrics and HIPAA audit logs)

You also need Bedrock model access enabled for three roles: a capable generation model for the reasoning layer (Claude Sonnet or equivalent), a cheaper fast model for scenario classification and modality inventory summarization (Claude Haiku or Nova Lite), and an embedding model for guideline retrieval (Titan Text Embeddings v2 or Cohere Embed English v3). Scope `bedrock:InvokeModel` to specific model ARNs in production.

A few things worth knowing upfront:

- **This is a reasoning pipeline, not an imaging-AI pipeline.** The code below consumes radiology report text and (optionally) structured outputs from cleared imaging AI vendors. It does NOT perform direct pixel-level interpretation of DICOM studies. Direct pixel interpretation by a general-purpose model is a regulatory posture you should not take lightly; the production pattern is to consume cleared-vendor outputs or human radiologist reports as pre-existing inputs.
- **Cleared imaging AI vendor integration is stubbed.** Real integrations use vendor-specific APIs (Aidoc, Viz.ai, RapidAI, others) with webhook-style result delivery tied to study instance UIDs. The stub below returns synthetic vendor output for illustration. Vendor contracts include workflow, retention, and liability terms that matter.
- **ECG foundation model integration is stubbed.** The `_invoke_ecg_foundation_model` function simulates a call to a SageMaker endpoint. Real ECG foundation models run on research or institutional endpoints and require waveform access (ECG management systems with WFDB, XML, or MUSE export), which is a separate integration problem.
- **HealthImaging integration is partial.** The DICOM metadata retrieval stub returns a fixed structure. Real integrations use the HealthImaging APIs with proper auth, study-index queries, and deep-link construction into the PACS viewer.
- **Comprehend Medical's byte limit** applies here just as in Recipe 2.9. The helper truncates by utf-8 byte count.
- **All clinical content in examples is SYNTHETIC.** Do not treat any specific finding, value, source, or recommendation as real.

---

## Configuration and Constants

Configuration first. Model IDs, modality retrieval windows, scope-gate rules, validation thresholds, and resource names are the knobs you'll change between environments.

```python
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

# Structured logging; ship JSON to CloudWatch Logs Insights for queryable analysis.
# Never log raw patient context, modality contents, or rendered reasoning in plain
# text. The audit trail for clinical content lives in S3 and DynamoDB under KMS,
# with CloudTrail data events enabled.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles Bedrock throttling. Multi-modal reasoning bursts around
# admission spikes and shift change; adaptive mode uses exponential backoff with
# jitter so retries don't pile on.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
comprehend_medical = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
cloudwatch = boto3.client("cloudwatch", config=BOTO3_RETRY_CONFIG)
# HealthLake, HealthImaging, SageMaker-runtime, and Secrets Manager clients are
# created in the functions that use them so the example runs without them
# configured.

# --- Model Configuration ---
# TODO: verify the exact model IDs available in your region and account. If your
# region requires cross-region inference, use the inference profile ID
# (e.g., "us.anthropic.claude-3-5-sonnet-20241022-v2:0").
SMALL_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"
REASONING_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"

# Bedrock Guardrail for the reasoning generation step. Configure one in the
# Bedrock console with the contextual grounding check enabled at a strict
# threshold (0.85+). For multi-modal clinical reasoning, grounding enforcement
# is non-negotiable. Leaving these None disables the Guardrail; do NOT ship
# without one.
GUARDRAIL_ID = None        # e.g., "abc123xyz"
GUARDRAIL_VERSION = None   # e.g., "DRAFT" or a numbered version

# --- OpenSearch Configuration ---
# Indexes: guidelines (society + public), institutional-protocols (local),
# case-analogs (optional curated corpus of similar cases with outcomes).
OPENSEARCH_ENDPOINT = "your-mm-reasoning-opensearch-domain.us-east-1.es.amazonaws.com"
OPENSEARCH_GUIDELINES_INDEX = "mm-guidelines"
OPENSEARCH_PROTOCOLS_INDEX = "mm-protocols"
OPENSEARCH_CASE_ANALOGS_INDEX = "mm-case-analogs"
OPENSEARCH_REGION = "us-east-1"

# --- HealthLake and HealthImaging ---
HEALTHLAKE_DATASTORE_ID = "your-healthlake-datastore-id"
HEALTHIMAGING_DATASTORE_ID = "your-healthimaging-datastore-id"

# --- Aurora (structured drug data, reused from Recipe 2.9) ---
AURORA_CLUSTER_ARN = "arn:aws:rds:us-east-1:123456789012:cluster:cds-drugdb"
AURORA_DATABASE = "cds_drugdb"
AURORA_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:cds-drugdb-creds"

# --- SageMaker Endpoints (optional self-hosted modality models) ---
ECG_FOUNDATION_MODEL_ENDPOINT = None  # e.g., "ecg-foundation-model-prod"
IMAGING_MODEL_ENDPOINT = None         # if using self-hosted imaging AI

# --- Storage Configuration ---
REASONING_ARCHIVE_BUCKET = "your-mm-reasoning-archive-bucket"
REASONING_ARCHIVE_CMK_ARN = "arn:aws:kms:us-east-1:123456789012:key/abcd1234-mm"

# DynamoDB tables
REASONING_RUNS_TABLE = "mm-reasoning-runs"       # (run_id)
PATIENT_RUNS_TABLE = "mm-patient-reasoning-runs" # (patient_id, run_id)

# --- Pipeline Tuning ---
GUIDELINE_RETRIEVAL_SIZE = 20
PROTOCOL_RETRIEVAL_SIZE = 10
CASE_ANALOG_RETRIEVAL_SIZE = 5

TOP_GUIDELINES_TO_PROMPT = 10
TOP_PROTOCOLS_TO_PROMPT = 8
TOP_CASE_ANALOGS_TO_PROMPT = 3

MAX_GENERATION_ATTEMPTS = 3
COMPREHEND_MEDICAL_MAX_BYTES = 19500

# Recency windows per modality (hours). Anything older is labeled "stale" in the
# inventory; the reasoning layer must consider staleness explicitly.
RECENCY_WINDOWS_HOURS = {
    "imaging_cxr":       48,    # chest radiograph for current encounter context
    "imaging_ct":        168,   # 7 days for CT
    "imaging_echo":      720,   # 30 days for echo; beyond, flag as stale
    "ecg":               48,
    "labs":              48,
    "vitals":            24,
    "notes_progress":    72,
    "notes_consult":     720,
}

# Suppression: if a reasoning run was produced for this patient+encounter+scenario
# within this window and no material change occurred, suppress.
SUPPRESSION_WINDOW_MINUTES = 120

# --- Scope rules per scenario ---
# Required modalities for each scenario scope. If any required modality is
# missing, the scope gate either scopes down to a narrower scenario or defers
# with an explanatory output.
SCENARIO_MODALITY_REQUIREMENTS = {
    "ed_dyspnea_workup": {
        "required":    ["structured_context", "labs", "vitals", "imaging_chest"],
        "recommended": ["ecg", "notes_recent", "imaging_prior"],
    },
    "hf_management": {
        "required":    ["structured_context", "labs", "imaging_echo"],
        "recommended": ["ecg", "notes_cardiology"],
    },
    "oncology_treatment_planning": {
        "required":    ["structured_context", "imaging_staging", "pathology"],
        "recommended": ["imaging_prior", "notes_oncology", "genomics"],
    },
    "comprehensive_reasoning": {
        "required":    ["structured_context", "labs"],
        "recommended": ["imaging", "ecg", "notes", "vitals"],
    },
}

# --- Validation Configuration ---
# Graded terms from radiology and pathology reports that must be preserved
# verbatim if they appear in the reasoning output. Upgrading "mild" to
# "moderate" is a specific, common, and dangerous hallucination.
GRADED_TERMS = [
    "mild", "mildly", "moderate", "moderately", "severe", "severely",
    "marked", "markedly", "minimal", "trace", "borderline", "preserved",
    "reduced", "depressed", "hyperdynamic",
]

# Directive language that should not appear in the reasoning output in the
# model's own voice. Verbatim-quoted guideline text may contain directives;
# the validator strips quoted passages before scanning.
DIRECTIVE_PHRASES = [
    "you should", "you must", "administer", "give", "prescribe",
    "start immediately", "stop immediately", "switch to",
]
```

---

## Shared Helpers

A few utilities reused across steps. Keeping them in one place so each step stays focused on the pattern it teaches.

```python
def _now_iso() -> str:
    """UTC ISO timestamp for audit fields."""
    return datetime.datetime.now(timezone.utc).isoformat()


def _get_opensearch_client() -> OpenSearch:
    """Build an IAM-authenticated OpenSearch client."""
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

    CRITICAL: must match whatever embedder indexed the guideline corpus.
    Mixing embedders between indexing and query time produces silently
    bad retrieval. Pin the model ID in config and verify it matches.
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
    """Parse JSON from a model response, stripping common markdown wrappers."""
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
    """Truncate to at most max_bytes when encoded as utf-8."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _to_decimal_safe(value):
    """
    Convert floats to Decimal for DynamoDB. Going through str avoids
    binary-precision artifacts that Decimal(float) introduces. DynamoDB
    raises TypeError on Python floats; this helper is the muscle memory
    that prevents that.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_decimal_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_decimal_safe(v) for v in value]
    return value


def _hours_since(iso_timestamp: str | None) -> float | None:
    """Return hours since an ISO timestamp. None if invalid."""
    if not iso_timestamp:
        return None
    try:
        then = datetime.datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        now = datetime.datetime.now(timezone.utc)
        return (now - then).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None
```

---

## Step 1: Start the Reasoning Run

*The pseudocode calls this `start_reasoning_run(trigger)`. A clinical event (ED presentation, admission, imaging finalized, lab crossing a threshold) arrives through EventBridge, or a clinician explicitly requests a reasoning run. The first step creates the run record with audit metadata so every later failure is traceable.*

```python
def start_reasoning_run(trigger: dict) -> dict:
    """
    Initialize a reasoning run and persist the record.

    Args:
        trigger: Dict with:
            - trigger_type:   "ed_presentation" | "admission" | "imaging_finalized"
                              | "lab_threshold" | "clinician_request"
            - patient_id:     FHIR Patient.id
            - encounter_id:   FHIR Encounter.id (when applicable)
            - scenario:       scenario name; see SCENARIO_MODALITY_REQUIREMENTS
            - clinician_id:   Cognito identity for audit trail
            - payload:        trigger-specific details

    Returns:
        Dict with run_id and initial status.
    """
    run_id = str(uuid.uuid4())
    now_iso = _now_iso()

    # Persist early. If any later step fails, we have a record of what was
    # triggered and for whom. The run record carries PHI (patient_id), so
    # the table uses KMS CMK encryption.
    runs_table = dynamodb.Table(REASONING_RUNS_TABLE)
    runs_table.put_item(Item=_to_decimal_safe({
        "run_id":        run_id,
        "trigger_type":  trigger.get("trigger_type"),
        "patient_id":    trigger.get("patient_id"),
        "encounter_id":  trigger.get("encounter_id", ""),
        "scenario":      trigger.get("scenario", "comprehensive_reasoning"),
        "clinician_id":  trigger.get("clinician_id"),
        "status":        "INITIATED",
        "initiated_at":  now_iso,
        "trigger_payload": trigger.get("payload", {}),
    }))

    logger.info("Started reasoning run %s for patient %s scenario %s",
                run_id, trigger.get("patient_id"), trigger.get("scenario"))
    return {"run_id": run_id, "status": "INITIATED", "initiated_at": now_iso}
```

---

## Step 2a: Ingest Imaging

*The pseudocode calls this `ingest_imaging(run_id, patient_id, scenario)`. Pull relevant imaging studies for the scenario (current encounter + most recent priors of the same anatomy). For each, retrieve the DICOM metadata from HealthImaging, the radiology report from HealthLake (or the report system) as a DocumentReference, entity-extract the report, and optionally attach cleared imaging AI vendor output. The reasoning layer never looks at pixels; it reads the report text and structured AI outputs.*

```python
def ingest_imaging(run_id: str, patient_id: str, scenario: str) -> list:
    """
    Collect relevant imaging studies and their structured interpretations.

    Returns a list of imaging records. Each record has the report text
    (radiologist's interpretation, already a structured input), any
    cleared imaging AI outputs (structured findings with probabilities),
    a deep link back to the PACS viewer for clinician review, and a
    stable source_id for citation in the reasoning output.
    """
    imaging_studies = _list_relevant_imaging_for_scenario(patient_id, scenario)
    imaging_records = []

    for study in imaging_studies:
        # Pull DICOM metadata. Real HealthImaging calls use the
        # MedicalImaging client; the stub below returns a fixed structure
        # so the example runs without a live datastore.
        metadata = _get_healthimaging_metadata(study["image_set_id"])

        # Pull the radiology report as a FHIR DocumentReference. The
        # category filter is typical but EHR-specific; some systems use a
        # different code system for report types.
        report = _fetch_radiology_report_from_healthlake(
            patient_id, metadata.get("study_instance_uid"),
        )

        # Entity-extract the report. Mapping to RadLex is ideal for
        # radiology entities; Comprehend Medical covers general clinical
        # entities. Use RadLex integration where your corpus supports it.
        report_text = report.get("content", "")
        if report_text:
            try:
                entities_resp = comprehend_medical.detect_entities_v2(
                    Text=_safe_utf8_truncate(report_text,
                                             COMPREHEND_MEDICAL_MAX_BYTES),
                )
                report_entities = entities_resp.get("Entities", [])
            except ClientError as exc:
                logger.warning("Comprehend Medical failed for imaging %s: %s",
                               metadata.get("study_instance_uid"), exc)
                report_entities = []
        else:
            report_entities = []

        # Cleared imaging AI vendor output, when applicable. The stub
        # produces a synthetic result for illustration. Real integrations
        # use vendor APIs with study-instance-UID lookup; results are
        # typically pushed via webhook and stored in the same report
        # system or a sidecar.
        cleared_ai_outputs = []
        if _scenario_requires_cleared_ai(scenario, metadata.get("modality")):
            vendor_output = _get_cleared_imaging_ai_output(
                study_uid=metadata.get("study_instance_uid"),
                modality=metadata.get("modality"),
            )
            if vendor_output:
                cleared_ai_outputs.append(vendor_output)

        source_id = f"imaging:{metadata.get('study_instance_uid')}"
        imaging_records.append({
            "source_id":          source_id,
            "modality_type":      "imaging",
            "study_modality":     metadata.get("modality"),
            "study_description":  metadata.get("study_description"),
            "study_date":         metadata.get("study_date"),
            "study_uid":          metadata.get("study_instance_uid"),
            "report_text":        report_text,
            "report_entities":    report_entities,
            "cleared_ai_outputs": cleared_ai_outputs,
            "pacs_deep_link":     _build_pacs_deep_link(metadata),
            "age_hours":          _hours_since(metadata.get("study_date")),
        })

    logger.info("Ingested %d imaging studies for run %s",
                len(imaging_records), run_id)
    return imaging_records


def _list_relevant_imaging_for_scenario(patient_id: str,
                                         scenario: str) -> list:
    """
    Pick imaging studies relevant to the scenario. The production version
    queries HealthImaging's search endpoint with patient and date filters
    plus modality filters per scenario.

    TODO (TechCodeReviewer): wire this to HealthImaging search. The stub
    returns synthetic studies so the example runs end-to-end.
    """
    # Synthetic studies for illustration.
    return [
        {"image_set_id": "synthetic-imageset-cxr-current"},
        {"image_set_id": "synthetic-imageset-echo-2024"},
    ]


def _get_healthimaging_metadata(image_set_id: str) -> dict:
    """
    Retrieve DICOM metadata from HealthImaging for an image set.

    TODO: replace with real `medical-imaging:GetImageSetMetadata` call.
    The real response is gzipped JSON containing the full DICOM header
    set for the image set.
    """
    # Illustrative synthetic metadata; REPLACE with real HealthImaging call.
    if "cxr" in image_set_id:
        return {
            "study_instance_uid":  "1.2.840.113619.2.1.1.322.1591042649.SYNTH.CXR",
            "modality":            "CR",
            "study_description":   "Chest 2 views",
            "study_date":          _now_iso(),
        }
    if "echo" in image_set_id:
        return {
            "study_instance_uid":  "1.2.840.113619.2.1.1.322.1591042649.SYNTH.ECHO",
            "modality":            "US",
            "study_description":   "Transthoracic echocardiogram, complete",
            "study_date":          "2024-04-11T10:15:00+00:00",
        }
    return {"study_instance_uid": image_set_id, "modality": "unknown",
            "study_description": "", "study_date": _now_iso()}


def _fetch_radiology_report_from_healthlake(patient_id: str,
                                              study_uid: str | None) -> dict:
    """
    Pull the radiology report for a study as a FHIR DocumentReference.

    TODO: replace with real HealthLake SigV4 HTTPS search. The stub
    returns a synthetic report so downstream code has something to
    reason over.
    """
    if not study_uid:
        return {"content": "", "id": None}
    # Synthetic report text for illustration.
    if "CXR" in study_uid:
        text = (
            "CHEST PA AND LATERAL. INDICATION: dyspnea. "
            "FINDINGS: Bibasilar opacities, not specific. Differential includes "
            "pulmonary edema, atypical infection, or pulmonary embolism with "
            "infarction. No pneumothorax. Cardiac silhouette is mildly enlarged. "
            "IMPRESSION: Bibasilar opacities; clinical correlation recommended. "
            "Consider CT pulmonary angiography if suspicion for PE."
        )
    elif "ECHO" in study_uid:
        text = (
            "TRANSTHORACIC ECHOCARDIOGRAM, 2024-04-11. "
            "LV systolic function is mildly to moderately reduced; estimated "
            "ejection fraction 40-45%. Mild mitral regurgitation. No pericardial "
            "effusion. Right ventricular function is preserved. Recommendations: "
            "clinical correlation; consider cardiology follow-up."
        )
    else:
        text = ""
    return {"content": text, "id": f"docref-synth-{study_uid}"}


def _scenario_requires_cleared_ai(scenario: str, modality: str | None) -> bool:
    """Whether to query a cleared imaging AI vendor for this combination."""
    if scenario == "ed_dyspnea_workup" and modality in ("CR", "CT"):
        return True
    if scenario == "oncology_treatment_planning" and modality in ("CT", "MR"):
        return True
    return False


def _get_cleared_imaging_ai_output(study_uid: str | None,
                                    modality: str | None) -> dict | None:
    """
    Query the cleared imaging AI vendor for structured output.

    TODO: replace with real vendor API call. Vendor contracts define
    the API shape, auth, latency SLA, and retention.
    """
    # Synthetic vendor output for illustration. Real outputs include
    # finding probability, localization (bounding boxes or segmentations),
    # vendor name, model version, and clearance reference.
    return None  # default: no AI output for the synthetic studies


def _build_pacs_deep_link(metadata: dict) -> str:
    """Construct a deep link into the PACS viewer for this study."""
    # Placeholder. Real links use the hospital PACS URL scheme.
    return f"pacs://studies/{metadata.get('study_instance_uid', '')}"
```

---

## Step 2b: Ingest ECG, Labs+Vitals, Notes, Structured Context

*Each remaining modality has its own ingestion function. The outputs all share a common shape: timestamped records with a stable source_id, the interpretation content, and modality-specific structured fields. In production these run in parallel as Step Functions Map branches; the sequential Python below is fine for understanding the pattern.*

```python
def ingest_ecg(run_id: str, patient_id: str, scenario: str,
               encounter_id: str) -> list:
    """
    Collect recent ECG interpretations. ECGs in FHIR are typically
    Observation resources with LOINC 11524-6 (12-lead ECG report) or
    DocumentReferences. Production systems also pull the waveform from
    an ECG management system for foundation-model interpretation.
    """
    # TODO: replace with real HealthLake FHIR search. Stub returns a
    # synthetic ECG for illustration.
    synthetic_ecgs = _synthetic_ecg_records(patient_id, scenario)
    ecg_records = []

    for ecg in synthetic_ecgs:
        # Optional: call an ECG foundation model for additional
        # interpretation. Requires waveform access.
        foundation_output = None
        if ECG_FOUNDATION_MODEL_ENDPOINT and \
                _scenario_requires_ecg_foundation_model(scenario):
            foundation_output = _invoke_ecg_foundation_model(
                ecg.get("waveform_reference"),
            )

        ecg_records.append({
            "source_id":               f"ecg:{ecg['id']}",
            "modality_type":           "ecg",
            "ecg_date":                ecg.get("effective_date_time"),
            "machine_interpretation":  ecg.get("machine_interpretation"),
            "clinician_overread":      ecg.get("overread"),
            "heart_rate":              ecg.get("hr"),
            "qtc":                     ecg.get("qtc"),
            "qrs":                     ecg.get("qrs"),
            "axis":                    ecg.get("axis"),
            "foundation_model_output": foundation_output,
            "age_hours":               _hours_since(ecg.get("effective_date_time")),
            "deep_link":               f"ecgs://{ecg['id']}",
        })

    logger.info("Ingested %d ECG records for run %s", len(ecg_records), run_id)
    return ecg_records


def _synthetic_ecg_records(patient_id: str, scenario: str) -> list:
    """
    Synthetic ECGs for illustration. Replace with HealthLake Observation
    search for LOINC 11524-6 (12-lead ECG report).

    For the default ED dyspnea vignette we return no ECGs so the pipeline
    exercises the missing-modality acknowledgment path in the reasoning
    prompt and validator. Production replaces this stub across all
    scenarios.
    """
    return []


def _scenario_requires_ecg_foundation_model(scenario: str) -> bool:
    return scenario in ("hf_management", "ed_dyspnea_workup")


def _invoke_ecg_foundation_model(waveform_reference: str | None) -> dict | None:
    """
    Call a SageMaker endpoint that returns an ECG foundation model
    interpretation. TODO: replace with real endpoint invocation.
    """
    if not waveform_reference or not ECG_FOUNDATION_MODEL_ENDPOINT:
        return None
    return None


def ingest_labs_and_vitals(run_id: str, patient_id: str,
                            scenario: str) -> dict:
    """
    Pull scenario-relevant labs with trend summaries and recent vitals.

    Trends matter more than point values for most clinical questions.
    A rising troponin and a stable mildly-elevated troponin are clinically
    different; the reasoning layer needs to see the classification.
    """
    scenario_loincs = _lab_loincs_for_scenario(scenario)
    labs_by_loinc = {}

    for loinc, display in scenario_loincs.items():
        # TODO: real HealthLake Observation search per LOINC over a 24-month
        # window, sorted ascending by effectiveDateTime. Stub returns synthetic.
        observations = _synthetic_observations_for_loinc(loinc, display)
        if observations:
            labs_by_loinc[loinc] = observations

    lab_trends = {}
    for loinc, obs_list in labs_by_loinc.items():
        obs_list = sorted(obs_list, key=lambda o: o.get("effective_date_time", ""))
        if len(obs_list) >= 2:
            current = obs_list[-1]
            prior = obs_list[-2]
            delta_percent = _percent_change(prior.get("value"), current.get("value"))
            lab_trends[loinc] = {
                "source_id":        f"lab:{loinc}",
                "display_name":     obs_list[-1].get("display"),
                "current_value":    current.get("value"),
                "current_unit":     current.get("unit"),
                "current_date":     current.get("effective_date_time"),
                "prior_value":      prior.get("value"),
                "prior_date":       prior.get("effective_date_time"),
                "delta_percent":    delta_percent,
                "classification":   _classify_trend(obs_list),
                "age_hours":        _hours_since(current.get("effective_date_time")),
            }
        elif len(obs_list) == 1:
            lab_trends[loinc] = {
                "source_id":      f"lab:{loinc}",
                "display_name":   obs_list[0].get("display"),
                "current_value":  obs_list[0].get("value"),
                "current_unit":   obs_list[0].get("unit"),
                "current_date":   obs_list[0].get("effective_date_time"),
                "classification": "single_value",
                "age_hours":      _hours_since(obs_list[0].get("effective_date_time")),
            }

    # Vitals summary over the current encounter window.
    vitals_summary = _synthetic_vitals_summary(patient_id, scenario)

    logger.info("Ingested %d lab trends and vitals summary for run %s",
                len(lab_trends), run_id)
    return {
        "source_id":      "labs_vitals",
        "lab_trends":     lab_trends,
        "vitals_summary": vitals_summary,
    }


def _lab_loincs_for_scenario(scenario: str) -> dict:
    """LOINCs relevant to the scenario. Expand per clinical domain."""
    common = {
        "2160-0":  "Creatinine",
        "2951-2":  "Sodium",
        "2823-3":  "Potassium",
        "718-7":   "Hemoglobin",
    }
    if scenario == "ed_dyspnea_workup":
        return {
            **common,
            "10834-0": "Troponin I",
            "42637-9": "BNP",
            "33762-6": "D-dimer",
            "6690-2":  "WBC",
        }
    if scenario == "hf_management":
        return {**common, "42637-9": "BNP", "4548-4": "HbA1c"}
    return common


def _synthetic_observations_for_loinc(loinc: str, display: str) -> list:
    """Synthetic lab observations for illustration."""
    now_iso = _now_iso()
    # Synthetic time-series; the reasoning layer sees current vs prior.
    if loinc == "2160-0":  # Creatinine
        return [
            {"loinc": loinc, "display": display, "value": 1.3,
             "unit": "mg/dL", "effective_date_time": "2025-12-10T08:00:00+00:00"},
            {"loinc": loinc, "display": display, "value": 1.6,
             "unit": "mg/dL", "effective_date_time": now_iso},
        ]
    if loinc == "10834-0":  # Troponin
        return [
            {"loinc": loinc, "display": display, "value": 0.08,
             "unit": "ng/mL", "effective_date_time": now_iso},
        ]
    if loinc == "42637-9":  # BNP
        return [
            {"loinc": loinc, "display": display, "value": 840,
             "unit": "pg/mL", "effective_date_time": now_iso},
        ]
    if loinc == "33762-6":  # D-dimer
        return [
            {"loinc": loinc, "display": display, "value": 1200,
             "unit": "ng/mL FEU", "effective_date_time": now_iso},
        ]
    return []


def _percent_change(old, new):
    if old is None or new is None:
        return None
    try:
        if float(old) == 0:
            return None
        return round(((float(new) - float(old)) / float(old)) * 100.0, 1)
    except (TypeError, ValueError):
        return None


def _classify_trend(obs_list: list) -> str:
    """Coarse trend classification. Production uses smoothed slope analysis."""
    if len(obs_list) < 2:
        return "single_value"
    values = [o.get("value") for o in obs_list if o.get("value") is not None]
    if len(values) < 2:
        return "insufficient_data"
    first, last = float(values[0]), float(values[-1])
    if first == 0:
        return "stable"
    change = (last - first) / first
    if change > 0.2:
        return "rising"
    if change < -0.2:
        return "falling"
    return "stable"


def _synthetic_vitals_summary(patient_id: str, scenario: str) -> dict:
    """Synthetic vitals summary for illustration."""
    return {
        "hr":   {"most_recent": 108, "min": 102, "max": 112, "unit": "bpm"},
        "sbp":  {"most_recent": 112, "unit": "mmHg"},
        "dbp":  {"most_recent": 68,  "unit": "mmHg"},
        "rr":   {"most_recent": 22,  "unit": "breaths/min"},
        "spo2": {"most_recent": 93,  "unit": "%", "room_air": True},
        "temp": {"most_recent": 98.4, "unit": "F"},
        "age_hours": 1.0,
    }


def ingest_notes(run_id: str, patient_id: str, scenario: str) -> list:
    """
    Pull scenario-relevant clinical notes. Each note becomes a citable
    source in the reasoning output.
    """
    # TODO: real HealthLake DocumentReference search scoped by note category
    # and date window. Stub returns synthetic notes.
    notes_raw = _synthetic_notes(patient_id, scenario)
    notes = []

    for note in notes_raw:
        content = note.get("content", "")
        if content:
            try:
                entities_resp = comprehend_medical.detect_entities_v2(
                    Text=_safe_utf8_truncate(content,
                                             COMPREHEND_MEDICAL_MAX_BYTES),
                )
                entities = entities_resp.get("Entities", [])
            except ClientError as exc:
                logger.warning("Comprehend Medical failed for note %s: %s",
                               note.get("id"), exc)
                entities = []
        else:
            entities = []

        # Extract key passages. Production systems look for specific section
        # headings (Assessment, Plan, Impression) or use a sentence scorer.
        # The stub uses a simple first-400-chars-of-content approach.
        key_passages = [content[:400]] if content else []

        notes.append({
            "source_id":     f"note:{note['id']}",
            "modality_type": "note",
            "note_type":     note.get("category"),
            "specialty":     note.get("specialty"),
            "note_date":     note.get("date"),
            "content":       content,
            "entities":      entities,
            "key_passages":  key_passages,
            "age_hours":     _hours_since(note.get("date")),
        })

    logger.info("Ingested %d notes for run %s", len(notes), run_id)
    return notes


def _synthetic_notes(patient_id: str, scenario: str) -> list:
    """Synthetic notes for illustration."""
    if scenario == "ed_dyspnea_workup":
        return [
            {
                "id": "note-oncology-2020",
                "category": "consult",
                "specialty": "Oncology",
                "date": "2020-03-15T14:20:00+00:00",
                "content": (
                    "ONCOLOGY CONSULTATION NOTE. Patient with ER-positive "
                    "breast cancer. Treatment plan: four cycles of AC "
                    "(doxorubicin and cyclophosphamide), then paclitaxel, then "
                    "radiation. Cardiology baseline echo obtained prior to "
                    "anthracycline initiation. Patient counseled on late "
                    "anthracycline cardiotoxicity risk and need for "
                    "surveillance."
                ),
            },
            {
                "id": "note-pcp-2026-04",
                "category": "progress",
                "specialty": "Primary Care",
                "date": "2026-04-14T09:00:00+00:00",
                "content": (
                    "PRIMARY CARE FOLLOW-UP. Patient reports new exertional "
                    "dyspnea over the last month; she has not escalated to us. "
                    "Weight stable. Vital signs within normal range today. "
                    "Plan: outpatient echocardiogram, BNP, electrolyte panel; "
                    "follow up in 2 weeks."
                ),
            },
        ]
    return []


def ingest_structured_context(run_id: str, patient_id: str) -> dict:
    """
    Pull the core FHIR resources for structured patient facts.

    Reuses the normalization pattern from Recipe 2.9. The structured
    context carries demographics, active conditions, current medications,
    allergies, and derived values (eGFR, BMI).
    """
    # TODO: real HealthLake search over Patient, Condition,
    # MedicationRequest, AllergyIntolerance, Observation, Procedure.
    # The stub returns a synthetic bundle equivalent to the ED vignette
    # from the main recipe.
    bundle = _synthetic_ed_vignette_bundle(patient_id)
    structured = _normalize_patient_context(bundle)
    logger.info("Ingested structured context for run %s (%d conditions, "
                "%d meds, %d allergies)", run_id,
                len(structured.get("active_conditions", [])),
                len(structured.get("current_medications", [])),
                len(structured.get("allergies", [])))
    return structured


def _synthetic_ed_vignette_bundle(patient_id: str) -> dict:
    """Synthetic FHIR bundle for the ED vignette in Recipe 2.10."""
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {
                "resourceType": "Patient", "id": patient_id,
                "gender": "female", "birthDate": "1964-02-11",
            }},
            {"resource": {
                "resourceType": "Condition",
                "clinicalStatus": {"coding": [{"code": "active"}]},
                "code": {"text": "History of breast cancer, 2020, anthracycline-treated"},
            }},
            {"resource": {
                "resourceType": "Condition",
                "clinicalStatus": {"coding": [{"code": "active"}]},
                "code": {"text": "Chronic kidney disease, stage 3B"},
            }},
            {"resource": {
                "resourceType": "Condition",
                "clinicalStatus": {"coding": [{"code": "active"}]},
                "code": {"text": "Type 2 diabetes mellitus"},
            }},
            {"resource": {
                "resourceType": "Condition",
                "clinicalStatus": {"coding": [{"code": "active"}]},
                "code": {"text": "Rheumatoid arthritis"},
            }},
            {"resource": {
                "resourceType": "MedicationRequest",
                "status": "active",
                "medicationCodeableConcept": {"text": "methotrexate 15 mg weekly"},
                "dosageInstruction": [{"text": "15 mg PO weekly"}],
            }},
        ],
    }


def _normalize_patient_context(bundle: dict) -> dict:
    """Minimal FHIR-bundle-to-structured-context normalization."""
    entries = bundle.get("entry", []) or []
    by_type = defaultdict(list)
    for e in entries:
        res = e.get("resource", {})
        rtype = res.get("resourceType")
        if rtype:
            by_type[rtype].append(res)

    patient = (by_type.get("Patient") or [{}])[0]
    birth_date = patient.get("birthDate")
    age = None
    if birth_date:
        try:
            bd = datetime.date.fromisoformat(birth_date)
            today = datetime.date.today()
            age = today.year - bd.year - (
                (today.month, today.day) < (bd.month, bd.day)
            )
        except ValueError:
            pass

    active_conditions = []
    for cond in by_type.get("Condition", []) or []:
        status = cond.get("clinicalStatus", {}).get("coding", [])
        if any(c.get("code") == "active" for c in status):
            active_conditions.append({
                "display": (cond.get("code") or {}).get("text"),
            })

    current_medications = []
    for med in by_type.get("MedicationRequest", []) or []:
        if med.get("status") == "active":
            current_medications.append({
                "display":   (med.get("medicationCodeableConcept") or {}).get("text"),
                "dose_text": ((med.get("dosageInstruction") or [{}])[0]).get("text"),
            })

    return {
        "demographics": {
            "age": age,
            "sex_assigned": patient.get("gender"),
        },
        "active_conditions":   active_conditions,
        "current_medications": current_medications,
        "allergies":           [],  # populate from AllergyIntolerance resources
        "derived": {
            # See Recipe 2.9 for full eGFR / BMI / Child-Pugh computation.
            "egfr_ckd_epi_2021": 44,  # placeholder matching the vignette
        },
    }
```

---

## Step 3: Normalize and Build the Modality Inventory

*The pseudocode calls this `normalize_and_inventory(...)`. Each modality produced its own record format. This step assembles them into a unified patient state and builds the modality inventory, which enumerates what is present, what is absent, and the recency of each item. The inventory is a first-class input to the reasoning prompt: the model must consult it to acknowledge missing modalities explicitly.*

```python
def normalize_and_inventory(imaging: list, ecg: list, labs_vitals: dict,
                             notes: list, structured: dict) -> dict:
    """
    Unify modality outputs and build the inventory for downstream reasoning.
    """
    patient_state = {
        "structured_context": structured,
        "imaging_records":    imaging,
        "ecg_records":        ecg,
        "lab_trends":         labs_vitals.get("lab_trends", {}),
        "vitals_summary":     labs_vitals.get("vitals_summary", {}),
        "notes":              notes,
    }

    # Modality inventory: what is present, what is absent, recency.
    inventory = {
        "structured_context": {
            "present":    bool(structured.get("active_conditions")
                               or structured.get("current_medications")),
            "recency":    "current",
        },
        "imaging": {
            "present":     len(imaging) > 0,
            "count":       len(imaging),
            "modalities":  sorted(list({i.get("study_modality")
                                        for i in imaging if i.get("study_modality")})),
            "most_recent_hours_old": _min_age_hours(imaging),
            "cleared_ai_present": any(i.get("cleared_ai_outputs") for i in imaging),
        },
        "ecg": {
            "present":     len(ecg) > 0,
            "count":       len(ecg),
            "most_recent_hours_old": _min_age_hours(ecg),
        },
        "labs": {
            "present":                 len(labs_vitals.get("lab_trends", {})) > 0,
            "lab_count":               len(labs_vitals.get("lab_trends", {})),
            "with_trend":              sum(1 for t in labs_vitals.get("lab_trends", {}).values()
                                            if t.get("classification") in
                                               ("rising", "falling", "stable")),
            "single_values":           sum(1 for t in labs_vitals.get("lab_trends", {}).values()
                                            if t.get("classification") == "single_value"),
        },
        "vitals": {
            "present": bool(labs_vitals.get("vitals_summary")),
            "recency": "current_encounter",
        },
        "notes": {
            "present":     len(notes) > 0,
            "count":       len(notes),
            "types":       sorted(list({n.get("note_type") for n in notes
                                         if n.get("note_type")})),
            "most_recent_hours_old": _min_age_hours(notes),
        },
    }

    logger.info("Modality inventory: imaging=%s ecg=%s labs=%s notes=%s",
                inventory["imaging"]["present"], inventory["ecg"]["present"],
                inventory["labs"]["present"], inventory["notes"]["present"])
    return {"patient_state": patient_state, "modality_inventory": inventory}


def _min_age_hours(records: list) -> float | None:
    """Minimum age in hours among a list of records with age_hours fields."""
    ages = [r.get("age_hours") for r in records
            if r.get("age_hours") is not None]
    if not ages:
        return None
    return round(min(ages), 1)
```

---

## Step 4: Scope Gate

*The pseudocode calls this `scope_gate(...)`. Given the scenario and the modality inventory, decide whether the reasoning run should proceed. If a recent run covered the same scenario without material changes, suppress. If required modalities are missing, either scope down or defer with an explanatory output that tells the clinician what is missing and what to obtain.*

```python
def scope_gate(scenario: str, modality_inventory: dict, patient_id: str,
               recent_runs: list) -> dict:
    """
    Decide whether to proceed with reasoning, scope down, or defer.

    Returns:
        Dict with proceed (bool), scoped_to (scenario to reason on),
        reason, and defer_reason if applicable.
    """
    decision = {
        "proceed":       False,
        "scoped_to":     None,
        "reason":        "",
        "defer_reason":  None,
        "missing":       [],
    }

    # Suppression check
    now = datetime.datetime.now(timezone.utc)
    for recent in recent_runs:
        if recent.get("scenario") == scenario:
            delivered_at = recent.get("delivered_at")
            if delivered_at:
                try:
                    then = datetime.datetime.fromisoformat(delivered_at)
                    age_min = (now - then).total_seconds() / 60.0
                    if age_min < SUPPRESSION_WINDOW_MINUTES:
                        decision["reason"] = "recently_reasoned_same_scenario"
                        return decision
                except ValueError:
                    pass

    # Required-modality check
    requirements = SCENARIO_MODALITY_REQUIREMENTS.get(
        scenario, SCENARIO_MODALITY_REQUIREMENTS["comprehensive_reasoning"])
    required = requirements.get("required", [])
    recommended = requirements.get("recommended", [])

    missing_required = [
        r for r in required
        if not _modality_available(modality_inventory, r)
    ]
    if missing_required:
        decision["proceed"] = False
        decision["defer_reason"] = "missing_required_modalities"
        decision["missing"] = missing_required
        decision["reason"] = (
            f"Cannot proceed: required modalities absent "
            f"({', '.join(missing_required)})"
        )
        return decision

    # Recommended-modality check: proceed but may scope down
    missing_recommended = [
        r for r in recommended
        if not _modality_available(modality_inventory, r)
    ]

    if scenario == "comprehensive_reasoning" and missing_recommended:
        # Scope down when possible
        if _modality_available(modality_inventory, "imaging"):
            decision["scoped_to"] = "ed_dyspnea_workup" if \
                _modality_available(modality_inventory, "imaging_chest") else scenario
        else:
            decision["scoped_to"] = scenario
        decision["proceed"] = True
        decision["reason"] = "scoped_down_due_to_missing_recommended"
        decision["missing"] = missing_recommended
        return decision

    decision["proceed"] = True
    decision["scoped_to"] = scenario
    decision["reason"] = "all_required_modalities_present"
    decision["missing"] = missing_recommended  # informational
    return decision


def _modality_available(inventory: dict, requirement: str) -> bool:
    """Check whether a requirement token is satisfied by the inventory."""
    # Structured context and vitals are always first-class.
    if requirement == "structured_context":
        return inventory.get("structured_context", {}).get("present", False)
    if requirement == "labs":
        return inventory.get("labs", {}).get("present", False)
    if requirement == "vitals":
        return inventory.get("vitals", {}).get("present", False)
    if requirement == "ecg":
        return inventory.get("ecg", {}).get("present", False)
    if requirement == "notes" or requirement == "notes_recent":
        return inventory.get("notes", {}).get("present", False)
    if requirement == "imaging":
        return inventory.get("imaging", {}).get("present", False)
    if requirement.startswith("imaging_"):
        # For specific anatomy requirements, check modalities. A more
        # sophisticated version reads study descriptions too.
        return inventory.get("imaging", {}).get("present", False)
    return False
```

---

## Step 5: Deterministic Safety Checks (reused from Recipe 2.9)

*The pseudocode calls this `run_safety_checks(...)`. These are the same structured queries from Recipe 2.9 (drug interactions, allergies, renal dosing, contraindications, duplicate therapy), run against the Aurora drug database. The outputs become hard inputs to the reasoning prompt. In this example we show a stub that returns a concise finding set appropriate for the ED vignette; for the full implementation see Recipe 2.9's Step 4.*

```python
def run_safety_checks(structured_context: dict,
                       proposed_medications: list | None = None) -> dict:
    """
    Stub: reuses the pattern from Recipe 2.9 Step 4.

    In production, import the `run_deterministic_safety_checks` function
    from your Recipe 2.9 module and call it directly. The function
    expects the normalized patient context plus an optional list of
    proposed medications. Returns a dict with interactions,
    allergy_conflicts, renal_dose_flags, hepatic_dose_flags,
    contraindications, and duplicate_therapy lists.
    """
    # Synthetic safety findings for the ED vignette.
    return {
        "interactions":       [],
        "allergy_conflicts":  [],
        "renal_dose_flags":   [
            {
                "drug":              {"display": "iodinated contrast (if CTPA ordered)"},
                "current_egfr":      (structured_context.get("derived") or {})
                                     .get("egfr_ckd_epi_2021"),
                "recommended_dose":  "Reduced volume per institutional contrast protocol",
                "contraindicated":   False,
                "notes":             "Monitor creatinine post-contrast",
                "source":            "institutional_contrast_protocol_v3",
            }
        ],
        "hepatic_dose_flags": [],
        "contraindications":  [],
        "duplicate_therapy":  [],
    }
```

---

## Step 6: Retrieval

*The pseudocode calls this `retrieve_supporting_content(...)`. Pull relevant guidelines, institutional protocols, and optionally case analogs from OpenSearch with hybrid (vector + BM25) search scoped to the scenario. This is the same retrieval pattern from Recipes 2.7 and 2.9; the multi-modal specific twist is that retrieval queries are shaped by the modality inventory (e.g., if imaging shows pulmonary opacities, include retrieval for differential diagnoses of pulmonary opacities).*

```python
def retrieve_supporting_content(scenario: str, patient_state: dict,
                                  modality_inventory: dict) -> dict:
    """
    Hybrid retrieval against guidelines, protocols, and case analogs.

    Returns a dict with ranked lists per source type.
    """
    client = _get_opensearch_client()
    queries = _derive_retrieval_queries(scenario, patient_state,
                                         modality_inventory)

    guidelines = _hybrid_search(
        client, OPENSEARCH_GUIDELINES_INDEX,
        queries.get("guideline_queries", []),
        scenario, GUIDELINE_RETRIEVAL_SIZE,
    )[:TOP_GUIDELINES_TO_PROMPT]

    protocols = _hybrid_search(
        client, OPENSEARCH_PROTOCOLS_INDEX,
        queries.get("protocol_queries", []),
        scenario, PROTOCOL_RETRIEVAL_SIZE,
    )[:TOP_PROTOCOLS_TO_PROMPT]

    case_analogs = []
    if _case_analog_corpus_enabled(scenario):
        case_analogs = _hybrid_search(
            client, OPENSEARCH_CASE_ANALOGS_INDEX,
            queries.get("case_analog_queries", []),
            scenario, CASE_ANALOG_RETRIEVAL_SIZE,
        )[:TOP_CASE_ANALOGS_TO_PROMPT]

    logger.info("Retrieval: %d guidelines, %d protocols, %d case analogs",
                len(guidelines), len(protocols), len(case_analogs))
    return {
        "guidelines":   guidelines,
        "protocols":    protocols,
        "case_analogs": case_analogs,
    }


def _derive_retrieval_queries(scenario: str, patient_state: dict,
                                inventory: dict) -> dict:
    """Build scenario-aware retrieval queries."""
    if scenario == "ed_dyspnea_workup":
        return {
            "guideline_queries": [
                "evaluation of acute dyspnea in adult with prior anthracycline "
                "chemotherapy and renal dysfunction",
                "heart failure with preserved or reduced ejection fraction "
                "workup in the emergency department",
                "pulmonary embolism risk stratification Wells score elevated "
                "D-dimer",
                "community acquired pneumonia with immunosuppression",
            ],
            "protocol_queries": [
                "ED dyspnea workup protocol",
                "contrast nephropathy prevention with reduced eGFR",
            ],
            "case_analog_queries": [
                "anthracycline-treated breast cancer survivor with new "
                "dyspnea and elevated BNP",
            ],
        }
    # Only ED dyspnea queries are populated in this teaching example.
    # Replace with scenario-aware queries for each scenario you support
    # in production.
    return {"guideline_queries": [], "protocol_queries": [],
            "case_analog_queries": []}


def _hybrid_search(client, index: str, queries: list, scenario: str,
                    size: int) -> list:
    """
    Dense + BM25 hybrid search with reciprocal rank fusion. This is the
    same pattern from Recipe 2.7; it's reproduced in compact form here
    for completeness. For the full annotated version with metadata
    filters and population-specific ranking, see Recipe 2.9's Step 6.

    TODO: real integration. The stub returns an empty list so the example
    does not depend on a populated index.
    """
    if not queries:
        return []
    # Real production: run kNN per query_embedding, run BM25 on entity
    # text, fuse with RRF, return top-K. See Recipe 2.7/2.9 for the
    # complete implementation.
    return []


def _case_analog_corpus_enabled(scenario: str) -> bool:
    """Whether a curated case-analog corpus exists for this scenario."""
    return scenario in ("oncology_treatment_planning", "hf_management")
```

---

## Step 7: Reasoning Layer

*The pseudocode calls this `invoke_reasoning_layer(...)`. Build the prompt with the patient context, modality inventory, assembled sources, and safety findings. The prompt enforces multi-hypothesis reasoning, evidence-for-and-against per hypothesis, explicit handling of missing modalities, verbatim preservation of quantitative values and graded terms, cross-modality consistency, and citation discipline. Apply a Bedrock Guardrail with contextual grounding as the outer safety net.*

````python
def invoke_reasoning_layer(scenario: str, patient_state: dict,
                            modality_inventory: dict, retrieved: dict,
                            safety_findings: dict, scope_decision: dict,
                            regeneration_hint: str = "") -> dict:
    """
    Build the prompt with stable source IDs, invoke the reasoning model,
    and return parsed JSON plus an id_to_source map for validation.

    Returns:
        Dict with status (GENERATED | GROUNDING_REJECTED | PARSE_FAILED |
        GENERATION_FAILED), the parsed reasoning object, and
        id_to_source.
    """
    sources_block, id_to_source = _build_sources_block(
        patient_state, modality_inventory, retrieved, safety_findings,
    )
    inventory_block = _format_inventory_for_prompt(modality_inventory,
                                                    scope_decision)
    safety_block = _format_safety_for_prompt(safety_findings, id_to_source)

    scope_target = scope_decision.get("scoped_to", scenario)

    reasoning_system = f"""You are a clinical reasoning assistant for a practicing clinician.
The clinician is the decision-maker; your output synthesizes available evidence.
You do not diagnose. You do not prescribe. You present options with transparent reasoning.

SCOPE: {scope_target}. Do not reason outside this scope.

HARD REQUIREMENTS:
- Every factual claim must cite at least one source_id from the SOURCES block
  (e.g., [imaging:...] or [lab:...] or [guideline:...] or [note:...]). Do not
  invent citations. Do not use source IDs not in the SOURCES block.
- Preserve exact wording for quantitative values (numeric lab values, vitals,
  ECG intervals, ejection fraction percentages), graded terms (mild, moderate,
  severe, marked, minimal, trace, preserved, reduced), and drug names and doses.
  Do not paraphrase quantities. Do not upgrade or downgrade grades. Quote
  verbatim.
- Acknowledge missing modalities. The MODALITY INVENTORY block tells you what
  is absent. If a modality relevant to the scenario is absent, NAME the absence
  explicitly in the `modalities_absent_and_relevant` field. Do not reason as if
  an absent modality were present.
- Evaluate cross-modality consistency. If two modality sources disagree, list
  the disagreement in the `cross_modality_contradictions` field. Do not collapse
  into a false consensus.
- Evaluate recency. If a modality source is substantially older than the
  current encounter (check `age_hours` in the sources), note the staleness in
  `recency_notes` on the relevant items.
- Every SAFETY FINDING must appear in the output. None may be omitted.
- Frame recommendations as options, not directives. Use "Consider...",
  "Option A is...", "The guideline supports...". Do not use "administer",
  "give", "prescribe", "start immediately" in your own voice (verbatim quoted
  guideline text may contain directives; quote them with quotation marks).
- Separate `confidence_given_data` (how well the available evidence supports
  this hypothesis) from `completeness_of_data` (how complete the evidence is
  for this scenario). Do not conflate them.
- If the evidence is insufficient to answer a question, say so in
  `what_is_insufficient_to_answer`. Do not manufacture a conclusion.

OUTPUT: a JSON object matching this structure (do not wrap in markdown):
{{
  "scenario": "...",
  "overall_assessment": "2-4 sentence summary of the clinical situation",
  "modalities_used": ["list of source_ids used"],
  "modalities_absent_and_relevant": [
    {{"modality": "...", "relevance": "...", "recommendation": "..."}}
  ],
  "differential_or_recommendations": [
    {{
      "title": "...", "description": "...",
      "evidence_for":     [{{"text": "...", "source_citations": ["..."]}}],
      "evidence_against": [{{"text": "...", "source_citations": ["..."]}}],
      "cross_modality_notes": "...",
      "recency_notes": "...",
      "confidence_given_data": "low"|"moderate"|"high",
      "completeness_of_data": "low"|"moderate"|"high",
      "suggested_next_steps": ["..."],
      "tier": "critical"|"important"|"informational"
    }}
  ],
  "cross_modality_contradictions": [
    {{"description": "...", "source_a": "...", "source_b": "...",
      "implication": "..."}}
  ],
  "safety_findings_included": [
    {{"finding": "...", "source_citations": ["..."], "where_in_output": "..."}}
  ],
  "what_is_insufficient_to_answer": ["..."],
  "overall_uncertainty": "low"|"moderate"|"high",
  "uncertainty_rationale": "..."
}}"""

    reasoning_user = f"""PATIENT STRUCTURED CONTEXT:
{json.dumps(patient_state.get('structured_context', {}), default=str)[:3000]}

MODALITY INVENTORY AND SCOPE:
{inventory_block}

SAFETY FINDINGS (must all appear in output):
{safety_block}

AVAILABLE SOURCES:
{sources_block}

{('REGENERATION HINT: ' + regeneration_hint) if regeneration_hint else ''}

Produce the reasoning now. Output ONLY the JSON object."""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens":        6000,
        "temperature":       0.15,
        "system":            reasoning_system,
        "messages":          [{"role": "user", "content": reasoning_user}],
    })

    invoke_kwargs = {
        "modelId":     REASONING_MODEL_ID,
        "contentType": "application/json",
        "accept":      "application/json",
        "body":        body,
    }
    if GUARDRAIL_ID and GUARDRAIL_VERSION:
        invoke_kwargs["guardrailIdentifier"] = GUARDRAIL_ID
        invoke_kwargs["guardrailVersion"]    = GUARDRAIL_VERSION

    try:
        response = bedrock_runtime.invoke_model(**invoke_kwargs)
        payload = json.loads(response["body"].read())
    except ClientError as exc:
        logger.error("Reasoning generation failed: %s", exc)
        return {"status": "GENERATION_FAILED", "error": str(exc),
                "reasoning": {}, "id_to_source": id_to_source}

    guardrail_action = payload.get("amazon-bedrock-guardrailAction")
    if guardrail_action == "INTERVENED":
        logger.warning("Guardrail intervened on reasoning")
        return {"status": "GROUNDING_REJECTED",
                "reasoning": {}, "id_to_source": id_to_source}

    raw_text = payload["content"][0]["text"]
    reasoning = _parse_json_response(raw_text)
    if not reasoning:
        return {"status": "PARSE_FAILED", "reasoning": {},
                "id_to_source": id_to_source,
                "raw_text_snippet": raw_text[:500]}

    logger.info("Reasoning generated: %d hypotheses, %d contradictions, "
                "uncertainty=%s",
                len(reasoning.get("differential_or_recommendations", [])),
                len(reasoning.get("cross_modality_contradictions", [])),
                reasoning.get("overall_uncertainty"))
    return {"status": "GENERATED", "reasoning": reasoning,
            "id_to_source": id_to_source}


def _build_sources_block(patient_state: dict, inventory: dict,
                          retrieved: dict, safety_findings: dict
                          ) -> tuple[str, dict]:
    """
    Format every source with its stable source_id for prompt inclusion,
    and return the id_to_source map the validator will use to confirm
    citations exist.
    """
    lines = []
    id_to_source = {}

    # Imaging
    for img in patient_state.get("imaging_records", []):
        sid = img["source_id"]
        lines.append(
            f"[{sid}] Imaging: {img.get('study_description')}, "
            f"modality {img.get('study_modality')}, date {img.get('study_date')}, "
            f"age_hours {img.get('age_hours')}\n"
            f"Report text: {img.get('report_text')}\n"
        )
        for ai in img.get("cleared_ai_outputs") or []:
            lines.append(f"  Cleared AI output: {json.dumps(ai, default=str)}")
        id_to_source[sid] = img

    # ECG
    for ecg in patient_state.get("ecg_records", []):
        sid = ecg["source_id"]
        lines.append(
            f"[{sid}] ECG: date {ecg.get('ecg_date')}, HR {ecg.get('heart_rate')}, "
            f"QTc {ecg.get('qtc')}, QRS {ecg.get('qrs')}, "
            f"age_hours {ecg.get('age_hours')}\n"
            f"Machine interpretation: {ecg.get('machine_interpretation')}\n"
        )
        id_to_source[sid] = ecg

    # Labs
    for loinc, trend in patient_state.get("lab_trends", {}).items():
        sid = trend.get("source_id", f"lab:{loinc}")
        lines.append(
            f"[{sid}] Lab {trend.get('display_name')}: "
            f"current {trend.get('current_value')} {trend.get('current_unit', '')} "
            f"on {trend.get('current_date')}; "
            f"prior {trend.get('prior_value')} on {trend.get('prior_date')}; "
            f"trend {trend.get('classification')}; "
            f"delta {trend.get('delta_percent')}%\n"
        )
        id_to_source[sid] = trend

    # Vitals
    vitals = patient_state.get("vitals_summary", {})
    if vitals:
        lines.append(f"[vitals] Current encounter vitals: "
                     f"{json.dumps(vitals, default=str)}\n")
        id_to_source["vitals"] = vitals

    # Notes
    for note in patient_state.get("notes", []):
        sid = note["source_id"]
        lines.append(
            f"[{sid}] Note: {note.get('note_type')}, "
            f"specialty {note.get('specialty')}, date {note.get('note_date')}, "
            f"age_hours {note.get('age_hours')}\n"
            f"Key passages: {note.get('key_passages')}\n"
        )
        id_to_source[sid] = note

    # Retrieved guidelines / protocols / case analogs
    for g in retrieved.get("guidelines", []):
        sid = f"guideline:{g.get('chunk_id', g.get('id', 'unknown'))}"
        lines.append(
            f"[{sid}] Guideline: {g.get('issuing_body')}, "
            f"section {g.get('section')}, year {g.get('publication_year')}\n"
            f"Content: {g.get('recommendation_text', '')}\n"
        )
        id_to_source[sid] = {**g, "_kind": "guideline"}

    for p in retrieved.get("protocols", []):
        sid = f"protocol:{p.get('chunk_id', p.get('id', 'unknown'))}"
        lines.append(
            f"[{sid}] Institutional Protocol: {p.get('name', p.get('source_id'))}, "
            f"version {p.get('publication_year')}\n"
            f"Content: {p.get('recommendation_text', '')}\n"
        )
        id_to_source[sid] = {**p, "_kind": "protocol"}

    return "\n".join(lines), id_to_source


def _format_inventory_for_prompt(inventory: dict, scope_decision: dict) -> str:
    """Human-readable modality inventory for the prompt."""
    out = [f"Scope: {scope_decision.get('scoped_to')}, "
           f"reason: {scope_decision.get('reason')}"]
    for mod, info in inventory.items():
        out.append(f"- {mod}: {json.dumps(info, default=str)}")
    return "\n".join(out)


def _format_safety_for_prompt(safety_findings: dict, id_to_source: dict) -> str:
    """Flat bullet list of safety findings for the prompt."""
    lines = []
    for item in safety_findings.get("interactions", []):
        lines.append(
            f"- Interaction: {item['drug_a'].get('display')} + "
            f"{item['drug_b'].get('display')}, severity "
            f"{item.get('severity')}, management: {item.get('management')}"
        )
    for item in safety_findings.get("allergy_conflicts", []):
        lines.append(
            f"- Allergy conflict: {item['drug'].get('display')} vs allergy "
            f"'{item['allergy'].get('display')}'"
        )
    for item in safety_findings.get("renal_dose_flags", []):
        contraind = " (CONTRAINDICATED)" if item.get("contraindicated") else ""
        lines.append(
            f"- Renal consideration: {item['drug'].get('display')} at eGFR="
            f"{item.get('current_egfr')}: {item.get('recommended_dose')}"
            f"{contraind}. Notes: {item.get('notes')}"
        )
    for item in safety_findings.get("contraindications", []):
        lines.append(
            f"- Contraindication: {item['drug'].get('display')} in "
            f"{item['condition'].get('display')}"
        )
    return "\n".join(lines) if lines else \
        "(no deterministic safety findings for this scenario)"
```

---

## Step 8: Post-Generation Validation

*The pseudocode calls this `validate_reasoning(...)`. Belt-and-suspenders on top of Guardrails. Every citation resolves; every numeric value appears verbatim in a cited source; every graded term appears verbatim; every safety finding is represented; every relevant missing modality is acknowledged; no claim silently contradicts another modality; no directive language in the model's voice. Failures trigger regeneration with augmented prompting or route to human review.*

```python
def validate_reasoning(reasoning: dict, id_to_source: dict,
                        safety_findings: dict, modality_inventory: dict,
                        scope_decision: dict, retry_count: int = 0) -> dict:
    """
    Run layered validation on the generated reasoning output.

    Returns:
        Dict with status (VALIDATED | RETRY_NEEDED | REVIEW_REQUIRED),
        list of unverified issues, and a regeneration hint if retrying.
    """
    unverified = []
    items = reasoning.get("differential_or_recommendations", []) or []

    # 1. Citation resolution
    for item in items:
        cits = _collect_all_citations(item)
        for c in cits:
            if c not in id_to_source:
                unverified.append({
                    "issue": "citation_not_in_retrieved_set",
                    "item": item.get("title"), "citation": c,
                    "severity": "HIGH",
                })
        if not cits:
            unverified.append({
                "issue": "recommendation_without_citations",
                "item": item.get("title"), "severity": "HIGH",
            })

    # 2. Verbatim quantitative check
    # Regex alternatives are tried left-to-right. Longer, more specific
    # units (`ng/mL FEU`) come before shorter prefixes (`ng/mL`) so the
    # full unit matches before a prefix consumes the numeric value.
    quantity_regex = re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:%|mcg|mg|g|mL|mmHg|bpm|ng/mL FEU|ng/mL|"
        r"pg/mL|U/L|mmol/L|ms)\b",
        flags=re.IGNORECASE,
    )
    for item in items:
        text_blob = _collect_item_text(item)
        cited_sources = [id_to_source.get(c, {})
                         for c in _collect_all_citations(item)]
        source_blob = json.dumps(cited_sources, default=str)
        for match in quantity_regex.findall(text_blob):
            if match not in source_blob:
                # Normalize whitespace before giving up
                if re.sub(r"\s+", "", match) not in re.sub(r"\s+", "", source_blob):
                    unverified.append({
                        "issue": "quantity_not_verbatim",
                        "item": item.get("title"), "quantity": match,
                        "severity": "HIGH",
                    })

    # 3. Graded-term verbatim check
    for item in items:
        text_blob = _collect_item_text(item).lower()
        cited_sources = [id_to_source.get(c, {})
                         for c in _collect_all_citations(item)]
        source_blob = json.dumps(cited_sources, default=str).lower()
        for term in GRADED_TERMS:
            pattern = rf"\b{re.escape(term)}\b"
            if re.search(pattern, text_blob):
                # If the reasoning uses a graded term, at least one cited
                # source must use the same term.
                if not re.search(pattern, source_blob):
                    unverified.append({
                        "issue": "graded_term_not_in_sources",
                        "item": item.get("title"), "term": term,
                        "severity": "HIGH",
                    })

    # 4. Safety findings represented
    all_safety = _flatten_safety_items(safety_findings)
    representations = _flatten_safety_representations(reasoning)
    for sig in all_safety:
        if not any(sig in r for r in representations):
            unverified.append({
                "issue": "safety_finding_missing",
                "finding": sig, "severity": "HIGH",
            })

    # 5. Missing-modality acknowledgment
    requirements = SCENARIO_MODALITY_REQUIREMENTS.get(
        scope_decision.get("scoped_to", "comprehensive_reasoning"),
        SCENARIO_MODALITY_REQUIREMENTS["comprehensive_reasoning"],
    )
    relevant_missing = [
        r for r in requirements.get("recommended", [])
        if not _modality_available(modality_inventory, r)
    ]
    acknowledged = " ".join(
        json.dumps(m, default=str)
        for m in reasoning.get("modalities_absent_and_relevant", []) or []
    ).lower()
    for m in relevant_missing:
        if m.lower() not in acknowledged:
            unverified.append({
                "issue": "missing_modality_not_acknowledged",
                "modality": m, "severity": "MEDIUM",
            })

    # 6. Directive language check (in model's own voice, not quoted)
    for item in items:
        text = _collect_item_text(item)
        unquoted = re.sub(r'"[^"]*"', "", text)
        for phrase in DIRECTIVE_PHRASES:
            if re.search(rf"\b{re.escape(phrase)}\b", unquoted,
                         flags=re.IGNORECASE):
                unverified.append({
                    "issue": "directive_language_in_model_voice",
                    "item": item.get("title"), "phrase": phrase,
                    "severity": "MEDIUM",
                })

    # NOTE: two validator checks from the Recipe 2.10 pseudocode are NOT
    # implemented in this teaching example:
    #   - Cross-modality consistency scan (semantic contradiction
    #     detection across modalities that the reasoning did not
    #     acknowledge).
    #   - Scope-compliance check (classifier over scope_decision.scoped_to
    #     that flags recommendations outside the scenario scope).
    # Both require more than regex and are discussed in the main recipe's
    # "Gap to Production" section. Production validators include a
    # semantic-similarity pass and a scope classifier.

    high = sum(1 for u in unverified if u["severity"] == "HIGH")
    medium = sum(1 for u in unverified if u["severity"] == "MEDIUM")

    if high == 0 and medium <= max(1, len(items) // 5):
        logger.info("Validation PASSED (0 HIGH, %d MEDIUM)", medium)
        return {"status": "VALIDATED", "unverified": unverified}

    if retry_count < MAX_GENERATION_ATTEMPTS - 1:
        hint = _build_validation_hint(unverified)
        logger.info("Validation: %d HIGH / %d MEDIUM; requesting retry",
                    high, medium)
        return {"status": "RETRY_NEEDED", "unverified": unverified,
                "suggested_prompt_augmentation": hint}

    logger.warning("Validation exhausted retries; routing to review "
                   "(%d HIGH, %d MEDIUM)", high, medium)
    return {"status": "REVIEW_REQUIRED", "unverified": unverified}


def _collect_all_citations(item: dict) -> list:
    """Walk an item's evidence lists and collect every source_citation."""
    cits = []
    for side in ("evidence_for", "evidence_against"):
        for e in item.get(side, []) or []:
            cits.extend(e.get("source_citations", []) or [])
    # The description and reasoning fields may also contain [bracketed] cites.
    text = _collect_item_text(item)
    for m in re.findall(r"\[([^\]]+)\]", text):
        if ":" in m:
            cits.append(m)
    return list(set(cits))


def _collect_item_text(item: dict) -> str:
    """Concatenate all text fields of an item for scanning."""
    parts = [item.get("description") or "",
             item.get("cross_modality_notes") or "",
             item.get("recency_notes") or ""]
    for side in ("evidence_for", "evidence_against"):
        for e in item.get(side, []) or []:
            parts.append(e.get("text") or "")
    for step in item.get("suggested_next_steps") or []:
        parts.append(str(step))
    return " ".join(parts)


def _flatten_safety_items(safety_findings: dict) -> list:
    """Short signatures for every safety finding (drug/condition/etc)."""
    sigs = []
    for item in safety_findings.get("interactions", []) or []:
        sigs.append(
            (item.get("drug_a", {}).get("display", "") + " " +
             item.get("drug_b", {}).get("display", "")).lower().strip()
        )
    for item in safety_findings.get("allergy_conflicts", []) or []:
        sigs.append(
            (item.get("drug", {}).get("display", "") + " " +
             item.get("allergy", {}).get("display", "")).lower().strip()
        )
    for item in safety_findings.get("renal_dose_flags", []) or []:
        drug = (item.get("drug", {}).get("display") or "").lower()
        sigs.append(drug)
    for item in safety_findings.get("contraindications", []) or []:
        sigs.append(
            (item.get("drug", {}).get("display", "") + " " +
             item.get("condition", {}).get("display", "")).lower().strip()
        )
    return [s for s in sigs if s]


def _flatten_safety_representations(reasoning: dict) -> list:
    """Gather text representations of safety findings from the reasoning."""
    reps = []
    for s in reasoning.get("safety_findings_included", []) or []:
        reps.append((s.get("finding") or "").lower())
    for item in reasoning.get("differential_or_recommendations", []) or []:
        reps.append(_collect_item_text(item).lower())
    return reps


def _build_validation_hint(unverified: list) -> str:
    """Compact regeneration hint covering the distinct issue types seen."""
    seen = set()
    lines = ["The previous draft had validation failures. Fix these:"]
    for u in unverified:
        key = u.get("issue")
        if key in seen:
            continue
        seen.add(key)
        if key == "citation_not_in_retrieved_set":
            lines.append(
                "- You cited source_ids not in the SOURCES block. Only cite "
                "IDs that appear with brackets in the SOURCES block."
            )
        elif key == "recommendation_without_citations":
            lines.append("- Every differential or recommendation must cite "
                         "at least one source.")
        elif key == "quantity_not_verbatim":
            lines.append(
                "- Numeric values in the output must appear VERBATIM in a "
                "cited source. Do not paraphrase quantities."
            )
        elif key == "graded_term_not_in_sources":
            lines.append(
                "- Graded terms (mild, moderate, severe, preserved, reduced) "
                "must appear VERBATIM in a cited source. Do not upgrade or "
                "downgrade grades."
            )
        elif key == "safety_finding_missing":
            lines.append(
                "- Every SAFETY FINDING must appear in the output. Surface "
                "each one in safety_findings_included or in a recommendation."
            )
        elif key == "missing_modality_not_acknowledged":
            lines.append(
                "- The inventory shows relevant modalities are absent. "
                "Name each one in modalities_absent_and_relevant."
            )
        elif key == "directive_language_in_model_voice":
            lines.append(
                "- Remove directive language ('administer', 'give', "
                "'prescribe', 'you should') from your own voice. Frame as "
                "options: 'Consider', 'Option A involves', 'The guideline "
                "supports'. Directives may appear in verbatim quoted "
                "guideline text inside double quotes."
            )
    return "\n".join(lines)
```

---

## Step 9: Tier, Render, and Archive

*The pseudocode calls this `tier_render_archive(...)`. Assign each recommendation a delivery tier based on clinical importance and whether it materially changes from prior runs. Substitute bracketed source_ids with numbered citations and build a bibliography with deep links to each modality source. Archive the full provenance.*

```python
def tier_render_archive(reasoning: dict, id_to_source: dict,
                         run_id: str, patient_id: str,
                         encounter_id: str, scope_decision: dict,
                         trace: dict) -> dict:
    """
    Render the reasoning with numbered citations, build the bibliography,
    and archive the full provenance to S3 and DynamoDB.

    Returns the rendered payload plus pointers to the archived artifacts.
    """
    now_iso = _now_iso()

    # Replace source_ids with numbered citations [1], [2], ...
    numbered = {}
    bibliography = []
    next_num = [1]

    def _replace(text: str) -> str:
        if not text:
            return text
        def _sub(match):
            cid = match.group(1)
            if cid not in id_to_source:
                return match.group(0)
            if cid not in numbered:
                numbered[cid] = next_num[0]
                source = id_to_source[cid]
                bibliography.append({
                    "number":      next_num[0],
                    "source_id":   cid,
                    "modality":    source.get("modality_type")
                                   or source.get("_kind", "unknown"),
                    "formatted":   _format_source_for_bibliography(source),
                    "deep_link":   _deep_link_for_source(source, cid),
                    "age_hours":   source.get("age_hours"),
                })
                next_num[0] += 1
            return f"[{numbered[cid]}]"
        return re.sub(r"\[([^\]]+)\]", _sub, text)

    rendered_items = []
    for item in reasoning.get("differential_or_recommendations", []) or []:
        r = dict(item)
        for field in ("description", "cross_modality_notes", "recency_notes"):
            r[field] = _replace(r.get(field) or "")
        for side in ("evidence_for", "evidence_against"):
            r[side] = [{**e, "text": _replace(e.get("text") or "")}
                       for e in (r.get(side) or [])]
        rendered_items.append(r)

    rendered_contradictions = []
    for c in reasoning.get("cross_modality_contradictions", []) or []:
        rendered_contradictions.append({
            **c, "description": _replace(c.get("description") or ""),
        })

    rendered_safety = []
    for s in reasoning.get("safety_findings_included", []) or []:
        rendered_safety.append({
            **s, "finding": _replace(s.get("finding") or ""),
        })

    rendered = {
        "run_id":                         run_id,
        "patient_id":                     patient_id,
        "encounter_id":                   encounter_id,
        "scenario":                       scope_decision.get("scoped_to"),
        "overall_assessment":             reasoning.get("overall_assessment"),
        "differential_or_recommendations": rendered_items,
        "cross_modality_contradictions":  rendered_contradictions,
        "safety_findings_included":       rendered_safety,
        "modalities_used":                reasoning.get("modalities_used") or [],
        "modalities_absent_and_relevant": reasoning.get("modalities_absent_and_relevant") or [],
        "what_is_insufficient_to_answer": reasoning.get("what_is_insufficient_to_answer") or [],
        "overall_uncertainty":            reasoning.get("overall_uncertainty"),
        "uncertainty_rationale":          reasoning.get("uncertainty_rationale"),
        "bibliography":                   bibliography,
        "disclaimer": (
            "This output is decision support synthesizing available "
            "multi-modal evidence. Review each cited source before acting. "
            "The clinician is the decision-maker."
        ),
    }

    # Archive rendered payload and trace to S3
    rendered_key = f"reasoning-runs/{run_id}/rendered.json"
    s3_client.put_object(
        Bucket=REASONING_ARCHIVE_BUCKET,
        Key=rendered_key,
        Body=json.dumps(rendered, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=REASONING_ARCHIVE_CMK_ARN,
    )

    trace_key = f"reasoning-runs/{run_id}/trace.json"
    s3_client.put_object(
        Bucket=REASONING_ARCHIVE_BUCKET,
        Key=trace_key,
        Body=json.dumps({**trace, "generated_at": now_iso},
                       indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=REASONING_ARCHIVE_CMK_ARN,
    )

    runs_table = dynamodb.Table(REASONING_RUNS_TABLE)
    runs_table.update_item(
        Key={"run_id": run_id},
        UpdateExpression=(
            "SET #s = :s, rendered_s3_key = :rk, trace_s3_key = :tk, "
            "delivered_at = :d, num_recommendations = :nr, "
            "uncertainty = :u"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s":  "DELIVERED",
            ":rk": rendered_key,
            ":tk": trace_key,
            ":d":  now_iso,
            ":nr": len(rendered_items),
            ":u":  rendered.get("overall_uncertainty") or "unknown",
        },
    )

    try:
        cloudwatch.put_metric_data(
            Namespace="MultiModalClinicalReasoning",
            MetricData=[
                {"MetricName": "ReasoningRunsDelivered",
                 "Value": 1.0, "Unit": "Count"},
                {"MetricName": "ModalitiesUsed",
                 "Value": float(len(rendered.get("modalities_used", []))),
                 "Unit": "Count"},
                {"MetricName": "CrossModalityContradictionsSurfaced",
                 "Value": float(len(rendered_contradictions)),
                 "Unit": "Count"},
            ],
        )
    except ClientError as exc:
        logger.warning("Metric emission failed: %s", exc)

    logger.info("Reasoning run %s archived (DELIVERED, %d items)",
                run_id, len(rendered_items))
    return {"status": "DELIVERED", "rendered": rendered,
            "rendered_key": rendered_key, "trace_key": trace_key}


def _format_source_for_bibliography(source: dict) -> str:
    """Human-readable bibliography entry for a source."""
    if source.get("_kind") == "guideline":
        return (f"{source.get('issuing_body', 'Unknown issuer')}. "
                f"{source.get('section', '')}. "
                f"{source.get('publication_year', 'n.d.')}.")
    if source.get("_kind") == "protocol":
        return (f"Institutional Protocol: {source.get('name', source.get('source_id'))}, "
                f"rev. {source.get('publication_year', 'n.d.')}.")
    modality = source.get("modality_type")
    if modality == "imaging":
        return (f"Imaging: {source.get('study_description')} "
                f"({source.get('study_modality')}), "
                f"{source.get('study_date')}.")
    if modality == "ecg":
        return f"ECG, {source.get('ecg_date')}."
    if modality == "note":
        return (f"Note ({source.get('note_type')}, "
                f"{source.get('specialty')}), {source.get('note_date')}.")
    if "current_value" in source:
        return (f"Lab {source.get('display_name')}: "
                f"{source.get('current_value')} {source.get('current_unit', '')}, "
                f"{source.get('current_date')}.")
    return json.dumps(source, default=str)[:160]


def _deep_link_for_source(source: dict, source_id: str) -> str:
    """Deep link into the source's native system for clinician review."""
    if source.get("modality_type") == "imaging":
        return source.get("pacs_deep_link", f"pacs://unknown/{source_id}")
    if source.get("modality_type") == "ecg":
        return source.get("deep_link", f"ecg://{source_id}")
    if source.get("modality_type") == "note":
        return f"ehr://notes/{source_id}"
    if source.get("_kind") == "guideline":
        return source.get("source_url", "")
    if source.get("_kind") == "protocol":
        return source.get("source_url", "")
    return f"internal://sources/{source_id}"
```

---

## Putting It All Together

The full pipeline assembled into one callable. Runs every step sequentially for one trigger. In production, each step becomes a Step Functions state; the parallel modality ingestion uses a Parallel or Map state; the generation-validation retry loop is a proper state-machine loop with a bounded counter. The sequential Python version below is fine for understanding the flow.

```python
# _collect_all_citations is defined in Step 8 above; it is the text-scanning
# version that also reads bracketed inline citations from description and
# evidence fields. Do NOT redefine it here; a second `def` at module scope
# would silently shadow the Step 8 helper and weaken the validator.


def run_multi_modal_reasoning(trigger: dict) -> dict:
    """
    Run the full multi-modal clinical reasoning pipeline for one trigger.

    Steps (matching the Recipe 2.10 pseudocode):
      1. Start the reasoning run
      2. Parallel modality ingestion (imaging, ECG, labs+vitals, notes,
         structured context)
      3. Normalize and build the modality inventory
      4. Scope gate
      5. Deterministic safety checks (reused from Recipe 2.9)
      6. Multi-source retrieval
      7. Reasoning layer with grounded multi-hypothesis synthesis
      8. Post-generation validation (with Step-7 retry on failure)
      9. Tier, render, archive

    Returns:
        Dict with pipeline status, run_id, and the rendered payload (or
        a suppression/failure record).
    """
    start = time.time()

    # Step 1
    print("Step 1: Starting reasoning run...")
    s1 = start_reasoning_run(trigger)
    run_id = s1["run_id"]
    patient_id = trigger.get("patient_id", "")
    encounter_id = trigger.get("encounter_id", "")
    scenario = trigger.get("scenario", "comprehensive_reasoning")
    print(f"  run_id={run_id}, scenario={scenario}")

    # Step 2: parallel modality ingestion (sequential here for clarity)
    print("Step 2: Ingesting modalities...")
    imaging = ingest_imaging(run_id, patient_id, scenario)
    ecg = ingest_ecg(run_id, patient_id, scenario, encounter_id)
    labs_vitals = ingest_labs_and_vitals(run_id, patient_id, scenario)
    notes = ingest_notes(run_id, patient_id, scenario)
    structured = ingest_structured_context(run_id, patient_id)
    print(f"  imaging={len(imaging)}, ecg={len(ecg)}, "
          f"labs={len(labs_vitals.get('lab_trends', {}))}, "
          f"notes={len(notes)}")

    # Step 3: normalize and inventory
    print("Step 3: Normalizing and building modality inventory...")
    norm = normalize_and_inventory(imaging, ecg, labs_vitals, notes, structured)
    patient_state = norm["patient_state"]
    modality_inventory = norm["modality_inventory"]

    # Step 4: scope gate
    print("Step 4: Checking scope gate...")
    recent_runs = _query_recent_runs(patient_id, encounter_id)
    scope_decision = scope_gate(scenario, modality_inventory, patient_id,
                                 recent_runs)
    if not scope_decision["proceed"]:
        runs_table = dynamodb.Table(REASONING_RUNS_TABLE)
        runs_table.update_item(
            Key={"run_id": run_id},
            UpdateExpression="SET #s = :s, scope_reason = :r, "
                             "missing_modalities = :m",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "DEFERRED_BY_SCOPE_GATE",
                ":r": scope_decision.get("reason", ""),
                ":m": scope_decision.get("missing", []),
            },
        )
        elapsed_ms = int((time.time() - start) * 1000)
        print(f"  Deferred: {scope_decision.get('reason')}")
        return {"status": "DEFERRED", "run_id": run_id,
                "reason": scope_decision.get("reason"),
                "missing": scope_decision.get("missing"),
                "processing_time_ms": elapsed_ms}
    print(f"  Scope: proceed, scoped_to={scope_decision.get('scoped_to')}")

    # Step 5: deterministic safety checks
    print("Step 5: Running safety checks...")
    safety_findings = run_safety_checks(patient_state["structured_context"])

    # Step 6: retrieval
    print("Step 6: Retrieving supporting content...")
    retrieved = retrieve_supporting_content(
        scope_decision["scoped_to"], patient_state, modality_inventory,
    )

    # Steps 7+8: generation + validation loop
    generation_result = None
    validation_result = None
    regeneration_hint = ""
    attempts = 0

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        attempts = attempt
        print(f"Step 7 (attempt {attempt}): Invoking reasoning layer...")
        generation_result = invoke_reasoning_layer(
            scenario=scope_decision["scoped_to"],
            patient_state=patient_state,
            modality_inventory=modality_inventory,
            retrieved=retrieved,
            safety_findings=safety_findings,
            scope_decision=scope_decision,
            regeneration_hint=regeneration_hint,
        )
        if generation_result["status"] == "GROUNDING_REJECTED":
            regeneration_hint = (
                "The previous draft was rejected by the grounding check. "
                "Stay strictly within content from the SOURCES block. "
                "Do not add facts beyond what the sources support."
            )
            continue
        if generation_result["status"] != "GENERATED":
            break

        print(f"Step 8 (attempt {attempt}): Validating reasoning...")
        validation_result = validate_reasoning(
            reasoning=generation_result["reasoning"],
            id_to_source=generation_result["id_to_source"],
            safety_findings=safety_findings,
            modality_inventory=modality_inventory,
            scope_decision=scope_decision,
            retry_count=attempt - 1,
        )
        print(f"  Validation: {validation_result['status']}")

        if validation_result["status"] == "VALIDATED":
            break
        if validation_result["status"] == "REVIEW_REQUIRED":
            break
        regeneration_hint = validation_result.get(
            "suggested_prompt_augmentation", "",
        )

    if not generation_result or generation_result["status"] != "GENERATED":
        runs_table = dynamodb.Table(REASONING_RUNS_TABLE)
        runs_table.update_item(
            Key={"run_id": run_id},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "GENERATION_FAILED"},
        )
        elapsed_ms = int((time.time() - start) * 1000)
        return {"status": "GENERATION_FAILED", "run_id": run_id,
                "processing_time_ms": elapsed_ms}

    # Orchestration gate between Step 8 and Step 9: only VALIDATED reasoning
    # is delivered to the clinician UI. REVIEW_REQUIRED is a terminal state;
    # archive the trace for audit, enqueue for clinical review, do NOT call
    # tier_render_archive. See the main recipe's "Orchestration gate between
    # Step 8 and Step 9" pseudocode block.
    if not validation_result or validation_result.get("status") != "VALIDATED":
        review_trace_key = f"reasoning-runs/{run_id}/review-queue-trace.json"
        try:
            s3_client.put_object(
                Bucket=REASONING_ARCHIVE_BUCKET,
                Key=review_trace_key,
                Body=json.dumps({
                    "run_id":             run_id,
                    "trigger":            trigger,
                    "scope_decision":     scope_decision,
                    "modality_inventory": modality_inventory,
                    "safety_findings":    safety_findings,
                    "raw_reasoning":      generation_result.get("reasoning"),
                    "validation_result":  validation_result,
                    "routed_at":          _now_iso(),
                }, indent=2, default=str).encode("utf-8"),
                ContentType="application/json",
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=REASONING_ARCHIVE_CMK_ARN,
            )
        except ClientError as exc:
            logger.error("Failed to archive review-queue trace for %s: %s",
                         run_id, exc)

        runs_table = dynamodb.Table(REASONING_RUNS_TABLE)
        runs_table.update_item(
            Key={"run_id": run_id},
            UpdateExpression=(
                "SET #s = :s, review_trace_s3_key = :rk, "
                "validation_issues = :v, routed_at = :r"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s":  "ROUTED_TO_REVIEW",
                ":rk": review_trace_key,
                ":v":  (validation_result or {}).get("unverified", []),
                ":r":  _now_iso(),
            },
        )

        # Enqueue to a clinical reviewer queue (SQS, DynamoDB stream, or
        # equivalent). Reviewer triage is out of scope for this example.
        try:
            cloudwatch.put_metric_data(
                Namespace="MultiModalClinicalReasoning",
                MetricData=[{"MetricName": "ReasoningRoutedToReview",
                             "Value": 1.0, "Unit": "Count"}],
            )
        except ClientError:
            pass

        elapsed_ms = int((time.time() - start) * 1000)
        logger.warning("Run %s routed to clinical review; not delivered",
                       run_id)
        return {"status":             "ROUTED_TO_REVIEW",
                "run_id":             run_id,
                "review_trace_key":   review_trace_key,
                "validation_result":  validation_result,
                "attempts":           attempts,
                "processing_time_ms": elapsed_ms}

    # Step 9: tier, render, archive
    print("Step 9: Tiering, rendering, archiving...")
    trace = {
        "run_id":                  run_id,
        "trigger":                 trigger,
        "scope_decision":          scope_decision,
        "modality_inventory":      modality_inventory,
        "retrieved_source_counts": {
            "guidelines":   len(retrieved.get("guidelines", [])),
            "protocols":    len(retrieved.get("protocols", [])),
            "case_analogs": len(retrieved.get("case_analogs", [])),
        },
        "safety_findings":         safety_findings,
        "prompt_version":          "v1",
        "reasoning_model":         REASONING_MODEL_ID,
        "small_model":             SMALL_MODEL_ID,
        "embedding_model":         EMBEDDING_MODEL_ID,
        "raw_reasoning_output":    generation_result.get("reasoning"),
        "validation_result":       validation_result,
        "attempts":                attempts,
    }
    archive = tier_render_archive(
        reasoning=generation_result["reasoning"],
        id_to_source=generation_result["id_to_source"],
        run_id=run_id,
        patient_id=patient_id,
        encounter_id=encounter_id,
        scope_decision=scope_decision,
        trace=trace,
    )

    elapsed_ms = int((time.time() - start) * 1000)
    print(f"\nDone. Processing time: {elapsed_ms} ms")

    return {
        "status":            "DELIVERED",
        "run_id":            run_id,
        "rendered":          archive["rendered"],
        "rendered_key":      archive["rendered_key"],
        "trace_key":         archive["trace_key"],
        "attempts":          attempts,
        "processing_time_ms": elapsed_ms,
    }


def _query_recent_runs(patient_id: str, encounter_id: str) -> list:
    """
    Query DynamoDB for recent runs for this patient+encounter. In
    production, index on (patient_id, encounter_id, delivered_at). Stub
    returns an empty list so the example runs without history.
    """
    return []


# --- Example usage ---
if __name__ == "__main__":
    # All clinical content is SYNTHETIC. Do not use real PHI in development.
    # This example assumes the Bedrock generation model is available in
    # your region and that the HealthLake, HealthImaging, OpenSearch, and
    # Aurora stubs are replaced with real integrations before running
    # against real data.
    trigger = {
        "trigger_type": "clinician_request",
        "patient_id":   "pt_illustrative_62f_ed",
        "encounter_id": "enc_illustrative_2amed",
        "scenario":     "ed_dyspnea_workup",
        "clinician_id": "CLN-ED-023",
        "payload": {
            "chief_complaint": "progressive dyspnea over 3 days",
            "question": (
                "62-year-old woman with history of anthracycline-treated "
                "breast cancer, CKD (eGFR 44), type 2 diabetes, rheumatoid "
                "arthritis on methotrexate, presenting with progressive "
                "dyspnea. Vitals: HR 108, BP 112/68, RR 22, SpO2 93% RA. "
                "Labs notable for mildly elevated troponin (0.08), BNP 840, "
                "creatinine 1.6 (up from 1.3), D-dimer 1200. CXR: bibasilar "
                "opacities, broad differential. Help with next-step reasoning."
            ),
        },
    }

    result = run_multi_modal_reasoning(trigger)

    print("\n" + "=" * 60)
    print("RESULT SUMMARY:")
    print("=" * 60)
    print(json.dumps({
        "status":             result.get("status"),
        "run_id":             result.get("run_id"),
        "attempts":           result.get("attempts"),
        "processing_time_ms": result.get("processing_time_ms"),
    }, indent=2, default=str))

    if result.get("rendered"):
        rendered = result["rendered"]
        print("\n" + "-" * 60)
        print("OVERALL ASSESSMENT:")
        print("-" * 60)
        print(rendered.get("overall_assessment", ""))

        print("\n" + "-" * 60)
        print("MODALITIES ABSENT AND RELEVANT:")
        print("-" * 60)
        for m in rendered.get("modalities_absent_and_relevant", []):
            print(f"  - {m}")

        print("\n" + "-" * 60)
        print("DIFFERENTIAL / RECOMMENDATIONS:")
        print("-" * 60)
        for item in rendered.get("differential_or_recommendations", [])[:4]:
            print(f"\n- {item.get('title')} "
                  f"[tier={item.get('tier')}, "
                  f"confidence={item.get('confidence_given_data')}, "
                  f"completeness={item.get('completeness_of_data')}]")
            print(f"  {(item.get('description') or '')[:400]}")

        print("\n" + "-" * 60)
        print("CROSS-MODALITY CONTRADICTIONS SURFACED:")
        print("-" * 60)
        for c in rendered.get("cross_modality_contradictions", []):
            print(f"  - {c.get('description')}")

        print("\n" + "-" * 60)
        print("BIBLIOGRAPHY:")
        print("-" * 60)
        for entry in rendered.get("bibliography", []):
            print(f"  [{entry['number']}] ({entry.get('modality')}) "
                  f"{entry.get('formatted')}")
```

---

## The Gap Between This and Production

Run this end-to-end with real HealthLake, HealthImaging, OpenSearch, Aurora, and Bedrock endpoints, and you'll see the shape: trigger received, modalities ingested in parallel, normalized with a modality inventory, scope-gated, safety-checked deterministically, retrieved against guidelines and protocols, reasoned through with citation discipline and cross-modality awareness, validated for citations and verbatim preservation, tiered and rendered with a full bibliography, archived with full provenance. The distance between this sketch and a real hospital deployment is larger than for any other recipe in this chapter. Here's where the gap lives.

**Regulatory determination before anything else.** Multi-modal clinical reasoning sits closer to the edge of the FDA CDS exemption than any other recipe in this chapter. Before any pilot, document the scope, the exemption analysis (four criteria), the specific design decisions supporting independent clinician review, the UI posture, the source transparency, and the review workflow. If your determination lands on the device-regulated side, the development path changes substantially (FDA submission, validation studies under a quality management system, labeling, post-market surveillance). Involve regulatory affairs and legal at design time, not at launch time. Revisit the determination whenever the scope expands or the UX materially changes.

**Cleared imaging AI vendor integration.** The `_get_cleared_imaging_ai_output` stub returns None. Real integrations use vendor APIs (Aidoc, Viz.ai, RapidAI, and others per indication) with webhook-style result delivery tied to study instance UIDs or HL7 feeds for finding notifications. Each vendor has specific clearance scope (patient population, modality, finding type, imaging vendor compatibility). Use a vendor's output only within its cleared scope; the reasoning pipeline treats the output as a structured input, not as a diagnostic conclusion to restate. Contracts include workflow integration, liability terms, retention, and sometimes revenue share. Evaluate vendors against your patient population data, not just the published clearance data.

**HealthImaging DICOM integration is real work.** The stub returns a fixed dict. Real integration uses `medical-imaging:GetImageSetMetadata` (or DICOMweb) with proper auth, handles the gzipped JSON response, extracts the relevant DICOM tags (study instance UID, modality, study description, date, series count, accession number), and constructs PACS deep-links that open the study in the clinician's image viewer. Prior imaging retrieval uses HealthImaging's study-index search. The metadata surface is rich; your code needs to handle the DICOM-standard tag references and the HealthImaging-specific access patterns.

**HealthLake FHIR integration is a stub.** The `_fetch_radiology_report_from_healthlake`, `_synthetic_ecg_records`, and `_synthetic_observations_for_loinc` functions return synthetic data. Real integrations use SigV4-signed HTTPS against the HealthLake datastore endpoint or call the EHR's FHIR API directly with OAuth2/SMART-on-FHIR. FHIR resources vary across EHR vendors (Epic and Cerner disagree on code systems, status values, and resource shapes); build a FHIR client layer that normalizes across vendors. Retry transient failures; handle pagination for resources with large result sets; bound date windows per resource type to control latency.

**ECG foundation model integration.** The `_invoke_ecg_foundation_model` function is a stub. Real ECG foundation models (Mayo-trained LV dysfunction detector, similar models from academic centers) require waveform access (WFDB or XML from an ECG management system), have specific input-format requirements, and are typically deployed on SageMaker Endpoints when self-hosted or behind a vendor API when vendor-hosted. Very few are FDA-cleared as diagnostic devices; verify clearance scope before routing output into a clinical reasoning pipeline.

**Guideline and case-analog corpus ingestion is 50%+ of the work.** The retrieval stubs return empty lists. The real work is building the corpus: guideline ingestion (parse PDFs into recommendation-grained chunks, tag with clinical domain, population, evidence tier, issuing body, publication year; embed with a medical-aware embedder; load into OpenSearch with proper field mappings), institutional protocol ingestion (work with clinical operations to collect and chunk current protocols), and optionally case-analog corpus curation (a high-value but expensive artifact that requires expert annotation). Ingestion runs as a separate Step Functions workflow with scheduled rebuilds. Source licensing (Lexicomp, Micromedex, First Databank, NCCN, UpToDate, DynaMed, and others) has specific redistribution terms; maintain a license registry and audit quarterly.

**Aurora drug database population.** The `run_safety_checks` stub returns a small synthetic result. The real implementation (Recipe 2.9 Step 4) depends on a populated drug database with interactions, renal dosing, and contraindications. Populating it from Lexicomp, First Databank, or open sources (DDInter, FDA SPLs) is its own ETL project.

**Bedrock Guardrails contextual grounding is non-optional.** The example leaves `GUARDRAIL_ID = None`. Production must configure a Guardrail with contextual grounding at a strict threshold (0.85+) using the combined sources+inventory+safety block as the authoritative content. Pair the Guardrail with the validator in Step 8 as defense in depth: the Guardrail catches gross drift; the validator catches precise citation and verbatim-preservation failures that the Guardrail's soft scoring sometimes misses.

**Missing-modality acknowledgment is the hardest invariant to enforce.** The validator in Step 8 does a coarse string match on whether the required-but-missing modality names appear in `modalities_absent_and_relevant`. Production systems need richer matching (synonyms, clinical-context awareness) and strong prompt-level reinforcement with failure examples. This is the specific failure mode that causes reasoning to proceed as if an absent study were present, which is the specific failure that hurts patients.

**Cross-modality contradiction detection needs more than prompting.** The prompt asks the model to surface contradictions; the validator has no automated check for whether contradictions genuinely exist in the data and whether the model acknowledged them. Production validators include a semantic-similarity pass that flags claims whose content contradicts another modality's source without acknowledgment. This is a hard NLP problem and an active research area. Use prompt-level enforcement plus output-level auditing, and treat occasional misses as something the clinician-in-the-loop catches rather than as something the pipeline can always prevent.

**Verbatim preservation for numerics and graded terms.** The validator does regex-based matching for common numeric formats and a fixed list of graded terms. Production versions need unit-aware numeric comparison (mg vs milligram; mcg vs μg vs micrograms; percentage vs fraction; preserve trailing-zero variants), fuzzy matching with high threshold for graded terms across synonym sets, and false-positive avoidance for terms that appear in non-graded contexts (e.g., "mild" in "mild symptoms" in an unrelated passage). Test each validator change against a regression suite of labeled examples.

**Step Functions orchestration.** The Python pipeline runs sequentially; production splits into states: Step 1 kicks off; Step 2 uses a Parallel state with one branch per modality; Step 3 merges; Step 4 is a Choice state that either proceeds, scopes down, or defers; Steps 5-6 run in parallel; Steps 7-8 form a bounded retry loop; Step 9 archives. The state machine makes the flow visible, resumable, and debuggable. Retrofitting Step Functions onto a tangled Python orchestration is a rewrite; start there.

**Prompt versioning from day one.** The reasoning prompt in Step 7 is version 1. It will evolve as you encounter specific failure modes. Store the prompt text in SSM Parameter Store or AppConfig with versioning, stamp every delivered reasoning run with the exact prompt version and model version, and maintain a regression test suite (labeled scenarios with expert-reviewed gold answers) that runs before promoting a new prompt version. Prompt changes that affect clinical content require clinical review; build the review workflow explicitly.

**Clinical validation studies per scenario.** Every reasoning scenario (ED dyspnea workup, HF management, oncology treatment planning) needs its own curated validation set with expert-reviewed gold answers. Run the pipeline against the set; have clinical domain experts review outputs; quantify agreement with clinically-meaningful metrics; iterate. This is slow (weeks per scenario), expensive (expert time), and non-negotiable. Budget 4-8 weeks of clinical-reviewer time per major scenario category. The day you stop running validation is the day your scope stops expanding safely.

**Post-market surveillance is half the work.** Once deployed, instrument every reasoning run to trace to downstream clinical events: did the clinician accept the reasoning? did the patient outcome match the implicit prediction? over time, are there patterns of error correlated with specific scenario types, specific patient subgroups, or specific modalities? This is the regulatory evidence trail for a CDS-exempt product, and the input to your improvement cycle. Without this loop, the system plateaus.

**Subgroup and fairness monitoring.** Each modality inherits biases from its training data; the reasoning layer inherits biases from its training and retrieval corpora. Multi-modal pipelines compound these biases. Instrument subgroup performance (demographic, comorbidity, language-of-record) across delivered runs. Monitor and publish. Act on disparities. This is table stakes for clinical AI.

**EHR workflow integration.** CDS in a separate tab is CDS that does not get read. SMART on FHIR for EHR-launched apps, CDS Hooks for specific workflow triggers (order entry, encounter open, problem-list update), and deep linking from the reasoning output back into the EHR (imaging viewer, lab trend, note) are the integration patterns that earn engagement. Plan integration as a first-class project.

**Alert fatigue and suppression tuning.** `SUPPRESSION_WINDOW_MINUTES` is a single global knob; real deployments tune per scenario, per trigger type, and per clinician role. Engagement metrics per recommendation type feed into the tuning. A pipeline that delivers useful reasoning that is ignored because it competes for attention with alert-fatigue noise is worse than no pipeline at all.

**VPC, encryption, and audit.** This example calls AWS APIs without VPC configuration. Production Lambda runs in private subnets with interface endpoints for Bedrock, Bedrock Guardrails, Comprehend Medical, HealthLake, HealthImaging, Step Functions, KMS, Secrets Manager, CloudWatch Logs, EventBridge, and SageMaker Runtime; gateway endpoints for S3 and DynamoDB; VPC-only OpenSearch and Aurora. All S3 buckets use SSE-KMS with customer-managed keys with distinct keys per modality if retention policies differ. CloudTrail data events are enabled for every Bedrock invocation, every S3 object access, every DynamoDB read/write, every HealthLake and HealthImaging read, every SageMaker endpoint invocation, and every Secrets Manager retrieval. The audit trail is the regulatory evidence.

**PHI minimization in prompts.** The prompts include the patient context and modality interpretations. Bedrock under BAA is HIPAA-eligible so this is compliant, but the minimum-necessary principle argues for pruning: strip direct identifiers (name, MRN, birthdate exact) before prompt construction and substitute back during rendering. This narrows the blast radius for model-invocation logging if enabled for quality monitoring.

**Cost control at scale.** At $0.40-$4.00 per reasoning run, a deployment invoked many times per day per facility can run substantial cost. Build scenario-aware model tiering (smaller model for scope determination and retrieval planning; full model for reasoning). Aggressive caching where safe (e.g., guideline embeddings). Per-clinician daily caps at the API Gateway layer to prevent runaway loops. CloudWatch dashboards by scenario, specialty, and facility. A mis-configured loop producing 20 reasoning runs for one patient in a day is a budget failure, not a quality signal.

**DynamoDB Decimal gotcha.** `_to_decimal_safe` routes floats through `Decimal(str(value))` to avoid the `TypeError: Float types are not supported` DynamoDB raises on Python floats. Every `put_item` and `update_item` with numeric fields uses it. Forgetting is an embarrassing 2 AM debug session.

**JSON parsing resilience.** `_parse_json_response` strips common markdown wrappers. On a hard parse failure in production, the right fallback is to send the raw output back to the model with a "fix the JSON structure; preserve content" instruction. Models self-correct structural errors well; this saves a full regeneration cycle.

**Testing with synthetic data.** There are no tests in this example. Production pipelines have unit tests for FHIR normalization, modality-inventory computation, scope-gate logic, validator rules, JSON parsing, and citation rewriting; integration tests against test OpenSearch and Aurora instances with small synthetic corpora; regression tests against labeled scenarios that hold known-good reasoning outputs stable through prompt and model changes; clinical-validation tests against expert-curated patient scenarios. Never use real PHI in development environments. Synthea-generated FHIR bundles are the standard synthetic source; use the hospital's own de-identified data only under an IRB-approved research use agreement.

**Observability and SLOs.** Reasonable production targets: 95th-percentile end-to-end latency under 30 seconds for focused scenarios and under 90 seconds for broader reasoning; validation pass rate above 90% first attempt; safety-finding coverage at 100% (every deterministic finding appears in every delivered reasoning output); fraction routed to human review below 10%; citation fidelity at 1.0 (every rendered citation exists in the assembled sources); cross-modality contradiction surfacing rate tracked per scenario; clinician-rated usefulness above 60% in pilot scenarios. Publish these as CloudWatch SLOs, alert on drift, and close the loop back to pipeline improvements.

**Model-ID lifecycle.** The Bedrock model IDs in this example will change as newer versions launch. Store model IDs in SSM Parameter Store or AppConfig, not in code. Before flipping production, run the full regression suite (unit tests + clinical validation set) against the new model. Cross-region inference profile IDs (prefixed `us.` or `eu.`) are increasingly required in many regions; plan for it.

**The clinician is the decision-maker.** This phrase appears throughout the recipe and throughout this code. The reasoning layer synthesizes options across modalities, surfaces sources, presents evidence for and against each hypothesis, flags safety findings, acknowledges missing and stale data, and surfaces cross-modality contradictions. The clinician reviews, audits, and decides. Never build a UI that hides reasoning behind a single-click "accept." Never build a prompt that shifts from options language to directives. Never let prompt iteration drift toward the prescriptive. The moment any of these drifts, the product has crossed the line that the CDS exemption depends on, and the regulatory posture changes in a way that's hard to walk back.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 2.10: Multi-Modal Clinical Reasoning](chapter02.10-multi-modal-clinical-reasoning) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard. Many of the cross-cutting patterns here (deterministic safety checks, structured drug data, grounded synthesis, citation discipline) are inherited from [Recipe 2.9: Clinical Decision Support Synthesis](chapter02.09-clinical-decision-support-synthesis); the new work in this recipe is the modality-specific ingestion, the modality inventory and scope gate, the cross-modality reasoning prompt, and the multi-modal-specific validations.*
