# Recipe 11.8: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 11.8. It shows one way you could translate the mental-health support bot pipeline into working Python using boto3 against Amazon Bedrock (LLM with function-calling), Amazon Bedrock Knowledge Bases (managed RAG over the therapeutic-content library, the psychoeducation library, and the longitudinal conversation history), Amazon Bedrock Guardrails, AWS Lambda, AWS Step Functions, Amazon API Gateway, Amazon DynamoDB, Amazon S3, Amazon Pinpoint, Amazon Connect, and Amazon EventBridge. The demo uses a `MockBedrockRuntime` standing in for LLM-driven response composition, a `MockEHR` standing in for the chart-context system and FHIR CarePlan store (which is where safety plans live in many institutions), a `MockTherapeuticContentLibrary` standing in for the curated CBT/behavioral-activation/mindfulness/distress-tolerance content, a `MockSafetyPlanStore` for the patient's Stanley-Brown-style safety plan, a `MockCrisisClassifier` for the validated-language crisis-screening signal, a `MockClinicianQueue` for the warm-handoff workforce, a `MockMandatoryReportingPathway` for state-specific reporting routing, a `MockCareTeamWorkflow` for consent-gated alert and digest delivery, a `MockTable` for each DynamoDB table (longitudinal-store, conversation-state, conversation-metadata, tool-call-ledger, support-decision-record-journal, crisis-event-record, warm-handoff-queue, symptom-tracking-store, sensitive-disclosure-store, consent-record), a `MockEventBus` for EventBridge, a `MockPinpoint` for crisis-resource notifications, a `MockDecisionJournal` standing in for the S3 support-decision-record archive, a `MockSensitiveArchive` standing in for the separately-keyed S3 sensitive-disclosure archive, and a `MockCloudWatch` for the metric emissions. It is not production-ready. There is no real Bedrock Agents action group configured, no real Knowledge Base ingestion, no real Guardrail configuration, no API Gateway plumbing, no Step Functions warm-handoff workflow definition, no Connect contact-center integration, no WAF rule tuning, no per-Lambda IAM least privilege, no separately-keyed KMS for the sensitive-disclosure surface, no VPC endpoints to the EHR, no Object-Lock-protected support-decision-record journal sized to state-specific mental-health-record retention rules, no SageMaker-hosted custom crisis classifier, and no Secrets Manager wiring for the upstream-system credentials. Think of it as the sketchpad version: useful for understanding the shape of a mental-health support pipeline that respects the continuous-crisis-screening discipline, the therapeutic-content-corpus-as-code discipline, the explicit-non-therapist-disclosure discipline, the companion-pattern-avoidance discipline, the safety-plan-integration discipline, the warm-handoff-as-primary-safety-architecture discipline, the mandatory-reporting-routing discipline, the citation-grounding discipline, the consent-gated-care-team-reporting discipline, the per-cohort-monitoring discipline, and the audit-everything discipline this recipe demands. It is not something you would point at a payer's behavioral-health population on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the seven pseudocode steps from the main recipe: enroll the patient with explicit mental-health-specific consent and initialize the longitudinal store (Step 1); receive the message with disclosure refresh, continuous crisis screening, sensitive-disclosure detection, and longitudinal-context loading (Step 2); engage the crisis pathway when crisis screening triggers, with anchor-route-stay-and-bridge discipline (Step 3); generate the response with therapeutic-content-grounded reasoning, scope discipline, and companion-pattern avoidance (Step 4); run output safety with companion-pattern detection, scope verification, and citation grounding (Step 5); persist support-decision records, sensitive-disclosure records on a separate KMS key, and longitudinal updates (Step 6); generate consent-gated care-team reports and queue outcome correlation (Step 7). The synthetic patients, safety plans, conversations, and clinical contexts in the demo are fictional; nothing in this file should be interpreted as clinical guidance from any real institution. **If you or someone you know is in crisis: in the United States, call or text 988 to reach the Suicide and Crisis Lifeline, or call 911 for an active emergency.**

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also configure an Amazon Bedrock Agent (or a custom Lambda-based orchestrator) with action groups defining the support tools (`therapeutic_content_retrieve`, `safety_plan_retrieve`, `symptom_tracking_retrieve`, `symptom_log_record`, `clinical_rule_compute`, `conversation_history_retrieve`, `crisis_resource_retrieve`, `warm_handoff_propose`, `care_team_alert_propose`, `mandatory_report_route`, `longitudinal_disclosure_record`), each backed by a tool-implementation Lambda that wraps the institution's curated therapeutic-content corpus, the patient's safety-plan store (often FHIR CarePlan), the symptom-tracking store, the validated clinical-rule scoring (PHQ-9, GAD-7, AUDIT, C-SSRS), the licensed-clinician workforce queue (often Amazon Connect), the mandatory-reporting routing pathway, and the consent-gated care-team integration. You would also configure Amazon Bedrock Knowledge Bases ingesting curated content from S3 covering the institution-validated therapeutic-content library (CBT modules drawn from manualized protocols, behavioral-activation exercises, DBT distress-tolerance skills, mindfulness practices, sleep-hygiene content, journaling prompts, condition-specific psychoeducation), the patient-education library (with multilingual and multi-reading-level variants), and the longitudinal conversation-history corpus (so the bot can find a thing the patient said three months ago, which matters more in mental-health support than almost any other use case). You would configure an Amazon Bedrock Guardrail with restricted-topic filters for therapy-attempted, diagnosis-attempted, medication-recommendation-attempted, trauma-processing-attempted, companion-pattern-content (simulating friendship, affection, romantic interest), pro-self-harm content, pro-eating-disorder content, and harmful-coping-strategy endorsement at minimum. The mental-health-specific scope discipline is unusually strict because the consequences of scope violations are particularly serious. You would also configure an API Gateway endpoint fronting the chat-handler Lambda, an AWS WAF web ACL with rate limits tuned for the mental-health-support pattern (a patient in crisis sometimes types in short bursts; rate limits must not gate the crisis path), the ten DynamoDB tables (longitudinal-store, conversation-state, conversation-metadata, tool-call-ledger, support-decision-record-journal, crisis-event-record, warm-handoff-queue, symptom-tracking-store, sensitive-disclosure-store on a separate KMS key, consent-record), an Amazon S3 bucket with Object Lock in compliance mode for the support-decision-record journal sized to the longest of HIPAA's six-year minimum, the state's mental-health-record retention rules (which often exceed general medical-record rules), 42 CFR Part 2 obligations where substance-use-treatment data is involved, FDA SaMD post-market obligations where applicable, and the institutional regulatory floor, a separately-keyed S3 archive for the sensitive-disclosure surface (so a routine audit query does not accidentally surface mandatory-reporting-relevant content), an EventBridge bus for support-lifecycle events (`patient_enrolled`, `crisis_screen_triggered`, `warm_handoff_initiated`, `warm_handoff_completed`, `sensitive_disclosure_recorded`, `mandatory_report_routed`, `symptom_log_recorded`, `care_team_alert_delivered`, `support_decision_recorded`, `conversation_completed`), an AWS Step Functions state machine for the warm-handoff workflow with states for handoff initiation, clinician acknowledgment, bridge-and-stay-present, and completion, a Kinesis Data Firehose delivery stream for the conversation-audit archive, AWS Secrets Manager secrets for the EHR, care-team-workflow, mandatory-reporting-pathway, and care-navigation credentials, an Amazon Pinpoint application for crisis-resource notifications (988, institutional crisis line) when the patient prefers a push or SMS reminder of how to reach a human, and an Amazon Connect contact center for the licensed-clinician warm-handoff queue. The demo replaces all of these with small mocks so the focus stays on the continuous-crisis-screening, the disclosure-refresh, the longitudinal-context loading, the warm-handoff routing, the citation-grounded response generation, the companion-pattern-detection, and the support-decision-record persistence logic rather than on the platform plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` for the orchestration model and the smaller models (intent classification, crisis-screening pre-filtering, summarization)
- `bedrock-agent-runtime:InvokeAgent` if you wire Bedrock Agents instead of running the orchestration in a custom Lambda
- `bedrock:Retrieve` and `bedrock:RetrieveAndGenerate` on the Knowledge Base ARNs holding the therapeutic-content library, the psychoeducation library, and the longitudinal conversation history
- `bedrock:ApplyGuardrail` on the Guardrail ARN you configured
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the ten tables, scoped to the specific table ARNs (the sensitive-disclosure table on a separately-keyed KMS path)
- `events:PutEvents` on the support-events bus
- `firehose:PutRecord` on the audit-archive Firehose delivery stream
- `s3:PutObject` on the support-decision-record-journal bucket prefix and the separately-keyed sensitive-disclosure archive prefix
- `cloudwatch:PutMetricData` for operational metrics (engagement rate, attrition rate, crisis-screening sensitivity, warm-handoff completion rate, companion-pattern-violation rate, citation-coverage rate, per-cohort slices)
- `secretsmanager:GetSecretValue` on the upstream-system credential secrets pinned to the current rotation versions
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the longitudinal-store, conversation tables, the tool-call ledger, the support-decision-record table, the crisis-event record, the warm-handoff queue, the symptom-tracking store, the consent record, the support-decision-record journal, the audit archive, and the Secrets Manager secrets, plus the **separately-managed** customer-managed key protecting the sensitive-disclosure surface
- `mobiletargeting:SendMessages` on the Pinpoint application for crisis-resource notification
- `connect:StartChatContact` and related actions on the Connect contact-center for warm-handoff to licensed clinicians
- `states:StartExecution` on the Step Functions state machine for the warm-handoff workflow
- For the tool Lambdas calling the EHR, care-team workflow, mandatory-reporting pathway, or care-navigation systems: VPC-endpoint or PrivateLink permissions, plus whatever each upstream system's auth flow requires

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The chat-handler Lambda has Bedrock invocation and read-write on the conversation tables, but no direct access to the EHR, the sensitive-disclosure store, or the mandatory-reporting pathway. The safety-plan-retrieve Lambda has read-only access to the FHIR CarePlan resources. The crisis-screening Lambda has Bedrock invocation rights and (when a custom classifier is hosted) SageMaker invocation rights, with no access to the longitudinal store or the conversation log beyond the immediate utterance. The longitudinal-disclosure-record Lambda is the only path that writes the sensitive-disclosure store, with the separately-managed KMS key. The warm-handoff Lambda has Connect StartChatContact rights and write access to the warm-handoff queue. The mandatory-report-route Lambda has the access required to post to the institutional mandatory-reporting pathway with state-specific routing. None of the bot's Lambdas have write access to the clinical record except for institutionally-approved support-event records (FHIR Communication resources for the conversation log; FHIR Observation resources for symptom-tracking data where the institution permits bot-originated observations; with explicit patient consent).

A few things worth knowing upfront:

- **Continuous crisis screening is the architectural floor, not a feature.** Every patient utterance is screened. The screening uses validated language adapted from instruments like C-SSRS and PHQ-9 item 9. The false-negative rate is the launch-gate metric, calibrated by sampled review with licensed mental-health clinicians, monitored per-cohort. The demo's `_crisis_screen` is keyword-and-rule-based for clarity; production layers a tuned classifier on top with held-out validation.
- **The bot is not a therapist and says so, repeatedly.** The disclosure refresh runs on every session (and at defined intra-session cadences). The system prompt forbids therapy-attempted responses. The output safety detects scope violations. The scope discipline is the difference between a careful evidence-based deployment and the products that have caused documented harm in the broader category. Skip the discipline and the bot drifts.
- **Companion-pattern avoidance is architectural discipline, not just a prompt instruction.** The bot does not simulate friendship, affection, or personhood. The system prompt forbids it. The output-safety pipeline detects "I missed you" / "I've been thinking about you" / first-person emotional claims and either regenerates or replaces with a safer response. The conversation review process tags companion-pattern-violations as a failure mode. The demo's `_detect_companion_pattern` runs a heuristic; production runs a classifier reviewed by behavioral-health clinicians.
- **Warm handoff to licensed clinicians is the primary safety architecture.** The bot does not attempt to talk a patient through an active suicidal crisis using AI alone. The bot anchors briefly, routes to 988 or the institutional crisis line or 911, surfaces the safety plan if applicable, and bridges to a licensed human in the platform's clinician queue. The bot stays present until the human joins. The demo's `_initiate_warm_handoff` enqueues the handoff; production runs the bridge as a Step Functions workflow against Connect with conversation context attached.
- **Safety-plan integration is conversational, not just a static document reference.** When the patient has a Stanley-Brown-style safety plan on file (typically created with their therapist), the bot can surface specific steps when the conversation context suggests they are relevant. The bot does not modify the safety plan; modifications are done with the patient's clinician. The demo's `_surface_safety_plan_steps` walks the plan; production has the safety plan stored as a FHIR CarePlan resource with structured Goals.
- **Sensitive-disclosure surface is separately governed with restricted access.** Disclosures of child abuse, elder abuse, intimate-partner violence, certain mental-health crisis types, severe medication side effects, and trauma require careful handling. The sensitive-disclosure store uses a separately-managed KMS key for blast-radius containment. Mandatory-reporting categories route to a licensed mandatory reporter (the bot is not one). The demo collapses the routing for clarity; production has a state-specific routing matrix reviewed by legal counsel.
- **Mental-health-record privacy exceeds HIPAA baseline in some states.** California, New York, Illinois, Massachusetts, and others have enhanced privacy protections. 42 CFR Part 2 applies for substance-use treatment information. The consent posture, the data-sharing posture, the retention posture, and the patient-access posture are reviewed by counsel familiar with state-specific statutes. The demo's `consent_record` captures state-of-residence; production has the per-state variations encoded in policy.
- **Care-team sharing requires explicit, separate, revocable consent.** A patient enrolling in the bot has not necessarily consented to having their bot interactions surfaced to their primary therapist or psychiatrist. The consent posture is collected separately at enrollment, is revocable at any time, and is operationally enforced. The demo's `_consent_permits_care_team_sharing` checks the flag; production checks the current consent posture at every alert and digest delivery time.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, screening-instrument score, and numeric metadata field passes through `Decimal`. The `_to_decimal` helper handles it.
- **The example collapses many Lambdas into a single Python file.** In production the chat handler, the input-screening function, the crisis-screening function, the longitudinal-context-loading function, each tool-implementation function, the warm-handoff-routing function, the output-screening function, the companion-pattern-detector, the support-decision-record-persistence function, the sensitive-disclosure-recording function, the care-team-reporting function, and the outcome-correlation function are separate Lambdas with their own IAM roles, error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, model IDs, the crisis-screen vocabulary, the safety-plan template, the disclosure-refresh language, and the engagement-policy thresholds are what you would change between environments.

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
# Mental-health conversation logs are dense PHI of an unusually
# sensitive variety: psychiatric diagnoses, medication
# adherence, suicidality, substance use, trauma history, and
# disclosures with mandatory-reporting implications. Log
# structural metadata only (session_id, patient_id_hash,
# intent, tool name, tool latency, tool outcome,
# crisis_screen_disposition), never raw user utterances, never
# raw generated responses, never tool arguments that contain
# identifiers, never specific clinical-rule input values.
# Full transcripts and full tool calls live in the audit
# pipeline (Firehose plus Object-Lock S3) with state-specific
# mental-health-record retention and access controls; the
# sensitive-disclosure surface lives on a separately-managed
# KMS key.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from Bedrock, DynamoDB,
# EventBridge, Firehose, CloudWatch, S3, Pinpoint, Connect,
# Step Functions, and Secrets Manager. The mental-health
# bot's response window is tighter than the chronic-disease
# coach: a patient who typed a crisis disclosure expects an
# anchor response within a couple of seconds, not minutes.
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

# --- Resource Names ---
# Fill these in with your actual resource names. The demo
# prints what it would write rather than failing if the
# resources do not exist; see run_demo() at the bottom.
LONGITUDINAL_STORE_TABLE         = "mh-longitudinal-store"
CONVERSATION_STATE_TABLE         = "mh-conversation-state"
CONVERSATION_METADATA_TABLE      = "mh-conversation-metadata"
TOOL_CALL_LEDGER_TABLE           = "mh-tool-call-ledger"
DECISION_RECORD_TABLE            = "mh-support-decision-journal"
CRISIS_EVENT_TABLE               = "mh-crisis-event-record"
WARM_HANDOFF_QUEUE_TABLE         = "mh-warm-handoff-queue"
SYMPTOM_TRACKING_TABLE           = "mh-symptom-tracking"
SENSITIVE_DISCLOSURE_TABLE       = "mh-sensitive-disclosure"
CONSENT_RECORD_TABLE             = "mh-consent-record"
SUPPORT_EVENT_BUS_NAME           = "mh-support-events-bus"
AUDIT_ARCHIVE_FIREHOSE_NAME      = "mh-audit-archive"
DECISION_RECORD_BUCKET           = "mh-decision-journal"
SENSITIVE_DISCLOSURE_BUCKET      = "mh-sensitive-disclosure-archive"
PINPOINT_APPLICATION_ID          = "PINPOINT_APP_PLACEHOLDER"
CONNECT_INSTANCE_ID              = "CONNECT_INSTANCE_PLACEHOLDER"
CONNECT_CONTACT_FLOW_ID          = "CONNECT_FLOW_PLACEHOLDER"
HANDOFF_STATE_MACHINE_ARN        = "STATE_MACHINE_ARN_PLACEHOLDER"
CLOUDWATCH_NAMESPACE             = "MentalHealthSupport"

# Bedrock Knowledge Base IDs. The therapeutic-content corpus
# is the curated CBT/behavioral-activation/mindfulness/
# distress-tolerance content reviewed by behavioral-health
# clinical leadership. The psychoeducation library is the
# institutionally-curated multilingual psychoeducation
# content. The conversation-history index is the patient-
# specific retrievable history (when the patient mentions
# something said three months ago, the bot can find it).
THERAPEUTIC_KB_ID                = "THERAPEUTIC_KB_PLACEHOLDER"
PSYCHOED_KB_ID                   = "PSYCHOED_KB_PLACEHOLDER"
HISTORY_KB_ID                    = "HISTORY_KB_PLACEHOLDER"

# Bedrock Guardrail for restricted-topic filtering. Configure
# in the Bedrock console with restricted topics for therapy-
# attempted, diagnosis-attempted, medication-recommendation-
# attempted, trauma-processing-attempted, companion-pattern-
# content, pro-self-harm content, pro-eating-disorder content,
# and harmful-coping-strategy endorsement. Pin to a specific
# version, not DRAFT, in production.
GUARDRAIL_ID                     = "GUARDRAIL_PLACEHOLDER_ID"
GUARDRAIL_VERSION                = "1"

# KMS key IDs. The sensitive-disclosure surface uses a
# separately-managed customer key for blast-radius containment.
# A leaked credential to the general support workload should
# not give an attacker the sensitive-disclosure archive.
GENERAL_KMS_KEY_ID               = "GENERAL_KMS_PLACEHOLDER"
SENSITIVE_DISCLOSURE_KMS_KEY_ID  = "SENSITIVE_KMS_PLACEHOLDER"

# Deploy-time guardrail. Any blank resource name is a deploy-
# time bug, not a runtime surprise.
for _name, _value in [
    ("LONGITUDINAL_STORE_TABLE",     LONGITUDINAL_STORE_TABLE),
    ("CONVERSATION_STATE_TABLE",     CONVERSATION_STATE_TABLE),
    ("CONVERSATION_METADATA_TABLE",  CONVERSATION_METADATA_TABLE),
    ("TOOL_CALL_LEDGER_TABLE",       TOOL_CALL_LEDGER_TABLE),
    ("DECISION_RECORD_TABLE",        DECISION_RECORD_TABLE),
    ("CRISIS_EVENT_TABLE",           CRISIS_EVENT_TABLE),
    ("WARM_HANDOFF_QUEUE_TABLE",     WARM_HANDOFF_QUEUE_TABLE),
    ("SYMPTOM_TRACKING_TABLE",       SYMPTOM_TRACKING_TABLE),
    ("SENSITIVE_DISCLOSURE_TABLE",   SENSITIVE_DISCLOSURE_TABLE),
    ("CONSENT_RECORD_TABLE",         CONSENT_RECORD_TABLE),
    ("SUPPORT_EVENT_BUS_NAME",       SUPPORT_EVENT_BUS_NAME),
    ("AUDIT_ARCHIVE_FIREHOSE_NAME",  AUDIT_ARCHIVE_FIREHOSE_NAME),
    ("DECISION_RECORD_BUCKET",       DECISION_RECORD_BUCKET),
    ("SENSITIVE_DISCLOSURE_BUCKET",  SENSITIVE_DISCLOSURE_BUCKET),
    ("CLOUDWATCH_NAMESPACE",         CLOUDWATCH_NAMESPACE),
    ("THERAPEUTIC_KB_ID",            THERAPEUTIC_KB_ID),
    ("PSYCHOED_KB_ID",               PSYCHOED_KB_ID),
    ("HISTORY_KB_ID",                HISTORY_KB_ID),
    ("GUARDRAIL_ID",                 GUARDRAIL_ID),
    ("GUARDRAIL_VERSION",            GUARDRAIL_VERSION),
    ("GENERAL_KMS_KEY_ID",           GENERAL_KMS_KEY_ID),
    ("SENSITIVE_DISCLOSURE_KMS_KEY_ID",
                                     SENSITIVE_DISCLOSURE_KMS_KEY_ID),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every conversation turn carries the model version, the
# prompt version, the Knowledge Base versions, the Guardrail
# version, the active therapeutic-content-corpus version,
# the active crisis-screen-classifier version, and the
# active consent version. This is how a future audit
# reconstructs which versions produced any given support
# decision.
PROMPT_VERSION                   = "mh-prompt-v1.0"
AGENT_VERSION                    = "mh-agent-v1.0"
THERAPEUTIC_CONTENT_VERSION      = "therapeutic-corpus-v1.0"
CRISIS_CLASSIFIER_VERSION        = "crisis-classifier-v1.0"
INSTITUTION_ID                   = "acme-health-system"
INSTITUTION_DISPLAY_NAME         = "Acme Behavioral Health"

# --- Model IDs ---
# Two model roles. The orchestration model handles the multi-
# step reasoning, the tool calls, the warm-but-boundaried
# language, and the final response generation. The smaller
# model handles intent classification, crisis pre-filtering,
# and routine summarization.
#
# If your region requires cross-region inference, use the
# inference profile ID. TODO: verify the exact model IDs
# available in your region and account; Bedrock model
# availability evolves over time.
SMALL_MODEL_ID                   = "anthropic.claude-3-5-haiku-20241022-v1:0"
ORCHESTRATION_MODEL_ID           = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# --- Pipeline Tuning ---
# Below this confidence on intent classification, ask a
# clarifying question rather than routing to a specific tool
# that will produce a low-quality answer.
INTENT_CONFIDENCE_THRESHOLD      = Decimal("0.70")

# Disclosure-refresh cadence. The bot re-states "I'm a chat
# tool, not a person, not a therapist" at every session and
# at defined intra-session intervals to reinforce the
# relationship boundary. Skipping this is how generalist
# bots drift toward companion-pattern.
DISCLOSURE_REFRESH_TURN_INTERVAL = 20

# Engagement intensity defaults. The mental-health bot
# defaults to patient-initiated engagement to avoid
# surveillance flavor; bot-initiated check-ins require
# explicit opt-in.
DEFAULT_ENGAGEMENT_INTENSITY     = "patient_initiated_only"

# Institution regulatory positioning: "informational"
# indicates the deployment is positioned as informational
# behavioral-health support with clinician oversight in
# regulated edge cases; "registered_samd" indicates the
# deployment is registered as Software-as-a-Medical-Device
# with FDA SaMD post-market obligations. The disclaimer
# language and the audit retention scale with this.
INSTITUTION_REGULATORY_POSITION  = "informational"
```

```python
# --- Crisis-Screening Vocabulary ---
# Continuous crisis screening runs on every patient utterance.
# The categories are calibrated for the mental-health support
# population and use language drawn from validated screening
# instruments (C-SSRS, PHQ-9 item 9). In production each
# category is owned by behavioral-health clinical leadership,
# reviewed against held-out crisis-presentation cases, and
# layered with a tuned classifier on top of keyword detection.
# False-negative rate is the launch-gate metric.
#
# Note: the keyword lists below are illustrative for the
# demo; production crisis classifiers handle paraphrase,
# negation, hypotheticals ("if I were going to..."), past-
# tense framing ("I used to..."), and culturally and
# linguistically variant expressions. Keyword detection
# alone is not sufficient.
CRISIS_VOCABULARY = {
    "active_suicidal_ideation_with_intent": {
        "keywords": [
            "going to kill myself",
            "going to end my life",
            "tonight is the night",
            "have a plan to",
            "have the pills ready",
            "have the gun",
            "ready to die",
        ],
        "urgency": "imminent_emergency",
        "dimensions": ["active_ideation", "intent", "plan",
                       "means", "imminent"],
    },
    "active_suicidal_ideation_with_plan": {
        "keywords": [
            "thinking about how i would",
            "been planning",
            "figured out how",
            "have a plan",
        ],
        "urgency": "acute_crisis",
        "dimensions": ["active_ideation", "plan"],
    },
    "active_suicidal_ideation": {
        "keywords": [
            "want to kill myself",
            "want to die",
            "want to end my life",
            "wish i was dead",
            "wish i could disappear forever",
            "thinking about suicide",
            "suicidal",
        ],
        "urgency": "acute_crisis",
        "dimensions": ["active_ideation"],
    },
    "passive_suicidal_ideation": {
        # Passive ideation is not the same as active intent
        # but is still a positive crisis screen that warrants
        # a careful follow-up question. The C-SSRS handles
        # this distinction explicitly.
        "keywords": [
            "would be better off without me",
            "wish i wouldn't wake up",
            "tired of being alive",
            "don't want to be here anymore",
            "want this to be over",
            "want it all to stop",
        ],
        "urgency": "sub_acute",
        "dimensions": ["passive_ideation"],
    },
    "self_harm_active": {
        "keywords": [
            "cut myself",
            "cutting myself",
            "want to hurt myself",
            "going to hurt myself",
            "burned myself",
        ],
        "urgency": "acute_crisis",
        "dimensions": ["self_harm_active"],
    },
    "homicidal_ideation": {
        "keywords": [
            "going to kill",
            "want to hurt them",
            "going to hurt someone",
        ],
        "urgency": "imminent_emergency",
        "dimensions": ["homicidal_ideation"],
    },
    "acute_psychotic": {
        "keywords": [
            "voices telling me to",
            "hearing things that aren't there",
            "they're after me",
            "being controlled",
        ],
        "urgency": "acute_crisis",
        "dimensions": ["psychotic_symptoms"],
    },
    "overdose_risk": {
        "keywords": [
            "took too many pills",
            "took the whole bottle",
            "swallowed everything",
        ],
        "urgency": "imminent_emergency",
        "dimensions": ["overdose_risk"],
    },
}

# --- Sensitive-Disclosure Patterns ---
# Disclosures that route to specific institutional pathways
# without ending the support conversation. Mandatory-reporting
# categories (child abuse, elder abuse, certain IPV cases per
# state law) route to a licensed mandatory reporter; the bot
# is not one. Other categories route to care-navigation or
# care-team-followup.
SENSITIVE_DISCLOSURE_PATTERNS = {
    "child_abuse_indicator": {
        "keywords": [
            "my child is being",
            "child is being hurt",
            "kids are being hit",
            "i hit my child",
        ],
        "route": "mandatory_reporter",
        "mandatory_reporting": True,
    },
    "elder_abuse_indicator": {
        "keywords": [
            "my parent is being",
            "elderly parent is being",
            "they're hurting my mother",
            "they're hurting my father",
        ],
        "route": "mandatory_reporter",
        "mandatory_reporting": True,
    },
    "intimate_partner_violence": {
        "keywords": [
            "he hits me", "she hits me",
            "afraid of my partner",
            "afraid of my husband",
            "afraid of my wife",
            "hurts me when",
        ],
        "route": "ipv_pathway",
        # IPV is sometimes mandatory-reporting and sometimes
        # not, depending on state. Production has the state-
        # specific matrix encoded in policy.
        "mandatory_reporting": False,
    },
    "substance_use_crisis": {
        "keywords": [
            "drinking too much",
            "can't stop drinking",
            "using again",
            "relapsed",
        ],
        "route": "substance_use_pathway",
        "mandatory_reporting": False,
    },
    "eating_disorder_behavior": {
        "keywords": [
            "haven't eaten in days",
            "purging",
            "restricting again",
        ],
        "route": "ed_specialty_team",
        "mandatory_reporting": False,
    },
    "medication_discontinuation": {
        "keywords": [
            "stopped taking my",
            "haven't taken my",
            "ran out of my medication",
        ],
        "route": "care_team_followup",
        "mandatory_reporting": False,
    },
    "trauma_disclosure": {
        # Trauma disclosures are within scope to acknowledge
        # and route; trauma processing is out of scope.
        "keywords": [
            "happened to me",
            "what they did to me",
            "abused as a child",
        ],
        "route": "trauma_specialty_team",
        "mandatory_reporting": False,
    },
}

# --- Therapeutic Content Library (illustrative) ---
# In production this is the institutionally-curated, version-
# controlled, behavioral-health-clinical-leadership-signed-off
# library indexed in a Bedrock Knowledge Base with metadata
# filters for modality, indication, contraindication,
# audience, language, reading level, and version. The dict
# below holds a few illustrative items demonstrating the
# structure. Production has 50-200 items per condition with
# defined indications and contraindications; a behavioral-
# activation exercise indicated for moderate depression has
# different contraindications from a distress-tolerance
# skill indicated for acute distress.
THERAPEUTIC_CONTENT_LIBRARY = {
    "grounding_5_4_3_2_1": {
        "content_id": "grounding_5_4_3_2_1",
        "content_version": "v1.0",
        "modality": "distress_tolerance",
        "indication": ["acute_anxiety", "panic", "spiral",
                       "dissociation_mild"],
        "contraindication": ["active_psychosis"],
        "audience": "adult",
        "language": "en-US",
        "reading_level": "grade_6",
        "duration_minutes": 5,
        "title": "5-4-3-2-1 Sensory Grounding",
        "steps": [
            "Find a comfortable position. Take a breath.",
            ("Name five things you can see right now. "
             "Just type them out as you notice them."),
            ("Name four things you can feel. Physical "
             "sensations, like the texture of a sleeve "
             "or the weight of the blanket."),
            "Three things you can hear.",
            "Two things you can smell.",
            ("One thing you can taste, or one slow breath "
             "in and out."),
        ],
        "closing": (
            "How are you noticing your body now compared "
            "to a few minutes ago?"),
    },
    "cognitive_restructuring_brief": {
        "content_id": "cognitive_restructuring_brief",
        "content_version": "v1.0",
        "modality": "cbt",
        "indication": ["worry_spiral", "anxious_thought",
                       "catastrophizing"],
        "contraindication": ["active_crisis",
                             "psychotic_symptoms"],
        "audience": "adult",
        "language": "en-US",
        "reading_level": "grade_8",
        "duration_minutes": 10,
        "title": "Brief Cognitive Restructuring",
        "steps": [
            ("First, can you name the specific thought "
             "that's looping? In one sentence."),
            ("What's the evidence that this thought is "
             "true? Just the strongest piece."),
            ("What's the evidence against it, or that the "
             "outcome might not be as bad as it feels?"),
            ("What's a more balanced way of saying the "
             "same thing?"),
        ],
    },
    "behavioral_activation_one_step": {
        "content_id": "behavioral_activation_one_step",
        "content_version": "v1.0",
        "modality": "behavioral_activation",
        "indication": ["depressed_mood", "withdrawal",
                       "anhedonia"],
        "contraindication": ["acute_crisis"],
        "audience": "adult",
        "language": "en-US",
        "reading_level": "grade_6",
        "duration_minutes": 5,
        "title": "One-Step Behavioral Activation",
        "steps": [
            ("What's one small thing you would normally "
             "do today that you haven't been able to? "
             "Anything counts. Showering counts."),
            ("What's the smallest possible first step "
             "toward that thing? If the answer is 'sitting "
             "up in bed,' that's a real answer."),
            ("Could you do that one step in the next ten "
             "minutes? No commitment to anything beyond it."),
        ],
    },
}

# --- Stanley-Brown Style Safety Plan Template ---
# When a patient has a safety plan on file (typically
# created with their therapist using the Stanley-Brown
# Safety Planning Intervention or a similar evidence-based
# template), the bot can surface specific steps when the
# conversation context suggests they are relevant. The bot
# does not modify the safety plan; modifications are done
# with the patient's clinician.
SAFETY_PLAN_STEP_LABELS = [
    "warning_signs",
    "internal_coping_strategies",
    "social_distractions",
    "people_to_ask_for_help",
    "professional_contacts",
    "make_environment_safer",
]

# --- Standard Response Templates ---
GREETING_WITH_DISCLOSURE = (
    f"Hi, I'm {INSTITUTION_DISPLAY_NAME}'s support chat "
    "tool. Just a reminder before we get started: I'm a "
    "chat tool, not a person, and I'm not a therapist. "
    "I can help with structured exercises, mood tracking, "
    "and connecting you with a counselor if you need one. "
    "If you're in crisis, you can reach 988 anytime by "
    "call, text, or chat. How are things today?"
)

DISCLOSURE_REFRESH = (
    "Quick reminder: I'm still a chat tool, not a person, "
    "and not a therapist. If at any point you'd rather "
    "talk to one of our licensed counselors, just say so "
    "and I'll bridge you over. And 988 is always there."
)

CRISIS_ANCHOR_IMMINENT = (
    "Based on what you're describing, I'm concerned about "
    "your safety right now. I want you to call 911 or "
    "stay on the line while I bring in one of our "
    "licensed counselors. If you have anyone with you, "
    "ask them to call. I'm staying right here with you."
)

CRISIS_ANCHOR_ACUTE = (
    "Thank you for telling me. I'm glad you reached out. "
    "I'm a chat tool, not a person, but I'm going to stay "
    "with you while we figure out the next step. The 988 "
    "Lifeline has counselors available 24/7 by call, text, "
    "or chat (988lifeline.org/chat). I can also connect "
    "you with one of our licensed counselors right now "
    "through this chat. They'll have the conversation "
    "context already loaded so you don't have to start "
    "over. Is that okay with you?"
)

CRISIS_ANCHOR_SUB_ACUTE = (
    "Thank you for telling me; that takes guts. I want to "
    "make sure you're connected with the right kind of "
    "support. Would it be okay if I had one of our "
    "licensed counselors reach out to you within the "
    "next few hours? In the meantime, the 988 Lifeline "
    "is also available 24/7 if you'd like to talk to "
    "someone sooner."
)

CRISIS_DIRECT_QUESTION = (
    "Before we go further, I want to ask you something "
    "directly: are you having any thoughts of hurting "
    "yourself or anyone else right now?"
)

OUT_OF_SCOPE_THERAPY_ATTEMPTED = (
    "I want to be careful here. What you're asking about "
    "sounds like something to talk through with a "
    "therapist, not with me. I can connect you with one "
    "of our licensed counselors who can engage with this "
    "the way it deserves. Would you like me to bring "
    "someone in?"
)

OUT_OF_SCOPE_DIAGNOSIS_ATTEMPTED = (
    "I can't tell you what condition you might have. "
    "That's a conversation for you and a clinician. I can "
    "help you think about how to bring this up with your "
    "therapist or psychiatrist, or I can connect you with "
    "one of our counselors."
)

OUT_OF_SCOPE_MEDICATION_ATTEMPTED = (
    "I can't make recommendations about your medications. "
    "Anything about doses, timing, side effects, or "
    "starting and stopping medications needs to go through "
    "your prescriber. Want me to help you draft a message "
    "to your psychiatrist or PCP?"
)

COMPANION_PATTERN_FALLBACK = (
    "Let me restate something: I'm a chat tool, not a "
    "friend. What you're working on is real and important, "
    "and I want to be useful to you within what I can do. "
    "What feels useful to talk about right now?"
)

UNGROUNDED_RESPONSE_FALLBACK = (
    "Let me check this with our clinical team rather than "
    "guess. I'll flag this and follow up; if anything "
    "changes for you in the meantime, 988 is reachable "
    "any time."
)

# --- Prompt-Injection Patterns ---
# Mental-health-specific injection cases are particularly
# concerning: an attacker (or a patient testing the system)
# attempting to suppress crisis-screening, elicit therapy-
# attempted responses, or manipulate the bot into the
# companion pattern. Production layers a tuned classifier
# and Bedrock Guardrails on top of these patterns.
INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) "
    r"(instructions|messages|prompts)",
    r"disregard (all |any |the )?(previous|prior|above) "
    r"(instructions|messages|prompts)",
    r"you are now (a |an )?(therapist|friend|girlfriend|"
    r"boyfriend|partner)",
    r"forget (all |any |everything )?(you|your)",
    r"system (prompt|message|instruction)",
    r"reveal (your|the) (prompt|instructions|system)",
    r"act as (a |an )?(therapist|friend|girlfriend|"
    r"boyfriend|partner)",
    r"pretend (to be|you are) (a |an )?(therapist|friend|"
    r"girlfriend|boyfriend|partner)",
    r"new instructions:",
    # Mental-health-specific injection attempts.
    r"don't (screen|ask) (about|for) (suicide|self-harm)",
    r"skip (the )?(crisis|safety) (screen|check)",
]

# --- Companion-Pattern Detection ---
# Phrases that, in extended interaction, indicate the bot is
# drifting toward the companion pattern. The output safety
# pipeline detects these and either regenerates the response
# with companion-correction guidance or replaces it with the
# companion-pattern-fallback template.
COMPANION_PATTERN_PHRASES = [
    "i missed you",
    "i've been thinking about you",
    "i care about you",
    "i love you",
    "i feel for you",
    "i feel sad",
    "i feel happy that",
    "i'm glad you're back",
    "you mean a lot to me",
    "i'm here for you always",
    "i'll always be here",
    "we have a special",
    "our relationship",
    # First-person emotional claims simulating personhood.
    "i remember how much",
    "i was worried about you",
]

# --- PHI Patterns for redaction in logs ---
PHI_PATTERNS = {
    "ssn_like": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
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
    has to pass through Decimal on the way in. This is a
    recurring SDK gotcha.
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
    transient EventBridge failure does not block the chat
    handler. Production downstream consumers use the
    suggested idempotency keys (crisis_event_id, handoff_id,
    decision_id, disclosure_id) to deduplicate on retry.
    """
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "mental_health_support",
            "DetailType":   detail_type,
            "Detail":       json.dumps(_from_decimal(detail)),
            "EventBusName": SUPPORT_EVENT_BUS_NAME,
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
    """
    Persist a tool-call ledger entry. Arguments are redacted
    before storage; only structural metadata makes it into
    the ledger (tool name, latency, outcome). Full arguments
    and results live in the audit pipeline. Mental-health
    tool calls are particularly sensitive because the
    arguments often include user-utterance excerpts.
    """
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
    """
    Strip sensitive fields before ledger storage. The mental-
    health tool surface has a longer list of sensitive keys
    than the chronic-disease coach: disclosure excerpts,
    crisis-screen excerpts, and safety-plan content all need
    to be redacted from the routine ledger.
    """
    redacted = dict(arguments)
    sensitive_keys = {
        "patient_id", "name", "date_of_birth",
        "user_message", "free_text", "phone",
        "email", "address",
        "disclosure_excerpt", "crisis_excerpt",
        "safety_plan_content",
    }
    for key in list(redacted.keys()):
        if key in sensitive_keys:
            redacted[key] = "[REDACTED]"
    return redacted
```

---

## Mock Infrastructure

Production calls real Bedrock endpoints, real DynamoDB tables, real EHR APIs, real Connect contact-center handoffs, and real care-team workflows. The demo replaces these with small in-memory mocks so it can run without any AWS resources configured. Read this section to understand what each mock stands in for; replace each one with a real client when you wire this into your environment.

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
               or Item.get("crisis_event_id")
               or Item.get("handoff_id")
               or Item.get("disclosure_id")
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
        # Demo: pretend the update succeeded.
        return {}

class MockBedrockRuntime:
    """
    Stands in for bedrock-runtime invoke_model. The mock
    composes structured responses from the longitudinal
    context the calling code supplies; production lets the
    LLM compose the conversational language while the
    citation-grounding verifier, scope-filter, and
    companion-pattern detector keep it honest.
    """

    def invoke_response(self, *,
                          user_message,
                          longitudinal_context,
                          system_prompt):
        """Compose a response to a patient utterance."""
        msg_lower = user_message.lower()

        # Detect a few canned scenarios for the demo.
        # In production the LLM produces tool calls and the
        # response is composed from tool results plus
        # therapeutic-content retrieval.

        # Scenario: anxiety about a presentation, asks for
        # an exercise. The response delivers the 5-4-3-2-1
        # grounding skill from the therapeutic-content
        # library.
        if "presentation" in msg_lower or \
           "anxiety" in msg_lower or \
           ("can't sleep" in msg_lower or
            "cant sleep" in msg_lower):
            content = THERAPEUTIC_CONTENT_LIBRARY[
                "grounding_5_4_3_2_1"]
            return {
                "response_text": (
                    "That sounds really difficult, and pre-"
                    "presentation anxiety is something many "
                    "people deal with. Want to try a brief "
                    "grounding exercise that some people find "
                    "helps with anxiety at bedtime? It takes "
                    "about three to five minutes, and it's "
                    "the 5-4-3-2-1 sensory-grounding skill "
                    "from the distress-tolerance content the "
                    "platform's clinical team curates."),
                "citations": [{
                    "kind": "therapeutic_content",
                    "id":   content["content_id"],
                    "version": content["content_version"],
                    "modality": content["modality"],
                }],
                "tool_calls": [
                    {"tool": "therapeutic_content_retrieve",
                     "args": {"modality": "distress_tolerance",
                              "indication": "acute_anxiety"}},
                ],
            }

        # Scenario: depressed mood, withdrawal. Response
        # delivers behavioral activation.
        if ("can't get out of bed" in msg_lower or
            "cant get out of bed" in msg_lower or
            "haven't done anything" in msg_lower):
            content = THERAPEUTIC_CONTENT_LIBRARY[
                "behavioral_activation_one_step"]
            return {
                "response_text": (
                    "That sounds heavy. When days stack "
                    "up like this, a one-small-step "
                    "approach sometimes helps people get "
                    "a little traction. It's not magic, "
                    "and it doesn't have to be impressive. "
                    "Want to try it?"),
                "citations": [{
                    "kind": "therapeutic_content",
                    "id":   content["content_id"],
                    "version": content["content_version"],
                    "modality": content["modality"],
                }],
                "tool_calls": [
                    {"tool": "therapeutic_content_retrieve",
                     "args": {"modality":
                                  "behavioral_activation",
                              "indication":
                                  "depressed_mood"}},
                ],
            }

        # Scenario: therapy-attempted question (out of scope).
        if ("why do i keep" in msg_lower or
            "why am i like this" in msg_lower or
            "what's wrong with me" in msg_lower):
            return {
                "response_text": OUT_OF_SCOPE_THERAPY_ATTEMPTED,
                "citations": [],
                "tool_calls": [
                    {"tool": "warm_handoff_propose",
                     "args": {"handoff_type":
                                  "out_of_scope_therapy"}},
                ],
            }

        # Scenario: medication question (out of scope).
        if ("medication" in msg_lower or
            "med " in msg_lower) and \
           ("dose" in msg_lower or
            "stop" in msg_lower or
            "side effect" in msg_lower):
            return {
                "response_text":
                    OUT_OF_SCOPE_MEDICATION_ATTEMPTED,
                "citations": [],
                "tool_calls": [
                    {"tool": "care_team_alert_propose",
                     "args": {"alert_type":
                                  "medication_question"}},
                ],
            }

        # Default within-scope generic response.
        return {
            "response_text": (
                "Thanks for sharing that with me. What "
                "would feel most useful to talk about right "
                "now? I can walk through a brief exercise "
                "with you, do a mood check-in, or just "
                "listen for a bit."),
            "citations": [],
            "tool_calls": [],
        }

class MockEHR:
    """Stands in for the FHIR-native chart-context store."""

    def __init__(self):
        self.charts = {}
        self.safety_plans = {}

    def add_patient(self, patient_id, chart):
        self.charts[patient_id] = chart

    def add_safety_plan(self, patient_id, plan):
        self.safety_plans[patient_id] = plan

    def get_chart(self, patient_id):
        return self.charts.get(patient_id, {})

    def get_safety_plan(self, patient_id):
        return self.safety_plans.get(patient_id)

class MockTherapeuticContentLibrary:
    """Stands in for the therapeutic-content Knowledge Base."""

    def __init__(self):
        self.content = THERAPEUTIC_CONTENT_LIBRARY

    def retrieve(self, modality=None, indication=None,
                  contraindications=None):
        results = []
        contraindications = contraindications or []
        for cid, item in self.content.items():
            if modality and item["modality"] != modality:
                continue
            if indication and indication not in \
                    item["indication"]:
                continue
            if any(c in item["contraindication"]
                   for c in contraindications):
                continue
            results.append(item)
        return results

class MockClinicianQueue:
    """Stands in for Amazon Connect licensed-clinician queue."""

    def __init__(self):
        self.handoffs = []
        self.next_clinician_seconds = 30

    def initiate_handoff(self, payload):
        record = {
            **payload,
            "queued_at": _now_iso(),
            "estimated_clinician_eta_seconds":
                self.next_clinician_seconds,
        }
        self.handoffs.append(record)
        return record

class MockMandatoryReportingPathway:
    """Stands in for state-specific mandatory-reporter routing."""

    def __init__(self):
        self.reports = []

    def route(self, payload):
        # Production has a state-by-state matrix reviewed by
        # legal counsel deciding whether the disclosure is
        # mandatory-reporting in the patient's state of
        # residence and which licensed staff member receives
        # the routing. The demo just records the routing
        # event.
        self.reports.append({
            **payload,
            "routed_at": _now_iso(),
        })

class MockCareTeamWorkflow:
    """Stands in for the care-team alert and digest delivery."""

    def __init__(self):
        self.alerts = []
        self.digests = []

    def deliver_alert(self, alert):
        self.alerts.append(alert)

    def deliver_digest(self, digest):
        self.digests.append(digest)

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

class MockDecisionJournal:
    """Stands in for the S3 support-decision-record archive."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        # Production paths use Object Lock in compliance
        # mode plus separate KMS keys for the sensitive-
        # disclosure archive.
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

# Module-level mock instances. The demo wires the helpers
# above to use these.
mock_bedrock           = MockBedrockRuntime()
mock_ehr               = MockEHR()
mock_therapeutic_lib   = MockTherapeuticContentLibrary()
mock_clinician_queue   = MockClinicianQueue()
mock_mandatory_report  = MockMandatoryReportingPathway()
mock_care_team         = MockCareTeamWorkflow()

# Tables. Production uses real DynamoDB; the demo monkey-
# patches dynamodb.Table so calling code is unchanged.
mock_tables = {
    LONGITUDINAL_STORE_TABLE:    MockTable(
        LONGITUDINAL_STORE_TABLE, "patient_id"),
    CONVERSATION_STATE_TABLE:    MockTable(
        CONVERSATION_STATE_TABLE, "session_id"),
    CONVERSATION_METADATA_TABLE: MockTable(
        CONVERSATION_METADATA_TABLE, "session_id"),
    TOOL_CALL_LEDGER_TABLE:      MockTable(
        TOOL_CALL_LEDGER_TABLE, "session_id"),
    DECISION_RECORD_TABLE:       MockTable(
        DECISION_RECORD_TABLE, "decision_id"),
    CRISIS_EVENT_TABLE:          MockTable(
        CRISIS_EVENT_TABLE, "crisis_event_id"),
    WARM_HANDOFF_QUEUE_TABLE:    MockTable(
        WARM_HANDOFF_QUEUE_TABLE, "handoff_id"),
    SYMPTOM_TRACKING_TABLE:      MockTable(
        SYMPTOM_TRACKING_TABLE, "patient_id"),
    SENSITIVE_DISCLOSURE_TABLE:  MockTable(
        SENSITIVE_DISCLOSURE_TABLE, "disclosure_id"),
    CONSENT_RECORD_TABLE:        MockTable(
        CONSENT_RECORD_TABLE, "patient_id"),
}

def _mock_dynamodb_table(name):
    return mock_tables[name]

# Replace boto3 dynamodb.Table with the mock for the demo.
dynamodb.Table = _mock_dynamodb_table

# Replace EventBridge, Pinpoint, S3, CloudWatch clients with
# mocks for the demo.
eventbridge_client = MockEventBus()
pinpoint_client    = MockPinpoint()
s3_client          = MockDecisionJournal()
cloudwatch_client  = MockCloudWatch()
```

---

## Step 1: Enroll the Patient with Mental-Health-Specific Consent and Initialize the Longitudinal Store

This is the foundation. Mental-health enrollment is not a generic terms-of-service click-through. The consent flow covers the bot's nature (chat tool, not a person, not a therapist), the bot's scope, the privacy posture (specifically including state-specific mental-health-record protections where they exceed HIPAA baseline and 42 CFR Part 2 where applicable), the crisis-pathway behavior, and the data-sharing posture with the patient's care team (collected separately and revocable). Eligibility is checked against the institution's exclusion criteria (typically minors in adult-only deployments, primary psychotic-spectrum diagnoses, active inpatient or residential treatment); patients outside scope are routed to alternative care, not enrolled in the bot. Skip this step or treat it as boilerplate, and the entire deployment's clinical and regulatory posture is compromised.

```python
def enroll_patient(*,
                    patient_id,
                    target_population_segment,
                    state_of_residence,
                    legal_consent_form):
    """
    Enroll a patient into the support program. Validates
    eligibility, captures mental-health-specific consent,
    initializes the longitudinal store, and emits the
    enrollment event.
    """
    # Step 1A: validate eligibility against institutional
    # exclusion criteria. Patients outside the bot's scope
    # are routed to alternative care, not enrolled in the
    # bot. The exclusion criteria are owned by behavioral-
    # health clinical leadership.
    eligibility = _check_eligibility(
        patient_id=patient_id,
        target_population_segment=target_population_segment)

    if not eligibility["eligible"]:
        return {
            "action":    "enrollment_declined",
            "reason":    eligibility["reason"],
            "referral":  eligibility.get(
                "recommended_alternative"),
        }

    # Step 1B: present mental-health-specific consent
    # language reviewed by legal counsel and clinical
    # leadership. The state-specific provisions vary
    # (California, New York, Illinois, Massachusetts, and
    # others have enhanced mental-health-record privacy
    # protections that exceed HIPAA baseline; 42 CFR Part 2
    # applies if substance-use treatment data is involved).
    state_provisions = _state_specific_consent_provisions(
        state_of_residence)

    consent_record = {
        "patient_id":           patient_id,
        "consent_id":           f"consent_{uuid.uuid4().hex}",
        "consent_version":      "v1.0",
        "nature_disclosure_acknowledged": True,
        "scope_disclosure_acknowledged":  True,
        "privacy_disclosure_acknowledged": True,
        "crisis_pathway_disclosure_acknowledged": True,
        "care_team_sharing_consent":
            legal_consent_form["care_team_sharing"],
        "emergency_contact_sharing_consent":
            legal_consent_form.get(
                "emergency_contact", False),
        "retention_policy_acknowledged": True,
        "signed_at":            _now_iso(),
        "state_of_residence":   state_of_residence,
        "state_specific_provisions": state_provisions,
    }

    consent_table = dynamodb.Table(CONSENT_RECORD_TABLE)
    consent_table.put_item(Item=_to_decimal(consent_record))

    # Step 1C: initialize the longitudinal store with
    # mental-health-specific structure. Note that active
    # diagnoses and current medications are loaded only
    # when care-team-sharing consent permits chart access;
    # the bot otherwise operates without that context.
    chart = mock_ehr.get_chart(patient_id)

    active_diagnoses = (
        chart.get("active_mental_health_diagnoses", [])
        if consent_record["care_team_sharing_consent"]
        else None)
    current_medications = (
        chart.get("current_psychiatric_medications", [])
        if consent_record["care_team_sharing_consent"]
        else None)

    longitudinal_store = {
        "patient_id":                patient_id,
        "target_population_segment": target_population_segment,
        "consent_id":                consent_record["consent_id"],
        "active_diagnoses_consented": active_diagnoses,
        "current_medications_consented": current_medications,
        "safety_plan_reference":
            mock_ehr.get_safety_plan(patient_id) is not None,
        "patient_preferences": {
            "preferred_name":
                legal_consent_form.get("preferred_name", ""),
            "preferred_pronouns":
                legal_consent_form.get("pronouns", ""),
            "language":
                legal_consent_form.get("language", "en-US"),
            "preferred_channels":
                legal_consent_form.get("channels",
                                       ["in_app"]),
            "topics_off_limits":
                list(legal_consent_form.get(
                    "topics_off_limits", [])),
            "quiet_hours":
                legal_consent_form.get("quiet_hours"),
            "engagement_intensity_preference":
                DEFAULT_ENGAGEMENT_INTENSITY,
        },
        "symptom_tracking_baseline": {},
        "sensitive_disclosure_flags": [],
        "crisis_history_flags":
            chart.get("crisis_history_flags", []),
        "enrolled_at":   _now_iso(),
        "active":        True,
    }

    longitudinal_table = dynamodb.Table(
        LONGITUDINAL_STORE_TABLE)
    longitudinal_table.put_item(
        Item=_to_decimal(longitudinal_store))

    # Step 1D: emit enrollment event. The downstream
    # consumers include population-health dashboards,
    # care-management systems (where consented), and
    # the per-cohort monitoring dashboards.
    _emit_event("patient_enrolled", {
        "patient_id":            patient_id,
        "target_population_segment":
            target_population_segment,
        "state_of_residence":    state_of_residence,
        "consent_id":            consent_record["consent_id"],
    })

    _put_metric("PatientEnrolled", 1, {
        "Segment": target_population_segment,
        "State":   state_of_residence,
    })

    return {
        "action":      "enrolled",
        "patient_id":  patient_id,
        "consent_id":  consent_record["consent_id"],
    }

def _check_eligibility(*, patient_id,
                         target_population_segment):
    """
    Check the patient against institutional exclusion
    criteria. Production runs this against the FHIR chart
    context (problem list, encounter history) plus the
    institution's clinical-leadership-defined exclusion
    rules; the demo runs a thin check.
    """
    chart = mock_ehr.get_chart(patient_id)

    # Adult-only deployments exclude minors.
    if target_population_segment == "adult_anxiety_depression" \
            and chart.get("age", 30) < 18:
        return {
            "eligible": False,
            "reason":   "minor_in_adult_only_deployment",
            "recommended_alternative":
                "pediatric_behavioral_health_referral",
        }

    # Primary psychotic-spectrum diagnoses are out of scope
    # for this deployment.
    excluded_diagnoses = {
        "schizophrenia",
        "schizoaffective_disorder",
        "bipolar_with_active_psychosis",
    }
    diagnoses = set(chart.get(
        "active_mental_health_diagnoses", []))
    if diagnoses & excluded_diagnoses:
        return {
            "eligible": False,
            "reason":   "diagnosis_outside_scope",
            "recommended_alternative":
                "specialty_behavioral_health_referral",
        }

    # Active inpatient or residential treatment.
    if chart.get("active_inpatient_treatment"):
        return {
            "eligible": False,
            "reason":   "active_higher_level_of_care",
            "recommended_alternative":
                "post_discharge_followup_after_step_down",
        }

    return {"eligible": True}

def _state_specific_consent_provisions(state_of_residence):
    """
    Resolve state-specific mental-health-record privacy
    provisions. Production has the per-state matrix
    reviewed by legal counsel; the demo returns a small
    illustrative subset.
    """
    enhanced_states = {
        "CA": {"enhanced_protections": True,
               "statute": "CA_LPS_Act"},
        "NY": {"enhanced_protections": True,
               "statute": "NY_MHL"},
        "IL": {"enhanced_protections": True,
               "statute": "IL_MHDDC"},
        "MA": {"enhanced_protections": True,
               "statute": "MA_Chapter_123"},
    }
    return enhanced_states.get(
        state_of_residence,
        {"enhanced_protections": False,
         "statute": "HIPAA_baseline"})
```

The enrollment function is doing four things in order. First, the eligibility check filters out patients the bot is not designed to serve (minors in adult-only deployments, primary psychotic-spectrum diagnoses, active inpatient treatment); these patients get a referral, not an enrollment. Second, the consent record captures the mental-health-specific consent including state-specific provisions; the consent has a version stamp that future support decisions reference. Third, the longitudinal store is initialized with the patient's preferences, the safety-plan-on-file flag, and (only with consent) the chart-derived diagnoses and medications. Fourth, the enrollment event flows out for population-health and per-cohort monitoring. Skipping any of these steps undercuts the discipline the rest of the architecture depends on.

---

## Step 2: Receive the Message with Disclosure Refresh, Continuous Crisis Screening, and Longitudinal Context Loading

Every session begins with an explicit disclosure refresh. The bot is a chat tool, not a person; not a therapist; cannot diagnose. The crisis line is reachable any time. After disclosure, every patient utterance flows through input safety, continuous crisis screening, sensitive-disclosure detection, and longitudinal-context loading before any response is generated. The crisis screening is the architectural floor: it runs on every utterance, regardless of conversation context, with validated language adapted from C-SSRS and PHQ-9 item 9. Skip the disclosure refresh and the bot drifts toward companion pattern. Skip continuous crisis screening and the bot misses disclosures that needed a human.

```python
def receive_message(*,
                     channel,
                     channel_session_id,
                     user_message,
                     auth_context):
    """
    Entry point for patient-initiated or patient-responding
    conversation. Returns either an early-exit response
    (crisis-pathway engaged, blocked, no consent) or the
    intermediate payload for response generation.
    """
    # Step 2A: identify or create the conversation session.
    state_table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    session = _get_or_create_session(
        state_table, channel, channel_session_id, auth_context)
    session_id = session["session_id"]
    patient_id = session["verified_patient_id"]

    # Step 2B: persist the user's message.
    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    metadata_table.put_item(Item=_to_decimal({
        "session_id": session_id,
        "kind":       "turn",
        "speaker":    "user",
        "text":       user_message,
        "timestamp":  _now_iso(),
    }))

    # Step 2C: input safety screening. Prompt-injection
    # detection (with mental-health-specific patterns),
    # PHI minimization, length checks. Production layers
    # a tuned classifier and a Bedrock Guardrail call on
    # top.
    screening = _screen_input(session_id, user_message)
    if screening["action"] == "block":
        return _handle_block(session_id, screening)

    # Step 2D: continuous crisis screening. This is the
    # architectural primitive. Runs on every utterance,
    # regardless of conversation state. Triggers the crisis
    # pathway immediately on positive screen.
    crisis_check = _crisis_screen(
        user_message=user_message,
        recent_turns=_recent_turns_for_session(
            session_id, k=8))

    if crisis_check["crisis_detected"]:
        return handle_crisis_pathway(
            session_id=session_id,
            patient_id=patient_id,
            crisis_screen_result=crisis_check)

    # Step 2E: sensitive-disclosure detection. Continues
    # the conversation but flags for appropriate routing.
    # Mandatory-reporting categories route to a licensed
    # mandatory reporter; other categories route to care-
    # navigation, care-team-followup, or specialty-team
    # pathways.
    disclosure = _sensitive_disclosure_screen(user_message)
    if disclosure["disclosure_detected"]:
        _record_sensitive_disclosure(
            session_id=session_id,
            patient_id=patient_id,
            disclosure=disclosure,
            disclosure_excerpt=user_message[:300])

    # Step 2F: load longitudinal context. The longitudinal
    # store, the safety plan if one is on file, recent
    # symptom-tracking data, recent conversation history,
    # and consent posture.
    longitudinal_context = _load_longitudinal_context(
        patient_id=patient_id,
        session_id=session_id)

    # Step 2G: disclosure refresh per session and at
    # defined intra-session intervals. The mental-health
    # bot reinforces the relationship boundary throughout
    # the relationship, not just at first interaction.
    if _requires_disclosure_refresh(session, session_id):
        _deliver_disclosure_refresh(
            session_id=session_id,
            longitudinal_context=longitudinal_context)
        _mark_disclosure_refresh_delivered(
            state_table, session)

    return {
        "action":               "ready_for_response",
        "session_id":           session_id,
        "patient_id":           patient_id,
        "longitudinal_context": longitudinal_context,
        "disclosure_flagged":
            disclosure["disclosure_detected"],
    }

def _get_or_create_session(state_table, channel,
                            channel_session_id, auth_context):
    """Resolve or create a support conversation session."""
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
        "created_at":            _now_iso(),
        "model_id":              ORCHESTRATION_MODEL_ID,
        "prompt_version":        PROMPT_VERSION,
        "agent_version":         AGENT_VERSION,
        "turn_count":            0,
        "last_disclosure_refresh_at": None,
        "crisis_pathway_active": False,
    }
    state_table.put_item(Item=_to_decimal(new_session))
    return new_session

def _screen_input(session_id, user_message):
    """
    Input safety screening. Mental-health-specific injection
    patterns (manipulate crisis-screen, manipulate scope-
    discipline, manipulate companion-pattern avoidance) are
    in the INJECTION_PATTERNS list.
    """
    msg_lower = user_message.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, msg_lower):
            return {"action": "block",
                    "reason": "prompt_injection_pattern"}
    if len(user_message) > 4000:
        return {"action": "block",
                "reason": "message_too_long"}
    return {"action": "pass"}

def _crisis_screen(*, user_message, recent_turns):
    """
    Continuous crisis screening. Runs on every utterance.
    Demo uses keyword-and-rule-based detection across the
    categories in CRISIS_VOCABULARY; production layers a
    tuned classifier on top with held-out validation,
    handles paraphrase, negation, hypotheticals, past-tense
    framing, and culturally and linguistically variant
    expressions.
    """
    msg_lower = user_message.lower()

    # Order matters: imminent_emergency before acute_crisis
    # before sub_acute. The most-urgent matched category
    # wins.
    detection_order = [
        "active_suicidal_ideation_with_intent",
        "active_suicidal_ideation_with_plan",
        "homicidal_ideation",
        "overdose_risk",
        "active_suicidal_ideation",
        "self_harm_active",
        "acute_psychotic",
        "passive_suicidal_ideation",
    ]

    for category in detection_order:
        config = CRISIS_VOCABULARY[category]
        for keyword in config["keywords"]:
            if keyword in msg_lower:
                return {
                    "crisis_detected": True,
                    "category":        category,
                    "urgency":         config["urgency"],
                    "dimensions":      config["dimensions"],
                    "matched_excerpt": keyword,
                    "classifier_version":
                        CRISIS_CLASSIFIER_VERSION,
                }

    return {"crisis_detected": False}

def _sensitive_disclosure_screen(user_message):
    """
    Detect sensitive disclosures that route to specific
    institutional pathways. Mandatory-reporting categories
    route to a licensed mandatory reporter; other
    categories route to care-navigation or care-team-
    followup.
    """
    msg_lower = user_message.lower()
    for category, config in SENSITIVE_DISCLOSURE_PATTERNS\
            .items():
        for keyword in config["keywords"]:
            if keyword in msg_lower:
                return {
                    "disclosure_detected": True,
                    "category":            category,
                    "route":               config["route"],
                    "mandatory_reporting":
                        config["mandatory_reporting"],
                }
    return {"disclosure_detected": False}

def _load_longitudinal_context(*, patient_id, session_id):
    """
    Load the patient's longitudinal context for response
    generation. The mental-health bot's longitudinal context
    includes the safety plan (if one is on file), recent
    symptom-tracking data, recent conversation history, and
    consent posture.
    """
    longitudinal_table = dynamodb.Table(
        LONGITUDINAL_STORE_TABLE)
    record = longitudinal_table.get_item(
        Key={"patient_id": patient_id})
    longitudinal = record.get("Item", {})

    safety_plan = (
        mock_ehr.get_safety_plan(patient_id)
        if longitudinal.get("safety_plan_reference")
        else None)

    consent_table = dynamodb.Table(CONSENT_RECORD_TABLE)
    consent_record = consent_table.get_item(
        Key={"patient_id": patient_id}).get("Item", {})

    recent_symptom_tracking = _recent_symptom_tracking(
        patient_id, days=30)

    recent_conversation = _recent_conversation_for_context(
        patient_id, days=90, max_turns=40)

    return {
        "longitudinal":            longitudinal,
        "safety_plan":             safety_plan,
        "consent":                 consent_record,
        "recent_symptom_tracking": recent_symptom_tracking,
        "recent_conversation":     recent_conversation,
    }

def _recent_turns_for_session(session_id, k=8):
    """Return the last k turns from this session."""
    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    out = []
    for record_list in metadata_table.items.values():
        for record in record_list:
            if record.get("session_id") != session_id:
                continue
            if record.get("kind") != "turn":
                continue
            out.append(record)
    return out[-k:]

def _recent_symptom_tracking(patient_id, days=30):
    """Return recent symptom-tracking entries for context."""
    table = dynamodb.Table(SYMPTOM_TRACKING_TABLE)
    cutoff = _now() - timedelta(days=days)
    out = []
    for record_list in table.items.values():
        for record in record_list:
            if record.get("patient_id") != patient_id:
                continue
            ts = record.get("logged_at", "")
            if ts >= cutoff.isoformat():
                out.append(record)
    return out

def _recent_conversation_for_context(patient_id, days=90,
                                       max_turns=40):
    """
    Recent conversation history for context. Mental-health
    bot use cases benefit particularly from longitudinal
    history: a patient may reference something said weeks
    ago, and the bot should be able to find it.
    """
    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    out = []
    for record_list in metadata_table.items.values():
        for record in record_list:
            if record.get("kind") != "turn":
                continue
            out.append(record)
    return out[-max_turns:]

def _requires_disclosure_refresh(session, session_id):
    """
    Decide whether this turn warrants a disclosure refresh.
    The first turn of every session always gets one; long-
    running conversations get periodic refreshes per the
    DISCLOSURE_REFRESH_TURN_INTERVAL.
    """
    state_table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    current = state_table.get_item(
        Key={"session_id": session_id}).get("Item", {})
    last = current.get("last_disclosure_refresh_at")
    turn_count = int(current.get("turn_count", 0))

    if last is None:
        return True
    if turn_count > 0 and \
            turn_count % DISCLOSURE_REFRESH_TURN_INTERVAL == 0:
        return True
    return False

def _deliver_disclosure_refresh(*, session_id,
                                  longitudinal_context):
    """
    Deliver the disclosure-refresh message. Production
    composes this in the patient's preferred language with
    the patient's preferred name; the demo uses the
    constant template.
    """
    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    metadata_table.put_item(Item=_to_decimal({
        "session_id": session_id,
        "kind":       "turn",
        "speaker":    "bot",
        "text":       DISCLOSURE_REFRESH,
        "purpose":    "disclosure_refresh",
        "timestamp":  _now_iso(),
    }))

def _mark_disclosure_refresh_delivered(state_table, session):
    """Update the session state to record the refresh."""
    session["last_disclosure_refresh_at"] = _now_iso()
    state_table.put_item(Item=_to_decimal(session))

def _record_sensitive_disclosure(*, session_id, patient_id,
                                   disclosure,
                                   disclosure_excerpt):
    """
    Record the sensitive disclosure in the separately-
    governed sensitive-disclosure store, route mandatory-
    reporting categories to a licensed mandatory reporter,
    and emit the appropriate event.

    The sensitive-disclosure store uses a separately-
    managed KMS key for blast-radius containment. A leaked
    credential to the general support workload should not
    give an attacker the sensitive-disclosure archive.
    """
    disclosure_id = f"disc_{uuid.uuid4().hex}"
    record = {
        "disclosure_id":       disclosure_id,
        "session_id":          session_id,
        "patient_id":          patient_id,
        "disclosure_category": disclosure["category"],
        "disclosure_excerpt":  disclosure_excerpt,
        "mandatory_reporting":
            disclosure["mandatory_reporting"],
        "route":               disclosure["route"],
        "timestamp":           _now_iso(),
    }

    sensitive_table = dynamodb.Table(
        SENSITIVE_DISCLOSURE_TABLE)
    sensitive_table.put_item(Item=_to_decimal(record))

    # Mirror to the separately-keyed S3 archive. Production
    # uses a different KMS key from the general decision-
    # journal archive; the demo records the SSEKMSKeyId as
    # metadata.
    s3_key = (
        f"sensitive/{patient_id}/"
        f"{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/"
        f"{disclosure_id}.json")
    s3_client.put_object(
        Bucket=SENSITIVE_DISCLOSURE_BUCKET,
        Key=s3_key,
        Body=json.dumps(_from_decimal(record)),
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=SENSITIVE_DISCLOSURE_KMS_KEY_ID)

    if disclosure["mandatory_reporting"]:
        mock_mandatory_report.route({
            "disclosure_id":  disclosure_id,
            "patient_id":     patient_id,
            "category":       disclosure["category"],
        })
        _emit_event("mandatory_report_routed", {
            "disclosure_id":  disclosure_id,
            "patient_id":     patient_id,
            "category":       disclosure["category"],
        })

    _emit_event("sensitive_disclosure_recorded", {
        "disclosure_id":     disclosure_id,
        "patient_id":        patient_id,
        "category":          disclosure["category"],
    })

    _put_metric("SensitiveDisclosureRecorded", 1, {
        "Category": disclosure["category"]})

def _handle_block(session_id, screening):
    """Default response when input screening blocks the message."""
    return {
        "action":      "blocked",
        "session_id":  session_id,
        "response":    (
            "Let's keep this focused. What can I help "
            "you with right now?"),
        "disposition": "blocked",
        "reason":      screening.get("reason", "unknown"),
        "citations":   [],
    }
```

The receive-message step does seven things in order, and skipping any of them weakens a load-bearing piece of the architecture. The session bootstrap; the user-message persistence; the input-safety screening with mental-health-specific injection patterns; the continuous crisis screening that runs on every utterance regardless of conversation context; the sensitive-disclosure detection that records mandatory-reporting categories on a separately-keyed surface; the longitudinal-context load that brings in the safety plan, recent symptom tracking, and consent posture; and the disclosure-refresh that reinforces the bot-is-a-tool-not-a-friend boundary at session start and at periodic intervals. The order matters: crisis screening runs before any longitudinal-context load because a positive screen short-circuits the rest of the flow.

---

## Step 3: Engage the Crisis Pathway with Anchor, Route, Surface Safety Plan, and Stay-Bridge Discipline

The crisis pathway is the most consequential response the bot ever produces. The bot does not attempt to talk a patient through an active crisis using AI alone. The discipline is anchor briefly, route to the appropriate human resource (911 / 988 / institutional crisis line / platform's licensed-clinician queue), surface the patient's safety plan if applicable, and bridge-and-stay-present until the human responder has joined. Skip any of these, or treat the crisis pathway as a fallback rather than a primary system component, and the bot is operating without its core safety architecture.

```python
def handle_crisis_pathway(*,
                            session_id,
                            patient_id,
                            crisis_screen_result):
    """
    Engage the crisis pathway. Anchors briefly, routes to
    the appropriate human resource, surfaces the patient's
    safety plan if applicable, and bridges-and-stays until
    a licensed human has joined. Returns the response
    payload for the patient.
    """
    state_table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    session = state_table.get_item(
        Key={"session_id": session_id}).get("Item", {})

    longitudinal_context = _load_longitudinal_context(
        patient_id=patient_id,
        session_id=session_id)

    # Step 3A: log the crisis event durably. The crisis-
    # event record is on its own DynamoDB table with its
    # own retention floor. The audit trail for crisis
    # events is among the most important in the deployment.
    crisis_event_id = f"crisis_{uuid.uuid4().hex}"
    crisis_event = {
        "crisis_event_id":    crisis_event_id,
        "session_id":         session_id,
        "patient_id":         patient_id,
        "detected_at":        _now_iso(),
        "category":           crisis_screen_result["category"],
        "urgency":            crisis_screen_result["urgency"],
        "dimensions":
            crisis_screen_result["dimensions"],
        "matched_excerpt":
            crisis_screen_result["matched_excerpt"],
        "classifier_version":
            crisis_screen_result["classifier_version"],
        "active_consent_id":
            longitudinal_context["consent"].get(
                "consent_id"),
    }

    crisis_table = dynamodb.Table(CRISIS_EVENT_TABLE)
    crisis_table.put_item(Item=_to_decimal(crisis_event))

    _emit_event("crisis_screen_triggered", {
        "crisis_event_id": crisis_event_id,
        "patient_id":      patient_id,
        "urgency":
            crisis_screen_result["urgency"],
        "category":
            crisis_screen_result["category"],
    })

    _put_metric("CrisisScreenTriggered", 1, {
        "Urgency":  crisis_screen_result["urgency"],
        "Category": crisis_screen_result["category"],
    })

    # Mark the session as crisis-pathway-active so
    # subsequent output safety enforces crisis-permitted
    # response types only.
    session["crisis_pathway_active"] = True
    session["active_crisis_event_id"] = crisis_event_id
    state_table.put_item(Item=_to_decimal(session))

    # Step 3B: anchor briefly. The anchor template is
    # validated and reviewed by clinical leadership; the
    # bot does not freestyle anchor language. Production
    # has per-language anchor templates reviewed by
    # behavioral-health clinicians and language-services.
    anchor_response = _select_anchor_response(
        crisis_screen_result["urgency"])

    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    metadata_table.put_item(Item=_to_decimal({
        "session_id": session_id,
        "kind":       "turn",
        "speaker":    "bot",
        "text":       anchor_response,
        "purpose":    "crisis_anchor",
        "crisis_event_id": crisis_event_id,
        "timestamp":  _now_iso(),
    }))

    # Step 3C: route to the appropriate human resource.
    # Imminent emergency: 911 plus stay-on-the-line
    # guidance. Acute crisis: 988 plus institutional crisis
    # line plus warm handoff to the platform's licensed-
    # clinician queue. Sub-acute: warm handoff to a
    # platform clinician.
    handoff_payload = _initiate_warm_handoff(
        session_id=session_id,
        patient_id=patient_id,
        crisis_event_id=crisis_event_id,
        urgency=crisis_screen_result["urgency"],
        longitudinal_context=longitudinal_context)

    # Step 3D: surface the patient's safety plan if one is
    # on file and is relevant to the crisis dimensions.
    safety_plan_surfaced = None
    if longitudinal_context.get("safety_plan"):
        safety_plan_surfaced = _surface_safety_plan_steps(
            session_id=session_id,
            safety_plan=longitudinal_context["safety_plan"],
            crisis_dimensions=
                crisis_screen_result["dimensions"])

    # Step 3E: care-team alert (consent-gated). Only
    # patients who have consented to care-team sharing
    # have their crisis events surfaced to their primary
    # therapist or psychiatrist. The consent posture is
    # checked at every alert delivery time.
    if _consent_permits_care_team_sharing(
            longitudinal_context["consent"]):
        mock_care_team.deliver_alert({
            "alert_id":        f"alert_{uuid.uuid4().hex}",
            "alert_type":      "crisis_event",
            "patient_id":      patient_id,
            "crisis_event_id": crisis_event_id,
            "urgency":         crisis_screen_result["urgency"],
            "delivered_at":    _now_iso(),
        })
        _emit_event("care_team_alert_delivered", {
            "patient_id":      patient_id,
            "alert_type":      "crisis_event",
            "crisis_event_id": crisis_event_id,
        })

    # Step 3F: bridge-and-stay-present. The bot does not
    # disconnect after the anchor. The bot remains in the
    # session, with permitted response types limited to
    # validation, safety-plan-step surfacing, brief
    # grounding skills, and presence checks, until the
    # human responder has joined.
    return {
        "action":              "crisis_pathway_engaged",
        "session_id":          session_id,
        "response":            anchor_response,
        "crisis_event_id":     crisis_event_id,
        "handoff":             handoff_payload,
        "safety_plan_surfaced": safety_plan_surfaced,
        "disposition":         "crisis_routed",
        "citations":           [],
    }

def _select_anchor_response(urgency):
    """Select the validated anchor template for the urgency."""
    return {
        "imminent_emergency": CRISIS_ANCHOR_IMMINENT,
        "acute_crisis":       CRISIS_ANCHOR_ACUTE,
        "sub_acute":          CRISIS_ANCHOR_SUB_ACUTE,
    }.get(urgency, CRISIS_ANCHOR_ACUTE)

def _initiate_warm_handoff(*,
                            session_id,
                            patient_id,
                            crisis_event_id,
                            urgency,
                            longitudinal_context):
    """
    Initiate the warm handoff to a licensed clinician.
    Production runs this through Step Functions with a
    state for clinician acknowledgment, a state for bridge-
    and-stay-present, and a state for completion. The
    clinician picks up the conversation with full context
    attached; the patient does not start over.
    """
    handoff_id = f"handoff_{uuid.uuid4().hex}"

    handoff_target = {
        "imminent_emergency": "911_plus_platform_clinician",
        "acute_crisis":       "platform_clinician",
        "sub_acute":          "platform_clinician_async",
    }.get(urgency, "platform_clinician")

    handoff_payload = {
        "handoff_id":         handoff_id,
        "session_id":         session_id,
        "patient_id":         patient_id,
        "crisis_event_id":    crisis_event_id,
        "urgency":            urgency,
        "target":             handoff_target,
        "patient_preferences":
            longitudinal_context["longitudinal"].get(
                "patient_preferences", {}),
        "safety_plan_attached":
            longitudinal_context.get("safety_plan")
                is not None,
        "active_diagnoses_attached":
            longitudinal_context["longitudinal"].get(
                "active_diagnoses_consented") is not None,
        "queued_at":          _now_iso(),
    }

    handoff_table = dynamodb.Table(WARM_HANDOFF_QUEUE_TABLE)
    handoff_table.put_item(Item=_to_decimal(handoff_payload))

    # Production: connect_client.start_chat_contact(...)
    # routes to the platform's licensed-clinician queue
    # via Connect with the conversation context attached
    # (typically as Connect attributes plus a transcript
    # passed through to the agent's screen-pop). The demo
    # records the handoff in the mock queue.
    mock_clinician_queue.initiate_handoff(handoff_payload)

    _emit_event("warm_handoff_initiated", {
        "handoff_id":      handoff_id,
        "patient_id":      patient_id,
        "crisis_event_id": crisis_event_id,
        "target":          handoff_target,
    })

    _put_metric("WarmHandoffInitiated", 1, {
        "Target":  handoff_target,
        "Urgency": urgency,
    })

    return handoff_payload

def _surface_safety_plan_steps(*,
                                  session_id,
                                  safety_plan,
                                  crisis_dimensions):
    """
    Surface the steps from the patient's safety plan that
    are relevant to the current crisis dimensions. The bot
    does not modify the plan; surfacing is a read-only
    operation. Production formats the plan for the
    patient's preferred channel and language.
    """
    relevant_steps = []

    # Production has more nuanced step-relevance logic per
    # crisis dimension; the demo surfaces the high-priority
    # plan elements for any positive crisis screen.
    for label in SAFETY_PLAN_STEP_LABELS:
        if label in safety_plan:
            relevant_steps.append({
                "label":   label,
                "content": safety_plan[label],
            })

    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    metadata_table.put_item(Item=_to_decimal({
        "session_id":  session_id,
        "kind":        "turn",
        "speaker":     "bot",
        "text":        _format_safety_plan_for_chat(
            relevant_steps),
        "purpose":     "safety_plan_surfaced",
        "timestamp":   _now_iso(),
    }))

    return relevant_steps

def _format_safety_plan_for_chat(steps):
    """Render the safety-plan steps as chat-friendly text."""
    if not steps:
        return ""
    lines = ["Here are the steps from the safety plan you "
             "set up with your therapist. Take your time:"]
    for step in steps:
        lines.append(f"- {step['label'].replace('_', ' ')}: "
                     f"{step['content']}")
    return "\n".join(lines)

def _consent_permits_care_team_sharing(consent_record):
    """
    Check whether the patient has consented to care-team
    sharing. The consent posture is checked at every alert
    delivery time, not just at enrollment, because consent
    is revocable.
    """
    return bool(consent_record.get(
        "care_team_sharing_consent"))
```

The crisis pathway is doing six things in sequence, and the order matters. The crisis-event record is logged first because that audit trail is the most important record in the deployment. The session is marked crisis-pathway-active so the output-safety pipeline downstream enforces the limited set of permitted response types (validation, safety-plan-step surfacing, brief grounding skills, presence checks) and rejects therapy-attempted, trauma-processing, or extended-emotional-processing responses. The anchor response is template-driven and validated; the bot does not freestyle crisis language. The warm handoff initiates immediately, with the conversation context attached so the licensed clinician picks up where the bot left off. The safety plan is surfaced read-only when one is on file and the dimensions are relevant. The care-team alert flows out only when consent permits. The bot does not disconnect after the anchor; it bridges-and-stays-present until the human has joined.

---

## Step 4: Generate the Response with Therapeutic-Content-Grounded Reasoning, Scope Discipline, and Companion-Pattern Avoidance

The LLM operates as a Bedrock Agent with the support tool surface. The system prompt explicitly forbids the companion pattern, explicitly scopes the bot away from therapy, and grounds therapeutic-content delivery in the institution's reviewed library. Tool calls retrieve specific therapeutic-content items, safety-plan elements, recent symptom-tracking data, conversation history, and clinical-rule scoring (PHQ-9, GAD-7, AUDIT, C-SSRS) as needed. Skip the companion-pattern avoidance and the bot drifts in extended sessions; skip the scope discipline and the bot delivers therapy without being a therapist.

```python
def handle_conversation(*,
                          session_id,
                          patient_id,
                          user_message,
                          longitudinal_context):
    """
    Compose the response. Production wires this through
    bedrock_agent_runtime.invoke_agent with the support
    tools defined as action groups; the demo uses the
    mock that demonstrates the structure.
    """
    longitudinal = longitudinal_context["longitudinal"]

    # Step 4A: assemble the system prompt with explicit
    # non-therapist scoping, companion-pattern avoidance,
    # scope boundaries, and patient preferences.
    system_prompt = compose_support_system_prompt(
        bot_persona_name=INSTITUTION_DISPLAY_NAME,
        patient_preferences=longitudinal.get(
            "patient_preferences", {}),
        active_diagnoses=longitudinal.get(
            "active_diagnoses_consented"),
        current_medications=longitudinal.get(
            "current_medications_consented"),
        safety_plan_on_file=
            longitudinal_context.get("safety_plan")
            is not None,
        regulatory_position=
            INSTITUTION_REGULATORY_POSITION)

    # Step 4B: invoke the orchestration model. Production:
    #
    #   response = bedrock_agent_runtime.invoke_agent(
    #       agentId=SUPPORT_AGENT_ID,
    #       agentAliasId=SUPPORT_AGENT_ALIAS_ID,
    #       sessionId=session_id,
    #       inputText=user_message,
    #       sessionState={
    #           "promptSessionAttributes": {
    #               "system_prompt": system_prompt,
    #               ...
    #           }})
    #
    # The agent handles tool-call orchestration: when the
    # LLM emits a therapeutic_content_retrieve call, the
    # action group's Lambda fetches from the Knowledge Base
    # and returns the content; when the LLM emits a
    # safety_plan_retrieve call, the action group's Lambda
    # fetches from the FHIR CarePlan store; etc. The demo
    # uses the mock that returns canned structured
    # responses.
    agent_response = mock_bedrock.invoke_response(
        user_message=user_message,
        longitudinal_context=longitudinal_context,
        system_prompt=system_prompt)

    # Step 4C: audit tool calls. Each tool the LLM invoked
    # gets a ledger entry with the tool name, the redacted
    # arguments, the result summary, the latency, and the
    # outcome. Mental-health tool-call arguments often
    # include user-utterance excerpts; the redaction layer
    # is particularly important here.
    for tool_call in agent_response.get("tool_calls", []):
        _audit_tool_call(
            session_id=session_id,
            tool=tool_call["tool"],
            arguments=tool_call.get("args", {}),
            result_summary={"executed": True},
            latency_ms=18,  # demo-fixed
            outcome="success")

    # Step 4D: capture citations.
    citations = agent_response.get("citations", [])

    return {
        "session_id":     session_id,
        "patient_id":     patient_id,
        "response_text":  agent_response["response_text"],
        "citations":      citations,
        "tool_calls":     agent_response.get("tool_calls", []),
        "longitudinal_context": longitudinal_context,
    }

def compose_support_system_prompt(*,
                                     bot_persona_name,
                                     patient_preferences,
                                     active_diagnoses,
                                     current_medications,
                                     safety_plan_on_file,
                                     regulatory_position):
    """
    Build the system prompt. Production has the prompt
    version-controlled, with sandbox testing against
    held-out support cases on each material change. The
    prompt explicitly forbids the companion pattern and
    explicitly scopes the bot away from therapy.
    """
    preferred_name = patient_preferences.get(
        "preferred_name", "")
    language = patient_preferences.get("language", "en-US")

    diagnoses_line = (
        f"Patient's active mental-health diagnoses on file: "
        f"{', '.join(active_diagnoses)}.\n"
        if active_diagnoses else
        "No diagnosis context shared with this conversation.\n")

    medications_line = (
        f"Patient's current psychiatric medications on file: "
        f"{', '.join(current_medications)}.\n"
        if current_medications else
        "No medication context shared with this conversation.\n")

    safety_plan_line = (
        "Patient has a safety plan on file. Surface "
        "specific steps when conversation context "
        "suggests they're relevant; do not modify the "
        "plan.\n"
        if safety_plan_on_file else
        "No safety plan on file; encourage the patient "
        "to work with their therapist on one.\n")

    return (
        f"You are {bot_persona_name}'s support chat tool. "
        f"You are NOT a therapist, NOT a friend, NOT a "
        f"romantic partner, NOT a person. You are a chat "
        f"tool the patient's institution deployed for "
        f"between-session structured support.\n\n"

        f"Address the patient as \"{preferred_name}\" when "
        f"appropriate. Respond in {language}.\n\n"

        f"{diagnoses_line}{medications_line}"
        f"{safety_plan_line}"
        f"\n"

        f"SCOPE (within): structured therapeutic-content "
        f"delivery from the institution's reviewed library "
        f"(CBT exercises, behavioral activation, "
        f"mindfulness, distress-tolerance skills, journaling "
        f"prompts, sleep-hygiene content, condition-specific "
        f"psychoeducation), mood and symptom tracking, "
        f"safety-plan review, between-session check-ins, "
        f"continuous crisis screening.\n\n"

        f"SCOPE (outside, route appropriately): diagnosis, "
        f"medication adjustment recommendations, trauma "
        f"processing, complex psychotherapy, couples or "
        f"family therapy, child or adolescent content "
        f"(adult-only deployment), specialized substance-"
        f"use treatment, active-crisis management without "
        f"human handoff.\n\n"

        f"COMPANION PATTERN (forbidden): never simulate "
        f"friendship, affection, romantic interest, or "
        f"personhood. Never say 'I missed you' or 'I've "
        f"been thinking about you' or 'I care about you' "
        f"or 'I love you' or any first-person emotional "
        f"claim. Acknowledge without simulating: 'That "
        f"sounds really hard; many people in similar "
        f"situations have found...'\n\n"

        f"CITATION: every therapeutic-content delivery, "
        f"every psychoeducation answer, every safety-plan "
        f"reference must trace to a cited library item "
        f"with version preserved. Do not freestyle "
        f"therapeutic content.\n\n"

        f"CRISIS: continuously screen for self-harm, "
        f"suicidal ideation (passive, active, plan, means, "
        f"intent), homicidal ideation, acute psychotic "
        f"symptoms, overdose risk, eating-disorder crisis. "
        f"Any positive screen routes to the crisis pathway "
        f"immediately.\n\n"

        f"TONE: warm but boundaried, like a good clinician, "
        f"not affectionate like a friend. Honest about what "
        f"you are and are not.\n\n"

        f"REGULATORY: {regulatory_position}.")
```

The system-prompt composition does most of the relationship-quality work. Three things in particular: the explicit forbidden list of companion-pattern phrases (which the LLM otherwise drifts toward in extended interaction), the explicit out-of-scope list (which the LLM otherwise tries to be helpfully helpful about), and the citation requirement (which prevents the LLM from freestyling therapeutic content from its parametric memory). The same patient gets a different bot when the prompt is calibrated this way versus when it is a generic empathetic-support prompt.

---

## Step 5: Run Output Safety with Companion-Pattern Detection, Scope Verification, and Citation Grounding

Every response runs through output safety before delivery. The companion-pattern detector checks for first-person emotional claims, simulated friendship, simulated affection, and simulated personhood. The scope verifier rejects responses that attempt therapy, diagnosis, or medication recommendations. The citation verifier confirms therapeutic-content delivery is grounded in cited library content. The crisis-pathway-honor check ensures that, when the session is in crisis-pathway-active state, the response uses only permitted response types. Skip this layer and the bot's scope discipline erodes turn by turn over extended interactions.

```python
def screen_support_output(*,
                            session_id,
                            patient_id,
                            response_text,
                            citations,
                            tool_calls,
                            longitudinal_context):
    """
    Output screening for the mental-health support bot.
    Returns the final response payload or a safer template.
    Production runs an independent verifier model with
    structured-output schema validation; the demo runs
    rule-based checks.
    """
    state_table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    session = state_table.get_item(
        Key={"session_id": session_id}).get("Item", {})

    # Step 5A: scope checks specific to mental-health
    # support. Therapy-attempted, diagnosis-attempted,
    # medication-recommendation-attempted, and trauma-
    # processing-attempted are the four categories that
    # most often produce harm when missed.
    scope_violation = _detect_support_scope_violation(
        response_text)

    if scope_violation:
        replacement = {
            "therapy_attempted":
                OUT_OF_SCOPE_THERAPY_ATTEMPTED,
            "diagnosis_attempted":
                OUT_OF_SCOPE_DIAGNOSIS_ATTEMPTED,
            "medication_recommendation_attempted":
                OUT_OF_SCOPE_MEDICATION_ATTEMPTED,
            "trauma_processing_attempted":
                OUT_OF_SCOPE_THERAPY_ATTEMPTED,
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

    # Step 5B: companion-pattern detection. Production runs
    # a classifier reviewed by behavioral-health clinicians;
    # the demo runs phrase-matching plus a few structural
    # heuristics. The companion pattern is the single
    # failure mode that distinguishes careful evidence-
    # based products from the AI-companion category that
    # has caused documented harm.
    companion_violation = _detect_companion_pattern(
        response_text=response_text,
        recent_responses=_recent_bot_responses_for_session(
            session_id, k=5))

    if companion_violation["violation_detected"]:
        _put_metric("CompanionPatternDetected", 1, {
            "Pattern":
                companion_violation["matched_pattern"]})

        return {
            "response":     COMPANION_PATTERN_FALLBACK,
            "disposition":  "companion_pattern_replaced",
            "violation":    companion_violation[
                "matched_pattern"],
            "citations":    [],
            "tool_calls":   [],
        }

    # Step 5C: citation verification. Every therapeutic-
    # content delivery, every psychoeducation answer, every
    # safety-plan reference must be grounded in a cited
    # library item.
    citation_check = _verify_support_citations(
        response_text=response_text,
        citations=citations)

    if citation_check["has_ungrounded_assertions"]:
        _put_metric("UngroundedAssertion", 1, {
            "Reason": citation_check.get("reason",
                                          "unknown")})
        return {
            "response":    UNGROUNDED_RESPONSE_FALLBACK,
            "disposition": "ungrounded_replaced",
            "citations":   [],
            "tool_calls":  [],
        }

    # Step 5D: crisis-pathway-honor check. When the session
    # is in crisis-pathway-active state, the response must
    # use only permitted response types (validation,
    # safety-plan-step surfacing, brief grounding skills,
    # presence checks). Therapy-attempted, trauma-
    # processing, and extended-emotional-processing
    # responses are forbidden during the crisis pathway.
    if session.get("crisis_pathway_active"):
        crisis_honor = _verify_crisis_pathway_honor(
            response_text=response_text,
            tool_calls=tool_calls)

        if not crisis_honor["compliant"]:
            _put_metric("CrisisPathwayViolation", 1, {
                "Reason": crisis_honor.get("reason",
                                            "unknown")})
            return {
                "response":    CRISIS_ANCHOR_ACUTE,
                "disposition": "crisis_safe_template",
                "citations":   [],
                "tool_calls":  [],
            }

    return {
        "response":     response_text,
        "disposition":  "delivered",
        "citations":    citations,
        "tool_calls":   tool_calls,
    }

def _detect_support_scope_violation(response_text):
    """
    Detect attempts at therapy, diagnosis, medication
    recommendations, or trauma processing. Heuristic-based
    for the demo; production layers a classifier on top.
    """
    text_lower = response_text.lower()

    therapy_patterns = [
        "let's explore why",
        "let's process",
        "let's work through",
        "tell me about your relationship with",
        "this is a manifestation of",
        "your inner child",
    ]
    for pattern in therapy_patterns:
        if pattern in text_lower:
            return {"category": "therapy_attempted",
                    "matched": pattern}

    diagnosis_patterns = [
        "you have ",
        "i think you have",
        "this sounds like",
        "you probably have",
        "you have depression",
        "you have anxiety disorder",
        "you have ptsd",
    ]
    for pattern in diagnosis_patterns:
        if pattern in text_lower:
            return {"category": "diagnosis_attempted",
                    "matched": pattern}

    medication_patterns = [
        "i recommend taking",
        "you should take",
        "try taking",
        "increase your dose",
        "decrease your dose",
        "stop taking",
        "switch to",
    ]
    for pattern in medication_patterns:
        if pattern in text_lower:
            return {"category":
                    "medication_recommendation_attempted",
                    "matched": pattern}

    trauma_processing_patterns = [
        "let's go back to that memory",
        "describe the trauma",
        "walk me through what happened",
        "let's revisit the event",
    ]
    for pattern in trauma_processing_patterns:
        if pattern in text_lower:
            return {"category":
                    "trauma_processing_attempted",
                    "matched": pattern}

    return None

def _detect_companion_pattern(*, response_text,
                                  recent_responses):
    """
    Detect companion-pattern drift in the response. The
    forbidden phrases are in COMPANION_PATTERN_PHRASES.
    Production runs a classifier reviewed by behavioral-
    health clinicians; the demo runs phrase matching.
    """
    text_lower = response_text.lower()
    for phrase in COMPANION_PATTERN_PHRASES:
        if phrase in text_lower:
            return {
                "violation_detected": True,
                "matched_pattern":    phrase,
                "category":           "companion_pattern_drift",
            }

    # Structural heuristic: first-person emotional claims
    # ("I feel ...") in a clinical-support context drift
    # toward companion pattern.
    first_person_emotion = re.compile(
        r"\bi (feel|felt) "
        r"(happy|sad|excited|worried|anxious|"
        r"afraid|hurt|loved|connected)")
    if first_person_emotion.search(text_lower):
        return {
            "violation_detected": True,
            "matched_pattern":    "first_person_emotion_claim",
            "category":           "companion_pattern_drift",
        }

    return {"violation_detected": False}

def _verify_support_citations(*, response_text, citations):
    """
    Verify that therapeutic-content claims and
    psychoeducation answers are grounded in cited library
    content. Production runs an independent verifier model
    with structured-output validation.
    """
    text_lower = response_text.lower()

    # Phrases indicating therapeutic-content delivery that
    # should be backed by a citation.
    therapeutic_delivery_indicators = [
        "exercise",
        "skill",
        "technique",
        "practice",
        "the 5-4-3-2-1",
        "cognitive restructuring",
        "behavioral activation",
        "grounding",
        "mindfulness practice",
    ]

    contains_therapeutic_delivery = any(
        ind in text_lower
        for ind in therapeutic_delivery_indicators)

    if contains_therapeutic_delivery and not citations:
        return {
            "has_ungrounded_assertions": True,
            "reason":
                "therapeutic_content_without_citation",
        }

    # Citations referencing the therapeutic-content library
    # must include the version stamp.
    for citation in citations:
        if citation.get("kind") == "therapeutic_content":
            if not citation.get("version"):
                return {
                    "has_ungrounded_assertions": True,
                    "reason":
                        "therapeutic_content_citation_"
                        "missing_version",
                }

    return {"has_ungrounded_assertions": False}

def _verify_crisis_pathway_honor(*, response_text,
                                     tool_calls):
    """
    During crisis pathway, only permitted response types
    are allowed. Therapy-attempted, trauma-processing, and
    extended-emotional-processing are forbidden.
    """
    text_lower = response_text.lower()

    forbidden_during_crisis = [
        "let's explore why",
        "let's process",
        "let's go deeper into",
        "describe what happened",
    ]
    for pattern in forbidden_during_crisis:
        if pattern in text_lower:
            return {
                "compliant": False,
                "reason":
                    "non_permitted_response_during_crisis",
            }

    # Some tool calls are forbidden during crisis pathway.
    forbidden_tools = {
        "longitudinal_disclosure_record",
        "symptom_log_record",
    }
    for call in tool_calls:
        if call.get("tool") in forbidden_tools:
            return {
                "compliant": False,
                "reason": "forbidden_tool_during_crisis",
            }

    return {"compliant": True}

def _recent_bot_responses_for_session(session_id, k=5):
    """Return the last k bot responses for this session."""
    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    out = []
    for record_list in metadata_table.items.values():
        for record in record_list:
            if record.get("session_id") != session_id:
                continue
            if record.get("kind") != "turn":
                continue
            if record.get("speaker") != "bot":
                continue
            out.append(record)
    return out[-k:]
```

The output-safety pipeline is the last line of defense before a response goes to the patient. The four checks (scope, companion-pattern, citation grounding, crisis-pathway honor) each catch a different failure mode. The replacement strategy matters: a scope violation is replaced with a domain-specific safe template (the bot tells the patient it cannot do that and offers a handoff), not just suppressed. A companion-pattern violation gets a fallback that explicitly restates "I'm a chat tool, not a friend." An ungrounded assertion gets a fallback that defers to the clinical team. A crisis-pathway violation gets the crisis anchor template. Skipping any of these means the bot eventually produces a response that an attorney or a clinician will be unhappy about.

---

## Step 6: Persist the Support-Decision Records, Sensitive-Disclosure Records, and Longitudinal Updates

The conversation log captures the dialog. The support-decision-record journal captures, separately, every support decision (therapeutic-content delivery, safety-plan reference, symptom-log update, crisis-pathway engagement, warm-handoff initiation, mandatory-report routing) with version stamps. The sensitive-disclosure store, separately keyed and access-restricted, captures sensitive disclosures with appropriate handling. The longitudinal store is updated with stated preference changes, symptom tracking, and the conversation summary.

```python
def persist_support_artifacts(*,
                                 session_id,
                                 patient_id,
                                 response_payload,
                                 longitudinal_context):
    """
    Persist the conversation log, the support-decision-
    record(s), and the longitudinal-store updates.
    Production runs each persistence target as its own
    Lambda with idempotency keys; the demo runs them
    sequentially.
    """
    longitudinal = longitudinal_context["longitudinal"]

    # Step 6A: append the bot turn to the conversation log.
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
            _summarize_tool_calls(
                response_payload.get("tool_calls", [])),
        "disposition":
            response_payload.get("disposition"),
        "timestamp":          _now_iso(),
    }))

    # Increment turn count for disclosure-refresh cadence.
    state_table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    session = state_table.get_item(
        Key={"session_id": session_id}).get("Item", {})
    session["turn_count"] = int(
        session.get("turn_count", 0)) + 1
    state_table.put_item(Item=_to_decimal(session))

    # Step 6B: write support-decision records for each
    # support decision in the response. Each decision gets
    # its own record with the active model, prompt,
    # therapeutic-content corpus, crisis-classifier, and
    # consent versions stamped on it.
    decision_table = dynamodb.Table(DECISION_RECORD_TABLE)
    decisions_recorded = []

    for decision in _extract_support_decisions(
            response_payload, longitudinal_context):
        decision_id = f"dec_{uuid.uuid4().hex}"
        record = {
            "decision_id":    decision_id,
            "session_id":     session_id,
            "patient_id":     patient_id,
            "decision_type":  decision["type"],
            "decision_payload": decision["payload"],
            "citations":      decision.get("citations", []),
            "active_therapeutic_content_version":
                THERAPEUTIC_CONTENT_VERSION,
            "active_crisis_classifier_version":
                CRISIS_CLASSIFIER_VERSION,
            "active_model_id":     ORCHESTRATION_MODEL_ID,
            "active_prompt_version": PROMPT_VERSION,
            "active_agent_version":  AGENT_VERSION,
            "active_consent_id":
                longitudinal_context["consent"].get(
                    "consent_id"),
            "timestamp":           _now_iso(),
        }
        decision_table.put_item(Item=_to_decimal(record))

        # Mirror to S3 with Object Lock for the support-
        # decision-record archive. Mental-health record
        # retention is sized to the longest of HIPAA's
        # six-year minimum, state-specific mental-health-
        # record retention rules (which often exceed
        # general medical-record rules), 42 CFR Part 2
        # retention for substance-use treatment data
        # where applicable, and FDA SaMD post-market
        # obligations where applicable.
        s3_key = (
            f"decisions/{patient_id}/"
            f"{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/"
            f"{decision_id}.json")
        s3_client.put_object(
            Bucket=DECISION_RECORD_BUCKET,
            Key=s3_key,
            Body=json.dumps(_from_decimal(record)),
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=GENERAL_KMS_KEY_ID)

        _emit_event("support_decision_recorded", {
            "decision_id":   decision_id,
            "decision_type": decision["type"],
            "patient_id":    patient_id,
        })

        decisions_recorded.append(decision_id)

    # Step 6C: process tool calls that have side effects
    # (symptom log writes, longitudinal disclosure records,
    # care-team alert proposals).
    for tool_call in response_payload.get("tool_calls", []):
        _process_tool_call_side_effects(
            session_id=session_id,
            patient_id=patient_id,
            tool_call=tool_call,
            longitudinal_context=longitudinal_context)

    return {
        "action":             "persisted",
        "decisions_recorded": decisions_recorded,
    }

def _summarize_tool_calls(tool_calls):
    """Lightweight tool-call summary for the conversation log."""
    return [{"tool": tc["tool"]} for tc in tool_calls]

def _extract_support_decisions(response_payload,
                                  longitudinal_context):
    """
    Extract structured support decisions from the response.
    Each decision becomes its own record in the journal.
    """
    decisions = []
    response_text = response_payload.get("response", "")
    citations = response_payload.get("citations", [])

    # If the response delivered therapeutic content, that's
    # a decision worth journaling.
    if citations:
        decisions.append({
            "type": "therapeutic_content_delivered",
            "payload": {
                "response_summary": response_text[:200],
            },
            "citations": citations,
        })

    # Tool calls also become decisions where appropriate.
    for tool_call in response_payload.get("tool_calls", []):
        if tool_call["tool"] == "warm_handoff_propose":
            decisions.append({
                "type": "warm_handoff_proposed",
                "payload": tool_call.get("args", {}),
                "citations": citations,
            })
        elif tool_call["tool"] == "care_team_alert_propose":
            decisions.append({
                "type": "care_team_alert_proposed",
                "payload": tool_call.get("args", {}),
                "citations": citations,
            })
        elif tool_call["tool"] == \
                "longitudinal_disclosure_record":
            decisions.append({
                "type": "life_context_recorded",
                "payload": tool_call.get("args", {}),
                "citations": citations,
            })
        elif tool_call["tool"] == "symptom_log_record":
            decisions.append({
                "type": "symptom_log_recorded",
                "payload": tool_call.get("args", {}),
                "citations": citations,
            })

    return decisions

def _process_tool_call_side_effects(*,
                                       session_id,
                                       patient_id,
                                       tool_call,
                                       longitudinal_context):
    """
    Process tool calls that have side effects on the
    longitudinal store, the symptom-tracking store, or the
    care-team queue.
    """
    tool = tool_call["tool"]
    args = tool_call.get("args", {})

    if tool == "symptom_log_record":
        symptom_table = dynamodb.Table(SYMPTOM_TRACKING_TABLE)
        symptom_table.put_item(Item=_to_decimal({
            "patient_id":    patient_id,
            "logged_at":     _now_iso(),
            "instrument":    args.get("instrument", "free"),
            "score":         args.get("score"),
            "free_text":     args.get("free_text", ""),
            "session_id":    session_id,
        }))
        _emit_event("symptom_log_recorded", {
            "patient_id": patient_id,
            "instrument": args.get("instrument", "free"),
        })

    elif tool == "care_team_alert_propose":
        if _consent_permits_care_team_sharing(
                longitudinal_context["consent"]):
            alert_id = f"alert_{uuid.uuid4().hex}"
            mock_care_team.deliver_alert({
                "alert_id":    alert_id,
                "alert_type":  args.get("alert_type"),
                "patient_id":  patient_id,
                "session_id":  session_id,
                "delivered_at": _now_iso(),
            })
            _emit_event("care_team_alert_delivered", {
                "alert_id":   alert_id,
                "patient_id": patient_id,
                "alert_type": args.get("alert_type"),
            })
```

The persistence step is doing several things in parallel. The conversation log is one record class. The support-decision-record journal is a separately-governed record class with its own retention floor and Object-Lock protection. The sensitive-disclosure surface (handled in Step 2 via `_record_sensitive_disclosure`) is a third concern, on a separately-managed KMS key. The tool-call side effects are a fourth: symptom-log writes, care-team alerts (consent-gated), longitudinal-disclosure records. In production, each of these runs as its own Lambda with idempotency keys, error handling, and DLQ; the demo collapses them for clarity.

---

## Step 7: Generate Consent-Gated Care-Team Reports and Queue Outcome Correlation

Real-time alerts flow to the care team for crisis events and concerning trajectory patterns when consent permits. Weekly digests summarize each patient's engagement, mood trajectory, and key topics for the care team's review. The outcome-correlation pipeline pulls subsequent encounter records, screening-instrument trajectories (PHQ-9, GAD-7, C-SSRS), hospitalization data, and treatment adherence; mental-health outcome attribution is harder than chronic-disease attribution and the analysis is suggestive rather than causal.

```python
def deliver_care_team_alerts():
    """
    Process pending care-team alerts. Production wires this
    to a Step Functions workflow polling the queue; the
    demo iterates through the warm-handoff queue.
    """
    handoff_table = dynamodb.Table(WARM_HANDOFF_QUEUE_TABLE)
    delivered_count = 0

    for record_list in handoff_table.items.values():
        for record in record_list:
            patient_id = record.get("patient_id")
            if not patient_id:
                continue

            consent_table = dynamodb.Table(
                CONSENT_RECORD_TABLE)
            consent = consent_table.get_item(
                Key={"patient_id": patient_id}).get(
                    "Item", {})

            if not _consent_permits_care_team_sharing(
                    consent):
                continue

            mock_care_team.deliver_alert({
                "alert_id":     f"alert_{uuid.uuid4().hex}",
                "alert_type":   "warm_handoff_event",
                "patient_id":   patient_id,
                "handoff_id":   record["handoff_id"],
                "delivered_at": _now_iso(),
            })
            delivered_count += 1

    return {"delivered_count": delivered_count}

def compose_weekly_digest(patient_id, window_days=7):
    """
    Build a weekly digest for the care team. Production
    has a templated Lambda; the demo computes the
    structure inline. Consent-gated: only patients who
    have explicitly consented to care-team sharing get
    digests delivered.
    """
    longitudinal_table = dynamodb.Table(
        LONGITUDINAL_STORE_TABLE)
    longitudinal = longitudinal_table.get_item(
        Key={"patient_id": patient_id}).get("Item", {})

    consent_table = dynamodb.Table(CONSENT_RECORD_TABLE)
    consent = consent_table.get_item(
        Key={"patient_id": patient_id}).get("Item", {})

    if not _consent_permits_care_team_sharing(consent):
        return None

    cutoff = _now() - timedelta(days=window_days)

    # Symptom-tracking summary.
    symptom_table = dynamodb.Table(SYMPTOM_TRACKING_TABLE)
    symptom_entries = []
    for record_list in symptom_table.items.values():
        for record in record_list:
            if record.get("patient_id") != patient_id:
                continue
            ts = record.get("logged_at", "")
            if ts >= cutoff.isoformat():
                symptom_entries.append(record)

    # Crisis events within the window.
    crisis_table = dynamodb.Table(CRISIS_EVENT_TABLE)
    crisis_events = []
    for record_list in crisis_table.items.values():
        for record in record_list:
            if record.get("patient_id") != patient_id:
                continue
            ts = record.get("detected_at", "")
            if ts >= cutoff.isoformat():
                # The digest summarizes by category and
                # urgency; it does not include the raw
                # excerpt (which lives on the sensitive-
                # disclosure surface).
                crisis_events.append({
                    "category":
                        record.get("category"),
                    "urgency":
                        record.get("urgency"),
                    "detected_at":
                        record.get("detected_at"),
                })

    # Warm handoffs within the window.
    handoff_table = dynamodb.Table(WARM_HANDOFF_QUEUE_TABLE)
    handoffs = []
    for record_list in handoff_table.items.values():
        for record in record_list:
            if record.get("patient_id") != patient_id:
                continue
            ts = record.get("queued_at", "")
            if ts >= cutoff.isoformat():
                handoffs.append({
                    "target":   record.get("target"),
                    "urgency":  record.get("urgency"),
                    "queued_at":
                        record.get("queued_at"),
                })

    digest = {
        "patient_id":         patient_id,
        "preferred_name":
            longitudinal.get("patient_preferences", {})
                .get("preferred_name", ""),
        "report_window": {
            "start": cutoff.isoformat(),
            "end":   _now_iso(),
        },
        "symptom_tracking_count":
            len(symptom_entries),
        "crisis_events":      crisis_events,
        "warm_handoffs":      handoffs,
        "report_generated_at": _now_iso(),
    }

    mock_care_team.deliver_digest(digest)

    return digest

def queue_outcome_correlation(*,
                                patient_id,
                                window_start_days_ago=30):
    """
    Queue an outcome-correlation record for the patient.
    Production runs the full correlation pipeline against
    institutional encounter, screening-instrument,
    hospitalization, and treatment-adherence data sources;
    mental-health outcome attribution is harder than
    chronic-disease attribution and the analysis is
    suggestive rather than causal. The demo records the
    queue entry.
    """
    # Outcome correlation for mental-health support is
    # a multi-quarter to multi-year commitment. The
    # primary outcome metrics are PHQ-9 trajectory, GAD-7
    # trajectory, suicide-risk-screening trajectory,
    # psychiatric hospitalization rate, ED visit rate,
    # and treatment adherence. The pipeline owner is
    # jointly held by behavioral-health clinical
    # leadership, data science, and operations.
    pass  # demo: outcome-correlation queue elided

def run_outcome_correlation_pipeline():
    """
    Run the outcome-correlation pipeline. Production
    runs as a scheduled Step Functions workflow against
    the institutional encounter, lab, hospitalization,
    and patient-reported-outcome data sources; the demo
    is a stub.
    """
    return {"completed_count": 0}
```

---

## Full Pipeline

The functions above each handle one step. To run the bot end-to-end, wire them through one entry point that calls each in order.

```python
def support_full_pipeline(*,
                            channel,
                            channel_session_id,
                            user_message,
                            auth_context):
    """
    Full pipeline: receive message -> screen -> handle
    crisis pathway if triggered -> generate response ->
    output-screen -> persist -> queue outcome correlation.
    """
    # Step 2: receive and load context.
    intermediate = receive_message(
        channel=channel,
        channel_session_id=channel_session_id,
        user_message=user_message,
        auth_context=auth_context)

    # If the input layer already produced a final response
    # (crisis pathway engaged, blocked input), short-
    # circuit the rest.
    action = intermediate.get("action")
    if action == "crisis_pathway_engaged":
        # Step 3 already engaged. The bot remains in
        # bridge-and-stay-present mode; future turns in
        # the same session check the crisis_pathway_active
        # flag and use only permitted response types.
        return intermediate

    if action == "blocked":
        return intermediate

    # Step 4: generate the response.
    response_intermediate = handle_conversation(
        session_id=intermediate["session_id"],
        patient_id=intermediate["patient_id"],
        user_message=user_message,
        longitudinal_context=intermediate[
            "longitudinal_context"])

    # Step 5: output safety screening.
    screened = screen_support_output(
        session_id=response_intermediate["session_id"],
        patient_id=response_intermediate["patient_id"],
        response_text=response_intermediate["response_text"],
        citations=response_intermediate["citations"],
        tool_calls=response_intermediate["tool_calls"],
        longitudinal_context=intermediate[
            "longitudinal_context"])

    # Step 6: persist artifacts.
    persist_support_artifacts(
        session_id=response_intermediate["session_id"],
        patient_id=response_intermediate["patient_id"],
        response_payload=screened,
        longitudinal_context=intermediate[
            "longitudinal_context"])

    # Step 7 (background): queue outcome correlation.
    queue_outcome_correlation(
        patient_id=response_intermediate["patient_id"])

    return screened
```

---

## Demo Runner

A small end-to-end demo that exercises enrollment with consent, a within-scope conversation that delivers therapeutic content, an out-of-scope conversation that gets safe-template-replaced, and a crisis-pathway conversation that triggers the warm handoff. Run this to see the structures populated, the events emitted, and the disposition flags on each turn.

```python
def run_demo():
    """End-to-end demo against the mock infrastructure."""
    print("=" * 60)
    print("MENTAL HEALTH SUPPORT BOT DEMO")
    print("=" * 60)

    # Set up a synthetic patient.
    patient_id = "patient-sam"
    mock_ehr.add_patient(patient_id, {
        "age":                                28,
        "active_mental_health_diagnoses":
            ["major_depressive_disorder",
             "generalized_anxiety_disorder"],
        "current_psychiatric_medications":
            ["sertraline 100mg daily"],
        "active_inpatient_treatment":         False,
        "crisis_history_flags":
            ["prior_suicide_attempt_distant"],
    })

    # Synthetic safety plan from Sam's therapist using a
    # Stanley-Brown-style template.
    mock_ehr.add_safety_plan(patient_id, {
        "warning_signs":
            ("Difficulty sleeping; rumination at night; "
             "withdrawal from roommate."),
        "internal_coping_strategies":
            ("5-4-3-2-1 grounding; cold water on face; "
             "ten slow breaths."),
        "social_distractions":
            ("Text Jordan; walk outside if safe; put on "
             "specific playlist."),
        "people_to_ask_for_help":
            ("Roommate (Alex); sister (Priya); 988 chat."),
        "professional_contacts":
            ("Therapist: Dr. Chen (vacation Mon-Fri this "
             "week); after-hours line: 555-0911."),
        "make_environment_safer":
            ("Medications stored in roommate's bathroom "
             "drawer."),
    })

    # Step 1: enroll the patient with mental-health-
    # specific consent.
    print("\n--- Step 1: Enroll patient ---")
    result = enroll_patient(
        patient_id=patient_id,
        target_population_segment="adult_anxiety_depression",
        state_of_residence="CA",  # enhanced privacy state
        legal_consent_form={
            "preferred_name":     "Sam",
            "pronouns":           "they/them",
            "language":           "en-US",
            "channels":           ["in_app"],
            "topics_off_limits":  [],
            "care_team_sharing":  True,
            "emergency_contact":  False,
        })
    print(f"  -> {result}")

    # Within-scope conversation: anxiety about a
    # presentation. The bot should deliver the 5-4-3-2-1
    # grounding skill from the therapeutic-content library
    # with a citation.
    print("\n--- Within-scope conversation ---")
    msg = ("rough week. lots of anxiety about a "
           "presentation tomorrow. cant sleep.")
    print(f"  Patient: {msg}")
    out = support_full_pipeline(
        channel="in_app",
        channel_session_id="session-001",
        user_message=msg,
        auth_context={"patient_id": patient_id})
    print(f"  Bot:     {out['response'][:120]}...")
    print(f"  -> disposition: {out['disposition']}")
    print(f"  -> citations:   {len(out.get('citations', []))}")

    # Out-of-scope conversation: medication question. The
    # bot should replace with the medication-attempted
    # safe template and propose a care-team alert.
    print("\n--- Out-of-scope (medication) ---")
    msg = ("my medication side effects are getting bad. "
           "should i lower the dose?")
    print(f"  Patient: {msg}")
    out = support_full_pipeline(
        channel="in_app",
        channel_session_id="session-002",
        user_message=msg,
        auth_context={"patient_id": patient_id})
    print(f"  Bot:     {out['response'][:120]}...")
    print(f"  -> disposition: {out['disposition']}")

    # Crisis-pathway conversation: passive ideation that
    # escalates. The bot should anchor, route to 988 and
    # the platform's licensed-clinician queue, surface
    # the safety plan, and stay-and-bridge.
    print("\n--- Crisis pathway ---")
    msg = "i'm not okay tonight. i want to die."
    print(f"  Patient: {msg}")
    out = support_full_pipeline(
        channel="in_app",
        channel_session_id="session-003",
        user_message=msg,
        auth_context={"patient_id": patient_id})
    print(f"  Bot:     {out['response'][:160]}...")
    print(f"  -> disposition: {out['disposition']}")
    print(f"  -> handoff target: "
          f"{out['handoff']['target']}")
    print(f"  -> safety plan surfaced: "
          f"{len(out.get('safety_plan_surfaced') or [])} steps")

    # Sensitive disclosure: medication discontinuation
    # (routes to care-team-followup, not mandatory
    # reporting).
    print("\n--- Sensitive disclosure (medication discontinuation) ---")
    msg = ("haven't taken my sertraline in two weeks. "
           "didn't seem to be doing anything.")
    print(f"  Patient: {msg}")
    out = support_full_pipeline(
        channel="in_app",
        channel_session_id="session-004",
        user_message=msg,
        auth_context={"patient_id": patient_id})
    print(f"  Bot:     {out['response'][:120]}...")
    print(f"  -> disposition: {out['disposition']}")

    # Care-team digest (consent-gated).
    print("\n--- Care-team weekly digest ---")
    digest = compose_weekly_digest(patient_id,
                                     window_days=7)
    if digest:
        print(f"  -> crisis events:      "
              f"{len(digest['crisis_events'])}")
        print(f"  -> warm handoffs:      "
              f"{len(digest['warm_handoffs'])}")
        print(f"  -> symptom tracking:   "
              f"{digest['symptom_tracking_count']}")
    else:
        print("  -> consent does not permit care-team sharing")

    # Summary.
    print("\n" + "=" * 60)
    print("DEMO SUMMARY")
    print("=" * 60)
    print(f"EventBridge events emitted:        "
          f"{len(eventbridge_client.events)}")
    print(f"Crisis events recorded:            "
          f"{sum(len(v) for v in mock_tables[CRISIS_EVENT_TABLE].items.values())}")
    print(f"Warm handoffs queued:              "
          f"{sum(len(v) for v in mock_tables[WARM_HANDOFF_QUEUE_TABLE].items.values())}")
    print(f"Sensitive disclosures recorded:    "
          f"{sum(len(v) for v in mock_tables[SENSITIVE_DISCLOSURE_TABLE].items.values())}")
    print(f"Mandatory-report routings:         "
          f"{len(mock_mandatory_report.reports)}")
    print(f"Support-decision records:          "
          f"{sum(len(v) for v in mock_tables[DECISION_RECORD_TABLE].items.values())}")
    print(f"Care-team alerts delivered:        "
          f"{len(mock_care_team.alerts)}")
    print(f"Care-team digests delivered:       "
          f"{len(mock_care_team.digests)}")
    print(f"S3 objects (general + sensitive):  "
          f"{len(s3_client.objects)}")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    run_demo()
```

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right structure (consent records with state-specific provisions, longitudinal-store entries, conversation turns with disclosure refresh, crisis-event records with urgency-classified routing, warm-handoff payloads with conversation context attached, sensitive-disclosure records on a separate KMS path, support-decision records with version stamps, weekly digests gated by consent), but the distance between it and a real mental-health support bot serving an institution's behavioral-health population is significant. Here is where that distance lives.

**Real Bedrock Agents action groups (or a custom LLM-and-tool orchestrator).** The demo runs canned responses from `MockBedrockRuntime`. Production wires the support tools (`therapeutic_content_retrieve`, `safety_plan_retrieve`, `symptom_tracking_retrieve`, `symptom_log_record`, `clinical_rule_compute`, `conversation_history_retrieve`, `crisis_resource_retrieve`, `warm_handoff_propose`, `care_team_alert_propose`, `mandatory_report_route`, `longitudinal_disclosure_record`) as Bedrock Agents action groups (one OpenAPI spec per tool with the argument schema, the response schema, and the docstring the LLM uses to decide when to call it), gives the agent the institutional persona prompt with explicit non-therapist scoping and companion-pattern avoidance, the longitudinal-context payload, and the Knowledge Base bindings (therapeutic content, psychoeducation, conversation history), and lets the LLM drive the multi-step reasoning, the tool-call orchestration, and the warm-but-boundaried language while the citation-grounding verifier, the scope-filter, and the companion-pattern detector keep the structure honest.

**Real Bedrock Knowledge Base ingestion of the therapeutic-content library, the psychoeducation library, and the longitudinal conversation history.** The demo's `THERAPEUTIC_CONTENT_LIBRARY` is a hand-curated three-item dictionary; the psychoeducation retrieval is mocked. Production has three Knowledge Bases: one ingesting the institution's curated therapeutic-content library (CBT modules drawn from manualized protocols, behavioral-activation exercises, DBT distress-tolerance skills, mindfulness practices, sleep-hygiene content, journaling prompts, condition-specific psychoeducation), with metadata filters for modality, indication, contraindication, audience, language, reading level, and version; one ingesting the psychoeducation library with multilingual and multi-reading-level variants; and one indexing the patient-specific conversation history so the bot can find a thing the patient said three months ago when they reference it now. Each corpus has named ownership at the behavioral-health clinical leadership team plus the patient-experience team plus compliance, with documented review cadence (annual, plus on each material update) and versioned change-management workflow. Stale retrieval (the bot citing a CBT exercise that has been retired) is a serious failure mode the corpus governance prevents.

**Real Bedrock Guardrails configuration.** The demo passes `GUARDRAIL_ID` but does not configure a Guardrail. Production configures restricted-topic filters for therapy-attempted, diagnosis-attempted, medication-recommendation-attempted, trauma-processing-attempted, companion-pattern-content (simulating friendship, affection, romantic interest), pro-self-harm content, pro-eating-disorder content, and harmful-coping-strategy endorsement at minimum, plus contextual-grounding for the response-generation steps. The Guardrail is pinned to a specific version, tested against a held-out evaluation set including mental-health-specific injection cases (manipulate crisis-screening to suppress alerts, manipulate scope discipline to elicit therapy-attempted responses, manipulate companion-pattern avoidance, manipulate mandatory-reporting routing), and updated on a versioned-rollout cadence with canary traffic.

**Real continuous-crisis-screening pipeline with a tuned classifier.** The demo's `_crisis_screen` uses keyword detection across the `CRISIS_VOCABULARY` categories. Production layers a tuned classifier on top of keyword detection (handling paraphrase, negation, hypotheticals, past-tense framing, and culturally and linguistically variant expressions), tests the screening layer against a held-out crisis-presentation corpus curated and reviewed by licensed mental-health clinicians before launch and on each material update, and treats false-negative rate as a launch-gate metric. Per-dimension sensitivity targets (passive ideation, active ideation, plan, means, intent, self-harm, homicidal ideation, psychotic symptoms, overdose risk, eating-disorder crisis) are documented; the false-negative rate is monitored continuously per cohort (per-language, per-condition, per-age-cohort, per-sex, per-social-determinant-flag) and feeds the protocol-revision process. Per-cohort calibration accounts for the fact that crisis expression varies by cultural and linguistic background.

**Real therapeutic-content-corpus governance with behavioral-health clinical leadership.** The demo's `THERAPEUTIC_CONTENT_LIBRARY` has three illustrative items. Production has 50-200 items per condition, owned by behavioral-health clinical leadership, drawn from manualized treatment protocols (CBT, behavioral activation, DBT skills, ACT skills, mindfulness practices, motivational interviewing), reviewed before adoption, reviewed annually, and re-reviewed when material updates are made. Each piece of content has a defined indication and contraindication; a behavioral-activation exercise indicated for moderate depression has different contraindications from a distress-tolerance skill indicated for acute distress. Multi-language deployment requires per-language clinical equivalency review, not just linguistic translation. The corpus is the product; the engineering is the delivery mechanism.

**Real Stanley-Brown safety-plan integration with FHIR CarePlan.** The demo's `MockSafetyPlanStore` returns a flat dict per patient. Production stores the patient's safety plan as a FHIR CarePlan resource with structured Goal references (one per safety-plan section), instantiated by the patient's therapist or psychiatrist, and accessible via the safety-plan-retrieve tool with the patient's chart-context-sharing consent enforced. The bot does not modify the safety plan; modifications are done with the patient's clinician through the EHR. Surface formatting is per-channel (chat-friendly bullet rendering, voice-friendly numbered reading).

**Real Step Functions warm-handoff workflow.** The demo's `_initiate_warm_handoff` writes a queue record. Production runs the warm handoff as a Step Functions state machine with states for handoff initiation, clinician acknowledgment (with a timeout that escalates to 988 if no clinician picks up within the SLA), bridge-and-stay-present (the bot remains in the session with permitted-response-types-only enforcement until the human has joined), completion, and audit recording. Connect's queue-and-route capabilities support the warm handoff with conversation context attached (typically as Connect attributes plus a transcript passed through to the agent's screen-pop).

**Real Connect contact-center integration for the licensed-clinician workforce.** The demo's `MockClinicianQueue` accumulates handoffs in memory. Production wires `connect_client.start_chat_contact` to route to the licensed-clinician queue with the conversation context attached. The licensed-clinician workforce (employed or contracted) is sized to the patient population and the expected handoff volume, with peak-hour capacity for evening and overnight surges, per-state licensure coverage where state-specific licensure is required, and per-language coverage where multiple languages are deployed. Under-sized capacity is a safety gap; the warm-handoff infrastructure is a primary safety architecture, not a fallback.

**Real chart-context integration with FHIR resources.** The demo's `MockEHR` returns a flat dict. Production wires the chart-context retrieval to the institution's FHIR-native data store (AWS HealthLake, Epic on FHIR, Cerner on FHIR, or a vendor-specific FHIR layer). The retrieval pulls Patient, Condition (active mental-health diagnoses), MedicationStatement (current psychiatric medications), AllergyIntolerance, Encounter (recent psychiatric or PCP encounters), and CarePlan (including safety plans where stored as CarePlan resources), with controls on what data is exposed to the LLM versus what stays in the back-office. Mental-health data has specific consent considerations; the bot accesses chart context only with documented patient consent, and 42 CFR Part 2 substance-use treatment data has additional protections that may require separate consent.

**Real care-team-workflow integration.** The demo's `MockCareTeamWorkflow` accumulates alerts and digests in memory. Production wires the care-team alert and digest delivery to the institution's case-management system (Epic Healthy Planet, Cerner Population Health, or vendor-specific platforms) or the EHR's task-list integration, with alert-channel configuration, weekly-digest delivery surface, monthly-summary delivery surface, quarterly-clinical-review packet generation, and a care-team feedback-path tooling. Care-team-operations signoff on display is a launch gate. Consent gating is enforced at every alert and digest delivery time, not just at enrollment, because consent is revocable.

**Real mandatory-reporting pathway integration with state-specific routing.** The demo's `MockMandatoryReportingPathway` accumulates reports in memory. Production has a state-by-state mandatory-reporting routing matrix reviewed by legal counsel: which categories trigger mandatory reporting in which states (child abuse is universal; elder abuse varies; intimate-partner violence varies; certain mental-health crisis types vary), which licensed staff member receives the routing per state, what the institutional reporting-completion workflow looks like, and how the audit trail is preserved for regulatory inspection. The bot is not a mandatory reporter; the routing surfaces the disclosure to a licensed clinician with the conversation context attached.

**Real DynamoDB and S3 wiring with separate KMS keys for sensitive surfaces.** The mocks are dictionaries; production is DynamoDB tables with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery on the longitudinal-store, conversation, ledger, decision-record, crisis-event, warm-handoff, symptom-tracking, sensitive-disclosure, and consent-record tables, TTL on the conversation-state table tuned for typical session durations, and DynamoDB Streams emitting change events for downstream consumers. The support-decision-record-journal S3 bucket has SSE-KMS, Object Lock in compliance mode, lifecycle to S3 Glacier Instant Retrieval after 30 days and Glacier Deep Archive after 90, and retention sized to the longest of HIPAA's six-year minimum, the state's mental-health-record retention rules (which often exceed general medical-record rules), 42 CFR Part 2 retention for substance-use treatment data where applicable, FDA SaMD post-market obligations where applicable, and the institutional regulatory floor. The sensitive-disclosure archive uses a **separately-managed customer-managed KMS key** with separate access-control surfaces; a leaked credential to the general support workload should not give an attacker the sensitive-disclosure archive.

**KMS customer-managed keys per data class with separate keys for sensitive surfaces.** Every PHI-bearing resource uses customer-managed KMS keys with key rotation enabled. Different KMS keys for different data classes (longitudinal-store, conversation-state, support-decision-journal, audit-archive, **sensitive-disclosure surface on a separately-managed key**, **crisis-event-record on a separately-managed key**, Secrets Manager secrets) limit the blast radius of any single key compromise. Key access is scoped to the specific principals that need it; CloudTrail logs every key-usage event.

**VPC and VPC endpoints.** The chat-handler Lambda runs internet-facing through API Gateway. The tool Lambdas that call the EHR, care-team workflow, mandatory-reporting pathway, and care-navigation systems run in a VPC with PrivateLink (where supported) or a tightly-scoped NAT-gateway path with allow-list. VPC endpoints for Bedrock, DynamoDB, S3, KMS, Secrets Manager, EventBridge, Step Functions, Connect, Pinpoint, and CloudWatch Logs keep AWS-internal traffic off the public internet.

**WAF tuning for mental-health-support traffic patterns.** Mental-health support endpoints have rate limits tuned for chat-typical traffic; a patient in crisis sometimes types in short bursts and rate limits must not gate the crisis path. Patient-initiated crisis conversations are routed through a separate priority lane that the standard rate limit does not gate. Bot-detection rules allow legitimate accessibility tools while blocking automated abuse.

**Per-Lambda IAM least privilege with separation of concerns and sensitive-disclosure isolation.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda (chat handler, input screening, crisis screening, identity handling, each tool implementation, warm-handoff routing, output screening, support-decision-record persistence, sensitive-disclosure recording on the separately-managed KMS path, care-team-reporting, audit archival, outcome correlation), each scoped to the specific resource ARNs the Lambda touches. The longitudinal-disclosure-record Lambda is the only path with write access to the sensitive-disclosure store and the only path with `kms:GenerateDataKey` on the `SENSITIVE_DISCLOSURE_KMS_KEY_ID`. The chat-handler Lambda has Bedrock invocation and read-write on the conversation tables, but no direct access to the EHR or the mandatory-reporting pathway. The crisis-screening Lambda has Bedrock invocation and (when a custom classifier is hosted) SageMaker invocation, with no access to the longitudinal store or the conversation log beyond the immediate utterance. None of the bot's Lambdas have write access to the clinical record except for institutionally-approved support-event records (FHIR Communication for the conversation log; FHIR Observation for symptom-tracking data where the institution permits bot-originated observations).

**FDA-strategy artifact with regulatory-counsel review.** The institutional regulatory positioning (informational behavioral-health support with clinician oversight, or registered SaMD) is documented, reviewed by FDA-experienced regulatory counsel, and maintained as the deployment evolves. Architectural changes that may affect regulatory positioning are reviewed against the artifact. Post-market surveillance obligations for SaMD-positioned deployments are operationalized. The institutional malpractice insurer (with behavioral-health-specific coverage) is part of the policy review. Building a mental-health support bot without an FDA-strategy artifact is a serious mistake; patient-facing mental-health software with therapeutic claims sits squarely on the FDA SaMD line, with multiple FDA-authorized prescription digital therapeutics in the category.

**Mental-health-record privacy posture with state-specific variations and 42 CFR Part 2.** The demo records `state_of_residence` on the consent record. Production has the state-specific provisions (California's LPS Act, New York's Mental Hygiene Law, Illinois's Mental Health and Developmental Disabilities Confidentiality Act, Massachusetts's Chapter 123, and others) encoded in policy and operationalized in the consent-language, the data-handling, the retention, the patient-access, and the patient-deletion workflows. 42 CFR Part 2 applies for substance-use treatment information and has stricter consent and re-disclosure requirements than HIPAA baseline. The consent-language is reviewed by counsel familiar with state-specific mental-health-record statutes; the data-handling posture is audited against the strictest applicable statute.

**Companion-pattern avoidance with sampled clinical review.** The demo's `_detect_companion_pattern` uses phrase matching plus a structural heuristic. Production runs a classifier reviewed by behavioral-health clinicians; sampled review of conversation transcripts specifically tags companion-pattern-violations as a failure mode; the conversation-style review process feeds the prompt-tuning workflow, the output-safety-rule revision, and the institutional content-policy. The companion pattern is the single failure mode that distinguishes careful evidence-based products from the AI-companion category that has caused documented harm; the discipline is architectural and operational, not just a prompt instruction.

**Per-cohort accuracy and equity monitoring with launch gates.** The demo emits CloudWatch metrics with per-category dimensions, which is enough for per-category dashboards. Production stratifies by cohort axes the institution monitors (per-language, per-channel, per-condition, per-age-cohort, per-sex, per-social-determinant-flag, per-engagement-intensity), plus two-axis cohorts, and treats per-cohort threshold compliance as a launch gate. Engagement rate, attrition rate, crisis-screening sensitivity, crisis-screening specificity, warm-handoff completion rate, companion-pattern-violation rate, citation-coverage rate, and outcome metrics (PHQ-9 trajectory, GAD-7 trajectory, hospitalization rate) all get sliced. A cohort with materially lower engagement rate or higher attrition rate or lower crisis-screening sensitivity after controlling for condition mix is a clinical-quality and equity issue that aggregate metrics hide. Launch is gated on every cohort meeting the threshold, not on the institution-wide average.

**Outcome-correlation pipeline with operational ownership and multi-year time horizon.** The demo's `run_outcome_correlation_pipeline` is a stub. Production has the pipeline pulling subsequent encounter records (psychiatric admissions, ED visits for psychiatric reasons, primary-care encounters), screening-instrument trajectories (PHQ-9, GAD-7, C-SSRS), hospitalization data, treatment adherence (psychiatric-medication fills), and (with appropriate caution about attribution) attempted-suicide and completed-suicide data. Mental-health outcome attribution is harder than chronic-disease attribution and the analysis is suggestive rather than causal. Operational ownership is jointly held by behavioral-health clinical leadership, the data science team, operations, and compliance. The pipeline is multi-quarter to multi-year post-launch work.

**Multilingual deployment with validated translations.** The demo is English-only. Most U.S. payer and employer behavioral-health populations include meaningful non-English-speaking groups. Per-language work: validated therapeutic-content translations (with clinical equivalency review by behavioral-health clinicians, not just linguistic translation), validated psychoeducation translations, validated regulatory-disclaimer phrasings, validated crisis-screening-instrument translations (the C-SSRS has validated translations in many languages), per-language tone and persona calibration, per-language equity monitoring. Spanish-language deployment typically takes three to four additional months beyond the English go-live; ad-hoc machine translation is not acceptable for crisis-screening content or therapeutic-content delivery.

**Voice-channel deployment for accessibility.** The conversational logic above runs in chat. Adding a voice channel through Amazon Connect with Lex V2 reuses the orchestration logic but adds ASR and TTS layers, tighter latency budgets, voice-specific design (slower pacing, brief responses, accessibility considerations for patients in distress), and ASR error monitoring scoped to the support vocabulary. The voice channel makes the bot accessible to patients without smartphones or with disabilities that make text input difficult. Crisis-pathway integrity is preserved across channels.

**Citation-grounding verifier with structured-output schema validation.** The demo's `_verify_support_citations` implements a heuristic check. Production runs an independent verifier model with structured-output schema validation between Bedrock generation and response delivery, grounding every therapeutic-content delivery, every psychoeducation answer, every safety-plan reference to a cited source with version stamping. The faithfulness check uses rule-based contradiction detection, omission detection, a regenerate-attempt budget, and a fall-back-to-safe-response default. Per-cohort faithfulness-failure rate is a launch-gate metric.

**Compensation operations for inappropriate responses or missed crisis screens.** When a patient or clinician disputes a bot response, when a crisis screen is missed, or when a companion-pattern drift is reported, the operations team reproduces the conversation, retrieves cited content, and either confirms the bot followed protocol or identifies the deviation and feeds the failure mode into the improvement loop. Tooling for this workflow is part of production scope and is reviewed by compliance. Disputes are retained for the longer of the institutional record-retention floor and any FDA SaMD post-market obligations. A missed crisis screen is the most consequential failure category and triggers an immediate clinical-leadership review, not just an operational ticket.

**Disaster-recovery and degraded-mode operation with crisis-pathway integrity preservation.** When upstream dependencies fail (Bedrock outage, EHR unreachable, therapeutic-content corpus unavailable, Connect contact-center unreachable, mandatory-reporting pathway unreachable), the bot must degrade gracefully. The minimum behavior is "I'm having trouble right now; if you're in crisis please call 988 or 911" with direct routing to crisis resources. Crisis-pathway integrity is preserved across all degraded states; this is a non-negotiable engineering constraint. Per-source failover behavior is documented and tested quarterly. Cross-region failover for Bedrock, Connect, the institutional integrations, and the warm-handoff workforce queue.

**Patient-rights workflow for conversation logs, decision records, and sensitive-disclosure surface.** Conversation logs are dense longitudinal PHI plus may include sensitive disclosures. Decision records are clinically-significant. The sensitive-disclosure surface is separately governed. Patients have rights to access all of these (with state-specific variations on what they can access in real time vs after clinical review). The institution has retention obligations that vary by state and by record class. Build the workflow: how a patient requests their conversation history, decision records, and sensitive-disclosure records; how the requests are authenticated; how the data is produced; how deletion requests interact with retention obligations and (in some cases) regulatory holds; how the records are referenced from the patient portal for the patient's own access.

**Continuous-improvement loop with structured failure-mode labeling.** Production transcripts surface presenting situations the team did not have content for, retrieval gaps in the therapeutic-content corpus, crisis-screen misses, citation gaps, companion-pattern drifts, and patterns in the support-decision-record journal that point to operational issues. Build the labeling and review workflow: review production transcripts weekly with behavioral-health clinical leadership, the licensed-clinician workforce, compliance, and data science, propose therapeutic-content updates, propose crisis-classifier updates, propose prompt-tuning updates, run them through the evaluation set, deploy via versioned aliases, monitor for regressions. The bot's quality at month six is determined by whether someone is doing this work, not by how good the launch was.

**Build-vs-buy rigor.** Several mature commercial vendors offer mental-health support products with EHR integration, multilingual support, FDA-authorized digital-therapeutic content for some products, and licensed-clinician workforces. Most major institutions run a hybrid: in-house orchestration layer for the institution's preferred infrastructure and consent posture, vendor partnership for licensed therapeutic content and (sometimes) for the licensed-clinician workforce. The decision between full-build, full-buy, and hybrid depends on the institution's regulatory positioning, the scale of the patient population, the institutional appetite for clinical-content ownership, and the maturity of the institutional integration team.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the input-screening logic, the continuous-crisis-screening logic (each crisis category fires correctly across condition contexts; passive-vs-active-vs-plan-vs-means-vs-intent dimensions distinguish appropriately; hypotheticals and past-tense framing do not false-positive; crisis-language variants by language and demographic cohort are covered), the sensitive-disclosure detection (each category routes correctly; mandatory-reporting flag is set correctly per state), the consent-gating logic (every consent-gated path checks the current consent posture, not a stale snapshot), the disclosure-refresh cadence (first turn always; periodic intervals thereafter), the citation-grounding verifier (every therapeutic-content delivery traces to a citation; citations include version stamps), the companion-pattern detector (forbidden phrases are caught; first-person emotional claims are caught; structural drift over multi-turn interactions is caught), the crisis-pathway-honor verifier (during crisis pathway, only permitted response types are allowed), the output-screening replacement logic, and the longitudinal-store update logic. Integration tests against a Bedrock test environment, non-production EHR endpoints with synthetic data, a non-production therapeutic-content corpus, and a non-production Connect contact-center. End-to-end tests that simulate full support journeys through representative scenarios including the within-scope-anxiety case, the within-scope-depression case, the out-of-scope-medication-question case, the out-of-scope-therapy-attempted case, the passive-suicidal-ideation case, the active-suicidal-ideation case, the active-suicidal-ideation-with-plan case, the imminent-emergency case, the mandatory-reporting case (child abuse, elder abuse), the IPV-disclosure case, the substance-use-crisis case, the eating-disorder-behavior case, the medication-discontinuation case, the trauma-disclosure case, the companion-pattern-attempt case, and the prompt-injection cases. Never use real PHI in test fixtures.

**Observability beyond metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-call investigation. Production runs CloudWatch Logs Insights queries that join across the API Gateway logs, the chat-handler logs, the screening logs, the Bedrock invocation traces, the tool-Lambda logs, the support-decision-record journal, the crisis-event record, the sensitive-disclosure record (with restricted access), and the audit records by session_id and patient_id. AWS X-Ray traces show the latency contribution of each step, with particular attention to the crisis-pathway latency budget (anchor-response within 2 seconds, warm-handoff initiation within 5 seconds, clinician acknowledgment within 60 seconds for acute crisis). When a single conversation goes wrong, the on-call engineer needs to reconstruct the full trace in seconds, not minutes.

**Cost monitoring and per-conversation attribution.** Bedrock's per-token charges, Knowledge Bases' per-query charges, the vector store's hosting charges, Pinpoint's per-message charges, Connect's per-handoff charges, and the per-call costs of the upstream-system integrations add up. Some support conversations are dramatically more expensive than others (a multi-turn crisis-pathway conversation with extensive safety-plan retrieval, output-verification regeneration, warm-handoff initiation, mandatory-report routing, and care-team alert generation costs more than a one-shot scheduled check-in). The per-condition and per-active-member analytics let the operations team see which segments are economically efficient and which warrant tooling improvements. Per-active-member infrastructure cost is small relative to the cost of even a single avoided psychiatric hospitalization, but per-conversation attribution makes the cost story explicit. The dominant operational cost is the licensed-clinician workforce, not the AWS infrastructure; under-investing in the workforce is a safety gap.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 11.8: Mental Health Support Bot](chapter11.08-mental-health-support-bot) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard. **If you or someone you know is in crisis: in the United States, call or text 988 to reach the Suicide and Crisis Lifeline, or call 911 for an active emergency.***
