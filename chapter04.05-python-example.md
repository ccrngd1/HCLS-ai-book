# Recipe 4.5: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 4.5. It shows one way you could translate the medication-adherence intervention-targeting pattern into working Python using AWS Glue / Athena for adherence computation and eligibility filtering, Amazon SageMaker (Feature Store, Batch Transform, Training) for the model stack, Amazon DynamoDB for the intervention catalog, recommendation log, barrier classifications, and patient profile, Amazon S3 for the data lake, AWS Step Functions for orchestration, AWS Lambda for the per-stage glue, Amazon Bedrock for barrier-classification second opinion, message tailoring, and pharmacist pre-call briefs, Amazon Kinesis for engagement and pharmacy events, and Amazon SES / Amazon Pinpoint / Amazon Connect for outreach delivery. It is not production-ready. There is no real PBM ingestion, no NCPDP X12 parsing, no validated PDC methodology against PQA specifications, no randomized-pilot infrastructure, no production propensity-score modeling, no LP-based heterogeneous allocator, no live PCP-EHR integration, no real outcome-evaluation methodology with pre-registration. Think of it as the sketchpad version: useful for understanding the shape of an adherence recommender that respects barriers and heterogeneous interventions, not something you'd wire into a 400,000-member health plan on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the eight pseudocode steps from the main recipe: compute per-(patient, medication) adherence features (PDC done with carry-forward and lag awareness), classify barriers (rules + supervised + LLM second opinion), build the (patient, intervention, medication) candidate set with eligibility, score need / barrier-fit / engagement / uplift in parallel, combine into priority with cost-effectiveness, allocate under heterogeneous capacities with multi-intervention-per-patient and equity floors, orchestrate outreach across channels (member-facing reminders, pharmacist queues, cost-assistance staff queues, partner-pharmacy APIs, EHR care-team inbox), and capture engagement / fill / barrier-elicited events for short-, medium-, and long-horizon training. All sample patients, medications, fills, interventions, and engagement signals are synthetic.

---

## Setup

You'll need the AWS SDK for Python and a couple of utility libraries:

```bash
pip install boto3 pandas numpy
```

For the local uplift-modeling demo (Step 4's training portion, not shown in the inference path) you'd add `econml` or `causalml`. The inference path itself only needs the SageMaker Batch Transform output, so the production Lambdas don't import those libraries.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `sagemaker:CreateTransformJob`, `sagemaker:DescribeTransformJob` on specific model ARNs (the per-class need scorers, per-intervention engagement predictors, per-intervention uplift estimators, supervised barrier classifier)
- `sagemaker:GetRecord`, `sagemaker:BatchGetRecord`, `sagemaker:PutRecord` on the SageMaker Feature Store feature group ARNs (`patient-medication-adherence`, `patient-regimen`)
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchWriteItem` on the intervention-catalog, patient-profile, recommendation-log, barrier-classifications, engagement-events, and pcp-overrides tables
- `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on the pharmacy-data-lake, feature-store offline, candidates, scores, and recommendation-output buckets
- `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults` for the adherence-computation pipeline
- `glue:GetTable`, `glue:GetPartitions` on the data-catalog tables Athena reads
- `bedrock:InvokeModel` on the specific model ARNs used for barrier classification, member-facing message tailoring, and pharmacist pre-call brief generation (e.g., a Claude Haiku or Nova Lite model)
- `kinesis:PutRecord` on the engagement stream
- `ses:SendEmail` scoped to the BAA-covered identity (or `pinpoint:SendMessages` for SMS)
- `connect:StartOutboundContact` (only if using Amazon Connect for in-house pharmacist outreach), scoped to the pharmacist-queue contact flow
- `cloudwatch:PutMetricData` for cohort-sliced metrics
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs

You also need model access enabled in the Bedrock console for the barrier-classification, message-tailoring, and pharmacist-brief models.

A few things worth knowing upfront:

- **The barrier classifier is the part most plans skip and the part that distinguishes a good adherence program from a reminder spam campaign.** This example wires the rule-based classifier as the primary signal, treats the supervised classifier as a refinement, and uses the LLM as a second opinion for high-stakes cases. Production needs a structured pharmacist-consult protocol that captures barrier labels at meaningful volume; without it, the supervised classifier never learns past its rule-based baseline.
- **The uplift model is the second-hardest part.** Same caveat as Recipe 4.4: production-grade uplift estimation requires either a randomized hold-out arm or careful propensity-score adjustment on observational data. The training script is out of scope for this companion; the main recipe's "Why This Isn't Production-Ready" section walks through the gap.
- **Bedrock model IDs change over time.** Some regions require cross-region inference profile IDs (prefixed `us.` or `eu.`). The IDs below are reasonable defaults; verify in the Bedrock console for your region before running.
- **All patients, fills, interventions, and engagement events in the example are synthetic.** Do not treat any specific patient_id, NDC, fill date, copay, or engagement signal as real. A production system ingests from a real PBM feed under BAA.
- **The example collapses Step Functions, Glue, Athena, and SageMaker Batch Transform into a single Python file for readability.** In production these are separate workflow stages with their own error handling, IAM, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, table names, S3 buckets, allocator policy weights, equity floors, contact-frequency caps, copay thresholds, and tracked therapeutic classes are the knobs you'll change between environments.

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
# CloudWatch Logs Insights. Never log a raw (patient_id, therapeutic_class,
# barrier) join along with clinical context; the row implicitly identifies
# both the medication and the suspected reason. The barrier-classifications
# table and the recommendation log are highly inferential PHI.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from SageMaker, DynamoDB, Bedrock,
# Kinesis, S3, Athena, and SES during the weekly batch run. Adherence
# adds pharmacy-claim ingestion bursts on top of the recommendation
# load; both stages share the same retry envelope.
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
# quality regressions, not on a single uniform default.
BARRIER_CLASSIFIER_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"
REMINDER_MODEL_ID           = "anthropic.claude-3-5-haiku-20241022-v1:0"
PHARMACIST_BRIEF_MODEL_ID   = "anthropic.claude-3-5-haiku-20241022-v1:0"
PCP_BRIEFING_MODEL_ID       = "anthropic.claude-3-5-haiku-20241022-v1:0"

# Names of the SageMaker model artifacts. The need scorer is per
# therapeutic class (the clinical risk of continued non-adherence
# differs enough between statins and oral diabetes meds that one
# model per class produces better calibration). Engagement and uplift
# are per intervention (a text reminder's engagement signature is
# not the same as a pharmacist-consult's signature).
NEED_MODEL_NAMES = {
    "statins":              "need-statins-v4",
    "ras_antagonists":      "need-ras-v3",
    "oral_diabetes":        "need-oral-diabetes-v4",
}
ENGAGEMENT_MODEL_NAMES = {
    "text_reminder":        "engagement-text-v3",
    "education":            "engagement-education-v2",
    "pharmacist_consult":   "engagement-pharmacist-v3",
    "cost_assistance":      "engagement-cost-assist-v2",
    "med_sync":             "engagement-med-sync-v1",
    "regimen_simplification": "engagement-regimen-v1",
}
UPLIFT_MODEL_NAMES = {
    "text_reminder":        "uplift-text-v2",
    "education":            "uplift-education-v1",
    "pharmacist_consult":   "uplift-pharmacist-v2",
    "cost_assistance":      "uplift-cost-assist-v2",
    "med_sync":             "uplift-med-sync-v1",
    "regimen_simplification": "uplift-regimen-v0",   # v0: still calibrating
}
SUPERVISED_BARRIER_MODEL_NAME = "barrier-supervised-v3"

# --- DynamoDB Table Names ---
# Six tables. Keep them separate so access patterns stay clean and
# IAM scoping is precise:
#   1. intervention-catalog:        canonical intervention record (intervention_id PK)
#   2. patient-profile:             member demographics, prefs, regimen meta (patient_id PK)
#   3. recommendation-log:          per (patient, intervention, medication, run_date) row
#   4. barrier-classifications:     per (patient, therapeutic_class) ranked-barriers row
#   5. engagement-events:           raw events (event_id PK; tracking_id GSI)
#   6. pcp-overrides:               PCP-declined recommendations for clinical review
INTERVENTION_CATALOG_TABLE     = "intervention-catalog"
PATIENT_PROFILE_TABLE          = "patient-profile"
RECOMMENDATION_LOG_TABLE       = "recommendation-log"
BARRIER_CLASSIFICATIONS_TABLE  = "barrier-classifications"
ENGAGEMENT_EVENTS_TABLE        = "engagement-events"
PCP_OVERRIDES_TABLE            = "pcp-overrides"

# --- S3 Buckets and Prefixes ---
# Production: each bucket has its own KMS key and bucket policy. The
# example uses placeholder names; replace with your account's buckets.
PHARMACY_DATA_LAKE_BUCKET      = "adherence-pharmacy-data-lake"
TARGET_SET_BUCKET              = "adherence-target-set"
CANDIDATES_BUCKET              = "adherence-candidates"
SCORES_BUCKET                  = "adherence-scores"
FEATURE_STORE_OFFLINE_BUCKET   = "adherence-feature-store-offline"
ATHENA_RESULTS_BUCKET          = "adherence-athena-results"

# --- Athena ---
ATHENA_WORKGROUP = "adherence-recommender"
ATHENA_DATABASE  = "adherence_data_lake"

# --- Kinesis ---
# Engagement stream pattern reused from Recipes 4.1-4.4, with new
# event types: pharmacy_fill_observed, refill_gap_detected,
# adherence_intervention_recommended, intervention_outreach_sent,
# intervention_engaged, intervention_completed, barrier_elicited,
# med_sync_enrolled, cost_assistance_initiated,
# cost_assistance_approved, pcp_override, pharmacist_consult_completed.
ENGAGEMENT_STREAM_NAME = "engagement-stream"

# --- SES ---
SES_FROM_ADDRESS         = "adherence@example-health-plan.org"
SES_CONFIGURATION_SET    = "adherence-baa"

# --- Tracked Therapeutic Classes ---
# The three CMS Star Ratings Part D adherence measures plus a few
# common chronic classes. Production: align to the current PQA
# (Pharmacy Quality Alliance) measure specifications, which CMS
# updates periodically.
TRACKED_THERAPEUTIC_CLASSES = [
    "statins",
    "ras_antagonists",      # ACE inhibitors, ARBs
    "oral_diabetes",        # metformin, SGLT2, DPP-4, sulfonylureas, etc.
    "anticoagulants",
    "respiratory_inhalers",
]

# --- PDC Computation ---
# 30-day settled lag: retail claims arrive on a 1-2 day lag, mail-order
# on a 5-14 day lag, and specialty up to 30. Computing PDC against
# claims that haven't all arrived yet produces noisy, biased numbers
# that systematically under-estimate adherence for mail-order users.
SETTLED_LAG_DAYS    = 30
PDC_WINDOW_365_DAYS = 365
PDC_WINDOW_90_DAYS  = 90

# --- Adherence Threshold ---
# CMS Star Ratings adherent-threshold: PDC >= 0.80. Below this, the
# patient is considered non-adherent for measurement purposes.
PDC_ADHERENT_THRESHOLD = 0.80

# --- Barrier Classifier Thresholds ---
# Tuned with a clinical pharmacist; production calibration uses the
# pharmacist-elicited-barrier dataset to tune precision/recall by
# barrier per therapeutic class.
COPAY_HIGH_THRESHOLD            = 35.0   # USD; above this, cost barrier is plausible
NEED_REVIEW_THRESHOLD           = 0.70   # need score above which LLM disagreement triggers review
LLM_LOW_CONFIDENCE_THRESHOLD    = 0.55   # blended top-1 below which LLM is consulted
SYMPTOMATIC_LATENT_CLASSES      = {"statins", "ras_antagonists"}

# Barrier taxonomy. Six categories; never collapse to a single label.
BARRIER_CATEGORIES = ["cost", "forgetfulness", "beliefs", "side_effects",
                      "complexity", "access"]

# --- Allocator Policy Weights ---
# Documented, version-controlled, reviewable. The cost_efficiency
# weight is what stops a $80 pharmacist consult from being chosen over
# a $0.05 reminder for every candidate where uplift is similar. The
# weights are policy: a cross-functional review (medical director,
# pharmacist lead, equity lead, data science) sets these.
POLICY_WEIGHTS = {
    "need":             0.25,
    "barrier_fit":      0.20,
    "engagement":       0.10,
    "uplift":           0.35,
    "cost_efficiency":  0.10,
}

# --- Per-Patient Caps ---
# Documented caps on how aggressively the recommender targets a single
# patient in one run. Without these, the optimization can stack 5
# interventions on the most-targetable patient and zero on patients
# with weaker model signal but real clinical need.
MAX_INTERVENTIONS_PER_PATIENT_PER_RUN  = 2
MAX_HIGH_TOUCH_PER_PATIENT_PER_RUN     = 1
MAX_CONTACTS_PER_PATIENT_30D           = 3

# --- Cost-efficiency Math Guard ---
# Avoid divide-by-zero when intervention cost is zero (e.g., a
# fully manufacturer-funded reminder).
MIN_COST_FOR_DIVISION = 0.01

# --- Run Configuration ---
POLICY_VERSION = "adherence-policy-v0.3"

# CloudWatch namespace for adherence metrics. Slice by intervention
# type, therapeutic class, language, engagement-history quartile, and
# SDOH cohort to catch subgroup drift.
METRIC_NAMESPACE = "AdherenceRecommender"
```

---

## Reference Data: Synthetic Intervention Catalog

A small intervention catalog used by the example. Production loads from the `intervention-catalog` DynamoDB table, fed by vendor-portal integrations and a clinical/contracting review. Each intervention has structured eligibility (LIS-only, brand-only, partner-pharmacy-only), supported barriers (which barriers this intervention addresses, and at what fit), capacity, and marginal cost.

```python
# Synthetic intervention catalog. In production this lives in DynamoDB
# and is updated by the catalog-sync Lambda when vendors push catalog
# changes through EventBridge. Each `supported_barriers` map gives the
# intervention's fit per barrier in [0, 1]; the barrier-fit score is
# the dot product of the patient's ranked-barriers vector with this
# map.
SAMPLE_INTERVENTIONS = [
    {
        "intervention_id":          "text-reminder-001",
        "type":                     "text_reminder",
        "display_name":             "Standard SMS Refill Reminder",
        "supported_barriers": {
            "forgetfulness":         1.0,
            "complexity":            0.4,
            "cost":                  0.0,
            "beliefs":               0.0,
            "side_effects":          0.0,
            "access":                0.0,
        },
        "marginal_cost":            0.05,        # cents per send
        "daily_capacity":           50000,        # essentially unbounded
        "is_high_touch":            False,
        "generates_patient_contact": True,
        "brand_only":               False,
        "requires_lis":             False,
        "requires_partner_pharmacy": False,
        "supported_languages":      ["en", "es"],
        "cooldown_days":            7,
        "default_template":         "reminder-default-en",
    },
    {
        "intervention_id":          "education-001",
        "type":                     "education",
        "display_name":             "Statin Education Module",
        "supported_barriers": {
            "beliefs":               0.8,
            "side_effects":          0.4,
            "forgetfulness":         0.1,
            "cost":                  0.0,
            "complexity":            0.0,
            "access":                0.0,
        },
        "marginal_cost":            0.50,
        "daily_capacity":           5000,
        "is_high_touch":            False,
        "generates_patient_contact": True,
        "brand_only":               False,
        "requires_lis":             False,
        "requires_partner_pharmacy": False,
        "supported_languages":      ["en", "es"],
        "cooldown_days":            30,
        "default_template":         "education-statin-default-en",
        "applicable_classes":       ["statins"],
    },
    {
        "intervention_id":          "pharmacist-consult-001",
        "type":                     "pharmacist_consult",
        "display_name":             "Telephonic Clinical Pharmacist Consult",
        "supported_barriers": {
            "beliefs":               0.9,
            "side_effects":          0.95,
            "complexity":            0.7,
            "cost":                  0.5,        # pharmacist can route to cost-assist
            "forgetfulness":         0.5,
            "access":                0.6,
        },
        "marginal_cost":            55.00,       # FTE time per substantive consult
        "daily_capacity":           80,           # 4 pharmacists * 20 consults/day
        "is_high_touch":            True,
        "generates_patient_contact": True,
        "brand_only":               False,
        "requires_lis":             False,
        "requires_partner_pharmacy": False,
        "supported_languages":      ["en", "es"],
        "cooldown_days":            90,
        "default_template":         "pharmacist-default",
    },
    {
        "intervention_id":          "cost-assist-001",
        "type":                     "cost_assistance",
        "display_name":             "Cost-Assistance Navigation",
        "supported_barriers": {
            "cost":                  1.0,
            "access":                0.3,
            "beliefs":               0.0,
            "side_effects":          0.0,
            "forgetfulness":         0.0,
            "complexity":            0.0,
        },
        "marginal_cost":            45.00,       # case-mgmt time per application
        "daily_capacity":           40,
        "is_high_touch":            True,
        "generates_patient_contact": True,
        "brand_only":               False,        # also covers formulary alternatives
        "requires_lis":             False,
        "requires_partner_pharmacy": False,
        "supported_languages":      ["en", "es"],
        "cooldown_days":            180,
        "default_template":         "cost-assist-default",
    },
    {
        "intervention_id":          "med-sync-001",
        "type":                     "med_sync",
        "display_name":             "Pharmacy Med-Sync Enrollment",
        "supported_barriers": {
            "complexity":            0.95,
            "forgetfulness":         0.6,
            "cost":                  0.1,
            "beliefs":               0.0,
            "side_effects":          0.0,
            "access":                0.4,
        },
        "marginal_cost":            8.00,         # one-time enrollment + ongoing
        "daily_capacity":           120,
        "is_high_touch":            False,
        "generates_patient_contact": True,
        "brand_only":               False,
        "requires_lis":             False,
        "requires_partner_pharmacy": True,
        "supported_languages":      ["en", "es"],
        "cooldown_days":            365,
        "default_template":         "med-sync-default",
    },
    {
        "intervention_id":          "regimen-simplify-001",
        "type":                     "regimen_simplification",
        "display_name":             "PCP Regimen Simplification Referral",
        "supported_barriers": {
            "complexity":            0.95,
            "forgetfulness":         0.5,
            "side_effects":          0.3,
            "beliefs":               0.1,
            "cost":                  0.0,
            "access":                0.0,
        },
        "marginal_cost":            12.00,        # care-team coordination time
        "daily_capacity":           50,
        "is_high_touch":            False,
        "generates_patient_contact": False,       # PCP-mediated, not patient-direct
        "brand_only":               False,
        "requires_lis":             False,
        "requires_partner_pharmacy": False,
        "supported_languages":      ["en", "es"],
        "cooldown_days":            180,
        "default_template":         "regimen-simplify-default",
    },
]

# Partner-pharmacy IDs that support med-sync via API. Production: a
# DynamoDB lookup or a small config table maintained by the contracts
# team. Pharmacy chains and PSAOs join and leave the partnership list
# at quarterly cadence; treat the list as data, not code.
PARTNER_PHARMACIES = {"PHARM-CHAIN-A", "PHARM-CHAIN-B", "PHARM-PSAO-1"}

# Cohort axes for equity-floor matching. Same shape as 4.4.
EQUITY_FLOORS = {
    "pharmacist-consult-001": {
        "engagement_q1":         8,    # lowest engagement quartile
        "language_non_en":       6,
        "sdoh_low_food_security": 6,
    },
    "cost-assist-001": {
        "sdoh_low_food_security": 8,
        "language_non_en":       4,
    },
    "education-001": {
        "language_non_en":       50,
    },
    # Reminder, med-sync, regimen-simplification: no floor in this
    # example. Production may add equity floors based on observed
    # disparities in the engagement and outcome dashboards.
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
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = _to_decimal(v)
        elif isinstance(v, dict):
            out[k] = _to_decimal_dict(v)
        elif isinstance(v, list):
            out[k] = [_to_decimal_dict(x) if isinstance(x, dict)
                      else _to_decimal(x) if isinstance(x, (int, float)) and not isinstance(x, bool)
                      else x
                      for x in v]
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
                      therapeutic_class: str, intervention_id: str) -> str:
    """
    Tracking_id used to join recommendation -> outreach -> engagement.

    NOTE: This example uses a readable string for clarity. Production
    must replace this with an opaque, non-reversible identifier (UUID
    or HMAC over the composite). Plain-text patient_id and
    therapeutic_class embedded in tracking IDs (carried in email
    open-tracking pixels, SMS click-through links, vendor outreach
    platform handoffs) are PHI leakage. The "Gap to Production"
    section at the end of this file flags the same issue.
    """
    return f"adherence-{run_date}-{patient_id}-{therapeutic_class}-{intervention_id}"

def _parse_s3_uri(uri: str) -> tuple:
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an S3 URI: {uri}")
    parts = uri[5:].split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""

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
            raise TimeoutError(f"Athena query {execution_id} timed out after {timeout_seconds}s")
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
```

---

## Step 1: Compute Per-(Patient, Medication) Adherence Features

*The pseudocode calls this `compute_adherence_features(patients, run_date)`. For each patient and each tracked therapeutic class, build a carry-forward "covered days" set from settled fill claims, compute trailing-365 and trailing-90 PDC, derive channel mix and copay statistics, assess data quality, and persist the result to the `patient-medication-adherence` SageMaker Feature Store group. Skip carry-forward and a 90-day mail-order patient looks like a non-adherent retail patient. Skip the 30-day settled lag and the model trains on noisy claims that systematically under-estimate adherence for mail-order users.*

```python
def compute_adherence_features(run_date: str) -> str:
    """
    Run the adherence-computation pipeline:

      1. Pull settled fill claims (Athena) for the trailing 365 days
         ending at run_date - SETTLED_LAG_DAYS.
      2. For each (patient_id, therapeutic_class), build the covered-
         days set, compute PDC at 365d and 90d, compute fill cadence
         and copay-paid statistics, assess data quality.
      3. Write the per-medication features to SageMaker Feature Store
         (online + offline) for downstream consumption.

    Returns the offline Parquet path that downstream stages can use
    when Feature Store online lookups aren't appropriate (large
    batch joins).
    """
    settled_window_end = (
        datetime.date.fromisoformat(run_date) - datetime.timedelta(days=SETTLED_LAG_DAYS)
    )
    settled_window_start = settled_window_end - datetime.timedelta(days=PDC_WINDOW_365_DAYS)

    classes_quoted = ", ".join(f"'{c}'" for c in TRACKED_THERAPEUTIC_CLASSES)
    query = f"""
        SELECT
            patient_id,
            ndc,
            therapeutic_class,
            fill_date,
            days_supply,
            channel,
            copay_paid,
            was_cash_pay,
            pharmacy_id
        FROM pharmacy_claims
        WHERE fill_date BETWEEN DATE '{settled_window_start.isoformat()}'
                            AND DATE '{settled_window_end.isoformat()}'
          AND therapeutic_class IN ({classes_quoted})
    """.strip()

    logger.info(
        "Pulling settled fills for run_date=%s window=%s..%s",
        run_date, settled_window_start, settled_window_end,
    )
    execution = athena_client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": ATHENA_DATABASE},
        WorkGroup=ATHENA_WORKGROUP,
        ResultConfiguration={
            "OutputLocation": f"s3://{ATHENA_RESULTS_BUCKET}/fills/{run_date}/",
        },
    )
    _wait_for_athena_query(execution["QueryExecutionId"], timeout_seconds=600)

    # Production: a Glue job streams the Athena results into an
    # in-memory frame keyed by (patient_id, therapeutic_class). The
    # example uses an injectable loader so tests can supply synthetic
    # fills without round-tripping through Athena.
    fills_by_patient_class = _load_settled_fills(execution["QueryExecutionId"], run_date)

    feature_records = []
    for (patient_id, therapeutic_class), fills in fills_by_patient_class.items():
        adherence = _compute_pdc_for_class(fills, settled_window_end)
        feature_records.append({
            "patient_id":         patient_id,
            "therapeutic_class":  therapeutic_class,
            "run_date":           run_date,
            **adherence,
        })

    _persist_adherence_features_to_feature_store(feature_records, run_date)

    # Aggregate per-patient regimen features (across all chronic
    # medications). The barrier classifier and complexity-related
    # interventions consume these.
    regimen_records = _compute_regimen_features(fills_by_patient_class, run_date)
    _persist_regimen_features_to_feature_store(regimen_records, run_date)

    offline_path = (
        f"s3://{FEATURE_STORE_OFFLINE_BUCKET}/run_date={run_date}/"
        f"adherence-features.parquet"
    )
    logger.info(
        "Computed adherence features for %d (patient, class) pairs; offline=%s",
        len(feature_records), offline_path,
    )
    return offline_path

def _compute_pdc_for_class(fills: list, settled_window_end: datetime.date) -> dict:
    """
    Build the carry-forward covered-days set for one (patient,
    therapeutic_class) and compute PDC at 365d and 90d.

    Each fill contributes a half-open interval
    [fill_date, fill_date + days_supply). Overlapping fills (early
    refills, stockpiling) extend the covered set without
    double-counting. The set membership test for "is day d covered"
    is what makes mail-order, retail, and synchronized refills all
    produce the same PDC for the same actual adherence.
    """
    if not fills:
        return _empty_pdc_record()

    # Sort by fill_date so the carry-forward loop is monotone.
    fills_sorted = sorted(fills, key=lambda f: f["fill_date"])

    covered_days = set()
    for fill in fills_sorted:
        fd = fill["fill_date"]
        if isinstance(fd, str):
            fd = datetime.date.fromisoformat(fd)
        for offset in range(int(fill["days_supply"])):
            covered_days.add(fd + datetime.timedelta(days=offset))

    # Restrict to days at or before the settled window end. A fill
    # with days_supply that runs past the window doesn't credit days
    # outside the window.
    window_start_365 = settled_window_end - datetime.timedelta(days=PDC_WINDOW_365_DAYS - 1)
    window_start_90  = settled_window_end - datetime.timedelta(days=PDC_WINDOW_90_DAYS - 1)

    in_window_365 = sum(
        1 for d in covered_days
        if window_start_365 <= d <= settled_window_end
    )
    in_window_90 = sum(
        1 for d in covered_days
        if window_start_90 <= d <= settled_window_end
    )

    pdc_365 = in_window_365 / PDC_WINDOW_365_DAYS
    pdc_90  = in_window_90  / PDC_WINDOW_90_DAYS

    last_fill = fills_sorted[-1]
    last_fill_date = last_fill["fill_date"]
    if isinstance(last_fill_date, str):
        last_fill_date = datetime.date.fromisoformat(last_fill_date)
    last_days_supply = int(last_fill["days_supply"])

    days_since_last_fill = (settled_window_end - last_fill_date).days
    gap_days = max(0, days_since_last_fill - last_days_supply)

    # Channel mix and copay-paid statistics. Proxies the barrier
    # classifier consumes: a patient on a mostly-mail-order channel
    # has a different barrier signature than one fragmented across
    # retail pharmacies. A patient with rising copays may be
    # cost-barriered; a patient with stable copays whose adherence
    # dropped probably isn't.
    channel_counts = {}
    copay_values = []
    cash_pay_count = 0
    for fill in fills_sorted:
        channel_counts[fill["channel"]] = channel_counts.get(fill["channel"], 0) + 1
        if fill.get("copay_paid") is not None:
            copay_values.append(float(fill["copay_paid"]))
        if fill.get("was_cash_pay"):
            cash_pay_count += 1
    total_fills = len(fills_sorted)
    channel_mix = {ch: count / total_fills for ch, count in channel_counts.items()}

    copay_paid_p50 = _percentile(copay_values, 50) if copay_values else 0.0
    copay_paid_p90 = _percentile(copay_values, 90) if copay_values else 0.0

    # Detect the most-recent copay change: did the most recent fill's
    # copay differ from the prior fills' typical copay? Used by the
    # cost-barrier rule.
    most_recent_copay = float(last_fill.get("copay_paid") or 0.0)
    prior_copays = [float(f.get("copay_paid") or 0.0) for f in fills_sorted[:-1]]
    gap_onset_aligned_with_copay_change = False
    if prior_copays:
        prior_p50 = _percentile(prior_copays, 50)
        if most_recent_copay > prior_p50 * 1.5 and most_recent_copay > COPAY_HIGH_THRESHOLD:
            gap_onset_aligned_with_copay_change = True

    pharmacy_count = len({f["pharmacy_id"] for f in fills_sorted})
    data_quality_flag = _assess_data_quality(
        fills_sorted, channel_mix, pharmacy_count, cash_pay_count, total_fills,
    )

    fills_pattern_is_sporadic = _is_sporadic_pattern(fills_sorted)
    fills_pattern_is_consistent_then_stopped = _is_consistent_then_stopped(
        fills_sorted, settled_window_end,
    )
    discontinued_after_one_or_two_fills = total_fills <= 2 and gap_days > 60

    return {
        "pdc_365":                                  pdc_365,
        "pdc_90":                                   pdc_90,
        "gap_days":                                 gap_days,
        "last_fill_date":                           last_fill_date.isoformat(),
        "channel_mix":                              channel_mix,
        "copay_paid_p50":                           copay_paid_p50,
        "copay_paid_p90":                           copay_paid_p90,
        "most_recent_copay":                        most_recent_copay,
        "gap_onset_aligned_with_copay_change":      gap_onset_aligned_with_copay_change,
        "cash_pay_indicator":                       cash_pay_count > 0,
        "pharmacy_count":                           pharmacy_count,
        "fills_pattern_is_sporadic":                fills_pattern_is_sporadic,
        "fills_pattern_is_consistent_then_stopped": fills_pattern_is_consistent_then_stopped,
        "discontinued_after_one_or_two_fills":      discontinued_after_one_or_two_fills,
        "total_fills":                              total_fills,
        "data_quality_flag":                        data_quality_flag,
    }

def _empty_pdc_record() -> dict:
    """Sentinel record for a (patient, class) with no fills."""
    return {
        "pdc_365": 0.0, "pdc_90": 0.0, "gap_days": 999,
        "last_fill_date": None, "channel_mix": {},
        "copay_paid_p50": 0.0, "copay_paid_p90": 0.0,
        "most_recent_copay": 0.0,
        "gap_onset_aligned_with_copay_change": False,
        "cash_pay_indicator": False, "pharmacy_count": 0,
        "fills_pattern_is_sporadic": False,
        "fills_pattern_is_consistent_then_stopped": False,
        "discontinued_after_one_or_two_fills": False,
        "total_fills": 0,
        "data_quality_flag": "no_history",
    }

def _percentile(values: list, pct: int) -> float:
    """Simple percentile (numpy not required for the demo)."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * pct / 100)
    idx = min(idx, len(sorted_v) - 1)
    return sorted_v[idx]

def _is_sporadic_pattern(fills_sorted: list) -> bool:
    """
    Sporadic = fill-to-fill gaps vary widely (some on time, some
    months late). Distinguishes forgetful patients from
    consistently-non-adherent patients.
    """
    if len(fills_sorted) < 3:
        return False
    gaps = []
    for i in range(1, len(fills_sorted)):
        d_curr = fills_sorted[i]["fill_date"]
        d_prev = fills_sorted[i - 1]["fill_date"]
        if isinstance(d_curr, str):
            d_curr = datetime.date.fromisoformat(d_curr)
        if isinstance(d_prev, str):
            d_prev = datetime.date.fromisoformat(d_prev)
        gaps.append((d_curr - d_prev).days)
    if not gaps:
        return False
    mean_gap = sum(gaps) / len(gaps)
    if mean_gap == 0:
        return False
    variance = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
    cv = (variance ** 0.5) / mean_gap
    return cv > 0.5

def _is_consistent_then_stopped(fills_sorted: list,
                                 settled_window_end: datetime.date) -> bool:
    """
    Consistent-then-stopped = patient filled regularly for a stretch,
    then stopped entirely. Suggests beliefs/concerns or access
    barriers, not forgetfulness.
    """
    if len(fills_sorted) < 3:
        return False
    last_fd = fills_sorted[-1]["fill_date"]
    if isinstance(last_fd, str):
        last_fd = datetime.date.fromisoformat(last_fd)
    days_since = (settled_window_end - last_fd).days
    if days_since < 90:
        return False
    # Check the prior fills had small gaps.
    early_gaps = []
    for i in range(1, min(len(fills_sorted), 5)):
        d_curr = fills_sorted[i]["fill_date"]
        d_prev = fills_sorted[i - 1]["fill_date"]
        if isinstance(d_curr, str):
            d_curr = datetime.date.fromisoformat(d_curr)
        if isinstance(d_prev, str):
            d_prev = datetime.date.fromisoformat(d_prev)
        early_gaps.append((d_curr - d_prev).days)
    if not early_gaps:
        return False
    return max(early_gaps) < 45

def _assess_data_quality(fills_sorted: list, channel_mix: dict,
                          pharmacy_count: int, cash_pay_count: int,
                          total_fills: int) -> str:
    """
    Tag each (patient, class) with a data-quality flag downstream
    consumers can gate on. A confident "non-adherent" label on a
    patient with `cash_pay_partial` is a confidently wrong label.
    """
    if total_fills == 0:
        return "no_history"
    if cash_pay_count > 0 and cash_pay_count / total_fills > 0.3:
        return "cash_pay_partial"
    if pharmacy_count >= 3:
        return "multi_pharmacy_fragmented"
    if total_fills < 3:
        return "sparse_history"
    return "complete"

def _load_settled_fills(athena_execution_id: str, run_date: str) -> dict:
    """
    Load Athena results into an in-memory dict keyed on
    (patient_id, therapeutic_class). Production: a Glue job that
    writes parquet partitioned by therapeutic_class. The example
    returns an empty dict; the demo runner monkey-patches this with
    synthetic fills for the offline run.
    """
    return {}

def _persist_adherence_features_to_feature_store(records: list, run_date: str) -> None:
    """
    Push per-(patient, class) feature records to the
    `patient-medication-adherence` SageMaker Feature Store group.

    Production wires this through the Feature Store's PutRecord API
    (online store) and lets the offline-store ingestion handle the
    S3-Parquet write asynchronously. The example logs the call shape
    so the demo can run without a real feature group provisioned.
    """
    for r in records:
        try:
            sagemaker_featurestore.put_record(
                FeatureGroupName="patient-medication-adherence",
                Record=[
                    {"FeatureName": "patient_id",
                     "ValueAsString": r["patient_id"]},
                    {"FeatureName": "therapeutic_class",
                     "ValueAsString": r["therapeutic_class"]},
                    {"FeatureName": "pdc_365",
                     "ValueAsString": str(r["pdc_365"])},
                    {"FeatureName": "pdc_90",
                     "ValueAsString": str(r["pdc_90"])},
                    {"FeatureName": "gap_days",
                     "ValueAsString": str(r["gap_days"])},
                    {"FeatureName": "data_quality_flag",
                     "ValueAsString": r["data_quality_flag"]},
                    {"FeatureName": "event_time",
                     "ValueAsString": _now_iso()},
                ],
            )
        except Exception as exc:
            # In the offline demo the feature group doesn't exist;
            # log and continue. Production: alarm on persistent
            # PutRecord failures.
            logger.debug(
                "Feature Store PutRecord skipped for %s/%s: %s",
                r["patient_id"], r["therapeutic_class"], exc,
            )

def _compute_regimen_features(fills_by_patient_class: dict, run_date: str) -> list:
    """
    Aggregate per-patient regimen features across all chronic
    medications. The barrier classifier consumes regimen size and
    pharmacy count to detect complexity-driven non-adherence.
    """
    by_patient = {}
    for (patient_id, therapeutic_class), fills in fills_by_patient_class.items():
        entry = by_patient.setdefault(patient_id, {
            "patient_id": patient_id,
            "classes":    set(),
            "pharmacies": set(),
            "fills":      0,
        })
        entry["classes"].add(therapeutic_class)
        entry["fills"] += len(fills)
        for f in fills:
            entry["pharmacies"].add(f["pharmacy_id"])

    profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
    records = []
    for patient_id, entry in by_patient.items():
        try:
            response = profile_table.get_item(Key={"patient_id": patient_id})
            profile = _from_decimal(response.get("Item") or {})
        except Exception:
            profile = {}
        records.append({
            "patient_id":           patient_id,
            "regimen_size":         len(entry["classes"]),
            "num_classes_tracked":  len(entry["classes"]),
            "pharmacy_count":       len(entry["pharmacies"]),
            "med_sync_enrolled":    bool(profile.get("med_sync_enrolled", False)),
            "doses_per_day_total":  profile.get("doses_per_day_total", 0),
            "run_date":             run_date,
        })
    return records

def _persist_regimen_features_to_feature_store(records: list, run_date: str) -> None:
    """Counterpart to the per-medication persistence; same caveats."""
    for r in records:
        try:
            sagemaker_featurestore.put_record(
                FeatureGroupName="patient-regimen",
                Record=[
                    {"FeatureName": "patient_id",         "ValueAsString": r["patient_id"]},
                    {"FeatureName": "regimen_size",       "ValueAsString": str(r["regimen_size"])},
                    {"FeatureName": "pharmacy_count",     "ValueAsString": str(r["pharmacy_count"])},
                    {"FeatureName": "med_sync_enrolled",  "ValueAsString": str(r["med_sync_enrolled"])},
                    {"FeatureName": "event_time",         "ValueAsString": _now_iso()},
                ],
            )
        except Exception as exc:
            logger.debug(
                "Feature Store PutRecord skipped for regimen/%s: %s",
                r["patient_id"], exc,
            )
```

---

## Step 2: Classify Barriers Per (Patient, Medication)

*The pseudocode calls this `classify_barriers(target_set, features, run_date)`. Three stages: a deterministic rule-based classifier (auditable and the right starting point), a supervised classifier that refines confidences when labels exist, and an LLM second opinion for high-stakes cases. The output is a ranked list of barriers per (patient, therapeutic_class) with confidences and source attribution. Single-label barrier classification is a useful simplification; the right long-term shape is multi-label.*

```python
def classify_barriers_for_target_set(
    target_set: list,
    adherence_features: dict,
    regimen_features: dict,
    member_profiles: dict,
    run_date: str,
) -> dict:
    """
    Classify barriers for each (patient_id, therapeutic_class) in
    target_set.

    target_set:           list of dicts with patient_id, therapeutic_class
    adherence_features:   dict[(patient_id, therapeutic_class)] -> adherence_record
    regimen_features:     dict[patient_id] -> regimen_record
    member_profiles:      dict[patient_id] -> profile dict

    Returns dict[(patient_id, therapeutic_class)] -> ranked_barriers list.
    """
    barriers_table = dynamodb.Table(BARRIER_CLASSIFICATIONS_TABLE)
    results = {}

    for entry in target_set:
        patient_id = entry["patient_id"]
        therapeutic_class = entry["therapeutic_class"]
        adherence = adherence_features.get((patient_id, therapeutic_class))
        regimen = regimen_features.get(patient_id, {})
        member = member_profiles.get(patient_id, {})

        if adherence is None:
            logger.warning(
                "No adherence features for %s/%s; skipping barrier classification",
                patient_id, therapeutic_class,
            )
            continue

        # Stage A: rule-based pass.
        rule_results = _rule_based_barrier_classifier(
            adherence, regimen, member, therapeutic_class,
        )

        # Stage B: supervised refinement (where labels exist).
        # Production: invoke a SageMaker endpoint with the feature
        # vector; the classifier returns probabilities over the six
        # barrier classes. The example skips the live call.
        supervised_probs = _supervised_barrier_predict(
            adherence, regimen, member, therapeutic_class,
        )

        # Blend rule-based and supervised. Rule-based gets the heavier
        # weight because it's auditable; supervised is augmentation.
        blended = _blend_rule_and_supervised(
            rule_results, supervised_probs,
            rule_weight=0.6, supervised_weight=0.4,
        )

        # Compute the need score (used to decide whether to escalate
        # to LLM second opinion). Production: a real per-class need
        # model; the example uses a derivable proxy.
        need_score = _proxy_need_score(adherence, member, therapeutic_class)

        # Stage C: LLM second opinion for high-stakes ambiguous cases.
        llm_review = None
        if _should_invoke_llm(blended, need_score):
            try:
                llm_review = _bedrock_barrier_second_opinion(
                    adherence, regimen, member, therapeutic_class,
                )
                # Flag to pharmacist review if LLM disagrees with
                # blended top-1 on a high-need case.
                if (llm_review and llm_review.get("predicted_barrier")
                    and llm_review["predicted_barrier"] != blended["ranked_list"][0]["barrier"]
                    and need_score > NEED_REVIEW_THRESHOLD):
                    _flag_for_pharmacist_review(
                        patient_id, therapeutic_class, blended, llm_review,
                    )
            except Exception as exc:
                logger.warning(
                    "Bedrock barrier second opinion failed for %s/%s: %s",
                    patient_id, therapeutic_class, exc,
                )

        ranked = blended["ranked_list"]
        results[(patient_id, therapeutic_class)] = ranked

        # Persist the ranked barriers. Don't collapse to a single label.
        try:
            barriers_table.put_item(Item=_to_decimal_dict({
                "patient_id":         patient_id,
                "therapeutic_class":  therapeutic_class,
                "run_date":           run_date,
                "ranked_barriers":    ranked,
                "llm_second_opinion": llm_review,
                "data_quality_flag":  adherence["data_quality_flag"],
                "classifier_versions": {
                    "rules":      "rules-v3",
                    "supervised": SUPERVISED_BARRIER_MODEL_NAME,
                    "llm":        BARRIER_CLASSIFIER_MODEL_ID,
                },
                "created_at":         _now_iso(),
            }))
        except Exception as exc:
            logger.warning(
                "Failed to persist barriers for %s/%s: %s",
                patient_id, therapeutic_class, exc,
            )

    logger.info(
        "Classified barriers for %d (patient, class) pairs", len(results),
    )
    return results

def _rule_based_barrier_classifier(
    adherence: dict, regimen: dict, member: dict, therapeutic_class: str,
) -> list:
    """
    Deterministic rule-based barrier classifier. Each rule emits one
    or more {barrier, rule_confidence} dicts. Multiple rules can fire.

    Production: rules live in a versioned config (DynamoDB or a
    Git-tracked YAML), reviewed by a clinical pharmacist. Hard-coding
    them here for clarity.
    """
    rule_results = []

    # Cost barrier: high copay aligned with gap onset.
    if (adherence["gap_days"] > 30
        and adherence["most_recent_copay"] > COPAY_HIGH_THRESHOLD
        and adherence["gap_onset_aligned_with_copay_change"]):
        rule_results.append({"barrier": "cost", "rule_confidence": 0.85})

    # Cost barrier: high copay without LIS enrollment, even without
    # alignment to a copay change.
    if (adherence["most_recent_copay"] > COPAY_HIGH_THRESHOLD
        and not adherence["gap_onset_aligned_with_copay_change"]
        and not member.get("lis_enrolled", False)):
        rule_results.append({"barrier": "cost", "rule_confidence": 0.55})

    # Complexity / forgetfulness from regimen size + sporadic fills.
    if (regimen.get("regimen_size", 0) >= 4
        and adherence["fills_pattern_is_sporadic"]
        and not regimen.get("med_sync_enrolled", False)):
        rule_results.append({"barrier": "complexity",    "rule_confidence": 0.65})
        rule_results.append({"barrier": "forgetfulness", "rule_confidence": 0.45})

    # Side effects: gap started after a side-effect-coded encounter.
    if member.get("recent_side_effect_encounter") and member.get(
        "side_effect_encounter_before_gap_onset", False
    ):
        rule_results.append({"barrier": "side_effects", "rule_confidence": 0.80})

    # Beliefs: classic asymptomatic-condition discontinuation pattern.
    if (therapeutic_class in SYMPTOMATIC_LATENT_CLASSES
        and adherence["discontinued_after_one_or_two_fills"]):
        rule_results.append({"barrier": "beliefs", "rule_confidence": 0.55})

    # Access: consistent then stopped, no recent care interaction.
    if (adherence["fills_pattern_is_consistent_then_stopped"]
        and not member.get("recent_side_effect_encounter")
        and member.get("recent_pcp_encounter_count", 0) == 0):
        rule_results.append({"barrier": "access", "rule_confidence": 0.40})

    # Default: if no rule fired, treat as low-confidence forgetfulness.
    # Better than empty so downstream barrier-fit scoring has something
    # to consume; the supervised classifier will refine.
    if not rule_results:
        rule_results.append({"barrier": "forgetfulness", "rule_confidence": 0.30})

    return rule_results

def _supervised_barrier_predict(
    adherence: dict, regimen: dict, member: dict, therapeutic_class: str,
) -> dict:
    """
    Invoke the supervised barrier classifier (SageMaker endpoint or
    Batch Transform). Returns a probability distribution over the six
    barrier categories.

    Production: the model is trained on (features, elicited_barrier)
    labels from pharmacist consults. Without those labels, this stage
    is omitted and the recommender runs on rule-based output only.

    The example returns a uniform-ish distribution as a placeholder;
    the demo runner can monkey-patch with synthetic predictions.
    """
    # Placeholder distribution. Avoid uniform exactly so the blend
    # function still has something to combine.
    return {
        "cost":          0.18,
        "forgetfulness": 0.20,
        "beliefs":       0.17,
        "side_effects":  0.15,
        "complexity":    0.16,
        "access":        0.14,
    }

def _blend_rule_and_supervised(
    rule_results: list, supervised_probs: dict,
    rule_weight: float, supervised_weight: float,
) -> dict:
    """
    Combine rule-based and supervised outputs into a single ranked
    list of barriers with confidences and source attribution.

    For each barrier:
      - rule_part = max rule_confidence across rules that fired for it (or 0)
      - supervised_part = supervised probability for that barrier
      - blended_confidence = rule_weight * rule_part + supervised_weight * supervised_part
    """
    rule_max = {b: 0.0 for b in BARRIER_CATEGORIES}
    rule_sources = {b: [] for b in BARRIER_CATEGORIES}
    for entry in rule_results:
        b = entry["barrier"]
        if entry["rule_confidence"] > rule_max[b]:
            rule_max[b] = entry["rule_confidence"]
        rule_sources[b].append("rule")

    ranked = []
    for b in BARRIER_CATEGORIES:
        rule_part = rule_max[b]
        sup_part = supervised_probs.get(b, 0.0)
        confidence = rule_weight * rule_part + supervised_weight * sup_part
        sources = []
        if rule_part > 0:
            sources.append("rule")
        if sup_part > 0:
            sources.append("supervised")
        ranked.append({
            "barrier":    b,
            "confidence": round(confidence, 4),
            "sources":    sources,
        })

    ranked.sort(key=lambda x: x["confidence"], reverse=True)
    return {
        "ranked_list": ranked,
        "top_1":       ranked[0],
    }

def _proxy_need_score(adherence: dict, member: dict, therapeutic_class: str) -> float:
    """
    Cheap proxy for the per-class need score so we can decide whether
    to spend an LLM call on this case. Production replaces this with
    a SageMaker Batch Transform output read.

    Higher score = greater clinical risk of continued non-adherence.
    """
    score = 0.0
    pdc_365 = adherence.get("pdc_365", 1.0)
    if pdc_365 < 0.50:
        score += 0.4
    elif pdc_365 < 0.80:
        score += 0.25
    if therapeutic_class in {"statins", "ras_antagonists", "oral_diabetes"}:
        score += 0.2
    if member.get("age", 0) >= 65:
        score += 0.1
    if member.get("recent_hospitalization_for_class", False):
        score += 0.2
    return min(score, 1.0)

def _should_invoke_llm(blended: dict, need_score: float) -> bool:
    """
    Spend the LLM call only when:
      - blended top-1 confidence is low (< threshold), OR
      - need score is high enough that getting it right matters.
    """
    top_conf = blended["top_1"]["confidence"]
    if top_conf < LLM_LOW_CONFIDENCE_THRESHOLD:
        return True
    if need_score > NEED_REVIEW_THRESHOLD and top_conf < 0.80:
        return True
    return False

def _bedrock_barrier_second_opinion(
    adherence: dict, regimen: dict, member: dict, therapeutic_class: str,
) -> dict:
    """
    Invoke Bedrock to produce a structured-output barrier prediction.

    IMPORTANT: pass de-identified context to the LLM. Don't pass raw
    patient_id, name, phone, or NDC into the prompt; the LLM doesn't
    need them, and stripping them at this boundary limits any vendor-
    side logging exposure (Bedrock service terms commit to not using
    prompts to train foundation models, but defense-in-depth still
    applies).
    """
    # Build a structured, de-identified context block.
    context = {
        "therapeutic_class":      therapeutic_class,
        "pdc_365":                round(adherence["pdc_365"], 3),
        "pdc_90":                 round(adherence["pdc_90"], 3),
        "gap_days":               adherence["gap_days"],
        "most_recent_copay":      adherence["most_recent_copay"],
        "copay_p50":              adherence["copay_paid_p50"],
        "fills_pattern_is_sporadic":               adherence["fills_pattern_is_sporadic"],
        "fills_pattern_is_consistent_then_stopped": adherence["fills_pattern_is_consistent_then_stopped"],
        "discontinued_after_one_or_two_fills":     adherence["discontinued_after_one_or_two_fills"],
        "regimen_size":           regimen.get("regimen_size", 0),
        "med_sync_enrolled":      regimen.get("med_sync_enrolled", False),
        "lis_enrolled":           member.get("lis_enrolled", False),
        "age_band":               member.get("age_band"),
        "data_quality_flag":      adherence["data_quality_flag"],
    }

    prompt = f"""You are a clinical adherence specialist reviewing a patient's
medication adherence pattern. Identify the most likely barrier to adherence.

Allowed barrier categories: cost, forgetfulness, beliefs, side_effects,
complexity, access.

Observed signals:
{json.dumps(context, indent=2)}

Return ONLY valid JSON with this shape (no prose, no code fences):
{{
  "predicted_barrier":     "<one of the six categories>",
  "confidence":            "<low | moderate | high>",
  "rationale":             "<2-3 sentences citing specific observed signals>",
  "alternative_barriers":  ["<barrier>", "<barrier>"],
  "uncertainty_notes":     "<what would change your prediction>"
}}

Cite only signals from the Observed signals block above. Do not invent
clinical history that isn't shown.
"""
    response = bedrock_runtime.invoke_model(
        modelId=BARRIER_CLASSIFIER_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        500,
            "temperature":       0.0,    # deterministic for second opinion
            "messages":          [{"role": "user", "content": prompt}],
        }),
    )
    payload = json.loads(response["body"].read())
    completion = payload["content"][0]["text"]

    # Defensive JSON extraction.
    import re as _re
    match = _re.search(r"\{.*\}", completion, _re.DOTALL)
    if not match:
        raise ValueError("LLM returned no JSON object")
    parsed = json.loads(match.group(0))

    # Validate the structured output: barrier must be in allowed
    # taxonomy, confidence must be one of the allowed strings.
    if parsed.get("predicted_barrier") not in BARRIER_CATEGORIES:
        raise ValueError(
            f"LLM returned invalid barrier: {parsed.get('predicted_barrier')}"
        )
    if parsed.get("confidence") not in ("low", "moderate", "high"):
        raise ValueError(
            f"LLM returned invalid confidence: {parsed.get('confidence')}"
        )
    return parsed

def _flag_for_pharmacist_review(
    patient_id: str, therapeutic_class: str,
    blended: dict, llm_review: dict,
) -> None:
    """
    When the LLM disagrees materially with the blended classifier on
    a high-need case, flag for pharmacist review rather than silently
    picking one. Production: write to a `pharmacist-review-queue`
    table that the operations team consumes daily.
    """
    logger.info(
        "Pharmacist review flagged: patient=%s class=%s blended_top=%s llm_top=%s",
        patient_id, therapeutic_class,
        blended["top_1"]["barrier"], llm_review["predicted_barrier"],
    )
```

---

## Step 3: Build the Per-(Patient, Intervention, Medication) Candidate Set

*The pseudocode calls this `build_candidate_triples(target_set, intervention_catalog, run_date)`. Not every intervention is eligible for every (patient, medication). Cost-assistance navigation is gated on cost-sharing tier and brand status. Med-sync requires the patient's pharmacy to be a partner. Pharmacist consults require pharmacist availability in the patient's region/language. Skip the eligibility filter and you waste downstream model inference on combinations that can't be allocated.*

```python
def build_candidate_triples(
    target_set: list,
    intervention_catalog: list,
    barriers_by_class: dict,
    member_profiles: dict,
    medication_metadata: dict,
    run_date: str,
) -> list:
    """
    Cross-product target_set with the intervention catalog, applying
    eligibility filters. Returns a flat list of candidate dicts with
    enough context that downstream scoring doesn't need to re-look-up
    member or medication state.

    barriers_by_class:    dict[(patient_id, therapeutic_class)] -> ranked_barriers
    medication_metadata:  dict[(patient_id, therapeutic_class)] -> {
                            ndc, is_brand, formulary_tier,
                            data_quality_flag, ...
                          }
    """
    candidates = []
    for entry in target_set:
        patient_id = entry["patient_id"]
        therapeutic_class = entry["therapeutic_class"]
        member = member_profiles.get(patient_id, {})
        barriers = barriers_by_class.get((patient_id, therapeutic_class), [])
        med = medication_metadata.get((patient_id, therapeutic_class), {})

        for intervention in intervention_catalog:
            # Hard eligibility filters. Each one is a documented
            # business rule; comments explain why.

            # Brand-only interventions only apply to brand-name fills.
            if intervention["brand_only"] and not med.get("is_brand", False):
                continue

            # Class-specific interventions (e.g., statin education
            # module) only apply to the matching class.
            applicable_classes = intervention.get("applicable_classes")
            if applicable_classes and therapeutic_class not in applicable_classes:
                continue

            # LIS-only interventions (e.g., LIS enrollment assistance)
            # only apply to LIS-eligible members.
            if intervention["requires_lis"] and not member.get("lis_enrolled", False):
                continue

            # Med-sync requires the member's preferred pharmacy to be
            # a partner pharmacy. Without partnership, the API path
            # doesn't exist; fall back to a pharmacist referral
            # instead. The orchestrator handles that fallback.
            if (intervention["requires_partner_pharmacy"]
                and member.get("preferred_pharmacy_id") not in PARTNER_PHARMACIES):
                continue

            # Language eligibility: a Spanish-only patient won't be
            # served by an English-only intervention.
            preferred_lang = member.get("preferred_language", "en")
            if preferred_lang not in intervention.get("supported_languages", ["en"]):
                continue

            # Cooldown: don't re-recommend the same intervention type
            # if the member already received one recently.
            cooldown = intervention.get("cooldown_days", 0)
            if cooldown > 0 and _within_cooldown(member, intervention, cooldown):
                continue

            # Mutual-exclusion: if a higher-touch intervention is
            # already in flight for this (patient, class), don't queue
            # a competing one. The check here is a placeholder; the
            # production version queries the engagement-events table
            # for in-flight interventions per (patient, class).
            if _has_inflight_conflicting(patient_id, therapeutic_class, intervention):
                continue

            candidates.append({
                "patient_id":              patient_id,
                "therapeutic_class":       therapeutic_class,
                "intervention_id":         intervention["intervention_id"],
                "intervention_type":       intervention["type"],
                "intervention_cost":       intervention["marginal_cost"],
                "is_high_touch":           intervention["is_high_touch"],
                "supported_barriers":      intervention["supported_barriers"],
                "ranked_barriers":         barriers,
                "data_quality_flag":       med.get("data_quality_flag", "complete"),
                "run_date":                run_date,
            })

    logger.info(
        "Built %d (patient, intervention, class) candidate triples", len(candidates),
    )
    return candidates

def _within_cooldown(member: dict, intervention: dict, cooldown_days: int) -> bool:
    """
    True if the member already received this intervention type within
    `cooldown_days`. The patient-profile table maintains a
    `prior_interventions` map keyed on intervention_type with the
    most-recent completion timestamp.
    """
    prior = member.get("prior_interventions", {}).get(intervention["type"])
    if not prior:
        return False
    last_completed = prior.get("completed_at")
    if not last_completed:
        return False
    try:
        last_dt = datetime.datetime.fromisoformat(last_completed)
    except ValueError:
        return False
    delta = datetime.datetime.now(timezone.utc) - last_dt.astimezone(timezone.utc)
    return delta.days < cooldown_days

def _has_inflight_conflicting(patient_id: str, therapeutic_class: str,
                               intervention: dict) -> bool:
    """
    Placeholder for the in-flight conflict check. Production: query
    the recommendation-log for (patient, class) rows in the last
    N days where intervention_status is 'queued', 'sent', or
    'engaged-not-completed'. The example returns False so the demo
    proceeds.
    """
    return False
```

---

## Step 4: Score Need, Barrier-Fit, Engagement, and Uplift

*The pseudocode calls this `score_candidates(candidates, run_date)`. Three SageMaker Batch Transform jobs run in parallel per intervention (engagement and uplift) plus one per therapeutic class (need). Barrier-fit scoring is a deterministic dot product, not a model call. Skip uplift and you over-target patients who would have improved on their own; skip barrier-fit and the recommender ignores why the patient is non-adherent.*

```python
def score_candidates(candidates: list, run_date: str) -> list:
    """
    Score the candidate triples on need, barrier-fit, engagement, and
    uplift. Returns the same candidates with score columns appended.

    The example uses synthetic scoring so the demo runs offline.
    Production: write candidates to S3 by intervention_id, kick off
    Batch Transform jobs in parallel, wait, read scores back.
    """
    # ---- Group candidates by intervention_id ----
    by_intervention = {}
    for c in candidates:
        by_intervention.setdefault(c["intervention_id"], []).append(c)

    # ---- Production-shape: kick off Batch Transform jobs ----
    # The example calls a synthetic scorer that returns deterministic
    # values; production replaces _score_candidates_via_batch_transform
    # with the real submit-and-wait logic.
    scored = []
    for intervention_id, triples in by_intervention.items():
        intervention_scores = _score_candidates_via_batch_transform(
            triples, intervention_id, run_date,
        )
        scored.extend(intervention_scores)

    # ---- Barrier-fit is a deterministic computation ----
    for c in scored:
        c["barrier_fit"] = _compute_barrier_fit(
            c["ranked_barriers"], c["supported_barriers"],
        )

    return scored

def _score_candidates_via_batch_transform(
    triples: list, intervention_id: str, run_date: str,
) -> list:
    """
    Production: write candidates to S3, kick off three Batch Transform
    jobs (need / engagement / uplift) for this intervention, wait,
    join the scores back to the candidates.

    The example uses a synthetic scorer that derives plausible scores
    from observed adherence + barrier signal. Sufficient for the
    pipeline demo; nowhere near production accuracy.
    """
    scored = []
    for c in triples:
        # Need score: heuristic from PDC and class. Production reads
        # this from the per-class need model output.
        pdc = _lookup_pdc(c["patient_id"], c["therapeutic_class"])
        if pdc < 0.50:
            need = 0.85
        elif pdc < 0.65:
            need = 0.65
        elif pdc < 0.80:
            need = 0.45
        else:
            need = 0.20

        # Engagement probability: heuristic from intervention type and
        # member engagement quartile. Production reads this from the
        # per-intervention engagement model.
        engagement_quartile = _lookup_engagement_quartile(c["patient_id"])
        type_base = {
            "text_reminder":          0.30,
            "education":              0.18,
            "pharmacist_consult":     0.42,
            "cost_assistance":        0.50,
            "med_sync":               0.55,
            "regimen_simplification": 0.35,
        }.get(c["intervention_type"], 0.30)
        quartile_adj = {"q1": -0.10, "q2": -0.05, "q3": 0.0, "q4": 0.10}.get(
            engagement_quartile, 0.0
        )
        engagement_prob = max(0.05, min(0.95, type_base + quartile_adj))

        # Uplift estimate: heuristic from barrier-fit-with-rule-top
        # and intervention type. Production reads this from the
        # per-intervention uplift model (causal forest / X-learner).
        top_barrier = c["ranked_barriers"][0]["barrier"] if c["ranked_barriers"] else None
        type_uplift_base = {
            "text_reminder":          0.05,
            "education":              0.07,
            "pharmacist_consult":     0.18,
            "cost_assistance":        0.20,
            "med_sync":               0.12,
            "regimen_simplification": 0.10,
        }.get(c["intervention_type"], 0.05)
        # If the intervention's top supported barrier matches the
        # patient's top barrier, bump the uplift estimate.
        supported = c["supported_barriers"]
        barrier_match_bonus = 0.0
        if top_barrier and supported.get(top_barrier, 0.0) >= 0.7:
            barrier_match_bonus = 0.10
        uplift = max(0.0, type_uplift_base + barrier_match_bonus)

        scored.append({
            **c,
            "need_score":         need,
            "engagement_prob":    engagement_prob,
            "uplift_estimate":    uplift,
        })
    return scored

def _compute_barrier_fit(ranked_barriers: list, supported_barriers: dict) -> float:
    """
    Dot product between the patient's ranked-barriers vector and the
    intervention's supported-barriers vector.

    Example: patient barriers [cost: 0.72, beliefs: 0.21] dotted with
    cost-assistance supports {cost: 1.0, beliefs: 0.0, ...} = 0.72.
    Same patient with text-reminder supports {forgetfulness: 1.0,
    cost: 0.0, ...} = 0.0.
    """
    score = 0.0
    for entry in ranked_barriers:
        b = entry["barrier"]
        score += entry["confidence"] * supported_barriers.get(b, 0.0)
    return round(score, 4)

def _lookup_pdc(patient_id: str, therapeutic_class: str) -> float:
    """Placeholder lookup. Production: read from Feature Store online store."""
    return _DEMO_PDC_LOOKUP.get((patient_id, therapeutic_class), 0.75)

def _lookup_engagement_quartile(patient_id: str) -> str:
    """Placeholder lookup. Production: read from patient-profile table."""
    return _DEMO_ENGAGEMENT_QUARTILE.get(patient_id, "q3")

# Demo state populated by the runner at the bottom of this file. The
# production functions above replace these globals with real lookups.
_DEMO_PDC_LOOKUP: dict = {}
_DEMO_ENGAGEMENT_QUARTILE: dict = {}
```

---

## Step 5: Combine Scores Into Per-Candidate Priority

*The pseudocode calls this `compute_priority(scored_candidates, policy)`. The combination weights are policy: documented, version-controlled, reviewable. The cost-efficiency term divides expected uplift by intervention cost so a $0.05 reminder doesn't get crowded out by a $80 pharmacist consult on every candidate. Skip the cost term and the system over-allocates expensive interventions where a cheaper one would have worked.*

```python
def compute_priority(
    scored_candidates: list,
    policy_weights: dict = POLICY_WEIGHTS,
    policy_version: str = POLICY_VERSION,
) -> list:
    """
    Compute combined priority per (patient, intervention, medication)
    triple, including the per-component contributions for downstream
    auditing.

    Normalization choice: min-max within intervention_type for
    engagement and uplift (so a high engagement-prob for a reminder
    is comparable to a high engagement-prob for a pharmacist consult);
    raw values for need (which is normalized within the per-class
    model already); raw values for barrier-fit (already in [0, 1]).

    Returns the candidates with priority and priority_components
    fields appended.
    """
    if not scored_candidates:
        return []

    # ---- Normalize engagement and uplift within intervention_type ----
    by_type: dict = {}
    for c in scored_candidates:
        by_type.setdefault(c["intervention_type"], []).append(c)

    for intervention_type, type_rows in by_type.items():
        for component in ("engagement_prob", "uplift_estimate"):
            values = [r[component] for r in type_rows]
            lo, hi = min(values), max(values)
            spread = hi - lo if hi > lo else 1.0
            for r in type_rows:
                r[f"{component}_norm"] = (r[component] - lo) / spread

        # Cost-efficiency = uplift / intervention_cost, normalized
        # within intervention type so the $0.05 reminder competes
        # with the $55 pharmacist consult on a like-for-like axis.
        ce_values = []
        for r in type_rows:
            ce = r["uplift_estimate"] / max(r["intervention_cost"], MIN_COST_FOR_DIVISION)
            r["_cost_efficiency_raw"] = ce
            ce_values.append(ce)
        ce_lo, ce_hi = min(ce_values), max(ce_values)
        ce_spread = ce_hi - ce_lo if ce_hi > ce_lo else 1.0
        for r in type_rows:
            r["cost_efficiency_norm"] = (r["_cost_efficiency_raw"] - ce_lo) / ce_spread

    # ---- Combine into priority ----
    for c in scored_candidates:
        priority_components = {
            "need_contrib":            policy_weights["need"]            * c["need_score"],
            "barrier_fit_contrib":     policy_weights["barrier_fit"]     * c["barrier_fit"],
            "engagement_contrib":      policy_weights["engagement"]      * c["engagement_prob_norm"],
            "uplift_contrib":          policy_weights["uplift"]          * c["uplift_estimate_norm"],
            "cost_efficiency_contrib": policy_weights["cost_efficiency"] * c["cost_efficiency_norm"],
        }
        c["priority"] = round(sum(priority_components.values()), 4)
        c["priority_components"] = {
            k: round(v, 4) for k, v in priority_components.items()
        }
        c["policy_version"] = policy_version

    # ---- Group by (patient, class) and rank within ----
    by_patient_class: dict = {}
    for c in scored_candidates:
        key = (c["patient_id"], c["therapeutic_class"])
        by_patient_class.setdefault(key, []).append(c)

    for key, rows in by_patient_class.items():
        rows.sort(key=lambda x: x["priority"], reverse=True)
        for rank_pos, r in enumerate(rows, start=1):
            r["intervention_rank_within_medication"] = rank_pos

    logger.info(
        "Computed priority for %d candidates across %d (patient, class) pairs",
        len(scored_candidates), len(by_patient_class),
    )
    return scored_candidates
```

---

## Step 6: Allocate Under Heterogeneous Capacities

*The pseudocode calls this `allocate_heterogeneous(prioritized, interventions, policy, run_date)`. The allocator walks priority-sorted candidates and assigns slots subject to: each intervention's daily capacity, the cumulative per-patient cap (default at most 2 interventions per run, at most 1 high-touch), the cross-intervention exclusions (a pharmacist consult on a medication suppresses lower-touch interventions for the same medication), and the equity floors. Skip the floors and the optimization quietly redistributes opportunity to the easiest-to-help cohorts.*

```python
def allocate_heterogeneous(
    prioritized: list,
    intervention_catalog: list,
    member_profiles: dict,
    policy_weights: dict = POLICY_WEIGHTS,
    equity_floors: dict = EQUITY_FLOORS,
    run_horizon_days: int = 7,
    run_date: str = None,
) -> list:
    """
    Greedy allocation with multi-intervention-per-patient and equity
    floors.

    Returns a list of allocation records with priority, components,
    cohort features, and allocation_reason. Persists to the
    recommendation-log table.
    """
    run_date = run_date or _today_str()
    if not prioritized:
        return []

    candidates_sorted = sorted(prioritized, key=lambda x: x["priority"], reverse=True)

    intervention_by_id = {i["intervention_id"]: i for i in intervention_catalog}

    # ---- Initialize per-intervention capacity counters ----
    capacity_remaining = {
        i["intervention_id"]: i["daily_capacity"] * run_horizon_days
        for i in intervention_catalog
    }

    # ---- Initialize per-intervention equity-floor counters ----
    equity_remaining = {
        i["intervention_id"]: dict(equity_floors.get(i["intervention_id"], {}))
        for i in intervention_catalog
    }

    # ---- Per-patient counters ----
    patient_intervention_count: dict = {}
    patient_high_touch_count: dict = {}
    patient_contact_count_30d: dict = {}

    allocated = []
    allocated_by_patient_class: dict = {}    # for cross-intervention exclusion

    # ---- Greedy primary pass ----
    for candidate in candidates_sorted:
        patient_id = candidate["patient_id"]
        therapeutic_class = candidate["therapeutic_class"]
        intervention_id = candidate["intervention_id"]
        intervention = intervention_by_id[intervention_id]
        member = member_profiles.get(patient_id, {})

        # Per-intervention capacity.
        if capacity_remaining.get(intervention_id, 0) <= 0:
            continue

        # Per-patient interventions-per-run cap.
        if (patient_intervention_count.get(patient_id, 0)
            >= MAX_INTERVENTIONS_PER_PATIENT_PER_RUN):
            continue

        # Per-patient high-touch cap.
        if intervention["is_high_touch"]:
            if (patient_high_touch_count.get(patient_id, 0)
                >= MAX_HIGH_TOUCH_PER_PATIENT_PER_RUN):
                continue

        # Per-patient 30-day contact cap. Sum existing contacts plus
        # contacts queued in this run.
        existing_contacts = int(member.get("outreach_recent_30d_count", 0))
        new_contacts_this_run = patient_contact_count_30d.get(patient_id, 0)
        if (intervention["generates_patient_contact"]
            and (existing_contacts + new_contacts_this_run)
                >= MAX_CONTACTS_PER_PATIENT_30D):
            continue

        # Cross-intervention exclusion: a pharmacist consult on a
        # medication suppresses a reminder on the same medication
        # (the pharmacist will handle the reminder framing).
        already = allocated_by_patient_class.get((patient_id, therapeutic_class), [])
        if _conflicts_with(already, intervention):
            continue

        # ---- Equity-floor accounting ----
        cohort_features = _lookup_cohort_features_from_profile(member)
        applicable = _applicable_floor_cohorts(
            cohort_features, equity_floors.get(intervention_id, {})
        )
        used_floor = None
        for floor_cohort in applicable:
            if equity_remaining[intervention_id].get(floor_cohort, 0) > 0:
                equity_remaining[intervention_id][floor_cohort] -= 1
                used_floor = floor_cohort
                break

        # ---- Commit the allocation ----
        capacity_remaining[intervention_id] -= 1
        patient_intervention_count[patient_id] = patient_intervention_count.get(patient_id, 0) + 1
        if intervention["is_high_touch"]:
            patient_high_touch_count[patient_id] = patient_high_touch_count.get(patient_id, 0) + 1
        if intervention["generates_patient_contact"]:
            patient_contact_count_30d[patient_id] = patient_contact_count_30d.get(patient_id, 0) + 1

        allocation_reason = (
            f"equity_floor:{used_floor}" if used_floor
            else "top_priority_general_capacity"
        )

        record = {
            "tracking_id": _make_tracking_id(
                run_date, patient_id, therapeutic_class, intervention_id,
            ),
            "run_date":              run_date,
            "patient_id":            patient_id,
            "therapeutic_class":     therapeutic_class,
            "intervention_id":       intervention_id,
            "intervention_type":     intervention["type"],
            "priority":              candidate["priority"],
            "priority_components":   candidate["priority_components"],
            "policy_version":        candidate["policy_version"],
            "cohort_features":       cohort_features,
            "allocation_reason":     allocation_reason,
            "data_quality_flag":     candidate.get("data_quality_flag", "complete"),
            "ranked_barriers":       candidate.get("ranked_barriers", []),
        }
        allocated.append(record)
        allocated_by_patient_class.setdefault(
            (patient_id, therapeutic_class), []
        ).append(intervention)

    # ---- Equity-floor top-up pass ----
    # If any floor wasn't filled in the primary pass, pull additional
    # candidates from the cohort to fill the reserved slots.
    for intervention_id, floors in equity_remaining.items():
        for floor_cohort, remaining in list(floors.items()):
            if remaining <= 0:
                continue
            logger.info(
                "Top-up pass: intervention=%s floor=%s remaining=%d",
                intervention_id, floor_cohort, remaining,
            )
            cohort_pool = []
            for c in candidates_sorted:
                if c["intervention_id"] != intervention_id:
                    continue
                pid = c["patient_id"]
                if patient_intervention_count.get(pid, 0) >= MAX_INTERVENTIONS_PER_PATIENT_PER_RUN:
                    continue
                if capacity_remaining[intervention_id] <= 0:
                    break
                cohort_features = _lookup_cohort_features_from_profile(
                    member_profiles.get(pid, {}),
                )
                if floor_cohort in _applicable_floor_cohorts(
                    cohort_features, {floor_cohort: 1},
                ):
                    cohort_pool.append((c, cohort_features))

            for c, cohort_features in cohort_pool[:remaining]:
                if capacity_remaining[intervention_id] <= 0:
                    break
                pid = c["patient_id"]
                tc = c["therapeutic_class"]
                intervention = intervention_by_id[intervention_id]

                # Re-check the per-patient and contact caps for the
                # top-up candidate.
                if patient_intervention_count.get(pid, 0) >= MAX_INTERVENTIONS_PER_PATIENT_PER_RUN:
                    continue
                if intervention["is_high_touch"] and (
                    patient_high_touch_count.get(pid, 0) >= MAX_HIGH_TOUCH_PER_PATIENT_PER_RUN
                ):
                    continue

                capacity_remaining[intervention_id] -= 1
                patient_intervention_count[pid] = patient_intervention_count.get(pid, 0) + 1
                if intervention["is_high_touch"]:
                    patient_high_touch_count[pid] = patient_high_touch_count.get(pid, 0) + 1
                if intervention["generates_patient_contact"]:
                    patient_contact_count_30d[pid] = patient_contact_count_30d.get(pid, 0) + 1
                equity_remaining[intervention_id][floor_cohort] -= 1

                allocated.append({
                    "tracking_id": _make_tracking_id(
                        run_date, pid, tc, intervention_id,
                    ),
                    "run_date":              run_date,
                    "patient_id":            pid,
                    "therapeutic_class":     tc,
                    "intervention_id":       intervention_id,
                    "intervention_type":     intervention["type"],
                    "priority":              c["priority"],
                    "priority_components":   c["priority_components"],
                    "policy_version":        c["policy_version"],
                    "cohort_features":       cohort_features,
                    "allocation_reason":     f"equity_floor_topup:{floor_cohort}",
                    "data_quality_flag":     c.get("data_quality_flag", "complete"),
                    "ranked_barriers":       c.get("ranked_barriers", []),
                })

    # ---- Persist to the recommendation-log table ----
    rec_table = dynamodb.Table(RECOMMENDATION_LOG_TABLE)
    try:
        with rec_table.batch_writer() as batch:
            for row in allocated:
                batch.put_item(Item=_to_decimal_dict({
                    **row,
                    "created_at": _now_iso(),
                }))
    except Exception as exc:
        logger.warning("Recommendation-log batch write failed: %s", exc)

    _emit_metric(
        "adherence_allocations_made",
        value=len(allocated),
        dimensions={"run_date": run_date, "policy_version": POLICY_VERSION},
    )
    logger.info(
        "Allocated %d (patient, intervention, class) triples across %d patients",
        len(allocated), len(patient_intervention_count),
    )
    return allocated

def _conflicts_with(already_allocated: list, intervention: dict) -> bool:
    """
    Cross-intervention exclusion logic. The full table lives in the
    intervention-catalog config; the example codes the most common
    case: a pharmacist consult absorbs lower-touch interventions for
    the same medication.
    """
    types_already = {i["type"] for i in already_allocated}
    if "pharmacist_consult" in types_already:
        # Don't queue a reminder or education on a class where a
        # pharmacist consult is already in flight.
        if intervention["type"] in {"text_reminder", "education"}:
            return True
    return False

def _lookup_cohort_features_from_profile(member: dict) -> dict:
    """Pull cohort features from the patient-profile dict."""
    return {
        "engagement_history_quartile": member.get("engagement_history_quartile", "q3"),
        "language":                    member.get("preferred_language", "en"),
        "sdoh_cohort":                 member.get("sdoh_cohort"),
        "age_band":                    member.get("age_band"),
    }

def _applicable_floor_cohorts(cohort_features: dict, floor_definitions: dict) -> list:
    """Return the floor names the candidate qualifies for."""
    result = []
    for floor_name in floor_definitions:
        if floor_name == "engagement_q1" and cohort_features.get("engagement_history_quartile") == "q1":
            result.append(floor_name)
        elif floor_name == "language_non_en" and cohort_features.get("language") not in (None, "en"):
            result.append(floor_name)
        elif floor_name == "sdoh_low_food_security" and cohort_features.get("sdoh_cohort") == "low_food_security":
            result.append(floor_name)
    return result
```

---

## Step 7: Orchestrate Outreach Across Heterogeneous Channels

*The pseudocode calls this `orchestrate_interventions(allocated, run_date, policy)`. Patient-facing interventions go to the channel optimizer from Recipe 4.1. Staff-facing interventions go to staff queues with structured pre-work (the LLM-generated pharmacist pre-call brief, the patient's adherence history, the suspected barrier rationale). Cost-assistance flows to a dedicated case-management queue. Med-sync flows to the partner pharmacy's API or a flagged-for-action queue when no partnership exists. Skip the per-intervention-type orchestration and your interventions become "send a generic email" regardless of what was actually allocated.*

```python
def orchestrate_interventions(
    allocated: list,
    member_profiles: dict,
    medication_metadata: dict,
    run_date: str,
) -> list:
    """
    For each allocated triple, dispatch through the appropriate
    channel: SMS/email reminder, education content match, pharmacist
    queue with pre-call brief, cost-assistance staff queue, partner-
    pharmacy med-sync API, or PCP care-team inbox.

    Returns a list of dispatch records for audit and downstream
    reconciliation.
    """
    profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
    dispatched = []

    for row in allocated:
        member = member_profiles.get(row["patient_id"], {})
        med = medication_metadata.get(
            (row["patient_id"], row["therapeutic_class"]), {}
        )

        # Build the de-identified context the LLM tasks consume.
        # Identifiers are NOT in this dict; the channel optimizer
        # re-attaches them after generation.
        de_id_context = {
            "therapeutic_class":      row["therapeutic_class"],
            "adherence_summary":      _summarize_adherence_for_outreach(
                row["patient_id"], row["therapeutic_class"],
            ),
            "ranked_barriers":        row.get("ranked_barriers", []),
            "preferred_language":     member.get("preferred_language", "en"),
            "tone":                   "supportive, non-alarming",
            "data_quality_flag":      row.get("data_quality_flag", "complete"),
        }

        try:
            if row["intervention_type"] == "text_reminder":
                dispatch = _dispatch_text_reminder(row, member, de_id_context)
            elif row["intervention_type"] == "education":
                dispatch = _dispatch_education(row, member, de_id_context)
            elif row["intervention_type"] == "pharmacist_consult":
                dispatch = _dispatch_pharmacist_consult(row, member, med, de_id_context)
            elif row["intervention_type"] == "cost_assistance":
                dispatch = _dispatch_cost_assistance(row, member, med)
            elif row["intervention_type"] == "med_sync":
                dispatch = _dispatch_med_sync(row, member)
            elif row["intervention_type"] == "regimen_simplification":
                dispatch = _dispatch_regimen_simplification(row, member, med, de_id_context)
            else:
                logger.warning(
                    "Unknown intervention_type=%s; skipping", row["intervention_type"],
                )
                continue
            dispatched.append(dispatch)
        except Exception as exc:
            logger.warning(
                "Dispatch failed for tracking_id=%s: %s", row["tracking_id"], exc,
            )
            continue

        # Update the contact-cap counter optimistically when patient
        # contact is generated. Reconcile in the engagement-attribution
        # step on outreach-failed events.
        if _intervention_generates_contact(row["intervention_type"]):
            try:
                profile_table.update_item(
                    Key={"patient_id": row["patient_id"]},
                    UpdateExpression=(
                        "ADD outreach_recent_30d_count :one "
                        "SET outreach_last_at = :now"
                    ),
                    ExpressionAttributeValues={
                        ":one": Decimal("1"),
                        ":now": _now_iso(),
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Failed to update contact counter for %s: %s",
                    row["patient_id"], exc,
                )

        # Emit the adherence_intervention_recommended event. This is
        # the join point for downstream attribution.
        try:
            kinesis_client.put_record(
                StreamName=ENGAGEMENT_STREAM_NAME,
                PartitionKey=row["patient_id"],
                Data=json.dumps({
                    "event_type":          "adherence_intervention_recommended",
                    "tracking_id":         row["tracking_id"],
                    "patient_id":          row["patient_id"],
                    "therapeutic_class":   row["therapeutic_class"],
                    "intervention_id":     row["intervention_id"],
                    "intervention_type":   row["intervention_type"],
                    "run_date":            row["run_date"],
                    "priority_components": row["priority_components"],
                    "allocation_reason":   row["allocation_reason"],
                    "timestamp":           _now_iso(),
                }, default=str).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to publish recommended event for %s: %s",
                row["tracking_id"], exc,
            )

    logger.info("Dispatched %d intervention assignments", len(dispatched))
    return dispatched

def _intervention_generates_contact(intervention_type: str) -> bool:
    """Whether this intervention type produces a patient-facing contact."""
    return intervention_type in {
        "text_reminder", "education", "pharmacist_consult",
        "cost_assistance", "med_sync",
    }

def _summarize_adherence_for_outreach(patient_id: str, therapeutic_class: str) -> dict:
    """
    Build a compact, high-level adherence summary for prompt context.
    Stays at the tier of "mostly on schedule, a few gaps" rather than
    surfacing exact PDC values that might leak into member-facing
    copy via LLM hallucination.
    """
    pdc = _lookup_pdc(patient_id, therapeutic_class)
    if pdc >= 0.80:
        return {"status": "mostly_on_schedule"}
    if pdc >= 0.50:
        return {"status": "occasional_gaps"}
    return {"status": "frequent_gaps"}

def _dispatch_text_reminder(row: dict, member: dict, ctx: dict) -> dict:
    """
    Generate a tailored SMS/email reminder via Bedrock and hand it
    to the channel optimizer. Falls back to the default template on
    LLM or validator failure.
    """
    intervention_id = row["intervention_id"]
    catalog_entry = _lookup_intervention(intervention_id)
    tailored = None
    try:
        tailored = _bedrock_tailor_reminder(catalog_entry, ctx)
        if not _validate_reminder(tailored):
            logger.warning(
                "Reminder validation failed for %s; falling back to template",
                row["tracking_id"],
            )
            tailored = None
    except Exception as exc:
        logger.warning("Reminder tailoring failed for %s: %s", row["tracking_id"], exc)

    return _queue_via_channel_optimizer({
        "tracking_id":       row["tracking_id"],
        "patient_id":        row["patient_id"],
        "therapeutic_class": row["therapeutic_class"],
        "content_type":      "adherence_reminder",
        "tailored":          tailored,
        "fallback_template": catalog_entry["default_template"],
        "urgency":           "standard",
        "queued_at":         _now_iso(),
    })

def _dispatch_education(row: dict, member: dict, ctx: dict) -> dict:
    """
    Match an education content artifact to the patient's barrier.
    Production: Recipe 4.2's content-matching pipeline. The example
    returns a placeholder match.
    """
    catalog_entry = _lookup_intervention(row["intervention_id"])
    return _queue_via_channel_optimizer({
        "tracking_id":       row["tracking_id"],
        "patient_id":        row["patient_id"],
        "therapeutic_class": row["therapeutic_class"],
        "content_type":      "adherence_education",
        "tailored":          None,
        "fallback_template": catalog_entry["default_template"],
        "urgency":           "standard",
        "queued_at":         _now_iso(),
    })

def _dispatch_pharmacist_consult(
    row: dict, member: dict, med: dict, ctx: dict,
) -> dict:
    """
    Generate the pharmacist pre-call brief and enqueue the consult.
    The brief is the structured pre-work the pharmacist reads before
    dialing; saves 5-10 minutes per call and improves quality.
    """
    try:
        brief = _bedrock_pharmacist_brief(member, med, ctx)
        if not _validate_pharmacist_brief(brief):
            brief = {"summary": "(brief generation failed; pharmacist to review chart manually)"}
    except Exception as exc:
        logger.warning("Pharmacist brief failed for %s: %s", row["tracking_id"], exc)
        brief = {"summary": "(brief generation failed; pharmacist to review chart manually)"}

    enqueue_record = {
        "tracking_id":         row["tracking_id"],
        "patient_id":          row["patient_id"],
        "therapeutic_class":   row["therapeutic_class"],
        "priority":            row["priority"],
        "suspected_barrier":   ctx["ranked_barriers"][0] if ctx["ranked_barriers"] else None,
        "brief":               brief,
        "target_window":       _compute_target_window(),
        "queued_at":           _now_iso(),
    }
    logger.info(
        "Queued pharmacist consult tracking_id=%s (priority=%.3f)",
        row["tracking_id"], row["priority"],
    )
    return enqueue_record

def _dispatch_cost_assistance(row: dict, member: dict, med: dict) -> dict:
    """
    Hand to the case-management queue. The case manager works through
    the cost-assistance cascade (formulary substitution, manufacturer
    copay card, foundation grants, LIS, state programs, generic
    alternatives) and writes outcomes back via engagement events.
    """
    enqueue_record = {
        "tracking_id":         row["tracking_id"],
        "patient_id":          row["patient_id"],
        "therapeutic_class":   row["therapeutic_class"],
        "medication_ndc":      med.get("ndc"),
        "suspected_barrier":   "cost",
        "member_lis_status":   bool(member.get("lis_enrolled", False)),
        "cost_sharing_tier":   med.get("formulary_tier"),
        "queued_at":           _now_iso(),
    }
    logger.info("Queued cost-assistance tracking_id=%s", row["tracking_id"])
    return enqueue_record

def _dispatch_med_sync(row: dict, member: dict) -> dict:
    """
    Route to the partner pharmacy API if available, otherwise to a
    pharmacist-mediated med-sync conversation queue.
    """
    pharmacy_id = member.get("preferred_pharmacy_id")
    if pharmacy_id in PARTNER_PHARMACIES:
        record = {
            "tracking_id":   row["tracking_id"],
            "patient_id":    row["patient_id"],
            "pharmacy_id":   pharmacy_id,
            "channel":       "partner_pharmacy_api",
            "queued_at":     _now_iso(),
        }
        logger.info("Queued med-sync via partner API for %s", row["tracking_id"])
        return record
    record = {
        "tracking_id":         row["tracking_id"],
        "patient_id":          row["patient_id"],
        "therapeutic_class":   row["therapeutic_class"],
        "channel":             "pharmacist_referral_queue",
        "queued_at":           _now_iso(),
    }
    logger.info(
        "Queued med-sync via pharmacist referral for %s (no partner pharmacy)",
        row["tracking_id"],
    )
    return record

def _dispatch_regimen_simplification(
    row: dict, member: dict, med: dict, ctx: dict,
) -> dict:
    """
    Build a PCP briefing and post to the EHR care-team inbox. The PCP
    decides whether to act (combination pill, once-daily, blister
    pack) at the next visit; a pcp_override event flows back if they
    decline.
    """
    try:
        briefing = _bedrock_pcp_briefing(member, med, ctx)
    except Exception as exc:
        logger.warning("PCP briefing failed for %s: %s", row["tracking_id"], exc)
        briefing = {
            "talking_points": ["Consider regimen simplification for adherence"],
            "rationale":      "Briefing generation failed; review chart",
        }

    record = {
        "tracking_id":     row["tracking_id"],
        "patient_id":      row["patient_id"],
        "channel":         "ehr_care_team_inbox",
        "briefing":        briefing,
        "suggested_action": "consider regimen simplification",
        "queued_at":       _now_iso(),
    }
    logger.info("Posted PCP briefing for %s", row["tracking_id"])
    return record

def _queue_via_channel_optimizer(payload: dict) -> dict:
    """
    Hand to Recipe 4.1's channel optimizer. The example logs and
    returns; production posts to an SQS queue or invokes the channel
    optimizer Lambda directly.
    """
    logger.info(
        "Queued via channel optimizer: tracking_id=%s urgency=%s",
        payload["tracking_id"], payload.get("urgency"),
    )
    return payload

def _compute_target_window() -> dict:
    """
    The window in which the pharmacist should attempt the consult.
    Tighter window for time-sensitive interventions; this example
    uses a 7-day default.
    """
    today = datetime.date.today()
    return {
        "start": today.isoformat(),
        "end":   (today + datetime.timedelta(days=7)).isoformat(),
    }

def _lookup_intervention(intervention_id: str) -> dict:
    """Fetch an intervention record from the catalog. Production: DynamoDB lookup."""
    for i in SAMPLE_INTERVENTIONS:
        if i["intervention_id"] == intervention_id:
            return i
    raise KeyError(f"Unknown intervention_id: {intervention_id}")
```

---

## Bedrock Helpers for Tailoring, Briefs, and Validators

Three Bedrock prompts wrapped in helpers: the member-facing reminder tailoring, the pharmacist pre-call brief, and the PCP briefing. Each returns structured JSON that's validated before consumption. The validators check shape and a small prohibited-claims blocklist; production extends these with an approved-claims list per medication and a sample-and-review workflow with the medical director.

```python
def _bedrock_tailor_reminder(intervention: dict, ctx: dict) -> dict:
    """
    Generate a tailored reminder message. Always pass de-identified
    context; never raw patient_id, name, or NDC.
    """
    prompt = f"""You write supportive, non-alarming medication adherence
reminders for a health plan. Produce a short reminder for the
member's medication class. Do NOT make clinical claims; do NOT promise
outcomes; do NOT use clinical jargon.

Therapeutic class: {ctx['therapeutic_class']}
Adherence summary: {ctx['adherence_summary']['status']}
Top suspected barrier: {(ctx['ranked_barriers'][0]['barrier'] if ctx['ranked_barriers'] else 'unknown')}
Preferred language (ISO 639-1): {ctx['preferred_language']}
Tone: {ctx['tone']}

Return ONLY valid JSON with this shape:
{{
  "subject_line":           "<subject>",
  "opening_line":           "<one short opener>",
  "body":                   "<2-3 sentence body>",
  "call_to_action":         "<single CTA, no guarantees>"
}}
"""
    response = bedrock_runtime.invoke_model(
        modelId=REMINDER_MODEL_ID,
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

def _validate_reminder(tailored: dict) -> bool:
    """
    Shape and prohibited-claims check. Production adds an approved-
    claims pass against a per-medication artifact owned by clinical/
    compliance.
    """
    if not isinstance(tailored, dict):
        return False
    required = {"subject_line", "opening_line", "body", "call_to_action"}
    if set(tailored.keys()) != required:
        return False
    if any(not isinstance(tailored[k], str) or not tailored[k].strip()
           for k in required):
        return False
    full_text = " ".join(tailored.values()).lower()
    blocklist = ["guaranteed", "cure", "100%", "definitely will", "must take"]
    if any(bad in full_text for bad in blocklist):
        return False
    return True

def _bedrock_pharmacist_brief(member: dict, med: dict, ctx: dict) -> dict:
    """
    Generate a structured pre-call brief for the clinical pharmacist.
    """
    prompt = f"""You prepare pre-call briefs for a clinical pharmacist who is
about to call a member about medication adherence. The brief should be
factual, concise, and professional.

Member age band: {member.get('age_band', 'unknown')}
Therapeutic class: {ctx['therapeutic_class']}
Medication brand status: {('brand' if med.get('is_brand') else 'generic')}
Adherence summary: {ctx['adherence_summary']['status']}
Top suspected barrier: {(ctx['ranked_barriers'][0]['barrier'] if ctx['ranked_barriers'] else 'unknown')}
Suspected-barrier confidence: {(ctx['ranked_barriers'][0]['confidence'] if ctx['ranked_barriers'] else 0.0)}
Data quality: {ctx['data_quality_flag']}

Return ONLY valid JSON with this shape:
{{
  "patient_summary":              "<one-line clinical summary>",
  "adherence_picture":            "<2-3 sentence adherence summary>",
  "suspected_barrier_rationale":  "<2-3 sentence rationale>",
  "suggested_talking_points":     ["<point>", "<point>", "<point>"],
  "contraindications_to_flag":    [],
  "estimated_call_duration_minutes": <integer>
}}
"""
    response = bedrock_runtime.invoke_model(
        modelId=PHARMACIST_BRIEF_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        700,
            "temperature":       0.0,    # deterministic for clinical content
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

def _validate_pharmacist_brief(brief: dict) -> bool:
    """Shape check for the pharmacist brief."""
    required = {
        "patient_summary", "adherence_picture", "suspected_barrier_rationale",
        "suggested_talking_points", "contraindications_to_flag",
        "estimated_call_duration_minutes",
    }
    if not isinstance(brief, dict):
        return False
    if not required.issubset(brief.keys()):
        return False
    if not isinstance(brief["suggested_talking_points"], list):
        return False
    if not isinstance(brief["contraindications_to_flag"], list):
        return False
    if not isinstance(brief["estimated_call_duration_minutes"], (int, float)):
        return False
    return True

def _bedrock_pcp_briefing(member: dict, med: dict, ctx: dict) -> dict:
    """
    Generate a one-paragraph briefing for the EHR care-team inbox.
    """
    prompt = f"""You write brief notes for a primary care physician's EHR inbox
recommending consideration of regimen simplification for a member with
adherence concerns. Be factual and concise; respect the PCP's clinical
authority.

Therapeutic class: {ctx['therapeutic_class']}
Adherence summary: {ctx['adherence_summary']['status']}
Top suspected barrier: {(ctx['ranked_barriers'][0]['barrier'] if ctx['ranked_barriers'] else 'unknown')}

Return ONLY valid JSON with this shape:
{{
  "talking_points":     ["<point>", "<point>"],
  "rationale":          "<2-3 sentence rationale>",
  "suggested_options":  ["<combination pill>", "<once-daily formulation>", "<blister pack>"]
}}
"""
    response = bedrock_runtime.invoke_model(
        modelId=PCP_BRIEFING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        400,
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
```

---

## Step 8: Capture Engagement, Fill, and Barrier-Elicited Events

*The pseudocode calls this `process_adherence_event(event)`. A separate Lambda consumes the engagement stream, joins each event back to the recommendation log by tracking_id (or by (patient, class) for organic pharmacy_fill_observed events), and updates short-, medium-, and long-horizon training data on the appropriate cadence. A barrier_elicited event from a pharmacist consult is gold-label data for the supervised barrier classifier. A pcp_override is a strong negative signal that goes to clinical review.*

```python
def process_adherence_event(event: dict) -> None:
    """
    Process one engagement / fill / barrier event from Kinesis.

    Expected shape:
      {
        "event_type":   "adherence_intervention_recommended" |
                        "intervention_outreach_sent" |
                        "intervention_outreach_opened" |
                        "intervention_outreach_clicked" |
                        "intervention_outreach_failed" |
                        "intervention_engaged" |
                        "intervention_completed" |
                        "barrier_elicited" |
                        "pharmacy_fill_observed" |
                        "med_sync_enrolled" |
                        "cost_assistance_initiated" |
                        "cost_assistance_approved" |
                        "pcp_override" |
                        "pharmacist_consult_completed",
        "tracking_id":  optional (organic fills may not have one),
        "patient_id":   "...",
        "therapeutic_class": optional,
        "intervention_id":   optional,
        "timestamp":    ISO 8601,
        "payload":      event-type-specific body
      }
    """
    event_type = event.get("event_type")
    patient_id = event.get("patient_id")
    if not (event_type and patient_id):
        logger.warning("Malformed event; dropping: %s", event)
        return

    # ---- Look up the originating recommendation ----
    rec = None
    tracking_id = event.get("tracking_id")
    if tracking_id:
        rec_table = dynamodb.Table(RECOMMENDATION_LOG_TABLE)
        try:
            response = rec_table.get_item(Key={"tracking_id": tracking_id})
            rec = response.get("Item")
        except Exception as exc:
            logger.warning("Recommendation lookup failed for %s: %s", tracking_id, exc)

    # Organic pharmacy fills don't carry a tracking_id; match them to
    # the most recent open recommendation for the same (patient,
    # class) within an attribution window.
    if rec is None and event_type == "pharmacy_fill_observed":
        rec = _match_organic_fill_to_open_recommendation(event)

    if rec is None:
        # Some events legitimately have no matching recommendation
        # (e.g., a fill that happened before the recommender ever
        # targeted the patient). Log and exit; don't pollute the
        # training data with un-attributable events.
        logger.info(
            "Event %s for patient=%s has no matched recommendation; logging only",
            event_type, patient_id,
        )
        return

    # Identity-boundary check: a buggy or malicious event source that
    # submits events with a patient_id different from the one in the
    # recommendation log would pollute another patient's training
    # data. Drop the event rather than absorb the inconsistency.
    if patient_id != rec.get("patient_id"):
        logger.warning(
            "Event patient_id=%s mismatch with recommendation %s; dropping",
            patient_id, tracking_id,
        )
        return

    # ---- Outreach failure: decrement the contact-cap counter ----
    # Without this reconciliation, members with flaky channels
    # accumulate phantom contact-cap consumption and get
    # systematically excluded from future allocations they should
    # still be eligible for.
    if event_type in ("intervention_outreach_failed",
                      "intervention_outreach_bounced"):
        try:
            profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
            profile_table.update_item(
                Key={"patient_id": patient_id},
                UpdateExpression="ADD outreach_recent_30d_count :neg",
                ExpressionAttributeValues={":neg": Decimal("-1")},
                # Only decrement if the counter is positive; never go
                # below zero (would suggest a bug elsewhere).
                ConditionExpression="outreach_recent_30d_count > :zero",
                ExpressionAttributeNames={},
            )
        except Exception as exc:
            logger.warning(
                "Contact-cap reconciliation failed for %s: %s", patient_id, exc,
            )

    # ---- Persist the raw event ----
    events_table = dynamodb.Table(ENGAGEMENT_EVENTS_TABLE)
    event_id = (
        f"{tracking_id}:{event_type}:{event.get('timestamp', _now_iso())}"
        if tracking_id else
        f"organic:{patient_id}:{event_type}:{event.get('timestamp', _now_iso())}"
    )
    try:
        events_table.put_item(Item=_to_decimal_dict({
            "event_id":            event_id,
            "tracking_id":         tracking_id,
            "patient_id":          patient_id,
            "therapeutic_class":   rec.get("therapeutic_class"),
            "intervention_id":     rec.get("intervention_id"),
            "intervention_type":   rec.get("intervention_type"),
            "event_type":          event_type,
            "timestamp":           event.get("timestamp", _now_iso()),
            "run_date":            rec.get("run_date"),
            "priority":            rec.get("priority"),
            "priority_components": _from_decimal(rec.get("priority_components", {})),
            "allocation_reason":   rec.get("allocation_reason"),
            "cohort_features":     _from_decimal(rec.get("cohort_features", {})),
            "event_payload":       event.get("payload", {}),
        }))
    except Exception as exc:
        logger.warning("Failed to persist engagement event %s: %s", event_id, exc)

    # ---- Short-horizon engagement signals ----
    if event_type in ("intervention_outreach_opened",
                      "intervention_outreach_clicked",
                      "intervention_engaged",
                      "intervention_completed"):
        _update_engagement_training_label(rec, event)

    # ---- Barrier-elicited: gold-label data for supervised classifier ----
    if event_type == "barrier_elicited":
        _update_barrier_classifier_training_label(rec, event)

    # ---- Medium-horizon adherence change from observed fills ----
    if event_type == "pharmacy_fill_observed":
        _update_uplift_observation(rec, event)

    # ---- PCP override: strong negative signal ----
    if event_type == "pcp_override":
        _record_pcp_override(rec, event)

    # ---- Cohort-sliced metric for the equity dashboard ----
    cohort = _from_decimal(rec.get("cohort_features", {})) or {}
    _emit_metric(
        "adherence_engagement",
        value=1,
        dimensions={
            "event_type":             event_type,
            "intervention_type":      rec.get("intervention_type", "unknown"),
            "therapeutic_class":      rec.get("therapeutic_class", "unknown"),
            "engagement_history_q":   str(cohort.get("engagement_history_quartile", "unknown")),
            "language":               str(cohort.get("language", "unknown")),
            "sdoh_cohort":            str(cohort.get("sdoh_cohort", "unknown")),
        },
    )
    logger.info(
        "Processed %s for tracking_id=%s patient=%s",
        event_type, tracking_id, patient_id,
    )

def _match_organic_fill_to_open_recommendation(event: dict) -> dict:
    """
    For an organic pharmacy_fill_observed event, find the most recent
    open recommendation for (patient, therapeutic_class). Production:
    a Query against a (patient_id, run_date) GSI on the
    recommendation-log table with a freshness filter. The example
    returns None.
    """
    return None

def _update_engagement_training_label(rec: dict, event: dict) -> None:
    """
    Append a row to the engagement-prediction training partition. The
    next training cycle reads partitions accumulated since the last
    run.
    """
    logger.debug(
        "engagement_training_label_added: tracking_id=%s event=%s",
        rec.get("tracking_id"), event["event_type"],
    )

def _update_barrier_classifier_training_label(rec: dict, event: dict) -> None:
    """
    Append a row to the supervised barrier classifier training
    partition. Each barrier_elicited event is gold-label data: the
    pharmacist asked the patient and got a structured answer.
    """
    payload = event.get("payload", {})
    elicited = payload.get("barrier")
    confidence = payload.get("confidence")
    source = payload.get("source", "pharmacist_consult")
    logger.info(
        "barrier_training_label_added: patient=%s class=%s elicited=%s "
        "confidence=%s source=%s",
        rec.get("patient_id"), rec.get("therapeutic_class"),
        elicited, confidence, source,
    )

def _update_uplift_observation(rec: dict, event: dict) -> None:
    """
    Append the fill observation to the uplift training partition.
    The trainer joins (recommendation, fills observed in the next 90
    days) into the per-intervention uplift model's training set.
    """
    logger.debug(
        "uplift_observation_added: tracking_id=%s fill_date=%s",
        rec.get("tracking_id"), event.get("payload", {}).get("fill_date"),
    )

def _record_pcp_override(rec: dict, event: dict) -> None:
    """
    Persist the PCP override and flag for clinical review.
    """
    overrides_table = dynamodb.Table(PCP_OVERRIDES_TABLE)
    try:
        overrides_table.put_item(Item=_to_decimal_dict({
            "override_id":      str(uuid.uuid4()),
            "tracking_id":      rec.get("tracking_id"),
            "patient_id":       rec.get("patient_id"),
            "therapeutic_class": rec.get("therapeutic_class"),
            "intervention_id":  rec.get("intervention_id"),
            "pcp_reason":       event.get("payload", {}).get("reason"),
            "timestamp":        event.get("timestamp", _now_iso()),
        }))
    except Exception as exc:
        logger.warning("Failed to record PCP override: %s", exc)
    _emit_metric(
        "pcp_override",
        value=1,
        dimensions={
            "intervention_type":  rec.get("intervention_type", "unknown"),
            "therapeutic_class":  rec.get("therapeutic_class", "unknown"),
        },
    )
```

---

## Putting It All Together

Here's the full inference pipeline assembled into a single callable function. In production, this is a Step Functions workflow with each step as a separate task: Glue jobs (adherence computation), barrier-classification Lambdas, candidate-build Lambda, SageMaker Batch Transform jobs in parallel (scoring), Lambda (priority, allocation, orchestration), and a separate Lambda consuming the engagement stream (Step 8). The example chains them together so you can trace one weekly run end-to-end.

```python
def run_weekly_batch(
    target_set: list,
    intervention_catalog: list,
    member_profiles: dict,
    medication_metadata: dict,
    adherence_features: dict,
    regimen_features: dict,
    run_date: str | None = None,
) -> dict:
    """
    Run the full weekly recommendation batch.

    Steps 2 through 7 of the recipe (Step 1 ran nightly already, so
    we receive its output as `adherence_features`):
      2. classify_barriers_for_target_set
      3. build_candidate_triples
      4. score_candidates
      5. compute_priority
      6. allocate_heterogeneous
      7. orchestrate_interventions

    Step 8 (process_adherence_event) runs continuously in a separate
    Lambda. The main run produces `adherence_intervention_recommended`
    events that Step 8 picks up.
    """
    run_date = run_date or _today_str()
    start = time.time()

    print(f"=== Starting weekly batch for run_date={run_date} ===")

    print("\nStep 2: Classifying barriers per (patient, class)...")
    barriers_by_class = classify_barriers_for_target_set(
        target_set, adherence_features, regimen_features, member_profiles, run_date,
    )
    print(f"  Classified {len(barriers_by_class)} (patient, class) pairs")

    print("\nStep 3: Building candidate triples...")
    candidates = build_candidate_triples(
        target_set, intervention_catalog, barriers_by_class,
        member_profiles, medication_metadata, run_date,
    )
    print(f"  Built {len(candidates)} candidates")

    print("\nStep 4: Scoring candidates...")
    scored = score_candidates(candidates, run_date)
    print(f"  Scored {len(scored)} candidates")

    print("\nStep 5: Computing priority...")
    prioritized = compute_priority(scored)
    print(f"  Priority computed for {len(prioritized)} candidates")

    print("\nStep 6: Allocating under heterogeneous capacities...")
    allocated = allocate_heterogeneous(
        prioritized, intervention_catalog, member_profiles, run_date=run_date,
    )
    print(f"  Allocated {len(allocated)} (patient, intervention, class) triples")

    print("\nStep 7: Orchestrating interventions...")
    dispatched = orchestrate_interventions(
        allocated, member_profiles, medication_metadata, run_date,
    )
    print(f"  Dispatched {len(dispatched)} intervention assignments")

    elapsed = int(time.time() - start)
    print(f"\n=== Batch complete in {elapsed}s ===")
    return {
        "run_date":         run_date,
        "n_targets":        len(target_set),
        "n_barriers":       len(barriers_by_class),
        "n_candidates":     len(candidates),
        "n_allocated":      len(allocated),
        "n_dispatched":     len(dispatched),
        "elapsed_seconds":  elapsed,
    }

# --- Demo runner ---
if __name__ == "__main__":
    # All sample data is SYNTHETIC. Do not use real PHI in development.
    # The demo:
    #   1. Builds a small target set with two synthetic patients
    #   2. Synthesizes adherence features and regimen features (the
    #      offline shape Step 1 would produce)
    #   3. Runs Steps 2-7 against the synthetic data
    #   4. Simulates a barrier_elicited event and a pharmacy_fill_observed
    #      event to exercise Step 8
    #
    # The actual Bedrock and SageMaker Batch Transform calls are
    # mocked at the helper level so the demo runs offline.

    print("=" * 70)
    print("Building synthetic target set, profiles, and adherence features...")
    print("=" * 70)

    run_date = _today_str()

    # Two synthetic patients with different barrier profiles.
    member_profiles = {
        "pat-000482": {
            "patient_id":                  "pat-000482",
            "preferred_language":          "en",
            "engagement_history_quartile": "q3",
            "sdoh_cohort":                 "moderate_food_security",
            "age_band":                    "55-64",
            "age":                         58,
            "lis_enrolled":                False,
            "med_sync_enrolled":           False,
            "preferred_pharmacy_id":       "PHARM-CHAIN-A",
            "outreach_recent_30d_count":   Decimal("0"),
            "wellness_consent_active":     True,
            "doses_per_day_total":         3,
            "recent_pcp_encounter_count":  1,
            "recent_side_effect_encounter": False,
            "side_effect_encounter_before_gap_onset": False,
        },
        "pat-000915": {
            "patient_id":                  "pat-000915",
            "preferred_language":          "es",
            "engagement_history_quartile": "q1",
            "sdoh_cohort":                 "low_food_security",
            "age_band":                    "65-74",
            "age":                         70,
            "lis_enrolled":                True,
            "med_sync_enrolled":           False,
            "preferred_pharmacy_id":       "PHARM-LOCAL-XYZ",   # NOT a partner
            "outreach_recent_30d_count":   Decimal("1"),
            "wellness_consent_active":     True,
            "doses_per_day_total":         5,
            "recent_pcp_encounter_count":  0,
            "recent_side_effect_encounter": False,
            "side_effect_encounter_before_gap_onset": False,
        },
    }

    # Synthetic adherence features as Step 1 would produce.
    adherence_features = {
        ("pat-000482", "statins"): {
            "pdc_365":           0.64,
            "pdc_90":            0.52,
            "gap_days":          12,
            "last_fill_date":    "2026-04-26",
            "channel_mix":       {"retail": 1.0},
            "copay_paid_p50":    8.0,
            "copay_paid_p90":    12.0,
            "most_recent_copay": 8.0,
            "gap_onset_aligned_with_copay_change":      False,
            "cash_pay_indicator":                       False,
            "pharmacy_count":                           1,
            "fills_pattern_is_sporadic":                True,
            "fills_pattern_is_consistent_then_stopped": False,
            "discontinued_after_one_or_two_fills":      False,
            "total_fills":                              7,
            "data_quality_flag":                        "complete",
        },
        ("pat-000915", "ras_antagonists"): {
            "pdc_365":           0.42,
            "pdc_90":            0.30,
            "gap_days":          35,
            "last_fill_date":    "2026-04-04",
            "channel_mix":       {"retail": 1.0},
            "copay_paid_p50":    45.0,
            "copay_paid_p90":    55.0,
            "most_recent_copay": 55.0,
            "gap_onset_aligned_with_copay_change":      True,
            "cash_pay_indicator":                       False,
            "pharmacy_count":                           1,
            "fills_pattern_is_sporadic":                False,
            "fills_pattern_is_consistent_then_stopped": True,
            "discontinued_after_one_or_two_fills":      False,
            "total_fills":                              4,
            "data_quality_flag":                        "complete",
        },
    }

    regimen_features = {
        "pat-000482": {
            "patient_id":         "pat-000482",
            "regimen_size":       3,
            "num_classes_tracked": 2,
            "pharmacy_count":     1,
            "med_sync_enrolled":  False,
            "doses_per_day_total": 3,
            "run_date":           run_date,
        },
        "pat-000915": {
            "patient_id":         "pat-000915",
            "regimen_size":       5,
            "num_classes_tracked": 3,
            "pharmacy_count":     1,
            "med_sync_enrolled":  False,
            "doses_per_day_total": 5,
            "run_date":           run_date,
        },
    }

    medication_metadata = {
        ("pat-000482", "statins"): {
            "ndc":               "00071-0156-23",
            "is_brand":          False,
            "formulary_tier":    "tier_1",
            "data_quality_flag": "complete",
        },
        ("pat-000915", "ras_antagonists"): {
            "ndc":               "00378-3825-77",
            "is_brand":          True,
            "formulary_tier":    "tier_3",
            "data_quality_flag": "complete",
        },
    }

    target_set = [
        {"patient_id": pid, "therapeutic_class": tc}
        for (pid, tc) in adherence_features.keys()
    ]

    # Wire up demo lookups so the synthetic scorer can read PDC and
    # engagement quartile without round-tripping through Feature Store.
    _DEMO_PDC_LOOKUP.update({
        ("pat-000482", "statins"):           0.64,
        ("pat-000915", "ras_antagonists"):   0.42,
    })
    _DEMO_ENGAGEMENT_QUARTILE.update({
        "pat-000482": "q3",
        "pat-000915": "q1",
    })

    # Mock Bedrock by short-circuiting the helpers. Production runs
    # the real calls; the demo skips them so the run is offline.
    def _mock_supervised(adherence, regimen, member, therapeutic_class):
        # Hand-tuned distributions per patient so the demo shows
        # plausible barrier picks for each profile.
        if member.get("patient_id") == "pat-000482":
            return {"beliefs": 0.45, "side_effects": 0.20, "forgetfulness": 0.15,
                    "complexity": 0.10, "cost": 0.05, "access": 0.05}
        if member.get("patient_id") == "pat-000915":
            return {"cost": 0.55, "access": 0.20, "complexity": 0.10,
                    "beliefs": 0.10, "forgetfulness": 0.03, "side_effects": 0.02}
        return {b: 1 / len(BARRIER_CATEGORIES) for b in BARRIER_CATEGORIES}

    def _mock_invoke_llm(blended, need_score):
        # Skip LLM in offline demo; in production this method is the
        # real gating logic.
        return False

    def _mock_tailor_reminder(intervention, ctx):
        return {
            "subject_line":     "Quick check-in about your medication",
            "opening_line":     "Hi, just a quick note.",
            "body":             "Your last fill was a few weeks ago. If you've already refilled, ignore this. If not, your pharmacy can usually have it ready in a few hours.",
            "call_to_action":   "Tap to request a refill.",
        }

    def _mock_pharmacist_brief(member, med, ctx):
        return {
            "patient_summary":              f"Member in age band {member.get('age_band')}, on {ctx['therapeutic_class']}.",
            "adherence_picture":            f"Adherence summary: {ctx['adherence_summary']['status']}.",
            "suspected_barrier_rationale":  f"Top suspected barrier: {ctx['ranked_barriers'][0]['barrier']} (confidence {ctx['ranked_barriers'][0]['confidence']}).",
            "suggested_talking_points":     ["Ask open-ended question about how the medication has been going",
                                              "Listen for concerns about side effects, beliefs, cost",
                                              "Offer to escalate to PCP if clinical conversation is needed"],
            "contraindications_to_flag":    [],
            "estimated_call_duration_minutes": 12,
        }

    def _mock_pcp_briefing(member, med, ctx):
        return {
            "talking_points":     ["Consider regimen simplification at next visit", "Patient adherence has been variable"],
            "rationale":          "Member has multiple chronic medications; complexity may be a factor.",
            "suggested_options":  ["combination pill", "once-daily formulation", "blister pack"],
        }

    # Patch the module-level functions for the offline demo. Production
    # never bypasses these; the real Bedrock and SageMaker calls run.
    globals()["_supervised_barrier_predict"] = _mock_supervised
    globals()["_should_invoke_llm"] = _mock_invoke_llm
    globals()["_bedrock_tailor_reminder"] = _mock_tailor_reminder
    globals()["_bedrock_pharmacist_brief"] = _mock_pharmacist_brief
    globals()["_bedrock_pcp_briefing"] = _mock_pcp_briefing

    print(f"  Target set: {len(target_set)} (patient, class) pairs")
    print(f"  Member profiles: {len(member_profiles)}")
    print(f"  Adherence feature records: {len(adherence_features)}")

    print("\n" + "=" * 70)
    print("Running pipeline Steps 2-7 against synthetic data...")
    print("=" * 70)
    summary = run_weekly_batch(
        target_set=target_set,
        intervention_catalog=SAMPLE_INTERVENTIONS,
        member_profiles=member_profiles,
        medication_metadata=medication_metadata,
        adherence_features=adherence_features,
        regimen_features=regimen_features,
        run_date=run_date,
    )
    print(f"\nBatch summary: {summary}")

    # ---- Step 8: simulate engagement events ----
    print("\n" + "=" * 70)
    print("Simulating engagement events to exercise Step 8...")
    print("=" * 70)

    # Build a tracking_id matching one we just allocated (the demo
    # runner pulls the first allocation from the recommendation log).
    # Since the real DynamoDB write may have failed offline, build a
    # synthetic tracking_id and recommendation record for demo use.
    sample_tracking_id = _make_tracking_id(
        run_date, "pat-000915", "ras_antagonists", "pharmacist-consult-001",
    )

    # Inject a synthetic recommendation row so the event processor
    # finds something to attribute the event to. Production never
    # does this.
    rec_table = dynamodb.Table(RECOMMENDATION_LOG_TABLE)
    try:
        rec_table.put_item(Item=_to_decimal_dict({
            "tracking_id":         sample_tracking_id,
            "run_date":            run_date,
            "patient_id":          "pat-000915",
            "therapeutic_class":   "ras_antagonists",
            "intervention_id":     "pharmacist-consult-001",
            "intervention_type":   "pharmacist_consult",
            "priority":            0.81,
            "priority_components": {
                "need_contrib":            0.20,
                "barrier_fit_contrib":     0.18,
                "engagement_contrib":      0.07,
                "uplift_contrib":          0.28,
                "cost_efficiency_contrib": 0.08,
            },
            "policy_version":      POLICY_VERSION,
            "cohort_features": {
                "engagement_history_quartile": "q1",
                "language":                    "es",
                "sdoh_cohort":                 "low_food_security",
                "age_band":                    "65-74",
            },
            "allocation_reason":   "top_priority_general_capacity",
            "data_quality_flag":   "complete",
            "ranked_barriers":     [{"barrier": "cost", "confidence": 0.74,
                                     "sources": ["rule", "supervised"]}],
            "created_at":          _now_iso(),
        }))
    except Exception as exc:
        logger.warning("Demo recommendation seed failed: %s", exc)

    # Simulate a barrier_elicited event from the pharmacist's call.
    print("\n  -> barrier_elicited (pharmacist confirmed cost barrier)...")
    process_adherence_event({
        "event_type":         "barrier_elicited",
        "tracking_id":        sample_tracking_id,
        "patient_id":         "pat-000915",
        "therapeutic_class":  "ras_antagonists",
        "intervention_id":    "pharmacist-consult-001",
        "timestamp":          _now_iso(),
        "payload": {
            "barrier":    "cost",
            "confidence": "high",
            "source":     "pharmacist_consult",
        },
    })

    # Simulate a downstream pharmacy_fill_observed event 30 days later.
    print("\n  -> pharmacy_fill_observed (downstream uplift signal)...")
    process_adherence_event({
        "event_type":         "pharmacy_fill_observed",
        "tracking_id":        sample_tracking_id,
        "patient_id":         "pat-000915",
        "therapeutic_class":  "ras_antagonists",
        "intervention_id":    "pharmacist-consult-001",
        "timestamp":          _now_iso(),
        "payload": {
            "fill_date":   (datetime.date.today() + datetime.timedelta(days=30)).isoformat(),
            "days_supply": 30,
            "copay_paid":  5.0,
            "channel":     "retail",
        },
    })

    print("\n=== Demo complete ===")
```

---

## The Gap Between This and Production

Run this end-to-end against a populated PBM data feed, a seeded patient profile table, trained SageMaker models, a working intervention catalog, configured channel optimizer / pharmacist queue / cost-assistance queue / partner-pharmacy API / EHR integration, and you'll see the pattern: per-(patient, medication) PDC computed correctly, barriers classified, candidate triples filtered for eligibility, scored on need / barrier-fit / engagement / uplift, prioritized with cost-effectiveness, allocated under heterogeneous capacities with equity floors, dispatched per intervention type, and engagement-tracked with barrier-elicited gold labels feeding the next training cycle. The distance between this and a real health-plan deployment is significant. Here's where it lives.

**PBM data ingestion contracts.** The example queries a normalized `pharmacy_claims` table; PBM feeds in production arrive in NCPDP X12 files, proprietary CSVs, occasionally JSON over an API, with separate streams for retail, mail-order, and specialty pharmacy. Specialty pharmacy is often a different vendor with a different cadence and schema. The data engineering to ingest, normalize against AHFS / NDF-RT, and reconcile against PBM-reported member-level adherence dashboards is its own project. Plan 8 to 16 weeks of ingestion engineering before the first model run, with explicit reconciliation checks against the PBM's reported PDC distributions for the same population and window.

**PDC methodology validated against PQA specifications.** The example computes PDC at therapeutic-class level with carry-forward and a 30-day lag. The Pharmacy Quality Alliance (PQA) measure specifications for the CMS Star Ratings Part D adherence measures (statins for cardiovascular disease, RAS antagonists for hypertension, oral diabetes medications) define many small choices: which fills count, how to handle hospitalizations and skilled-nursing stays during which the patient may not have outpatient pharmacy fills, how to handle therapeutic substitutions, how to treat prescription start dates. Compare your computed PDC distributions against your PBM-reported PDC distributions for the same population and window; sustained discrepancies flag a methodology bug. Engage a clinical pharmacist with quality-measure experience to review the implementation.

**Barrier-classifier label generation.** The example wires the supervised classifier as a placeholder. The labels come from pharmacist consults that elicit barriers explicitly. In year one, you have very few labels. Plan a structured barrier-elicitation protocol: pharmacist consults follow a guided conversation that captures barrier with high inter-rater agreement, the consult result is structured and stored, the dataset accumulates over time. Without the protocol, pharmacist notes are unstructured text and the labels are too noisy to train on. The barrier_elicited engagement-event flow in this example is the receiving end of that protocol.

**Uplift training data.** Same caveat as Recipe 4.4. The example loads "pre-trained" uplift models per intervention. Real uplift modeling requires either a randomized hold-out arm in a prior cycle (gold standard, expensive in member experience and program capacity, worth it) or careful propensity-score adjustment on observational data. The honest day-one launch path: ship the pipeline with engagement-and-need scoring only; carve out a 10-20 percent randomized hold-out for each intervention type for one or two cycles to generate training data; turn on uplift scoring as the pilot data accrues; document explicitly that early runs are calibrating, not optimized.

**Propensity-score modeling.** When a randomized pilot isn't feasible, propensity adjustment is the alternative. Production-grade propensity modeling: train and calibrate the propensity model on historical data; audit for overlap (the propensity overlap assumption requires sufficient density of treated and untreated members at each propensity value); run sensitivity analyses against unobserved-confounder bounds; have a causal-inference specialist review the methodology. This is a multi-quarter investment, not a sprint task.

**SageMaker Feature Store integration.** The example calls `PutRecord` with a placeholder feature group. Production wires feature ingestion through Glue or a Spark job into both the offline (S3 + Glue Data Catalog) and online (DynamoDB-backed) stores, with feature freshness guarantees per source. The feature definitions are reused across Recipes 4.4, 4.5, 4.6, 4.7; centralizing them is the entire point.

**SageMaker Batch Transform output schema.** The example replaces real Batch Transform calls with a synthetic scorer. Production: define an explicit output schema per model (ideally JSONL with named fields), validate it on every job completion, version the schema alongside the model. A model upgrade that silently changes output column order is a production failure mode that's painful to debug.

**Eligibility and adherence SQL via Glue, not application code.** The example builds adherence and eligibility SQL via string concatenation for clarity. Production uses parameterized queries, Jinja templating, or a SQL-construction library. A typo in a therapeutic-class definition that becomes SQL injection is not the production failure mode you want.

**Step Functions orchestration.** The example chains Steps 1-7 in a single Python function. Production runs the batch as a Step Functions state machine: a Map state for adherence computation per therapeutic class, a Map state for barrier classification across (patient, class) shards, a Map state for scoring (one Batch Transform per intervention, in parallel), Lambda tasks for ranking / allocation / orchestration. Each task has Catch handlers routing failures to per-stage SQS DLQs keyed on (run_date, stage, failure_reason); a Step Functions execution that fails partway through can resume from the last successful state.

**DLQ coverage on every Lambda path.** None of the architecture's Lambdas in this example have explicit DLQs. Production needs DLQs at three boundaries: Step Functions tasks routing failures via Catch; the Kinesis-to-Lambda event source mapping for the attribution Lambda configured with an `OnFailure` destination pointing to SQS, alarmed on DLQ depth; SageMaker Batch Transform failures wired into the Step Functions Catch since SageMaker doesn't surface failures via DLQ. A silently-dropped pharmacy_fill_observed event leaves the uplift training data incomplete and the dashboards wrong, with no observable symptom until a quarterly evaluation regresses.

**Bedrock cost and latency budget.** The example calls Bedrock per allocated triple for reminder tailoring, pharmacist briefs, and PCP briefings. At 30K LLM calls per week with Haiku-class models, the budget is manageable. At higher volumes or with larger models, it isn't. Production caches tailored content by (intervention_id, language, cohort_features hash, top_barrier) since many candidates share the same effective context, and only calls Bedrock for the unique cases. Monitor Bedrock spend in CloudWatch and set per-account quota alarms.

**Outreach-message governance for adherence content.** Adherence reminders are a regulated communication category. State boards of pharmacy have varying rules about who can send reminders for what medications, and what disclosures are required. Manufacturer-funded reminder programs (where the manufacturer pays for the outreach for their drug) have additional anti-kickback considerations. Engage your compliance counsel on the message governance before launch. The validator in this example checks shape and a small blocklist; production extends with: required disclosures per state, an approved-claims list per medication, a prohibited-claims regex/blocklist, and an approved-claims-only check against a per-medication artifact owned by clinical/compliance. Failure-handling: schema/length failures fall back to `intervention.default_template`; clinical-claim or prohibited-claims failures defer the outreach with reason `validator_failed:<reason>` and flag for human review.

**Multilingual outreach quality.** The example passes the preferred language to the LLM and trusts the output. Production: per-language regression suites (curated (input_context, expected_output_quality) pairs) that run on every model version change; per-language member-feedback dashboards; a low-confidence fallback to the default localized template when the LLM output fails validation. Spanish, Mandarin, Vietnamese, and Tagalog have different LLM quality characteristics and different cultural conventions for health communication.

**PCP-EHR integration.** The example "posts" the PCP briefing by logging it. Real EHR integration: Epic, Oracle Health (Cerner), Athena, Veradigm each have their own SMART-on-FHIR or proprietary integration surface. Each requires a purpose-built adapter Lambda (or vendor-managed integration), per-EHR credential management in Secrets Manager, message format mapping, and a write-back path so the PCP's response (endorse, decline, defer) flows back into the engagement stream as a `pcp_override` event. The integration work is on the order of months per EHR.

**Partner-pharmacy med-sync API integration.** The example logs a `partner_pharmacy_api` dispatch. Real integration: each pharmacy chain or PSAO publishes a different API for med-sync enrollment. Build per-partner adapter Lambdas, handle credential rotation through Secrets Manager, validate confirmation responses, and write-back enrollment events to the engagement stream. PSAO partnerships shift quarterly; treat the PARTNER_PHARMACIES set as a config table, not a constant.

**Vendor reporting reconciliation.** Pharmacy benefit data, pharmacist consult outcomes, cost-assistance application status, and EHR PCP responses arrive on different cadences and formats: 277CA acknowledgment files, vendor portal exports, occasional flat files emailed to a shared inbox. The engagement events in this example assume a normalized stream; in reality, a per-vendor ingestion layer with explicit schema validation, reconciliation against the recommendation log, and a dead-letter queue for unmatched records is real work. Build it as one Lambda per vendor, not a single dispatch function, so per-vendor schema drift doesn't take down the whole pipeline.

**Star Ratings cycle awareness.** CMS Star Ratings measurement years are calendar-aligned, with cut points published in the spring for the prior measurement year. The recommender should know where in the measurement cycle each target patient sits (months remaining for them to recover their PDC for this measurement year). Encode the cycle in the policy. The cross-functional review committee documents how much capacity is reserved for the high-clinical-need / low-PDC cohort versus the Star-Ratings-attractive 75-79 PDC band; this decision is policy, not an emergent property of the optimization.

**Cross-recipe contact-cap reconciliation.** The patient-profile `outreach_recent_30d_count` in this example is shared with Recipes 4.1, 4.2, 4.4, and any other recipe that generates patient-facing contacts. Production needs a single rolling 30-day total counter that all recipes update, plus per-recipe sub-counters for cohort attribution. Define the policy: at most N total contacts per 30 days, of which at most M are high-touch, with priority-based eviction when caps would be exceeded. The cross-recipe orchestrator owns the policy enforcement; per-recipe orchestrators read and update the shared counter.

**Tracking-ID privacy.** The example builds tracking IDs as `f"adherence-{run_date}-{patient_id}-{therapeutic_class}-{intervention_id}"` for readability. Production must replace this with an opaque, non-reversible identifier (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plain-text patient_ids and therapeutic_classes embedded in tracking IDs (carried in email open-tracking pixels, SMS click-through links, vendor outreach platform handoffs) are PHI leakage. The `_make_tracking_id` helper in this file flags this; fix it before any non-development deployment.

**DynamoDB Decimal gotchas.** The example uses `_to_decimal` and `_to_decimal_dict` consistently when persisting numeric values. The pattern is correct, but the trap is real: if you add a feature that persists a model confidence, an embedding magnitude, or any other floating-point value, you must wrap it at the boundary or DynamoDB will reject the write. Wrap floats in Decimal at the boundary and forget about it.

**Cohort-feature PHI sensitivity.** The recommendation log carries `cohort_features` like `engagement_history_quartile`, `language`, `sdoh_cohort`, `age_band` joined to `patient_id`. The barrier-classifications table is even more sensitive: a row indicating "patient has a cost barrier on diabetes medication" implies socioeconomic distress and a specific clinical condition. Apply customer-managed KMS, CloudTrail data events, narrow IAM read scopes, defined retention (90-180 days for individually-attributed records; longer only after de-identification), and explicit deletion jobs with alarming. A small SDOH cohort in a specific geography is reidentifiable even without direct identifiers.

**Idempotency and retry semantics.** Each stage's outputs are addressed by (run_date, intervention_id, patient_id, therapeutic_class) and writes should be conditional, so a Step Functions retry that re-attempts a completed step is a no-op rather than a duplicate. The example uses `batch_writer` and `put_item` without conditions; production adds `ConditionExpression` to the relevant writes (e.g., `attribute_not_exists(tracking_id)` on the recommendation-log put) so reattempted writes converge.

**Outreach-failure reconciliation paths.** The example handles `intervention_outreach_failed` and `intervention_outreach_bounced` by decrementing the contact-cap counter. Production also adds: a stale-pending sweep for tracking_ids with no engagement-stream activity within 24 hours (suggests a vendor-side processing failure), a per-channel failure-rate alarm (sudden spike in SES bounces or Pinpoint failures triggers operations attention), and a per-vendor reconciliation report against the recommendation log (any tracking_id we expected to dispatch that never produced any event is a missing-handoff candidate).

**Specialty pharmacy adherence.** The example tracks retail and mail-order classes. Specialty medications (biologics, infusions, oral oncology) have completely different fill cadences, different stakeholder relationships, and different clinical workflows. The carry-forward PDC math doesn't apply cleanly. Most plans treat specialty as a separate adherence program with its own intervention catalog and its own measurement methodology; don't shoehorn specialty into this pipeline.

**Newly prescribed medications.** The example's PDC math is meaningful for medications with at least 60-90 days of fill history. A medication first prescribed within the last 30 to 60 days needs a different intervention set: did the patient fill at all (primary adherence)? Build a parallel pipeline with its own target set (newly-prescribed in the last 60 days), its own intervention catalog (cost-assistance navigation, education on the new medication, pharmacist outreach to confirm side-effect tolerance), and its own measurement methodology (primary adherence, not PDC).

**Cost-assistance cascade.** The example treats `cost_assistance` as a single intervention. In production, cost-assistance is a cascade: formulary substitution to a generic if available, manufacturer copay card for branded medications, foundation grant programs, Medicare LIS enrollment for income-eligible Part D members, state pharmaceutical assistance programs, $4 generic lists at major retailers. Build the cascade as a structured workflow with the case-management staff working through the options in order, with a structured outcome at each step, rather than as a single "cost-assistance" intervention type.

**Refill-gap real-time triggers.** Beyond the weekly batch run, an EventBridge rule can fire on a `refill_gap_detected` event (patient is N days past expected refill for a high-priority medication) and trigger a same-day intervention pathway. This collapses the time-to-intervention from a week to hours, which matters for medications where short gaps have meaningful clinical risk (anticoagulants, certain anti-rejection drugs). Build the pathway to share the recommender's allocation logic but bypass the weekly cycle for time-sensitive cases.

**Cohort fairness review process.** The architecture emits cohort-sliced metrics, but a dashboard nobody reviews is useless. Establish a quarterly review with a cross-functional committee (data science, equity lead, medical director, pharmacist lead, vendor management, member services). Watch for: barrier-distribution disparities by language and SDOH cohort (a classifier that under-predicts cost barriers in a specific cohort is encoding bias from training-label distribution); engagement-rate disparities by intervention type within the same cohort; PDC change disparities post-intervention; persistent under-utilization of equity floors. Each finding produces an action item with an owner; close the loop or the dashboards become decoration.

**Outcome evaluation methodology rigor.** The example doesn't ship an outcome-evaluation function; the architecture diagram shows it, but the implementation is intentionally out of scope for a recipe demonstration. Production: pre-register the analysis specification before each evaluation runs (define cohort definitions, outcome definitions, primary statistical test up front), run sensitivity analyses against alternative matching specifications, have a statistical reviewer who is not the team running the recommender, document the methodology in a memo signed by the medical director and the equity lead. Without that rigor, evaluation becomes a marketing artifact rather than honest assessment. Watch especially for the "the program drove PDC up but didn't move clinical outcomes" trap discussed in the main recipe's Honest Take.

**VPC, encryption, and audit.** This example calls APIs over public AWS endpoints. A production Lambda handling PHI runs in a VPC with private subnets and VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock Runtime (interface), SageMaker Runtime and Feature Store (interface), Kinesis (interface), CloudWatch Logs (interface), Athena (interface), Step Functions (`states`), EventBridge (`events`), STS, SES, Pinpoint, and Connect. All six DynamoDB tables encrypt at rest with a customer-managed KMS key. CloudTrail data events are enabled for the patient-profile, intervention-catalog, recommendation-log, barrier-classifications, engagement-events, and pcp-overrides tables. A clinical or compliance audit will eventually ask "who was recommended for what on this date and why" and you need to answer definitively.

**Synthetic data and testing.** There are no tests in this example. A production pipeline needs unit tests for the PDC math (carry-forward, lag, therapeutic-class boundaries), the barrier-classifier rules, the candidate-eligibility filters, the priority math, and the heterogeneous allocator with equity floors; integration tests against a test data lake with synthetic Synthea-generated patients across cohort axes; regression tests that confirm hard exclusion rules (cooldowns, partner-pharmacy requirements, language eligibility) are never bypassed even when scores prefer those candidates; load tests at expected weekly volumes (80K eligible patients across 6 interventions and 5 classes); chaos tests that drop a SageMaker job mid-pipeline and verify Step Functions resumes from the right state. Never use real PHI in non-production environments. [Synthea](https://github.com/synthetichealth/synthea) generates synthetic FHIR patients with realistic prescribing patterns suitable for the adherence pipeline.

**Cold-start handling for new interventions.** The example assumes every intervention has trained engagement and uplift models. A brand-new intervention type has neither. Cold-start strategy: launch new interventions with need-and-barrier-fit scoring only (no uplift), run a randomized pilot for the first 1-2 cycles to bootstrap uplift training data, fall back to need-only scoring if the engagement model is underfitting, document explicitly in the recommendation log that the intervention is in "calibrating" mode. Without this, the recommender will silently over- or under-recommend new interventions based on whatever weak signal the partial models produce.

**Member-stated preferences as hard filters.** The example checks `wellness_consent_active` (inherited from Recipe 4.4 patterns) but doesn't check finer-grained adherence-program preferences (e.g., "I'm not interested in pharmacist calls"). Production member portals collect richer preference data; the recommender treats those as hard filters on top of the eligibility step. Track opt-out rates per intervention type (high opt-out rates signal poor intervention-market fit, not just member preference) and surface them in the equity dashboard.

**Cross-recipe orchestration with Recipe 4.4 (Wellness) and 4.7 (Care Management).** A patient with diabetes who is non-adherent to metformin and not enrolled in DPP and not in care management is a candidate for adherence intervention (here), wellness program enrollment (4.4), and care-management enrollment (4.7) simultaneously. The cross-recipe orchestrator avoids redundant outreach (no four-week-blast of three recipes' recommendations) and sequences (often address adherence first because the medication is already prescribed and a quick win, then enroll in lifestyle programs). Define explicit interaction rules between recommendations from different chapters, with a thin coordinator Lambda that consults all relevant recommenders and picks at most one or two outreach actions per cycle.

**Cost-per-PDC-point-gained tracking.** The cost numbers in the main recipe's Prerequisites table cover infrastructure. Production reporting needs to ladder up to per-intervention total cost (infrastructure + staff time + intervention vendor invoices) divided by PDC points gained in the targeted cohort, separated from organic PDC change (the matched-control comparison). That number gets compared to expected long-horizon savings (avoided hospitalizations, ED visits, complications). The data engineering to track this end-to-end is its own project: an FP&A integration that joins infrastructure spend (Cost and Usage Report) to vendor invoice data (typically a separate AP feed) to recommendation-log records, evaluated monthly.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 4.5: Medication Adherence Intervention Targeting](chapter04.05-medication-adherence-intervention-targeting) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
