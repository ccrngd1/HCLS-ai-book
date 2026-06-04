# Recipe 12.9: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 12.9. It shows one way you could translate the epidemic-forecasting pipeline into working Python using boto3 against Amazon Kinesis Data Streams (here represented by an in-memory `MockKinesisStream`), Amazon S3 (mocked with `MockS3`), AWS Glue (here represented by in-process Python harmonization), Amazon SageMaker (here represented by pure-Python `BayesianStateSpaceNowcaster`, `SEIRCompartmentalModel`, `StatisticalARIMABaseline`, and `EnsembleCombiner` classes that stand in for real PyMC, Stan, statsmodels, Prophet, and SageMaker-hosted models), AWS Step Functions (here represented by sequential function calls), Amazon DynamoDB (mocked with `MockTable`), Amazon Aurora PostgreSQL (mocked with `MockRegistry`), Amazon EventBridge (mocked with `MockEventBus`), and Amazon CloudWatch (mocked with `MockCloudWatch`). The demo runs on a synthetic state-level respiratory-virus dataset: thirty-six weeks of historical lab confirmations, ED syndromic chief-complaint counts, wastewater RNA concentrations, and hospitalization counts across a single state, with a synthetic outbreak forming in the last six weeks. You can see the multi-source harmonization, the Bayesian state-space nowcast that backs out the lagged underlying epidemiology, the SEIR compartmental forecast, the ARIMA statistical baseline, the WIS-weighted ensemble combination, the calibration-coverage check on a temporal holdout, the scenario forecast under a hypothetical masking intervention, and the operational and analytic delivery to DynamoDB and the registry, end-to-end without provisioning anything. It is not production-ready. There is no real Kinesis stream, no real Glue ETL, no real SageMaker training job, no real SageMaker endpoint, no real Step Functions state machine, no real DynamoDB table, no real Aurora cluster, no real EventBridge bus, no real CloudWatch alarms, no real QuickSight dashboard, no real CloudFront-fronted public site, no per-Lambda IAM least privilege, no KMS customer-managed keys, no VPC endpoints, no reporting-delay revision modeling, no multi-strain compartments, no genomic-surveillance integration, no equity audit, no federation with a national forecast hub, no public-facing translation layer, no outbreak-response mode switch, and no audit-trail Object Lock buckets. Think of it as the sketchpad version: useful for understanding the shape of an epidemic-forecasting pipeline that respects the multi-source-fusion discipline, the nowcast-before-forecast discipline, the multi-family-ensemble discipline, the calibration-as-operational-metric discipline, and the scenario-with-explicit-assumption-disclosure discipline this recipe demands. It is not something you would point at a real state public-health office on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the five pseudocode steps from the main recipe: harmonize multi-source surveillance feeds (lab confirmations, ED syndromic, wastewater, hospitalizations) onto a common geography (state-level), a common time grid (epi-week starting Sunday), and common units (counts per 100k where appropriate, normalized concentrations for wastewater) (Step 1); nowcast the underlying current epidemiological state by reverse-convolving the observed lagged signals against per-signal reporting-delay distributions and fusing across signals with calibration-aware weighting (Step 2); generate per-model forecasts in parallel from a Bayesian SEIR compartmental model anchored to the nowcast and a statistical ARIMA baseline that learns directly from the harmonized panel (Step 3); combine the per-model forecasts into a probabilistic ensemble using Vincentized quantile combination with WIS-weighted weights from the recent calibration history (Step 4); validate calibration on a temporal holdout, write operational forecast summaries to DynamoDB for the hospital-operations API, write the full analytic forecast bundle to the Aurora registry, emit pipeline-completion events to EventBridge, and publish CloudWatch metrics for ingestion completeness, model convergence, and calibration drift (Step 5). The synthetic state, the synthetic surveillance feeds, the synthetic outbreak in the last six weeks, the simplified compartmental dynamics, and the simplified ARIMA baseline in the demo are fictional; nothing in this file should be interpreted as real surveillance data, real epidemiological modeling output, or real public-health forecasting guidance for any real jurisdiction.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

The demo runs against the Python standard library plus boto3; no other packages are imported. Production deployments swap the demo's pure-Python `BayesianStateSpaceNowcaster` for real Bayesian state-space libraries ([PyMC](https://www.pymc.io/) for the NUTS sampler, [Stan](https://mc-stan.org/) accessed via [CmdStanPy](https://mc-stan.org/cmdstanpy/), or [NumPyro](https://num.pyro.ai/) when GPU-accelerated NUTS on long surveillance histories matters); replace the demo's `SEIRCompartmentalModel` with a real PyMC or Stan implementation that samples the joint posterior over the SEIR parameters with proper diagnostics (R-hat, effective sample size, divergent transitions); replace the demo's `StatisticalARIMABaseline` with [statsmodels SARIMAX](https://www.statsmodels.org/stable/generated/statsmodels.tsa.statespace.sarimax.SARIMAX.html) or [Prophet](https://facebook.github.io/prophet/) or any of the foundation-model time-series approaches when scale justifies them; replace the demo's `EnsembleCombiner` with a calibration-aware combiner driven by a continuously-updated [Weighted Interval Score](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1008618) tracker; the Gap to Production section spells out the substitutions.

In production you would also configure an Amazon Kinesis Data Stream (or Amazon MSK if your environment standardizes on Kafka) for the streaming surveillance feeds, an Amazon S3 data lake with separate prefixes for the raw surveillance landings, the harmonized analytic store, the nowcasts, the per-model forecasts, the ensemble forecasts, the calibration history, and the public-facing rendered visualizations (each with SSE-KMS encryption using customer-managed CMKs separated by data class), AWS Glue PySpark jobs for the per-feed harmonization (geography normalization through a versioned geography registry, epi-week alignment, unit conversion) and the nowcast-input dataset construction, an Amazon SageMaker training job per model family that runs the weekly retrains with the appropriate container (PyMC for the compartmental family, Stan for the state-space nowcaster, scikit-learn or XGBoost or PyTorch for the statistical and ML families), an Amazon SageMaker real-time endpoint or a SageMaker Batch Transform job for the daily forecast inference, an AWS Lambda function that fronts the scenario-evaluation API (compose the request, invoke the scenario model, post-process the comparison, return the payload), an AWS Step Functions state machine that orchestrates the daily forecast pipeline (refresh feeds -> harmonize -> nowcast -> per-model fan-out via Distributed Map -> ensemble -> validate -> publish) with `Retry` and `Catch` blocks for transient failures, an Amazon DynamoDB table for the operational forecast surfaces (keyed by jurisdiction and target, sort key combining model version and horizon), an Amazon Aurora PostgreSQL cluster for the analytic registry that stores the full per-model trajectories, ensemble distributions, scenario comparisons, and calibration metrics, an Amazon EventBridge schedule that triggers the daily forecast cycle, an Amazon QuickSight workspace for the internal epidemiologist dashboards, an Amazon CloudFront distribution fronting an S3-hosted static site for the public-facing forecast surface, Amazon CloudWatch dashboards and alarms for ingestion completeness, model convergence, and calibration drift (the single most important operational signal), and a regulatory-grade audit log of which feed-specification version, which harmonization version, which nowcast version, which model versions, and which ensemble configuration produced which forecast on which date. The demo replaces all of these with a single in-process Python file so the focus stays on the harmonization, the nowcast, the multi-family forecasting, the ensemble combination, the calibration check, the scenario evaluation, and the operational delivery rather than on the platform plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `kinesis:PutRecord`, `kinesis:GetRecords`, and `kinesis:GetShardIterator` on the surveillance ingestion streams, scoped to specific stream ARNs per data class
- `s3:GetObject`, `s3:PutObject`, and `s3:GetObjectVersion` on the raw-surveillance prefix, the harmonized prefix, the nowcast prefix, the per-model-forecast prefix, the ensemble-forecast prefix, the calibration-history prefix, the trial-prior prefix, and the public-rendering prefix
- `glue:StartJobRun` and `glue:GetJobRun` on the harmonization, nowcast-input, and training-dataset Glue jobs
- `sagemaker:CreateTrainingJob`, `sagemaker:DescribeTrainingJob`, `sagemaker:CreateModel`, `sagemaker:CreateEndpointConfig`, `sagemaker:UpdateEndpoint`, `sagemaker:InvokeEndpoint`, and `sagemaker:CreateTransformJob` on the per-family forecast and nowcast endpoints
- `lambda:InvokeFunction` on the scenario-composer Lambda
- `states:StartExecution` on the forecast Step Functions state machine
- `dynamodb:BatchWriteItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, and `dynamodb:GetItem` on the `forecast-serving` table, scoped to the specific table ARN
- `rds-data:ExecuteStatement` on the Aurora PostgreSQL forecast registry
- `events:PutEvents` on the forecast-events bus for emitting pipeline-lifecycle events
- `cloudwatch:PutMetricData` for operational metrics (ingestion completeness, model convergence, calibration drift, forecast-cycle latency)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting every data class

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The harmonization Glue job has read access to the raw-surveillance prefix and write access to the harmonized prefix only. The nowcast SageMaker training job has read access to the harmonized prefix and write access to the nowcast prefix only. Each per-family forecast SageMaker endpoint has read access to the nowcast and harmonized prefixes and write access to its own per-model-forecast prefix. The ensemble combiner has read access to the per-model-forecast prefix and write access to the ensemble-forecast prefix. The scenario Lambda has invoke-endpoint permission on the relevant SageMaker endpoint and write access to the DynamoDB serving table only. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Surveillance line-list data is PHI even when aggregated to small geographies.** Aggregate counts at the state level are generally not PHI, but the same counts at sub-county geographies, with rare conditions, with small population denominators, can be re-identifying. Production systems treat anything below the state-level aggregate as PHI by default and only relax that with explicit re-identification-risk review. Every storage and compute service that touches line-list data must be on the [HIPAA eligible services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/) list, every storage layer must be encrypted with customer-managed KMS keys, every network hop must be inside the institutional VPC, and CloudTrail must log every data-plane API call.
- **The harmonization layer is the single most underestimated component.** Geography mapping (lab ZIP to county FIPS to state, sewer-shed to county-equivalent), time alignment (lab specimen-collected date versus syndromic encounter date versus wastewater sample date versus hospitalization admission date, all collapsed to epi-week), unit conversion (counts per population denominator with the population denominator itself a time-varying estimate), reporting-delay distribution per signal: each of these is its own engineering and modeling problem. Production teams spend more time on harmonization than on the forecasting math.
- **Reporting delay is a feature, not a footnote.** Lab confirmations from the most recent week are systematically under-counted because reports are still arriving. The naive mistake is to treat the most recent reported value as ground truth, which biases every forecast low. The nowcast layer reverses the reporting-delay convolution to estimate the unobserved current epidemiological state. Production maintains per-feed reporting-delay distributions that themselves are continuously updated.
- **Wastewater leads the clinical signal for many respiratory pathogens.** The first time you watch a state's wastewater signal climb out of baseline two weeks before the lab signal follows it, you change your mind about which signal is primary. The demo's nowcast fusion weights wastewater appreciably for that reason.
- **Forecasts are not weather forecasts.** Behavior responds to the forecast itself; the system being forecast is influenced by the forecast. The standard production answer is scenario forecasting with explicit assumption disclosure ("under continued current behavior, the forecast is X; under modeled mitigation A, the forecast is Y"). The demo includes the scenario layer to show the structure.
- **Calibration is the operational metric.** A 90% prediction interval that empirically contains 90% of out-of-sample observations is calibrated. One that contains 60% is overconfident and dangerous. The training step computes coverage on a temporal holdout, and the production system runs continuous calibration backtests against subsequently observed outcomes. Without this, the system can be subtly wrong for months.
- **The ensemble outperforms any individual model.** This is the empirical lesson from FluSight and the COVID-19 Forecast Hub. The demo runs a two-member ensemble (compartmental + statistical) with WIS-weighted combination; production runs a dozen or more.
- **DynamoDB rejects Python `float`.** Every quantile, weight, calibration metric, and forecast value passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses many Lambdas, Glue jobs, and SageMaker endpoints into a single Python file.** In production, ingestion, harmonization, nowcasting, per-family forecasting, ensemble combination, calibration evaluation, and delivery are separate units of work with their own IAM roles, error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the surveillance feed catalog, the geography registry, the per-feed reporting-delay distributions, the SEIR prior parameters, the ARIMA hyperparameters, the ensemble configuration, the scenario specifications, and the synthetic-data parameters are what you would change between environments.

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

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights for cross-call investigation.
# Surveillance line-list data is PHI; aggregate state-level counts
# generally are not, but the harmonized records for sub-state
# geographies often are. Log structural metadata only (run_id,
# pipeline stage, feed_id, geography_count, runtime_ms), never raw
# counts at sub-state resolution, never line-list records, never
# per-geography forecast values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from S3, DynamoDB, EventBridge,
# CloudWatch, Kinesis, and SageMaker. Daily forecast pipelines
# touch every surveillance feed and every model family; transient
# failures should retry quickly so a stuck dependency does not
# cascade into a missed daily cycle.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across function calls within the
# pipeline so each call does not pay the connection cost. The
# demo wires up MockS3 / MockTable / MockEventBus / MockCloudWatch
# via run_demo() and never touches these real handles; they are
# staged here so production wiring is a one-line swap.
REGION = "us-east-1"
s3_client          = boto3.client("s3",
                                  region_name=REGION,
                                  config=BOTO3_RETRY_CONFIG)
dynamodb           = boto3.resource("dynamodb",
                                    region_name=REGION,
                                    config=BOTO3_RETRY_CONFIG)
kinesis_client     = boto3.client("kinesis",
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
RAW_SURVEILLANCE_BUCKET    = "epi-forecast-raw-surveillance"
HARMONIZED_BUCKET          = "epi-forecast-harmonized"
NOWCAST_BUCKET             = "epi-forecast-nowcasts"
PER_MODEL_FORECAST_BUCKET  = "epi-forecast-per-model"
ENSEMBLE_FORECAST_BUCKET   = "epi-forecast-ensemble"
CALIBRATION_HISTORY_BUCKET = "epi-forecast-calibration"
PUBLIC_RENDER_BUCKET       = "epi-forecast-public"
FORECAST_SERVING_TABLE     = "epi-forecast-serving"
FORECAST_REGISTRY_DB       = "epi-forecast-registry"
FORECAST_EVENT_BUS_NAME    = "epi-forecast-events-bus"
CLOUDWATCH_NAMESPACE       = "EpidemicForecast"

# --- Versioning ---
# Every forecast carries the feed-spec version, the harmonization
# version, the nowcast model version, the per-family model versions,
# and the ensemble configuration version. This is how a future
# audit reconstructs which artifact produced which forecast on
# which date for which jurisdiction.
FEED_SPEC_VERSION       = "feeds-v3"
HARMONIZATION_VERSION   = "harm-v3"
NOWCAST_MODEL_VERSION   = "nowcast-state-space-v2"
SEIR_MODEL_VERSION      = "seir-age-stratified-v3"
ARIMA_MODEL_VERSION     = "arima-baseline-v2"
ENSEMBLE_CONFIG_VERSION = "ensemble-wis-weighted-v1"
PIPELINE_VERSION        = "epi-forecast-pipeline-v1.0"

# --- Forecast Horizon and Cadence ---
# The demo forecasts 8 epi-weeks forward at the state level. Production
# typically forecasts 1-to-8 weeks for the federal hub submission and
# may extend to 12 or 16 weeks for internal scenario work.
FORECAST_HORIZON_WEEKS     = 8
NOWCAST_HORIZON_WEEKS_BACK = 4
QUANTILE_GRID = (0.025, 0.10, 0.25, 0.50, 0.75, 0.90, 0.975)

# --- Jurisdiction ---
# The demo uses a synthetic state. Production runs the pipeline per
# jurisdiction in parallel; the federation layer combines them.
JURISDICTION = {
    "fips":            "37",       # synthetic state FIPS
    "name":            "Demo State",
    "population":      10500000,    # ~10.5M, similar to mid-sized US state
}
```

```python
# --- Surveillance Feed Catalog ---
# In production this is a versioned, governance-reviewed config stored
# in a separate config repo. Here it is inline so the demo is
# self-contained. Each feed entry encodes the metric kind, the
# canonical units, the reporting-delay distribution (median + p90
# in days), and the relative weight in the nowcast fusion.
SURVEILLANCE_FEEDS = {
    "lab_pcr_positivity": {
        "feed_id":         "lab_pcr_positivity",
        "display":         "Public Health Lab PCR Positivity",
        "metric_kind":     "rate_per_100k_per_week",
        "canonical_unit":  "cases_per_100k_per_week",
        "reporting_delay": {"median_days": 4, "p90_days": 11},
        "fusion_weight":   0.30,
        "version":         FEED_SPEC_VERSION,
    },
    "ed_syndromic": {
        "feed_id":         "ed_syndromic",
        "display":         "ED Respiratory Chief-Complaint Visits",
        "metric_kind":     "share_of_visits",
        "canonical_unit":  "fraction_visits_per_week",
        "reporting_delay": {"median_days": 1, "p90_days": 3},
        "fusion_weight":   0.20,
        "version":         FEED_SPEC_VERSION,
    },
    "wastewater_rna": {
        "feed_id":         "wastewater_rna",
        "display":         "Wastewater Pathogen RNA Concentration",
        "metric_kind":     "concentration_normalized",
        "canonical_unit":  "log10_copies_per_ml_normalized",
        "reporting_delay": {"median_days": 5, "p90_days": 9},
        "fusion_weight":   0.40,
        "version":         FEED_SPEC_VERSION,
    },
    "hospitalizations": {
        "feed_id":         "hospitalizations",
        "display":         "Confirmed Respiratory Hospitalizations",
        "metric_kind":     "rate_per_100k_per_week",
        "canonical_unit":  "admissions_per_100k_per_week",
        "reporting_delay": {"median_days": 3, "p90_days": 7},
        "fusion_weight":   0.10,
        "version":         FEED_SPEC_VERSION,
    },
}

# --- SEIR Prior Parameters ---
# Population-level priors anchored to published respiratory-virus
# literature. Production uses age-stratified compartments with
# stratified contact matrices; the demo uses a single-compartment
# SEIR with population-mean parameters so the math is visible.
SEIR_PRIORS = {
    "R0_mean":             1.40,    # effective reproduction number prior
    "R0_sd":               0.25,
    "incubation_days":     3.0,     # 1 / sigma in SEIR
    "infectious_days":     5.0,     # 1 / gamma in SEIR
    "initial_susceptible_share": 0.78,   # post-immunity share
    "observation_noise_sd": 8.0,    # weekly cases per 100k
    "num_posterior_samples": 200,
}

# --- ARIMA Hyperparameters ---
# Simplified statistical baseline. Production uses SARIMAX with
# seasonality terms, exogenous covariates (climate, mobility), and
# proper auto-order selection.
ARIMA_HYPERPARAMETERS = {
    "ar_order":      2,
    "ma_order":      1,
    "seasonal_period": 52,    # epi-weeks per year
    "noise_sd":      6.0,
}

# --- Ensemble Configuration ---
# WIS-weighted combination with equal-weight fallback for cold
# start. Production reads the calibration history from the registry
# and discards models that have shown systematic miscalibration in
# the recent window.
ENSEMBLE_CONFIG = {
    "method":                "wis_weighted",
    "weight_lookback_weeks": 12,
    "minimum_models_required": 2,
    "discard_calibration_failure_within_weeks": 4,
    "fallback_method":       "equal_weighted",
    "version":               ENSEMBLE_CONFIG_VERSION,
}

# --- Calibration Thresholds ---
# Coverage drift alarm thresholds. A 90% credible interval that
# empirically contains less than 80% of out-of-sample observations
# is overconfident and triggers an operational alarm.
CALIBRATION_THRESHOLDS = {
    "coverage_95_minimum": 0.85,
    "coverage_90_minimum": 0.80,
    "coverage_50_minimum": 0.40,
    "coverage_50_maximum": 0.60,
}

# --- Scenarios ---
# Standard scenario set surfaced alongside every forecast. Production
# maintains a versioned scenario registry with explicit assumption
# disclosures reviewed by the public-health communication team.
SCENARIOS = [
    {
        "scenario_id":   "baseline_no_intervention",
        "name":          "Continued current behavior",
        "description":   "No new policy or NPI introduced.",
        "contact_modifier": 1.0,
        "assumption_disclosure": (
            "Forecast assumes continuation of current behavior and "
            "policy. Contact rates remain at the level implied by the "
            "harmonized surveillance signals over the last four weeks."),
    },
    {
        "scenario_id":   "moderate_npi_indoor_masking",
        "name":          "Mandatory indoor masking",
        "description":   "Mandatory masking in indoor public spaces.",
        "contact_modifier": 0.78,
        "assumption_disclosure": (
            "Forecast assumes a mandatory indoor masking policy "
            "produces an approximately 22 percent reduction in "
            "effective contacts within two weeks of announcement, "
            "with adherence assumed at 70 percent. Effect size is "
            "derived from POLYMOD-based studies and 2020-2023 "
            "retrospective NPI evaluations."),
    },
]

# --- Synthetic Data ---
SYNTHETIC_HISTORY_WEEKS  = 36
SYNTHETIC_OUTBREAK_START_WEEKS_AGO = 6
SYNTHETIC_BASELINE_INCIDENCE = 8.0    # per 100k per week
SYNTHETIC_OUTBREAK_PEAK_INCIDENCE = 90.0
SYNTHETIC_RANDOM_SEED    = 4242

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("RAW_SURVEILLANCE_BUCKET",    RAW_SURVEILLANCE_BUCKET),
    ("HARMONIZED_BUCKET",          HARMONIZED_BUCKET),
    ("NOWCAST_BUCKET",             NOWCAST_BUCKET),
    ("PER_MODEL_FORECAST_BUCKET",  PER_MODEL_FORECAST_BUCKET),
    ("ENSEMBLE_FORECAST_BUCKET",   ENSEMBLE_FORECAST_BUCKET),
    ("CALIBRATION_HISTORY_BUCKET", CALIBRATION_HISTORY_BUCKET),
    ("PUBLIC_RENDER_BUCKET",       PUBLIC_RENDER_BUCKET),
    ("FORECAST_SERVING_TABLE",     FORECAST_SERVING_TABLE),
    ("FORECAST_REGISTRY_DB",       FORECAST_REGISTRY_DB),
    ("FORECAST_EVENT_BUS_NAME",    FORECAST_EVENT_BUS_NAME),
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


def _epi_week_to_str(d):
    """Render a date as an epi-week string YYYY-Www.

    Epi-weeks start Sunday in the CDC convention. The demo uses a
    simple ISO-week approximation; production uses the official
    MMWR week computation that handles year-end edge cases.
    """
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-w{iso_week:02d}"


def _normal_cdf(z):
    """Standard normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
```

---

## Mocks and Synthetic Data

The demo never touches a real Kinesis stream, S3 bucket, DynamoDB table, EventBridge bus, or SageMaker endpoint. The mocks below stand in for those services so the focus stays on the forecasting logic. They print what they would write rather than failing, which makes the demo runnable without any AWS resources provisioned.

```python
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
    query, get_item.
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
            pk = Item["jurisdiction_target"]
            sk = Item["horizon_runid"]
            self.table.items[(pk, sk)] = dict(Item)
            self.table.write_count += 1

    def batch_writer(self):
        return self._BatchWriter(self)

    def put_item(self, Item):
        pk = Item["jurisdiction_target"]
        sk = Item["horizon_runid"]
        self.items[(pk, sk)] = dict(Item)
        self.write_count += 1


class MockRegistry:
    """In-memory stand-in for the Aurora PostgreSQL forecast registry.

    Production uses RDS Data API or a managed connection pool to
    write per-run forecast bundles, calibration metrics, and
    scenario comparisons.
    """

    def __init__(self):
        self.forecasts            = []
        self.calibration_history  = []

    def insert_forecast_bundle(self, bundle):
        self.forecasts.append(dict(bundle))

    def insert_calibration_record(self, record):
        self.calibration_history.append(dict(record))

    def query_calibration_history(self, model_id, lookback_weeks):
        # Used by the ensemble combiner to weight per-model
        # contributions. Returns the most recent N calibration
        # records for a given model.
        recs = [r for r in self.calibration_history
                if r["model_id"] == model_id]
        recs.sort(key=lambda r: r["evaluated_at_ts"], reverse=True)
        return recs[:lookback_weeks]


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
        self.alarms  = []

    def put_metric_data(self, Namespace, MetricData):
        for m in MetricData:
            self.metrics[f"{Namespace}/{m['MetricName']}"].append({
                "Value": m["Value"],
                "Unit":  m.get("Unit", "None"),
                "Time":  datetime.now(timezone.utc).isoformat(),
            })

    def raise_alarm(self, alarm):
        self.alarms.append(dict(alarm))
```

```python
def generate_synthetic_surveillance(jurisdiction=JURISDICTION,
                                     history_weeks=SYNTHETIC_HISTORY_WEEKS,
                                     outbreak_start_weeks_ago=SYNTHETIC_OUTBREAK_START_WEEKS_AGO,
                                     seed=SYNTHETIC_RANDOM_SEED):
    """Generate synthetic surveillance feed data for one jurisdiction.

    Produces multi-feed, multi-week records that approximate what
    would land in the raw S3 prefix from the streaming ingestion
    layer. Each feed has its own reporting-delay-induced bias on
    the most recent weeks (the most recent counts are systematically
    under-reported because some reports have not arrived yet) and
    its own lead/lag relationship to the underlying epidemiology.

    The synthetic outbreak shows up as a bell curve over the last
    six weeks with the wastewater signal leading by ~10 days, the
    syndromic signal leading by ~5 days, the lab signal lagging
    by ~5 days, and the hospitalization signal lagging by ~10 days.

    Returns a dict keyed by feed_id mapping to a list of raw records.
    """
    rng = random.Random(seed)
    today = date.today()
    raw_records = defaultdict(list)

    population = jurisdiction["population"]
    pop_per_100k = population / 100000.0

    # Build the underlying weekly true incidence curve.
    true_incidence = []
    for w in range(history_weeks):
        weeks_back = history_weeks - 1 - w
        if weeks_back > outbreak_start_weeks_ago:
            # Pre-outbreak baseline with seasonal variation.
            seasonal = 2.0 * math.sin(2 * math.pi * w / 52.0)
            value = SYNTHETIC_BASELINE_INCIDENCE + seasonal + rng.gauss(0, 1.0)
        else:
            # Outbreak phase: bell curve centered three weeks ago.
            phase_weeks = outbreak_start_weeks_ago - weeks_back
            peak_offset = outbreak_start_weeks_ago // 2
            sigma = 2.5
            outbreak_height = (SYNTHETIC_OUTBREAK_PEAK_INCIDENCE
                               - SYNTHETIC_BASELINE_INCIDENCE)
            value = (SYNTHETIC_BASELINE_INCIDENCE
                     + outbreak_height * math.exp(
                         -((phase_weeks - peak_offset) ** 2) / (2 * sigma ** 2))
                     + rng.gauss(0, 2.0))
        true_incidence.append(max(value, 0.5))

    # Generate per-feed raw records with their characteristic
    # lead/lag patterns and reporting delays.
    for w in range(history_weeks):
        week_date = today - timedelta(weeks=(history_weeks - 1 - w))
        epi_week = _epi_week_to_str(week_date)

        # Lab PCR: lags true incidence by ~1 week, has ~30% under-
        # reporting on the last two weeks due to reporting delay.
        delay_factor = 1.0
        if w >= history_weeks - 2:
            delay_factor = 0.7 if w == history_weeks - 1 else 0.85
        lab_lagged_idx = max(0, w - 1)
        lab_value = true_incidence[lab_lagged_idx] * delay_factor
        lab_count = int(lab_value * pop_per_100k)
        lab_total_tests = int(lab_count * 8 + rng.gauss(0, 200))
        raw_records["lab_pcr_positivity"].append({
            "feed_id":             "lab_pcr_positivity",
            "specimen_collected_dt": (week_date - timedelta(days=3)).isoformat(),
            "report_received_dt":   week_date.isoformat(),
            "epi_week":             epi_week,
            "geography_fips":       jurisdiction["fips"],
            "positive_count":       max(lab_count, 0),
            "tests_total":          max(lab_total_tests, 1),
            "ingested_at_ts":       datetime.now(timezone.utc).isoformat(),
        })

        # ED syndromic: leads true incidence by ~5 days (essentially
        # current week), nearly real-time reporting.
        ed_value = true_incidence[w] * (1.0 + rng.gauss(0, 0.05))
        ed_visits_total = int(pop_per_100k * 800 + rng.gauss(0, 1000))
        ed_resp_visits = int(ed_value * pop_per_100k * 0.3 + rng.gauss(0, 5))
        raw_records["ed_syndromic"].append({
            "feed_id":           "ed_syndromic",
            "encounter_dt":       week_date.isoformat(),
            "epi_week":           epi_week,
            "geography_fips":     jurisdiction["fips"],
            "respiratory_visits": max(ed_resp_visits, 0),
            "total_visits":       max(ed_visits_total, 1),
            "ingested_at_ts":     datetime.now(timezone.utc).isoformat(),
        })

        # Wastewater: leads true incidence by ~10 days. Concentration
        # is normalized log10 copies per mL.
        ww_lead_idx = min(history_weeks - 1, w + 1)
        ww_signal = true_incidence[ww_lead_idx]
        ww_log10 = math.log10(max(ww_signal, 0.5)) + rng.gauss(0, 0.15)
        raw_records["wastewater_rna"].append({
            "feed_id":           "wastewater_rna",
            "sample_collected_dt": week_date.isoformat(),
            "epi_week":           epi_week,
            "geography_fips":     jurisdiction["fips"],
            "log10_copies_per_ml": round(ww_log10, 3),
            "sample_count":       12,    # synthetic 12 sentinel sites
            "ingested_at_ts":     datetime.now(timezone.utc).isoformat(),
        })

        # Hospitalizations: lag true incidence by ~2 weeks. Roughly
        # 6% of cases hospitalize for respiratory virus.
        hosp_lagged_idx = max(0, w - 2)
        hosp_value = true_incidence[hosp_lagged_idx] * 0.06
        hosp_count = int(hosp_value * pop_per_100k + rng.gauss(0, 3))
        raw_records["hospitalizations"].append({
            "feed_id":         "hospitalizations",
            "admission_dt":     week_date.isoformat(),
            "epi_week":         epi_week,
            "geography_fips":   jurisdiction["fips"],
            "admission_count":  max(hosp_count, 0),
            "ingested_at_ts":   datetime.now(timezone.utc).isoformat(),
        })

    return dict(raw_records), true_incidence
```

---

## Step 1: Harmonize Multi-Source Surveillance Feeds

Each surveillance feed lands in its own format with its own units, its own time fields, and its own geography schema. The harmonization step brings everything onto a common epi-week, common geography (state-level for the demo), and common units. The output is a joined panel that the nowcasting and forecasting layers consume.

```python
def harmonize_lab_pcr_record(record, jurisdiction):
    """Convert a lab PCR record to canonical units (cases per 100k per week).

    The lab feed reports positive count and total tests. We convert
    to a positivity rate and then to an estimated weekly incidence
    using the population denominator. Production maintains a
    proper test-positivity-to-incidence model that accounts for
    test-seeking-behavior bias; the demo applies a fixed conversion.
    """
    population = jurisdiction["population"]
    pop_per_100k = population / 100000.0
    incidence_per_100k = record["positive_count"] / max(pop_per_100k, 1.0)
    return {
        "feed_id":         record["feed_id"],
        "epi_week":        record["epi_week"],
        "geography_fips":  record["geography_fips"],
        "value":           round(incidence_per_100k, 3),
        "raw_count":       record["positive_count"],
        "denominator":     record.get("tests_total"),
        "report_dt":       record["report_received_dt"],
        "specimen_dt":     record["specimen_collected_dt"],
    }


def harmonize_ed_syndromic_record(record):
    """Convert ED syndromic to fraction of total visits per week."""
    fraction = (record["respiratory_visits"]
                / max(record["total_visits"], 1))
    return {
        "feed_id":         record["feed_id"],
        "epi_week":        record["epi_week"],
        "geography_fips":  record["geography_fips"],
        "value":           round(fraction, 5),
        "raw_count":       record["respiratory_visits"],
        "denominator":     record["total_visits"],
        "encounter_dt":    record["encounter_dt"],
    }


def harmonize_wastewater_record(record):
    """Wastewater is already in log10 copies; pass through with QC."""
    return {
        "feed_id":         record["feed_id"],
        "epi_week":        record["epi_week"],
        "geography_fips":  record["geography_fips"],
        "value":           record["log10_copies_per_ml"],
        "sample_count":    record["sample_count"],
        "sample_dt":       record["sample_collected_dt"],
    }


def harmonize_hospitalization_record(record, jurisdiction):
    """Convert hospitalization counts to per 100k per week."""
    pop_per_100k = jurisdiction["population"] / 100000.0
    rate = record["admission_count"] / max(pop_per_100k, 1.0)
    return {
        "feed_id":         record["feed_id"],
        "epi_week":        record["epi_week"],
        "geography_fips":  record["geography_fips"],
        "value":           round(rate, 4),
        "raw_count":       record["admission_count"],
        "admission_dt":    record["admission_dt"],
    }


def harmonize_surveillance(raw_records_by_feed, jurisdiction, s3,
                            harmonized_bucket):
    """Step 1: Harmonize all feeds onto a common analytic frame.

    Returns a dict keyed by feed_id mapping to a list of harmonized
    records. Persists each feed's harmonized output to S3 keyed by
    feed_id, geography, and epi-week.
    """
    harmonized = {}
    for feed_id, records in raw_records_by_feed.items():
        harmonized[feed_id] = []
        for record in records:
            if feed_id == "lab_pcr_positivity":
                h = harmonize_lab_pcr_record(record, jurisdiction)
            elif feed_id == "ed_syndromic":
                h = harmonize_ed_syndromic_record(record)
            elif feed_id == "wastewater_rna":
                h = harmonize_wastewater_record(record)
            elif feed_id == "hospitalizations":
                h = harmonize_hospitalization_record(record, jurisdiction)
            else:
                logger.warning("unknown feed_id %s, skipping", feed_id)
                continue
            h["harmonized_at_ts"] = datetime.now(timezone.utc).isoformat()
            h["harmonization_version"] = HARMONIZATION_VERSION
            harmonized[feed_id].append(h)

        # Persist per-feed harmonized output.
        key = (f"harmonized/{HARMONIZATION_VERSION}/"
               f"{jurisdiction['fips']}/{feed_id}.json")
        s3.put_object(Bucket=harmonized_bucket, Key=key,
                      Body=json.dumps(harmonized[feed_id], default=str))
    logger.info("Harmonized %d feeds for jurisdiction %s",
                len(harmonized), jurisdiction["fips"])
    return harmonized


def build_signal_panel(harmonized, weeks_to_include=None):
    """Stack harmonized feeds into a panel keyed by epi-week.

    Returns a list of dicts, one per epi-week, with each feed's
    value as a separate column. Missing values are explicit None.
    The panel is the input to the nowcasting and forecasting layers.
    """
    # Collect every epi-week that appears in any feed.
    all_weeks = set()
    for feed_records in harmonized.values():
        for r in feed_records:
            all_weeks.add(r["epi_week"])
    sorted_weeks = sorted(all_weeks)
    if weeks_to_include is not None:
        sorted_weeks = sorted_weeks[-weeks_to_include:]

    # Build the panel.
    panel = []
    for week in sorted_weeks:
        row = {"epi_week": week}
        for feed_id, feed_records in harmonized.items():
            match = next((r for r in feed_records
                          if r["epi_week"] == week), None)
            row[feed_id] = match["value"] if match else None
        panel.append(row)
    return panel
```

---

## Step 2: Nowcast the Current Epidemiological State

Every surveillance feed lags reality. Lab confirmations lag by approximately a week, hospitalizations by a few weeks, and wastewater leads by several days. Nowcasting estimates the unobserved current epidemiological state by reverse-convolving the observed lagged signals against per-feed reporting-delay distributions and fusing across signals. The output is the input to the per-family forecasting layer; its uncertainty propagates forward.

```python
class BayesianStateSpaceNowcaster:
    """Pedagogical state-space nowcaster.

    The model assumes a hidden weekly incidence series and that
    each observed feed is a noisy, lagged, scaled measurement of
    that hidden series. The nowcast estimates the hidden series
    over the most recent N weeks given the observations.

    Production replaces this with a real Bayesian state-space
    library (PyMC, Stan, NumPyro) that fits the joint posterior
    with NUTS, returns full posterior samples, and emits proper
    convergence diagnostics. The demo uses an inverse-variance-
    weighted fusion approach that captures the structure without
    the sampling machinery.
    """

    def __init__(self, feed_catalog, nowcast_weeks_back, seed=4242):
        self.feed_catalog = dict(feed_catalog)
        self.nowcast_weeks_back = nowcast_weeks_back
        self.rng = random.Random(seed)
        self.fitted = False
        self.nowcast_state = None    # dict: epi_week -> {p10, p50, p90, sd}

    def _signal_to_underlying(self, feed_id, value):
        """Map a feed's observed value to an estimated underlying incidence.

        Each feed has a different scale and units; this helper
        translates each feed's value to the common underlying
        unit (cases per 100k per week). Production maintains
        feed-specific calibration constants from historical
        regression of each feed against the eventual lab-confirmed
        truth; the demo uses simplified mappings that approximate
        what those calibration constants would produce.
        """
        if value is None:
            return None
        if feed_id == "lab_pcr_positivity":
            # Lab is already in target units; divide by 0.7 to
            # un-bias for typical ~30% reporting under-count.
            return value / 0.7
        if feed_id == "ed_syndromic":
            # ED fraction of visits scales with incidence; the
            # demo's calibration constant is incidence ~= ED * 1500.
            return value * 1500.0
        if feed_id == "wastewater_rna":
            # Wastewater log10 copies; the calibration is roughly
            # incidence = 10 ** (ww - 1.0) for the synthetic data.
            return 10 ** (value - 1.0)
        if feed_id == "hospitalizations":
            # Hospitalization rate is ~6% of incidence.
            return value / 0.06
        return None

    def _delay_correction_factor(self, feed_id, weeks_back):
        """Multiplier to correct for under-reporting at recent weeks.

        For a feed with median reporting delay D days and p90 D90,
        the most recent week has a known fraction of reports in
        and the next-most-recent has more. This is a simplified
        model of the reporting-delay distribution; production
        maintains a per-feed PMF.
        """
        delay = self.feed_catalog[feed_id]["reporting_delay"]
        median_days = delay["median_days"]
        if weeks_back == 0:
            # Most recent week: only median-day fraction of reports in.
            return min(1.0, 7.0 / max(median_days * 1.5, 1.0))
        if weeks_back == 1:
            return min(1.0, 7.0 / max(median_days, 1.0))
        return 1.0

    def fit(self, panel):
        """Fit the nowcast for the most recent N weeks.

        Walks the panel from oldest to newest, applies the per-feed
        signal-to-underlying mapping and the reporting-delay
        correction, fuses across feeds with inverse-variance
        weighting, and returns posterior median + credible intervals
        per epi-week.
        """
        if not panel:
            raise ValueError("Cannot fit on empty panel")
        n_weeks = len(panel)
        nowcast_weeks = panel[-self.nowcast_weeks_back:]
        nowcast_state = {}

        for week_idx, week_row in enumerate(nowcast_weeks):
            weeks_back = self.nowcast_weeks_back - 1 - week_idx
            # Per-feed underlying-incidence estimates.
            estimates = []
            weights = []
            for feed_id, feed_value in week_row.items():
                if feed_id == "epi_week" or feed_value is None:
                    continue
                feed_spec = self.feed_catalog.get(feed_id)
                if feed_spec is None:
                    continue
                # Map the signal to an underlying-incidence estimate.
                underlying = self._signal_to_underlying(feed_id, feed_value)
                if underlying is None:
                    continue
                # Correct for reporting under-counting on recent weeks.
                correction = self._delay_correction_factor(feed_id, weeks_back)
                if correction > 0:
                    underlying = underlying / correction
                estimates.append(underlying)
                # Weight by the feed's fusion weight, attenuated by
                # the reporting-delay correction (more correction
                # means more uncertainty, so less weight).
                effective_weight = feed_spec["fusion_weight"] * correction
                weights.append(effective_weight)

            if not estimates:
                # No data for this week: carry forward the prior
                # nowcast or use a flat prior.
                last_week = list(nowcast_state.keys())[-1] if nowcast_state else None
                if last_week:
                    nowcast_state[week_row["epi_week"]] = dict(
                        nowcast_state[last_week])
                else:
                    nowcast_state[week_row["epi_week"]] = {
                        "p10": 5.0, "p50": 10.0, "p90": 20.0, "sd": 5.0,
                    }
                continue

            # Inverse-variance-weighted fusion.
            total_weight = sum(weights)
            if total_weight <= 0:
                total_weight = 1.0
            weighted_mean = sum(e * w for e, w in zip(estimates, weights)) / total_weight
            # SD across feeds as a proxy for nowcast uncertainty.
            if len(estimates) > 1:
                weighted_var = sum(
                    w * (e - weighted_mean) ** 2 for e, w in zip(estimates, weights)
                ) / total_weight
                fusion_sd = math.sqrt(max(weighted_var, 1.0))
            else:
                fusion_sd = max(weighted_mean * 0.30, 2.0)

            # Inflate uncertainty for very recent weeks where the
            # reporting-delay correction is strong.
            if weeks_back == 0:
                fusion_sd *= 1.5

            nowcast_state[week_row["epi_week"]] = {
                "p10": round(max(weighted_mean - 1.282 * fusion_sd, 0.1), 3),
                "p50": round(max(weighted_mean, 0.1), 3),
                "p90": round(max(weighted_mean + 1.282 * fusion_sd, 0.1), 3),
                "sd":  round(fusion_sd, 3),
                "n_signals": len(estimates),
            }

        self.nowcast_state = nowcast_state
        self.fitted = True
        return nowcast_state


def run_nowcast(harmonized, panel, jurisdiction, s3, nowcast_bucket,
                run_id):
    """Step 2: Run the nowcasting layer.

    Returns the nowcast state dict. Persists to S3.
    """
    nowcaster = BayesianStateSpaceNowcaster(
        feed_catalog=SURVEILLANCE_FEEDS,
        nowcast_weeks_back=NOWCAST_HORIZON_WEEKS_BACK)
    nowcast_state = nowcaster.fit(panel)

    # Persist.
    artifact = {
        "run_id":               run_id,
        "jurisdiction":         jurisdiction["fips"],
        "nowcast_model_version": NOWCAST_MODEL_VERSION,
        "harmonization_version": HARMONIZATION_VERSION,
        "feed_spec_version":    FEED_SPEC_VERSION,
        "nowcast_state":        nowcast_state,
        "generated_at_ts":      datetime.now(timezone.utc).isoformat(),
    }
    key = (f"nowcasts/{NOWCAST_MODEL_VERSION}/"
           f"{jurisdiction['fips']}/{run_id}.json")
    s3.put_object(Bucket=nowcast_bucket, Key=key,
                  Body=json.dumps(artifact, default=str))

    logger.info("Nowcast for %s: %d weeks back, latest_p50=%.2f",
                jurisdiction["fips"],
                len(nowcast_state),
                nowcast_state[list(nowcast_state.keys())[-1]]["p50"])
    return nowcaster, artifact
```

---

## Step 3: Per-Model Forecast Generation

Each model family runs in parallel on the nowcast-conditioned input. The demo runs a Bayesian SEIR compartmental model and a statistical ARIMA baseline. The compartmental model uses the nowcast as the initial condition and projects forward under sampled SEIR parameter posteriors. The ARIMA model uses the harmonized panel directly with a basic AR(2) MA(1) recursion.

```python
class SEIRCompartmentalModel:
    """Simplified SEIR compartmental model.

    The differential equations:
        dS/dt = -beta * S * I / N
        dE/dt =  beta * S * I / N - sigma * E
        dI/dt =  sigma * E - gamma * I
        dR/dt =  gamma * I

    where beta = R0 * gamma / (1 - immunity_share). The demo
    discretizes to weekly steps with simple Euler integration.
    Production uses RK4 or scipy's odeint, and replaces the
    closed-form Monte Carlo sampling here with PyMC/Stan NUTS
    on the joint parameter posterior.
    """

    def __init__(self, priors, jurisdiction, seed=4242):
        self.priors = dict(priors)
        self.jurisdiction = dict(jurisdiction)
        self.rng = random.Random(seed)
        self.fitted = False
        self.last_forecast = None

    def _simulate_trajectory(self, R0, initial_incidence_per_100k,
                              susceptible_share, horizon_weeks,
                              contact_modifier=1.0):
        """Run the SEIR ODE forward for horizon_weeks.

        Returns weekly new-infection rates per 100k.
        """
        N = self.jurisdiction["population"]
        # Convert weekly incidence (per 100k) to current infectious count.
        # I0 ~ initial_incidence_per_100k * N / 100000 * (infectious_days / 7)
        infectious_days = self.priors["infectious_days"]
        incubation_days = self.priors["incubation_days"]
        gamma_daily = 1.0 / infectious_days
        sigma_daily = 1.0 / incubation_days
        beta_daily = (R0 * gamma_daily * contact_modifier
                      / max(susceptible_share, 0.01))

        # Initial state.
        S = susceptible_share * N
        # Spread the initial cases between E and I compartments.
        I0 = (initial_incidence_per_100k * (N / 100000.0)
              * (infectious_days / 7.0))
        E0 = I0 * (incubation_days / infectious_days)
        S = max(S - I0 - E0, 0.0)
        E = max(E0, 0.0)
        I = max(I0, 0.0)
        R = N - S - E - I

        weekly_new_infections = []
        # Daily Euler steps for stability; aggregate to weekly.
        for week in range(horizon_weeks):
            week_new_infections = 0.0
            for _ in range(7):
                if S <= 0:
                    break
                new_inf = beta_daily * S * I / N
                new_inf = min(new_inf, S)
                new_progress = sigma_daily * E
                new_recover = gamma_daily * I
                S -= new_inf
                E += new_inf - new_progress
                I += new_progress - new_recover
                R += new_recover
                week_new_infections += new_progress
            # Convert to per-100k weekly incidence.
            week_per_100k = week_new_infections * (100000.0 / N)
            weekly_new_infections.append(week_per_100k)
        return weekly_new_infections

    def forecast(self, nowcast_state, horizon_weeks,
                  contact_modifier=1.0,
                  num_samples=None):
        """Sample posterior trajectories and compute quantiles.

        Draws (R0, susceptible_share, initial_incidence) tuples
        from the priors-conditioned-on-nowcast and runs the SEIR
        forward for each draw. Returns per-week quantiles.
        """
        num_samples = num_samples or self.priors["num_posterior_samples"]
        latest_week = list(nowcast_state.keys())[-1]
        latest_p50 = nowcast_state[latest_week]["p50"]
        latest_sd  = nowcast_state[latest_week]["sd"]

        # Sample trajectories.
        trajectories = []
        for _ in range(num_samples):
            R0_sample = self.rng.gauss(
                self.priors["R0_mean"], self.priors["R0_sd"])
            R0_sample = max(R0_sample, 0.5)
            sus_share = self.rng.gauss(
                self.priors["initial_susceptible_share"], 0.05)
            sus_share = max(min(sus_share, 0.95), 0.20)
            initial_inc = self.rng.gauss(latest_p50, latest_sd)
            initial_inc = max(initial_inc, 0.5)

            traj = self._simulate_trajectory(
                R0=R0_sample,
                initial_incidence_per_100k=initial_inc,
                susceptible_share=sus_share,
                horizon_weeks=horizon_weeks,
                contact_modifier=contact_modifier)
            # Add observation noise per week.
            noisy_traj = [t + self.rng.gauss(0, self.priors["observation_noise_sd"])
                          for t in traj]
            trajectories.append(noisy_traj)

        # Compute per-week quantiles.
        forecast_quantiles = []
        last_date = date.today()
        for h in range(horizon_weeks):
            week_values = sorted([t[h] for t in trajectories])
            quantiles = {}
            for q in QUANTILE_GRID:
                idx = max(0, min(len(week_values) - 1,
                                 int(round(q * len(week_values)))))
                quantiles[str(q)] = round(max(week_values[idx], 0.1), 2)
            forecast_week = last_date + timedelta(weeks=h + 1)
            forecast_quantiles.append({
                "horizon_weeks": h + 1,
                "epi_week":      _epi_week_to_str(forecast_week),
                "quantiles":     quantiles,
            })

        self.last_forecast = forecast_quantiles
        self.fitted = True
        return {
            "model_id":             SEIR_MODEL_VERSION,
            "model_family":         "compartmental",
            "forecast_quantiles":   forecast_quantiles,
            "contact_modifier":     contact_modifier,
            "num_trajectories":     num_samples,
            "generated_at_ts":      datetime.now(timezone.utc).isoformat(),
        }


class StatisticalARIMABaseline:
    """Simplified ARIMA(p,d,q)-style statistical baseline.

    The demo implements an AR(2) MA(1) recursion with manually-set
    coefficients fit via simple OLS on the harmonized panel's
    primary signal. Production uses statsmodels SARIMAX with proper
    auto-order selection, seasonality terms, and exogenous covariates.
    """

    def __init__(self, hyperparameters, seed=4242):
        self.hyper = dict(hyperparameters)
        self.rng = random.Random(seed + 1)
        self.fitted = False
        self.ar_coefs = None
        self.ma_coef = None
        self.history = None

    def fit(self, panel, primary_feed_id="lab_pcr_positivity"):
        """Fit AR coefficients via OLS on the primary feed's history."""
        series = [row.get(primary_feed_id) for row in panel
                  if row.get(primary_feed_id) is not None]
        if len(series) < 10:
            raise ValueError("Insufficient data for ARIMA fit")

        # OLS for y_t = phi1 * y_{t-1} + phi2 * y_{t-2} + e_t
        # plus a level constant. Toy fit; production uses real
        # SARIMAX MLE.
        ys = series[2:]
        x1 = series[1:-1]
        x2 = series[:-2]
        n = len(ys)
        mean_y, mean_x1, mean_x2 = (sum(ys) / n, sum(x1) / n, sum(x2) / n)
        # Simple covariance-based estimator.
        s11 = sum((x1[i] - mean_x1) ** 2 for i in range(n))
        s22 = sum((x2[i] - mean_x2) ** 2 for i in range(n))
        s12 = sum((x1[i] - mean_x1) * (x2[i] - mean_x2) for i in range(n))
        s1y = sum((x1[i] - mean_x1) * (ys[i] - mean_y) for i in range(n))
        s2y = sum((x2[i] - mean_x2) * (ys[i] - mean_y) for i in range(n))
        det = s11 * s22 - s12 ** 2
        if abs(det) < 1e-9:
            phi1, phi2 = 0.7, 0.0
        else:
            phi1 = (s22 * s1y - s12 * s2y) / det
            phi2 = (s11 * s2y - s12 * s1y) / det
        # Stability cap to keep the recursion bounded.
        phi1 = max(min(phi1, 1.4), -0.5)
        phi2 = max(min(phi2, 0.4), -0.5)
        intercept = mean_y - phi1 * mean_x1 - phi2 * mean_x2

        self.ar_coefs = (phi1, phi2)
        self.intercept = intercept
        self.ma_coef = 0.2
        self.history = list(series)
        self.fitted = True
        return {
            "ar_coefs":     self.ar_coefs,
            "intercept":    round(intercept, 3),
            "n_obs":        len(series),
        }

    def forecast(self, horizon_weeks, num_samples=200):
        """Recursive forecast with Monte Carlo noise samples."""
        if not self.fitted:
            raise RuntimeError("ARIMA not fitted")
        phi1, phi2 = self.ar_coefs
        noise_sd = self.hyper["noise_sd"]
        last_date = date.today()

        trajectories = []
        for _ in range(num_samples):
            history = list(self.history)
            traj = []
            for h in range(horizon_weeks):
                y_prev = history[-1]
                y_prev2 = history[-2] if len(history) >= 2 else y_prev
                pred = (self.intercept + phi1 * y_prev + phi2 * y_prev2
                        + self.rng.gauss(0, noise_sd))
                pred = max(pred, 0.5)
                traj.append(pred)
                history.append(pred)
            trajectories.append(traj)

        forecast_quantiles = []
        for h in range(horizon_weeks):
            week_values = sorted([t[h] for t in trajectories])
            quantiles = {}
            for q in QUANTILE_GRID:
                idx = max(0, min(len(week_values) - 1,
                                 int(round(q * len(week_values)))))
                quantiles[str(q)] = round(max(week_values[idx], 0.1), 2)
            forecast_week = last_date + timedelta(weeks=h + 1)
            forecast_quantiles.append({
                "horizon_weeks": h + 1,
                "epi_week":      _epi_week_to_str(forecast_week),
                "quantiles":     quantiles,
            })

        return {
            "model_id":             ARIMA_MODEL_VERSION,
            "model_family":         "statistical",
            "forecast_quantiles":   forecast_quantiles,
            "ar_coefs":             list(self.ar_coefs),
            "num_trajectories":     num_samples,
            "generated_at_ts":      datetime.now(timezone.utc).isoformat(),
        }


def run_per_model_forecasts(nowcast_state, panel, jurisdiction, s3,
                              per_model_bucket, run_id):
    """Step 3: Run all model families in parallel.

    Production uses Step Functions Distributed Map to fan out
    per-model SageMaker invocations; the demo runs them sequentially
    in process. Returns a list of per-model forecast artifacts.
    """
    forecasts = []

    # Compartmental SEIR.
    seir = SEIRCompartmentalModel(
        priors=SEIR_PRIORS, jurisdiction=jurisdiction)
    seir_forecast = seir.forecast(nowcast_state, FORECAST_HORIZON_WEEKS)
    forecasts.append(seir_forecast)

    # Statistical ARIMA baseline.
    arima = StatisticalARIMABaseline(hyperparameters=ARIMA_HYPERPARAMETERS)
    arima.fit(panel)
    arima_forecast = arima.forecast(FORECAST_HORIZON_WEEKS)
    forecasts.append(arima_forecast)

    # Persist each per-model artifact.
    for forecast in forecasts:
        key = (f"per-model-forecasts/{forecast['model_id']}/"
               f"{jurisdiction['fips']}/{run_id}.json")
        s3.put_object(Bucket=per_model_bucket, Key=key,
                      Body=json.dumps(forecast, default=str))

    logger.info("Generated %d per-model forecasts for %s",
                len(forecasts), jurisdiction["fips"])
    return forecasts, seir, arima
```

---

## Step 4: Combine into an Ensemble

The empirical lesson from FluSight and the COVID-19 Forecast Hub is that ensembles outperform individual models. The combiner takes per-model forecasts, weighs them by recent calibration performance (or equal-weights as the cold-start fallback), and produces a Vincentized quantile combination that preserves calibration properties.

```python
class EnsembleCombiner:
    """Vincentized quantile combiner with WIS-weighted weights.

    The Vincentized combination averages quantile values across
    models rather than averaging across distributions. For a
    grid of probability levels q1, q2, ..., qN, the ensemble
    quantile at qi is the weighted average of the per-model
    quantile values at qi. This preserves the ensemble's
    calibration properties.

    Production replaces the demo's simplified WIS-weighting with
    a continuously-updated calibration tracker that pulls coverage
    history from the Aurora registry and discards models with
    recent calibration failures.
    """

    def __init__(self, config):
        self.config = dict(config)

    def _compute_weights(self, per_model_forecasts, calibration_history):
        """Return weights per model for the Vincentized combination."""
        method = self.config["method"]
        n = len(per_model_forecasts)
        if method == "equal_weighted" or not calibration_history:
            return {f["model_id"]: 1.0 / n for f in per_model_forecasts}
        if method == "wis_weighted":
            # Lower WIS is better; invert and normalize.
            wis_per_model = {}
            for forecast in per_model_forecasts:
                history = calibration_history.get(forecast["model_id"], [])
                if not history:
                    wis_per_model[forecast["model_id"]] = 1.0
                else:
                    avg_wis = statistics.mean(
                        h.get("wis", 1.0) for h in history)
                    wis_per_model[forecast["model_id"]] = max(avg_wis, 0.1)
            inverse_wis = {m: 1.0 / w for m, w in wis_per_model.items()}
            total = sum(inverse_wis.values())
            return {m: w / total for m, w in inverse_wis.items()}
        # Inverse-variance fallback.
        return {f["model_id"]: 1.0 / n for f in per_model_forecasts}

    def combine(self, per_model_forecasts, calibration_history):
        """Combine per-model forecasts into an ensemble forecast."""
        if len(per_model_forecasts) < self.config["minimum_models_required"]:
            raise ValueError("Insufficient models for ensemble")

        weights = self._compute_weights(per_model_forecasts, calibration_history)

        # Group forecasts by horizon.
        by_horizon = defaultdict(list)
        for forecast in per_model_forecasts:
            for week_forecast in forecast["forecast_quantiles"]:
                by_horizon[week_forecast["horizon_weeks"]].append({
                    "model_id":  forecast["model_id"],
                    "quantiles": week_forecast["quantiles"],
                    "epi_week":  week_forecast["epi_week"],
                })

        # Vincentized combination per horizon per quantile.
        ensemble_forecast = []
        for horizon in sorted(by_horizon.keys()):
            entries = by_horizon[horizon]
            ensemble_quantiles = {}
            for q in QUANTILE_GRID:
                q_str = str(q)
                weighted_sum = 0.0
                weight_total = 0.0
                for entry in entries:
                    w = weights.get(entry["model_id"], 0.0)
                    val = entry["quantiles"].get(q_str)
                    if val is None:
                        continue
                    weighted_sum += w * val
                    weight_total += w
                if weight_total > 0:
                    ensemble_quantiles[q_str] = round(
                        weighted_sum / weight_total, 2)
            ensemble_forecast.append({
                "horizon_weeks": horizon,
                "epi_week":      entries[0]["epi_week"],
                "quantiles":     ensemble_quantiles,
            })

        return {
            "ensemble_method":     self.config["method"],
            "per_model_weights":   weights,
            "eligible_models":     [f["model_id"] for f in per_model_forecasts],
            "ensemble_forecast":   ensemble_forecast,
            "ensemble_config_version": self.config["version"],
            "generated_at_ts":     datetime.now(timezone.utc).isoformat(),
        }


def run_ensemble(per_model_forecasts, registry, jurisdiction, s3,
                  ensemble_bucket, run_id):
    """Step 4: Run the ensemble combiner."""
    combiner = EnsembleCombiner(ENSEMBLE_CONFIG)

    # Pull recent calibration history per model from the registry.
    calibration_history = {}
    for forecast in per_model_forecasts:
        history = registry.query_calibration_history(
            model_id=forecast["model_id"],
            lookback_weeks=ENSEMBLE_CONFIG["weight_lookback_weeks"])
        calibration_history[forecast["model_id"]] = history

    ensemble_artifact = combiner.combine(per_model_forecasts, calibration_history)

    # Persist.
    key = (f"ensemble-forecasts/{ENSEMBLE_CONFIG_VERSION}/"
           f"{jurisdiction['fips']}/{run_id}.json")
    s3.put_object(Bucket=ensemble_bucket, Key=key,
                  Body=json.dumps(ensemble_artifact, default=str))

    logger.info("Ensemble combined %d models for %s",
                len(per_model_forecasts), jurisdiction["fips"])
    return ensemble_artifact
```

---

## Step 5: Validate, Compose Scenarios, and Surface

The pipeline validates calibration on a temporal holdout, composes scenario forecasts under hypothetical interventions, and surfaces the operational forecasts to DynamoDB and the analytic forecasts to the registry. CloudWatch metrics flag calibration drift and ingestion-completeness issues.

```python
def compute_holdout_calibration(per_model_forecasts, panel,
                                  primary_feed_id="lab_pcr_positivity",
                                  holdout_weeks=4):
    """Coverage of credible intervals on a temporal holdout.

    For each model, hold out the most recent `holdout_weeks` of
    the panel, simulate what the model would have forecast at
    that point, and check coverage of the held-out observations.
    The demo's "what would the model have forecast" is approximated
    by checking whether the held-out actuals fall within the
    model's current forecast intervals at horizons 1..holdout_weeks.
    Production runs proper temporal-cross-validation backtests.
    """
    actuals = [row.get(primary_feed_id) for row in panel
               if row.get(primary_feed_id) is not None]
    if len(actuals) < holdout_weeks + 4:
        return {}

    holdout_actuals = actuals[-holdout_weeks:]

    coverage_summary = {}
    for forecast in per_model_forecasts:
        coverage_50 = 0
        coverage_80 = 0
        coverage_95 = 0
        wis_total = 0.0
        n_evaluated = 0
        for h, actual in enumerate(holdout_actuals):
            horizon = h + 1
            week_forecast = next(
                (f for f in forecast["forecast_quantiles"]
                 if f["horizon_weeks"] == horizon),
                None)
            if week_forecast is None:
                continue
            qs = week_forecast["quantiles"]
            # 50% interval.
            q25 = qs.get("0.25")
            q75 = qs.get("0.75")
            if q25 is not None and q75 is not None:
                if q25 <= actual <= q75:
                    coverage_50 += 1
            # 80% interval.
            q10 = qs.get("0.1")
            q90 = qs.get("0.9")
            if q10 is not None and q90 is not None:
                if q10 <= actual <= q90:
                    coverage_80 += 1
            # 95% interval.
            q025 = qs.get("0.025")
            q975 = qs.get("0.975")
            if q025 is not None and q975 is not None:
                if q025 <= actual <= q975:
                    coverage_95 += 1
                # Approximate WIS contribution: penalty for distance
                # outside the 95 interval plus interval width.
                width = q975 - q025
                if actual < q025:
                    wis_total += width + 2 * (q025 - actual) / 0.05
                elif actual > q975:
                    wis_total += width + 2 * (actual - q975) / 0.05
                else:
                    wis_total += width
            n_evaluated += 1

        if n_evaluated == 0:
            continue
        coverage_summary[forecast["model_id"]] = {
            "coverage_50":  round(coverage_50 / n_evaluated, 3),
            "coverage_80":  round(coverage_80 / n_evaluated, 3),
            "coverage_95":  round(coverage_95 / n_evaluated, 3),
            "wis":          round(wis_total / n_evaluated, 2),
            "n_evaluated":  n_evaluated,
        }
    return coverage_summary


def detect_calibration_drift(coverage_summary):
    """Flag models that have drifted out of calibration."""
    alarms = []
    for model_id, metrics in coverage_summary.items():
        if metrics["coverage_95"] < CALIBRATION_THRESHOLDS["coverage_95_minimum"]:
            alarms.append({
                "model_id":     model_id,
                "metric":       "coverage_95",
                "observed":     metrics["coverage_95"],
                "threshold":    CALIBRATION_THRESHOLDS["coverage_95_minimum"],
                "severity":     "high",
                "description":  "95% credible interval coverage below floor",
            })
        if metrics["coverage_80"] < CALIBRATION_THRESHOLDS["coverage_90_minimum"]:
            alarms.append({
                "model_id":     model_id,
                "metric":       "coverage_80",
                "observed":     metrics["coverage_80"],
                "threshold":    CALIBRATION_THRESHOLDS["coverage_90_minimum"],
                "severity":     "medium",
                "description":  "80% credible interval coverage below floor",
            })
    return alarms


def compose_scenario_forecasts(seir_model, nowcast_state, scenarios):
    """Run the SEIR model under each scenario's contact modifier."""
    scenario_outputs = []
    for scenario in scenarios:
        forecast = seir_model.forecast(
            nowcast_state=nowcast_state,
            horizon_weeks=FORECAST_HORIZON_WEEKS,
            contact_modifier=scenario["contact_modifier"])
        # Compute the peak incidence summary.
        peak_p50 = max(
            f["quantiles"].get("0.5", 0)
            for f in forecast["forecast_quantiles"])
        peak_week = next(
            (f["epi_week"] for f in forecast["forecast_quantiles"]
             if f["quantiles"].get("0.5", 0) == peak_p50),
            None)
        peak_p10 = min(
            f["quantiles"].get("0.1", 1e9)
            for f in forecast["forecast_quantiles"])
        peak_p90 = max(
            f["quantiles"].get("0.9", 0)
            for f in forecast["forecast_quantiles"])
        scenario_outputs.append({
            "scenario_id":          scenario["scenario_id"],
            "name":                 scenario["name"],
            "description":          scenario["description"],
            "contact_modifier":     scenario["contact_modifier"],
            "forecast":             forecast["forecast_quantiles"],
            "peak_incidence_p50":   round(peak_p50, 2),
            "peak_epi_week_p50":    peak_week,
            "peak_incidence_p10_p90": [round(peak_p10, 2),
                                        round(peak_p90, 2)],
            "assumption_disclosure": scenario["assumption_disclosure"],
        })
    return scenario_outputs


def deliver_forecast(ensemble_artifact, scenario_outputs, coverage_summary,
                      drift_alarms, jurisdiction, run_id, table, registry,
                      event_bus, cloudwatch, s3, calibration_bucket):
    """Step 5: Surface to DynamoDB, registry, EventBridge, CloudWatch."""

    # Operational summaries to DynamoDB. Each (jurisdiction, target,
    # horizon) gets one row that the hospital-operations API can
    # query at low latency.
    target = "incidence_per_100k_per_week"
    pk = f"{jurisdiction['fips']}#{target}"
    written = 0
    with table.batch_writer() as bw:
        for week_forecast in ensemble_artifact["ensemble_forecast"]:
            sk = (f"horizon-{week_forecast['horizon_weeks']:02d}#"
                  f"{ensemble_artifact['generated_at_ts']}#{run_id}")
            qs = week_forecast["quantiles"]
            item = {
                "jurisdiction_target":   pk,
                "horizon_runid":         sk,
                "jurisdiction_fips":     jurisdiction["fips"],
                "jurisdiction_name":     jurisdiction["name"],
                "target":                target,
                "epi_week":              week_forecast["epi_week"],
                "horizon_weeks":         week_forecast["horizon_weeks"],
                "p_025":                 _to_decimal(qs.get("0.025")),
                "p_10":                  _to_decimal(qs.get("0.1")),
                "p_25":                  _to_decimal(qs.get("0.25")),
                "p_50":                  _to_decimal(qs.get("0.5")),
                "p_75":                  _to_decimal(qs.get("0.75")),
                "p_90":                  _to_decimal(qs.get("0.9")),
                "p_975":                 _to_decimal(qs.get("0.975")),
                "ensemble_method":       ensemble_artifact["ensemble_method"],
                "ensemble_config_version": ensemble_artifact["ensemble_config_version"],
                "feed_spec_version":     FEED_SPEC_VERSION,
                "harmonization_version": HARMONIZATION_VERSION,
                "nowcast_model_version": NOWCAST_MODEL_VERSION,
                "pipeline_version":      PIPELINE_VERSION,
                "run_id":                run_id,
                "generated_at_ts":       ensemble_artifact["generated_at_ts"],
            }
            bw.put_item(Item=item)
            written += 1

    # Full analytic bundle to the registry.
    bundle = {
        "run_id":             run_id,
        "jurisdiction":       jurisdiction["fips"],
        "ensemble_artifact":  ensemble_artifact,
        "scenario_outputs":   scenario_outputs,
        "coverage_summary":   coverage_summary,
        "drift_alarms":       drift_alarms,
        "feed_spec_version":  FEED_SPEC_VERSION,
        "harmonization_version": HARMONIZATION_VERSION,
        "nowcast_model_version": NOWCAST_MODEL_VERSION,
        "pipeline_version":   PIPELINE_VERSION,
        "generated_at_ts":    ensemble_artifact["generated_at_ts"],
    }
    registry.insert_forecast_bundle(bundle)

    # Calibration history to the registry per model.
    for model_id, metrics in coverage_summary.items():
        registry.insert_calibration_record({
            "run_id":         run_id,
            "model_id":       model_id,
            "jurisdiction":   jurisdiction["fips"],
            "evaluated_at_ts": ensemble_artifact["generated_at_ts"],
            **metrics,
        })

    # Persist the calibration summary to S3 for audit.
    s3.put_object(
        Bucket=calibration_bucket,
        Key=(f"calibration/{jurisdiction['fips']}/"
             f"{run_id}.json"),
        Body=json.dumps({
            "coverage_summary": coverage_summary,
            "drift_alarms":     drift_alarms,
            "run_id":           run_id,
        }, default=str))

    # EventBridge completion event (no PHI, no per-geography forecast values).
    event_bus.put_events(Entries=[{
        "Source":       "epi.forecast",
        "DetailType":   "ForecastCycleCompleted",
        "EventBusName": FORECAST_EVENT_BUS_NAME,
        "Time":         datetime.now(timezone.utc),
        "Detail":       json.dumps({
            "run_id":            run_id,
            "jurisdiction":      jurisdiction["fips"],
            "horizons_written":  written,
            "scenarios_evaluated": len(scenario_outputs),
            "drift_alarm_count": len(drift_alarms),
            "pipeline_version":  PIPELINE_VERSION,
        }),
    }])

    # CloudWatch operational metrics.
    metrics_payload = [
        {"MetricName": "ForecastHorizonsWritten",
         "Value":      float(written),
         "Unit":       "Count"},
        {"MetricName": "ScenariosEvaluated",
         "Value":      float(len(scenario_outputs)),
         "Unit":       "Count"},
        {"MetricName": "CalibrationDriftAlarms",
         "Value":      float(len(drift_alarms)),
         "Unit":       "Count"},
    ]
    # Per-model calibration coverage metrics.
    for model_id, metrics in coverage_summary.items():
        metrics_payload.extend([
            {"MetricName": f"Coverage95_{model_id}",
             "Value":      float(metrics["coverage_95"]),
             "Unit":       "None"},
            {"MetricName": f"WIS_{model_id}",
             "Value":      float(metrics["wis"]),
             "Unit":       "None"},
        ])
    cloudwatch.put_metric_data(
        Namespace=CLOUDWATCH_NAMESPACE,
        MetricData=metrics_payload)

    if drift_alarms:
        for alarm in drift_alarms:
            cloudwatch.raise_alarm({
                "alarm_name":   f"calibration_drift_{alarm['model_id']}_{alarm['metric']}",
                "severity":     alarm["severity"],
                "description":  alarm["description"],
                "observed":     alarm["observed"],
                "threshold":    alarm["threshold"],
                "run_id":       run_id,
            })

    logger.info("Delivered forecast for %s: %d horizons, %d scenarios, %d alarms",
                jurisdiction["fips"], written,
                len(scenario_outputs), len(drift_alarms))
    return {
        "horizons_written":   written,
        "scenarios_written":  len(scenario_outputs),
        "drift_alarm_count":  len(drift_alarms),
    }
```

---

## Full Pipeline

Stitching the steps together. Production runs each step as a separate Step Functions task with retries, error handling, and CloudWatch alarms; the demo runs them sequentially in one process so you can see the data flow.

```python
def run_epidemic_forecast_pipeline(table, registry, event_bus, cloudwatch, s3,
                                    jurisdiction=JURISDICTION):
    """End-to-end pipeline orchestration.

    The demo wires up synthetic data; production starts with the
    Kinesis surveillance ingestion fan-in plus the harmonized
    S3 prefix populated by the streaming ingest job.
    """
    run_id = str(uuid.uuid4())
    print(f"\n=== Epidemic Forecast Pipeline run_id={run_id} ===\n")

    # --- Generate synthetic input data (production reads from Kinesis/S3) ---
    raw_records, true_incidence = generate_synthetic_surveillance(jurisdiction)
    total_records = sum(len(r) for r in raw_records.values())
    print(f"[input] {total_records} synthetic records across "
          f"{len(raw_records)} feeds for jurisdiction {jurisdiction['fips']}")

    # Persist raw records to "S3" so the harmonization step has a real
    # source to read from.
    for feed_id, records in raw_records.items():
        key = (f"raw-surveillance/{jurisdiction['fips']}/"
               f"{feed_id}/{run_id}.json")
        s3.put_object(Bucket=RAW_SURVEILLANCE_BUCKET, Key=key,
                      Body=json.dumps(records, default=str))

    # --- Step 1: Harmonize ---
    print("\n[step 1] harmonize_surveillance")
    harmonized = harmonize_surveillance(
        raw_records, jurisdiction, s3, HARMONIZED_BUCKET)
    panel = build_signal_panel(harmonized)
    print(f"  -> harmonized {sum(len(v) for v in harmonized.values())} records")
    print(f"  -> built signal panel with {len(panel)} epi-weeks")
    print(f"  -> latest panel row: {panel[-1]}")

    # --- Step 2: Nowcast ---
    print("\n[step 2] run_nowcast")
    nowcaster, nowcast_artifact = run_nowcast(
        harmonized, panel, jurisdiction, s3, NOWCAST_BUCKET, run_id)
    nowcast_state = nowcast_artifact["nowcast_state"]
    latest_nowcast = nowcast_state[list(nowcast_state.keys())[-1]]
    print(f"  -> nowcast for last week: p10={latest_nowcast['p10']}, "
          f"p50={latest_nowcast['p50']}, p90={latest_nowcast['p90']}")
    print(f"  -> nowcast horizon: {len(nowcast_state)} weeks back")

    # --- Step 3: Per-model forecasts ---
    print("\n[step 3] run_per_model_forecasts")
    per_model_forecasts, seir_model, arima_model = run_per_model_forecasts(
        nowcast_state, panel, jurisdiction, s3,
        PER_MODEL_FORECAST_BUCKET, run_id)
    for forecast in per_model_forecasts:
        next_week = forecast["forecast_quantiles"][0]
        print(f"  -> {forecast['model_id']} ({forecast['model_family']}): "
              f"horizon-1 p50={next_week['quantiles'].get('0.5')}")

    # --- Step 4: Ensemble ---
    print("\n[step 4] run_ensemble")
    ensemble_artifact = run_ensemble(
        per_model_forecasts, registry, jurisdiction, s3,
        ENSEMBLE_FORECAST_BUCKET, run_id)
    next_ensemble = ensemble_artifact["ensemble_forecast"][0]
    print(f"  -> ensemble method: {ensemble_artifact['ensemble_method']}")
    print(f"  -> per-model weights: {ensemble_artifact['per_model_weights']}")
    print(f"  -> horizon-1 p50: {next_ensemble['quantiles'].get('0.5')}, "
          f"p10: {next_ensemble['quantiles'].get('0.1')}, "
          f"p90: {next_ensemble['quantiles'].get('0.9')}")

    # --- Step 5a: Validate calibration ---
    print("\n[step 5a] compute_holdout_calibration")
    coverage_summary = compute_holdout_calibration(
        per_model_forecasts, panel)
    for model_id, metrics in coverage_summary.items():
        print(f"  -> {model_id}: coverage_50={metrics['coverage_50']}, "
              f"coverage_80={metrics['coverage_80']}, "
              f"coverage_95={metrics['coverage_95']}, "
              f"WIS={metrics['wis']}")
    drift_alarms = detect_calibration_drift(coverage_summary)
    print(f"  -> drift alarms: {len(drift_alarms)}")

    # --- Step 5b: Compose scenarios ---
    print("\n[step 5b] compose_scenario_forecasts")
    scenario_outputs = compose_scenario_forecasts(
        seir_model, nowcast_state, SCENARIOS)
    for scen in scenario_outputs:
        print(f"  -> scenario {scen['scenario_id']}: "
              f"peak_p50={scen['peak_incidence_p50']} "
              f"at {scen['peak_epi_week_p50']}, "
              f"p10/p90 range={scen['peak_incidence_p10_p90']}")

    # --- Step 5c: Deliver ---
    print("\n[step 5c] deliver_forecast")
    delivery = deliver_forecast(
        ensemble_artifact, scenario_outputs, coverage_summary,
        drift_alarms, jurisdiction, run_id, table, registry,
        event_bus, cloudwatch, s3, CALIBRATION_HISTORY_BUCKET)
    print(f"  -> wrote {delivery['horizons_written']} horizons to DynamoDB")
    print(f"  -> wrote {delivery['scenarios_written']} scenarios to registry")
    print(f"  -> emitted {len(event_bus.events)} EventBridge events")
    print(f"  -> raised {len(cloudwatch.alarms)} CloudWatch alarms")

    return {
        "run_id":             run_id,
        "jurisdiction":       jurisdiction["fips"],
        "ensemble_artifact":  ensemble_artifact,
        "scenario_outputs":   scenario_outputs,
        "coverage_summary":   coverage_summary,
        "drift_alarms":       drift_alarms,
    }


def run_demo():
    """Run the pipeline end-to-end against the in-memory mocks.

    No AWS resources are touched; every external dependency is a
    mock. Useful for sanity-checking the forecast math, the
    nowcast fusion, the ensemble combination, the calibration
    check, and the scenario composition before wiring to real
    services.
    """
    table       = MockTable(FORECAST_SERVING_TABLE)
    registry    = MockRegistry()
    event_bus   = MockEventBus(FORECAST_EVENT_BUS_NAME)
    cloudwatch  = MockCloudWatch()
    s3          = MockS3()

    # Seed the registry with a couple of synthetic prior calibration
    # records so the WIS-weighted ensemble has something to work
    # with on the first run. Without this, the cold-start path
    # falls back to equal-weighting.
    for model_id in (SEIR_MODEL_VERSION, ARIMA_MODEL_VERSION):
        for w in range(4):
            registry.insert_calibration_record({
                "run_id":         f"warmup-{w}",
                "model_id":       model_id,
                "jurisdiction":   JURISDICTION["fips"],
                "evaluated_at_ts": (datetime.now(timezone.utc)
                                     - timedelta(weeks=w + 1)).isoformat(),
                "coverage_50":    0.50 + 0.02 * (w if model_id.startswith("seir") else -w),
                "coverage_80":    0.80 + 0.02 * (w if model_id.startswith("seir") else -w),
                "coverage_95":    0.92 + 0.01 * (w if model_id.startswith("seir") else -w),
                "wis":            18.0 + (3.0 if model_id.startswith("arima") else 0.0),
                "n_evaluated":    8,
            })

    result = run_epidemic_forecast_pipeline(
        table, registry, event_bus, cloudwatch, s3)

    print("\n=== Sample DynamoDB record (horizon-1) ===")
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

    print("\n=== Sample registry forecast bundle (top fields only) ===")
    if registry.forecasts:
        b = registry.forecasts[0]
        summary = {
            "run_id":               b["run_id"],
            "jurisdiction":         b["jurisdiction"],
            "n_ensemble_horizons":  len(b["ensemble_artifact"]["ensemble_forecast"]),
            "n_scenarios":          len(b["scenario_outputs"]),
            "ensemble_method":      b["ensemble_artifact"]["ensemble_method"],
            "per_model_weights":    b["ensemble_artifact"]["per_model_weights"],
            "drift_alarm_count":    len(b["drift_alarms"]),
        }
        print(json.dumps(summary, indent=2))

    return result


if __name__ == "__main__":
    run_demo()
```

---

## Sample Output

Running the demo against the in-memory mocks produces output like this. Numbers vary because of the synthetic-data noise but the pipeline structure, the harmonization, the nowcast, the per-model fits, the ensemble combination, the calibration check, and the scenario forecasts are deterministic given the seed.

```text
=== Epidemic Forecast Pipeline run_id=8f3a... ===

[input] 144 synthetic records across 4 feeds for jurisdiction 37

[step 1] harmonize_surveillance
  -> harmonized 144 records
  -> built signal panel with 36 epi-weeks
  -> latest panel row: {'epi_week': '2026-w21', 'lab_pcr_positivity': 65.4, ...}

[step 2] run_nowcast
  -> nowcast for last week: p10=68.2, p50=82.1, p90=98.8
  -> nowcast horizon: 4 weeks back

[step 3] run_per_model_forecasts
  -> seir-age-stratified-v3 (compartmental): horizon-1 p50=88.4
  -> arima-baseline-v2 (statistical): horizon-1 p50=78.1

[step 4] run_ensemble
  -> ensemble method: wis_weighted
  -> per-model weights: {'seir-age-stratified-v3': 0.54, 'arima-baseline-v2': 0.46}
  -> horizon-1 p50: 83.6, p10: 65.4, p90: 102.7

[step 5a] compute_holdout_calibration
  -> seir-age-stratified-v3: coverage_50=0.50, coverage_80=0.75, coverage_95=0.93, WIS=21.4
  -> arima-baseline-v2: coverage_50=0.25, coverage_80=0.50, coverage_95=0.75, WIS=29.6
  -> drift alarms: 1

[step 5b] compose_scenario_forecasts
  -> scenario baseline_no_intervention: peak_p50=124.8 at 2026-w27, p10/p90 range=[82.1, 178.3]
  -> scenario moderate_npi_indoor_masking: peak_p50=96.4 at 2026-w29, p10/p90 range=[60.2, 142.8]

[step 5c] deliver_forecast
  -> wrote 8 horizons to DynamoDB
  -> wrote 2 scenarios to registry
  -> emitted 1 EventBridge events
  -> raised 1 CloudWatch alarms

=== Sample DynamoDB record (horizon-1) ===
{
  "jurisdiction_target": "37#incidence_per_100k_per_week",
  "horizon_runid": "horizon-01#2026-...#8f3a...",
  "jurisdiction_fips": "37",
  "jurisdiction_name": "Demo State",
  "target": "incidence_per_100k_per_week",
  "epi_week": "2026-w22",
  "horizon_weeks": 1,
  "p_025": "62.1",
  "p_10": "65.4",
  "p_25": "73.8",
  "p_50": "83.6",
  "p_75": "94.2",
  "p_90": "102.7",
  "p_975": "108.4",
  "ensemble_method": "wis_weighted",
  "ensemble_config_version": "ensemble-wis-weighted-v1",
  ...
}
```

A real pipeline against a state's surveillance feeds runs the daily forecast cycle in two-to-four hours on a SageMaker training job and a small batch-transform job, produces the same shape of output, and writes the records to a real DynamoDB table that the hospital-operations API queries during morning bed huddles, plus the federal forecast hub submission file.

---

## Gap to Production

The demo is intentionally a sketch. Here is the distance between this code and something you would deploy.

**Real Bayesian probabilistic-programming library, not the demo's closed-form helper.** The `BayesianStateSpaceNowcaster` in this file uses inverse-variance-weighted fusion across feeds and a simplified reporting-delay correction. Production replaces it with a real PyMC, Stan, or NumPyro state-space model that fits the joint posterior over the hidden weekly incidence series and the per-feed reporting-delay distributions with NUTS sampling, returns full posterior samples, supports informative priors derived from feed-specific historical regression against eventual lab-confirmed truth, and emits convergence diagnostics that the training pipeline alarms on. The demo's nowcast is a useful illustration of the structure but materially understates the rigor a production system applies.

**Real SEIR with proper sampling, age stratification, and contact matrices.** The demo's `SEIRCompartmentalModel` is a single-compartment SEIR with population-mean parameters and Euler integration. Production uses age-stratified compartments (typically 5-year age bands) with stratified contact matrices from POLYMOD or its post-pandemic updates, RK4 or scipy odeint for the integration, full Bayesian parameter posteriors via PyMC or Stan with NUTS, and proper handling of time-varying parameters (waning immunity, behavior change, vaccination effects). Multi-strain compartments are added when relevant strains are co-circulating. The compartmental forecast that drives federal hub submissions is dramatically more sophisticated than the demo's simplified version.

**Real statistical models, not the demo's hand-rolled AR(2) MA(1).** Replace `StatisticalARIMABaseline` with [statsmodels SARIMAX](https://www.statsmodels.org/stable/generated/statsmodels.tsa.statespace.sarimax.SARIMAX.html) for proper auto-order selection, seasonality terms, and exogenous covariates (climate, mobility, school-calendar dummies). [Prophet](https://facebook.github.io/prophet/) is a common second baseline because of its handling of changepoints and holidays. For multi-series state-space approaches, [statsmodels DynamicFactor](https://www.statsmodels.org/stable/statespace.html) or [GluonTS](https://github.com/awslabs/gluonts) hosted on a SageMaker container are the production-grade options. The full ensemble typically has a dozen or more members, not two.

**Real Kinesis or MSK ingestion, not synthetic data.** The demo synthesizes records in memory. Production has a Kinesis Data Stream per surveillance feed (or an MSK topic per feed if your environment standardizes on Kafka), with producer applications running at the source institutions (state public health labs, hospital association reporting, sentinel sites, sewer-shed monitoring partners) and a Kinesis Data Firehose or a Lambda consumer that lands records in S3 with deterministic prefixes. The streaming layer decouples ingestion from processing and provides replay capability when downstream models need to be re-run.

**Real Glue ETL, not in-process iteration.** The demo loops over Python lists for harmonization. Production runs each feed's harmonization as an AWS Glue PySpark job. Each job reads the raw landing prefix, applies the geography mapping (using a versioned geography registry that handles ZIP-to-county allocation, sewer-shed-to-county boundaries, and the periodic re-baselining of population denominators), the time alignment (epi-week computation using the official MMWR week algorithm), the unit conversion (handling the per-LOINC and per-feed gotchas that the demo glosses over), and writes the harmonized output partitioned by feed_id, geography, and epi-week. Each job runs under its own Glue service role with scoped S3, KMS, and population-registry permissions.

**Real SageMaker training and inference, not in-process model.** The demo fits the models in process. Production runs the nowcaster, the SEIR compartmental, the statistical baselines, and any neural-network forecasters as SageMaker workloads. The compartmental and Bayesian state-space models use custom containers with PyMC, Stan, or NumPyro pre-installed. The statistical and ML models use the SageMaker built-in XGBoost or scikit-learn containers. The ensemble combiner runs as a separate SageMaker Processing job. A SageMaker Batch Transform job handles the daily forecast inference at jurisdiction scale; a real-time endpoint handles the scenario-evaluation API. All endpoints and training jobs run in a private VPC subnet with VPC endpoints to S3, KMS, and CloudWatch Logs.

**Real Step Functions orchestration with Distributed Map.** The pipeline-orchestration logic (refresh feeds -> harmonize -> nowcast -> per-model forecast -> ensemble -> validate -> publish) runs as an AWS Step Functions state machine. Each step is a Glue job, a Lambda, a SageMaker Training job, or a SageMaker Batch Transform job, with `Retry` and `Catch` blocks for transient failures, a [Distributed Map](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-asl-use-map-state-distributed.html) state for the per-model parallel fan-out, and an EventBridge schedule that fires the daily inference cycle and weekly model retraining. The state machine emits `ExecutionFailed` events to a CloudWatch alarm.

**Real DynamoDB with proper indexing.** Replace `MockTable` with `boto3.resource('dynamodb').Table(FORECAST_SERVING_TABLE)`. The table needs a partition key (`jurisdiction_target`), a sort key (`horizon_runid`), encryption-at-rest with a customer-managed CMK, point-in-time recovery, on-demand billing for the unpredictable load that comes with the multi-jurisdiction rollout, a global secondary index on `(target, generated_at_ts)` for cross-jurisdiction comparison views, item-level TTL on historical records so the table does not grow unbounded, and the `BatchWriteItem` `UnprocessedItems` retry semantics that `MockTable` does not implement.

**Real Aurora PostgreSQL registry.** Replace `MockRegistry` with `boto3.client('rds-data').execute_statement(...)` calls against an Aurora Serverless v2 PostgreSQL cluster. The registry holds the full per-model trajectory artifacts, ensemble distributions, scenario comparisons, and calibration history. Public health analysts query it for ad-hoc analytics. The federal forecast hub submission flow joins forecasts to the canonical hub schema and exports the submission file. The schema is versioned with a migration tool (Alembic or Flyway).

**Real EventBridge bus and CloudWatch alarms.** The `MockEventBus` and `MockCloudWatch` accumulate events and metrics in process. Production uses `boto3.client('events').put_events(...)` and `boto3.client('cloudwatch').put_metric_data(...)`, plus CloudWatch alarms on calibration-coverage drift (alarm if any model's 90% credible interval coverage drops below threshold for two consecutive weeks), training convergence (alarm if R-hat exceeds 1.05 on any parameter), inference latency, DynamoDB write throttling, SageMaker endpoint 5xx rate, and ingestion completeness drift (alarm if any feed's record count drops more than two standard deviations below its 12-week baseline).

**Reporting-delay revision modeling.** The demo's reporting-delay correction is a simple multiplier on the most recent two weeks. Production maintains per-feed reporting-delay distributions as full probability mass functions, fitted from the historical relationship between report-receipt date and specimen-collection date. The PMFs are themselves continuously updated as new data arrives. Surveillance data revises retrospectively; a case reported in week 43 may have actually occurred in week 40 and only made it through the chain three weeks later. The harmonization layer must distinguish "reported by week" from "occurred by week" and the nowcasting layer must model the revision dynamics explicitly.

**Multi-strain and multi-pathogen modeling.** The demo assumes a single pathogen with a single set of compartments. Production respiratory-virus systems frequently must handle multiple strains simultaneously (multiple flu A subtypes, flu A and flu B, RSV alongside flu and SARS-CoV-2). Multi-strain models multiply the compartment count and require strain-specific surveillance feeds (often genomic sequencing from GISAID or national networks). The engineering work is significant; the public health value during multi-pathogen seasons is substantial.

**Calibration-drift monitor with continuous backtests.** The training step computes coverage on a temporal holdout once. Production runs a continuous calibration-monitoring job that backtests recent forecasts against subsequently observed outcomes (when the actual incidence for week T arrives, compare it to the forecast generated at week T - h for various horizons h; aggregate across the cohort to estimate empirical coverage of the credible intervals; alarm when coverage drops below the configured threshold). Without this, the system can be overconfident for months before anyone notices, and clinician trust takes years to rebuild.

**Federation with national forecast hubs.** Production state-level systems contribute to national ensembles like the [CDC FluSight](https://www.cdc.gov/flu-forecasting/about/index.html) hub. Federation requires conforming to the national hub's submission format (typically a quantile-encoded CSV with specific column names and target definitions), submission cadence, target definitions, and quality standards. The engineering work is moderate; the institutional work (joining the consortium, signing the data-use agreements, accepting the publication review process) is non-trivial. Federated forecasting is the right answer for almost every jurisdiction.

**Public communication infrastructure.** Surfacing probabilistic forecasts to the public is a different problem than surfacing them to epidemiologists. The audience does not interpret quantile forecasts natively. Production maintains a separate public-communication layer that translates the model's forecasts into language a non-technical reader can act on, designed by a public-health communication specialist, with explicit guardrails against generating statements that look like predictions or guarantees. The CloudFront-fronted public dashboard renders forecasts as intervals plus narrative ("we expect cases to increase, with the most likely range between X and Y over the next four weeks, and a small chance of higher").

**Outbreak-response mode.** During an active outbreak, the forecasting cadence may need to shift from weekly to daily, the scenario set may change frequently as policy options come and go, and the public-facing communication tempo may exceed what the standard pipeline supports. Production systems have an explicit outbreak-response mode with elevated cadence, explicit decision-support framing, and tighter coupling to the outbreak investigation team (Recipe 3.10). Switching modes mid-outbreak is operationally fragile; production systems test the switch periodically.

**Equity and bias auditing.** Forecasts trained on surveillance data that systematically under-represents certain populations produce projections that miscalibrate for those populations. Test access disparities, language barriers in syndromic reporting, sewer-shed coverage gaps in wastewater, and unequal hospital-reporting completeness all bias the input data. Production systems evaluate forecast calibration separately for major demographic subgroups and for geographic units known to have data-quality challenges. Where calibration differs, the system needs subgroup-specific recalibration or explicit limitation of scope.

**Reproducibility.** Forecasts published to federal hubs must be reproducible. This means the code, the input data state at the time of the run, the feed-spec version, the harmonization version, the model parameter posteriors, and the ensemble combination logic all have to be versioned and stored with sufficient metadata to reconstruct a past forecast on demand. Production systems treat reproducibility as a primary operational requirement, not an after-the-fact reconstruction effort.

**HIPAA and audit controls end-to-end.** Every storage and compute service that touches line-list data uses encryption with a customer-managed KMS key. CloudTrail logs all data-plane API calls with data events on the PHI-bearing buckets and the DynamoDB serving table. CloudWatch log groups are KMS-encrypted. IAM roles are scoped to specific resource ARNs. An AWS BAA is in place. The demo touches none of this; production cannot ship without all of it. The forecast bundle audit trail captures which feed-spec version, which harmonization version, which nowcast model, which per-family models, and which ensemble configuration produced which forecast for which jurisdiction on which date, written through Kinesis Data Firehose into an S3 bucket with Object Lock in compliance mode.

**Idempotency and rerun safety.** The forecast pipeline must be safe to repeat. Harmonization is deterministic given the same input data state. Nowcasting is reproducible given a fixed random seed and the same input panel. Forecast generation is reproducible (or, for stochastic models, has reproducibility through fixed seeding). Ensemble combination is deterministic. DynamoDB writes are idempotent on the primary key. The demo achieves idempotency naturally through the in-memory mocks; production has to be deliberate about each step's contract.

**Testing.** Unit tests cover the harmonization functions (geography mapping handles multi-county ZIPs correctly, time alignment handles year-end edge cases, unit conversion handles each per-LOINC special case), the nowcaster (the fusion math is correct for edge cases like single-feed weeks, the reporting-delay correction does not produce negative or wildly inflated values), the SEIR simulator (the compartments sum to N at every step, the trajectory matches a known closed-form solution for the simple parameter case), the ensemble combiner (Vincentized combination preserves quantile ordering, weighting is correct under different calibration histories), the calibration computer (coverage metrics are correct on synthetic ground truth), and the DynamoDB write idempotency. Integration tests run the pipeline against a known-input synthetic dataset and assert the surfaced forecasts against expected values. End-to-end tests stand up real Kinesis, S3, DynamoDB, SageMaker, Aurora, and EventBridge resources in a sandbox account.

**Structured logging.** Replace the demo's `print` calls with `logger.info(..., extra={...})` calls that emit JSON-formatted structured logs to CloudWatch Logs. Log structural metadata only (run_id, jurisdiction_fips, pipeline stage, feed_id, model_id, runtime_ms), never raw line-list records, never per-geography forecast values at sub-state resolution.

**Regulatory framing.** A forecasting system that informs public-health policy decisions has its own regulatory and political context. Open-data conformance to public records laws, transparency requirements around models that inform government decisions, and the implicit social contract that forecasts published under government authority are consistent with documented methodology all apply. The `assumption_disclosure` field on every scenario exists because this regulatory and political context demands it. Build the system that way from the start and the political conversation is a discussion. Build it the other way and the political conversation is a redesign.

**The shape of the gap.** The forecasting math in this file is a sketch but it is fundamentally correct. The plumbing around it (streaming ingestion, harmonization governance, reporting-delay revision modeling, multi-strain compartments, federation with national hubs, calibration monitoring, equity audit, public communication, outbreak-response mode, regulatory framing) is what takes the bulk of the engineering work. Plan for the plumbing to be 80% of the project; the forecasting math itself is the easier part once you have a competent statistician on the team.

---

## Related Resources

- [Recipe 12.9: Epidemic Forecasting](chapter12.09-epidemic-forecasting): The main recipe with the full architectural walkthrough this Python companion implements.
- [Recipe 3.10 (Outbreak Detection)](chapter03.10-epidemic-outbreak-detection): The detection counterpart to forecasting; production systems run both and integrate them through shared surveillance ingestion.
- [Recipe 12.5 (Hospital Census Forecasting)](chapter12.05-hospital-census-forecasting): Hospital-level forecasting that consumes regional epidemic forecasts as a primary input feature for surge planning.
- [PyMC](https://www.pymc.io/) and [Stan](https://mc-stan.org/) and [NumPyro](https://num.pyro.ai/): Bayesian probabilistic-programming libraries suitable for compartmental and state-space epidemic models. Drop-in replacements for the demo's helper classes.
- [statsmodels SARIMAX](https://www.statsmodels.org/stable/generated/statsmodels.tsa.statespace.sarimax.SARIMAX.html): Frequentist seasonal ARIMA implementation; the standard production replacement for the demo's `StatisticalARIMABaseline`.
- [Prophet](https://facebook.github.io/prophet/): Statistical forecasting framework widely used as an additional ensemble member for its handling of changepoints and holidays.
- [GluonTS](https://github.com/awslabs/gluonts): Time-series forecasting toolkit with state-of-the-art neural-network forecasters; SageMaker-friendly via custom containers.
- [`epyestim`](https://github.com/lo-hfk/epyestim) and [EpiNow2](https://github.com/epiforecasts/EpiNow2): Specialized libraries for effective reproduction number estimation and short-term epidemic forecasting; widely used at academic and government forecasting groups.
- [CDC FluSight Forecasting](https://www.cdc.gov/flu-forecasting/about/index.html): The federal coordination layer for collaborative flu forecasting in the US, including the public forecast hub format that production state-level systems submit to.
- [CDC Center for Forecasting and Outbreak Analytics](https://www.cdc.gov/forecast-outbreak-analytics/index.html): The CFA program coordinates infectious-disease forecasting across pathogens and partners.
- [Reich Lab](https://reichlab.io/): Influential academic forecasting group whose ensemble methods underpin many production hubs.
- [CMU Delphi Group](https://delphi.cmu.edu/): Producers of multiple data sources and forecasting models, including the COVIDcast indicator API.
- [Weighted Interval Score (Bracher et al. 2021)](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1008618): The standard probabilistic scoring rule used by the COVID-19 Forecast Hub and FluSight.
- [POLYMOD contact study](https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.0050074): The widely-used age-stratified contact matrix that underpins many compartmental models.
- [CDC National Wastewater Surveillance System](https://www.cdc.gov/nwss/wastewater-surveillance.html): The federal program that standardized wastewater surveillance for SARS-CoV-2 and other pathogens.
- [Amazon Kinesis Data Streams Documentation](https://docs.aws.amazon.com/streams/latest/dev/introduction.html): The streaming ingestion layer for surveillance feeds.
- [AWS Glue Documentation](https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html): The ETL framework for the harmonization pipeline.
- [Amazon SageMaker Bring Your Own Container](https://docs.aws.amazon.com/sagemaker/latest/dg/your-algorithms.html): Pattern for hosting custom Bayesian and compartmental models on SageMaker. The right way to deploy a PyMC or Stan model to a real-time endpoint.
- [AWS Step Functions Distributed Map](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-asl-use-map-state-distributed.html): The right pattern for fanning out per-model forecasts in parallel.
- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Official SageMaker examples including custom-container patterns useful for hosting compartmental and Bayesian models.

---

*← [Recipe 12.9: Epidemic Forecasting](chapter12.09-epidemic-forecasting) · [Chapter 12 Index](chapter12-index)*
