# Recipe 12.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 12.3. It shows one way you could translate the ED arrival forecasting pipeline into working Python using boto3 against Amazon Kinesis Data Streams (here represented by an in-memory list of synthetic ADT registration records), Amazon S3 (here represented by a `MockS3` dict), AWS Glue (here represented by an in-process Python aggregation), Amazon SageMaker (here represented by a pure-Python `PoissonGLM` volume model and a `MultinomialAcuityClassifier` that stand in for a real Poisson regression and a real multinomial classifier), AWS Step Functions (here represented by sequential function calls), Amazon DynamoDB (mocked with `MockTable`), Amazon EventBridge (mocked with `MockEventBus`), and Amazon CloudWatch (mocked with `MockCloudWatch`). The demo generates synthetic ADT-A04 registration records with realistic daily, weekly, and seasonal arrival patterns plus weather and flu-surveillance effects so you can see the feature engineering, the volume forecast, the acuity-mix classifier, and the prediction-interval logic work end-to-end without provisioning anything. It is not production-ready. There is no real Kinesis stream, no real Glue ETL, no real SageMaker training job, no real Step Functions state machine, no real DynamoDB table, no real EventBridge bus, no real CloudWatch alarms, no per-Lambda IAM least privilege, no KMS customer-managed keys, no VPC endpoints, no late-record reconciliation, no diversion window handling, no triage-time ESI reconciliation pass, no real weather forecast feed, no charge-nurse override capture, no surge-plan trigger logic, no inpatient-census coupling, and no drift detection. Think of it as the sketchpad version: useful for understanding the shape of an ED arrival forecasting pipeline that respects the count-data discipline, the acuity-mix discipline, the prediction-interval-not-point-estimate discipline, the multi-horizon-forecast discipline, and the operational-decision-not-model-output discipline this recipe demands. It is not something you would point at a real charge nurse on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the five pseudocode steps from the main recipe: aggregate the ADT registration stream into hourly arrival counts per ED per ESI level (Step 1); build the feature table with calendar features, weather, flu surveillance, event flags, and lag features (Step 2); train a count-regression volume model and a multinomial acuity classifier with a 90-day held-out validation window (Step 3); generate hourly forecasts at 4-hour, 12-hour, and 24-hour horizons including 80% and 95% prediction intervals and per-acuity breakdowns (Step 4); load the forecast records to DynamoDB keyed by `ed_id` with an idempotent batched write and emit an EventBridge completion event (Step 5). The synthetic ED, the synthetic arrival rates, the synthetic weather, the synthetic flu index, and the synthetic event calendar in the demo are fictional; nothing in this file should be interpreted as real ED arrival data from any real institution.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

The demo runs against the Python standard library plus boto3; no other packages are imported. Production deployments swap the demo's pure-Python `PoissonGLM` and `MultinomialAcuityClassifier` for real model libraries (statsmodels' GLM with the Poisson family for the volume baseline, scikit-learn's `LogisticRegression(multi_class='multinomial')` or a gradient boosting library for the acuity classifier, [Prophet](https://facebook.github.io/prophet/) when you want auto-handled multi-seasonality with external regressors, or the SageMaker [DeepAR built-in algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html) when you are forecasting jointly across many EDs in a health system); the Gap to Production section spells out the substitutions.

In production you would also configure an Amazon Kinesis Data Stream for the ADT-A04 registration ingest (or Amazon HealthLake for systems that want full FHIR storage), an Amazon S3 bucket for the hourly arrival counts, the weather and surveillance feeds, the model artifacts, and the forecast outputs (one prefix per concern, all SSE-KMS encrypted with a customer-managed key), an AWS Glue Streaming job that aggregates the raw ADT records into hourly counts per ED per ESI level, an Amazon SageMaker training job that fits the volume and acuity models on the modeling-ready table from S3, an Amazon SageMaker inference endpoint that serves the trained models behind a private VPC endpoint, an AWS Step Functions state machine that orchestrates the hourly cycle (aggregate -> feature-join -> infer -> load) with retries and `Catch` blocks, an Amazon EventBridge schedule that triggers the state machine every hour for inference and weekly for retraining, an Amazon DynamoDB table for the served forecasts keyed by `ed_id` with a sort key combining `forecast_for_hour` and `generated_at`, AWS Lambda functions for the lightweight transforms (weather API pulls, flu-index pulls, forecast post-processing, DynamoDB loader), Amazon CloudWatch dashboards and alarms for pipeline failures and per-horizon forecast drift, and a thin integration layer that exposes the forecast records to the charge-nurse dashboard, the staffing scheduler, and the surge-plan trigger logic. The demo replaces all of these with a single in-process Python file so the focus stays on the feature engineering, the count-regression math, the acuity-mix classification, the prediction interval generation, and the per-horizon forecast composition rather than on the platform plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `kinesis:GetRecords`, `kinesis:GetShardIterator`, and `kinesis:DescribeStream` on the ADT registration stream
- `s3:GetObject` and `s3:PutObject` on the hourly-arrivals prefix, the weather prefix, the flu-index prefix, the event-calendar prefix, the model-artifact prefix, and the forecast-output prefix
- `glue:StartJobRun` and `glue:GetJobRun` on the hourly-aggregation Glue job, plus the Glue service role's permissions for the streaming ETL job
- `sagemaker:CreateTrainingJob`, `sagemaker:DescribeTrainingJob`, `sagemaker:CreateModel`, `sagemaker:CreateEndpointConfig`, `sagemaker:UpdateEndpoint`, and `sagemaker:InvokeEndpoint` on the volume and acuity models
- `dynamodb:BatchWriteItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, and `dynamodb:GetItem` on the `ed-forecasts` table, scoped to the specific table ARN
- `events:PutEvents` on the ed-forecast-events bus for emitting pipeline-lifecycle events (run started, hourly aggregation completed, forecast generated, forecasts loaded, drift alarm raised)
- `states:StartExecution` on the ed-forecast Step Functions state machine for the hourly inference run and the weekly retraining run
- `cloudwatch:PutMetricData` for the operational metrics (per-horizon MAPE, per-ESI-level macro F1, forecast-vs-actual residual mean, hourly inference latency, DynamoDB write throttle count)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the S3 prefixes, the DynamoDB table, the Kinesis stream, and the model-artifact bucket
- `secretsmanager:GetSecretValue` on the weather-API and flu-surveillance-API credentials secrets pinned to the current rotation version

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The weather-pull Lambda has read access to the weather-API secret and write access to the weather S3 prefix, but no SageMaker permissions. The forecast-loader Lambda has read access to the forecast-output S3 prefix and write access to the `ed-forecasts` DynamoDB table, but no Kinesis permissions. The aggregation Glue job has read access to the Kinesis stream and write access to the hourly-arrivals S3 prefix, but no DynamoDB write access. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **ADT messages contain PHI directly.** An HL7 ADT-A04 registration message carries patient name, MRN, date of birth, demographics, and the chief complaint. Even after aggregation to hourly counts the upstream stream is full PHI. The Kinesis stream uses server-side encryption with a customer-managed KMS key, the consumers run inside the institutional VPC with no public network path, and CloudTrail logs every consumer call. The hourly counts that flow downstream are derived from PHI and live under the BAA, even though the count rows themselves carry no patient identifiers.
- **Hour boundaries are local time at the ED, not UTC.** ED operations are local. A 02:00 hour at a Pacific-time ED is a different operational reality than a 02:00 hour at an Eastern-time ED. The pipeline tags each record with the ED's local timezone and aggregates against local hours. Mixing UTC and local time here produces subtle but real bugs (the daily seasonality pattern shifts seven hours; the model learns nonsense).
- **The acuity assignment lags the arrival.** ESI level is assigned at triage, which can be minutes to hours after the registration timestamp. The pipeline takes the placeholder approach: count the arrival in the hour it registered, with `esi_unknown` as a temporary label, and reconcile to the assigned ESI level when the triage record arrives. The demo's synthetic data assumes ESI is known at registration so you can see the full pipeline; the Gap to Production section calls out the reconciliation pass you would add for real data.
- **Lag features are how the model gets recent context.** Last hour's arrivals, the same hour yesterday, the same hour last week. These three lags do most of the heavy lifting for short-horizon accuracy. Production care: at inference time the lag at horizon `h > 1` cannot use a future actual; the pipeline either uses the model's own previous predictions (recursive forecasting, accumulates error) or fits a separate model per horizon (direct forecasting, more compute). The demo uses recursive forecasting because it is simpler to read.
- **The prediction interval is the operational primitive, not the point estimate.** A charge nurse cares about the upper bound on hourly arrivals, not the expected value. The volume model's residual standard deviation on the held-out validation window drives the interval width. If the model produces tight intervals on validation but loose intervals in production, your training data and your inference data are not the same thing and you have a feature-drift problem to investigate.
- **Acuity is harder than volume.** Volume forecasts converge nicely with two years of history and the right calendar and weather features. Acuity-mix classifiers are more sensitive to short-term shifts (a flu wave concentrates ESI 3 visits, a heat wave concentrates ESI 2 visits) and the historical training data may not reflect the immediate present. Production builds the acuity model on a faster retraining cadence than the volume model (often weekly vs monthly) for this reason.
- **DynamoDB rejects Python `float`.** Every count, lower bound, upper bound, share fraction, and metric value passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses many Lambdas, Glue jobs, and SageMaker training jobs into a single Python file.** In production the streaming aggregation Glue job, the feature-join Lambda, the volume-model and acuity-model SageMaker training jobs, the SageMaker inference endpoint, the forecast-postprocessing Lambda, and the DynamoDB-loader Lambda are separate units of work with their own IAM roles, error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the modeling horizons, the prediction-interval levels, the validation window length, the per-ESI default shares, and the synthetic-data parameters are what you would change between environments.

```python
import json
import logging
import math
import random
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import mean, stdev

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights for cross-call investigation.
# ADT registration messages contain PHI directly (patient name,
# MRN, demographics, chief complaint). The aggregation step
# strips identifiers; everything downstream of the Glue boundary
# is hourly-count aggregates without per-patient identifiers.
# Log structural metadata only (run_id, ed_id, hour_local,
# arrival_count, mean_error, runtime_ms), never raw ADT records,
# never per-patient timestamps tied to identifiable visits.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from S3, DynamoDB, EventBridge,
# CloudWatch, Kinesis, and SageMaker. The hourly inference cycle
# is a scheduled batch job with a charge-nurse waiting on the
# refreshed dashboard, so retries should be quick and capped.
# A stuck dependency must not balloon a 90-second hourly cycle
# into a multi-minute incident.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across function calls within the
# pipeline so each call does not pay the connection cost. The
# demo wires up MockS3 / MockTable / MockEventBus / MockCloudWatch
# via run_demo() and never touches these real handles; they are
# staged here so production wiring is a one-line swap. boto3
# client and resource construction is lazy (no network call
# until first use), so the unused handles are free at import.
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
sagemaker_client   = boto3.client("sagemaker",
                                  region_name=REGION,
                                  config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do
# not exist; see run_demo() at the bottom.
ADT_KINESIS_STREAM_NAME    = "ed-adt-registration-stream"
HOURLY_ARRIVALS_BUCKET     = "ed-forecast-arrivals-hourly"
WEATHER_BUCKET             = "ed-forecast-weather"
FLU_INDEX_BUCKET           = "ed-forecast-flu-index"
EVENT_CALENDAR_BUCKET      = "ed-forecast-event-calendar"
MODEL_ARTIFACT_BUCKET      = "ed-forecast-models"
FORECAST_OUTPUT_BUCKET     = "ed-forecast-outputs"
ED_FORECASTS_TABLE         = "ed-forecast-records"
FORECAST_EVENT_BUS_NAME    = "ed-forecast-events-bus"
CLOUDWATCH_NAMESPACE       = "EDArrivalForecast"

# --- Versioning ---
# Every forecast record carries the model version active at the
# time of generation. This is how a future audit reconstructs
# which model produced which dashboard reading on which night.
PIPELINE_VERSION       = "ed-arrivals-v1.4"
VOLUME_MODEL_VERSION   = "poisson-glm-2026-04-08"
ACUITY_MODEL_VERSION   = "multinomial-2026-04-08"

# --- ED and Time Configuration ---
# Synthetic ED for the demo. Production reads the ED list from
# a registry table and runs the pipeline per-ED in a Step
# Functions Map state.
SYNTHETIC_ED_ID       = "regional-medical-center-001"
SYNTHETIC_ED_TIMEZONE = "US/Eastern"   # for documentation only; demo uses naive local times

# --- Forecast Horizons ---
# Three operational horizons cover the typical ED decision
# surface: 4 hours for charge-nurse call-in decisions, 12 hours
# for shift-staffing tweaks, 24 hours for next-day shift planning.
# Each horizon is evaluated separately because accuracy degrades
# with horizon length.
FORECAST_HORIZONS_HOURS = [4, 12, 24]

# --- Validation Window ---
# 90 days of recent history held out from training and used for
# computing forecast-error metrics and the residual standard
# deviation that drives prediction intervals. Less than 60 days
# does not span enough day-of-week and weather variation; more
# than 120 days starves the training set without proportional
# benefit.
VALIDATION_WINDOW_DAYS = 90

# --- Prediction Interval Levels ---
# 80% interval for typical operational planning, 95% for the
# upper-bound surge-plan trigger. The z-scores correspond to
# the standard normal approximation; production with a true
# Poisson or negative-binomial model would use the actual
# distribution's quantile.
PREDICTION_INTERVAL_LEVELS = {
    "80": Decimal("1.282"),
    "95": Decimal("1.960"),
}

# --- Acuity / ESI Levels ---
# Emergency Severity Index ranges from 1 (resuscitation) to 5
# (routine). Level 1 and Level 2 demand immediate room and
# physician attention; Level 4 and Level 5 can be handled in a
# fast-track lane with an advanced practice provider.
ESI_LEVELS = [1, 2, 3, 4, 5]

# Default mix used as a fallback when the acuity classifier
# cannot produce a confident split (e.g., very early hours of
# new ED onboarding before enough triage history has accumulated).
# The defaults below are illustrative; production reads the
# baseline mix from the institution's ESI mix history.
DEFAULT_ACUITY_SHARES = {
    1: Decimal("0.02"),
    2: Decimal("0.18"),
    3: Decimal("0.46"),
    4: Decimal("0.24"),
    5: Decimal("0.10"),
}

# --- Synthetic Data ---
# Knobs for the demo's synthetic-arrivals generator. The ranges
# produce a small but realistic-shaped two-year history with
# daily, weekly, and seasonal patterns plus weather effects and
# flu-season uplift.
SYNTHETIC_HISTORY_DAYS = 730     # two years of hourly history
SYNTHETIC_RANDOM_SEED  = 42

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("ADT_KINESIS_STREAM_NAME",    ADT_KINESIS_STREAM_NAME),
    ("HOURLY_ARRIVALS_BUCKET",     HOURLY_ARRIVALS_BUCKET),
    ("WEATHER_BUCKET",             WEATHER_BUCKET),
    ("FLU_INDEX_BUCKET",           FLU_INDEX_BUCKET),
    ("EVENT_CALENDAR_BUCKET",      EVENT_CALENDAR_BUCKET),
    ("MODEL_ARTIFACT_BUCKET",      MODEL_ARTIFACT_BUCKET),
    ("FORECAST_OUTPUT_BUCKET",     FORECAST_OUTPUT_BUCKET),
    ("ED_FORECASTS_TABLE",         ED_FORECASTS_TABLE),
    ("FORECAST_EVENT_BUS_NAME",    FORECAST_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",       CLOUDWATCH_NAMESPACE),
]:
    assert _value, f"{_name} must be set before deploying."


def _to_decimal(value):
    """Convert numeric values to Decimal for DynamoDB-safe writes.

    DynamoDB rejects Python float at the SDK boundary because
    floating-point cannot represent every decimal value exactly.
    Pass everything numeric through this helper before any
    PutItem, BatchWriteItem, or UpdateItem call. Pandas and
    numpy types are not Decimal-friendly out of the box, so the
    helper covers the common cases (int, float, str-of-number,
    None) and lets exotic types fail loudly rather than silently.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        # bool is a subclass of int in Python; route it explicitly
        # so True does not become Decimal('1') unexpectedly.
        return value
    if isinstance(value, (int, float)):
        # Round float through string to avoid the float->Decimal
        # repr surprise (Decimal(0.1) is not Decimal('0.1')).
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(f"Cannot convert {type(value).__name__} to Decimal")
```

---

## Mocks and Synthetic Data

The demo never touches a real Kinesis stream, S3 bucket, DynamoDB table, EventBridge bus, or SageMaker endpoint. The mocks below stand in for those services so the focus stays on the forecasting logic. They print what they would write rather than failing, which makes the demo runnable without any AWS resources provisioned.

```python
class MockS3:
    """In-memory stand-in for an S3 bucket.

    Production uses boto3.client('s3').get_object / put_object.
    The mock stores objects keyed by (bucket, key) so the demo
    can show what would have been written and what would have
    been read at each pipeline stage.
    """

    def __init__(self):
        self.objects = {}    # (bucket, key) -> bytes

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

    Production uses boto3.resource('dynamodb').Table(name). The
    mock supports the operations the demo calls: batch_writer,
    put_item, query, get_item. It is not a complete DynamoDB
    emulation; it covers what this pipeline needs.
    """

    def __init__(self, name):
        self.name        = name
        self.items       = {}    # (pk, sk) -> item dict
        self.write_count = 0

    class _BatchWriter:
        def __init__(self, table):
            self.table = table

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def put_item(self, Item):
            pk = Item["ed_id"]
            sk = Item["forecast_for_hour_generated_at"]
            self.table.items[(pk, sk)] = dict(Item)
            self.table.write_count += 1

    def batch_writer(self):
        return self._BatchWriter(self)

    def put_item(self, Item):
        pk = Item["ed_id"]
        sk = Item["forecast_for_hour_generated_at"]
        self.items[(pk, sk)] = dict(Item)
        self.write_count += 1


class MockEventBus:
    """In-memory stand-in for EventBridge.

    Production uses boto3.client('events').put_events(...). The
    mock accumulates events so the demo can show what would have
    been emitted to the ed-forecast-events bus at each pipeline
    stage.
    """

    def __init__(self, name):
        self.name   = name
        self.events = []

    def put_events(self, Entries):
        self.events.extend(Entries)
        return {"FailedEntryCount": 0}


class MockCloudWatch:
    """In-memory stand-in for CloudWatch.

    Production uses boto3.client('cloudwatch').put_metric_data(...).
    The mock accumulates metrics so the demo can show what would
    have been emitted (per-horizon MAPE, per-ESI macro F1,
    inference latency, records-written count).
    """

    def __init__(self):
        self.metrics = defaultdict(list)

    def put_metric_data(self, Namespace, MetricData):
        for m in MetricData:
            self.metrics[f"{Namespace}/{m['MetricName']}"].append({
                "Value": m["Value"],
                "Unit":  m.get("Unit", "None"),
                "Time":  datetime.now(timezone.utc).isoformat(),
            })


def generate_synthetic_adt_records(history_days=SYNTHETIC_HISTORY_DAYS,
                                    seed=SYNTHETIC_RANDOM_SEED):
    """Generate synthetic ADT-A04 registration records.

    Production reads from a Kinesis Data Stream populated by the
    EHR's HL7 outbound feed. The demo synthesizes records with
    realistic daily, weekly, and seasonal arrival patterns plus
    weather-driven variability and a flu-season uplift.

    Pattern summary:
      - Hourly base rate has a daily curve peaking at ~18:00.
      - Mondays and weekends carry distinct weekly uplifts.
      - Cold months (Dec-Feb) carry a flu-season uplift.
      - Severe-weather days suppress walk-ins by ~25%.
      - Per-arrival ESI level is sampled from a baseline mix
        with hour-of-day skew (high acuity slightly more common
        in early-morning hours).
    """
    rng = random.Random(seed)

    # End the synthetic history at midnight today so the demo's
    # "current" time is well-defined.
    end_d   = date.today()
    start_d = end_d - timedelta(days=history_days)

    # Synthesize a parallel weather and flu-index series so the
    # downstream feature engineering has something to join on.
    weather_by_date   = {}
    flu_index_by_date = {}
    for i in range(history_days + 1):
        d = start_d + timedelta(days=i)
        # Temperature: rough sinusoid by month plus daily noise.
        seasonal_t = 50 + 30 * math.sin(2 * math.pi * (d.timetuple().tm_yday - 100) / 365)
        temp_f     = seasonal_t + rng.gauss(0, 8)
        precip_in  = max(0.0, rng.gauss(0.05, 0.2))
        wind_mph   = max(0.0, rng.gauss(8, 4))
        # Severe weather flag triggered by extremes.
        is_severe = (temp_f < 10 or temp_f > 100 or
                     precip_in > 1.0 or wind_mph > 30)
        weather_by_date[d.isoformat()] = {
            "temperature_f":    round(temp_f, 1),
            "precipitation_in": round(precip_in, 2),
            "wind_speed_mph":   round(wind_mph, 1),
            "is_severe":        is_severe,
        }
        # Flu index: rises Dec-Feb, falls otherwise.
        is_flu_season = d.month in (12, 1, 2)
        flu_index_by_date[d.isoformat()] = round(
            (45 if is_flu_season else 12) + rng.gauss(0, 5), 1)

    records   = []
    arrival_n = 0
    for i in range(history_days):
        d = start_d + timedelta(days=i)
        weather   = weather_by_date[d.isoformat()]
        flu_index = flu_index_by_date[d.isoformat()]

        is_weekend = d.weekday() in (5, 6)
        is_monday  = d.weekday() == 0

        # Daily seasonal uplift based on flu index.
        flu_uplift = 1.0 + (flu_index - 12) / 80.0
        # Severe-weather suppression.
        weather_factor = 0.75 if weather["is_severe"] else 1.0
        # Weekly factor: Mondays a bit busier, weekends mixed.
        weekly_factor = 1.10 if is_monday else (1.05 if is_weekend else 1.0)

        for hour in range(24):
            # Hourly intensity curve: low overnight, ramps to a
            # late-afternoon peak around 18:00, falls into evening.
            hourly_curve = (3.5
                            + 4.0 * math.exp(-((hour - 18) ** 2) / 18.0)
                            + 1.5 * math.exp(-((hour - 10) ** 2) / 8.0))
            mu = (hourly_curve
                  * flu_uplift
                  * weather_factor
                  * weekly_factor)

            # Sample a Poisson-ish count from the rate. Use the
            # standard sum-of-exponentials trick for small means;
            # close enough for a demo.
            count = 0
            t = 0.0
            while True:
                t += rng.expovariate(1.0)
                if t > mu:
                    break
                count += 1

            for _ in range(count):
                # Per-arrival timestamp uniformly within the hour.
                minute = rng.randint(0, 59)
                arrival_ts = datetime(
                    d.year, d.month, d.day, hour, minute, 0)
                # Sample an ESI level. High acuity slightly more
                # common in early-morning hours. Convert the
                # Decimal defaults to float for the sampling math.
                acuity_weights = [float(w) for w in DEFAULT_ACUITY_SHARES.values()]
                if hour < 6:
                    acuity_weights = [w * (1.4 if i in (0, 1) else 0.95)
                                      for i, w in enumerate(acuity_weights)]
                total_w = sum(acuity_weights)
                pick    = rng.uniform(0, total_w)
                acc     = 0.0
                esi     = 3
                for idx, w in enumerate(acuity_weights):
                    acc += w
                    if pick <= acc:
                        esi = ESI_LEVELS[idx]
                        break

                arrival_n += 1
                records.append({
                    "ed_id":        SYNTHETIC_ED_ID,
                    "arrival_ts":   arrival_ts.isoformat(),
                    "esi_level":    esi,
                    "encounter_id": f"E{arrival_n:08d}",
                })

    return records, weather_by_date, flu_index_by_date


def generate_synthetic_event_calendar():
    """Sparse event calendar covering the synthetic history.

    Production reads from a hand-curated calendar table that
    operations updates monthly. The demo creates a few illustrative
    entries so the feature pipeline has something to attach.
    """
    today = date.today()
    return [
        {"start_date": (today - timedelta(days=14)).isoformat(),
         "end_date":   (today - timedelta(days=14)).isoformat(),
         "name":       "Regional Basketball Tournament",
         "expected_impact": "moderate"},
        {"start_date": (today - timedelta(days=60)).isoformat(),
         "end_date":   (today - timedelta(days=60)).isoformat(),
         "name":       "City Marathon",
         "expected_impact": "moderate"},
    ]
```

---

## Step 1: Aggregate ADT Stream to Hourly Counts

This step consumes raw ADT registration records (one per arrival) and buckets them into hourly counts per ED per ESI level. In production this is an AWS Glue Streaming job that reads from Kinesis, applies a watermark for late-arriving records, and writes hourly Parquet partitions to S3. The demo does the equivalent in plain Python over the in-memory list so you can trace what each transform accomplishes.

```python
def aggregate_arrivals_to_hourly(adt_records):
    """Step 1: Bucket ADT records into hourly arrival counts per ESI level.

    See pseudocode Step 1 in the main recipe. The output is a list
    of rows, one per (ed_id, local_hour) pair, with per-ESI-level
    counts plus a total. A real pipeline reads from Kinesis with a
    five-minute watermark for late records; the demo assumes
    in-order arrival because the synthetic data is generated
    sequentially.
    """
    # 1a. Bucket each arrival into a (ed_id, local_hour) pair.
    # Hour boundaries are local time at the ED. The demo uses
    # naive datetimes; production tags each record with the ED's
    # IANA timezone identifier and floors against the local
    # wall-clock hour, not UTC.
    hourly_buckets = defaultdict(lambda: {
        "esi_1": 0, "esi_2": 0, "esi_3": 0, "esi_4": 0, "esi_5": 0,
        "esi_unknown": 0, "total": 0,
    })

    for record in adt_records:
        arrival_ts = datetime.fromisoformat(record["arrival_ts"])
        # Floor to the hour. Production uses the ED's local
        # timezone; the demo uses naive local times so the
        # synthetic data and the floored hour are consistent.
        local_hour = arrival_ts.replace(minute=0, second=0, microsecond=0)
        key = (record["ed_id"], local_hour.isoformat())

        bucket = hourly_buckets[key]

        # ESI level is assigned at triage. Production sees ~10-30%
        # of registrations arrive without an ESI level and
        # reconciles them when the triage record lands. The demo
        # assumes ESI is known at registration so the pipeline
        # is easier to read.
        esi = record.get("esi_level")
        if esi is None or esi not in ESI_LEVELS:
            bucket["esi_unknown"] += 1
        else:
            bucket[f"esi_{esi}"] += 1
        bucket["total"] += 1

    # 1b. Materialize the hourly rows. Production writes these to
    # S3 partitioned by (ed_id, year, month, day) as Parquet so
    # the downstream feature-engineering Glue job can read them
    # efficiently with predicate pushdown.
    output = []
    for (ed_id, hour_iso), counts in hourly_buckets.items():
        output.append({
            "ed_id":        ed_id,
            "local_hour":   hour_iso,
            "esi_1":        counts["esi_1"],
            "esi_2":        counts["esi_2"],
            "esi_3":        counts["esi_3"],
            "esi_4":        counts["esi_4"],
            "esi_5":        counts["esi_5"],
            "esi_unknown":  counts["esi_unknown"],
            "total":        counts["total"],
        })

    # 1c. Sort chronologically per-ED so downstream lag features
    # have predictable input order. A real Glue job reads sorted
    # Parquet partitions; the demo sorts in-process for clarity.
    output.sort(key=lambda r: (r["ed_id"], r["local_hour"]))

    # 1d. Fill gaps. Hours with zero arrivals are real signal
    # (overnight at a small ED, holiday closures), but they show
    # up as missing rows in the bucketing. The model needs every
    # hour represented to learn the daily curve correctly.
    if output:
        ed_ids = sorted({r["ed_id"] for r in output})
        filled = []
        for ed in ed_ids:
            ed_rows = [r for r in output if r["ed_id"] == ed]
            start_h = datetime.fromisoformat(ed_rows[0]["local_hour"])
            end_h   = datetime.fromisoformat(ed_rows[-1]["local_hour"])
            existing = {r["local_hour"]: r for r in ed_rows}
            cursor = start_h
            while cursor <= end_h:
                key = cursor.isoformat()
                if key in existing:
                    filled.append(existing[key])
                else:
                    filled.append({
                        "ed_id":       ed,
                        "local_hour":  key,
                        "esi_1": 0, "esi_2": 0, "esi_3": 0,
                        "esi_4": 0, "esi_5": 0, "esi_unknown": 0,
                        "total": 0,
                    })
                cursor += timedelta(hours=1)
        output = filled

    logger.info(
        "Aggregated %d hourly rows from %d raw arrivals",
        len(output), len(adt_records))
    return output
```

---

## Step 2: Build the Feature Table

The hourly counts get joined with calendar features, weather, flu surveillance, event flags, and lag features. This is where most of the modeling value is created. A model with great hyperparameters and bad features will be beaten by an average model with good features every time.

```python
US_FEDERAL_HOLIDAYS = {
    # Stub; production reads from a holiday calendar table that
    # accounts for state-specific holidays and observance shifts.
    "2025-01-01", "2025-07-04", "2025-12-25",
    "2026-01-01", "2026-07-04", "2026-12-25",
    "2024-01-01", "2024-07-04", "2024-12-25",
}


def build_feature_table(hourly_rows, weather_by_date,
                        flu_index_by_date, event_calendar):
    """Step 2: Attach calendar, weather, surveillance, event, and lag features.

    See pseudocode Step 2 in the main recipe. The output is a
    list of feature rows, one per hourly bucket, ready for the
    Step 3 modeling routines. Production runs this as a Glue or
    Lambda job that reads the hourly Parquet from S3 and writes
    a modeling-ready Parquet partition.
    """
    # Sort by ED and time to make the lag joins below straightforward.
    rows_sorted = sorted(hourly_rows,
                         key=lambda r: (r["ed_id"], r["local_hour"]))

    # Index by (ed_id, hour_iso) for the lag lookups.
    by_key = {(r["ed_id"], r["local_hour"]): r for r in rows_sorted}

    # Index event flags by date for fast lookups.
    event_dates = set()
    for ev in event_calendar:
        d_start = date.fromisoformat(ev["start_date"])
        d_end   = date.fromisoformat(ev["end_date"])
        cur     = d_start
        while cur <= d_end:
            event_dates.add(cur.isoformat())
            cur += timedelta(days=1)

    features = []
    for r in rows_sorted:
        local_hour = datetime.fromisoformat(r["local_hour"])
        day_iso    = local_hour.date().isoformat()

        # 2a. Calendar features. The model can only learn patterns
        # it has features for; encoding hour-of-day and day-of-week
        # explicitly gives the model a head start over inferring
        # them from raw timestamps.
        is_holiday  = day_iso in US_FEDERAL_HOLIDAYS
        # Days to nearest holiday (positive = upcoming, negative = past).
        # The demo uses a small fixed search window for simplicity.
        nearest_d = None
        for offset in range(-7, 8):
            probe = (local_hour.date() + timedelta(days=offset)).isoformat()
            if probe in US_FEDERAL_HOLIDAYS:
                if nearest_d is None or abs(offset) < abs(nearest_d):
                    nearest_d = offset
        holiday_distance_days = nearest_d if nearest_d is not None else 0

        # 2b. Weather features. Fall back to the closest available
        # reading if the exact day is missing; production uses a
        # join against an hourly weather feed instead of a daily
        # one but the principle is the same.
        weather = weather_by_date.get(day_iso, {
            "temperature_f": 65.0,
            "precipitation_in": 0.0,
            "wind_speed_mph": 5.0,
            "is_severe": False,
        })

        # 2c. Surveillance feature: most recent flu index reading.
        # The lag between reporting and effect is roughly a week,
        # so use the most recent available value, not a forecast.
        flu_index = flu_index_by_date.get(day_iso, 12.0)

        # 2d. Event flag.
        has_local_event = day_iso in event_dates

        # 2e. Lag features. Same hour yesterday, same hour last
        # week. These give the model recent-state context. At
        # training time the lags use actual past values; at
        # inference time the lag at horizon h > 1 uses the model's
        # own previous predictions (recursive forecasting).
        lag_1h_key   = (r["ed_id"],
                        (local_hour - timedelta(hours=1)).isoformat())
        lag_24h_key  = (r["ed_id"],
                        (local_hour - timedelta(hours=24)).isoformat())
        lag_168h_key = (r["ed_id"],
                        (local_hour - timedelta(hours=168)).isoformat())
        lag_1h   = by_key.get(lag_1h_key,   {}).get("total", 0)
        lag_24h  = by_key.get(lag_24h_key,  {}).get("total", 0)
        lag_168h = by_key.get(lag_168h_key, {}).get("total", 0)

        features.append({
            "ed_id":               r["ed_id"],
            "local_hour":          r["local_hour"],
            # Targets
            "target_total":        r["total"],
            "target_esi_1":        r["esi_1"],
            "target_esi_2":        r["esi_2"],
            "target_esi_3":        r["esi_3"],
            "target_esi_4":        r["esi_4"],
            "target_esi_5":        r["esi_5"],
            # Calendar features
            "hour_of_day":         local_hour.hour,
            "day_of_week":         local_hour.weekday(),
            "month":               local_hour.month,
            "is_weekend":          local_hour.weekday() in (5, 6),
            "is_holiday":          is_holiday,
            "holiday_distance_d":  holiday_distance_days,
            # Weather features
            "temperature_f":       weather["temperature_f"],
            "precipitation_in":    weather["precipitation_in"],
            "wind_speed_mph":      weather["wind_speed_mph"],
            "is_severe_weather":   weather["is_severe"],
            # Surveillance
            "flu_index":           flu_index,
            # Events
            "has_local_event":     has_local_event,
            # Lags
            "lag_1h":              lag_1h,
            "lag_24h":             lag_24h,
            "lag_168h":            lag_168h,
        })

    logger.info(
        "Built feature table: %d rows with %d feature columns",
        len(features), len(features[0]) if features else 0)
    return features
```

---

## Step 3: Train Volume and Acuity Models

Two parallel modeling tracks: a count regression for total hourly volume and a multinomial classifier for the per-acuity share. Both train on history holding out the most recent 90 days for validation. The volume model is evaluated by MAPE; the acuity classifier is evaluated by per-class log loss and macro F1.

The demo implements two pedagogical models. Production replaces them as described in the Gap to Production section.

```python
class PoissonGLM:
    """Pedagogical stand-in for a Poisson regression on hourly counts.

    Real production uses statsmodels' GLM with the Poisson family
    or a negative binomial model when the data is overdispersed.
    The demo uses a coordinate-descent on the squared-error
    objective with a log link to keep the math readable. The
    interface (fit, predict, sigma) is what matters: any model
    that produces a point forecast plus a residual standard
    deviation drops in.
    """

    # Feature names this model consumes. Must match the keys
    # built in Step 2.
    FEATURE_NAMES = [
        "hour_of_day", "day_of_week", "month",
        "is_weekend_int", "is_holiday_int", "holiday_distance_d",
        "temperature_f", "precipitation_in", "wind_speed_mph",
        "is_severe_int", "flu_index", "has_event_int",
        "lag_1h", "lag_24h", "lag_168h",
    ]

    def __init__(self):
        self.intercept = 0.0
        self.coef      = {name: 0.0 for name in self.FEATURE_NAMES}
        self.sigma     = 0.0   # residual standard deviation

    def _row_to_vector(self, row):
        """Convert a Step-2 feature row into the numeric vector."""
        return {
            "hour_of_day":        float(row["hour_of_day"]),
            "day_of_week":        float(row["day_of_week"]),
            "month":              float(row["month"]),
            "is_weekend_int":     1.0 if row["is_weekend"] else 0.0,
            "is_holiday_int":     1.0 if row["is_holiday"] else 0.0,
            "holiday_distance_d": float(row["holiday_distance_d"]),
            "temperature_f":      float(row["temperature_f"]),
            "precipitation_in":   float(row["precipitation_in"]),
            "wind_speed_mph":     float(row["wind_speed_mph"]),
            "is_severe_int":      1.0 if row["is_severe_weather"] else 0.0,
            "flu_index":          float(row["flu_index"]),
            "has_event_int":      1.0 if row["has_local_event"] else 0.0,
            "lag_1h":             float(row["lag_1h"]),
            "lag_24h":            float(row["lag_24h"]),
            "lag_168h":           float(row["lag_168h"]),
        }

    def _predict_one(self, x):
        """Linear combination plus exponential link."""
        z = self.intercept
        for name, val in x.items():
            z += self.coef[name] * val
        # Cap exponent for numerical stability.
        z = max(min(z, 8.0), -4.0)
        return math.exp(z)

    def fit(self, training_rows, n_iters=8, lr=0.001):
        """Iterative coordinate descent on the log-link squared error.

        A real Poisson GLM uses iteratively reweighted least
        squares against the deviance. The demo uses gradient
        descent on the squared-error objective for readability;
        it produces a model close enough to demonstrate the
        forecast pipeline.
        """
        if not training_rows:
            return self

        # Initialize the intercept to log of the mean count so
        # the optimizer starts in the right neighborhood.
        mean_count = max(0.5, mean(r["target_total"] for r in training_rows))
        self.intercept = math.log(mean_count)

        # Standardize numeric features so gradient descent
        # behaves. Production GLM solvers handle this internally;
        # the demo does it explicitly so the math is visible.
        feat_means = {name: 0.0 for name in self.FEATURE_NAMES}
        feat_sds   = {name: 1.0 for name in self.FEATURE_NAMES}
        n          = len(training_rows)
        vectors    = [self._row_to_vector(r) for r in training_rows]
        for name in self.FEATURE_NAMES:
            vals      = [v[name] for v in vectors]
            feat_means[name] = sum(vals) / n
            sd = stdev(vals) if n > 1 else 1.0
            feat_sds[name]   = sd if sd > 1e-9 else 1.0

        def standardize(v):
            return {name: (v[name] - feat_means[name]) / feat_sds[name]
                    for name in self.FEATURE_NAMES}

        # Gradient descent loop.
        for _ in range(n_iters):
            grad_intercept = 0.0
            grad_coef      = {name: 0.0 for name in self.FEATURE_NAMES}
            for row, v in zip(training_rows, vectors):
                vs    = standardize(v)
                pred  = self._predict_one(vs)
                err   = pred - row["target_total"]
                grad_intercept += err
                for name in self.FEATURE_NAMES:
                    grad_coef[name] += err * vs[name]
            self.intercept -= lr * grad_intercept / n
            for name in self.FEATURE_NAMES:
                self.coef[name] -= lr * grad_coef[name] / n

        # Compute residual sigma on training data. Production
        # computes it on the held-out validation window because
        # training residuals understate the operational error.
        residuals = []
        self._feat_means = feat_means
        self._feat_sds   = feat_sds
        for row, v in zip(training_rows, vectors):
            vs   = standardize(v)
            pred = self._predict_one(vs)
            residuals.append(row["target_total"] - pred)
        if len(residuals) > 1:
            self.sigma = stdev(residuals)
        else:
            self.sigma = 1.0

        return self

    def predict(self, row):
        """Predict expected hourly arrivals for a single feature row."""
        v = self._row_to_vector(row)
        if not hasattr(self, "_feat_means"):
            return self._predict_one(v)
        vs = {name: (v[name] - self._feat_means[name]) / self._feat_sds[name]
              for name in self.FEATURE_NAMES}
        return self._predict_one(vs)


class MultinomialAcuityClassifier:
    """Pedagogical multinomial classifier for per-ESI share.

    Production uses scikit-learn's LogisticRegression with
    multi_class='multinomial', or a gradient-boosted classifier
    when the relationships are non-linear. The demo computes
    smoothed per-feature share averages and combines them so
    you can see the full pipeline run without a sklearn dependency.
    """

    # Coarse buckets for hour-of-day and month; the model conditions
    # the share on these to capture the time-of-day and seasonal
    # acuity drift.
    HOUR_BUCKETS  = [(0, 6), (6, 12), (12, 18), (18, 24)]
    MONTH_BUCKETS = [(1, 4), (4, 7), (7, 10), (10, 13)]

    def __init__(self):
        # share_table[(hour_bucket, month_bucket, severe_flag)] = {esi -> share}
        self.share_table = {}
        self.fallback    = dict(DEFAULT_ACUITY_SHARES)

    def _bucket(self, value, buckets):
        for i, (lo, hi) in enumerate(buckets):
            if lo <= value < hi:
                return i
        return len(buckets) - 1

    def fit(self, training_rows):
        """Estimate per-bucket per-ESI share from training data."""
        # Counts per (bucket_key, esi_level)
        counts = defaultdict(lambda: {esi: 0 for esi in ESI_LEVELS})
        totals = defaultdict(int)

        for row in training_rows:
            hour_b  = self._bucket(row["hour_of_day"], self.HOUR_BUCKETS)
            month_b = self._bucket(row["month"], self.MONTH_BUCKETS)
            severe  = bool(row["is_severe_weather"])
            key     = (hour_b, month_b, severe)
            for esi in ESI_LEVELS:
                c = row[f"target_esi_{esi}"]
                counts[key][esi] += c
                totals[key]      += c

        # Convert to shares with Laplace smoothing so unseen
        # buckets do not produce zero shares (which the
        # multinomial cross-entropy can't handle).
        for key, esi_counts in counts.items():
            total = totals[key]
            smoothed_total = total + len(ESI_LEVELS)
            self.share_table[key] = {
                esi: (esi_counts[esi] + 1) / smoothed_total
                for esi in ESI_LEVELS
            }
        return self

    def predict_shares(self, row):
        """Return a dict {esi_level -> share} for a feature row."""
        hour_b  = self._bucket(row["hour_of_day"], self.HOUR_BUCKETS)
        month_b = self._bucket(row["month"], self.MONTH_BUCKETS)
        severe  = bool(row["is_severe_weather"])
        key     = (hour_b, month_b, severe)
        if key in self.share_table:
            return dict(self.share_table[key])
        return {esi: float(s) for esi, s in self.fallback.items()}


def train_volume_and_acuity_models(feature_table):
    """Step 3: Fit both models on training history with held-out validation.

    See pseudocode Step 3 in the main recipe. Returns a dict with
    the fitted models, validation metrics, and the model versions.
    Production runs each model as a separate SageMaker training
    job in parallel via Step Functions; the demo collapses both
    into a single in-process call.
    """
    if not feature_table:
        raise ValueError("feature_table is empty; cannot train")

    # 3a. Sort and split into training and validation windows.
    rows_sorted = sorted(feature_table, key=lambda r: r["local_hour"])
    last_hour   = datetime.fromisoformat(rows_sorted[-1]["local_hour"])
    cutoff      = last_hour - timedelta(days=VALIDATION_WINDOW_DAYS)

    training   = [r for r in rows_sorted
                  if datetime.fromisoformat(r["local_hour"]) < cutoff]
    validation = [r for r in rows_sorted
                  if datetime.fromisoformat(r["local_hour"]) >= cutoff]
    logger.info(
        "Train/validation split: %d training rows, %d validation rows",
        len(training), len(validation))

    # 3b. Fit the volume model.
    volume_model = PoissonGLM().fit(training)

    # 3c. Fit the acuity classifier.
    acuity_model = MultinomialAcuityClassifier().fit(training)

    # 3d. Evaluate on the held-out window. MAPE for volume,
    # macro-F1 for acuity (computed against the dominant class
    # per row for simplicity).
    abs_pct_errors = []
    for row in validation:
        if row["target_total"] == 0:
            continue   # avoid divide-by-zero in MAPE
        pred = volume_model.predict(row)
        abs_pct_errors.append(abs(pred - row["target_total"]) / row["target_total"])
    volume_mape = (sum(abs_pct_errors) / len(abs_pct_errors)
                   if abs_pct_errors else float("nan"))

    # Acuity macro-F1 against the dominant ESI per row.
    tp = defaultdict(int); fp = defaultdict(int); fn = defaultdict(int)
    for row in validation:
        if row["target_total"] == 0:
            continue
        actual_esi = max(ESI_LEVELS,
                         key=lambda e: row[f"target_esi_{e}"])
        shares = acuity_model.predict_shares(row)
        pred_esi   = max(shares, key=shares.get)
        for esi in ESI_LEVELS:
            if pred_esi == esi and actual_esi == esi: tp[esi] += 1
            elif pred_esi == esi and actual_esi != esi: fp[esi] += 1
            elif pred_esi != esi and actual_esi == esi: fn[esi] += 1
    f1_per_class = []
    for esi in ESI_LEVELS:
        prec = tp[esi] / (tp[esi] + fp[esi]) if (tp[esi] + fp[esi]) > 0 else 0
        rec  = tp[esi] / (tp[esi] + fn[esi]) if (tp[esi] + fn[esi]) > 0 else 0
        f1   = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0
        f1_per_class.append(f1)
    acuity_macro_f1 = sum(f1_per_class) / len(f1_per_class)

    # 3e. Quality gate. Production rejects models that regress
    # on either metric beyond a configured tolerance against the
    # current production model. The demo always promotes.
    logger.info(
        "Validation: volume MAPE=%.4f, acuity macro F1=%.4f",
        volume_mape, acuity_macro_f1)

    return {
        "volume_model":         volume_model,
        "acuity_model":         acuity_model,
        "volume_mape":          volume_mape,
        "acuity_macro_f1":      acuity_macro_f1,
        "volume_model_version": VOLUME_MODEL_VERSION,
        "acuity_model_version": ACUITY_MODEL_VERSION,
        "validation_size":      len(validation),
    }
```

---

## Step 4: Generate Hourly Forecasts

The inference pipeline runs every hour. It builds future feature rows for the configured horizons, calls the volume model and acuity classifier, composes the per-acuity counts, and computes prediction intervals from the residual standard deviation. In production this runs as a Step Functions Map state that calls the SageMaker endpoint once per horizon.

```python
def _build_future_feature_row(ed_id, future_hour, weather_by_date,
                              flu_index_by_date, event_dates,
                              recent_history):
    """Construct a feature row for a future hour at inference time.

    `recent_history` is a list of recent (hour_iso, total) pairs
    used to compute lags. At inference time the lag at horizon
    h > 1 must come from either an actual past value (if h is
    short enough that the past hour is known) or the model's
    own previous prediction (recursive forecasting). The demo
    uses recursive forecasting because it is simpler to read.
    """
    day_iso = future_hour.date().isoformat()

    # Calendar features.
    is_holiday = day_iso in US_FEDERAL_HOLIDAYS
    nearest_d  = None
    for offset in range(-7, 8):
        probe = (future_hour.date() + timedelta(days=offset)).isoformat()
        if probe in US_FEDERAL_HOLIDAYS:
            if nearest_d is None or abs(offset) < abs(nearest_d):
                nearest_d = offset
    holiday_distance_days = nearest_d if nearest_d is not None else 0

    # Weather: production uses a forecast feed for future hours.
    # The demo reuses the most-recent observed weather as a
    # weatherman-of-last-resort fallback.
    weather = weather_by_date.get(day_iso)
    if not weather:
        # Find the latest available date in weather_by_date.
        if weather_by_date:
            latest_iso = max(weather_by_date)
            weather    = weather_by_date[latest_iso]
        else:
            weather = {"temperature_f": 65.0, "precipitation_in": 0.0,
                       "wind_speed_mph": 5.0, "is_severe": False}

    flu_index = flu_index_by_date.get(day_iso)
    if flu_index is None:
        flu_index = (flu_index_by_date.get(max(flu_index_by_date))
                     if flu_index_by_date else 12.0)

    has_local_event = day_iso in event_dates

    # Lag features. For h=1 we always have the actual hour's
    # value; for longer horizons we use whatever the recursive
    # forecasting loop has set in the recent_history dict.
    history_map = dict(recent_history)
    lag_1h_iso   = (future_hour - timedelta(hours=1)).isoformat()
    lag_24h_iso  = (future_hour - timedelta(hours=24)).isoformat()
    lag_168h_iso = (future_hour - timedelta(hours=168)).isoformat()
    lag_1h   = history_map.get(lag_1h_iso, 0.0)
    lag_24h  = history_map.get(lag_24h_iso, 0.0)
    lag_168h = history_map.get(lag_168h_iso, 0.0)

    return {
        "ed_id":               ed_id,
        "local_hour":          future_hour.isoformat(),
        "hour_of_day":         future_hour.hour,
        "day_of_week":         future_hour.weekday(),
        "month":               future_hour.month,
        "is_weekend":          future_hour.weekday() in (5, 6),
        "is_holiday":          is_holiday,
        "holiday_distance_d":  holiday_distance_days,
        "temperature_f":       weather["temperature_f"],
        "precipitation_in":    weather["precipitation_in"],
        "wind_speed_mph":      weather["wind_speed_mph"],
        "is_severe_weather":   weather["is_severe"],
        "flu_index":           flu_index,
        "has_local_event":     has_local_event,
        "lag_1h":              lag_1h,
        "lag_24h":             lag_24h,
        "lag_168h":            lag_168h,
    }


def generate_hourly_forecasts(ed_id, trained_models, feature_table,
                              weather_by_date, flu_index_by_date,
                              event_calendar, current_hour=None):
    """Step 4: Produce per-horizon forecasts with prediction intervals.

    See pseudocode Step 4 in the main recipe. Returns a list of
    forecast records ready for the Step 5 DynamoDB writer.
    """
    if not feature_table:
        return []

    volume_model = trained_models["volume_model"]
    acuity_model = trained_models["acuity_model"]
    sigma        = max(volume_model.sigma, 0.5)

    # Default "current hour" is the latest hour in the feature
    # table. Production reads it from the EventBridge schedule.
    rows_sorted = sorted(feature_table, key=lambda r: r["local_hour"])
    if current_hour is None:
        current_hour = datetime.fromisoformat(rows_sorted[-1]["local_hour"])

    # Build the recent-history map for lag lookups.
    recent_history = [(r["local_hour"], r["target_total"])
                      for r in rows_sorted[-200:]]   # ~8 days of context

    # Index event dates for the future-row builder.
    event_dates = set()
    for ev in event_calendar:
        d_start = date.fromisoformat(ev["start_date"])
        d_end   = date.fromisoformat(ev["end_date"])
        cur     = d_start
        while cur <= d_end:
            event_dates.add(cur.isoformat())
            cur += timedelta(days=1)

    # 4a. Forecast hour-by-hour out to the longest horizon. We
    # need to predict each hour because longer-horizon lags
    # depend on the model's own predictions for nearer hours.
    max_horizon = max(FORECAST_HORIZONS_HOURS)
    predicted_by_hour = {}
    for h in range(1, max_horizon + 1):
        future_hour = current_hour + timedelta(hours=h)
        future_row  = _build_future_feature_row(
            ed_id, future_hour, weather_by_date, flu_index_by_date,
            event_dates, recent_history)
        volume_pred = volume_model.predict(future_row)
        # Append to recent_history so the next iteration's
        # lag_1h, lag_24h, etc. can find this prediction.
        recent_history.append((future_row["local_hour"], volume_pred))
        # Acuity shares.
        shares = acuity_model.predict_shares(future_row)
        predicted_by_hour[future_hour] = {
            "volume_pred": volume_pred,
            "shares":      shares,
            "future_row":  future_row,
        }

    # 4b. Compose the per-horizon forecast records.
    forecast_records = []
    generated_at = datetime.now(timezone.utc).isoformat()
    for h in FORECAST_HORIZONS_HOURS:
        future_hour = current_hour + timedelta(hours=h)
        info        = predicted_by_hour[future_hour]
        volume_pred = info["volume_pred"]
        shares      = info["shares"]

        # Prediction intervals widen with horizon. The demo uses
        # a simple linear scaling; production uses the model's
        # actual forward-step covariance or a quantile-regression
        # approach.
        horizon_sigma = sigma * math.sqrt(max(1.0, h / 4.0))
        z_80 = float(PREDICTION_INTERVAL_LEVELS["80"])
        z_95 = float(PREDICTION_INTERVAL_LEVELS["95"])
        lower_80 = max(0, int(round(volume_pred - z_80 * horizon_sigma)))
        upper_80 = max(0, int(round(volume_pred + z_80 * horizon_sigma)))
        lower_95 = max(0, int(round(volume_pred - z_95 * horizon_sigma)))
        upper_95 = max(0, int(round(volume_pred + z_95 * horizon_sigma)))

        # Per-acuity counts: multiply volume by the ESI share.
        per_acuity_counts = {}
        for esi in ESI_LEVELS:
            per_acuity_counts[f"esi_{esi}"] = int(round(volume_pred * shares[esi]))

        forecast_records.append({
            "ed_id":              ed_id,
            "forecast_for_hour":  future_hour.isoformat(),
            "forecast_horizon_h": h,
            "volume_point":       int(round(volume_pred)),
            "volume_lower_80":    lower_80,
            "volume_upper_80":    upper_80,
            "volume_lower_95":    lower_95,
            "volume_upper_95":    upper_95,
            "esi_breakdown":      per_acuity_counts,
            "generated_at":       generated_at,
            "volume_model_version": trained_models["volume_model_version"],
            "acuity_model_version": trained_models["acuity_model_version"],
            "pipeline_version":     PIPELINE_VERSION,
        })

    logger.info(
        "Generated %d forecast records for ED %s at horizons %s",
        len(forecast_records), ed_id, FORECAST_HORIZONS_HOURS)
    return forecast_records
```

---

## Step 5: Load Forecasts to DynamoDB

The forecast records get written to DynamoDB keyed by `ed_id` with a sort key combining `forecast_for_hour` and `generated_at` so a query for a single forecast hour returns all generated revisions in order. The write is idempotent: this hour's forecast for `(ed A, future hour H)` overwrites the previous forecast for the same key. An older forecast can still be retrieved by querying the sort-key range, which is useful for after-action reviews.

```python
def load_forecasts_to_dynamodb(records, table, event_bus, cloudwatch):
    """Step 5: Idempotently load forecast records to DynamoDB.

    See pseudocode Step 5 in the main recipe. Returns the count
    of records written. Production wraps this in a Lambda with
    DLQ, structured logs, and exponential backoff on
    UnprocessedItems; the demo writes directly through the mock.
    """
    if not records:
        return 0

    # Convert all numeric values to Decimal before any DynamoDB
    # boundary call. DynamoDB rejects Python float and pandas /
    # numpy types. The helper handles the common cases.
    written = 0
    chunk   = 25
    for i in range(0, len(records), chunk):
        batch = records[i:i + chunk]
        with table.batch_writer() as bw:
            for record in batch:
                # Compose the sort key from the forecast-for-hour
                # plus the generated_at timestamp. This shape lets
                # the dashboard ask "what is the latest forecast for
                # 18:00?" with a Query for the prefix and a Limit=1
                # in descending order, while preserving older
                # forecasts for after-action review.
                sk = f"{record['forecast_for_hour']}#{record['generated_at']}"

                item = {
                    "ed_id":                            record["ed_id"],
                    "forecast_for_hour_generated_at":   sk,
                    "forecast_for_hour":                record["forecast_for_hour"],
                    "generated_at":                     record["generated_at"],
                    "forecast_horizon_h":               _to_decimal(record["forecast_horizon_h"]),
                    "volume_point":                     _to_decimal(record["volume_point"]),
                    "volume_lower_80":                  _to_decimal(record["volume_lower_80"]),
                    "volume_upper_80":                  _to_decimal(record["volume_upper_80"]),
                    "volume_lower_95":                  _to_decimal(record["volume_lower_95"]),
                    "volume_upper_95":                  _to_decimal(record["volume_upper_95"]),
                    "esi_breakdown":                    {k: _to_decimal(v) for k, v in record["esi_breakdown"].items()},
                    "volume_model_version":             record["volume_model_version"],
                    "acuity_model_version":             record["acuity_model_version"],
                    "pipeline_version":                 record["pipeline_version"],
                }
                bw.put_item(Item=item)
                written += 1

    # Upsert a CURRENT pointer per (ed_id, forecast_for_hour)
    # so the dashboard can do a single GetItem instead of querying
    # and sorting client-side.
    for record in records:
        sk = f"CURRENT#{record['forecast_for_hour']}"
        item = {
            "ed_id":                          record["ed_id"],
            "forecast_for_hour_generated_at": sk,
            "forecast_for_hour":              record["forecast_for_hour"],
            "generated_at":                   record["generated_at"],
            "forecast_horizon_h":             _to_decimal(record["forecast_horizon_h"]),
            "volume_point":                   _to_decimal(record["volume_point"]),
            "volume_lower_80":                _to_decimal(record["volume_lower_80"]),
            "volume_upper_80":                _to_decimal(record["volume_upper_80"]),
            "volume_lower_95":                _to_decimal(record["volume_lower_95"]),
            "volume_upper_95":                _to_decimal(record["volume_upper_95"]),
            "esi_breakdown":                  {k: _to_decimal(v) for k, v in record["esi_breakdown"].items()},
            "volume_model_version":           record["volume_model_version"],
            "acuity_model_version":           record["acuity_model_version"],
            "pipeline_version":               record["pipeline_version"],
        }
        table.put_item(Item=item)

    # Emit an EventBridge event so downstream consumers (the
    # charge-nurse dashboard, the staffing scheduler, the
    # surge-plan trigger) know a new forecast batch is available.
    # The event payload deliberately carries no PHI: just the run
    # identifier, the ED, the horizon list, and the timestamp.
    event_bus.put_events(Entries=[{
        "Source":       "ed.forecast",
        "DetailType":   "ForecastBatchCompleted",
        "EventBusName": FORECAST_EVENT_BUS_NAME,
        "Time":         datetime.now(timezone.utc),
        "Detail":       json.dumps({
            "ed_id":              records[0]["ed_id"],
            "horizons":           sorted({r["forecast_horizon_h"] for r in records}),
            "generated_at":       records[0]["generated_at"],
            "record_count":       len(records),
            "pipeline_version":   PIPELINE_VERSION,
        }),
    }])

    # Emit operational metrics. Production also emits per-horizon
    # forecast residuals against actuals from the previous run,
    # which is the foundation for drift detection.
    cloudwatch.put_metric_data(
        Namespace=CLOUDWATCH_NAMESPACE,
        MetricData=[
            {"MetricName": "RecordsWritten",
             "Value":      float(written),
             "Unit":       "Count"},
            {"MetricName": "ForecastBatchSize",
             "Value":      float(len(records)),
             "Unit":       "Count"},
        ])

    logger.info("Loaded %d forecast records into %s", written, table.name)
    return written
```

---

## Full Pipeline

Stitching the steps together. Production runs each step as a separate Step Functions task with retries, error handling, and CloudWatch alarms; the demo runs them sequentially in one process so you can see the data flow.

```python
def run_ed_forecast_pipeline(table, event_bus, cloudwatch):
    """End-to-end pipeline orchestration.

    The demo wires up synthetic data; production starts with a
    Kinesis read of the most recent ADT records and an S3 read
    of the historical hourly counts for the target ED.
    """
    run_id = str(uuid.uuid4())
    print(f"\n=== ED Arrival Forecast Pipeline run_id={run_id} ===\n")

    # --- Generate synthetic input data (production reads from Kinesis + S3) ---
    adt_records, weather_by_date, flu_index_by_date = generate_synthetic_adt_records()
    event_calendar                                  = generate_synthetic_event_calendar()
    print(f"[input] {len(adt_records)} synthetic ADT records, "
          f"{len(weather_by_date)} weather days, "
          f"{len(flu_index_by_date)} flu-index days, "
          f"{len(event_calendar)} calendar events")

    # --- Step 1: Aggregate to hourly counts ---
    print("\n[step 1] aggregate_arrivals_to_hourly")
    hourly_rows = aggregate_arrivals_to_hourly(adt_records)
    print(f"  -> {len(hourly_rows)} hourly rows")

    # --- Step 2: Build feature table ---
    print("\n[step 2] build_feature_table")
    feature_table = build_feature_table(
        hourly_rows, weather_by_date, flu_index_by_date, event_calendar)
    print(f"  -> {len(feature_table)} feature rows")
    if feature_table:
        sample = feature_table[-1]
        print(f"  sample feature row keys: {sorted(sample.keys())}")

    # --- Step 3: Train both models ---
    print("\n[step 3] train_volume_and_acuity_models")
    trained = train_volume_and_acuity_models(feature_table)
    print(f"  -> volume MAPE = {trained['volume_mape']:.4f}")
    print(f"  -> acuity macro F1 = {trained['acuity_macro_f1']:.4f}")
    print(f"  -> validation_size = {trained['validation_size']}")

    # --- Step 4: Generate hourly forecasts ---
    print("\n[step 4] generate_hourly_forecasts")
    records = generate_hourly_forecasts(
        SYNTHETIC_ED_ID, trained, feature_table,
        weather_by_date, flu_index_by_date, event_calendar)
    for r in records:
        print(f"  horizon={r['forecast_horizon_h']:>2}h "
              f"point={r['volume_point']:>3} "
              f"80%=({r['volume_lower_80']:>3}..{r['volume_upper_80']:>3}) "
              f"95%=({r['volume_lower_95']:>3}..{r['volume_upper_95']:>3}) "
              f"esi={r['esi_breakdown']}")

    # --- Step 5: Load to DynamoDB ---
    print("\n[step 5] load_forecasts_to_dynamodb")
    written = load_forecasts_to_dynamodb(records, table, event_bus, cloudwatch)
    print(f"  -> wrote {written} records "
          f"(plus {len(records)} CURRENT pointers)")
    print(f"  -> emitted {len(event_bus.events)} EventBridge events")
    print(f"  -> emitted CloudWatch metrics: "
          f"{sorted(cloudwatch.metrics.keys())}")

    return records


def run_demo():
    """Run the pipeline end-to-end against the in-memory mocks.

    No AWS resources are touched; every external dependency is
    a mock. Useful for sanity-checking the forecasting logic and
    the prediction-interval math before wiring to real services.
    """
    table      = MockTable(ED_FORECASTS_TABLE)
    event_bus  = MockEventBus(FORECAST_EVENT_BUS_NAME)
    cloudwatch = MockCloudWatch()

    records = run_ed_forecast_pipeline(table, event_bus, cloudwatch)

    print("\n=== Sample CURRENT record ===")
    sample_pk = records[0]["ed_id"]
    sample_sk = f"CURRENT#{records[0]['forecast_for_hour']}"
    sample    = table.items[(sample_pk, sample_sk)]
    def _decimalify(o):
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return o
    print(json.dumps(sample, default=_decimalify, indent=2))

    return records


if __name__ == "__main__":
    run_demo()
```

---

## Sample Output

Running the demo against the in-memory mocks produces output like this. Numbers vary because of the synthetic-data noise but the segmentation, the model selection, and the prediction-interval logic are deterministic given the seed.

```text
=== ED Arrival Forecast Pipeline run_id=4f2d... ===

[input] 87341 synthetic ADT records, 731 weather days, 731 flu-index days, 2 calendar events

[step 1] aggregate_arrivals_to_hourly
  -> 17520 hourly rows

[step 2] build_feature_table
  -> 17520 feature rows
  sample feature row keys: ['day_of_week', 'ed_id', 'flu_index', ...]

[step 3] train_volume_and_acuity_models
  -> volume MAPE = 0.1842
  -> acuity macro F1 = 0.4031
  -> validation_size = 2160

[step 4] generate_hourly_forecasts
  horizon= 4h point= 17 80%=( 12.. 22) 95%=(  9.. 25) esi={'esi_1': 0, 'esi_2': 3, 'esi_3': 8, 'esi_4': 4, 'esi_5': 2}
  horizon=12h point= 12 80%=(  6.. 18) 95%=(  3.. 21) esi={'esi_1': 0, 'esi_2': 2, 'esi_3': 6, 'esi_4': 3, 'esi_5': 1}
  horizon=24h point= 18 80%=( 10.. 26) 95%=(  5.. 31) esi={'esi_1': 0, 'esi_2': 3, 'esi_3': 9, 'esi_4': 4, 'esi_5': 2}

[step 5] load_forecasts_to_dynamodb
  -> wrote 3 records (plus 3 CURRENT pointers)
  -> emitted 1 EventBridge events
  -> emitted CloudWatch metrics: ['EDArrivalForecast/ForecastBatchSize', 'EDArrivalForecast/RecordsWritten']
```

A real pipeline against a single ED's two-year ADT history runs the hourly inference cycle in 30 to 90 seconds on a small SageMaker endpoint, produces the same shape of output, and writes the records straight to a real DynamoDB table that the charge-nurse dashboard queries every minute.

---

## Gap to Production

The demo is intentionally a sketch. Here is the distance between this code and something you would deploy.

**Real model libraries, not demo helpers.** The `PoissonGLM` and `MultinomialAcuityClassifier` in this file are pedagogical stand-ins. Production replaces `PoissonGLM` with [statsmodels' GLM](https://www.statsmodels.org/stable/glm.html) using the Poisson family for the simple case, with a [negative binomial GLM](https://www.statsmodels.org/stable/generated/statsmodels.discrete.discrete_model.NegativeBinomial.html) when the count data is overdispersed (the variance exceeds the mean), with [Prophet](https://facebook.github.io/prophet/) when you want auto-handled multi-seasonality plus external regressors, or with the SageMaker [DeepAR built-in algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html) for joint training across many EDs in a health system. Production replaces `MultinomialAcuityClassifier` with scikit-learn's `LogisticRegression(multi_class='multinomial')`, a gradient-boosted classifier (`xgboost`, `lightgbm`), or a small neural classifier when the relationships are non-linear. The demo's models are good enough to demonstrate the feature engineering and the prediction-interval logic; they are not good enough to drive real charge-nurse decisions.

**Real Kinesis stream and Glue Streaming, not in-memory lists.** The `aggregate_arrivals_to_hourly` function loops over a Python list of synthetic ADT records. Production runs an AWS Glue Streaming job that consumes from Kinesis with a five-minute watermark for late-arriving registrations, joins against the SKU-equivalent ED registry table, applies the placeholder ESI mapping, and writes hourly Parquet partitions to S3. The Glue job uses the Glue service role with scoped Kinesis, S3, and KMS permissions. For systems that prefer FHIR over raw HL7, Amazon HealthLake replaces the Kinesis path; the downstream feature pipeline reads `Encounter` resources instead of ADT records.

**Real SageMaker training and inference, not pure-Python fits.** The `train_volume_and_acuity_models` function fits everything in-process. Production uses two SageMaker training jobs running in parallel via the Step Functions Map state. Each job pulls its slice of the modeling-ready dataset from S3, fits the model, captures error metrics on the held-out 90-day window, and writes a versioned model artifact to the model-artifact S3 prefix. The training image is a custom container built on the SageMaker scikit-learn base with statsmodels and Prophet installed, or the SageMaker DeepAR built-in algorithm for the multi-series neural option. Inference is served by a SageMaker real-time endpoint with at least two instances in different Availability Zones, the model package promoted via SageMaker Model Registry with manual approval, and a shadow-deployment step that runs the new model in parallel for 24 hours before cutting traffic over.

**Real DynamoDB, not MockTable.** Replace `MockTable` with `boto3.resource('dynamodb').Table(ED_FORECASTS_TABLE)`. The table needs a partition key (`ed_id`, type S), a sort key (`forecast_for_hour_generated_at`, type S), encryption-at-rest with a customer-managed KMS key, point-in-time recovery enabled, on-demand billing for the unpredictable load that comes with a multi-ED rollout (or provisioned with auto-scaling for predictable single-ED load), a global secondary index on `(ed_id, generated_at)` if dashboards filter by run instead of by future hour, and an item-level TTL on the historical (non-CURRENT) records so the table does not grow unbounded. Also handle the `BatchWriteItem` `UnprocessedItems` response with exponential backoff; `MockTable` ignores this case but DynamoDB returns unprocessed items under throttling. The DynamoDB Streams feature is useful here too: a Lambda subscribed to the stream can refresh the charge-nurse dashboard with sub-second latency without polling.

**Real Step Functions orchestration.** The pipeline-orchestration logic (aggregate -> features -> infer -> load for hourly inference; train -> evaluate -> deploy for weekly retraining) runs as two AWS Step Functions state machines in production. Each step is a Lambda or a SageMaker job, with `Retry` and `Catch` blocks for transient failures, a `Map` state for parallel per-ED inference (when multiple EDs share the pipeline), and `EventBridge` schedules that fire hourly for inference and weekly for retraining. The state machine emits `ExecutionFailed` events to a CloudWatch alarm so on-call gets paged when a run fails.

**Real EventBridge bus and CloudWatch alarms.** The `MockEventBus` and `MockCloudWatch` accumulate events and metrics. Production uses real `boto3.client('events').put_events(...)` and `boto3.client('cloudwatch').put_metric_data(...)`, plus CloudWatch alarms on per-horizon forecast error (alarm if MAPE exceeds tolerance for two consecutive cycles), pipeline-execution latency, DynamoDB write throttling, SageMaker endpoint 5xx rate, and Kinesis iterator-age (a leading indicator that the consumer is falling behind). The alarms feed an SNS topic that pages the on-call ML engineer and the on-call ED operations leader.

**Late-record reconciliation.** ADT messages do not always arrive in order. A registration that happened at 14:32 might land in the stream at 14:45 because of EHR queue delays. The demo assumes in-order arrival. Production aggregates with an explicit watermark (typically five minutes) and a late-record reconciliation pass that updates the most recent hour's count when stragglers arrive. Without this, the most recent hour's count is always slightly wrong, and the model sees biased recent history.

**Triage-time ESI reconciliation.** ESI level is assigned at triage, which can be minutes to hours after the registration timestamp. The demo assumes ESI is known at registration. Production captures the registration with `esi_unknown` and updates to the assigned ESI level when the triage record arrives, typically within the same hourly bucket but sometimes spanning bucket boundaries. The reconciliation pass runs as a separate Glue job on a faster cadence than the main aggregation.

**Diversion window handling.** When the ED goes on diversion (ambulances are routed elsewhere because the ED is overwhelmed), arrivals drop artificially. A model trained on diversion-affected history under-predicts true demand. The demo has no concept of diversion. Production maintains a diversion log (often manually entered, sometimes inferred from EMS data) and the training pipeline either excludes diversion windows or models them with an explicit indicator.

**Per-horizon and per-ED forecast monitoring.** The pipeline writes the forecast records but does not compare last hour's forecast against this hour's actuals to detect drift. Production maintains a separate monitoring job that, on each new run, joins the prior run's forecasts against newly-aggregated arrivals to compute realized error, alarms on per-horizon sustained drift, and triggers retraining outside the normal cadence. Without this monitoring, the first sign of model degradation is a charge nurse complaining the dashboard is wrong.

**Charge-nurse override and feedback.** Forecasts are advisory, not directive. Charge nurses make staffing decisions based on the forecast plus their own context. A production system captures the actual staffing decision and the rationale when it diverges from the forecast so the model can be evaluated against operational outcomes (door-to-doctor time, LWBS rate), not just forecast error. This feedback loop is also the foundation for the optimization layers in Recipe 14.2.

**Surge plan trigger logic.** The forecast says "expected 22 arrivals in the next 4 hours, 95% interval upper bound 28." The surge plan trigger says "call in additional staff if expected arrivals exceed our staffed capacity." Connecting these is not trivial: capacity is itself a function of current census, boarding load, and staff levels. The trigger logic is a small but real piece of operations engineering on top of the forecast and lives in a separate Lambda that consumes the forecast event from EventBridge.

**Coupling to inpatient census.** ED throughput depends on inpatient capacity. When the hospital cannot admit boarders, the ED fills regardless of arrival rate. A forecast that ignores this misses the dominant operational constraint on busy days. The full picture is a coupled forecast that connects to Recipe 12.5 (Hospital Census Forecasting). For a basic implementation, surface the inpatient occupancy alongside the arrival forecast on the dashboard so the charge nurse sees both.

**Multi-ED hierarchical forecasting.** For health systems running multiple EDs, hierarchical forecasting (forecast at each ED and reconcile to system totals, or forecast at the system and disaggregate) produces more stable forecasts at every level and supports system-level decisions like ED-to-ED diversion routing. The demo runs a single ED. Multi-ED extensions either run the same pipeline per-ED inside a Step Functions Map state or replace the per-ED models with a SageMaker DeepAR model trained jointly across the series.

**HIPAA controls end-to-end.** The Kinesis stream uses server-side encryption with a customer-managed KMS key; the S3 prefixes use SSE-KMS with the same key family; the DynamoDB table uses encryption-at-rest with a customer-managed key; SageMaker training and inference jobs run in a VPC with VPC endpoints to S3, Kinesis, CloudWatch Logs, and KMS; the Glue job reads and writes only encrypted data; CloudTrail logs all S3, DynamoDB, Glue, Kinesis, and SageMaker API calls; CloudWatch log groups are KMS-encrypted; IAM roles are scoped to specific resource ARNs; an AWS BAA is in place. The demo touches none of this; production cannot ship without all of it.

**Idempotency and audit trail.** Each pipeline run is identified by a `run_id`, all forecast records carry that run_id and the model versions, the DynamoDB writes overwrite cleanly by the `(ed_id, forecast_for_hour_generated_at)` key, and the model-artifact S3 writes use deterministic prefixes so a rerun produces the same output. An immutable audit log captures which model version produced which forecast on which night, written through Kinesis Data Firehose into an Object-Lock S3 bucket sized to the institutional retention floor (typically seven years for clinical operational records).

**Testing.** Unit tests cover the aggregation function (records on a bucket boundary land in the correct hour, late records land in the correct hour after watermark), the feature builder (lag features compute correctly, holiday distance is symmetric around the holiday), the volume model fit (a constant-rate input produces a near-constant prediction, the fit converges on the synthetic data), the prediction interval generator (the upper bound respects the configured z-score), and the DynamoDB write idempotency (writing the same record twice is a no-op). Integration tests run the pipeline against a known-input synthetic dataset and assert the output forecasts and prediction intervals against expected values. End-to-end tests stand up real S3, DynamoDB, Kinesis, and EventBridge resources in a sandbox account and run the full Step Functions state machine.

**Structured logging.** Replace the demo's `print` calls with `logger.info(..., extra={...})` calls that emit JSON-formatted structured logs to CloudWatch Logs. Log structural metadata only (run_id, ed_id, hour_local, mean_error, runtime_ms), never raw ADT records, never per-patient timestamps tied to identifiable visits.

**The shape of the gap.** The forecasting math in this file is a sketch but it is fundamentally correct. The plumbing around it (storage, orchestration, security, late-record handling, monitoring, dashboard integration, surge-plan logic) is what takes the bulk of the engineering work. Plan for the plumbing to be 80% of the project; the modeling itself routinely surprises teams by being the easier part.

---

## Related Resources

- [Recipe 12.3: ED Arrival Forecasting](chapter12.03-ed-arrival-forecasting): The main recipe with the full architectural walkthrough this Python companion implements.
- [Amazon SageMaker DeepAR Forecasting Algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html): Built-in SageMaker algorithm for multi-series neural forecasting at scale, the practical default for multi-ED rollouts.
- [statsmodels Documentation](https://www.statsmodels.org/stable/): Python implementation of GLM (Poisson and negative binomial), ETS, and ARIMA used as the volume-model baseline.
- [Prophet Documentation (Meta Open Source)](https://facebook.github.io/prophet/): Reference for the Prophet forecasting library that handles multiple seasonalities and external regressors gracefully.
- [Forecasting: Principles and Practice (Hyndman & Athanasopoulos)](https://otexts.com/fpp3/): Free online textbook covering classical forecasting methods including TBATS for the multi-seasonality cases.
- [AWS Step Functions Map State](https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-map-state.html): Pattern for fanning out per-ED inference and per-segment training jobs in parallel.
- [Amazon HealthLake Documentation](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html): For systems ingesting full FHIR rather than raw HL7 ADT.
- [MIMIC-IV-ED on PhysioNet](https://physionet.org/content/mimic-iv-ed/): De-identified ED visit data suitable for prototyping ED forecasting models with credentialed access.

---

*← [Recipe 12.3: ED Arrival Forecasting](chapter12.03-ed-arrival-forecasting) · [Chapter 12 Index](chapter12-index) · [Next: Recipe 12.4 - Lab Result Trend Analysis →](chapter12.04-lab-result-trend-analysis)*
