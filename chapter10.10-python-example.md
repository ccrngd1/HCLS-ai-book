# Recipe 10.10: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 10.10 (multilingual real-time medical interpretation). It shows one way you could translate the pipeline into working Python using boto3 against Amazon Transcribe and Transcribe Medical (streaming source-language ASR with medical-vocabulary customization), Amazon Translate (with Custom Terminology for institution-specific terms), Amazon Bedrock (with Guardrails for LLM-based translation on hard content categories and faithfulness verification), Amazon Polly (streaming neural and generative TTS with pronunciation lexicons), Amazon Connect (telephonic deployment), Amazon Chime SDK (in-person and telehealth deployment), AWS Lambda, AWS Step Functions, Amazon API Gateway, Amazon Cognito, Amazon DynamoDB, Amazon S3, AWS KMS, AWS Secrets Manager, Amazon EventBridge, Amazon CloudWatch, AWS CloudTrail, and Amazon Kinesis Data Firehose. The demo uses `MockTranscribeStreaming` standing in for the per-language streaming ASR sessions, a `MockTranslate` standing in for the medical-domain MT path with Custom Terminology, a `MockBedrock` standing in for the LLM-translation and faithfulness-verification path, a `MockPolly` standing in for the per-language TTS path, a `MockConnect` and `MockChimeSDK` standing in for the audio infrastructure, a `MockHumanInterpreterPool` standing in for the human-interpreter handoff service, and small helpers for the encounter table, the per-utterance audit table, the audio S3 bucket, the audit S3 bucket, the EventBridge bus, and CloudWatch-style metrics. It is not production-ready. There is no real audio capture from a clinic device, telephony provider, or telehealth platform, no real Cognito authorizer, no real Transcribe streaming WebSocket session, no real Translate or Bedrock invocation, no real Polly streaming synthesis, no real Connect or Chime SDK wiring, no real DynamoDB or S3 wiring, no Step Functions state machine, no IAM least-privilege role per Lambda, no KMS customer-managed key configuration, no VPC endpoints, no per-language-pair quality monitoring or disparity alerting, no biometric-data deletion-on-request workflow, no real human-interpreter pool integration, and no language-access compliance dashboard. Think of it as the sketchpad version: useful for understanding the shape of a real-time medical interpretation pipeline that respects the per-pair validation discipline, the deployment-posture-per-topic-category framing, the number-and-unit verification as a hard gate, the faithfulness-checked LLM translation, the seamless human-interpreter handoff, the per-language consent disclosure, the audio-as-biometric data governance, and the language-access program integration this recipe demands. It is not something you would deploy to limited-English-proficient patients on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the seven core pseudocode steps from the main recipe: set up the encounter session with language pair, deployment posture, and consent capture (Step 1), route per-speaker audio streams to the appropriate ASR engine with channel separation (Step 2), translate finalized source-language transcripts with medical-domain configuration, faithfulness checks, and number-and-unit verification (Step 3), synthesize target-language audio with neural TTS and pronunciation lexicons (Step 4), manage turn-taking and barge-in with a conversational state machine (Step 5), escalate to a human interpreter on confidence-below-threshold and other triggers (Step 6), and close the encounter with audit, audio retention per consent, and per-pair quality monitoring (Step 7). The synthetic patients, clinicians, languages, dialects, transcripts, and translations in the demo are fictional; the names, MRNs, model versions, language codes, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also configure the audio capture path (a clinic-grade microphone with known frequency response for in-person encounters, an Amazon Connect SIP integration for telephonic encounters, or an Amazon Chime SDK WebRTC session for telehealth encounters with per-participant audio channels), per-language Transcribe streaming sessions with medical-vocabulary custom terminology applied per institution, an Amazon Translate Custom Terminology configuration per language pair plus Active Custom Translation parallel medical corpora where the institution has curated them, an Amazon Bedrock inference profile pinned to a specific translation-rendering model and region for the LLM-based translation path on hard content categories, an Amazon Bedrock Guardrails configuration that filters content categories on patient-facing translations and applies prompt-injection mitigation on patient-generated source content, Amazon Polly neural and generative voices configured per target language with pronunciation lexicons for institution-specific terms (drug names, provider names, location names), the Lambda functions that orchestrate each pipeline stage (the session-setup Lambda, the audio-router Lambda, the faithfulness-and-verification Lambda, the turn-taking-state-machine Lambda, the escalation-logic Lambda, the audit-and-archival Lambda), an AWS Step Functions state machine that durably orchestrates the encounter lifecycle and the human-interpreter handoff process, DynamoDB tables that hold per-encounter session state, per-utterance audit records, escalation history, vendor selection per pair, and per-pair quality evaluation history, AWS Secrets Manager secrets for any third-party ASR, MT, or TTS vendor API credentials integrated for languages where AWS native services are inadequate, an Amazon EventBridge bus for cross-system events (`encounter_setup_complete`, `audio_streaming`, `utterance_translated`, `human_escalation`, `encounter_ended`, `audio_discarded`), Amazon S3 buckets for audio with consent-bounded retention, transcripts and translations with appropriate retention, and the audit archive (with Object Lock in compliance mode and lifecycle to Glacier Deep Archive), customer-managed KMS keys for every PHI-bearing and biometric-bearing data class, and Amazon CloudWatch dashboards plus per-pair quality monitoring jobs that compare the system's translations against a curated medical-content evaluation set on a scheduled cadence. The demo replaces all of these with small mocks so the focus stays on the per-stage processing logic rather than on the cloud-resource provisioning.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `transcribe:StartStreamTranscription` and `transcribe:StartMedicalStreamTranscription` for the streaming ASR sessions, scoped to the specific language codes and medical-specialty configurations the institution uses
- `translate:TranslateText` and access to Custom Terminology resources for the medical-domain MT path
- `bedrock:InvokeModel` for the LLM-translation and faithfulness-verification models, scoped to the specific foundation-model ARNs and inference profiles in use
- `bedrock:ApplyGuardrail` for the runtime guardrails check on patient-facing translations
- `polly:SynthesizeSpeech` and access to Polly Lexicons resources for the per-language TTS path
- `connect:StartContactStreaming` and related Connect actions for the telephonic deployment
- `chime:CreateMeeting` and related Chime SDK actions for the in-person and telehealth deployments
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the encounter, audit, and language-pair-configuration tables
- `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on the audio bucket (with lifecycle-driven deletion the primary path) and the audit-archive bucket, scoped to the per-encounter key prefixes
- `secretsmanager:GetSecretValue` on any third-party vendor credentials pinned to the current rotation version
- `events:PutEvents` on the medical-interpretation EventBridge bus
- `cloudwatch:PutMetricData` for the operational metrics (per-pair end-to-end latency, per-pair confidence distributions, per-pair escalation rates, per-population disparity metrics, audio-quality scores)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the audio bucket, the audit archive, the DynamoDB tables, and the Secrets Manager secrets
- `states:StartExecution` for the Step Functions state machine that orchestrates the encounter lifecycle and the human-interpreter handoff

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The session-setup Lambda has scoped DynamoDB write for the encounter table only and EventBridge publish. The audio-router Lambda has Transcribe streaming permissions, S3 write to the audio bucket scoped to the per-encounter prefix, and DynamoDB update on the encounter table. The faithfulness-and-verification Lambda has Translate, Bedrock invoke-model, and Bedrock apply-guardrail permissions, plus DynamoDB write to the audit table. The TTS-and-delivery Lambda has Polly synthesize-speech permissions and the appropriate Connect or Chime SDK delivery permissions. The escalation Lambda has Connect and Chime SDK permissions for human-interpreter handoff plus Secrets Manager read for vendor credentials. The audit Lambda has DynamoDB write and EventBridge publish. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Voice samples are PHI and biometric.** A patient's voice can identify the patient independent of any other context. The privacy regime is the more restrictive of HIPAA, biometric-data law where applicable (Illinois BIPA, Texas, Washington and similar), and GDPR Article 9 for EU patients. The consent disclosure in the patient's preferred language must explicitly address the biometric-data implications, the audio retention terms, the right to request human interpretation at any time, and the deployment-posture framing for this encounter. Audio retention is a privacy-officer-reviewed decision, not a default. The architecture treats audio as PHI and biometric throughout: encrypted at rest with KMS customer-managed keys, encrypted in transit with TLS, retention bound by an explicit consent disclosure validated per language with native speakers, BAAs in place for any vendor service that processes the audio, and a biometric-data-deletion-on-request workflow that handles audio, transcripts, and audit records per the patient's jurisdiction.
- **Per-pair validation is a launch gate, not a post-launch concern.** Each language pair, in each direction, on representative medical content, against a curated evaluation set, with measured accuracy on number-and-unit content, drug names, anatomical terms, and cultural-framing-sensitive content. Pairs that have not been validated for the institution's medical content do not deploy in machine-mediated mode at all; they fall back to human-only interpretation routing.
- **Deployment posture is per topic category, not per institution.** A single institution may run machine-only interpretation for refill-request phone calls, machine-with-human-on-standby for routine outpatient visits, and human-primary-with-machine-assistance for informed consent and mental health. The architecture supports all three with the same components, configured differently per topic category. The deployment-posture decision is owned by clinical-quality leadership in collaboration with the language-access program; it is not a technical choice.
- **Number-and-unit verification is a hard gate, not a soft warning.** Drug doses, dosing intervals, ages, weights, vital signs, and other numerical content drive clinical decisions. The system must verify that numerical content in the translated output matches the numerical content in the source, with a hard block on mismatches that routes to human-interpreter escalation rather than producing a translation that is wrong about a dosage.
- **Faithfulness checks on LLM-based translation are not optional.** When the architecture uses Bedrock LLM-based translation for low-resource pairs or high-fluency clinical content, the LLM-translation path inherits hallucination concerns: invented content, omitted content, contradictions with the source. Per-segment faithfulness checks (citation grounding to the source, structured-output validation, secondary verification by an independent model) are part of the production pipeline. The faithfulness scaffolding from recipe 2.6 (clinical note summarization) and recipe 2.10 (multi-modal clinical reasoning) applies here.
- **Human-interpreter escalation is a feature, not a fallback.** Institutions that frame human escalation as a fallback (the machine is the primary, the human catches errors) tend to use the human pool less and erode the human-interpreter pipeline. The architecture frames human escalation as a first-class pathway alongside the machine pathway, with the system choosing based on the topic category and the moment-to-moment confidence. The framing affects the staffing model, the interpreter compensation, and the long-term professional pipeline.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, latency value, and numeric metadata field passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses multiple Lambdas, the Step Functions orchestration, the EventBridge fan-out, and the CloudWatch metric emission into a single Python file for readability.** In production each pipeline stage is a separate Lambda with its own IAM role, error handling, retries, and DLQs, with Step Functions as the durable orchestrator for the encounter lifecycle and the human-interpreter handoff process. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the per-language-pair definitions, the per-topic-category deployment posture, the per-pair confidence thresholds, the consent disclosures, and the number-and-unit verification rules are what you would change between environments.

```python
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights. The medical-interpretation pipeline
# operates on heavily PHI-bearing and biometric-bearing data:
# the audio is PHI and biometric, the source-language transcripts
# capture spontaneous patient speech that often contains PHI
# beyond the clinical content, the target-language translations
# are the institution's clinical communication to (or from) the
# patient with full liability for any error, and every utterance
# is auditable. Log structural metadata only (encounter_id,
# language_pair, deployment_posture, segment counts, escalation
# events), never raw audio references that could leak biometric
# content, never source or target transcript content that could
# leak PHI, never patient demographics that could enable
# re-identification.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from Transcribe, Translate,
# Bedrock, Polly, DynamoDB, S3, EventBridge, CloudWatch, and
# Secrets Manager. Real-time medical interpretation has tight
# per-utterance latency budgets: 1.5 to 3 seconds end-to-end
# for the conversational flow to stay natural. The retry config
# below favors fewer attempts on the latency-critical path so
# a stalled vendor does not blow the budget; the audit and
# archival path uses more generous retry tuning.
BOTO3_RETRY_CONFIG_REALTIME = Config(
    retries={"max_attempts": 2, "mode": "adaptive"})
BOTO3_RETRY_CONFIG_ASYNC = Config(
    retries={"max_attempts": 6, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in
# warm containers so each invocation does not pay the
# connection cost. The demo below uses Mock* classes instead;
# the real clients are never invoked here.
REGION = "us-east-1"
dynamodb            = boto3.resource("dynamodb", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
s3_client           = boto3.client("s3", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
transcribe_streaming = boto3.client(
    "transcribe-streaming", region_name=REGION,
    config=BOTO3_RETRY_CONFIG_REALTIME)
translate_client    = boto3.client("translate", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_REALTIME)
bedrock_runtime     = boto3.client("bedrock-runtime",
                                       region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_REALTIME)
polly_client        = boto3.client("polly", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_REALTIME)
connect_client      = boto3.client("connect", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
chime_sdk_client    = boto3.client("chime-sdk-meetings",
                                       region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
eventbridge_client  = boto3.client("events", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
cloudwatch_client   = boto3.client("cloudwatch", region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)
secrets_client      = boto3.client("secretsmanager",
                                       region_name=REGION,
                                       config=BOTO3_RETRY_CONFIG_ASYNC)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo
# prints what it would write rather than failing if the
# resources do not exist.
ENCOUNTER_TABLE              = "medical-interpretation-encounters"
AUDIT_TABLE                  = "medical-interpretation-audit"
LANGUAGE_PAIR_CONFIG_TABLE   = "medical-interpretation-pair-configs"
AUDIO_BUCKET                 = "medical-interpretation-audio"
AUDIT_ARCHIVE_BUCKET         = "medical-interpretation-audit-archive"
EVENT_BUS_NAME               = "medical-interpretation-events-bus"
CLOUDWATCH_NAMESPACE         = "MedicalInterpretation"
INSTITUTION_ID               = "academic-medical-center-richmond"

# Bedrock configuration. In production, pin to a specific
# model version and inference profile so a model upgrade does
# not silently change translation behavior. The model and
# region combination must be in your AWS BAA scope.
BEDROCK_TRANSLATION_MODEL_ID = (
    "anthropic.claude-3-5-sonnet-20240620-v1:0")
BEDROCK_TRANSLATION_PROFILE_ARN = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "medical-interpretation-translation-v1")
BEDROCK_FAITHFULNESS_MODEL_ID = (
    "anthropic.claude-3-haiku-20240307-v1:0")
TRANSLATION_GUARDRAIL_ID = "guardrail-medical-translation-v1"
TRANSLATION_GUARDRAIL_VERSION = "2"

# Deploy-time guardrail. Any blank resource name is a deploy-
# time bug, not a runtime surprise.
for _name, _value in [
    ("ENCOUNTER_TABLE",             ENCOUNTER_TABLE),
    ("AUDIT_TABLE",                 AUDIT_TABLE),
    ("LANGUAGE_PAIR_CONFIG_TABLE",  LANGUAGE_PAIR_CONFIG_TABLE),
    ("AUDIO_BUCKET",                AUDIO_BUCKET),
    ("AUDIT_ARCHIVE_BUCKET",        AUDIT_ARCHIVE_BUCKET),
    ("EVENT_BUS_NAME",              EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",        CLOUDWATCH_NAMESPACE),
    ("BEDROCK_TRANSLATION_MODEL_ID",
        BEDROCK_TRANSLATION_MODEL_ID),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every encounter carries the versions of the artifacts that
# influenced its translations: per-pair ASR and MT engine
# versions, the medical-vocabulary and custom-terminology
# version, the LLM-translation prompt version, the
# faithfulness-verifier prompt version, and the Polly voice
# version. A future audit reconstructs which configuration
# was active when a particular utterance was translated.
ASR_PIPELINE_VERSION             = "asr-pipeline-2026-q1"
MT_PIPELINE_VERSION              = "mt-pipeline-2026-q1"
TTS_PIPELINE_VERSION             = "tts-pipeline-2026-q1"
TRANSLATION_PROMPT_VERSION       = "translation-prompt-v2.1"
FAITHFULNESS_PROMPT_VERSION      = "faithfulness-prompt-v1.4"

# --- Confidence and Quality Thresholds ---
# Per-segment translation confidence below this threshold
# triggers escalation review or render-with-warning depending
# on the deployment posture. Per-word ASR confidence below
# this threshold contributes to escalation decisions on the
# upstream side.
DEFAULT_TRANSLATION_CONFIDENCE_THRESHOLD = Decimal("0.78")
DEFAULT_ASR_CONFIDENCE_THRESHOLD         = Decimal("0.72")
DEFAULT_FAITHFULNESS_THRESHOLD           = Decimal("0.85")

# --- Latency Budgets ---
# End-to-end latency budget per utterance: from end-of-source-
# audio to start-of-target-audio playback. Budget overruns are
# tracked and alarmed; sustained overruns trigger automatic
# escalation to human interpretation.
LATENCY_BUDGET_P50_MS = 1800
LATENCY_BUDGET_P95_MS = 2800

# --- Audio Quality Thresholds ---
DEFAULT_MIN_SAMPLE_RATE_HZ      = 16000
DEFAULT_MIN_SNR_DB              = Decimal("10.0")

# --- Endpointing Thresholds ---
# Silence threshold for end-of-utterance detection. Aggressive
# (short) values reduce latency but produce more mid-sentence
# cutoffs; conservative (long) values produce cleaner segments
# at the cost of latency. Per-topic-category configuration:
# routine clinical uses moderate values, sensitive content
# (mental health, end-of-life) uses longer thresholds to give
# the speaker space.
ENDPOINTING_THRESHOLDS_MS = {
    "administrative":           500,
    "routine_clinical":         700,
    "safety_critical":          1100,
    "mental_health":            1400,
    "end_of_life":              1500,
}

# --- Consent Disclosures ---
# Voice samples are biometric. The disclosure language differs
# by jurisdiction (Illinois BIPA, Texas, Washington each have
# specific requirements), by EU patients (GDPR Article 9 adds
# explicit-consent and right-to-erasure framing), and by
# language. The disclosure must be presented in the patient's
# preferred language, validated per language by native
# speakers, and at an appropriate literacy level. Production
# looks up the patient's jurisdiction and language; the demo
# uses illustrative defaults.
# TODO (TechWriter): consent disclosure text below is
# illustrative-only. Production deployment requires native-
# speaker-validated translations per language with attention
# to literacy level and cultural framing.
CONSENT_DISCLOSURE_DEFAULT_EN = (
    "We are using a computer-based interpretation service "
    "for this conversation. Your voice is being processed "
    "by automated software to translate between English "
    "and your preferred language. You can ask for a human "
    "interpreter at any time, and your care will not be "
    "delayed if you do. Audio recordings will be deleted "
    "after the encounter unless you give specific "
    "permission for longer retention. By continuing, you "
    "consent to this interpretation method.")
CONSENT_DISCLOSURE_DEFAULT_ES = (
    "Estamos usando un servicio de interpretacion por "
    "computadora para esta conversacion. Su voz esta "
    "siendo procesada por software automatizado para "
    "traducir entre ingles y su idioma preferido. Puede "
    "solicitar un interprete humano en cualquier momento, "
    "y su atencion no se demorara si lo hace. Las "
    "grabaciones de audio se eliminaran despues del "
    "encuentro a menos que usted otorgue permiso "
    "especifico para una retencion mas prolongada. Al "
    "continuar, usted consiente a este metodo de "
    "interpretacion.")
CONSENT_DISCLOSURE_BIPA_OVERLAY_EN = (
    "Under Illinois law, we are specifically informing you "
    "that voice recordings are biometric data. We are "
    "collecting them for the medical-interpretation purpose "
    "described above. We will retain audio only for the "
    "period stated in your consent. You can request "
    "deletion at any time. By continuing, you give written "
    "consent to this collection.")

# Jurisdictions with biometric-data laws requiring specific
# disclosure language. The list is approximate and changes
# over time as state law evolves; production maintains this
# in a legal-team-reviewed configuration with an explicit
# update cadence.
# TODO (TechWriter): verify the current biometric-data-law
# state list against the IAPP biometric-privacy tracker
# before deploying.
BIOMETRIC_DATA_LAW_STATES = {"IL", "TX", "WA"}


# --- Topic Category to Deployment Posture Mapping ---
# The institutional language-access policy owns this mapping.
# Production maintains it as a clinical-operations-reviewed
# configuration with explicit version history; the demo
# uses an illustrative set.
TOPIC_TO_POSTURE = {
    "administrative":           "machine_only",
    "self_service":             "machine_only",
    "routine_clinical":         "machine_with_human_standby",
    "patient_education":        "machine_with_human_standby",
    "safety_critical":          "human_primary_with_machine_assistance",
    "informed_consent":         "human_only",
    "mental_health_crisis":     "human_only",
    "end_of_life":              "human_only",
    "complex_new_diagnosis":    "human_only",
}


# --- Per-Pair Configuration Definitions ---
# Each language pair stores the validated vendor selection,
# the medical-vocabulary and custom-terminology IDs, the per-
# pair confidence threshold (often tuned tighter for low-
# resource pairs), and the deployment status. Production
# reads these from DynamoDB; the demo uses an in-memory dict.
LANGUAGE_PAIR_CONFIGS = {
    "es-MX_to_en-US": {
        "pair_id":               "es-MX_to_en-US",
        "source_language":       "es-MX",
        "target_language":       "en-US",
        "deployment_status":     "validated",
        "asr_engine":            "transcribe",
        "asr_custom_vocabulary": "medical-spanish-mexico-v3",
        "mt_engine":             "translate",
        "mt_custom_terminology": "medical-es-en-v8",
        "tts_voice":             "Joanna",
        "tts_engine":             "neural",
        "tts_lexicons":          ["medical-en-pronunciation-v2"],
        "confidence_threshold":  Decimal("0.78"),
        "latency_budget_p95_ms": 2400,
    },
    "en-US_to_es-MX": {
        "pair_id":               "en-US_to_es-MX",
        "source_language":       "en-US",
        "target_language":       "es-MX",
        "deployment_status":     "validated",
        "asr_engine":            "transcribe_medical",
        "asr_specialty":         "PRIMARYCARE",
        "asr_custom_vocabulary": "medical-clinical-en-v6",
        "mt_engine":             "translate",
        "mt_custom_terminology": "medical-en-es-v8",
        "tts_voice":             "Lupe",
        "tts_engine":            "neural",
        "tts_lexicons":          ["medical-es-pronunciation-v2"],
        "confidence_threshold":  Decimal("0.78"),
        "latency_budget_p95_ms": 2400,
    },
    "vi-VN_to_en-US": {
        "pair_id":               "vi-VN_to_en-US",
        "source_language":       "vi-VN",
        "target_language":       "en-US",
        "deployment_status":     "validated",
        "asr_engine":            "transcribe",
        "asr_custom_vocabulary": "medical-vietnamese-v2",
        # Vietnamese gets the LLM path for high-fluency
        # rendering of clinical idioms; Translate is used
        # for routine content and routine-clinical content.
        "mt_engine":             "hybrid_translate_bedrock",
        "mt_custom_terminology": "medical-vi-en-v3",
        "tts_voice":             "Joanna",
        "tts_engine":             "neural",
        "tts_lexicons":          ["medical-en-pronunciation-v2"],
        "confidence_threshold":  Decimal("0.74"),
        "latency_budget_p95_ms": 3200,
    },
    "en-US_to_vi-VN": {
        "pair_id":               "en-US_to_vi-VN",
        "source_language":       "en-US",
        "target_language":       "vi-VN",
        "deployment_status":     "validated",
        "asr_engine":            "transcribe_medical",
        "asr_specialty":         "PRIMARYCARE",
        "asr_custom_vocabulary": "medical-clinical-en-v6",
        "mt_engine":             "hybrid_translate_bedrock",
        "mt_custom_terminology": "medical-en-vi-v3",
        # Vietnamese TTS coverage in Polly is limited at the
        # time of this writing; production may route to a
        # third-party vendor for the patient-direction TTS.
        # TODO (TechWriter): verify current Polly Vietnamese
        # voice availability and quality.
        "tts_voice":             "Lien",
        "tts_engine":             "neural",
        "tts_lexicons":          ["medical-vi-pronunciation-v1"],
        "confidence_threshold":  Decimal("0.74"),
        "latency_budget_p95_ms": 3200,
    },
    # Karen, a low-resource language served by some refugee
    # populations, illustrates the not-validated case. The
    # institution does not have validation evidence at the
    # quality threshold for any vendor on this pair, so it
    # is marked not_validated and routes to human-only.
    "ksw-MM_to_en-US": {
        "pair_id":               "ksw-MM_to_en-US",
        "source_language":       "ksw-MM",
        "target_language":       "en-US",
        "deployment_status":     "not_validated",
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


def _select_consent_disclosure(language, jurisdiction):
    """Pick the appropriate disclosure language and any
    jurisdiction-specific overlay (BIPA for Illinois, etc.)."""
    base = (CONSENT_DISCLOSURE_DEFAULT_ES
            if language.startswith("es")
            else CONSENT_DISCLOSURE_DEFAULT_EN)
    overlay = (CONSENT_DISCLOSURE_BIPA_OVERLAY_EN
                if jurisdiction in BIOMETRIC_DATA_LAW_STATES
                else None)
    if overlay:
        return f"{base}\n\n{overlay}"
    return base


def audit_log(event):
    """
    Sanitized audit print so you can see the sequence of
    decisions without leaking the underlying values. Production
    routes events to CloudWatch Logs Insights with structured
    JSON; ship to a SIEM if available. Voice samples are
    biometric; never include the audio reference itself in
    routine audit logs, never include source or target
    transcript content that could capture spontaneous PHI,
    never include patient demographics that could enable
    re-identification.
    """
    safe_event = {k: v for k, v in event.items()
                  if k not in {"audio_ref", "source_text",
                                "target_text",
                                "patient_demographics"}}
    if "audio_ref" in event:
        safe_event["audio_ref_hash"] = _hash_value(
            event["audio_ref"])
    logger.info("AUDIT %s",
                  json.dumps(safe_event, default=str))
```

---

## Mock Resources for the Demo

These mocks stand in for the production AWS resources and back-office systems. They are deliberately simple and are not how you would build the real thing. Their purpose is to keep the focus on the medical-interpretation logic.

```python
class MockTranscribeStreaming:
    """
    Stands in for Amazon Transcribe streaming and Transcribe
    Medical streaming. In production, the real client opens a
    streaming WebSocket session per audio direction (one for
    the patient-side audio, one for the clinician-side audio
    where channel separation is available) with the
    appropriate language code, custom-vocabulary configuration,
    and partial-results-stability setting. The mock returns
    canned transcript segments per audio_ref.
    """
    def __init__(self, segment_fixtures):
        # fixtures keyed by audio_ref -> list of segments
        self._fixtures = segment_fixtures
        self.sessions_started = []

    def start_streaming_transcription(self, language_code,
                                          audio_ref,
                                          custom_vocabulary=None,
                                          specialty=None,
                                          end_of_utterance_silence_ms=700):
        # Real boto3 (Transcribe streaming via the streaming
        # client class):
        #   transcribe_streaming.start_stream_transcription(
        #     LanguageCode=language_code,
        #     MediaSampleRateHertz=16000,
        #     MediaEncoding="pcm",
        #     VocabularyName=custom_vocabulary,
        #     EnablePartialResultsStabilization=True,
        #     PartialResultsStability="high",
        #     AudioStream=...)
        # Transcribe Medical uses a similar pattern with
        # `start_medical_stream_transcription` and a
        # Specialty parameter.
        self.sessions_started.append({
            "language_code":       language_code,
            "audio_ref":           audio_ref,
            "custom_vocabulary":   custom_vocabulary,
            "specialty":           specialty,
            "end_of_utterance_silence_ms":
                end_of_utterance_silence_ms,
            "started_at":          _now_iso(),
        })
        return {
            "session_id":  uuid.uuid4().hex[:16],
            "audio_ref":   audio_ref,
        }

    def get_finalized_segments(self, audio_ref):
        """In real Transcribe streaming, segments are
        emitted asynchronously through the WebSocket as the
        ASR stabilizes them. The mock just returns the
        pre-canned segment list."""
        return list(self._fixtures.get(audio_ref, []))


class MockTranslate:
    """
    Stands in for Amazon Translate's TranslateText API with
    Custom Terminology applied. In production this is
    `translate_client.translate_text` with the appropriate
    SourceLanguageCode, TargetLanguageCode, and
    TerminologyNames pointing at the institution's medical-
    domain custom-terminology resources. The mock returns
    canned translations per (source_text, source_lang,
    target_lang) tuple.
    """
    def __init__(self, translation_fixtures):
        self._fixtures = translation_fixtures
        self.invocations = []

    def translate_text(self, text, source_language_code,
                          target_language_code,
                          terminology_names=None):
        self.invocations.append({
            "source_language_code": source_language_code,
            "target_language_code": target_language_code,
            "terminology_names":    terminology_names or [],
            "text_length":          len(text or ""),
        })
        key = (text, source_language_code,
                target_language_code)
        fixture = self._fixtures.get(key, {})
        return {
            "translated_text":
                fixture.get("translated_text",
                              "<no fixture available>"),
            "applied_terminologies":
                fixture.get(
                    "applied_terminologies", []),
            "applied_settings_confidence":
                fixture.get("confidence", Decimal("0.85")),
        }


class MockBedrock:
    """
    Stands in for Amazon Bedrock's InvokeModel for LLM-based
    translation on hard content categories and for the
    independent faithfulness verifier. In production this is
    `bedrock_runtime.invoke_model` with the structured prompt,
    Guardrails configuration, and structured-output schema.
    """
    def __init__(self, translation_responses,
                    faithfulness_responses):
        self._translation_responses = translation_responses
        self._faithfulness_responses = faithfulness_responses
        self.invocations = []

    def invoke_translation(self, source_text, source_language,
                              target_language,
                              guardrail_id):
        self.invocations.append({
            "type":           "translation",
            "source_language": source_language,
            "target_language": target_language,
            "guardrail_id":    guardrail_id,
        })
        key = (source_text, source_language, target_language)
        response = self._translation_responses.get(key, {
            "translated_text":
                "<no LLM translation fixture available>",
            "confidence":     Decimal("0.80"),
            "guardrail_action": "NONE",
        })
        return {"body": json.dumps(response, default=str)}

    def invoke_faithfulness_check(self, source_text,
                                       target_text,
                                       source_language,
                                       target_language):
        self.invocations.append({
            "type":            "faithfulness",
            "source_language": source_language,
            "target_language": target_language,
        })
        key = (source_text, target_text)
        response = self._faithfulness_responses.get(key, {
            "score":         Decimal("0.92"),
            "issues":         [],
        })
        return {"body": json.dumps(response, default=str)}


class MockPolly:
    """
    Stands in for Amazon Polly's SynthesizeSpeech streaming
    invocation. In production this is
    `polly_client.synthesize_speech` with `OutputFormat="ogg_vorbis"`,
    `Engine="neural"` or "generative", `VoiceId=voice_id`,
    `LexiconNames=lexicon_ids`, and `TextType="ssml"` for
    fine-grained pronunciation control. The mock just records
    the invocation parameters and returns a placeholder.
    """
    def __init__(self):
        self.invocations = []

    def synthesize_speech_streaming(self, text, voice_id,
                                         engine, lexicon_ids,
                                         text_type="ssml",
                                         language_code=None):
        self.invocations.append({
            "voice_id":       voice_id,
            "engine":         engine,
            "lexicon_ids":    list(lexicon_ids or []),
            "text_type":      text_type,
            "language_code":  language_code,
            "text_length":    len(text or ""),
            "synthesized_at": _now_iso(),
        })
        return {
            "audio_stream_ref":
                f"audio-stream-{uuid.uuid4().hex[:10]}",
            "format":          "audio/ogg",
            "sample_rate":     "24000",
            "time_to_first_byte_ms":
                300 + (len(text or "") // 100) * 30,
        }


class MockConnect:
    """
    Stands in for Amazon Connect's contact-center and SIP
    integration for telephonic encounters. In production this
    handles the call routing, queue management, audio path
    between the patient phone and the cloud, and the human-
    interpreter handoff via call transfer. The mock just
    records the operations.
    """
    def __init__(self):
        self.contacts_started   = []
        self.audio_transfers    = []

    def start_contact(self, contact_id, language):
        self.contacts_started.append({
            "contact_id": contact_id,
            "language":   language,
            "started_at": _now_iso(),
        })
        return {"contact_id": contact_id,
                "audio_path": f"connect-audio-{contact_id}"}

    def transfer_audio(self, contact_id, from_mode,
                          to_mode, target_session=None):
        self.audio_transfers.append({
            "contact_id":      contact_id,
            "from_mode":       from_mode,
            "to_mode":         to_mode,
            "target_session":  target_session,
            "transferred_at":  _now_iso(),
        })


class MockChimeSDK:
    """
    Stands in for Amazon Chime SDK's WebRTC infrastructure
    for in-person and telehealth encounters with per-
    participant audio channels. The mock just records the
    operations.
    """
    def __init__(self):
        self.meetings_created   = []
        self.audio_transfers    = []

    def create_meeting(self, meeting_id, participants):
        self.meetings_created.append({
            "meeting_id":    meeting_id,
            "participants":  list(participants),
            "created_at":    _now_iso(),
        })
        return {
            "meeting_id":   meeting_id,
            "participants": [
                {"participant_id": p,
                 "audio_path":
                     f"chime-audio-{meeting_id}-{p}"}
                for p in participants
            ],
        }

    def transfer_audio(self, meeting_id, from_mode,
                          to_mode, target_session=None):
        self.audio_transfers.append({
            "meeting_id":      meeting_id,
            "from_mode":       from_mode,
            "to_mode":         to_mode,
            "target_session":  target_session,
            "transferred_at":  _now_iso(),
        })


class MockHumanInterpreterPool:
    """
    Stands in for the institutional human-interpreter pool
    integration (or the contracted vendor's pool, e.g.,
    LanguageLine, Stratus, Globo). In production this is a
    real integration over the vendor's API with routing,
    interpreter dispatch, audio transfer, and billing
    reconciliation. The mock just records the operations.
    """
    def __init__(self):
        self.dispatches  = []
        self.standby_sessions = {}

    def pre_stage_interpreter(self, language, dialect,
                                  encounter_type):
        session_id = f"interp-standby-{uuid.uuid4().hex[:10]}"
        self.standby_sessions[session_id] = {
            "session_id":      session_id,
            "language":        language,
            "dialect":         dialect,
            "encounter_type":  encounter_type,
            "status":          "standby",
            "staged_at":       _now_iso(),
        }
        return self.standby_sessions[session_id]

    def dispatch_on_demand(self, language, dialect,
                              encounter_type, urgency):
        session_id = f"interp-on-demand-{uuid.uuid4().hex[:10]}"
        dispatch = {
            "session_id":      session_id,
            "language":        language,
            "dialect":         dialect,
            "encounter_type":  encounter_type,
            "urgency":         urgency,
            "dispatch_time":   _now_iso(),
            "connect_time":    _now_iso(),
        }
        self.dispatches.append(dispatch)
        return dispatch

    def deliver_briefing(self, session_id, briefing):
        # Production sends the conversational-context briefing
        # to the interpreter through the pool's interpreter-
        # facing UI, with appropriate confidentiality scoping.
        return {"delivered": True,
                "briefing_id":
                    f"brief-{uuid.uuid4().hex[:8]}"}


class MockEncounterTable:
    """In-memory stand-in for the DynamoDB encounter table.
    Each entry tracks one encounter session through the
    seven pipeline stages."""
    def __init__(self):
        self._items = {}

    def get(self, encounter_id):
        return dict(self._items.get(encounter_id, {}))

    def put(self, encounter_id, item):
        self._items[encounter_id] = dict(item)

    def update(self, encounter_id, updates):
        existing = self._items.setdefault(
            encounter_id, {"encounter_id": encounter_id})
        existing.update(updates)


class MockAuditTable:
    """In-memory stand-in for the DynamoDB per-utterance
    audit table."""
    def __init__(self):
        self._items = []

    def put(self, item):
        self._items.append(dict(item))

    def query_by_encounter(self, encounter_id):
        return [dict(item) for item in self._items
                  if item.get("encounter_id") ==
                     encounter_id]


class MockS3:
    """
    Stands in for S3 audio storage and audit archive. Holds
    objects in memory keyed by (bucket, key). Production uses
    customer-managed KMS keys for encryption and lifecycle
    policies for retention.
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
    """Stands in for Amazon EventBridge."""
    def __init__(self):
        self.events = []

    def put_events(self, entries):
        for entry in entries:
            self.events.append(dict(entry))


class MockCloudWatch:
    """Stands in for CloudWatch metric emission."""
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
encounter_table       = MockEncounterTable()
audit_table           = MockAuditTable()
s3_store              = MockS3()
event_bus             = MockEventBus()
cloudwatch            = MockCloudWatch()
connect_mock          = MockConnect()
chime_mock            = MockChimeSDK()
interpreter_pool      = MockHumanInterpreterPool()
polly_mock            = MockPolly()
# transcribe_mock, translate_mock, and bedrock_mock are wired
# up in run_demo() with fixture data for the scenario.
transcribe_mock       = None
translate_mock        = None
bedrock_mock          = None


# --- Patient demographics lookup ---
PATIENT_DEMOGRAPHICS = {
    "pt-elena-9c1b": {
        "patient_id":         "pt-elena-9c1b",
        "preferred_language": "es-MX",
        "preferred_dialect":  "Mexican Spanish",
        "jurisdiction":       "VA",
        "age_years":          64,
    },
    "pt-tuan-3d52": {
        "patient_id":         "pt-tuan-3d52",
        "preferred_language": "vi-VN",
        "preferred_dialect":  "Vietnamese",
        "jurisdiction":       "IL",
        "age_years":          71,
    },
    "pt-saw-4e88": {
        "patient_id":         "pt-saw-4e88",
        "preferred_language": "ksw-MM",
        "preferred_dialect":  "Karen",
        "jurisdiction":       "MN",
        "age_years":          38,
    },
}


def lookup_patient_context(patient_id):
    return dict(PATIENT_DEMOGRAPHICS.get(patient_id, {}))


def lookup_language_pair(source_language, target_language):
    """Return the per-pair configuration. Production reads
    from the language-pair-config DynamoDB table; the demo
    uses the in-memory dict."""
    pair_id = f"{source_language}_to_{target_language}"
    return dict(LANGUAGE_PAIR_CONFIGS.get(pair_id, {}))


def determine_deployment_posture(topic_category, pair_def):
    """Map the topic category to the institutional deployment
    posture. The mapping is policy-owned by clinical-quality
    leadership."""
    return TOPIC_TO_POSTURE.get(topic_category, "human_only")


def select_endpointing_threshold(topic_category):
    """Pick the silence threshold for end-of-utterance
    detection based on the topic category."""
    return ENDPOINTING_THRESHOLDS_MS.get(
        topic_category,
        ENDPOINTING_THRESHOLDS_MS["routine_clinical"])
```

---

## Step 1: Set Up the Encounter Session with Language Pair, Deployment Posture, and Consent

*The pseudocode calls this `ON encounter_initiated(...)`. When the encounter begins, the system records the language pair, identifies the deployment posture per the encounter's topic category, presents the consent disclosure to the patient (in the patient's language with any jurisdiction-specific overlay), captures the consent decision, and provisions per-pair vendor configuration and human-interpreter standby where the posture requires it. Skip the explicit pair validation and the system might run an unvalidated pair in machine-mediated mode; skip the deployment-posture mapping and a safety-critical encounter might run machine-only when it should be human-primary; skip the consent capture and the institution operates outside its language-access policy.*

```python
def capture_patient_consent(patient_id, disclosure,
                                consent_type):
    """
    Capture the patient's consent. Production presents the
    disclosure through the device or contact-center UI in
    the patient's preferred language and records explicit
    acknowledgment (audio confirmation for telephonic, tap
    confirmation for in-person and telehealth). The demo
    simulates a granted consent.
    """
    consent_id = "consent-" + uuid.uuid4().hex[:12]
    return {
        "granted":       True,
        "consent_id":    consent_id,
        "consent_type":  consent_type,
        "disclosure_text_hash":
            _hash_value(disclosure),
        "captured_at":   _now_iso(),
    }


def initiate_human_interpreter_handoff(language, dialect,
                                            encounter_type):
    """Route to the human-interpreter pool when machine
    interpretation is not available or not appropriate."""
    return interpreter_pool.dispatch_on_demand(
        language=language,
        dialect=dialect,
        encounter_type=encounter_type,
        urgency="standard")


def encounter_initiated(clinician_id, patient_id,
                            declared_language, declared_dialect,
                            encounter_type, topic_category,
                            encounter_id_hint=None):
    """
    Bootstrap an encounter session: validate the language
    pair has been validated for production use, determine
    the deployment posture from the topic category, capture
    consent in the patient's language, and provision per-
    pair vendor configuration plus human-interpreter standby
    where the posture requires it.
    """
    # Step 1A: validate pair coverage for the patient-to-
    # clinician direction. The clinician-to-patient direction
    # is validated separately via the second pair lookup.
    patient_to_clinician = lookup_language_pair(
        source_language=declared_language,
        target_language="en-US")
    clinician_to_patient = lookup_language_pair(
        source_language="en-US",
        target_language=declared_language)

    if not patient_to_clinician or \
       patient_to_clinician.get("deployment_status") != \
           "validated":
        # Pair not validated; route the entire encounter to
        # human-only interpretation.
        audit_log({
            "event_type":       "PAIR_NOT_VALIDATED",
            "declared_language": declared_language,
            "direction":         "patient_to_clinician",
            "timestamp":         _now_iso(),
        })
        return {
            "status":  "PAIR_REQUIRES_HUMAN_INTERPRETER",
            "handoff":
                initiate_human_interpreter_handoff(
                    language=declared_language,
                    dialect=declared_dialect,
                    encounter_type=encounter_type),
        }

    # Step 1B: determine the deployment posture for this
    # encounter based on the topic category.
    posture = determine_deployment_posture(
        topic_category=topic_category,
        pair_def=patient_to_clinician)

    if posture == "human_only":
        # Topic category requires human-only interpretation;
        # short-circuit to the human-interpreter pool.
        audit_log({
            "event_type":      "HUMAN_ONLY_REQUIRED",
            "topic_category":  topic_category,
            "language_pair":
                patient_to_clinician.get("pair_id"),
            "timestamp":       _now_iso(),
        })
        return {
            "status":   "HUMAN_ONLY_REQUIRED",
            "handoff":
                initiate_human_interpreter_handoff(
                    language=declared_language,
                    dialect=declared_dialect,
                    encounter_type=encounter_type),
        }

    # Step 1C: consent disclosure in the patient's language,
    # with any jurisdiction-specific overlay.
    patient_context = lookup_patient_context(patient_id)
    disclosure = _select_consent_disclosure(
        language=declared_language,
        jurisdiction=patient_context.get("jurisdiction"))
    consent_outcome = capture_patient_consent(
        patient_id=patient_id,
        disclosure=disclosure,
        consent_type="machine_interpretation")

    if not consent_outcome["granted"]:
        audit_log({
            "event_type":       "CONSENT_DECLINED",
            "patient_id_hash":
                _hash_value(patient_id),
            "timestamp":        _now_iso(),
        })
        return {
            "status":   "CONSENT_DECLINED_HUMAN_ROUTING",
            "handoff":
                initiate_human_interpreter_handoff(
                    language=declared_language,
                    dialect=declared_dialect,
                    encounter_type=encounter_type),
        }

    # Step 1D: bootstrap the encounter record and pre-stage
    # human-interpreter standby where the posture requires.
    encounter_id = encounter_id_hint or (
        "mi-" + uuid.uuid4().hex[:16])

    human_standby = None
    if posture in ("machine_with_human_standby",
                       "human_primary_with_machine_assistance"):
        human_standby = interpreter_pool.pre_stage_interpreter(
            language=declared_language,
            dialect=declared_dialect,
            encounter_type=encounter_type)

    encounter_table.put(encounter_id, _to_decimal({
        "encounter_id":           encounter_id,
        "patient_id_hash":        _hash_value(patient_id),
        "clinician_id":           clinician_id,
        "declared_language":      declared_language,
        "declared_dialect":       declared_dialect,
        "encounter_type":         encounter_type,
        "topic_category":         topic_category,
        "deployment_posture":     posture,
        "language_pair_patient_to_clinician":
            patient_to_clinician.get("pair_id"),
        "language_pair_clinician_to_patient":
            clinician_to_patient.get("pair_id")
            if clinician_to_patient else None,
        "patient_to_clinician_config":
            patient_to_clinician,
        "clinician_to_patient_config":
            clinician_to_patient or {},
        "consent_id":
            consent_outcome["consent_id"],
        "consent_disclosure_hash":
            consent_outcome["disclosure_text_hash"],
        "human_standby_session":  human_standby,
        "endpointing_threshold_ms":
            select_endpointing_threshold(topic_category),
        "asr_pipeline_version":
            ASR_PIPELINE_VERSION,
        "mt_pipeline_version":
            MT_PIPELINE_VERSION,
        "tts_pipeline_version":
            TTS_PIPELINE_VERSION,
        "started_at":             _now_iso(),
        "status":                 "setup_complete",
    }))

    event_bus.put_events([{
        "Source":       "medical_interpretation",
        "DetailType":   "encounter_setup_complete",
        "EventBusName": EVENT_BUS_NAME,
        "Detail": json.dumps({
            "encounter_id":   encounter_id,
            "language_pair":
                patient_to_clinician.get("pair_id"),
            "posture":        posture,
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "EncountersInitiated", 1,
        "Count",
        dimensions={
            "language_pair":
                patient_to_clinician.get(
                    "pair_id", "unknown"),
            "posture":         posture,
            "topic_category":  topic_category,
        })

    audit_log({
        "event_type":       "ENCOUNTER_SETUP_COMPLETE",
        "encounter_id":     encounter_id,
        "language_pair":
            patient_to_clinician.get("pair_id"),
        "posture":          posture,
        "topic_category":   topic_category,
        "human_standby":    bool(human_standby),
        "timestamp":        _now_iso(),
    })

    return {
        "status":         "READY_FOR_AUDIO",
        "encounter_id":   encounter_id,
        "language_pair":
            patient_to_clinician.get("pair_id"),
        "posture":        posture,
    }
```

---

## Step 2: Route Per-Speaker Audio Streams to the Appropriate ASR Engine

*The pseudocode calls this `route_audio_to_asr(...)`. The audio router takes the patient-side audio and the clinician-side audio (separated where the deployment supports it, single-channel with diarization where it does not), routes each stream to the appropriate streaming-ASR endpoint with the correct language code and custom-vocabulary configuration, and tracks per-stream quality. Skip the channel separation and diarization becomes a hard problem; skip the per-stream quality tracking and audio-quality issues surface as transcript errors that the clinician then has to chase.*

```python
def assess_stream_quality(stream_metadata, expected_language):
    """Assess audio stream quality (SNR, sample rate, codec)
    against institutional minimums."""
    snr = Decimal(str(stream_metadata.get("snr_db", 20)))
    sample_rate = stream_metadata.get(
        "sample_rate", DEFAULT_MIN_SAMPLE_RATE_HZ)
    return {
        "snr_db":            snr,
        "sample_rate":       sample_rate,
        "expected_language": expected_language,
        "passes_minimum":
            snr >= DEFAULT_MIN_SNR_DB
            and sample_rate >= DEFAULT_MIN_SAMPLE_RATE_HZ,
    }


def route_audio_to_asr(encounter_id, patient_audio_stream,
                            clinician_audio_stream):
    """
    For an active encounter, start the streaming-ASR sessions
    for the patient and clinician audio streams with the
    appropriate per-language configuration. Production opens
    real WebSocket sessions to Transcribe; the demo just
    records the start-of-session metadata.
    """
    state = encounter_table.get(encounter_id)

    # Step 2A: per-stream audio quality assessment.
    patient_quality = assess_stream_quality(
        stream_metadata=patient_audio_stream,
        expected_language=state.get("declared_language"))
    clinician_quality = assess_stream_quality(
        stream_metadata=clinician_audio_stream,
        expected_language="en-US")

    if not patient_quality["passes_minimum"] or \
       not clinician_quality["passes_minimum"]:
        audit_log({
            "event_type":       "AUDIO_QUALITY_WARNING",
            "encounter_id":     encounter_id,
            "patient_passes":
                patient_quality["passes_minimum"],
            "clinician_passes":
                clinician_quality["passes_minimum"],
            "timestamp":        _now_iso(),
        })
        # Continue with degraded confidence; the downstream
        # confidence-based escalation will handle the low-
        # quality audio. Production may also prompt for
        # microphone repositioning at this point.

    # Step 2B: start the streaming ASR sessions per stream.
    pair_patient = state.get(
        "patient_to_clinician_config", {})
    pair_clinician = state.get(
        "clinician_to_patient_config", {})

    patient_asr = transcribe_mock.start_streaming_transcription(
        language_code=state.get("declared_language"),
        audio_ref=patient_audio_stream.get("audio_ref"),
        custom_vocabulary=pair_patient.get(
            "asr_custom_vocabulary"),
        end_of_utterance_silence_ms=
            int(state.get("endpointing_threshold_ms", 700)))

    clinician_asr = transcribe_mock.start_streaming_transcription(
        language_code="en-US",
        audio_ref=clinician_audio_stream.get("audio_ref"),
        custom_vocabulary=pair_clinician.get(
            "asr_custom_vocabulary"),
        specialty=pair_clinician.get("asr_specialty"),
        end_of_utterance_silence_ms=
            int(state.get("endpointing_threshold_ms", 700)))

    encounter_table.update(encounter_id, _to_decimal({
        "patient_asr_session_id":
            patient_asr["session_id"],
        "clinician_asr_session_id":
            clinician_asr["session_id"],
        "patient_audio_ref":
            patient_audio_stream.get("audio_ref"),
        "clinician_audio_ref":
            clinician_audio_stream.get("audio_ref"),
        "audio_quality": {
            "patient":   patient_quality,
            "clinician": clinician_quality,
        },
        "asr_streaming_started_at":  _now_iso(),
        "status":                    "asr_streaming",
    }))

    event_bus.put_events([{
        "Source":       "medical_interpretation",
        "DetailType":   "audio_streaming",
        "EventBusName": EVENT_BUS_NAME,
        "Detail": json.dumps({
            "encounter_id":  encounter_id,
            "patient_session_id":
                patient_asr["session_id"],
            "clinician_session_id":
                clinician_asr["session_id"],
        }),
    }])

    audit_log({
        "event_type":          "ASR_STREAMING_STARTED",
        "encounter_id":        encounter_id,
        "patient_session_id":
            patient_asr["session_id"],
        "clinician_session_id":
            clinician_asr["session_id"],
        "timestamp":           _now_iso(),
    })

    return {
        "patient_asr":   patient_asr,
        "clinician_asr": clinician_asr,
    }
```

---

## Step 3: Translate Finalized Source-Language Transcripts with Verification

*The pseudocode calls this `ON asr_finalized_transcript(...)`. Each finalized source transcript is routed to the appropriate translation engine: Translate with Custom Terminology for routine content, Bedrock LLM with translation prompt for high-fluency or low-resource cases. The translated output is verified for numerical-content fidelity (drug doses, dosing intervals, dates, weights) and faithfulness against the source. Skip the verification and the system can produce confidently-wrong translations on the content that matters most clinically.*

```python
# Number-and-unit verification uses regular expressions to
# extract numerical content from source and target. Production
# uses a per-language number-and-unit grammar that handles
# spelled-out numbers ("twenty-five milligrams"), localized
# unit expressions, fraction handling, and drug-dose patterns.
# The demo uses a simple digit-and-unit pattern that catches
# the common cases.
NUMBER_PATTERN = re.compile(
    r"(\d+(?:[\.,]\d+)?)\s*"
    r"(mg|mcg|g|ml|mL|kg|lbs?|cc|hours?|hrs?|times?|"
    r"days?|weeks?|months?|years?|degrees?|"
    r"miligramos|gramos|mililitros|kilos|veces|"
    r"horas|dias|semanas|meses|anos)?",
    re.IGNORECASE)

# Map of unit translations across languages so the
# number-and-unit verifier can recognize equivalent units.
UNIT_EQUIVALENCES = {
    "mg":           {"mg", "miligramos", "milligrams",
                     "milligram"},
    "mcg":          {"mcg", "microgramos", "micrograms"},
    "g":            {"g", "gramos", "grams", "gram"},
    "ml":           {"ml", "mL", "mililitros",
                     "milliliters", "milliliter"},
    "kg":           {"kg", "kilos", "kilogramos",
                     "kilograms", "kilogram"},
    "times":        {"times", "veces"},
    "hours":        {"hours", "hrs", "horas"},
    "days":         {"days", "dias"},
    "weeks":        {"weeks", "semanas"},
    "months":       {"months", "meses"},
    "years":        {"years", "anos"},
}


def _canonical_unit(unit):
    """Normalize a unit string to its canonical form for
    matching across languages."""
    if not unit:
        return ""
    unit_lower = unit.strip().lower()
    for canonical, equivalents in UNIT_EQUIVALENCES.items():
        if unit_lower in {e.lower()
                            for e in equivalents}:
            return canonical
    return unit_lower


def extract_numerical_content(text, language):
    """Extract (value, canonical_unit) pairs from a piece of
    text. Production handles per-language number-word
    expansion (writing out "twenty-five" as 25); the demo
    handles digits with optional unit suffixes."""
    if not text:
        return []
    pairs = []
    for match in NUMBER_PATTERN.finditer(text):
        value_str = match.group(1).replace(",", ".")
        try:
            value = Decimal(value_str)
        except Exception:  # pylint: disable=broad-except
            continue
        unit = _canonical_unit(match.group(2) or "")
        pairs.append((value, unit))
    return pairs


def verify_numerical_content(source_text, target_text,
                                  source_language,
                                  target_language):
    """
    Compare the numerical content extracted from source
    against the numerical content extracted from target.
    Drug doses, dosing intervals, ages, weights, durations,
    and any other numerical content all checked. A mismatch
    is a hard block.
    """
    source_pairs = extract_numerical_content(
        source_text, source_language)
    target_pairs = extract_numerical_content(
        target_text, target_language)

    # Compare as multisets: every (value, unit) pair in source
    # must appear in target with the same value and an
    # equivalent unit. Production also handles expected unit
    # conversions (mg <-> g where the value scales) and
    # allowable rendering variations ("1500 mg" vs "1.5 g");
    # the demo treats them as mismatches and routes to human.
    source_multiset = sorted(source_pairs)
    target_multiset = sorted(target_pairs)

    matches = source_multiset == target_multiset
    return {
        "matches":           matches,
        "source_extractions": [
            {"value": str(v), "unit": u}
            for v, u in source_multiset
        ],
        "target_extractions": [
            {"value": str(v), "unit": u}
            for v, u in target_multiset
        ],
    }


def archive_text(text):
    """Archive transcript content to encrypted storage with
    appropriate retention. The audit pipeline references the
    archived text by hash rather than echoing it through
    logs. Production writes to an SSE-KMS-encrypted S3 bucket;
    the demo just hashes for the audit reference."""
    text_hash = _hash_value(text)
    s3_store.put_object(
        bucket=AUDIO_BUCKET,
        key=f"transcripts/{text_hash[:16]}.txt",
        body=(text or "").encode("utf-8"),
        metadata={"text_hash": text_hash})
    return text_hash


def select_translation_engine(source_language, target_language,
                                  topic_category, segment_text,
                                  pair_def):
    """
    Pick the translation engine based on the per-pair
    configuration and the content category. Routine content
    on validated pairs goes to Amazon Translate with Custom
    Terminology; safety-critical or low-resource content on
    pairs configured for hybrid mode goes to Bedrock with the
    translation prompt and Guardrails.
    """
    engine = pair_def.get("mt_engine", "translate")
    if engine == "translate":
        return "translate"
    if engine == "hybrid_translate_bedrock":
        # Hybrid: route safety-critical, mental-health, and
        # end-of-life content to Bedrock for high-fluency
        # rendering; route routine and administrative
        # content to Translate.
        if topic_category in (
                "safety_critical", "mental_health",
                "end_of_life", "complex_new_diagnosis"):
            return "bedrock_llm"
        # Long source segments (heuristic for clinically-
        # rich content) also benefit from LLM rendering.
        if len(segment_text or "") > 200:
            return "bedrock_llm"
        return "translate"
    if engine == "bedrock_only":
        return "bedrock_llm"
    return "translate"


def check_faithfulness(source_text, target_text,
                            source_language, target_language):
    """Run an independent verifier model to check that the
    target translation is faithful to the source: no invented
    content, no omitted content, no contradictions. The
    verifier is deliberately a different model from the one
    that produced the translation."""
    response = bedrock_mock.invoke_faithfulness_check(
        source_text=source_text,
        target_text=target_text,
        source_language=source_language,
        target_language=target_language)
    parsed = json.loads(response["body"])
    return {
        "score":   Decimal(str(parsed.get("score", 0))),
        "issues":  parsed.get("issues", []),
    }


def escalate_to_human(encounter_id, reason, segment,
                          additional_context=None):
    """Triggered from inside the translation pipeline when
    a verification gate fails. Implementation deferred to
    Step 6; here we just capture the trigger event."""
    audit_log({
        "event_type":      "ESCALATION_TRIGGERED",
        "encounter_id":    encounter_id,
        "reason":          reason,
        "segment_id":      segment.get("utterance_id"),
        "timestamp":       _now_iso(),
    })
    return {"escalation_triggered": True, "reason": reason}


def asr_finalized_transcript(encounter_id, speaker, segment):
    """
    Triggered when an ASR stream finalizes a transcript
    segment. speaker is "patient" or "clinician". Pick the
    translation direction, route to the appropriate engine,
    verify numerical content, verify faithfulness on LLM
    output, and persist the per-utterance audit record.
    """
    state = encounter_table.get(encounter_id)

    # Step 3A: select translation direction based on speaker.
    if speaker == "patient":
        source_language = state.get("declared_language")
        target_language = "en-US"
        target_audience = state.get("clinician_id")
        pair_def = state.get(
            "patient_to_clinician_config", {})
    else:
        source_language = "en-US"
        target_language = state.get("declared_language")
        target_audience = state.get("patient_id_hash")
        pair_def = state.get(
            "clinician_to_patient_config", {})

    # Step 3B: select translation engine.
    engine = select_translation_engine(
        source_language=source_language,
        target_language=target_language,
        topic_category=state.get("topic_category"),
        segment_text=segment.get("transcript_text", ""),
        pair_def=pair_def)

    # Step 3C: translate.
    translated_text = ""
    translation_confidence = Decimal("0")
    guardrail_action = None

    if engine == "translate":
        translation_result = translate_mock.translate_text(
            text=segment.get("transcript_text", ""),
            source_language_code=source_language,
            target_language_code=target_language,
            terminology_names=[
                pair_def.get("mt_custom_terminology")
            ] if pair_def.get("mt_custom_terminology")
              else None)
        translated_text = translation_result[
            "translated_text"]
        translation_confidence = Decimal(str(
            translation_result.get(
                "applied_settings_confidence", 0.85)))
    elif engine == "bedrock_llm":
        bedrock_response = bedrock_mock.invoke_translation(
            source_text=segment.get("transcript_text", ""),
            source_language=source_language,
            target_language=target_language,
            guardrail_id=TRANSLATION_GUARDRAIL_ID)
        parsed = json.loads(bedrock_response["body"])
        translated_text = parsed.get("translated_text", "")
        translation_confidence = Decimal(str(
            parsed.get("confidence", 0.80)))
        guardrail_action = parsed.get("guardrail_action")

    # Step 3D: number-and-unit verification (hard gate).
    number_verification = verify_numerical_content(
        source_text=segment.get("transcript_text", ""),
        target_text=translated_text,
        source_language=source_language,
        target_language=target_language)

    if not number_verification["matches"]:
        # Hard block on numerical mismatch. Route this
        # segment to a human interpreter; do not deliver the
        # confidently-wrong translation.
        audit_log({
            "event_type":     "NUMBER_MISMATCH_BLOCK",
            "encounter_id":   encounter_id,
            "segment_id":     segment.get("utterance_id"),
            "source_extractions":
                number_verification["source_extractions"],
            "target_extractions":
                number_verification["target_extractions"],
            "timestamp":      _now_iso(),
        })
        escalate_to_human(
            encounter_id=encounter_id,
            reason="number_mismatch",
            segment=segment,
            additional_context=number_verification)
        # Persist the audit record reflecting the block.
        audit_table.put(_to_decimal({
            "encounter_id":     encounter_id,
            "utterance_id":
                segment.get("utterance_id"),
            "timestamp":        segment.get("timestamp"),
            "speaker":          speaker,
            "source_language":  source_language,
            "target_language":  target_language,
            "source_text_hash":
                archive_text(
                    segment.get("transcript_text", "")),
            "target_text_hash":
                archive_text(translated_text),
            "engine":           engine,
            "translation_confidence":
                translation_confidence,
            "asr_confidence":
                Decimal(str(segment.get(
                    "per_word_confidence_min", 0))),
            "number_verification":
                number_verification,
            "escalation_triggered":  True,
            "escalation_reason":     "number_mismatch",
        }))
        return {
            "translated_text":   None,
            "escalated":         True,
            "escalation_reason": "number_mismatch",
        }

    # Step 3E: faithfulness check on LLM output.
    faithfulness_result = None
    if engine == "bedrock_llm":
        faithfulness_result = check_faithfulness(
            source_text=segment.get("transcript_text", ""),
            target_text=translated_text,
            source_language=source_language,
            target_language=target_language)
        if faithfulness_result["score"] < \
                DEFAULT_FAITHFULNESS_THRESHOLD:
            audit_log({
                "event_type":     "FAITHFULNESS_FAILURE",
                "encounter_id":   encounter_id,
                "segment_id":
                    segment.get("utterance_id"),
                "score":
                    str(faithfulness_result["score"]),
                "issues":
                    faithfulness_result["issues"],
                "timestamp":      _now_iso(),
            })
            escalate_to_human(
                encounter_id=encounter_id,
                reason="faithfulness_below_threshold",
                segment=segment,
                additional_context=faithfulness_result)
            audit_table.put(_to_decimal({
                "encounter_id":   encounter_id,
                "utterance_id":
                    segment.get("utterance_id"),
                "timestamp":
                    segment.get("timestamp"),
                "speaker":        speaker,
                "source_language": source_language,
                "target_language": target_language,
                "source_text_hash":
                    archive_text(
                        segment.get(
                            "transcript_text", "")),
                "target_text_hash":
                    archive_text(translated_text),
                "engine":         engine,
                "translation_confidence":
                    translation_confidence,
                "asr_confidence":
                    Decimal(str(segment.get(
                        "per_word_confidence_min",
                        0))),
                "faithfulness_score":
                    faithfulness_result["score"],
                "escalation_triggered":  True,
                "escalation_reason":
                    "faithfulness_below_threshold",
            }))
            return {
                "translated_text":   None,
                "escalated":         True,
                "escalation_reason":
                    "faithfulness_below_threshold",
            }

    # Step 3F: confidence-based escalation by deployment
    # posture.
    confidence_threshold = Decimal(str(
        pair_def.get(
            "confidence_threshold",
            DEFAULT_TRANSLATION_CONFIDENCE_THRESHOLD)))
    asr_confidence = Decimal(str(
        segment.get("per_word_confidence_min", 1)))
    low_confidence = (
        translation_confidence < confidence_threshold
        or asr_confidence <
            DEFAULT_ASR_CONFIDENCE_THRESHOLD)

    posture = state.get("deployment_posture")
    if low_confidence and posture in (
            "machine_with_human_standby",
            "human_primary_with_machine_assistance"):
        escalate_to_human(
            encounter_id=encounter_id,
            reason="confidence_below_threshold",
            segment=segment,
            additional_context={
                "translation_confidence":
                    str(translation_confidence),
                "asr_confidence":
                    str(asr_confidence),
            })
        audit_table.put(_to_decimal({
            "encounter_id":   encounter_id,
            "utterance_id":
                segment.get("utterance_id"),
            "timestamp":      segment.get("timestamp"),
            "speaker":        speaker,
            "source_language": source_language,
            "target_language": target_language,
            "source_text_hash":
                archive_text(
                    segment.get("transcript_text", "")),
            "target_text_hash":
                archive_text(translated_text),
            "engine":         engine,
            "translation_confidence":
                translation_confidence,
            "asr_confidence": asr_confidence,
            "number_verification": number_verification,
            "faithfulness_score":
                (faithfulness_result["score"]
                 if faithfulness_result else None),
            "escalation_triggered":  True,
            "escalation_reason":
                "confidence_below_threshold",
        }))
        return {
            "translated_text":   None,
            "escalated":         True,
            "escalation_reason":
                "confidence_below_threshold",
        }

    # Step 3G: persist per-utterance audit record for the
    # successful path and emit operational metrics.
    audit_table.put(_to_decimal({
        "encounter_id":   encounter_id,
        "utterance_id":
            segment.get("utterance_id"),
        "timestamp":      segment.get("timestamp"),
        "speaker":        speaker,
        "source_language": source_language,
        "target_language": target_language,
        "source_text_hash":
            archive_text(
                segment.get("transcript_text", "")),
        "target_text_hash":
            archive_text(translated_text),
        "engine":          engine,
        "translation_confidence":
            translation_confidence,
        "asr_confidence":  asr_confidence,
        "number_verification": number_verification,
        "faithfulness_score":
            (faithfulness_result["score"]
             if faithfulness_result else None),
        "guardrail_action": guardrail_action,
        "escalation_triggered":  False,
    }))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE,
        "UtteranceTranslated",
        1, "Count",
        dimensions={
            "language_pair":
                pair_def.get("pair_id", "unknown"),
            "engine":          engine,
            "low_confidence":
                "true" if low_confidence else "false",
        })

    return {
        "translated_text":         translated_text,
        "translation_confidence":  translation_confidence,
        "engine":                  engine,
        "target_audience":         target_audience,
        "escalated":               False,
        "number_verification":     number_verification,
        "faithfulness_score":
            (faithfulness_result["score"]
             if faithfulness_result else None),
    }
```

---

## Step 4: Synthesize Target-Language Audio with Streaming TTS

*The pseudocode calls this `synthesize_translated_audio(...)`. The verified translation goes to TTS with the appropriate voice for the target language and dialect, with a pronunciation lexicon applied for institution-specific terms. Output streams to the listener as audio bytes are produced. Skip the lexicon and drug names get mispronounced in ways that confuse the listener; skip streaming output and time-to-first-audio doubles, breaking the conversational flow.*

```python
def build_ssml(text, language, lexicon_ids):
    """Wrap the translated text in SSML so Polly can apply
    the configured pronunciation lexicons. Production tunes
    additional SSML hints (pause durations, prosody for
    sensitive content); the demo emits a minimal SSML
    envelope."""
    return (
        f'<speak xml:lang="{language}">{text or ""}</speak>')


def deliver_audio_stream(target_audience, audio_stream,
                              encounter_id,
                              time_to_first_byte_target_ms):
    """Deliver the synthesized audio to the target audience
    through the appropriate audio path (Connect for
    telephonic, Chime SDK for in-person and telehealth).
    Production handles the audio mixing and the playback
    path; the demo logs the delivery."""
    audit_log({
        "event_type":            "AUDIO_DELIVERED",
        "encounter_id":          encounter_id,
        "audio_stream_ref":
            audio_stream.get("audio_stream_ref"),
        "target_audience_hash":
            _hash_value(target_audience),
        "time_to_first_byte_ms":
            audio_stream.get(
                "time_to_first_byte_ms", 0),
        "ttfb_target_ms":
            time_to_first_byte_target_ms,
        "timestamp":             _now_iso(),
    })


def synthesize_translated_audio(encounter_id,
                                     translated_text,
                                     target_language,
                                     target_audience,
                                     source_timestamp_ms):
    """
    Synthesize and stream the translated audio. Picks the
    appropriate voice per pair configuration, applies the
    pronunciation lexicons, streams to the target audience,
    and records end-to-end latency.
    """
    state = encounter_table.get(encounter_id)

    # Determine which pair_def applies based on the target.
    if target_audience == state.get("clinician_id"):
        pair_def = state.get(
            "patient_to_clinician_config", {})
    else:
        pair_def = state.get(
            "clinician_to_patient_config", {})

    # Step 4A: build SSML with pronunciation lexicons.
    ssml_text = build_ssml(
        text=translated_text,
        language=target_language,
        lexicon_ids=pair_def.get("tts_lexicons", []))

    # Step 4B: synthesize with streaming output.
    synthesis = polly_mock.synthesize_speech_streaming(
        text=ssml_text,
        voice_id=pair_def.get("tts_voice", "Joanna"),
        engine=pair_def.get("tts_engine", "neural"),
        lexicon_ids=pair_def.get("tts_lexicons", []),
        text_type="ssml",
        language_code=target_language)

    # Step 4C: stream audio to the target audience.
    deliver_audio_stream(
        target_audience=target_audience,
        audio_stream=synthesis,
        encounter_id=encounter_id,
        time_to_first_byte_target_ms=800)

    # Step 4D: track end-to-end latency.
    end_to_end_latency_ms = max(
        1, int((datetime.now(timezone.utc).timestamp()
                  * 1000) - (source_timestamp_ms or 0)))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE,
        "EndToEndLatencyMs",
        end_to_end_latency_ms, "Milliseconds",
        dimensions={
            "language_pair":
                pair_def.get("pair_id", "unknown"),
            "posture":
                state.get(
                    "deployment_posture", "unknown"),
        })

    return {
        "audio_stream":            synthesis,
        "end_to_end_latency_ms":   end_to_end_latency_ms,
    }
```

---

## Step 5: Manage Turn-Taking and Barge-In with a Conversational State Machine

*The pseudocode calls these `ON vad_event(...)` and `handle_barge_in(...)`. The conversational state machine tracks who is speaking, when the system is translating, when the system is playing translated audio, and how to handle interruptions. Barge-in (a speaker starting before the system has finished translating the previous turn) gracefully halts in-flight TTS and queues the new audio. Skip the state machine and the conversation feels like a walkie-talkie; skip barge-in handling and speakers talk over the system's output and lose content.*

```python
def transition_to_state(encounter_id, new_state, **extra):
    """Transition the conversational state machine to a new
    state and persist."""
    updates = {
        "conversational_state": new_state,
        "last_state_change_at": _now_iso(),
    }
    updates.update(extra)
    encounter_table.update(encounter_id, _to_decimal(updates))


def get_current_state(encounter_id):
    state = encounter_table.get(encounter_id)
    return state.get("conversational_state", "idle")


def halt_translation(translation_id):
    """Halt an in-flight TTS playback. Production sends an
    abort signal to the TTS streaming session and clears the
    pending audio buffer; the demo just logs."""
    audit_log({
        "event_type":      "TRANSLATION_HALTED",
        "translation_id":  translation_id,
        "timestamp":       _now_iso(),
    })


def handle_barge_in(encounter_id, interrupting_speaker,
                       in_flight_translation):
    """A new speaker started before the system finished
    translating the previous turn. Halt TTS gracefully and
    let the normal ASR path capture the interrupting
    speaker's utterance."""
    halt_translation(
        in_flight_translation.get("translation_id"))
    audit_log({
        "event_type":      "BARGE_IN",
        "encounter_id":    encounter_id,
        "interrupting_speaker": interrupting_speaker,
        "in_flight_translation_id":
            in_flight_translation.get("translation_id"),
        "timestamp":       _now_iso(),
    })


def vad_event(encounter_id, speaker, event_type):
    """
    VAD events (speech_start, speech_end, silence) drive the
    conversational state machine. Production wires this to
    the audio capture path; the demo provides the function
    so test scenarios can drive state transitions explicitly.
    event_type: "speech_start", "speech_end", "silence"
    """
    state = encounter_table.get(encounter_id)
    current_state = state.get(
        "conversational_state", "idle")

    if event_type == "speech_start":
        if current_state == "idle":
            transition_to_state(
                encounter_id, "speaker_active",
                active_speaker=speaker)
        elif current_state == "translating" and \
                speaker != state.get(
                    "translating_for_speaker"):
            handle_barge_in(
                encounter_id=encounter_id,
                interrupting_speaker=speaker,
                in_flight_translation=state.get(
                    "in_flight_translation", {}))
            transition_to_state(
                encounter_id, "speaker_active",
                active_speaker=speaker)
        elif current_state == "playing_translation" and \
                speaker == state.get(
                    "target_audience_speaker"):
            handle_barge_in(
                encounter_id=encounter_id,
                interrupting_speaker=speaker,
                in_flight_translation=state.get(
                    "in_flight_translation", {}))
            transition_to_state(
                encounter_id, "speaker_active",
                active_speaker=speaker)
    elif event_type == "speech_end":
        # Speaker finished; ASR path will finalize the
        # transcript segment.
        transition_to_state(
            encounter_id, "translating",
            translating_for_speaker=speaker)
    elif event_type == "silence":
        # Long-silence-driven idle reset is handled by the
        # caller; this branch records the silence event.
        pass

    event_bus.put_events([{
        "Source":       "medical_interpretation",
        "DetailType":   "conversational_state",
        "EventBusName": EVENT_BUS_NAME,
        "Detail": json.dumps({
            "encounter_id":    encounter_id,
            "previous_state":  current_state,
            "new_state":
                get_current_state(encounter_id),
            "event":           event_type,
            "speaker":         speaker,
        }),
    }])
```

---

## Step 6: Escalate to a Human Interpreter on Confidence-Below-Threshold or Topic-Requires-Human

*The pseudocode calls this `escalate_to_human(...)` (a fuller version than the placeholder used in Step 3). The escalation pathway connects to the institutional human-interpreter pool, briefs the interpreter on conversational context with appropriate confidentiality scoping, transfers audio routing to the interpreter, and logs the escalation reason and timing for audit. Skip the seamless handoff and the conversation breaks awkwardly when the machine fails; skip the confidentiality scoping and the interpreter receives more context than they should.*

```python
def determine_interpreter_pool(language, dialect,
                                   encounter_type,
                                   pre_staged_session):
    """Identify the appropriate interpreter pool. Production
    routes to the institutional pool first, then to the
    contracted vendor's pool by language and urgency. The
    demo just notes whether a pre-staged session exists."""
    return {
        "language":         language,
        "dialect":          dialect,
        "encounter_type":   encounter_type,
        "has_pre_staged":   pre_staged_session is not None,
    }


def determine_urgency(topic_category, reason):
    """Pick the urgency tier for on-demand dispatch."""
    if topic_category in (
            "mental_health_crisis", "safety_critical",
            "end_of_life") or reason in (
            "number_mismatch",
            "faithfulness_below_threshold"):
        return "urgent"
    return "standard"


def get_recent_utterances(encounter_id,
                              max_briefing_utterances=5):
    """Pull the recent conversational context for the
    interpreter briefing, with confidentiality scoping
    applied at the briefing-builder layer."""
    audit_records = audit_table.query_by_encounter(
        encounter_id)
    audit_records.sort(
        key=lambda r: r.get("timestamp", ""),
        reverse=True)
    return audit_records[:max_briefing_utterances]


def determine_confidentiality_scope(state):
    """Decide what context the interpreter is allowed to
    receive based on the topic category. Production applies
    a per-topic confidentiality matrix; the demo uses a
    coarse mapping."""
    topic = state.get("topic_category", "routine_clinical")
    if topic in ("mental_health_crisis",
                  "intimate_partner_violence",
                  "substance_use", "sexual_health"):
        return "minimal_briefing"
    return "recent_utterances_only"


def build_interpreter_briefing(recent_utterances,
                                    confidentiality_scope,
                                    topic_category):
    """Assemble the briefing for the interpreter. Production
    redacts content per the confidentiality scope; the demo
    returns a minimal briefing referring to the audit
    records by hash."""
    return {
        "topic_category":          topic_category,
        "confidentiality_scope":   confidentiality_scope,
        "utterance_references": [
            {"utterance_id":
                  u.get("utterance_id"),
             "speaker":   u.get("speaker"),
             "timestamp": u.get("timestamp")}
            for u in recent_utterances
        ],
    }


def transfer_audio_routing(encounter_id, from_mode, to_mode,
                                interpreter_session):
    """Transfer audio routing from machine mode to human-
    interpreter mode."""
    state = encounter_table.get(encounter_id)
    if state.get("encounter_type", "").startswith(
            "telephonic"):
        connect_mock.transfer_audio(
            contact_id=state.get(
                "contact_id", encounter_id),
            from_mode=from_mode,
            to_mode=to_mode,
            target_session=interpreter_session.get(
                "session_id"))
    else:
        chime_mock.transfer_audio(
            meeting_id=state.get(
                "meeting_id", encounter_id),
            from_mode=from_mode,
            to_mode=to_mode,
            target_session=interpreter_session.get(
                "session_id"))


def execute_escalation(encounter_id, reason, segment,
                            additional_context=None):
    """
    Full implementation of the escalation pathway. Connects
    to the interpreter pool, briefs the interpreter with
    confidentiality scoping, transfers audio routing, and
    logs the escalation event.
    """
    state = encounter_table.get(encounter_id)

    # Step 6A: identify the interpreter pool.
    determine_interpreter_pool(
        language=state.get("declared_language"),
        dialect=state.get("declared_dialect"),
        encounter_type=state.get("encounter_type"),
        pre_staged_session=state.get(
            "human_standby_session"))

    # Step 6B: connect to the interpreter.
    standby = state.get("human_standby_session")
    if standby:
        interpreter_session = standby
        # Production: promote the standby session to active
        # via the pool's API.
    else:
        interpreter_session = (
            interpreter_pool.dispatch_on_demand(
                language=state.get("declared_language"),
                dialect=state.get("declared_dialect"),
                encounter_type=state.get(
                    "encounter_type"),
                urgency=determine_urgency(
                    state.get("topic_category"),
                    reason)))

    # Step 6C: brief the interpreter with confidentiality
    # scoping.
    context_briefing = build_interpreter_briefing(
        recent_utterances=get_recent_utterances(
            encounter_id, 5),
        confidentiality_scope=
            determine_confidentiality_scope(state),
        topic_category=state.get("topic_category"))
    interpreter_pool.deliver_briefing(
        interpreter_session.get("session_id"),
        context_briefing)

    # Step 6D: transfer audio routing.
    transfer_audio_routing(
        encounter_id=encounter_id,
        from_mode="machine",
        to_mode="human_interpreter",
        interpreter_session=interpreter_session)

    # Step 6E: log escalation.
    escalation_event = _to_decimal({
        "encounter_id":   encounter_id,
        "event_type":     "human_escalation",
        "timestamp":      _now_iso(),
        "reason":         reason,
        "segment_at_escalation":
            (segment or {}).get("utterance_id"),
        "interpreter_session_id":
            interpreter_session.get("session_id"),
        "wait_time_ms":   0,
        "additional_context":
            additional_context or {},
    })
    audit_table.put(escalation_event)

    event_bus.put_events([{
        "Source":       "medical_interpretation",
        "DetailType":   "human_escalation",
        "EventBusName": EVENT_BUS_NAME,
        "Detail": json.dumps({
            "encounter_id":  encounter_id,
            "reason":        reason,
            "language_pair":
                state.get(
                    "language_pair_patient_to_clinician"),
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "HumanEscalations", 1,
        "Count",
        dimensions={
            "reason":  reason,
            "posture":
                state.get(
                    "deployment_posture", "unknown"),
            "language_pair":
                state.get(
                    "language_pair_patient_to_clinician",
                    "unknown"),
        })

    encounter_table.update(encounter_id, {
        "current_mode":            "human_interpreter",
        "last_escalation_reason":  reason,
        "last_escalation_at":      _now_iso(),
    })

    audit_log({
        "event_type":      "HUMAN_ESCALATION_COMPLETE",
        "encounter_id":    encounter_id,
        "reason":          reason,
        "interpreter_session_id":
            interpreter_session.get("session_id"),
        "timestamp":       _now_iso(),
    })

    return {
        "escalation_complete":   True,
        "interpreter_session":   interpreter_session,
    }
```

---

## Step 7: Close the Encounter, Retain Audio per Consent, and Update Quality Monitoring

*The pseudocode calls this `ON encounter_ended(...)`. When the encounter ends, the system writes the durable audit record (encounter metadata, per-utterance confidence distributions, escalation events, satisfaction signals where captured), schedules audio deletion per consent terms, and feeds the per-pair quality monitoring pipeline with this encounter's data. Skip the audit record and the institution loses the language-access compliance evidence; skip the quality monitoring update and per-pair regression goes undetected.*

```python
def lookup_audio_retention(consent_id, deployment_context):
    """Look up the audio retention window from the consent
    record. Production reads from the consent management
    system; the demo uses a default of 7 days for QA."""
    return {"days": 7}


def get_audio_refs_for_encounter(encounter_id):
    """Return the audio references captured during the
    encounter."""
    state = encounter_table.get(encounter_id)
    refs = []
    if state.get("patient_audio_ref"):
        refs.append(state["patient_audio_ref"])
    if state.get("clinician_audio_ref"):
        refs.append(state["clinician_audio_ref"])
    return refs


def schedule_audio_deletion(audio_refs, delete_after):
    """Schedule audio deletion per consent terms. Production
    uses S3 lifecycle keyed on object tags; the demo logs
    and removes the mock objects."""
    for audio_ref in audio_refs:
        audit_log({
            "event_type":     "AUDIO_DELETION_SCHEDULED",
            "audio_ref_hash": _hash_value(audio_ref),
            "delete_after_days":
                delete_after.get("days"),
            "timestamp":      _now_iso(),
        })


def compute_confidence_distribution(encounter_id):
    """Aggregate per-utterance confidence into a percentile
    distribution for the audit record."""
    records = audit_table.query_by_encounter(encounter_id)
    confidences = [
        Decimal(str(r.get("translation_confidence", 0)))
        for r in records
        if r.get("translation_confidence") is not None
    ]
    if not confidences:
        return {"count": 0}
    confidences.sort()
    n = len(confidences)
    def pct(p):
        idx = max(0, min(n - 1, int(p * n)))
        return confidences[idx]
    return {
        "count":  n,
        "p50":    pct(0.50),
        "p10":    pct(0.10),
        "min":    confidences[0],
        "max":    confidences[-1],
    }


def list_escalation_events(encounter_id):
    """Pull the escalation events for the encounter from the
    audit table."""
    records = audit_table.query_by_encounter(encounter_id)
    return [
        {
            "utterance_id":   r.get("utterance_id"),
            "timestamp":      r.get("timestamp"),
            "reason":         r.get("escalation_reason"),
        }
        for r in records
        if r.get("escalation_triggered")
    ]


def list_modes_used(encounter_id):
    """Track which interpretation modes were used during the
    encounter (machine_only, machine_with_human_standby,
    human_interpreter)."""
    state = encounter_table.get(encounter_id)
    modes = ["machine"]
    if state.get("current_mode") == "human_interpreter":
        modes.append("human_interpreter")
    return modes


def count_utterances(encounter_id):
    return len(audit_table.query_by_encounter(encounter_id))


def compute_latency_distribution(encounter_id):
    """Compute end-to-end latency percentiles. Production
    pulls from the CloudWatch metrics stream; the demo uses
    the metrics list directly."""
    relevant = [
        m for m in cloudwatch.metrics
        if m.get("metric_name") == "EndToEndLatencyMs"
        and m.get("dimensions", {}).get(
            "language_pair") is not None
    ]
    if not relevant:
        return {"count": 0}
    values = sorted(int(m.get("value", 0))
                       for m in relevant)
    n = len(values)
    def pct(p):
        idx = max(0, min(n - 1, int(p * n)))
        return values[idx]
    return {
        "count": n,
        "p50_ms": pct(0.5),
        "p95_ms": pct(0.95),
        "max_ms": values[-1],
    }


def encounter_ended(encounter_id, end_reason):
    """
    Aggregate the encounter audit, schedule audio deletion,
    emit per-pair operational metrics, and persist the
    encounter-level audit record.
    """
    state = encounter_table.get(encounter_id)

    # Step 7A: aggregate the encounter-level audit summary.
    encounter_audit = _to_decimal({
        "encounter_id":         encounter_id,
        "patient_id_hash":
            state.get("patient_id_hash"),
        "clinician_id":
            state.get("clinician_id"),
        "language_pair":
            state.get(
                "language_pair_patient_to_clinician"),
        "declared_language":
            state.get("declared_language"),
        "declared_dialect":
            state.get("declared_dialect"),
        "encounter_type":
            state.get("encounter_type"),
        "topic_category":
            state.get("topic_category"),
        "deployment_posture":
            state.get("deployment_posture"),
        "consent_id":
            state.get("consent_id"),
        "started_at":
            state.get("started_at"),
        "ended_at":             _now_iso(),
        "end_reason":           end_reason,
        "utterance_count":
            count_utterances(encounter_id),
        "per_utterance_confidence_distribution":
            compute_confidence_distribution(encounter_id),
        "end_to_end_latency_distribution":
            compute_latency_distribution(encounter_id),
        "escalation_events":
            list_escalation_events(encounter_id),
        "modes_used":           list_modes_used(
            encounter_id),
        "model_versions": {
            "asr_pipeline":
                state.get("asr_pipeline_version"),
            "mt_pipeline":
                state.get("mt_pipeline_version"),
            "tts_pipeline":
                state.get("tts_pipeline_version"),
            "translation_prompt":
                TRANSLATION_PROMPT_VERSION,
            "faithfulness_prompt":
                FAITHFULNESS_PROMPT_VERSION,
        },
    })

    # Persist the audit record to the audit archive.
    audit_archive_object = s3_store.put_object(
        bucket=AUDIT_ARCHIVE_BUCKET,
        key=(f"audit/"
             f"{datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
             f"/{encounter_id}.json"),
        body=json.dumps(encounter_audit,
                          default=str).encode("utf-8"),
        metadata={"encounter_id": encounter_id})

    # Step 7B: schedule audio deletion per consent terms.
    audio_refs = get_audio_refs_for_encounter(encounter_id)
    if audio_refs:
        schedule_audio_deletion(
            audio_refs=audio_refs,
            delete_after=lookup_audio_retention(
                consent_id=state.get("consent_id"),
                deployment_context=state.get(
                    "encounter_type")))

    # Step 7C: per-pair quality metrics emission.
    utterance_count = encounter_audit.get(
        "utterance_count", 1) or 1
    escalation_count = len(
        encounter_audit.get("escalation_events", []) or [])
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "EscalationRate",
        Decimal(str(escalation_count))
            / Decimal(str(max(utterance_count, 1))),
        "None",
        dimensions={
            "language_pair":
                encounter_audit.get(
                    "language_pair", "unknown"),
            "posture":
                encounter_audit.get(
                    "deployment_posture", "unknown"),
            "topic_category":
                encounter_audit.get(
                    "topic_category", "unknown"),
        })

    latency_dist = encounter_audit.get(
        "end_to_end_latency_distribution", {})
    if latency_dist.get("count"):
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "P95LatencyMs",
            int(latency_dist.get("p95_ms", 0)),
            "Milliseconds",
            dimensions={
                "language_pair":
                    encounter_audit.get(
                        "language_pair", "unknown"),
            })

    # Step 7D: emit the encounter-ended event for the
    # per-pair quality monitoring pipeline to consume.
    event_bus.put_events([{
        "Source":       "medical_interpretation",
        "DetailType":   "encounter_ended",
        "EventBusName": EVENT_BUS_NAME,
        "Detail": json.dumps({
            "encounter_id":      encounter_id,
            "language_pair":
                encounter_audit.get("language_pair"),
            "audit_archive_ref":
                audit_archive_object["uri"],
        }),
    }])

    encounter_table.update(encounter_id, _to_decimal({
        "ended_at":           _now_iso(),
        "end_reason":         end_reason,
        "audit_archive_ref":
            audit_archive_object["uri"],
        "status":             "ended",
    }))

    audit_log({
        "event_type":          "ENCOUNTER_ENDED",
        "encounter_id":        encounter_id,
        "end_reason":          end_reason,
        "utterance_count":
            encounter_audit.get("utterance_count"),
        "escalation_count":    escalation_count,
        "audit_archive_ref":
            audit_archive_object["uri"],
        "timestamp":           _now_iso(),
    })

    return encounter_audit
```

---

## Putting It All Together

The pipeline ties together as a top-level handler that simulates a single end-to-end medical-interpretation encounter flowing through the seven stages. In a Lambda-and-Step-Functions deployment, the session-setup stage runs in response to the encounter-initiation event from the contact center or the telehealth platform, the audio-routing stage runs in response to the audio-streaming event, and the per-utterance translation stages run as the streaming ASR emits finalized segments; the demo orchestrates them inline so you can see the full sequence.

```python
def run_interpretation_encounter(clinician_id, patient_id,
                                       declared_language,
                                       declared_dialect,
                                       encounter_type,
                                       topic_category,
                                       conversation_segments,
                                       encounter_id_hint=None):
    """
    Drive a single medical-interpretation encounter end-to-
    end. conversation_segments is a list of (speaker,
    segment_dict) tuples ordered by timestamp. Production
    would receive segments asynchronously through Transcribe
    streaming and route them as they arrive; the demo
    iterates them in order.
    """
    # Stage 1: encounter setup.
    setup_result = encounter_initiated(
        clinician_id=clinician_id,
        patient_id=patient_id,
        declared_language=declared_language,
        declared_dialect=declared_dialect,
        encounter_type=encounter_type,
        topic_category=topic_category,
        encounter_id_hint=encounter_id_hint)
    if setup_result["status"] != "READY_FOR_AUDIO":
        return {
            "status":   setup_result["status"],
            "stage":    "setup",
            "handoff":  setup_result.get("handoff"),
        }

    encounter_id = setup_result["encounter_id"]

    # Stage 2: audio capture and ASR routing.
    patient_audio_stream = {
        "audio_ref":
            f"s3://{AUDIO_BUCKET}/{encounter_id}/patient.ogg",
        "snr_db":      Decimal("24.0"),
        "sample_rate": 16000,
    }
    clinician_audio_stream = {
        "audio_ref":
            f"s3://{AUDIO_BUCKET}/{encounter_id}/clinician.ogg",
        "snr_db":      Decimal("28.0"),
        "sample_rate": 16000,
    }
    route_audio_to_asr(
        encounter_id=encounter_id,
        patient_audio_stream=patient_audio_stream,
        clinician_audio_stream=clinician_audio_stream)

    # Stages 3-6: per-utterance translation flow with
    # turn-taking events. Production drives this off the
    # async ASR stream; the demo iterates a pre-defined
    # conversation list.
    translated_results = []
    for speaker, segment in conversation_segments:
        # Speech-start VAD event.
        vad_event(encounter_id, speaker, "speech_start")
        # Speech-end VAD event triggers ASR finalization.
        vad_event(encounter_id, speaker, "speech_end")

        translation_result = asr_finalized_transcript(
            encounter_id=encounter_id,
            speaker=speaker,
            segment=segment)
        translated_results.append(translation_result)

        if translation_result.get("escalated"):
            # Trigger the full escalation pathway. After
            # escalation completes, subsequent utterances
            # in this demo continue through the machine
            # path; production would route them to the
            # human interpreter.
            execute_escalation(
                encounter_id=encounter_id,
                reason=translation_result.get(
                    "escalation_reason"),
                segment=segment,
                additional_context={
                    "translation_confidence":
                        str(translation_result.get(
                            "translation_confidence",
                            0)),
                })
        elif translation_result.get("translated_text"):
            # Stage 4: synthesize and stream the audio.
            synthesize_translated_audio(
                encounter_id=encounter_id,
                translated_text=translation_result[
                    "translated_text"],
                target_language=(
                    "en-US" if speaker == "patient"
                    else declared_language),
                target_audience=translation_result.get(
                    "target_audience"),
                source_timestamp_ms=segment.get(
                    "start_timestamp_ms"))

    # Stage 7: encounter close.
    audit_record = encounter_ended(
        encounter_id=encounter_id,
        end_reason="completed_normally")

    return {
        "status":            "COMPLETE",
        "encounter_id":      encounter_id,
        "setup_result":      setup_result,
        "translated_results":
            translated_results,
        "audit_record":      audit_record,
    }
```

The demo runner wires up the mocks with fixture data for one end-to-end scenario.

```python
def run_demo():
    """
    Run a single end-to-end scenario that exercises the
    main paths through the medical-interpretation pipeline:

      Elena (64-year-old Mexican Spanish speaker, outpatient
      follow-up for hypertension) is in the clinic with her
      bilingual son. The encounter is routine_clinical with
      machine_with_human_standby posture. Most of the
      conversation translates cleanly. One utterance involves
      a dosing change ("take 25 mg twice a day") where a
      number-mismatch is simulated to demonstrate the hard-
      gate escalation. One utterance has low translation
      confidence to demonstrate the confidence-based
      escalation.
    """
    # pylint: disable=global-statement
    global transcribe_mock, translate_mock, bedrock_mock

    encounter_id_demo = "mi-demo-elena-2026-05-23"

    # Per-utterance ASR fixtures keyed by audio_ref.
    transcribe_mock = MockTranscribeStreaming({
        # Production drives this off the live audio stream;
        # the demo does not actually stream audio so the
        # fixtures are not exercised in this run.
        f"s3://{AUDIO_BUCKET}/{encounter_id_demo}/patient.ogg":
            [],
        f"s3://{AUDIO_BUCKET}/{encounter_id_demo}/clinician.ogg":
            [],
    })

    # Translation fixtures for the routine, clean path.
    translate_mock = MockTranslate({
        ("Buenos dias doctora, hoy me siento un poco "
         "mareada por la manana.",
         "es-MX", "en-US"): {
            "translated_text":
                "Good morning doctor, today I feel a "
                "little dizzy in the morning.",
            "applied_terminologies": ["medical-es-en-v8"],
            "confidence": Decimal("0.92"),
        },
        ("How often is the dizziness happening?",
         "en-US", "es-MX"): {
            "translated_text":
                "Con que frecuencia esta ocurriendo el "
                "mareo?",
            "applied_terminologies": ["medical-en-es-v8"],
            "confidence": Decimal("0.91"),
        },
        ("Pasa casi cada manana cuando me levanto de la "
         "cama.",
         "es-MX", "en-US"): {
            "translated_text":
                "It happens almost every morning when I "
                "get out of bed.",
            "applied_terminologies": ["medical-es-en-v8"],
            "confidence": Decimal("0.89"),
        },
        # The dosing-change utterance: clinician says
        # "take 25 mg twice a day" but the simulated
        # translation comes back with "250 mg" instead.
        # The number-and-unit verifier catches the mismatch
        # and routes to human escalation.
        ("Take 25 mg twice a day starting tomorrow.",
         "en-US", "es-MX"): {
            "translated_text":
                "Tome 250 mg dos veces al dia "
                "comenzando manana.",
            "applied_terminologies": ["medical-en-es-v8"],
            "confidence": Decimal("0.86"),
        },
        # A low-confidence utterance to demonstrate the
        # confidence-based escalation.
        ("Tengo dolor en el pecho como una opresion.",
         "es-MX", "en-US"): {
            "translated_text":
                "I have chest pain like a tightness.",
            "applied_terminologies": ["medical-es-en-v8"],
            "confidence": Decimal("0.62"),
        },
        # A normal closing utterance.
        ("See you in three months for follow-up.",
         "en-US", "es-MX"): {
            "translated_text":
                "Nos vemos en tres meses para "
                "seguimiento.",
            "applied_terminologies": ["medical-en-es-v8"],
            "confidence": Decimal("0.93"),
        },
    })

    bedrock_mock = MockBedrock(
        translation_responses={},
        faithfulness_responses={})

    # The ordered conversation. Each utterance has a stable
    # utterance_id, a per-word confidence floor, and a
    # source-side timestamp the demo uses for latency math.
    base_ms = int(datetime.now(timezone.utc).timestamp()
                    * 1000)
    conversation = [
        ("patient", {
            "utterance_id":   "u-001",
            "transcript_text":
                "Buenos dias doctora, hoy me siento un "
                "poco mareada por la manana.",
            "per_word_confidence_min": Decimal("0.88"),
            "timestamp":      _now_iso(),
            "start_timestamp_ms":  base_ms - 1500,
        }),
        ("clinician", {
            "utterance_id":   "u-002",
            "transcript_text":
                "How often is the dizziness happening?",
            "per_word_confidence_min": Decimal("0.94"),
            "timestamp":      _now_iso(),
            "start_timestamp_ms":  base_ms - 1300,
        }),
        ("patient", {
            "utterance_id":   "u-003",
            "transcript_text":
                "Pasa casi cada manana cuando me "
                "levanto de la cama.",
            "per_word_confidence_min": Decimal("0.85"),
            "timestamp":      _now_iso(),
            "start_timestamp_ms":  base_ms - 1100,
        }),
        # The dosing change: number-mismatch escalation.
        ("clinician", {
            "utterance_id":   "u-004",
            "transcript_text":
                "Take 25 mg twice a day starting "
                "tomorrow.",
            "per_word_confidence_min": Decimal("0.93"),
            "timestamp":      _now_iso(),
            "start_timestamp_ms":  base_ms - 900,
        }),
        # The low-confidence utterance.
        ("patient", {
            "utterance_id":   "u-005",
            "transcript_text":
                "Tengo dolor en el pecho como una "
                "opresion.",
            "per_word_confidence_min": Decimal("0.78"),
            "timestamp":      _now_iso(),
            "start_timestamp_ms":  base_ms - 700,
        }),
        # Resume on the machine path for the closing.
        ("clinician", {
            "utterance_id":   "u-006",
            "transcript_text":
                "See you in three months for follow-up.",
            "per_word_confidence_min": Decimal("0.95"),
            "timestamp":      _now_iso(),
            "start_timestamp_ms":  base_ms - 500,
        }),
    ]

    print("\n=== Medical Interpretation Pipeline Demo ===\n")
    result = run_interpretation_encounter(
        clinician_id="clinician_dr_patel",
        patient_id="pt-elena-9c1b",
        declared_language="es-MX",
        declared_dialect="Mexican Spanish",
        encounter_type="outpatient_routine_followup",
        topic_category="routine_clinical",
        conversation_segments=conversation,
        encounter_id_hint=encounter_id_demo)

    # Summarize the demo run for visibility.
    audit = result.get("audit_record", {})
    summary = {
        "status":          result.get("status"),
        "encounter_id":
            result.get("encounter_id"),
        "language_pair":
            audit.get("language_pair"),
        "posture":
            audit.get("deployment_posture"),
        "utterance_count":
            audit.get("utterance_count"),
        "escalation_count":
            len(audit.get("escalation_events", []) or []),
        "modes_used":
            audit.get("modes_used"),
        "audit_archive_ref":
            (encounter_table.get(
                result.get("encounter_id")) or {}).get(
                "audit_archive_ref"),
    }
    print(json.dumps(summary, default=str, indent=2))


if __name__ == "__main__":
    run_demo()
```

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right audit records, but the distance between it and a real medical-interpretation pipeline running in patient encounters is significant. Here is where that distance lives.

**Real audio capture from a clinic microphone, telephony line, or telehealth platform.** The demo's audio refs are S3 placeholders. Production captures audio from a clinic-grade microphone with known frequency response, an Amazon Connect SIP integration for telephonic encounters with the institution's contact-center routing, or an Amazon Chime SDK WebRTC session for telehealth with per-participant audio channels. Each capture surface has its own per-context validation work; the per-deployment-context configuration is part of the architectural pattern.

**Real Transcribe and Transcribe Medical streaming sessions.** The demo's `MockTranscribeStreaming` returns canned segments. Production opens a real WebSocket session to Transcribe (or Transcribe Medical for English) per audio direction, with the appropriate language code, custom-vocabulary configuration, and partial-results-stability setting. The session emits partial transcripts as audio comes in, with the partial results being revised as more audio is heard; the system consumes the stable-partial results once end-of-utterance is detected. Per-language ASR coverage is uneven; for languages without adequate Transcribe coverage, production routes through a third-party streaming-ASR vendor with the same audit and quality scaffolding.

**Real Amazon Translate invocation with Custom Terminology and Active Custom Translation.** The demo's `MockTranslate` looks up canned responses. Production calls `translate_client.translate_text` with `SourceLanguageCode`, `TargetLanguageCode`, and `TerminologyNames` referencing the institution's medical-domain custom-terminology resources. Custom Terminology is a per-pair resource that the institutional language-access program curates and maintains; Active Custom Translation extends this with parallel medical-corpus fine-tuning. Building and maintaining these assets is a multi-month workstream per pair, with ongoing updates as institutional vocabulary evolves.

**Real Bedrock invocation, prompt management, and Guardrails configuration.** The demo's `MockBedrock` uses fixture lookups. Production calls `bedrock_runtime.invoke_model` with `modelId=BEDROCK_TRANSLATION_PROFILE_ARN` and a structured `body` containing the system prompt (versioned, owned by clinical operations and the language-access program), a `tools` field that declares the structured-output schema as a tool definition, and the user message containing the source-language text wrapped in a delimited untrusted-input envelope. The `guardrailIdentifier` and `guardrailVersion` parameters apply the runtime Guardrails policy, including content filtering on the patient-facing translation, prompt-injection mitigation that treats the source content as content to translate rather than instructions, and contextual-grounding checks that verify the translation does not invent content beyond the source.

**Real Polly streaming synthesis.** The demo's `MockPolly` records the invocation and returns a placeholder audio reference. Production calls `polly_client.synthesize_speech` with `OutputFormat="ogg_vorbis"` (or the format the playback path expects), `Engine="neural"` or `"generative"`, the appropriate `VoiceId` per target language, `LexiconNames=lexicon_ids` for institution-specific pronunciation, and `TextType="ssml"` for fine-grained pronunciation control. The synthesized audio bytes stream back to the caller, which forwards them to the audio path (Connect for telephonic, Chime SDK for in-person and telehealth) for playback. The streaming approach is essential for hitting the time-to-first-audio latency target.

**Real Connect and Chime SDK wiring.** The demo's `MockConnect` and `MockChimeSDK` log the operations. Production integrates Amazon Connect for the telephonic-mode contact center (SIP, call routing, queue management, audio path between the patient phone and the cloud, integration with the institutional contact-center workforce-management system) and the Chime SDK for in-person and telehealth WebRTC sessions (per-participant audio channel separation, video for telehealth, integration with the institutional telehealth platform). The institutional integration work is real but tractable; AWS provides reference architectures for both.

**Number-and-unit verification beyond regex.** The demo's `verify_numerical_content` uses a simple digit-and-unit regex with a small unit-equivalence map. Production uses a per-language number-and-unit grammar that handles spelled-out numbers ("twenty-five milligrams" -> 25 mg), localized unit expressions, fraction handling, drug-dose patterns ("one tablet three times a day"), allowable conversions ("1500 mg" matches "1.5 g" within tolerance), and date and time expressions. The grammar is per-language and per-medication-domain; building it is real work and requires native-speaker review per language.

**Faithfulness verifier with structured-output validation and citation grounding.** The demo's `check_faithfulness` returns a fixture score. Production uses a separate Bedrock model (different from the translation model) with a structured-output schema that requires the verifier to enumerate (a) any content in the target that does not appear in the source, (b) any content in the source that does not appear in the target, (c) any contradictions between source and target, and (d) any cultural-framing or idiomatic-content concerns. The verifier output is parsed against the schema; failures route to escalation. The verifier model and prompt are versioned and validated against a curated medical-content evaluation set.

**Per-pair quality monitoring with launch gates and disparity detection.** The demo emits CloudWatch metrics but does not implement the per-pair quality monitoring pipeline. Production runs continuous monitoring against a curated medical-content evaluation set per pair: BLEU or COMET against reference translations, per-segment quality estimation, bidirectional tracking, and per-population disparity detection (per-age, per-dialect, per-clinical-content-category). Per-pair launch gates and ongoing-operation thresholds are defined; pairs that miss the threshold either get a different vendor, fall back to human-only, or get deployed only in low-stakes flows. Vendor-update regression detection compares pre-update and post-update accuracy on the same evaluation set.

**Per-Lambda IAM roles.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda (session-setup, audio-router, translation-and-verification, TTS-and-delivery, turn-taking-state-machine, escalation, audit), each scoped to the specific resource ARNs the Lambda touches. The translation Lambda has scoped Translate, Bedrock invoke-model, and Bedrock apply-guardrail rights pinned to the validated translation models and Guardrails configurations only. Wildcard actions and resources will fail any serious IAM review.

**Real DynamoDB wiring with KMS and PITR.** The mocks in the demo are dictionaries; production is DynamoDB tables (encounters partitioned by encounter-id with TTL on idle sessions, audit partitioned by encounter-id with sort key on utterance-timestamp, language-pair-config partitioned by pair-id with sort key on version) with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery enabled, and DynamoDB Streams emitting change events to the audit and analytics consumers.

**Customer-managed KMS keys, per data class.** Every PHI-bearing and biometric-bearing resource (audio bucket, transcript and translation archive, audit archive, all DynamoDB tables, Lambda environment variables, CloudWatch Logs, Secrets Manager) uses customer-managed KMS keys with rotation enabled. Different keys per data class for blast-radius containment: a compromised audio-bucket key does not compromise the audit archive. Voice samples and any biometric voiceprint storage (if used for clinician enrollment) use separate keys because their retention and governance differ from transcript content.

**S3 lifecycle and Object Lock.** The audio bucket has a brief-retention lifecycle bound to consent terms (often hours to a few days for QA, optionally longer with explicit consent for model improvement). The transcript and translation archive retains aligned with medical-record retention. The audit archive uses Object Lock in compliance mode with retention sized to the longer of HIPAA's six-year minimum, biometric-data law retention requirements, state medical-records-retention rules, and the institutional regulatory floor. Lifecycle transitions move older audit-archive objects to S3 Glacier Deep Archive for cost optimization.

**VPC and VPC endpoints.** Lambdas that call back-office APIs (institutional contact-center systems, EHR write-back of interpretation events, language-access program platform, human-interpreter pool integration) run in a VPC with private subnets that route traffic through a controlled egress path. VPC endpoints for S3, DynamoDB, KMS, Secrets Manager, EventBridge, CloudWatch Logs, Transcribe, Translate, Bedrock, Polly, Connect, and Chime SDK keep AWS-internal traffic on the AWS backbone. Endpoint policies pin access to the specific resources the pipeline uses.

**Step Functions orchestration of the encounter lifecycle and human-interpreter handoff.** The demo orchestrates the encounter inline. Production runs the encounter lifecycle as an AWS Step Functions state machine with explicit states for setup, asr-streaming, per-utterance-translation (with Map-state fan-out across utterances), human-interpreter-handoff (with `waitForTaskToken` for the interpreter pool integration), encounter-close, and audit-and-archival. Step Functions provides durable retry semantics: if Translate throttles, retry with exponential backoff; if Bedrock fails on an LLM-translation segment, fall back to Translate and flag for review; if the human-interpreter handoff fails, route to a backup pool with audit logging.

**Real human-interpreter pool integration.** The demo's `MockHumanInterpreterPool` is a placeholder. Production integrates with the institutional human-interpreter program or the contracted vendor's pool (LanguageLine, Stratus, Globo, and others) over the vendor's API, with routing by language and dialect, urgency-aware dispatch, conversational-context briefing with confidentiality scoping, audio path transfer through Connect or Chime SDK, billing reconciliation, and audit. The integration layer is substantial and is one of the most under-invested areas in actual deployments.

**Native-speaker-validated consent disclosures per language.** The demo's consent disclosure is in English and Spanish only, with TODO comments noting that production needs native-speaker validation. Production maintains the consent disclosure per language with attention to literacy level and cultural framing, validated by native speakers, with regular review based on patient feedback. The consent flow validation is a launch gate per language.

**Biometric-data deletion-on-request workflow.** The demo's `schedule_audio_deletion` deletes the audio object. Production maintains a biometric-data deletion-on-request workflow that handles audio, transcript hashes, and audit records per the patient's (or guardian's, where applicable) request, while preserving the audit obligations that override deletion (HIPAA records-retention floor, regulatory inquiries, ongoing legal proceedings). The workflow respects per-state biometric-data law disclosure-accounting requirements.

**Idempotency and retry semantics.** The demo's encounter-id is generated freshly each run. Production uses a conditional DynamoDB write keyed on `(clinician_id, patient_id_hash, encounter_initiation_timestamp)` so a duplicate encounter-initiation event is rejected with `ConditionalCheckFailedException` rather than producing two encounters. Per-utterance audit writes use an idempotency key built from `(encounter_id, utterance_id)`. Configure DLQs on every Lambda; alarm on DLQ depth.

**Performance under burst load and latency budget enforcement.** Real-time medical interpretation has tight per-utterance latency budgets (1.5 to 3 seconds end-to-end). The demo runs a single encounter at a time. Production holds the latency budget under burst: Transcribe streaming session quotas, Translate request rate limits, Bedrock model invocation quotas, Polly synthesize-speech quotas. Reserve concurrency on the latency-critical Lambdas; load test against realistic peak profiles before launch. CloudWatch alarms on latency-budget overruns trigger automatic escalation to human interpretation within an encounter.

**Disaster recovery and degraded-mode operation.** The demo assumes happy-path execution. Production tests the failure modes in staging quarterly: Transcribe unavailable (route to backup ASR vendor), Translate unavailable (fall back to Bedrock-only translation with the same number-and-unit verification), Bedrock unavailable (route hybrid-pair traffic to Translate-only with conservative confidence thresholds), Polly unavailable (route to backup TTS vendor), Connect or Chime SDK unavailable (escalate the encounter to the institutional language-access program for manual interpretation routing), interpreter-pool API unreachable (queue the escalation request and alert the language-access program). The system is patient-and-clinician-facing; its absence does not block clinical care but the institution must have a defined fallback procedure.

**Audit log retention with regulatory-aware lifecycle.** The demo's audit-archive S3 bucket is created without Object Lock in the mock. Production enables Object Lock in compliance mode with retention sized per HIPAA, biometric-data law, state medical-records-retention rules, and pediatric-extending-to-age-of-majority where applicable. Legal hold capabilities are configurable.

**Per-pair, per-population, and per-deployment-context cost monitoring.** Different language pairs, different deployment contexts, and different content categories have very different per-encounter costs (a 30-minute telephonic encounter on English-Spanish with Translate-only routing is dramatically cheaper than a 30-minute in-person encounter on English-Vietnamese with hybrid Translate-and-Bedrock routing plus higher escalation rate). Per-pair, per-population, per-deployment-context cost dashboards let operations identify outliers and tune accordingly.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the language-pair lookup, unit tests for the deployment-posture mapping, unit tests for the number-and-unit verification across language pairs and unit categories, unit tests for the faithfulness check parsing, integration tests against test buckets and tables, and end-to-end tests that simulate full encounter flows including the not-validated-pair path, the consent-declined path, the human-only-required path, the number-mismatch escalation path, the faithfulness-failure escalation path, the confidence-below-threshold escalation path, the barge-in path, and the multi-language paths. Never use real patient voice samples in test fixtures; voice samples are biometric and PHI-bearing data with non-trivial governance implications. Use synthetic patients (Synthea-style) and TTS-generated audio in source and target languages, or use the public medical-translation parallel corpora under their license terms.

**Observability beyond the metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-stage investigation. Production runs CloudWatch Logs Insights queries that join across the session-setup logs, the audio-routing logs, the per-utterance translation-and-verification logs, the TTS-and-delivery logs, the escalation logs, and the audit logs by encounter_id. AWS X-Ray traces show the latency contribution of each stage. When a single encounter goes wrong (a sustained latency overrun, a per-pair confidence drop, a number-mismatch on content the model usually handles well), the on-call engineer needs to reconstruct the full trace in seconds.

**Language-access program integration.** The deployment is part of the institutional language-access program, not a stand-alone project. Production integrates the per-pair quality dashboards, the escalation analytics, the patient-experience feedback per language, and the cost analytics with the language-access program manager's tooling. The program manager owns the deployment posture per topic category, the per-pair launch gates, the human-interpreter staffing strategy, and the regulatory documentation; the technology team supports rather than replaces this ownership.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 10.10: Multilingual Real-Time Medical Interpretation](chapter10.10-multilingual-realtime-medical-interpretation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard. See [Recipe 10.7: Ambient Clinical Documentation](chapter10.07-ambient-clinical-documentation) for the per-speaker audio capture, diarization, and consent patterns that share the audio infrastructure foundation. See [Recipe 2.6: Clinical Note Summarization](chapter02.06-clinical-note-summarization) and [Recipe 2.10: Multi-Modal Clinical Reasoning](chapter02.10-multi-modal-clinical-reasoning) for the LLM faithfulness scaffolding that transfers directly to LLM-based translation.*
