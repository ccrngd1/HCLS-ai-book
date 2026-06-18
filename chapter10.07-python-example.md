# Recipe 10.7: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 10.7 (in-person ambient clinical documentation). It shows one way you could translate the pipeline into working Python using boto3 against AWS HealthScribe (streaming and batch), Amazon Transcribe Medical (as the alternative ASR primitive), Amazon Bedrock (with Guardrails for institutional-template note rendering and faithfulness checking), Amazon Comprehend Medical (for medication and condition extraction with RxNorm and ICD-10 coding), AWS Lambda, AWS Step Functions, Amazon API Gateway, Amazon Cognito, Amazon DynamoDB, Amazon S3, AWS KMS, AWS Secrets Manager, Amazon EventBridge, and Amazon CloudWatch. Optionally, Amazon Chime SDK or a vendor-managed in-room capture device sits in front of the audio path. The demo uses a `MockHealthScribeStreaming` standing in for the in-encounter streaming session, a `MockHealthScribeBatch` standing in for the post-encounter batch job, a `MockBedrock` standing in for the institutional-template rendering and faithfulness-checking LLM calls, a `MockComprehendMedical` standing in for the coded clinical-entity extraction, a `MockEHR` standing in for the FHIR-based note write-back and structured chart updates, and small helpers for the encounter-state table, the transcript-state table, the note-state table, the audio S3 bucket, the transcript S3 bucket, the audit S3 bucket, the EventBridge bus, and CloudWatch-style metrics. It is not production-ready. There is no real in-room device integration carrying audio frames through Chime SDK or a third-party capture appliance's API, no real Cognito authorizer, no real WebSocket-based streaming HealthScribe session, no real Bedrock invocation, no real Comprehend Medical inference, no real DynamoDB or S3 wiring, no Step Functions state machine, no IAM least-privilege role per Lambda, no KMS customer-managed key configuration, no VPC endpoints, no per-cohort accuracy disparity alerting, no behavioral-health profile with stricter retention, no production faithfulness-regression test suite, no real EHR FHIR write-back, no clinician-voiceprint enrollment store, and no production patient-portal release flow. Think of it as the sketchpad version: useful for understanding the shape of an in-room ambient documentation pipeline that respects the recording-consent discipline, the bystander-acknowledgement discipline, the audio-path engineering discipline, the diarization-with-movement discipline, the LLM-faithfulness discipline, the structured-extraction-with-explicit-confirmation discipline, the side-by-side-review discipline, and the cohort-stratified audit discipline this recipe demands. It is not something you would deploy to clinicians on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the seven core pseudocode steps from the main recipe: capture consent at encounter start, identify bystanders, and bootstrap the ambient session (Step 1), stream audio from the in-room device to HealthScribe streaming with VAD, beamforming, and movement-robust diarization (Step 2), run batch HealthScribe reprocessing for the canonical transcript and structured note draft (Step 3), render the institutional-template note from the HealthScribe draft using Bedrock with citation grounding and faithfulness checks (Step 4), extract structured clinical entities and present them for explicit clinician confirmation (Step 5), present the draft to the clinician for review-and-sign with side-by-side transcript display (Step 6), and audit, archive, retain audio per policy, and feed cohort-stratified accuracy monitoring (Step 7). The synthetic patients, providers, encounters, medications, and conversations in the demo are fictional; the names, MRNs, RxNorm codes, ICD-10 codes, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

Streaming HealthScribe and streaming Transcribe Medical are HTTP/2 services and are not exposed through the regular boto3 transcribe client. The streaming API is wrapped by a separate Python package:

```bash
pip install amazon-transcribe
```

In production you would also configure the in-room audio capture device (a clinician's iPad or iPhone with a vendor app, a wall-mount or desk-mount microphone-array appliance with beamforming DSP, or a ceiling-mounted far-field array), an Amazon Transcribe custom vocabulary per institution and per language, an optional Amazon Transcribe custom language model trained on institutional clinical text for higher accuracy on specialty-specific vocabulary, an Amazon Bedrock inference profile pinned to a specific note-rendering model and region, an Amazon Bedrock Guardrails configuration filtering clinical-advice and harmful-content categories, the Lambda functions that orchestrate each pipeline stage (the encounter-start handler, the audio-capture coordinator, the streaming-ASR result handler, the batch-reprocessing trigger, the institutional-rendering invoker, the faithfulness-check runner, the structured-field extractor, the EHR write-back, the audit writer), an AWS Step Functions state machine that durably orchestrates the post-encounter pipeline with retry semantics, DynamoDB tables that hold encounter state, transcript state, and note state across the lifecycle, AWS Secrets Manager secrets for the EHR API credentials and the patient-portal integration credentials, an Amazon EventBridge bus for cross-system events (`session_started`, `encounter_transcribed`, `note_generated`, `note_signed`, `encounter_audited`), Amazon S3 buckets for audio recordings (with brief-retention lifecycle), transcripts and generated notes (with medical-record retention), and the long-term audit archive (with Object Lock in compliance mode), and customer-managed KMS keys for every PHI-bearing data class. The demo replaces all of these with small mocks so the focus stays on the per-stage processing logic rather than on the cloud-resource provisioning.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `transcribe:StartMedicalScribeJob`, `transcribe:GetMedicalScribeJob`, `transcribe:ListMedicalScribeJobs` for batch HealthScribe; `transcribe:StartStreamTranscription` (via the streaming SDK) for streaming HealthScribe and streaming Transcribe Medical, with `transcribe:CreateVocabulary`, `transcribe:UpdateVocabulary`, `transcribe:GetVocabulary` for custom-vocabulary management
- `bedrock:InvokeModel` for the institutional-template rendering and faithfulness-checker models, scoped to the specific foundation-model ARNs and inference profiles in use
- `bedrock:ApplyGuardrail` for the runtime guardrails check on generated content
- `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM` for coded clinical-entity extraction
- `chime:CreateMediaCapturePipeline`, `chime:DeleteMediaCapturePipeline` plus `kinesisvideo:GetMedia`, `kinesisvideo:GetDataEndpoint` when Chime SDK is the audio path for institution-built capture experiences
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the encounter-state, transcript-state, and note-state tables
- `s3:GetObject`, `s3:PutObject` on the audio bucket, the transcript bucket, and the audit-archive bucket, scoped to the per-encounter key prefixes
- `secretsmanager:GetSecretValue` on the EHR-API credentials and patient-portal credential secrets pinned to the current rotation version
- `events:PutEvents` on the encounter-events EventBridge bus
- `cloudwatch:PutMetricData` for the operational metrics (per-stage latency, per-encounter audio quality, ASR confidence, faithfulness scores, edit-distance distributions, structured-extraction acceptance rates, per-clinician adoption)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the audio bucket, the transcript bucket, the audit bucket, the DynamoDB tables, and the Secrets Manager secrets
- `states:StartExecution` for the Step Functions state machine that orchestrates the post-encounter pipeline

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The encounter-start Lambda has scoped DynamoDB write for the encounter-state table only. The streaming-ASR-handler Lambda has scoped HealthScribe streaming session creation rights and write access to the transcript-state table only. The institutional-rendering Lambda has scoped Bedrock invocation rights pinned to one model and one inference profile. The structured-field-extractor Lambda has scoped Comprehend Medical inference rights only. The EHR-handoff Lambda has scoped Secrets Manager read for the EHR credentials and the EHR-specific egress path only. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Audio is PHI throughout, and biometric.** The microphone in the room captures the patient's voice (a biometric identifier), the clinician's voice, and any bystanders. The audio is PHI by HIPAA definition; in some jurisdictions (Illinois under BIPA, and similar statutes in Texas and Washington) the voiceprint itself is regulated as biometric data with specific consent and disclosure requirements. The architecture treats audio as PHI throughout: encrypted at rest with KMS customer-managed keys, encrypted in transit with TLS, retention bound by an explicit privacy-officer-reviewed policy (typically a few hours to a few days post-signing), BAAs in place for any vendor service that processes the audio.
- **The in-room audio path is where ambient documentation deployments most often quietly fail.** A great ASR with bad audio underperforms a mediocre ASR with good audio, almost without exception. The capture-device choice (clinician phone vs. wall-mounted microphone array vs. ceiling-mounted far-field array), the per-room acoustic survey, and the beamforming-and-noise-suppression configuration matter more than the choice of ASR vendor. The demo's `audio_capture_config` flag captures the device-type intent; production aggressively pursues per-room audio quality measurement before launch.
- **Diarization is the central engineering problem.** Two-speaker diarization (clinician + patient) in a clean room is a near-solved problem. Three-or-more-speaker diarization (clinician + patient + family member, pediatric encounters with the child, geriatric encounters with the caregiver, teaching encounters with the resident and student) in a real exam room with movement, overlap, and acoustically-similar voices is harder than published vendor benchmarks suggest. Clinician-voiceprint enrollment for high-volume users meaningfully helps. Bystander declaration at encounter start tells diarization the expected speaker count. Per-segment diarization confidence drives the review-UI flagging.
- **State-by-state recording-consent law applies.** For in-person ambient documentation, the clinic's location governs (unlike telehealth recipe 10.6 where the patient's location matters). All-party-consent jurisdictions require an explicit consent disclosure plus acknowledgment; one-party-consent jurisdictions require less but most institutions still play a recording notice. Behavioral-health visits may have additional state-level confidentiality requirements (42 CFR Part 2 for substance-use treatment records). The demo's `determine_consent_regime` and the behavioral-health profile sketch the pattern.
- **Bystander handling is workflow design, not a checkbox.** Family members, caregivers, students, and other bystanders are routine in clinical encounters. The clinician's confirmation at encounter start of who is in the room is the workflow-friendly approach. Production deployments build this into the device's start-of-encounter flow.
- **LLM faithfulness is a structural risk, not a side issue.** When an LLM generates a clinical note from a transcript, "may have" can become "had," "intermittent" can become "occasional," and clinical content the patient never said can be invented. Run the faithfulness check at runtime (Step 4E in the pseudocode); also maintain an offline evaluation set across specialties that gates production model and prompt updates on regression results. The demo's `run_faithfulness_check` is illustrative; production uses citation-based grounding verification, an LLM-judge faithfulness scoring pass, and clinical-rule-based contradiction detection in cascade.
- **Structured-field extractions require explicit clinician confirmation.** The medication-and-problem extraction occasionally pulls from passing mentions ("I used to take lisinopril years ago") rather than from active clinical content. Never silently apply a structured update from a transcript. The demo's `clinician_save_review` enforces accept-only writes with the supporting transcript context displayed alongside.
- **Per-cohort accuracy monitoring is a launch gate, not an analytics afterthought.** Voice ASR has well-documented accuracy disparities across speaker demographics; in-room ambient documentation adds room-acoustics variability on top. The cohort axes (per-language, per-specialty, per-clinician, per-patient-cohort, per-audio-quality-band, per-room) are policy-level decisions made with the equity-monitoring committee. The demo emits the cohort dimensions on every metric so you can see the segmentation pattern.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, and numeric metadata field passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses Chime SDK or vendor-device integration, multiple Lambdas, the Step Functions orchestration, the EventBridge fan-out, and the CloudWatch metric emission into a single Python file for readability.** In production each pipeline stage is a separate Lambda with its own IAM role, error handling, retries, and DLQs, with Step Functions as the durable orchestrator for the post-encounter workflow. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the per-specialty templates, the faithfulness thresholds, the consent disclosures, the recording-consent state lists, and the cohort axes are what you would change between environments.

```python
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights. The ambient documentation
# pipeline operates on heavily PHI-bearing data: the audio is
# PHI and biometric, the verbatim transcript is PHI, the
# generated note is PHI, the structured-field extractions are
# PHI, and every signature event is a clinical-record
# transaction. Log structural metadata only (session_id, ASR
# confidence band, faithfulness score band, signature event),
# never raw transcripts, never patient demographics, never
# medication or diagnosis values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from HealthScribe, Bedrock,
# Comprehend Medical, DynamoDB, S3, EventBridge, CloudWatch,
# and Secrets Manager. The streaming-display latency budget is
# tight (a couple of seconds end to end); the post-encounter
# batch budget is looser (a minute or two is acceptable). Cap
# the retries on the streaming path so the in-encounter
# display does not stall; let the batch path retry more
# aggressively because the clinician is no longer waiting in
# real time.
BOTO3_RETRY_CONFIG_STREAMING = Config(
    retries={"max_attempts": 2, "mode": "adaptive"})
BOTO3_RETRY_CONFIG_BATCH = Config(
    retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in
# warm containers so each invocation does not pay the
# connection cost. The demo below uses Mock* classes instead;
# the real clients are never invoked here. Note: streaming
# HealthScribe and streaming Transcribe Medical do not run
# through the boto3 transcribe client; they use the standalone
# amazon-transcribe-streaming-sdk Python package.
REGION = "us-east-1"
dynamodb               = boto3.resource("dynamodb", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG_BATCH)
s3_client              = boto3.client("s3", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG_BATCH)
transcribe_batch       = boto3.client("transcribe", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG_BATCH)
bedrock_runtime        = boto3.client("bedrock-runtime", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG_BATCH)
comprehend_medical     = boto3.client("comprehendmedical", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG_BATCH)
eventbridge_client     = boto3.client("events", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG_BATCH)
cloudwatch_client      = boto3.client("cloudwatch", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG_BATCH)
secrets_client         = boto3.client("secretsmanager", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG_BATCH)
stepfunctions_client   = boto3.client("stepfunctions", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG_BATCH)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo
# prints what it would write rather than failing if the
# resources do not exist; see run_demo() at the bottom.
ENCOUNTER_STATE_TABLE     = "ambient-doc-encounter-state"
TRANSCRIPT_STATE_TABLE    = "ambient-doc-transcript-state"
NOTE_STATE_TABLE          = "ambient-doc-note-state"
AUDIO_BUCKET              = "ambient-doc-audio"
TRANSCRIPT_BUCKET         = "ambient-doc-transcripts"
AUDIT_ARCHIVE_BUCKET      = "ambient-doc-audit-archive"
HEALTHSCRIBE_OUTPUT_BUCKET = "ambient-doc-healthscribe-output"
ENCOUNTER_EVENT_BUS_NAME  = "ambient-doc-events-bus"
CLOUDWATCH_NAMESPACE      = "AmbientDocumentation"
INSTITUTION_ID            = "academic-medical-center-richmond"
INSTITUTIONAL_VOCABULARY  = "ambient-doc-clinical-vocabulary"
INSTITUTIONAL_LANGUAGE_MODEL = "ambient-doc-clinical-lm-v2"
AMBIENT_DOC_GUARDRAIL_ID  = "guardrail-90123"
AMBIENT_DOC_GUARDRAIL_VERSION = "2"
HEALTHSCRIBE_DATA_ACCESS_ROLE_ARN = (
    "arn:aws:iam::000000000000:role/HealthScribeDataAccessRole")
OUTPUT_KMS_KEY_ARN = (
    "arn:aws:kms:us-east-1:000000000000:key/"
    "11111111-2222-3333-4444-555555555555")

# Bedrock configuration. In production, pin to a specific
# model version and inference profile so a model upgrade does
# not silently change note-rendering behavior. The model and
# region combination must be in your AWS BAA scope.
BEDROCK_NOTE_RENDERING_MODEL_ID = (
    "anthropic.claude-3-5-sonnet-20240620-v1:0")
BEDROCK_NOTE_RENDERING_PROFILE_ARN = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "ambient-doc-note-render-v1")
# A smaller, cheaper model is appropriate for the faithfulness
# check; the check is structurally simpler than the rendering.
BEDROCK_FAITHFULNESS_MODEL_ID = (
    "anthropic.claude-3-haiku-20240307-v1:0")
BEDROCK_FAITHFULNESS_PROFILE_ARN = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "ambient-doc-faithfulness-v1")
# Structured extraction uses the same Sonnet-class model as
# note rendering, but with a different prompt and a strict
# JSON-schema response format expressed via tool-use.
BEDROCK_EXTRACTION_MODEL_ID = (
    "anthropic.claude-3-5-sonnet-20240620-v1:0")

# Deploy-time guardrail. Any blank resource name is a deploy-
# time bug, not a runtime surprise.
for _name, _value in [
    ("ENCOUNTER_STATE_TABLE",     ENCOUNTER_STATE_TABLE),
    ("TRANSCRIPT_STATE_TABLE",    TRANSCRIPT_STATE_TABLE),
    ("NOTE_STATE_TABLE",          NOTE_STATE_TABLE),
    ("AUDIO_BUCKET",              AUDIO_BUCKET),
    ("TRANSCRIPT_BUCKET",         TRANSCRIPT_BUCKET),
    ("AUDIT_ARCHIVE_BUCKET",      AUDIT_ARCHIVE_BUCKET),
    ("HEALTHSCRIBE_OUTPUT_BUCKET", HEALTHSCRIBE_OUTPUT_BUCKET),
    ("ENCOUNTER_EVENT_BUS_NAME",  ENCOUNTER_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",      CLOUDWATCH_NAMESPACE),
    ("INSTITUTIONAL_VOCABULARY",  INSTITUTIONAL_VOCABULARY),
    ("BEDROCK_NOTE_RENDERING_MODEL_ID",
        BEDROCK_NOTE_RENDERING_MODEL_ID),
    ("BEDROCK_FAITHFULNESS_MODEL_ID",
        BEDROCK_FAITHFULNESS_MODEL_ID),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every encounter record carries the versions of the artifacts
# that influenced it: the streaming ASR model version, the
# batch ASR model version, the note-rendering prompt version,
# the faithfulness-check prompt version, the structured-
# extraction rules version, the per-specialty template
# version. A future audit reconstructs which configuration was
# active when a particular encounter was processed.
STREAMING_ASR_MODEL_VERSION   = "healthscribe-streaming-2026-q1"
BATCH_ASR_MODEL_VERSION       = "healthscribe-batch-2026-q1"
NOTE_RENDERING_PROMPT_VERSION = "note-render-prompt-v2.1"
FAITHFULNESS_PROMPT_VERSION   = "faithfulness-prompt-v1.3"
STRUCTURED_EXTRACTION_VERSION = "structured-extraction-v1.2"
TEMPLATE_LIBRARY_VERSION      = "templates-v3.0"

# --- ASR Confidence and Audio Quality Gates ---
# Average per-word confidence below this floor flags the
# transcript for QA review and surfaces a low-confidence flag
# to the reviewing clinician. The minimum-confidence-word
# threshold is a secondary gate: even a high-average-
# confidence transcript with several critical words at very
# low confidence (often medication names) deserves an explicit
# review highlight.
ASR_MIN_AVG_CONFIDENCE              = Decimal("0.85")
ASR_LOW_CONFIDENCE_WORD_THRESHOLD   = Decimal("0.70")
ASR_QA_REVIEW_LOW_CONF_WORD_LIMIT   = 5

# Audio quality SNR warning threshold. When per-encounter
# average SNR drops below this, the clinician's device gets
# an audio-quality warning so they can investigate the room
# acoustics or microphone placement before the encounter
# proceeds.
AUDIO_QUALITY_WARNING_THRESHOLD_DB  = Decimal("12.0")

# --- Faithfulness Threshold ---
# The faithfulness checker returns a score in [0, 1]; below
# this threshold, the draft is either blocked (severity=block)
# or flagged for the clinician's attention (severity=flag).
# Severity is determined per failure type by the institutional
# faithfulness program.
FAITHFULNESS_PASS_THRESHOLD     = Decimal("0.88")
FAITHFULNESS_BLOCK_THRESHOLD    = Decimal("0.65")

# --- Recording Consent Disclosures ---
# Production looks up the clinic's jurisdiction (for in-person
# ambient documentation, the clinic's location governs) and
# selects the appropriate disclosure. Behavioral-health visits
# use a different disclosure that explicitly mentions
# transcript handling and shorter retention.
CONSENT_DISCLOSURE_ALL_PARTY = (
    "Today's visit will be captured and transcribed for your "
    "medical record. To continue, please confirm by saying "
    "yes when the doctor asks.")
CONSENT_DISCLOSURE_ONE_PARTY = (
    "Today's visit will be captured and transcribed for your "
    "medical record.")
CONSENT_DISCLOSURE_BEHAVIORAL_HEALTH = (
    "Today's visit will be captured and transcribed for your "
    "medical record. The transcript will be retained as part "
    "of your behavioral health treatment record under our "
    "confidentiality policy. Please confirm to continue.")

# All-party-consent states. The list is approximate and
# changes over time as state law evolves; production maintains
# this in a legal-team-reviewed configuration with an explicit
# update cadence.
# TODO (TechWriter): verify the current all-party-consent state
# list against the Reporters Committee for Freedom of the Press
# state-by-state recording-laws guide before deploying.
ALL_PARTY_CONSENT_STATES = {
    "CA", "CT", "FL", "IL", "MD", "MA",
    "MT", "NV", "NH", "PA", "WA",
}

# Visit types that always trigger an explicit per-encounter
# disclosure regardless of the state regime, because the
# content is more sensitive and the patient's expectation of
# conversational privacy is higher.
SENSITIVE_VISIT_TYPES = {
    "behavioral_health",
    "substance_use_treatment",
    "reproductive_health_sensitive",
    "genetic_counseling",
}

# --- Cohort Axes ---
# Stratification axes used in the audit pipeline for equity
# monitoring. The age-band and primary-language are opt-in:
# the patient self-discloses during portal enrollment.
# Inferred demographic labels for protected classes are
# explicitly not used.
COHORT_AXES = ["language", "visit_type", "specialty",
               "audio_quality_band", "age_band", "room_id"]

# --- Per-Specialty Note Templates ---
# Production maintains per-specialty templates as versioned
# clinical-informatics assets. The demo includes a small
# subset to show the pattern.
DEFAULT_TEMPLATES = {
    "primary-care-soap-v3": {
        "id":       "primary-care-soap-v3",
        "specialty": "family_medicine",
        "structure": "SOAP",
        "sections": ["subjective", "objective",
                     "assessment", "plan"],
    },
    "behavioral-health-progress-v2": {
        "id":       "behavioral-health-progress-v2",
        "specialty": "behavioral_health",
        "structure": "behavioral_health_progress",
        "sections": ["presenting_concerns",
                     "mental_status_exam",
                     "risk_assessment", "interventions",
                     "plan"],
    },
    "geriatric-comprehensive-v1": {
        "id":       "geriatric-comprehensive-v1",
        "specialty": "geriatrics",
        "structure": "SOAP_with_function",
        "sections": ["subjective", "functional_status",
                     "objective", "assessment", "plan"],
    },
}

# --- Helper: float -> Decimal ---
# DynamoDB rejects native Python float. Every numeric value on
# its way into DynamoDB has to be a Decimal. This helper
# handles nested dicts and lists.
def _to_decimal(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_decimal(v) for v in value]
    return value

def _hash_value(value):
    """Stable hash for non-PHI audit linkage."""
    if not value:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _bucket_audio_quality(quality_metrics):
    """
    Categorize per-encounter audio quality into a small number
    of bands for cohort stratification. Production tunes these
    thresholds against the institution's actual audio-quality
    distribution. For in-room ambient documentation, the room
    acoustics and microphone placement drive most of the
    variation; the band is one of the strongest predictors of
    downstream transcript and note quality.
    """
    if not quality_metrics:
        return "unknown"
    avg_snr = quality_metrics.get("avg_snr_db", 0)
    if avg_snr >= 25:
        return "high"
    if avg_snr >= 15:
        return "medium"
    return "low"
```

---

## Mock Resources for the Demo

These mocks stand in for the production AWS resources and back-office systems. They are deliberately simple and are not how you would build the real thing. Their purpose is to keep the focus on the in-room ambient documentation pipeline logic.

```python
class MockHealthScribeStreaming:
    """
    Stands in for the streaming HealthScribe API used during
    the encounter. In production, the streaming API runs over
    HTTP/2 via the amazon-transcribe Python package and emits
    speaker-attributed transcript segments with clinical-
    content classification labels. The mock plays back canned
    per-segment streaming events so the pipeline can be
    exercised without a real audio source.
    """
    def __init__(self, fixture_segments):
        # fixture_segments is keyed by encounter_id, with each
        # entry a list of segment dicts that simulate what
        # would arrive on the streaming connection.
        self._fixtures = fixture_segments
        self.streamed = []

    def stream_session(self, session_id, encounter_id,
                         expected_speaker_count, language):
        """
        Yields streaming-event dicts from the in-room
        microphone. Production yields these as they arrive;
        the mock yields them in the order specified by the
        fixture, preserving each segment's speaker_role and
        segment_class so the downstream handlers see the same
        event shape they would get from real HealthScribe.
        """
        segments = self._fixtures.get(encounter_id, [])
        for segment in segments:
            event = {
                "session_id":      session_id,
                "speaker_role":    segment["speaker_role"],
                "transcript":      segment["text"],
                "is_partial":      False,
                "timestamp":       segment["timestamp"],
                "segment_class":
                    segment.get("segment_class", "hpi"),
                "diarization_confidence":
                    segment.get("diarization_confidence",
                                Decimal("0.92")),
                "average_word_confidence":
                    segment.get("confidence", Decimal("0.9")),
                "words": [{"word": w,
                           "confidence":
                               segment.get("confidence",
                                            Decimal("0.9"))}
                           for w in segment["text"].split()],
            }
            self.streamed.append(event)
            yield event

    def emit_audio_quality_events(self, session_id,
                                     encounter_id):
        """
        Production emits periodic audio-quality events
        (signal-to-noise ratio, speech-detection rate,
        acoustic-event detections) on the streaming session.
        The mock yields a single fixture quality reading so
        the downstream handler exercises the warning path
        when the room is noisy.
        """
        # The fixture key is per-encounter so different
        # scenarios can simulate different acoustic conditions.
        fixtures = {
            "encounter-2026-05-23-0411": {
                "signal_to_noise_db": Decimal("22.5"),
                "speech_detection_rate": Decimal("0.62"),
                "acoustic_events": [],
            },
            "encounter-2026-05-23-0412": {
                "signal_to_noise_db": Decimal("9.5"),
                "speech_detection_rate": Decimal("0.48"),
                "acoustic_events": [
                    {"type": "hallway_bleed",
                     "timestamp": "00:04:21"},
                    {"type": "door_open",
                     "timestamp": "00:11:08"},
                ],
            },
        }
        yield fixtures.get(encounter_id, {
            "signal_to_noise_db": Decimal("20.0"),
            "speech_detection_rate": Decimal("0.55"),
            "acoustic_events": [],
        })

class MockHealthScribeBatch:
    """
    Stands in for the batch HealthScribe API used after the
    encounter ends. In production this is
    transcribe_batch.start_medical_scribe_job(...) which
    produces a higher-accuracy transcript with full
    diarization plus a structured clinical note draft. The
    mock returns a canned full-encounter transcript and the
    HealthScribe-default SOAP note draft.
    """
    def __init__(self, fixture_transcripts, fixture_note_drafts):
        self._fixture_transcripts = fixture_transcripts
        self._fixture_note_drafts = fixture_note_drafts
        self.jobs_started = []

    def start_medical_scribe_job(self, job_name, encounter_id,
                                    audio_uri, language,
                                    max_speaker_labels,
                                    template_id):
        self.jobs_started.append({
            "job_name":           job_name,
            "encounter_id":       encounter_id,
            "audio_uri":          audio_uri,
            "language":           language,
            "max_speaker_labels": max_speaker_labels,
            "template_id":        template_id,
            "started_at":         _now_iso(),
        })
        # Return a fake job descriptor that "completes
        # immediately" for the demo.
        return {"MedicalScribeJobName": job_name,
                "MedicalScribeJobStatus": "COMPLETED"}

    def retrieve_transcript(self, encounter_id):
        return dict(self._fixture_transcripts.get(
            encounter_id, {}))

    def retrieve_note_draft(self, encounter_id):
        return dict(self._fixture_note_drafts.get(
            encounter_id, {}))

class MockBedrock:
    """
    Stands in for Amazon Bedrock's InvokeModel. Three
    invocation patterns: institutional-template note rendering
    (returns a structured note draft with citations,
    re-rendered from HealthScribe's default SOAP draft into
    the institution's preferred format), faithfulness check
    (returns a 0-to-1 score plus a list of any failed checks),
    and structured extraction (returns a JSON-schema-validated
    extraction object for higher-level fields Comprehend
    Medical does not directly extract).
    """
    def __init__(self, render_responses, faithfulness_responses,
                 extraction_responses):
        self._render_responses = render_responses
        self._faithfulness_responses = faithfulness_responses
        self._extraction_responses = extraction_responses
        self.invocations = []

    def render_institutional_note(self, encounter_id,
                                     transcript,
                                     healthscribe_draft,
                                     template, guardrail_id):
        # Production: bedrock_runtime.invoke_model with the
        # transcript, the HealthScribe SOAP draft, and the
        # institutional template structure in the prompt
        # context. Structured output for Anthropic Claude on
        # Bedrock is enforced through tool-use (the tools
        # field inside the body, with the structured-output
        # schema declared as a tool definition) or through a
        # system prompt that demands JSON. The guardrail is
        # applied at runtime via guardrailIdentifier and
        # guardrailVersion parameters on invoke_model.
        self.invocations.append({
            "type":         "note_rendering",
            "encounter_id": encounter_id,
            "template":     template["id"],
            "guardrail_id": guardrail_id,
        })
        response = self._render_responses.get(encounter_id, {
            "content":   {"sections": {}},
            "citations": [],
            "guardrail_action": "NONE",
        })
        return {"body": json.dumps(response,
                                     default=str)}

    def check_faithfulness(self, encounter_id, rendered_note,
                            transcript, ehr_context):
        # Production: bedrock_runtime.invoke_model with a
        # smaller model, prompted to score the rendered note
        # against the source transcript and EHR context for
        # citation grounding, absence of hallucinated content,
        # and clinical consistency.
        self.invocations.append({
            "type":         "faithfulness_check",
            "encounter_id": encounter_id,
        })
        response = self._faithfulness_responses.get(
            encounter_id, {
                "score":         0.95,
                "failed_checks": [],
                "annotations":   [],
            })
        return {"body": json.dumps(response,
                                     default=str)}

    def extract_higher_level_fields(self, encounter_id,
                                      transcript):
        # Production: bedrock_runtime.invoke_model for entities
        # Comprehend Medical does not directly extract (orders,
        # follow-up actions, patient-reported vitals,
        # patient-reported allergies, referrals).
        self.invocations.append({
            "type":         "structured_extraction",
            "encounter_id": encounter_id,
        })
        response = self._extraction_responses.get(
            encounter_id, {
                "orders_placed":           [],
                "labs_requested":          [],
                "imaging_requested":       [],
                "follow_up_appointments":  [],
                "patient_reported_vitals": [],
                "patient_reported_allergies": [],
                "referrals_placed":        [],
            })
        return {"body": json.dumps(response,
                                     default=str)}

class MockComprehendMedical:
    """
    Stands in for Amazon Comprehend Medical's
    DetectEntitiesV2, InferRxNorm, and InferICD10CM APIs.
    Used to extract coded medication and condition entities
    from the transcript with RxNorm and ICD-10 linking.
    """
    def __init__(self, entity_fixtures):
        self._fixtures = entity_fixtures
        self.invocations = []

    def detect_entities(self, text):
        self.invocations.append({"type": "detect_entities",
                                 "text_len": len(text)})
        return self._fixtures.get("detect_entities",
                                    {"Entities": []})

    def infer_rx_norm(self, text):
        self.invocations.append({"type": "infer_rx_norm",
                                 "text_len": len(text)})
        return self._fixtures.get("infer_rx_norm",
                                    {"Entities": []})

    def infer_icd10cm(self, text):
        self.invocations.append({"type": "infer_icd10cm",
                                 "text_len": len(text)})
        return self._fixtures.get("infer_icd10cm",
                                    {"Entities": []})

class MockEHR:
    """
    Stands in for the EHR's FHIR write surface for clinical
    notes (DocumentReference), structured chart updates
    (MedicationRequest, Condition, Observation, ServiceRequest),
    and patient-portal release. In production this is the EHR
    vendor's FHIR API authenticated through SMART on FHIR or
    backend-services authentication.
    """
    def __init__(self):
        self.documents_written = []
        self.chart_updates = []
        self.portal_releases = []

    def fetch_ehr_context(self, patient_id_hash):
        """
        Production reads the patient's allergies, current
        medications, problem list, recent labs, and recent
        imaging from the EHR to populate note sections that
        are not usually discussed aloud (and to give the
        faithfulness check a second grounding source). The
        mock returns a small synthetic context.
        """
        return {
            "allergies":     ["NKDA"],
            "medications":   [
                {"name": "metformin",  "dose": "1000 mg BID",
                 "rx_norm_code": "860975"},
                {"name": "lisinopril", "dose": "10 mg daily",
                 "rx_norm_code": "314076"},
            ],
            "problems":      [
                {"name": "Type 2 diabetes mellitus",
                 "icd_10_code": "E11.9"},
                {"name": "Essential hypertension",
                 "icd_10_code": "I10"},
            ],
            "recent_labs":   [],
            "recent_imaging": [],
        }

    def write_document_reference(self, patient_id, encounter_id,
                                   document_content, author,
                                   signed_at,
                                   idempotency_key):
        document_id = f"doc-{uuid.uuid4().hex[:10]}"
        self.documents_written.append({
            "document_id":      document_id,
            "patient_id":       patient_id,
            "encounter_id":     encounter_id,
            "document_content": document_content,
            "author":           author,
            "signed_at":        signed_at,
            "idempotency_key":  idempotency_key,
        })
        return {"document_id": document_id}

    def apply_structured_update(self, patient_id, update_kind,
                                  payload):
        self.chart_updates.append({
            "patient_id":   patient_id,
            "update_kind":  update_kind,  # medication, problem, etc.
            "payload":      dict(payload),
            "applied_at":   _now_iso(),
        })

    def release_to_portal(self, patient_id, summary,
                           release_at):
        self.portal_releases.append({
            "patient_id": patient_id,
            "summary":    summary,
            "release_at": release_at,
        })

class MockClinicianReviewClient:
    """
    Stands in for the clinician's review-and-sign web client.
    The demo simulates the clinician opening the review pane,
    confirming or rejecting structured-field extractions,
    making narrative edits, and signing.
    """
    def __init__(self):
        self._review_decisions = []
        self._signature = None
        self._note_edits = None

    def queue_review_decisions(self, decisions):
        self._review_decisions = list(decisions)

    def queue_note_edits(self, edits):
        self._note_edits = edits

    def queue_signature(self, signature):
        self._signature = dict(signature)

    def collect_review_decisions(self):
        decisions = list(self._review_decisions)
        self._review_decisions = []
        return decisions

    def collect_note_edits(self):
        edits = self._note_edits
        self._note_edits = None
        return edits

    def get_signature(self):
        signature = dict(self._signature or {
            "type":      "electronic",
            "method":    "password_plus_mfa",
            "timestamp": _now_iso(),
        })
        self._signature = None
        return signature

class MockEncounterState:
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

class MockTranscriptState:
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

    def append_streaming_segment(self, session_id, segment):
        existing = self._items.setdefault(
            session_id, {"session_id": session_id,
                          "streaming_segments": []})
        existing.setdefault("streaming_segments", []).append(
            dict(segment))

    def get_streaming_segments(self, session_id):
        return list(self._items.get(session_id, {})
                     .get("streaming_segments", []))

class MockNoteState:
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

class MockS3:
    """
    Stands in for S3 audio storage, transcript storage,
    HealthScribe output, and audit archive. Holds objects in
    memory keyed by (bucket, key). Production uses customer-
    managed KMS keys for encryption and lifecycle policies for
    retention.
    """
    def __init__(self):
        self._objects = {}

    def put_object(self, bucket, key, body, metadata=None):
        self._objects[(bucket, key)] = {
            "body":      body,
            "metadata":  dict(metadata or {}),
            "stored_at": _now_iso(),
        }
        return {"bucket": bucket, "key": key,
                "uri":    f"s3://{bucket}/{key}"}

    def get_object(self, bucket, key):
        return dict(self._objects.get((bucket, key), {}))

    def list(self, bucket=None):
        return [{"bucket": b, "key": k,
                 "metadata": v["metadata"]}
                for (b, k), v in self._objects.items()
                if bucket is None or b == bucket]

class MockEventBus:
    """
    Stands in for Amazon EventBridge. Lifecycle events flow
    here for cross-system fan-out: session_started,
    encounter_transcribed, note_generated, note_signed,
    encounter_audited.
    """
    def __init__(self):
        self.events = []

    def put_events(self, entries):
        for entry in entries:
            self.events.append(dict(entry))

class MockCloudWatch:
    """
    Stands in for CloudWatch metric emission. In production
    the metrics flow into dashboards and alarms.
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
encounter_state        = MockEncounterState()
transcript_state       = MockTranscriptState()
note_state             = MockNoteState()
ehr                    = MockEHR()
clinician_client       = MockClinicianReviewClient()
event_bus              = MockEventBus()
cloudwatch             = MockCloudWatch()
s3_store               = MockS3()
# healthscribe_streaming, healthscribe_batch_mock,
# bedrock_mock, and comprehend_mock are wired up in run_demo()
# with fixture data tailored to each scenario.
healthscribe_streaming = None
healthscribe_batch_mock = None
bedrock_mock           = None
comprehend_mock        = None

# Clinician voiceprint registry. Production stores enrolled
# clinician voiceprints (with consent, with biometric-data
# governance) and references them at session start so the
# diarization can label clinician segments directly. The mock
# stores opaque IDs.
CLINICIAN_VOICEPRINT_REGISTRY = {
    "clinician-patel":   "voiceprint-patel-abc123",
    "clinician-okonkwo": "voiceprint-okonkwo-def456",
}

def audit_log(event):
    """
    Sanitized audit print so you can see the sequence of
    decisions without leaking the underlying values.
    Production routes events to CloudWatch Logs Insights with
    structured JSON; ship to a SIEM if available.
    """
    safe_event = {k: v for k, v in event.items()
                  if k not in {"verbatim_transcript",
                                "rendered_note_text",
                                "patient_demographics",
                                "structured_decisions_raw"}}
    if "verbatim_transcript" in event:
        safe_event["verbatim_transcript_length"] = len(
            event["verbatim_transcript"] or "")
    if "rendered_note_text" in event:
        safe_event["rendered_note_text_length"] = len(
            event["rendered_note_text"] or "")
    logger.info("AUDIT %s", json.dumps(safe_event,
                                          default=str))
```

---

## Step 1: Capture Consent at Encounter Start, Identify Bystanders, and Bootstrap the Ambient Session

*The pseudocode calls this `ON encounter_start(...)`. When the clinician opens the encounter (typically by selecting the patient in the EHR and starting the visit), the system captures the appropriate recording-and-transcription consent (institutional-policy-driven, state-law-aware), identifies who is in the room (patient alone, patient + family, patient + caregiver, teaching encounter), and bootstraps an ambient-documentation session that links the encounter ID to the audio capture path. Skip the per-encounter bystander identification and the system risks recording someone who has not consented, which is both a privacy and compliance violation.*

```python
def determine_consent_regime(clinic_jurisdiction, visit_type):
    """
    For in-person ambient documentation, the clinic's location
    governs the recording-consent regime. Behavioral-health
    and other sensitive visit types use an explicit-
    acknowledgment disclosure regardless of the state regime.
    """
    if visit_type in SENSITIVE_VISIT_TYPES:
        return "behavioral_health_explicit"
    if clinic_jurisdiction in ALL_PARTY_CONSENT_STATES:
        return "all_party_consent"
    return "one_party_consent"

def select_disclosure_text(consent_regime):
    """Return the disclosure text for the regime."""
    if consent_regime == "behavioral_health_explicit":
        return CONSENT_DISCLOSURE_BEHAVIORAL_HEALTH
    if consent_regime == "all_party_consent":
        return CONSENT_DISCLOSURE_ALL_PARTY
    return CONSENT_DISCLOSURE_ONE_PARTY

def lookup_feature_status(clinician_id, visit_type):
    """
    Per-clinician and per-visit-type feature status lookup.
    Some clinicians opt out entirely; some institutions
    exclude certain visit types (behavioral-health is the
    most common exclusion).
    """
    # Production reads from a per-institution policy table.
    # The demo defaults all encounters to enabled.
    return {"enabled": True, "reason": "default_enabled"}

def configure_audio_capture(room_id, session_id, device_type,
                              expected_speaker_count):
    """
    Configure the in-room audio capture path. Production
    reads the per-room device metadata (which device is
    deployed, what its capabilities are) and sets up the
    streaming session. The demo collapses this to a config
    dict that downstream stages reference.
    """
    return {
        "room_id":                room_id,
        "session_id":             session_id,
        "device_type":            device_type,
        # Possible device_type values:
        #   clinician_tablet, wall_mounted_array,
        #   ceiling_mounted_array, lavalier_with_room_array.
        "encoding":               "pcm",
        "sample_rate":            16000,
        "expected_speaker_count": expected_speaker_count,
        "beamforming_enabled":
            device_type != "clinician_tablet",
        "noise_suppression":      "moderate",
        "vad_enabled":            True,
        "audio_stream_path":
            f"audio/{session_id}/encounter.pcm",
    }

def check_voiceprint_enrollment(clinician_id):
    """
    Look up whether the clinician has an enrolled voiceprint.
    Voiceprint enrollment is biometric-data governance
    territory (Illinois BIPA, Texas, Washington each have
    specific consent and disclosure rules); production gates
    enrollment behind explicit clinician consent and an
    institutional review.
    """
    return clinician_id in CLINICIAN_VOICEPRINT_REGISTRY

def encounter_start(encounter_id, patient_id, clinician_id,
                     clinician_specialty, clinic_jurisdiction,
                     visit_type, room_id,
                     bystanders=None,
                     device_type="wall_mounted_array",
                     language="en-US",
                     consent_acknowledged=True):
    """
    Start an ambient-documentation session in response to an
    encounter-start event. Captures consent, identifies
    bystanders, and bootstraps the encounter state.

    Args:
        encounter_id: Encounter identifier from the EHR.
        patient_id: Patient identifier (will be hashed in
            persistent state).
        clinician_id: Authenticated clinician identifier.
        clinician_specialty: Specialty key used for template
            selection.
        clinic_jurisdiction: Two-letter state code for the
            clinic's location (governs recording-consent
            regime for in-person encounters).
        visit_type: e.g. "primary_care", "behavioral_health",
            "geriatric_followup".
        room_id: Per-room identifier so the audit can stratify
            by room (room acoustics drive per-cohort accuracy).
        bystanders: List of bystander descriptors (e.g.
            ["family_member", "caregiver"]).
        device_type: In-room capture device type.
        language: Encounter language. Defaults to en-US.
        consent_acknowledged: For the demo, whether the
            patient acknowledged the disclosure.

    Returns:
        Session-context dict consumed by downstream stages, or
        a sentinel indicating the patient declined or the
        feature was disabled.
    """
    bystanders = list(bystanders or [])

    # Step 1A: determine the recording-consent regime.
    consent_regime = determine_consent_regime(
        clinic_jurisdiction=clinic_jurisdiction,
        visit_type=visit_type)
    disclosure_text = select_disclosure_text(consent_regime)

    # Step 1B: determine whether ambient documentation is
    # enabled for this clinician + visit-type combination.
    feature_status = lookup_feature_status(
        clinician_id=clinician_id, visit_type=visit_type)
    if not feature_status["enabled"]:
        audit_log({
            "event_type":   "AMBIENT_FEATURE_DISABLED",
            "encounter_id": encounter_id,
            "reason":       feature_status["reason"],
            "timestamp":    _now_iso(),
        })
        return {"feature_enabled": False,
                "reason":           feature_status["reason"]}

    # Step 1C: capture consent disclosure. For all-party-
    # consent jurisdictions and sensitive visit types, gate
    # continuation on explicit acknowledgment. Production
    # plays the disclosure through the in-room device's
    # speaker; the demo records the disclosure text.
    requires_acknowledgment = consent_regime in (
        "all_party_consent", "behavioral_health_explicit")
    if requires_acknowledgment and not consent_acknowledged:
        audit_log({
            "event_type":     "AMBIENT_DECLINED_BY_PATIENT",
            "encounter_id":   encounter_id,
            "consent_regime": consent_regime,
            "timestamp":      _now_iso(),
        })
        return {"feature_enabled": False,
                "reason":           "consent_declined",
                "consent_regime":   consent_regime}

    # Step 1D: bootstrap the ambient session.
    session_id = "amb-" + uuid.uuid4().hex[:16]
    started_at = _now_iso()

    # The clinician declares who is in the room. The
    # diarization layer uses the expected speaker count;
    # the consent record captures who is being captured.
    expected_speaker_count = 1 + len(bystanders)  # patient + others

    audio_capture_config = configure_audio_capture(
        room_id=room_id,
        session_id=session_id,
        device_type=device_type,
        expected_speaker_count=expected_speaker_count)

    voiceprint_enrolled = check_voiceprint_enrollment(
        clinician_id)

    encounter_state.put(session_id, _to_decimal({
        "session_id":              session_id,
        "encounter_id":            encounter_id,
        "patient_id_hash":         _hash_value(patient_id),
        "clinician_id":            clinician_id,
        "clinician_specialty":     clinician_specialty,
        "room_id":                 room_id,
        "visit_type":              visit_type,
        "language":                language,
        "consent_regime":          consent_regime,
        "bystanders":              bystanders,
        "expected_speaker_count":  expected_speaker_count,
        "feature_status":          "enabled",
        "started_at":              started_at,
        "device_type":             device_type,
        "audio_capture_config":    audio_capture_config,
        "audio_archive_ref":       None,
        "canonical_transcript_ref": None,
        "healthscribe_note_draft_ref": None,
        "clinician_voiceprint_enrolled": voiceprint_enrolled,
        "avg_audio_quality_snr":   Decimal("0.0"),
        "avg_streaming_asr_confidence": Decimal("0.0"),
        "avg_batch_asr_confidence":     Decimal("0.0"),
        "diarization_disagreement_count": 0,
        "streaming_asr_model_version":   STREAMING_ASR_MODEL_VERSION,
        "batch_asr_model_version":       BATCH_ASR_MODEL_VERSION,
        "note_rendering_prompt_version":
            NOTE_RENDERING_PROMPT_VERSION,
        "faithfulness_prompt_version":
            FAITHFULNESS_PROMPT_VERSION,
        "structured_extraction_version":
            STRUCTURED_EXTRACTION_VERSION,
        "template_library_version":
            TEMPLATE_LIBRARY_VERSION,
    }))

    # Step 1E: emit lifecycle event.
    event_bus.put_events([{
        "Source":       "ambient_documentation",
        "DetailType":   "session_started",
        "EventBusName": ENCOUNTER_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":      session_id,
            "encounter_id":    encounter_id,
            "visit_type":      visit_type,
            "language":        language,
            "consent_regime":  consent_regime,
            "bystander_count": len(bystanders),
            "device_type":     device_type,
            "room_id":         room_id,
            "timestamp":       started_at,
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "SessionsStarted", 1, "Count",
        dimensions={"visit_type":   visit_type,
                    "language":     language,
                    "specialty":    clinician_specialty,
                    "device_type":  device_type})

    audit_log({
        "event_type":              "AMBIENT_SESSION_OPENED",
        "session_id":              session_id,
        "encounter_id":            encounter_id,
        "visit_type":              visit_type,
        "consent_regime":          consent_regime,
        "language":                language,
        "device_type":             device_type,
        "expected_speaker_count":  expected_speaker_count,
        "voiceprint_enrolled":     voiceprint_enrolled,
        "timestamp":               started_at,
    })

    return {
        "feature_enabled":      True,
        "session_id":           session_id,
        "encounter_id":         encounter_id,
        "patient_id":           patient_id,
        "clinician_id":         clinician_id,
        "clinician_specialty":  clinician_specialty,
        "room_id":              room_id,
        "visit_type":           visit_type,
        "language":             language,
        "consent_regime":       consent_regime,
        "bystanders":           bystanders,
        "expected_speaker_count": expected_speaker_count,
        "device_type":          device_type,
        "audio_capture_config": audio_capture_config,
        "voiceprint_enrolled":  voiceprint_enrolled,
        "started_at":           started_at,
        "disclosure_text":      disclosure_text,
    }
```

---

## Step 2: Stream Audio from the In-Room Device to HealthScribe Streaming

*The pseudocode calls this `stream_audio_to_healthscribe(...)`. As audio is captured by the in-room device, voice activity detection and beamforming at the device produce a cleaned audio stream that is sent to HealthScribe streaming. The streaming pipeline produces a rolling speaker-attributed transcript with per-segment clinical-content classification and confidence. Skip the device-side audio cleanup and the cloud ASR receives audio with significantly more noise and reverberation than necessary, with measurable accuracy impact.*

```python
def push_audio_quality_warning(session_id, quality):
    """
    Production pushes an audio-quality warning to the
    clinician's device or to a discreet display. The mock
    just logs the warning. Common sources of quality drops:
    HVAC noise, microphone too far from active speaker,
    adjacent-room sound bleed, the clinician walking out of
    the device's beamforming sweet spot.
    """
    audit_log({
        "event_type":           "AUDIO_QUALITY_WARNING",
        "session_id":           session_id,
        "signal_to_noise_db":
            float(quality.get("signal_to_noise_db", 0)),
        "speech_detection_rate":
            float(quality.get("speech_detection_rate", 0)),
        "acoustic_event_count":
            len(quality.get("acoustic_events", [])),
        "timestamp":            _now_iso(),
    })

def stream_audio_to_healthscribe(session_context):
    """
    Run the streaming HealthScribe session for the encounter.
    HealthScribe handles ASR, diarization, role assignment
    (CLINICIAN, PATIENT, FAMILY, OTHER), and clinical-content
    classification together; the demo's mock simulates the
    same per-segment event flow.
    """
    session_id = session_context["session_id"]
    encounter_id = session_context["encounter_id"]
    audio_capture_config = session_context["audio_capture_config"]
    language = session_context["language"]
    state = encounter_state.get(session_id)

    # Step 2A: configure the streaming session. Production
    # passes max_speaker_labels (so HealthScribe knows the
    # expected speaker count from the clinician's bystander
    # declaration), the institutional vocabulary, and the
    # clinician voiceprint hint when enrollment is available.
    #
    # In production:
    #   client = TranscribeStreamingClient(region=REGION)
    #   stream = await client.start_stream_transcription(
    #       language_code=language,
    #       media_sample_rate_hz=audio_capture_config["sample_rate"],
    #       media_encoding=audio_capture_config["encoding"],
    #       vocabulary_name=INSTITUTIONAL_VOCABULARY,
    #       language_model_name=INSTITUTIONAL_LANGUAGE_MODEL,
    #       show_speaker_label=True,
    #       max_speaker_labels=audio_capture_config[
    #           "expected_speaker_count"],
    #       enable_partial_results_stabilization=True)
    #
    # HealthScribe-specific streaming exposes role labels
    # (CLINICIAN, PATIENT, FAMILY, OTHER) and clinical
    # classification (CHIEF_COMPLAINT, HPI, ROS, EXAM, etc.).
    # The mock yields canned segments with these labels
    # already assigned.

    streaming_confidence_sum = Decimal("0.0")
    streaming_segment_count = 0
    diarization_confidence_sum = Decimal("0.0")

    # Step 2B: process each segment as it arrives.
    for event in healthscribe_streaming.stream_session(
            session_id=session_id,
            encounter_id=encounter_id,
            expected_speaker_count=
                audio_capture_config["expected_speaker_count"],
            language=language):

        handle_streaming_segment(
            session_id=session_id,
            event=event,
            language=language,
            specialty=session_context["clinician_specialty"])

        streaming_confidence_sum += Decimal(str(
            event["average_word_confidence"]))
        diarization_confidence_sum += Decimal(str(
            event["diarization_confidence"]))
        streaming_segment_count += 1

    # Step 2C: monitor per-encounter audio quality.
    avg_snr = Decimal("0.0")
    for quality in healthscribe_streaming.emit_audio_quality_events(
            session_id=session_id, encounter_id=encounter_id):
        avg_snr = quality.get("signal_to_noise_db",
                              Decimal("0.0"))
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "AudioQualitySNR",
            float(avg_snr), "None",
            dimensions={
                "room_id":     state.get("room_id", "unknown"),
                "device_type":
                    state.get("device_type", "unknown"),
                "visit_type":
                    session_context["visit_type"],
            })
        if avg_snr < AUDIO_QUALITY_WARNING_THRESHOLD_DB:
            push_audio_quality_warning(session_id, quality)
        # Persist acoustic events to the audit pipeline. A
        # door-open event might explain a brief diarization
        # confusion later in the encounter; a hallway-bleed
        # event might explain low-confidence segments that
        # should be excluded from the note.
        for acoustic_event in quality.get("acoustic_events", []):
            audit_log({
                "event_type":           "ACOUSTIC_EVENT",
                "session_id":           session_id,
                "acoustic_event_type":
                    acoustic_event.get("type"),
                "acoustic_event_timestamp":
                    acoustic_event.get("timestamp"),
                "timestamp":            _now_iso(),
            })

    avg_streaming_confidence = (
        (streaming_confidence_sum / streaming_segment_count)
        if streaming_segment_count else Decimal("0.0"))
    avg_diarization_confidence = (
        (diarization_confidence_sum / streaming_segment_count)
        if streaming_segment_count else Decimal("0.0"))

    encounter_state.update(session_id, _to_decimal({
        "avg_audio_quality_snr":         avg_snr,
        "avg_streaming_asr_confidence":  avg_streaming_confidence,
        "avg_diarization_confidence":
            avg_diarization_confidence,
        "streaming_segment_count":       streaming_segment_count,
    }))

    audit_log({
        "event_type":              "STREAMING_SESSION_COMPLETED",
        "session_id":              session_id,
        "segments_processed":      streaming_segment_count,
        "avg_streaming_confidence":
            float(avg_streaming_confidence),
        "avg_diarization_confidence":
            float(avg_diarization_confidence),
        "avg_audio_quality_snr":   float(avg_snr),
        "timestamp":               _now_iso(),
    })

    return {
        "session_id":                session_id,
        "segments_processed":        streaming_segment_count,
        "avg_streaming_confidence":  avg_streaming_confidence,
        "avg_diarization_confidence":
            avg_diarization_confidence,
        "avg_audio_quality_snr":     avg_snr,
    }

def handle_streaming_segment(session_id, event, language,
                                specialty):
    """
    Persist the streaming segment metadata (verbatim text
    goes to the transcript-archive S3 bucket rather than
    DynamoDB to avoid creating a parallel PHI store outside
    the standard audit governance), update the live display,
    and emit per-segment quality metrics.
    """
    transcript_state.append_streaming_segment(
        session_id=session_id,
        segment={
            "speaker_role":   event["speaker_role"],
            "text":           event["transcript"],
            "is_final":       not event["is_partial"],
            "words":          event["words"],
            "timestamp":      event["timestamp"],
            "segment_class":  event["segment_class"],
            "average_word_confidence":
                event["average_word_confidence"],
            "diarization_confidence":
                event["diarization_confidence"],
        })

    # Production pushes the segment to the clinician's live
    # display via an API Gateway WebSocket or server-sent
    # event. The demo just records the metric.
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "StreamingASRConfidence",
        float(event["average_word_confidence"]), "None",
        dimensions={
            "speaker_role": event["speaker_role"],
            "language":     language,
            "specialty":    specialty,
        })
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "DiarizationConfidence",
        float(event["diarization_confidence"]), "None",
        dimensions={
            "speaker_role": event["speaker_role"],
            "language":     language,
            "specialty":    specialty,
        })
```

---

## Step 3: Run Batch HealthScribe Reprocessing for the Canonical Transcript and Structured Note Draft

*The pseudocode calls this `run_batch_healthscribe(...)`. When the encounter ends, a batch HealthScribe job runs over the full audio with full discourse context, producing the canonical transcript with diarization plus a HealthScribe-default structured clinical note draft. The batch output is the canonical record. Skip the batch reprocessing and the canonical transcript is the streaming output, which is fine for navigation but suboptimal for the documentation that will end up in the chart.*

```python
def select_template(visit_type, specialty):
    """
    Production maintains per-specialty per-visit-type
    templates as versioned clinical-informatics assets. The
    demo uses a small fixed mapping.
    """
    if visit_type == "behavioral_health":
        return DEFAULT_TEMPLATES["behavioral-health-progress-v2"]
    if specialty == "geriatrics":
        return DEFAULT_TEMPLATES["geriatric-comprehensive-v1"]
    return DEFAULT_TEMPLATES["primary-care-soap-v3"]

def run_batch_healthscribe(session_context,
                              audio_archive_ref):
    """
    Trigger the batch HealthScribe job over the full audio.
    HealthScribe batch produces a higher-accuracy transcript
    plus a structured clinical note draft organized by
    section (Subjective, Objective, Assessment, Plan by
    default). The mock returns canned fixtures.
    """
    session_id = session_context["session_id"]
    encounter_id = session_context["encounter_id"]
    state = encounter_state.get(session_id)
    template = select_template(
        visit_type=session_context["visit_type"],
        specialty=session_context["clinician_specialty"])

    # In production:
    #   transcribe_batch.start_medical_scribe_job(
    #       MedicalScribeJobName=f"{session_id}-batch",
    #       Media={"MediaFileUri": audio_archive_ref},
    #       OutputBucketName=HEALTHSCRIBE_OUTPUT_BUCKET,
    #       OutputEncryptionKMSKeyId=OUTPUT_KMS_KEY_ARN,
    #       DataAccessRoleArn=
    #           HEALTHSCRIBE_DATA_ACCESS_ROLE_ARN,
    #       Settings={
    #           "ShowSpeakerLabels": True,
    #           "MaxSpeakerLabels":
    #               state["expected_speaker_count"],
    #           "ChannelIdentification": False,
    #           "VocabularyName": INSTITUTIONAL_VOCABULARY,
    #           "ClinicalNoteGenerationSettings": {
    #               "NoteTemplate": template["id"],
    #           },
    #       })
    # Then poll get_medical_scribe_job until COMPLETED. The
    # mock collapses this to a single call that returns
    # immediately.
    job_name = f"{session_id}-batch-{uuid.uuid4().hex[:6]}"
    job = healthscribe_batch_mock.start_medical_scribe_job(
        job_name=job_name,
        encounter_id=encounter_id,
        audio_uri=audio_archive_ref,
        language=session_context["language"],
        max_speaker_labels=state.get("expected_speaker_count",
                                     2),
        template_id=template["id"])

    canonical_transcript = (
        healthscribe_batch_mock.retrieve_transcript(
            encounter_id=encounter_id))
    healthscribe_note_draft = (
        healthscribe_batch_mock.retrieve_note_draft(
            encounter_id=encounter_id))

    # Step 3D: persist the canonical transcript and the
    # HealthScribe-default note draft to S3 with KMS
    # encryption. Production additionally writes references
    # to the encounter-state and transcript-state tables.
    transcript_object = s3_store.put_object(
        bucket=TRANSCRIPT_BUCKET,
        key=f"{session_id}/canonical_transcript.json",
        body=json.dumps(canonical_transcript,
                          default=str).encode("utf-8"),
        metadata={"session_id":   session_id,
                   "encounter_id": encounter_id})

    note_draft_object = s3_store.put_object(
        bucket=HEALTHSCRIBE_OUTPUT_BUCKET,
        key=f"{session_id}/healthscribe_note_draft.json",
        body=json.dumps(healthscribe_note_draft,
                          default=str).encode("utf-8"),
        metadata={"session_id":   session_id,
                   "encounter_id": encounter_id})

    # Compute average batch confidence for the cohort metrics.
    batch_confidence_sum = Decimal("0.0")
    batch_segment_count = 0
    for seg in canonical_transcript.get("segments", []):
        batch_confidence_sum += Decimal(str(
            seg.get("confidence", 0.9)))
        batch_segment_count += 1
    avg_batch_confidence = (
        (batch_confidence_sum / batch_segment_count)
        if batch_segment_count else Decimal("0.0"))

    encounter_state.update(session_id, _to_decimal({
        "canonical_transcript_ref":    transcript_object["uri"],
        "healthscribe_note_draft_ref":
            note_draft_object["uri"],
        "batch_completed_at":          _now_iso(),
        "avg_batch_asr_confidence":    avg_batch_confidence,
    }))

    transcript_state.update(session_id, _to_decimal({
        "canonical_transcript_ref": transcript_object["uri"],
        "batch_segment_count":       batch_segment_count,
    }))

    event_bus.put_events([{
        "Source":       "ambient_documentation",
        "DetailType":   "encounter_transcribed",
        "EventBusName": ENCOUNTER_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":     session_id,
            "encounter_id":   encounter_id,
            "avg_batch_confidence":
                float(avg_batch_confidence),
            "segment_count":  batch_segment_count,
        }),
    }])

    audit_log({
        "event_type":              "BATCH_HEALTHSCRIBE_COMPLETED",
        "session_id":              session_id,
        "job_name":                job["MedicalScribeJobName"],
        "segment_count":           batch_segment_count,
        "avg_batch_confidence":
            float(avg_batch_confidence),
        "canonical_transcript_ref":
            transcript_object["uri"],
        "timestamp":               _now_iso(),
    })

    return {
        "canonical_transcript":     canonical_transcript,
        "healthscribe_note_draft":  healthscribe_note_draft,
        "canonical_transcript_ref": transcript_object["uri"],
    }
```

---

## Step 4: Render the Institutional-Template Note from the HealthScribe Draft Using Bedrock

*The pseudocode calls this `render_institutional_note(...)`. HealthScribe's default note format may not match the institution's preferred template. The Bedrock-rendering step takes the HealthScribe structured output plus the canonical transcript plus the EHR context and produces the institution-specific note format. Every claim in the rendered note carries a citation back to the supporting transcript segment or EHR source. A faithfulness-check pass scores the rendered note against the source for fabrication and contradictions. Skip the faithfulness check and the rendered note may include fluent-sounding clinical content that the patient never said, which is the worst class of failure for this recipe.*

```python
def lookup_clinician_style(clinician_id):
    """
    Per-clinician style preferences (terse SOAP vs. narrative
    HPI prose, specific phrasing preferences). Production
    learns these from the clinician's prior signed notes (with
    consent) or captures them through explicit configuration.
    The demo returns an empty preference set.
    """
    return {"prefer_narrative_hpi": False,
            "prefer_terse_assessment": False,
            "specific_phrasings": []}

def determine_faithfulness_severity(failed_checks, score):
    """
    Map faithfulness-check results to a severity level.
    Production's mapping is policy-owned by the clinical-
    quality officer; the demo collapses to a simple threshold
    plus a check-type lookup. Severe failures (claim_without_
    citation, contradiction_with_transcript) block the draft
    from being shown at all; minor failures flag for clinician
    attention.
    """
    if score < FAITHFULNESS_BLOCK_THRESHOLD:
        return "block"

    severe_check_types = {
        "claim_without_citation",
        "contradiction_with_transcript",
        "added_clinical_recommendation",
        "fabricated_exam_finding",
        "fabricated_medication",
    }
    for check in failed_checks or []:
        if check.get("type") in severe_check_types:
            return "block"
        if check.get("severity") == "severe":
            return "block"

    if score < FAITHFULNESS_PASS_THRESHOLD:
        return "flag"
    return "pass"

def run_faithfulness_check(session_context, rendered_note,
                             canonical_transcript, ehr_context):
    """
    Verify that every claim in the rendered note has a
    transcript citation or an EHR-source citation, score the
    rendered content for citation grounding, and detect
    contradictions or out-of-scope additions. Production runs
    this as a cascade of cheaper rule-based checks (citation
    presence, named-entity contradiction) followed by an
    LLM-judge pass for the harder cases. The demo collapses
    to a single LLM call.
    """
    session_id = session_context["session_id"]
    encounter_id = session_context["encounter_id"]

    response = bedrock_mock.check_faithfulness(
        encounter_id=encounter_id,
        rendered_note=rendered_note,
        transcript=canonical_transcript,
        ehr_context=ehr_context)

    body = json.loads(response["body"])
    score = Decimal(str(body.get("score", 0.0)))
    failed_checks = body.get("failed_checks", [])
    annotations = body.get("annotations", [])

    severity = determine_faithfulness_severity(
        failed_checks=failed_checks, score=score)

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "FaithfulnessScore",
        float(score), "None",
        dimensions={
            "specialty":  session_context["clinician_specialty"],
            "language":   session_context["language"],
            "visit_type": session_context["visit_type"],
        })
    if severity != "pass":
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "FaithfulnessFailures",
            1, "Count",
            dimensions={
                "severity":   severity,
                "specialty":  session_context["clinician_specialty"],
                "language":   session_context["language"],
            })

    audit_log({
        "event_type":           "FAITHFULNESS_CHECK_RUN",
        "session_id":           session_id,
        "score":                float(score),
        "severity":             severity,
        "failed_check_count":   len(failed_checks),
        "timestamp":            _now_iso(),
    })

    return {
        "score":         score,
        "severity":      severity,
        "failed_checks": failed_checks,
        "annotations":   annotations,
    }

def render_institutional_note(session_context,
                                 canonical_transcript,
                                 healthscribe_note_draft):
    """
    Render the institutional-template note from the
    HealthScribe draft, the canonical transcript, and the
    EHR context. Run the faithfulness check before persisting
    the draft. If the faithfulness check blocks the draft,
    fall back to manual documentation and surface the failure
    to the clinical-quality team via the audit pipeline.
    """
    session_id = session_context["session_id"]
    encounter_id = session_context["encounter_id"]
    state = encounter_state.get(session_id)

    # Step 4A: load the per-specialty template.
    template = select_template(
        visit_type=session_context["visit_type"],
        specialty=session_context["clinician_specialty"])

    # Step 4B: assemble EHR context. Production reads from
    # the EHR's FHIR API; the mock returns a synthetic
    # context dict.
    ehr_context = ehr.fetch_ehr_context(
        patient_id_hash=state.get("patient_id_hash"))

    # Step 4D: invoke Bedrock to render the note. Production
    # calls bedrock_runtime.invoke_model with the transcript
    # as grounding source, the HealthScribe SOAP draft as a
    # starting point, the EHR context as additional grounding,
    # the institutional template structure, and the per-
    # clinician style preferences. The Guardrails policy is
    # applied at runtime.
    note_response = bedrock_mock.render_institutional_note(
        encounter_id=encounter_id,
        transcript=canonical_transcript,
        healthscribe_draft=healthscribe_note_draft,
        template=template,
        guardrail_id=AMBIENT_DOC_GUARDRAIL_ID)

    note_body = json.loads(note_response["body"])
    rendered_content = note_body.get("content", {})
    citations = note_body.get("citations", [])
    guardrail_action = note_body.get("guardrail_action", "NONE")

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "NoteRenderingInvocations",
        1, "Count",
        dimensions={
            "specialty": session_context["clinician_specialty"],
            "template":  template["id"],
        })

    # Check for Guardrail intervention. Production routes
    # this to the clinical-quality team for review; the
    # clinician falls back to manual documentation.
    if guardrail_action == "INTERVENED":
        audit_log({
            "event_type":      "GUARDRAIL_BLOCKED_NOTE",
            "session_id":      session_id,
            "guardrail_id":    AMBIENT_DOC_GUARDRAIL_ID,
            "timestamp":       _now_iso(),
        })
        note_state.put(session_id, _to_decimal({
            "session_id":      session_id,
            "draft_available": False,
            "block_reason":    "guardrail_intervention",
            "fallback":        "manual_documentation",
            "generated_at":    _now_iso(),
        }))
        return {"draft_available": False,
                "reason":          "guardrail_intervention",
                "fallback":        "manual_documentation"}

    # Step 4E: faithfulness check. Verify that every claim in
    # the rendered note has a transcript or EHR citation and
    # that the cited content actually supports the claim.
    faithfulness_result = run_faithfulness_check(
        session_context=session_context,
        rendered_note=rendered_content,
        canonical_transcript=canonical_transcript,
        ehr_context=ehr_context)

    if faithfulness_result["severity"] == "block":
        # The draft is too unreliable to show; the clinician
        # falls back to manual documentation. The audit
        # captures the failure for clinical-quality review.
        audit_log({
            "event_type":           "NOTE_DRAFT_BLOCKED",
            "session_id":           session_id,
            "faithfulness_score":
                float(faithfulness_result["score"]),
            "failed_checks":
                faithfulness_result["failed_checks"],
            "timestamp":            _now_iso(),
        })
        note_state.put(session_id, _to_decimal({
            "session_id":           session_id,
            "draft_available":      False,
            "block_reason":         "faithfulness_block",
            "faithfulness_score":
                faithfulness_result["score"],
            "faithfulness_failed_checks":
                faithfulness_result["failed_checks"],
            "fallback":             "manual_documentation",
            "generated_at":         _now_iso(),
            "model_version":
                BEDROCK_NOTE_RENDERING_MODEL_ID,
            "prompt_version":
                NOTE_RENDERING_PROMPT_VERSION,
        }))
        return {"draft_available": False,
                "reason":          "faithfulness_block",
                "fallback":        "manual_documentation"}

    # Step 4F: persist the rendered draft with citations and
    # faithfulness annotations.
    rendered_object = s3_store.put_object(
        bucket=TRANSCRIPT_BUCKET,
        key=f"{session_id}/rendered_note.json",
        body=json.dumps({
            "rendered_content": rendered_content,
            "citations":        citations,
            "faithfulness_annotations":
                faithfulness_result["annotations"],
        }, default=str).encode("utf-8"),
        metadata={"session_id": session_id})

    note_state.put(session_id, _to_decimal({
        "session_id":              session_id,
        "draft_available":         True,
        "draft_note":              rendered_content,
        "rendered_note_archive_ref":
            rendered_object["uri"],
        "citations":               citations,
        "template_id":             template["id"],
        "specialty":
            session_context["clinician_specialty"],
        "faithfulness_score":
            faithfulness_result["score"],
        "faithfulness_severity":
            faithfulness_result["severity"],
        "faithfulness_failed_checks":
            faithfulness_result["failed_checks"],
        "faithfulness_annotations":
            faithfulness_result["annotations"],
        "generated_at":            _now_iso(),
        "model_version":
            BEDROCK_NOTE_RENDERING_MODEL_ID,
        "prompt_version":
            NOTE_RENDERING_PROMPT_VERSION,
    }))

    event_bus.put_events([{
        "Source":       "ambient_documentation",
        "DetailType":   "note_generated",
        "EventBusName": ENCOUNTER_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":   session_id,
            "encounter_id": encounter_id,
            "specialty":
                session_context["clinician_specialty"],
            "faithfulness_score":
                float(faithfulness_result["score"]),
            "faithfulness_severity":
                faithfulness_result["severity"],
        }),
    }])

    audit_log({
        "event_type":          "NOTE_RENDERED",
        "session_id":          session_id,
        "specialty":
            session_context["clinician_specialty"],
        "template_id":         template["id"],
        "faithfulness_score":
            float(faithfulness_result["score"]),
        "faithfulness_severity":
            faithfulness_result["severity"],
        "timestamp":           _now_iso(),
    })

    return {"draft_available":     True,
            "draft_id":            session_id,
            "faithfulness_score":
                faithfulness_result["score"],
            "faithfulness_severity":
                faithfulness_result["severity"]}
```

---

## Step 5: Extract Structured Clinical Entities and Present Them for Explicit Clinician Confirmation

*The pseudocode calls this `extract_structured_fields(...)`. Beyond the narrative note, the system extracts structured clinical entities (medications, problems, allergies, vitals, orders, follow-up actions) using Comprehend Medical for the canonical coding (RxNorm, ICD-10) and a Bedrock LLM for the higher-level structuring. Each extracted field is presented to the clinician for explicit confirmation before being applied to the structured chart. Skip the explicit confirmation and the structured chart can be silently modified with content the clinician would not have endorsed.*

```python
def lookup_speaker_role_for_offset(transcript, offset_seconds):
    """
    Find which speaker said the words at a given offset. Used
    for context-aware structured-field extraction (a medication
    mentioned by the patient describing their history is
    processed differently from one the clinician verbalizes
    as part of the plan).
    """
    for segment in transcript.get("segments", []):
        # The fixture timestamps are HH:MM:SS strings;
        # normalize to seconds for the comparison.
        ts = segment.get("timestamp", "00:00:00")
        try:
            parts = [int(p) for p in ts.split(":")]
            seg_seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
        except (ValueError, IndexError):
            seg_seconds = 0
        if abs(seg_seconds - offset_seconds) < 30:
            return segment.get("speaker_role")
    return "unknown"

def extract_context_snippet(transcript, offset_seconds,
                              window_seconds=10):
    """
    Pull a small window of transcript text around an offset
    to show alongside the structured-field suggestion in the
    review UI. Lets the clinician see the conversational
    context that produced the extraction.
    """
    for segment in transcript.get("segments", []):
        ts = segment.get("timestamp", "00:00:00")
        try:
            parts = [int(p) for p in ts.split(":")]
            seg_seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
        except (ValueError, IndexError):
            seg_seconds = 0
        if abs(seg_seconds - offset_seconds) < window_seconds:
            return segment.get("text", "")
    return ""

def infer_clinician_action(entity, transcript):
    """
    Heuristic: was the medication mentioned in a context that
    suggests a clinician action (a new prescription, a dose
    adjustment, an order) versus a passing patient mention
    ("I used to take that years ago")? Production uses a
    fine-tuned classifier or an LLM-judge pass; the demo uses
    a simple speaker-role check.
    """
    offset = entity.get("OffsetSeconds", 0)
    speaker_role = lookup_speaker_role_for_offset(
        transcript, offset)
    return speaker_role == "clinician"

def extract_structured_fields(session_context,
                                canonical_transcript):
    """
    Extract clinical entities (medications, conditions) using
    Comprehend Medical with RxNorm and ICD-10 coding, plus
    higher-level fields (orders, follow-up, allergies, vitals,
    referrals) using a Bedrock LLM. Persist all extractions
    for clinician confirmation; never apply them silently to
    the chart.
    """
    session_id = session_context["session_id"]
    encounter_id = session_context["encounter_id"]

    full_text = " ".join(
        seg.get("text", "")
        for seg in canonical_transcript.get("segments", []))

    # Step 5A: extract medications and link to RxNorm.
    rx_response = comprehend_mock.infer_rx_norm(text=full_text)
    coded_medications = []
    for entity in rx_response.get("Entities", []):
        rx_concepts = entity.get("RxNormConcepts", [])
        first_code = (rx_concepts[0]["Code"]
                       if rx_concepts else None)
        offset_seconds = entity.get("OffsetSeconds", 0)
        coded_medications.append({
            "text":           entity.get("Text"),
            "rx_norm_code":   first_code,
            "speaker_role":
                lookup_speaker_role_for_offset(
                    canonical_transcript, offset_seconds),
            "context_snippet":
                extract_context_snippet(
                    canonical_transcript, offset_seconds),
            "clinician_action_likely":
                infer_clinician_action(entity,
                                         canonical_transcript),
            "score":
                Decimal(str(entity.get("Score", 0.85))),
            "clinician_confirmed": False,
        })

    # Step 5A: extract conditions and link to ICD-10.
    icd_response = comprehend_mock.infer_icd10cm(text=full_text)
    coded_conditions = []
    for entity in icd_response.get("Entities", []):
        icd_concepts = entity.get("ICD10CMConcepts", [])
        first_code = (icd_concepts[0]["Code"]
                       if icd_concepts else None)
        offset_seconds = entity.get("OffsetSeconds", 0)
        coded_conditions.append({
            "text":           entity.get("Text"),
            "icd_10_code":    first_code,
            "speaker_role":
                lookup_speaker_role_for_offset(
                    canonical_transcript, offset_seconds),
            "context_snippet":
                extract_context_snippet(
                    canonical_transcript, offset_seconds),
            "score":
                Decimal(str(entity.get("Score", 0.85))),
            "clinician_confirmed": False,
        })

    # Step 5B: use the LLM to identify higher-level structured
    # fields that Comprehend Medical does not directly extract.
    higher_level_response = (
        bedrock_mock.extract_higher_level_fields(
            encounter_id=encounter_id,
            transcript=canonical_transcript))
    higher_level = json.loads(higher_level_response["body"])

    # Mark each higher-level extraction as pending
    # confirmation.
    for category in ("orders_placed", "labs_requested",
                     "imaging_requested",
                     "follow_up_appointments",
                     "patient_reported_vitals",
                     "patient_reported_allergies",
                     "referrals_placed"):
        for item in higher_level.get(category, []):
            item["clinician_confirmed"] = False

    # Step 5C: persist all extractions for clinician
    # confirmation.
    structured_extractions = {
        "medications":              coded_medications,
        "conditions":               coded_conditions,
        "orders_placed":
            higher_level.get("orders_placed", []),
        "labs_requested":
            higher_level.get("labs_requested", []),
        "imaging_requested":
            higher_level.get("imaging_requested", []),
        "follow_up_appointments":
            higher_level.get("follow_up_appointments", []),
        "patient_reported_vitals":
            higher_level.get("patient_reported_vitals", []),
        "patient_reported_allergies":
            higher_level.get("patient_reported_allergies", []),
        "referrals_placed":
            higher_level.get("referrals_placed", []),
        "confirmation_status":      "pending_clinician_review",
    }

    note_state.update(session_id, _to_decimal({
        "structured_extractions": structured_extractions,
    }))

    extraction_count = (
        len(coded_medications)
        + len(coded_conditions)
        + len(higher_level.get("orders_placed", []))
        + len(higher_level.get("labs_requested", []))
        + len(higher_level.get("imaging_requested", []))
        + len(higher_level.get("follow_up_appointments", []))
        + len(higher_level.get("patient_reported_vitals", []))
        + len(higher_level.get(
            "patient_reported_allergies", []))
        + len(higher_level.get("referrals_placed", [])))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "StructuredExtractionsGenerated",
        extraction_count, "Count",
        dimensions={
            "specialty":
                session_context["clinician_specialty"],
            "language":  session_context["language"],
        })

    audit_log({
        "event_type":         "STRUCTURED_FIELDS_EXTRACTED",
        "session_id":         session_id,
        "medication_count":   len(coded_medications),
        "condition_count":    len(coded_conditions),
        "higher_level_count":
            (extraction_count
             - len(coded_medications)
             - len(coded_conditions)),
        "total_extractions":  extraction_count,
        "timestamp":          _now_iso(),
    })

    return {"extraction_count":       extraction_count,
            "structured_extractions": structured_extractions}
```

---

## Step 6: Present the Draft to the Clinician for Review-and-Sign

*The pseudocode calls this `clinician_review_request(...)`, `clinician_save_review(...)`, and `clinician_sign(...)`. The clinician opens the review interface, sees the draft note alongside the transcript with click-through citations, reviews flagged uncertain segments, confirms each structured-field extraction explicitly, edits the narrative as needed, and signs. The signed note is the legal record; the audio is at most ephemeral. Skip the side-by-side display and the clinician cannot easily verify what was actually said versus what the LLM produced.*

```python
def extract_low_confidence_segments(canonical_transcript,
                                       threshold=ASR_LOW_CONFIDENCE_WORD_THRESHOLD):
    """
    Identify segments with low average word confidence so the
    review UI can highlight them. The clinician's eye is drawn
    to uncertain segments, where ASR errors are most likely.
    """
    flagged = []
    for segment in canonical_transcript.get("segments", []):
        confidence = Decimal(str(
            segment.get("confidence", 1.0)))
        if confidence < threshold:
            flagged.append({
                "timestamp":  segment.get("timestamp"),
                "speaker":    segment.get("speaker_role"),
                "confidence": confidence,
            })
    return flagged

def extract_uncertain_speaker_segments(canonical_transcript):
    """
    Identify segments where speaker attribution is uncertain.
    Production diarization emits per-segment speaker
    confidence; the demo uses a fixture flag.
    """
    uncertain = []
    for segment in canonical_transcript.get("segments", []):
        if segment.get("speaker_uncertain", False):
            uncertain.append({
                "timestamp":     segment.get("timestamp"),
                "current_label": segment.get("speaker_role"),
                "alternatives":
                    segment.get("speaker_alternatives", []),
            })
    return uncertain

def extract_bystander_segments(canonical_transcript,
                                  bystanders):
    """
    Identify segments attributed to a bystander role
    (family_member, caregiver, student, other). The review UI
    surfaces these so the clinician can confirm which
    bystander content belongs in the note.
    """
    if not bystanders:
        return []
    bystander_roles = {"family_member", "caregiver",
                        "student", "other"}
    return [{"timestamp":    seg.get("timestamp"),
             "speaker_role": seg.get("speaker_role"),
             "text_excerpt": (seg.get("text", "") or "")[:80]}
            for seg in canonical_transcript.get("segments", [])
            if seg.get("speaker_role") in bystander_roles]

def clinician_review_request(session_context):
    """
    Assemble the side-by-side review payload for the
    clinician. The web UI uses this to render the draft note
    next to the transcript with click-through citations,
    confidence highlights, and structured-field confirmation
    gates.
    """
    session_id = session_context["session_id"]

    note_record = note_state.get(session_id)
    transcript_object = s3_store.get_object(
        bucket=TRANSCRIPT_BUCKET,
        key=f"{session_id}/canonical_transcript.json")

    if not transcript_object:
        return {"available": False,
                "reason":    "transcript_not_found"}

    canonical_transcript = json.loads(
        transcript_object["body"].decode("utf-8"))

    # If the draft was blocked by faithfulness or guardrails,
    # route the clinician to manual documentation rather than
    # showing the unreliable draft.
    if not note_record.get("draft_available"):
        return {"available":           False,
                "reason":
                    note_record.get("block_reason",
                                     "draft_unavailable"),
                "fallback":             "manual_documentation",
                "canonical_transcript": canonical_transcript}

    review_payload = {
        "available":               True,
        "draft_note":              note_record.get("draft_note"),
        "citations":               note_record.get("citations"),
        "canonical_transcript":    canonical_transcript,
        "structured_extractions":
            note_record.get("structured_extractions"),
        "faithfulness_score":
            note_record.get("faithfulness_score"),
        "faithfulness_severity":
            note_record.get("faithfulness_severity"),
        "faithfulness_annotations":
            note_record.get("faithfulness_annotations"),
        "confidence_highlights":
            extract_low_confidence_segments(
                canonical_transcript),
        "speaker_label_uncertainty":
            extract_uncertain_speaker_segments(
                canonical_transcript),
        "bystander_segments":
            extract_bystander_segments(
                canonical_transcript,
                session_context.get("bystanders", [])),
    }

    audit_log({
        "event_type":      "CLINICIAN_REVIEW_OPENED",
        "session_id":      session_id,
        "faithfulness_severity":
            note_record.get("faithfulness_severity"),
        "extraction_count": (
            len(note_record.get(
                "structured_extractions", {})
                .get("medications", []))
            + len(note_record.get(
                "structured_extractions", {})
                .get("conditions", []))),
        "timestamp":       _now_iso(),
    })

    return review_payload

def clinician_save_review(session_context, review_actions):
    """
    Apply the clinician's edits and confirmation decisions to
    the draft. Each structured-field confirmation is recorded
    with the supporting transcript context. Rejections are
    also recorded to feed the extraction-quality metrics.
    """
    session_id = session_context["session_id"]
    note_record = note_state.get(session_id)

    structured_extractions = note_record.get(
        "structured_extractions", {})

    confirmed_extractions = []
    rejected_extractions = []

    decisions_by_key = {
        (d["category"], d["text"]): d
        for d in review_actions.get("structured_decisions", [])
    }

    for category in ("medications", "conditions",
                     "orders_placed", "labs_requested",
                     "imaging_requested",
                     "follow_up_appointments",
                     "patient_reported_vitals",
                     "patient_reported_allergies",
                     "referrals_placed"):
        for item in structured_extractions.get(category, []):
            key = (category, item.get("text")
                              or item.get("name", ""))
            decision = decisions_by_key.get(key)
            if decision and decision.get("confirmed"):
                item_with_decision = dict(item)
                item_with_decision["clinician_confirmed"] = True
                item_with_decision["category"] = category
                confirmed_extractions.append(item_with_decision)
            else:
                item_with_decision = dict(item)
                item_with_decision["clinician_confirmed"] = False
                item_with_decision["category"] = category
                if decision:
                    item_with_decision["rejection_reason"] = (
                        decision.get("rejection_reason"))
                rejected_extractions.append(item_with_decision)

    edited_note = (review_actions.get("note_edits")
                   or note_record.get("draft_note"))

    note_state.update(session_id, _to_decimal({
        "edited_note":            edited_note,
        "confirmed_extractions":  confirmed_extractions,
        "rejected_extractions":   rejected_extractions,
        "review_completed_at":    _now_iso(),
    }))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ExtractionsConfirmed",
        len(confirmed_extractions), "Count",
        dimensions={
            "specialty":
                session_context["clinician_specialty"],
            "language":  session_context["language"],
        })
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ExtractionsRejected",
        len(rejected_extractions), "Count",
        dimensions={
            "specialty":
                session_context["clinician_specialty"],
            "language":  session_context["language"],
        })

    audit_log({
        "event_type":               "CLINICIAN_REVIEW_SAVED",
        "session_id":               session_id,
        "confirmed_extraction_count":
            len(confirmed_extractions),
        "rejected_extraction_count":
            len(rejected_extractions),
        "timestamp":                _now_iso(),
    })

    return {"confirmed": confirmed_extractions,
            "rejected":  rejected_extractions}

def build_idempotency_key(encounter_id, clinician_id,
                            document_type, signed_at):
    """
    Idempotency key for EHR write-back. Truncate signed_at to
    the minute so a within-the-minute retry is treated as the
    same write.
    """
    minute = signed_at.split(":")[0] + ":" + signed_at.split(":")[1]
    raw = f"{encounter_id}|{clinician_id}|{document_type}|{minute}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def clinician_sign(session_context, patient_id):
    """
    Sign the final note, write it to the EHR via FHIR, apply
    the confirmed structured updates to the chart, and
    optionally release the patient-facing summary to the
    portal. Signature is the legal-medical-record boundary;
    after this point any changes are addenda.
    """
    session_id = session_context["session_id"]
    note_record = note_state.get(session_id)

    final_note = (note_record.get("edited_note")
                   or note_record.get("draft_note"))
    confirmed = note_record.get("confirmed_extractions", [])

    signature = clinician_client.get_signature()
    signed_at = signature.get("timestamp", _now_iso())

    idempotency_key = build_idempotency_key(
        encounter_id=session_context["encounter_id"],
        clinician_id=session_context["clinician_id"],
        document_type="clinical_note",
        signed_at=signed_at)

    # Step 6C: write the signed note to the EHR's FHIR
    # DocumentReference resource. Production uses the EHR's
    # FHIR endpoint with SMART on FHIR authentication; the
    # mock just records the write.
    ehr_response = ehr.write_document_reference(
        patient_id=patient_id,
        encounter_id=session_context["encounter_id"],
        document_content=final_note,
        author=session_context["clinician_id"],
        signed_at=signed_at,
        idempotency_key=idempotency_key)

    # Apply confirmed structured-field updates to the chart.
    # Each update is a FHIR resource write (MedicationRequest,
    # Condition, ServiceRequest, etc.).
    for confirmed_item in confirmed:
        category = confirmed_item.get("category")
        if category == "medications":
            ehr.apply_structured_update(
                patient_id=patient_id,
                update_kind="medication",
                payload={
                    "text":         confirmed_item.get("text"),
                    "rx_norm_code":
                        confirmed_item.get("rx_norm_code"),
                    "encounter_id":
                        session_context["encounter_id"],
                })
        elif category == "conditions":
            ehr.apply_structured_update(
                patient_id=patient_id,
                update_kind="problem",
                payload={
                    "text":         confirmed_item.get("text"),
                    "icd_10_code":
                        confirmed_item.get("icd_10_code"),
                    "encounter_id":
                        session_context["encounter_id"],
                })
        elif category in ("labs_requested",
                           "imaging_requested",
                           "orders_placed"):
            ehr.apply_structured_update(
                patient_id=patient_id,
                update_kind="order",
                payload=confirmed_item)
        elif category == "follow_up_appointments":
            ehr.apply_structured_update(
                patient_id=patient_id,
                update_kind="follow_up",
                payload=confirmed_item)
        elif category == "referrals_placed":
            ehr.apply_structured_update(
                patient_id=patient_id,
                update_kind="referral",
                payload=confirmed_item)

    note_state.update(session_id, _to_decimal({
        "signed_note":          final_note,
        "signed_at":            signed_at,
        "signed_by":            session_context["clinician_id"],
        "ehr_document_id":
            ehr_response.get("document_id"),
        "signature":            signature,
        "idempotency_key":      idempotency_key,
        "status":               "signed",
    }))

    started_at_str = session_context["started_at"]
    duration_seconds = (
        datetime.fromisoformat(
            signed_at.replace("Z", "+00:00"))
        - datetime.fromisoformat(
            started_at_str.replace("Z", "+00:00"))
    ).total_seconds()

    event_bus.put_events([{
        "Source":       "ambient_documentation",
        "DetailType":   "note_signed",
        "EventBusName": ENCOUNTER_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":          session_id,
            "encounter_id":
                session_context["encounter_id"],
            "specialty":
                session_context["clinician_specialty"],
            "ehr_document_id":
                ehr_response.get("document_id"),
            "duration_encounter_to_sign_seconds":
                duration_seconds,
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "NotesSigned", 1, "Count",
        dimensions={
            "specialty":
                session_context["clinician_specialty"],
            "language":  session_context["language"],
            "visit_type":
                session_context["visit_type"],
        })

    audit_log({
        "event_type":      "NOTE_SIGNED",
        "session_id":      session_id,
        "ehr_document_id":
            ehr_response.get("document_id"),
        "confirmed_extraction_count": len(confirmed),
        "duration_encounter_to_sign_seconds":
            duration_seconds,
        "timestamp":       signed_at,
    })

    return {"signed":          True,
            "ehr_document_id":
                ehr_response.get("document_id"),
            "signed_at":       signed_at,
            "confirmed_extraction_count": len(confirmed)}
```

---

## Step 7: Audit, Archive, Retain Audio per Policy, and Feed Cohort-Stratified Accuracy Monitoring

*The pseudocode calls this `audit_archive_and_telemetry(...)`. Every encounter produces a durable audit record: the transcript, the rendered draft, the clinician edits, the structured-field decisions, the signed final note, the consent and bystander events. Audio is retained briefly per institutional policy and then deleted. Cohort-stratified metrics (per-language, per-specialty, per-clinician, per-patient-cohort, per-audio-quality-band, per-room) feed the equity-monitoring dashboard. Skip the audio retention enforcement and the institution silently accumulates biometric data beyond its policy commitment, which is a compliance exposure. Skip the cohort segmentation and the system's per-cohort failure modes are invisible until a complaint or a regulator surfaces them.*

```python
def compute_edit_distance(draft_text, final_text):
    """
    Compute a simple character-level edit distance between
    the LLM draft and the clinician's signed note. Production
    uses a tokenized word-level distance; the demo uses
    Levenshtein on the JSON-serialized strings as a proxy.
    """
    if not draft_text or not final_text:
        return 0
    a = json.dumps(draft_text, default=str, sort_keys=True)
    b = json.dumps(final_text, default=str, sort_keys=True)
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    distances = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        new_row = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            new_row.append(min(distances[j] + 1,
                                new_row[-1] + 1,
                                distances[j - 1] + cost))
        distances = new_row
    return distances[-1]

def compute_audio_retention(visit_type):
    """
    Per-visit-type audio retention. Behavioral-health visits
    have stricter retention windows; general ambulatory visits
    use the institutional default.
    """
    if visit_type in SENSITIVE_VISIT_TYPES:
        return {"hours": 24}
    return {"hours": 168}  # 7 days default

def schedule_audio_deletion(audio_ref, delete_after):
    """
    Schedule audio deletion per institutional retention
    policy. Production uses an S3 lifecycle policy to
    automatically delete after a fixed window; this helper
    records the intended deletion in the audit log so the
    privacy officer can confirm the deletion happened.
    """
    audit_log({
        "event_type":            "AUDIO_DELETION_SCHEDULED",
        "audio_ref":             audio_ref,
        "delete_after_hours":
            delete_after.get("hours"),
        "timestamp":             _now_iso(),
    })

def audit_archive_and_telemetry(session_context,
                                  patient_age_band="not_disclosed"):
    """
    Write the durable audit record, schedule audio deletion
    per the institutional retention policy, emit the
    encounter-audited lifecycle event, and emit per-cohort
    operational metrics.
    """
    session_id = session_context["session_id"]
    state = encounter_state.get(session_id)
    note_record = note_state.get(session_id)
    transcript_record = transcript_state.get(session_id)

    # Audio quality band for cohort stratification (high,
    # medium, low, unknown). Production also emits this as a
    # CloudWatch metric dimension.
    quality_band = _bucket_audio_quality({
        "avg_snr_db":
            float(state.get("avg_audio_quality_snr",
                              Decimal("0.0"))),
    })

    edit_distance = compute_edit_distance(
        draft_text=note_record.get("draft_note"),
        final_text=note_record.get("signed_note")
                    or note_record.get("edited_note"))

    confirmed_count = len(
        note_record.get("confirmed_extractions", []))
    rejected_count = len(
        note_record.get("rejected_extractions", []))
    extraction_acceptance_rate = (
        Decimal(str(confirmed_count
                     / max(confirmed_count + rejected_count,
                            1))))

    audit_record = _to_decimal({
        "session_id":             session_id,
        "encounter_id":           state.get("encounter_id"),
        "clinician_id":           state.get("clinician_id"),
        "clinician_specialty":
            state.get("clinician_specialty"),
        "patient_id_hash":        state.get("patient_id_hash"),
        "room_id":                state.get("room_id"),
        "visit_type":             state.get("visit_type"),
        "language":               state.get("language"),
        "consent_regime":         state.get("consent_regime"),
        "bystander_count":
            len(state.get("bystanders", [])),
        "feature_status":         state.get("feature_status"),
        "device_type":            state.get("device_type"),
        "voiceprint_enrolled":
            state.get("clinician_voiceprint_enrolled"),
        "audio_archive_ref":      state.get("audio_archive_ref"),
        "canonical_transcript_ref":
            state.get("canonical_transcript_ref"),
        "healthscribe_note_draft_ref":
            state.get("healthscribe_note_draft_ref"),
        "rendered_note_archive_ref":
            note_record.get("rendered_note_archive_ref"),
        "draft_available":        note_record.get("draft_available"),
        "block_reason":           note_record.get("block_reason"),
        "ehr_document_id":        note_record.get("ehr_document_id"),
        "signed_at":              note_record.get("signed_at"),
        "edit_distance_draft_to_final":  edit_distance,
        "faithfulness_score":
            note_record.get("faithfulness_score"),
        "faithfulness_severity":
            note_record.get("faithfulness_severity"),
        "faithfulness_failed_checks":
            note_record.get("faithfulness_failed_checks", []),
        "confirmed_extraction_count":  confirmed_count,
        "rejected_extraction_count":   rejected_count,
        "extraction_acceptance_rate":
            extraction_acceptance_rate,
        "avg_audio_quality_snr":
            state.get("avg_audio_quality_snr"),
        "avg_streaming_asr_confidence":
            state.get("avg_streaming_asr_confidence"),
        "avg_diarization_confidence":
            state.get("avg_diarization_confidence"),
        "avg_batch_asr_confidence":
            state.get("avg_batch_asr_confidence"),
        "diarization_disagreement_count":
            state.get("diarization_disagreement_count"),
        # Versions of every artifact that influenced the
        # encounter.
        "streaming_asr_model_version":
            state.get("streaming_asr_model_version"),
        "batch_asr_model_version":
            state.get("batch_asr_model_version"),
        "note_rendering_prompt_version":
            state.get("note_rendering_prompt_version"),
        "faithfulness_prompt_version":
            state.get("faithfulness_prompt_version"),
        "structured_extraction_version":
            state.get("structured_extraction_version"),
        "template_library_version":
            state.get("template_library_version"),
        # Cohort axes for equity monitoring. The age_band is
        # opt-in self-disclosed; never inferred for protected
        # classes.
        "cohort_axes": {
            "language":           state.get("language"),
            "visit_type":         state.get("visit_type"),
            "specialty":
                state.get("clinician_specialty"),
            "audio_quality_band": quality_band,
            "age_band":           patient_age_band,
            "room_id":            state.get("room_id"),
            "device_type":        state.get("device_type"),
        },
    })

    audit_object = s3_store.put_object(
        bucket=AUDIT_ARCHIVE_BUCKET,
        key=(f"audit/"
             f"{datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
             f"/{session_id}.json"),
        body=json.dumps(audit_record,
                          default=str).encode("utf-8"),
        metadata={
            "session_id":         session_id,
            "encounter_id":       state.get("encounter_id"),
            "audio_quality_band": quality_band,
        })

    # Step 7A: schedule audio deletion per institutional
    # retention policy.
    if state.get("audio_archive_ref"):
        schedule_audio_deletion(
            audio_ref=state.get("audio_archive_ref"),
            delete_after=compute_audio_retention(
                visit_type=state.get("visit_type")))

    event_bus.put_events([{
        "Source":       "ambient_documentation",
        "DetailType":   "encounter_audited",
        "EventBusName": ENCOUNTER_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":          session_id,
            "encounter_id":        state.get("encounter_id"),
            "edit_distance":       edit_distance,
            "faithfulness_score":
                float(note_record.get("faithfulness_score")
                       or 0.0),
            "extraction_acceptance_rate":
                float(extraction_acceptance_rate),
            "audio_quality_band":  quality_band,
        }),
    }])

    # Per-cohort operational metrics. Each metric carries the
    # cohort dimensions so the equity-monitoring dashboard can
    # stratify.
    cohort_dims = {
        "specialty":
            state.get("clinician_specialty", "unknown"),
        "language":           state.get("language", "unknown"),
        "visit_type":
            state.get("visit_type", "unknown"),
        "audio_quality_band": quality_band,
        "device_type":
            state.get("device_type", "unknown"),
    }
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "EditDistanceDraftToFinal",
        edit_distance, "Count",
        dimensions=cohort_dims)
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ExtractionAcceptanceRate",
        float(extraction_acceptance_rate), "None",
        dimensions=cohort_dims)
    if note_record.get("faithfulness_score") is not None:
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "FinalFaithfulnessScore",
            float(note_record.get("faithfulness_score")),
            "None",
            dimensions=cohort_dims)

    audit_log({
        "event_type":              "ENCOUNTER_AUDITED",
        "session_id":              session_id,
        "audit_archive_ref":       audit_object["uri"],
        "edit_distance":           edit_distance,
        "extraction_acceptance_rate":
            float(extraction_acceptance_rate),
        "audio_quality_band":      quality_band,
        "timestamp":               _now_iso(),
    })

    return audit_record
```

---

## Putting It All Together

The pipeline ties together as a top-level handler that simulates a single end-to-end encounter flowing through the seven stages. In a Lambda-and-Step-Functions deployment, the streaming-display stages run on the audio-stream-handler Lambda while the post-encounter stages run as a Step Functions state machine; the demo orchestrates them inline so you can see the full sequence.

```python
def run_encounter_pipeline(encounter_id, patient_id,
                              clinician_id,
                              clinician_specialty,
                              clinic_jurisdiction,
                              visit_type, room_id,
                              bystanders=None,
                              device_type="wall_mounted_array",
                              language="en-US",
                              consent_acknowledged=True,
                              review_decisions=None,
                              note_edits=None,
                              patient_age_band="not_disclosed"):
    """
    Drive a single ambient-documentation encounter end-to-end
    through all seven pipeline stages. Production splits this
    across multiple Lambdas with Step Functions orchestration;
    the demo collapses to a single function for readability.
    """
    # Stage 1: encounter start, consent, bystander capture,
    # session bootstrap.
    session_context = encounter_start(
        encounter_id=encounter_id,
        patient_id=patient_id,
        clinician_id=clinician_id,
        clinician_specialty=clinician_specialty,
        clinic_jurisdiction=clinic_jurisdiction,
        visit_type=visit_type,
        room_id=room_id,
        bystanders=bystanders,
        device_type=device_type,
        language=language,
        consent_acknowledged=consent_acknowledged)

    if not session_context.get("feature_enabled"):
        return {"feature_enabled": False,
                "reason": session_context.get("reason"),
                "consent_regime":
                    session_context.get("consent_regime")}

    # Stage 2: streaming HealthScribe (during the encounter).
    streaming_result = stream_audio_to_healthscribe(
        session_context)

    # Persist the audio archive reference. Production has the
    # in-room device or Chime SDK media-capture pipeline write
    # the audio to S3 with KMS encryption; the demo stamps a
    # reference and proceeds.
    audio_archive_ref = (
        f"s3://{AUDIO_BUCKET}/{session_context['session_id']}/"
        f"audio.pcm")
    encounter_state.update(session_context["session_id"], {
        "audio_archive_ref": audio_archive_ref,
    })

    # Stage 3: batch HealthScribe (post-encounter).
    batch_result = run_batch_healthscribe(
        session_context=session_context,
        audio_archive_ref=audio_archive_ref)
    canonical_transcript = batch_result["canonical_transcript"]
    healthscribe_note_draft = (
        batch_result["healthscribe_note_draft"])

    # Stage 4: institutional-template rendering plus
    # faithfulness check.
    note_result = render_institutional_note(
        session_context=session_context,
        canonical_transcript=canonical_transcript,
        healthscribe_note_draft=healthscribe_note_draft)

    if not note_result["draft_available"]:
        # Faithfulness or guardrails blocked the draft; the
        # clinician falls back to manual documentation. Still
        # write the audit record so the failure is visible to
        # clinical quality.
        audit_archive_and_telemetry(
            session_context=session_context,
            patient_age_band=patient_age_band)
        return {"feature_enabled": True,
                "draft_available": False,
                "reason":          note_result["reason"]}

    # Stage 5: structured-field extraction.
    extraction_result = extract_structured_fields(
        session_context=session_context,
        canonical_transcript=canonical_transcript)

    # Stage 6: clinician review + sign.
    if review_decisions:
        clinician_client.queue_review_decisions(
            review_decisions)
    if note_edits:
        clinician_client.queue_note_edits(note_edits)

    review_payload = clinician_review_request(session_context)
    if not review_payload.get("available"):
        audit_archive_and_telemetry(
            session_context=session_context,
            patient_age_band=patient_age_band)
        return {"feature_enabled": True,
                "draft_available": False,
                "reason":
                    review_payload.get("reason")}

    confirmation_result = clinician_save_review(
        session_context=session_context,
        review_actions={
            "structured_decisions":
                clinician_client.collect_review_decisions(),
            "note_edits":
                clinician_client.collect_note_edits(),
        })

    sign_result = clinician_sign(
        session_context=session_context,
        patient_id=patient_id)

    # Stage 7: audit + cohort metrics.
    audit_record = audit_archive_and_telemetry(
        session_context=session_context,
        patient_age_band=patient_age_band)

    return {
        "feature_enabled":         True,
        "session_id":              session_context["session_id"],
        "draft_available":         True,
        "faithfulness_score":
            note_result["faithfulness_score"],
        "faithfulness_severity":
            note_result["faithfulness_severity"],
        "extraction_count":
            extraction_result["extraction_count"],
        "confirmed_extraction_count":
            len(confirmation_result["confirmed"]),
        "rejected_extraction_count":
            len(confirmation_result["rejected"]),
        "ehr_document_id":         sign_result["ehr_document_id"],
        "audit_archive_ref":
            f"audit/{session_context['session_id']}.json",
    }
```

The demo runner wires up the mocks with fixture data for two end-to-end scenarios.

```python
def run_demo():
    """
    Run two end-to-end scenarios that exercise the main paths
    through the in-room ambient documentation pipeline:
      1. Carl (older primary-care patient with his daughter
         present) has an 18-minute encounter with Dr. Patel
         in a clinic exam room with a wall-mounted microphone
         array. Three speakers (clinician + patient + family
         member). The note draft passes faithfulness checks;
         the clinician confirms the gabapentin and lab-order
         extractions and signs.
      2. Marcus (Spanish-speaking primary-care patient) has
         a follow-up visit with Dr. Vega in an older exam
         room with a clinician-tablet capture device. Lower
         audio quality due to room acoustics and HVAC noise;
         the faithfulness check passes but flags one segment
         for review.
    """
    # pylint: disable=global-statement
    global healthscribe_streaming, healthscribe_batch_mock
    global bedrock_mock, comprehend_mock

    # Scenario 1 fixtures: Carl's visit with Dr. Patel.
    encounter_id_1 = "encounter-2026-05-23-0411"
    streaming_segments_1 = [
        {"speaker_role": "clinician",
         "timestamp":    "00:00:08",
         "text":
             "Hi Carl, good to see you. And Sarah, thanks "
             "for coming with your dad today. You both know "
             "our visit is being captured for documentation; "
             "let me know if you'd like me to pause that.",
         "segment_class": "social_workflow",
         "confidence":    Decimal("0.96"),
         "diarization_confidence": Decimal("0.95")},
        {"speaker_role": "patient",
         "timestamp":    "00:00:24",
         "text":         "That's fine, doctor.",
         "segment_class": "social_workflow",
         "confidence":    Decimal("0.92"),
         "diarization_confidence": Decimal("0.93")},
        {"speaker_role": "patient",
         "timestamp":    "00:01:42",
         "text":
             "I've been having this tingling in my feet, "
             "mostly at night. It started maybe a couple "
             "months ago, I think.",
         "segment_class": "hpi",
         "confidence":    Decimal("0.91"),
         "diarization_confidence": Decimal("0.90")},
        {"speaker_role": "family_member",
         "timestamp":    "00:01:58",
         "text":
             "Dad, you said it started right after Christmas. "
             "And he's been kind of unsteady too. Last week "
             "he caught his foot on the rug.",
         "segment_class": "hpi",
         "confidence":    Decimal("0.88"),
         "diarization_confidence": Decimal("0.84")},
        {"speaker_role": "clinician",
         "timestamp":    "00:08:33",
         "text":
             "Lungs are clear. Heart is regular. I don't "
             "appreciate any focal weakness in the lower "
             "extremities. Reflexes are diminished at the "
             "ankles bilaterally.",
         "segment_class": "exam_narrated",
         "confidence":    Decimal("0.94"),
         "diarization_confidence": Decimal("0.95")},
        {"speaker_role": "clinician",
         "timestamp":    "00:11:02",
         "text":
             "I'm going to start you on gabapentin three "
             "hundred milligrams at bedtime, and we'll order "
             "an A1C and a B12.",
         "segment_class": "plan",
         "confidence":    Decimal("0.95"),
         "diarization_confidence": Decimal("0.96")},
    ]
    batch_transcript_1 = {
        "session_id":    None,
        "encounter_id":  encounter_id_1,
        "duration_seconds": 1086,
        "diarization_quality": "high",
        "segments":      [
            {**seg, "speaker_uncertain": False}
            for seg in streaming_segments_1
        ],
    }
    healthscribe_note_draft_1 = {
        "subjective": "Patient reports new-onset bilateral "
                       "foot tingling.",
        "objective":  "Lungs clear; reflexes diminished at "
                       "the ankles.",
        "assessment": "Peripheral neuropathy.",
        "plan":       "Start gabapentin; order A1C and B12.",
    }
    rendered_note_response_1 = {
        "content": {
            "sections": {
                "subjective": {
                    "text":
                        "Carl Johnson is a 67-year-old male "
                        "with type 2 diabetes and "
                        "hypertension presenting for "
                        "follow-up. He reports new bilateral "
                        "foot tingling, predominantly "
                        "nocturnal, with onset approximately "
                        "two months ago (his daughter notes "
                        "the timing was just after "
                        "Christmas). His daughter "
                        "additionally reports episodes of "
                        "unsteadiness, including a recent "
                        "near-fall over a rug.",
                },
                "objective": {
                    "text":
                        "Vital signs reviewed (see "
                        "structured chart). Lungs clear to "
                        "auscultation bilaterally. Heart "
                        "regular rate and rhythm. No focal "
                        "weakness in the lower extremities "
                        "on motor exam. Diminished reflexes "
                        "at the ankles bilaterally.",
                },
                "assessment": {
                    "text":
                        "1. Bilateral peripheral neuropathy, "
                        "new onset, possible diabetic "
                        "etiology. 2. Type 2 diabetes "
                        "mellitus. 3. Hypertension, "
                        "controlled. 4. Reported gait "
                        "instability; falls risk noted.",
                },
                "plan": {
                    "text":
                        "1. Add gabapentin 300 mg PO at "
                        "bedtime. 2. Order HbA1c and "
                        "vitamin B12. 3. Discussed home "
                        "safety; recommended removing loose "
                        "rugs. 4. Follow-up in 6 weeks.",
                },
            },
        },
        "citations": [
            {"section": "subjective",
             "transcript_segment_timestamp": "00:01:42"},
            {"section": "subjective",
             "transcript_segment_timestamp": "00:01:58"},
            {"section": "objective",
             "transcript_segment_timestamp": "00:08:33"},
            {"section": "plan",
             "transcript_segment_timestamp": "00:11:02"},
        ],
        "guardrail_action": "NONE",
    }
    faithfulness_response_1 = {
        "score":         0.94,
        "failed_checks": [],
        "annotations":   [],
    }
    extraction_response_1 = {
        "orders_placed": [],
        "labs_requested": [
            {"name": "HbA1c",       "loinc_code": "4548-4"},
            {"name": "Vitamin B12", "loinc_code": "2132-9"},
        ],
        "imaging_requested":          [],
        "follow_up_appointments": [
            {"interval_weeks": 6,
             "modality_options": ["in_person", "telehealth"]},
        ],
        "patient_reported_vitals":    [],
        "patient_reported_allergies": [],
        "referrals_placed":           [],
    }
    rx_norm_fixture_1 = {
        "Entities": [
            {"Text": "gabapentin",
             "Score": 0.97,
             "OffsetSeconds": 662,
             "RxNormConcepts": [
                 {"Code": "25480",
                  "Description": "gabapentin"}]},
        ]
    }
    icd10_fixture_1 = {
        "Entities": [
            {"Text": "peripheral neuropathy",
             "Score": 0.92,
             "OffsetSeconds": 102,
             "ICD10CMConcepts": [
                 {"Code": "G62.9",
                  "Description":
                      "Polyneuropathy, unspecified"}]},
            {"Text": "type 2 diabetes",
             "Score": 0.96,
             "OffsetSeconds": 102,
             "ICD10CMConcepts": [
                 {"Code": "E11.9",
                  "Description":
                      "Type 2 diabetes mellitus without "
                      "complications"}]},
        ]
    }

    # Scenario 2 fixtures: Marcus's encounter with Dr. Vega
    # (Spanish, clinician-tablet device, lower-quality audio).
    encounter_id_2 = "encounter-2026-05-23-0412"
    streaming_segments_2 = [
        {"speaker_role": "clinician",
         "timestamp":    "00:00:05",
         "text":
             "Hola senor Hernandez, gracias por venir hoy.",
         "segment_class": "social_workflow",
         "confidence":    Decimal("0.91"),
         "diarization_confidence": Decimal("0.90")},
        {"speaker_role": "patient",
         "timestamp":    "00:00:14",
         "text":
             "Hola doctor, me he sentido bastante bien.",
         "segment_class": "social_workflow",
         "confidence":    Decimal("0.82"),
         "diarization_confidence": Decimal("0.78")},
        {"speaker_role": "patient",
         "timestamp":    "00:02:30",
         "text":
             "Pero la presion ha estado un poco alta esta "
             "semana.",
         "segment_class": "hpi",
         "confidence":    Decimal("0.76"),
         "diarization_confidence": Decimal("0.71")},
    ]
    batch_transcript_2 = {
        "session_id":    None,
        "encounter_id":  encounter_id_2,
        "duration_seconds": 612,
        "diarization_quality": "medium",
        "segments":      [
            {**seg,
             "speaker_uncertain":
                 seg["timestamp"] == "00:02:30",
             "speaker_alternatives":
                 ["clinician"]
                 if seg["timestamp"] == "00:02:30"
                 else []}
            for seg in streaming_segments_2
        ],
    }
    healthscribe_note_draft_2 = {
        "subjective": "Patient reports feeling well overall; "
                       "elevated blood pressure this week.",
        "objective":  "",
        "assessment": "Hypertension, suboptimally controlled.",
        "plan":       "Reinforce medication adherence; "
                       "follow-up.",
    }
    rendered_note_response_2 = {
        "content": {
            "sections": {
                "subjective": {
                    "text":
                        "Mr. Hernandez reports overall "
                        "well-being but notes elevated "
                        "blood pressure readings at home "
                        "over the past week.",
                },
                "objective": {
                    "text":
                        "Physical exam not narrated; please "
                        "complete as needed.",
                },
                "assessment": {
                    "text":
                        "Essential hypertension, "
                        "suboptimally controlled.",
                },
                "plan": {
                    "text":
                        "Reinforce medication adherence. "
                        "Patient to log home BP readings. "
                        "Follow-up in 4 weeks.",
                },
            },
        },
        "citations": [
            {"section": "subjective",
             "transcript_segment_timestamp": "00:02:30"},
        ],
        "guardrail_action": "NONE",
    }
    faithfulness_response_2 = {
        "score":         0.91,
        "failed_checks": [],
        "annotations":   [
            {"segment":  "00:02:30",
             "note":     "low diarization confidence; speaker "
                          "attribution should be reviewed"}],
    }

    # Wire up the mocks.
    healthscribe_streaming = MockHealthScribeStreaming({
        encounter_id_1: streaming_segments_1,
        encounter_id_2: streaming_segments_2,
    })
    healthscribe_batch_mock = MockHealthScribeBatch(
        fixture_transcripts={
            encounter_id_1: batch_transcript_1,
            encounter_id_2: batch_transcript_2,
        },
        fixture_note_drafts={
            encounter_id_1: healthscribe_note_draft_1,
            encounter_id_2: healthscribe_note_draft_2,
        })
    bedrock_mock = MockBedrock(
        render_responses={
            encounter_id_1: rendered_note_response_1,
            encounter_id_2: rendered_note_response_2,
        },
        faithfulness_responses={
            encounter_id_1: faithfulness_response_1,
            encounter_id_2: faithfulness_response_2,
        },
        extraction_responses={
            encounter_id_1: extraction_response_1,
            encounter_id_2: {
                "orders_placed":              [],
                "labs_requested":             [],
                "imaging_requested":          [],
                "follow_up_appointments": [
                    {"interval_weeks": 4,
                     "modality_options": ["in_person"]}],
                "patient_reported_vitals":    [],
                "patient_reported_allergies": [],
                "referrals_placed":           [],
            },
        })
    comprehend_mock = MockComprehendMedical({
        "infer_rx_norm":   rx_norm_fixture_1,
        "infer_icd10cm":   icd10_fixture_1,
        "detect_entities": {"Entities": []},
    })

    # Scenario 1: Carl with Dr. Patel. Three-speaker encounter
    # with the daughter present. Clinician confirms the
    # gabapentin and labs.
    print("\n=== Scenario 1: Carl with Dr. Patel ===")
    review_decisions_1 = [
        {"category": "medications",
         "text":     "gabapentin",
         "confirmed": True},
        {"category": "conditions",
         "text":     "peripheral neuropathy",
         "confirmed": True},
        {"category": "conditions",
         "text":     "type 2 diabetes",
         "confirmed": True},
        {"category": "labs_requested",
         "text":     "HbA1c",
         "confirmed": True},
        {"category": "labs_requested",
         "text":     "Vitamin B12",
         "confirmed": True},
    ]
    result_1 = run_encounter_pipeline(
        encounter_id=encounter_id_1,
        patient_id="pt-44219",
        clinician_id="clinician-patel",
        clinician_specialty="family_medicine",
        clinic_jurisdiction="VA",
        visit_type="primary_care",
        room_id="clinic-A-room-12",
        bystanders=["family_member"],
        device_type="wall_mounted_array",
        language="en-US",
        consent_acknowledged=True,
        review_decisions=review_decisions_1,
        patient_age_band="65_74")
    print(json.dumps(result_1, default=str, indent=2))

    # Scenario 2: Marcus with Dr. Vega. Lower audio quality
    # and a flagged speaker-uncertainty segment for review.
    print("\n=== Scenario 2: Marcus with Dr. Vega ===")
    result_2 = run_encounter_pipeline(
        encounter_id=encounter_id_2,
        patient_id="pt-77310",
        clinician_id="clinician-vega",
        clinician_specialty="family_medicine",
        clinic_jurisdiction="VA",
        visit_type="primary_care",
        room_id="clinic-B-room-04",
        bystanders=[],
        device_type="clinician_tablet",
        language="es-US",
        consent_acknowledged=True,
        review_decisions=[],
        patient_age_band="55_64")
    print(json.dumps(result_2, default=str, indent=2))

if __name__ == "__main__":
    run_demo()
```

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right audit records, but the distance between it and a real in-room ambient documentation pipeline running in clinicians' workflows is significant. Here is where that distance lives.

**Real in-room device integration.** The demo treats the audio capture as a configuration choice between a clinician tablet, a wall-mounted array, a ceiling-mounted array, or a lavalier-with-room-array combination. Production integrates with a specific device or vendor SDK: the Amazon Chime SDK with media-capture pipelines for institution-built capture experiences, a commercial wall-mounted or desk-mounted appliance from a vendor (Shure, Yealink, Logitech, plus several healthcare-specific vendors) with the vendor's own SDK and audio path, or a dedicated mobile-app on a clinician iPad or iPhone. The integration depth varies: some appliances expose per-microphone-capsule streams for institutional beamforming, some do beamforming on-device and stream a single cleaned channel. Plan the device integration as its own multi-week workstream after device selection. Per-room audio survey before installation is a launch gate; some rooms will need acoustic treatment (acoustic ceiling tiles, carpet, drapes, door seals) before they can support good ambient capture.

**Real HealthScribe streaming wiring.** The demo mocks the streaming HealthScribe session. Production uses the standalone amazon-transcribe Python package (not the boto3 transcribe client, which is for batch and vocabulary management only): the streaming session opens an HTTP/2 connection, audio frames push through as they arrive from the in-room device, partial transcripts emit back to the clinician's live display, the final speaker-attributed transcript with clinical-content classifications emits at end-of-utterance. HealthScribe's streaming surface includes role labels (CLINICIAN, PATIENT, FAMILY, OTHER) and segment classes (CHIEF_COMPLAINT, HPI, ROS, EXAM, ASSESSMENT, PLAN) that downstream stages consume directly.

**Real HealthScribe batch wiring.** The demo's `MockHealthScribeBatch.start_medical_scribe_job` returns immediately. Production uses `transcribe_batch.start_medical_scribe_job(...)` which is asynchronous; the orchestrator polls `get_medical_scribe_job` until the status is COMPLETED, then retrieves the transcript and clinical-document outputs from the configured output bucket. The job typically completes within minutes of submission for a typical 15-30 minute encounter. HealthScribe's batch output includes the structured note draft organized by section, plus the per-section transcript citations that the institutional-rendering layer uses for grounding.

**Real custom-vocabulary management.** The demo records the vocabulary name and proceeds. Production maintains custom vocabularies per institution (the formulary, provider list), per language (different vocabulary lists for each supported language), and optionally per specialty (specialty-specific term sets curated by clinical operations). Vocabularies are created via `transcribe_batch.create_vocabulary` and updated as terms are added. Custom language models, when used, are trained on institutional clinical text via `transcribe_batch.create_language_model`; training takes hours and the resulting model is referenced by name in the streaming and batch ASR configurations.

**Real Bedrock invocation, prompt management, and inference profile.** The demo's `MockBedrock` uses fixture lookups. Production calls `bedrock_runtime.invoke_model` with `modelId=BEDROCK_NOTE_RENDERING_PROFILE_ARN` (the inference profile ARN is what you pass for cross-region inference and per-profile rate limits). The `body` parameter is the model-specific JSON request: for Anthropic Claude on Bedrock, that is a `messages` API request with a `system` prompt (versioned, owned by clinical operations), a `tools` field that declares the structured-output schema as a tool definition (this is how you enforce JSON output), and the user message containing the canonical transcript, the HealthScribe SOAP draft, the EHR context, and the institutional template structure. The `guardrailIdentifier` and `guardrailVersion` parameters apply the runtime Guardrails policy. The faithfulness checker uses a smaller, cheaper model (Claude 3 Haiku is appropriate); the note generator uses the larger, more capable model. Both prompts are versioned and deployed alongside the rest of the pipeline; prompt changes go through clinical-operations review (the prompts are load-bearing safety artifacts, not config strings).

**Real Bedrock Guardrails configuration.** The demo references a guardrail ID but does not invoke it. Production configures a Guardrails policy that filters clinical-advice and harmful-content categories, applies the guardrail at runtime via the `guardrailIdentifier` parameter on `invoke_model`, and surfaces guardrail-trigger events to the audit pipeline. For ambient documentation, the contextual-grounding check is particularly useful: configure the canonical transcript and the EHR context as the grounding sources and any rendered claim that does not have grounding triggers a guardrail intervention. Guardrails is a defense-in-depth layer; the system-prompt constraints in the note-rendering prompt, the runtime faithfulness check, and the Guardrails filter all operate together.

**Real Comprehend Medical wiring.** The demo's `MockComprehendMedical` uses fixture lookups. Production calls `comprehend_medical.detect_entities_v2(Text=transcript)` for entity extraction, `comprehend_medical.infer_rx_norm(Text=transcript)` for medication coding, and `comprehend_medical.infer_icd10cm(Text=transcript)` for condition coding. The responses are merged on entity offsets to produce the suggestion list. Comprehend Medical occasionally misidentifies entities, misses negation ("denies chest pain" must not produce a chest-pain problem-list entry), or extracts dosages incorrectly; the suggestion-with-explicit-confirmation flow is what makes this safe to deploy.

**Per-Lambda IAM roles.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda (encounter-start handler, audio-stream-handler, batch-trigger, institutional-rendering invoker, faithfulness-check runner, structured-field extractor, EHR write-back, audit writer, adaptation-feedback emitter), each scoped to the specific resource ARNs the Lambda touches. The institutional-rendering role has scoped Bedrock invocation rights pinned to one model and one inference profile. The structured-field-extractor role has scoped Comprehend Medical inference rights only. The EHR-handoff role has scoped Secrets Manager read for the EHR credentials and write access only to the in-flight encounter's note-state record. Wildcard actions and resources will fail any serious IAM review.

**Real DynamoDB wiring with KMS and PITR.** The mocks in the demo are dictionaries; production is DynamoDB tables (encounter-state with TTL on idle sessions, transcript-state partitioned by session_id with global secondary indexes for encounter-level queries, note-state partitioned by clinician_id with session_id sort key) with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery enabled, and DynamoDB Streams emitting change events to the audit and analytics consumers. The audit table has Streams feeding a Kinesis Firehose delivery stream that writes to S3 with Object Lock in compliance mode for HIPAA-grade durability.

**Customer-managed KMS keys, per data class.** Every PHI-bearing resource (audio bucket, transcript bucket, audit-archive bucket, HealthScribe output bucket, encounter-state table, transcript-state table, note-state table, Lambda environment variables, CloudWatch Logs, Secrets Manager) uses customer-managed KMS keys with rotation enabled. Different keys per data class for blast-radius containment: a compromised audio-bucket key does not compromise the audit archive. Different keys per visit type when the institution wants behavioral-health audio segregated from general ambulatory audio at the cryptographic level. CloudTrail logs every key-usage event. The institutional KMS-key-management runbook specifies rotation cadence, access review cadence, and the cross-account key-grant pattern.

**S3 lifecycle and Object Lock.** The audio bucket has a brief-retention lifecycle (delete after a few hours to a few days post-signing, per the privacy-officer-reviewed retention policy, with shorter retention for behavioral-health visits). The transcript and note buckets retain for the medical-record retention. The audit archive uses Object Lock in compliance mode for HIPAA-grade durability with retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, and the institution's policy. Lifecycle transitions move older audit-archive objects to Glacier Deep Archive for cost optimization.

**VPC and VPC endpoints.** Lambdas that call the EHR API run in a VPC with private subnets that route traffic through a controlled egress path (PrivateLink to a cloud-hosted EHR, or a VPN/Direct Connect to an on-premises EHR system). VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, EventBridge, CloudWatch Logs, Bedrock, Comprehend Medical, and Transcribe (HealthScribe) keep AWS-internal traffic on the AWS backbone rather than traversing NAT and the public internet. Endpoint policies pin access to the specific resources the pipeline uses.

**Step Functions orchestration of the post-encounter pipeline.** The demo orchestrates the post-encounter stages inline. Production runs them as an AWS Step Functions state machine triggered by the `encounter_end` event: batch HealthScribe submission and polling, institutional-rendering with faithfulness check, structured-field extraction, presentation to the clinician for review. Step Functions provides the durable retry semantics: if Bedrock throttles, retry with exponential backoff; if Comprehend Medical fails, route to a DLQ; if the EHR handoff fails, hold the signed note in a queue with manual replay capability. Each Lambda has its own IAM role, error handling, retries, and DLQs.

**Per-specialty template library with named clinical-informatics owners.** The demo's `DEFAULT_TEMPLATES` is a small fixed mapping. Production maintains per-specialty templates as versioned clinical-informatics assets owned by the institutional clinical-informatics or documentation-improvement team. Each specialty (primary care, behavioral health, cardiology, dermatology, neurology, geriatrics, others) has its own preferred SOAP, APSO, or specialty-specific structure; the templates capture the institutional preferences and drive the LLM rendering prompt construction. Templates evolve over time based on clinician feedback; a maintenance cadence is required.

**Per-clinician style adaptation.** The demo's `lookup_clinician_style` returns an empty preference set. Production captures per-clinician preferences (some clinicians prefer terse SOAP, some prefer narrative HPI prose, some have specific phrasings they have used for twenty years) either through explicit configuration or through learned-style adaptation based on the clinician's prior signed notes (with consent). The closer the rendered draft matches the clinician's voice, the lower the edit distance between draft and signed, and the higher the sustained adoption.

**Layered faithfulness program.** The demo's runtime faithfulness check is the first line of defense. Production additionally maintains a multi-layer program: rule-based grounding verification (every claim has a transcript or EHR citation), LLM-judge faithfulness scoring (flagged claims are reviewed by a separate model), clinical-rule-based contradiction detection (the note says X but the transcript implies not-X), and offline sampling review (clinical-quality team reviews a sample of generated notes against transcripts on a defined cadence). Owned by the clinical-quality officer, not the engineering team. Findings feed prompt and rule updates. Failed faithfulness checks are tracked as clinical-quality events.

**Faithfulness regression testing on prompt and model updates.** The note-rendering LLM and the faithfulness-checker model are versioned components. Each model update or prompt update can change faithfulness behavior in subtle ways. Production maintains a regression test suite: a held-out set of representative encounter transcripts with known good notes, automated faithfulness scoring on the regression set after every prompt or model change, manual review of the regression diffs before promoting changes to production. Promote changes through canary inference profiles with traffic shift, with rollback-on-regression triggers tied to the faithfulness regression metrics.

**Per-cohort accuracy and adoption monitoring with launch gates.** Per-cohort metrics (per-language, per-specialty, per-clinician, per-patient-cohort, per-audio-quality-band, per-room) are a launch gate, not a post-launch dashboard. Production defines cohort axes, per-cohort minimum sample sizes, per-cohort threshold metrics (WER, diarization error rate, faithfulness score, structured-extraction acceptance rate, edit distance, sustained adoption rate). Launch is gated on every cohort meeting the threshold, not on the institution-wide average. Disparity alerts trigger reviews; sustained disparity triggers product-level remediation including (potentially) disabling the feature for cohorts where it underperforms. Per-room reporting is particularly important: room acoustics drive substantial variation, and rooms that consistently underperform need physical-plant remediation.

**Recording-consent compliance with bystander handling.** The demo's `determine_consent_regime` uses a tiny static table. Production maintains the all-party-consent state list in a legal-team-reviewed configuration with an explicit update cadence. Bystander declaration at encounter start is a workflow-design problem: the clinician needs to be able to declare bystanders in two seconds, the disclosure has to be unambiguous to non-English-speaking patients (multilingual disclosure), the consent record has to capture who consented. Build the bystander-declaration workflow into the in-room device's start-of-encounter flow. Build a "someone new entered the room" affordance that the clinician can tap mid-encounter. Build clear signage in the exam room indicating the room may capture audio for documentation. Document the institutional policy on bystanders and review it with the privacy officer.

**Behavioral-health-specific privacy controls.** The demo flags `behavioral_health` visits with an explicit-acknowledgment disclosure but applies the same retention and access controls otherwise. Production builds a behavioral-health profile with stricter retention windows (often hours rather than days), narrower access controls (only the treating clinician and authorized clinical staff), redacted handling for sensitive content categories, and explicit consent capture per institutional policy. Substance-use treatment records under 42 CFR Part 2 have specific consent and disclosure requirements that the engineering pipeline supports through the behavioral-health profile. Some institutions exclude behavioral health from ambient documentation entirely; the architecture supports either choice.

**Biometric-data law compliance for clinician-voiceprint enrollment.** The demo's `CLINICIAN_VOICEPRINT_REGISTRY` is a dict. Production stores enrolled voiceprints in a secured registry with access controls, with explicit clinician consent at enrollment, with disclosure language meeting Illinois BIPA, Texas, and Washington biometric-data-law requirements where applicable. Voiceprints are biometric identifiers; the institutional privacy and legal team reviews the enrollment program before launch. Some institutions choose not to enroll voiceprints at all and accept the lower diarization accuracy that follows; this is a defensible choice for institutions in BIPA-equivalent jurisdictions where the compliance overhead is non-trivial.

**Audio retention policy with privacy-officer review.** The demo retains audio in a mock S3 store with no lifecycle. Production deployment requires explicit privacy-officer review of the retention duration, the access controls on retained audio, the consent disclosure language, and the deletion verification. The default is conservative (a few hours to a few days for QA review, then automatic deletion); longer retention requires explicit consent and an operational purpose. In-room audio captures bystanders and the clinic environment; the data-minimization argument is strong.

**EHR integration depth and write-back validation.** The demo's `MockEHR` is a dictionary. Production handles the EHR vendor's specific FHIR write surface (DocumentReference for the clinical note, MedicationRequest for medication updates, Condition for problem-list updates, ServiceRequest for orders, ProcedureRequest for referrals) plus vendor-specific extensions. Co-signature workflows for trainees (the resident drafts, the attending co-signs), late-addendum support (a separate signed document linked to the original; the original note is never modified), order-entry integration (a confirmed lab extraction drafts a CPOE order for separate clinician signature), and patient-portal release with institutionally-required hold periods are all production scope. The same explicit-confirmation rigor applies to every structured write. Plan the EHR integration as its own multi-month workstream with the EHR vendor's interface-team engagement.

**Disaster recovery and degraded-mode operation.** The demo assumes happy-path execution. Production tests the failure modes in staging quarterly: HealthScribe streaming unavailable (fall back to batch-only with delayed transcript), HealthScribe batch unavailable (fall back to manual documentation), Bedrock unavailable (fall back to manual documentation; the audit captures the failure), Comprehend Medical unavailable (skip structured-field extraction; surface the gap to the clinician), EHR API unreachable (hold the signed note in a queue with manual replay), in-room device failure (fall back to manual documentation, never silently lose the encounter). The clinician should never lose the encounter because of a downstream component failure. Quarterly DR exercises validate the failover paths.

**Idempotency and retry semantics.** The demo's session-id is generated freshly each run. Production uses a conditional DynamoDB write keyed on `(encounter_id, session_id)` so a duplicate encounter-start event (network blip, double click) is rejected with `ConditionalCheckFailedException` rather than producing two sessions. The note write to the EHR uses the idempotency key built in `clinician_sign` so a retry of the EHR write does not produce two DocumentReference resources. Configure DLQs on every Lambda; alarm on DLQ depth.

**Performance under burst load.** Encounter volume has strong diurnal and weekly patterns. Monday mornings spike. The demo runs encounters one at a time. Production holds the latency budget under burst: HealthScribe streaming session quotas, HealthScribe batch concurrent-job quotas, Bedrock model invocation quotas, downstream EHR API rate limits all need provisioning headroom and burst-capacity planning. Reserve concurrency where the latency-sensitive Lambdas would otherwise be starved. Load test against realistic peak profiles before launch.

**Vendor evaluation rigor for build-vs-buy decisions.** Most institutions deploying ambient documentation should be buying a commercial product (HealthScribe-built, commercial vendors like Microsoft Nuance DAX / Suki / Abridge / Ambience / Augmedix / Deep Scribe, EHR-vendor-bundled offerings) rather than building one from scratch. The demo's pipeline is the architecture for the careful-custom-build path. The vendor evaluation program runs in parallel: per-cohort accuracy benchmarking against held-out audio, faithfulness evaluation, scope-containment evaluation, EHR integration depth, in-room device support, reference checks with comparable institutions. A custom build that cannot match the major commercial vendors on these axes is the wrong call. Even institutions that buy still benefit from understanding the architecture deeply for vendor evaluation, contract negotiation, and operational ownership.

**Audit log retention and legal hold.** The demo's audit-archive S3 bucket is created without Object Lock in the mock. Production enables Object Lock in compliance mode with retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, the EHR vendor's audit-retention floor, and the institutional regulatory floor. Legal hold capabilities (suspending deletion for specific clinicians or patients during litigation) are configurable.

**Cost monitoring per specialty, per cohort, and per room.** Different specialties have very different per-encounter costs (a long primary-care visit with a complex assessment is structurally different from a quick pediatric well-child visit). Per-specialty, per-cohort, and per-room cost dashboards let operations identify outliers and tune accordingly. Per-room cost monitoring also surfaces room-specific issues (a room whose audio quality forces fall-backs to manual documentation more often than other rooms is worth investigating).

**In-room device and per-room audio-quality monitoring.** The demo emits audio-quality fixtures. Production extracts real signal-to-noise ratio, speech-detection rate, acoustic-event detections, and beamforming-confidence metrics from the device's telemetry. Trends in per-room audio quality over time identify systematic issues (a room where HVAC noise is consistently high, a room where the microphone placement is suboptimal, a device that has degraded over time) that drive remediation.

**Clinician training and adoption support.** Production includes a clinician adoption program: initial training (60-90 minutes per clinician on the device controls, the review interface, the structured-extraction confirmation, in-encounter narration patterns that improve note quality, and the in-room consent workflow), ongoing office hours and support during the first month, per-clinician feedback collection, and per-clinician adaptation of the system over time (custom vocabulary additions, template preferences, voiceprint enrollment). Adoption is not a feature flag; it is a workflow change-management program. Plan it as a months-long workstream with named clinical-leadership ownership.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the consent-regime determination with edge cases (multi-jurisdiction visits, behavioral-health profile selection), unit tests for the speaker-role mapping, unit tests for the faithfulness-severity classifier, integration tests against test buckets and tables, and end-to-end tests that simulate full encounter flows including the faithfulness-block path, the guardrail-intervention path, the per-device-type paths, and the multi-language paths. Never use real patient encounter audio in test fixtures; voice samples are biometric and PHI-bearing data with non-trivial governance implications. Use synthetic patients (Synthea-style) and TTS-generated audio with known ground truth, or open evaluation datasets (MTS-Dialog, Primock57) with their licensing terms reviewed before integration.

**Observability beyond the metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-stage investigation. Production runs CloudWatch Logs Insights queries that join across the audio-stream-handler logs, the batch-trigger logs, the institutional-rendering logs, the faithfulness-check logs, the structured-field-extractor logs, and the EHR-handoff logs by session_id. AWS X-Ray traces show the latency contribution of each stage. When a single encounter goes wrong (a faithfulness check fails, an EHR handoff stalls, a per-cohort disparity alert fires), the on-call engineer needs to reconstruct the full trace in seconds.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 10.7: Ambient Clinical Documentation](chapter10.07-ambient-clinical-documentation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard. See [Recipe 2.8: Ambient Clinical Documentation](chapter02.08-ambient-clinical-documentation) for the LLM-focused companion that covers note generation, faithfulness, consent management, and EHR integration in deeper detail. See [Recipe 10.6: Speech-to-Text for Telehealth Documentation](chapter10.06-speech-to-text-telehealth-documentation) for the telehealth sibling, which shares the ASR core but has different audio-path engineering and consent design.*
