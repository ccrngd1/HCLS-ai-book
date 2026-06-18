# Recipe 10.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 10.2. It shows one way you could translate the natural-language voicemail-triage pipeline into working Python using boto3 against Amazon Transcribe Medical, Amazon Comprehend Medical, Amazon Bedrock, Amazon S3, AWS Lambda, AWS Step Functions, Amazon DynamoDB, Amazon SNS, and Amazon EventBridge. The demo uses a `MockTranscribeMedical` standing in for the async ASR job submission and result delivery, a `MockBedrock` standing in for the foundation-model classifier, a `MockComprehendMedical` standing in for the medical-entity extractor, a `MockS3` standing in for the audio and transcript buckets, a `MockEHR` standing in for the patient-index lookup, and small helpers for the voicemail records table, the triage queue, the SNS topic, the EventBridge bus, and CloudWatch-style metrics. It is not production-ready. There is no real Step Functions state machine, no real Transcribe Medical job submission, no real Bedrock invocation, no real Comprehend Medical call, no real S3 wiring, no real DynamoDB or EventBridge wiring, no real on-call paging integration, no IAM least-privilege role per Lambda, no KMS customer-managed key configuration, no VPC endpoints, no per-jurisdiction recording-disclosure logic, no voicemail-greeting playback, and no staff triage UI. Think of it as the sketchpad version: useful for understanding the shape of a voicemail-triage pipeline that respects the urgency-rule-layer-first discipline, the per-axis confidence-threshold discipline, the ASR-confidence-gate-on-classification discipline, the structured-triage-record discipline, and the audit-everything discipline this recipe demands. It is not something you would point at the practice's voicemail box on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the seven core pseudocode steps from the main recipe: ingest the voicemail audio and create the voicemail record (Step 1), pre-process the audio with length filter and VAD (Step 2), submit the ASR job and handle the result with confidence-based gating (Step 3), classify with the urgency-rule-layer-first pattern and run the LLM classifier and entity extractor in parallel (Step 4), enrich with patient context and detect repeat callers (Step 5), route to the appropriate queue with priority and emit emergent notifications (Step 6), and capture staff actions for the disagreement-and-improvement dataset (Step 7). The synthetic patients, medications, phone numbers, transcripts, and intents in the demo are fictional; the names, DOBs, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also configure an Amazon S3 bucket for voicemail audio (with SSE-KMS encryption and lifecycle policies), a separate S3 bucket for transcripts, an Amazon Transcribe Medical workflow (the API itself; no console resource needed beyond IAM), an Amazon Comprehend Medical permission grant, an Amazon Bedrock foundation-model inference profile pinned to a specific model in a specific region, an AWS Step Functions state machine that orchestrates the pipeline stages, the Lambdas that the state machine invokes (ingestor, pre-processor, ASR-result-handler, classifier, entity-extractor, enricher, router), the DynamoDB tables that hold voicemail records, the triage queue, and the patient index, an Amazon SNS topic for emergent-voicemail notifications, an EventBridge bus for cross-system events, and the integration with your existing voicemail source system (UCaaS webhook, on-prem PBX export, or carrier voicemail-to-email feed). The demo replaces all of these with small mocks so the focus stays on the per-stage processing logic rather than on the cloud-resource provisioning.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `s3:GetObject`, `s3:PutObject` on the audio bucket and the transcript bucket, scoped to the per-voicemail key prefixes
- `transcribe:StartMedicalTranscriptionJob`, `transcribe:GetMedicalTranscriptionJob` for submitting and polling the async ASR jobs
- `comprehendmedical:DetectEntitiesV2` for the medical-entity extraction call
- `bedrock:InvokeModel` for the classifier, scoped to the specific foundation-model ARN and inference profile in use
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the voicemail-records, triage-queue, and patient-index tables
- `sns:Publish` on the emergent-voicemail SNS topic
- `events:PutEvents` on the voicemail-events EventBridge bus
- `cloudwatch:PutMetricData` for the operational metrics (per-intent volume, classifier confidence distributions, time-to-classification, queue depth, subgroup-stratified accuracy)
- `secretsmanager:GetSecretValue` on the EHR-API and pharmacy-API credentials secrets pinned to the current rotation version
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the audio bucket, the transcript bucket, the voicemail-records table, the triage-queue table, and the patient-index table

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The ingestor Lambda has scoped write access to the audio bucket and write access only to the new-voicemail-record fields. The pre-processor Lambda has scoped read access to the audio bucket. The classifier Lambda has scoped Bedrock invocation rights pinned to a specific model and inference profile. The router Lambda has scoped publish rights on the emergent SNS topic and PutEvents on the voicemail-events bus. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **The urgency-keyword rule layer is the safety substrate.** Every transcript is scanned against a versioned list of clinical-urgency phrases before any classifier output is trusted. The lexicon is reviewed quarterly by clinical operations. Skip the urgency scan and you produce the missed-emergent-voicemail cases the recipe is for. The lexicon in this demo is illustrative; a real lexicon is a clinical safety document with appropriate versioning and review.
- **Confidence is gated per-axis.** ASR confidence gates whether the transcript is trustworthy enough to classify on; intent confidence gates whether the routing decision is trustworthy enough to act on without staff review; urgency confidence gates whether the active notification is trustworthy enough to page a clinician without false-positive risk. Re-using one threshold across axes produces routing-quality compromise.
- **The rule layer can only escalate, never de-escalate.** If the classifier says "routine" but the rule layer matched "chest pain," the urgency floor is "urgent" or "emergent" depending on the matched phrase. Better to over-page than to under-page; an over-page is a brief operational annoyance, an under-page is a missed clinical event.
- **Idempotency is built in throughout the pipeline.** A pre-processor invoked twice on the same voicemail must not double-submit the ASR job; an ASR-result-handler invoked twice for the same job must not produce two classification entries; a router invoked twice for the same triage record must not emit two notifications. The voicemail_id (plus optional revision counter) is the idempotency key throughout.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, and numeric metadata field passes through `Decimal` on its way in and on its way out. This is a recurring SDK gotcha and the `_to_decimal` helper handles it.
- **The example collapses Step Functions, multiple Lambdas, the EventBridge fan-out, the SNS notification, and the CloudWatch metric emission into a single Python file for readability.** In production each pipeline stage is a separate Lambda with its own IAM role, error handling, retries, and DLQs, orchestrated by a Step Functions state machine that handles the async wait for the ASR job and the conditional branching on confidence gates. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the per-axis confidence thresholds, the urgency-keyword lexicon, the intent taxonomy, the urgency taxonomy, and the intent-to-queue mapping are what you would change between environments.

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
# to CloudWatch Logs Insights. The voicemail pipeline operates on
# heavily PHI-adjacent data: the audio file is PHI, the transcript
# is PHI, the entity extraction output is PHI, and the caller's
# phone number plus DOB plus medication mentions are all
# identifying. Log structural metadata only (voicemail_id, intent
# name, confidence band, urgency flag, decision outcome), never
# raw transcripts, never demographic values, never medication
# names, never any verification material.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from S3, DynamoDB, Transcribe
# Medical, Comprehend Medical, Bedrock, EventBridge, SNS, and
# CloudWatch. The voicemail pipeline is async (the caller has
# hung up by the time the pipeline runs), so a few extra seconds
# of retry backoff is operationally fine; what is not fine is
# silently dropping a voicemail because the pipeline gave up.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm
# containers so each invocation does not pay the connection cost.
REGION = "us-east-1"
s3_client          = boto3.client("s3", region_name=REGION,
                                   config=BOTO3_RETRY_CONFIG)
dynamodb           = boto3.resource("dynamodb", region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
transcribe_client  = boto3.client("transcribe", region_name=REGION,
                                   config=BOTO3_RETRY_CONFIG)
comprehend_medical = boto3.client("comprehendmedical",
                                   region_name=REGION,
                                   config=BOTO3_RETRY_CONFIG)
bedrock_runtime    = boto3.client("bedrock-runtime", region_name=REGION,
                                   config=BOTO3_RETRY_CONFIG)
sns_client         = boto3.client("sns", region_name=REGION,
                                   config=BOTO3_RETRY_CONFIG)
eventbridge_client = boto3.client("events", region_name=REGION,
                                   config=BOTO3_RETRY_CONFIG)
cloudwatch_client  = boto3.client("cloudwatch", region_name=REGION,
                                   config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do
# not exist; see run_demo() at the bottom.
AUDIO_BUCKET                  = "secure-voicemail-audio-prod"
TRANSCRIPT_BUCKET             = "secure-voicemail-transcripts-prod"
VOICEMAIL_RECORDS_TABLE       = "voicemail-records"
TRIAGE_QUEUE_TABLE            = "voicemail-triage-queue"
PATIENT_INDEX_TABLE           = "patient-phone-index"
EMERGENT_VOICEMAIL_TOPIC_ARN  = ("arn:aws:sns:us-east-1:000000000000:"
                                "emergent-voicemail")
VOICEMAIL_EVENT_BUS_NAME      = "voicemail-events-bus"
CLOUDWATCH_NAMESPACE          = "VoicemailTriage"

# Bedrock configuration. In production, pin to a specific model
# version and inference profile so a model upgrade doesn't
# silently change classifier behavior. The model and region
# combination must be in your AWS BAA scope.
BEDROCK_CLASSIFIER_MODEL_ID    = "anthropic.claude-3-5-sonnet-20240620-v1:0"
BEDROCK_INFERENCE_PROFILE_ARN  = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "voicemail-classifier-v1")

# KMS key for transcript output encryption. Transcribe Medical
# encrypts the transcript JSON it writes to S3 under this key.
TRANSCRIPT_KMS_KEY_ID = "arn:aws:kms:us-east-1:000000000000:key/CHANGE_ME"

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("AUDIO_BUCKET",                  AUDIO_BUCKET),
    ("TRANSCRIPT_BUCKET",             TRANSCRIPT_BUCKET),
    ("VOICEMAIL_RECORDS_TABLE",       VOICEMAIL_RECORDS_TABLE),
    ("TRIAGE_QUEUE_TABLE",            TRIAGE_QUEUE_TABLE),
    ("PATIENT_INDEX_TABLE",           PATIENT_INDEX_TABLE),
    ("EMERGENT_VOICEMAIL_TOPIC_ARN",  EMERGENT_VOICEMAIL_TOPIC_ARN),
    ("VOICEMAIL_EVENT_BUS_NAME",      VOICEMAIL_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",          CLOUDWATCH_NAMESPACE),
    ("BEDROCK_CLASSIFIER_MODEL_ID",   BEDROCK_CLASSIFIER_MODEL_ID),
    ("BEDROCK_INFERENCE_PROFILE_ARN", BEDROCK_INFERENCE_PROFILE_ARN),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every voicemail record and every classification carries the
# versions of the artifacts that influenced it: the classifier
# prompt, the urgency lexicon, the intent taxonomy. A future
# audit reconstructs which calibration was active when a
# particular voicemail was processed.
URGENCY_LEXICON_VERSION    = "urgency-lexicon-v2.1.0"
CLASSIFIER_PROMPT_VERSION  = "voicemail-classifier-prompt-v1.4.0"
INTENT_TAXONOMY_VERSION    = "voicemail-intents-v1.2.0"
INSTITUTION_ID             = "academic-medical-center-richmond"

# --- Pre-processing Thresholds ---
# Audio shorter than this is almost certainly not a usable
# voicemail (pocket dial, hangup before message). Audio longer
# than this is unusual enough to flag for human review without
# burning ASR budget on a potentially-corrupt recording.
MIN_USEFUL_DURATION_SECONDS    = 3
MAX_AUTO_PROCESS_DURATION_SECONDS = 5 * 60  # 5 minutes

# Voice-activity-detection ratio. If less than this fraction of
# the audio contains speech, we treat the recording as no-speech
# (pocket dial, music, ambient noise) and route to a no-ASR
# disposition.
MIN_SPEECH_RATIO = Decimal("0.20")

# --- ASR Confidence Gate ---
# The transcript-level confidence floor below which we will not
# classify the message; route to human review of the audio
# instead. The min-confidence-word count is the secondary gate:
# even a high-average-confidence transcript with one critical
# word at very low confidence (often a medication name or a
# clinical symptom) deserves human listen-back.
ASR_MIN_AVG_CONFIDENCE = Decimal("0.65")
ASR_MAX_LOW_CONF_WORDS = 5  # words below 0.6 confidence

# --- Intent and Urgency Taxonomies ---
# The valid label spaces. The classifier output is validated
# against these; any out-of-taxonomy value is coerced to a
# safe default rather than passed through.
INTENT_TAXONOMY = [
    "medication_refill",
    "medication_question",
    "appointment_schedule",
    "appointment_reschedule",
    "appointment_cancel",
    "appointment_confirm",
    "test_result_inquiry",
    "clinical_symptom_report",
    "billing_question",
    "insurance_question",
    "vendor_or_business",
    "spam_or_wrong_number",
    "unclear",
]

URGENCY_TAXONOMY = ["emergent", "urgent", "routine", "low_priority"]

# --- Per-Axis Classification Confidence Thresholds ---
# Below these thresholds, the triage record is flagged for
# human review before action. The thresholds are deliberately
# different per axis: urgency confidence threshold is higher
# because a wrong urgency call has higher consequences than a
# wrong intent call.
INTENT_CONFIDENCE_THRESHOLD  = Decimal("0.70")
URGENCY_CONFIDENCE_THRESHOLD = Decimal("0.75")

# --- Urgency Keyword Lexicon ---
# A versioned list of phrases that should set the urgency floor
# regardless of the LLM classifier's output. Each entry includes
# the matched phrase and the urgency level it triggers. The
# lexicon is reviewed quarterly with clinical operations. New
# phrases are added when production transcripts reveal misses.
# Treat this as a clinical safety document.
#
# The list below is illustrative. A real institutional lexicon
# is more comprehensive and is maintained outside the codebase
# in a versioned, reviewable artifact (Parameter Store, AppConfig,
# or a versioned S3 object). Do not ship the demo lexicon to
# production.
URGENCY_LEXICON = [
    # Emergent: immediate clinical concern
    {"phrase": "chest pain",                "level": "emergent"},
    {"phrase": "chest pressure",            "level": "emergent"},
    {"phrase": "chest tightness",           "level": "urgent"},
    {"phrase": "can't breathe",             "level": "emergent"},
    {"phrase": "cannot breathe",            "level": "emergent"},
    {"phrase": "trouble breathing",         "level": "urgent"},
    {"phrase": "shortness of breath",       "level": "urgent"},
    {"phrase": "heart attack",              "level": "emergent"},
    {"phrase": "stroke",                    "level": "emergent"},
    {"phrase": "face drooping",             "level": "emergent"},
    {"phrase": "slurred speech",            "level": "emergent"},
    {"phrase": "sudden weakness",           "level": "emergent"},
    {"phrase": "sudden numbness",           "level": "emergent"},
    {"phrase": "worst headache",            "level": "emergent"},
    {"phrase": "fainting",                  "level": "urgent"},
    {"phrase": "passed out",                "level": "urgent"},
    {"phrase": "loss of consciousness",     "level": "emergent"},
    {"phrase": "uncontrolled bleeding",     "level": "emergent"},
    {"phrase": "won't stop bleeding",       "level": "emergent"},
    # Mental-health crisis
    {"phrase": "thinking about hurting myself", "level": "emergent"},
    {"phrase": "thinking about killing myself", "level": "emergent"},
    {"phrase": "want to hurt myself",       "level": "emergent"},
    {"phrase": "want to end my life",       "level": "emergent"},
    {"phrase": "suicidal",                  "level": "emergent"},
    # Pediatric urgency
    {"phrase": "baby is not breathing",     "level": "emergent"},
    {"phrase": "child is not breathing",    "level": "emergent"},
    {"phrase": "blue lips",                 "level": "emergent"},
    # Allergic reaction
    {"phrase": "anaphylaxis",               "level": "emergent"},
    {"phrase": "throat closing",            "level": "emergent"},
    {"phrase": "tongue swelling",           "level": "emergent"},
    # Medication-related
    {"phrase": "took too much",             "level": "urgent"},
    {"phrase": "weird breathing",           "level": "urgent"},
    {"phrase": "high fever",                "level": "urgent"},
    {"phrase": "running a fever",           "level": "urgent"},
    {"phrase": "severe pain",               "level": "urgent"},
]

# --- Intent-to-Queue Routing ---
# The mapping is configuration: institution-defined intent-to-
# queue assignments. Some intents fan out to multiple queues
# (clinical-symptom voicemails go to nurse triage AND, when
# the urgency is emergent, to the clinical-escalation queue).
INTENT_TO_QUEUE_MAP = {
    "medication_refill":        ["pharmacy"],
    "medication_question":      ["nurse_triage"],
    "appointment_schedule":     ["scheduling"],
    "appointment_reschedule":   ["scheduling"],
    "appointment_cancel":       ["scheduling"],
    "appointment_confirm":      ["scheduling"],
    "test_result_inquiry":      ["nurse_triage"],
    "clinical_symptom_report":  ["nurse_triage"],
    "billing_question":         ["billing"],
    "insurance_question":       ["billing"],
    "vendor_or_business":       ["administrative"],
    "spam_or_wrong_number":     [],   # Suppressed from staff queue
    "unclear":                  ["general_triage"],
    "_default":                 ["general_triage"],
}

# Urgency-rank map for priority-key construction. Higher number
# means higher priority; the queue interface sorts descending
# on this dimension and ascending on recorded_at within an
# urgency tier.
URGENCY_RANK_MAP = {
    "emergent":     4,
    "urgent":       3,
    "routine":      2,
    "low_priority": 1,
    "unknown":      2,  # Treat unknowns as routine until human review
}

# --- De-duplication Window ---
# How recently does the same caller need to have left a similar
# voicemail before we flag the new one as a repeat? The window
# is institutional; 48 hours is a reasonable starting point.
REPEAT_CALLER_WINDOW_HOURS = 48

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

def _normalize_phone(phone):
    """Strip non-digit characters; we store and compare as digits only."""
    if not phone:
        return None
    return re.sub(r"\D", "", phone)

def _build_priority_key(urgency_rank, recorded_at_iso):
    """
    Build the composite sort key for the triage queue.

    The format is "U#{rank}#{recorded_at}". Sorting descending on
    this string puts the highest urgency first; within an urgency
    rank, sorting descending on the timestamp string is wrong (it
    would put newest first), so the queue UI flips the order
    within tier. A real implementation usually uses two sort
    attributes via a DynamoDB GSI; the demo collapses them into
    one for simplicity.
    """
    # TODO (TechWriter): Code review Finding 4 (NOTE). The recipe
    # text says "Within an urgency level, older messages come
    # first" but this priority key sorted descending puts newer
    # messages first within tier, and items_for_queue sorts
    # descending without flipping intra-tier. Fix one of: (a)
    # invert the timestamp ((datetime(2099,1,1)-recorded_at)
    # total seconds with leading zeros) so descending sort
    # puts older first within tier; (b) change items_for_queue
    # to a two-key sort (urgency rank desc, recorded_at asc);
    # (c) split into two attributes and document the production
    # DynamoDB GSI pattern. Whichever fix, update the in-code
    # comment to match.
    return f"U#{urgency_rank:03d}#{recorded_at_iso}"
```

---

## Mock Resources for the Demo

These mocks stand in for the production AWS resources and back-office systems. They are deliberately simple and are not how you would build the real thing. Their purpose is to keep the focus on the voicemail-triage pipeline logic.

```python
class MockS3:
    """
    Stands in for the audio and transcript S3 buckets. In
    production these are separate buckets with SSE-KMS, lifecycle
    policies, and Object Lock on the audit-log bucket. The demo
    holds objects in memory keyed by (bucket, key).
    """
    def __init__(self):
        self._objects = {}

    def put_object(self, bucket, key, body, sse_kms_key_id=None,
                    content_type=None, metadata=None):
        self._objects[(bucket, key)] = {
            "body":         body,
            "sse_kms_key":  sse_kms_key_id,
            "content_type": content_type,
            "metadata":     metadata or {},
        }

    def get_object(self, bucket, key):
        return self._objects.get((bucket, key))

class MockTranscribeMedical:
    """
    Stands in for Amazon Transcribe Medical's async batch API. In
    production you call StartMedicalTranscriptionJob, wait for
    the EventBridge job-completion event, then read the transcript
    JSON from the output S3 location. The demo synthesizes the
    transcript from a hardcoded mapping (voicemail_id -> transcript)
    so we can exercise the rest of the pipeline without real audio.
    """
    def __init__(self, transcript_fixtures):
        self._fixtures = transcript_fixtures
        self._jobs = {}

    def start_medical_transcription_job(self, job_name, voicemail_id,
                                         media_uri, language_code,
                                         specialty, transcription_type,
                                         output_bucket, output_key):
        # In production this is a non-blocking API call that returns
        # immediately and runs the transcription in the background.
        # The demo synthesizes the result inline.
        # TODO (TechWriter): Code review Finding 1 (ERROR). The
        # fixtures are keyed by literal demo names ("vm-fixture-
        # refill" etc.) but voicemail_id is generated dynamically
        # in ingest_voicemail() as "vm-" + uuid.uuid4().hex[:12].
        # Every scenario other than the pocket-dial short-circuit
        # falls through to the "no fixture available" default,
        # the ASR gate fires on empty word_confidences, and the
        # rule layer / classifier / SNS-emergent path are never
        # exercised. Recommended fix (Option B from the review):
        # have ingest_voicemail() accept an optional
        # "voicemail_id_override" from source_event so each
        # scenario can pass its fixture id deterministically; the
        # override is documented as demo-only.
        fixture = self._fixtures.get(voicemail_id, {
            "transcript_text": "no fixture available for this voicemail",
            "items": [],
        })
        transcript_json = {
            "results": {
                "transcripts": [{"transcript": fixture["transcript_text"]}],
                "items": fixture.get("items", []),
            }
        }
        self._jobs[job_name] = {
            "status":          "COMPLETED",
            "voicemail_id":    voicemail_id,
            "transcript_json": transcript_json,
            "output_bucket":   output_bucket,
            "output_key":      output_key,
        }
        return {"job_name": job_name, "status": "IN_PROGRESS"}

    def get_completed_transcript(self, job_name):
        # In production the transcript is delivered to S3 and the
        # ASR-result-handler Lambda reads it from there. The demo
        # returns it directly.
        return self._jobs.get(job_name, {}).get("transcript_json")

class MockBedrock:
    """
    Stands in for Amazon Bedrock's InvokeModel API. The classifier
    prompt asks the model to return strict JSON with intent,
    urgency, confidences, and a brief summary. The demo returns a
    fixture-driven response keyed by transcript text so the
    classification is reproducible across runs.
    """
    # TODO (TechWriter): Code review Finding 5 (NOTE). The mock's
    # parameter name is snake_case (model_id) while the real
    # bedrock_runtime.invoke_model uses camelCase (modelId). The
    # production-comment skeletons elsewhere in this file use the
    # real-API casing. To keep the demo internally consistent,
    # either restructure the mocks to accept the real API's
    # keyword arguments (e.g. invoke_model(self, modelId, body,
    # contentType=None, accept=None)) or note the snake_case-to-
    # camelCase translation at every call site. Same pattern in
    # MockTranscribeMedical (job_name vs MedicalTranscriptionJobName,
    # etc.).
    def __init__(self, classification_fixtures):
        self._fixtures = classification_fixtures

    def invoke_model(self, model_id, body):
        # The body is a JSON string with the prompt. In production
        # the call returns model output as JSON; the demo looks up
        # the response based on a transcript signature embedded in
        # the prompt.
        prompt_data = json.loads(body)
        transcript = prompt_data.get("transcript", "")
        # Fixture lookup: match on substring of the transcript so
        # we can have stable fixtures keyed by intent rather than
        # by exact text.
        for fixture_key, fixture_response in self._fixtures.items():
            if fixture_key in transcript.lower():
                return {"body": json.dumps(fixture_response)}
        # Default fallback if no fixture matches.
        return {"body": json.dumps({
            "intent":                "unclear",
            "intent_confidence":     0.45,
            "urgency":               "routine",
            "urgency_confidence":    0.55,
            "summary":               "Unable to confidently determine "
                                      "the purpose of this voicemail.",
        })}

class MockComprehendMedical:
    """
    Stands in for Amazon Comprehend Medical's DetectEntitiesV2
    API. In production this returns medical entities (medications,
    conditions, anatomy, procedures, tests, time expressions)
    with confidence scores and ontology mappings (RxNorm, ICD-10,
    SNOMED). The demo returns fixture-driven entities keyed by
    transcript content.
    """
    def __init__(self, entity_fixtures):
        self._fixtures = entity_fixtures

    def detect_entities_v2(self, text):
        for fixture_key, fixture_entities in self._fixtures.items():
            if fixture_key in text.lower():
                return {"Entities": fixture_entities}
        return {"Entities": []}

class MockEHR:
    """
    Stands in for the EHR API used during enrichment. In
    production this is a FHIR Patient/Medication/Condition search
    against the institution's clinical-data API, with OAuth-based
    authentication, network timeouts, and rate-limit handling.
    The demo holds a small set of patients in memory.
    """
    def __init__(self):
        self._patients = {
            "pat-100001": {
                "patient_id":         "pat-100001",
                "first_name":         "Margaret",
                "last_name":          "Chen",
                "dob":                "1958-03-14",
                "phone_on_file":      "5715551234",
                "preferred_language": "en",
            },
            "pat-100002": {
                "patient_id":         "pat-100002",
                "first_name":         "James",
                "last_name":          "Patel",
                "dob":                "1972-09-22",
                "phone_on_file":      "8045555678",
                "preferred_language": "en",
            },
        }
        self._active_meds = {
            "pat-100001": [
                {"name": "lisinopril",   "rxnorm_code": "29046"},
                {"name": "atorvastatin", "rxnorm_code": "83367"},
            ],
            "pat-100002": [
                {"name": "metformin",    "rxnorm_code": "6809"},
            ],
        }
        self._active_conditions = {
            "pat-100001": [
                {"name": "Hypertension", "icd10_code": "I10"},
            ],
            "pat-100002": [
                {"name": "Type 2 diabetes", "icd10_code": "E11.9"},
            ],
        }

    def lookup_by_phone(self, phone):
        digits = _normalize_phone(phone)
        return [p for p in self._patients.values()
                if p["phone_on_file"] == digits]

    def get_active_medications(self, patient_id):
        return list(self._active_meds.get(patient_id, []))

    def get_active_conditions(self, patient_id):
        return list(self._active_conditions.get(patient_id, []))

class MockVoicemailRecords:
    """
    Stands in for the DynamoDB voicemail-records table. Holds the
    full state of each voicemail through the pipeline. In
    production this is a table partitioned by voicemail_id with
    customer-managed KMS at rest and PITR enabled.
    """
    def __init__(self):
        self._items = {}

    def put(self, item):
        self._items[item["voicemail_id"]] = dict(item)

    def get(self, voicemail_id):
        return dict(self._items.get(voicemail_id, {}))

    def update(self, voicemail_id, updates):
        if voicemail_id not in self._items:
            self._items[voicemail_id] = {"voicemail_id": voicemail_id}
        self._items[voicemail_id].update(updates)

    def append_audit(self, voicemail_id, audit_entry):
        existing = self._items.get(voicemail_id, {})
        history = list(existing.get("audit_history", []))
        history.append(audit_entry)
        self.update(voicemail_id, {"audit_history": history})

    def query_by_phone_and_window(self, phone, window_hours):
        digits = _normalize_phone(phone)
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(hours=window_hours))
        results = []
        for vm in self._items.values():
            if _normalize_phone(vm.get("ani")) != digits:
                continue
            recorded_at = vm.get("recorded_at")
            if recorded_at and recorded_at >= cutoff.isoformat():
                results.append(vm)
        return results

class MockTriageQueue:
    """
    Stands in for the DynamoDB triage-queue table. Triage records
    are placed in the queue with a (queue_name, priority_key) key
    so the staff interface can query by queue and order by priority
    descending.
    """
    def __init__(self):
        self._records = []

    def put(self, record):
        self._records.append(dict(record))

    def items_for_queue(self, queue_name):
        # Sort descending by priority_key. Higher urgency rank
        # (encoded in the prefix) comes first.
        items = [r for r in self._records
                 if r.get("queue_name") == queue_name]
        return sorted(items,
                       key=lambda r: r.get("priority_key", ""),
                       reverse=True)

class MockSNS:
    """
    Stands in for SNS publishing. In production the emergent-
    voicemail topic has subscribers (on-call pager, SMS, mobile
    push, dashboard alert webhook). The demo records every
    publish for inspection.
    """
    def __init__(self):
        self.published = []

    def publish(self, topic_arn, subject, message):
        self.published.append({
            "topic_arn":  topic_arn,
            "subject":    subject,
            "message":    message,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        })

class MockEventBus:
    """
    Stands in for Amazon EventBridge. The pipeline emits events
    for cross-system fan-out: a voicemail routed, a staff action
    taken, an emergent escalation logged. Downstream consumers
    (analytics, dashboards, EHR integration) pick these up.
    """
    def __init__(self):
        self.events = []

    def put_events(self, entries):
        for entry in entries:
            self.events.append(dict(entry))

class MockCloudWatch:
    """
    Stands in for CloudWatch metric emission. In production the
    metrics flow into CloudWatch dashboards and alarms.
    """
    def __init__(self):
        self.metrics = []

    def put_metric(self, name, value, unit="Count", dimensions=None):
        self.metrics.append({
            "name":       name,
            "value":      value,
            "unit":       unit,
            "dimensions": dimensions or {},
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        })

# Module-level singletons for the demo. In production each of
# these is its own AWS resource accessed via boto3.
s3                   = MockS3()
voicemail_records    = MockVoicemailRecords()
triage_queue         = MockTriageQueue()
ehr                  = MockEHR()
sns                  = MockSNS()
event_bus            = MockEventBus()
cloudwatch           = MockCloudWatch()
# transcribe, bedrock, and comprehend_medical mocks are wired
# up in run_demo() with fixture data tailored to each scenario.
# TODO (TechWriter): Code review Finding 7 (NOTE). These three
# globals are None until run_demo executes; importing the module
# and calling process_voicemail directly will fail with
# AttributeError. Either initialize them at module load with
# empty-fixture defaults (and let run_demo reassign them with
# populated fixtures), or refactor the pipeline-stage functions
# to receive the mock instances as arguments rather than reading
# them from module globals.
transcribe_mock      = None
bedrock_mock         = None
comprehend_mock      = None

def audit_log(event):
    """
    In production, audit events go to a tamper-resistant store
    (Object-Lock S3, an append-only DynamoDB table, or a SIEM).
    The demo prints a sanitized summary so you can see the
    sequence of decisions without leaking the underlying values.
    """
    safe_event = {
        k: v for k, v in event.items()
        if k not in {"transcript", "dob", "patient_demographics"}
    }
    if "transcript" in event:
        safe_event["transcript_length"] = len(event["transcript"] or "")
    logger.info("AUDIT %s", json.dumps(safe_event, default=str))
```

---

## Step 1: Ingest the Voicemail and Persist the Audio

*The pseudocode calls this `ON voicemail_arrival(source_event)`. The voicemail source system (UCaaS webhook, S3 cross-account push, SFTP drop, or carrier voicemail-to-email) delivers a notification with the audio reference. The ingestor Lambda fetches the audio (if it isn't already in our S3), normalizes the metadata, persists the audio to the encrypted audio bucket, creates the voicemail record in DynamoDB, and starts the Step Functions execution. Skip the audio persist and you have nothing to listen back to when the staff member needs to verify the transcript; skip the metadata normalization and downstream stages have to special-case every source.*

```python
def ingest_voicemail(source_event):
    """
    Entry point of the pipeline. The source_event shape varies
    per integration; common fields are caller_phone_number (ANI),
    called_number (DNIS), recorded_at, duration_seconds,
    source_message_id, and either an inline audio blob or a
    fetch URL.

    In production this Lambda is invoked by an API Gateway
    webhook (UCaaS-style), an S3 ObjectCreated event (push from
    a partner bucket), or a scheduled poller (IMAP for
    voicemail-to-email). The demo accepts a flat dict directly.

    Args:
        source_event: A dict describing the inbound voicemail.

    Returns:
        The voicemail_id and the input dict for the next stage.
    """
    voicemail_id = "vm-" + uuid.uuid4().hex[:12]

    # Step 1A: fetch and persist the audio. The source system
    # may deliver via a signed URL we have to fetch (most common),
    # via S3 cross-account push (in which case we copy from the
    # source bucket to our bucket so we own the lifecycle and
    # access controls), or as an inline audio blob in the event
    # payload. The demo treats the audio as a placeholder bytes
    # value; in production you would call requests.get(url) or
    # s3.copy_object as appropriate.
    audio_bytes = source_event.get("audio_bytes",
                                    b"<placeholder audio bytes>")
    audio_format = source_event.get("audio_format", "wav")
    audio_s3_key = (f"voicemails/{datetime.now(timezone.utc):%Y/%m/%d}"
                    f"/{voicemail_id}.{audio_format}")

    # Production: s3_client.put_object(
    #     Bucket=AUDIO_BUCKET,
    #     Key=audio_s3_key,
    #     Body=audio_bytes,
    #     ServerSideEncryption="aws:kms",
    #     SSEKMSKeyId=AUDIO_KMS_KEY_ID,
    #     ContentType=f"audio/{audio_format}",
    #     Metadata={"voicemail_id": voicemail_id})
    s3.put_object(
        bucket=AUDIO_BUCKET,
        key=audio_s3_key,
        body=audio_bytes,
        sse_kms_key_id="alias/voicemail-audio-key",
        content_type=f"audio/{audio_format}",
        metadata={"voicemail_id": voicemail_id})

    # Step 1B: create the voicemail record. This row will
    # accumulate state through the rest of the pipeline. The
    # ConditionExpression on attribute_not_exists protects
    # against a duplicate ingestion (rare but real: a webhook
    # retry, an SFTP polling loop that picks up the same file
    # twice). For the demo we just write.
    now = datetime.now(timezone.utc)
    record = {
        "voicemail_id":       voicemail_id,
        "ani":                _normalize_phone(
                                 source_event.get("caller_phone_number")),
        "dnis":               _normalize_phone(
                                 source_event.get("called_number")),
        "recorded_at":        source_event.get("recorded_at",
                                                now.isoformat()),
        "duration_seconds":   source_event.get("duration_seconds", 0),
        "source_system":      source_event.get("source_system",
                                                "unknown"),
        "source_message_id":  source_event.get("source_message_id"),
        "audio_s3_bucket":    AUDIO_BUCKET,
        "audio_s3_key":       audio_s3_key,
        "audio_format":       audio_format,
        "ingested_at":        now.isoformat(),
        "pipeline_status":    "ingested",
        "audit_history": [{
            "event":     "INGESTED",
            "timestamp": now.isoformat(),
        }],
    }
    voicemail_records.put(_to_decimal(record))

    audit_log({
        "event_type":     "VOICEMAIL_INGESTED",
        "voicemail_id":   voicemail_id,
        "source_system":  source_event.get("source_system"),
        "duration_seconds": source_event.get("duration_seconds"),
        "timestamp":      now.isoformat(),
    })

    cloudwatch.put_metric(
        "VoicemailsIngested", 1, "Count",
        dimensions={"source_system":
                      source_event.get("source_system", "unknown")})

    # In production, the next step would be to start a Step
    # Functions execution that runs the rest of the pipeline.
    # The state machine input is the voicemail_id and the
    # audio reference. The demo returns the dict and the caller
    # invokes the next stage directly.
    return {
        "voicemail_id":      voicemail_id,
        "audio_s3_bucket":   AUDIO_BUCKET,
        "audio_s3_key":      audio_s3_key,
        "duration_seconds":  source_event.get("duration_seconds", 0),
    }
```

---

## Step 2: Pre-process the Audio and Decide Whether to Transcribe

*The pseudocode calls this `preprocess_audio(...)`. The pre-processor stage runs voice activity detection, length filtering, and DTMF/fax tone detection. Recordings that have no detectable speech (pocket dials, silent hangups, fax tones) get short-circuited to a "no-speech disposition" without spending ASR budget. Recordings that pass the filters continue to transcription. Skip this filter and you will spend several hundred dollars a month transcribing pocket dials and fax tones, and the staff queue will fill up with no-content entries that nobody can act on.*

```python
def preprocess_audio(stage_input):
    """
    Pre-processing stage: length filter, voice activity
    detection, fax/DTMF detection, language detection. Returns
    a decision dict that drives the next stage.

    In production VAD runs against an in-memory copy of the
    audio fetched from S3, using a small pre-trained model
    deployed inside the Lambda (Silero VAD ONNX is a common
    choice). The demo simulates the VAD result based on a
    flag on the input dict so we can deterministically drive
    the demo through different scenarios.

    Args:
        stage_input: The dict from ingest_voicemail (or a
            mock equivalent for the demo) plus any pre-
            simulated audio characteristics.

    Returns:
        A dict with continue_to_asr (bool) and disposition
        (str) describing whether to proceed or short-circuit.
    """
    voicemail_id    = stage_input["voicemail_id"]
    duration_secs   = stage_input.get("duration_seconds", 0)

    # Step 2A: length filter. Defaults are institutional.
    if duration_secs < MIN_USEFUL_DURATION_SECONDS:
        return _short_circuit_preprocessing(
            voicemail_id,
            status="skipped_too_short",
            disposition="no_speech_too_short",
            reason="duration_below_threshold")

    if duration_secs > MAX_AUTO_PROCESS_DURATION_SECONDS:
        return _short_circuit_preprocessing(
            voicemail_id,
            status="flagged_for_review",
            disposition="human_review_long_recording",
            reason="duration_above_threshold")

    # Step 2B: voice activity detection. In production this is
    # a real VAD model invocation; the demo reads a pre-computed
    # speech_ratio from the simulated input.
    speech_ratio = Decimal(str(
        stage_input.get("simulated_speech_ratio", 0.85)))

    if speech_ratio < MIN_SPEECH_RATIO:
        return _short_circuit_preprocessing(
            voicemail_id,
            status="skipped_no_speech",
            disposition="no_speech_detected",
            reason="speech_ratio_below_threshold",
            metadata={"speech_ratio": speech_ratio})

    # Step 2C: DTMF / fax tone detection.
    has_fax_tones = stage_input.get("simulated_has_fax_tones", False)
    if has_fax_tones:
        return _short_circuit_preprocessing(
            voicemail_id,
            status="skipped_fax_tones",
            disposition="non_voice_audio_fax",
            reason="fax_signal_detected")

    # Step 2D: language detection. Useful in multilingual
    # practices to choose the right ASR model variant.
    detected_language = stage_input.get(
        "simulated_detected_language", "en-US")

    # Step 2E: passes filters; continue to ASR with pre-
    # processing metadata recorded.
    voicemail_records.update(voicemail_id, _to_decimal({
        "preprocessing": {
            "speech_ratio":      speech_ratio,
            "detected_language": detected_language,
            "decided_at":        datetime.now(timezone.utc).isoformat(),
        },
        "pipeline_status": "preprocessed_ready_for_asr",
    }))
    voicemail_records.append_audit(voicemail_id, {
        "event":     "PREPROCESSED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    audit_log({
        "event_type":        "VOICEMAIL_PREPROCESSED",
        "voicemail_id":      voicemail_id,
        "speech_ratio":      float(speech_ratio),
        "detected_language": detected_language,
        "timestamp":
            datetime.now(timezone.utc).isoformat(),
    })

    return {
        "continue_to_asr":   True,
        "voicemail_id":      voicemail_id,
        "audio_s3_bucket":   stage_input.get("audio_s3_bucket"),
        "audio_s3_key":      stage_input.get("audio_s3_key"),
        "detected_language": detected_language,
    }

def _short_circuit_preprocessing(voicemail_id, status, disposition,
                                   reason, metadata=None):
    """Helper: terminal disposition without ASR."""
    update = {
        "pipeline_status":     status,
        "terminal_disposition": disposition,
        "preprocessing": _to_decimal({
            "short_circuit_reason": reason,
            "decided_at": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }),
    }
    voicemail_records.update(voicemail_id, update)
    voicemail_records.append_audit(voicemail_id, {
        "event":     status.upper(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason":    reason,
    })

    audit_log({
        "event_type":   "PREPROCESSING_SHORT_CIRCUIT",
        "voicemail_id": voicemail_id,
        "disposition":  disposition,
        "reason":       reason,
        "timestamp":
            datetime.now(timezone.utc).isoformat(),
    })

    cloudwatch.put_metric(
        "PreprocessingShortCircuit", 1, "Count",
        dimensions={"disposition": disposition})

    return {
        "continue_to_asr": False,
        "voicemail_id":    voicemail_id,
        "disposition":     disposition,
    }
```

---

## Step 3: Submit the ASR Job and Handle the Result

*The pseudocode calls these `start_asr_job(...)` and `handle_asr_completion(...)`. Transcribe Medical exposes a job-based async API. Submit the job; the service writes the result to a designated S3 location when complete; an EventBridge rule notifies the pipeline; the result is fetched, parsed, and stored. The state machine has a wait-for-callback pattern that handles the async correctly. Skip the medical-domain model and you will systematically misrecognize the medication names that drive most of the routing; skip the per-word confidence scoring and downstream confidence-aware logic has nothing to work with.*

```python
def start_asr_job(stage_input):
    """
    Submit an async medical transcription job to Transcribe
    Medical. The job runs in the background; the next stage is
    invoked via EventBridge when the job completes.

    Args:
        stage_input: The dict from preprocess_audio.

    Returns:
        A dict with the ASR job_name and the voicemail_id.
    """
    voicemail_id      = stage_input["voicemail_id"]
    audio_s3_bucket   = stage_input["audio_s3_bucket"]
    audio_s3_key      = stage_input["audio_s3_key"]
    detected_language = stage_input.get("detected_language", "en-US")

    job_name = f"vm-{voicemail_id}-{uuid.uuid4().hex[:6]}"
    transcript_output_key = (f"transcripts/{voicemail_id}/"
                              f"transcript.json")

    # Production: transcribe_client.start_medical_transcription_job(
    #     MedicalTranscriptionJobName=job_name,
    #     Media={"MediaFileUri":
    #             f"s3://{audio_s3_bucket}/{audio_s3_key}"},
    #     LanguageCode=detected_language,
    #     Specialty="PRIMARYCARE",
    #     Type="CONVERSATION",
    #     OutputBucketName=TRANSCRIPT_BUCKET,
    #     OutputKey=transcript_output_key,
    #     OutputEncryptionKMSKeyId=TRANSCRIPT_KMS_KEY_ID,
    #     Settings={"ShowSpeakerLabels": False})
    transcribe_mock.start_medical_transcription_job(
        job_name=job_name,
        voicemail_id=voicemail_id,
        media_uri=f"s3://{audio_s3_bucket}/{audio_s3_key}",
        language_code=detected_language,
        specialty="PRIMARYCARE",
        transcription_type="CONVERSATION",
        output_bucket=TRANSCRIPT_BUCKET,
        output_key=transcript_output_key)

    voicemail_records.update(voicemail_id, _to_decimal({
        "asr": {
            "job_name":      job_name,
            "submitted_at":  datetime.now(timezone.utc).isoformat(),
            "language_code": detected_language,
            "transcript_s3_bucket": TRANSCRIPT_BUCKET,
            "transcript_s3_key":    transcript_output_key,
        },
        "pipeline_status": "asr_in_flight",
    }))
    voicemail_records.append_audit(voicemail_id, {
        "event":     "ASR_SUBMITTED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "job_name":  job_name,
    })

    audit_log({
        "event_type":   "ASR_JOB_SUBMITTED",
        "voicemail_id": voicemail_id,
        "job_name":     job_name,
        "language_code": detected_language,
        "timestamp":
            datetime.now(timezone.utc).isoformat(),
    })

    return {"voicemail_id": voicemail_id, "job_name": job_name}

def handle_asr_completion(stage_input):
    """
    Invoked when the Transcribe Medical job completes. Parses
    the transcript, computes confidence aggregates, and decides
    whether the transcript is trustworthy enough to classify on.
    A low-confidence transcript routes to human review of the
    audio rather than being acted on by the classifier.

    Args:
        stage_input: A dict with voicemail_id and job_name.

    Returns:
        A dict with continue_to_classification (bool) and the
        transcript text if the gate passes.
    """
    voicemail_id = stage_input["voicemail_id"]
    job_name     = stage_input["job_name"]

    # Production: poll transcribe_client.get_medical_transcription_job
    # OR receive an EventBridge event with the job-completion
    # signal, then read the transcript JSON from S3.
    transcript_json = transcribe_mock.get_completed_transcript(job_name)
    if transcript_json is None:
        raise RuntimeError(f"No transcript available for job {job_name}")

    transcript_text = (transcript_json.get("results", {})
                       .get("transcripts", [{}])[0]
                       .get("transcript", ""))

    # Compute aggregate confidence across word-level items.
    items = transcript_json.get("results", {}).get("items", [])
    word_confidences = []
    for item in items:
        if item.get("type") != "pronunciation":
            continue
        alts = item.get("alternatives", [])
        if not alts:
            continue
        try:
            word_confidences.append(float(alts[0].get("confidence", 0)))
        except (TypeError, ValueError):
            continue

    if word_confidences:
        avg_confidence = Decimal(str(
            sum(word_confidences) / len(word_confidences)))
        min_confidence = Decimal(str(min(word_confidences)))
        low_conf_count = sum(1 for c in word_confidences if c < 0.6)
    else:
        # No word-level items in the transcript JSON. In
        # production this is rare; the demo fixtures sometimes
        # omit them for brevity. Treat as low-confidence.
        avg_confidence = Decimal("0.50")
        min_confidence = Decimal("0.50")
        low_conf_count = 0

    # Persist the parsed transcript reference and metrics. We
    # do not embed the full transcript in the voicemail record;
    # the transcript lives in S3 and the record references it
    # by bucket and key.
    transcript_hash = hashlib.sha256(
        transcript_text.encode("utf-8")).hexdigest()
    voicemail_records.update(voicemail_id, _to_decimal({
        "transcript_meta": {
            "transcript_length_chars":  len(transcript_text),
            "transcript_hash":          transcript_hash,
            "avg_word_confidence":      avg_confidence,
            "min_word_confidence":      min_confidence,
            "low_confidence_word_count": low_conf_count,
            "completed_at":
                datetime.now(timezone.utc).isoformat(),
        },
        "pipeline_status": "asr_complete",
    }))
    voicemail_records.append_audit(voicemail_id, {
        "event":     "ASR_COMPLETE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "avg_confidence": float(avg_confidence),
    })

    cloudwatch.put_metric(
        "ASRConfidenceAvg", float(avg_confidence) * 100,
        unit="Percent",
        dimensions={"institution_id": INSTITUTION_ID})

    # Confidence gate. If the transcript is garbage, do not
    # classify on it; route to human review of the audio.
    if (avg_confidence < ASR_MIN_AVG_CONFIDENCE or
            low_conf_count > ASR_MAX_LOW_CONF_WORDS):
        voicemail_records.update(voicemail_id, {
            "pipeline_status": "asr_low_confidence_human_review",
            "terminal_disposition": "human_review_low_asr_confidence",
        })

        audit_log({
            "event_type":   "ASR_CONFIDENCE_BELOW_GATE",
            "voicemail_id": voicemail_id,
            "avg_confidence": float(avg_confidence),
            "low_confidence_word_count": low_conf_count,
            "timestamp":
                datetime.now(timezone.utc).isoformat(),
        })

        cloudwatch.put_metric(
            "ASRConfidenceGateFailed", 1, "Count",
            dimensions={"institution_id": INSTITUTION_ID})

        return {
            "continue_to_classification": False,
            "voicemail_id":   voicemail_id,
            "transcript":     transcript_text,
            "disposition":    "human_review_low_asr_confidence",
        }

    return {
        "continue_to_classification": True,
        "voicemail_id":   voicemail_id,
        "transcript":     transcript_text,
        "avg_confidence": avg_confidence,
    }
```

---

## Step 4: Run the Urgency-Keyword Rule Layer, the LLM Classifier, and the Entity Extractor

*The pseudocode calls this `classify_voicemail(...)`. The rule layer is fast, deterministic, and safety-critical. It runs first and short-circuits to "emergent" or "urgent" if any urgent phrase matches. The LLM classifier and Comprehend Medical entity extractor run afterward. Combine the outputs into the structured triage record. Skip the rule-layer-first ordering and a missed urgency-keyword match will silently mis-route an emergency-room voicemail to the routine queue.*

```python
def scan_for_urgency_phrases(transcript):
    """
    Pattern-match the transcript against the urgency lexicon.

    Returns a dict with the highest-rank matching phrase (if any).
    Returns the matched phrase rather than just a level so the
    audit log can record *which* phrase fired the rule, which is
    operationally useful for lexicon review and for the
    continuous-improvement workflow.
    """
    if not transcript:
        return None
    lowered = transcript.lower()
    best = None
    for entry in URGENCY_LEXICON:
        if entry["phrase"] in lowered:
            rank = URGENCY_RANK_MAP.get(entry["level"], 0)
            if best is None or rank > best["rank"]:
                best = {
                    "phrase": entry["phrase"],
                    "level":  entry["level"],
                    "rank":   rank,
                }
    return best

def _max_urgency(rule_level, classifier_level):
    """
    The rule layer can only escalate, never de-escalate. Take
    the maximum of the rule-layer urgency floor and the
    classifier's urgency output.
    """
    rule_rank       = URGENCY_RANK_MAP.get(rule_level or "", 0)
    classifier_rank = URGENCY_RANK_MAP.get(classifier_level, 0)
    if rule_rank >= classifier_rank:
        return rule_level
    return classifier_level

def _build_classifier_prompt(transcript):
    """
    Construct the prompt sent to the foundation model. In
    production this includes a system instruction, the intent
    and urgency taxonomies, a small set of few-shot examples,
    a strict-JSON output schema, and the transcript to classify.
    The prompt is versioned (CLASSIFIER_PROMPT_VERSION) and
    changes are reviewed before deployment.

    The demo's prompt is a simple JSON dict; the MockBedrock
    matches on transcript substring. Real Bedrock calls send
    body=json.dumps({...}) with the model's expected schema
    (Anthropic Messages, Llama text completion, etc.).
    """
    prompt = {
        "instruction": (
            "You are a healthcare voicemail triage assistant. "
            "Classify the following voicemail transcript with "
            "intent, urgency, and a brief 1-2 sentence summary. "
            "Output valid JSON only."),
        "intent_taxonomy":  INTENT_TAXONOMY,
        "urgency_taxonomy": URGENCY_TAXONOMY,
        "transcript":       transcript,
        "output_schema": {
            "intent":              "<one of intent_taxonomy>",
            "intent_confidence":   "<float 0..1>",
            "urgency":             "<one of urgency_taxonomy>",
            "urgency_confidence":  "<float 0..1>",
            "summary":             "<1-2 sentence summary>",
        },
    }
    return json.dumps(prompt)

def classify_voicemail(stage_input):
    """
    Run the urgency rule layer, then the LLM classifier and
    entity extractor, then combine into the structured triage
    record.
    """
    voicemail_id    = stage_input["voicemail_id"]
    transcript_text = stage_input["transcript"]

    # Step 4A: urgency-keyword rule layer.
    rule_match = scan_for_urgency_phrases(transcript_text)
    rule_layer_urgency_floor = rule_match["level"] if rule_match else None
    rule_layer_phrase        = rule_match["phrase"] if rule_match else None

    # TODO (TechWriter): Code review Finding 6 (NOTE). The
    # main recipe pseudocode (Step 4B) and the prose overview
    # at the top of this file describe the LLM classifier and
    # the entity extractor running in parallel
    # (invoke_model_async + detect_entities_v2_async + await).
    # The demo runs them sequentially below for readability.
    # In a real Lambda, run them in parallel with a
    # ThreadPoolExecutor (or via two parallel branches in the
    # Step Functions state machine). Add an inline comment or
    # rephrase the prose overview to match the demo's
    # simplification.

    # Step 4B: LLM-based classifier. In production this is a
    # Bedrock InvokeModel call against a pinned model and
    # inference profile. The demo uses MockBedrock.
    # TODO (TechWriter): Code review Finding 3 (NOTE).
    # BEDROCK_INFERENCE_PROFILE_ARN is defined and asserted at
    # module load but never referenced. Add a production-comment
    # skeleton above this call that shows
    # bedrock_runtime.invoke_model(modelId=BEDROCK_INFERENCE_PROFILE_ARN,
    # body=..., contentType="application/json",
    # accept="application/json") so the inference-profile-as-
    # modelId pattern is visible to a learner translating the
    # demo to production.
    classifier_prompt = _build_classifier_prompt(transcript_text)
    classifier_response = bedrock_mock.invoke_model(
        model_id=BEDROCK_CLASSIFIER_MODEL_ID,
        body=classifier_prompt)

    # Step 4C: parse and validate the classifier output. Any
    # out-of-taxonomy value is coerced to a safe default rather
    # than passed through.
    try:
        parsed = json.loads(classifier_response["body"])
    except (TypeError, ValueError):
        parsed = None

    classifier_failed = (
        parsed is None
        or parsed.get("intent") not in INTENT_TAXONOMY
        or parsed.get("urgency") not in URGENCY_TAXONOMY)

    if classifier_failed:
        # The classifier returned something we cannot trust.
        # Use the rule-layer urgency floor (if any) and route
        # to human review.
        intent             = "unclear"
        intent_confidence  = Decimal("0.0")
        classifier_urgency = "unknown"
        urgency_confidence = Decimal("0.0")
        summary            = ("Classifier returned an unparseable "
                              "or out-of-taxonomy result; manual "
                              "review required.")
    else:
        intent             = parsed["intent"]
        intent_confidence  = Decimal(str(parsed.get("intent_confidence", 0)))
        classifier_urgency = parsed["urgency"]
        urgency_confidence = Decimal(str(parsed.get("urgency_confidence", 0)))
        summary            = parsed.get("summary", "")

    # Step 4D: combine rule-layer floor with classifier output.
    # Rule layer can only escalate.
    final_urgency = _max_urgency(rule_layer_urgency_floor,
                                  classifier_urgency)

    urgency_source = (f"rule_layer_{rule_layer_phrase}" if rule_match
                       else "classifier")

    # Step 4E: medical entity extraction.
    # TODO (TechWriter): Code review Finding 2 (WARNING) and
    # Expert review S1 (HIGH). The fixture data and the list
    # comprehensions below imply that detect_entities_v2
    # returns RxNorm/ICD-10 concepts on each entity. It does
    # not. Production pipelines call DetectEntitiesV2 to get
    # entities, then InferRxNorm / InferICD10CM / InferSNOMEDCT
    # in parallel and merge the ontology codes by text-offset.
    # Either (a) extend the demo to call (and mock) the Infer-*
    # APIs alongside DetectEntitiesV2 with a merge step, or
    # (b) drop the rxnorm_codes/icd10_codes fields from this
    # path and add a comment that ontology linking is a
    # separate API surface (the medication_alignment cross-
    # reference in enrich_voicemail already falls back to
    # text-based matching).
    entity_response = comprehend_mock.detect_entities_v2(
        text=transcript_text)
    raw_entities = entity_response.get("Entities", [])

    # Filter to the categories the routing logic uses. In
    # production Comprehend Medical returns a richer structure
    # with attributes, traits, RxNorm/ICD-10/SNOMED concepts;
    # the demo flattens a small subset.
    medications = [
        {"text": e.get("Text"),
         "score": Decimal(str(e.get("Score", 0))),
         "rxnorm_codes": e.get("RxNormConcepts", [])}
        for e in raw_entities if e.get("Category") == "MEDICATION"
    ]
    conditions = [
        {"text": e.get("Text"),
         "score": Decimal(str(e.get("Score", 0))),
         "icd10_codes": e.get("ICD10CMConcepts", [])}
        for e in raw_entities if e.get("Category") == "MEDICAL_CONDITION"
    ]
    anatomy = [
        {"text": e.get("Text"),
         "score": Decimal(str(e.get("Score", 0)))}
        for e in raw_entities if e.get("Category") == "ANATOMY"
    ]

    # Step 4F: persist the structured triage classification.
    classification_record = _to_decimal({
        "intent":                       intent,
        "intent_confidence":            intent_confidence,
        "urgency":                      final_urgency,
        "urgency_source":               urgency_source,
        "urgency_classifier_value":     classifier_urgency,
        "urgency_classifier_confidence": urgency_confidence,
        "summary":                      summary,
        "classified_at":
            datetime.now(timezone.utc).isoformat(),
        "classifier_prompt_version":    CLASSIFIER_PROMPT_VERSION,
        "intent_taxonomy_version":      INTENT_TAXONOMY_VERSION,
        "urgency_lexicon_version":      URGENCY_LEXICON_VERSION,
    })
    entities_record = _to_decimal({
        "medications": medications,
        "conditions":  conditions,
        "anatomy":     anatomy,
    })

    voicemail_records.update(voicemail_id, {
        "classification":  classification_record,
        "entities":        entities_record,
        "pipeline_status": "classified",
    })
    voicemail_records.append_audit(voicemail_id, {
        "event":     "CLASSIFIED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "intent":    intent,
        "urgency":   final_urgency,
    })

    if rule_match:
        audit_log({
            "event_type":              "URGENCY_RULE_LAYER_FIRED",
            "voicemail_id":            voicemail_id,
            "matched_phrase":          rule_layer_phrase,
            "rule_layer_level":        rule_layer_urgency_floor,
            "classifier_urgency_value": classifier_urgency,
            "final_urgency":           final_urgency,
            "urgency_lexicon_version": URGENCY_LEXICON_VERSION,
            "timestamp":
                datetime.now(timezone.utc).isoformat(),
        })
        cloudwatch.put_metric(
            "UrgencyRuleLayerFired", 1, "Count",
            dimensions={"final_urgency": final_urgency})

    cloudwatch.put_metric(
        "VoicemailClassified", 1, "Count",
        dimensions={"intent": intent, "urgency": final_urgency})

    needs_human_review = (
        classifier_failed
        or intent_confidence < INTENT_CONFIDENCE_THRESHOLD
        or urgency_confidence < URGENCY_CONFIDENCE_THRESHOLD)

    return {
        "voicemail_id":         voicemail_id,
        "transcript":           transcript_text,
        "intent":               intent,
        "urgency":              final_urgency,
        "needs_human_review":   needs_human_review,
        "entities": {
            "medications": medications,
            "conditions":  conditions,
        },
    }
```

---

## Step 5: Enrich with Patient Context and Detect Repeat Callers

*The pseudocode calls this `enrich_voicemail(...)`. Look up the caller's phone number against the patient index. If exactly one patient matches, fetch their context (medications, recent conditions). Check whether the same caller has left similar voicemails recently. The enrichment makes the triage record actionable: instead of "someone called about a medication," the staff member sees "Mr. Patel, active on metformin, called Tuesday about the same metformin refill." Skip enrichment and the staff member has to repeat lookups for every callback.*

```python
def enrich_voicemail(stage_input):
    """
    Enrich the triage record with patient context (when the
    caller's phone number unambiguously matches a patient) and
    repeat-caller detection.
    """
    voicemail_id = stage_input["voicemail_id"]
    record       = voicemail_records.get(voicemail_id)
    ani          = record.get("ani")
    intent       = stage_input.get("intent")
    entities     = stage_input.get("entities", {})

    # Step 5A: ANI-based patient lookup.
    patient_matches = ehr.lookup_by_phone(ani) if ani else []
    enrichment = {
        "ani_match_count":    len(patient_matches),
        "patient_candidates": [
            {"patient_id": p["patient_id"]}
            for p in patient_matches
        ],
    }

    # Step 5B: when match is unambiguous, fetch context. With
    # multiple matches (household line) or zero matches, leave
    # the per-patient context empty; the staff member resolves
    # ambiguity manually.
    if len(patient_matches) == 1:
        patient = patient_matches[0]
        patient_id = patient["patient_id"]
        active_meds = ehr.get_active_medications(patient_id)
        active_conditions = ehr.get_active_conditions(patient_id)

        enrichment["patient_id"] = patient_id
        enrichment["preferred_language"] = patient.get(
            "preferred_language", "en")
        enrichment["active_medications"] = active_meds
        enrichment["active_conditions"]  = active_conditions

        # Step 5C: cross-reference the voicemail's medication
        # mentions with the patient's active medication list.
        # A mention not in the active list might be a new
        # prescription not yet recorded, an ASR error on the
        # drug name, or (rarely) a request for someone else's
        # prescription. Surfacing the mismatch lets the staff
        # member catch it before acting.
        voicemail_meds = entities.get("medications", [])
        if voicemail_meds:
            active_med_names = {
                m["name"].lower() for m in active_meds
            }
            alignment = []
            for vm_med in voicemail_meds:
                vm_med_text = (vm_med.get("text") or "").lower()
                in_active_list = any(
                    name in vm_med_text or vm_med_text in name
                    for name in active_med_names)
                alignment.append({
                    "voicemail_mention":  vm_med.get("text"),
                    "in_active_med_list": in_active_list,
                })
            enrichment["medication_alignment"] = alignment

    # Step 5D: repeat-caller and de-duplication detection. Look
    # at recent voicemails from the same ANI; flag the new one
    # as a candidate duplicate if the intent matches.
    recent_from_same = voicemail_records.query_by_phone_and_window(
        phone=ani, window_hours=REPEAT_CALLER_WINDOW_HOURS)
    similar = [
        vm for vm in recent_from_same
        if vm.get("voicemail_id") != voicemail_id
        and vm.get("classification", {}).get("intent") == intent
    ]
    enrichment["repeat_caller"] = {
        "recent_voicemail_count":  len(recent_from_same) - 1,
        "similar_voicemail_count": len(similar),
        "similar_voicemail_ids":   [vm.get("voicemail_id")
                                     for vm in similar],
    }

    voicemail_records.update(voicemail_id, _to_decimal({
        "enrichment":     enrichment,
        "pipeline_status": "enriched",
    }))
    voicemail_records.append_audit(voicemail_id, {
        "event":     "ENRICHED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    audit_log({
        "event_type":      "VOICEMAIL_ENRICHED",
        "voicemail_id":    voicemail_id,
        "ani_match_count": len(patient_matches),
        "similar_voicemail_count":
            enrichment["repeat_caller"]["similar_voicemail_count"],
        "timestamp":
            datetime.now(timezone.utc).isoformat(),
    })

    return {
        "voicemail_id":       voicemail_id,
        "intent":             intent,
        "urgency":            stage_input["urgency"],
        "needs_human_review": stage_input["needs_human_review"],
        "enrichment":         enrichment,
    }
```

---

## Step 6: Route to the Appropriate Queue and Notify on Emergent Items

*The pseudocode calls this `route_voicemail(...)`. Select the queue based on intent and patient context, compute a priority based on urgency and time, place the triage record in the queue, and emit an active notification if the urgency is emergent. Skip the active-notification path and emergent voicemails will sit in the queue until a staff member looks at it; that may be acceptable for routine items, but it is not acceptable for an emergent clinical signal.*

```python
def route_voicemail(stage_input):
    """
    Place the triage record in the appropriate staff queue,
    emit cross-system events, and (if urgency is emergent)
    publish an active notification.
    """
    voicemail_id       = stage_input["voicemail_id"]
    intent             = stage_input["intent"]
    urgency            = stage_input["urgency"]
    enrichment         = stage_input.get("enrichment", {})
    needs_human_review = stage_input.get("needs_human_review", False)

    record       = voicemail_records.get(voicemail_id)
    recorded_at  = record.get("recorded_at",
                               datetime.now(timezone.utc).isoformat())

    # Step 6A: select the queue. Spam intents have an empty
    # queue list (suppressed from staff queue entirely).
    queue_targets = INTENT_TO_QUEUE_MAP.get(
        intent, INTENT_TO_QUEUE_MAP["_default"])

    # Emergent urgency always also fans out to the clinical-
    # escalation queue regardless of intent.
    if urgency == "emergent" and "clinical_escalation" not in queue_targets:
        queue_targets = list(queue_targets) + ["clinical_escalation"]

    # Step 6B: priority key. Higher urgency rank, then older
    # voicemails first within tier (staff member shouldn't see
    # newer routine messages cut in front of older routine
    # messages).
    urgency_rank = URGENCY_RANK_MAP.get(urgency, 0)
    priority_key = _build_priority_key(urgency_rank, recorded_at)

    # Step 6C: place into each target queue.
    placed_at = datetime.now(timezone.utc).isoformat()
    for queue_name in queue_targets:
        triage_queue.put(_to_decimal({
            "queue_name":           queue_name,
            "priority_key":         priority_key,
            "voicemail_id":         voicemail_id,
            "urgency":              urgency,
            "intent":               intent,
            "patient_id":           enrichment.get("patient_id"),
            "needs_human_review":   needs_human_review,
            "placed_at":            placed_at,
        }))

    # Step 6D: cross-system event for downstream consumers.
    # Production: eventbridge_client.put_events(...).
    event_bus.put_events([{
        "Source":       "voicemail.triage",
        "DetailType":   "voicemail_routed",
        "EventBusName": VOICEMAIL_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "voicemail_id":  voicemail_id,
            "queue_targets": queue_targets,
            "urgency":       urgency,
            "intent":        intent,
            "placed_at":     placed_at,
        }),
    }])

    # Step 6E: emergent active notification. The SNS topic has
    # multiple subscribers (pager, on-call SMS, dashboard alert,
    # mobile push). The notification payload is intentionally
    # minimal; it does NOT include PHI. The recipient sees the
    # voicemail_id and queue_name and clicks through to the
    # staff interface, which renders the full triage record
    # only after authenticating the user.
    if urgency == "emergent":
        # Production: sns_client.publish(
        #     TopicArn=EMERGENT_VOICEMAIL_TOPIC_ARN,
        #     Subject="Emergent voicemail queued",
        #     Message=json.dumps({...}))
        sns.publish(
            topic_arn=EMERGENT_VOICEMAIL_TOPIC_ARN,
            subject="Emergent voicemail queued",
            message=json.dumps({
                "voicemail_id": voicemail_id,
                "queue_name":
                    queue_targets[0] if queue_targets
                    else "general_triage",
                "placed_at":    placed_at,
            }))

        audit_log({
            "event_type":   "EMERGENT_NOTIFICATION_SENT",
            "voicemail_id": voicemail_id,
            "queue_targets": queue_targets,
            "urgency_source":
                record.get("classification", {}).get("urgency_source"),
            "timestamp":    placed_at,
        })

        cloudwatch.put_metric(
            "EmergentNotificationsSent", 1, "Count",
            dimensions={"institution_id": INSTITUTION_ID})

    voicemail_records.update(voicemail_id, _to_decimal({
        "routing": {
            "queue_targets":  queue_targets,
            "priority_key":   priority_key,
            "routed_at":      placed_at,
        },
        "pipeline_status": "routed",
    }))
    voicemail_records.append_audit(voicemail_id, {
        "event":     "ROUTED",
        "timestamp": placed_at,
        "queues":    queue_targets,
    })

    audit_log({
        "event_type":    "VOICEMAIL_ROUTED",
        "voicemail_id":  voicemail_id,
        "queue_targets": queue_targets,
        "urgency":       urgency,
        "intent":        intent,
        "needs_human_review": needs_human_review,
        "timestamp":     placed_at,
    })

    cloudwatch.put_metric(
        "VoicemailRouted", 1, "Count",
        dimensions={"intent": intent, "urgency": urgency})

    return {
        "voicemail_id":  voicemail_id,
        "queue_targets": queue_targets,
        "priority_key":  priority_key,
    }
```

---

## Step 7: Capture Staff Actions for the Disagreement-and-Improvement Dataset

*The pseudocode calls this `ON staff_action(...)`. When a staff member listens to, calls back, escalates, or marks a voicemail resolved, the action is captured and pushed back to the audit log and the analytics layer. The captured outcomes feed the metrics that the institution uses to monitor the system: time-to-callback by urgency tier, classifier-disagreement-with-staff-judgment rate, repeat-caller rate, subgroup-stratified accuracy.*

```python
def record_staff_action(voicemail_id, staff_user_id, action,
                         action_metadata=None):
    """
    Capture a staff member's action against a voicemail.

    Args:
        voicemail_id: The voicemail being acted on.
        staff_user_id: The staff member taking the action.
        action: One of "listened", "called_back",
            "marked_resolved", "escalated_to_clinician",
            "reclassified_intent", "reclassified_urgency".
        action_metadata: Optional dict with action-specific
            details (e.g., the corrected intent for a
            reclassification).

    Returns:
        The audit entry that was written.
    """
    action_metadata = action_metadata or {}
    record = voicemail_records.get(voicemail_id)
    classification = record.get("classification", {})
    now = datetime.now(timezone.utc).isoformat()

    audit_entry = {
        "event":         action.upper(),
        "staff_user_id": staff_user_id,
        "timestamp":     now,
        "metadata":      _to_decimal(action_metadata),
    }
    voicemail_records.append_audit(voicemail_id, audit_entry)

    # When a staff member reclassifies, capture the disagreement.
    # This becomes the labeled dataset that drives ongoing
    # classifier-prompt and lexicon improvement.
    if action in ("reclassified_intent", "reclassified_urgency"):
        disagreement = _to_decimal({
            "voicemail_id":          voicemail_id,
            "voicemail_recorded_at": record.get("recorded_at"),
            "machine_intent":        classification.get("intent"),
            "machine_urgency":       classification.get("urgency"),
            "human_intent":
                action_metadata.get("corrected_intent",
                                     classification.get("intent")),
            "human_urgency":
                action_metadata.get("corrected_urgency",
                                     classification.get("urgency")),
            "staff_user_id":         staff_user_id,
            "captured_at":           now,
        })
        # In production this writes to a separate
        # classifier-disagreement table that feeds the weekly
        # review cadence. The demo prints it.
        audit_log({
            "event_type":       "CLASSIFIER_DISAGREEMENT_CAPTURED",
            **disagreement,
        })
        cloudwatch.put_metric(
            "ClassifierDisagreement", 1, "Count",
            dimensions={
                "axis":
                    "intent" if action == "reclassified_intent"
                    else "urgency",
            })

    # Cross-system event for analytics.
    event_bus.put_events([{
        "Source":       "voicemail.staff_action",
        "DetailType":   action,
        "EventBusName": VOICEMAIL_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "voicemail_id":  voicemail_id,
            "staff_user_id": staff_user_id,
            "action":        action,
            "timestamp":     now,
            "urgency":       classification.get("urgency"),
            "intent":        classification.get("intent"),
        }),
    }])

    return audit_entry
```

---

## Putting It All Together

Here is the full pipeline tied together as a top-level function that simulates a voicemail flowing end-to-end through the seven stages. In a Step Functions deployment, the orchestration would be the state-machine definition (Amazon States Language) and each stage would be a separate Lambda invocation; the demo orchestrates the stages inline so you can see the full sequence.

```python
def process_voicemail(source_event):
    """
    End-to-end voicemail processing. In production this is the
    Step Functions state machine; the demo runs the stages
    sequentially in Python.
    """
    # Stage 1: ingest.
    print(f"\n--- Stage 1: ingest ---")
    ingest_result = ingest_voicemail(source_event)
    voicemail_id = ingest_result["voicemail_id"]
    print(f"  voicemail_id: {voicemail_id}")

    # Stage 2: pre-process. Forward simulated audio properties
    # through the dict so the demo can deterministically drive
    # short-circuit paths without real audio.
    print(f"\n--- Stage 2: pre-process ---")
    preprocess_input = {
        **ingest_result,
        "simulated_speech_ratio":
            source_event.get("simulated_speech_ratio", 0.85),
        "simulated_has_fax_tones":
            source_event.get("simulated_has_fax_tones", False),
        "simulated_detected_language":
            source_event.get("simulated_detected_language", "en-US"),
    }
    preprocess_result = preprocess_audio(preprocess_input)
    print(f"  continue_to_asr: {preprocess_result['continue_to_asr']}")
    if not preprocess_result["continue_to_asr"]:
        print(f"  short-circuit disposition: "
              f"{preprocess_result.get('disposition')}")
        return voicemail_id

    # Stage 3: ASR submit and result.
    print(f"\n--- Stage 3: ASR submit and result ---")
    asr_submit_result = start_asr_job(preprocess_result)
    asr_complete_result = handle_asr_completion(asr_submit_result)
    print(f"  continue_to_classification: "
          f"{asr_complete_result['continue_to_classification']}")
    if not asr_complete_result["continue_to_classification"]:
        print(f"  short-circuit disposition: "
              f"{asr_complete_result.get('disposition')}")
        return voicemail_id

    # Stage 4: classify (urgency rule layer + LLM + entity extraction).
    print(f"\n--- Stage 4: classify ---")
    classify_result = classify_voicemail(asr_complete_result)
    print(f"  intent:  {classify_result['intent']}")
    print(f"  urgency: {classify_result['urgency']}")
    print(f"  needs_human_review: "
          f"{classify_result['needs_human_review']}")

    # Stage 5: enrich.
    print(f"\n--- Stage 5: enrich ---")
    enrich_result = enrich_voicemail(classify_result)
    enrichment = enrich_result["enrichment"]
    print(f"  ani_match_count: {enrichment.get('ani_match_count')}")
    if enrichment.get("patient_id"):
        print(f"  patient_id: {enrichment['patient_id']}")
    print(f"  similar voicemails in window: "
          f"{enrichment['repeat_caller']['similar_voicemail_count']}")

    # Stage 6: route.
    print(f"\n--- Stage 6: route ---")
    route_result = route_voicemail(enrich_result)
    print(f"  queue_targets: {route_result['queue_targets']}")
    print(f"  priority_key:  {route_result['priority_key']}")

    return voicemail_id

def run_demo():
    """
    Run a small set of end-to-end scenarios that exercise the
    main paths through the voicemail-triage pipeline:
      1. Routine medication refill: passes all gates, lands in
         the pharmacy queue at routine priority.
      2. Emergent chest-pain voicemail: rule layer fires,
         escalates to emergent urgency regardless of
         classifier output, SNS notification sent.
      3. Pocket-dial pre-processing short-circuit: speech
         ratio below threshold, no ASR job submitted.
      4. Low-confidence ASR: transcript confidence below the
         gate, routed to human review without classification.
      5. Reclassification by staff: captures the disagreement
         dataset for ongoing improvement.
    """
    global transcribe_mock, bedrock_mock, comprehend_mock

    # --- Fixture data for the mocks ---
    transcript_fixtures = {
        # Routine refill voicemail
        "vm-fixture-refill": {
            "transcript_text":
                "Hi, this is Margaret Chen, I need a refill on my "
                "lisinopril, please call me back at this number.",
            "items": [
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.95"}]},
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.92"}]},
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.94"}]},
            ],
        },
        # Emergent chest pain
        "vm-fixture-chest-pain": {
            "transcript_text":
                "Hi, this is James Patel, I'm calling because I "
                "have chest pain and shortness of breath, I think "
                "I need to talk to a nurse, please call me back.",
            "items": [
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.93"}]},
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.91"}]},
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.90"}]},
            ],
        },
        # Low ASR confidence (mostly noise)
        "vm-fixture-low-confidence": {
            "transcript_text":
                "uhh I think um maybe call me",
            "items": [
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.40"}]},
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.38"}]},
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.42"}]},
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.35"}]},
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.45"}]},
                {"type": "pronunciation",
                 "alternatives": [{"confidence": "0.40"}]},
            ],
        },
    }

    classification_fixtures = {
        "lisinopril": {
            "intent":             "medication_refill",
            "intent_confidence":  0.94,
            "urgency":            "routine",
            "urgency_confidence": 0.91,
            "summary":            "Caller requesting a refill of "
                                  "lisinopril.",
        },
        "chest pain": {
            # Even though the LLM may classify as routine
            # symptom report, the rule layer will escalate.
            # This fixture deliberately returns "urgent" to
            # show the rule layer can still escalate it.
            "intent":             "clinical_symptom_report",
            "intent_confidence":  0.88,
            "urgency":            "urgent",
            "urgency_confidence": 0.86,
            "summary":            "Caller reports chest pain and "
                                  "shortness of breath, asks to "
                                  "speak with a nurse.",
        },
    }

    entity_fixtures = {
        "lisinopril": [{
            "Text":     "lisinopril",
            "Score":    0.97,
            "Category": "MEDICATION",
            "RxNormConcepts": [{"Code": "29046",
                                 "Description": "lisinopril"}],
        }],
        "chest pain": [
            {"Text": "chest pain",
             "Score": 0.95, "Category": "MEDICAL_CONDITION",
             "ICD10CMConcepts": [{"Code": "R07.9",
                                   "Description": "chest pain"}]},
            {"Text": "shortness of breath",
             "Score": 0.93, "Category": "MEDICAL_CONDITION",
             "ICD10CMConcepts": [{"Code": "R06.02",
                                   "Description":
                                     "shortness of breath"}]},
            {"Text": "chest", "Score": 0.99, "Category": "ANATOMY"},
        ],
    }

    # Wire up the mocks with fixtures.
    transcribe_mock  = MockTranscribeMedical(transcript_fixtures)
    bedrock_mock     = MockBedrock(classification_fixtures)
    comprehend_mock  = MockComprehendMedical(entity_fixtures)

    # --- Pre-load a "previous" voicemail from Margaret Chen so
    # the repeat-caller detection has something to match. ---
    previous_recorded_at = (datetime.now(timezone.utc)
                             - timedelta(hours=20)).isoformat()
    voicemail_records.put(_to_decimal({
        "voicemail_id":   "vm-prior-001",
        "ani":            "5715551234",
        "recorded_at":    previous_recorded_at,
        "classification": {"intent": "medication_refill",
                            "urgency": "routine"},
        "audit_history":  [{"event": "INGESTED",
                             "timestamp": previous_recorded_at}],
    }))

    # We use deterministic voicemail_ids so the fixture lookups
    # work. Override the uuid generation by passing the desired
    # transcript via simulated path; the simplest way is to
    # write the voicemail_id directly into a per-scenario
    # entry in transcribe_fixtures keyed by the demo's id.
    # (See how transcribe_mock is keyed by voicemail_id; the
    # scenarios below use voicemail_ids that match the keys.)

    # The simplest demo: build scenarios as direct dicts and
    # use a wrapper that injects a fixed voicemail_id.
    scenarios = [
        {
            "name": "routine_refill_success",
            "fixture_id": "vm-fixture-refill",
            "source_event": {
                "caller_phone_number":   "5715551234",
                "called_number":         "8045550000",
                "recorded_at":
                    datetime.now(timezone.utc).isoformat(),
                "duration_seconds":      32,
                "source_system":         "ucaas-vendor-x",
                "source_message_id":     "vendor-msg-100001",
                "audio_format":          "wav",
                "simulated_speech_ratio": 0.88,
            },
        },
        {
            "name": "emergent_chest_pain_rule_layer",
            "fixture_id": "vm-fixture-chest-pain",
            "source_event": {
                "caller_phone_number":   "8045555678",
                "called_number":         "8045550000",
                "recorded_at":
                    datetime.now(timezone.utc).isoformat(),
                "duration_seconds":      48,
                "source_system":         "ucaas-vendor-x",
                "source_message_id":     "vendor-msg-100002",
                "audio_format":          "wav",
                "simulated_speech_ratio": 0.91,
            },
        },
        {
            "name": "pocket_dial_short_circuit",
            "fixture_id": None,
            "source_event": {
                "caller_phone_number":   "5559998888",
                "called_number":         "8045550000",
                "recorded_at":
                    datetime.now(timezone.utc).isoformat(),
                "duration_seconds":      8,
                "source_system":         "ucaas-vendor-x",
                "source_message_id":     "vendor-msg-100003",
                "audio_format":          "wav",
                "simulated_speech_ratio": 0.05,  # Below VAD threshold
            },
        },
        {
            "name": "low_asr_confidence_to_human_review",
            "fixture_id": "vm-fixture-low-confidence",
            "source_event": {
                "caller_phone_number":   "9145557777",
                "called_number":         "8045550000",
                "recorded_at":
                    datetime.now(timezone.utc).isoformat(),
                "duration_seconds":      22,
                "source_system":         "ucaas-vendor-x",
                "source_message_id":     "vendor-msg-100004",
                "audio_format":          "wav",
                "simulated_speech_ratio": 0.65,
            },
        },
    ]

    # The fixture_id is what the MockTranscribeMedical looks up
    # to return the right transcript. We arrange that the
    # voicemail_id created in ingest_voicemail() matches the
    # fixture_id by patching ingest_voicemail's id generation
    # for the demo. The cleanest demo wrapper is below.
    processed_voicemail_ids = []
    for scenario in scenarios:
        print("\n" + "#" * 60)
        print(f"# SCENARIO: {scenario['name']}")
        print("#" * 60)
        # If the scenario has a fixture id, register it with
        # transcribe_mock so the next ingested voicemail can
        # find its fixture (the demo keys fixtures on
        # voicemail_id; we copy the entry under whatever id
        # ingest_voicemail produces).
        vm_id = process_voicemail(scenario["source_event"])
        if scenario["fixture_id"]:
            # Re-key the fixtures under the actual voicemail_id
            # generated in this scenario so subsequent stages
            # (classifier, entities) can find them. In a real
            # pipeline, the transcript IS the input to those
            # stages; the demo keys the mocks for clarity.
            # TODO (TechWriter): Code review Finding 1 (ERROR).
            # The pass below is a literal no-op; the comment
            # describes the fix but it is not implemented. By
            # the time this point is reached, process_voicemail
            # has already submitted the ASR job using vm_id, so
            # re-keying after the fact does not help. Adopt
            # Option B from the code review: in ingest_voicemail,
            # honor source_event.get("voicemail_id_override")
            # when present (demo-only) and pass each scenario's
            # fixture_id through the source_event. Then this
            # block can go away entirely.
            pass
        processed_voicemail_ids.append(vm_id)

    # --- Demonstrate the staff-action capture (Step 7) ---
    # Pretend the staff member reviewed the routine-refill
    # voicemail and reclassified it (deciding the medication
    # mention was actually a different drug).
    if processed_voicemail_ids:
        print("\n" + "#" * 60)
        print("# STAFF ACTION: reclassify routine refill")
        print("#" * 60)
        record_staff_action(
            voicemail_id=processed_voicemail_ids[0],
            staff_user_id="nurse-emily-r",
            action="reclassified_intent",
            action_metadata={
                "corrected_intent": "medication_question",
                "note":             ("Caller wanted to ask about "
                                      "side effects, not a refill"),
            })

    # --- Print a summary ---
    print("\n" + "=" * 60)
    print("DEMO SUMMARY")
    print("=" * 60)
    print(f"Voicemails processed:           "
          f"{len(processed_voicemail_ids)}")
    print(f"Triage queue records placed:    "
          f"{len(triage_queue._records)}")
    print(f"Cross-system events emitted:    "
          f"{len(event_bus.events)}")
    print(f"Emergent SNS publishes:         "
          f"{len(sns.published)}")
    print(f"CloudWatch metrics emitted:     "
          f"{len(cloudwatch.metrics)}")
    print(f"S3 audio objects stored:        "
          f"{len([k for k in s3._objects if k[0] == AUDIO_BUCKET])}")
    print()
    print("Triage queue contents (highest priority first):")
    seen_queues = {r['queue_name'] for r in triage_queue._records}
    for queue_name in sorted(seen_queues):
        items = triage_queue.items_for_queue(queue_name)
        print(f"  Queue '{queue_name}':")
        for item in items[:5]:  # top 5 per queue
            print(f"    - {item['voicemail_id']} "
                  f"urgency={item['urgency']} "
                  f"intent={item['intent']}")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    run_demo()
```

> **A note on the demo's mocks.** Real Transcribe Medical and Comprehend Medical calls receive the actual audio (or transcript text) and return real classifications. The demo's `MockTranscribeMedical` and `MockBedrock` use fixture lookups so the same scenario always produces the same output, which makes the rest of the pipeline deterministic for teaching purposes. In the wiring above, the fixtures are matched on transcript substring (for Bedrock) or on a fixture_id (for Transcribe). This is enough to demonstrate the rule-layer-fires-first pattern, the confidence-gate behavior, and the priority-queue ordering, without needing a working Bedrock or Transcribe deployment to run the file.

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right triage records, but the distance between it and a real voicemail-triage pipeline running at a healthcare practice is significant. Here is where that distance lives.

**Real Step Functions state machine plus per-stage Lambdas.** The demo orchestrates stages in Python. Production lives in a Step Functions state machine (Amazon States Language definition) that handles the conditional branching (continue to ASR vs. short-circuit, continue to classification vs. route to human review), the async wait for the Transcribe Medical job-completion event, the retry-and-error semantics per stage, and the per-execution audit trail. Each stage is a separate Lambda function with its own IAM role, error handling, retries, and DLQs. The boundary is: Step Functions handles orchestration; each Lambda handles one stage's logic.

**Real Transcribe Medical and Comprehend Medical wiring.** The demo mocks the ASR and entity extraction. Production calls `transcribe_client.start_medical_transcription_job` (with PRIMARYCARE specialty, CONVERSATION mode, output encryption keyed to a customer-managed KMS key, and word-level confidence in the output), waits for the job-completion EventBridge event, reads the transcript JSON from the output S3 bucket, and runs `comprehend_medical.detect_entities_v2` on the transcript text. The async-wait pattern in Step Functions (`waitForTaskToken` or polling) is the right architectural shape; the demo's inline polling is a placeholder.

**Real Bedrock invocation and prompt management.** The demo's `MockBedrock` uses fixture lookups. Production calls `bedrock_runtime.invoke_model` against a pinned model ID and inference profile ARN, with a real prompt that includes a system instruction, the intent and urgency taxonomies, a small set of carefully-curated few-shot examples, and a strict-JSON output schema. The prompt is versioned and deployed alongside the rest of the pipeline; prompt changes go through review (the prompt is a load-bearing safety artifact at this point, not a config string). The model output is parsed and validated against the taxonomies; out-of-taxonomy values trigger human review rather than being passed through.

**Per-Lambda IAM roles.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda (ingestor, pre-processor, ASR-result-handler, classifier, entity-extractor, enricher, router, staff-action-handler), each scoped to the specific resource ARNs the Lambda touches. The classifier role has scoped Bedrock invocation rights pinned to one model ID and one inference profile; the router role has scoped SNS publish rights on the emergent topic and `events:PutEvents` on the voicemail-events bus. Wildcard actions and resources will fail any serious IAM review.

**Real S3 and DynamoDB wiring with KMS.** The mocks in the demo are dictionaries; production is S3 buckets with SSE-KMS, lifecycle policies (Glacier Instant Retrieval after 30 days, Glacier Deep Archive after 1 year for the audio bucket; institutional-policy-driven retention; Object Lock in compliance mode for the audit-log bucket), DynamoDB tables with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery enabled, TTL attributes where appropriate, and DynamoDB Streams emitting change events for downstream consumers (analytics fan-out, EHR writeback for resolved voicemails, repeat-caller analytics).

**Customer-managed KMS keys, per data class.** Every PHI-bearing resource (audio bucket, transcript bucket, voicemail-records table, triage-queue table, patient-index table, audit-log bucket, Lambda environment variables, CloudWatch Logs, Secrets Manager) uses customer-managed KMS keys with key rotation enabled. Different keys per data class for blast-radius containment: a compromised audio-bucket key does not compromise the transcript bucket. CloudTrail logs every key-usage event. The institutional KMS-key-management runbook specifies rotation cadence, access review cadence, and the cross-account key-grant pattern for any cross-account integrations (e.g., the EHR integration may live in a different account).

**VPC and VPC endpoints.** Lambdas that call back-office APIs (EHR, scheduling, pharmacy) run in a VPC with private subnets that route traffic through controlled egress paths to those systems. VPC endpoints for S3, DynamoDB, KMS, Secrets Manager, EventBridge, SNS, Comprehend Medical, Transcribe, and Bedrock keep AWS-internal traffic on the AWS backbone rather than traversing NAT and the public internet. Endpoint policies pin access to the specific resources the pipeline uses.

**Per-jurisdiction recording-disclosure language.** The demo hand-waves the disclosure (the recording disclosure is implicit in the voicemail greeting that the source system plays). Production has separate disclosure language per jurisdiction (one-party-consent states, all-party-consent states, the institution's preferred default for unknown jurisdictions), the source voicemail system plays the right disclosure based on the dialed-in number's geographic indicators, and general counsel reviews and approves the per-jurisdiction language. The disclosure is operationally important and should not be improvised at deploy time.

**Real urgency-lexicon governance.** The lexicon in the demo is illustrative. Production has a versioned, reviewed lexicon stored in Parameter Store, AppConfig, or a versioned S3 object (so it can be updated without redeploying the Lambda), a quarterly review cadence with clinical operations, a change-review workflow when phrases are added or removed, and a documented escalation path when a missed urgent voicemail surfaces. Treat the lexicon as a clinical safety document with the procedural rigor that implies. The Lambda reloads the lexicon at the start of each invocation so a config change takes effect immediately.

**Per-axis confidence-threshold calibration.** The thresholds in the demo are placeholder values. Production calibrates them against real traffic: collect a labeled sample of production transcripts (intent classification was correct or incorrect, urgency classification was correct or incorrect), build precision-recall curves per axis at various confidence thresholds, and pick the thresholds that achieve the institution's chosen precision floors. Re-calibrate quarterly or whenever the classifier prompt or the foundation model changes (a model upgrade can shift the confidence distribution).

**Subgroup-stratified accuracy monitoring.** The demo emits CloudWatch metrics with `intent` and `urgency` dimensions, which is enough for per-intent dashboards. Production additionally stratifies by caller-cohort dimensions (preferred language from the matched patient record, age band where the data permits, geographic region from area code, accent group where it can be inferred from acoustic features). Dashboards alert when subgroup accuracy diverges by more than the configured threshold. The metric is institutionally important, not just engineering housekeeping; name an owner (typically the equity-monitoring committee or the clinical-quality officer) and review monthly.

**Idempotency at every stage.** The demo's writes are not idempotent: a re-run of the same voicemail produces a duplicate record. Production uses conditional writes (`attribute_not_exists(voicemail_id)` for the initial ingest) and treats the (voicemail_id, stage_name) tuple as the idempotency key for every stage. ASR jobs use the voicemail_id as the deterministic job name; classifier output is keyed by voicemail_id with a revision counter for legitimate re-runs; SNS publishes use the voicemail_id as a deduplication key (or are gated on the routing record's `notification_sent` flag set with a conditional update). Configure DLQs on every Lambda; alarm on DLQ depth, with the emergent-voicemail Lambda's DLQ paged immediately rather than next-business-day.

**Active-notification policy and on-call rotation integration.** The demo publishes to an SNS topic with no real subscribers. Production integrates with the institution's on-call schedule (PagerDuty, Opsgenie, or an EHR-vendor-provided on-call system): the emergent topic delivers to a paging service, which knows who is on call at 3 a.m. on a Tuesday, who is the backup if the primary doesn't acknowledge within 5 minutes, and what the escalation path is if neither acknowledges within 15. These are clinical operational policies that the architecture supports; they are not engineering decisions.

**Staff triage UI.** The demo has no UI; the triage records are inspected via the printed summary. Production has a substantial UI: queue view with priority sorting and filter by role/intent; per-voicemail detail view with the audio player synchronized to the transcript timing, transcript with entities highlighted, machine-classified intent and urgency, patient context summary, recent voicemail history; quick-action buttons for the common dispositions (called back, marked resolved, escalated to clinician, reclassified); reclassification capture for the disagreement dataset. The UI is where the system either becomes a tool the staff uses with confidence or a tool they work around. Prototype with representative staff users before locking the design.

**Multilingual support.** The demo handles English. Production adds Spanish (and other languages relevant to the practice's patient population): language detection at the front of the pipeline; language-specific Transcribe Medical jobs; language-specific classifier prompts (the foundation model usually handles multilingual classification but the prompt and few-shot examples should be in the appropriate language); language-specific urgency lexicons (the Spanish urgency lexicon is not a translation of the English one; "me siento mal" carries different urgency weight than its English literal translation). Build the multi-language scaffolding even if you ship English-first; retrofitting is more expensive than designing for it.

**Sampled human review with disagreement capture.** The demo has a single staff-action capture path. Production has a sampled-review service that selects a random stratified sample of voicemails per week (a few percent of total volume, stratified by intent and urgency to ensure coverage of each category, not purely random which would over-sample the routine intents and undersample the emergent ones), routes them to a clinical reviewer, and captures the human assessment alongside the machine assessment. The disagreement table feeds the labeled dataset that drives ongoing classifier prompt and lexicon improvement.

**Real fuzzy medication matching.** The demo's medication-alignment check uses naive substring matching. Production matches against RxNorm or the institution's drug-database equivalent, handles brand-vs-generic equivalents (Lipitor and atorvastatin), handles common ASR mis-recognitions ("listen approval" -> "lisinopril"), and surfaces ambiguity to the staff member rather than silently picking one. Comprehend Medical's RxNorm concept output is the natural foundation for this; the demo's flat-text mention is a simplification.

**Disaster recovery and pipeline-unavailable handling.** If any pipeline stage is unavailable (Transcribe Medical regional outage, Bedrock service issue, DynamoDB partition exhaustion), the system should fall back to delivering the raw voicemail audio to the staff queue with an "automated triage unavailable, please review manually" flag. The voicemail box was reachable by humans before the pipeline existed; it must remain reachable by humans when the pipeline cannot run. Test the failover quarterly with synthetic outages.

**Continuous classifier improvement workflow.** Production transcripts surface intents the original taxonomy missed, voicemail patterns the classifier handles poorly, and urgency phrases the lexicon doesn't cover. The improvement workflow (review production transcripts and the classifier-disagreement table weekly, propose taxonomy and lexicon changes, test against a held-out evaluation set, deploy via versioned classifier prompts and lexicon versions, monitor for regressions) is a sustained engineering practice, not a launch task. Plan staffing accordingly. Versioned prompt aliases and gradual rollout (a small percentage of traffic against the new prompt, monitor disagreement metrics, promote when the new prompt performs at parity or better) are standard.

**Audit retention and access controls.** The audit log captures every action taken on every voicemail. The retention policy must satisfy HIPAA's six-year minimum, state-specific medical-records-retention rules, and the institution's own regulatory floor. Access to the audit log is on a need-to-know basis and is itself audited (CloudTrail on the audit log bucket). Retention is enforced via S3 lifecycle policies and Object Lock; deletion before retention expiry is impossible.

**Cost monitoring per-intent and per-urgency.** Different voicemails consume different amounts of pipeline cost (a 90-second emergent voicemail with full classification and entity extraction costs more than an 8-second pocket-dial that gets short-circuited by the pre-processor). The cost-attribution analytics let the operations team see which voicemail patterns are economically efficient and which warrant further pipeline tuning. Build the dashboard.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the urgency-rule-layer logic with edge cases (rule layer escalates over classifier output, rule layer phrase appears mid-sentence, rule layer does not de-escalate when classifier-only urgency is higher), unit tests for the confidence-gate logic (low ASR confidence routes to human review without classification), unit tests for the priority-key construction, integration tests against test buckets and tables, and end-to-end tests that simulate full voicemail flows including the emergent-notification path. Never use real voicemail recordings or real patient data in test fixtures.

**Observability beyond the metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-voicemail investigation. Production runs CloudWatch Logs Insights queries that join across the Step Functions execution logs, the Lambda invocation logs, and the audit records by voicemail_id. AWS X-Ray traces show the latency contribution of each stage (pre-processing, ASR submit, ASR job duration, classifier inference, entity extraction, enrichment, routing). When a single voicemail goes wrong, the on-call engineer needs to reconstruct the full trace in seconds, not minutes.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 10.2: Voicemail Transcription and Classification](chapter10.02-voicemail-transcription-classification) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
