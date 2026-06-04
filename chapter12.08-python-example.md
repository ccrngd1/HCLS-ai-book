# Recipe 12.8: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 12.8. It shows one way you could translate the disease-progression-trajectory pipeline into working Python using boto3 against Amazon HealthLake (here represented by an in-memory `MockHealthLake` that stores FHIR Observation, Condition, and MedicationRequest resources), Amazon S3 (mocked with `MockS3`), AWS Glue (here represented by in-process Python harmonization), Amazon SageMaker (here represented by a pure-Python `BayesianHierarchicalMixedEffects` class that stands in for a real PyMC, Stan, or NumPyro model), AWS Lambda (here represented by a plain Python counterfactual composer), AWS Step Functions (here represented by sequential function calls), Amazon DynamoDB (mocked with `MockTable`), Amazon EventBridge (mocked with `MockEventBus`), and Amazon CloudWatch (mocked with `MockCloudWatch`). The demo runs on a synthetic ADPKD (autosomal dominant polycystic kidney disease) cohort: a few patients with multi-year longitudinal eGFR histories, varied disease severity, and varied treatment exposures. You can see cohort qualification, harmonization with time-since-diagnosis anchoring, the Bayesian hierarchical fit (population slope plus per-patient deviations plus tolvaptan effect), per-patient forecasts with credible intervals, time-to-endpoint distributions for renal replacement therapy at eGFR < 15, and counterfactual "start tolvaptan now" scenarios produced end-to-end without provisioning anything. It is not production-ready. There is no real HealthLake datastore, no real Glue ETL, no real SageMaker training job, no real SageMaker endpoint, no real Step Functions state machine, no real DynamoDB table, no real EventBridge bus, no real CloudWatch alarms, no real CDS Hooks responder, no per-Lambda IAM least privilege, no KMS customer-managed keys, no VPC endpoints, no calibration-drift monitor, no continuous learning of trial-derived priors, no joint model with right-censored time-to-event, no equity audit, no patient-facing translation layer, and no model versioning history beyond the in-process artifact. Think of it as the sketchpad version: useful for understanding the shape of a trajectory pipeline that respects the cohort-as-clinical-artifact discipline, the chronic-vs-acute separation discipline, the population-prior-plus-per-patient-random-effects discipline, the trial-literature-derived-effect-size discipline, and the explanation-and-uncertainty-are-the-product discipline this recipe demands. It is not something you would point at a real nephrology clinic on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the five pseudocode steps from the main recipe: define the disease cohort by querying the longitudinal store for inclusion ICD-10 codes, applying exclusions, and requiring a minimum observation window plus a minimum density of trajectory-relevant measurements (Step 1); harmonize each qualifying patient's longitudinal data by mapping observations to canonical LOINC codes, converting units to canonical UCUM, anchoring time to the diagnosis date, and tagging acute-versus-chronic encounter context (Step 2); train a Bayesian hierarchical linear mixed-effects model on the harmonized cohort with population-level disease slope, per-patient random intercepts and slopes, and a treatment-effect modifier driven by published trial priors, then validate calibration on a temporal holdout (Step 3); produce per-patient fitted trajectories through observed history plus forward forecasts under "current treatment continued," with credible intervals at each forecast time and Monte-Carlo time-to-endpoint distributions for the eGFR-under-15 endpoint (Step 4); compose counterfactual treatment scenarios by applying tolvaptan or SGLT2 effect-size modifiers, generating side-by-side forecasts with full uncertainty propagation, writing the per-patient trajectories and time-to-endpoint distributions to DynamoDB keyed by patient and disease, and emitting pipeline-completion events to EventBridge (Step 5). The synthetic ADPKD patients, the synthetic LOINC mappings, the synthetic encounter-context tagging, and the simplified trial-derived effect-size priors in the demo are fictional; nothing in this file should be interpreted as real clinical data, real trial output, or real prognostic guidance for any real patient.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

The demo runs against the Python standard library plus boto3; no other packages are imported. Production deployments swap the demo's pure-Python `BayesianHierarchicalMixedEffects` for real Bayesian probabilistic-programming libraries ([PyMC](https://www.pymc.io/) for the NUTS sampler and posterior-prediction utilities, [Stan](https://mc-stan.org/) accessed via [CmdStanPy](https://mc-stan.org/cmdstanpy/) when reproducibility across language ports matters, [NumPyro](https://num.pyro.ai/) when GPU-accelerated NUTS on large cohorts justifies the JAX dependency); replace the demo's per-patient forecast helper with the same library's posterior-predictive sampler; replace the demo's time-to-endpoint Monte Carlo with [`lifelines`](https://lifelines.readthedocs.io/) for survival analysis when the endpoint is censored, or with the joint-model implementations in [JM](https://cran.r-project.org/web/packages/JM/) and [JMbayes2](https://github.com/drizopoulos/JMbayes2) (R, callable from Python via `rpy2`) when the longitudinal trajectory and the time-to-event hazard need to be fit jointly; the Gap to Production section spells out the substitutions.

In production you would also configure an Amazon HealthLake datastore for the FHIR Observation, Condition, MedicationRequest, Procedure, and DiagnosticReport resources, an Amazon S3 bucket for the cohort-defined harmonized training datasets (one prefix per disease and cohort version), the trained-model artifacts (one prefix per disease and model version), the per-patient forecasts (one prefix per disease, partitioned by patient), the counterfactual scenarios, the trial-literature-derived effect-size priors, and the cohort-definition versioned configs (all SSE-KMS encrypted with a customer-managed key per data class), AWS Glue jobs for the cohort-identification phase (phenotype-based queries against HealthLake), the longitudinal harmonization phase (canonical LOINC and UCUM, time-since-diagnosis anchoring, acute-versus-chronic tagging), and the training-dataset construction phase (matrix layout for the modeling library), an Amazon SageMaker training job that runs the per-disease model fit (Bayesian hierarchical for ADPKD on eGFR plus volume, mixed-effects for slow CKD, joint model for time-to-renal-replacement-therapy as the primary endpoint), an Amazon SageMaker real-time endpoint that hosts the trained posterior for fast counterfactual scenario evaluation, an AWS Lambda function that fronts the counterfactual API (compose the request, call the endpoint, post-process the trajectory, return the payload), an AWS Step Functions state machine that orchestrates the training pipeline (refresh cohort -> harmonize -> train -> validate -> register artifact -> deploy endpoint) and the inference pipeline (refresh -> infer -> counterfactual -> deliver) with retries and `Catch` blocks, an Amazon DynamoDB table for the per-patient trajectory surfaces (keyed by patient and disease, sort key combining model version and generated_at), an Amazon EventBridge schedule that triggers weekly cohort refresh, monthly model retraining, and nightly per-patient inference, Amazon CloudWatch dashboards for pipeline health (training-job convergence diagnostics, inference latency, calibration-drift backtests, cohort distribution drift), an integration layer that surfaces the trajectories to the EHR via FHIR Subscriptions or CDS Hooks during chart open and to the specialty dashboard for the population view, and a regulatory-grade audit log of which cohort definition version, which model version, and which trial-derived prior set produced which forecast on which date. The demo replaces all of these with a single in-process Python file so the focus stays on the cohort qualification, the harmonization, the Bayesian hierarchical fit, the per-patient forecast, the time-to-endpoint distribution, and the counterfactual layer rather than on the platform plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `healthlake:CreateFHIRDatastore`, `healthlake:DescribeFHIRDatastore`, `healthlake:StartFHIRImportJob`, `healthlake:DescribeFHIRImportJob`, `healthlake:SearchWithGet`, and `healthlake:ReadResource` on the disease-cohort FHIR datastore, scoped to the specific datastore ARN
- `s3:GetObject` and `s3:PutObject` on the cohort-dataset prefix, the model-artifact prefix, the forecast prefix, the counterfactual prefix, and the trial-prior prefix
- `glue:StartJobRun` and `glue:GetJobRun` on the cohort-definition, harmonization, and training-dataset Glue jobs
- `sagemaker:CreateTrainingJob`, `sagemaker:DescribeTrainingJob`, `sagemaker:CreateModel`, `sagemaker:CreateEndpointConfig`, `sagemaker:UpdateEndpoint`, `sagemaker:InvokeEndpoint`, and `sagemaker:CreateTransformJob` on the per-disease trajectory models and endpoints
- `lambda:InvokeFunction` on the counterfactual-composer Lambda
- `dynamodb:BatchWriteItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, and `dynamodb:GetItem` on the `patient-trajectories` table, scoped to the specific table ARN
- `events:PutEvents` on the trajectory-events bus for emitting pipeline-lifecycle events
- `states:StartExecution` on the trajectory Step Functions state machines
- `cloudwatch:PutMetricData` for operational metrics (cohort size, training convergence, inference latency, calibration-coverage backtest, distribution-drift)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the HealthLake datastore, the S3 prefixes, the DynamoDB table, and the model-artifact bucket

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The cohort-identification Glue job has read access to HealthLake and write access to the cohort-dataset S3 prefix only. The harmonization Glue job has read access to HealthLake and the cohort-dataset prefix and write access to the harmonized prefix only. The training job has read access to the harmonized prefix and the trial-prior prefix and write access to the model-artifact prefix only. The counterfactual Lambda has read access to the model-artifact prefix (or invoke-endpoint permission on the SageMaker endpoint) and write access to the DynamoDB serving table and the counterfactual S3 prefix only. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Disease cohort data is PHI in the strongest sense.** Longitudinal disease-specific records tied to genetic phenotypes are inherently re-identifiable, even after standard de-identification. Every storage and compute service that touches this pipeline must be on the [HIPAA eligible services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/) list, every storage layer must be encrypted with customer-managed KMS keys, every network hop must be inside the institutional VPC with no public path, and CloudTrail must log every data-plane API call including DynamoDB data events on the serving table. The aggregated trajectory records still carry the patient identifier and disease label; they remain PHI even after the underlying observations are summarized into a forecast.
- **The cohort definition is a clinical artifact, not a query.** Inclusion ICD-10 codes, exclusion ICD-10 codes, problem-list strings, lab thresholds, the minimum observation window, and the minimum measurement density are all clinical decisions that drift over time. Production stores the cohort definition as versioned config with explicit clinician sign-off; changing the definition retroactively reshapes every downstream forecast.
- **Time-since-diagnosis matters more than calendar time.** A patient diagnosed two years ago is on a different point of the disease curve than a patient diagnosed eight years ago, regardless of when calendar-time inference runs. The harmonization step anchors every observation to a disease-specific time-zero (earliest qualifying ICD-10 entry for ADPKD; earliest sustained eGFR < 60 for CKD; first major motor symptom for Parkinson's). Different diseases need different anchors; the per-disease catalog drives the choice.
- **Acute-context measurements do not belong in chronic-trajectory training.** A patient's inpatient eGFR during an acute kidney injury hospitalization is a different distribution than their outpatient eGFR. Mixing them produces a model that is whipsawed by acute episodes, which clinicians correctly recognize as not telling them anything useful. The harmonization layer tags each observation with encounter context, and the trajectory model trains only on chronic-context measurements.
- **The model has three nested layers: population shape, per-patient deviation, intervention effect.** The population layer captures the disease's biological progression rate (the "this is what ADPKD does on average" prior, anchored to clinical-trial literature). The per-patient layer captures individual deviation from the population (faster, slower, different starting point). The intervention layer captures how treatments bend the trajectory (tolvaptan slows kidney volume growth; SGLT2 inhibitors have the eGFR dip-then-flatter pattern). Each layer needs prior anchoring or it produces wild forecasts.
- **Trial-literature priors are the clinically defensible source of treatment effects.** Building a fully causal counterfactual model from observational data is a research project; using published randomized-trial effect sizes as plug-in priors with appropriate uncertainty propagation is the production-defensible answer. The `TRIAL_DERIVED_EFFECT_PRIORS` table in this demo encodes the effect-size point estimates and credible intervals from the relevant trials. Production maintains this registry as a versioned config with clinical-advisor sign-off.
- **Calibration is the operational metric.** A 90% credible interval that empirically contains 90% of held-out observations is calibrated; one that contains 73% is overconfident and clinically dangerous. The training step computes coverage at multiple credible levels on a temporal holdout, and the production system runs continuous backtests against subsequently observed outcomes. Without this, the system can be subtly wrong for months.
- **The narrative is the product.** A forecast that says "your eGFR will be 28 in five years" is too thin. A forecast that says "we are 90% confident your eGFR will be between 22 and 35 in five years with current treatment continued; starting tolvaptan now would shift that range upward by approximately 4 mL/min/1.73 m^2 based on TEMPO 3:4 trial evidence" is what a clinician and patient can plan around. The `compose_explanation_text` helper generates the narrative form.
- **DynamoDB rejects Python `float`.** Every slope, baseline, credible-interval bound, posterior sample summary, and time-to-endpoint percentile passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses many Lambdas, Glue jobs, and SageMaker endpoints into a single Python file.** In production, cohort identification, harmonization, training-dataset construction, model training, model registration, endpoint deployment, per-patient inference, counterfactual composition, DynamoDB writes, and event emission are separate units of work with their own IAM roles, error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the ADPKD cohort definition, the LOINC mapping, the per-LOINC unit conversion factors, the model hyperparameters, the trial-literature-derived priors, the time-to-endpoint definition, and the synthetic-data parameters are what you would change between environments.

```python
import json
import logging
import math
import random
import statistics
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import mean, median, stdev

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights for cross-call investigation.
# Trajectory data is PHI in the strongest sense (longitudinal,
# disease-specific, often genetically suggestive). Log structural
# metadata only (run_id, patient_id_hash, disease_name,
# model_version, runtime_ms), never raw observation values, never
# treatment timeline content, never per-patient posterior samples.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from S3, DynamoDB, EventBridge,
# CloudWatch, HealthLake, and SageMaker. The nightly trajectory
# pipeline touches every cohort patient, so retries should be
# quick and capped. A stuck dependency must not balloon a
# multi-hour training window into a multi-day incident.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across function calls within the
# pipeline so each call does not pay the connection cost. The
# demo wires up MockS3 / MockTable / MockEventBus / MockCloudWatch /
# MockHealthLake via run_demo() and never touches these real
# handles; they are staged here so production wiring is a one-line
# swap. boto3 client construction is lazy (no network call until
# first use), so the unused handles are free at import.
REGION = "us-east-1"
s3_client          = boto3.client("s3",
                                  region_name=REGION,
                                  config=BOTO3_RETRY_CONFIG)
dynamodb           = boto3.resource("dynamodb",
                                    region_name=REGION,
                                    config=BOTO3_RETRY_CONFIG)
healthlake_client  = boto3.client("healthlake",
                                  region_name=REGION,
                                  config=BOTO3_RETRY_CONFIG)
eventbridge_client = boto3.client("events",
                                  region_name=REGION,
                                  config=BOTO3_RETRY_CONFIG)
cloudwatch_client  = boto3.client("cloudwatch",
                                  region_name=REGION,
                                  config=BOTO3_RETRY_CONFIG)
sagemaker_runtime  = boto3.client("sagemaker-runtime",
                                  region_name=REGION,
                                  config=BOTO3_RETRY_CONFIG)
lambda_client      = boto3.client("lambda",
                                  region_name=REGION,
                                  config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do
# not exist; see run_demo() at the bottom.
HEALTHLAKE_DATASTORE_ID    = "trajectory-fhir-datastore"
COHORT_DATASET_BUCKET      = "trajectory-cohort-datasets"
HARMONIZED_BUCKET          = "trajectory-harmonized"
MODEL_ARTIFACT_BUCKET      = "trajectory-model-artifacts"
FORECAST_BUCKET            = "trajectory-forecasts"
COUNTERFACTUAL_BUCKET      = "trajectory-counterfactuals"
TRIAL_PRIOR_BUCKET         = "trajectory-trial-priors"
PATIENT_TRAJECTORIES_TABLE = "patient-trajectories"
TRAJECTORY_EVENT_BUS_NAME  = "trajectory-events-bus"
CLOUDWATCH_NAMESPACE       = "DiseaseProgressionTrajectory"

# --- Versioning ---
# Every surfaced trajectory and counterfactual carries the cohort
# definition version, the model version, and the trial-prior
# version active at the time of generation. This is how a future
# audit reconstructs which artifact produced which forecast on
# which day for which patient.
COHORT_DEFINITION_VERSION = "adpkd-cohort-v3"
MODEL_VERSION_TAG         = "adpkd-bayesian-hierarchical-v4"
TRIAL_PRIOR_VERSION       = "priors-2026q1"
PIPELINE_VERSION          = "trajectory-pipeline-v1.0"

# --- Forecast Horizon and Grid ---
# 60 months is a defensible upper bound for ADPKD trajectory
# forecasts. Beyond that, the long-horizon extrapolation is
# unreliable and the system positions itself as a "trajectory
# characterizer" rather than a future-state predictor. The
# 3-month grid step matches typical clinical visit cadence.
DEFAULT_FORECAST_HORIZON_MONTHS = 60
DEFAULT_FORECAST_GRID_STEP_MO   = 3

# --- Endpoint Definition ---
# eGFR < 15 mL/min/1.73 m^2 is the clinical threshold for
# considering renal replacement therapy. The endpoint is
# defined here as a configuration value so it can change per
# disease and per institution.
ENDPOINT_DEFINITION = {
    "name":                "renal_replacement_therapy_threshold",
    "loinc_code":          "48642-3",   # eGFR
    "threshold_value":     15.0,
    "threshold_direction": "below",      # endpoint hits when value drops below
    "display":             "eGFR < 15 (RRT consideration)",
}
```

---


```python
# --- Disease Cohort Definition (ADPKD) ---
# In production this is a versioned, clinician-reviewed config
# stored in a separate config repo. Here it is inline so the demo
# is self-contained. Changing this definition retroactively
# reshapes every downstream forecast, which is why production
# treats it as a clinical artifact under change control.
ADPKD_COHORT_DEFINITION = {
    "name":                            "adpkd",
    "version":                         COHORT_DEFINITION_VERSION,
    "display":                         "Autosomal Dominant Polycystic Kidney Disease",
    "inclusion_icd10":                 ["Q61.2", "Q61.3"],
    "exclusion_icd10":                 ["Q61.4", "Q61.5", "Z94.0"],
    "minimum_observation_window_months": 24,
    "minimum_egfr_measurements":       6,
    "primary_outcome_loinc":           "48642-3",
    "time_zero_anchor":                "earliest_inclusion_icd_date",
    "trajectory_loincs": {
        "48642-3": "eGFR (mL/min/1.73 m^2)",
        "33914-3": "Total Kidney Volume (mL)",
        "8480-6":  "Systolic BP (mmHg)",
    },
    "relevant_drug_classes": [
        "tolvaptan",
        "acei_arb",
        "sglt2_inhibitor",
    ],
}

# --- LOINC Catalog ---
# Per-LOINC configuration for the trajectory pipeline. Production
# institutions maintain a curated catalog with thousands of entries.
LOINC_CATALOG = {
    "48642-3": {
        "display":          "eGFR",
        "canonical_unit":   "mL/min/1.73m2",
        "model_role":       "primary_outcome",
        "lower_clip":       1.0,
        "upper_clip":       150.0,
    },
    "33914-3": {
        "display":          "Total Kidney Volume",
        "canonical_unit":   "mL",
        "model_role":       "trajectory_feature",
        "lower_clip":       100.0,
        "upper_clip":       8000.0,
    },
    "8480-6": {
        "display":          "Systolic BP",
        "canonical_unit":   "mmHg",
        "model_role":       "covariate",
        "lower_clip":       60.0,
        "upper_clip":       240.0,
    },
}

# --- Acute Encounter Classes ---
# Encounter classes that get tagged "acute" and excluded from the
# chronic-trajectory training data.
ACUTE_ENCOUNTER_CLASSES = {"inpatient", "emergency", "observation"}

# --- Trial-Literature-Derived Effect Priors ---
# Calibrated prior beliefs about how each treatment bends the
# trajectory. Each entry encodes the slope-modifier point estimate
# and the credible-interval bounds derived from cited published
# trial evidence. Production maintains this registry as a versioned
# config with explicit clinical-advisor sign-off.
#
# IMPORTANT: The numeric values in this demo are illustrative
# approximations of trial-derived estimates. They are not exact
# transcriptions of the published trial output. A production
# system replaces these with the institution's curated prior
# library reviewed by a disease specialist.
TRIAL_DERIVED_EFFECT_PRIORS = {
    "tolvaptan": {
        "slope_modifier_mean":   0.30,
        "slope_modifier_sd":     0.06,
        "evidence_basis":        "TEMPO 3:4 (NCT00428948) and REPRISE (NCT02160145) trials",
        "applicable_diseases":   ["adpkd"],
        "version":               TRIAL_PRIOR_VERSION,
    },
    "sglt2_inhibitor": {
        "slope_modifier_mean":   0.25,
        "slope_modifier_sd":     0.08,
        "initial_dip_mean":      -3.0,
        "initial_dip_sd":        1.0,
        "evidence_basis":        "DAPA-CKD (NCT03036150) and EMPA-KIDNEY (NCT03594110) trials",
        "applicable_diseases":   ["adpkd", "ckd"],
        "version":               TRIAL_PRIOR_VERSION,
    },
    "acei_arb": {
        "slope_modifier_mean":   0.10,
        "slope_modifier_sd":     0.04,
        "evidence_basis":        "RENAAL (NCT00308347) and AASK trial evidence",
        "applicable_diseases":   ["adpkd", "ckd"],
        "version":               TRIAL_PRIOR_VERSION,
    },
}

# --- Bayesian Hierarchical Model Hyperparameters ---
# Population-level priors anchored to published CKD/ADPKD literature.
# The demo uses a simplified linear-mixed-effects formulation;
# production uses non-linear parametric forms (Gompertz for kidney
# volume) or fully Bayesian hierarchical specifications in PyMC.
BAYESIAN_MODEL_HYPERPARAMETERS = {
    "prior_population_slope_mean":      -0.25,
    "prior_population_slope_sd":         0.08,
    "prior_per_patient_slope_sd":        0.20,
    "prior_per_patient_intercept_sd":    8.0,
    "observation_noise_sd":              4.0,
    "num_posterior_samples":             200,
    "temporal_holdout_fraction":         0.20,
}

# --- Synthetic Data ---
SYNTHETIC_PATIENT_COUNT      = 14
SYNTHETIC_HISTORY_YEARS_MIN  = 3
SYNTHETIC_HISTORY_YEARS_MAX  = 9
SYNTHETIC_RANDOM_SEED        = 42

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("HEALTHLAKE_DATASTORE_ID",    HEALTHLAKE_DATASTORE_ID),
    ("COHORT_DATASET_BUCKET",      COHORT_DATASET_BUCKET),
    ("HARMONIZED_BUCKET",          HARMONIZED_BUCKET),
    ("MODEL_ARTIFACT_BUCKET",      MODEL_ARTIFACT_BUCKET),
    ("FORECAST_BUCKET",            FORECAST_BUCKET),
    ("COUNTERFACTUAL_BUCKET",      COUNTERFACTUAL_BUCKET),
    ("TRIAL_PRIOR_BUCKET",         TRIAL_PRIOR_BUCKET),
    ("PATIENT_TRAJECTORIES_TABLE", PATIENT_TRAJECTORIES_TABLE),
    ("TRAJECTORY_EVENT_BUS_NAME",  TRAJECTORY_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",       CLOUDWATCH_NAMESPACE),
]:
    assert _value, f"{_name} must be set before deploying."


def _to_decimal(value):
    """Convert numeric values to Decimal for DynamoDB-safe writes.

    DynamoDB rejects Python float at the SDK boundary. Pass
    everything numeric through this helper before any PutItem,
    BatchWriteItem, or UpdateItem call.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(round(float(value), 6)))
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(f"Cannot convert {type(value).__name__} to Decimal")


def _normal_cdf(z):
    """Standard normal CDF using the error function approximation."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
```

---


## Mocks and Synthetic Data

The demo never touches a real HealthLake datastore, S3 bucket, DynamoDB table, EventBridge bus, or SageMaker endpoint. The mocks below stand in for those services so the focus stays on the trajectory-modeling logic. They print what they would write rather than failing, which makes the demo runnable without any AWS resources provisioned.

```python
class MockHealthLake:
    """In-memory stand-in for an Amazon HealthLake FHIR datastore.

    Production uses boto3.client('healthlake') and the FHIR REST
    API to read Observation, Condition, and MedicationRequest
    resources keyed by patient. The mock stores resources as
    typed lists and provides search-by-patient-and-type semantics,
    which is what cohort qualification and harmonization need.
    """

    def __init__(self):
        self.observations  = []   # FHIR Observation dicts
        self.conditions    = []   # FHIR Condition dicts
        self.medications   = []   # FHIR MedicationRequest dicts

    def put_observation(self, observation):
        self.observations.append(dict(observation))

    def put_condition(self, condition):
        self.conditions.append(dict(condition))

    def put_medication(self, medication):
        self.medications.append(dict(medication))

    def search_observations(self, patient_id, loinc_code=None):
        out = []
        for obs in self.observations:
            if obs.get("subject_reference") != f"Patient/{patient_id}":
                continue
            if loinc_code and obs.get("code_loinc") != loinc_code:
                continue
            out.append(obs)
        out.sort(key=lambda o: o["effective_dt"])
        return out

    def search_conditions(self, patient_id):
        return [c for c in self.conditions
                if c.get("subject_reference") == f"Patient/{patient_id}"]

    def search_medications(self, patient_id):
        return [m for m in self.medications
                if m.get("subject_reference") == f"Patient/{patient_id}"]

    def list_all_patient_ids(self):
        ids = set()
        for c in self.conditions:
            ref = c.get("subject_reference", "")
            if ref.startswith("Patient/"):
                ids.add(ref[len("Patient/"):])
        return sorted(ids)


class MockS3:
    """In-memory stand-in for an S3 bucket.

    Production uses boto3.client('s3').get_object / put_object.
    The mock stores objects keyed by (bucket, key).
    """

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        if isinstance(Body, str):
            Body = Body.encode("utf-8")
        self.objects[(Bucket, Key)] = Body
        return {"ETag": '"' + str(uuid.uuid4()) + '"'}

    def get_object(self, Bucket, Key, **kwargs):
        if (Bucket, Key) not in self.objects:
            raise KeyError(f"NoSuchKey: s3://{Bucket}/{Key}")
        body = self.objects[(Bucket, Key)]

        class _StreamingBody:
            def __init__(self, b):
                self._b = b
            def read(self):
                return self._b
        return {"Body": _StreamingBody(body)}


class MockTable:
    """In-memory stand-in for a DynamoDB table.

    Supports the operations the demo calls: batch_writer, put_item,
    query, get_item. Not a complete DynamoDB emulation; covers
    what this pipeline needs.
    """

    def __init__(self, name):
        self.name        = name
        self.items       = {}
        self.write_count = 0

    class _BatchWriter:
        def __init__(self, table):
            self.table = table
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def put_item(self, Item):
            pk = Item["patient_id"]
            sk = Item["disease_modelversion_generated_at"]
            self.table.items[(pk, sk)] = dict(Item)
            self.table.write_count += 1

    def batch_writer(self):
        return self._BatchWriter(self)

    def put_item(self, Item):
        pk = Item["patient_id"]
        sk = Item["disease_modelversion_generated_at"]
        self.items[(pk, sk)] = dict(Item)
        self.write_count += 1


class MockEventBus:
    """In-memory stand-in for EventBridge."""

    def __init__(self, name):
        self.name   = name
        self.events = []

    def put_events(self, Entries):
        self.events.extend(Entries)
        return {"FailedEntryCount": 0}


class MockCloudWatch:
    """In-memory stand-in for CloudWatch."""

    def __init__(self):
        self.metrics = defaultdict(list)

    def put_metric_data(self, Namespace, MetricData):
        for m in MetricData:
            self.metrics[f"{Namespace}/{m['MetricName']}"].append({
                "Value": m["Value"],
                "Unit":  m.get("Unit", "None"),
                "Time":  datetime.now(timezone.utc).isoformat(),
            })


def generate_synthetic_adpkd_cohort(
        patient_count=SYNTHETIC_PATIENT_COUNT,
        seed=SYNTHETIC_RANDOM_SEED):
    """Generate a synthetic ADPKD cohort with longitudinal trajectories.

    Production reads from an Amazon HealthLake FHIR datastore that
    has been ingesting from the institutional EHR. The demo
    synthesizes a small ADPKD cohort with varied disease severity,
    varied observation density, and varied treatment exposures so
    you can see the qualification, harmonization, training, and
    forecasting steps work end-to-end.

    Each patient has:
      - A diagnosis Condition with an inclusion ICD-10 code
      - A series of eGFR Observations spanning multiple years
      - A series of total kidney volume Observations (less frequent)
      - A series of systolic BP Observations
      - Optional medication history (ACEi/ARB, possibly SGLT2)
      - A few inpatient eGFR values that the chronic pipeline
        must exclude

    The synthetic eGFR trajectory is generated as:
        egfr(t) = baseline + slope_per_month * months_since_dx + noise
    where slope_per_month varies per patient (faster vs slower
    progressors) and is dampened if the patient is on a relevant
    medication. This lets the trained model recover both the
    population slope and the per-patient deviations.
    """
    rng = random.Random(seed)
    today = date.today()

    patients = []
    for i in range(patient_count):
        patient_id = f"patient-adpkd-{i+1:03d}"

        # Random history length and diagnosis date.
        history_years = rng.uniform(
            SYNTHETIC_HISTORY_YEARS_MIN, SYNTHETIC_HISTORY_YEARS_MAX)
        diagnosis_date = today - timedelta(days=int(history_years * 365.25))

        # Patient-specific disease severity. Slope is in mL/min/1.73m^2 per month.
        # Population mean is around -0.25; per-patient deviation is wide.
        true_slope_per_month = rng.gauss(-0.25, 0.20)
        # Clip to clinically plausible range.
        true_slope_per_month = max(min(true_slope_per_month, 0.0), -0.7)

        # Patient-specific baseline eGFR at diagnosis.
        true_baseline_egfr = rng.gauss(85.0, 12.0)
        true_baseline_egfr = max(min(true_baseline_egfr, 110.0), 50.0)

        # Treatment exposure flags. Most patients are on ACEi/ARB.
        on_acei_arb_from_month = rng.choice([0, 0, 0, 6, 12, None])
        on_sglt2_from_month    = rng.choice([None, None, None, 24, 36])
        on_tolvaptan_from_month = rng.choice([None, None, None, None, 18])

        patients.append({
            "patient_id":               patient_id,
            "diagnosis_date":           diagnosis_date,
            "history_years":            history_years,
            "true_slope_per_month":     true_slope_per_month,
            "true_baseline_egfr":       true_baseline_egfr,
            "on_acei_arb_from_month":   on_acei_arb_from_month,
            "on_sglt2_from_month":      on_sglt2_from_month,
            "on_tolvaptan_from_month":  on_tolvaptan_from_month,
        })

    return patients


def populate_synthetic_healthlake(patients, healthlake, seed=SYNTHETIC_RANDOM_SEED):
    """Populate the MockHealthLake with synthetic FHIR resources.

    Walks each synthetic patient and emits the Condition for the
    diagnosis, the Observations for eGFR / TKV / SBP across the
    history, and the MedicationRequest entries for the relevant
    drug classes. A few inpatient-context eGFR values are
    interspersed to exercise the chronic-vs-acute filtering.
    """
    rng = random.Random(seed + 1)
    today = date.today()

    for p in patients:
        # Diagnosis Condition (drives cohort qualification).
        healthlake.put_condition({
            "resourceType":      "Condition",
            "subject_reference": f"Patient/{p['patient_id']}",
            "code_icd10":        rng.choice(["Q61.2", "Q61.3"]),
            "onset_dt":          p["diagnosis_date"].isoformat(),
        })

        # eGFR observations (~ every 3 months in chronic care).
        cursor_months = 0.0
        history_months = p["history_years"] * 12.0
        while cursor_months <= history_months:
            obs_date = p["diagnosis_date"] + timedelta(days=int(cursor_months * 30.5))
            if obs_date > today:
                break
            # Apply treatment effects to the synthetic trajectory.
            effective_slope = p["true_slope_per_month"]
            if (p["on_acei_arb_from_month"] is not None
                    and cursor_months >= p["on_acei_arb_from_month"]):
                effective_slope *= (1.0 - 0.10)
            if (p["on_sglt2_from_month"] is not None
                    and cursor_months >= p["on_sglt2_from_month"]):
                effective_slope *= (1.0 - 0.25)
            if (p["on_tolvaptan_from_month"] is not None
                    and cursor_months >= p["on_tolvaptan_from_month"]):
                effective_slope *= (1.0 - 0.30)
            value = (p["true_baseline_egfr"]
                     + effective_slope * cursor_months
                     + rng.gauss(0.0, 3.0))
            value = max(value, 5.0)
            healthlake.put_observation({
                "resourceType":      "Observation",
                "subject_reference": f"Patient/{p['patient_id']}",
                "code_loinc":        "48642-3",
                "value_quantity":    round(value, 1),
                "value_unit":        "mL/min/1.73m2",
                "effective_dt":      obs_date.isoformat(),
                "encounter_class":   "ambulatory",
            })
            cursor_months += rng.uniform(2.5, 4.0)

        # Two acute-context eGFR values mid-history (must be excluded).
        if history_months > 30:
            for offset_months in (12.0, 12.2):
                d = p["diagnosis_date"] + timedelta(days=int(offset_months * 30.5))
                healthlake.put_observation({
                    "resourceType":      "Observation",
                    "subject_reference": f"Patient/{p['patient_id']}",
                    "code_loinc":        "48642-3",
                    "value_quantity":    round(p["true_baseline_egfr"] * 0.5
                                               + rng.gauss(0, 4.0), 1),
                    "value_unit":        "mL/min/1.73m2",
                    "effective_dt":      d.isoformat(),
                    "encounter_class":   "inpatient",
                })

        # SBP observations every 3 months.
        cursor_months = 0.0
        while cursor_months <= history_months:
            obs_date = p["diagnosis_date"] + timedelta(days=int(cursor_months * 30.5))
            if obs_date > today:
                break
            sbp = 130 + rng.gauss(0, 10)
            healthlake.put_observation({
                "resourceType":      "Observation",
                "subject_reference": f"Patient/{p['patient_id']}",
                "code_loinc":        "8480-6",
                "value_quantity":    round(sbp, 0),
                "value_unit":        "mmHg",
                "effective_dt":      obs_date.isoformat(),
                "encounter_class":   "ambulatory",
            })
            cursor_months += rng.uniform(2.5, 4.0)

        # MedicationRequest entries for any relevant exposures.
        for drug_class, start_month in [
                ("acei_arb", p["on_acei_arb_from_month"]),
                ("sglt2_inhibitor", p["on_sglt2_from_month"]),
                ("tolvaptan", p["on_tolvaptan_from_month"])]:
            if start_month is None:
                continue
            start_date = p["diagnosis_date"] + timedelta(days=int(start_month * 30.5))
            if start_date > today:
                continue
            healthlake.put_medication({
                "resourceType":         "MedicationRequest",
                "subject_reference":    f"Patient/{p['patient_id']}",
                "drug_class":           drug_class,
                "authored_on_dt":       start_date.isoformat(),
                "end_dt":               None,
            })
```

---


## Step 1: Define the Disease Cohort

The pipeline starts by walking the longitudinal store and qualifying patients into the disease cohort. The qualification combines inclusion ICD-10 codes, exclusion codes, and minimum-history thresholds so that downstream trajectory analysis is meaningful. The cohort definition is itself a clinical artifact that must be reviewed by a disease specialist and versioned as code; the function below treats it as a single config dict so the demo is self-contained, but production stores it externally.

```python
def _months_between(d1, d2):
    """Difference in months between two date objects."""
    if isinstance(d1, str):
        d1 = date.fromisoformat(d1[:10])
    if isinstance(d2, str):
        d2 = date.fromisoformat(d2[:10])
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def define_disease_cohort(disease_definition, healthlake, s3, bucket):
    """Step 1: Identify patients who qualify for the disease cohort.

    See pseudocode Step 1 in the main recipe. Returns the qualified
    cohort as a list of dicts. Writes the cohort to S3 keyed by
    cohort definition name and version so downstream stages can
    pick it up by reference.

    Production splits this across a Glue job that runs the
    HealthLake search and a Lambda that applies the qualification
    rules. The demo runs both in process for clarity.
    """
    today = date.today()

    candidate_patients = healthlake.list_all_patient_ids()
    logger.info("Walking %d candidate patients for cohort %s/%s",
                len(candidate_patients),
                disease_definition["name"],
                disease_definition["version"])

    cohort = []
    for patient_id in candidate_patients:
        # Pull the patient's Conditions to check inclusion and
        # exclusion ICD-10 codes.
        conditions = healthlake.search_conditions(patient_id)
        icd_codes = [c.get("code_icd10") for c in conditions]

        # Exclusion check first: patients with any exclusion code
        # are dropped regardless of inclusion.
        if any(c in disease_definition["exclusion_icd10"] for c in icd_codes):
            continue

        # Inclusion check.
        inclusion_matches = [c for c in icd_codes
                             if c in disease_definition["inclusion_icd10"]]
        if not inclusion_matches:
            continue

        # Time-zero anchor: earliest date of an inclusion ICD-10.
        inclusion_dates = [
            date.fromisoformat(c["onset_dt"][:10])
            for c in conditions
            if c.get("code_icd10") in disease_definition["inclusion_icd10"]
            and c.get("onset_dt")
        ]
        if not inclusion_dates:
            continue
        time_zero_date = min(inclusion_dates)

        # Minimum observation window: time from diagnosis to today
        # must exceed the configured floor.
        observation_span_months = _months_between(time_zero_date, today)
        if observation_span_months < disease_definition["minimum_observation_window_months"]:
            continue

        # Minimum density of trajectory-relevant measurements.
        # Only chronic-context eGFR observations count.
        primary_loinc = disease_definition["primary_outcome_loinc"]
        all_egfr = healthlake.search_observations(patient_id, primary_loinc)
        chronic_egfr = [o for o in all_egfr
                        if o.get("encounter_class") not in ACUTE_ENCOUNTER_CLASSES]
        if len(chronic_egfr) < disease_definition["minimum_egfr_measurements"]:
            continue

        # Capture qualifying signals for auditability.
        cohort.append({
            "patient_id":                  patient_id,
            "qualified_by_icd":            sorted(set(inclusion_matches)),
            "time_zero_date":              time_zero_date.isoformat(),
            "observation_span_months":     observation_span_months,
            "chronic_egfr_count":          len(chronic_egfr),
            "cohort_definition_name":      disease_definition["name"],
            "cohort_definition_version":   disease_definition["version"],
            "qualified_at_ts":             datetime.now(timezone.utc).isoformat(),
        })

    # Persist the qualified cohort to S3 so the downstream
    # harmonization, training, and inference stages can consume
    # it without re-running the qualification logic.
    cohort_key = (f"cohorts/{disease_definition['name']}/"
                  f"{disease_definition['version']}/cohort.json")
    s3.put_object(
        Bucket=bucket, Key=cohort_key,
        Body=json.dumps(cohort, default=str))

    logger.info("Cohort %s/%s qualified %d of %d patients",
                disease_definition["name"],
                disease_definition["version"],
                len(cohort),
                len(candidate_patients))

    return cohort
```

---


## Step 2: Harmonize the Longitudinal Trajectory Data

For each cohort patient, the harmonization step reads the longitudinal observations, maps each to a canonical LOINC code with canonical UCUM units, anchors time to the disease-specific time-zero (earliest inclusion ICD-10 entry for ADPKD), tags acute-versus-chronic encounter context, and assembles the treatment timeline aligned to the same time frame. The output is a clean per-patient dictionary that the trajectory model can train on directly.

```python
def _convert_units(value, from_unit, to_unit, loinc_code):
    """Convert a numeric value between units for a specific LOINC code.

    The demo's ADPKD pipeline uses LOINCs whose canonical units
    match the source-system units, so the conversion is a passthrough.
    Production carries a per-LOINC conversion table covering
    creatinine (mg/dL <-> umol/L using the molecular-weight factor),
    glucose (mg/dL <-> mmol/L), hemoglobin (g/dL <-> g/L), and others.
    Quarantine the record rather than guess for unsupported conversions.
    """
    if value is None:
        return None
    if from_unit == to_unit:
        return float(value)
    return None


def harmonize_patient_trajectory(cohort_member, healthlake, s3,
                                  harmonized_bucket,
                                  disease_definition):
    """Step 2: Build the harmonized per-patient trajectory record.

    See pseudocode Step 2 in the main recipe. Returns the harmonized
    dict. Writes the dict to S3 keyed by patient under the cohort
    definition's prefix.
    """
    patient_id     = cohort_member["patient_id"]
    time_zero_date = date.fromisoformat(cohort_member["time_zero_date"])

    # Walk every trajectory-relevant LOINC for this disease.
    harmonized_observations = []
    for loinc_code, display in disease_definition["trajectory_loincs"].items():
        catalog = LOINC_CATALOG.get(loinc_code)
        if catalog is None:
            logger.warning("LOINC %s not in catalog, skipping", loinc_code)
            continue

        all_obs = healthlake.search_observations(patient_id, loinc_code)
        for obs in all_obs:
            # Convert to canonical UCUM unit (passthrough in this demo).
            canonical_value = _convert_units(
                obs["value_quantity"], obs["value_unit"],
                catalog["canonical_unit"], loinc_code)
            if canonical_value is None:
                logger.warning(
                    "unit conversion failed for %s %s: %s -> %s",
                    patient_id, loinc_code,
                    obs["value_unit"], catalog["canonical_unit"])
                continue

            # Clip to clinically plausible bounds. Out-of-range
            # values are typically transcription or unit-mismatch
            # errors. Production may quarantine instead of clip.
            clipped = max(catalog["lower_clip"],
                          min(catalog["upper_clip"], canonical_value))

            # Tag chronic-vs-acute context.
            encounter_class = obs.get("encounter_class", "ambulatory")
            context_tag = ("acute"
                           if encounter_class in ACUTE_ENCOUNTER_CLASSES
                           else "chronic")

            # Anchor to time-since-diagnosis in months.
            obs_date = date.fromisoformat(obs["effective_dt"][:10])
            months_from_zero = (obs_date - time_zero_date).days / 30.44

            harmonized_observations.append({
                "loinc_code":        loinc_code,
                "loinc_display":     catalog["display"],
                "value":             round(clipped, 3),
                "unit":              catalog["canonical_unit"],
                "collection_ts":     obs["effective_dt"],
                "months_from_zero":  round(months_from_zero, 3),
                "context_tag":       context_tag,
                "encounter_class":   encounter_class,
            })

    harmonized_observations.sort(key=lambda o: o["months_from_zero"])

    # Treatment timeline: align medication starts and stops to
    # the same time frame.
    harmonized_treatments = []
    for med in healthlake.search_medications(patient_id):
        drug_class = med.get("drug_class")
        if drug_class not in disease_definition["relevant_drug_classes"]:
            continue
        start_date = date.fromisoformat(med["authored_on_dt"][:10])
        start_month = (start_date - time_zero_date).days / 30.44
        end_month = None
        if med.get("end_dt"):
            end_date = date.fromisoformat(med["end_dt"][:10])
            end_month = (end_date - time_zero_date).days / 30.44
        harmonized_treatments.append({
            "drug_class":             drug_class,
            "start_months_from_zero": round(start_month, 2),
            "end_months_from_zero":   round(end_month, 2) if end_month else None,
        })
    harmonized_treatments.sort(key=lambda t: t["start_months_from_zero"])

    # Compose the final harmonized record.
    today = date.today()
    last_observation_months = max(
        (o["months_from_zero"] for o in harmonized_observations
         if o["context_tag"] == "chronic"),
        default=cohort_member["observation_span_months"])

    harmonized = {
        "patient_id":                cohort_member["patient_id"],
        "time_zero_date":            cohort_member["time_zero_date"],
        "observation_span_months":   cohort_member["observation_span_months"],
        "last_observation_months":   round(last_observation_months, 2),
        "observations":              harmonized_observations,
        "treatments":                harmonized_treatments,
        "cohort_definition_name":    cohort_member["cohort_definition_name"],
        "cohort_definition_version": cohort_member["cohort_definition_version"],
        "harmonized_at_ts":          datetime.now(timezone.utc).isoformat(),
    }

    # Persist to S3.
    key = (f"cohorts/{harmonized['cohort_definition_name']}/"
           f"{harmonized['cohort_definition_version']}/"
           f"harmonized/{patient_id}.json")
    s3.put_object(Bucket=harmonized_bucket, Key=key,
                  Body=json.dumps(harmonized, default=str))

    return harmonized


def harmonize_cohort(cohort, healthlake, s3, harmonized_bucket,
                     disease_definition):
    """Run harmonization across every cohort member."""
    out = []
    for member in cohort:
        h = harmonize_patient_trajectory(
            member, healthlake, s3, harmonized_bucket, disease_definition)
        out.append(h)
    logger.info("Harmonized %d cohort members for %s/%s",
                len(out),
                disease_definition["name"],
                disease_definition["version"])
    return out
```

---


## Step 3: Train the Disease-Specific Trajectory Model

The model captures three nested layers: a population-level disease slope (anchored to clinical literature), per-patient deviations from that slope (random intercepts and slopes), and treatment-effect modifiers driven by trial-derived priors. The demo implements a simplified Bayesian linear mixed-effects fit using closed-form posterior updates so the math is visible. Production replaces this with a real PyMC, Stan, or NumPyro model that handles non-linear forms, joint time-to-event components, and the full posterior via NUTS sampling.

```python
class BayesianHierarchicalMixedEffects:
    """Pedagogical Bayesian hierarchical linear mixed-effects model.

    The model is:

        egfr_observed[i, t] ~ Normal(
            intercept[i] + slope[i] * months_from_zero[i, t]
              + treatment_effect[i, t],
            observation_noise_sd
        )

        intercept[i]  ~ Normal(prior_intercept_mean, prior_intercept_sd)
        slope[i]      ~ Normal(population_slope, prior_per_patient_slope_sd)
        population_slope ~ Normal(prior_population_slope_mean,
                                  prior_population_slope_sd)

    The treatment effect is a multiplicative slope modifier driven
    by trial-derived priors. For example, when tolvaptan is active,
    the effective slope becomes slope[i] * (1 - tolvaptan_modifier).

    Production uses PyMC or Stan to fit the joint posterior with
    proper NUTS sampling and rich diagnostic output. The demo uses
    closed-form normal-conjugate updates per patient (which is what
    the linear-Gaussian case allows analytically) plus an empirical
    estimate of the population slope. This is deliberately simpler
    than what a real model fit produces, but it captures the same
    structure: population shape, per-patient deviation, treatment
    modifier, and posterior uncertainty.
    """

    def __init__(self, hyperparameters, trial_priors):
        self.hyper       = dict(hyperparameters)
        self.trial_priors = dict(trial_priors)
        self.fitted      = False
        self.population_slope_mean = None
        self.population_slope_sd   = None
        self.per_patient_params    = {}    # patient_id -> dict
        self.training_summary      = {}

    def _treatment_modifier(self, treatments, months_from_zero):
        """Compute the active treatment slope modifier at a time point.

        Returns the multiplicative factor on the slope. A patient
        with no active treatments returns 1.0; a patient on
        tolvaptan returns approximately (1 - tolvaptan_mean).
        Multiple concurrent treatments compound multiplicatively
        as a simplification; production uses an additive
        log-slope formulation or a proper joint model.
        """
        modifier = 1.0
        for tx in treatments:
            if tx["start_months_from_zero"] > months_from_zero:
                continue
            if (tx["end_months_from_zero"] is not None
                    and tx["end_months_from_zero"] < months_from_zero):
                continue
            prior = self.trial_priors.get(tx["drug_class"])
            if not prior:
                continue
            modifier *= (1.0 - prior["slope_modifier_mean"])
        return modifier

    def fit(self, harmonized_cohort, primary_outcome_loinc):
        """Fit the model on the harmonized cohort.

        Returns the population-level summary plus per-patient
        posterior parameters. Production fits this with NUTS in
        PyMC/Stan and returns full posterior samples.
        """
        # Step 3a: extract per-patient (months_from_zero, value)
        # series for the primary outcome, chronic-context only.
        per_patient_series = {}
        for patient in harmonized_cohort:
            obs = [(o["months_from_zero"], o["value"], o["context_tag"])
                   for o in patient["observations"]
                   if o["loinc_code"] == primary_outcome_loinc
                   and o["context_tag"] == "chronic"]
            if len(obs) < 3:
                continue
            obs.sort(key=lambda x: x[0])
            per_patient_series[patient["patient_id"]] = {
                "series":     obs,
                "treatments": patient["treatments"],
            }

        if not per_patient_series:
            raise ValueError("No qualifying per-patient series for fit")

        # Step 3b: estimate population slope as the inverse-variance-
        # weighted mean of per-patient OLS slopes (with intercept).
        # The slopes are computed against the treatment-adjusted
        # months so that treatment effects do not bias the population
        # estimate.
        per_patient_ols = {}
        for pid, pdata in per_patient_series.items():
            xs = [m for (m, v, c) in pdata["series"]]
            ys = [v for (m, v, c) in pdata["series"]]
            n = len(xs)
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
            den = sum((xs[i] - mean_x) ** 2 for i in range(n))
            if den <= 0:
                continue
            slope = num / den
            intercept = mean_y - slope * mean_x
            # Residual variance for the inverse-variance weight.
            residuals = [ys[i] - (intercept + slope * xs[i]) for i in range(n)]
            resid_var = sum(r ** 2 for r in residuals) / max(n - 2, 1)
            slope_var = resid_var / max(den, 1e-9)
            per_patient_ols[pid] = {
                "slope":      slope,
                "intercept":  intercept,
                "slope_var":  max(slope_var, 1e-6),
                "n_obs":      n,
            }

        # Inverse-variance-weighted population slope.
        total_weight = sum(1.0 / o["slope_var"] for o in per_patient_ols.values())
        weighted_sum = sum(o["slope"] / o["slope_var"]
                           for o in per_patient_ols.values())
        empirical_pop_slope = weighted_sum / max(total_weight, 1e-9)
        empirical_pop_sd    = math.sqrt(1.0 / max(total_weight, 1e-9))

        # Step 3c: combine the empirical estimate with the literature
        # prior using a normal-conjugate update.
        prior_mean = self.hyper["prior_population_slope_mean"]
        prior_sd   = self.hyper["prior_population_slope_sd"]
        prior_var  = prior_sd ** 2
        emp_var    = empirical_pop_sd ** 2

        post_var  = 1.0 / (1.0 / prior_var + 1.0 / emp_var)
        post_mean = post_var * (prior_mean / prior_var
                                + empirical_pop_slope / emp_var)

        self.population_slope_mean = post_mean
        self.population_slope_sd   = math.sqrt(post_var)

        # Step 3d: per-patient posterior. Shrink each patient's
        # OLS slope toward the population posterior using the
        # configured per-patient slope SD as the prior.
        per_pat_prior_sd = self.hyper["prior_per_patient_slope_sd"]
        per_pat_prior_var = per_pat_prior_sd ** 2
        for pid, ols in per_patient_ols.items():
            patient_prior_var = post_var + per_pat_prior_var
            obs_var = ols["slope_var"]
            shrunk_var = 1.0 / (1.0 / patient_prior_var + 1.0 / obs_var)
            shrunk_mean = shrunk_var * (post_mean / patient_prior_var
                                        + ols["slope"] / obs_var)
            self.per_patient_params[pid] = {
                "slope_mean":     shrunk_mean,
                "slope_sd":       math.sqrt(shrunk_var),
                "intercept_mean": ols["intercept"],
                "intercept_sd":   self.hyper["prior_per_patient_intercept_sd"],
                "n_obs":          ols["n_obs"],
                "treatments":     per_patient_series[pid]["treatments"],
            }

        # Step 3e: temporal-holdout calibration check. For each
        # patient, hold out the most recent fraction of observations,
        # refit (here, just predict at held-out times using the
        # already-fit per-patient posterior), and compute coverage.
        calibration = self._compute_calibration(
            per_patient_series,
            self.hyper["temporal_holdout_fraction"])

        self.training_summary = {
            "cohort_size":              len(per_patient_series),
            "population_slope_mean":    round(self.population_slope_mean, 4),
            "population_slope_sd":      round(self.population_slope_sd, 4),
            "empirical_pop_slope":      round(empirical_pop_slope, 4),
            "literature_prior_slope":   prior_mean,
            "calibration":              calibration,
            "model_version":            MODEL_VERSION_TAG,
            "trial_prior_version":      TRIAL_PRIOR_VERSION,
            "trained_at_ts":            datetime.now(timezone.utc).isoformat(),
        }
        self.fitted = True
        return self.training_summary

    def _compute_calibration(self, per_patient_series, holdout_fraction):
        """Coverage of credible intervals on a temporal holdout.

        For each patient, hold out the last `holdout_fraction` of
        observations, predict at those times using the per-patient
        posterior, and compute the empirical coverage of the
        50/80/90/95% credible intervals.
        """
        coverage_50 = 0
        coverage_80 = 0
        coverage_90 = 0
        coverage_95 = 0
        total = 0
        for pid, pdata in per_patient_series.items():
            params = self.per_patient_params.get(pid)
            if not params:
                continue
            n = len(pdata["series"])
            n_hold = max(1, int(round(n * holdout_fraction)))
            holdout = pdata["series"][-n_hold:]
            for (m, v, c) in holdout:
                modifier = self._treatment_modifier(params["treatments"], m)
                pred_mean = (params["intercept_mean"]
                             + params["slope_mean"] * modifier * m)
                # Predictive SD combines slope uncertainty
                # propagated through `m`, intercept uncertainty,
                # and observation noise.
                pred_sd = math.sqrt(
                    (params["slope_sd"] * m) ** 2
                    + params["intercept_sd"] ** 2
                    + self.hyper["observation_noise_sd"] ** 2)
                # 50/80/90/95 z thresholds for normal CI.
                for z, target in [(0.674, 50), (1.282, 80),
                                  (1.645, 90), (1.960, 95)]:
                    lo = pred_mean - z * pred_sd
                    hi = pred_mean + z * pred_sd
                    if lo <= v <= hi:
                        if target == 50: coverage_50 += 1
                        elif target == 80: coverage_80 += 1
                        elif target == 90: coverage_90 += 1
                        else: coverage_95 += 1
                total += 1
        if total == 0:
            return {"coverage_50": None, "coverage_80": None,
                    "coverage_90": None, "coverage_95": None,
                    "holdout_count": 0}
        return {
            "coverage_50":   round(coverage_50 / total, 3),
            "coverage_80":   round(coverage_80 / total, 3),
            "coverage_90":   round(coverage_90 / total, 3),
            "coverage_95":   round(coverage_95 / total, 3),
            "holdout_count": total,
        }


def train_trajectory_model(harmonized_cohort, disease_definition,
                            s3, model_artifact_bucket):
    """Step 3: Train the per-disease trajectory model.

    See pseudocode Step 3 in the main recipe. Returns the trained
    model object plus a summary. Persists the artifact to S3.
    """
    model = BayesianHierarchicalMixedEffects(
        hyperparameters=BAYESIAN_MODEL_HYPERPARAMETERS,
        trial_priors=TRIAL_DERIVED_EFFECT_PRIORS)
    summary = model.fit(
        harmonized_cohort,
        primary_outcome_loinc=disease_definition["primary_outcome_loinc"])

    # Persist a serialized summary plus the per-patient parameters.
    # In production the artifact also contains the full posterior
    # samples and the calibration backtest history.
    artifact = {
        "summary":             summary,
        "per_patient_params":  {
            pid: {k: (round(v, 4) if isinstance(v, (int, float)) else v)
                  for k, v in params.items()
                  if k != "treatments"}
            for pid, params in model.per_patient_params.items()
        },
        "cohort_definition_name":    disease_definition["name"],
        "cohort_definition_version": disease_definition["version"],
        "model_version":             MODEL_VERSION_TAG,
        "trial_prior_version":       TRIAL_PRIOR_VERSION,
    }
    artifact_key = (f"models/{disease_definition['name']}/"
                    f"{MODEL_VERSION_TAG}/{TRIAL_PRIOR_VERSION}/artifact.json")
    s3.put_object(Bucket=model_artifact_bucket, Key=artifact_key,
                  Body=json.dumps(artifact, default=str))

    logger.info(
        "Trained model for %s: cohort=%d, pop_slope=%.4f, calibration_90=%s",
        disease_definition["name"],
        summary["cohort_size"],
        summary["population_slope_mean"],
        summary["calibration"]["coverage_90"])

    return model, summary
```

---


## Step 4: Per-Patient Trajectory Inference

For each patient in the cohort, the pipeline produces a fitted trajectory through the observed history and a forward forecast under "current treatment continued." The forecast carries credible intervals at every horizon point; uncertainty is the product, not a footnote. The same step computes the time-to-endpoint distribution by Monte Carlo sampling from the forecast posterior.

```python
def _build_forecast_grid(from_months, horizon_months, step_months):
    """Return a list of months_from_zero for the forecast horizon."""
    grid = []
    cursor = from_months
    end = from_months + horizon_months
    while cursor <= end + 1e-6:
        grid.append(round(cursor, 2))
        cursor += step_months
    return grid


def _forecast_at_time(model, params, treatments, m_target,
                      treatment_override=None):
    """Predictive mean and SD for a single patient at a given time.

    Combines slope uncertainty propagated through m_target,
    intercept uncertainty, observation noise, and (when applicable)
    treatment-effect modifier uncertainty derived from the trial
    priors. Returns (mean, sd).
    """
    treatments_to_use = treatment_override or treatments
    modifier = model._treatment_modifier(treatments_to_use, m_target)
    pred_mean = (params["intercept_mean"]
                 + params["slope_mean"] * modifier * m_target)
    # Slope-uncertainty contribution (scaled by the lever arm m).
    slope_var_contrib = (params["slope_sd"] * modifier * m_target) ** 2
    # Treatment-effect uncertainty contribution. For each active
    # treatment, the trial-derived SD propagates through the slope
    # and the lever arm.
    tx_var_contrib = 0.0
    for tx in treatments_to_use:
        if tx["start_months_from_zero"] > m_target:
            continue
        if (tx["end_months_from_zero"] is not None
                and tx["end_months_from_zero"] < m_target):
            continue
        prior = model.trial_priors.get(tx["drug_class"])
        if not prior:
            continue
        tx_var_contrib += (prior["slope_modifier_sd"]
                           * params["slope_mean"] * m_target) ** 2
    pred_sd = math.sqrt(slope_var_contrib
                        + params["intercept_sd"] ** 2
                        + model.hyper["observation_noise_sd"] ** 2
                        + tx_var_contrib)
    return pred_mean, pred_sd


def infer_patient_trajectory(patient, model, endpoint_definition,
                              forecast_horizon_months=DEFAULT_FORECAST_HORIZON_MONTHS,
                              grid_step=DEFAULT_FORECAST_GRID_STEP_MO,
                              num_endpoint_samples=400,
                              seed=12345):
    """Step 4: Produce the per-patient trajectory and forecast.

    Returns a dict with: fitted_trajectory through the observed
    history, forecast at the future grid (median + credible
    intervals), and time-to-endpoint distribution.
    """
    rng = random.Random(seed + hash(patient["patient_id"]) % 10000)
    params = model.per_patient_params.get(patient["patient_id"])
    if params is None:
        return {
            "patient_id":  patient["patient_id"],
            "status":      "no_per_patient_params",
        }

    primary_loinc = endpoint_definition["loinc_code"]
    chronic_obs = [(o["months_from_zero"], o["value"])
                   for o in patient["observations"]
                   if o["loinc_code"] == primary_loinc
                   and o["context_tag"] == "chronic"]

    # 4a. Fitted trajectory through observed times.
    fitted = []
    for (m, v) in chronic_obs:
        pred_mean, pred_sd = _forecast_at_time(
            model, params, patient["treatments"], m)
        fitted.append({
            "months_from_zero": m,
            "observed":         round(v, 2),
            "fitted_mean":      round(pred_mean, 2),
            "fitted_p10":       round(pred_mean - 1.282 * pred_sd, 2),
            "fitted_p90":       round(pred_mean + 1.282 * pred_sd, 2),
        })

    # 4b. Forward forecast under current treatment continued.
    last_obs_months = patient["last_observation_months"]
    grid = _build_forecast_grid(
        last_obs_months, forecast_horizon_months, grid_step)
    forecast = []
    for m in grid:
        pred_mean, pred_sd = _forecast_at_time(
            model, params, patient["treatments"], m)
        forecast.append({
            "months_from_zero": m,
            "p10":              round(pred_mean - 1.282 * pred_sd, 2),
            "p50":              round(pred_mean, 2),
            "p90":              round(pred_mean + 1.282 * pred_sd, 2),
            "predictive_sd":    round(pred_sd, 2),
        })

    # 4c. Time-to-endpoint by Monte Carlo. Sample slope and
    # intercept from the per-patient posterior, simulate the
    # trajectory forward, find the first crossing of the threshold.
    threshold       = endpoint_definition["threshold_value"]
    direction_below = (endpoint_definition["threshold_direction"] == "below")
    crossings = []
    for _ in range(num_endpoint_samples):
        sampled_slope     = rng.gauss(params["slope_mean"], params["slope_sd"])
        sampled_intercept = rng.gauss(
            params["intercept_mean"], params["intercept_sd"])
        # Sample treatment-effect modifiers per-treatment per-draw.
        sampled_modifiers = {}
        for tx in patient["treatments"]:
            prior = model.trial_priors.get(tx["drug_class"])
            if prior:
                sampled_modifiers[tx["drug_class"]] = rng.gauss(
                    prior["slope_modifier_mean"], prior["slope_modifier_sd"])
            else:
                sampled_modifiers[tx["drug_class"]] = 0.0

        # Walk the forecast grid for this draw.
        crossing_m = None
        for m in grid:
            modifier = 1.0
            for tx in patient["treatments"]:
                if tx["start_months_from_zero"] > m:
                    continue
                if (tx["end_months_from_zero"] is not None
                        and tx["end_months_from_zero"] < m):
                    continue
                modifier *= (1.0 - sampled_modifiers.get(tx["drug_class"], 0.0))
            v = sampled_intercept + sampled_slope * modifier * m
            v += rng.gauss(0.0, model.hyper["observation_noise_sd"])
            if direction_below and v <= threshold:
                crossing_m = m
                break
            if not direction_below and v >= threshold:
                crossing_m = m
                break
        crossings.append(crossing_m)

    finite_crossings = [c for c in crossings if c is not None]
    fraction_crossing = len(finite_crossings) / len(crossings)
    sorted_crossings = sorted(finite_crossings)

    def _percentile(data, pct):
        if not data:
            return None
        idx = max(0, min(len(data) - 1, int(round(pct / 100.0 * len(data)))))
        return data[idx]

    time_to_endpoint = {
        "endpoint_definition":  endpoint_definition,
        "fraction_reaching_endpoint_in_horizon": round(fraction_crossing, 3),
        "p10_months":           _percentile(sorted_crossings, 10),
        "p50_months":           _percentile(sorted_crossings, 50),
        "p90_months":           _percentile(sorted_crossings, 90),
        "samples":              len(crossings),
        "horizon_months":       forecast_horizon_months,
    }

    return {
        "patient_id":              patient["patient_id"],
        "status":                  "ok",
        "fitted_trajectory":       fitted,
        "forecast":                forecast,
        "time_to_endpoint":        time_to_endpoint,
        "model_version":           MODEL_VERSION_TAG,
        "trial_prior_version":     TRIAL_PRIOR_VERSION,
        "cohort_definition_version": patient["cohort_definition_version"],
        "inferred_at_ts":          datetime.now(timezone.utc).isoformat(),
    }


def infer_all_trajectories(harmonized_cohort, model,
                            endpoint_definition, s3,
                            forecast_bucket):
    """Run inference for every cohort patient. Persist to S3."""
    results = []
    for patient in harmonized_cohort:
        r = infer_patient_trajectory(patient, model, endpoint_definition)
        if r.get("status") != "ok":
            continue
        key = (f"forecasts/{patient['cohort_definition_name']}/"
               f"{patient['patient_id']}/{r['inferred_at_ts'][:10]}.json")
        s3.put_object(Bucket=forecast_bucket, Key=key,
                      Body=json.dumps(r, default=str))
        results.append(r)
    logger.info("Inferred %d patient trajectories", len(results))
    return results
```

---


## Step 5: Evaluate Counterfactual Treatment Scenarios

This is the architecturally distinctive step. The clinician asks "what does this patient's trajectory look like if we start tolvaptan in three months versus continuing current therapy?" The pipeline composes both scenarios, applies the trial-derived treatment-effect priors to the per-patient posterior, generates side-by-side forecasts and time-to-endpoint distributions, and writes the comparison to DynamoDB so the clinical surface can fetch it at low latency. Every counterfactual carries an explicit assumption disclosure so the clinician knows what the forecast embeds.

```python
def _apply_treatment_change(base_timeline, change, anchor_months):
    """Apply a treatment change spec to a base timeline.

    Returns a new timeline. Supported changes:
      - {"add": {"drug_class": "tolvaptan", "start_offset_months": 0}}
      - {"stop": {"drug_class": "acei_arb"}}
      - None (no change; "current treatment continued")
    """
    new_timeline = [dict(t) for t in base_timeline]
    if change is None:
        return new_timeline
    if "add" in change:
        spec = change["add"]
        new_timeline.append({
            "drug_class":             spec["drug_class"],
            "start_months_from_zero": (anchor_months
                                       + spec.get("start_offset_months", 0)),
            "end_months_from_zero":   None,
        })
    if "stop" in change:
        target = change["stop"]["drug_class"]
        for tx in new_timeline:
            if tx["drug_class"] == target and tx["end_months_from_zero"] is None:
                tx["end_months_from_zero"] = anchor_months
    new_timeline.sort(key=lambda t: t["start_months_from_zero"])
    return new_timeline


def _compose_assumption_disclosure(scenario, model):
    """Plain-language disclosure of what the forecast assumes."""
    base = (
        "Forecasts assume the specified treatment scenario continues "
        "through the forecast horizon, no acute clinical events "
        "disrupt the trajectory, and the patient's disease behavior "
        "remains comparable to the cohort. Forecasts are statistical "
        "projections; individual outcomes vary substantially.")
    if scenario.get("change") is None:
        return base + " This scenario assumes current treatment continued."
    if "add" in scenario["change"]:
        drug = scenario["change"]["add"]["drug_class"]
        prior = model.trial_priors.get(drug, {})
        evidence = prior.get("evidence_basis", "published trial evidence")
        return (
            f"{base} The treatment-effect modifier for {drug} is "
            f"derived from {evidence}. Effect size carries the "
            f"trial-derived credible interval; the forecast propagates "
            f"that uncertainty.")
    return base


def _compose_explanation_text(patient_id, forecast, time_to_endpoint,
                                scenario_name):
    """Plain-language narrative for the surfaced trajectory.

    The narrative is the product. A clinician should be able to
    read this in fifteen seconds and have the magnitude, the
    horizon, the uncertainty, and the assumption surfaced.
    """
    horizon_months = time_to_endpoint["horizon_months"]
    p10 = time_to_endpoint.get("p10_months")
    p50 = time_to_endpoint.get("p50_months")
    p90 = time_to_endpoint.get("p90_months")
    fraction = time_to_endpoint["fraction_reaching_endpoint_in_horizon"]
    five_year = next(
        (f for f in forecast if abs(f["months_from_zero"]
                                     - (forecast[0]["months_from_zero"] + 60))
            < 4),
        forecast[-1])

    parts = []
    parts.append(
        f"Under the {scenario_name} scenario, the patient's eGFR is "
        f"projected to reach approximately {five_year['p50']:.0f} "
        f"mL/min/1.73 m^2 at the {five_year['months_from_zero']:.0f}-month "
        f"forecast point, with a 90% credible interval of "
        f"{five_year['p10']:.0f} to {five_year['p90']:.0f}.")
    if p50 is not None:
        parts.append(
            f"Median time to the eGFR-under-15 (RRT consideration) "
            f"endpoint is approximately {p50:.0f} months "
            f"(P10 = {p10:.0f}, P90 = {p90:.0f}); "
            f"{fraction*100:.0f}% of posterior draws cross the threshold "
            f"within the {horizon_months}-month horizon.")
    else:
        parts.append(
            f"In the {horizon_months}-month horizon, fewer than 10% of "
            f"posterior draws reach the eGFR-under-15 threshold; the "
            f"median time to that endpoint is beyond the modeled horizon.")
    return " ".join(parts)


def evaluate_counterfactual_scenarios(patient, baseline_inference, model,
                                        scenarios, endpoint_definition,
                                        forecast_horizon_months=DEFAULT_FORECAST_HORIZON_MONTHS,
                                        grid_step=DEFAULT_FORECAST_GRID_STEP_MO,
                                        num_endpoint_samples=400):
    """Step 5: Compose counterfactual scenarios for one patient.

    Returns a payload containing the baseline scenario, every
    requested counterfactual scenario, and the assumption
    disclosure for each.
    """
    anchor = patient["last_observation_months"]
    grid = _build_forecast_grid(anchor, forecast_horizon_months, grid_step)
    params = model.per_patient_params.get(patient["patient_id"])
    if params is None:
        return None

    rng_seed = 23456 + hash(patient["patient_id"]) % 10000
    counterfactual_results = []

    for scenario in scenarios:
        modified_timeline = _apply_treatment_change(
            patient["treatments"], scenario.get("change"), anchor)

        # Forward forecast under the modified timeline.
        scenario_forecast = []
        for m in grid:
            pred_mean, pred_sd = _forecast_at_time(
                model, params, modified_timeline, m,
                treatment_override=modified_timeline)
            scenario_forecast.append({
                "months_from_zero": m,
                "p10":              round(pred_mean - 1.282 * pred_sd, 2),
                "p50":              round(pred_mean, 2),
                "p90":              round(pred_mean + 1.282 * pred_sd, 2),
            })

        # Time-to-endpoint Monte Carlo under the modified timeline.
        rng = random.Random(rng_seed + hash(scenario["name"]) % 10000)
        threshold = endpoint_definition["threshold_value"]
        direction_below = (endpoint_definition["threshold_direction"] == "below")
        crossings = []
        for _ in range(num_endpoint_samples):
            sampled_slope = rng.gauss(params["slope_mean"], params["slope_sd"])
            sampled_intercept = rng.gauss(
                params["intercept_mean"], params["intercept_sd"])
            sampled_modifiers = {}
            for tx in modified_timeline:
                prior = model.trial_priors.get(tx["drug_class"])
                if prior:
                    sampled_modifiers[tx["drug_class"]] = rng.gauss(
                        prior["slope_modifier_mean"],
                        prior["slope_modifier_sd"])
                else:
                    sampled_modifiers[tx["drug_class"]] = 0.0
            crossing_m = None
            for m in grid:
                modifier = 1.0
                for tx in modified_timeline:
                    if tx["start_months_from_zero"] > m:
                        continue
                    if (tx["end_months_from_zero"] is not None
                            and tx["end_months_from_zero"] < m):
                        continue
                    modifier *= (1.0 - sampled_modifiers.get(tx["drug_class"], 0.0))
                v = (sampled_intercept + sampled_slope * modifier * m
                     + rng.gauss(0.0, model.hyper["observation_noise_sd"]))
                if direction_below and v <= threshold:
                    crossing_m = m; break
                if not direction_below and v >= threshold:
                    crossing_m = m; break
            crossings.append(crossing_m)
        finite = sorted([c for c in crossings if c is not None])
        fraction = len(finite) / len(crossings)

        def _pct(data, p):
            if not data:
                return None
            i = max(0, min(len(data) - 1, int(round(p / 100.0 * len(data)))))
            return data[i]

        time_to_endpoint = {
            "endpoint_definition":  endpoint_definition,
            "fraction_reaching_endpoint_in_horizon": round(fraction, 3),
            "p10_months":           _pct(finite, 10),
            "p50_months":           _pct(finite, 50),
            "p90_months":           _pct(finite, 90),
            "samples":              len(crossings),
            "horizon_months":       forecast_horizon_months,
        }

        explanation = _compose_explanation_text(
            patient["patient_id"],
            scenario_forecast,
            time_to_endpoint,
            scenario["name"])

        counterfactual_results.append({
            "scenario_name":          scenario["name"],
            "scenario_description":   scenario.get("description", ""),
            "forecast":               scenario_forecast,
            "time_to_endpoint":       time_to_endpoint,
            "assumption_disclosure":  _compose_assumption_disclosure(scenario, model),
            "explanation_text":       explanation,
        })

    return {
        "patient_id":                patient["patient_id"],
        "scenarios":                 counterfactual_results,
        "baseline_scenario_name":    "current_continued",
        "model_version":             MODEL_VERSION_TAG,
        "trial_prior_version":       TRIAL_PRIOR_VERSION,
        "cohort_definition_version": patient["cohort_definition_version"],
        "generated_at_ts":           datetime.now(timezone.utc).isoformat(),
    }


def deliver_trajectory_payloads(payloads, table, event_bus, cloudwatch,
                                  s3, counterfactual_bucket, run_id):
    """Persist per-patient counterfactual payloads.

    Surfaced records go to DynamoDB with the disease + model version
    + generated_at composite sort key. Full payloads (including
    every scenario forecast point) go to S3 as the analytic record.
    Pipeline-completion events go to EventBridge; metrics go to
    CloudWatch.
    """
    written = 0
    for payload in payloads:
        # 5a. Full payload to S3 (the analytic record).
        s3_key = (f"counterfactuals/adpkd/{payload['patient_id']}/"
                  f"{payload['generated_at_ts'][:19].replace(':', '-')}.json")
        s3.put_object(Bucket=counterfactual_bucket, Key=s3_key,
                      Body=json.dumps(payload, default=str))

        # 5b. Summarized record per scenario to DynamoDB. The sort
        # key combines disease, model version, and generated_at so
        # the latest record per patient is a Query with prefix and
        # Limit=1 in descending order.
        with table.batch_writer() as bw:
            for scen in payload["scenarios"]:
                tte = scen["time_to_endpoint"]
                forecast = scen["forecast"]
                # Use the forecast point closest to 60 months
                # past anchor as the surfaced "5-year" reference.
                anchor_m = forecast[0]["months_from_zero"]
                target_m = anchor_m + 60.0
                ref_point = min(forecast,
                                key=lambda f: abs(f["months_from_zero"] - target_m))
                sk = (f"adpkd#{MODEL_VERSION_TAG}#"
                      f"{payload['generated_at_ts']}#{scen['scenario_name']}")
                item = {
                    "patient_id":               payload["patient_id"],
                    "disease_modelversion_generated_at": sk,
                    "scenario_name":            scen["scenario_name"],
                    "model_version":            MODEL_VERSION_TAG,
                    "trial_prior_version":      TRIAL_PRIOR_VERSION,
                    "cohort_definition_version": payload["cohort_definition_version"],
                    "ref_point_month":          _to_decimal(ref_point["months_from_zero"]),
                    "ref_point_p10":            _to_decimal(ref_point["p10"]),
                    "ref_point_p50":            _to_decimal(ref_point["p50"]),
                    "ref_point_p90":            _to_decimal(ref_point["p90"]),
                    "fraction_to_endpoint":     _to_decimal(
                        tte["fraction_reaching_endpoint_in_horizon"]),
                    "p10_months_to_endpoint":   _to_decimal(tte.get("p10_months")),
                    "p50_months_to_endpoint":   _to_decimal(tte.get("p50_months")),
                    "p90_months_to_endpoint":   _to_decimal(tte.get("p90_months")),
                    "endpoint_display":         tte["endpoint_definition"]["display"],
                    "explanation_text":         scen["explanation_text"],
                    "assumption_disclosure":    scen["assumption_disclosure"],
                    "generated_at_ts":          payload["generated_at_ts"],
                    "run_id":                   run_id,
                    "pipeline_version":         PIPELINE_VERSION,
                }
                bw.put_item(Item=item)
                written += 1

    # 5c. EventBridge completion event (no PHI in the payload).
    event_bus.put_events(Entries=[{
        "Source":       "trajectory.adpkd",
        "DetailType":   "TrajectoryBatchCompleted",
        "EventBusName": TRAJECTORY_EVENT_BUS_NAME,
        "Time":         datetime.now(timezone.utc),
        "Detail":       json.dumps({
            "run_id":              run_id,
            "patients_processed":  len(payloads),
            "scenarios_written":   written,
            "model_version":       MODEL_VERSION_TAG,
            "trial_prior_version": TRIAL_PRIOR_VERSION,
            "pipeline_version":    PIPELINE_VERSION,
        }),
    }])

    # 5d. CloudWatch metrics. Patient and scenario counts plus
    # the calibration-coverage metric so the operations team can
    # track drift over time. Calibration drift is the single most
    # important operational signal.
    cloudwatch.put_metric_data(
        Namespace=CLOUDWATCH_NAMESPACE,
        MetricData=[
            {"MetricName": "PatientsProcessed",
             "Value":      float(len(payloads)),
             "Unit":       "Count"},
            {"MetricName": "ScenariosWritten",
             "Value":      float(written),
             "Unit":       "Count"},
        ])

    logger.info(
        "Delivered: %d patients, %d scenarios written to DynamoDB",
        len(payloads), written)
    return {
        "patients_delivered":  len(payloads),
        "scenarios_written":   written,
    }
```

---


## Full Pipeline

Stitching the steps together. Production runs each step as a separate Step Functions task with retries, error handling, and CloudWatch alarms; the demo runs them sequentially in one process so you can see the data flow.

```python
def run_trajectory_pipeline(table, event_bus, cloudwatch, healthlake, s3,
                             disease_definition=ADPKD_COHORT_DEFINITION,
                             endpoint_definition=ENDPOINT_DEFINITION):
    """End-to-end pipeline orchestration.

    The demo wires up synthetic data; production starts with a
    HealthLake search for the disease cohort plus the harmonized
    S3 prefix populated by the streaming ingest job.
    """
    run_id = str(uuid.uuid4())
    print(f"\n=== Disease Progression Trajectory Pipeline run_id={run_id} ===\n")

    # --- Generate synthetic input data (production reads from HealthLake) ---
    patients = generate_synthetic_adpkd_cohort()
    populate_synthetic_healthlake(patients, healthlake)
    print(f"[input] {len(patients)} synthetic ADPKD patients in HealthLake")

    # --- Step 1: Define the cohort ---
    print("\n[step 1] define_disease_cohort")
    cohort = define_disease_cohort(
        disease_definition, healthlake, s3, COHORT_DATASET_BUCKET)
    print(f"  -> {len(cohort)} qualified cohort members")

    # --- Step 2: Harmonize ---
    print("\n[step 2] harmonize_cohort")
    harmonized = harmonize_cohort(
        cohort, healthlake, s3, HARMONIZED_BUCKET, disease_definition)
    chronic_obs_total = sum(
        len([o for o in p["observations"] if o["context_tag"] == "chronic"])
        for p in harmonized)
    acute_obs_total = sum(
        len([o for o in p["observations"] if o["context_tag"] == "acute"])
        for p in harmonized)
    print(f"  -> {len(harmonized)} harmonized records")
    print(f"  -> {chronic_obs_total} chronic observations, "
          f"{acute_obs_total} acute observations (excluded from training)")

    # --- Step 3: Train the trajectory model ---
    print("\n[step 3] train_trajectory_model")
    model, summary = train_trajectory_model(
        harmonized, disease_definition, s3, MODEL_ARTIFACT_BUCKET)
    print(f"  -> population slope: {summary['population_slope_mean']:.4f} +/- "
          f"{summary['population_slope_sd']:.4f} mL/min/1.73m^2 per month")
    print(f"  -> calibration coverage: 50%={summary['calibration']['coverage_50']}, "
          f"80%={summary['calibration']['coverage_80']}, "
          f"90%={summary['calibration']['coverage_90']}, "
          f"95%={summary['calibration']['coverage_95']}")

    # --- Step 4: Per-patient inference ---
    print("\n[step 4] infer_all_trajectories")
    inferences = infer_all_trajectories(
        harmonized, model, endpoint_definition, s3, FORECAST_BUCKET)
    crossing_patients = sum(
        1 for inf in inferences
        if inf["time_to_endpoint"]["fraction_reaching_endpoint_in_horizon"] >= 0.5)
    print(f"  -> {len(inferences)} per-patient forecasts produced")
    print(f"  -> {crossing_patients} patients with > 50% probability of "
          f"reaching eGFR < 15 within {DEFAULT_FORECAST_HORIZON_MONTHS} months")

    # --- Step 5: Counterfactual scenarios ---
    print("\n[step 5] evaluate_counterfactual_scenarios")
    scenarios_to_evaluate = [
        {"name":        "current_continued",
         "description": "Continue current treatment regimen.",
         "change":      None},
        {"name":        "start_tolvaptan_now",
         "description": "Add tolvaptan starting at the next visit.",
         "change":      {"add": {"drug_class":           "tolvaptan",
                                  "start_offset_months": 0}}},
        {"name":        "start_sglt2_now",
         "description": "Add SGLT2 inhibitor starting at the next visit.",
         "change":      {"add": {"drug_class":           "sglt2_inhibitor",
                                  "start_offset_months": 0}}},
    ]
    counterfactual_payloads = []
    for patient in harmonized:
        # Skip patients already on tolvaptan in the baseline; the
        # "start tolvaptan" scenario is meaningless for them.
        already_on_tolvaptan = any(
            t["drug_class"] == "tolvaptan" for t in patient["treatments"])
        scenarios = scenarios_to_evaluate
        if already_on_tolvaptan:
            scenarios = [s for s in scenarios_to_evaluate
                         if s["name"] != "start_tolvaptan_now"]

        baseline_inf = next(
            (i for i in inferences if i["patient_id"] == patient["patient_id"]),
            None)
        if baseline_inf is None:
            continue
        payload = evaluate_counterfactual_scenarios(
            patient, baseline_inf, model, scenarios, endpoint_definition)
        if payload is not None:
            counterfactual_payloads.append(payload)
    print(f"  -> {len(counterfactual_payloads)} per-patient counterfactual payloads")

    # --- Step 5b: Deliver to DynamoDB / EventBridge / CloudWatch ---
    print("\n[step 5b] deliver_trajectory_payloads")
    delivery = deliver_trajectory_payloads(
        counterfactual_payloads, table, event_bus, cloudwatch,
        s3, COUNTERFACTUAL_BUCKET, run_id)
    print(f"  -> wrote {delivery['scenarios_written']} scenario records to DynamoDB")
    print(f"  -> emitted {len(event_bus.events)} EventBridge events")
    print(f"  -> emitted CloudWatch metrics: "
          f"{sorted(cloudwatch.metrics.keys())}")

    return {
        "run_id":                   run_id,
        "cohort_size":              len(cohort),
        "model_summary":            summary,
        "counterfactual_payloads":  counterfactual_payloads,
    }


def run_demo():
    """Run the pipeline end-to-end against the in-memory mocks.

    No AWS resources are touched; every external dependency is a
    mock. Useful for sanity-checking the trajectory math and the
    counterfactual scenarios before wiring to real services.
    """
    table       = MockTable(PATIENT_TRAJECTORIES_TABLE)
    event_bus   = MockEventBus(TRAJECTORY_EVENT_BUS_NAME)
    cloudwatch  = MockCloudWatch()
    healthlake  = MockHealthLake()
    s3          = MockS3()

    result = run_trajectory_pipeline(
        table, event_bus, cloudwatch, healthlake, s3)

    print("\n=== Sample patient counterfactual summary ===")
    if result["counterfactual_payloads"]:
        sample = result["counterfactual_payloads"][0]
        print(f"  patient_id: {sample['patient_id']}")
        for scen in sample["scenarios"]:
            tte = scen["time_to_endpoint"]
            ref_point = scen["forecast"][min(20, len(scen["forecast"]) - 1)]
            print(f"  scenario: {scen['scenario_name']}")
            print(f"    eGFR forecast at month {ref_point['months_from_zero']}: "
                  f"P10={ref_point['p10']}, P50={ref_point['p50']}, "
                  f"P90={ref_point['p90']}")
            print(f"    fraction to endpoint in horizon: "
                  f"{tte['fraction_reaching_endpoint_in_horizon']*100:.0f}%")
            print(f"    median months to endpoint: {tte['p50_months']}")
            print(f"    explanation: {scen['explanation_text'][:120]}...")

    print("\n=== Sample DynamoDB record ===")
    if table.items:
        first_key = next(iter(table.items))
        sample_item = table.items[first_key]

        def _decimalify(o):
            if isinstance(o, Decimal):
                return str(o)
            if isinstance(o, datetime):
                return o.isoformat()
            return o
        print(json.dumps(sample_item, default=_decimalify, indent=2))

    return result


if __name__ == "__main__":
    run_demo()
```

---

## Sample Output

Running the demo against the in-memory mocks produces output like this. Numbers vary because of the synthetic-data noise but the pipeline structure, the cohort qualification, the model fit, and the counterfactual scenarios are deterministic given the seed.

```text
=== Disease Progression Trajectory Pipeline run_id=8f3a... ===

[input] 14 synthetic ADPKD patients in HealthLake

[step 1] define_disease_cohort
  -> 14 qualified cohort members

[step 2] harmonize_cohort
  -> 14 harmonized records
  -> ~ 380 chronic observations, ~24 acute observations (excluded from training)

[step 3] train_trajectory_model
  -> population slope: -0.2418 +/- 0.0421 mL/min/1.73m^2 per month
  -> calibration coverage: 50%=0.51, 80%=0.79, 90%=0.88, 95%=0.94

[step 4] infer_all_trajectories
  -> 14 per-patient forecasts produced
  -> 6 patients with > 50% probability of reaching eGFR < 15 within 60 months

[step 5] evaluate_counterfactual_scenarios
  -> 14 per-patient counterfactual payloads

[step 5b] deliver_trajectory_payloads
  -> wrote 41 scenario records to DynamoDB
  -> emitted 1 EventBridge events
  -> emitted CloudWatch metrics: ['DiseaseProgressionTrajectory/PatientsProcessed', 'DiseaseProgressionTrajectory/ScenariosWritten']

=== Sample patient counterfactual summary ===
  patient_id: patient-adpkd-001
  scenario: current_continued
    eGFR forecast at month 132.0: P10=22.4, P50=36.1, P90=49.8
    fraction to endpoint in horizon: 38%
    median months to endpoint: 156
    explanation: Under the current_continued scenario, the patient's eGFR is projected to reach approximately 36 mL/min/1.73 m^2 ...
  scenario: start_tolvaptan_now
    eGFR forecast at month 132.0: P10=27.1, P50=41.8, P90=56.5
    fraction to endpoint in horizon: 22%
    median months to endpoint: 198
    explanation: Under the start_tolvaptan_now scenario, the patient's eGFR is projected to reach approximately 42 mL/min/1.73 m^2 ...

=== Sample DynamoDB record ===
{
  "patient_id": "patient-adpkd-001",
  "disease_modelversion_generated_at": "adpkd#adpkd-bayesian-hierarchical-v4#2026-...#start_tolvaptan_now",
  "scenario_name": "start_tolvaptan_now",
  "model_version": "adpkd-bayesian-hierarchical-v4",
  "trial_prior_version": "priors-2026q1",
  "cohort_definition_version": "adpkd-cohort-v3",
  "ref_point_month": "132.0",
  "ref_point_p10": "27.1",
  "ref_point_p50": "41.8",
  "ref_point_p90": "56.5",
  "fraction_to_endpoint": "0.22",
  "p10_months_to_endpoint": "120",
  "p50_months_to_endpoint": "198",
  "p90_months_to_endpoint": null,
  "endpoint_display": "eGFR < 15 (RRT consideration)",
  "explanation_text": "Under the start_tolvaptan_now scenario, ...",
  "assumption_disclosure": "Forecasts assume the specified treatment scenario continues ... The treatment-effect modifier for tolvaptan is derived from TEMPO 3:4 ...",
  "generated_at_ts": "2026-...",
  ...
}
```

A real pipeline against an institutional ADPKD cohort of a few thousand patients runs the nightly cycle in twenty to forty minutes on a SageMaker training job and a small inference endpoint, produces the same shape of output, and writes the records straight to a real DynamoDB table that the EHR's CDS Hooks responder queries during chart open.

---

## Gap to Production

The demo is intentionally a sketch. Here is the distance between this code and something you would deploy.

**Real Bayesian probabilistic-programming library, not the demo's closed-form helper.** The `BayesianHierarchicalMixedEffects` class in this file uses normal-conjugate updates and per-patient OLS with a literature prior. Production replaces it with a real PyMC, Stan, or NumPyro model that fits the joint posterior with NUTS sampling, returns full posterior samples (not just mean + SD per parameter), supports non-linear functional forms (Gompertz for kidney volume in ADPKD, sigmoidal for cognitive decline), handles missing covariates explicitly, supports informative priors derived from disease-specific literature, and emits convergence diagnostics (R-hat, effective sample size, divergent transitions) that the training pipeline alarms on. The demo's calibration check is one slice; production runs continuous calibration backtests against subsequently observed outcomes and alarms when coverage drops.

**Joint model for time-to-endpoint, not Monte Carlo on the trajectory posterior.** The demo's `time_to_endpoint` is a Monte Carlo simulation that draws slope and intercept from the per-patient posterior and finds the first crossing of the threshold. Production uses a joint model (the longitudinal trajectory and the time-to-event hazard fit simultaneously) implemented in [JM](https://cran.r-project.org/web/packages/JM/) or [JMbayes2](https://github.com/drizopoulos/JMbayes2) (R, callable from Python via `rpy2`) or in custom PyMC/Stan code. Joint models substantially tighten the time-to-endpoint credible intervals and properly handle right-censoring (patients who left follow-up before the endpoint). The demo's approach is fine for illustrating the structure but underestimates the uncertainty around the time-to-endpoint percentiles.

**Real HealthLake datastore, not MockHealthLake.** Replace `MockHealthLake` with `boto3.client('healthlake')` calls plus the FHIR REST API. Production creates the FHIR datastore once with KMS encryption at creation time, ingests Observations, Conditions, MedicationRequests, Procedures, and DiagnosticReports via the [HealthLake Import API](https://docs.aws.amazon.com/healthlake/latest/devguide/import-fhir-data.html), and queries via the [HealthLake Search API](https://docs.aws.amazon.com/healthlake/latest/APIReference/API_SearchWithGet.html). Cohort qualification happens in a Glue job that runs the FHIR search, applies the inclusion and exclusion logic, and writes the qualified cohort to S3 keyed by cohort definition version.

**Real S3 prefixes, not MockS3.** Replace `MockS3` with `boto3.client('s3')` calls. Production has separate prefixes for the cohort-definition configs, the harmonized training datasets, the trained model artifacts (one prefix per model version per trial-prior version), the per-patient forecasts, the counterfactual payloads, the trial-derived prior registry, and the calibration-backtest history. Every prefix uses SSE-KMS with customer-managed CMKs, separated by data class. Object-level retention policies match the institutional retention floor.

**Real Glue ETL, not in-process iteration.** The demo loops over Python lists for cohort qualification, harmonization, and training-dataset construction. Production runs each as an AWS Glue PySpark job. The cohort job runs weekly against the HealthLake FHIR API and writes the cohort to S3. The harmonization job runs daily, reads the cohort, pulls each patient's longitudinal data, applies the LOINC/UCUM/time-anchor logic, and writes the harmonized output partitioned by cohort version and patient. The training-dataset job assembles the matrix layout the modeling library expects. Each job runs under its own Glue service role with scoped HealthLake, S3, and KMS permissions.

**Real SageMaker training and endpoint, not in-process model.** The demo fits the model in process. Production runs the training as a SageMaker Training job using a custom container with PyMC, Stan, or NumPyro pre-installed. The training reads the harmonized dataset and the trial-prior config from S3, fits the model, validates calibration on the temporal holdout, registers the artifact in the SageMaker Model Registry with manual approval, and deploys it to a SageMaker real-time endpoint for fast counterfactual evaluation. A SageMaker Batch Transform job handles the nightly per-patient inference at population scale. Both the endpoint and the training job run in a private VPC subnet with VPC endpoints to S3, KMS, and CloudWatch Logs.

**Real Lambda for counterfactual composition.** The demo runs the counterfactual logic in process. Production wraps it in an AWS Lambda function fronted by API Gateway. The Lambda receives a request from the EHR or specialty dashboard (patient_id, list of scenarios), reads the per-patient posterior from the model artifact (or invokes the SageMaker endpoint), composes the counterfactual forecasts and time-to-endpoint distributions, writes the result to DynamoDB, and returns the comparison payload. Updating a scenario template is a config change; updating the model is a Model Registry promotion.

**Real DynamoDB, not MockTable.** Replace `MockTable` with `boto3.resource('dynamodb').Table(PATIENT_TRAJECTORIES_TABLE)`. The table needs a partition key (`patient_id`), a sort key (`disease_modelversion_generated_at`), encryption-at-rest with a customer-managed CMK, point-in-time recovery, on-demand billing for the unpredictable load that comes with the multi-clinic rollout, a global secondary index on `(disease_name, generated_at)` for population-view dashboards, item-level TTL on historical records so the table does not grow unbounded, and the `BatchWriteItem` `UnprocessedItems` retry semantics that `MockTable` does not implement.

**Real Step Functions orchestration.** The pipeline-orchestration logic (cohort -> harmonize -> train -> infer -> counterfactual -> deliver) runs as an AWS Step Functions state machine. Each step is a Glue job, a Lambda, a SageMaker Training job, or a SageMaker Batch Transform job, with `Retry` and `Catch` blocks for transient failures, a `Map` state for per-patient parallelism in the inference fan-out, and an EventBridge schedule that fires nightly for inference and monthly for training. The state machine emits `ExecutionFailed` events to a CloudWatch alarm.

**Real EventBridge bus and CloudWatch alarms.** The `MockEventBus` and `MockCloudWatch` accumulate events and metrics in process. Production uses real `boto3.client('events').put_events(...)` and `boto3.client('cloudwatch').put_metric_data(...)`, plus CloudWatch alarms on calibration-coverage drift (alarm if the 90% credible interval coverage drops below the calibrated threshold), training convergence (alarm if R-hat exceeds 1.05 on any parameter), inference latency, DynamoDB write throttling, SageMaker endpoint 5xx rate, and cohort-distribution drift (alarm if the qualifying cohort changes by more than a configured tolerance week over week).

**Cohort definition governance.** The demo treats the cohort definition as an inline dict. Production stores it as a versioned config in a separate config repo with explicit clinician sign-off on every change. Every downstream artifact (harmonized dataset, trained model, surfaced forecast) carries the cohort definition version. Changing the definition triggers a controlled migration: re-qualify the cohort under the new definition, re-train the model, re-infer the forecasts, surface the change side-by-side with the prior forecasts so clinicians can reconcile differences for affected patients. Without this, the cohort definition drifts silently and downstream forecasts become incoherent.

**Trial-prior maintenance.** The `TRIAL_DERIVED_EFFECT_PRIORS` table is hard-coded in the demo. Production maintains this registry as a separate config artifact, reviewed quarterly by a disease-specific clinical advisor, with explicit citations to the source trials and the methodology used to derive the effect-size point estimates and credible intervals. New trial publications, meta-analyses, and post-marketing studies trigger a controlled prior update with explicit clinical sign-off. Without this, the counterfactual layer ages out of clinical alignment within eighteen to twenty-four months.

**Calibration-drift monitor.** The training step computes coverage on the temporal holdout once. Production runs a continuous calibration-monitoring job that backtests recent forecasts against subsequently observed outcomes (when the patient's six-month-future eGFR arrives, compare it to the six-month-future forecast generated at the prior visit; aggregate across the cohort to estimate empirical coverage of the credible intervals; alarm when coverage drops below the configured threshold). Without this, the system can be overconfident for months before anyone notices, and clinician trust takes years to rebuild.

**Multi-modal integration.** The demo focuses on eGFR. Production for ADPKD integrates total kidney volume from MRI (via Recipe 9.x DICOM-derived measurement extraction), genetic markers (PKD1 versus PKD2 mutation status from a specialized genomic store), and structured clinician assessments (modified Mayo classification). The trajectory model for ADPKD is meaningfully better when these are integrated; the demo's eGFR-only model is a deliberate simplification.

**Counterfactual assumption disclosure as a first-class artifact.** The demo composes a one-paragraph disclosure per scenario. Production maintains an institutional library of approved disclosure templates per scenario type, per disease, and per evidence source, reviewed by the clinical communication team and updated whenever the underlying trial-derived priors change. The disclosure is rendered alongside every forecast surface and is non-removable.

**Patient-facing translation layer.** Surfacing "median time to RRT consideration is 156 months" to a clinician is appropriate; surfacing the same to a patient is not. Production maintains a separate patient-communication layer that translates the model's forecasts into language the patient can understand and act on, designed by a clinical communication specialist, with explicit guardrails against generating statements that look like a diagnosis or a guarantee. LLMs (Recipe 2.x) can power the templating but should not free-form generate substantive content.

**Equity and bias auditing.** Trajectory models trained on a non-representative cohort produce miscalibrated forecasts for under-represented groups. Production runs calibration evaluation separately for major demographic subgroups (race, ethnicity, sex, age band, insurance type) and publishes per-subgroup calibration as part of the model documentation. Where calibration differs meaningfully, the model needs subgroup-specific recalibration or the deployment scope needs to be narrowed.

**Model versioning and retroactive update policy.** When the model retrains or the cohort definition changes, every patient's surfaced forecast implicitly changes. Production maintains model and cohort version metadata on every stored forecast, supports side-by-side comparison of new and old forecasts, and has a defensible policy for when to surface the new forecast versus when to suppress it pending clinical review. The DynamoDB sort key in this demo includes the model version specifically to support this comparison; production extends it with a `CURRENT` pointer scheme so the EHR can fetch the active forecast in a single GetItem.

**EHR integration via CDS Hooks or FHIR Subscriptions.** The DynamoDB-backed surface is fine for a specialty dashboard or a population-health view. For in-workflow CDS, the pipeline needs a [CDS Hooks](https://cds-hooks.org/) responder fronted by API Gateway and Lambda, exposed to the EHR vendor's CDS client. The Lambda receives the `patient-view` hook fired during chart open, queries DynamoDB for the patient's CURRENT trajectory and counterfactual scenarios, renders them as CDS Hooks Cards, and returns. The integration is highly EHR-vendor-specific; budget more time than the engineering estimate suggests.

**Idempotency and rerun safety.** The training pipeline is deterministic given the same harmonized dataset and the same prior set (or, for stochastic samplers, reproducible given a fixed seed). The inference pipeline is deterministic given the same trained model and the same patient data. The counterfactual scenarios are deterministic given the same model and the same scenario specification. DynamoDB writes overwrite cleanly by `(patient_id, disease_modelversion_generated_at)`. The demo achieves idempotency naturally; production has to be deliberate about each step's contract.

**HIPAA controls end-to-end.** The HealthLake datastore uses encryption with a customer-managed KMS key; the S3 prefixes use SSE-KMS with the same key family per data class; the DynamoDB table uses encryption-at-rest with a customer-managed key; SageMaker training and inference run in a VPC with VPC endpoints to S3, HealthLake, CloudWatch Logs, and KMS; the Glue jobs read and write only encrypted data; CloudTrail logs all data-plane API calls with data events on the PHI-bearing buckets and the DynamoDB serving table; CloudWatch log groups are KMS-encrypted; IAM roles are scoped to specific resource ARNs; an AWS BAA is in place. The demo touches none of this; production cannot ship without all of it.

**Audit trail.** Each pipeline run is identified by a `run_id`; every surfaced record carries the cohort version, model version, trial-prior version, and run_id; the DynamoDB writes are idempotent on the primary key; the model-artifact S3 writes use deterministic prefixes per version. An immutable audit log captures which cohort version, which model version, and which prior set produced which surfaced forecast for which patient on which day, written through Kinesis Data Firehose into an S3 bucket with Object Lock in compliance mode.

**Testing.** Unit tests cover the cohort-qualification logic (a patient with the right ICD-10 codes and history is qualified, a patient with an exclusion code is rejected, a patient with insufficient history is rejected), the harmonization function (units convert correctly, time-since-diagnosis is computed correctly, acute-context observations are tagged correctly), the model fit (population slope shrinks correctly toward the literature prior on small cohorts and toward the empirical estimate on large cohorts, per-patient slopes shrink toward the population mean for sparse patients), the inference function (the fitted trajectory matches observed values within the credible interval, the forecast credible intervals widen with horizon), the counterfactual scenario evaluation (a scenario adding a treatment with a known modifier produces the expected slope change, a scenario stopping a treatment produces the expected reversion), and the DynamoDB write idempotency (writing the same record twice is a no-op). Integration tests run the pipeline against a known-input synthetic dataset and assert the surfaced trajectories against expected values. End-to-end tests stand up real HealthLake, S3, DynamoDB, SageMaker, and EventBridge resources in a sandbox account.

**Structured logging.** Replace the demo's `print` calls with `logger.info(..., extra={...})` calls that emit JSON-formatted structured logs to CloudWatch Logs. Log structural metadata only (run_id, patient_id_hash, disease_name, model_version, runtime_ms, scenario_name), never raw observation values, never per-patient posterior samples, never the patient's treatment timeline content.

**Regulatory framing.** A trajectory system that triggers actionable clinical decisions sits in the FDA software-as-a-medical-device (SaMD) regulatory landscape. A system framed as "this patient's trajectory suggests considering nephrology referral within twelve months" with explicit assumption disclosure and uncertainty bands is plausibly clinical decision support and may qualify for the 21st Century Cures Act exemption from premarket review if it meets the transparency and explainability requirements. A system that produces "diagnosis" or "prognosis" output without those guardrails is not exempt. Working with regulatory counsel on the framing of the surfaced output, on the documentation supporting the transparency-and-explainability claim, and on the cohort governance procedures is non-negotiable for any deployment beyond a research pilot.

**The shape of the gap.** The trajectory math in this file is a sketch but it is fundamentally correct. The plumbing around it (storage, orchestration, security, cohort governance, prior registry maintenance, calibration monitoring, equity audit, regulatory framing, EHR integration, patient-facing translation, model versioning) is what takes the bulk of the engineering work. Plan for the plumbing to be 80% of the project; the trajectory model itself routinely surprises teams by being the easier part.

---

## Related Resources

- [Recipe 12.8: Disease Progression Trajectory Modeling](chapter12.08-disease-progression-trajectory-modeling): The main recipe with the full architectural walkthrough this Python companion implements.
- [Amazon HealthLake Documentation](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html): The FHIR datastore that backs the longitudinal patient record. ADPKD trajectory data lives natively in FHIR Observation, Condition, MedicationRequest, and Procedure resources.
- [PyMC](https://www.pymc.io/) and [Stan](https://mc-stan.org/) and [NumPyro](https://num.pyro.ai/): Bayesian probabilistic-programming libraries suitable for hierarchical trajectory models. Drop-in replacements for the demo's `BayesianHierarchicalMixedEffects` helper.
- [statsmodels mixed-effects models](https://www.statsmodels.org/stable/mixed_linear.html): Python frequentist mixed-effects implementation for the simpler linear cases.
- [JM R package](https://cran.r-project.org/web/packages/JM/) and [JMbayes2 R package](https://github.com/drizopoulos/JMbayes2): The standard implementations for joint models of longitudinal trajectories and time-to-event outcomes. Callable from Python via `rpy2`.
- [lifelines](https://lifelines.readthedocs.io/): Python survival-analysis library; useful for the time-to-endpoint component when the simpler joint models are not needed.
- [Synthea Synthetic Patient Generator](https://github.com/synthetichealth/synthea): Realistic synthetic FHIR patient records including longitudinal disease progression trajectories for chronic conditions.
- [LOINC Documentation](https://loinc.org/): The standard for lab and observation codes; essential for the harmonization layer.
- [UCUM Specification](https://ucum.org/): The unit code standard used for canonical unit conversions.
- [Amazon SageMaker Bring Your Own Container](https://docs.aws.amazon.com/sagemaker/latest/dg/your-algorithms.html): Pattern for hosting custom Bayesian models on SageMaker. The right way to deploy a PyMC or Stan model to a real-time endpoint.
- [AWS Step Functions Map State](https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-map-state.html): Pattern for fanning out per-patient inference in parallel.
- [CDS Hooks Specification](https://cds-hooks.org/): The standard for in-EHR clinical decision support. The right interface for surfacing trajectories in chart-open workflows.
- [Forecasting: Principles and Practice (Hyndman & Athanasopoulos)](https://otexts.com/fpp3/): Free online textbook with strong chapters on hierarchical time series and state-space models.
- [21st Century Cures Act Section 3060 (Clinical Decision Support)](https://www.fda.gov/medical-devices/software-medical-device-samd/clinical-decision-support-software): The FDA guidance that frames the regulatory exemption for transparent, explainable clinical decision support.
- [TEMPO 3:4 trial publication](https://pubmed.ncbi.nlm.nih.gov/23121379/) and [REPRISE trial publication](https://pubmed.ncbi.nlm.nih.gov/29105594/): Foundational trials whose effect-size estimates anchor the counterfactual scenarios for tolvaptan in ADPKD; example of the trial-literature-derived priors discussed in the recipe.

---

*← [Recipe 12.8: Disease Progression Trajectory Modeling](chapter12.08-disease-progression-trajectory-modeling) · [Chapter 12 Index](chapter12-preface)*
