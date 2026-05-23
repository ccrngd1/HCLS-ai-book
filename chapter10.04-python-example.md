# Recipe 10.4: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 10.4. It shows one way you could translate the medical-dictation pipeline into working Python using boto3 against Amazon Transcribe Medical (streaming and batch), Amazon Bedrock, Amazon Comprehend Medical, AWS Lambda, AWS Step Functions, Amazon API Gateway, Amazon Cognito, Amazon DynamoDB, Amazon S3, AWS Secrets Manager, Amazon EventBridge, and Amazon CloudWatch. The demo uses a `MockTranscribeMedical` standing in for the streaming clinical ASR session, a `MockBedrock` standing in for the LLM-driven formatting and faithfulness check, a `MockComprehendMedical` standing in for the coded clinical-entity extraction, a `MockEHR` standing in for the SMART on FHIR-launched note-creation API, and small helpers for the session-state table, the dictation-metadata table, the per-clinician configuration table, the audio S3 bucket, the audit S3 bucket, the EventBridge bus, and CloudWatch-style metrics. It is not production-ready. There is no real API Gateway WebSocket carrying audio frames, no real Cognito authorizer, no real SMART on FHIR launch, no real streaming Transcribe Medical session over WebSocket, no real Bedrock invocation, no real Comprehend Medical inference, no real DynamoDB or S3 wiring, no Step Functions state machine, no IAM least-privilege role per Lambda, no KMS customer-managed key configuration, no VPC endpoints, no per-clinician acoustic-model adaptation, no critical-error detection deployed at clinical-quality-officer review, and no production audit-overlay integration with the EHR's native audit log. Think of it as the sketchpad version: useful for understanding the shape of a dictation pipeline that respects the per-clinician-vocabulary discipline, the command-versus-content discipline, the LLM-faithfulness discipline, the structured-field-suggestion-with-explicit-confirmation discipline, the read-edit-sign discipline, and the audit-everything discipline this recipe demands. It is not something you would deploy to clinicians on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the eight core pseudocode steps from the main recipe: open the dictation session and load per-clinician configuration (Step 1), stream audio to Transcribe Medical and capture the verbatim transcript with per-word confidence (Step 2), disambiguate commands from content and apply structural events (Step 3), format the verbatim content into the note template with optional LLM post-processing and faithfulness checking (Step 4), extract structured-field suggestions with cross-checks against the patient's chart (Step 5), render the read-edit-sign view and capture clinician corrections (Step 6), hand off the signed note to the EHR and apply confirmed structured updates (Step 7), and audit, archive, and feed adaptation (Step 8). The synthetic clinicians, patients, schedules, medications, and dictated transcripts in the demo are fictional; the names, MRNs, RxNorm codes, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also configure an Amazon API Gateway WebSocket API for the streaming-audio endpoint plus a REST API for dictation lifecycle and final note submission, an Amazon Cognito user pool federated to the institutional identity provider for clinician authentication, a SMART on FHIR launch context handoff with the host EHR, an Amazon Transcribe Medical custom vocabulary per institution (and optionally per specialty, per clinician), an Amazon Bedrock inference profile pinned to a specific clinical-formatter model and region, the Lambda functions that orchestrate each pipeline stage (the session opener, the ASR result handler, the formatter wrapper, the structured-field extractor wrapper, the EHR handoff, the audit writer, the adaptation-feedback emitter), an AWS Step Functions state machine that durably orchestrates the dictation-to-signed-note workflow with retry semantics, DynamoDB tables that hold session state, dictation metadata across the lifecycle, and per-clinician configuration (custom vocabulary, preferred templates, macros, adaptation parameters), AWS Secrets Manager secrets for the EHR API credentials and the SMART on FHIR backend-services signing keys, an Amazon EventBridge bus for cross-system events (`dictation_started`, `dictation_transcribed`, `dictation_signed`, `dictation_failed`), Amazon S3 buckets for audio recordings (with brief-retention lifecycle) and the long-term audit archive (with Object Lock in compliance mode), and customer-managed KMS keys for every PHI-bearing data class. The demo replaces all of these with small mocks so the focus stays on the per-stage processing logic rather than on the cloud-resource provisioning.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `transcribe:StartMedicalStreamTranscription` and `transcribe:StartMedicalTranscriptionJob` for streaming and batch clinical ASR
- `transcribe:CreateMedicalVocabulary`, `transcribe:UpdateMedicalVocabulary`, `transcribe:GetMedicalVocabulary` for per-institution and per-clinician custom vocabulary management
- `bedrock:InvokeModel` for the formatter and faithfulness models, scoped to the specific foundation-model ARNs and inference profiles in use
- `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM` for coded clinical-entity extraction
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the session-state, dictation-metadata, and per-clinician-config tables
- `s3:GetObject`, `s3:PutObject` on the audio bucket and the audit-archive bucket, scoped to the per-session key prefixes
- `secretsmanager:GetSecretValue` on the EHR-API credentials and SMART on FHIR signing-key secrets pinned to the current rotation version
- `events:PutEvents` on the dictation-events EventBridge bus
- `cloudwatch:PutMetricData` for the operational metrics (per-stage latency, ASR confidence distributions, correction rates, structured-field acceptance rates, time-to-sign distributions, critical-error-detection hits)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the audio bucket, the audit bucket, the DynamoDB tables, and the Secrets Manager secrets
- `states:StartExecution` for the Step Functions state machine that orchestrates the dictation-to-signed-note workflow

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The session-opener Lambda has scoped DynamoDB read for the per-clinician-config table and write for the session-state table only. The ASR-result-handler Lambda has scoped Transcribe Medical session creation rights and write access to the dictation-metadata record only. The formatter Lambda has scoped Bedrock invocation rights pinned to one model and one inference profile. The structured-field-extractor Lambda has scoped Comprehend Medical inference rights only. The EHR-handoff Lambda has scoped Secrets Manager read for the EHR credentials and write access to the dictation-metadata record only. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Audio is PHI from the moment the microphone opens.** The dictation captures the clinician describing the patient's condition. It is, in every regulatory reading, PHI. Encrypt at rest with KMS customer-managed keys, encrypt in transit with TLS, retention bound by an explicit privacy-officer-reviewed policy, BAAs in place for every vendor service that processes the audio. The mocks in this demo handle audio as opaque references; production drives a real S3 PutObject with SSE-KMS and a strict lifecycle policy.
- **The clinician's signature is the gate to the legal record.** Until the clinician signs, the note is a draft. Downstream systems (CDS, billing, public-health reporting) consume signed notes only. The pipeline must prevent unsigned drafts from being treated as authoritative clinical documentation.
- **LLM faithfulness is a structural risk, not a side issue.** When an LLM reformats the verbatim transcript, "may have" can become "had," "intermittent" can become "occasional," and clinical hedging can be silently smoothed away. Run the faithfulness check at runtime (Step 4D in the pseudocode); also maintain an offline evaluation set across specialties that gates production model updates on regression results. The demo's `check_faithfulness` is illustrative; production uses a dedicated check model or a deterministic clinical-claim comparator.
- **Structured-field updates require explicit clinician confirmation.** Comprehend Medical's RxNorm and ICD-10 linkers occasionally misidentify entities, miss negation, or extract dosages incorrectly. Never silently apply a structured update from a dictation. The demo's `handoff_to_ehr` enforces accept-only writes.
- **Critical-error detection is not the same as overall accuracy monitoring.** Word error rate measures aggregate accuracy. Critical-error rate measures clinically-meaningful errors: laterality flips (left vs right), negation flips (no vs not, denies vs endorses), drug-name confusions among look-alike sound-alike pairs, dose-by-order-of-magnitude errors. The detection rules are a clinical-safety artifact owned by the clinical-quality officer. The demo includes a small `detect_critical_errors` to show the pattern.
- **Per-clinician adaptation is the highest-leverage long-term investment.** The user-correction events from the read-edit-sign workflow are the training signal that improves accuracy over time. Capture them, attribute them, and feed them back into per-clinician custom vocabulary (and, where the institution chooses, per-clinician acoustic-model adaptation via SageMaker training jobs). The demo emits the adaptation events to EventBridge so you can see where the consumer would sit.
- **Idempotency at the dictation level.** A dictation submitted twice (network blip, accidental double submission) must not produce two notes in the EHR. The (clinician_id, session_id, transcript_hash) tuple is the idempotency key. The demo collapses this to a transcript-hash check on the metadata table; production uses a conditional DynamoDB write on the dictation-metadata record.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, and numeric metadata field passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses API Gateway, Cognito, multiple Lambdas, the Step Functions orchestration, the EventBridge fan-out, and the CloudWatch metric emission into a single Python file for readability.** In production each pipeline stage is a separate Lambda with its own IAM role, error handling, retries, and DLQs, with Step Functions as the durable orchestrator. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the per-axis confidence thresholds, the command vocabulary, the critical-error rules, the signature requirements, and the formatting prompts are what you would change between environments.

```python
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights. The dictation pipeline operates on
# heavily PHI-bearing data: the audio is PHI, the verbatim
# transcript is PHI, the formatted note is PHI, the structured-
# field suggestions are PHI, and every signature event is a
# clinical-record transaction. Log structural metadata only
# (session_id, ASR confidence band, formatter version, signature
# event), never raw transcripts, never patient demographics,
# never medication or diagnosis values, never the clinician's
# authentication material.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from Transcribe Medical,
# Bedrock, Comprehend Medical, DynamoDB, S3, EventBridge,
# CloudWatch, and Secrets Manager. The dictation latency budget
# is tighter than batch jobs but looser than voice navigation:
# the clinician dictates, then reviews; a few seconds of
# additional formatting time is acceptable. Cap the retries and
# let the caller's failure path surface a clear "system slow"
# message so the clinician can fall back to typing without
# losing the dictated audio.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 4, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm
# containers so each invocation does not pay the connection cost.
REGION = "us-east-1"
dynamodb              = boto3.resource("dynamodb", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
s3_client             = boto3.client("s3", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
transcribe_client     = boto3.client("transcribe", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
bedrock_runtime       = boto3.client("bedrock-runtime", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
comprehend_medical    = boto3.client("comprehendmedical", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
eventbridge_client    = boto3.client("events", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
cloudwatch_client     = boto3.client("cloudwatch", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
secrets_client        = boto3.client("secretsmanager", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
stepfunctions_client  = boto3.client("stepfunctions", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do
# not exist; see run_demo() at the bottom.
SESSION_STATE_TABLE         = "dictation-session-state"
DICTATION_METADATA_TABLE    = "dictation-metadata"
CLINICIAN_CONFIG_TABLE      = "dictation-clinician-config"
AUDIO_BUCKET                = "dictation-audio-bucket"
AUDIT_ARCHIVE_BUCKET        = "dictation-audit-archive"
DICTATION_EVENT_BUS_NAME    = "dictation-events-bus"
CLOUDWATCH_NAMESPACE        = "Dictation"
INSTITUTION_ID              = "academic-medical-center-richmond"

# Bedrock configuration. In production, pin to a specific model
# version and inference profile so a model upgrade does not
# silently change formatter behavior. The model and region
# combination must be in your AWS BAA scope.
BEDROCK_FORMATTER_MODEL_ID    = "anthropic.claude-3-5-sonnet-20240620-v1:0"
BEDROCK_FORMATTER_PROFILE_ARN = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "dictation-formatter-v1")
BEDROCK_FAITHFULNESS_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
BEDROCK_FAITHFULNESS_PROFILE_ARN = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "dictation-faithfulness-v1")

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("SESSION_STATE_TABLE",          SESSION_STATE_TABLE),
    ("DICTATION_METADATA_TABLE",     DICTATION_METADATA_TABLE),
    ("CLINICIAN_CONFIG_TABLE",       CLINICIAN_CONFIG_TABLE),
    ("AUDIO_BUCKET",                 AUDIO_BUCKET),
    ("AUDIT_ARCHIVE_BUCKET",         AUDIT_ARCHIVE_BUCKET),
    ("DICTATION_EVENT_BUS_NAME",     DICTATION_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",         CLOUDWATCH_NAMESPACE),
    ("BEDROCK_FORMATTER_MODEL_ID",   BEDROCK_FORMATTER_MODEL_ID),
    ("BEDROCK_FORMATTER_PROFILE_ARN", BEDROCK_FORMATTER_PROFILE_ARN),
    ("BEDROCK_FAITHFULNESS_MODEL_ID", BEDROCK_FAITHFULNESS_MODEL_ID),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every dictation record carries the versions of the artifacts
# that influenced it: the ASR model version, the formatter
# version, the LLM prompt version, the critical-error rules
# version, the structured-extraction rules version. A future
# audit reconstructs which calibration was active when a
# particular dictation was processed.
ASR_MODEL_VERSION              = "transcribe-medical-2026-q1"
RULE_FORMATTER_VERSION         = "rule-formatter-v3.2"
LLM_FORMATTER_PROMPT_VERSION   = "formatter-prompt-v1.4"
FAITHFULNESS_PROMPT_VERSION    = "faithfulness-prompt-v1.2"
CRITICAL_ERROR_RULES_VERSION   = "critical-errors-v1.1"
STRUCTURED_EXTRACTION_VERSION  = "structured-extraction-v1.0"

# --- ASR Confidence Gates ---
# Average per-word confidence below this floor flags the
# dictation for QA review. The minimum-confidence-word count is
# a secondary gate: even a high-average-confidence transcript
# with several critical words at very low confidence (often
# medication names) deserves an explicit review highlight.
ASR_MIN_AVG_CONFIDENCE              = Decimal("0.85")
ASR_LOW_CONFIDENCE_WORD_THRESHOLD   = Decimal("0.70")
ASR_QA_REVIEW_LOW_CONF_WORD_LIMIT   = 5

# --- LLM Faithfulness Threshold ---
# The faithfulness model returns a score in [0, 1]; below this
# threshold the rule-based draft is preferred and the LLM draft
# is offered as a "suggested alternative" for clinician
# comparison rather than substituted silently.
FAITHFULNESS_PASS_THRESHOLD         = Decimal("0.92")

# --- Command Vocabulary ---
# Phrases the dictation system treats as commands rather than
# content. The boundary between commands and content is a
# clinical-safety design decision; the institution's command
# vocabulary is reviewed by clinical operations and versioned.
# COMMAND_PREFIX is the explicit prefix mode; when present at
# the start of a segment, the rest of the segment is treated
# as a command regardless of phrasing.
COMMAND_PREFIX = "computer"
COMMAND_VOCABULARY = {
    "new paragraph":       {"action": "structural",
                             "name":   "new_paragraph"},
    "next field":          {"action": "navigation",
                             "name":   "next_field"},
    "previous field":      {"action": "navigation",
                             "name":   "previous_field"},
    "go to assessment":    {"action": "navigation",
                             "name":   "go_to_section",
                             "section": "assessment"},
    "go to plan":          {"action": "navigation",
                             "name":   "go_to_section",
                             "section": "plan"},
    "go to history":       {"action": "navigation",
                             "name":   "go_to_section",
                             "section": "history_of_present_illness"},
    "delete that sentence": {"action": "edit",
                             "name":   "delete_last_sentence"},
    "scratch that":        {"action": "edit",
                             "name":   "delete_last_sentence"},
}

# Pause threshold for command-versus-content disambiguation.
# Segments separated by a pause longer than this are candidates
# for command interpretation; embedded phrases without a
# preceding pause are treated as content.
COMMAND_PAUSE_THRESHOLD_SECONDS = 0.4

# --- Critical Error Detection Rules ---
# Word substitutions that have outsized clinical consequence.
# Owned by the clinical-quality officer. Versioned. Surfaced in
# the review pane with explicit clinician confirmation required.
# This list is illustrative, not exhaustive; a real institution
# will have a much larger and per-specialty-tuned rule set.
CRITICAL_ERROR_PAIRS = {
    # Laterality flips
    ("left", "right"),
    ("right", "left"),
    # Negation flips (the safer one to flag is the one whose
    # presence in the formatted note differs from the verbatim)
    ("no", "not"),
    ("not", "no"),
    ("denies", "endorses"),
    ("endorses", "denies"),
    ("with", "without"),
    ("without", "with"),
    # Look-alike, sound-alike drug pairs
    ("morphine", "naloxone"),
    ("hydromorphone", "morphine"),
    ("metoprolol", "metoclopramide"),
    ("hyzaar", "cozaar"),
    # Vital-sign-direction flips
    ("hypertension", "hypotension"),
    ("hypotension", "hypertension"),
    ("hyperthermia", "hypothermia"),
    ("hypoglycemia", "hyperglycemia"),
    # Symptom-pair confusions
    ("hemoptysis", "hematemesis"),
    ("hematemesis", "hemoptysis"),
    # Direction confusions
    ("increase", "decrease"),
    ("decrease", "increase"),
    ("improving", "worsening"),
    ("worsening", "improving"),
}

# --- Default Note Templates ---
# In production these come from a versioned templates table
# managed by clinical operations per specialty. The demo carries
# a minimal primary-care template inline.
DEFAULT_TEMPLATES = {
    "primary-care-followup-v2": {
        "id": "primary-care-followup-v2",
        "specialty": "PRIMARYCARE",
        "note_type": "progress-note",
        "sections": [
            {"key": "chief_complaint",
             "header": "Chief Complaint",
             "required": True},
            {"key": "history_of_present_illness",
             "header": "History of Present Illness",
             "required": True},
            {"key": "past_medical_history",
             "header": "Past Medical History",
             "required": False},
            {"key": "medications",
             "header": "Medications",
             "required": False},
            {"key": "physical_exam",
             "header": "Physical Exam",
             "required": False},
            {"key": "assessment",
             "header": "Assessment",
             "required": True},
            {"key": "plan",
             "header": "Plan",
             "required": True},
        ],
    },
}

# --- Idempotency window ---
DUPLICATE_DICTATION_WINDOW_SECONDS = 30

# --- Helper: float -> Decimal ---
# DynamoDB rejects native Python float. Every numeric value on
# its way into DynamoDB has to be a Decimal. This helper handles
# nested dicts and lists.
def _to_decimal(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_decimal(v) for v in value]
    return value


def _hash_transcript(transcript):
    """Stable transcript hash for idempotency and audit linkage."""
    if not transcript:
        return None
    return hashlib.sha256(
        transcript.lower().strip().encode("utf-8")).hexdigest()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()
```

---

## Mock Resources for the Demo

These mocks stand in for the production AWS resources and back-office systems. They are deliberately simple and are not how you would build the real thing. Their purpose is to keep the focus on the dictation pipeline logic.

```python
class MockTranscribeMedical:
    """
    Stands in for Amazon Transcribe Medical's streaming API. In
    production you open a streaming session with the specialty,
    type=DICTATION, and a custom-vocabulary name; you push audio
    frames as they arrive from the client; you receive partial
    and final transcripts progressively with per-word
    confidence. The demo synthesizes the final transcript from a
    hardcoded mapping (session_id -> transcript fixture) so we
    can exercise the rest of the pipeline without real audio.
    """
    def __init__(self, transcript_fixtures):
        self._fixtures   = transcript_fixtures
        self._biasing    = {}
        self._specialty  = {}

    def configure_session(self, session_id, specialty,
                           vocabulary_name, biasing_terms=None):
        # In production these are arguments to
        # start_medical_stream_transcription. The mock records
        # them so the demo can show what was configured.
        self._specialty[session_id] = specialty
        self._biasing[session_id]   = list(biasing_terms or [])
        return {"session_id": session_id,
                "specialty":  specialty,
                "vocabulary_name": vocabulary_name}

    def transcribe_session(self, session_id):
        """
        Simulate a complete streaming session: the demo skips
        the audio-pumping and returns the final result with
        per-word confidence scores and timing.
        """
        fixture = self._fixtures.get(session_id, {
            "verbatim":       "no fixture available for this session",
            "items":          [],
            "duration_seconds": 0.0,
        })
        return {
            "verbatim":         fixture["verbatim"],
            "items":            fixture.get("items", []),
            "duration_seconds": fixture.get("duration_seconds", 0.0),
            "specialty":        self._specialty.get(session_id),
            "biasing_applied":  self._biasing.get(session_id, []),
        }


class MockBedrock:
    """
    Stands in for Amazon Bedrock's InvokeModel API. Two
    invocation patterns: the formatter (turns verbatim transcript
    into a section-structured formatted note) and the
    faithfulness check (compares verbatim and formatted to score
    semantic preservation).
    """
    def __init__(self, formatter_responses, faithfulness_responses):
        self._formatter_responses     = formatter_responses
        self._faithfulness_responses  = faithfulness_responses

    def invoke_formatter(self, model_id, prompt_payload):
        # In production this is bedrock_runtime.invoke_model
        # with modelId pinned to the inference profile and a
        # prompt that returns strict JSON.
        verbatim_key = self._fixture_key(prompt_payload.get("verbatim"))
        if verbatim_key in self._formatter_responses:
            return {"body": json.dumps(
                self._formatter_responses[verbatim_key])}
        return {"body": json.dumps({
            "formatted_note": prompt_payload.get("rule_based_draft", ""),
            "structural_changes": [],
            "rationale": "No fixture; returning rule-based draft as-is.",
        })}

    def invoke_faithfulness(self, model_id, prompt_payload):
        verbatim_key = self._fixture_key(prompt_payload.get("verbatim"))
        if verbatim_key in self._faithfulness_responses:
            return {"body": json.dumps(
                self._faithfulness_responses[verbatim_key])}
        return {"body": json.dumps({
            "faithfulness_score": 0.99,
            "warnings":           [],
            "rationale":          "No semantic drift detected.",
        })}

    @staticmethod
    def _fixture_key(verbatim):
        return (verbatim or "").lower().split(".")[0][:60]


class MockComprehendMedical:
    """
    Stands in for Amazon Comprehend Medical's DetectEntitiesV2,
    InferRxNorm, and InferICD10CM APIs. The demo returns
    fixture-driven entity lists keyed by transcript substring.
    """
    def __init__(self, entity_fixtures):
        self._fixtures = entity_fixtures

    def detect_entities(self, text):
        # Production: comprehend_medical.detect_entities_v2(Text=text)
        for fixture_key, fixture_response in self._fixtures.items():
            if fixture_key in (text or "").lower():
                return dict(fixture_response)
        return {"Entities": []}


class MockEHR:
    """
    Stands in for the EHR's note-creation, structured-update, and
    chart-context APIs. In production this is a SMART on FHIR-
    launched app calling FHIR endpoints (DocumentReference,
    Composition, MedicationStatement, Condition, AllergyIntolerance,
    Provenance) plus vendor-specific extensions for note signing
    and structured-field cross-checks.
    """
    def __init__(self):
        self._patients = {
            "pt-44219-3c": {
                "patient_id":  "pt-44219-3c",
                "first_name":  "Margaret",
                "last_name":   "Chen",
                "dob":         "1958-03-14",
                "mrn":         "MRN-2010001",
            },
            "pt-77310-4f": {
                "patient_id":  "pt-77310-4f",
                "first_name":  "James",
                "last_name":   "Patel",
                "dob":         "1972-09-22",
                "mrn":         "MRN-2010102",
            },
        }
        # Patient-specific "current chart" state. Used by the
        # structured-field extractor to cross-check.
        self._chart_state = {
            "pt-44219-3c": {
                "medications": [
                    {"rxnorm_code": "29046",
                     "display":     "Lisinopril 10 MG Oral Tablet"},
                ],
                "conditions":  [
                    {"icd10_code": "I10",
                     "display":     "Essential (primary) hypertension"},
                ],
                "allergies":   [],
            },
            "pt-77310-4f": {
                "medications": [],
                "conditions":  [],
                "allergies":   [],
            },
        }
        self._created_notes        = {}
        self._structured_writes    = []
        self._note_counter         = 0

    def get_chart_state(self, patient_id):
        return dict(self._chart_state.get(patient_id, {
            "medications": [], "conditions": [], "allergies": []}))

    def create_note(self, patient_id, encounter_id, author_id,
                     note_type, content, signature):
        self._note_counter += 1
        note_id = f"doc-{self._note_counter:06d}"
        self._created_notes[note_id] = {
            "note_id":      note_id,
            "patient_id":   patient_id,
            "encounter_id": encounter_id,
            "author_id":    author_id,
            "note_type":    note_type,
            "content":      content,
            "signature":    signature,
            "created_at":   _now_iso(),
        }
        return {"note_id": note_id, "status": "created"}

    def add_medication(self, patient_id, medication_code, dosage,
                        frequency, source_note_id):
        record = {"type": "medication",
                  "patient_id": patient_id,
                  "rxnorm_code": medication_code,
                  "dosage":     dosage,
                  "frequency":  frequency,
                  "source_note_id": source_note_id,
                  "applied_at": _now_iso()}
        self._structured_writes.append(record)
        # Update the chart state so subsequent dictations see it.
        self._chart_state.setdefault(
            patient_id, {"medications": [], "conditions": [],
                          "allergies": []})
        self._chart_state[patient_id]["medications"].append({
            "rxnorm_code": medication_code,
            "display":     f"medication {medication_code}",
        })
        return {"status": "applied", "rxnorm_code": medication_code}

    def add_condition(self, patient_id, condition_code,
                       source_note_id):
        record = {"type": "condition",
                  "patient_id": patient_id,
                  "icd10_code": condition_code,
                  "source_note_id": source_note_id,
                  "applied_at": _now_iso()}
        self._structured_writes.append(record)
        self._chart_state.setdefault(
            patient_id, {"medications": [], "conditions": [],
                          "allergies": []})
        self._chart_state[patient_id]["conditions"].append({
            "icd10_code": condition_code,
            "display":    f"condition {condition_code}",
        })
        return {"status": "applied", "icd10_code": condition_code}


class MockClient:
    """
    Stands in for the dictation client (browser EHR plugin,
    desktop client, or mobile app). Captures partial transcripts,
    review-pane events, suggestion-decision events, and the
    final signature event so the demo can show what the clinician
    would see and produce.
    """
    def __init__(self):
        self.events = []
        self._review_decisions = []
        self._signature        = None

    def emit_partial(self, session_id, text, is_final):
        self.events.append({
            "type":       "partial_transcript",
            "session_id": session_id,
            "text":       text,
            "is_final":   is_final,
            "at":         _now_iso(),
        })

    def render_review(self, payload):
        self.events.append({
            "type":          "review_view_rendered",
            "session_id":    payload.get("session_id"),
            "summary":       (
                f"{len(payload.get('confidence_overlay', []))} words, "
                f"{len(payload.get('suggestions', []))} suggestions, "
                f"{len(payload.get('cross_check_warnings', []))} warnings, "
                f"{len(payload.get('critical_error_alerts', []))} "
                f"critical-error alerts"),
            "at":            _now_iso(),
        })

    def queue_review_decisions(self, decisions):
        """Demo control: pre-decide which suggestions get accepted."""
        self._review_decisions = list(decisions)

    def queue_signature(self, signature):
        self._signature = dict(signature)

    def collect_review_events(self):
        decisions = list(self._review_decisions)
        self._review_decisions = []
        return decisions

    def get_signature(self):
        signature = dict(self._signature or {
            "type":      "electronic",
            "method":    "password",
            "timestamp": _now_iso(),
        })
        self._signature = None
        return signature


class MockSessionState:
    def __init__(self):
        self._items = {}

    def get(self, session_id):
        return dict(self._items.get(session_id, {}))

    def put(self, session_id, item):
        self._items[session_id] = dict(item)

    def update(self, session_id, updates):
        existing = self._items.setdefault(
            session_id, {"session_id": session_id})
        existing.update(updates)


class MockDictationMetadata:
    """
    Stands in for the DynamoDB dictation-metadata table. In
    production the table is partitioned by clinician_id with a
    sort key on session_id; Streams emit change events to the
    audit and analytics consumers.
    """
    def __init__(self):
        self._items = {}

    def put(self, session_id, item):
        self._items[session_id] = dict(item)

    def get(self, session_id):
        return dict(self._items.get(session_id, {}))

    def update(self, session_id, updates):
        existing = self._items.setdefault(
            session_id, {"session_id": session_id})
        existing.update(updates)

    def find_recent_for_idempotency(self, clinician_id,
                                     transcript_hash, window_seconds):
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(seconds=window_seconds))
        for record in self._items.values():
            if (record.get("clinician_id") == clinician_id
                    and (record.get("verbatim_transcript_hash")
                         == transcript_hash)):
                ts = record.get("transcribed_at")
                if ts and ts >= cutoff.isoformat():
                    return record
        return None


class MockClinicianConfig:
    """
    Stands in for the per-clinician configuration table. Holds
    custom vocabulary additions, preferred templates, macro
    library, and adaptation parameters.
    """
    def __init__(self, configs):
        self._configs = dict(configs)

    def get(self, clinician_id):
        return dict(self._configs.get(clinician_id, {
            "clinician_id":      clinician_id,
            "specialty":         "PRIMARYCARE",
            "custom_terms":      [],
            "specialty_terms":   [],
            "preferred_template": "primary-care-followup-v2",
            "macros":            {},
        }))


class MockS3:
    """
    Stands in for S3 audio storage and audit archive. Holds
    objects in memory keyed by (bucket, key). Production uses
    customer-managed KMS keys for encryption and lifecycle
    policies for retention.
    """
    def __init__(self):
        self._objects = {}

    def put_object(self, bucket, key, body, metadata=None):
        self._objects[(bucket, key)] = {
            "body":     body,
            "metadata": dict(metadata or {}),
            "stored_at": _now_iso(),
        }
        return {"bucket": bucket, "key": key,
                "uri":    f"s3://{bucket}/{key}"}

    def list(self, bucket=None):
        return [{"bucket": b, "key": k,
                 "metadata": v["metadata"]}
                for (b, k), v in self._objects.items()
                if bucket is None or b == bucket]


class MockEventBus:
    """
    Stands in for Amazon EventBridge. Lifecycle events flow here
    for cross-system fan-out: dictation_started,
    dictation_transcribed, dictation_signed, dictation_failed.
    """
    def __init__(self):
        self.events = []

    def put_events(self, entries):
        for entry in entries:
            self.events.append(dict(entry))


class MockCloudWatch:
    """
    Stands in for CloudWatch metric emission. In production the
    metrics flow into dashboards and alarms.
    """
    def __init__(self):
        self.metrics = []

    def put_metric(self, namespace, metric_name, value,
                    unit="Count", dimensions=None):
        self.metrics.append({
            "namespace":   namespace,
            "metric_name": metric_name,
            "value":       value,
            "unit":        unit,
            "dimensions":  dimensions or {},
            "timestamp":   _now_iso(),
        })


# Module-level singletons for the demo. In production each of
# these is its own AWS resource accessed via boto3.
session_state     = MockSessionState()
dictation_meta    = MockDictationMetadata()
ehr               = MockEHR()
client            = MockClient()
event_bus         = MockEventBus()
cloudwatch        = MockCloudWatch()
s3_store          = MockS3()
# transcribe_med, bedrock_mock, comprehend_mock, and
# clinician_config are wired up in run_demo() with fixture data
# tailored to each scenario.
transcribe_med    = None
bedrock_mock      = None
comprehend_mock   = None
clinician_config  = None


def audit_log(event):
    """
    Sanitized audit print so you can see the sequence of
    decisions without leaking the underlying values. Production
    routes events to CloudWatch Logs Insights with structured
    JSON; ship to a SIEM if available.
    """
    safe_event = {k: v for k, v in event.items()
                  if k not in {"verbatim_transcript",
                                "formatted_text",
                                "patient_demographics",
                                "structured_decisions_raw"}}
    if "verbatim_transcript" in event:
        safe_event["verbatim_transcript_length"] = len(
            event["verbatim_transcript"] or "")
    if "formatted_text" in event:
        safe_event["formatted_text_length"] = len(
            event["formatted_text"] or "")
    logger.info("AUDIT %s", json.dumps(safe_event, default=str))
```

---

## Step 1: Open the Dictation Session and Load Per-Clinician Configuration

*The pseudocode calls this `ON dictation_start_request(...)`. The clinician begins a dictation session from inside the EHR (or a desktop client). The system authenticates the clinician, loads the per-clinician custom vocabulary and preferred template, builds the session-specific biasing list (institutional formulary plus specialty-specific terms plus per-clinician additions plus patient-specific medications and providers), opens a streaming Transcribe Medical session with the right specialty, and persists the session state. Skip the per-clinician vocabulary load and the ASR runs without institutional biasing, which immediately drops accuracy on the medications the clinician most commonly prescribes.*

```python
def open_dictation_session(clinician_id, smart_on_fhir_context,
                             note_context, activation_at=None):
    """
    Open a dictation session in response to a clinician
    initiating dictation from the EHR.

    Args:
        clinician_id: Authenticated clinician identity from
            Cognito or the institutional IdP.
        smart_on_fhir_context: Dict with launch_id, access_token,
            issued_at, patient_id, encounter_id.
        note_context: Dict with note_type and (optional) target
            template override.
        activation_at: Optional ISO timestamp of activation.
            Defaults to now().

    Returns:
        Session-context dict consumed by downstream stages.
    """
    activation_at = activation_at or _now_iso()

    # Step 1A: validate the SMART on FHIR launch context. Stale
    # tokens are a security failure mode; reject with a re-launch
    # prompt rather than passing through.
    issued_at = smart_on_fhir_context.get("issued_at")
    if issued_at:
        issued_dt = datetime.fromisoformat(
            issued_at.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - issued_dt
        if age > timedelta(hours=8):
            audit_log({
                "event_type":   "DICTATION_REJECTED_STALE_LAUNCH",
                "clinician_id": clinician_id,
                "timestamp":    _now_iso(),
            })
            raise RuntimeError(
                "SMART on FHIR launch context is stale; "
                "re-launch required.")

    # Step 1B: load per-clinician configuration. Specialty,
    # preferred template, custom vocabulary additions, macro
    # library, adaptation parameters.
    config = clinician_config.get(clinician_id)
    specialty = config.get("specialty", "PRIMARYCARE")

    # Step 1C: build the session-specific custom vocabulary.
    # Combine the institutional formulary, the specialty-specific
    # term list, the per-clinician additions, and the patient-
    # specific terms (current medications, recent procedures)
    # where the patient context is known. In production the
    # patient terms come from a FHIR fetch against MedicationRequest
    # and Procedure for the patient.
    institutional_terms = ["lisinopril", "atorvastatin", "metformin",
                            "amlodipine", "metoprolol"]
    patient_terms = []
    if smart_on_fhir_context.get("patient_id"):
        chart = ehr.get_chart_state(
            smart_on_fhir_context["patient_id"])
        for med in chart.get("medications", []):
            patient_terms.append(med.get("display", "").split()[0])

    biasing_terms = list(set(
        institutional_terms
        + config.get("specialty_terms", [])
        + config.get("custom_terms", [])
        + [t for t in patient_terms if t]))

    # Step 1D: select the note template. The template determines
    # the section structure and the structured-field hooks. In
    # production the template comes from a versioned templates
    # table managed by clinical operations per specialty.
    template_id = (note_context.get("template_id")
                    or config.get("preferred_template")
                    or "primary-care-followup-v2")
    template = DEFAULT_TEMPLATES.get(template_id)
    if not template:
        raise RuntimeError(
            f"Unknown template {template_id}; check template registry")

    # Step 1E: configure the streaming Transcribe Medical session.
    # In production this is:
    #   transcribe_client.start_medical_stream_transcription(
    #       LanguageCode="en-US",
    #       MediaSampleRateHertz=16000,
    #       Specialty=specialty,
    #       Type="DICTATION",
    #       VocabularyName=vocabulary_name,
    #       ShowSpeakerLabels=False,
    #       EnablePartialResultsStabilization=True,
    #       PartialResultsStability="high",
    #   )
    # The mock records the configuration so we can assert it
    # later.
    session_id = "dict-" + uuid.uuid4().hex[:16]
    vocabulary_name = (
        f"clinician-{clinician_id.replace('user-', '')}-vocab")
    transcribe_med.configure_session(
        session_id=session_id,
        specialty=specialty,
        vocabulary_name=vocabulary_name,
        biasing_terms=biasing_terms)

    # Step 1F: persist the session state. The session_id is the
    # idempotency anchor for everything that follows.
    session_record = {
        "session_id":          session_id,
        "clinician_id":        clinician_id,
        "patient_id":
            smart_on_fhir_context.get("patient_id"),
        "encounter_id":
            smart_on_fhir_context.get("encounter_id"),
        "launch_id":
            smart_on_fhir_context.get("launch_id"),
        "specialty":           specialty,
        "template_id":         template["id"],
        "vocabulary_name":     vocabulary_name,
        "biasing_terms":       biasing_terms,
        "activation_at":       activation_at,
        "status":              "active",
    }
    session_state.put(session_id, _to_decimal(session_record))

    # Initial dictation-metadata record. Each subsequent stage
    # updates this row.
    dictation_meta.put(session_id, _to_decimal({
        "session_id":     session_id,
        "clinician_id":   clinician_id,
        "patient_id":
            smart_on_fhir_context.get("patient_id"),
        "encounter_id":
            smart_on_fhir_context.get("encounter_id"),
        "specialty":      specialty,
        "template_id":    template["id"],
        "started_at":     activation_at,
        "asr_model_version": ASR_MODEL_VERSION,
        "rule_formatter_version": RULE_FORMATTER_VERSION,
        "llm_formatter_prompt_version": LLM_FORMATTER_PROMPT_VERSION,
        "faithfulness_prompt_version": FAITHFULNESS_PROMPT_VERSION,
        "critical_error_rules_version": CRITICAL_ERROR_RULES_VERSION,
        "structured_extraction_version": STRUCTURED_EXTRACTION_VERSION,
        "status":         "session_open",
    }))

    event_bus.put_events([{
        "Source":       "dictation",
        "DetailType":   "dictation_started",
        "EventBusName": DICTATION_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":   session_id,
            "clinician_id": clinician_id,
            "specialty":    specialty,
            "timestamp":    activation_at,
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "DictationSessionsStarted", 1, "Count",
        dimensions={"specialty": specialty,
                    "institution_id": INSTITUTION_ID})

    audit_log({
        "event_type":   "DICTATION_SESSION_OPENED",
        "session_id":   session_id,
        "clinician_id": clinician_id,
        "specialty":    specialty,
        "template_id":  template["id"],
        "biasing_term_count": len(biasing_terms),
        "timestamp":    activation_at,
    })

    return {
        "session_id":      session_id,
        "clinician_id":    clinician_id,
        "patient_id":
            smart_on_fhir_context.get("patient_id"),
        "encounter_id":
            smart_on_fhir_context.get("encounter_id"),
        "access_token":
            smart_on_fhir_context.get("access_token"),
        "specialty":       specialty,
        "template":        template,
        "vocabulary_name": vocabulary_name,
        "biasing_terms":   biasing_terms,
        "activation_at":   activation_at,
    }
```

---

## Step 2: Stream Audio to ASR and Capture the Verbatim Transcript

*The pseudocode calls this `stream_audio_to_asr(...)`. Audio frames stream from the device through API Gateway's WebSocket to the Transcribe Medical streaming session. Partial transcripts emit progressively (so the client can show the words appearing as the clinician dictates) and the final transcript emits at end-of-dictation. The pipeline collects per-word confidence scores for downstream review-pane highlighting and records the audio reference in S3 with KMS-encrypted at-rest storage. Skip the per-word confidence and the read-back view loses its single most useful affordance for catching ASR errors.*

```python
def stream_audio_and_transcribe(session_context):
    """
    Run the streaming ASR for the dictation and produce a
    finalized verbatim transcript with per-word timing and
    confidence.

    Args:
        session_context: The dict returned by
            open_dictation_session.

    Returns:
        Dict with verbatim transcript, per-word details, average
        confidence, and the audio S3 URI for downstream stages.
    """
    session_id = session_context["session_id"]

    # Step 2A: open the streaming Transcribe Medical session.
    # Production calls transcribe_client.start_medical_stream_transcription(...)
    # and pumps audio frames through the resulting stream. The
    # mock returns the final transcript directly.
    asr_started_at = _now_iso()
    asr_result = transcribe_med.transcribe_session(session_id)
    verbatim = asr_result.get("verbatim", "")
    items    = asr_result.get("items", [])

    # Step 2B: emit a (simulated) partial transcript so the
    # client UI can render words as they finalize. In production
    # this happens many times during the streaming session; the
    # mock emits one finalization event for illustration.
    if verbatim:
        client.emit_partial(
            session_id=session_id,
            text=verbatim.split(".")[0],
            is_final=True)

    # Step 2C: collect per-word confidence and timing. Transcribe
    # Medical streaming returns word-level alternatives with
    # confidence scores and start/end timing; the pipeline
    # aggregates these for downstream review-pane highlighting
    # and structural-event detection.
    word_level_results = []
    for item in items:
        alts = item.get("alternatives", [])
        if not alts:
            continue
        try:
            confidence = float(alts[0].get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        word_level_results.append({
            "word":       alts[0].get("content", ""),
            "start_time": float(item.get("start_time", 0.0)),
            "end_time":   float(item.get("end_time", 0.0)),
            "confidence": confidence,
        })

    if word_level_results:
        avg_confidence = Decimal(str(
            sum(w["confidence"] for w in word_level_results)
            / len(word_level_results)))
        low_conf_count = sum(
            1 for w in word_level_results
            if Decimal(str(w["confidence"]))
                < ASR_LOW_CONFIDENCE_WORD_THRESHOLD)
    else:
        avg_confidence = Decimal("0.0")
        low_conf_count = 0

    # Step 2D: persist the audio recording. Production uses
    # customer-managed KMS keys, brief retention via S3 lifecycle,
    # and the privacy-officer-reviewed retention policy. The mock
    # stores an opaque body reference.
    audio_object = s3_store.put_object(
        bucket=AUDIO_BUCKET,
        key=f"{datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
            f"/{session_id}.flac",
        body=b"<audio bytes here>",
        metadata={"session_id": session_id,
                  "clinician_id": session_context["clinician_id"],
                  "specialty":   session_context["specialty"]})

    # Step 2E: persist the verbatim transcript reference. The
    # transcript itself is also PHI; encrypted at rest, retention
    # bound to the audit-archive policy.
    verbatim_object = s3_store.put_object(
        bucket=AUDIT_ARCHIVE_BUCKET,
        key=f"transcripts/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
            f"/{session_id}.txt",
        body=verbatim.encode("utf-8"),
        metadata={"session_id": session_id})

    transcript_hash = _hash_transcript(verbatim)

    # Step 2F: idempotency check at the ASR level. If the same
    # clinician submitted the same transcript within the
    # duplicate window, treat as a re-fire and short-circuit.
    duplicate = dictation_meta.find_recent_for_idempotency(
        clinician_id=session_context["clinician_id"],
        transcript_hash=transcript_hash,
        window_seconds=DUPLICATE_DICTATION_WINDOW_SECONDS)
    if duplicate and duplicate.get("session_id") != session_id:
        audit_log({
            "event_type":     "DUPLICATE_DICTATION_SUPPRESSED",
            "session_id":     session_id,
            "duplicate_of":   duplicate.get("session_id"),
            "timestamp":      _now_iso(),
        })
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "DuplicateDictationSuppressed",
            1, "Count",
            dimensions={"institution_id": INSTITUTION_ID})
        return {
            "proceed":      False,
            "session_id":   session_id,
            "disposition": "duplicate_suppressed",
            "duplicate_of": duplicate.get("session_id"),
        }

    # Step 2G: update the dictation metadata with the verbatim
    # transcript references, confidence aggregates, and audio
    # references.
    dictation_meta.update(session_id, _to_decimal({
        "verbatim_transcript_hash": transcript_hash,
        "verbatim_transcript_length_chars": len(verbatim),
        "verbatim_avg_confidence": avg_confidence,
        "verbatim_low_conf_word_count": low_conf_count,
        "audio_s3_uri":     audio_object["uri"],
        "verbatim_archive_ref": verbatim_object["uri"],
        "duration_seconds": Decimal(str(
            asr_result.get("duration_seconds", 0.0))),
        "transcribed_at":   _now_iso(),
        "status":           "transcribed",
    }))

    event_bus.put_events([{
        "Source":       "dictation",
        "DetailType":   "dictation_transcribed",
        "EventBusName": DICTATION_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":      session_id,
            "clinician_id":    session_context["clinician_id"],
            "avg_confidence":  float(avg_confidence),
            "duration_seconds":
                asr_result.get("duration_seconds", 0.0),
            "word_count":      len(word_level_results),
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ASRAvgConfidence",
        float(avg_confidence) * 100, "Percent",
        dimensions={"specialty": session_context["specialty"]})
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ASRLowConfidenceWords",
        low_conf_count, "Count",
        dimensions={"specialty": session_context["specialty"]})

    audit_log({
        "event_type":     "ASR_FINALIZED",
        "session_id":     session_id,
        "asr_started_at": asr_started_at,
        "completed_at":   _now_iso(),
        "avg_confidence": float(avg_confidence),
        "low_conf_count": low_conf_count,
        "word_count":     len(word_level_results),
    })

    return {
        "proceed":            True,
        "session_id":         session_id,
        "verbatim":           verbatim,
        "verbatim_hash":      transcript_hash,
        "word_level_results": word_level_results,
        "avg_confidence":     avg_confidence,
        "low_conf_count":     low_conf_count,
        "audio_s3_uri":       audio_object["uri"],
        "verbatim_archive_ref": verbatim_object["uri"],
    }
```

---

## Step 3: Disambiguate Commands from Content

*The pseudocode calls this `disambiguate_commands(...)`. Walk through the verbatim transcript and the timing-aligned word stream. Identify command phrases (the explicit prefix `computer ...`, or configured command vocabulary preceded by a meaningful pause) and route them to the structural-event log; everything else is content. The boundary between commands and content is one of the highest-stakes design decisions in the recipe; ambiguous decisions produce notes with command artifacts in them or commands silently ignored. Skip this stage and command phrases either appear as literal text in the formatted note or get silently dropped, depending on which way the heuristic falls.*

```python
def _segment_by_pauses(word_level_results, pause_threshold_seconds):
    """
    Split the word stream into segments separated by significant
    pauses. Pauses are inferred from gaps between consecutive
    word end_time and start_time. The pause threshold is the
    primary acoustic cue the disambiguation layer uses.
    """
    if not word_level_results:
        return []
    segments = []
    current = [word_level_results[0]]
    for word in word_level_results[1:]:
        prev_end = current[-1]["end_time"]
        gap = word["start_time"] - prev_end
        if gap >= pause_threshold_seconds:
            segments.append(current)
            current = [word]
        else:
            current.append(word)
    if current:
        segments.append(current)
    return segments


def _segment_text(segment):
    return " ".join(w["word"] for w in segment).strip().lower()


def disambiguate_commands(asr_result, session_context):
    """
    Walk the verbatim transcript and route command phrases to
    the structural-event log; everything else is content.

    Args:
        asr_result: Dict from stream_audio_and_transcribe.
        session_context: Dict from open_dictation_session.

    Returns:
        Dict with content_segments and structural_events. The
        structural events include explicit-prefix commands and
        pause-isolated phrases that match the configured
        command vocabulary.
    """
    session_id = session_context["session_id"]
    word_level_results = asr_result["word_level_results"]

    segments = _segment_by_pauses(
        word_level_results, COMMAND_PAUSE_THRESHOLD_SECONDS)

    content_segments  = []
    structural_events = []

    for segment in segments:
        segment_text = _segment_text(segment)
        if not segment_text:
            continue

        # Step 3A: explicit command prefix match. The safest
        # disambiguation: anything starting with "computer, ..."
        # is a command regardless of phrasing.
        if segment_text.startswith(COMMAND_PREFIX + " "):
            command_text = segment_text[len(COMMAND_PREFIX):].strip(", ")
            command = COMMAND_VOCABULARY.get(command_text, {
                "action": "unknown",
                "name":   command_text,
            })
            structural_events.append({
                "type":          "command",
                "source":        "explicit_prefix",
                "command":       command,
                "raw_text":      segment_text,
                "segment_start": segment[0]["start_time"],
            })
            continue

        # Step 3B: implicit command match. Only when the entire
        # segment matches a configured command phrase. Embedded
        # command-like phrases inside longer dictation segments
        # are treated as content (the conservative bias).
        if segment_text in COMMAND_VOCABULARY:
            command = COMMAND_VOCABULARY[segment_text]
            structural_events.append({
                "type":          "command",
                "source":        "implicit_match",
                "command":       command,
                "raw_text":      segment_text,
                "segment_start": segment[0]["start_time"],
            })
            continue

        # Step 3C: everything else is content.
        content_segments.append({
            "text":          segment_text,
            "words":         segment,
            "segment_start": segment[0]["start_time"],
        })

    audit_log({
        "event_type":         "COMMANDS_DISAMBIGUATED",
        "session_id":         session_id,
        "content_segments":   len(content_segments),
        "structural_events":  len(structural_events),
        "explicit_prefix_count": sum(
            1 for e in structural_events
            if e["source"] == "explicit_prefix"),
        "implicit_match_count": sum(
            1 for e in structural_events
            if e["source"] == "implicit_match"),
    })

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "StructuralEventsPerDictation",
        len(structural_events), "Count",
        dimensions={"specialty": session_context["specialty"]})

    return {
        "session_id":         session_id,
        "content_segments":   content_segments,
        "structural_events":  structural_events,
    }
```

---

## Step 4: Format and Structure into the Note Template

*The pseudocode calls this `format_and_structure(...)`. Apply rule-based formatting (punctuation inference, capitalization, number-and-date canonicalization, section-header detection), then optionally invoke a Bedrock LLM to refine the formatting and reorganize content into the right template sections. Run a faithfulness check between the verbatim transcript and the LLM-formatted note: the formatted note must contain the same clinical claims as the verbatim, with no paraphrasing that changes meaning. When faithfulness fails, fall back to the rule-based draft and surface the LLM version as a "suggested alternative" rather than substitute it silently. Skip the faithfulness check and the formatted note may paraphrase clinical content in ways that change meaning, which is the worst class of failure for this recipe.*

```python
NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000,
}


def _words_to_number(words):
    """
    Convert a sequence of number words to an integer. Handles
    the common spoken patterns ("fifty four", "three hundred and
    fifteen"). Returns None if the words don't parse.
    """
    if not words:
        return None
    total = 0
    current = 0
    for word in words:
        normalized = word.replace("-", " ")
        for token in normalized.split():
            if token == "and":
                continue
            if token not in NUMBER_WORDS:
                return None
            value = NUMBER_WORDS[token]
            if value == 100:
                current = max(current, 1) * 100
            elif value == 1000:
                total += max(current, 1) * 1000
                current = 0
            else:
                current += value
    return total + current


def _canonicalize_numbers(text):
    """
    Convert spoken number patterns to canonical numeric form.
    "fifty four year old" -> "54-year-old"; "ten milligrams" ->
    "10 mg"; "five out of ten" -> "5/10". Heavy lifting in
    production is delegated to a tested NLP library; the demo
    handles a few common patterns inline.
    """
    # Compound-age form: "X year old" -> "X-year-old"
    def age_replace(match):
        words = match.group(1).split()
        n = _words_to_number(words)
        if n is None:
            return match.group(0)
        return f"{n}-year-old"

    text = re.sub(
        r"((?:zero|one|two|three|four|five|six|seven|eight|nine|"
        r"ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
        r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
        r"sixty|seventy|eighty|ninety|hundred|and|[- ])+)\s+"
        r"year[- ]old",
        age_replace, text)

    # "X milligrams" -> "X mg"
    def mg_replace(match):
        n = _words_to_number(match.group(1).split())
        if n is None:
            return match.group(0)
        return f"{n} mg"

    text = re.sub(
        r"((?:zero|one|two|three|four|five|six|seven|eight|nine|"
        r"ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
        r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
        r"sixty|seventy|eighty|ninety|hundred|and|[- ])+)\s+"
        r"milligrams?",
        mg_replace, text)

    # "X out of ten" -> "X/10"
    def out_of_ten(match):
        n = _words_to_number(match.group(1).split())
        if n is None:
            return match.group(0)
        return f"{n}/10"

    text = re.sub(
        r"((?:zero|one|two|three|four|five|six|seven|eight|nine|"
        r"ten)\s*(?:to\s+(?:zero|one|two|three|four|five|six|"
        r"seven|eight|nine|ten))?)\s+out\s+of\s+ten",
        out_of_ten, text)

    return text


def _apply_punctuation_and_capitalization(text):
    """
    Convert dictated punctuation words ("comma", "period", "colon",
    "new paragraph") to written punctuation, capitalize sentence
    starts, and apply common medical-abbreviation casing.
    """
    text = re.sub(r"\bcomma\b", ",", text)
    text = re.sub(r"\bperiod\b", ".", text)
    text = re.sub(r"\bcolon\b", ":", text)
    text = re.sub(r"\bsemicolon\b", ";", text)
    text = re.sub(r"\bnew paragraph\b", "\n\n", text)
    text = re.sub(r"\bnew line\b", "\n", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)

    # Capitalize sentence starts.
    def cap(match):
        return match.group(1) + match.group(2).upper()
    text = re.sub(r"(^|[\.\!\?]\s+|\n\s*)([a-z])",
                  cap, text)

    # Common medical abbreviations.
    medical_caps = {
        " po ": " PO ",
        " bid": " BID",
        " tid": " TID",
        " qid": " QID",
        " prn": " PRN",
    }
    for pattern, replacement in medical_caps.items():
        text = text.replace(pattern, replacement)

    return text.strip()


def _detect_section_headers(text, template):
    """
    Recognize section-header patterns in the text and convert
    them to bolded headers per the template's section list. The
    rule-based detector handles a few common patterns; the LLM
    in step 4C handles the long tail.
    """
    section_keys = [
        (r"chief complaint\s*[:\.]",      "Chief Complaint:"),
        (r"history of present illness\s*[:\.]",
         "History of Present Illness:"),
        (r"past medical history\s*[:\.]", "Past Medical History:"),
        (r"medications?\s*[:\.]",         "Medications:"),
        (r"allergies?\s*[:\.]",           "Allergies:"),
        (r"physical exam\s*[:\.]",        "Physical Exam:"),
        (r"assessment\s*[:\.]",           "Assessment:"),
        (r"plan\s*[:\.]",                 "Plan:"),
    ]
    for pattern, header in section_keys:
        text = re.sub(
            pattern, f"\n\n**{header}**\n\n",
            text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_formatter_prompt(verbatim, rule_based_draft, template,
                              specialty):
    """
    Build the formatter prompt. Production prompts are versioned,
    reviewed, and include explicit faithfulness instructions:
    preserve hedging, preserve clinical claims, preserve
    negations, never insert content the clinician did not say.
    """
    return {
        "instruction": (
            "You are a clinical documentation formatter. The "
            "verbatim transcript is the clinician's dictation; "
            "the rule_based_draft is a mechanical first pass. "
            "Return a formatted note that follows the template "
            "sections and the institutional formatting "
            "conventions. CRITICAL: preserve every clinical "
            "claim from the verbatim transcript exactly. "
            "Preserve hedging language ('may have' must not "
            "become 'had'). Preserve negations. Do not insert "
            "any clinical content the clinician did not "
            "dictate. Do not paraphrase clinical findings. "
            "Output strict JSON with formatted_note and "
            "structural_changes fields."),
        "verbatim":         verbatim,
        "rule_based_draft": rule_based_draft,
        "template_id":      template["id"],
        "template_sections":
            [s["header"] for s in template["sections"]],
        "specialty":        specialty,
    }


def _build_faithfulness_prompt(verbatim, formatted_note):
    """
    Build the faithfulness-check prompt. The check returns a
    score in [0, 1] and a list of warnings flagging clinical-
    claim drift between the verbatim and the formatted note.
    """
    return {
        "instruction": (
            "You are a clinical-faithfulness checker. Compare "
            "the verbatim transcript and the formatted note. "
            "Return faithfulness_score in [0, 1] reflecting "
            "whether the formatted note preserves every clinical "
            "claim from the verbatim. Flag warnings for any "
            "drift: hedging removal, claim strengthening, "
            "negation flips, dose changes, laterality flips, "
            "or content inserted that the verbatim does not "
            "support. Output strict JSON with faithfulness_score, "
            "warnings (list of {type, before, after, severity}), "
            "and rationale."),
        "verbatim":       verbatim,
        "formatted_note": formatted_note,
    }


def format_and_structure(disambiguated, asr_result, session_context):
    """
    Apply rule-based formatting to the verbatim content, then
    optionally run an LLM formatter, then run a faithfulness
    check before substituting the LLM output for the rule-based
    draft.

    Args:
        disambiguated: Dict from disambiguate_commands.
        asr_result: Dict from stream_audio_and_transcribe.
        session_context: Dict from open_dictation_session.

    Returns:
        Dict with formatted_note, faithfulness info, and an
        optional llm_alternative if the LLM draft did not pass
        the faithfulness check.
    """
    session_id = session_context["session_id"]
    template   = session_context["template"]
    verbatim   = asr_result["verbatim"]

    # Step 4A: rule-based formatting pass. Punctuation inference,
    # capitalization, number-and-date canonicalization, section
    # header detection. Lower latency than the LLM, deterministic.
    content_text = " ".join(
        s["text"] for s in disambiguated["content_segments"])
    rule_text = _apply_punctuation_and_capitalization(content_text)
    rule_text = _canonicalize_numbers(rule_text)
    rule_text = _detect_section_headers(rule_text, template)

    # Step 4B: optional LLM post-processing. Production gates
    # this on a per-clinician or per-specialty config flag; the
    # demo always runs it.
    llm_response = bedrock_mock.invoke_formatter(
        model_id=BEDROCK_FORMATTER_PROFILE_ARN,
        prompt_payload=_build_formatter_prompt(
            verbatim=verbatim,
            rule_based_draft=rule_text,
            template=template,
            specialty=session_context["specialty"]))
    try:
        llm_parsed = json.loads(llm_response["body"])
        llm_formatted_note = llm_parsed.get("formatted_note", "")
    except (TypeError, ValueError):
        llm_formatted_note = ""

    # Step 4C: faithfulness check. The formatted note must
    # preserve every clinical claim from the verbatim. The check
    # is run unconditionally when the LLM is in the formatting
    # path; the score gates whether the LLM output is preferred
    # or the rule-based draft is preferred.
    faithfulness_response = bedrock_mock.invoke_faithfulness(
        model_id=BEDROCK_FAITHFULNESS_PROFILE_ARN,
        prompt_payload=_build_faithfulness_prompt(
            verbatim=verbatim,
            formatted_note=llm_formatted_note))
    try:
        faith_parsed = json.loads(faithfulness_response["body"])
        faithfulness_score = Decimal(str(
            faith_parsed.get("faithfulness_score", 0.0)))
        faithfulness_warnings = list(
            faith_parsed.get("warnings", []))
    except (TypeError, ValueError):
        faithfulness_score = Decimal("0.0")
        faithfulness_warnings = []

    # Step 4D: choose between the LLM draft and the rule-based
    # draft based on faithfulness. When the LLM draft does not
    # pass, fall back to the rule-based draft and attach the LLM
    # version as a "suggested alternative" for clinician
    # comparison. This is the structural safeguard against the
    # silent paraphrasing failure mode.
    if (llm_formatted_note
            and faithfulness_score >= FAITHFULNESS_PASS_THRESHOLD):
        chosen_text = llm_formatted_note
        formatter_path = "llm_with_faithfulness_pass"
        llm_alternative = None
    else:
        chosen_text = rule_text
        formatter_path = (
            "rule_based_fallback_after_faithfulness_fail"
            if llm_formatted_note
            else "rule_based_only")
        llm_alternative = (
            llm_formatted_note if llm_formatted_note else None)

    formatted_object = s3_store.put_object(
        bucket=AUDIT_ARCHIVE_BUCKET,
        key=f"notes/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
            f"/{session_id}.md",
        body=chosen_text.encode("utf-8"),
        metadata={"session_id": session_id,
                  "formatter_path": formatter_path})

    dictation_meta.update(session_id, _to_decimal({
        "formatted_text_length_chars": len(chosen_text),
        "formatter_path":              formatter_path,
        "faithfulness_score":          faithfulness_score,
        "faithfulness_warning_count":  len(faithfulness_warnings),
        "formatted_archive_ref":       formatted_object["uri"],
        "formatted_at":                _now_iso(),
        "status":                      "formatted",
    }))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "FaithfulnessScore",
        float(faithfulness_score) * 100, "Percent",
        dimensions={"formatter_path": formatter_path,
                    "specialty":      session_context["specialty"]})
    if faithfulness_score < FAITHFULNESS_PASS_THRESHOLD:
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "FaithfulnessFailures",
            1, "Count",
            dimensions={"specialty":
                          session_context["specialty"]})

    audit_log({
        "event_type":          "DICTATION_FORMATTED",
        "session_id":          session_id,
        "formatter_path":      formatter_path,
        "faithfulness_score":  float(faithfulness_score),
        "warning_count":       len(faithfulness_warnings),
    })

    return {
        "session_id":          session_id,
        "formatted_text":      chosen_text,
        "formatter_path":      formatter_path,
        "faithfulness_score":  faithfulness_score,
        "faithfulness_warnings": faithfulness_warnings,
        "llm_alternative":     llm_alternative,
        "formatted_archive_ref": formatted_object["uri"],
    }
```

---

## Step 5: Extract Structured-Field Suggestions

*The pseudocode calls this `extract_structured_fields(...)`. Run Comprehend Medical against the verbatim transcript to extract medications (with RxNorm codes), conditions (with ICD-10 codes), allergies, and procedures. Cross-check against the patient's structured chart and flag discrepancies (medications mentioned in the dictation but not on the active list, conditions newly diagnosed, dosage changes). Treat every extracted entity as a suggestion for clinician review, never as a silent update. Skip this step and the dictation produces narrative text that never makes it into the structured chart, which is the entire reason the clinician was tempted to type it directly into the structured fields in the first place.*

```python
def detect_critical_errors(verbatim, formatted_text):
    """
    Flag substitutions between the verbatim and the formatted
    note that hit the configured critical-error pairs. Production
    runs this as a separate pass with a versioned rule set owned
    by the clinical-quality officer, plus a model-based pass for
    semantic drift the literal-pair check misses.
    """
    verbatim_words   = re.findall(r"[a-zA-Z]+", verbatim.lower())
    formatted_words  = re.findall(r"[a-zA-Z]+", formatted_text.lower())

    verbatim_set = set(verbatim_words)
    formatted_set = set(formatted_words)

    alerts = []
    # For each critical-error pair, flag if the "before" word is
    # in the verbatim and the "after" word is in the formatted
    # but not vice-versa. This catches one direction of
    # substitution per pair; the rules table includes both
    # directions explicitly.
    for before, after in CRITICAL_ERROR_PAIRS:
        if (before in verbatim_set
                and after in formatted_set
                and before not in formatted_set):
            alerts.append({
                "type":     "critical_substitution_suspected",
                "before":   before,
                "after":    after,
                "severity": "high",
                "rationale": (
                    f"'{before}' is in the verbatim but not in "
                    f"the formatted note; '{after}' is in the "
                    f"formatted note but not in the verbatim. "
                    f"This pair is on the critical-error list."),
            })
    return alerts


def extract_structured_fields(asr_result, formatted, session_context):
    """
    Extract coded clinical entities from the verbatim transcript,
    cross-check against the patient's chart, and produce a
    suggestions list for clinician review.

    Args:
        asr_result: Dict from stream_audio_and_transcribe.
        formatted: Dict from format_and_structure.
        session_context: Dict from open_dictation_session.

    Returns:
        Dict with suggestions, cross_check_warnings, and
        critical_error_alerts.
    """
    session_id = session_context["session_id"]
    verbatim   = asr_result["verbatim"]
    patient_id = session_context["patient_id"]

    # Step 5A: run Comprehend Medical to extract coded clinical
    # entities. Production calls
    #   comprehend_medical.detect_entities_v2(Text=verbatim)
    # plus comprehend_medical.infer_rx_norm(Text=verbatim) and
    # comprehend_medical.infer_icd10_cm(Text=verbatim) for
    # coded linking. The mock returns the union as a single
    # entity list.
    cm_response = comprehend_mock.detect_entities(verbatim)
    entities = cm_response.get("Entities", [])

    medications = []
    conditions  = []
    allergies   = []

    for entity in entities:
        category = entity.get("Category")
        if category == "MEDICATION":
            attributes = {a.get("Type"): a.get("Text")
                          for a in entity.get("Attributes", [])}
            medications.append({
                "source_text":  entity.get("Text", ""),
                "rxnorm_code":  entity.get("RxNormCode"),
                "rxnorm_display": entity.get("RxNormDisplay"),
                "dosage":       attributes.get("DOSAGE"),
                "route":        attributes.get("ROUTE_OR_MODE"),
                "frequency":    attributes.get("FREQUENCY"),
                "source_span":  (entity.get("BeginOffset"),
                                  entity.get("EndOffset")),
                "confidence":   Decimal(str(entity.get("Score", 0.0))),
            })
        elif category == "MEDICAL_CONDITION":
            negated = any(
                t.get("Name") == "NEGATION"
                for t in entity.get("Traits", []))
            conditions.append({
                "source_text":  entity.get("Text", ""),
                "icd10_code":   entity.get("ICD10Code"),
                "icd10_display": entity.get("ICD10Display"),
                "negated":      negated,
                "source_span":  (entity.get("BeginOffset"),
                                  entity.get("EndOffset")),
                "confidence":   Decimal(str(entity.get("Score", 0.0))),
            })
        elif category == "ALLERGY":
            allergies.append({
                "source_text": entity.get("Text", ""),
                "source_span": (entity.get("BeginOffset"),
                                 entity.get("EndOffset")),
                "confidence":  Decimal(str(entity.get("Score", 0.0))),
            })

    # Step 5B: cross-check against the patient's structured chart.
    # Highlight discrepancies. Note that this is intentionally
    # conservative: medications discussed but not prescribed,
    # conditions ruled out vs newly diagnosed, and dosage changes
    # all need clinical interpretation. The mock surfaces the
    # raw discrepancies; production wraps them in a clinical-
    # interpretation layer.
    chart = ehr.get_chart_state(patient_id) if patient_id else {
        "medications": [], "conditions": [], "allergies": []}
    chart_med_codes = {m.get("rxnorm_code")
                       for m in chart.get("medications", [])
                       if m.get("rxnorm_code")}
    chart_cond_codes = {c.get("icd10_code")
                        for c in chart.get("conditions", [])
                        if c.get("icd10_code")}

    suggestions          = []
    cross_check_warnings = []

    for med in medications:
        if not med.get("rxnorm_code"):
            continue
        in_chart = med["rxnorm_code"] in chart_med_codes
        suggestion = {
            "suggestion_id":   f"sug-{uuid.uuid4().hex[:12]}",
            "type":            "medication",
            "source_text":     med["source_text"],
            "source_span":     list(med["source_span"]),
            "rxnorm_code":     med["rxnorm_code"],
            "rxnorm_display":  med["rxnorm_display"],
            "dosage":          med["dosage"],
            "route":           med["route"],
            "frequency":       med["frequency"],
            "extraction_confidence": med["confidence"],
            "in_chart":        in_chart,
            "action":          ("no_change_needed" if in_chart
                                 else "add_to_med_list"),
        }
        suggestions.append(suggestion)
        if not in_chart:
            cross_check_warnings.append({
                "type":    "medication_mentioned_not_in_chart",
                "rxnorm_code": med["rxnorm_code"],
                "display": med["rxnorm_display"],
            })

    for cond in conditions:
        if cond["negated"] or not cond.get("icd10_code"):
            continue
        in_chart = cond["icd10_code"] in chart_cond_codes
        suggestion = {
            "suggestion_id":   f"sug-{uuid.uuid4().hex[:12]}",
            "type":            "condition",
            "source_text":     cond["source_text"],
            "source_span":     list(cond["source_span"]),
            "icd10_code":      cond["icd10_code"],
            "icd10_display":   cond["icd10_display"],
            "extraction_confidence": cond["confidence"],
            "in_chart":        in_chart,
            "action":          ("no_change_needed" if in_chart
                                 else "review_for_problem_list"),
        }
        suggestions.append(suggestion)
        if not in_chart:
            cross_check_warnings.append({
                "type":       "condition_mentioned_not_in_chart",
                "icd10_code": cond["icd10_code"],
                "display":    cond["icd10_display"],
            })

    # Step 5C: critical-error detection. Compare verbatim and
    # formatted text for the configured critical-error pairs.
    # Surface any hits as high-severity review alerts.
    critical_alerts = detect_critical_errors(
        verbatim=verbatim,
        formatted_text=formatted["formatted_text"])

    dictation_meta.update(session_id, _to_decimal({
        "structured_suggestions_count": len(suggestions),
        "cross_check_warnings_count":   len(cross_check_warnings),
        "critical_error_alerts_count":  len(critical_alerts),
        "structured_extraction_at":     _now_iso(),
        "status":                       "structured_extracted",
    }))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "StructuredSuggestionsPerDictation",
        len(suggestions), "Count",
        dimensions={"specialty": session_context["specialty"]})
    if critical_alerts:
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "CriticalErrorAlertsRaised",
            len(critical_alerts), "Count",
            dimensions={"specialty":
                          session_context["specialty"]})

    audit_log({
        "event_type":            "STRUCTURED_EXTRACTION_COMPLETED",
        "session_id":            session_id,
        "suggestion_count":      len(suggestions),
        "cross_check_warnings":  len(cross_check_warnings),
        "critical_error_alerts": len(critical_alerts),
    })

    return {
        "session_id":           session_id,
        "suggestions":          suggestions,
        "cross_check_warnings": cross_check_warnings,
        "critical_error_alerts": critical_alerts,
    }
```

---

## Step 6: Render the Read-Edit-Sign View and Capture Clinician Corrections

*The pseudocode calls this `render_review_view(...)`. Show the formatted note to the clinician with low-confidence words highlighted, the LLM's tracked changes (when used) visible, structured-field suggestions in a side panel, cross-check warnings flagged, and critical-error alerts surfaced with explicit confirmation required. The clinician edits, accepts or rejects each structured-field suggestion, resolves any critical-error alerts, and signs. Capture every correction as an adaptation signal for the per-clinician adaptation pipeline. Skip the correction-capture and the system never improves; clinicians see the same recurring errors month after month.*

```python
def _build_confidence_overlay(formatted_text, word_level_results):
    """
    Build a per-word confidence overlay for the review pane. The
    overlay is what the client uses to highlight low-confidence
    words for clinician attention.
    """
    overlay = []
    for word in word_level_results:
        confidence = Decimal(str(word.get("confidence", 0.0)))
        overlay.append({
            "word":       word["word"],
            "confidence": confidence,
            "is_low":     confidence < ASR_LOW_CONFIDENCE_WORD_THRESHOLD,
            "start_time": word["start_time"],
            "end_time":   word["end_time"],
        })
    return overlay


def render_review_and_capture_decisions(
        asr_result, formatted, structured, session_context):
    """
    Render the formatted note for clinician review, capture the
    clinician's decisions on structured-field suggestions, and
    capture the signature.

    Args:
        asr_result: Dict from stream_audio_and_transcribe.
        formatted: Dict from format_and_structure.
        structured: Dict from extract_structured_fields.
        session_context: Dict from open_dictation_session.

    Returns:
        Dict with signed flag, signed note, signature,
        structured_decisions, and corrections list.
    """
    session_id = session_context["session_id"]

    # Step 6A: build the review payload. Each word tagged with
    # its confidence; suggestions tagged with their source span
    # and provenance; critical-error alerts surfaced with the
    # severity tag.
    confidence_overlay = _build_confidence_overlay(
        formatted_text=formatted["formatted_text"],
        word_level_results=asr_result["word_level_results"])

    review_payload = {
        "session_id":           session_id,
        "formatted_text":       formatted["formatted_text"],
        "confidence_overlay":   confidence_overlay,
        "suggestions":          structured["suggestions"],
        "cross_check_warnings": structured["cross_check_warnings"],
        "critical_error_alerts":
            structured["critical_error_alerts"],
        "faithfulness_warnings":
            formatted["faithfulness_warnings"],
        "llm_alternative":      formatted["llm_alternative"],
    }

    client.render_review(review_payload)

    # Step 6B: capture clinician decisions on structured-field
    # suggestions. In production the client posts decisions back
    # to a REST endpoint as the clinician interacts with the
    # review pane; the demo retrieves a pre-queued list of
    # decisions.
    decisions = client.collect_review_events()

    # Build a structured-decisions list aligned with each
    # suggestion. Decisions are accept | reject | modify; modify
    # carries an updated value.
    decisions_by_id = {d.get("suggestion_id"): d
                        for d in decisions}
    structured_decisions = []
    for suggestion in structured["suggestions"]:
        decision = decisions_by_id.get(
            suggestion["suggestion_id"],
            {"suggestion_id": suggestion["suggestion_id"],
             "decision":      "reject"})
        structured_decisions.append({
            "suggestion_id":     suggestion["suggestion_id"],
            "type":              suggestion["type"],
            "decision":          decision.get("decision", "reject"),
            "rxnorm_code":       suggestion.get("rxnorm_code"),
            "icd10_code":        suggestion.get("icd10_code"),
            "dosage":            suggestion.get("dosage"),
            "frequency":         suggestion.get("frequency"),
            "modified_value":    decision.get("modified_value"),
        })

    # Step 6C: critical-error alerts must be explicitly resolved
    # before signature. The demo enforces by requiring that a
    # signature only be captured when no high-severity alerts
    # are unacknowledged. Production tracks per-alert
    # acknowledgments.
    unresolved_critical = [
        a for a in structured["critical_error_alerts"]
        if a.get("severity") == "high"
        and not any(
            d.get("decision") == "acknowledge_critical"
            and d.get("alert_index") == idx
            for idx, d in enumerate(decisions))
    ]
    if unresolved_critical:
        audit_log({
            "event_type":              "SIGNATURE_BLOCKED_CRITICAL_ALERT",
            "session_id":              session_id,
            "unresolved_alert_count":  len(unresolved_critical),
        })
        # Production blocks signature; the demo logs and
        # continues so the audit record reflects the gap. In
        # production this would loop back to the review UX.

    # Step 6D: capture the signature. Production prompts the
    # clinician for password + button-press; the demo uses the
    # mock's queued signature.
    signature = client.get_signature()

    # Step 6E: capture corrections (text edits the clinician made
    # in the review pane). Each correction is an adaptation
    # signal for the per-clinician adaptation pipeline.
    corrections = [
        d for d in decisions
        if d.get("event_type") == "text_edit"
    ]

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "StructuredSuggestionsAccepted",
        sum(1 for d in structured_decisions
            if d["decision"] == "accept"),
        "Count",
        dimensions={"specialty": session_context["specialty"]})
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "StructuredSuggestionsRejected",
        sum(1 for d in structured_decisions
            if d["decision"] == "reject"),
        "Count",
        dimensions={"specialty": session_context["specialty"]})
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "CorrectionsPerNote",
        len(corrections), "Count",
        dimensions={"clinician_id":
                      session_context["clinician_id"],
                    "specialty":
                      session_context["specialty"]})

    audit_log({
        "event_type":           "DICTATION_REVIEWED_AND_SIGNED",
        "session_id":           session_id,
        "structured_decisions": len(structured_decisions),
        "accepted":             sum(
            1 for d in structured_decisions
            if d["decision"] == "accept"),
        "rejected":             sum(
            1 for d in structured_decisions
            if d["decision"] == "reject"),
        "corrections_count":    len(corrections),
        "signature_method":     signature.get("method"),
    })

    return {
        "signed":               True,
        "session_id":           session_id,
        "signed_note":          formatted["formatted_text"],
        "signature":            signature,
        "structured_decisions": structured_decisions,
        "corrections":          corrections,
        "unresolved_critical_count": len(unresolved_critical),
    }
```

---

## Step 7: Hand Off the Signed Note to the EHR and Apply Confirmed Structured Updates

*The pseudocode calls this `handoff_to_ehr(...)`. Push the signed note into the EHR's note repository, apply the structured-field updates the clinician confirmed (accept-only writes; rejected suggestions never touch the chart), capture the EHR's response, and update the dictation-metadata record. Treat structured-field writes with the same idempotency and audit rigor as any other clinical write. Skip the explicit confirmation handling and structured updates execute silently, which is the same anti-pattern as the read-write boundary in recipe 10.3 and produces the same class of harm.*

```python
def handoff_to_ehr(review_result, session_context):
    """
    Create the signed note in the EHR and apply the confirmed
    structured-field updates. Reject decisions never produce
    writes. Capture the EHR's response and update the dictation-
    metadata record with the final state.

    Args:
        review_result: Dict from
            render_review_and_capture_decisions.
        session_context: Dict from open_dictation_session.

    Returns:
        Dict with note_id and the structured_results list.
    """
    session_id = session_context["session_id"]
    patient_id = session_context["patient_id"]

    # Step 7A: create the note in the EHR. Production calls the
    # FHIR DocumentReference / Composition resource creation
    # APIs with the clinician's access token; on success the EHR
    # returns the note_id which becomes the chart's authoritative
    # reference. Idempotency: a re-submission with the same
    # session_id MUST not create a duplicate note. Production
    # implements this with a vendor-specific idempotency header
    # or a conditional-create pattern. The mock simply creates
    # one note per call.
    note_creation = ehr.create_note(
        patient_id=patient_id,
        encounter_id=session_context.get("encounter_id"),
        author_id=session_context["clinician_id"],
        note_type=session_context["template"]["note_type"],
        content=review_result["signed_note"],
        signature=review_result["signature"])
    note_id = note_creation["note_id"]

    # Step 7B: apply confirmed structured updates. accept ->
    # write to the appropriate FHIR resource. reject -> log
    # only. modify -> apply with the clinician's modified value.
    structured_results = []
    for decision in review_result["structured_decisions"]:
        if decision["decision"] == "reject":
            structured_results.append({
                "suggestion_id": decision["suggestion_id"],
                "type":          decision["type"],
                "result":        "rejected_no_write",
            })
            continue

        if decision["type"] == "medication" and decision.get("rxnorm_code"):
            result = ehr.add_medication(
                patient_id=patient_id,
                medication_code=decision["rxnorm_code"],
                dosage=(decision.get("modified_value", {}).get("dosage")
                        if decision.get("decision") == "modify"
                        else decision.get("dosage")),
                frequency=(decision.get("modified_value", {})
                            .get("frequency")
                           if decision.get("decision") == "modify"
                           else decision.get("frequency")),
                source_note_id=note_id)
            structured_results.append({
                "suggestion_id": decision["suggestion_id"],
                "type":          "medication",
                "rxnorm_code":   decision["rxnorm_code"],
                "result":        result.get("status"),
            })
        elif decision["type"] == "condition" and decision.get("icd10_code"):
            result = ehr.add_condition(
                patient_id=patient_id,
                condition_code=decision["icd10_code"],
                source_note_id=note_id)
            structured_results.append({
                "suggestion_id": decision["suggestion_id"],
                "type":          "condition",
                "icd10_code":    decision["icd10_code"],
                "result":        result.get("status"),
            })
        else:
            structured_results.append({
                "suggestion_id": decision["suggestion_id"],
                "type":          decision["type"],
                "result":        "unsupported_or_missing_code",
            })

    dictation_meta.update(session_id, _to_decimal({
        "note_id":              note_id,
        "structured_results":   structured_results,
        "structured_accepted_count": sum(
            1 for r in structured_results
            if r.get("result") == "applied"),
        "structured_rejected_count": sum(
            1 for r in structured_results
            if r.get("result") == "rejected_no_write"),
        "signed_at":            review_result["signature"].get("timestamp"),
        "signature_method":
            review_result["signature"].get("method"),
        "status":               "signed_and_handed_off",
    }))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "NotesSigned", 1, "Count",
        dimensions={"specialty": session_context["specialty"]})

    audit_log({
        "event_type":          "EHR_HANDOFF_COMPLETE",
        "session_id":          session_id,
        "note_id":             note_id,
        "structured_writes":   len(
            [r for r in structured_results
             if r.get("result") == "applied"]),
    })

    return {
        "session_id":         session_id,
        "note_id":            note_id,
        "structured_results": structured_results,
    }
```

---

## Step 8: Audit, Archive, and Feed Adaptation

*The pseudocode calls this `audit_archive_and_adapt(...)`. Capture the full lifecycle of the dictation in the audit archive: the audio reference (under the institution's retention policy), the verbatim transcript reference, the formatted note reference, the structured-field suggestions and decisions, the corrections stream, the signature, and the EHR handoff result. Emit operational telemetry for the dashboards, lifecycle events for the cross-system consumers, and per-clinician adaptation signals for the next dictation. Skip the audit and the institution cannot reconstruct what the system did during a clinical-quality review or during litigation.*

```python
def audit_archive_and_adapt(asr_result, formatted, structured,
                              review_result, ehr_handoff, session_context):
    """
    Write the durable audit record, emit lifecycle events, fan
    out adaptation signals, and emit operational metrics.
    """
    session_id   = session_context["session_id"]
    metadata     = dictation_meta.get(session_id)

    # Step 8A: write the durable audit record. References (not
    # contents) for the audio and the verbatim transcript;
    # structural metadata captured for forensic queries.
    activation_at = session_context["activation_at"]
    signed_at     = review_result["signature"].get("timestamp")
    try:
        time_to_sign = (
            datetime.fromisoformat(signed_at.replace("Z", "+00:00"))
            - datetime.fromisoformat(
                activation_at.replace("Z", "+00:00"))
        ).total_seconds()
    except (TypeError, ValueError):
        time_to_sign = 0.0

    audit_record = _to_decimal({
        "session_id":           session_id,
        "clinician_id":         session_context["clinician_id"],
        "patient_id":           session_context.get("patient_id"),
        "encounter_id":
            session_context.get("encounter_id"),
        "note_id":              ehr_handoff["note_id"],
        "specialty":            session_context["specialty"],
        "template_id":          session_context["template"]["id"],
        "dictation_started_at": activation_at,
        "transcribed_at":       metadata.get("transcribed_at"),
        "formatted_at":         metadata.get("formatted_at"),
        "signed_at":             signed_at,
        "audio_archive_ref":     asr_result["audio_s3_uri"],
        "verbatim_transcript_archive_ref":
            asr_result["verbatim_archive_ref"],
        "verbatim_transcript_length_chars":
            len(asr_result["verbatim"]),
        "verbatim_avg_confidence":
            asr_result["avg_confidence"],
        "verbatim_low_conf_word_count":
            asr_result["low_conf_count"],
        "formatted_archive_ref":
            formatted["formatted_archive_ref"],
        "formatted_text_length_chars":
            len(formatted["formatted_text"]),
        "formatter_path":       formatted["formatter_path"],
        "faithfulness_score":   formatted["faithfulness_score"],
        "faithfulness_warning_count":
            len(formatted["faithfulness_warnings"]),
        "structured_suggestions_count":
            len(structured["suggestions"]),
        "structured_accepted_count": sum(
            1 for r in ehr_handoff["structured_results"]
            if r.get("result") == "applied"),
        "structured_rejected_count": sum(
            1 for r in ehr_handoff["structured_results"]
            if r.get("result") == "rejected_no_write"),
        "critical_error_alerts_count":
            len(structured["critical_error_alerts"]),
        "unresolved_critical_count":
            review_result["unresolved_critical_count"],
        "corrections_count":
            len(review_result["corrections"]),
        "time_to_sign_seconds": Decimal(str(time_to_sign)),
        "asr_model_version":    ASR_MODEL_VERSION,
        "rule_formatter_version": RULE_FORMATTER_VERSION,
        "llm_formatter_prompt_version":
            LLM_FORMATTER_PROMPT_VERSION,
        "faithfulness_prompt_version":
            FAITHFULNESS_PROMPT_VERSION,
        "critical_error_rules_version":
            CRITICAL_ERROR_RULES_VERSION,
        "structured_extraction_version":
            STRUCTURED_EXTRACTION_VERSION,
        "signature":            review_result["signature"],
    })

    audit_object = s3_store.put_object(
        bucket=AUDIT_ARCHIVE_BUCKET,
        key=f"audit/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
            f"/{session_id}.json",
        body=json.dumps(audit_record, default=str).encode("utf-8"),
        metadata={"session_id": session_id,
                  "clinician_id": session_context["clinician_id"]})

    # Step 8B: emit lifecycle event for downstream consumers
    # (analytics, dashboards, EHR audit overlay).
    event_bus.put_events([{
        "Source":       "dictation",
        "DetailType":   "dictation_signed",
        "EventBusName": DICTATION_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":   session_id,
            "clinician_id": session_context["clinician_id"],
            "specialty":    session_context["specialty"],
            "note_id":      ehr_handoff["note_id"],
            "time_to_sign_seconds": time_to_sign,
            "corrections_count":
                len(review_result["corrections"]),
            "structured_accepted":
                int(audit_record["structured_accepted_count"]),
            "critical_error_alerts":
                len(structured["critical_error_alerts"]),
        }),
    }])

    # Step 8C: feed corrections into the per-clinician adaptation
    # pipeline. Each correction (verbatim word -> corrected word)
    # is a training signal for the per-clinician custom
    # vocabulary and, when applicable, for per-clinician
    # acoustic-model adaptation.
    for correction in review_result["corrections"]:
        event_bus.put_events([{
            "Source":       "dictation.adaptation",
            "DetailType":   "clinician_correction",
            "EventBusName": DICTATION_EVENT_BUS_NAME,
            "Detail": json.dumps({
                "session_id":   session_id,
                "clinician_id":
                    session_context["clinician_id"],
                "before":       correction.get("before"),
                "after":        correction.get("after"),
                "position":     correction.get("position"),
                "audio_archive_ref": asr_result["audio_s3_uri"],
            }),
        }])

    # Step 8D: operational metrics.
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "TimeToSignSeconds",
        time_to_sign, "Seconds",
        dimensions={"specialty": session_context["specialty"],
                    "note_type":
                      session_context["template"]["note_type"]})

    audit_log({
        "event_type":         "DICTATION_AUDITED",
        "session_id":         session_id,
        "audit_archive_ref":  audit_object["uri"],
        "time_to_sign_seconds": time_to_sign,
    })

    return audit_record
```

---

## Putting It All Together

The pipeline ties together as a top-level function that simulates a single dictation flowing end-to-end through the eight stages. In a Lambda-and-Step-Functions deployment, each stage is a separate Lambda invoked from the Step Functions state machine; the demo orchestrates them inline so you can see the full sequence.

```python
def process_dictation(clinician_id, smart_on_fhir_context,
                       note_context):
    """
    End-to-end dictation processing for a single dictation
    session. Assumes the clinician has authenticated and
    initiated dictation; this function runs once per dictation.
    """
    activation_at = _now_iso()
    print("\n--- Stage 1: open dictation session ---")
    session_context = open_dictation_session(
        clinician_id=clinician_id,
        smart_on_fhir_context=smart_on_fhir_context,
        note_context=note_context,
        activation_at=activation_at)
    print(f"  session_id: {session_context['session_id']}")
    print(f"  specialty:  {session_context['specialty']}")
    print(f"  template:   {session_context['template']['id']}")
    print(f"  biasing terms: "
          f"{len(session_context['biasing_terms'])}")

    print("\n--- Stage 2: stream audio + transcribe ---")
    asr_result = stream_audio_and_transcribe(session_context)
    if not asr_result["proceed"]:
        print(f"  proceed: False; "
              f"disposition: {asr_result['disposition']}")
        return {"status": asr_result["disposition"],
                "session_id": session_context["session_id"]}
    print(f"  verbatim length: {len(asr_result['verbatim'])} chars")
    print(f"  avg confidence:  "
          f"{float(asr_result['avg_confidence']):.2f}")
    print(f"  low-conf words:  {asr_result['low_conf_count']}")

    print("\n--- Stage 3: disambiguate commands ---")
    disambiguated = disambiguate_commands(asr_result, session_context)
    print(f"  content segments:    "
          f"{len(disambiguated['content_segments'])}")
    print(f"  structural events:   "
          f"{len(disambiguated['structural_events'])}")

    print("\n--- Stage 4: format + structure ---")
    formatted = format_and_structure(
        disambiguated, asr_result, session_context)
    print(f"  formatter path:      {formatted['formatter_path']}")
    print(f"  faithfulness score:  "
          f"{float(formatted['faithfulness_score']):.2f}")
    print(f"  warnings:            "
          f"{len(formatted['faithfulness_warnings'])}")

    print("\n--- Stage 5: extract structured fields ---")
    structured = extract_structured_fields(
        asr_result, formatted, session_context)
    print(f"  suggestions:           "
          f"{len(structured['suggestions'])}")
    print(f"  cross-check warnings:  "
          f"{len(structured['cross_check_warnings'])}")
    print(f"  critical-error alerts: "
          f"{len(structured['critical_error_alerts'])}")

    print("\n--- Stage 6: render review + capture decisions ---")
    review_result = render_review_and_capture_decisions(
        asr_result, formatted, structured, session_context)
    accepted = sum(1 for d in review_result["structured_decisions"]
                   if d["decision"] == "accept")
    rejected = sum(1 for d in review_result["structured_decisions"]
                   if d["decision"] == "reject")
    print(f"  signed:               {review_result['signed']}")
    print(f"  decisions accepted:   {accepted}")
    print(f"  decisions rejected:   {rejected}")
    print(f"  corrections captured: "
          f"{len(review_result['corrections'])}")

    print("\n--- Stage 7: hand off to EHR ---")
    ehr_handoff = handoff_to_ehr(review_result, session_context)
    print(f"  note_id:              {ehr_handoff['note_id']}")
    print(f"  structured writes:    "
          f"{sum(1 for r in ehr_handoff['structured_results'] "
          f"if r.get('result') == 'applied')}")

    print("\n--- Stage 8: audit + adapt ---")
    audit_record = audit_archive_and_adapt(
        asr_result, formatted, structured,
        review_result, ehr_handoff, session_context)
    print(f"  time-to-sign:         "
          f"{float(audit_record['time_to_sign_seconds']):.2f}s")

    return {
        "status":       "signed",
        "session_id":   session_context["session_id"],
        "note_id":      ehr_handoff["note_id"],
        "time_to_sign": float(audit_record["time_to_sign_seconds"]),
    }


def run_demo():
    """
    Run a small set of end-to-end scenarios that exercise the
    main paths through the dictation pipeline:
      1. Standard primary-care followup dictation: clean ASR,
         LLM passes the faithfulness check, structured-field
         suggestions extracted and accepted by the clinician.
      2. Faithfulness-fail scenario: the LLM "improves" the
         clinician's hedging and the faithfulness check rejects
         the LLM draft; the rule-based draft is preferred and
         the LLM version is offered as a "suggested alternative."
      3. Critical-error scenario: the verbatim contains "left"
         but the formatted text contains "right" (a laterality
         flip that would be a clinical-safety event); the
         critical-error detector flags it for explicit
         clinician confirmation.
    """
    global transcribe_med, bedrock_mock, comprehend_mock, clinician_config

    # --- Per-clinician config fixtures ---
    clinician_config = MockClinicianConfig({
        "user-jdoe": {
            "clinician_id":      "user-jdoe",
            "specialty":         "PRIMARYCARE",
            "specialty_terms":   ["hypertension", "hyperlipidemia"],
            "custom_terms":      ["dabigatran"],
            "preferred_template": "primary-care-followup-v2",
            "macros":            {},
        },
    })

    # --- Per-scenario fixture data ---
    transcript_fixtures   = {}
    formatter_responses   = {}
    faithfulness_responses = {}
    entity_fixtures       = {}

    transcribe_med   = MockTranscribeMedical(transcript_fixtures)
    bedrock_mock     = MockBedrock(
        formatter_responses, faithfulness_responses)
    comprehend_mock  = MockComprehendMedical(entity_fixtures)

    smart_context_template = {
        "launch_id":    "launch-1a2b3c4d",
        "access_token": "<placeholder access token>",
        "issued_at":    _now_iso(),
        "patient_id":   "pt-44219-3c",
        "encounter_id": "enc-2026-05-23-1422",
    }

    # ---------- Scenario 1 ----------
    s1_verbatim = (
        "chief complaint comma chest pain period new paragraph "
        "history of present illness colon the patient is a "
        "fifty four year old male with a history of "
        "hypertension and hyperlipidemia who presents to the "
        "clinic today complaining of intermittent chest pain "
        "over the last two weeks period the pain is described "
        "as pressure like comma rated five out of ten in "
        "severity period new paragraph medications colon "
        "lisinopril ten milligrams po daily comma atorvastatin "
        "forty milligrams po nightly period")
    s1_items = [
        {"start_time": i * 0.4, "end_time": i * 0.4 + 0.35,
         "alternatives": [{"content": w, "confidence": "0.94"}]}
        for i, w in enumerate(s1_verbatim.split())
    ]
    s1_formatted = (
        "**Chief Complaint:** Chest pain.\n\n"
        "**History of Present Illness:**\n\n"
        "The patient is a 54-year-old male with a history of "
        "hypertension and hyperlipidemia who presents to the "
        "clinic today complaining of intermittent chest pain "
        "over the last two weeks. The pain is described as "
        "pressure-like, rated 5/10 in severity.\n\n"
        "**Medications:**\n\n"
        "- Lisinopril 10 mg PO daily\n"
        "- Atorvastatin 40 mg PO nightly\n")

    # ---------- Scenario 2 (faithfulness fail) ----------
    s2_verbatim = (
        "the patient may have had a small stroke in the "
        "interim period the symptoms are intermittent and "
        "may be related to medication adjustments period")
    s2_items = [
        {"start_time": i * 0.4, "end_time": i * 0.4 + 0.35,
         "alternatives": [{"content": w, "confidence": "0.92"}]}
        for i, w in enumerate(s2_verbatim.split())
    ]
    # The LLM "improved" the hedging language ("may have had" ->
    # "had"); the faithfulness check should reject this.
    s2_llm_formatted = (
        "The patient had a small stroke in the interim. The "
        "symptoms are occasional and are related to medication "
        "adjustments.")

    # ---------- Scenario 3 (critical-error: laterality flip) ----------
    s3_verbatim = (
        "the patient reports pain in the left lower quadrant "
        "period there is no rebound tenderness period")
    s3_items = [
        {"start_time": i * 0.4, "end_time": i * 0.4 + 0.35,
         "alternatives": [{"content": w, "confidence": "0.93"}]}
        for i, w in enumerate(s3_verbatim.split())
    ]
    # The LLM (or the rule pass) flipped "left" to "right", a
    # critical clinical error.
    s3_llm_formatted = (
        "The patient reports pain in the right lower quadrant. "
        "There is no rebound tenderness.")

    # Wire up fixtures.
    formatter_responses[
        MockBedrock._fixture_key(s1_verbatim)] = {
            "formatted_note":    s1_formatted,
            "structural_changes": ["section_headers_inserted",
                                    "list_formatting_applied"],
            "rationale":         "Standard formatting applied.",
        }
    faithfulness_responses[
        MockBedrock._fixture_key(s1_verbatim)] = {
            "faithfulness_score": 0.98,
            "warnings":          [],
            "rationale":         "All clinical claims preserved.",
        }
    formatter_responses[
        MockBedrock._fixture_key(s2_verbatim)] = {
            "formatted_note":    s2_llm_formatted,
            "structural_changes": [],
            "rationale":         "Refined wording for clarity.",
        }
    faithfulness_responses[
        MockBedrock._fixture_key(s2_verbatim)] = {
            "faithfulness_score": 0.62,
            "warnings": [
                {"type":     "hedging_removed",
                 "before":   "may have had",
                 "after":    "had",
                 "severity": "high"},
                {"type":     "claim_strengthened",
                 "before":   "intermittent",
                 "after":    "occasional",
                 "severity": "medium"},
            ],
            "rationale": ("Hedging language stripped; clinical "
                          "claims have changed."),
        }
    formatter_responses[
        MockBedrock._fixture_key(s3_verbatim)] = {
            "formatted_note":    s3_llm_formatted,
            "structural_changes": [],
            "rationale":         "Light formatting applied.",
        }
    faithfulness_responses[
        MockBedrock._fixture_key(s3_verbatim)] = {
            # The faithfulness model failed to catch the
            # laterality flip; the critical-error detector is
            # the second line of defense.
            "faithfulness_score": 0.95,
            "warnings":          [],
            "rationale":         ("No semantic drift detected by "
                                   "the faithfulness check."),
        }

    # Comprehend Medical fixtures keyed by transcript substring.
    entity_fixtures["lisinopril"] = {
        "Entities": [
            {"Category": "MEDICATION", "Text": "lisinopril",
             "Score": 0.97, "BeginOffset": 0, "EndOffset": 10,
             "RxNormCode": "29046",
             "RxNormDisplay": "Lisinopril 10 MG Oral Tablet",
             "Attributes": [
                 {"Type": "DOSAGE", "Text": "10 mg"},
                 {"Type": "ROUTE_OR_MODE", "Text": "oral"},
                 {"Type": "FREQUENCY", "Text": "daily"},
             ]},
            {"Category": "MEDICATION", "Text": "atorvastatin",
             "Score": 0.95, "BeginOffset": 10, "EndOffset": 22,
             "RxNormCode": "83367",
             "RxNormDisplay": "Atorvastatin 40 MG Oral Tablet",
             "Attributes": [
                 {"Type": "DOSAGE", "Text": "40 mg"},
                 {"Type": "ROUTE_OR_MODE", "Text": "oral"},
                 {"Type": "FREQUENCY", "Text": "at bedtime"},
             ]},
            {"Category": "MEDICAL_CONDITION",
             "Text": "intermittent chest pain",
             "Score": 0.84, "BeginOffset": 100, "EndOffset": 122,
             "ICD10Code": "R07.9",
             "ICD10Display": "Chest pain, unspecified",
             "Traits": []},
        ],
    }

    scenarios = [
        {"name":     "standard_primary_care_dictation",
         "verbatim": s1_verbatim,
         "items":    s1_items,
         "decisions": [
             # Accept lisinopril (already in chart, no-op);
             # accept atorvastatin (will add to med list);
             # reject the chest-pain condition suggestion
             # because it's already documented in the HPI.
             {"suggestion_id": "ANY_MEDICATION_LISINOPRIL",
              "decision": "accept"},
             {"suggestion_id": "ANY_MEDICATION_ATORVASTATIN",
              "decision": "accept"},
             {"suggestion_id": "ANY_CONDITION",
              "decision": "reject"},
         ],
         "duration": 89.0},
        {"name":     "faithfulness_fail_hedging_removed",
         "verbatim": s2_verbatim,
         "items":    s2_items,
         "decisions": [],
         "duration": 12.0},
        {"name":     "critical_error_laterality_flip",
         "verbatim": s3_verbatim,
         "items":    s3_items,
         "decisions": [],
         "duration": 9.0},
    ]

    for scenario in scenarios:
        print("\n" + "#" * 60)
        print(f"# SCENARIO: {scenario['name']}")
        print("#" * 60)

        # Open a fresh session and inject the per-scenario
        # fixture under the session_id.
        smart_context = dict(smart_context_template)
        note_context = {"note_type": "progress-note",
                         "template_id": "primary-care-followup-v2"}

        # Pre-build the session_id so we can prime the transcript
        # fixture before the streaming step runs.
        # Easier approach: open the session first, then inject
        # the fixture under the resulting session_id, then run
        # the rest of the pipeline. We do this by splitting
        # process_dictation manually for the demo.

        session_context = open_dictation_session(
            clinician_id="user-jdoe",
            smart_on_fhir_context=smart_context,
            note_context=note_context,
            activation_at=_now_iso())
        transcript_fixtures[session_context["session_id"]] = {
            "verbatim":         scenario["verbatim"],
            "items":            scenario["items"],
            "duration_seconds": scenario["duration"],
        }

        # Map the suggestion-decision aliases ("ANY_MEDICATION_X")
        # to the actual suggestion_ids that get generated, by
        # running the pipeline up through stage 5 first, then
        # queueing decisions, then continuing.
        asr_result = stream_audio_and_transcribe(session_context)
        if not asr_result["proceed"]:
            print(f"  >>> aborting: "
                  f"{asr_result.get('disposition')}")
            continue

        disambiguated = disambiguate_commands(
            asr_result, session_context)
        formatted = format_and_structure(
            disambiguated, asr_result, session_context)
        structured = extract_structured_fields(
            asr_result, formatted, session_context)

        # Translate alias decisions to real suggestion_ids.
        decisions = []
        for alias_decision in scenario["decisions"]:
            alias = alias_decision["suggestion_id"]
            for sug in structured["suggestions"]:
                if (alias == "ANY_MEDICATION_LISINOPRIL"
                        and sug["type"] == "medication"
                        and sug.get("rxnorm_code") == "29046"):
                    decisions.append(
                        {"suggestion_id": sug["suggestion_id"],
                         "decision":      alias_decision["decision"]})
                elif (alias == "ANY_MEDICATION_ATORVASTATIN"
                          and sug["type"] == "medication"
                          and sug.get("rxnorm_code") == "83367"):
                    decisions.append(
                        {"suggestion_id": sug["suggestion_id"],
                         "decision":      alias_decision["decision"]})
                elif (alias == "ANY_CONDITION"
                          and sug["type"] == "condition"):
                    decisions.append(
                        {"suggestion_id": sug["suggestion_id"],
                         "decision":      alias_decision["decision"]})
        client.queue_review_decisions(decisions)
        client.queue_signature({
            "type":      "electronic",
            "method":    "password",
            "timestamp": _now_iso(),
        })

        review_result = render_review_and_capture_decisions(
            asr_result, formatted, structured, session_context)
        ehr_handoff = handoff_to_ehr(
            review_result, session_context)
        audit_record = audit_archive_and_adapt(
            asr_result, formatted, structured,
            review_result, ehr_handoff, session_context)

        print(f"\n  >>> formatter_path:     "
              f"{formatted['formatter_path']}")
        print(f"  >>> faithfulness_score: "
              f"{float(formatted['faithfulness_score']):.2f}")
        print(f"  >>> critical_alerts:    "
              f"{len(structured['critical_error_alerts'])}")
        print(f"  >>> note_id:            "
              f"{ehr_handoff['note_id']}")
        print(f"  >>> structured_writes:  "
              f"{sum(1 for r in ehr_handoff['structured_results'] "
              f"if r.get('result') == 'applied')}")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("DEMO SUMMARY")
    print("=" * 60)
    print(f"Audit objects written:       "
          f"{len(s3_store.list(AUDIT_ARCHIVE_BUCKET))}")
    print(f"Audio objects written:       "
          f"{len(s3_store.list(AUDIO_BUCKET))}")
    print(f"Cross-system events emitted: "
          f"{len(event_bus.events)}")
    print(f"CloudWatch metrics emitted:  "
          f"{len(cloudwatch.metrics)}")
    print(f"EHR notes created:           "
          f"{len(ehr._created_notes)}")
    print(f"EHR structured writes:       "
          f"{len(ehr._structured_writes)}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    run_demo()
```

> **A note on the demo's mocks.** Real Transcribe Medical, Bedrock, and Comprehend Medical calls receive the actual audio (or text) and return real model outputs. The demo's mocks use fixture lookups so the same scenario always produces the same output, which makes the rest of the pipeline deterministic for teaching purposes. The fixtures are keyed by session_id (for Transcribe Medical) and by verbatim-substring (for Bedrock and Comprehend Medical). This is enough to demonstrate the per-clinician-vocabulary discipline, the command-versus-content disambiguation, the LLM-faithfulness fallback, the critical-error detection, and the explicit-confirmation rigor for structured-field updates, without needing live model deployments to run the file.

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right audit records, but the distance between it and a real medical-dictation pipeline running in clinicians' offices is significant. Here is where that distance lives.

**Real API Gateway WebSocket plus per-stage Lambdas plus Step Functions.** The demo orchestrates stages in Python. Production fronts the streaming audio with API Gateway's WebSocket API (with a Cognito authorizer and the SMART on FHIR access token validated on connect), routes audio frames to an audio-stream-handler service (an ECS task or a long-running Lambda variant for streaming sessions), and orchestrates the post-ASR pipeline through AWS Step Functions. Step Functions handles the durable retry semantics: if Bedrock throttles, retry with exponential backoff; if Comprehend Medical fails, route to a DLQ; if the EHR handoff fails, hold the signed note in a queue with manual replay capability. Each Lambda has its own IAM role, error handling, retries, and DLQs.

**Real Transcribe Medical streaming wiring.** The demo mocks the streaming ASR. Production calls `transcribe_client.start_medical_stream_transcription` with `LanguageCode="en-US"`, `MediaSampleRateHertz=16000`, `Specialty=session_context["specialty"]`, `Type="DICTATION"`, `VocabularyName=vocabulary_name`, `ShowSpeakerLabels=False`, `EnablePartialResultsStabilization=True`, and `PartialResultsStability="high"`. The audio frames push through the resulting stream as they arrive from the WebSocket; partial transcripts emit back to the client for visual feedback (the words appearing as the clinician dictates); the final transcript emits at end-of-dictation. The streaming connection is bounded: a long radiology dictation may run several minutes, but each individual streaming call is bounded by the service's session limit and the operational budget. For dictations that exceed a single streaming-session window, the architecture chunks the audio with explicit session boundaries and stitches the chunks together at the formatting layer.

**Real custom-vocabulary management.** The demo records the biasing terms and proceeds. Production maintains custom vocabularies per institution (the formulary, provider list), per specialty (specialty-specific term sets curated by clinical operations), and per clinician (personal additions accumulated through the adaptation pipeline). The vocabularies are created via `transcribe_client.create_medical_vocabulary` and updated as terms are added. The `VocabularyName` referenced at session start must exist and be in the `READY` state; production has a vocabulary-management service that creates, updates, and warms vocabularies before sessions reference them.

**Real Bedrock invocation, prompt management, and inference profile.** The demo's MockBedrock uses fixture lookups. Production calls `bedrock_runtime.invoke_model` with `modelId=BEDROCK_FORMATTER_PROFILE_ARN` (the inference profile is what you pass for cross-region inference and per-profile rate limits) and a versioned prompt that includes a system instruction, the template schema, the institutional formatting conventions, explicit faithfulness instructions, and a strict-JSON output schema. The faithfulness model can be a smaller, cheaper model (Claude 3 Haiku is appropriate); the formatter is the larger, more capable model. Both prompts are versioned and deployed alongside the rest of the pipeline; prompt changes go through clinical-operations review (the prompts are load-bearing safety artifacts, not config strings).

**Real Comprehend Medical wiring.** The demo's MockComprehendMedical uses fixture lookups. Production calls `comprehend_medical.detect_entities_v2(Text=verbatim)` for the entity extraction, `comprehend_medical.infer_rx_norm(Text=verbatim)` for medication coding, and `comprehend_medical.infer_icd10_cm(Text=verbatim)` for condition coding. The responses are merged on entity offsets to produce the suggestion list. Comprehend Medical occasionally misidentifies entities, misses negation, or extracts dosages incorrectly; the suggestion-with-explicit-confirmation flow is what makes this safe to deploy.

**Per-Lambda IAM roles.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda (session-opener, audio-stream-handler, formatter, structured-field-extractor, EHR-handoff, audit-writer, adaptation-emitter), each scoped to the specific resource ARNs the Lambda touches. The formatter role has scoped Bedrock invocation rights pinned to one model and one inference profile. The structured-field-extractor role has scoped Comprehend Medical inference rights only. The EHR-handoff role has scoped Secrets Manager read for the EHR credentials and write access only to the in-flight dictation-metadata record. Wildcard actions and resources will fail any serious IAM review.

**Real DynamoDB wiring with KMS and PITR.** The mocks in the demo are dictionaries; production is DynamoDB tables (session-state with TTL on idle sessions, dictation-metadata partitioned by clinician_id with session_id sort key, clinician-config partitioned by clinician_id) with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery enabled, and DynamoDB Streams emitting change events to the audit and analytics consumers. The audit table has Streams feeding a Kinesis Firehose delivery stream that writes to S3 with Object Lock in compliance mode for HIPAA-grade durability.

**Customer-managed KMS keys, per data class.** Every PHI-bearing resource (audio bucket, audit-archive bucket, dictation-metadata table, session-state table, clinician-config table, Lambda environment variables, CloudWatch Logs, Secrets Manager) uses customer-managed KMS keys with rotation enabled. Different keys per data class for blast-radius containment: a compromised audio-bucket key does not compromise the audit archive. CloudTrail logs every key-usage event. The institutional KMS-key-management runbook specifies rotation cadence, access review cadence, and the cross-account key-grant pattern.

**S3 lifecycle and Object Lock.** The audio bucket has a brief-retention lifecycle (delete after seven to thirty days, per the privacy-officer-reviewed retention policy) with the option of opt-in longer retention with explicit consent. The audit archive uses Object Lock in compliance mode for HIPAA-grade durability with retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, and the institution's policy. Lifecycle transitions move older audit archive objects to Glacier Deep Archive for cost optimization.

**VPC and VPC endpoints.** Lambdas that call the EHR API run in a VPC with private subnets that route traffic through a controlled egress path (PrivateLink to a cloud-hosted EHR, or a VPN/Direct Connect to an on-premises EHR system). VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, EventBridge, CloudWatch Logs, Bedrock, Comprehend Medical, and Transcribe keep AWS-internal traffic on the AWS backbone rather than traversing NAT and the public internet. Endpoint policies pin access to the specific resources the pipeline uses.

**SMART on FHIR launch, authorization, and session handling.** The demo hand-waves the SMART on FHIR launch. Production implements the full SMART App Launch flow with backend-services authentication for the dictation client app: the EHR launches the app with a launch parameter and an iss URL, the app exchanges these for an authorization code via the EHR's authorization endpoint, the app exchanges the code for an access token, and the access token authorizes the FHIR API calls during note creation and structured-field updates. The signing key for backend-services lives in Secrets Manager with rotation per the institutional cadence.

**Per-clinician adaptation pipeline.** The demo emits `clinician_correction` events to EventBridge but does not consume them. Production has a separate adaptation pipeline that aggregates corrections per clinician, updates the per-clinician custom vocabulary on a daily or weekly cadence, validates updates against a held-out evaluation set (so a single clinician's idiosyncratic corrections do not degrade their personal model), and optionally triggers SageMaker training jobs for per-clinician acoustic-model adaptation when the institution chooses to operate that pipeline. The adaptation cadence is documented; the validation gates are explicit; the rollback path for a bad adaptation is tested.

**Critical-error detection ownership.** The demo's `detect_critical_errors` uses a small literal-pair set. Production's critical-error rules are owned by the clinical-quality officer (or equivalent role), reviewed quarterly, and versioned. The detection runs both on the rule-based critical-error pairs and on a model-based check that catches semantic drift the literal-pair check misses. Surfaces in the review pane with explicit clinician confirmation required; tracks aggregate detection rates and drift over time. Alarms when the detection rate spikes (suggesting either a new failure mode or an upstream model regression).

**Subgroup-stratified accuracy monitoring with disparity alerts.** The demo emits CloudWatch metrics with `specialty` and `clinician_id` dimensions. Production additionally stratifies by clinician dimensions (per-clinician accuracy, per-clinician language background where it can be inferred, per-clinician ASR confidence distribution) so the equity-monitoring committee can detect disparities. Disparities exceeding configured thresholds alert. Voice ASR systematically underperforms for some speaker demographics; the monitoring is the institution's mechanism for detecting whether the system is silently underserving specific clinicians.

**LLM-formatter faithfulness program.** The demo's runtime faithfulness check is the first line of defense. Production additionally maintains an offline evaluation set of verbatim-and-faithful-formatted note pairs across specialties, runs the formatter against the evaluation set on every model and prompt update, classifies regressions by clinical-impact tier, and gates production model updates on regression results. The offline program is the second line of defense and the structural mechanism for catching faithfulness drift before it reaches clinicians.

**Specialty-specific tuning programs.** The demo handles a single primary-care template. Production maintains per-specialty configurations (radiology, cardiology, neurology, oncology, urology, emergency medicine, psychiatry, primary care) with per-specialty templates, per-specialty custom vocabularies, per-specialty LLM prompts, and per-specialty critical-error rules. Pilots and rollouts happen per specialty.

**EHR integration depth and breadth.** The demo handles note creation and basic medication and condition writes. Production handles more: co-signature workflows for trainees (the trainee dictates, the attending signs, both signatures captured), late-addendum support (a separate signed document linked to the original; the original note is never modified), integration with order entry (a dictated medication suggestion drafts a CPOE order for separate clinician review and signature), integration with billing-code suggestion engines, and handling of vendor-specific extensions for the institution's EHR. The same explicit-confirmation rigor applies to every structured write.

**Audio retention policy with privacy-officer review.** The demo retains audio in a mock S3 store with no lifecycle. Production deployment requires explicit privacy-officer review of the retention duration, the access controls on retained audio, the consent disclosure to clinicians (whose voice biometric data is being retained), and the deletion verification. The default is conservative (a few days for QA review, then automatic deletion); longer retention requires explicit consent and an operational purpose.

**Disaster recovery and partial-failure handling.** The demo assumes happy-path execution. Production tests the failure modes in a staging environment quarterly: Transcribe Medical unavailable (fall back to the clinician retrying or typing), Bedrock unavailable (fall back to rule-based formatting only), Comprehend Medical unavailable (skip structured-field extraction; surface the gap to the clinician), EHR API unreachable (hold the signed note in a queue with manual replay). The clinician should never lose dictated audio because of a downstream component failure; the audio archive is the safety net.

**Idempotency and retry semantics.** The demo's idempotency check is a transcript-hash lookup in a window. Production uses a conditional DynamoDB write keyed on `(clinician_id, session_id, transcript_hash)` so a duplicate dictation submission (network blip, double click) is rejected with `ConditionalCheckFailedException` rather than producing two notes. Configure DLQs on every Lambda; alarm on DLQ depth.

**Performance under load and burst.** The latency budget for streaming dictation is tight; the system must hold the budget under load. Transcribe Medical streaming session limits, Bedrock invocation throughput per inference profile, Comprehend Medical inference rates, and EHR API rate limits all need provisioning headroom. Load test before launch; reserve concurrency where the latency-sensitive Lambdas would otherwise be starved.

**Vendor evaluation rigor for build-vs-buy decisions.** Most institutions deploying medical dictation should be buying a commercial product (Nuance Dragon Medical, M-Modal/3M, vendor-bundled offerings from Epic and Cerner) rather than building one. The demo's pipeline is the architecture for the careful-custom-build path. The vendor evaluation program runs in parallel: per-specialty accuracy benchmarking against held-out audio, evaluation of the read-edit-sign workflow, evaluation of the custom-vocabulary management, evaluation of the EHR integration depth, and reference checks with comparable institutions. A custom build that cannot match the major commercial vendors on these axes is the wrong call.

**Audit log retention and legal hold.** The demo's audit-archive S3 bucket is created without Object Lock in the mock. Production enables Object Lock in compliance mode with retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, the EHR vendor's audit-retention floor, and the institutional regulatory floor. Legal hold capabilities (suspending deletion for specific clinicians or patients during litigation) are configurable.

**Cost monitoring per clinician and per specialty.** Different clinicians use the system at very different rates; different specialties have very different per-note costs (a radiologist dictating fifty reports a day is structurally different from a primary-care physician dictating fifteen). Per-clinician and per-specialty cost dashboards let operations identify outliers and tune accordingly.

**Microphone hardware and clinician training.** Both are operational scope outside the engineering pipeline but determine whether the deployment succeeds. Adequate microphone hardware (close-talking headsets in noisy environments, beamforming workstation mics for general use, handheld dictation mics for radiologists and pathologists who prefer them) yields more accuracy improvement than the same investment in the model layer. Structured clinician training, on-call support during early use, and per-specialty rollout playbooks are the difference between sustained adoption and gradual abandonment.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the punctuation-and-capitalization logic with edge cases (medical abbreviations, sentence-boundary detection), unit tests for the number-canonicalization patterns, unit tests for the command-versus-content disambiguation, unit tests for the critical-error detection rules, integration tests against test buckets and tables, and end-to-end tests that simulate full dictation flows including the faithfulness-fail and critical-error paths. Never use real clinician audio or real patient data in test fixtures; use synthetic Synthea patients and TTS-generated audio with known ground truth.

**Observability beyond the metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-stage investigation. Production runs CloudWatch Logs Insights queries that join across the audio-stream-handler logs, the formatter logs, the structured-field-extractor logs, and the EHR-handoff logs by session_id. AWS X-Ray traces show the latency contribution of each stage. When a single dictation goes wrong (a critical-error alert fires, a faithfulness check fails, an EHR handoff stalls), the on-call engineer needs to reconstruct the full trace in seconds.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 10.4: Medical Transcription (Dictation)](chapter10.04-medical-transcription-dictation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
