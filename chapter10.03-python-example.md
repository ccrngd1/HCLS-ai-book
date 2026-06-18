# Recipe 10.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 10.3. It shows one way you could translate the voice-to-text-for-EHR-navigation pipeline into working Python using boto3 against Amazon Transcribe (streaming), Amazon Lex V2, Amazon Bedrock, AWS Lambda, Amazon API Gateway, Amazon Cognito, Amazon DynamoDB, AWS Secrets Manager, Amazon EventBridge, and Amazon CloudWatch. The demo uses a `MockTranscribeStreaming` standing in for the streaming ASR session, a `MockLex` standing in for intent classification and slot filling, a `MockBedrock` standing in for the foundation-model fallback classifier, a `MockEHR` standing in for the SMART on FHIR-launched EHR API, and small helpers for the session-state table, the command-audit table, the configuration table, the EventBridge bus, the SNS topic, and CloudWatch-style metrics. It is not production-ready. There is no real API Gateway WebSocket, no real Cognito authorizer, no real SMART on FHIR launch, no real streaming Transcribe session over WebSocket, no real Lex bot, no real Bedrock invocation, no real DynamoDB or EventBridge wiring, no IAM least-privilege role per Lambda, no KMS customer-managed key configuration, no VPC endpoints, no on-call paging integration, no clinician-training UI, and no production audit-overlay integration with the EHR's native audit log. Think of it as the sketchpad version: useful for understanding the shape of a voice-navigation pipeline that respects the activation-feedback discipline, the per-axis confidence-threshold discipline, the patient-slot-resolution-must-not-silently-pick discipline, the EHR-is-source-of-truth discipline, the read-write-boundary discipline, and the audit-everything discipline this recipe demands. It is not something you would deploy to clinicians on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the seven core pseudocode steps from the main recipe: activate the session and capture audio (Step 1), stream audio to ASR and finalize the transcript (Step 2), parse the command into intent and slots (Step 3), resolve context and disambiguate (Step 4), confirm write-class commands and execute read-class commands directly (Step 5), execute against the EHR and reflect the result (Step 6), and audit and emit telemetry (Step 7). The synthetic clinicians, patients, schedules, medications, and command transcripts in the demo are fictional; the names, MRNs, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also configure an Amazon API Gateway WebSocket API for the audio-streaming endpoint plus a REST API for the command-execution endpoint, an Amazon Cognito user pool federated to the institutional identity provider for clinician authentication, an Amazon Lex V2 bot with the navigation intents and slots, a Lex bot alias pinned to a specific bot version, an Amazon Bedrock inference profile pinned to a specific model and region for the LLM fallback classifier, the Lambda functions that the API Gateway and Lex invoke (the audio-stream handler, the command-executor, the audit writer, the telemetry emitter), DynamoDB tables that hold session state, the command audit log, and the per-institution configuration (intent taxonomy, read-write classification, confidence thresholds), AWS Secrets Manager secrets for the EHR API credentials and the SMART on FHIR backend-services signing keys, an Amazon EventBridge bus for cross-system events, an Amazon S3 bucket for audio recordings (when retained, with brief lifecycle), and the SMART on FHIR launch context handoff with the host EHR. The demo replaces all of these with small mocks so the focus stays on the per-stage processing logic rather than on the cloud-resource provisioning.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `transcribe:StartStreamTranscription` for the streaming ASR session
- `lex:RecognizeText` for sending the finalized transcript to a Lex bot programmatically
- `bedrock:InvokeModel` for the LLM fallback classifier, scoped to the specific foundation-model ARN and inference profile in use
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the session-state, command-audit, and configuration tables
- `secretsmanager:GetSecretValue` on the EHR-API credentials and SMART on FHIR signing-key secrets pinned to the current rotation version
- `events:PutEvents` on the voice-navigation EventBridge bus
- `cloudwatch:PutMetricData` for the operational metrics (per-stage latency, ASR confidence histograms, intent confidence distributions, command success rates, disambiguation rates)
- `s3:PutObject` on the optional audio-retention bucket, scoped to the per-session key prefixes
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the audio bucket, the audit-log archive bucket, the DynamoDB tables, and the Secrets Manager secrets
- `connect:UpdateContactAttributes` is not used here; this recipe sits inside the EHR rather than on the contact-center side

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The audio-stream-handler Lambda has scoped Transcribe streaming session rights and write access only to the in-flight session-state record. The command-executor Lambda has scoped Lex invocation rights, Bedrock invocation rights pinned to one model and one inference profile, EHR API credentials read access (for the appropriate rotation version), and write access to the command-audit table and the EventBridge bus. The audit-writer Lambda has scoped write access to the audit table and the audit S3 bucket only. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Activation feedback is non-optional.** Every push-to-talk or wake-word activation produces an immediate visible (LED, screen indicator) or audible (brief tone) acknowledgment that the system is listening. Without this, the clinician does not know whether the system heard them and reverts to the keyboard. The mocks in this demo emit a structured `activation_feedback` event so you can see where production code would drive the device's indicator hardware.
- **Patient-slot resolution must never silently pick.** When the slot value matches multiple patients on the day's schedule (three Mr. Smiths), the system disambiguates with a prompt; it does not guess. The cost of opening the wrong patient's chart is too high (HIPAA event, clinical-trust event). The `resolve_context` step in this demo enforces this with a hard branch on candidate count.
- **The EHR is the source of truth, not the voice system.** Before each command, the pipeline re-fetches the EHR's current patient context. The voice system's session state is a derived view that re-syncs on every command. The architectures that maintain a parallel context independent of the EHR are the ones that show data for the wrong patient when the clinician clicked something in the EHR UI directly between voice commands.
- **Read commands and write commands have asymmetric confirmation rigor.** Read commands execute on confidence; write commands require explicit non-voice confirmation (button press, typed signature). The classification is configuration, not code, so clinical operations can review and adjust without a deployment. The demo's `confirm_command` enforces the asymmetry.
- **Idempotency at the command level.** A command issued twice (network blip, double button press) must not produce two executions. The (clinician_id, session_id, transcript_hash, time_window) tuple is the idempotency key. The demo collapses this to a transcript-hash check on the audit table; production uses a conditional DynamoDB write.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, and numeric metadata field passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses API Gateway, Cognito, multiple Lambdas, the EventBridge fan-out, and the CloudWatch metric emission into a single Python file for readability.** In production each pipeline stage is a separate Lambda with its own IAM role, error handling, retries, and DLQs, fronted by API Gateway with Cognito authorization. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the per-axis confidence thresholds, the intent taxonomy, the read-write classification map, and the disambiguation policy are what you would change between environments.

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
# to CloudWatch Logs Insights. The voice-navigation pipeline
# operates on heavily PHI-adjacent data: the audio is PHI, the
# transcript is PHI, the resolved patient identity is PHI, and
# every executed command is an EHR access event. Log structural
# metadata only (command_id, intent name, confidence band, read
# or write classification, decision outcome), never raw
# transcripts, never patient demographics, never medication or
# diagnosis values, never the clinician's authentication
# material.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from Transcribe streaming,
# Lex, Bedrock, DynamoDB, EventBridge, CloudWatch, and Secrets
# Manager. The voice-navigation response-window expectation is
# tight: the clinician is in the middle of a patient encounter
# and a retry storm that adds 5 seconds of dead air is
# operationally worse than a fast failure. Cap the retries and
# let the caller's failure path surface "system unavailable"
# clearly so the clinician falls back to keyboard-and-mouse.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm
# containers so each invocation does not pay the connection cost.
REGION = "us-east-1"
dynamodb           = boto3.resource("dynamodb", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
transcribe_client  = boto3.client("transcribe", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
lex_client         = boto3.client("lexv2-runtime", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
bedrock_runtime    = boto3.client("bedrock-runtime", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
eventbridge_client = boto3.client("events", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
cloudwatch_client  = boto3.client("cloudwatch", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
secrets_client     = boto3.client("secretsmanager", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do
# not exist; see run_demo() at the bottom.
SESSION_STATE_TABLE         = "voice-nav-session-state"
COMMAND_AUDIT_TABLE         = "voice-nav-command-audit"
CONFIGURATION_TABLE         = "voice-nav-configuration"
VOICE_NAV_EVENT_BUS_NAME    = "voice-nav-events-bus"
CLOUDWATCH_NAMESPACE        = "VoiceNavigation"
LEX_BOT_ID                  = "NAVIGATION_BOT_ID_PLACEHOLDER"
LEX_BOT_ALIAS_ID            = "NAVIGATION_BOT_ALIAS_PROD_PLACEHOLDER"
LEX_LOCALE_ID               = "en_US"

# Bedrock configuration. In production, pin to a specific model
# version and inference profile so a model upgrade does not
# silently change classifier behavior. The model and region
# combination must be in your AWS BAA scope.
BEDROCK_FALLBACK_MODEL_ID   = "anthropic.claude-3-5-sonnet-20240620-v1:0"
BEDROCK_INFERENCE_PROFILE_ARN = (
    "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
    "voice-nav-fallback-v1")

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("SESSION_STATE_TABLE",         SESSION_STATE_TABLE),
    ("COMMAND_AUDIT_TABLE",         COMMAND_AUDIT_TABLE),
    ("CONFIGURATION_TABLE",         CONFIGURATION_TABLE),
    ("VOICE_NAV_EVENT_BUS_NAME",    VOICE_NAV_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",        CLOUDWATCH_NAMESPACE),
    ("LEX_BOT_ID",                  LEX_BOT_ID),
    ("LEX_BOT_ALIAS_ID",            LEX_BOT_ALIAS_ID),
    ("LEX_LOCALE_ID",               LEX_LOCALE_ID),
    ("BEDROCK_FALLBACK_MODEL_ID",   BEDROCK_FALLBACK_MODEL_ID),
    ("BEDROCK_INFERENCE_PROFILE_ARN", BEDROCK_INFERENCE_PROFILE_ARN),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every command record carries the versions of the artifacts that
# influenced it: the bot version, the intent taxonomy version,
# the threshold-config version, the read-write-rules version. A
# future audit reconstructs which calibration was active when a
# particular command was executed.
BOT_VERSION                 = "navigation-bot-v1.4.2"
INTENT_TAXONOMY_VERSION     = "voice-nav-intents-v1.2.0"
THRESHOLD_CONFIG_VERSION    = "voice-nav-thresholds-v1.1.0"
READ_WRITE_RULES_VERSION    = "voice-nav-rwrules-v1.0.0"
INSTITUTION_ID              = "academic-medical-center-richmond"

# --- Activation Modality ---
# The default activation modality. Push-to-talk is the safe
# default for clinical environments; wake-word and always-on are
# phase-two options.
DEFAULT_ACTIVATION_MODE     = "push_to_talk"

# --- ASR Confidence Gates ---
# The transcript-level confidence floor below which we will not
# pass the transcript to the intent classifier; prompt the user
# to repeat instead. The min-confidence-word count is a secondary
# gate: even a high-average-confidence transcript with one
# critical word at very low confidence (often a patient name)
# deserves a "I didn't catch that" prompt rather than guessing.
ASR_MIN_AVG_CONFIDENCE      = Decimal("0.65")
ASR_MAX_LOW_CONF_WORDS      = 2  # words below 0.6 confidence

# --- Intent Confidence Thresholds ---
# Below these thresholds, the command is routed to a confirmation
# card instead of auto-executing. The thresholds differ per
# read-write class because the consequences of a wrong action
# differ. Read intents auto-execute at lower confidence than
# write intents because the cost of a wrong read (open the wrong
# chart, recover) is lower than the cost of a wrong write (queue
# an order for the wrong patient).
INTENT_CONFIDENCE_THRESHOLD       = Decimal("0.70")
READ_AUTO_CONFIDENCE_THRESHOLD    = Decimal("0.85")
BEDROCK_FALLBACK_CONFIDENCE_THRESHOLD = Decimal("0.75")

# --- Session Staleness ---
# If the session has been idle past this threshold, the next
# command requires explicit patient confirmation before
# proceeding. The threshold is institutional; 5 minutes is a
# reasonable starting point for in-encounter use.
SESSION_STALENESS_THRESHOLD_SECONDS = 5 * 60

# --- Intent Taxonomy ---
# The valid intent space. The classifier output is validated
# against this; any out-of-taxonomy value is coerced to "unknown"
# rather than passed through.
INTENT_TAXONOMY = [
    "open_patient",
    "show_recent_results",
    "open_note",
    "navigate_section",
    "navigate_schedule",
    "go_back",
    "scroll_down",
    "scroll_up",
    "log_out",
    "unknown",
]

# --- Read-Write Classification Map ---
# The classification per intent. Reviewed by clinical operations.
# Stored in the configuration table in production so it can be
# updated without a deployment; pinned to the read-write-rules
# version for audit reconstruction.
INTENT_READ_WRITE_MAP = {
    "open_patient":         "read",
    "show_recent_results":  "read",
    "open_note":            "read",
    "navigate_section":     "read",
    "navigate_schedule":    "read",
    "go_back":              "read",
    "scroll_down":          "read",
    "scroll_up":            "read",
    "log_out":              "read",  # session-only state
    "unknown":              "unknown",
}

# Intents requiring a typed signature in addition to a button-
# press confirmation. Empty in MVP; populated as voice-write
# capabilities expand under clinical-operations review.
SIGNATURE_REQUIRED_INTENTS = set()

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

These mocks stand in for the production AWS resources and back-office systems. They are deliberately simple and are not how you would build the real thing. Their purpose is to keep the focus on the voice-navigation pipeline logic.

```python
class MockTranscribeStreaming:
    """
    Stands in for Amazon Transcribe's streaming API. In production
    you open a WebSocket session, push audio frames as they arrive
    from the client, and receive partial-and-final transcripts
    progressively. The demo synthesizes the final transcript from
    a hardcoded mapping (session_id -> transcript fixture) so we
    can exercise the rest of the pipeline without real audio.
    """
    def __init__(self, transcript_fixtures):
        self._fixtures = transcript_fixtures
        self._biasing = {}

    def set_biasing(self, session_id, biasing_terms):
        # In production, vocabulary biasing is set via a custom
        # vocabulary or via per-request biasing terms. The demo
        # records the biasing list so we can assert it was set.
        self._biasing[session_id] = list(biasing_terms)

    def transcribe_session(self, session_id):
        """
        Simulate a complete streaming session: take in the audio
        (we don't have any here), emit a partial transcript or
        two, and return a finalized result with per-word
        confidences.
        """
        fixture = self._fixtures.get(session_id, {
            "transcript_text": "no fixture available for this session",
            "items": [],
        })
        return {
            "transcript":      fixture["transcript_text"],
            "items":           fixture.get("items", []),
            "biasing_applied": self._biasing.get(session_id, []),
        }

class MockLex:
    """
    Stands in for Amazon Lex V2's RecognizeText API. The demo
    matches on transcript substring to return fixture intents and
    slots; production calls lex_client.recognize_text against a
    real bot and receives the same shape of response.
    """
    def __init__(self, intent_fixtures):
        self._fixtures = intent_fixtures

    def recognize_text(self, bot_id, bot_alias_id, locale_id,
                        session_id, text):
        # The bot_id and bot_alias_id are recorded for clarity;
        # the demo doesn't use them for routing because it has a
        # single intent fixture map.
        lowered = (text or "").lower()
        for fixture_key, fixture_response in self._fixtures.items():
            if fixture_key in lowered:
                # Lex returns a dict with intent + slots +
                # confidence; the production response also
                # carries dialog state and an interpretations
                # array. The demo flattens to the bits the
                # pipeline uses.
                return dict(fixture_response)
        return {
            "intent":     {"name": "unknown",
                            "confidence_score": 0.0,
                            "slots": {}},
            "interpretations": [],
        }

class MockBedrock:
    """
    Stands in for Amazon Bedrock's InvokeModel API for the LLM
    fallback classifier. When Lex confidence is low, the pipeline
    sends the transcript to a foundation model with a strict-JSON
    prompt to classify the intent and extract slots. The demo
    returns a fixture-driven response keyed by transcript
    substring.
    """
    def __init__(self, fallback_fixtures):
        self._fixtures = fallback_fixtures

    def invoke_model(self, model_id, body):
        prompt_data = json.loads(body)
        transcript = (prompt_data.get("transcript") or "").lower()
        for fixture_key, fixture_response in self._fixtures.items():
            if fixture_key in transcript:
                return {"body": json.dumps(fixture_response)}
        return {"body": json.dumps({
            "intent":             "unknown",
            "intent_confidence":  0.40,
            "slots":              {},
            "rationale":          ("Could not confidently classify "
                                    "this transcript."),
        })}

class MockEHR:
    """
    Stands in for the EHR API used during context resolution and
    execution. In production this is a SMART on FHIR-launched app
    that calls FHIR endpoints (Patient, Observation, Composition,
    DocumentReference, Encounter, Schedule) with the launch
    context's access token, plus vendor-specific extensions for
    proprietary navigation actions. The demo holds a small set of
    patients, schedules, notes, and observations in memory.
    """
    def __init__(self):
        self._current_state = {
            "patient_id":    None,
            "section":       "schedule",
            "snapshot_id":   "ehr-snap-0001",
        }
        self._patients = {
            "pt-44219-3c": {
                "patient_id":  "pt-44219-3c",
                "first_name":  "Margaret",
                "last_name":   "Chen",
                "dob":         "1958-03-14",
                "mrn":         "MRN-2010001",
            },
            "pt-91002-7a": {
                "patient_id":  "pt-91002-7a",
                "first_name":  "Robert",
                "last_name":   "Smith",
                "dob":         "1942-07-21",
                "mrn":         "MRN-2010055",
            },
            "pt-91002-7b": {
                "patient_id":  "pt-91002-7b",
                "first_name":  "Robert",
                "last_name":   "Smith",
                "dob":         "1971-10-02",
                "mrn":         "MRN-2010056",
            },
            "pt-77310-4f": {
                "patient_id":  "pt-77310-4f",
                "first_name":  "James",
                "last_name":   "Patel",
                "dob":         "1972-09-22",
                "mrn":         "MRN-2010102",
            },
        }
        self._observations = {
            "pt-44219-3c": [
                {"date": "2026-05-20",
                 "category": "laboratory",
                 "name": "Basic Metabolic Panel"},
                {"date": "2026-05-20",
                 "category": "laboratory",
                 "name": "Lipid Panel"},
            ],
            "pt-77310-4f": [
                {"date": "2026-04-12",
                 "category": "laboratory",
                 "name": "Hemoglobin A1c"},
            ],
        }
        self._notes = {
            "pt-44219-3c": [
                {"note_id": "note-77001",
                 "type":    "operative-note",
                 "date":    "2026-10-14",
                 "title":   "Cystoscopy with biopsy"},
                {"note_id": "note-77002",
                 "type":    "progress-note",
                 "date":    "2026-04-30",
                 "title":   "Annual visit"},
            ],
        }

    def get_current_state(self, clinician_id, device_id):
        # In production this either consumes an event from the
        # EHR (the EHR pushes patient-context-changed events to
        # the SMART app) or polls a cached "what's open" endpoint
        # tied to the current launch context.
        return dict(self._current_state)

    def set_current_patient(self, patient_id, section="summary"):
        # Helper for the demo so we can simulate the EHR's state
        # changing as commands execute.
        self._current_state["patient_id"] = patient_id
        self._current_state["section"]    = section

    def search_schedule(self, clinician_id, name_query):
        """Return today's schedule entries whose name matches."""
        # The demo's schedule is fixed; in production this is a
        # FHIR Schedule + Slot search filtered by practitioner.
        schedule = [
            {"patient_id": "pt-44219-3c",
             "appointment_at": "2026-05-23T09:00:00Z"},
            {"patient_id": "pt-91002-7a",
             "appointment_at": "2026-05-23T10:00:00Z"},
            {"patient_id": "pt-91002-7b",
             "appointment_at": "2026-05-23T10:30:00Z"},
            {"patient_id": "pt-77310-4f",
             "appointment_at": "2026-05-23T11:30:00Z"},
        ]
        results = []
        ql = (name_query or "").strip().lower()
        for slot in schedule:
            patient = self._patients.get(slot["patient_id"])
            if not patient:
                continue
            full_name = (f"{patient['first_name']} "
                         f"{patient['last_name']}").lower()
            if ql in full_name or full_name.endswith(" " + ql):
                results.append({
                    "patient_id":      patient["patient_id"],
                    "first_name":      patient["first_name"],
                    "last_name":       patient["last_name"],
                    "dob":             patient["dob"],
                    "mrn":             patient["mrn"],
                    "appointment_at":  slot["appointment_at"],
                })
        return results

    def open_patient_chart(self, patient_id):
        # Production: PUT /Patient/{id}/$set-active or vendor-
        # specific equivalent.
        if patient_id not in self._patients:
            return {"status": "not_found", "patient_id": patient_id}
        self.set_current_patient(patient_id, section="summary")
        return {"status": "success",
                "patient_id": patient_id,
                "section": "summary"}

    def fetch_observations(self, patient_id, category, count, sort):
        # Production: GET /Observation?patient=...&category=...
        # &_count=...&_sort=...
        observations = list(self._observations.get(patient_id, []))
        if category:
            observations = [
                o for o in observations
                if o.get("category") == category]
        observations.sort(key=lambda o: o.get("date", ""), reverse=True)
        if count:
            observations = observations[:count]
        return {"status": "success",
                "patient_id": patient_id,
                "observations": observations}

    def find_note(self, patient_id, note_type, date=None, author=None):
        # Production: GET /DocumentReference?patient=...&type=...
        # &date=... with appropriate ontology-coded type.
        notes = self._notes.get(patient_id, [])
        for note in notes:
            if note.get("type") != note_type:
                continue
            if date and note.get("date") != date:
                continue
            return note["note_id"]
        return None

    def open_note_in_ehr(self, note_id):
        return {"status": "success", "note_id": note_id}

    def set_chart_section(self, patient_id, section):
        if patient_id not in self._patients:
            return {"status": "not_found", "patient_id": patient_id}
        self.set_current_patient(patient_id, section=section)
        return {"status": "success",
                "patient_id": patient_id,
                "section": section}

class MockClient:
    """
    Stands in for the SMART on FHIR voice-navigation client app
    on the rolling cart. Captures the activation feedback, partial
    transcripts, confirmation cards, and user messages so the demo
    can show what the clinician would see and hear. Production
    drives device LEDs, on-screen indicators, and an audio output
    channel.
    """
    def __init__(self):
        self.events = []
        self._next_confirmation_decision = None
        self._next_write_confirmation_decision = None

    def emit_activation_feedback(self, visible, audible):
        self.events.append({
            "type":    "activation_feedback",
            "visible": visible,
            "audible": audible,
            "at":      _now_iso(),
        })

    def emit_partial_to_client(self, text):
        self.events.append({
            "type": "partial_transcript",
            "text": text,
            "at":   _now_iso(),
        })

    def emit_to_client(self, type, message):
        self.events.append({
            "type":    type,
            "message": message,
            "at":      _now_iso(),
        })

    def emit_user_message(self, message):
        self.events.append({
            "type":    "user_message",
            "message": message,
            "at":      _now_iso(),
        })

    def render_results_panel(self, results):
        self.events.append({
            "type":    "results_panel",
            "summary": (f"{len(results.get('observations', []))} "
                        f"observations rendered"),
            "at":      _now_iso(),
        })

    def show_confirmation_card(self, title, description, actions,
                                allow_voice_confirm, timeout_seconds):
        self.events.append({
            "type":               "confirmation_card",
            "title":              title,
            "description":        description,
            "actions":            actions,
            "allow_voice_confirm": allow_voice_confirm,
            "timeout_seconds":    timeout_seconds,
            "at":                 _now_iso(),
        })

    def show_write_confirmation(self, title, description, actions,
                                 allow_voice_confirm, timeout_seconds,
                                 signature_required):
        self.events.append({
            "type":               "write_confirmation",
            "title":              title,
            "description":        description,
            "actions":            actions,
            "allow_voice_confirm": allow_voice_confirm,
            "timeout_seconds":    timeout_seconds,
            "signature_required": signature_required,
            "at":                 _now_iso(),
        })

    def queue_next_confirmation(self, action, method="button_press"):
        """Demo control: pre-decide the next read-confirm answer."""
        self._next_confirmation_decision = {"action": action,
                                              "method": method}

    def queue_next_write_confirmation(self, action,
                                       method="button_press"):
        """Demo control: pre-decide the next write-confirm answer."""
        self._next_write_confirmation_decision = {
            "action": action, "method": method}

    def wait_for_confirmation(self):
        decision = (self._next_confirmation_decision
                    or {"action": "confirm", "method": "auto"})
        self._next_confirmation_decision = None
        return decision

    def wait_for_write_confirmation(self):
        decision = (self._next_write_confirmation_decision
                    or {"action": "cancel", "method": "auto"})
        self._next_write_confirmation_decision = None
        return decision

class MockSessionState:
    """
    Stands in for the DynamoDB session-state table. Holds the
    in-flight context for each device's current voice-navigation
    session.
    """
    def __init__(self):
        self._items = {}

    def get(self, session_id):
        return dict(self._items.get(session_id, {}))

    def put(self, session_id, item):
        self._items[session_id] = dict(item)

    def update(self, session_id, updates):
        existing = self._items.setdefault(session_id,
                                            {"session_id": session_id})
        existing.update(updates)

class MockCommandAudit:
    """
    Stands in for the DynamoDB command-audit table plus the S3
    audit archive. Every command, every confirmation, every
    execution outcome lands here. In production this is a table
    partitioned by clinician_id with a sort key on command_id,
    plus a Kinesis Firehose stream that copies records to S3 with
    Object Lock for HIPAA-grade durability.
    """
    def __init__(self):
        self._records = []

    def put(self, record):
        self._records.append(dict(record))

    def find_recent_for_idempotency(self, clinician_id, session_id,
                                     transcript_hash, window_seconds):
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(seconds=window_seconds))
        for record in reversed(self._records):
            if (record.get("clinician_id") == clinician_id
                    and record.get("session_id") == session_id
                    and (record.get("transcript_hash")
                         == transcript_hash)):
                ts = record.get("timestamp")
                if ts and ts >= cutoff.isoformat():
                    return record
        return None

class MockEventBus:
    """
    Stands in for Amazon EventBridge. The pipeline emits events
    for cross-system fan-out: command-issued, command-executed,
    command-failed, command-disambiguated, command-abandoned.
    Downstream consumers (analytics, dashboards, EHR audit
    overlay) pick these up.
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
session_state    = MockSessionState()
command_audit    = MockCommandAudit()
ehr              = MockEHR()
client           = MockClient()
event_bus        = MockEventBus()
cloudwatch       = MockCloudWatch()
# transcribe, lex, and bedrock mocks are wired up in run_demo()
# with fixture data tailored to each scenario.
transcribe_mock  = None
lex_mock         = None
bedrock_mock     = None

def audit_log(event):
    """
    In production, audit events go to a tamper-resistant store
    (Object-Lock S3, an append-only DynamoDB table, or a SIEM).
    The demo prints a sanitized summary so you can see the
    sequence of decisions without leaking the underlying values.
    """
    safe_event = {
        k: v for k, v in event.items()
        if k not in {"transcript", "patient_demographics",
                      "slot_values_raw"}
    }
    if "transcript" in event:
        safe_event["transcript_length"] = len(event["transcript"] or "")
    logger.info("AUDIT %s", json.dumps(safe_event, default=str))
```

---

## Step 1: Activate the Session and Capture Audio

*The pseudocode calls this `ON activation_signal(...)`. The clinician presses the push-to-talk button (or the foot pedal, or the headset button). The client app validates the clinician session and the SMART on FHIR launch context, opens a streaming audio session, and emits immediate visible-or-audible activation feedback so the clinician knows the system is listening. The session also loads the per-call vocabulary biasing list (today's schedule, the current patient's medications, the providers in the practice). Skip the activation feedback and the clinician will not know whether the system heard them; this is the most common MVP regression.*

```python
def activate_session(device_id, clinician_id, smart_on_fhir_context,
                      activation_mode=DEFAULT_ACTIVATION_MODE,
                      schedule_for_today=None,
                      providers_in_practice=None):
    """
    Open a voice-navigation session in response to an activation
    signal. Returns a session-context dict that downstream stages
    consume.

    In production this is invoked when the WebSocket connects to
    API Gateway with a Cognito-authenticated clinician identity
    and the SMART on FHIR launch context's access token in the
    request headers.

    Args:
        device_id: Stable identifier for the rolling cart, the
            workstation, or the mobile device.
        clinician_id: Authenticated clinician identity from
            Cognito.
        smart_on_fhir_context: Dict with "patient_id",
            "encounter_id", "access_token", "launch_id",
            "issued_at" fields.
        activation_mode: "push_to_talk", "wake_word", or
            "foot_pedal". Drives downstream UX and audit
            classification.
        schedule_for_today: Optional list of patient names on
            today's schedule. Used for vocabulary biasing.
        providers_in_practice: Optional list of provider names
            for biasing.

    Returns:
        Session-context dict with session_id, identity fields,
        biasing list, activation timestamp, and the EHR's
        current state at session start.
    """
    # Step 1A: validate the clinician session and the SMART on
    # FHIR launch context. Stale tokens are a security failure
    # mode; reject with a re-launch prompt rather than passing
    # through.
    issued_at = smart_on_fhir_context.get("issued_at")
    if issued_at:
        issued_dt = datetime.fromisoformat(
            issued_at.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - issued_dt
        # Production: token-lifetime enforcement would also
        # honor the EHR vendor's session timeout policy.
        if age > timedelta(hours=8):
            audit_log({
                "event_type":   "ACTIVATION_REJECTED_STALE_LAUNCH",
                "clinician_id": clinician_id,
                "device_id":    device_id,
                "timestamp":    _now_iso(),
            })
            raise RuntimeError(
                "SMART on FHIR launch context is stale; "
                "re-launch required")

    # Step 1B: create the session record. The session_id is the
    # idempotency anchor for everything that follows.
    session_id = "sess-" + uuid.uuid4().hex[:16]
    activated_at = _now_iso()
    session_record = {
        "session_id":               session_id,
        "device_id":                device_id,
        "clinician_id":             clinician_id,
        "launch_id":                smart_on_fhir_context.get("launch_id"),
        "activation_mode":          activation_mode,
        "activated_at":             activated_at,
        "last_command_at":          activated_at,
        "current_patient_id":
            smart_on_fhir_context.get("patient_id"),
        "current_encounter_id":
            smart_on_fhir_context.get("encounter_id"),
        "schedule_today":           list(schedule_for_today or []),
        "providers_in_practice":    list(providers_in_practice or []),
        "bot_version":              BOT_VERSION,
        "intent_taxonomy_version":  INTENT_TAXONOMY_VERSION,
    }
    session_state.put(session_id, _to_decimal(session_record))

    # Step 1C: emit immediate user-visible activation. The visible
    # acknowledgment can be a device LED, a tone, a screen
    # indicator, or all of the above; pick at least one. Without
    # this, the user is talking to a system that gives no
    # feedback. In production this is driven by the device-
    # control channel that sits alongside the audio stream.
    client.emit_activation_feedback(visible=True, audible=True)

    # Step 1D: build the per-session vocabulary biasing list.
    # Patient-name recognition in noisy clinical environments
    # depends heavily on this. The list is dynamic: today's
    # schedule, the current patient's medications, recent
    # encounters, the providers in the practice. The custom
    # vocabulary is created or refreshed in Transcribe before
    # the streaming session starts.
    biasing_terms = list(schedule_for_today or [])
    biasing_terms += list(providers_in_practice or [])
    # In production the biasing list also includes the current
    # patient's active medication names (RxNorm common forms)
    # and the recent encounter dates, both fetched via FHIR
    # before the session opens.
    transcribe_mock.set_biasing(session_id, biasing_terms)

    audit_log({
        "event_type":      "SESSION_ACTIVATED",
        "session_id":      session_id,
        "clinician_id":    clinician_id,
        "device_id":       device_id,
        "activation_mode": activation_mode,
        "timestamp":       activated_at,
    })

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "SessionsActivated", 1, "Count",
        dimensions={"activation_mode": activation_mode,
                    "institution_id":  INSTITUTION_ID})

    return {
        "session_id":               session_id,
        "device_id":                device_id,
        "clinician_id":             clinician_id,
        "launch_id":                smart_on_fhir_context.get("launch_id"),
        "access_token":
            smart_on_fhir_context.get("access_token"),
        "activation_mode":          activation_mode,
        "activated_at":             activated_at,
        "current_patient_id":
            smart_on_fhir_context.get("patient_id"),
        "schedule":                 list(schedule_for_today or []),
        "panel":                    list(providers_in_practice or []),
        "biasing_terms":            biasing_terms,
    }
```

---

## Step 2: Stream Audio to ASR and Finalize the Transcript

*The pseudocode calls this `stream_audio_to_asr(...)`. Audio frames stream from the device through API Gateway's WebSocket to the Transcribe streaming endpoint. Partial transcripts emit progressively (so the client can show "listening: open patient...") and the final transcript emits when end-of-utterance is detected (button release in push-to-talk mode). The pipeline computes aggregate confidence and gates further processing on it: a low-confidence transcription is bounced back to the user for a re-utterance rather than passed to the classifier. Skip the per-word confidence aggregation and the downstream layers cannot make confidence-aware decisions; the read-write boundary breaks down.*

```python
def stream_audio_to_asr(session_context):
    """
    Run the streaming ASR for a single utterance and produce a
    finalized transcript with confidence aggregates.

    In production this is the audio-stream-handler Lambda (or an
    ECS task for longer-lived WebSocket handling) that pumps
    audio frames from the API Gateway WebSocket into a Transcribe
    streaming session and emits partial transcripts back to the
    client.

    Args:
        session_context: The dict returned by activate_session.

    Returns:
        A dict with proceed (bool), transcript text, and
        confidence aggregates.
    """
    session_id = session_context["session_id"]

    # Step 2A: open the streaming Transcribe session. Production
    # calls transcribe_client.start_stream_transcription with
    # MediaSampleRateHertz=16000, LanguageCode="en-US", and the
    # custom-vocabulary or per-request biasing list. The mock
    # short-circuits the streaming pumping and returns the final
    # result directly.
    asr_started_at = _now_iso()
    asr_result = transcribe_mock.transcribe_session(session_id)
    transcript_text = asr_result.get("transcript", "")
    items = asr_result.get("items", [])

    # Step 2B: emit a (simulated) partial transcript so the
    # client UI can show "listening: ..." mid-utterance. In
    # production this happens many times during the streaming
    # session; the demo emits one to illustrate the pattern.
    if transcript_text:
        client.emit_partial_to_client(
            text=transcript_text.split(".")[0])

    # Step 2C: collect per-word confidences. Transcribe streaming
    # returns word-level alternatives with confidence scores; the
    # pipeline averages and tracks the minimum so confidence-
    # aware downstream decisions have something to gate on.
    word_confidences = []
    for item in items:
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
        avg_confidence = Decimal("0.50")
        min_confidence = Decimal("0.50")
        low_conf_count = 0

    audit_log({
        "event_type":     "ASR_FINALIZED",
        "session_id":     session_id,
        "started_at":     asr_started_at,
        "completed_at":   _now_iso(),
        "avg_confidence": float(avg_confidence),
        "min_confidence": float(min_confidence),
        "low_conf_count": low_conf_count,
        "timestamp":      _now_iso(),
    })

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "ASRConfidenceAvg",
        float(avg_confidence) * 100, "Percent",
        dimensions={"institution_id": INSTITUTION_ID})

    # Step 2D: gate on overall ASR confidence. If the
    # transcription is too uncertain, prompt the user to repeat
    # rather than guessing. The threshold is per-axis: ASR
    # confidence is calibrated independently from intent
    # confidence in step 3.
    if (avg_confidence < ASR_MIN_AVG_CONFIDENCE
            or low_conf_count > ASR_MAX_LOW_CONF_WORDS):
        client.emit_to_client(
            type="ASR_LOW_CONFIDENCE",
            message="I didn't catch that. Try again?")
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "ASRConfidenceGateFailed",
            1, "Count",
            dimensions={"institution_id": INSTITUTION_ID})
        return {
            "proceed":         False,
            "session_id":      session_id,
            "disposition":     "asr_low_confidence",
            "transcript":      transcript_text,
            "avg_confidence":  avg_confidence,
        }

    return {
        "proceed":         True,
        "session_id":      session_id,
        "transcript":      transcript_text,
        "avg_confidence":  avg_confidence,
        "min_confidence":  min_confidence,
        "word_confidences": [Decimal(str(c)) for c in word_confidences],
        "asr_started_at":  asr_started_at,
        "asr_completed_at": _now_iso(),
    }
```

---

## Step 3: Parse the Command into Intent and Slots

*The pseudocode calls this `parse_command(...)`. The transcript goes to Lex (the managed bot) for intent classification and slot extraction. When Lex confidence is below threshold, the pipeline optionally falls back to Bedrock for a second opinion. The output is a structured command object with intent, slots, the read-or-write classification (looked up from configuration), and per-component confidence. Strict validation against the configured taxonomy: out-of-vocabulary intents are coerced to "unknown" rather than passed through. Skip the strict validation and a hallucinated intent could trigger an unintended EHR action.*

```python
def _build_bedrock_prompt(transcript, intent_taxonomy):
    """
    Build the prompt for the LLM fallback classifier. In
    production this is a versioned, reviewed prompt with system
    instructions, the intent taxonomy, slot schemas, and a small
    set of few-shot examples. The output schema is strict JSON.
    """
    prompt = {
        "instruction": (
            "You are a voice-navigation assistant for an EHR. "
            "Classify the following voice command into one of "
            "the listed intents and extract any slots. Output "
            "valid JSON only, matching the output_schema."),
        "intent_taxonomy": intent_taxonomy,
        "slot_schemas": {
            "open_patient":        ["patient"],
            "show_recent_results": ["result_type", "count"],
            "open_note":           ["note_type", "date", "author"],
            "navigate_section":    ["section"],
            "navigate_schedule":   ["target"],
        },
        "transcript": transcript,
        "output_schema": {
            "intent":             "<one of intent_taxonomy>",
            "intent_confidence":  "<float 0..1>",
            "slots":              "<dict per slot_schemas>",
            "rationale":          "<brief explanation>",
        },
    }
    return json.dumps(prompt)

def _normalize_slot_date(date_text, reference=None):
    """
    Canonicalize a spoken date phrase to ISO 8601. In production
    this delegates to a robust date-parsing library that handles
    "two weeks ago," "yesterday," "October fourteenth," etc.,
    against a reference timestamp. The demo handles a few
    explicit shapes for illustration.
    """
    if not date_text:
        return None
    text = date_text.strip().lower()
    reference = reference or datetime.now(timezone.utc)
    # ISO already
    iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if iso_match:
        return text
    # "october fourteenth" -> approximate
    months = {"january": 1, "february": 2, "march": 3, "april": 4,
              "may": 5, "june": 6, "july": 7, "august": 8,
              "september": 9, "october": 10, "november": 11,
              "december": 12}
    ordinals = {
        "first": 1, "second": 2, "third": 3, "fourth": 4,
        "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
        "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
        "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
        "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
        "nineteenth": 19, "twentieth": 20, "twenty-first": 21,
        "twenty-second": 22, "twenty-third": 23,
        "twenty-fourth": 24, "twenty-fifth": 25,
        "twenty-sixth": 26, "twenty-seventh": 27,
        "twenty-eighth": 28, "twenty-ninth": 29,
        "thirtieth": 30, "thirty-first": 31,
    }
    for month_name, month_num in months.items():
        if month_name in text:
            for ordinal_name, day_num in ordinals.items():
                if ordinal_name in text:
                    return (f"{reference.year:04d}-"
                            f"{month_num:02d}-{day_num:02d}")
    return None

def parse_command(asr_result, session_context):
    """
    Run the intent classifier (Lex) and, if needed, the LLM
    fallback (Bedrock). Validate output against the configured
    taxonomy. Return a structured command object.

    Args:
        asr_result: The dict returned by stream_audio_to_asr.
        session_context: The dict returned by activate_session.

    Returns:
        A dict with proceed flag, intent, slots, confidence,
        and the read-write classification.
    """
    transcript = asr_result["transcript"]
    session_id = session_context["session_id"]

    # Step 3A: invoke Lex. Lex returns the intent name, slot
    # values, per-intent confidence, and a dialog state. The
    # production call is lex_client.recognize_text(...) against
    # a real bot; the demo uses MockLex.
    lex_response = lex_mock.recognize_text(
        bot_id=LEX_BOT_ID,
        bot_alias_id=LEX_BOT_ALIAS_ID,
        locale_id=LEX_LOCALE_ID,
        session_id=session_id,
        text=transcript)

    intent_obj = lex_response.get("intent", {}) or {}
    intent = intent_obj.get("name", "unknown")
    intent_confidence = Decimal(str(
        intent_obj.get("confidence_score", 0.0)))
    slots = dict(intent_obj.get("slots", {}) or {})
    classifier_used = "lex"

    # Step 3B: validate against the configured taxonomy. Lex
    # generally returns configured intents only, but defensive
    # validation is appropriate for any classifier.
    if intent not in INTENT_TAXONOMY:
        intent = "unknown"
        intent_confidence = Decimal("0.0")

    # Step 3C: if Lex confidence is below threshold, optionally
    # fall back to Bedrock for a second opinion. The fallback is
    # configurable per institution (BEDROCK_FALLBACK_ENABLED in
    # production); the demo always attempts it when confidence
    # is low.
    if intent_confidence < INTENT_CONFIDENCE_THRESHOLD:
        # Production: bedrock_runtime.invoke_model(
        #     modelId=BEDROCK_INFERENCE_PROFILE_ARN,
        #     body=_build_bedrock_prompt(transcript, INTENT_TAXONOMY),
        #     contentType="application/json",
        #     accept="application/json")
        # The inference-profile ARN is what you pass as modelId
        # for cross-region inference and per-profile rate limits.
        bedrock_response = bedrock_mock.invoke_model(
            model_id=BEDROCK_INFERENCE_PROFILE_ARN,
            body=_build_bedrock_prompt(transcript, INTENT_TAXONOMY))
        try:
            bedrock_parsed = json.loads(bedrock_response["body"])
        except (TypeError, ValueError):
            bedrock_parsed = None

        if (bedrock_parsed
                and bedrock_parsed.get("intent") in INTENT_TAXONOMY
                and (Decimal(str(bedrock_parsed.get("intent_confidence", 0)))
                     > BEDROCK_FALLBACK_CONFIDENCE_THRESHOLD)):
            intent = bedrock_parsed["intent"]
            intent_confidence = Decimal(str(
                bedrock_parsed["intent_confidence"]))
            slots = dict(bedrock_parsed.get("slots", {}) or {})
            classifier_used = "bedrock_fallback"
            audit_log({
                "event_type":          "BEDROCK_FALLBACK_USED",
                "session_id":          session_id,
                "lex_confidence":
                    float(intent_obj.get("confidence_score", 0.0)),
                "bedrock_confidence":  float(intent_confidence),
                "intent":              intent,
                "timestamp":           _now_iso(),
            })

    # Step 3D: classify the command as read or write. The
    # classification is configuration, not code, so clinical
    # operations can adjust without a deployment.
    read_write = INTENT_READ_WRITE_MAP.get(intent, "unknown")

    # Step 3E: canonicalize slots. Date slots are normalized to
    # ISO 8601 against the current timestamp. Medical-vocabulary
    # slots (medication, lab) would be canonicalized via
    # Comprehend Medical's RxNorm / LOINC linkers in production;
    # the demo skips that.
    if "date" in slots and slots["date"]:
        slots["date"] = (_normalize_slot_date(slots["date"])
                         or slots["date"])
    if "patient" in slots and slots["patient"]:
        slots["patient"] = slots["patient"].strip()

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "IntentConfidence",
        float(intent_confidence) * 100, "Percent",
        dimensions={"intent": intent,
                    "classifier_used": classifier_used})

    return {
        "proceed":           intent != "unknown",
        "session_id":        session_id,
        "transcript":        transcript,
        "transcript_hash":   _hash_transcript(transcript),
        "avg_confidence":    asr_result["avg_confidence"],
        "min_confidence":    asr_result["min_confidence"],
        "intent":            intent,
        "intent_confidence": intent_confidence,
        "slots":             slots,
        "read_write":        read_write,
        "classifier_used":   classifier_used,
    }
```

---

## Step 4: Resolve Context and Disambiguate

*The pseudocode calls this `resolve_context(...)`. The parsed command meets the EHR's current context. If the command includes a patient slot, the patient is resolved against the day's schedule, the clinician's panel, or a broader index. Ambiguous matches go to a disambiguation prompt; unique matches proceed; zero matches go to a clarification prompt. The system never silently picks a patient when input is ambiguous. Skip this gate and you are one misrecognition away from opening the wrong patient's chart, which is a HIPAA event.*

```python
def _build_disambiguation_prompt(candidate_patients):
    """
    Render a short disambiguation prompt the client can show.
    Includes enough identifying info (first name, last name,
    DOB, appointment time) for the clinician to pick. Never
    silently pick.
    """
    lines = ["I see more than one patient by that name today. "
             "Which one do you mean?"]
    for idx, patient in enumerate(candidate_patients, start=1):
        first = patient.get("first_name") or ""
        last  = patient.get("last_name") or ""
        dob   = patient.get("dob") or ""
        appt  = patient.get("appointment_at") or ""
        lines.append(
            f"  {idx}. {first} {last}, DOB {dob}, "
            f"appointment {appt}")
    return "\n".join(lines)

def _resolve_patient_slot(spoken_name, schedule):
    """
    Match the spoken name against today's schedule. Return the
    list of candidate patient records.

    Production: this uses the patient-index pipeline (recipe
    5.1) to handle nicknames, honorifics, and partial names. The
    demo does a simple last-name substring match against today's
    schedule.
    """
    if not spoken_name:
        return []
    return ehr.search_schedule(
        clinician_id=None, name_query=spoken_name)

def resolve_context(parsed_command, session_context):
    """
    Sync with the EHR's current state, resolve patient slots,
    apply staleness checks. Returns a command-with-context dict
    ready for confirmation/execution, or routes to a
    disambiguation/clarification flow.
    """
    session_id = session_context["session_id"]
    intent     = parsed_command["intent"]
    slots      = dict(parsed_command["slots"])

    # Step 4A: re-fetch the EHR's current context. The EHR is
    # the authoritative source of truth; voice-system context is
    # a derived view that re-syncs on every command. Skipping
    # this is how you end up showing data for the wrong patient
    # when the clinician clicked something in the EHR UI between
    # commands.
    ehr_state = ehr.get_current_state(
        clinician_id=session_context["clinician_id"],
        device_id=session_context["device_id"])
    current_patient_id = ehr_state.get("patient_id")
    current_section    = ehr_state.get("section")

    # Step 4B: if the command specifies a patient slot, resolve
    # against today's schedule.
    resolved_patient_id = current_patient_id
    if "patient" in slots and slots["patient"]:
        candidates = _resolve_patient_slot(
            spoken_name=slots["patient"],
            schedule=session_context.get("schedule", []))

        if len(candidates) == 0:
            client.emit_user_message(
                "I don't see a patient by that name on your "
                "schedule today. Can you spell it?")
            cloudwatch.put_metric(
                CLOUDWATCH_NAMESPACE, "PatientSlotNotFound",
                1, "Count",
                dimensions={"institution_id": INSTITUTION_ID})
            return {
                "proceed":      False,
                "disposition":  "patient_not_found",
            }

        if len(candidates) > 1:
            # Multiple matches. Disambiguation prompt shows the
            # top candidates with enough identifying info for
            # the clinician to pick. Never silently pick.
            prompt = _build_disambiguation_prompt(candidates)
            client.emit_to_client(
                type="DISAMBIGUATION_REQUIRED",
                message=prompt)
            audit_log({
                "event_type":     "PATIENT_SLOT_AMBIGUOUS",
                "session_id":     session_id,
                "candidate_count": len(candidates),
                "timestamp":      _now_iso(),
            })
            cloudwatch.put_metric(
                CLOUDWATCH_NAMESPACE, "PatientSlotAmbiguous",
                1, "Count",
                dimensions={"institution_id": INSTITUTION_ID})
            return {
                "proceed":      False,
                "disposition":  "patient_ambiguous",
                "candidates":   candidates,
            }

        resolved_patient_id = candidates[0]["patient_id"]

    # Step 4C: staleness check. If the device has been idle past
    # the staleness threshold, require explicit patient
    # confirmation before proceeding for any command that
    # operates on a patient.
    session_record = session_state.get(session_id)
    last_command_at = session_record.get("last_command_at")
    if last_command_at:
        last_dt = datetime.fromisoformat(
            last_command_at.replace("Z", "+00:00"))
        idle_seconds = (datetime.now(timezone.utc) - last_dt
                        ).total_seconds()
    else:
        idle_seconds = 0

    if (idle_seconds > SESSION_STALENESS_THRESHOLD_SECONDS
            and resolved_patient_id
            and "patient" not in parsed_command["slots"]):
        client.emit_user_message(
            f"It's been a while. Are you still with patient "
            f"{resolved_patient_id}?")
        return {
            "proceed":      False,
            "disposition":  "stale_session_confirm_patient",
        }

    enriched_command = dict(parsed_command)
    enriched_command["resolved_patient_id"] = resolved_patient_id
    enriched_command["current_section"]     = current_section
    enriched_command["ehr_snapshot_id"]     = ehr_state.get("snapshot_id")
    enriched_command["proceed"]             = True
    return enriched_command
```

---

## Step 5: Confirm Write-Class Commands; Execute Read-Class Commands Directly

*The pseudocode calls this `confirm_command(...)`. The read-write classification gates the confirmation flow. Read commands execute immediately if the intent confidence is above the auto-confidence threshold; otherwise a brief confirmation card displays. Write commands always require explicit, non-voice confirmation: the system displays the proposed action and waits for a button press or typed signature. Skip the asymmetric confirmation rigor and either the system is too cautious to be useful (everything confirms) or too aggressive to be safe (writes execute on voice alone).*

```python
def _build_command_description(enriched_command):
    """
    Render a short, readable description of the command for the
    confirmation card. Used for both read and write
    confirmations.
    """
    intent = enriched_command["intent"]
    slots  = enriched_command.get("slots", {})
    if intent == "open_patient":
        return f"Open patient: {slots.get('patient', '?')}"
    if intent == "show_recent_results":
        return (f"Show recent {slots.get('result_type', 'results')} "
                f"for the current patient")
    if intent == "open_note":
        return (f"Open the {slots.get('note_type', '')} note "
                f"from {slots.get('date', 'recent')}")
    if intent == "navigate_section":
        return f"Go to {slots.get('section', '?')}"
    if intent == "navigate_schedule":
        return f"Schedule navigation: {slots.get('target', '?')}"
    return f"Run intent: {intent}"

def confirm_command(enriched_command):
    """
    Decide whether the command needs a confirmation card. Read
    commands execute on confidence; write commands always
    require explicit non-voice confirmation.

    Returns:
        Dict with confirmed (bool), confirmation_required (bool),
        confirmation_method (str). Caller should not execute when
        confirmed is False.
    """
    intent_confidence = enriched_command["intent_confidence"]
    read_write        = enriched_command["read_write"]
    intent            = enriched_command["intent"]

    # Step 5A: read-only commands with high confidence execute
    # immediately.
    if (read_write == "read"
            and intent_confidence >= READ_AUTO_CONFIDENCE_THRESHOLD):
        return {"confirmed":             True,
                "confirmation_required": False,
                "confirmation_method":   None}

    # Step 5B: read-only commands with medium confidence get a
    # lightweight confirmation card. The user can confirm with
    # button or voice.
    if read_write == "read":
        client.show_confirmation_card(
            title="Did you mean...?",
            description=_build_command_description(enriched_command),
            actions=["confirm", "cancel"],
            allow_voice_confirm=True,
            timeout_seconds=5)
        decision = client.wait_for_confirmation()
        confirmed = decision.get("action") == "confirm"
        return {"confirmed":             confirmed,
                "confirmation_required": True,
                "confirmation_method":   decision.get("method")}

    # Step 5C: write-class commands always require explicit
    # non-voice confirmation. Voice cannot confirm a write. The
    # signature_required flag adds a typed-signature step for
    # the highest-stakes intents (e.g., signing a note); for
    # MVP no intents are in the write set, so this branch is
    # mostly a placeholder for the maturity expansion.
    if read_write == "write":
        client.show_write_confirmation(
            title="Confirm action",
            description=_build_command_description(enriched_command),
            actions=["confirm_button", "cancel"],
            allow_voice_confirm=False,
            timeout_seconds=15,
            signature_required=intent in SIGNATURE_REQUIRED_INTENTS)
        decision = client.wait_for_write_confirmation()
        confirmed = decision.get("action") == "confirm_button"
        return {"confirmed":             confirmed,
                "confirmation_required": True,
                "confirmation_method":   "button_press"}

    # Step 5D: unknown classification: never auto-execute. The
    # safe default is to not act on a command we cannot place
    # on the read-write spectrum.
    return {"confirmed":             False,
            "confirmation_required": True,
            "confirmation_method":   None,
            "disposition":           "unclassified_no_execute"}
```

---

## Step 6: Execute Against the EHR and Reflect the Result

*The pseudocode calls this `execute_command(...)`. The execution layer translates the structured command into one or more EHR API calls. SMART on FHIR is the preferred path; vendor-specific platforms are next; UI automation is the fallback (and is the integration model of last resort). The result either updates the EHR's display directly or returns data that the voice-navigation client renders alongside the EHR. Capture every API call's outcome for the audit log. Skip detailed audit and you have no way to reconstruct what the system did when something goes wrong later.*

```python
def execute_command(enriched_command, session_context):
    """
    Translate the structured command to one or more EHR API
    calls and execute them. Returns an execution-log dict that
    feeds the audit step.
    """
    intent     = enriched_command["intent"]
    slots      = enriched_command.get("slots", {})
    patient_id = enriched_command.get("resolved_patient_id")
    session_id = session_context["session_id"]

    execution_log = {
        "intent":     intent,
        "slots":      dict(slots),
        "patient_id": patient_id,
        "started_at": _now_iso(),
        "ehr_api_calls": [],
    }

    try:
        if intent == "open_patient":
            # Production: ehr_api.open_patient_chart(
            #     patient_id=patient_id,
            #     clinician_token=session_context["access_token"])
            api_started = _now_iso()
            result = ehr.open_patient_chart(patient_id)
            execution_log["ehr_api_calls"].append({
                "endpoint":    "/Patient/$set-active",
                "method":      "POST",
                "params":      {"patient_id": patient_id},
                "status":      result.get("status"),
                "started_at":  api_started,
                "completed_at": _now_iso(),
            })
            execution_log["ehr_result"] = result

        elif intent == "show_recent_results":
            api_started = _now_iso()
            result = ehr.fetch_observations(
                patient_id=patient_id,
                category=slots.get("result_type", "laboratory"),
                count=int(slots.get("count", 10)),
                sort="-date")
            execution_log["ehr_api_calls"].append({
                "endpoint":    "/Observation",
                "method":      "GET",
                "params":      {"patient": patient_id,
                                "category":
                                    slots.get("result_type",
                                              "laboratory")},
                "status":      result.get("status"),
                "started_at":  api_started,
                "completed_at": _now_iso(),
            })
            client.render_results_panel(result)
            execution_log["ehr_result"] = result

        elif intent == "open_note":
            note_type = slots.get("note_type")
            api_started = _now_iso()
            note_id = ehr.find_note(
                patient_id=patient_id,
                note_type=note_type,
                date=slots.get("date"),
                author=slots.get("author"))
            execution_log["ehr_api_calls"].append({
                "endpoint":    "/DocumentReference",
                "method":      "GET",
                "params":      {"patient": patient_id,
                                "type":    note_type,
                                "date":    slots.get("date")},
                "status":      "200" if note_id else "404",
                "started_at":  api_started,
                "completed_at": _now_iso(),
            })
            if note_id:
                api_started = _now_iso()
                result = ehr.open_note_in_ehr(note_id)
                execution_log["ehr_api_calls"].append({
                    "endpoint":    f"/Composition/{note_id}",
                    "method":      "GET",
                    "status":      result.get("status"),
                    "started_at":  api_started,
                    "completed_at": _now_iso(),
                })
                execution_log["ehr_result"] = result
            else:
                client.emit_user_message("No matching note found.")
                execution_log["ehr_result"] = {"status": "not_found"}

        elif intent == "navigate_section":
            api_started = _now_iso()
            result = ehr.set_chart_section(
                patient_id=patient_id,
                section=slots.get("section"))
            execution_log["ehr_api_calls"].append({
                "endpoint":    "/Patient/$set-section",
                "method":      "POST",
                "params":      {"patient_id": patient_id,
                                "section":    slots.get("section")},
                "status":      result.get("status"),
                "started_at":  api_started,
                "completed_at": _now_iso(),
            })
            execution_log["ehr_result"] = result

        else:
            execution_log["ehr_result"] = {"status": "unsupported_intent"}

        execution_log["completed_at"] = _now_iso()
        execution_log["status"]       = "success"

    except Exception as err:
        execution_log["completed_at"] = _now_iso()
        execution_log["status"]       = "ehr_api_error"
        execution_log["error"]        = str(err)
        client.emit_user_message(
            "EHR is not responding. Try again or use the keyboard.")

    # Step 6B: update the voice-system session context to reflect
    # the EHR state change. The "EHR is source of truth" rule
    # means we re-derive context from the EHR on the next
    # command anyway, but updating here keeps in-flight state
    # consistent for the audit trail.
    if execution_log["status"] == "success" and patient_id:
        session_state.update(session_id, {
            "current_patient_id": patient_id,
            "current_section":    slots.get(
                "section", enriched_command.get("current_section")),
            "last_command_at":    execution_log["completed_at"],
        })

    return execution_log
```

---

## Step 7: Audit and Emit Telemetry

*The pseudocode calls this `audit_and_telemetry(...)`. Every command is recorded with the full pipeline detail: original transcript, parsed intent, resolved slots, confirmation event (if any), execution result. The audit feeds two consumers: the durable HIPAA-grade audit log (DynamoDB plus S3 archive via Firehose with Object Lock) and the operational telemetry layer (CloudWatch metrics, EventBridge events). Skip the durable audit and you cannot reconstruct what the system did during an investigation or quality review.*

```python
def audit_and_telemetry(enriched_command, confirmation_result,
                         execution_log, session_context,
                         activation_at):
    """
    Write the durable audit record, emit the cross-system
    EventBridge event, and emit operational CloudWatch metrics.
    """
    session_id = session_context["session_id"]

    # Step 7A: idempotency check. If the same transcript-hash
    # was just recorded for this session within a short window,
    # treat the duplicate as a re-fire and short-circuit. The
    # production version uses a conditional DynamoDB write keyed
    # on (session_id, transcript_hash, second-bucket).
    duplicate = command_audit.find_recent_for_idempotency(
        clinician_id=session_context["clinician_id"],
        session_id=session_id,
        transcript_hash=enriched_command.get("transcript_hash"),
        window_seconds=10)
    if duplicate:
        audit_log({
            "event_type":   "DUPLICATE_COMMAND_SUPPRESSED",
            "session_id":   session_id,
            "command_id":   duplicate.get("command_id"),
            "timestamp":    _now_iso(),
        })
        return duplicate

    # Step 7B: durable audit record. The HIPAA-grade record of
    # who issued what command, against which patient, with what
    # outcome.
    command_id = "cmd-" + uuid.uuid4().hex[:16]
    now = _now_iso()
    audit_record = _to_decimal({
        "command_id":             command_id,
        "clinician_id":           session_context["clinician_id"],
        "device_id":               session_context["device_id"],
        "session_id":             session_id,
        "smart_on_fhir_launch_id":
            session_context.get("launch_id"),
        "timestamp":              now,
        "activation_at":          activation_at,
        "transcript":             enriched_command.get("transcript"),
        "transcript_hash":
            enriched_command.get("transcript_hash"),
        "transcript_avg_confidence":
            enriched_command.get("avg_confidence"),
        "transcript_min_confidence":
            enriched_command.get("min_confidence"),
        "intent":                 enriched_command.get("intent"),
        "intent_confidence":
            enriched_command.get("intent_confidence"),
        "slots":                  enriched_command.get("slots"),
        "read_write_classification":
            enriched_command.get("read_write"),
        "classifier_used":
            enriched_command.get("classifier_used"),
        "resolved_patient_id":
            enriched_command.get("resolved_patient_id"),
        "ehr_snapshot_id":
            enriched_command.get("ehr_snapshot_id"),
        "confirmation_required":
            confirmation_result.get("confirmation_required"),
        "confirmation_method":
            confirmation_result.get("confirmation_method"),
        "confirmation_outcome":
            confirmation_result.get("confirmed"),
        "execution_status":       execution_log.get("status"),
        "execution_started_at":   execution_log.get("started_at"),
        "execution_completed_at": execution_log.get("completed_at"),
        "ehr_api_calls":          execution_log.get("ehr_api_calls", []),
        "bot_version":            BOT_VERSION,
        "intent_taxonomy_version": INTENT_TAXONOMY_VERSION,
        "threshold_config_version": THRESHOLD_CONFIG_VERSION,
        "read_write_rules_version": READ_WRITE_RULES_VERSION,
    })
    command_audit.put(audit_record)

    # Step 7C: cross-system event for the analytics layer and
    # the EHR's audit overlay (where one is integrated).
    event_bus.put_events([{
        "Source":       "voice.navigation",
        "DetailType":   "command_executed",
        "EventBusName": VOICE_NAV_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "command_id":      command_id,
            "clinician_id":    session_context["clinician_id"],
            "patient_id":
                enriched_command.get("resolved_patient_id"),
            "intent":          enriched_command.get("intent"),
            "execution_status": execution_log.get("status"),
            "timestamp":       now,
        }),
    }])

    # Step 7D: operational metrics. These feed dashboards that
    # surface latency regressions, accuracy drift, and adoption
    # trends. Per-clinician and per-intent dimensions let the
    # equity-monitoring committee detect subgroup disparities.
    try:
        completed_dt = datetime.fromisoformat(
            execution_log["completed_at"].replace("Z", "+00:00"))
        activation_dt = datetime.fromisoformat(
            activation_at.replace("Z", "+00:00"))
        latency_seconds = (completed_dt - activation_dt).total_seconds()
    except (KeyError, ValueError, TypeError):
        latency_seconds = 0.0

    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "CommandLatency",
        latency_seconds, "Seconds",
        dimensions={"intent":  enriched_command.get("intent", "unknown"),
                    "outcome": execution_log.get("status", "unknown")})
    cloudwatch.put_metric(
        CLOUDWATCH_NAMESPACE, "CommandsExecuted", 1, "Count",
        dimensions={"intent":  enriched_command.get("intent", "unknown"),
                    "outcome": execution_log.get("status", "unknown")})
    if confirmation_result.get("confirmation_required"):
        cloudwatch.put_metric(
            CLOUDWATCH_NAMESPACE, "ConfirmationRequired", 1, "Count",
            dimensions={"read_write":
                          enriched_command.get("read_write", "unknown")})

    audit_log({
        "event_type":   "COMMAND_AUDITED",
        "command_id":   command_id,
        "intent":       enriched_command.get("intent"),
        "outcome":      execution_log.get("status"),
        "timestamp":    now,
    })

    return audit_record
```

---

## Putting It All Together

Here is the full pipeline tied together as a top-level function that simulates a single voice command flowing end-to-end through the seven stages. In a Lambda deployment, the audio-streaming and command-execution stages are separate Lambdas behind API Gateway; the demo orchestrates them inline so you can see the full sequence.

```python
def process_voice_command(session_context):
    """
    End-to-end voice-command processing for a single utterance.
    Assumes the session has already been activated; this runs
    once per push-to-talk press (or wake-word activation).
    """
    activation_at = _now_iso()
    print(f"\n--- Stage 2: stream audio to ASR ---")
    asr_result = stream_audio_to_asr(session_context)
    print(f"  proceed: {asr_result['proceed']}")
    if not asr_result["proceed"]:
        print(f"  disposition: {asr_result.get('disposition')}")
        return {"status": "asr_low_confidence",
                "session_id": session_context["session_id"]}

    print(f"\n--- Stage 3: parse command ---")
    parsed = parse_command(asr_result, session_context)
    print(f"  intent: {parsed['intent']}")
    print(f"  intent_confidence: "
          f"{float(parsed['intent_confidence']):.2f}")
    print(f"  slots: {parsed['slots']}")
    print(f"  read_write: {parsed['read_write']}")
    print(f"  classifier_used: {parsed['classifier_used']}")

    if not parsed["proceed"]:
        execution_log = {
            "status":          "unknown_intent",
            "started_at":      activation_at,
            "completed_at":    _now_iso(),
            "ehr_api_calls":   [],
            "ehr_result":      {"status": "unknown_intent"},
        }
        confirmation_result = {
            "confirmed":             False,
            "confirmation_required": False,
            "confirmation_method":   None,
        }
        client.emit_user_message(
            "I didn't understand that command. Try again?")
        audit_and_telemetry(parsed, confirmation_result,
                              execution_log, session_context,
                              activation_at)
        return {"status": "unknown_intent",
                "session_id": session_context["session_id"]}

    print(f"\n--- Stage 4: resolve context ---")
    enriched = resolve_context(parsed, session_context)
    if not enriched["proceed"]:
        print(f"  disposition: {enriched.get('disposition')}")
        execution_log = {
            "status":          enriched.get("disposition"),
            "started_at":      activation_at,
            "completed_at":    _now_iso(),
            "ehr_api_calls":   [],
            "ehr_result":      {"status": enriched.get("disposition")},
        }
        confirmation_result = {
            "confirmed":             False,
            "confirmation_required": True,
            "confirmation_method":   None,
        }
        # Add the disposition into the audit-bound command. The
        # disposition itself is the audit-relevant signal here,
        # not just the unexecuted command.
        parsed["resolved_patient_id"] = None
        parsed["ehr_snapshot_id"]     = None
        audit_and_telemetry(parsed, confirmation_result,
                              execution_log, session_context,
                              activation_at)
        return {"status": enriched.get("disposition"),
                "session_id": session_context["session_id"]}
    print(f"  resolved_patient_id: {enriched['resolved_patient_id']}")

    print(f"\n--- Stage 5: confirm ---")
    confirmation_result = confirm_command(enriched)
    print(f"  confirmed: {confirmation_result['confirmed']}")
    print(f"  confirmation_required: "
          f"{confirmation_result['confirmation_required']}")

    if not confirmation_result["confirmed"]:
        execution_log = {
            "status":          "user_cancelled",
            "started_at":      activation_at,
            "completed_at":    _now_iso(),
            "ehr_api_calls":   [],
            "ehr_result":      {"status": "user_cancelled"},
        }
        audit_and_telemetry(enriched, confirmation_result,
                              execution_log, session_context,
                              activation_at)
        return {"status": "user_cancelled",
                "session_id": session_context["session_id"]}

    print(f"\n--- Stage 6: execute ---")
    execution_log = execute_command(enriched, session_context)
    print(f"  status: {execution_log['status']}")
    print(f"  ehr api calls: {len(execution_log['ehr_api_calls'])}")

    print(f"\n--- Stage 7: audit + telemetry ---")
    audit_record = audit_and_telemetry(
        enriched, confirmation_result,
        execution_log, session_context, activation_at)
    print(f"  command_id: {audit_record.get('command_id')}")

    return {
        "status":     execution_log["status"],
        "command_id": audit_record.get("command_id"),
        "session_id": session_context["session_id"],
    }

def run_demo():
    """
    Run a small set of end-to-end scenarios that exercise the
    main paths through the voice-navigation pipeline:
      1. High-confidence read command: open a patient on today's
         schedule. Auto-executes; chart opens.
      2. Open-note read command with date slot: opens the
         operative note from a specific date for the current
         patient.
      3. Ambiguous patient slot: two patients named Smith on
         today's schedule trigger the disambiguation prompt;
         the system does NOT silently pick.
      4. Low-confidence ASR: transcript confidence below the
         gate, returns "I didn't catch that."
      5. Show recent results for the current patient: read
         command using EHR-current-patient context rather than
         a slot.
    """
    global transcribe_mock, lex_mock, bedrock_mock

    # --- Fixture data for the mocks ---
    # Each session_id below is keyed deterministically so the
    # MockTranscribeStreaming returns the right transcript per
    # scenario. The demo registers the fixture under the
    # session_id that activate_session generates by injecting it
    # before the audio stream runs.
    transcript_fixtures = {}  # filled in per scenario below

    intent_fixtures = {
        "open patient margaret": {
            "intent": {
                "name":             "open_patient",
                "confidence_score": 0.93,
                "slots":            {"patient": "Margaret Chen"},
            },
            "interpretations": [],
        },
        "open patient smith": {
            "intent": {
                "name":             "open_patient",
                "confidence_score": 0.91,
                "slots":            {"patient": "Smith"},
            },
            "interpretations": [],
        },
        "open the operative note": {
            "intent": {
                "name":             "open_note",
                "confidence_score": 0.89,
                "slots":            {"note_type": "operative-note",
                                      "date":      "october fourteenth"},
            },
            "interpretations": [],
        },
        "show last labs": {
            "intent": {
                "name":             "show_recent_results",
                "confidence_score": 0.94,
                "slots":            {"result_type": "laboratory",
                                      "count":       5},
            },
            "interpretations": [],
        },
    }

    bedrock_fallback_fixtures = {
        # The Bedrock fallback would catch unusual phrasings
        # that Lex misses. Not exercised in the demo's main
        # paths, but the fixture is here for completeness.
        "let me see the recent": {
            "intent":             "show_recent_results",
            "intent_confidence":  0.86,
            "slots":              {"result_type": "laboratory",
                                    "count":       10},
            "rationale":          ("Treat as request for recent "
                                    "lab results."),
        },
    }

    # Wire up the mocks with fixtures.
    transcribe_mock = MockTranscribeStreaming(transcript_fixtures)
    lex_mock        = MockLex(intent_fixtures)
    bedrock_mock    = MockBedrock(bedrock_fallback_fixtures)

    # Common SMART on FHIR launch context for the demo.
    smart_context_template = {
        "launch_id":    "launch-1a2b3c4d",
        "access_token": "<placeholder access token>",
        "issued_at":    _now_iso(),
        "encounter_id": "enc-2026-05-23-01",
    }

    schedule_today = ["Margaret Chen", "Robert Smith",
                       "James Patel"]
    providers = ["Dr. Lee", "Dr. Patel", "Dr. Nguyen"]

    scenarios = [
        {
            "name": "high_confidence_open_patient",
            "transcript_text":
                "open patient Margaret Chen",
            "items": [
                {"alternatives": [{"confidence": "0.95"}]},
                {"alternatives": [{"confidence": "0.93"}]},
                {"alternatives": [{"confidence": "0.94"}]},
                {"alternatives": [{"confidence": "0.92"}]},
            ],
            "smart_context_patient": None,  # No EHR context yet
        },
        {
            "name": "open_operative_note_with_date",
            "transcript_text":
                "open the operative note from October fourteenth",
            "items": [
                {"alternatives": [{"confidence": "0.93"}]},
                {"alternatives": [{"confidence": "0.91"}]},
                {"alternatives": [{"confidence": "0.94"}]},
                {"alternatives": [{"confidence": "0.92"}]},
                {"alternatives": [{"confidence": "0.90"}]},
                {"alternatives": [{"confidence": "0.89"}]},
                {"alternatives": [{"confidence": "0.93"}]},
            ],
            "smart_context_patient": "pt-44219-3c",  # Margaret Chen
        },
        {
            "name": "ambiguous_smith_disambiguation",
            "transcript_text":
                "open patient Smith",
            "items": [
                {"alternatives": [{"confidence": "0.92"}]},
                {"alternatives": [{"confidence": "0.93"}]},
                {"alternatives": [{"confidence": "0.91"}]},
            ],
            "smart_context_patient": None,
        },
        {
            "name": "low_asr_confidence_repeat",
            "transcript_text":
                "uh open something maybe",
            "items": [
                {"alternatives": [{"confidence": "0.40"}]},
                {"alternatives": [{"confidence": "0.38"}]},
                {"alternatives": [{"confidence": "0.42"}]},
                {"alternatives": [{"confidence": "0.35"}]},
            ],
            "smart_context_patient": None,
        },
        {
            "name": "show_last_labs_for_current_patient",
            "transcript_text":
                "show last labs",
            "items": [
                {"alternatives": [{"confidence": "0.94"}]},
                {"alternatives": [{"confidence": "0.95"}]},
                {"alternatives": [{"confidence": "0.93"}]},
            ],
            "smart_context_patient": "pt-44219-3c",
        },
    ]

    for scenario in scenarios:
        print("\n" + "#" * 60)
        print(f"# SCENARIO: {scenario['name']}")
        print("#" * 60)

        # Activate a fresh session per scenario.
        smart_context = dict(smart_context_template)
        smart_context["patient_id"] = scenario["smart_context_patient"]
        # Set the EHR's "current state" to match the SMART
        # context so resolve_context observes a realistic state.
        ehr.set_current_patient(
            scenario["smart_context_patient"] or None,
            section="summary" if scenario["smart_context_patient"]
                                else "schedule")

        session_context = activate_session(
            device_id="rolling-cart-room4",
            clinician_id="user-jdoe",
            smart_on_fhir_context=smart_context,
            activation_mode="push_to_talk",
            schedule_for_today=schedule_today,
            providers_in_practice=providers)

        # Inject the per-scenario transcript fixture under the
        # session_id that was just generated, so the streaming
        # mock can return the right transcript when asked.
        transcript_fixtures[session_context["session_id"]] = {
            "transcript_text": scenario["transcript_text"],
            "items":           scenario["items"],
        }

        # Run a single voice command end-to-end.
        result = process_voice_command(session_context)
        print(f"\n  >>> result.status: {result['status']}")

    # --- Print a summary ---
    print("\n" + "=" * 60)
    print("DEMO SUMMARY")
    print("=" * 60)
    print(f"Audit records written:      "
          f"{len(command_audit._records)}")
    print(f"Cross-system events emitted: "
          f"{len(event_bus.events)}")
    print(f"CloudWatch metrics emitted:  "
          f"{len(cloudwatch.metrics)}")
    print(f"Client events emitted:       {len(client.events)}")
    print()
    print("Audit record outcomes:")
    for record in command_audit._records:
        print(f"  - intent={record.get('intent'):<24} "
              f"outcome={record.get('execution_status')}")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    run_demo()
```

> **A note on the demo's mocks.** Real Transcribe, Lex, and Bedrock calls receive the actual audio (or transcript text) and return real classifications. The demo's mocks use fixture lookups so the same scenario always produces the same output, which makes the rest of the pipeline deterministic for teaching purposes. The fixtures match on session_id (for Transcribe) and on transcript substring (for Lex and Bedrock). This is enough to demonstrate the activation-feedback pattern, the confidence-gate behavior, the patient-slot disambiguation, and the read-write asymmetric confirmation, without needing a working bot deployment to run the file.

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right command audit records, but the distance between it and a real voice-navigation pipeline running on rolling carts in clinical exam rooms is significant. Here is where that distance lives.

**Real API Gateway WebSocket plus per-stage Lambdas.** The demo orchestrates stages in Python. Production fronts the streaming audio with API Gateway's WebSocket API (with a Cognito authorizer and the SMART on FHIR access token validated on connect), routes audio frames to an audio-stream-handler Lambda (or an ECS task for longer-lived sessions), and routes the finalized transcript to a command-executor Lambda. Each Lambda has its own IAM role, error handling, retries, and DLQs. The boundary is: API Gateway handles transport; each Lambda handles one stage's logic.

**Real Transcribe streaming wiring.** The demo mocks the streaming ASR. Production calls `transcribe_client.start_stream_transcription` with `MediaSampleRateHertz=16000`, `LanguageCode="en-US"`, `EnablePartialResultsStabilization=True`, `PartialResultsStability="high"`, and either a custom-vocabulary name or per-request biasing terms. The audio frames are pushed through the streaming session as they arrive from the WebSocket; partial transcripts are emitted back to the client for visual feedback ("listening: open patient..."); the final transcript emits when end-of-utterance is detected (button release). The streaming connection is bounded: long-running streams run as ECS tasks (with WebSocket fronting) rather than Lambdas because Lambda's 15-minute execution limit is plenty for individual commands but inadequate for always-on listening.

**Real Lex bot definition and bot-version pinning.** The demo's MockLex uses fixture lookups. Production has a Lex V2 bot defined in the console (or via CloudFormation/CDK) with all the navigation intents, sample utterances per intent, slot types (built-in for dates and persons, custom slot types for sections, note types, and result types), and dialog-management configuration. The bot is versioned; the alias (`LEX_BOT_ALIAS_ID`) points at a specific version, and version promotion goes through review. Bot configuration changes are tracked in source control alongside the Lambda code.

**Real Bedrock invocation, prompt management, and inference profile.** The demo's MockBedrock uses fixture lookups. Production calls `bedrock_runtime.invoke_model` with `modelId=BEDROCK_INFERENCE_PROFILE_ARN` (the inference profile is what you pass for cross-region inference and per-profile rate limits), a real prompt that includes a system instruction, the intent taxonomy, slot schemas, a small set of curated few-shot examples, and a strict-JSON output schema. The prompt is versioned and deployed alongside the rest of the pipeline; prompt changes go through review (the prompt is a load-bearing safety artifact at this point, not a config string). Model output is parsed and validated against the taxonomy; out-of-taxonomy values trigger "unknown" rather than passing through.

**Per-Lambda IAM roles.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda (audio-stream-handler, command-executor, audit-writer, telemetry-emitter, EHR-integration-adapter), each scoped to the specific resource ARNs the Lambda touches. The command-executor role has scoped Lex invocation rights, scoped Bedrock invocation rights pinned to one model and one inference profile, scoped Secrets Manager read rights for the EHR API credentials, and write access to the audit table and the EventBridge bus. The audio-stream-handler role has scoped Transcribe streaming rights and write access only to the in-flight session-state record. Wildcard actions and resources will fail any serious IAM review.

**Real DynamoDB wiring with KMS and PITR.** The mocks in the demo are dictionaries; production is DynamoDB tables (session-state with TTL on idle sessions, command-audit partitioned by clinician_id with command_id sort key, configuration partitioned by config-key) with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery enabled, DynamoDB Streams emitting change events, and Global Tables if multi-region failover is part of the disaster-recovery plan. The audit table has Streams enabled feeding a Kinesis Firehose delivery stream that writes to S3 with Object Lock in compliance mode for HIPAA-grade durability.

**Customer-managed KMS keys, per data class.** Every PHI-bearing resource (audio bucket if retained, audit-log bucket, session-state table, command-audit table, configuration table, Lambda environment variables, CloudWatch Logs, Secrets Manager) uses customer-managed KMS keys with key rotation enabled. Different keys per data class for blast-radius containment: a compromised audit-bucket key does not compromise the session-state table. CloudTrail logs every key-usage event. The institutional KMS-key-management runbook specifies rotation cadence, access review cadence, and the cross-account key-grant pattern for any cross-account integrations.

**VPC and VPC endpoints.** Lambdas that call back-office APIs (the EHR FHIR endpoint in particular) run in a VPC with private subnets that route traffic through a controlled egress path (private-link to a cloud-hosted EHR, or a VPN/Direct Connect to an on-premises EHR system). VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, EventBridge, CloudWatch Logs, Bedrock, Lex, and Transcribe keep AWS-internal traffic on the AWS backbone rather than traversing NAT and the public internet. Endpoint policies pin access to the specific resources the pipeline uses.

**SMART on FHIR launch and authorization.** The demo hand-waves the SMART on FHIR launch. Production implements the full SMART App Launch flow: the EHR launches the voice-navigation app with a `launch` parameter and an `iss` URL pointing at the EHR's FHIR base; the app exchanges these for an authorization code via the EHR's authorization endpoint, exchanges the code for an access token, and uses the token to call FHIR endpoints with the clinician's permissions. For backend-services authentication (JWT-signed assertions with a registered key set), the signing key lives in Secrets Manager, the app retrieves it once per token-refresh cycle, and the JWT is signed and exchanged for the access token. The launch context's patient ID, encounter ID, and clinician identity flow into the voice-navigation session as established context.

**EHR-side audit-overlay integration.** Voice-driven EHR access produces audit events in the voice system. Many institutions also need those events to land in the EHR's native audit log so the patient's chart-access record is complete from the EHR's perspective. The integration is via FHIR `AuditEvent` resources where the EHR supports them, or via vendor-specific audit APIs (Epic and Oracle Health both have audit-write APIs). The demo emits to EventBridge; production additionally fans out to the EHR's audit overlay with the appropriate `AuditEvent` resource shape.

**Per-axis confidence-threshold calibration.** The thresholds in the demo are placeholder values (`ASR_MIN_AVG_CONFIDENCE`, `INTENT_CONFIDENCE_THRESHOLD`, `READ_AUTO_CONFIDENCE_THRESHOLD`, `BEDROCK_FALLBACK_CONFIDENCE_THRESHOLD`). Production calibrates them against real traffic: collect a labeled sample of production transcripts (intent classification was correct or incorrect, slot extraction was correct or incorrect), build precision-recall curves per axis at various confidence thresholds, and pick the thresholds that achieve the institution's chosen precision floors. Calibration is per-axis (ASR confidence is calibrated independently from classifier confidence), per-intent (read intents tolerate lower confidence than write intents), and ongoing (recalibrate as the underlying models update).

**Subgroup-stratified accuracy monitoring.** The demo emits CloudWatch metrics with `intent` and `outcome` dimensions. Production additionally stratifies by clinician dimensions (per-clinician accuracy, per-clinician language background where it can be inferred, per-clinician ASR confidence distribution) so the equity-monitoring committee can detect disparities. Disparities exceeding configured thresholds alert. The metric is institutionally important; name an owner (the equity-monitoring committee or the clinical-quality officer) and review monthly.

**Idempotency at every command.** The demo's idempotency check is a transcript-hash lookup in a window. Production uses a conditional DynamoDB write keyed on `(clinician_id, session_id, transcript_hash, second-bucket)` so a duplicate command (network blip, double button press, EventBridge re-delivery) is rejected with `ConditionalCheckFailedException` rather than producing two executions. Configure DLQs on every Lambda; alarm on DLQ depth.

**Patient slot resolution against the patient index, not just today's schedule.** The demo searches today's schedule. Production additionally consults the patient-index pipeline (recipe 5.1) to handle: patients not on the day's schedule (urgent walk-ins, unscheduled consults), patients spoken as nicknames or honorifics, patients whose names involve non-Latin character sets, accents, or non-standard romanizations, patients with similar names whose disambiguation requires more than first name (DOB, MRN, clinic location). Pilot the resolution logic against a representative slice of the institution's patient name distribution before launch.

**Voice-write boundary as a clinical safety document.** No intents are in the write set in this demo. Production's expansion of voice-write capabilities is governed by clinical operations: the list of write-class intents, the confirmation requirements per intent, and the audit-trail expectations form a clinical safety policy. The list is conservative at MVP and expands only with deliberate review. Voice-driven medication-order signing, clinical-note signing, and medication reconciliation completion are out of scope for this recipe; the dictation and CPOE recipes (10.4 and beyond) handle those more carefully.

**Activation hardware and device control channel.** The demo emits structured `activation_feedback` events. Production drives device hardware: a USB or Bluetooth HID push-to-talk button on the rolling cart, a foot pedal in procedural environments, or a headset button for power users. The device-control channel sits alongside the audio stream and lets the voice app blink an LED, play a tone, or update an on-screen indicator within the latency budget that makes the system feel responsive. Without this, the user is talking to a system that gives no feedback.

**Continuous adaptation workflow.** Production transcripts surface intents the original taxonomy missed, command patterns the classifier handles poorly, and patient-name pronunciations the slot extractor mangles. The improvement workflow (review production transcripts and abandoned commands weekly, propose taxonomy and biasing updates, test against a held-out evaluation set, deploy versioned configurations) is a sustained engineering practice, not a launch task. Versioned bot aliases and gradual rollout (a small percentage of traffic against the new bot version, monitor disagreement metrics, promote when the new version performs at parity or better) are standard.

**Multi-language support.** The demo handles English. Production adds Spanish (or other languages relevant to the practice's clinician demographics): per-language Transcribe configurations (custom vocabularies per language), per-language Lex bots (or a multilingual NLU layer), per-language intent example utterances, per-language slot extraction for date and number recognition, per-language confirmation card text. The clinician experience supports per-clinician language preference.

**Disaster recovery and EHR-unavailable handling.** If the EHR API is unreachable (vendor outage, network partition, planned maintenance), voice commands cannot execute. The system must communicate this to the clinician immediately and clearly, and the clinician must be able to fall back to keyboard-and-mouse without restarting anything. Test the failure modes in a staging environment quarterly with synthetic outages.

**On-device or on-premise ASR for air-gapped deployments.** The demo assumes cloud-streaming ASR. Some hospital environments do not permit clinical audio to leave the institutional network. For those deployments, an on-premise ASR alternative is required: an on-prem Transcribe-equivalent service, a private cloud connection that satisfies the institution's network policy, or a hybrid pattern where the audio stays on-prem and only the (de-identified or fully-PHI but on-prem) processing happens in cloud. Plan the air-gapped variant as a separate architectural track.

**Audit retention and access controls.** The audit log captures every command, every chart open, every result view. Retention must satisfy HIPAA's six-year minimum, state-specific medical-records-retention rules, and the institution's regulatory floor. Access to the audit log is on a need-to-know basis and is itself audited (CloudTrail on the audit-log bucket and the audit DynamoDB table). Retention is enforced via S3 lifecycle policies and Object Lock; deletion before retention expiry is impossible. Legal hold capabilities (suspending deletion for specific clinicians or patients during litigation) are configurable.

**Cost monitoring per clinician and per intent.** Different clinicians use the system at very different rates; different intents have very different per-command costs. Per-clinician and per-intent cost dashboards let operations identify outliers and tune accordingly. Build the dashboard.

**Microphone hardware and room acoustics.** A bad microphone in a noisy room produces bad audio that produces bad ASR. The architecture assumes adequate microphone hardware (beamforming preferred, headset for power users); procurement, installation, and maintenance of microphone hardware is non-trivial operational scope that the engineering organization typically does not own. Identify the operational owner early. Investing in microphone hardware yields more accuracy improvement than the same investment in the model layer.

**Clinician training and change management.** The system requires clinicians to learn the command set, the activation pattern, and the failure-mode handling. Most successful deployments include structured training, on-site pilot support during the first week, and a designated point-person for clinician questions. A voice-navigation deployment without change-management investment routinely shows great pilot metrics and stalls at scale.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the patient-slot resolution logic with edge cases (zero matches, unique match, ambiguous match, name with diacritics), unit tests for the confidence-gate logic (low ASR confidence routes to "I didn't catch that"), unit tests for the read-write classification, integration tests against test buckets and tables, and end-to-end tests that simulate full command flows including the disambiguation path. Never use real clinician audio or real patient data in test fixtures; use synthetic Synthea patients and TTS-generated command audio with known ground truth.

**Observability beyond the metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-command investigation. Production runs CloudWatch Logs Insights queries that join across the audio-stream-handler logs, the command-executor logs, and the audit records by command_id. AWS X-Ray traces show the latency contribution of each stage (activation, ASR, intent classification, context resolution, confirmation, execution, audit). When a single command goes wrong, the on-call engineer needs to reconstruct the full trace in seconds, not minutes.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 10.3: Voice-to-Text for EHR Navigation](chapter10.03-voice-to-text-ehr-navigation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
