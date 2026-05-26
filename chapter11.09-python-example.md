# Recipe 11.9: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 11.9. It shows one way you could translate the care-coordination-assistant pipeline into working Python using boto3 against Amazon Bedrock (LLM with function-calling), Amazon Bedrock Knowledge Bases (managed RAG over the coordination-protocol corpus and the patient-education library), Amazon Bedrock Guardrails, AWS Lambda, AWS Step Functions, AWS HealthLake, Amazon API Gateway, Amazon DynamoDB, Amazon S3, Amazon Pinpoint, Amazon Connect, and Amazon EventBridge. The demo uses mock implementations standing in for the real services so you can see the shape of the pipeline without provisioning anything. It is not production-ready. There is no real Bedrock Agents action group configured, no real Knowledge Base ingestion, no real Guardrail configuration, no real HL7 listener, no real FHIR poller, no real claims-feed processor, no real pharmacy-API integration, no real home-health vendor adapter, no real HIE/TEFCA participation, no real Step Functions transition-of-care state machines with clinical-leadership signoff, no real Connect contact-center integration with the licensed care-management workforce, no real per-Lambda IAM least privilege, no real separately-keyed KMS for the provenance journal and coordination-decision-record store, no real Object-Lock-protected coordination-decision-record journal sized to state-specific medical-record retention, no Secrets Manager wiring for the upstream-system credentials, and no per-state caregiver-consent matrix encoded in policy. Think of it as the sketchpad version: useful for understanding the shape of a care-coordination-assistant pipeline that respects the cross-organizational-data-integration discipline, the longitudinal-coordination-state-as-system-of-record discipline, the provenance-as-architectural-primitive discipline, the seam-detection-rule-engine-with-clinical-leadership-ownership discipline, the referral-and-transition-of-care-state-machine discipline, the caregiver-as-first-class-participant discipline, the cross-organizational-consent discipline, the citation-grounding discipline, the scope-discipline-across-adjacent-recipes discipline, the per-cohort-monitoring discipline, and the audit-everything discipline this recipe demands. It is not something you would point at a payer's chronic-multi-condition population on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the ten pseudocode steps from the main recipe: enroll the patient with cross-organizational consent and caregiver setup (Step 1); ingest cross-organizational data with provenance discipline (Step 2); run the seam-detection rule engine and protocol-trigger evaluator (Step 3); receive the conversation turn with input safety, identity, and coordination-context loading (Step 4); run the agent's tool-use loop with citation discipline (Step 5); run output safety with protocol-faithfulness verification (Step 6); orchestrate transitions of care with Step Functions (Step 7); track referral lifecycles to closure (Step 8); handle medication-reconciliation seams across pharmacies and clinicians (Step 9); generate care-team reporting and queue outcome correlation (Step 10). The synthetic patients, caregivers, clinicians, pharmacies, hospitals, and coordination protocols in the demo are fictional; nothing in this file should be interpreted as clinical guidance from any real institution. **If you or someone you know is in crisis: in the United States, call or text 988 to reach the Suicide and Crisis Lifeline, or call 911 for an active emergency.**

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also configure an Amazon Bedrock Agent (or a custom Lambda-based orchestrator) with action groups defining the coordination tools (`coordination_state_retrieve`, `referral_lifecycle_retrieve`, `encounter_retrieve`, `medication_list_reconcile`, `open_followups_retrieve`, `seam_flags_retrieve`, `protocol_retrieve`, `patient_education_content_retrieve`, `care_team_alert_propose`, `patient_action_propose`, `follow_up_schedule`, `escalation_propose`, `provenance_retrieve`), each backed by a tool-implementation Lambda that wraps the institution's coordination-state store, the referral-lifecycle state machine, the FHIR-native chart-context store (typically AWS HealthLake), the synthesized medication list, the open-followups registry, the seam-flag store, the curated coordination-protocol corpus, the patient-education library, the licensed care-management workforce queue (typically Amazon Connect), and the consent-gated care-team integration. You would also configure Amazon Bedrock Knowledge Bases ingesting curated content from S3 covering the institution-validated coordination-protocol corpus (transition-of-care protocols by destination setting, referral-tracking protocols by specialty and urgency, post-discharge protocols by admission type, post-procedure protocols by procedure category, medication-reconciliation protocols, condition-specific coordination playbooks for high-prevalence multi-condition combinations) and the patient-education library (with multilingual and multi-reading-level variants reviewed by clinical leadership and patient-experience leadership). You would configure an Amazon Bedrock Guardrail with restricted-topic filters for diagnosis-attempted, prescription-attempted, dose-titration-attempted, treatment-recommendation-beyond-existing-orders, therapy-attempted (which routes to recipe 11.8 pathway), triage-attempted (which routes to recipe 11.6 pathway), and benefits-quote-attempted (which routes to recipe 11.5 pathway). You would configure an API Gateway endpoint fronting the chat-handler Lambda, an AWS WAF web ACL with rate limits tuned for the coordination-conversation pattern, the twelve DynamoDB tables (patient-coordination-store, coordination-state-store, referral-lifecycle-store, transition-of-care-store, seam-flag-store, caregiver-store, conversation-state, conversation-metadata, tool-call-ledger, coordination-decision-record-journal, provenance-journal on a separately-managed KMS key, consent-record), an Amazon S3 bucket with Object Lock in compliance mode for the coordination-decision-record journal sized to the longest of HIPAA's six-year minimum, the state's medical-record retention rules, 42 CFR Part 2 obligations where substance-use-treatment data is involved, FDA SaMD post-market obligations where applicable, and the institutional regulatory floor, a separately-keyed S3 archive for the provenance journal, an EventBridge bus for coordination-lifecycle events, AWS Step Functions state machines for the transition-of-care workflows by destination setting (hospital-to-home, hospital-to-SNF, ED-to-PCP follow-up, surgery-to-home, etc.) with clinical-leadership signoff, an Amazon MWAA environment for population-scale batch ingestion (FHIR Bulk Data exports, claims-feed periodic refresh, population-level seam-detection runs), a Kinesis Data Firehose delivery stream for the conversation-audit archive, AWS Secrets Manager secrets for the EHR, HIE/TEFCA, payer-claims, pharmacy-API, home-health-vendor, and care-team-workflow credentials, an Amazon Pinpoint application for proactive care-event-triggered messaging, an Amazon Connect contact center for warm-handoff to licensed care managers, and AWS HealthLake as the FHIR-native data store normalizing data from multiple EHRs and HIE feeds. The demo replaces all of these with small mocks so the focus stays on the cross-organizational-ingestion-with-provenance, the longitudinal-coordination-state synthesis, the seam-detection rule engine, the referral-lifecycle state machine, the transition-of-care orchestration, the citation-grounded response generation, and the coordination-decision-record persistence logic rather than on the platform plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` for the orchestration model and the smaller models (intent classification, seam-detection-rule pre-filtering, summarization)
- `bedrock-agent-runtime:InvokeAgent` if you wire Bedrock Agents instead of running the orchestration in a custom Lambda
- `bedrock:Retrieve` and `bedrock:RetrieveAndGenerate` on the Knowledge Base ARNs holding the coordination-protocol corpus and the patient-education library
- `bedrock:ApplyGuardrail` on the Guardrail ARN you configured
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the twelve tables, scoped to specific table ARNs (the provenance-journal on a separately-keyed KMS path)
- `events:PutEvents` on the coordination-events bus
- `firehose:PutRecord` on the audit-archive Firehose delivery stream
- `s3:PutObject` on the coordination-decision-record-journal bucket prefix and the separately-keyed provenance-archive prefix
- `cloudwatch:PutMetricData` for operational metrics (referral closure rate, transition-of-care completion rate, medication-reconciliation accuracy, seam-detection rate, seam-resolution rate, escalation rate, citation-coverage rate, per-cohort slices)
- `secretsmanager:GetSecretValue` on the upstream-system credential secrets pinned to the current rotation versions
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the coordination-state, referral-lifecycle, transition-of-care, seam-flag, caregiver, conversation tables, the tool-call ledger, the coordination-decision-record table, the consent record, the audit archive, and the Secrets Manager secrets, plus the **separately-managed** customer-managed key protecting the provenance journal
- `mobiletargeting:SendMessages` on the Pinpoint application for proactive care-event-triggered messaging
- `connect:StartChatContact` and related actions on the Connect contact-center for warm-handoff to licensed care managers
- `states:StartExecution` on the Step Functions state machines for the transition-of-care workflows
- `healthlake:ReadResource`, `healthlake:SearchWithGet`, `healthlake:SearchWithPost` on the FHIR data store
- For the tool Lambdas calling external EHRs, HIE/TEFCA endpoints, payer claims feeds, pharmacy APIs, home-health vendor APIs, or care-team-workflow systems: VPC-endpoint or PrivateLink permissions, plus whatever each upstream system's auth flow requires

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The chat-handler Lambda has Bedrock invocation and read-write on the conversation tables, but no direct access to the provenance journal or the mandatory-reporting pathway. The HL7 listener and FHIR poller Lambdas have read access to the connected EHR endpoints with credentials in Secrets Manager and write access to HealthLake plus the provenance journal. The seam-detection rule engine Lambda has read access to the coordination-state and write access to the seam-flag store. The provenance-record Lambda is the only path that writes the provenance journal, with the separately-managed KMS key. None of the bot's Lambdas have write access to the clinical record except for institutionally-approved coordination-event records (FHIR Communication for the conversation log; FHIR ServiceRequest for follow-up scheduling where the institution permits assistant-originated requests; with explicit patient consent and institutional clinical-leadership signoff).

A few things worth knowing upfront:

- **Cross-organizational data integration is the architectural floor, not a feature.** The coordination assistant cannot deliver value without consuming data from multiple sources. The integration layer (HL7 listeners, FHIR API consumers, claims-feed processors, pharmacy-data integrations, HIE/TEFCA participation) is multi-quarter engineering work and is the largest single engineering investment in the system. Skip it and the assistant degrades to a chat surface over a single EHR.
- **Provenance is architectural, not optional.** Every entry in the coordination state has a recorded source, timestamp, and provenance chain. Every assistant-generated assertion about the patient's coordination state cites that provenance. The provenance journal is on a separately-managed KMS key for blast-radius containment.
- **The longitudinal coordination state is its own record class.** Distinct from any single EHR's chart, with its own retention policy, its own access controls, its own provenance discipline, and its own update workflows. The coordination state is the system of record for coordination state; the EHRs remain the system of record for clinical decisions.
- **The seam-detection rule library and the coordination-protocol corpus are institutional content, not LLM creativity.** Each rule and each protocol has named clinical-leadership ownership, an effective date, a version history, sampled review for precision and recall, and clinical-leadership signoff before deployment. Multi-quarter clinical work to mature.
- **Caregivers are first-class participants.** Separate identities, separate authentication, separate proxy-access scope, separate state-law access posture, separate message templates, separate burden monitoring. The patient-plus-caregiver pattern is the modal experience for the highest-need population.
- **Cross-organizational consent has nuanced regulatory exposure.** HIPAA, the Information Blocking and Interoperability rules, TEFCA, state-specific medical-record statutes, state-specific caregiver-consent and proxy-access laws, 42 CFR Part 2 for substance-use treatment records, state-specific mental-health-record protections. Legal counsel reviews the consent posture before launch and on each material change.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, and numeric metadata field passes through `Decimal`. The `_to_decimal` helper handles it.
- **The example collapses many Lambdas into a single Python file.** In production each ingestion adapter (HL7, FHIR, claims, pharmacy, home-health, HIE), each tool implementation, the seam-detection rule engine, the protocol-trigger evaluator, the transition-of-care state-machine workers, the chat handler, the input-screening function, the longitudinal-context-loading function, the output-screening function, the coordination-decision-record-persistence function, the provenance-journal-recording function, the care-team-reporting function, and the outcome-correlation function are separate Lambdas with their own IAM roles, error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, model IDs, the seam-detection rule definitions, the referral-lifecycle states, the transition-of-care protocol templates, and the engagement-policy thresholds are what you would change between environments.

```python
import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights for cross-call investigation.
# Care-coordination conversation logs and the coordination-
# state journal are dense PHI from multiple organizations:
# active conditions, current medications across pharmacies,
# open referrals, recent encounters, lab results, transition-
# of-care milestones, and caregiver context. Log structural
# metadata only (session_id, patient_id_hash, intent, tool
# name, tool latency, tool outcome, seam-flag IDs raised),
# never raw user utterances, never raw generated responses,
# never tool arguments that contain identifiers, never
# provenance excerpts. Full transcripts and full tool calls
# live in the audit pipeline (Firehose plus Object-Lock S3)
# with state-specific medical-record retention; the
# provenance journal lives on a separately-managed KMS key.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from Bedrock, DynamoDB,
# EventBridge, Firehose, CloudWatch, S3, Pinpoint, Connect,
# Step Functions, HealthLake, and Secrets Manager.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in
# warm containers so each invocation does not pay the
# connection cost.
REGION = "us-east-1"
bedrock_runtime       = boto3.client("bedrock-runtime",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
dynamodb              = boto3.resource("dynamodb",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
eventbridge_client    = boto3.client("events",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
firehose_client       = boto3.client("firehose",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
cloudwatch_client     = boto3.client("cloudwatch",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
s3_client             = boto3.client("s3",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
secrets_client        = boto3.client("secretsmanager",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
pinpoint_client       = boto3.client("pinpoint",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
connect_client        = boto3.client("connect",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
sfn_client            = boto3.client("stepfunctions",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)
healthlake_client     = boto3.client("healthlake",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
PATIENT_COORDINATION_TABLE       = "cc-patient-coordination"
COORDINATION_STATE_TABLE         = "cc-coordination-state"
REFERRAL_LIFECYCLE_TABLE         = "cc-referral-lifecycle"
TRANSITION_OF_CARE_TABLE         = "cc-transition-of-care"
SEAM_FLAG_TABLE                  = "cc-seam-flags"
CAREGIVER_TABLE                  = "cc-caregivers"
CONVERSATION_STATE_TABLE         = "cc-conversation-state"
CONVERSATION_METADATA_TABLE      = "cc-conversation-metadata"
TOOL_CALL_LEDGER_TABLE           = "cc-tool-call-ledger"
DECISION_RECORD_TABLE            = "cc-coordination-decision-journal"
PROVENANCE_JOURNAL_TABLE         = "cc-provenance-journal"
CONSENT_RECORD_TABLE             = "cc-consent-record"
COORD_EVENT_BUS_NAME             = "cc-coordination-events-bus"
AUDIT_ARCHIVE_FIREHOSE_NAME      = "cc-audit-archive"
DECISION_RECORD_BUCKET           = "cc-decision-journal"
PROVENANCE_ARCHIVE_BUCKET        = "cc-provenance-archive"
PINPOINT_APPLICATION_ID          = "PINPOINT_APP_PLACEHOLDER"
CONNECT_INSTANCE_ID              = "CONNECT_INSTANCE_PLACEHOLDER"
CONNECT_CONTACT_FLOW_ID          = "CONNECT_FLOW_PLACEHOLDER"
DISCHARGE_STATE_MACHINE_ARN      = "TOC_DISCHARGE_HOME_SM_ARN"
SNF_STATE_MACHINE_ARN            = "TOC_DISCHARGE_SNF_SM_ARN"
ED_FOLLOWUP_STATE_MACHINE_ARN    = "TOC_ED_FOLLOWUP_SM_ARN"
HEALTHLAKE_DATASTORE_ID          = "HEALTHLAKE_DS_PLACEHOLDER"
CLOUDWATCH_NAMESPACE             = "CareCoordination"

# Bedrock Knowledge Base IDs.
PROTOCOL_KB_ID                   = "PROTOCOL_KB_PLACEHOLDER"
PATIENT_EDUCATION_KB_ID          = "EDU_KB_PLACEHOLDER"
HISTORY_KB_ID                    = "HISTORY_KB_PLACEHOLDER"

# Bedrock Guardrail. Pin to a specific version, not DRAFT,
# in production.
GUARDRAIL_ID                     = "GUARDRAIL_PLACEHOLDER_ID"
GUARDRAIL_VERSION                = "1"

# KMS key IDs. The provenance journal uses a separately-
# managed customer key for blast-radius containment. A
# leaked credential to the general coordination workload
# should not give an attacker the provenance archive.
GENERAL_KMS_KEY_ID               = "GENERAL_KMS_PLACEHOLDER"
PROVENANCE_KMS_KEY_ID            = "PROVENANCE_KMS_PLACEHOLDER"
DECISION_RECORD_KMS_KEY_ID       = "DECISION_KMS_PLACEHOLDER"

# Deploy-time guardrail. Any blank resource name is a deploy-
# time bug, not a runtime surprise.
for _name, _value in [
    ("PATIENT_COORDINATION_TABLE", PATIENT_COORDINATION_TABLE),
    ("COORDINATION_STATE_TABLE",   COORDINATION_STATE_TABLE),
    ("REFERRAL_LIFECYCLE_TABLE",   REFERRAL_LIFECYCLE_TABLE),
    ("TRANSITION_OF_CARE_TABLE",   TRANSITION_OF_CARE_TABLE),
    ("SEAM_FLAG_TABLE",            SEAM_FLAG_TABLE),
    ("CAREGIVER_TABLE",            CAREGIVER_TABLE),
    ("CONVERSATION_STATE_TABLE",   CONVERSATION_STATE_TABLE),
    ("CONVERSATION_METADATA_TABLE",
                                   CONVERSATION_METADATA_TABLE),
    ("TOOL_CALL_LEDGER_TABLE",     TOOL_CALL_LEDGER_TABLE),
    ("DECISION_RECORD_TABLE",      DECISION_RECORD_TABLE),
    ("PROVENANCE_JOURNAL_TABLE",   PROVENANCE_JOURNAL_TABLE),
    ("CONSENT_RECORD_TABLE",       CONSENT_RECORD_TABLE),
    ("COORD_EVENT_BUS_NAME",       COORD_EVENT_BUS_NAME),
    ("AUDIT_ARCHIVE_FIREHOSE_NAME",
                                   AUDIT_ARCHIVE_FIREHOSE_NAME),
    ("DECISION_RECORD_BUCKET",     DECISION_RECORD_BUCKET),
    ("PROVENANCE_ARCHIVE_BUCKET",  PROVENANCE_ARCHIVE_BUCKET),
    ("CLOUDWATCH_NAMESPACE",       CLOUDWATCH_NAMESPACE),
    ("PROTOCOL_KB_ID",             PROTOCOL_KB_ID),
    ("PATIENT_EDUCATION_KB_ID",    PATIENT_EDUCATION_KB_ID),
    ("HISTORY_KB_ID",              HISTORY_KB_ID),
    ("GUARDRAIL_ID",               GUARDRAIL_ID),
    ("GUARDRAIL_VERSION",          GUARDRAIL_VERSION),
    ("GENERAL_KMS_KEY_ID",         GENERAL_KMS_KEY_ID),
    ("PROVENANCE_KMS_KEY_ID",      PROVENANCE_KMS_KEY_ID),
    ("DECISION_RECORD_KMS_KEY_ID", DECISION_RECORD_KMS_KEY_ID),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
PROMPT_VERSION                   = "cc-prompt-v1.0"
AGENT_VERSION                    = "cc-agent-v1.0"
PROTOCOL_CORPUS_VERSION          = "protocol-corpus-v1.0"
SEAM_RULE_LIBRARY_VERSION        = "seam-rules-v1.0"
INSTITUTION_ID                   = "acme-health-system"
INSTITUTION_DISPLAY_NAME         = "Acme Health Coordination"

# --- Model IDs ---
# TODO: verify the exact model IDs available in your region
# and account; Bedrock model availability evolves over time.
SMALL_MODEL_ID                   = "anthropic.claude-3-5-haiku-20241022-v1:0"
ORCHESTRATION_MODEL_ID           = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# --- Pipeline Tuning ---
INTENT_CONFIDENCE_THRESHOLD      = Decimal("0.70")
DEFAULT_ENGAGEMENT_INTENSITY     = "protocol_driven_with_quiet_hours"
INSTITUTION_REGULATORY_POSITION  = "informational"

# Default protocol windows (days) for a few common
# coordination triggers. Production has the full library
# in the protocol corpus with named clinical-leadership
# ownership and version history; the demo holds a small
# subset inline.
PROTOCOL_WINDOWS_DAYS = {
    "post_discharge_followup_routine":              7,
    "post_discharge_followup_high_risk":            3,
    "ed_to_pcp_followup":                           3,
    "post_procedure_followup":                      14,
    "specialty_referral_routine_scheduling":        14,
    "specialty_referral_urgent_scheduling":         3,
    "lab_result_acknowledgement":                   5,
    "discharge_med_reconciliation":                 2,
}
```

```python
# --- Referral-Lifecycle State Machine ---
# Each referral moves through this state machine. Production
# has the state machine signed off by clinical leadership,
# version-controlled, and audited; the demo holds the
# transitions inline.
REFERRAL_STATES = [
    "ordered",
    "communicated_to_patient",
    "scheduled",
    "rescheduled",
    "attended",
    "no_showed",
    "cancelled",
    "consult_note_received",
    "closed",
    "aged_out",
]

REFERRAL_TRANSITIONS = {
    "ordered":               {"communicated_to_patient",
                              "scheduled", "cancelled",
                              "aged_out"},
    "communicated_to_patient": {"scheduled", "cancelled",
                                "aged_out"},
    "scheduled":             {"rescheduled", "attended",
                              "no_showed", "cancelled"},
    "rescheduled":           {"attended", "no_showed",
                              "cancelled", "aged_out"},
    "attended":              {"consult_note_received",
                              "aged_out"},
    "no_showed":              {"scheduled", "cancelled",
                               "aged_out"},
    "cancelled":              set(),
    "consult_note_received":  {"closed"},
    "closed":                 set(),
    "aged_out":               set(),
}

# --- Seam-Detection Rules (illustrative) ---
# Production has the full rule library with named clinical-
# leadership ownership per rule and effective dates; the
# demo holds three illustrative rules inline.
SEAM_RULES = {
    "med_discrepancy_pharmacy_vs_clinician": {
        "rule_id": "med_discrepancy_pharmacy_vs_clinician",
        "owner":   "pharmacy_director",
        "effective_date": "2026-01-01",
        "version": "v1.0",
        "priority": "medium",
        "suggested_resolver": "care_team",
        "description":
            ("A pharmacy fill differs in dose or "
             "discontinuation status from the "
             "clinician's recorded order."),
    },
    "referral_not_scheduled_within_window": {
        "rule_id": "referral_not_scheduled_within_window",
        "owner":   "care_management_director",
        "effective_date": "2026-01-01",
        "version": "v1.0",
        "priority": "medium",
        "suggested_resolver": "patient_or_caregiver",
        "description":
            ("A referral has been ordered but has not "
             "been scheduled within the protocol window "
             "for its specialty and urgency tier."),
    },
    "transition_followup_appointment_missing": {
        "rule_id": "transition_followup_appointment_missing",
        "owner":   "post_discharge_director",
        "effective_date": "2026-01-01",
        "version": "v1.0",
        "priority": "high",
        "suggested_resolver": "patient_and_care_team",
        "description":
            ("A discharge plan called for follow-up "
             "within a protocol window and that "
             "appointment is not on the schedule."),
    },
}

# --- Standard Response Templates ---
GREETING_WITH_DISCLOSURE = (
    f"Hi, I'm {INSTITUTION_DISPLAY_NAME}'s coordination "
    "tool. Just a reminder before we get started: I'm a "
    "chat tool, not a person, and I work alongside your "
    "care team. I can help you keep track of appointments, "
    "referrals, and medications across your different "
    "doctors, and I'll flag things to your care team when "
    "they need a clinician's eyes. If you have an urgent "
    "medical concern, please call your care team or 911. "
    "How can I help today?"
)

OUT_OF_SCOPE_DIAGNOSIS_ATTEMPTED = (
    "I can't tell you what's causing those symptoms. That's "
    "a conversation for you and a clinician. I can flag "
    "this to your care team to follow up, or if it feels "
    "urgent, please call them directly or go to an "
    "emergency department."
)

OUT_OF_SCOPE_DOSE_TITRATION = (
    "I can't make recommendations about medication doses. "
    "Anything about doses, timing, side effects, or "
    "starting and stopping medications needs to go through "
    "your prescriber. Want me to send a message to your "
    "care team about this?"
)

OUT_OF_SCOPE_TRIAGE = (
    "What you're describing sounds like something to talk "
    "through with the triage line, not with me. I'll bring "
    "the triage workflow up for you now; if you feel this "
    "is an emergency, please call 911."
)

UNGROUNDED_RESPONSE_FALLBACK = (
    "Let me check this with your care team rather than "
    "guess. I'll flag this and follow up; if anything "
    "urgent comes up in the meantime, please call your "
    "care team's line or 911."
)

# --- Prompt-Injection Patterns ---
INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) "
    r"(instructions|messages|prompts)",
    r"disregard (all |any |the )?(previous|prior|above) "
    r"(instructions|messages|prompts)",
    r"you are now (a |an )?(doctor|nurse|clinician|"
    r"therapist)",
    r"forget (all |any |everything )?(you|your)",
    r"system (prompt|message|instruction)",
    r"reveal (your|the) (prompt|instructions|system)",
    r"act as (a |an )?(doctor|nurse|clinician)",
    r"new instructions:",
    # Coordination-specific injection attempts.
    r"show (me|us) (other|another) (patient|patients)",
    r"skip (the )?(consent|caregiver) (check|verification)",
    r"override (the )?(seam|protocol)",
]

# --- PHI Patterns for redaction in logs ---
PHI_PATTERNS = {
    "ssn_like":       re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "card_number_like":
        re.compile(r"\b\d{15,16}\b"),
}
```

---

## Shared Helpers

A few utilities used across steps. Keeping them together so each step's code stays focused on the pattern it teaches.

```python
def _to_decimal(obj):
    """
    Recursively convert floats to Decimal for DynamoDB.
    DynamoDB rejects Python float values; every numeric field
    has to pass through Decimal on the way in.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(v) for v in obj]
    return obj


def _from_decimal(obj):
    """Inverse of _to_decimal for JSON serialization."""
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_decimal(v) for v in obj]
    return obj


def _now_iso() -> str:
    """Current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


def _redact_pii_for_logging(text: str) -> str:
    """Light redaction for log lines."""
    redacted = text
    for pattern in PHI_PATTERNS.values():
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _emit_event(detail_type: str, detail: dict) -> None:
    """
    Emit an EventBridge event. Wrapped in try/except so a
    transient EventBridge failure does not block the
    pipeline. Production downstream consumers use the
    suggested idempotency keys (encounter_id, referral_id,
    transition_id, seam_flag_id, decision_id, provenance_id)
    to deduplicate on retry.
    """
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "care_coordination",
            "DetailType":   detail_type,
            "Detail":       json.dumps(_from_decimal(detail)),
            "EventBusName": COORD_EVENT_BUS_NAME,
        }])
    except Exception as exc:
        logger.error(
            "EventBridge emit failed for %s: %s",
            detail_type, exc)


def _put_metric(metric_name: str, value: float,
                dimensions: dict) -> None:
    """Emit a CloudWatch metric. Best-effort; never blocks."""
    try:
        cloudwatch_client.put_metric_data(
            Namespace=CLOUDWATCH_NAMESPACE,
            MetricData=[{
                "MetricName": metric_name,
                "Value":      value,
                "Unit":       "Count",
                "Dimensions": [
                    {"Name": k, "Value": str(v)}
                    for k, v in dimensions.items()
                ],
            }])
    except Exception as exc:
        logger.error(
            "CloudWatch put_metric_data failed for %s: %s",
            metric_name, exc)


def _audit_tool_call(session_id: str,
                      tool: str,
                      arguments: dict,
                      result_summary: dict,
                      latency_ms: int,
                      outcome: str) -> None:
    """Persist a tool-call ledger entry."""
    try:
        table = dynamodb.Table(TOOL_CALL_LEDGER_TABLE)
        table.put_item(Item=_to_decimal({
            "session_id":         session_id,
            "invoked_at":         _now_iso(),
            "tool":               tool,
            "arguments_summary":  _redact_tool_args(arguments),
            "result_summary":     result_summary,
            "latency_ms":         latency_ms,
            "outcome":            outcome,
        }))
    except Exception as exc:
        logger.error(
            "Tool-call ledger write failed for %s/%s: %s",
            session_id, tool, exc)


def _redact_tool_args(arguments: dict) -> dict:
    """Strip sensitive fields before ledger storage."""
    redacted = dict(arguments)
    sensitive_keys = {
        "patient_id", "name", "date_of_birth",
        "user_message", "free_text", "phone",
        "email", "address", "caregiver_phone",
        "caregiver_email", "provenance_excerpt",
    }
    for key in list(redacted.keys()):
        if key in sensitive_keys:
            redacted[key] = "[REDACTED]"
    return redacted
```

---

## Mock Infrastructure

Production calls real Bedrock endpoints, real DynamoDB tables, real HealthLake FHIR endpoints, real HL7 listeners, real FHIR pollers, real Connect contact-center handoffs, and real care-team workflows. The demo replaces these with small in-memory mocks so it can run without any AWS resources configured. Read this section to understand what each mock stands in for; replace each one with a real client when you wire this into your environment.

```python
class MockTable:
    """Stands in for a DynamoDB table for the demo."""

    def __init__(self, name, partition_key="session_id"):
        self.name = name
        self.items = {}
        self.partition_key = partition_key

    def put_item(self, Item):
        key = (Item.get(self.partition_key)
               or Item.get("decision_id")
               or Item.get("seam_flag_id")
               or Item.get("referral_id")
               or Item.get("transition_id")
               or Item.get("provenance_id")
               or Item.get("alert_id")
               or str(uuid.uuid4()))
        self.items.setdefault(key, []).append(_from_decimal(Item))

    def get_item(self, Key):
        key_value = list(Key.values())[0]
        records = self.items.get(key_value, [])
        if records:
            return {"Item": records[-1]}
        return {}

    def query(self, **kwargs):
        items = []
        for record_list in self.items.values():
            items.extend(record_list)
        return {"Items": items}

    def scan(self, **kwargs):
        return self.query()

    def update_item(self, Key, **kwargs):
        return {}


class MockBedrockRuntime:
    """
    Stands in for bedrock-runtime invoke_model. The mock
    composes structured responses from the coordination
    context the calling code supplies; production lets the
    LLM compose the conversational language while the
    citation-grounding verifier, scope-filter, and faithful-
    ness verifier keep it honest.
    """

    def invoke_response(self, *,
                          user_message,
                          coordination_context,
                          system_prompt):
        """Compose a response to a patient or caregiver utterance."""
        msg_lower = user_message.lower()

        # Scenario: post-discharge med-list reconciliation
        # question. The bot retrieves the medication list,
        # surfaces the discrepancy, and proposes a care-team
        # alert.
        if ("furosemide" in msg_lower or
            "diuretic" in msg_lower or
            "60 mg" in msg_lower):
            return {
                "response_text": (
                    "Thanks for telling me. The dose change "
                    "you're describing is different from "
                    "what I have from your discharge list. "
                    "I'm flagging this to your primary care "
                    "nurse to confirm with the cardiology "
                    "office. Until that's confirmed, please "
                    "stay on the discharge dose. I'm not "
                    "making the dose decision; the "
                    "clinicians are."),
                "citations": [{
                    "kind":     "coordination_state",
                    "id":       "discharge_med_list",
                    "provenance_id": "prov_demo_dx_meds",
                }, {
                    "kind":     "protocol",
                    "id":       "post_discharge_med_recon_v1",
                    "version":  "v1.0",
                }],
                "tool_calls": [
                    {"tool": "medication_list_reconcile",
                     "args": {"patient_id":
                                  coordination_context.get(
                                      "patient_id", "")}},
                    {"tool": "care_team_alert_propose",
                     "args": {"alert_type":
                                  "med_discrepancy"}},
                ],
            }

        # Scenario: referral status question. The bot
        # retrieves the referral lifecycle state and
        # explains where things stand.
        if ("referral" in msg_lower or
            "specialist" in msg_lower or
            "appointment with the" in msg_lower):
            return {
                "response_text": (
                    "Let me check on that referral. Your "
                    "primary care doctor sent a referral to "
                    "cardiology two weeks ago. It looks "
                    "like the appointment hasn't been "
                    "scheduled yet. The protocol window for "
                    "this kind of referral is two weeks, so "
                    "we're at the edge. I can flag this for "
                    "the scheduling team to call you, or "
                    "you can call cardiology directly at "
                    "the number on your after-visit "
                    "summary. Which would you prefer?"),
                "citations": [{
                    "kind":     "referral",
                    "id":       "ref_demo_cardiology",
                    "provenance_id": "prov_demo_pcm_referral",
                }, {
                    "kind":     "protocol",
                    "id":       "specialty_referral_v1",
                    "version":  "v1.0",
                }],
                "tool_calls": [
                    {"tool": "referral_lifecycle_retrieve",
                     "args": {"patient_id":
                                  coordination_context.get(
                                      "patient_id", "")}},
                    {"tool": "patient_action_propose",
                     "args": {"action_type":
                                  "scheduling_assistance"}},
                ],
            }

        # Scenario: out-of-scope clinical question (dose
        # titration).
        if ("should i take" in msg_lower or
            "should i increase" in msg_lower or
            "should i lower" in msg_lower):
            return {
                "response_text": OUT_OF_SCOPE_DOSE_TITRATION,
                "citations": [],
                "tool_calls": [
                    {"tool": "care_team_alert_propose",
                     "args": {"alert_type":
                                  "medication_question"}},
                ],
            }

        # Scenario: post-discharge welcome-home check-in.
        if ("how are things" in msg_lower or
            "post-discharge" in msg_lower or
            "got home" in msg_lower or
            "okay" in msg_lower):
            return {
                "response_text": (
                    "Glad you made it home. I'm going to "
                    "walk through a couple of things: the "
                    "medication list from your discharge, "
                    "your follow-up appointment with "
                    "cardiology, and a few signs that "
                    "would mean call your care team. Sound "
                    "okay?"),
                "citations": [{
                    "kind":     "protocol",
                    "id":       "post_discharge_welcome_home",
                    "version":  "v1.0",
                }],
                "tool_calls": [
                    {"tool": "protocol_retrieve",
                     "args": {"protocol_type":
                                  "post_discharge_welcome_home"}},
                ],
            }

        # Default within-scope generic response.
        return {
            "response_text": (
                "Thanks. What would be most useful to "
                "talk through right now? I can check on "
                "your appointments, your medication list, "
                "or any open referrals."),
            "citations": [],
            "tool_calls": [],
        }


class MockHealthLake:
    """
    Stands in for AWS HealthLake. Production queries this
    for FHIR resources (Patient, Encounter, Condition,
    MedicationRequest, MedicationStatement, Observation,
    DiagnosticReport, ServiceRequest, CarePlan,
    AllergyIntolerance, Immunization, Coverage); the demo
    holds a small dict per patient.
    """

    def __init__(self):
        self.charts = {}

    def add_patient(self, patient_id, chart):
        self.charts[patient_id] = chart

    def get_chart(self, patient_id):
        return self.charts.get(patient_id, {})


class MockProtocolCorpus:
    """Stands in for the coordination-protocol Knowledge Base."""

    def __init__(self):
        self.protocols = {
            "post_discharge_welcome_home": {
                "id":      "post_discharge_welcome_home",
                "version": "v1.0",
                "owner":   "post_discharge_director",
                "destination_setting": "home",
                "trigger_window_hours": 48,
                "items": [
                    "medication_reconciliation",
                    "followup_appointment_validation",
                    "red_flag_warning_delivery",
                    "patient_education_delivery",
                    "symptom_monitoring_engagement",
                    "closure_verification",
                ],
            },
            "post_discharge_med_recon_v1": {
                "id":      "post_discharge_med_recon_v1",
                "version": "v1.0",
                "owner":   "pharmacy_director",
                "items": [
                    "compare_discharge_list_to_preadmit",
                    "reconcile_against_pharmacy_fills",
                    "surface_discrepancies_for_review",
                ],
            },
            "specialty_referral_v1": {
                "id":      "specialty_referral_v1",
                "version": "v1.0",
                "owner":   "care_management_director",
                "items": [
                    "confirm_patient_received_referral",
                    "walk_through_scheduling_step",
                    "surface_external_barriers",
                    "track_appointment_to_attended",
                    "verify_consult_note_received",
                ],
            },
        }

    def retrieve(self, protocol_type=None):
        return self.protocols.get(protocol_type)


class MockClinicianQueue:
    """Stands in for Amazon Connect care-management queue."""

    def __init__(self):
        self.alerts = []
        self.handoffs = []

    def deliver_alert(self, payload):
        self.alerts.append({**payload,
                            "delivered_at": _now_iso()})

    def initiate_handoff(self, payload):
        self.handoffs.append({**payload,
                               "queued_at": _now_iso()})


class MockEventBus:
    """Stands in for EventBridge."""

    def __init__(self):
        self.events = []

    def put_events(self, Entries):
        for entry in Entries:
            self.events.append(entry)
        return {"FailedEntryCount": 0}


class MockPinpoint:
    """Stands in for Pinpoint message dispatch."""

    def __init__(self):
        self.messages = []

    def send_messages(self, **kwargs):
        self.messages.append(kwargs)
        return {"MessageResponse": {"Result": {}}}


class MockS3:
    """Stands in for S3 PutObject for the audit archive."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[(Bucket, Key)] = {
            "Body": Body,
            "kms_key": kwargs.get("SSEKMSKeyId"),
        }
        return {}


class MockCloudWatch:
    """Stands in for CloudWatch metrics."""

    def __init__(self):
        self.metrics = []

    def put_metric_data(self, Namespace, MetricData):
        for record in MetricData:
            self.metrics.append({
                "namespace": Namespace,
                **record,
            })


class MockStepFunctions:
    """Stands in for Step Functions transition-of-care workflows."""

    def __init__(self):
        self.executions = []

    def start_execution(self, **kwargs):
        execution_id = (f"arn:demo:execution:"
                        f"{uuid.uuid4().hex[:12]}")
        self.executions.append({
            "execution_id":   execution_id,
            "state_machine": kwargs.get("stateMachineArn"),
            "input":          kwargs.get("input"),
            "started_at":     _now_iso(),
        })
        return {"executionArn": execution_id}


# Module-level mock instances.
mock_bedrock           = MockBedrockRuntime()
mock_healthlake        = MockHealthLake()
mock_protocols         = MockProtocolCorpus()
mock_clinician_queue   = MockClinicianQueue()

mock_tables = {
    PATIENT_COORDINATION_TABLE:  MockTable(
        PATIENT_COORDINATION_TABLE, "patient_id"),
    COORDINATION_STATE_TABLE:    MockTable(
        COORDINATION_STATE_TABLE, "patient_id"),
    REFERRAL_LIFECYCLE_TABLE:    MockTable(
        REFERRAL_LIFECYCLE_TABLE, "referral_id"),
    TRANSITION_OF_CARE_TABLE:    MockTable(
        TRANSITION_OF_CARE_TABLE, "transition_id"),
    SEAM_FLAG_TABLE:             MockTable(
        SEAM_FLAG_TABLE, "seam_flag_id"),
    CAREGIVER_TABLE:             MockTable(
        CAREGIVER_TABLE, "caregiver_id"),
    CONVERSATION_STATE_TABLE:    MockTable(
        CONVERSATION_STATE_TABLE, "session_id"),
    CONVERSATION_METADATA_TABLE: MockTable(
        CONVERSATION_METADATA_TABLE, "session_id"),
    TOOL_CALL_LEDGER_TABLE:      MockTable(
        TOOL_CALL_LEDGER_TABLE, "session_id"),
    DECISION_RECORD_TABLE:       MockTable(
        DECISION_RECORD_TABLE, "decision_id"),
    PROVENANCE_JOURNAL_TABLE:    MockTable(
        PROVENANCE_JOURNAL_TABLE, "provenance_id"),
    CONSENT_RECORD_TABLE:        MockTable(
        CONSENT_RECORD_TABLE, "patient_id"),
}


def _mock_dynamodb_table(name):
    return mock_tables[name]


# Replace boto3 dynamodb.Table with the mock for the demo.
dynamodb.Table = _mock_dynamodb_table

# Replace EventBridge, Pinpoint, S3, CloudWatch, Step
# Functions clients with mocks for the demo.
eventbridge_client = MockEventBus()
pinpoint_client    = MockPinpoint()
s3_client          = MockS3()
cloudwatch_client  = MockCloudWatch()
sfn_client         = MockStepFunctions()
```

---

## Step 1: Enroll the Patient with Cross-Organizational Consent and Caregiver Setup

This is the foundation. Care-coordination enrollment is more involved than enrollment for the previous chapter 11 bots because the consent posture covers multiple data sources, multiple sharing relationships, and (often) one or more caregivers with proxy-access scope. The consent flow has been reviewed by legal counsel familiar with HIPAA, the Information Blocking rule, state-specific medical-record statutes, state-specific caregiver-consent rules, and (where applicable) 42 CFR Part 2, state-specific mental-health-record protections, and other sensitive-record rules. Skip this step or treat it as boilerplate, and the deployment's regulatory posture is compromised before the first conversation.

```python
def enroll_patient(*,
                    patient_id,
                    enrollment_program_id,
                    state_of_residence,
                    legal_consent_form,
                    caregiver_designations=None,
                    known_relationships=None):
    """
    Enroll a patient into the care-coordination program.
    Validates eligibility, captures cross-organizational
    consent, designates caregivers with proxy-access scope,
    captures known clinicians/pharmacies/payers/ancillary
    services, captures preferences, and emits the
    enrollment event.
    """
    caregiver_designations = caregiver_designations or []
    known_relationships    = known_relationships or {}

    # Step 1A: validate eligibility against institutional
    # exclusion criteria.
    eligibility = _check_eligibility(
        patient_id=patient_id,
        program=enrollment_program_id)

    if not eligibility["eligible"]:
        return {
            "action":    "enrollment_declined",
            "reason":    eligibility["reason"],
            "referral":  eligibility.get(
                "recommended_alternative"),
        }

    # Step 1B: capture cross-organizational consent posture.
    # Consent is per data source and per sharing relation-
    # ship. The consent record is the operational gate the
    # architecture enforces; it is not optional and not
    # bypass-able from the assistant.
    state_provisions = _state_specific_consent_provisions(
        state_of_residence)

    consent_record = {
        "patient_id":           patient_id,
        "consent_id":           f"consent_{uuid.uuid4().hex}",
        "consent_version":      "v1.0",
        "data_source_consents":
            legal_consent_form.get(
                "data_source_consents", {}),
        "sharing_relationships":
            legal_consent_form.get(
                "sharing_relationships", []),
        "sensitive_record_categories":
            legal_consent_form.get(
                "sensitive_record_categories", {}),
        "revocability":         "revocable_at_any_time",
        "signed_at":            _now_iso(),
        "state_of_residence":   state_of_residence,
        "state_specific_provisions": state_provisions,
    }

    consent_table = dynamodb.Table(CONSENT_RECORD_TABLE)
    consent_table.put_item(Item=_to_decimal(consent_record))

    # Step 1C: capture caregiver designations.
    # Each caregiver gets a separate identity, separate
    # authentication, separate proxy-access scope, and
    # separate state-law access posture.
    caregiver_records = []
    caregiver_table = dynamodb.Table(CAREGIVER_TABLE)

    for cg in caregiver_designations:
        caregiver_id = f"cg_{uuid.uuid4().hex}"
        cg_record = {
            "caregiver_id":      caregiver_id,
            "patient_id":        patient_id,
            "preferred_name":    cg.get("preferred_name", ""),
            "relationship":      cg.get("relationship", ""),
            "access_level":      cg.get(
                "access_level", "scheduling_only"),
            "sensitive_record_carve_outs":
                cg.get("sensitive_carve_outs", []),
            "channels":          cg.get(
                "channels", ["sms"]),
            "state_law_check":   _check_state_caregiver_law(
                state_of_residence,
                cg.get("relationship", "")),
            "designated_at":     _now_iso(),
        }
        caregiver_table.put_item(
            Item=_to_decimal(cg_record))
        caregiver_records.append(cg_record)

    # Step 1D: persist the patient-coordination record.
    # Captures known clinicians, pharmacies, payers,
    # ancillary services, and patient preferences.
    patient_record = {
        "patient_id":           patient_id,
        "enrollment_program_id": enrollment_program_id,
        "consent_id":           consent_record["consent_id"],
        "caregiver_ids":
            [cg["caregiver_id"] for cg in caregiver_records],
        "known_relationships":  known_relationships,
        "preferences": {
            "preferred_name":
                legal_consent_form.get(
                    "preferred_name", ""),
            "language":
                legal_consent_form.get(
                    "language", "en-US"),
            "preferred_channels":
                legal_consent_form.get(
                    "channels", ["in_app", "sms"]),
            "quiet_hours":
                legal_consent_form.get(
                    "quiet_hours",
                    {"start": "21:00", "end": "08:00"}),
            "engagement_intensity":
                DEFAULT_ENGAGEMENT_INTENSITY,
        },
        "state_of_residence":   state_of_residence,
        "enrolled_at":          _now_iso(),
        "active":               True,
    }

    patient_table = dynamodb.Table(
        PATIENT_COORDINATION_TABLE)
    patient_table.put_item(Item=_to_decimal(patient_record))

    # Step 1E: initialize the empty coordination state.
    coordination_state = {
        "patient_id":             patient_id,
        "active_conditions":      [],
        "active_medication_list": [],
        "open_referrals":         [],
        "upcoming_encounters":    [],
        "recent_encounters":      [],
        "recent_test_results":    [],
        "active_care_events":     [],
        "seam_flag_ids":          [],
        "state_version":          1,
        "last_updated":           _now_iso(),
    }
    state_table = dynamodb.Table(COORDINATION_STATE_TABLE)
    state_table.put_item(Item=_to_decimal(coordination_state))

    # Step 1F: emit enrollment events for downstream systems.
    _emit_event("patient_enrolled", {
        "patient_id":             patient_id,
        "enrollment_program_id":  enrollment_program_id,
        "consent_id":             consent_record["consent_id"],
    })
    for cg in caregiver_records:
        _emit_event("caregiver_designated", {
            "patient_id":   patient_id,
            "caregiver_id": cg["caregiver_id"],
        })

    _put_metric("PatientEnrolled", 1, {
        "Program": enrollment_program_id,
        "State":   state_of_residence,
    })

    return {
        "action":            "enrolled",
        "patient_id":        patient_id,
        "consent_id":        consent_record["consent_id"],
        "caregiver_ids":
            [cg["caregiver_id"] for cg in caregiver_records],
    }


def _check_eligibility(*, patient_id, program):
    """
    Check the patient against institutional exclusion
    criteria. Production runs this against the FHIR chart
    context plus the institution's clinical-leadership-
    defined exclusion rules.
    """
    chart = mock_healthlake.get_chart(patient_id)

    # Active hospice patients are typically out of scope
    # for general coordination programs.
    if chart.get("active_hospice"):
        return {
            "eligible": False,
            "reason":   "active_hospice",
            "recommended_alternative":
                "hospice_specific_coordination",
        }

    # Pediatric in adult-only programs.
    if program.startswith("adult_") and \
            chart.get("age", 30) < 18:
        return {
            "eligible": False,
            "reason":   "minor_in_adult_only_program",
            "recommended_alternative":
                "pediatric_complex_care_coordination",
        }

    return {"eligible": True}


def _state_specific_consent_provisions(state_of_residence):
    """
    Resolve state-specific medical-record privacy
    provisions. Production has the per-state matrix
    reviewed by legal counsel; the demo returns a small
    illustrative subset.
    """
    enhanced_states = {
        "CA": {"enhanced_protections": True,
               "statute": "CA_CMIA"},
        "NY": {"enhanced_protections": True,
               "statute": "NY_PHL"},
        "IL": {"enhanced_protections": True,
               "statute": "IL_MHDDC"},
        "MA": {"enhanced_protections": True,
               "statute": "MA_Chapter_111"},
    }
    return enhanced_states.get(
        state_of_residence,
        {"enhanced_protections": False,
         "statute": "HIPAA_baseline"})


def _check_state_caregiver_law(state_of_residence,
                                  relationship):
    """
    Check state-specific caregiver-consent and proxy-
    access requirements. Production has per-state matrix
    reviewed by legal counsel; the demo returns a thin
    placeholder.
    """
    return {
        "state":         state_of_residence,
        "relationship":  relationship,
        "documentation_required":
            relationship in ["healthcare_proxy",
                             "power_of_attorney"],
    }
```

The enrollment function is doing six things in order. The eligibility check filters out patients the assistant is not designed to serve. The cross-organizational consent record captures per-data-source and per-sharing-relationship consent with state-specific provisions. Caregiver designations get separate identity records with proxy-access scope and state-law-compliance checks. The patient-coordination record captures the known relationships and patient preferences. The empty coordination state is initialized for the ingestion layer to populate. Enrollment events flow out for population-health and per-cohort monitoring.

---

## Step 2: Ingest Cross-Organizational Data with Provenance Discipline

The ingestion layer is the architectural floor for the coordination assistant. Every data point ingested is recorded with its source, its timestamp, its ingestion path, and its integrity hash. The ingestion pipeline is composed of per-source adapters; each adapter handles authentication, rate limiting, format translation, sensitive-record classification, and provenance recording. The demo collapses the per-source adapters into a single `ingest_event` function that handles a few representative source types; production has a separate Lambda per source with its own IAM role, retry behavior, and DLQ.

```python
def ingest_event(*,
                  source_type,
                  raw_message,
                  ingestion_metadata):
    """
    Ingest a single cross-organizational data point.
    Validates, classifies sensitivity, enforces consent,
    records provenance, normalizes, reconciles against
    the existing coordination state, and emits care-event
    triggers for downstream protocol and seam-detection
    processing.
    """
    # Step 2A: route to the appropriate per-source adapter
    # for parsing. The demo supports a few representative
    # types; production has a separate adapter per source.
    if source_type not in {
        "hl7_v2_adt",
        "hl7_v2_oru",
        "fhir_subscription",
        "claims_batch",
        "pharmacy_ncpdp",
        "home_health_vendor_api",
        "patient_reported",
    }:
        return {"action": "rejected",
                "reason": "unknown_source_type"}

    # Step 2B: parse and validate.
    parsed = _parse_message(source_type, raw_message)
    if not parsed.get("patient_id"):
        return {"action": "rejected",
                "reason": "missing_patient_id"}

    # Step 2C: classify sensitive-record categories. Some
    # categories trigger separate handling per state and
    # federal rules; this is operational, not optional.
    sensitivity = _classify_sensitivity(parsed)

    # Step 2D: enforce per-source consent posture. If the
    # patient has not consented to ingestion from this
    # source, or has revoked consent, the data is dropped
    # and the revocation is honored.
    consent_check = _verify_consent(
        patient_id=parsed["patient_id"],
        source_type=source_type,
        sensitivity_category=sensitivity["category"])

    if not consent_check["allowed"]:
        return {"action": "consent_denied"}

    # Step 2E: write to the provenance journal. Provenance
    # records are append-only and on a separately-managed
    # KMS key for blast-radius containment.
    provenance_id = _write_provenance(
        patient_id=parsed["patient_id"],
        source_type=source_type,
        ingestion_metadata=ingestion_metadata,
        parsed=parsed,
        sensitivity_category=sensitivity["category"],
        raw_message=raw_message)

    # Step 2F: normalize to the coordination-state schema.
    normalized = _normalize_event(source_type, parsed)

    # Step 2G: reconcile against existing coordination state.
    reconciliation = _reconcile_with_state(
        patient_id=parsed["patient_id"],
        normalized_event=normalized,
        provenance_id=provenance_id)

    # Step 2H: update the coordination-state-store with
    # provenance references preserved.
    _update_coordination_state(
        patient_id=parsed["patient_id"],
        normalized_event=normalized,
        reconciliation=reconciliation,
        provenance_id=provenance_id)

    # Step 2I: emit care-event triggers for downstream
    # protocol and seam-detection processing.
    triggers = _derive_triggers(normalized, reconciliation)
    for trigger in triggers:
        _emit_event(trigger["type"], trigger["payload"])

    return {
        "action":          "ingested",
        "provenance_id":   provenance_id,
        "triggers_emitted": len(triggers),
    }


def _parse_message(source_type, raw_message):
    """
    Per-source parsing. The demo accepts pre-structured
    dicts; production has dedicated parsers (hl7apy or
    similar for HL7 v2; the FHIR resources from the FHIR
    APIs are already structured; NCPDP for pharmacy; vendor-
    specific formats for home health).
    """
    if isinstance(raw_message, dict):
        return raw_message
    return {}


def _classify_sensitivity(parsed):
    """
    Classify the sensitive-record category. Production has
    a calibrated classifier reviewed by legal counsel and
    clinical leadership; the demo runs a rule-based check.
    Categories include "general", "mental_health",
    "substance_use_42_cfr_part_2", "hiv", "genetic", and
    "adolescent_confidential".
    """
    text = json.dumps(parsed).lower()

    if "substance use" in text or \
            "42 cfr" in text or \
            "addiction" in text:
        return {"category": "substance_use_42_cfr_part_2"}
    if "psychiatric" in text or \
            "mental health" in text or \
            "behavioral health" in text:
        return {"category": "mental_health"}
    if "hiv" in text:
        return {"category": "hiv"}
    if "genetic" in text or "brca" in text:
        return {"category": "genetic"}
    return {"category": "general"}


def _verify_consent(*, patient_id, source_type,
                       sensitivity_category):
    """
    Check the patient's consent posture against the data
    source and the sensitivity category. Sensitivity
    categories may require explicit category-specific
    consent per state and federal rules.
    """
    consent_table = dynamodb.Table(CONSENT_RECORD_TABLE)
    consent_record = consent_table.get_item(
        Key={"patient_id": patient_id}).get("Item", {})

    if not consent_record:
        return {"allowed": False,
                "reason":  "no_consent_record"}

    source_consents = consent_record.get(
        "data_source_consents", {})
    if source_consents.get(source_type) is False:
        return {"allowed": False,
                "reason":  "source_not_consented"}

    if sensitivity_category != "general":
        sensitive_consents = consent_record.get(
            "sensitive_record_categories", {})
        if not sensitive_consents.get(
                sensitivity_category):
            return {"allowed": False,
                    "reason":
                        f"{sensitivity_category}_not_consented"}

    return {"allowed": True}


def _write_provenance(*, patient_id, source_type,
                         ingestion_metadata, parsed,
                         sensitivity_category, raw_message):
    """
    Append the provenance record. The provenance journal
    is on a separately-managed KMS key for blast-radius
    containment and is mirrored to the provenance archive
    in S3 with Object Lock in compliance mode.
    """
    provenance_id = f"prov_{uuid.uuid4().hex}"
    record = {
        "provenance_id":         provenance_id,
        "patient_id":            patient_id,
        "source_type":           source_type,
        "source_message_id":
            ingestion_metadata.get("message_id", ""),
        "source_timestamp":
            parsed.get("source_timestamp", _now_iso()),
        "ingestion_timestamp":   _now_iso(),
        "ingestion_path":
            ingestion_metadata.get("path", ""),
        "integrity_hash":
            str(hash(json.dumps(raw_message,
                                 sort_keys=True,
                                 default=str))),
        "sensitivity_category":  sensitivity_category,
    }

    table = dynamodb.Table(PROVENANCE_JOURNAL_TABLE)
    table.put_item(Item=_to_decimal(record))

    # Mirror to the separately-keyed S3 archive. Production
    # uses a different KMS key from the general decision-
    # record archive.
    s3_key = (
        f"provenance/{patient_id}/"
        f"{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/"
        f"{provenance_id}.json")
    s3_client.put_object(
        Bucket=PROVENANCE_ARCHIVE_BUCKET,
        Key=s3_key,
        Body=json.dumps(_from_decimal(record)),
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=PROVENANCE_KMS_KEY_ID)

    return provenance_id


def _normalize_event(source_type, parsed):
    """
    Normalize the event to the coordination-state schema.
    For FHIR-native sources, the event is already in
    FHIR-aligned shape; for HL7 v2 and other non-FHIR
    sources, this maps to FHIR-aligned shapes for
    consistency. Demo: passes through with type tagging.
    """
    return {
        "kind":        _kind_from_source_type(source_type),
        "source_type": source_type,
        "patient_id":  parsed.get("patient_id"),
        "data":        parsed,
        "ingested_at": _now_iso(),
    }


def _kind_from_source_type(source_type):
    """Map source type to coordination-state record kind."""
    return {
        "hl7_v2_adt":            "encounter",
        "hl7_v2_oru":            "lab_result",
        "fhir_subscription":     "fhir_resource",
        "claims_batch":          "claim_event",
        "pharmacy_ncpdp":        "medication_fill",
        "home_health_vendor_api":"home_health_visit",
        "patient_reported":      "patient_reported",
    }.get(source_type, "unknown")


def _reconcile_with_state(*, patient_id, normalized_event,
                              provenance_id):
    """
    Reconcile the new event against existing coordination
    state. Returns the reconciliation outcome (new entry,
    update, conflict, duplicate). Production has rules per
    record class (encounter, medication, referral, lab
    result); the demo runs a thin check.
    """
    return {
        "update_type": "new_entry",
        "details":     {},
    }


def _update_coordination_state(*, patient_id,
                                  normalized_event,
                                  reconciliation,
                                  provenance_id):
    """
    Update the coordination-state store with the new entry,
    preserving the provenance reference.
    """
    state_table = dynamodb.Table(COORDINATION_STATE_TABLE)
    current = state_table.get_item(
        Key={"patient_id": patient_id}).get("Item", {})

    if not current:
        current = {
            "patient_id":             patient_id,
            "active_conditions":      [],
            "active_medication_list": [],
            "open_referrals":         [],
            "upcoming_encounters":    [],
            "recent_encounters":      [],
            "recent_test_results":    [],
            "active_care_events":     [],
            "seam_flag_ids":          [],
            "state_version":          0,
            "last_updated":           _now_iso(),
        }

    # Demo: append to the appropriate registry by kind.
    kind = normalized_event["kind"]
    entry = {
        "data":          normalized_event["data"],
        "provenance_id": provenance_id,
        "ingested_at":   normalized_event["ingested_at"],
    }
    registry_map = {
        "encounter":         "recent_encounters",
        "lab_result":        "recent_test_results",
        "medication_fill":
            "active_medication_list",
        "fhir_resource":     "recent_encounters",
        "home_health_visit": "recent_encounters",
        "claim_event":       "recent_encounters",
        "patient_reported":  "active_care_events",
    }
    target = registry_map.get(kind, "active_care_events")
    current.setdefault(target, []).append(entry)
    current["state_version"] = (
        int(current.get("state_version", 0)) + 1)
    current["last_updated"] = _now_iso()

    state_table.put_item(Item=_to_decimal(current))


def _derive_triggers(normalized_event, reconciliation):
    """
    Derive care-event triggers for downstream processing.
    Triggers fire seam-detection rules and protocol
    workflows.
    """
    triggers = []
    kind = normalized_event["kind"]
    data = normalized_event["data"]

    if kind == "encounter":
        if data.get("event_type") == "discharge":
            triggers.append({
                "type":    "discharge_event",
                "payload": {
                    "patient_id": data.get("patient_id"),
                    "encounter_id":
                        data.get("encounter_id"),
                    "destination":
                        data.get("destination", "home"),
                    "admission_type":
                        data.get("admission_type",
                                  "unspecified"),
                },
            })
        else:
            triggers.append({
                "type":    "encounter_ingested",
                "payload": {
                    "patient_id":
                        data.get("patient_id"),
                    "encounter_id":
                        data.get("encounter_id"),
                },
            })

    if kind == "fhir_resource":
        if data.get("resourceType") == "ServiceRequest":
            triggers.append({
                "type":    "referral_ordered",
                "payload": {
                    "patient_id": data.get("patient_id"),
                    "referral_id":
                        data.get("id",
                                 f"ref_{uuid.uuid4().hex}"),
                    "specialty":
                        data.get("specialty",
                                 "unspecified"),
                    "urgency":
                        data.get("urgency", "routine"),
                },
            })

    if kind == "medication_fill":
        triggers.append({
            "type":    "medication_filled",
            "payload": {
                "patient_id": data.get("patient_id"),
                "fill_id":    data.get("fill_id",
                                        f"fill_{uuid.uuid4().hex}"),
                "drug":       data.get("drug"),
                "dose":       data.get("dose"),
            },
        })

    if kind == "lab_result":
        triggers.append({
            "type":    "lab_result_posted",
            "payload": {
                "patient_id": data.get("patient_id"),
                "result_id":
                    data.get("result_id",
                             f"res_{uuid.uuid4().hex}"),
            },
        })

    return triggers
```

Provenance is the primitive that distinguishes a coordination assistant from a chat surface over a single EHR. Every entry in the coordination state has a recorded source, timestamp, integrity hash, and ingestion path. When the assistant later asserts that the cardiologist increased the diuretic last Tuesday, the provenance chain answers the "how do you know?" question structurally rather than by conjecture.

---

## Step 3: Run the Seam-Detection Rule Engine and Protocol-Trigger Evaluator

Seam detection is the assistant's distinctive value layer. Each rule is institutional content with named clinical-leadership ownership, an effective date, and a version history. The engine runs the rules deterministically (or with calibrated heuristic models) and routes detected gaps to the appropriate human or to the patient-and-caregiver engagement scheduler. The protocol-trigger evaluator pulls protocol-defined workflow triggers (post-discharge welcome-home conversations within 48 hours; referral-tracking check-ins one week after order; etc.) and routes them appropriately.

```python
def evaluate_seams_and_triggers(*, patient_id, event):
    """
    Evaluate the seam-detection rule library and the
    protocol-trigger library against the patient's
    coordination state. Returns the seam findings, the
    protocol triggers, and the routing actions taken.
    """
    state_table = dynamodb.Table(COORDINATION_STATE_TABLE)
    state = state_table.get_item(
        Key={"patient_id": patient_id}).get("Item", {})
    if not state:
        return {"seam_findings": 0,
                "protocol_triggers": 0,
                "engagements_scheduled": 0,
                "alerts_created": 0,
                "escalations": 0}

    # Step 3A: run the seam-detection rule set.
    seam_findings = []

    # Rule: med discrepancy pharmacy vs clinician.
    med_discrepancy = _eval_med_discrepancy_rule(state, event)
    if med_discrepancy:
        seam_findings.append({
            "rule":     SEAM_RULES[
                "med_discrepancy_pharmacy_vs_clinician"],
            "finding":  med_discrepancy,
        })

    # Rule: referral not scheduled within window.
    referral_lag = _eval_referral_window_rule(state, event)
    if referral_lag:
        seam_findings.append({
            "rule":     SEAM_RULES[
                "referral_not_scheduled_within_window"],
            "finding":  referral_lag,
        })

    # Rule: post-discharge follow-up appointment missing.
    transition_gap = _eval_transition_gap_rule(state, event)
    if transition_gap:
        seam_findings.append({
            "rule":     SEAM_RULES[
                "transition_followup_appointment_missing"],
            "finding":  transition_gap,
        })

    # Step 3B: persist seam-flags and emit events.
    seam_table = dynamodb.Table(SEAM_FLAG_TABLE)
    for finding in seam_findings:
        seam_flag_id = f"seam_{uuid.uuid4().hex}"
        seam_record = {
            "seam_flag_id": seam_flag_id,
            "patient_id":   patient_id,
            "rule_id":      finding["rule"]["rule_id"],
            "rule_owner":   finding["rule"]["owner"],
            "rule_version": finding["rule"]["version"],
            "priority":     finding["rule"]["priority"],
            "suggested_resolver":
                finding["rule"]["suggested_resolver"],
            "description":
                finding["rule"]["description"],
            "finding":      finding["finding"],
            "raised_at":    _now_iso(),
            "status":       "open",
        }
        seam_table.put_item(Item=_to_decimal(seam_record))
        _emit_event("seam_flag_raised", {
            "patient_id":  patient_id,
            "seam_flag_id": seam_flag_id,
            "rule_id":     finding["rule"]["rule_id"],
            "priority":    finding["rule"]["priority"],
        })
        _put_metric("SeamFlagRaised", 1, {
            "Rule":     finding["rule"]["rule_id"],
            "Priority": finding["rule"]["priority"],
        })

    # Step 3C: evaluate protocol triggers.
    protocol_triggers = _evaluate_protocol_triggers(
        state=state, event=event)

    # Step 3D: schedule patient-and-caregiver engagements
    # for resolvable items.
    engagements_scheduled = 0
    for trigger in protocol_triggers:
        if trigger["action_type"] == \
                "engage_patient_or_caregiver":
            _schedule_engagement(
                patient_id=patient_id,
                trigger=trigger)
            engagements_scheduled += 1

    # Step 3E: route care-team-resolvable items to alerts.
    alerts_created = 0
    for finding in seam_findings:
        resolver = finding["rule"]["suggested_resolver"]
        if resolver in ("care_team", "clinician",
                        "patient_and_care_team"):
            mock_clinician_queue.deliver_alert({
                "alert_id":     f"alert_{uuid.uuid4().hex}",
                "patient_id":   patient_id,
                "rule_id":      finding["rule"]["rule_id"],
                "priority":     finding["rule"]["priority"],
                "description":  finding["rule"]["description"],
            })
            alerts_created += 1

    # Step 3F: handle high-acuity events.
    escalations = 0
    for finding in seam_findings:
        if finding["rule"]["priority"] == "high":
            _emit_event("escalation_routed", {
                "patient_id":  patient_id,
                "rule_id":     finding["rule"]["rule_id"],
            })
            escalations += 1

    return {
        "seam_findings":          len(seam_findings),
        "protocol_triggers":      len(protocol_triggers),
        "engagements_scheduled":  engagements_scheduled,
        "alerts_created":         alerts_created,
        "escalations":            escalations,
    }


def _eval_med_discrepancy_rule(state, event):
    """
    Detect medication discrepancies between pharmacy fills
    and clinician orders. Demo: thin check against the
    medication list.
    """
    if event.get("type") != "medication_filled":
        return None
    fill = event.get("payload", {})
    med_list = state.get("active_medication_list", [])
    # Look for a same-drug entry with a different dose. The
    # production rule has rxnorm-based drug matching and
    # ucum-based dose comparison; the demo runs a thin
    # check.
    for entry in med_list:
        data = entry.get("data", {})
        if (data.get("drug", "").lower() ==
                (fill.get("drug") or "").lower() and
                data.get("dose") and fill.get("dose") and
                data.get("dose") != fill.get("dose")):
            return {
                "drug":             fill.get("drug"),
                "fill_dose":        fill.get("dose"),
                "recorded_dose":    data.get("dose"),
                "recorded_provenance":
                    entry.get("provenance_id"),
            }
    return None


def _eval_referral_window_rule(state, event):
    """
    Detect referrals that have been ordered but have not
    been scheduled within the protocol window for their
    specialty and urgency tier.
    """
    referral_table = dynamodb.Table(REFERRAL_LIFECYCLE_TABLE)
    findings = []
    for record_list in referral_table.items.values():
        for ref in record_list:
            if ref.get("patient_id") != state.get(
                    "patient_id"):
                continue
            if ref.get("state") != "ordered":
                continue
            ordered_at = ref.get("state_changed_at", "")
            if not ordered_at:
                continue
            try:
                ordered_dt = datetime.fromisoformat(
                    ordered_at)
            except Exception:
                continue
            urgency = ref.get("urgency", "routine")
            window_key = (
                "specialty_referral_urgent_scheduling"
                if urgency == "urgent"
                else
                "specialty_referral_routine_scheduling")
            window_days = PROTOCOL_WINDOWS_DAYS.get(
                window_key, 14)
            if (_now() - ordered_dt) > timedelta(
                    days=window_days):
                findings.append({
                    "referral_id": ref.get("referral_id"),
                    "ordered_at":  ordered_at,
                    "urgency":     urgency,
                    "window_days": window_days,
                })
    return findings or None


def _eval_transition_gap_rule(state, event):
    """
    Detect post-discharge follow-up appointments missing
    from the schedule when the discharge plan called for
    one within a protocol window.
    """
    transition_table = dynamodb.Table(
        TRANSITION_OF_CARE_TABLE)
    findings = []
    for record_list in transition_table.items.values():
        for tr in record_list:
            if tr.get("patient_id") != state.get(
                    "patient_id"):
                continue
            if tr.get("status") != "in_progress":
                continue
            initiated_at = tr.get("initiated_at", "")
            if not initiated_at:
                continue
            try:
                initiated_dt = datetime.fromisoformat(
                    initiated_at)
            except Exception:
                continue
            window_days = (
                PROTOCOL_WINDOWS_DAYS[
                    "post_discharge_followup_routine"])
            if (_now() - initiated_dt) > timedelta(
                    days=window_days) and \
                    not tr.get("followup_scheduled"):
                findings.append({
                    "transition_id": tr.get("transition_id"),
                    "initiated_at":  initiated_at,
                    "window_days":   window_days,
                })
    return findings or None


def _evaluate_protocol_triggers(*, state, event):
    """
    Evaluate which protocol triggers fire for this event.
    Triggers come from the protocol library, not from LLM
    judgment.
    """
    triggers = []

    # Discharge-event trigger: post-discharge welcome-home
    # conversation within 48 hours.
    if event.get("type") == "discharge_event":
        triggers.append({
            "trigger_id":
                f"trig_{uuid.uuid4().hex}",
            "action_type": "engage_patient_or_caregiver",
            "protocol_id": "post_discharge_welcome_home",
            "window_hours": 48,
            "channel_preference": "in_app",
            "payload": event.get("payload", {}),
        })

    # Referral-ordered trigger: scheduling-status check-in
    # one week after order if not yet scheduled.
    if event.get("type") == "referral_ordered":
        triggers.append({
            "trigger_id":
                f"trig_{uuid.uuid4().hex}",
            "action_type": "engage_patient_or_caregiver",
            "protocol_id":
                "specialty_referral_scheduling_checkin",
            "window_days": 7,
            "channel_preference": "sms",
            "payload": event.get("payload", {}),
        })

    return triggers


def _schedule_engagement(*, patient_id, trigger):
    """
    Schedule a patient-or-caregiver engagement. Production
    routes to Pinpoint with channel-preference enforcement,
    quiet-hours discipline, and TCPA/10DLC compliance for
    SMS; the demo records the engagement.
    """
    # TODO (TechWriter): Code review Issue 2 (WARNING). In
    # real Pinpoint, the keys of MessageRequest.Addresses
    # are the actual delivery addresses (phone number for
    # SMS, email for EMAIL, device token for APNS/GCM,
    # endpoint ID for IN_APP), not opaque patient_ids. As
    # written this will not deliver in production. Either
    # switch to the EndpointIds shape (preferred for
    # healthcare bots that resolve patient -> endpoint via
    # the Pinpoint endpoint registry on enrollment), or
    # replace patient_id with a placeholder address and
    # add an explicit "in production, look up via Pinpoint
    # endpoint registry" comment.
    pinpoint_client.send_messages(
        ApplicationId=PINPOINT_APPLICATION_ID,
        MessageRequest={
            "Addresses": {patient_id: {
                "ChannelType":
                    trigger.get("channel_preference",
                                "in_app").upper()}},
            "MessageConfiguration": {
                "DefaultMessage": {
                    "Body": (
                        f"Coordination check-in from "
                        f"{INSTITUTION_DISPLAY_NAME}: "
                        f"protocol "
                        f"{trigger['protocol_id']}")},
            },
        })

    _emit_event("engagement_scheduled", {
        "patient_id":  patient_id,
        "trigger_id":  trigger["trigger_id"],
        "protocol_id": trigger["protocol_id"],
    })
```

The seam-detection layer is where most of the engineering value of a coordination assistant lives. The LLM is the interface; the deterministic rules and heuristic models are the substance. Investment in seam-detection-rule development with named clinical-leadership ownership per rule is multi-quarter work and continues alongside the engineering work.

---

## Step 4: Receive the Conversation Turn with Input Safety, Identity, and Coordination-Context Loading

A conversation can be patient-initiated, caregiver-initiated, or assistant-initiated. Whichever the entry point, the conversation handler runs the same input-safety pipeline as the previous chapter 11 bots, plus identity verification with the speaker-role distinction (patient vs. caregiver), plus the coordination-state context loading scoped by the speaker's proxy-access posture.

```python
def receive_conversation_turn(*,
                                channel,
                                channel_session_id,
                                user_message,
                                auth_context):
    """
    Entry point for patient-initiated, caregiver-initiated,
    or patient-responding conversation. Runs input safety,
    identity verification with speaker-role distinction,
    and coordination-context loading.
    """
    # Step 4A: identify or create the conversation session.
    state_table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    session = _get_or_create_session(
        state_table, channel, channel_session_id,
        auth_context)
    session_id = session["session_id"]
    patient_id = session["verified_patient_id"]
    speaker_role = session["speaker_role"]

    # Step 4B: persist the user's message.
    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    metadata_table.put_item(Item=_to_decimal({
        "session_id":   session_id,
        "kind":         "turn",
        "speaker":      speaker_role,
        "text":         user_message,
        "timestamp":    _now_iso(),
    }))

    # Step 4C: input safety screening with prompt-injection
    # detection (including coordination-specific patterns),
    # PHI minimization, length checks. Production layers a
    # tuned classifier and a Bedrock Guardrail call on top.
    screening = _screen_input(session_id, user_message)
    if screening["action"] == "block":
        return _handle_block(session_id, screening)

    # Step 4D: continuous coordination-acuity screening.
    # Detects acute-emergency presentations and high-acuity
    # coordination events that need immediate routing.
    acuity = _coordination_acuity_screen(user_message)
    if acuity["routing_required"]:
        return _route_to_acuity_pathway(
            session_id, acuity)

    # Step 4E: load coordination context scoped to the
    # speaker's proxy-access posture.
    coordination_context = _load_coordination_context(
        patient_id=patient_id,
        speaker_role=speaker_role,
        proxy_scope=session.get("proxy_scope"))

    return {
        "action":               "ready_for_response",
        "session_id":           session_id,
        "patient_id":           patient_id,
        "speaker_role":         speaker_role,
        "coordination_context": coordination_context,
    }


def _get_or_create_session(state_table, channel,
                              channel_session_id,
                              auth_context):
    """Resolve or create a conversation session."""
    session_key = f"{channel}#{channel_session_id}"
    existing = state_table.get_item(
        Key={"session_id": session_key})
    if existing.get("Item"):
        return existing["Item"]
    new_session = {
        "session_id":            session_key,
        "channel":               channel,
        "channel_session_id":    channel_session_id,
        "verified_patient_id":   auth_context["patient_id"],
        "speaker_role":
            auth_context.get("speaker_role", "patient"),
        "proxy_scope":
            auth_context.get("proxy_scope"),
        "created_at":            _now_iso(),
        "model_id":              ORCHESTRATION_MODEL_ID,
        "prompt_version":        PROMPT_VERSION,
        "agent_version":         AGENT_VERSION,
        "turn_count":            0,
    }
    state_table.put_item(Item=_to_decimal(new_session))
    return new_session


def _screen_input(session_id, user_message):
    """Input safety screening."""
    msg_lower = user_message.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, msg_lower):
            return {"action": "block",
                    "reason": "prompt_injection_pattern"}
    if len(user_message) > 4000:
        return {"action": "block",
                "reason": "message_too_long"}
    return {"action": "pass"}


def _coordination_acuity_screen(user_message):
    """
    Detect acute-emergency presentations and high-acuity
    coordination events.
    """
    msg_lower = user_message.lower()

    emergency_patterns = [
        ("chest pain", "triage_pathway"),
        ("can't breathe", "triage_pathway"),
        ("severe shortness of breath", "triage_pathway"),
        ("suicidal", "mental_health_pathway"),
        ("want to die", "mental_health_pathway"),
        ("stroke", "triage_pathway"),
        ("severe bleeding", "triage_pathway"),
    ]
    for keyword, route in emergency_patterns:
        if keyword in msg_lower:
            return {"routing_required": True,
                    "route":            route,
                    "matched":          keyword}

    return {"routing_required": False}


def _route_to_acuity_pathway(session_id, acuity):
    """Route to the appropriate adjacent recipe pathway."""
    response = (
        OUT_OF_SCOPE_TRIAGE
        if acuity["route"] == "triage_pathway"
        else (
            "What you're describing sounds like something "
            "to talk through with a behavioral-health "
            "support tool. I'm bringing that pathway up "
            "now. If this feels like an emergency, please "
            "call 988 or 911."))
    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    metadata_table.put_item(Item=_to_decimal({
        "session_id":  session_id,
        "kind":        "turn",
        "speaker":     "bot",
        "text":        response,
        "purpose":     "acuity_routing",
        "timestamp":   _now_iso(),
    }))
    _emit_event("acuity_routing_triggered", {
        "session_id": session_id,
        "route":      acuity["route"],
    })
    return {
        "action":      "acuity_routed",
        "session_id":  session_id,
        "response":    response,
        "route":       acuity["route"],
        "disposition": "acuity_routed",
        "citations":   [],
    }


def _load_coordination_context(*, patient_id, speaker_role,
                                  proxy_scope):
    """
    Load coordination context scoped to the speaker's
    proxy-access posture. A caregiver speaking on behalf
    of the patient may have restricted access to certain
    categories per the patient's preference or state law.
    """
    patient_table = dynamodb.Table(
        PATIENT_COORDINATION_TABLE)
    patient_record = patient_table.get_item(
        Key={"patient_id": patient_id}).get("Item", {})

    state_table = dynamodb.Table(COORDINATION_STATE_TABLE)
    state = state_table.get_item(
        Key={"patient_id": patient_id}).get("Item", {})

    consent_table = dynamodb.Table(CONSENT_RECORD_TABLE)
    consent = consent_table.get_item(
        Key={"patient_id": patient_id}).get("Item", {})

    # Scope filter: caregivers with limited access do not
    # see categories outside their proxy scope.
    if speaker_role == "caregiver" and proxy_scope:
        scope_level = proxy_scope.get("access_level", "")
        if scope_level == "scheduling_only":
            state = {
                "patient_id":            patient_id,
                "active_medication_list": [],
                "open_referrals":         state.get(
                    "open_referrals", []),
                "upcoming_encounters":
                    state.get("upcoming_encounters", []),
            }
        carve_outs = proxy_scope.get(
            "sensitive_record_carve_outs", [])
        # In production: filter the medication list,
        # encounter list, and care-event list against the
        # carve-outs. The demo records the carve-outs but
        # passes through.
    else:
        carve_outs = []

    return {
        "patient_id":     patient_id,
        "patient_record": patient_record,
        "state":          state,
        "consent":        consent,
        "speaker_role":   speaker_role,
        "proxy_scope":    proxy_scope,
        "carve_outs":     carve_outs,
    }


def _handle_block(session_id, screening):
    return {
        "action":      "blocked",
        "session_id":  session_id,
        "response":    (
            "Let's keep this focused on your coordination "
            "questions. What can I help you with right now?"),
        "disposition": "blocked",
        "reason":      screening.get("reason", "unknown"),
        "citations":   [],
    }
```

The receive-conversation-turn step does five things in order. The session bootstrap captures the speaker role (patient or caregiver) and any proxy-access scope. The user-message persistence lands the turn in the conversation log. The input-safety screening runs the standard prompt-injection patterns plus coordination-specific ones (manipulate seam-flag routing, manipulate proxy-scope, manipulate scope discipline). The coordination-acuity screen catches acute presentations and routes them to the triage or mental-health pathway. The coordination-context load brings in the patient record, the coordination state, the consent posture, and the speaker-role-scoped view.

---

## Step 5: Run the Agent's Tool-Use Loop with Citation Discipline

The LLM operates as a Bedrock Agent with the coordination tool surface. The system prompt explicitly scopes the assistant to coordination work, defers clinical-judgment questions to the care team, and grounds coordination-state assertions in cited provenance. Each tool call is recorded in the tool-call ledger; each retrieved citation is preserved in the response trace.

```python
def handle_conversation(*,
                          session_id,
                          patient_id,
                          speaker_role,
                          user_message,
                          coordination_context):
    """
    Compose the response. Production wires this through
    bedrock_agent_runtime.invoke_agent with the
    coordination tools defined as action groups; the demo
    uses the mock that demonstrates the structure.
    """
    # Step 5A: assemble the system prompt.
    system_prompt = compose_coordination_system_prompt(
        bot_persona_name=INSTITUTION_DISPLAY_NAME,
        patient_record=coordination_context["patient_record"],
        speaker_role=speaker_role,
        carve_outs=coordination_context["carve_outs"],
        regulatory_position=
            INSTITUTION_REGULATORY_POSITION)

    # Step 5B: invoke the orchestration model. Production:
    #
    #   response = bedrock_agent_runtime.invoke_agent(
    #       agentId=COORD_AGENT_ID,
    #       agentAliasId=COORD_AGENT_ALIAS_ID,
    #       sessionId=session_id,
    #       inputText=user_message,
    #       sessionState={...})
    #
    # The agent handles tool-call orchestration: when the
    # LLM emits a coordination_state_retrieve call, the
    # action group's Lambda fetches from the coordination-
    # state-store and returns the data; when the LLM emits
    # a referral_lifecycle_retrieve call, the action
    # group's Lambda fetches from the referral-lifecycle-
    # store; etc. The demo uses the mock that returns
    # canned structured responses.
    agent_response = mock_bedrock.invoke_response(
        user_message=user_message,
        coordination_context=coordination_context,
        system_prompt=system_prompt)

    # Step 5C: validate each tool call against scope and
    # patient_id-cross-check.
    validated_calls = []
    for tool_call in agent_response.get("tool_calls", []):
        # Defense-in-depth: every tool that takes a
        # patient_id validates it against the verified
        # session.
        if tool_call.get("args", {}).get("patient_id"):
            if tool_call["args"]["patient_id"] != patient_id:
                logger.error(
                    "patient_id mismatch in tool call: %s",
                    tool_call)
                continue

        # Demo: simulate tool execution and audit.
        result = _execute_coordination_tool(
            tool_call, coordination_context)

        _audit_tool_call(
            session_id=session_id,
            tool=tool_call["tool"],
            arguments=tool_call.get("args", {}),
            result_summary={"executed": True},
            latency_ms=22,
            outcome="success")

        validated_calls.append({
            "tool_call": tool_call,
            "result":    result,
        })

    # Step 5D: capture citations.
    citations = agent_response.get("citations", [])

    return {
        "session_id":     session_id,
        "patient_id":     patient_id,
        "speaker_role":   speaker_role,
        "response_text":  agent_response["response_text"],
        "citations":      citations,
        "tool_calls":     [tc["tool_call"]
                           for tc in validated_calls],
        "tool_results":   validated_calls,
        "coordination_context": coordination_context,
    }


def compose_coordination_system_prompt(*,
                                          bot_persona_name,
                                          patient_record,
                                          speaker_role,
                                          carve_outs,
                                          regulatory_position):
    """
    Build the system prompt. Production has the prompt
    version-controlled, with sandbox testing against
    held-out coordination cases on each material change.
    """
    prefs = patient_record.get("preferences", {})
    preferred_name = prefs.get("preferred_name", "")
    language = prefs.get("language", "en-US")

    role_line = (
        f"You are speaking with the patient ({preferred_name}). "
        if speaker_role == "patient"
        else
        f"You are speaking with the patient's caregiver. "
        f"Apply the proxy-access scope.")

    carve_outs_line = (
        f"The caregiver's access excludes: "
        f"{', '.join(carve_outs)}. "
        f"Do not surface these categories.\n"
        if speaker_role == "caregiver" and carve_outs else "")

    return (
        f"You are {bot_persona_name}'s care-coordination "
        f"chat tool. You are NOT a doctor, NOT a nurse, "
        f"NOT a clinician. You are a chat tool the "
        f"institution deployed to help coordinate care "
        f"across the patient's clinicians, pharmacies, and "
        f"organizations.\n\n"

        f"{role_line}\nRespond in {language}.\n\n"

        f"{carve_outs_line}"

        f"SCOPE (within): coordination questions, next-step "
        f"guidance, referral status, transition-of-care "
        f"orchestration, medication-reconciliation "
        f"surfacing, caregiver support, seam-flag "
        f"resolution.\n\n"

        f"SCOPE (outside, route appropriately): clinical "
        f"questions requiring care-team judgment, triage "
        f"of new acute symptoms (recipe 11.6), mental-"
        f"health crisis (recipe 11.8), benefits questions "
        f"(recipe 11.5), refills (recipe 11.3), complex "
        f"scheduling (recipe 11.2), chronic-disease "
        f"coaching (recipe 11.7), diagnosis-attempted, "
        f"prescription-attempted, dose-titration-"
        f"attempted, treatment-recommendation-beyond-"
        f"existing-orders.\n\n"

        f"CITATION: every coordination-state assertion "
        f"must cite a provenance ID. Every protocol "
        f"instruction must cite a protocol ID and version. "
        f"Every patient-education delivery must cite a "
        f"library entry. If a fact is not in the "
        f"coordination state or in cited protocol, say so "
        f"honestly.\n\n"

        f"DEFERENCE: where the response could plausibly "
        f"involve clinical judgment beyond coordination "
        f"scope, defer to the care team. Do not produce "
        f"diagnostic or prescriptive recommendations "
        f"beyond what the patient's existing clinicians "
        f"have ordered.\n\n"

        f"TONE: warm but boundaried, like a competent "
        f"care coordinator, not affectionate like a "
        f"friend. Honest about what you are and are not.\n\n"

        f"REGULATORY: {regulatory_position}.")


def _execute_coordination_tool(tool_call,
                                  coordination_context):
    """
    Execute a coordination tool call against the
    underlying stores. Demo: returns thin canned results
    for the few tools the mock invokes.
    """
    tool = tool_call["tool"]
    args = tool_call.get("args", {})
    patient_id = (args.get("patient_id") or
                  coordination_context.get("patient_id"))

    if tool == "coordination_state_retrieve":
        state_table = dynamodb.Table(
            COORDINATION_STATE_TABLE)
        return state_table.get_item(
            Key={"patient_id": patient_id}).get(
                "Item", {})

    if tool == "referral_lifecycle_retrieve":
        referral_table = dynamodb.Table(
            REFERRAL_LIFECYCLE_TABLE)
        results = []
        for record_list in referral_table.items.values():
            for ref in record_list:
                if ref.get("patient_id") == patient_id:
                    results.append(ref)
        return {"referrals": results}

    if tool == "medication_list_reconcile":
        state_table = dynamodb.Table(
            COORDINATION_STATE_TABLE)
        state = state_table.get_item(
            Key={"patient_id": patient_id}).get(
                "Item", {})
        return {"medication_list":
                state.get("active_medication_list", [])}

    if tool == "protocol_retrieve":
        return mock_protocols.retrieve(
            args.get("protocol_type"))

    if tool == "care_team_alert_propose":
        # Just records the proposal; the actual alert
        # happens in Step 6 persistence with consent gating.
        return {"proposed": True,
                "alert_type": args.get("alert_type")}

    if tool == "patient_action_propose":
        return {"proposed": True,
                "action_type": args.get("action_type")}

    return {"executed": False, "reason": "unknown_tool"}
```

The system prompt does most of the relationship-quality and scope-discipline work. Three things specifically: the explicit out-of-scope list with named recipe pathways for each adjacent topic (so the LLM defers cleanly when a patient asks about a benefits question rather than guessing), the citation requirement (which prevents the LLM from freestyling coordination assertions from its parametric memory), and the deference clause (which catches the cases that look like coordination but cross into clinical judgment).

---

## Step 6: Run Output Safety with Protocol-Faithfulness Verification

Every response runs through output safety before delivery. Standard scope, guardrail, and persona checks come from the previous chapter 11 recipes. The coordination-specific addition is a faithfulness verifier that confirms every coordination-state assertion cites preserved provenance and every protocol instruction cites preserved protocol content.

```python
def screen_coordination_output(*,
                                  session_id,
                                  patient_id,
                                  speaker_role,
                                  response_text,
                                  citations,
                                  tool_calls,
                                  tool_results,
                                  coordination_context):
    """
    Output screening for the coordination assistant.
    Returns the final response payload or a safer template.
    Production runs an independent verifier model with
    structured-output schema validation; the demo runs
    rule-based checks.
    """
    # Step 6A: scope checks specific to coordination work.
    scope_violation = _detect_coordination_scope_violation(
        response_text)

    if scope_violation:
        replacement = {
            "diagnosis_attempted":
                OUT_OF_SCOPE_DIAGNOSIS_ATTEMPTED,
            "dose_titration_attempted":
                OUT_OF_SCOPE_DOSE_TITRATION,
            "triage_attempted":
                OUT_OF_SCOPE_TRIAGE,
        }.get(scope_violation["category"],
              UNGROUNDED_RESPONSE_FALLBACK)

        _put_metric("ScopeViolationDetected", 1, {
            "Category": scope_violation["category"]})

        return {
            "response":     replacement,
            "disposition":  "scope_replaced",
            "violation":    scope_violation["category"],
            "citations":    [],
            "tool_calls":   [],
        }

    # Step 6B: faithfulness verification.
    # Coordination-state assertions must be grounded in the
    # tool_results; protocol instructions must cite a
    # protocol with a version stamp; the citation chain
    # back to provenance must be intact.
    faithfulness = _verify_coordination_faithfulness(
        response_text=response_text,
        tool_results=tool_results,
        citations=citations)

    if not faithfulness["passes"]:
        _put_metric("FaithfulnessFailure", 1, {
            "Reason": faithfulness.get("reason", "unknown")})
        return {
            "response":    UNGROUNDED_RESPONSE_FALLBACK,
            "disposition": "ungrounded_replaced",
            "citations":   [],
            "tool_calls":  [],
        }

    # Step 6C: speaker-role-appropriate disclosure check.
    role_check = _speaker_role_disclosure_check(
        response_text=response_text,
        speaker_role=speaker_role,
        carve_outs=coordination_context["carve_outs"])
    if role_check["violation"]:
        _put_metric("RoleScopeViolation", 1, {
            "Reason": role_check.get("reason", "unknown")})
        return {
            "response":    UNGROUNDED_RESPONSE_FALLBACK,
            "disposition": "role_scope_replaced",
            "citations":   [],
            "tool_calls":  [],
        }

    # Step 6D: conservative-bias check. Where the response
    # could plausibly involve clinical judgment beyond the
    # coordination scope, did the response defer to the
    # care team?
    if _suggests_clinical_judgment(response_text) and \
            not _contains_deference(response_text):
        _put_metric("ConservativeBiasViolation", 1, {})
        return {
            "response":    UNGROUNDED_RESPONSE_FALLBACK,
            "disposition": "deference_replaced",
            "citations":   [],
            "tool_calls":  [],
        }

    return {
        "response":     response_text,
        "disposition":  "delivered",
        "citations":    citations,
        "tool_calls":   tool_calls,
    }


def _detect_coordination_scope_violation(response_text):
    """
    Detect attempts at diagnosis, dose-titration,
    treatment recommendations beyond existing orders, or
    triage. Heuristic-based for the demo; production layers
    a classifier on top.
    """
    text_lower = response_text.lower()

    diagnosis_patterns = [
        "you have ", "i think you have", "you probably have",
        "this is likely", "you are diagnosed with",
    ]
    for pattern in diagnosis_patterns:
        if pattern in text_lower:
            return {"category": "diagnosis_attempted",
                    "matched":  pattern}

    dose_patterns = [
        "increase your dose", "decrease your dose",
        "go up to", "go down to", "take more",
        "take less", "switch to ",
    ]
    for pattern in dose_patterns:
        if pattern in text_lower:
            return {"category":
                        "dose_titration_attempted",
                    "matched":  pattern}

    triage_patterns = [
        "this is an emergency, do",
        "you should go to the er right now",
        "you are having a heart attack",
    ]
    for pattern in triage_patterns:
        if pattern in text_lower:
            return {"category": "triage_attempted",
                    "matched":  pattern}

    return None


def _verify_coordination_faithfulness(*, response_text,
                                          tool_results,
                                          citations):
    """
    Verify that coordination-state assertions cite tool
    results and that protocol instructions cite protocol
    versions. Production runs an independent verifier
    model; the demo runs structural checks.
    """
    text_lower = response_text.lower()

    # Phrases indicating a coordination-state assertion that
    # should trace to provenance.
    state_assertion_indicators = [
        "discharge list",
        "your medication",
        "your referral",
        "your appointment",
        "your prescription",
        "the cardiology",
        "your follow-up",
        "ordered ",
        "scheduled ",
    ]
    contains_state_assertion = any(
        ind in text_lower
        for ind in state_assertion_indicators)

    if contains_state_assertion:
        # Need at least one citation of kind
        # coordination_state, referral, or encounter.
        has_state_citation = any(
            c.get("kind") in (
                "coordination_state", "referral",
                "encounter", "medication_list")
            for c in citations)
        if not has_state_citation:
            return {
                "passes": False,
                "reason":
                    "state_assertion_without_provenance",
            }

        # Each state citation must include a provenance_id.
        for c in citations:
            if c.get("kind") in (
                    "coordination_state", "referral",
                    "encounter", "medication_list"):
                if not c.get("provenance_id"):
                    return {
                        "passes": False,
                        "reason":
                            "state_citation_missing_"
                            "provenance",
                    }

    # Protocol instructions must cite a versioned protocol.
    protocol_indicators = [
        "the protocol",
        "the discharge plan calls for",
        "within the window",
        "within seven days",
        "within forty-eight hours",
    ]
    contains_protocol_instruction = any(
        ind in text_lower
        for ind in protocol_indicators)

    if contains_protocol_instruction:
        protocol_citations = [
            c for c in citations
            if c.get("kind") == "protocol"]
        if not protocol_citations:
            return {
                "passes": False,
                "reason": "protocol_instruction_uncited",
            }
        for c in protocol_citations:
            if not c.get("version"):
                return {
                    "passes": False,
                    "reason":
                        "protocol_citation_missing_version",
                }

    return {"passes": True}


def _speaker_role_disclosure_check(*, response_text,
                                       speaker_role,
                                       carve_outs):
    """
    Check that the response honors the speaker-role carve-
    outs. Demo: rejects if any carve-out keyword appears
    in the response text addressed to a caregiver. The
    production check is more nuanced.
    """
    if speaker_role != "caregiver" or not carve_outs:
        return {"violation": False}
    text_lower = response_text.lower()
    for carve_out in carve_outs:
        if carve_out.lower() in text_lower:
            return {"violation": True,
                    "reason":
                        f"carve_out_disclosed_{carve_out}"}
    return {"violation": False}


def _suggests_clinical_judgment(response_text):
    """
    Quick heuristic for whether a response is making a
    clinical-judgment claim. Production runs a classifier;
    the demo runs simple keyword matching.
    """
    text_lower = response_text.lower()
    indicators = [
        "you should",
        "i recommend",
        "it would be best",
        "the right thing is to",
    ]
    return any(ind in text_lower for ind in indicators)


def _contains_deference(response_text):
    """Check whether the response defers to the care team."""
    text_lower = response_text.lower()
    deference_indicators = [
        "your care team",
        "your clinician",
        "your doctor",
        "your nurse",
        "your prescriber",
        "i'll flag this",
        "let me check",
        "i'm not making the",
    ]
    return any(ind in text_lower
               for ind in deference_indicators)


def persist_coordination_artifacts(*,
                                       session_id,
                                       patient_id,
                                       speaker_role,
                                       response_payload,
                                       coordination_context):
    """
    Persist the bot turn, the coordination-decision
    record(s), and process tool-call side effects.
    """
    # Step 6E: append the bot turn to the conversation log.
    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    metadata_table.put_item(Item=_to_decimal({
        "session_id":         session_id,
        "kind":               "turn",
        "speaker":            "bot",
        "text":               response_payload["response"],
        "citations":
            response_payload.get("citations", []),
        "tool_calls_summary":
            [{"tool": tc["tool"]}
             for tc in response_payload.get(
                 "tool_calls", [])],
        "disposition":
            response_payload.get("disposition"),
        "timestamp":          _now_iso(),
    }))

    state_table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    session = state_table.get_item(
        Key={"session_id": session_id}).get("Item", {})
    session["turn_count"] = int(
        session.get("turn_count", 0)) + 1
    state_table.put_item(Item=_to_decimal(session))

    # Step 6F: persist a coordination-decision record per
    # actionable decision in the response.
    decision_ids = []
    decision_table = dynamodb.Table(DECISION_RECORD_TABLE)
    for decision in _extract_coordination_decisions(
            response_payload):
        decision_id = f"dec_{uuid.uuid4().hex}"
        record = {
            "decision_id":            decision_id,
            "session_id":             session_id,
            "patient_id":             patient_id,
            "speaker_role":           speaker_role,
            "decision_type":          decision["type"],
            "decision_payload":       decision["payload"],
            "citations":              decision.get(
                "citations", []),
            "active_protocol_corpus_version":
                PROTOCOL_CORPUS_VERSION,
            "active_seam_rule_library_version":
                SEAM_RULE_LIBRARY_VERSION,
            "active_model_id":        ORCHESTRATION_MODEL_ID,
            "active_prompt_version":  PROMPT_VERSION,
            "active_agent_version":   AGENT_VERSION,
            "active_consent_id":
                coordination_context["consent"].get(
                    "consent_id"),
            "timestamp":              _now_iso(),
        }
        decision_table.put_item(Item=_to_decimal(record))

        # Mirror to S3 with Object Lock for the decision-
        # record archive. Retention sized to the longest
        # of HIPAA's six-year minimum, state-specific
        # medical-record retention, and any FDA SaMD post-
        # market obligations.
        s3_key = (
            f"decisions/{patient_id}/"
            f"{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/"
            f"{decision_id}.json")
        s3_client.put_object(
            Bucket=DECISION_RECORD_BUCKET,
            Key=s3_key,
            Body=json.dumps(_from_decimal(record)),
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=DECISION_RECORD_KMS_KEY_ID)

        _emit_event("coordination_decision_recorded", {
            "decision_id":   decision_id,
            "decision_type": decision["type"],
            "patient_id":    patient_id,
        })

        decision_ids.append(decision_id)

    # Step 6G: process tool-call side effects (care-team
    # alerts gated by consent, follow-up scheduling).
    for tool_call in response_payload.get("tool_calls", []):
        _process_tool_side_effects(
            session_id=session_id,
            patient_id=patient_id,
            tool_call=tool_call,
            coordination_context=coordination_context)

    return {"decisions_recorded": decision_ids}


def _extract_coordination_decisions(response_payload):
    """Extract decisions worth journaling from the response."""
    decisions = []
    response_text = response_payload.get("response", "")
    citations = response_payload.get("citations", [])

    if citations:
        decisions.append({
            "type":   "coordination_response_delivered",
            "payload": {
                "response_summary": response_text[:200],
            },
            "citations": citations,
        })

    for tool_call in response_payload.get("tool_calls", []):
        if tool_call["tool"] == "care_team_alert_propose":
            decisions.append({
                "type": "care_team_alert_proposed",
                "payload": tool_call.get("args", {}),
                "citations": citations,
            })
        elif tool_call["tool"] == "patient_action_propose":
            decisions.append({
                "type": "patient_action_proposed",
                "payload": tool_call.get("args", {}),
                "citations": citations,
            })
        elif tool_call["tool"] == "follow_up_schedule":
            decisions.append({
                "type": "follow_up_scheduled",
                "payload": tool_call.get("args", {}),
                "citations": citations,
            })
        elif tool_call["tool"] == "escalation_propose":
            decisions.append({
                "type": "escalation_proposed",
                "payload": tool_call.get("args", {}),
                "citations": citations,
            })

    return decisions


def _process_tool_side_effects(*, session_id, patient_id,
                                  tool_call,
                                  coordination_context):
    """Process tool calls that have downstream side effects."""
    tool = tool_call["tool"]
    args = tool_call.get("args", {})

    if tool == "care_team_alert_propose":
        if _consent_permits_care_team_sharing(
                coordination_context["consent"]):
            mock_clinician_queue.deliver_alert({
                "alert_id":   f"alert_{uuid.uuid4().hex}",
                "alert_type": args.get("alert_type"),
                "patient_id": patient_id,
                "session_id": session_id,
            })
            _emit_event("care_team_alert_delivered", {
                "patient_id": patient_id,
                "alert_type": args.get("alert_type"),
            })


def _consent_permits_care_team_sharing(consent_record):
    """
    Check whether the patient has consented to care-team
    sharing. Consent is checked at every alert-delivery
    time, not just at enrollment, because consent is
    revocable.
    """
    sharing = consent_record.get(
        "sharing_relationships", [])
    return ("with_care_management" in sharing or
            "with_primary_care" in sharing)
```

Output safety has four checks: scope violations get domain-specific safe replacements; faithfulness failures (an assertion without provenance, an instruction without a versioned protocol citation) get the ungrounded fallback; role-scope violations (a caregiver getting access to a carve-out category) get rejected; and conservative-bias violations (a clinical-judgment claim without deference) get rejected. Each replacement is structured so the patient or caregiver gets a useful next step rather than a dead end.

---

## Step 7: Orchestrate Transitions of Care with Step Functions

When a discharge event arrives, the assistant initiates the appropriate transition-of-care workflow. The workflow is a Step Functions state machine, version-controlled, signed off by clinical leadership, with deterministic state transitions and explicit completion criteria. The LLM operates on top of the state machine as the conversational interface; the state machine drives the protocol.

```python
def initiate_transition_of_care(*, patient_id,
                                    discharge_event):
    """
    Initiate the transition-of-care workflow for a
    discharge event. Selects the protocol by destination
    setting and admission type, instantiates the workflow,
    and persists the transition record.
    """
    # Step 7A: select the appropriate transition protocol.
    transition_protocol = _select_transition_protocol(
        patient_id=patient_id,
        admission_type=discharge_event.get(
            "admission_type", "unspecified"),
        destination=discharge_event.get(
            "destination", "home"))

    # Step 7B: persist the transition record.
    transition_id = f"trans_{uuid.uuid4().hex}"
    transition_record = {
        "transition_id":         transition_id,
        "patient_id":            patient_id,
        "admission_type":
            discharge_event.get("admission_type"),
        "destination":
            discharge_event.get("destination"),
        "transition_protocol_id":
            transition_protocol["id"],
        "transition_protocol_version":
            transition_protocol["version"],
        "initiated_at":          _now_iso(),
        "status":                "in_progress",
        "completion_window_days":
            transition_protocol.get("window_days", 30),
        "items_pending":
            list(transition_protocol.get("items", [])),
        "items_completed":       [],
        "followup_scheduled":    False,
        "med_recon_completed":   False,
        "education_delivered":   False,
        "red_flags_delivered":   False,
    }

    transition_table = dynamodb.Table(
        TRANSITION_OF_CARE_TABLE)
    transition_table.put_item(
        Item=_to_decimal(transition_record))

    # Step 7C: instantiate the Step Functions workflow.
    state_machine_arn = _select_state_machine_arn(
        destination=discharge_event.get(
            "destination", "home"))

    sfn_client.start_execution(
        stateMachineArn=state_machine_arn,
        input=json.dumps({
            "patient_id":         patient_id,
            "transition_id":      transition_id,
            "transition_protocol_id":
                transition_protocol["id"],
            "discharge_event":    discharge_event,
        }))

    _emit_event("transition_initiated", {
        "patient_id":     patient_id,
        "transition_id":  transition_id,
        "destination":
            discharge_event.get("destination"),
    })

    _put_metric("TransitionInitiated", 1, {
        "Destination":
            discharge_event.get("destination", "home"),
    })

    return {
        "transition_id":     transition_id,
        "transition_protocol_id":
            transition_protocol["id"],
        "completion_window_days":
            transition_protocol.get("window_days", 30),
    }


def _select_transition_protocol(*, patient_id,
                                    admission_type,
                                    destination):
    """
    Select the appropriate transition protocol from the
    coordination-protocol corpus. Production uses the
    Bedrock Knowledge Base with metadata filters; the demo
    returns a thin selection.
    """
    base = mock_protocols.retrieve(
        "post_discharge_welcome_home") or {}
    return {
        "id":      "post_discharge_welcome_home",
        "version": base.get("version", "v1.0"),
        "items":   base.get("items", []),
        "window_days": 30,
    }


def _select_state_machine_arn(*, destination):
    """Pick the Step Functions state machine for the destination."""
    return {
        "home":    DISCHARGE_STATE_MACHINE_ARN,
        "snf":     SNF_STATE_MACHINE_ARN,
        "ed":      ED_FOLLOWUP_STATE_MACHINE_ARN,
    }.get(destination, DISCHARGE_STATE_MACHINE_ARN)
```

---

## Step 8: Track Referral Lifecycles to Closure

Referrals are first-class coordination objects with a structured lifecycle. The state machine is institutional content; the LLM operates on top of it.

```python
def process_referral_event(*, patient_id, referral_event):
    """
    Process a referral lifecycle event. Validates the
    transition, persists the new state, emits the change
    event, and schedules the next protocol-driven action.
    """
    referral_id = referral_event["referral_id"]
    event_type  = referral_event["event_type"]

    # Step 8A: load the current referral state.
    referral_table = dynamodb.Table(
        REFERRAL_LIFECYCLE_TABLE)
    referral = referral_table.get_item(
        Key={"referral_id": referral_id}).get("Item")

    # Step 8B: if the referral does not exist yet, create it
    # in the ordered state. This typically happens on the
    # FHIR ServiceRequest ingestion path.
    if not referral:
        if event_type != "ordered":
            return {"action": "rejected",
                    "reason": "referral_not_found"}
        referral = {
            "referral_id":        referral_id,
            "patient_id":         patient_id,
            "specialty":
                referral_event.get("specialty",
                                    "unspecified"),
            "urgency":
                referral_event.get("urgency", "routine"),
            "state":              "ordered",
            "state_changed_at":   _now_iso(),
            "history":            [{
                "state":      "ordered",
                "changed_at": _now_iso(),
            }],
        }
        referral_table.put_item(
            Item=_to_decimal(referral))
        _emit_event("referral_ordered", {
            "patient_id":  patient_id,
            "referral_id": referral_id,
        })
        return {"action": "created",
                "referral_state": "ordered"}

    # Step 8C: validate the transition.
    current_state = referral["state"]
    target_state  = _map_event_to_target_state(event_type)
    if not target_state:
        return {"action": "rejected",
                "reason": "unknown_event_type"}
    allowed = REFERRAL_TRANSITIONS.get(
        current_state, set())
    if target_state not in allowed:
        return {"action": "rejected",
                "reason":
                    f"invalid_transition_"
                    f"{current_state}_to_{target_state}"}

    # Step 8D: persist the new state with the transition
    # history preserved.
    referral["state"] = target_state
    referral["state_changed_at"] = _now_iso()
    history = referral.get("history", [])
    history.append({
        "state":      target_state,
        "changed_at": _now_iso(),
    })
    referral["history"] = history
    referral_table.put_item(Item=_to_decimal(referral))

    # Step 8E: emit downstream events.
    _emit_event("referral_state_changed", {
        "patient_id":     patient_id,
        "referral_id":    referral_id,
        "previous_state": current_state,
        "new_state":      target_state,
    })

    # Step 8F: derive the next protocol-driven action.
    next_action = _next_referral_action(referral, event_type)
    if next_action["type"] == "engage_patient":
        _schedule_engagement(
            patient_id=patient_id,
            trigger={
                "trigger_id":
                    f"trig_{uuid.uuid4().hex}",
                "action_type":
                    "engage_patient_or_caregiver",
                "protocol_id":
                    "specialty_referral_scheduling_checkin",
                "channel_preference": "sms",
                "payload": {
                    "referral_id": referral_id,
                },
            })
    elif next_action["type"] == "alert_care_team":
        mock_clinician_queue.deliver_alert({
            "alert_id":      f"alert_{uuid.uuid4().hex}",
            "alert_type":
                "referral_aged_past_protocol_window",
            "patient_id":    patient_id,
            "referral_id":   referral_id,
        })
    elif next_action["type"] == "close_referral":
        referral["state"] = "closed"
        referral["state_changed_at"] = _now_iso()
        history.append({
            "state":      "closed",
            "changed_at": _now_iso(),
        })
        referral["history"] = history
        referral_table.put_item(
            Item=_to_decimal(referral))
        _emit_event("referral_closed", {
            "patient_id":  patient_id,
            "referral_id": referral_id,
        })

    return {"action": "transitioned",
            "new_state": referral["state"],
            "next_action": next_action}


def _map_event_to_target_state(event_type):
    """Map a referral event type to its target state."""
    mapping = {
        "ordered":              "ordered",
        "communicated":         "communicated_to_patient",
        "scheduled":            "scheduled",
        "rescheduled":          "rescheduled",
        "attended":             "attended",
        "no_showed":            "no_showed",
        "cancelled":            "cancelled",
        "consult_note_received":
            "consult_note_received",
        "closed":               "closed",
        "aged_out":             "aged_out",
    }
    return mapping.get(event_type)


def _next_referral_action(referral, event_type):
    """Derive the next protocol-driven action."""
    state = referral["state"]
    if state == "ordered":
        return {"type": "engage_patient",
                "reason":
                    "scheduling_assistance_at_protocol_window"}
    if state == "consult_note_received":
        return {"type": "close_referral"}
    if state == "aged_out":
        return {"type": "alert_care_team",
                "reason":
                    "referral_aged_past_protocol_window"}
    return {"type": "no_action"}
```

---

## Step 9: Handle Medication-Reconciliation Seams Across Pharmacies and Clinicians

The assistant maintains the patient's medication list as a single source of truth synthesized from all known pharmacy fills, all known clinician orders, and all patient-reported medications. When a discrepancy is detected, the assistant flags it for human reconciliation rather than attempting clinical judgment.

```python
def process_medication_event(*, patient_id,
                                 medication_event):
    """
    Process a medication event from any source (pharmacy
    fill, clinician order, patient-reported, discharge med
    list). Normalizes, reconciles, updates the synthesized
    list with provenance preserved, and surfaces seams.
    """
    # Step 9A: normalize the medication entry. Production
    # canonicalizes the drug name (RxNorm), the dose
    # representation (UCUM), and the dosing instructions
    # where possible.
    normalized = _normalize_medication(medication_event)

    # Step 9B: load the patient's current synthesized
    # medication list.
    state_table = dynamodb.Table(COORDINATION_STATE_TABLE)
    state = state_table.get_item(
        Key={"patient_id": patient_id}).get(
            "Item", {})
    current_list = state.get(
        "active_medication_list", [])

    # Step 9C: reconcile against the current list.
    reconciliation = _reconcile_medication(
        normalized=normalized,
        current_list=current_list)

    # Step 9D: update the synthesized list with provenance
    # preserved.
    new_list = _apply_med_reconciliation(
        current_list=current_list,
        reconciliation=reconciliation,
        normalized=normalized,
        provenance_id=medication_event.get(
            "provenance_id"))
    state["active_medication_list"] = new_list
    state["last_updated"] = _now_iso()
    state_table.put_item(Item=_to_decimal(state))

    # Step 9E: surface seams for any detected discrepancies.
    seam_table = dynamodb.Table(SEAM_FLAG_TABLE)
    seam_ids = []
    for seam in reconciliation.get("seams", []):
        seam_id = f"seam_{uuid.uuid4().hex}"
        seam_record = {
            "seam_flag_id":      seam_id,
            "patient_id":        patient_id,
            "rule_id":
                "med_discrepancy_pharmacy_vs_clinician",
            "rule_owner":        "pharmacy_director",
            "rule_version":      "v1.0",
            "priority":          seam.get(
                "priority", "medium"),
            "suggested_resolver":
                seam.get("suggested_resolver", "care_team"),
            "description":       seam.get("description"),
            "finding":           seam.get("finding"),
            "raised_at":         _now_iso(),
            "status":            "open",
        }
        seam_table.put_item(Item=_to_decimal(seam_record))
        _emit_event("seam_flag_raised", {
            "patient_id":   patient_id,
            "seam_flag_id": seam_id,
            "rule_id":
                "med_discrepancy_pharmacy_vs_clinician",
        })
        seam_ids.append(seam_id)

    return {
        "action":         "reconciled",
        "list_size":      len(new_list),
        "seams_raised":   len(seam_ids),
    }


def _normalize_medication(medication_event):
    """
    Normalize a medication entry. Demo: thin pass-through
    with a few defaults; production runs RxNorm lookup,
    UCUM dose normalization, and a sig parser for free-
    text dosing instructions.
    """
    return {
        "source_type":
            medication_event.get("source_type",
                                  "unknown"),
        "drug":
            (medication_event.get("drug") or "").lower(),
        "dose":
            medication_event.get("dose"),
        "frequency":
            medication_event.get("frequency"),
        "discontinued":
            medication_event.get("discontinued", False),
        "fill_id":
            medication_event.get("fill_id"),
        "ingested_at":
            medication_event.get("ingested_at",
                                  _now_iso()),
    }


def _reconcile_medication(*, normalized, current_list):
    """
    Reconcile the new medication entry against the current
    list. Returns the reconciliation outcome and any
    detected seams.
    """
    drug_match = None
    for entry in current_list:
        data = entry.get("data", {})
        if data.get("drug", "").lower() == \
                normalized["drug"]:
            drug_match = entry
            break

    if drug_match is None:
        return {"update": "new_entry", "seams": []}

    seams = []
    existing = drug_match.get("data", {})

    # Dose discrepancy.
    if (existing.get("dose") and normalized.get("dose")
            and existing["dose"] != normalized["dose"]):
        seams.append({
            "priority":   "medium",
            "suggested_resolver": "care_team",
            "description":
                ("Pharmacy fill differs in dose from the "
                 "recorded order."),
            "finding": {
                "drug":          normalized["drug"],
                "fill_dose":     normalized.get("dose"),
                "recorded_dose": existing.get("dose"),
                "fill_provenance":
                    normalized.get("fill_id"),
                "recorded_provenance":
                    drug_match.get("provenance_id"),
            },
        })

    # Discontinuation conflict.
    if existing.get("discontinued") and \
            not normalized.get("discontinued"):
        seams.append({
            "priority":   "medium",
            "suggested_resolver": "care_team",
            "description":
                ("Pharmacy filled a medication that was "
                 "previously discontinued."),
            "finding": {
                "drug":          normalized["drug"],
                "discontinued_provenance":
                    drug_match.get("provenance_id"),
            },
        })

    return {"update": "update_existing", "seams": seams}


def _apply_med_reconciliation(*, current_list,
                                  reconciliation, normalized,
                                  provenance_id):
    """Apply the reconciliation to produce the new list."""
    if reconciliation["update"] == "new_entry":
        return current_list + [{
            "data":          normalized,
            "provenance_id": provenance_id,
            "ingested_at":   normalized["ingested_at"],
        }]

    new_list = []
    for entry in current_list:
        data = entry.get("data", {})
        if data.get("drug", "").lower() == \
                normalized["drug"]:
            new_list.append({
                "data":          normalized,
                "provenance_id": provenance_id,
                "ingested_at":   normalized["ingested_at"],
                "previous_provenance_id":
                    entry.get("provenance_id"),
            })
        else:
            new_list.append(entry)
    return new_list
```

---

## Step 10: Generate Care-Team Reporting and Queue Outcome Correlation

Real-time alerts flow to the care team when consent permits. Weekly digests summarize each patient's coordination state, open referrals, transition status, and seam flags. The outcome-correlation pipeline pulls subsequent encounter records, readmission data, ED-utilization data, and patient-and-caregiver-reported coordination experience on multi-quarter windows.

```python
def compose_weekly_digest(patient_id, window_days=7):
    """
    Build a weekly digest for the care team. Consent-gated.
    """
    consent_table = dynamodb.Table(CONSENT_RECORD_TABLE)
    consent = consent_table.get_item(
        Key={"patient_id": patient_id}).get("Item", {})

    if not _consent_permits_care_team_sharing(consent):
        return None

    cutoff = _now() - timedelta(days=window_days)

    # Open referrals.
    referral_table = dynamodb.Table(
        REFERRAL_LIFECYCLE_TABLE)
    open_referrals = []
    for record_list in referral_table.items.values():
        for ref in record_list:
            if ref.get("patient_id") != patient_id:
                continue
            if ref.get("state") in ("closed",
                                     "cancelled"):
                continue
            open_referrals.append({
                "referral_id": ref.get("referral_id"),
                "specialty":   ref.get("specialty"),
                "state":       ref.get("state"),
                "urgency":     ref.get("urgency"),
            })

    # Transitions in progress.
    transition_table = dynamodb.Table(
        TRANSITION_OF_CARE_TABLE)
    transitions = []
    for record_list in transition_table.items.values():
        for tr in record_list:
            if tr.get("patient_id") != patient_id:
                continue
            initiated_at = tr.get("initiated_at", "")
            if not initiated_at:
                continue
            if initiated_at >= cutoff.isoformat():
                transitions.append({
                    "transition_id":
                        tr.get("transition_id"),
                    "destination":
                        tr.get("destination"),
                    "status":
                        tr.get("status"),
                    "items_pending":
                        tr.get("items_pending", []),
                })

    # Open seam flags.
    seam_table = dynamodb.Table(SEAM_FLAG_TABLE)
    open_seams = []
    for record_list in seam_table.items.values():
        for seam in record_list:
            if seam.get("patient_id") != patient_id:
                continue
            if seam.get("status") != "open":
                continue
            raised_at = seam.get("raised_at", "")
            if raised_at >= cutoff.isoformat():
                open_seams.append({
                    "seam_flag_id":
                        seam.get("seam_flag_id"),
                    "rule_id":   seam.get("rule_id"),
                    "priority":  seam.get("priority"),
                })

    digest = {
        "patient_id":    patient_id,
        "report_window": {
            "start": cutoff.isoformat(),
            "end":   _now_iso(),
        },
        "open_referrals":
            open_referrals,
        "transitions_in_progress":
            transitions,
        "open_seam_flags":
            open_seams,
        "report_generated_at": _now_iso(),
    }

    mock_clinician_queue.deliver_alert({
        "alert_id":   f"digest_{uuid.uuid4().hex}",
        "alert_type": "weekly_digest",
        "patient_id": patient_id,
        "digest":     digest,
    })

    return digest


def queue_outcome_correlation(*, patient_id,
                                  window_days_ago=30):
    """
    Queue an outcome-correlation record. Production runs
    the pipeline against institutional encounter, claims,
    and patient-reported-outcome data sources; the demo
    is a stub.
    """
    # Outcome correlation for care coordination is multi-
    # quarter to multi-year work. The primary outcome
    # metrics are referral closure rate, transition-of-
    # care completion rate, medication-reconciliation
    # accuracy, avoidable-readmission rate, avoidable-ED-
    # utilization rate, duplicate-service rate, patient-
    # and-caregiver-reported coordination experience, and
    # caregiver-burden trajectory.
    pass
```

---

## Full Pipeline

The functions above each handle one step. To run the assistant end-to-end, wire them through one entry point that calls each in order.

```python
def coordination_full_pipeline(*,
                                  channel,
                                  channel_session_id,
                                  user_message,
                                  auth_context):
    """
    Full pipeline: receive turn -> screen -> handle acuity
    routing if triggered -> generate response -> output-
    screen -> persist -> queue outcome correlation.
    """
    # Step 4: receive and load context.
    intermediate = receive_conversation_turn(
        channel=channel,
        channel_session_id=channel_session_id,
        user_message=user_message,
        auth_context=auth_context)

    action = intermediate.get("action")
    if action in ("blocked", "acuity_routed"):
        return intermediate

    # Step 5: generate the response.
    response_intermediate = handle_conversation(
        session_id=intermediate["session_id"],
        patient_id=intermediate["patient_id"],
        speaker_role=intermediate["speaker_role"],
        user_message=user_message,
        coordination_context=intermediate[
            "coordination_context"])

    # Step 6: output safety screening.
    screened = screen_coordination_output(
        session_id=response_intermediate["session_id"],
        patient_id=response_intermediate["patient_id"],
        speaker_role=response_intermediate["speaker_role"],
        response_text=
            response_intermediate["response_text"],
        citations=
            response_intermediate["citations"],
        tool_calls=
            response_intermediate["tool_calls"],
        tool_results=
            response_intermediate["tool_results"],
        coordination_context=intermediate[
            "coordination_context"])

    # Step 6E-G: persist artifacts.
    persist_coordination_artifacts(
        session_id=response_intermediate["session_id"],
        patient_id=response_intermediate["patient_id"],
        speaker_role=response_intermediate["speaker_role"],
        response_payload=screened,
        coordination_context=intermediate[
            "coordination_context"])

    # Step 10 (background): queue outcome correlation.
    queue_outcome_correlation(
        patient_id=response_intermediate["patient_id"])

    return screened
```

---

## Demo Runner

A small end-to-end demo that exercises enrollment with cross-organizational consent and caregiver designation; ingestion of a discharge event, a FHIR referral order, and a pharmacy fill that conflicts with the discharge medication list; seam-detection over the resulting state; a within-scope conversation that retrieves the medication list and surfaces the discrepancy; and an out-of-scope conversation that gets safe-template-replaced.

```python
def run_demo():
    """End-to-end demo against the mock infrastructure."""
    print("=" * 60)
    print("CARE COORDINATION ASSISTANT DEMO")
    print("=" * 60)

    # Set up a synthetic patient (David from the recipe
    # opening, with a mix of chronic conditions).
    patient_id = "patient-david"
    mock_healthlake.add_patient(patient_id, {
        "age": 67,
        "active_conditions": [
            "heart_failure",
            "atrial_fibrillation",
            "type_2_diabetes",
            "chronic_kidney_disease_stage_3b",
            "mild_cognitive_impairment",
        ],
        "current_medications": [
            {"drug": "metoprolol", "dose": "50 mg",
             "frequency": "twice daily"},
            {"drug": "lisinopril", "dose": "10 mg",
             "frequency": "once daily"},
            {"drug": "furosemide", "dose": "40 mg",
             "frequency": "once daily"},
        ],
    })

    # Step 1: enroll the patient with consent and a
    # caregiver (David's wife).
    print("\n--- Step 1: Enroll patient ---")
    result = enroll_patient(
        patient_id=patient_id,
        enrollment_program_id=
            "adult_chronic_multi_condition",
        state_of_residence="CA",
        legal_consent_form={
            "preferred_name":     "David",
            "language":           "en-US",
            "channels":           ["in_app", "sms"],
            "data_source_consents": {
                "hl7_v2_adt":            True,
                "hl7_v2_oru":            True,
                "fhir_subscription":     True,
                "claims_batch":          True,
                "pharmacy_ncpdp":        True,
                "home_health_vendor_api": True,
                "patient_reported":      True,
            },
            "sharing_relationships": [
                "with_primary_care",
                "with_specialists",
                "with_care_management",
                "with_designated_caregivers",
            ],
            "sensitive_record_categories": {
                "mental_health":           False,
                "substance_use_42_cfr_part_2": False,
                "hiv":                     False,
                "genetic":                 False,
                "adolescent_confidential": False,
            },
        },
        caregiver_designations=[
            {"preferred_name":   "Linda",
             "relationship":    "spouse",
             "access_level":    "scheduling_only",
             "channels":        ["sms"]},
        ],
        known_relationships={
            "clinicians": [
                "primary_care_dr_patel",
                "cardiology_dr_chen",
                "nephrology_dr_okonkwo",
            ],
            "pharmacies": [
                "primary_pharmacy_walgreens_local",
                "mail_order_express_scripts",
            ],
            "payers": ["medicare_advantage_acme"],
            "ancillary_services": [
                "home_health_three_days_per_week",
                "anticoagulation_clinic_biweekly",
            ],
        })
    print(f"  -> {result}")

    # Step 2: ingest a discharge event from the hospital.
    print("\n--- Step 2: Ingest discharge event ---")
    discharge_result = ingest_event(
        source_type="hl7_v2_adt",
        raw_message={
            "patient_id":     patient_id,
            "event_type":     "discharge",
            "destination":    "home",
            "admission_type": "heart_failure_exacerbation",
            "encounter_id":   "enc_dx_001",
            "source_timestamp": _now_iso(),
        },
        ingestion_metadata={
            "message_id": "msg_dx_001",
            "path":       "hospital_a_hl7_listener",
        })
    print(f"  -> {discharge_result}")

    # Step 2 (continued): ingest a discharge medication
    # list update (furosemide bumped to 60 mg).
    print("\n--- Step 2: Ingest discharge med (furosemide 60 mg) ---")
    dx_med_result = ingest_event(
        source_type="pharmacy_ncpdp",
        raw_message={
            "patient_id":  patient_id,
            "drug":        "furosemide",
            "dose":        "60 mg",
            "frequency":   "once daily",
            "fill_id":     "fill_dx_001",
            "source_timestamp": _now_iso(),
        },
        ingestion_metadata={
            "message_id": "msg_pharm_001",
            "path":       "pharmacy_a_ncpdp",
        })
    print(f"  -> {dx_med_result}")

    # Step 2 (continued): ingest a FHIR referral order
    # for cardiology follow-up.
    print("\n--- Step 2: Ingest cardiology referral ---")
    referral_result = ingest_event(
        source_type="fhir_subscription",
        raw_message={
            "patient_id":   patient_id,
            "resourceType": "ServiceRequest",
            "id":           "ref_demo_cardiology",
            "specialty":    "cardiology",
            "urgency":      "routine",
            "source_timestamp": _now_iso(),
        },
        ingestion_metadata={
            "message_id": "msg_fhir_001",
            "path":       "primary_care_fhir_subscription",
        })
    print(f"  -> {referral_result}")

    # Process referral lifecycle (creates the referral in
    # the ordered state).
    process_referral_event(
        patient_id=patient_id,
        referral_event={
            "referral_id": "ref_demo_cardiology",
            "event_type":  "ordered",
            "specialty":   "cardiology",
            "urgency":     "routine",
        })

    # Step 7: initiate transition-of-care workflow for the
    # discharge event.
    print("\n--- Step 7: Initiate transition of care ---")
    transition_result = initiate_transition_of_care(
        patient_id=patient_id,
        discharge_event={
            "destination":    "home",
            "admission_type": "heart_failure_exacerbation",
            "encounter_id":   "enc_dx_001",
        })
    print(f"  -> {transition_result}")

    # Step 9: process a follow-up pharmacy fill that
    # conflicts with the discharge med (cardiologist's
    # office told the wife to titrate to 80 mg, the
    # pharmacy filled at 80 mg, the discharge list has
    # 60 mg).
    print("\n--- Step 9: Process medication fill (80 mg, conflicts) ---")
    med_event_result = process_medication_event(
        patient_id=patient_id,
        medication_event={
            "patient_id":    patient_id,
            "source_type":   "pharmacy_ncpdp",
            "drug":          "furosemide",
            "dose":          "80 mg",
            "frequency":     "once daily",
            "fill_id":       "fill_post_dx_002",
            "provenance_id": "prov_demo_post_dx_pharm",
            "ingested_at":   _now_iso(),
        })
    print(f"  -> {med_event_result}")

    # Step 3: run seam-detection and protocol-trigger
    # evaluation against the current coordination state.
    print("\n--- Step 3: Evaluate seams and triggers ---")
    seam_result = evaluate_seams_and_triggers(
        patient_id=patient_id,
        event={"type": "post_ingestion_evaluation"})
    print(f"  -> {seam_result}")

    # Within-scope conversation: medication question.
    print("\n--- Within-scope conversation ---")
    msg = ("the cardiologist's office called my wife and "
           "told her i should be on 80 mg of furosemide. "
           "is that what i'm supposed to take?")
    print(f"  Patient: {msg}")
    out = coordination_full_pipeline(
        channel="in_app",
        channel_session_id="session-001",
        user_message=msg,
        auth_context={
            "patient_id":   patient_id,
            "speaker_role": "patient",
        })
    print(f"  Bot:     {out['response'][:200]}...")
    print(f"  -> disposition: {out['disposition']}")
    print(f"  -> citations:   {len(out.get('citations', []))}")

    # Within-scope conversation: referral status.
    print("\n--- Within-scope: referral status ---")
    msg = ("did i ever get scheduled with the "
           "cardiology specialist?")
    print(f"  Patient: {msg}")
    out = coordination_full_pipeline(
        channel="in_app",
        channel_session_id="session-002",
        user_message=msg,
        auth_context={
            "patient_id":   patient_id,
            "speaker_role": "patient",
        })
    print(f"  Bot:     {out['response'][:200]}...")
    print(f"  -> disposition: {out['disposition']}")

    # Out-of-scope (dose titration). The bot should replace
    # with the dose-titration safe template.
    # TODO (TechWriter): Code review Issue 1 (WARNING). The
    # mock LLM checks "furosemide" before the dose-titration
    # phrases, so this test never exercises the
    # OUT_OF_SCOPE_DOSE_TITRATION safe template. Either
    # reorder MockBedrockRuntime.invoke_response so the
    # dose-titration check fires first, or change this
    # message to remove "furosemide" (e.g., "should i lower
    # my heart medication tonight?") so the chained checks
    # reach the dose-titration branch.
    print("\n--- Out-of-scope (dose titration) ---")
    msg = "should i lower my furosemide dose tonight?"
    print(f"  Patient: {msg}")
    out = coordination_full_pipeline(
        channel="in_app",
        channel_session_id="session-003",
        user_message=msg,
        auth_context={
            "patient_id":   patient_id,
            "speaker_role": "patient",
        })
    print(f"  Bot:     {out['response'][:200]}...")
    print(f"  -> disposition: {out['disposition']}")

    # Out-of-scope (acute symptom routes to triage).
    print("\n--- Out-of-scope (acute chest pain) ---")
    msg = ("i have chest pain right now and it feels "
           "different from before")
    print(f"  Patient: {msg}")
    out = coordination_full_pipeline(
        channel="in_app",
        channel_session_id="session-004",
        user_message=msg,
        auth_context={
            "patient_id":   patient_id,
            "speaker_role": "patient",
        })
    print(f"  Bot:     {out['response'][:200]}...")
    print(f"  -> disposition: {out['disposition']}")

    # Caregiver-initiated turn (Linda asks about the
    # appointment). Caregiver has scheduling_only proxy
    # scope, so coordination context is filtered.
    print("\n--- Caregiver conversation (scheduling_only) ---")
    msg = ("i'm david's wife. when is his next "
           "cardiology appointment?")
    print(f"  Caregiver: {msg}")
    out = coordination_full_pipeline(
        channel="in_app",
        channel_session_id="session-005",
        user_message=msg,
        auth_context={
            "patient_id":   patient_id,
            "speaker_role": "caregiver",
            "proxy_scope":  {
                "access_level":    "scheduling_only",
                "sensitive_record_carve_outs": [],
            },
        })
    print(f"  Bot:       {out['response'][:200]}...")
    print(f"  -> disposition: {out['disposition']}")

    # Care-team weekly digest.
    print("\n--- Care-team weekly digest ---")
    digest = compose_weekly_digest(patient_id,
                                     window_days=14)
    if digest:
        print(f"  -> open referrals:       "
              f"{len(digest['open_referrals'])}")
        print(f"  -> transitions in progress: "
              f"{len(digest['transitions_in_progress'])}")
        print(f"  -> open seam flags:      "
              f"{len(digest['open_seam_flags'])}")
    else:
        print("  -> consent does not permit care-team sharing")

    # Summary.
    print("\n" + "=" * 60)
    print("DEMO SUMMARY")
    print("=" * 60)
    print(f"EventBridge events emitted:      "
          f"{len(eventbridge_client.events)}")
    print(f"Coordination state versions:     "
          f"{sum(int(state.get('state_version', 0)) for record_list in mock_tables[COORDINATION_STATE_TABLE].items.values() for state in record_list)}")
    print(f"Provenance journal records:      "
          f"{sum(len(v) for v in mock_tables[PROVENANCE_JOURNAL_TABLE].items.values())}")
    print(f"Referrals tracked:               "
          f"{sum(len(v) for v in mock_tables[REFERRAL_LIFECYCLE_TABLE].items.values())}")
    print(f"Transitions initiated:           "
          f"{sum(len(v) for v in mock_tables[TRANSITION_OF_CARE_TABLE].items.values())}")
    print(f"Seam flags raised:               "
          f"{sum(len(v) for v in mock_tables[SEAM_FLAG_TABLE].items.values())}")
    print(f"Coordination decisions recorded: "
          f"{sum(len(v) for v in mock_tables[DECISION_RECORD_TABLE].items.values())}")
    print(f"Care-team alerts delivered:      "
          f"{len(mock_clinician_queue.alerts)}")
    print(f"Step Functions executions:       "
          f"{len(sfn_client.executions)}")
    print(f"Pinpoint engagements scheduled:  "
          f"{len(pinpoint_client.messages)}")
    print(f"S3 archive objects:              "
          f"{len(s3_client.objects)}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    run_demo()
```

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right structure (consent records with state-specific provisions and per-source consent posture, caregiver records with proxy-access scope, coordination-state entries with provenance references, referral lifecycle records moving through the state machine, transition-of-care records linked to a Step Functions workflow, seam-flag records with named clinical-leadership ownership, coordination-decision records with version stamps, and weekly digests gated by consent), but the distance between it and a real care-coordination assistant serving a payer's chronic-multi-condition population is significant. Here is where that distance lives.

**Real cross-organizational ingestion adapters.** The demo's `ingest_event` accepts pre-structured dicts. Production has a separate Lambda per source: an HL7 v2 listener subscribed to participating hospitals' MLLP feeds with an HL7 parser (hl7apy or vendor-specific); a FHIR poller and FHIR Subscription consumer for the participating ambulatory and inpatient FHIR APIs (with USCDI v3 conformance); a claims-feed processor consuming the payer's claims-feed deliveries (typically X12 837/835 plus value-added enrichment); a pharmacy-API consumer using NCPDP standards or vendor APIs from CVS, Walgreens, Walmart, regional chains, mail-order, and specialty pharmacies; a home-health vendor adapter; an HIE/TEFCA adapter using QHIN federation where the institution participates. Each adapter has authentication, rate limiting, error handling, idempotency, format translation, sensitive-record classification, and provenance recording. The integration layer is multi-quarter engineering work and is the largest single engineering investment in the system.

**Real AWS HealthLake integration.** The demo's `MockHealthLake` is a dict per patient. Production wires HealthLake as the FHIR-native data store normalizing data from multiple EHRs and HIE feeds. The tools that retrieve encounter, condition, medication-request, observation, diagnostic-report, service-request, care-plan, allergy-intolerance, immunization, and coverage data query HealthLake; the assistant's coordination-state-store maintains pointers and synthesized views.

**Real Bedrock Agents action groups (or a custom LLM-and-tool orchestrator).** The demo runs canned responses from `MockBedrockRuntime`. Production wires the coordination tools (`coordination_state_retrieve`, `referral_lifecycle_retrieve`, `encounter_retrieve`, `medication_list_reconcile`, `open_followups_retrieve`, `seam_flags_retrieve`, `protocol_retrieve`, `patient_education_content_retrieve`, `care_team_alert_propose`, `patient_action_propose`, `follow_up_schedule`, `escalation_propose`, `provenance_retrieve`) as Bedrock Agents action groups (one OpenAPI spec per tool with the argument schema, the response schema, and the docstring the LLM uses to decide when to call it), gives the agent the institutional persona prompt with explicit non-clinician scoping and citation discipline, the speaker-role-scoped coordination-context payload, and the Knowledge Base bindings (coordination protocols, patient education, conversation history), and lets the LLM drive the multi-step reasoning, the tool-call orchestration, and the warm-but-boundaried language while the citation-grounding verifier, the scope-filter, and the faithfulness verifier keep the structure honest.

**Real Bedrock Knowledge Base ingestion of the coordination-protocol corpus and the patient-education library.** The demo's `MockProtocolCorpus` is a hand-curated three-item dictionary; the patient-education retrieval is mocked. Production has two Knowledge Bases: one ingesting the institution's curated coordination-protocol corpus (transition-of-care protocols by destination setting, referral-tracking protocols by specialty and urgency, post-discharge protocols by admission type, post-procedure protocols by procedure category, medication-reconciliation protocols, condition-specific coordination playbooks for high-prevalence multi-condition combinations) with metadata filters for transition type, specialty, urgency tier, audience, language, reading level, and version; one ingesting the patient-education library with multilingual and multi-reading-level variants. Each corpus has named ownership at the clinical leadership across primary care, hospital medicine, specialty practice, pharmacy, home health, and care management, with documented review cadence (annual, plus on each material update) and versioned change-management workflow. Stale retrieval is a serious failure mode the corpus governance prevents.

**Real Bedrock Guardrails configuration.** The demo passes `GUARDRAIL_ID` but does not configure a Guardrail. Production configures restricted-topic filters for diagnosis-attempted, prescription-attempted, dose-titration-attempted, treatment-recommendation-beyond-existing-orders, therapy-attempted (which routes to recipe 11.8 pathway), triage-attempted (which routes to recipe 11.6 pathway), benefits-quote-attempted (which routes to recipe 11.5 pathway), refill-handling (which routes to recipe 11.3 pathway), and similar scope violations. The Guardrail is pinned to a specific version, tested against a held-out evaluation set including coordination-specific injection cases (manipulate seam-flag routing, manipulate referral-lifecycle transitions, manipulate scope discipline to elicit clinical recommendations, manipulate proxy-scope to reach restricted records, attempt to access another patient's data), and updated on a versioned-rollout cadence with canary traffic.

**Real Step Functions transition-of-care state machines with clinical-leadership signoff.** The demo's `_select_state_machine_arn` returns a placeholder ARN. Production has a state machine per transition type (hospital-to-home, hospital-to-SNF, ED-to-PCP follow-up, surgery-to-home, oncology-treatment cycles, hospital-at-home, etc.) with states for the protocol-defined steps (welcome-home check-in within 48 hours, medication reconciliation, follow-up-appointment validation, home-health or DME order validation, patient-and-caregiver education delivery, red-flag warning instructions, symptom-monitoring engagement cadence, closure verification), with version control, with clinical-leadership signoff, and with audited execution. The state machines are content owned by clinical leadership; the engineering is the orchestration layer.

**Real referral-lifecycle state machine with named clinical-leadership ownership.** The demo's `REFERRAL_TRANSITIONS` is a thin dict; the next-action logic is rudimentary. Production has the state machine signed off by clinical leadership, with specialty-specific time windows, urgency-tier-specific scheduling protocols, alternative-specialist surfacing for barriers (the specialty practice does not take the patient's insurance; the wait time is six weeks and the patient cannot wait that long), and consult-note-feedback-loop logic. The referral-tracking subsystem is institutional content; the LLM operates on top of it.

**Real seam-detection rule library with named clinical-leadership ownership per rule.** The demo's `SEAM_RULES` has three illustrative rules. Production has dozens to hundreds of rules across medication-discrepancy detection, referral non-scheduling, transition-of-care incompleteness, test-result-acknowledgement gap, conflicting-order detection, care-plan-item aging, lapsed-coverage detection, and similar. Each rule has named clinical-leadership ownership (patient safety officer, pharmacy director, care-management director, post-discharge care coordinator director, etc., depending on the rule), an effective date, a version history, sampled review for precision and recall, and clinical-leadership signoff before deployment. Multi-quarter clinical work to mature.

**Real medication-reconciliation logic with pharmacy-informatics partnership.** The demo's `_normalize_medication` is a pass-through; `_reconcile_medication` runs a thin dose-comparison check. Production has medication-naming canonicalization (RxNorm), dose representation (UCUM), dosing-instruction parsing (best-effort with preserved-free-text fallback), and discrepancy-detection rules owned by pharmacy informatics and signed off by pharmacy leadership. Multi-quarter work to mature, with the institutional pharmacy informatics team as the operational owner.

**Real Connect contact-center integration for the licensed care-management workforce.** The demo's `MockClinicianQueue` accumulates alerts in memory. Production wires `connect_client.start_chat_contact` to route to the licensed care-management queue with the conversation context attached. The licensed care-management workforce (employed or contracted) is sized to the patient population and the expected escalation volume, with peak-hour capacity, per-state licensure coverage where state-specific licensure is required, and per-language coverage where multiple languages are deployed. Under-sized capacity is a safety gap; the warm-handoff infrastructure is a primary safety architecture, not a fallback.

**Real care-team-workflow integration.** The demo's `MockClinicianQueue.deliver_alert` accumulates alerts. Production wires the care-team alert and digest delivery to the institution's case-management system (Epic Healthy Planet, Cerner Population Health, or vendor-specific platforms) or the EHR's task-list integration, with alert-channel configuration, weekly-digest delivery surface, monthly-summary delivery surface, transition-of-care closure reports, and quarterly clinical-review packets. Care-team-operations signoff on display is a launch gate. Consent gating is enforced at every alert and digest delivery time, not just at enrollment, because consent is revocable.

**Real DynamoDB and S3 wiring with separate KMS keys for sensitive surfaces.** The mocks are dictionaries; production is DynamoDB tables with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery on the patient-coordination, coordination-state, referral-lifecycle, transition-of-care, seam-flag, caregiver, conversation, ledger, decision-record, provenance-journal, and consent-record tables, TTL on the conversation-state table tuned for typical session durations, and DynamoDB Streams emitting change events for downstream consumers. The coordination-decision-record-journal S3 bucket has SSE-KMS, Object Lock in compliance mode, lifecycle to S3 Glacier Instant Retrieval after 30 days and Glacier Deep Archive after 90, and retention sized to the longest of HIPAA's six-year minimum, the state's medical-record retention rules, 42 CFR Part 2 retention for substance-use treatment data where applicable, FDA SaMD post-market obligations where applicable, and the institutional regulatory floor. The provenance archive uses a **separately-managed customer-managed KMS key** with separate access-control surfaces; a leaked credential to the general coordination workload should not give an attacker the provenance archive.

**KMS customer-managed keys per data class with separate keys for sensitive surfaces.** Every PHI-bearing resource uses customer-managed KMS keys with key rotation enabled. Different KMS keys for different data classes (general coordination, **provenance journal on a separately-managed key**, **coordination-decision-record on a separately-managed key**, audit-archive, Secrets Manager secrets) limit the blast radius of any single key compromise. Key access is scoped to the specific principals that need it; CloudTrail logs every key-usage event.

**VPC and VPC endpoints.** The chat-handler Lambda runs internet-facing through API Gateway. The ingestion adapter Lambdas (HL7, FHIR, claims, pharmacy, home-health, HIE) and the tool Lambdas that call upstream EHRs, payers, pharmacies, home-health vendors, care-team workflows, mandatory-reporting pathways, and care-navigation systems run in a VPC with PrivateLink (where supported) or a tightly-scoped NAT-gateway path with allow-list. VPC endpoints for Bedrock, DynamoDB, S3, KMS, Secrets Manager, EventBridge, Step Functions, MWAA, Connect, Pinpoint, HealthLake, Comprehend Medical, and CloudWatch Logs keep AWS-internal traffic off the public internet.

**WAF tuning for coordination-conversation traffic patterns.** Coordination endpoints have rate limits tuned for chat-typical traffic; bot-detection rules allow legitimate accessibility tools while blocking automated abuse. Patient-initiated emergency-routing conversations are routed through a separate priority lane that the standard rate limit does not gate.

**Per-Lambda IAM least privilege with separation of concerns and provenance-journal isolation.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda, each scoped to the specific resource ARNs the Lambda touches. The provenance-record Lambda is the only path with write access to the provenance journal and the only path with `kms:GenerateDataKey` on the `PROVENANCE_KMS_KEY_ID`. The chat-handler Lambda has Bedrock invocation and read-write on the conversation tables, but no direct access to the provenance journal or the mandatory-reporting pathway. The seam-detection rule engine Lambda has read access to coordination-state tables and write access to the seam-flag store. None of the assistant's Lambdas have write access to the clinical record except for institutionally-approved coordination-event records (FHIR Communication for the conversation log; FHIR ServiceRequest for follow-up scheduling where the institution permits assistant-originated requests; with explicit patient consent).

**FDA-strategy artifact with regulatory-counsel review.** The institutional regulatory positioning (informational care-coordination support, or registered SaMD where applicable) is documented, reviewed by FDA-experienced regulatory counsel, and maintained as the deployment evolves. Architectural changes that may affect regulatory positioning are reviewed against the artifact. Post-market surveillance obligations for SaMD-positioned deployments are operationalized. The institutional malpractice insurer is part of the policy review. Building a care-coordination assistant without an FDA-strategy artifact is a serious mistake; patient-facing coordination software with cross-organizational data integration sits at the intersection of HIPAA, the Information Blocking and Interoperability rules, state medical-record statutes, state caregiver-consent rules, 42 CFR Part 2, state-specific mental-health-record protections, and (where the assistant produces clinical recommendations) the FDA SaMD line.

**Cross-organizational consent posture with regulatory review.** The demo records `state_of_residence` and a thin set of source consents on the consent record. Production has the per-state matrix for medical-record privacy provisions, for caregiver-consent and proxy-access requirements (some states require notarized HCP/POA documentation; others have specific rules for adolescents and aging adults; rules vary by relationship), for sensitive-record categories (42 CFR Part 2 substance-use treatment records, state-specific mental-health-record protections under California's CMIA, New York's PHL, Illinois's MHDDC, Massachusetts's Chapter 111, and others; HIV record protections; genetic-test-result protections; adolescent confidentiality), and for the Information Blocking rule's required-data-sharing provisions. The consent record is the operational gate the architecture enforces; it is reviewed by legal counsel before launch and on each material change.

**MWAA for population-scale batch ingestion.** The demo runs ingestion event-by-event. Production also runs population-level batch ingestion (FHIR Bulk Data exports per the FHIR Bulk Data Access specification; claims-feed periodic refreshes; population-level seam-detection runs over the program's full panel) on schedules through MWAA or AWS Step Functions, with the batch outputs feeding the coordination-state-store and the seam-detection layer.

**Per-cohort accuracy and equity monitoring with launch gates.** The demo emits CloudWatch metrics with per-rule and per-priority dimensions, which is enough for per-rule dashboards. Production stratifies by cohort axes the institution monitors (per-language, per-channel, per-condition mix, per-age cohort, per-sex, per-social-determinant flag, per-caregiver presence, per-integration-coverage profile), plus two-axis cohorts, and treats per-cohort threshold compliance as a launch gate. Engagement rate, attrition rate, referral-closure rate, transition-of-care completion rate, medication-reconciliation accuracy, seam-detection precision and recall, faithfulness rate, citation-coverage rate, and outcome metrics (avoidable-readmission rate, ED-utilization rate) all get sliced. A cohort with materially lower engagement rate or higher attrition rate or lower referral-closure rate after controlling for condition mix is a clinical-quality and equity issue that aggregate metrics hide. Launch is gated on every cohort meeting the threshold, not on the institution-wide average.

**Outcome-correlation pipeline with operational ownership and multi-year time horizon.** The demo's `queue_outcome_correlation` is a stub. Production has the pipeline pulling subsequent encounter records, claims data, hospitalization data, ED-utilization data, and patient-and-caregiver-reported coordination experience on multi-window correlation (30-day, 90-day, 6-month, 12-month, 24-month, 36-month) with appropriate caution about attribution. Care-coordination outcome attribution requires matched-cohort or quasi-experimental analysis (engaged patients are not a random sample). Operational ownership is jointly held by clinical leadership, the data science team, operations, compliance, and the participating payer's quality and analytics teams.

**Multilingual deployment with validated translations.** The demo is English-only. Most U.S. payer and integrated-delivery-network coordination populations include meaningful non-English-speaking groups. Per-language work: validated coordination-protocol translations (with clinical equivalency review by clinical leadership, not just linguistic translation), validated patient-education translations, validated regulatory-disclaimer phrasings, per-language tone and persona calibration, per-language equity monitoring. Spanish-language deployment typically takes three to four additional months beyond the English go-live; ad-hoc machine translation is not acceptable for protocol-driven coordination instructions.

**Voice-channel deployment for accessibility.** The conversational logic above runs in chat. Adding a voice channel through Amazon Connect with Lex V2 reuses the orchestration logic but adds ASR and TTS layers, tighter latency budgets, voice-specific design (slower pacing, brief responses, accessibility considerations for older patients), and ASR error monitoring scoped to the coordination vocabulary. The voice channel makes the assistant accessible to patients without smartphones or with disabilities that make text input difficult.

**Citation-grounding verifier with structured-output schema validation.** The demo's `_verify_coordination_faithfulness` implements heuristic checks. Production runs an independent verifier model with structured-output schema validation between Bedrock generation and response delivery, grounding every coordination-state assertion to cited provenance and every protocol instruction to a cited protocol with version stamping. Per-cohort faithfulness-failure rate is a launch-gate metric.

**Compensation operations for inappropriate responses or missed seams.** When a patient or clinician disputes an assistant response, when a seam is missed, or when a referral or transition closure is mishandled, the operations team reproduces the conversation, retrieves cited content, and either confirms the assistant followed protocol or identifies the deviation and feeds the failure mode into the improvement loop. Tooling for this workflow is part of production scope and is reviewed by compliance. Disputes are retained for the longer of the institutional record-retention floor and any FDA SaMD post-market obligations. A missed seam that contributed to a preventable adverse event is the most consequential failure category and triggers an immediate clinical-leadership review, not just an operational ticket.

**Disaster-recovery and degraded-mode operation with crisis-pathway integrity preservation.** When upstream dependencies fail (Bedrock outage, EHR unreachable, HIE unreachable, payer claims feed delayed, pharmacy API unreachable, Connect contact-center unreachable), the assistant degrades gracefully. The minimum behavior is "I'm having trouble pulling that data right now; for anything urgent please contact your care team at [number]." Crisis-pathway integrity is preserved across all degraded states; this is a non-negotiable engineering constraint. Per-source failover behavior is documented and tested quarterly. Cross-region failover for Bedrock, Connect, the institutional integrations, and the warm-handoff workforce queue.

**Patient-rights workflow for conversation logs, decision records, and provenance journal.** Conversation logs are dense longitudinal PHI. Coordination-decision records are clinically-significant. The provenance journal is separately governed. Patients have rights to access all of these (with state-specific variations on what they can access in real time vs after clinical review). The institution has retention obligations that vary by state and by record class. Build the workflow: how a patient requests their conversation history, decision records, and (where applicable) provenance records; how the requests are authenticated; how the data is produced; how deletion requests interact with retention obligations and (in some cases) regulatory holds; how the records are referenced from the patient portal for the patient's own access.

**Continuous-improvement loop with structured failure-mode labeling.** Production transcripts surface coordination situations the team did not have content for, retrieval gaps in the protocol corpus, seam-detection misses, citation gaps, scope-discipline drifts, and patterns in the coordination-decision-record journal that point to operational issues. Build the labeling and review workflow: review production transcripts weekly with clinical leadership across primary care, hospital medicine, specialty practice, pharmacy, home health, and care management plus operations plus data science, propose protocol updates, propose seam-detection-rule updates, propose prompt-tuning updates, run them through the evaluation set, deploy via versioned aliases, monitor for regressions. The assistant's quality at month six is determined by whether someone is doing this work, not by how good the launch was.

**Build-vs-buy rigor.** Several mature commercial vendors offer care-coordination platforms with FHIR integration, claims-feed processing, transition-of-care workflows, and (in some cases) hybrid-coordination workforces. Most major institutions in production run a hybrid: thin orchestration layer in-house on the institution's preferred infrastructure, partnership with vendors for the cross-organizational integration substrate (HIE participation, TEFCA QHIN access, claims-feed plumbing), jointly-owned protocol library, jointly-owned seam-detection rule engine. The decision between full-build, full-buy, and hybrid depends on the integration profile, the protocol portfolio, the care-management workforce structure, the population targeted, and the existing technology stack.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the input-screening logic, the cross-organizational consent enforcement (every consent-gated path checks the current consent posture, not a stale snapshot), the per-source consent enforcement (data from a non-consented source is dropped at ingestion), the sensitive-record classification, the seam-detection rules (each rule fires correctly across condition contexts; precision and recall against held-out cases meet the launch-gate threshold; per-cohort calibration is preserved), the referral-lifecycle state-machine transitions (each transition validates correctly; invalid transitions are rejected; aged-out routing fires at the protocol window), the medication-reconciliation logic (RxNorm-canonicalized matching catches same-drug entries; UCUM dose comparison catches discrepancies; discontinuation-conflict detection catches "filled the discontinued med" cases), the citation-grounding verifier (every coordination-state assertion traces to a provenance ID; every protocol instruction cites a versioned protocol), the speaker-role-scoped disclosure check (caregiver carve-outs are enforced), the proxy-access scope enforcement (a scheduling-only caregiver does not see medication content), the conservative-bias check (clinical-judgment claims defer to the care team), and the longitudinal-context loading. Integration tests against a Bedrock test environment, non-production EHR endpoints with synthetic data, a non-production HealthLake datastore, a non-production protocol corpus, and a non-production Connect contact-center. End-to-end tests that simulate full coordination journeys through representative scenarios including the post-discharge welcome-home case, the referral-tracking case, the medication-reconciliation case, the transition-of-care closure case, the cross-clinician conflicting-order case, the caregiver-access-restricted case, the out-of-scope dose-titration case, the out-of-scope diagnosis-attempted case, the acute-symptom-routes-to-triage case, the mental-health-routing case, and the prompt-injection cases. Never use real PHI in test fixtures.

**Observability beyond metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-call investigation. Production runs CloudWatch Logs Insights queries that join across the API Gateway logs, the chat-handler logs, the screening logs, the Bedrock invocation traces, the tool-Lambda logs, the coordination-decision-record journal, the provenance journal (with restricted access), and the audit records by session_id and patient_id. AWS X-Ray traces show the latency contribution of each step. When a single conversation goes wrong, the on-call engineer needs to reconstruct the full trace in seconds, not minutes.

**Cost monitoring and per-active-member attribution.** Bedrock's per-token charges, Knowledge Bases' per-query charges, the vector store's hosting charges, HealthLake's per-resource charges, MWAA's per-environment charges, Pinpoint's per-message charges, Connect's per-handoff charges, and the per-call costs of the upstream-system integrations add up. Some coordination conversations are dramatically more expensive than others (a multi-turn post-discharge conversation with extensive provenance retrieval, output-verification regeneration, transition-orchestration initiation, and care-team alert generation costs more than a one-shot scheduling-status check). Per-active-member infrastructure cost is small relative to the cost of even a single avoided readmission; per-member-per-month attribution makes the cost story explicit. The dominant operational cost is the licensed care-management workforce, not the AWS infrastructure; under-investing in the workforce is a safety gap.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 11.9: Care Coordination Assistant](chapter11.09-care-coordination-assistant) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
