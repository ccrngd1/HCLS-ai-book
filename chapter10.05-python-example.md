# Recipe 10.5: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 10.5. It shows one way you could translate the patient-facing voice assistant pipeline into working Python using boto3 against Amazon Connect, Amazon Lex V2, Amazon Bedrock (with Knowledge Bases and Guardrails), Amazon Comprehend Medical, Amazon Transcribe, Amazon Polly, AWS Lambda, AWS Step Functions, Amazon API Gateway, Amazon Cognito, Amazon Pinpoint, Amazon DynamoDB, Amazon S3, AWS KMS, AWS Secrets Manager, Amazon EventBridge, and Amazon CloudWatch. The demo uses a `MockLex` standing in for the conversational core, a `MockBedrock` standing in for LLM-driven intent fallback and RAG-grounded informational responses, a `MockBedrockKB` standing in for the institutional knowledge base, a `MockComprehendMedical` standing in for the coded clinical-entity extraction, a `MockPinpoint` standing in for OTP delivery, a `MockConnect` standing in for the contact-center transfer pathway, a `MockEHR` standing in for the appointment-lookup and refill-request integrations, a `MockPatientRegistry` for caller-ID and DOB matching, and small helpers for the conversation-state table, the identity-verification table, the conversation-metadata table, the audio S3 bucket, the audit S3 bucket, the EventBridge bus, and CloudWatch-style metrics. It is not production-ready. There is no real Amazon Connect contact flow carrying audio frames, no real Lex bot configured with intents and slots, no real OTP SMS delivery, no real Bedrock invocation, no real Comprehend Medical inference, no real DynamoDB or S3 wiring, no Step Functions state machine, no IAM least-privilege role per Lambda, no KMS customer-managed key configuration, no VPC endpoints, no per-cohort accuracy disparity alerting, no smart-speaker or app channel, and no production warm-handoff screen-pop integration with the contact-center agent desktop. Think of it as the sketchpad version: useful for understanding the shape of a patient-facing voice pipeline that respects the recording-consent discipline, the parallel crisis-detection discipline, the layered identity-verification discipline, the scope-containment discipline, the warm-handoff discipline, and the cohort-stratified audit discipline this recipe demands. It is not something you would deploy to patients on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the eight core pseudocode steps from the main recipe: receive the channel entry and play the recording-consent disclosure (Step 1), stream audio to ASR and run the parallel crisis detector (Step 2), classify the intent and extract slots (Step 3), verify identity at the assurance level the intent requires (Step 4), fulfill the intent through the appropriate integration (Step 5), generate the response and render it through TTS (Step 6), escalate with a warm-handoff packet when needed (Step 7), and audit, archive, and feed cohort-stratified accuracy monitoring (Step 8). The synthetic patients, providers, appointments, medications, and dictated transcripts in the demo are fictional; the names, MRNs, RxNorm codes, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also configure an Amazon Connect instance with an inbound phone number and a contact flow that integrates with the Lex bot, an Amazon Lex V2 bot defined with the patient-facing intents (confirm appointment, request refill, facility info, callback, transfer to agent, out-of-scope handlers, crisis), per-language locales (en-US and es-US at minimum), slot definitions and example utterances, an Amazon Bedrock inference profile pinned to a specific model and region for the LLM intent fallback and the RAG response generation, an Amazon Bedrock Knowledge Base ingesting the institutional facility-information documents, an Amazon Bedrock Guardrails configuration filtering clinical-advice and financial-advice topics, an Amazon Comprehend Medical client (no per-customer setup required beyond IAM), an Amazon Polly custom-pronunciation lexicon for clinical and institutional terms, an Amazon API Gateway WebSocket API plus REST API for the mobile-app channel, an Amazon Cognito user pool federated to the institutional patient portal IdP, an Amazon Pinpoint application configured for SMS delivery in your region, the Lambda functions that orchestrate each pipeline stage (the channel-entry handler, the crisis-detector, the intent-fallback wrapper, the identity-verifier, the appointment-lookup, the refill-request, the facility-info RAG handler, the warm-transfer trigger, the audit writer), an AWS Step Functions state machine that durably orchestrates multi-stage fulfillment workflows like refill-request-with-OTP, DynamoDB tables that hold conversation state, identity-verification state, and conversation metadata across the lifecycle, AWS Secrets Manager secrets for the EHR API credentials and the pharmacy-system credentials, an Amazon EventBridge bus for cross-system events (`conversation_started`, `crisis_detected`, `conversation_escalated`, `conversation_completed`), Amazon S3 buckets for audio recordings (with brief-retention lifecycle) and the long-term audit archive (with Object Lock in compliance mode), and customer-managed KMS keys for every PHI-bearing data class. The demo replaces all of these with small mocks so the focus stays on the per-stage processing logic rather than on the cloud-resource provisioning.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `connect:StartContactStreaming`, `connect:StopContactStreaming`, `connect:StartOutboundVoiceContact`, `connect:UpdateContactAttributes` for managing inbound and warm-transfer contact flows
- `lex:RecognizeText`, `lex:RecognizeUtterance`, `lex:PutSession`, `lex:GetSession` for Lex V2 conversational interactions
- `bedrock:InvokeModel` for the intent fallback and response generation models, scoped to specific foundation-model ARNs and inference profiles
- `bedrock-agent-runtime:Retrieve`, `bedrock-agent-runtime:RetrieveAndGenerate` for Bedrock Knowledge Bases retrieval-augmented generation
- `bedrock:ApplyGuardrail` for the runtime guardrails check
- `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM` for coded clinical-entity extraction during refill-intent handling
- `transcribe:StartStreamTranscription` for streaming ASR on the app and smart-speaker channels (when not using Connect's built-in ASR)
- `polly:SynthesizeSpeech`, `polly:GetLexicon` for TTS with custom-pronunciation lexicons
- `pinpoint:SendMessages`, `pinpoint:SendOTPMessage` for OTP delivery during step-up authentication
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the conversation-state, identity-verification, and conversation-metadata tables
- `s3:GetObject`, `s3:PutObject` on the audio bucket and the audit-archive bucket, scoped to the per-conversation key prefixes
- `secretsmanager:GetSecretValue` on the EHR-API and pharmacy-system credential secrets pinned to the current rotation version
- `events:PutEvents` on the conversation-events EventBridge bus
- `cloudwatch:PutMetricData` for the operational metrics (per-stage latency, intent-classification confidence distributions, identity-verification success rates, containment rate per intent, escalation rate per intent, crisis-detection rate, per-cohort accuracy)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the audio bucket, the audit bucket, the DynamoDB tables, and the Secrets Manager secrets
- `states:StartExecution` for the Step Functions state machine that orchestrates multi-stage refill workflows

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The channel-entry Lambda has scoped Connect read for caller metadata only. The crisis-detector Lambda has the smallest possible permission scope (no PHI store reads at all; it operates on the utterance text passed in). The appointment-lookup Lambda has scoped EHR API egress and read on the patient-registry table only. The refill-request Lambda has scoped pharmacy-system access, OTP-issuance access via Pinpoint, and read-write on the identity-verification table only. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Audio is PHI from the moment the patient identifies themselves to the institution.** The fact that someone is calling a healthcare organization's patient line is itself protected information; the audio of the call is PHI by virtue of that association alone, in addition to whatever the patient says inside it. Encrypt at rest with KMS customer-managed keys, encrypt in transit with TLS, retention bound by an explicit privacy-officer-reviewed policy, BAAs in place for every vendor service that processes the audio.
- **Recording-consent law varies by jurisdiction.** All-party-consent states require an explicit consent disclosure before recording begins; one-party-consent states require less but most institutions still play a "this call may be recorded for quality" notice. The disclosure is the first thing the caller hears. Cross-state callers (the caller is in California, the institution is in Texas) follow the stricter of the two regimes. The demo's `play_consent_disclosure` plays a default disclosure; production looks up the caller's jurisdiction and plays the appropriate one.
- **Crisis detection runs on every utterance, in parallel with intent classification.** A patient may call about an appointment and mention chest pain three turns into the call. The detector must catch that turn, not when the conversation ends. The demo runs the detector synchronously before intent classification on each utterance; production runs both in parallel and races them with a hard-interrupt callback.
- **Identity verification scales with stakes.** Anonymous lookups (facility hours) require no auth; soft-personal interactions (appointment confirmation) require caller-ID match plus DOB; PHI-disclosing interactions (refill, results) require OTP step-up. The architecture decouples the intent from the assurance requirement and steps up dynamically. The demo encodes the policy in `INTENT_ASSURANCE_REQUIREMENTS`.
- **Scope containment is a clinical-safety requirement.** The LLM components in the stack are inherently disposed to attempt answers to questions they should not be answering. The runtime scope filter, the explicit out-of-scope intent handlers, the system-prompt constraints, and the Bedrock Guardrails defense-in-depth layer are the layered defenses. The demo's `scope_filter_check` is illustrative; production's filter is policy-owned by the clinical-quality officer.
- **Crisis detection vocabulary is a clinical-safety document, not an engineering configuration.** The keyword list, the severity tiering, the multilingual coverage, and the false-negative review program are owned by the clinical-quality officer. The engineering team implements what the clinical team specifies. The demo includes a small `CRISIS_KEYWORDS` table to show the pattern.
- **Warm-handoff packets must include enough context that the patient does not have to repeat themselves.** The agent's screen-pop receives the conversation summary, the transcript reference, the identity-verification status, the detected intent and slots so far, and any crisis flags before the call connects. The demo's `build_warm_handoff_packet` shows the structure.
- **Per-cohort accuracy monitoring is a launch gate, not an analytics afterthought.** Voice ASR has well-documented accuracy disparities across speaker demographics. The cohort axes (per-language, per-channel, per-region, per-age-band where opt-in declared) are policy-level decisions made with the equity-monitoring committee. The demo emits the cohort dimensions on every metric so you can see the segmentation pattern.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, and numeric metadata field passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses Connect, Lex, multiple Lambdas, the Step Functions orchestration, the EventBridge fan-out, and the CloudWatch metric emission into a single Python file for readability.** In production each pipeline stage is a separate Lambda with its own IAM role, error handling, retries, and DLQs, with Step Functions as the durable orchestrator for the multi-stage workflows. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the per-intent assurance requirements, the crisis vocabulary, the scope filter rules, the response templates, and the cohort-axis configuration are what you would change between environments.

```python
import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights. The patient-facing voice pipeline
# operates on heavily PHI-bearing data: the audio is PHI, the
# verbatim transcript is PHI, the intent and slots are PHI, the
# patient identity is PHI, and every fulfillment outcome is a
# clinical-record-adjacent transaction. Log structural metadata
# only (session_id, intent confidence band, identity assurance
# level, escalation reason), never raw transcripts, never
# patient demographics, never medication or appointment values,
# never the OTP code itself.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from Lex, Bedrock, Comprehend
# Medical, Pinpoint, Connect, DynamoDB, S3, EventBridge,
# CloudWatch, and Secrets Manager. The conversational latency
# budget is tight: the patient is on the phone waiting for a
# response. Cap the retries and let the caller's failure path
# surface a clean "let me transfer you" message rather than a
# long silence.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm
# containers so each invocation does not pay the connection cost.
# The demo below uses Mock* classes instead; the real clients
# are never invoked here.
REGION = "us-east-1"
dynamodb              = boto3.resource("dynamodb", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
s3_client             = boto3.client("s3", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
lex_client            = boto3.client("lexv2-runtime", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
bedrock_runtime       = boto3.client("bedrock-runtime", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime",
                                      region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
comprehend_medical    = boto3.client("comprehendmedical", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
polly_client          = boto3.client("polly", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
pinpoint_client       = boto3.client("pinpoint", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
connect_client        = boto3.client("connect", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
eventbridge_client    = boto3.client("events", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
cloudwatch_client     = boto3.client("cloudwatch", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)
secrets_client        = boto3.client("secretsmanager", region_name=REGION,
                                          config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do
# not exist; see run_demo() at the bottom.
CONVERSATION_STATE_TABLE     = "patient-assistant-conversation-state"
IDENTITY_VERIFICATION_TABLE  = "patient-assistant-identity-verification"
CONVERSATION_METADATA_TABLE  = "patient-assistant-conversation-metadata"
AUDIO_BUCKET                 = "patient-assistant-audio-bucket"
AUDIT_ARCHIVE_BUCKET         = "patient-assistant-audit-archive"
CONVERSATION_EVENT_BUS_NAME  = "patient-assistant-events-bus"
CLOUDWATCH_NAMESPACE         = "PatientAssistant"
INSTITUTION_ID               = "riverside-health-system"
LEX_BOT_ID                   = "BOTID12345"
LEX_BOT_ALIAS_ID             = "BOTALIAS67890"
PINPOINT_APPLICATION_ID      = "ppapp1234567890"
INSTITUTIONAL_KB_ID          = "KB001234"
PATIENT_ASSISTANT_GUARDRAIL_ID = "guardrail-12345"
PATIENT_ASSISTANT_GUARDRAIL_VERSION = "1"

# Polly TTS voice persona. Pick one consistent voice per
# language. The custom-pronunciation lexicons handle medication
# names, provider names, and institutional terminology.
POLLY_VOICE_BY_LANGUAGE = {
    "en-US": "Joanna",
    "es-US": "Lupe",
}
POLLY_LEXICON_NAMES = [
    "institutional-pronunciations",
    "medication-pronunciations",
    "provider-pronunciations",
]

# Bedrock configuration. In production, pin to a specific model
# version and inference profile so a model upgrade does not
# silently change response generation behavior. The model and
# region combination must be in your AWS BAA scope.
BEDROCK_INTENT_FALLBACK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
BEDROCK_RESPONSE_GENERATION_MODEL_ID = (
    "anthropic.claude-3-5-sonnet-20240620-v1:0")
BEDROCK_RESPONSE_PROFILE_ARN = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "patient-assistant-response-v1")

# Deploy-time guardrail. Any blank resource name is a deploy-
# time bug, not a runtime surprise.
for _name, _value in [
    ("CONVERSATION_STATE_TABLE",     CONVERSATION_STATE_TABLE),
    ("IDENTITY_VERIFICATION_TABLE",  IDENTITY_VERIFICATION_TABLE),
    ("CONVERSATION_METADATA_TABLE",  CONVERSATION_METADATA_TABLE),
    ("AUDIO_BUCKET",                 AUDIO_BUCKET),
    ("AUDIT_ARCHIVE_BUCKET",         AUDIT_ARCHIVE_BUCKET),
    ("CONVERSATION_EVENT_BUS_NAME",  CONVERSATION_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",         CLOUDWATCH_NAMESPACE),
    ("LEX_BOT_ID",                   LEX_BOT_ID),
    ("INSTITUTIONAL_KB_ID",          INSTITUTIONAL_KB_ID),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every conversation record carries the versions of the artifacts
# that influenced it: the Lex bot version, the LLM prompt
# version, the crisis-detection rules version, the scope-filter
# rules version, the identity-policy version. A future audit
# reconstructs which configuration was active when a particular
# conversation was processed.
LEX_BOT_VERSION                  = "patient-assistant-2026-q2"
INTENT_FALLBACK_PROMPT_VERSION   = "intent-fallback-v1.3"
RESPONSE_GENERATION_PROMPT_VERSION = "response-gen-v1.5"
CRISIS_DETECTION_RULES_VERSION   = "crisis-rules-v2.1"
SCOPE_FILTER_RULES_VERSION       = "scope-filter-v1.4"
IDENTITY_POLICY_VERSION          = "identity-policy-v1.2"

# --- Intent Confidence Threshold ---
# Below this Lex confidence, fall back to the LLM-driven intent
# classifier. Below the LLM's confidence too, default to an
# explicit "let me transfer you" path rather than guess.
INTENT_CONFIDENCE_THRESHOLD      = Decimal("0.70")
LLM_INTENT_CONFIDENCE_THRESHOLD  = Decimal("0.60")

# --- Identity Assurance Levels ---
# A higher number means stronger assurance. The intent-to-
# requirement table below maps each intent to the minimum
# assurance level required.
ASSURANCE_ANONYMOUS       = 0  # No identity verified.
ASSURANCE_SOFT_PERSONAL   = 1  # Caller-ID match + DOB confirmed.
ASSURANCE_PHI_DISCLOSING  = 2  # OTP step-up completed.

INTENT_ASSURANCE_REQUIREMENTS = {
    "facility_info":               ASSURANCE_ANONYMOUS,
    "callback_request":            ASSURANCE_ANONYMOUS,
    "transfer_to_agent":           ASSURANCE_ANONYMOUS,
    "out_of_scope_clinical":       ASSURANCE_ANONYMOUS,
    "out_of_scope_billing_complex": ASSURANCE_ANONYMOUS,
    "confirm_appointment":         ASSURANCE_SOFT_PERSONAL,
    "request_refill":              ASSURANCE_PHI_DISCLOSING,
    "test_results_inquiry":        ASSURANCE_PHI_DISCLOSING,
}

# --- OTP Configuration ---
OTP_LENGTH                  = 6
OTP_TTL_SECONDS             = 300  # 5 minutes
OTP_MAX_ATTEMPTS            = 3

# --- Crisis Detection Rules ---
# Owned by the clinical-quality officer. Versioned. Surfaced as
# a hard interrupt that preempts every other dialog state. This
# list is illustrative, not exhaustive; a real institution will
# have a much larger and per-language-tuned rule set, with
# native-speaker clinical input on each language's vocabulary.
# Tier "acute" routes to 911 + nurse triage.
# Tier "suicidal" routes to 988 + crisis triage.
# Tier "abuse" routes to the protective-services pathway.
# Tier "urgent" routes to nurse triage with urgent flag.
CRISIS_KEYWORDS = {
    "acute_medical_emergency": [
        "chest pain", "can't breathe", "cant breathe",
        "trouble breathing", "having a heart attack",
        "having a stroke", "stroke symptoms", "face is drooping",
        "slurred speech", "severe bleeding", "overdose",
        "overdosed", "took too many pills", "anaphylaxis",
        "throat closing", "baby is not breathing",
        "child not breathing",
    ],
    "suicidal_ideation": [
        "want to die", "want to kill myself",
        "thinking about suicide", "going to end it",
        "going to hurt myself", "going to kill myself",
        "no reason to live", "better off dead",
    ],
    "suspected_abuse": [
        "being hit", "afraid of him", "afraid of her",
        "they hurt me", "elder abuse",
    ],
    "urgent_symptoms": [
        "severe pain", "high fever for days",
        "worst headache of my life", "can't stop vomiting",
        "passed out",
    ],
}

# --- Scope Filter Rules ---
# Topics the assistant must refuse and offer a transfer for. The
# filter runs on every LLM-generated response; if any of these
# patterns match, the response is replaced with an explicit
# refusal-and-transfer prompt. Production also wires Bedrock
# Guardrails as a defense-in-depth layer.
SCOPE_VIOLATION_PATTERNS = {
    "clinical_advice": [
        r"\byou should take\b",
        r"\byour symptoms suggest\b",
        r"\bthat sounds like\b.*\b(infection|cancer|stroke|attack)\b",
        r"\bI recommend that you\b.*\b(start|stop|increase|decrease)\b.*\b(medication|drug|dose)\b",
        r"\btry taking\b",
        r"\bwhat you have is\b",
        r"\bthis condition\b.*\b(means|indicates)\b",
    ],
    "dosing_information": [
        r"\bincrease your dose\b",
        r"\bdouble your dose\b",
        r"\btake more\b.*\b(medication|pills|tablets)\b",
        r"\bskip your dose\b",
    ],
    "diagnostic_interpretation": [
        r"\byour lab.*results.*mean\b",
        r"\bnormal range is\b",
        r"\babove normal\b",
        r"\bbelow normal\b",
    ],
}

# --- Recording Consent Disclosure ---
# Production looks up the caller's jurisdiction and selects the
# appropriate disclosure. The demo defaults to the all-party-
# consent variant since it is the more conservative.
CONSENT_DISCLOSURE_ALL_PARTY = (
    "Thank you for calling Riverside Health. This call may be "
    "recorded for quality and training. To continue, please say "
    "yes or stay on the line.")
CONSENT_DISCLOSURE_ONE_PARTY = (
    "Thank you for calling Riverside Health. This call may be "
    "recorded for quality.")

# All-party-consent states. The list is approximate and changes
# over time as state law evolves; production maintains this in a
# legal-team-reviewed configuration with an explicit update
# cadence.
# TODO (TechWriter): verify the current all-party-consent state
# list against the Reporters Committee for Freedom of the Press
# state-by-state recording-laws guide before deploying.
ALL_PARTY_CONSENT_STATES = {
    "CA", "CT", "FL", "IL", "MD", "MA",
    "MT", "NV", "NH", "PA", "WA",
}

# --- Cohort Axes ---
# Stratification axes used in the audit pipeline for equity
# monitoring. The age-band is opt-in: the patient self-discloses
# during portal enrollment, and the value flows through SMART
# launch context where applicable. Inferred demographic labels
# for protected classes are explicitly not used.
COHORT_AXES = ["channel", "language", "region_hint", "age_band"]

# --- Greeting and Standard Phrases ---
GREETING_BY_LANGUAGE = {
    "en-US": "How can I help you today?",
    "es-US": "Como puedo ayudarle hoy?",
}
TRANSFER_TO_AGENT_PHRASE = (
    "Let me connect you with someone who can help.")
CLINICAL_OUT_OF_SCOPE_PHRASE = (
    "I cant help with clinical questions, but our nurse line "
    "can. Would you like me to transfer you?")
ACUTE_EMERGENCY_PHRASE = (
    "If this is a medical emergency, please hang up and dial "
    "911. Otherwise, Im connecting you with our nurse line "
    "right now.")
SUICIDAL_CRISIS_PHRASE = (
    "Thank you for telling me. The 988 Suicide and Crisis "
    "Lifeline can help right now. Im also connecting you with "
    "our crisis team.")
URGENT_TRIAGE_PHRASE = (
    "Id like to connect you with our nurse line so they can "
    "help with what youre experiencing.")

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

def _hash_value(value):
    """Stable hash for non-PHI audit linkage."""
    if not value:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

def _hash_otp(code, salt):
    """OTP storage uses HMAC-SHA256 with a per-issuance salt."""
    return hmac.new(salt.encode("utf-8"),
                     code.encode("utf-8"),
                     hashlib.sha256).hexdigest()

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _generate_otp(length=OTP_LENGTH):
    """Cryptographically random OTP."""
    return "".join(str(secrets.randbelow(10)) for _ in range(length))
```

---

## Mock Resources for the Demo

These mocks stand in for the production AWS resources and back-office systems. They are deliberately simple and are not how you would build the real thing. Their purpose is to keep the focus on the patient-facing voice pipeline logic.

```python
class MockLex:
    """
    Stands in for Amazon Lex V2's RecognizeText API. In
    production you call lex_client.recognize_text(botId=...,
    botAliasId=..., localeId=..., sessionId=..., text=...) and
    receive back interpretations (intent + slots + confidence).
    The demo synthesizes responses from a fixture mapping
    (utterance_substring -> intent + slots + confidence) so the
    rest of the pipeline can be exercised without a real Lex bot.
    """
    def __init__(self, fixture_map):
        self._fixtures = fixture_map

    def recognize_text(self, session_id, text, locale="en-US"):
        # In production this is lex_client.recognize_text(...)
        # with the bot configured to handle each intent.
        normalized = (text or "").lower().strip()
        for substring, response in self._fixtures.items():
            if substring in normalized:
                return {
                    "sessionId":      session_id,
                    "interpretations": [{
                        "intent": {
                            "name":  response["intent"],
                            "slots": dict(response.get("slots", {})),
                        },
                        "nluConfidence": {
                            "score": response.get("confidence", 0.0)
                        },
                    }],
                }
        # Default to FallbackIntent with low confidence so the
        # LLM fallback path activates.
        return {
            "sessionId":      session_id,
            "interpretations": [{
                "intent": {"name": "FallbackIntent", "slots": {}},
                "nluConfidence": {"score": 0.30},
            }],
        }

class MockBedrock:
    """
    Stands in for Amazon Bedrock's InvokeModel and the Bedrock
    Knowledge Bases retrieve_and_generate API. Two invocation
    patterns: intent-fallback classification (returns a
    structured intent label and confidence) and RAG-grounded
    response generation (returns a natural reply grounded in
    knowledge-base passages).
    """
    def __init__(self, intent_responses, rag_responses):
        self._intent_responses = intent_responses
        self._rag_responses    = rag_responses

    def classify_intent(self, utterance, available_intents,
                         conversation_history):
        # Production: bedrock_runtime.invoke_model with a strict
        # JSON-schema response_format and the conversation
        # history in the prompt context.
        normalized = (utterance or "").lower().strip()
        for substring, response in self._intent_responses.items():
            if substring in normalized:
                return {"body": json.dumps(response)}
        return {"body": json.dumps({
            "intent":     "transfer_to_agent",
            "confidence": 0.50,
            "rationale":  "No fixture matched; default to transfer.",
        })}

    def generate_rag_response(self, query, retrieved_passages,
                                language="en-US"):
        # Production: bedrock_agent_runtime.retrieve_and_generate
        # with the institutional knowledge base ID, with
        # Bedrock Guardrails configured for clinical-advice
        # filtering.
        normalized = (query or "").lower().strip()
        for substring, response in self._rag_responses.items():
            if substring in normalized:
                return {"body": json.dumps(response)}
        return {"body": json.dumps({
            "text":        ("Im not sure I can help with that, "
                             "let me connect you with someone "
                             "who can."),
            "in_scope":    False,
            "source_passages": [],
        })}

class MockBedrockKB:
    """
    Stands in for Bedrock Knowledge Bases retrieval. The demo
    returns curated facility-information snippets keyed by
    query substring.
    """
    def __init__(self, snippet_fixtures):
        self._fixtures = snippet_fixtures

    def retrieve(self, query, max_results=3):
        normalized = (query or "").lower().strip()
        for substring, snippets in self._fixtures.items():
            if substring in normalized:
                return {"passages": list(snippets[:max_results])}
        return {"passages": []}

class MockComprehendMedical:
    """
    Stands in for Amazon Comprehend Medical's DetectEntitiesV2
    and InferRxNorm APIs. Used to extract a coded medication
    entity from a refill request.
    """
    def __init__(self, entity_fixtures):
        self._fixtures = entity_fixtures

    def infer_rx_norm(self, text):
        normalized = (text or "").lower().strip()
        for substring, response in self._fixtures.items():
            if substring in normalized:
                return dict(response)
        return {"Entities": []}

class MockPolly:
    """
    Stands in for Amazon Polly's SynthesizeSpeech API. Returns
    an opaque "audio bytes" reference rather than real audio so
    the demo can show what would be played without invoking the
    real service.
    """
    def __init__(self):
        self.synthesized = []

    def synthesize_speech(self, text, voice_id, language_code,
                            lexicon_names=None):
        record = {
            "text":          text,
            "voice_id":      voice_id,
            "language_code": language_code,
            "lexicon_names": list(lexicon_names or []),
            "synthesized_at": _now_iso(),
        }
        self.synthesized.append(record)
        return {"AudioStream": b"<polly audio bytes>",
                "ContentType": "audio/pcm",
                "RequestCharacters": len(text or "")}

class MockPinpoint:
    """
    Stands in for Amazon Pinpoint's OTP delivery. Captures the
    OTP code and destination so the demo can demonstrate the
    step-up flow without sending real SMS.
    """
    def __init__(self):
        self.delivered_otps = []

    def send_otp(self, destination, code, channel="SMS"):
        self.delivered_otps.append({
            "destination":  destination,
            "code":         code,
            "channel":      channel,
            "delivered_at": _now_iso(),
        })
        return {"MessageResponse":
                {"Result": {destination: {"StatusCode": 200,
                                          "DeliveryStatus":
                                              "SUCCESSFUL"}}}}

class MockConnect:
    """
    Stands in for Amazon Connect's call control. In production
    this is connect_client.update_contact_attributes(...) plus
    the contact-flow transfer block that routes the call to the
    target queue with the screen-pop attributes set. The mock
    records what would have been done.
    """
    def __init__(self):
        self.transfers = []
        self.recordings = []

    def start_recording(self, contact_id):
        self.recordings.append({
            "contact_id": contact_id,
            "started_at": _now_iso(),
        })

    def warm_transfer(self, contact_id, target_queue,
                       screen_pop_packet):
        self.transfers.append({
            "contact_id":         contact_id,
            "target_queue":       target_queue,
            "screen_pop_packet":  screen_pop_packet,
            "transferred_at":     _now_iso(),
        })

class MockEHR:
    """
    Stands in for the EHR's appointment, refill, and billing
    APIs. In production this is FHIR endpoints (Appointment,
    MedicationRequest, Coverage) plus pharmacy-workflow APIs
    plus billing-system APIs. The mock returns canned data for
    a small set of patients.
    """
    def __init__(self):
        self._appointments_by_patient = {
            "pt-44219": [
                {"id":       "appt-90001",
                 "status":   "booked",
                 "start":    "2026-06-17T18:30:00Z",
                 "provider": "Dr. Patel",
                 "specialty": "Cardiology",
                 "location": "Riverside Cardiology Clinic"},
            ],
            "pt-77310": [
                {"id":       "appt-90002",
                 "status":   "booked",
                 "start":    "2026-05-30T14:00:00Z",
                 "provider": "Dr. Nguyen",
                 "specialty": "Primary Care",
                 "location": "Riverside Main Clinic"},
                {"id":       "appt-90003",
                 "status":   "booked",
                 "start":    "2026-06-12T09:15:00Z",
                 "provider": "Dr. Vega",
                 "specialty": "Endocrinology",
                 "location": "Riverside Endocrine Clinic"},
            ],
        }
        self._refill_tickets = []

    def search_appointments(self, patient_id):
        return list(self._appointments_by_patient.get(
            patient_id, []))

    def create_refill_request(self, patient_id, medication_rxnorm,
                               medication_text, requested_via,
                               session_id):
        ticket_id = f"refill-{uuid.uuid4().hex[:8]}"
        ticket = {
            "ticket_id":         ticket_id,
            "patient_id":        patient_id,
            "medication_rxnorm": medication_rxnorm,
            "medication_text":   medication_text,
            "requested_via":     requested_via,
            "session_id":        session_id,
            "status":            "queued_for_clinical_review",
            "created_at":        _now_iso(),
        }
        self._refill_tickets.append(ticket)
        return ticket

class MockPatientRegistry:
    """
    Stands in for the institutional patient registry. The demo
    has a tiny patient population keyed by phone number so the
    caller-ID match in the soft-personal identity flow has
    something to look up.
    """
    def __init__(self):
        self._by_phone = {
            "+15555550143": {
                "patient_id": "pt-44219",
                "first_name": "Walter",
                "last_name":  "Bowen",
                "dob":        "1943-10-14",
                "preferred_otp_destination": "+15555550143",
                "preferred_language": "en-US",
                "registered_phones": ["+15555550143"],
                "opt_in_age_band": "75_plus",
            },
            "+15555550199": {
                "patient_id": "pt-77310",
                "first_name": "Marisol",
                "last_name":  "Hernandez",
                "dob":        "1968-03-22",
                "preferred_otp_destination": "+15555550199",
                "preferred_language": "es-US",
                "registered_phones": ["+15555550199"],
                "opt_in_age_band": "55_64",
            },
            "+15555550111": {
                "patient_id": "pt-99001",
                "first_name": "Test",
                "last_name":  "Anonymous",
                "dob":        "1985-01-01",
                "preferred_otp_destination": "+15555550111",
                "preferred_language": "en-US",
                "registered_phones": ["+15555550111"],
                "opt_in_age_band": "not_disclosed",
            },
        }

    def find_by_phone(self, phone):
        return dict(self._by_phone.get(phone, {})) or None

    def verify_dob_match(self, patient_id, dob_attempt):
        for record in self._by_phone.values():
            if (record["patient_id"] == patient_id
                    and record["dob"] == dob_attempt):
                return True
        return False

class MockConversationState:
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

class MockIdentityVerification:
    """
    Stands in for the DynamoDB identity-verification table. In
    production the table has a TTL on each issuance so expired
    OTPs auto-delete. The mock checks the timestamp on lookup.
    """
    def __init__(self):
        self._items = {}

    def issue_otp(self, session_id, code_hash, salt,
                   destination, ttl_seconds):
        self._items[session_id] = {
            "session_id":    session_id,
            "code_hash":     code_hash,
            "salt":          salt,
            "destination":   destination,
            "issued_at":     _now_iso(),
            "expires_at":    (datetime.now(timezone.utc)
                              + timedelta(seconds=ttl_seconds))
                                .isoformat(),
            "attempts":      0,
            "consumed":      False,
        }

    def verify_otp(self, session_id, code_attempt):
        record = self._items.get(session_id)
        if not record:
            return {"verified": False, "reason": "no_otp_issued"}
        if record["consumed"]:
            return {"verified": False, "reason": "otp_already_consumed"}
        expires_at = datetime.fromisoformat(
            record["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_at:
            return {"verified": False, "reason": "otp_expired"}
        record["attempts"] += 1
        if record["attempts"] > OTP_MAX_ATTEMPTS:
            return {"verified": False, "reason": "max_attempts_exceeded"}
        attempted_hash = _hash_otp(code_attempt, record["salt"])
        if hmac.compare_digest(attempted_hash, record["code_hash"]):
            record["consumed"] = True
            return {"verified": True}
        return {"verified": False, "reason": "code_mismatch"}

class MockConversationMetadata:
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
            "body":      body,
            "metadata":  dict(metadata or {}),
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
    Stands in for Amazon EventBridge. Lifecycle events flow
    here for cross-system fan-out: conversation_started,
    crisis_detected, conversation_escalated, conversation_completed.
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
conversation_state    = MockConversationState()
identity_verification = MockIdentityVerification()
conversation_meta     = MockConversationMetadata()
s3_store              = MockS3()
event_bus             = MockEventBus()
cloudwatch            = MockCloudWatch()
polly_mock            = MockPolly()
pinpoint_mock         = MockPinpoint()
connect_mock          = MockConnect()
ehr                   = MockEHR()
patient_registry      = MockPatientRegistry()
# lex_mock, bedrock_mock, kb_mock, and comprehend_mock are wired
# up in run_demo() with fixture data tailored to each scenario.
lex_mock              = None
bedrock_mock          = None
kb_mock               = None
comprehend_mock       = None

def audit_log(event):
    """
    Sanitized audit print so you can see the sequence of
    decisions without leaking the underlying values. Production
    routes events to CloudWatch Logs Insights with structured
    JSON; ship to a SIEM if available.
    """
    safe_event = {k: v for k, v in event.items()
                  if k not in {"verbatim_transcript",
                                "patient_demographics",
                                "otp_code",
                                "raw_response_text",
                                "patient_dob"}}
    if "verbatim_transcript" in event:
        safe_event["verbatim_transcript_length"] = len(
            event["verbatim_transcript"] or "")
    if "raw_response_text" in event:
        safe_event["response_text_length"] = len(
            event["raw_response_text"] or "")
    logger.info("AUDIT %s", json.dumps(safe_event, default=str))
```

---

## Step 1: Receive the Channel Entry, Play the Recording-Consent Disclosure, and Bootstrap the Conversation

*The pseudocode calls this `ON channel_entry(...)`. The patient connects through phone, app, or smart speaker. The system determines the recording-consent regime (jurisdictional choice between all-party and one-party consent), plays the appropriate disclosure, captures the channel and caller-ID metadata, and bootstraps a conversation session. Skip the consent disclosure and the institution risks state-law compliance violations in all-party-consent jurisdictions; skip the channel-and-caller-ID capture and the warm-handoff packet later in the pipeline has nothing to attach the patient identity to.*

```python
def determine_consent_regime(caller_id, institution_state):
    """
    Determine which recording-consent disclosure the caller
    should hear. Cross-jurisdiction calls follow the stricter
    of the two regimes (caller's state vs. institution's state).
    Production looks up the caller's likely state from area
    code, registered address, or a third-party number-lookup
    service; the demo uses a tiny area-code-to-state map.
    """
    # Approximate area-code-to-state mapping for the demo.
    AREA_CODE_TO_STATE = {
        "415": "CA", "510": "CA", "213": "CA",
        "212": "NY", "718": "NY",
        "312": "IL", "773": "IL",
        "617": "MA",
        "215": "PA",
        "206": "WA",
        "555": "TX",  # Fictional area code used in test data.
    }
    area_code = (caller_id or "")[2:5] if caller_id else ""
    caller_state = AREA_CODE_TO_STATE.get(area_code,
                                            institution_state)

    # Stricter regime wins: any all-party-consent state in play
    # triggers the all-party disclosure.
    if (caller_state in ALL_PARTY_CONSENT_STATES
            or institution_state in ALL_PARTY_CONSENT_STATES):
        return "all_party_consent"
    return "one_party_consent"

def play_consent_disclosure(consent_regime, language):
    """
    Play the appropriate consent disclosure. Production uses
    Polly to synthesize the disclosure (or a pre-recorded
    audio prompt) into the Connect contact flow. The mock
    routes through MockPolly so the demo records that the
    disclosure was synthesized.
    """
    if consent_regime == "all_party_consent":
        text = CONSENT_DISCLOSURE_ALL_PARTY
    else:
        text = CONSENT_DISCLOSURE_ONE_PARTY
    voice = POLLY_VOICE_BY_LANGUAGE.get(language, "Joanna")
    polly_mock.synthesize_speech(
        text=text, voice_id=voice,
        language_code=language,
        lexicon_names=POLLY_LEXICON_NAMES)
    return text

def open_conversation(channel_type, caller_id,
                       channel_metadata=None,
                       institution_state="TX",
                       language=None):
    """
    Open a patient-facing conversation in response to a channel
    entry event. Plays the recording-consent disclosure,
    bootstraps the conversation session, and starts the recording
    if the caller acknowledged consent.

    Args:
        channel_type: One of "telephony", "app", "smart_speaker".
        caller_id: E.164-formatted phone number for telephony
            calls; opaque session identifier for app and smart-
            speaker.
        channel_metadata: Optional dict with channel-specific
            context (Connect contact_id, app device hash, smart-
            speaker device id).
        institution_state: Two-letter state code for the
            institution's primary location. Used for jurisdiction
            handling.
        language: Optional preferred language. Defaults from the
            patient registry lookup or "en-US".

    Returns:
        Session-context dict consumed by downstream stages.
    """
    channel_metadata = channel_metadata or {}

    # Step 1A: determine the recording-consent regime and play
    # the appropriate disclosure. The disclosure is the first
    # thing the caller hears; production gates audio recording
    # on this step succeeding.
    consent_regime = determine_consent_regime(
        caller_id=caller_id,
        institution_state=institution_state)
    # Best-effort language detection from the patient registry.
    if not language:
        registered = patient_registry.find_by_phone(caller_id) \
            if caller_id else None
        language = (registered.get("preferred_language", "en-US")
                    if registered else "en-US")
    disclosure_text = play_consent_disclosure(
        consent_regime=consent_regime, language=language)

    # Step 1B: bootstrap the conversation session.
    session_id = "conv-" + uuid.uuid4().hex[:16]
    started_at = _now_iso()
    region_hint = (channel_metadata.get("region_hint")
                   or "us-northeast")

    conversation_state.put(session_id, _to_decimal({
        "session_id":            session_id,
        "channel_type":          channel_type,
        "caller_id_hint":        caller_id,
        "consent_regime":        consent_regime,
        "language":              language,
        "region_hint":           region_hint,
        "identity_assurance_level": ASSURANCE_ANONYMOUS,
        "patient_id":            None,
        "caregiver_context":     None,
        "started_at":            started_at,
        "status":                "active",
        "intent_history":        [],
        "turn_history":          [],
        "fulfillment_history":   [],
        "escalation_history":    [],
        "scope_violation_events": [],
        "crisis_flags":          [],
        "connect_contact_id":
            channel_metadata.get("connect_contact_id"),
    }))

    conversation_meta.put(session_id, _to_decimal({
        "session_id":   session_id,
        "channel_type": channel_type,
        "language":     language,
        "started_at":   started_at,
        "lex_bot_version": LEX_BOT_VERSION,
        "intent_fallback_prompt_version":
            INTENT_FALLBACK_PROMPT_VERSION,
        "response_generation_prompt_version":
            RESPONSE_GENERATION_PROMPT_VERSION,
        "crisis_detection_rules_version":
            CRISIS_DETECTION_RULES_VERSION,
        "scope_filter_rules_version":
            SCOPE_FILTER_RULES_VERSION,
        "identity_policy_version":
            IDENTITY_POLICY_VERSION,
        "status":       "session_open",
    }))

    # Step 1C: start the call recording (in production, only
    # after consent acknowledgment for all-party-consent
    # jurisdictions).
    if channel_type == "telephony" and \
            channel_metadata.get("connect_contact_id"):
        connect_mock.start_recording(
            channel_metadata["connect_contact_id"])

    # Step 1D: emit lifecycle event.
    event_bus.put_events([{
        "Source":       "patient_assistant",
        "DetailType":   "conversation_started",
        "EventBusName": CONVERSATION_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":     session_id,
            "channel":        channel_type,
            "language":       language,
            "consent_regime": consent_regime,
            "timestamp":      started_at,
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ConversationsStarted", 1, "Count",
        dimensions={"channel":  channel_type,
                    "language": language,
                    "institution_id": INSTITUTION_ID})

    audit_log({
        "event_type":     "CONVERSATION_OPENED",
        "session_id":     session_id,
        "channel":        channel_type,
        "language":       language,
        "consent_regime": consent_regime,
        "timestamp":      started_at,
    })

    # Step 1E: play the greeting and prepare to receive the
    # first utterance. In production the greeting is
    # synthesized via Polly and played through the channel
    # sink; the demo records the synthesis call.
    greeting_text = GREETING_BY_LANGUAGE.get(language,
                                              GREETING_BY_LANGUAGE["en-US"])
    polly_mock.synthesize_speech(
        text=greeting_text,
        voice_id=POLLY_VOICE_BY_LANGUAGE.get(language, "Joanna"),
        language_code=language,
        lexicon_names=POLLY_LEXICON_NAMES)

    return {
        "session_id":    session_id,
        "channel_type":  channel_type,
        "caller_id":     caller_id,
        "language":      language,
        "consent_regime": consent_regime,
        "started_at":    started_at,
        "disclosure_text": disclosure_text,
        "greeting_text":   greeting_text,
        "region_hint":     region_hint,
        "connect_contact_id":
            channel_metadata.get("connect_contact_id"),
    }
```

---

## Step 2: Run the Parallel Crisis Detector on Every Utterance

*The pseudocode calls this `on_utterance_received(...)`. As the patient speaks, the ASR produces transcripts and every utterance flows through the crisis detector before any other dialog logic. The detector is layered: a curated keyword list (highest recall, easiest to audit), a small classifier for paraphrase variation, and an LLM-driven detector for the subtle cases. A crisis detection preempts everything else: the conversation is rerouted to 911, 988, the protective-services pathway, or nurse triage depending on severity. Skip the parallel crisis detection and a patient who mentions chest pain in passing during an appointment-confirmation flow may not have it noticed until the conversation ends, which is too late.*

```python
def detect_crisis(utterance):
    """
    Layered crisis detector. The demo only implements the
    keyword-list layer; production wires a small dedicated
    classifier and an LLM-driven detector on top, with the
    union of detections taken so any single layer can preempt
    the conversation.

    Returns:
        Dict with severity ("none", "high"), category, and the
        matched phrase if any.
    """
    if not utterance:
        return {"severity": "none", "category": None,
                "matched_phrase": None}

    text = utterance.lower()

    # The order of evaluation matters: acute medical emergency
    # is the highest-priority bucket because the routing
    # disposition (911 + nurse triage) is the most time-critical.
    for category in ("acute_medical_emergency",
                      "suicidal_ideation",
                      "suspected_abuse",
                      "urgent_symptoms"):
        for phrase in CRISIS_KEYWORDS.get(category, []):
            if phrase in text:
                return {
                    "severity":       "high",
                    "category":       category,
                    "matched_phrase": phrase,
                    "rules_version":  CRISIS_DETECTION_RULES_VERSION,
                }
    return {"severity": "none", "category": None,
            "matched_phrase": None}

def handle_crisis(session_context, crisis_signal, utterance):
    """
    Hard-interrupt handler invoked when the crisis detector
    fires. Updates the conversation state, speaks the
    appropriate immediate response, and warm-transfers to the
    correct destination. Identity verification is intentionally
    bypassed: getting the patient to help comes first.
    """
    session_id = session_context["session_id"]
    severity   = crisis_signal["severity"]
    category   = crisis_signal["category"]
    language   = session_context["language"]

    # Update state with the crisis flag for the audit trail.
    conversation_state.update(session_id, {
        "crisis_detected":   True,
        "crisis_severity":   severity,
        "crisis_category":   category,
        "crisis_matched_phrase":
            crisis_signal.get("matched_phrase"),
    })

    # Emit the crisis event for immediate clinical-quality
    # review and per-cohort accuracy tracking.
    event_bus.put_events([{
        "Source":       "patient_assistant",
        "DetailType":   "crisis_detected",
        "EventBusName": CONVERSATION_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":     session_id,
            "severity":       severity,
            "category":       category,
            "channel":        session_context["channel_type"],
            "language":       language,
            "matched_phrase":
                crisis_signal.get("matched_phrase"),
            "timestamp":      _now_iso(),
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "CrisisDetected", 1, "Count",
        dimensions={"category": category,
                    "channel":  session_context["channel_type"],
                    "language": language})

    # Map category -> spoken response and target queue.
    if category == "acute_medical_emergency":
        response_text = ACUTE_EMERGENCY_PHRASE
        target_queue  = "nurse-triage-emergency"
    elif category == "suicidal_ideation":
        response_text = SUICIDAL_CRISIS_PHRASE
        target_queue  = "behavioral-health-crisis"
    elif category == "suspected_abuse":
        response_text = (
            "Im going to connect you with someone who can help.")
        target_queue  = "protective-services-pathway"
    else:  # urgent_symptoms
        response_text = URGENT_TRIAGE_PHRASE
        target_queue  = "nurse-triage-urgent"

    # Speak the immediate response.
    voice_id = POLLY_VOICE_BY_LANGUAGE.get(language, "Joanna")
    polly_mock.synthesize_speech(
        text=response_text, voice_id=voice_id,
        language_code=language,
        lexicon_names=POLLY_LEXICON_NAMES)

    # Build and ship the warm-handoff packet for crisis routing.
    packet = build_warm_handoff_packet(
        session_context=session_context,
        target_queue=target_queue,
        handoff_reason=f"crisis:{category}")
    state = conversation_state.get(session_id)
    contact_id = state.get("connect_contact_id")
    if contact_id:
        connect_mock.warm_transfer(
            contact_id=contact_id,
            target_queue=target_queue,
            screen_pop_packet=packet)
    conversation_state.update(session_id, {
        "status":            "escalated_crisis",
        "escalation_history": list(state.get(
            "escalation_history", [])) + [{
                "reason":    f"crisis:{category}",
                "queue":     target_queue,
                "at":        _now_iso(),
            }],
    })

    audit_log({
        "event_type":     "CRISIS_ROUTED",
        "session_id":     session_id,
        "severity":       severity,
        "category":       category,
        "target_queue":   target_queue,
    })

    return {"crisis_handled": True,
            "target_queue":   target_queue,
            "response_text":  response_text}

def on_utterance_received(session_context, utterance,
                            asr_avg_confidence=Decimal("0.92")):
    """
    Top-level handler invoked for every patient utterance. Runs
    the parallel crisis detector first; if no crisis, returns
    the utterance for downstream intent classification.

    Args:
        session_context: Dict from open_conversation.
        utterance: The verbatim transcript text for this turn.
        asr_avg_confidence: Average per-word ASR confidence for
            this utterance, used for downstream gating.

    Returns:
        Dict with crisis_handled (bool) and the utterance for
        intent classification when no crisis was detected.
    """
    session_id = session_context["session_id"]

    # Append to the conversation's turn history for the
    # warm-handoff packet and the audit trail.
    state = conversation_state.get(session_id)
    turn_history = list(state.get("turn_history", []))
    turn_history.append({
        "speaker":   "patient",
        "text_hash": _hash_value(utterance),
        "asr_avg_confidence": asr_avg_confidence,
        "at":        _now_iso(),
    })
    conversation_state.update(session_id, _to_decimal({
        "turn_history": turn_history,
    }))

    # Step 2A: crisis detection runs on every utterance,
    # regardless of dialog state.
    crisis_signal = detect_crisis(utterance)

    if crisis_signal["severity"] != "none":
        crisis_outcome = handle_crisis(
            session_context=session_context,
            crisis_signal=crisis_signal,
            utterance=utterance)
        return {"crisis_handled": True,
                "outcome":         crisis_outcome}

    # Step 2B: log ASR confidence for per-cohort monitoring and
    # downstream gating. Low-confidence audio for a particular
    # cohort is the equity-monitoring signal.
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ASRAvgConfidence",
        float(asr_avg_confidence) * 100, "Percent",
        dimensions={"channel":  session_context["channel_type"],
                    "language": session_context["language"]})

    return {"crisis_handled": False,
            "utterance":       utterance,
            "asr_avg_confidence": asr_avg_confidence}
```

---

## Step 3: Classify the Intent and Extract Slots

*The pseudocode calls this `classify_intent_and_slots(...)`. Within the non-crisis flow, the Lex bot maps the utterance to one of the configured intents and extracts the relevant slots. When Lex's confidence is below the gate, the LLM-driven fallback handles the harder cases. For medication-bearing slots, Comprehend Medical returns a coded RxNorm entity. Out-of-scope intents have explicit handlers that refuse politely and offer a concrete alternative. Skip the explicit out-of-scope handler and the LLM may attempt to answer clinical questions, which is the worst class of failure for this recipe.*

```python
AVAILABLE_INTENTS = [
    "confirm_appointment",
    "request_refill",
    "facility_info",
    "callback_request",
    "transfer_to_agent",
    "out_of_scope_clinical",
    "out_of_scope_billing_complex",
    "test_results_inquiry",
]

def classify_intent(session_context, utterance):
    """
    Run the layered intent classifier: Lex first, LLM fallback
    when Lex's confidence is below the gate, an explicit
    transfer when both classifiers fail.

    Returns:
        Dict with intent, slots, confidence, and the source
        ("lex" | "llm_fallback" | "default_transfer").
    """
    session_id = session_context["session_id"]
    language   = session_context["language"]

    # Step 3A: primary intent classification via Lex.
    lex_result = lex_mock.recognize_text(
        session_id=session_id,
        text=utterance,
        locale=language)
    interpretation = lex_result["interpretations"][0]
    lex_intent      = interpretation["intent"]["name"]
    lex_slots       = dict(interpretation["intent"].get("slots", {}))
    lex_confidence  = Decimal(str(
        interpretation["nluConfidence"]["score"]))

    if lex_confidence >= INTENT_CONFIDENCE_THRESHOLD \
            and lex_intent != "FallbackIntent":
        return {
            "intent":     lex_intent,
            "slots":      lex_slots,
            "confidence": lex_confidence,
            "source":     "lex",
        }

    # Step 3B: LLM fallback for low-confidence utterances. The
    # LLM sees the conversation history (turn count and last
    # few turns, not the raw transcript) and returns a
    # structured classification. Production validates the LLM
    # output against the available-intents list before trusting
    # it.
    state = conversation_state.get(session_id)
    history_summary = {
        "turn_count": len(state.get("turn_history", [])),
        "prior_intents": [i["intent"]
                           for i in state.get("intent_history", [])
                           [-3:]],
    }
    llm_response = bedrock_mock.classify_intent(
        utterance=utterance,
        available_intents=AVAILABLE_INTENTS,
        conversation_history=history_summary)
    try:
        parsed = json.loads(llm_response["body"])
        llm_intent      = parsed.get("intent", "transfer_to_agent")
        llm_confidence  = Decimal(str(parsed.get("confidence", 0.0)))
    except (TypeError, ValueError):
        llm_intent      = "transfer_to_agent"
        llm_confidence  = Decimal("0.0")

    # Validate the LLM's intent against the allowed list. An
    # unknown label collapses to transfer_to_agent.
    if llm_intent not in AVAILABLE_INTENTS:
        llm_intent     = "transfer_to_agent"
        llm_confidence = Decimal("0.0")

    if llm_confidence >= LLM_INTENT_CONFIDENCE_THRESHOLD:
        return {
            "intent":     llm_intent,
            "slots":      lex_slots,  # LLM did not re-extract slots
            "confidence": llm_confidence,
            "source":     "llm_fallback",
        }

    # Step 3C: both classifiers failed; default to transfer.
    # The explicit "I dont know, let me get you to someone" is
    # always safer than guessing.
    return {
        "intent":     "transfer_to_agent",
        "slots":      {},
        "confidence": Decimal("0.0"),
        "source":     "default_transfer",
    }

def extract_medication_slot(utterance):
    """
    Use Comprehend Medical's RxNorm linker to extract a coded
    medication entity from the utterance. Returns None if no
    medication entity is detected.
    """
    response = comprehend_mock.infer_rx_norm(utterance)
    entities = response.get("Entities", [])
    if not entities:
        return None

    # Take the highest-confidence medication entity.
    best = max(entities,
               key=lambda e: e.get("Score", 0.0))
    rx_concepts = best.get("RxNormConcepts", [])
    if not rx_concepts:
        return None
    top_concept = rx_concepts[0]
    return {
        "medication_text":     best.get("Text"),
        "medication_rxnorm":   top_concept.get("Code"),
        "medication_display":  top_concept.get("Description"),
        "extraction_confidence":
            Decimal(str(best.get("Score", 0.0))),
    }

def classify_and_extract(session_context, utterance):
    """
    End-to-end intent classification and slot extraction with
    out-of-scope handling and medication-slot RxNorm linking.

    Returns:
        Dict with intent, slots, confidence, and a "handled"
        flag indicating whether the result is terminal (out-of-
        scope refusal, immediate transfer) or whether the
        downstream identity-and-fulfillment stages should run.
    """
    session_id = session_context["session_id"]

    intent_result = classify_intent(
        session_context=session_context,
        utterance=utterance)
    intent     = intent_result["intent"]
    slots      = dict(intent_result["slots"])
    confidence = intent_result["confidence"]

    # Append the intent observation to history.
    state = conversation_state.get(session_id)
    intent_history = list(state.get("intent_history", []))
    intent_history.append({
        "intent":     intent,
        "confidence": confidence,
        "source":     intent_result["source"],
        "at":         _now_iso(),
    })
    conversation_state.update(session_id, _to_decimal({
        "intent_history": intent_history,
    }))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "IntentClassificationConfidence",
        float(confidence) * 100, "Percent",
        dimensions={"intent":  intent,
                    "channel": session_context["channel_type"],
                    "language": session_context["language"],
                    "source":  intent_result["source"]})

    # Step 3D: out-of-scope handling. The LLM components in the
    # stack are inherently disposed to attempt clinical
    # answers; the explicit refusal-and-transfer path is the
    # boundary that makes the assistant safe.
    if intent == "out_of_scope_clinical":
        return {"intent": intent, "slots": {},
                "confidence": confidence,
                "handled": True,
                "disposition": "transfer_after_refusal",
                "response_text": CLINICAL_OUT_OF_SCOPE_PHRASE,
                "target_queue": "nurse-triage-general"}

    if intent == "out_of_scope_billing_complex":
        return {"intent": intent, "slots": {},
                "confidence": confidence,
                "handled": True,
                "disposition": "transfer_after_refusal",
                "response_text": (
                    "Let me get you to someone in billing who "
                    "can help with that."),
                "target_queue": "billing"}

    if intent == "transfer_to_agent":
        return {"intent": intent, "slots": {},
                "confidence": confidence,
                "handled": True,
                "disposition": "transfer",
                "response_text": TRANSFER_TO_AGENT_PHRASE,
                "target_queue": "general"}

    # Step 3E: medication-slot RxNorm linking for refill intent.
    if intent == "request_refill":
        med_slot = extract_medication_slot(utterance)
        if med_slot:
            slots.update(med_slot)
        else:
            # Refill without an extractable medication: send to
            # a human for clarification.
            return {"intent": intent, "slots": {},
                    "confidence": confidence,
                    "handled": True,
                    "disposition": "transfer",
                    "response_text": (
                        "Let me get you to someone who can "
                        "help with your refill."),
                    "target_queue": "pharmacy"}

    audit_log({
        "event_type":  "INTENT_CLASSIFIED",
        "session_id":  session_id,
        "intent":      intent,
        "source":      intent_result["source"],
        "confidence":  float(confidence),
    })

    return {"intent": intent, "slots": slots,
            "confidence": confidence,
            "source": intent_result["source"],
            "handled": False}
```

---

## Step 4: Verify Identity at the Assurance Level the Intent Requires

*The pseudocode calls this `ensure_identity_for_intent(...)`. Different intents need different identity-assurance levels. The system grants the lowest assurance that satisfies the intent and steps up dynamically when the conversation moves to a higher-stakes intent. Caller-ID match plus DOB confirmation buys soft-personal assurance; an OTP step-up via Pinpoint buys PHI-disclosing assurance. Skip the per-intent assurance check and the assistant either over-friction-loads low-stakes interactions or under-protects high-stakes ones.*

```python
def soft_personal_check(session_context, dob_attempt):
    """
    Match the caller-ID against the patient registry and
    confirm the DOB the patient said. The DOB-attempt comes
    from a follow-up turn; the demo just takes it as a
    parameter.

    Returns:
        Dict with success flag and patient_id if matched.
    """
    caller_id = session_context["caller_id"]
    if not caller_id:
        return {"success": False,
                "reason":  "no_caller_id"}

    record = patient_registry.find_by_phone(caller_id)
    if not record:
        return {"success": False,
                "reason":  "caller_id_not_in_registry"}

    if record["dob"] != dob_attempt:
        return {"success": False,
                "reason":  "dob_mismatch"}

    return {"success":    True,
            "patient_id": record["patient_id"],
            "registry_record": record}

def issue_otp(session_context, patient_id):
    """
    Issue an OTP via Pinpoint and persist the salted hash to
    the identity-verification table. Returns the destination
    so the spoken prompt can describe it ("a code to your
    phone ending in 1234").
    """
    session_id = session_context["session_id"]
    record = None
    for entry in patient_registry._by_phone.values():
        if entry["patient_id"] == patient_id:
            record = entry
            break
    if not record:
        return {"issued": False,
                "reason": "patient_not_found"}

    code = _generate_otp()
    salt = secrets.token_hex(16)
    code_hash = _hash_otp(code, salt)
    destination = record["preferred_otp_destination"]

    identity_verification.issue_otp(
        session_id=session_id,
        code_hash=code_hash,
        salt=salt,
        destination=destination,
        ttl_seconds=OTP_TTL_SECONDS)

    # In production this hits Pinpoint's SMS/email APIs; the
    # mock records the delivery for demo visibility.
    pinpoint_mock.send_otp(destination=destination,
                            code=code,
                            channel="SMS")

    # The OTP code is never logged. The demo returns it only so
    # the demo runner can simulate the patient reading it back.
    audit_log({
        "event_type":  "OTP_ISSUED",
        "session_id":  session_id,
        "destination_last_four": destination[-4:],
    })
    return {"issued":      True,
            "destination": destination,
            "_demo_code":  code}  # Real code never returned.

def ensure_identity_for_intent(session_context, intent,
                                  patient_dob_attempt=None,
                                  otp_attempt=None):
    """
    Grant the assurance level the intent requires, stepping up
    when the current level is insufficient. The patient_dob_
    attempt and otp_attempt parameters are how the demo
    simulates the multi-turn data capture; production captures
    them through additional turn handling in Lex slot prompts.

    Returns:
        Dict with satisfied flag, patient_id, current
        assurance level, and the reason if it could not satisfy.
    """
    session_id = session_context["session_id"]
    state = conversation_state.get(session_id)
    current_level   = int(state.get("identity_assurance_level",
                                       ASSURANCE_ANONYMOUS))
    required_level  = INTENT_ASSURANCE_REQUIREMENTS.get(
        intent, ASSURANCE_ANONYMOUS)

    if current_level >= required_level:
        return {"satisfied": True,
                "patient_id": state.get("patient_id"),
                "current_level": current_level}

    # Step 4A: soft-personal step-up via caller-ID + DOB.
    if required_level >= ASSURANCE_SOFT_PERSONAL \
            and current_level < ASSURANCE_SOFT_PERSONAL:
        if not patient_dob_attempt:
            return {"satisfied": False,
                    "reason":    "soft_personal_dob_required",
                    "prompt":    ("To look up your record, can "
                                  "you please tell me your "
                                  "date of birth?")}

        soft = soft_personal_check(
            session_context=session_context,
            dob_attempt=patient_dob_attempt)
        if not soft["success"]:
            audit_log({
                "event_type":   "SOFT_PERSONAL_FAILED",
                "session_id":   session_id,
                "reason":       soft["reason"],
            })
            cloudwatch.put_metric(
                CLOUDWATCH_NAMESPACE, "IdentityVerificationOutcome",
                0, "Count",
                dimensions={"assurance_level":
                              "soft_personal",
                            "channel":
                              session_context["channel_type"]})
            return {"satisfied": False,
                    "reason":    soft["reason"],
                    "disposition": "transfer_for_identity",
                    "target_queue": "general"}

        conversation_state.update(session_id, {
            "identity_assurance_level": ASSURANCE_SOFT_PERSONAL,
            "patient_id":               soft["patient_id"],
        })
        current_level = ASSURANCE_SOFT_PERSONAL

        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "IdentityVerificationOutcome",
            1, "Count",
            dimensions={"assurance_level": "soft_personal",
                        "channel":
                          session_context["channel_type"]})
        audit_log({
            "event_type":   "SOFT_PERSONAL_SUCCESS",
            "session_id":   session_id,
            "patient_id_hash": _hash_value(soft["patient_id"]),
        })

    # Step 4B: PHI-disclosing step-up via OTP.
    if required_level >= ASSURANCE_PHI_DISCLOSING \
            and current_level < ASSURANCE_PHI_DISCLOSING:
        state = conversation_state.get(session_id)
        patient_id = state.get("patient_id")
        if not patient_id:
            return {"satisfied": False,
                    "reason":    "patient_id_missing_for_otp"}

        if otp_attempt is None:
            # First time we hit this branch in the conversation:
            # issue the OTP and ask for it.
            issuance = issue_otp(
                session_context=session_context,
                patient_id=patient_id)
            if not issuance["issued"]:
                return {"satisfied": False,
                        "reason":    issuance["reason"]}
            destination = issuance["destination"]
            return {"satisfied": False,
                    "reason":    "phi_disclosing_otp_required",
                    "_demo_otp_code": issuance["_demo_code"],
                    "prompt":    (f"Im sending a six-digit code "
                                  f"to your phone ending in "
                                  f"{destination[-4:]}. Please "
                                  f"read it back to me when you "
                                  f"receive it.")}

        result = identity_verification.verify_otp(
            session_id=session_id,
            code_attempt=otp_attempt)
        if not result["verified"]:
            audit_log({
                "event_type":   "OTP_VERIFICATION_FAILED",
                "session_id":   session_id,
                "reason":       result["reason"],
            })
            cloudwatch.put_metric(
                CLOUDWATCH_NAMESPACE, "IdentityVerificationOutcome",
                0, "Count",
                dimensions={"assurance_level": "phi_disclosing",
                            "channel":
                              session_context["channel_type"]})
            return {"satisfied": False,
                    "reason":    result["reason"],
                    "disposition": "transfer_for_identity",
                    "target_queue": "general"}

        conversation_state.update(session_id, {
            "identity_assurance_level": ASSURANCE_PHI_DISCLOSING,
        })
        current_level = ASSURANCE_PHI_DISCLOSING
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "IdentityVerificationOutcome",
            1, "Count",
            dimensions={"assurance_level": "phi_disclosing",
                        "channel":
                          session_context["channel_type"]})
        audit_log({
            "event_type":   "OTP_VERIFICATION_SUCCESS",
            "session_id":   session_id,
        })

    state = conversation_state.get(session_id)
    return {"satisfied":     True,
            "patient_id":    state.get("patient_id"),
            "current_level": current_level}
```

---

## Step 5: Fulfill the Intent Through the Appropriate Integration

*The pseudocode calls this `fulfill_intent(...)`. Each intent has its own fulfillment path: appointment lookup against the EHR scheduling API, refill request through the pharmacy workflow with clinical-review queueing, knowledge-base retrieval for facility info, callback ticket creation for things the assistant defers. Skip the explicit per-intent fulfillment routing and the assistant becomes a thin wrapper around the LLM that does not actually do anything.*

```python
def format_appointment_response(appointment, language="en-US"):
    """
    Format a single appointment for spoken response. Production
    has per-language templates and uses Polly's SSML for
    emphasis on the date and time.
    """
    start_dt = datetime.fromisoformat(
        appointment["start"].replace("Z", "+00:00"))
    if language == "es-US":
        return (f"Su cita es el {start_dt.strftime('%d de %B')} "
                f"a las {start_dt.strftime('%I:%M %p')} con "
                f"{appointment['provider']} en "
                f"{appointment['location']}.")
    return (f"Your appointment is on "
            f"{start_dt.strftime('%A, %B %d')} at "
            f"{start_dt.strftime('%I:%M %p')} with "
            f"{appointment['provider']} at "
            f"{appointment['location']}.")

def fulfill_appointment_lookup(session_context, identity_context):
    """
    Look up the patient's upcoming appointments through the
    EHR scheduling API and format the response.
    """
    session_id = session_context["session_id"]
    appointments = ehr.search_appointments(
        identity_context["patient_id"])

    if not appointments:
        return {"success": True,
                "response_text":
                    ("I dont see any upcoming appointments on "
                     "your record. Would you like me to "
                     "transfer you to scheduling?"),
                "transfer_after": True,
                "target_queue":   "scheduling"}

    if len(appointments) == 1:
        return {"success": True,
                "response_text": format_appointment_response(
                    appointments[0],
                    language=session_context["language"]),
                "transfer_after": False,
                "appointment_id": appointments[0]["id"]}

    # Multiple upcoming: list briefly, ask which one.
    summary = "; ".join(
        format_appointment_response(a, language="en-US")
        for a in appointments[:2])
    return {"success": True,
            "response_text": (
                f"You have {len(appointments)} upcoming "
                f"appointments. {summary}. Which one would you "
                f"like more information about?"),
            "transfer_after": False,
            "multiple":       True}

def fulfill_refill_request(session_context, slots,
                             identity_context):
    """
    Submit the refill request through the pharmacy workflow.
    Most institutions queue refills for clinical review rather
    than auto-authorize. The mock just creates a ticket.
    """
    session_id = session_context["session_id"]
    rxnorm = slots.get("medication_rxnorm")
    med_text = slots.get("medication_text", "")
    med_display = slots.get("medication_display", med_text)

    if not rxnorm:
        return {"success": False,
                "response_text": (
                    "Let me get you to someone in pharmacy "
                    "who can help with that refill."),
                "transfer_after": True,
                "target_queue":   "pharmacy"}

    ticket = ehr.create_refill_request(
        patient_id=identity_context["patient_id"],
        medication_rxnorm=rxnorm,
        medication_text=med_text,
        requested_via="voice_assistant",
        session_id=session_id)

    return {"success": True,
            "response_text": (
                f"Ive submitted a refill request for "
                f"{med_display}. Your care team will review it "
                f"and well send the prescription to your "
                f"preferred pharmacy. Is there anything else "
                f"I can help with?"),
            "transfer_after": False,
            "ticket_id":      ticket["ticket_id"]}

def fulfill_facility_info(session_context, utterance):
    """
    Retrieve relevant passages from the institutional knowledge
    base and ground an LLM response. The scope filter on the
    response is the boundary that prevents the LLM from
    drifting into clinical advice when the patient's "facility
    info" question shades into something else.
    """
    retrieval = kb_mock.retrieve(query=utterance, max_results=3)
    passages = retrieval.get("passages", [])

    if not passages:
        return {"success": False,
                "response_text": (
                    "Let me get you to someone who can help "
                    "with that."),
                "transfer_after": True,
                "target_queue":   "general"}

    rag_response = bedrock_mock.generate_rag_response(
        query=utterance,
        retrieved_passages=passages,
        language=session_context["language"])
    try:
        parsed = json.loads(rag_response["body"])
    except (TypeError, ValueError):
        parsed = {"text": "", "in_scope": False,
                   "source_passages": []}

    response_text = parsed.get("text", "")
    in_scope_self_reported = parsed.get("in_scope", False)

    # Scope filter: even when the LLM declares the response
    # in-scope, run the patterns over the response text.
    scope_check = scope_filter_check(response_text)
    if not in_scope_self_reported or scope_check["violation"]:
        # Replace the LLM response with an explicit refusal-and-
        # transfer prompt.
        return {"success": False,
                "response_text": (
                    "Let me get you to someone who can give "
                    "you the right answer."),
                "transfer_after": True,
                "target_queue":   "general",
                "scope_violation": scope_check.get("category")}

    return {"success": True,
            "response_text": response_text,
            "transfer_after": False,
            "source_passage_count": len(parsed.get(
                "source_passages", []))}

def fulfill_callback_request(session_context, slots):
    """
    Create a callback ticket. The patient does not need an
    identity-assurance step-up: the callback simply records
    that someone wants to be called back.
    """
    return {"success": True,
            "response_text": (
                "Ive created a callback request. Someone will "
                "call you back within one business day at the "
                "number you called from."),
            "transfer_after": False,
            "ticket_id": f"cb-{uuid.uuid4().hex[:8]}"}

def scope_filter_check(response_text):
    """
    Run the response text against the configured scope-violation
    patterns. Returns a dict with a violation flag and the
    matched category if any.
    """
    if not response_text:
        return {"violation": False, "category": None}
    text = response_text.lower()
    for category, patterns in SCOPE_VIOLATION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                return {"violation":      True,
                        "category":       category,
                        "matched_pattern": pattern}
    return {"violation": False, "category": None}

def fulfill_intent(session_context, classification,
                     identity_context, utterance):
    """
    Route the classified intent to its fulfillment handler and
    return the response payload.
    """
    session_id = session_context["session_id"]
    intent = classification["intent"]
    slots  = classification["slots"]

    if intent == "confirm_appointment":
        result = fulfill_appointment_lookup(
            session_context, identity_context)
    elif intent == "request_refill":
        result = fulfill_refill_request(
            session_context, slots, identity_context)
    elif intent == "facility_info":
        result = fulfill_facility_info(
            session_context, utterance)
    elif intent == "callback_request":
        result = fulfill_callback_request(session_context, slots)
    else:
        # Defensive default: an intent that reached here
        # without a fulfillment handler is a config bug, not a
        # patient-facing failure. Transfer rather than guess.
        result = {"success": False,
                  "response_text": TRANSFER_TO_AGENT_PHRASE,
                  "transfer_after": True,
                  "target_queue":   "general"}

    state = conversation_state.get(session_id)
    fulfillment_history = list(state.get("fulfillment_history", []))
    fulfillment_history.append({
        "intent":  intent,
        "success": result.get("success", False),
        "transfer_after":
            result.get("transfer_after", False),
        "at":      _now_iso(),
    })
    conversation_state.update(session_id, _to_decimal({
        "fulfillment_history": fulfillment_history,
    }))

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "FulfillmentOutcome",
        1 if result.get("success") else 0, "Count",
        dimensions={"intent":  intent,
                    "channel": session_context["channel_type"],
                    "language": session_context["language"]})

    audit_log({
        "event_type":     "INTENT_FULFILLED",
        "session_id":     session_id,
        "intent":         intent,
        "success":        result.get("success", False),
        "transfer_after": result.get("transfer_after", False),
    })

    return result
```

---

## Step 6: Generate the Response, Render TTS, and Handle Barge-In

*The pseudocode calls this `speak(...)`. The assistant's response text is composed (templated for high-stakes intents, LLM-grounded for informational intents), passed through the scope filter and Bedrock Guardrails, rendered to TTS via Polly with the custom-pronunciation lexicon, and played to the patient. The patient may interrupt mid-prompt; the system handles barge-in gracefully. Skip the scope filter on every generated response and an LLM-driven response can drift into clinical advice that the explicit out-of-scope handlers were supposed to prevent.*

```python
def speak_response(session_context, response_text):
    """
    Apply the scope filter as a defense-in-depth check, then
    synthesize the response through Polly and emit it through
    the channel sink. Production attaches barge-in detection so
    the patient can interrupt mid-prompt.
    """
    session_id = session_context["session_id"]
    language   = session_context["language"]

    # Step 6A: scope filter on the response. Even when the
    # upstream intent classification was correct, the response
    # generation step has its own filter as a defense-in-depth
    # layer.
    scope_check = scope_filter_check(response_text)
    final_text  = response_text
    scope_violation_caught = False

    if scope_check["violation"]:
        scope_violation_caught = True
        final_text = (
            "Let me get you to someone who can help with that.")
        state = conversation_state.get(session_id)
        violations = list(state.get("scope_violation_events", []))
        violations.append({
            "category":         scope_check["category"],
            "matched_pattern":  scope_check["matched_pattern"],
            "at":               _now_iso(),
        })
        conversation_state.update(session_id, _to_decimal({
            "scope_violation_events": violations,
        }))
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "ScopeViolationsCaught", 1, "Count",
            dimensions={"category":
                          scope_check["category"],
                        "channel":
                          session_context["channel_type"],
                        "language": language})
        audit_log({
            "event_type":      "SCOPE_VIOLATION_CAUGHT",
            "session_id":      session_id,
            "category":        scope_check["category"],
            "matched_pattern": scope_check["matched_pattern"],
        })

    # Step 6B: render to TTS with custom-pronunciation lexicon.
    voice_id = POLLY_VOICE_BY_LANGUAGE.get(language, "Joanna")
    polly_mock.synthesize_speech(
        text=final_text,
        voice_id=voice_id,
        language_code=language,
        lexicon_names=POLLY_LEXICON_NAMES)

    # Step 6C: append to turn history.
    state = conversation_state.get(session_id)
    turn_history = list(state.get("turn_history", []))
    turn_history.append({
        "speaker":   "assistant",
        "text_hash": _hash_value(final_text),
        "at":        _now_iso(),
    })
    conversation_state.update(session_id, _to_decimal({
        "turn_history": turn_history,
    }))

    audit_log({
        "event_type":      "RESPONSE_SPOKEN",
        "session_id":      session_id,
        "scope_violation_caught": scope_violation_caught,
    })

    return {"text_spoken": final_text,
            "scope_violation_caught": scope_violation_caught}
```

---

## Step 7: Escalate to a Human with a Warm-Handoff Packet

*The pseudocode calls this `warm_transfer(...)`. When the assistant cannot or should not continue, the call transfers to a human agent (or to crisis triage) with a context packet that includes the conversation summary, the transcript reference, the identity-verification status, the detected intent and slots so far, and any crisis flags. The agent receives the packet on screen before they answer. Skip the warm-handoff packet and patient experience drops sharply at the moment the assistant hands off, which is the wrong place to drop experience.*

```python
def summarize_conversation_for_agent(state):
    """
    Build a short human-readable summary the agent reads on
    their screen pop. The summary references intents and
    fulfillment outcomes, never raw transcript content (the
    transcript reference is in the packet for agents who need
    to dig deeper).
    """
    intents = [i["intent"]
               for i in state.get("intent_history", [])]
    fulfillment = state.get("fulfillment_history", [])
    successful = sum(1 for f in fulfillment if f.get("success"))
    return (
        f"Caller spoke with the assistant for "
        f"{len(state.get('turn_history', []))} turns. "
        f"Detected intents: {', '.join(intents) or 'none'}. "
        f"Successful fulfillments: {successful}. "
        f"Identity assurance: "
        f"{state.get('identity_assurance_level', 0)}.")

def build_warm_handoff_packet(session_context, target_queue,
                                handoff_reason):
    """
    Assemble the screen-pop packet for the receiving agent.
    Includes everything the agent needs to continue the
    conversation without making the patient repeat themselves.
    """
    session_id = session_context["session_id"]
    state = conversation_state.get(session_id)
    return {
        "session_id":         session_id,
        "channel":            state.get("channel_type"),
        "caller_id":          state.get("caller_id_hint"),
        "language":           state.get("language"),
        "identity_assurance_level":
            state.get("identity_assurance_level"),
        "patient_id":         state.get("patient_id"),
        "caregiver_context":
            state.get("caregiver_context"),
        "conversation_summary":
            summarize_conversation_for_agent(state),
        "intent_history":     state.get("intent_history", []),
        "fulfillment_history":
            state.get("fulfillment_history", []),
        "crisis_detected":
            state.get("crisis_detected", False),
        "crisis_severity":
            state.get("crisis_severity"),
        "crisis_category":
            state.get("crisis_category"),
        "scope_violations_caught":
            len(state.get("scope_violation_events", [])),
        "target_queue":       target_queue,
        "handoff_reason":     handoff_reason,
        "transcript_archive_ref":
            state.get("transcript_archive_ref"),
    }

def warm_transfer(session_context, target_queue, handoff_reason):
    """
    Trigger the warm transfer through Connect with the screen-
    pop packet attached. Updates conversation state and emits
    the lifecycle event.
    """
    session_id = session_context["session_id"]

    packet = build_warm_handoff_packet(
        session_context=session_context,
        target_queue=target_queue,
        handoff_reason=handoff_reason)

    state = conversation_state.get(session_id)
    contact_id = state.get("connect_contact_id")
    if contact_id:
        connect_mock.warm_transfer(
            contact_id=contact_id,
            target_queue=target_queue,
            screen_pop_packet=packet)

    escalation_history = list(state.get("escalation_history", []))
    escalation_history.append({
        "reason":  handoff_reason,
        "queue":   target_queue,
        "at":      _now_iso(),
    })
    conversation_state.update(session_id, {
        "escalation_history": escalation_history,
        "status":             "escalated",
    })

    event_bus.put_events([{
        "Source":       "patient_assistant",
        "DetailType":   "conversation_escalated",
        "EventBusName": CONVERSATION_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":      session_id,
            "target_queue":    target_queue,
            "handoff_reason":  handoff_reason,
            "channel":         session_context["channel_type"],
        }),
    }])

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ConversationEscalated", 1, "Count",
        dimensions={"reason":  handoff_reason,
                    "channel": session_context["channel_type"],
                    "language": session_context["language"]})

    audit_log({
        "event_type":     "WARM_TRANSFER_COMPLETE",
        "session_id":     session_id,
        "target_queue":   target_queue,
        "handoff_reason": handoff_reason,
    })

    return {"transferred": True,
            "target_queue": target_queue,
            "packet":       packet}
```

---

## Step 8: Audit, Archive, and Feed Cohort-Stratified Accuracy Monitoring

*The pseudocode calls this `audit_archive_and_telemetry(...)`. Every conversation produces a durable audit record: the audio reference, the transcript reference, the intent and slots, the identity-verification trail, the fulfillment outcome, the escalation events, the scope-violation events, the crisis flags. Cohort-stratified metrics (per-language, per-channel, per-cohort axis) feed the equity-monitoring dashboard. Skip the cohort segmentation and the assistant's per-cohort failure modes are invisible until a complaint or a regulator surfaces them.*

```python
def close_conversation_and_audit(session_context):
    """
    Close the conversation, write the durable audit record,
    emit the completion lifecycle event, and emit per-cohort
    operational metrics.
    """
    session_id = session_context["session_id"]
    state = conversation_state.get(session_id)
    ended_at = _now_iso()

    # Determine final disposition for the audit record.
    if state.get("crisis_detected"):
        final_disposition = "crisis_routed"
    elif state.get("status") == "escalated":
        final_disposition = "escalated"
    elif state.get("fulfillment_history"):
        last = state["fulfillment_history"][-1]
        if last.get("success") and not last.get("transfer_after"):
            final_disposition = "contained"
        else:
            final_disposition = "escalated"
    else:
        final_disposition = "abandoned"

    started_at_str = state.get("started_at")
    try:
        duration = (
            datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            - datetime.fromisoformat(
                started_at_str.replace("Z", "+00:00"))
        ).total_seconds()
    except (TypeError, ValueError):
        duration = 0.0

    # Step 8A: write the durable audit record. References (not
    # contents) for the audio and verbatim transcript;
    # structural metadata captured for forensic and analytics
    # queries.
    audit_record = _to_decimal({
        "session_id":     session_id,
        "channel":        state.get("channel_type"),
        "started_at":     started_at_str,
        "ended_at":       ended_at,
        "language":       state.get("language"),
        "consent_regime": state.get("consent_regime"),
        "identity_assurance_level":
            state.get("identity_assurance_level"),
        "patient_id_hash":
            _hash_value(state.get("patient_id")),
        "caregiver_relationship_type":
            (state.get("caregiver_context") or {}).get(
                "relationship_type"),
        "intents_observed": state.get("intent_history", []),
        "fulfillment_outcomes":
            state.get("fulfillment_history", []),
        "escalation_events":
            state.get("escalation_history", []),
        "crisis_detected":
            state.get("crisis_detected", False),
        "crisis_severity":
            state.get("crisis_severity"),
        "crisis_category":
            state.get("crisis_category"),
        "scope_violations_caught":
            len(state.get("scope_violation_events", [])),
        "scope_violation_events":
            state.get("scope_violation_events", []),
        "turn_count":     len(state.get("turn_history", [])),
        "duration_seconds": Decimal(str(duration)),
        "final_disposition": final_disposition,
        "lex_bot_version": LEX_BOT_VERSION,
        "intent_fallback_prompt_version":
            INTENT_FALLBACK_PROMPT_VERSION,
        "response_generation_prompt_version":
            RESPONSE_GENERATION_PROMPT_VERSION,
        "crisis_detection_rules_version":
            CRISIS_DETECTION_RULES_VERSION,
        "scope_filter_rules_version":
            SCOPE_FILTER_RULES_VERSION,
        "identity_policy_version":
            IDENTITY_POLICY_VERSION,
        # Cohort axes for equity monitoring. The age_band is
        # opt-in self-disclosed; never inferred for protected
        # classes.
        "cohort_axes": {
            "channel":      state.get("channel_type"),
            "language":     state.get("language"),
            "region_hint":  state.get("region_hint"),
            "age_band":
                _resolve_opt_in_age_band(state.get("patient_id")),
        },
    })

    audit_object = s3_store.put_object(
        bucket=AUDIT_ARCHIVE_BUCKET,
        key=f"audit/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
            f"/{session_id}.json",
        body=json.dumps(audit_record, default=str).encode("utf-8"),
        metadata={"session_id":  session_id,
                  "disposition": final_disposition})

    conversation_state.update(session_id, {
        "status":   "closed",
        "ended_at": ended_at,
    })
    conversation_meta.update(session_id, {
        "ended_at":          ended_at,
        "final_disposition": final_disposition,
        "audit_archive_ref": audit_object["uri"],
    })

    # Step 8B: emit the completion lifecycle event.
    event_bus.put_events([{
        "Source":       "patient_assistant",
        "DetailType":   "conversation_completed",
        "EventBusName": CONVERSATION_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "session_id":        session_id,
            "channel":           state.get("channel_type"),
            "language":          state.get("language"),
            "disposition":       final_disposition,
            "duration_seconds":  duration,
            "turn_count":        len(state.get("turn_history", [])),
        }),
    }])

    # Step 8C: per-cohort operational metrics. Each metric
    # carries the cohort dimensions so the equity-monitoring
    # dashboard can stratify.
    cohort_dims = {
        "channel":  state.get("channel_type"),
        "language": state.get("language"),
        "region_hint": state.get("region_hint"),
    }
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ConversationDuration",
        duration, "Seconds",
        dimensions={**cohort_dims,
                    "disposition": final_disposition})
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ContainmentRate",
        1 if final_disposition == "contained" else 0,
        "Count",
        dimensions={**cohort_dims,
                    "primary_intent":
                      _primary_intent(state)})

    audit_log({
        "event_type":      "CONVERSATION_AUDITED",
        "session_id":      session_id,
        "audit_archive_ref": audit_object["uri"],
        "final_disposition": final_disposition,
        "duration_seconds": duration,
    })

    return audit_record

def _primary_intent(state):
    """
    Extract the primary (first non-fallback) intent from the
    conversation history, for per-intent operational metrics.
    """
    for intent_event in state.get("intent_history", []):
        intent = intent_event.get("intent")
        if intent and intent != "FallbackIntent":
            return intent
    return "none"

def _resolve_opt_in_age_band(patient_id):
    """
    Resolve the opt-in self-disclosed age band from the patient
    registry. Returns "not_disclosed" when the patient has not
    opted in. Inferred demographic labels for protected classes
    are explicitly not used.
    """
    if not patient_id:
        return "not_disclosed"
    for record in patient_registry._by_phone.values():
        if record["patient_id"] == patient_id:
            return record.get("opt_in_age_band", "not_disclosed")
    return "not_disclosed"
```

---

## Putting It All Together

The pipeline ties together as a top-level handler that simulates a single multi-turn conversation flowing end-to-end through the eight stages. In a Lambda-and-Step-Functions deployment, each stage is a separate Lambda invoked from the Step Functions state machine; the demo orchestrates them inline so you can see the full sequence.

```python
def handle_turn(session_context, utterance,
                  asr_avg_confidence=Decimal("0.92"),
                  patient_dob_attempt=None,
                  otp_attempt=None):
    """
    Process a single conversation turn end-to-end.

    Returns:
        Dict with the response text, escalation status, and
        whether the conversation should continue.
    """
    session_id = session_context["session_id"]

    # Stage 2: parallel crisis detection.
    utterance_result = on_utterance_received(
        session_context=session_context,
        utterance=utterance,
        asr_avg_confidence=asr_avg_confidence)

    if utterance_result["crisis_handled"]:
        return {"continue": False,
                "disposition": "crisis_routed",
                "outcome": utterance_result["outcome"]}

    # Stage 3: intent classification + slot extraction.
    classification = classify_and_extract(
        session_context=session_context,
        utterance=utterance)

    if classification.get("handled"):
        # Out-of-scope refusal or transfer-to-agent intent.
        speak_response(
            session_context=session_context,
            response_text=classification["response_text"])
        warm_transfer(
            session_context=session_context,
            target_queue=classification["target_queue"],
            handoff_reason=f"intent:{classification['intent']}")
        return {"continue": False,
                "disposition": classification["disposition"]}

    # Stage 4: identity verification at the required level.
    identity = ensure_identity_for_intent(
        session_context=session_context,
        intent=classification["intent"],
        patient_dob_attempt=patient_dob_attempt,
        otp_attempt=otp_attempt)

    if not identity["satisfied"]:
        # Either ask for the missing factor (DOB or OTP) or
        # transfer if verification failed.
        if identity.get("disposition") == "transfer_for_identity":
            speak_response(
                session_context=session_context,
                response_text=(
                    "I couldnt verify that. Let me transfer "
                    "you to someone who can help."))
            warm_transfer(
                session_context=session_context,
                target_queue=identity.get("target_queue", "general"),
                handoff_reason=f"identity:{identity['reason']}")
            return {"continue": False,
                    "disposition": "transfer_for_identity"}
        # Step-up still pending; speak the prompt and wait for
        # the next turn (which will carry DOB or OTP).
        speak_response(
            session_context=session_context,
            response_text=identity["prompt"])
        return {"continue":     True,
                "disposition":  "awaiting_identity",
                "step_up_reason": identity["reason"],
                "_demo_otp_code":
                    identity.get("_demo_otp_code")}

    # Stage 5: fulfillment.
    fulfillment = fulfill_intent(
        session_context=session_context,
        classification=classification,
        identity_context=identity,
        utterance=utterance)

    # Stage 6: speak the response (with scope filter).
    speak_result = speak_response(
        session_context=session_context,
        response_text=fulfillment["response_text"])

    # Stage 7: warm transfer if fulfillment requested it.
    if fulfillment.get("transfer_after"):
        warm_transfer(
            session_context=session_context,
            target_queue=fulfillment.get("target_queue", "general"),
            handoff_reason=f"fulfillment:{classification['intent']}")
        return {"continue": False,
                "disposition": "escalated_after_fulfillment"}

    return {"continue": True,
            "disposition": "fulfilled",
            "response_text": speak_result["text_spoken"]}

def run_demo():
    """
    Run a small set of end-to-end scenarios that exercise the
    main paths through the patient-facing voice assistant
    pipeline:
      1. Walter (older patient) calls to confirm a cardiology
         appointment. The soft-personal identity check
         succeeds; the appointment is confirmed.
      2. Marisol (Spanish-speaking patient) calls to refill
         lisinopril. Identity steps up through OTP; the
         pharmacy ticket is created.
      3. A patient calls about an appointment but mentions
         chest pain mid-conversation. The crisis detector
         preempts the appointment flow and routes to nurse
         triage.
      4. A patient asks the assistant a clinical question. The
         scope filter catches it and the assistant transfers
         after an explicit refusal.
      5. A patient asks for facility hours. The RAG response
         is grounded and within scope; the assistant answers
         and ends the call.
    """
    global lex_mock, bedrock_mock, kb_mock, comprehend_mock

    # --- Lex fixture map: utterance substring -> intent + slots
    lex_fixtures = {
        "confirm my next cardiology appointment": {
            "intent":     "confirm_appointment",
            "confidence": 0.94,
            "slots":      {},
        },
        "next appointment":   {"intent": "confirm_appointment",
                                "confidence": 0.92, "slots": {}},
        "i need to refill":   {"intent": "request_refill",
                                "confidence": 0.93, "slots": {}},
        "necesito un refill": {"intent": "request_refill",
                                "confidence": 0.91, "slots": {}},
        "what time does":     {"intent": "facility_info",
                                "confidence": 0.90, "slots": {}},
        "what are your":      {"intent": "facility_info",
                                "confidence": 0.91, "slots": {}},
        "is my appointment":  {"intent": "confirm_appointment",
                                "confidence": 0.93, "slots": {}},
        "october fourteenth": {"intent": "confirm_appointment",
                                "confidence": 0.85, "slots": {}},
        "march twenty second": {"intent": "request_refill",
                                "confidence": 0.85, "slots": {}},
        "blood pressure has been kind of high": {
            "intent": "out_of_scope_clinical",
            "confidence": 0.88, "slots": {}},
        "should i take more": {"intent": "out_of_scope_clinical",
                                "confidence": 0.91, "slots": {}},
    }
    lex_mock = MockLex(lex_fixtures)

    # --- Bedrock fixture maps
    bedrock_intent_responses = {
        "should i go to the hospital": {
            "intent":     "out_of_scope_clinical",
            "confidence": 0.92,
        },
    }
    bedrock_rag_responses = {
        "what time does the lab open": {
            "text": ("Our main lab opens at 7 AM Monday through "
                     "Friday and at 8 AM on Saturdays. Its "
                     "closed on Sundays."),
            "in_scope": True,
            "source_passages": ["lab_hours_v3"],
        },
        "what are your hours": {
            "text": ("Our main clinic is open 8 AM to 6 PM "
                     "Monday through Friday, and 9 AM to 1 PM "
                     "on Saturdays."),
            "in_scope": True,
            "source_passages": ["clinic_hours_v2"],
        },
    }
    bedrock_mock = MockBedrock(bedrock_intent_responses,
                                 bedrock_rag_responses)

    # --- Knowledge Base snippet fixtures
    kb_fixtures = {
        "lab": [
            {"passage": "Lab hours: M-F 7am-6pm, Sat 8am-1pm",
             "source": "facility-info/lab-hours-v3.md"},
        ],
        "hours": [
            {"passage": "Clinic hours: M-F 8am-6pm, Sat 9am-1pm",
             "source": "facility-info/clinic-hours-v2.md"},
        ],
    }
    kb_mock = MockBedrockKB(kb_fixtures)

    # --- Comprehend Medical fixtures
    cm_fixtures = {
        "lisinopril": {
            "Entities": [{
                "Text":  "lisinopril",
                "Score": 0.96,
                "BeginOffset": 19,
                "EndOffset":   29,
                "RxNormConcepts": [{
                    "Code":        "29046",
                    "Description": "Lisinopril 10 MG Oral Tablet",
                    "Score":       0.94,
                }],
            }]
        },
    }
    comprehend_mock = MockComprehendMedical(cm_fixtures)

    # ---------- Scenario 1: Walter confirms appointment ----------
    print("\n" + "#" * 60)
    print("# SCENARIO 1: appointment confirmation (Walter)")
    print("#" * 60)
    session_ctx = open_conversation(
        channel_type="telephony",
        caller_id="+15555550143",
        channel_metadata={"connect_contact_id": "ctc-walter-1",
                           "region_hint": "us-northeast"},
        institution_state="CA")
    print(f"  session_id: {session_ctx['session_id']}")
    print(f"  consent_regime: {session_ctx['consent_regime']}")

    print("\n  Patient: 'I want to confirm my next cardiology "
          "appointment.'")
    turn_one = handle_turn(
        session_ctx,
        "I want to confirm my next cardiology appointment.",
        asr_avg_confidence=Decimal("0.93"))
    print(f"  Disposition: {turn_one['disposition']}")
    if turn_one.get("step_up_reason"):
        print(f"  Step-up: {turn_one['step_up_reason']}")

    print("\n  Patient: 'October fourteenth, nineteen forty-three.'")
    turn_two = handle_turn(
        session_ctx,
        "October fourteenth, nineteen forty-three.",
        asr_avg_confidence=Decimal("0.91"),
        patient_dob_attempt="1943-10-14")
    print(f"  Disposition: {turn_two['disposition']}")
    if turn_two.get("response_text"):
        print(f"  Response: {turn_two['response_text']}")

    close_conversation_and_audit(session_ctx)

    # ---------- Scenario 2: Marisol refill with OTP step-up ----
    print("\n" + "#" * 60)
    print("# SCENARIO 2: refill request with OTP (Marisol)")
    print("#" * 60)
    session_ctx = open_conversation(
        channel_type="telephony",
        caller_id="+15555550199",
        channel_metadata={"connect_contact_id": "ctc-marisol-1",
                           "region_hint": "us-southwest"},
        institution_state="TX")

    print(f"  session_id: {session_ctx['session_id']}")
    print(f"  language: {session_ctx['language']}")

    print("\n  Patient: 'I need to refill my lisinopril.'")
    turn_one = handle_turn(
        session_ctx,
        "I need to refill my lisinopril, the ten milligram one.",
        asr_avg_confidence=Decimal("0.92"))
    print(f"  Disposition: {turn_one['disposition']}")
    if turn_one.get("step_up_reason"):
        print(f"  Step-up: {turn_one['step_up_reason']}")

    print("\n  Patient: 'March twenty-second, nineteen "
          "sixty-eight.'")
    turn_two = handle_turn(
        session_ctx,
        "March twenty-second, nineteen sixty-eight.",
        asr_avg_confidence=Decimal("0.90"),
        patient_dob_attempt="1968-03-22")
    print(f"  Disposition: {turn_two['disposition']}")
    if turn_two.get("step_up_reason"):
        print(f"  Step-up: {turn_two['step_up_reason']}")
    demo_otp = turn_two.get("_demo_otp_code")

    print(f"\n  Patient: '{demo_otp}.'  (OTP read back)")
    turn_three = handle_turn(
        session_ctx,
        "I need to refill my lisinopril.",
        asr_avg_confidence=Decimal("0.93"),
        otp_attempt=demo_otp)
    print(f"  Disposition: {turn_three['disposition']}")
    if turn_three.get("response_text"):
        print(f"  Response: {turn_three['response_text']}")

    close_conversation_and_audit(session_ctx)

    # ---------- Scenario 3: crisis preempts appointment flow ---
    print("\n" + "#" * 60)
    print("# SCENARIO 3: crisis (chest pain mid-conversation)")
    print("#" * 60)
    session_ctx = open_conversation(
        channel_type="telephony",
        caller_id="+15555550143",
        channel_metadata={"connect_contact_id": "ctc-walter-2",
                           "region_hint": "us-northeast"},
        institution_state="CA")

    print("\n  Patient: 'Is my appointment on the seventeenth?'")
    turn_one = handle_turn(
        session_ctx,
        "Is my appointment on the seventeenth?",
        asr_avg_confidence=Decimal("0.92"))
    print(f"  Disposition: {turn_one['disposition']}")

    print("\n  Patient: 'Actually, Im having some chest pain "
          "right now and Im not sure what to do.'")
    turn_two = handle_turn(
        session_ctx,
        "Actually, I'm having some chest pain right now.",
        asr_avg_confidence=Decimal("0.90"))
    print(f"  Disposition: {turn_two['disposition']}")
    if turn_two.get("outcome"):
        print(f"  Crisis target queue: "
              f"{turn_two['outcome']['target_queue']}")

    close_conversation_and_audit(session_ctx)

    # ---------- Scenario 4: clinical out-of-scope refusal -----
    print("\n" + "#" * 60)
    print("# SCENARIO 4: clinical out-of-scope refusal")
    print("#" * 60)
    session_ctx = open_conversation(
        channel_type="telephony",
        caller_id="+15555550111",
        channel_metadata={"connect_contact_id": "ctc-clin-1",
                           "region_hint": "us-northeast"},
        institution_state="TX")

    print("\n  Patient: 'My blood pressure has been kind of "
          "high lately, what do you think?'")
    turn_one = handle_turn(
        session_ctx,
        "My blood pressure has been kind of high lately, "
        "what do you think?",
        asr_avg_confidence=Decimal("0.91"))
    print(f"  Disposition: {turn_one['disposition']}")

    close_conversation_and_audit(session_ctx)

    # ---------- Scenario 5: facility info via RAG -------------
    print("\n" + "#" * 60)
    print("# SCENARIO 5: facility info via RAG")
    print("#" * 60)
    session_ctx = open_conversation(
        channel_type="app",
        caller_id="+15555550111",
        channel_metadata={"region_hint": "us-northeast"},
        institution_state="TX")

    print("\n  Patient: 'What time does the lab open on "
          "Saturday?'")
    turn_one = handle_turn(
        session_ctx,
        "What time does the lab open on Saturday?",
        asr_avg_confidence=Decimal("0.93"))
    print(f"  Disposition: {turn_one['disposition']}")
    if turn_one.get("response_text"):
        print(f"  Response: {turn_one['response_text']}")

    close_conversation_and_audit(session_ctx)

    # --- Summary ---
    print("\n" + "=" * 60)
    print("DEMO SUMMARY")
    print("=" * 60)
    print(f"Audit objects written:       "
          f"{len(s3_store.list(AUDIT_ARCHIVE_BUCKET))}")
    print(f"Cross-system events emitted: "
          f"{len(event_bus.events)}")
    print(f"CloudWatch metrics emitted:  "
          f"{len(cloudwatch.metrics)}")
    print(f"Polly synthesis calls:       "
          f"{len(polly_mock.synthesized)}")
    print(f"Pinpoint OTPs delivered:     "
          f"{len(pinpoint_mock.delivered_otps)}")
    print(f"Connect warm transfers:      "
          f"{len(connect_mock.transfers)}")
    print(f"Refill tickets created:      "
          f"{len(ehr._refill_tickets)}")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    run_demo()
```

> **A note on the demo's mocks.** Real Lex, Bedrock, Bedrock Knowledge Bases, Comprehend Medical, Polly, Pinpoint, and Connect calls receive the actual utterance audio (or text) and return real model outputs. The demo's mocks use fixture lookups so the same scenario always produces the same output, which makes the rest of the pipeline deterministic for teaching purposes. The fixtures are keyed by utterance substring (for Lex, Bedrock, and Comprehend Medical) and by query substring (for the Knowledge Base). This is enough to demonstrate the recording-consent discipline, the parallel crisis-detection discipline, the layered identity-verification flow, the scope-filter defense-in-depth, the warm-handoff packet, and the cohort-stratified audit pipeline, without needing a live Lex bot, a live Bedrock invocation, or a live Connect contact flow to run the file.

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right audit records, but the distance between it and a real patient-facing voice assistant running in production is significant. Here is where that distance lives.

**Real Amazon Connect contact flow plus per-stage Lambdas plus Step Functions.** The demo orchestrates stages in Python. Production fronts the inbound call through a Connect contact flow that plays the recording-consent disclosure, captures consent acknowledgment, attaches the Lex bot through a `Get customer input` block configured for a Lex V2 bot, and routes to the fulfillment Lambdas through Lambda invocation blocks. The post-Lex pipeline is orchestrated through AWS Step Functions for the multi-stage workflows (refill request with OTP step-up, identity-verification followed by appointment lookup): Step Functions handles durable retry semantics, parallel branches for crisis detection and intent classification, and timeout handling. Each Lambda has its own IAM role, error handling, retries, and DLQs.

**Real Lex V2 bot with intents, slots, and example utterances.** The demo's MockLex uses fixture lookups. Production has a Lex V2 bot defined per language locale (en-US, es-US at minimum) with each intent declared (`confirm_appointment`, `request_refill`, `facility_info`, `callback_request`, `transfer_to_agent`, the out-of-scope handlers, and a fallback intent that routes to the LLM-driven classifier). Each intent has slot definitions with example utterances, slot-elicitation prompts, confirmation prompts, and Lambda fulfillment hooks. The bot is versioned through Lex bot aliases (`Production`, `Staging`, `Development`); deploys go through alias rotation rather than direct edits to the production bot.

**Real Bedrock invocation with a versioned prompt and inference profile.** The demo's MockBedrock returns fixture outputs. Production calls `bedrock_runtime.invoke_model` (for the intent fallback) and `bedrock_agent_runtime.retrieve_and_generate` (for RAG-grounded informational responses) with `modelId` pinned to the inference profile ARN (the inference profile is what you pass for cross-region inference and per-profile rate limits) and a versioned prompt that includes the system instruction, the available-intents schema, the conversation context, the language preference, and a strict-JSON output schema. The intent-fallback prompt is small and uses Claude 3 Haiku for cost; the response-generation prompt is larger and uses Claude 3.5 Sonnet for quality. Both prompts are versioned and deployed alongside the rest of the pipeline; prompt changes go through clinical-operations review (the prompts are load-bearing safety artifacts, not config strings).

**Real Bedrock Knowledge Bases with the institutional FAQ, parking, and what-to-expect content.** The demo's MockBedrockKB returns fixture passages. Production ingests the institutional content (facility-info documents, hours, parking, what-to-expect content, holiday schedules) into a Bedrock Knowledge Base with automatic chunking and embedding. Retrieval at query time goes through `bedrock_agent_runtime.retrieve_and_generate` with the knowledge-base ID and the configured retrieval and generation parameters. The institutional content has a curation lifecycle owned by patient experience: who owns each piece, what the review cadence is, how time-sensitive content is flagged for auto-deferral to humans (today's hours, current wait times), and how staleness is detected.

**Real Bedrock Guardrails configuration as defense-in-depth.** The demo's `scope_filter_check` is a regex pattern set. Production additionally configures a Bedrock Guardrails policy with denied topics (clinical advice, financial advice, legal advice), word-and-phrase filters, sensitive-information filters for PHI redaction, and contextual grounding checks. The Guardrails policy runs on every Bedrock invocation through `bedrock_runtime.invoke_model` with the `guardrailIdentifier` and `guardrailVersion` parameters; the response is intercepted before it reaches the response-generation step. Guardrails is the defense-in-depth layer; the runtime scope filter remains active as a second line of defense.

**Real Comprehend Medical wiring.** The demo's MockComprehendMedical uses fixture lookups. Production calls `comprehend_medical.infer_rx_norm(Text=utterance)` for the medication coding and `comprehend_medical.detect_entities_v2(Text=utterance)` for the broader entity extraction. The responses are merged and the slot-extraction step takes the highest-confidence medication entity. Comprehend Medical occasionally misidentifies entities or extracts dosages incorrectly; the institutional review-and-confirm pattern (the assistant reads back the medication name and dosage before submitting the refill ticket) is what makes this safe.

**Real Polly synthesis with custom-pronunciation lexicons.** The demo's MockPolly records what would have been synthesized. Production calls `polly_client.synthesize_speech` with `Engine="neural"`, the voice ID per language, the SSML-marked text where prosody is needed, and the `LexiconNames` parameter listing the institutional, medication, and provider pronunciation lexicons. The lexicons are managed through `polly_client.put_lexicon` and reviewed periodically by the patient-experience team for new clinical and institutional terms.

**Real Pinpoint OTP delivery with per-region SMS infrastructure.** The demo's MockPinpoint records the OTP and destination. Production calls `pinpoint_client.send_otp_message` (the dedicated OTP API with built-in rate limiting and delivery analytics) or `pinpoint_client.send_messages` for SMS delivery. The Pinpoint application is configured for the regions the institution operates in, with appropriate SMS delivery channel configuration and 10DLC registration where applicable. OTP delivery analytics (delivery success rate, delivery latency, opt-out rate) feed the operations dashboard.

**Real API Gateway WebSocket plus Cognito authorizer for the app channel.** The demo handles only the telephony channel. Production fronts the app channel with API Gateway WebSocket API (audio frames flow over the WebSocket; intent results flow back) plus a REST API for session lifecycle. The Cognito authorizer validates the patient portal session token; the patient is identified by their portal-authenticated identity. The same Lex bot handles both telephony and app channels; the audio source and identity-context source differ at the edges.

**Per-Lambda IAM roles.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda (channel-entry, crisis-detector, intent-fallback, identity-verifier, OTP-issuer, appointment-lookup, refill-request, facility-info, callback-creator, warm-transfer, audit-writer), each scoped to the specific resource ARNs the Lambda touches. The crisis-detector Lambda has the smallest possible permission scope (no PHI store reads at all). The OTP-issuer Lambda has Pinpoint send rights and identity-verification table write only. The appointment-lookup Lambda has Secrets Manager read for the EHR credentials and FHIR API egress only. Wildcard actions and resources will fail any serious IAM review.

**Real DynamoDB wiring with KMS, PITR, and Streams.** The mocks in the demo are dictionaries; production is DynamoDB tables (conversation-state with TTL on idle sessions, identity-verification with TTL on issued OTPs, conversation-metadata partitioned by session_id with a GSI on caller_id_hint for forensic queries) with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery enabled, and DynamoDB Streams emitting change events to the audit and analytics consumers. The audit table has Streams feeding a Kinesis Firehose delivery stream that writes to S3 with Object Lock in compliance mode for HIPAA-grade durability.

**Customer-managed KMS keys, per data class.** Every PHI-bearing resource (audio bucket, audit-archive bucket, conversation-state table, identity-verification table, conversation-metadata table, Lambda environment variables, CloudWatch Logs, Secrets Manager) uses customer-managed KMS keys with rotation enabled. Different keys per data class for blast-radius containment: a compromised audio-bucket key does not compromise the audit archive. CloudTrail logs every key-usage event. The institutional KMS-key-management runbook specifies rotation cadence, access review cadence, and the cross-account key-grant pattern.

**S3 lifecycle and Object Lock.** The audio bucket has a brief-retention lifecycle (delete after seven to thirty days, per the privacy-officer-reviewed retention policy) with the option of opt-in longer retention with explicit consent. The audit archive uses Object Lock in compliance mode for HIPAA-grade durability with retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, and the institution's policy. Lifecycle transitions move older audit-archive objects to Glacier Deep Archive for cost optimization.

**VPC and VPC endpoints.** Lambdas that call back-office APIs (EHR, pharmacy, billing) run in a VPC with private subnets that route traffic through a controlled egress path (PrivateLink to a cloud-hosted EHR, or a VPN/Direct Connect to an on-premises EHR system). VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, EventBridge, CloudWatch Logs, Bedrock, Comprehend Medical, Lex, and Polly keep AWS-internal traffic on the AWS backbone rather than traversing NAT and the public internet. Endpoint policies pin access to the specific resources the pipeline uses. The patient-facing edges (Connect for telephony, API Gateway for the app) are public by design; the back-office traffic is private.

**Real recording-consent jurisdiction logic.** The demo's `determine_consent_regime` uses a tiny area-code-to-state map. Production maintains a comprehensive area-code-to-state mapping (with regular updates as new area codes are introduced), uses a third-party number-lookup service for VOIP-routed calls where area codes are not reliable indicators, and applies the cross-jurisdiction rule (stricter regime wins) consistently. The all-party-consent state list is reviewed by the legal team on a documented cadence. The Reporters Committee for Freedom of the Press maintains a state-by-state guide that production teams should consult when updating the list.

**Real crisis-detection program with named clinical ownership.** The demo's `CRISIS_KEYWORDS` is a small illustrative list. Production builds the crisis-detection vocabulary as a version-controlled clinical-safety document owned by the clinical-quality officer. Per-language vocabulary lists (with native-speaker clinical input on each language). Severity tiers explicitly defined. Escalation pathways per tier (911, 988, protective-services pathway, nurse triage urgent, nurse triage general). Periodic review cadence (quarterly). A documented change-management process. Aggregate detection rates and false-negative reviews tracked monthly. False-negative cases treated as clinical-quality incidents subject to root-cause analysis. The detector is layered: keyword list (highest recall, audited), small dedicated classifier for paraphrase variation, LLM-driven detector for the subtle cases. The LLM detector is the most expensive and is run in parallel with the others rather than only when the keyword list fails to match.

**Real scope-containment program with continuous review.** The demo's `SCOPE_VIOLATION_PATTERNS` is a small literal-pattern set. Production runs a continuous review program: weekly sampling of conversations across intents, scope-violation classification (clinical advice, financial advice, legal advice, other out-of-scope), root-cause analysis (was it the LLM, was it the prompt, was it the knowledge base, was it the intent classifier), and feedback into prompt-and-rule updates. Owned by clinical operations and patient experience, supported by the engineering team.

**Per-cohort accuracy and containment monitoring with launch gates.** The demo emits CloudWatch metrics with cohort dimensions. Production additionally builds the equity-monitoring as a launch gate: define cohort axes, per-cohort minimum sample sizes, per-cohort threshold metrics (intent-classification accuracy, identity-verification success rate, containment rate, escalation rate, abandonment rate). Launch is gated on every cohort meeting the threshold, not on the institution-wide average. Disparity alerts trigger reviews; sustained disparity triggers product-level remediation. The cohort axes are policy-level decisions made with the equity-monitoring committee (per-language, per-channel, per-region, per-age-band where opt-in declared).

**Real warm-handoff screen-pop integration with the contact-center agent desktop.** The demo's MockConnect just records what would have been transferred. Production integrates the warm-handoff packet with the contact-center agent desktop (Connect's CCP, Salesforce Service Cloud, vendor-specific desktops) so the agent receives the packet on screen before they answer. The screen-pop store has TTL semantics; the packet expires if not consumed within ten minutes. Agent training covers the screen-pop UX: what fields are present, how to interpret the assurance level, what to do with the crisis flags.

**Real caregiver-proxy enrollment and resolution.** The demo handles only the patient-themselves identity case. Production additionally supports caregiver-proxy interactions: the caregiver authenticates as themselves (caller-ID match plus DOB), the system looks up the patients the caregiver is authorized to act for from the caregiver-relationship table in the EHR, and the conversation proceeds in the named patient's record. The caregiver-relationship records are populated through an explicit caregiver-enrollment workflow (in-person, portal-based, or phone-based with full identity verification). Without the enrollment substrate, the caregiver-proxy paths degrade to escalation-to-human, which is a worse experience than an enrolled caregiver would have.

**Real DTMF fallback for callers who cannot use voice.** The demo handles only the voice path. Production builds the DTMF fallback as a first-class feature: any time the assistant detects ASR failure, audio quality issues, or explicit patient request for touch-tone, it falls back to a DTMF-driven menu for the core intents (confirm appointment, request refill, transfer to agent). The DTMF flow is less rich than the voice flow but it must exist.

**Real smart-speaker channel certification.** The demo handles only telephony and app. Production launching on Alexa or Google additionally completes the platform certification: vendor review, security disclosure, BAA negotiation, PHI handling controls, and ongoing compliance reviews as platform policies change. The smart-speaker channel typically has a narrower intent scope than telephony or app due to the shared-device privacy concern.

**Real EHR integration depth and breadth.** The demo handles only appointment lookup and refill ticket creation. Production handles more: appointment rescheduling (where institutional policy allows), prescription pickup status, lab-result inquiries (where the institutional policy allows automated disclosure), billing inquiries with structured callback ticket creation, insurance-update requests, and the long tail of patient-information inquiries. Each integration has its own API surface, authentication requirements, failure modes, and latency budget. The integrations are most of the engineering work in this recipe.

**Real disaster recovery and degraded-mode operation.** The demo assumes happy-path execution. Production tests the failure modes in a staging environment quarterly: Connect unavailable (fall back to traditional IVR routing), Lex unavailable (fall back to direct queue placement), Bedrock unavailable (skip the LLM intent fallback; route low-confidence utterances directly to humans), Comprehend Medical unavailable (skip medication-slot RxNorm linking; transfer refill requests to pharmacy team), EHR API unreachable (callback ticket fallback). The patient must always reach a human when the system cannot help; the dead-end-to-IVR fallback is the safety net.

**Real idempotency and retry semantics.** The demo's idempotency check is implicit in the session-id uniqueness. Production uses conditional DynamoDB writes keyed on `(session_id, turn_index)` so a duplicate turn submission (network blip, double click) is rejected with `ConditionalCheckFailedException` rather than producing duplicate state. Configure DLQs on every Lambda; alarm on DLQ depth.

**Performance under load and burst.** The latency budget for conversational turns is tight; the system must hold the budget under load. Lex per-request quotas, Bedrock invocation throughput per inference profile, Comprehend Medical inference rates, EHR API rate limits, and Pinpoint SMS delivery rates all need provisioning headroom. Connect agent capacity for warm-transfer destinations needs burst-capacity planning. Load test against realistic peak profiles (Monday-morning spikes, post-system-outage spikes) before launch.

**Real audio retention policy with privacy-officer review.** The demo retains audio in a mock S3 store with no lifecycle. Production deployment requires explicit privacy-officer review of the retention duration, the access controls on retained audio, the consent disclosure language, and the deletion verification. The default is conservative (a few days for QA review, then automatic deletion); longer retention requires explicit consent and an operational purpose.

**Audit log retention and legal hold.** The demo's audit-archive S3 bucket is created without Object Lock. Production enables Object Lock in compliance mode with retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, the EHR vendor's audit-retention floor, and the institutional regulatory floor. Legal hold capabilities (suspending deletion for specific patients during litigation) are configurable.

**Cost monitoring per channel and per intent.** Different channels have very different per-conversation costs (telephony has Connect minute charges that app and smart speaker do not); different intents have very different costs (a RAG-grounded informational response is more expensive than a templated appointment confirmation). Per-channel and per-intent cost dashboards let operations identify outliers and tune accordingly.

**Real vendor evaluation rigor for build-vs-buy decisions.** Most institutions deploying patient-facing voice assistants should be buying a commercial product (Hyro, Notable, Conversa, several others) rather than building one. The demo's pipeline is the architecture for the careful-custom-build path. The vendor evaluation program runs in parallel: per-cohort accuracy benchmarking, scope-containment evaluation, identity-verification evaluation, EHR-and-pharmacy integration depth, escalation-quality evaluation, reference checks with comparable institutions. A custom build that cannot match the major commercial vendors on these axes is the wrong call.

**Operational ownership across multiple teams.** The system sits at the intersection of contact-center operations, IT, patient experience, clinical operations, and compliance. Establish clear ownership at the start: who owns the crisis-detection vocabulary, who owns the scope-filter rules, who owns the institutional knowledge base, who owns the identity-verification policy, who owns the per-cohort equity monitoring, who owns the patient-experience prompts and persona. Without explicit ownership the system drifts and the metrics are not reviewed.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the consent-regime determination logic with edge cases (cross-jurisdiction calls, unknown area codes), unit tests for the crisis-detection rules with the full per-language vocabulary, unit tests for the scope-filter patterns, unit tests for the identity-verification step-up flow including failure modes, integration tests against test buckets and tables with synthetic patient registry data, and end-to-end tests that simulate full conversation flows including the crisis-preempt and OTP-step-up paths. Never use real patient audio or real patient data in test fixtures; use synthetic Synthea patients and TTS-generated audio with known ground truth.

**Observability beyond the metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-stage investigation. Production runs CloudWatch Logs Insights queries that join across the Connect call records, the Lex bot logs, the Lambda execution logs, and the Bedrock invocation logs by session_id. AWS X-Ray traces show the latency contribution of each stage. When a single conversation goes wrong (a crisis is misclassified, a scope violation is caught, an EHR handoff stalls), the on-call engineer needs to reconstruct the full trace in seconds.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 10.5: Patient-Facing Voice Assistant](chapter10.05-patient-facing-voice-assistant) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
