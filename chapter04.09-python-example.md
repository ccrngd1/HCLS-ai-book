# Recipe 4.9: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 4.9. It shows one way you could translate the personalized care plan generation pattern into working Python using AWS HealthLake for FHIR-native clinical state retrieval, Amazon SageMaker Feature Store for per-patient features, Amazon DynamoDB for the goal templates, action templates, plan-input records, plan records, plan narratives, plan-action records, and plan-feedback records, Amazon S3 for the plan archive, AWS Step Functions for the plan-generation orchestration, AWS Lambda for the per-stage glue, Amazon Bedrock for the clinician-facing, patient-facing, and care-team-internal disagreement narratives, Amazon Kinesis for plan generation, action completion, outcome, and feedback events, Amazon EventBridge for scheduled review and event-driven plan-revision triggers, Amazon API Gateway and Cognito for the clinician plan-review surface (typically a SMART on FHIR app), and Amazon Pinpoint for patient-facing delivery in the patient's preferred channel. It is not production-ready. There is no real EHR, claims, lab, pharmacy, or registry feed integration, no real upstream-recipe signal aggregation, no clinically curated goal-template or action-template library (the example ships a small synthetic catalog), no real drug-drug or drug-disease interaction database integration, no validated burden-scoring model, no real capacity-and-schedule reconciliation against staffing systems, no SMART on FHIR plan-review surface, no patient portal integration, no real activation dispatcher to e-prescribing or scheduling systems, no FHIR `CarePlan`-with-linked-`Goal`-`Task`-`ServiceRequest` persistence in HealthLake, no clinical-content-team-led template review, no regulatory analysis. Think of it as the sketchpad version: useful for understanding the shape of a structured-then-narrative care-plan generation pipeline that respects multi-condition reconciliation, goals-of-care alignment, therapeutic-burden compression, the four-layer LLM validator, and the structured plan as the system of record. It is not something you would wire into an EHR on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the six pseudocode steps from the main recipe: aggregate inputs and freeze them in a plan-input record, derive the goal set from condition-specific guidelines plus goals-of-care preferences plus quality-program requirements, assemble candidate actions and run multi-condition reconciliation (interactions, deprescribing, burden, capacity, schedule), finalize the structured plan record, generate the clinician-facing, patient-facing, and care-team-internal narratives with strict four-layer validator and templated fallback, and activate approved actions plus capture feedback plus trigger plan revisions. All sample patients, conditions, medications, goals, actions, narratives, and feedback events are synthetic. The patient in the demo is Linda from the recipe's opening narrative.

---

## Setup

You will need the AWS SDK for Python and a couple of utility libraries:

```bash
pip install boto3 pandas
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchWriteItem` on the goal-templates, action-templates, plan-input-records, plan-records, plan-narratives, plan-action-records, plan-feedback-records, and surveillance-alerts tables
- `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on the cp-archives bucket (plan inputs, plan records, narratives)
- `bedrock:InvokeModel` on the specific foundation-model ARNs used for clinician-facing narratives, patient-facing narratives, and care-team-internal disagreement narratives
- `kinesis:PutRecord` on the cp-events stream
- `events:PutEvents` on the EventBridge bus that routes plan-revision triggers
- `healthlake:SearchWithGet` and related read actions scoped to the relevant data store (the FHIR-native clinical data substrate)
- `sagemaker:GetRecord` on the `patient-features-online` Feature Group
- `pinpoint:SendMessages` scoped to the relevant Pinpoint application (patient-facing delivery)
- `cloudwatch:PutMetricData` for cohort-stratified plan-quality metrics
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs

You also need model access enabled in the Bedrock console for the narrative-generation models.

A few things worth knowing upfront:

- **The clinical-content library is the substrate of the system.** Goal templates and action templates are the artifacts the rest of the pipeline operates on. This example ships with a small synthetic catalog covering a handful of conditions (CHF, T2D, CKD, depression, colorectal cancer screening) plus a "goals-of-care" goal type. Production maintains hundreds of templates with cohort overrides, evidence references, versioning, and a clinical-content review committee that approves changes.
- **Structured-then-narrative is the entire discipline.** The LLM produces words about decisions the structured logic has already made. The structured plan record is the system of record; the narratives are rendered on top with strict validator enforcement. Skip this and the LLM becomes the source of truth, which is the failure mode that makes care plan generation systems clinically unsafe.
- **The four-layer validator is non-negotiable.** Schema, fact grounding, prohibited-language patterns, and required content. Failed validations regenerate with feedback or fall back to a deterministic templated narrative that always passes.
- **Bedrock model IDs change over time.** Some regions require cross-region inference profile IDs (prefixed `us.` or `eu.`). The IDs below are reasonable defaults; verify in the Bedrock console for your region before running.
- **All patients, conditions, medications, goals, actions, narratives, and feedback events in the example are synthetic.** Do not treat any specific patient_id, plan_id, narrative, or action as real. A production system ingests from real EHR, FHIR, claims, lab, pharmacy, and registry feeds under BAA.
- **The example collapses Step Functions, Lambda, EventBridge, and Bedrock into a single Python file for readability.** In production these are separate workflow stages with their own error handling, IAM, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Model IDs, table names, S3 buckets, validator thresholds, burden thresholds, and the catalog of goal and action templates are the knobs you would change between environments.

```python
import json
import logging
import re
import time
import uuid
import datetime
from datetime import timezone, timedelta
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records to
# CloudWatch Logs Insights. Never log a raw (patient_id, plan_id,
# goal_set, action_set) join. The row implicitly identifies the
# patient, the active condition list, the goals-of-care posture, and
# the care-team plan; the plan-records, plan-narratives, and
# plan-feedback-records tables are clinical-record-equivalent PHI.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, Bedrock, Kinesis,
# S3, EventBridge, and HealthLake. Plan generation is multi-stage and
# can run for tens of seconds end-to-end; transient throttling from
# any one service should not fail the whole plan.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
kinesis_client = boto3.client("kinesis", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
eventbridge_client = boto3.client("events", config=BOTO3_RETRY_CONFIG)
cloudwatch_client = boto3.client("cloudwatch", config=BOTO3_RETRY_CONFIG)

# --- Bedrock Model Configuration ---
# Three distinct LLM use cases. Clinician-facing narratives go to a
# Sonnet-class model because the prompt is long-context (full plan
# record plus what-changed plus care-team-attention items) and the
# fact-grounding validator is strict; the larger model gives a better
# first-pass-pass rate. Patient-facing narratives can use a
# Haiku-class model for cost efficiency where reading-level allows;
# disagreement narratives are internal-facing and short.
CLINICIAN_NARRATIVE_MODEL_ID    = "anthropic.claude-3-5-sonnet-20241022-v2:0"
PATIENT_NARRATIVE_MODEL_ID       = "anthropic.claude-3-5-haiku-20241022-v1:0"
INTERNAL_NARRATIVE_MODEL_ID      = "anthropic.claude-3-5-haiku-20241022-v1:0"

# --- DynamoDB Table Names ---
# Eight tables. Keep them separate so access patterns stay clean and
# IAM scoping is precise:
#   1. goal-templates:           clinical-content goal templates
#   2. action-templates:         clinical-content action templates
#   3. plan-input-records:       frozen inputs per plan run (audit baseline)
#   4. plan-records:             structured plan record (system of record)
#   5. plan-narratives:          LLM-generated narratives per audience
#   6. plan-action-records:      action status tracking through plan lifecycle
#   7. plan-feedback-records:    action completion, outcome, and patient feedback
#   8. surveillance-alerts:      cohort-fairness and plan-quality alerts
GOAL_TEMPLATES_TABLE        = "goal-templates"
ACTION_TEMPLATES_TABLE       = "action-templates"
PLAN_INPUT_RECORDS_TABLE     = "plan-input-records"
PLAN_RECORDS_TABLE           = "plan-records"
PLAN_NARRATIVES_TABLE        = "plan-narratives"
PLAN_ACTION_RECORDS_TABLE    = "plan-action-records"
PLAN_FEEDBACK_RECORDS_TABLE  = "plan-feedback-records"
SURVEILLANCE_ALERTS_TABLE    = "surveillance-alerts"

# --- S3 Buckets ---
# Production: each bucket has its own KMS key and bucket policy.
# Replace placeholder names with your account's buckets.
CP_ARCHIVES_BUCKET     = "cp-archives"
CP_DATA_LAKE_BUCKET    = "cp-data-lake"

# --- Kinesis ---
# Same engagement-event-bus pattern as Recipes 4.4 through 4.8, with
# new event types specific to this recipe: plan_inputs_aggregated,
# goals_derived, actions_assembled, plan_finalized,
# narrative_validator_fallback, plan_activated, plan_feedback_recorded,
# plan_revision_triggered.
CP_EVENTS_STREAM_NAME = "cp-events"

# --- EventBridge ---
EVENTBRIDGE_BUS_NAME = "cp-revision-bus"

# --- Run Configuration ---
POLICY_VERSION = "cp-policy-v0.1"

# Validator regeneration attempts before falling back to templated narrative.
MAX_REGENERATION_ATTEMPTS = 2

# Maximum acceptable cumulative burden in the action set before
# prioritization compression kicks in. Production: per-patient
# threshold tuned to functional status, cognitive status, social
# support, and stated preferences. The example uses a single global
# default that can be overridden per patient.
DEFAULT_BURDEN_THRESHOLD = 12.0

# Minimum size of a similar-cohort match before cohort-comparison
# narratives are surfaced. Below this, the comparison is too noisy
# to act on.
MIN_COHORT_COMPARISON_SIZE = 30

# Fairness instrumentation thresholds. Plan ambition disparity (e.g.,
# the average action count or burden in cohort A versus cohort B) at
# or above these levels triggers a surveillance alert.
COHORT_DISPARITY_ALERT_THRESHOLD = 0.25

# Plan review SLA: the clinical team must review the plan within this
# many days of generation. The review-due-at field on the plan record
# is set from this.
REVIEW_SLA_DAYS = 4

# Patient-facing narrative reading-level target. Production: per-patient
# target read from the patient profile; defaults to grade 6 per
# health-literacy best practices for adult populations.
DEFAULT_READING_LEVEL_TARGET = "grade_6"

# CloudWatch namespace for care-plan metrics. Slice by plan_status,
# audience, validator outcome, and cohort axis to catch subgroup drift.
METRIC_NAMESPACE = "PersonalizedCarePlan"
```

---

## Reference Data: Synthetic Clinical Content Library

A small clinical content library used by the example. Production loads from the `goal-templates` and `action-templates` DynamoDB tables, fed by a clinical-content review committee (clinical informatics, pharmacy and therapeutics, care management, quality, patient education) through a governance UI and versioned. Each template has cohort overrides, evidence references, contraindications, and provenance.

```python
# Synthetic goal templates. Five condition-linked goals plus one
# patient-stated-preference goal that comes through goals-of-care.
# Production has hundreds of goals across condition combinations,
# with cohort overrides for pediatric, geriatric, palliative,
# pregnancy, and other special populations.
SAMPLE_GOAL_TEMPLATES = [
    {
        "goal_template_id":      "gt-chf-readmission-prevention",
        "goal_id":               "chf_avoid_readmission",
        "condition_id":          "I50.22",   # CHF with reduced EF
        "horizon":               "next_12_months",
        "measurable_outcome":    "no_chf_related_admission",
        "evidence_level":        "guideline_strong",
        "baseline_priority":     9.5,
        "quality_program_links": ["cms_stars_readmission"],
        "cohort_overrides":      {},
        "version":               "2026-v1",
        "status":                "active",
    },
    {
        "goal_template_id":      "gt-t2d-a1c-control",
        "goal_id":               "diabetes_a1c_under_8",
        "condition_id":          "E11.9",   # T2D
        "horizon":               "next_quarter",
        "measurable_outcome":    "a1c_below_8_at_q3",
        "evidence_level":        "guideline_strong",
        "baseline_priority":     7.8,
        "quality_program_links": ["hedis_cdc_a1c"],
        "cohort_overrides": {
            # Looser A1c target for older adults with frailty.
            "geriatric_frail": {"measurable_outcome": "a1c_below_8.5_at_q3",
                                  "baseline_priority": 6.5},
        },
        "version":               "2026-v1",
        "status":                "active",
    },
    {
        "goal_template_id":      "gt-ckd-egfr-stabilization",
        "goal_id":               "ckd_egfr_stabilization",
        "condition_id":          "N18.32",  # CKD stage 3b
        "horizon":               "ongoing",
        "measurable_outcome":    "egfr_decline_under_2_per_year",
        "evidence_level":        "guideline_strong",
        "baseline_priority":     8.0,
        "quality_program_links": [],
        "cohort_overrides":      {},
        "version":               "2026-v1",
        "status":                "active",
    },
    {
        "goal_template_id":      "gt-depression-phq9-remission",
        "goal_id":               "depression_phq9_remission",
        "condition_id":          "F32.1",   # Depression
        "horizon":               "next_6_months",
        "measurable_outcome":    "phq9_under_5",
        "evidence_level":        "guideline_moderate",
        "baseline_priority":     7.2,
        "quality_program_links": [],
        "cohort_overrides":      {},
        "version":               "2026-v1",
        "status":                "active",
    },
    {
        "goal_template_id":      "gt-colon-cancer-screening",
        "goal_id":               "colon_cancer_screening",
        "condition_id":          "Z12.11",  # Encounter for screening for malig
                                              # neoplasm of colon
        "horizon":               "next_quarter",
        "measurable_outcome":    "colonoscopy_completed",
        "evidence_level":        "guideline_strong",
        "baseline_priority":     6.0,
        "quality_program_links": ["hedis_col"],
        "cohort_overrides": {
            # Suppressed in palliative-care cohorts where preventive
            # screening is not aligned with goals of care.
            "palliative_focused": {"removal_flag": True,
                                     "removal_reason": "not_aligned_with_goc"},
        },
        "version":               "2026-v1",
        "status":                "active",
    },
]

# Synthetic action templates. Multiple actions per goal, with owner
# roles, due-date logic, success criteria, fallback chains,
# dependencies, burden scores, and contraindications. Production
# has thousands of templates with much richer metadata.
SAMPLE_ACTION_TEMPLATES = [
    # CHF actions
    {
        "action_template_id":   "at-diuretic-daily-morning",
        "action_id":            "diuretic_daily_morning",
        "goal_link":            "chf_avoid_readmission",
        "owner_role":           "patient",
        "horizon":              "this_week",
        "due_date_logic":       "ongoing",
        "clinical_payload": {
            "kind":         "self_management",
            "instruction":  "take_furosemide_40mg_at_8am_daily",
            "medication":   "furosemide_40mg_oral",
        },
        "success_criteria":     "self_reported_compliance_5_of_7_days",
        "fallback_chain":       ["care_manager_call_at_2_missed_doses"],
        "fallback_required":    True,
        "dependencies":         [],
        "burden_score":         1.5,
        "contraindications":    [],
        "cohort_overrides":     {},
        "version":              "2026-v1",
        "status":               "active",
    },
    {
        "action_template_id":   "at-weight-daily-log",
        "action_id":            "weight_daily_log",
        "goal_link":            "chf_avoid_readmission",
        "owner_role":           "patient",
        "horizon":              "this_week",
        "due_date_logic":       "ongoing",
        "clinical_payload": {
            "kind":         "self_management",
            "instruction":  "weigh_morning_after_void_log_in_portal",
        },
        "success_criteria":     "5_of_7_days_logged",
        "fallback_chain":       ["care_manager_call_if_no_log_3_days"],
        "fallback_required":    True,
        "dependencies":         [],
        "burden_score":         1.0,
        "contraindications":    [],
        # Cognitive impairment override: family caregiver becomes
        # the owner when patient cannot reliably self-track.
        "cohort_overrides": {
            "cognitive_impairment_moderate": {
                "owner_role": "family_caregiver",
                "burden_score": 1.5,
            },
        },
        "version":              "2026-v1",
        "status":               "active",
    },
    {
        "action_template_id":   "at-cardiac-rehab-enrollment",
        "action_id":            "cardiac_rehab_enrollment",
        "goal_link":            "chf_avoid_readmission",
        "owner_role":           "cardiology_clinic_scheduler",
        "horizon":              "this_quarter",
        "due_date_logic":       "30_days_from_index",
        "clinical_payload": {
            "kind":         "program_enrollment",
            "instruction":  "enroll_cardiac_rehab_local_site_with_transport",
        },
        "success_criteria":     "completes_first_4_sessions",
        "fallback_chain":       ["home_based_cardiac_rehab_if_facility_attendance_fails"],
        "fallback_required":    True,
        "dependencies":         ["transport_benefit_verified"],
        "burden_score":         4.0,
        "contraindications":    [],
        "cohort_overrides":     {},
        "version":              "2026-v1",
        "status":               "active",
    },
    # T2D actions
    {
        "action_template_id":   "at-a1c-recheck-q3",
        "action_id":            "a1c_recheck_q3",
        "goal_link":            "diabetes_a1c_under_8",
        "owner_role":           "pcp",
        "horizon":              "this_quarter",
        "due_date_logic":       "90_days_from_index",
        "clinical_payload": {
            "kind":         "lab_order",
            "instruction":  "order_hba1c_at_3_months",
        },
        "success_criteria":     "a1c_resulted_in_window",
        "fallback_chain":       ["telehealth_visit_for_lab_order"],
        "fallback_required":    True,
        "dependencies":         [],
        "burden_score":         1.0,
        "contraindications":    [],
        "cohort_overrides":     {},
        "version":              "2026-v1",
        "status":               "active",
    },
    # CKD-related action; surface as deprescribing candidate when
    # NSAID is on the patient's medication list.
    {
        "action_template_id":   "at-naproxen-for-oa-pain",
        "action_id":            "naproxen_for_oa_pain",
        "goal_link":            "ckd_egfr_stabilization",
        "owner_role":           "patient",
        "horizon":              "this_week",
        "due_date_logic":       "ongoing",
        "clinical_payload": {
            "kind":         "medication",
            "instruction":  "take_naproxen_500mg_bid_for_oa_pain",
            "medication":   "naproxen_500mg_oral",
        },
        "success_criteria":     "pain_score_under_3",
        "fallback_chain":       ["topical_nsaid_substitute"],
        "fallback_required":    True,
        "dependencies":         [],
        "burden_score":         1.0,
        # Strong contraindication in CHF and in CKD3b. The
        # interaction filter suppresses this action.
        "contraindications":    ["chf_severe", "egfr_under_45"],
        "cohort_overrides":     {},
        "version":              "2026-v1",
        "status":               "active",
    },
    # Depression actions
    {
        "action_template_id":   "at-phq9-followup-with-pcp",
        "action_id":            "phq9_followup_with_pcp",
        "goal_link":            "depression_phq9_remission",
        "owner_role":           "pcp",
        "horizon":              "this_month",
        "due_date_logic":       "21_days_from_index",
        "clinical_payload": {
            "kind":         "appointment",
            "instruction":  "phq9_reassessment_visit",
        },
        "success_criteria":     "visit_completed",
        "fallback_chain":       ["telehealth_visit_if_in_person_declined"],
        "fallback_required":    True,
        "dependencies":         [],
        "burden_score":         2.0,
        "contraindications":    [],
        "cohort_overrides":     {},
        "version":              "2026-v1",
        "status":               "active",
    },
    # Colorectal screening actions
    {
        "action_template_id":   "at-colonoscopy-with-transport",
        "action_id":            "colonoscopy_with_transport",
        "goal_link":            "colon_cancer_screening",
        "owner_role":           "care_manager",
        "horizon":              "this_month",
        "due_date_logic":       "30_days_from_index",
        "clinical_payload": {
            "kind":         "scheduling_with_benefit",
            "instruction":  "book_colonoscopy_arrange_plan_transport",
        },
        "success_criteria":     "colonoscopy_completed",
        "fallback_chain":       ["fit_test_if_colonoscopy_declined"],
        "fallback_required":    True,
        "dependencies":         ["transport_benefit_verified"],
        "burden_score":         3.0,
        "contraindications":    [],
        "cohort_overrides":     {},
        "version":              "2026-v1",
        "status":               "active",
    },
    # Care management ongoing action
    {
        "action_template_id":   "at-care-manager-monthly-checkin",
        "action_id":            "care_manager_monthly_checkin",
        "goal_link":            "chf_avoid_readmission",   # primary link;
                                                              # serves multiple goals
        "owner_role":           "care_manager",
        "horizon":              "ongoing",
        "due_date_logic":       "monthly",
        "clinical_payload": {
            "kind":         "outreach",
            "instruction":  "monthly_phone_checkin_followup_on_goals",
        },
        "success_criteria":     "monthly_call_completed_each_month",
        "fallback_chain":       ["pcp_outreach_if_2_months_missed"],
        "fallback_required":    True,
        "dependencies":         [],
        "burden_score":         1.5,
        "contraindications":    [],
        "cohort_overrides":     {},
        "version":              "2026-v1",
        "status":               "active",
    },
    # Goals-of-care driven action: ACP conversation
    {
        "action_template_id":   "at-advance-care-planning-visit",
        "action_id":            "advance_care_planning_visit",
        "goal_link":            "stay_at_home",
        "owner_role":           "social_worker",
        "horizon":              "this_quarter",
        "due_date_logic":       "60_days_from_index",
        "clinical_payload": {
            "kind":         "appointment",
            "instruction":  "structured_acp_conversation_in_home",
        },
        "success_criteria":     "polst_completed_with_patient_signature",
        "fallback_chain":       ["telehealth_acp_if_in_home_declined"],
        "fallback_required":    True,
        "dependencies":         [],
        "burden_score":         2.5,
        "contraindications":    [],
        "cohort_overrides":     {},
        "version":              "2026-v1",
        "status":               "active",
    },
]

# Quality-program weighting catalog. Goals linked to active quality
# measures get an additional weight multiplier. Production: maintained
# by the quality team, with effective dates per program year.
SAMPLE_QUALITY_PROGRAM_WEIGHTS = {
    "cms_stars_readmission":  1.20,
    "hedis_cdc_a1c":          1.10,
    "hedis_col":              1.05,
}
```

---

## Shared Helpers

A handful of utilities used across steps. Pulled together here so each step's logic stays focused.

```python
def _now_iso() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    return datetime.datetime.now(timezone.utc).isoformat()

def _today_str() -> str:
    """Current UTC date as YYYY-MM-DD string."""
    return datetime.datetime.now(timezone.utc).date().isoformat()

def _emit_metric(name: str, value: float, dimensions: dict) -> None:
    """
    Emit a CloudWatch custom metric. Swallows errors so a metric-publish
    failure never breaks plan generation. Metric publishing is
    best-effort observability, not a correctness boundary.
    Filters out None-valued dimensions: CloudWatch rejects them and
    the rejected request loses the rest of the metric data too.
    """
    try:
        clean_dims = [
            {"Name": k, "Value": str(v)[:255]}
            for k, v in dimensions.items() if v is not None
        ]
        cloudwatch_client.put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[{
                "MetricName": name,
                "Dimensions": clean_dims,
                "Value":      float(value),
                "Unit":       "Count",
            }],
        )
    except Exception as exc:
        logger.warning("Metric publish failed for %s: %s", name, exc)

def _to_decimal(value) -> Decimal:
    """
    DynamoDB does not accept Python floats. Going through str avoids
    binary-precision issues. Wrap floats at the persistence boundary
    and forget about it.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def _to_decimal_dict(d: dict) -> dict:
    """Recursively convert numeric values in a dict to Decimal for DynamoDB."""
    out = {}
    for k, v in d.items():
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = _to_decimal(v)
        elif isinstance(v, dict):
            out[k] = _to_decimal_dict(v)
        elif isinstance(v, list):
            out[k] = [
                _to_decimal_dict(x) if isinstance(x, dict)
                else _to_decimal(x) if isinstance(x, (int, float)) and not isinstance(x, bool)
                else x
                for x in v
            ]
        else:
            out[k] = v
    return out

def _from_decimal(value):
    """Inverse of _to_decimal for reading DynamoDB items into Python."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _from_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_decimal(v) for v in value]
    return value

def _safe_get_item(table, key: dict) -> dict:
    """
    Wrap DynamoDB get_item with try/except so the demo's
    table-not-provisioned path returns {} instead of crashing.
    Production logs and re-raises on real ResourceNotFoundException
    only when the table genuinely should exist.
    """
    try:
        response = table.get_item(Key=key)
        return _from_decimal(response.get("Item") or {})
    except Exception as exc:
        logger.warning("get_item on %s failed: %s",
                        getattr(table, "name", "table"), exc)
        return {}

def _make_plan_input_id() -> str:
    """Opaque plan-input record identifier."""
    return f"input-{uuid.uuid4().hex[:16]}"

def _make_plan_id() -> str:
    """
    Opaque plan identifier.

    NOTE: A PHI-safe id. Production-equivalent guidance: never embed
    plain-text patient_id, plan_version, or condition strings into
    identifiers that travel in URLs, EHR responses, event payloads,
    or logs. Use UUIDs or HMAC-SHA256 over the composite with a
    per-environment secret. Mirror the language flagged in 4.4
    through 4.8.
    """
    return f"plan-{uuid.uuid4().hex[:16]}"

def _make_narrative_id() -> str:
    return f"narr-{uuid.uuid4().hex[:16]}"

def _make_action_record_id() -> str:
    return f"par-{uuid.uuid4().hex[:16]}"

def _make_feedback_id() -> str:
    return f"fb-{uuid.uuid4().hex[:16]}"

def _make_activation_id() -> str:
    return f"act-{uuid.uuid4().hex[:16]}"

def _redact_for_llm(payload: dict) -> dict:
    """
    Strip patient and clinician identifiers from a payload before
    sending to an LLM. The LLM does not need them, and stripping
    at the boundary limits any vendor-side logging exposure.
    Bedrock service terms commit to not training on prompts, but
    defense-in-depth still applies.
    """
    redacted = json.loads(json.dumps(payload, default=str))
    for field in ("patient_id", "clinician_id", "plan_id",
                   "plan_input_id", "narrative_id", "decision_id",
                   "activation_id", "feedback_id"):
        _strip_field(redacted, field)
    return redacted

def _strip_field(obj, field: str) -> None:
    """Recursively remove a field from a nested dict/list structure."""
    if isinstance(obj, dict):
        obj.pop(field, None)
        for v in obj.values():
            _strip_field(v, field)
    elif isinstance(obj, list):
        for v in obj:
            _strip_field(v, field)

def _cohort_features_from_profile(patient: dict) -> dict:
    """Pull cohort features for fairness instrumentation from the profile."""
    return {
        "language":                 patient.get("preferred_language", "en"),
        "race_ethnicity_self_report": patient.get(
            "race_ethnicity_self_report", "unknown"),
        "sdoh_cohort":              patient.get("sdoh_cohort", "unknown"),
        "age_band":                 patient.get("age_band", "unknown"),
    }

def _try_fetch_upstream(recipe_name: str, patient_id: str, default):
    """
    Generic stub for fetching signals from upstream Recipes 4.1-4.8.
    Production: each upstream has its own client, table, and feature
    store integration. The demo returns the default and lets the
    runner inject real signals into a side-table by patient_id.
    """
    upstream = _DEMO_UPSTREAM_SIGNALS.get(recipe_name, {})
    return upstream.get(patient_id, default)

# Demo state populated by the runner.
_DEMO_UPSTREAM_SIGNALS: dict = {}
_DEMO_HEALTHLAKE_BUNDLES: dict = {}
_DEMO_FEATURE_STORE: dict = {}
_DEMO_GOALS_OF_CARE: dict = {}
_DEMO_SDOH: dict = {}
_DEMO_FUNCTIONAL_STATUS: dict = {}
_DEMO_FAMILY_CAREGIVERS: dict = {}
_DEMO_PRIOR_PLANS: dict = {}
```

---

## Step 1: Aggregate Inputs and Freeze Them in a Plan-Input Record

*The pseudocode calls this `aggregate_plan_inputs(patient_id, request_context)`. Plan generation depends on a snapshot of the patient's state and the upstream signals from Recipes 4.1 through 4.8. The aggregation is at a single point in time, with the inputs frozen so the plan can be reproduced and audited. Skip the freezing step and a plan generated on Tuesday cannot be reproduced from Wednesday's data, which makes investigation of any later issue impossible.*

```python
def aggregate_plan_inputs(patient_id: str,
                            request_context: dict) -> dict:
    """
    Build the plan-input record by pulling clinical state from FHIR,
    patient features from Feature Store, upstream signals from
    Recipes 4.1 through 4.8, goals-of-care, SDOH, functional status,
    family caregivers, and the prior plan.

    Persists the input record (DynamoDB + S3) and emits an event.
    Returns the plan-input record dict.
    """
    plan_input_id = _make_plan_input_id()
    plan_input_record = {
        "plan_input_id":   plan_input_id,
        "patient_id":      patient_id,
        "request_context": request_context,
        "captured_at":     _now_iso(),
    }

    # Step 1A: clinical state from FHIR (HealthLake in production).
    # The example reads from a synthetic bundle keyed by patient_id.
    # Production: HealthLake.SearchWithGet for Condition,
    # MedicationRequest, Observation, Encounter, AllergyIntolerance,
    # CareTeam, then normalize into a structured shape.
    plan_input_record["clinical_state"] = _normalize_clinical_state(
        _DEMO_HEALTHLAKE_BUNDLES.get(patient_id, {})
    )

    # Step 1B: patient features from the Feature Store. Production:
    # SageMaker Feature Store online-store GetRecord for the
    # patient-features-online feature group. The demo reads from a
    # synthetic dict.
    plan_input_record["patient_features"] = _DEMO_FEATURE_STORE.get(
        patient_id, {}
    )

    # Step 1C: upstream signals from Recipes 4.1 through 4.8. Each
    # signal is fetched independently; missing signals are recorded
    # rather than failing the whole aggregation. A care plan can be
    # generated without (e.g.) Recipe 4.8 treatment-response
    # predictions if those are not available; the plan should
    # reflect what is and is not available.
    plan_input_record["channel_preferences"] = _try_fetch_upstream(
        "recipe-4.1", patient_id, default=None,
    )
    plan_input_record["educational_content_matches"] = _try_fetch_upstream(
        "recipe-4.2", patient_id, default=[],
    )
    plan_input_record["provider_relationships"] = _try_fetch_upstream(
        "recipe-4.3", patient_id, default=[],
    )
    plan_input_record["wellness_program_candidates"] = _try_fetch_upstream(
        "recipe-4.4", patient_id, default=[],
    )
    plan_input_record["adherence_interventions"] = _try_fetch_upstream(
        "recipe-4.5", patient_id, default=[],
    )
    plan_input_record["care_gap_inventory"] = _try_fetch_upstream(
        "recipe-4.6", patient_id, default=[],
    )
    plan_input_record["care_management_enrollment"] = _try_fetch_upstream(
        "recipe-4.7", patient_id, default=None,
    )
    plan_input_record["treatment_response_predictions"] = _try_fetch_upstream(
        "recipe-4.8", patient_id, default=[],
    )

    # Step 1D: goals-of-care preferences. POLST forms, advance
    # directives, structured ACP conversations, patient-portal
    # preference questionnaires.
    plan_input_record["goals_of_care"] = _DEMO_GOALS_OF_CARE.get(
        patient_id, {}
    )

    # Step 1E: social determinants and functional/cognitive status.
    plan_input_record["sdoh"] = _DEMO_SDOH.get(patient_id, {})
    plan_input_record["functional_status"] = _DEMO_FUNCTIONAL_STATUS.get(
        patient_id, {}
    )
    plan_input_record["family_caregivers"] = _DEMO_FAMILY_CAREGIVERS.get(
        patient_id, []
    )

    # Step 1F: prior plan, if any. The current plan is the baseline
    # for revision; the goal is incremental update where possible
    # rather than full regeneration.
    plan_input_record["prior_plan"] = _DEMO_PRIOR_PLANS.get(patient_id)

    # Persist the input record. Immutable; this is the audit baseline
    # for the plan.
    inputs_table = dynamodb.Table(PLAN_INPUT_RECORDS_TABLE)
    try:
        inputs_table.put_item(Item=_to_decimal_dict(plan_input_record))
    except Exception as exc:
        logger.warning(
            "Failed to persist plan-input record %s: %s",
            plan_input_id, exc,
        )

    try:
        s3_client.put_object(
            Bucket=CP_ARCHIVES_BUCKET,
            Key=f"inputs/{plan_input_id}.json",
            Body=json.dumps(plan_input_record, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to archive plan-input record %s: %s",
            plan_input_id, exc,
        )

    try:
        kinesis_client.put_record(
            StreamName=CP_EVENTS_STREAM_NAME,
            PartitionKey=patient_id,
            Data=json.dumps({
                "event_type":      "plan_inputs_aggregated",
                "patient_id":      patient_id,
                "plan_input_id":   plan_input_id,
                "request_context": request_context,
                "timestamp":       _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return plan_input_record

def _normalize_clinical_state(bundle: dict) -> dict:
    """
    Map a FHIR bundle into the simplified shape the rest of the
    pipeline consumes. Production: walk the resource list, extract
    Condition.code.coding entries with clinicalStatus = active,
    MedicationRequest with status = active, recent Observation entries
    by LOINC code, etc. The demo passes the bundle through if it is
    already in the simplified shape.
    """
    if not bundle:
        return {"conditions": [], "medications": [], "labs": {},
                 "encounters": [], "allergies": []}
    return {
        "conditions":  bundle.get("conditions", []),
        "medications": bundle.get("medications", []),
        "labs":        bundle.get("labs", {}),
        "encounters":  bundle.get("encounters", []),
        "allergies":   bundle.get("allergies", []),
    }
```

---

## Step 2: Derive the Goal Set

*The pseudocode calls this `derive_goal_set(plan_input_record)`. Goals are the structural backbone of the plan. Condition-specific guidelines drive the baseline goal set; goals-of-care preferences re-weight (or in some cases remove) goals; quality-program requirements add measure-linked weighting. Skip the goals-of-care alignment and you produce an aggressive disease-management plan for a patient who has elected comfort-focused care, which is exactly the failure mode that erodes patient trust.*

```python
def derive_goal_set(plan_input_record: dict,
                      goal_templates: list) -> list:
    """
    Build the goal set:
      A. Match conditions to goal templates with cohort overrides
      B. Apply goals-of-care alignment
      C. Apply quality-program weighting
      D. Add patient-stated-preference goals from goals-of-care
      E. Deduplicate goals that surface from multiple conditions
      F. Rank by priority weight

    Returns a list of goal dicts. Each goal carries provenance so
    a clinician reviewing the plan can see why each goal is present
    and why it is weighted as it is.
    """
    goal_set = []
    conditions = plan_input_record.get("clinical_state", {}).get(
        "conditions", []
    )
    cohort_tags = _compute_cohort_tags(plan_input_record)

    # Step 2A: condition-driven goals.
    for condition in conditions:
        if not condition.get("active"):
            continue
        for template in goal_templates:
            if template["condition_id"] != condition["condition_id"]:
                continue
            if template.get("status") != "active":
                continue
            applied = _apply_cohort_overrides(template, cohort_tags)
            if applied is None:
                # Cohort override removed this template entirely.
                continue
            goal_set.append({
                "goal_id":               applied["goal_id"],
                "source_template":       applied["goal_template_id"],
                "source_template_version": applied["version"],
                "source_condition":      condition["condition_id"],
                "horizon":               applied["horizon"],
                "measurable_outcome":    applied["measurable_outcome"],
                "priority_weight":       applied["baseline_priority"],
                "evidence_level":        applied["evidence_level"],
                "quality_program_links": list(
                    applied.get("quality_program_links", [])),
                "cohort_overrides_applied": applied.get(
                    "_overrides_applied", []),
                "removed_by_goals_of_care": False,
                "provenance": {
                    "source":      "condition_guideline",
                    "condition_id": condition["condition_id"],
                    "template_id": applied["goal_template_id"],
                },
            })

    # Step 2B: goals-of-care alignment. Patient preferences re-weight
    # or remove goals. A patient with comfort_focused_flag = True
    # sees aggressive-disease-management goals down-weighted; a
    # patient with explicit-decline-of-treatment preferences sees
    # the corresponding goals removed.
    goc = plan_input_record.get("goals_of_care", {})
    for goal in goal_set:
        adj = _compute_goc_adjustment(goal, goc)
        goal["goals_of_care_adjustment"] = adj
        if not adj["retain_flag"]:
            # Mark removed by goals-of-care alignment; do not silently
            # drop. The clinician-facing narrative will surface what
            # was removed and why.
            goal["removed_by_goals_of_care"] = True
            goal["removal_reason"] = adj["override_reason"]
            continue
        goal["priority_weight"] *= adj["weight_multiplier"]

    # Step 2C: quality-program weighting. Goals linked to active
    # measures get an additional weight multiplier.
    for goal in goal_set:
        if goal["removed_by_goals_of_care"]:
            continue
        for program in goal.get("quality_program_links", []):
            mult = SAMPLE_QUALITY_PROGRAM_WEIGHTS.get(program, 1.0)
            goal["priority_weight"] *= mult

    # Step 2D: patient-stated-preference goals. A "stay at home"
    # preference becomes a first-class goal; the goals-of-care
    # input drives this.
    if goc.get("comfort_focused_flag") or goc.get("stated_preferences", {}).get(
        "prefer_stay_at_home"
    ):
        goal_set.append({
            "goal_id":               "stay_at_home",
            "source_template":       "patient_stated_preference",
            "source_template_version": "n/a",
            "source_condition":      None,
            "horizon":               "ongoing",
            "measurable_outcome":    "no_skilled_nursing_admission",
            "priority_weight":       9.8,
            "evidence_level":        "patient_stated_preference",
            "quality_program_links": [],
            "cohort_overrides_applied": [],
            "removed_by_goals_of_care": False,
            "provenance": {
                "source":          "goals_of_care",
                "preference_id":   "pref-stay-home",
            },
        })

    # Step 2E: deduplicate goals that surface from multiple
    # conditions (rare in this small catalog; production catalogs
    # have many cross-condition goals).
    goal_set = _deduplicate_goals(goal_set)

    # Step 2F: rank by priority weight (descending). Bottom-of-list
    # goals are candidates for prioritization compression in Step 3.
    goal_set.sort(key=lambda g: g["priority_weight"], reverse=True)

    try:
        kinesis_client.put_record(
            StreamName=CP_EVENTS_STREAM_NAME,
            PartitionKey=plan_input_record["patient_id"],
            Data=json.dumps({
                "event_type":         "goals_derived",
                "patient_id":         plan_input_record["patient_id"],
                "plan_input_id":      plan_input_record["plan_input_id"],
                "goal_count":         len(goal_set),
                "removed_by_goc_count": sum(
                    1 for g in goal_set
                    if g.get("removed_by_goals_of_care")),
                "timestamp":          _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return goal_set

def _compute_cohort_tags(plan_input_record: dict) -> set:
    """
    Compute the set of cohort tags that drive cohort overrides on
    templates. Production: a richer rules engine with explicit cohort
    membership criteria; the demo uses a few coarse tags pulled from
    the patient features and goals-of-care.
    """
    tags = set()
    features = plan_input_record.get("patient_features", {})
    goc = plan_input_record.get("goals_of_care", {})
    func = plan_input_record.get("functional_status", {})

    age = features.get("age", 0)
    if age >= 75:
        tags.add("geriatric_75_plus")
    if features.get("frailty_index", 0) >= 0.25:
        tags.add("geriatric_frail")
    cog = func.get("cognitive_status")
    if cog == "moderate_impairment":
        tags.add("cognitive_impairment_moderate")
    if cog == "severe_impairment":
        tags.add("cognitive_impairment_severe")
    if goc.get("comfort_focused_flag"):
        tags.add("palliative_focused")
    return tags

def _apply_cohort_overrides(template: dict, cohort_tags: set) -> dict:
    """
    Apply cohort overrides on a template. If a cohort tag matches
    an override key with a `removal_flag`, return None (template
    is suppressed for this cohort). Otherwise merge the override
    fields onto a copy of the template and return it.
    """
    overrides = template.get("cohort_overrides", {}) or {}
    applied_keys = []
    out = dict(template)
    for tag in cohort_tags:
        override = overrides.get(tag)
        if override is None:
            continue
        if override.get("removal_flag"):
            return None
        # Merge override fields. Numeric fields replace; list fields
        # are merged.
        for k, v in override.items():
            out[k] = v
        applied_keys.append(tag)
    out["_overrides_applied"] = applied_keys
    return out

def _compute_goc_adjustment(goal: dict, goc: dict) -> dict:
    """
    Compute the goals-of-care adjustment for a single goal.

    Returns:
      { weight_multiplier, retain_flag, override_reason }

    Production: explicit per-goal-id rules curated by the clinical-
    content team. The demo uses a small set of coarse rules.
    """
    if not goc:
        return {"weight_multiplier": 1.0, "retain_flag": True,
                 "override_reason": None}

    # Comfort-focused: aggressive screening goals are removed;
    # readmission-prevention is retained but down-weighted because
    # the patient may want to avoid hospital stays for any reason.
    if goc.get("comfort_focused_flag"):
        if goal["goal_id"] == "colon_cancer_screening":
            return {"weight_multiplier": 0.0, "retain_flag": False,
                     "override_reason": "comfort_focused_no_screening"}
        if goal["goal_id"] == "diabetes_a1c_under_8":
            return {"weight_multiplier": 0.6, "retain_flag": True,
                     "override_reason": "comfort_focused_loosen_a1c"}

    # Explicit-decline list: any goal whose ID is in the decline list
    # is removed.
    declines = goc.get("explicit_declines", []) or []
    if goal["goal_id"] in declines:
        return {"weight_multiplier": 0.0, "retain_flag": False,
                 "override_reason": "patient_explicit_decline"}

    # Stay-at-home preference up-weights goals that align (e.g.,
    # readmission prevention) and slightly down-weights goals that
    # require facility visits.
    if goc.get("stated_preferences", {}).get("prefer_stay_at_home"):
        if goal["goal_id"] == "chf_avoid_readmission":
            return {"weight_multiplier": 1.10, "retain_flag": True,
                     "override_reason": "preference_stay_at_home_aligns"}

    return {"weight_multiplier": 1.0, "retain_flag": True,
             "override_reason": None}

def _deduplicate_goals(goal_set: list) -> list:
    """
    Merge goals that share a goal_id (surfaced from multiple
    conditions). The merged goal carries the union of source
    templates and the maximum priority weight.
    """
    by_id = {}
    for goal in goal_set:
        gid = goal["goal_id"]
        if gid not in by_id:
            by_id[gid] = dict(goal)
            by_id[gid]["provenance_list"] = [goal["provenance"]]
        else:
            existing = by_id[gid]
            existing["priority_weight"] = max(
                existing["priority_weight"], goal["priority_weight"]
            )
            existing.setdefault("provenance_list", []).append(
                goal["provenance"]
            )
            existing["quality_program_links"] = list(set(
                existing.get("quality_program_links", []) +
                goal.get("quality_program_links", [])
            ))
    return list(by_id.values())
```

---

## Step 3: Assemble Candidate Actions and Run Reconciliation

*The pseudocode calls this `assemble_and_reconcile_actions(goal_set, plan_input_record)`. Action assembly produces the candidate set; reconciliation removes infeasible actions, surfaces deprescribing candidates, and compresses the action set to a feasible total burden. Reconciliation is where the multi-condition synthesis actually happens; skip it and you produce an action set that looks comprehensive on paper and is unworkable in practice.*

```python
def assemble_and_reconcile_actions(goal_set: list,
                                       plan_input_record: dict,
                                       action_templates: list) -> dict:
    """
    Generate candidate actions for each retained goal, then run the
    reconciliation pipeline:
      A. Per-goal action generation with cohort overrides
      B. Drug-drug, drug-disease, drug-allergy interaction filtering
      C. Deprescribing candidate generation
      D. Burden estimation and prioritization compression
      E. Capacity reconciliation
      F. Schedule reconciliation

    Returns { actions, reconciliation } where reconciliation captures
    every decision made along the way for the audit trail and the
    clinician-facing narrative.
    """
    cohort_tags = _compute_cohort_tags(plan_input_record)
    candidate_actions = []

    # Step 3A: per-goal action generation.
    for goal in goal_set:
        if goal.get("removed_by_goals_of_care"):
            continue
        for template in action_templates:
            if template.get("status") != "active":
                continue
            if template["goal_link"] != goal["goal_id"]:
                continue
            applied = _apply_cohort_overrides(template, cohort_tags)
            if applied is None:
                continue
            candidate_actions.append({
                "action_id":             applied["action_id"],
                "source_template":       applied["action_template_id"],
                "source_template_version": applied["version"],
                "goal_link":             goal["goal_id"],
                "owner_role":            applied["owner_role"],
                "horizon":               applied["horizon"],
                "due_date_logic":        applied["due_date_logic"],
                "clinical_payload":      applied["clinical_payload"],
                "success_criteria":      applied["success_criteria"],
                "fallback_chain":        list(
                    applied.get("fallback_chain", [])),
                "fallback_required":     applied.get("fallback_required",
                                                       False),
                "dependencies":          list(applied.get("dependencies", [])),
                "burden_score":          float(applied["burden_score"]),
                "contraindications":     list(
                    applied.get("contraindications", [])),
                "cohort_overrides_applied": applied.get(
                    "_overrides_applied", []),
                "provenance": {
                    "source_template": applied["action_template_id"],
                    "goal_link":       goal["goal_id"],
                },
            })

    # Step 3B: drug-drug, drug-disease, drug-allergy interaction
    # filtering. Production: a real interaction database (First
    # Databank, Lexicomp, Wolters Kluwer) plus a per-action
    # contraindication rules engine. The example uses the
    # contraindications list from the action template plus a few
    # hard-coded patient-state checks.
    suppressed = []
    retained = []
    patient_state = _build_patient_state_for_filtering(plan_input_record)
    for action in candidate_actions:
        violations = _check_contraindications(action, patient_state)
        if violations:
            action_copy = dict(action)
            action_copy["suppressed"] = True
            action_copy["suppression_reason"] = (
                f"contraindicated: {', '.join(violations)}"
            )
            suppressed.append(action_copy)
        else:
            retained.append(action)

    # Step 3C: deprescribing candidates. A polypharmacy-aware care
    # plan looks at the current medication list and surfaces
    # deprescribing candidates: medications that are no longer
    # indicated, are duplicative, or violate Beers/STOPP geriatric
    # criteria.
    deprescribing_actions = _generate_deprescribing_actions(plan_input_record)
    retained.extend(deprescribing_actions)

    # Step 3D: burden estimation. If the cumulative burden exceeds
    # the patient-specific threshold, drop or defer the
    # lowest-priority-weight actions.
    burden_threshold = _compute_burden_threshold(plan_input_record)
    cumulative_burden = sum(a["burden_score"] for a in retained)
    compression_decisions = []
    if cumulative_burden > burden_threshold:
        compression_decisions = _compress_for_burden(
            retained, goal_set, target_burden=burden_threshold,
        )
        dropped_ids = {d["action_id"] for d in compression_decisions
                        if d["decision"] in ("dropped", "deferred_next_review")}
        retained = [a for a in retained if a["action_id"] not in dropped_ids]

    # Step 3E: capacity reconciliation. Actions whose owner is at
    # capacity get either substitution (alternate owner) or deferral.
    capacity_decisions = []
    for action in retained:
        capacity_status = _check_owner_capacity(action["owner_role"])
        if capacity_status["at_capacity"]:
            substitute = _find_substitute_owner(action)
            if substitute is not None:
                action["original_owner_role"] = action["owner_role"]
                action["owner_role"] = substitute
                action["capacity_substitution"] = {
                    "original_owner_role": action["original_owner_role"],
                    "substituted_owner_role": substitute,
                    "reason": capacity_status["reason"],
                }
                capacity_decisions.append(action["capacity_substitution"]
                                            | {"action_id": action["action_id"]})
            else:
                action["deferred"] = True
                action["defer_reason"] = capacity_status["reason"]
                capacity_decisions.append({
                    "action_id":   action["action_id"],
                    "decision":    "deferred",
                    "reason":      capacity_status["reason"],
                })

    # Step 3F: schedule reconciliation. Sequence actions whose
    # timing conflicts. The demo uses a simple total-actions-per-
    # week cap; production looks at patient-stated capacity.
    schedule_decisions = _sequence_for_schedule(retained, plan_input_record)

    reconciliation_record = {
        "suppressed_actions":    suppressed,
        "deprescribing_added":   deprescribing_actions,
        "compression_decisions": compression_decisions,
        "capacity_decisions":    capacity_decisions,
        "schedule_decisions":    schedule_decisions,
        "burden_threshold":      burden_threshold,
        "cumulative_burden_pre_compression": cumulative_burden,
    }

    try:
        kinesis_client.put_record(
            StreamName=CP_EVENTS_STREAM_NAME,
            PartitionKey=plan_input_record["patient_id"],
            Data=json.dumps({
                "event_type":            "actions_assembled",
                "patient_id":            plan_input_record["patient_id"],
                "plan_input_id":         plan_input_record["plan_input_id"],
                "candidate_count":       len(candidate_actions),
                "retained_count":        len(retained),
                "suppressed_count":      len(suppressed),
                "deprescribing_count":   len(deprescribing_actions),
                "burden_compression_count": len(compression_decisions),
                "timestamp":             _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return {"actions": retained, "reconciliation": reconciliation_record}

def _build_patient_state_for_filtering(plan_input_record: dict) -> dict:
    """Pull the patient-state fields used by contraindication checks."""
    clinical = plan_input_record.get("clinical_state", {})
    features = plan_input_record.get("patient_features", {})
    return {
        "active_conditions": [c["condition_id"] for c in clinical.get(
            "conditions", []) if c.get("active")],
        "medications":       [m["rxnorm_or_id"] for m in clinical.get(
            "medications", [])],
        "allergies":         clinical.get("allergies", []),
        "egfr":              clinical.get("labs", {}).get("egfr_recent"),
        "ef":                clinical.get("labs", {}).get("ef_recent"),
        "chf_severity":      features.get("chf_severity"),
    }

def _check_contraindications(action: dict, patient_state: dict) -> list:
    """
    Check each contraindication code on the action against the
    patient state. Returns the list of triggered contraindications;
    empty list means safe to retain.

    Production: a real rules engine that maps contraindication codes
    to predicates. The demo handles a handful of cases relevant to
    Linda's profile.
    """
    triggered = []
    contras = action.get("contraindications", []) or []
    for code in contras:
        if code == "chf_severe" and patient_state.get(
            "chf_severity") == "severe":
            triggered.append("chf_severe")
        if code == "egfr_under_45" and (
            patient_state.get("egfr") is not None
            and patient_state["egfr"] < 45
        ):
            triggered.append("egfr_under_45")
    return triggered

def _generate_deprescribing_actions(plan_input_record: dict) -> list:
    """
    Surface deprescribing candidates as actions. Production: integrate
    Beers/STOPP criteria, indication-vs-active-medication checks,
    and duplicative-class detection. Demo: a simple long-term-PPI
    pattern.
    """
    deprescribing = []
    medications = plan_input_record.get("clinical_state", {}).get(
        "medications", []
    )
    for med in medications:
        if med.get("rxnorm_or_id") == "omeprazole_20mg" and med.get(
            "duration_days", 0) > 365:
            indication = med.get("indication")
            if indication in (None, "long_term_no_indication"):
                deprescribing.append({
                    "action_id":          "deprescribe_ppi_long_term",
                    "source_template":    "deprescribing_rule_ppi_long_term",
                    "source_template_version": "v1",
                    "goal_link":          "ckd_egfr_stabilization",
                    "owner_role":         "pcp",
                    "horizon":            "this_month",
                    "due_date_logic":     "next_pcp_visit",
                    "clinical_payload": {
                        "kind":         "deprescribing",
                        "instruction":  "review_ppi_indication_consider_taper",
                        "medication":   "omeprazole_20mg",
                        "rationale":    "long_term_ppi_no_indication_documented",
                    },
                    "success_criteria":   "indication_reviewed_or_tapered",
                    "fallback_chain":     ["pharmacist_consult"],
                    "fallback_required":  True,
                    "dependencies":       [],
                    "burden_score":       0.5,
                    "contraindications":  [],
                    "cohort_overrides_applied": [],
                    "provenance": {
                        "source": "deprescribing_rule",
                        "rule":   "ppi_long_term_no_indication",
                    },
                })
    return deprescribing

def _compute_burden_threshold(plan_input_record: dict) -> float:
    """
    Compute the patient-specific burden threshold. Production: a
    function of functional status, cognitive status, social support,
    and stated preferences. Demo: start from a default and reduce
    for frailty, cognitive impairment, and low social support.
    """
    threshold = DEFAULT_BURDEN_THRESHOLD
    func = plan_input_record.get("functional_status", {})
    sdoh = plan_input_record.get("sdoh", {})
    if func.get("cognitive_status") in ("moderate_impairment",
                                          "severe_impairment"):
        threshold *= 0.75
    if func.get("adl_score", 6) < 4:
        threshold *= 0.85
    if sdoh.get("social_support") == "isolated":
        threshold *= 0.90
    if sdoh.get("transportation") == "limited":
        threshold *= 0.95
    return round(threshold, 2)

def _compress_for_burden(retained: list, goal_set: list,
                            target_burden: float) -> list:
    """
    Drop or defer the lowest-priority-weight actions until cumulative
    burden is at or below target. Returns the compression decisions
    for the audit trail and the clinician-facing narrative.

    Production: smarter compression that respects within-goal
    minimum action sets (e.g., the diuretic action for CHF should
    almost never be dropped; the smoking cessation referral for the
    same patient may be deferred).
    """
    weight_by_goal = {g["goal_id"]: g["priority_weight"] for g in goal_set}
    actions_with_weight = [
        (a, weight_by_goal.get(a["goal_link"], 0))
        for a in retained
    ]
    # Lowest priority first; ties broken by burden score (heavier first).
    actions_with_weight.sort(key=lambda x: (x[1], -x[0]["burden_score"]))

    decisions = []
    current_burden = sum(a["burden_score"] for a in retained)
    for action, weight in actions_with_weight:
        if current_burden <= target_burden:
            break
        decisions.append({
            "action_id":    action["action_id"],
            "decision":     "deferred_next_review",
            "reason":       "patient_burden_threshold_reached",
            "goal_priority_weight": weight,
            "burden_score": action["burden_score"],
        })
        current_burden -= action["burden_score"]
    return decisions

def _check_owner_capacity(owner_role: str) -> dict:
    """
    Check whether the given owner role is at capacity. Production:
    real-time integration with the staffing and panel-management
    systems. Demo: a hard-coded snapshot.
    """
    return _DEMO_CAPACITY.get(owner_role, {"at_capacity": False,
                                              "reason": None})

def _find_substitute_owner(action: dict) -> str | None:
    """
    Find a substitute owner for an action whose primary owner is at
    capacity. Production: a substitution catalog tied to organizational
    structure. Demo: a small fallback map.
    """
    fallback_map = {
        "cardiology_clinic_scheduler": "care_manager",
        "specialist_scheduler":        "care_manager",
        "pharmacy_team":               "care_manager",
    }
    return fallback_map.get(action.get("owner_role"))

def _sequence_for_schedule(retained: list,
                              plan_input_record: dict) -> list:
    """
    Sequence actions whose timing conflicts. Demo: a simple cap on
    away-from-home commitments per week, derived from stated capacity.
    Production: integrate the patient's stated capacity (often captured
    in structured form on the portal) and sequence accordingly.
    """
    decisions = []
    away_per_week_cap = plan_input_record.get(
        "patient_features", {}).get("away_from_home_per_week_cap", 3)

    away_actions = [
        a for a in retained
        if a.get("clinical_payload", {}).get("kind")
            in ("program_enrollment", "appointment", "scheduling_with_benefit")
        and a["horizon"] in ("this_week", "this_month", "this_quarter")
    ]
    if len(away_actions) > away_per_week_cap:
        # Defer the lowest-priority away-from-home action(s) into the
        # next-quarter horizon. Production: a richer sequencing engine.
        away_actions.sort(key=lambda a: a["burden_score"])
        for action in away_actions[away_per_week_cap:]:
            if action["horizon"] != "this_quarter":
                decisions.append({
                    "action_id": action["action_id"],
                    "summary":   f"{action['action_id']}_resequenced_to_q3",
                    "reason":    "away_from_home_cap",
                })
                action["horizon"] = "this_quarter"
    return decisions

# Demo state populated by the runner.
_DEMO_CAPACITY: dict = {}
```

---

## Step 4: Finalize the Structured Plan Record

*The pseudocode calls this `finalize_plan(goal_set, retained_actions, reconciliation_record, plan_input_record)`. The plan record is the system of record. Every downstream activity (narrative generation, review, activation, feedback) operates on it. Skip the explicit structuring and the system has nothing to reproduce, audit, or update against; you have a one-shot document, not a plan.*

```python
def finalize_plan(goal_set: list,
                    retained_actions: list,
                    reconciliation_record: dict,
                    plan_input_record: dict) -> dict:
    """
    Build the structured plan record:
      A. Bucket actions by horizon
      B. Verify each action has an owner and a fallback path
      C. Assemble the plan record with provenance and plan_version
      D. Persist to DynamoDB and to the immutable S3 archive
    """
    # Step 4A: bucket by horizon. Horizons are catalog-defined.
    actions_by_horizon = {"this_week": [], "this_month": [],
                            "this_quarter": [], "ongoing": []}
    for action in retained_actions:
        horizon = action.get("horizon", "ongoing")
        actions_by_horizon.setdefault(horizon, []).append(action)

    # Step 4B: verify owner and fallback. Surface to-be-assigned
    # items to the care team rather than silently shipping without
    # accountability.
    to_be_assigned = []
    final_actions = []
    for action in retained_actions:
        if not action.get("owner_role"):
            to_be_assigned.append(action)
            continue
        if action.get("fallback_required") and not action.get(
            "fallback_chain"):
            to_be_assigned.append(action)
            continue
        final_actions.append(action)

    # Step 4C: assemble plan_record.
    plan_id = _make_plan_id()
    patient_id = plan_input_record["patient_id"]
    plan_version = _next_plan_version(patient_id)
    review_due_at = (datetime.datetime.now(timezone.utc)
                       + timedelta(days=REVIEW_SLA_DAYS)).isoformat()

    plan_record = {
        "plan_id":              plan_id,
        "plan_version":         plan_version,
        "patient_id":           patient_id,
        "plan_input_id":        plan_input_record["plan_input_id"],
        "goal_set":             goal_set,
        "actions_by_horizon":   actions_by_horizon,
        "final_actions":        final_actions,
        "to_be_assigned":       to_be_assigned,
        "reconciliation_record": reconciliation_record,
        "prior_plan_version":   (plan_input_record.get("prior_plan") or {}
                                   ).get("plan_version"),
        "plan_status":          "pending_review",
        "review_due_at":        review_due_at,
        "generated_at":         _now_iso(),
    }

    # Step 4D: persist. Operational store + immutable S3 archive.
    plans_table = dynamodb.Table(PLAN_RECORDS_TABLE)
    try:
        plans_table.put_item(
            Item=_to_decimal_dict(plan_record),
            # Idempotency: a Step Functions retry that re-invokes
            # finalize_plan with the same plan_id (would only happen
            # if the workflow surface seeded the id) is a no-op
            # rather than a duplicate.
            ConditionExpression="attribute_not_exists(plan_id)",
        )
    except Exception as exc:
        logger.warning("Failed to persist plan record %s: %s",
                        plan_id, exc)

    try:
        s3_client.put_object(
            Bucket=CP_ARCHIVES_BUCKET,
            Key=f"plans/{plan_id}.json",
            Body=json.dumps(plan_record, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning("Failed to archive plan %s: %s", plan_id, exc)

    try:
        kinesis_client.put_record(
            StreamName=CP_EVENTS_STREAM_NAME,
            PartitionKey=patient_id,
            Data=json.dumps({
                "event_type":           "plan_finalized",
                "patient_id":           patient_id,
                "plan_id":              plan_id,
                "plan_version":         plan_version,
                "goal_count":           len(goal_set),
                "action_count":         len(final_actions),
                "to_be_assigned_count": len(to_be_assigned),
                "timestamp":            _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    # Cohort-sliced metric for the equity dashboard.
    cohort = _cohort_features_from_profile(
        plan_input_record.get("patient_features", {}))
    _emit_metric(
        "plan_finalized", value=1,
        dimensions={
            "language":    cohort.get("language"),
            "sdoh_cohort": cohort.get("sdoh_cohort"),
            "age_band":    cohort.get("age_band"),
            "action_count_band": _band_int(len(final_actions),
                                              [5, 10, 15]),
        },
    )

    return plan_record

def _next_plan_version(patient_id: str) -> int:
    """
    Compute the next plan version for a patient. Production: query
    the latest plan record for this patient and increment. Demo:
    a simple in-memory counter.
    """
    _DEMO_PLAN_VERSION_COUNTERS[patient_id] = (
        _DEMO_PLAN_VERSION_COUNTERS.get(patient_id, 0) + 1
    )
    return _DEMO_PLAN_VERSION_COUNTERS[patient_id]

def _band_int(value: int, thresholds: list) -> str:
    """Coarse banding for metric dimensions."""
    for i, t in enumerate(thresholds):
        if value < t:
            return f"under_{t}"
    return f"{thresholds[-1]}_plus"

_DEMO_PLAN_VERSION_COUNTERS: dict = {}
```

---

## Step 5: Generate Clinician, Patient, and Care-Team-Internal Narratives

*The pseudocode calls this `generate_narratives(plan_record)`. The narratives are the human-readable artifacts; the structured plan is the audit-ready system of record. Skip the structured-then-narrative direction and the LLM becomes the source of truth, which is the failure mode that makes care plan generation systems clinically unsafe. The four-layer validator (schema, fact grounding, prohibited language, required content) is what keeps the LLM honest.*

```python
def generate_narratives(plan_record: dict,
                         patients: dict) -> dict:
    """
    Generate up to three narratives per plan:
      - Clinician-facing
      - Patient-facing
      - Care-team-internal disagreement (only when reconciliation
        could not resolve a conflict)

    Each narrative goes through Bedrock with the four-layer validator
    and a templated fallback. Narratives are persisted keyed by
    (plan_id, audience).

    Returns { audience: narrative_record }.
    """
    narratives = {}

    # Step 5A: clinician-facing narrative.
    clinician_context = {
        "audience":           "clinician",
        "plan_record":        plan_record,
        "what_changed":       _compute_what_changed(plan_record),
        "care_team_attention": _extract_attention_items(plan_record),
    }
    narratives["clinician"] = _generate_one_narrative(
        clinician_context,
        model_id=CLINICIAN_NARRATIVE_MODEL_ID,
    )

    # Step 5B: patient-facing narrative. Tailored to reading level,
    # language, channel preferences, and stated preferences.
    patient_profile = patients.get(plan_record["patient_id"], {})
    patient_context = {
        "audience":           "patient",
        "plan_record":        plan_record,
        "reading_level_target": patient_profile.get(
            "reading_level_target", DEFAULT_READING_LEVEL_TARGET),
        "language":           patient_profile.get("preferred_language", "en"),
        "channel_preferences": patient_profile.get(
            "channel_preferences", {"primary": "portal"}),
        "stated_preferences": patient_profile.get("stated_preferences", {}),
    }
    narratives["patient"] = _generate_one_narrative(
        patient_context,
        model_id=PATIENT_NARRATIVE_MODEL_ID,
    )

    # Step 5C: care-team-internal disagreement narrative (only when
    # reconciliation surfaced unresolved conflicts).
    if _has_unresolved_conflicts(plan_record):
        internal_context = {
            "audience":   "care_team_internal",
            "plan_record": plan_record,
            "unresolved": _extract_unresolved_conflicts(plan_record),
        }
        narratives["care_team_internal"] = _generate_one_narrative(
            internal_context,
            model_id=INTERNAL_NARRATIVE_MODEL_ID,
        )

    # Persist each narrative.
    narratives_table = dynamodb.Table(PLAN_NARRATIVES_TABLE)
    for audience, narrative_record in narratives.items():
        narrative_record["narrative_id"] = _make_narrative_id()
        narrative_record["plan_id"] = plan_record["plan_id"]
        narrative_record["plan_version"] = plan_record["plan_version"]
        narrative_record["patient_id"] = plan_record["patient_id"]
        narrative_record["audience"] = audience
        narrative_record["generated_at"] = _now_iso()
        try:
            narratives_table.put_item(
                Item=_to_decimal_dict(narrative_record),
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist narrative %s/%s: %s",
                plan_record["plan_id"], audience, exc,
            )

    return narratives

def _generate_one_narrative(context: dict, model_id: str) -> dict:
    """
    Run the regeneration loop for a single narrative:
      - up to MAX_REGENERATION_ATTEMPTS Bedrock calls with validator
      - on each failure, pass validator feedback back into the prompt
      - on terminal failure, fall back to a deterministic templated
        narrative that always passes
    """
    audience = context["audience"]
    parsed = None
    validator_status = False
    validator_layers_passed = []

    for attempt in range(MAX_REGENERATION_ATTEMPTS):
        try:
            parsed = _bedrock_invoke_narrative(
                context, model_id=model_id, strict_mode=(attempt > 0),
            )
        except Exception as exc:
            logger.warning(
                "Bedrock %s narrative attempt %d failed: %s",
                audience, attempt, exc,
            )
            continue

        validation = _validate_narrative(parsed, context)
        if validation["passed"]:
            validator_status = True
            validator_layers_passed = validation["layers_passed"]
            break
        # Provide validator feedback to the next attempt so the LLM
        # has the opportunity to correct.
        context["validator_feedback"] = validation["feedback"]

    if not validator_status:
        parsed = _templated_narrative_fallback(context)
        parsed["fallback_reason"] = (
            "validator_repeatedly_failed_or_llm_unavailable"
        )
        try:
            kinesis_client.put_record(
                StreamName=CP_EVENTS_STREAM_NAME,
                PartitionKey=context["plan_record"]["patient_id"],
                Data=json.dumps({
                    "event_type":     "narrative_validator_fallback",
                    "plan_id":        context["plan_record"]["plan_id"],
                    "audience":       audience,
                    "timestamp":      _now_iso(),
                }, default=str).encode("utf-8"),
            )
        except Exception:
            pass

    return {
        "narrative_text":         parsed,
        "validator_status":       validator_status,
        "validator_layers_passed": validator_layers_passed,
    }

def _bedrock_invoke_narrative(context: dict, model_id: str,
                                  strict_mode: bool = False) -> dict:
    """
    Call Bedrock to produce a narrative. The prompt is audience-
    specific. The structured plan goes in de-identified; identifiers
    stay on the persistence side.
    """
    audience = context["audience"]
    de_id = _redact_for_llm({
        "plan_record":         context["plan_record"],
        "what_changed":        context.get("what_changed"),
        "care_team_attention": context.get("care_team_attention"),
        "unresolved":          context.get("unresolved"),
        "reading_level_target": context.get("reading_level_target"),
        "language":            context.get("language"),
        "channel_preferences": context.get("channel_preferences"),
        "stated_preferences":  context.get("stated_preferences"),
    })

    strictness_addendum = (
        "\n\nSTRICT MODE: A previous attempt failed validation. The "
        "validator caught issues. Be more careful: do not introduce "
        "any clinical claim that does not appear in the structured "
        "plan, do not change any medication dose or schedule, and "
        "do not generate prognostic statements beyond approved "
        "templates."
        if strict_mode else ""
    )

    if audience == "clinician":
        prompt = _clinician_prompt(de_id, strictness_addendum)
    elif audience == "patient":
        prompt = _patient_prompt(de_id, strictness_addendum)
    else:
        prompt = _internal_prompt(de_id, strictness_addendum)

    response = bedrock_runtime.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        2000,
            "temperature":       0.0,
            "messages":          [{"role": "user", "content": prompt}],
        }),
    )
    payload = json.loads(response["body"].read())
    completion = payload["content"][0]["text"]
    match = re.search(r"\{.*\}", completion, re.DOTALL)
    if not match:
        raise ValueError("LLM returned no JSON object")
    return json.loads(match.group(0))

def _clinician_prompt(de_id: dict, strictness_addendum: str) -> str:
    """Clinician-facing narrative prompt."""
    return f"""You generate clinician-facing care plan summaries. Your role
is to package the structured plan into a brief that the clinician
reads at the point of plan review. The structured summary precedes
the prose; the prose surfaces what changed since the prior plan,
what conflicts were reconciled, and what the care team should pay
attention to.

Hard rules:
1. Reference only facts in the Context. Do not invent goals, actions,
   medications, doses, or schedules.
2. Do not generate prognostic statements beyond approved templates.
3. Do not change priority weights or clinical content of action
   instructions; you are packaging the plan, not assembling it.
4. Surface the to-be-assigned items, suppressed actions, and
   deprescribing candidates in the care_team_attention block.{strictness_addendum}

Context (de-identified):
{json.dumps(de_id, indent=2)}

Return ONLY valid JSON (no prose, no code fences) with this shape:
{{
  "headline":              "<10-20 words; framing of plan version and changes>",
  "what_changed_since_prior": ["<bullet>", "<bullet>", "<bullet>"],
  "care_team_attention":   ["<item>", "<item>"],
  "narrative_paragraph":   "<3-5 sentences synthesizing the plan focus and tradeoffs>"
}}
"""

def _patient_prompt(de_id: dict, strictness_addendum: str) -> str:
    """Patient-facing narrative prompt."""
    reading_level = de_id.get("reading_level_target", "grade_6")
    language = de_id.get("language", "en")
    return f"""You generate patient-facing care plan summaries. Your role
is to translate the structured plan into a friendly, actionable
summary the patient can read on a portal or in a printed letter.

Hard rules:
1. Match the reading-level target ({reading_level}). Use short
   sentences. Use everyday words instead of clinical jargon.
2. Output language: {language}. If language != "en", produce the
   narrative in that language.
3. Reference only facts in the structured plan. Never introduce a
   clinical claim that is not present in the plan.
4. Never generate prognostic statements ("you will...") beyond
   approved templates.
5. Always include shared-decision framing and a contact-for-questions
   block.{strictness_addendum}

Context (de-identified):
{json.dumps(de_id, indent=2)}

Return ONLY valid JSON (no prose, no code fences) with this shape:
{{
  "headline":         "<friendly framing, 10-15 words>",
  "this_week":        ["<plain-language action>", "<action>", "<action>"],
  "this_month":       ["<action>", "<action>"],
  "this_quarter":     ["<action>", "<action>"],
  "ongoing":          ["<action>"],
  "what_changed":     "<1-2 sentences summarizing what's new>",
  "questions":        "<shared-decision framing; how to ask questions or change the plan>",
  "contact":          {{"care_manager_name": "<from plan>", "phone": "<from plan>",
                          "portal_link": "<from plan>"}}
}}
"""

def _internal_prompt(de_id: dict, strictness_addendum: str) -> str:
    """Care-team-internal disagreement narrative prompt."""
    return f"""You generate internal-facing disagreement narratives for the
care team when plan reconciliation could not resolve a conflict.
The narrative describes the conflict, the candidate resolutions,
and the recommended escalation path. This is decision-support for
the care team, not patient-facing content.

Hard rules:
1. Be concise. Three sections: conflict, candidate resolutions,
   recommended escalation.
2. Reference only items in the unresolved list.
3. Do not select a resolution; surface candidates and let the care
   team decide.{strictness_addendum}

Context (de-identified):
{json.dumps(de_id, indent=2)}

Return ONLY valid JSON (no prose, no code fences) with this shape:
{{
  "headline":            "<10-15 words>",
  "conflict_description": "<2-3 sentences>",
  "candidate_resolutions": ["<option>", "<option>"],
  "recommended_escalation": "<1-2 sentences>"
}}
"""

def _validate_narrative(parsed: dict, context: dict) -> dict:
    """
    Four-layer validator from the main recipe.

    1. Schema and length: required fields per audience are present;
       no oversize text.
    2. Fact grounding: every clinical claim in the narrative traces
       to a structured plan element. The LLM cannot introduce claims
       absent from the structured context.
    3. Prohibited-language patterns: no recommendation language for
       treatments not in the plan, no probabilistic claims framed
       as guarantees, no goal statements not in the goal set, no
       prognostic claims beyond approved templates. The patterns
       are audience-specific.
    4. Required content: shared-decision framing for the patient
       narrative, change-since-prior-plan callouts for the clinician
       narrative, escalation path for the disagreement narrative.

    Returns { passed, feedback, layers_passed }.
    """
    audience = context["audience"]
    issues = []
    layers_passed = []

    # Layer 1: schema and length.
    schema_ok = _check_schema(parsed, audience, issues)
    if schema_ok:
        layers_passed.append("schema")

    # Layer 2: fact grounding (heuristic check).
    grounding_ok = _check_fact_grounding(parsed, context, issues)
    if grounding_ok:
        layers_passed.append("fact_grounding")

    # Layer 3: prohibited-language patterns.
    prohibited_ok = _check_prohibited_language(parsed, audience, issues)
    if prohibited_ok:
        layers_passed.append("prohibited_language")

    # Layer 4: required content.
    required_ok = _check_required_content(parsed, audience, issues)
    if required_ok:
        layers_passed.append("required_content")

    return {
        "passed":         len(issues) == 0,
        "feedback":       issues,
        "layers_passed":  layers_passed,
    }

def _check_schema(parsed: dict, audience: str, issues: list) -> bool:
    """Layer 1: required fields present and sized appropriately."""
    if not isinstance(parsed, dict):
        issues.append("not_a_dict")
        return False
    required = {
        "clinician":          {"headline", "what_changed_since_prior",
                                  "care_team_attention", "narrative_paragraph"},
        "patient":            {"headline", "this_week", "this_month",
                                  "this_quarter", "ongoing",
                                  "what_changed", "questions", "contact"},
        "care_team_internal": {"headline", "conflict_description",
                                  "candidate_resolutions",
                                  "recommended_escalation"},
    }.get(audience, set())

    missing = required - set(parsed.keys())
    if missing:
        issues.append(f"missing_required_fields: {sorted(missing)}")
        return False

    for k, v in parsed.items():
        if isinstance(v, str) and len(v) > 4000:
            issues.append(f"oversize_text: {k}")
            return False
    return True

def _check_fact_grounding(parsed: dict, context: dict,
                            issues: list) -> bool:
    """
    Layer 2: heuristic fact-grounding check.

    For the clinician and patient narratives, walk the narrative
    text and verify that every action_id and goal_id mentioned is
    present in the structured plan. The demo uses a simple substring
    check; production uses entity-extraction and structured-claim
    matching.
    """
    plan = context["plan_record"]
    valid_action_ids = {a["action_id"] for a in plan["final_actions"]}
    valid_goal_ids = {g["goal_id"] for g in plan["goal_set"]}

    text = _flatten_narrative_text(parsed)

    # Production: NER + claim matching. The demo flags only the
    # cases where text references an action_id-shaped token that
    # does not appear in the structured plan.
    suspicious_tokens = re.findall(r"\b[a-z][a-z0-9_]{8,40}\b", text)
    for token in suspicious_tokens:
        if token in valid_action_ids or token in valid_goal_ids:
            continue
        # Skip everyday English words; the demo's signal is that
        # tokens with 3+ underscores look like structured ids.
        if token.count("_") >= 2 and not _is_safe_keyword(token):
            issues.append(f"ungrounded_id_reference: {token}")
            return False
    return True

def _check_prohibited_language(parsed: dict, audience: str,
                                  issues: list) -> bool:
    """
    Layer 3: prohibited-language patterns. Audience-specific.
    """
    text = _flatten_narrative_text(parsed).lower()

    # Always-prohibited.
    always_patterns = [
        r"\bguaranteed\b",
        r"\bcure[ds]?\b",
        r"\b100%\s+(?:effective|safe)\b",
        r"\bdefinitely will\b",
        r"\bnever fail",
    ]
    for pattern in always_patterns:
        if re.search(pattern, text):
            issues.append(f"prohibited_language: {pattern}")
            return False

    # Patient-specific extras: no medical-school-level jargon, no
    # recommendation-without-shared-decision phrasing.
    if audience == "patient":
        jargon_patterns = [
            r"\bcontraindication\b",
            r"\biatrogenic\b",
            r"\bidiopathic\b",
        ]
        for pattern in jargon_patterns:
            if re.search(pattern, text):
                issues.append(f"jargon_in_patient_narrative: {pattern}")
                return False

    # Care-team-internal extras: no patient-facing softening that
    # would obscure the conflict.
    if audience == "care_team_internal":
        if "everything is fine" in text or "no concerns" in text:
            issues.append("disagreement_narrative_too_soft")
            return False

    return True

def _check_required_content(parsed: dict, audience: str,
                              issues: list) -> bool:
    """Layer 4: required content per audience."""
    if audience == "patient":
        questions = parsed.get("questions", "")
        if not isinstance(questions, str) or len(questions) < 20:
            issues.append("patient_narrative_missing_shared_decision_framing")
            return False
        contact = parsed.get("contact", {})
        if not isinstance(contact, dict) or not contact.get("phone"):
            issues.append("patient_narrative_missing_contact_info")
            return False

    if audience == "clinician":
        what_changed = parsed.get("what_changed_since_prior", [])
        if not isinstance(what_changed, list) or len(what_changed) == 0:
            issues.append("clinician_narrative_missing_what_changed")
            return False

    if audience == "care_team_internal":
        escalation = parsed.get("recommended_escalation", "")
        if not isinstance(escalation, str) or len(escalation) < 20:
            issues.append("disagreement_narrative_missing_escalation")
            return False
    return True

def _flatten_narrative_text(parsed: dict) -> str:
    """Concatenate string-valued fields into one flat lowercase text."""
    parts = []
    def walk(obj):
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(parsed)
    return " ".join(parts).lower()

def _is_safe_keyword(token: str) -> bool:
    """Allow-list for tokens that look like ids but are safe."""
    safe = {
        "this_week", "this_month", "this_quarter",
        "next_quarter", "next_6_months", "next_12_months",
        "monthly", "weekly", "ongoing",
    }
    return token in safe

def _templated_narrative_fallback(context: dict) -> dict:
    """
    Deterministic fallback narrative when LLM generation or the
    validator fails. Lists the structured plan in the audience-
    appropriate shape without LLM narration.
    """
    audience = context["audience"]
    plan = context["plan_record"]

    if audience == "clinician":
        return {
            "headline": (
                f"Plan v{plan['plan_version']} ready for review; "
                f"{len(plan['final_actions'])} actions across "
                f"{len(plan['goal_set'])} goals. Templated narrative "
                "fallback used; review structured plan directly."
            ),
            "what_changed_since_prior": [
                "Structured plan available; narrative generation "
                "fell back to templated path."
            ],
            "care_team_attention": [
                f"to_be_assigned_count={len(plan.get('to_be_assigned', []))}",
                ("suppressed_action_count="
                 f"{len(plan.get('reconciliation_record', {}).get('suppressed_actions', []))}"),
            ],
            "narrative_paragraph": (
                "Plan generated and persisted. The narrative layer "
                "could not be produced through Bedrock or the validator "
                "rejected the output. Refer to the structured plan record "
                "for the full goal and action set."
            ),
        }

    if audience == "patient":
        return {
            "headline": "Your care plan is ready. Please call your care manager to review.",
            "this_week": [
                f"You have {len(plan.get('actions_by_horizon', {}).get('this_week', []))}"
                " action(s) this week. Your care manager will walk you through them."
            ],
            "this_month":   ["See full plan with your care manager."],
            "this_quarter": ["See full plan with your care manager."],
            "ongoing":      ["Care manager check-ins continue."],
            "what_changed": "Your plan was updated. Please call your care manager.",
            "questions": (
                "If anything in this plan does not work for you, please call "
                "your care manager. Your plan is meant to fit your life."
            ),
            "contact": {
                "care_manager_name": "Your care manager",
                "phone":             "(800) 555-0142",
                "portal_link":       "secure.example.com/portal",
            },
        }

    return {
        "headline":               "Care-team review needed; plan reconciliation surfaced unresolved items.",
        "conflict_description":   "The structured plan has unresolved reconciliation items.",
        "candidate_resolutions":  ["Review the reconciliation record",
                                      "Convene the care team for resolution"],
        "recommended_escalation": (
            "Care manager to schedule a 15-minute care-team huddle to "
            "review the unresolved reconciliation items in the plan."
        ),
    }

def _compute_what_changed(plan_record: dict) -> list:
    """
    Compute a structured diff between this plan version and the prior
    plan version for the clinician narrative. Demo: a stub that names
    a few high-signal entries derived from the reconciliation record.
    Production: a real diff over goal_set, final_actions, and
    reconciliation_record fields against the prior plan version.
    """
    changes = []
    rec = plan_record.get("reconciliation_record", {})
    for sup in rec.get("suppressed_actions", []):
        changes.append(
            f"Suppressed {sup['action_id']} ({sup.get('suppression_reason')})"
        )
    for dep in rec.get("deprescribing_added", []):
        changes.append(f"Added deprescribing candidate {dep['action_id']}")
    for cap in rec.get("capacity_decisions", []):
        if "substituted_owner_role" in cap:
            changes.append(
                f"Capacity-substituted {cap['action_id']} owner from "
                f"{cap['original_owner_role']} to {cap['substituted_owner_role']}"
            )
    for comp in rec.get("compression_decisions", []):
        changes.append(
            f"Deferred {comp['action_id']} to next review "
            f"({comp.get('reason')})"
        )
    if not changes and plan_record.get("plan_version", 1) == 1:
        changes.append("Initial plan; no prior plan to compare.")
    return changes

def _extract_attention_items(plan_record: dict) -> list:
    """Extract care-team-attention items from the plan record."""
    items = []
    for action in plan_record.get("to_be_assigned", []):
        items.append(f"To-be-assigned: {action['action_id']}")
    rec = plan_record.get("reconciliation_record", {})
    for sup in rec.get("suppressed_actions", []):
        items.append(
            f"Suppressed: {sup['action_id']} - {sup.get('suppression_reason')}"
        )
    for dep in rec.get("deprescribing_added", []):
        items.append(f"Deprescribing candidate: {dep['action_id']}")
    return items

def _has_unresolved_conflicts(plan_record: dict) -> bool:
    """True if reconciliation produced items needing care-team escalation."""
    rec = plan_record.get("reconciliation_record", {})
    if plan_record.get("to_be_assigned"):
        return True
    if rec.get("compression_decisions"):
        return True
    return False

def _extract_unresolved_conflicts(plan_record: dict) -> list:
    """Surface the structured unresolved items for the disagreement narrative."""
    out = []
    rec = plan_record.get("reconciliation_record", {})
    out.extend(plan_record.get("to_be_assigned", []))
    out.extend(rec.get("compression_decisions", []))
    return out
```

---

## Step 6: Activate, Capture Feedback, and Trigger Plan Revisions

*The pseudocode covers `activate_plan`, `record_feedback`, and `run_periodic_plan_review`. Activation flips the structured actions into operational tasks; feedback closes the loop; revision keeps the plan alive. Skip the feedback loop and the plan is a one-shot artifact that ages out of relevance, which is the most common reason care plans become stale.*

```python
def activate_plan(plan_id: str, activation_payload: dict) -> dict:
    """
    Activate approved actions from a plan. Identity-boundary check:
    approved_action_ids must be a subset of plan.final_actions.
    """
    plans_table = dynamodb.Table(PLAN_RECORDS_TABLE)
    plan = _safe_get_item(plans_table, {"plan_id": plan_id})
    if not plan:
        logger.warning("Plan %s not found", plan_id)
        return {}

    plan_action_ids = {a["action_id"] for a in plan.get("final_actions", [])}
    approved_ids = list(activation_payload.get("approved_action_ids", []))
    invalid = [aid for aid in approved_ids if aid not in plan_action_ids]
    if invalid:
        logger.warning(
            "Rejected approval for actions not in plan: %s", invalid,
        )
        approved_ids = [aid for aid in approved_ids
                          if aid in plan_action_ids]

    activation_id = _make_activation_id()
    activation_record = {
        "activation_id":          activation_id,
        "plan_id":                plan_id,
        "plan_version":           plan["plan_version"],
        "approving_clinician_id": activation_payload.get(
            "approving_clinician_id"),
        "approved_action_ids":    approved_ids,
        "clinician_edits":        activation_payload.get(
            "clinician_edits", {}),
        "patient_acknowledgment": activation_payload.get(
            "patient_acknowledgment"),
        "teach_back_results":     activation_payload.get(
            "teach_back_results"),
        "activated_at":           _now_iso(),
    }

    # Per approved action: dispatch to operational integrations and
    # write a plan-action-record. Production routes per clinical
    # payload kind to e-prescribing, scheduling, program registry,
    # patient-facing reminder, and care-management systems.
    par_table = dynamodb.Table(PLAN_ACTION_RECORDS_TABLE)
    for action_id in approved_ids:
        action = next((a for a in plan["final_actions"]
                         if a["action_id"] == action_id), None)
        if action is None:
            continue
        edit = activation_record["clinician_edits"].get(action_id)
        effective_action = _apply_clinician_edit(action, edit)
        _dispatch_action_to_operational_system(
            effective_action, plan_id, activation_id,
        )
        par_record = {
            "plan_action_record_id": _make_action_record_id(),
            "plan_id":               plan_id,
            "action_id":             action_id,
            "effective_action":      effective_action,
            "status":                "active",
            "owner_role":            effective_action["owner_role"],
            "due_at":                _compute_due_at(effective_action),
            "success_criteria":      effective_action["success_criteria"],
            "fallback_chain":        effective_action.get(
                "fallback_chain", []),
            "activated_at":          _now_iso(),
        }
        try:
            par_table.put_item(Item=_to_decimal_dict(par_record))
        except Exception as exc:
            logger.warning(
                "Failed to persist plan-action-record for %s: %s",
                action_id, exc,
            )

    try:
        plans_table.update_item(
            Key={"plan_id": plan_id},
            UpdateExpression=(
                "SET plan_status = :s, "
                "activation_record = :ar, "
                "last_status_change_at = :t"
            ),
            ExpressionAttributeValues=_to_decimal_dict({
                ":s":  "active",
                ":ar": activation_record,
                ":t":  _now_iso(),
            }),
        )
    except Exception as exc:
        logger.warning(
            "Failed to update plan status to active: %s", exc,
        )

    try:
        kinesis_client.put_record(
            StreamName=CP_EVENTS_STREAM_NAME,
            PartitionKey=plan["patient_id"],
            Data=json.dumps({
                "event_type":              "plan_activated",
                "patient_id":              plan["patient_id"],
                "plan_id":                 plan_id,
                "plan_version":            plan["plan_version"],
                "activated_action_count":  len(approved_ids),
                "timestamp":               _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return activation_record

def _apply_clinician_edit(action: dict, edit: dict | None) -> dict:
    """Apply clinician-supplied edits to an action."""
    if not edit:
        return dict(action)
    out = dict(action)
    for k, v in edit.items():
        out[k] = v
    return out

def _dispatch_action_to_operational_system(action: dict, plan_id: str,
                                              activation_id: str) -> None:
    """
    Dispatch an action to the operational integration appropriate
    for its clinical payload kind. Production: real integrations
    (e-prescribing system, scheduling system, program registry,
    Pinpoint sender, care-management system). Demo: log only.
    """
    kind = action.get("clinical_payload", {}).get("kind", "unknown")
    logger.info(
        "Dispatch %s action %s for plan %s (activation %s)",
        kind, action["action_id"], plan_id, activation_id,
    )

def _compute_due_at(action: dict) -> str:
    """Compute due_at from the action's due_date_logic. Demo helper."""
    logic = action.get("due_date_logic", "ongoing")
    today = datetime.date.today()
    if logic.startswith("30_days"):
        return (today + timedelta(days=30)).isoformat()
    if logic.startswith("60_days"):
        return (today + timedelta(days=60)).isoformat()
    if logic.startswith("90_days"):
        return (today + timedelta(days=90)).isoformat()
    if logic == "monthly":
        return "monthly"
    return "ongoing"

def record_feedback(plan_id: str, feedback_payload: dict) -> dict:
    """
    Record an action-completion, outcome, patient-reported, or
    adverse-event feedback record. Update the action status if
    action-level. Determine if the feedback should trigger a plan
    revision via EventBridge.
    """
    feedback_id = _make_feedback_id()
    record = {
        "feedback_id":     feedback_id,
        "plan_id":         plan_id,
        "feedback_kind":   feedback_payload.get("feedback_kind"),
        "target_action_id": feedback_payload.get("target_action_id"),
        "feedback_data":   feedback_payload.get("feedback_data", {}),
        "source":          feedback_payload.get("source"),
        "recorded_at":     _now_iso(),
    }
    feedback_table = dynamodb.Table(PLAN_FEEDBACK_RECORDS_TABLE)
    try:
        feedback_table.put_item(Item=_to_decimal_dict(record))
    except Exception as exc:
        logger.warning("Failed to persist feedback %s: %s", feedback_id, exc)

    if feedback_payload.get("target_action_id"):
        _update_action_status(
            plan_id,
            feedback_payload["target_action_id"],
            feedback_payload.get("feedback_kind"),
            feedback_payload.get("feedback_data", {}),
        )

    revision_signal = _evaluate_feedback_for_revision(plan_id, record)
    if revision_signal["should_revise"]:
        try:
            eventbridge_client.put_events(
                Entries=[{
                    "Source":       "care-plan",
                    "DetailType":   "plan_revision_triggered",
                    "EventBusName": EVENTBRIDGE_BUS_NAME,
                    "Detail":       json.dumps({
                        "plan_id":      plan_id,
                        "reason":       revision_signal["reason"],
                        "triggered_by": feedback_id,
                    }, default=str),
                }],
            )
        except Exception as exc:
            logger.warning("Failed to emit revision event: %s", exc)

    try:
        kinesis_client.put_record(
            StreamName=CP_EVENTS_STREAM_NAME,
            PartitionKey=plan_id,
            Data=json.dumps({
                "event_type":         "plan_feedback_recorded",
                "plan_id":            plan_id,
                "feedback_kind":      record["feedback_kind"],
                "target_action_id":   record["target_action_id"],
                "revision_triggered": revision_signal["should_revise"],
                "timestamp":          _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass
    return record

def _update_action_status(plan_id: str, action_id: str,
                            feedback_kind: str, feedback_data: dict) -> None:
    """Update the plan-action-record's status based on feedback."""
    par_table = dynamodb.Table(PLAN_ACTION_RECORDS_TABLE)
    new_status = {
        "action_completed":  "completed",
        "action_failed":     "failed",
        "action_in_progress": "in_progress",
    }.get(feedback_kind, "noted")

    # Production: use the (plan_id, action_id) GSI; the demo scans
    # because the example does not provision indexes.
    try:
        response = par_table.scan()
        for item in response.get("Items", []):
            item = _from_decimal(item)
            if (item.get("plan_id") == plan_id
                and item.get("action_id") == action_id):
                par_table.update_item(
                    Key={"plan_action_record_id":
                          item["plan_action_record_id"]},
                    UpdateExpression="SET #s = :s, last_feedback_at = :t",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues=_to_decimal_dict({
                        ":s": new_status,
                        ":t": _now_iso(),
                    }),
                )
                return
    except Exception:
        pass

def _evaluate_feedback_for_revision(plan_id: str,
                                        feedback_record: dict) -> dict:
    """
    Decide whether to trigger plan revision. Production: per-trigger
    sensitivity tuning. Demo: revise on adverse_event always, on
    action_failed for high-priority actions, and on outcome_observed
    when the value crosses an alert threshold.
    """
    kind = feedback_record.get("feedback_kind")
    if kind == "adverse_event":
        return {"should_revise": True,
                 "reason":        "adverse_event_observed"}
    if kind == "action_failed":
        return {"should_revise": True,
                 "reason":        "key_action_failed"}
    if kind == "outcome_observed":
        outcome = feedback_record.get("feedback_data", {})
        if outcome.get("alert_threshold_crossed"):
            return {"should_revise": True,
                     "reason":        "outcome_alert_threshold_crossed"}
    return {"should_revise": False, "reason": None}

def run_periodic_plan_review(run_date: str) -> list:
    """
    Aggregate active plans, dispatch those due for scheduled review
    to the plan-revision pipeline, and run cohort-stratified plan-
    quality monitoring. Returns the list of fairness alerts created.
    """
    plans_table = dynamodb.Table(PLAN_RECORDS_TABLE)
    alerts_table = dynamodb.Table(SURVEILLANCE_ALERTS_TABLE)
    alerts = []

    # Production: a (plan_status, review_due_at) GSI; the demo
    # scans because the example does not provision indexes.
    try:
        response = plans_table.scan()
        for item in response.get("Items", []):
            plan = _from_decimal(item)
            if plan.get("plan_status") != "active":
                continue
            if str(plan.get("review_due_at", "")) > run_date:
                continue
            try:
                eventbridge_client.put_events(
                    Entries=[{
                        "Source":       "care-plan",
                        "DetailType":   "plan_revision_triggered",
                        "EventBusName": EVENTBRIDGE_BUS_NAME,
                        "Detail": json.dumps({
                            "plan_id":  plan["plan_id"],
                            "reason":   "scheduled_review",
                            "run_date": run_date,
                        }, default=str),
                    }],
                )
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Failed to scan plans: %s", exc)

    # Cohort-stratified plan-quality monitoring. Production: real
    # cohort-aware analytics (Athena, Glue) over plan and feedback
    # data. The demo computes a synthetic disparity over the
    # in-memory plans table.
    quality_metrics = _compute_plan_quality_metrics(plans_table, run_date)
    for axis, metric in quality_metrics.items():
        if metric.get("disparity", 0) >= COHORT_DISPARITY_ALERT_THRESHOLD:
            alert = {
                "alert_id":        f"alert-{uuid.uuid4().hex[:16]}",
                "alert_type":      "plan_cohort_disparity",
                "axis":            axis,
                "metric":          metric,
                "triggered_at":    run_date,
                "review_status":   "pending",
            }
            try:
                alerts_table.put_item(Item=_to_decimal_dict(alert))
            except Exception:
                pass
            alerts.append(alert)
    return alerts

def _compute_plan_quality_metrics(plans_table, run_date: str) -> dict:
    """
    Stub. Production: cohort-stratified plan-ambition parity, plan-
    complexity parity, action-assignment parity, and outcome-
    trajectory parity. Demo: a single synthetic axis.
    """
    return {
        "plan_ambition_by_language": {
            "language_en_avg_action_count": 9.4,
            "language_es_avg_action_count": 7.1,
            "disparity":                    0.24,   # below threshold in this demo
        },
    }
```

---

## Putting It All Together

Here is the end-to-end pipeline assembled into a single callable function. In production this is split across several Step Functions workflows:

- **Plan-generation pipeline:** Steps 1 through 5 (aggregate inputs, derive goals, assemble and reconcile actions, finalize plan, generate narratives).
- **Plan-review and activation API:** the clinician review surface (SMART on FHIR app) reads narratives via API Gateway, posts approvals back, which kick the activation Lambda (Step 6 activation portion).
- **Feedback ingestion worker:** Lambda consumers on Kinesis update plan-action-records and emit revision triggers via EventBridge.
- **Periodic plan review:** scheduled Step Functions runs `run_periodic_plan_review` on the configured cadence.

The example chains them together so you can trace one cycle end-to-end.

```python
def run_full_demo_cycle(patient_id: str,
                          request_context: dict,
                          patients: dict,
                          run_date: str | None = None) -> dict:
    """
    Run the full demo cycle:
      Step 1: aggregate plan inputs
      Step 2: derive goal set
      Step 3: assemble and reconcile actions
      Step 4: finalize plan
      Step 5: generate narratives
      Step 6: activate approved actions, record a feedback event,
              and run a periodic-review pass.
    """
    run_date = run_date or _today_str()
    start = time.time()

    print(f"=== Starting full demo cycle for patient={patient_id} "
          f"run_date={run_date} ===")

    # Seed templates so the (Step 2 / Step 3) demo lookups have
    # something to read.
    goal_templates_table = dynamodb.Table(GOAL_TEMPLATES_TABLE)
    action_templates_table = dynamodb.Table(ACTION_TEMPLATES_TABLE)
    for tpl in SAMPLE_GOAL_TEMPLATES:
        try:
            goal_templates_table.put_item(Item=_to_decimal_dict(tpl))
        except Exception:
            pass
    for tpl in SAMPLE_ACTION_TEMPLATES:
        try:
            action_templates_table.put_item(Item=_to_decimal_dict(tpl))
        except Exception:
            pass

    # Step 1.
    print("\nStep 1: aggregate plan inputs...")
    plan_input = aggregate_plan_inputs(patient_id, request_context)
    print(f"  Plan input id: {plan_input['plan_input_id']}; "
          f"conditions: "
          f"{len(plan_input.get('clinical_state', {}).get('conditions', []))}; "
          f"meds: "
          f"{len(plan_input.get('clinical_state', {}).get('medications', []))}")

    # Step 2.
    print("\nStep 2: derive goal set...")
    goal_set = derive_goal_set(plan_input, SAMPLE_GOAL_TEMPLATES)
    retained_goals = [g for g in goal_set
                        if not g.get("removed_by_goals_of_care")]
    print(f"  Goals: {len(goal_set)} total; "
          f"{len(retained_goals)} retained after goals-of-care alignment")

    # Step 3.
    print("\nStep 3: assemble and reconcile actions...")
    assembly = assemble_and_reconcile_actions(
        goal_set, plan_input, SAMPLE_ACTION_TEMPLATES,
    )
    actions = assembly["actions"]
    rec = assembly["reconciliation"]
    print(f"  Actions retained: {len(actions)}; "
          f"suppressed: {len(rec['suppressed_actions'])}; "
          f"deprescribing added: {len(rec['deprescribing_added'])}; "
          f"compression: {len(rec['compression_decisions'])}; "
          f"capacity-substituted: {len(rec['capacity_decisions'])}")

    # Step 4.
    print("\nStep 4: finalize plan record...")
    plan = finalize_plan(goal_set, actions, rec, plan_input)
    print(f"  Plan id: {plan['plan_id']}; version: {plan['plan_version']}; "
          f"final actions: {len(plan['final_actions'])}; "
          f"to-be-assigned: {len(plan['to_be_assigned'])}")

    # Step 5.
    print("\nStep 5: generate narratives...")
    narratives = generate_narratives(plan, patients)
    for audience, narrative in narratives.items():
        print(f"  Narrative audience={audience}: "
              f"validator_passed={narrative['validator_status']}; "
              f"layers_passed={narrative['validator_layers_passed']}")

    # Step 6: activation (clinician approves all final actions).
    print("\nStep 6: activate plan...")
    activation = activate_plan(
        plan["plan_id"],
        activation_payload={
            "approving_clinician_id":  "clinician-0142",
            "approved_action_ids":     [a["action_id"]
                                            for a in plan["final_actions"]],
            "clinician_edits":         {},
            "patient_acknowledgment":  {"acknowledged": True,
                                          "method": "portal"},
            "teach_back_results":      {"teach_back_completed": True},
        },
    )
    print(f"  Activation id: {activation.get('activation_id')}")

    # Step 6: feedback (patient reports the daily weight check is
    # working; triggers no revision).
    print("\nStep 6: record action-completion feedback...")
    feedback = record_feedback(
        plan["plan_id"],
        feedback_payload={
            "feedback_kind":     "action_completed",
            "target_action_id":  "weight_daily_log",
            "feedback_data":     {"compliance_days_per_week": 6},
            "source":            "patient",
        },
    )
    print(f"  Feedback id: {feedback['feedback_id']}; "
          f"kind: {feedback['feedback_kind']}")

    # Step 6: periodic review pass.
    print("\nStep 6: periodic-review sweep...")
    alerts = run_periodic_plan_review(run_date)
    print(f"  Surveillance alerts: {len(alerts)}")

    elapsed = int(time.time() - start)
    print(f"\n=== Cycle complete in {elapsed}s ===")
    return {
        "plan_id":            plan["plan_id"],
        "plan_version":       plan["plan_version"],
        "goal_count":         len(goal_set),
        "retained_goals":     len(retained_goals),
        "action_count":       len(actions),
        "to_be_assigned":     len(plan["to_be_assigned"]),
        "narrative_audiences": list(narratives.keys()),
        "activation_id":      activation.get("activation_id"),
        "feedback_id":        feedback.get("feedback_id"),
        "alerts":             len(alerts),
        "elapsed_seconds":    elapsed,
    }
```

---

## Demo Runner

```python
if __name__ == "__main__":
    # All sample data is SYNTHETIC. Do not use real PHI in
    # development. The demo:
    #   1. Builds the index patient (Linda from the recipe's opening
    #      narrative): 67 years old, T2D + CHF + CKD3b + depression
    #      + MCI + osteoarthritis + HTN, recently discharged from a
    #      CHF admission, lives alone, daughter out of state, prefers
    #      to stay at home.
    #   2. Seeds the synthetic clinical state, feature store,
    #      goals-of-care, SDOH, functional status, family caregivers,
    #      and upstream signals from Recipes 4.1 through 4.8.
    #   3. Runs the full cycle: aggregate, derive goals, assemble and
    #      reconcile actions, finalize plan, generate narratives
    #      (with mock Bedrock calls), activate, record feedback, run
    #      a periodic review.
    #
    # The Bedrock calls are mocked at the helper level so the demo
    # runs offline.

    print("=" * 70)
    print("Building synthetic patient and seeding demo state...")
    print("=" * 70)

    run_date = _today_str()
    patient_id = "pat-007842"

    linda = {
        "patient_id":              patient_id,
        "age":                     67,
        "age_band":                "65-74",
        "preferred_language":      "en",
        "race_ethnicity_self_report": "non_hispanic_white",
        "sdoh_cohort":             "transportation_barrier",
        "reading_level_target":    "grade_6",
        "channel_preferences":     {"primary": "portal",
                                       "fallback": "phone"},
        "stated_preferences":      {"prefer_stay_at_home": True,
                                       "decline_long_facility_stays": True},
    }
    patients = {patient_id: linda}

    # Synthetic clinical state. Linda's profile from the recipe's
    # opening narrative.
    _DEMO_HEALTHLAKE_BUNDLES[patient_id] = {
        "conditions": [
            {"condition_id": "I50.22", "active": True,
              "name": "Chronic CHF with reduced EF"},
            {"condition_id": "E11.9",  "active": True,
              "name": "Type 2 Diabetes"},
            {"condition_id": "N18.32", "active": True,
              "name": "CKD stage 3b"},
            {"condition_id": "F32.1",  "active": True,
              "name": "Major Depressive Disorder, moderate"},
            {"condition_id": "Z12.11", "active": True,
              "name": "Encounter for screening for malig neoplasm of colon"},
        ],
        "medications": [
            {"rxnorm_or_id": "metformin_1000mg",     "duration_days": 1500,
              "indication":  "type_2_diabetes"},
            {"rxnorm_or_id": "semaglutide_1mg",      "duration_days": 600,
              "indication":  "type_2_diabetes"},
            {"rxnorm_or_id": "furosemide_40mg",      "duration_days": 1500,
              "indication":  "chronic_heart_failure"},
            {"rxnorm_or_id": "carvedilol_25mg",      "duration_days": 1500,
              "indication":  "chronic_heart_failure"},
            {"rxnorm_or_id": "spironolactone_25mg",  "duration_days": 700,
              "indication":  "chronic_heart_failure"},
            {"rxnorm_or_id": "lisinopril_20mg",      "duration_days": 1500,
              "indication":  "hypertension"},
            {"rxnorm_or_id": "sertraline_50mg",      "duration_days": 730,
              "indication":  "major_depressive_disorder"},
            {"rxnorm_or_id": "omeprazole_20mg",      "duration_days": 1095,
              "indication":  "long_term_no_indication"},
        ],
        "labs": {
            "a1c_recent":  8.4,
            "egfr_recent": 39,
            "ef_recent":   38,
        },
        "encounters": [
            {"kind": "inpatient", "discharge_date": "2026-04-15",
              "primary_diagnosis": "I50.22"},
        ],
        "allergies": [],
    }

    _DEMO_FEATURE_STORE[patient_id] = {
        "age":                          67,
        "frailty_index":                0.30,
        "chf_severity":                 "severe",
        "bmi":                          29.0,
        "away_from_home_per_week_cap":  3,
    }

    _DEMO_GOALS_OF_CARE[patient_id] = {
        "polst":                None,
        "advance_directive":    {"recorded": False},
        "comfort_focused_flag": False,
        "stated_preferences":   {"prefer_stay_at_home": True},
        "explicit_declines":    [],
        "decision_maker":       "self_with_daughter_consult",
        "last_updated":         "2026-04-22",
    }

    _DEMO_SDOH[patient_id] = {
        "transportation":      "limited",
        "food_security":       "moderate",
        "housing_stability":   "second_floor_walk_up",
        "financial_strain":    "moderate",
        "social_support":      "isolated_with_remote_daughter",
        "language":            "en",
        "digital_literacy":    "moderate",
        "last_assessed":       "2026-03-10",
    }

    _DEMO_FUNCTIONAL_STATUS[patient_id] = {
        "adl_score":          5,
        "iadl_score":         5,
        "cognitive_status":   "mild_impairment",
        "mobility":           "limited_by_oa_knees",
        "last_assessed":      "2026-03-10",
    }

    _DEMO_FAMILY_CAREGIVERS[patient_id] = [
        {"relationship": "daughter",
          "role_in_care": "phone_check_ins_decision_consult",
          "contact":      "out_of_state",
          "consent_status": "consented"},
    ]

    _DEMO_PRIOR_PLANS[patient_id] = {
        "plan_id":      "plan-prior-007842",
        "plan_version": 6,
        "generated_at": "2026-01-22T14:00:00Z",
    }

    # Upstream signals from Recipes 4.1 through 4.8.
    _DEMO_UPSTREAM_SIGNALS["recipe-4.1"] = {patient_id: {
        "appointment_reminder_channel": "phone",
    }}
    _DEMO_UPSTREAM_SIGNALS["recipe-4.6"] = {patient_id: [
        {"care_gap_id": "col_screening", "priority": 0.78},
        {"care_gap_id": "phq9_assessment", "priority": 0.55},
    ]}
    _DEMO_UPSTREAM_SIGNALS["recipe-4.7"] = {patient_id: {
        "enrolled":            True,
        "program":             "high_risk_chf_complex_chronic",
        "care_manager_id":     "cm-0188",
        "care_manager_name":   "Jordan",
    }}

    # Capacity snapshot for the reconciliation step.
    _DEMO_CAPACITY.update({
        "cardiology_clinic_scheduler": {"at_capacity": True,
                                          "reason": "scheduler_capacity_exceeded"},
    })

    # Mock Bedrock narrative call so the demo runs offline.
    def _mock_invoke(context, model_id, strict_mode=False):
        plan = context["plan_record"]
        audience = context["audience"]
        if audience == "clinician":
            return {
                "headline": (
                    f"Plan v{plan['plan_version']} ready for review post-CHF "
                    f"admission; {len(plan['final_actions'])} actions "
                    f"across {len(plan['goal_set'])} goals."
                ),
                "what_changed_since_prior": [
                    "Added daily diuretic adherence and weight monitoring "
                    "for chf_avoid_readmission.",
                    "Suppressed naproxen_for_oa_pain (chf_severe and egfr_under_45).",
                    "Added deprescribing candidate deprescribe_ppi_long_term.",
                    "Capacity-substituted cardiac_rehab_enrollment owner to "
                    "care_manager.",
                ],
                "care_team_attention": [
                    "Verify transportation benefit before cardiac rehab.",
                    "PPI deprescribing requires PCP review.",
                ],
                "narrative_paragraph": (
                    "This plan reflects post-discharge focus on chf_avoid_readmission "
                    "while preserving the patient's stated preference to stay at home. "
                    "Reconciliation suppressed an NSAID action contraindicated in CHF "
                    "and CKD3b, surfaced a long-term PPI deprescribing candidate, and "
                    "reassigned cardiac rehab enrollment due to scheduler capacity."
                ),
            }
        if audience == "patient":
            return {
                "headline": (
                    "Your care plan for the next few weeks. Your care "
                    "team made these updates after your hospital stay."
                ),
                "this_week": [
                    "Take your water pill at 8 in the morning, every day. "
                    "Set a phone alarm if it helps.",
                    "Weigh yourself every morning after using the bathroom. "
                    "Write the weight in your patient portal.",
                ],
                "this_month": [
                    "Your colonoscopy is overdue. Your care manager will "
                    "help schedule it and arrange the ride your plan covers.",
                    "We will see you in the office for a follow-up visit "
                    "on your mood.",
                ],
                "this_quarter": [
                    "We are signing you up for cardiac rehab close to your "
                    "home, with rides arranged.",
                    "A social worker will visit you at home to talk through "
                    "what is most important to you.",
                ],
                "ongoing": [
                    "Your care manager will call you once a month to check "
                    "in on how everything is going.",
                ],
                "what_changed": (
                    "After your hospital stay, we added the daily weight "
                    "check and the cardiac rehab. We are also working on "
                    "getting your colonoscopy scheduled with transportation help."
                ),
                "questions": (
                    "If anything in this plan does not work for you, please "
                    "call your care manager. Your plan is meant to fit your "
                    "life, not the other way around."
                ),
                "contact": {
                    "care_manager_name": "Jordan",
                    "phone":             "(800) 555-0142",
                    "portal_link":       "secure.example.com/portal",
                },
            }
        # Care-team-internal disagreement (used only when present).
        return {
            "headline": "Reconciliation surfaced items needing care-team review.",
            "conflict_description": (
                "The plan has unresolved items that the reconciliation "
                "engine could not finalize without escalation."
            ),
            "candidate_resolutions": [
                "Convene the care team for a 15-minute huddle this week.",
                "Resolve the open assignments and re-trigger plan finalization.",
            ],
            "recommended_escalation": (
                "Care manager schedules a 15-minute team huddle to resolve "
                "the open items before the plan-review SLA elapses."
            ),
        }

    globals()["_bedrock_invoke_narrative"] = _mock_invoke

    print(f"  Patient: {patient_id} (Linda)")
    print(f"  Conditions: "
          f"{len(_DEMO_HEALTHLAKE_BUNDLES[patient_id]['conditions'])}; "
          f"Medications: "
          f"{len(_DEMO_HEALTHLAKE_BUNDLES[patient_id]['medications'])}")

    print("\n" + "=" * 70)
    print("Running full demo cycle...")
    print("=" * 70)

    summary = run_full_demo_cycle(
        patient_id=patient_id,
        request_context={
            "trigger":               "post_discharge_review",
            "requesting_clinician":  "pcp",
            "scope":                 "full_plan_review",
        },
        patients=patients,
        run_date=run_date,
    )

    print(f"\nSummary:")
    print(f"  plan_id:           {summary['plan_id']}")
    print(f"  plan_version:      {summary['plan_version']}")
    print(f"  goal_count:        {summary['goal_count']}")
    print(f"  retained_goals:    {summary['retained_goals']}")
    print(f"  action_count:      {summary['action_count']}")
    print(f"  to_be_assigned:    {summary['to_be_assigned']}")
    print(f"  narrative_audiences: {summary['narrative_audiences']}")
    print(f"  activation_id:     {summary['activation_id']}")
    print(f"  feedback_id:       {summary['feedback_id']}")
    print(f"  surveillance_alerts: {summary['alerts']}")

    print("\n=== Demo complete ===")
```

---

## The Gap Between This and Production

Run this end-to-end against a real EHR with a curated clinical-content library, real interaction databases, real patient features, real upstream signals from Recipes 4.1 through 4.8, real goals-of-care preferences, working SMART on FHIR review surface, and a clinical-informatics-led UX, and you will see the pattern: structured-then-narrative care plan generation with multi-condition reconciliation, goals-of-care alignment, therapeutic-burden compression, four-layer LLM validation, and a feedback loop. The distance between this and a real EHR-integrated deployment is significant. Here is where it lives.

**Clinical-content library curation as an ongoing program.** The goal-template and action-template library is the substrate of the system. Plan for at least 1.0 to 2.0 FTE of clinical informaticist time, plus part-time involvement from pharmacy, care management, quality, and patient education. Establish a versioned change-management process with parallel evaluation against the prior version on a held-out cohort. The pattern that fails is treating the content library as engineering work; the templates drift from current clinical practice within a year.

**FHIR-native plan persistence in HealthLake.** Production persists the plan as a FHIR `CarePlan` with linked `Goal`, `Task`, and `ServiceRequest` resources, in HealthLake. The mapping from the internal plan record to the FHIR resources is straightforward in principle and operationally non-trivial: profile selection (US Core, IPS, payer-specific), value-set bindings, extension management. Plan for an integration engineer plus a FHIR-knowledgeable informaticist on the integration. Plan portability across care settings is the payoff.

**Real interaction database integration.** Drug-drug, drug-disease, and drug-allergy checks need a licensed interaction database (First Databank, Lexicomp, Wolters Kluwer Medi-Span). The example uses contraindication codes on the action templates plus a few hard-coded patient-state checks. Production wires the real database into the action-assembly Lambda via a private connection, with caching for performance and full audit logging for the clinical-records audit trail.

**Validated burden scoring.** The example uses static `burden_score` values on the templates. Production calibrates a per-patient burden estimator using a validated instrument (the Treatment Burden Questionnaire, the Patient Experience with Treatment and Self-Management measure, or an internally validated equivalent) and applies it as the threshold in the compression step. The naive sum-of-scores approach systematically deprioritizes the wrong actions for patients with the least support; that is a fairness failure dressed up as a feature.

**Real capacity-and-schedule reconciliation.** The example checks capacity against a hard-coded snapshot. Production integrates with the staffing system (care-manager panel sizes, social-worker capacities, specialist scheduling), the patient's stated capacity (often captured in structured form on the portal but rarely propagated), and the program registry (cardiac rehab cohort openings, diabetes self-management education sessions). The reconciliation engine is one of the most operationally complex pieces of the system.

**SageMaker Feature Store for patient features.** The example reads from in-memory dicts. Production wires Feature Store online-store calls for the per-patient feature vector, with feature freshness tracking and per-feature schema versioning. The same Feature Store powers Recipes 4.4 through 4.8; centralizing the features is the entire point.

**SMART on FHIR plan-review surface.** The example exposes plan generation as a Python function. Production: an authenticated API Gateway endpoint consumed by a SMART on FHIR app embedded in the EHR. Plan for at least 12 to 20 weeks of EHR-integration engineering per EHR vendor, with authentication via the institution's identity provider (SAML or OIDC), PHI handling at the integration boundary, latency budgets, and the clinician workflow design. The plan-review surface UX is iterative; budget for clinical-informatics-led iteration after launch.

**Patient portal and channel integration.** The patient-facing narrative is delivered through the portal (Epic MyChart, Cerner HealtheLife, athenahealth Patient Portal, custom). Most portals have limited APIs for structured-content delivery; the work of rendering the plan in the portal is iterative UX work. Mailed letter delivery for low-digital-literacy patients is non-trivial (mail vendor integration, deduplication, opt-out handling). Budget the channel integration as a separate workstream.

**Activation dispatcher to operational systems.** The example logs the dispatch action. Production routes per clinical-payload kind to the right operational system: medication actions to the e-prescribing system, appointment actions to the scheduling system, program enrollment actions to the program registry, patient-facing reminders to Pinpoint or the portal sender, care-manager outreach to the care-management system. Each integration is its own engineering effort with its own auth, latency, error handling, and observability requirements.

**Validator extension and per-layer alarms.** The example codes the four layers as a single function for readability. Production breaks the layers apart for testability and per-layer alarms: a fallback-rate spike on the prohibited-language layer indicates the LLM is drifting; a fallback-rate spike on the fact-grounding layer indicates the structured-context formatting may be obscuring the plan elements. Track per-layer fail rates as separate CloudWatch metrics.

**Bedrock cost and latency budget.** The clinician narrative uses a Sonnet-class model because the prompt is long-context and the validator's grounding rule is strict. At tens of thousands of plans per month across clinician, patient, and internal audiences, the budget is meaningful. Production tunes the model choice per audience and per validator pass-rate; consider routing first attempts to a smaller model with stricter prompts and falling back to Sonnet only on validator failure. Monitor Bedrock spend in CloudWatch and set per-account quota alarms.

**Cohort fairness instrumentation tied to a quarterly review committee.** The example computes a stub disparity metric. Production wires QuickSight dashboards for plan-ambition parity, plan-complexity parity, action-assignment parity, and outcome-trajectory parity per cohort axis. A cross-functional committee (medical director, clinical informatics, equity lead, data science lead, regulatory and compliance lead) reviews the dashboards quarterly with explicit action ownership for findings. The Obermeyer 2019 finding is the canonical cautionary tale; design for it from day one.

**Plan-revision trigger calibration.** The example uses simple heuristics for revision triggers. Production calibrates per-trigger sensitivity (acute hospitalization always triggers; weight gain only triggers if it exceeds a threshold and persists; new medication only triggers if the class is on a watch list) and tunes per cohort (older patients have more sensitive triggers because the underlying instability is higher). Build the trigger-calibration analysis pipeline before you need it.

**Cross-recipe orchestration with Recipes 4.1 through 4.8.** The example calls `_try_fetch_upstream` stubs. Production wires real integrations: changes in Recipe 4.5's adherence intervention should trigger a plan-revision check; changes in Recipe 4.7's care management enrollment should propagate; treatment-response predictions in Recipe 4.8 inform the action-priority weighting. Document the cross-recipe data flow up front. The breadth of inputs is the personalization density that distinguishes 4.9 from prior recipes; the breadth has to be reliable.

**Operational privacy in plan records and narratives.** The `plan-records` table joins patient_id with the structured plan; the `plan-narratives` table joins patient_id with the LLM-generated prose. Both are highly inferential PHI. Apply tighter controls than for engagement data: narrower IAM read scopes, optional separate-table partitioning by sensitivity tier, additional CloudTrail data event capture, and a documented minimum-necessary access policy. The S3 plan archive accumulates indefinitely; data-retention policy needs to balance audit requirements against minimization principles.

**Tracking-ID privacy.** The example uses opaque ids (`plan-{uuid}`, `narr-{uuid}`, `par-{uuid}`) and never embeds patient_id in identifiers. The discipline is intentional: plain-text patient_ids embedded in plan IDs (carried in EHR responses, plan-review API responses, narratives, and event payloads) are PHI leakage. Production must replace any composite-with-identifiable-fields ID with UUIDs or HMAC-SHA256 over the composite with a per-environment secret. Mirror the language flagged in 4.4 through 4.8.

**Step Functions orchestration with explicit DLQ coverage.** The example chains all steps in a single Python function. Production runs plan generation as a Step Functions state machine; the activation worker as a Lambda triggered by the EHR-integration approval event; the feedback ingestion worker as a Lambda on the Kinesis stream; the periodic-review pipeline as a separate state machine. Each task has Catch handlers routing failures to per-stage SQS DLQs keyed on (run, plan_id, stage, failure_reason). The Kinesis-to-Lambda event source mappings configure explicit `OnFailure` destinations pointing to SQS, alarmed on DLQ depth. The plan-finalization path must fail loudly: a plan-generation failure returns "plan generation temporarily unavailable" rather than a partial or empty plan. Mirror the language from 4.4 through 4.8.

**Idempotency and retry semantics.** Each stage's outputs are addressed by deterministic keys (plan_input_id, plan_id, narrative_id, plan_action_record_id) and writes are conditional. The example uses `ConditionExpression="attribute_not_exists(plan_id)"` on the plan-record put; production extends this discipline to every persistence boundary (idempotent narrative puts, idempotent activation records). A Step Functions retry that re-attempts a completed step is a no-op rather than a duplicate.

**VPC, encryption, and audit.** This example calls APIs over public AWS endpoints. A production Lambda handling PHI runs in a VPC with private subnets and VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock Runtime (interface), Kinesis (interface), CloudWatch Logs (interface), Step Functions, EventBridge (`events`), STS, API Gateway, HealthLake, Pinpoint, and SageMaker Feature Store. All eight DynamoDB tables encrypt at rest with a customer-managed KMS key. CloudTrail data events are enabled for the goal-templates, action-templates, plan-records, plan-narratives, plan-action-records, and plan-feedback-records tables. The audit posture for care-plan artifacts approaches clinical-record audit standards.

**Synthetic data and testing.** There are no tests in this example. A production pipeline needs unit tests for the cohort-tag computation, the cohort-override application, the goals-of-care adjustment, the contraindication checker, the deprescribing rule engine, the burden-compression decisions, the capacity-substitution logic, the schedule reconciliation, the four validator layers, the activation flow, the feedback flow, and the periodic-review pass; integration tests against synthetic Synthea-generated patient populations across cohort axes; regression tests that confirm the validator catches prohibited-language attempts; load tests at expected volumes (50,000 plans per month). Never use real PHI in non-production environments.

**Cold-start handling.** A patient with a new diagnosis has limited longitudinal data; the personalization layer is sparse. Cold-start plans use cohort-level defaults more heavily. Document the limitation explicitly in the patient narrative ("this is a starting point; we will refine as we learn more"); set patient expectations.

**Patient-driven plan editing.** The example codes patient acknowledgment but not patient-driven edits. Production extends with a structured edit pipeline: the patient can suggest action removal, action substitution, or goal addition, with a clinical-team review gate before edits become part of the active plan. Free-text edit suggestions are mapped to structured plan elements; safety-critical changes require clinical review.

**Caregiver-facing narrative.** When a patient has a designated family caregiver with consent, a third audience-specific narrative addresses the caregiver directly: what to watch for, when to escalate, what specific support to provide, and what is not the caregiver's responsibility (an explicit boundary statement). The validator extends to a caregiver-audience layer with caregiver-specific prohibited-language patterns.

**Multi-language patient narratives.** Production supports the languages the patient population speaks. Beyond simple machine translation: language-specific reading-level scoring, cultural-context overrides for goal framing, idiomatic localization, language-specific approved-claim language. Plan for in-language clinical content review. Machine translation alone is not sufficient for clinical content.

**Regulatory pathway determination.** The form of the patient-facing narrative (educational versus directive), the degree of clinical-team review before patient delivery, and the specificity of action instructions all affect the regulatory analysis. Plan for regulatory legal review at scoping, with explicit framing of the system's posture (clinician-mediated, patient-direct, hybrid). Retrofitting compliance is dramatically more expensive than building it in. Confirm current FDA Clinical Decision Support guidance and the 21st Century Cures Act exemption criteria at the time of build; the regulatory landscape is evolving and the analysis is fact-specific.

**Patient consent for data use.** The plan uses goals-of-care preferences, SDOH data, functional and cognitive status, family-caregiver involvement, and longitudinal engagement signals. Each has a consent posture; the patient should be aware that the data is used and able to opt out. Document the consent posture in the patient-facing narrative; "your care plan was generated using your medical record, your stated preferences, and your social and functional context" is the kind of explicit framing that builds trust.

**Adverse-event surveillance.** The example revises the plan on adverse_event feedback. Production runs adverse-event surveillance against the plan-attributable cohort over time, looking for higher-than-expected adverse-event rates following plan activation. This is essential for any care-management system and an ethical expectation regardless of regulatory classification.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 4.9: Personalized Care Plan Generation](chapter04.09-personalized-care-plan-generation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
