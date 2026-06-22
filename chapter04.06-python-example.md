# Recipe 4.6: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 4.6. It shows one way you could translate the care-gap prioritization pattern into working Python using AWS Glue / Athena for daily gap evaluation against a measure registry, Amazon SageMaker (Feature Store, Batch Transform, Training) for the per-gap-type clinical urgency models and per-pathway engagement and closure-probability models, Amazon DynamoDB for the measure registry, per-(patient, gap) state machine, recommendation log, clinician briefings, and clinician overrides, Amazon S3 for the data lake and evaluation outputs, AWS Step Functions for the daily and pre-visit pipelines, AWS Lambda for the per-stage glue, Amazon Bedrock for candidate-gap surfacing, pre-visit clinician briefings, and patient-facing message tailoring, Amazon Kinesis for closure and engagement events, and Amazon SES / Amazon Pinpoint / Amazon Connect for outreach delivery. It is not production-ready. There is no real claims, EHR, or immunization-registry ingestion, no NCQA-parity testing against a HEDIS vendor, no validated supervised urgency model with confounding-adjustment, no live PCP-EHR integration via SMART-on-FHIR, no real outcome-evaluation methodology with pre-registration, no measure registry curated by clinical informatics, no actual cohort-aware fairness instrumentation. Think of it as the sketchpad version: useful for understanding the shape of a care-gap recommender that respects clinical urgency, visit context, and multi-source closure tracking, not something you'd wire into a 400,000-member health plan on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the six pseudocode steps from the main recipe: evaluate the measure registry against patient data to produce open-gap lists with a state machine (open / provisionally_closed / confirmed_closed / reopened / excluded), score clinical urgency and per-pathway engagement and closure probability and synthesize priority, rank gaps for tomorrow's encounters with visit-fit filtering and LLM-generated clinician briefings, orchestrate asynchronous closures across heterogeneous pathways (patient-driven pharmacy, home test kits, specialist referrals, chase-team calls, PCP inbox), track closures from multiple sources with canonical-source rules, and capture clinician overrides as structured retraining signals. All sample patients, measures, gaps, schedules, and engagement events are synthetic.

---

## Setup

You'll need the AWS SDK for Python and a couple of utility libraries:

```bash
pip install boto3 pandas numpy
```

For the local urgency-model experimentation (training scripts not shown in the inference path) you'd add `xgboost` or `lightgbm`. The inference path itself only needs the SageMaker Batch Transform output, so the production Lambdas don't import those libraries.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `sagemaker:CreateTransformJob`, `sagemaker:DescribeTransformJob` on specific model ARNs (the per-gap-type clinical urgency models, per-pathway engagement and closure-probability models)
- `sagemaker:GetRecord`, `sagemaker:BatchGetRecord`, `sagemaker:PutRecord` on the SageMaker Feature Store feature group ARNs (`patient-gap-features`, `patient-profile-features`)
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchWriteItem` on the measure-registry, patient-gaps, patient-profile, recommendation-log, clinician-briefings, clinician-overrides, and clinical-informatics-review-queue tables
- `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on the gap-data-lake, feature-store-offline, evaluation-output, and closure-event-lake buckets
- `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults` for the gap-evaluation pipeline
- `glue:GetTable`, `glue:GetPartitions` on the data-catalog tables Athena reads
- `bedrock:InvokeModel` on the specific model ARNs used for candidate-gap surfacing, clinician briefings, and patient-facing message tailoring (e.g., a Claude Haiku or Nova Lite model)
- `kinesis:PutRecord` on the closure-and-engagement stream
- `ses:SendEmail` scoped to the BAA-covered identity (or `pinpoint:SendMessages` for SMS)
- `connect:StartOutboundContact` (only if using Amazon Connect for in-house chase team), scoped to the chase-queue contact flow
- `cloudwatch:PutMetricData` for cohort-sliced metrics
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs

You also need model access enabled in the Bedrock console for the candidate-gap surfacer, clinician-briefing, and patient-message-tailoring models.

A few things worth knowing upfront:

- **The measure registry is the source of truth for what counts as a gap, and it has to be curated.** This example ships with a small synthetic registry of 5 measures across HEDIS and patient-specific patterns. Production needs structured change management with clinical informatics review, parallel evaluation against the prior measure version on a sample, and ongoing reconciliation against your HEDIS vendor's official numbers. Without that, the recommender's gap counts will diverge from the plan's reported HEDIS performance and credibility burns.
- **The closure tracker is the part most teams skip and the part that makes or breaks operator trust.** This example wires the multi-source reconciliation with canonical-source rules per measure. The chase team should never call a patient about a colonoscopy they had last week; the suppression of in-flight outreach on closure-event arrival is what makes that work.
- **The clinical urgency model is the second-hardest part.** Production-grade urgency estimation requires longitudinal outcome data with confounding adjustment (the patients who close their gaps differ from the patients who don't). The training script is out of scope for this companion; the main recipe's "Why This Isn't Production-Ready" section walks through the gap. The example uses a rule-based proxy.
- **Bedrock model IDs change over time.** Some regions require cross-region inference profile IDs (prefixed `us.` or `eu.`). The IDs below are reasonable defaults; verify in the Bedrock console for your region before running.
- **All patients, measures, gaps, schedules, and engagement events in the example are synthetic.** Do not treat any specific patient_id, measure_id, evidence event, or closure event as real. A production system ingests from real claims, EHR, lab, pharmacy, and immunization-registry feeds under BAA.
- **The example collapses Step Functions, Glue, Athena, and SageMaker Batch Transform into a single Python file for readability.** In production these are separate workflow stages with their own error handling, IAM, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, table names, S3 buckets, allocator policy weights, equity floors, contact-frequency caps, suppression policies, and tracked measure types are the knobs you'll change between environments.

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
# CloudWatch Logs Insights. Never log a raw (patient_id, measure_id,
# state, urgency_score) join along with clinical context; the row
# implicitly identifies both the condition and the suspected risk.
# The patient-gaps table and the clinician-briefings table are highly
# inferential PHI.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from SageMaker, DynamoDB, Bedrock,
# Kinesis, S3, Athena, and SES during the daily evaluation and
# pre-visit ranking runs. Care-gap pipelines are bursty: nightly batch
# evaluation, then a smaller pre-visit ranking run the next morning.
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
# Three distinct LLM use cases, each wired to a small/fast model.
# Haiku-class hits the cost target at scale; larger frontier models
# add cost without meaningfully better tailoring on these prompt
# shapes. Production picks the model per use case based on observed
# quality regressions, not a uniform default.
CANDIDATE_GAP_MODEL_ID       = "anthropic.claude-3-5-haiku-20241022-v1:0"
CLINICIAN_BRIEFING_MODEL_ID  = "anthropic.claude-3-5-haiku-20241022-v1:0"
MESSAGE_MODEL_ID             = "anthropic.claude-3-5-haiku-20241022-v1:0"
CHASE_BRIEF_MODEL_ID         = "anthropic.claude-3-5-haiku-20241022-v1:0"

# Names of the SageMaker model artifacts. The urgency model is
# per-gap-type because the clinical risk dynamics for an overdue
# colonoscopy differ enough from an overdue flu shot that one model
# per gap-family produces better calibration. Engagement and closure
# probabilities are per-pathway (a pharmacy nudge's signature is not
# the same as a specialist referral's signature).
URGENCY_MODEL_NAMES = {
    "hedis-eed":                       "urgency-eye-exam-v3",
    "hedis-cdc-foot-exam":             "urgency-foot-exam-v2",
    "uspstf-colorectal-screening":     "urgency-colorectal-v4",
    "cdc-pneumococcal-65plus":         "urgency-pneumococcal-v2",
    "ada-uacr-annual-diabetes":        "urgency-uacr-v2",
}
ENGAGEMENT_MODEL_NAMES = {
    "in_visit":                  "engagement-in-visit-v3",
    "patient_driven_pharmacy":   "engagement-pharmacy-v3",
    "patient_driven_home_kit":   "engagement-home-kit-v2",
    "specialist_referral":       "engagement-referral-v3",
    "chase_team_call":           "engagement-chase-call-v2",
    "asynchronous_pcp_inbox":    "engagement-pcp-inbox-v1",
}

# --- DynamoDB Table Names ---
# Seven tables. Keep them separate so access patterns stay clean and
# IAM scoping is precise:
#   1. measure-registry:                canonical measure definitions
#                                       (measure_id + version PK)
#   2. patient-gaps:                    per-(patient, measure) state
#                                       machine (patient_id + measure_id PK)
#   3. patient-profile:                 member demographics, prefs,
#                                       cohort attributes (patient_id PK)
#   4. recommendation-log:              per (patient, measure, run_date)
#                                       allocation row
#   5. clinician-briefings:             per-encounter LLM-generated
#                                       briefings (briefing_id PK)
#   6. clinician-overrides:             override audit trail
#                                       (override_id PK)
#   7. clinical-informatics-review-queue: candidate-gap surfacer output
MEASURE_REGISTRY_TABLE                = "measure-registry"
PATIENT_GAPS_TABLE                    = "patient-gaps"
PATIENT_PROFILE_TABLE                 = "patient-profile"
RECOMMENDATION_LOG_TABLE              = "recommendation-log"
CLINICIAN_BRIEFINGS_TABLE             = "clinician-briefings"
CLINICIAN_OVERRIDES_TABLE             = "clinician-overrides"
CLINICAL_INFORMATICS_REVIEW_QUEUE     = "clinical-informatics-review-queue"

# --- S3 Buckets ---
# Production: each bucket has its own KMS key and bucket policy.
# Replace placeholder names with your account's buckets.
GAP_DATA_LAKE_BUCKET           = "gap-recommender-data-lake"
EVALUATION_OUTPUT_BUCKET       = "gap-recommender-evaluation"
SCORES_BUCKET                  = "gap-recommender-scores"
FEATURE_STORE_OFFLINE_BUCKET   = "gap-recommender-feature-store-offline"
ATHENA_RESULTS_BUCKET          = "gap-recommender-athena-results"

# --- Athena ---
ATHENA_WORKGROUP = "gap-recommender"
ATHENA_DATABASE  = "gap_data_lake"

# --- Kinesis ---
# Closure-and-engagement stream pattern reused from Recipes 4.1-4.5,
# with new event types: gap_identified, gap_provisionally_closed,
# gap_confirmed_closed, gap_reopened, gap_excluded,
# gap_referral_scheduled, gap_referral_completed,
# gap_surfaced_at_visit, gap_surfaced_for_outreach,
# clinician_override_recorded, patient_self_report_received.
CLOSURE_STREAM_NAME = "closure-and-engagement-stream"

# --- SES ---
SES_FROM_ADDRESS         = "carecoordination@example-health-plan.org"
SES_CONFIGURATION_SET    = "gap-recommender-baa"

# --- Tracked Closure Pathways ---
# Each gap has one or more compatible pathways; each pathway has
# its own engagement / closure-probability profile.
TRACKED_PATHWAYS = [
    "in_visit",                   # in-office foot exam, vaccine, BP, etc.
    "patient_driven_pharmacy",    # vaccinations, certain screenings
    "patient_driven_home_kit",    # FIT, A1c home tests
    "specialist_referral",        # colonoscopy, retinal exam, mammogram
    "chase_team_call",            # high-touch outreach
    "asynchronous_pcp_inbox",     # PCP order without visit (e.g., UACR)
]

# --- Run Configuration ---
POLICY_VERSION = "gap-policy-v0.4"

# Policy weights for priority synthesis. Documented and version-
# controlled. The window-urgency weight has a hard cap (see
# orchestrator) so year-end push doesn't swamp clinical urgency.
POLICY_WEIGHTS = {
    "clinical_urgency":     0.40,
    "closure_probability":  0.20,
    "measure_value":        0.20,
    "window_urgency":       0.20,
}

# Visit-fit thresholds.
PREVENTIVE_TIME_SHARE                 = 0.60   # fraction of visit reserved for preventive
MIN_VISIT_COMPATIBILITY_FOR_AGENDA    = 0.35
MAX_AGENDA_ITEMS_PER_VISIT            = 5

# Per-patient caps. Shared with Recipes 4.1, 4.2, 4.4, 4.5.
MAX_GAPS_PER_PATIENT_PER_RUN          = 3
MAX_TOTAL_CONTACTS_PER_PATIENT_30D    = 3

# Async visit-defer horizon: don't queue async outreach for gaps
# that may close at an upcoming visit within this many days.
ASYNC_VISIT_HORIZON_DAYS              = 14

# Suppression policies tied to clinician-override reasons.
# Production: each policy has a more nuanced exception structure
# (e.g., a new abnormal lab reopens a previously-declined gap).
SUPPRESSION_BY_REASON = {
    "appropriate_decline":                     {"days": 90},
    "previously_addressed_outside_record":     {"days": 180,
                                                "mark_provisional": True},
    "clinical_judgment_defer":                 {"days": 30},
    "patient_refusal":                         {"days": 180},
    "out_of_scope_for_visit":                  {"days": 0},   # async only
    "exclusion_documented":                    {"days": 365,
                                                "mark_excluded": True},
    "other":                                   {"days": 60},
}

# Allowed override reasons. Anything else is a malformed event.
ALLOWED_OVERRIDE_REASONS = list(SUPPRESSION_BY_REASON.keys())

# Allowed gap states.
ALLOWED_GAP_STATES = [
    "open", "provisionally_closed", "confirmed_closed",
    "reopened", "excluded",
]

# CloudWatch namespace for care-gap metrics. Slice by measure_id,
# pathway, language, engagement-history quartile, and SDOH cohort
# to catch subgroup drift.
METRIC_NAMESPACE = "GapRecommender"
```

---

## Reference Data: Synthetic Measure Registry and Equity Floors

A small measure registry used by the example. Production loads from the `measure-registry` DynamoDB table, fed by clinical informatics through a governance UI and versioned. Each measure has structured denominator / numerator / exclusion logic, lookback windows, canonical sources, supported closure pathways, and an `urgency_baseline` reflecting the program's clinical-importance judgment.

```python
# Synthetic measure registry. In production this lives in DynamoDB
# and is updated by the registry-sync Lambda when clinical
# informatics pushes registry changes through EventBridge. Each
# measure entry is the source of truth for what counts as a gap
# of this type.
SAMPLE_MEASURE_REGISTRY = [
    {
        "measure_id":            "hedis-eed",
        "version":               "2026-v1",
        "display_name":          "HEDIS Eye Exam for Patients with Diabetes (EED)",
        "denominator_logic": {
            "age_min":                  18,
            "age_max":                  75,
            "required_conditions":      ["diabetes_type_1", "diabetes_type_2"],
            "continuous_enrollment_months": 11,
        },
        "numerator_lookback_days":  365,
        "denominator_lookback_days": 365,
        "exclusion_codes":           ["palliative_care", "hospice"],
        "canonical_source":          "claims",
        "secondary_sources":         ["ehr"],
        "supported_pathways":        ["specialist_referral", "in_visit"],
        "urgency_baseline":          0.45,
        "measure_value":             0.85,    # high-bonus HEDIS Stars measure
        "is_hedis":                  True,
        "is_stars_bonus":            True,
        "effective_start":           "2026-01-01",
        "effective_end":             "2026-12-31",
    },
    {
        "measure_id":            "hedis-cdc-foot-exam",
        "version":               "2026-v1",
        "display_name":          "HEDIS CDC Foot Exam (Diabetic)",
        "denominator_logic": {
            "age_min":                  18,
            "age_max":                  75,
            "required_conditions":      ["diabetes_type_1", "diabetes_type_2"],
            "continuous_enrollment_months": 11,
        },
        "numerator_lookback_days":  365,
        "denominator_lookback_days": 365,
        "exclusion_codes":           ["palliative_care", "hospice", "amputation"],
        "canonical_source":          "ehr",
        "secondary_sources":         ["claims"],
        "supported_pathways":        ["in_visit"],
        "urgency_baseline":          0.40,
        "measure_value":             0.55,
        "is_hedis":                  True,
        "is_stars_bonus":            False,
        "effective_start":           "2026-01-01",
        "effective_end":             "2026-12-31",
    },
    {
        "measure_id":            "uspstf-colorectal-screening",
        "version":               "2026-v1",
        "display_name":          "USPSTF Colorectal Cancer Screening",
        "denominator_logic": {
            "age_min":                  45,
            "age_max":                  75,
            "required_conditions":      [],
            "continuous_enrollment_months": 11,
        },
        "numerator_lookback_days":  3650,    # colonoscopy: 10 years if normal
        "denominator_lookback_days": 365,
        "exclusion_codes":           ["palliative_care", "hospice",
                                       "colorectal_cancer_history",
                                       "total_colectomy"],
        "canonical_source":          "claims",
        "secondary_sources":         ["ehr", "patient_self_report"],
        "supported_pathways":        ["specialist_referral",
                                       "patient_driven_home_kit"],
        "urgency_baseline":          0.55,
        "measure_value":             0.60,
        "is_hedis":                  True,
        "is_stars_bonus":            False,
        "effective_start":           "2026-01-01",
        "effective_end":             "2026-12-31",
    },
    {
        "measure_id":            "cdc-pneumococcal-65plus",
        "version":               "2026-v1",
        "display_name":          "CDC Pneumococcal Vaccine (65+)",
        "denominator_logic": {
            "age_min":                  65,
            "age_max":                  120,
            "required_conditions":      [],
            "continuous_enrollment_months": 6,
        },
        "numerator_lookback_days":  3650,    # lifetime measure for most adults
        "denominator_lookback_days": 365,
        "exclusion_codes":           ["palliative_care", "hospice"],
        "canonical_source":          "immunization_registry",
        "secondary_sources":         ["claims", "pharmacy", "ehr"],
        "supported_pathways":        ["patient_driven_pharmacy", "in_visit"],
        "urgency_baseline":          0.35,
        "measure_value":             0.45,
        "is_hedis":                  False,
        "is_stars_bonus":            False,
        "effective_start":           "2026-01-01",
        "effective_end":             "2026-12-31",
    },
    {
        "measure_id":            "ada-uacr-annual-diabetes",
        "version":               "2026-v1",
        "display_name":          "ADA Annual UACR for Diabetic Patients",
        "denominator_logic": {
            "age_min":                  18,
            "age_max":                  120,
            "required_conditions":      ["diabetes_type_1", "diabetes_type_2"],
            "continuous_enrollment_months": 11,
        },
        "numerator_lookback_days":  365,
        "denominator_lookback_days": 365,
        "exclusion_codes":           ["palliative_care", "hospice",
                                       "dialysis_dependent"],
        "canonical_source":          "lab",
        "secondary_sources":         ["ehr", "claims"],
        "supported_pathways":        ["asynchronous_pcp_inbox", "in_visit"],
        "urgency_baseline":          0.50,
        "measure_value":             0.30,    # ACO/contracted, not big HEDIS
        "is_hedis":                  False,
        "is_stars_bonus":            False,
        "effective_start":           "2026-01-01",
        "effective_end":             "2026-12-31",
    },
]

# Per-pathway typical time costs and visit-type compatibility.
# Production: lives in a config table maintained alongside the
# measure registry. The example codes the most common cases.
PATHWAY_PROFILES = {
    "in_visit": {
        "time_cost_minutes":          5,
        "visit_type_compatibility": {
            "annual_visit": 1.0, "follow_up": 0.7,
            "sick_visit": 0.3, "telehealth": 0.4,
        },
        "generates_patient_contact":  False,
        "completion_conditional_on_engagement": 0.85,
    },
    "patient_driven_pharmacy": {
        "time_cost_minutes":          0,
        "visit_type_compatibility": {
            "annual_visit": 0.0, "follow_up": 0.0,
            "sick_visit": 0.0, "telehealth": 0.0,
        },
        "generates_patient_contact":  True,
        "completion_conditional_on_engagement": 0.55,
    },
    "patient_driven_home_kit": {
        "time_cost_minutes":          0,
        "visit_type_compatibility": {
            "annual_visit": 0.0, "follow_up": 0.0,
            "sick_visit": 0.0, "telehealth": 0.0,
        },
        "generates_patient_contact":  True,
        "completion_conditional_on_engagement": 0.40,
    },
    "specialist_referral": {
        "time_cost_minutes":          2,    # the visit minute is the order
        "visit_type_compatibility": {
            "annual_visit": 0.6, "follow_up": 0.5,
            "sick_visit": 0.2, "telehealth": 0.4,
        },
        "generates_patient_contact":  True,
        "completion_conditional_on_engagement": 0.45,
    },
    "chase_team_call": {
        "time_cost_minutes":          0,
        "visit_type_compatibility": {
            "annual_visit": 0.0, "follow_up": 0.0,
            "sick_visit": 0.0, "telehealth": 0.0,
        },
        "generates_patient_contact":  True,
        "completion_conditional_on_engagement": 0.35,
    },
    "asynchronous_pcp_inbox": {
        "time_cost_minutes":          0,
        "visit_type_compatibility": {
            "annual_visit": 0.4, "follow_up": 0.4,
            "sick_visit": 0.1, "telehealth": 0.3,
        },
        "generates_patient_contact":  False,
        "completion_conditional_on_engagement": 0.70,
    },
}

# Per-pathway daily capacity. Reminder/pharmacy capacity is
# essentially unbounded; chase-team and cost-assistance navigation
# is bounded by FTE.
PATHWAY_CAPACITY = {
    "in_visit":                 50000,    # bounded by visit volume itself
    "patient_driven_pharmacy":  50000,
    "patient_driven_home_kit":   3000,    # kit fulfillment capacity
    "specialist_referral":       2000,    # referral-management throughput
    "chase_team_call":            120,    # 6 FTE * 20 calls/day
    "asynchronous_pcp_inbox":    1500,
}

# Equity floors per pathway. The orchestrator reserves capacity for
# cohorts with documented closure-rate disparities. Conservative
# starting values; production tunes against the equity dashboard.
EQUITY_FLOORS = {
    "chase_team_call": {
        "engagement_q1":           20,
        "language_non_en":         15,
        "sdoh_low_food_security":  15,
    },
    "specialist_referral": {
        "language_non_en":         100,
        "sdoh_transportation_barrier": 80,
    },
    "patient_driven_home_kit": {
        "language_non_en":         200,
    },
    # in_visit, patient_driven_pharmacy, asynchronous_pcp_inbox:
    # no equity floor in this example. Production may add floors
    # as observed disparities emerge.
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

def _make_tracking_id(run_date: str, patient_id: str,
                      measure_id: str, pathway: str) -> str:
    """
    Tracking_id used to join recommendation -> outreach -> closure event.

    NOTE: This example uses a readable string for clarity. Production
    must replace this with an opaque, non-reversible identifier (UUID
    or HMAC over the composite). Plain-text patient_ids and
    measure_ids embedded in tracking IDs (carried in email
    open-tracking pixels, SMS click-through links, EHR inbox URLs)
    are PHI leakage. The "Gap to Production" section at the end of
    this file flags the same issue.
    """
    return f"gap-{run_date}-{patient_id}-{measure_id}-{pathway}"

def _make_briefing_id(encounter: dict, run_date: str) -> str:
    """Same caveat as _make_tracking_id. Replace with opaque ID in production."""
    return (
        f"brief-{run_date}-{encounter['provider_id']}-{encounter['patient_id']}"
    )

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
    Strip patient/provider identifiers from a list of gap rows before
    sending to an LLM. The LLM doesn't need them, and stripping at the
    boundary limits any vendor-side logging exposure (Bedrock service
    terms commit to not training on prompts, but defense-in-depth
    still applies).
    """
    redacted = []
    for item in items:
        copy = dict(item)
        for field in ("patient_id", "provider_id", "evidence",
                      "tracking_id", "encounter_time"):
            copy.pop(field, None)
        redacted.append(copy)
    return redacted
```

---

## Step 1: Evaluate the Measure Registry to Produce Open-Gap Lists

*The pseudocode calls this `evaluate_measures(patients, run_date)`. For each active measure in the registry, evaluate denominator membership, numerator satisfaction, and exclusion criteria using the canonical source the registry specifies. Maintain a per-(patient, measure) state machine: open, provisionally_closed, confirmed_closed, reopened, excluded. Skip the registry abstraction and you end up hard-coding measure logic that becomes a maintenance disaster when measure specifications change annually.*

```python
def evaluate_measures(patients: list, run_date: str) -> list:
    """
    Run the daily gap-evaluation pipeline.

    Returns a list of state transitions for downstream stages
    (enrichment, ranking) to consume. Persists per-(patient, measure)
    state to the patient-gaps table.
    """
    active_measures = _load_active_measures(run_date)
    logger.info(
        "Evaluating %d active measures against %d patients for run_date=%s",
        len(active_measures), len(patients), run_date,
    )

    transitions = []
    gaps_table = dynamodb.Table(PATIENT_GAPS_TABLE)

    for measure in active_measures:
        # Step 1A: denominator. Production: an Athena query template
        # parameterized over the registry's denominator predicates.
        # The example uses an in-memory filter so the demo runs offline.
        denominator = _evaluate_denominator(patients, measure, run_date)

        # Step 1B: numerator. Look for qualifying events in the
        # canonical source within the numerator lookback. Production:
        # an Athena query against the source-specific table partitioned
        # by patient_id and event_date.
        qualifying_events = _evaluate_numerator(denominator, measure, run_date)

        # Step 1C: exclusions. Categorical (palliative_care, hospice)
        # and conditional (pregnancy excludes some measures, dialysis
        # excludes UACR, etc.).
        excluded = _evaluate_exclusions(denominator, measure, run_date)

        # Step 1D: state determination per patient.
        for patient_id in denominator:
            new_state, evidence = _determine_state(
                patient_id, qualifying_events, excluded, measure,
            )

            previous_state = _read_previous_state(
                gaps_table, patient_id, measure["measure_id"],
            )

            transition_event = _compute_transition(
                previous_state, new_state, measure, run_date,
            )

            window_open, window_close = _compute_measure_window(
                measure, patient_id, run_date,
            )

            data_quality_flag = _assess_source_completeness(
                patient_id, measure, evidence,
            )

            record = {
                "patient_id":           patient_id,
                "measure_id":           measure["measure_id"],
                "measure_version":      measure["version"],
                "state":                new_state,
                "state_history":        previous_state.get("state_history", []) + [{
                    "event":     transition_event,
                    "timestamp": run_date,
                    "evidence":  evidence,
                }],
                "current_window_open":  window_open,
                "current_window_close": window_close,
                "evidence":             evidence,
                "canonical_source":     measure["canonical_source"],
                "data_quality_flag":    data_quality_flag,
                "last_evaluation_date": run_date,
            }

            try:
                gaps_table.put_item(Item=_to_decimal_dict(record))
            except Exception as exc:
                logger.warning(
                    "Failed to persist gap state for %s/%s: %s",
                    patient_id, measure["measure_id"], exc,
                )

            transitions.append({
                "patient_id":     patient_id,
                "measure_id":     measure["measure_id"],
                "previous_state": previous_state.get("state"),
                "new_state":      new_state,
                "transition":     transition_event,
            })

    logger.info(
        "Gap evaluation produced %d (patient, measure) state records",
        len(transitions),
    )
    return transitions

def _load_active_measures(run_date: str) -> list:
    """
    Load every active measure version from the registry. The registry
    is the source of truth; engineering doesn't hard-code measure
    logic. New measures or annual revisions land as new registry
    versions.
    """
    registry_table = dynamodb.Table(MEASURE_REGISTRY_TABLE)
    try:
        response = registry_table.scan()
        active = []
        for item in response.get("Items", []):
            item = _from_decimal(item)
            if (item["effective_start"] <= run_date <= item["effective_end"]):
                active.append(item)
        return active
    except Exception:
        # Offline demo path: fall back to the synthetic registry.
        return [m for m in SAMPLE_MEASURE_REGISTRY
                if m["effective_start"] <= run_date <= m["effective_end"]]

def _evaluate_denominator(patients: list, measure: dict, run_date: str) -> list:
    """
    Determine which patients are in this measure's denominator as of
    run_date. Production: SQL against a normalized claims+EHR view.
    The example uses an in-memory filter.
    """
    logic = measure["denominator_logic"]
    eligible = []
    for patient in patients:
        # Age check.
        age = patient.get("age", 0)
        if age < logic["age_min"] or age > logic["age_max"]:
            continue

        # Required-condition check. Patient must have at least one of
        # the required conditions on the active problem list.
        required = set(logic.get("required_conditions", []))
        patient_conditions = set(patient.get("active_conditions", []))
        if required and not (required & patient_conditions):
            continue

        # Continuous-enrollment check. Production: pull from the
        # eligibility/enrollment data; the example uses a flag.
        if (logic.get("continuous_enrollment_months", 0) > 0
            and not patient.get("continuously_enrolled", True)):
            continue

        eligible.append(patient["patient_id"])
    return eligible

def _evaluate_numerator(denominator: list, measure: dict, run_date: str) -> dict:
    """
    For each denominator-eligible patient, check whether a qualifying
    event exists in the canonical source within the numerator
    lookback. Returns dict[patient_id] -> {event_payload, source}.

    Production: Athena query against the canonical-source table
    using the measure's numerator value set; secondary sources
    are evaluated only when the canonical source has no event.
    """
    # Demo path: read from globals._DEMO_QUALIFYING_EVENTS so the
    # runner can inject synthetic events.
    found = {}
    canonical = measure["canonical_source"]
    secondary = measure.get("secondary_sources", [])
    measure_id = measure["measure_id"]

    for patient_id in denominator:
        # Check canonical source first.
        canonical_event = _DEMO_QUALIFYING_EVENTS.get(
            (patient_id, measure_id, canonical)
        )
        if canonical_event:
            found[patient_id] = {
                "event":  canonical_event,
                "source": canonical,
            }
            continue

        # Fall back to secondary sources for provisional state.
        for src in secondary:
            secondary_event = _DEMO_QUALIFYING_EVENTS.get(
                (patient_id, measure_id, src)
            )
            if secondary_event:
                found[patient_id] = {
                    "event":  secondary_event,
                    "source": src,
                }
                break

    return found

def _evaluate_exclusions(denominator: list, measure: dict, run_date: str) -> set:
    """
    Apply measure-specific exclusion logic. Some patients are excluded
    categorically (palliative care, hospice); some are excluded
    conditionally (pregnancy excludes some screenings; dialysis
    excludes UACR).
    """
    excluded_codes = set(measure.get("exclusion_codes", []))
    excluded = set()
    for patient_id in denominator:
        patient_exclusions = _DEMO_EXCLUSION_FLAGS.get(patient_id, set())
        if patient_exclusions & excluded_codes:
            excluded.add(patient_id)
    return excluded

def _determine_state(patient_id: str, qualifying_events: dict,
                      excluded: set, measure: dict) -> tuple:
    """
    State determination logic from the pseudocode:
      - If excluded: state = excluded
      - If qualifying event from canonical source: state = confirmed_closed
      - If qualifying event from secondary source: state = provisionally_closed
      - Otherwise: state = open
    """
    if patient_id in excluded:
        return "excluded", None

    qe = qualifying_events.get(patient_id)
    if qe is None:
        return "open", None

    if qe["source"] == measure["canonical_source"]:
        return "confirmed_closed", qe
    return "provisionally_closed", qe

def _read_previous_state(gaps_table, patient_id: str, measure_id: str) -> dict:
    """Read the previous state record for this (patient, measure)."""
    try:
        response = gaps_table.get_item(
            Key={"patient_id": patient_id, "measure_id": measure_id}
        )
        return _from_decimal(response.get("Item") or {})
    except Exception:
        return {}

def _compute_transition(previous: dict, new_state: str,
                         measure: dict, run_date: str) -> str:
    """
    Determine the state-history event label.

    Special case: a confirmed_closed gap whose numerator window has
    rolled over reopens.
    """
    prev_state = previous.get("state")
    if prev_state is None:
        return f"initial_{new_state}"

    # Reopen detection: previously confirmed_closed, window has rolled
    # over, and this evaluation finds no qualifying event.
    prev_window_close = previous.get("current_window_close")
    if (prev_state == "confirmed_closed"
        and prev_window_close
        and prev_window_close < run_date
        and new_state == "open"):
        return "reopened"

    if prev_state == new_state:
        return "unchanged"

    return f"transitioned_{prev_state}_to_{new_state}"

def _compute_measure_window(measure: dict, patient_id: str,
                             run_date: str) -> tuple:
    """
    Compute the current measurement window for this (patient, measure).
    Most HEDIS measures use calendar-aligned years; some use
    rolling-year windows; some are lifetime measures.

    The example uses calendar-year alignment as a sane default; the
    registry should specify the windowing pattern in production.
    """
    year = int(run_date[:4])
    return f"{year}-01-01", f"{year}-12-31"

def _assess_source_completeness(patient_id: str, measure: dict,
                                 evidence) -> str:
    """
    Tag the (patient, measure) record with a data-quality flag that
    downstream consumers can gate on. A confidently "open" gap on a
    patient with `cross_provider_fragmentation` data quality is much
    less reliable than the same label on a patient with `complete`
    data quality.
    """
    if not evidence:
        # No evidence might mean genuinely no qualifying event, OR it
        # might mean the canonical source doesn't see the patient's
        # care because the patient gets care across multiple systems.
        fragmentation = _DEMO_FRAGMENTATION_FLAGS.get(patient_id, False)
        if fragmentation:
            return "cross_provider_fragmentation"
        history_count = _DEMO_HISTORY_COUNT.get(patient_id, 100)
        if history_count < 10:
            return "sparse_history"
        return "complete"

    # If we found evidence in a non-canonical source, flag the
    # multi-source disagreement as relevant context.
    canonical = measure["canonical_source"]
    if evidence["source"] != canonical:
        return "multi_source_disagreement"

    return "complete"

# Demo state populated by the runner at the bottom of this file. The
# production functions above replace these with real data feeds.
_DEMO_QUALIFYING_EVENTS: dict = {}
_DEMO_EXCLUSION_FLAGS: dict = {}
_DEMO_FRAGMENTATION_FLAGS: dict = {}
_DEMO_HISTORY_COUNT: dict = {}

def surface_candidate_gaps_via_llm(
    patients_subset: list, run_date: str,
) -> list:
    """
    Optional LLM-assisted candidate-gap surfacer. Run on a sampled or
    high-risk subset, not the full population. The output is a
    candidate queue for clinical informatics review, not a direct gap
    signal.

    Production gates this on a clinical-informatics review queue with
    explicit staffing; without staffing, the queue grows and the
    feature becomes shelfware.
    """
    review_queue_table = dynamodb.Table(CLINICAL_INFORMATICS_REVIEW_QUEUE)
    candidates_emitted = []

    for patient in patients_subset:
        chart_context = _build_chart_context(patient, lookback_days=730)
        try:
            candidates = _bedrock_candidate_gap_surface(chart_context)
        except Exception as exc:
            logger.warning(
                "Bedrock candidate-gap surfacer failed for %s: %s",
                patient["patient_id"], exc,
            )
            continue

        for candidate in candidates:
            if not _validate_candidate_gap(candidate, chart_context):
                logger.info(
                    "Candidate gap rejected by validator for %s: %s",
                    patient["patient_id"], candidate.get("candidate_gap_label"),
                )
                continue

            review_id = str(uuid.uuid4())
            try:
                review_queue_table.put_item(Item=_to_decimal_dict({
                    "review_id":     review_id,
                    "patient_id":    patient["patient_id"],
                    "candidate":     candidate,
                    "proposed_at":   _now_iso(),
                    "state":         "pending_review",
                    "run_date":      run_date,
                }))
                candidates_emitted.append({
                    "review_id":  review_id,
                    "patient_id": patient["patient_id"],
                    "candidate":  candidate,
                })
            except Exception as exc:
                logger.warning(
                    "Failed to enqueue candidate gap %s: %s", review_id, exc,
                )

    logger.info(
        "Candidate-gap surfacer emitted %d candidates for review",
        len(candidates_emitted),
    )
    return candidates_emitted

def _build_chart_context(patient: dict, lookback_days: int) -> dict:
    """
    Build a structured, de-identified chart context block for the LLM.
    Don't pass raw patient_id, name, or address; the LLM doesn't need
    them and stripping limits vendor-side logging exposure.
    """
    return {
        "age_band":              patient.get("age_band"),
        "active_conditions":     patient.get("active_conditions", []),
        "recent_lab_trends":     patient.get("recent_lab_trends", {}),
        "recent_encounter_summary": patient.get("recent_encounter_summary"),
        "current_medications":   patient.get("current_medications", []),
        "family_history_flags":  patient.get("family_history_flags", []),
    }

def _validate_candidate_gap(candidate: dict, observed_data: dict) -> bool:
    """
    Validate the LLM's candidate-gap output. Four layers:
      1. Schema check (required keys present, no extras)
      2. Rationale length (2-4 sentences, not boilerplate)
      3. Rationale must cite observable data points (the LLM cannot
         invent clinical history that isn't in observed_data)
      4. Prohibited content (no PHI invented, no prescriber names)
    Failure means the candidate is dropped and logged for prompt-
    engineering review.
    """
    required = {"candidate_gap_label", "rationale",
                "suggested_evidence_to_check", "confidence",
                "supporting_chart_excerpts"}
    if not isinstance(candidate, dict):
        return False
    if not required.issubset(candidate.keys()):
        return False

    rationale = candidate.get("rationale", "")
    if not isinstance(rationale, str) or len(rationale) < 30 or len(rationale) > 600:
        return False

    excerpts = candidate.get("supporting_chart_excerpts", [])
    if not isinstance(excerpts, list) or len(excerpts) == 0:
        return False

    # Each excerpt should reference a data point that appears in the
    # observed_data block. The example does a coarse substring check;
    # production uses a more rigorous matching function.
    observed_str = json.dumps(observed_data).lower()
    for excerpt in excerpts:
        if not isinstance(excerpt, str):
            return False
        # At least one keyword from the excerpt should appear in the
        # observed data block.
        keywords = [w for w in excerpt.lower().split() if len(w) > 4]
        if keywords and not any(kw in observed_str for kw in keywords[:3]):
            return False

    confidence = candidate.get("confidence")
    if confidence not in ("low", "moderate", "high"):
        return False

    return True

def _bedrock_candidate_gap_surface(chart_context: dict) -> list:
    """
    Invoke Bedrock to propose candidate gaps the deterministic
    registry might have missed. Returns a list of candidate dicts.
    Production: gate on clinical-informatics review queue staffing.
    """
    prompt = f"""You review a patient's chart context and propose clinical
gaps that the standard quality-measure registry might have missed.
You are a candidate generator, not a decision maker; the proposed
gaps go to clinical informatics review, never directly to the
clinician.

Allowed gap categories: chronic_disease_monitoring,
medication_titration, screening_overdue, condition_documentation,
follow_up_overdue.

Chart context (de-identified):
{json.dumps(chart_context, indent=2)}

Return ONLY valid JSON (no prose, no code fences) with this shape:
{{
  "candidates": [
    {{
      "candidate_gap_label":          "<short label>",
      "rationale":                    "<2-4 sentences citing observable data>",
      "suggested_evidence_to_check":  ["<specific code/test/event>"],
      "confidence":                   "<low | moderate | high>",
      "supporting_chart_excerpts":    ["<excerpt 1>", "<excerpt 2>"]
    }}
  ]
}}

Cite only signals from the Chart context block. Do not invent history.
Up to three candidates; fewer is fine.
"""
    response = bedrock_runtime.invoke_model(
        modelId=CANDIDATE_GAP_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        900,
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
    parsed = json.loads(match.group(0))
    return parsed.get("candidates", [])
```

---

## Step 2: Score Clinical Urgency, Engagement, and Synthesize Priority

*The pseudocode calls this `enrich_open_gaps(patient_gaps_today, run_date)`. Per-(patient, gap), produce a clinical urgency score (independent of quality-measure status), per-pathway engagement and closure-probability scores, and a synthesized priority. Skip the per-gap-type urgency modeling and you treat all gaps with the same urgency profile, which is the error David's PCP fell into when the dashboard sorted by HEDIS bonus value.*

```python
def enrich_open_gaps(run_date: str, patients: dict,
                     measure_lookup: dict) -> list:
    """
    Read open gaps from patient-gaps, score urgency and per-pathway
    engagement, synthesize priority, persist enriched record.

    patients:        dict[patient_id] -> patient profile
    measure_lookup:  dict[measure_id] -> measure registry entry

    Returns the enriched gap list for downstream stages (visit ranker,
    async orchestrator) to consume.
    """
    gaps_table = dynamodb.Table(PATIENT_GAPS_TABLE)
    open_gaps = _scan_open_gaps(gaps_table)
    logger.info("Enriching %d open gaps for run_date=%s", len(open_gaps), run_date)

    enriched = []
    for gap in open_gaps:
        patient_id = gap["patient_id"]
        measure_id = gap["measure_id"]
        measure = measure_lookup.get(measure_id)
        patient = patients.get(patient_id, {})

        if measure is None:
            logger.warning(
                "Gap references unknown measure_id=%s; skipping", measure_id,
            )
            continue

        # ---- Stage A: clinical urgency scoring ----
        # Production: SageMaker Batch Transform call to the per-gap-type
        # urgency model. The example uses a rule-based proxy that
        # combines the registry's urgency_baseline with patient-level
        # risk modifiers.
        urgency = _score_clinical_urgency(patient, gap, measure)

        # ---- Stage B: per-pathway engagement and closure probability ----
        per_pathway = {}
        for pathway in measure["supported_pathways"]:
            engagement_prob = _score_engagement(patient, gap, measure, pathway)
            pathway_profile = PATHWAY_PROFILES[pathway]
            closure_conditional = pathway_profile[
                "completion_conditional_on_engagement"
            ]
            closure_prob = engagement_prob * closure_conditional
            per_pathway[pathway] = {
                "engagement_prob":  round(engagement_prob, 4),
                "closure_prob":     round(closure_prob, 4),
            }

        # Pick the best pathway by closure probability. The orchestrator
        # may override based on visit context or pathway constraints,
        # but this is the default selection signal.
        best_pathway = max(per_pathway, key=lambda p: per_pathway[p]["closure_prob"])
        best_closure_prob = per_pathway[best_pathway]["closure_prob"]

        # ---- Stage C: priority synthesis ----
        measure_value = measure.get("measure_value", 0.0)
        window_urgency = _compute_window_urgency(gap, run_date)

        priority_components = {
            "urgency_contrib":       POLICY_WEIGHTS["clinical_urgency"]
                                     * urgency,
            "closure_prob_contrib":  POLICY_WEIGHTS["closure_probability"]
                                     * best_closure_prob,
            "measure_value_contrib": POLICY_WEIGHTS["measure_value"]
                                     * measure_value,
            "window_urgency_contrib": POLICY_WEIGHTS["window_urgency"]
                                     * window_urgency,
        }
        priority = round(sum(priority_components.values()), 4)
        priority_components = {
            k: round(v, 4) for k, v in priority_components.items()
        }

        cohort_features = _lookup_cohort_features_from_profile(patient)

        enriched_record = {
            **gap,
            "urgency_score":        round(urgency, 4),
            "per_pathway":          per_pathway,
            "best_pathway":         best_pathway,
            "best_closure_prob":    round(best_closure_prob, 4),
            "window_urgency":       round(window_urgency, 4),
            "priority":             priority,
            "priority_components":  priority_components,
            "cohort_features":      cohort_features,
            "policy_version":       POLICY_VERSION,
            "last_enrichment_date": run_date,
        }

        try:
            gaps_table.update_item(
                Key={"patient_id": patient_id, "measure_id": measure_id},
                UpdateExpression=(
                    "SET urgency_score = :u, per_pathway = :pp, "
                    "best_pathway = :bp, best_closure_prob = :bcp, "
                    "window_urgency = :wu, priority = :p, "
                    "priority_components = :pc, cohort_features = :cf, "
                    "policy_version = :pv, last_enrichment_date = :led"
                ),
                ExpressionAttributeValues=_to_decimal_dict({
                    ":u":   urgency,
                    ":pp":  per_pathway,
                    ":bp":  best_pathway,
                    ":bcp": best_closure_prob,
                    ":wu":  window_urgency,
                    ":p":   priority,
                    ":pc":  priority_components,
                    ":cf":  cohort_features,
                    ":pv":  POLICY_VERSION,
                    ":led": run_date,
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to update enriched gap for %s/%s: %s",
                patient_id, measure_id, exc,
            )

        enriched.append(enriched_record)

    logger.info("Enrichment computed priority for %d open gaps", len(enriched))
    return enriched

def _scan_open_gaps(gaps_table) -> list:
    """
    Production: Query a (state, run_date) GSI rather than a scan; this
    example uses a simple scan for the demo.
    """
    open_gaps = []
    try:
        response = gaps_table.scan()
        for item in response.get("Items", []):
            item = _from_decimal(item)
            if item.get("state") == "open":
                open_gaps.append(item)
    except Exception as exc:
        logger.warning("Scan of patient-gaps failed: %s", exc)
    return open_gaps

def _score_clinical_urgency(patient: dict, gap: dict, measure: dict) -> float:
    """
    Rule-based clinical urgency scoring. Production replaces with a
    per-gap-type SageMaker Batch Transform output.

    Output is a continuous urgency in [0, 1]: the expected clinical
    harm of delayed closure over the next 6-24 months.

    The rules below are illustrative. Real curation involves clinical
    informatics encoding family-history modifiers, lab-trend
    modifiers, comorbidity load adjustments, and SDOH factors that
    affect closure feasibility (a high-urgency gap with a transport
    barrier is still high-urgency clinically; the closure probability
    is what reflects feasibility).
    """
    urgency = float(measure.get("urgency_baseline", 0.4))
    measure_id = measure["measure_id"]

    # Family history modifiers for cancer-screening measures.
    family_flags = patient.get("family_history_flags", [])
    if measure_id == "uspstf-colorectal-screening":
        if "first_degree_colon_cancer" in family_flags:
            urgency = min(1.0, urgency + 0.30)

    # Lab-trend modifiers. UACR urgency rises sharply when eGFR is
    # falling and there's no documented CKD conversation.
    lab_trends = patient.get("recent_lab_trends", {})
    if measure_id == "ada-uacr-annual-diabetes":
        egfr_drop = lab_trends.get("egfr_change_24mo", 0)
        if egfr_drop <= -10:
            urgency = min(1.0, urgency + 0.30)

    # Comorbidity load: a patient with multiple complications has
    # higher urgency on diabetes-related gaps.
    if measure_id in {"hedis-eed", "hedis-cdc-foot-exam"}:
        a1c = lab_trends.get("a1c_recent")
        if a1c and a1c >= 8.0:
            urgency = min(1.0, urgency + 0.15)

    # Age modifier for vaccinations.
    if measure_id == "cdc-pneumococcal-65plus":
        if patient.get("age", 0) >= 75:
            urgency = min(1.0, urgency + 0.15)

    return urgency

def _score_engagement(patient: dict, gap: dict, measure: dict,
                       pathway: str) -> float:
    """
    Rule-based engagement-probability scoring. Production: SageMaker
    Batch Transform call to the per-pathway engagement model.

    Returns the probability that the patient takes the action this
    pathway requires (fills the prescription, attends the referral,
    answers the chase call, completes the home test kit).
    """
    base = {
        "in_visit":                  0.75,
        "patient_driven_pharmacy":   0.45,
        "patient_driven_home_kit":   0.30,
        "specialist_referral":       0.55,
        "chase_team_call":           0.40,
        "asynchronous_pcp_inbox":    0.65,
    }.get(pathway, 0.4)

    # Engagement-history modifier.
    quartile = patient.get("engagement_history_quartile", "q3")
    quartile_adj = {"q1": -0.15, "q2": -0.05, "q3": 0.0, "q4": 0.10}.get(
        quartile, 0.0,
    )

    # Language match: the language-aware pathway implementations
    # account for this; here we model a small penalty when the
    # patient's language isn't English.
    if patient.get("preferred_language", "en") != "en":
        # Penalty only for pathways that don't have great non-English
        # support yet; chase team has bilingual agents.
        if pathway in {"patient_driven_home_kit", "patient_driven_pharmacy"}:
            quartile_adj -= 0.05

    # SDOH modifier for referral pathways.
    if pathway == "specialist_referral":
        if patient.get("sdoh_cohort") == "transportation_barrier":
            quartile_adj -= 0.20

    return max(0.05, min(0.95, base + quartile_adj))

def _compute_window_urgency(gap: dict, run_date: str) -> float:
    """
    Time pressure from the measure's closing window. A gap that closes
    in 30 days has higher window urgency than the same gap with 8
    months left.

    The math: urgency rises sharply as the window closes. We use a
    simple piecewise-linear function; production may use a steeper
    curve near the deadline (annual chase periods).
    """
    window_close_str = gap.get("current_window_close")
    if not window_close_str:
        return 0.0
    try:
        window_close = datetime.date.fromisoformat(window_close_str)
        run = datetime.date.fromisoformat(run_date)
        days_remaining = (window_close - run).days
    except Exception:
        return 0.0

    if days_remaining < 0:
        return 1.0    # already past the window
    if days_remaining <= 30:
        return 0.90
    if days_remaining <= 90:
        return 0.65
    if days_remaining <= 180:
        return 0.40
    return 0.15

def _lookup_cohort_features_from_profile(patient: dict) -> dict:
    """Pull cohort features from the patient profile."""
    return {
        "engagement_history_quartile": patient.get(
            "engagement_history_quartile", "q3"),
        "language":                    patient.get("preferred_language", "en"),
        "sdoh_cohort":                 patient.get("sdoh_cohort"),
        "age_band":                    patient.get("age_band"),
    }
```

---

## Step 3: Visit-Context Ranking for Tomorrow's Encounters

*The pseudocode calls this `rank_visit_agendas(next_day_schedule, run_date)`. Consume the next-day schedule, look up each scheduled patient's enriched gap list, filter to gaps with closure pathways compatible with the visit type and visit time, and produce a per-encounter ranked agenda. Generate an LLM briefing the clinician can read in three seconds. Skip the visit-fit filter and you put a colonoscopy referral on a 15-minute sick visit's agenda, which is a useless recommendation.*

```python
def rank_visit_agendas(next_day_schedule: list, run_date: str,
                       enriched_gaps: list, patients: dict) -> list:
    """
    For each encounter on next_day_schedule, build a ranked agenda
    from the patient's enriched open gaps. Generate a clinician
    briefing via Bedrock. Persist briefings to DynamoDB for the
    EHR-inbox push.
    """
    briefings_table = dynamodb.Table(CLINICIAN_BRIEFINGS_TABLE)
    visit_agendas = []

    # Index enriched gaps by patient_id for quick lookup.
    gaps_by_patient: dict = {}
    for gap in enriched_gaps:
        gaps_by_patient.setdefault(gap["patient_id"], []).append(gap)

    for encounter in next_day_schedule:
        patient_id = encounter["patient_id"]
        visit_type = encounter.get("visit_type", "follow_up")
        visit_minutes = encounter.get("visit_minutes", 25)
        provider = {
            "provider_id":    encounter["provider_id"],
            "provider_name":  encounter.get("provider_name"),
        }
        acute_context = encounter.get("acute_context", {})

        patient_gaps = gaps_by_patient.get(patient_id, [])
        if not patient_gaps:
            continue

        # Score visit-fit per gap: how compatible is the gap's best
        # pathway with this specific visit?
        ranked_for_visit = []
        for gap in patient_gaps:
            visit_fit = _compute_visit_fit(
                gap, visit_type, visit_minutes, provider, acute_context,
            )

            adjusted_priority = (
                gap["priority"]
                * visit_fit["pathway_compatibility"]
                * visit_fit["time_cost_factor"]
                * (1 - visit_fit["acute_displacement"])
            )

            ranked_for_visit.append({
                "gap":               gap,
                "adjusted_priority": adjusted_priority,
                "visit_fit":         visit_fit,
            })

        ranked_for_visit.sort(
            key=lambda x: x["adjusted_priority"], reverse=True,
        )

        # Build the in-visit agenda subject to size and time-budget caps.
        in_visit_agenda = []
        cumulative_minutes = 0
        in_visit_budget = visit_minutes * PREVENTIVE_TIME_SHARE

        for row in ranked_for_visit:
            if len(in_visit_agenda) >= MAX_AGENDA_ITEMS_PER_VISIT:
                break
            if (row["visit_fit"]["pathway_compatibility"]
                < MIN_VISIT_COMPATIBILITY_FOR_AGENDA):
                continue
            if (cumulative_minutes
                + row["visit_fit"]["time_cost_minutes"] > in_visit_budget):
                continue
            in_visit_agenda.append(row)
            cumulative_minutes += row["visit_fit"]["time_cost_minutes"]

        # Everything else flows to the async closure queue.
        async_queue = [
            r for r in ranked_for_visit if r not in in_visit_agenda
        ]

        # Generate the clinician briefing.
        briefing_parsed = _generate_clinician_briefing(
            encounter, in_visit_agenda, async_queue,
            patients.get(patient_id, {}),
        )

        briefing_id = _make_briefing_id(encounter, run_date)
        try:
            briefings_table.put_item(Item=_to_decimal_dict({
                "briefing_id":      briefing_id,
                "patient_id":       patient_id,
                "provider_id":      encounter["provider_id"],
                "encounter_time":   encounter["scheduled_time"],
                "briefing_text":    briefing_parsed,
                "in_visit_agenda":  [
                    {
                        "measure_id":  r["gap"]["measure_id"],
                        "priority":    r["gap"]["priority"],
                        "adjusted_priority": r["adjusted_priority"],
                        "visit_fit":   r["visit_fit"],
                    }
                    for r in in_visit_agenda
                ],
                "async_queue":      [
                    {"measure_id": r["gap"]["measure_id"],
                     "priority":   r["gap"]["priority"]}
                    for r in async_queue
                ],
                "policy_version":   POLICY_VERSION,
                "generated_at":     run_date,
            }))
        except Exception as exc:
            logger.warning(
                "Failed to persist briefing %s: %s", briefing_id, exc,
            )

        visit_agendas.append({
            "encounter":       encounter,
            "briefing_id":     briefing_id,
            "in_visit_agenda": in_visit_agenda,
            "async_queue":     async_queue,
            "briefing":        briefing_parsed,
        })

    logger.info("Built visit agendas for %d encounters", len(visit_agendas))
    return visit_agendas

def _compute_visit_fit(gap: dict, visit_type: str, visit_minutes: int,
                        provider: dict, acute_context: dict) -> dict:
    """
    Per-pathway visit-fit scoring. The best pathway determines the
    pathway_compatibility component; the time cost is the in-visit
    minutes the gap would consume if addressed; the
    acute_displacement reflects how much of the visit is consumed by
    a non-preventive issue (a back-pain sick visit has high acute
    displacement; an annual wellness visit has none).
    """
    best_pathway = gap["best_pathway"]
    pathway_profile = PATHWAY_PROFILES[best_pathway]

    pathway_compatibility = pathway_profile["visit_type_compatibility"].get(
        visit_type, 0.0,
    )

    time_cost_minutes = pathway_profile["time_cost_minutes"]
    # Time-cost factor: gaps that fit in <2 minutes are very cheap,
    # gaps that take ~5 minutes are normal, gaps that take >10 minutes
    # are expensive in a 25-minute visit.
    if time_cost_minutes <= 2:
        time_cost_factor = 1.0
    elif time_cost_minutes <= 5:
        time_cost_factor = 0.85
    else:
        time_cost_factor = 0.60

    acute_displacement = float(acute_context.get("displacement", 0.0))

    return {
        "pathway":               best_pathway,
        "pathway_compatibility": pathway_compatibility,
        "time_cost_minutes":     time_cost_minutes,
        "time_cost_factor":      time_cost_factor,
        "acute_displacement":    acute_displacement,
    }

def _generate_clinician_briefing(encounter: dict, in_visit_agenda: list,
                                  async_queue: list, patient: dict) -> dict:
    """
    Generate a per-encounter LLM briefing. Falls back to a templated
    summary on LLM/validator failure.
    """
    de_id_context = {
        "patient_summary":       _summarize_patient_for_briefing(patient),
        "visit_type":             encounter.get("visit_type"),
        "visit_minutes":          encounter.get("visit_minutes"),
        "in_visit_agenda":        _redact_identifiers([
            {"measure_id": r["gap"]["measure_id"],
             "priority": r["gap"]["priority"],
             "adjusted_priority": r["adjusted_priority"]}
            for r in in_visit_agenda
        ]),
        "top_async_items":        _redact_identifiers([
            {"measure_id": r["gap"]["measure_id"],
             "priority":   r["gap"]["priority"]}
            for r in async_queue[:5]
        ]),
        "acute_context":          encounter.get("acute_context", {}),
        "language":               encounter.get("preferred_language", "en"),
    }

    try:
        briefing = _bedrock_clinician_briefing(de_id_context)
        if not _validate_briefing(briefing, in_visit_agenda):
            logger.warning(
                "Briefing validator failed for %s; falling back to template",
                encounter.get("provider_id"),
            )
            return _templated_briefing_fallback(in_visit_agenda, async_queue)
        return briefing
    except Exception as exc:
        logger.warning(
            "Briefing generation failed for %s: %s",
            encounter.get("provider_id"), exc,
        )
        return _templated_briefing_fallback(in_visit_agenda, async_queue)

def _summarize_patient_for_briefing(patient: dict) -> dict:
    """
    Build a compact patient summary for the LLM. Stays at the tier of
    "65-74, diabetic, eGFR trending down" rather than surfacing exact
    lab values that might leak into briefing copy via hallucination.
    """
    lab_trends = patient.get("recent_lab_trends", {})
    return {
        "age_band":             patient.get("age_band"),
        "active_conditions":    patient.get("active_conditions", []),
        "recent_lab_summary":   {
            "egfr_trend":  ("falling" if lab_trends.get("egfr_change_24mo", 0) <= -10
                            else "stable"),
            "a1c_band":    _a1c_band(lab_trends.get("a1c_recent")),
        },
        "family_history_flags": patient.get("family_history_flags", []),
    }

def _a1c_band(a1c) -> str:
    if a1c is None:
        return "unknown"
    if a1c < 7.0:
        return "well_controlled"
    if a1c < 8.0:
        return "moderately_controlled"
    return "elevated"

def _bedrock_clinician_briefing(context: dict) -> dict:
    """
    Generate a one-paragraph briefing for the clinician's EHR inbox.
    """
    prompt = f"""You write brief, clinically focused notes for a primary care
physician's EHR inbox before an upcoming encounter. Distill the
deterministic ranker's agenda into a paragraph the clinician can read
in three seconds. Never invent gaps that aren't on the agenda; never
override the ranker's choices. The clinician retains full clinical
authority.

Encounter context (de-identified):
{json.dumps(context, indent=2)}

Return ONLY valid JSON (no prose, no code fences) with this shape:
{{
  "headline":                  "<10-15 word summary>",
  "suggested_focus":           "<2-3 sentence primary focus>",
  "agenda_summary":            "<1-2 sentence summary of agenda items>",
  "deferred_items_summary":    "<1 sentence on async items>",
  "notable_clinical_context":  "<1-2 sentences on relevant context>",
  "confidence_notes":          "<1 sentence on confidence/limitations>"
}}

Reference only measure_ids that appear in in_visit_agenda or
top_async_items. Do not propose new gaps.
"""
    response = bedrock_runtime.invoke_model(
        modelId=CLINICIAN_BRIEFING_MODEL_ID,
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

def _validate_briefing(briefing: dict, in_visit_agenda: list) -> bool:
    """
    Four-layer validator from the main recipe:
      1. Schema and length
      2. Every referenced measure must appear in in_visit_agenda or
         async_queue (the LLM cannot hallucinate gaps)
      3. Prohibited content (no PHI invented, no prescriber names
         other than the visit provider's)
      4. Required disclaimers ("subject to clinical judgment")

    The example checks shape and the agenda-reference invariant; a
    production validator extends with a regex/blocklist pass and an
    approved-claims-only check.
    """
    required = {"headline", "suggested_focus", "agenda_summary",
                "deferred_items_summary", "notable_clinical_context",
                "confidence_notes"}
    if not isinstance(briefing, dict):
        return False
    if not required.issubset(briefing.keys()):
        return False

    # Shape check on each field.
    for key in required:
        val = briefing[key]
        if not isinstance(val, str) or not val.strip():
            return False
        if len(val) > 600:
            return False

    # Agenda-reference invariant: every measure_id mentioned in the
    # briefing should appear in the agenda or async queue.
    agenda_measure_ids = {r["gap"]["measure_id"] for r in in_visit_agenda}
    full_text = " ".join(briefing.values()).lower()

    # If the briefing contains text that looks like a measure_id
    # (hyphenated lowercase tokens) that doesn't appear in the agenda,
    # flag it.
    import re as _re
    candidate_ids = _re.findall(r"\b[a-z]+-[a-z0-9-]{3,}\b", full_text)
    for cid in candidate_ids:
        if "-" in cid and cid not in agenda_measure_ids:
            # Allow common non-measure tokens like "in-office" or
            # "follow-up"; production maintains an allowlist.
            common_tokens = {
                "in-office", "follow-up", "long-term", "low-pressure",
                "first-degree", "well-controlled", "year-end",
            }
            if cid in common_tokens:
                continue
            # If the token looks like a measure_id (matches the
            # registry naming pattern) and isn't on the agenda, fail.
            if any(prefix in cid for prefix in
                   ("hedis-", "uspstf-", "ada-", "cdc-", "kdigo-")):
                return False

    return True

def _templated_briefing_fallback(in_visit_agenda: list,
                                   async_queue: list) -> dict:
    """
    Fallback briefing when the LLM call fails or the validator
    rejects the LLM output. Lists agenda items deterministically.
    """
    if not in_visit_agenda:
        return {
            "headline":                 "No high-priority care gap items for this visit.",
            "suggested_focus":          "No deterministic agenda items met visit-fit threshold.",
            "agenda_summary":           "(none)",
            "deferred_items_summary":   f"{len(async_queue)} items deferred to async closure.",
            "notable_clinical_context": "(briefing fallback; LLM generation skipped or failed)",
            "confidence_notes":         "Briefing fallback used; review patient chart directly.",
        }

    items = ", ".join(r["gap"]["measure_id"] for r in in_visit_agenda)
    return {
        "headline":                 f"Visit agenda: {len(in_visit_agenda)} items.",
        "suggested_focus":          f"Address ranked items: {items}.",
        "agenda_summary":           f"{len(in_visit_agenda)} in-visit items, "
                                     f"{len(async_queue)} deferred.",
        "deferred_items_summary":   f"{len(async_queue)} items deferred to async closure.",
        "notable_clinical_context": "(briefing fallback; LLM generation skipped or failed)",
        "confidence_notes":         "Briefing fallback used; clinician judgment applies.",
    }
```

---

## Step 4: Asynchronous Orchestration for Non-Visit Closures

*The pseudocode calls this `orchestrate_async_closures(...)`. Gaps that didn't make a visit agenda flow to the async orchestrator. The orchestrator picks the best pathway per gap, respects per-patient contact-frequency caps, applies equity floors, and routes to the appropriate channel. Skip the per-pathway routing and your colonoscopy gap becomes an undifferentiated "send a generic email" outreach, which has near-zero closure rate and burns trust.*

```python
def orchestrate_async_closures(
    visit_agendas: list,
    enriched_gaps: list,
    patients: dict,
    measure_lookup: dict,
    run_date: str,
) -> list:
    """
    Allocate async closure pathways for gaps not on an upcoming visit
    agenda. Persist allocations to recommendation-log; emit
    gap_surfaced_for_outreach events to Kinesis; dispatch to the
    appropriate per-pathway worker.
    """
    visit_horizon_end = (
        datetime.date.fromisoformat(run_date)
        + datetime.timedelta(days=ASYNC_VISIT_HORIZON_DAYS)
    )
    visited_or_planned = _collect_patient_ids_with_upcoming_visits(
        visit_horizon_end,
    )

    # Build the async candidate set: gaps that are open and not on a
    # near-term visit agenda.
    visit_agenda_lookup = {
        va["encounter"]["patient_id"]: {
            r["gap"]["measure_id"] for r in va["in_visit_agenda"]
        }
        for va in visit_agendas
    }

    async_candidates = []
    for gap in enriched_gaps:
        patient_id = gap["patient_id"]
        if patient_id in visited_or_planned:
            agenda_measures = visit_agenda_lookup.get(patient_id, set())
            if gap["measure_id"] in agenda_measures:
                # The visit will address this gap; don't queue async too.
                continue
        async_candidates.append(gap)

    candidates_sorted = sorted(
        async_candidates, key=lambda x: x["priority"], reverse=True,
    )

    # Per-pathway capacity counters. Capacity is daily * horizon_days.
    capacity_remaining = {
        pathway: PATHWAY_CAPACITY[pathway] * ASYNC_VISIT_HORIZON_DAYS
        for pathway in TRACKED_PATHWAYS
    }

    # Per-pathway equity-floor counters.
    equity_remaining = {
        pathway: dict(EQUITY_FLOORS.get(pathway, {}))
        for pathway in TRACKED_PATHWAYS
    }

    patient_gap_count: dict = {}
    patient_contact_count_30d: dict = {}

    allocated = []

    for candidate in candidates_sorted:
        patient_id = candidate["patient_id"]
        patient = patients.get(patient_id, {})
        chosen_pathway = candidate["best_pathway"]

        # Per-pathway capacity.
        if capacity_remaining.get(chosen_pathway, 0) <= 0:
            # Try the second-best pathway.
            chosen_pathway = _second_best_pathway(candidate, capacity_remaining)
            if chosen_pathway is None:
                continue

        # Per-patient gap-count cap.
        if (patient_gap_count.get(patient_id, 0)
            >= MAX_GAPS_PER_PATIENT_PER_RUN):
            continue

        # Global contact-frequency cap (shared across Chapter 4 recipes).
        existing_contacts = int(patient.get("outreach_recent_30d_count", 0))
        new_contacts = patient_contact_count_30d.get(patient_id, 0)
        pathway_profile = PATHWAY_PROFILES[chosen_pathway]
        if (pathway_profile["generates_patient_contact"]
            and (existing_contacts + new_contacts)
                >= MAX_TOTAL_CONTACTS_PER_PATIENT_30D):
            continue

        # Cross-recipe coordination: if the patient is currently in
        # an adherence intervention (4.5) or wellness enrollment (4.4)
        # that suppresses additional outreach, skip or downgrade.
        if _cross_recipe_suppresses(patient_id, chosen_pathway):
            continue

        # Apply equity floor.
        cohort_features = candidate.get("cohort_features", {})
        applicable = _applicable_floor_cohorts(
            cohort_features, EQUITY_FLOORS.get(chosen_pathway, {}),
        )
        used_floor = None
        for floor_cohort in applicable:
            if equity_remaining[chosen_pathway].get(floor_cohort, 0) > 0:
                equity_remaining[chosen_pathway][floor_cohort] -= 1
                used_floor = floor_cohort
                break

        # Commit the allocation.
        capacity_remaining[chosen_pathway] -= 1
        patient_gap_count[patient_id] = patient_gap_count.get(
            patient_id, 0) + 1
        if pathway_profile["generates_patient_contact"]:
            patient_contact_count_30d[patient_id] = (
                patient_contact_count_30d.get(patient_id, 0) + 1
            )

        allocation_reason = (
            f"equity_floor:{used_floor}" if used_floor
            else "high_priority_general_capacity"
        )

        record = {
            "tracking_id":         _make_tracking_id(
                run_date, patient_id, candidate["measure_id"], chosen_pathway,
            ),
            "run_date":            run_date,
            "patient_id":          patient_id,
            "measure_id":          candidate["measure_id"],
            "chosen_pathway":      chosen_pathway,
            "priority":            candidate["priority"],
            "priority_components": candidate["priority_components"],
            "policy_version":      candidate["policy_version"],
            "cohort_features":     cohort_features,
            "allocation_reason":   allocation_reason,
            "data_quality_flag":   candidate.get("data_quality_flag", "complete"),
        }
        allocated.append(record)

    # Persist allocations and dispatch.
    rec_table = dynamodb.Table(RECOMMENDATION_LOG_TABLE)
    profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
    dispatched = []

    for row in allocated:
        try:
            rec_table.put_item(Item=_to_decimal_dict({
                **row, "created_at": _now_iso(),
            }))
        except Exception as exc:
            logger.warning(
                "Failed to persist allocation for %s: %s",
                row["tracking_id"], exc,
            )

        # Dispatch by pathway.
        try:
            patient = patients.get(row["patient_id"], {})
            measure = measure_lookup.get(row["measure_id"], {})
            dispatch_record = _dispatch_async_pathway(row, patient, measure)
            dispatched.append(dispatch_record)
        except Exception as exc:
            logger.warning(
                "Async dispatch failed for %s: %s", row["tracking_id"], exc,
            )

        # Optimistically increment the contact-cap counter; the
        # closure tracker decrements on outreach failure.
        pathway_profile = PATHWAY_PROFILES[row["chosen_pathway"]]
        if pathway_profile["generates_patient_contact"]:
            try:
                profile_table.update_item(
                    Key={"patient_id": row["patient_id"]},
                    UpdateExpression="ADD outreach_recent_30d_count :one",
                    ExpressionAttributeValues={":one": Decimal("1")},
                )
            except Exception as exc:
                logger.warning(
                    "Failed to update contact counter for %s: %s",
                    row["patient_id"], exc,
                )

        # Emit the surfacing event.
        try:
            kinesis_client.put_record(
                StreamName=CLOSURE_STREAM_NAME,
                PartitionKey=row["patient_id"],
                Data=json.dumps({
                    "event_type":          "gap_surfaced_for_outreach",
                    "tracking_id":         row["tracking_id"],
                    "patient_id":          row["patient_id"],
                    "measure_id":          row["measure_id"],
                    "chosen_pathway":      row["chosen_pathway"],
                    "priority_components": row["priority_components"],
                    "allocation_reason":   row["allocation_reason"],
                    "run_date":            row["run_date"],
                    "timestamp":           _now_iso(),
                }, default=str).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to publish surfacing event for %s: %s",
                row["tracking_id"], exc,
            )

    logger.info(
        "Async orchestration allocated %d gaps; dispatched %d",
        len(allocated), len(dispatched),
    )
    return allocated

def _collect_patient_ids_with_upcoming_visits(horizon_end: datetime.date) -> set:
    """
    Production: query the schedule feed for patients with visits in
    the next ASYNC_VISIT_HORIZON_DAYS. The example returns an empty
    set; the runner overrides with synthetic visited patients.
    """
    return _DEMO_VISITED_PATIENTS

def _second_best_pathway(candidate: dict,
                          capacity_remaining: dict) -> str | None:
    """
    Pick the second-best pathway by closure probability, restricted
    to pathways with remaining capacity.
    """
    per_pathway = candidate.get("per_pathway", {})
    sorted_pathways = sorted(
        per_pathway.keys(),
        key=lambda p: per_pathway[p]["closure_prob"],
        reverse=True,
    )
    for p in sorted_pathways[1:]:
        if capacity_remaining.get(p, 0) > 0:
            return p
    return None

def _cross_recipe_suppresses(patient_id: str, pathway: str) -> bool:
    """
    Cross-recipe coordination: if the patient is currently in an
    adherence intervention (4.5) or wellness program (4.4) with an
    active suppression flag, downgrade or skip this gap's outreach.
    Production: query the patient-profile cross-recipe flags.
    """
    return False

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

def _dispatch_async_pathway(row: dict, patient: dict, measure: dict) -> dict:
    """
    Per-pathway dispatch. Each branch hands to the right channel:
    member messaging, fulfillment, referral management, chase queue,
    or PCP inbox. Production: each branch invokes a dedicated worker
    Lambda.
    """
    pathway = row["chosen_pathway"]
    if pathway == "patient_driven_pharmacy":
        return _dispatch_pharmacy_nudge(row, patient, measure)
    if pathway == "patient_driven_home_kit":
        return _dispatch_home_kit_fulfillment(row, patient, measure)
    if pathway == "specialist_referral":
        return _dispatch_specialist_referral(row, patient, measure)
    if pathway == "chase_team_call":
        return _dispatch_chase_team_call(row, patient, measure)
    if pathway == "asynchronous_pcp_inbox":
        return _dispatch_pcp_inbox(row, patient, measure)
    if pathway == "in_visit":
        # In-visit pathways are surfaced via the briefing, not async.
        return {"tracking_id": row["tracking_id"], "channel": "in_visit_only"}
    raise ValueError(f"Unknown pathway: {pathway}")

def _dispatch_pharmacy_nudge(row: dict, patient: dict, measure: dict) -> dict:
    """
    Tailored portal/SMS/email nudge directing the patient to a
    network pharmacy. Falls back to the default template on LLM or
    validator failure.
    """
    try:
        tailored = _bedrock_tailor_pharmacy_message(row, patient, measure)
        if not _validate_clinical_message(tailored, measure["measure_id"]):
            tailored = None
    except Exception as exc:
        logger.warning(
            "Pharmacy message tailoring failed for %s: %s",
            row["tracking_id"], exc,
        )
        tailored = None

    payload = {
        "tracking_id":      row["tracking_id"],
        "patient_id":       row["patient_id"],
        "measure_id":       row["measure_id"],
        "channel":          "pharmacy_nudge",
        "tailored":         tailored,
        "fallback_template": f"pharmacy-nudge-{measure['measure_id']}-default",
        "queued_at":        _now_iso(),
    }
    logger.info(
        "Queued pharmacy nudge for %s (measure=%s)",
        row["tracking_id"], row["measure_id"],
    )
    return payload

def _dispatch_home_kit_fulfillment(row: dict, patient: dict,
                                    measure: dict) -> dict:
    """Hand to the home-kit fulfillment partner."""
    payload = {
        "tracking_id":  row["tracking_id"],
        "patient_id":   row["patient_id"],
        "measure_id":   row["measure_id"],
        "channel":      "home_kit_fulfillment",
        "queued_at":    _now_iso(),
    }
    logger.info("Queued home-kit fulfillment for %s", row["tracking_id"])
    return payload

def _dispatch_specialist_referral(row: dict, patient: dict,
                                    measure: dict) -> dict:
    """Hand to the referral-management workflow."""
    payload = {
        "tracking_id":          row["tracking_id"],
        "patient_id":           row["patient_id"],
        "measure_id":           row["measure_id"],
        "channel":              "referral_management",
        "suggested_specialty":  _suggest_specialty_for_measure(measure),
        "priority":             row["priority"],
        "queued_at":            _now_iso(),
    }
    logger.info("Queued specialist referral for %s", row["tracking_id"])
    return payload

def _dispatch_chase_team_call(row: dict, patient: dict, measure: dict) -> dict:
    """
    Generate a structured pre-call brief for the chase agent and
    enqueue.
    """
    try:
        brief = _bedrock_chase_brief(row, patient, measure)
        if not _validate_chase_brief(brief):
            brief = {"summary": "(chase brief generation failed; agent to review)"}
    except Exception as exc:
        logger.warning(
            "Chase brief failed for %s: %s", row["tracking_id"], exc,
        )
        brief = {"summary": "(chase brief generation failed; agent to review)"}

    payload = {
        "tracking_id":  row["tracking_id"],
        "patient_id":   row["patient_id"],
        "measure_id":   row["measure_id"],
        "channel":      "chase_team_queue",
        "priority":     row["priority"],
        "brief_text":   brief,
        "queued_at":    _now_iso(),
    }
    logger.info("Queued chase-team call for %s", row["tracking_id"])
    return payload

def _dispatch_pcp_inbox(row: dict, patient: dict, measure: dict) -> dict:
    """Post a structured note to the PCP inbox with a one-click order."""
    payload = {
        "tracking_id":      row["tracking_id"],
        "patient_id":       row["patient_id"],
        "measure_id":       row["measure_id"],
        "channel":          "ehr_pcp_inbox",
        "suggested_action": _default_pcp_action_for_measure(measure),
        "queued_at":        _now_iso(),
    }
    logger.info("Posted PCP inbox note for %s", row["tracking_id"])
    return payload

def _suggest_specialty_for_measure(measure: dict) -> str:
    """Mapping of measure to suggested specialty for referral."""
    return {
        "hedis-eed":                    "ophthalmology_optometry",
        "uspstf-colorectal-screening":  "gastroenterology",
    }.get(measure["measure_id"], "primary_care")

def _default_pcp_action_for_measure(measure: dict) -> str:
    """Default one-click PCP action."""
    return {
        "ada-uacr-annual-diabetes": "order_uacr",
    }.get(measure["measure_id"], "review_chart")

def _bedrock_tailor_pharmacy_message(row: dict, patient: dict,
                                       measure: dict) -> dict:
    """Generate a pharmacy-nudge message via Bedrock."""
    context = {
        "measure":              measure["display_name"],
        "preferred_language":   patient.get("preferred_language", "en"),
        "tone":                 "informational, low-pressure",
    }
    prompt = f"""You write supportive, non-alarming healthcare reminders for a
health plan. Produce a short pharmacy-nudge message for a member.
Do NOT make clinical claims; do NOT promise outcomes; do NOT use
clinical jargon.

Context:
{json.dumps(context, indent=2)}

Return ONLY valid JSON with this shape:
{{
  "subject_line":      "<subject>",
  "body":              "<2-3 sentence body>",
  "call_to_action":    "<single CTA, no guarantees>",
  "tone":              "<one phrase>"
}}
"""
    response = bedrock_runtime.invoke_model(
        modelId=MESSAGE_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        400,
            "temperature":       0.3,
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

def _validate_clinical_message(tailored: dict, measure_id: str) -> bool:
    """
    Shape and prohibited-claims check for member-facing messages.
    Production extends with an approved-claims pass against a
    per-measure artifact owned by clinical/compliance.
    """
    if not isinstance(tailored, dict):
        return False
    required = {"subject_line", "body", "call_to_action", "tone"}
    if not required.issubset(tailored.keys()):
        return False
    full_text = " ".join(
        v for v in tailored.values() if isinstance(v, str)
    ).lower()
    blocklist = ["guaranteed", "cure", "100%", "definitely will", "must take"]
    if any(bad in full_text for bad in blocklist):
        return False
    return True

def _bedrock_chase_brief(row: dict, patient: dict, measure: dict) -> dict:
    """Generate a structured pre-call brief for the chase agent."""
    context = {
        "measure":            measure["display_name"],
        "priority":           row["priority"],
        "preferred_language": patient.get("preferred_language", "en"),
    }
    prompt = f"""You write structured pre-call briefs for chase-team agents.
Stay factual, concise, and respectful of the member's time.

Context:
{json.dumps(context, indent=2)}

Return ONLY valid JSON with this shape:
{{
  "opening_script":      "<one sentence>",
  "talking_points":      ["<point>", "<point>", "<point>"],
  "anticipated_objections": ["<objection>"],
  "outcome_capture":     "<one phrase>"
}}
"""
    response = bedrock_runtime.invoke_model(
        modelId=CHASE_BRIEF_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        500,
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

def _validate_chase_brief(brief: dict) -> bool:
    """Shape check for the chase brief."""
    required = {"opening_script", "talking_points",
                "anticipated_objections", "outcome_capture"}
    if not isinstance(brief, dict):
        return False
    if not required.issubset(brief.keys()):
        return False
    if not isinstance(brief["talking_points"], list):
        return False
    if not isinstance(brief["anticipated_objections"], list):
        return False
    return True

# Demo state populated by the runner.
_DEMO_VISITED_PATIENTS: set = set()
```

---

## Step 5: Track Closures From Multiple Sources

*The pseudocode calls this `process_closure_event(event)`. Closure events arrive from claims, EHR encounters, lab feeds, pharmacy data, immunization registries, and patient self-report. Each has its own latency and trustworthiness profile. Skip the multi-source reconciliation and your chase team will call patients about colonoscopies they had last week.*

```python
def process_closure_event(event: dict, measure_lookup: dict) -> None:
    """
    Process one closure event from Kinesis and update the gap state
    machine.

    Expected shape:
      {
        "event_type":        "closure_source_event",
        "patient_id":        "...",
        "source":            "claims" | "ehr" | "lab" | "pharmacy" |
                             "immunization_registry" | "patient_self_report",
        "qualifying_codes":  ["..."],
        "timestamp":         ISO 8601,
        "payload":           source-specific event body
      }
    """
    patient_id = event.get("patient_id")
    source = event.get("source")
    if not (patient_id and source):
        logger.warning("Malformed closure event; dropping: %s", event)
        return

    # Step 5A: match the event to one or more open or
    # provisionally-closed gaps. A single event (e.g., a colonoscopy
    # claim) can satisfy multiple measures.
    candidate_matches = _match_event_to_open_gaps(
        patient_id, event, measure_lookup,
    )

    if not candidate_matches:
        logger.info(
            "Closure event from %s for %s has no matched gap; logging only",
            source, patient_id,
        )
        return

    gaps_table = dynamodb.Table(PATIENT_GAPS_TABLE)

    # Step 5B: per-match, advance the state machine.
    for match in candidate_matches:
        gap = match["gap"]
        measure = match["measure"]

        if source == measure["canonical_source"]:
            new_state = "confirmed_closed"
        else:
            # Non-canonical event: provisional unless gap is already
            # provisional or confirmed.
            if gap["state"] == "open":
                new_state = "provisionally_closed"
            else:
                new_state = gap["state"]

        if new_state == gap["state"]:
            logger.debug(
                "No state change for %s/%s on %s event",
                patient_id, gap["measure_id"], source,
            )
            continue

        try:
            gaps_table.update_item(
                Key={
                    "patient_id": patient_id,
                    "measure_id": gap["measure_id"],
                },
                UpdateExpression=(
                    "SET #s = :ns, evidence = :ev, "
                    "last_evaluation_date = :led "
                    "ADD state_history :history_event"
                ),
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues=_to_decimal_dict({
                    ":ns":  new_state,
                    ":ev":  event.get("payload", {}),
                    ":led": _now_iso(),
                    ":history_event": [{
                        "event":     f"transitioned_to_{new_state}",
                        "timestamp": event.get("timestamp", _now_iso()),
                        "source":    source,
                        "evidence":  event.get("payload", {}),
                    }],
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to advance gap state for %s/%s: %s",
                patient_id, gap["measure_id"], exc,
            )
            continue

        # Step 5C: suppress in-flight outreach for this gap.
        _suppress_inflight_outreach(
            patient_id, gap["measure_id"], reason="gap_closed",
            closure_state=new_state,
        )

        # Step 5D: emit the closure event for downstream consumers.
        try:
            event_type = (
                "gap_confirmed_closed" if new_state == "confirmed_closed"
                else "gap_provisionally_closed"
            )
            kinesis_client.put_record(
                StreamName=CLOSURE_STREAM_NAME,
                PartitionKey=patient_id,
                Data=json.dumps({
                    "event_type":     event_type,
                    "patient_id":     patient_id,
                    "measure_id":     gap["measure_id"],
                    "event_source":   source,
                    "event_payload":  event.get("payload", {}),
                    "timestamp":      event.get("timestamp", _now_iso()),
                }, default=str).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to publish closure event for %s/%s: %s",
                patient_id, gap["measure_id"], exc,
            )

        # Step 5E: cohort-sliced metrics for the equity dashboard.
        cohort = gap.get("cohort_features", {}) or {}
        _emit_metric(
            "gap_closure",
            value=1,
            dimensions={
                "measure_id":     gap["measure_id"],
                "closure_source": source,
                "new_state":      new_state,
                "engagement_q":   str(cohort.get("engagement_history_quartile", "unknown")),
                "language":       str(cohort.get("language", "unknown")),
                "sdoh_cohort":    str(cohort.get("sdoh_cohort", "unknown")),
            },
        )

        logger.info(
            "Closure event processed: patient=%s measure=%s source=%s -> %s",
            patient_id, gap["measure_id"], source, new_state,
        )

def _match_event_to_open_gaps(patient_id: str, event: dict,
                                measure_lookup: dict) -> list:
    """
    Find open or provisionally-closed gaps for this patient that the
    event satisfies. Production: a Query against a (patient_id, state)
    GSI on patient-gaps; for each open gap, check whether the event's
    qualifying_codes intersect with the measure's numerator value set.
    """
    gaps_table = dynamodb.Table(PATIENT_GAPS_TABLE)
    matches = []
    qualifying_codes = set(event.get("qualifying_codes", []))

    try:
        # Production: Query with KeyConditionExpression on a
        # patient_id+state GSI. The example does a scan over the
        # patient's gap rows for clarity.
        response = gaps_table.scan(
            FilterExpression="patient_id = :pid",
            ExpressionAttributeValues={":pid": patient_id},
        )
        gaps = [_from_decimal(item) for item in response.get("Items", [])]
    except Exception as exc:
        logger.warning("Match scan failed for patient %s: %s", patient_id, exc)
        return []

    for gap in gaps:
        if gap.get("state") not in {"open", "provisionally_closed"}:
            continue
        measure = measure_lookup.get(gap["measure_id"])
        if measure is None:
            continue

        # Numerator-match check: if the event references qualifying
        # codes for this measure, it's a match. The example uses a
        # simple set intersection against a synthetic measure-to-code
        # map; production uses the registry's numerator value set.
        measure_codes = set(_DEMO_MEASURE_QUALIFYING_CODES.get(
            gap["measure_id"], []))
        if measure_codes & qualifying_codes:
            matches.append({"gap": gap, "measure": measure})

    return matches

def _suppress_inflight_outreach(patient_id: str, measure_id: str,
                                 reason: str, closure_state: str) -> None:
    """
    When a gap closes, suppress in-flight outreach for that gap so
    the chase team doesn't call about a colonoscopy the patient had
    last week. Production: query the recommendation-log for in-flight
    rows on this (patient, measure) and mark them suppressed.
    """
    logger.info(
        "Outreach suppression: patient=%s measure=%s reason=%s state=%s",
        patient_id, measure_id, reason, closure_state,
    )

# Synthetic measure -> qualifying code mapping for the demo. Production
# pulls from the measure registry's numerator value sets.
_DEMO_MEASURE_QUALIFYING_CODES: dict = {}
```

---

## Step 6: Handle Clinician Overrides as Structured Signals

*The pseudocode calls this `process_clinician_override(event)`. When a clinician dismisses a high-priority gap with a reason, the override is gold-label data. It informs both immediate suppression and longer-horizon model retraining. Skip the structured override capture and you either keep nagging the clinician or you lose the signal entirely.*

```python
def process_clinician_override(event: dict) -> None:
    """
    Process a clinician-override event. Persist the override to the
    audit table, apply the suppression policy, and emit a feedback
    signal for retraining.

    Expected shape:
      {
        "event_type":      "clinician_override",
        "briefing_id":     "...",
        "patient_id":      "...",
        "provider_id":     "...",
        "measure_id":      "...",
        "reason":          "<one of ALLOWED_OVERRIDE_REASONS>",
        "free_text_note":  "<optional>",
        "timestamp":       ISO 8601
      }
    """
    reason = event.get("reason")
    if reason not in ALLOWED_OVERRIDE_REASONS:
        logger.warning("Invalid override reason: %s", reason)
        return

    patient_id = event.get("patient_id")
    measure_id = event.get("measure_id")
    if not (patient_id and measure_id):
        logger.warning("Malformed override event; dropping: %s", event)
        return

    overrides_table = dynamodb.Table(CLINICIAN_OVERRIDES_TABLE)
    override_record = {
        "override_id":      str(uuid.uuid4()),
        "briefing_id":      event.get("briefing_id"),
        "patient_id":       patient_id,
        "provider_id":      event.get("provider_id"),
        "measure_id":       measure_id,
        "reason":           reason,
        "free_text_note":   event.get("free_text_note", ""),
        "timestamp":        event.get("timestamp", _now_iso()),
    }

    try:
        overrides_table.put_item(Item=_to_decimal_dict(override_record))
    except Exception as exc:
        logger.warning("Failed to persist override: %s", exc)
        return

    # Apply suppression policy.
    suppression = SUPPRESSION_BY_REASON[reason]
    _apply_suppression(patient_id, measure_id, suppression)

    # Feed into the urgency-model retraining pipeline as a structured
    # label. Some reasons (clinical_judgment_defer,
    # exclusion_documented) carry strong signal that the urgency model
    # miscalibrated; out_of_scope_for_visit carries signal about
    # visit-fit ranking, not urgency.
    _update_training_label(override_record)

    # Emit the override event for downstream consumers.
    try:
        kinesis_client.put_record(
            StreamName=CLOSURE_STREAM_NAME,
            PartitionKey=patient_id,
            Data=json.dumps({
                "event_type":   "clinician_override_recorded",
                "patient_id":   patient_id,
                "measure_id":   measure_id,
                "provider_id":  event.get("provider_id"),
                "reason":       reason,
                "briefing_id":  event.get("briefing_id"),
                "timestamp":    event.get("timestamp", _now_iso()),
            }, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to publish override event for %s/%s: %s",
            patient_id, measure_id, exc,
        )

    _emit_metric(
        "clinician_override",
        value=1,
        dimensions={
            "measure_id":  measure_id,
            "reason":      reason,
            "provider_id": event.get("provider_id", "unknown"),
        },
    )

    logger.info(
        "Clinician override processed: patient=%s measure=%s reason=%s",
        patient_id, measure_id, reason,
    )

def _apply_suppression(patient_id: str, measure_id: str,
                        suppression: dict) -> None:
    """
    Apply suppression on the gap based on the override reason. The
    suppression record sits on the patient-gaps row so the next
    enrichment cycle excludes the gap from surfacing for the
    suppression window.
    """
    gaps_table = dynamodb.Table(PATIENT_GAPS_TABLE)
    suppress_until = (
        datetime.date.today()
        + datetime.timedelta(days=suppression.get("days", 0))
    ).isoformat()

    update_expression = (
        "SET suppressed_until = :su, last_suppression_reason = :sr"
    )
    expression_values = {
        ":su": suppress_until,
        ":sr": suppression,
    }

    if suppression.get("mark_excluded"):
        update_expression += ", #s = :excluded"
        expression_values[":excluded"] = "excluded"
    elif suppression.get("mark_provisional"):
        update_expression += ", #s = :prov"
        expression_values[":prov"] = "provisionally_closed"

    expression_attribute_names = (
        {"#s": "state"}
        if "#s" in update_expression
        else None
    )

    try:
        kwargs = {
            "Key": {"patient_id": patient_id, "measure_id": measure_id},
            "UpdateExpression": update_expression,
            "ExpressionAttributeValues": _to_decimal_dict(expression_values),
        }
        if expression_attribute_names:
            kwargs["ExpressionAttributeNames"] = expression_attribute_names
        gaps_table.update_item(**kwargs)
    except Exception as exc:
        logger.warning(
            "Failed to apply suppression to %s/%s: %s",
            patient_id, measure_id, exc,
        )

def _update_training_label(override_record: dict) -> None:
    """
    Append the override to the urgency-model retraining label
    partition. The trainer joins (recommendation, override) pairs
    into the per-gap-type urgency model's training set, weighting
    reasons appropriately (clinical_judgment_defer is a stronger
    urgency-down signal than out_of_scope_for_visit, which is a
    visit-fit-ranker signal instead).
    """
    logger.debug(
        "training_label_added: measure=%s reason=%s",
        override_record["measure_id"], override_record["reason"],
    )
```

---

## Putting It All Together

Here's the full daily pipeline assembled into a single callable function. In production, this is a Step Functions workflow with each step as a separate task: Glue/Athena (gap evaluation), SageMaker Batch Transform jobs in parallel (urgency and per-pathway engagement), Lambda (priority synthesis, visit ranking, async orchestration, briefing generation). Step 5 (closure tracking) and Step 6 (override handling) run continuously in separate Lambdas consuming the closure-and-engagement stream. The example chains them together so you can trace one daily run end-to-end.

```python
def run_daily_batch(
    patients_list: list,
    next_day_schedule: list,
    run_date: str | None = None,
) -> dict:
    """
    Run the full daily pipeline.

    Steps 1-4:
      1. evaluate_measures
      2. enrich_open_gaps
      3. rank_visit_agendas (over next_day_schedule)
      4. orchestrate_async_closures

    Steps 5 and 6 run continuously in separate Lambdas. The example
    invokes them once each at the end with synthetic events to
    exercise the pipeline end-to-end.
    """
    run_date = run_date or _today_str()
    start = time.time()

    print(f"=== Starting daily batch for run_date={run_date} ===")

    patients = {p["patient_id"]: p for p in patients_list}
    measure_lookup = {m["measure_id"]: m for m in SAMPLE_MEASURE_REGISTRY}

    print("\nStep 1: Evaluating measure registry against patient data...")
    transitions = evaluate_measures(patients_list, run_date)
    print(f"  {len(transitions)} (patient, measure) state records")

    print("\nStep 1b (optional): LLM candidate-gap surfacer (sampled)...")
    high_risk_subset = [
        p for p in patients_list
        if p.get("recent_lab_trends", {}).get("egfr_change_24mo", 0) <= -10
    ][:5]
    candidates = surface_candidate_gaps_via_llm(high_risk_subset, run_date)
    print(f"  {len(candidates)} candidates queued for clinical-informatics review")

    print("\nStep 2: Enriching open gaps with urgency, engagement, priority...")
    enriched = enrich_open_gaps(run_date, patients, measure_lookup)
    print(f"  Enriched {len(enriched)} open gaps")

    print("\nStep 3: Ranking gaps for tomorrow's encounters...")
    visit_agendas = rank_visit_agendas(
        next_day_schedule, run_date, enriched, patients,
    )
    print(f"  Built {len(visit_agendas)} visit agendas")

    print("\nStep 4: Orchestrating async closures for non-visit gaps...")
    allocated = orchestrate_async_closures(
        visit_agendas, enriched, patients, measure_lookup, run_date,
    )
    print(f"  Allocated {len(allocated)} async pathway assignments")

    elapsed = int(time.time() - start)
    print(f"\n=== Batch complete in {elapsed}s ===")
    return {
        "run_date":          run_date,
        "n_patients":        len(patients_list),
        "n_transitions":     len(transitions),
        "n_candidates":      len(candidates),
        "n_enriched":        len(enriched),
        "n_visit_agendas":   len(visit_agendas),
        "n_allocated":       len(allocated),
        "elapsed_seconds":   elapsed,
    }

# --- Demo runner ---
if __name__ == "__main__":
    # All sample data is SYNTHETIC. Do not use real PHI in development.
    # The demo:
    #   1. Builds two synthetic patients (David, who matches the opening
    #      narrative of the recipe, and Mr. Chen from the briefing example)
    #   2. Seeds the synthetic qualifying-event and exclusion lookup tables
    #   3. Runs Steps 1-4 against the synthetic data
    #   4. Simulates a closure event (Step 5) and a clinician override
    #      (Step 6) to exercise those Lambdas
    #
    # The actual Bedrock and SageMaker calls are mocked at the helper
    # level so the demo runs offline.

    print("=" * 70)
    print("Building synthetic patients, schedule, and feed lookups...")
    print("=" * 70)

    run_date = _today_str()

    patients_list = [
        {
            "patient_id":               "pat-000482",
            "age":                      64,
            "age_band":                 "55-64",
            "preferred_language":       "en",
            "engagement_history_quartile": "q3",
            "sdoh_cohort":              "moderate_food_security",
            "active_conditions":        ["diabetes_type_2", "hypertension"],
            "continuously_enrolled":    True,
            "outreach_recent_30d_count": Decimal("0"),
            "recent_lab_trends": {
                "a1c_recent":         7.8,
                "egfr_change_24mo":  -14,    # 78 -> 64 over 24 months
            },
            "family_history_flags":     ["first_degree_colon_cancer"],
            "current_medications":      ["metformin", "atorvastatin",
                                          "lisinopril"],
            "recent_encounter_summary": "PCP follow-up 8 months ago; "
                                         "annual visit scheduled tomorrow.",
        },
        {
            "patient_id":               "pat-000915",
            "age":                      70,
            "age_band":                 "65-74",
            "preferred_language":       "es",
            "engagement_history_quartile": "q1",
            "sdoh_cohort":              "low_food_security",
            "active_conditions":        ["diabetes_type_2"],
            "continuously_enrolled":    True,
            "outreach_recent_30d_count": Decimal("1"),
            "recent_lab_trends": {
                "a1c_recent":         6.9,
                "egfr_change_24mo":  -3,
            },
            "family_history_flags":     [],
            "current_medications":      ["metformin"],
            "recent_encounter_summary": "PCP visit 14 months ago; "
                                         "no upcoming visit.",
        },
    ]

    next_day_schedule = [
        {
            "patient_id":      "pat-000482",
            "provider_id":     "prov-014",
            "provider_name":   "Dr. Patel",
            "scheduled_time":  f"{run_date}T09:15:00Z",
            "visit_type":      "annual_visit",
            "visit_minutes":   25,
            "preferred_language": "en",
            "acute_context":   {"displacement": 0.0},
        },
    ]

    # Seed the synthetic qualifying-event lookups. pat-000482 has no
    # qualifying events for any measure in the lookback (so all gaps
    # show as open). pat-000915 has an old colonoscopy claim from
    # 2020 that's still within the 10-year lookback.
    _DEMO_QUALIFYING_EVENTS.update({
        ("pat-000915", "uspstf-colorectal-screening", "claims"): {
            "code":         "45378",   # colonoscopy CPT
            "service_date": "2020-08-12",
        },
    })
    _DEMO_EXCLUSION_FLAGS.update({})
    _DEMO_FRAGMENTATION_FLAGS.update({})
    _DEMO_HISTORY_COUNT.update({
        "pat-000482": 50,
        "pat-000915": 30,
    })
    _DEMO_VISITED_PATIENTS.add("pat-000482")    # has visit tomorrow
    _DEMO_MEASURE_QUALIFYING_CODES.update({
        "uspstf-colorectal-screening":  ["45378", "45380", "45381"],
        "hedis-cdc-eye-exam":           ["67220", "92002", "92004", "92012"],
        "hedis-cdc-foot-exam":          ["g0245", "g0246"],
        "cdc-pneumococcal-65plus":      ["90670", "90732"],
        "ada-uacr-annual-diabetes":     ["82043"],
    })

    # Mock Bedrock calls so the demo runs offline. Production never
    # bypasses these.
    def _mock_candidate_gap(chart_context):
        return [{
            "candidate_gap_label":         "ckd_conversation_overdue",
            "rationale":                   "Patient has diabetes with declining "
                                            "eGFR (-14 over 24 months) and no "
                                            "documented CKD conversation in "
                                            "recent encounter summary.",
            "suggested_evidence_to_check": ["CKD conversation note",
                                             "nephrology referral"],
            "confidence":                  "moderate",
            "supporting_chart_excerpts":   ["egfr trend declining",
                                             "diabetes type 2"],
        }]

    def _mock_briefing(context):
        return {
            "headline":                 "Annual visit; multiple gaps; "
                                         "consider kidney conversation focus.",
            "suggested_focus":          "Patient's eGFR has declined materially; "
                                         "consider CKD conversation and UACR order. "
                                         "Diabetic foot exam fits in office.",
            "agenda_summary":           "3 in-visit items selected; "
                                         "specialist referrals deferred to async.",
            "deferred_items_summary":   "Eye exam and pneumococcal vaccine "
                                         "deferred to chase team.",
            "notable_clinical_context": "Family history first-degree colon cancer; "
                                         "colonoscopy gap clinically important.",
            "confidence_notes":         "Briefing reflects deterministic ranker; "
                                         "subject to clinical judgment.",
        }

    def _mock_pharmacy_message(row, patient, measure):
        return {
            "subject_line":   "Quick health checklist item",
            "body":           "Your in-network pharmacies can provide your "
                              "vaccine without an appointment. Often takes "
                              "less than 15 minutes.",
            "call_to_action": "Find a pharmacy near you",
            "tone":           "informational, low-pressure",
        }

    def _mock_chase_brief(row, patient, measure):
        return {
            "opening_script":         "Hi, this is your care team calling "
                                       "with a quick health check-in.",
            "talking_points":         ["Confirm member's preferred pharmacy",
                                        "Mention upcoming preventive care",
                                        "Offer scheduling assistance"],
            "anticipated_objections": ["Already had it elsewhere"],
            "outcome_capture":        "scheduled / completed_elsewhere / declined",
        }

    # Patch module-level Bedrock helpers for offline demo.
    globals()["_bedrock_candidate_gap_surface"] = _mock_candidate_gap
    globals()["_bedrock_clinician_briefing"] = _mock_briefing
    globals()["_bedrock_tailor_pharmacy_message"] = _mock_pharmacy_message
    globals()["_bedrock_chase_brief"] = _mock_chase_brief

    print(f"  Patients: {len(patients_list)}")
    print(f"  Encounters tomorrow: {len(next_day_schedule)}")

    print("\n" + "=" * 70)
    print("Running pipeline Steps 1-4 against synthetic data...")
    print("=" * 70)

    summary = run_daily_batch(
        patients_list=patients_list,
        next_day_schedule=next_day_schedule,
        run_date=run_date,
    )
    print(f"\nBatch summary: {summary}")

    # ---- Step 5: simulate a closure event ----
    print("\n" + "=" * 70)
    print("Simulating a closure event to exercise Step 5...")
    print("=" * 70)

    measure_lookup = {m["measure_id"]: m for m in SAMPLE_MEASURE_REGISTRY}

    print("\n  -> claims-source flu-equivalent for pat-000482 "
          "(pneumococcal CPT 90670)...")
    process_closure_event({
        "event_type":        "closure_source_event",
        "patient_id":        "pat-000482",
        "source":            "claims",
        "qualifying_codes":  ["90670"],
        "timestamp":         _now_iso(),
        "payload": {
            "code":         "90670",
            "service_date": run_date,
            "source_id":    "synthetic-claim-001",
        },
    }, measure_lookup)

    # ---- Step 6: simulate a clinician override ----
    print("\n" + "=" * 70)
    print("Simulating a clinician override to exercise Step 6...")
    print("=" * 70)

    # Inject a synthetic briefing record so the override has a referent.
    brief_table = dynamodb.Table(CLINICIAN_BRIEFINGS_TABLE)
    sample_briefing_id = _make_briefing_id(next_day_schedule[0], run_date)

    print("\n  -> override: clinical_judgment_defer on colorectal screening")
    process_clinician_override({
        "event_type":      "clinician_override",
        "briefing_id":     sample_briefing_id,
        "patient_id":      "pat-000482",
        "provider_id":     "prov-014",
        "measure_id":      "uspstf-colorectal-screening",
        "reason":          "clinical_judgment_defer",
        "free_text_note":  "Discussed with patient; declining at this visit; "
                            "will reconsider in 90 days as renal status stabilizes.",
        "timestamp":       _now_iso(),
    })

    print("\n=== Demo complete ===")
```

---

## The Gap Between This and Production

Run this end-to-end against a curated measure registry, populated claims/EHR/lab/pharmacy/immunization-registry feeds, trained SageMaker urgency and engagement models, working visit schedule integration, configured outreach channels, and you'll see the pattern: per-(patient, measure) state machine maintained correctly, urgency and per-pathway probabilities scored, visit-context ranked, async pathways allocated, multi-source closures reconciled, and clinician overrides captured as retraining signal. The distance between this and a real health-plan deployment is significant. Here's where it lives.

**Measure registry curation as an ongoing program.** The registry is the source of truth for what counts as a gap, and it has to be maintained continuously. Annual NCQA HEDIS revisions, CMS Stars technical updates, USPSTF guideline changes, and contract-specific measure additions all require registry updates. Plan for at least 0.5 to 1.0 FTE of clinical-informatics time on registry maintenance ongoing, with structured change-management: proposed change, evidence packet, version bump, parallel evaluation against the prior version on a sample to quantify population impact, then promotion. 

**Measure-spec parity testing against the plan's HEDIS vendor.** The recommender's gap evaluation will not exactly match the plan's HEDIS vendor's numerator counts; small implementation differences in value sets, lookback boundary handling, and supplemental-data inclusion can shift numerators by 1 to 3 percentage points. Build a parity test that runs nightly comparing the recommender's open-gap counts to the vendor's open-gap counts at the population level, with alerting on divergence beyond an established tolerance. Persistent divergence is an alignment task with the vendor, not a model failure.

**Multi-source data ingestion.** The example queries from synthetic in-memory dicts. Production ingests from at least six distinct source types: claims (EDI 837 from PBM and provider feeds), EHR (FHIR API or batch flat-file export per EHR vendor; Epic, Oracle Health, Athena, Veradigm each have their own integration shape), lab feeds (HL7 v2 ORU messages or FHIR Observation resources from clinical lab partners), pharmacy data (NCPDP-formatted feeds and immunization administration data), state immunization registries (ImmReg APIs in some states, batch flat files in others), and patient self-report (portal/app submissions with consent capture). Each requires its own ingestion adapter, normalization, and reconciliation. Plan 8 to 16 weeks of ingestion engineering before the first gap evaluation run, plus an ongoing source-feed health dashboard.

**Multi-source closure reconciliation engineering.** Closure events arrive out of chronological order, with periodic restated/corrected records (a registry that re-submits last month's data with updates each month). The reconciliation logic needs to be tolerant of late-arriving data, partial redactions for consent-restricted records, and source-specific reliability profiles. The state-machine semantics in this example assume well-formed events; production handles malformed and partially-formed events explicitly, with explicit outage handling per source.

**Clinical-urgency model training data.** The urgency models in this example are rule-based. Production-grade urgency estimation requires longitudinal outcome data with confounding adjustment (the patients who close their gaps differ systematically from those who don't, and naive estimation will overstate urgency for non-engaged patients). Plan 6 to 12 months of training data preparation per measure family, with explicit handling of confounding via propensity weighting or instrumental-variable methods if randomization isn't feasible. This is a Chapter 7 (Risk Scoring) problem layered into the care gap recommender.

**Engagement and closure-probability training data.** Same pattern as 4.4 and 4.5. Real engagement-and-closure modeling requires either a randomized hold-out arm in a prior cycle or careful propensity-score adjustment on observational data. The honest day-one launch path: ship the pipeline with rule-based urgency and engagement only; carve out a 10-20 percent randomized hold-out for each pathway for one or two cycles to generate training data; turn on supervised scoring as the pilot data accrues; document explicitly that early runs are calibrating, not optimized.

**SageMaker Feature Store integration.** The example skips Feature Store usage. Production wires per-(patient, measure) feature ingestion through Glue or Spark into both the offline and online stores, with feature freshness guarantees per source. The feature definitions are reused across Recipes 4.4, 4.5, 4.6, and 4.7; centralizing them is the entire point.

**SageMaker Batch Transform output schema.** The example replaces real Batch Transform calls with rule-based proxies. Production: define an explicit output schema per model (ideally JSONL with named fields), validate it on every job completion, version the schema alongside the model. A model upgrade that silently changes output column order is a production failure mode that's painful to debug.

**SageMaker training-job trigger and promotion path.** The architecture diagram shows "Periodic retrain" without an explicit trigger or promotion path. Production wires the urgency and engagement-model retraining via either an EventBridge schedule (e.g., monthly) or a CloudWatch metric threshold (e.g., closure-rate drift exceeds X). New models go through SageMaker Model Registry with a canary run on a held-out cohort before promotion to production endpoints; canary failures trigger rollback and Slack alerts.

**Eligibility and gap-evaluation SQL via Glue, not application code.** The example builds denominator/numerator/exclusion logic in Python for clarity. Production uses parameterized SQL templates (Jinja or a SQL-construction library) so denominator predicates are SQL queries that scale across millions of patient-rows. A typo in a value-set definition that becomes SQL injection is not the production failure mode you want.

**Step Functions orchestration with explicit DLQ coverage.** The example chains Steps 1-4 in a single Python function. Production runs the daily batch as a Step Functions state machine with Map states for parallel evaluation per measure, parallel scoring per pathway, and per-encounter ranking. Each task has Catch handlers routing failures to per-stage SQS DLQs keyed on (run_date, stage, failure_reason). The Kinesis-to-Lambda event source mapping for the closure tracker needs an explicit `OnFailure` destination pointing to SQS, alarmed on DLQ depth. A silently-dropped closure event is operationally damaging in this recipe (the chase team calls a patient who already closed the gap), so the DLQ coverage matters more here than in some prior recipes.

**Bedrock cost and latency budget.** The example calls Bedrock per visit-encounter for clinician briefings, per allocated chase queue for chase briefs, and per allocated patient nudge for message tailoring. At 10K visits/day plus 50K async pathway dispatches/week, the budget is manageable with Haiku-class models. Production caches tailored content by (measure_id, language, cohort_features hash) since many candidates share the same effective context, and only calls Bedrock for unique cases. Monitor Bedrock spend in CloudWatch and set per-account quota alarms.

**LLM candidate-gap surfacer review queue.** The example populates the review queue but doesn't ship a UI. Plan for 10 to 20 hours per week of clinical-informatics time on the review queue (varies by sample size and surfacing aggressiveness) plus a review UI that lets reviewers approve patterns into the registry, reject candidates, or escalate to medical-director review. Without the staffing, the queue grows indefinitely and the surfacer becomes shelfware. If you can't staff the review, scope the surfacer to a small, well-defined set of patient types where the patterns are most likely to be valuable.

**Visit-context features need to be accurate.** The visit-context ranker depends on knowing the visit type, the typical visit duration for the provider, the acute context, and the clinician's closure habits. Visit-type metadata in scheduling systems is often noisy or inconsistent; "annual wellness visit" can mean different things across providers; visit-duration estimates vary widely. Production deployment requires investing in scheduling-data quality: a clean visit-type taxonomy, per-provider visit-duration calibration from historical encounter data, and a feedback loop where clinician overrides update the model's understanding of visit fit.

**Suppression-rule governance.** The suppression policies tied to clinician-override reasons have material impact on patient care. A "patient_refusal" suppressed for 180 days is a reasonable default; suppressed for 18 months is a patient-safety problem when the clinical context shifts. Each suppression rule needs an exception-condition mapping: shifts in clinical context that should reopen the gap regardless of prior suppression (a new abnormal lab, a new diagnosis, a hospitalization). The example codes only the day-count; production codes the full exception-condition logic.

**Tracking-ID privacy.** The example builds tracking IDs as `f"gap-{run_date}-{patient_id}-{measure_id}-{pathway}"` for readability. Production must replace this with an opaque, non-reversible identifier (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plain-text patient_ids and measure_ids embedded in tracking IDs (carried in email open-tracking pixels, SMS click-through links, EHR inbox URLs, vendor outreach handoffs) are PHI leakage. The `_make_tracking_id` helper in this file flags this; fix it before any non-development deployment. Same applies to `_make_briefing_id`.

**DynamoDB Decimal gotchas.** The example uses `_to_decimal` and `_to_decimal_dict` consistently when persisting numeric values. The pattern is correct, but the trap is real: if you add a feature that persists a model confidence, an embedding magnitude, or any other floating-point value, you must wrap it at the boundary or DynamoDB will reject the write.

**Cohort-feature PHI sensitivity.** The patient-gaps and clinician-briefings tables are highly inferential PHI. A row indicating "patient has open mental-health-follow-up gap with high urgency" is much more sensitive than a row indicating "patient has open flu-shot gap." Apply tighter controls to gap state for stigmatized or high-sensitivity measures (mental health, substance use, HIV-related, reproductive health): narrower IAM read scopes, optional separate-table partitioning, additional CloudTrail data event capture, and a documented minimum-necessary access policy. SDOH cohort labels in `cohort_features` (e.g., `transportation_barrier`, `low_food_security`) are PHI-equivalent and should follow the minimum-necessary principle.

**Cross-recipe orchestration with Recipes 4.4, 4.5, and 4.7.** A patient with multiple care gaps, multiple non-adherent medications, a wellness program enrollment recommendation, and a care-management eligibility flag can easily exceed any reasonable contact-frequency budget if each recipe orchestrates independently. The example checks `_cross_recipe_suppresses` as a stub. Production needs an explicit priority-arbitration policy: when 4.4, 4.5, 4.6, and 4.7 all want to message the same patient and the global cap allows only one, what wins? Default proposal: weighted priority across recipes with a clinical-urgency tiebreaker, with explicit documentation that operationally-attractive recipes (4.5 adherence reminders near year-end, 4.6 quality-measure-driven gaps near window close) cannot crowd out the high-clinical-urgency cohorts from 4.4 (DPP for newly diagnosed diabetes) or 4.6 (rising eGFR with no CKD conversation). The cross-recipe orchestrator owns the policy enforcement; per-recipe orchestrators read and update the shared `outreach_recent_30d_count` counter.

**Outreach-message governance for care gap content.** Care gap reminders are a regulated communication category, and the rules vary by gap type. State pharmacy boards have varying rules on vaccination prompts. CMS has guidance on Medicare Advantage member communications. Some health-condition prompts (cancer screening, depression screening) have additional state-specific consumer-protection rules. Engage compliance counsel on per-measure messaging before launch. The validator in this example checks shape and a small blocklist; production extends with: required disclosures per state, an approved-claims list per measure, a prohibited-claims regex/blocklist, and an approved-claims-only check against a per-measure approved-claims artifact owned by clinical/compliance. Failure-handling: schema/length failures fall back to a templated default; clinical-claim or prohibited-claims failures defer the outreach with reason `validator_failed:<reason>` and flag for human review.

**Multilingual outreach quality.** The example passes the preferred language to the LLM and trusts the output. Production: per-language regression suites (curated input/expected-output quality pairs) that run on every model version change; per-language member-feedback dashboards; a low-confidence fallback to the default localized template when LLM output fails validation. Spanish, Mandarin, Vietnamese, and Tagalog have different LLM quality characteristics and different cultural conventions for health communication.

**EHR briefing integration.** The example "posts" the briefing by writing to DynamoDB. Real EHR integration: Epic, Oracle Health (Cerner), Athena, Veradigm each have their own SMART-on-FHIR or proprietary integration surface. Each requires a purpose-built adapter Lambda (or vendor-managed integration), per-EHR credential management in Secrets Manager, message format mapping (FHIR Communication resource, Epic InBasket, etc.), and a write-back path so the clinician's response (acted, dismissed, deferred) flows back into the override-event stream. The integration work is on the order of months per EHR.

**Specialist-coordination workflows.** For gaps that close via specialist visits (retinal exam, mammogram, colonoscopy, behavioral-health follow-up), build an end-to-end coordination workflow: scheduling assistance, transportation help, prior auth, reminder cascades, result-return-tracking, and PCP notification. The example dispatches to a `referral_management` channel as a placeholder; production wires this to your referral-management vendor or in-house workflow. Plans that invest in this coordination see materially higher referral-completion rates than plans that send a referral and hope.

**Equity floor design.** The equity floors in this example reserve fixed capacity per cohort. Designing the floors well requires baseline cohort closure data (which you don't have until you've been operating for some time), explicit policy on which disparities trigger floors versus other interventions, and willingness to accept that you'll be wrong sometimes about which cohorts need protection. Start with conservative floors, monitor cohort closure-rate parity, expand floors where parity remains poor, and revisit quarterly. Don't try to design the perfect equity floor on day one; design the right operating cadence for adjusting them.

**Idempotency and retry semantics.** Each stage's outputs are addressed by deterministic keys (run_date, measure_id, patient_id) and writes should be conditional, so a Step Functions retry that re-attempts a completed step is a no-op rather than a duplicate. The example uses `put_item` and `update_item` without conditions; production adds `ConditionExpression` to the relevant writes (e.g., `attribute_not_exists(tracking_id)` on the recommendation-log put) so reattempted writes converge.

**Outreach-failure reconciliation paths.** The example optimistically increments `outreach_recent_30d_count` on dispatch but doesn't decrement on failure. Production handles `gap_outreach_failed` and `gap_outreach_bounced` events by decrementing the counter (with a `ConditionExpression` that prevents going below zero). Add: a stale-pending sweep for tracking_ids with no engagement-stream activity within 24 hours (suggests a vendor-side processing failure), a per-channel failure-rate alarm (sudden spike in SES bounces or Pinpoint failures triggers operations attention), and a per-vendor reconciliation report against the recommendation log (any tracking_id we expected to dispatch that never produced any event is a missing-handoff candidate).

**Star Ratings and HEDIS cycle awareness.** Quality-measure measurement years are calendar-aligned, with cut points published in the spring for the prior measurement year. The recommender should know where in the measurement cycle each target gap sits (months remaining for the measure to close in the current measurement year). Encode the cycle in the policy. Define explicit `chase_period_weight_overrides` that activate between specific dates so the year-end push doesn't quietly redistribute effort to the easiest-to-close gaps in the cohorts already best-served by the program.

**Patient-friendly closure visibility.** Patients should see their own care gaps and closures in the patient portal, with explanations they can understand. "You are due for a screening colonoscopy" is more useful than "HEDIS COL-E open." Patient-facing summaries are a separate UX project, with content review by health-literacy specialists, but the gap state machine in this recipe is the source data for that view. Plan the patient-facing layer as a parallel deliverable.

**Real-time closure-suppression triggers.** Beyond the daily reconciliation cycle, an EventBridge rule can fire on incoming closure events and suppress in-flight outreach for the matching gap immediately. Patients who got the flu shot at the pharmacy on Saturday should not receive a Monday morning robocall. The latency between closure and suppression is the most operationally visible failure mode of these systems; pushing it from hours to minutes is high-leverage. The example processes closure events synchronously; production uses a Lambda triggered on the Kinesis stream for sub-minute latency.

**Cost-per-closure tracking.** The cost numbers in the main recipe's Prerequisites table are infrastructure only. Production reporting needs to ladder up to per-measure total cost (infrastructure + staff time + outreach vendor invoices + referral logistics) divided by confirmed closures attributable to the program (above the matched-control baseline). That number is what gets compared to the value of closure (HEDIS bonus for measure-bound gaps, clinical-outcome benefit for clinically-driven gaps). The data engineering to track this end-to-end with attribution is its own project.

**VPC, encryption, and audit.** This example calls APIs over public AWS endpoints. A production Lambda handling PHI runs in a VPC with private subnets and VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock Runtime (interface), SageMaker Runtime and Feature Store (interface), Kinesis (interface), CloudWatch Logs (interface), Athena (interface), Step Functions (`states`), EventBridge (`events`), STS, SES, Pinpoint, and Connect. All seven DynamoDB tables encrypt at rest with a customer-managed KMS key. CloudTrail data events are enabled for the patient-gaps, measure-registry, clinician-briefings, clinician-overrides, recommendation-log, and patient-profile tables. A clinical or compliance audit will eventually ask "who was recommended for what on this date and why" and you need to answer definitively.

**Synthetic data and testing.** There are no tests in this example. A production pipeline needs unit tests for the denominator/numerator/exclusion logic per measure; the state-machine transitions; the visit-fit math; the heterogeneous allocator with equity floors; integration tests against a synthetic Synthea-generated patient population across cohort axes; regression tests that confirm hard exclusion rules (palliative care, hospice) are never bypassed; load tests at expected volumes (250K eligible patients, 40 measures, 1M (patient, gap) rows daily); chaos tests that drop a SageMaker job mid-pipeline and verify Step Functions resumes from the right state. Never use real PHI in non-production environments. [Synthea](https://github.com/synthetichealth/synthea) generates synthetic FHIR patients with realistic conditions and procedures suitable for the gap pipeline.

**Cohort fairness review process.** The architecture emits cohort-sliced metrics, but a dashboard nobody reviews is useless. Establish a quarterly review with a cross-functional committee (data science, equity lead, medical director, quality lead, operations lead). Watch for: gap-identification rate disparities by cohort (a measure that produces 3x more open gaps in one cohort versus another may reflect actual unmet need or data-completeness disparities; the dashboard surfaces both); urgency-score distribution disparities; in-visit closure rate disparities by cohort and clinician; referral-completion rate disparities; long-horizon closure-rate disparities. Each finding produces an action item with an owner.

**Outcome evaluation methodology rigor.** The example doesn't ship an outcome-evaluation function; the architecture diagram shows it, but the implementation is intentionally out of scope for a recipe demonstration. Production: pre-register the analysis specification before each evaluation runs (define cohort definitions, outcome definitions, primary statistical test up front), run sensitivity analyses against alternative matching specifications, have a statistical reviewer who is not the team running the recommender, document the methodology in a memo signed by the medical director and the equity lead. Watch especially for the "the program drove closure rates up but didn't move clinical outcomes" trap discussed in the main recipe's Honest Take.

**Cold-start handling for new measures.** The example assumes every measure has trained urgency and engagement models. A brand-new measure has neither. Cold-start strategy: launch new measures with rule-based urgency only (no supervised model), run a randomized pilot for the first 1-2 cycles to bootstrap engagement training data, fall back to baseline urgency if the model is underfitting, document explicitly in the recommendation log that the measure is in "calibrating" mode.

**Data-quality flag propagation.** The `data_quality_flag` is set per (patient, measure) but downstream consumers in this example don't gate on it. Production should: skip outreach when the flag is `cross_provider_fragmentation` (the gap might already be closed at a non-network provider); de-prioritize when the flag is `sparse_history`; escalate to clinical-informatics review when the flag is `multi_source_disagreement` and the urgency is high. A confidently "open" gap on a patient with `cross_provider_fragmentation` is a confidently wrong recommendation if the patient already had the procedure elsewhere.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 4.6: Care Gap Prioritization](chapter04.06-care-gap-prioritization) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
