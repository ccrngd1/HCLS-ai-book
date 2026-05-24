# Recipe 10.9: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 10.9 (speech therapy assessment and monitoring). It shows one way you could translate the pipeline into working Python using boto3 against Amazon SageMaker (per-population disordered-speech-aware endpoints for forced alignment, phoneme classification, fluency event detection, and voice-quality scoring), Amazon Transcribe Medical (for connected-speech transcription feeding linguistic-feature extraction), Amazon Bedrock (with Guardrails for SLP-facing report generation and patient-and-parent-friendly summary generation), AWS HealthLake (FHIR Observation, Goal, and CarePlan write-back), AWS Lambda, AWS Step Functions, Amazon API Gateway, Amazon Cognito, Amazon DynamoDB, Amazon S3, AWS KMS, AWS Secrets Manager, Amazon EventBridge, Amazon CloudWatch, AWS CloudTrail, and Amazon Kinesis Data Firehose. The demo uses `MockSageMakerRuntime` standing in for the per-population scoring endpoints, a `MockTranscribeMedical` standing in for the speech-to-text path used by the connected-speech linguistic-feature extractor, a `MockBedrock` standing in for the SLP-report and family-summary LLM, a `MockHealthLake` standing in for the FHIR write-back, and small helpers for the session table, the longitudinal store, the feature-vector S3 bucket, the audio S3 bucket, the audit S3 bucket, the EventBridge bus, and CloudWatch-style metrics. It is not production-ready. There is no real audio capture from a clinic device or telepractice platform, no real Cognito authorizer, no real SageMaker invocation, no real Bedrock invocation, no real DynamoDB or S3 wiring, no Step Functions state machine, no IAM least-privilege role per Lambda, no KMS customer-managed key configuration, no VPC endpoints, no per-population accuracy disparity alerting, no biometric-data deletion-on-request workflow that handles the long-horizon pediatric retention, no FDA SaMD post-market surveillance integration where applicable, no SLP feedback loop wired through to model improvement, and no real EHR or school SIS write-back. Think of it as the sketchpad version: useful for understanding the shape of a speech-therapy-assessment pipeline that respects the SLP-as-customer framing, the disordered-speech-explicit-target discipline, the per-population validation discipline, the established-instrument alignment, the per-item confidence-based SLP-review flagging, the longitudinal-trajectory discipline, the pediatric consent infrastructure, the per-deployment-context configuration, and the post-deployment surveillance discipline this recipe demands. It is not something you would deploy to SLPs on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the eight core pseudocode steps from the main recipe: set up the assessment session with SLP-selected instruments, stimuli, patient context, and consent (Step 1), capture audio per task with task-aware quality assessment and recapture prompts (Step 2), extract acoustic, phonetic, and linguistic features per task with disordered-speech-tolerant alignment (Step 3), score each instrument with population-norm comparison and per-item confidence-based SLP-review flagging (Step 4), compute longitudinal comparison against prior sessions and active goals (Step 5), hand off to the SLP for review, override, and clinical interpretation (Step 6), generate the assessment-report documentation, family summary, and EHR or SIS write-back (Step 7), and audit, retain audio per consent, and feed post-deployment surveillance (Step 8). The synthetic patients, instruments, stimuli, scores, and goal trajectories in the demo are fictional; the names, MRNs, model versions, instrument IDs, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also configure the audio capture path (a clinic-grade dedicated microphone with known frequency-response characteristics for in-clinic assessment, a telepractice platform's audio path with telepractice-fine-tuned acoustic models, or a mobile-app capture path for home-practice deployments), per-population SageMaker endpoints (forced alignment, phoneme classification, fluency-event detection, voice-quality scoring; pediatric and adult variants per indication where the validation evidence supports the split), per-instrument stimulus and norm-reference data licensed from the assessment-instrument publishers and stored in DynamoDB or S3, an Amazon Bedrock inference profile pinned to a specific report-rendering model and region, an Amazon Bedrock Guardrails configuration that filters clinical-claim and harmful-content categories on family-facing communications, the Lambda functions that orchestrate each pipeline stage (the session-setup Lambda, the capture-ingest Lambda, the feature-extraction Lambda, the per-instrument-scoring Lambda, the longitudinal-comparison Lambda, the SLP-review handoff Lambda, the documentation-generation Lambda, the EHR or SIS write-back Lambda, the audit-and-surveillance Lambda), an AWS Step Functions state machine that durably orchestrates the multi-stage pipeline with retry semantics and Map-state fan-out across stimulus items, DynamoDB tables that hold session state, per-patient longitudinal feature history, per-instrument scoring records, per-goal progress trajectories, and SLP-edit history, AWS Secrets Manager secrets for the EHR API credentials, school SIS API credentials, and any external-vendor model-API credentials, an Amazon EventBridge bus for cross-system events (`session_setup_complete`, `session_captured`, `features_extracted`, `scoring_completed`, `longitudinal_completed`, `slp_review_complete`, `documentation_complete`, `session_audited`), Amazon S3 buckets for task-segmented audio (with consent-bounded retention lifecycle), feature vectors (with longer retention for longitudinal analysis and model improvement), assessment-report PDFs and structured archives, and the long-term audit archive (with Object Lock in compliance mode and lifecycle to Glacier Deep Archive), customer-managed KMS keys for every PHI-bearing and biometric-bearing data class, an AWS HealthLake datastore for FHIR Observation, Goal, and CarePlan write-back where the deployment context is FHIR-aligned, and Amazon CloudWatch dashboards plus SageMaker Model Monitor and Clarify jobs for the post-deployment surveillance program. The demo replaces all of these with small mocks so the focus stays on the per-stage processing logic rather than on the cloud-resource provisioning.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `sagemaker:InvokeEndpoint` and `sagemaker:InvokeEndpointAsync` for the per-population alignment, phoneme-classification, fluency-detection, and voice-quality endpoints, scoped to the specific endpoint ARNs of validated models in production use
- `bedrock:InvokeModel` for the SLP-report and family-summary generation models, scoped to the specific foundation-model ARNs and inference profiles in use
- `bedrock:ApplyGuardrail` for the runtime guardrails check on family-facing communications
- `transcribe:StartMedicalTranscriptionJob`, `transcribe:GetMedicalTranscriptionJob` for the connected-speech-transcript path used in linguistic-feature extraction
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the session, longitudinal, instrument-definition, norm-reference, and goal-tracking tables
- `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on the audio bucket (with lifecycle-driven deletion the primary path), the feature-vector bucket, the report-archive bucket, and the audit-archive bucket, scoped to the per-session key prefixes
- `secretsmanager:GetSecretValue` on the EHR-API and SIS-API credentials pinned to the current rotation version
- `events:PutEvents` on the speech-therapy EventBridge bus
- `cloudwatch:PutMetricData` for the operational metrics (per-stage latency, per-instrument scoring distributions, per-population SLP-edit rates, indeterminate-result rates, audio-quality scores, calibration-drift indicators, SLP-acceptance rates)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the audio bucket, the feature-vector bucket, the report archive, the audit archive, the DynamoDB tables, and the Secrets Manager secrets
- `states:StartExecution` for the Step Functions state machine that orchestrates the multi-stage scoring and documentation pipeline
- `healthlake:CreateResource`, `healthlake:UpdateResource` on the FHIR datastore for Observation, Goal, and CarePlan write-back

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The session-setup Lambda has scoped DynamoDB write for the session table only and EventBridge publish. The capture-ingest Lambda has scoped S3 write to the audio bucket and DynamoDB update on the session table. The feature-extraction Lambda has scoped S3 read on the audio bucket, S3 write on the feature bucket, Transcribe Medical permissions, and SageMaker invoke-endpoint scoped to the alignment, phoneme-classification, fluency-detection, and voice-quality endpoints. The scoring Lambda has DynamoDB read on the instrument-definition and norm-reference tables and write on the session table. The longitudinal Lambda has DynamoDB read and write on the longitudinal-history table. The documentation Lambda has Bedrock invoke-model permissions, S3 write to the report archive, HealthLake create-resource permissions, and Secrets Manager read for EHR or SIS credentials. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Voice samples are PHI and biometric.** A patient's voice can identify the patient independent of any other context. The privacy regime is the more restrictive of HIPAA, biometric-data law where applicable (Illinois BIPA, Texas, Washington and similar), FERPA for school-based deployments, and COPPA for any direct-to-child interface elements. Pediatric retention is materially longer than adult retention because pediatric medical records often must be retained until the patient reaches age of majority plus a state-specific number of years. Audio retention is a privacy-officer-reviewed decision, not a default. The architecture treats audio as PHI and biometric throughout: encrypted at rest with KMS customer-managed keys, encrypted in transit with TLS, retention bound by an explicit consent disclosure with FERPA-and-COPPA overlays where applicable, BAAs in place for any vendor service that processes the audio, and a biometric-data-deletion-on-request workflow that handles audio, feature vectors, and longitudinal-history entries with the long-horizon pediatric protection.
- **Disordered speech is the explicit target, not a degraded edge case.** The acoustic models, the alignment algorithms, and the phoneme classifiers all need to be validated against disordered speech. Off-the-shelf speech recognition tuned on typical adult speech will misclassify the population the system is meant to serve. The architecture supports per-population endpoints with explicit per-population validation envelopes; out-of-envelope samples produce SLP-review flags rather than confident-looking auto-scores.
- **Established assessment instruments anchor the scoring.** Each scoring path aligns with a published clinical instrument (Goldman-Fristoe-aligned articulation inventories, Hodson-aligned phonological pattern analysis, SSI-4-aligned fluency scoring, CAPE-V-aligned voice-quality dimensions, VHI-aligned voice-handicap estimation). The architecture stores per-instrument definitions, scoring rubrics, severity cutoffs, and norm references in DynamoDB so updates to the instrument or norm-reference data are configuration changes rather than code changes.
- **Per-item confidence-based SLP-review flagging is essential.** Items where the model's confidence falls below the institutional threshold are flagged for SLP review rather than auto-scored. The aggregate score reflects the auto-scored items plus the SLP-reviewed items; pretending the system is confidently right about every item breaks SLP trust the first time a confident-looking auto-score is wrong.
- **SLP-in-the-loop is the architectural primitive, not an optimization.** The SLP reviews flagged items, applies overrides with reasoning capture, and provides the clinical interpretation. The SLP's edits are the gold-standard signal that feeds back into model improvement and post-deployment surveillance.
- **Longitudinal trajectory often beats single-session scoring.** A child's articulation improvement over twelve weeks of therapy is more clinically actionable than the single-session percent-consonants-correct number. The architecture maintains per-patient longitudinal histories with per-target-sound and per-goal trajectories.
- **Pediatric and adult populations are different products sharing infrastructure.** Pediatric speech is acoustically different (different fundamental frequencies, different formant frequencies, different developmental phonology) and pediatric assessment instruments use age-graded stimuli and norms. The architecture supports per-population validated profiles rather than treating pediatric as a parameter on an adult model.
- **Per-deployment-context configuration matters.** Hospital-outpatient, school-based, private-practice, telepractice, and home-practice deployments have different documentation system targets, different consent requirements, and different population profiles. The architecture supports per-context configuration with explicit positioning per context.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, percent-correct value, and numeric metadata field passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses multiple Lambdas, the Step Functions orchestration, the EventBridge fan-out, and the CloudWatch metric emission into a single Python file for readability.** In production each pipeline stage is a separate Lambda with its own IAM role, error handling, retries, and DLQs, with Step Functions as the durable orchestrator for the multi-stage flow and Map-state fan-out across stimulus items. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the per-instrument definitions, the per-population norm references, the per-task quality thresholds, the consent disclosures, and the deployment-context flags are what you would change between environments.

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
# to CloudWatch Logs Insights. The speech-therapy pipeline
# operates on heavily PHI-bearing and biometric-bearing data:
# the audio is PHI and biometric, the transcripts and feature
# vectors are derivative biometric data, the per-instrument
# scores carry clinical implications, and every SLP-facing,
# parent-facing, or patient-facing artifact is a clinical-
# record transaction. Log structural metadata only (session_id,
# instrument_id, population_profile, item-count and review-
# pending-count summaries), never raw audio references that
# could leak the underlying biometric content, never patient
# demographics, never specific score values that could enable
# re-identification.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from SageMaker, Bedrock,
# Transcribe Medical, DynamoDB, S3, EventBridge, CloudWatch,
# HealthLake, and Secrets Manager. Speech-therapy assessment
# typically runs as an asynchronous post-session pipeline; a
# few seconds to minutes of latency is acceptable. The home-
# practice variant has tighter latency budgets that warrant
# different retry tuning.
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
# resources do not exist.
SESSION_TABLE             = "speech-therapy-sessions"
LONGITUDINAL_TABLE        = "speech-therapy-longitudinal-history"
INSTRUMENT_DEFINITION_TABLE = "speech-therapy-instrument-defs"
NORM_REFERENCE_TABLE      = "speech-therapy-norm-references"
GOAL_TRACKING_TABLE       = "speech-therapy-goal-tracking"
SLP_EDIT_HISTORY_TABLE    = "speech-therapy-slp-edits"
AUDIO_BUCKET              = "speech-therapy-audio"
FEATURE_BUCKET            = "speech-therapy-features"
REPORT_ARCHIVE_BUCKET     = "speech-therapy-reports"
AUDIT_ARCHIVE_BUCKET      = "speech-therapy-audit-archive"
HEALTHLAKE_DATASTORE_ID   = "12345678abcdefgh1234567890abcdef"
SLP_EVENT_BUS_NAME        = "speech-therapy-events-bus"
CLOUDWATCH_NAMESPACE      = "SpeechTherapyAssessment"
INSTITUTION_ID            = "academic-medical-center-richmond"

# Bedrock configuration. In production, pin to a specific
# model version and inference profile so a model upgrade does
# not silently change SLP-report or family-summary behavior.
# The model and region combination must be in your AWS BAA
# scope.
BEDROCK_REPORT_MODEL_ID = (
    "anthropic.claude-3-5-sonnet-20240620-v1:0")
BEDROCK_REPORT_PROFILE_ARN = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "speech-therapy-report-v1")
SLP_REPORT_GUARDRAIL_ID = "guardrail-slp-report-v1"
SLP_REPORT_GUARDRAIL_VERSION = "2"
FAMILY_SUMMARY_GUARDRAIL_ID = "guardrail-family-summary-v1"
FAMILY_SUMMARY_GUARDRAIL_VERSION = "3"

# Deploy-time guardrail. Any blank resource name is a deploy-
# time bug, not a runtime surprise.
for _name, _value in [
    ("SESSION_TABLE",                SESSION_TABLE),
    ("LONGITUDINAL_TABLE",           LONGITUDINAL_TABLE),
    ("INSTRUMENT_DEFINITION_TABLE",  INSTRUMENT_DEFINITION_TABLE),
    ("NORM_REFERENCE_TABLE",         NORM_REFERENCE_TABLE),
    ("AUDIO_BUCKET",                 AUDIO_BUCKET),
    ("FEATURE_BUCKET",               FEATURE_BUCKET),
    ("REPORT_ARCHIVE_BUCKET",        REPORT_ARCHIVE_BUCKET),
    ("AUDIT_ARCHIVE_BUCKET",         AUDIT_ARCHIVE_BUCKET),
    ("HEALTHLAKE_DATASTORE_ID",      HEALTHLAKE_DATASTORE_ID),
    ("SLP_EVENT_BUS_NAME",           SLP_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",         CLOUDWATCH_NAMESPACE),
    ("BEDROCK_REPORT_MODEL_ID",      BEDROCK_REPORT_MODEL_ID),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every assessment session carries the versions of the
# artifacts that influenced its scoring: per-instrument
# scoring-engine versions, per-population alignment and
# phoneme-classifier model versions, the feature-pipeline
# version, the prompt versions used for SLP-report and
# family-summary generation. A future audit reconstructs
# which configuration was active when a particular session
# was scored.
FEATURE_PIPELINE_VERSION    = "feature-pipeline-2026-q1"
SCORING_ENGINE_VERSION      = "scoring-engine-v2.3"
SLP_REPORT_PROMPT_VERSION   = "slp-report-prompt-v2.1"
FAMILY_SUMMARY_PROMPT_VERSION = "family-summary-prompt-v1.4"

# --- Audio Quality Thresholds ---
# Per-task quality must clear the institutional minimums
# before the segment enters the feature pipeline. Below these
# floors, the capture is rejected with a recapture prompt
# rather than producing low-confidence features. The
# thresholds are per-task in production; the demo uses a
# single set of defaults plus per-task overrides via the
# instrument definition.
DEFAULT_MIN_SAMPLE_RATE_HZ      = 16000
DEFAULT_MIN_SNR_DB              = Decimal("12.0")
DEFAULT_MAX_CLIPPING_PERCENT    = Decimal("1.5")
DEFAULT_MIN_TASK_QUALITY        = Decimal("0.65")
DEFAULT_MAX_TASK_RETRIES        = 2

# --- Per-Item Confidence Threshold ---
# Items with model confidence below this threshold are
# flagged for SLP review rather than auto-scored. The
# threshold is per-instrument in production; the demo uses a
# default with per-instrument overrides.
DEFAULT_PER_ITEM_CONFIDENCE_THRESHOLD = Decimal("0.70")

# --- Trajectory Configuration ---
# Minimum number of prior sessions required before a
# trajectory baseline can be computed; below this, the system
# reports the single-session score without trajectory
# context. The within-patient typical variation is computed
# from the patient's own session-to-session deltas in
# production; the demo uses a default proxy.
MIN_SESSIONS_FOR_TRAJECTORY = 2
TRAJECTORY_WINDOW_MONTHS    = 24
DEFAULT_WITHIN_PATIENT_TYPICAL_VARIATION = Decimal("0.04")

# --- Consent Disclosures ---
# Voice samples are biometric. The disclosure language differs
# by jurisdiction (Illinois BIPA, Texas, Washington each have
# specific requirements), by deployment context (school-based
# adds FERPA, direct-to-child adds COPPA), and by patient age
# (pediatric requires parent consent plus age-appropriate
# assent). Production looks up the patient's jurisdiction,
# the deployment context, and the patient's age band; the
# demo uses illustrative defaults.
CONSENT_DISCLOSURE_DEFAULT_ADULT = (
    "We are recording your voice during this assessment to "
    "support your speech-therapy care. Your voice is "
    "considered biometric data and will be handled with the "
    "same protections as your other health information. "
    "Audio recordings will be deleted after analysis unless "
    "you give specific permission for longer retention. "
    "Numerical features and scoring derived from the recording "
    "will be retained for ongoing care planning. You can "
    "withdraw your consent at any time.")
CONSENT_DISCLOSURE_PEDIATRIC_PARENT = (
    "We are recording your child's voice during this "
    "assessment to support their speech-therapy care. Your "
    "child's voice is biometric data; we protect it like "
    "any other health information. Audio recordings will be "
    "deleted after analysis except where you give specific "
    "permission for longer retention. Numerical features "
    "and scoring will be retained as part of your child's "
    "medical record. You can withdraw consent at any time.")
CONSENT_DISCLOSURE_PEDIATRIC_ASSENT_AGE_7_PLUS = (
    "We will record your voice while you do speech "
    "exercises today. We use the recording to help your "
    "speech therapist understand how to help you. You can "
    "say 'no' if you do not want to be recorded.")
CONSENT_DISCLOSURE_BIPA = (
    "Under Illinois law, we are specifically informing you "
    "that voice recordings are biometric data. We are "
    "collecting them for the speech-therapy assessment "
    "purpose described above. We will retain audio only for "
    "the period stated in your consent. You can request "
    "deletion at any time. By continuing, you give written "
    "consent to this collection.")
CONSENT_DISCLOSURE_FERPA_SCHOOL = (
    "This assessment is part of your child's educational "
    "record under FERPA. The school-based speech-language "
    "pathologist will use the results to support IEP "
    "planning. You may inspect the record and request "
    "amendments per FERPA procedures.")

# Jurisdictions with biometric-data laws requiring specific
# disclosure language. The list is approximate and changes
# over time as state law evolves; production maintains this
# in a legal-team-reviewed configuration with an explicit
# update cadence.
# TODO (TechWriter): verify the current biometric-data-law
# state list against the IAPP biometric-privacy tracker
# before deploying.
BIOMETRIC_DATA_LAW_STATES = {"IL", "TX", "WA"}

# --- Population Profile Definitions ---
# The validated population profiles available for routing to
# the appropriate per-population SageMaker endpoints.
# Production profiles are per-indication and per-validation-
# study; the demo uses an illustrative set.
POPULATION_PROFILES = {
    "pediatric_typical_age_4_8":  "pediatric typical-development, ages 4-8",
    "pediatric_typical_age_9_12": "pediatric typical-development, ages 9-12",
    "pediatric_disordered_age_4_8":
        "pediatric speech-disordered, ages 4-8",
    "pediatric_disordered_age_9_12":
        "pediatric speech-disordered, ages 9-12",
    "adult_typical":              "adult typical speech",
    "adult_dysarthric":           "adult dysarthric speech",
    "adult_aphasic":              "adult post-stroke aphasia",
    "adult_voice_disorder":       "adult voice-disorder population",
}
```

Now the per-instrument and per-population SageMaker endpoint configurations:

```python
# --- Per-Population SageMaker Endpoint Routing ---
# Each per-population endpoint reflects the per-population
# validation. Adding a new population means adding a new
# validated endpoint, not retraining an existing one to
# stretch beyond its validation envelope.
ALIGNMENT_ENDPOINTS = {
    "pediatric_typical_age_4_8":
        "speech-therapy-alignment-peds-typical-4-8",
    "pediatric_typical_age_9_12":
        "speech-therapy-alignment-peds-typical-9-12",
    "pediatric_disordered_age_4_8":
        "speech-therapy-alignment-peds-disordered-4-8",
    "pediatric_disordered_age_9_12":
        "speech-therapy-alignment-peds-disordered-9-12",
    "adult_typical":
        "speech-therapy-alignment-adult-typical",
    "adult_dysarthric":
        "speech-therapy-alignment-adult-dysarthric",
}
PHONEME_CLASSIFIER_ENDPOINTS = {
    "pediatric_typical_age_4_8":
        "speech-therapy-phoneme-peds-typical-4-8",
    "pediatric_typical_age_9_12":
        "speech-therapy-phoneme-peds-typical-9-12",
    "pediatric_disordered_age_4_8":
        "speech-therapy-phoneme-peds-disordered-4-8",
    "pediatric_disordered_age_9_12":
        "speech-therapy-phoneme-peds-disordered-9-12",
    "adult_typical":
        "speech-therapy-phoneme-adult-typical",
    "adult_dysarthric":
        "speech-therapy-phoneme-adult-dysarthric",
}
FLUENCY_ENDPOINTS = {
    "pediatric_typical_age_4_8":
        "speech-therapy-fluency-peds-4-8",
    "pediatric_typical_age_9_12":
        "speech-therapy-fluency-peds-9-12",
    "adult_typical":
        "speech-therapy-fluency-adult",
}
VOICE_QUALITY_ENDPOINTS = {
    "adult_voice_disorder":
        "speech-therapy-voice-quality-adult",
    "pediatric_typical_age_9_12":
        "speech-therapy-voice-quality-peds-9-12",
}

# --- Per-Instrument Definitions ---
# Each instrument definition stores the stimulus list, the
# scoring rubric, the severity cutoffs, the available norm
# references, the validation envelope, and the per-instrument
# confidence threshold. Production reads these from
# DynamoDB; the demo uses an in-memory dict.
INSTRUMENT_DEFINITIONS = {
    "articulation_inventory_gfta_aligned": {
        "instrument_id":
            "articulation_inventory_gfta_aligned",
        "instrument_class":  "articulation",
        "scoring_method":    "percent_consonants_correct",
        "applicable_populations": [
            "pediatric_typical_age_4_8",
            "pediatric_typical_age_9_12",
            "pediatric_disordered_age_4_8",
            "pediatric_disordered_age_9_12",
        ],
        "validation_envelope": {
            "age_band":          ["4_8", "9_12"],
            "primary_language":  ["en-US"],
            "device_class": [
                "clinic_dedicated_microphone",
                "telepractice_video",
            ],
        },
        "stimulus_list": [
            {"task_id":            "rabbit",
             "task_type":          "single_word_articulation",
             "expected_target":    "rabbit",
             "expected_phonemes":
                 ["r", "ae", "b", "ih", "t"],
             "expected_duration":  Decimal("1.5"),
             "minimum_quality":
                 DEFAULT_MIN_TASK_QUALITY,
             "quality_thresholds": {
                 "min_snr_db":         DEFAULT_MIN_SNR_DB,
                 "max_clipping_percent":
                     DEFAULT_MAX_CLIPPING_PERCENT,
             },
             "max_retries":        DEFAULT_MAX_TASK_RETRIES,
             "required":           True},
            {"task_id":            "sheep",
             "task_type":          "single_word_articulation",
             "expected_target":    "sheep",
             "expected_phonemes":  ["sh", "iy", "p"],
             "expected_duration":  Decimal("1.2"),
             "minimum_quality":
                 DEFAULT_MIN_TASK_QUALITY,
             "quality_thresholds": {
                 "min_snr_db":         DEFAULT_MIN_SNR_DB,
                 "max_clipping_percent":
                     DEFAULT_MAX_CLIPPING_PERCENT,
             },
             "max_retries":        DEFAULT_MAX_TASK_RETRIES,
             "required":           True},
            {"task_id":            "thumb",
             "task_type":          "single_word_articulation",
             "expected_target":    "thumb",
             "expected_phonemes":  ["th", "ah", "m"],
             "expected_duration":  Decimal("1.2"),
             "minimum_quality":
                 DEFAULT_MIN_TASK_QUALITY,
             "quality_thresholds": {
                 "min_snr_db":         DEFAULT_MIN_SNR_DB,
                 "max_clipping_percent":
                     DEFAULT_MAX_CLIPPING_PERCENT,
             },
             "max_retries":        DEFAULT_MAX_TASK_RETRIES,
             "required":           True},
            # In production the stimulus list spans the full
            # instrument inventory (typically 50+ items for
            # GFTA-aligned articulation). The demo uses three.
        ],
        "scoring_items":  [
            {"item_id":          "item_001_rabbit",
             "task_id":          "rabbit",
             "expected_target":  "rabbit",
             "scored_phonemes":
                 ["r", "ae", "b", "ih", "t"]},
            {"item_id":          "item_002_sheep",
             "task_id":          "sheep",
             "expected_target":  "sheep",
             "scored_phonemes":  ["sh", "iy", "p"]},
            {"item_id":          "item_003_thumb",
             "task_id":          "thumb",
             "expected_target":  "thumb",
             "scored_phonemes":  ["th", "ah", "m"]},
        ],
        "summary_method":            "percent_consonants_correct",
        "severity_cutoffs": {
            "within_normal_limits": Decimal("0.85"),
            "mild":                 Decimal("0.70"),
            "mild_to_moderate":     Decimal("0.55"),
            "moderate":             Decimal("0.40"),
            "severe":               Decimal("0.0"),
        },
        "confidence_threshold":
            DEFAULT_PER_ITEM_CONFIDENCE_THRESHOLD,
        "available_norms": [
            "gfta3_age_4_0_to_4_5_female",
            "gfta3_age_4_0_to_4_5_male",
            "gfta3_age_4_6_to_4_11_female",
            "gfta3_age_4_6_to_4_11_male",
            "gfta3_age_5_0_to_5_5_female",
            "gfta3_age_5_0_to_5_5_male",
            "gfta3_age_5_6_to_5_11_female",
            "gfta3_age_5_6_to_5_11_male",
            "gfta3_age_6_0_to_6_5_female",
            "gfta3_age_6_0_to_6_5_male",
            "gfta3_age_6_6_to_6_11_female",
            "gfta3_age_6_6_to_6_11_male",
        ],
        "detects_phonological_patterns": False,
    },
    "phonological_pattern_analysis": {
        "instrument_id":     "phonological_pattern_analysis",
        "instrument_class":  "phonological_pattern",
        "scoring_method":    "percent_pattern_occurrence",
        "applicable_populations": [
            "pediatric_typical_age_4_8",
            "pediatric_disordered_age_4_8",
            "pediatric_disordered_age_9_12",
        ],
        "validation_envelope": {
            "age_band":          ["4_8", "9_12"],
            "primary_language":  ["en-US"],
            "device_class": [
                "clinic_dedicated_microphone",
                "telepractice_video",
            ],
        },
        "stimulus_list": [],  # shares stimuli with articulation
        "scoring_items": [],  # derived from articulation items
        "summary_method":  "phonological_pattern_summary",
        "severity_cutoffs": {},
        "confidence_threshold": Decimal("0.65"),
        "available_norms": ["hodson_pattern_age_4_to_8"],
        "detects_phonological_patterns": True,
        "pattern_definitions": [
            {"pattern": "final_consonant_deletion",
             "age_appropriate_through_age": Decimal("3.5"),
             "detection_rule":
                 "expected_final_consonant_omitted"},
            {"pattern": "gliding_of_liquids",
             "age_appropriate_through_age": Decimal("6.5"),
             "detection_rule":
                 "r_or_l_substituted_with_w_or_y"},
            {"pattern": "stopping_of_fricatives",
             "age_appropriate_through_age": Decimal("3.5"),
             "detection_rule":
                 "fricative_substituted_with_stop"},
            {"pattern": "fronting",
             "age_appropriate_through_age": Decimal("3.5"),
             "detection_rule":
                 "velar_substituted_with_alveolar"},
            {"pattern": "cluster_reduction",
             "age_appropriate_through_age": Decimal("4.0"),
             "detection_rule":
                 "consonant_cluster_simplified"},
        ],
    },
    "connected_speech_picture_description": {
        "instrument_id":
            "connected_speech_picture_description",
        "instrument_class":  "connected_speech",
        "scoring_method":    "linguistic_feature_summary",
        "applicable_populations": [
            "pediatric_typical_age_4_8",
            "pediatric_typical_age_9_12",
            "pediatric_disordered_age_4_8",
            "pediatric_disordered_age_9_12",
            "adult_typical",
            "adult_aphasic",
        ],
        "validation_envelope": {
            "age_band":          ["4_8", "9_12", "adult"],
            "primary_language":  ["en-US"],
            "device_class": [
                "clinic_dedicated_microphone",
                "telepractice_video",
            ],
        },
        "stimulus_list": [
            {"task_id":            "picnic_scene",
             "task_type":
                 "connected_speech_picture_description",
             "expected_target":
                 "spontaneous narrative description",
             "expected_phonemes":  None,
             "expected_duration":  Decimal("60"),
             "minimum_quality":
                 DEFAULT_MIN_TASK_QUALITY,
             "quality_thresholds": {
                 "min_snr_db":         DEFAULT_MIN_SNR_DB,
                 "max_clipping_percent":
                     DEFAULT_MAX_CLIPPING_PERCENT,
             },
             "max_retries":        1,
             "required":           True,
             "linguistic_features": [
                 "mean_length_of_utterance_morphemes",
                 "lexical_diversity_ttr",
                 "syntactic_complexity_index",
                 "narrative_structure_score",
             ]},
        ],
        "scoring_items": [
            {"item_id":   "item_001_picnic_narrative",
             "task_id":   "picnic_scene",
             "scored_features": [
                 "mean_length_of_utterance_morphemes",
                 "lexical_diversity_ttr",
                 "syntactic_complexity_index",
                 "narrative_structure_score",
             ]},
        ],
        "summary_method":  "connected_speech_summary",
        "severity_cutoffs": {},
        "confidence_threshold": Decimal("0.60"),
        "available_norms": [
            "mlu_norms_age_4_8_english",
            "mlu_norms_age_9_12_english",
        ],
        "detects_phonological_patterns": False,
    },
}

# --- Per-Population Norm Reference Tables ---
# Population norms keyed by reference_id. Production licenses
# these from the assessment-instrument publishers and stores
# them in DynamoDB; the demo uses an in-memory dict with one
# entry per illustrative norm.
NORM_REFERENCE_LOOKUP = {
    "gfta3_age_6_0_to_6_5_female": {
        "reference_id":
            "gfta3_age_6_0_to_6_5_female",
        "instrument_id":
            "articulation_inventory_gfta_aligned",
        "norm_population":
            "general American English, ages 6.0 to 6.5, female",
        "percentile_table": [
            (Decimal("0.95"), 99),
            (Decimal("0.90"), 90),
            (Decimal("0.85"), 75),
            (Decimal("0.80"), 50),
            (Decimal("0.70"), 25),
            (Decimal("0.60"), 10),
            (Decimal("0.50"), 5),
            (Decimal("0.40"), 1),
        ],
        "standard_score_table": [
            (Decimal("0.95"), 115),
            (Decimal("0.90"), 105),
            (Decimal("0.85"), 95),
            (Decimal("0.80"), 90),
            (Decimal("0.70"), 82),
            (Decimal("0.60"), 75),
            (Decimal("0.50"), 70),
        ],
        "norm_publication_year": 2026,
        "norm_provenance":
            "illustrative-only-not-real-norms",
    },
    "mlu_norms_age_4_8_english": {
        "reference_id":   "mlu_norms_age_4_8_english",
        "instrument_id":
            "connected_speech_picture_description",
        "norm_population":
            "general American English, ages 4-8",
        "mean_by_age": {
            "4":  Decimal("4.4"),
            "5":  Decimal("4.9"),
            "6":  Decimal("5.3"),
            "7":  Decimal("5.7"),
            "8":  Decimal("6.0"),
        },
        "norm_publication_year": 2026,
        "norm_provenance":
            "illustrative-only-not-real-norms",
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


def _bucket_age(age_years):
    """Translate a numeric age into the cohort age band."""
    if age_years is None:
        return "not_disclosed"
    if age_years < 4:
        return "under_4"
    if age_years <= 8:
        return "4_8"
    if age_years <= 12:
        return "9_12"
    if age_years < 18:
        return "13_17"
    return "adult"


def _select_consent_disclosure(jurisdiction,
                                  deployment_context,
                                  is_minor):
    """Pick the disclosure language based on the patient's
    jurisdiction, the deployment context, and whether the
    patient is a minor."""
    if deployment_context == "school_based":
        return CONSENT_DISCLOSURE_FERPA_SCHOOL
    if jurisdiction in BIOMETRIC_DATA_LAW_STATES:
        return CONSENT_DISCLOSURE_BIPA
    if is_minor:
        return CONSENT_DISCLOSURE_PEDIATRIC_PARENT
    return CONSENT_DISCLOSURE_DEFAULT_ADULT


def audit_log(event):
    """
    Sanitized audit print so you can see the sequence of
    decisions without leaking the underlying values.
    Production routes events to CloudWatch Logs Insights with
    structured JSON; ship to a SIEM if available. Voice
    samples are biometric data; never include the audio
    reference itself in routine audit logs, never include
    raw transcripts that could capture spontaneous PHI from
    connected-speech tasks, never include patient
    demographics that could enable re-identification.
    """
    safe_event = {k: v for k, v in event.items()
                  if k not in {"audio_ref", "transcript",
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

These mocks stand in for the production AWS resources and back-office systems. They are deliberately simple and are not how you would build the real thing. Their purpose is to keep the focus on the speech-therapy assessment logic.

```python
class MockSageMakerRuntime:
    """
    Stands in for the per-population SageMaker endpoint
    invocations. In production, each per-population endpoint
    (forced alignment, phoneme classification, fluency-event
    detection, voice-quality scoring) is hosted as its own
    SageMaker endpoint with the appropriate per-population
    validated model. The mock returns canned outputs per
    (endpoint_name, audio_ref, expected_target) tuple.
    """
    def __init__(self, fixtures):
        # fixtures keyed by (endpoint_name, audio_ref)
        self._fixtures = fixtures
        self.invocations = []

    def invoke_endpoint(self, endpoint_name, body,
                          content_type="application/json"):
        # Production:
        #   sagemaker_runtime.invoke_endpoint(
        #     EndpointName=endpoint_name,
        #     ContentType=content_type,
        #     Body=body)
        # The body is the model-specific JSON request shape;
        # the response includes the model output (alignment
        # boundaries, phoneme classifications, fluency events,
        # voice-quality dimensions) plus per-output confidence.
        request = json.loads(body) if isinstance(body, str) else body
        self.invocations.append({
            "endpoint":     endpoint_name,
            "audio_ref":    request.get("audio_ref"),
            "task_id":      request.get("task_id"),
        })
        key = (endpoint_name, request.get("audio_ref"))
        response = self._fixtures.get(key, {
            "alignment":        None,
            "phoneme_classification": None,
            "fluency_events":   None,
            "voice_quality":    None,
            "model_version":    "unknown",
        })
        return {"body": json.dumps(response, default=str)}


class MockTranscribeMedical:
    """
    Stands in for the Transcribe Medical batch transcription
    used by the connected-speech linguistic-feature pipeline.
    In production, this is
    `transcribe_client.start_medical_transcription_job`
    plus polling for job completion. The mock returns canned
    transcripts keyed by audio_ref.
    """
    def __init__(self, transcript_fixtures):
        self._fixtures = transcript_fixtures
        self.jobs_started = []

    def start_medical_transcription(self, job_name,
                                       audio_uri, language,
                                       specialty="PRIMARYCARE"):
        # Real boto3:
        #   transcribe_client.start_medical_transcription_job(
        #     MedicalTranscriptionJobName=job_name,
        #     Media={"MediaFileUri": audio_uri},
        #     LanguageCode=language,
        #     Specialty=specialty,
        #     Type="DICTATION",
        #     OutputBucketName=...,
        #     OutputKey=...)
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


class MockBedrock:
    """
    Stands in for Amazon Bedrock's InvokeModel for SLP-
    facing report generation and family-facing summary
    generation. In production this is
    bedrock_runtime.invoke_model with the structured
    scoring data, the longitudinal context, the clinical
    interpretation, and the institutional template as the
    prompt context. Guardrails are applied at runtime,
    especially for the family-facing generation.
    """
    def __init__(self, report_responses, summary_responses):
        self._report_responses = report_responses
        self._summary_responses = summary_responses
        self.invocations = []

    def render_slp_report(self, session_id, report_input,
                            guardrail_id):
        self.invocations.append({
            "type":          "slp_report",
            "session_id":    session_id,
            "guardrail_id":  guardrail_id,
        })
        response = self._report_responses.get(
            session_id, {
                "content":
                    "Speech-therapy assessment report. "
                    "This is decision support, not a "
                    "diagnosis. The SLP retains clinical "
                    "interpretive authority over the "
                    "scoring and the recommendations.",
                "guardrail_action": "NONE",
            })
        return {"body": json.dumps(response, default=str)}

    def render_family_summary(self, session_id, summary_input,
                                 guardrail_id):
        self.invocations.append({
            "type":          "family_summary",
            "session_id":    session_id,
            "guardrail_id":  guardrail_id,
        })
        response = self._summary_responses.get(
            session_id, {
                "content":
                    "Thank you for participating in today's "
                    "speech-therapy session. Your speech-"
                    "language pathologist will review the "
                    "results and discuss next steps with "
                    "you.",
                "guardrail_action": "NONE",
            })
        return {"body": json.dumps(response, default=str)}


class MockHealthLake:
    """
    Stands in for AWS HealthLake's FHIR resource write
    surface. In production this is healthlake_client.
    create_resource(DatastoreId=..., ResourceType=..., 
    Resource=...) for Observation, Goal, and CarePlan
    resources. The mock just records the writes.
    """
    def __init__(self):
        self.resources_written = []

    def create_resource(self, datastore_id, resource_type,
                          resource):
        resource_id = (
            f"{resource_type.lower()}-{uuid.uuid4().hex[:10]}")
        self.resources_written.append({
            "resource_id":    resource_id,
            "resource_type":  resource_type,
            "datastore_id":   datastore_id,
            "resource":       dict(resource),
        })
        return {"resource_id": resource_id}


class MockSchoolSIS:
    """
    Stands in for school-district student information
    system integration (PowerSchool, Infinite Campus, and
    similar). Production routes through the institutional
    integration layer; the mock just records the write.
    """
    def __init__(self):
        self.assessments_written = []

    def write_assessment(self, student_id, assessment_record,
                          iep_alignment):
        record_id = f"sis-{uuid.uuid4().hex[:10]}"
        self.assessments_written.append({
            "record_id":         record_id,
            "student_id":        student_id,
            "assessment_record": dict(assessment_record),
            "iep_alignment":     iep_alignment,
            "written_at":        _now_iso(),
        })
        return {"record_id": record_id}


class MockSessionTable:
    """In-memory stand-in for the DynamoDB session table.
    Each entry tracks one assessment session through the
    eight pipeline stages."""
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


class MockLongitudinalTable:
    """In-memory stand-in for the DynamoDB longitudinal
    history table. Per-patient series of session-level
    feature and score histories."""
    def __init__(self):
        self._items = []

    def put(self, item):
        self._items.append(dict(item))

    def get_history(self, patient_id_hash, window_months,
                       limit=20):
        cutoff = (datetime.now(timezone.utc)
                    - timedelta(days=30 * window_months)
                  ).isoformat()
        history = [item for item in self._items
                    if item.get("patient_id_hash") ==
                       patient_id_hash
                    and item.get("session_timestamp", "")
                        >= cutoff]
        history.sort(
            key=lambda x: x.get("session_timestamp", ""),
            reverse=True)
        return history[:limit]


class MockS3:
    """
    Stands in for S3 audio storage, feature-vector storage,
    report archive, and audit archive. Holds objects in
    memory keyed by (bucket, key). Production uses customer-
    managed KMS keys for encryption and lifecycle policies
    for retention.
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
    flow here for cross-system fan-out: session_setup_complete,
    session_captured, features_extracted, scoring_completed,
    longitudinal_completed, slp_review_complete,
    documentation_complete, session_audited."""
    def __init__(self):
        self.events = []

    def put_events(self, entries):
        for entry in entries:
            self.events.append(dict(entry))


class MockCloudWatch:
    """Stands in for CloudWatch metric emission. In
    production the metrics flow into dashboards and alarms,
    with SageMaker Model Monitor and Clarify producing
    additional per-population surveillance reports on a
    scheduled cadence."""
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


# Module-level singletons for the demo. In production each
# of these is its own AWS resource accessed via boto3.
session_table         = MockSessionTable()
longitudinal_table    = MockLongitudinalTable()
s3_store              = MockS3()
event_bus             = MockEventBus()
cloudwatch            = MockCloudWatch()
healthlake            = MockHealthLake()
school_sis            = MockSchoolSIS()
# sagemaker_mock, transcribe_mock, and bedrock_mock are wired
# up in run_demo() with fixture data tailored to each
# scenario.
sagemaker_mock        = None
transcribe_mock       = None
bedrock_mock          = None


# --- Patient demographics and goal lookups ---
# Production reads from the EHR via FHIR or from the school
# SIS; the demo uses in-memory maps keyed by patient_id.
PATIENT_DEMOGRAPHICS = {
    "pt-maya-77": {
        "age_years":         6,
        "sex":               "female",
        "primary_language":  "en-US",
        "is_minor":          True,
        "jurisdiction":      "VA",
        "student_id":        "stu-77",
        "has_speech_disorder": True,
        "stimulus_customizations": [],
    },
    "pt-marcus-42": {
        "age_years":         62,
        "sex":               "male",
        "primary_language":  "en-US",
        "is_minor":          False,
        "jurisdiction":      "IL",
        "student_id":        None,
        "stimulus_customizations": [],
    },
}


def lookup_patient_context(patient_id):
    return dict(PATIENT_DEMOGRAPHICS.get(patient_id, {}))


def lookup_patient_id(patient_id_hash):
    """Reverse lookup the unhashed patient ID from the hash.
    Production reads from a small ID-mapping service; the
    demo derives it from the in-memory map."""
    for pid, demo in PATIENT_DEMOGRAPHICS.items():
        if _hash_value(pid) == patient_id_hash:
            return pid
    return None


# Per-patient active goals. Production reads from a goal-
# tracking table keyed on patient_id; the demo uses an
# in-memory map.
ACTIVE_GOALS = {
    "pt-maya-77": [
        {
            "goal_id":         "goal_001_final_consonants",
            "goal_text":
                "Maya will produce final consonants in single "
                "words with 80% accuracy",
            "target_metric":
                "final_consonant_production_accuracy",
            "baseline_value": Decimal("0.42"),
            "target_value":   Decimal("0.80"),
            "evaluation_rubric":
                "percent_correct_in_articulation_inventory",
        },
        {
            "goal_id":         "goal_002_initial_fricatives",
            "goal_text":
                "Maya will produce /s/, /f/ in initial "
                "position with 80% accuracy",
            "target_metric":
                "initial_fricative_production_accuracy",
            "baseline_value": Decimal("0.55"),
            "target_value":   Decimal("0.80"),
            "evaluation_rubric":
                "percent_correct_target_phonemes",
        },
    ],
}


def lookup_active_goals(patient_id):
    return [dict(g) for g in
              ACTIVE_GOALS.get(patient_id, [])]


def lookup_most_recent_session(patient_id):
    """Return a reference to the most recent prior session
    for this patient, if any."""
    history = longitudinal_table.get_history(
        _hash_value(patient_id), window_months=24, limit=1)
    if history:
        return history[0].get("session_id")
    return None


def lookup_population_profile(patient_context):
    """
    Determine the patient population profile that selects
    the appropriate per-population SageMaker endpoints.
    Production maintains a richer per-indication mapping;
    the demo uses an age-and-clinical-status-driven shortcut.
    """
    age_years = patient_context.get("age_years")
    age_band = _bucket_age(age_years)
    has_disorder = patient_context.get(
        "has_speech_disorder", False)
    if age_band == "4_8":
        return ("pediatric_disordered_age_4_8"
                if has_disorder
                else "pediatric_typical_age_4_8")
    if age_band == "9_12":
        return ("pediatric_disordered_age_9_12"
                if has_disorder
                else "pediatric_typical_age_9_12")
    if age_band == "adult":
        return ("adult_dysarthric"
                if patient_context.get(
                    "has_dysarthria", False)
                else "adult_typical")
    return "adult_typical"


def lookup_instrument_definition(instrument_id):
    return INSTRUMENT_DEFINITIONS.get(instrument_id)


def lookup_norm_reference(reference_id):
    return NORM_REFERENCE_LOOKUP.get(reference_id)


def select_norm_reference(available_norms, age_years, sex,
                             primary_language):
    """
    Select the most appropriate norm reference from the
    instrument's available norms based on the patient's
    profile. Production handles continuous age matching
    with appropriate banding; the demo picks a substring-
    matching shortcut.
    """
    target_pieces = []
    if age_years is not None:
        # GFTA-style norms band on six-month intervals.
        whole = int(age_years)
        target_pieces.append(f"age_{whole}_")
    if sex:
        target_pieces.append(sex.lower())
    for ref in available_norms:
        if all(piece in ref for piece in target_pieces):
            return ref
    return available_norms[0] if available_norms else None
```

---

## Step 1: Set Up the Assessment Session with Instruments, Stimuli, Patient Context, and Consent

*The pseudocode calls this `ON session_initiated(...)`. When the SLP initiates an assessment, the system records the selected instruments, customizes the stimulus list per the patient's profile, captures consent (with FERPA, COPPA, and biometric-data-law overlays where applicable), and persists the session record. Skip the per-patient instrument applicability check and the system administers instruments outside their validation envelope; skip the consent capture and the institution accumulates biometric data without proper authorization.*

```python
def check_instrument_applicability(patient_context,
                                       instrument_def):
    """
    Check whether the instrument's validation envelope
    covers the patient's profile. Production handles
    continuous variables (age) with band matching and
    categorical variables (language, device class) with set
    membership; the demo uses the same pattern.
    """
    envelope = instrument_def.get("validation_envelope", {})
    age_band = _bucket_age(patient_context.get("age_years"))
    age_eligible = age_band in envelope.get("age_band", [])
    language_eligible = patient_context.get(
        "primary_language") in envelope.get(
        "primary_language", [])
    return {
        "applicable":      age_eligible and language_eligible,
        "age_band":        age_band,
        "age_eligible":    age_eligible,
        "language":
            patient_context.get("primary_language"),
        "language_eligible": language_eligible,
        "reason":
            None if age_eligible and language_eligible
            else (
                "age_outside_validation"
                if not age_eligible
                else "language_outside_validation"),
    }


def customize_stimuli(stimulus_list, customizations):
    """
    Apply patient-specific stimulus customizations (skip
    items, substitute alternates, adjust order). The demo
    just returns the base list."""
    if not customizations:
        return list(stimulus_list)
    skip_items = {c["task_id"] for c in customizations
                   if c.get("action") == "skip"}
    return [task for task in stimulus_list
            if task.get("task_id") not in skip_items]


def determine_consent_frameworks(patient_context,
                                     deployment_context):
    """
    Determine which consent frameworks apply to this
    session. School-based deployments add FERPA; pediatric
    direct-to-child interfaces add COPPA; certain
    jurisdictions add biometric-data-law requirements; all
    deployments apply HIPAA where the assessment is part of
    clinical care.
    """
    frameworks = ["HIPAA"]
    if deployment_context.get("context_type") == "school_based":
        frameworks.append("FERPA")
    if patient_context.get("is_minor") and \
       deployment_context.get("interface_type") \
            == "direct_to_child":
        frameworks.append("COPPA")
    if patient_context.get("jurisdiction") in \
       BIOMETRIC_DATA_LAW_STATES:
        frameworks.append("biometric_data_law")
    return frameworks


def capture_consent(patient_id, consent_type,
                       deployment_context,
                       applicable_frameworks,
                       retention_terms, is_minor):
    """
    Capture the patient's (or parent's) consent. Production
    presents the disclosure through the device or clinic UI
    and records explicit acknowledgment, parent-or-guardian
    signature for minors, age-appropriate assent text for
    pediatric patients age 7+, and FERPA-aligned procedures
    for school deployments. The demo simulates a granted
    consent.
    """
    consent_id = "consent-" + uuid.uuid4().hex[:12]
    return {
        "granted":              True,
        "consent_id":           consent_id,
        "consent_type":         consent_type,
        "deployment_context":   deployment_context,
        "applicable_frameworks":
            applicable_frameworks,
        "retention_terms":      retention_terms,
        "captured_at":          _now_iso(),
        "is_minor":             is_minor,
    }


def session_initiated(slp_id, patient_id,
                         selected_instruments,
                         deployment_context,
                         session_id_hint=None):
    """
    Bootstrap an assessment session: load patient context,
    validate that each selected instrument applies to the
    patient profile, capture consent under the appropriate
    frameworks, customize the stimulus list, and persist the
    session record.
    """
    # Step 1A: load patient context.
    patient_context = lookup_patient_context(patient_id)
    if not patient_context:
        audit_log({
            "event_type":  "PATIENT_NOT_FOUND",
            "timestamp":   _now_iso(),
        })
        return {"status": "PATIENT_NOT_FOUND"}

    # Step 1B: validate instrument applicability.
    applicable_instruments = []
    for instrument_id in selected_instruments:
        instrument_def = lookup_instrument_definition(
            instrument_id)
        if not instrument_def:
            audit_log({
                "event_type":     "INSTRUMENT_NOT_FOUND",
                "instrument_id":  instrument_id,
                "timestamp":      _now_iso(),
            })
            continue

        applicability = check_instrument_applicability(
            patient_context=patient_context,
            instrument_def=instrument_def)

        if applicability["applicable"]:
            applicable_instruments.append({
                "instrument_id":   instrument_id,
                "stimulus_list":   customize_stimuli(
                    instrument_def["stimulus_list"],
                    patient_context.get(
                        "stimulus_customizations", [])),
                "norm_reference":  select_norm_reference(
                    instrument_def.get(
                        "available_norms", []),
                    patient_context.get("age_years"),
                    patient_context.get("sex"),
                    patient_context.get(
                        "primary_language")),
            })
        else:
            audit_log({
                "event_type":      "INSTRUMENT_INAPPLICABLE",
                "instrument_id":   instrument_id,
                "reason":          applicability["reason"],
                "timestamp":       _now_iso(),
            })

    if not applicable_instruments:
        return {"status": "NO_APPLICABLE_INSTRUMENTS"}

    # Step 1C: capture consent.
    applicable_frameworks = determine_consent_frameworks(
        patient_context, deployment_context)

    is_minor = patient_context.get("is_minor", False)
    consent_outcome = capture_consent(
        patient_id=patient_id,
        consent_type="speech_therapy_assessment",
        deployment_context=deployment_context,
        applicable_frameworks=applicable_frameworks,
        retention_terms={
            "audio_hours":          48,
            "feature_vector_days":  730,
            "score_retention_days":
                7300 if is_minor else 2190,
        },
        is_minor=is_minor)

    if not consent_outcome["granted"]:
        audit_log({
            "event_type":      "CONSENT_DECLINED",
            "patient_id_hash": _hash_value(patient_id),
            "timestamp":       _now_iso(),
        })
        return {"status": "CONSENT_DECLINED"}

    # Step 1D: bootstrap the session record.
    session_id = session_id_hint or (
        "sta-" + uuid.uuid4().hex[:16])
    population_profile = lookup_population_profile(
        patient_context)

    session_table.put(session_id, _to_decimal({
        "session_id":             session_id,
        "patient_id_hash":        _hash_value(patient_id),
        "slp_id":                 slp_id,
        "deployment_context":     deployment_context,
        "patient_population_profile": population_profile,
        "patient_context":        patient_context,
        "applicable_instruments": applicable_instruments,
        "consent_id":             consent_outcome["consent_id"],
        "applicable_frameworks":  applicable_frameworks,
        "prior_session_ref":
            lookup_most_recent_session(patient_id),
        "active_goals":
            lookup_active_goals(patient_id),
        "started_at":             _now_iso(),
        "feature_pipeline_version":
            FEATURE_PIPELINE_VERSION,
        "scoring_engine_version":
            SCORING_ENGINE_VERSION,
        "status":                 "setup_complete",
    }))

    event_bus.put_events([{
        "Source":       "speech_therapy_assessment",
        "DetailType":   "session_setup_complete",
        "EventBusName": SLP_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":     session_id,
            "instrument_count":
                len(applicable_instruments),
            "population_profile": population_profile,
            "deployment_context":
                deployment_context.get("context_type"),
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "SessionsInitiated", 1,
        "Count",
        dimensions={
            "deployment_context":
                deployment_context.get(
                    "context_type", "unknown"),
            "population_profile": population_profile,
        })

    audit_log({
        "event_type":          "SESSION_SETUP_COMPLETE",
        "session_id":          session_id,
        "instrument_count":
            len(applicable_instruments),
        "population_profile":  population_profile,
        "deployment_context":
            deployment_context.get("context_type"),
        "applicable_frameworks": applicable_frameworks,
        "timestamp":           _now_iso(),
    })

    return {
        "status":      "READY_TO_CAPTURE",
        "session_id":  session_id,
        "instruments": applicable_instruments,
    }
```

---

## Step 2: Capture Audio per Task with Task-Aware Quality Assessment and Recapture Prompts

*The pseudocode calls this `capture_session_audio(...)`. Each instrument has its own task structure: articulation inventories elicit one stimulus at a time, fluency probes capture continuous speech segments, voice-quality tasks elicit sustained vowels, connected-speech tasks capture longer narrative samples. The capture system handles each task type appropriately, runs quality checks per the task's thresholds, and prompts for recapture on failure. Skip the per-task quality gating and the system silently scores low-quality audio, producing unreliable results that the SLP has to manually override.*

```python
def present_stimulus(task):
    """
    Present the stimulus to the patient. Production drives
    the device or clinic UI: showing a picture for
    articulation tasks, playing an audio prompt for
    sentence-imitation tasks, displaying a written passage
    for read-aloud tasks. The mock just prints the prompt.
    """
    return {
        "task_id":       task.get("task_id"),
        "stimulus_kind": task.get("task_type"),
        "presented_at":  _now_iso(),
    }


def capture_audio_with_task_quality(task, fixture_lookup):
    """
    Capture audio for one task and assess its quality
    in-line. Production drives the microphone capture, runs
    real-time SNR and clipping detection, and prompts the
    speaker (or SLP) to retry if the quality fails the
    thresholds. The mock returns a fixture per task_id.
    """
    fixture = fixture_lookup.get(task["task_id"], {})
    return {
        "task_id":          task["task_id"],
        "s3_uri":
            f"s3://{AUDIO_BUCKET}/"
            f"{fixture.get('session_id', 'demo-session')}/"
            f"{task['task_id']}.wav",
        "duration":
            fixture.get(
                "duration",
                task.get("expected_duration",
                          Decimal("1.5"))),
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
        "speaker_only_verified":
            fixture.get("speaker_only_verified", True),
    }


# Per-task fixtures wired up by run_demo before each
# scenario.
CURRENT_CAPTURE_FIXTURE = {}


def capture_session_audio(session_id):
    """
    Walk the speaker through each instrument's stimulus
    list, capture per-task audio with quality assessment,
    persist the captured tasks, and emit the
    session-captured event. Failures on required tasks
    short-circuit the session with an INSUFFICIENT_QUALITY
    status; failures on optional tasks log and continue.
    """
    state = session_table.get(session_id)
    captured_tasks = []

    for instrument in state.get("applicable_instruments", []):
        instrument_id = instrument["instrument_id"]
        for task in instrument.get("stimulus_list", []):
            present_stimulus(task)

            captured_audio = capture_audio_with_task_quality(
                task=task,
                fixture_lookup=CURRENT_CAPTURE_FIXTURE)

            # Stamp the session_id onto every fixture so the
            # demo's S3 paths are session-specific.
            captured_audio["s3_uri"] = (
                f"s3://{AUDIO_BUCKET}/{session_id}/"
                f"{task['task_id']}.wav")

            quality_score = Decimal(str(
                captured_audio["quality_score"]))
            min_quality = Decimal(str(
                task.get("minimum_quality",
                          DEFAULT_MIN_TASK_QUALITY)))

            if quality_score < min_quality:
                audit_log({
                    "event_type":     "TASK_QUALITY_FAILED",
                    "session_id":     session_id,
                    "instrument_id":  instrument_id,
                    "task_id":        task["task_id"],
                    "quality_score":
                        float(quality_score),
                    "min_required":   float(min_quality),
                    "timestamp":      _now_iso(),
                })
                if task.get("required", True):
                    session_table.update(session_id, {
                        "status":        "quality_failed",
                        "failed_task":   task["task_id"],
                        "completed_at":  _now_iso(),
                    })
                    return {
                        "status":      "INSUFFICIENT_QUALITY",
                        "session_id":  session_id,
                        "failed_task": task["task_id"],
                    }
                else:
                    continue

            # Persist the captured audio to S3. Production
            # uses customer-managed KMS keys for encryption.
            s3_store.put_object(
                bucket=AUDIO_BUCKET,
                key=f"{session_id}/{task['task_id']}.wav",
                body=b"<mock audio bytes>",
                metadata={
                    "session_id":     session_id,
                    "instrument_id":  instrument_id,
                    "task_id":        task["task_id"],
                    "duration":
                        str(captured_audio["duration"]),
                    "snr_db":
                        str(captured_audio["snr_db"]),
                })

            captured_tasks.append({
                "instrument_id":     instrument_id,
                "task_id":           task["task_id"],
                "task_type":         task.get("task_type"),
                "expected_target":   task.get(
                    "expected_target"),
                "expected_phonemes": task.get(
                    "expected_phonemes"),
                "audio_ref":         captured_audio["s3_uri"],
                "duration_seconds":
                    captured_audio["duration"],
                "quality_score":
                    captured_audio["quality_score"],
                "sample_rate":
                    captured_audio["sample_rate"],
                "codec":             captured_audio["codec"],
                "snr_db":            captured_audio["snr_db"],
                "clipping_detected":
                    captured_audio["clipping"]
                    > Decimal("0.5"),
                "speaker_only_verified":
                    captured_audio["speaker_only_verified"],
                "linguistic_features_requested":
                    task.get("linguistic_features"),
            })

    session_table.update(session_id, _to_decimal({
        "captured_tasks":         captured_tasks,
        "capture_completed_at":   _now_iso(),
        "status":                 "captured",
    }))

    event_bus.put_events([{
        "Source":       "speech_therapy_assessment",
        "DetailType":   "session_captured",
        "EventBusName": SLP_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":  session_id,
            "task_count":  len(captured_tasks),
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "SessionsCaptured", 1, "Count",
        dimensions={
            "population_profile":
                state.get("patient_population_profile",
                            "unknown"),
        })

    audit_log({
        "event_type":     "SESSION_CAPTURED",
        "session_id":     session_id,
        "task_count":     len(captured_tasks),
        "timestamp":      _now_iso(),
    })

    return {
        "status":      "CAPTURED",
        "session_id":  session_id,
        "task_count":  len(captured_tasks),
    }
```

---

## Step 3: Extract Acoustic, Phonetic, and Linguistic Features per Task

*The pseudocode calls this `extract_features(...)`. Each task is processed through the appropriate feature pipeline: articulation tasks run through forced alignment and phoneme classification; fluency tasks run through fluency-event detection; voice-quality tasks run through acoustic-feature extraction; connected-speech tasks add transcription and linguistic-feature extraction. Per-feature confidence is captured throughout. Skip the disordered-speech-tolerant configuration and the alignment fails on the population the system is meant to serve.*

```python
def select_alignment_endpoint(population_profile, task_type):
    """Pick the per-population alignment endpoint."""
    return ALIGNMENT_ENDPOINTS.get(
        population_profile,
        ALIGNMENT_ENDPOINTS.get("adult_typical"))


def select_phoneme_endpoint(population_profile):
    """Pick the per-population phoneme classifier endpoint."""
    return PHONEME_CLASSIFIER_ENDPOINTS.get(
        population_profile,
        PHONEME_CLASSIFIER_ENDPOINTS.get("adult_typical"))


def select_fluency_endpoint(population_profile):
    """Pick the per-population fluency-detection endpoint."""
    return FLUENCY_ENDPOINTS.get(
        population_profile,
        FLUENCY_ENDPOINTS.get("adult_typical"))


def select_voice_quality_endpoint(population_profile):
    """Pick the per-population voice-quality endpoint."""
    return VOICE_QUALITY_ENDPOINTS.get(
        population_profile,
        VOICE_QUALITY_ENDPOINTS.get("adult_voice_disorder"))


def parse_alignment(raw_response):
    """Parse the alignment payload from the SageMaker
    response."""
    body = json.loads(raw_response["body"]) \
        if isinstance(raw_response.get("body"), str) \
        else raw_response.get("body", {})
    return body.get("alignment", {})


def parse_phoneme_classification(raw_response):
    """Parse the phoneme-classification payload."""
    body = json.loads(raw_response["body"]) \
        if isinstance(raw_response.get("body"), str) \
        else raw_response.get("body", {})
    return body.get("phoneme_classification", {})


def parse_fluency_events(raw_response):
    """Parse the fluency-events payload."""
    body = json.loads(raw_response["body"]) \
        if isinstance(raw_response.get("body"), str) \
        else raw_response.get("body", {})
    return body.get("fluency_events", [])


def parse_voice_quality(raw_response):
    """Parse the voice-quality payload."""
    body = json.loads(raw_response["body"]) \
        if isinstance(raw_response.get("body"), str) \
        else raw_response.get("body", {})
    return body.get("voice_quality", {})


def compute_prosodic_features(audio_ref, alignment):
    """
    Compute prosodic features (articulation rate, pause
    distribution, F0 mean/std, pitch range) from the audio
    and the alignment. Production calls a feature-extraction
    service or runs an in-process pipeline; the demo returns
    canned values per audio_ref.
    """
    fixture = PROSODIC_FEATURE_FIXTURES.get(audio_ref, {})
    return {
        "articulation_rate":
            fixture.get("articulation_rate",
                          Decimal("4.5")),
        "pause_distribution":
            fixture.get("pause_distribution",
                          Decimal("0.18")),
        "f0_mean":
            fixture.get("f0_mean", Decimal("220")),
        "f0_std":
            fixture.get("f0_std", Decimal("32")),
        "pitch_range":
            fixture.get("pitch_range", Decimal("85")),
    }


def extract_linguistic_features(transcript, patient_age,
                                    requested_features):
    """
    Extract linguistic features from a connected-speech
    transcript. Production runs an NLP pipeline (mean length
    of utterance, lexical diversity, syntactic complexity,
    narrative coherence, idea density); the demo returns
    canned values per (transcript, feature) pair.
    """
    if not requested_features:
        return {}
    return {
        feature: LINGUISTIC_FEATURE_FIXTURES.get(
            (transcript, feature),
            Decimal("0.5"))
        for feature in requested_features
    }


# Per-task feature fixtures wired up by run_demo.
PROSODIC_FEATURE_FIXTURES = {}
LINGUISTIC_FEATURE_FIXTURES = {}


def extract_features(session_id):
    """
    For each captured task, call the appropriate per-
    population SageMaker endpoints to produce alignment,
    phoneme classification, fluency events, voice-quality
    features, prosodic features, and (for connected speech)
    transcript-derived linguistic features. Persist the
    feature set to S3.
    """
    state = session_table.get(session_id)
    population_profile = state.get(
        "patient_population_profile", "adult_typical")
    feature_set = {
        "session_id":          session_id,
        "population_profile":  population_profile,
        "per_task_features":   {},
        "model_versions":      {},
    }

    for captured_task in state.get("captured_tasks", []):
        task_id = captured_task["task_id"]
        task_type = captured_task.get("task_type", "")
        per_task = {"task_id": task_id}

        # Step 3A: forced alignment for articulation tasks
        # and read-passage tasks.
        if task_type in (
                "single_word_articulation",
                "phonological_pattern_probe",
                "diadochokinetic_rate",
                "read_passage"):
            alignment_endpoint = select_alignment_endpoint(
                population_profile=population_profile,
                task_type=task_type)
            alignment_response = sagemaker_mock.invoke_endpoint(
                endpoint_name=alignment_endpoint,
                content_type="application/json",
                body=json.dumps({
                    "audio_ref":
                        captured_task["audio_ref"],
                    "task_id":  task_id,
                    "expected_target":
                        captured_task.get(
                            "expected_target"),
                    "expected_phonemes":
                        captured_task.get(
                            "expected_phonemes"),
                }, default=str))
            per_task["alignment"] = parse_alignment(
                alignment_response)
            feature_set["model_versions"][
                f"alignment_{task_id}"] = (
                alignment_endpoint)

        # Step 3B: phoneme classification (substitution,
        # omission, distortion detection) for articulation
        # tasks.
        if task_type in (
                "single_word_articulation",
                "phonological_pattern_probe",
                "diadochokinetic_rate"):
            phoneme_endpoint = select_phoneme_endpoint(
                population_profile=population_profile)
            phoneme_response = sagemaker_mock.invoke_endpoint(
                endpoint_name=phoneme_endpoint,
                content_type="application/json",
                body=json.dumps({
                    "audio_ref":
                        captured_task["audio_ref"],
                    "task_id":      task_id,
                    "alignment":
                        per_task.get("alignment"),
                    "expected_phonemes":
                        captured_task.get(
                            "expected_phonemes"),
                }, default=str))
            per_task["phoneme_classification"] = (
                parse_phoneme_classification(phoneme_response))
            feature_set["model_versions"][
                f"phoneme_{task_id}"] = phoneme_endpoint

        # Step 3C: fluency event detection for fluency tasks.
        if task_type in (
                "fluency_probe_reading",
                "fluency_probe_conversation",
                "fluency_probe_picture_description"):
            fluency_endpoint = select_fluency_endpoint(
                population_profile=population_profile)
            fluency_response = sagemaker_mock.invoke_endpoint(
                endpoint_name=fluency_endpoint,
                content_type="application/json",
                body=json.dumps({
                    "audio_ref":
                        captured_task["audio_ref"],
                    "task_id":  task_id,
                }, default=str))
            per_task["fluency_events"] = parse_fluency_events(
                fluency_response)
            feature_set["model_versions"][
                f"fluency_{task_id}"] = fluency_endpoint

        # Step 3D: voice-quality acoustic features for
        # voice-quality tasks and any sustained-vowel tasks.
        if task_type in (
                "sustained_vowel_voice_quality",
                "cape_v_protocol",
                "vhi_protocol"):
            vq_endpoint = select_voice_quality_endpoint(
                population_profile=population_profile)
            vq_response = sagemaker_mock.invoke_endpoint(
                endpoint_name=vq_endpoint,
                content_type="application/json",
                body=json.dumps({
                    "audio_ref":
                        captured_task["audio_ref"],
                    "task_id":  task_id,
                }, default=str))
            per_task["voice_quality"] = parse_voice_quality(
                vq_response)
            feature_set["model_versions"][
                f"voice_quality_{task_id}"] = vq_endpoint

        # Step 3E: prosodic and rate features (computed for
        # most tasks where alignment is available).
        if per_task.get("alignment"):
            per_task["prosodic"] = compute_prosodic_features(
                audio_ref=captured_task["audio_ref"],
                alignment=per_task["alignment"])

        # Step 3F: connected-speech transcription and
        # linguistic-feature extraction.
        if task_type == "connected_speech_picture_description" \
                or task_type in (
                    "connected_speech_story_retell",
                    "connected_speech_conversation"):
            transcribe_mock.start_medical_transcription(
                job_name=(
                    f"linguistic-{uuid.uuid4().hex[:8]}"),
                audio_uri=captured_task["audio_ref"],
                language=state.get(
                    "patient_context", {}).get(
                    "primary_language", "en-US"))
            transcript = transcribe_mock.retrieve_transcript(
                captured_task["audio_ref"])
            per_task["transcript"] = transcript
            per_task["linguistic_features"] = (
                extract_linguistic_features(
                    transcript=transcript,
                    patient_age=state.get(
                        "patient_context", {}).get(
                        "age_years"),
                    requested_features=
                        captured_task.get(
                            "linguistic_features_requested",
                            [])))

        feature_set["per_task_features"][task_id] = per_task

    # Step 3G: persist the feature set to S3.
    feature_archive = s3_store.put_object(
        bucket=FEATURE_BUCKET,
        key=f"{session_id}/features.json",
        body=json.dumps(feature_set,
                          default=str).encode("utf-8"),
        metadata={"session_id": session_id})

    session_table.update(session_id, _to_decimal({
        "feature_set_archive_ref": feature_archive["uri"],
        "features_extracted_at":   _now_iso(),
        "status":                  "features_extracted",
    }))

    event_bus.put_events([{
        "Source":       "speech_therapy_assessment",
        "DetailType":   "features_extracted",
        "EventBusName": SLP_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":            session_id,
            "feature_archive_ref":   feature_archive["uri"],
            "task_count":
                len(feature_set["per_task_features"]),
        }),
    }])

    audit_log({
        "event_type":     "FEATURES_EXTRACTED",
        "session_id":     session_id,
        "task_count":
            len(feature_set["per_task_features"]),
        "timestamp":      _now_iso(),
    })

    return {
        "feature_set":          feature_set,
        "feature_archive_ref":  feature_archive["uri"],
    }
```

---

## Step 4: Score Each Instrument with Population-Norm Comparison and Per-Item SLP-Review Flagging

*The pseudocode calls this `score_instruments(...)`. For each assessment instrument, the scoring engine combines per-task features into instrument-aligned scores: percent-consonants-correct for articulation, percent-pattern-occurrence for phonological patterns, percent-syllables-stuttered for fluency, CAPE-V dimensions for voice quality, MLU and lexical-diversity for connected speech. Items with confidence below the threshold are flagged for SLP review rather than auto-scored. Population norms are applied to interpret the raw scores against age-and-sex-appropriate benchmarks. Skip the confidence-based flagging and the system silently misclassifies the items where it is uncertain.*

```python
def collect_features_for_instrument(feature_set, instrument):
    """Pull the per-task feature set entries that belong to
    this instrument's tasks."""
    per_task = feature_set.get("per_task_features", {})
    relevant_task_ids = {
        task["task_id"] for task in
        instrument.get("stimulus_list", [])
    }
    return {
        task_id: features for task_id, features in
        per_task.items()
        if task_id in relevant_task_ids
        or not relevant_task_ids
    }


def extract_item_features(instrument_features, item):
    """Pull the per-task features relevant to this scoring
    item."""
    return instrument_features.get(item.get("task_id"), {})


def score_item(item, features, scoring_method):
    """
    Score an individual item per the instrument's scoring
    rubric. For articulation items this is per-phoneme
    correct/substituted/omitted/distorted classification
    derived from the phoneme classifier; for connected-
    speech items this is per-feature scoring of MLU,
    lexical diversity, etc. The model confidence is
    returned alongside.
    """
    if scoring_method == "percent_consonants_correct":
        # Articulation scoring: per-phoneme outcome
        # derived from the phoneme classifier.
        phoneme_class = features.get(
            "phoneme_classification") or {}
        per_phoneme = phoneme_class.get(
            "per_phoneme", [])
        if not per_phoneme:
            return {
                "observed":     "unknown",
                "score_value": Decimal("0"),
                "confidence":  Decimal("0"),
                "evidence": {
                    "reason": "no_phoneme_classification"},
            }
        correct_count = sum(
            1 for p in per_phoneme
            if p.get("outcome") == "correct")
        confidence_values = [
            Decimal(str(p.get("confidence", 0)))
            for p in per_phoneme]
        avg_confidence = (
            sum(confidence_values)
            / Decimal(str(max(len(confidence_values), 1))))
        # Outcome label: if all phonemes are correct, the
        # item is "correct"; otherwise the label reflects
        # the dominant error pattern.
        if correct_count == len(per_phoneme):
            observed = "correct"
        else:
            error_outcomes = [
                p.get("outcome") for p in per_phoneme
                if p.get("outcome") != "correct"]
            observed = (error_outcomes[0]
                        if error_outcomes else "correct")
        return {
            "observed":      observed,
            "score_value":
                Decimal(str(correct_count))
                / Decimal(str(max(len(per_phoneme), 1))),
            "confidence":    avg_confidence,
            "evidence": {
                "per_phoneme": per_phoneme,
                "phoneme_count":
                    len(per_phoneme),
                "correct_count": correct_count,
            },
        }
    if scoring_method == "linguistic_feature_summary":
        ling = features.get("linguistic_features", {})
        if not ling:
            return {
                "observed":      "unknown",
                "score_value":   Decimal("0"),
                "confidence":    Decimal("0"),
                "evidence": {
                    "reason": "no_linguistic_features"},
            }
        return {
            "observed":      "scored",
            "score_value":   Decimal("1"),
            "confidence":    Decimal("0.78"),
            "evidence":      ling,
        }
    return {
        "observed":      "unknown",
        "score_value":   Decimal("0"),
        "confidence":    Decimal("0"),
        "evidence":      {"reason": "scoring_method_unknown"},
    }


def compute_instrument_summary(scoring_method, items):
    """Compute the per-instrument summary score from the
    contributing items."""
    if not items:
        return {
            "items_scored":      0,
            "summary_value":     Decimal("0"),
        }
    if scoring_method == "percent_consonants_correct":
        item_correct_counts = []
        item_substituted_counts = []
        item_omitted_counts = []
        item_distorted_counts = []
        total_phonemes = 0
        total_correct = 0
        for item in items:
            evidence = item.get("supporting_evidence", {})
            per_phoneme = evidence.get("per_phoneme", [])
            for phoneme in per_phoneme:
                total_phonemes += 1
                outcome = phoneme.get("outcome")
                if outcome == "correct":
                    total_correct += 1
            item_correct_counts.append(
                evidence.get("correct_count", 0))
        return {
            "items_scored":            len(items),
            "items_correct":           sum(
                1 for it in items
                if it.get("observed") == "correct"),
            "items_substituted":       sum(
                1 for it in items
                if it.get("observed") == "substituted"),
            "items_omitted":           sum(
                1 for it in items
                if it.get("observed") == "omitted"),
            "items_distorted":         sum(
                1 for it in items
                if it.get("observed") == "distorted"),
            "total_phonemes":          total_phonemes,
            "total_correct_phonemes":  total_correct,
            "summary_value":
                (Decimal(str(total_correct))
                 / Decimal(str(max(total_phonemes, 1)))),
            "summary_label":
                "percent_consonants_correct",
        }
    if scoring_method == "connected_speech_summary":
        # Aggregate the linguistic features across items.
        merged = {}
        for it in items:
            for k, v in it.get(
                    "supporting_evidence", {}).items():
                merged[k] = v
        return {
            "items_scored":      len(items),
            "linguistic_summary": merged,
        }
    return {
        "items_scored":   len(items),
        "summary_value":  Decimal("0"),
    }


def apply_norms(instrument_id, auto_summary, norm_reference):
    """
    Apply the selected norm reference to the auto-summary.
    For percent-consonants-correct, look up the percentile
    rank and the standard score; for connected-speech
    summaries, compare each linguistic feature against the
    age-band norm.
    """
    if not norm_reference:
        return {
            "norm_reference":     None,
            "percentile_rank":    None,
            "standard_score":     None,
        }
    norm_def = lookup_norm_reference(norm_reference)
    if not norm_def:
        return {
            "norm_reference":     norm_reference,
            "percentile_rank":    None,
            "standard_score":     None,
            "norm_provenance":    "unknown",
        }
    summary_value = Decimal(str(
        auto_summary.get("summary_value", 0)))
    percentile_rank = None
    if "percentile_table" in norm_def:
        for cutoff, percentile in norm_def[
                "percentile_table"]:
            if summary_value >= Decimal(str(cutoff)):
                percentile_rank = percentile
                break
    standard_score = None
    if "standard_score_table" in norm_def:
        for cutoff, ss in norm_def["standard_score_table"]:
            if summary_value >= Decimal(str(cutoff)):
                standard_score = ss
                break
    return {
        "norm_reference":     norm_reference,
        "percentile_rank":    percentile_rank,
        "standard_score":     standard_score,
        "norm_provenance":    norm_def.get(
            "norm_provenance"),
        "norm_publication_year":
            norm_def.get("norm_publication_year"),
    }


def classify_severity(instrument_id, auto_summary,
                          norm_comparison, severity_cutoffs):
    """Classify severity per the instrument-defined cutoff
    thresholds applied to the auto-summary value."""
    if not severity_cutoffs:
        return None
    summary_value = Decimal(str(
        auto_summary.get("summary_value", 0)))
    sorted_cutoffs = sorted(
        severity_cutoffs.items(),
        key=lambda kv: Decimal(str(kv[1])),
        reverse=True)
    for label, cutoff in sorted_cutoffs:
        if summary_value >= Decimal(str(cutoff)):
            return label
    return sorted_cutoffs[-1][0] if sorted_cutoffs else None


def detect_phonological_patterns(per_item_scores,
                                     pattern_definitions,
                                     patient_age):
    """
    Detect phonological patterns in the per-item scoring.
    For each pattern definition, count occurrences across
    the items that exhibit the rule and produce the
    percent-occurrence and the age-appropriateness flag.
    """
    patterns = []
    for pattern_def in pattern_definitions:
        # Production walks through the per-item per-phoneme
        # outcomes and detects the pattern's rule
        # (final-consonant-deletion, fronting, gliding).
        # The demo uses a fixture-driven simulation.
        detected = PHONOLOGICAL_PATTERN_FIXTURES.get(
            pattern_def["pattern"], {})
        if not detected:
            continue
        age_appropriate = (
            patient_age is None
            or Decimal(str(patient_age)) <=
                Decimal(str(pattern_def[
                    "age_appropriate_through_age"])))
        patterns.append({
            "pattern":           pattern_def["pattern"],
            "percent_occurrence":
                detected.get("percent_occurrence",
                                Decimal("0")),
            "age_appropriateness":
                "typical_for_age" if age_appropriate
                else "atypical_for_age",
            "target_for_therapy":
                not age_appropriate,
        })
    return patterns


# Fixture-driven phonological pattern detection.
PHONOLOGICAL_PATTERN_FIXTURES = {}


def score_instruments(session_id):
    """
    Score each applicable instrument with per-item
    confidence-based SLP-review flagging, population-norm
    comparison, and severity classification.
    """
    state = session_table.get(session_id)
    feature_archive = s3_store.get_object(
        bucket=FEATURE_BUCKET,
        key=f"{session_id}/features.json")
    feature_set = json.loads(
        feature_archive["body"].decode("utf-8"))
    scores = {}

    for instrument in state.get("applicable_instruments", []):
        instrument_id = instrument["instrument_id"]
        instrument_def = lookup_instrument_definition(
            instrument_id)
        if not instrument_def:
            continue

        instrument_features = collect_features_for_instrument(
            feature_set, instrument)
        confidence_threshold = Decimal(str(
            instrument_def.get(
                "confidence_threshold",
                DEFAULT_PER_ITEM_CONFIDENCE_THRESHOLD)))

        # Step 4A: per-item scoring with confidence.
        per_item_scores = []
        scoring_method = instrument_def.get("scoring_method")
        for item in instrument_def.get("scoring_items", []):
            item_features = extract_item_features(
                instrument_features, item)
            item_score = score_item(
                item=item,
                features=item_features,
                scoring_method=scoring_method)
            slp_review_flag = (
                item_score["confidence"]
                < confidence_threshold)
            per_item_scores.append({
                "item_id":           item.get("item_id"),
                "expected_target":   item.get(
                    "expected_target"),
                "observed":          item_score["observed"],
                "score_value":       item_score[
                    "score_value"],
                "model_confidence":  item_score["confidence"],
                "slp_review_flag":   slp_review_flag,
                "supporting_evidence":
                    item_score["evidence"],
            })

        # Step 4B: aggregate per-instrument summary across
        # auto-scored items (review-pending excluded from
        # auto-summary).
        auto_scored = [i for i in per_item_scores
                        if not i["slp_review_flag"]]
        review_pending = [i for i in per_item_scores
                           if i["slp_review_flag"]]
        auto_summary = compute_instrument_summary(
            scoring_method=scoring_method,
            items=auto_scored)

        # Step 4C: norm-referenced comparison.
        norm_comparison = apply_norms(
            instrument_id=instrument_id,
            auto_summary=auto_summary,
            norm_reference=instrument.get("norm_reference"))

        # Step 4D: severity classification.
        severity = classify_severity(
            instrument_id=instrument_id,
            auto_summary=auto_summary,
            norm_comparison=norm_comparison,
            severity_cutoffs=instrument_def.get(
                "severity_cutoffs", {}))

        # Step 4E: phonological-pattern detection where
        # applicable.
        phonological_patterns = None
        if instrument_def.get(
                "detects_phonological_patterns"):
            phonological_patterns = (
                detect_phonological_patterns(
                    per_item_scores=per_item_scores,
                    pattern_definitions=instrument_def.get(
                        "pattern_definitions", []),
                    patient_age=state.get(
                        "patient_context", {}).get(
                        "age_years")))

        scores[instrument_id] = {
            "per_item_scores":         per_item_scores,
            "review_pending_count":    len(review_pending),
            "auto_summary":            auto_summary,
            "norm_comparison":         norm_comparison,
            "severity_classification": severity,
            "phonological_patterns":
                phonological_patterns,
            "norm_reference_used":
                instrument.get("norm_reference"),
            "scoring_model_versions":
                feature_set.get("model_versions", {}),
            "scored_at":               _now_iso(),
        }

    session_table.update(session_id, _to_decimal({
        "instrument_scores":      scores,
        "scoring_completed_at":   _now_iso(),
        "status":                 "scored",
    }))

    for instrument_id, score in scores.items():
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "ReviewPendingRate",
            score["review_pending_count"], "Count",
            dimensions={
                "instrument_id":      instrument_id,
                "population_profile":
                    state.get(
                        "patient_population_profile",
                        "unknown"),
            })

    event_bus.put_events([{
        "Source":       "speech_therapy_assessment",
        "DetailType":   "scoring_completed",
        "EventBusName": SLP_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":   session_id,
            "instruments": list(scores.keys()),
        }),
    }])

    audit_log({
        "event_type":     "INSTRUMENTS_SCORED",
        "session_id":     session_id,
        "instrument_count": len(scores),
        "timestamp":      _now_iso(),
    })

    return scores
```

---

## Step 5: Compute Longitudinal Comparison Against Prior Sessions and Active Goals

*The pseudocode calls this `compute_longitudinal(...)`. Within-patient progress is the clinically richest signal. The system computes per-instrument deltas against the prior session, evaluates progress against each active therapy goal, and detects trajectory patterns. Skip the longitudinal layer and the SLP loses the comparison that drives most therapy-planning decisions.*

```python
def compute_score_delta(current_summary, prior_summary,
                            instrument_id):
    """Compute the delta between current and prior auto-
    summary values."""
    current = Decimal(str(current_summary.get(
        "summary_value", 0)))
    prior = Decimal(str(prior_summary.get(
        "summary_value", 0)))
    delta = current - prior
    return {
        "current": current,
        "prior":   prior,
        "delta":   delta,
        "interpretation":
            ("improvement_outside_typical_variation"
             if delta > DEFAULT_WITHIN_PATIENT_TYPICAL_VARIATION
             else "regression_outside_typical_variation"
             if delta <
                -DEFAULT_WITHIN_PATIENT_TYPICAL_VARIATION
             else "stable_within_typical_variation"),
    }


def lookup_within_patient_variation(patient_id_hash,
                                       instrument_id):
    """
    Look up the within-patient typical session-to-session
    variation. Production computes this from the patient's
    own history and per-instrument variance; the demo
    returns a default proxy.
    """
    return DEFAULT_WITHIN_PATIENT_TYPICAL_VARIATION


def analyze_trajectory(history, instrument_id,
                          within_patient_typical_variation):
    """
    Analyze the trajectory across the historical sessions
    plus the current session for this instrument. Production
    fits a simple linear or piecewise model and produces a
    direction label, slope, and confidence; the demo just
    pulls the most-recent and oldest values.
    """
    relevant = [
        h for h in history
        if instrument_id in (h.get("instrument_scores")
                              or {})]
    if len(relevant) < 2:
        return {
            "available":   False,
            "session_count": len(relevant),
        }
    relevant_sorted = sorted(
        relevant,
        key=lambda h: h.get("session_timestamp", ""))
    oldest = Decimal(str(relevant_sorted[0].get(
        "instrument_scores", {}).get(
        instrument_id, {}).get(
        "auto_summary", {}).get(
        "summary_value", 0)))
    newest = Decimal(str(relevant_sorted[-1].get(
        "instrument_scores", {}).get(
        instrument_id, {}).get(
        "auto_summary", {}).get(
        "summary_value", 0)))
    direction = (
        "improving" if newest - oldest >
                       within_patient_typical_variation
        else "regressing"
        if newest - oldest <
           -within_patient_typical_variation
        else "stable")
    return {
        "available":      True,
        "session_count":  len(relevant_sorted),
        "oldest_value":   oldest,
        "newest_value":   newest,
        "delta":          newest - oldest,
        "direction":      direction,
    }


def evaluate_goal_progress(goal, current_scores,
                              evaluation_rubric):
    """
    Evaluate progress on an active therapy goal against
    the current session's scoring. Production maps each
    goal's target_metric to a specific instrument-and-
    item subset; the demo uses the articulation summary as
    a proxy for the demo goals.
    """
    target_value = Decimal(str(goal.get(
        "target_value", 1)))
    baseline_value = Decimal(str(goal.get(
        "baseline_value", 0)))

    # Use the articulation auto-summary as a proxy for
    # both demo goals. Production maps goals to specific
    # instruments and per-item subsets explicitly.
    articulation_score = current_scores.get(
        "articulation_inventory_gfta_aligned", {})
    summary_value = Decimal(str(
        articulation_score.get(
            "auto_summary", {}).get(
            "summary_value", 0)))
    if target_value <= baseline_value:
        percent_progress = Decimal("0")
    else:
        percent_progress = (
            (summary_value - baseline_value)
            / (target_value - baseline_value))
        percent_progress = max(
            Decimal("0"), min(Decimal("1"),
                                percent_progress))

    on_track = percent_progress >= Decimal("0.5")
    if percent_progress >= Decimal("0.85"):
        recommended_action = (
            "near_target_consider_generalization_phase")
    elif on_track:
        recommended_action = "continue_current_therapy_plan"
    else:
        recommended_action = "consider_goal_modification"

    return {
        "current_value":     summary_value,
        "percent_progress":  percent_progress,
        "on_track":          on_track,
        "recommended_action": recommended_action,
    }


def detect_trajectory_patterns(longitudinal, goal_progress,
                                   pattern_thresholds=None):
    """Detect higher-order patterns across instruments and
    goals: plateau across multiple instruments, regression
    on specific target sounds, acceleration after
    intervention change."""
    flags = []
    instrument_directions = [
        (v.get("trajectory") or {}).get("direction")
        for v in longitudinal.values()
        if (v.get("trajectory") or {}).get("available")
    ]
    improving_count = sum(
        1 for d in instrument_directions if d == "improving")
    if improving_count >= 1:
        flags.append("improvement_in_targeted_sounds")
    near_target_goals = [
        g for g in goal_progress.values()
        if Decimal(str(g.get("percent_progress", 0)))
            >= Decimal("0.85")
    ]
    if near_target_goals:
        flags.append(
            "near_target_attainment_for_one_active_goal")
    return flags


def compute_longitudinal(session_id):
    """
    Compute per-instrument deltas, per-goal progress, and
    cross-instrument trajectory patterns.
    """
    state = session_table.get(session_id)
    current_scores = state.get("instrument_scores", {})

    # Step 5A: load prior sessions for this patient.
    prior_sessions = longitudinal_table.get_history(
        patient_id_hash=state.get("patient_id_hash"),
        window_months=TRAJECTORY_WINDOW_MONTHS,
        limit=20)

    longitudinal = {}
    # Step 5B: per-instrument longitudinal comparison.
    for instrument_id, current in current_scores.items():
        prior_for_instrument = [
            s for s in prior_sessions
            if instrument_id in (
                s.get("instrument_scores") or {})]
        if not prior_for_instrument:
            longitudinal[instrument_id] = {
                "first_assessment":     True,
                "trajectory":           None,
                "most_recent_delta":    None,
            }
            continue

        most_recent = prior_for_instrument[0]
        most_recent_delta = compute_score_delta(
            current_summary=current.get(
                "auto_summary", {}),
            prior_summary=most_recent.get(
                "instrument_scores", {}).get(
                instrument_id, {}).get(
                "auto_summary", {}),
            instrument_id=instrument_id)

        trajectory = analyze_trajectory(
            history=prior_for_instrument + [{
                "session_id":         session_id,
                "session_timestamp":
                    state.get("started_at"),
                "instrument_scores":  current_scores,
            }],
            instrument_id=instrument_id,
            within_patient_typical_variation=
                lookup_within_patient_variation(
                    state.get("patient_id_hash"),
                    instrument_id))

        longitudinal[instrument_id] = {
            "first_assessment":   False,
            "trajectory":         trajectory,
            "most_recent_delta":  most_recent_delta,
            "sessions_in_baseline":
                len(prior_for_instrument),
        }

    # Step 5C: per-goal progress evaluation.
    goal_progress = {}
    for goal in state.get("active_goals", []):
        progress = evaluate_goal_progress(
            goal=goal,
            current_scores=current_scores,
            evaluation_rubric=goal.get(
                "evaluation_rubric"))
        goal_progress[goal.get("goal_id")] = {
            "goal_text":         goal.get("goal_text"),
            "target_metric":     goal.get("target_metric"),
            "current_value":     progress["current_value"],
            "baseline_value":
                Decimal(str(goal.get(
                    "baseline_value", 0))),
            "target_value":
                Decimal(str(goal.get(
                    "target_value", 1))),
            "percent_progress":  progress["percent_progress"],
            "on_track":          progress["on_track"],
            "recommended_action":
                progress["recommended_action"],
        }

    # Step 5D: cross-instrument trajectory pattern detection.
    trajectory_patterns = detect_trajectory_patterns(
        longitudinal=longitudinal,
        goal_progress=goal_progress)

    session_table.update(session_id, _to_decimal({
        "longitudinal":             longitudinal,
        "goal_progress":            goal_progress,
        "trajectory_patterns":      trajectory_patterns,
        "longitudinal_completed_at": _now_iso(),
        "status":                   "longitudinal_computed",
    }))

    audit_log({
        "event_type":         "LONGITUDINAL_COMPUTED",
        "session_id":         session_id,
        "trajectory_pattern_count": len(trajectory_patterns),
        "goal_count":         len(goal_progress),
        "timestamp":          _now_iso(),
    })

    return {
        "longitudinal":         longitudinal,
        "goal_progress":        goal_progress,
        "trajectory_patterns":  trajectory_patterns,
    }
```

---

## Step 6: Hand Off to the SLP for Review, Override, and Clinical Interpretation

*The pseudocode calls these `slp_review_initiated(...)` and `slp_submits_review(...)`. The SLP-facing review interface presents the per-item scores with confidence values, highlights items flagged for review, and shows the longitudinal comparison alongside. The SLP can override individual item scores with reasoning capture, accept high-confidence items in bulk, and provide the clinical interpretation. Skip the SLP-in-the-loop step and the system ships uncertain items as confident-looking auto-scores and loses the feedback signal for ongoing model improvement.*

```python
def build_slp_review_package(session_id, instrument_scores,
                                longitudinal, goal_progress,
                                trajectory_patterns,
                                captured_tasks):
    """
    Build the SLP-facing review package. SLP-review-flagged
    items appear first; the SLP gets per-item playback,
    side-by-side prior-session comparison, and the
    institutional template for clinical interpretation
    capture.
    """
    return {
        "session_id":           session_id,
        "instrument_scores":    instrument_scores,
        "longitudinal":         longitudinal,
        "goal_progress":        goal_progress,
        "trajectory_patterns":  trajectory_patterns,
        "captured_tasks":       captured_tasks,
        "review_priority_items": [
            {
                "instrument_id":   instrument_id,
                "item_id":         item.get("item_id"),
                "expected_target": item.get(
                    "expected_target"),
                "observed":        item.get("observed"),
                "model_confidence":
                    item.get("model_confidence"),
            }
            for instrument_id, scores in
                instrument_scores.items()
            for item in scores.get("per_item_scores", [])
            if item.get("slp_review_flag")
        ],
    }


def slp_review_initiated(session_id, slp_id):
    """SLP opens the assessment for review."""
    state = session_table.get(session_id)
    review_package = build_slp_review_package(
        session_id=session_id,
        instrument_scores=state.get(
            "instrument_scores", {}),
        longitudinal=state.get("longitudinal", {}),
        goal_progress=state.get("goal_progress", {}),
        trajectory_patterns=state.get(
            "trajectory_patterns", []),
        captured_tasks=state.get("captured_tasks", []))
    session_table.update(session_id, {
        "slp_review_initiated_at": _now_iso(),
        "reviewing_slp_id":        slp_id,
        "status":                  "slp_reviewing",
    })
    audit_log({
        "event_type":  "SLP_REVIEW_INITIATED",
        "session_id":  session_id,
        "slp_id":      slp_id,
        "review_pending_total": len(
            review_package["review_priority_items"]),
        "timestamp":   _now_iso(),
    })
    return review_package


def lookup_item_score(scores, instrument_id, item_id):
    """Find an existing item score in the scoring set."""
    items = scores.get(instrument_id, {}).get(
        "per_item_scores", [])
    for it in items:
        if it.get("item_id") == item_id:
            return dict(it)
    return None


def apply_item_edit(scores, edit):
    """Apply an SLP edit to a per-item score."""
    items = scores.get(edit["instrument_id"], {}).get(
        "per_item_scores", [])
    for it in items:
        if it.get("item_id") == edit["item_id"]:
            it["observed"] = edit.get("new_value", {}).get(
                "observed", it.get("observed"))
            it["score_value"] = Decimal(str(
                edit.get("new_value", {}).get(
                    "score_value",
                    it.get("score_value", 0))))
            it["slp_edit_applied"] = True
            it["slp_edit_reasoning"] = edit.get("reasoning")
            it["slp_review_flag"] = False
            break


def slp_submits_review(session_id, slp_id, edits,
                          clinical_interpretation):
    """
    Apply SLP edits, recompute per-instrument summaries
    over the full edited item set, capture the clinical
    interpretation, and persist.
    """
    state = session_table.get(session_id)
    edited_scores = json.loads(
        json.dumps(state.get("instrument_scores", {}),
                     default=str))

    # Re-decimal the freshly deserialized scores so
    # downstream arithmetic stays in Decimal.
    edited_scores = _to_decimal(edited_scores)

    edit_history = []
    for edit in edits:
        original = lookup_item_score(
            edited_scores,
            edit.get("instrument_id"),
            edit.get("item_id"))
        apply_item_edit(edited_scores, edit)
        edit_history.append({
            "instrument_id":   edit.get("instrument_id"),
            "item_id":         edit.get("item_id"),
            "original_value":  original,
            "new_value":       edit.get("new_value"),
            "slp_reasoning":   edit.get("reasoning"),
            "edited_by":       slp_id,
            "edited_at":       _now_iso(),
        })

    # Step 6C: recompute per-instrument summaries with all
    # items now scored (auto plus SLP-edited).
    final_summaries = {}
    for instrument_id, scores in edited_scores.items():
        instrument_def = lookup_instrument_definition(
            instrument_id)
        if not instrument_def:
            continue
        all_items = scores.get("per_item_scores", [])
        final_summary = compute_instrument_summary(
            scoring_method=instrument_def.get(
                "scoring_method"),
            items=all_items)
        final_norm_comparison = apply_norms(
            instrument_id=instrument_id,
            auto_summary=final_summary,
            norm_reference=scores.get(
                "norm_reference_used"))
        final_severity = classify_severity(
            instrument_id=instrument_id,
            auto_summary=final_summary,
            norm_comparison=final_norm_comparison,
            severity_cutoffs=instrument_def.get(
                "severity_cutoffs", {}))
        final_summaries[instrument_id] = {
            "final_summary":         final_summary,
            "final_norm_comparison": final_norm_comparison,
            "final_severity":        final_severity,
            "phonological_patterns":
                scores.get("phonological_patterns"),
            "slp_edits_count":
                sum(1 for e in edit_history
                    if e["instrument_id"] == instrument_id),
        }

    clinical_record = {
        "working_diagnosis_or_hypothesis":
            clinical_interpretation.get("diagnosis"),
        "goal_modifications":
            clinical_interpretation.get(
                "goal_modifications", []),
        "new_goals":
            clinical_interpretation.get("new_goals", []),
        "recommended_therapy_frequency":
            clinical_interpretation.get(
                "therapy_frequency"),
        "recommended_therapy_modality":
            clinical_interpretation.get(
                "therapy_modality"),
        "discharge_readiness":
            clinical_interpretation.get(
                "discharge_readiness", "not_yet"),
        "free_text_observations":
            clinical_interpretation.get(
                "observations", ""),
        "finalized_by_slp":   slp_id,
        "finalized_at":       _now_iso(),
    }

    session_table.update(session_id, _to_decimal({
        "edited_scores":           edited_scores,
        "final_summaries":         final_summaries,
        "edit_history":            edit_history,
        "clinical_record":         clinical_record,
        "slp_review_completed_at": _now_iso(),
        "status":                  "slp_review_complete",
    }))

    event_bus.put_events([{
        "Source":       "speech_therapy_assessment",
        "DetailType":   "slp_review_complete",
        "EventBusName": SLP_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":  session_id,
            "edit_count":  len(edit_history),
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "SLPEditCount",
        len(edit_history), "Count",
        dimensions={
            "population_profile":
                state.get(
                    "patient_population_profile",
                    "unknown"),
        })

    audit_log({
        "event_type":   "SLP_REVIEW_COMPLETE",
        "session_id":   session_id,
        "slp_id":       slp_id,
        "edit_count":   len(edit_history),
        "timestamp":    _now_iso(),
    })

    return {
        "status":           "REVIEW_COMPLETE",
        "edit_count":       len(edit_history),
        "final_summaries":  final_summaries,
    }
```

---

## Step 7: Generate the Assessment Report, Family Summary, and EHR or SIS Write-Back

*The pseudocode calls this `generate_documentation(...)`. The system generates a structured assessment report from the SLP-validated scores and clinical interpretation, plus a parent-and-patient-friendly summary at appropriate reading level. Documentation flows to the EHR (clinical settings) or school SIS (school deployments) as discrete data, FHIR resources, and PDF artifacts. Skip the structured documentation and the SLP loses the productivity benefit; skip the family summary and parents and patients are left with clinical-jargon outputs they cannot act on.*

```python
def extract_metadata(state):
    """Pull the metadata fields the report templates need."""
    patient_context = state.get("patient_context", {})
    return {
        "session_id":          state.get("session_id"),
        "session_started_at":  state.get("started_at"),
        "slp_id":              state.get(
            "reviewing_slp_id"),
        "deployment_context":
            state.get("deployment_context", {}).get(
                "context_type"),
        "patient_age_years":
            patient_context.get("age_years"),
        "patient_sex":         patient_context.get("sex"),
        "patient_primary_language":
            patient_context.get("primary_language"),
    }


def build_report_prompt(input_data, template):
    """Assemble the prompt for Bedrock's SLP-report
    generation."""
    return {
        "input":     input_data,
        "template":  template,
        "version":   SLP_REPORT_PROMPT_VERSION,
    }


def build_family_summary_prompt(input_data, template):
    """Assemble the prompt for Bedrock's family-summary
    generation."""
    return {
        "input":     input_data,
        "template":  template,
        "version":   FAMILY_SUMMARY_PROMPT_VERSION,
    }


def simplify_for_family(final_summaries):
    """Strip clinical-jargon details out of the final
    summaries for family-facing rendering."""
    simplified = {}
    for instrument_id, summary in final_summaries.items():
        simplified[instrument_id] = {
            "severity":
                summary.get("final_severity"),
            "summary_value":
                summary.get("final_summary", {}).get(
                    "summary_value"),
        }
    return simplified


def extract_progress_highlights(goal_progress):
    """Pull the most important goal-progress points for the
    family summary."""
    highlights = []
    for goal_id, progress in goal_progress.items():
        if progress.get("on_track"):
            highlights.append({
                "goal_text":         progress.get(
                    "goal_text"),
                "percent_progress":
                    progress.get("percent_progress"),
                "status":            "on_track",
            })
        else:
            highlights.append({
                "goal_text":         progress.get(
                    "goal_text"),
                "percent_progress":
                    progress.get("percent_progress"),
                "status":            "needs_attention",
            })
    return highlights


def derive_home_practice(clinical_record):
    """Derive home-practice recommendations from the
    SLP's clinical interpretation."""
    return clinical_record.get(
        "free_text_observations", "")


def determine_reading_level_for_family(patient_context):
    """Pick a reading level appropriate for the family. For
    pediatric patients, target the parent's likely reading
    level (typically 6th-8th grade for general-public
    health communication)."""
    if patient_context.get("is_minor"):
        return "grade_6_to_8_for_parent"
    return "grade_6_to_8_for_patient"


SLP_REPORT_TEMPLATE = (
    "Standard SLP assessment-report structure: history, "
    "instruments-administered, results-by-instrument, "
    "clinical-impressions, goals-and-recommendations.")
FAMILY_SUMMARY_TEMPLATE = (
    "Family-friendly summary at appropriate reading level "
    "with progress highlights and home-practice "
    "recommendations.")


def build_fhir_observation(patient_id, instrument_id,
                              instrument_summary,
                              session_started_at):
    """Build an FHIR Observation resource for one
    instrument's final summary."""
    summary_value = instrument_summary.get(
        "final_summary", {}).get("summary_value")
    if summary_value is None:
        summary_value = 0
    return {
        "resourceType":  "Observation",
        "status":        "final",
        "category": [{
            "coding": [{
                "system":
                    "http://terminology.hl7.org/"
                    "CodeSystem/observation-category",
                "code":    "exam",
                "display": "Exam",
            }],
        }],
        "code": {
            "coding": [{
                "system":
                    "http://institutional-codes.example.com/"
                    "speech-therapy-assessment",
                "code":    instrument_id,
                "display":
                    f"Speech therapy: {instrument_id}",
            }],
        },
        "subject":       {"reference":
                              f"Patient/{patient_id}"},
        "effectiveDateTime": session_started_at,
        "valueQuantity": {
            "value":  float(summary_value),
            "unit":   "auto_summary_value",
        },
        "interpretation": [{
            "coding": [{
                "system":
                    "http://institutional-codes.example.com/"
                    "speech-therapy-severity",
                "code":
                    instrument_summary.get(
                        "final_severity") or "unknown",
            }],
        }],
        "extension": [
            {"url": "norm_reference",
             "valueString":
                 (instrument_summary.get(
                     "final_norm_comparison") or {}).get(
                     "norm_reference") or "unknown"},
            {"url": "slp_edits_count",
             "valueInteger":
                 instrument_summary.get(
                     "slp_edits_count", 0)},
        ],
    }


def build_fhir_goal(patient_id, goal_modification):
    """Build an FHIR Goal resource for an SLP-recommended
    goal modification or new goal."""
    return {
        "resourceType":  "Goal",
        "lifecycleStatus": "active",
        "subject":       {"reference":
                              f"Patient/{patient_id}"},
        "description": {
            "text":
                goal_modification.get("goal_text",
                                          "Updated speech-"
                                          "therapy goal"),
        },
        "note": [{
            "text":
                goal_modification.get("modification",
                                          ""),
        }],
    }


def build_fhir_resources(observation_per_instrument,
                            goal_resources,
                            document_reference_for_report,
                            patient_id):
    """Assemble the full FHIR resource set for the
    documentation hand-off."""
    resources = []
    for instrument_id, summary in (
            observation_per_instrument or {}).items():
        resources.append({
            "resource_type": "Observation",
            "body": build_fhir_observation(
                patient_id=patient_id,
                instrument_id=instrument_id,
                instrument_summary=summary,
                session_started_at=
                    document_reference_for_report.get(
                        "session_started_at",
                        _now_iso())),
        })
    for goal in (goal_resources or []):
        resources.append({
            "resource_type": "Goal",
            "body": build_fhir_goal(
                patient_id=patient_id,
                goal_modification=goal),
        })
    return resources


def convert_to_sis_format(slp_report, fhir_resources):
    """Translate the SLP-report content and FHIR resources
    into the school SIS's expected format. Production
    targets the specific SIS vendor's API; the demo
    produces a generic dict."""
    return {
        "report_text": slp_report,
        "structured_results": fhir_resources,
    }


def generate_documentation(session_id):
    """
    Generate the SLP-facing assessment report, the family-
    facing summary, the FHIR resource set, and the EHR or
    SIS write-back per the deployment context.
    """
    state = session_table.get(session_id)
    final_summaries = state.get("final_summaries", {})
    deployment_context = state.get(
        "deployment_context", {})

    # Step 7A: SLP-facing assessment report.
    slp_report_input = {
        "session_metadata":   extract_metadata(state),
        "instrument_results": final_summaries,
        "per_item_detail":
            state.get("edited_scores", {}),
        "longitudinal":
            state.get("longitudinal", {}),
        "goal_progress":
            state.get("goal_progress", {}),
        "clinical_record":
            state.get("clinical_record", {}),
        "edit_history":
            state.get("edit_history", []),
    }
    slp_report_response = bedrock_mock.render_slp_report(
        session_id=session_id,
        report_input=slp_report_input,
        guardrail_id=SLP_REPORT_GUARDRAIL_ID)
    slp_report = json.loads(
        slp_report_response["body"]).get("content", "")

    # Step 7B: family-friendly summary.
    family_summary_input = {
        "session_metadata":   extract_metadata(state),
        "instrument_results_simplified":
            simplify_for_family(final_summaries),
        "progress_highlights":
            extract_progress_highlights(
                state.get("goal_progress", {})),
        "home_practice_recommendations":
            derive_home_practice(
                state.get("clinical_record", {})),
        "target_reading_level":
            determine_reading_level_for_family(
                state.get("patient_context", {})),
    }
    family_summary_response = (
        bedrock_mock.render_family_summary(
            session_id=session_id,
            summary_input=family_summary_input,
            guardrail_id=FAMILY_SUMMARY_GUARDRAIL_ID))
    family_summary = json.loads(
        family_summary_response["body"]).get(
        "content", "")

    # Step 7C: assemble FHIR resources.
    patient_id = lookup_patient_id(
        state.get("patient_id_hash"))
    fhir_resources = build_fhir_resources(
        observation_per_instrument=final_summaries,
        goal_resources=(
            (state.get("clinical_record") or {}).get(
                "new_goals", []) +
            (state.get("clinical_record") or {}).get(
                "goal_modifications", [])),
        document_reference_for_report={
            "session_started_at":
                state.get("started_at"),
        },
        patient_id=patient_id)

    # Step 7D: persist artifacts.
    report_archive_object = s3_store.put_object(
        bucket=REPORT_ARCHIVE_BUCKET,
        key=f"{session_id}/slp_report.json",
        body=json.dumps({
            "slp_report":       slp_report,
            "family_summary":   family_summary,
            "fhir_resources":   fhir_resources,
        }, default=str).encode("utf-8"),
        metadata={"session_id": session_id})

    # Step 7E: write to EHR or SIS per deployment context.
    documentation_target = deployment_context.get(
        "documentation_target", "fhir_ehr")
    if documentation_target == "fhir_ehr":
        for resource in fhir_resources:
            healthlake.create_resource(
                datastore_id=HEALTHLAKE_DATASTORE_ID,
                resource_type=resource["resource_type"],
                resource=resource["body"])
    elif documentation_target == "school_sis":
        school_sis.write_assessment(
            student_id=state.get(
                "patient_context", {}).get("student_id"),
            assessment_record=convert_to_sis_format(
                slp_report, fhir_resources),
            iep_alignment=deployment_context.get(
                "iep_context"))

    session_table.update(session_id, _to_decimal({
        "slp_report_ref":        report_archive_object[
            "uri"],
        "family_summary_ref":    report_archive_object[
            "uri"],
        "documentation_completed_at": _now_iso(),
        "status":                "documented",
    }))

    event_bus.put_events([{
        "Source":       "speech_therapy_assessment",
        "DetailType":   "documentation_complete",
        "EventBusName": SLP_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":  session_id,
            "documentation_target": documentation_target,
        }),
    }])

    audit_log({
        "event_type":  "DOCUMENTATION_COMPLETE",
        "session_id":  session_id,
        "documentation_target": documentation_target,
        "timestamp":   _now_iso(),
    })

    return {
        "slp_report":      slp_report,
        "family_summary":  family_summary,
        "fhir_resources":  fhir_resources,
        "report_archive_ref":
            report_archive_object["uri"],
    }
```

---

## Step 8: Audit, Retain Audio per Consent, and Feed Post-Deployment Surveillance

*The pseudocode calls this `audit_and_surveillance(...)`. Every session produces a durable audit record with the SLP's edits, per-item confidence values, model versions used, and outcome links where available. Audio is retained per consent and then deleted; feature vectors are retained longer for model improvement and longitudinal analysis. Per-population surveillance metrics feed dashboards that track the system's performance against SLP gold-standard scoring over time. Skip the surveillance pipeline and per-population drift surfaces only through SLP complaints.*

```python
def lookup_audio_retention(consent_id, deployment_context):
    """
    Look up the audio-retention window for this consent and
    deployment context. Production reads from the consent
    record; the demo uses a default of 48 hours.
    """
    if deployment_context.get("context_type") == "school_based":
        return {"hours": 24}
    return {"hours": 48}


def schedule_audio_deletion(audio_refs, delete_after):
    """Schedule audio deletion per the consent retention
    window. Production uses S3 lifecycle keyed on tags or
    prefixes; the demo logs the intended deletion and
    immediately removes the mock object."""
    for audio_ref in audio_refs:
        audit_log({
            "event_type":     "AUDIO_DELETION_SCHEDULED",
            "audio_ref_hash": _hash_value(audio_ref),
            "delete_after_hours":
                delete_after.get("hours"),
            "timestamp":      _now_iso(),
        })
        if audio_ref and audio_ref.startswith("s3://"):
            without_scheme = audio_ref[5:]
            slash = without_scheme.find("/")
            if slash > 0:
                bucket = without_scheme[:slash]
                key = without_scheme[slash + 1:]
                s3_store.delete_object(
                    bucket, key,
                    reason="consent_retention_expired")


def count_edits_for_instrument(edit_history, instrument_id):
    """Count SLP edits attributable to one instrument."""
    return sum(1 for e in edit_history
                if e.get("instrument_id") == instrument_id)


def summarize_goal_progress(goal_progress):
    """Produce a compact summary of goal progress for the
    audit record."""
    return {
        goal_id: {
            "percent_progress":
                progress.get("percent_progress"),
            "on_track":
                progress.get("on_track"),
        }
        for goal_id, progress in goal_progress.items()
    }


def summarize_edited_scores(edited_scores):
    """Produce a compact summary of the edited per-item
    scores for longitudinal storage."""
    return {
        instrument_id: {
            "items_total":
                len(scores.get("per_item_scores", [])),
            "items_slp_edited":
                sum(1 for it in scores.get(
                    "per_item_scores", [])
                    if it.get("slp_edit_applied")),
        }
        for instrument_id, scores in edited_scores.items()
    }


def extract_capture_metadata(state):
    """Pull the recording-chain capture metadata for the
    longitudinal record."""
    captured = state.get("captured_tasks", [])
    if not captured:
        return {}
    return {
        "device_class":
            state.get("deployment_context", {}).get(
                "device_class"),
        "task_count":   len(captured),
        "min_quality_score":
            min((Decimal(str(t.get("quality_score", 1)))
                 for t in captured),
                default=Decimal("1")),
    }


def audit_and_surveillance(session_id):
    """
    Produce the durable audit record, schedule audio
    deletion per consent, emit per-population surveillance
    metrics, and write the longitudinal-record entry.
    """
    state = session_table.get(session_id)
    final_summaries = state.get("final_summaries", {})
    edit_history = state.get("edit_history", [])

    audit_record = {
        "session_id":         session_id,
        "patient_id_hash":    state.get("patient_id_hash"),
        "patient_population_profile":
            state.get("patient_population_profile"),
        "slp_id":             state.get(
            "reviewing_slp_id"),
        "deployment_context":
            state.get("deployment_context"),
        "captured_at":        state.get("started_at"),
        "slp_review_completed_at":
            state.get("slp_review_completed_at"),
        "documentation_completed_at":
            state.get("documentation_completed_at"),
        "instruments_administered":
            list(final_summaries.keys()),
        "per_instrument_outcomes": {
            instrument_id: {
                "final_severity":
                    summary.get("final_severity"),
                "norm_reference_used":
                    state.get("instrument_scores", {}).get(
                        instrument_id, {}).get(
                        "norm_reference_used"),
                "review_pending_count_pre_slp":
                    state.get("instrument_scores", {}).get(
                        instrument_id, {}).get(
                        "review_pending_count"),
                "slp_edit_count_for_instrument":
                    count_edits_for_instrument(
                        edit_history, instrument_id),
                "model_versions":
                    state.get("instrument_scores", {}).get(
                        instrument_id, {}).get(
                        "scoring_model_versions"),
            }
            for instrument_id, summary in
                final_summaries.items()
        },
        "goal_progress_summary":
            summarize_goal_progress(
                state.get("goal_progress", {})),
        "consent_id":         state.get("consent_id"),
    }

    audit_object = s3_store.put_object(
        bucket=AUDIT_ARCHIVE_BUCKET,
        key=(f"audit/"
             f"{datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
             f"/{session_id}.json"),
        body=json.dumps(audit_record,
                          default=str).encode("utf-8"),
        metadata={"session_id": session_id})

    # Step 8A: schedule audio deletion per consent terms.
    audio_refs = [t.get("audio_ref") for t in
                   state.get("captured_tasks", [])
                   if t.get("audio_ref")]
    if audio_refs:
        schedule_audio_deletion(
            audio_refs=audio_refs,
            delete_after=lookup_audio_retention(
                consent_id=state.get("consent_id"),
                deployment_context=state.get(
                    "deployment_context", {})))

    # Step 8B: per-population surveillance metrics.
    for instrument_id, outcome in audit_record[
            "per_instrument_outcomes"].items():
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "SLPEditRate",
            outcome.get("slp_edit_count_for_instrument", 0),
            "Count",
            dimensions={
                "instrument_id":      instrument_id,
                "population_profile":
                    audit_record.get(
                        "patient_population_profile",
                        "unknown"),
                "deployment_context":
                    (audit_record.get(
                        "deployment_context") or {}).get(
                        "context_type", "unknown"),
            })
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE,
            "ReviewPendingPreSLP",
            outcome.get(
                "review_pending_count_pre_slp", 0),
            "Count",
            dimensions={
                "instrument_id":      instrument_id,
                "population_profile":
                    audit_record.get(
                        "patient_population_profile",
                        "unknown"),
            })

    # Step 8D: longitudinal-store update with this session.
    longitudinal_table.put(_to_decimal({
        "patient_id_hash":   state.get("patient_id_hash"),
        "session_id":        session_id,
        "session_timestamp": state.get("started_at"),
        "instrument_scores": final_summaries,
        "edited_scores_summary":
            summarize_edited_scores(
                state.get("edited_scores", {})),
        "goal_progress":
            state.get("goal_progress", {}),
        "trajectory_patterns":
            state.get("trajectory_patterns", []),
        "capture_metadata":
            extract_capture_metadata(state),
    }))

    session_table.update(session_id, _to_decimal({
        "audit_archive_ref":  audit_object["uri"],
        "audited_at":         _now_iso(),
        "status":             "audited",
    }))

    event_bus.put_events([{
        "Source":       "speech_therapy_assessment",
        "DetailType":   "session_audited",
        "EventBusName": SLP_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":         session_id,
            "audit_archive_ref":  audit_object["uri"],
        }),
    }])

    audit_log({
        "event_type":          "SESSION_AUDITED",
        "session_id":          session_id,
        "audit_archive_ref":   audit_object["uri"],
        "audio_refs_deleted":  len(audio_refs),
        "instrument_count":
            len(audit_record["per_instrument_outcomes"]),
        "timestamp":           _now_iso(),
    })

    return audit_record
```

---

## Putting It All Together

The pipeline ties together as a top-level handler that simulates a single end-to-end speech-therapy assessment session flowing through the eight stages. In a Lambda-and-Step-Functions deployment, the session-setup stage runs in response to the SLP's session-initiation request, the capture stage runs in response to the device-side capture-completion event, and the post-capture stages run as a Step Functions state machine; the demo orchestrates them inline so you can see the full sequence.

```python
def run_assessment_pipeline(slp_id, patient_id,
                                selected_instruments,
                                deployment_context,
                                slp_edits=None,
                                clinical_interpretation=None,
                                session_id_hint=None):
    """
    Drive a single speech-therapy assessment session end-to-
    end through all eight pipeline stages. Production splits
    this across multiple Lambdas with Step Functions
    orchestration; the demo collapses to a single function
    for readability.
    """
    # Stage 1: session setup.
    setup_result = session_initiated(
        slp_id=slp_id,
        patient_id=patient_id,
        selected_instruments=selected_instruments,
        deployment_context=deployment_context,
        session_id_hint=session_id_hint)
    if setup_result["status"] != "READY_TO_CAPTURE":
        return {"status": setup_result["status"],
                "stage":  "setup"}

    session_id = setup_result["session_id"]

    # Stage 2: audio capture.
    capture_result = capture_session_audio(session_id)
    if capture_result["status"] != "CAPTURED":
        return {"status": capture_result["status"],
                "stage":  "capture",
                "session_id": session_id}

    # Stage 3: feature extraction.
    feature_result = extract_features(session_id)

    # Stage 4: per-instrument scoring.
    scoring_result = score_instruments(session_id)

    # Stage 5: longitudinal comparison.
    longitudinal_result = compute_longitudinal(session_id)

    # Stage 6: SLP review and override.
    slp_review_initiated(session_id, slp_id)
    review_result = slp_submits_review(
        session_id=session_id,
        slp_id=slp_id,
        edits=slp_edits or [],
        clinical_interpretation=
            clinical_interpretation or {})

    # Stage 7: documentation generation.
    documentation_result = generate_documentation(session_id)

    # Stage 8: audit and surveillance.
    audit_record = audit_and_surveillance(session_id)

    return {
        "status":            "COMPLETE",
        "session_id":        session_id,
        "setup_result":      setup_result,
        "capture_result":    capture_result,
        "feature_result": {
            "feature_archive_ref":
                feature_result.get(
                    "feature_archive_ref"),
        },
        "scoring_result":    scoring_result,
        "longitudinal_result":
            longitudinal_result,
        "review_result":     review_result,
        "documentation_result": {
            "report_archive_ref":
                documentation_result.get(
                    "report_archive_ref"),
        },
        "audit_archive_ref":
            audit_record.get("audit_archive_ref")
            or f"audit/{session_id}.json",
    }
```

The demo runner wires up the mocks with fixture data for one end-to-end scenario.

```python
def run_demo():
    """
    Run a single end-to-end scenario that exercises the
    main paths through the speech-therapy assessment
    pipeline:
      Maya (6-year-old female, English, outpatient clinic)
      submits an articulation inventory plus a phonological-
      pattern analysis plus a connected-speech picture
      description as part of a 12-week reassessment. She
      has prior baseline samples; the trajectory shows
      improvement in the targeted sounds, and one of her
      goals is near target.
    """
    # pylint: disable=global-statement
    global sagemaker_mock, transcribe_mock, bedrock_mock
    global PROSODIC_FEATURE_FIXTURES
    global LINGUISTIC_FEATURE_FIXTURES
    global PHONOLOGICAL_PATTERN_FIXTURES
    global CURRENT_CAPTURE_FIXTURE

    session_id_demo = "sta-demo-maya-2026-05-23"

    # ---- Per-task capture fixtures ----
    capture_fixture = {
        "rabbit": {
            "session_id":      session_id_demo,
            "duration":        Decimal("1.4"),
            "quality_score":   Decimal("0.92"),
            "sample_rate":     44100,
            "codec":           "PCM_16",
            "snr_db":          Decimal("28.0"),
            "clipping_percent": Decimal("0.0"),
            "speaker_only_verified": True,
        },
        "sheep": {
            "session_id":      session_id_demo,
            "duration":        Decimal("1.2"),
            "quality_score":   Decimal("0.90"),
            "sample_rate":     44100,
            "codec":           "PCM_16",
            "snr_db":          Decimal("27.0"),
            "clipping_percent": Decimal("0.1"),
            "speaker_only_verified": True,
        },
        "thumb": {
            "session_id":      session_id_demo,
            "duration":        Decimal("1.1"),
            "quality_score":   Decimal("0.88"),
            "sample_rate":     44100,
            "codec":           "PCM_16",
            "snr_db":          Decimal("26.0"),
            "clipping_percent": Decimal("0.2"),
            "speaker_only_verified": True,
        },
        "picnic_scene": {
            "session_id":      session_id_demo,
            "duration":        Decimal("87"),
            "quality_score":   Decimal("0.85"),
            "sample_rate":     44100,
            "codec":           "PCM_16",
            "snr_db":          Decimal("25.0"),
            "clipping_percent": Decimal("0.3"),
            "speaker_only_verified": True,
        },
    }

    # ---- SageMaker fixtures: alignment + phoneme classification ----
    sagemaker_fixtures = {
        # Articulation: rabbit. Maya substitutes /r/ -> /w/.
        ("speech-therapy-alignment-peds-disordered-4-8",
         f"s3://{AUDIO_BUCKET}/{session_id_demo}/rabbit.wav"): {
            "alignment": {
                "phoneme_boundaries": [
                    {"phoneme": "r", "start_ms": 0,
                     "end_ms": 80},
                    {"phoneme": "ae", "start_ms": 80,
                     "end_ms": 220},
                    {"phoneme": "b", "start_ms": 220,
                     "end_ms": 320},
                    {"phoneme": "ih", "start_ms": 320,
                     "end_ms": 460},
                    {"phoneme": "t", "start_ms": 460,
                     "end_ms": 560},
                ],
                "alignment_confidence": Decimal("0.86"),
            },
        },
        ("speech-therapy-phoneme-peds-disordered-4-8",
         f"s3://{AUDIO_BUCKET}/{session_id_demo}/rabbit.wav"): {
            "phoneme_classification": {
                "per_phoneme": [
                    {"expected": "r", "observed": "w",
                     "outcome": "substituted",
                     "confidence": Decimal("0.88")},
                    {"expected": "ae", "observed": "ae",
                     "outcome": "correct",
                     "confidence": Decimal("0.94")},
                    {"expected": "b", "observed": "b",
                     "outcome": "correct",
                     "confidence": Decimal("0.91")},
                    {"expected": "ih", "observed": "ih",
                     "outcome": "correct",
                     "confidence": Decimal("0.93")},
                    {"expected": "t", "observed": "t",
                     "outcome": "correct",
                     "confidence": Decimal("0.90")},
                ],
            },
        },
        # Articulation: sheep. Correct production this time.
        ("speech-therapy-alignment-peds-disordered-4-8",
         f"s3://{AUDIO_BUCKET}/{session_id_demo}/sheep.wav"): {
            "alignment": {
                "phoneme_boundaries": [
                    {"phoneme": "sh", "start_ms": 0,
                     "end_ms": 200},
                    {"phoneme": "iy", "start_ms": 200,
                     "end_ms": 600},
                    {"phoneme": "p", "start_ms": 600,
                     "end_ms": 720},
                ],
                "alignment_confidence": Decimal("0.84"),
            },
        },
        ("speech-therapy-phoneme-peds-disordered-4-8",
         f"s3://{AUDIO_BUCKET}/{session_id_demo}/sheep.wav"): {
            "phoneme_classification": {
                "per_phoneme": [
                    {"expected": "sh", "observed": "sh",
                     "outcome": "correct",
                     "confidence": Decimal("0.83")},
                    {"expected": "iy", "observed": "iy",
                     "outcome": "correct",
                     "confidence": Decimal("0.92")},
                    {"expected": "p", "observed": "p",
                     "outcome": "correct",
                     "confidence": Decimal("0.89")},
                ],
            },
        },
        # Articulation: thumb. Substitutes /th/ -> /f/.
        ("speech-therapy-alignment-peds-disordered-4-8",
         f"s3://{AUDIO_BUCKET}/{session_id_demo}/thumb.wav"): {
            "alignment": {
                "phoneme_boundaries": [
                    {"phoneme": "th", "start_ms": 0,
                     "end_ms": 130},
                    {"phoneme": "ah", "start_ms": 130,
                     "end_ms": 360},
                    {"phoneme": "m", "start_ms": 360,
                     "end_ms": 540},
                ],
                "alignment_confidence": Decimal("0.81"),
            },
        },
        ("speech-therapy-phoneme-peds-disordered-4-8",
         f"s3://{AUDIO_BUCKET}/{session_id_demo}/thumb.wav"): {
            "phoneme_classification": {
                "per_phoneme": [
                    {"expected": "th", "observed": "f",
                     "outcome": "substituted",
                     "confidence": Decimal("0.62")},
                    {"expected": "ah", "observed": "ah",
                     "outcome": "correct",
                     "confidence": Decimal("0.89")},
                    {"expected": "m", "observed": "m",
                     "outcome": "correct",
                     "confidence": Decimal("0.90")},
                ],
            },
        },
    }
    sagemaker_mock = MockSageMakerRuntime(sagemaker_fixtures)

    # ---- Transcribe fixture for the connected-speech task ----
    transcribe_mock = MockTranscribeMedical({
        f"s3://{AUDIO_BUCKET}/{session_id_demo}/picnic_scene.wav":
            "The family is having a picnic. The dog is "
            "running. The boy is eating a sandwich. The "
            "girl is drinking juice. Then it started "
            "raining. Everyone packed up.",
    })

    # ---- Linguistic feature fixtures ----
    LINGUISTIC_FEATURE_FIXTURES = {
        ("The family is having a picnic. The dog is "
         "running. The boy is eating a sandwich. The "
         "girl is drinking juice. Then it started "
         "raining. Everyone packed up.",
         "mean_length_of_utterance_morphemes"):
            Decimal("4.8"),
        ("The family is having a picnic. The dog is "
         "running. The boy is eating a sandwich. The "
         "girl is drinking juice. Then it started "
         "raining. Everyone packed up.",
         "lexical_diversity_ttr"): Decimal("0.61"),
        ("The family is having a picnic. The dog is "
         "running. The boy is eating a sandwich. The "
         "girl is drinking juice. Then it started "
         "raining. Everyone packed up.",
         "syntactic_complexity_index"): Decimal("2.3"),
        ("The family is having a picnic. The dog is "
         "running. The boy is eating a sandwich. The "
         "girl is drinking juice. Then it started "
         "raining. Everyone packed up.",
         "narrative_structure_score"): Decimal("0.72"),
    }

    # ---- Prosodic feature fixtures ----
    PROSODIC_FEATURE_FIXTURES = {
        f"s3://{AUDIO_BUCKET}/{session_id_demo}/picnic_scene.wav": {
            "articulation_rate":   Decimal("3.8"),
            "pause_distribution":  Decimal("0.22"),
            "f0_mean":             Decimal("245"),
            "f0_std":              Decimal("28"),
            "pitch_range":         Decimal("92"),
        },
    }

    # ---- Phonological pattern fixtures ----
    PHONOLOGICAL_PATTERN_FIXTURES = {
        "stopping_of_fricatives": {
            "percent_occurrence": Decimal("0.22"),
        },
        "gliding_of_liquids": {
            "percent_occurrence": Decimal("0.78"),
        },
        "final_consonant_deletion": {
            "percent_occurrence": Decimal("0.31"),
        },
    }

    # ---- Bedrock fixtures ----
    bedrock_mock = MockBedrock(
        report_responses={
            session_id_demo: {
                "content":
                    "Maya is a 6-year-old female with a "
                    "mild-to-moderate phonological "
                    "disorder showing positive response "
                    "to intervention. Articulation "
                    "scoring across 3 demo items shows "
                    "improvement on targeted final "
                    "consonants. Phonological-pattern "
                    "analysis identifies stopping of "
                    "fricatives and final consonant "
                    "deletion as atypical-for-age "
                    "patterns warranting continued "
                    "therapy. Connected-speech "
                    "linguistic features are "
                    "approximately age-appropriate "
                    "for MLU and lexical diversity. "
                    "This is decision support; the SLP "
                    "retains clinical interpretive "
                    "authority.",
                "guardrail_action": "NONE",
            },
        },
        summary_responses={
            session_id_demo: {
                "content":
                    "Maya did a great job in today's "
                    "speech assessment. She is making "
                    "good progress on her sounds, "
                    "especially the ones we've been "
                    "practicing for ending words. We "
                    "will keep working on /s/ and /f/ "
                    "sounds and on saying the last "
                    "sound in each word. Please keep "
                    "practicing the home activities your "
                    "therapist gave you.",
                "guardrail_action": "NONE",
            },
        })

    # ---- Pre-load the longitudinal table with three prior
    # ---- sessions so the trajectory layer has data to work
    # ---- with.
    patient_id_hash_demo = _hash_value("pt-maya-77")
    prior_session_summary_articulation = {
        "auto_summary": {"summary_value": Decimal("0.532")},
        "final_severity": "moderate",
    }
    for offset_days in (84, 56, 28):
        ts = (datetime.now(timezone.utc)
              - timedelta(days=offset_days)).isoformat()
        score_value = Decimal("0.500") + Decimal("0.01") * (
            Decimal(str(84 - offset_days)))
        longitudinal_table.put(_to_decimal({
            "patient_id_hash":   patient_id_hash_demo,
            "session_id":        f"prior-{ts[:10]}",
            "session_timestamp": ts,
            "instrument_scores": {
                "articulation_inventory_gfta_aligned": {
                    "auto_summary": {
                        "summary_value": score_value},
                    "final_severity": "mild_to_moderate",
                },
            },
            "edited_scores_summary": {},
            "goal_progress":      {},
            "trajectory_patterns": [],
            "capture_metadata":   {},
        }))

    # ---- Wire up the per-task capture fixture for this
    # ---- scenario.
    CURRENT_CAPTURE_FIXTURE = capture_fixture

    print("\n=== Speech Therapy Assessment Pipeline Demo ===\n")
    result = run_assessment_pipeline(
        slp_id="slp-rivera",
        patient_id="pt-maya-77",
        selected_instruments=[
            "articulation_inventory_gfta_aligned",
            "phonological_pattern_analysis",
            "connected_speech_picture_description",
        ],
        deployment_context={
            "context_type":           "outpatient_clinic",
            "interface_type":         "slp_administered",
            "documentation_target":   "fhir_ehr",
            "device_class":
                "clinic_dedicated_microphone",
        },
        session_id_hint=session_id_demo,
        slp_edits=[
            {
                "instrument_id":
                    "articulation_inventory_gfta_aligned",
                "item_id":   "item_003_thumb",
                "new_value": {
                    "observed":     "distorted",
                    "score_value": Decimal("0.5"),
                },
                "reasoning":
                    "Acoustic confidence was low; on "
                    "playback the production sounds "
                    "approximately /th/ with mild "
                    "distortion rather than the model's "
                    "/f/ classification.",
            },
        ],
        clinical_interpretation={
            "diagnosis":
                "moderate_phonological_disorder_responding"
                "_to_intervention",
            "goal_modifications": [
                {"goal_id":
                     "goal_002_initial_fricatives",
                 "goal_text":
                     "Maya will produce /s/, /f/ in "
                     "initial position with 80% accuracy",
                 "modification":
                     "advance_to_generalization_phase_in_"
                     "connected_speech"},
            ],
            "new_goals":          [],
            "therapy_frequency":
                "twice_weekly_45_minutes",
            "therapy_modality":
                "in_clinic_with_home_practice",
            "discharge_readiness": "not_yet",
            "observations":
                "Maya is engaged in therapy and showing "
                "consistent progress. Home practice has "
                "been adherent.",
        })
    print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    run_demo()
```

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right audit records, but the distance between it and a real speech-therapy assessment pipeline running in SLPs' workflows is significant. Here is where that distance lives.

**Real audio capture from a clinic device, telepractice platform, or home-practice app.** The demo's `capture_audio_with_task_quality` reads from in-memory fixtures. Production captures audio from a clinic-grade dedicated microphone with known frequency-response characteristics, a telepractice platform's audio path with telepractice-specific acoustic models and recording-quality guidance, or a mobile-app capture path for home-practice deployments. Each capture surface has its own per-context validation work; the per-deployment-context configuration is part of the architectural pattern.

**Real SageMaker endpoint hosting per population.** The demo's `MockSageMakerRuntime` returns canned outputs. Production hosts each per-population alignment, phoneme-classification, fluency-detection, and voice-quality model as its own SageMaker endpoint. The endpoint configuration is per-model (instance class, autoscaling policy, KMS key for inference data, VPC configuration). Production additionally configures SageMaker Model Monitor jobs that compare production inference against the training-time baseline for data-quality and model-quality drift, plus SageMaker Clarify jobs that produce per-population attribution and bias reports on a scheduled cadence.

**Real Bedrock invocation, prompt management, and Guardrails configuration.** The demo's `MockBedrock` uses fixture lookups. Production calls `bedrock_runtime.invoke_model` with `modelId=BEDROCK_REPORT_PROFILE_ARN` and a structured `body` containing the system prompt (versioned, owned by clinical operations), a `tools` field that declares the structured-output schema as a tool definition, and the user message containing the structured scoring data, the longitudinal context, the clinical record, and the institutional template. The `guardrailIdentifier` and `guardrailVersion` parameters apply the runtime Guardrails policy. Family-facing summaries use a more conservative Guardrails policy than SLP-facing reports; the family policy's contextual-grounding check ensures the family communication does not over-claim what the assessment supports and stays at the appropriate reading level.

**Real Transcribe Medical wiring.** The demo's `MockTranscribeMedical` returns fixture transcripts. Production calls `transcribe_client.start_medical_transcription_job` with the appropriate medical specialty and an institutional custom vocabulary, polls for job completion, and reads the transcript from S3. The transcription step is asynchronous and adds latency; for the connected-speech tasks the latency budget for the overall scoring path includes the transcription time.

**Disordered-speech-tolerant alignment, phoneme classification, and fluency detection.** This is the dominant gap. Off-the-shelf speech recognition tuned on typical adult speech does not handle disordered speech well; the production system requires per-population alignment models (typically built on top of self-supervised speech representations like wav2vec 2.0, HuBERT, or WavLM, fine-tuned on disordered-speech corpora) and per-population phoneme classifiers. Building these models is a multi-year clinical-research undertaking; most institutions should be buying validated commercial models with appropriate evidence packages rather than building from scratch.

**Per-instrument and per-population validation evidence.** The demo's `INSTRUMENT_DEFINITIONS` is a tiny in-memory dict with three illustrative instruments. Production maintains per-instrument definitions with the stimulus list, scoring rubric, severity cutoffs, validation envelope, and per-instrument confidence threshold reviewed and approved by clinical operations. Each combination of instrument and population needs its own validation evidence: a model that scores GFTA-aligned articulation accurately for typical-development 6-year-olds is not necessarily accurate for typical-development 4-year-olds, for speech-disordered 6-year-olds, for African American English speakers, or for bilingual Spanish-English speakers. Production validates each combination explicitly.

**Stimulus-set licensing and norm-reference data.** Established assessment instruments are often copyrighted by their publishers; production deployment requires licensing agreements and signed BAAs with the publishers. Population norms for specific instruments and populations are similarly licensed or institutionally validated. The demo's three illustrative items are not a real GFTA inventory; production maintains the full licensed stimulus and norm data with the change-management process for instrument updates.

**Pediatric consent infrastructure.** The demo's `capture_consent` simulates a granted consent. Production deploys a layered pediatric consent program: parent or guardian consent flow, age-appropriate assent for children age 7+, FERPA-aligned consent for school deployments, COPPA-aligned consent for any direct-to-child interface elements, biometric-data-law disclosure for affected jurisdictions, and the long-horizon pediatric records-retention infrastructure that supports retention until age of majority plus a state-specific number of years. The pediatric consent infrastructure is more substantial than typical adult HIPAA-only consent.

**Per-deployment-context configuration.** The demo handles two deployment contexts (FHIR-aligned EHR and school SIS) via a single configuration field. Production maintains per-context configurations that span consent flow, documentation target, IEP integration for school deployments, telepractice-specific acoustic models for telepractice deployments, home-practice-specific scoring rubrics for home-practice apps, and per-context population profiles. Each context requires its own implementation work.

**Per-Lambda IAM roles.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda (session-setup, capture-ingest, feature-extraction, scoring, longitudinal, SLP-review, documentation, EHR or SIS write-back, audit), each scoped to the specific resource ARNs the Lambda touches. The scoring Lambda has scoped SageMaker invoke-endpoint rights pinned to the validated per-population endpoints only; the documentation Lambda has scoped Bedrock invocation rights pinned to the report-rendering model and inference profile; the EHR or SIS write-back Lambda has scoped Secrets Manager read for the appropriate credentials and the system-specific egress only. Wildcard actions and resources will fail any serious IAM review.

**Real DynamoDB wiring with KMS and PITR.** The mocks in the demo are dictionaries; production is DynamoDB tables (sessions partitioned by session-id with TTL on idle sessions, longitudinal partitioned by patient-id-hash with sort key on session-timestamp, instrument-definitions partitioned by instrument-id with sort key on version, norm-references partitioned by reference-id, goal-tracking partitioned by patient-id-hash with sort key on goal-id, SLP-edit-history partitioned by session-id with sort key on edit-timestamp) with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery enabled, and DynamoDB Streams emitting change events to the audit and analytics consumers.

**Customer-managed KMS keys, per data class.** Every PHI-bearing and biometric-bearing resource (audio bucket, feature-vector bucket, report archive, audit archive, all DynamoDB tables, Lambda environment variables, CloudWatch Logs, Secrets Manager) uses customer-managed KMS keys with rotation enabled. Different keys per data class for blast-radius containment: a compromised audio-bucket key does not compromise the report archive. Voice samples and feature vectors use separate keys because feature-vector retention is typically longer than audio retention. Per-state biometric-data law sometimes requires distinct cryptographic isolation; the architecture supports per-jurisdiction key management where required.

**S3 lifecycle and Object Lock.** The audio bucket has a brief-retention lifecycle bound to consent terms (often hours to a few days for active therapy support, longer with explicit consent for longitudinal-monitoring scenarios). The feature-vector bucket retains for the longitudinal-analysis and model-improvement window. The report-archive bucket retains aligned with medical-record retention or educational-record retention as applicable. The audit archive uses Object Lock in compliance mode with retention sized to the longer of HIPAA's six-year minimum, biometric-data-law retention requirements, FERPA educational-record retention where applicable, state medical-records-retention rules including pediatric-extending-to-age-of-majority-plus-X, and the institutional regulatory floor. Lifecycle transitions move older audit-archive objects to S3 Glacier Deep Archive for cost optimization.

**VPC and VPC endpoints.** Lambdas that call back-office APIs (EHR FHIR write-back, school SIS, patient portal, parent-coaching app) run in a VPC with private subnets that route traffic through a controlled egress path. VPC endpoints for S3, DynamoDB, KMS, Secrets Manager, EventBridge, CloudWatch Logs, SageMaker Runtime, Transcribe Medical, Bedrock, HealthLake keep AWS-internal traffic on the AWS backbone. Endpoint policies pin access to the specific resources the pipeline uses. SageMaker endpoints in VPC mode where the chosen model container supports it.

**Step Functions orchestration of the multi-stage scoring and documentation pipeline.** The demo orchestrates the post-capture stages inline. Production runs them as an AWS Step Functions state machine triggered by the `session_captured` event: feature extraction (with Map-state fan-out across captured tasks), per-instrument scoring, longitudinal comparison, SLP-review handoff (with a wait-for-human-input pattern using Step Functions `waitForTaskToken`), documentation generation, and EHR or SIS write-back. Step Functions provides durable retry semantics: if SageMaker throttles, retry with exponential backoff; if Bedrock fails, route to a DLQ with a fall-back to a templated report; if HealthLake or SIS handoff fails, hold the result in a queue with manual replay capability.

**Biometric-data deletion-on-request workflow with pediatric protection.** The demo's `schedule_audio_deletion` deletes the audio object. Production maintains a biometric-data deletion-on-request workflow that handles audio, feature vectors, longitudinal-history entries, and the long-term audit record per the patient's (or parent's, on behalf of a minor) request. The workflow respects FERPA's amendment-and-deletion provisions for school-based educational records, the long pediatric-records-retention floor, and per-state biometric-data law disclosure-accounting requirements. Feature vectors derived from voice may persist after the source audio is deleted; whether the feature vectors are themselves biometric is a privacy-officer judgment call.

**SLP-feedback closed-loop surveillance.** The demo records SLP edits in the audit archive but does not feed them back into model improvement. Production runs the closed loop: the SLP's per-item edits are the gold-standard signal for per-population, per-instrument surveillance; persistent disagreement on a per-population basis triggers a re-validation review; the institutional clinical-quality team reviews edit patterns on a cadence; and findings feed into model-card updates and clinical-action-mapping updates. The surveillance dashboard segments edit rates by population profile, instrument, deployment context, and device class.

**Per-population accuracy and adoption monitoring with launch gates.** Per-population metrics (per-age-band, per-language, per-dialect, per-device-class, per-deployment-context) are a launch gate, not a post-launch dashboard. Production defines population axes, per-population minimum sample sizes, per-population threshold metrics (per-item agreement with SLP gold-standard, indeterminate-result rate, SLP-edit rate), and gates launch on every population meeting the threshold rather than on the institution-wide average. Disparity alerts trigger reviews; sustained disparity triggers product-level remediation, including (potentially) disabling the system for populations where it underperforms.

**FDA SaMD strategy where applicable.** The demo emits surveillance metrics but does not implement the regulatory-reporting workflow. Speech-therapy AI tools that produce autonomous diagnostic claims are potentially subject to FDA's SaMD framework. The strategy decision (pursue clearance, deploy as SLP-augmentation, deploy as practice-and-monitoring tool) is upstream of the technical work. Most current speech-therapy AI products position themselves outside the regulatory perimeter as SLP-augmentation tools; that positioning constrains the clinical claims but reduces the regulatory exposure.

**SLP-review interface design and clinical-workflow integration.** The demo's `slp_submits_review` accepts a list of edits without a real review interface. Production deploys a substantial SLP-facing review interface: per-item scoring with confidence, audio playback for any item, side-by-side prior-session comparison, bulk-acceptance for high-confidence items, free-text observation capture, goal-modification workflow, and integration with the SLP's existing documentation tool. The interface design is the system's single biggest determinant of clinician adoption; SLP-led iterative usability testing is essential.

**Faithfulness and grounding for LLM-generated reports.** The demo accepts the Bedrock-generated SLP report and family summary at face value. Production verifies the LLM output: schema validation against the structured-output schema, citation grounding to the underlying scoring data, secondary checks that verify the report does not invent items or scores beyond what the system measured, reading-level validation for family-facing summaries, and Guardrails coverage for content categories. The verification pipeline runs as a post-generation check, and reports that fail verification fall back to a templated report rather than shipping with hallucinated content.

**Idempotency and retry semantics.** The demo's session-id is generated freshly each run. Production uses a conditional DynamoDB write keyed on `(slp_id, patient_id_hash, session_initiation_timestamp)` so a duplicate session-initiation event is rejected with `ConditionalCheckFailedException` rather than producing two sessions. The HealthLake create-resource call uses an idempotency key built from `(session_id, instrument_id)` so a retry does not produce two Observation resources. Configure DLQs on every Lambda; alarm on DLQ depth.

**Performance under burst load.** Speech-therapy assessment volume has strong patterns: morning clinic sessions, weekly school-based caseload review days, scheduled longitudinal-monitoring batches. The demo runs a single session at a time. Production holds the latency budget under burst: SageMaker endpoint quotas, Bedrock model invocation quotas, Transcribe Medical job concurrency quotas, and downstream EHR or SIS API rate limits all need provisioning headroom and burst-capacity planning. Reserve concurrency where the latency-sensitive Lambdas would otherwise be starved. Load test against realistic peak profiles before launch.

**Disaster recovery and degraded-mode operation.** The demo assumes happy-path execution. Production tests the failure modes in staging quarterly: SageMaker endpoint unavailable (fall back to manual SLP-only scoring with explicit "AI scoring service unavailable" framing), Bedrock unavailable (fall back to a templated SLP report; the audit captures the fallback), Transcribe Medical unavailable (skip linguistic-feature path; surface "linguistic features not available" indicator), HealthLake unavailable (hold the FHIR write in a queue with manual replay), SIS API unreachable (hold the assessment hand-off in a queue with retry). The system is decision support; its absence does not block clinical care.

**Audit log retention with regulatory-aware lifecycle.** The demo's audit-archive S3 bucket is created without Object Lock in the mock. Production enables Object Lock in compliance mode with retention sized per the FERPA, HIPAA, biometric-data law, state medical-records-retention rules, and pediatric-extending-to-age-of-majority-plus-X requirements. Legal hold capabilities (suspending deletion for specific patients during litigation) are configurable.

**Cost monitoring per instrument, per population, and per deployment context.** Different instruments and populations have very different per-session costs (a connected-speech task with transcription plus linguistic-feature extraction is structurally more expensive than a single-word articulation task). Per-instrument, per-population, per-deployment-context cost dashboards let operations identify outliers and tune accordingly.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the instrument-applicability check, unit tests for the per-item scoring and summary computation, unit tests for the norm-reference application across age bands, integration tests against test buckets and tables, and end-to-end tests that simulate full session flows including the not-applicable-instrument path, the quality-failure path, the all-confident-no-review-flag path, the heavy-SLP-edit path, the school-based deployment path, and the multi-language paths. Never use real patient voice samples in test fixtures; voice samples are biometric and PHI-bearing data with non-trivial governance implications. Use synthetic patients (Synthea-style) and TTS-generated audio with controlled disordered-speech characteristics, or use the public disordered-speech corpora (TORGO, UASpeech, AphasiaBank, FluencyBank) under their license terms.

**Observability beyond the metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-stage investigation. Production runs CloudWatch Logs Insights queries that join across the session-setup logs, the capture-ingest logs, the feature-extraction logs, the scoring logs, the longitudinal logs, the SLP-review logs, the documentation logs, and the EHR or SIS write-back logs by session_id. AWS X-Ray traces show the latency contribution of each stage. When a single session goes wrong (an unexpectedly high SLP-edit rate, a per-population drift alarm firing, a documentation hand-off stalling), the on-call engineer needs to reconstruct the full trace in seconds.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 10.9: Speech Therapy Assessment and Monitoring](chapter10.09-speech-therapy-assessment-monitoring) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard. See [Recipe 10.8: Voice Biomarker Detection](chapter10.08-voice-biomarker-detection) for the per-cohort calibration, eligibility-gating, and post-deployment surveillance patterns that transfer directly. See [Recipe 10.6: Speech-to-Text for Telehealth Documentation](chapter10.06-speech-to-text-telehealth-documentation) for the per-cohort accuracy discipline that informs per-population validation here.*
