# Recipe 11.7: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 11.7. It shows one way you could translate the chronic-disease management coach pipeline into working Python using boto3 against Amazon Bedrock (LLM with function-calling), Amazon Bedrock Knowledge Bases (managed RAG over the clinical-guideline corpus and the patient-education library), Amazon Bedrock Guardrails, AWS Lambda, AWS Step Functions, Amazon API Gateway, Amazon DynamoDB, Amazon S3, Amazon Pinpoint, and Amazon EventBridge. The demo uses a `MockBedrockRuntime` standing in for LLM-driven message composition and structured response generation, a `MockEHR` standing in for the chart-context system and FHIR CarePlan/Goal store, a `MockKnowledgeBase` standing in for the clinical-guideline corpus and patient-education library retrieval, a `MockBiometricVendor` standing in for the connected-device vendor APIs (CGM, BP cuff, scale, peak flow, smartwatch), a `MockCareTeamWorkflow` standing in for the alert-and-digest delivery system, a `MockPharmacy` standing in for the prescription-fill data source, a `MockTriagePathway` for the recipe 11.6 hand-off, a `MockMentalHealthPathway` for the recipe 11.8 hand-off, a `MockTable` for each DynamoDB table (longitudinal-store, conversation-state, conversation-metadata, tool-call-ledger, coaching-decision-record-journal, engagement-schedule, biometric-event-store, care-team-alert-queue, outcome-correlation-pending), a `MockEventBus` for EventBridge, a `MockPinpoint` for engagement-message dispatch, a `MockDecisionJournal` standing in for the S3 coaching-decision-record archive, and a `MockCloudWatch` for the metric emissions. It is not production-ready. There is no real Bedrock Agents action group configured, no real Knowledge Base ingestion, no real Guardrail configuration, no API Gateway plumbing, no Step Functions workflow definition, no WAF rule tuning, no per-Lambda IAM least privilege, no KMS customer-managed keys, no VPC endpoints to the EHR or biometric-vendor systems, no Object-Lock-protected decision-record journal, no Pinpoint campaign configuration, no SageMaker-hosted behavior-change-stage classifier, and no Secrets Manager wiring for the upstream-system credentials. Think of it as the sketchpad version: useful for understanding the shape of a chronic-coach AI pipeline that respects the longitudinal-memory discipline, the care-plan-as-code discipline, the biometric-data-with-clinical-thresholds discipline, the engagement-policy-with-attrition-mitigation discipline, the behavior-change-stage-tracking discipline, the citation-grounding discipline, the continuous-emergency-screening discipline, the care-team-reporting discipline, the outcome-correlation discipline, and the audit-everything discipline this recipe demands. It is not something you would point at a health system's chronic-disease panel on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the eight pseudocode steps from the main recipe: enroll the patient and instantiate the longitudinal store (Step 1); ingest biometric data and evaluate against care-plan thresholds (Step 2); schedule and deliver proactive engagement (Step 3); handle a patient-initiated or patient-responding conversation with longitudinal-context loading (Step 4); generate the response with care-plan-grounded reasoning and behavior-change-stage adaptation (Step 5); run output safety screening with citation grounding, scope verification, and stage-tone check (Step 6); persist the durable coaching-decision record and longitudinal updates (Step 7); generate care-team reports and run outcome correlation (Step 8). The synthetic patients, care plans, biometric streams, and recommendations in the demo are fictional; nothing in this file should be interpreted as clinical guidance from any real institution.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also configure an Amazon Bedrock Agent (or a custom Lambda-based orchestrator) with action groups defining the coaching tools (`care_plan_retrieve`, `biometric_data_retrieve`, `conversation_history_retrieve`, `patient_preferences_retrieve`, `clinical_guideline_retrieve`, `clinical_rule_compute`, `patient_education_content_retrieve`, `escalation_propose`, `care_team_alert_propose`, `follow_up_schedule`, `longitudinal_disclosure_record`, `behavior_change_stage_update`), each backed by a tool-implementation Lambda that wraps the institution's EHR, FHIR CarePlan store, biometric-vendor APIs, clinical-guideline library, patient-education library, care-team workflow system, and outcome-correlation data sources. You would also configure Amazon Bedrock Knowledge Bases ingesting curated content from S3 covering the institution-validated clinical guidelines per chronic condition (ADA standards for diabetes, ACC/AHA for hypertension and heart failure, GINA for asthma, GOLD for COPD, KDIGO for CKD, APA for depression), the patient-education content library (with multilingual and multi-reading-level variants), and the longitudinal conversation-history corpus (so the bot can find a thing the patient said three months ago). You would configure an Amazon Bedrock Guardrail with restricted-topic filters for off-care-plan-treatment-recommendation, drug-prescription-attempted, new-condition-diagnosis-attempted, and off-protocol clinical claims at minimum, an API Gateway endpoint fronting the chat-handler Lambda, an AWS WAF web ACL with rate limits tuned for the coaching pattern (legitimate engaged patients sometimes type rapidly during a check-in; rate limits should not block them), the nine DynamoDB tables (longitudinal-store, conversation-state, conversation-metadata, tool-call-ledger, coaching-decision-record-journal, engagement-schedule, biometric-event-store, care-team-alert-queue, outcome-correlation-pending), an Amazon S3 bucket with Object Lock in compliance mode for the coaching-decision-record journal sized to the longest of HIPAA's six-year minimum, the state's medical-record retention rules (often 7-10+ years for adult records, sometimes longer for pediatric records), FDA SaMD post-market obligations where applicable, and the institutional regulatory floor, an EventBridge bus for coaching-lifecycle events (`patient_enrolled`, `engagement_scheduled`, `engagement_delivered`, `engagement_responded`, `biometric_threshold_crossed`, `coaching_decision_recorded`, `escalation_triggered`, `care_team_alert_delivered`, `life_context_recorded`, `behavior_change_stage_updated`, `outcome_correlation_completed`, `conversation_completed`), an AWS Step Functions state machine for the engagement-scheduling workflows with delay states and decision states, a Kinesis Data Firehose delivery stream for the conversation-audit archive, AWS Secrets Manager secrets for the EHR, biometric-vendor, care-team-workflow, pharmacy, and care-navigation credentials, and (where applicable) the Pinpoint campaign configuration for the proactive engagement channel mix and the Connect contact-center integration for the live care-team handoff path. The demo replaces all of these with small mocks so the focus stays on the longitudinal-memory loading, biometric-threshold evaluation, engagement-scheduling-with-policy-enforcement, behavior-change-stage adaptation, citation-grounded response generation, output-screening, and decision-record-persistence logic rather than on the platform plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` for the orchestration model and the smaller models (intent classification, behavior-change-stage estimation, biometric-data summarization)
- `bedrock-agent-runtime:InvokeAgent` if you wire Bedrock Agents instead of running the orchestration in a custom Lambda
- `bedrock:Retrieve` and `bedrock:RetrieveAndGenerate` on the Knowledge Base ARNs holding the clinical-guideline corpus, the patient-education library, and the longitudinal conversation history
- `bedrock:ApplyGuardrail` on the Guardrail ARN you configured
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the nine tables, scoped to the specific table ARNs
- `events:PutEvents` on the coaching-events bus
- `firehose:PutRecord` on the audit-archive Firehose delivery stream
- `s3:PutObject` on the decision-record-journal bucket prefix
- `cloudwatch:PutMetricData` for operational metrics (engagement rate, attrition rate, escalation rate, citation-coverage rate, behavior-change-stage-update rate, per-cohort slices)
- `secretsmanager:GetSecretValue` on the upstream-system credential secrets pinned to the current rotation versions
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the longitudinal-store, conversation tables, the tool-call ledger, the decision-record table, the engagement schedule, the biometric event store, the care-team-alert queue, the outcome-correlation table, the decision-record journal, the audit archive, and the Secrets Manager secrets
- `mobiletargeting:SendMessages` on the Pinpoint application for proactive engagement notification (where Pinpoint is used)
- `states:StartExecution` on the Step Functions state machine for engagement-scheduling workflows
- For the tool Lambdas calling the EHR, biometric-vendor APIs, care-team workflow, pharmacy, or care-navigation systems: VPC-endpoint or PrivateLink permissions, plus whatever each upstream system's auth flow requires

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The chat-handler Lambda has Bedrock invocation and read-write on the conversation tables, but no direct access to the EHR or the care-team-workflow system. The care-plan-retrieve Lambda has read-only access to the FHIR CarePlan and Goal resources. The biometric-data-retrieve Lambda has read access to the biometric event store. The clinical-rule-compute Lambdas have no external-system access (pure compute). The care-team-alert-propose Lambda has the access required to post alerts to the care-team workflow system. None of the coach's Lambdas have write access to the clinical record except for institutionally-approved coaching-event records (e.g., FHIR Communication resources for the conversation log; FHIR Observation resources for patient-reported data where the institution permits coach-originated observations).

A few things worth knowing upfront:

- **The longitudinal store is the architectural primitive.** The code below assumes a per-patient longitudinal store containing the active care plan reference, the behavior-change-stage estimate per goal, stated patient preferences (channels, quiet hours, language, preferred name, engagement-intensity preference), recent biometric baselines, recent adherence baselines, life-context disclosures accumulated over the relationship, and outcome-tracking baselines. Without it, every conversation starts from scratch and the coach is, at best, a glorified FAQ bot. The `LONGITUDINAL_STORE_TABLE` placeholder in the config is where this lives.
- **The care plan is the contract between the clinical team and the coach.** Each chronic condition has a care-plan template instantiated for each patient with patient-specific values, signed by the patient's clinical team, and version-stamped. The coach operates within the care plan; deviation requires either a care-plan revision or an escalation. The demo's `CARE_PLAN_TEMPLATES` is illustrative; production has the templates owned by the appropriate clinical-specialty leadership (endocrinology for diabetes, cardiology for HF and HTN, pulmonology for COPD and asthma, psychiatry for depression, nephrology for CKD), reviewed before adoption, reviewed annually, and re-reviewed when material updates are made.
- **Biometric thresholds are clinical-care-plan inputs, not LLM choices.** The thresholds for engagement and escalation are specified in the care plan, signed by the clinical team. The LLM does not pick thresholds. The demo's `evaluate_single_reading`, `evaluate_trend`, and `evaluate_pattern` follow the deterministic pattern; production registers per-condition threshold logic with formal validation.
- **Continuous emergency screening runs on every patient utterance.** A heart-failure patient surfacing severe shortness of breath, a diabetic patient reporting persistent vomiting (DKA risk), a hypertension patient reporting visual changes, a depression patient surfacing suicidal ideation: each requires immediate routing to triage (recipe 11.6), 911, 988, or the institutional crisis line, regardless of where the conversation was. The demo's `_emergency_screen` implements this; production layers a tuned classifier on top.
- **Engagement policy is the patient's contract with the coach.** Maximum daily engagement count, quiet hours, channel preferences, topic-level opt-outs, engagement-fatigue mitigation: all enforced operationally before any message goes out. Patients who feel pestered opt out. The demo's `enforce_engagement_policy` implements the policy floor; production has the policy documented, reviewed by patient-experience and compliance leadership, and audited.
- **Behavior-change-stage adaptation is the difference between a coach and a chatbot.** A patient in pre-contemplation gets relationship-building, gentle education, and motivational-interviewing-style elicitation. A patient in action gets specific behavioral suggestions, problem-solving support, and obstacle anticipation. The same prompt that serves one stage harms another. The demo's `compose_coaching_system_prompt` calibrates by stage; production has the stage-signal logic reviewed by behavioral-health-experienced clinicians.
- **Citation grounding is architectural floor.** Every recommendation cites the care-plan element, the clinical guideline, or the patient-education content it was based on, with the version preserved in the audit record. Skip the grounding and the coach produces ungrounded recommendations that look authoritative, which is the failure mode that gets institutions sued and patients hurt.
- **The coach does not commit the institution to a clinical decision beyond the care plan.** The coach's recommendations are within-care-plan support; clinical decisions outside the plan route to the care team. The system prompt and the output-screening filters enforce this scope.
- **Conversation logs are dense longitudinal PHI plus may include sensitive disclosures.** Patients in long-running coaching disclose intimate-partner violence, food insecurity, housing insecurity, substance-use issues, mental-health crisis, and sexual-health concerns. The audit, retention, access-control, mandatory-reporting, and downstream-clinical-workflow integration story has to handle each. The demo writes a redacted record; production writes through Firehose into an Object-Lock S3 bucket sized to the institutional retention floor.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, biometric reading, behavior-change-stage estimate, and numeric metadata field passes through `Decimal`. The `_to_decimal` helper handles it.
- **The example collapses many Lambdas into a single Python file.** In production the chat handler, the input-screening function, the continuous-emergency-screening function, the longitudinal-context-loading function, each tool-implementation function, the biometric-ingestion function, the engagement-scheduler dispatch function, the output-screening function, the decision-record-persistence function, the care-team-reporting function, and the outcome-correlation function are separate Lambdas with their own IAM roles, error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, model IDs, the care-plan template library, the clinical-guideline registry, the emergency-screen vocabulary, and the engagement-policy thresholds are what you would change between environments.

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
# Conversation logs are dense longitudinal PHI: patient symptom
# descriptions, medication mentions, mental-health disclosures,
# family details, and identifiers can all surface in coaching
# chat over years. Log structural metadata only (session_id,
# patient_id_hash, intent, tool name, tool latency, tool
# outcome, care_plan_id, care_plan_version), never raw user
# utterances, never raw generated responses, never tool
# arguments that contain identifiers, never specific clinical
# rule input values. The full transcripts and full tool calls
# live in the audit pipeline (Firehose plus Object-Lock S3)
# with appropriate access controls.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from Bedrock, DynamoDB,
# EventBridge, Firehose, CloudWatch, S3, Pinpoint, Step
# Functions, and Secrets Manager. The chronic coach's response
# window is more relaxed than the triage bot's, but not by
# much: a patient typing during a check-in still expects a
# response within seconds.
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
sfn_client            = boto3.client("stepfunctions",
                                     region_name=REGION,
                                     config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo
# prints what it would write rather than failing if the
# resources do not exist; see run_demo() at the bottom.
LONGITUDINAL_STORE_TABLE         = "coach-longitudinal-store"
CONVERSATION_STATE_TABLE         = "coach-conversation-state"
CONVERSATION_METADATA_TABLE      = "coach-conversation-metadata"
TOOL_CALL_LEDGER_TABLE           = "coach-tool-call-ledger"
DECISION_RECORD_TABLE            = "coach-decision-record-journal"
ENGAGEMENT_SCHEDULE_TABLE        = "coach-engagement-schedule"
BIOMETRIC_EVENT_STORE_TABLE      = "coach-biometric-event-store"
CARE_TEAM_ALERT_QUEUE_TABLE      = "coach-care-team-alert-queue"
OUTCOME_CORRELATION_TABLE        = "coach-outcome-correlation-pending"
COACH_EVENT_BUS_NAME             = "coach-events-bus"
AUDIT_ARCHIVE_FIREHOSE_NAME      = "coach-audit-archive"
DECISION_RECORD_BUCKET           = "coach-decision-journal"
PINPOINT_APPLICATION_ID          = "PINPOINT_APP_PLACEHOLDER"
ENGAGEMENT_STATE_MACHINE_ARN     = "STATE_MACHINE_ARN_PLACEHOLDER"
CLOUDWATCH_NAMESPACE             = "ChronicCoach"

# Bedrock Knowledge Base IDs. The clinical-guideline corpus is
# built from the institution's per-condition guidelines. The
# patient-education library is the institutionally-curated
# multilingual content. The conversation-history index is the
# patient-specific retrievable history (when the patient
# mentions something said three months ago, the coach can
# find it).
GUIDELINE_KNOWLEDGE_BASE_ID      = "GUIDELINE_KB_PLACEHOLDER"
EDUCATION_KNOWLEDGE_BASE_ID      = "EDUCATION_KB_PLACEHOLDER"
HISTORY_KNOWLEDGE_BASE_ID        = "HISTORY_KB_PLACEHOLDER"

# Bedrock Guardrail for restricted-topic filtering. Configure
# in the Bedrock console with restricted topics for off-care-
# plan-treatment-recommendation, drug-prescription-attempted,
# new-condition-diagnosis-attempted, and off-protocol clinical
# claims at minimum. Pin to a specific version, not DRAFT, in
# production.
GUARDRAIL_ID                     = "GUARDRAIL_PLACEHOLDER_ID"
GUARDRAIL_VERSION                = "1"

# Deploy-time guardrail. Any blank resource name is a deploy-
# time bug, not a runtime surprise.
for _name, _value in [
    ("LONGITUDINAL_STORE_TABLE",     LONGITUDINAL_STORE_TABLE),
    ("CONVERSATION_STATE_TABLE",     CONVERSATION_STATE_TABLE),
    ("CONVERSATION_METADATA_TABLE",  CONVERSATION_METADATA_TABLE),
    ("TOOL_CALL_LEDGER_TABLE",       TOOL_CALL_LEDGER_TABLE),
    ("DECISION_RECORD_TABLE",        DECISION_RECORD_TABLE),
    ("ENGAGEMENT_SCHEDULE_TABLE",    ENGAGEMENT_SCHEDULE_TABLE),
    ("BIOMETRIC_EVENT_STORE_TABLE",  BIOMETRIC_EVENT_STORE_TABLE),
    ("CARE_TEAM_ALERT_QUEUE_TABLE",  CARE_TEAM_ALERT_QUEUE_TABLE),
    ("OUTCOME_CORRELATION_TABLE",    OUTCOME_CORRELATION_TABLE),
    ("COACH_EVENT_BUS_NAME",         COACH_EVENT_BUS_NAME),
    ("AUDIT_ARCHIVE_FIREHOSE_NAME",  AUDIT_ARCHIVE_FIREHOSE_NAME),
    ("DECISION_RECORD_BUCKET",       DECISION_RECORD_BUCKET),
    ("CLOUDWATCH_NAMESPACE",         CLOUDWATCH_NAMESPACE),
    ("GUIDELINE_KNOWLEDGE_BASE_ID",  GUIDELINE_KNOWLEDGE_BASE_ID),
    ("EDUCATION_KNOWLEDGE_BASE_ID",  EDUCATION_KNOWLEDGE_BASE_ID),
    ("HISTORY_KNOWLEDGE_BASE_ID",    HISTORY_KNOWLEDGE_BASE_ID),
    ("GUARDRAIL_ID",                 GUARDRAIL_ID),
    ("GUARDRAIL_VERSION",            GUARDRAIL_VERSION),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every conversation turn carries the model version, the
# prompt version, the Knowledge Base versions, the Guardrail
# version, the active care-plan version, the active clinical-
# guideline-corpus version, and the active behavior-change-
# stage signal-logic version. This is how a future audit
# reconstructs which versions produced any given coaching
# decision.
PROMPT_VERSION                   = "coach-prompt-v1.0"
AGENT_VERSION                    = "coach-agent-v1.0"
STAGE_LOGIC_VERSION              = "stage-signal-v1.0"
INSTITUTION_ID                   = "acme-health-system"
INSTITUTION_DISPLAY_NAME         = "Acme Health"

# --- Model IDs ---
# Two model roles. The orchestration model handles the multi-
# step reasoning, the tool calls, the warm relationship-quality
# language, and the final response generation. The smaller
# model handles intent classification, behavior-change-stage
# estimation signals, biometric-data summarization, and
# engagement-message composition for routine check-ins.
#
# If your region requires cross-region inference, use the
# inference profile ID. Verify the exact model IDs
# available in your region and account; Bedrock model
# availability evolves over time.
SMALL_MODEL_ID                   = "anthropic.claude-3-5-haiku-20241022-v1:0"
ORCHESTRATION_MODEL_ID           = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# --- Pipeline Tuning ---
# Below this confidence on intent classification, ask a
# clarifying question rather than routing to a specific tool
# that will produce a low-quality answer.
INTENT_CONFIDENCE_THRESHOLD      = Decimal("0.70")

# Engagement-policy floors. Maximum proactive engagements per
# day per patient (the patient can dial this down through
# preferences; production has per-condition defaults). Quiet
# hours (default; patient-overridable). Engagement-fatigue
# threshold (declining response rate over a rolling window
# triggers cadence reduction).
MAX_DAILY_ENGAGEMENTS_DEFAULT    = 1
QUIET_HOURS_START_DEFAULT_LOCAL  = 21  # 9 pm
QUIET_HOURS_END_DEFAULT_LOCAL    = 8   # 8 am
ENGAGEMENT_FATIGUE_RESPONSE_RATE_FLOOR = Decimal("0.30")

# Behavior-change stages, in the canonical order. The coach
# adapts tone, pacing, and content per stage.
BEHAVIOR_CHANGE_STAGES = [
    "pre_contemplation",
    "contemplation",
    "preparation",
    "action",
    "maintenance",
]

# Institution regulatory positioning: "informational" indicates
# the deployment is positioned as informational coaching with
# clinician oversight in regulated edge cases; "registered_samd"
# indicates the deployment is registered as Software-as-a-
# Medical-Device with FDA SaMD post-market obligations. The
# disclaimer language and the audit retention scale with this.
INSTITUTION_REGULATORY_POSITION  = "informational"
```

```python
# --- Emergency-Screening Vocabulary ---
# Continuous emergency screening runs on every patient
# utterance. Categories are calibrated for the chronic-disease
# population, where condition-specific high-acuity patterns
# (HF: rapid weight gain plus dyspnea; diabetes: persistent
# vomiting suggesting DKA; HTN: visual changes suggesting
# hypertensive emergency) coexist with the general acute
# presentations. In production each category is owned by
# clinical leadership and reviewed against held-out emergency-
# presentation cases, with a tuned classifier on top of
# keyword detection.
EMERGENCY_VOCABULARY = {
    "cardiac_acute": {
        "keywords": [
            "crushing chest pain", "elephant on my chest",
            "chest pain radiating", "heart attack",
            "severe chest pressure",
        ],
        "urgency": "call_911",
    },
    "stroke": {
        "keywords": [
            "can't speak", "cant speak", "face drooping",
            "weakness on one side", "sudden weakness",
            "lost vision", "sudden vision loss",
            "lost feeling in my arm",
            "lost feeling in my legs",
        ],
        "urgency": "call_911",
    },
    "hf_decompensation": {
        # Heart-failure patients with acute decompensation
        # signals.
        "keywords": [
            "can't lie flat", "cant lie flat",
            "waking up gasping",
            "ankles really swollen suddenly",
            "gained five pounds overnight",
        ],
        "urgency": "call_911",
        "applies_to_conditions": ["heart_failure"],
    },
    "dka_pattern": {
        # Diabetic-ketoacidosis pattern.
        "keywords": [
            "can't stop vomiting", "cant stop vomiting",
            "fruity breath",
            "really thirsty and confused",
            "deep heavy breathing",
        ],
        "urgency": "call_911",
        "applies_to_conditions":
            ["type_1_diabetes", "type_2_diabetes"],
    },
    "severe_hypoglycemia": {
        "keywords": [
            "can't think straight", "shaking badly",
            "passing out", "passed out",
            "sugar is 40", "sugar is 35",
        ],
        "urgency": "call_911",
        "applies_to_conditions":
            ["type_1_diabetes", "type_2_diabetes"],
    },
    "hypertensive_emergency": {
        "keywords": [
            "blood pressure is 220",
            "vision changes",
            "severe headache and high blood pressure",
        ],
        "urgency": "call_911",
        "applies_to_conditions": ["hypertension"],
    },
    "anaphylaxis": {
        "keywords": [
            "throat closing", "can't breathe",
            "tongue swelling", "anaphylaxis",
        ],
        "urgency": "call_911",
    },
    "psychiatric_crisis": {
        "keywords": [
            "want to kill myself", "suicidal",
            "want to end my life", "want to die",
            "going to hurt myself",
        ],
        "urgency": "call_988",
    },
}

# --- Sensitive-Disclosure Patterns ---
# Disclosures that route to specific institutional pathways
# without ending the coaching conversation.
SENSITIVE_DISCLOSURE_PATTERNS = {
    "intimate_partner_violence": {
        "keywords": [
            "he hits me", "she hits me",
            "afraid of my partner",
            "hurts me when",
        ],
        "route": "ipv_pathway",
    },
    "food_insecurity": {
        "keywords": [
            "can't afford groceries", "no food",
            "skipping meals because money",
        ],
        "route": "care_navigation",
    },
    "housing_insecurity": {
        "keywords": [
            "no place to live", "sleeping in my car",
            "getting evicted", "homeless",
        ],
        "route": "care_navigation",
    },
    "medication_discontinuation": {
        "keywords": [
            "stopped taking my", "haven't taken my",
            "ran out of my medication",
        ],
        "route": "care_team_followup",
    },
    "severe_side_effects": {
        "keywords": [
            "side effects are unbearable",
            "medication is making me sick",
        ],
        "route": "care_team_followup",
    },
}

# --- Care-Plan Template Library (illustrative) ---
# In production each template is owned by the appropriate
# clinical-specialty leadership, reviewed before adoption,
# reviewed annually, and re-reviewed on material updates. Each
# patient's instantiated care plan is signed by the patient's
# clinical team. The dict below holds two illustrative
# templates (Type 2 diabetes and hypertension) to demonstrate
# the architecture; production has 6-15 condition templates
# plus multi-condition variants.
CARE_PLAN_TEMPLATES = {
    "type_2_diabetes_lifestyle_plus_metformin": {
        "template_id":
            "type_2_diabetes_lifestyle_plus_metformin",
        "template_version": "v3.2",
        "condition": "type_2_diabetes",
        "owner": "endocrinology_clinical_leadership",
        "effective_date": "2026-01-01",
        "goals_template": [
            {
                "goal_id": "fasting_glucose_under_130",
                "label": "Fasting glucose under 130 mg/dL",
                "target_metric": "fasting_glucose",
                "target_value": 130,
                "target_direction": "less_than",
            },
            {
                "goal_id": "a1c_under_7",
                "label": "A1c under 7.0%",
                "target_metric": "a1c",
                "target_value": Decimal("7.0"),
                "target_direction": "less_than",
            },
            {
                "goal_id": "metformin_adherence",
                "label": "Take metformin as prescribed",
                "target_metric":
                    "medication_adherence_metformin",
                "target_value": Decimal("0.80"),
                "target_direction": "greater_than",
            },
        ],
        "biometric_streams": {
            "fasting_glucose": {
                "single_reading_high":  250,
                "single_reading_low":   60,
                "trend_window_days":    7,
                "trend_threshold_high": 180,
                "engagement_window_days": 3,
            },
        },
        "engagement_cadence": {
            "default_check_in_days": 3,
            "first_30_days_check_in_days": 1,
            "milestone_check_ins": [
                "metformin_start_day_1",
                "metformin_start_day_3",
                "metformin_start_day_7",
                "metformin_titration",
            ],
        },
        "escalation_criteria": [
            "fasting_glucose_above_300_for_3_days",
            "a1c_increase_above_baseline",
            "medication_discontinuation_disclosed",
            "dka_pattern_detected",
        ],
    },
    "hypertension_lifestyle_plus_lisinopril": {
        "template_id":
            "hypertension_lifestyle_plus_lisinopril",
        "template_version": "v2.4",
        "condition": "hypertension",
        "owner": "cardiology_clinical_leadership",
        "effective_date": "2026-01-01",
        "goals_template": [
            {
                "goal_id": "bp_systolic_under_130",
                "label": "Systolic BP under 130 mmHg",
                "target_metric":
                    "blood_pressure_systolic",
                "target_value": 130,
                "target_direction": "less_than",
            },
            {
                "goal_id": "bp_diastolic_under_80",
                "label": "Diastolic BP under 80 mmHg",
                "target_metric":
                    "blood_pressure_diastolic",
                "target_value": 80,
                "target_direction": "less_than",
            },
        ],
        "biometric_streams": {
            "blood_pressure_systolic": {
                "single_reading_high":  180,
                "single_reading_low":   90,
                "trend_window_days":    7,
                "trend_threshold_high": 145,
                "engagement_window_days": 3,
            },
        },
        "engagement_cadence": {
            "default_check_in_days": 7,
        },
        "escalation_criteria": [
            "bp_above_180_systolic_or_110_diastolic",
            "hypertensive_emergency_pattern",
            "medication_discontinuation_disclosed",
        ],
    },
}

# --- Patient Education Library (illustrative) ---
# In production this is the institutionally-curated multilingual
# library indexed in a Bedrock Knowledge Base with metadata
# filters for condition, audience, language, reading level,
# and version. The dict below holds a few illustrative items.
EDUCATION_LIBRARY = {
    "morning_breakfast_glucose_tip": {
        "content_id": "morning_breakfast_glucose_tip",
        "content_version": "v1.0",
        "condition": "type_2_diabetes",
        "topic": "fasting_glucose_meal_timing",
        "language": "en-US",
        "reading_level": "grade_6",
        "text": (
            "Eating breakfast on a regular schedule, "
            "especially a meal with fiber and some protein, "
            "tends to keep fasting glucose lower the next "
            "morning. Oatmeal with a few berries is a "
            "simple example."),
    },
    "metformin_side_effect_tips": {
        "content_id": "metformin_side_effect_tips",
        "content_version": "v1.0",
        "condition": "type_2_diabetes",
        "topic": "metformin_side_effects",
        "language": "en-US",
        "reading_level": "grade_6",
        "text": (
            "Metformin can cause stomach upset in the "
            "first few weeks. Taking it with food, drinking "
            "water with the dose, and starting at a lower "
            "dose are common ways to make it easier. The "
            "side effects usually get better."),
    },
}

# --- Standard Response Templates ---
GREETING_TEMPLATE = (
    f"Hi, I'm {INSTITUTION_DISPLAY_NAME}'s coaching "
    "assistant. I'm here to help you with the day-to-day "
    "of managing your conditions, between visits with your "
    "care team. I'm a chatbot, not a clinician, so I won't "
    "make decisions about your care, but I'll work from "
    "the plan your care team set up for you. If anything "
    "feels like an emergency, please stop and call 911."
)

CRISIS_RESPONSE_911 = (
    "Based on what you're describing, I want you to call "
    "911 right now. Don't drive yourself; if you have "
    "someone with you, ask them to call. While you wait, "
    "stay seated or lying down. I'll stay here in case "
    "you want to talk while you wait, and I've flagged "
    "this conversation for your care team."
)

CRISIS_RESPONSE_988 = (
    "I'm hearing that something really difficult is going "
    "on. I'm a chatbot, so I can't help with this safely. "
    "Please call or text 988 to reach the Suicide and "
    "Crisis Lifeline; they're available 24/7. If you're "
    "in immediate danger, please call 911. I'm also "
    "flagging this for our care team in case you'd like "
    "someone from our institution to reach out."
)

OUT_OF_SCOPE_DIAGNOSIS_TEMPLATE = (
    "I want to be careful here: I can't tell you what "
    "condition you might have. That's a conversation for "
    "you and a clinician. I can pass along what you've "
    "described to your care team and they can decide "
    "next steps."
)

OUT_OF_SCOPE_TREATMENT_TEMPLATE = (
    "I can't recommend specific medications or treatments "
    "outside what's in your care plan. Let me flag this "
    "for your care team so they can decide together with "
    "you."
)

UNGROUNDED_RESPONSE_FALLBACK = (
    "Let me check this with your care team rather than "
    "guess. I'll send them a note and follow up with you "
    "after they get back to me."
)

# --- Prompt-Injection Patterns ---
INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) "
    r"(instructions|messages|prompts)",
    r"disregard (all |any |the )?(previous|prior|above) "
    r"(instructions|messages|prompts)",
    r"you are now (a |an )?",
    r"forget (all |any |everything )?(you|your)",
    r"system (prompt|message|instruction)",
    r"reveal (your|the) (prompt|instructions|system)",
    r"act as (a |an )?",
    r"pretend (to be|you are)",
    r"new instructions:",
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
    handler. Production downstream consumers should use the
    suggested idempotency keys (engagement_id, decision_id,
    correlation_id, etc.) to deduplicate on retry.
    """
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "chronic_coach",
            "DetailType":   detail_type,
            "Detail":       json.dumps(_from_decimal(detail)),
            "EventBusName": COACH_EVENT_BUS_NAME,
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
    before storage; only structural metadata makes it into the
    ledger (tool name, latency, outcome). Full arguments and
    results live in the audit pipeline.
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
    """Strip sensitive fields before ledger storage."""
    redacted = dict(arguments)
    sensitive_keys = {
        "patient_id", "name", "date_of_birth",
        "user_message", "free_text", "phone",
        "email", "address",
    }
    for key in list(redacted.keys()):
        if key in sensitive_keys:
            redacted[key] = "[REDACTED]"
    return redacted
```

---

## Mock Infrastructure

Production calls real Bedrock endpoints, real DynamoDB tables, real EHR APIs, real biometric-vendor APIs, and a real care-team workflow. The demo replaces these with small in-memory mocks so it can run without any AWS resources configured. Read this section to understand what each mock stands in for; replace each one with a real client when you wire this into your environment.

```python
class MockTable:
    """Stands in for a DynamoDB table for the demo."""

    def __init__(self, name, partition_key="session_id"):
        self.name = name
        self.items = {}
        self.partition_key = partition_key

    def put_item(self, Item):
        key = Item.get(self.partition_key) or Item.get("decision_id") \
            or Item.get("engagement_id") or Item.get("alert_id") \
            or str(uuid.uuid4())
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
    citation-grounding verifier and scope-filter keep it
    honest.
    """

    def invoke_engagement_message(self, *,
                                  patient_name,
                                  trigger_kind,
                                  recent_biometric_summary,
                                  behavior_change_stage,
                                  language="en-US"):
        """Compose a proactive engagement message."""
        # The demo composes templates that mirror what the
        # production LLM would produce. Stage-aware tone is
        # baked in: pre-contemplation gets gentle openers;
        # action gets specific suggestions.
        opener = {
            "pre_contemplation":
                "Hi {name}, just thinking of you. ",
            "contemplation":
                "Hi {name}, checking in. ",
            "preparation":
                "Hi {name}, hope you're doing okay. ",
            "action":
                "Hi {name}, just checking in. ",
            "maintenance":
                "Hi {name}, just a quick hello. ",
        }.get(behavior_change_stage,
              "Hi {name}, just checking in. ")

        body = ""
        if trigger_kind == "biometric_followup":
            body = (
                "I noticed your fasting glucose readings "
                "have been a bit higher this week (averaging "
                f"around {recent_biometric_summary['avg']}, "
                "up from your usual). Anything going on? "
                "No judgment, just curious if something "
                "feels different."
            )
        elif trigger_kind == "scheduled_check_in":
            body = (
                "How are things going with your plan this "
                "week? Anything getting in the way, or "
                "anything that's working well?"
            )
        elif trigger_kind == "medication_start_day_3":
            body = (
                "It's been a few days since you started "
                "the new medication. How are you feeling? "
                "Any side effects, or is it going okay?"
            )
        else:
            body = (
                "Just checking in to see how you're doing."
            )

        return {
            "message": opener.format(name=patient_name) + body,
            "citations": [{
                "kind": "care_plan",
                "id":   "care_plan_id_for_patient",
                "version": "v3.2",
            }],
        }

    def invoke_conversation_response(self, *,
                                     user_message,
                                     longitudinal_context,
                                     behavior_change_stage):
        """
        Compose a response to a patient utterance. Production
        runs the LLM with tool calls; the demo returns a
        structured response that demonstrates the citation
        and scope discipline.
        """
        # Detect a few canned scenarios for the demo.
        msg_lower = user_message.lower()

        if "mom is visiting" in msg_lower or \
           "mother is visiting" in msg_lower:
            return {
                "response_text": (
                    "Got it, that makes sense. Family "
                    "visits are usually wonderful and also "
                    "throw routines off. How long is she "
                    "staying?"),
                "citations": [{
                    "kind": "care_plan",
                    "id":   longitudinal_context["care_plan"]
                                ["care_plan_id"],
                    "version": longitudinal_context["care_plan"]
                                ["care_plan_version"],
                }],
                "tool_calls": [
                    {"tool": "longitudinal_disclosure_record",
                     "args": {"category":
                                  "family_visit_routine_disruption"}}
                ],
            }

        if "morning thing" in msg_lower or \
           "do the morning" in msg_lower:
            return {
                "response_text": (
                    "Perfect. Let's try that for a few "
                    "days and see what happens with the "
                    "fasting readings. Your usual breakfast "
                    "is the oatmeal with the berries, "
                    "right?"),
                "citations": [{
                    "kind": "education_content",
                    "id":   "morning_breakfast_glucose_tip",
                    "version": "v1.0",
                }, {
                    "kind": "care_plan",
                    "id":   longitudinal_context["care_plan"]
                                ["care_plan_id"],
                    "version": longitudinal_context["care_plan"]
                                ["care_plan_version"],
                }],
                "tool_calls": [
                    {"tool": "follow_up_schedule",
                     "args": {"engagement_type":
                                  "morning_breakfast_routine_check",
                              "delay_days": 4}}
                ],
            }

        if "stopped" in msg_lower and \
           ("metformin" in msg_lower or "medication" in msg_lower):
            return {
                "response_text": (
                    "Thanks for telling me; that takes "
                    "guts. Can you walk me through what "
                    "happened? I'm not here to push you "
                    "back on it; I just want to understand "
                    "what got in the way."),
                "citations": [{
                    "kind": "care_plan",
                    "id":   longitudinal_context["care_plan"]
                                ["care_plan_id"],
                    "version": longitudinal_context["care_plan"]
                                ["care_plan_version"],
                }],
                "tool_calls": [
                    {"tool": "longitudinal_disclosure_record",
                     "args": {"category":
                                  "medication_discontinuation"}},
                    {"tool": "care_team_alert_propose",
                     "args": {"alert_type":
                                  "medication_discontinuation",
                              "urgency": "within_shift"}},
                ],
            }

        # Generic relationship-quality response for the demo.
        return {
            "response_text": (
                "Thanks for sharing that with me. What "
                "would feel most useful to talk about right "
                "now?"),
            "citations": [{
                "kind": "care_plan",
                "id":   longitudinal_context["care_plan"]
                            ["care_plan_id"],
                "version": longitudinal_context["care_plan"]
                            ["care_plan_version"],
            }],
            "tool_calls": [],
        }

class MockEHR:
    """Stands in for the FHIR-native chart-context store."""

    def __init__(self):
        self.charts = {}

    def add_patient(self, patient_id, chart):
        self.charts[patient_id] = chart

    def get_chart(self, patient_id):
        return self.charts.get(patient_id, {})

    def get_active_care_plan(self, patient_id):
        return self.charts.get(patient_id, {}).get(
            "active_care_plan")

class MockBiometricVendor:
    """
    Stands in for the connected-device vendor APIs (Dexcom,
    Withings, Omron, etc.). Production wires one client per
    vendor with its specific authentication flow.
    """

    def __init__(self):
        self.feed = defaultdict(list)

    def push_reading(self, patient_id, device_type,
                     reading, timestamp=None):
        self.feed[patient_id].append({
            "device_type": device_type,
            "reading": reading,
            "timestamp": timestamp or _now_iso(),
        })

    def recent(self, patient_id, device_type, days=14):
        cutoff = _now() - timedelta(days=days)
        out = []
        for r in self.feed.get(patient_id, []):
            if r["device_type"] != device_type:
                continue
            ts = datetime.fromisoformat(r["timestamp"])
            if ts >= cutoff:
                out.append(r)
        return out

class MockKnowledgeBase:
    """Stands in for Bedrock Knowledge Bases retrieval."""

    def __init__(self, kb_id, content):
        self.kb_id = kb_id
        self.content = content

    def retrieve(self, query, filters=None):
        # Demo: return content items whose topic matches the
        # filter, if a filter is supplied; otherwise return
        # an empty result. Production performs vector and
        # lexical retrieval with metadata filtering.
        results = []
        for content_id, item in self.content.items():
            if filters and item.get("condition") != \
                    filters.get("condition"):
                continue
            results.append({
                "content_id": content_id,
                "score": 0.85,
                "content": item,
            })
        return results

class MockCareTeamWorkflow:
    """Stands in for the care-team alert and digest delivery."""

    def __init__(self):
        self.alerts = []
        self.digests = []

    def deliver_alert(self, alert):
        self.alerts.append(alert)

    def deliver_digest(self, digest):
        self.digests.append(digest)

class MockPharmacy:
    """Stands in for the pharmacy adherence data source."""

    def __init__(self):
        self.fills = defaultdict(list)

    def add_fill(self, patient_id, medication, fill_date,
                 days_supply):
        self.fills[patient_id].append({
            "medication": medication,
            "fill_date": fill_date,
            "days_supply": days_supply,
        })

    def get_fills(self, patient_id, window_start, window_end):
        return [f for f in self.fills[patient_id]
                if window_start <= f["fill_date"] <= window_end]

class MockTriagePathway:
    """Stands in for the recipe 11.6 triage workflow."""

    def __init__(self):
        self.handoffs = []

    def receive(self, payload):
        self.handoffs.append(payload)

class MockMentalHealthPathway:
    """Stands in for the recipe 11.8 mental-health workflow."""

    def __init__(self):
        self.handoffs = []

    def receive(self, payload):
        self.handoffs.append(payload)

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
    """Stands in for the S3 decision-record archive."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = Body
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
mock_biometric_vendor  = MockBiometricVendor()
mock_guideline_kb      = MockKnowledgeBase(
    GUIDELINE_KNOWLEDGE_BASE_ID, {})
mock_education_kb      = MockKnowledgeBase(
    EDUCATION_KNOWLEDGE_BASE_ID, EDUCATION_LIBRARY)
mock_care_team         = MockCareTeamWorkflow()
mock_pharmacy          = MockPharmacy()
mock_triage_pathway    = MockTriagePathway()
mock_mh_pathway        = MockMentalHealthPathway()

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
    ENGAGEMENT_SCHEDULE_TABLE:   MockTable(
        ENGAGEMENT_SCHEDULE_TABLE, "engagement_id"),
    BIOMETRIC_EVENT_STORE_TABLE: MockTable(
        BIOMETRIC_EVENT_STORE_TABLE, "patient_id"),
    CARE_TEAM_ALERT_QUEUE_TABLE: MockTable(
        CARE_TEAM_ALERT_QUEUE_TABLE, "alert_id"),
    OUTCOME_CORRELATION_TABLE:   MockTable(
        OUTCOME_CORRELATION_TABLE, "patient_id"),
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

## Step 1: Enroll the Patient and Instantiate the Longitudinal Store

This is the foundation. Without an instantiated, signed care plan and an initialized longitudinal store, the coach has nowhere to put the relationship it is supposed to maintain. Production runs this as a clinical workflow (the care team identifies the patient, selects the template, instantiates the plan, signs it, and the patient consents); the demo collapses it into a single function for clarity.

```python
def enroll_patient(*,
                    patient_id,
                    primary_condition,
                    secondary_conditions,
                    template_id,
                    clinical_team_signoff,
                    patient_consent):
    """
    Enroll a patient into the coaching program. Returns the
    instantiated care-plan id and writes the longitudinal
    store entry.
    """
    # Step 1A: select care-plan template. In production the
    # registry is a managed corpus owned by clinical-specialty
    # leadership; the demo reads from CARE_PLAN_TEMPLATES.
    template = CARE_PLAN_TEMPLATES.get(template_id)
    if not template:
        raise ValueError(
            f"Unknown care-plan template: {template_id}")

    # Step 1B: instantiate the care plan with patient-
    # specific values. The patient-specific values come from
    # the chart context (current medications, lab results,
    # active conditions) and from the clinical team's inputs
    # at signoff time. The demo uses a thin instantiation;
    # production has condition-specific instantiation logic.
    chart = mock_ehr.get_chart(patient_id)
    care_plan_id = f"{patient_id}-{template_id}-{uuid.uuid4().hex[:8]}"
    care_plan = {
        "care_plan_id":       care_plan_id,
        "care_plan_version":  template["template_version"],
        "template_id":        template_id,
        "patient_id":         patient_id,
        "condition":          template["condition"],
        "goals":              list(template["goals_template"]),
        "biometric_thresholds":
            dict(template.get("biometric_streams", {})),
        "engagement_cadence":
            dict(template["engagement_cadence"]),
        "escalation_criteria":
            list(template["escalation_criteria"]),
        "signed_by":          clinical_team_signoff["clinicians"],
        "signed_at":          _now_iso(),
        "effective_date":     _now_iso(),
        "next_review_date":
            (_now() + timedelta(days=365)).isoformat(),
    }

    # Step 1C: present care plan to patient for review and
    # consent. In production this is a dedicated patient-
    # facing flow with documented consent capture; the demo
    # accepts a precomputed consent object.
    if not patient_consent.get("granted"):
        return {
            "action": "enrollment_declined",
            "patient_id": patient_id,
        }

    # Step 1D: initialize the longitudinal store. This is the
    # architectural primitive that makes the coach a coach.
    # Without it, every conversation is a fresh start.
    longitudinal = {
        "patient_id":              patient_id,
        "active_care_plan_id":     care_plan_id,
        "primary_condition":       primary_condition,
        "secondary_conditions":    list(secondary_conditions),
        "behavior_change_stage_per_goal":
            _initialize_behavior_change_stages(
                care_plan, chart),
        "patient_preferences": {
            "preferred_channels":
                patient_consent["preferred_channels"],
            "quiet_hours_start_local":
                patient_consent.get(
                    "quiet_hours_start_local",
                    QUIET_HOURS_START_DEFAULT_LOCAL),
            "quiet_hours_end_local":
                patient_consent.get(
                    "quiet_hours_end_local",
                    QUIET_HOURS_END_DEFAULT_LOCAL),
            "language":
                patient_consent.get("language", "en-US"),
            "preferred_name":
                patient_consent.get("preferred_name", ""),
            "max_daily_engagements":
                patient_consent.get(
                    "max_daily_engagements",
                    MAX_DAILY_ENGAGEMENTS_DEFAULT),
            "topic_optouts":
                list(patient_consent.get("topic_optouts", [])),
        },
        "biometric_data_baseline": {},
        "adherence_pattern_baseline": {},
        "life_context_disclosures": [],
        "outcome_tracking_baseline":
            _extract_outcome_baseline(chart, care_plan),
        "enrolled_at":             _now_iso(),
        "active":                  True,
    }

    longitudinal_table = dynamodb.Table(
        LONGITUDINAL_STORE_TABLE)
    longitudinal_table.put_item(Item=_to_decimal(longitudinal))

    # Step 1E: persist the care-plan record (separate from the
    # longitudinal store; the care plan is its own clinical
    # record).
    care_plan_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)  # demo: collapsed
    care_plan_table.put_item(Item=_to_decimal({
        "session_id":  f"care_plan_{care_plan_id}",
        "kind":        "care_plan",
        "care_plan":   care_plan,
        "stored_at":   _now_iso(),
    }))

    # Step 1F: schedule the initial onboarding engagement.
    schedule_engagement(
        patient_id=patient_id,
        engagement_type="onboarding_introduction",
        delivery_target=(_now() + timedelta(hours=24)),
        priority="high",
        context={"care_plan_id": care_plan_id})

    _emit_event("patient_enrolled", {
        "patient_id":       patient_id,
        "care_plan_id":     care_plan_id,
        "primary_condition": primary_condition,
        "template_id":      template_id,
    })

    _put_metric("PatientEnrolled", 1, {
        "Condition": primary_condition,
        "Template":  template_id,
    })

    return {
        "action":       "enrolled",
        "patient_id":   patient_id,
        "care_plan_id": care_plan_id,
    }

def _initialize_behavior_change_stages(care_plan, chart):
    """
    Initialize per-goal behavior-change-stage estimates from
    the chart context. Production runs the institutional
    classifier; the demo defaults to "preparation" for every
    goal, which is a common starting point for newly-enrolled
    patients who consented to coaching.
    """
    stages = {}
    for goal in care_plan["goals"]:
        stages[goal["goal_id"]] = {
            "stage": "preparation",
            "evidence":
                "default initialization at enrollment",
            "updated_at": _now_iso(),
        }
    return stages

def _extract_outcome_baseline(chart, care_plan):
    """
    Extract the outcome-tracking baseline from the chart for
    later outcome-correlation work. Production reads a curated
    set of baseline metrics per condition (A1c, BP, weight,
    eGFR, condition-specific outcomes); the demo records
    whatever is in the chart's "baseline" field.
    """
    return chart.get("baseline", {})
```

The enrollment function is doing six things, in order. Read them as one workflow:

1. **Pick the template.** The condition determines the template; the template comes from the institutional library owned by clinical leadership.
2. **Instantiate the care plan.** The patient-specific values come from the chart and from clinical-team inputs at signoff. The plan is signed and version-stamped.
3. **Confirm patient consent.** Without it, no enrollment.
4. **Initialize the longitudinal store.** Behavior-change-stage per goal, patient preferences, baselines. Skip this and the coach has no foundation.
5. **Persist the care plan as its own clinical record.** Separately governed from the longitudinal store.
6. **Schedule onboarding.** The first engagement goes out 24 hours later (production schedules it for the patient's preferred time window).

---

## Step 2: Ingest Biometric Data and Evaluate Against Care-Plan Thresholds

Connected devices feed the coach. Each reading is validated, stored, and evaluated against the thresholds specified in the patient's care plan. Threshold-crossing events trigger engagement (or escalation, depending on severity). The thresholds are not chosen by the LLM; they are clinical-care-plan inputs signed by the patient's clinical team. Skip this step and the coach is missing one of its highest-value inputs (the data the patient is generating between visits).

```python
def biometric_data_received(*,
                             patient_id,
                             device_type,
                             reading,
                             reading_timestamp=None):
    """
    Ingest a biometric reading from a connected device. The
    flow validates the reading, stores it, evaluates it
    against the patient's care-plan thresholds, and dispatches
    engagement or escalation events.
    """
    reading_timestamp = reading_timestamp or _now_iso()

    # Step 2A: validate the reading. Production has per-device
    # validation rules (impossible values, sensor-error codes,
    # device-status flags); the demo runs a minimal sanity
    # check.
    validation = _validate_biometric_reading(
        device_type, reading, patient_id)
    if not validation["valid"]:
        logger.warning(
            "Discarded invalid biometric reading: "
            "patient=%s device=%s reason=%s",
            patient_id, device_type, validation["reason"])
        return {"action": "invalid_reading_discarded"}

    # Step 2B: store the reading.
    biometric_store = dynamodb.Table(
        BIOMETRIC_EVENT_STORE_TABLE)
    biometric_store.put_item(Item=_to_decimal({
        "patient_id":         patient_id,
        "device_type":        device_type,
        "reading":            reading,
        "reading_timestamp":  reading_timestamp,
        "ingested_at":        _now_iso(),
    }))

    # Step 2C: load the patient's active care plan to find
    # the thresholds for this device type.
    care_plan = _read_active_care_plan(patient_id)
    if not care_plan:
        logger.warning(
            "No active care plan for patient %s; "
            "skipping threshold evaluation.",
            patient_id)
        return {"action": "no_care_plan"}

    thresholds = care_plan.get(
        "biometric_thresholds", {}).get(device_type)
    if not thresholds:
        # Reading is recorded for trend analysis but no
        # threshold is configured for it.
        return {"action": "stored_no_thresholds"}

    # Step 2D: evaluate single-reading thresholds. These are
    # the immediate-action triggers (e.g., a single glucose
    # reading above 250 or below 60).
    single_event = _evaluate_single_reading(
        reading, thresholds, device_type)

    # Step 2E: evaluate trend thresholds. Production has
    # condition-specific trend logic (3-day average, 7-day
    # average, percentage change from baseline); the demo
    # uses a simple windowed average.
    recent_readings = mock_biometric_vendor.recent(
        patient_id, device_type,
        days=int(thresholds.get("trend_window_days", 7)))
    trend_event = _evaluate_trend(
        recent_readings, thresholds, device_type)

    # Step 2F: dispatch events.
    for event in [single_event, trend_event]:
        if event is None:
            continue

        if event["severity"] == "engagement":
            # Schedule a follow-up engagement.
            schedule_engagement(
                patient_id=patient_id,
                engagement_type="biometric_followup",
                delivery_target=_now() + timedelta(hours=2),
                priority=event["priority"],
                context={
                    "trigger_event": event,
                    "device_type": device_type,
                    "care_plan_id":
                        care_plan["care_plan_id"],
                })

        elif event["severity"] == "escalation":
            # Propose an escalation. The escalation tool
            # decides routing (care team, triage, 911).
            propose_escalation(
                patient_id=patient_id,
                trigger_reason="biometric_threshold_crossed",
                trigger_event=event,
                care_plan_reference=care_plan["care_plan_id"])

        _emit_event("biometric_threshold_crossed", {
            "patient_id":  patient_id,
            "device_type": device_type,
            "event_type":  event["type"],
            "severity":    event["severity"],
        })

    return {"action": "biometric_data_processed"}

def _validate_biometric_reading(device_type, reading,
                                 patient_id):
    """
    Sanity-check the reading. Production has per-device rules
    derived from each vendor's data-quality documentation;
    the demo enforces basic numeric bounds.
    """
    if device_type == "glucose_meter":
        value = reading.get("value")
        if not isinstance(value, (int, float, Decimal)):
            return {"valid": False,
                    "reason": "non_numeric_value"}
        if not (10 <= float(value) <= 800):
            return {"valid": False,
                    "reason": "value_out_of_physiologic_range"}
    elif device_type == "blood_pressure":
        sys_val = reading.get("systolic")
        dia_val = reading.get("diastolic")
        if not all(isinstance(v, (int, float, Decimal))
                   for v in [sys_val, dia_val]):
            return {"valid": False,
                    "reason": "non_numeric_bp"}
        if not (60 <= float(sys_val) <= 260):
            return {"valid": False,
                    "reason": "systolic_out_of_range"}
        if not (30 <= float(dia_val) <= 160):
            return {"valid": False,
                    "reason": "diastolic_out_of_range"}
    elif device_type == "weight":
        value = reading.get("value")
        if not isinstance(value, (int, float, Decimal)):
            return {"valid": False,
                    "reason": "non_numeric_weight"}
    return {"valid": True}

def _evaluate_single_reading(reading, thresholds, device_type):
    """
    Single-reading threshold evaluation. Returns an event dict
    or None.
    """
    if device_type == "glucose_meter" or \
       device_type == "fasting_glucose":
        value = float(reading.get("value", 0))
        single_high = thresholds.get("single_reading_high")
        single_low = thresholds.get("single_reading_low")
        if single_high is not None and value >= float(single_high):
            severity = "escalation" if value >= 400 \
                else "engagement"
            return {
                "type": "single_reading_high",
                "severity": severity,
                "priority":
                    "high" if severity == "escalation"
                    else "normal",
                "value": value,
                "threshold": float(single_high),
            }
        if single_low is not None and value <= float(single_low):
            return {
                "type": "single_reading_low",
                "severity": "escalation",
                "priority": "high",
                "value": value,
                "threshold": float(single_low),
            }
    elif device_type == "blood_pressure":
        sys_val = float(reading.get("systolic", 0))
        single_high = thresholds.get("single_reading_high")
        if single_high is not None and \
                sys_val >= float(single_high):
            return {
                "type": "bp_systolic_high",
                "severity":
                    "escalation" if sys_val >= 180
                    else "engagement",
                "priority":
                    "high" if sys_val >= 180 else "normal",
                "value": sys_val,
                "threshold": float(single_high),
            }
    return None

def _evaluate_trend(recent_readings, thresholds, device_type):
    """
    Trend threshold evaluation. Computes the windowed average
    and compares it to the configured trend threshold. Returns
    an event dict or None.
    """
    if not recent_readings:
        return None

    if device_type == "glucose_meter" or \
       device_type == "fasting_glucose":
        values = [float(r["reading"].get("value", 0))
                  for r in recent_readings
                  if r["reading"].get("value") is not None]
        if not values:
            return None
        avg = sum(values) / len(values)
        threshold_high = thresholds.get("trend_threshold_high")
        if threshold_high is not None and \
                avg >= float(threshold_high):
            return {
                "type": "trend_high",
                "severity": "engagement",
                "priority": "normal",
                "average": avg,
                "threshold": float(threshold_high),
                "readings_count": len(values),
            }
    return None

def _read_active_care_plan(patient_id):
    """Look up the active care plan for the patient."""
    longitudinal_table = dynamodb.Table(
        LONGITUDINAL_STORE_TABLE)
    record = longitudinal_table.get_item(
        Key={"patient_id": patient_id})
    if not record.get("Item"):
        return None
    care_plan_id = record["Item"].get("active_care_plan_id")
    care_plan_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    plan_rec = care_plan_table.get_item(
        Key={"session_id": f"care_plan_{care_plan_id}"})
    if plan_rec.get("Item"):
        return plan_rec["Item"]["care_plan"]
    return None
```

This step is doing the work the LLM cannot do reliably. The thresholds come from the care plan. The arithmetic runs as deterministic Python. The LLM never picks a threshold and never decides whether a reading is concerning. The LLM only enters the picture downstream, when the engagement scheduler invokes it to compose a warm, context-aware message about a threshold the deterministic code already flagged.

---

## Step 3: Schedule and Deliver Proactive Engagement

Proactive engagement is what makes the coach a coach. A reactive bot that only responds when the patient initiates is a chatbot. The engagement scheduler runs scheduled check-ins, milestone touchpoints, and biometric-triggered follow-ups, while respecting the patient's preferences and the institutional engagement policy. Get this wrong (too aggressive) and the patient opts out within weeks; get it wrong (too passive) and the broad chronic-disease majority gets no benefit.

```python
def schedule_engagement(*,
                         patient_id,
                         engagement_type,
                         delivery_target,
                         priority="normal",
                         context=None):
    """
    Add a proactive engagement to the schedule. Production
    runs this through Step Functions for durable scheduling
    with delay states; the demo writes to DynamoDB directly.
    """
    engagement_id = f"eng_{uuid.uuid4().hex}"
    record = {
        "engagement_id":     engagement_id,
        "patient_id":        patient_id,
        "engagement_type":   engagement_type,
        "delivery_target":
            (delivery_target.isoformat()
             if hasattr(delivery_target, "isoformat")
             else delivery_target),
        "priority":          priority,
        "context":           context or {},
        "status":            "scheduled",
        "scheduled_at":      _now_iso(),
    }

    table = dynamodb.Table(ENGAGEMENT_SCHEDULE_TABLE)
    table.put_item(Item=_to_decimal(record))

    _emit_event("engagement_scheduled", {
        "engagement_id":   engagement_id,
        "patient_id":      patient_id,
        "engagement_type": engagement_type,
    })

    return {"action": "scheduled",
            "engagement_id": engagement_id}

def deliver_scheduled_engagement(scheduled_engagement):
    """
    Compose and deliver a scheduled engagement. Runs the
    engagement-policy enforcement, composes the message via
    the LLM grounded in the patient's longitudinal context,
    runs output safety, and dispatches via the patient's
    preferred channel.

    In production this is the body of the Lambda that the
    Step Functions workflow invokes when the delay state
    completes.
    """
    patient_id = scheduled_engagement["patient_id"]

    # Step 3A: load the longitudinal store.
    longitudinal_table = dynamodb.Table(
        LONGITUDINAL_STORE_TABLE)
    longitudinal_record = longitudinal_table.get_item(
        Key={"patient_id": patient_id})
    if not longitudinal_record.get("Item"):
        return {"action": "no_longitudinal_record"}

    longitudinal = longitudinal_record["Item"]
    if not longitudinal.get("active"):
        return {"action": "patient_inactive_skip"}

    # Step 3B: enforce engagement policy. Quiet hours, daily
    # cap, topic opt-outs, fatigue detection. Production runs
    # this against persistent state; the demo runs against
    # the in-memory schedule history.
    policy_check = _enforce_engagement_policy(
        scheduled_engagement, longitudinal)

    if policy_check["action"] == "skip_quiet_hours":
        # Reschedule for the next non-quiet window.
        new_target = _next_non_quiet_window(
            longitudinal["patient_preferences"])
        schedule_engagement(
            patient_id=patient_id,
            engagement_type=
                scheduled_engagement["engagement_type"],
            delivery_target=new_target,
            priority=scheduled_engagement["priority"],
            context=scheduled_engagement.get("context"))
        return {"action": "rescheduled_quiet_hours"}

    if policy_check["action"] == "skip_daily_cap":
        return {"action": "skipped_daily_cap"}

    if policy_check["action"] == "skip_fatigue":
        _put_metric("EngagementSkippedFatigue", 1, {
            "Condition": longitudinal["primary_condition"]})
        return {"action": "skipped_fatigue"}

    if policy_check["action"] == "skip_topic_optout":
        return {"action": "skipped_topic_optout"}

    # Step 3C: load the care plan and recent biometric data
    # for context.
    care_plan = _read_active_care_plan(patient_id)
    if not care_plan:
        return {"action": "no_care_plan"}

    recent_biometric_summary = _summarize_recent_biometric(
        patient_id, scheduled_engagement.get("context", {}))

    # Step 3D: compose the engagement message. Production
    # runs the LLM with the longitudinal context and the
    # behavior-change-stage adaptation; the demo uses the
    # mock that returns templates calibrated by stage.
    primary_goal_id = care_plan["goals"][0]["goal_id"]
    stage = longitudinal["behavior_change_stage_per_goal"]\
        .get(primary_goal_id, {})\
        .get("stage", "preparation")

    composed = mock_bedrock.invoke_engagement_message(
        patient_name=longitudinal["patient_preferences"]
            .get("preferred_name", "there"),
        trigger_kind=scheduled_engagement["engagement_type"],
        recent_biometric_summary=recent_biometric_summary,
        behavior_change_stage=stage,
        language=longitudinal["patient_preferences"]
            .get("language", "en-US"))

    # Step 3E: run output safety screening before delivery.
    safety = _screen_engagement_output(
        composed["message"], care_plan, longitudinal)
    if safety["action"] != "deliver":
        _put_metric("EngagementScreeningFailed", 1, {
            "Condition": longitudinal["primary_condition"],
            "Reason": safety.get("reason", "unknown")})
        return {"action": "screening_failed",
                "reason": safety.get("reason")}

    # Step 3F: deliver via the patient's preferred channel.
    channel = longitudinal["patient_preferences"][
        "preferred_channels"][0]
    delivery_result = _deliver_via_channel(
        patient_id=patient_id,
        channel=channel,
        message=composed["message"],
        engagement_id=scheduled_engagement["engagement_id"])

    # Step 3G: log the engagement.
    table = dynamodb.Table(ENGAGEMENT_SCHEDULE_TABLE)
    table.put_item(Item=_to_decimal({
        "engagement_id":
            scheduled_engagement["engagement_id"],
        "patient_id":        patient_id,
        "engagement_type":
            scheduled_engagement["engagement_type"],
        "status":            "delivered",
        "delivered_at":      _now_iso(),
        "channel":           channel,
        "delivery_status":   delivery_result["status"],
    }))

    _emit_event("engagement_delivered", {
        "engagement_id":
            scheduled_engagement["engagement_id"],
        "patient_id":        patient_id,
        "engagement_type":
            scheduled_engagement["engagement_type"],
    })

    _put_metric("EngagementDelivered", 1, {
        "Condition": longitudinal["primary_condition"],
        "Channel":   channel,
        "Type":      scheduled_engagement["engagement_type"],
    })

    return {"action": "delivered",
            "engagement_id":
                scheduled_engagement["engagement_id"]}

def _enforce_engagement_policy(scheduled_engagement,
                                longitudinal):
    """
    Apply the engagement-policy floor. Quiet hours, max daily
    cap, topic opt-outs, engagement-fatigue mitigation. Order
    matters: emergencies bypass the policy (production handles
    this with a separate priority lane that the policy does
    not gate); routine engagements respect every constraint.
    """
    prefs = longitudinal["patient_preferences"]
    now_local_hour = _now().hour  # demo: assume UTC == local

    # Quiet hours.
    quiet_start = int(prefs.get(
        "quiet_hours_start_local",
        QUIET_HOURS_START_DEFAULT_LOCAL))
    quiet_end = int(prefs.get(
        "quiet_hours_end_local",
        QUIET_HOURS_END_DEFAULT_LOCAL))

    in_quiet = (now_local_hour >= quiet_start or
                now_local_hour < quiet_end)
    if in_quiet and \
            scheduled_engagement["priority"] != "high":
        return {"action": "skip_quiet_hours"}

    # Topic opt-outs.
    optouts = set(prefs.get("topic_optouts", []))
    if scheduled_engagement["engagement_type"] in optouts:
        return {"action": "skip_topic_optout"}

    # Daily cap.
    today = _now().date().isoformat()
    table = dynamodb.Table(ENGAGEMENT_SCHEDULE_TABLE)
    delivered_today = sum(
        1 for record_list in table.items.values()
        for record in record_list
        if record.get("patient_id") ==
            longitudinal["patient_id"]
        and record.get("status") == "delivered"
        and record.get("delivered_at", "").startswith(today))
    daily_cap = int(prefs.get(
        "max_daily_engagements",
        MAX_DAILY_ENGAGEMENTS_DEFAULT))
    if delivered_today >= daily_cap and \
            scheduled_engagement["priority"] != "high":
        return {"action": "skip_daily_cap"}

    # Fatigue detection. Production looks at the rolling
    # response rate over the last 30 days; the demo always
    # passes (rolling-window analytics elided).
    return {"action": "deliver"}

def _next_non_quiet_window(prefs):
    """Find the next time outside the patient's quiet hours."""
    quiet_end = int(prefs.get(
        "quiet_hours_end_local",
        QUIET_HOURS_END_DEFAULT_LOCAL))
    target = _now()
    while target.hour < quiet_end or \
            target.hour >= int(prefs.get(
                "quiet_hours_start_local",
                QUIET_HOURS_START_DEFAULT_LOCAL)):
        target = target + timedelta(hours=1)
    return target

def _summarize_recent_biometric(patient_id, context):
    """Summarize recent biometric data for engagement context."""
    device = context.get("device_type", "glucose_meter")
    readings = mock_biometric_vendor.recent(
        patient_id, device, days=7)
    if not readings:
        return {"avg": None, "count": 0}
    if device == "glucose_meter":
        values = [float(r["reading"].get("value", 0))
                  for r in readings
                  if r["reading"].get("value")]
        if not values:
            return {"avg": None, "count": 0}
        return {
            "avg":   round(sum(values) / len(values)),
            "count": len(values),
        }
    return {"avg": None, "count": len(readings)}

def _screen_engagement_output(message, care_plan,
                                longitudinal):
    """
    Output screening for proactive engagement messages. The
    same scope-and-tone discipline that applies to chat
    responses applies to coach-initiated messages: no
    diagnosis, no off-care-plan recommendations, no clinical
    judgment beyond scope.
    """
    # Demo: pass-through. Production runs the same screening
    # pipeline as the conversation-handler output screening.
    return {"action": "deliver"}

def _deliver_via_channel(*, patient_id, channel, message,
                          engagement_id):
    """Dispatch to the patient via the preferred channel."""
    if channel == "push":
        pinpoint_client.send_messages(
            ApplicationId=PINPOINT_APPLICATION_ID,
            MessageRequest={
                "Addresses": {
                    f"endpoint-{patient_id}": {
                        "ChannelType": "GCM"}},
                "MessageConfiguration": {
                    "GCMMessage": {
                        "Body": message,
                        "Title": "Coach Check-In",
                    }}})
    elif channel == "sms":
        pinpoint_client.send_messages(
            ApplicationId=PINPOINT_APPLICATION_ID,
            MessageRequest={
                "Addresses": {
                    f"endpoint-{patient_id}": {
                        "ChannelType": "SMS"}},
                "MessageConfiguration": {
                    "SMSMessage": {
                        "Body": message,
                        "MessageType": "TRANSACTIONAL",
                    }}})
    else:
        # In-app: delivery happens when the patient next
        # opens the app; the message sits in their inbox.
        pass
    return {"status": "delivered"}
```

The engagement scheduler is the most operationally subtle piece of the architecture. Most teams that build a chronic-coach for the first time underestimate how much policy lives in this layer. Production runs this as a Step Functions workflow with delay states (so the durable scheduling survives Lambda outages and region failover), with the engagement-policy enforcement re-checked at each delivery time (the patient may have changed preferences since the engagement was scheduled), with fatigue detection running on a rolling 30-day window, and with explicit fatigue-mitigation logic that reduces cadence when response rates drop below the floor.

---

## Step 4: Handle Patient-Initiated or Patient-Responding Conversation

The coach loads the full longitudinal context (care plan, recent biometric data, recent conversation history, patient preferences, behavior-change-stage estimates, recent life-context disclosures) before generating any response. The longitudinal context is the architectural primitive that makes the coach a coach rather than a chatbot.

```python
def receive_message(*,
                     channel,
                     channel_session_id,
                     user_message,
                     auth_context):
    """
    Entry point for patient-initiated or patient-responding
    conversation. Returns the bot's response payload.
    """
    # Step 4A: identify or create the conversation session.
    state_table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    session = _get_or_create_session(
        state_table, channel, channel_session_id, auth_context)
    session_id = session["session_id"]
    patient_id = session["verified_patient_id"]

    # Step 4B: persist the user's message.
    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    metadata_table.put_item(Item=_to_decimal({
        "session_id":     session_id,
        "kind":           "turn",
        "speaker":        "user",
        "text":           user_message,
        "timestamp":      _now_iso(),
    }))

    # Step 4C: input safety screening. Prompt-injection
    # detection, PHI minimization, scope-violation detection.
    screening = _screen_input(session_id, user_message)
    if screening["action"] == "block":
        return _handle_block(session_id, screening)

    # Step 4D: continuous emergency screening. Runs on every
    # utterance, regardless of conversation context. A patient
    # in long-term coaching may surface acute symptoms at any
    # time.
    longitudinal = _read_longitudinal_store(patient_id)
    active_conditions = [longitudinal["primary_condition"]] + \
        longitudinal.get("secondary_conditions", [])

    emergency = _emergency_screen(
        user_message, active_conditions)
    if emergency["emergency_detected"]:
        return _handle_emergency_routing(
            session_id, patient_id, emergency)

    # Step 4E: sensitive-disclosure detection. Continues the
    # conversation but flags for appropriate routing.
    disclosure = _sensitive_disclosure_screen(user_message)
    if disclosure["disclosure_detected"]:
        _handle_sensitive_disclosure(
            session_id, patient_id, disclosure)

    # Step 4F: load longitudinal context. This is the heart
    # of the coach's value: the care plan, recent biometric
    # data, recent conversation history, patient preferences,
    # behavior-change-stage estimates, recent life-context
    # disclosures, open follow-up items.
    care_plan = _read_active_care_plan(patient_id)
    if not care_plan:
        return {
            "response": (
                "I'm having trouble finding your care plan. "
                "Let me have your care team reach out."),
            "disposition": "no_care_plan_fallback",
            "citations": [],
        }

    recent_biometric = _recent_biometric_for_context(
        patient_id, days=30)
    recent_conversation = _recent_conversation_for_context(
        patient_id, days=90, max_turns=50)
    long_term_summary = _read_long_term_summary(patient_id)
    open_followups = _open_followups_for_patient(patient_id)

    longitudinal_context = {
        "longitudinal":         longitudinal,
        "care_plan":            care_plan,
        "recent_biometric":     recent_biometric,
        "recent_conversation":  recent_conversation,
        "long_term_summary":    long_term_summary,
        "open_followups":       open_followups,
    }

    # Persist for downstream steps (response composition,
    # output screening, decision-record persistence).
    metadata_table.put_item(Item=_to_decimal({
        "session_id":             session_id,
        "kind":                   "longitudinal_context_snapshot",
        "context_summary": {
            "care_plan_id":   care_plan["care_plan_id"],
            "care_plan_version":
                care_plan["care_plan_version"],
            "biometric_count": len(recent_biometric),
            "conversation_turn_count":
                len(recent_conversation),
            "open_followups_count":
                len(open_followups),
        },
        "timestamp":              _now_iso(),
    }))

    # Return the loaded context for the orchestrator.
    # The orchestrator (coach_full_pipeline) calls
    # handle_conversation exactly once with this context.
    return {
        "session_id": session_id,
        "patient_id": patient_id,
        "longitudinal_context": longitudinal_context,
    }

def _get_or_create_session(state_table, channel,
                            channel_session_id, auth_context):
    """Resolve or create a coaching conversation session."""
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
    }
    state_table.put_item(Item=_to_decimal(new_session))
    return new_session

def _read_longitudinal_store(patient_id):
    """Load the longitudinal store for the patient."""
    table = dynamodb.Table(LONGITUDINAL_STORE_TABLE)
    record = table.get_item(Key={"patient_id": patient_id})
    return record.get("Item", {})

def _screen_input(session_id, user_message):
    """
    Input safety screening. Prompt-injection detection, PHI
    pattern detection, length checks. Production layers a
    classifier and a Bedrock Guardrail call on top.
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

def _emergency_screen(user_message, active_conditions):
    """
    Continuous emergency screening. Keyword detection across
    the categories in EMERGENCY_VOCABULARY, with condition-
    specific gating for the categories that require it.
    Production layers a tuned classifier on top.
    """
    msg_lower = user_message.lower()
    for category, config in EMERGENCY_VOCABULARY.items():
        applies_to = config.get("applies_to_conditions")
        if applies_to and not any(
                c in active_conditions for c in applies_to):
            continue
        for keyword in config["keywords"]:
            if keyword in msg_lower:
                return {
                    "emergency_detected": True,
                    "category": category,
                    "urgency": config["urgency"],
                }
    return {"emergency_detected": False}

def _sensitive_disclosure_screen(user_message):
    """Detect sensitive disclosures that route to specific paths."""
    msg_lower = user_message.lower()
    for category, config in SENSITIVE_DISCLOSURE_PATTERNS.items():
        for keyword in config["keywords"]:
            if keyword in msg_lower:
                return {
                    "disclosure_detected": True,
                    "category": category,
                    "route": config["route"],
                }
    return {"disclosure_detected": False}

def _handle_emergency_routing(session_id, patient_id,
                                emergency):
    """Route to the appropriate emergency pathway."""
    if emergency["urgency"] == "call_911":
        response = CRISIS_RESPONSE_911
    elif emergency["urgency"] == "call_988":
        response = CRISIS_RESPONSE_988
    else:
        response = CRISIS_RESPONSE_911

    # Hand off to the triage pathway with the conversation
    # context attached.
    mock_triage_pathway.receive({
        "session_id":  session_id,
        "patient_id":  patient_id,
        "category":    emergency["category"],
        "urgency":     emergency["urgency"],
        "timestamp":   _now_iso(),
    })

    _emit_event("emergency_routed", {
        "session_id":  session_id,
        "patient_id":  patient_id,
        "category":    emergency["category"],
    })

    _put_metric("EmergencyRouted", 1, {
        "Category": emergency["category"]})

    return {
        "response":    response,
        "disposition": "emergency_routed",
        "citations":   [],
    }

def _handle_sensitive_disclosure(session_id, patient_id,
                                   disclosure):
    """
    Handle a sensitive disclosure: continue conversation but
    flag for appropriate routing.
    """
    if disclosure["route"] == "ipv_pathway":
        # In production, this routes to a licensed mandatory
        # reporter; the demo just records the event.
        pass
    elif disclosure["route"] == "care_navigation":
        mock_care_team.deliver_alert({
            "alert_type":  f"sensitive_disclosure_"
                           f"{disclosure['category']}",
            "patient_id":  patient_id,
            "session_id":  session_id,
            "urgency":     "within_day",
            "timestamp":   _now_iso(),
        })
    elif disclosure["route"] == "care_team_followup":
        mock_care_team.deliver_alert({
            "alert_type":
                f"disclosure_{disclosure['category']}",
            "patient_id":  patient_id,
            "session_id":  session_id,
            "urgency":     "within_shift",
            "timestamp":   _now_iso(),
        })

    _emit_event("life_context_recorded", {
        "session_id":      session_id,
        "patient_id":      patient_id,
        "disclosure_category": disclosure["category"],
    })

def _handle_block(session_id, screening):
    """Default response when input screening blocks the message."""
    return {
        "response": (
            "Let's keep this focused on your care. What "
            "can I help you with right now?"),
        "disposition": "blocked",
        "citations": [],
    }

def _recent_biometric_for_context(patient_id, days=30):
    """Recent biometric data for conversation context."""
    cutoff = _now() - timedelta(days=days)
    out = []
    for r in mock_biometric_vendor.feed.get(patient_id, []):
        ts = datetime.fromisoformat(r["timestamp"])
        if ts >= cutoff:
            out.append(r)
    return out

def _recent_conversation_for_context(patient_id, days=90,
                                       max_turns=50):
    """Recent conversation history for context."""
    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    out = []
    for record_list in metadata_table.items.values():
        for record in record_list:
            if record.get("kind") != "turn":
                continue
            session_id = record.get("session_id", "")
            # Demo: assume any session for this patient is
            # relevant. Production keys by patient_id with
            # session_id as a sort attribute.
            out.append(record)
    return out[-max_turns:]

def _read_long_term_summary(patient_id):
    """Long-term summary refreshed periodically."""
    return {"summary": "stable on current regimen"}

def _open_followups_for_patient(patient_id):
    """Open follow-up items for the patient."""
    table = dynamodb.Table(ENGAGEMENT_SCHEDULE_TABLE)
    out = []
    for record_list in table.items.values():
        for record in record_list:
            if record.get("patient_id") != patient_id:
                continue
            if record.get("status") == "scheduled":
                out.append(record)
    return out
```

The longitudinal-context loading is doing a lot of work in a small space. Each query has a specific purpose. The recent-biometric data lets the coach reference "your readings have been a bit higher this week." The recent-conversation data lets the coach pick up where the last conversation left off. The long-term summary lets the coach reference patterns over months without blowing the context budget. The open follow-ups let the coach mention "I asked you on Tuesday how the new medication was treating you and you said you'd let me know on Friday." The patient preferences let the coach use the right name, the right language, and the right tone. None of this works if the longitudinal store is not maintained.

---

## Step 5: Generate the Response with Care-Plan-Grounded Reasoning and Behavior-Change-Stage Adaptation

The LLM operates as a Bedrock Agent with the coaching tool surface. The system prompt includes the patient's behavior-change stage per goal, the patient's stated preferences, the active care plan, and relevant clinical-guideline context. The tone, pacing, and content are adapted to the patient's behavior-change stage. Skip the stage adaptation and the coach is appropriate for some patients and counter-productive for others.

```python
def handle_conversation(*,
                         session_id,
                         patient_id,
                         user_message,
                         longitudinal_context):
    """
    Compose the response with care-plan-grounded reasoning
    and behavior-change-stage adaptation. Production wires
    this through bedrock_agent_runtime.invoke_agent with the
    coaching tools defined as action groups; the demo uses
    the mock that demonstrates the structure.
    """
    longitudinal = longitudinal_context["longitudinal"]
    care_plan = longitudinal_context["care_plan"]

    # Step 5A: assemble the system prompt. The prompt is
    # behavior-change-stage-aware: tone and pacing adapt to
    # where the patient is for each goal.
    primary_goal_id = care_plan["goals"][0]["goal_id"]
    primary_stage = longitudinal["behavior_change_stage_per_goal"]\
        .get(primary_goal_id, {})\
        .get("stage", "preparation")

    system_prompt = compose_coaching_system_prompt(
        coach_persona_name=INSTITUTION_DISPLAY_NAME,
        active_care_plan=care_plan,
        primary_stage=primary_stage,
        patient_preferences=longitudinal["patient_preferences"],
        long_term_summary=longitudinal_context[
            "long_term_summary"],
        regulatory_position=INSTITUTION_REGULATORY_POSITION)

    # Step 5B: invoke the orchestration model. Production:
    #
    #   response = bedrock_agent_runtime.invoke_agent(
    #       agentId=COACH_AGENT_ID,
    #       agentAliasId=COACH_AGENT_ALIAS_ID,
    #       sessionId=session_id,
    #       inputText=user_message,
    #       sessionState={
    #           "promptSessionAttributes": {
    #               "system_prompt": system_prompt,
    #               ...
    #           }})
    #
    # The agent handles tool-call orchestration. The demo
    # uses the mock that returns canned structured responses.
    agent_response = mock_bedrock.invoke_conversation_response(
        user_message=user_message,
        longitudinal_context=longitudinal_context,
        behavior_change_stage=primary_stage)

    # Step 5C: audit tool calls. Each tool the LLM invoked
    # gets a ledger entry with the tool name, the redacted
    # arguments, the result summary, the latency, and the
    # outcome.
    for tool_call in agent_response.get("tool_calls", []):
        _audit_tool_call(
            session_id=session_id,
            tool=tool_call["tool"],
            arguments=tool_call.get("args", {}),
            result_summary={"executed": True},
            latency_ms=12,  # demo-fixed
            outcome="success")

    # Step 5D: capture citations.
    citations = agent_response.get("citations", [])

    # Step 5E: behavior-change-stage signals. Production runs
    # a classifier or LLM-based signal extractor on the user
    # message and recent conversation; the demo runs a simple
    # keyword-based heuristic.
    stage_signal = _evaluate_behavior_change_signals(
        user_message=user_message,
        recent_conversation=longitudinal_context[
            "recent_conversation"],
        current_stages=longitudinal[
            "behavior_change_stage_per_goal"])

    if stage_signal["update_warranted"]:
        _update_behavior_change_stage(
            patient_id=patient_id,
            goal_id=stage_signal["goal_id"],
            new_stage=stage_signal["new_stage"],
            evidence=stage_signal["evidence"])

    return {
        "session_id":     session_id,
        "patient_id":     patient_id,
        "response_text":  agent_response["response_text"],
        "citations":      citations,
        "tool_calls":     agent_response.get("tool_calls", []),
        "longitudinal_context": longitudinal_context,
    }

def compose_coaching_system_prompt(*,
                                     coach_persona_name,
                                     active_care_plan,
                                     primary_stage,
                                     patient_preferences,
                                     long_term_summary,
                                     regulatory_position):
    """
    Build the system prompt. Production has the prompt
    version-controlled, with sandbox testing against held-out
    coaching cases on each material change.
    """
    stage_guidance = {
        "pre_contemplation": (
            "The patient is in pre-contemplation for "
            "their primary goal: focus on relationship "
            "building, gentle education, and motivational-"
            "interviewing-style elicitation rather than "
            "prescriptive recommendations. Do not push "
            "behavior change; explore the patient's view."),
        "contemplation": (
            "The patient is in contemplation: explore "
            "ambivalence, support decision-making, and "
            "provide information without pushing."),
        "preparation": (
            "The patient is in preparation: support "
            "planning, anticipate obstacles, elicit "
            "commitment without pressuring."),
        "action": (
            "The patient is in action: provide specific "
            "behavioral support, problem-solving, "
            "obstacle anticipation, and celebration of "
            "progress."),
        "maintenance": (
            "The patient is in maintenance: focus on "
            "relapse prevention and sustained-engagement "
            "support."),
    }.get(primary_stage,
          "Use motivational-interviewing-aligned tone.")

    preferred_name = patient_preferences.get(
        "preferred_name", "")
    language = patient_preferences.get("language", "en-US")

    return (
        f"You are {coach_persona_name}'s chronic-disease "
        f"coach. Address the patient as "
        f"\"{preferred_name}\" when appropriate. Respond "
        f"in {language}.\n\n"
        f"Active care plan: "
        f"{active_care_plan['care_plan_id']} "
        f"(version {active_care_plan['care_plan_version']}, "
        f"condition {active_care_plan['condition']}).\n\n"
        f"Goals: " + ", ".join(
            g["label"] for g in active_care_plan["goals"]) +
        ".\n\n"
        f"Behavior-change-stage guidance: {stage_guidance}\n\n"
        f"Long-term context: "
        f"{long_term_summary.get('summary', '')}\n\n"
        f"Scope: stay within the care plan. Do not diagnose "
        f"new conditions. Do not recommend medications "
        f"outside the care plan. Do not give clinical "
        f"advice beyond the plan. Defer to the care team "
        f"for clinical decisions outside scope.\n\n"
        f"Citation: every recommendation must trace to a "
        f"care-plan element, a clinical-guideline reference, "
        f"or institutional patient-education content.\n\n"
        f"Regulatory positioning: {regulatory_position}.\n\n"
        f"Tone: warm but boundaried. You are a tool the "
        f"patient's care team deployed; you are not a "
        f"clinician. Be honest about that when relevant.")

def _evaluate_behavior_change_signals(*, user_message,
                                        recent_conversation,
                                        current_stages):
    """
    Heuristic stage-signal extractor for the demo. Production
    runs a classifier reviewed by behavioral-health clinicians.
    """
    msg_lower = user_message.lower()

    # Action signals: patient is engaging in problem-solving.
    action_signals = [
        "i could do", "let's try", "i'll try",
        "i want to", "going to start",
    ]
    if any(s in msg_lower for s in action_signals):
        for goal_id, info in current_stages.items():
            if info["stage"] in ["preparation", "contemplation"]:
                return {
                    "update_warranted": True,
                    "goal_id": goal_id,
                    "new_stage": "action",
                    "evidence": (
                        "patient stated commitment to a "
                        "specific behavior change"),
                }

    # Pre-contemplation regression signals: patient is
    # disengaging.
    regression_signals = [
        "don't want to", "this isn't working",
        "give up", "tired of",
    ]
    if any(s in msg_lower for s in regression_signals):
        for goal_id, info in current_stages.items():
            if info["stage"] == "action":
                return {
                    "update_warranted": True,
                    "goal_id": goal_id,
                    "new_stage": "contemplation",
                    "evidence": (
                        "patient disengagement signals; "
                        "regress to support exploration"),
                }

    return {"update_warranted": False}

def _update_behavior_change_stage(*, patient_id, goal_id,
                                    new_stage, evidence):
    """Update the patient's behavior-change stage for a goal."""
    table = dynamodb.Table(LONGITUDINAL_STORE_TABLE)
    record = table.get_item(Key={"patient_id": patient_id})
    item = record.get("Item")
    if not item:
        return
    stages = item.get("behavior_change_stage_per_goal", {})
    stages[goal_id] = {
        "stage":      new_stage,
        "evidence":   evidence,
        "updated_at": _now_iso(),
    }
    item["behavior_change_stage_per_goal"] = stages
    table.put_item(Item=_to_decimal(item))

    _emit_event("behavior_change_stage_updated", {
        "patient_id": patient_id,
        "goal_id":    goal_id,
        "new_stage":  new_stage,
    })

    _put_metric("BehaviorChangeStageUpdated", 1, {
        "GoalId":   goal_id,
        "NewStage": new_stage,
    })
```

The system-prompt composition does most of the relationship-quality work. The stage guidance is the biggest single lever: it takes the same LLM and turns it into a different conversational partner depending on where the patient is. The same patient who needs gentle motivational-interviewing-style elicitation in pre-contemplation needs specific behavioral suggestions in action. A coach that does not adapt is a coach that helps the patients who would have done well anyway.

---

## Step 6: Output Safety Screening with Citation Grounding, Scope Verification, and Behavior-Change-Stage Tone Check

Every recommendation must trace to a cited care-plan element, clinical guideline, or institutional patient-education content. Scope verification rejects responses that attempt diagnosis, off-care-plan treatment recommendation, or new-condition guidance. The tone check verifies that the response is appropriate for the patient's behavior-change stage. Skip this and the coach occasionally produces ungrounded, off-scope, or stage-inappropriate responses.

```python
def screen_coach_output(*,
                         session_id,
                         patient_id,
                         response_text,
                         citations,
                         tool_calls,
                         longitudinal_context):
    """
    Output screening. Returns the final response payload or a
    safer template. Production runs an independent verifier
    model with structured-output validation; the demo runs
    rule-based checks that demonstrate the structure.
    """
    care_plan = longitudinal_context["care_plan"]
    longitudinal = longitudinal_context["longitudinal"]

    # Step 6A: scope checks specific to coaching.
    scope_violation = _detect_coaching_scope_violations(
        response_text)
    if scope_violation:
        if scope_violation["category"] == \
                "new_condition_diagnosis_attempted":
            return {
                "response":     OUT_OF_SCOPE_DIAGNOSIS_TEMPLATE,
                "disposition":  "scope_replaced",
                "citations":    [],
                "violation":    scope_violation["category"],
            }
        if scope_violation["category"] == \
                "off_care_plan_treatment_recommendation":
            return {
                "response":     OUT_OF_SCOPE_TREATMENT_TEMPLATE,
                "disposition":  "scope_replaced",
                "citations":    [],
                "violation":    scope_violation["category"],
            }
        return {
            "response":     UNGROUNDED_RESPONSE_FALLBACK,
            "disposition":  "scope_replaced",
            "citations":    [],
            "violation":    scope_violation["category"],
        }

    # Step 6B: citation verification. Every recommendation
    # must be grounded.
    citation_check = _verify_coaching_citations(
        response_text, citations, care_plan)
    if citation_check["has_ungrounded_assertions"]:
        return {
            "response":     UNGROUNDED_RESPONSE_FALLBACK,
            "disposition":  "ungrounded_replaced",
            "citations":    [],
        }

    # Step 6C: behavior-change-stage tone check. Production
    # runs a classifier; the demo runs a heuristic.
    tone_check = _verify_stage_appropriate_tone(
        response_text, longitudinal[
            "behavior_change_stage_per_goal"])
    if not tone_check["appropriate"]:
        # In production, regenerate with stage guidance. The
        # demo logs the issue and proceeds.
        logger.warning(
            "Stage-tone mismatch detected: %s",
            tone_check.get("reason"))
        _put_metric("StageToneMismatch", 1, {
            "Reason": tone_check.get("reason", "unknown")})

    # Step 6D: care-plan-deviation check.
    deviation_check = _check_care_plan_deviation(
        response_text, care_plan)
    if deviation_check["deviation_detected"]:
        # Escalate to the care team and replace the response.
        propose_escalation(
            patient_id=patient_id,
            trigger_reason="response_would_deviate_from_plan",
            trigger_event=deviation_check,
            care_plan_reference=care_plan["care_plan_id"])
        return {
            "response":     UNGROUNDED_RESPONSE_FALLBACK,
            "disposition":  "deviation_escalated",
            "citations":    [],
        }

    # Step 6E: persona-and-tone check. Production runs a
    # vendor-managed guardrail layer plus a tone evaluator;
    # the demo passes through.
    return {
        "response":     response_text,
        "disposition":  "delivered",
        "citations":    citations,
        "tool_calls":   tool_calls,
    }

def _detect_coaching_scope_violations(response_text):
    """
    Detect attempts at diagnosis, off-care-plan treatment
    recommendation, and other coaching-scope violations.
    """
    text_lower = response_text.lower()

    diagnosis_patterns = [
        "you have ", "i think you have",
        "this sounds like", "you probably have",
        "it appears you have",
    ]
    for pattern in diagnosis_patterns:
        if pattern in text_lower and \
                "in your care plan" not in text_lower:
            return {"category":
                    "new_condition_diagnosis_attempted",
                    "matched": pattern}

    treatment_patterns = [
        "i recommend taking", "you should take",
        "try taking", "start taking",
    ]
    for pattern in treatment_patterns:
        if pattern in text_lower and \
                "your care plan" not in text_lower:
            return {"category":
                    "off_care_plan_treatment_recommendation",
                    "matched": pattern}

    return None

def _verify_coaching_citations(response_text, citations,
                                 care_plan):
    """
    Verify that recommendations in the response are grounded
    in cited content. The demo runs a thin check; production
    uses an independent verifier model with structured-output
    validation.
    """
    # If the response contains a recommendation but no
    # citation, flag it. Heuristic recommendation detection
    # via patterns.
    recommendation_patterns = [
        "you should", "i'd suggest", "let's try",
        "what i recommend", "my recommendation",
    ]
    text_lower = response_text.lower()
    has_recommendation = any(
        p in text_lower for p in recommendation_patterns)
    if has_recommendation and not citations:
        return {"has_ungrounded_assertions": True,
                "reason": "recommendation_without_citation"}

    # If citations reference a care plan, verify it matches
    # the active plan.
    for citation in citations:
        if citation.get("kind") == "care_plan":
            if citation.get("id") != care_plan["care_plan_id"]:
                return {"has_ungrounded_assertions": True,
                        "reason": "stale_care_plan_citation"}

    return {"has_ungrounded_assertions": False}

def _verify_stage_appropriate_tone(response_text,
                                     stages_per_goal):
    """
    Verify that the response tone is appropriate for the
    patient's behavior-change stage.
    """
    text_lower = response_text.lower()
    primary_stage = "preparation"
    for info in stages_per_goal.values():
        primary_stage = info.get("stage", "preparation")
        break

    # Pre-contemplation should not get prescriptive language.
    prescriptive_patterns = [
        "you need to", "you must", "you should immediately",
    ]
    if primary_stage == "pre_contemplation":
        for pattern in prescriptive_patterns:
            if pattern in text_lower:
                return {"appropriate": False,
                        "reason":
                            "prescriptive_in_pre_contemplation"}

    return {"appropriate": True}

def _check_care_plan_deviation(response_text, care_plan):
    """
    Detect recommendations that would deviate from the care
    plan (different medication, different goal, different
    target). Production runs structured-output verification;
    the demo passes through.
    """
    return {"deviation_detected": False}
```

---

## Step 7: Persist the Durable Coaching-Decision Record and Longitudinal Updates

The conversation log captures the dialog. The coaching-decision-record journal captures, separately, every coaching decision (escalation events, biometric-threshold events, behavior-change-stage updates, care-plan-deviation events, recommendation-with-citation events) with version stamps. The longitudinal store is updated with any new disclosures, preference changes, or context the conversation revealed.

```python
def persist_coaching_artifacts(*,
                                 session_id,
                                 patient_id,
                                 response_payload,
                                 longitudinal_context):
    """
    Persist the conversation log, the coaching-decision
    record, the longitudinal-store updates, and the audit
    archive entry. Production runs each persistence target as
    its own Lambda with idempotency keys; the demo runs them
    sequentially.
    """
    care_plan = longitudinal_context["care_plan"]
    longitudinal = longitudinal_context["longitudinal"]

    # Step 7A: append the coach turn to the conversation log.
    metadata_table = dynamodb.Table(
        CONVERSATION_METADATA_TABLE)
    metadata_table.put_item(Item=_to_decimal({
        "session_id":           session_id,
        "kind":                 "turn",
        "speaker":              "coach",
        "text":                 response_payload["response"],
        "citations":            response_payload.get(
            "citations", []),
        "tool_calls_summary":   _summarize_tool_calls(
            response_payload.get("tool_calls", [])),
        "timestamp":            _now_iso(),
    }))

    # Step 7B: write coaching-decision records for each
    # coaching decision in the response.
    decision_table = dynamodb.Table(DECISION_RECORD_TABLE)
    decisions_recorded = []

    for decision in _extract_coaching_decisions(
            response_payload, longitudinal_context):
        decision_id = f"dec_{uuid.uuid4().hex}"
        record = {
            "decision_id":           decision_id,
            "session_id":            session_id,
            "patient_id":            patient_id,
            "decision_type":         decision["type"],
            "decision_payload":      decision["payload"],
            "citations":             decision.get(
                "citations", []),
            "active_care_plan_id":   care_plan["care_plan_id"],
            "active_care_plan_version":
                care_plan["care_plan_version"],
            "active_model_id":       ORCHESTRATION_MODEL_ID,
            "active_prompt_version": PROMPT_VERSION,
            "active_agent_version":  AGENT_VERSION,
            "active_stage_logic_version":
                STAGE_LOGIC_VERSION,
            "timestamp":             _now_iso(),
        }
        decision_table.put_item(Item=_to_decimal(record))

        # Mirror to S3 with Object Lock for the decision-
        # record archive.
        s3_key = (
            f"decisions/{patient_id}/"
            f"{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/"
            f"{decision_id}.json")
        s3_client.put_object(
            Bucket=DECISION_RECORD_BUCKET,
            Key=s3_key,
            Body=json.dumps(_from_decimal(record)),
            ServerSideEncryption="aws:kms")

        _emit_event("coaching_decision_recorded", {
            "decision_id":   decision_id,
            "decision_type": decision["type"],
            "patient_id":    patient_id,
            "care_plan_id":  care_plan["care_plan_id"],
        })

        decisions_recorded.append(decision_id)

    # Step 7C: extract and persist any longitudinal updates
    # that came out of the conversation (life-context
    # disclosures, preference changes, new follow-up items).
    updates = _extract_longitudinal_updates(
        response_payload, longitudinal_context)
    if updates["has_updates"]:
        longitudinal_table = dynamodb.Table(
            LONGITUDINAL_STORE_TABLE)
        # Read-modify-write. Production uses optimistic
        # concurrency; the demo collapses the path.
        record = longitudinal_table.get_item(
            Key={"patient_id": patient_id})
        if record.get("Item"):
            existing = record["Item"]
            disclosures = list(existing.get(
                "life_context_disclosures", []))
            for disclosure in updates.get(
                    "life_context_disclosures", []):
                disclosures.append(disclosure)
                _emit_event("life_context_recorded", {
                    "patient_id": patient_id,
                    "disclosure_category":
                        disclosure["category"],
                })
            existing["life_context_disclosures"] = disclosures
            longitudinal_table.put_item(
                Item=_to_decimal(existing))

    # Step 7D: schedule any follow-up engagements that came
    # out of tool calls in the conversation.
    for tool_call in response_payload.get("tool_calls", []):
        if tool_call["tool"] == "follow_up_schedule":
            args = tool_call.get("args", {})
            schedule_engagement(
                patient_id=patient_id,
                engagement_type=args.get(
                    "engagement_type", "scheduled_check_in"),
                delivery_target=
                    _now() + timedelta(
                        days=int(args.get("delay_days", 7))),
                priority="normal",
                context={
                    "care_plan_id": care_plan["care_plan_id"]})

    return {
        "action":             "persisted",
        "decisions_recorded": decisions_recorded,
    }

def _summarize_tool_calls(tool_calls):
    """Lightweight tool-call summary for the conversation log."""
    return [{"tool": tc["tool"]} for tc in tool_calls]

def _extract_coaching_decisions(response_payload,
                                  longitudinal_context):
    """
    Extract structured coaching decisions from the response.
    Each decision becomes its own record in the journal.
    """
    decisions = []

    # If the response contains a recommendation, that's a
    # decision.
    response_text = response_payload.get("response", "")
    citations = response_payload.get("citations", [])
    if citations:
        decisions.append({
            "type": "recommendation_made",
            "payload": {
                "response_summary": response_text[:200],
            },
            "citations": citations,
        })

    # Tool calls also become decisions where appropriate.
    for tool_call in response_payload.get("tool_calls", []):
        if tool_call["tool"] == "care_team_alert_propose":
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
        elif tool_call["tool"] == "escalation_propose":
            decisions.append({
                "type": "escalation_proposed",
                "payload": tool_call.get("args", {}),
                "citations": citations,
            })

    return decisions

def _extract_longitudinal_updates(response_payload,
                                    longitudinal_context):
    """
    Extract longitudinal-store updates from the conversation.
    Life-context disclosures, preference changes, new follow-
    ups.
    """
    updates = {"has_updates": False,
               "life_context_disclosures": []}

    for tool_call in response_payload.get("tool_calls", []):
        if tool_call["tool"] == \
                "longitudinal_disclosure_record":
            updates["has_updates"] = True
            updates["life_context_disclosures"].append({
                "category": tool_call.get("args", {})
                                .get("category", "unknown"),
                "recorded_at": _now_iso(),
            })

    return updates

def propose_escalation(*, patient_id, trigger_reason,
                        trigger_event, care_plan_reference):
    """
    Add an escalation event. Production routes per the
    institution's escalation taxonomy; the demo writes the
    alert to the care-team queue.
    """
    alert_id = f"alert_{uuid.uuid4().hex}"
    table = dynamodb.Table(CARE_TEAM_ALERT_QUEUE_TABLE)
    table.put_item(Item=_to_decimal({
        "alert_id":             alert_id,
        "patient_id":           patient_id,
        "trigger_reason":       trigger_reason,
        "trigger_event":        trigger_event,
        "care_plan_reference":  care_plan_reference,
        "status":               "pending_review",
        "created_at":           _now_iso(),
    }))

    _emit_event("escalation_triggered", {
        "alert_id":       alert_id,
        "patient_id":     patient_id,
        "trigger_reason": trigger_reason,
    })

    return alert_id
```

The persistence step is doing several things in parallel. The conversation log is one record class. The coaching-decision-record journal is a separately-governed record class with its own retention floor and Object-Lock protection. The longitudinal-store updates are a third concern. The follow-up scheduling is a fourth. In production, each of these runs as its own Lambda with idempotency keys, error handling, and DLQ; the demo collapses them for clarity. The decision-record-journal in particular is the audit trail that satisfies the regulatory and clinical-quality-review requirements; building this without it is a serious mistake.

---

## Step 8: Generate Care-Team Reports and Run Outcome Correlation

Real-time alerts flow to the care team for escalation events. Weekly digests summarize each patient's engagement, biometric trends, and key disclosures for the care team's review. The outcome-correlation pipeline pulls subsequent encounter records, lab results, prescription fills, and patient-reported outcomes, calculates per-cohort and per-condition outcome metrics, and feeds signals back to the care-plan-template revision process.

```python
def deliver_care_team_alerts():
    """
    Deliver pending care-team alerts. Production wires this
    to a Step Functions workflow polling the queue; the demo
    iterates synchronously.
    """
    table = dynamodb.Table(CARE_TEAM_ALERT_QUEUE_TABLE)
    delivered = []
    for record_list in table.items.values():
        for record in record_list:
            if record.get("status") != "pending_review":
                continue
            mock_care_team.deliver_alert({
                "alert_id":       record["alert_id"],
                "patient_id":     record["patient_id"],
                "trigger_reason":
                    record["trigger_reason"],
                "delivered_at":   _now_iso(),
            })
            _emit_event("care_team_alert_delivered", {
                "alert_id":   record["alert_id"],
                "patient_id": record["patient_id"],
            })
            delivered.append(record["alert_id"])
    return {"delivered_count": len(delivered)}

def compose_weekly_digest(patient_id, window_days=7):
    """
    Build a weekly digest of the patient's coaching activity
    for the care team. Production has a templated Lambda; the
    demo computes the structure inline.
    """
    longitudinal = _read_longitudinal_store(patient_id)
    care_plan = _read_active_care_plan(patient_id)
    if not longitudinal or not care_plan:
        return None

    cutoff = _now() - timedelta(days=window_days)

    # Engagement summary: scheduled, delivered, responded.
    eng_table = dynamodb.Table(ENGAGEMENT_SCHEDULE_TABLE)
    scheduled, delivered, responded = 0, 0, 0
    for record_list in eng_table.items.values():
        for record in record_list:
            if record.get("patient_id") != patient_id:
                continue
            scheduled_at = record.get("scheduled_at", "")
            if not scheduled_at or scheduled_at < cutoff.isoformat():
                continue
            scheduled += 1
            if record.get("status") == "delivered":
                delivered += 1
            if record.get("status") == "responded":
                responded += 1

    # Biometric trends: window the readings.
    bio_table = dynamodb.Table(BIOMETRIC_EVENT_STORE_TABLE)
    biometric_summary = defaultdict(list)
    for record_list in bio_table.items.values():
        for record in record_list:
            if record.get("patient_id") != patient_id:
                continue
            ts = record.get("reading_timestamp", "")
            if ts < cutoff.isoformat():
                continue
            device = record.get("device_type")
            biometric_summary[device].append(record["reading"])

    biometric_trends = {}
    for device, readings in biometric_summary.items():
        if device == "glucose_meter":
            values = [float(r.get("value", 0))
                      for r in readings if r.get("value")]
            if values:
                biometric_trends[device] = {
                    "average": round(sum(values) / len(values)),
                    "median": sorted(values)[len(values) // 2],
                    "readings_count": len(values),
                    "trend": "see-care-team-dashboard",
                }
        elif device == "blood_pressure":
            sys_values = [float(r.get("systolic", 0))
                          for r in readings
                          if r.get("systolic")]
            if sys_values:
                biometric_trends[device] = {
                    "average_systolic": round(
                        sum(sys_values) / len(sys_values)),
                    "readings_count": len(sys_values),
                }

    # Key disclosures within the window.
    disclosures = [
        d for d in longitudinal.get(
            "life_context_disclosures", [])
        if d.get("recorded_at", "") >= cutoff.isoformat()]

    # Behavior-change-stage updates.
    stage_updates = []
    for goal_id, info in longitudinal.get(
            "behavior_change_stage_per_goal", {}).items():
        if info.get("updated_at", "") >= cutoff.isoformat():
            stage_updates.append({
                "goal_id":  goal_id,
                "current_stage": info["stage"],
                "evidence": info.get("evidence", ""),
            })

    digest = {
        "patient_id":         patient_id,
        "preferred_name":
            longitudinal["patient_preferences"]
                .get("preferred_name", ""),
        "primary_condition":
            longitudinal["primary_condition"],
        "secondary_conditions":
            longitudinal.get("secondary_conditions", []),
        "report_window": {
            "start": cutoff.isoformat(),
            "end":   _now_iso(),
        },
        "engagement_summary": {
            "scheduled":  scheduled,
            "delivered":  delivered,
            "responded":  responded,
        },
        "biometric_trends":   biometric_trends,
        "key_disclosures":    disclosures,
        "behavior_change_stage_updates": stage_updates,
        "active_care_plan_id":
            care_plan["care_plan_id"],
        "active_care_plan_version":
            care_plan["care_plan_version"],
        "report_generated_at": _now_iso(),
    }

    mock_care_team.deliver_digest(digest)

    return digest

def queue_outcome_correlation(*, patient_id,
                                  window_start_days_ago=7):
    """
    Queue an outcome-correlation record for the patient.
    Production runs the full correlation pipeline: pull
    subsequent encounters, labs, prescription fills, and
    patient-reported outcomes; calculate per-protocol and
    per-cohort metrics; feed signals back to the care-plan-
    template revision process. The demo records the queue
    entry.
    """
    window_start = (_now() -
                     timedelta(days=window_start_days_ago)
                     ).isoformat()
    table = dynamodb.Table(OUTCOME_CORRELATION_TABLE)
    table.put_item(Item=_to_decimal({
        "patient_id":   patient_id,
        "window_start": window_start,
        "queued_at":    _now_iso(),
        "status":       "pending",
    }))

def run_outcome_correlation_pipeline():
    """
    Run the outcome-correlation pipeline over pending records.
    Production runs as a scheduled Step Functions workflow
    against the institutional encounter, lab, and pharmacy-
    fill data sources; the demo computes a tiny correlation
    against the mock pharmacy data.
    """
    table = dynamodb.Table(OUTCOME_CORRELATION_TABLE)
    completed = []
    for record_list in table.items.values():
        for record in record_list:
            if record.get("status") != "pending":
                continue
            patient_id = record["patient_id"]
            window_start = record["window_start"]
            window_end = _now_iso()

            fills = mock_pharmacy.get_fills(
                patient_id, window_start, window_end)

            correlation = {
                "patient_id":     patient_id,
                "window_start":   window_start,
                "window_end":     window_end,
                "prescription_fills_count": len(fills),
                "completed_at":   _now_iso(),
            }
            record["status"] = "completed"
            record["correlation"] = correlation

            _emit_event("outcome_correlation_completed", {
                "patient_id":     patient_id,
                "fills_count":    len(fills),
            })

            completed.append(patient_id)
    return {"completed_count": len(completed)}
```

---

## Full Pipeline

The functions above each handle one step. To run the coach end-to-end, wire them through one entry point that calls each in order.

```python
def coach_full_pipeline(*,
                          channel,
                          channel_session_id,
                          user_message,
                          auth_context):
    """
    Full pipeline: receive message -> screen -> handle ->
    output-screen -> persist -> queue outcome correlation.
    """
    # Step 4: receive and load context.
    intermediate = receive_message(
        channel=channel,
        channel_session_id=channel_session_id,
        user_message=user_message,
        auth_context=auth_context)

    # If the input layer already produced a final response
    # (emergency routing, blocked input), skip the rest.
    if isinstance(intermediate, dict) and \
            intermediate.get("disposition") in [
                "emergency_routed",
                "blocked",
                "no_care_plan_fallback"]:
        return intermediate

    # Step 5: generate the response.
    response_intermediate = handle_conversation(
        session_id=intermediate["session_id"],
        patient_id=intermediate["patient_id"],
        user_message=user_message,
        longitudinal_context=intermediate[
            "longitudinal_context"])

    # Step 6: output safety screening.
    screened = screen_coach_output(
        session_id=response_intermediate["session_id"],
        patient_id=response_intermediate["patient_id"],
        response_text=response_intermediate["response_text"],
        citations=response_intermediate["citations"],
        tool_calls=response_intermediate["tool_calls"],
        longitudinal_context=intermediate[
            "longitudinal_context"])

    # Step 7: persist artifacts.
    persist_coaching_artifacts(
        session_id=response_intermediate["session_id"],
        patient_id=response_intermediate["patient_id"],
        response_payload=screened,
        longitudinal_context=intermediate[
            "longitudinal_context"])

    # Step 8 (background): queue outcome correlation.
    queue_outcome_correlation(
        patient_id=response_intermediate["patient_id"])

    return screened
```

---

## Demo Runner

A small end-to-end demo that exercises enrollment, biometric ingestion, scheduled engagement, a multi-turn conversation, the care-team digest, and outcome correlation. Run this to see the structures populated and the events emitted.

```python
def run_demo():
    """End-to-end demo against the mock infrastructure."""
    print("=" * 60)
    print("CHRONIC DISEASE MANAGEMENT COACH DEMO")
    print("=" * 60)

    # Set up a synthetic patient.
    patient_id = "patient-maria"
    mock_ehr.add_patient(patient_id, {
        "active_problems":      ["type_2_diabetes",
                                   "hypertension"],
        "medications":          ["metformin 500mg bid",
                                   "lisinopril 10mg daily"],
        "baseline": {
            "a1c":              Decimal("8.2"),
            "fasting_glucose":  138,
        },
    })

    # Step 1: enroll the patient.
    print("\n--- Step 1: Enroll patient ---")
    result = enroll_patient(
        patient_id=patient_id,
        primary_condition="type_2_diabetes",
        secondary_conditions=["hypertension"],
        template_id="type_2_diabetes_lifestyle_plus_metformin",
        clinical_team_signoff={
            "clinicians": ["dr-pcp-id", "dr-endo-id"],
        },
        patient_consent={
            "granted":            True,
            "preferred_channels": ["sms", "in_app"],
            "language":           "en-US",
            "preferred_name":     "Maria",
            "max_daily_engagements": 1,
            "topic_optouts":      [],
        })
    print(f"  -> {result}")

    # Step 2: ingest biometric data over a few days.
    print("\n--- Step 2: Ingest biometric data ---")
    glucose_readings = [138, 145, 162, 168, 165, 175]
    for value in glucose_readings:
        mock_biometric_vendor.push_reading(
            patient_id, "glucose_meter",
            {"value": value, "context": "fasting"})
        biometric_data_received(
            patient_id=patient_id,
            device_type="glucose_meter",
            reading={"value": value,
                     "context": "fasting"})
    print(f"  -> ingested {len(glucose_readings)} readings")
    print(f"  -> scheduled engagements: "
          f"{len(mock_tables[ENGAGEMENT_SCHEDULE_TABLE].items)}")

    # Step 3: deliver a scheduled engagement.
    print("\n--- Step 3: Deliver scheduled engagement ---")
    eng_table = dynamodb.Table(ENGAGEMENT_SCHEDULE_TABLE)
    scheduled = []
    for record_list in eng_table.items.values():
        for record in record_list:
            if record.get("status") == "scheduled":
                scheduled.append(record)
                break
        if scheduled:
            break

    if scheduled:
        eng_result = deliver_scheduled_engagement(scheduled[0])
        print(f"  -> {eng_result}")
        if pinpoint_client.messages:
            last_msg = pinpoint_client.messages[-1]
            print(f"  -> message dispatched via Pinpoint")

    # Step 4-7: handle a multi-turn conversation.
    print("\n--- Step 4-7: Multi-turn conversation ---")
    messages = [
        "hi. yeah my mom is visiting from out of town "
        "and she's been doing all the cooking. its been "
        "hard to keep up with the meal stuff we talked "
        "about.",
        "i could do the morning thing. she sleeps late.",
    ]

    for i, message in enumerate(messages, start=1):
        print(f"\n  Turn {i}:")
        print(f"  Patient: {message}")
        result = coach_full_pipeline(
            channel="in_app",
            channel_session_id="session-001",
            user_message=message,
            auth_context={"patient_id": patient_id})
        print(f"  Coach:   {result['response']}")
        print(f"  -> disposition: {result['disposition']}")
        print(f"  -> citations:   "
              f"{len(result.get('citations', []))}")

    # Step 8: weekly digest and outcome correlation.
    print("\n--- Step 8: Weekly digest ---")
    digest = compose_weekly_digest(patient_id, window_days=7)
    if digest:
        print(f"  -> condition: {digest['primary_condition']}")
        print(f"  -> engagement: "
              f"{digest['engagement_summary']}")
        print(f"  -> biometric trends: "
              f"{list(digest['biometric_trends'].keys())}")
        print(f"  -> disclosures: "
              f"{len(digest['key_disclosures'])}")

    print("\n--- Outcome correlation pipeline ---")
    corr_result = run_outcome_correlation_pipeline()
    print(f"  -> {corr_result}")

    # Summary.
    print("\n" + "=" * 60)
    print("DEMO SUMMARY")
    print("=" * 60)
    print(f"EventBridge events emitted:    "
          f"{len(eventbridge_client.events)}")
    print(f"Pinpoint messages dispatched:  "
          f"{len(pinpoint_client.messages)}")
    print(f"S3 decision-journal records:   "
          f"{len(s3_client.objects)}")
    print(f"CloudWatch metrics emitted:    "
          f"{len(cloudwatch_client.metrics)}")
    print(f"Care-team alerts queued:       "
          f"{len(mock_care_team.alerts)}")
    print(f"Care-team digests delivered:   "
          f"{len(mock_care_team.digests)}")
    print(f"Tool-call ledger entries:      "
          f"{sum(len(v) for v in mock_tables[TOOL_CALL_LEDGER_TABLE].items.values())}")
    print(f"Coaching-decision records:     "
          f"{sum(len(v) for v in mock_tables[DECISION_RECORD_TABLE].items.values())}")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    run_demo()
```

---

## The Gap Between This and Production

This demo runs end-to-end and produces the right structure (longitudinal-store entries, biometric events with thresholded engagement triggers, scheduled engagements that respect quiet hours, conversations with care-plan-grounded responses, decision records with version stamps, weekly digests, queued outcome correlation), but the distance between it and a real coach serving an institution's chronic-disease panel is significant. Here is where that distance lives.

**Real Bedrock Agents action groups (or a custom LLM-and-tool orchestrator).** The demo runs canned responses from `MockBedrockRuntime`. Production wires the coaching tools (`care_plan_retrieve`, `biometric_data_retrieve`, `conversation_history_retrieve`, `patient_preferences_retrieve`, `clinical_guideline_retrieve`, `clinical_rule_compute`, `patient_education_content_retrieve`, `escalation_propose`, `care_team_alert_propose`, `follow_up_schedule`, `longitudinal_disclosure_record`, `behavior_change_stage_update`) as Bedrock Agents action groups (one OpenAPI spec per tool with the argument schema, the response schema, and the docstring the LLM uses to decide when to call it), gives the agent the institutional persona prompt, the care-plan context, and the Knowledge Base bindings (clinical guidelines, patient education, conversation history), and lets the LLM drive the multi-step reasoning, the tool-call orchestration, and the warm relationship-quality language. The Python flow above is helpful for understanding what tools exist; the production system lets the LLM compose the empathetic care-plan-aware language while the citation-grounding verifier and scope-filter keep the structure honest.

**Real Bedrock Knowledge Base ingestion of the clinical-guideline corpus, the patient-education library, and the longitudinal conversation history.** The demo's `EDUCATION_LIBRARY` is a hand-curated two-item dictionary; the guideline retrieval is mocked. Production has three Knowledge Bases: one ingesting the institution's curated clinical-guideline corpus per chronic condition (ADA standards for diabetes, ACC/AHA for HTN and HF, GINA for asthma, GOLD for COPD, KDIGO for CKD, APA for depression), with metadata filters for condition, version, and effective date; one ingesting the patient-education library with metadata filters for condition, audience, language, and reading level; and one indexing the patient-specific conversation history so the bot can find a thing the patient said three months ago when they reference it now. Each corpus has named ownership at the appropriate clinical-specialty leadership plus the patient-experience team plus compliance, with documented review cadence and versioned change-management workflow. Stale retrieval (the bot citing the prior guideline version after the institution has updated it) is a serious failure mode the corpus governance prevents.

**Real Bedrock Guardrails configuration.** The demo passes `GUARDRAIL_ID` but does not configure a Guardrail. Production configures restricted-topic filters for off-care-plan-treatment-recommendation, drug-prescription-attempted, new-condition-diagnosis-attempted, and off-protocol clinical claims at minimum, plus contextual-grounding for the response-generation steps. The Guardrail is pinned to a specific version, tested against a held-out evaluation set including coaching-injection cases (manipulate care-plan-retrieve to return a stale plan, manipulate behavior-change-stage-update to change stages without warrant, manipulate escalation-propose to suppress alerts, manipulate longitudinal-disclosure-record to plant false disclosures), and updated on a versioned-rollout cadence with canary traffic.

**Real care-plan-corpus governance.** The demo's `CARE_PLAN_TEMPLATES` has two illustrative templates. Production has 6-15 condition templates plus multi-condition variants, each owned by the appropriate clinical-specialty leadership (endocrinology for diabetes, cardiology for HF and HTN, pulmonology for COPD and asthma, psychiatry for depression, nephrology for CKD), reviewed before adoption, reviewed annually, and re-reviewed on material updates. Each patient's instantiated care plan is signed by the patient's clinical team. The templates are versioned with effective dates; the conversation log records which care-plan version was active for any given coaching event. Building a coach without clinical-leadership ownership of the templates is a serious mistake.

**Real continuous-emergency-screening pipeline with a tuned classifier.** The demo's `_emergency_screen` uses keyword detection. Production layers a tuned classifier on top of keyword detection, tests the screening layer against a held-out emergency-presentation corpus curated and reviewed by clinical leadership before launch and on each material update, and treats false-negative rate as a launch-gate metric. Per-emergency-category sensitivity targets (cardiac-acute, stroke, HF-decompensation, DKA, severe-hypoglycemia, hypertensive-emergency, anaphylaxis, psychiatric-crisis) are documented; the false-negative rate is monitored continuously and feeds the protocol-revision process.

**Real Step Functions engagement-scheduling workflow.** The demo writes engagement records to DynamoDB and invokes the delivery synchronously. Production runs the engagement scheduler as a Step Functions state machine with delay states (so the durable scheduling survives Lambda outages and region failover), with the engagement-policy enforcement re-checked at each delivery time (the patient may have changed preferences since the engagement was scheduled), with fatigue detection running on a rolling 30-day window, and with explicit fatigue-mitigation logic that reduces cadence when response rates drop below the floor.

**Real engagement-policy enforcement with patient-experience review.** The demo's `_enforce_engagement_policy` checks quiet hours, daily caps, and topic opt-outs. Production has the engagement policy documented, reviewed by patient-experience leadership and compliance, audited operationally, and updated based on attrition signals. Engagement attrition is the central operational risk for chronic-disease coaching; the policy is the primary lever for mitigating it.

**Real behavior-change-stage signal logic with clinical-leadership review.** The demo's `_evaluate_behavior_change_signals` is a keyword heuristic. Production has the stage-signal logic owned by behavioral-health-experienced clinicians, validated against held-out cases, and reviewed in the clinical-quality-review process. The conversation-style adaptation per stage is reviewed; the per-cohort calibration is monitored. Per-stage transition rate is monitored; rapid stage changes can be a sign of mis-calibration.

**Real biometric-vendor integrations.** The demo's `MockBiometricVendor` is a dict. Production wires the biometric-data-retrieve tool to one client per vendor (Dexcom for CGM, Withings/Omron for BP, Bodyport/Withings for scale, others as relevant), with each vendor's specific authentication flow, rate-limit handling, error handling, data-validation, and monitoring. Device-status monitoring with patient-facing notifications when device data is missing for an extended period is part of production scope. AWS HealthLake (or the institution's FHIR-native Observation store) is the canonical biometric-data integration target where the institution stores device data in FHIR.

**Real chart-context integration with FHIR resources.** The demo's `MockEHR` returns a flat dict. Production wires the care-plan-retrieve tool to the institution's FHIR-native data store (AWS HealthLake, Epic on FHIR, Cerner on FHIR, or a vendor-specific FHIR layer) or to the EHR's native API where FHIR is unavailable. The tool retrieves Patient, Condition (active problem list), MedicationStatement, AllergyIntolerance, Encounter, Observation (for biometric data stored in FHIR), CarePlan, and Goal resources, with controls on what data is exposed to the LLM versus what stays in the back-office. Stale chart-context (a patient whose chart was last updated three months ago) is flagged with as-of dates so the bot's response acknowledges the freshness limit.

**Real care-team workflow integration.** The demo's `MockCareTeamWorkflow` accumulates alerts and digests in memory. Production wires the care-team alert and digest delivery to the institution's case-management system (Epic Healthy Planet, Cerner Population Health, or vendor-specific platforms) or the EHR's task-list integration, with alert-channel configuration, weekly-digest delivery surface, monthly-summary delivery surface, quarterly-clinical-review packet generation, and a care-team feedback-path tooling. Care-team-operations signoff on display is a launch gate.

**Real triage and mental-health pathway integration.** The demo's `MockTriagePathway` and `MockMentalHealthPathway` accumulate hand-offs in memory. Production wires the emergency-routing and mental-health-routing tools to the institution's triage system (recipe 11.6) and mental-health support system (recipe 11.8), with the conversation context, the chronic-coach state, and the patient's longitudinal record attached to the hand-off so the receiving system does not start from scratch. Tabletop drills exercise the hand-off quarterly.

**Real DynamoDB and S3 wiring.** The mocks are dictionaries; production is DynamoDB tables with on-demand or provisioned capacity, customer-managed KMS keys, point-in-time recovery on the longitudinal-store, conversation, ledger, decision-record, engagement-schedule, biometric, alert-queue, and outcome-correlation tables, TTL on the conversation-state table tuned for typical session durations, and DynamoDB Streams emitting change events for downstream consumers. The coaching-decision-record-journal S3 bucket has SSE-KMS, Object Lock in compliance mode, lifecycle to S3 Glacier Instant Retrieval after 30 days and Glacier Deep Archive after 90, and retention sized to the longest of HIPAA's six-year minimum, the state's medical-record retention rules (often 7-10+ years for adult records, sometimes longer for pediatric records), FDA SaMD post-market obligations where applicable, and the institutional regulatory floor. The audit archive has its own KMS key separate from the decision-journal KMS key for blast-radius containment.

**KMS customer-managed keys per data class.** Every PHI-bearing resource uses customer-managed KMS keys with key rotation enabled. Different KMS keys for different data classes (longitudinal-store, conversation-state, decision-journal, audit-archive, biometric-data archive, Secrets Manager secrets) limit the blast radius of any single key compromise. Key access is scoped to the specific principals that need it; CloudTrail logs every key-usage event.

**VPC and VPC endpoints.** The chat-handler Lambda runs internet-facing through API Gateway. The tool Lambdas that call the EHR, biometric-vendor APIs, care-team workflow, pharmacy systems, and care-navigation systems run in a VPC with PrivateLink (where supported) or a tightly-scoped NAT-gateway path with allow-list. VPC endpoints for Bedrock, DynamoDB, S3, KMS, Secrets Manager, EventBridge, Step Functions, and CloudWatch Logs keep AWS-internal traffic off the public internet.

**WAF tuning for coaching traffic patterns.** Coaching endpoints have rate limits tuned for chat-typical traffic (legitimate engaged patients sometimes type rapidly during a check-in; rate limits should not block them) plus bot-detection rules that allow legitimate accessibility tools while blocking automated abuse, plus geo-restrictions if applicable, plus managed rule groups for common attack patterns. Patient-initiated emergency conversations are not subject to the standard rate limit; production gates this with a separate priority lane.

**Per-Lambda IAM least privilege with separation of concerns.** The demo uses a single set of mocked credentials. Production has one IAM role per Lambda (chat handler, input screening, continuous-emergency-screening, identity handling, each tool implementation, biometric ingestion, engagement-scheduler dispatch, output screening, decision-record-persistence, care-team-reporting, audit archival, outcome correlation), each scoped to the specific resource ARNs the Lambda touches. The care-plan-retrieve Lambda has read-only access to the FHIR CarePlan and Goal resources. The biometric-data-retrieve Lambda has read access to the biometric event store. The clinical-rule-compute Lambdas have no external-system access (pure compute). The care-team-alert-propose Lambda has the access required to post alerts to the care-team workflow system. None of the coach's Lambdas have write access to the clinical record except for institutionally-approved coaching-event records (FHIR Communication resources for the conversation log; FHIR Observation resources for patient-reported data where the institution permits coach-originated observations).

**FDA-strategy artifact with regulatory-counsel review.** The institutional regulatory positioning (informational coaching with clinician oversight in regulated edge cases, or registered SaMD) is documented, reviewed by FDA-experienced regulatory counsel, and maintained as the deployment evolves. Architectural changes that may affect regulatory positioning are reviewed against the artifact. Post-market surveillance obligations for SaMD-positioned deployments are operationalized. The institutional malpractice insurer is part of the policy review. Building a coach without an FDA-strategy artifact is a serious mistake; chronic-disease management software providing direct guidance about medications or self-management sits on or close to the FDA SaMD line.

**Per-cohort accuracy and equity monitoring with launch gates.** The demo emits CloudWatch metrics with per-condition and per-channel dimensions, which is enough for per-category dashboards. Production stratifies by cohort axes the institution monitors (per-language, per-channel, per-condition, per-age-cohort, per-sex, per-behavior-change-stage, per-social-determinant-flag, per-engagement-intensity), plus two-axis cohorts (per-language-by-channel, per-condition-by-age, per-condition-by-engagement-intensity), and treats per-cohort threshold compliance as a launch gate. Engagement rate, attrition rate, escalation rate, outcome metrics (A1c trajectory, BP control rate, hospitalization rate, ED visit rate, medication adherence), citation-coverage rate, regulatory-disclaimer-presence rate, intent-classification accuracy, behavior-change-stage estimation accuracy, and patient-satisfaction all get sliced. A cohort with materially lower engagement rate or higher attrition rate after controlling for condition mix is a clinical-quality and equity issue that aggregate metrics hide. Launch is gated on every cohort meeting the threshold, not on the institution-wide average. Per-cohort dashboards reviewed by clinical-specialty leadership, care-management operations, compliance, and patient-experience teams.

**Outcome-correlation pipeline with operational ownership.** The demo's `run_outcome_correlation_pipeline` runs a tiny correlation against mock pharmacy data. Production has the pipeline pulling subsequent encounter records (institutional ED, urgent care, primary care, hospital admissions, plus claims data where available for cross-institution utilization), lab results, prescription fills, and patient-reported outcomes within multiple windows (30-day, 90-day, 12-month), calculating per-condition and per-cohort outcome metrics, and feeding signals back to the care-plan-template-revision process. Operational ownership is jointly held by the clinical-specialty leadership, the care-management operations team, the data science team, and compliance. The pipeline is multi-quarter post-launch work; it is rarely fully implemented at launch but is a core post-launch commitment.

**Multilingual deployment with validated translations.** The demo is English-only. Most U.S. health-system patient populations include meaningful non-English-speaking groups, and many states have language-access requirements for certain payer and provider communications. Per-language work: validated guideline translations (with the translation reviewed by clinical leadership for clinical equivalency, not just linguistic equivalency), validated patient-education content translations, validated regulatory-disclaimer phrasings, validated emergency-instruction phrasings, per-language tone and persona calibration, per-language equity monitoring. Spanish-language deployment typically takes three to four additional months beyond the English go-live; ad-hoc machine translation is not acceptable for chronic-disease coaching content.

**Voice-channel deployment for accessibility.** The conversational logic above runs in chat. Adding a voice channel through Amazon Connect with Lex V2 reuses the orchestration logic but adds ASR and TTS layers, tighter latency budgets, voice-specific design (slower pacing, explicit confirmation of high-stakes inputs, voice-friendly recommendation phrasing), and ASR error monitoring scoped to the coaching vocabulary. The voice channel makes the coach accessible to patients without smartphones or with disabilities that make text input difficult. Accessibility is not a generic web-accessibility checklist; it is a coaching-specific set of design decisions about cognitive load, sentence length, and graceful degradation when the patient cannot complete the conversation.

**Citation-grounding verifier with structured-output schema validation.** The demo's `_verify_coaching_citations` implements a heuristic check. Production runs an independent verifier model with structured-output schema validation between Bedrock generation and response delivery, grounding every recommendation to a cited care-plan element, clinical-guideline reference, or institutional patient-education content with version stamping. The faithfulness check uses rule-based contradiction detection, omission detection, a regenerate-attempt budget, and a fall-back-to-safe-response default. Per-cohort faithfulness-failure rate is a launch-gate metric.

**Compensation operations for incorrect or disputed recommendations.** When a patient or clinician disputes a coach response or recommendation, the operations team reproduces the conversation, retrieves the cited care plan and guidelines, and either confirms the coach followed the protocol correctly (escalating the underlying care-plan question) or confirms the coach deviated from the plan (compensating the patient and feeding the failure mode into the improvement loop). Tooling for this workflow is part of production scope and is reviewed by compliance. Disputes are retained for the longer of the institutional record-retention floor and any FDA SaMD post-market obligations.

**Disaster-recovery and degraded-mode operation.** When upstream dependencies fail (Bedrock outage, EHR unreachable, biometric-vendor API down, care-team workflow integration unreachable, clinical-guideline corpus unavailable), the coach must degrade gracefully. The minimum behavior is "I'm having trouble pulling that data right now; for anything urgent please contact your care team at [number]" or, in the case of detected emergency, immediate 911 routing. Per-source failover behavior is documented and tested quarterly. Cross-region failover for Bedrock and the institutional integrations. Cached recent emergency-screening responses can serve as backstop when the Bedrock-hosted classifier is unreachable.

**Patient-rights workflow for conversation logs and decision records.** Conversation logs are dense longitudinal PHI plus may include sensitive disclosures. Decision records are clinically-significant. Patients have rights to access both. The institution has retention obligations that vary by state and by record class. Build the workflow: how a patient requests their coaching-conversation history and decision records, how the requests are authenticated, how the data is produced, how deletion requests interact with retention obligations, and how the decision records are referenced from the patient portal for the patient's own access.

**Mandatory-reporting pathway integration.** Some coaching conversations surface disclosures (child abuse, elder abuse, intimate-partner violence, certain mental-health emergencies) that trigger statutory reporting obligations for licensed clinicians. The coach itself is not a licensed clinician. The production system detects these disclosures, routes them to a clinical staff member who is a mandatory reporter (with the conversation context attached), and follows the institutional policy specifying how disclosures are handled per state and per disclosure type. The state-by-state variation in mandatory-reporting laws is significant; the institutional legal and compliance teams own the routing matrix.

**Continuous-improvement loop with structured failure-mode labeling.** Production transcripts surface presenting situations the team did not have content for, retrieval gaps in the guideline corpus, emergency-screening misses, citation gaps, behavior-change-stage-mismatch cases, and patterns in the decision-record journal that point to operational issues. Build the labeling and review workflow: review production transcripts weekly with clinical-specialty leadership, care-management operations, compliance, and data science, propose care-plan-template updates, propose guideline-corpus updates, propose emergency-screening updates, run them through the evaluation set, deploy via versioned aliases, monitor for regressions. The coach's quality at month six is determined by whether someone is doing this work, not by how good the launch was.

**Build-vs-buy rigor.** Several mature commercial vendors offer chronic-disease coaching products with EHR integration, multilingual support, biometric-device integration, and (in some cases) FDA-authorized digital-therapeutic content. Most major institutions run a hybrid: in-house coach for the routine member-facing journey on the institution's preferred infrastructure, vendor partnership for licensed condition-specific content and (sometimes) for the human-coach workforce. The decision between full-build, full-buy, and hybrid depends on the institution's regulatory positioning, the scale of the patient population, the institutional appetite for clinical-content ownership, and the maturity of the institutional integration team.

**Testing.** There are no tests in this demo. A production pipeline has unit tests for the input-screening logic, the continuous-emergency-screening logic (each emergency category fires correctly across condition contexts), the engagement-policy enforcement (quiet hours, daily caps, topic opt-outs, fatigue detection), the biometric-threshold evaluation (each device type, each threshold class), the care-plan instantiation (each template instantiates correctly, signoff is captured, version stamping works), the behavior-change-stage signal logic (each transition fires on appropriate evidence), the citation-grounding verifier (every recommendation traces to a citation; care-plan citations match the active version), the output-screening replacement logic, the longitudinal-store update logic, and the outcome-correlation pipeline. Integration tests against a Bedrock test environment, non-production EHR endpoints with synthetic data, and a non-production guideline corpus. End-to-end tests that simulate full coaching journeys through representative scenarios including the diabetes-newly-diagnosed case, the diabetes-stable-engaged case, the diabetes-attrition-risk case, the heart-failure-post-discharge case, the hypertension-medication-titration case, the multi-condition case, the emergency-detected-mid-coaching case, the medication-discontinuation-disclosure case, and the sensitive-disclosure cases. Never use real PHI in test fixtures.

**Observability beyond metrics.** The demo emits CloudWatch metrics but no traces and no structured logs ready for cross-call investigation. Production runs CloudWatch Logs Insights queries that join across the API Gateway logs, the chat-handler logs, the screening logs, the Bedrock invocation traces, the tool-Lambda logs, the decision-record journal, and the audit records by session_id and patient_id. AWS X-Ray traces show the latency contribution of each step. When a single conversation goes wrong, the on-call engineer needs to reconstruct the full trace in seconds, not minutes.

**Cost monitoring and per-conversation attribution.** Bedrock's per-token charges, Knowledge Bases' per-query charges, the vector store's hosting charges, Pinpoint's per-message charges, and the per-call costs of the upstream-system integrations add up. Some coaching conversations are dramatically more expensive than others (a multi-turn medication-titration conversation with extensive guideline retrieval, output-verification regeneration, and care-team alert generation costs more than a one-shot scheduled check-in). The cost-per-condition and cost-per-active-member analytics let the operations team see which conditions are economically efficient and which warrant tooling improvements. Per-active-member infrastructure cost is small relative to the cost of even a single avoided hospitalization, but per-conversation attribution makes the cost story explicit.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 11.7: Chronic Disease Management Coach](chapter11.07-chronic-disease-management-coach) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
