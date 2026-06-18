# Recipe 10.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 10.1. It shows one way you could translate the natural-language IVR pipeline into working Python using boto3 against Amazon Connect, Amazon Lex V2, AWS Lambda, Amazon DynamoDB, and Amazon EventBridge. The demo uses a `MockLexEvent` standing in for the Lex V2 fulfillment-hook payload that Connect would deliver, a `MockEHR` standing in for the EHR patient-index lookup, a `MockEPrescribing` standing in for the e-prescribing system that actually queues refill requests, and small helpers for the active-call-context store, the call-disposition log, the urgency-lexicon scanner, and CloudWatch-style metrics. It is not production-ready. There is no real Connect contact flow, no real Lex V2 bot definition, no real Polly TTS rendering, no real Step Functions orchestration, no real DynamoDB or EventBridge wiring, no Contact Lens integration, no Voice ID enrollment, no IAM least-privilege role per Lambda, no KMS customer-managed key configuration, no VPC endpoints, no per-state recording-consent disclosure logic, and no fraud-pattern detection on the call stream. Think of it as the sketchpad version: useful for understanding the shape of an IVR routing pipeline that respects the urgency-override discipline, the per-intent confidence-threshold discipline, the verification-before-fulfillment discipline, the eligibility-check-before-action discipline, and the audit-everything discipline this recipe demands. It is not something you would point at the practice's main number on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the five core pseudocode steps from the main recipe: answer the call and play the disclosure (Step 1, modeled here as session initialization), classify and route a Lex turn with urgency override and per-intent confidence thresholding (Step 2), verify the caller before any action that touches PHI (Step 3), fulfill a self-service refill request with eligibility checks (Step 4), and capture the call disposition for analytics (Step 5). The synthetic patients, medications, phone numbers, and intents in the demo are fictional; the names, DOBs, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also configure an Amazon Connect instance with a published phone number, a Lex V2 bot with the intents and slots you want the IVR to handle, a Lex bot alias that points at a specific bot version, a Connect contact flow that hands off audio to the Lex bot, the Lambdas that the Lex bot invokes for fulfillment (one per logical fulfillment domain: caller-verifier, refill-fulfillment, appointment-fulfillment, urgency-escalator), the DynamoDB tables that hold active-call-context and caller-recent-history, the EventBridge bus that fans out IVR-driven actions to downstream systems, the Kinesis Data Stream that consumes Connect's Contact Trace Records, and the S3 buckets for call recordings and CTR archives. The demo replaces all of these with small mocks so the focus stays on the per-turn classification, urgency-override, verification, fulfillment, and disposition logic rather than on the Connect-and-Lex bot-configuration plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem` on the `active-call-context` and `call-disposition-log` tables
- `lex:RecognizeText` for sending utterances to a Lex bot programmatically (the production fulfillment Lambda is invoked by Lex rather than calling Lex itself, but the demo uses `RecognizeText` to simulate the turn flow)
- `events:PutEvents` on the `ivr-events-bus` for emitting cross-system events when the IVR queues a refill or schedules a callback
- `cloudwatch:PutMetricData` for the IVR operational metrics (containment rate, per-intent confidence distribution, urgency-override rate, verification-failure rate)
- `secretsmanager:GetSecretValue` on the EHR-API and e-prescribing-API credentials secrets pinned to the current rotation version
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the active-call-context table, the call-disposition-log table, and the call-recordings bucket
- `connect:UpdateContactAttributes` for writing the IVR-resolved attributes (verified caller, classified intent, slots gathered) onto the Connect contact for screen-pop on agent transfer

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The caller-verifier Lambda has read-only access to the EHR patient-index and write access only to the verification-status fields of active-call-context. The refill-fulfillment Lambda has scoped access to the e-prescribing system's queue-refill API and write access only to the disposition-record. The urgency-escalator Lambda has scoped access to the Connect transfer API for the clinical-triage queue and audit-event emission. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **The urgency lexicon is the safety substrate.** Every utterance is scanned against a versioned list of clinical-urgency phrases before any other routing decision. The lexicon is reviewed quarterly by clinical operations. Skip the urgency scan and you produce the missed-clinical-urgency cases the recipe is for. The lexicon in this demo is illustrative; a real lexicon is a clinical safety document with appropriate versioning and review.
- **Per-intent confidence thresholds are calibrated separately.** "Confirm appointment" can run on lower confidence than "release prescription refill" because the consequences of a wrong action are very different. Re-using one threshold across all intents produces routing-quality compromise: low-stakes intents get over-escalated to agents (containment rate drops); high-stakes intents get acted on at false-positive rates (refills queued for the wrong patient).
- **Caller verification is per-call and per-intent.** Some intents do not require verification ("what are your hours"). Some do (every action that touches PHI or the back office). Verification, once established for a session, persists for that call. The verification policy is intent-dependent and should be configured per intent.
- **Self-service eligibility is checked before fulfillment, not assumed.** Controlled substances, expired prescriptions, prescriptions with no refills remaining, and certain clinical-flag medications are excluded from self-service refill regardless of caller verification. The eligibility check is the safety floor that prevents the IVR from auto-refilling things it shouldn't.
- **Idempotency is built into the fulfillment layer.** The (call_id, intent_name, turn_index) tuple is the idempotency key. A fulfillment Lambda invoked twice (because the dialog turn was retried, because an EventBridge delivery duplicated) does not double-queue a refill or double-emit an audit record.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, and numeric metadata field passes through `Decimal` on its way in and on its way out. This is a recurring SDK gotcha and the `_to_decimal` helper handles it.
- **The example collapses Connect's contact flow, multiple Lex-invoked Lambdas, the EventBridge fan-out, and the CloudWatch metric emission into a single Python file for readability.** In production the contact flow lives in Connect's flow editor, the Lex bot lives in the Lex console, and each fulfillment domain (verification, refill, appointment, urgency-escalation) is a separate Lambda with its own IAM role, error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the per-intent confidence-threshold table, the urgency-lexicon, the verification-policy-per-intent, and the self-service-eligibility rules are what you would change between environments.

```python
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
# to CloudWatch Logs Insights. The IVR pipeline operates on heavily
# PHI-adjacent data: the audio stream is PHI, the transcript is PHI,
# the intent and slots can carry PHI (medication names, condition
# mentions), and the caller's phone number plus DOB plus partial
# phone is the verification material. Log structural metadata only
# (call_id, intent_name, confidence band, urgency flag, decision
# outcome), never raw transcripts, never demographic values, never
# medication names, never any verification material.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, Lex,
# EventBridge, CloudWatch, Secrets Manager, and Connect. The IVR
# response-window expectation is tight: the caller is on the line
# waiting for the system to respond, and a retry storm that adds
# 5 seconds of dead air is operationally worse than a fast failure.
# Cap the retries and let the contact flow's failure path handle
# the fall-back to DTMF or to an agent.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm
# containers so each invocation does not pay the connection cost.
REGION = "us-east-1"
dynamodb           = boto3.resource("dynamodb", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
lex_client         = boto3.client("lexv2-runtime", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
connect_client     = boto3.client("connect", region_name=REGION,
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
ACTIVE_CALL_CONTEXT_TABLE   = "active-call-context"
CALL_DISPOSITION_LOG_TABLE  = "call-disposition-log"
IVR_EVENT_BUS_NAME          = "ivr-events-bus"
CLOUDWATCH_NAMESPACE        = "IVRCallRouting"
CONNECT_INSTANCE_ID         = "00000000-0000-0000-0000-000000000000"
LEX_BOT_ID                  = "PATIENT_BOT_ID_PLACEHOLDER"
LEX_BOT_ALIAS_ID            = "PATIENT_BOT_ALIAS_PROD_PLACEHOLDER"
LEX_LOCALE_ID               = "en_US"

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("ACTIVE_CALL_CONTEXT_TABLE",  ACTIVE_CALL_CONTEXT_TABLE),
    ("CALL_DISPOSITION_LOG_TABLE", CALL_DISPOSITION_LOG_TABLE),
    ("IVR_EVENT_BUS_NAME",         IVR_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",       CLOUDWATCH_NAMESPACE),
    ("CONNECT_INSTANCE_ID",        CONNECT_INSTANCE_ID),
    ("LEX_BOT_ID",                 LEX_BOT_ID),
    ("LEX_BOT_ALIAS_ID",           LEX_BOT_ALIAS_ID),
    ("LEX_LOCALE_ID",              LEX_LOCALE_ID),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every turn record and every routing decision carries the bot
# version, the threshold-config version, and the urgency-lexicon
# version active at decision time. This is how a future audit
# reconstructs which calibration was active when a particular
# call was handled.
BOT_VERSION                 = "patient-bot-v2.4.1"
THRESHOLD_CONFIG_VERSION    = "ivr-thresholds-v1.3.0"
URGENCY_LEXICON_VERSION     = "urgency-lexicon-v1.5.0"
INSTITUTION_ID              = "academic-medical-center-richmond"
INSTITUTION_JURISDICTION    = "state-of-virginia"

# --- Per-Intent Confidence Thresholds ---
# The threshold below which we will not act on the intent. The
# threshold for "release prescription refill" is higher than the
# threshold for "what are your hours" because the consequences
# of a wrong action are very different. In production, these
# come from a config store (Parameter Store or AppConfig) and
# are tuned against production traffic. The values here are
# illustrative starting points.
PER_INTENT_CONFIDENCE_THRESHOLDS = {
    "refill_prescription":   Decimal("0.85"),
    "schedule_appointment":  Decimal("0.75"),
    "confirm_appointment":   Decimal("0.70"),
    "billing_question":      Decimal("0.65"),
    "ask_hours_or_location": Decimal("0.60"),
    "speak_to_nurse":        Decimal("0.70"),
    "operator":              Decimal("0.50"),
    # Fallback for intents not in the table. Keep this
    # conservative; an unknown intent should be routed to an
    # agent rather than acted on at low confidence.
    "_default":              Decimal("0.80"),
}

# --- Urgency Lexicon ---
# A versioned list of phrases that should trigger immediate
# clinical-triage routing, regardless of the intent classifier's
# output. The lexicon is reviewed quarterly with clinical
# operations. New phrases are added when production calls reveal
# misses. Treat this as a clinical safety document.
#
# The list below is illustrative. A real institutional lexicon
# is more comprehensive and is maintained outside the codebase
# in a versioned, reviewable artifact. Do not ship the demo
# lexicon to production.
URGENCY_LEXICON = [
    # Cardiac and respiratory
    "chest pain",
    "chest pressure",
    "can't breathe",
    "cannot breathe",
    "trouble breathing",
    "shortness of breath",
    "heart attack",
    # Stroke symptoms
    "stroke",
    "face drooping",
    "slurred speech",
    "sudden weakness",
    "sudden numbness",
    # Severe symptoms
    "severe pain",
    "worst headache",
    "fainting",
    "passed out",
    "loss of consciousness",
    "uncontrolled bleeding",
    "won't stop bleeding",
    # Mental-health crisis
    "thinking about hurting myself",
    "thinking about killing myself",
    "want to hurt myself",
    "want to end my life",
    "suicidal",
    # Pediatric urgency
    "baby is not breathing",
    "child is not breathing",
    "blue lips",
    # Allergic reaction
    "anaphylaxis",
    "throat closing",
    "tongue swelling",
]

# --- Verification Policy Per Intent ---
# Whether the intent requires caller verification before
# fulfillment. In production this is a richer policy that
# includes the verification method (DOB plus partial phone, DOB
# plus address, full PHI verification for sensitive intents),
# but for the demo a boolean is enough.
INTENT_REQUIRES_VERIFICATION = {
    "refill_prescription":   True,
    "schedule_appointment":  True,
    "confirm_appointment":   True,
    "billing_question":      True,
    "ask_hours_or_location": False,
    "speak_to_nurse":        False,  # Nurse line agent does verification
    "operator":              False,
    "_default":              True,   # When in doubt, verify
}

# --- Self-Service Eligibility Rules ---
# Medications excluded from IVR self-service refill regardless
# of verification. Controlled substances and certain clinical-
# flag medications require a clinical touch. In production this
# list comes from the e-prescribing system's drug database with
# DEA-schedule lookups, not from a hardcoded list. The list
# below is illustrative.
NON_SELF_SERVICE_DRUG_CLASSES = {
    "controlled_substance_schedule_2",
    "controlled_substance_schedule_3",
    "anticoagulant_warfarin",  # Clinical-touch policy at this institution
    "chemotherapy_oral",
    "biologic_injectable",
}

# --- Verification Configuration ---
# The maximum number of verification attempts before transfer
# to an agent. Two is typical; one is too strict, three is too
# lax (the third attempt is rarely the legitimate caller).
MAX_VERIFICATION_ATTEMPTS = 2

# The maximum number of consecutive low-confidence turns before
# transfer. Three is typical; the dialog has clearly broken
# down and continuing wastes the caller's time.
MAX_LOW_CONFIDENCE_TURNS = 3

# Active-call-context TTL. The context expires shortly after
# call completion; we don't need to retain it long-term. The
# call-disposition record is the long-term record.
ACTIVE_CALL_CONTEXT_TTL_SECONDS = 6 * 60 * 60  # 6 hours

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
```

---

## Mock Resources for the Demo

These mocks stand in for the production AWS resources and back-office systems. They are deliberately simple and are not how you would build the real thing. Their purpose is to keep the focus on the IVR routing logic.

```python
class MockEHR:
    """
    Stands in for the EHR patient-index API. In production this
    is a FHIR Patient search call or a direct query against the
    institution's master patient index, with OAuth-based
    authentication, network timeouts, and rate-limit handling.
    The demo holds three patients in memory.
    """
    def __init__(self):
        self._patients = {
            "pat-100001": {
                "patient_id": "pat-100001",
                "first_name": "Margaret",
                "last_name": "Chen",
                "dob": "1958-03-14",
                "phone_on_file": "5715551234",
                "address_on_file": "742 Oak Lane, Richmond VA",
            },
            "pat-100002": {
                "patient_id": "pat-100002",
                "first_name": "James",
                "last_name": "Patel",
                "dob": "1972-09-22",
                "phone_on_file": "8045555678",
                "address_on_file": "1015 River Road, Charlottesville VA",
            },
            "pat-100003": {
                "patient_id": "pat-100003",
                "first_name": "Aisha",
                "last_name": "Johnson",
                "dob": "1985-01-08",
                "phone_on_file": "8045559876",
                "address_on_file": "330 Cedar Court, Richmond VA",
            },
        }

    def lookup_by_phone(self, ani):
        # Strip non-digit characters; the phone-on-file is stored
        # as ten digits with no formatting.
        digits = re.sub(r"\D", "", ani or "")
        return [p for p in self._patients.values()
                if p["phone_on_file"] == digits]

    def lookup_by_dob_and_phone(self, dob, partial_phone, ani):
        # The verification slots are: full DOB, last four digits
        # of the phone on file. The ANI is used as a tiebreaker
        # but is not sufficient on its own (ANI can be spoofed).
        digits = re.sub(r"\D", "", partial_phone or "")
        matches = []
        for p in self._patients.values():
            if p["dob"] != dob:
                continue
            if not p["phone_on_file"].endswith(digits):
                continue
            matches.append(p)
        return matches

class MockEPrescribing:
    """
    Stands in for the e-prescribing system. In production this is
    a Surescripts-compliant API, an Epic/Cerner pharmacy module,
    or an integration with the institution's pharmacy IT vendor.
    The demo holds active medications and queues refill requests
    in memory.
    """
    def __init__(self):
        self._active_meds = {
            "pat-100001": [
                {
                    "medication_id": "med-001",
                    "name": "lisinopril",
                    "strength": "10 mg",
                    "drug_class": "ace_inhibitor",
                    "refills_remaining": 3,
                    "expiration_date": "2026-12-31",
                },
                {
                    "medication_id": "med-002",
                    "name": "atorvastatin",
                    "strength": "20 mg",
                    "drug_class": "statin",
                    "refills_remaining": 5,
                    "expiration_date": "2026-09-30",
                },
            ],
            "pat-100002": [
                {
                    "medication_id": "med-003",
                    "name": "metformin",
                    "strength": "500 mg",
                    "drug_class": "biguanide",
                    "refills_remaining": 2,
                    "expiration_date": "2026-08-15",
                },
                {
                    "medication_id": "med-004",
                    "name": "warfarin",
                    "strength": "5 mg",
                    "drug_class": "anticoagulant_warfarin",
                    "refills_remaining": 1,
                    "expiration_date": "2026-07-15",
                },
            ],
            "pat-100003": [
                {
                    "medication_id": "med-005",
                    "name": "oxycodone",
                    "strength": "5 mg",
                    "drug_class": "controlled_substance_schedule_2",
                    "refills_remaining": 0,
                    "expiration_date": "2026-06-30",
                },
            ],
        }
        self.queued_refills = []

    def get_active_medications(self, patient_id):
        return list(self._active_meds.get(patient_id, []))

    def queue_refill_request(self, patient_id, medication_id,
                              requested_via, requested_at,
                              idempotency_key):
        # Idempotency check: if the same idempotency key is seen
        # twice, return the existing refill_request_id rather
        # than queuing a duplicate. In production, DynamoDB
        # conditional writes or e-prescribing-system support
        # for idempotency tokens handle this.
        for existing in self.queued_refills:
            if existing["idempotency_key"] == idempotency_key:
                return existing["refill_request_id"]

        refill_request_id = f"rx-req-{uuid.uuid4().hex[:8]}"
        self.queued_refills.append({
            "refill_request_id":  refill_request_id,
            "patient_id":         patient_id,
            "medication_id":      medication_id,
            "requested_via":      requested_via,
            "requested_at":       requested_at,
            "idempotency_key":    idempotency_key,
        })
        return refill_request_id

class MockActiveCallContext:
    """
    Stands in for the DynamoDB active-call-context table. The
    real table has a TTL attribute so entries expire shortly
    after call completion; the demo holds them in memory.
    """
    def __init__(self):
        self._items = {}

    def put(self, item):
        self._items[item["call_id"]] = dict(item)

    def get(self, call_id):
        return dict(self._items.get(call_id, {}))

    def update(self, call_id, updates):
        if call_id not in self._items:
            self._items[call_id] = {"call_id": call_id}
        self._items[call_id].update(updates)

class MockCallDispositionLog:
    """
    Stands in for the DynamoDB call-disposition-log table. This
    is the long-term record of what happened on the call:
    intents classified, slots gathered, fulfillment outcomes,
    and the end reason. Analytics reads from here for
    containment-rate, per-intent-accuracy, and subgroup-
    stratified-accuracy reporting.
    """
    def __init__(self):
        self.records = []

    def put(self, record):
        self.records.append(dict(record))

class MockEventBus:
    """
    Stands in for Amazon EventBridge. The IVR emits events for
    cross-system fan-out: a refill queued, a callback scheduled,
    an escalation logged. Downstream consumers (analytics, the
    care-management platform, the agent-desktop screen-pop) pick
    these up and react.
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
ehr                  = MockEHR()
e_prescribing        = MockEPrescribing()
active_call_context  = MockActiveCallContext()
call_disposition_log = MockCallDispositionLog()
event_bus            = MockEventBus()
cloudwatch           = MockCloudWatch()

def audit_log(event):
    """
    In production, audit events go to a tamper-resistant store
    (Object-Lock S3, an append-only DynamoDB table, or a SIEM).
    The demo prints a sanitized summary so you can see the
    sequence of decisions without leaking the underlying values.
    """
    safe_event = {
        k: v for k, v in event.items()
        if k not in {"transcript", "dob", "partial_phone",
                      "medication_name", "patient_demographics"}
    }
    if "transcript" in event:
        safe_event["transcript_length"] = len(event["transcript"] or "")
    logger.info("AUDIT %s", json.dumps(safe_event, default=str))
```

---

## Step 1: Initialize the Call Session

*The pseudocode calls this `ON inbound_call(call_id, ani, dnis)`. In the real Connect contact flow, this is the entry state: Connect picks up the call, plays the recording-and-privacy disclosure, then hands off to the Lex bot for the initial open-ended prompt. The Python demo simulates the session-initialization side of that handoff: write the active-call-context entry that subsequent turns and Lambdas read from. The actual disclosure playback is a Connect contact-flow step, not Python code; the disclosure WAV files live in the Connect prompt library and are jurisdiction-aware (some U.S. states are one-party-consent, some are all-party-consent, and the institution's general counsel approves the per-jurisdiction disclosure language).*

```python
def initialize_call_session(call_id, ani, dnis):
    """
    Persist the initial call state at the moment Connect picks
    up the inbound call. Subsequent dialog turns join against the
    call_id; the Lambdas that the Lex bot invokes read the
    context to know whether the caller has been verified, what
    intent the dialog is currently serving, and how many
    consecutive low-confidence turns have occurred.

    In production this is invoked by the Connect contact flow's
    "Invoke AWS Lambda function" step after the recording
    disclosure has played, before the call is handed to the Lex
    bot. The contact flow's parameters carry the call_id (the
    Connect contact identifier), the ani (the caller's phone
    number when not blocked), and the dnis (the dialed-in number,
    which entry-point of the contact flow the caller reached).

    Args:
        call_id: Connect's contact identifier; the join key for
            everything that follows.
        ani: The caller's phone number, or None if blocked.
        dnis: The dialed-in number, indicating which entry point.

    Returns:
        The active-call-context record that was created.
    """
    # ANI-based prefill. If the caller's phone number matches a
    # unique patient record, we capture that as a hint for the
    # later verification step. The match is never sufficient on
    # its own (ANI is spoofable), but it tells the verification
    # step what record to compare against and lets the system
    # personalize the greeting in low-stakes intents.
    ani_matches = ehr.lookup_by_phone(ani) if ani else []

    now = datetime.now(timezone.utc)
    ttl_seconds = int(now.timestamp()) + ACTIVE_CALL_CONTEXT_TTL_SECONDS

    context = {
        "call_id":                       call_id,
        "ani":                           ani,
        "dnis":                          dnis,
        "started_at":                    now.isoformat(),
        "verification_status":           "unverified",
        "verification_failure_count":    0,
        "low_confidence_turn_count":     0,
        "urgency_flag":                  False,
        "intents_classified_history":    [],
        "slots_collected":               {},
        "ani_match_count":               len(ani_matches),
        "ani_matched_patient_id":
            ani_matches[0]["patient_id"] if len(ani_matches) == 1 else None,
        "bot_version":                   BOT_VERSION,
        "threshold_config_version":      THRESHOLD_CONFIG_VERSION,
        "urgency_lexicon_version":       URGENCY_LEXICON_VERSION,
        "ttl":                           ttl_seconds,
    }

    # Production: dynamodb.Table(ACTIVE_CALL_CONTEXT_TABLE).put_item(
    #     Item=_to_decimal(context),
    #     ConditionExpression="attribute_not_exists(call_id)")
    # The conditional write protects against the rare contact-flow
    # retry that re-invokes initialization for the same call_id.
    active_call_context.put(context)

    audit_log({
        "event_type":         "CALL_INITIALIZED",
        "call_id":            call_id,
        "dnis":               dnis,
        "ani_match_count":    len(ani_matches),
        "timestamp":          now.isoformat(),
    })

    cloudwatch.put_metric(
        "CallsInitiated", 1, "Count",
        dimensions={"institution_id": INSTITUTION_ID})

    return context
```

---

## Step 2: Classify and Route a Lex Turn

*The pseudocode calls this `handle_lex_turn(turn_event)`. The Lex bot has performed ASR, intent classification, and slot filling for the caller's most recent utterance. The intent-router Lambda receives the turn result as a fulfillment hook from Lex (Lex calls the Lambda with a structured payload that includes the intent, slots, per-element confidence, and the raw transcript). The Lambda decides what action to take and returns a response that Lex relays back to Connect, which renders the next prompt or executes the action.*

*The order of checks is critical: urgency override runs before anything else. A caller who says "I'm having chest pain and I want to refill my lisinopril" must be routed to clinical triage even though "refill_prescription" is the highest-confidence intent. Skip the urgency override and you produce the missed-clinical-urgency cases the recipe is specifically about preventing.*

```python
def matches_urgency_lexicon(transcript):
    """
    Pattern-match the transcript against the urgency lexicon.

    The match is case-insensitive and substring-based. The
    real-world lexicon is more sophisticated (handles
    morphological variants, near-miss phonetic matches that the
    ASR layer might have produced, and per-language variants),
    but for the demo straightforward substring matching is
    enough.

    Returns the matched phrase if any, else None. Returning the
    phrase rather than a boolean lets the audit log record
    *which* phrase triggered the escalation, which is
    operationally useful for lexicon review.
    """
    if not transcript:
        return None
    lowered = transcript.lower()
    for phrase in URGENCY_LEXICON:
        if phrase in lowered:
            return phrase
    return None

def load_per_intent_threshold(intent_name):
    """
    Look up the per-intent confidence threshold. Falls back to
    the _default threshold if the intent isn't in the table.
    """
    return PER_INTENT_CONFIDENCE_THRESHOLDS.get(
        intent_name, PER_INTENT_CONFIDENCE_THRESHOLDS["_default"])

def handle_lex_turn(turn_event):
    """
    Process a single Lex dialog turn.

    Args:
        turn_event: The Lex V2 fulfillment-hook payload. The
            real payload is documented in the Lex V2 developer
            guide; the demo passes a simplified dict with the
            fields we actually consume.

    Returns:
        A response dict describing the next action: a prompt to
        speak, a queue to transfer to, an internal fulfillment
        to invoke, or a clinical-triage escalation.
    """
    call_id            = turn_event["session_id"]
    transcript         = turn_event.get("input_transcript", "") or ""
    intent_name        = turn_event["intent"]["name"]
    intent_confidence  = Decimal(str(turn_event["intent"]["confidence"]))
    slots              = turn_event["intent"].get("slots", {})
    turn_index         = turn_event.get("turn_index", 0)

    # Step 2A: log the turn so we can audit it later regardless
    # of routing outcome. Every routing decision in this Lambda
    # has to be reconstructable after the fact.
    audit_log({
        "event_type":              "LEX_TURN_RECEIVED",
        "call_id":                 call_id,
        "turn_index":              turn_index,
        "intent_name":             intent_name,
        "intent_confidence":       float(intent_confidence),
        "transcript_length":       len(transcript),
        "transcript":              transcript,
        "bot_version":             BOT_VERSION,
        "threshold_config_version": THRESHOLD_CONFIG_VERSION,
        "urgency_lexicon_version": URGENCY_LEXICON_VERSION,
        "timestamp":               datetime.now(timezone.utc).isoformat(),
    })

    cloudwatch.put_metric(
        "LexTurnsReceived", 1, "Count",
        dimensions={"intent_name": intent_name})

    # Step 2B: urgency override. This runs before any other
    # routing logic. A caller who used an urgent phrase gets
    # routed to clinical triage even if the intent classifier
    # thinks they're calling about something else, and even if
    # the confidence is low. Better to over-escalate than to
    # under-escalate.
    urgency_match = matches_urgency_lexicon(transcript)
    if urgency_match:
        active_call_context.update(call_id, {"urgency_flag": True})

        audit_log({
            "event_type":              "URGENCY_OVERRIDE_TRIGGERED",
            "call_id":                 call_id,
            "matched_phrase":          urgency_match,
            "intent_name":             intent_name,
            "intent_confidence":       float(intent_confidence),
            "urgency_lexicon_version": URGENCY_LEXICON_VERSION,
            "timestamp":               datetime.now(timezone.utc).isoformat(),
        })

        cloudwatch.put_metric(
            "UrgencyOverrideTriggered", 1, "Count",
            dimensions={"matched_phrase_class": "urgency"})

        return {
            "action":   "transfer_clinical_triage",
            "reason":   "urgency_lexicon_match",
            "prompt":
                "I want to make sure you get help right away. "
                "I'm connecting you with our clinical team now. "
                "Please stay on the line.",
        }

    # Step 2C: confidence-based routing. The thresholds are
    # per-intent because the consequences of acting on a wrong
    # intent vary widely. A low-confidence "operator" request is
    # safer to act on than a low-confidence "release prescription
    # refill" request.
    threshold = load_per_intent_threshold(intent_name)

    if intent_confidence < threshold:
        # Below the floor for this intent: don't act on it.
        # Either ask a clarifying question (if we haven't tried
        # too many times) or transfer to an agent.
        ctx = active_call_context.get(call_id)
        new_low_count = ctx.get("low_confidence_turn_count", 0) + 1
        active_call_context.update(call_id, {
            "low_confidence_turn_count": new_low_count,
        })

        cloudwatch.put_metric(
            "LowConfidenceTurn", 1, "Count",
            dimensions={"intent_name": intent_name})

        if new_low_count >= MAX_LOW_CONFIDENCE_TURNS:
            audit_log({
                "event_type": "TRANSFER_REPEATED_LOW_CONFIDENCE",
                "call_id":    call_id,
                "low_confidence_turn_count": new_low_count,
                "timestamp":  datetime.now(timezone.utc).isoformat(),
            })
            return {
                "action": "transfer_general_agent",
                "reason": "repeated_low_confidence",
                "prompt":
                    "Let me get you to someone who can help. "
                    "I'm connecting you now.",
            }

        return {
            "action": "elicit_clarification",
            "reason": "below_intent_threshold",
            "prompt":
                "I'm sorry, I didn't quite catch that. Could you "
                "tell me in a few words what you're calling about? "
                "You can also press zero to speak with someone.",
        }

    # Step 2D: high enough confidence to proceed. Record the
    # intent in the call's history (for the disposition record)
    # and dispatch to the per-intent handler.
    ctx = active_call_context.get(call_id)
    history = list(ctx.get("intents_classified_history", []))
    history.append({
        "intent":      intent_name,
        "confidence":  float(intent_confidence),
        "turn_index":  turn_index,
    })
    active_call_context.update(call_id, {
        "intents_classified_history": history,
        "low_confidence_turn_count":  0,
    })

    if intent_name == "refill_prescription":
        return handle_refill_intent(call_id, slots, turn_index)

    if intent_name == "schedule_appointment":
        return {
            "action": "transfer_scheduling_queue",
            "reason": "intent_routed",
            "prompt":
                "I'll connect you with our scheduling team to "
                "find a time that works.",
        }

    if intent_name == "billing_question":
        return {
            "action": "transfer_billing_queue",
            "reason": "intent_routed",
            "prompt":
                "Sure, I'll connect you with our billing team.",
        }

    if intent_name == "ask_hours_or_location":
        # Self-service fulfillment: read the practice's hours
        # without verification. No PHI is exposed.
        return {
            "action":     "play_audio_and_offer_more",
            "reason":     "intent_fulfilled_self_service",
            "audio_key":  "hours-and-location.wav",
            "prompt":
                "Our office hours are Monday through Friday, "
                "eight to five. We're at 100 Main Street in "
                "Richmond. Is there anything else I can help with?",
        }

    if intent_name == "speak_to_nurse":
        return {
            "action": "transfer_nurse_line",
            "reason": "intent_routed",
            "prompt":
                "Got it. I'm connecting you with our nursing line.",
        }

    if intent_name == "operator":
        return {
            "action": "transfer_general_agent",
            "reason": "caller_requested",
            "prompt":
                "Of course. Let me get you to someone right now.",
        }

    # Default: intent recognized but no handler. Transfer to a
    # general agent rather than guess. This is also where you'd
    # land for the Lex "fallback" intent (the catch-all the bot
    # uses when nothing matches).
    audit_log({
        "event_type":  "TRANSFER_NO_HANDLER",
        "call_id":     call_id,
        "intent_name": intent_name,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    })
    return {
        "action": "transfer_general_agent",
        "reason": "intent_recognized_no_handler",
        "prompt":
            "Let me connect you with someone who can help with that.",
    }
```

---

## Step 3: Verify the Caller

*The pseudocode calls this `verify_caller_if_needed(call_id, intent_name)` and `verify_slots_returned(call_id, dob, partial_phone)`. The verifier checks whether the intent requires verification, whether the caller has already been verified for this session, and (if not) prompts for the verification slots and validates them. The verification persists for the session: a caller who verified for an earlier intent does not re-verify for a subsequent intent on the same call.*

*The verification policy in the demo is illustrative: full DOB plus the last four digits of the phone on file. Real institutions have layered policies that vary by intent risk level, by detected fraud signals (a phone number that has never appeared for this patient, rapid attempts across multiple identities), and by patient preference. The policy is an explicit document maintained by the institution's identity-and-access governance, not a snippet of Lambda code.*

```python
def verify_caller_if_needed(call_id, intent_name):
    """
    Decide whether verification is needed for this intent and,
    if it is, whether the caller has already been verified for
    this session. If verification is needed and not yet
    completed, return a sub-dialog response that elicits the
    verification slots.

    Returns:
        A dict with one of:
        - {"verified": True, "reason": ...}
            The intent does not require verification, or the
            caller has already been verified for this session.
        - {"verified": False, "next_action": "elicit_slots", ...}
            Verification is needed; ask for the slots.
        - {"verified": False, "next_action": "transfer_general_agent", ...}
            Verification has failed too many times; transfer.
    """
    requires = INTENT_REQUIRES_VERIFICATION.get(
        intent_name, INTENT_REQUIRES_VERIFICATION["_default"])
    if not requires:
        return {
            "verified": True,
            "reason":   "intent_does_not_require_verification",
        }

    ctx = active_call_context.get(call_id)
    if ctx.get("verification_status") == "verified":
        return {
            "verified": True,
            "reason":   "already_verified_this_session",
        }

    # We need to verify. Has the caller already failed too many
    # times on this call? If so, stop trying and transfer.
    failures = ctx.get("verification_failure_count", 0)
    if failures >= MAX_VERIFICATION_ATTEMPTS:
        return {
            "verified":     False,
            "next_action":  "transfer_general_agent",
            "reason":       "verification_failed_max_attempts",
            "prompt":
                "I'm having trouble verifying your information. "
                "Let me connect you with someone who can help.",
        }

    # Otherwise, elicit the verification slots. In production
    # this returns a Lex dialog action that hands the
    # conversation to a verification sub-dialog the bot defines;
    # the sub-dialog elicits DOB and partial phone, then calls
    # back into verify_slots_returned with the captured values.
    return {
        "verified":     False,
        "next_action":  "elicit_slots",
        "reason":       "verification_required",
        "ani_match_count": ctx.get("ani_match_count", 0),
        "prompt":
            "Before I can help with that, I need to verify your "
            "identity. Could you tell me your date of birth, "
            "followed by the last four digits of the phone "
            "number we have on file?",
    }

def verify_slots_returned(call_id, dob, partial_phone):
    """
    Validate the verification slots the caller provided.

    Args:
        call_id: The Connect contact identifier.
        dob: The caller's full date of birth in YYYY-MM-DD
            format. The Lex slot type for date returns this
            format; the demo accepts it as-is.
        partial_phone: The last four digits of the phone on file
            as a string of four digits.

    Returns:
        A dict describing the verification outcome.
    """
    ctx = active_call_context.get(call_id)
    ani = ctx.get("ani")

    candidates = ehr.lookup_by_dob_and_phone(
        dob=dob, partial_phone=partial_phone, ani=ani)

    if len(candidates) == 1:
        # Exactly one match. Verified.
        active_call_context.update(call_id, {
            "verification_status":     "verified",
            "verified_patient_id":     candidates[0]["patient_id"],
            "verified_at":
                datetime.now(timezone.utc).isoformat(),
        })

        audit_log({
            "event_type":          "CALLER_VERIFIED",
            "call_id":             call_id,
            "verification_method": "dob_plus_partial_phone",
            "timestamp":
                datetime.now(timezone.utc).isoformat(),
        })

        cloudwatch.put_metric(
            "CallerVerified", 1, "Count",
            dimensions={"verification_method":
                          "dob_plus_partial_phone"})

        return {
            "verified": True,
            "patient_id": candidates[0]["patient_id"],
        }

    # Either zero or multiple matches. Don't disclose which;
    # just say verification failed. Disclosing "we found two
    # records matching that DOB" leaks information that could
    # be used to enumerate patients.
    new_failure_count = ctx.get("verification_failure_count", 0) + 1
    active_call_context.update(call_id, {
        "verification_failure_count": new_failure_count,
    })

    audit_log({
        "event_type":              "VERIFICATION_FAILED",
        "call_id":                 call_id,
        "verification_failure_count": new_failure_count,
        "candidate_count":         len(candidates),
        "timestamp":
            datetime.now(timezone.utc).isoformat(),
    })

    cloudwatch.put_metric(
        "VerificationFailed", 1, "Count",
        dimensions={"failure_count_band":
                      "first" if new_failure_count == 1 else "subsequent"})

    if new_failure_count >= MAX_VERIFICATION_ATTEMPTS:
        return {
            "verified":     False,
            "next_action":  "transfer_general_agent",
            "reason":       "verification_failed_max_attempts",
            "prompt":
                "I'm sorry, I wasn't able to verify your "
                "information. Let me connect you with someone "
                "who can help.",
        }

    return {
        "verified":     False,
        "next_action":  "retry_verification",
        "reason":       "verification_failed",
        "prompt":
            "I'm sorry, that doesn't match what we have on file. "
            "Let's try once more. Please say your date of birth, "
            "then the last four digits of the phone number on "
            "file.",
    }
```

---

## Step 4: Fulfill a Self-Service Refill

*The pseudocode calls this `handle_refill_intent(call_id, slots)`. With the caller verified and the intent classified as a refill, the refill-fulfillment Lambda checks self-service eligibility, queues the refill, and confirms with the caller. The eligibility check is the safety floor: controlled substances, expired prescriptions, prescriptions with no refills remaining, and certain clinical-flag medications are excluded regardless of caller verification.*

*The idempotency key prevents double-queuing. The (call_id, intent_name, turn_index) tuple is unique per call-and-intent-and-turn; the e-prescribing system rejects a second queue-refill request with the same idempotency key. This is what lets the fulfillment Lambda be safely invoked twice (because the dialog turn was retried, because an EventBridge delivery duplicated) without queuing two refills.*

```python
def fuzzy_match_medication(spoken_name, candidates):
    """
    Match the spoken medication name against the patient's
    active medication list.

    Real systems use a fuzzy match against a drug-name
    knowledge base (RxNorm) plus the patient's active list,
    handling brand-vs-generic equivalents (Lipitor and
    atorvastatin), common ASR mis-recognitions ("listen
    approval" -> "lisinopril"), and patient-spoken variants
    (the patient says "the blood pressure pill" rather than
    the drug name). The demo does case-insensitive substring
    matching against the active list, which is enough to
    illustrate the flow.

    Returns the matched medication dict if a single
    high-confidence match was found, else None.
    """
    if not spoken_name:
        return None
    lowered = spoken_name.lower().strip()
    matches = [m for m in candidates if m["name"].lower() in lowered
                                          or lowered in m["name"].lower()]
    if len(matches) == 1:
        return matches[0]
    # Zero matches or ambiguous (multiple matches). Caller-
    # facing: ask for clarification or hand off. Ambiguous
    # matches should never silently pick one.
    return None

def check_self_service_eligibility(patient_id, medication):
    """
    Check whether the medication is eligible for IVR
    self-service refill.

    Returns a dict with "eligible" (bool) and "reason" (str)
    fields. The reasons are coded so downstream analytics can
    aggregate them and operations can see which exclusion
    classes are most common.
    """
    if medication["drug_class"] in NON_SELF_SERVICE_DRUG_CLASSES:
        return {
            "eligible": False,
            "reason":   "drug_class_excluded",
            "drug_class": medication["drug_class"],
        }

    if medication.get("refills_remaining", 0) <= 0:
        return {
            "eligible": False,
            "reason":   "no_refills_remaining",
        }

    expiration = medication.get("expiration_date")
    if expiration:
        # The Lex slot type for date returns YYYY-MM-DD strings;
        # we compare against today.
        today = datetime.now(timezone.utc).date().isoformat()
        if expiration < today:
            return {
                "eligible": False,
                "reason":   "prescription_expired",
            }

    return {
        "eligible": True,
        "reason":   "eligible_for_self_service",
    }

def handle_refill_intent(call_id, slots, turn_index):
    """
    Handle a refill_prescription intent end to end.

    This is invoked from handle_lex_turn after intent
    classification has determined the caller wants a refill at
    high enough confidence to act on. The handler does the
    verification check, the medication lookup, the eligibility
    check, and the queue-the-refill action.
    """
    # Step 4A: ensure the caller is verified.
    verification = verify_caller_if_needed(
        call_id, "refill_prescription")
    if not verification["verified"]:
        # The caller hasn't been verified yet. Return the
        # verification dialog action; the caller will speak
        # their DOB and partial phone, the bot will capture
        # them as slots, and a follow-up turn will land in
        # verify_slots_returned.
        return {
            "action": verification.get("next_action", "elicit_slots"),
            "reason": verification.get("reason"),
            "prompt": verification.get("prompt"),
        }

    ctx = active_call_context.get(call_id)
    patient_id = ctx.get("verified_patient_id")

    # Step 4B: pull the medication slot value. Lex slots arrive
    # as a nested dict with the resolved value plus optional
    # confidence and resolutions. Real Lex slot payloads vary by
    # slot type; the demo passes a flat shape for clarity.
    medication_slot = slots.get("medication_name") or {}
    medication_name = medication_slot.get("value")
    medication_conf = Decimal(str(medication_slot.get("confidence", 0.0)))

    # Step 4C: if the medication slot wasn't extracted at
    # adequate confidence, ask for it explicitly.
    if not medication_name or medication_conf < Decimal("0.7"):
        return {
            "action": "elicit_slot",
            "slot":   "medication_name",
            "reason": "medication_slot_missing_or_low_confidence",
            "prompt":
                "Sure, I can help with that. Which medication "
                "would you like to refill?",
        }

    # Step 4D: look up the patient's active medications. The
    # refill request must match an existing prescription; we
    # don't write new ones from the IVR.
    active_meds = e_prescribing.get_active_medications(patient_id)
    matching_med = fuzzy_match_medication(
        spoken_name=medication_name, candidates=active_meds)

    if matching_med is None:
        audit_log({
            "event_type": "REFILL_MEDICATION_NOT_FOUND",
            "call_id":    call_id,
            "patient_id": patient_id,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        })
        return {
            "action": "transfer_pharmacy_queue",
            "reason": "medication_not_on_active_list",
            "prompt":
                "I wasn't able to find that medication on your "
                "active list. Let me transfer you to someone who "
                "can help.",
        }

    # Step 4E: check eligibility for self-service refill. This
    # is the safety floor; we never let the IVR auto-refill
    # things that require a clinical touch.
    eligibility = check_self_service_eligibility(
        patient_id, matching_med)

    if not eligibility["eligible"]:
        audit_log({
            "event_type":     "REFILL_INELIGIBLE_FOR_SELF_SERVICE",
            "call_id":        call_id,
            "patient_id":     patient_id,
            "medication_id":  matching_med["medication_id"],
            "ineligible_reason": eligibility["reason"],
            "timestamp":      datetime.now(timezone.utc).isoformat(),
        })

        cloudwatch.put_metric(
            "RefillIneligible", 1, "Count",
            dimensions={"reason": eligibility["reason"]})

        return {
            "action": "transfer_pharmacy_queue",
            "reason": "self_service_ineligible_" + eligibility["reason"],
            "prompt":
                "I'd like to get you the right help with that one. "
                "Let me transfer you to our pharmacy team.",
        }

    # Step 4F: queue the refill request. We don't dispense; we
    # just queue it for the e-prescribing system's normal flow.
    # The (call_id, intent_name, turn_index) tuple is the
    # idempotency key that prevents double-queuing if this
    # Lambda is invoked twice for the same turn.
    idempotency_key = f"{call_id}:refill_prescription:{turn_index}"
    requested_at = datetime.now(timezone.utc).isoformat()

    refill_request_id = e_prescribing.queue_refill_request(
        patient_id=patient_id,
        medication_id=matching_med["medication_id"],
        requested_via="ivr_self_service",
        requested_at=requested_at,
        idempotency_key=idempotency_key,
    )

    # Step 4G: record the fulfillment in the call context so
    # the disposition record can capture it.
    ctx = active_call_context.get(call_id)
    fulfillments = list(ctx.get("fulfillments", []))
    fulfillments.append({
        "type":               "refill_request_queued",
        "refill_request_id":  refill_request_id,
        "medication_id":      matching_med["medication_id"],
        "queued_at":          requested_at,
    })
    active_call_context.update(call_id, {
        "fulfillments":              fulfillments,
        "last_fulfillment_outcome":  "self_service_refill_queued",
    })

    audit_log({
        "event_type":         "REFILL_REQUEST_QUEUED",
        "call_id":            call_id,
        "patient_id":         patient_id,
        "medication_id":      matching_med["medication_id"],
        "refill_request_id":  refill_request_id,
        "idempotency_key":    idempotency_key,
        "timestamp":          requested_at,
    })

    # Step 4H: emit the cross-system event. The e-prescribing
    # pipeline, the patient-portal notification system, and the
    # care-management platform all subscribe to refill-queued
    # events.
    event_bus.put_events([{
        "Source":         "ivr.refill",
        "DetailType":     "refill_request_queued",
        "EventBusName":   IVR_EVENT_BUS_NAME,
        "Detail": json.dumps({
            "call_id":            call_id,
            "patient_id":         patient_id,
            "medication_id":      matching_med["medication_id"],
            "refill_request_id":  refill_request_id,
            "queued_at":          requested_at,
        }),
    }])

    cloudwatch.put_metric(
        "RefillSelfServiceCompleted", 1, "Count",
        dimensions={"institution_id": INSTITUTION_ID})

    # Step 4I: confirm with the caller and offer additional
    # help. The caller-facing prompt names the medication so
    # the caller can catch a wrong-medication confirmation
    # before hanging up.
    return {
        "action": "confirm_and_offer_more",
        "reason": "self_service_refill_queued",
        "prompt":
            f"Got it. I've sent your refill request for "
            f"{matching_med['name']} {matching_med['strength']} "
            f"to the pharmacy team. You should hear back within "
            f"one business day. Is there anything else I can "
            f"help with?",
        "fulfillment": {
            "refill_request_id": refill_request_id,
        },
    }
```

---

## Step 5: Capture the Call Disposition

*The pseudocode calls this `ON call_end(call_id, end_reason)`. When the call ends (caller hangs up, transfer completes, self-service fulfillment confirmed), the disposition is captured. This is the row that goes into analytics and feeds the per-intent accuracy metrics, the containment rate, the subgroup-stratified accuracy reports, and the urgency-override-rate dashboard.*

*In Connect, the call-end event is the Contact Trace Record (CTR) that Connect emits when the contact terminates. The disposition Lambda is invoked by an EventBridge rule that watches for CTR events. The active-call-context record is read for the per-call state; the disposition is written to the long-term log; the active-call-context record is allowed to expire via its TTL rather than being explicitly deleted.*

```python
def capture_call_disposition(call_id, end_reason):
    """
    Write the long-term disposition record at call end.

    Args:
        call_id: The Connect contact identifier.
        end_reason: One of:
            - "self_service_fulfilled"
            - "transferred_to_agent"
            - "transferred_to_triage"
            - "transferred_to_billing"
            - "transferred_to_nurse_line"
            - "transferred_to_pharmacy"
            - "callback_scheduled"
            - "abandoned"

    Returns:
        The disposition record that was written.
    """
    ctx = active_call_context.get(call_id)
    now = datetime.now(timezone.utc)

    started_at = ctx.get("started_at")
    started_dt = (datetime.fromisoformat(started_at)
                  if started_at else now)
    duration_seconds = int((now - started_dt).total_seconds())

    disposition = {
        "call_id":           call_id,
        "ani":               ctx.get("ani"),
        "dnis":              ctx.get("dnis"),
        "started_at":        started_at,
        "ended_at":          now.isoformat(),
        "duration_seconds":  duration_seconds,
        "end_reason":        end_reason,
        "verification_status":
            ctx.get("verification_status", "unverified"),
        "intents_classified_history":
            ctx.get("intents_classified_history", []),
        "slots_collected":
            ctx.get("slots_collected", {}),
        "fulfillments":
            ctx.get("fulfillments", []),
        "urgency_flag_raised":
            ctx.get("urgency_flag", False),
        "low_confidence_turn_count":
            ctx.get("low_confidence_turn_count", 0),
        "verification_failure_count":
            ctx.get("verification_failure_count", 0),
        "last_fulfillment_outcome":
            ctx.get("last_fulfillment_outcome"),
        # Versioning: every disposition record carries the
        # versions of the artifacts that influenced it. A future
        # audit reconstructs which calibration was active.
        "bot_version":
            ctx.get("bot_version", BOT_VERSION),
        "threshold_config_version":
            ctx.get("threshold_config_version",
                     THRESHOLD_CONFIG_VERSION),
        "urgency_lexicon_version":
            ctx.get("urgency_lexicon_version",
                     URGENCY_LEXICON_VERSION),
        "institution_id":           INSTITUTION_ID,
        "institution_jurisdiction": INSTITUTION_JURISDICTION,
    }

    # Production: dynamodb.Table(CALL_DISPOSITION_LOG_TABLE).put_item(
    #     Item=_to_decimal(disposition))
    # The disposition record is the long-term audit row; it has
    # no TTL, and lifecycle is managed by S3 archival tiers
    # rather than table-level TTL.
    call_disposition_log.put(disposition)

    audit_log({
        "event_type":  "CALL_DISPOSITION_RECORDED",
        "call_id":     call_id,
        "end_reason":  end_reason,
        "duration_seconds": duration_seconds,
        "timestamp":   now.isoformat(),
    })

    # Containment-rate metric. A call counts as "contained"
    # (handled in self-service without a human agent) only when
    # the end_reason is "self_service_fulfilled". Every other
    # outcome (transfer to any queue, abandonment, callback) is
    # not containment.
    is_contained = (end_reason == "self_service_fulfilled")
    cloudwatch.put_metric(
        "CallContained" if is_contained else "CallNotContained",
        1, "Count",
        dimensions={"end_reason": end_reason})

    cloudwatch.put_metric(
        "CallDurationSeconds", duration_seconds, "Seconds",
        dimensions={"end_reason": end_reason})

    return disposition
```

---

## Putting It All Together

Here is the full pipeline tied together as a Lambda-style handler that simulates an inbound call: the Connect contact-flow initialization, two Lex turns (the verification turn and the refill turn), and the call-end disposition. In a Lambda deployment, your handler would be invoked by Lex's fulfillment hook (one invocation per turn) rather than orchestrating turns directly; the demo orchestrates them inline so you can see the full sequence.

```python
def simulate_inbound_call(call_scenario):
    """
    Simulate an inbound call end-to-end.

    Args:
        call_scenario: A dict describing the call:
            - call_id, ani, dnis: Connect-side identifiers.
            - turns: A list of Lex turn payloads to inject.
            - verification: An optional dict with dob and
                partial_phone, applied if a turn returns an
                "elicit_slots" action for verification.
            - end_reason: The disposition end_reason.

    Returns:
        The disposition record that was captured.
    """
    call_id = call_scenario["call_id"]
    ani     = call_scenario.get("ani")
    dnis    = call_scenario.get("dnis", "+18045550000")

    # Step 1: Connect picks up the call and initializes
    # session state.
    print(f"\n=== Call {call_id} starts ===")
    initialize_call_session(call_id, ani, dnis)

    # Steps 2-4: process each Lex turn.
    last_response = None
    for turn in call_scenario.get("turns", []):
        print(f"\n--- Turn {turn.get('turn_index', '?')}: "
              f"caller said: {turn.get('input_transcript')!r} ---")
        last_response = handle_lex_turn(turn)
        print(f"  -> action: {last_response.get('action')}")
        print(f"  -> reason: {last_response.get('reason')}")
        if last_response.get("prompt"):
            print(f"  -> prompt: {last_response['prompt']}")

        # If the turn requested verification slots and the
        # scenario provides them, apply them. In production
        # this happens via the Lex sub-dialog: the bot prompts
        # for the slots, captures them as dialog turns, and
        # invokes the verification Lambda when both are
        # filled. The demo collapses this into a single
        # callback for readability.
        if (last_response.get("action") == "elicit_slots"
                and call_scenario.get("verification")):
            print("  -> caller provides verification slots")
            ver = verify_slots_returned(
                call_id=call_id,
                dob=call_scenario["verification"]["dob"],
                partial_phone=
                    call_scenario["verification"]["partial_phone"],
            )
            print(f"     verification: {ver.get('verified')}, "
                  f"{ver.get('reason', '')}")
            # Re-run the same turn now that verification has
            # been resolved. In production the Lex dialog state
            # remembers where it was; in the demo we simply
            # re-invoke handle_lex_turn for the same payload.
            if ver.get("verified"):
                last_response = handle_lex_turn(turn)
                print(f"  -> action: {last_response.get('action')}")
                print(f"  -> reason: {last_response.get('reason')}")
                if last_response.get("prompt"):
                    print(f"  -> prompt: {last_response['prompt']}")

    # Step 5: capture the call disposition at call end.
    end_reason = call_scenario.get(
        "end_reason", "transferred_to_agent")
    disposition = capture_call_disposition(call_id, end_reason)
    print(f"\n=== Call {call_id} ended: {end_reason} ===")
    return disposition

def run_demo():
    """
    Run a small set of end-to-end scenarios that exercise the
    main paths through the IVR routing logic:
      1. Self-service refill: caller verifies, asks for a
         refill, the medication is eligible, the refill is
         queued.
      2. Urgency override: caller mentions chest pain, the
         system bypasses normal routing and transfers to
         clinical triage.
      3. Ineligible refill: caller verifies, asks for a refill,
         the medication is a controlled substance and is
         excluded from self-service; transfer to pharmacy.
      4. Low-confidence repeated: the bot's confidence is below
         threshold three turns in a row; transfer to a general
         agent.
    """
    scenarios = [
        {
            "name": "self_service_refill_success",
            "call_id": "contact-demo-0001",
            "ani":     "5715551234",
            "dnis":    "+18045550000",
            "verification": {
                "dob":            "1958-03-14",
                "partial_phone":  "1234",
            },
            "turns": [
                {
                    "session_id": "contact-demo-0001",
                    "turn_index": 1,
                    "input_transcript":
                        "I need to refill my lisinopril",
                    "intent": {
                        "name":       "refill_prescription",
                        "confidence": 0.94,
                        "slots": {
                            "medication_name": {
                                "value":      "lisinopril",
                                "confidence": 0.91,
                            },
                        },
                    },
                },
            ],
            "end_reason": "self_service_fulfilled",
        },
        {
            "name": "urgency_override_chest_pain",
            "call_id": "contact-demo-0002",
            "ani":     "8045555678",
            "dnis":    "+18045550000",
            "turns": [
                {
                    "session_id": "contact-demo-0002",
                    "turn_index": 1,
                    "input_transcript":
                        "I'm having chest pain and I want to "
                        "talk to someone about my medication",
                    "intent": {
                        "name":       "refill_prescription",
                        "confidence": 0.86,
                        "slots": {},
                    },
                },
            ],
            "end_reason": "transferred_to_triage",
        },
        {
            "name": "refill_controlled_substance_blocked",
            "call_id": "contact-demo-0003",
            "ani":     "8045559876",
            "dnis":    "+18045550000",
            "verification": {
                "dob":            "1985-01-08",
                "partial_phone":  "9876",
            },
            "turns": [
                {
                    "session_id": "contact-demo-0003",
                    "turn_index": 1,
                    "input_transcript":
                        "I need a refill on my oxycodone",
                    "intent": {
                        "name":       "refill_prescription",
                        "confidence": 0.92,
                        "slots": {
                            "medication_name": {
                                "value":      "oxycodone",
                                "confidence": 0.88,
                            },
                        },
                    },
                },
            ],
            "end_reason": "transferred_to_pharmacy",
        },
        {
            "name": "low_confidence_three_strikes",
            "call_id": "contact-demo-0004",
            "ani":     None,
            "dnis":    "+18045550000",
            "turns": [
                {
                    "session_id": "contact-demo-0004",
                    "turn_index": 1,
                    "input_transcript": "uhhh I dunno",
                    "intent": {
                        "name":       "refill_prescription",
                        "confidence": 0.42,
                        "slots": {},
                    },
                },
                {
                    "session_id": "contact-demo-0004",
                    "turn_index": 2,
                    "input_transcript": "the thing",
                    "intent": {
                        "name":       "schedule_appointment",
                        "confidence": 0.39,
                        "slots": {},
                    },
                },
                {
                    "session_id": "contact-demo-0004",
                    "turn_index": 3,
                    "input_transcript": "you know",
                    "intent": {
                        "name":       "billing_question",
                        "confidence": 0.31,
                        "slots": {},
                    },
                },
            ],
            "end_reason": "transferred_to_agent",
        },
    ]

    for scenario in scenarios:
        print("\n" + "#" * 60)
        print(f"# SCENARIO: {scenario['name']}")
        print("#" * 60)
        simulate_inbound_call(scenario)

    # Print a small summary of what the demo emitted.
    print("\n" + "=" * 60)
    print("DEMO SUMMARY")
    print("=" * 60)
    print(f"Call dispositions captured: "
          f"{len(call_disposition_log.records)}")
    print(f"Cross-system events emitted: "
          f"{len(event_bus.events)}")
    print(f"CloudWatch metrics emitted: "
          f"{len(cloudwatch.metrics)}")
    print(f"Refill requests queued: "
          f"{len(e_prescribing.queued_refills)}")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    run_demo()
```

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right disposition records, but the distance between it and a real Amazon Connect IVR running at a healthcare practice is significant. Here is where that distance lives.

**Real Connect contact flow plus Lex bot.** The demo orchestrates Lex turns in Python. Production lives in Connect's contact-flow editor (a graphical flow that handles SIP call setup, the recording disclosure, the Lex bot invocation, the per-action transfers and audio playback) plus the Lex V2 bot definition (intents, sample utterances, slot types, slot-elicitation prompts, fulfillment hooks). Build the contact flow first, build the Lex bot second, then write the fulfillment Lambdas that the bot invokes. The boundary is: the contact flow handles call-leg lifecycle; Lex handles ASR, NLU, and slot-filling dialog; Lambdas handle business logic and back-office integration.

**Per-Lambda IAM roles.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda function (caller-verifier, refill-fulfillment, appointment-fulfillment, urgency-escalator, disposition-recorder), each scoped to the specific resource ARNs the Lambda touches. The verifier role has read-only access to the patient-index API and write access only to the verification-status fields of active-call-context; the refill-fulfillment role has scoped access to the e-prescribing API and write access only to the disposition record. Wildcard actions and resources will fail any serious IAM review.

**Real DynamoDB and S3 wiring.** The mocks in the demo are dictionaries; production is DynamoDB tables with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time-recovery enabled on the disposition log, TTL on the active-call-context table, and DynamoDB Streams emitting change events for downstream consumers. Call recordings land in an S3 bucket with SSE-KMS, lifecycle to S3 Glacier Instant Retrieval after 30 days and Glacier Deep Archive after 90, and a retention bound by the longest of HIPAA's six-year minimum, the state's medical-records-retention requirement, and the institutional regulatory floor.

**KMS customer-managed keys.** Every PHI-bearing resource (recordings, active-call-context, call-disposition-log, Secrets Manager secrets, Lambda environment variables, CloudWatch Logs) uses customer-managed KMS keys with key rotation enabled. Key access is scoped to the specific principals that need it; CloudTrail logs every key-usage event. The institutional KMS-key-management runbook specifies rotation cadence, access review cadence, and the cross-account key-grant pattern for any cross-account integrations.

**VPC and VPC endpoints.** Lambdas that call back-office APIs (EHR, e-prescribing, scheduling) run in a VPC with private subnets that route traffic to those systems through controlled egress paths. VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, EventBridge, and CloudWatch Logs keep AWS-internal traffic on the AWS backbone rather than traversing NAT and the public internet. Connect itself runs outside your VPC; the integration with Lambda and Lex still terminates in your account.

**Per-jurisdiction recording-consent disclosure.** The demo hand-waves the disclosure ("a Connect contact-flow step plays the disclosure WAV"). Production has separate disclosure WAVs per jurisdiction (one-party-consent states, all-party-consent states, the institution's preferred default for unknown jurisdictions), the contact flow selects the right WAV based on the caller's geographic indicators (DNIS, ANI area code, geo-IP signals on related interactions), and general counsel reviews and approves the per-jurisdiction language. The disclosure logic is operationally important and should not be improvised at deploy time.

**Real urgency-lexicon governance.** The lexicon in the demo is illustrative. Production has a versioned, reviewed lexicon stored in Parameter Store or AppConfig (so it can be updated without redeploying the Lambda), a quarterly review cadence with clinical operations, a change-review workflow when phrases are added or removed, and a documented escalation path when a missed urgent call surfaces in production. Treat the lexicon as a clinical safety document with the procedural rigor that implies. The Lambda reloads the lexicon at the start of each invocation so that a config change takes effect immediately.

**Per-intent threshold calibration.** The thresholds in the demo are placeholder values. Production calibrates them against real traffic: collect a labeled sample of production turns (intent classification was correct or incorrect), build a precision-recall curve per intent at various confidence thresholds, and pick the threshold that achieves the institution's chosen precision floor. Re-calibrate quarterly or whenever the bot version changes (a bot retraining can shift the confidence distribution). Per-intent thresholds also vary by caller cohort if subgroup-stratified accuracy reveals the model behaves differently for specific populations.

**Subgroup-stratified accuracy monitoring.** The demo emits CloudWatch metrics with an `intent_name` dimension, which is enough for per-intent dashboards. Production additionally stratifies by caller-cohort dimensions (age band where the data permits, language preference from caller demographics, geographic region from area code, accent group where it can be inferred from acoustic features). The dashboards alert when subgroup accuracy diverges by more than the configured threshold. The metric is institutionally important, not just engineering housekeeping.

**Connect Contact Lens integration.** Contact Lens provides built-in conversation analytics on call recordings: sentiment, talk-time imbalance, keyword detection, automatic redaction of PII in the transcript output. The redaction in particular is institutionally useful: the analytics pipeline can consume redacted transcripts for trend analysis without re-handling raw PHI. Enabling Contact Lens is a configuration step on the Connect instance plus per-contact-flow opt-in.

**Real fuzzy medication matching.** The demo's `fuzzy_match_medication` is naive substring matching. Production matches against RxNorm or the institution's drug-database equivalent, handles brand-vs-generic equivalents (Lipitor and atorvastatin), handles common ASR mis-recognitions ("listen approval" -> "lisinopril"), and asks for confirmation on high-risk medications ("I heard methotrexate, is that right?"). The medication match is one of the highest-leverage places to invest in the bot's accuracy, because misrecognition here produces refill-the-wrong-medication failures.

**Idempotency at the platform level.** The demo's idempotency-key approach prevents the e-prescribing system from queuing duplicate refills, which is the most important failure mode. Production extends this to every fulfillment action and every cross-system event. The (call_id, intent_name, turn_index) tuple is the key for fulfillment idempotency; the (event_type, call_id, fulfillment_action_id) tuple is the key for event-emission idempotency. Configure DLQs on every Lambda; alarm on DLQ depth.

**Disaster recovery and failover.** The IVR is the front door. When it's down, callers can't reach the practice. The architecture needs an explicit failover path: if Lex is unavailable, the contact flow drops to a DTMF menu that captures the caller's intent through digit selection; if Connect is unavailable, the carrier-side IVR (configured at the SIP-trunk level) plays a recorded message with alternate contact methods. The recovery testing is institutionally important and is often the part of the architecture that's drawn nicely in slides and never actually exercised. Build it and exercise it quarterly.

**Continuous bot improvement workflow.** Production transcripts surface intents you didn't define, slot values you didn't anticipate, and phrasings the model handles poorly. The improvement workflow (review production transcripts weekly, propose bot changes, test against a held-out evaluation set, deploy via versioned bot aliases, monitor for regressions) is a sustained engineering practice, not a launch task. Plan staffing accordingly. The Lex bot-alias indirection is what lets you deploy a new bot version safely: aim a small percentage of calls at the new alias, monitor accuracy and disposition metrics, then promote the alias when the new version performs at parity or better.

**Multi-language support.** The demo is English-only. Most U.S. healthcare organizations need Spanish; many need additional languages depending on patient population. Lex V2 supports multi-language bots; the operational pattern (one bot with locale-specific training, or one bot per locale, or a router bot that detects language and dispatches) is an architectural decision with real implications. Build for multi-language from the start even if you ship English-first; retrofitting multi-language onto a single-language design is more expensive than designing for it day one.

**Fraud detection on the call stream.** Once the IVR can release information (your appointment is on Friday, the prescription was sent to your usual pharmacy) or trigger actions (refill submitted, appointment confirmed), it becomes a target for social engineers. Production runs pattern-based anomaly detection on the call stream: rapid attempts across multiple identities from the same ANI, callers using a phone number that has never appeared for a given patient, voice characteristics inconsistent with the patient's known profile. Flagged calls route to enhanced verification or to a human agent rather than to self-service fulfillment.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the intent-router logic with edge cases (urgency override beats high-confidence non-urgent intent, low-confidence below threshold elicits clarification, repeated low-confidence transfers to agent), unit tests for the verifier (single match verifies, zero matches fails without disclosing, multiple matches fails without disclosing), unit tests for the eligibility check (controlled substance excluded, expired excluded, no-refills-remaining excluded), integration tests against a Lex test bot with a fixture of utterances and expected intents, and end-to-end tests that simulate full call flows including the verification sub-dialog. Never use real patient data in test fixtures.

**Observability beyond the metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-call investigation. Production runs CloudWatch Logs Insights queries that join across the contact-flow logs, the Lex conversation logs, the Lambda invocation logs, and the disposition records by call_id. AWS X-Ray traces show the latency contribution of each step (Lex ASR, Lambda invocation, EHR API call, e-prescribing API call). When a single call goes wrong, the on-call engineer needs to reconstruct the full trace in seconds, not minutes.

**Cost monitoring and per-intent attribution.** Connect's per-minute charges and Lex's per-request charges add up. Some intents are dramatically cheaper than others (a 10-second hours-and-location lookup costs much less than a 3-minute multi-turn refill dialog). The cost-per-intent and cost-per-call analytics let the operations team see which call patterns are economically efficient to handle in self-service and which are not. Build the dashboard.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 10.1: IVR Call Routing Enhancement](chapter10.01-ivr-call-routing-enhancement) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
