# Recipe 10.6: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 10.6. It shows one way you could translate the telehealth speech-to-text pipeline into working Python using boto3 against Amazon Transcribe (streaming and batch with channel identification and diarization), Amazon Bedrock (with Guardrails for the note-generation and faithfulness-checking models), Amazon Comprehend Medical (for medication and condition extraction with RxNorm and ICD-10 coding), Amazon Polly (for optional patient-facing audio summaries), AWS Lambda, AWS Step Functions, Amazon API Gateway, Amazon Cognito, Amazon DynamoDB, Amazon S3, AWS KMS, AWS Secrets Manager, Amazon EventBridge, and Amazon CloudWatch. Optionally, Amazon Chime SDK and Amazon Kinesis Video Streams sit in front of the audio path when the institution runs its own telehealth video infrastructure. The demo uses a `MockTranscribeStreaming` standing in for the streaming ASR session, a `MockTranscribeBatch` standing in for the batch ASR job, a `MockBedrock` standing in for the LLM-driven note generation and faithfulness checking, a `MockComprehendMedical` standing in for the coded clinical-entity extraction, a `MockEHR` standing in for the FHIR-based note write-back and structured chart updates, and small helpers for the visit-state table, the transcript-state table, the note-state table, the audio S3 bucket, the transcript S3 bucket, the audit S3 bucket, the EventBridge bus, and CloudWatch-style metrics. It is not production-ready. There is no real telehealth platform integration carrying audio frames through Chime SDK or a third-party platform's API, no real Cognito authorizer, no real WebSocket-based streaming Transcribe session, no real Bedrock invocation, no real Comprehend Medical inference, no real DynamoDB or S3 wiring, no Step Functions state machine, no IAM least-privilege role per Lambda, no KMS customer-managed key configuration, no VPC endpoints, no per-cohort accuracy disparity alerting, no behavioral-health profile with stricter retention, no production faithfulness-regression test suite, no real EHR FHIR write-back, and no production patient-portal release flow. Think of it as the sketchpad version: useful for understanding the shape of a telehealth speech-to-text pipeline that respects the recording-consent discipline, the per-channel-audio discipline, the streaming-and-batch-reconciliation discipline, the LLM-faithfulness discipline, the structured-extraction-with-explicit-confirmation discipline, the side-by-side-review discipline, and the cohort-stratified audit discipline this recipe demands. It is not something you would deploy to clinicians on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the seven core pseudocode steps from the main recipe: capture consent at visit start and bootstrap the speech-to-text session (Step 1), run streaming ASR per channel and update the live display (Step 2), run batch ASR after the visit ends and reconcile with the streaming transcript (Step 3), generate the structured note draft with grounded citations and run faithfulness checks (Step 4), extract structured fields with explicit clinician confirmation gates (Step 5), present the draft to the clinician for review-and-sign with side-by-side transcript display (Step 6), and audit, archive, and feed cohort-stratified accuracy monitoring (Step 7). The synthetic patients, providers, encounters, medications, and conversations in the demo are fictional; the names, MRNs, RxNorm codes, ICD-10 codes, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

Streaming Transcribe (and Transcribe Medical) is HTTP/2 and is not exposed through the regular boto3 transcribe client. The streaming API is wrapped by a separate Python package:

```bash
pip install amazon-transcribe
```

In production you would also configure the telehealth video platform (Amazon Chime SDK with Kinesis Video Streams for institution-owned video, or a third-party platform like Zoom Healthcare, Teladoc Health, Doxy.me, Microsoft Teams Healthcare, or vendor-bundled telehealth from Epic or Cerner with platform-specific audio APIs), an Amazon Transcribe custom vocabulary per institution and per language, an optional Amazon Transcribe custom language model trained on institutional clinical text for higher accuracy on specialty-specific vocabulary, an Amazon Bedrock inference profile pinned to a specific note-generation model and region, an Amazon Bedrock Guardrails configuration filtering clinical-advice and harmful-content categories, the Lambda functions that orchestrate each pipeline stage (the visit-start handler, the audio-capture coordinator, the streaming-ASR result handler, the batch-reprocessing trigger, the reconciliation worker, the note-generation invoker, the faithfulness-check runner, the structured-field extractor, the EHR write-back, the audit writer), an AWS Step Functions state machine that durably orchestrates the post-visit pipeline with retry semantics, DynamoDB tables that hold visit state, transcript state, and note state across the lifecycle, AWS Secrets Manager secrets for the EHR API credentials and the patient-portal integration credentials, an Amazon EventBridge bus for cross-system events (`session_started`, `visit_transcribed`, `note_generated`, `note_signed`, `visit_audited`), Amazon S3 buckets for audio recordings (with brief-retention lifecycle), transcripts and generated notes (with medical-record retention), and the long-term audit archive (with Object Lock in compliance mode), and customer-managed KMS keys for every PHI-bearing data class. The demo replaces all of these with small mocks so the focus stays on the per-stage processing logic rather than on the cloud-resource provisioning.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `transcribe:StartStreamTranscription` and `transcribe:StartTranscriptionJob` for streaming and batch ASR, with `transcribe:CreateVocabulary`, `transcribe:UpdateVocabulary`, `transcribe:GetVocabulary` for custom-vocabulary management
- `bedrock:InvokeModel` for the note-generation and faithfulness-checker models, scoped to the specific foundation-model ARNs and inference profiles in use
- `bedrock:ApplyGuardrail` for the runtime guardrails check on generated content
- `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM` for coded clinical-entity extraction
- `polly:SynthesizeSpeech`, `polly:GetLexicon` for optional patient-facing audio summaries
- `chime:CreateMediaCapturePipeline`, `chime:DeleteMediaCapturePipeline` plus `kinesisvideo:GetMedia`, `kinesisvideo:GetDataEndpoint` when Chime SDK and Kinesis Video Streams are the audio path
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the visit-state, transcript-state, and note-state tables
- `s3:GetObject`, `s3:PutObject` on the audio bucket, the transcript bucket, and the audit-archive bucket, scoped to the per-visit key prefixes
- `secretsmanager:GetSecretValue` on the EHR-API credentials and patient-portal credential secrets pinned to the current rotation version
- `events:PutEvents` on the visit-events EventBridge bus
- `cloudwatch:PutMetricData` for the operational metrics (per-stage latency, per-channel ASR confidence, faithfulness scores, edit-distance distributions, structured-extraction acceptance rates, per-clinician adoption)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the audio bucket, the transcript bucket, the audit bucket, the DynamoDB tables, and the Secrets Manager secrets
- `states:StartExecution` for the Step Functions state machine that orchestrates the post-visit pipeline

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The visit-start Lambda has scoped DynamoDB write for the visit-state table only. The streaming-ASR-handler Lambda has scoped Transcribe streaming session creation rights and write access to the transcript-state table only. The note-generation Lambda has scoped Bedrock invocation rights pinned to one model and one inference profile. The structured-field-extractor Lambda has scoped Comprehend Medical inference rights only. The EHR-handoff Lambda has scoped Secrets Manager read for the EHR credentials and the EHR-specific egress path only. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Audio is PHI throughout, with telehealth-specific complications.** Telehealth audio captures the patient's voice in their home environment, often with bystanders audible in the background, with content that is often more candid than what makes it to the formal record. The architecture treats audio as PHI throughout: encrypted at rest with KMS customer-managed keys, encrypted in transit with TLS, retention bound by an explicit privacy-officer-reviewed policy, BAAs in place for any vendor service that processes the audio. The retention is typically shorter than for in-person ambient recording because the data-minimization argument is stronger (the patient's home audio captures more bystander content than a clinical exam room).
- **Per-channel audio access is an architectural priority.** When the platform exposes per-participant audio as separate channels, diarization is essentially trivial: each channel maps to a known speaker. When the audio is mixed into a single channel, diarization runs acoustically and quality drops. The demo's `audio_capture_config` flag chooses between the two paths; production aggressively pursues per-channel access during platform selection and integration.
- **Streaming and batch run in parallel, not in sequence.** The streaming pipeline serves the in-visit display; the batch pipeline serves the canonical post-visit transcript. They are independent paths sharing an audio source. Failure of one does not take down the other. The demo's `run_streaming_asr` and `run_batch_transcription` are separate functions; production has separate Step Functions state machines so a streaming hiccup does not block batch processing.
- **State-by-state recording-consent law applies and follows the patient.** The patient's location at visit time governs (in telehealth, this often differs from the institution's location). All-party-consent jurisdictions require an explicit consent disclosure plus acknowledgment; one-party-consent jurisdictions require less but most institutions still play a recording notice. Behavioral-health visits may have additional state-level confidentiality requirements (42 CFR Part 2 for substance-use treatment records) on top of HIPAA. The demo's `determine_consent_regime` and the behavioral-health profile sketch the pattern.
- **LLM faithfulness is a structural risk, not a side issue.** When an LLM generates a clinical note from a transcript, "may have" can become "had," "intermittent" can become "occasional," and clinical content the patient never said can be invented. Run the faithfulness check at runtime (Step 4C in the pseudocode); also maintain an offline evaluation set across specialties that gates production model and prompt updates on regression results. The demo's `run_faithfulness_check` is illustrative; production uses citation-based grounding verification, an LLM-judge faithfulness scoring pass, and clinical-rule-based contradiction detection in cascade.
- **Structured-field extractions require explicit clinician confirmation.** The medication-and-problem extraction occasionally pulls from passing mentions ("I used to take lisinopril years ago") rather than from active clinical content. Never silently apply a structured update from a transcript. The demo's `clinician_save_review` enforces accept-only writes with the supporting transcript context displayed alongside.
- **Per-cohort accuracy monitoring is a launch gate, not an analytics afterthought.** Voice ASR has well-documented accuracy disparities across speaker demographics; in telehealth, the audio-quality variability layered on top of the demographic variation compounds the equity problem. The cohort axes (per-language, per-specialty, per-clinician, per-patient-cohort, per-audio-quality-band) are policy-level decisions made with the equity-monitoring committee. The demo emits the cohort dimensions on every metric so you can see the segmentation pattern.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, and numeric metadata field passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses Chime SDK, multiple Lambdas, the Step Functions orchestration, the EventBridge fan-out, and the CloudWatch metric emission into a single Python file for readability.** In production each pipeline stage is a separate Lambda with its own IAM role, error handling, retries, and DLQs, with Step Functions as the durable orchestrator for the post-visit workflow. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the per-language Polly voices, the per-specialty templates, the faithfulness thresholds, the consent disclosures, and the cohort axes are what you would change between environments.

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
# to CloudWatch Logs Insights. The telehealth speech-to-text
# pipeline operates on heavily PHI-bearing data: the audio is
# PHI, the verbatim transcript is PHI, the generated note is
# PHI, the structured-field extractions are PHI, and every
# signature event is a clinical-record transaction. Log
# structural metadata only (session_id, ASR confidence band,
# faithfulness score band, signature event), never raw
# transcripts, never patient demographics, never medication or
# diagnosis values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from Transcribe, Bedrock,
# Comprehend Medical, Polly, DynamoDB, S3, EventBridge,
# CloudWatch, and Secrets Manager. The streaming-display
# latency budget is tight (a couple of seconds end to end);
# the post-visit batch budget is looser (a minute or two is
# acceptable). Cap the retries on the streaming path so the
# in-visit display does not stall; let the batch path retry
# more aggressively because the clinician is no longer
# waiting in real time.
BOTO3_RETRY_CONFIG_STREAMING = Config(
    retries={"max_attempts": 2, "mode": "adaptive"})
BOTO3_RETRY_CONFIG_BATCH = Config(
    retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm
# containers so each invocation does not pay the connection
# cost. The demo below uses Mock* classes instead; the real
# clients are never invoked here. Note: streaming Transcribe
# does not run through the boto3 transcribe client; it uses
# the standalone amazon-transcribe-streaming-sdk Python package
# (TranscribeStreamingClient.start_stream_transcription).
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
polly_client           = boto3.client("polly", region_name=REGION,
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
VISIT_STATE_TABLE         = "telehealth-stt-visit-state"
TRANSCRIPT_STATE_TABLE    = "telehealth-stt-transcript-state"
NOTE_STATE_TABLE          = "telehealth-stt-note-state"
AUDIO_BUCKET              = "telehealth-stt-audio"
TRANSCRIPT_BUCKET         = "telehealth-stt-transcripts"
AUDIT_ARCHIVE_BUCKET      = "telehealth-stt-audit-archive"
VISIT_EVENT_BUS_NAME      = "telehealth-stt-events-bus"
CLOUDWATCH_NAMESPACE      = "TelehealthSTT"
INSTITUTION_ID            = "academic-medical-center-richmond"
INSTITUTIONAL_VOCABULARY  = "telehealth-clinical-vocabulary"
INSTITUTIONAL_LANGUAGE_MODEL = "telehealth-clinical-lm-v2"
TELEHEALTH_NOTE_GUARDRAIL_ID = "guardrail-78901"
TELEHEALTH_NOTE_GUARDRAIL_VERSION = "2"

# Bedrock configuration. In production, pin to a specific model
# version and inference profile so a model upgrade does not
# silently change note-generation behavior. The model and
# region combination must be in your AWS BAA scope.
BEDROCK_NOTE_GENERATION_MODEL_ID = (
    "anthropic.claude-3-5-sonnet-20240620-v1:0")
BEDROCK_NOTE_GENERATION_PROFILE_ARN = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "telehealth-note-gen-v1")
# A smaller, cheaper model is appropriate for the faithfulness
# check; the check is structurally simpler than the generation.
BEDROCK_FAITHFULNESS_MODEL_ID = (
    "anthropic.claude-3-haiku-20240307-v1:0")
BEDROCK_FAITHFULNESS_PROFILE_ARN = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "telehealth-faithfulness-v1")
# Structured extraction uses the same Sonnet-class model as
# note generation, but with a different prompt and a strict
# JSON-schema response format.
BEDROCK_EXTRACTION_MODEL_ID = (
    "anthropic.claude-3-5-sonnet-20240620-v1:0")

# Polly TTS voice persona for optional patient-facing audio
# summaries. Pick one consistent voice per language.
POLLY_VOICE_BY_LANGUAGE = {
    "en-US": "Joanna",
    "es-US": "Lupe",
}
POLLY_LEXICON_NAMES = [
    "institutional-pronunciations",
    "medication-pronunciations",
    "provider-pronunciations",
]

# Deploy-time guardrail. Any blank resource name is a deploy-
# time bug, not a runtime surprise.
for _name, _value in [
    ("VISIT_STATE_TABLE",         VISIT_STATE_TABLE),
    ("TRANSCRIPT_STATE_TABLE",    TRANSCRIPT_STATE_TABLE),
    ("NOTE_STATE_TABLE",          NOTE_STATE_TABLE),
    ("AUDIO_BUCKET",              AUDIO_BUCKET),
    ("TRANSCRIPT_BUCKET",         TRANSCRIPT_BUCKET),
    ("AUDIT_ARCHIVE_BUCKET",      AUDIT_ARCHIVE_BUCKET),
    ("VISIT_EVENT_BUS_NAME",      VISIT_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",      CLOUDWATCH_NAMESPACE),
    ("INSTITUTIONAL_VOCABULARY",  INSTITUTIONAL_VOCABULARY),
    ("BEDROCK_NOTE_GENERATION_MODEL_ID",
        BEDROCK_NOTE_GENERATION_MODEL_ID),
    ("BEDROCK_FAITHFULNESS_MODEL_ID",
        BEDROCK_FAITHFULNESS_MODEL_ID),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every visit record carries the versions of the artifacts that
# influenced it: the streaming ASR model version, the batch ASR
# model version, the note-generation prompt version, the
# faithfulness-check prompt version, the structured-extraction
# rules version, the per-specialty template version. A future
# audit reconstructs which configuration was active when a
# particular visit was processed.
STREAMING_ASR_MODEL_VERSION   = "transcribe-streaming-2026-q1"
BATCH_ASR_MODEL_VERSION       = "transcribe-batch-2026-q1"
NOTE_GENERATION_PROMPT_VERSION = "note-gen-prompt-v2.1"
FAITHFULNESS_PROMPT_VERSION   = "faithfulness-prompt-v1.3"
STRUCTURED_EXTRACTION_VERSION = "structured-extraction-v1.2"
TEMPLATE_LIBRARY_VERSION      = "templates-v3.0"

# --- ASR Confidence Gates ---
# Average per-word confidence below this floor flags the
# transcript for QA review and surfaces a low-confidence flag
# to the reviewing clinician. The minimum-confidence-word count
# is a secondary gate: even a high-average-confidence transcript
# with several critical words at very low confidence (often
# medication names) deserves an explicit review highlight.
ASR_MIN_AVG_CONFIDENCE              = Decimal("0.85")
ASR_LOW_CONFIDENCE_WORD_THRESHOLD   = Decimal("0.70")
ASR_QA_REVIEW_LOW_CONF_WORD_LIMIT   = 5

# --- Faithfulness Threshold ---
# The faithfulness checker returns a score in [0, 1]; below
# this threshold, the draft is either blocked (severity=block)
# or flagged for the clinician's attention (severity=flag).
# Severity is determined per failure type by the institutional
# faithfulness program.
FAITHFULNESS_PASS_THRESHOLD     = Decimal("0.88")
FAITHFULNESS_BLOCK_THRESHOLD    = Decimal("0.65")

# --- Recording Consent Disclosures ---
# Production looks up the patient's jurisdiction at visit time
# and selects the appropriate disclosure. Behavioral-health
# visits may use a different disclosure that explicitly
# mentions transcript handling.
CONSENT_DISCLOSURE_ALL_PARTY = (
    "This visit is being recorded and transcribed for your "
    "medical record. To continue, please confirm by saying "
    "yes or staying on the line.")
CONSENT_DISCLOSURE_ONE_PARTY = (
    "This visit is being recorded and transcribed for your "
    "medical record.")
CONSENT_DISCLOSURE_BEHAVIORAL_HEALTH = (
    "This visit is being recorded and transcribed for your "
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

# --- Cohort Axes ---
# Stratification axes used in the audit pipeline for equity
# monitoring. The age-band and primary-language are opt-in:
# the patient self-discloses during portal enrollment.
# Inferred demographic labels for protected classes are
# explicitly not used.
COHORT_AXES = ["language", "visit_type", "specialty",
               "audio_quality_band", "age_band"]

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
    "cardiology-followup-v1": {
        "id":       "cardiology-followup-v1",
        "specialty": "cardiology",
        "structure": "APSO",
        "sections": ["assessment", "plan",
                     "subjective", "objective"],
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
    Categorize per-channel audio quality into a small number of
    bands for cohort stratification. Production tunes these
    thresholds against the institution's actual audio-quality
    distribution.
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

These mocks stand in for the production AWS resources and back-office systems. They are deliberately simple and are not how you would build the real thing. Their purpose is to keep the focus on the telehealth speech-to-text pipeline logic.

```python
class MockTranscribeStreaming:
    """
    Stands in for the streaming Transcribe API used during the
    visit. In production, the streaming API runs over HTTP/2
    via the amazon-transcribe Python package. For per-channel
    separated audio, two parallel streaming sessions run (one
    per channel) and the transcripts are merged by timestamp
    downstream. For mixed audio with diarization, a single
    streaming session runs with diarization enabled. The mock
    plays back canned per-segment streaming events so the
    pipeline can be exercised without a real audio source.
    """
    def __init__(self, fixture_segments):
        # fixture_segments is keyed by visit_id, with each entry
        # a list of segment dicts that simulate what would
        # arrive on the streaming connection.
        self._fixtures = fixture_segments
        self.streamed = []

    def stream_per_channel(self, session_id, visit_id,
                           channel_role, language):
        """
        Yields streaming-event dicts for the given channel.
        Production yields these as they arrive; the mock yields
        them in the order specified by the fixture.
        """
        segments = self._fixtures.get(visit_id, [])
        for segment in segments:
            if segment["speaker_role"] != channel_role:
                continue
            event = {
                "session_id":      session_id,
                "speaker_role":    channel_role,
                "transcript":      segment["text"],
                "is_partial":      False,
                "timestamp":       segment["timestamp"],
                "average_word_confidence":
                    segment.get("confidence", Decimal("0.9")),
                "words": [{"word": w,
                           "confidence": segment.get("confidence",
                                                      Decimal("0.9"))}
                           for w in segment["text"].split()],
            }
            self.streamed.append(event)
            yield event


class MockTranscribeBatch:
    """
    Stands in for the batch Transcribe API used after the visit
    ends. In production this is
    transcribe_batch.start_transcription_job(...) with channel
    identification (when audio is per-channel separated) or
    speaker labels (when audio is mixed). The mock returns a
    canned full-visit transcript with full diarization applied.
    """
    def __init__(self, fixture_transcripts):
        self._fixtures = fixture_transcripts
        self.jobs_started = []

    def start_transcription_job(self, visit_id, audio_uri,
                                  language, per_channel):
        job_name = f"{visit_id}_batch_{uuid.uuid4().hex[:6]}"
        self.jobs_started.append({
            "job_name":      job_name,
            "visit_id":      visit_id,
            "audio_uri":     audio_uri,
            "language":      language,
            "per_channel":   per_channel,
            "started_at":    _now_iso(),
        })
        # Return a fake job descriptor that "completes
        # immediately" for the demo.
        return {"TranscriptionJobName": job_name,
                "TranscriptionJobStatus": "COMPLETED"}

    def retrieve_transcript(self, visit_id):
        return dict(self._fixtures.get(visit_id, {}))


class MockBedrock:
    """
    Stands in for Amazon Bedrock's InvokeModel. Three invocation
    patterns: note generation (returns a structured note draft
    with citations), faithfulness check (returns a 0-to-1
    score plus a list of any failed checks), and structured
    extraction (returns a JSON-schema-validated extraction
    object).
    """
    def __init__(self, note_responses, faithfulness_responses,
                 extraction_responses):
        self._note_responses = note_responses
        self._faithfulness_responses = faithfulness_responses
        self._extraction_responses = extraction_responses
        self.invocations = []

    def generate_note(self, visit_id, transcript, template,
                       guardrail_id):
        # Production: bedrock_runtime.invoke_model with a strict
        # JSON-schema response_format and the transcript and
        # template structure in the prompt context. The
        # guardrail is applied at runtime via the guardrail_id
        # parameter.
        self.invocations.append({
            "type":       "note_generation",
            "visit_id":   visit_id,
            "template":   template["id"],
            "guardrail_id": guardrail_id,
        })
        response = self._note_responses.get(visit_id, {
            "content":   {"sections": {}},
            "citations": [],
        })
        return {"body": json.dumps(response)}

    def check_faithfulness(self, visit_id, generated_note,
                            transcript):
        # Production: bedrock_runtime.invoke_model with a
        # smaller model, prompted to score the generated note
        # against the source transcript for citation grounding,
        # absence of hallucinated content, and clinical
        # consistency.
        self.invocations.append({
            "type":     "faithfulness_check",
            "visit_id": visit_id,
        })
        response = self._faithfulness_responses.get(visit_id, {
            "score":         0.95,
            "failed_checks": [],
            "annotations":   [],
        })
        return {"body": json.dumps(response)}

    def extract_higher_level_fields(self, visit_id, transcript):
        # Production: bedrock_runtime.invoke_model for entities
        # Comprehend Medical does not directly extract (orders,
        # follow-up actions, patient-reported vitals, allergies).
        self.invocations.append({
            "type":     "structured_extraction",
            "visit_id": visit_id,
        })
        response = self._extraction_responses.get(visit_id, {
            "orders_placed":           [],
            "labs_requested":          [],
            "imaging_requested":       [],
            "follow_up_appointments":  [],
            "patient_reported_vitals": [],
            "patient_reported_allergies": [],
        })
        return {"body": json.dumps(response)}


class MockComprehendMedical:
    """
    Stands in for Amazon Comprehend Medical's DetectEntitiesV2,
    InferRxNorm, and InferICD10CM APIs. Used to extract coded
    medication and condition entities from the transcript.
    """
    def __init__(self, entity_fixtures):
        self._fixtures = entity_fixtures
        self.invocations = []

    def detect_entities(self, text):
        self.invocations.append({"type": "detect_entities",
                                 "text_len": len(text)})
        return self._fixtures.get("detect_entities", {"Entities": []})

    def infer_rx_norm(self, text):
        self.invocations.append({"type": "infer_rx_norm",
                                 "text_len": len(text)})
        return self._fixtures.get("infer_rx_norm", {"Entities": []})

    def infer_icd10cm(self, text):
        self.invocations.append({"type": "infer_icd10cm",
                                 "text_len": len(text)})
        return self._fixtures.get("infer_icd10cm", {"Entities": []})


class MockEHR:
    """
    Stands in for the EHR's FHIR write surface for clinical
    notes (DocumentReference), structured chart updates
    (MedicationRequest, Condition, Observation), and patient-
    portal release. In production this is the EHR vendor's
    FHIR API authenticated through SMART on FHIR or backend-
    services authentication.
    """
    def __init__(self):
        self.documents_written = []
        self.chart_updates = []
        self.portal_releases = []

    def write_document_reference(self, patient_id, encounter_id,
                                   document_content, author,
                                   signed_at):
        document_id = f"doc-{uuid.uuid4().hex[:10]}"
        self.documents_written.append({
            "document_id":      document_id,
            "patient_id":       patient_id,
            "encounter_id":     encounter_id,
            "document_content": document_content,
            "author":           author,
            "signed_at":        signed_at,
        })
        return {"document_id": document_id}

    def apply_structured_update(self, patient_id, update_kind,
                                  payload):
        self.chart_updates.append({
            "patient_id":   patient_id,
            "update_kind":  update_kind,  # medication, problem, lab
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

    def queue_review_decisions(self, decisions):
        self._review_decisions = list(decisions)

    def queue_signature(self, signature):
        self._signature = dict(signature)

    def collect_review_decisions(self):
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


class MockVisitState:
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
    Stands in for S3 audio storage, transcript storage, and
    audit archive. Holds objects in memory keyed by
    (bucket, key). Production uses customer-managed KMS keys
    for encryption and lifecycle policies for retention.
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
    visit_transcribed, note_generated, note_signed,
    visit_audited.
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
visit_state            = MockVisitState()
transcript_state       = MockTranscriptState()
note_state             = MockNoteState()
ehr                    = MockEHR()
clinician_client       = MockClinicianReviewClient()
event_bus              = MockEventBus()
cloudwatch             = MockCloudWatch()
s3_store               = MockS3()
# transcribe_streaming, transcribe_batch_mock, bedrock_mock,
# and comprehend_mock are wired up in run_demo() with fixture
# data tailored to each scenario.
transcribe_streaming   = None
transcribe_batch_mock  = None
bedrock_mock           = None
comprehend_mock        = None


def audit_log(event):
    """
    Sanitized audit print so you can see the sequence of
    decisions without leaking the underlying values. Production
    routes events to CloudWatch Logs Insights with structured
    JSON; ship to a SIEM if available.
    """
    safe_event = {k: v for k, v in event.items()
                  if k not in {"verbatim_transcript",
                                "generated_note_text",
                                "patient_demographics",
                                "structured_decisions_raw"}}
    if "verbatim_transcript" in event:
        safe_event["verbatim_transcript_length"] = len(
            event["verbatim_transcript"] or "")
    if "generated_note_text" in event:
        safe_event["generated_note_text_length"] = len(
            event["generated_note_text"] or "")
    logger.info("AUDIT %s", json.dumps(safe_event, default=str))
```

---

## Step 1: Capture Consent at Visit Start and Bootstrap the Speech-to-Text Session

*The pseudocode calls this `ON visit_start(...)`. When a telehealth visit begins, the system captures the appropriate recording-and-transcription consent (institutional-policy-driven, state-law-aware), enables the speech-to-text feature per the visit's configuration, and bootstraps a session that links the visit ID to the audio capture path. Behavioral-health visits use a different disclosure that explicitly mentions transcript handling. Skip the per-visit consent confirmation and the institution risks documenting visits where the patient explicitly opted out, which is a privacy violation regardless of the engineering quality.*

```python
def determine_consent_regime(patient_jurisdiction,
                              institution_state,
                              visit_type):
    """
    Determine which recording-and-transcription consent
    disclosure the visit should use. Cross-jurisdiction
    visits follow the stricter of the two regimes (patient's
    state vs. institution's state). Behavioral-health visits
    use a behavioral-health-specific disclosure regardless of
    state regime, because the disclosure language about
    transcript handling matters for behavioral-health
    confidentiality.
    """
    if visit_type == "behavioral_health":
        # Behavioral-health profile: always require the
        # explicit-acknowledgment disclosure with transcript-
        # handling language.
        return "behavioral_health_explicit"

    if (patient_jurisdiction in ALL_PARTY_CONSENT_STATES
            or institution_state in ALL_PARTY_CONSENT_STATES):
        return "all_party_consent"
    return "one_party_consent"


def select_disclosure_text(consent_regime):
    """Return the appropriate disclosure text for the regime."""
    if consent_regime == "behavioral_health_explicit":
        return CONSENT_DISCLOSURE_BEHAVIORAL_HEALTH
    if consent_regime == "all_party_consent":
        return CONSENT_DISCLOSURE_ALL_PARTY
    return CONSENT_DISCLOSURE_ONE_PARTY


def configure_audio_capture(visit_id, platform_type,
                              prefer_per_channel=True):
    """
    Configure the audio capture path. Production reads the
    per-visit telehealth platform metadata (which platform,
    which audio API, what codecs are exposed) and chooses
    between per-channel separated audio and mixed audio. For
    institution-owned video via Chime SDK, per-channel access
    is straightforward; for third-party platforms, it depends
    on the platform's capabilities.
    """
    # Demo simplification: assume Chime SDK and third-party-
    # video-with-mixed-audio are the two possibilities.
    per_channel_separated = (
        prefer_per_channel and platform_type == "chime_sdk")
    return {
        "platform_type":         platform_type,
        "per_channel_separated": per_channel_separated,
        "encoding":              "pcm",
        "sample_rate":           16000,
        "clinician_channel":     f"audio/{visit_id}/clinician.pcm",
        "patient_channel":       f"audio/{visit_id}/patient.pcm",
        "mixed_channel":         f"audio/{visit_id}/mixed.pcm",
    }


def visit_start(visit_id, patient_id, clinician_id,
                clinician_specialty, patient_jurisdiction,
                visit_type, platform_type="chime_sdk",
                language="en-US",
                institution_state="VA",
                consent_acknowledged=True):
    """
    Start a telehealth speech-to-text session in response to a
    visit-start event. Plays the consent disclosure, bootstraps
    the visit state, and configures the audio capture path.

    Args:
        visit_id: Encounter identifier from the EHR.
        patient_id: Patient identifier (will be hashed in
            persistent state).
        clinician_id: Authenticated clinician identifier.
        clinician_specialty: Specialty key used for template
            selection.
        patient_jurisdiction: Two-letter state code for the
            patient's location at visit time.
        visit_type: e.g. "primary_care", "behavioral_health",
            "cardiology_followup".
        platform_type: "chime_sdk" or "third_party_video".
        language: Visit language. Defaults to en-US.
        institution_state: Institution's primary state.
        consent_acknowledged: For the demo, whether the patient
            acknowledged the disclosure. Production captures
            this from the actual consent flow.

    Returns:
        Session-context dict consumed by downstream stages, or
        a sentinel indicating the patient declined consent.
    """
    # Step 1A: determine the consent regime based on
    # jurisdiction and visit type.
    consent_regime = determine_consent_regime(
        patient_jurisdiction=patient_jurisdiction,
        institution_state=institution_state,
        visit_type=visit_type)

    disclosure_text = select_disclosure_text(consent_regime)

    # Step 1B: play the disclosure. Production routes the
    # disclosure text through the telehealth platform's audio
    # path so both clinician and patient hear it; the demo
    # simply records it. For all-party-consent and behavioral-
    # health regimes, gate continuation on explicit
    # acknowledgment.
    requires_acknowledgment = consent_regime in (
        "all_party_consent", "behavioral_health_explicit")
    if requires_acknowledgment and not consent_acknowledged:
        # The patient declined or did not acknowledge; the
        # speech-to-text feature is disabled for this visit
        # and the clinician falls back to manual documentation.
        audit_log({
            "event_type":      "STT_DECLINED_BY_PATIENT",
            "visit_id":        visit_id,
            "consent_regime":  consent_regime,
            "timestamp":       _now_iso(),
        })
        return {"feature_enabled": False,
                "reason":          "consent_declined",
                "consent_regime":  consent_regime}

    # Step 1C: bootstrap the speech-to-text session.
    session_id = "stt-" + uuid.uuid4().hex[:16]
    started_at = _now_iso()

    audio_capture_config = configure_audio_capture(
        visit_id=visit_id,
        platform_type=platform_type,
        prefer_per_channel=True)

    visit_state.put(session_id, _to_decimal({
        "session_id":              session_id,
        "visit_id":                visit_id,
        "patient_id_hash":         _hash_value(patient_id),
        "clinician_id":            clinician_id,
        "clinician_specialty":     clinician_specialty,
        "visit_type":              visit_type,
        "language":                language,
        "consent_regime":          consent_regime,
        "feature_status":          "enabled",
        "started_at":              started_at,
        "platform_type":           platform_type,
        "audio_capture_config":    audio_capture_config,
        "audio_archive_ref":       None,
        "canonical_transcript_ref": None,
        "per_channel_quality_metrics": {},
        "avg_streaming_asr_confidence": Decimal("0.0"),
        "avg_batch_asr_confidence":     Decimal("0.0"),
        "diarization_disagreement_count": 0,
        "streaming_asr_model_version":   STREAMING_ASR_MODEL_VERSION,
        "batch_asr_model_version":       BATCH_ASR_MODEL_VERSION,
        "note_generation_prompt_version":
            NOTE_GENERATION_PROMPT_VERSION,
        "faithfulness_prompt_version":
            FAITHFULNESS_PROMPT_VERSION,
        "structured_extraction_version":
            STRUCTURED_EXTRACTION_VERSION,
        "template_library_version":
            TEMPLATE_LIBRARY_VERSION,
    }))

    # Step 1D: emit lifecycle event.
    event_bus.put_events([{
        "Source":       "telehealth_stt",
        "DetailType":   "session_started",
        "EventBusName": VISIT_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":     session_id,
            "visit_id":       visit_id,
            "visit_type":     visit_type,
            "language":       language,
            "consent_regime": consent_regime,
            "platform_type":  platform_type,
            "timestamp":      started_at,
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "SessionsStarted", 1, "Count",
        dimensions={"visit_type":  visit_type,
                    "language":    language,
                    "specialty":   clinician_specialty,
                    "platform_type": platform_type})

    audit_log({
        "event_type":     "STT_SESSION_OPENED",
        "session_id":     session_id,
        "visit_id":       visit_id,
        "visit_type":     visit_type,
        "consent_regime": consent_regime,
        "language":       language,
        "platform_type":  platform_type,
        "per_channel_separated":
            audio_capture_config["per_channel_separated"],
        "timestamp":      started_at,
    })

    return {
        "feature_enabled":      True,
        "session_id":           session_id,
        "visit_id":             visit_id,
        "patient_id":           patient_id,
        "clinician_id":         clinician_id,
        "clinician_specialty":  clinician_specialty,
        "visit_type":           visit_type,
        "language":             language,
        "consent_regime":       consent_regime,
        "platform_type":        platform_type,
        "audio_capture_config": audio_capture_config,
        "started_at":           started_at,
        "disclosure_text":      disclosure_text,
    }
```

---

## Step 2: Run Streaming ASR Per Channel and Update the Live Display

*The pseudocode calls this `run_streaming_asr(...)`. As audio arrives from each channel, the streaming ASR produces partial-and-final transcripts that update the clinician's live display. Per-channel separation makes diarization trivial: the clinician's channel is labeled "clinician," the patient's channel is labeled "patient." When audio is mixed into a single channel, the streaming pipeline runs a single ASR with diarization enabled and the labels are mapped from acoustic clusters to roles using visit context. Skip the per-channel processing and diarization quality drops sharply for the audio configurations where it matters most.*

```python
def map_speaker_label_to_role(speaker_label, visit_id,
                                clinician_id):
    """
    Map an acoustic speaker label (spk_0, spk_1, spk_2) to a
    clinical role (clinician, patient, family_member). In
    production this uses timing heuristics (the clinician
    usually starts the visit and asks the first questions),
    optional voiceprint enrollment for known clinicians, or a
    simple convention agreed at session start. The demo uses
    a fixed convention for predictability.
    """
    label_to_role = {
        "spk_0": "clinician",
        "spk_1": "patient",
        "spk_2": "family_member",
    }
    return label_to_role.get(speaker_label, "unknown")


def run_streaming_asr(session_context):
    """
    Run the streaming ASR for the visit. For per-channel
    separated audio, two streaming sessions run (one per
    channel). For mixed audio, a single streaming session runs
    with diarization enabled and speaker labels mapped to
    roles using visit context.
    """
    session_id = session_context["session_id"]
    visit_id = session_context["visit_id"]
    audio_capture_config = session_context["audio_capture_config"]
    language = session_context["language"]

    # Track per-channel quality metrics for cohort
    # stratification.
    per_channel_quality = {"clinician": {"avg_snr_db": 28.0,
                                          "speech_rate": 0.7},
                            "patient":  {"avg_snr_db": 18.5,
                                          "speech_rate": 0.55}}

    if audio_capture_config["per_channel_separated"]:
        # Step 2A: launch one streaming ASR per channel. Each
        # channel maps to a known speaker role.
        channels_to_process = [
            ("clinician", audio_capture_config["clinician_channel"]),
            ("patient",   audio_capture_config["patient_channel"]),
        ]
    else:
        # Step 2C: mixed audio with diarization. A single
        # streaming session emits speaker labels alongside
        # the transcript; the demo's mock simulates the same
        # event flow by yielding both speakers from the mixed
        # channel.
        channels_to_process = [
            ("mixed", audio_capture_config["mixed_channel"]),
        ]

    streaming_confidence_sum = Decimal("0.0")
    streaming_segment_count = 0

    for channel_role, audio_source in channels_to_process:
        # In production:
        #   client = TranscribeStreamingClient(region=REGION)
        #   stream = await client.start_stream_transcription(
        #       language_code=language,
        #       media_sample_rate_hz=
        #           audio_capture_config["sample_rate"],
        #       media_encoding=audio_capture_config["encoding"],
        #       vocabulary_name=INSTITUTIONAL_VOCABULARY,
        #       language_model_name=INSTITUTIONAL_LANGUAGE_MODEL,
        #       show_speaker_label=
        #           not audio_capture_config["per_channel_separated"],
        #       number_of_channels=1)
        # The mock yields canned segments instead.
        for event in transcribe_streaming.stream_per_channel(
                session_id=session_id,
                visit_id=visit_id,
                channel_role=channel_role,
                language=language):

            # Step 2B/2C: handle each segment as it arrives.
            handle_streaming_event(
                session_id=session_id,
                speaker_role=event["speaker_role"],
                event=event,
                language=language)

            streaming_confidence_sum += Decimal(str(
                event["average_word_confidence"]))
            streaming_segment_count += 1

    avg_streaming_confidence = (
        (streaming_confidence_sum / streaming_segment_count)
        if streaming_segment_count else Decimal("0.0"))

    visit_state.update(session_id, _to_decimal({
        "per_channel_quality_metrics": per_channel_quality,
        "avg_streaming_asr_confidence":  avg_streaming_confidence,
    }))

    audit_log({
        "event_type":              "STREAMING_ASR_COMPLETED",
        "session_id":              session_id,
        "segments_processed":      streaming_segment_count,
        "avg_streaming_confidence":
            float(avg_streaming_confidence),
        "per_channel_separated":
            audio_capture_config["per_channel_separated"],
        "timestamp":               _now_iso(),
    })

    return {
        "session_id":             session_id,
        "segments_processed":     streaming_segment_count,
        "avg_confidence":         avg_streaming_confidence,
        "per_channel_quality":    per_channel_quality,
    }


def handle_streaming_event(session_id, speaker_role, event,
                            language):
    """
    Update the live display with the streaming partial or
    final, persist the segment to the transcript-state table,
    and emit per-channel quality metrics for cohort
    stratification.
    """
    transcript_state.append_streaming_segment(
        session_id=session_id,
        segment={
            "speaker_role":   speaker_role,
            "text":           event["transcript"],
            "is_final":       not event["is_partial"],
            "words":          event["words"],
            "timestamp":      event["timestamp"],
            "average_word_confidence":
                event["average_word_confidence"],
        })

    # Push the update to the clinician's live display.
    # Production calls the live-display API (an API Gateway
    # WebSocket push or a server-sent event); the demo just
    # records the metric.
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "StreamingASRConfidence",
        float(event["average_word_confidence"]), "None",
        dimensions={
            "speaker_role": speaker_role,
            "language":     language,
        })
```

---

## Step 3: Run Batch ASR After the Visit Ends and Reconcile with the Streaming Transcript

*The pseudocode calls this `run_batch_transcription(...)` and `reconcile_streaming_and_batch(...)`. When the visit ends, a batch ASR runs over the full audio with full context, producing a higher-accuracy transcript with full diarization. The batch transcript is reconciled with the streaming transcript: in-visit corrections from the clinician are carried forward, and the batch transcript is established as the canonical record. Skip the batch reprocessing and the canonical transcript is the lower-accuracy streaming output, which is fine for navigation but suboptimal for the documentation that goes into the chart.*

```python
def run_batch_transcription(session_context, audio_archive_ref):
    """
    Trigger the batch Transcribe job over the full audio. Use
    channel identification when per-channel audio was captured;
    use diarization when the audio is mixed.
    """
    session_id = session_context["session_id"]
    visit_id = session_context["visit_id"]
    audio_capture_config = session_context["audio_capture_config"]
    language = session_context["language"]

    # In production:
    #   transcribe_batch.start_transcription_job(
    #       TranscriptionJobName=f"{session_id}_batch",
    #       LanguageCode=language,
    #       Media={"MediaFileUri": audio_archive_ref},
    #       Settings={
    #           "VocabularyName": INSTITUTIONAL_VOCABULARY,
    #           "LanguageModelName": INSTITUTIONAL_LANGUAGE_MODEL,
    #           "ChannelIdentification": per_channel,
    #           # OR for mixed audio:
    #           # "ShowSpeakerLabels": True,
    #           # "MaxSpeakerLabels": 5,
    #       })
    # then poll get_transcription_job until COMPLETED. The mock
    # collapses this to a single call that returns immediately.
    job = transcribe_batch_mock.start_transcription_job(
        visit_id=visit_id,
        audio_uri=audio_archive_ref,
        language=language,
        per_channel=audio_capture_config["per_channel_separated"])

    batch_transcript = transcribe_batch_mock.retrieve_transcript(
        visit_id=visit_id)

    audit_log({
        "event_type":      "BATCH_ASR_COMPLETED",
        "session_id":      session_id,
        "job_name":        job["TranscriptionJobName"],
        "segment_count":   len(batch_transcript.get("segments", [])),
        "timestamp":       _now_iso(),
    })

    return batch_transcript


def align_by_timestamp(streaming_segments, batch_segments):
    """
    Align streaming and batch segments by timestamp for
    reconciliation. Production uses a more sophisticated
    aligner that handles partial overlaps; the demo collapses
    this to a simple by-index match for predictability.
    """
    aligned = []
    for index, batch_seg in enumerate(batch_segments):
        streaming_seg = (streaming_segments[index]
                          if index < len(streaming_segments)
                          else None)
        aligned.append({
            "index":           index,
            "timestamp":       batch_seg.get("timestamp"),
            "streaming_text":  (streaming_seg or {}).get("text"),
            "streaming_speaker":
                (streaming_seg or {}).get("speaker_role"),
            "batch_text":      batch_seg.get("text"),
            "batch_speaker":   batch_seg.get("speaker_role"),
        })
    return aligned


def reconcile_streaming_and_batch(session_context,
                                    batch_transcript):
    """
    Identify segments where streaming and batch disagree,
    carry forward in-visit corrections from the streaming
    transcript, and persist the canonical transcript.
    """
    session_id = session_context["session_id"]

    streaming_segments = transcript_state.get_streaming_segments(
        session_id)
    batch_segments = batch_transcript.get("segments", [])

    # Step 3C: align the two transcripts by timestamp and
    # identify disagreements.
    aligned = align_by_timestamp(streaming_segments,
                                   batch_segments)
    disagreements = [
        seg for seg in aligned
        if seg["streaming_text"]
        and seg["batch_text"]
        and seg["streaming_text"] != seg["batch_text"]
    ]

    # Step 3D: any in-visit clinician corrections (the
    # clinician fixed a misrecognized word during the visit)
    # were stored on the streaming-segment records. Production
    # carries these forward into the batch transcript by
    # replacing the matching batch segment text. The demo
    # collapses this to a no-op since the fixtures do not
    # include in-visit corrections.
    canonical_segments = list(batch_segments)

    # Compute average batch confidence for the cohort metrics.
    batch_confidence_sum = Decimal("0.0")
    batch_segment_count = 0
    for seg in batch_segments:
        batch_confidence_sum += Decimal(str(
            seg.get("confidence", 0.9)))
        batch_segment_count += 1
    avg_batch_confidence = (
        (batch_confidence_sum / batch_segment_count)
        if batch_segment_count else Decimal("0.0"))

    # Step 3E: persist the canonical transcript.
    canonical_transcript = {
        "session_id":         session_id,
        "visit_id":           session_context["visit_id"],
        "language":           session_context["language"],
        "duration_seconds":
            batch_transcript.get("duration_seconds", 0),
        "segments":           canonical_segments,
        "diarization_quality":
            batch_transcript.get("diarization_quality", "high"),
        "per_channel_audio":
            session_context["audio_capture_config"][
                "per_channel_separated"],
        "in_visit_corrections": 0,
        "disagreement_count": len(disagreements),
    }

    transcript_object = s3_store.put_object(
        bucket=TRANSCRIPT_BUCKET,
        key=f"{session_id}/canonical_transcript.json",
        body=json.dumps(canonical_transcript,
                         default=str).encode("utf-8"),
        metadata={"session_id": session_id,
                   "visit_id":   session_context["visit_id"]})

    transcript_state.update(session_id, _to_decimal({
        "canonical_transcript_ref": transcript_object["uri"],
        "reconciliation_status":    "complete",
        "disagreement_count":       len(disagreements),
    }))

    visit_state.update(session_id, _to_decimal({
        "canonical_transcript_ref":  transcript_object["uri"],
        "avg_batch_asr_confidence":  avg_batch_confidence,
        "diarization_disagreement_count":
            len(disagreements),
    }))

    event_bus.put_events([{
        "Source":       "telehealth_stt",
        "DetailType":   "visit_transcribed",
        "EventBusName": VISIT_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":          session_id,
            "visit_id":            session_context["visit_id"],
            "disagreement_count":  len(disagreements),
            "avg_batch_confidence":
                float(avg_batch_confidence),
        }),
    }])

    audit_log({
        "event_type":         "TRANSCRIPT_RECONCILED",
        "session_id":         session_id,
        "disagreement_count": len(disagreements),
        "canonical_transcript_ref": transcript_object["uri"],
        "avg_batch_confidence":
            float(avg_batch_confidence),
        "timestamp":          _now_iso(),
    })

    return canonical_transcript
```

---

## Step 4: Generate the Structured Note Draft with Grounded Citations and Run Faithfulness Checks

*The pseudocode calls this `generate_note_draft(...)`. The canonical transcript is sent to a Bedrock-hosted LLM with a per-specialty prompt that produces a structured note draft. Each section of the generated note carries citations back to the supporting transcript segments. A separate faithfulness-check pass scores the generated content against the source transcript to detect hallucinated content, contradictions, or out-of-scope additions. Skip the faithfulness check and the LLM may produce fluent-sounding clinical content that the patient never actually said, which is the worst class of failure for this recipe.*

```python
def lookup_note_template(specialty, visit_type):
    """
    Select the per-specialty note template. Production
    maintains the templates as versioned clinical-informatics
    assets keyed by (specialty, visit_type). The demo uses a
    small fixed mapping.
    """
    if visit_type == "behavioral_health":
        return DEFAULT_TEMPLATES["behavioral-health-progress-v2"]
    if specialty == "cardiology":
        return DEFAULT_TEMPLATES["cardiology-followup-v1"]
    return DEFAULT_TEMPLATES["primary-care-soap-v3"]


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
    }
    for check in failed_checks or []:
        if check.get("type") in severe_check_types:
            return "block"
        if check.get("severity") == "severe":
            return "block"

    if score < FAITHFULNESS_PASS_THRESHOLD:
        return "flag"
    return "pass"


def run_faithfulness_check(session_context, generated_note,
                             transcript):
    """
    Verify that every claim in the generated note has a
    transcript citation, score the generated content for
    citation grounding, and detect contradictions or out-of-
    scope additions. Production runs this as a cascade of
    cheaper rule-based checks (citation presence, named-entity
    contradiction) followed by an LLM-judge pass for the
    harder cases. The demo collapses to a single LLM call.
    """
    session_id = session_context["session_id"]
    visit_id = session_context["visit_id"]

    response = bedrock_mock.check_faithfulness(
        visit_id=visit_id,
        generated_note=generated_note,
        transcript=transcript)

    body = json.loads(response["body"])
    score = Decimal(str(body.get("score", 0.0)))
    failed_checks = body.get("failed_checks", [])
    annotations = body.get("annotations", [])

    severity = determine_faithfulness_severity(
        failed_checks=failed_checks,
        score=score)

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


def generate_note_draft(session_context, canonical_transcript):
    """
    Generate the structured visit note from the canonical
    transcript. Each note section carries citations back to
    supporting transcript segments. The faithfulness check
    runs before the draft is persisted; severe failures block
    the draft and the clinician falls back to manual
    documentation.
    """
    session_id = session_context["session_id"]
    visit_id = session_context["visit_id"]

    # Step 4A: select the per-specialty template.
    template = lookup_note_template(
        specialty=session_context["clinician_specialty"],
        visit_type=session_context["visit_type"])

    # Step 4B: invoke the LLM through Bedrock with the
    # transcript and template structure. In production this is
    # bedrock_runtime.invoke_model with a JSON-schema response
    # format and the Guardrails configuration applied. The
    # mock returns a fixture response.
    note_response = bedrock_mock.generate_note(
        visit_id=visit_id,
        transcript=canonical_transcript,
        template=template,
        guardrail_id=TELEHEALTH_NOTE_GUARDRAIL_ID)

    note_body = json.loads(note_response["body"])
    generated_content = note_body.get("content", {})
    citations = note_body.get("citations", [])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "NoteGenerationInvocations",
        1, "Count",
        dimensions={
            "specialty":  session_context["clinician_specialty"],
            "template":   template["id"],
        })

    # Step 4C: faithfulness check. Verify that every claim in
    # the generated note has a transcript citation and that
    # the cited segment supports the claim.
    faithfulness_result = run_faithfulness_check(
        session_context=session_context,
        generated_note=generated_content,
        transcript=canonical_transcript)

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
                BEDROCK_NOTE_GENERATION_MODEL_ID,
            "prompt_version":
                NOTE_GENERATION_PROMPT_VERSION,
        }))
        return {"draft_available": False,
                "reason":          "faithfulness_block",
                "fallback":        "manual_documentation"}

    # Step 4D: persist the draft with citations and
    # faithfulness annotations.
    note_state.put(session_id, _to_decimal({
        "session_id":          session_id,
        "draft_available":     True,
        "draft_note":          generated_content,
        "citations":           citations,
        "template_id":         template["id"],
        "specialty":           session_context["clinician_specialty"],
        "faithfulness_score":  faithfulness_result["score"],
        "faithfulness_severity":
            faithfulness_result["severity"],
        "faithfulness_failed_checks":
            faithfulness_result["failed_checks"],
        "faithfulness_annotations":
            faithfulness_result["annotations"],
        "generated_at":        _now_iso(),
        "model_version":
            BEDROCK_NOTE_GENERATION_MODEL_ID,
        "prompt_version":
            NOTE_GENERATION_PROMPT_VERSION,
    }))

    event_bus.put_events([{
        "Source":       "telehealth_stt",
        "DetailType":   "note_generated",
        "EventBusName": VISIT_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":          session_id,
            "visit_id":            visit_id,
            "specialty":           session_context["clinician_specialty"],
            "faithfulness_score":
                float(faithfulness_result["score"]),
            "faithfulness_severity":
                faithfulness_result["severity"],
        }),
    }])

    audit_log({
        "event_type":          "NOTE_DRAFT_GENERATED",
        "session_id":          session_id,
        "specialty":           session_context["clinician_specialty"],
        "template_id":         template["id"],
        "faithfulness_score":
            float(faithfulness_result["score"]),
        "faithfulness_severity":
            faithfulness_result["severity"],
        "timestamp":           _now_iso(),
    })

    return {"draft_available": True,
            "draft_id":        session_id,
            "faithfulness_score":
                faithfulness_result["score"],
            "faithfulness_severity":
                faithfulness_result["severity"]}
```

---

## Step 5: Extract Structured Fields with Explicit Clinician Confirmation Gates

*The pseudocode calls this `extract_structured_fields(...)`. Beyond the narrative note, the system extracts structured clinical entities (medications, problems, allergies, vitals, orders) using Comprehend Medical for the entity detection and a Bedrock LLM for the higher-level structuring. Each extracted field is presented to the clinician for explicit confirmation before being applied to the structured chart. Skip the explicit confirmation and the structured chart can be silently modified with content the clinician would not have endorsed.*

```python
def lookup_speaker_role_for_offset(transcript, offset_seconds):
    """
    Find which speaker said the words at a given offset. Used
    for context-aware structured-field extraction (e.g., a
    medication mentioned by the patient describing their
    history is processed differently from a medication the
    clinician verbalizes as part of the plan).
    """
    for segment in transcript.get("segments", []):
        # The fixture timestamps are HH:MM:SS strings; normalize
        # to seconds for the comparison.
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
    Pull a small window of transcript text around an offset to
    show alongside the structured-field suggestion in the
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


def extract_structured_fields(session_context,
                                canonical_transcript):
    """
    Extract clinical entities (medications, conditions) using
    Comprehend Medical with RxNorm and ICD-10 coding, plus
    higher-level fields (orders, follow-up, allergies, vitals)
    using a Bedrock LLM. Persist all extractions for clinician
    confirmation; never apply them silently to the chart.
    """
    session_id = session_context["session_id"]
    visit_id = session_context["visit_id"]

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
        # The fixture entities include a synthetic offset
        # second; production reads BeginOffset and converts it
        # to a timestamp using the audio metadata.
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
    higher_level_response = bedrock_mock.extract_higher_level_fields(
        visit_id=visit_id,
        transcript=canonical_transcript)
    higher_level = json.loads(higher_level_response["body"])

    # Mark each higher-level extraction as pending confirmation.
    for category in ("orders_placed", "labs_requested",
                     "imaging_requested",
                     "follow_up_appointments",
                     "patient_reported_vitals",
                     "patient_reported_allergies"):
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
        + len(higher_level.get("patient_reported_allergies", [])))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "StructuredExtractionsGenerated",
        extraction_count, "Count",
        dimensions={
            "specialty":  session_context["clinician_specialty"],
            "language":   session_context["language"],
        })

    audit_log({
        "event_type":         "STRUCTURED_FIELDS_EXTRACTED",
        "session_id":         session_id,
        "medication_count":   len(coded_medications),
        "condition_count":    len(coded_conditions),
        "higher_level_count": (extraction_count
                                - len(coded_medications)
                                - len(coded_conditions)),
        "total_extractions":  extraction_count,
        "timestamp":          _now_iso(),
    })

    return {"extraction_count": extraction_count,
            "structured_extractions": structured_extractions}
```

---

## Step 6: Present the Draft to the Clinician for Review-and-Sign with Side-by-Side Transcript Display

*The pseudocode calls this `clinician_review_request(...)`, `clinician_save_review(...)`, and `clinician_sign(...)`. The clinician opens the review interface, sees the draft note alongside the transcript with click-through citations, reviews flagged uncertain segments, confirms each structured-field extraction explicitly, edits the narrative as needed, and signs the final note. Skip the side-by-side display and the clinician cannot easily verify what was actually said versus what the LLM produced, which undermines the faithfulness story.*

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


def clinician_review_request(session_context):
    """
    Assemble the side-by-side review payload for the clinician.
    The web UI uses this to render the draft note next to the
    transcript with click-through citations, confidence
    highlights, and structured-field confirmation gates.
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

    # If the draft was blocked by faithfulness checks, route
    # the clinician to manual documentation rather than
    # showing the unreliable draft.
    if not note_record.get("draft_available"):
        return {"available":         False,
                "reason":
                    note_record.get("block_reason",
                                     "draft_unavailable"),
                "fallback":           "manual_documentation",
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
    }

    audit_log({
        "event_type":      "CLINICIAN_REVIEW_OPENED",
        "session_id":      session_id,
        "faithfulness_severity":
            note_record.get("faithfulness_severity"),
        "extraction_count": (
            len(note_record.get("structured_extractions", {})
                .get("medications", []))
            + len(note_record.get("structured_extractions", {})
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

    # The review_actions dict carries per-extraction decisions
    # keyed by category and extraction text.
    decisions_by_key = {
        (d["category"], d["text"]): d
        for d in review_actions.get("structured_decisions", [])
    }

    for category in ("medications", "conditions",
                     "orders_placed", "labs_requested",
                     "imaging_requested",
                     "follow_up_appointments",
                     "patient_reported_vitals",
                     "patient_reported_allergies"):
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

    # Apply narrative edits. Production diff-tracks the edits;
    # the demo collapses to a final-text replacement.
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
            "specialty":  session_context["clinician_specialty"],
            "language":   session_context["language"],
        })
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ExtractionsRejected",
        len(rejected_extractions), "Count",
        dimensions={
            "specialty":  session_context["clinician_specialty"],
            "language":   session_context["language"],
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

    final_note = note_record.get("edited_note") \
                  or note_record.get("draft_note")
    confirmed = note_record.get("confirmed_extractions", [])

    signature = clinician_client.get_signature()
    signed_at = signature.get("timestamp", _now_iso())

    # Step 6C: write the signed note to the EHR's FHIR
    # DocumentReference resource. Production uses the EHR's
    # FHIR endpoint with SMART on FHIR authentication; the
    # mock just records the write.
    ehr_response = ehr.write_document_reference(
        patient_id=patient_id,
        encounter_id=session_context["visit_id"],
        document_content=final_note,
        author=session_context["clinician_id"],
        signed_at=signed_at)

    # Apply confirmed structured-field updates to the chart.
    # Each update is a FHIR resource write
    # (MedicationRequest, Condition, ServiceRequest, etc.).
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
                    "encounter_id": session_context["visit_id"],
                })
        elif category == "conditions":
            ehr.apply_structured_update(
                patient_id=patient_id,
                update_kind="problem",
                payload={
                    "text":         confirmed_item.get("text"),
                    "icd_10_code":
                        confirmed_item.get("icd_10_code"),
                    "encounter_id": session_context["visit_id"],
                })
        elif category in ("labs_requested", "imaging_requested"):
            ehr.apply_structured_update(
                patient_id=patient_id,
                update_kind="order",
                payload=confirmed_item)
        elif category == "follow_up_appointments":
            ehr.apply_structured_update(
                patient_id=patient_id,
                update_kind="follow_up",
                payload=confirmed_item)

    note_state.update(session_id, _to_decimal({
        "signed_note":          final_note,
        "signed_at":            signed_at,
        "signed_by":            session_context["clinician_id"],
        "ehr_document_id":
            ehr_response.get("document_id"),
        "signature":            signature,
        "status":               "signed",
    }))

    event_bus.put_events([{
        "Source":       "telehealth_stt",
        "DetailType":   "note_signed",
        "EventBusName": VISIT_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":          session_id,
            "visit_id":            session_context["visit_id"],
            "specialty":           session_context["clinician_specialty"],
            "ehr_document_id":
                ehr_response.get("document_id"),
            "duration_visit_to_sign_seconds":
                (datetime.fromisoformat(
                    signed_at.replace("Z", "+00:00"))
                 - datetime.fromisoformat(
                    session_context["started_at"]
                    .replace("Z", "+00:00"))).total_seconds(),
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "NotesSigned", 1, "Count",
        dimensions={
            "specialty":  session_context["clinician_specialty"],
            "language":   session_context["language"],
            "visit_type": session_context["visit_type"],
        })

    audit_log({
        "event_type":      "NOTE_SIGNED",
        "session_id":      session_id,
        "ehr_document_id": ehr_response.get("document_id"),
        "confirmed_extraction_count": len(confirmed),
        "timestamp":       signed_at,
    })

    return {"signed":          True,
            "ehr_document_id": ehr_response.get("document_id"),
            "signed_at":       signed_at,
            "confirmed_extraction_count": len(confirmed)}
```

---

## Step 7: Audit, Archive, and Feed Cohort-Stratified Accuracy Monitoring

*The pseudocode calls this `audit_archive_and_telemetry(...)`. Every visit produces a durable audit record: the streaming and batch transcripts, the generated draft, the clinician edits, the structured-field decisions, the final signed note, the consent and disclosure events. Cohort-stratified metrics (per-language, per-specialty, per-clinician, per-patient-cohort, per-audio-quality-band) feed the equity-monitoring dashboard. Skip the cohort segmentation and the system's per-cohort failure modes are invisible until a complaint or a regulator surfaces them.*

```python
def compute_edit_distance(draft_text, final_text):
    """
    Compute a simple character-level edit distance between the
    LLM draft and the clinician's signed note. Production uses
    a tokenized word-level distance; the demo uses Levenshtein
    on the JSON-serialized strings as a proxy.
    """
    if not draft_text or not final_text:
        return 0
    a = json.dumps(draft_text, default=str, sort_keys=True)
    b = json.dumps(final_text, default=str, sort_keys=True)
    # Tiny Levenshtein implementation for a self-contained
    # example. Real production uses a library (Levenshtein,
    # rapidfuzz) for performance and tokenization quality.
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


def audit_archive_and_telemetry(session_context,
                                  patient_age_band="not_disclosed"):
    """
    Write the durable audit record, emit the visit-audited
    lifecycle event, and emit per-cohort operational metrics.
    """
    session_id = session_context["session_id"]
    state = visit_state.get(session_id)
    note_record = note_state.get(session_id)
    transcript_record = transcript_state.get(session_id)

    # Audio quality band for cohort stratification (high,
    # medium, low, unknown). Production also emits this as a
    # CloudWatch metric dimension.
    quality_band = _bucket_audio_quality(
        state.get("per_channel_quality_metrics"))

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
                     / max(confirmed_count + rejected_count, 1))))

    audit_record = _to_decimal({
        "session_id":             session_id,
        "visit_id":               state.get("visit_id"),
        "clinician_id":           state.get("clinician_id"),
        "clinician_specialty":    state.get("clinician_specialty"),
        "patient_id_hash":        state.get("patient_id_hash"),
        "visit_type":             state.get("visit_type"),
        "language":               state.get("language"),
        "consent_regime":         state.get("consent_regime"),
        "feature_status":         state.get("feature_status"),
        "platform_type":          state.get("platform_type"),
        "per_channel_separated":
            state.get("audio_capture_config", {})
                  .get("per_channel_separated"),
        "audio_archive_ref":      state.get("audio_archive_ref"),
        "canonical_transcript_ref":
            state.get("canonical_transcript_ref"),
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
        "per_channel_audio_quality":
            state.get("per_channel_quality_metrics"),
        "avg_streaming_asr_confidence":
            state.get("avg_streaming_asr_confidence"),
        "avg_batch_asr_confidence":
            state.get("avg_batch_asr_confidence"),
        "diarization_disagreement_count":
            state.get("diarization_disagreement_count"),
        "streaming_batch_disagreement_count":
            transcript_record.get("disagreement_count"),
        # Versions of every artifact that influenced the visit.
        "streaming_asr_model_version":
            state.get("streaming_asr_model_version"),
        "batch_asr_model_version":
            state.get("batch_asr_model_version"),
        "note_generation_prompt_version":
            state.get("note_generation_prompt_version"),
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
            "specialty":          state.get("clinician_specialty"),
            "audio_quality_band": quality_band,
            "age_band":           patient_age_band,
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
            "visit_id":           state.get("visit_id"),
            "audio_quality_band": quality_band,
        })

    event_bus.put_events([{
        "Source":       "telehealth_stt",
        "DetailType":   "visit_audited",
        "EventBusName": VISIT_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":          session_id,
            "visit_id":            state.get("visit_id"),
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
        "specialty":          state.get("clinician_specialty"),
        "language":           state.get("language"),
        "visit_type":         state.get("visit_type"),
        "audio_quality_band": quality_band,
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
        "event_type":              "VISIT_AUDITED",
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

The pipeline ties together as a top-level handler that simulates a single end-to-end visit flowing through the seven stages. In a Lambda-and-Step-Functions deployment, the streaming-display stages run on the audio-stream-handler Lambda while the post-visit stages run as a Step Functions state machine; the demo orchestrates them inline so you can see the full sequence.

```python
def run_visit_pipeline(visit_id, patient_id, clinician_id,
                        clinician_specialty, patient_jurisdiction,
                        visit_type, platform_type="chime_sdk",
                        language="en-US",
                        institution_state="VA",
                        consent_acknowledged=True,
                        review_decisions=None,
                        note_edits=None,
                        patient_age_band="not_disclosed"):
    """
    Drive a single telehealth visit end-to-end through all
    seven pipeline stages. Production splits this across
    multiple Lambdas with Step Functions orchestration; the
    demo collapses to a single function for readability.
    """
    # Stage 1: visit start, consent, session bootstrap.
    session_context = visit_start(
        visit_id=visit_id,
        patient_id=patient_id,
        clinician_id=clinician_id,
        clinician_specialty=clinician_specialty,
        patient_jurisdiction=patient_jurisdiction,
        visit_type=visit_type,
        platform_type=platform_type,
        language=language,
        institution_state=institution_state,
        consent_acknowledged=consent_acknowledged)

    if not session_context.get("feature_enabled"):
        return {"feature_enabled": False,
                "reason": session_context.get("reason"),
                "consent_regime":
                    session_context.get("consent_regime")}

    # Stage 2: streaming ASR (during the visit).
    streaming_result = run_streaming_asr(session_context)

    # Persist the audio archive reference. Production has the
    # Chime SDK media-capture pipeline write the audio to
    # Kinesis Video Streams with KMS encryption; the demo
    # stamps a reference and proceeds.
    audio_archive_ref = (
        f"s3://{AUDIO_BUCKET}/{session_context['session_id']}/"
        f"audio.pcm")
    visit_state.update(session_context["session_id"], {
        "audio_archive_ref": audio_archive_ref,
    })

    # Stage 3: batch ASR + reconciliation (post-visit).
    batch_transcript = run_batch_transcription(
        session_context=session_context,
        audio_archive_ref=audio_archive_ref)
    canonical_transcript = reconcile_streaming_and_batch(
        session_context=session_context,
        batch_transcript=batch_transcript)

    # Stage 4: note draft + faithfulness.
    note_result = generate_note_draft(
        session_context=session_context,
        canonical_transcript=canonical_transcript)

    if not note_result["draft_available"]:
        # Faithfulness blocked the draft; the clinician falls
        # back to manual documentation. Still write the audit
        # record so the failure is visible to clinical
        # quality.
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
            "note_edits": note_edits,
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
        "extraction_count":        extraction_result["extraction_count"],
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
    through the telehealth speech-to-text pipeline:
      1. Carl (older primary-care patient) has a 18-minute
         telehealth visit with Dr. Okonkwo about new
         peripheral-neuropathy symptoms. The visit uses Chime
         SDK with per-channel separated audio. The note draft
         passes faithfulness checks; the clinician confirms
         the gabapentin and lab-order extractions and signs.
      2. Marisol (Spanish-speaking primary-care patient) has
         a follow-up visit with Dr. Vega via a third-party
         video platform with mixed audio. The diarization is
         lower-quality due to the mixed-channel constraint;
         the faithfulness check passes but flags one segment
         for review.
    """
    # pylint: disable=global-statement
    global transcribe_streaming, transcribe_batch_mock
    global bedrock_mock, comprehend_mock

    # Scenario 1 fixtures: Carl's visit with Dr. Okonkwo.
    visit_id_1 = "encounter-2026-05-23-0411"
    streaming_segments_1 = [
        {"speaker_role": "clinician",
         "timestamp":    "00:00:08",
         "text":
             "Hi Carl, good to see you. Before we get started, "
             "you should know our visit is being transcribed and "
             "added to your medical record. Is that okay with you?",
         "confidence":   Decimal("0.96")},
        {"speaker_role": "patient",
         "timestamp":    "00:00:18",
         "text":
             "Yeah that's fine, thanks for letting me know.",
         "confidence":   Decimal("0.94")},
        {"speaker_role": "patient",
         "timestamp":    "00:01:42",
         "text":
             "I've been having this tingling in my feet, mostly "
             "at night. It started maybe a couple months ago.",
         "confidence":   Decimal("0.91")},
        {"speaker_role": "family_member",
         "timestamp":    "00:01:58",
         "text":
             "He's also been kind of unsteady. Last week he "
             "caught his foot on the rug.",
         "confidence":   Decimal("0.88")},
        {"speaker_role": "clinician",
         "timestamp":    "00:11:02",
         "text":
             "I'm going to start you on gabapentin three "
             "hundred milligrams at bedtime, and we'll order "
             "an A1C and a B12.",
         "confidence":   Decimal("0.95")},
    ]
    batch_transcript_1 = {
        "session_id":    None,
        "visit_id":      visit_id_1,
        "duration_seconds": 1086,
        "diarization_quality": "high",
        "segments":      [
            {**seg,
             "speaker_uncertain": False}
            for seg in streaming_segments_1
        ],
    }
    note_response_1 = {
        "content": {
            "sections": {
                "subjective": {
                    "text":
                        "67-year-old male with type 2 diabetes "
                        "and hypertension presenting via "
                        "telehealth for follow-up. Reports new "
                        "bilateral foot tingling with onset "
                        "approximately 2 months ago. Patient's "
                        "wife reports episodes of unsteadiness.",
                },
                "assessment": {
                    "text":
                        "1. Bilateral peripheral neuropathy, "
                        "new onset, possible diabetic etiology. "
                        "2. Type 2 diabetes mellitus. "
                        "3. Hypertension, controlled.",
                },
                "plan": {
                    "text":
                        "1. Add gabapentin 300 mg PO at "
                        "bedtime. 2. Order HbA1c and vitamin "
                        "B12. 3. Follow-up in 6 weeks.",
                },
            },
        },
        "citations": [
            {"section": "subjective",
             "transcript_segment_timestamp": "00:01:42"},
            {"section": "subjective",
             "transcript_segment_timestamp": "00:01:58"},
            {"section": "plan",
             "transcript_segment_timestamp": "00:11:02"},
        ],
    }
    faithfulness_response_1 = {
        "score":         0.94,
        "failed_checks": [],
        "annotations":   [],
    }
    extraction_response_1 = {
        "orders_placed":           [],
        "labs_requested": [
            {"name": "HbA1c",      "loinc_code": "4548-4"},
            {"name": "Vitamin B12", "loinc_code": "2132-9"},
        ],
        "imaging_requested":       [],
        "follow_up_appointments": [
            {"interval_weeks": 6,
             "modality_options": ["telehealth", "in_person"]},
        ],
        "patient_reported_vitals": [],
        "patient_reported_allergies": [],
    }
    rx_norm_fixture = {
        "Entities": [
            {"Text": "gabapentin",
             "Score": 0.97,
             "OffsetSeconds": 662,
             "RxNormConcepts": [{"Code": "25480",
                                  "Description": "gabapentin"}]},
        ]
    }
    icd10_fixture = {
        "Entities": [
            {"Text": "peripheral neuropathy",
             "Score": 0.92,
             "OffsetSeconds": 102,
             "ICD10CMConcepts": [{"Code": "G62.9",
                                    "Description":
                                        "Polyneuropathy, "
                                        "unspecified"}]},
            {"Text": "type 2 diabetes",
             "Score": 0.96,
             "OffsetSeconds": 102,
             "ICD10CMConcepts": [{"Code": "E11.9",
                                    "Description":
                                        "Type 2 diabetes "
                                        "mellitus without "
                                        "complications"}]},
        ]
    }

    # Scenario 2 fixtures: Marisol's visit with Dr. Vega
    # (Spanish, third-party platform, mixed audio).
    visit_id_2 = "encounter-2026-05-23-0412"
    streaming_segments_2 = [
        {"speaker_role": "clinician",
         "timestamp":    "00:00:05",
         "text":
             "Hola senora Hernandez, gracias por unirse hoy.",
         "confidence":   Decimal("0.93")},
        {"speaker_role": "patient",
         "timestamp":    "00:00:14",
         "text":
             "Hola doctora, me he sentido bastante bien.",
         "confidence":   Decimal("0.84")},
        {"speaker_role": "patient",
         "timestamp":    "00:02:30",
         "text":
             "Pero la presion ha estado un poco alta esta "
             "semana.",
         "confidence":   Decimal("0.79")},
    ]
    batch_transcript_2 = {
        "session_id":    None,
        "visit_id":      visit_id_2,
        "duration_seconds": 612,
        "diarization_quality": "medium",
        "segments":      [
            {**seg,
             "speaker_uncertain":
                 seg["timestamp"] == "00:02:30"}
            for seg in streaming_segments_2
        ],
    }

    # Wire up the mocks.
    transcribe_streaming = MockTranscribeStreaming({
        visit_id_1: streaming_segments_1,
        visit_id_2: streaming_segments_2,
    })
    transcribe_batch_mock = MockTranscribeBatch({
        visit_id_1: batch_transcript_1,
        visit_id_2: batch_transcript_2,
    })
    bedrock_mock = MockBedrock(
        note_responses={visit_id_1: note_response_1,
                         visit_id_2: {"content":
                                       {"sections": {}},
                                       "citations": []}},
        faithfulness_responses={visit_id_1: faithfulness_response_1,
                                  visit_id_2:
                                      {"score": 0.91,
                                       "failed_checks": [],
                                       "annotations": [
                                           {"segment":
                                                "00:02:30",
                                            "note":
                                                "speaker uncertain"}]}},
        extraction_responses={visit_id_1: extraction_response_1,
                                visit_id_2:
                                    {"orders_placed": [],
                                     "labs_requested": [],
                                     "imaging_requested": [],
                                     "follow_up_appointments": [],
                                     "patient_reported_vitals": [],
                                     "patient_reported_allergies":
                                        []}})
    comprehend_mock = MockComprehendMedical({
        "infer_rx_norm":  rx_norm_fixture,
        "infer_icd10cm":  icd10_fixture,
        "detect_entities": {"Entities": []},
    })

    # Scenario 1: Carl's visit. Clinician confirms the
    # extracted medication and follow-up.
    print("\n=== Scenario 1: Carl with Dr. Okonkwo ===")
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
    result_1 = run_visit_pipeline(
        visit_id=visit_id_1,
        patient_id="pt-44219",
        clinician_id="clinician-okonkwo",
        clinician_specialty="family_medicine",
        patient_jurisdiction="VA",
        visit_type="primary_care",
        platform_type="chime_sdk",
        language="en-US",
        institution_state="VA",
        consent_acknowledged=True,
        review_decisions=review_decisions_1,
        patient_age_band="65_74")
    print(json.dumps(result_1, default=str, indent=2))

    # Scenario 2: Marisol's visit. The mixed-audio diarization
    # is lower quality; the clinician sees the speaker-
    # uncertainty flag in the review UI.
    print("\n=== Scenario 2: Marisol with Dr. Vega ===")
    result_2 = run_visit_pipeline(
        visit_id=visit_id_2,
        patient_id="pt-77310",
        clinician_id="clinician-vega",
        clinician_specialty="family_medicine",
        patient_jurisdiction="CA",
        visit_type="primary_care",
        platform_type="third_party_video",
        language="es-US",
        institution_state="VA",
        consent_acknowledged=True,
        review_decisions=[],
        patient_age_band="55_64")
    print(json.dumps(result_2, default=str, indent=2))


if __name__ == "__main__":
    run_demo()
```

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right audit records, but the distance between it and a real telehealth speech-to-text pipeline running in clinicians' workflows is significant. Here is where that distance lives.

**Real telehealth platform integration.** The demo treats the audio capture path as a configuration choice between Chime SDK and third-party video. Production integrates with a specific platform (Chime SDK, Zoom Healthcare, Teladoc Health, Doxy.me, Microsoft Teams Healthcare, or a vendor-bundled telehealth module from Epic or Cerner) with platform-specific authentication, platform-specific audio APIs, platform-specific recording-consent integration, and platform-specific session-lifecycle handling. For Chime SDK deployments, the integration uses the Amazon Chime SDK's media-capture pipelines that persist audio to Kinesis Video Streams; the per-participant audio streams are accessed through the meeting events API. For third-party platforms, the integration depth varies: some platforms expose per-participant WebRTC streams, some require SIPREC or platform-proprietary protocols, some only offer post-call recording APIs. Plan the platform integration as its own multi-week workstream after platform selection.

**Real Transcribe streaming wiring.** The demo mocks the streaming ASR. Production uses the standalone amazon-transcribe Python package (not the boto3 transcribe client, which is for batch and vocabulary management only): `client = TranscribeStreamingClient(region=REGION)` then `await client.start_stream_transcription(language_code=language, media_sample_rate_hz=audio_capture_config["sample_rate"], media_encoding=audio_capture_config["encoding"], vocabulary_name=INSTITUTIONAL_VOCABULARY, language_model_name=INSTITUTIONAL_LANGUAGE_MODEL, show_speaker_label=not per_channel, number_of_channels=1)`. Audio frames push through the resulting stream as they arrive from the platform; partial transcripts emit back to the client for the live display; the final transcript emits at end-of-utterance. For per-channel separated audio, two parallel streaming sessions run (one per channel) and the transcripts are merged by timestamp downstream.

**Real custom-vocabulary management.** The demo records the vocabulary name and proceeds. Production maintains custom vocabularies per institution (the formulary, provider list), per language (different vocabulary lists for each supported language), and optionally per specialty (specialty-specific term sets curated by clinical operations). Vocabularies are created via `transcribe_batch.create_vocabulary` and updated as terms are added. Custom language models, when used, are trained on institutional clinical text via `transcribe_batch.create_language_model`; training takes hours and the resulting model is referenced by name in the streaming and batch ASR configurations. The vocabulary-management service runs on its own cadence (daily or weekly updates), validates new entries against a held-out evaluation set, and warms vocabularies before sessions reference them.

**Real Bedrock invocation, prompt management, and inference profile.** The demo's MockBedrock uses fixture lookups. Production calls `bedrock_runtime.invoke_model` with `modelId=BEDROCK_NOTE_GENERATION_PROFILE_ARN` (the inference profile ARN is what you pass for cross-region inference and per-profile rate limits) and a versioned prompt that includes the per-specialty template, the institutional formatting conventions, explicit faithfulness instructions, and a strict-JSON output schema. The faithfulness checker uses a smaller, cheaper model (Claude 3 Haiku is appropriate); the note generator uses the larger, more capable model. Both prompts are versioned and deployed alongside the rest of the pipeline; prompt changes go through clinical-operations review (the prompts are load-bearing safety artifacts, not config strings).

**Real Bedrock Guardrails configuration.** The demo references a guardrail ID but does not invoke it. Production configures a Guardrails policy that filters clinical-advice and harmful-content categories, applies the guardrail at runtime via the `guardrailIdentifier` parameter on `invoke_model`, and surfaces guardrail-trigger events to the audit pipeline. Guardrails is a defense-in-depth layer; the system-prompt constraints in the note-generation prompt, the runtime faithfulness check, and the Guardrails filter all operate together.

**Real Comprehend Medical wiring.** The demo's MockComprehendMedical uses fixture lookups. Production calls `comprehend_medical.detect_entities_v2(Text=transcript)` for entity extraction, `comprehend_medical.infer_rx_norm(Text=transcript)` for medication coding, and `comprehend_medical.infer_icd10cm(Text=transcript)` for condition coding. The responses are merged on entity offsets to produce the suggestion list. Comprehend Medical occasionally misidentifies entities, misses negation ("denies chest pain" must not produce a chest-pain problem-list entry), or extracts dosages incorrectly; the suggestion-with-explicit-confirmation flow is what makes this safe to deploy.

**Per-Lambda IAM roles.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda (visit-start handler, audio-stream-handler, batch-reprocessing trigger, reconciliation worker, note-generation invoker, faithfulness-check runner, structured-field extractor, EHR write-back, audit writer, adaptation-feedback emitter), each scoped to the specific resource ARNs the Lambda touches. The note-generation role has scoped Bedrock invocation rights pinned to one model and one inference profile. The structured-field-extractor role has scoped Comprehend Medical inference rights only. The EHR-handoff role has scoped Secrets Manager read for the EHR credentials and write access only to the in-flight visit's note-state record. Wildcard actions and resources will fail any serious IAM review.

**Real DynamoDB wiring with KMS and PITR.** The mocks in the demo are dictionaries; production is DynamoDB tables (visit-state with TTL on idle sessions, transcript-state partitioned by session_id with global secondary indexes for visit-level queries, note-state partitioned by clinician_id with session_id sort key) with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery enabled, and DynamoDB Streams emitting change events to the audit and analytics consumers. The audit table has Streams feeding a Kinesis Firehose delivery stream that writes to S3 with Object Lock in compliance mode for HIPAA-grade durability.

**Customer-managed KMS keys, per data class.** Every PHI-bearing resource (audio bucket, transcript bucket, audit-archive bucket, visit-state table, transcript-state table, note-state table, Lambda environment variables, CloudWatch Logs, Secrets Manager) uses customer-managed KMS keys with rotation enabled. Different keys per data class for blast-radius containment: a compromised audio-bucket key does not compromise the audit archive. CloudTrail logs every key-usage event. The institutional KMS-key-management runbook specifies rotation cadence, access review cadence, and the cross-account key-grant pattern.

**S3 lifecycle and Object Lock.** The audio bucket has a brief-retention lifecycle (delete after seven to thirty days, per the privacy-officer-reviewed retention policy) with the option of opt-in longer retention with explicit consent. The transcript and note buckets retain for the medical-record retention. The audit archive uses Object Lock in compliance mode for HIPAA-grade durability with retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, and the institution's policy. Lifecycle transitions move older audit-archive objects to Glacier Deep Archive for cost optimization.

**VPC and VPC endpoints.** Lambdas that call the EHR API run in a VPC with private subnets that route traffic through a controlled egress path (PrivateLink to a cloud-hosted EHR, or a VPN/Direct Connect to an on-premises EHR system). VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, EventBridge, CloudWatch Logs, Bedrock, Comprehend Medical, and Transcribe keep AWS-internal traffic on the AWS backbone rather than traversing NAT and the public internet. Endpoint policies pin access to the specific resources the pipeline uses.

**Step Functions orchestration of the post-visit pipeline.** The demo orchestrates the post-visit stages inline. Production runs them as an AWS Step Functions state machine triggered by the `visit_end` event: batch reprocessing, reconciliation, note generation, faithfulness check, structured-field extraction, presentation to the clinician for review. Step Functions provides the durable retry semantics: if Bedrock throttles, retry with exponential backoff; if Comprehend Medical fails, route to a DLQ; if the EHR handoff fails, hold the signed note in a queue with manual replay capability. Each Lambda has its own IAM role, error handling, retries, and DLQs.

**Per-specialty template library with named clinical-informatics owners.** The demo's `DEFAULT_TEMPLATES` is a small fixed mapping. Production maintains per-specialty templates as versioned clinical-informatics assets owned by the institutional clinical-informatics or documentation-improvement team. Each specialty (primary care, behavioral health, cardiology, dermatology, neurology, others) has its own preferred SOAP, APSO, or specialty-specific structure; the templates capture the institutional preferences and drive the LLM prompt construction. Templates evolve over time based on clinician feedback; a maintenance cadence is required.

**Layered faithfulness program.** The demo's runtime faithfulness check is the first line of defense. Production additionally maintains a multi-layer program: rule-based grounding verification (every claim has a transcript citation), LLM-judge faithfulness scoring (flagged claims are reviewed by a separate model), clinical-rule-based contradiction detection (the note says X but the transcript implies not-X), and offline sampling review (clinical-quality team reviews a sample of generated notes against transcripts on a defined cadence). Owned by the clinical-quality officer, not the engineering team. Findings feed prompt and rule updates. Failed faithfulness checks are tracked as clinical-quality events.

**Faithfulness regression testing on prompt and model updates.** The note-generation LLM and the faithfulness-checker model are versioned components. Each model update or prompt update can change faithfulness behavior in subtle ways. Production maintains a regression test suite: a held-out set of representative transcripts with known good notes, automated faithfulness scoring on the regression set after every prompt or model change, manual review of the regression diffs before promoting changes to production. Promote changes through canary inference profiles with traffic shift, with rollback-on-regression triggers tied to the faithfulness regression metrics.

**Per-cohort accuracy and adoption monitoring with launch gates.** Per-cohort metrics (per-language, per-specialty, per-clinician, per-patient-cohort, per-audio-quality-band) are a launch gate, not a post-launch dashboard. Production defines cohort axes, per-cohort minimum sample sizes, per-cohort threshold metrics (WER, diarization error rate, faithfulness score, structured-extraction acceptance rate, edit distance, sustained adoption rate). Launch is gated on every cohort meeting the threshold, not on the institution-wide average. Disparity alerts trigger reviews; sustained disparity triggers product-level remediation including (potentially) disabling the feature for cohorts where it underperforms.

**Multi-state recording-consent compliance.** Telehealth visits frequently cross state lines. The demo's `determine_consent_regime` uses a tiny static table. Production builds the cross-jurisdiction handling explicitly: detect the patient's likely jurisdiction (the registered address, IP-based geolocation, or explicit confirmation at visit start), determine the more-restrictive applicable regime, play the appropriate disclosure. The all-party-consent state list is reviewed by the legal-and-compliance team on a defined cadence. Documented institutional policy covers ambiguous cases.

**Behavioral-health-specific privacy controls.** The demo flags `behavioral_health` visits with an explicit-acknowledgment disclosure but applies the same retention and access controls otherwise. Production builds a behavioral-health profile with stricter retention windows (often days rather than weeks), narrower access controls (only the treating clinician and authorized clinical staff), redacted handling for sensitive content categories, and explicit consent capture per institutional policy. Substance-use treatment records under 42 CFR Part 2 have specific consent and disclosure requirements that the engineering pipeline supports through the behavioral-health profile. Plan the behavioral-health profile as a distinct configuration with the privacy officer's review.

**Audio retention policy with privacy-officer review.** The demo retains audio in a mock S3 store with no lifecycle. Production deployment requires explicit privacy-officer review of the retention duration, the access controls on retained audio, the consent disclosure language, and the deletion verification. The default is conservative (a few days for QA review, then automatic deletion); longer retention requires explicit consent and an operational purpose. Telehealth audio captures the patient's home environment and bystanders; the data-minimization argument is stronger than for in-person ambient documentation.

**EHR integration depth and write-back validation.** The demo's MockEHR is a dictionary. Production handles the EHR vendor's specific FHIR write surface (DocumentReference for the clinical note, MedicationRequest for medication updates, Condition for problem-list updates, ServiceRequest for orders) plus vendor-specific extensions. Co-signature workflows for trainees (the resident drafts, the attending co-signs), late-addendum support (a separate signed document linked to the original; the original note is never modified), order-entry integration (a confirmed lab extraction drafts a CPOE order for separate clinician signature), and patient-portal release with institutionally-required hold periods are all production scope. The same explicit-confirmation rigor applies to every structured write.

**Disaster recovery and degraded-mode operation.** The demo assumes happy-path execution. Production tests the failure modes in staging quarterly: Transcribe streaming unavailable (fall back to batch-only with delayed transcript), Bedrock unavailable (fall back to manual documentation; the audit captures the failure), Comprehend Medical unavailable (skip structured-field extraction; surface the gap to the clinician), EHR API unreachable (hold the signed note in a queue with manual replay), telehealth-platform integration broken (fall back to manual documentation, never silently lose the visit). The clinician should never lose the visit because of a downstream component failure. Quarterly DR exercises validate the failover paths.

**Idempotency and retry semantics.** The demo's session-id is generated freshly each run. Production uses a conditional DynamoDB write keyed on `(visit_id, session_id)` so a duplicate visit-start event (network blip, double click) is rejected with `ConditionalCheckFailedException` rather than producing two sessions. The note write to the EHR uses an idempotency key derived from `(visit_id, session_id, signed_at)` so a retry of the EHR write does not produce two DocumentReference resources. Configure DLQs on every Lambda; alarm on DLQ depth.

**Performance under burst load.** Telehealth visit volume has strong diurnal and weekly patterns. Monday mornings spike. Behavioral-health practices have peak hours. The demo runs visits one at a time. Production holds the latency budget under burst: Transcribe streaming session quotas, Bedrock model invocation quotas, downstream EHR API rate limits all need provisioning headroom and burst-capacity planning. Reserve concurrency where the latency-sensitive Lambdas would otherwise be starved. Load test against realistic peak profiles before launch.

**Vendor evaluation rigor for build-vs-buy decisions.** Most institutions deploying telehealth speech-to-text should be buying a commercial product (commercial vendors, EHR-bundled offerings) rather than building one. The demo's pipeline is the architecture for the careful-custom-build path. The vendor evaluation program runs in parallel: per-cohort accuracy benchmarking against held-out audio, faithfulness evaluation, scope-containment evaluation, EHR integration depth, telehealth-platform integration depth, reference checks with comparable institutions. A custom build that cannot match the major commercial vendors on these axes is the wrong call.

**Audit log retention and legal hold.** The demo's audit-archive S3 bucket is created without Object Lock in the mock. Production enables Object Lock in compliance mode with retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, the EHR vendor's audit-retention floor, and the institutional regulatory floor. Legal hold capabilities (suspending deletion for specific clinicians or patients during litigation) are configurable.

**Cost monitoring per specialty and per cohort.** Different specialties have very different per-visit costs (a cardiology consult dictating a long assessment is structurally different from a primary-care follow-up). Per-specialty and per-cohort cost dashboards let operations identify outliers and tune accordingly.

**Telehealth-platform audio-quality monitoring.** The demo emits per-channel quality metrics from a fixture. Production extracts real signal-to-noise ratio, packet-loss-rate, codec-and-bitrate, and network-quality indicators from the platform's media events. Trends in patient-side audio quality over time identify systematic issues (a particular geographic region with consistent network problems, a particular device type with poor microphone capture) that drive remediation.

**Clinician training and adoption support.** Production includes a clinician adoption program: initial training (30-60 minutes per clinician on the review interface, the structured-extraction confirmation, and the in-visit correction affordances), ongoing office hours and support during the first month, per-clinician feedback collection, and per-clinician adaptation of the system over time. Adoption is not a feature flag; it is a workflow change-management program.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the consent-regime determination with edge cases (multi-state visits, behavioral-health profile selection), unit tests for the speaker-role mapping, unit tests for the reconciliation logic, unit tests for the faithfulness-severity classifier, integration tests against test buckets and tables, and end-to-end tests that simulate full visit flows including the faithfulness-block path, the per-channel-vs-mixed paths, and the multi-language paths. Never use real patient telehealth audio in test fixtures; voice samples are biometric and PHI-bearing data with non-trivial governance implications. Use synthetic Synthea patients and TTS-generated audio with known ground truth.

**Observability beyond the metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-stage investigation. Production runs CloudWatch Logs Insights queries that join across the audio-stream-handler logs, the batch-reconciliation logs, the note-generation logs, the faithfulness-check logs, the structured-field-extractor logs, and the EHR-handoff logs by session_id. AWS X-Ray traces show the latency contribution of each stage. When a single visit goes wrong (a faithfulness check fails, an EHR handoff stalls, a per-cohort disparity alert fires), the on-call engineer needs to reconstruct the full trace in seconds.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 10.6: Speech-to-Text for Telehealth Documentation](chapter10.06-speech-to-text-telehealth-documentation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
