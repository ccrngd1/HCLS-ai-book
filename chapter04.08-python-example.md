# Recipe 4.8: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 4.8. It shows one way you could translate the treatment response prediction pattern into working Python using AWS Glue / Athena for cohort construction (target trial emulation), Amazon SageMaker (Training, Pipelines, Model Registry, Real-Time Inference, Batch Transform, Feature Store) for the per-treatment-comparator propensity, outcome, and CATE-ensemble models, Amazon DynamoDB for the treatment catalog, the treatment-comparison-pair specifications, the scoring results, the decision records, the prediction-outcome pairs, and the clinician-facing briefings, Amazon S3 for the cohort archive and model evaluation outputs, AWS Step Functions for the weekly retraining and monthly surveillance pipelines, AWS Lambda for the per-stage glue, Amazon Bedrock for clinician-facing comparison briefings, patient-facing summaries, and disagreement-investigation narratives, Amazon Kinesis for scoring, decision, and outcome events, Amazon API Gateway and Cognito for the on-demand scoring API consumed by the EHR via SMART on FHIR or CDS Hooks, and AWS HealthLake for FHIR-native clinical data. It is not production-ready. There is no real claims, EHR, lab, pharmacy, or registry feed integration, no actual causal-inference modeling pipeline (the example uses rule-based proxies for the propensity, outcome, and CATE estimators), no real target trial emulation against historical data, no calibration drift detection against a longitudinal observation set, no clinical-informatics review of the model promotion gate, no FDA SaMD predetermined change control plan, no real EHR integration via SMART on FHIR or CDS Hooks, no live cohort fairness instrumentation tied to a quarterly review committee. Think of it as the sketchpad version: useful for understanding the shape of a per-treatment-comparator CATE pipeline that respects causal-inference rigor, uncertainty quantification, equity instrumentation, and the regulatory posture appropriate for clinical decision support, not something you'd wire into an EHR on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the six pseudocode steps from the main recipe: construct the cohort and outcome labels per treatment-comparator pair using target trial emulation, train per-pair propensity, outcome, and CATE-ensemble models, evaluate with calibration and fairness tests and gate model promotion through governance, score an index patient on demand at the point of care with similar-patient cohort retrieval and uncertainty quantification, generate the clinician-facing comparison briefing with strict validator enforcement, and capture the clinician's decision and the patient's subsequent outcome and feed the matched pair back into surveillance and retraining. All sample patients, treatments, cohorts, predictions, decisions, and outcomes are synthetic.

---

## Setup

You'll need the AWS SDK for Python and a couple of utility libraries:

```bash
pip install boto3 pandas numpy
```

For local causal-inference experimentation (training scripts not shown in the inference path) you'd add `econml`, `dowhy`, `causalml`, `scikit-learn`, `xgboost`, `lifelines`, and (for the BART arm of the CATE ensemble) `pymc-bart` or an R wrapper around `bcf`. The inference path itself only needs the SageMaker Real-Time Inference and Batch Transform output, so the production Lambdas don't import those libraries.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `sagemaker:CreateTrainingJob`, `sagemaker:CreateTransformJob`, `sagemaker:DescribeTransformJob`, `sagemaker:InvokeEndpoint`, `sagemaker:DescribeModelPackage` on specific model and endpoint ARNs (the per-pair propensity, outcome, and CATE-ensemble models)
- `sagemaker:GetRecord`, `sagemaker:BatchGetRecord`, `sagemaker:PutRecord` on the SageMaker Feature Store feature group ARNs (`patient-features-online`, `patient-features-offline`, `treatment-history-features`)
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchWriteItem` on the treatment-catalog, treatment-comparison-pairs, scoring-results, briefings, decision-records, prediction-outcome-pairs, cohort-metadata, governance-review-tasks, and surveillance-alerts tables
- `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on the trx-cohorts, trx-eval, and trx-surveillance buckets
- `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults` for the cohort-construction and outcome-evaluation pipelines
- `glue:GetTable`, `glue:GetPartitions` on the data-catalog tables Athena reads
- `bedrock:InvokeModel` on the specific model ARNs used for comparison briefings, patient-facing summaries, and disagreement-investigation narratives (e.g., a Claude Sonnet for clinician briefings and Claude Haiku for routine summaries)
- `kinesis:PutRecord` on the trx-events stream
- `healthlake:SearchWithGet` and related read actions scoped to the relevant data store (if HealthLake is in the architecture)
- `apigateway:Invoke` for the scoring API
- `cloudwatch:PutMetricData` for cohort-sliced metrics
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs

You also need model access enabled in the Bedrock console for the comparison-briefing, patient-summary, and disagreement-narrative models.

A few things worth knowing upfront:

- **The treatment catalog is the source of truth for what each treatment-comparator pair means.** This example ships with a small synthetic catalog of 3 pairs covering second-line T2D therapy comparisons (GLP-1 vs SGLT2, GLP-1 vs sulfonylurea, SGLT2 vs sulfonylurea). Production needs structured change management with pharmacy and therapeutics, clinical informatics, health economics and outcomes research, and compliance, with parallel evaluation against the prior catalog version when significant changes ship.
- **Causal-inference modeling is the hardest part and the part most teams skip.** Production-grade CATE estimation requires target trial emulation, propensity-score modeling with overlap diagnostics, outcome modeling, an ensemble of estimators from different method families (causal forest, DR-learner, BART or equivalent), uncertainty quantification combining sampling, model-agreement, and sensitivity-analysis bounds, and calibration testing on held-out cohorts and protected subgroups. The training scripts are out of scope for this companion; the main recipe's "Why This Isn't Production-Ready" section walks through the gap. The example uses rule-based proxies.
- **The clinician-facing briefing is the surface where a careless LLM does real damage.** The validator enforces strict no-recommendation language, explicit uncertainty, and required caveats. This example codes the four-layer validator as a single function for readability; production breaks the layers apart for testability and per-layer alarms.
- **Bedrock model IDs change over time.** Some regions require cross-region inference profile IDs (prefixed `us.` or `eu.`). The IDs below are reasonable defaults; verify in the Bedrock console for your region before running.
- **All patients, treatments, cohorts, predictions, decisions, and outcomes in the example are synthetic.** Do not treat any specific patient_id, treatment_id, comparator_id, prediction, or outcome as real. A production system ingests from real claims, EHR, lab, pharmacy, registry, and PROM feeds under BAA.
- **The example collapses Step Functions, Glue, Athena, SageMaker Pipelines, and SageMaker Real-Time Inference into a single Python file for readability.** In production these are separate workflow stages with their own error handling, IAM, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, table names, S3 buckets, validator thresholds, OOD-flag policies, and the catalog of treatment-comparator pairs are the knobs you'll change between environments.

```python
import json
import logging
import math
import re
import time
import uuid
import datetime
from datetime import timezone, timedelta
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records to
# CloudWatch Logs Insights. Never log a raw (patient_id, treatment_id,
# comparator_id, predicted_effect, similar_patient_cohort_features)
# join. The row implicitly identifies the patient, the suspected
# clinical condition, and the treatment options being weighed; the
# scoring-results, briefings, and decision-records tables are
# clinical-record-equivalent PHI.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from SageMaker, DynamoDB, Bedrock,
# Kinesis, S3, and Athena. The point-of-care scoring path is bursty
# (clinician opens a chart and requests scoring), and the weekly
# retraining and monthly surveillance pipelines run heavy batch loads.
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

# --- Bedrock Model Configuration ---
# Three distinct LLM use cases. Clinician-facing comparison briefings
# go to a Sonnet-class model because the prompt is long-context and
# the validator's recommendation-language rule is strict; the larger
# model gives a better first-pass-pass rate. Patient-facing summaries
# and disagreement-investigation narratives use a Haiku-class model
# because they're shorter and cheaper at scale.
COMPARISON_BRIEFING_MODEL_ID    = "anthropic.claude-3-5-sonnet-20241022-v2:0"
PATIENT_SUMMARY_MODEL_ID         = "anthropic.claude-3-5-haiku-20241022-v1:0"
DISAGREEMENT_NARRATIVE_MODEL_ID  = "anthropic.claude-3-5-haiku-20241022-v1:0"

# --- DynamoDB Table Names ---
# Nine tables. Keep them separate so access patterns stay clean and
# IAM scoping is precise:
#   1. treatment-catalog:           catalog of treatments and metadata
#   2. treatment-comparison-pairs:  per-pair model and protocol pointers
#   3. cohort-metadata:             per-(pair, protocol_version, run)
#                                    archive pointer
#   4. scoring-results:             per (patient, scoring_run)
#                                    structured result feeding briefings
#   5. briefings:                   LLM-generated clinician briefings
#   6. decision-records:            clinician's recorded decision plus
#                                    frozen-at-decision-time predictions
#   7. prediction-outcome-pairs:    matched predicted-vs-actual outcomes
#   8. governance-review-tasks:     pending-promotion review queue
#   9. surveillance-alerts:         calibration drift, fairness drift,
#                                    adverse-event rate alerts
TREATMENT_CATALOG_TABLE          = "treatment-catalog"
TREATMENT_COMPARISON_PAIRS_TABLE = "treatment-comparison-pairs"
COHORT_METADATA_TABLE            = "cohort-metadata"
SCORING_RESULTS_TABLE            = "scoring-results"
BRIEFINGS_TABLE                  = "briefings"
DECISION_RECORDS_TABLE           = "decision-records"
PREDICTION_OUTCOME_PAIRS_TABLE   = "prediction-outcome-pairs"
GOVERNANCE_REVIEW_TASKS_TABLE    = "governance-review-tasks"
SURVEILLANCE_ALERTS_TABLE        = "surveillance-alerts"

# --- S3 Buckets ---
# Production: each bucket has its own KMS key and bucket policy.
# Replace placeholder names with your account's buckets.
TRX_COHORTS_BUCKET       = "trx-cohorts"
TRX_EVAL_BUCKET          = "trx-eval"
TRX_SURVEILLANCE_BUCKET  = "trx-surveillance"
TRX_DATA_LAKE_BUCKET     = "trx-data-lake"
ATHENA_RESULTS_BUCKET    = "trx-athena-results"

# --- Athena ---
ATHENA_WORKGROUP = "trx-recommender"
ATHENA_DATABASE  = "trx_data_lake"

# --- Kinesis ---
# Same engagement-event-bus pattern as Recipes 4.4 through 4.7, with
# new event types specific to this recipe: cohort_constructed,
# training_suspended, governance_review_pending, model_promoted,
# treatment_scoring_requested, treatment_scoring_completed,
# treatment_scoring_oodflag_triggered, briefing_generated,
# briefing_validator_fallback, treatment_decision_recorded,
# treatment_outcome_observed, prediction_calibration_alert,
# disagreement_alert.
TRX_EVENTS_STREAM_NAME = "trx-events"

# --- Run Configuration ---
POLICY_VERSION = "trx-policy-v0.1"

# CATE ensemble configuration. The example simulates an ensemble of
# three estimators (causal forest, DR-learner, BART). Production
# trains all three through SageMaker BYOC containers with EconML,
# bartCause, or grf wrappers and registers them in the SageMaker
# Model Registry. The agreement threshold below determines when
# disagreement triggers an alert; lower values are stricter.
CATE_ESTIMATOR_NAMES = ["causal_forest", "dr_learner", "bart"]
DISAGREEMENT_THRESHOLD = 0.30   # spread of point estimates across
                                # estimators normalized to the
                                # outcome's natural scale

# Minimum sample size for fairness analysis within a protected
# cohort. Below this size, fairness metrics are too unreliable to
# act on; the system reports "insufficient sample" rather than a
# misleading number.
MIN_FAIRNESS_SAMPLE_SIZE = 30

# Calibration-slope thresholds. A well-calibrated model has slope
# near 1.0; values outside this band trigger a calibration warning
# at the governance gate.
CALIBRATION_SLOPE_LOW   = 0.7
CALIBRATION_SLOPE_HIGH  = 1.3

# Surveillance window for calibration drift detection (days).
# Production typically uses 90 days for outcomes that read out at
# 90 days and longer for outcomes with longer time-to-readout.
SURVEILLANCE_WINDOW_DAYS  = 90
DRIFT_ALERT_THRESHOLD     = 0.20  # absolute change in slope or
                                  # intercept relative to baseline
COHORT_DRIFT_ALERT_THRESHOLD = 0.25

# OOD policy. The example computes a simple severity from propensity
# distance and density of similar patients; production uses a more
# sophisticated combination of propensity tail-flag, embedding-
# distance, and isolation-forest-based anomaly score.
OOD_SEVERITY_WARNING_THRESHOLD = 0.50
OOD_SEVERITY_SUPPRESS_THRESHOLD = 0.85

# Minimum size of similar-patient cohort to summarize. Below this
# size, the demographic and outcome summaries are too noisy to be
# useful; the system suppresses the cohort summary rather than
# present a misleading number.
MIN_SIMILAR_PATIENT_COHORT = 25

# Briefing TTL. A briefing generated for a Tuesday visit should not
# be presented unchanged at a Friday visit; the EHR re-requests
# scoring if the briefing is older than this.
BRIEFING_TTL_HOURS = 24

# Validator regeneration attempts before falling back to templated
# briefing.
MAX_REGENERATION_ATTEMPTS = 2

# CloudWatch namespace for treatment-response metrics. Slice by
# treatment_pair_id, cohort axis, OOD severity, and disagreement
# flag to catch subgroup drift.
METRIC_NAMESPACE = "TreatmentResponseRecommender"

# Model risk tier thresholds. The catalog tags each pair with a
# tier; tier-1 may qualify for the 21st Century Cures Act CDS
# exemption, tier-2 and above are likely SaMD with corresponding
# regulatory documentation requirements.
MODEL_RISK_TIERS = {
    "tier_1_advisory_only_well_evidenced": "low_risk",
    "tier_2_advisory_observational":       "moderate_risk",
    "tier_3_higher_stakes":                "high_risk",
}
```

---

## Reference Data: Synthetic Treatment Catalog and Comparison Pairs

A small treatment catalog used by the example. Production loads from the `treatment-catalog` and `treatment-comparison-pairs` DynamoDB tables, fed by pharmacy and therapeutics through a governance UI and versioned. Each pair has a target trial protocol (eligibility, washout, exposure, comparator, outcome, follow-up, censoring), evidence level, formulary status, and a model-risk tier.

```python
# Synthetic treatment catalog. Three drug classes covering the
# T2D second-line therapy decision space from the recipe's opening
# narrative. Production catalog has dozens of treatments across
# multiple conditions; the example keeps it small for tractability.
SAMPLE_TREATMENT_CATALOG = [
    {
        "treatment_id":     "glp1_receptor_agonist_class",
        "display_name":     "GLP-1 Receptor Agonist (class)",
        "rxnorm_class":     "GLP-1RA",
        "primary_indication": "type_2_diabetes",
        "formulary_status": "tier_2_with_prior_auth",
        "supply_status":    "constrained_intermittent",
    },
    {
        "treatment_id":     "sglt2_inhibitor_class",
        "display_name":     "SGLT2 Inhibitor (class)",
        "rxnorm_class":     "SGLT2",
        "primary_indication": "type_2_diabetes",
        "formulary_status": "tier_1",
        "supply_status":    "available",
    },
    {
        "treatment_id":     "sulfonylurea_class",
        "display_name":     "Sulfonylurea (class)",
        "rxnorm_class":     "SU",
        "primary_indication": "type_2_diabetes",
        "formulary_status": "tier_1",
        "supply_status":    "available",
    },
]

# Synthetic treatment-comparison-pair catalog. Each pair specifies
# the target trial protocol, the model-risk tier, the production
# CATE-estimator endpoint pointers, and the governance metadata.
SAMPLE_PAIR_CATALOG = [
    {
        "pair_id":              "t2d-glp1-vs-sglt2",
        "treatment_id":         "glp1_receptor_agonist_class",
        "comparator_id":        "sglt2_inhibitor_class",
        "indication":           "type_2_diabetes_inadequately_controlled_on_metformin",
        "primary_outcome_id":   "a1c_change_at_90_days",
        "secondary_outcomes":   ["weight_change_at_90_days",
                                  "hypoglycemia_event_at_90_days",
                                  "gi_intolerance_discontinuation_60_days"],
        "model_risk_tier":      "tier_2_advisory_observational",
        "evidence_level":       "RCT_supported_with_observational_extension",
        "guideline_references": ["ada_standards_of_care_2026_section_9.4",
                                   "kdigo_2024_diabetes_guidelines"],
        "is_production":        True,
        "production_calibration_status": "production_calibrated_2026Q1",
        "fairness_axes":        ["language", "race_ethnicity_self_report",
                                   "sdoh_cohort", "age_band"],
        "protocol_version":     "2026-v1",
        "feature_set_version":  "v3",
        "production_pair_endpoints": {
            "causal_forest": "trx-cf-t2d-glp1-vs-sglt2-prod",
            "dr_learner":    "trx-dr-t2d-glp1-vs-sglt2-prod",
            "bart":          "trx-bart-t2d-glp1-vs-sglt2-prod",
        },
    },
    {
        "pair_id":              "t2d-glp1-vs-sulfonylurea",
        "treatment_id":         "glp1_receptor_agonist_class",
        "comparator_id":        "sulfonylurea_class",
        "indication":           "type_2_diabetes_inadequately_controlled_on_metformin",
        "primary_outcome_id":   "a1c_change_at_90_days",
        "secondary_outcomes":   ["weight_change_at_90_days",
                                  "hypoglycemia_event_at_90_days"],
        "model_risk_tier":      "tier_2_advisory_observational",
        "evidence_level":       "RCT_supported_with_observational_extension",
        "guideline_references": ["ada_standards_of_care_2026_section_9.4"],
        "is_production":        True,
        "production_calibration_status": "production_calibrated_2026Q1",
        "fairness_axes":        ["language", "race_ethnicity_self_report",
                                   "sdoh_cohort", "age_band"],
        "protocol_version":     "2026-v1",
        "feature_set_version":  "v3",
        "production_pair_endpoints": {
            "causal_forest": "trx-cf-t2d-glp1-vs-su-prod",
            "dr_learner":    "trx-dr-t2d-glp1-vs-su-prod",
            "bart":          "trx-bart-t2d-glp1-vs-su-prod",
        },
    },
    {
        "pair_id":              "t2d-sglt2-vs-sulfonylurea",
        "treatment_id":         "sglt2_inhibitor_class",
        "comparator_id":        "sulfonylurea_class",
        "indication":           "type_2_diabetes_inadequately_controlled_on_metformin",
        "primary_outcome_id":   "a1c_change_at_90_days",
        "secondary_outcomes":   ["weight_change_at_90_days",
                                  "hypoglycemia_event_at_90_days",
                                  "egfr_change_at_180_days"],
        "model_risk_tier":      "tier_2_advisory_observational",
        "evidence_level":       "RCT_supported_with_observational_extension",
        "guideline_references": ["ada_standards_of_care_2026_section_9.4",
                                   "kdigo_2024_diabetes_guidelines"],
        "is_production":        True,
        "production_calibration_status": "production_calibrated_2026Q1",
        "fairness_axes":        ["language", "race_ethnicity_self_report",
                                   "sdoh_cohort", "age_band"],
        "protocol_version":     "2026-v1",
        "feature_set_version":  "v3",
        "production_pair_endpoints": {
            "causal_forest": "trx-cf-t2d-sglt2-vs-su-prod",
            "dr_learner":    "trx-dr-t2d-sglt2-vs-su-prod",
            "bart":          "trx-bart-t2d-sglt2-vs-su-prod",
        },
    },
]

# Target trial protocol per pair. Specifies eligibility, washout,
# exposure assignment, censoring, and outcome timing. Production
# stores this in the treatment-comparison-pairs table; the example
# inlines it for clarity.
SAMPLE_PROTOCOLS = {
    "t2d-glp1-vs-sglt2": {
        "version":       "2026-v1",
        "eligibility": {
            "diagnosis_required":            "type_2_diabetes",
            "current_medication_required":   "metformin_monotherapy",
            "a1c_min_at_index":              7.0,
            "a1c_max_at_index":              12.0,
            "egfr_min_at_index":             30,
            "exclusions":                    ["type_1_diabetes", "pregnancy",
                                               "active_malignancy",
                                               "dialysis_dependent"],
            "continuous_enrollment_months":  6,
        },
        "washout": {
            "days":              180,
            "excluded_exposures": ["glp1_receptor_agonist_class",
                                    "sglt2_inhibitor_class",
                                    "dpp4_inhibitor_class",
                                    "thiazolidinedione_class"],
        },
        "exposure_definitions": {
            "treated":    "first_dispense_glp1_within_30_days_of_index",
            "comparator": "first_dispense_sglt2_within_30_days_of_index",
        },
        "outcomes": [
            {"outcome_id":   "a1c_change_at_90_days",
              "measurement_window_days": 90,
              "tolerance_days": 14,
              "censor_on_treatment_switch": True,
              "censor_on_discontinuation": False},
            {"outcome_id":   "weight_change_at_90_days",
              "measurement_window_days": 90,
              "tolerance_days": 14},
            {"outcome_id":   "hypoglycemia_event_at_90_days",
              "measurement_window_days": 90,
              "binary": True},
            {"outcome_id":   "gi_intolerance_discontinuation_60_days",
              "measurement_window_days": 60,
              "binary": True},
        ],
        "feature_set_version":           "v3",
        "propensity_hyperparameters":    {"max_depth": 6, "n_estimators": 400,
                                            "learning_rate": 0.05},
        "outcome_hyperparameters": {
            "a1c_change_at_90_days":     {"max_depth": 6, "n_estimators": 600,
                                            "learning_rate": 0.05},
        },
        "cate_hyperparameters": {
            "causal_forest": {"n_estimators": 1000, "min_samples_leaf": 20,
                                "honest": True},
            "dr_learner":    {"max_depth": 5, "n_estimators": 500},
            "bart":          {"n_trees": 200, "n_chains": 4, "n_samples": 2000},
        },
    },
}

# Sensitivity-analysis bounds per pair. Pre-computed at training
# time and used at scoring time to widen reported CIs. The example
# uses a fixed multiplier; production runs E-value computations and
# Rosenbaum bounds per pair.
SAMPLE_SENSITIVITY_BOUNDS = {
    "t2d-glp1-vs-sglt2":     {"e_value": 1.84, "ci_widen_multiplier": 1.20},
    "t2d-glp1-vs-sulfonylurea": {"e_value": 1.21, "ci_widen_multiplier": 1.45},
    "t2d-sglt2-vs-sulfonylurea": {"e_value": 1.62, "ci_widen_multiplier": 1.25},
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
    failure never breaks the scoring pipeline. Metric publishing is
    best-effort observability, not a correctness boundary.
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

def _make_scoring_run_id(patient_id: str, run_date: str) -> str:
    """
    Scoring run ID used to join scoring results to briefings to
    decisions to outcomes.

    NOTE: This example uses a readable string for clarity. Production
    must replace this with an opaque, non-reversible identifier (UUID
    or HMAC-SHA256 over the composite with a per-environment secret).
    Plain-text patient_ids embedded in scoring IDs (carried in
    EHR responses, scoring API responses, briefings, and decision
    events) are PHI leakage. Mirror the language from 4.4 through 4.7.
    """
    return f"score-{run_date}-{patient_id}-{uuid.uuid4().hex[:8]}"

def _make_briefing_id() -> str:
    """Opaque briefing identifier."""
    return f"brief-{uuid.uuid4().hex[:16]}"

def _make_decision_id() -> str:
    """Opaque decision identifier."""
    return f"decision-{uuid.uuid4().hex[:16]}"

def _make_cohort_id(pair_id: str, protocol_version: str, run_date: str) -> str:
    """Cohort identifier joining cohort archive to model artifacts."""
    return f"cohort-{pair_id}-{protocol_version}-{run_date}"

def _wait_for_athena_query(execution_id: str,
                              timeout_seconds: int = 300) -> None:
    """Poll Athena until the query reaches a terminal state."""
    start = time.time()
    while True:
        response = athena_client.get_query_execution(
            QueryExecutionId=execution_id)
        state = response["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return
        if state in ("FAILED", "CANCELLED"):
            reason = response["QueryExecution"]["Status"].get(
                "StateChangeReason", "")
            raise RuntimeError(
                f"Athena query {execution_id} {state}: {reason}")
        if time.time() - start > timeout_seconds:
            raise TimeoutError(f"Athena query {execution_id} timed out")
        time.sleep(2)

def _redact_identifiers(items: list) -> list:
    """
    Strip patient/clinician identifiers from a list of records before
    sending to an LLM. The LLM doesn't need them, and stripping at the
    boundary limits any vendor-side logging exposure (Bedrock service
    terms commit to not training on prompts, but defense-in-depth
    still applies).
    """
    redacted = []
    for item in items:
        copy = dict(item)
        for field in ("patient_id", "clinician_id", "scoring_run_id",
                       "briefing_id", "decision_id"):
            copy.pop(field, None)
        redacted.append(copy)
    return redacted

def _cohort_features_from_profile(patient: dict) -> dict:
    """Pull cohort features for fairness instrumentation from the profile."""
    return {
        "language":                 patient.get("preferred_language", "en"),
        "race_ethnicity_self_report": patient.get(
            "race_ethnicity_self_report", "unknown"),
        "sdoh_cohort":              patient.get("sdoh_cohort", "unknown"),
        "age_band":                 patient.get("age_band", "unknown"),
    }

def _lookup_pair(pair_id: str, pair_catalog: list) -> dict:
    """Return the pair spec for a given pair_id, or {} if not found."""
    for pair in pair_catalog:
        if pair["pair_id"] == pair_id:
            return pair
    return {}

def _lookup_treatment(treatment_id: str, treatment_catalog: list) -> dict:
    """Return the treatment spec for a given treatment_id, or {}."""
    for tx in treatment_catalog:
        if tx["treatment_id"] == treatment_id:
            return tx
    return {}
```

---

## Step 1: Construct the Cohort and Outcome Labels per Treatment-Comparator Pair Using Target Trial Emulation

*The pseudocode calls this `construct_cohort(treatment_pair, run_date)`. The target trial protocol is the explicit specification of the analysis, and the cohort construction implements it: who is eligible, when the index date is, what the washout window excludes, what the treatment exposure is, what the comparator is, what the outcomes are with explicit timing, and what censoring rules apply. Skip the explicit protocol and you build a cohort with implicit decisions that bias every downstream estimate in ways nobody can audit.*

```python
def construct_cohort(pair: dict, run_date: str,
                       protocols: dict = None) -> dict:
    """
    Run target trial emulation for a single treatment-comparator pair.

    Steps:
      A. Identify candidate patients from the data lake using the
         protocol's eligibility predicates.
      B. Apply the washout window to exclude patients with relevant
         prior exposures.
      C. Assign treatment exposure to each eligible patient based on
         what they were actually prescribed at the index date.
      D. Construct outcome labels at the protocol-specified timing,
         with censoring rules.
      E. Persist the cohort to S3 (versioned, partitioned by pair
         and protocol version).
      F. Persist cohort metadata for traceability.

    Returns the cohort metadata record (without the full cohort,
    which is in S3).
    """
    pair_id = pair["pair_id"]
    protocols = protocols or SAMPLE_PROTOCOLS
    protocol = protocols.get(pair_id, {})
    if not protocol:
        logger.warning("No protocol for pair %s; skipping", pair_id)
        return {}

    protocol_version = protocol["version"]
    cohort_id = _make_cohort_id(pair_id, protocol_version, run_date)

    # Step 1A: candidate patients. Production: parameterized SQL on
    # the data lake joining the eligibility view with the encounter,
    # diagnosis, medication, lab, and enrollment tables. The example
    # delegates to a stub that returns a synthetic cohort.
    candidates = _athena_candidate_query(protocol, run_date)

    # Step 1B: washout. Exclude patients with relevant prior
    # exposures within the washout window. Per-pair washout because
    # what counts as a relevant prior exposure depends on what is
    # being compared.
    eligible = _athena_washout_query(candidates, protocol, run_date)

    # Step 1C: assign exposure. For each eligible patient, determine
    # whether they fell into the treated or comparator arm based on
    # what was actually prescribed at the index date. Patients who
    # received neither (or both within the protocol's grace window)
    # are excluded from this pair's cohort.
    cohort_treated = _assign_arm(
        eligible, protocol["exposure_definitions"]["treated"], "treated",
    )
    cohort_comparator = _assign_arm(
        eligible, protocol["exposure_definitions"]["comparator"], "comparator",
    )
    cohort = cohort_treated + cohort_comparator

    # Step 1D: construct outcome labels. For each cohort member,
    # compute outcomes at the protocol-specified timing with
    # censoring rules.
    cohort_with_outcomes = []
    for member in cohort:
        outcomes = {}
        for outcome_def in protocol["outcomes"]:
            outcomes[outcome_def["outcome_id"]] = _compute_outcome(
                member, outcome_def, protocol,
            )
        cohort_with_outcomes.append({
            "patient_id":      member["patient_id"],
            "treatment_arm":    member["treatment_arm"],
            "index_date":       member["index_date"],
            "covariates":       member["covariates"],   # feature vector at index
            "outcomes":         outcomes,
            "protocol_version": protocol_version,
        })

    # Step 1E: persist cohort to S3 (in production, written as
    # Parquet partitioned by pair_id and protocol_version). The
    # example writes a JSON line list for inspection.
    cohort_s3_path = (
        f"s3://{TRX_COHORTS_BUCKET}/pair={pair_id}/"
        f"protocol_version={protocol_version}/run_date={run_date}/cohort.jsonl"
    )
    try:
        s3_client.put_object(
            Bucket=TRX_COHORTS_BUCKET,
            Key=(f"pair={pair_id}/protocol_version={protocol_version}/"
                  f"run_date={run_date}/cohort.jsonl"),
            Body="\n".join(
                json.dumps(rec, default=str) for rec in cohort_with_outcomes
            ).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to persist cohort for %s: %s; continuing with metadata only",
            pair_id, exc,
        )

    treated_size    = sum(1 for r in cohort_with_outcomes
                            if r["treatment_arm"] == "treated")
    comparator_size = sum(1 for r in cohort_with_outcomes
                            if r["treatment_arm"] == "comparator")

    metadata = {
        "cohort_id":         cohort_id,
        "pair_id":           pair_id,
        "protocol_version":  protocol_version,
        "run_date":          run_date,
        "cohort_path":       cohort_s3_path,
        "size_treated":      treated_size,
        "size_comparator":   comparator_size,
        "outcome_definitions": [o["outcome_id"] for o in protocol["outcomes"]],
        "feature_set_version": protocol["feature_set_version"],
        "constructed_at":    _now_iso(),
    }

    # Step 1F: persist cohort metadata for traceability.
    metadata_table = dynamodb.Table(COHORT_METADATA_TABLE)
    try:
        metadata_table.put_item(Item=_to_decimal_dict(metadata))
    except Exception as exc:
        logger.warning(
            "Failed to persist cohort metadata for %s: %s", cohort_id, exc,
        )

    try:
        kinesis_client.put_record(
            StreamName=TRX_EVENTS_STREAM_NAME,
            PartitionKey=pair_id,
            Data=json.dumps({
                "event_type":      "cohort_constructed",
                "cohort_id":       cohort_id,
                "pair_id":         pair_id,
                "size_treated":    treated_size,
                "size_comparator": comparator_size,
                "timestamp":       _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to publish cohort_constructed event: %s", exc,
        )

    logger.info(
        "Cohort %s: %d treated, %d comparator",
        cohort_id, treated_size, comparator_size,
    )
    return metadata

def _athena_candidate_query(protocol: dict, run_date: str) -> list:
    """
    Production: Athena query on the data lake using the protocol's
    eligibility predicates. Demo: return the synthetic cohort.
    """
    return _DEMO_CANDIDATE_COHORT

def _athena_washout_query(candidates: list, protocol: dict,
                            run_date: str) -> list:
    """
    Production: Athena query joining candidate patients with the
    medication-exposure view to apply the washout. Demo: stub
    that returns candidates as-is, since the synthetic cohort is
    pre-filtered.
    """
    return candidates

def _assign_arm(eligible: list, exposure_definition: str, arm: str) -> list:
    """
    Apply the exposure definition to assign each eligible patient
    to the treated or comparator arm. Production: SQL pattern that
    looks at the medication-dispense view; the example uses a
    pre-tagged synthetic cohort.
    """
    out = []
    for patient in eligible:
        if patient.get("synthetic_treatment_arm") == arm:
            out.append({
                **patient,
                "treatment_arm": arm,
            })
    return out

def _compute_outcome(member: dict, outcome_def: dict,
                      protocol: dict) -> dict:
    """
    Compute the outcome value for a cohort member at the
    protocol-specified timing, with censoring. Production: pull
    longitudinal lab, encounter, and medication data; apply the
    outcome definition's measurement window and tolerance; flag
    censoring on treatment switch, plan disenrollment, or death.
    The example reads from a synthetic per-patient outcome dict.
    """
    outcome_id = outcome_def["outcome_id"]
    raw = member.get("synthetic_outcomes", {}).get(outcome_id)
    if raw is None:
        return {
            "value":         None,
            "observed":      False,
            "censored":      True,
            "censor_reason": "no_observed_outcome_in_window",
        }
    return {
        "value":         raw["value"],
        "observed":      raw.get("observed", True),
        "censored":      raw.get("censored", False),
        "censor_reason": raw.get("censor_reason"),
    }

# Synthetic candidate cohort populated by the runner at the bottom
# of this file. In production this comes from Athena.
_DEMO_CANDIDATE_COHORT: list = []
```

---

## Step 2: Train the Propensity, Outcome, and CATE-Ensemble Models per Treatment-Comparator Pair

*The pseudocode calls this `train_pair_models(cohort_id, run_date)`. Three model families per pair: a propensity model (probability of receiving treatment given covariates), an outcome model (outcome given covariates and treatment), and a CATE estimator ensemble (causal forest, DR-learner, BART). Skip the ensemble and you cannot tell whether your point estimate is robust or a methodological artifact. Skip the propensity-overlap diagnostic and you ship CATE estimates that are extrapolating across the distribution gap between the treated and comparator arms, which is exactly the case where the estimates are least reliable.*

```python
def train_pair_models(cohort_metadata: dict, run_date: str) -> dict:
    """
    Train the propensity, outcome, and CATE-ensemble models for a
    single treatment-comparator pair.

    Production: each training stage launches a SageMaker Training
    Job with a BYOC container that wraps EconML, grf, or bartCause.
    The example simulates training by registering pseudo-model ARNs
    and computing a synthetic propensity-overlap diagnostic.

    Returns a dict with the training status and the registered model
    pointers, or {"status": "suspended", "reason": "..."} if the
    propensity-overlap check fails.
    """
    cohort_id = cohort_metadata["cohort_id"]
    pair_id   = cohort_metadata["pair_id"]
    pair      = _lookup_pair(pair_id, SAMPLE_PAIR_CATALOG)

    # ---- Stage A: propensity score model ----
    # Predicts P(treatment = treated | covariates X). Trained on
    # the full cohort with treatment_arm as the binary label.
    # XGBoost with isotonic calibration is a reasonable baseline;
    # logistic regression is the simplest comparator. Production
    # cross-validates and evaluates calibration on a held-out set.
    propensity_model_arn = _simulate_training_job(
        algorithm="xgboost-with-isotonic-calibration",
        cohort_id=cohort_id,
        target="treatment_arm_treated",
        family="propensity",
        run_date=run_date,
        pair_id=pair_id,
    )

    # Propensity overlap diagnostic. If the treated and comparator
    # cohorts have substantially non-overlapping covariate
    # distributions, the CATE estimator is extrapolating across the
    # gap, and the resulting estimates are dominated by modeling
    # assumptions rather than data. This is a HARD GATE: insufficient
    # overlap suspends training for this pair until the cohort can
    # be re-scoped (different eligibility, different comparator).
    overlap = _assess_propensity_overlap(propensity_model_arn,
                                            cohort_metadata)
    if overlap["severe"]:
        logger.warning(
            "Propensity overlap severe for %s; suspending training",
            pair_id,
        )
        try:
            kinesis_client.put_record(
                StreamName=TRX_EVENTS_STREAM_NAME,
                PartitionKey=pair_id,
                Data=json.dumps({
                    "event_type": "training_suspended",
                    "cohort_id":  cohort_id,
                    "pair_id":    pair_id,
                    "reason":     "propensity_overlap_severe",
                    "details":    overlap,
                    "timestamp":  _now_iso(),
                }, default=str).encode("utf-8"),
            )
        except Exception:
            pass
        return {
            "status":  "suspended",
            "reason":  "propensity_overlap_severe",
            "details": overlap,
        }

    # ---- Stage B: outcome model(s) ----
    # Predicts E[Y | X, T] for each outcome of interest. The
    # outcome model is one of the inputs to the meta-learners
    # (DR-learner, X-learner). Trained on the full cohort with
    # outcome as the label and treatment as a feature.
    outcome_model_arns = {}
    for outcome_id in cohort_metadata["outcome_definitions"]:
        outcome_model_arns[outcome_id] = _simulate_training_job(
            algorithm="xgboost-regression",
            cohort_id=cohort_id,
            target=outcome_id,
            family="outcome",
            run_date=run_date,
            pair_id=pair_id,
        )

    # ---- Stage C: CATE estimator ensemble ----
    # At least two methods from different families. The ensemble
    # surfaces estimator disagreement, which is a structural-
    # uncertainty signal that no single estimator can provide.
    cate_estimator_arns = {}
    for estimator_name in CATE_ESTIMATOR_NAMES:
        cate_estimator_arns[estimator_name] = _simulate_training_job(
            algorithm=f"cate-{estimator_name}",
            cohort_id=cohort_id,
            target="treatment_effect",
            family=f"cate_{estimator_name}",
            run_date=run_date,
            pair_id=pair_id,
        )

    # Persist training status to the pairs table for the governance
    # gate to read in Step 3.
    pairs_table = dynamodb.Table(TREATMENT_COMPARISON_PAIRS_TABLE)
    try:
        pairs_table.update_item(
            Key={"pair_id": pair_id},
            UpdateExpression=(
                "SET training_status = :st, "
                "propensity_model_arn = :pm, "
                "outcome_model_arns = :om, "
                "cate_estimator_arns = :cm, "
                "cohort_id = :cid, "
                "last_training_run = :run"
            ),
            ExpressionAttributeValues=_to_decimal_dict({
                ":st":  "trained_pending_evaluation",
                ":pm":  propensity_model_arn,
                ":om":  outcome_model_arns,
                ":cm":  cate_estimator_arns,
                ":cid": cohort_id,
                ":run": run_date,
            }),
        )
    except Exception as exc:
        logger.warning(
            "Failed to update training status for %s: %s", pair_id, exc,
        )

    return {
        "status":               "trained_pending_evaluation",
        "pair_id":              pair_id,
        "cohort_id":            cohort_id,
        "propensity_model_arn": propensity_model_arn,
        "outcome_model_arns":   outcome_model_arns,
        "cate_estimator_arns":  cate_estimator_arns,
        "propensity_overlap":   overlap,
    }

def _simulate_training_job(algorithm: str, cohort_id: str, target: str,
                              family: str, run_date: str,
                              pair_id: str) -> str:
    """
    Stand-in for SageMaker Training Job submission. Production:
    `sagemaker_client.create_training_job(...)` with a BYOC
    container, then poll until the job completes, then register
    the resulting model in the SageMaker Model Registry.
    """
    job_name = f"{family}-{pair_id}-{run_date}"
    pseudo_arn = (
        f"arn:aws:sagemaker:us-east-1:000000000000:model/{job_name}"
    )
    logger.info(
        "Simulated training: algorithm=%s job=%s target=%s",
        algorithm, job_name, target,
    )
    return pseudo_arn

def _assess_propensity_overlap(propensity_model_arn: str,
                                  cohort_metadata: dict) -> dict:
    """
    Compute a propensity-overlap diagnostic for the cohort.

    Production: predict propensity scores for every cohort member,
    inspect the distributions in the treated and comparator arms,
    and flag severe overlap failure when the proportion of patients
    with propensity in the tails (< 0.05 or > 0.95) exceeds a
    pre-set threshold (often 5%-10%, depending on cohort size).

    The example computes a stub that uses the cohort sizes as a
    proxy: very imbalanced cohorts get worse overlap scores. Real
    propensity overlap is a much richer diagnostic.
    """
    treated   = cohort_metadata["size_treated"]
    comparator = cohort_metadata["size_comparator"]
    total = treated + comparator
    if total == 0:
        return {"severe": True, "imbalance": 1.0,
                 "tail_fraction_estimate": 1.0}
    imbalance = abs(treated - comparator) / total

    # Synthetic tail-fraction estimate. Production: actual percentiles
    # of the predicted propensity distribution.
    tail_fraction = 0.05 + 0.40 * imbalance
    return {
        "severe":               tail_fraction > 0.20,
        "imbalance":            round(imbalance, 4),
        "tail_fraction_estimate": round(tail_fraction, 4),
        "treated_size":         treated,
        "comparator_size":      comparator,
    }
```

---

## Step 3: Run Calibration and Fairness Tests, and Gate Promotion Through Governance

*The pseudocode calls this `evaluate_and_gate_pair_models(treatment_pair_id, run_date)`. A trained model is not a production model. Calibration tests check that predicted treatment effects match observed effects in held-out cohorts. Fairness tests check that calibration is consistent across protected subpopulations. Estimator agreement is the structural-uncertainty signal. Sensitivity analysis bounds how much unmeasured confounding could change the conclusion. The governance gate is a human review of the test results before the new model artifacts are promoted to production.*

```python
def evaluate_and_gate_pair_models(pair_id: str, run_date: str) -> dict:
    """
    Run calibration, cohort-stratified fairness, estimator-agreement,
    and sensitivity analyses for a single pair. Persist the
    evaluation report and create a governance-review-task for human
    review before promotion.

    Returns the evaluation report plus the review task id.
    """
    pairs_table = dynamodb.Table(TREATMENT_COMPARISON_PAIRS_TABLE)
    pair = _from_decimal(pairs_table.get_item(
        Key={"pair_id": pair_id}
    ).get("Item") or {})
    if not pair:
        logger.warning("Pair %s not found in registry", pair_id)
        return {}

    # ---- Stage A: held-out calibration ----
    # Production: use the held-out test split of the training cohort
    # (typically temporal: train on older cohort, test on newer).
    # Predict treatment effects on the test set and compare against
    # observed effects within covariate-defined subgroups.
    calibration_results = {}
    for estimator_name in CATE_ESTIMATOR_NAMES:
        calibration_results[estimator_name] = _compute_calibration(
            estimator_name, pair, run_date,
        )

    # ---- Stage B: cohort-stratified fairness ----
    # Repeat the calibration within each protected cohort. Calibration
    # parity across cohorts is the bar.
    fairness_results = {}
    for axis in pair.get("fairness_axes", []):
        for cohort_value in _DEMO_COHORT_VALUES.get(axis, []):
            sample_size = _DEMO_FAIRNESS_SAMPLE_SIZE.get(
                (pair_id, axis, cohort_value), 0,
            )
            if sample_size < MIN_FAIRNESS_SAMPLE_SIZE:
                fairness_results[(axis, cohort_value)] = {
                    "status":      "insufficient_sample",
                    "sample_size": sample_size,
                }
                continue
            fairness_results[(axis, cohort_value)] = _compute_calibration_subset(
                pair_id, axis, cohort_value, sample_size,
            )

    # ---- Stage C: estimator agreement ----
    # Per-patient correlation of CATE estimates across the ensemble.
    # Disagreement is a structural-uncertainty signal.
    agreement = _compute_estimator_agreement(pair_id)

    # ---- Stage D: sensitivity analysis ----
    # Pre-compute E-value and ci-widening multiplier per pair.
    # Production runs VanderWeele-Ding E-value computation and
    # Rosenbaum bounds on the actual cohort.
    sensitivity = SAMPLE_SENSITIVITY_BOUNDS.get(pair_id, {
        "e_value": 1.20,
        "ci_widen_multiplier": 1.30,
    })

    # ---- Stage E: classify overall ----
    overall_status = _classify_overall_evaluation(
        calibration_results, fairness_results, agreement, sensitivity,
    )

    eval_report = {
        "pair_id":            pair_id,
        "run_date":           run_date,
        "calibration_results": calibration_results,
        "fairness_results":    {f"{k[0]}={k[1]}": v
                                  for k, v in fairness_results.items()},
        "agreement_results":   agreement,
        "sensitivity_results": sensitivity,
        "evaluation_status":   overall_status,
    }

    # Persist the evaluation report.
    eval_path = (
        f"s3://{TRX_EVAL_BUCKET}/pair={pair_id}/run={run_date}/report.json"
    )
    try:
        s3_client.put_object(
            Bucket=TRX_EVAL_BUCKET,
            Key=f"pair={pair_id}/run={run_date}/report.json",
            Body=json.dumps(eval_report, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to persist eval report for %s: %s", pair_id, exc,
        )

    # ---- Stage F: governance gate ----
    # The system creates a review task; the cross-functional
    # committee (medical director, clinical informatics, equity
    # lead, data science lead) decides whether to promote.
    task_id = f"review-{uuid.uuid4().hex[:16]}"
    review_tasks_table = dynamodb.Table(GOVERNANCE_REVIEW_TASKS_TABLE)
    try:
        review_tasks_table.put_item(Item=_to_decimal_dict({
            "task_id":              task_id,
            "pair_id":              pair_id,
            "run_date":             run_date,
            "evaluation_report_path": eval_path,
            "evaluation_status":    overall_status,
            "status":               "pending_review",
            "created_at":           run_date,
        }))
    except Exception as exc:
        logger.warning(
            "Failed to persist governance review task: %s", exc,
        )

    try:
        kinesis_client.put_record(
            StreamName=TRX_EVENTS_STREAM_NAME,
            PartitionKey=pair_id,
            Data=json.dumps({
                "event_type":        "governance_review_pending",
                "pair_id":           pair_id,
                "task_id":           task_id,
                "evaluation_status": overall_status,
                "timestamp":         _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to publish governance_review_pending: %s", exc,
        )

    return {
        "report":  eval_report,
        "task_id": task_id,
    }

def process_governance_decision(task_id: str, human_decision: dict) -> None:
    """
    Process a committee-reviewed governance decision. On approval,
    promote the new model artifacts to production aliases in the
    Model Registry and update production_pair_endpoints in the
    pairs table. On rejection, mark training as evaluation_failed.

    human_decision is one of:
      { "decision": "approve", "reviewer_ids": [...], "notes": "..." }
      { "decision": "reject", "reviewer_ids": [...],
        "rejection_reason": "..." }
    """
    review_tasks_table = dynamodb.Table(GOVERNANCE_REVIEW_TASKS_TABLE)
    pairs_table = dynamodb.Table(TREATMENT_COMPARISON_PAIRS_TABLE)

    task = _from_decimal(review_tasks_table.get_item(
        Key={"task_id": task_id}
    ).get("Item") or {})
    if not task:
        logger.warning("Governance review task %s not found", task_id)
        return

    pair_id = task["pair_id"]

    if human_decision.get("decision") == "approve":
        # Promote: in production, alias the new model artifacts to
        # production endpoints, update production_pair_endpoints in
        # the pairs table, archive the prior production artifacts
        # for rollback.
        try:
            pairs_table.update_item(
                Key={"pair_id": pair_id},
                UpdateExpression=(
                    "SET training_status = :st, "
                    "is_production = :prod, "
                    "production_calibration_status = :pcs, "
                    "promoted_at = :pa"
                ),
                ExpressionAttributeValues=_to_decimal_dict({
                    ":st":  "production",
                    ":prod": True,
                    ":pcs": f"production_calibrated_{task['run_date']}",
                    ":pa":  _now_iso(),
                }),
            )
        except Exception as exc:
            logger.warning(
                "Failed to promote pair %s: %s", pair_id, exc,
            )

        try:
            kinesis_client.put_record(
                StreamName=TRX_EVENTS_STREAM_NAME,
                PartitionKey=pair_id,
                Data=json.dumps({
                    "event_type": "model_promoted",
                    "pair_id":    pair_id,
                    "task_id":    task_id,
                    "promoted_by": human_decision.get("reviewer_ids", []),
                    "timestamp":  _now_iso(),
                }, default=str).encode("utf-8"),
            )
        except Exception:
            pass

    else:
        try:
            pairs_table.update_item(
                Key={"pair_id": pair_id},
                UpdateExpression="SET training_status = :st",
                ExpressionAttributeValues={
                    ":st": "evaluation_failed",
                },
            )
        except Exception:
            pass

    try:
        review_tasks_table.update_item(
            Key={"task_id": task_id},
            UpdateExpression=(
                "SET #s = :resolved, human_decision = :hd, "
                "resolved_at = :ra"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=_to_decimal_dict({
                ":resolved": "resolved",
                ":hd":       human_decision,
                ":ra":       _now_iso(),
            }),
        )
    except Exception:
        pass

def _compute_calibration(estimator_name: str, pair: dict,
                            run_date: str) -> dict:
    """
    Compute calibration on the held-out test set for a single
    estimator. Production: bin patients by predicted treatment
    effect, compare predicted-vs-observed mean within each bin,
    fit a calibration slope and intercept. Demo: synthetic.
    """
    base = _DEMO_CALIBRATION_BY_ESTIMATOR.get(estimator_name, {
        "calibration_slope":     0.92,
        "calibration_intercept": 0.05,
        "n_test_patients":       300,
    })
    slope = base["calibration_slope"]
    return {
        **base,
        "calibration_warning": slope < CALIBRATION_SLOPE_LOW
                                or slope > CALIBRATION_SLOPE_HIGH,
    }

def _compute_calibration_subset(pair_id: str, axis: str,
                                  cohort_value: str,
                                  sample_size: int) -> dict:
    """
    Compute calibration within a single protected cohort. Production:
    same calibration computation as above, restricted to the cohort
    subset. Demo: synthetic.
    """
    key = (pair_id, axis, cohort_value)
    base = _DEMO_COHORT_CALIBRATION.get(key, {
        "calibration_slope":     0.88,
        "calibration_intercept": 0.04,
    })
    return {
        **base,
        "sample_size":         sample_size,
        "cohort_axis":         axis,
        "cohort_value":        cohort_value,
        "calibration_warning": base["calibration_slope"] < CALIBRATION_SLOPE_LOW
                                or base["calibration_slope"] > CALIBRATION_SLOPE_HIGH,
    }

def _compute_estimator_agreement(pair_id: str) -> dict:
    """
    Per-patient agreement among ensemble members. Production:
    correlate per-patient point estimates from each estimator,
    flag the percent of patients with inter-estimator spread above
    DISAGREEMENT_THRESHOLD. Demo: synthetic.
    """
    return _DEMO_ESTIMATOR_AGREEMENT.get(pair_id, {
        "mean_pairwise_correlation":    0.78,
        "percent_high_disagreement":    0.14,
        "agreement_score_summary":      "moderate",
    })

def _classify_overall_evaluation(calibration_results: dict,
                                    fairness_results: dict,
                                    agreement: dict,
                                    sensitivity: dict) -> str:
    """
    Classify the evaluation report as green (clear pass), yellow
    (warnings, governance review required), or red (clear fail,
    suspend). Production: explicit policy with thresholds reviewed
    by the committee; the demo uses a coarse heuristic.
    """
    cal_warnings = sum(
        1 for r in calibration_results.values()
        if isinstance(r, dict) and r.get("calibration_warning")
    )
    fairness_warnings = sum(
        1 for r in fairness_results.values()
        if isinstance(r, dict) and r.get("calibration_warning")
    )
    if cal_warnings == 0 and fairness_warnings == 0:
        if agreement.get("percent_high_disagreement", 1.0) <= 0.10:
            return "green"
        return "yellow"
    if cal_warnings >= 2 or fairness_warnings >= 2:
        return "red"
    return "yellow"

# Demo state populated by the runner.
_DEMO_COHORT_VALUES: dict = {}
_DEMO_FAIRNESS_SAMPLE_SIZE: dict = {}
_DEMO_CALIBRATION_BY_ESTIMATOR: dict = {}
_DEMO_COHORT_CALIBRATION: dict = {}
_DEMO_ESTIMATOR_AGREEMENT: dict = {}
```

> **Curious how this looks alongside the prose?** This Python companion implements the pseudocode walkthrough in [Recipe 4.8](chapter04.08-treatment-response-prediction). The recipe explains the architecture, the methodological discipline, and the honest take on where this gets hard.

---

## Step 4: Score an Index Patient on Demand at the Point of Care

*The pseudocode calls this `score_patient(patient_id, request_context)`. When the clinician opens the patient's chart and requests treatment guidance, the system identifies eligible treatment-comparator pairs from the catalog, invokes each pair's CATE ensemble, retrieves the similar-patient cohort underlying the estimate, computes uncertainty across all sources, and flags out-of-distribution cases. Skip the OOD flag and the system silently extrapolates predictions to patients who are not represented in the training data, which is exactly the case where the prediction is least reliable.*

```python
def score_patient(patient_id: str, request_context: dict,
                    patients: dict, pair_catalog: list,
                    treatment_catalog: list) -> dict:
    """
    Run on-demand scoring for an index patient.

    Steps:
      A. Identify eligible treatment-comparator pairs from the catalog.
      B. For each eligible pair, invoke the CATE ensemble, retrieve
         the similar-patient cohort summary, compute uncertainty,
         and flag OOD.
      C. Apply sensitivity-analysis bounds to widen reported CIs.
      D. Persist scoring result; emit scoring event.

    Returns the structured scoring result for downstream briefing
    generation.
    """
    patient_features = _featurestore_get_patient(patient_id, patients)
    if not patient_features:
        logger.warning("No features for patient %s", patient_id)
        return {}

    # Step 4A: identify eligible pairs.
    eligible_pairs = []
    for pair in pair_catalog:
        if not pair.get("is_production"):
            continue
        if not _meets_pair_eligibility(patient_features, pair, request_context):
            continue
        if _has_contraindication(patient_features, pair):
            continue
        eligible_pairs.append(pair)

    scoring_run_id = _make_scoring_run_id(patient_id, _today_str())

    if not eligible_pairs:
        # No eligible pairs. Return a structured response that tells
        # the clinician we have nothing to add for this patient. Do
        # not silently produce a low-confidence estimate.
        result = {
            "patient_id":     patient_id,
            "scoring_run_id": scoring_run_id,
            "scoring_status": "no_eligible_pairs",
            "scoring_reason": "no_pairs_match_index_condition_and_eligibility",
            "request_context": request_context,
            "scoring_completed_at": _now_iso(),
        }
        _persist_scoring_result(result)
        return result

    # Step 4B: per-pair scoring.
    pair_results = []
    for pair in eligible_pairs:
        # Run each estimator. Real-time endpoints return per-estimator
        # point estimate and confidence interval.
        estimator_outputs = {}
        for estimator_name in CATE_ESTIMATOR_NAMES:
            endpoint = pair["production_pair_endpoints"].get(estimator_name)
            estimator_outputs[estimator_name] = _invoke_cate_endpoint(
                endpoint, patient_features, pair["pair_id"],
            )

        # Step 4C: ensemble uncertainty.
        ensemble = _combine_ensemble_estimates(estimator_outputs)

        # Step 4D: similar-patient cohort retrieval (summary only;
        # full cohort would be PHI-leaking).
        cohort_summary = _retrieve_similar_patient_summary(
            patient_features, pair["pair_id"],
        )

        # Step 4E: out-of-distribution flag.
        ood_flag = _compute_ood_flag(
            patient_features, pair["pair_id"], cohort_summary,
        )

        # Step 4F: apply sensitivity-analysis bounds.
        adjusted = _apply_sensitivity_bounds(ensemble, pair["pair_id"])

        # If OOD severity is above the suppress threshold, mark
        # this pair's result as suppressed; the briefing layer will
        # explicitly tell the clinician we have no reliable estimate.
        if ood_flag["severity"] >= OOD_SEVERITY_SUPPRESS_THRESHOLD:
            pair_result = {
                "treatment_pair_id":   pair["pair_id"],
                "treatment_id":        pair["treatment_id"],
                "comparator_id":       pair["comparator_id"],
                "outcome_id":          pair["primary_outcome_id"],
                "scoring_status":      "suppressed_oodflag",
                "ood_flag":            ood_flag,
                "evidence_level":      pair["evidence_level"],
                "formulary_status":    _lookup_treatment(
                    pair["treatment_id"], treatment_catalog,
                ).get("formulary_status"),
            }
        else:
            pair_result = {
                "treatment_pair_id":     pair["pair_id"],
                "treatment_id":          pair["treatment_id"],
                "comparator_id":         pair["comparator_id"],
                "outcome_id":            pair["primary_outcome_id"],
                "point_estimate":        round(adjusted["point_estimate"], 4),
                "ci_low":                round(adjusted["ci_low"], 4),
                "ci_high":               round(adjusted["ci_high"], 4),
                "estimator_agreement":   round(
                    ensemble["estimator_agreement_score"], 4),
                "disagreement_flag":     ensemble["disagreement_flag"],
                "cohort_summary":        cohort_summary,
                "ood_flag":              ood_flag,
                "evidence_level":        pair["evidence_level"],
                "formulary_status":      _lookup_treatment(
                    pair["treatment_id"], treatment_catalog,
                ).get("formulary_status"),
                "guideline_references":  pair.get("guideline_references", []),
                "calibration_status":    pair.get(
                    "production_calibration_status"),
            }
        pair_results.append(pair_result)

        # Cohort-sliced metric for the equity dashboard.
        cohort_features = _cohort_features_from_profile(
            patients.get(patient_id, {}))
        _emit_metric(
            "treatment_scoring_completed", value=1,
            dimensions={
                "pair_id":     pair["pair_id"],
                "ood_severity_band": _severity_band(ood_flag["severity"]),
                "language":    cohort_features.get("language", "unknown"),
                "sdoh_cohort": cohort_features.get("sdoh_cohort", "unknown"),
            },
        )

    # Step 4G: persist scoring result.
    result = {
        "patient_id":          patient_id,
        "scoring_run_id":      scoring_run_id,
        "request_context":     request_context,
        "index_condition":     request_context.get("index_condition"),
        "eligible_pair_ids":   [p["pair_id"] for p in eligible_pairs],
        "pair_results":        pair_results,
        "scoring_status":      "completed",
        "scoring_completed_at": _now_iso(),
    }
    _persist_scoring_result(result)

    try:
        kinesis_client.put_record(
            StreamName=TRX_EVENTS_STREAM_NAME,
            PartitionKey=patient_id,
            Data=json.dumps({
                "event_type":         "treatment_scoring_completed",
                "patient_id":         patient_id,
                "scoring_run_id":     scoring_run_id,
                "eligible_pair_count": len(eligible_pairs),
                "any_oodflag":        any(
                    p.get("ood_flag", {}).get("severity", 0)
                      >= OOD_SEVERITY_WARNING_THRESHOLD
                    for p in pair_results),
                "any_disagreement":   any(
                    p.get("disagreement_flag", False) for p in pair_results),
                "timestamp":          _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to publish treatment_scoring_completed event: %s", exc,
        )

    return result

def _featurestore_get_patient(patient_id: str, patients: dict) -> dict:
    """
    Production: SageMaker Feature Store online-store GetRecord call
    for the patient. Demo: read from the synthetic patients dict.
    """
    return patients.get(patient_id, {})

def _meets_pair_eligibility(patient_features: dict, pair: dict,
                              request_context: dict) -> bool:
    """
    Determine whether the patient meets the pair's eligibility
    predicates. Production: encode the protocol's eligibility logic;
    the demo applies a coarse condition match.
    """
    if request_context.get("index_condition") != pair["indication"]:
        return False
    # Demo: T2D inadequately controlled on metformin.
    if pair["indication"].startswith("type_2_diabetes"):
        if "type_2_diabetes" not in patient_features.get(
            "active_conditions", []):
            return False
        if "metformin" not in patient_features.get("current_medications", []):
            return False
        a1c = patient_features.get("recent_lab_trends", {}).get("a1c_recent")
        if a1c is None or a1c < 7.0 or a1c > 12.0:
            return False
    return True

def _has_contraindication(patient_features: dict, pair: dict) -> bool:
    """
    Demo contraindication check. Production: a richer rules engine
    plus integration with the EHR's medication-allergy and
    drug-interaction services.
    """
    contras = patient_features.get("contraindications", [])
    if pair["treatment_id"] == "glp1_receptor_agonist_class":
        if "history_of_pancreatitis" in contras:
            return True
        if "medullary_thyroid_carcinoma_personal_or_family" in contras:
            return True
    if pair["treatment_id"] == "sglt2_inhibitor_class":
        if "egfr_below_30" in contras:
            return True
        if "active_diabetic_ketoacidosis_history" in contras:
            return True
    return False

def _invoke_cate_endpoint(endpoint: str, patient_features: dict,
                            pair_id: str) -> dict:
    """
    Production: SageMaker Real-Time Inference InvokeEndpoint with
    the patient feature vector serialized for the model. Returns
    point estimate and confidence interval.

    The example uses a rule-based proxy that returns a synthetic
    estimate keyed off the patient's a1c, weight, and pair id.
    """
    a1c = patient_features.get("recent_lab_trends", {}).get(
        "a1c_recent", 8.0)
    bmi = patient_features.get("bmi", 30)

    # Synthetic CATE estimates roughly modeled on T2D second-line
    # therapy literature. Real estimates come from the trained
    # CATE model.
    if pair_id == "t2d-glp1-vs-sglt2":
        # GLP-1 advantage on A1c reduction at 90 days, more pronounced
        # at higher baseline A1c and BMI.
        point = -0.50 - 0.10 * max(0, a1c - 8.0) - 0.005 * max(0, bmi - 28)
        ci_half = 0.30
    elif pair_id == "t2d-glp1-vs-sulfonylurea":
        point = -0.30 - 0.05 * max(0, a1c - 8.0)
        ci_half = 0.35
    elif pair_id == "t2d-sglt2-vs-sulfonylurea":
        point = 0.10 - 0.03 * max(0, a1c - 8.0)
        ci_half = 0.30
    else:
        point = 0.0
        ci_half = 0.50

    # Inject a small amount of estimator-specific variation so the
    # ensemble has nonzero spread.
    variation = (hash(endpoint) % 100) / 1000 - 0.05
    point = point + variation
    return {
        "point_estimate":  point,
        "ci_low":          point - ci_half,
        "ci_high":         point + ci_half,
    }

def _combine_ensemble_estimates(estimator_outputs: dict) -> dict:
    """
    Combine per-estimator estimates into ensemble uncertainty. The
    ensemble point estimate is the mean across estimators; the
    ensemble CI is the union of estimator CIs (the most conservative
    representation of combined sampling and model uncertainty).
    Disagreement is the spread of point estimates normalized to
    the median CI width.
    """
    points = [o["point_estimate"] for o in estimator_outputs.values()]
    ci_lows = [o["ci_low"] for o in estimator_outputs.values()]
    ci_highs = [o["ci_high"] for o in estimator_outputs.values()]

    mean_point = sum(points) / len(points)
    union_low  = min(ci_lows)
    union_high = max(ci_highs)
    spread     = max(points) - min(points)
    median_width = sorted([h - l for h, l in zip(ci_highs, ci_lows)])[
        len(points) // 2]
    if median_width <= 0:
        median_width = 1e-6
    normalized_spread = spread / median_width
    agreement_score   = max(0.0, 1.0 - normalized_spread)

    return {
        "point_estimate":             mean_point,
        "ci_low":                     union_low,
        "ci_high":                    union_high,
        "estimator_agreement_score":  agreement_score,
        "disagreement_flag":          normalized_spread > DISAGREEMENT_THRESHOLD,
    }

def _retrieve_similar_patient_summary(patient_features: dict,
                                          pair_id: str) -> dict:
    """
    Retrieve the similar-patient cohort summary underlying the
    estimate. Production: query the cohort index using the patient
    embedding (or a hand-engineered similarity metric) to return
    summary statistics over the K nearest training-cohort patients.
    Full-cohort retrieval would be PHI-leaking; only summaries leave
    the cohort store.

    The example returns a synthetic summary keyed off the pair id.
    """
    base = _DEMO_COHORT_SUMMARIES.get(pair_id, {})
    if not base:
        return {
            "total_size":              0,
            "cohort_match_quality":    "no_data",
        }
    return {
        **base,
        "training_data_recency":  base.get(
            "training_data_recency", "2023-01-01_to_2025-12-31"),
    }

def _compute_ood_flag(patient_features: dict, pair_id: str,
                        cohort_summary: dict) -> dict:
    """
    Compute the out-of-distribution severity for this patient on
    this pair. Production: combine propensity-tail flag, embedding-
    distance from training distribution, and per-feature density
    estimates.

    Demo: severity rises if cohort match quality is poor or if the
    patient's a1c is outside the typical trained range.
    """
    a1c = patient_features.get("recent_lab_trends", {}).get(
        "a1c_recent", 8.0)
    cohort_size = cohort_summary.get("total_size", 0)
    match_score = cohort_summary.get("demographic_match_score", 0.0)

    severity = 0.0
    reasons = []
    if cohort_size < MIN_SIMILAR_PATIENT_COHORT:
        severity = max(severity, 0.85)
        reasons.append("similar_patient_cohort_too_small")
    if match_score < 0.5:
        severity = max(severity, 0.70)
        reasons.append("low_demographic_match")
    if a1c < 7.0 or a1c > 11.0:
        severity = max(severity, 0.40)
        reasons.append("a1c_outside_training_range")
    return {
        "is_ood":   severity >= OOD_SEVERITY_WARNING_THRESHOLD,
        "severity": round(severity, 3),
        "reasons":  reasons,
    }

def _apply_sensitivity_bounds(ensemble: dict, pair_id: str) -> dict:
    """
    Apply pre-computed sensitivity-analysis bounds to widen the
    reported CI. The widening accounts for unmeasured-confounding
    structural uncertainty that the model's statistical CI doesn't
    capture.
    """
    sensitivity = SAMPLE_SENSITIVITY_BOUNDS.get(pair_id, {
        "ci_widen_multiplier": 1.30,
    })
    multiplier = sensitivity["ci_widen_multiplier"]
    point = ensemble["point_estimate"]
    half = (ensemble["ci_high"] - ensemble["ci_low"]) / 2
    widened = half * multiplier
    return {
        "point_estimate": point,
        "ci_low":         point - widened,
        "ci_high":        point + widened,
    }

def _persist_scoring_result(result: dict) -> None:
    """Persist the scoring result to DynamoDB for the briefing layer."""
    table = dynamodb.Table(SCORING_RESULTS_TABLE)
    try:
        table.put_item(Item=_to_decimal_dict(result))
    except Exception as exc:
        logger.warning(
            "Failed to persist scoring result %s: %s",
            result.get("scoring_run_id"), exc,
        )

def _severity_band(severity: float) -> str:
    """Coarse OOD severity band for metric dimensions."""
    if severity >= OOD_SEVERITY_SUPPRESS_THRESHOLD:
        return "suppress"
    if severity >= OOD_SEVERITY_WARNING_THRESHOLD:
        return "warn"
    return "normal"

# Demo state populated by the runner.
_DEMO_COHORT_SUMMARIES: dict = {}
```

---

## Step 5: Generate the Clinician-Facing Comparison Briefing With Strict Validator Enforcement

*The pseudocode calls this `generate_briefing(scoring_run_id)`. The structured scoring result is rendered into a paragraph the clinician reads at the point of care. The LLM packages the comparison; the validator enforces strict no-recommendation language, explicit uncertainty, and required caveats. Skip the validator and an LLM that has been trained on the broader internet may quietly insert recommendation language ("the evidence supports prescribing X") that the clinician interprets as the system selecting a treatment.*

```python
def generate_briefing(scoring_run_id: str, patients: dict,
                        treatment_catalog: list) -> dict:
    """
    Generate the clinician-facing comparison briefing for a
    scoring run, with strict validator enforcement and templated
    fallback.

    Returns the briefing dict that was persisted.
    """
    scoring_table = dynamodb.Table(SCORING_RESULTS_TABLE)
    scoring = _from_decimal(scoring_table.get_item(
        Key={"patient_id": _scoring_run_patient(scoring_run_id),
              "scoring_run_id": scoring_run_id}
    ).get("Item") or {})

    if not scoring:
        # In production, the scoring-results table is keyed on the
        # composite (patient_id, scoring_run_id). Demo: scan as a
        # fallback so the runner doesn't need to know the patient.
        scoring = _scan_scoring_result(scoring_run_id)

    if not scoring:
        logger.warning("Scoring result %s not found", scoring_run_id)
        return {}

    if scoring.get("scoring_status") == "no_eligible_pairs":
        # No eligible pairs: return a templated "no recommendation"
        # briefing rather than invoking the LLM. The clinician sees
        # an explicit message rather than a confusing empty paragraph.
        briefing_parsed = _no_eligible_briefing(scoring)
        validator_status = True
    else:
        briefing_context = _build_briefing_context(
            scoring, patients, treatment_catalog,
        )

        # Generate via Bedrock with regeneration loop and templated
        # fallback.
        briefing_parsed = None
        validator_status = False

        for attempt in range(MAX_REGENERATION_ATTEMPTS):
            try:
                briefing_parsed = _bedrock_comparison_briefing(
                    briefing_context, strict_mode=(attempt > 0),
                )
            except Exception as exc:
                logger.warning(
                    "Bedrock briefing attempt %d failed: %s", attempt, exc,
                )
                continue

            validation_result = _validate_briefing(
                briefing_parsed, briefing_context,
            )
            if validation_result["passed"]:
                validator_status = True
                break
            else:
                # Provide validator feedback to the next attempt so
                # the LLM has the opportunity to correct the issues.
                briefing_context["validator_feedback"] = (
                    validation_result["feedback"]
                )

        if not validator_status:
            briefing_parsed = _templated_briefing_fallback(briefing_context)
            briefing_parsed["fallback_reason"] = (
                "validator_repeatedly_failed_or_llm_unavailable"
            )
            try:
                kinesis_client.put_record(
                    StreamName=TRX_EVENTS_STREAM_NAME,
                    PartitionKey=scoring["patient_id"],
                    Data=json.dumps({
                        "event_type":     "briefing_validator_fallback",
                        "scoring_run_id": scoring_run_id,
                        "reason":         "validator_repeatedly_failed",
                        "timestamp":      _now_iso(),
                    }, default=str).encode("utf-8"),
                )
            except Exception:
                pass

    briefing_id = _make_briefing_id()
    briefing_record = {
        "briefing_id":      briefing_id,
        "scoring_run_id":   scoring_run_id,
        "patient_id":       scoring["patient_id"],
        "briefing_text":    briefing_parsed,
        "validator_status": validator_status,
        "generated_at":     _now_iso(),
        "ttl_expires_at":   (datetime.datetime.now(timezone.utc)
                              + timedelta(hours=BRIEFING_TTL_HOURS)).isoformat(),
    }

    briefings_table = dynamodb.Table(BRIEFINGS_TABLE)
    try:
        briefings_table.put_item(Item=_to_decimal_dict(briefing_record))
    except Exception as exc:
        logger.warning(
            "Failed to persist briefing %s: %s", briefing_id, exc,
        )

    try:
        kinesis_client.put_record(
            StreamName=TRX_EVENTS_STREAM_NAME,
            PartitionKey=scoring["patient_id"],
            Data=json.dumps({
                "event_type":     "briefing_generated",
                "patient_id":     scoring["patient_id"],
                "scoring_run_id": scoring_run_id,
                "briefing_id":    briefing_id,
                "validator_status": validator_status,
                "timestamp":      _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return briefing_record

def _build_briefing_context(scoring: dict, patients: dict,
                              treatment_catalog: list) -> dict:
    """
    Build the structured briefing context. The LLM consumes a
    de-identified version of this; identifiers stay on the
    persistence side.
    """
    patient = patients.get(scoring["patient_id"], {})
    return {
        "patient_summary":    _summarize_patient_for_briefing(patient),
        "index_condition":    scoring.get("index_condition"),
        "pair_results":       scoring.get("pair_results", []),
        "treatments":         [
            _lookup_treatment(p["treatment_id"], treatment_catalog)
            for p in scoring.get("pair_results", [])
        ],
        "any_oodflag":        any(
            p.get("ood_flag", {}).get("severity", 0)
              >= OOD_SEVERITY_WARNING_THRESHOLD
            for p in scoring.get("pair_results", [])),
        "any_disagreement":   any(
            p.get("disagreement_flag", False)
            for p in scoring.get("pair_results", [])),
        "request_context":    scoring.get("request_context", {}),
    }

def _summarize_patient_for_briefing(patient: dict) -> dict:
    """
    Compact patient summary at the level appropriate for clinical
    decision support. Avoids surfacing exact lab values that risk
    being copied into hallucinated text.
    """
    lab_trends = patient.get("recent_lab_trends", {})
    return {
        "age_band":             patient.get("age_band"),
        "active_conditions":    patient.get("active_conditions", []),
        "recent_lab_summary":   {
            "egfr_band":  _egfr_band(lab_trends.get("egfr_recent")),
            "egfr_trend": ("falling"
                            if lab_trends.get("egfr_change_24mo", 0) <= -10
                            else "stable"),
            "a1c_band":   _a1c_band(lab_trends.get("a1c_recent")),
            "albuminuria": ("present"
                              if lab_trends.get("uacr_recent", 0) >= 30
                              else "absent_or_mild"),
        },
        "bmi_band":             _bmi_band(patient.get("bmi")),
        "calcium_score_band":   _calcium_band(
            patient.get("coronary_calcium_score")),
        "current_medications":  patient.get("current_medications", []),
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
    if a1c < 9.0:
        return "elevated"
    return "very_elevated"

def _egfr_band(egfr) -> str:
    if egfr is None:
        return "unknown"
    if egfr >= 90:
        return "normal"
    if egfr >= 60:
        return "mild_decrease"
    if egfr >= 45:
        return "mild_to_moderate"
    if egfr >= 30:
        return "moderate"
    return "severe"

def _bmi_band(bmi) -> str:
    if bmi is None:
        return "unknown"
    if bmi < 25:
        return "normal_or_underweight"
    if bmi < 30:
        return "overweight"
    if bmi < 35:
        return "obesity_class_1"
    if bmi < 40:
        return "obesity_class_2"
    return "obesity_class_3"

def _calcium_band(score) -> str:
    if score is None:
        return "not_measured"
    if score == 0:
        return "zero"
    if score < 100:
        return "minimal"
    if score < 400:
        return "moderate"
    return "high"

def _bedrock_comparison_briefing(context: dict,
                                    strict_mode: bool = False) -> dict:
    """
    Generate a structured clinician-facing comparison briefing via
    Bedrock. The prompt enforces no-recommendation language, explicit
    uncertainty, and required caveats; the validator catches any
    output that slips through.
    """
    de_id = _redact_identifiers([context])[0]

    strictness_addendum = (
        "\n\nSTRICT MODE: A previous attempt failed validation. The "
        "validator caught language that crossed into recommendation. "
        "Be even more careful: describe the comparison without "
        "selecting a treatment. Use phrases like 'the model estimates' "
        "and 'in this cohort' rather than 'we recommend' or 'the "
        "evidence supports'."
        if strict_mode else ""
    )

    prompt = f"""You generate clinician-facing comparison briefings for
a treatment response prediction system. Your role is to package the
deterministic CATE estimates and the patient context into a brief
the clinician reads in about 30 seconds at the point of care. You
do NOT recommend a treatment. You do NOT select a best option. You
describe the comparison, the magnitude, the uncertainty, and the
caveats. The clinician is the decision-maker.

Hard rules:
1. No recommendation language. Never write "should prescribe X",
   "the best choice is Y", "the recommended treatment is Z",
   "the evidence supports starting", or any equivalent.
2. Every magnitude estimate must be accompanied by its confidence
   interval and any flags (out-of-distribution, estimator
   disagreement) must be surfaced explicitly.
3. Required caveats: estimates are conditional-average effects from
   observational data, not individual guarantees; the clinician's
   judgment and patient preferences are essential and not in the model.
4. Reference only the data in the Context. Do not invent treatment
   effect estimates, cohort sizes, or outcome figures.{strictness_addendum}

Context (de-identified):
{json.dumps(de_id, indent=2)}

Return ONLY valid JSON (no prose, no code fences) with this shape:
{{
  "headline":                          "<10-15 words; comparison framing, no recommendation>",
  "comparison_paragraph":              "<3-5 sentence comparison; cite estimates with CIs>",
  "per_treatment_summary": {{
     "<treatment_id>": "<1-2 sentences per treatment; describe context not selection>"
  }},
  "uncertainty_summary":               "<1-2 sentences on uncertainty sources>",
  "caveats":                           ["<caveat>", "<caveat>", "<caveat>", "<caveat>"],
  "suggested_clinician_review_points": ["<point>", "<point>", "<point>"]
}}
"""
    response = bedrock_runtime.invoke_model(
        modelId=COMPARISON_BRIEFING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        1500,
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

def _validate_briefing(briefing: dict, observed_context: dict) -> dict:
    """
    Four-layer validator from the main recipe.

    1. Schema and length: required fields present; no oversize text.
    2. Recommendation language: pattern matching for recommendation
       phrasing. This is the strict layer.
    3. Uncertainty completeness: every estimate mentioned must be
       accompanied by its confidence interval reference, and any
       OOD or disagreement flags must be surfaced.
    4. Required caveats: explicit acknowledgment of observational-data
       limitations, conditional-average framing, and clinician-as-
       decision-maker.

    Returns a dict with `passed` (bool) and `feedback` (list of
    issues) for the regeneration loop.
    """
    issues = []

    # Layer 1: schema and length.
    required_keys = {
        "headline", "comparison_paragraph", "per_treatment_summary",
        "uncertainty_summary", "caveats",
        "suggested_clinician_review_points",
    }
    if not isinstance(briefing, dict):
        return {"passed": False, "feedback": ["briefing_not_dict"]}
    if not required_keys.issubset(briefing.keys()):
        missing = required_keys - set(briefing.keys())
        issues.append(f"missing_required_fields: {sorted(missing)}")

    for key in {"headline", "comparison_paragraph",
                  "uncertainty_summary"}:
        val = briefing.get(key, "")
        if not isinstance(val, str) or not val.strip():
            issues.append(f"empty_or_non_string: {key}")
        elif len(val) > 2000:
            issues.append(f"oversize_text: {key}")

    if not isinstance(briefing.get("caveats", []), list):
        issues.append("caveats_not_list")
    if not isinstance(briefing.get("suggested_clinician_review_points", []),
                       list):
        issues.append("review_points_not_list")
    if not isinstance(briefing.get("per_treatment_summary", {}), dict):
        issues.append("per_treatment_summary_not_dict")

    full_text = " ".join(
        v if isinstance(v, str)
        else " ".join(str(x) for x in v) if isinstance(v, list)
        else " ".join(str(x) for x in v.values()) if isinstance(v, dict)
        else str(v)
        for v in briefing.values()
    ).lower()

    # Layer 2: recommendation language.
    recommendation_patterns = [
        r"\bshould prescribe\b",
        r"\bshould be prescribed\b",
        r"\bshould start\b",
        r"\bbest choice\b",
        r"\bbest option\b",
        r"\brecommended treatment\b",
        r"\brecommend (?:starting|prescribing|that)\b",
        r"\bthe evidence supports (?:starting|prescribing)\b",
        r"\bclearly the (?:better|best)\b",
        r"\bsuperior choice\b",
        r"\bdefinitely (?:choose|prescribe)\b",
    ]
    for pattern in recommendation_patterns:
        if re.search(pattern, full_text):
            issues.append(f"recommendation_language_detected: {pattern}")

    # Layer 3: uncertainty completeness. Heuristic: if pair_results
    # contained OOD-flagged or disagreement-flagged entries, the
    # briefing should mention "out-of-distribution", "out of
    # distribution", "wide interval", "uncertainty", or
    # "disagreement" somewhere.
    if observed_context.get("any_oodflag"):
        if not any(term in full_text
                    for term in ["out-of-distribution", "out of distribution",
                                  "limited similar", "extrapolat",
                                  "few comparable"]):
            issues.append("oodflag_present_but_not_surfaced")
    if observed_context.get("any_disagreement"):
        if not any(term in full_text
                    for term in ["disagreement", "estimators disagree",
                                  "wide interval", "wide confidence"]):
            issues.append("disagreement_present_but_not_surfaced")

    # Layer 4: required caveats. The caveats list must include
    # at least one entry referencing observational data and one
    # referencing the clinician's role.
    caveats_text = " ".join(
        c.lower() if isinstance(c, str) else ""
        for c in briefing.get("caveats", [])
    )
    if not any(term in caveats_text
                for term in ["observational", "not randomized",
                              "real-world data"]):
        issues.append("missing_observational_caveat")
    if not any(term in caveats_text
                for term in ["clinician", "clinical judgment",
                              "shared decision", "patient prefer"]):
        issues.append("missing_clinician_judgment_caveat")

    return {
        "passed":   len(issues) == 0,
        "feedback": issues,
    }

def _templated_briefing_fallback(context: dict) -> dict:
    """
    Deterministic fallback briefing when LLM generation or the
    validator fails. Lists the structured comparison without LLM
    narration. Less readable but always passes validation; faithful
    to the data.
    """
    pair_summaries = {}
    headline_tx = []
    for pair in context.get("pair_results", []):
        if pair.get("scoring_status") == "suppressed_oodflag":
            pair_summaries[pair["treatment_pair_id"]] = (
                f"{pair['treatment_id']} vs {pair['comparator_id']}: "
                f"estimate suppressed (OOD severity "
                f"{pair['ood_flag']['severity']:.2f})."
            )
            continue
        pair_summaries[pair["treatment_pair_id"]] = (
            f"{pair['treatment_id']} vs {pair['comparator_id']}: "
            f"estimated {pair['outcome_id']} change "
            f"{pair['point_estimate']:+.2f} (CI {pair['ci_low']:+.2f} "
            f"to {pair['ci_high']:+.2f}); cohort size "
            f"{pair.get('cohort_summary', {}).get('total_size', 'unknown')}."
        )
        headline_tx.append(pair["treatment_id"])

    return {
        "headline": (
            "Structured comparison across "
            f"{len(headline_tx)} treatment(s); briefing fallback used. "
            "Refer to the values below."
        ),
        "comparison_paragraph": (
            "The model produced estimates for the eligible treatment-comparator "
            "pairs listed below. The narrative briefing was not generated "
            "(LLM unavailable or validator rejected output). Estimates are "
            "from observational data with target trial emulation and reflect "
            "conditional-average treatment effects within the matched cohort."
        ),
        "per_treatment_summary": pair_summaries,
        "uncertainty_summary": (
            "Confidence intervals reflect statistical uncertainty plus "
            "estimator agreement plus pre-computed sensitivity-analysis bounds."
        ),
        "caveats": [
            "Estimates are from observational data, not randomized trials.",
            "Estimates are conditional-average effects within the matched cohort, "
              "not individual guarantees.",
            "The clinician's judgment and patient preferences are essential "
              "and not captured in the model.",
            "Patient barriers (cost, injectable acceptance, supply) should "
              "drive shared decision-making.",
        ],
        "suggested_clinician_review_points": [
            "Review the patient's cardiovascular and renal indications.",
            "Confirm formulary status and current copay.",
            "Discuss patient preferences regarding modality and side effects.",
        ],
        "fallback_reason": "templated_briefing_used",
    }

def _no_eligible_briefing(scoring: dict) -> dict:
    """Templated 'no eligible pairs' briefing."""
    return {
        "headline": (
            "No eligible treatment-comparator pairs for this patient at "
            "this index condition."
        ),
        "comparison_paragraph": (
            "The treatment catalog has no production-ready pairs that "
            "match the patient's profile and the requested index condition."
        ),
        "per_treatment_summary":             {},
        "uncertainty_summary":               "no_estimates_to_present",
        "caveats": [
            "This is not a contraindication; it indicates the catalog "
              "does not currently support this decision.",
            "Standard clinical workflow continues. The clinician's "
              "judgment and the institutional formulary apply.",
        ],
        "suggested_clinician_review_points": [
            "Use standard clinical guidelines for this decision.",
            "Consider whether the patient's profile suggests a referral "
              "or specialist consultation.",
        ],
        "validator_status": True,
    }

def _scoring_run_patient(scoring_run_id: str) -> str:
    """Extract the patient_id from a scoring_run_id (demo-only helper)."""
    parts = scoring_run_id.split("-")
    # Format: score-{run_date}-{patient_id}-{suffix}
    if len(parts) >= 4:
        return "-".join(parts[2:-1])
    return ""

def _scan_scoring_result(scoring_run_id: str) -> dict:
    """Demo-only fallback: scan for a scoring_run_id."""
    table = dynamodb.Table(SCORING_RESULTS_TABLE)
    try:
        response = table.scan()
        for item in response.get("Items", []):
            item = _from_decimal(item)
            if item.get("scoring_run_id") == scoring_run_id:
                return item
    except Exception:
        pass
    return {}
```

---

## Step 6: Capture the Clinician's Decision and Match to Subsequent Outcome

*The pseudocode covers `record_decision`, `match_outcome`, and `run_calibration_drift_detection`. The decision record links the prediction at the time of decision to the actual treatment chosen and (later) the actual outcome. The matched prediction-outcome pair is the feedback that drives calibration drift detection, cohort-stratified performance monitoring, and retraining triggers. Skip this and you have a prediction system with no feedback loop, which is the single most common reason production ML systems quietly degrade over time.*

```python
def record_decision(scoring_run_id: str, decision_payload: dict,
                      patients: dict) -> dict:
    """
    Record a clinician's decision after reviewing the briefing.

    decision_payload includes:
      - clinician_id (from the authenticated session)
      - chosen_treatment_id (or 'none')
      - clinician_rationale (free-text or structured)
      - patient_consent_recorded (bool)
      - shared_decision_indicators (whether the patient summary
        was shared, whether patient preferences influenced the
        decision)

    Returns the persisted decision record.
    """
    scoring = _scan_scoring_result(scoring_run_id)
    if not scoring:
        logger.warning("No scoring result for run %s", scoring_run_id)
        return {}

    # Find the latest briefing for this scoring run.
    briefings_table = dynamodb.Table(BRIEFINGS_TABLE)
    briefing_id = None
    try:
        response = briefings_table.scan()
        candidates = []
        for item in response.get("Items", []):
            item = _from_decimal(item)
            if item.get("scoring_run_id") == scoring_run_id:
                candidates.append(item)
        candidates.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
        if candidates:
            briefing_id = candidates[0]["briefing_id"]
    except Exception as exc:
        logger.warning("Failed to look up briefing: %s", exc)

    decision_id = _make_decision_id()
    decision = {
        "decision_id":           decision_id,
        "scoring_run_id":        scoring_run_id,
        "patient_id":            scoring["patient_id"],
        "clinician_id":          decision_payload["clinician_id"],
        "chosen_treatment_id":   decision_payload.get(
            "chosen_treatment_id", "none"),
        "clinician_rationale":   decision_payload.get(
            "clinician_rationale", ""),
        "patient_consent":       decision_payload.get(
            "patient_consent_recorded", False),
        "shared_decision":       decision_payload.get(
            "shared_decision_indicators", {}),
        # Frozen-at-decision-time view of the predictions: what the
        # clinician saw when deciding. Critical for audit and for
        # after-the-fact analysis of predictions versus decisions.
        "predictions_at_decision": scoring.get("pair_results", []),
        "briefing_id_at_decision": briefing_id,
        "decision_recorded_at":    _now_iso(),
    }

    # Determine whether the decision agrees with the model's
    # best-effect estimate (for monitoring, not for judgment).
    decision["agrees_with_best_effect_estimate"] = _compute_agreement(
        decision["chosen_treatment_id"], scoring.get("pair_results", []),
    )

    decisions_table = dynamodb.Table(DECISION_RECORDS_TABLE)
    try:
        decisions_table.put_item(Item=_to_decimal_dict(decision))
    except Exception as exc:
        logger.warning(
            "Failed to persist decision %s: %s", decision_id, exc,
        )

    try:
        kinesis_client.put_record(
            StreamName=TRX_EVENTS_STREAM_NAME,
            PartitionKey=decision["patient_id"],
            Data=json.dumps({
                "event_type":            "treatment_decision_recorded",
                "patient_id":            decision["patient_id"],
                "scoring_run_id":        scoring_run_id,
                "decision_id":           decision_id,
                "chosen_treatment_id":   decision["chosen_treatment_id"],
                "agrees_with_best_effect": decision[
                    "agrees_with_best_effect_estimate"],
                "timestamp":             _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return decision

def match_outcome(decision_id: str, run_date: str,
                    patients: dict, pair_catalog: list) -> dict:
    """
    Match a recorded decision to the patient's actual outcome at
    the protocol-specified timing. The matched prediction-outcome
    pair feeds calibration drift detection and cohort-stratified
    performance monitoring.

    Production: a batch job runs on a cadence aligned with each pair's
    primary outcome timing (e.g., 90-day matching for 90-day A1c).
    """
    decisions_table = dynamodb.Table(DECISION_RECORDS_TABLE)
    decision = _from_decimal(decisions_table.get_item(
        Key={"decision_id": decision_id}
    ).get("Item") or {})
    if not decision:
        logger.warning("Decision %s not found", decision_id)
        return {}

    chosen_treatment_id = decision.get("chosen_treatment_id")
    if chosen_treatment_id in (None, "none"):
        return {"outcome_status": "no_treatment_chosen"}

    pair = _find_pair_for_treatment(chosen_treatment_id, pair_catalog,
                                      decision.get("predictions_at_decision",
                                                    []))
    if not pair:
        return {"outcome_status": "no_pair_found_for_treatment"}

    actual_outcome = _compute_actual_outcome(
        patient_id=decision["patient_id"],
        outcome_id=pair["primary_outcome_id"],
        decision_date=decision["decision_recorded_at"],
        run_date=run_date,
    )

    pair_table = dynamodb.Table(PREDICTION_OUTCOME_PAIRS_TABLE)

    if not actual_outcome.get("observed"):
        record = {
            "pair_id":          f"po-{uuid.uuid4().hex[:16]}",
            "decision_id":      decision_id,
            "patient_id":       decision["patient_id"],
            "scoring_run_id":   decision["scoring_run_id"],
            "outcome_status":   "censored",
            "censor_reason":    actual_outcome.get("censor_reason"),
            "recorded_at":      run_date,
        }
        try:
            pair_table.put_item(Item=_to_decimal_dict(record))
        except Exception:
            pass
        return record

    chosen_prediction = _find_prediction_for_treatment(
        decision.get("predictions_at_decision", []), chosen_treatment_id,
    )
    if not chosen_prediction:
        return {"outcome_status": "no_prediction_for_chosen_treatment"}

    cohort_features = _cohort_features_from_profile(
        patients.get(decision["patient_id"], {}))

    record = {
        "pair_id":              f"po-{uuid.uuid4().hex[:16]}",
        "decision_id":          decision_id,
        "patient_id":           decision["patient_id"],
        "scoring_run_id":       decision["scoring_run_id"],
        "chosen_treatment_id":  chosen_treatment_id,
        "chosen_pair_id":       pair["pair_id"],
        "predicted_outcome":    chosen_prediction.get("point_estimate"),
        "predicted_ci_low":     chosen_prediction.get("ci_low"),
        "predicted_ci_high":    chosen_prediction.get("ci_high"),
        "actual_outcome":       actual_outcome["value"],
        "outcome_status":       "observed",
        "ood_flag_at_decision": chosen_prediction.get("ood_flag", {}),
        "cohort_features":      cohort_features,
        "recorded_at":          run_date,
    }
    try:
        pair_table.put_item(Item=_to_decimal_dict(record))
    except Exception as exc:
        logger.warning(
            "Failed to persist prediction-outcome pair: %s", exc,
        )

    try:
        kinesis_client.put_record(
            StreamName=TRX_EVENTS_STREAM_NAME,
            PartitionKey=decision["patient_id"],
            Data=json.dumps({
                "event_type":          "treatment_outcome_observed",
                "patient_id":          decision["patient_id"],
                "decision_id":         decision_id,
                "chosen_pair_id":      pair["pair_id"],
                "predicted":           chosen_prediction.get("point_estimate"),
                "actual":              actual_outcome["value"],
                "timestamp":           _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return record

def run_calibration_drift_detection(run_date: str,
                                        pair_catalog: list) -> list:
    """
    Aggregate prediction-outcome pairs since the last surveillance
    run; per pair, compute calibration on observed outcomes and
    compare to baseline. Significant drift triggers a surveillance
    alert that a human reviews.

    Production: this runs on a monthly cadence as part of the
    surveillance Step Functions workflow.

    Returns the list of alerts created.
    """
    alerts = []
    pair_table = dynamodb.Table(PREDICTION_OUTCOME_PAIRS_TABLE)
    alerts_table = dynamodb.Table(SURVEILLANCE_ALERTS_TABLE)

    cutoff = (datetime.date.fromisoformat(run_date)
                - timedelta(days=SURVEILLANCE_WINDOW_DAYS)).isoformat()

    for pair in pair_catalog:
        if not pair.get("is_production"):
            continue

        # Production: query a (chosen_pair_id, recorded_at) GSI;
        # the example uses a scan for the demo.
        try:
            response = pair_table.scan()
            recent = []
            for item in response.get("Items", []):
                item = _from_decimal(item)
                if (item.get("chosen_pair_id") == pair["pair_id"]
                    and item.get("outcome_status") == "observed"
                    and str(item.get("recorded_at", "")) >= cutoff):
                    recent.append(item)
        except Exception:
            recent = []

        if len(recent) < 30:
            # Insufficient sample for drift detection. Production
            # logs an "insufficient sample" status to the dashboard
            # so reviewers can spot pairs with too few outcomes
            # accruing.
            continue

        current_calibration = _compute_calibration_from_pairs(recent)
        baseline_slope = _DEMO_BASELINE_SLOPES.get(
            pair["pair_id"], 0.95,
        )
        slope_delta = abs(
            current_calibration["calibration_slope"] - baseline_slope
        )
        drift_severity = slope_delta

        if drift_severity >= DRIFT_ALERT_THRESHOLD:
            alert = {
                "alert_id":      f"alert-{uuid.uuid4().hex[:16]}",
                "alert_type":    "calibration_drift",
                "pair_id":       pair["pair_id"],
                "drift_signal": {
                    "current_slope":       current_calibration[
                        "calibration_slope"],
                    "baseline_slope":      baseline_slope,
                    "slope_delta":         slope_delta,
                    "n_observed":          len(recent),
                    "drift_severity":      drift_severity,
                },
                "triggered_at":  run_date,
                "review_status": "pending",
            }
            try:
                alerts_table.put_item(Item=_to_decimal_dict(alert))
            except Exception:
                pass
            try:
                kinesis_client.put_record(
                    StreamName=TRX_EVENTS_STREAM_NAME,
                    PartitionKey=pair["pair_id"],
                    Data=json.dumps({
                        "event_type":     "prediction_calibration_alert",
                        "pair_id":        pair["pair_id"],
                        "drift_severity": drift_severity,
                        "n_observed":     len(recent),
                        "timestamp":      _now_iso(),
                    }, default=str).encode("utf-8"),
                )
            except Exception:
                pass
            alerts.append(alert)

        # Cohort-stratified drift detection. Even if overall
        # calibration is stable, cohort-specific drift may be
        # widening disparities and is a fairness concern.
        for cohort_axis in pair.get("fairness_axes", []):
            for cohort_value in _DEMO_COHORT_VALUES.get(cohort_axis, []):
                cohort_subset = [
                    r for r in recent
                    if r.get("cohort_features", {}).get(cohort_axis)
                          == cohort_value
                ]
                if len(cohort_subset) < MIN_FAIRNESS_SAMPLE_SIZE:
                    continue
                cohort_calibration = _compute_calibration_from_pairs(
                    cohort_subset)
                cohort_baseline = _DEMO_COHORT_BASELINE_SLOPES.get(
                    (pair["pair_id"], cohort_axis, cohort_value), 0.92,
                )
                cohort_delta = abs(
                    cohort_calibration["calibration_slope"] - cohort_baseline
                )
                if cohort_delta >= COHORT_DRIFT_ALERT_THRESHOLD:
                    cohort_alert = {
                        "alert_id":      f"alert-{uuid.uuid4().hex[:16]}",
                        "alert_type":    "cohort_calibration_drift",
                        "pair_id":       pair["pair_id"],
                        "cohort_axis":   cohort_axis,
                        "cohort_value":  cohort_value,
                        "drift_signal": {
                            "current_slope":  cohort_calibration[
                                "calibration_slope"],
                            "baseline_slope": cohort_baseline,
                            "slope_delta":    cohort_delta,
                            "n_observed":     len(cohort_subset),
                        },
                        "triggered_at":  run_date,
                        "review_status": "pending",
                    }
                    try:
                        alerts_table.put_item(
                            Item=_to_decimal_dict(cohort_alert))
                    except Exception:
                        pass
                    alerts.append(cohort_alert)

    return alerts

def _compute_agreement(chosen_treatment_id: str,
                          pair_results: list) -> bool:
    """
    Determine whether the clinician's decision agrees with the
    model's best-effect estimate. The model's best-effect estimate
    is the treatment with the most-favorable point estimate among
    the eligible pairs. This is a monitoring metric, NOT a judgment
    of clinician decisions.
    """
    if not pair_results:
        return False
    # Pick the treatment with the most-favorable point estimate
    # (most negative for outcomes where lower is better, like A1c
    # reduction).
    valid = [p for p in pair_results
              if p.get("scoring_status") != "suppressed_oodflag"
              and "point_estimate" in p]
    if not valid:
        return False
    best = min(valid, key=lambda p: p["point_estimate"])
    return chosen_treatment_id == best.get("treatment_id")

def _find_pair_for_treatment(treatment_id: str, pair_catalog: list,
                                predictions: list) -> dict:
    """
    Find the pair that was used to score the chosen treatment.
    Prefers the pair the patient was actually scored against; falls
    back to the first catalog pair with this treatment.
    """
    for pair in predictions:
        if pair.get("treatment_id") == treatment_id:
            for catalog_pair in pair_catalog:
                if catalog_pair["pair_id"] == pair.get("treatment_pair_id"):
                    return catalog_pair
    for catalog_pair in pair_catalog:
        if catalog_pair["treatment_id"] == treatment_id:
            return catalog_pair
    return {}

def _find_prediction_for_treatment(predictions: list,
                                       treatment_id: str) -> dict:
    """Find the prediction entry for the chosen treatment."""
    for pred in predictions:
        if pred.get("treatment_id") == treatment_id:
            return pred
    return {}

def _compute_actual_outcome(patient_id: str, outcome_id: str,
                                decision_date: str, run_date: str) -> dict:
    """
    Compute the patient's actual observed outcome at the
    protocol-specified timing. Production: pull longitudinal lab
    and encounter data; check that the measurement is within the
    measurement window plus tolerance; flag censoring on treatment
    switch, plan disenrollment, or competing events. Demo: read
    from a synthetic dict.
    """
    return _DEMO_ACTUAL_OUTCOMES.get(
        (patient_id, outcome_id),
        {"observed": False, "censor_reason": "no_observation_window_yet"},
    )

def _compute_calibration_from_pairs(pairs: list) -> dict:
    """
    Compute calibration slope and intercept from a list of
    prediction-outcome pairs. Production: use a least-squares fit
    on (predicted, actual) pairs grouped by predicted value bins.
    Demo: a simple ratio of mean(actual) to mean(predicted) as a
    proxy for slope.
    """
    if not pairs:
        return {"calibration_slope": 0.0,
                 "calibration_intercept": 0.0,
                 "n_pairs": 0}
    predicted = [p["predicted_outcome"] for p in pairs
                  if p.get("predicted_outcome") is not None]
    actual = [p["actual_outcome"] for p in pairs
                if p.get("actual_outcome") is not None]
    if not predicted or not actual:
        return {"calibration_slope": 0.0,
                 "calibration_intercept": 0.0,
                 "n_pairs": 0}
    mean_p = sum(predicted) / len(predicted)
    mean_a = sum(actual) / len(actual)
    slope = (mean_a / mean_p) if abs(mean_p) > 1e-6 else 1.0
    return {
        "calibration_slope":     round(slope, 4),
        "calibration_intercept": round(mean_a - slope * mean_p, 4),
        "n_pairs":               len(pairs),
    }

# Demo state populated by the runner.
_DEMO_ACTUAL_OUTCOMES: dict = {}
_DEMO_BASELINE_SLOPES: dict = {}
_DEMO_COHORT_BASELINE_SLOPES: dict = {}
```

---

## Putting It All Together

Here's the end-to-end pipeline assembled into a single callable function. In production, this is split across several Step Functions workflows:

- **Weekly retraining pipeline** runs Steps 1-3 per treatment-comparator pair: cohort construction, model training, evaluation, governance gate.
- **On-demand scoring API** runs Steps 4-5 when a clinician requests scoring at the point of care: scoring, briefing generation.
- **Decision-capture worker** runs the decision-recording portion of Step 6 when the EHR posts a decision back via SMART on FHIR or CDS Hooks.
- **Monthly surveillance pipeline** runs the outcome-matching and calibration-drift portions of Step 6.

The example chains them together so you can trace one cycle end-to-end.

```python
def run_full_demo_cycle(patients_list: list,
                          run_date: str | None = None) -> dict:
    """
    Run the full demo cycle:

      Steps 1-3 (per pair): cohort construction, training, evaluation
      Step 4: on-demand scoring for an index patient
      Step 5: briefing generation
      Step 6: decision recording and outcome matching, plus a
              calibration drift detection pass.

    Returns a summary dict.
    """
    run_date = run_date or _today_str()
    start = time.time()

    print(f"=== Starting full demo cycle for run_date={run_date} ===")

    patients = {p["patient_id"]: p for p in patients_list}

    # ---- Steps 1-3: per-pair retraining and evaluation ----
    print("\nSteps 1-3: per-pair cohort construction, training, evaluation...")
    cohort_metadatas = []
    training_results = []
    eval_reports = []
    for pair in SAMPLE_PAIR_CATALOG:
        print(f"  - Pair: {pair['pair_id']}")
        cohort_meta = construct_cohort(pair, run_date, SAMPLE_PROTOCOLS)
        if not cohort_meta:
            continue
        cohort_metadatas.append(cohort_meta)
        training = train_pair_models(cohort_meta, run_date)
        training_results.append(training)
        if training.get("status") == "trained_pending_evaluation":
            eval_result = evaluate_and_gate_pair_models(
                pair["pair_id"], run_date,
            )
            eval_reports.append(eval_result)
            # Auto-approve for the demo. Production: a human
            # committee reviews the report and decides.
            if eval_result.get("task_id"):
                process_governance_decision(
                    eval_result["task_id"],
                    human_decision={
                        "decision":      "approve",
                        "reviewer_ids":  ["medical_director", "informatics_lead",
                                            "equity_lead", "data_science_lead"],
                        "notes":         "Demo auto-approval; production "
                                          "requires committee review.",
                    },
                )

    # ---- Step 4: on-demand scoring for the index patient ----
    print("\nStep 4: on-demand scoring for index patient...")
    index_patient_id = "pat-007842"
    request_context = {
        "clinician_id":          "clinician-0142",
        "index_condition":       "type_2_diabetes_inadequately_controlled_on_metformin",
        "visit_context":         "established_patient_followup",
        "formulary_preference":  "tier_1_or_tier_2_only",
    }
    scoring = score_patient(
        index_patient_id, request_context, patients,
        SAMPLE_PAIR_CATALOG, SAMPLE_TREATMENT_CATALOG,
    )
    print(f"  Scored {len(scoring.get('pair_results', []))} pairs for "
          f"{index_patient_id}")

    # ---- Step 5: briefing generation ----
    print("\nStep 5: briefing generation with validator...")
    briefing = generate_briefing(
        scoring["scoring_run_id"], patients, SAMPLE_TREATMENT_CATALOG,
    )
    print(f"  Briefing generated: validator_status="
          f"{briefing.get('validator_status')}")

    # ---- Step 6: decision recording and outcome matching ----
    print("\nStep 6: decision recording (clinician chose GLP-1)...")
    decision = record_decision(
        scoring_run_id=scoring["scoring_run_id"],
        decision_payload={
            "clinician_id":              "clinician-0142",
            "chosen_treatment_id":       "glp1_receptor_agonist_class",
            "clinician_rationale":       "Patient profile: cardiovascular "
                                            "indication, declining eGFR, "
                                            "elevated BMI; GLP-1 effect estimate "
                                            "favorable; patient consented after "
                                            "discussion of injectable and "
                                            "GI side effects.",
            "patient_consent_recorded":  True,
            "shared_decision_indicators": {
                "patient_summary_shared":  True,
                "patient_preference_recorded": True,
                "patient_preference":      "willing_to_try_injectable",
            },
        },
        patients=patients,
    )
    print(f"  Decision recorded: {decision.get('decision_id')}")

    # 90 days later, simulate the outcome readout.
    print("\nStep 6: outcome matching (90 days after decision)...")
    future_run_date = (datetime.date.fromisoformat(run_date)
                         + timedelta(days=90)).isoformat()
    outcome_match = match_outcome(
        decision["decision_id"], future_run_date, patients,
        SAMPLE_PAIR_CATALOG,
    )
    print(f"  Outcome match: status={outcome_match.get('outcome_status')}; "
          f"predicted={outcome_match.get('predicted_outcome')}; "
          f"actual={outcome_match.get('actual_outcome')}")

    # Calibration drift detection pass.
    print("\nStep 6: calibration drift detection sweep...")
    alerts = run_calibration_drift_detection(
        future_run_date, SAMPLE_PAIR_CATALOG,
    )
    print(f"  Calibration drift alerts: {len(alerts)}")

    elapsed = int(time.time() - start)
    print(f"\n=== Cycle complete in {elapsed}s ===")
    return {
        "run_date":           run_date,
        "n_patients":         len(patients_list),
        "n_cohorts_built":    len(cohort_metadatas),
        "n_pairs_trained":    sum(
            1 for t in training_results
            if t.get("status") == "trained_pending_evaluation"),
        "scoring_run_id":     scoring.get("scoring_run_id"),
        "n_pair_results":     len(scoring.get("pair_results", [])),
        "briefing_id":        briefing.get("briefing_id"),
        "validator_status":   briefing.get("validator_status"),
        "decision_id":        decision.get("decision_id"),
        "outcome_status":     outcome_match.get("outcome_status"),
        "n_alerts":           len(alerts),
        "elapsed_seconds":    elapsed,
    }
```

---

## Demo Runner

```python
if __name__ == "__main__":
    # All sample data is SYNTHETIC. Do not use real PHI in
    # development. The demo:
    #   1. Builds a synthetic candidate cohort for the T2D
    #      second-line therapy comparison
    #   2. Builds an index patient (Marcus from the recipe's
    #      opening narrative) plus auxiliary fairness data
    #   3. Runs Steps 1-3 to construct cohorts, train pseudo-models,
    #      evaluate, and auto-approve the governance gate
    #   4. Runs Step 4 to score Marcus against the eligible pairs
    #   5. Runs Step 5 to generate the comparison briefing
    #   6. Runs Step 6 to record Marcus's decision (GLP-1), match
    #      to a synthetic 90-day outcome, and detect calibration
    #      drift
    #
    # The Bedrock and SageMaker calls are mocked at the helper level
    # so the demo runs offline.

    print("=" * 70)
    print("Building synthetic cohort, patients, and seeding demo state...")
    print("=" * 70)

    run_date = _today_str()

    # --- The index patient (Marcus from the recipe's opening) ---
    index_patient = {
        "patient_id":              "pat-007842",
        "age":                     58,
        "age_band":                "55-64",
        "preferred_language":      "en",
        "race_ethnicity_self_report": "non_hispanic_white",
        "sdoh_cohort":             "moderate_food_security",
        "active_conditions":       ["type_2_diabetes", "hypertension",
                                      "hyperlipidemia"],
        "current_medications":     ["metformin", "atorvastatin",
                                      "lisinopril"],
        "bmi":                     34.0,
        "coronary_calcium_score":  240,
        "recent_lab_trends": {
            "a1c_recent":         8.7,
            "egfr_recent":        64,
            "egfr_change_24mo":  -14,
            "uacr_recent":       45,
        },
        "contraindications":       [],
        "social_context_summary":  "Works full-time, family history of "
                                    "diabetes and CAD; primary concern is "
                                    "weight and energy.",
    }

    # --- Auxiliary patients for fairness data ---
    auxiliary_patients = [
        {
            "patient_id":              "pat-007843",
            "age":                     61,
            "age_band":                "55-64",
            "preferred_language":      "es",
            "race_ethnicity_self_report": "hispanic_latino",
            "sdoh_cohort":             "low_food_security",
            "active_conditions":       ["type_2_diabetes"],
            "current_medications":     ["metformin"],
            "bmi":                     31.5,
            "coronary_calcium_score":  None,
            "recent_lab_trends": {"a1c_recent": 9.0, "egfr_recent": 78,
                                   "egfr_change_24mo": -3, "uacr_recent": 12},
            "contraindications":       [],
        },
        {
            "patient_id":              "pat-007844",
            "age":                     67,
            "age_band":                "65-74",
            "preferred_language":      "en",
            "race_ethnicity_self_report": "non_hispanic_black",
            "sdoh_cohort":             "transportation_barrier",
            "active_conditions":       ["type_2_diabetes",
                                          "chronic_kidney_disease"],
            "current_medications":     ["metformin", "lisinopril"],
            "bmi":                     29.0,
            "coronary_calcium_score":  120,
            "recent_lab_trends": {"a1c_recent": 8.2, "egfr_recent": 52,
                                   "egfr_change_24mo": -8, "uacr_recent": 65},
            "contraindications":       [],
        },
    ]

    patients_list = [index_patient] + auxiliary_patients

    # --- Synthetic candidate cohort for cohort construction ---
    # In production, Athena queries the data lake. The demo uses
    # this in-memory list with a treatment-arm tag so the assigner
    # can build cohorts.
    _DEMO_CANDIDATE_COHORT.extend([
        {
            "patient_id":              f"hist-{i:04d}",
            "synthetic_treatment_arm": "treated" if i % 2 == 0 else "comparator",
            "index_date":              "2024-06-01",
            "covariates":              {"a1c_at_index": 8.0 + (i % 30) * 0.05,
                                          "bmi_at_index": 28 + (i % 12)},
            "synthetic_outcomes": {
                "a1c_change_at_90_days": {
                    "value":    -1.4 if i % 2 == 0 else -0.8,
                    "observed": True,
                    "censored": False,
                },
                "weight_change_at_90_days": {
                    "value":    -0.08 if i % 2 == 0 else -0.02,
                    "observed": True,
                    "censored": False,
                },
                "hypoglycemia_event_at_90_days": {
                    "value":    0,
                    "observed": True,
                    "censored": False,
                },
                "gi_intolerance_discontinuation_60_days": {
                    "value":    1 if (i % 2 == 0 and i % 7 == 0) else 0,
                    "observed": True,
                    "censored": False,
                },
            },
        }
        for i in range(1300)
    ])

    # --- Demo cohort summaries returned by the cohort retrieval stub ---
    _DEMO_COHORT_SUMMARIES.update({
        "t2d-glp1-vs-sglt2": {
            "total_size":              1284,
            "treated_size":            612,
            "comparator_size":         672,
            "demographic_match_score": 0.79,
            "condition_match_score":   0.84,
            "average_treated_outcome_a1c_change":   -1.41,
            "average_comparator_outcome_a1c_change": -0.79,
        },
        "t2d-glp1-vs-sulfonylurea": {
            "total_size":              891,
            "treated_size":            412,
            "comparator_size":         479,
            "demographic_match_score": 0.74,
            "condition_match_score":   0.82,
            "average_treated_outcome_a1c_change":   -1.41,
            "average_comparator_outcome_a1c_change": -1.07,
        },
        "t2d-sglt2-vs-sulfonylurea": {
            "total_size":              763,
            "treated_size":            342,
            "comparator_size":         421,
            "demographic_match_score": 0.71,
            "condition_match_score":   0.80,
            "average_treated_outcome_a1c_change":   -0.79,
            "average_comparator_outcome_a1c_change": -1.07,
        },
    })

    # Demo calibration baselines (set at training time in production).
    _DEMO_CALIBRATION_BY_ESTIMATOR.update({
        "causal_forest": {"calibration_slope": 0.96,
                            "calibration_intercept": 0.02,
                            "n_test_patients": 320},
        "dr_learner":    {"calibration_slope": 0.92,
                            "calibration_intercept": 0.04,
                            "n_test_patients": 320},
        "bart":          {"calibration_slope": 0.94,
                            "calibration_intercept": 0.03,
                            "n_test_patients": 320},
    })

    # Demo cohort axes for fairness instrumentation.
    _DEMO_COHORT_VALUES.update({
        "language": ["en", "es", "zh"],
        "race_ethnicity_self_report": [
            "non_hispanic_white", "non_hispanic_black",
            "hispanic_latino", "asian"],
        "sdoh_cohort": ["high_food_security", "moderate_food_security",
                          "low_food_security", "transportation_barrier"],
        "age_band":  ["18-34", "35-54", "55-64", "65-74", "75-plus"],
    })

    for axis, values in _DEMO_COHORT_VALUES.items():
        for value in values:
            for pair in SAMPLE_PAIR_CATALOG:
                _DEMO_FAIRNESS_SAMPLE_SIZE[
                    (pair["pair_id"], axis, value)] = 60

    _DEMO_ESTIMATOR_AGREEMENT.update({
        pair["pair_id"]: {
            "mean_pairwise_correlation":  0.83,
            "percent_high_disagreement":  0.08,
            "agreement_score_summary":    "strong",
        }
        for pair in SAMPLE_PAIR_CATALOG
    })

    # Demo pair-table seed so train_pair_models / evaluate / promote
    # can read and write.
    pairs_table = dynamodb.Table(TREATMENT_COMPARISON_PAIRS_TABLE)
    for pair in SAMPLE_PAIR_CATALOG:
        try:
            pairs_table.put_item(Item=_to_decimal_dict(pair))
        except Exception:
            pass

    # Demo synthetic outcome at 90 days for Marcus.
    _DEMO_ACTUAL_OUTCOMES[
        ("pat-007842", "a1c_change_at_90_days")] = {
        "value":    -1.62,
        "observed": True,
        "censored": False,
    }

    _DEMO_BASELINE_SLOPES.update({
        pair["pair_id"]: 0.95 for pair in SAMPLE_PAIR_CATALOG
    })

    # Mock Bedrock briefing call so the demo runs offline.
    def _mock_briefing(context, strict_mode=False):
        first = next(
            (p for p in context["pair_results"]
              if p.get("scoring_status") != "suppressed_oodflag"
              and "point_estimate" in p),
            None,
        )
        if not first:
            return _no_eligible_briefing(
                {"patient_id": "demo", "pair_results": []})
        return {
            "headline": (
                "Comparison of estimated 90-day A1c change across "
                "eligible second-line therapies."
            ),
            "comparison_paragraph": (
                f"For a patient with this profile, the model estimates "
                f"a 90-day A1c change of "
                f"{first['point_estimate']:+.2f} percentage points (95% CI "
                f"{first['ci_low']:+.2f} to {first['ci_high']:+.2f}) for "
                f"{first['treatment_id']} versus {first['comparator_id']}. "
                "The cohort underlying this estimate has "
                f"{first.get('cohort_summary', {}).get('total_size', 'unknown')} "
                "patients with strong demographic and condition match. "
                "Estimator agreement is strong; the patient is in-distribution."
            ),
            "per_treatment_summary": {
                p["treatment_id"]: (
                    f"Estimated change {p.get('point_estimate', 'n/a')} pp; "
                    f"cohort {p.get('cohort_summary', {}).get('total_size', 'unknown')}; "
                    f"formulary status {p.get('formulary_status', 'unknown')}."
                )
                for p in context["pair_results"]
                if p.get("scoring_status") != "suppressed_oodflag"
            },
            "uncertainty_summary": (
                "Confidence intervals reflect statistical uncertainty plus "
                "estimator-agreement plus pre-computed sensitivity analysis. "
                "Sensitivity analyses indicate the GLP-1 versus SGLT2 "
                "comparison is robust to moderate unmeasured confounding."
            ),
            "caveats": [
                "Estimates are conditional-average effects from observational "
                  "data, not individual guarantees.",
                "Cardiovascular and renal benefits are evidenced by RCTs and "
                  "are not fully captured in the 90-day A1c outcome.",
                "Patient preferences and barriers (cost, injectable acceptance, "
                  "supply) are not in the model and should drive shared "
                  "decision-making.",
                "The clinician's clinical judgment is essential and not "
                  "captured in the model.",
            ],
            "suggested_clinician_review_points": [
                "Weight management goal: weight is a strong secondary "
                  "consideration in this patient's profile.",
                "Cardiovascular and renal indication: GLP-1 and SGLT2 both "
                  "have indication-supported benefit; the choice between them "
                  "is not driven by 90-day A1c alone.",
                "Patient willingness to use injectable: not in the model; ask "
                  "the patient.",
            ],
        }

    globals()["_bedrock_comparison_briefing"] = _mock_briefing

    print(f"  Patients: {len(patients_list)}")
    print(f"  Synthetic candidate cohort size: "
          f"{len(_DEMO_CANDIDATE_COHORT)}")

    print("\n" + "=" * 70)
    print("Running full demo cycle...")
    print("=" * 70)

    summary = run_full_demo_cycle(patients_list=patients_list,
                                       run_date=run_date)

    print(f"\nSummary keys: {list(summary.keys())}")
    print(f"Cohorts built: {summary['n_cohorts_built']}; "
          f"Pairs trained: {summary['n_pairs_trained']}")
    print(f"Scoring run: {summary['scoring_run_id']}; "
          f"Pair results: {summary['n_pair_results']}")
    print(f"Briefing validator passed: {summary['validator_status']}")
    print(f"Decision: {summary['decision_id']}")
    print(f"Outcome status: {summary['outcome_status']}")
    print(f"Calibration alerts: {summary['n_alerts']}")

    print("\n=== Demo complete ===")
```

---

## The Gap Between This and Production

Run this end-to-end against a curated treatment catalog, populated claims/EHR/lab/pharmacy/registry/PROM feeds, real causal-inference pipelines (EconML, grf, bartCause), trained per-pair propensity, outcome, and CATE-ensemble models, working SMART on FHIR or CDS Hooks integration, and a clinician-informatics-led UX, and you'll see the pattern: per-pair causal models with calibration and fairness instrumentation, on-demand scoring at the point of care with similar-patient cohort retrieval and uncertainty quantification, validator-protected clinician-facing briefings, decision capture with frozen-at-decision-time predictions, prediction-outcome matching, and calibration drift detection. The distance between this and a real EHR-integrated deployment is significant. Here's where it lives.

**Treatment-catalog curation as an ongoing program.** The catalog is the source of truth for what each treatment-comparator pair means. New drugs land, new indications emerge, formulary changes ship quarterly, evolving guideline recommendations require pair-level updates, supply constraints come and go, and post-marketing safety signals shift the evidence base. Plan for at least 0.5 to 1.0 FTE of pharmacy and therapeutics, clinical informatics, and health economics time on catalog maintenance ongoing, plus a structured change-management process with parallel evaluation against the prior catalog version when significant changes ship.

**Causal-inference rigor at production scale.** The methodology described in the main recipe's "The Technology" section is not a checklist; it is a discipline that requires a dedicated methodologist or a methodologist-trained data scientist in the loop. Plan for the staffing: at minimum a senior data scientist with formal causal-inference training, a clinical informaticist who understands the outcome definitions and target trials, and a biostatistician who can evaluate the sensitivity analyses. The example uses rule-based proxies; production trains EconML's CausalForestDML, DRLearner, and a BART-based estimator (or grf and bartCause via R wrappers) on the actual cohort, with cross-validation, hyperparameter selection, and methodological review.

**Target trial emulation infrastructure.** The cohort construction in this example is a stub. Production needs parameterized SQL templates per protocol (eligibility, washout, exposure assignment, censoring), versioned alongside the protocol, with proper handling of the index-date selection, the grace-window for treatment exposure, the competing-events handling for survival outcomes, and the per-outcome measurement window with tolerance. Plan 12 to 20 weeks of clinical-informatics-led cohort engineering before the first end-to-end retraining run, plus an ongoing methodological review process for new pair additions.

**SageMaker Feature Store integration.** The example skips Feature Store usage. Production wires per-patient and per-treatment-history feature ingestion through Glue or Spark into both the offline and online stores, with feature freshness guarantees per source. The feature definitions are reused across Recipes 4.4 through 4.7 and 4.8; centralizing them in the Feature Store is the entire point. Special handling for time-varying features (lab trajectories, medication histories) that need point-in-time correctness for retraining cohorts.

**SageMaker Pipelines and Model Registry per pair.** The example replaces real Training Job submissions with pseudo-ARNs. Production: a SageMaker Pipeline per pair that trains the propensity, outcome, and CATE-ensemble models, runs the calibration and fairness tests, registers the artifacts in the Model Registry, and gates promotion through the governance task table. With three model artifacts per pair times ten to thirty pairs in scope, the registry plus canary-on-held-out-cohort-before-promotion automation is essential.

**Real-time inference topology.** The example simulates per-pair endpoints. Production rationalizes the serving topology against actual usage: SageMaker Multi-Model Endpoints amortize the per-pair models on shared infrastructure, SageMaker Asynchronous Inference handles bursty workloads, SageMaker Serverless Inference is appropriate for low-volume pairs. Latency budget at the point of care is typically 1-3 seconds for the full ensemble; per-estimator latency budgets should be set accordingly.

**Propensity overlap as a hard gate.** The example checks overlap and suspends training on severe failure. Production enforces this strictly: the per-pair pipeline does not promote new artifacts when overlap fails, and the pre-existing production artifact remains in service or is suspended depending on policy. Re-scoping the cohort (different eligibility, different comparator, narrower indication) is the methodologically appropriate response; over-extrapolating across the gap is not.

**Estimator ensemble selection and tuning.** The example uses three estimators by name. Production picks the ensemble per pair based on data characteristics: causal forest for high-dimensional features with non-linear heterogeneity, DR-learner when the propensity model is well-specified, BART for the Bayesian uncertainty quantification when the cohort is large enough to support it. The choice is empirical; benchmarking on held-out data with known treatment effects (or randomized subsets) is essential.

**Sensitivity analysis as first-class output.** The example uses a fixed multiplier per pair. Production runs VanderWeele-Ding E-value computation and Rosenbaum bounds on the actual cohort at training time, persists the bounds with the model artifacts, and applies them to widen reported CIs at scoring time. The E-value is a structural-uncertainty bound that the briefing surfaces explicitly; the larger the E-value, the more robust the conclusion to unmeasured confounding.

**Cohort fairness instrumentation tied to a quarterly review committee.** The example computes per-cohort calibration but doesn't surface it on a dashboard. Production wires QuickSight dashboards for per-treatment-pair calibration parity, per-cohort estimate parity at clinical equipoise, and adverse-event parity. A cross-functional committee (medical director, clinical informatics, equity lead, data science lead, regulatory and compliance lead) reviews the dashboards quarterly with explicit action ownership for findings. The Obermeyer 2019 finding is the canonical cautionary tale; design for it from day one.

**Regulatory pathway determination and documentation.** The model risk tier per treatment-comparator pair determines whether the pair is in scope for FDA SaMD regulation, the 21st Century Cures Act CDS exemption, or another regulatory framework. The decision is fact-specific: the form of the recommendation (descriptive paragraph versus ranked list versus single recommendation), the underlying evidence (RCT-backed versus observational), and the clinician's ability to review the basis matter. Plan for regulatory legal review at scoping, a predetermined change control plan if SaMD applies, postmarket surveillance documentation, complaint handling, and quality system documentation. Retrofitting compliance is dramatically more expensive than building it in.

**EHR integration through SMART on FHIR or CDS Hooks.** The example exposes scoring as a Python function call. Production: an authenticated API Gateway endpoint consumed by a SMART on FHIR app embedded in the EHR (Cerner, Epic, athenahealth, etc.) or a CDS Hooks endpoint invoked by the EHR at relevant decision points (medication-prescribe, condition-encounter). Plan for at least 12 to 20 weeks of EHR-integration engineering per EHR vendor, including authentication (the institution's identity provider via SAML or OIDC), PHI handling at the integration boundary, latency budgets, and the clinician workflow design that determines where and how the briefing surfaces.

**Clinician workflow design.** The integration point is critical, but the workflow design is what determines whether the briefing actually informs decisions. Production needs a dedicated clinical-informatics-led UX project: when does the briefing surface (always, on-demand, contextual), how does the clinician dismiss it (per-patient, per-session), how does the chosen-treatment field get back to the system, how does the rationale get captured, what does the briefing look like on a desktop versus a tablet versus a smartphone. Plan for iterative deployment to a small clinician cohort, clinician feedback loops, and willingness to redesign the surface before broad rollout.

**Patient consent and shared decision-making.** Treatment decisions are shared decisions. The patient-facing summary is a separate UX project, with reading-level matching, lay-language equivalents, and integration with the institution's existing shared decision-making programs. Whether and how the patient-facing version is shared, whether the patient's preferences are captured back into the decision record, and whether the patient consents to having their data used for ongoing model improvement are all design decisions with legal, ethical, and operational implications.

**Validator extension and per-layer alarms.** The example uses a single `_validate_briefing` function. Production breaks the four layers (schema, recommendation language, uncertainty completeness, required caveats) apart for testability and per-layer alarms: a validator-fallback rate spike on the recommendation-language layer indicates the LLM is drifting in a direction that requires a system-prompt update; a fallback-rate spike on the uncertainty-completeness layer indicates the briefing context format may be obscuring uncertainty signals. Track the per-layer fail rates as separate CloudWatch metrics.

**Bedrock cost and latency budget.** The clinician-facing briefing uses Sonnet-class models because the prompt is long-context and the validator's recommendation-language rule is strict. At thousands of scoring requests per day, the budget is meaningful. Production tunes the model choice per region and per validator pass-rate; consider routing first attempts through a smaller model with stricter prompts and falling back to Sonnet only on validator failure. Monitor Bedrock spend in CloudWatch and set per-account quota alarms.

**Briefing TTL and staleness handling.** The example sets a TTL on briefings. Production needs the EHR integration to respect the TTL: a briefing displayed at a Tuesday visit should not surface unchanged at a Friday visit. The integration re-requests scoring when the cached briefing is stale, with a UX pattern that doesn't make the clinician wait for re-scoring on chart open if the prior briefing is recent enough.

**Decision capture latency and reliability.** The decision-recording flow assumes the EHR posts the decision back synchronously. Production: tolerate decision-capture latency (minutes to hours after the visit) by treating decision capture as eventually consistent, with the decision-records table updated on EHR-event arrival via Kinesis. Be prepared for decisions that never arrive (clinician dismissed the briefing without recording a decision); design the surveillance metrics to handle missing data without distortion.

**Outcome matching at scale.** The example matches one outcome at a time. Production runs nightly batch jobs that match all outstanding decisions to outcomes at their primary outcome timing, with proper handling of secondary outcomes that read out at different timings and of patients with multiple decisions over time (each decision has its own predicted-outcome pair). Outcome computation respects the protocol's measurement window, tolerance, and censoring rules; the example reads from a synthetic dict, but production pulls longitudinal lab and encounter data with point-in-time correctness.

**Calibration drift detection at network scale.** Single-institution surveillance is underpowered for many drift signals. Production benefits from consortium-based surveillance (OHDSI, PCORnet, Sentinel) where calibration drift signals are pooled across multiple institutions with privacy-preserving methods. Building the consortium integration is a large external partnership; the recipe assumes single-institution operation, but the production version benefits substantially from consortium membership.

**Adverse-event surveillance.** The example focuses on calibration drift. Production also runs adverse-event surveillance: matching prescriptions of recommended treatments to subsequent adverse events at higher-than-expected rates. This is essential for SaMD-class tools and an ethical expectation regardless of regulatory classification. Adverse-event surveillance at low base rates is methodologically distinct (signal-detection methods, sequential probability ratio tests) and benefits from the same consortium integration mentioned above.

**Cross-recipe orchestration with Recipes 4.5, 4.6, 4.7, 4.9, and 4.10.** A patient who gets a treatment-response prediction at the visit may also be a candidate for medication-adherence intervention (4.5), care-gap closure (4.6), care-management enrollment (4.7), personalized care plan generation (4.9), or dynamic treatment regime recommendation (4.10). Document the cross-recipe data flow; the chosen treatment from 4.8 feeds the care plan in 4.9; the predicted adherence from 4.5 feeds the 4.8 prediction's caveat about adherence assumptions; the care-management enrollment in 4.7 may include monitoring for the chosen treatment's outcomes. Design for the integration rather than bolting it on.

**Privacy posture for scoring results, briefings, and decision records.** The `scoring-results` table joins patient identifiers, predicted treatment outcomes, and similar-patient cohort summaries; it is highly inferential PHI. The `briefings` table contains LLM-generated treatment-comparison text tied to a patient and a clinician; it is treatment-recommendation-relevant content with elevated sensitivity. The `decision-records` table joins patient identifier, chosen treatment, predictions at decision time, and clinician rationale; it is closer to clinical-record audit content than typical analytics audit. Apply tighter controls than for engagement data: narrower IAM read scopes, optional separate-table partitioning by sensitivity tier, additional CloudTrail data event capture, documented minimum-necessary access policy. Mirror the language flagged in 4.4 through 4.7.

**Tracking-ID and scoring-ID privacy.** The example builds scoring run IDs as `f"score-{run_date}-{patient_id}-{suffix}"` for readability. Production must replace this with an opaque, non-reversible identifier (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plain-text patient_ids embedded in scoring IDs (carried in EHR responses, scoring API responses, briefings, and decision events) are PHI leakage. The same applies to `_make_briefing_id` and `_make_decision_id` (already opaque in the example). Mirror the language from 4.4 through 4.7.

**DynamoDB Decimal gotchas.** The example uses `_to_decimal` and `_to_decimal_dict` consistently when persisting numeric values. The pattern is correct, but the trap is real: if you add a feature that persists a model confidence interval or any other floating-point value, you must wrap it at the boundary or DynamoDB will reject the write.

**Step Functions orchestration with explicit DLQ coverage.** The example chains all steps in a single Python function. Production runs the weekly retraining pipeline as a Step Functions state machine; the on-demand scoring API as Lambda behind API Gateway; the decision-capture worker as a Lambda triggered on the EHR-integration event stream; the monthly surveillance pipeline as a separate state machine. Each task has Catch handlers routing failures to per-stage SQS DLQs keyed on (run, pair, stage, failure_reason). The Kinesis-to-Lambda event source mappings for the decision-capture and outcome-matching workers need explicit `OnFailure` destinations pointing to SQS, alarmed on DLQ depth. The point-of-care scoring path must fail loudly: a scoring API timeout returns "scoring temporarily unavailable" rather than a partial or stale prediction. Mirror the language from 4.4 through 4.7.

**Idempotency and retry semantics.** Each stage's outputs are addressed by deterministic keys (cohort run, scoring run id, decision id) and writes should be conditional, so a Step Functions retry that re-attempts a completed step is a no-op rather than a duplicate. The example uses `put_item` and `update_item` without conditions on most paths; production adds `ConditionExpression` to the relevant writes (e.g., `attribute_not_exists(decision_id)` on the decision put) so reattempted writes converge.

**VPC, encryption, and audit.** This example calls APIs over public AWS endpoints. A production Lambda handling PHI runs in a VPC with private subnets and VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock Runtime (interface), SageMaker Runtime and Feature Store (interface), Kinesis (interface), CloudWatch Logs (interface), Athena (interface), Step Functions (`states`), EventBridge (`events`), STS, API Gateway, and HealthLake (if used). All nine DynamoDB tables encrypt at rest with a customer-managed KMS key. CloudTrail data events are enabled for the treatment-catalog, treatment-comparison-pairs, scoring-results, briefings, decision-records, prediction-outcome-pairs, and surveillance-alerts tables. A clinical or compliance audit will eventually ask "who was scored for what on this date and why" and you need to answer definitively.

**Synthetic data and testing.** There are no tests in this example. A production pipeline needs unit tests for the cohort construction logic per pair, the propensity-overlap diagnostic, the per-estimator scoring, the ensemble combination, the OOD-flag computation, the validator's four layers, the decision-capture flow, and the outcome-matching flow; integration tests against a synthetic Synthea-generated patient population across cohort axes; regression tests that confirm the validator catches recommendation-language attempts; load tests at expected volumes (5,000 scoring requests per day, 30 pairs in scope); chaos tests that drop a SageMaker endpoint mid-scoring and verify the API returns a non-prediction response. Never use real PHI in non-production environments.

**Cold-start handling for new pairs.** The example assumes every pair has trained production models. A brand-new pair has none. Cold-start strategy: launch new pairs as advisory-only (tier 1) with rule-based scoring only, run the first cohort emulation in shadow mode, gather feedback from the cross-functional review committee before promoting the pair to production. Document the pair's training-status explicitly; clinicians should know when a pair is in "calibrating" mode versus production.

**Model retirement and sunset.** Some pairs will, over time, lose calibration faster than retraining can recover, become structurally biased in ways that fairness instrumentation cannot fully correct, or be superseded by a regulatory-cleared alternative. Production needs a sunset path: a pair can be retired from production with explicit rationale, the retirement triggers downstream cleanup (suppress the briefings, archive the decision records with the retired-model annotation, communicate to the clinical-informatics team). The pattern that fails is models that quietly degrade in production because nobody is responsible for retiring them; the result is clinicians who learn to ignore the briefing.

**Patient-facing summaries.** The example codes only the clinician-facing briefing. Production extends with a patient-facing summary generator (Haiku-class model, similar validator pattern, reading-level matching for patient literacy, approved-claim language enforcement). Whether and when the summary is shared with the patient is a clinician decision; the system supports both modes (clinician-only, clinician-and-patient-shared).

**Disagreement-investigation narratives for the modeling team.** When the multiple CATE estimators disagree more than the threshold, an internal-facing narrative helps the modeling team triage the cause (model misspecification, unmeasured confounding, treatment-effect heterogeneity, data quality). The example does not implement this; production wires a separate Lambda that fires on `disagreement_alert` Kinesis events and posts a structured summary to the modeling team's queue.

**Real-world evidence integration.** The catalog and the evaluation infrastructure described here are the substrate for real-world evidence generation. Per-treatment-comparator cohort effects, with the methodological rigor of target trial emulation, are evidence that supports regulatory submissions, label expansions, and post-marketing safety analyses. A research collaboration with a regulatory or RWE partner extends the value of the system substantially beyond decision support.

**Negative-control and falsification analyses.** A robust CATE pipeline includes negative-control outcomes (outcomes that should not be affected by the treatment; if the estimator finds an effect on a negative-control outcome, the estimator is misspecified or there is unmeasured confounding) and falsification tests (effects on treatment-naive periods, effects on outcomes that occurred before treatment). These are research-grade discipline but increasingly expected in production-grade real-world evidence pipelines. The example does not implement these; production adds them as part of the per-pair evaluation in Step 3.

**Cost-effectiveness extensions.** A model that predicts only clinical effects misses the cost-effectiveness dimension that drives many real-world treatment decisions. An extended pipeline computes per-patient cost-of-treatment (drug cost, monitoring cost, downstream cost based on predicted outcomes) alongside clinical effect, and the briefing surfaces a cost-versus-benefit comparison. Cost-effectiveness analysis is methodologically distinct (incremental cost-effectiveness ratios, willingness-to-pay thresholds) and benefits from health economics expertise on the team.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 4.8: Treatment Response Prediction](chapter04.08-treatment-response-prediction) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
