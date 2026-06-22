# Recipe 4.7: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 4.7. It shows one way you could translate the care management program enrollment pattern into working Python using AWS Glue / Athena for nightly eligibility evaluation against the program registry, Amazon SageMaker (Feature Store, Batch Transform, Training) for the per-program response (uplift), enrollment-likelihood, and engagement-prediction models, Amazon DynamoDB for the program registry, the per-(patient, program) state machine, the recommendation log, the outreach state, the engagement state, the enrollment briefings, and the disenrollment decisions, Amazon S3 for the data lake and evaluation outputs, AWS Step Functions for the daily eligibility, weekly enrollment-decision, and monthly outcome-evaluation pipelines, AWS Lambda for the per-stage glue, Amazon Bedrock for enrollment briefings, patient-facing message tailoring, mid-program engagement summaries, and disenrollment-decision rationales, Amazon Kinesis for outreach, engagement, clinical, and disenrollment events, Amazon Connect for care-manager telephonic outreach, and Amazon SES / Amazon Pinpoint for member-facing email and SMS. It is not production-ready. There is no real claims, EHR, lab, pharmacy, discharge feed, or care management system integration, no validated propensity-matched difference-in-differences evaluation, no causal-inference-grade response models, no live randomized hold-out cohort, no Connect contact-flow integration, no real consent capture and HIPAA authorization workflow, no actual cohort-aware fairness instrumentation tied to a quarterly review committee. Think of it as the sketchpad version: useful for understanding the shape of a multi-stage care management enrollment recommender that respects program semantics, capacity constraints, equity floors, longitudinal state, and engagement tracking, not something you'd wire into a 250,000-member health plan on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the six pseudocode steps from the main recipe: evaluate the program registry against patient data to produce per-(patient, program) eligibility records, score per-program response (uplift), enrollment likelihood, and program-fit and synthesize priority, run multi-stage capacity-and-equity-constrained allocation across time-sensitive, disease-specific, complex-care, and add-on programs, generate care-manager-facing enrollment briefings and dispatch outreach, track in-program engagement and trigger retention attempts when engagement declines, and process the human disenrollment decision plus cross-program transitions and post-graduation observation. All sample patients, programs, eligibility records, engagement events, and outcome events are synthetic.

---

## Setup

You'll need the AWS SDK for Python and a couple of utility libraries:

```bash
pip install boto3 pandas numpy
```

For the local response-model experimentation (training scripts not shown in the inference path) you'd add `xgboost`, `lightgbm`, `econml`, and `dowhy`. The inference path itself only needs the SageMaker Batch Transform output, so the production Lambdas don't import those libraries.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `sagemaker:CreateTransformJob`, `sagemaker:DescribeTransformJob` on specific model ARNs (the per-program response, enrollment-likelihood, and engagement-prediction models, three model families across five programs in the example)
- `sagemaker:GetRecord`, `sagemaker:BatchGetRecord`, `sagemaker:PutRecord` on the SageMaker Feature Store feature group ARNs (`patient-program-features`, `patient-profile-features`)
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchWriteItem` on the program-registry, patient-program-state, patient-profile, recommendation-log, enrollment-briefings, outreach-state, engagement-state, disenrollment-decisions, and cross-program-transitions tables
- `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on the cm-data-lake, cm-feature-store-offline, cm-evaluation, cm-scores, and cm-event-lake buckets
- `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults` for the eligibility-evaluation pipeline
- `glue:GetTable`, `glue:GetPartitions` on the data-catalog tables Athena reads
- `bedrock:InvokeModel` on the specific model ARNs used for enrollment briefings, patient-message tailoring, engagement summaries, and disenrollment-decision rationales (e.g., a Claude Haiku or Nova Lite model)
- `kinesis:PutRecord` on the cm-engagement-stream
- `ses:SendEmail` scoped to the BAA-covered identity (or `pinpoint:SendMessages` for SMS)
- `connect:StartOutboundContact` (only if using Amazon Connect for in-house care-management team), scoped to the care-management contact flow
- `cloudwatch:PutMetricData` for cohort-sliced metrics
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs

You also need model access enabled in the Bedrock console for the enrollment-briefing, patient-message-tailoring, engagement-summary, and disenrollment-rationale models.

A few things worth knowing upfront:

- **The program registry is the source of truth for what each program is and who it's for.** This example ships with a small synthetic registry of 5 programs covering disease-specific (heart-failure, diabetes), complex-care, transitional, and polypharmacy archetypes. Production needs structured change management with clinical operations, program leadership, and contracts review, with parallel evaluation against the prior registry version when significant changes ship.
- **Per-program response (uplift) modeling is the hardest part and the part most teams skip.** Production-grade response estimation requires either randomized enrollment in a fraction of slots or careful causal-inference tooling (propensity matching, doubly-robust estimation, instrumental variables) on observational enrollment data. The training scripts are out of scope for this companion; the main recipe's "Why This Isn't Production-Ready" section walks through the gap. The example uses rule-based proxies.
- **The engagement-and-retention worker is the part that determines whether enrollment actually translates into outcomes.** This example wires per-program engagement scoring, decline-pattern classification, and retention-strategy dispatch. Production extends with a much richer engagement-event stream, modality-switching automation, and structured retention budgets per cohort.
- **Bedrock model IDs change over time.** Some regions require cross-region inference profile IDs (prefixed `us.` or `eu.`). The IDs below are reasonable defaults; verify in the Bedrock console for your region before running.
- **All patients, programs, eligibility records, engagement events, and outcome events in the example are synthetic.** Do not treat any specific patient_id, program_id, evidence event, enrollment event, or engagement event as real. A production system ingests from real claims, EHR, lab, pharmacy, discharge feeds, and care management system events under BAA.
- **The example collapses Step Functions, Glue, Athena, and SageMaker Batch Transform into a single Python file for readability.** In production these are separate workflow stages with their own error handling, IAM, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, table names, S3 buckets, allocator policy weights, equity floors, contact-frequency caps, suppression policies, and program archetypes are the knobs you'll change between environments.

```python
import json
import logging
import time
import uuid
import datetime
from datetime import timezone, timedelta
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records to
# CloudWatch Logs Insights. Never log a raw (patient_id, program_id,
# state, uplift_score, priority_components) join along with clinical
# context; the row implicitly identifies the patient, the suspected
# diagnosis pattern, and the program's theory of change. The
# patient-program-state and enrollment-briefings tables are highly
# inferential PHI.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from SageMaker, DynamoDB, Bedrock,
# Kinesis, S3, Athena, and SES during the daily eligibility and
# weekly enrollment-decision runs. Care management pipelines are
# bursty: nightly batch evaluation, then a weekly enrollment-decision
# cycle, plus on-demand evaluation triggered by discharge events.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
sagemaker_client = boto3.client("sagemaker", config=BOTO3_RETRY_CONFIG)
sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
sagemaker_featurestore = boto3.client(
    "sagemaker-featurestore-runtime", config=BOTO3_RETRY_CONFIG
)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
kinesis_client = boto3.client("kinesis", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
athena_client = boto3.client("athena", config=BOTO3_RETRY_CONFIG)
cloudwatch_client = boto3.client("cloudwatch", config=BOTO3_RETRY_CONFIG)
ses_client = boto3.client("ses", config=BOTO3_RETRY_CONFIG)

# --- Model Configuration ---
# Four distinct LLM use cases, each wired to a small/fast model.
# Haiku-class hits the cost target at scale; larger frontier models
# add cost without meaningfully better tailoring on these prompt
# shapes. Production picks the model per use case based on observed
# quality regressions, not a uniform default.
ENROLLMENT_BRIEFING_MODEL_ID    = "anthropic.claude-3-5-haiku-20241022-v1:0"
PATIENT_MESSAGE_MODEL_ID        = "anthropic.claude-3-5-haiku-20241022-v1:0"
ENGAGEMENT_SUMMARY_MODEL_ID     = "anthropic.claude-3-5-haiku-20241022-v1:0"
DISENROLLMENT_RATIONALE_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"

# Names of the SageMaker model artifacts. Three model families per
# program: response (uplift), enrollment-likelihood, engagement-
# prediction. With five programs in the demo, that's 15 artifacts.
# Production schedules retraining and promotion via SageMaker Model
# Registry with a canary run on a held-out cohort before promotion.
UPLIFT_MODEL_NAMES = {
    "heart-failure-program":          "uplift-hf-v3",
    "diabetes-management-program":    "uplift-dm-v2",
    "complex-care-management":        "uplift-ccm-v4",
    "transitional-care-management":   "uplift-tcm-v3",
    "polypharmacy-management":        "uplift-poly-v2",
}
LIKELIHOOD_MODEL_NAMES = {
    "heart-failure-program":          "likelihood-hf-v3",
    "diabetes-management-program":    "likelihood-dm-v2",
    "complex-care-management":        "likelihood-ccm-v3",
    "transitional-care-management":   "likelihood-tcm-v3",
    "polypharmacy-management":        "likelihood-poly-v2",
}
ENGAGEMENT_MODEL_NAMES = {
    "heart-failure-program":          "engagement-hf-v3",
    "diabetes-management-program":    "engagement-dm-v2",
    "complex-care-management":        "engagement-ccm-v3",
    "transitional-care-management":   "engagement-tcm-v2",
    "polypharmacy-management":        "engagement-poly-v2",
}

# --- DynamoDB Table Names ---
# Nine tables. Keep them separate so access patterns stay clean and
# IAM scoping is precise:
#   1. program-registry:           canonical program definitions
#                                   (program_id + version PK)
#   2. patient-program-state:      per-(patient, program) state
#                                   machine (patient_id + program_id PK)
#   3. patient-profile:            member demographics, prefs, cohort
#                                   attributes (patient_id PK)
#   4. recommendation-log:         per (patient, program, run_date)
#                                   allocation row
#   5. enrollment-briefings:       per-(patient, program, run_date)
#                                   LLM-generated briefings
#   6. outreach-state:             in-flight outreach attempts
#   7. engagement-state:           per-(patient, program) engagement
#                                   scoring + decline pattern
#   8. disenrollment-decisions:    decision-support records pending
#                                   human review
#   9. cross-program-transitions:  cross-program transition
#                                   recommendations pending review
PROGRAM_REGISTRY_TABLE             = "program-registry"
PATIENT_PROGRAM_STATE_TABLE        = "patient-program-state"
PATIENT_PROFILE_TABLE              = "patient-profile"
RECOMMENDATION_LOG_TABLE           = "recommendation-log"
ENROLLMENT_BRIEFINGS_TABLE         = "enrollment-briefings"
OUTREACH_STATE_TABLE               = "outreach-state"
ENGAGEMENT_STATE_TABLE             = "engagement-state"
DISENROLLMENT_DECISIONS_TABLE      = "disenrollment-decisions"
CROSS_PROGRAM_TRANSITIONS_TABLE    = "cross-program-transitions"

# --- S3 Buckets ---
# Production: each bucket has its own KMS key and bucket policy.
# Replace placeholder names with your account's buckets.
CM_DATA_LAKE_BUCKET            = "cm-recommender-data-lake"
CM_EVALUATION_BUCKET           = "cm-recommender-evaluation"
CM_SCORES_BUCKET               = "cm-recommender-scores"
CM_FEATURE_STORE_OFFLINE_BUCKET = "cm-recommender-feature-store-offline"
CM_EVENT_LAKE_BUCKET           = "cm-recommender-event-lake"
ATHENA_RESULTS_BUCKET          = "cm-recommender-athena-results"

# --- Athena ---
ATHENA_WORKGROUP = "cm-recommender"
ATHENA_DATABASE  = "cm_data_lake"

# --- Kinesis ---
# CM engagement stream pattern reused from Recipes 4.1-4.6, with new
# event types specific to this recipe: eligibility_acquired,
# program_recommended, program_outreach_initiated,
# program_outreach_attempted, program_consent_obtained,
# program_enrolled, program_engagement_event, program_at_risk,
# program_retention_attempted, program_disenrolled,
# program_graduated, program_re_eligible,
# cross_program_transition_recommended,
# disenrollment_decision_recommended,
# post_graduation_relapse_detected.
CM_ENGAGEMENT_STREAM_NAME = "cm-engagement-stream"

# --- SES ---
SES_FROM_ADDRESS         = "carecoordination@example-health-plan.org"
SES_CONFIGURATION_SET    = "cm-recommender-baa"

# --- Run Configuration ---
POLICY_VERSION = "cm-policy-v0.6"

# Policy weights for priority synthesis. Documented and version-
# controlled. Uplift is the dominant weight because it captures the
# counterfactual benefit (the outcome change attributable to
# enrollment, not just the patient's risk level).
POLICY_WEIGHTS = {
    "uplift":                       0.45,
    "enrollment_likelihood":        0.20,
    "program_fit":                  0.20,
    "post_enrollment_engagement":   0.15,
}

# Disease-fit threshold for stage 2 of the multi-stage allocator.
# Patients below this fit threshold are held for stage 3 (complex-care).
DISEASE_FIT_THRESHOLD = 0.55

# Per-patient add-on cap. Add-ons (polypharmacy, behavioral-health)
# stack on top of one primary program; the cap prevents excessive
# stacking.
MAX_ADD_ONS_PER_PATIENT = 2

# Outreach-attempt limits.
MAX_OUTREACH_ATTEMPTS = 5

# Retention-attempt limits before disenrollment-for-cause is
# considered.
MAX_RETENTION_ATTEMPTS = 3

# Days of no engagement before disenrollment-for-cause is considered
# (after retention attempts have failed).
DISENROLL_NO_ENGAGEMENT_DAYS = 21

# Re-eligibility window after disenrollment-for-cause (days).
RE_ELIGIBILITY_WINDOW_FOR_NO_ENGAGEMENT = 90

# Post-graduation observation window (days).
POST_GRADUATION_OBSERVATION_DAYS = 180

# Extension days when extending a near-completion enrollment.
EXTENSION_DAYS = 28

# Enrollment-outreach contact budget. Care management enrollment
# outreach uses a separate budget from the routine engagement
# messaging in 4.4-4.6, since the enrollment conversation is a
# distinct, infrequent interaction. Document the exception in the
# cross-recipe policy.
MAX_CM_OUTREACH_PER_PATIENT_30D    = 2
MAX_TOTAL_CONTACTS_PER_PATIENT_30D = 3   # 4.4-4.6 engagement budget

# Allowed states for the per-(patient, program) state machine. The
# state machine is the source of truth; downstream consumers gate
# on these.
ALLOWED_PROGRAM_STATES = [
    "ineligible",
    "eligible",
    "recommended",
    "outreach_in_progress",
    "consented",
    "declined",
    "deferred",
    "outreach_failed",
    "enrolled",
    "engaged",
    "at_risk",
    "enrolled_extended",
    "disenrolled_incomplete",
    "disenrolled_for_cause",
    "graduated",
    "in_observation_relapse_detected",
    "re_eligible",
    "transitioned_out",
    "excluded",
]

# CloudWatch namespace for care management metrics. Slice by
# program_id, stage, language, engagement-history quartile, and
# SDOH cohort to catch subgroup drift.
METRIC_NAMESPACE = "CareManagementRecommender"
```

---

*Continued in subsequent sections.*

## Reference Data: Synthetic Program Registry, Capacity, and Equity Floors

A small program registry used by the example. Production loads from the `program-registry` DynamoDB table, fed by program leadership through a governance UI and versioned. Each program has structured denominator / inclusion / exclusion logic, capacity, language and geographic support, theory-of-change tags, target duration, expected per-patient cost, expected per-patient uplift magnitude, and category (primary or add-on, time-sensitive or not, disease-specific or complex-care).

```python
# Synthetic program registry. In production this lives in DynamoDB
# and is updated by the registry-sync Lambda when program leadership
# pushes registry changes through EventBridge. Each program entry is
# the source of truth for what counts as eligibility, what the
# program is for, and what its capacity is. New programs land as
# new registry versions; engineering does not hard-code program logic.
SAMPLE_PROGRAM_REGISTRY = [
    {
        "program_id":               "transitional-care-management",
        "version":                  "2026-v1",
        "display_name":             "Transitional Care Management (30-day post-discharge)",
        "category":                 "primary",
        "is_time_sensitive":        True,
        "subcategory":              "transitional",
        "denominator_logic": {
            "age_min":                  18,
            "age_max":                  120,
            "discharge_within_days":    14,    # post-discharge time window
            "continuous_enrollment_months": 1,
        },
        "inclusion_logic": {
            "inpatient_admission_within_days": 30,
            "discharge_disposition_excludes":   ["expired", "left_ama"],
        },
        "exclusion_codes":          ["hospice", "palliative_care",
                                      "currently_in_other_cm_program"],
        "supported_languages":      ["en", "es"],
        "supported_geographies":    ["all"],
        "target_active_capacity":   180,
        "target_duration_days":     30,
        "expected_cost_per_patient": 350,
        "expected_uplift_magnitude": 0.12,    # 12 pp readmission reduction
        "primary_outcome":          "30_day_all_cause_readmission_rate",
        "theory_of_change":         "Structured early support during the high-risk first 30 days reduces readmissions via medication reconciliation, follow-up scheduling, and symptom-monitoring.",
        "effective_start":          "2026-01-01",
        "effective_end":            "2026-12-31",
    },
    {
        "program_id":               "heart-failure-program",
        "version":                  "2026-v2",
        "display_name":             "Heart Failure Disease Management Program",
        "category":                 "primary",
        "is_time_sensitive":        False,
        "subcategory":              "disease_specific",
        "denominator_logic": {
            "age_min":                  18,
            "age_max":                  120,
            "required_conditions":      ["heart_failure"],
            "continuous_enrollment_months": 6,
        },
        "inclusion_logic": {
            "hf_related_encounter_within_days": 180,
        },
        "exclusion_codes":          ["hospice", "palliative_care",
                                      "advanced_dementia_severe",
                                      "currently_in_other_disease_program"],
        "supported_languages":      ["en", "es"],
        "supported_geographies":    ["all"],
        "target_active_capacity":   320,
        "target_duration_days":     84,    # 12-week curriculum
        "expected_cost_per_patient": 1800,
        "expected_uplift_magnitude": 0.18,
        "primary_outcome":          "90_day_readmission_rate_change",
        "theory_of_change":         "Weekly check-ins, weight monitoring, medication optimization, and symptom self-management reduce HF decompensations.",
        "effective_start":          "2026-01-01",
        "effective_end":            "2026-12-31",
    },
    {
        "program_id":               "diabetes-management-program",
        "version":                  "2026-v1",
        "display_name":             "Diabetes Self-Management Program",
        "category":                 "primary",
        "is_time_sensitive":        False,
        "subcategory":              "disease_specific",
        "denominator_logic": {
            "age_min":                  18,
            "age_max":                  120,
            "required_conditions":      ["diabetes_type_1", "diabetes_type_2"],
            "continuous_enrollment_months": 6,
        },
        "inclusion_logic": {
            "a1c_within_days":          180,
            "a1c_min_for_inclusion":    7.5,
        },
        "exclusion_codes":          ["hospice", "palliative_care",
                                      "currently_in_other_disease_program"],
        "supported_languages":      ["en", "es"],
        "supported_geographies":    ["all"],
        "target_active_capacity":   240,
        "target_duration_days":     180,
        "expected_cost_per_patient": 1200,
        "expected_uplift_magnitude": 0.10,
        "primary_outcome":          "a1c_change_at_180_days",
        "theory_of_change":         "Structured diabetes education, medication optimization, and CGM support drive A1c reduction.",
        "effective_start":          "2026-01-01",
        "effective_end":            "2026-12-31",
    },
    {
        "program_id":               "complex-care-management",
        "version":                  "2026-v1",
        "display_name":             "Complex Care Management (multi-condition)",
        "category":                 "primary",
        "is_time_sensitive":        False,
        "subcategory":              "complex_care",
        "denominator_logic": {
            "age_min":                  18,
            "age_max":                  120,
            "required_conditions":      [],
            "continuous_enrollment_months": 6,
        },
        "inclusion_logic": {
            "min_active_conditions":              3,
            "predicted_admission_probability_min": 0.20,
        },
        "exclusion_codes":          ["hospice"],
        "supported_languages":      ["en", "es", "zh"],
        "supported_geographies":    ["all"],
        "target_active_capacity":   200,
        "target_duration_days":     365,    # longitudinal
        "expected_cost_per_patient": 4800,    # ~$400/month indefinite
        "expected_uplift_magnitude": 0.14,
        "primary_outcome":          "12_month_total_cost_of_care_change",
        "theory_of_change":         "Longitudinal multi-disciplinary coordination (nurse, social worker, pharmacist) addresses heterogeneous problems no single-condition program covers.",
        "effective_start":          "2026-01-01",
        "effective_end":            "2026-12-31",
    },
    {
        "program_id":               "polypharmacy-management",
        "version":                  "2026-v1",
        "display_name":             "Polypharmacy / Medication Management",
        "category":                 "add_on",
        "is_time_sensitive":        False,
        "subcategory":              "specialized",
        "denominator_logic": {
            "age_min":                  18,
            "age_max":                  120,
            "required_conditions":      [],
            "continuous_enrollment_months": 3,
        },
        "inclusion_logic": {
            "min_active_medications": 8,
            "min_prescribers_in_180d": 2,
        },
        "exclusion_codes":          ["hospice"],
        "supported_languages":      ["en", "es"],
        "supported_geographies":    ["all"],
        "target_active_capacity":   460,
        "target_duration_days":     84,    # six 2-week sessions
        "expected_cost_per_patient": 600,
        "expected_uplift_magnitude": 0.08,
        "primary_outcome":          "medication_related_adverse_event_rate",
        "theory_of_change":         "Clinical pharmacist review identifies dose-adjustment opportunities, drug-drug interactions, and prescriber-coordination gaps.",
        "effective_start":          "2026-01-01",
        "effective_end":            "2026-12-31",
    },
]

# Equity floors per program. The orchestrator reserves capacity for
# cohorts with documented enrollment-rate disparities. Conservative
# starting values; production tunes against the equity dashboard
# quarterly. The Obermeyer-style failure mode (under-enrollment of
# protected cohorts driven by selection-biased historical training
# data) is what these floors are designed to compensate for.
EQUITY_FLOORS = {
    "transitional-care-management": {
        "language_non_en":              25,
        "sdoh_low_food_security":       15,
    },
    "heart-failure-program": {
        "language_non_en":              35,
        "sdoh_transportation_barrier":  25,
        "engagement_q1":                20,
    },
    "diabetes-management-program": {
        "language_non_en":              30,
        "engagement_q1":                20,
    },
    "complex-care-management": {
        "language_non_en":              30,
        "sdoh_low_food_security":       20,
        "engagement_q1":                25,
    },
    "polypharmacy-management": {
        "language_non_en":              50,
    },
}

# Engagement-scoring profiles per program. Each profile defines
# what "engaged" looks like for that program. Production: a config
# table maintained alongside the program registry; the example
# codes the most common shapes inline.
ENGAGEMENT_PROFILES = {
    "transitional-care-management": {
        "expected_contacts_in_window": 3,    # 2 calls + 1 home visit
        "min_contacts_for_engaged":    2,
        "expected_outcome_signals":    ["follow_up_appointment_scheduled",
                                         "med_reconciliation_complete"],
        "at_risk_threshold":           0.50,
    },
    "heart-failure-program": {
        "expected_contacts_in_window": 4,    # weekly check-ins
        "min_contacts_for_engaged":    3,
        "expected_outcome_signals":    ["weight_submission",
                                         "med_adherence_signal"],
        "at_risk_threshold":           0.55,
    },
    "diabetes-management-program": {
        "expected_contacts_in_window": 6,    # biweekly over 12 weeks
        "min_contacts_for_engaged":    4,
        "expected_outcome_signals":    ["a1c_resubmit",
                                         "education_module_complete"],
        "at_risk_threshold":           0.45,
    },
    "complex-care-management": {
        "expected_contacts_in_window": 3,    # monthly visits/televisits
        "min_contacts_for_engaged":    2,
        "expected_outcome_signals":    ["care_plan_goal_progress"],
        "at_risk_threshold":           0.50,
    },
    "polypharmacy-management": {
        "expected_contacts_in_window": 3,
        "min_contacts_for_engaged":    2,
        "expected_outcome_signals":    ["prescriber_action_taken"],
        "at_risk_threshold":           0.50,
    },
}

# Cross-program-transition mapping. After graduation or escalation,
# which programs are natural next steps. Production: a knowledge
# graph; the example codes the simplest mappings.
CROSS_PROGRAM_TRANSITIONS_MAP = {
    ("transitional-care-management", "graduation"):  ["heart-failure-program",
                                                       "diabetes-management-program",
                                                       "complex-care-management"],
    ("heart-failure-program", "graduation"):         ["polypharmacy-management"],
    ("heart-failure-program", "deterioration"):      ["complex-care-management"],
    ("diabetes-management-program", "graduation"):   ["polypharmacy-management"],
    ("diabetes-management-program", "deterioration"):["complex-care-management"],
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
    """Current UTC date as YYYY-MM-DD string for run_date."""
    return datetime.datetime.now(timezone.utc).date().isoformat()

def _emit_metric(name: str, value: float, dimensions: dict) -> None:
    """
    Emit a CloudWatch custom metric. Swallows errors so a metric-publish
    failure never breaks the recommendation pipeline. CloudWatch metric
    publishing is best-effort observability, not a correctness boundary.
    """
    try:
        cloudwatch_client.put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[{
                "MetricName": name,
                "Dimensions": [
                    {"Name": k, "Value": str(v)[:255]} for k, v in dimensions.items()
                ],
                "Value": float(value),
                "Unit":  "Count",
            }],
        )
    except Exception as exc:
        logger.warning("Metric publish failed for %s: %s", name, exc)

def _to_decimal(value) -> Decimal:
    """
    DynamoDB does not accept Python floats. Going through str avoids
    binary-precision issues. Wrap floats at the persistence boundary
    and forget about it. (This is the SDK gotcha that bites every
    boto3 newcomer; fixed at the boundary, not in business logic.)
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

def _make_briefing_id(patient_id: str, program_id: str, run_date: str) -> str:
    """
    Briefing ID used to join the recommendation, the briefing, and
    the outreach record.

    NOTE: This example uses a readable string for clarity. Production
    must replace this with an opaque, non-reversible identifier (UUID
    or HMAC-SHA256 over the composite with a per-environment secret).
    Plain-text patient_ids and program_ids embedded in IDs (carried
    in care-manager queues, EHR inboxes, and engagement events) are
    PHI leakage. The "Gap to Production" section at the end of this
    file flags the same issue.
    """
    return f"brief-{run_date}-{patient_id}-{program_id}"

def _make_outreach_id() -> str:
    """Opaque outreach identifier."""
    return f"outreach-{uuid.uuid4().hex[:16]}"

def _make_decision_id() -> str:
    """Opaque disenrollment-decision identifier."""
    return f"decision-{uuid.uuid4().hex[:16]}"

def _wait_for_athena_query(execution_id: str, timeout_seconds: int = 300) -> None:
    """Poll Athena until the query reaches a terminal state."""
    start = time.time()
    while True:
        response = athena_client.get_query_execution(QueryExecutionId=execution_id)
        state = response["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return
        if state in ("FAILED", "CANCELLED"):
            reason = response["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {execution_id} {state}: {reason}")
        if time.time() - start > timeout_seconds:
            raise TimeoutError(f"Athena query {execution_id} timed out")
        time.sleep(2)

def _wait_for_transform_job(job_name: str, timeout_seconds: int = 3600) -> None:
    """Poll a Batch Transform job until it reaches a terminal state."""
    start = time.time()
    while True:
        response = sagemaker_client.describe_transform_job(TransformJobName=job_name)
        status = response["TransformJobStatus"]
        if status == "Completed":
            return
        if status in ("Failed", "Stopped"):
            reason = response.get("FailureReason", "")
            raise RuntimeError(f"Transform job {job_name} {status}: {reason}")
        if time.time() - start > timeout_seconds:
            raise TimeoutError(f"Transform job {job_name} timed out")
        time.sleep(15)

def _redact_identifiers(items: list) -> list:
    """
    Strip patient/provider identifiers from a list of records before
    sending to an LLM. The LLM doesn't need them, and stripping at the
    boundary limits any vendor-side logging exposure (Bedrock service
    terms commit to not training on prompts, but defense-in-depth
    still applies).
    """
    redacted = []
    for item in items:
        copy = dict(item)
        for field in ("patient_id", "provider_id", "tracking_id",
                      "outreach_id", "decision_id"):
            copy.pop(field, None)
        redacted.append(copy)
    return redacted

def _cohort_features_from_profile(patient: dict) -> dict:
    """Pull cohort features from the patient profile."""
    return {
        "engagement_history_quartile": patient.get(
            "engagement_history_quartile", "q3"),
        "language":                    patient.get("preferred_language", "en"),
        "sdoh_cohort":                 patient.get("sdoh_cohort"),
        "age_band":                    patient.get("age_band"),
    }

def _applicable_floor_cohorts(cohort_features: dict,
                                floor_definitions: dict) -> list:
    """Return the floor names the candidate qualifies for."""
    result = []
    for floor_name in floor_definitions:
        if (floor_name == "engagement_q1"
            and cohort_features.get("engagement_history_quartile") == "q1"):
            result.append(floor_name)
        elif (floor_name == "language_non_en"
              and cohort_features.get("language") not in (None, "en")):
            result.append(floor_name)
        elif (floor_name == "sdoh_low_food_security"
              and cohort_features.get("sdoh_cohort") == "low_food_security"):
            result.append(floor_name)
        elif (floor_name == "sdoh_transportation_barrier"
              and cohort_features.get("sdoh_cohort") == "transportation_barrier"):
            result.append(floor_name)
    return result
```

---

## Step 1: Evaluate the Program Registry to Produce Per-(Patient, Program) Eligibility Records

*The pseudocode calls this `evaluate_program_eligibility(patients, run_date)`. For each active program in the registry, evaluate denominator, inclusion, and exclusion predicates against the patient feature snapshot. Maintain a per-(patient, program) state machine. Skip the registry abstraction and you end up hard-coding program logic, which becomes a maintenance disaster when programs are added, retired, or have their capacity adjusted quarterly.*

```python
def evaluate_program_eligibility(patients: list, run_date: str) -> list:
    """
    Run the daily eligibility-evaluation pipeline.

    Returns a list of state transitions for downstream stages
    (enrichment, allocation) to consume. Persists per-(patient,
    program) state to the patient-program-state table.
    """
    active_programs = _load_active_programs(run_date)
    logger.info(
        "Evaluating %d active programs against %d patients for run_date=%s",
        len(active_programs), len(patients), run_date,
    )

    transitions = []
    state_table = dynamodb.Table(PATIENT_PROGRAM_STATE_TABLE)

    for program in active_programs:
        # Step 1A: denominator. Production: an Athena query template
        # parameterized over the registry's denominator predicates
        # joined with the eligibility/enrollment view. The example uses
        # an in-memory filter so the demo runs offline.
        denominator = _evaluate_denominator(patients, program, run_date)

        # Step 1B: inclusion criteria. Some programs add inclusion
        # logic on top of the denominator (HF program requires not
        # just an HF diagnosis but also a recent HF-related encounter).
        inclusion_passing = _evaluate_inclusion(
            denominator, patients, program, run_date,
        )

        # Step 1C: exclusion criteria. Hospice, palliative care,
        # active oncology treatment, current enrollment in a competing
        # program, language not supported by the program's staffing.
        excluded = _evaluate_exclusions(
            denominator, patients, program, run_date,
        )

        # Step 1D: per-patient eligibility determination.
        for patient_id in inclusion_passing:
            if patient_id in excluded:
                eligibility = "excluded"
                exclusion_reason = _lookup_exclusion_reason(
                    patient_id, program, excluded,
                )
            else:
                eligibility = "eligible"
                exclusion_reason = None

            previous_record = _read_previous_state(
                state_table, patient_id, program["program_id"],
            )

            transition_event = _compute_eligibility_transition(
                previous_record, eligibility,
            )

            data_quality_flag = _assess_source_completeness(
                patient_id, program,
            )

            # Don't overwrite the state machine for already-enrolled
            # patients; their state has progressed past eligibility.
            # Only set state when we're starting from ineligible,
            # eligible, or fresh.
            previous_state = previous_record.get("state")
            if previous_state in (None, "ineligible", "eligible", "excluded",
                                   "re_eligible"):
                derived_state = (
                    eligibility if eligibility in ("eligible", "excluded")
                    else "ineligible"
                )
            else:
                derived_state = previous_state

            new_history_entry = {
                "event":     transition_event,
                "timestamp": run_date,
                "source":    "eligibility_evaluation",
            }
            state_history = (previous_record.get("state_history", [])
                             + [new_history_entry])

            record = {
                "patient_id":           patient_id,
                "program_id":           program["program_id"],
                "program_version":      program["version"],
                "eligibility":          eligibility,
                "exclusion_reason":     exclusion_reason,
                "state":                derived_state,
                "state_history":        state_history,
                "last_evaluation_date": run_date,
                "data_quality_flag":    data_quality_flag,
            }

            try:
                state_table.put_item(Item=_to_decimal_dict(record))
            except Exception as exc:
                logger.warning(
                    "Failed to persist program state for %s/%s: %s",
                    patient_id, program["program_id"], exc,
                )

            transitions.append({
                "patient_id":     patient_id,
                "program_id":     program["program_id"],
                "previous_state": previous_state,
                "new_state":      derived_state,
                "transition":     transition_event,
            })

        # Time-sensitive eligibility changes (transitional care after
        # discharge) emit a separate event so the downstream
        # orchestrator can run an off-cycle evaluation rather than
        # waiting for the weekly enrollment-decision cycle.
        if program.get("is_time_sensitive"):
            for newly_eligible_patient in _newly_eligible(
                inclusion_passing, excluded, program, run_date, state_table,
            ):
                try:
                    kinesis_client.put_record(
                        StreamName=CM_ENGAGEMENT_STREAM_NAME,
                        PartitionKey=newly_eligible_patient,
                        Data=json.dumps({
                            "event_type":     "eligibility_acquired",
                            "patient_id":     newly_eligible_patient,
                            "program_id":     program["program_id"],
                            "run_date":       run_date,
                            "time_sensitive": True,
                            "timestamp":      _now_iso(),
                        }, default=str).encode("utf-8"),
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to publish eligibility-acquired event for %s: %s",
                        newly_eligible_patient, exc,
                    )

    logger.info(
        "Eligibility evaluation produced %d (patient, program) state records",
        len(transitions),
    )
    return transitions

def _load_active_programs(run_date: str) -> list:
    """
    Load every active program version from the registry. The registry
    is the source of truth; engineering doesn't hard-code program
    logic. New programs land as new registry versions; capacity
    changes land as new versions; program retirements land as
    effective_end updates.
    """
    registry_table = dynamodb.Table(PROGRAM_REGISTRY_TABLE)
    try:
        response = registry_table.scan()
        active = []
        for item in response.get("Items", []):
            item = _from_decimal(item)
            if item["effective_start"] <= run_date <= item["effective_end"]:
                active.append(item)
        if active:
            return active
    except Exception:
        pass
    # Offline demo path: fall back to the synthetic registry.
    return [p for p in SAMPLE_PROGRAM_REGISTRY
            if p["effective_start"] <= run_date <= p["effective_end"]]

def _evaluate_denominator(patients: list, program: dict, run_date: str) -> list:
    """
    Determine which patients are in this program's denominator as of
    run_date. Production: SQL against a normalized claims+EHR+
    discharge view. The example uses an in-memory filter.
    """
    logic = program["denominator_logic"]
    eligible = []
    for patient in patients:
        # Age check.
        age = patient.get("age", 0)
        if age < logic["age_min"] or age > logic["age_max"]:
            continue

        # Required-condition check (disease-specific programs).
        required = set(logic.get("required_conditions", []))
        patient_conditions = set(patient.get("active_conditions", []))
        if required and not (required & patient_conditions):
            continue

        # Discharge-window check (transitional care).
        discharge_within_days = logic.get("discharge_within_days")
        if discharge_within_days is not None:
            last_discharge = patient.get("last_discharge_date")
            if not last_discharge:
                continue
            try:
                last = datetime.date.fromisoformat(last_discharge)
                run = datetime.date.fromisoformat(run_date)
                if (run - last).days > discharge_within_days:
                    continue
            except Exception:
                continue

        # Continuous-enrollment check.
        if (logic.get("continuous_enrollment_months", 0) > 0
            and not patient.get("continuously_enrolled", True)):
            continue

        eligible.append(patient["patient_id"])
    return eligible

def _evaluate_inclusion(denominator: list, patients: list,
                          program: dict, run_date: str) -> list:
    """
    Apply program-specific inclusion logic on top of the denominator.
    HF program requires a recent HF-related encounter; DM program
    requires recent A1c >= 7.5; complex-care requires multi-condition
    complexity and a minimum admission risk.
    """
    inclusion = program.get("inclusion_logic", {})
    if not inclusion:
        return list(denominator)

    patient_lookup = {p["patient_id"]: p for p in patients}
    passing = []

    for patient_id in denominator:
        patient = patient_lookup.get(patient_id, {})

        # HF-related encounter window.
        hf_window = inclusion.get("hf_related_encounter_within_days")
        if hf_window is not None:
            last_hf_encounter = patient.get("last_hf_encounter_date")
            if not last_hf_encounter:
                continue
            try:
                last = datetime.date.fromisoformat(last_hf_encounter)
                run = datetime.date.fromisoformat(run_date)
                if (run - last).days > hf_window:
                    continue
            except Exception:
                continue

        # A1c-based inclusion (DM program).
        a1c_window = inclusion.get("a1c_within_days")
        if a1c_window is not None:
            a1c_recent = patient.get("recent_lab_trends", {}).get("a1c_recent")
            a1c_min = inclusion.get("a1c_min_for_inclusion", 0.0)
            if a1c_recent is None or a1c_recent < a1c_min:
                continue

        # Inpatient-admission window (transitional care).
        admission_window = inclusion.get("inpatient_admission_within_days")
        if admission_window is not None:
            last_admission = patient.get("last_admission_date")
            if not last_admission:
                continue
            try:
                last = datetime.date.fromisoformat(last_admission)
                run = datetime.date.fromisoformat(run_date)
                if (run - last).days > admission_window:
                    continue
            except Exception:
                continue
            # Discharge-disposition exclusion check.
            disposition = patient.get("last_discharge_disposition")
            excludes = inclusion.get("discharge_disposition_excludes", [])
            if disposition in excludes:
                continue

        # Multi-condition / risk inclusion (complex-care).
        min_conditions = inclusion.get("min_active_conditions")
        if min_conditions is not None:
            condition_count = len(patient.get("active_conditions", []))
            if condition_count < min_conditions:
                continue
        min_admit_prob = inclusion.get("predicted_admission_probability_min")
        if min_admit_prob is not None:
            admit_prob = patient.get("predicted_admission_probability_12mo", 0.0)
            if admit_prob < min_admit_prob:
                continue

        # Polypharmacy: medication count and prescriber count.
        min_meds = inclusion.get("min_active_medications")
        if min_meds is not None:
            med_count = len(patient.get("current_medications", []))
            if med_count < min_meds:
                continue
        min_prescribers = inclusion.get("min_prescribers_in_180d")
        if min_prescribers is not None:
            prescriber_count = patient.get("distinct_prescribers_180d", 0)
            if prescriber_count < min_prescribers:
                continue

        passing.append(patient_id)

    return passing

def _evaluate_exclusions(denominator: list, patients: list,
                          program: dict, run_date: str) -> set:
    """
    Apply program-specific exclusion logic. Categorical exclusions
    (hospice, palliative_care) plus the language-support gate.
    """
    excluded_codes = set(program.get("exclusion_codes", []))
    supported_languages = set(program.get("supported_languages", ["en"]))
    patient_lookup = {p["patient_id"]: p for p in patients}
    excluded = set()

    for patient_id in denominator:
        patient = patient_lookup.get(patient_id, {})
        patient_exclusions = set(patient.get("exclusion_flags", []))
        if patient_exclusions & excluded_codes:
            excluded.add(patient_id)
            continue

        # Language support: if the patient's preferred language is
        # not supported by this program's staffing, exclude. The
        # equity floor still reserves capacity within the
        # supported-language cohort; this is about staffing reality,
        # not preference.
        preferred = patient.get("preferred_language", "en")
        if preferred not in supported_languages:
            excluded.add(patient_id)
            continue

    return excluded

def _lookup_exclusion_reason(patient_id: str, program: dict,
                               excluded: set) -> str:
    """
    For a patient in the excluded set, return a human-readable
    exclusion reason. The example uses a coarse heuristic; production
    captures the specific exclusion code or rule that triggered.
    """
    return "exclusion_criteria_met"

def _read_previous_state(state_table, patient_id: str,
                           program_id: str) -> dict:
    """Read the previous state record for this (patient, program)."""
    try:
        response = state_table.get_item(
            Key={"patient_id": patient_id, "program_id": program_id}
        )
        return _from_decimal(response.get("Item") or {})
    except Exception:
        return {}

def _compute_eligibility_transition(previous: dict, new_eligibility: str) -> str:
    """Determine the state-history event label for an eligibility change."""
    prev_eligibility = previous.get("eligibility")
    if prev_eligibility is None:
        return f"initial_{new_eligibility}"
    if prev_eligibility == new_eligibility:
        return "unchanged"
    return f"transitioned_{prev_eligibility}_to_{new_eligibility}"

def _newly_eligible(inclusion_passing: list, excluded: set,
                      program: dict, run_date: str, state_table) -> list:
    """
    Return patients who are newly eligible for this program at this
    run_date. Time-sensitive programs use this to fire events outside
    the weekly cycle.
    """
    newly = []
    for patient_id in inclusion_passing:
        if patient_id in excluded:
            continue
        previous = _read_previous_state(
            state_table, patient_id, program["program_id"],
        )
        if previous.get("eligibility") != "eligible":
            newly.append(patient_id)
    return newly

def _assess_source_completeness(patient_id: str, program: dict) -> str:
    """
    Tag the (patient, program) record with a data-quality flag that
    downstream consumers can gate on. A confidently "eligible" record
    on a patient with `cross_provider_fragmentation` data quality is
    less reliable than the same label on a patient with `complete`
    data quality.

    Mirrors the pattern from 4.5 and 4.6.
    """
    fragmentation = _DEMO_FRAGMENTATION_FLAGS.get(patient_id, False)
    if fragmentation:
        return "cross_provider_fragmentation"
    history_count = _DEMO_HISTORY_COUNT.get(patient_id, 100)
    if history_count < 10:
        return "sparse_history"
    return "complete"

# Demo state populated by the runner at the bottom of this file.
_DEMO_FRAGMENTATION_FLAGS: dict = {}
_DEMO_HISTORY_COUNT: dict = {}
```

---

## Step 2: Score Per-Program Response (Uplift), Enrollment Likelihood, and Synthesize Priority

*The pseudocode calls this `enrich_eligible_candidates(eligibility_records, run_date)`. Per-(patient, program), produce a response (uplift) score with confidence intervals, an enrollment-likelihood score, an engagement-prediction score, a program-fit score, and a synthesized priority. Skip per-program modeling and you treat all programs as interchangeable, which is the trap of "highest risk first" enrollment that ignores program semantics.*

```python
def enrich_eligible_candidates(run_date: str, patients: dict,
                                program_lookup: dict) -> list:
    """
    Read eligible candidates from patient-program-state, score
    response/likelihood/engagement/fit per (patient, program),
    synthesize priority, persist enriched record.

    patients:        dict[patient_id] -> patient profile
    program_lookup:  dict[program_id] -> program registry entry

    Returns the enriched candidate list for downstream stages
    (enrollment-decision allocation) to consume.
    """
    state_table = dynamodb.Table(PATIENT_PROGRAM_STATE_TABLE)
    candidates = _scan_eligible_candidates(state_table)
    logger.info(
        "Enriching %d eligible candidates for run_date=%s",
        len(candidates), run_date,
    )

    enriched = []
    for candidate in candidates:
        patient_id = candidate["patient_id"]
        program_id = candidate["program_id"]
        program = program_lookup.get(program_id)
        patient = patients.get(patient_id, {})

        if program is None:
            logger.warning(
                "Candidate references unknown program_id=%s; skipping",
                program_id,
            )
            continue

        # ---- Stage A: per-program uplift (response) scoring ----
        # Production: SageMaker Batch Transform call to the per-program
        # uplift model. Output is the conditional treatment effect
        # (CATE): expected change in the program's primary outcome
        # if the patient is enrolled, vs not enrolled, with a
        # confidence interval. Trained against propensity-matched
        # historical enrollment data.
        # The example uses a rule-based proxy.
        uplift = _score_uplift(patient, program)

        # ---- Stage B: enrollment-likelihood scoring ----
        # Production: per-program model predicting probability of
        # accepting enrollment given outreach. Inputs include barrier
        # flags (transportation, language, cost-sensitivity), prior
        # enrollment-attempt history, and recent engagement
        # responsiveness.
        likelihood = _score_enrollment_likelihood(patient, program)

        # ---- Stage C: engagement-prediction (post-enrollment) ----
        # Probability the patient remains engaged through program
        # completion if enrolled.
        engagement = _score_engagement_prediction(patient, program)

        # ---- Stage D: program-fit score ----
        # Theory-of-change alignment; hard-coded plus learned
        # components. The example codes the hard-coded part inline;
        # a learned residual model would feed in via a fifth Batch
        # Transform call.
        fit_score = _compute_program_fit(patient, program, run_date)

        # ---- Stage E: priority synthesis ----
        priority_components = {
            "uplift_contrib":            POLICY_WEIGHTS["uplift"]
                                          * uplift["point_estimate"],
            "uplift_uncertainty":        uplift["ci_high"] - uplift["ci_low"],
            "likelihood_contrib":        POLICY_WEIGHTS["enrollment_likelihood"]
                                          * likelihood,
            "fit_contrib":               POLICY_WEIGHTS["program_fit"]
                                          * fit_score,
            "engagement_contrib":        POLICY_WEIGHTS["post_enrollment_engagement"]
                                          * engagement,
        }
        priority = round(
            priority_components["uplift_contrib"]
            + priority_components["likelihood_contrib"]
            + priority_components["fit_contrib"]
            + priority_components["engagement_contrib"],
            4,
        )
        priority_components = {
            k: round(v, 4) for k, v in priority_components.items()
        }

        cohort_features = _cohort_features_from_profile(patient)

        enriched_record = {
            **candidate,
            "uplift_score":         {
                "point_estimate": round(uplift["point_estimate"], 4),
                "ci_low":         round(uplift["ci_low"], 4),
                "ci_high":        round(uplift["ci_high"], 4),
                "outcome":        program["primary_outcome"],
            },
            "enrollment_likelihood": round(likelihood, 4),
            "engagement_prediction": round(engagement, 4),
            "fit_score":             round(fit_score, 4),
            "priority":              priority,
            "priority_components":   priority_components,
            "cohort_features":       cohort_features,
            "policy_version":        POLICY_VERSION,
            "last_enrichment_date":  run_date,
        }

        try:
            state_table.update_item(
                Key={"patient_id": patient_id, "program_id": program_id},
                UpdateExpression=(
                    "SET uplift_score = :u, enrollment_likelihood = :el, "
                    "engagement_prediction = :ep, fit_score = :fs, "
                    "priority = :p, priority_components = :pc, "
                    "cohort_features = :cf, policy_version = :pv, "
                    "last_enrichment_date = :led"
                ),
                ExpressionAttributeValues=_to_decimal_dict({
                    ":u":   enriched_record["uplift_score"],
                    ":el":  enriched_record["enrollment_likelihood"],
                    ":ep":  enriched_record["engagement_prediction"],
                    ":fs":  enriched_record["fit_score"],
                    ":p":   priority,
                    ":pc":  priority_components,
                    ":cf":  cohort_features,
                    ":pv":  POLICY_VERSION,
                    ":led": run_date,
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to update enriched candidate for %s/%s: %s",
                patient_id, program_id, exc,
            )

        enriched.append(enriched_record)

    logger.info(
        "Enrichment computed priority for %d candidates", len(enriched),
    )
    return enriched

def _scan_eligible_candidates(state_table) -> list:
    """
    Production: Query a (state, last_evaluation_date) GSI rather than
    a scan; this example uses a simple scan for the demo.
    """
    candidates = []
    try:
        response = state_table.scan()
        for item in response.get("Items", []):
            item = _from_decimal(item)
            if item.get("eligibility") == "eligible" and item.get(
                "state") in ("eligible", "re_eligible"):
                candidates.append(item)
    except Exception as exc:
        logger.warning("Scan of patient-program-state failed: %s", exc)
    return candidates

def _score_uplift(patient: dict, program: dict) -> dict:
    """
    Rule-based uplift (CATE) scoring. Production replaces with a
    per-program SageMaker Batch Transform call, ideally trained with
    causal-inference tooling (EconML, DoWhy) on propensity-matched
    historical enrollment data, augmented with randomized-enrollment
    data when available.

    Output is the expected change in the program's primary outcome
    over the program's evaluation horizon (lower readmission rate,
    A1c reduction, total-cost-of-care reduction), with a confidence
    interval.

    The rules below illustrate a few mechanics:
      - Recent destabilization (admission, A1c spike) raises the
        uplift estimate for programs whose theory of change addresses
        the destabilization.
      - Patients whose trajectory is shaped by progressive disease
        with limited program leverage have lower uplift even at high
        risk.
      - Patient engagement history is only weakly correlated with
        uplift; high-engagement patients are slightly more likely
        to benefit, but the dominant signal is clinical.
    """
    program_id = program["program_id"]
    base = float(program.get("expected_uplift_magnitude", 0.10))
    point = base
    lab_trends = patient.get("recent_lab_trends", {})
    last_admission = patient.get("last_admission_date")

    # Recent admission boosts uplift for HF, transitional, and
    # complex-care programs.
    if last_admission and program_id in {
        "heart-failure-program",
        "transitional-care-management",
        "complex-care-management",
    }:
        try:
            last = datetime.date.fromisoformat(last_admission)
            today = datetime.date.fromisoformat(_today_str())
            days_since = (today - last).days
            if days_since <= 30:
                point = min(0.30, point + 0.06)
            elif days_since <= 90:
                point = min(0.30, point + 0.03)
        except Exception:
            pass

    # Diabetes program: bigger uplift for elevated A1c.
    if program_id == "diabetes-management-program":
        a1c = lab_trends.get("a1c_recent")
        if a1c and a1c >= 9.0:
            point = min(0.25, point + 0.05)
        elif a1c and a1c >= 8.0:
            point = min(0.25, point + 0.02)

    # Polypharmacy program: bigger uplift for higher med counts and
    # multiple prescribers.
    if program_id == "polypharmacy-management":
        med_count = len(patient.get("current_medications", []))
        if med_count >= 12:
            point = min(0.20, point + 0.04)
        prescribers = patient.get("distinct_prescribers_180d", 0)
        if prescribers >= 4:
            point = min(0.20, point + 0.02)

    # Engagement-history modifier (modest).
    quartile = patient.get("engagement_history_quartile", "q3")
    quartile_adj = {"q1": -0.01, "q2": 0.0, "q3": 0.01, "q4": 0.02}.get(
        quartile, 0.0,
    )
    point = max(0.0, min(0.40, point + quartile_adj))

    # Confidence interval. Wider intervals for programs with delayed
    # outcomes (DM A1c readout in 6 months) and patients with sparse
    # history. A more rigorous model would use bootstrapped or
    # quantile-regression CIs; this example uses a fixed-shape proxy.
    history_count = _DEMO_HISTORY_COUNT.get(patient.get("patient_id", ""), 100)
    if history_count < 10:
        ci_half_width = 0.12
    elif program_id == "diabetes-management-program":
        ci_half_width = 0.08    # delayed-outcome program: wider CI
    else:
        ci_half_width = 0.05

    return {
        "point_estimate": point,
        "ci_low":         max(0.0, point - ci_half_width),
        "ci_high":        min(0.50, point + ci_half_width),
    }

def _score_enrollment_likelihood(patient: dict, program: dict) -> float:
    """
    Rule-based enrollment-likelihood scoring. Production: per-program
    SageMaker Batch Transform.

    Returns probability the patient consents and enrolls given
    outreach. Modifiers reflect barrier flags, prior outreach
    history, and program-specific friction (a 12-week curriculum is
    higher-friction than a single check-in).
    """
    base = {
        "transitional-care-management": 0.65,
        "heart-failure-program":        0.50,
        "diabetes-management-program":  0.45,
        "complex-care-management":      0.40,
        "polypharmacy-management":      0.55,
    }.get(program["program_id"], 0.45)

    quartile = patient.get("engagement_history_quartile", "q3")
    quartile_adj = {"q1": -0.20, "q2": -0.08, "q3": 0.0, "q4": 0.10}.get(
        quartile, 0.0,
    )

    # SDOH modifiers. Transportation barrier hurts most for programs
    # that involve in-person visits; language-mismatch hurts when
    # program staffing for that language is thin.
    sdoh = patient.get("sdoh_cohort")
    sdoh_adj = 0.0
    if sdoh == "transportation_barrier":
        sdoh_adj -= 0.10
    elif sdoh == "low_food_security":
        sdoh_adj -= 0.05

    # Prior-decline penalty: a patient who declined the same program
    # within the last year is unlikely to consent now.
    if program["program_id"] in patient.get("prior_program_declines", []):
        sdoh_adj -= 0.20

    return max(0.05, min(0.95, base + quartile_adj + sdoh_adj))

def _score_engagement_prediction(patient: dict, program: dict) -> float:
    """
    Rule-based engagement-prediction scoring. Production: per-program
    SageMaker Batch Transform.

    Returns probability the patient remains engaged through program
    completion if enrolled.
    """
    base = {
        "transitional-care-management": 0.75,
        "heart-failure-program":        0.65,
        "diabetes-management-program":  0.55,
        "complex-care-management":      0.60,
        "polypharmacy-management":      0.65,
    }.get(program["program_id"], 0.55)

    quartile = patient.get("engagement_history_quartile", "q3")
    quartile_adj = {"q1": -0.15, "q2": -0.05, "q3": 0.0, "q4": 0.08}.get(
        quartile, 0.0,
    )
    return max(0.05, min(0.95, base + quartile_adj))

def _compute_program_fit(patient: dict, program: dict, run_date: str) -> float:
    """
    Hard-coded theory-of-change alignment. The example codes the
    most common cases inline. Production combines this with a
    learned residual model.

    Output range [0, 1]: 1.0 = strong fit; 0.0 = poor fit.
    """
    program_id = program["program_id"]
    conditions = set(patient.get("active_conditions", []))

    if program_id == "transitional-care-management":
        # Fit decays with days since discharge.
        last_discharge = patient.get("last_discharge_date")
        if not last_discharge:
            return 0.0
        try:
            last = datetime.date.fromisoformat(last_discharge)
            run = datetime.date.fromisoformat(run_date)
            days = (run - last).days
        except Exception:
            return 0.0
        if days <= 7:
            return 1.0
        if days <= 14:
            return 0.7
        if days <= 21:
            return 0.4
        return 0.1

    if program_id == "heart-failure-program":
        # Strong fit when HF is the primary actionable problem.
        # Weakens when many other major problems coexist (consider
        # complex-care instead).
        if "heart_failure" not in conditions:
            return 0.0
        major_others = conditions - {"heart_failure", "hypertension",
                                       "hyperlipidemia"}
        if len(major_others) <= 1:
            return 0.95
        if len(major_others) <= 3:
            return 0.70
        return 0.40

    if program_id == "diabetes-management-program":
        if not (conditions & {"diabetes_type_1", "diabetes_type_2"}):
            return 0.0
        major_others = conditions - {"diabetes_type_1", "diabetes_type_2",
                                       "hypertension", "hyperlipidemia"}
        if len(major_others) <= 1:
            return 0.90
        if len(major_others) <= 3:
            return 0.65
        return 0.40

    if program_id == "complex-care-management":
        # Strong fit when the patient has multi-system complexity.
        condition_count = len(conditions)
        if condition_count >= 5:
            return 0.95
        if condition_count >= 4:
            return 0.80
        if condition_count >= 3:
            return 0.60
        return 0.30

    if program_id == "polypharmacy-management":
        med_count = len(patient.get("current_medications", []))
        prescribers = patient.get("distinct_prescribers_180d", 0)
        if med_count >= 12 and prescribers >= 4:
            return 0.95
        if med_count >= 10:
            return 0.80
        if med_count >= 8:
            return 0.65
        return 0.30

    return 0.50
```

---

## Step 3: Multi-Stage Enrollment Allocation With Capacity, Equity, and Operational Constraints

*The pseudocode calls this `allocate_enrollments(enriched_candidates, run_date, policy)`. The orchestrator runs in stages so program semantics are respected: time-sensitive transitional-care first, disease-specific high-fit second, complex-care third for residual high-uplift complex patients, parallel add-ons fourth. Within each stage, allocation is greedy-by-priority subject to capacity, per-cohort equity floors, per-patient single-active-primary constraint, and operational feasibility. Skip the multi-stage structure and you produce allocations that ignore the most important property of care management: that programs are designed for specific theories of change.*

```python
def allocate_enrollments(enriched_candidates: list, run_date: str,
                          program_lookup: dict) -> list:
    """
    Multi-stage capacity-and-equity-constrained allocation.

    Stage 1: time-sensitive (transitional-care).
    Stage 2: disease-specific high-fit.
    Stage 3: complex-care for residual.
    Stage 4: add-on parallel programs (polypharmacy).

    Persists recommendations to recommendation-log; transitions
    state machine to recommended; emits program_recommended events.
    """
    # Per-program capacity counters from registry-stated capacity
    # minus current active enrollments.
    capacity_remaining = {}
    equity_remaining = {}
    for program_id, program in program_lookup.items():
        active = _count_active_enrollments(program_id)
        capacity_remaining[program_id] = max(
            0, program["target_active_capacity"] - active,
        )
        equity_remaining[program_id] = dict(EQUITY_FLOORS.get(program_id, {}))

    # Per-patient counters for the single-active-primary and add-on
    # constraints. A patient is not in two competing primary programs
    # simultaneously; parallel add-ons can stack on top of a primary
    # up to MAX_ADD_ONS_PER_PATIENT.
    patient_primary_assigned: dict = {}
    patient_add_on_count: dict = {}

    # Pre-load the set of patients with active primary enrollments so
    # the orchestrator doesn't re-allocate them.
    state_table = dynamodb.Table(PATIENT_PROGRAM_STATE_TABLE)
    for record in _scan_active_primary_enrollments(state_table, program_lookup):
        patient_primary_assigned[record["patient_id"]] = record["program_id"]

    allocated = []

    # Stage 1: time-sensitive programs.
    time_sensitive_program_ids = {
        pid for pid, p in program_lookup.items() if p.get("is_time_sensitive")
    }
    stage1_candidates = [c for c in enriched_candidates
                          if c["program_id"] in time_sensitive_program_ids]
    stage1_sorted = sorted(stage1_candidates,
                            key=lambda x: x["priority"], reverse=True)
    allocated += _allocate_stage(
        stage1_sorted, "time_sensitive", capacity_remaining, equity_remaining,
        patient_primary_assigned, patient_add_on_count, program_lookup,
    )

    # Stage 2: disease-specific programs with high theory-of-change fit.
    disease_program_ids = {
        pid for pid, p in program_lookup.items()
        if p.get("subcategory") == "disease_specific"
        and not p.get("is_time_sensitive")
    }
    stage2_candidates = [
        c for c in enriched_candidates
        if c["program_id"] in disease_program_ids
        and c["fit_score"] >= DISEASE_FIT_THRESHOLD
        and c["patient_id"] not in patient_primary_assigned
    ]
    stage2_sorted = sorted(stage2_candidates,
                            key=lambda x: x["priority"], reverse=True)
    allocated += _allocate_stage(
        stage2_sorted, "disease_specific", capacity_remaining,
        equity_remaining, patient_primary_assigned, patient_add_on_count,
        program_lookup,
    )

    # Stage 3: complex-care for residual high-uplift patients.
    complex_program_ids = {
        pid for pid, p in program_lookup.items()
        if p.get("subcategory") == "complex_care"
    }
    stage3_candidates = [
        c for c in enriched_candidates
        if c["program_id"] in complex_program_ids
        and c["patient_id"] not in patient_primary_assigned
    ]
    stage3_sorted = sorted(stage3_candidates,
                            key=lambda x: x["priority"], reverse=True)
    allocated += _allocate_stage(
        stage3_sorted, "complex_care", capacity_remaining, equity_remaining,
        patient_primary_assigned, patient_add_on_count, program_lookup,
    )

    # Stage 4: parallel add-ons.
    add_on_program_ids = {
        pid for pid, p in program_lookup.items()
        if p.get("category") == "add_on"
    }
    stage4_candidates = [c for c in enriched_candidates
                          if c["program_id"] in add_on_program_ids]
    stage4_sorted = sorted(stage4_candidates,
                            key=lambda x: x["priority"], reverse=True)
    allocated += _allocate_stage(
        stage4_sorted, "add_on", capacity_remaining, equity_remaining,
        patient_primary_assigned, patient_add_on_count, program_lookup,
    )

    # Persist recommendations and transition state machine.
    rec_table = dynamodb.Table(RECOMMENDATION_LOG_TABLE)
    for row in allocated:
        try:
            rec_table.put_item(Item=_to_decimal_dict({
                **row,
                "created_at": _now_iso(),
            }))
        except Exception as exc:
            logger.warning(
                "Failed to persist recommendation for %s/%s: %s",
                row["patient_id"], row["program_id"], exc,
            )

        try:
            state_table.update_item(
                Key={"patient_id": row["patient_id"],
                      "program_id": row["program_id"]},
                UpdateExpression=(
                    "SET #s = :recommended, recommended_run_date = :rd, "
                    "allocation_reason = :ar, allocation_stage = :stg, "
                    "policy_version = :pv, "
                    "state_history = list_append("
                    "if_not_exists(state_history, :empty), :history_event)"
                ),
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues=_to_decimal_dict({
                    ":recommended": "recommended",
                    ":rd":          run_date,
                    ":ar":          row["allocation_reason"],
                    ":stg":         row["stage_name"],
                    ":pv":          POLICY_VERSION,
                    ":empty":       [],
                    ":history_event": [{
                        "event":             "transitioned_eligible_to_recommended",
                        "timestamp":         run_date,
                        "stage":             row["stage_name"],
                        "allocation_reason": row["allocation_reason"],
                    }],
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to update state for %s/%s: %s",
                row["patient_id"], row["program_id"], exc,
            )

        try:
            kinesis_client.put_record(
                StreamName=CM_ENGAGEMENT_STREAM_NAME,
                PartitionKey=row["patient_id"],
                Data=json.dumps({
                    "event_type":          "program_recommended",
                    "patient_id":          row["patient_id"],
                    "program_id":          row["program_id"],
                    "stage":               row["stage_name"],
                    "priority":            row["priority"],
                    "priority_components": row["priority_components"],
                    "allocation_reason":   row["allocation_reason"],
                    "cohort_features":     row["cohort_features"],
                    "policy_version":      POLICY_VERSION,
                    "run_date":            run_date,
                    "timestamp":           _now_iso(),
                }, default=str).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to publish program_recommended event for %s/%s: %s",
                row["patient_id"], row["program_id"], exc,
            )

        # Cohort-sliced metric for the equity dashboard.
        cohort = row.get("cohort_features", {})
        _emit_metric(
            "program_recommended",
            value=1,
            dimensions={
                "program_id":   row["program_id"],
                "stage":        row["stage_name"],
                "engagement_q": str(cohort.get("engagement_history_quartile",
                                                  "unknown")),
                "language":     str(cohort.get("language", "unknown")),
                "sdoh_cohort":  str(cohort.get("sdoh_cohort", "unknown")),
            },
        )

    logger.info("Allocated %d enrollments across stages", len(allocated))
    return allocated

def _allocate_stage(candidates_sorted: list, stage_name: str,
                     capacity_remaining: dict, equity_remaining: dict,
                     patient_primary_assigned: dict,
                     patient_add_on_count: dict,
                     program_lookup: dict) -> list:
    """
    Greedy-by-priority allocation within a stage, respecting capacity,
    per-patient single-primary, add-on caps, equity floors, and
    operational feasibility.
    """
    stage_allocated = []

    for candidate in candidates_sorted:
        program_id = candidate["program_id"]
        patient_id = candidate["patient_id"]
        program = program_lookup[program_id]

        # Capacity check.
        if capacity_remaining.get(program_id, 0) <= 0:
            continue

        # Per-patient primary-program constraint.
        if (program["category"] != "add_on"
            and patient_id in patient_primary_assigned):
            continue

        # Per-patient add-on cap.
        if program["category"] == "add_on":
            if patient_add_on_count.get(patient_id, 0) >= MAX_ADD_ONS_PER_PATIENT:
                continue

        # Operational feasibility: language and geography are already
        # filtered at exclusion; here we keep a placeholder for future
        # checks (e.g., per-region staffing capacity by month).
        if not _operational_feasible(candidate, program):
            continue

        # Equity floor: if the candidate qualifies for a floor cohort
        # and reserved capacity is available, prefer using floor capacity.
        cohort_features = candidate.get("cohort_features", {})
        applicable_floors = _applicable_floor_cohorts(
            cohort_features, EQUITY_FLOORS.get(program_id, {}),
        )
        used_floor = None
        for floor_cohort in applicable_floors:
            if equity_remaining[program_id].get(floor_cohort, 0) > 0:
                equity_remaining[program_id][floor_cohort] -= 1
                used_floor = floor_cohort
                break

        # Allocate.
        capacity_remaining[program_id] -= 1
        if program["category"] == "add_on":
            patient_add_on_count[patient_id] = (
                patient_add_on_count.get(patient_id, 0) + 1
            )
        else:
            patient_primary_assigned[patient_id] = program_id

        allocation_reason = _reason_string(candidate, used_floor, stage_name)

        stage_allocated.append({
            "patient_id":         patient_id,
            "program_id":         program_id,
            "stage_name":         stage_name,
            "priority":           candidate["priority"],
            "priority_components": candidate["priority_components"],
            "allocation_reason":  allocation_reason,
            "cohort_features":    cohort_features,
            "uplift_estimate":    candidate["uplift_score"],
            "fit_score":          candidate.get("fit_score"),
            "data_quality_flag":  candidate.get("data_quality_flag", "complete"),
        })

    return stage_allocated

def _count_active_enrollments(program_id: str) -> int:
    """Production: query a (program_id, state) GSI; the demo returns 0."""
    return 0

def _scan_active_primary_enrollments(state_table, program_lookup: dict) -> list:
    """
    Production: query a (state, category) GSI joined with the program
    registry; the demo returns an empty list.
    """
    return []

def _operational_feasible(candidate: dict, program: dict) -> bool:
    """
    Operational-feasibility check beyond the language/geography
    filters in eligibility. Placeholder for future per-region
    staffing-capacity checks; the demo returns True.
    """
    return True

def _reason_string(candidate: dict, used_floor: str | None,
                    stage_name: str) -> str:
    """Human-readable allocation reason for the audit log."""
    if used_floor:
        return f"{stage_name}:equity_floor:{used_floor}"
    return f"{stage_name}:high_priority_general_capacity"
```

---

## Step 4: Generate the Care-Manager Enrollment Briefing and Dispatch Outreach

*The pseudocode calls this `dispatch_outreach(allocated_recommendations, run_date)`. Once the orchestrator picks a recommendation, the care management team needs a briefing they can read in 30 seconds before the initial outreach call. Skip the briefing and the care manager goes into the call cold, which produces lower enrollment-conversion and worse rapport on calls that succeed.*

```python
def dispatch_outreach(allocated_recommendations: list, run_date: str,
                       patients: dict, program_lookup: dict) -> list:
    """
    For each allocated recommendation, build a structured briefing
    context, generate the care-manager-facing briefing via Bedrock
    (with templated fallback), persist to enrollment-briefings,
    create the outreach-state row, and transition the per-(patient,
    program) state machine to outreach_in_progress.
    """
    briefings_table = dynamodb.Table(ENROLLMENT_BRIEFINGS_TABLE)
    outreach_table = dynamodb.Table(OUTREACH_STATE_TABLE)
    state_table = dynamodb.Table(PATIENT_PROGRAM_STATE_TABLE)
    profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
    dispatched = []

    for row in allocated_recommendations:
        patient_id = row["patient_id"]
        program_id = row["program_id"]
        program = program_lookup.get(program_id)
        patient = patients.get(patient_id, {})

        if program is None:
            logger.warning(
                "Allocated recommendation references unknown program %s; skipping",
                program_id,
            )
            continue

        # Cross-recipe coordination: care management enrollment
        # outreach has its own contact budget (see main recipe's
        # "Why This Isn't Production-Ready" section). Don't gate
        # this against the routine 4.4-4.6 engagement budget; do
        # gate against a CM-specific budget.
        cm_outreach_30d = int(patient.get("cm_outreach_recent_30d_count", 0))
        if cm_outreach_30d >= MAX_CM_OUTREACH_PER_PATIENT_30D:
            logger.info(
                "Skipping outreach for %s/%s: CM outreach budget exhausted",
                patient_id, program_id,
            )
            continue

        # Build the structured briefing context. De-identified before
        # the LLM call; identifiers are re-attached when the briefing
        # is persisted.
        briefing_context = _build_briefing_context(
            patient, program, row,
        )

        # Generate the briefing via Bedrock (with templated fallback).
        try:
            briefing_parsed = _bedrock_enrollment_briefing(briefing_context)
            if not _validate_briefing(briefing_parsed, briefing_context):
                logger.warning(
                    "Briefing validator failed for %s/%s; using fallback",
                    patient_id, program_id,
                )
                briefing_parsed = _templated_briefing_fallback(
                    briefing_context, row,
                )
        except Exception as exc:
            logger.warning(
                "Briefing generation failed for %s/%s: %s; using fallback",
                patient_id, program_id, exc,
            )
            briefing_parsed = _templated_briefing_fallback(
                briefing_context, row,
            )

        briefing_id = _make_briefing_id(patient_id, program_id, run_date)

        try:
            briefings_table.put_item(Item=_to_decimal_dict({
                "briefing_id":       briefing_id,
                "patient_id":        patient_id,
                "program_id":        program_id,
                "briefing_text":     briefing_parsed,
                "briefing_context":  briefing_context,
                "allocation_reason": row["allocation_reason"],
                "policy_version":    POLICY_VERSION,
                "generated_at":      run_date,
            }))
        except Exception as exc:
            logger.warning(
                "Failed to persist briefing %s: %s", briefing_id, exc,
            )

        # Route to a care-manager queue. Production: the routing
        # respects language, condition specialization, and
        # per-care-manager workload. The example assigns a stub
        # care-manager id for clarity.
        cm_assignment = _route_to_care_manager(row, program)
        outreach_id = _make_outreach_id()

        try:
            outreach_table.put_item(Item=_to_decimal_dict({
                "outreach_id":     outreach_id,
                "patient_id":      patient_id,
                "program_id":      program_id,
                "briefing_id":     briefing_id,
                "assigned_to":     cm_assignment["cm_id"],
                "state":           "queued",
                "attempts":        [],
                "created_at":      run_date,
                "policy_version":  POLICY_VERSION,
            }))
        except Exception as exc:
            logger.warning(
                "Failed to persist outreach record %s: %s", outreach_id, exc,
            )

        try:
            state_table.update_item(
                Key={"patient_id": patient_id, "program_id": program_id},
                UpdateExpression=(
                    "SET #s = :outreach, outreach_id = :oid, "
                    "state_history = list_append("
                    "if_not_exists(state_history, :empty), :history_event)"
                ),
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues=_to_decimal_dict({
                    ":outreach":      "outreach_in_progress",
                    ":oid":           outreach_id,
                    ":empty":         [],
                    ":history_event": [{
                        "event":       "transitioned_recommended_to_outreach",
                        "timestamp":   run_date,
                        "assigned_to": cm_assignment["cm_id"],
                        "outreach_id": outreach_id,
                    }],
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to update state to outreach_in_progress for %s/%s: %s",
                patient_id, program_id, exc,
            )

        # Optimistically increment the CM outreach 30d counter; the
        # outreach worker decrements on outreach failure or unreachable.
        try:
            profile_table.update_item(
                Key={"patient_id": patient_id},
                UpdateExpression="ADD cm_outreach_recent_30d_count :one",
                ExpressionAttributeValues={":one": Decimal("1")},
            )
        except Exception as exc:
            logger.warning(
                "Failed to update CM outreach counter for %s: %s",
                patient_id, exc,
            )

        try:
            kinesis_client.put_record(
                StreamName=CM_ENGAGEMENT_STREAM_NAME,
                PartitionKey=patient_id,
                Data=json.dumps({
                    "event_type":   "program_outreach_initiated",
                    "patient_id":   patient_id,
                    "program_id":   program_id,
                    "outreach_id":  outreach_id,
                    "assigned_to":  cm_assignment["cm_id"],
                    "briefing_id":  briefing_id,
                    "timestamp":    _now_iso(),
                }, default=str).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to publish program_outreach_initiated event: %s", exc,
            )

        dispatched.append({
            "outreach_id": outreach_id,
            "patient_id":  patient_id,
            "program_id":  program_id,
            "briefing_id": briefing_id,
            "briefing":    briefing_parsed,
            "cm_id":       cm_assignment["cm_id"],
        })

    logger.info("Dispatched %d outreach records", len(dispatched))
    return dispatched

def _build_briefing_context(patient: dict, program: dict, row: dict) -> dict:
    """
    Build the structured de-identified context the LLM and the
    fallback template will both consume.
    """
    return {
        "patient_summary":         _summarize_patient_for_briefing(patient),
        "program_id":              program["program_id"],
        "program_name":            program["display_name"],
        "program_theory_of_change": program["theory_of_change"],
        "program_target_duration":  program["target_duration_days"],
        "uplift_estimate":         row["uplift_estimate"],
        "enrollment_likelihood":   row["priority_components"].get(
            "likelihood_contrib"),
        "anticipated_barriers":    _lookup_barriers(patient),
        "recent_clinical_events":  _lookup_recent_events(patient, days=90),
        "language":                patient.get("preferred_language", "en"),
        "allocation_reason":       row["allocation_reason"],
    }

def _summarize_patient_for_briefing(patient: dict) -> dict:
    """
    Compact patient summary at the level of "70s, HF + DM, recent
    discharge, lives alone with weekend caregiver" rather than
    surfacing exact lab values that risk hallucination in the briefing.
    """
    lab_trends = patient.get("recent_lab_trends", {})
    return {
        "age_band":             patient.get("age_band"),
        "active_conditions":    patient.get("active_conditions", []),
        "recent_lab_summary":   {
            "egfr_trend": ("falling" if lab_trends.get("egfr_change_24mo", 0) <= -10
                            else "stable"),
            "a1c_band":   _a1c_band(lab_trends.get("a1c_recent")),
        },
        "social_context":       patient.get("social_context_summary", ""),
        "preferred_language":   patient.get("preferred_language", "en"),
    }

def _a1c_band(a1c) -> str:
    if a1c is None:
        return "unknown"
    if a1c < 7.0:
        return "well_controlled"
    if a1c < 8.0:
        return "moderately_controlled"
    return "elevated"

def _lookup_barriers(patient: dict) -> list:
    """
    Pull barrier flags from the patient profile. Production: query
    the barrier classifier from Recipe 4.5.
    """
    return patient.get("barrier_flags", [])

def _lookup_recent_events(patient: dict, days: int) -> list:
    """
    Recent clinical events relevant to enrollment. Production: query
    the engagement-event store for events within the last `days` days.
    """
    return patient.get("recent_clinical_events", [])[:5]

def _route_to_care_manager(row: dict, program: dict) -> dict:
    """
    Route to a care manager from the program-specific pool. Production
    accounts for language match, condition specialization, and
    per-care-manager workload. The example returns a stub.
    """
    return {"cm_id": f"cm-stub-{program['program_id'][:6]}"}

def _bedrock_enrollment_briefing(context: dict) -> dict:
    """
    Generate a structured enrollment briefing via Bedrock. The
    briefing distills the deterministic ranker's choice plus the
    patient's clinical and social context into a paragraph the care
    manager reads before the initial outreach call.
    """
    de_id_context = _redact_identifiers([context])[0]
    prompt = f"""You write structured enrollment briefings for care managers
in a health plan's care management program. Your role is to package
the deterministic ranker's choice and the patient's clinical and
social context into a brief that the care manager can read in
about 30 seconds before initial outreach. You do not override the
recommendation; you do not propose alternative programs; you do not
invent clinical history not in the context.

Context (de-identified):
{json.dumps(de_id_context, indent=2)}

Return ONLY valid JSON (no prose, no code fences) with this shape:
{{
  "headline":                       "<10-15 word summary>",
  "lead_with":                      "<2-3 sentences on what to lead with>",
  "anticipated_concerns":           ["<concern>", "<concern>", "<concern>"],
  "social_context_that_matters":    "<1-2 sentences>",
  "suggested_modality":             "<recommended initial modality>",
  "suggested_outreach_window":      "<one phrase>",
  "confidence_notes":               "<1 sentence acknowledging uplift uncertainty>"
}}

Reference only conditions, events, barriers, and social-context
elements that appear in the Context block. Do not invent diagnoses
or events. The recommendation is final; do not propose alternative
programs.
"""
    response = bedrock_runtime.invoke_model(
        modelId=ENROLLMENT_BRIEFING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        700,
            "temperature":       0.0,
            "messages":          [{"role": "user", "content": prompt}],
        }),
    )
    payload = json.loads(response["body"].read())
    completion = payload["content"][0]["text"]

    import re as _re
    match = _re.search(r"\{.*\}", completion, _re.DOTALL)
    if not match:
        raise ValueError("LLM returned no JSON object")
    return json.loads(match.group(0))

def _validate_briefing(briefing: dict, observed_context: dict) -> bool:
    """
    Four-layer validator from the main recipe:
      1. Schema and length.
      2. Every referenced clinical fact must appear in observed_context
         (the LLM cannot hallucinate diagnoses or events).
      3. Prohibited content (no PHI invented, no prescriber names,
         no overrides of the deterministic recommendation).
      4. Required notes ("subject to clinical judgment", briefing is
         advisory, patient consent required).

    The example checks shape and the observed-context invariant; a
    production validator extends with regex/blocklist passes.
    """
    required = {"headline", "lead_with", "anticipated_concerns",
                "social_context_that_matters", "suggested_modality",
                "suggested_outreach_window", "confidence_notes"}
    if not isinstance(briefing, dict):
        return False
    if not required.issubset(briefing.keys()):
        return False

    # Shape check.
    for key in {"headline", "lead_with", "social_context_that_matters",
                 "suggested_modality", "suggested_outreach_window",
                 "confidence_notes"}:
        val = briefing[key]
        if not isinstance(val, str) or not val.strip():
            return False
        if len(val) > 600:
            return False

    if not isinstance(briefing["anticipated_concerns"], list):
        return False
    if any(not isinstance(c, str) for c in briefing["anticipated_concerns"]):
        return False

    # Observed-context invariant: any condition the briefing mentions
    # should appear in observed_context.active_conditions.
    full_text = " ".join(
        v if isinstance(v, str) else " ".join(v)
        for v in briefing.values()
    ).lower()

    observed_conditions = set(
        observed_context["patient_summary"]["active_conditions"]
    )
    sentinel_conditions = {
        "heart_failure", "diabetes_type_1", "diabetes_type_2",
        "ckd", "copd", "hypertension", "hyperlipidemia",
    }
    for sentinel in sentinel_conditions:
        sentinel_phrase = sentinel.replace("_", " ")
        if sentinel_phrase in full_text and sentinel not in observed_conditions:
            # Mentioned in the briefing but not in the patient summary:
            # likely hallucination.
            return False

    return True

def _templated_briefing_fallback(context: dict, row: dict) -> dict:
    """
    Deterministic fallback when LLM generation fails or the validator
    rejects. Lists the structured context without LLM narration so
    the care manager still has a usable artifact.
    """
    program_name = context.get("program_name", "")
    barriers = context.get("anticipated_barriers", []) or [
        "(no barrier flags surfaced)"
    ]
    return {
        "headline":                    f"Enrollment candidate: {program_name} "
                                        f"({row.get('allocation_reason', '')}).",
        "lead_with":                   "Lead with the patient's most recent "
                                        "clinical context and the program's fit. "
                                        "(Briefing fallback used; review chart directly.)",
        "anticipated_concerns":        list(barriers)[:3],
        "social_context_that_matters": context.get(
            "patient_summary", {}).get("social_context", "")
            or "(no social context summary available)",
        "suggested_modality":          "telephonic",
        "suggested_outreach_window":   "weekday daytime",
        "confidence_notes":            "Briefing fallback; LLM generation failed "
                                        "or validator rejected output. Care manager "
                                        "should read chart context before outreach.",
    }


def _decrement_outreach_counter(patient_id: str) -> None:
    """
    Decrement the rolling 30-day outreach counter on the patient profile.
    Called when an outreach attempt results in a terminal-unreachable,
    declined, or deferred outcome: the slot didn't produce the intended
    enrollment conversation, so it should not count against the patient's
    future outreach budget.

    Uses SET with subtraction (not ADD, which only supports Number and Set
    types) and a ConditionExpression to prevent going below zero.
    """
    dynamodb = boto3.resource("dynamodb")
    profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
    try:
        profile_table.update_item(
            Key={"patient_id": patient_id},
            UpdateExpression=(
                "SET cm_outreach_recent_30d_count = "
                "cm_outreach_recent_30d_count - :one"
            ),
            ExpressionAttributeValues={
                ":one":  Decimal("1"),
                ":zero": Decimal("0"),
            },
            ConditionExpression="cm_outreach_recent_30d_count > :zero",
        )
    except Exception:
        # Condition check fails if counter is already 0; safe to ignore.
        pass


def record_outreach_attempt(outreach_id: str, attempt_result: dict,
                              run_date: str) -> None:
    """
    Record the result of a care-manager outreach attempt and advance
    the per-(patient, program) state machine accordingly.

    attempt_result is one of:
      { "result": "consented", "consent_form_id": "...",
        "baseline_assessment_id": "..." }
      { "result": "declined", "reason": "..." }
      { "result": "unreachable", "attempt_count": int,
        "next_attempt_scheduled": ISO date }
      { "result": "deferred", "reason": "...", "defer_until": ISO date }
    """
    outreach_table = dynamodb.Table(OUTREACH_STATE_TABLE)
    state_table = dynamodb.Table(PATIENT_PROGRAM_STATE_TABLE)
    profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)

    try:
        response = outreach_table.get_item(Key={"outreach_id": outreach_id})
        outreach = _from_decimal(response.get("Item") or {})
    except Exception as exc:
        logger.warning("Failed to read outreach record %s: %s",
                        outreach_id, exc)
        return

    if not outreach:
        logger.warning("Outreach record %s not found", outreach_id)
        return

    attempts = outreach.get("attempts", []) + [{
        "attempt_at": _now_iso(),
        "result":     attempt_result["result"],
        "details":    attempt_result,
    }]

    result = attempt_result["result"]
    patient_id = outreach["patient_id"]
    program_id = outreach["program_id"]

    if result == "consented":
        new_outreach_state = "consented"
        new_program_state = "enrolled"
        consent_id = attempt_result.get("consent_form_id")
        baseline_id = attempt_result.get("baseline_assessment_id")
        program_target_duration = _lookup_target_duration(program_id)
        history_event = {
            "event":                 "transitioned_outreach_to_enrolled",
            "timestamp":             _now_iso(),
            "consent_form_id":       consent_id,
            "baseline_assessment_id": baseline_id,
        }
        try:
            state_table.update_item(
                Key={"patient_id": patient_id, "program_id": program_id},
                UpdateExpression=(
                    "SET #s = :enrolled, "
                    "enrollment_metadata = :em, "
                    "state_history = list_append("
                    "if_not_exists(state_history, :empty), :history_event)"
                ),
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues=_to_decimal_dict({
                    ":enrolled":      "enrolled",
                    ":empty":         [],
                    ":em": {
                        "enrolled_at":           _now_iso(),
                        "consent_form_id":        consent_id,
                        "baseline_assessment_id": baseline_id,
                        "target_duration":        program_target_duration,
                    },
                    ":history_event":  [history_event],
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist enrollment for %s/%s: %s",
                patient_id, program_id, exc,
            )

    elif result == "declined":
        new_outreach_state = "declined"
        new_program_state = "declined"
        try:
            state_table.update_item(
                Key={"patient_id": patient_id, "program_id": program_id},
                UpdateExpression=(
                    "SET #s = :declined, "
                    "state_history = list_append("
                    "if_not_exists(state_history, :empty), :he)"
                ),
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues=_to_decimal_dict({
                    ":declined": "declined",
                    ":empty":    [],
                    ":he": [{
                        "event":         "transitioned_outreach_to_declined",
                        "timestamp":     _now_iso(),
                        "decline_reason": attempt_result.get("reason"),
                    }],
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist decline for %s/%s: %s",
                patient_id, program_id, exc,
            )
        # Decrement the outreach budget: a declined outreach did not
        # produce the intended enrollment conversation. Without this,
        # the counter accumulates phantom consumption that silences
        # the patient from future enrollment outreach for 30 days.
        _decrement_outreach_counter(patient_id)

    elif result == "unreachable":
        if attempt_result.get("attempt_count", 0) >= MAX_OUTREACH_ATTEMPTS:
            new_outreach_state = "unreachable_terminal"
            new_program_state = "outreach_failed"
            try:
                state_table.update_item(
                    Key={"patient_id": patient_id, "program_id": program_id},
                    UpdateExpression=(
                        "SET #s = :failed, "
                        "state_history = list_append("
                        "if_not_exists(state_history, :empty), :he)"
                    ),
                    ExpressionAttributeNames={"#s": "state"},
                    ExpressionAttributeValues=_to_decimal_dict({
                        ":failed": "outreach_failed",
                        ":empty":  [],
                        ":he": [{
                            "event":     "transitioned_outreach_to_failed",
                            "timestamp": _now_iso(),
                            "attempts":  attempt_result.get("attempt_count"),
                        }],
                    }),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to persist outreach_failed for %s/%s: %s",
                    patient_id, program_id, exc,
                )
            # Decrement the CM outreach budget when the attempt
            # terminates unreachable; the slot didn't actually result
            # in a patient-facing conversation.
            _decrement_outreach_counter(patient_id)
        else:
            new_outreach_state = "unreachable_pending_retry"
            new_program_state = None    # state stays outreach_in_progress

    elif result == "deferred":
        new_outreach_state = "deferred"
        new_program_state = "deferred"
        try:
            state_table.update_item(
                Key={"patient_id": patient_id, "program_id": program_id},
                UpdateExpression=(
                    "SET #s = :deferred, deferred_until = :du, "
                    "state_history = list_append("
                    "if_not_exists(state_history, :empty), :he)"
                ),
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues=_to_decimal_dict({
                    ":deferred": "deferred",
                    ":du":       attempt_result.get("defer_until"),
                    ":empty":    [],
                    ":he": [{
                        "event":        "transitioned_outreach_to_deferred",
                        "timestamp":    _now_iso(),
                        "defer_until":  attempt_result.get("defer_until"),
                        "defer_reason": attempt_result.get("reason"),
                    }],
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist deferral for %s/%s: %s",
                patient_id, program_id, exc,
            )
        # Decrement the outreach budget: a deferred outreach did not
        # produce the intended enrollment conversation. The counter
        # will be re-incremented when the deferred outreach is
        # re-attempted after defer_until.
        _decrement_outreach_counter(patient_id)
    else:
        logger.warning("Unknown outreach result: %s", result)
        return

    try:
        outreach_table.update_item(
            Key={"outreach_id": outreach_id},
            UpdateExpression="SET #s = :st, attempts = :att",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues=_to_decimal_dict({
                ":st":  new_outreach_state,
                ":att": attempts,
            }),
        )
    except Exception as exc:
        logger.warning(
            "Failed to update outreach state %s: %s", outreach_id, exc,
        )

    try:
        kinesis_client.put_record(
            StreamName=CM_ENGAGEMENT_STREAM_NAME,
            PartitionKey=patient_id,
            Data=json.dumps({
                "event_type":  "program_outreach_attempted",
                "outreach_id": outreach_id,
                "patient_id":  patient_id,
                "program_id":  program_id,
                "result":      result,
                "timestamp":   _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to publish program_outreach_attempted event: %s", exc,
        )

def _lookup_target_duration(program_id: str) -> int:
    """Look up program target duration from the registry."""
    for p in SAMPLE_PROGRAM_REGISTRY:
        if p["program_id"] == program_id:
            return p.get("target_duration_days", 90)
    return 90
```

> **Curious how this looks alongside the prose?** This Python companion implements the pseudocode walkthrough in [Recipe 4.7](chapter04.07-care-management-program-enrollment). The recipe explains the architecture, the trade-offs, and the honest take on where this gets hard.

---

## Step 5: Track In-Program Engagement and Trigger Retention When Engagement Declines

*The pseudocode calls this `score_engagement(patient_id, program_id, run_date)`. Once a patient is enrolled, the engagement scorer runs against the program-specific engagement profile. Below threshold, the retention worker activates with a strategy keyed to the decline pattern. Skip the engagement tracking and you discover at month three that the patient stopped engaging at month one and the program slot has been wasted.*

```python
def score_engagement(patient_id: str, program_id: str, run_date: str,
                      program_lookup: dict) -> dict:
    """
    Compute the per-(patient, program) engagement score, classify
    the decline pattern if at-risk, persist to engagement-state, and
    fire the retention worker when engagement is below threshold.

    Returns the engagement record persisted.
    """
    state_table = dynamodb.Table(PATIENT_PROGRAM_STATE_TABLE)
    engagement_table = dynamodb.Table(ENGAGEMENT_STATE_TABLE)

    state_response = state_table.get_item(
        Key={"patient_id": patient_id, "program_id": program_id}
    )
    state_record = _from_decimal(state_response.get("Item") or {})
    if state_record.get("state") not in ("enrolled", "engaged",
                                            "enrolled_extended", "at_risk"):
        logger.info(
            "Skipping engagement scoring for %s/%s: state=%s",
            patient_id, program_id, state_record.get("state"),
        )
        return {}

    program = program_lookup.get(program_id, {})
    profile = _build_engagement_profile(patient_id, program_id, run_date)
    engagement_score = _engagement_scoring_function(profile, program_id)

    threshold = ENGAGEMENT_PROFILES.get(
        program_id, {}).get("at_risk_threshold", 0.50)
    is_at_risk = engagement_score < threshold

    decline_pattern = None
    if is_at_risk:
        decline_pattern = _classify_decline(profile)

    record = {
        "patient_id":        patient_id,
        "program_id":        program_id,
        "engagement_score":  round(engagement_score, 4),
        "engagement_profile": profile,
        "is_at_risk":        is_at_risk,
        "decline_pattern":   decline_pattern,
        "last_scored_at":    _now_iso(),
        "scoring_window":    f"{run_date}_window",
    }

    try:
        engagement_table.put_item(Item=_to_decimal_dict(record))
    except Exception as exc:
        logger.warning(
            "Failed to persist engagement state for %s/%s: %s",
            patient_id, program_id, exc,
        )

    # Update the per-(patient, program) state machine.
    new_state = "at_risk" if is_at_risk else "engaged"
    if state_record.get("state") != new_state:
        try:
            state_table.update_item(
                Key={"patient_id": patient_id, "program_id": program_id},
                UpdateExpression=(
                    "SET #s = :st, "
                    "state_history = list_append("
                    "if_not_exists(state_history, :empty), :he)"
                ),
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues=_to_decimal_dict({
                    ":st": new_state,
                    ":empty": [],
                    ":he": [{
                        "event":            f"transitioned_to_{new_state}",
                        "timestamp":        _now_iso(),
                        "engagement_score": engagement_score,
                        "decline_pattern":  decline_pattern,
                    }],
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to update state to %s for %s/%s: %s",
                new_state, patient_id, program_id, exc,
            )

    if is_at_risk:
        try:
            kinesis_client.put_record(
                StreamName=CM_ENGAGEMENT_STREAM_NAME,
                PartitionKey=patient_id,
                Data=json.dumps({
                    "event_type":       "program_at_risk",
                    "patient_id":       patient_id,
                    "program_id":       program_id,
                    "engagement_score": engagement_score,
                    "decline_pattern":  decline_pattern,
                    "timestamp":        _now_iso(),
                }, default=str).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to publish program_at_risk event for %s/%s: %s",
                patient_id, program_id, exc,
            )

        trigger_retention(patient_id, program_id, decline_pattern)

    return record

def _build_engagement_profile(patient_id: str, program_id: str,
                                run_date: str) -> dict:
    """
    Assemble the per-(patient, program) engagement profile. Production:
    join the engagement-event stream with the case-management system's
    completed-contact records and any patient self-report submissions.
    The example reads from a synthetic in-memory dict.
    """
    return _DEMO_ENGAGEMENT_PROFILES.get((patient_id, program_id), {
        "scheduled_contacts":            0,
        "completed_contacts":            0,
        "missed_contacts":               0,
        "self_reported_data_submissions": 0,
        "education_modules_completed":   0,
        "recent_clinical_events":        [],
    })

def _engagement_scoring_function(profile: dict, program_id: str) -> float:
    """
    Per-program engagement-scoring function. Each program weights
    the engagement signals differently; HF cares about weight
    submissions, DM cares about education-module completion,
    polypharmacy cares about prescriber-action follow-through.

    Output [0, 1].
    """
    expected_contacts = ENGAGEMENT_PROFILES.get(
        program_id, {}).get("expected_contacts_in_window", 1)
    completed = profile.get("completed_contacts", 0)
    missed = profile.get("missed_contacts", 0)
    submissions = profile.get("self_reported_data_submissions", 0)
    modules = profile.get("education_modules_completed", 0)

    contact_component = (
        min(1.0, completed / max(1, expected_contacts))
        - 0.1 * missed
    )
    contact_component = max(0.0, contact_component)

    submission_component = min(1.0, submissions / 4.0)
    module_component = min(1.0, modules / 3.0)

    if program_id == "heart-failure-program":
        weights = (0.45, 0.40, 0.15)    # contact, weight subs, modules
    elif program_id == "diabetes-management-program":
        weights = (0.35, 0.25, 0.40)
    elif program_id == "polypharmacy-management":
        weights = (0.50, 0.30, 0.20)
    elif program_id == "transitional-care-management":
        weights = (0.70, 0.20, 0.10)
    else:    # complex-care
        weights = (0.55, 0.25, 0.20)

    score = (weights[0] * contact_component
             + weights[1] * submission_component
             + weights[2] * module_component)
    return max(0.0, min(1.0, score))

def _classify_decline(profile: dict) -> str:
    """
    Classify the decline pattern when engagement is below threshold.

    Patterns:
      - no_initial_engagement: never engaged after enrollment
      - gradual_drop_off: engagement declined steadily
      - event_driven_drop: engagement dropped after a specific event
        (admission, life event)
      - modality_mismatch: low engagement on assigned modality;
        switching may help
      - staffing_disruption: care-manager change or vacation
        coincides with the drop
    """
    completed = profile.get("completed_contacts", 0)
    missed = profile.get("missed_contacts", 0)
    recent_events = profile.get("recent_clinical_events", [])

    if completed == 0:
        return "no_initial_engagement"

    recent_admission = any(
        e.get("event_type") == "inpatient_admission" for e in recent_events
    )
    if recent_admission:
        return "event_driven_drop"

    if missed >= 2 and completed >= 1:
        return "gradual_drop_off"

    return "modality_mismatch"

def trigger_retention(patient_id: str, program_id: str,
                       decline_pattern: str | None) -> None:
    """
    Schedule a retention attempt keyed to the decline pattern. The
    retention strategies are program-specific; the example codes
    decline-pattern-specific dispatch but stops short of the per-
    program tailoring (production extends per program).
    """
    if decline_pattern is None:
        return

    strategy_map = {
        "no_initial_engagement":     ("fresh_cm_different_modality", 7),
        "gradual_drop_off":          ("engagement_check_in_conversation", 5),
        "event_driven_drop":         ("event_acknowledgment_and_recalibration", 3),
        "modality_mismatch":         ("modality_switch", 7),
        "staffing_disruption":       ("continuity_recovery", 7),
    }

    strategy, attempt_within_days = strategy_map.get(
        decline_pattern, ("engagement_check_in_conversation", 7),
    )

    logger.info(
        "Retention scheduled for %s/%s: strategy=%s within %d days",
        patient_id, program_id, strategy, attempt_within_days,
    )

    try:
        kinesis_client.put_record(
            StreamName=CM_ENGAGEMENT_STREAM_NAME,
            PartitionKey=patient_id,
            Data=json.dumps({
                "event_type":         "program_retention_attempted",
                "patient_id":         patient_id,
                "program_id":         program_id,
                "decline_pattern":    decline_pattern,
                "strategy":           strategy,
                "attempt_within_days": attempt_within_days,
                "timestamp":          _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to publish retention event for %s/%s: %s",
            patient_id, program_id, exc,
        )

# Demo state populated by the runner.
_DEMO_ENGAGEMENT_PROFILES: dict = {}
```

---

## Step 6: Disenrollment Decisions, Cross-Program Transitions, and Post-Graduation Observation

*The pseudocode covers `evaluate_disenrollment`, `process_disenrollment_decision`, `recommend_cross_program_transitions`, and `post_graduation_observation`. Disenrollment is decision-supported, not autonomous: the deterministic policy proposes, the LLM packages a rationale, the human decides. Skip the post-graduation observation pathway and you lose graduates to relapse without any visibility, undermining the whole point of program graduation.*

```python
def evaluate_disenrollment(patient_id: str, program_id: str,
                             run_date: str, program_lookup: dict) -> dict:
    """
    Evaluate whether to recommend disenrollment for an at-risk
    patient or whether to graduate a near-completion patient or
    transition mid-program. The decision is decision-supported, not
    autonomous; the LLM-generated rationale is for human review.
    """
    state_table = dynamodb.Table(PATIENT_PROGRAM_STATE_TABLE)
    engagement_table = dynamodb.Table(ENGAGEMENT_STATE_TABLE)

    state_record = _from_decimal(state_table.get_item(
        Key={"patient_id": patient_id, "program_id": program_id}
    ).get("Item") or {})
    engagement_record = _from_decimal(engagement_table.get_item(
        Key={"patient_id": patient_id, "program_id": program_id}
    ).get("Item") or {})

    if not state_record:
        logger.warning("No state record for %s/%s", patient_id, program_id)
        return {}

    enrollment = state_record.get("enrollment_metadata", {}) or {}
    enrolled_at = enrollment.get("enrolled_at")
    if not enrolled_at:
        return {}

    target_duration = enrollment.get(
        "target_duration", _lookup_target_duration(program_id),
    )

    try:
        run = datetime.date.fromisoformat(run_date)
        enrolled = datetime.date.fromisoformat(enrolled_at[:10])
        days_since_enrollment = (run - enrolled).days
    except Exception:
        days_since_enrollment = 0

    last_engagement_at = _last_engagement_date(engagement_record)
    days_since_last_engagement = (
        (run - datetime.date.fromisoformat(last_engagement_at[:10])).days
        if last_engagement_at else 9999
    )

    failed_retention = _count_failed_retention_attempts(
        patient_id, program_id,
    )
    is_at_risk = engagement_record.get("is_at_risk", False)

    # Decision policy.
    if (is_at_risk
        and failed_retention >= MAX_RETENTION_ATTEMPTS
        and days_since_last_engagement >= DISENROLL_NO_ENGAGEMENT_DAYS):
        recommended_action = "disenroll_for_no_engagement"
    elif days_since_enrollment >= target_duration:
        if _goals_substantially_met(patient_id, program_id):
            recommended_action = "graduate"
        elif is_at_risk:
            recommended_action = "disenroll_did_not_complete"
        else:
            recommended_action = "extend_or_transition"
    elif _clinical_deterioration_detected(patient_id, program_id):
        recommended_action = "transition_to_higher_acuity"
    else:
        recommended_action = "continue"

    if recommended_action == "continue":
        return {"recommended_action": "continue"}

    # Generate the LLM rationale (with templated fallback).
    rationale_context = {
        "patient_summary":         _summarize_patient_for_briefing(
            _DEMO_PATIENTS_FOR_RATIONALE.get(patient_id, {})
        ),
        "program_id":              program_id,
        "program_name":            program_lookup.get(program_id, {}).get(
            "display_name", ""),
        "enrollment_metadata":     enrollment,
        "engagement_history":      engagement_record.get(
            "engagement_profile", {}),
        "days_since_enrollment":   days_since_enrollment,
        "days_since_last_engagement": days_since_last_engagement,
        "recommended_action":      recommended_action,
        "policy_rule_triggered":   _describe_triggering_rule(
            recommended_action, engagement_record, enrollment,
            days_since_enrollment, days_since_last_engagement,
        ),
    }

    try:
        rationale_parsed = _bedrock_disenrollment_rationale(rationale_context)
        if not _validate_rationale(rationale_parsed):
            rationale_parsed = _templated_rationale_fallback(rationale_context)
    except Exception as exc:
        logger.warning(
            "Disenrollment rationale generation failed for %s/%s: %s",
            patient_id, program_id, exc,
        )
        rationale_parsed = _templated_rationale_fallback(rationale_context)

    decision_id = _make_decision_id()
    decisions_table = dynamodb.Table(DISENROLLMENT_DECISIONS_TABLE)
    try:
        decisions_table.put_item(Item=_to_decimal_dict({
            "decision_id":          decision_id,
            "patient_id":           patient_id,
            "program_id":           program_id,
            "recommended_action":   recommended_action,
            "rationale":            rationale_parsed,
            "rationale_context":    rationale_context,
            "human_review_pending": True,
            "recommended_at":       run_date,
        }))
    except Exception as exc:
        logger.warning(
            "Failed to persist disenrollment decision %s: %s",
            decision_id, exc,
        )

    try:
        kinesis_client.put_record(
            StreamName=CM_ENGAGEMENT_STREAM_NAME,
            PartitionKey=patient_id,
            Data=json.dumps({
                "event_type":         "disenrollment_decision_recommended",
                "patient_id":         patient_id,
                "program_id":         program_id,
                "decision_id":        decision_id,
                "recommended_action": recommended_action,
                "timestamp":          _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to publish disenrollment_decision_recommended event: %s",
            exc,
        )

    return {
        "decision_id":        decision_id,
        "patient_id":         patient_id,
        "program_id":         program_id,
        "recommended_action": recommended_action,
        "rationale":          rationale_parsed,
    }

def process_disenrollment_decision(decision_id: str,
                                      human_decision: dict,
                                      program_lookup: dict) -> None:
    """
    Process a clinical-lead-reviewed disenrollment decision. Update
    state, trigger cross-program transition recommendations, mark
    the decision resolved.

    human_decision is one of:
      { "decision": "approve", "recommended_action": "..." }
      { "decision": "override", "actual_action": "...",
        "override_reason": "..." }
    """
    decisions_table = dynamodb.Table(DISENROLLMENT_DECISIONS_TABLE)
    state_table = dynamodb.Table(PATIENT_PROGRAM_STATE_TABLE)

    decision = _from_decimal(decisions_table.get_item(
        Key={"decision_id": decision_id}
    ).get("Item") or {})
    if not decision:
        logger.warning("Disenrollment decision %s not found", decision_id)
        return

    final_action = (
        decision["recommended_action"]
        if human_decision.get("decision") == "approve"
        else human_decision.get("actual_action")
    )

    patient_id = decision["patient_id"]
    program_id = decision["program_id"]

    if final_action == "graduate":
        try:
            state_table.update_item(
                Key={"patient_id": patient_id, "program_id": program_id},
                UpdateExpression=(
                    "SET #s = :graduated, "
                    "graduation_metadata = :gm, "
                    "state_history = list_append("
                    "if_not_exists(state_history, :empty), :he)"
                ),
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues=_to_decimal_dict({
                    ":graduated": "graduated",
                    ":empty":     [],
                    ":gm": {
                        "graduated_at": _now_iso(),
                        "post_graduation_observation_window":
                            POST_GRADUATION_OBSERVATION_DAYS,
                        "post_graduation_relapse_signals": [],
                    },
                    ":he": [{
                        "event":      "transitioned_enrolled_to_graduated",
                        "timestamp":  _now_iso(),
                        "decision_id": decision_id,
                    }],
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to record graduation for %s/%s: %s",
                patient_id, program_id, exc,
            )
        recommend_cross_program_transitions(
            patient_id, program_id, "graduation", program_lookup,
        )

    elif final_action == "disenroll_for_no_engagement":
        _persist_disenrollment(
            patient_id, program_id, decision_id,
            new_state="disenrolled_for_cause",
            reason="no_engagement_after_retention",
            re_eligibility_window_days=RE_ELIGIBILITY_WINDOW_FOR_NO_ENGAGEMENT,
        )

    elif final_action == "disenroll_did_not_complete":
        _persist_disenrollment(
            patient_id, program_id, decision_id,
            new_state="disenrolled_incomplete",
            reason="duration_reached_with_unmet_engagement",
        )

    elif final_action == "transition_to_higher_acuity":
        _persist_disenrollment(
            patient_id, program_id, decision_id,
            new_state="transitioned_out",
            reason="deterioration_during_enrollment",
        )
        recommend_cross_program_transitions(
            patient_id, program_id, "deterioration", program_lookup,
        )

    elif final_action == "extend_or_transition":
        try:
            state_table.update_item(
                Key={"patient_id": patient_id, "program_id": program_id},
                UpdateExpression=(
                    "SET #s = :extended, "
                    "enrollment_metadata.target_duration = "
                    "enrollment_metadata.target_duration + :ext, "
                    "state_history = list_append("
                    "if_not_exists(state_history, :empty), :he)"
                ),
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues=_to_decimal_dict({
                    ":extended": "enrolled_extended",
                    ":ext":      EXTENSION_DAYS,
                    ":empty":    [],
                    ":he": [{
                        "event":       "extended",
                        "timestamp":   _now_iso(),
                        "decision_id": decision_id,
                    }],
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to extend enrollment for %s/%s: %s",
                patient_id, program_id, exc,
            )

    try:
        decisions_table.update_item(
            Key={"decision_id": decision_id},
            UpdateExpression=(
                "SET human_review_pending = :false, "
                "human_decision = :hd, final_action = :fa, "
                "resolved_at = :now"
            ),
            ExpressionAttributeValues=_to_decimal_dict({
                ":false": False,
                ":hd":    human_decision,
                ":fa":    final_action,
                ":now":   _now_iso(),
            }),
        )
    except Exception as exc:
        logger.warning(
            "Failed to mark decision %s resolved: %s", decision_id, exc,
        )

def _persist_disenrollment(patient_id: str, program_id: str,
                            decision_id: str, new_state: str,
                            reason: str,
                            re_eligibility_window_days: int | None = None) -> None:
    """Common disenrollment-state persistence helper."""
    state_table = dynamodb.Table(PATIENT_PROGRAM_STATE_TABLE)
    metadata = {
        "disenrolled_at": _now_iso(),
        "reason":         reason,
    }
    if re_eligibility_window_days is not None:
        metadata["re_eligibility_window_days"] = re_eligibility_window_days

    try:
        state_table.update_item(
            Key={"patient_id": patient_id, "program_id": program_id},
            UpdateExpression=(
                "SET #s = :st, disenrollment_metadata = :dm, "
                "state_history = list_append("
                "if_not_exists(state_history, :empty), :he)"
            ),
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues=_to_decimal_dict({
                ":st": new_state,
                ":dm": metadata,
                ":empty": [],
                ":he": [{
                    "event":       f"transitioned_to_{new_state}",
                    "timestamp":   _now_iso(),
                    "decision_id": decision_id,
                    "reason":      reason,
                }],
            }),
        )
    except Exception as exc:
        logger.warning(
            "Failed to persist disenrollment for %s/%s: %s",
            patient_id, program_id, exc,
        )

def recommend_cross_program_transitions(patient_id: str,
                                          prior_program_id: str,
                                          context: str,
                                          program_lookup: dict) -> dict:
    """
    Recommend a cross-program transition based on the configured
    transition map. Surface for human review; the human decides
    whether to act.
    """
    transitions_table = dynamodb.Table(CROSS_PROGRAM_TRANSITIONS_TABLE)
    candidate_program_ids = CROSS_PROGRAM_TRANSITIONS_MAP.get(
        (prior_program_id, context), [],
    )

    if not candidate_program_ids:
        return {}

    # Pick the first candidate that exists in the active registry.
    chosen = None
    for pid in candidate_program_ids:
        if pid in program_lookup:
            chosen = pid
            break
    if chosen is None:
        return {}

    transition_id = f"transition-{uuid.uuid4().hex[:16]}"
    record = {
        "transition_id":          transition_id,
        "patient_id":             patient_id,
        "prior_program_id":       prior_program_id,
        "recommended_program_id": chosen,
        "context":                context,
        "recommended_at":         _now_iso(),
        "human_review_pending":   True,
    }

    try:
        transitions_table.put_item(Item=_to_decimal_dict(record))
    except Exception as exc:
        logger.warning(
            "Failed to persist cross-program-transition %s: %s",
            transition_id, exc,
        )

    try:
        kinesis_client.put_record(
            StreamName=CM_ENGAGEMENT_STREAM_NAME,
            PartitionKey=patient_id,
            Data=json.dumps({
                "event_type":             "cross_program_transition_recommended",
                "patient_id":             patient_id,
                "prior_program_id":       prior_program_id,
                "recommended_program_id": chosen,
                "context":                context,
                "transition_id":          transition_id,
                "timestamp":              _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to publish cross_program_transition_recommended: %s",
            exc,
        )

    return record


def sweep_stale_pending_outreach(run_date: str) -> None:
    """
    Hourly sweep: for outreach-state rows where state is 'queued' or
    'outreach_in_progress' and created_at is more than 7 days ago
    with no engagement-event activity, mark state as
    'stale_no_activity' and decrement the outreach counter.

    This catches outreach dispatched but never reached the patient
    (care-manager attrition, queue overflow, system errors). Without
    this sweep, phantom counter consumption silences the patient from
    future enrollment outreach.
    """
    dynamodb = boto3.resource("dynamodb")
    outreach_table = dynamodb.Table(OUTREACH_STATE_TABLE)
    cutoff = (datetime.fromisoformat(run_date)
              - timedelta(days=7)).isoformat()

    # In production, use a GSI on state + created_at for efficient
    # scanning. This example uses a full scan for simplicity.
    response = outreach_table.scan(
        FilterExpression=(
            "(#s = :queued OR #s = :in_progress) AND created_at < :cutoff"
        ),
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={
            ":queued":      "queued",
            ":in_progress": "outreach_in_progress",
            ":cutoff":      cutoff,
        },
    )
    for row in response.get("Items", []):
        try:
            outreach_table.update_item(
                Key={"outreach_id": row["outreach_id"]},
                UpdateExpression="SET #s = :stale",
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues={":stale": "stale_no_activity"},
            )
            _decrement_outreach_counter(row["patient_id"])
            logger.info(
                "Marked stale outreach %s for %s/%s",
                row["outreach_id"], row["patient_id"], row["program_id"],
            )
        except Exception as exc:
            logger.warning(
                "Failed to mark stale outreach %s: %s",
                row["outreach_id"], exc,
            )


def post_graduation_observation(run_date: str) -> list:
    """
    Daily sweep over recently graduated patients within the
    observation window. Detect relapse signals and update state to
    in_observation_relapse_detected when found.
    """
    state_table = dynamodb.Table(PATIENT_PROGRAM_STATE_TABLE)
    relapses = []

    try:
        response = state_table.scan()
        records = [_from_decimal(item) for item in response.get("Items", [])]
    except Exception as exc:
        logger.warning("Scan of state for observation failed: %s", exc)
        return []

    cutoff_str = (
        datetime.date.fromisoformat(run_date)
        - datetime.timedelta(days=POST_GRADUATION_OBSERVATION_DAYS)
    ).isoformat()

    for record in records:
        if record.get("state") != "graduated":
            continue
        graduation_metadata = record.get("graduation_metadata", {})
        graduated_at = graduation_metadata.get("graduated_at", "")[:10]
        if graduated_at < cutoff_str:
            continue

        relapse_signals = _detect_relapse_signals(
            record["patient_id"], record["program_id"], graduated_at,
        )

        if not relapse_signals:
            continue

        try:
            state_table.update_item(
                Key={"patient_id": record["patient_id"],
                      "program_id": record["program_id"]},
                UpdateExpression=(
                    "SET #s = :rel, "
                    "graduation_metadata.post_graduation_relapse_signals = :rs"
                ),
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues=_to_decimal_dict({
                    ":rel": "in_observation_relapse_detected",
                    ":rs":  relapse_signals,
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to update post-graduation observation for %s/%s: %s",
                record["patient_id"], record["program_id"], exc,
            )

        try:
            kinesis_client.put_record(
                StreamName=CM_ENGAGEMENT_STREAM_NAME,
                PartitionKey=record["patient_id"],
                Data=json.dumps({
                    "event_type":      "post_graduation_relapse_detected",
                    "patient_id":      record["patient_id"],
                    "prior_program_id": record["program_id"],
                    "relapse_signals": relapse_signals,
                    "timestamp":       _now_iso(),
                }, default=str).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to publish post-graduation relapse event: %s", exc,
            )

        relapses.append({
            "patient_id":      record["patient_id"],
            "prior_program_id": record["program_id"],
            "relapse_signals":  relapse_signals,
        })

    logger.info(
        "Post-graduation observation found %d relapses in window", len(relapses),
    )
    return relapses

def _last_engagement_date(engagement_record: dict) -> str | None:
    """Pull the most recent engagement-date from the engagement profile."""
    profile = engagement_record.get("engagement_profile", {}) or {}
    if profile.get("completed_contacts", 0) > 0:
        return engagement_record.get("last_scored_at")
    return None

def _count_failed_retention_attempts(patient_id: str,
                                       program_id: str) -> int:
    """
    Production: query the engagement-event store for retention
    events tagged failed in the recent window.
    """
    return _DEMO_FAILED_RETENTION_COUNTS.get((patient_id, program_id), 0)

def _goals_substantially_met(patient_id: str, program_id: str) -> bool:
    """
    Program-specific goal-completion check. Production: query the
    case-management system for completed care-plan goals.
    """
    return _DEMO_GOALS_MET.get((patient_id, program_id), False)

def _clinical_deterioration_detected(patient_id: str,
                                       program_id: str) -> bool:
    """
    Detect mid-program clinical deterioration that should trigger
    escalation to a higher-acuity program. Production: pull recent
    clinical events; the demo reads from a synthetic dict.
    """
    return _DEMO_DETERIORATION.get((patient_id, program_id), False)

def _describe_triggering_rule(recommended_action: str,
                                engagement_record: dict,
                                enrollment: dict,
                                days_since_enrollment: int,
                                days_since_last_engagement: int) -> str:
    """Describe the policy rule that triggered the recommendation."""
    if recommended_action == "disenroll_for_no_engagement":
        return (
            f"At-risk after {MAX_RETENTION_ATTEMPTS} retention attempts; "
            f"{days_since_last_engagement} days since last engagement "
            f"(threshold: {DISENROLL_NO_ENGAGEMENT_DAYS})."
        )
    if recommended_action == "graduate":
        return f"Program duration met ({days_since_enrollment} days); goals met."
    if recommended_action == "disenroll_did_not_complete":
        return (
            f"Program duration reached ({days_since_enrollment} days); "
            "engagement remained at-risk."
        )
    if recommended_action == "transition_to_higher_acuity":
        return "Mid-program clinical deterioration detected."
    if recommended_action == "extend_or_transition":
        return (
            f"Program duration reached ({days_since_enrollment} days); "
            "engaged but goals not yet substantially met."
        )
    return "no_rule_described"

def _detect_relapse_signals(patient_id: str, program_id: str,
                             graduated_at: str) -> list:
    """Detect relapse signals from the engagement-event store and clinical feeds."""
    return _DEMO_RELAPSE_SIGNALS.get((patient_id, program_id), [])

def _bedrock_disenrollment_rationale(context: dict) -> dict:
    """Generate a structured disenrollment-decision rationale via Bedrock."""
    de_id_context = _redact_identifiers([context])[0]
    prompt = f"""You generate decision-support rationales for clinical leads
reviewing care management disenrollment decisions. You package the
deterministic policy rule that triggered the recommendation and the
engagement-history evidence supporting it. You do not make the
disenrollment decision; the human does.

Context (de-identified):
{json.dumps(de_id_context, indent=2)}

Return ONLY valid JSON (no prose, no code fences) with this shape:
{{
  "headline":                       "<10-15 word summary of the recommendation>",
  "evidence_summary":               "<2-4 sentences citing engagement-history evidence>",
  "countervailing_factors":         ["<factor>", "<factor>"],
  "policy_rule":                    "<plain-language description of the rule>",
  "suggested_human_review_questions": ["<question>", "<question>"]
}}

Cite only engagement and timing evidence that appears in the Context.
Do not invent clinical details. The recommendation is decision-supported,
not autonomous; the human makes the actual call.
"""
    response = bedrock_runtime.invoke_model(
        modelId=DISENROLLMENT_RATIONALE_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        700,
            "temperature":       0.0,
            "messages":          [{"role": "user", "content": prompt}],
        }),
    )
    payload = json.loads(response["body"].read())
    completion = payload["content"][0]["text"]
    import re as _re
    match = _re.search(r"\{.*\}", completion, _re.DOTALL)
    if not match:
        raise ValueError("LLM returned no JSON object")
    return json.loads(match.group(0))

def _validate_rationale(rationale: dict) -> bool:
    """Shape and length validator for the disenrollment rationale."""
    required = {"headline", "evidence_summary", "countervailing_factors",
                "policy_rule", "suggested_human_review_questions"}
    if not isinstance(rationale, dict):
        return False
    if not required.issubset(rationale.keys()):
        return False
    for key in {"headline", "evidence_summary", "policy_rule"}:
        if not isinstance(rationale[key], str):
            return False
        if not rationale[key].strip():
            return False
        if len(rationale[key]) > 700:
            return False
    if not isinstance(rationale["countervailing_factors"], list):
        return False
    if not isinstance(rationale["suggested_human_review_questions"], list):
        return False
    return True

def _templated_rationale_fallback(context: dict) -> dict:
    """Templated fallback rationale when LLM generation or validation fails."""
    return {
        "headline":         f"Recommendation: {context.get('recommended_action')}.",
        "evidence_summary": context.get("policy_rule_triggered", ""),
        "countervailing_factors": ["(LLM rationale unavailable; review chart directly.)"],
        "policy_rule":      context.get("policy_rule_triggered", ""),
        "suggested_human_review_questions": [
            "Is the engagement evidence consistent with chart context?",
            "Are there structural barriers the retention attempts did not address?",
        ],
    }

# Demo state populated by the runner.
_DEMO_FAILED_RETENTION_COUNTS: dict = {}
_DEMO_GOALS_MET: dict = {}
_DEMO_DETERIORATION: dict = {}
_DEMO_RELAPSE_SIGNALS: dict = {}
_DEMO_PATIENTS_FOR_RATIONALE: dict = {}
```

---

## Putting It All Together

Here's the daily / weekly pipeline assembled into a single callable function. In production, this is split across several Step Functions workflows:

- **Daily eligibility evaluation pipeline** runs Step 1 against the prior day's data feeds.
- **Weekly enrollment-decision pipeline** runs Steps 2-4: enrich eligible candidates, allocate via the multi-stage orchestrator, dispatch outreach with briefings.
- **Continuous engagement worker** runs Step 5 against the engagement-event stream from the case-management system.
- **Weekly disenrollment-evaluation pipeline** runs the at-risk and near-completion sweep against `evaluate_disenrollment`.
- **Daily post-graduation observation pipeline** runs Step 6's `post_graduation_observation`.

The example chains them together so you can trace one cycle end-to-end.

```python
def run_weekly_enrollment_cycle(
    patients_list: list,
    run_date: str | None = None,
) -> dict:
    """
    Run the full weekly enrollment cycle.

    Steps 1-4:
      1. evaluate_program_eligibility (daily; we run once for the demo)
      2. enrich_eligible_candidates
      3. allocate_enrollments
      4. dispatch_outreach

    Step 5 (engagement scoring) and Step 6 (disenrollment + post-grad
    observation + cross-program transitions) run continuously and on
    separate cadences. The example runs them once each at the end with
    synthetic events.
    """
    run_date = run_date or _today_str()
    start = time.time()

    print(f"=== Starting weekly enrollment cycle for run_date={run_date} ===")

    patients = {p["patient_id"]: p for p in patients_list}
    program_lookup = {p["program_id"]: p for p in SAMPLE_PROGRAM_REGISTRY}

    print("\nStep 1: Evaluating program registry against patient data...")
    transitions = evaluate_program_eligibility(patients_list, run_date)
    print(f"  {len(transitions)} (patient, program) eligibility records")

    print("\nStep 2: Enriching eligible candidates with uplift, likelihood, "
          "engagement, fit, priority...")
    enriched = enrich_eligible_candidates(run_date, patients, program_lookup)
    print(f"  Enriched {len(enriched)} candidates")

    print("\nStep 3: Multi-stage allocation under capacity and equity floors...")
    allocated = allocate_enrollments(enriched, run_date, program_lookup)
    print(f"  Allocated {len(allocated)} (patient, program) recommendations")

    print("\nStep 4: Generating enrollment briefings and dispatching outreach...")
    dispatched = dispatch_outreach(allocated, run_date, patients, program_lookup)
    print(f"  Dispatched {len(dispatched)} outreach records")

    elapsed = int(time.time() - start)
    print(f"\n=== Cycle complete in {elapsed}s ===")
    return {
        "run_date":         run_date,
        "n_patients":       len(patients_list),
        "n_transitions":    len(transitions),
        "n_enriched":       len(enriched),
        "n_allocated":      len(allocated),
        "n_dispatched":     len(dispatched),
        "elapsed_seconds":  elapsed,
        "dispatched":       dispatched,
        "allocated":        allocated,
    }

# --- Demo runner ---
if __name__ == "__main__":
    # All sample data is SYNTHETIC. Do not use real PHI in development.
    # The demo:
    #   1. Builds three synthetic patients (Linda from the opening
    #      narrative of the recipe, plus two others)
    #   2. Seeds synthetic engagement profiles, goals-met flags,
    #      relapse signals, and deterioration flags
    #   3. Runs Steps 1-4 against the synthetic data
    #   4. Simulates an outreach-attempt result (consented), an
    #      engagement-scoring run (Step 5), a disenrollment evaluation
    #      and human decision (Step 6), a cross-program transition,
    #      and a post-graduation observation sweep
    #
    # The Bedrock and SageMaker calls are mocked at the helper level so
    # the demo runs offline.

    print("=" * 70)
    print("Building synthetic patients and seeding feed lookups...")
    print("=" * 70)

    run_date = _today_str()

    patients_list = [
        {
            "patient_id":               "pat-002148",
            "age":                      72,
            "age_band":                 "65-74",
            "preferred_language":       "en",
            "engagement_history_quartile": "q3",
            "sdoh_cohort":              "moderate_food_security",
            "active_conditions":        ["heart_failure", "diabetes_type_2",
                                          "ckd", "atrial_fibrillation",
                                          "hypertension"],
            "continuously_enrolled":    True,
            "cm_outreach_recent_30d_count": Decimal("0"),
            "outreach_recent_30d_count": Decimal("0"),
            "last_admission_date":      (datetime.date.fromisoformat(run_date)
                                           - datetime.timedelta(days=22)
                                          ).isoformat(),
            "last_discharge_date":      (datetime.date.fromisoformat(run_date)
                                           - datetime.timedelta(days=18)
                                          ).isoformat(),
            "last_discharge_disposition": "home",
            "last_hf_encounter_date":   (datetime.date.fromisoformat(run_date)
                                           - datetime.timedelta(days=22)
                                          ).isoformat(),
            "predicted_admission_probability_12mo": 0.41,
            "recent_lab_trends": {
                "a1c_recent":         8.4,
                "egfr_change_24mo":  -8,
            },
            "current_medications":      ["furosemide", "carvedilol",
                                          "lisinopril", "spironolactone",
                                          "metformin", "apixaban",
                                          "atorvastatin"],
            "distinct_prescribers_180d": 3,
            "barrier_flags":            ["cost_sensitivity", "mobility_limited"],
            "social_context_summary":   "Lives alone, fourth-floor walkup with "
                                         "intermittent elevator. Daughter "
                                         "available weekends.",
            "prior_program_declines":   [],
            "recent_clinical_events":   [
                {"event_type": "inpatient_admission",
                 "date": (datetime.date.fromisoformat(run_date)
                          - datetime.timedelta(days=22)).isoformat(),
                 "primary_diagnosis": "HF_decompensation"},
            ],
        },
        {
            "patient_id":               "pat-002149",
            "age":                      58,
            "age_band":                 "55-64",
            "preferred_language":       "es",
            "engagement_history_quartile": "q1",
            "sdoh_cohort":              "low_food_security",
            "active_conditions":        ["diabetes_type_2"],
            "continuously_enrolled":    True,
            "cm_outreach_recent_30d_count": Decimal("0"),
            "outreach_recent_30d_count": Decimal("0"),
            "predicted_admission_probability_12mo": 0.18,
            "recent_lab_trends": {
                "a1c_recent":         9.2,
                "egfr_change_24mo":  -2,
            },
            "current_medications":      ["metformin", "glipizide"],
            "distinct_prescribers_180d": 1,
            "barrier_flags":            ["language_barrier"],
            "social_context_summary":   "Working two part-time jobs; "
                                         "daughter is primary translator.",
            "prior_program_declines":   [],
            "recent_clinical_events":   [],
        },
        {
            "patient_id":               "pat-002150",
            "age":                      80,
            "age_band":                 "75-plus",
            "preferred_language":       "en",
            "engagement_history_quartile": "q2",
            "sdoh_cohort":              "transportation_barrier",
            "active_conditions":        ["copd", "heart_failure",
                                          "diabetes_type_2", "ckd",
                                          "depression", "osteoarthritis"],
            "continuously_enrolled":    True,
            "cm_outreach_recent_30d_count": Decimal("0"),
            "outreach_recent_30d_count": Decimal("0"),
            "predicted_admission_probability_12mo": 0.55,
            "recent_lab_trends": {
                "a1c_recent":         7.6,
                "egfr_change_24mo":  -12,
            },
            "current_medications":      ["furosemide", "metformin",
                                          "tiotropium", "albuterol",
                                          "sertraline", "metoprolol",
                                          "atorvastatin", "vitamin_d",
                                          "calcium_carbonate", "acetaminophen"],
            "distinct_prescribers_180d": 4,
            "barrier_flags":            ["transportation", "low_health_literacy"],
            "social_context_summary":   "Lives with adult daughter; "
                                         "transportation requires daughter's "
                                         "schedule.",
            "prior_program_declines":   [],
            "recent_clinical_events":   [],
        },
    ]

    # Seed the synthetic exclusion / fragmentation / history / dispatch
    # state.
    _DEMO_FRAGMENTATION_FLAGS.update({})
    _DEMO_HISTORY_COUNT.update({
        "pat-002148": 80, "pat-002149": 30, "pat-002150": 120,
    })

    # Mock Bedrock calls so the demo runs offline. Production never
    # bypasses these.
    def _mock_briefing(context):
        return {
            "headline":                    f"{context.get('program_name')} "
                                            f"candidate after recent destabilization.",
            "lead_with":                   "Lead with the connection between recent "
                                            "events and the program's theory of change. "
                                            "Frame as keeping the patient out of the "
                                            "hospital, not as a program structure.",
            "anticipated_concerns":        ["Cost concerns",
                                             "Time/scheduling fit",
                                             "Logistical barriers"],
            "social_context_that_matters": context.get(
                "patient_summary", {}).get("social_context", "")
                or "(no specific social context)",
            "suggested_modality":          "telephonic",
            "suggested_outreach_window":   "weekday mornings",
            "confidence_notes":            "Uplift estimate has wide CI; "
                                            "recommendation is to enroll, but "
                                            "expect probabilistic improvement.",
        }

    def _mock_rationale(context):
        return {
            "headline":         f"Recommendation: {context.get('recommended_action')}.",
            "evidence_summary": context.get("policy_rule_triggered", ""),
            "countervailing_factors": ["Engagement history pattern",
                                         "Recent clinical context"],
            "policy_rule":      context.get("policy_rule_triggered", ""),
            "suggested_human_review_questions": [
                "Did the retention attempts address the actual decline pattern?",
                "Is there a different modality that has not been tried?",
            ],
        }

    # Patch module-level Bedrock helpers for offline demo.
    globals()["_bedrock_enrollment_briefing"] = _mock_briefing
    globals()["_bedrock_disenrollment_rationale"] = _mock_rationale

    _DEMO_PATIENTS_FOR_RATIONALE.update({
        p["patient_id"]: p for p in patients_list
    })

    print(f"  Patients: {len(patients_list)}")

    print("\n" + "=" * 70)
    print("Running pipeline Steps 1-4 against synthetic data...")
    print("=" * 70)

    summary = run_weekly_enrollment_cycle(
        patients_list=patients_list,
        run_date=run_date,
    )
    print(f"\nCycle summary keys: {list(summary.keys())}")
    print(f"Allocated: {summary['n_allocated']}; "
          f"Dispatched: {summary['n_dispatched']}")

    # ---- Outreach attempt: simulate Linda consenting to HF program ----
    if summary["dispatched"]:
        target = next(
            (d for d in summary["dispatched"]
             if d["patient_id"] == "pat-002148"
             and d["program_id"] == "heart-failure-program"),
            None,
        )
        if target:
            print("\n" + "=" * 70)
            print("Simulating outreach result: Linda consents to HF program")
            print("=" * 70)
            record_outreach_attempt(
                outreach_id=target["outreach_id"],
                attempt_result={
                    "result":                 "consented",
                    "consent_form_id":        f"consent-{run_date}-pat-002148-hf",
                    "baseline_assessment_id": f"baseline-{run_date}-pat-002148-hf",
                },
                run_date=run_date,
            )

    # ---- Step 5: simulate engagement scoring during week 4 ----
    print("\n" + "=" * 70)
    print("Simulating engagement scoring at week 4 (Step 5)...")
    print("=" * 70)
    program_lookup = {p["program_id"]: p for p in SAMPLE_PROGRAM_REGISTRY}

    _DEMO_ENGAGEMENT_PROFILES[("pat-002148", "heart-failure-program")] = {
        "scheduled_contacts":             4,
        "completed_contacts":             4,
        "missed_contacts":                0,
        "self_reported_data_submissions": 3,
        "education_modules_completed":    3,
        "recent_clinical_events": [
            {"event_type": "lab_BNP", "value": "412 pg/mL",
             "trend": "down_from_baseline"},
        ],
    }
    score_engagement("pat-002148", "heart-failure-program",
                       run_date, program_lookup)

    # An at-risk example to exercise the retention path.
    _DEMO_ENGAGEMENT_PROFILES[("pat-002150", "complex-care-management")] = {
        "scheduled_contacts":             3,
        "completed_contacts":             1,
        "missed_contacts":                2,
        "self_reported_data_submissions": 0,
        "education_modules_completed":    0,
        "recent_clinical_events":         [],
    }
    # We need state to be enrolled-or-equivalent for the scorer to run.
    state_table = dynamodb.Table(PATIENT_PROGRAM_STATE_TABLE)
    try:
        state_table.put_item(Item=_to_decimal_dict({
            "patient_id":   "pat-002150",
            "program_id":   "complex-care-management",
            "state":        "enrolled",
            "eligibility":  "eligible",
            "state_history": [{"event": "demo_seed",
                                "timestamp": _now_iso()}],
            "enrollment_metadata": {
                "enrolled_at":    (datetime.date.fromisoformat(run_date)
                                    - datetime.timedelta(days=21)
                                   ).isoformat(),
                "target_duration": 365,
            },
        }))
    except Exception:
        pass
    score_engagement("pat-002150", "complex-care-management",
                       run_date, program_lookup)

    # ---- Step 6: simulate a disenrollment evaluation -> human decision ----
    print("\n" + "=" * 70)
    print("Simulating disenrollment evaluation and human decision (Step 6)...")
    print("=" * 70)

    _DEMO_FAILED_RETENTION_COUNTS[("pat-002150",
                                    "complex-care-management")] = 3
    _DEMO_GOALS_MET[("pat-002150", "complex-care-management")] = False

    decision = evaluate_disenrollment(
        "pat-002150", "complex-care-management", run_date, program_lookup,
    )
    print(f"  Disenrollment decision: {decision.get('recommended_action')}")

    if decision.get("decision_id"):
        process_disenrollment_decision(
            decision["decision_id"],
            human_decision={"decision":           "approve",
                             "recommended_action": decision["recommended_action"]},
            program_lookup=program_lookup,
        )
        print("  Human decision: approve")

    # Cross-program transition example: graduation from HF program.
    print("\n" + "=" * 70)
    print("Simulating cross-program transition recommendation...")
    print("=" * 70)
    transition = recommend_cross_program_transitions(
        "pat-002148", "heart-failure-program", "graduation", program_lookup,
    )
    print(f"  Transition recommendation: {transition.get('recommended_program_id')}")

    # Post-graduation observation sweep.
    print("\n" + "=" * 70)
    print("Running post-graduation observation sweep...")
    print("=" * 70)
    relapses = post_graduation_observation(run_date)
    print(f"  Relapses detected: {len(relapses)}")

    print("\n=== Demo complete ===")
```

---

## The Gap Between This and Production

Run this end-to-end against a curated program registry, populated claims/EHR/lab/pharmacy/discharge feeds, trained SageMaker response/likelihood/engagement models, working case-management-system integration, configured outreach channels, and a Connect-integrated care-manager workflow, and you'll see the pattern: per-(patient, program) state machine maintained correctly, response (uplift) and per-program engagement scored, multi-stage allocation respecting capacity and equity, briefings and outreach dispatched, in-program engagement tracked with retention triggers, disenrollment decisions decision-supported with cross-program transitions and post-graduation observation. The distance between this and a real health-plan deployment is significant. Here's where it lives.

**Program-registry curation as an ongoing program.** The registry is the source of truth for what each program is, who it's for, and what its capacity is. New programs launch, old programs sunset, capacities flex with staffing every quarter, contractual obligations evolve, and clinical evidence shifts what each program does. Plan for at least 0.25 to 0.5 FTE of program-leadership and clinical-informatics time on registry maintenance ongoing, with structured change management: proposed change, capacity model, impact analysis on prior-version cohort, version bump, parallel evaluation, then promotion. 

**Causal-inference rigor for response (uplift) models.** Most plans have observational enrollment data with strong selection bias (clinician referral, prior engagement, geographic accessibility). Training response models on observational data without causal-inference tooling produces uplift estimates biased toward the cohorts the historical selection process favored. The downstream effect is a recommender that recommends what the historical bias recommended, with extra steps. Plan for a data science investment in causal inference: skills, tooling (EconML's DML, DR-Learner, Causal Forest, plus DoWhy), and operational willingness to randomize a fraction of enrollment slots for unbiased reference. Without this, the program drifts toward serving the cohorts the historical bias served. The Obermeyer 2019 finding is the canonical cautionary tale; design for it. 

**Multi-source data ingestion.** The example queries from synthetic in-memory dicts. Production ingests from at least seven distinct source types: claims (EDI 837), EHR (FHIR API or batch flat-file export per EHR vendor), lab feeds (HL7 v2 ORU or FHIR Observation), pharmacy data (NCPDP feeds and immunization administration), discharge feeds (ADT messages from inpatient systems, often vendor-mediated), risk-stratification scores (commercial vendor or in-house model), and care-management-system events (vendor APIs or vendor-pushed events). Plan 12 to 20 weeks of ingestion engineering before the first eligibility-evaluation run, plus an ongoing source-feed health dashboard and explicit outage handling per source.

**SageMaker Feature Store integration.** The example skips Feature Store usage. Production wires per-patient and per-(patient, program) feature ingestion through Glue or Spark into both the offline and online stores, with feature freshness guarantees per source. The feature definitions are reused across Recipes 4.4, 4.5, 4.6, and 4.7; centralizing them in the Feature Store is the entire point.

**SageMaker Batch Transform output schema and model registry.** The example replaces real Batch Transform calls with rule-based proxies. Production: define an explicit output schema per model (ideally JSONL with named fields), validate it on every job completion, version the schema alongside the model. With three model families across five programs, that's 15 model artifacts; the SageMaker Model Registry plus canary-run-on-held-out-cohort-before-promotion automation is essential. A model upgrade that silently changes output column order is a production failure mode that's painful to debug.

**SageMaker training-job triggers.** The architecture diagram shows "Periodic retrain" without an explicit trigger. Production wires retraining via either an EventBridge schedule (e.g., monthly per program) or a CloudWatch metric threshold (e.g., engagement-rate drift exceeds X). New models go through SageMaker Model Registry with a canary on a held-out cohort; failures trigger rollback and Slack alerts. With 15 artifacts, the retraining schedule and the canary-failure runbook matter substantively.

**Eligibility and inclusion via Glue, not application code.** The example builds denominator/inclusion/exclusion logic in Python for clarity. Production uses parameterized SQL templates (Jinja or a SQL-construction library) so denominator predicates are SQL queries that scale across millions of patient-rows. A typo in a registry-stored predicate that becomes SQL injection is not the production failure mode you want.

**Step Functions orchestration with explicit DLQ coverage.** The example chains Steps 1-4 in a single Python function. Production runs the daily eligibility pipeline as a Step Functions state machine; the weekly enrollment-decision pipeline as a second state machine; the engagement-scoring worker as a Lambda triggered on the Kinesis cm-engagement-stream; the disenrollment-evaluation pipeline as a third state machine on a weekly cadence; and the post-graduation observation pipeline as a fourth state machine on a daily cadence. Each task has Catch handlers routing failures to per-stage SQS DLQs keyed on (run_date, stage, failure_reason). The Kinesis-to-Lambda event source mapping for the state-machine worker, engagement scorer, and retention trigger needs an explicit `OnFailure` destination pointing to SQS, alarmed on DLQ depth. A silently-dropped state-transition event is operationally damaging in this recipe (a missed `program_at_risk` event delays retention; a missed `program_enrolled` event leaves the engagement scorer unarmed; a missed disenrollment decision leaves the slot tied up indefinitely), so DLQ coverage matters substantively. Mirrors the language flagged in 4.4 through 4.6.

**Bedrock cost and latency budget.** The example calls Bedrock per allocated recommendation for enrollment briefings, per disenrollment decision for rationales, and per outreach for patient-message tailoring. At ~1,400 active enrollments plus 5,000 monthly engagement summaries plus ~200 monthly disenrollment rationales, the budget is manageable with Haiku-class models. Production caches templated content where the structured context is similar (per-program, per-language, per-cohort hash) and only invokes Bedrock for unique cases. Monitor Bedrock spend in CloudWatch and set per-account quota alarms.

**Connect contact-flow and care-management integration.** The example dispatches outreach to a stub `cm-stub-*` care-manager id. Real Amazon Connect integration: contact-flow definitions for the enrollment outreach script, work-queue routing that respects language and program-specialization, HIPAA-eligible call recording, integration with the engagement-event stream so dispatch and outcome are reflected as state transitions, and care-manager-facing softphone or browser CRM integration. Plans with vendor-managed care management have a parallel integration shape: structured-event handoff to the vendor's queue, structured-event return, and contractual data-feed requirements for engagement and outcome events. Plan 12 to 20 weeks of Connect or vendor-integration engineering depending on which path you're on.

**Patient consent and HIPAA authorization workflow.** Care management enrollment requires multiple consent artifacts: HIPAA authorization for data sharing across program staff (and across vendor partners if applicable), program-specific informed consent describing what the patient is enrolling in, and (for some programs) consent for data sharing with external entities (community resources, social-work referrals). The consent capture and storage flow needs to be tightly designed and tightly audited; consent-form-version mismatches and missing consent are compliance issues that produce disenrollment-and-restart cycles. The example treats consent as a `consent_form_id` string; production: a separate consent-management service (often vendor-supplied) integrated via structured events with version tracking and re-consent renewals.

**Tracking-ID and briefing-ID privacy.** The example builds briefing IDs as `f"brief-{run_date}-{patient_id}-{program_id}"` for readability. Production must replace this with an opaque, non-reversible identifier (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plain-text patient_ids and program_ids embedded in briefing IDs (carried in care-manager queues, EHR inboxes, vendor outreach handoffs, engagement events) are PHI leakage. The same applies to `_make_outreach_id` (already opaque in the example) and `_make_decision_id` (already opaque). Mirror the language flagged in 4.4 through 4.6.

**DynamoDB Decimal gotchas.** The example uses `_to_decimal` and `_to_decimal_dict` consistently when persisting numeric values. The pattern is correct, but the trap is real: if you add a feature that persists a model confidence, an embedding magnitude, or any other floating-point value, you must wrap it at the boundary or DynamoDB will reject the write.

**Cohort-feature PHI sensitivity and program-state inferential PHI.** The patient-program-state, enrollment-briefings, and engagement-state tables are highly inferential PHI. A row indicating "patient recommended for complex-care management with high uplift" is more sensitive than a row indicating "patient eligible for wellness program" because the recommendation reveals the program's clinical-need profile. Apply tighter controls to program state for stigmatized or high-sensitivity programs (behavioral health, substance use, palliative care, HIV-related): narrower IAM read scopes, optional separate-table partitioning, additional CloudTrail data event capture, and a documented minimum-necessary access policy. SDOH cohort labels (`transportation_barrier`, `low_food_security`) are PHI-equivalent and should follow the minimum-necessary principle: engagement events should carry only the cohort axes the equity dashboard actually consumes, with narrower IAM scope than for general engagement data. Mirror the language flagged in 4.4 through 4.6.

**Equity floor design and Obermeyer-style failure-mode prevention.** The equity floors in this example reserve fixed capacity per cohort. Designing the floors well requires baseline cohort enrollment data (which you don't have until operating for some time), explicit policy on which disparities trigger floors versus other interventions (cohort-aware retraining, cohort-stratified outcome evaluation, retention-strategy adjustments), and willingness to revisit floors quarterly. The Obermeyer scenario is the canonical concern: a recommender trained on observational data with under-represented cohorts will systematically under-enroll those cohorts unless the design explicitly compensates. Equity floors are one mechanism; cohort-aware retraining with reweighting is another; cohort-stratified outcome evaluation is the validation. Don't try to design the perfect equity floor on day one; design the right operating cadence for adjusting them. Plan a quarterly cross-functional committee review of equity metrics with explicit action ownership.

**Cross-recipe orchestration with Recipes 4.4, 4.5, 4.6.** A patient who's a candidate for adherence intervention (4.5), care-gap closure (4.6), wellness program (4.4), and care management (4.7) gets too many touches if each recipe orchestrates independently. The example uses a CM-specific contact budget (`cm_outreach_recent_30d_count`) separate from the routine 4.4-4.6 engagement budget; this is the documented exception. Production needs an explicit cross-recipe priority-arbitration policy, version-controlled and committee-reviewed, that documents: (1) care management enrollment outreach gets a separate budget from routine 4.4-4.6 outreach, with a hard cap on combined contacts in 30 days; (2) cross-recipe priority arbitration when caps would be exceeded; (3) the rule that the enrollment conversation is the highest-priority interaction in chapter 4 and should not routinely be deferred for adherence reminders. 

**Outreach attempt management.** The example handles outreach-attempt counting and terminal-unreachable transitions. Production needs more nuance: rest periods between attempts, time-of-day modeling per patient, opt-out registry integration, suppression after specific patient signals (declined first outreach plus missed appointment is a stronger signal than two unanswered calls), TCPA and state telephone-consumer-protection rules, and integration with the case-management system's contact-history view. The outreach worker is the most patient-facing component; treat it accordingly.

**Disenrollment governance and review.** Disenrollment-for-cause decisions have member-experience implications and may have civil-rights implications if they concentrate in protected populations. Build a monthly disenrollment-review cadence: a cross-functional committee reviews the prior month's disenrollment-for-cause cases, with cohort breakdowns, looking for patterns suggesting the policy is mis-targeting, the retention attempts are inadequate, or the program structure is unfit for some cohorts. Build the review cadence into the policy from day one, not as an afterthought.

**Multi-source state-machine reconciliation.** The patient's program state lives in multiple systems: the recommender's `patient-program-state` table, the care management vendor's case-management system, the EHR's care-plan view, and the patient's portal. Drift across these is a chronic operational pain. Plan for tight integration with the case-management system (event-driven sync, not periodic batch reconciliation), explicit conflict-resolution rules when sources disagree, and periodic full-reconciliation runs that flag drift for human review.

**Outcome evaluation methodology rigor.** The example doesn't ship an outcome-evaluation function; the architecture diagram shows it, but the implementation is intentionally out of scope for a recipe demonstration. Production: pre-register the analysis specification before each evaluation runs (define cohort definitions, outcome definitions, primary statistical test up front), run sensitivity analyses against alternative matching specifications, have a statistical reviewer who is not the team running the recommender, document the methodology in a memo signed by the medical director and the equity lead. Watch especially for the regression-to-the-mean trap discussed in the main recipe's Honest Take. Without propensity-matched difference-in-differences as the default, outcome reporting will overstate program impact.

**Cost-per-enrollment and cost-per-prevented-event tracking.** The cost numbers in the main recipe's Prerequisites table are infrastructure only. Production reporting needs end-to-end cost (infrastructure + care-manager loaded hours + telephony + vendor invoices + program-specific costs like Bluetooth scales for HF or pharmacist time for polypharmacy) divided by confirmed prevented events attributable to the program (above the matched-control baseline). That number compared to the value of prevented events (avoided admission cost, avoided ED visit cost, plan-quality-bonus value) determines whether the program returns its budget. The data engineering to track this end-to-end with attribution is its own project and is essential for program-level decisions about expansion or contraction.

**Annual and contractual reporting requirements.** CMS Medicare Advantage care management activities have specific reporting requirements (CCM and PCM CPT code documentation, care plan structure, time-tracking for billable activities). State Medicaid programs often have their own care management reporting structures. Value-based contracts have their own. Build the reporting layer into the system from the beginning; retrofitting reporting onto a system that wasn't designed for it is painful and produces compliance gaps. 

**Care-manager workload modeling.** Care managers don't have uniform capacity: a complex-care manager handling 50 patients with multi-system disease has different bandwidth than a transitional-care nurse running 20 active 30-day episodes. The work-queue routing in Step 4 needs to model per-care-manager realistic loaded hours, not just headcount. Without this, the routing produces care-manager burnout, attrition, and a slow-moving operations problem that undermines the entire program.

**Patient-friendly enrollment visibility.** Patients should see their own program enrollment status, upcoming activities, and progress in the patient portal, with explanations they can understand. "Your heart-failure care management program" is more useful than "HF-CMP-2026-v2." Patient-facing summaries are a separate UX project, with content review by health-literacy specialists, but the program state machine in this recipe is the source data. Plan for the patient-facing layer as a parallel deliverable.

**VPC, encryption, and audit.** This example calls APIs over public AWS endpoints. A production Lambda handling PHI runs in a VPC with private subnets and VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock Runtime (interface), SageMaker Runtime and Feature Store (interface), Kinesis (interface), CloudWatch Logs (interface), Athena (interface), Step Functions (`states`), EventBridge (`events`), STS, SES, Pinpoint, Connect, and HealthLake (if used). All nine DynamoDB tables encrypt at rest with a customer-managed KMS key. CloudTrail data events are enabled for the patient-program-state, program-registry, enrollment-briefings, outreach-state, engagement-state, recommendation-log, disenrollment-decisions, and patient-profile tables. A clinical or compliance audit will eventually ask "who was recommended for what on this date and why" and you need to answer definitively.

**Synthetic data and testing.** There are no tests in this example. A production pipeline needs unit tests for the denominator/inclusion/exclusion logic per program; the per-program response and engagement scoring functions; the multi-stage allocator with capacity and equity floors; the engagement scorer with decline-pattern classification; the disenrollment-decision policy; the cross-program-transition recommender; integration tests against a synthetic Synthea-generated patient population across cohort axes; regression tests that confirm hard exclusion rules (hospice, palliative care) are never bypassed; load tests at expected volumes (250K eligible patients, 5+ programs, 1,400 active enrollments, weekly enrollment cycle); chaos tests that drop a SageMaker job mid-pipeline and verify Step Functions resumes from the right state. Never use real PHI in non-production environments. [Synthea](https://github.com/synthetichealth/synthea) generates synthetic FHIR patients with realistic conditions and procedures suitable for the eligibility pipeline.

**Cohort fairness review process.** The architecture emits cohort-sliced metrics, but a dashboard nobody reviews is useless. Establish a quarterly review with a cross-functional committee (data science, equity lead, medical director, program leadership, operations lead). Watch for: enrollment-rate parity by cohort, per-cohort uplift versus per-cohort enrollment rate, per-cohort engagement and graduation rates, per-cohort disenrollment-for-cause rates, per-cohort outcome (post-program admissions, ED, total cost). Each finding produces an action item with an owner.

**Cold-start handling for new programs.** The example assumes every program has trained response, likelihood, and engagement models. A brand-new program has none. Cold-start strategy: launch new programs with rule-based scoring only (no supervised model), run a randomized pilot for the first 1-2 cycles to bootstrap training data, fall back to baseline scoring if the model is underfitting, document explicitly in the recommendation log that the program is in "calibrating" mode. Mirrors the cold-start pattern from 4.6.

**Data-quality flag propagation.** The `data_quality_flag` is set per (patient, program) but downstream consumers in this example don't gate on it. Production must gate at these sites: (1) the disenrollment evaluator must route `cross_provider_fragmentation` and `multi_source_disagreement` patients through a `verify_engagement_first` action before any `disenroll_for_no_engagement` recommendation (as now specified in the architecture pseudocode); (2) the response-enrichment step should widen the uplift confidence interval on non-complete data-quality cases; (3) the orchestrator should route fragmented-data patients through a verification-first allocation path; (4) the briefing generator should include a `data_quality_caveat` in `confidence_notes`; (5) the engagement scorer should widen CI on the engagement score and require multi-source consistency for `is_at_risk = true`; (6) the cross-program transition recommender should flag recommendations with a `data_quality_caveat`. A confidently "eligible" recommendation on a patient with `cross_provider_fragmentation` is a confidently mis-calibrated recommendation if the patient is already enrolled in care management at a different system. Disenrolling on incomplete data has civil-rights implications when it concentrates in protected cohorts.

**Idempotency and retry semantics.** Each stage's outputs are addressed by deterministic keys (run_date, patient_id, program_id) and writes should be conditional, so a Step Functions retry that re-attempts a completed step is a no-op rather than a duplicate. The example uses `put_item` and `update_item` without conditions on most paths; production adds `ConditionExpression` to the relevant writes (e.g., `attribute_not_exists(briefing_id)` on the briefings put) so reattempted writes converge. A DynamoDB gotcha: appending to a List attribute requires the `list_append(if_not_exists(state_history, :empty), :new_event)` pattern in the `UpdateExpression`, not the `ADD` action (which only supports Number and Set data types). All state-transition sites in this example use the correct `list_append` + `if_not_exists` pattern.

**Mid-program clinical-deterioration detection.** The example uses a synthetic flag (`_DEMO_DETERIORATION`). Production: a continuous monitor over the engagement-event stream and the clinical-event feeds that detects deterioration during enrollment (new admission, abnormal lab, condition progression, sharp engagement drop concurrent with clinical signals) and triggers the disenrollment-and-cross-program-transition path immediately rather than waiting for the weekly disenrollment cycle. Latency between deterioration and escalation is a clinical-quality metric; minutes-to-hours is the target, not days.

**Re-engagement-after-disenrollment cycle.** The example codes the re-eligibility window for disenrollment-for-cause but doesn't ship a re-engagement mechanism. Production: an EventBridge rule fires when the re-eligibility window ends, the eligibility evaluator runs against the patient, and if eligibility is restored a re-engagement recommendation enters the next enrollment cycle with explicit context that the patient was previously disenrolled-for-cause. The re-engagement attempt typically uses a different care manager and a different modality than the original; the deterministic policy can encode this.

**Real-time post-discharge enrollment.** The example treats all programs on the same daily eligibility cycle. Production: an EventBridge rule fires on incoming discharge events and immediately runs transitional-care eligibility for that patient outside the daily cycle. The 30-day TCM window is time-sensitive; reducing the time-to-outreach from days to hours captures more of the high-leverage early window. The pseudocode emits an `eligibility_acquired` event tagged `time_sensitive`; production wires that to a dedicated state machine that runs steps 2-4 for the single patient on demand.

**Care-team feedback loop.** Care managers' notes, clinical observations, and disenrollment reasons should flow back into the recommender as features and as labels. The example doesn't ship this loop. Production: a structured-feedback API on the case-management system that captures (patient, program, feedback_category, feedback_text, structured_label) and joins into the retraining pipeline. Without the feedback loop, the response models drift away from the operational reality the care managers see daily.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 4.7: Care Management Program Enrollment](chapter04.07-care-management-program-enrollment) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
