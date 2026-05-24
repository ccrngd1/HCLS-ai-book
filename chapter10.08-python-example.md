# Recipe 10.8: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 10.8 (voice biomarker detection). It shows one way you could translate the pipeline into working Python using boto3 against Amazon SageMaker (per-indication model endpoints, with Asynchronous Inference for the longitudinal-monitoring path), Amazon Transcribe Medical (speech-to-text for linguistic-feature extraction in cognitive biomarkers), Amazon Comprehend Medical (clinical-entity extraction from spontaneous-speech samples), Amazon Bedrock (with Guardrails for clinician-facing and patient-facing communication packaging), AWS HealthLake (FHIR Observation write-back), AWS Lambda, AWS Step Functions, Amazon API Gateway, Amazon Cognito, Amazon DynamoDB, Amazon S3, AWS KMS, AWS Secrets Manager, Amazon EventBridge, Amazon CloudWatch, AWS CloudTrail, and Amazon Kinesis Data Firehose. The demo uses `MockSageMakerRuntime` standing in for the per-indication scoring endpoints, a `MockTranscribeMedical` standing in for the speech-to-text path used by linguistic-feature extraction, a `MockComprehendMedical` standing in for clinical-entity extraction from spontaneous-speech transcripts, a `MockBedrock` standing in for the clinician-summary LLM, a `MockHealthLake` standing in for the FHIR Observation write-back, and small helpers for the capture-session table, the trajectory table, the feature-vector S3 bucket, the audio S3 bucket, the audit S3 bucket, the EventBridge bus, and CloudWatch-style metrics. It is not production-ready. There is no real audio capture from a clinical device or smartphone app, no real Cognito authorizer, no real SageMaker invocation, no real Bedrock invocation, no real DynamoDB or S3 wiring, no Step Functions state machine, no IAM least-privilege role per Lambda, no KMS customer-managed key configuration, no VPC endpoints, no per-cohort accuracy disparity alerting, no biometric-data deletion-on-request workflow, no FDA SaMD post-market surveillance integration, no clinician-feedback capture loop, and no real EHR FHIR Observation write-back. Think of it as the sketchpad version: useful for understanding the shape of a voice-biomarker pipeline that respects the per-indication-validation discipline, the per-cohort-calibration discipline, the eligibility-checking discipline, the indeterminate-result discipline, the recording-chain-awareness discipline, the longitudinal-trajectory discipline, the biometric-data-governance discipline, and the post-market-surveillance discipline this recipe demands. It is not something you would deploy to clinicians on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the seven core pseudocode steps from the main recipe: capture the audio sample with the indication-specific protocol, real-time quality assessment, and explicit biometric-data consent (Step 1), extract acoustic and linguistic features with bandwidth and codec-aware processing (Step 2), check eligibility for each candidate biomarker model based on the validation envelope (Step 3), score the eligible biomarkers with per-cohort calibration and indeterminate handling (Step 4), compute longitudinal trajectory and package the clinical interpretation with Bedrock-rendered clinician summary (Step 5), deliver the result to the clinical workflow with explicit indeterminate handling and clinician override capture (Step 6), and audit, retain audio per consent, and feed cohort-stratified post-market surveillance (Step 7). The synthetic patients, providers, indications, scores, and trajectories in the demo are fictional; the names, MRNs, model versions, calibration versions, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also configure the audio capture path (a clinic-grade dedicated microphone with known frequency-response characteristics, a smartphone app with a controlled-protocol UX, a telehealth platform's audio path with bandwidth-aware feature handling, or a kiosk-based capture device for at-home longitudinal monitoring), per-indication SageMaker endpoints (one per validated indication, with multi-model endpoints when several related indications share an underlying feature pipeline), per-cohort calibration tables stored in DynamoDB or as JSON in S3, an Amazon Bedrock inference profile pinned to a specific summary-rendering model and region, an Amazon Bedrock Guardrails configuration that filters clinical-advice and harmful-content categories on patient-facing communications, the Lambda functions that orchestrate each pipeline stage (the capture-ingest handler, the feature-extraction Lambda, the eligibility-check Lambda, the scoring Lambda, the calibration Lambda, the packaging Lambda, the EHR write-back Lambda, the audit-and-surveillance Lambda), an AWS Step Functions state machine that durably orchestrates the multi-stage pipeline with retry semantics, DynamoDB tables that hold capture-session state, per-patient longitudinal trajectory, per-cohort calibration, and model-card metadata, AWS Secrets Manager secrets for the EHR API credentials and any external-vendor model-API credentials, an Amazon EventBridge bus for cross-system events (`sample_captured`, `features_extracted`, `scoring_completed`, `result_delivered`, `clinician_feedback_captured`, `session_audited`), Amazon S3 buckets for audio recordings (with brief-retention lifecycle bound to consent terms), feature vectors (with longer retention for surveillance and re-validation), and the long-term audit archive (with Object Lock in compliance mode), customer-managed KMS keys for every PHI-bearing and biometric-bearing data class, an AWS HealthLake datastore for FHIR Observation write-back, and Amazon CloudWatch dashboards plus SageMaker Model Monitor and Clarify jobs for the post-market surveillance program. The demo replaces all of these with small mocks so the focus stays on the per-stage processing logic rather than on the cloud-resource provisioning.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `sagemaker:InvokeEndpoint` and `sagemaker:InvokeEndpointAsync` for the per-indication scoring endpoints, scoped to the specific endpoint ARNs of validated models in production use
- `bedrock:InvokeModel` for the clinician-summary and patient-message generation models, scoped to the specific foundation-model ARNs and inference profiles in use
- `bedrock:ApplyGuardrail` for the runtime guardrails check on patient-facing communications
- `transcribe:StartTranscriptionJob`, `transcribe:GetTranscriptionJob` for the linguistic-feature path used in cognitive biomarkers (using Transcribe Medical when the speech is clinical content)
- `comprehendmedical:DetectEntitiesV2` for clinical-entity extraction from spontaneous-speech transcripts
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the capture-session, trajectory, calibration, and model-card tables
- `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on the audio bucket (with lifecycle-driven deletion the primary path), the feature-vector bucket, and the audit-archive bucket, scoped to the per-session key prefixes
- `secretsmanager:GetSecretValue` on the EHR-API credentials and external-vendor credential secrets pinned to the current rotation version
- `events:PutEvents` on the voice-biomarker EventBridge bus
- `cloudwatch:PutMetricData` for the operational metrics (per-stage latency, per-indication score distributions, per-cohort eligibility-pass rates, indeterminate-result rates, audio-quality scores, calibration drift indicators, clinician-feedback acceptance rates)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the audio bucket, the feature-vector bucket, the audit bucket, the DynamoDB tables, and the Secrets Manager secrets
- `states:StartExecution` for the Step Functions state machine that orchestrates the multi-stage scoring pipeline
- `healthlake:CreateResource`, `healthlake:UpdateResource` on the FHIR datastore for biomarker-Observation write-back

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The capture-ingest Lambda has scoped DynamoDB write for the capture-session table only and S3 write to the audio bucket only. The feature-extraction Lambda has scoped S3 read on the audio bucket and write on the feature bucket plus Transcribe and Comprehend Medical permissions. The eligibility-check Lambda has read-only access to the model-card and calibration tables. The scoring Lambda has SageMaker invoke-endpoint permissions for the validated-indication endpoints only. The packaging Lambda has DynamoDB write to the trajectory table, HealthLake create-resource on the FHIR datastore, Bedrock invoke-model on the summary-rendering model, and EventBridge publish. The EHR-handoff Lambda has Secrets Manager access for the EHR credentials and the EHR-specific egress only. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Voice samples are PHI and biometric.** A patient's voice can identify the patient independent of any other context. The privacy regime is the more restrictive of HIPAA, biometric-data law where applicable (Illinois BIPA, Texas, Washington and similar), and GDPR Article 9 special-category-data treatment for EU patients. Audio retention is a privacy-officer-reviewed decision, not a default. The architecture treats audio as PHI throughout: encrypted at rest with KMS customer-managed keys, encrypted in transit with TLS, retention bound by an explicit consent disclosure, BAAs in place for any vendor service that processes the audio, and a biometric-data-deletion-on-request workflow that handles audio, feature vectors, and longitudinal trajectory entries.
- **Per-indication validation is the architectural primitive, not an optimization.** The architecture supports multiple per-indication models, each with its own validation cohort, its own calibration, its own per-cohort threshold maps, its own indeterminate-result handling, and its own institutional approval status. Adding a new indication means adding a new validated model, not retraining an existing one to do more.
- **Eligibility checking precedes scoring.** Each per-indication model has a validation envelope: the demographic distributions, recording-chain conditions, and task-completion expectations the model was validated under. Out-of-envelope samples produce an "indication not assessable" result rather than a potentially-misleading score. This is a clinical-safety primitive.
- **Indeterminate is a first-class output.** A clinically-defensible voice biomarker frequently returns indeterminate results when the input quality is too low, the patient-specific confounds are too high, or the model's confidence is too low. Treating every score as actionable is a clinical-safety failure mode.
- **Per-cohort calibration with cohort-specific thresholds.** A single threshold across a heterogeneous population produces disparate sensitivity and specificity per cohort. Per-cohort calibration with explicit cohort disclosure on every result is the methodologically correct pattern.
- **Recording-chain awareness in the feature pipeline.** Bandwidth-aware feature selection (some features are not reliably measurable when the codec aggressively compresses high frequencies) is part of feature extraction, not a tuning step.
- **Longitudinal trajectory often beats single-sample scoring.** Many voice biomarkers are more reliable as change-detectors over a patient's own baseline than as single-point classifiers against a population baseline. The trajectory layer is what makes the system clinically useful for many indications.
- **Clinician feedback closes the surveillance loop.** When the clinician reviews a biomarker result and takes (or does not take) the institutionally-mapped action, that response is the ground-truth signal for the post-market surveillance dashboard. Without the feedback loop, the institution flies blind on per-cohort drift.
- **DynamoDB rejects Python `float`.** Every confidence score, calibrated score, threshold, and numeric metadata field passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses multiple Lambdas, the Step Functions orchestration, the EventBridge fan-out, and the CloudWatch metric emission into a single Python file for readability.** In production each pipeline stage is a separate Lambda with its own IAM role, error handling, retries, and DLQs, with Step Functions as the durable orchestrator for the multi-stage scoring flow. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the per-indication model cards, the per-cohort calibration tables, the eligibility envelopes, the consent disclosures, and the cohort axes are what you would change between environments.

```python
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights. The voice-biomarker pipeline
# operates on heavily PHI-bearing and biometric-bearing data:
# the audio is PHI and biometric, the feature vectors are
# derivative biometric data, the scores carry clinical
# implications, and every clinician-facing or patient-facing
# delivery is a clinical-record transaction. Log structural
# metadata only (session_id, indication, cohort, score band,
# clinical-action mapping), never raw audio references that
# could leak the underlying biometric content, never patient
# demographics, never specific score values that could enable
# re-identification.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from SageMaker, Bedrock,
# Transcribe Medical, Comprehend Medical, DynamoDB, S3,
# EventBridge, CloudWatch, HealthLake, and Secrets Manager.
# Voice biomarker scoring is typically not real-time-critical
# in the same way that ambient documentation is; a few seconds
# of latency is acceptable for synchronous in-encounter
# scoring, and the asynchronous longitudinal-monitoring path
# tolerates minutes of latency. Configure the retries
# accordingly so the synchronous path does not stall and the
# asynchronous path retries aggressively.
BOTO3_RETRY_CONFIG_REALTIME = Config(
    retries={"max_attempts": 3, "mode": "adaptive"})
BOTO3_RETRY_CONFIG_ASYNC = Config(
    retries={"max_attempts": 6, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in
# warm containers so each invocation does not pay the
# connection cost. The demo below uses Mock* classes instead;
# the real clients are never invoked here.
REGION = "us-east-1"
dynamodb           = boto3.resource("dynamodb", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
s3_client          = boto3.client("s3", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
sagemaker_runtime  = boto3.client("sagemaker-runtime",
                                       region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_REALTIME)
bedrock_runtime    = boto3.client("bedrock-runtime",
                                       region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
transcribe_client  = boto3.client("transcribe", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
comprehend_medical = boto3.client("comprehendmedical",
                                       region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
healthlake_client  = boto3.client("healthlake", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
eventbridge_client = boto3.client("events", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
cloudwatch_client  = boto3.client("cloudwatch", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
secrets_client     = boto3.client("secretsmanager",
                                       region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo
# prints what it would write rather than failing if the
# resources do not exist; see run_demo() at the bottom.
CAPTURE_SESSION_TABLE     = "voice-biomarker-capture-sessions"
TRAJECTORY_TABLE          = "voice-biomarker-patient-trajectory"
CALIBRATION_TABLE         = "voice-biomarker-cohort-calibration"
MODEL_CARD_TABLE          = "voice-biomarker-model-cards"
CLINICIAN_FEEDBACK_TABLE  = "voice-biomarker-clinician-feedback"
AUDIO_BUCKET              = "voice-biomarker-audio"
FEATURE_BUCKET            = "voice-biomarker-features"
AUDIT_ARCHIVE_BUCKET      = "voice-biomarker-audit-archive"
HEALTHLAKE_DATASTORE_ID   = "12345678abcdefgh1234567890abcdef"
BIOMARKER_EVENT_BUS_NAME  = "voice-biomarker-events-bus"
CLOUDWATCH_NAMESPACE      = "VoiceBiomarker"
INSTITUTION_ID            = "academic-medical-center-richmond"

# Bedrock configuration. In production, pin to a specific
# model version and inference profile so a model upgrade does
# not silently change clinician-summary behavior. The model
# and region combination must be in your AWS BAA scope.
BEDROCK_SUMMARY_MODEL_ID = (
    "anthropic.claude-3-5-sonnet-20240620-v1:0")
BEDROCK_SUMMARY_PROFILE_ARN = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "voice-biomarker-summary-v1")
BIOMARKER_GUARDRAIL_ID = "guardrail-biomarker-summary-v2"
BIOMARKER_GUARDRAIL_VERSION = "3"
PATIENT_MESSAGING_GUARDRAIL_ID = (
    "guardrail-biomarker-patient-messaging-v2")
PATIENT_MESSAGING_GUARDRAIL_VERSION = "2"

# Deploy-time guardrail. Any blank resource name is a deploy-
# time bug, not a runtime surprise.
for _name, _value in [
    ("CAPTURE_SESSION_TABLE",    CAPTURE_SESSION_TABLE),
    ("TRAJECTORY_TABLE",         TRAJECTORY_TABLE),
    ("CALIBRATION_TABLE",        CALIBRATION_TABLE),
    ("MODEL_CARD_TABLE",         MODEL_CARD_TABLE),
    ("AUDIO_BUCKET",             AUDIO_BUCKET),
    ("FEATURE_BUCKET",           FEATURE_BUCKET),
    ("AUDIT_ARCHIVE_BUCKET",     AUDIT_ARCHIVE_BUCKET),
    ("HEALTHLAKE_DATASTORE_ID",  HEALTHLAKE_DATASTORE_ID),
    ("BIOMARKER_EVENT_BUS_NAME", BIOMARKER_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",     CLOUDWATCH_NAMESPACE),
    ("BEDROCK_SUMMARY_MODEL_ID", BEDROCK_SUMMARY_MODEL_ID),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every captured sample carries the versions of the artifacts
# that influenced its scoring: per-indication model versions,
# per-indication calibration versions, the feature-pipeline
# version, the eligibility-rule version, the summary prompt
# version. A future audit reconstructs which configuration
# was active when a particular sample was scored.
FEATURE_PIPELINE_VERSION   = "feature-pipeline-2026-q1"
ELIGIBILITY_RULES_VERSION  = "eligibility-rules-v1.4"
SUMMARY_PROMPT_VERSION     = "summary-prompt-v2.0"

# --- Audio Quality Thresholds ---
# Per-segment quality must clear the institutional minimums
# before the segment enters the feature pipeline. Below these
# floors, the capture is rejected with a recapture prompt
# rather than producing low-confidence features.
MIN_SAMPLE_RATE_HZ          = 16000
MIN_SNR_DB                  = Decimal("15.0")
MAX_CLIPPING_PERCENT        = Decimal("1.0")
MIN_TASK_DURATION_SECONDS   = 5
MAX_TASK_RETRIES            = 2

# --- Indeterminate Threshold ---
# Calibrated confidence intervals wider than this threshold
# produce indeterminate results rather than confident-looking
# scores. The threshold is per-indication in production; the
# demo uses a single illustrative value.
DEFAULT_INDETERMINATE_INTERVAL_WIDTH = Decimal("0.20")

# --- Trajectory Configuration ---
# Minimum number of prior samples required before a trajectory
# baseline can be computed; below this, the system reports a
# single-point score without trajectory context.
MIN_SAMPLES_FOR_TRAJECTORY  = 3
TRAJECTORY_BASELINE_DAYS    = 730  # two-year window
TRAJECTORY_BASELINE_EXCLUDE_DAYS = 30

# --- Consent Disclosures ---
# Voice samples are biometric. The disclosure language differs
# by jurisdiction (Illinois BIPA, Texas, Washington each have
# specific requirements) and by indication (research-track
# protocols carry different terms than clinical-track
# protocols). Production looks up the patient's jurisdiction
# and the indication-specific protocol terms; the demo uses
# illustrative defaults.
CONSENT_DISCLOSURE_DEFAULT = (
    "We are collecting a brief voice sample to help support "
    "your care. Your voice is biometric data and will be "
    "handled with the same protections as your other health "
    "information. The sample will be deleted after analysis "
    "unless you give specific permission for longer "
    "retention. You can withdraw your consent at any time.")
CONSENT_DISCLOSURE_BIPA = (
    "Under Illinois law, we are specifically informing you "
    "that your voice is biometric data. We are collecting it "
    "for the clinical purpose described in your protocol. "
    "We will retain it only for the period stated in your "
    "consent. You can request deletion at any time. By "
    "continuing, you give written consent to this collection.")
CONSENT_DISCLOSURE_RESEARCH = (
    "This voice sample will be used in a research study. "
    "Your participation is voluntary. Your data will be "
    "stored and analyzed under the IRB-approved protocol. "
    "You can withdraw at any time without affecting your "
    "clinical care.")

# Jurisdictions with biometric-data laws requiring specific
# disclosure language. The list is approximate and changes
# over time as state law evolves; production maintains this
# in a legal-team-reviewed configuration with an explicit
# update cadence.
# TODO (TechWriter): verify the current biometric-data-law
# state list against the IAPP biometric-privacy tracker
# before deploying.
BIOMETRIC_DATA_LAW_STATES = {"IL", "TX", "WA"}

# --- Cohort Axes ---
# Stratification axes for per-cohort calibration and post-
# market surveillance. Production cohort definitions are
# per-indication and per-validation-study; the demo uses a
# small illustrative set.
COHORT_AXES = ["age_band", "sex", "language",
               "device_class", "recording_environment"]

# --- Per-Indication Model Cards ---
# Each model card defines the validation envelope, the
# per-cohort calibration references, the indeterminate
# threshold, the inference mode (real-time vs. asynchronous),
# and the SageMaker endpoint configuration for one validated
# indication. Production maintains these as DynamoDB items
# with a deploy-time validation that the SageMaker endpoint
# referenced is actually live and that the calibration entry
# referenced exists. The demo uses an in-memory dict.
MODEL_CARDS = {
    "parkinsons_screening": {
        "indication":            "parkinsons_screening",
        "model_version":         "parkinsons_v3.2.1",
        "sagemaker_endpoint":
            "voice-biomarker-parkinsons-v3-2-1",
        "inference_mode":        "real_time",
        "required_tasks":        ["sustained_vowel",
                                  "read_passage"],
        "min_per_task_quality":  Decimal("0.7"),
        "validation_demographics": {
            "age_band": ["55_64", "65_74", "75_84"],
            "sex":      ["male", "female"],
            "language": ["en-US"],
        },
        "validation_recording_envelope": {
            "device_class": ["clinic_dedicated_microphone",
                             "smartphone_high_grade",
                             "telehealth_video"],
            "min_codec_bandwidth_hz": 8000,
        },
        "indeterminate_threshold":
            Decimal("0.18"),
        "calibration_versions": {
            "55-64_male_english_clinic_recording":
                "calibration_v3.2.1_20260301",
            "65-74_male_english_clinic_recording":
                "calibration_v3.2.1_20260301",
            "75-84_male_english_clinic_recording":
                "calibration_v3.2.1_20260301",
            "55-64_female_english_clinic_recording":
                "calibration_v3.2.1_20260301",
            "65-74_female_english_clinic_recording":
                "calibration_v3.2.1_20260301",
            "75-84_female_english_clinic_recording":
                "calibration_v3.2.1_20260301",
        },
        "confounds_to_flag": [
            "recent_respiratory_infection",
            "recent_dental_procedure",
            "acute_voice_use_high",
        ],
        "embedding_model_id":    "wavlm-base-plus-2024",
        "feature_set":           "engineered_plus_embedding",
    },
    "respiratory_monitoring": {
        "indication":            "respiratory_monitoring",
        "model_version":         "cough_classifier_v2.1.0",
        "sagemaker_endpoint":
            "voice-biomarker-cough-v2-1-0",
        "inference_mode":        "real_time",
        "required_tasks":        ["voluntary_cough"],
        "min_per_task_quality":  Decimal("0.65"),
        "validation_demographics": {
            "age_band": ["18_44", "45_64", "65_84"],
            "sex":      ["male", "female"],
            "language": ["en-US", "es-US"],
        },
        "validation_recording_envelope": {
            "device_class": ["smartphone_standard",
                             "smartphone_high_grade",
                             "clinic_dedicated_microphone"],
            "min_codec_bandwidth_hz": 4000,
        },
        "indeterminate_threshold":
            Decimal("0.15"),
        "calibration_versions": {
            "default_cohort": "calibration_v2.1.0_20260201",
        },
        "confounds_to_flag":     [],
        "embedding_model_id":    None,
        "feature_set":           "engineered_only",
    },
}

# --- Per-Cohort Calibration Lookup ---
# Production stores calibration curves and threshold maps in
# DynamoDB keyed on (indication, cohort, calibration_version).
# The demo uses an in-memory dict with one entry per cohort.
CALIBRATION_LOOKUP = {
    ("parkinsons_screening",
     "65-74_male_english_clinic_recording",
     "calibration_v3.2.1_20260301"): {
        "curve":      "platt_scaling",
        "intercept":  Decimal("-0.42"),
        "slope":      Decimal("1.18"),
        "thresholds": {
            "low_signal":      Decimal("0.30"),
            "elevated_signal": Decimal("0.55"),
            "high_signal":     Decimal("0.75"),
        },
        "cohort_size":            1842,
        "calibration_uncertainty": Decimal("0.04"),
        "version":                "calibration_v3.2.1_20260301",
    },
    ("respiratory_monitoring",
     "default_cohort",
     "calibration_v2.1.0_20260201"): {
        "curve":      "isotonic",
        "knot_points": [
            {"raw": Decimal("0.10"),
             "calibrated": Decimal("0.08")},
            {"raw": Decimal("0.50"),
             "calibrated": Decimal("0.45")},
            {"raw": Decimal("0.90"),
             "calibrated": Decimal("0.92")},
        ],
        "thresholds": {
            "non_productive_dry":   Decimal("0.30"),
            "productive_wet":       Decimal("0.55"),
            "asthma_pattern":       Decimal("0.70"),
            "uri_pattern":          Decimal("0.75"),
        },
        "cohort_size":            4521,
        "calibration_uncertainty": Decimal("0.05"),
        "version":                "calibration_v2.1.0_20260201",
    },
}

# --- Clinical-Action Mapping ---
# Per-indication, per-category mapping of biomarker output to
# clinical action. Owned by clinical-quality leadership in
# production; the demo uses an illustrative mapping.
CLINICAL_ACTION_MAP = {
    "parkinsons_screening": {
        "low_signal":         "longitudinal_only",
        "elevated_signal":    "clinician_review",
        "high_signal":        "clinician_review",
        "trajectory_change":  "clinician_review",
    },
    "respiratory_monitoring": {
        "non_productive_dry": "longitudinal_only",
        "productive_wet":     "clinician_review",
        "asthma_pattern":     "clinician_review",
        "uri_pattern":        "patient_communication",
    },
}

# --- Per-Indication Capture Protocols ---
# Each protocol defines the tasks the speaker performs, the
# expected duration per task, the per-task quality gates, the
# retention terms, and the consent requirements. Production
# maintains these as versioned clinical-research assets owned
# by the clinical operations team; the demo uses a small
# illustrative subset.
CAPTURE_PROTOCOLS = {
    "parkinsons_screening_v1": {
        "indication":   "parkinsons_screening",
        "version":      "parkinsons_screening_v1",
        "tasks": [
            {"task_id":           "sustained_vowel_a",
             "prompt_text":
                 "Take a deep breath, then say 'ah' for as "
                 "long as you can.",
             "min_duration_seconds": 5,
             "max_duration_seconds": 20,
             "minimum_quality":      Decimal("0.7"),
             "quality_thresholds": {
                 "min_snr_db":         Decimal("15.0"),
                 "max_clipping_percent": Decimal("1.0"),
             },
             "max_retries":           2,
             "required":              True},
            {"task_id":           "read_passage",
             "prompt_text":
                 "Please read the passage shown on the "
                 "screen at your normal speaking pace.",
             "min_duration_seconds": 20,
             "max_duration_seconds": 60,
             "minimum_quality":      Decimal("0.7"),
             "quality_thresholds": {
                 "min_snr_db":         Decimal("15.0"),
                 "max_clipping_percent": Decimal("1.0"),
             },
             "max_retries":           1,
             "required":              True},
        ],
        "retention": {
            "audio_hours":           48,
            "feature_vector_days":   730,
            "score_retention_days":  3650,
        },
        "requires_explicit_consent": True,
        "disclosures":               ["clinical_workflow"],
        "language":                  "en-US",
    },
    "respiratory_monitoring_v1": {
        "indication":   "respiratory_monitoring",
        "version":      "respiratory_monitoring_v1",
        "tasks": [
            {"task_id":           "voluntary_cough",
             "prompt_text":
                 "When you are ready, please cough three "
                 "times into the microphone.",
             "min_duration_seconds": 3,
             "max_duration_seconds": 15,
             "minimum_quality":      Decimal("0.65"),
             "quality_thresholds": {
                 "min_snr_db":         Decimal("12.0"),
                 "max_clipping_percent": Decimal("2.0"),
             },
             "max_retries":           2,
             "required":              True},
        ],
        "retention": {
            "audio_hours":           24,
            "feature_vector_days":   365,
            "score_retention_days":  1825,
        },
        "requires_explicit_consent": True,
        "disclosures":               ["clinical_workflow"],
        "language":                  "en-US",
    },
}


# --- Helpers ---
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


def _bucket_age(age):
    """Translate a numeric age into the cohort age band."""
    if age is None:
        return "not_disclosed"
    if age < 18:    return "under_18"
    if age < 45:    return "18_44"
    if age < 55:    return "45_54"
    if age < 65:    return "55_64"
    if age < 75:    return "65_74"
    if age < 85:    return "75_84"
    return "85_plus"


def _select_consent_disclosure(jurisdiction, indication_type):
    """Pick the disclosure language for the patient's
    jurisdiction and the indication's clinical vs. research
    context."""
    if indication_type == "research":
        return CONSENT_DISCLOSURE_RESEARCH
    if jurisdiction in BIOMETRIC_DATA_LAW_STATES:
        return CONSENT_DISCLOSURE_BIPA
    return CONSENT_DISCLOSURE_DEFAULT


def audit_log(event):
    """
    Sanitized audit print so you can see the sequence of
    decisions without leaking the underlying values.
    Production routes events to CloudWatch Logs Insights with
    structured JSON; ship to a SIEM if available. Voice
    samples are biometric data; never include the audio
    reference itself in routine audit logs.
    """
    safe_event = {k: v for k, v in event.items()
                  if k not in {"audio_ref",
                                "patient_demographics",
                                "raw_features"}}
    if "audio_ref" in event:
        safe_event["audio_ref_hash"] = _hash_value(
            event["audio_ref"])
    logger.info("AUDIT %s",
                  json.dumps(safe_event, default=str))
```

---

## Mock Resources for the Demo

These mocks stand in for the production AWS resources and back-office systems. They are deliberately simple and are not how you would build the real thing. Their purpose is to keep the focus on the voice-biomarker pipeline logic.

```python
class MockSageMakerRuntime:
    """
    Stands in for the per-indication SageMaker endpoint
    invocations. In production, each validated indication is
    hosted as its own SageMaker endpoint (or as one model
    behind a multi-model endpoint), with real-time invocation
    for in-encounter scoring and asynchronous invocation for
    longitudinal-monitoring batches. The mock returns canned
    raw scores per (indication, session_id) pair.
    """
    def __init__(self, score_fixtures):
        self._fixtures = score_fixtures
        self.invocations = []

    def invoke_endpoint(self, endpoint_name, body,
                          content_type="application/json"):
        # Production: sagemaker_runtime.invoke_endpoint(
        #     EndpointName=endpoint_name,
        #     ContentType=content_type,
        #     Body=body)
        # The body is the model-specific JSON request shape
        # (typically a feature vector plus metadata); the
        # response includes the raw model output and any
        # explanation features the model exposes.
        request = json.loads(body) if isinstance(body, str) else body
        self.invocations.append({
            "endpoint":     endpoint_name,
            "session_id":   request.get("session_id"),
            "indication":   request.get("indication"),
            "mode":         "real_time",
        })
        key = (request.get("indication"),
                request.get("session_id"))
        response = self._fixtures.get(key, {
            "raw_score":    Decimal("0.50"),
            "feature_attribution": {
                "top_features": [],
            },
            "model_version": "unknown",
        })
        return {"body": json.dumps(response, default=str)}

    def invoke_endpoint_async(self, endpoint_name,
                                input_location):
        # Production:
        #   sagemaker_runtime.invoke_endpoint_async(
        #     EndpointName=endpoint_name,
        #     InputLocation=input_location)
        # The async call returns immediately with an output-
        # location S3 URI; production polls that URI until the
        # output is available. The mock collapses to a single
        # synchronous call returning the same fixture.
        self.invocations.append({
            "endpoint":         endpoint_name,
            "input_location":   input_location,
            "mode":             "async",
        })
        # Pull the indication and session_id from the input
        # location's path convention (the demo's mock writer
        # uses session_id and indication in the path).
        parts = input_location.split("/")
        session_id = parts[-2] if len(parts) >= 2 else None
        indication = parts[-1].replace(".json", "") \
                       if parts else None
        return {
            "OutputLocation":
                f"s3://{FEATURE_BUCKET}/async/"
                f"{session_id}/{indication}.json",
            "_fixture_key": (indication, session_id),
        }

    def retrieve_async_output(self, output_location,
                                 fixture_key):
        # Production reads the output S3 object once it is
        # available; the mock returns the same fixture lookup.
        response = self._fixtures.get(fixture_key, {
            "raw_score":    Decimal("0.50"),
            "feature_attribution": {"top_features": []},
            "model_version": "unknown",
        })
        return {"body": json.dumps(response, default=str)}


class MockTranscribeMedical:
    """
    Stands in for the Transcribe Medical batch transcription
    used by linguistic-feature pipelines (cognitive-decline
    biomarkers and other indications that consume transcribed
    spontaneous-speech samples). In production, this is
    `transcribe_client.start_medical_transcription_job` plus
    polling for job completion. The mock returns canned
    transcripts keyed by audio_ref.
    """
    def __init__(self, transcript_fixtures):
        self._fixtures = transcript_fixtures
        self.jobs_started = []

    def start_medical_transcription(self, job_name, audio_uri,
                                       language,
                                       specialty="PRIMARYCARE"):
        self.jobs_started.append({
            "job_name":   job_name,
            "audio_uri":  audio_uri,
            "language":   language,
            "specialty":  specialty,
            "started_at": _now_iso(),
        })
        return {"MedicalTranscriptionJobName": job_name,
                "TranscriptionJobStatus":      "COMPLETED"}

    def retrieve_transcript(self, audio_uri):
        return self._fixtures.get(audio_uri, "")


class MockComprehendMedical:
    """
    Stands in for Comprehend Medical's DetectEntitiesV2,
    used to extract clinical entities from spontaneous-speech
    transcripts. The biomarker pipeline uses the entities as
    features for some indications and to surface
    incidentally-mentioned clinical content (for example, a
    patient describing chest pain in a spontaneous-speech
    sample) for clinical follow-up regardless of the
    biomarker output.
    """
    def __init__(self, entity_fixtures):
        self._fixtures = entity_fixtures
        self.invocations = []

    def detect_entities_v2(self, text):
        # Real boto3: comprehend_medical.detect_entities_v2(Text=text).
        # The capitalized Text= keyword on the production
        # client; the demo uses lowercase text= for Pythonic
        # readability. detect_entities (without _v2) is
        # deprecated; new integrations should use _v2.
        self.invocations.append({"type":     "detect_entities_v2",
                                  "text_len": len(text)})
        return self._fixtures.get(text,
                                    {"Entities": []})


class MockBedrock:
    """
    Stands in for Amazon Bedrock's InvokeModel for clinician-
    facing summary generation and patient-facing message
    generation. In production this is bedrock_runtime.
    invoke_model with the structured biomarker output, the
    cohort context, the trajectory, and the institutional
    template as the prompt context. Guardrails are applied
    at runtime for the patient-facing generation.
    """
    def __init__(self, summary_responses):
        self._summary_responses = summary_responses
        self.invocations = []

    def render_clinician_summary(self, session_id, indication,
                                    score, trajectory,
                                    clinical_action,
                                    guardrail_id):
        self.invocations.append({
            "type":          "clinician_summary",
            "session_id":    session_id,
            "indication":    indication,
            "guardrail_id":  guardrail_id,
        })
        response = self._summary_responses.get(
            (session_id, indication), {
                "content":
                    "Voice biomarker result available. "
                    "This is decision support, not a "
                    "diagnosis. Please review the "
                    "supporting features and the trajectory "
                    "context.",
                "guardrail_action": "NONE",
            })
        return {"body": json.dumps(response, default=str)}

    def render_patient_message(self, session_id, indication,
                                  interpretation,
                                  guardrail_id):
        self.invocations.append({
            "type":          "patient_message",
            "session_id":    session_id,
            "indication":    indication,
            "guardrail_id":  guardrail_id,
        })
        return {"body": json.dumps({
            "content":
                "Thank you for completing your voice check. "
                "Your care team will review the result and "
                "be in touch if any follow-up is needed.",
            "guardrail_action": "NONE",
        }, default=str)}


class MockHealthLake:
    """
    Stands in for AWS HealthLake's FHIR Observation write
    surface. In production this is healthlake_client.
    create_resource(DatastoreId=..., ResourceType=
    'Observation', Resource=...). The mock just records the
    write.
    """
    def __init__(self):
        self.observations_written = []

    def create_observation(self, datastore_id, observation):
        observation_id = f"obs-{uuid.uuid4().hex[:10]}"
        self.observations_written.append({
            "observation_id": observation_id,
            "datastore_id":   datastore_id,
            "observation":    dict(observation),
        })
        return {"resource_id": observation_id}


class MockEHRDecisionSupport:
    """
    Stands in for the EHR's clinical-decision-support alert
    surface. Production uses the EHR vendor's CDS-Hooks or
    proprietary alerting API; the mock just records the alert.
    """
    def __init__(self):
        self.alerts = []

    def create_alert(self, patient_id_hash, indication,
                       interpretation, priority):
        alert_id = f"alert-{uuid.uuid4().hex[:10]}"
        self.alerts.append({
            "alert_id":         alert_id,
            "patient_id_hash":  patient_id_hash,
            "indication":       indication,
            "priority":         priority,
            "interpretation":
                {k: v for k, v in interpretation.items()
                 if k != "score"},  # never include raw score in alert
            "created_at":       _now_iso(),
        })
        return {"alert_id": alert_id}


class MockPatientCommunication:
    """
    Stands in for the patient-communication system (patient
    portal message, SMS, email). Production routes through
    the institutional communication-preference service with
    appropriate channel selection.
    """
    def __init__(self):
        self.messages = []

    def send(self, patient_id_hash, message, channel):
        self.messages.append({
            "patient_id_hash": patient_id_hash,
            "message":         message,
            "channel":         channel,
            "sent_at":         _now_iso(),
        })


class MockCaptureSessionTable:
    """In-memory stand-in for the DynamoDB capture-session
    table. Each entry tracks one voice-biomarker session
    through the seven pipeline stages."""
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


class MockTrajectoryTable:
    """In-memory stand-in for the DynamoDB trajectory table.
    Per-patient longitudinal series of biomarker scores; in
    production a global secondary index on indication
    supports cohort-level queries."""
    def __init__(self):
        self._items = []

    def put(self, item):
        self._items.append(dict(item))

    def get_history(self, patient_id_hash, indication,
                      window_days):
        cutoff = (datetime.now(timezone.utc)
                    - timedelta(days=window_days)).isoformat()
        return [item for item in self._items
                if item.get("patient_id_hash") ==
                   patient_id_hash
                and item.get("indication") == indication
                and item.get("sample_timestamp", "") >= cutoff]


class MockClinicianFeedbackTable:
    """In-memory stand-in for the clinician-feedback table.
    Captures the clinician's response to a delivered
    biomarker result; the feedback is the ground-truth signal
    for post-market surveillance."""
    def __init__(self):
        self._items = []

    def put(self, item):
        self._items.append(dict(item))


class MockS3:
    """
    Stands in for S3 audio storage, feature-vector storage,
    and audit archive. Holds objects in memory keyed by
    (bucket, key). Production uses customer-managed KMS keys
    for encryption and lifecycle policies for retention.
    """
    def __init__(self):
        self._objects = {}
        self.deletion_log = []

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

    def delete_object(self, bucket, key, reason="lifecycle"):
        if (bucket, key) in self._objects:
            del self._objects[(bucket, key)]
        self.deletion_log.append({
            "bucket":     bucket,
            "key":        key,
            "reason":     reason,
            "deleted_at": _now_iso(),
        })


class MockEventBus:
    """Stands in for Amazon EventBridge. Lifecycle events
    flow here for cross-system fan-out: sample_captured,
    features_extracted, scoring_completed, result_delivered,
    clinician_feedback_captured, session_audited."""
    def __init__(self):
        self.events = []

    def put_events(self, entries):
        for entry in entries:
            self.events.append(dict(entry))


class MockCloudWatch:
    """Stands in for CloudWatch metric emission. In
    production the metrics flow into dashboards and alarms,
    with SageMaker Model Monitor and Clarify producing
    additional per-cohort surveillance reports on a scheduled
    cadence."""
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
capture_session_table = MockCaptureSessionTable()
trajectory_table      = MockTrajectoryTable()
clinician_feedback_table = MockClinicianFeedbackTable()
s3_store              = MockS3()
event_bus             = MockEventBus()
cloudwatch            = MockCloudWatch()
healthlake            = MockHealthLake()
ehr_cds               = MockEHRDecisionSupport()
patient_comm          = MockPatientCommunication()
# sagemaker_mock, transcribe_mock, comprehend_mock, and
# bedrock_mock are wired up in run_demo() with fixture data
# tailored to each scenario.
sagemaker_mock        = None
transcribe_mock       = None
comprehend_mock       = None
bedrock_mock          = None


# --- Patient demographics lookup ---
# Production reads from the EHR via FHIR; the demo uses an
# in-memory map keyed by patient_id (NOT the patient_id_hash,
# because demographics are looked up from the unhashed ID and
# converted to the cohort representation that gets persisted
# alongside the score).
PATIENT_DEMOGRAPHICS = {
    "pt-44219": {
        "age":               68,
        "sex":               "male",
        "primary_language":  "en-US",
        "jurisdiction":      "VA",
    },
    "pt-77310": {
        "age":               58,
        "sex":               "male",
        "primary_language":  "es-US",
        "jurisdiction":      "VA",
    },
    "pt-22018": {
        "age":               42,
        "sex":               "female",
        "primary_language":  "en-US",
        "jurisdiction":      "IL",
    },
}


def lookup_patient_demographics(patient_id):
    return dict(PATIENT_DEMOGRAPHICS.get(patient_id, {}))


def lookup_patient_jurisdiction(patient_id):
    return PATIENT_DEMOGRAPHICS.get(
        patient_id, {}).get("jurisdiction", "unknown")


def lookup_patient_language(patient_id):
    return PATIENT_DEMOGRAPHICS.get(
        patient_id, {}).get("primary_language", "en-US")


def lookup_recent_clinical_events(patient_id_hash,
                                     window_days=30):
    """
    Look up recent clinical events that may flag confounds
    for the biomarker scoring (recent respiratory infection,
    recent dental procedure, acute medication change, recent
    voice-rest order). Production reads from the EHR; the
    demo returns a small synthetic set keyed off an in-memory
    map.
    """
    return CLINICAL_EVENTS_BY_PATIENT.get(patient_id_hash, [])


CLINICAL_EVENTS_BY_PATIENT = {}


def lookup_protocol(indication, patient_language,
                      capture_context):
    """
    Look up the indication-specific capture protocol for the
    patient's language and capture context. Production
    selects from a per-indication, per-language matrix; the
    demo uses a single protocol per indication.
    """
    if indication == "parkinsons_screening":
        return CAPTURE_PROTOCOLS.get(
            "parkinsons_screening_v1")
    if indication == "respiratory_monitoring":
        return CAPTURE_PROTOCOLS.get(
            "respiratory_monitoring_v1")
    return None


def lookup_model_card(indication):
    """Look up the per-indication model card."""
    return MODEL_CARDS.get(indication)


def lookup_cohort_calibration(indication, cohort):
    """Look up the per-cohort calibration entry."""
    model_card = lookup_model_card(indication)
    if not model_card:
        return None
    calibration_version = model_card.get(
        "calibration_versions", {}).get(cohort)
    if not calibration_version:
        return None
    return CALIBRATION_LOOKUP.get(
        (indication, cohort, calibration_version))


def lookup_clinical_action_mapping(indication, category,
                                     trajectory,
                                     confound_flags):
    """
    Look up the institutional clinical-action mapping for
    this combination. Production owns this in a clinical-
    quality-leadership-reviewed table; the demo uses a
    simple lookup with a trajectory-change override.
    """
    base = CLINICAL_ACTION_MAP.get(indication, {}).get(
        category, "longitudinal_only")
    if (trajectory
            and trajectory.get("delta_significance")
                == "outside_typical_variation"
            and base == "longitudinal_only"):
        return "clinician_review"
    return base
```

---

## Step 1: Capture the Audio Sample with Indication-Specific Protocol, Real-Time Quality Assessment, and Explicit Biometric-Data Consent

*The pseudocode calls this `ON capture_initiated(...)`. When a patient or clinician initiates a capture, the system selects the indication-specific protocol, prompts the speaker through the tasks, runs real-time quality checks, and records the consent context including the biometric-data terms. Skip the per-protocol prompt design and the resulting audio cannot be reliably scored against the model's validation conditions. Skip the consent capture and the institution accumulates biometric data without proper authorization.*

```python
def build_disclosure(indication, retention_terms,
                      jurisdiction, third_party_disclosure):
    """
    Assemble the consent disclosure for the patient. The
    disclosure language depends on the indication's clinical
    vs. research framing, the patient's jurisdiction (BIPA-
    equivalent states require specific language), and the
    institutional retention terms. Production composes this
    from versioned disclosure templates; the demo selects a
    base disclosure and appends the retention terms.
    """
    indication_type = "research" \
        if indication.endswith("_research") else "clinical"
    base_disclosure = _select_consent_disclosure(
        jurisdiction=jurisdiction,
        indication_type=indication_type)
    retention_addendum = (
        f" Audio samples will be retained for "
        f"{retention_terms.get('audio_hours', 24)} hours; "
        f"feature vectors derived from your voice will be "
        f"retained for "
        f"{retention_terms.get('feature_vector_days', 365)} "
        f"days. You may request deletion at any time.")
    return base_disclosure + retention_addendum


def capture_consent(patient_id, consent_type, disclosure,
                     require_explicit):
    """
    Capture the patient's consent. Production presents the
    disclosure through the device UI and records an explicit
    acknowledgment for jurisdictions or indications that
    require it; the demo simulates a granted consent.
    """
    consent_id = "consent-" + uuid.uuid4().hex[:12]
    return {
        "granted":       True,
        "consent_id":    consent_id,
        "consent_type":  consent_type,
        "disclosure":    disclosure,
        "explicit":      require_explicit,
        "captured_at":   _now_iso(),
    }


def capture_audio_with_quality_assessment(task,
                                              quality_thresholds,
                                              max_retries):
    """
    Capture audio for one task and assess its quality
    in-line. Production drives the device's microphone
    capture, runs real-time SNR and clipping detection, and
    prompts the speaker to retry if the quality fails the
    institutional minimums. The mock returns a fixture per
    task_id pulled from CURRENT_CAPTURE_FIXTURE.
    """
    fixture = CURRENT_CAPTURE_FIXTURE.get(task["task_id"], {})
    captured = {
        "task_id":        task["task_id"],
        "s3_uri":
            f"s3://{AUDIO_BUCKET}/"
            f"{fixture.get('session_id', 'demo-session')}/"
            f"{task['task_id']}.wav",
        "duration":
            fixture.get("duration",
                          task.get("min_duration_seconds", 5)),
        "quality_score":
            fixture.get("quality_score",
                          Decimal("0.85")),
        "sample_rate":
            fixture.get("sample_rate", 16000),
        "codec":
            fixture.get("codec", "PCM_16"),
        "snr_db":
            fixture.get("snr_db", Decimal("22.0")),
        "clipping":
            fixture.get("clipping_percent",
                          Decimal("0.1")),
    }

    # In production: write the audio to S3 with KMS encryption
    # and metadata that includes the session_id, task_id, and
    # quality measurements. The demo just records a stub.
    s3_store.put_object(
        bucket=AUDIO_BUCKET,
        key=(f"{fixture.get('session_id', 'demo-session')}/"
             f"{task['task_id']}.wav"),
        body=b"<mock audio bytes>",
        metadata={
            "session_id":
                fixture.get("session_id", "demo-session"),
            "task_id":   task["task_id"],
            "duration":  str(captured["duration"]),
            "snr_db":    str(captured["snr_db"]),
        })

    return captured


# Per-task fixtures. The demo wires this up before running
# each scenario.
CURRENT_CAPTURE_FIXTURE = {}


def capture_initiated(patient_id, indication,
                        capture_context, session_id_hint=None):
    """
    Bootstrap a voice-biomarker capture session: select the
    indication-specific protocol, capture biometric-data
    consent, walk the speaker through the protocol tasks,
    record per-task quality, and persist the session record.
    """
    # Step 1A: select the indication-specific protocol.
    patient_language = lookup_patient_language(patient_id)
    protocol = lookup_protocol(
        indication=indication,
        patient_language=patient_language,
        capture_context=capture_context)

    if protocol is None:
        audit_log({
            "event_type":    "PROTOCOL_NOT_AVAILABLE",
            "indication":    indication,
            "language":      patient_language,
            "device_class":
                capture_context.get("device_class"),
            "timestamp":     _now_iso(),
        })
        return {"status":     "PROTOCOL_NOT_AVAILABLE",
                "indication": indication}

    # Step 1B: capture biometric-data consent.
    jurisdiction = lookup_patient_jurisdiction(patient_id)
    disclosure = build_disclosure(
        indication=indication,
        retention_terms=protocol.get("retention", {}),
        jurisdiction=jurisdiction,
        third_party_disclosure=protocol.get("disclosures"))

    consent_outcome = capture_consent(
        patient_id=patient_id,
        consent_type="voice_biomarker_collection",
        disclosure=disclosure,
        require_explicit=protocol.get(
            "requires_explicit_consent", True))

    if not consent_outcome["granted"]:
        audit_log({
            "event_type":      "CONSENT_DECLINED",
            "indication":      indication,
            "jurisdiction":    jurisdiction,
            "timestamp":       _now_iso(),
        })
        return {"status":     "CONSENT_DECLINED",
                "indication": indication}

    # Step 1C: bootstrap the capture session.
    session_id = session_id_hint or (
        "vbm-" + uuid.uuid4().hex[:16])
    started_at = _now_iso()

    # Make the session_id available to the per-task capture
    # mock so it can build appropriate S3 paths.
    for fixture in CURRENT_CAPTURE_FIXTURE.values():
        fixture["session_id"] = session_id

    capture_session_table.put(session_id, _to_decimal({
        "session_id":            session_id,
        "patient_id_hash":       _hash_value(patient_id),
        "indication":            indication,
        "protocol_version":      protocol["version"],
        "consent_id":            consent_outcome["consent_id"],
        "capture_context":       capture_context,
        "device_class":
            capture_context.get("device_class", "unknown"),
        "jurisdiction":          jurisdiction,
        "started_at":            started_at,
        "status":                "in_progress",
        "captured_segments":     [],
        "feature_pipeline_version":
            FEATURE_PIPELINE_VERSION,
        "eligibility_rules_version":
            ELIGIBILITY_RULES_VERSION,
    }))

    # Step 1D: walk the speaker through the protocol tasks.
    captured_segments = []
    for task in protocol["tasks"]:
        # Production prompts the speaker through the device
        # UI and waits for the audio to be captured. The mock
        # simulates the capture using the per-task fixture.
        segment = capture_audio_with_quality_assessment(
            task=task,
            quality_thresholds=task["quality_thresholds"],
            max_retries=task.get(
                "max_retries", MAX_TASK_RETRIES))

        if segment["quality_score"] < task["minimum_quality"]:
            audit_log({
                "event_type":         "TASK_QUALITY_FAILED",
                "session_id":         session_id,
                "task_id":            task["task_id"],
                "quality_score":
                    float(segment["quality_score"]),
                "min_required":
                    float(task["minimum_quality"]),
                "timestamp":          _now_iso(),
            })
            if task.get("required", True):
                capture_session_table.update(session_id, {
                    "status":            "quality_failed",
                    "failed_task":       task["task_id"],
                    "completed_at":      _now_iso(),
                })
                return {
                    "status":         "INSUFFICIENT_QUALITY",
                    "session_id":     session_id,
                    "failed_task":    task["task_id"],
                }

        captured_segments.append({
            "task_id":          segment["task_id"],
            "audio_ref":        segment["s3_uri"],
            "duration_seconds": segment["duration"],
            "quality_score":    segment["quality_score"],
            "sample_rate":      segment["sample_rate"],
            "codec":             segment["codec"],
            "snr_db":            segment["snr_db"],
            "clipping_percent": segment["clipping"],
        })

    # Step 1E: persist the captured-segments record.
    capture_session_table.update(session_id, _to_decimal({
        "captured_segments":     captured_segments,
        "capture_completed_at":  _now_iso(),
        "status":                "captured",
    }))

    event_bus.put_events([{
        "Source":       "voice_biomarker",
        "DetailType":   "sample_captured",
        "EventBusName": BIOMARKER_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":     session_id,
            "indication":     indication,
            "segment_count":  len(captured_segments),
            "device_class":
                capture_context.get("device_class"),
            "jurisdiction":   jurisdiction,
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "SamplesCaptured", 1, "Count",
        dimensions={
            "indication":   indication,
            "device_class":
                capture_context.get("device_class", "unknown"),
            "language":     patient_language,
        })

    audit_log({
        "event_type":          "CAPTURE_SESSION_COMPLETE",
        "session_id":          session_id,
        "indication":          indication,
        "segment_count":       len(captured_segments),
        "device_class":
            capture_context.get("device_class"),
        "jurisdiction":        jurisdiction,
        "timestamp":           _now_iso(),
    })

    return {
        "status":             "CAPTURED",
        "session_id":         session_id,
        "indication":         indication,
        "segment_count":      len(captured_segments),
    }
```

---

## Step 2: Extract Acoustic and Linguistic Features with Bandwidth and Codec-Aware Processing

*The pseudocode calls this `extract_features(...)`. Each task segment is processed through the appropriate feature pipeline: sustained-vowel segments produce vocal-fold-function features (jitter, shimmer, harmonic-to-noise ratio); read-passage and spontaneous-speech segments produce timing, prosody, and articulation features plus optional linguistic features from the transcript; cough-collection segments produce acoustic-event features. The feature extraction is bandwidth-aware; features that depend on frequencies the recording chain does not preserve are flagged as unmeasurable rather than computed against missing signal. Skip the bandwidth-awareness and the resulting features include garbage values from frequencies that the codec discarded.*

```python
def determine_codec_bandwidth(state):
    """
    Determine the minimum codec bandwidth across the
    captured segments. The biomarker pipeline filters out
    features that depend on frequencies above this floor.
    """
    min_bandwidth = float("inf")
    for segment in state.get("captured_segments", []):
        codec = segment.get("codec", "PCM_16")
        sample_rate = int(segment.get("sample_rate", 16000))
        # Telephony codecs aggressively limit high frequencies.
        # Production maintains a per-codec bandwidth lookup;
        # the demo uses sample_rate / 2 (Nyquist) as the
        # bandwidth proxy with a telephony-codec override.
        if codec in {"G711", "G722"}:
            bandwidth = 4000 if codec == "G711" else 7000
        else:
            bandwidth = sample_rate // 2
        min_bandwidth = min(min_bandwidth, bandwidth)
    return min_bandwidth if min_bandwidth != float("inf") else 8000


def lookup_task_definition(indication, task_id):
    """
    Look up the per-indication, per-task feature
    requirements. Production maintains per-task feature lists
    keyed on the indication and task_id; the demo uses an
    illustrative subset.
    """
    base_definitions = {
        "sustained_vowel_a": {
            "feature_list": {
                "acoustic": ["jitter_local", "shimmer_local",
                             "harmonic_to_noise_ratio",
                             "f0_mean", "f0_std",
                             "spectral_tilt"],
                "linguistic": [],
            },
            "embedding_model_id": "wavlm-base-plus-2024",
            "uses_linguistic_features": False,
            "is_spontaneous_speech":   False,
        },
        "read_passage": {
            "feature_list": {
                "acoustic": ["articulation_rate",
                             "pause_distribution",
                             "pitch_range",
                             "voice_onset_time",
                             "formant_trajectories",
                             "mfcc_stats"],
                "linguistic": [],
            },
            "embedding_model_id": "wavlm-base-plus-2024",
            "uses_linguistic_features": False,
            "is_spontaneous_speech":   False,
        },
        "voluntary_cough": {
            "feature_list": {
                "acoustic": ["cough_event_count",
                             "spectral_centroid",
                             "burst_energy_ratio",
                             "post_burst_decay"],
                "linguistic": [],
            },
            "embedding_model_id": None,
            "uses_linguistic_features": False,
            "is_spontaneous_speech":   False,
        },
        "spontaneous_speech": {
            "feature_list": {
                "acoustic": ["articulation_rate",
                             "pause_distribution",
                             "lexical_pause_locations"],
                "linguistic": ["lexical_diversity",
                               "syntactic_complexity",
                               "idea_density",
                               "word_finding_pauses",
                               "semantic_coherence"],
            },
            "embedding_model_id": "wavlm-base-plus-2024",
            "uses_linguistic_features": True,
            "is_spontaneous_speech":   True,
        },
    }
    return base_definitions.get(task_id, {
        "feature_list": {"acoustic": [], "linguistic": []},
        "embedding_model_id": None,
        "uses_linguistic_features": False,
        "is_spontaneous_speech":   False,
    })


def filter_features_by_bandwidth(requested_features,
                                    available_bandwidth_hz):
    """
    Bandwidth-aware feature selection. Some features (high-
    frequency spectral tilt, certain formant features) are
    not reliably measurable when the codec aggressively
    compresses high frequencies. Production maintains a per-
    feature minimum-bandwidth requirement; the demo uses a
    simple threshold per feature class.
    """
    high_frequency_dependent = {
        "spectral_tilt", "formant_trajectories",
        "voice_onset_time", "burst_energy_ratio",
    }
    applicable_acoustic = []
    excluded = []
    for feature in requested_features.get("acoustic", []):
        if (feature in high_frequency_dependent
                and available_bandwidth_hz < 6000):
            excluded.append({
                "feature":           feature,
                "reason":            "bandwidth_below_floor",
                "available_hz":      available_bandwidth_hz,
                "required_hz":       6000,
            })
        else:
            applicable_acoustic.append(feature)

    return {
        "acoustic":   applicable_acoustic,
        "linguistic": list(
            requested_features.get("linguistic", [])),
        "excluded":   excluded,
    }


def compute_acoustic_features(audio_ref, features,
                                 return_confidence=True):
    """
    Compute the requested acoustic features. Production calls
    a feature-extraction service (a custom Lambda or Fargate
    task running a librosa / openSMILE / Praat-derived
    pipeline, or a SageMaker endpoint dedicated to feature
    extraction); the demo returns canned values per audio_ref.
    """
    fixture = ACOUSTIC_FEATURE_FIXTURES.get(audio_ref, {})
    return {
        "values": {
            feature: fixture.get(
                feature, Decimal("0.5"))
            for feature in features
        },
        "per_feature_confidence": {
            feature: Decimal("0.85")
            for feature in features
        },
    }


def compute_speech_embeddings(audio_ref, model_id):
    """
    Compute the pretrained-speech-model embedding for the
    audio segment. Production hosts the embedding model
    behind a SageMaker real-time endpoint; the demo returns
    a small fake embedding.
    """
    if not model_id:
        return None
    fixture_key = (audio_ref, model_id)
    return EMBEDDING_FIXTURES.get(fixture_key,
        [Decimal("0.0")] * 8)


def transcribe_for_linguistic_features(audio_ref, language):
    """
    Transcribe the audio for linguistic-feature extraction.
    Production calls Transcribe Medical (when the speech is
    clinical content) or general Transcribe; the demo
    returns a fixture transcript.
    """
    job_name = f"linguistic-{uuid.uuid4().hex[:8]}"
    transcribe_mock.start_medical_transcription(
        job_name=job_name,
        audio_uri=audio_ref,
        language=language)
    return transcribe_mock.retrieve_transcript(audio_ref)


def extract_linguistic_features(transcript,
                                   requested_features):
    """
    Extract linguistic features from the transcript.
    Production runs an NLP pipeline that computes lexical
    diversity, syntactic complexity, idea density, and other
    linguistic-feature primitives; the demo returns canned
    values per (transcript, feature) pair.
    """
    return {
        feature: LINGUISTIC_FEATURE_FIXTURES.get(
            (transcript, feature), Decimal("0.5"))
        for feature in requested_features.get("linguistic", [])
    }


def has_actionable_clinical_content(clinical_entities):
    """
    Check whether the spontaneous-speech transcript contains
    incidentally-mentioned clinical content (chest pain,
    suicidal ideation, severe headache) that warrants
    clinical follow-up regardless of the biomarker output.
    """
    actionable_terms = {
        "chest pain", "suicidal", "severe headache",
        "shortness of breath", "loss of consciousness",
    }
    for entity in clinical_entities.get("Entities", []):
        text = (entity.get("Text") or "").lower()
        if any(term in text for term in actionable_terms):
            return True
    return False


def route_to_clinical_review(session_id, clinical_entities):
    """
    Route incidentally-mentioned actionable clinical content
    to the clinical-review workflow regardless of the
    biomarker output. Production creates an EHR alert; this
    demo only records an audit event. A real deployment calls
    something like ehr_cds.create_alert(...) with a
    "spontaneous_speech_incidental" priority so the alert
    reaches a clinician synchronously.
    """
    # TODO (TechWriter): production should create an EHR
    # decision-support alert here, not just audit-log it.
    audit_log({
        "event_type":      "INCIDENTAL_CLINICAL_CONTENT",
        "session_id":      session_id,
        "entity_count":
            len(clinical_entities.get("Entities", [])),
        "timestamp":       _now_iso(),
    })


# Per-segment feature fixtures. The demo wires these up
# before each scenario.
ACOUSTIC_FEATURE_FIXTURES = {}
EMBEDDING_FIXTURES = {}
LINGUISTIC_FEATURE_FIXTURES = {}


def extract_features(session_id):
    """
    Extract acoustic and (where applicable) linguistic
    features for each captured task segment, with bandwidth
    and codec-aware processing. Persist the resulting
    feature set to S3 and update the capture-session record.

    Note: production runs voice-activity detection and task-
    specific segmentation on each captured audio_ref before
    the feature pipeline. The demo assumes captured segments
    are already trimmed and task-segmented; a real
    implementation calls a VAD service (a custom Lambda
    running webrtcvad or silero-vad, or a SageMaker endpoint
    hosting a VAD model) at this point.
    """
    state = capture_session_table.get(session_id)
    indication = state.get("indication")
    feature_set = {
        "session_id":              session_id,
        "indication":              indication,
        "per_segment_features":    {},
        "recording_chain_metadata": {
            "device_class":
                state.get("device_class"),
            "min_codec_bandwidth_hz":
                determine_codec_bandwidth(state),
        },
    }

    # Step 2A: per-segment feature extraction.
    for segment in state.get("captured_segments", []):
        task_def = lookup_task_definition(
            indication=indication,
            task_id=segment.get("task_id"))

        applicable_features = filter_features_by_bandwidth(
            requested_features=task_def["feature_list"],
            available_bandwidth_hz=feature_set[
                "recording_chain_metadata"][
                    "min_codec_bandwidth_hz"])

        # Acoustic features.
        acoustic_features = compute_acoustic_features(
            audio_ref=segment["audio_ref"],
            features=applicable_features["acoustic"],
            return_confidence=True)

        # Pretrained-representation features.
        embedding_features = compute_speech_embeddings(
            audio_ref=segment["audio_ref"],
            model_id=task_def.get("embedding_model_id"))

        # Linguistic features (if applicable).
        linguistic_features = None
        if task_def.get("uses_linguistic_features"):
            transcript = transcribe_for_linguistic_features(
                audio_ref=segment["audio_ref"],
                language=state.get(
                    "capture_context", {}).get(
                    "language", "en-US"))

            linguistic_features = extract_linguistic_features(
                transcript=transcript,
                requested_features=applicable_features)

            if task_def.get("is_spontaneous_speech"):
                clinical_entities = (
                    comprehend_mock.detect_entities_v2(
                        text=transcript))
                if has_actionable_clinical_content(
                        clinical_entities):
                    route_to_clinical_review(
                        session_id, clinical_entities)

        feature_set["per_segment_features"][
            segment["task_id"]] = {
                "acoustic":              acoustic_features,
                "embeddings":            embedding_features,
                "linguistic":            linguistic_features,
                "unmeasurable_features":
                    applicable_features["excluded"],
            }

    # Step 2B: persist the feature set to S3.
    feature_archive_object = s3_store.put_object(
        bucket=FEATURE_BUCKET,
        key=f"{session_id}/features.json",
        body=json.dumps(feature_set,
                          default=str).encode("utf-8"),
        metadata={
            "session_id": session_id,
            "indication": indication,
        })

    capture_session_table.update(session_id, _to_decimal({
        "feature_set_archive_ref":
            feature_archive_object["uri"],
        "features_extracted_at":  _now_iso(),
        "status":                 "features_extracted",
    }))

    event_bus.put_events([{
        "Source":       "voice_biomarker",
        "DetailType":   "features_extracted",
        "EventBusName": BIOMARKER_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":  session_id,
            "indication":  indication,
            "feature_archive_ref":
                feature_archive_object["uri"],
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "FeaturesExtracted", 1, "Count",
        dimensions={"indication": indication})

    audit_log({
        "event_type":          "FEATURES_EXTRACTED",
        "session_id":          session_id,
        "indication":          indication,
        "segment_count":
            len(feature_set["per_segment_features"]),
        "min_codec_bandwidth_hz":
            feature_set["recording_chain_metadata"][
                "min_codec_bandwidth_hz"],
        "timestamp":           _now_iso(),
    })

    return {
        "feature_set":            feature_set,
        "feature_archive_ref":
            feature_archive_object["uri"],
    }
```

---

## Step 3: Check Eligibility for Each Candidate Biomarker Model Based on Validation Envelope

*The pseudocode calls this `check_eligibility(...)`. Each per-indication model has a validation envelope: the demographic distributions, recording-chain conditions, and task-completion expectations the model was validated under. Before the model is invoked, the system checks whether the current sample fits the envelope. Out-of-envelope samples produce an "indication not assessable" result rather than a potentially-misleading score. Skip the eligibility check and the system silently produces scores on samples the model was not validated for, which is a clinical-safety failure mode.*

```python
def check_demographic_envelope(patient_demographics,
                                  validation_demographics):
    """
    Check whether the patient's demographics fit within the
    model's validation distribution. Production handles
    continuous variables (age) with band-based matching and
    categorical variables (sex, language) with set
    membership; the demo uses the same pattern.
    """
    age_band = _bucket_age(patient_demographics.get("age"))
    sex      = patient_demographics.get("sex")
    language = patient_demographics.get("primary_language")

    age_eligible = age_band in validation_demographics.get(
        "age_band", [])
    sex_eligible = sex in validation_demographics.get(
        "sex", [])
    language_eligible = language in (
        validation_demographics.get("language", []))

    return {
        "eligible":
            age_eligible and sex_eligible and language_eligible,
        "age_band":         age_band,
        "age_eligible":     age_eligible,
        "sex":              sex,
        "sex_eligible":     sex_eligible,
        "language":         language,
        "language_eligible": language_eligible,
    }


def check_recording_envelope(recording_metadata,
                                validation_envelope):
    """
    Check whether the recording chain fits within the model's
    validation envelope. The device class (clinic-grade
    microphone vs. smartphone vs. telehealth) and the
    minimum codec bandwidth are the primary axes; production
    additionally checks per-codec-class eligibility and
    per-environment categorization.
    """
    device_class = recording_metadata.get("device_class")
    min_bandwidth = recording_metadata.get(
        "min_codec_bandwidth_hz", 0)

    device_eligible = device_class in (
        validation_envelope.get("device_class", []))
    bandwidth_eligible = min_bandwidth >= (
        validation_envelope.get("min_codec_bandwidth_hz", 0))

    return {
        "eligible":           device_eligible
                                and bandwidth_eligible,
        "device_class":       device_class,
        "device_eligible":    device_eligible,
        "min_codec_bandwidth_hz":  min_bandwidth,
        "bandwidth_eligible": bandwidth_eligible,
    }


def check_task_completion(captured_segments,
                            required_tasks,
                            min_per_task_quality):
    """
    Check whether the captured segments include all required
    tasks at adequate quality.
    """
    captured_task_ids = {seg.get("task_id")
                          for seg in captured_segments}
    missing_tasks = [t for t in required_tasks
                     if t not in captured_task_ids]

    low_quality_tasks = []
    for seg in captured_segments:
        if (seg.get("task_id") in required_tasks
                and Decimal(str(seg.get("quality_score", 0)))
                < min_per_task_quality):
            low_quality_tasks.append(seg.get("task_id"))

    return {
        "eligible":              not missing_tasks
                                  and not low_quality_tasks,
        "missing_tasks":         missing_tasks,
        "low_quality_tasks":     low_quality_tasks,
    }


def check_confounds(patient_id_hash, recent_clinical_events,
                      model_confounds):
    """
    Flag confound conditions that may affect the biomarker
    score (recent respiratory infection, recent dental
    procedure, acute medication change). The flags do not
    automatically disqualify; they accompany the score so
    the clinician knows which confounds to consider.
    """
    flags = []
    event_keys = {evt.get("event_type")
                   for evt in recent_clinical_events}
    for confound in model_confounds:
        if confound in event_keys:
            flags.append(confound)
    return flags


def assign_cohort(patient_demographics,
                    recording_chain_metadata,
                    cohort_definitions=None):
    """
    Assign the cohort label that selects the per-cohort
    calibration. Production maintains per-indication cohort
    definitions; the demo uses a default schema based on
    age-band, sex, language, and recording-environment.
    """
    age_band = _bucket_age(patient_demographics.get("age"))
    sex = patient_demographics.get("sex", "unknown")
    language = patient_demographics.get(
        "primary_language", "unknown").split("-")[0].lower()

    device_class = recording_chain_metadata.get(
        "device_class", "unknown")
    if device_class == "clinic_dedicated_microphone":
        recording_class = "clinic_recording"
    elif device_class.startswith("smartphone"):
        recording_class = "smartphone_recording"
    elif device_class == "telehealth_video":
        recording_class = "telehealth_recording"
    else:
        recording_class = "unknown_recording"

    return f"{age_band}_{sex}_{language}_{recording_class}"


def summarize_ineligibility(elig):
    """Produce a short, human-readable list of ineligibility
    reasons for the result payload."""
    reasons = []
    # Handle the simplified "no model card available" shape
    # produced by check_eligibility when an indication has no
    # model card. Without this guard, the chained dict lookups
    # below would raise KeyError mid-loop and crash scoring
    # for every other indication in the same session.
    if "reason" in elig and "demographic_fit" not in elig:
        return [elig["reason"]]
    if not elig["demographic_fit"]["eligible"]:
        if not elig["demographic_fit"]["age_eligible"]:
            reasons.append("age_outside_validation")
        if not elig["demographic_fit"]["sex_eligible"]:
            reasons.append("sex_outside_validation")
        if not elig["demographic_fit"]["language_eligible"]:
            reasons.append("language_outside_validation")
    if not elig["recording_fit"]["eligible"]:
        if not elig["recording_fit"]["device_eligible"]:
            reasons.append(
                "device_class_outside_validation")
        if not elig["recording_fit"]["bandwidth_eligible"]:
            reasons.append(
                "codec_bandwidth_below_floor")
    if not elig["task_fit"]["eligible"]:
        if elig["task_fit"]["missing_tasks"]:
            reasons.append("missing_required_tasks")
        if elig["task_fit"]["low_quality_tasks"]:
            reasons.append("low_quality_required_tasks")
    return reasons


def check_eligibility(session_id, candidate_indications,
                        patient_id):
    """
    For each candidate indication, check whether the captured
    sample fits the model's validation envelope and assign
    the cohort for downstream calibration.
    """
    state = capture_session_table.get(session_id)
    feature_set_object = s3_store.get_object(
        bucket=FEATURE_BUCKET,
        key=f"{session_id}/features.json")
    feature_set = json.loads(
        feature_set_object["body"].decode("utf-8"))

    eligibility_results = {}
    patient_demographics = lookup_patient_demographics(
        patient_id)

    for indication in candidate_indications:
        model_card = lookup_model_card(indication)
        if not model_card:
            eligibility_results[indication] = {
                "eligible": False,
                "reason":   "no_model_card_available",
            }
            continue

        demographic_fit = check_demographic_envelope(
            patient_demographics=patient_demographics,
            validation_demographics=model_card.get(
                "validation_demographics", {}))

        recording_fit = check_recording_envelope(
            recording_metadata=feature_set[
                "recording_chain_metadata"],
            validation_envelope=model_card.get(
                "validation_recording_envelope", {}))

        task_fit = check_task_completion(
            captured_segments=state.get(
                "captured_segments", []),
            required_tasks=model_card.get(
                "required_tasks", []),
            min_per_task_quality=Decimal(str(
                model_card.get("min_per_task_quality", 0.5))))

        confound_flags = check_confounds(
            patient_id_hash=state.get("patient_id_hash"),
            recent_clinical_events=
                lookup_recent_clinical_events(
                    state.get("patient_id_hash"),
                    window_days=30),
            model_confounds=model_card.get(
                "confounds_to_flag", []))

        eligibility_results[indication] = {
            "eligible":         (demographic_fit["eligible"]
                                  and recording_fit["eligible"]
                                  and task_fit["eligible"]),
            "demographic_fit":  demographic_fit,
            "recording_fit":    recording_fit,
            "task_fit":         task_fit,
            "confound_flags":   confound_flags,
            "assigned_cohort":  assign_cohort(
                patient_demographics=patient_demographics,
                recording_chain_metadata=feature_set[
                    "recording_chain_metadata"]),
        }

    capture_session_table.update(session_id, _to_decimal({
        "eligibility":             eligibility_results,
        "eligibility_assessed_at": _now_iso(),
        "status":                  "eligibility_assessed",
    }))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "EligibilityAssessmentsRun",
        len(candidate_indications), "Count",
        dimensions={
            "indication":
                ",".join(candidate_indications)[:100],
        })

    for indication, elig in eligibility_results.items():
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "EligibilityOutcome",
            1, "Count",
            dimensions={
                "indication": indication,
                "outcome":
                    ("eligible" if elig.get("eligible")
                     else "ineligible"),
                "cohort":
                    elig.get("assigned_cohort", "unknown"),
            })

    audit_log({
        "event_type":          "ELIGIBILITY_ASSESSED",
        "session_id":          session_id,
        "candidate_indications": candidate_indications,
        "eligible_indications": [
            ind for ind, elig in eligibility_results.items()
            if elig.get("eligible")],
        "timestamp":           _now_iso(),
    })

    return eligibility_results
```

---

## Step 4: Score the Eligible Biomarkers with Per-Cohort Calibration and Indeterminate Handling

*The pseudocode calls this `score_biomarkers(...)`. For each indication that passed eligibility, the system invokes the validated SageMaker endpoint, applies the per-cohort calibration to the raw model output, computes a confidence interval, and packages the result. When the model's confidence is below the institutional threshold, the result is marked indeterminate rather than passed through as a confident score. Skip the per-cohort calibration and the system produces uncalibrated outputs that perform inconsistently across cohorts. Skip the indeterminate handling and edge-case samples produce confident-looking scores that the clinical workflow takes at face value.*

```python
def assemble_model_input(feature_set, model_card,
                            session_id, indication):
    """
    Build the JSON input payload the SageMaker endpoint
    expects. The shape is model-specific; production
    maintains per-model input adapters, the demo uses a
    common shape with the per-segment feature dicts.
    """
    return {
        "session_id":       session_id,
        "indication":       indication,
        "model_version":    model_card.get("model_version"),
        "feature_pipeline_version":
            FEATURE_PIPELINE_VERSION,
        "per_segment_features":
            feature_set.get("per_segment_features", {}),
        "recording_chain_metadata":
            feature_set.get("recording_chain_metadata", {}),
    }


def parse_score(raw_response):
    """Parse the raw response from the SageMaker endpoint."""
    body = json.loads(raw_response["body"]) \
        if isinstance(raw_response.get("body"), str) \
        else raw_response.get("body", {})
    return {
        "raw_score":      Decimal(str(body.get(
            "raw_score", 0.5))),
        "feature_attribution": body.get(
            "feature_attribution", {"top_features": []}),
        "model_version":  body.get(
            "model_version", "unknown"),
    }


def apply_calibration(raw_score, calibration_curve):
    """
    Apply per-cohort calibration to the raw model score.
    Production supports multiple calibration curve types
    (Platt scaling, isotonic regression, beta calibration);
    the demo handles the two used in the fixture data.
    """
    if isinstance(calibration_curve, dict) and \
       calibration_curve.get("curve") == "platt_scaling":
        # Logistic calibration: 1 / (1 + exp(-(intercept +
        # slope * raw_score))). The demo uses Decimal-safe
        # arithmetic with a small lookup-table approximation
        # for exp; production uses numpy or scipy.
        intercept = Decimal(str(calibration_curve.get(
            "intercept", 0)))
        slope = Decimal(str(calibration_curve.get(
            "slope", 1)))
        z = intercept + slope * raw_score
        # Approximate sigmoid using a piecewise table to
        # avoid pulling math.exp in the demo.
        if z > Decimal("4"):
            return Decimal("0.98")
        if z < Decimal("-4"):
            return Decimal("0.02")
        # Linear approximation around 0; close enough for
        # illustration. Production uses real sigmoid (math.exp
        # via float, then convert back to Decimal).
        return min(Decimal("0.99"),
                     max(Decimal("0.01"),
                           Decimal("0.5") + z
                           * Decimal("0.18")))
    if isinstance(calibration_curve, dict) and \
       calibration_curve.get("curve") == "isotonic":
        knots = calibration_curve.get("knot_points", [])
        if not knots:
            return raw_score
        # Linear interpolation between knot points.
        for i in range(len(knots) - 1):
            lo, hi = knots[i], knots[i + 1]
            if Decimal(str(lo["raw"])) <= raw_score \
                    <= Decimal(str(hi["raw"])):
                lo_raw = Decimal(str(lo["raw"]))
                hi_raw = Decimal(str(hi["raw"]))
                lo_cal = Decimal(str(lo["calibrated"]))
                hi_cal = Decimal(str(hi["calibrated"]))
                if hi_raw == lo_raw:
                    return lo_cal
                ratio = ((raw_score - lo_raw)
                          / (hi_raw - lo_raw))
                return lo_cal + ratio * (hi_cal - lo_cal)
        if raw_score < Decimal(str(knots[0]["raw"])):
            return Decimal(str(knots[0]["calibrated"]))
        return Decimal(str(knots[-1]["calibrated"]))
    return raw_score


def compute_confidence_interval(score, cohort_size,
                                   calibration_uncertainty):
    """
    Compute a confidence interval on the calibrated score.
    Production uses the calibration's empirical uncertainty
    plus a per-cohort-size correction; the demo uses a
    simple symmetric interval.
    """
    half_width = (Decimal(str(calibration_uncertainty))
                    + (Decimal("1.0")
                        / Decimal(str(max(cohort_size, 1)))
                        ).sqrt() * Decimal("0.5"))
    lower = max(Decimal("0"), score - half_width)
    upper = min(Decimal("1"), score + half_width)
    return {
        "lower":  lower,
        "upper":  upper,
        "width":  upper - lower,
    }


def assign_category(calibrated_score, thresholds):
    """
    Assign a categorical label based on the threshold map.
    Thresholds are ordered ascending; the first threshold
    the score does not exceed determines the category.
    """
    sorted_thresholds = sorted(
        thresholds.items(),
        key=lambda kv: Decimal(str(kv[1])))
    last_label = sorted_thresholds[0][0] \
        if sorted_thresholds else "unknown"
    for label, threshold in sorted_thresholds:
        if calibrated_score >= Decimal(str(threshold)):
            last_label = label
    return last_label


def compute_attribution(model_card, model_input,
                          raw_response):
    """
    Surface the top contributing features for clinician
    interpretation. Production reads the attribution from
    the model output (SHAP values, attention weights, or
    similar); the demo passes through whatever the mock
    provided.
    """
    body = json.loads(raw_response["body"]) \
        if isinstance(raw_response.get("body"), str) \
        else raw_response.get("body", {})
    return body.get("feature_attribution",
                     {"top_features": []})


def score_biomarkers(session_id):
    """
    For each eligible indication, invoke the SageMaker
    endpoint, apply per-cohort calibration, compute the
    confidence interval, and produce either a confident
    score or an indeterminate result.
    """
    state = capture_session_table.get(session_id)
    feature_set_object = s3_store.get_object(
        bucket=FEATURE_BUCKET,
        key=f"{session_id}/features.json")
    feature_set = json.loads(
        feature_set_object["body"].decode("utf-8"))
    eligibility = state.get("eligibility", {})
    scores = {}

    for indication, elig in eligibility.items():
        if not elig.get("eligible"):
            scores[indication] = {
                "status": "NOT_ASSESSABLE",
                "ineligibility_reasons":
                    summarize_ineligibility(elig),
            }
            continue

        model_card = lookup_model_card(indication)
        endpoint_name = model_card.get("sagemaker_endpoint")

        # Step 4A: assemble model inputs.
        model_input = assemble_model_input(
            feature_set=feature_set,
            model_card=model_card,
            session_id=session_id,
            indication=indication)

        # Step 4B: invoke the SageMaker endpoint. Real-time
        # endpoints serve in-encounter scoring; asynchronous
        # endpoints serve longitudinal-monitoring batches.
        # Real boto3 uses PascalCase keyword arguments:
        #     sagemaker_runtime.invoke_endpoint(
        #         EndpointName=endpoint_name,
        #         Body=json.dumps(model_input).encode("utf-8"),
        #         ContentType="application/json")
        # The mock uses snake_case to keep the demo readable.
        if model_card.get("inference_mode") == "real_time":
            raw_response = sagemaker_mock.invoke_endpoint(
                endpoint_name=endpoint_name,
                content_type="application/json",
                body=json.dumps(model_input, default=str))
        else:
            # Production writes the input payload to S3 and
            # passes the S3 URI to invoke_endpoint_async.
            # In production: invoke_endpoint_async returns
            # immediately with OutputLocation, InferenceId,
            # and FailureLocation; the actual model output
            # is written to OutputLocation asynchronously
            # (tens of seconds to minutes for voice biomarker
            # workloads). Poll S3 for the output object, or
            # use the endpoint's SNS notification topic
            # (the preferred production pattern), then
            # s3.get_object on the OutputLocation. A long-
            # blocking Lambda is not appropriate here; Step
            # Functions handles this with a Wait + GetObject
            # loop, or EventBridge handles the SNS-driven
            # completion event.
            input_object = s3_store.put_object(
                bucket=FEATURE_BUCKET,
                key=(f"async-input/{session_id}/"
                     f"{indication}.json"),
                body=json.dumps(model_input,
                                  default=str).encode("utf-8"))
            async_response = (
                sagemaker_mock.invoke_endpoint_async(
                    endpoint_name=endpoint_name,
                    input_location=input_object["uri"]))
            raw_response = sagemaker_mock.retrieve_async_output(
                output_location=async_response[
                    "OutputLocation"],
                fixture_key=async_response["_fixture_key"])

        parsed = parse_score(raw_response)
        raw_score = parsed["raw_score"]

        # Step 4C: apply per-cohort calibration.
        calibration = lookup_cohort_calibration(
            indication=indication,
            cohort=elig["assigned_cohort"])

        if not calibration:
            # No calibration available for the assigned
            # cohort; treat as not assessable rather than
            # using the population-default calibration. This
            # is the per-cohort discipline.
            scores[indication] = {
                "status":  "NOT_ASSESSABLE",
                "ineligibility_reasons": [
                    "no_calibration_for_cohort",
                ],
                "cohort":  elig["assigned_cohort"],
            }
            continue

        calibrated_score = apply_calibration(
            raw_score=raw_score,
            calibration_curve=calibration)

        # Step 4D: compute confidence interval.
        confidence_interval = compute_confidence_interval(
            score=calibrated_score,
            cohort_size=int(calibration.get(
                "cohort_size", 1)),
            calibration_uncertainty=calibration.get(
                "calibration_uncertainty", Decimal("0.05")))

        indeterminate_threshold = model_card.get(
            "indeterminate_threshold",
            DEFAULT_INDETERMINATE_INTERVAL_WIDTH)

        if confidence_interval["width"] > indeterminate_threshold:
            scores[indication] = {
                "status":              "INDETERMINATE",
                "raw_score":           raw_score,
                "calibrated_score":    calibrated_score,
                "confidence_interval": confidence_interval,
                "cohort":              elig["assigned_cohort"],
                "confound_flags":      elig["confound_flags"],
                "recommended_action":
                    "recapture_or_clinician_review",
                "model_version":       parsed["model_version"],
                "calibration_version": calibration["version"],
            }
            continue

        # Step 4E: threshold-based category assignment.
        category = assign_category(
            calibrated_score, calibration["thresholds"])

        # Step 4F: feature-attribution explanation.
        feature_attribution = compute_attribution(
            model_card=model_card,
            model_input=model_input,
            raw_response=raw_response)

        scores[indication] = {
            "status":              "SCORED",
            "raw_score":           raw_score,
            "calibrated_score":    calibrated_score,
            "confidence_interval": confidence_interval,
            "category":            category,
            "cohort":              elig["assigned_cohort"],
            "confound_flags":      elig["confound_flags"],
            "top_features":
                feature_attribution.get("top_features", []),
            "model_version":       parsed["model_version"],
            "calibration_version": calibration["version"],
            "scored_at":           _now_iso(),
        }

    capture_session_table.update(session_id, _to_decimal({
        "scores":               scores,
        "scoring_completed_at": _now_iso(),
        "status":               "scored",
    }))

    for indication, score in scores.items():
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "ScoringOutcome",
            1, "Count",
            dimensions={
                "indication": indication,
                "status":     score["status"],
                "cohort":     score.get("cohort", "unknown"),
            })

    event_bus.put_events([{
        "Source":       "voice_biomarker",
        "DetailType":   "scoring_completed",
        "EventBusName": BIOMARKER_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id": session_id,
            "indications": list(scores.keys()),
            "outcomes":
                {ind: sc["status"]
                 for ind, sc in scores.items()},
        }),
    }])

    audit_log({
        "event_type":         "BIOMARKERS_SCORED",
        "session_id":         session_id,
        "indication_count":   len(scores),
        "scored_count":       sum(
            1 for s in scores.values()
            if s["status"] == "SCORED"),
        "indeterminate_count": sum(
            1 for s in scores.values()
            if s["status"] == "INDETERMINATE"),
        "not_assessable_count": sum(
            1 for s in scores.values()
            if s["status"] == "NOT_ASSESSABLE"),
        "timestamp":          _now_iso(),
    })

    return scores
```

---

## Step 5: Compute Longitudinal Trajectory and Package the Clinical Interpretation

*The pseudocode calls this `package_interpretation(...)`. For patients with prior samples, the system computes the trajectory delta against the patient's baseline. The packaged interpretation includes the score, the trajectory, the supporting features, the cohort context, the confound flags, and the institutionally-approved clinical-action mapping. Skip the trajectory computation and the system loses the per-patient longitudinal context that makes voice biomarkers most reliable. Skip the institutional clinical-action mapping and individual clinicians have to infer how to act on the score.*

```python
def compute_patient_baseline(prior_samples,
                                exclude_recent_days):
    """
    Compute the patient's baseline score from prior samples,
    excluding the most recent window to avoid contamination
    from the trajectory we are trying to detect.
    """
    cutoff = (datetime.now(timezone.utc)
                - timedelta(days=exclude_recent_days)
              ).isoformat()
    baseline_samples = [s for s in prior_samples
                         if s.get("sample_timestamp", "")
                            < cutoff]
    if not baseline_samples:
        return None

    scores = [Decimal(str(s.get("calibrated_score", 0)))
              for s in baseline_samples]
    mean = sum(scores) / Decimal(str(len(scores)))
    if len(scores) > 1:
        variance = (sum((sc - mean) ** 2 for sc in scores)
                     / Decimal(str(len(scores) - 1)))
        std = variance.sqrt()
    else:
        std = Decimal("0.05")
    return {
        "mean":          mean,
        "std":           std,
        "sample_count":  len(baseline_samples),
        "window_start":
            min(s.get("sample_timestamp", "")
                for s in baseline_samples),
        "window_end":
            max(s.get("sample_timestamp", "")
                for s in baseline_samples),
    }


def compute_trajectory_delta(current_score, baseline,
                                model_card):
    """
    Compare the current score to the patient's own baseline
    and label the delta significance. Production maintains
    per-indication delta-significance thresholds tuned on
    the validation cohort; the demo uses a simple
    standard-deviation-based test.
    """
    if not baseline:
        return None
    delta = current_score - baseline["mean"]
    std = baseline.get("std", Decimal("0.05"))
    if std <= Decimal("0"):
        std = Decimal("0.05")
    z_score = delta / std

    if abs(z_score) > Decimal("2.0"):
        significance = "outside_typical_variation"
    elif abs(z_score) > Decimal("1.0"):
        significance = "modest_change"
    else:
        significance = "within_typical_variation"

    return {
        "baseline_score":      baseline["mean"],
        "baseline_std":        std,
        "current_score":       current_score,
        "delta":               delta,
        "z_score":             z_score,
        "delta_significance":  significance,
        "samples_in_baseline": baseline["sample_count"],
        "baseline_window":
            f"{baseline['window_start']}_to_"
            f"{baseline['window_end']}",
    }


def build_summary_prompt(indication, score, trajectory,
                            clinical_action, template):
    """
    Assemble the prompt for Bedrock's clinician-summary
    generation. Production uses a versioned, clinical-
    operations-reviewed prompt template; the demo collapses
    to a string.
    """
    return {
        "indication":       indication,
        "score":            score,
        "trajectory":       trajectory,
        "clinical_action":  clinical_action,
        "template":         template,
    }


def package_interpretation(session_id):
    """
    For each scored indication, compute the longitudinal
    trajectory if available, look up the institutionally-
    approved clinical-action mapping, generate the clinician-
    facing summary via Bedrock, and persist the trajectory
    record.
    """
    state = capture_session_table.get(session_id)
    scores = state.get("scores", {})
    interpretations = {}

    for indication, score in scores.items():
        if score["status"] in ("NOT_ASSESSABLE",
                                "INDETERMINATE"):
            interpretations[indication] = score
            continue

        # Step 5A: longitudinal trajectory.
        prior_samples = trajectory_table.get_history(
            patient_id_hash=state["patient_id_hash"],
            indication=indication,
            window_days=TRAJECTORY_BASELINE_DAYS)

        trajectory = None
        if len(prior_samples) >= MIN_SAMPLES_FOR_TRAJECTORY:
            baseline = compute_patient_baseline(
                prior_samples=prior_samples,
                exclude_recent_days=
                    TRAJECTORY_BASELINE_EXCLUDE_DAYS)
            trajectory = compute_trajectory_delta(
                current_score=score["calibrated_score"],
                baseline=baseline,
                model_card=lookup_model_card(indication))

        # Step 5B: clinical-action mapping.
        clinical_action = lookup_clinical_action_mapping(
            indication=indication,
            category=score.get("category"),
            trajectory=trajectory,
            confound_flags=score.get("confound_flags", []))

        # Step 5C: clinician-facing summary via Bedrock.
        # In production: real bedrock_runtime.invoke_model
        # returns a StreamingBody under the "body" key, so
        # the parse is:
        #     body_text = response["body"].read().decode("utf-8")
        #     parsed = json.loads(body_text)
        # The request body for Anthropic Claude on Bedrock is
        # the Anthropic Messages API shape (messages, system,
        # max_tokens, anthropic_version, optionally tools +
        # tool_choice for structured output via tool-use). The
        # pseudocode's response_format / json_schema field in
        # the main recipe is OpenAI-style; the Anthropic
        # equivalent on Bedrock is forcing a tool call.
        summary_response = (
            bedrock_mock.render_clinician_summary(
                session_id=session_id,
                indication=indication,
                score=score,
                trajectory=trajectory,
                clinical_action=clinical_action,
                guardrail_id=BIOMARKER_GUARDRAIL_ID))
        summary_body = json.loads(summary_response["body"])
        clinician_summary = summary_body.get(
            "content",
            "Voice biomarker result available; please review "
            "the supporting features and trajectory context.")

        # Step 5D: store the trajectory record.
        trajectory_record = {
            "patient_id_hash":   state["patient_id_hash"],
            "indication":        indication,
            "sample_timestamp":  state.get("started_at"),
            "session_id":        session_id,
            "calibrated_score":  score["calibrated_score"],
            "cohort":            score["cohort"],
            "confound_flags":    score["confound_flags"],
            "recording_chain": {
                "device_class":  state.get("device_class"),
            },
            "trajectory_delta":
                (trajectory.get("delta")
                 if trajectory else None),
        }
        trajectory_table.put(_to_decimal(trajectory_record))

        interpretations[indication] = {
            "status":              "INTERPRETED",
            "score":               score,
            "trajectory":          trajectory,
            "clinical_action":     clinical_action,
            "clinician_summary":   clinician_summary,
            "summary_prompt_version": SUMMARY_PROMPT_VERSION,
            "packaged_at":         _now_iso(),
        }

    capture_session_table.update(session_id, _to_decimal({
        "interpretations":         interpretations,
        "packaging_completed_at":  _now_iso(),
        "status":                  "interpreted",
    }))

    audit_log({
        "event_type":             "INTERPRETATION_PACKAGED",
        "session_id":             session_id,
        "interpreted_count":      sum(
            1 for i in interpretations.values()
            if i.get("status") == "INTERPRETED"),
        "trajectory_count":       sum(
            1 for i in interpretations.values()
            if i.get("status") == "INTERPRETED"
               and i.get("trajectory")),
        "timestamp":              _now_iso(),
    })

    return interpretations
```

---

## Step 6: Deliver the Result to the Clinical Workflow with Explicit Indeterminate Handling and Clinician Override Capture

*The pseudocode calls this `deliver_to_workflow(...)` and `clinician_acknowledges_result(...)`. The clinician sees the biomarker result in their decision-support context, with the option to acknowledge, override, or request follow-up. The biomarker is decision support, not diagnosis; the clinician retains diagnostic authority. The result is also written to the EHR as a FHIR Observation for the longitudinal record. Skip the clinician override capture and the institution loses the feedback loop that supports post-market surveillance. Skip the EHR write and the result is invisible to the rest of the care team.*

```python
def build_fhir_observation(patient_id, indication,
                              interpretation, performed_at):
    """
    Build a FHIR Observation resource for the biomarker
    result. Production uses the institutional FHIR profile
    for voice-biomarker observations (with custom extensions
    for cohort, confound flags, indeterminate-result
    handling, and trajectory context); the demo uses a
    minimal Observation shape.
    """
    score = interpretation.get("score", {})
    return {
        "resourceType":  "Observation",
        "status":        "final",
        "category": [{
            "coding": [{
                "system":
                    "http://terminology.hl7.org/CodeSystem/"
                    "observation-category",
                "code":    "exam",
                "display": "Exam",
            }],
        }],
        "code": {
            "coding": [{
                "system":
                    "http://institutional-codes.example.com/"
                    "voice-biomarker",
                "code":    indication,
                "display":
                    f"Voice biomarker: {indication}",
            }],
        },
        "subject":       {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": performed_at,
        "valueQuantity": {
            "value":  float(score.get(
                "calibrated_score", 0)),
            "unit":   "calibrated_score_0_1",
        },
        "interpretation": [{
            "coding": [{
                "system":
                    "http://institutional-codes.example.com/"
                    "voice-biomarker-category",
                "code":    score.get("category", "unknown"),
            }],
        }],
        "extension": [
            {"url": "cohort",
             "valueString": score.get("cohort", "unknown")},
            {"url": "confound_flags",
             "valueString":
                 ",".join(score.get("confound_flags", []))},
            {"url": "model_version",
             "valueString":
                 score.get("model_version", "unknown")},
            {"url": "calibration_version",
             "valueString":
                 score.get("calibration_version",
                             "unknown")},
            {"url": "clinical_action",
             "valueString":
                 interpretation.get("clinical_action",
                                     "unknown")},
        ],
    }


def lookup_patient_id(patient_id_hash):
    """Reverse-lookup the unhashed patient ID for FHIR
    write-back. Production reads from a small ID-mapping
    service; the demo derives it from the in-memory
    demographics map."""
    for pid, demo in PATIENT_DEMOGRAPHICS.items():
        if _hash_value(pid) == patient_id_hash:
            return pid
    return None


def lookup_patient_preference(patient_id_hash):
    """Look up the patient's communication preference. The
    demo returns a default of patient portal."""
    return "patient_portal"


def generate_patient_message(interpretation,
                                guardrail_id):
    """Generate a patient-facing message via Bedrock with
    the patient-messaging Guardrails policy applied."""
    response = bedrock_mock.render_patient_message(
        session_id=interpretation.get("packaged_at",
                                        "unknown"),
        indication=interpretation.get("score", {}).get(
            "category", "unknown"),
        interpretation=interpretation,
        guardrail_id=guardrail_id)
    body = json.loads(response["body"])
    return body.get("content",
                    "Your voice check has been completed.")


def schedule_patient_communication(patient_id_hash, message,
                                       channel):
    """Schedule the patient communication. The demo just
    sends through the mock messaging system."""
    patient_comm.send(
        patient_id_hash=patient_id_hash,
        message=message,
        channel=channel)


def create_decision_support_alert(patient_id_hash,
                                      indication,
                                      interpretation,
                                      priority):
    """Create the EHR decision-support alert. The demo just
    records via the mock EHR alert surface."""
    return ehr_cds.create_alert(
        patient_id_hash=patient_id_hash,
        indication=indication,
        interpretation=interpretation,
        priority=priority)


def deliver_to_workflow(session_id):
    """
    Deliver the per-indication interpretation to the
    appropriate clinical-workflow surface based on the
    institutional clinical-action mapping. Write FHIR
    Observations for all interpreted indications.
    """
    state = capture_session_table.get(session_id)
    interpretations = state.get("interpretations", {})
    delivery_records = {}

    for indication, interpretation in interpretations.items():
        if interpretation.get("status") not in (
                "INTERPRETED", "INDETERMINATE"):
            delivery_records[indication] = {
                "delivered":  False,
                "reason":
                    interpretation.get("status",
                                         "no_result"),
            }
            continue

        # Step 6A: write the biomarker as a FHIR Observation.
        # For interpreted results we include the score; for
        # indeterminate results we still write the
        # observation with an indeterminate-status extension
        # so the longitudinal record reflects that the sample
        # was processed.
        patient_id = lookup_patient_id(
            state.get("patient_id_hash"))
        observation = build_fhir_observation(
            patient_id=patient_id,
            indication=indication,
            interpretation=interpretation,
            performed_at=state.get("started_at"))

        observation_response = healthlake.create_observation(
            datastore_id=HEALTHLAKE_DATASTORE_ID,
            observation=observation)
        # Real boto3:
        #   healthlake_client.create_resource(
        #       DatastoreId=HEALTHLAKE_DATASTORE_ID,
        #       ResourceType="Observation",
        #       Resource=json.dumps(observation))
        # The Resource parameter is a JSON-encoded string,
        # not a dict; the mock takes the dict for readability.

        # Step 6B: surface the result per the clinical-action
        # mapping. Indeterminate results route to clinician
        # review automatically; interpreted results follow
        # the institutional mapping.
        clinical_action = interpretation.get(
            "clinical_action",
            "clinician_review"
            if interpretation.get("status") == "INDETERMINATE"
            else "longitudinal_only")

        if clinical_action == "clinician_review":
            alert = create_decision_support_alert(
                patient_id_hash=state.get("patient_id_hash"),
                indication=indication,
                interpretation=interpretation,
                priority=interpretation.get("score", {}).get(
                    "category",
                    interpretation.get("status",
                                         "indeterminate")))
            delivery_records[indication] = {
                "delivered":            True,
                "delivery_kind":        "clinician_review",
                "alert_id":             alert["alert_id"],
                "fhir_observation_id":
                    observation_response["resource_id"],
            }
        elif clinical_action == "patient_communication":
            patient_message = generate_patient_message(
                interpretation=interpretation,
                guardrail_id=
                    PATIENT_MESSAGING_GUARDRAIL_ID)
            schedule_patient_communication(
                patient_id_hash=state.get("patient_id_hash"),
                message=patient_message,
                channel=lookup_patient_preference(
                    state.get("patient_id_hash")))
            delivery_records[indication] = {
                "delivered":           True,
                "delivery_kind":       "patient_communication",
                "fhir_observation_id":
                    observation_response["resource_id"],
            }
        elif clinical_action == "longitudinal_only":
            delivery_records[indication] = {
                "delivered":           True,
                "delivery_kind":       "longitudinal_only",
                "fhir_observation_id":
                    observation_response["resource_id"],
            }
        else:
            delivery_records[indication] = {
                "delivered":           True,
                "delivery_kind":       "no_action",
                "fhir_observation_id":
                    observation_response["resource_id"],
            }

        event_bus.put_events([{
            "Source":       "voice_biomarker",
            "DetailType":   "result_delivered",
            "EventBusName": BIOMARKER_EVENT_BUS_NAME,
            "Detail": json.dumps({
                "session_id":   session_id,
                "indication":   indication,
                "delivery_kind":
                    delivery_records[indication][
                        "delivery_kind"],
                "category":
                    interpretation.get("score", {}).get(
                        "category",
                        interpretation.get("status")),
            }),
        }])

        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "ResultDelivered",
            1, "Count",
            dimensions={
                "indication":    indication,
                "delivery_kind":
                    delivery_records[indication][
                        "delivery_kind"],
                "cohort":
                    interpretation.get("score", {}).get(
                        "cohort", "unknown"),
            })

    capture_session_table.update(session_id, _to_decimal({
        "delivery_records":      delivery_records,
        "delivered_at":          _now_iso(),
        "status":                "delivered",
    }))

    audit_log({
        "event_type":      "RESULTS_DELIVERED",
        "session_id":      session_id,
        "delivery_count":  len(delivery_records),
        "delivered_count": sum(
            1 for d in delivery_records.values()
            if d.get("delivered")),
        "timestamp":       _now_iso(),
    })

    return delivery_records


def clinician_acknowledges_result(session_id, clinician_id,
                                     indication,
                                     action_taken,
                                     feedback=None):
    """
    Capture the clinician's response to a delivered
    biomarker result. The agreement-with-biomarker flag
    feeds the post-market surveillance dashboard; persistent
    disagreement on a per-cohort basis triggers a re-
    validation review.
    """
    state = capture_session_table.get(session_id)
    interpretations = state.get("interpretations", {})
    interpretation = interpretations.get(indication, {})

    expected_action = interpretation.get("clinical_action")
    agreement = (action_taken == expected_action)

    clinician_feedback_table.put(_to_decimal({
        "session_id":        session_id,
        "indication":        indication,
        "clinician_id":      clinician_id,
        "action_taken":      action_taken,
        "expected_action":   expected_action,
        "agreement_with_biomarker": agreement,
        "feedback":          feedback,
        "responded_at":      _now_iso(),
        "cohort":
            interpretation.get("score", {}).get(
                "cohort", "unknown"),
    }))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ClinicianFeedbackAgreement",
        1 if agreement else 0, "Count",
        dimensions={
            "indication": indication,
            "cohort":
                interpretation.get("score", {}).get(
                    "cohort", "unknown"),
            "agreement":
                "agree" if agreement else "disagree",
        })

    event_bus.put_events([{
        "Source":       "voice_biomarker",
        "DetailType":   "clinician_feedback_captured",
        "EventBusName": BIOMARKER_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":  session_id,
            "indication":  indication,
            "agreement":   agreement,
        }),
    }])

    audit_log({
        "event_type":       "CLINICIAN_FEEDBACK",
        "session_id":       session_id,
        "indication":       indication,
        "agreement":        agreement,
        "timestamp":        _now_iso(),
    })

    return {"agreement": agreement,
            "expected_action": expected_action,
            "action_taken":    action_taken}
```

---

## Step 7: Audit, Retain Audio per Consent, and Feed Cohort-Stratified Post-Market Surveillance

*The pseudocode calls this `audit_and_surveillance(...)`. Every sample produces a durable audit record with the score, the cohort context, the confound flags, and the clinical-action linkage. Audio is retained per the consent terms and then deleted; feature vectors are retained longer for surveillance and re-validation. Cohort-stratified metrics feed the post-market surveillance dashboards that monitor the deployed biomarker's performance against ground-truth clinical outcomes. Skip the audio retention enforcement and the institution silently accumulates biometric data beyond its consent commitment. Skip the cohort-stratified surveillance and per-cohort drift surfaces only through complaints.*

```python
def lookup_audio_retention(consent_id, jurisdiction):
    """
    Look up the audio retention window for this consent.
    Production keys retention to the consent record's terms;
    the demo defaults to the protocol-level retention.
    """
    # In production: read the consent record and apply its
    # retention term, with a per-jurisdiction override for
    # BIPA-equivalent states that may require shorter
    # retention.
    base_hours = 48
    if jurisdiction in BIOMETRIC_DATA_LAW_STATES:
        base_hours = 24
    return {"hours": base_hours}


def schedule_audio_deletion(audio_refs, delete_after):
    """
    Schedule audio deletion per the consent retention window.
    Production uses an S3 lifecycle policy keyed on object
    tags or prefixes; the demo records the intended deletion
    in the audit log and immediately removes the mock object
    when run synchronously to demonstrate the discipline.
    """
    for audio_ref in audio_refs:
        audit_log({
            "event_type":       "AUDIO_DELETION_SCHEDULED",
            "audio_ref_hash":   _hash_value(audio_ref),
            "delete_after_hours":
                delete_after.get("hours"),
            "timestamp":        _now_iso(),
        })
        # Production uses a lifecycle policy; the demo
        # immediately deletes from the mock S3 to demonstrate
        # the discipline. In the real path, the deletion
        # executes asynchronously.
        if audio_ref.startswith("s3://"):
            without_scheme = audio_ref[5:]
            slash = without_scheme.find("/")
            if slash > 0:
                bucket = without_scheme[:slash]
                key = without_scheme[slash + 1:]
                s3_store.delete_object(
                    bucket, key,
                    reason="consent_retention_expired")


def audit_and_surveillance(session_id, patient_age_band=None):
    """
    Produce the durable audit record, schedule audio
    deletion per consent, emit per-cohort surveillance
    metrics, and emit the session-audited lifecycle event.
    """
    state = capture_session_table.get(session_id)
    interpretations = state.get("interpretations", {})

    audit_record = {
        "session_id":       session_id,
        "patient_id_hash":
            state.get("patient_id_hash"),
        "captured_at":      state.get("started_at"),
        "capture_completed_at":
            state.get("capture_completed_at"),
        "scoring_completed_at":
            state.get("scoring_completed_at"),
        "delivered_at":     state.get("delivered_at"),
        "indication":       state.get("indication"),
        "indications_attempted":
            list(interpretations.keys()),
        "per_indication_outcomes": {
            indication: {
                "status":             interp.get("status"),
                "category":
                    interp.get("score", {}).get(
                        "category"),
                "cohort":
                    interp.get("score", {}).get("cohort"),
                "clinical_action":
                    interp.get("clinical_action"),
                "confound_flags":
                    interp.get("score", {}).get(
                        "confound_flags"),
                "model_version":
                    interp.get("score", {}).get(
                        "model_version"),
                "calibration_version":
                    interp.get("score", {}).get(
                        "calibration_version"),
                "trajectory_significance":
                    (interp.get("trajectory") or {}).get(
                        "delta_significance")
                    if interp.get("trajectory") else None,
            }
            for indication, interp in interpretations.items()
        },
        "recording_chain_metadata": {
            "device_class":     state.get("device_class"),
            "min_codec_bandwidth_hz":
                determine_codec_bandwidth(state),
        },
        "consent_id":        state.get("consent_id"),
        "protocol_version":  state.get("protocol_version"),
        "feature_pipeline_version":
            state.get("feature_pipeline_version"),
        "eligibility_rules_version":
            state.get("eligibility_rules_version"),
        "summary_prompt_version":   SUMMARY_PROMPT_VERSION,
    }

    audit_object = s3_store.put_object(
        bucket=AUDIT_ARCHIVE_BUCKET,
        key=(f"audit/"
             f"{datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
             f"/{session_id}.json"),
        body=json.dumps(audit_record,
                          default=str).encode("utf-8"),
        metadata={
            "session_id":  session_id,
            "indication":  state.get("indication"),
        })

    # Step 7A: schedule audio deletion per consent terms.
    audio_refs = [seg.get("audio_ref") for seg in
                   state.get("captured_segments", [])
                   if seg.get("audio_ref")]
    if audio_refs:
        schedule_audio_deletion(
            audio_refs=audio_refs,
            delete_after=lookup_audio_retention(
                consent_id=state.get("consent_id"),
                jurisdiction=state.get("jurisdiction")))

    # Step 7B: per-cohort surveillance metrics.
    for indication, outcome in audit_record[
            "per_indication_outcomes"].items():
        cohort_dims = {
            "indication":   indication,
            "cohort":       outcome.get("cohort", "unknown"),
            "device_class": state.get(
                "device_class", "unknown"),
            "outcome_status":
                outcome.get("status", "unknown"),
        }
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "PerOutcomeStatus",
            1, "Count", dimensions=cohort_dims)
        if outcome.get("status") == "INTERPRETED" \
                and outcome.get("category"):
            cloudwatch.put_metric(
                CLOUDWATCH_NAMESPACE,
                "BiomarkerCategoryRate", 1, "Count",
                dimensions={**cohort_dims,
                             "category":
                                 outcome.get("category")})

    # Step 7C: emit session-audited lifecycle event for
    # downstream Model Monitor and Clarify consumers.
    event_bus.put_events([{
        "Source":       "voice_biomarker",
        "DetailType":   "session_audited",
        "EventBusName": BIOMARKER_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":      session_id,
            "audit_archive_ref":
                audit_object["uri"],
            "audited_at":      _now_iso(),
        }),
    }])

    capture_session_table.update(session_id, _to_decimal({
        "audit_archive_ref":  audit_object["uri"],
        "audited_at":         _now_iso(),
        "status":             "audited",
    }))

    audit_log({
        "event_type":              "SESSION_AUDITED",
        "session_id":              session_id,
        "audit_archive_ref":       audit_object["uri"],
        "audio_refs_deleted":      len(audio_refs),
        "indication_count":
            len(audit_record["per_indication_outcomes"]),
        "timestamp":               _now_iso(),
    })

    return audit_record
```

---

## Putting It All Together

The pipeline ties together as a top-level handler that simulates a single end-to-end voice-biomarker session flowing through the seven stages. In a Lambda-and-Step-Functions deployment, the capture stage runs in response to the device-side capture-completion event and the post-capture stages run as a Step Functions state machine; the demo orchestrates them inline so you can see the full sequence.

```python
def run_biomarker_pipeline(patient_id, indication,
                              capture_context,
                              candidate_indications=None,
                              clinician_id=None,
                              clinician_action=None,
                              session_id_hint=None):
    """
    Drive a single voice-biomarker session end-to-end through
    all seven pipeline stages. Production splits this across
    multiple Lambdas with Step Functions orchestration; the
    demo collapses to a single function for readability.
    """
    candidate_indications = candidate_indications \
        or [indication]

    # Stage 1: capture audio with consent and quality gates.
    capture_result = capture_initiated(
        patient_id=patient_id,
        indication=indication,
        capture_context=capture_context,
        session_id_hint=session_id_hint)

    if capture_result["status"] != "CAPTURED":
        return {"status": capture_result["status"],
                "stage":  "capture",
                "details": capture_result}

    session_id = capture_result["session_id"]

    # Stage 2: feature extraction (acoustic, embeddings,
    # linguistic where applicable).
    feature_result = extract_features(session_id)

    # Stage 3: per-indication eligibility check.
    eligibility = check_eligibility(
        session_id=session_id,
        candidate_indications=candidate_indications,
        patient_id=patient_id)

    # Stage 4: per-indication scoring with per-cohort
    # calibration and indeterminate handling.
    scores = score_biomarkers(session_id)

    # Stage 5: trajectory + clinician summary packaging.
    interpretations = package_interpretation(session_id)

    # Stage 6: deliver to clinical workflow.
    delivery_records = deliver_to_workflow(session_id)

    # Stage 6 (continued): clinician acknowledgement, if
    # provided. In production this is a separate event later
    # in time; the demo simulates inline.
    feedback_records = {}
    if clinician_id and clinician_action:
        for indication_key, action in clinician_action.items():
            if indication_key in interpretations:
                feedback_records[indication_key] = (
                    clinician_acknowledges_result(
                        session_id=session_id,
                        clinician_id=clinician_id,
                        indication=indication_key,
                        action_taken=action,
                        feedback="demo_feedback"))

    # Stage 7: audit + cohort metrics.
    audit_record = audit_and_surveillance(
        session_id=session_id)

    return {
        "status":            "COMPLETE",
        "session_id":        session_id,
        "capture_result":    capture_result,
        "feature_result":    {
            "feature_archive_ref":
                feature_result.get("feature_archive_ref"),
        },
        "eligibility":       eligibility,
        "scores":            scores,
        "interpretations":   interpretations,
        "delivery_records":  delivery_records,
        "feedback_records":  feedback_records,
        "audit_archive_ref": audit_record.get(
            "audit_archive_ref")
            or f"audit/{session_id}.json",
    }
```

The demo runner wires up the mocks with fixture data for two end-to-end scenarios.

```python
def run_demo():
    """
    Run two end-to-end scenarios that exercise the main paths
    through the voice-biomarker pipeline:
      1. Carl (68-year-old male, English, clinic-grade
         microphone) submits a Parkinson's-screening sample
         as part of a longitudinal monitoring program.
         He has prior baseline samples; the trajectory is
         flagged as outside_typical_variation, which routes
         to clinician review.
      2. Marcus (58-year-old male, Spanish, smartphone
         capture) submits a respiratory-monitoring cough
         sample. The result indicates an asthma pattern,
         routing to clinician review per the institutional
         clinical-action mapping.
    """
    # pylint: disable=global-statement
    global sagemaker_mock, transcribe_mock
    global comprehend_mock, bedrock_mock
    global ACOUSTIC_FEATURE_FIXTURES, EMBEDDING_FIXTURES
    global LINGUISTIC_FEATURE_FIXTURES
    global CURRENT_CAPTURE_FIXTURE
    global CLINICAL_EVENTS_BY_PATIENT

    # ---- Scenario 1: Carl, Parkinson's screening ----
    session_id_1 = "vbm-demo-carl-2026-05-23"
    capture_fixture_1 = {
        "sustained_vowel_a": {
            "session_id":      session_id_1,
            "duration":        12,
            "quality_score":   Decimal("0.88"),
            "sample_rate":     44100,
            "codec":           "PCM_16",
            "snr_db":          Decimal("28.0"),
            "clipping_percent": Decimal("0.0"),
        },
        "read_passage": {
            "session_id":      session_id_1,
            "duration":        45,
            "quality_score":   Decimal("0.85"),
            "sample_rate":     44100,
            "codec":           "PCM_16",
            "snr_db":          Decimal("27.0"),
            "clipping_percent": Decimal("0.1"),
        },
    }
    acoustic_fixture_1 = {
        f"s3://{AUDIO_BUCKET}/{session_id_1}/"
        f"sustained_vowel_a.wav": {
            "jitter_local":             Decimal("0.018"),
            "shimmer_local":            Decimal("0.092"),
            "harmonic_to_noise_ratio":  Decimal("14.2"),
            "f0_mean":                  Decimal("132.0"),
            "f0_std":                   Decimal("18.4"),
            "spectral_tilt":            Decimal("-12.1"),
        },
        f"s3://{AUDIO_BUCKET}/{session_id_1}/"
        f"read_passage.wav": {
            "articulation_rate":        Decimal("4.3"),
            "pause_distribution":       Decimal("0.21"),
            "pitch_range":              Decimal("51.0"),
            "voice_onset_time":         Decimal("0.062"),
            "formant_trajectories":     Decimal("0.71"),
            "mfcc_stats":               Decimal("0.45"),
        },
    }
    embedding_fixture_1 = {
        (f"s3://{AUDIO_BUCKET}/{session_id_1}/"
         f"sustained_vowel_a.wav",
         "wavlm-base-plus-2024"):
            [Decimal("0.12"), Decimal("0.35"),
             Decimal("-0.08"), Decimal("0.21"),
             Decimal("0.04"), Decimal("-0.18"),
             Decimal("0.32"), Decimal("0.05")],
        (f"s3://{AUDIO_BUCKET}/{session_id_1}/"
         f"read_passage.wav",
         "wavlm-base-plus-2024"):
            [Decimal("0.18"), Decimal("0.31"),
             Decimal("-0.04"), Decimal("0.27"),
             Decimal("0.08"), Decimal("-0.14"),
             Decimal("0.29"), Decimal("0.11")],
    }
    score_fixture_1 = {
        ("parkinsons_screening", session_id_1): {
            "raw_score":     Decimal("0.71"),
            "feature_attribution": {
                "top_features": [
                    {"feature":
                         "harmonic_to_noise_ratio_sustained_a",
                     "patient_value_z": Decimal("-1.8"),
                     "cohort_baseline_mean": Decimal("21.4"),
                     "patient_value": Decimal("14.2")},
                    {"feature": "pitch_range_passage",
                     "patient_value_z": Decimal("-1.4"),
                     "cohort_baseline_mean": Decimal("78.2"),
                     "patient_value": Decimal("51.0")},
                    {"feature":
                         "articulation_rate_passage",
                     "patient_value_z": Decimal("-1.1"),
                     "cohort_baseline_mean": Decimal("5.1"),
                     "patient_value": Decimal("4.3")},
                ],
            },
            "model_version": "parkinsons_v3.2.1",
        },
    }
    summary_fixture_1 = {
        (session_id_1, "parkinsons_screening"): {
            "content":
                "Voice features show acoustic patterns "
                "associated with Parkinsonian speech: "
                "reduced harmonic-to-noise ratio, narrowed "
                "pitch range, and slowed articulation rate. "
                "The patient's score has increased "
                "meaningfully relative to their own "
                "baseline. This is a decision-support "
                "signal, not a diagnosis. Consider "
                "movement-disorder workup if other clinical "
                "signs warrant.",
            "guardrail_action": "NONE",
        },
    }

    # Carl has a baseline trajectory: four prior samples
    # over the past year with consistent low-signal scores.
    baseline_dates = [
        (datetime.now(timezone.utc)
         - timedelta(days=offset)).isoformat()
        for offset in (380, 290, 200, 95)
    ]
    for ts, prior_score in zip(
            baseline_dates,
            [Decimal("0.39"), Decimal("0.42"),
             Decimal("0.40"), Decimal("0.43")]):
        trajectory_table.put(_to_decimal({
            "patient_id_hash":   _hash_value("pt-44219"),
            "indication":        "parkinsons_screening",
            "sample_timestamp":  ts,
            "session_id":        f"prior-{ts[:10]}",
            "calibrated_score":  prior_score,
            "cohort":
                "65-74_male_english_clinic_recording",
            "confound_flags":    [],
            "recording_chain":   {
                "device_class":
                    "clinic_dedicated_microphone"},
            "trajectory_delta":  None,
        }))

    # ---- Scenario 2: Marcus, respiratory monitoring ----
    session_id_2 = "vbm-demo-marcus-2026-05-23"
    capture_fixture_2 = {
        "voluntary_cough": {
            "session_id":      session_id_2,
            "duration":        8,
            "quality_score":   Decimal("0.78"),
            "sample_rate":     16000,
            "codec":           "OPUS",
            "snr_db":          Decimal("18.5"),
            "clipping_percent": Decimal("0.4"),
        },
    }
    acoustic_fixture_2 = {
        f"s3://{AUDIO_BUCKET}/{session_id_2}/"
        f"voluntary_cough.wav": {
            "cough_event_count":     Decimal("3.0"),
            "spectral_centroid":     Decimal("1840.0"),
            "burst_energy_ratio":    Decimal("0.62"),
            "post_burst_decay":      Decimal("0.18"),
        },
    }
    score_fixture_2 = {
        ("respiratory_monitoring", session_id_2): {
            "raw_score":     Decimal("0.68"),
            "feature_attribution": {
                "top_features": [
                    {"feature":     "spectral_centroid",
                     "patient_value_z": Decimal("1.5"),
                     "cohort_baseline_mean": Decimal("1420"),
                     "patient_value": Decimal("1840")},
                    {"feature":     "burst_energy_ratio",
                     "patient_value_z": Decimal("1.2"),
                     "cohort_baseline_mean": Decimal("0.45"),
                     "patient_value": Decimal("0.62")},
                ],
            },
            "model_version": "cough_classifier_v2.1.0",
        },
    }
    summary_fixture_2 = {
        (session_id_2, "respiratory_monitoring"): {
            "content":
                "Cough acoustic features are consistent "
                "with an asthma-pattern classification. "
                "This is a decision-support signal, not a "
                "diagnosis. Consider review of the patient's "
                "asthma management and current medication "
                "adherence.",
            "guardrail_action": "NONE",
        },
    }

    # Wire up the mocks for both scenarios.
    sagemaker_mock = MockSageMakerRuntime({
        **score_fixture_1,
        **score_fixture_2,
    })
    transcribe_mock = MockTranscribeMedical({})
    comprehend_mock = MockComprehendMedical({})
    bedrock_mock = MockBedrock({
        **summary_fixture_1,
        **summary_fixture_2,
    })

    # ---- Run scenario 1 ----
    print("\n=== Scenario 1: Carl, Parkinson's Screening ===")
    ACOUSTIC_FEATURE_FIXTURES = acoustic_fixture_1
    EMBEDDING_FIXTURES = embedding_fixture_1
    LINGUISTIC_FEATURE_FIXTURES = {}
    CURRENT_CAPTURE_FIXTURE = capture_fixture_1

    result_1 = run_biomarker_pipeline(
        patient_id="pt-44219",
        indication="parkinsons_screening",
        capture_context={
            "device_class":
                "clinic_dedicated_microphone",
            "language":     "en-US",
            "environment":  "exam_room",
        },
        candidate_indications=["parkinsons_screening"],
        clinician_id="clinician-patel",
        clinician_action={
            "parkinsons_screening": "clinician_review"},
        session_id_hint=session_id_1)
    print(json.dumps(result_1, default=str, indent=2))

    # ---- Run scenario 2 ----
    print("\n=== Scenario 2: Marcus, Respiratory Monitoring ===")
    ACOUSTIC_FEATURE_FIXTURES = acoustic_fixture_2
    EMBEDDING_FIXTURES = {}
    LINGUISTIC_FEATURE_FIXTURES = {}
    CURRENT_CAPTURE_FIXTURE = capture_fixture_2

    result_2 = run_biomarker_pipeline(
        patient_id="pt-77310",
        indication="respiratory_monitoring",
        capture_context={
            "device_class":
                "smartphone_standard",
            "language":     "es-US",
            "environment":  "home",
        },
        candidate_indications=["respiratory_monitoring"],
        clinician_id="clinician-vega",
        clinician_action={
            "respiratory_monitoring": "clinician_review"},
        session_id_hint=session_id_2)
    print(json.dumps(result_2, default=str, indent=2))


if __name__ == "__main__":
    run_demo()
```

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right audit records, but the distance between it and a real voice-biomarker pipeline running in clinicians' workflows is significant. Here is where that distance lives.

**Real audio capture from a clinical device or app.** The demo's `capture_audio_with_quality_assessment` reads from in-memory fixtures. Production captures audio from a clinic-grade dedicated microphone with known frequency-response characteristics, a smartphone app with a controlled-protocol UX, a telehealth platform's audio path with bandwidth-aware feature handling, or a kiosk-based capture device for at-home longitudinal monitoring. The capture-device choice has substantial accuracy implications: the same patient saying the same words into different devices produces measurably different feature vectors, which the model's validation envelope must account for. Per-device validation work is its own multi-week effort after device selection.

**Real SageMaker endpoint hosting per indication.** The demo's `MockSageMakerRuntime` returns canned scores. Production hosts each validated indication as its own SageMaker endpoint (or as one model behind a multi-model endpoint when several related indications share an underlying feature pipeline) with real-time invocation for in-encounter scoring and asynchronous invocation for longitudinal-monitoring batches. The endpoint configuration is per-model (instance class, autoscaling policy, KMS key for inference data, VPC configuration); the deployment uses SageMaker model packages or BYO containers depending on whether the model is institutional, vendor-supplied, or built on a SageMaker JumpStart model. Production additionally configures SageMaker Model Monitor jobs that compare production inference against the training-time baseline for data-quality drift and model-quality drift, plus SageMaker Clarify jobs that produce per-cohort attribution and bias reports on a scheduled cadence. Together they provide the per-cohort surveillance the regulatory and clinical-quality posture requires.

**Real Bedrock invocation, prompt management, and inference profile.** The demo's `MockBedrock` uses fixture lookups. Production calls `bedrock_runtime.invoke_model` with `modelId=BEDROCK_SUMMARY_PROFILE_ARN` (the inference profile ARN is what you pass for cross-region inference and per-profile rate limits). The `body` parameter is the model-specific JSON request: for Anthropic Claude on Bedrock, that is a `messages` API request with a `system` prompt (versioned, owned by clinical operations), a `tools` field that declares the structured-output schema as a tool definition (this is how you enforce JSON output), and the user message containing the structured biomarker output, the cohort context, the trajectory, and the institutional template. The `guardrailIdentifier` and `guardrailVersion` parameters apply the runtime Guardrails policy. Patient-facing messages use a separate, more conservative Guardrails policy than clinician-facing summaries; the patient policy's contextual-grounding check ensures the patient communication does not over-claim what the biomarker supports.

**Real Bedrock Guardrails configuration.** The demo references guardrail IDs but does not invoke them. Production configures two Guardrails policies: one for clinician-facing summaries (filters clinical-advice categories and harmful-content categories) and one for patient-facing messages (additionally enforces contextual-grounding against the structured biomarker output, more conservative content filters, and an explicit "decision-support, not diagnosis" framing requirement). Guardrails is a defense-in-depth layer; the system-prompt constraints in the summary-rendering prompt and the runtime Guardrails filter operate together.

**Real Transcribe Medical and Comprehend Medical wiring.** The demo's mocks return fixture transcripts and entities. Production calls `transcribe_client.start_medical_transcription_job` for the linguistic-feature pipeline (with the appropriate medical specialty and an institutional custom vocabulary) and `comprehend_medical.detect_entities_v2` for the clinical-entity extraction from spontaneous-speech transcripts. The transcription step is asynchronous and adds latency; for cognitive-decline biomarkers that require linguistic features, the latency budget for the overall scoring path includes the transcription time. For real-time use cases that cannot tolerate the transcription latency, the linguistic-feature pipeline runs as a separate asynchronous track with its own SageMaker endpoint that produces a delayed cognitive-biomarker score.

**Per-indication validation evidence and ongoing cohort expansion.** The demo's `MODEL_CARDS` is a tiny in-memory dict. Production maintains validated per-indication models with the cohort, evidence, and regulatory work that implies. For most institutions, this means selecting commercial vendors with FDA clearances or strong published evidence (cough analysis, Parkinson's screening) rather than building from scratch. Building a clinically-defensible voice biomarker for a single indication is a multi-year, multi-million-dollar undertaking requiring clinical-research staff, IRB-approved cohort development, and biostatistical expertise. The architectural pattern in this demo supports either approach: third-party model integration through SageMaker endpoint or vendor API, or institutionally-built models hosted on SageMaker endpoints.

**FDA SaMD strategy and ongoing post-market surveillance.** The demo emits surveillance metrics to CloudWatch but does not implement the regulatory-reporting workflow. Production's surveillance program includes FDA-compliant post-market surveillance for any cleared SaMD devices: ongoing per-cohort accuracy tracking against ground-truth clinical outcomes, drift-detection alarms with re-validation triggers, adverse-event reporting workflows, and the institutional clinical-quality review meetings that act on the surveillance findings. Plan a quarterly per-indication clinical-quality review meeting at minimum.

**Per-cohort calibration with cohort-specific thresholds.** The demo's `CALIBRATION_LOOKUP` is a tiny in-memory dict. Production maintains per-indication, per-cohort calibration entries in DynamoDB keyed on `(indication, cohort, calibration_version)` with the calibration curve, the threshold map, the cohort size, the calibration uncertainty, and the validation date. Cohort definitions are per-indication and per-validation-study. Per-cohort accuracy must meet the institutional threshold for that cohort before the biomarker is deployed to that cohort; cohorts where per-cohort performance is inadequate either get the biomarker disabled or get it deployed with explicit caveats.

**Per-Lambda IAM roles.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda (capture-ingest, feature-extraction, eligibility-check, scoring, calibration, packaging, EHR write-back, audit-and-surveillance), each scoped to the specific resource ARNs the Lambda touches. The scoring role has scoped SageMaker invoke-endpoint rights pinned to the validated-indication endpoints only. The packaging role has scoped Bedrock invocation rights pinned to the summary-rendering model and inference profile. The EHR-handoff role has scoped Secrets Manager read for the EHR credentials and HealthLake create-resource rights only. Wildcard actions and resources will fail any serious IAM review.

**Real DynamoDB wiring with KMS and PITR.** The mocks in the demo are dictionaries; production is DynamoDB tables (capture-session-state with TTL on idle sessions, trajectory partitioned by patient-id-hash with sort key on sample-timestamp, calibration partitioned by indication with sort key on cohort, model-card partitioned by indication with sort key on model-version, clinician-feedback partitioned by session-id with sort key on indication) with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery enabled, and DynamoDB Streams emitting change events to the audit and analytics consumers.

**Customer-managed KMS keys, per data class.** Every PHI-bearing and biometric-bearing resource (audio bucket, feature-vector bucket, audit-archive bucket, capture-session table, trajectory table, calibration table, Lambda environment variables, CloudWatch Logs, Secrets Manager) uses customer-managed KMS keys with rotation enabled. Different keys per data class for blast-radius containment: a compromised audio-bucket key does not compromise the audit archive. Voice samples and feature vectors use separate keys because feature-vector retention is typically longer than audio retention. Per-state biometric-data law sometimes requires distinct cryptographic isolation; the architecture supports per-jurisdiction key management where required.

**S3 lifecycle and Object Lock.** The audio bucket has a brief-retention lifecycle bound to consent terms (often hours to days; longer with explicit consent for longitudinal-monitoring scenarios). The feature-vector bucket retains for the surveillance and re-validation window. The audit archive uses Object Lock in compliance mode with retention sized to the longer of HIPAA's six-year minimum, biometric-data law retention requirements, state medical-records-retention rules, and the institutional regulatory floor. Lifecycle transitions move older audit-archive objects to S3 Glacier Deep Archive for cost optimization.

**VPC and VPC endpoints.** Lambdas that call back-office APIs (EHR FHIR write-back, patient-portal release) run in a VPC with private subnets that route traffic through a controlled egress path. VPC endpoints for S3, DynamoDB, KMS, Secrets Manager, EventBridge, CloudWatch Logs, SageMaker Runtime, Transcribe, Comprehend Medical, Bedrock, HealthLake keep AWS-internal traffic on the AWS backbone. Endpoint policies pin access to the specific resources the pipeline uses. SageMaker endpoints in VPC mode where the chosen model container supports it.

**Step Functions orchestration of the multi-stage scoring pipeline.** The demo orchestrates the post-capture stages inline. Production runs them as an AWS Step Functions state machine triggered by the `sample_captured` event: feature extraction, eligibility check, per-indication scoring (parallel over the candidate indications), calibration, packaging, and delivery. Step Functions provides the durable retry semantics: if SageMaker throttles, retry with exponential backoff; if Bedrock fails, route to a DLQ with a fall-back to a templated summary; if the EHR handoff fails, hold the result in a queue with manual replay capability. Each Lambda has its own IAM role, error handling, retries, and DLQs.

**Biometric-data deletion-on-request workflow.** The demo's `schedule_audio_deletion` deletes the audio object. Production maintains a biometric-data deletion-on-request workflow that handles audio, feature vectors, trajectory entries, and the long-term audit record per the patient's request. The workflow is more involved than standard PHI deletion because feature vectors derived from voice may persist after the source audio is deleted, and the question of whether the feature vectors are themselves biometric data is a privacy-officer judgment call. Per-state biometric-data law (Illinois BIPA, Texas, Washington and others) determines the required deletion timeline and the required disclosure-accounting back to the requester.

**Recording-chain validation gates per device class.** The demo's eligibility check trusts the device-class label. Production validates each supported device class against the per-indication validation envelope before the device class is added to the supported-devices list. New device classes (a new smartphone model, a new telehealth platform's audio codec, a new clinic-deployed microphone) require per-cohort validation work before they are eligible to feed the biomarker pipeline.

**Per-cohort accuracy and adoption monitoring with launch gates.** Per-cohort metrics (per-language, per-specialty, per-clinician, per-patient-cohort, per-audio-quality-band, per-room) are a launch gate, not a post-launch dashboard. Production defines cohort axes, per-cohort minimum sample sizes, per-cohort threshold metrics (calibrated AUC, sensitivity-at-threshold, specificity-at-threshold, indeterminate-result rate, clinician-feedback agreement rate). Launch is gated on every cohort meeting the threshold, not on the institution-wide average. Disparity alerts trigger reviews; sustained disparity triggers product-level remediation including (potentially) disabling the indication for cohorts where it underperforms.

**Clinician-feedback capture loop with closed-loop surveillance.** The demo's `clinician_acknowledges_result` records the agreement-with-biomarker flag. Production runs the closed loop: the clinician's response is the ground-truth signal for per-cohort surveillance, persistent disagreement on a per-cohort basis triggers a re-validation review, the institutional clinical-quality team reviews disagreement patterns on a cadence, and findings feed into model-card updates and clinical-action-mapping updates. The surveillance dashboard segments agreement rates by cohort axes and flags drift early.

**Layered consent infrastructure with biometric-data governance.** The demo's `capture_consent` simulates a granted consent. Production deploys a layered consent program: per-jurisdiction disclosure language reviewed by legal, per-indication retention terms reviewed by the privacy officer, an explicit-acknowledgment flow for BIPA-equivalent jurisdictions, a right-to-deletion workflow with disclosure-accounting, and per-patient consent versioning so a patient who consented under an earlier disclosure can be re-prompted when the disclosure changes materially. The institutional biometric-data governance policy applies explicitly to voice samples; the privacy-officer review is upstream of any production deployment.

**Per-indication clinical-action mapping with named clinical-quality leadership.** The demo's `CLINICAL_ACTION_MAP` is a static dict. Production owns the mapping in a clinical-quality-leadership-reviewed table with explicit per-indication, per-category, per-trajectory-significance, per-confound-flag combinations. The mapping is updated based on post-market surveillance findings, clinician feedback patterns, and institutional clinical-quality review outcomes. Without named ownership, the mapping drifts and the resulting clinical actions become inconsistent.

**Idempotency and retry semantics.** The demo's session-id is generated freshly each run. Production uses a conditional DynamoDB write keyed on `(patient_id_hash, indication, capture_initiated_at)` so a duplicate capture-completion event is rejected with `ConditionalCheckFailedException` rather than producing two sessions. The HealthLake Observation create uses an idempotency key built from `(session_id, indication)` so a retry does not produce two Observation resources. Configure DLQs on every Lambda; alarm on DLQ depth.

**Performance under burst load.** Voice-biomarker volume has strong patterns: morning clinic spikes, longitudinal-monitoring program scheduled batches, weekly cohort-collection campaigns. The demo runs sessions one at a time. Production holds the latency budget under burst: SageMaker endpoint quotas, Bedrock model invocation quotas, Transcribe job concurrency quotas, and downstream EHR API rate limits all need provisioning headroom and burst-capacity planning. Reserve concurrency where the latency-sensitive Lambdas would otherwise be starved. Load test against realistic peak profiles before launch.

**Disaster recovery and degraded-mode operation.** The demo assumes happy-path execution. Production tests the failure modes in staging quarterly: SageMaker endpoint unavailable (fall back to indeterminate result with explicit "scoring service unavailable" reason), Bedrock unavailable (fall back to a templated clinician summary; the audit captures the fallback), Transcribe Medical unavailable (skip linguistic-feature path; surface "linguistic features not available" indicator), HealthLake unavailable (hold the FHIR write in a queue with manual replay), EHR alert API unreachable (hold the alert in a queue with retry). The biomarker is decision support; its absence does not block clinical care.

**Vendor evaluation rigor for build-vs-buy decisions.** Most institutions deploying voice biomarkers should be buying validated commercial models for the indications where commercial validation exists, not building from scratch. The demo's pipeline is the architecture for the build-or-integrate path. The vendor evaluation program runs in parallel: per-cohort accuracy benchmarking against held-out audio, FDA-clearance review, EHR integration depth, in-room or smartphone device support, reference checks with comparable institutions. Even institutions that buy still benefit from understanding the architecture deeply for vendor evaluation, contract negotiation, and operational ownership.

**Audit log retention with regulatory-aware lifecycle.** The demo's audit-archive S3 bucket is created without Object Lock in the mock. Production enables Object Lock in compliance mode with retention sized to the longer of HIPAA's six-year minimum, state biometric-data-law retention requirements (which can be longer than HIPAA's), state medical-records-retention rules, the FDA's SaMD post-market surveillance retention requirements where applicable, and the institutional regulatory floor. Legal hold capabilities (suspending deletion for specific patients during litigation) are configurable.

**Cost monitoring per indication, per cohort, and per device class.** Different indications have very different per-sample costs (a Parkinson's-screening sample with two tasks plus pretrained embeddings is structurally different from a cough sample with engineered features only). Per-indication, per-cohort, per-device-class cost dashboards let operations identify outliers and tune accordingly.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the eligibility-check logic with edge cases (multi-jurisdiction patients, partially-eligible cohorts, unsupported device classes), unit tests for the per-cohort calibration application, unit tests for the indeterminate-result threshold, integration tests against test buckets and tables, and end-to-end tests that simulate full session flows including the not-assessable path, the indeterminate path, the per-cohort-calibration-missing path, and the multi-language paths. Never use real patient voice samples in test fixtures; voice samples are biometric and PHI-bearing data with non-trivial governance implications. Use synthetic patients (Synthea-style) and TTS-generated audio with known ground truth, or open evaluation datasets (mPower, Coswara, DementiaBank) with their licensing terms reviewed before integration.

**Observability beyond the metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-stage investigation. Production runs CloudWatch Logs Insights queries that join across the capture-ingest logs, the feature-extraction logs, the eligibility-check logs, the scoring logs, the packaging logs, and the EHR-handoff logs by session_id. AWS X-Ray traces show the latency contribution of each stage. When a single session goes wrong (an indeterminate result the clinician disputes, a per-cohort drift alarm firing, an EHR handoff stalling), the on-call engineer needs to reconstruct the full trace in seconds.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 10.8: Voice Biomarker Detection](chapter10.08-voice-biomarker-detection) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard. See [Recipe 10.6: Speech-to-Text for Telehealth Documentation](chapter10.06-speech-to-text-telehealth-documentation) for the per-cohort-accuracy discipline that transfers directly to per-cohort voice-biomarker validation. See [Recipe 10.7: Ambient Clinical Documentation](chapter10.07-ambient-clinical-documentation) for the in-room audio infrastructure that voice-biomarker workflows can share when the audio fidelity is preserved appropriately.*
