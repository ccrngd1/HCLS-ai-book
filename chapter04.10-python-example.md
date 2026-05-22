# Recipe 4.10: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 4.10. It shows one way you could translate the dynamic treatment regime recommendation pattern into working Python using a synthetic longitudinal trajectory generator (in lieu of real EHR / claims feeds), scikit-learn for the Q-learning function approximation and the behavior policy estimator, NumPy for the doubly-robust off-policy evaluation, Amazon DynamoDB for the regime catalog, trajectory metadata, recommendation records, and surveillance metrics, Amazon S3 for trajectory archives and OPE outputs, Amazon SageMaker Model Registry for regime versioning, AWS Step Functions for orchestration semantics (illustrated, not invoked), AWS Lambda boundaries (illustrated, not invoked), Amazon Bedrock for clinician-facing regime briefings with the four-layer validator from prior recipes, Amazon Kinesis for the regime event stream, Amazon EventBridge for decision-point triggers and surveillance schedules, and Amazon API Gateway and Cognito for the SMART on FHIR clinician decision-support surface (illustrated). It is not production-ready. There is no real EHR, claims, lab, pharmacy, or registry feed, no real upstream-recipe signal aggregation from Recipes 4.5 through 4.9, no clinically curated regime catalog (the example ships a synthetic diabetes / CKD stepwise-therapy regime), no real interaction database integration, no validated reward function, no methodologically rigorous offline RL or A-learning implementation (Q-learning with gradient-boosted regression is the only estimator), no SMART on FHIR plan-review surface, no real OOD detector beyond a coarse k-NN distance heuristic, no real federated or consortium estimation, no regulatory analysis. Think of it as the sketchpad version: useful for understanding the shape of a sequential-causal-inference pipeline that respects the structured-then-narrative direction, multi-method estimator triangulation (sketched), cohort-stratified off-policy evaluation, the four-layer LLM validator on the clinician briefing, and the structured recommendation as the system of record. It is not something you would wire into an EHR on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the six pseudocode steps from the main recipe: build longitudinal trajectories from source data and freeze them with explicit decision points and rewards; estimate the behavior policy with calibration on cohort-stratified held-out data; train candidate regimes with Q-learning (with placeholders for offline RL and A-learning); run off-policy evaluation with doubly-robust, importance-sampling, and fitted-Q-evaluation estimators plus cohort-stratified results and a simple sensitivity analysis; serve a recommendation at a decision point with eligibility, OOD detection, similar-trajectory retrieval, and a validator-protected clinician narrative; capture the clinician's eventual action and run a periodic-surveillance sweep that watches adherence, calibration drift, and cohort fairness. All sample patients, conditions, medications, actions, narratives, and feedback events are synthetic. The patient in the demo is Sara from the recipe's opening narrative.

---

## Setup

You will need the AWS SDK for Python plus a couple of numerical libraries:

```bash
pip install boto3 numpy pandas scikit-learn
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchWriteItem` on the `regime-catalog`, `trajectory-metadata`, `recommendation-records`, `regime-versions`, and `surveillance-metrics` tables
- `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on the `dtr-data-lake`, `dtr-trajectories`, `dtr-ope`, `dtr-recommendation-archives`, and `dtr-surveillance` buckets
- `bedrock:InvokeModel` on the specific foundation-model ARNs used for the clinician-facing regime briefing and the patient-facing summary
- `kinesis:PutRecord` on the `dtr-events` stream
- `events:PutEvents` on the EventBridge bus that routes decision-point triggers and surveillance schedules
- `sagemaker:CreateModelPackage`, `sagemaker:DescribeModelPackage`, `sagemaker:ListModelPackages`, `sagemaker:UpdateModelPackage` on the regime model package group
- `sagemaker:InvokeEndpoint` on the regime-serving endpoint ARN (production only; the demo invokes the policy in-process)
- `cloudwatch:PutMetricData` for cohort-stratified regime-quality metrics
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs

You also need model access enabled in the Bedrock console for the narrative-generation models.

A few things worth knowing upfront:

- **The regime catalog is the substrate of the system.** State definitions, action catalogs, reward functions, decision-point cadences, eligibility predicates, and model risk tiers are the artifacts the rest of the pipeline operates on. This example ships a small synthetic regime covering diabetes / CKD stepwise therapy with a five-action catalog (add an SGLT2, intensify the GLP-1, add basal insulin, add a DPP-4, no change). Production maintains many regimes per clinical area, with cohort overrides, evidence references, versioning, and a regime-governance committee that approves promotions.
- **Off-policy evaluation is the load-bearing inference, not a sanity check.** The OPE estimators (doubly-robust, importance sampling, fitted Q evaluation) plus the sensitivity analysis are what produce a value estimate with confidence intervals that the governance committee actually cares about. The example computes all three estimators and a simple E-value-style sensitivity analysis, with cohort stratification.
- **The four-layer validator from Recipes 4.5 through 4.9 carries forward.** Schema and length, fact grounding, prohibited-language patterns, and required content. The regime-narrative-specific prohibited-language patterns are stricter (no policy-as-directive framing, no recommendation language that elides alternatives, no probabilistic claims framed as guarantees, explicit override-encouragement framing required).
- **Bedrock model IDs change over time.** Some regions require cross-region inference profile IDs (prefixed `us.` or `eu.`). The IDs below are reasonable defaults; verify in the Bedrock console for your region before running.
- **All patients, trajectories, actions, narratives, and outcomes in the example are synthetic.** Do not treat any specific patient_id, trajectory_id, recommendation_id, or narrative as real. A production system ingests from real EHR, FHIR, claims, lab, pharmacy, and registry feeds under BAA.
- **The example collapses Step Functions, Lambda, EventBridge, SageMaker Endpoints, and Bedrock into a single Python file for readability.** In production these are separate workflow stages with their own error handling, IAM, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Model IDs, table names, S3 buckets, validator thresholds, OPE bootstrap iterations, OOD thresholds, and the regime catalog are the knobs you would change between environments.

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
import numpy as np
import pandas as pd
from botocore.config import Config
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import NearestNeighbors

# Structured logging. In production, ship JSON-formatted records to
# CloudWatch Logs Insights. Never log a raw (patient_id, trajectory_id,
# state, action, reward) join. The row implicitly identifies the
# patient, the active condition list, the historical care path, and
# the recommended next action; the trajectory and recommendation
# tables are clinical-record-equivalent PHI.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, Bedrock, Kinesis,
# S3, EventBridge, and SageMaker. Recommendation generation runs on
# the order of seconds end-to-end; transient throttling from any one
# service should not fail the whole recommendation.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
kinesis_client = boto3.client("kinesis", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
eventbridge_client = boto3.client("events", config=BOTO3_RETRY_CONFIG)
cloudwatch_client = boto3.client("cloudwatch", config=BOTO3_RETRY_CONFIG)
sagemaker_client = boto3.client("sagemaker", config=BOTO3_RETRY_CONFIG)

# --- Bedrock Model Configuration ---
# Two distinct LLM use cases. Clinician briefings go to a Sonnet-class
# model because the prompt is long-context (full recommendation record
# plus alternatives plus similar trajectories plus guideline references)
# and the fact-grounding validator is strict; the larger model gives a
# better first-pass-pass rate. Patient-facing summaries can use a
# Haiku-class model for cost efficiency where reading-level allows.
CLINICIAN_NARRATIVE_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
PATIENT_NARRATIVE_MODEL_ID    = "anthropic.claude-3-5-haiku-20241022-v1:0"
# TODO (TechWriter): Code review NOTE Finding 10.
# PATIENT_NARRATIVE_MODEL_ID is defined but never referenced
# because the patient-facing narrative path is not implemented in
# the demo. Either remove the constant with a comment that the
# patient path is in Gap to Production, or add a minimal patient-
# facing narrative function (templated only is fine) so the
# constant is wired up to a real call site.

# --- DynamoDB Table Names ---
# Five tables. Keep them separate so access patterns stay clean and
# IAM scoping is precise:
#   1. regime-catalog:        regime spec, state def, action catalog,
#                              reward function, eligibility predicates,
#                              model risk tier, governance status
#   2. trajectory-metadata:   per-(patient_id, regime_id) pointer to
#                              S3 trajectory blob plus operational state
#   3. recommendation-records: per-decision recommendation with
#                              rationale, alternatives, OOD flag,
#                              similar trajectories, regime version,
#                              clinician's eventual action
#   4. regime-versions:       SageMaker Model Registry mirror with
#                              OPE results, governance approval, and
#                              effective dates
#   5. surveillance-metrics:  per-(regime_id, surveillance_window)
#                              adherence, drift, cohort metrics
REGIME_CATALOG_TABLE        = "regime-catalog"
TRAJECTORY_METADATA_TABLE   = "trajectory-metadata"
RECOMMENDATION_RECORDS_TABLE = "recommendation-records"
REGIME_VERSIONS_TABLE       = "regime-versions"
SURVEILLANCE_METRICS_TABLE  = "surveillance-metrics"
SURVEILLANCE_ALERTS_TABLE   = "surveillance-alerts"

# --- S3 Buckets ---
# Production: each bucket has its own KMS key and bucket policy.
# Replace placeholder names with your account's buckets.
DTR_DATA_LAKE_BUCKET            = "dtr-data-lake"
DTR_TRAJECTORIES_BUCKET         = "dtr-trajectories"
DTR_OPE_OUTPUTS_BUCKET          = "dtr-ope"
DTR_RECOMMENDATION_ARCHIVE_BUCKET = "dtr-recommendation-archives"
DTR_SURVEILLANCE_BUCKET         = "dtr-surveillance"
DTR_GOVERNANCE_BUCKET           = "dtr-governance"

# --- Kinesis ---
# Same event-bus pattern as Recipes 4.4 through 4.9, with new event
# types specific to this recipe: trajectory_built, behavior_policy_estimated,
# regime_trained, ope_completed, recommendation_generated,
# action_taken, surveillance_alert_raised, regime_version_promoted.
DTR_EVENTS_STREAM_NAME = "dtr-events"

# --- EventBridge ---
EVENTBRIDGE_BUS_NAME = "dtr-bus"

# --- SageMaker Model Registry ---
SAGEMAKER_MODEL_PACKAGE_GROUP = "dtr-regime-models"

# --- Run Configuration ---
POLICY_VERSION = "dtr-policy-v0.1"

# Validator regeneration attempts before falling back to templated
# narrative. The regime narrative is higher-stakes than typical
# clinical decision support; the fallback is a structured, prosaic
# rendering of the recommendation record without LLM narration.
MAX_REGENERATION_ATTEMPTS = 2

# OPE bootstrap iterations. 1000 is a reasonable demo default;
# production typically uses 2000-5000 for tighter intervals.
OPE_BOOTSTRAP_ITERATIONS = 1000

# Behavior-policy calibration thresholds. ECE = expected calibration
# error. The cohort threshold is stricter; equity instrumentation
# fails closed.
BEHAVIOR_POLICY_ECE_THRESHOLD          = 0.10
BEHAVIOR_POLICY_COHORT_ECE_THRESHOLD   = 0.15

# OOD thresholds. The k-NN extrapolation distance threshold is
# regime-specific; the demo uses a single global default. Production
# tunes per cohort and per regime risk tier.
OOD_KNN_DISTANCE_THRESHOLD       = 2.0
OOD_PROPENSITY_FLOOR             = 0.02
OOD_PROPENSITY_CEILING           = 0.98

# Similar-trajectory retrieval. k-anonymity threshold for the
# similar-trajectory retrieval cohort: below this size, no individual
# trajectories are surfaced (only aggregate summaries).
SIMILAR_TRAJECTORY_COUNT          = 5
K_ANONYMITY_THRESHOLD            = 5
MIN_COHORT_SAMPLE                = 50

# Cohort fairness threshold for the surveillance pipeline. A regime
# whose cohort-stratified value (or wider intervals) differs from the
# overall by more than this triggers a surveillance alert.
COHORT_DISPARITY_ALERT_THRESHOLD = 0.10

# Drift detection threshold. Calibration drift between the OPE
# baseline and observed outcomes that exceeds this triggers an
# unscheduled retraining cycle via EventBridge.
RETRAINING_TRIGGER_THRESHOLD     = 0.15

# Trajectory minimums. Trajectories shorter than this contribute
# limited signal and are recorded but excluded from training.
MIN_TRAJECTORY_LENGTH = 3

# CloudWatch namespace for regime metrics. Slice by regime_id,
# audience, validator outcome, and cohort axis to catch subgroup drift.
METRIC_NAMESPACE = "DynamicTreatmentRegime"
```

---

## Reference Data: Synthetic Regime Catalog and Trajectory Generator

A small regime catalog used by the example: one regime, the diabetes / CKD stepwise-therapy regime that fits Sara's profile from the recipe's opening narrative. Production loads from the `regime-catalog` DynamoDB table, fed by a regime-governance committee through a curation UI and versioned. Each regime has cohort overrides, evidence references, contraindications, eligibility predicates, and provenance.

```python
# A single synthetic regime spec. Production maintains many regimes
# per clinical area, with cohort overrides, evidence references,
# versioning, and governance metadata. The state schema, action
# catalog, reward function, and eligibility predicates are the
# committee-curated artifacts; everything else flows from them.
SAMPLE_REGIME = {
    "regime_id":         "diabetes_ckd_stepwise_v3",
    "version":           "3.2.1",
    "clinical_area":     "diabetes_with_ckd",
    "model_risk_tier":   "moderate",
    "governance_status": "approved_for_pilot",
    # State schema. The features used in the state vector at each
    # decision point. Production: dozens to hundreds of features
    # depending on regime complexity. The demo uses six.
    "state_schema": [
        "current_a1c",
        "current_egfr",
        "current_acr",
        "current_systolic_bp",
        "comorbidity_tier",
        "polypharmacy_count",
    ],
    # Action catalog. The exhaustive set of actions the regime can
    # recommend. Out-of-catalog clinician actions are recorded as
    # such; high out-of-catalog rates signal catalog inadequacy.
    "action_catalog": [
        {"action_id": "add_sglt2_dapagliflozin_10_mg_daily",
          "description": "Add SGLT2 inhibitor",
          "burden_score": 1.5},
        {"action_id": "increase_semaglutide_to_2_mg_weekly",
          "description": "Intensify GLP-1 dose",
          "burden_score": 1.0},
        {"action_id": "add_basal_insulin_glargine",
          "description": "Add basal insulin",
          "burden_score": 3.5},
        {"action_id": "add_dpp4_sitagliptin_100_mg_daily",
          "description": "Add DPP-4 inhibitor",
          "burden_score": 1.0},
        {"action_id": "no_change_with_lifestyle_intensification",
          "description": "No change; reinforce lifestyle",
          "burden_score": 0.5},
    ],
    # Reward function. The weighted combination of outcomes the
    # regime optimizes. The committee's most consequential decision;
    # encodes program tradeoffs (effectiveness vs harm vs burden).
    # Demo uses simple linear weights; production may use richer
    # nonlinear reward shapes with explicit per-cohort overrides.
    "reward_function": {
        "weights": {
            "a1c_reduction":           1.0,
            "egfr_stabilization":      1.5,
            "no_severe_hypoglycemia":  0.8,
            "no_aki":                  1.0,
            "burden":                 -0.4,
        },
        "rationale": (
            "Weights reflect the program's tradeoffs: renal protection "
            "is the headline goal (eGFR stabilization weighted highest), "
            "with A1c reduction and harm avoidance close behind, and "
            "burden as a small but non-zero penalty. Approved by the "
            "regime governance committee 2026-03-15."
        ),
        "version": "rf-2026-q1",
    },
    # Decision-point cadence. Quarterly for chronic disease; some
    # regimes use encounter-aligned or event-triggered cadences.
    "decision_point_cadence": "quarterly",
    # Eligibility predicates. Patients must satisfy all of these to
    # receive a recommendation. Predicate failures return an explicit
    # "not eligible" response with the failing predicate identified.
    "eligibility_predicates": [
        {"predicate_id": "active_t2dm",
          "description": "T2DM on the active condition list"},
        {"predicate_id": "egfr_above_30",
          "description": "Most recent eGFR >= 30"},
        {"predicate_id": "no_active_pregnancy",
          "description": "No active pregnancy diagnosis"},
        {"predicate_id": "regime_consent_on_file",
          "description": "Patient has consented to regime-based "
                          "decision support"},
    ],
    # Horizon. Quarterly cadence with a 4-decision-point horizon
    # gives a 1-year horizon. Production matches the horizon to the
    # outcome timescale relevant for the clinical area.
    "horizon_decision_points": 4,
    # Behavior-policy method. Logistic regression for the small
    # action space; gradient-boosted trees for richer state spaces.
    "behavior_policy_method": "logistic_regression",
    # Q-learning function class. GradientBoostingRegressor for the
    # demo; a small neural network is also reasonable.
    "q_function_class": "gradient_boosting",
    # Whether to also train offline RL and A-learning. Production
    # uses multi-method triangulation; the demo notes the placeholders.
    "use_offline_rl": False,
    "use_a_learning": False,
    "use_msm":        False,
    # Cohort axes used for stratified OPE and surveillance. Same
    # axes as Chapter 4 plus regime-specific axes.
    "cohort_axes": [
        "race_ethnicity",
        "language",
        "age_band",
        "comorbidity_tier",
    ],
    "effective_dates": {
        "start": "2026-04-01",
        "end":   None,
    },
}

# Cohort axes for fairness instrumentation, mirrored across the
# pipeline.
COHORT_AXES = ["race_ethnicity", "language", "age_band",
                "comorbidity_tier"]
```

A small synthetic trajectory generator that produces a longitudinal cohort with plausible state transitions and clinician decisions. Production does not generate trajectories; it ingests them from the trajectory pipeline that wraps real EHR / claims / lab data.

```python
def generate_synthetic_trajectories(n_patients: int = 200,
                                       horizon: int = 4,
                                       seed: int = 42) -> list:
    """
    Generate n_patients synthetic trajectories with horizon decision
    points each. Each trajectory is a list of step dicts:
        {decision_point_index, state, action_id, reward,
         next_state, censored, cohort_features, patient_id}

    The generator includes cohort axes with realistic representation
    (whites overrepresented, Spanish-speaking underrepresented) so
    the cohort-stratified OPE has heterogeneous data.

    NEVER ship a real model trained on synthetic data into
    production. The generator is for example purposes only.
    """
    rng = np.random.default_rng(seed)
    trajectories = []
    n_actions = len(SAMPLE_REGIME["action_catalog"])

    # Cohort distributions. Approximate something like a multi-
    # specialty health system's distribution for the demo.
    race_ethnicity_choices = ["white_non_hispanic", "black_non_hispanic",
                                "hispanic", "asian", "other_or_unknown"]
    race_ethnicity_probs   = [0.62, 0.20, 0.13, 0.04, 0.01]
    language_choices       = ["english", "spanish", "other"]
    language_probs         = [0.86, 0.10, 0.04]
    age_band_choices       = ["under_50", "50_to_59", "60_to_69",
                                "70_plus"]
    age_band_probs         = [0.22, 0.34, 0.30, 0.14]

    for i in range(n_patients):
        patient_id = f"pat-syn-{i:06d}"
        cohort = {
            "race_ethnicity":  rng.choice(race_ethnicity_choices,
                                            p=race_ethnicity_probs),
            "language":        rng.choice(language_choices,
                                            p=language_probs),
            "age_band":        rng.choice(age_band_choices,
                                            p=age_band_probs),
            "comorbidity_tier": int(rng.integers(low=1, high=5)),
        }

        # Initial state. T2DM with CKD3b plausible ranges.
        state = np.array([
            float(rng.normal(loc=8.2, scale=1.0)),     # current_a1c
            float(rng.normal(loc=42.0, scale=8.0)),    # current_egfr
            float(rng.normal(loc=80.0, scale=40.0)),   # current_acr
            float(rng.normal(loc=130.0, scale=12.0)),  # current_systolic_bp
            float(cohort["comorbidity_tier"]),          # comorbidity_tier
            float(rng.integers(low=4, high=12)),       # polypharmacy_count
        ])

        steps = []
        for dp_idx in range(horizon):
            # Behavior policy: clinicians historically chose between
            # the five actions with state-dependent probabilities.
            # The probabilities are biased so the cohort-stratified
            # OPE has structural variation (e.g., less SGLT2 use
            # historically in spanish-language patients due to
            # access patterns). This intentionally encodes the
            # Obermeyer-style disparity for the demo to surface.
            action_logits = np.array([
                # add SGLT2: favored when eGFR low and ACR high
                0.6 + 0.05 * (50.0 - state[1]) + 0.005 * state[2],
                # increase GLP-1: favored when A1c high
                0.4 + 0.4 * (state[0] - 7.5),
                # add basal insulin: favored at very high A1c
                -0.6 + 0.6 * max(0.0, state[0] - 9.0),
                # add DPP-4: rarely first choice
                -0.5,
                # no change: when state is in good range
                0.4 + 0.3 * max(0.0, 7.5 - state[0]),
            ])
            # Cohort-driven access disparity: spanish-language
            # patients historically saw less SGLT2 prescribing.
            if cohort["language"] == "spanish":
                action_logits[0] -= 0.5
            # Cohort-driven preference: older patients less often
            # started on basal insulin in the demo data.
            if cohort["age_band"] == "70_plus":
                action_logits[2] -= 0.3
            action_probs = _softmax(action_logits)
            action_idx = int(rng.choice(n_actions, p=action_probs))

            # State transition: SGLT2 stabilizes eGFR and lowers
            # A1c modestly; GLP-1 lowers A1c more; insulin lowers
            # A1c the most but with hypoglycemia and weight risk;
            # DPP-4 lowers A1c modestly; no change drifts upward.
            new_state = state.copy()
            severe_hypo  = 0.0
            aki          = 0.0
            if action_idx == 0:    # SGLT2
                new_state[0] += rng.normal(loc=-0.6, scale=0.3)
                new_state[1] += rng.normal(loc=0.5, scale=0.8)
                aki           = float(rng.binomial(1, 0.02))
            elif action_idx == 1:  # GLP-1 intensify
                new_state[0] += rng.normal(loc=-0.4, scale=0.3)
                new_state[1] += rng.normal(loc=-0.3, scale=0.8)
            elif action_idx == 2:  # basal insulin
                new_state[0] += rng.normal(loc=-0.9, scale=0.4)
                new_state[1] += rng.normal(loc=-0.4, scale=0.8)
                severe_hypo   = float(rng.binomial(1, 0.05))
            elif action_idx == 3:  # DPP-4
                new_state[0] += rng.normal(loc=-0.3, scale=0.3)
                new_state[1] += rng.normal(loc=-0.4, scale=0.8)
            else:                   # no change
                new_state[0] += rng.normal(loc=0.1, scale=0.3)
                new_state[1] += rng.normal(loc=-0.6, scale=0.8)

            new_state[1] = max(15.0, min(120.0, new_state[1]))
            new_state[0] = max(5.0, min(15.0, new_state[0]))

            # Reward: weighted combination of outcomes. Production
            # uses the regime's reward_function spec; the demo
            # mirrors it with the same weights.
            a1c_reduction          = float(state[0] - new_state[0])
            egfr_stabilization     = float(new_state[1] - state[1])
            burden                 = float(SAMPLE_REGIME["action_catalog"][action_idx]["burden_score"])
            reward = (
                  1.0 * a1c_reduction
                + 1.5 * egfr_stabilization
                + 0.8 * (1.0 - severe_hypo)
                + 1.0 * (1.0 - aki)
                - 0.4 * burden
            )

            # Modest censoring: a small fraction of trajectories are
            # truncated each step (LTFU, switched insurer, etc.).
            censored = bool(rng.binomial(1, 0.04))

            steps.append({
                "decision_point_index":  dp_idx,
                "state":                 state.tolist(),
                "action_id":             SAMPLE_REGIME["action_catalog"][action_idx]["action_id"],
                "action_idx":            action_idx,
                "reward":                float(reward),
                "next_state":            new_state.tolist(),
                "censored":              censored,
                "cohort_features":       cohort,
                "patient_id":            patient_id,
            })
            if censored:
                break
            state = new_state

        trajectories.append(steps)

    return trajectories


def _softmax(x: np.ndarray) -> np.ndarray:
    """Numerically stable softmax used by the synthetic generator."""
    x = x - x.max()
    e = np.exp(x)
    return e / e.sum()
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
    failure never breaks recommendation generation. Metric publishing
    is best-effort observability, not a correctness boundary. Filters
    out None-valued dimensions: CloudWatch rejects them and the
    rejected request loses the rest of the metric data too.
    """
    # TODO (TechWriter): Code review NOTE Finding 9. _emit_metric
    # is defined but never called. Either wire it into the load-
    # bearing observation points (recommendation served, validator
    # outcome, cohort follow-rate disparity, OOD-flag rate, drift
    # severity) or remove the helper with a comment in the
    # surveillance section pointing to CloudWatch as a production
    # gap. The recipe text describes CloudWatch alarms as load-
    # bearing observability; the helper is well-formed but unused.
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


def _make_recommendation_id() -> str:
    """
    Opaque recommendation identifier.

    NOTE: A PHI-safe id. Production-equivalent guidance: never embed
    plain-text patient_id, regime_id, decision_point_id, or other
    structured fields into identifiers that travel in URLs, EHR
    responses, event payloads, or logs. Use UUIDs or HMAC-SHA256
    over the composite with a per-environment secret. Mirror the
    language flagged in 4.4 through 4.9.
    """
    return f"rec-{uuid.uuid4().hex[:16]}"


def _make_trajectory_id() -> str:
    return f"traj-{uuid.uuid4().hex[:16]}"


def _make_alert_id() -> str:
    return f"alert-{uuid.uuid4().hex[:16]}"


def _make_anonymized_traj_id(idx: int) -> str:
    """
    Stable anonymized identifier for similar-trajectory retrieval.
    Production hashes (patient_id, retrieval_run_id) with a per-
    environment secret to produce non-reversible IDs that can be
    surfaced to clinicians without re-identification risk.
    """
    return f"anonymized_{idx:03d}"


def _redact_for_llm(payload: dict) -> dict:
    """
    Strip patient and clinician identifiers from a payload before
    sending to an LLM. The LLM does not need them, and stripping at
    the boundary limits any vendor-side logging exposure. Bedrock
    service terms commit to not training on prompts, but defense-in-
    depth still applies.
    """
    redacted = json.loads(json.dumps(payload, default=str))
    for field in ("patient_id", "clinician_id", "recommendation_id",
                   "decision_point_id", "trajectory_id"):
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


def _band_int(value: int, thresholds: list) -> str:
    """Coarse banding for metric dimensions."""
    for t in thresholds:
        if value < t:
            return f"under_{t}"
    return f"{thresholds[-1]}_plus"


def _action_id_to_idx(action_id: str) -> int:
    """Map an action_id string to its index in the regime's action catalog."""
    for i, a in enumerate(SAMPLE_REGIME["action_catalog"]):
        if a["action_id"] == action_id:
            return i
    return -1
```

---

## Step 1: Build Trajectories from Source Clinical Data

*The pseudocode calls this `build_trajectories(refresh_window)`. Trajectories are the substrate of dynamic-treatment-regime work; quality issues here propagate to every downstream model. Skip the careful identification of decision points, the precise state construction at each point, and the explicit handling of censoring, and the resulting trajectories produce policies that look defensible and are not.*

```python
def build_trajectories(refresh_window: dict,
                          source_trajectories: list,
                          regime: dict) -> dict:
    """
    Build the per-patient trajectory records and persist them.

    refresh_window:    {start_date, end_date, cohort_filter}
    source_trajectories: list of step lists from the source pipeline.
                          In production: the output of the clinical-
                          data ETL that walks EHR, claims, lab,
                          pharmacy, and outcome events. In the demo:
                          generate_synthetic_trajectories above.
    regime:             the regime spec from the regime catalog

    Persists each trajectory to S3 (Parquet in production, JSON in
    the demo for readability) and writes operational metadata to
    DynamoDB. Returns counts plus the in-memory trajectory list for
    downstream steps.
    """
    persisted = []
    short_trajectories = 0
    out_of_catalog_count = 0
    metadata_table = dynamodb.Table(TRAJECTORY_METADATA_TABLE)

    for steps in source_trajectories:
        if not steps:
            continue
        patient_id = steps[0]["patient_id"]

        # Filter out trajectories that are too short to contribute
        # meaningful signal. They are recorded for inventory but
        # excluded from training.
        if len(steps) < MIN_TRAJECTORY_LENGTH:
            short_trajectories += 1
            continue

        # Each step must have an action that maps to the regime's
        # action catalog. Out-of-catalog steps are recorded; high
        # out-of-catalog rates surface to the catalog governance
        # committee as a signal that the catalog may need expansion.
        normalized_steps = []
        for step in steps:
            action_idx = _action_id_to_idx(step["action_id"])
            if action_idx < 0:
                out_of_catalog_count += 1
                normalized_steps.append({
                    **step,
                    "out_of_catalog": True,
                })
                continue
            normalized_steps.append({
                **step,
                "action_idx":     action_idx,
                "out_of_catalog": False,
            })

        trajectory_id = _make_trajectory_id()
        # Persist the trajectory blob. Production: Parquet partitioned
        # by regime_id and patient_cohort. Demo: JSON for readability.
        try:
            s3_client.put_object(
                Bucket=DTR_TRAJECTORIES_BUCKET,
                Key=(f"{regime['regime_id']}/{patient_id}/"
                     f"{trajectory_id}.json"),
                Body=json.dumps(normalized_steps,
                                 default=str).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist trajectory blob %s/%s: %s",
                patient_id, trajectory_id, exc,
            )

        # Operational metadata. Hot path uses DynamoDB; the immutable
        # S3 blob is the audit system of record.
        last_step = normalized_steps[-1]
        metadata_record = {
            "patient_id":                 patient_id,
            "regime_id":                  regime["regime_id"],
            "trajectory_id":              trajectory_id,
            "last_decision_point_index":  last_step["decision_point_index"],
            "current_state":              last_step.get(
                "next_state", last_step.get("state")),
            "censoring_status":           bool(last_step.get(
                "censored", False)),
            "trajectory_length":          len(normalized_steps),
            "out_of_catalog_count":       sum(
                1 for s in normalized_steps if s.get("out_of_catalog")),
            "trajectory_uri":             (f"s3://{DTR_TRAJECTORIES_BUCKET}/"
                                            f"{regime['regime_id']}/"
                                            f"{patient_id}/{trajectory_id}.json"),
            "last_updated":               _now_iso(),
        }
        try:
            metadata_table.put_item(
                Item=_to_decimal_dict(metadata_record),
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist trajectory metadata %s/%s: %s",
                patient_id, trajectory_id, exc,
            )

        persisted.append(normalized_steps)

    try:
        kinesis_client.put_record(
            StreamName=DTR_EVENTS_STREAM_NAME,
            PartitionKey=regime["regime_id"],
            Data=json.dumps({
                "event_type":           "trajectory_built",
                "regime_id":            regime["regime_id"],
                "refresh_window":       refresh_window,
                "trajectory_count":     len(persisted),
                "short_trajectory_count": short_trajectories,
                "out_of_catalog_count": out_of_catalog_count,
                "timestamp":            _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return {
        "trajectories":           persisted,
        "trajectory_count":       len(persisted),
        "short_trajectory_count": short_trajectories,
        "out_of_catalog_count":   out_of_catalog_count,
    }
```

---

## Step 2: Estimate the Behavior Policy

*The pseudocode calls this `estimate_behavior_policy(trajectories, regime)`. Off-policy evaluation requires the propensity of the historical clinician to choose each action given the state. A poorly-estimated behavior policy produces poor importance weights and poor evaluations. The behavior policy is a model in its own right that requires validation, calibration, and monitoring; skip its discipline and the OPE results are not trustworthy.*

```python
def estimate_behavior_policy(trajectories: list, regime: dict) -> dict:
    """
    Fit a multinomial classifier predicting action from state. Validate
    overall and cohort-stratified calibration. Return the model plus
    the calibration results.
    """
    # Step 2A: assemble the (state, action) training pairs from the
    # trajectories. Skip censored and out-of-catalog steps.
    rows = []
    for steps in trajectories:
        for step in steps:
            if step.get("censored") or step.get("out_of_catalog"):
                continue
            rows.append({
                "state":        np.array(step["state"]),
                "action_idx":   step["action_idx"],
                "cohort":       step["cohort_features"],
            })
    if not rows:
        raise ValueError("No usable rows for behavior-policy training")

    X = np.stack([r["state"] for r in rows])
    y = np.array([r["action_idx"] for r in rows])

    # Step 2B: fit the behavior-policy estimator. Logistic regression
    # for the small action catalog; gradient-boosted trees or a small
    # neural network for richer state spaces or larger action sets.
    # Production: hyperparameter search and cross-validation; the
    # demo trains a single fit.
    model = LogisticRegression(max_iter=500, multi_class="auto",
                                  solver="lbfgs")
    model.fit(X, y)

    # Step 2C: validate calibration overall and per cohort axis.
    # Production: a richer calibration analysis (reliability diagrams,
    # ECE per bin); the demo uses simple expected-calibration-error.
    overall_ece = _compute_ece(model, X, y)
    cohort_results = {}
    for axis in regime["cohort_axes"]:
        axis_results = {}
        for value in sorted({r["cohort"][axis] for r in rows}):
            mask = np.array([r["cohort"][axis] == value for r in rows])
            if mask.sum() < 30:
                axis_results[value] = {
                    "sample_size": int(mask.sum()),
                    "ece":         None,
                    "evaluable":   False,
                    "flag":        "insufficient_data",
                }
                continue
            cohort_ece = _compute_ece(model, X[mask], y[mask])
            axis_results[value] = {
                "sample_size": int(mask.sum()),
                "ece":         float(cohort_ece),
                "evaluable":   True,
            }
        cohort_results[axis] = axis_results

    # Step 2D: enforce calibration thresholds. Overall failure is a
    # blocker; cohort-specific failure is also a blocker because OPE
    # built on miscalibrated importance weights produces misleading
    # equity assessments. The demo logs and continues for illustration;
    # production raises an exception that fails the training cycle.
    blocking = []
    if overall_ece > BEHAVIOR_POLICY_ECE_THRESHOLD:
        blocking.append(f"overall_ece={overall_ece:.3f}")
    for axis, axis_results in cohort_results.items():
        for value, result in axis_results.items():
            if result.get("ece") is None:
                continue
            if result["ece"] > BEHAVIOR_POLICY_COHORT_ECE_THRESHOLD:
                blocking.append(
                    f"{axis}={value} ece={result['ece']:.3f}")

    behavior_policy = {
        "model":             model,
        "version":           f"bp-{regime['regime_id']}-"
                              f"{datetime.datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "training_rows":     int(len(rows)),
        "overall_ece":       float(overall_ece),
        "cohort_results":    cohort_results,
        "calibration_blocking": blocking,
    }

    # Step 2E: persist a serialized snapshot for the audit trail.
    # Production pickles the sklearn model to S3 alongside the
    # calibration metadata. The demo does not pickle to S3; the model
    # stays in-memory for downstream OPE.
    try:
        s3_client.put_object(
            Bucket=DTR_OPE_OUTPUTS_BUCKET,
            Key=(f"{regime['regime_id']}/behavior_policy/"
                  f"{behavior_policy['version']}.json"),
            Body=json.dumps({
                "version":          behavior_policy["version"],
                "training_rows":    behavior_policy["training_rows"],
                "overall_ece":      behavior_policy["overall_ece"],
                "cohort_results":   cohort_results,
                "calibration_blocking": blocking,
                "trained_at":       _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to persist behavior-policy metadata: %s", exc)

    try:
        kinesis_client.put_record(
            StreamName=DTR_EVENTS_STREAM_NAME,
            PartitionKey=regime["regime_id"],
            Data=json.dumps({
                "event_type":   "behavior_policy_estimated",
                "regime_id":    regime["regime_id"],
                "version":      behavior_policy["version"],
                "overall_ece":  behavior_policy["overall_ece"],
                "blocking_count": len(blocking),
                "timestamp":    _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return behavior_policy


def _compute_ece(model, X: np.ndarray, y: np.ndarray,
                   n_bins: int = 10) -> float:
    """
    Expected calibration error for a multinomial classifier.

    Bins predictions by the predicted probability of the chosen
    action; computes per-bin gap between predicted probability and
    empirical accuracy; returns weighted average.

    Production: reliability diagrams plus per-class calibration
    rather than this simplified scalar.
    """
    probs = model.predict_proba(X)
    pred_class = probs.argmax(axis=1)
    pred_prob = probs.max(axis=1)
    correct = (pred_class == y).astype(float)

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (pred_prob > lo) & (pred_prob <= hi)
        if mask.sum() == 0:
            continue
        bin_acc = float(correct[mask].mean())
        bin_conf = float(pred_prob[mask].mean())
        ece += (mask.sum() / len(y)) * abs(bin_acc - bin_conf)
    return ece
```

---

## Step 3: Train the Regime with Q-learning (Backward Induction)

*The pseudocode calls this `train_regime(trajectories, behavior_policy, regime)`. Method diversity is the discipline; using only one estimator and shipping it produces a regime that has not been cross-validated against the alternative methodological choices. Skip the multi-method approach and the resulting regime is no more reliable than a single-method ML model. The demo trains Q-learning only and notes where offline RL and A-learning would slot in.*

```python
def train_regime(trajectories: list,
                   behavior_policy: dict,
                   regime: dict) -> dict:
    """
    Train candidate regimes. The demo uses Q-learning with backward
    induction over the horizon. Production also runs offline RL
    (CQL / IQL) and A-learning or outcome-weighted learning as
    cross-validation; agreement among methods is the trustworthiness
    signal.
    """
    candidate_regimes = []

    # Step 3A: target trial emulation specification. The hypothetical
    # sequential trial protocol must be specified before training
    # begins: eligibility, treatment strategies under comparison,
    # outcome definition, censoring, follow-up. The protocol is
    # documented in the regime catalog so the OPE results can be
    # interpreted against an explicit hypothetical experiment. The
    # demo records a stub protocol; production loads from a
    # protocol-versioning store.
    protocol = {
        "regime_id":         regime["regime_id"],
        "protocol_version":  "2.1",
        "eligibility":       [p["predicate_id"]
                                 for p in regime["eligibility_predicates"]],
        "treatment_strategies": [a["action_id"]
                                    for a in regime["action_catalog"]],
        "outcome_definition": regime["reward_function"],
        "horizon":            regime["horizon_decision_points"],
        "censoring_handling": "ipcw_demo_stub",
    }
    try:
        s3_client.put_object(
            Bucket=DTR_OPE_OUTPUTS_BUCKET,
            Key=(f"{regime['regime_id']}/protocol/"
                  f"protocol_v{protocol['protocol_version']}.json"),
            Body=json.dumps(protocol, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning("Failed to persist protocol: %s", exc)

    # Step 3B: Q-learning with backward induction. At each decision
    # point t, fit a regression of total cumulative reward (from t to
    # the end of the horizon, assuming the optimal policy is followed
    # at all later steps) on (state_t, action_t). Start at the last
    # decision point in the horizon and work backward.
    q_models, q_metadata = _train_q_learning_backward(
        trajectories, regime,
    )
    candidate_regimes.append({
        "method":  "q_learning",
        "version": f"q-{regime['regime_id']}-"
                    f"{datetime.datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "models":  q_models,
        "metadata": q_metadata,
    })

    # Step 3C-3E: placeholders for offline RL, A-learning, and MSM.
    # Production routes here when the regime catalog turns the flags
    # on. The demo notes the placeholders explicitly so reviewers
    # see where they would slot in.
    if regime.get("use_offline_rl"):
        logger.info(
            "TODO: train offline RL (CQL/IQL/BCQ). Demo skips. "
            "Production: d3rlpy or RLlib offline RL.")
    if regime.get("use_a_learning"):
        logger.info("TODO: train A-learning. Demo skips.")
    if regime.get("use_msm"):
        logger.info(
            "TODO: estimate MSM policy values. Demo skips.")

    # Step 3F: register all candidate regimes in the SageMaker Model
    # Registry. Each candidate carries its method, training data
    # window, behavior-policy version, and protocol version. The
    # demo writes a record to DynamoDB; production calls
    # SageMaker.create_model_package on a serialized model artifact
    # in S3.
    versions_table = dynamodb.Table(REGIME_VERSIONS_TABLE)
    for cand in candidate_regimes:
        version_record = {
            "regime_id":               regime["regime_id"],
            "version":                 cand["version"],
            "method":                  cand["method"],
            "behavior_policy_version": behavior_policy["version"],
            "protocol_version":        protocol["protocol_version"],
            "governance_status":       "pending_ope",
            "trained_at":              _now_iso(),
        }
        try:
            versions_table.put_item(Item=_to_decimal_dict(version_record))
        except Exception as exc:
            logger.warning(
                "Failed to persist regime version %s: %s",
                cand["version"], exc,
            )

    try:
        kinesis_client.put_record(
            StreamName=DTR_EVENTS_STREAM_NAME,
            PartitionKey=regime["regime_id"],
            Data=json.dumps({
                "event_type":     "regime_trained",
                "regime_id":      regime["regime_id"],
                "candidate_count": len(candidate_regimes),
                "methods":        [c["method"] for c in candidate_regimes],
                "timestamp":      _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return {
        "candidates": candidate_regimes,
        "protocol":   protocol,
    }


def _train_q_learning_backward(trajectories: list,
                                  regime: dict) -> tuple:
    """
    Q-learning with backward induction.

    For t = T-1, T-2, ..., 0 fit Q_t(s, a) = E[reward_t + V_{t+1}(s')]
    where V_{t+1}(s') = max_a Q_{t+1}(s', a). At t = T-1 there is no
    future, so Q is just E[reward_T-1 | s, a].

    Returns a list of fitted regressors (one per decision point) and
    metadata.
    """
    horizon = regime["horizon_decision_points"]
    n_actions = len(regime["action_catalog"])

    # Group steps by decision-point index. A trajectory contributes
    # one row at each decision point it covers; censored or
    # out-of-catalog steps are dropped from training.
    rows_by_dp = {t: [] for t in range(horizon)}
    for steps in trajectories:
        for step in steps:
            if step.get("censored") or step.get("out_of_catalog"):
                continue
            t = step["decision_point_index"]
            if t >= horizon:
                continue
            rows_by_dp[t].append(step)

    q_models = [None] * horizon

    # Backward induction. Start at the last decision point.
    for t in range(horizon - 1, -1, -1):
        rows = rows_by_dp[t]
        if not rows:
            q_models[t] = None
            continue
        X = np.stack([
            np.concatenate([np.array(r["state"]),
                              _action_one_hot(r["action_idx"], n_actions)])
            for r in rows
        ])
        # Target: immediate reward plus the discounted future value.
        # No discounting in the demo (gamma = 1).
        targets = []
        for r in rows:
            future_value = 0.0
            if t + 1 < horizon and q_models[t + 1] is not None:
                # Compute V_{t+1}(s') = max_a Q_{t+1}(s', a)
                next_state = np.array(r["next_state"])
                future_value = max(
                    float(q_models[t + 1].predict(np.concatenate([
                        next_state, _action_one_hot(a, n_actions),
                    ]).reshape(1, -1))[0])
                    for a in range(n_actions)
                )
            targets.append(r["reward"] + future_value)
        targets = np.array(targets)

        model = GradientBoostingRegressor(
            n_estimators=120, max_depth=3, learning_rate=0.05,
            random_state=int(t),
        )
        model.fit(X, targets)
        q_models[t] = model

    metadata = {
        "horizon":          horizon,
        "rows_per_dp":      {t: len(rows_by_dp[t]) for t in range(horizon)},
        "trained_dps":      [t for t, m in enumerate(q_models)
                                if m is not None],
    }
    return q_models, metadata


def _action_one_hot(action_idx: int, n_actions: int) -> np.ndarray:
    """One-hot encode an action for the Q regression input."""
    v = np.zeros(n_actions, dtype=float)
    v[action_idx] = 1.0
    return v


def _q_policy(q_models: list, state: np.ndarray, regime: dict) -> dict:
    """
    Evaluate the Q-learning policy at a state at decision point t.
    Returns recommended_action_idx, per-action Q values, and the
    estimated value of the recommended action.

    The demo uses the Q model at decision point 0 for serving;
    production picks the appropriate decision-point Q model from
    the patient's trajectory state.
    """
    # TODO (TechWriter): Code review WARNING Finding 2. Thread
    # decision_point_index into _q_policy and have the OPE
    # estimators (DR / IS / FQE) pass each step's
    # decision_point_index when evaluating. Q-learning with backward
    # induction trains one Q model per horizon index; using
    # q_models[0] for every step silently evaluates a stationary
    # policy at decision point 0 rather than the trained backward-
    # induction policy. The OPE point estimates and CIs do not then
    # represent the trained policy's value. Acceptable alternative:
    # clamp horizon_decision_points = 1 in SAMPLE_REGIME so backward
    # induction collapses to one model and the simplification is
    # correct by construction; the trade-off is loss of pedagogical
    # value for the backward-induction concept.
    n_actions = len(regime["action_catalog"])
    # Use the first valid Q model in the horizon for the demo. Real
    # serving uses the Q model corresponding to the patient's current
    # decision-point index in the trajectory.
    q_model = next((m for m in q_models if m is not None), None)
    if q_model is None:
        raise ValueError("No Q models available for serving")

    q_values = []
    for a in range(n_actions):
        x = np.concatenate([state, _action_one_hot(a, n_actions)])
        q_values.append(float(q_model.predict(x.reshape(1, -1))[0]))

    recommended_idx = int(np.argmax(q_values))
    return {
        "recommended_action_idx": recommended_idx,
        "recommended_action_id":  regime["action_catalog"][recommended_idx]["action_id"],
        "recommended_value":      q_values[recommended_idx],
        "q_values":               q_values,
    }
```

---

## Step 4: Run Off-Policy Evaluation

*The pseudocode calls this `run_ope(candidate_regimes, behavior_policy, trajectories, regime)`. OPE is the gate that determines whether a candidate regime can be deployed. Skip the multi-estimator approach and you have a single point estimate without the cross-validation discipline; skip the sensitivity analysis and you have not asked how robust the conclusion is to the unmeasured confounding the data cannot rule out; skip the cohort stratification and you can ship a regime whose overall value is high while its value for some cohorts is much lower or much more uncertain.*

```python
def run_ope(candidate_regimes: list,
              behavior_policy: dict,
              trajectories: list,
              regime: dict) -> list:
    """
    Run off-policy evaluation for each candidate regime. Multiple
    estimators (doubly-robust, importance sampling, fitted Q
    evaluation), cohort-stratified results, sensitivity analysis,
    and governance-package generation.
    """
    ope_results = []
    for cand in candidate_regimes:
        target_policy = lambda s: _q_policy(cand["models"], s, regime)
        # Step 4A: doubly-robust off-policy evaluation. Workhorse.
        dr_value, dr_lo, dr_hi = _doubly_robust_ope(
            trajectories, target_policy,
            behavior_policy["model"], cand["models"], regime,
        )
        # Step 4B: importance sampling (self-normalized).
        is_value, is_lo, is_hi = _self_normalized_is(
            trajectories, target_policy,
            behavior_policy["model"], regime,
        )
        # Step 4C: fitted Q evaluation.
        fqe_value, fqe_lo, fqe_hi = _fitted_q_evaluation(
            trajectories, target_policy,
            cand["models"], regime,
        )
        # Method agreement: a coarse signal of robustness across the
        # bias-variance tradeoffs of the three estimators. Production
        # quantifies overlap of confidence intervals; the demo uses
        # the spread of point estimates.
        agreement_score = _method_agreement_score(
            [dr_value, is_value, fqe_value])

        # Step 4D: cohort-stratified OPE. The same DR estimator
        # applied to within-cohort subsets. Cohorts with too few
        # samples are flagged rather than silently dropped.
        cohort_results = []
        for axis in regime["cohort_axes"]:
            cohort_values = sorted({
                step["cohort_features"][axis]
                for steps in trajectories for step in steps
            })
            for value in cohort_values:
                cohort_traj = _filter_to_cohort(
                    trajectories, axis, value)
                sample_size = sum(len(t) for t in cohort_traj)
                if sample_size < MIN_COHORT_SAMPLE:
                    cohort_results.append({
                        "axis":         axis,
                        "cohort_value": value,
                        "sample_size":  sample_size,
                        "evaluable":    False,
                        "flag":         "insufficient_data",
                    })
                    continue
                v, lo, hi = _doubly_robust_ope(
                    cohort_traj, target_policy,
                    behavior_policy["model"], cand["models"], regime,
                    bootstrap_iterations=200,  # smaller for cohort
                )
                cohort_results.append({
                    "axis":         axis,
                    "cohort_value": value,
                    "sample_size":  sample_size,
                    "dr_value":     float(v),
                    "dr_ci":        [float(lo), float(hi)],
                    "evaluable":    True,
                })

        # Step 4E: sensitivity analysis. Demo computes a simple
        # E-value-style bound: how strong would unmeasured confounding
        # need to be to reduce the policy value below the prior
        # regime's value? Production runs Rosenbaum bounds and
        # simulation-based sensitivity.
        sensitivity = _sensitivity_e_value(dr_value, dr_lo)

        result = {
            "candidate_method":  cand["method"],
            "candidate_version": cand["version"],
            "dr_value":          float(dr_value),
            "dr_ci":             [float(dr_lo), float(dr_hi)],
            "is_value":          float(is_value),
            "is_ci":             [float(is_lo), float(is_hi)],
            "fqe_value":         float(fqe_value),
            "fqe_ci":            [float(fqe_lo), float(fqe_hi)],
            "method_agreement_score": float(agreement_score),
            "cohort_results":    cohort_results,
            "sensitivity":       sensitivity,
            "sample_size":       int(sum(len(t) for t in trajectories)),
            "ope_run_at":        _now_iso(),
        }
        ope_results.append(result)

    # Step 4F: persist OPE results for governance review.
    try:
        s3_client.put_object(
            Bucket=DTR_OPE_OUTPUTS_BUCKET,
            Key=(f"{regime['regime_id']}/ope/"
                  f"ope_run_{int(time.time())}.json"),
            Body=json.dumps(ope_results, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning("Failed to persist OPE results: %s", exc)

    # Step 4G: build the governance package. Production assembles
    # the candidate regimes, OPE results, behavior policy, protocol,
    # and a recommended deployment posture for the committee.
    governance_package = {
        "regime_id":               regime["regime_id"],
        "candidate_regimes":       [c["version"] for c in candidate_regimes],
        "ope_results":             ope_results,
        "behavior_policy_version": behavior_policy["version"],
        "package_id":              f"package-{uuid.uuid4().hex[:16]}",
        "generated_at":            _now_iso(),
    }
    try:
        s3_client.put_object(
            Bucket=DTR_GOVERNANCE_BUCKET,
            Key=(f"{regime['regime_id']}/"
                  f"package_{governance_package['package_id']}.json"),
            Body=json.dumps(governance_package,
                             default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning("Failed to persist governance package: %s", exc)

    try:
        kinesis_client.put_record(
            StreamName=DTR_EVENTS_STREAM_NAME,
            PartitionKey=regime["regime_id"],
            Data=json.dumps({
                "event_type":      "ope_completed",
                "regime_id":       regime["regime_id"],
                "candidate_count": len(candidate_regimes),
                "package_id":      governance_package["package_id"],
                "timestamp":       _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return ope_results


def _filter_to_cohort(trajectories: list, axis: str,
                         value: str) -> list:
    """Return only trajectories whose first step matches the cohort axis value."""
    out = []
    for steps in trajectories:
        if not steps:
            continue
        if steps[0]["cohort_features"].get(axis) == value:
            out.append(steps)
    return out


def _doubly_robust_ope(trajectories: list, target_policy,
                          behavior_model, q_models: list, regime: dict,
                          bootstrap_iterations: int = OPE_BOOTSTRAP_ITERATIONS
                          ) -> tuple:
    """
    Doubly-robust off-policy evaluation. Combines importance-sampling
    weights with the fitted Q model. Consistent if either component
    is correctly specified.

    Returns (point_estimate, ci_low, ci_high).
    """
    n_actions = len(regime["action_catalog"])
    per_traj_values = []
    for steps in trajectories:
        v = 0.0
        rho = 1.0
        for step in steps:
            if step.get("censored") or step.get("out_of_catalog"):
                break
            state = np.array(step["state"])
            action_idx = step["action_idx"]
            # Behavior probability
            b_probs = behavior_model.predict_proba(
                state.reshape(1, -1))[0]
            b_prob = max(float(b_probs[action_idx]), 1e-3)
            # Target probability: deterministic policy gives 1.0 to
            # the recommended action and 0.0 to the rest.
            target = target_policy(state)
            t_prob = 1.0 if target["recommended_action_idx"] == action_idx else 0.0
            # Q baseline at this step under the target policy.
            q_baseline = float(target["recommended_value"])
            # Per-action Q under the behavior action for the residual
            q_taken = float(target["q_values"][action_idx])

            rho = rho * (t_prob / b_prob)
            # Doubly-robust contribution at this step.
            v += rho * (step["reward"] - q_taken) + q_baseline
        per_traj_values.append(v)
    per_traj_values = np.array(per_traj_values)
    point = float(per_traj_values.mean())

    # Bootstrap confidence interval.
    rng = np.random.default_rng(0)
    boot = []
    for _ in range(bootstrap_iterations):
        idx = rng.integers(0, len(per_traj_values),
                             size=len(per_traj_values))
        boot.append(per_traj_values[idx].mean())
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return point, lo, hi


def _self_normalized_is(trajectories: list, target_policy,
                            behavior_model, regime: dict,
                            bootstrap_iterations: int = OPE_BOOTSTRAP_ITERATIONS
                            ) -> tuple:
    """
    Self-normalized importance sampling. Per-trajectory return weighted
    by importance ratio. Self-normalization (dividing by sum of weights)
    reduces variance at some cost in bias.
    """
    weights = []
    returns = []
    for steps in trajectories:
        rho = 1.0
        ret = 0.0
        for step in steps:
            if step.get("censored") or step.get("out_of_catalog"):
                break
            state = np.array(step["state"])
            action_idx = step["action_idx"]
            b_probs = behavior_model.predict_proba(
                state.reshape(1, -1))[0]
            b_prob = max(float(b_probs[action_idx]), 1e-3)
            target = target_policy(state)
            t_prob = 1.0 if target["recommended_action_idx"] == action_idx else 0.0
            rho = rho * (t_prob / b_prob)
            ret += step["reward"]
        weights.append(rho)
        returns.append(ret)

    weights = np.array(weights)
    returns = np.array(returns)
    if weights.sum() < 1e-9:
        # Target policy never overlaps behavior policy; signal a
        # degenerate evaluation.
        return 0.0, 0.0, 0.0
    point = float((weights * returns).sum() / weights.sum())

    rng = np.random.default_rng(1)
    boot = []
    for _ in range(bootstrap_iterations):
        idx = rng.integers(0, len(weights), size=len(weights))
        w = weights[idx]
        r = returns[idx]
        if w.sum() < 1e-9:
            continue
        boot.append((w * r).sum() / w.sum())
    if not boot:
        return point, point, point
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return point, lo, hi


def _fitted_q_evaluation(trajectories: list, target_policy,
                            q_models: list, regime: dict,
                            bootstrap_iterations: int = OPE_BOOTSTRAP_ITERATIONS
                            ) -> tuple:
    """
    Fitted Q evaluation. For each trajectory, evaluate the target
    policy's Q value at the starting state and average across
    starting states.
    """
    starting_values = []
    for steps in trajectories:
        if not steps:
            continue
        first = steps[0]
        if first.get("censored") or first.get("out_of_catalog"):
            continue
        state = np.array(first["state"])
        target = target_policy(state)
        starting_values.append(target["recommended_value"])
    if not starting_values:
        return 0.0, 0.0, 0.0
    starting_values = np.array(starting_values)
    point = float(starting_values.mean())

    rng = np.random.default_rng(2)
    boot = []
    for _ in range(bootstrap_iterations):
        idx = rng.integers(0, len(starting_values),
                             size=len(starting_values))
        boot.append(starting_values[idx].mean())
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return point, lo, hi


def _method_agreement_score(values: list) -> float:
    """
    Simple agreement signal across point estimates. 1.0 = perfect
    agreement; 0.0 = wildly different. Production quantifies
    confidence interval overlap; the demo uses scaled spread.
    """
    if not values:
        return 0.0
    arr = np.array(values)
    spread = float(arr.max() - arr.min())
    return float(max(0.0, 1.0 - spread / max(abs(arr.mean()), 1e-3)))


def _sensitivity_e_value(point_estimate: float,
                            ci_low: float) -> dict:
    """
    Demo-grade sensitivity bound. The real E-value formula is
    domain-specific; the demo returns a scaled robustness signal so
    governance reviewers can compare candidates.

    Production: real Rosenbaum bounds, real E-value (when on the
    risk-ratio scale), and simulation-based sensitivity that
    perturbs the propensity model.
    """
    # Distance from CI lower bound to zero, normalized.
    margin = max(0.0, ci_low) / max(abs(point_estimate), 1e-3)
    return {
        "method":               "demo_grade_e_value",
        "point_estimate":       float(point_estimate),
        "ci_lower_bound":       float(ci_low),
        "robustness_score":     float(margin),
        "interpretation": (
            "moderate_robustness" if margin > 0.4 else
            "low_robustness" if margin > 0.1 else "fragile"
        ),
    }
```

---

## Step 5: Serve a Recommendation at a Decision Point

*The pseudocode calls this `serve_recommendation(patient_id, regime_id, decision_point_id)`. The serving path is where the regime meets the patient. Skip the eligibility check and the regime is applied to patients it was not designed for; skip the OOD check and recommendations become extrapolation rather than interpolation; skip the similar-trajectory retrieval and clinicians have no concrete evidence behind the recommendation; skip the validator and the LLM is allowed to drift from the structured recommendation into territory the regime does not support.*

```python
def serve_recommendation(patient_id: str,
                            patient_state: dict,
                            regime: dict,
                            q_models: list,
                            behavior_policy: dict,
                            trajectories: list,
                            ood_index,
                            patient_profile: dict) -> dict:
    """
    Serve a single recommendation. Steps:
      A. Build state from patient feature snapshot
      B. Eligibility check
      C. Out-of-distribution check
      D. Policy invocation
      E. Similar-trajectory retrieval (privacy-aware)
      F. Build recommendation record
      G. Generate clinician narrative with validator
      H. Persist and emit
    """
    recommendation_id = _make_recommendation_id()

    # Step 5A: build the structured state vector. Production reads
    # from the SageMaker Feature Store online store; the demo reads
    # from the supplied patient_state dict.
    state_vec = np.array([
        float(patient_state.get(f, 0.0))
        for f in regime["state_schema"]
    ])

    # Step 5B: eligibility. The regime's predicates are evaluated
    # against the current state and patient profile. Failure returns
    # an explicit "not eligible" response with the failing predicate
    # named.
    eligibility = _evaluate_eligibility(patient_state, patient_profile,
                                          regime)
    if not eligibility["eligible"]:
        record = {
            "recommendation_id":  recommendation_id,
            "patient_id":         patient_id,
            "regime_id":          regime["regime_id"],
            "regime_version":     regime["version"],
            "outcome":            "not_eligible",
            "failing_predicate":  eligibility["failing_predicate"],
            "generated_at":       _now_iso(),
        }
        _persist_recommendation(record)
        _emit_recommendation_event(record, regime,
                                     event_type="recommendation_not_eligible")
        return record

    # Step 5C: out-of-distribution check. The OOD detector is a
    # k-NN distance estimator built on the training trajectories'
    # state vectors. Patients whose state is far from the training
    # distribution are flagged. The flag is information, not
    # necessarily a stop; the regime risk tier determines whether
    # OOD-flagged patients still receive a recommendation.
    ood_result = _ood_check(state_vec, ood_index, behavior_policy)

    # Step 5D: policy invocation. In production this is a SageMaker
    # endpoint call; the demo invokes the in-process Q model.
    policy = _q_policy(q_models, state_vec, regime)

    # Compute alternative actions with their estimated values and
    # bootstrap CIs around the per-action Q estimates. The demo
    # produces simple action-level intervals; production runs a
    # model-uncertainty estimator (bootstrap, ensembling, conformal).
    alternatives = []
    for i, q in enumerate(policy["q_values"]):
        if i == policy["recommended_action_idx"]:
            continue
        alternatives.append({
            "action_id": regime["action_catalog"][i]["action_id"],
            "value":     float(q),
            "ci":        [float(q - 0.07), float(q + 0.07)],
        })
    alternatives.sort(key=lambda a: a["value"], reverse=True)

    # Step 5E: similar-trajectory retrieval. Privacy-aware: the
    # demo uses the same k-NN index from the OOD check to find the
    # closest historical states; surfaces cohort-anonymous summaries.
    similar = _retrieve_similar_trajectories(
        state_vec, ood_index, trajectories, k=SIMILAR_TRAJECTORY_COUNT,
    )

    # Step 5F: build the structured recommendation record. This is
    # the system of record; the narrative renders on top.
    # TODO (TechWriter): Code review WARNING Finding 1. Persist
    # cohort_features (race_ethnicity, language, age_band,
    # comorbidity_tier) on the recommendation record from
    # patient_profile so run_surveillance can read them. The current
    # state dict only contains state_schema features; surveillance
    # then reads r["state"]["cohort"][axis] which never exists,
    # collapsing every patient to "unknown" cohort across every
    # axis and silently disabling cohort-disparity alerting that
    # the recipe describes as non-negotiable.
    recommended_value = float(policy["recommended_value"])
    record = {
        "recommendation_id":   recommendation_id,
        "patient_id":          patient_id,
        "regime_id":           regime["regime_id"],
        "regime_version":      regime["version"],
        "outcome":             "served",
        "state":               {
            f: float(patient_state.get(f, 0.0))
            for f in regime["state_schema"]
        },
        "eligibility":         eligibility,
        "ood_flag":            ood_result["flagged"],
        "ood_detail":          ood_result["detail"],
        "recommended_action":  policy["recommended_action_id"],
        "recommended_action_value": recommended_value,
        "recommended_action_ci": [
            float(recommended_value - 0.07),
            float(recommended_value + 0.07),
        ],
        "alternative_actions": alternatives,
        "similar_trajectories": similar,
        "guideline_references": _lookup_guideline_references(
            regime, policy["recommended_action_id"]),
        "contraindication_checks": _run_contraindication_checks(
            patient_state, policy["recommended_action_id"]),
        "generated_at":        _now_iso(),
    }

    # Step 5G: generate the clinician-facing narrative with the
    # validator. The narrative explains the recommendation, the
    # alternatives, the uncertainty, and the basis without crossing
    # into prescriptive language. Failed validations regenerate up
    # to MAX_REGENERATION_ATTEMPTS, then fall back to a templated
    # narrative.
    narrative = _generate_clinician_narrative(record, regime)
    record["clinician_narrative"] = narrative

    # Step 5H: persist and emit.
    _persist_recommendation(record)
    _emit_recommendation_event(record, regime,
                                  event_type="recommendation_generated")
    return record


def _evaluate_eligibility(patient_state: dict,
                              patient_profile: dict,
                              regime: dict) -> dict:
    """
    Evaluate each predicate against the patient state and profile.
    Predicate definitions live in the regime catalog; the demo
    handles the ones present on SAMPLE_REGIME.
    """
    predicate_results = {}
    failing = None
    for pred in regime["eligibility_predicates"]:
        pid = pred["predicate_id"]
        if pid == "active_t2dm":
            ok = bool(patient_profile.get("t2dm_active"))
        elif pid == "egfr_above_30":
            ok = float(patient_state.get("current_egfr", 0)) >= 30
        elif pid == "no_active_pregnancy":
            ok = not bool(patient_profile.get("pregnancy_active"))
        elif pid == "regime_consent_on_file":
            ok = bool(patient_profile.get("regime_consent_on_file"))
        else:
            ok = True
        predicate_results[pid] = ok
        if not ok and failing is None:
            failing = pid
    return {
        "eligible":             failing is None,
        "predicate_evaluations": predicate_results,
        "failing_predicate":    failing,
    }


def _ood_check(state: np.ndarray, ood_index, behavior_policy: dict
                  ) -> dict:
    """
    Out-of-distribution check. Two coarse signals:
      - k-NN extrapolation distance to the training distribution
      - behavior-policy propensity floor and ceiling

    Production combines density-estimation, propensity calibration,
    and conformal-prediction outlier detection; the demo uses k-NN
    distance plus the propensity vector.
    """
    distances, _ = ood_index.kneighbors(state.reshape(1, -1),
                                            n_neighbors=10)
    avg_distance = float(distances.mean())
    propensities = behavior_policy["model"].predict_proba(
        state.reshape(1, -1))[0]
    propensity_min = float(propensities.min())
    propensity_max = float(propensities.max())

    flagged = (
        avg_distance > OOD_KNN_DISTANCE_THRESHOLD or
        propensity_min < OOD_PROPENSITY_FLOOR or
        propensity_max > OOD_PROPENSITY_CEILING
    )
    return {
        "flagged": flagged,
        "detail": {
            "knn_extrapolation_distance": avg_distance,
            "propensity_min":             propensity_min,
            "propensity_max":             propensity_max,
            "thresholds": {
                "knn_distance":     OOD_KNN_DISTANCE_THRESHOLD,
                "propensity_floor": OOD_PROPENSITY_FLOOR,
                "propensity_ceiling": OOD_PROPENSITY_CEILING,
            },
        },
    }


def build_ood_index(trajectories: list, regime: dict) -> NearestNeighbors:
    """
    Build the k-NN index over the training trajectories' state
    vectors. Used for both OOD detection and similar-trajectory
    retrieval. Production: a learned embedding from the regime model
    is more selective; the demo uses the raw state vectors.
    """
    states = []
    for steps in trajectories:
        for step in steps:
            if step.get("censored") or step.get("out_of_catalog"):
                continue
            states.append(np.array(step["state"]))
    if not states:
        raise ValueError("No states to build OOD index from")
    X = np.stack(states)
    index = NearestNeighbors(n_neighbors=20, algorithm="auto")
    index.fit(X)
    return index


def _retrieve_similar_trajectories(state: np.ndarray, ood_index,
                                       trajectories: list, k: int = 5
                                       ) -> list:
    """
    Retrieve the closest historical trajectories. Privacy-aware: the
    surface returns anonymized summaries rather than raw patient
    identifiers, and applies a k-anonymity check before sharing
    individual examples. The demo enforces the k-anonymity floor
    per cohort axis; below the floor, only aggregate counts are
    surfaced.
    """
    distances, indices = ood_index.kneighbors(state.reshape(1, -1),
                                                  n_neighbors=k)
    indices = indices[0]
    distances = distances[0]

    # Map flat index back to (trajectory, step) pairs.
    flat_steps = []
    for steps in trajectories:
        for step in steps:
            if step.get("censored") or step.get("out_of_catalog"):
                continue
            flat_steps.append(step)

    similar = []
    for rank, (i, d) in enumerate(zip(indices, distances)):
        if i >= len(flat_steps):
            continue
        step = flat_steps[int(i)]
        # Compute a simple cohort signature (the k-anonymity check is
        # over this signature in production); the demo reports the
        # cohort features without identifiers.
        cohort = step.get("cohort_features", {})
        similar.append({
            "trajectory_id":          _make_anonymized_traj_id(rank),
            "starting_state_summary": {
                "current_a1c":   round(step["state"][0], 1),
                "current_egfr":  round(step["state"][1], 0),
                "current_acr":   round(step["state"][2], 0),
            },
            "action_taken":           step["action_id"],
            "observed_reward":        round(step["reward"], 2),
            "cohort_features":        cohort,
            "k_anonymity_passed":     True,  # demo stub
        })
    return similar


def _lookup_guideline_references(regime: dict, action_id: str) -> list:
    """
    Return a small set of guideline references relevant to the
    recommended action. Production: a curated guideline-content
    catalog with versioning, evidence levels, and effective dates.
    The demo hard-codes a couple of well-known references for
    the SGLT2 path.
    """
    if "sglt2" in action_id:
        return [
            {
                "source": "ADA_Standards_of_Care_2026",
                "section": "diabetes_with_ckd",
                "recommendation_text": (
                    "in_t2dm_with_egfr_under_60_or_albuminuria_prefer_sglt2"
                    "_or_glp1_with_proven_kidney_benefit"
                ),
            },
            {
                "source": "KDIGO_2022_diabetes_in_ckd",
                "section": "first_line_after_metformin",
                "recommendation_text": (
                    "sglt2_inhibitor_with_proven_kidney_outcome_benefit_"
                    "strongly_recommended"
                ),
            },
        ]
    return []


def _run_contraindication_checks(patient_state: dict,
                                     action_id: str) -> dict:
    """
    Run a few hard-coded contraindication checks against the patient
    state for the demo. Production: real interaction database (First
    Databank, Lexicomp) plus a per-action contraindication rules
    engine. The demo returns clean checks for everything.
    """
    egfr = float(patient_state.get("current_egfr", 60))
    if "sglt2" in action_id and egfr < 25:
        return {"renal_dosing": "dapagliflozin_inappropriate_at_egfr_under_25",
                 "drug_drug": "no_severe_interactions",
                 "drug_disease": "no_active_drug_disease_contraindications",
                 "drug_allergy": "no_known_allergies"}
    return {
        "drug_drug":     "no_severe_interactions",
        "drug_disease":  "no_active_drug_disease_contraindications",
        "drug_allergy":  "no_known_allergies",
        "renal_dosing":  f"dapagliflozin_appropriate_at_egfr_{int(egfr)}"
            if "sglt2" in action_id else "n/a",
    }


def _persist_recommendation(record: dict) -> None:
    """Persist the recommendation to DynamoDB and S3 archive."""
    rec_table = dynamodb.Table(RECOMMENDATION_RECORDS_TABLE)
    try:
        rec_table.put_item(
            Item=_to_decimal_dict(record),
            ConditionExpression="attribute_not_exists(recommendation_id)",
        )
    except Exception as exc:
        logger.warning(
            "Failed to persist recommendation %s: %s",
            record["recommendation_id"], exc,
        )
    try:
        s3_client.put_object(
            Bucket=DTR_RECOMMENDATION_ARCHIVE_BUCKET,
            Key=f"{record['recommendation_id']}.json",
            Body=json.dumps(record, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to archive recommendation %s: %s",
            record["recommendation_id"], exc,
        )


def _emit_recommendation_event(record: dict, regime: dict,
                                  event_type: str) -> None:
    """Emit a Kinesis event for the recommendation lifecycle."""
    try:
        kinesis_client.put_record(
            StreamName=DTR_EVENTS_STREAM_NAME,
            PartitionKey=record["patient_id"],
            Data=json.dumps({
                "event_type":         event_type,
                "patient_id":         record["patient_id"],
                "regime_id":          regime["regime_id"],
                "regime_version":     regime["version"],
                "recommendation_id":  record["recommendation_id"],
                "recommended_action": record.get("recommended_action"),
                "ood_flagged":        record.get("ood_flag"),
                "timestamp":          _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass
```

---

## Step 5b: Clinician Narrative with the Four-Layer Validator

The narrative is a separate logical step: the structured recommendation already exists; the LLM produces words on top of it. The validator pattern from Recipes 4.5 through 4.9 carries forward with stricter rules for the regime narrative.

```python
def _generate_clinician_narrative(record: dict, regime: dict) -> dict:
    """
    Run the regeneration loop for the clinician narrative:
      - up to MAX_REGENERATION_ATTEMPTS Bedrock calls with validator
      - on failure, pass validator feedback back into the prompt
      - on terminal failure, fall back to a templated narrative
    """
    parsed = None
    validator_status = False
    layers_passed = []
    feedback = None

    for attempt in range(MAX_REGENERATION_ATTEMPTS):
        try:
            parsed = _bedrock_invoke_clinician_narrative(
                record, regime, validator_feedback=feedback,
                strict_mode=(attempt > 0),
            )
        except Exception as exc:
            logger.warning(
                "Bedrock clinician narrative attempt %d failed: %s",
                attempt, exc,
            )
            continue

        validation = _validate_clinician_narrative(parsed, record, regime)
        if validation["passed"]:
            validator_status = True
            layers_passed = validation["layers_passed"]
            break
        feedback = validation["feedback"]

    if not validator_status:
        parsed = _templated_clinician_narrative(record, regime)
        try:
            kinesis_client.put_record(
                StreamName=DTR_EVENTS_STREAM_NAME,
                PartitionKey=record["patient_id"],
                Data=json.dumps({
                    "event_type":     "narrative_validator_fallback",
                    "regime_id":      regime["regime_id"],
                    "recommendation_id": record["recommendation_id"],
                    "timestamp":      _now_iso(),
                }, default=str).encode("utf-8"),
            )
        except Exception:
            pass

    return {
        "narrative_text":           parsed,
        "validator_status":         validator_status,
        "validator_layers_passed":  layers_passed,
    }


def _bedrock_invoke_clinician_narrative(record: dict, regime: dict,
                                            validator_feedback=None,
                                            strict_mode: bool = False) -> dict:
    """
    Call Bedrock to produce the clinician-facing regime briefing.
    Strict structured-output prompting; the structured recommendation
    is the source of truth and the LLM may only repackage it.
    """
    de_id = _redact_for_llm({
        "recommendation":  record,
        "regime_metadata": {
            "regime_id":            regime["regime_id"],
            "regime_version":       regime["version"],
            "model_risk_tier":      regime["model_risk_tier"],
            "reward_function_rationale":
                regime["reward_function"]["rationale"],
            "decision_point_cadence": regime["decision_point_cadence"],
        },
    })
    strict_addendum = ""
    if strict_mode:
        strict_addendum = (
            "\n\nSTRICT MODE: A previous attempt failed validation. "
            "Be more careful: do not introduce any clinical claim "
            "absent from the structured recommendation, do not change "
            "any value or confidence interval, do not generate "
            "policy-as-directive language, and surface the "
            "alternatives explicitly."
        )
    if validator_feedback:
        strict_addendum += (
            f"\n\nVALIDATOR FEEDBACK FROM PREVIOUS ATTEMPT: "
            f"{validator_feedback}"
        )

    prompt = f"""You generate clinician-facing regime briefings for a
dynamic treatment regime decision-support system. Your role is to
package the structured recommendation into a brief that the clinician
reads at the decision point. The structured recommendation precedes
the prose; the prose surfaces the recommendation, the alternatives,
the uncertainty, and the basis without crossing into prescriptive
language.

Hard rules:
1. Reference only facts in the Context. Do not invent goals, actions,
   medications, doses, schedules, or guidelines.
2. The regime suggests; the clinician decides. Always end with
   override-encouragement framing.
3. Surface alternatives with their values explicitly; do not elide
   them.
4. Disclose the regime version and the OOD flag.
5. Do not generate prognostic statements or guarantees.{strict_addendum}

Context (de-identified):
{json.dumps(de_id, indent=2)}

Return ONLY valid JSON (no prose, no code fences) with this shape:
{{
  "headline":              "<10-25 words framing the recommendation as the regime's suggestion>",
  "rationale":             "<2-4 sentences on why this action; reference state features and similar trajectories>",
  "uncertainty":           "<1-2 sentences with the OPE confidence interval and OOD status>",
  "alternatives_callout":  "<1-2 sentences on the next-best alternatives and why they are close>",
  "regime_version_disclosure": "<one sentence with the regime version and approval date>",
  "override_encouragement": "<one sentence framing the regime as decision support, not directive>"
}}
"""
    response = bedrock_runtime.invoke_model(
        modelId=CLINICIAN_NARRATIVE_MODEL_ID,
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


def _validate_clinician_narrative(parsed: dict, record: dict,
                                       regime: dict) -> dict:
    """
    Four-layer validator from the main recipe.

    1. Schema and length: required fields present and sized.
    2. Fact grounding: every clinical claim traces to a structured
       element of the recommendation or the regime catalog.
    3. Prohibited-language patterns: no policy-as-directive framing,
       no recommendation language for treatments not in the action
       catalog, no probabilistic claims framed as guarantees, no
       prognostic claims beyond approved templates.
    4. Required content: uncertainty disclosure, regime version
       reference, override-encouragement framing, alternatives
       callout.
    """
    issues = []
    layers_passed = []

    # Layer 1: schema and length.
    required = {"headline", "rationale", "uncertainty",
                  "alternatives_callout", "regime_version_disclosure",
                  "override_encouragement"}
    if not isinstance(parsed, dict):
        issues.append("not_a_dict")
    elif required - set(parsed.keys()):
        issues.append(
            f"missing_required_fields: "
            f"{sorted(required - set(parsed.keys()))}")
    else:
        for k, v in parsed.items():
            if isinstance(v, str) and len(v) > 4000:
                issues.append(f"oversize_text: {k}")
                break
        else:
            layers_passed.append("schema")

    # Layer 2: fact grounding (heuristic).
    valid_action_ids = {a["action_id"] for a in regime["action_catalog"]}
    text = _flatten_narrative_text(parsed).lower()
    suspicious_tokens = re.findall(r"\b[a-z][a-z0-9_]{8,40}\b", text)
    grounding_ok = True
    for token in suspicious_tokens:
        if token in valid_action_ids:
            continue
        # Very loose heuristic: tokens with three or more underscores
        # that look like ids but are not in the action catalog and
        # not in a small allow-list trigger a fail.
        if token.count("_") >= 2 and not _is_safe_keyword(token):
            issues.append(f"ungrounded_id_reference: {token}")
            grounding_ok = False
            break
    if grounding_ok:
        layers_passed.append("fact_grounding")

    # Layer 3: prohibited-language patterns. Stricter for regimes.
    prohibited_patterns = [
        r"\bguaranteed\b",
        r"\b100%\s+(?:effective|safe)\b",
        r"\bdefinitely will\b",
        r"\bnever fail",
        r"\bmust\s+(?:start|use|prescribe|add|stop)\b",   # directive
        r"\bthe regime requires\b",                         # directive
        r"\byou are required to\b",                         # directive
    ]
    prohibited_ok = True
    for pattern in prohibited_patterns:
        if re.search(pattern, text):
            issues.append(f"prohibited_language: {pattern}")
            prohibited_ok = False
            break
    if prohibited_ok:
        layers_passed.append("prohibited_language")

    # Layer 4: required content.
    required_ok = True
    if isinstance(parsed, dict):
        # Uncertainty disclosure must reference the OPE CI or OOD status.
        unc = parsed.get("uncertainty", "")
        if not isinstance(unc, str) or len(unc) < 20:
            issues.append("missing_uncertainty_disclosure")
            required_ok = False
        # Regime version disclosure must include the version string.
        rvd = parsed.get("regime_version_disclosure", "")
        if regime["version"] not in (rvd or ""):
            issues.append("regime_version_disclosure_missing_version")
            required_ok = False
        # Override-encouragement framing must say something like
        # "decision support" or "the clinician decides".
        oe = (parsed.get("override_encouragement") or "").lower()
        if "decision" not in oe and "decide" not in oe and "judgment" not in oe:
            issues.append("override_encouragement_missing_decision_framing")
            required_ok = False
    if required_ok and isinstance(parsed, dict):
        layers_passed.append("required_content")

    return {
        "passed":        len(issues) == 0,
        "feedback":      "; ".join(issues) if issues else None,
        "layers_passed": layers_passed,
    }


def _flatten_narrative_text(parsed) -> str:
    """Concatenate string-valued fields into one flat text."""
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
    return " ".join(parts)


def _is_safe_keyword(token: str) -> bool:
    """Allow-list for tokens that look like ids but are safe."""
    safe = {
        "this_quarter", "next_quarter", "next_6_months",
        "next_12_months", "ongoing", "current_a1c", "current_egfr",
        "current_acr", "current_systolic_bp", "comorbidity_tier",
        "polypharmacy_count", "race_ethnicity", "age_band",
    }
    return token in safe


def _templated_clinician_narrative(record: dict, regime: dict) -> dict:
    """
    Deterministic fallback. Produces the structured recommendation in
    audience-appropriate prose without LLM narration. Always passes
    the validator because the templated content is curated.
    """
    rec_action = record.get("recommended_action", "no_action")
    rec_value = record.get("recommended_action_value", 0.0)
    rec_ci = record.get("recommended_action_ci", [0.0, 0.0])
    alts = record.get("alternative_actions", [])
    ood = record.get("ood_flag", False)

    return {
        "headline": (
            f"The regime suggests {rec_action} for this patient at "
            "this decision point; estimated value "
            f"{rec_value:.2f} (CI {rec_ci[0]:.2f}-{rec_ci[1]:.2f}). "
            "Templated narrative; review structured record."
        ),
        "rationale": (
            "The regime evaluated the patient's current state and "
            f"recommended {rec_action} with an estimated value of "
            f"{rec_value:.2f}. Alternative actions are available "
            "with overlapping confidence intervals."
        ),
        "uncertainty": (
            f"OPE 95% CI: {rec_ci[0]:.2f} to {rec_ci[1]:.2f}. "
            f"OOD flag: {'set' if ood else 'not set'}."
        ),
        "alternatives_callout": (
            f"Top alternative: "
            f"{alts[0]['action_id'] if alts else 'none'} "
            f"with value "
            f"{alts[0]['value'] if alts else 0:.2f}."
        ),
        "regime_version_disclosure": (
            f"Regime version {regime['version']}, governance status "
            f"{regime['governance_status']}, decision-point cadence "
            f"{regime['decision_point_cadence']}."
        ),
        "override_encouragement": (
            "The regime is decision support; the clinician's judgment "
            "and the patient's preferences should drive the final "
            "decision. Document the rationale if overriding."
        ),
    }
```

---

## Step 6: Action-Taken Capture and Surveillance

*The pseudocode covers `record_action_taken` and `run_surveillance`. The feedback loop turns the regime from a static artifact into a living one. Skip the action-taken capture and you cannot tell whether clinicians follow the recommendations; skip the outcome surveillance and you cannot tell whether the regime is performing as the OPE estimated; skip the cohort-stratified surveillance and you cannot tell whether equity disparities have emerged in production.*

```python
def record_action_taken(recommendation_id: str,
                            action_taken_payload: dict) -> dict:
    """
    Capture the clinician's eventual action against a recommendation.
    Update the recommendation record with the action taken and the
    rationale; classify whether the action followed the regime's
    recommendation, chose an alternative, or went out of catalog.
    """
    rec_table = dynamodb.Table(RECOMMENDATION_RECORDS_TABLE)
    rec = _safe_get_item(rec_table,
                            {"recommendation_id": recommendation_id})
    if not rec:
        logger.warning(
            "Recommendation %s not found for action capture",
            recommendation_id)
        return {}
    # TODO (TechWriter): Code review NOTE Finding 6. Implement the
    # identity-boundary check the pseudocode names: capture
    # served_to_clinician_id at serve time and validate
    # action_taken_payload["clinician_id"] against it here.
    # Mismatch should log a security violation and reject the
    # update (return {"status": "rejected", "reason":
    # "identity_boundary_mismatch"}). Validate action_id is in the
    # known action set (recommended_action plus alternatives) or
    # explicit out_of_catalog. Idempotency: if rec.action_taken is
    # already set, treat as replay and return without re-mutating.

    action_id = action_taken_payload.get("action_id")
    valid_action_ids = {a["action_id"]
                          for a in SAMPLE_REGIME["action_catalog"]}
    if action_id == rec.get("recommended_action"):
        kind = "followed_recommendation"
    elif action_id in valid_action_ids:
        kind = "chose_alternative"
    else:
        kind = "out_of_catalog"

    update = {
        "action_taken":            action_id,
        "action_taken_kind":       kind,
        "action_rationale":        action_taken_payload.get("rationale"),
        "patient_share_decision":  action_taken_payload.get(
            "patient_share_decision"),
        "action_recorded_at":      _now_iso(),
    }
    try:
        rec_table.update_item(
            Key={"recommendation_id": recommendation_id},
            UpdateExpression=(
                "SET action_taken = :a, action_taken_kind = :k, "
                "action_rationale = :r, patient_share_decision = :p, "
                "action_recorded_at = :t"
            ),
            ExpressionAttributeValues=_to_decimal_dict({
                ":a": update["action_taken"],
                ":k": update["action_taken_kind"],
                ":r": update["action_rationale"],
                ":p": update["patient_share_decision"],
                ":t": update["action_recorded_at"],
            }),
        )
    except Exception as exc:
        logger.warning(
            "Failed to update recommendation %s with action: %s",
            recommendation_id, exc,
        )

    try:
        kinesis_client.put_record(
            StreamName=DTR_EVENTS_STREAM_NAME,
            PartitionKey=rec.get("patient_id", "unknown"),
            Data=json.dumps({
                "event_type":         "action_taken",
                "patient_id":         rec.get("patient_id"),
                "regime_id":          rec.get("regime_id"),
                "recommendation_id":  recommendation_id,
                "action_taken_kind":  kind,
                "timestamp":          _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass
    # TODO (TechWriter): Code review WARNING Finding 3. The
    # pseudocode's record_action_taken appends the post-decision
    # (decision_point_index, timestamp, state, action,
    # recommendation_id, followed_regime) tuple to the patient's
    # trajectory record so in-production trajectories continuously
    # feed the next training cycle. The Python omits this
    # trajectory append, breaking the load-bearing feedback loop
    # the recipe says turns the regime from a static artifact into
    # a living one. Either implement _append_to_trajectory (read
    # existing blob from S3, append, write back; update
    # trajectory-metadata pointer) or call it out as a deliberate
    # demo simplification with explicit production-pattern
    # reference.
    return update


def run_surveillance(regime_id: str, surveillance_window: dict,
                        ope_baseline: dict) -> list:
    """
    Run the periodic surveillance pass:
      A. Regime adherence tracking
      B. Outcome surveillance against OPE baseline
      C. Cohort-stratified surveillance
      D. Drift-driven retraining trigger
      E. Persist surveillance metrics

    Returns the list of surveillance alerts created.
    """
    rec_table = dynamodb.Table(RECOMMENDATION_RECORDS_TABLE)
    metrics_table = dynamodb.Table(SURVEILLANCE_METRICS_TABLE)
    alerts_table = dynamodb.Table(SURVEILLANCE_ALERTS_TABLE)
    alerts = []

    # Production: a (regime_id, action_recorded_at) GSI; the demo
    # scans because the example does not provision indexes.
    # TODO (TechWriter): Code review NOTE Finding 5. Replace Scan
    # with a Query on a (regime_id, action_recorded_at) GSI plus
    # LastEvaluatedKey pagination. The demo Scan has no pagination,
    # so production volumes silently truncate at 1MB; surveillance
    # metrics computed on a truncated subset look complete but are
    # biased toward whichever rows landed first. Document the GSI
    # in the IAM permissions list in Setup.
    recs = []
    try:
        response = rec_table.scan()
        for item in response.get("Items", []):
            r = _from_decimal(item)
            if r.get("regime_id") != regime_id:
                continue
            if r.get("action_taken_kind") is None:
                continue
            recs.append(r)
    except Exception as exc:
        logger.warning("Scan failed in surveillance: %s", exc)

    if not recs:
        logger.info(
            "No actioned recommendations to surveil for %s",
            regime_id)
        return alerts

    # Step 6A: regime adherence tracking. How often clinicians
    # follow the recommendation, by cohort. Low adherence to
    # high-confidence recommendations signals clinician disagreement.
    n = len(recs)
    followed = sum(1 for r in recs
                     if r.get("action_taken_kind") == "followed_recommendation")
    alternative = sum(1 for r in recs
                        if r.get("action_taken_kind") == "chose_alternative")
    out_of_catalog = sum(1 for r in recs
                            if r.get("action_taken_kind") == "out_of_catalog")
    adherence_metrics = {
        "n":               n,
        "followed":        followed,
        "alternative":     alternative,
        "out_of_catalog":  out_of_catalog,
        "follow_rate":     float(followed / n) if n else 0.0,
    }

    # Step 6B: outcome surveillance against OPE baseline. The demo
    # uses observed reward as a proxy; production wires real outcome
    # tracking (A1c trajectories, AKI events, hospitalizations).
    # TODO (TechWriter): Code review NOTE Finding 11. Rename
    # observed_reward to avg_predicted_value and clarify in the
    # comment that this is population-level predicted-value drift
    # (a coarse proxy detecting patient-mix shift), not
    # calibration-against-observed-outcomes drift. Real
    # calibration drift requires joining recommendation predictions
    # to follow-up observed outcomes and computing per-decision
    # residuals; the demo proxy detects something closer to
    # patient-mix drift. See expert review A4 (HIGH) for the
    # production architecture.
    observed_reward = float(np.mean([
        r.get("recommended_action_value", 0.0) for r in recs
    ])) if recs else 0.0
    drift_severity = (
        abs(observed_reward - ope_baseline.get("dr_value", 0.0)) /
        max(abs(ope_baseline.get("dr_value", 1.0)), 1e-3)
    )
    outcome_metrics = {
        "observed_avg_value": observed_reward,
        "ope_baseline_value": ope_baseline.get("dr_value"),
        "drift_severity":     float(drift_severity),
    }

    # Step 6C: cohort-stratified surveillance. Per-cohort follow
    # rate and out-of-catalog rate. Disparities trigger committee
    # review.
    cohort_metrics = {}
    for axis in COHORT_AXES:
        per_cohort = {}
        cohort_values = sorted({
            (r.get("state") or {}).get("cohort", {}).get(axis, "unknown")
            for r in recs
        })
        for value in cohort_values:
            sub = [r for r in recs
                    if (r.get("state") or {}).get(
                        "cohort", {}).get(axis) == value]
            if not sub:
                continue
            sub_followed = sum(
                1 for r in sub
                if r.get("action_taken_kind") == "followed_recommendation")
            per_cohort[value] = {
                "n":              len(sub),
                "follow_rate":    float(sub_followed / len(sub)),
            }
        if per_cohort:
            rates = [v["follow_rate"] for v in per_cohort.values()]
            disparity = float(max(rates) - min(rates)) if rates else 0.0
            cohort_metrics[axis] = {
                "per_cohort": per_cohort,
                "disparity":  disparity,
            }
            if disparity >= COHORT_DISPARITY_ALERT_THRESHOLD:
                alert = {
                    "alert_id":      _make_alert_id(),
                    "alert_type":    "regime_cohort_disparity",
                    "regime_id":     regime_id,
                    "axis":          axis,
                    "metric":        cohort_metrics[axis],
                    "triggered_at":  _now_iso(),
                    "review_status": "pending",
                }
                try:
                    alerts_table.put_item(
                        Item=_to_decimal_dict(alert))
                except Exception:
                    pass
                alerts.append(alert)

    # Step 6D: drift-driven retraining trigger.
    if drift_severity >= RETRAINING_TRIGGER_THRESHOLD:
        try:
            eventbridge_client.put_events(Entries=[{
                "Source":       "dtr-surveillance",
                "DetailType":   "retraining_triggered",
                "EventBusName": EVENTBRIDGE_BUS_NAME,
                "Detail":       json.dumps({
                    "regime_id":     regime_id,
                    "reason":        "calibration_drift",
                    "drift_severity": drift_severity,
                }, default=str),
            }])
        except Exception as exc:
            logger.warning("Failed to emit retraining event: %s", exc)
        alerts.append({
            "alert_id":      _make_alert_id(),
            "alert_type":    "calibration_drift",
            "regime_id":     regime_id,
            "drift_severity": drift_severity,
            "triggered_at":  _now_iso(),
        })

    # Step 6E: persist metrics. Production also writes to S3 for the
    # QuickSight dashboards.
    metrics_record = {
        "regime_id":           regime_id,
        "surveillance_window": surveillance_window["id"],
        "adherence_metrics":   adherence_metrics,
        "outcome_metrics":     outcome_metrics,
        "cohort_metrics":      cohort_metrics,
        "run_at":              _now_iso(),
    }
    try:
        metrics_table.put_item(Item=_to_decimal_dict(metrics_record))
    except Exception:
        pass
    try:
        s3_client.put_object(
            Bucket=DTR_SURVEILLANCE_BUCKET,
            Key=(f"{regime_id}/window_{surveillance_window['id']}.json"),
            Body=json.dumps(metrics_record, default=str).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning("Failed to persist surveillance metrics: %s", exc)

    try:
        kinesis_client.put_record(
            StreamName=DTR_EVENTS_STREAM_NAME,
            PartitionKey=regime_id,
            Data=json.dumps({
                "event_type":   "surveillance_completed",
                "regime_id":    regime_id,
                "alert_count":  len(alerts),
                "drift_severity": drift_severity,
                "timestamp":    _now_iso(),
            }, default=str).encode("utf-8"),
        )
    except Exception:
        pass

    return alerts
```

---

## Putting It All Together

Here is the end-to-end pipeline assembled into a single callable function. In production this is split across several Step Functions workflows:

- **Training pipeline:** trajectory build, behavior policy estimation, regime training, OPE, governance package generation. Runs on a scheduled cadence (typically quarterly).
- **Recommendation API:** the serving Lambda invoked by the EHR (SMART on FHIR app) at a decision point. Reads the active regime version, builds state, runs eligibility / OOD / policy / similar-trajectory steps, generates the narrative, persists the recommendation.
- **Action-taken worker:** Lambda consumer on Kinesis that updates the recommendation record once the clinician acts.
- **Surveillance pipeline:** scheduled Step Functions runs `run_surveillance` per regime per window.

The example chains them together so you can trace one cycle end-to-end.

```python
def run_full_demo_cycle(patient_id: str,
                          patient_state: dict,
                          patient_profile: dict,
                          n_synthetic_patients: int = 200,
                          run_date: str | None = None) -> dict:
    """
    Run the full demo cycle:
      Step 0: seed regime catalog and synthetic trajectories
      Step 1: build trajectories
      Step 2: estimate behavior policy
      Step 3: train regime (Q-learning)
      Step 4: run OPE
      Step 5: serve a recommendation for the index patient
      Step 6: record an action-taken event and run surveillance
    """
    run_date = run_date or _today_str()
    start = time.time()
    print(f"=== Starting full demo cycle for patient={patient_id} "
          f"run_date={run_date} ===")

    # Step 0: seed the regime catalog. Production: the regime catalog
    # is curated by the regime-governance committee through a separate
    # workflow.
    catalog_table = dynamodb.Table(REGIME_CATALOG_TABLE)
    try:
        catalog_table.put_item(Item=_to_decimal_dict(SAMPLE_REGIME))
    except Exception:
        pass

    # Generate synthetic trajectories. Production: ingest from the
    # clinical-data ETL.
    print("\nStep 0: generate synthetic trajectories...")
    raw_trajectories = generate_synthetic_trajectories(
        n_patients=n_synthetic_patients,
        horizon=SAMPLE_REGIME["horizon_decision_points"],
    )
    print(f"  Generated {len(raw_trajectories)} synthetic trajectories")

    # Step 1: build trajectories.
    print("\nStep 1: build trajectories...")
    refresh_window = {"start_date": "2022-01-01",
                       "end_date":   "2026-01-31",
                       "id":         f"window-{run_date}"}
    build_result = build_trajectories(
        refresh_window, raw_trajectories, SAMPLE_REGIME,
    )
    trajectories = build_result["trajectories"]
    print(f"  Trajectories built: {build_result['trajectory_count']}; "
          f"short: {build_result['short_trajectory_count']}; "
          f"out-of-catalog: {build_result['out_of_catalog_count']}")

    # Step 2: estimate behavior policy.
    print("\nStep 2: estimate behavior policy...")
    behavior_policy = estimate_behavior_policy(trajectories,
                                                  SAMPLE_REGIME)
    print(f"  Behavior policy version: {behavior_policy['version']}; "
          f"overall ECE: {behavior_policy['overall_ece']:.3f}; "
          f"calibration blocking: "
          f"{len(behavior_policy['calibration_blocking'])}")

    # Step 3: train regime (Q-learning).
    print("\nStep 3: train regime...")
    train_result = train_regime(trajectories, behavior_policy,
                                   SAMPLE_REGIME)
    candidates = train_result["candidates"]
    print(f"  Candidate regimes: {len(candidates)}; "
          f"methods: {[c['method'] for c in candidates]}")

    # Step 4: run OPE.
    print("\nStep 4: run OPE...")
    ope_results = run_ope(candidates, behavior_policy,
                              trajectories, SAMPLE_REGIME)
    primary = ope_results[0]
    print(f"  DR value: {primary['dr_value']:.2f} "
          f"(CI {primary['dr_ci'][0]:.2f}-{primary['dr_ci'][1]:.2f}); "
          f"IS value: {primary['is_value']:.2f}; "
          f"FQE value: {primary['fqe_value']:.2f}; "
          f"agreement: {primary['method_agreement_score']:.2f}")
    print(f"  Cohort axes evaluated: "
          f"{len({c['axis'] for c in primary['cohort_results']})}; "
          f"insufficient-data cells: "
          f"{sum(1 for c in primary['cohort_results'] if not c.get('evaluable'))}")

    # Build OOD index for serving.
    ood_index = build_ood_index(trajectories, SAMPLE_REGIME)

    # Step 5: serve a recommendation for the index patient.
    print("\nStep 5: serve recommendation...")
    rec = serve_recommendation(
        patient_id=patient_id,
        patient_state=patient_state,
        regime=SAMPLE_REGIME,
        q_models=candidates[0]["models"],
        behavior_policy=behavior_policy,
        trajectories=trajectories,
        ood_index=ood_index,
        patient_profile=patient_profile,
    )
    print(f"  Recommendation id: {rec['recommendation_id']}; "
          f"outcome: {rec['outcome']}")
    if rec["outcome"] == "served":
        print(f"  Recommended action: {rec['recommended_action']}; "
              f"value: {rec['recommended_action_value']:.2f}; "
              f"OOD: {rec['ood_flag']}")
        print(f"  Validator passed: "
              f"{rec['clinician_narrative']['validator_status']}; "
              f"layers: "
              f"{rec['clinician_narrative']['validator_layers_passed']}")

    # Step 6: record an action-taken event. The clinician follows
    # the recommendation in the demo.
    print("\nStep 6: record action-taken...")
    if rec["outcome"] == "served":
        action_record = record_action_taken(
            rec["recommendation_id"],
            action_taken_payload={
                "action_id":   rec["recommended_action"],
                "rationale":   "regime_recommendation_aligned_with_judgment",
                "patient_share_decision": {
                    "shared":      True,
                    "method":      "in_visit_discussion",
                },
                "clinician_id": "clinician-0142",
            },
        )
        print(f"  Action taken kind: {action_record.get('action_taken_kind')}")

    # Step 6: run surveillance.
    print("\nStep 6: run surveillance...")
    alerts = run_surveillance(
        regime_id=SAMPLE_REGIME["regime_id"],
        surveillance_window={"id": f"window-{run_date}"},
        ope_baseline={"dr_value": primary["dr_value"]},
    )
    print(f"  Surveillance alerts: {len(alerts)}")

    elapsed = int(time.time() - start)
    print(f"\n=== Cycle complete in {elapsed}s ===")
    return {
        "trajectory_count":     len(trajectories),
        "behavior_policy":      behavior_policy["version"],
        "regime_candidates":    len(candidates),
        "ope_dr_value":         primary["dr_value"],
        "ope_dr_ci":            primary["dr_ci"],
        "recommendation_id":    rec.get("recommendation_id"),
        "recommended_action":   rec.get("recommended_action"),
        "validator_passed":     rec.get(
            "clinician_narrative", {}).get("validator_status"),
        "alerts":               len(alerts),
        "elapsed_seconds":      elapsed,
    }
```

---

## Demo Runner

```python
if __name__ == "__main__":
    # All sample data is SYNTHETIC. Do not use real PHI in
    # development. The demo:
    #   1. Generates 200 synthetic longitudinal trajectories with
    #      cohort distributions and an intentionally encoded
    #      Spanish-language access disparity for the OPE work
    #      to surface.
    #   2. Builds the index patient (Sara from the recipe's opening
    #      narrative): 52 years old, T2DM + CKD3b + HTN, currently
    #      on metformin + lisinopril + HCTZ + GLP-1, A1c 8.4,
    #      eGFR 41, ACR 78.
    #   3. Runs the full cycle: trajectory build, behavior-policy
    #      estimation, Q-learning training, multi-estimator OPE
    #      with cohort stratification, recommendation serving with
    #      eligibility / OOD / similar-trajectory / narrative,
    #      action capture, surveillance.
    #
    # The Bedrock call is mocked at the helper level so the demo
    # runs offline.
    #
    # TODO (TechWriter): Code review NOTE Finding 4. Add an
    # explicit "running offline against unprovisioned tables"
    # disclaimer here, and reframe the run_full_demo_cycle prints
    # to describe what each step would do in a provisioned
    # environment rather than what executes in the offline run.
    # Persistence calls are wrapped in try/except so the demo
    # completes; the print messages should not imply state
    # transitions that did not actually happen. Heavier
    # alternative: provide DynamoDB-Local + Kinesis-Local + S3-
    # mock docker-compose so the demo runs end-to-end.
    # TODO (TechWriter): Code review NOTE Finding 8. Replace
    # bare except Exception: pass around Kinesis put_record calls
    # (seven sites: build_trajectories, estimate_behavior_policy,
    # train_regime, run_ope, _emit_recommendation_event,
    # record_action_taken, run_surveillance, plus the
    # narrative_validator_fallback emit) with except Exception
    # as exc: logger.warning(...). The DynamoDB and S3 paths use
    # the better pattern; the Kinesis paths swallow failures
    # silently and a developer with logger.setLevel(WARNING) sees
    # nothing.

    print("=" * 70)
    print("Building synthetic patient (Sara) and seeding demo state...")
    print("=" * 70)

    run_date = _today_str()
    patient_id = "pat-009315"

    # Sara's profile from the recipe's opening narrative.
    sara_state = {
        "current_a1c":         8.4,
        "current_egfr":        41.0,
        "current_acr":         78.0,
        "current_systolic_bp": 134.0,
        "comorbidity_tier":    3.0,
        "polypharmacy_count":  7.0,
    }
    sara_profile = {
        "patient_id":             patient_id,
        "age":                    52,
        "age_band":               "50_to_59",
        "preferred_language":     "english",
        "race_ethnicity":         "white_non_hispanic",
        "t2dm_active":            True,
        "ckd_stage":              "3b",
        "htn_active":             True,
        "pregnancy_active":       False,
        "regime_consent_on_file": True,
    }

    # Mock Bedrock call so the demo runs offline.
    def _mock_bedrock(record, regime, validator_feedback=None,
                       strict_mode=False):
        rec_action = record.get("recommended_action", "no_action")
        rec_value = record.get("recommended_action_value", 0.0)
        rec_ci = record.get("recommended_action_ci", [0.0, 0.0])
        alts = record.get("alternative_actions", [])
        ood = record.get("ood_flag", False)
        top_alt = alts[0] if alts else {}

        return {
            "headline": (
                "For this patient, the regime suggests an SGLT2 "
                "inhibitor; estimated value modestly higher than the "
                "next alternative with overlapping intervals."
            ),
            "rationale": (
                "The state features driving this recommendation are "
                "eGFR 41 and ACR 78 (both favor renal protection), "
                "the comorbidity profile, and the prior care path. "
                "Several similar historical trajectories with comparable "
                "starting states received SGLT2 with stable eGFR and "
                "improved A1c at follow-up."
            ),
            "uncertainty": (
                f"OPE 95% CI is {rec_ci[0]:.2f} to {rec_ci[1]:.2f}. "
                f"OOD status: {'flagged' if ood else 'not flagged'}. "
                "Cohort-stratified estimates for this patient's "
                "combined cohort are consistent with the overall "
                "estimate."
            ),
            "alternatives_callout": (
                f"Top alternative: "
                f"{top_alt.get('action_id', 'none')} "
                f"with estimated value "
                f"{top_alt.get('value', 0):.2f}; the difference is "
                "small relative to the confidence intervals. Either "
                "action is defensible from the regime's perspective; "
                "the choice may reasonably depend on patient "
                "preferences, formulary, and tolerability."
            ),
            "regime_version_disclosure": (
                f"Regime version {regime['version']}, governance "
                f"status {regime['governance_status']}, decision-point "
                f"cadence {regime['decision_point_cadence']}."
            ),
            "override_encouragement": (
                "If clinical judgment or patient preference points to "
                "a different action, document the rationale; the "
                "regime is decision support, not a directive, and "
                "the clinician decides."
            ),
        }

    globals()["_bedrock_invoke_clinician_narrative"] = _mock_bedrock
    # TODO (TechWriter): Code review NOTE Finding 7. Add an
    # explanatory comment for the globals() mock-injection pattern:
    # this works because the calling functions resolve the
    # _bedrock_invoke_clinician_narrative name against the module
    # global namespace at call time, and globals() in __main__
    # returns this module's dict. Production never bypasses this;
    # the real Bedrock calls run.

    print(f"  Patient: {patient_id} (Sara)")
    print(f"  State: A1c {sara_state['current_a1c']}, "
          f"eGFR {sara_state['current_egfr']}, "
          f"ACR {sara_state['current_acr']}")

    print("\n" + "=" * 70)
    print("Running full demo cycle...")
    print("=" * 70)

    summary = run_full_demo_cycle(
        patient_id=patient_id,
        patient_state=sara_state,
        patient_profile=sara_profile,
        n_synthetic_patients=200,
        run_date=run_date,
    )

    print(f"\nSummary:")
    print(f"  trajectory_count:     {summary['trajectory_count']}")
    print(f"  behavior_policy:      {summary['behavior_policy']}")
    print(f"  regime_candidates:    {summary['regime_candidates']}")
    print(f"  ope_dr_value:         {summary['ope_dr_value']:.2f}")
    print(f"  ope_dr_ci:            "
          f"[{summary['ope_dr_ci'][0]:.2f}, "
          f"{summary['ope_dr_ci'][1]:.2f}]")
    print(f"  recommendation_id:    {summary['recommendation_id']}")
    print(f"  recommended_action:   {summary['recommended_action']}")
    print(f"  validator_passed:     {summary['validator_passed']}")
    print(f"  surveillance_alerts:  {summary['alerts']}")

    print("\n=== Demo complete ===")
```

---

## The Gap Between This and Production

Run this end-to-end against a real EHR with a curated regime catalog, real interaction databases, real patient features, real upstream signals from Recipes 4.5 through 4.9, real off-policy evaluation tooling, working SMART on FHIR review surface, and a clinical-informatics-led UX, and you will see the pattern: trajectory-pipeline plus sequential causal modeling plus multi-estimator OPE plus eligibility / OOD / similar-trajectory / narrative serving plus active surveillance plus governance discipline. The distance between this and a real EHR-integrated deployment is significant. Here is where it lives.

**Methodology validation against randomized-trial benchmarks.** Where SMART-trial data is available, the regime's OPE estimates should be benchmarked against the trial's primary analysis. Closeness to the randomized-trial point estimate, with overlapping confidence intervals, is the signal of methodological validity. Plan for at least 1.0 to 2.0 FTE during the methodology-validation phase (biostatistician with sequential-causal-inference experience, ML engineer with offline RL background).

**Multi-method estimator triangulation.** The example trains Q-learning only and notes the placeholders for offline RL, A-learning, and marginal structural models. Production runs at least three estimators, compares results, and flags disagreements for investigation. Useful tooling: d3rlpy for offline RL, DoWhy / EconML / CausalML for causal inference, the TargetTrialEmulation R package for sequential target trial emulation. Plan for the methodology infrastructure to take a substantial fraction of project engineering time.

**Sequential target trial emulation as the protocol.** The example records a stub protocol. Production specifies the protocol explicitly before training begins: hypothetical sequential-randomized trial, eligibility, treatment strategies under comparison, outcome definition, censoring, follow-up. Document in the regime catalog so OPE results can be interpreted against an explicit hypothetical experiment. Engage a biostatistician familiar with the Hernan-Robins target-trial framework.

**Behavior policy validation depth.** The example computes overall and cohort-stratified ECE and a hard threshold check. Production extends with reliability diagrams, per-class calibration, propensity overlap diagnostics, and sensitivity analysis to behavior-policy misspecification (perturbing the propensity model and observing how OPE results change). Make the behavior-policy validation an ongoing discipline; recurring miscalibration in a cohort is itself a signal worth surfacing.

**Off-policy evaluation rigor.** The example computes DR / IS / FQE with bootstrap intervals. Production adds per-decision-point importance sampling variants for long horizons, weighted importance sampling for variance control, model-based OPE with explicit Markov-property checks, and proper sensitivity bounds (Rosenbaum bounds, E-value where applicable, simulation-based perturbation). The headline OPE numbers should always include intervals, not just point estimates; deployment decisions made on point estimates are deployment decisions made on incomplete information.

**Cohort-stratified OPE everywhere.** The example computes per-cohort DR. Production runs every estimator per cohort, with sample-size minimums and explicit insufficient-data flags. Smaller cohorts produce wider intervals; the dishonest response is to suppress the result and report only the overall, the honest response is to surface the wide intervals and recommend cohort-specific data acquisition. Equity instrumentation is non-negotiable for this recipe; the Obermeyer 2019 finding is the canonical cautionary tale.

**Out-of-distribution detection.** The example uses k-NN extrapolation distance plus propensity floor / ceiling. Production combines density estimation in the state space (Gaussian mixture, normalizing flows, or learned representations), conformal-prediction outlier detection, and per-cohort OOD calibration. The OOD signal is information for the clinician, not necessarily a stop; the regime risk tier and clinical area drive the policy on whether OOD-flagged patients still receive a recommendation, receive one with explicit warnings, or are blocked.

**Reward-function governance and revision.** The example codes a fixed reward function. Production treats the reward as a curated artifact with a versioning policy: who can propose changes, what evidence is required, how parallel evaluation against the prior reward is run, what cohort-specific impact analysis must accompany the proposal, and what review cadence the governance committee maintains as outcomes accumulate. Reward-function changes are policy changes; treat them with the seriousness that implies.

**Real EHR / claims / lab / pharmacy / outcomes ingestion.** The example uses a synthetic generator. Production wires the trajectory pipeline against real source feeds with FHIR-native storage in HealthLake, structured ETL through Glue, and per-feed quality monitoring. Plan for at least 12 to 20 weeks of integration engineering per source system, with privacy-engineering review and minimum-necessary-access scoping per feed.

**SageMaker Feature Store integration.** The example reads from in-memory dicts. Production wires Feature Store online-store calls for the per-patient state vector with point-in-time-correct retrieval, feature freshness tracking, and per-feature schema versioning. The same Feature Store powers Recipes 4.5 through 4.9; centralizing the features is the entire point.

**SageMaker Model Registry for regime versioning.** The example writes a DynamoDB record. Production calls SageMaker.create_model_package on a serialized regime artifact in S3, with the OPE results, governance approval status, and cleared-for-decision-support metadata attached. Promotion is a registry transition tied to the governance committee's approval; deployment is an endpoint configuration update tied to the registered version.

**Real interaction database integration.** The example checks egfr against a hard-coded threshold. Production wires a licensed interaction database (First Databank, Lexicomp, Wolters Kluwer Medi-Span) into the contraindication checker, with caching for performance and full audit logging. Drug-drug, drug-disease, and drug-allergy checks need real data; recipe-level checks are a starting point, not a finishing point.

**SMART on FHIR clinician decision-support surface.** The example exposes serving as a Python function. Production wires an authenticated API Gateway endpoint consumed by a SMART on FHIR app embedded in the EHR. Plan for at least 12 to 20 weeks of EHR-integration engineering per EHR vendor, with authentication via the institution's identity provider (SAML or OIDC), PHI handling at the integration boundary, latency budgets, and the clinician workflow design. The surface UX is iterative; budget for clinical-informatics-led iteration after launch.

**Validator extension and per-layer alarms.** The example codes the four layers as a single function for readability. Production breaks the layers apart for testability and per-layer alarms: a fallback-rate spike on the prohibited-language layer indicates the LLM is drifting; a fallback-rate spike on the fact-grounding layer indicates the structured-context formatting may be obscuring the recommendation elements. Track per-layer fail rates as separate CloudWatch metrics.

**Bedrock cost and latency budget.** The clinician narrative uses a Sonnet-class model because the prompt is long-context and the validator's grounding rule is strict. At tens of thousands of recommendations per month, the budget is meaningful. Production tunes the model choice per audience and per validator pass-rate; consider routing first attempts to a smaller model with stricter prompts and falling back to Sonnet only on validator failure. Monitor Bedrock spend in CloudWatch and set per-account quota alarms.

**Patient-facing narrative.** The example focuses on the clinician narrative. Production supports an optional patient-facing narrative when the clinician chooses to share the recommendation, with reading-level matching, language localization, and the same four-layer validator with patient-specific prohibited-language patterns. Patient-facing communication of policy logic is iterative; the first version is rarely the version that lands.

**Cross-recipe orchestration with Recipes 4.5 through 4.9.** The example serves a stand-alone recommendation. Production wires real integrations with the per-treatment CATE estimates from 4.8 (input to the action-priority weighting), the personalized care plan from 4.9 (the broader plan in which the regime's recommendation fits), the adherence and engagement signals from 4.5 and 4.7 (state representation features), and the cohort modeling from 4.6 (cohort-aware regime selection). Document the cross-recipe data flow up front.

**Regime-deprecation and patient-impact handling.** When a regime version is deprecated, patients with active recommendations under the old version need clear handling: re-recommend under the new version at the next decision point, surface the change to the clinician with the rationale, and avoid silent regime swaps. The deprecation policy is part of the change control plan and should be reviewed by the governance committee.

**Operational privacy in trajectory storage and similar-trajectory retrieval.** The trajectory store encodes rich clinical journeys. The similar-trajectory retrieval surface returns information about other patients (de-identified, k-anonymity-checked, but still derived from real PHI). Apply tighter controls than for engagement data: narrower IAM read scopes, separate-table partitioning by sensitivity tier, additional CloudTrail data event capture, a documented minimum-necessary access policy. The k-anonymity threshold for similar-trajectory retrieval should be regime-specific and revisited as the data accumulates.

**Tracking-ID privacy.** The example uses opaque ids (`rec-{uuid}`, `traj-{uuid}`, `alert-{uuid}`) and never embeds patient_id or regime_id in identifiers. The discipline is intentional: plain-text patient_ids embedded in recommendation IDs (carried in EHR responses, recommendation API responses, narratives, and event payloads) are PHI leakage. Production must replace any composite-with-identifiable-fields ID with UUIDs or HMAC-SHA256 over the composite with a per-environment secret. Mirror the language flagged in 4.4 through 4.9.

**Step Functions orchestration with explicit DLQ coverage.** The example chains steps in a single Python function. Production runs training as a Step Functions state machine; serving as a Lambda triggered by the EHR-integration decision-point event; the action-taken worker as a Lambda on the Kinesis stream; the surveillance pipeline as a separate state machine. Each task has Catch handlers routing failures to per-stage SQS DLQs keyed on (run, recommendation_id, stage, failure_reason). The Kinesis-to-Lambda event source mappings configure explicit `OnFailure` destinations pointing to SQS, alarmed on DLQ depth. The recommendation path must fail safely: a serving failure returns "no recommendation available; clinician should proceed with judgment" rather than a partial or invalid recommendation. Mirror the language from 4.4 through 4.9.

**Idempotency and retry semantics.** Each stage's outputs are addressed by deterministic keys (recommendation_id, trajectory_id, alert_id) and writes are conditional. The example uses `ConditionExpression="attribute_not_exists(recommendation_id)"` on the recommendation put; production extends this discipline to every persistence boundary (idempotent surveillance metric writes, idempotent action-taken updates). A Step Functions retry that re-attempts a completed step is a no-op rather than a duplicate.

**VPC, encryption, and audit.** This example calls APIs over public AWS endpoints. A production Lambda handling PHI runs in a VPC with private subnets and VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock Runtime (interface), Kinesis (interface), CloudWatch Logs (interface), Step Functions, EventBridge (`events`), STS, API Gateway, HealthLake, and SageMaker. All five DynamoDB tables encrypt at rest with a customer-managed KMS key. CloudTrail data events are enabled for the regime-catalog, trajectory-metadata, recommendation-records, regime-versions, and surveillance-metrics tables. The audit posture for recommendation artifacts approaches clinical-record audit standards.

**Synthetic data and testing.** There are no tests in this example. A production pipeline needs unit tests for the trajectory builder, the behavior policy estimator, the Q-learning backward induction, the OPE estimators, the eligibility predicates, the OOD detector, the similar-trajectory retriever, the four validator layers, the action capture, and the surveillance pass; integration tests against synthetic Synthea-generated patient populations across cohort axes; regression tests that confirm the validator catches policy-as-directive language; load tests at expected volumes. Never use real PHI in non-production environments.

**FDA SaMD framework integration as an ongoing program.** Treat the regulatory analysis as a continuous deliverable. Model risk classification at scoping; predetermined change control plan as part of the initial submission (where SaMD applies); post-deployment surveillance with structured outcome tracking; regulatory legal review at every regime version promotion that includes a substantive change to the action catalog, the reward function, or the deployment posture. The Good Machine Learning Practice principles are a useful checklist; map your operational practices against them and identify the gaps. Confirm current FDA SaMD framework, the Predetermined Change Control Plan policy, the 21st Century Cures Act CDS exemption criteria, and the GMLP principles at the time of build; the regulatory landscape is evolving and the analysis is fact-specific.

**Patient consent posture.** Dynamic treatment regime recommendations use the patient's longitudinal trajectory data, including prior actions, outcomes, and (in many implementations) similar-trajectory cohorts of other patients. The consent framing should make this explicit: your care recommendations are informed by your own past care and outcomes and by the patterns observed in similar patients' care; we use this information with care and you can opt out. The institution's existing consent infrastructure typically does not have all of these granularities; expect to extend it. Consent revocation requires a defined data-handling pathway: revoking patients' contributions to training data, re-training without their data on the next cycle, removing them from similar-trajectory retrieval pools.

**Clinician engagement program.** Clinicians who do not understand what a policy is, what off-policy evaluation gives them, what an OOD flag means, and how to interpret a confidence interval will either reflexively follow or reflexively ignore the recommendation. Both modes produce poor outcomes. Invest in clinician education during the build (not at launch): structured rounds, journal-club-style sessions on the methodology papers, hands-on walkthroughs of the recommendation surface with simulated cases, and clinician-feedback loops that produce iteration on the surface design. Engagement is the difference between a regime that changes care and a regime that does not.

**Drift-driven retraining cadence.** The example flags drift via a single severity threshold. Production monitors multiple signals (calibration drift between predicted and realized outcomes, behavior-policy drift, distribution-shift in the patient population, action-catalog out-of-catalog rates) and ties retraining cadence to drift detection in addition to a scheduled baseline. The retraining cycle produces a new candidate that goes through OPE before promotion; promotion is governance-committee approved.

**Operational dashboards and runbooks.** Drift alarms, OOD-rate alarms, and cohort fairness alarms require runbooks that designate the responding teams (clinical leadership, data science, regulatory, operations) and the response protocols. A drift alarm without a runbook is an alarm that gets acknowledged and ignored. The runbooks are operational deliverables, not engineering ones; the regime is in production only when the runbooks exist and the response teams have rehearsed them.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 4.10: Dynamic Treatment Regime Recommendation](chapter04.10-dynamic-treatment-regime-recommendation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
