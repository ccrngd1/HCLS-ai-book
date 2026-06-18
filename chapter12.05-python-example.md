# Recipe 12.5: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 12.5. It shows one way you could translate the hospital census forecasting pipeline into working Python using boto3 against Amazon HealthLake (here represented by an in-memory `MockHealthLake` that stores FHIR Encounter resources keyed by patient and admission), Amazon S3 (here represented by a `MockS3` dict), AWS Glue (here represented by an in-process Python feature-engineering step), Amazon SageMaker (here represented by pure-Python `PoissonInflowModel`, `ExponentialSurvivalModel`, and `MultinomialUnitAssigner` classes that stand in for real statsmodels Poisson regression, real lifelines or XGBSE survival models, and a real scikit-learn or SageMaker XGBoost classifier), AWS Lambda (here represented by a plain Python function that runs the Monte Carlo composition step), AWS Step Functions (here represented by sequential function calls), Amazon DynamoDB (mocked with `MockTable`), Amazon EventBridge (mocked with `MockEventBus`), and Amazon CloudWatch (mocked with `MockCloudWatch`). The demo generates a synthetic 412-bed community hospital with five units (ED holding, telemetry, med-surg, ortho post-op, and step-down ICU), a roster of currently admitted patients with realistic length-of-stay distributions, an OR schedule with a few elective cardiac and ortho cases, an ED tracking board with pending admit holds, and a transfer-center queue with a couple of inbound transfers, so you can see the snapshot, the inflow forecast, the per-patient discharge survival model, the Monte Carlo composition, and the prediction-interval logic work end-to-end without provisioning anything. It is not production-ready. There is no real HealthLake datastore, no real Glue ETL, no real SageMaker endpoint, no real Step Functions state machine, no real DynamoDB table, no real EventBridge bus, no real CloudWatch alarms, no per-Lambda IAM least privilege, no KMS customer-managed keys, no VPC endpoints, no ADT timestamp reconciliation, no discharge-order timing model, no real bed-management overflow rules, no service-line drift detection, no multi-hospital shared models, no operational feedback loop, no Bedrock narrative summary, no CDS Hooks integration, and no SaMD framing. Think of it as the sketchpad version: useful for understanding the shape of a hospital census pipeline that respects the flow-not-volume discipline, the three-layer (inflow, outflow, composition) discipline, the per-patient-survival discipline, the Monte-Carlo-prediction-interval discipline, and the unit-by-unit-not-just-aggregate discipline this recipe demands. It is not something you would point at a real bed huddle on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the five pseudocode steps from the main recipe: snapshot every active inpatient encounter at the current time and build the per-patient feature record (Step 1); forecast inflows by source, service, and admit unit using a per-source Poisson model for ED and direct admits, a deterministic OR-schedule pass for surgical admits, and a queue-plus-Poisson hybrid for transfers in (Step 2); predict per-patient discharge probabilities over the forecast horizon using a survival model fed by the per-patient features (Step 3); compose unit-level census trajectories by Monte Carlo sampling of the inflow and outflow draws starting from the snapshot, applying the bed-management overflow rules at each hour (Step 4); deliver the per-unit per-hour expected occupancy and prediction intervals to DynamoDB, log the sample trajectories to S3 for after-the-fact analysis, emit pipeline-lifecycle events to EventBridge, and write the forecast-accuracy and predicted-gridlock metrics to CloudWatch (Step 5). The synthetic hospital, the synthetic units, the synthetic patients, the synthetic OR schedule, the synthetic transfer queue, and the synthetic ED holds in the demo are fictional; nothing in this file should be interpreted as real hospital operations data from any real institution.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

The demo runs against the Python standard library plus boto3; no other packages are imported. Production deployments swap the demo's pure-Python `PoissonInflowModel`, `ExponentialSurvivalModel`, and `MultinomialUnitAssigner` for real model libraries ([statsmodels GLM with the Poisson family](https://www.statsmodels.org/stable/glm.html) for the per-source inflow regressors, [lifelines](https://lifelines.readthedocs.io/) or [XGBSE](https://github.com/loft-br/xgboost-survival-embeddings) or [PySurvival](https://square.github.io/pysurvival/) for the discharge-time survival model, [scikit-learn `LogisticRegression(multi_class='multinomial')`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html) or the [SageMaker built-in XGBoost algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/xgboost.html) for the unit-assignment classifier, and the [SageMaker DeepAR built-in algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html) or the [Chronos foundation model](https://github.com/amazon-science/chronos-forecasting) when you want a learned multi-series neural model layered on top of the per-source baselines for multi-hospital health systems); the Gap to Production section spells out the substitutions.

In production you would also configure an Amazon HealthLake datastore for the FHIR Encounter resources (or an Amazon S3 prefix populated by an HL7 ADT ingestion pipeline if you do not need the full FHIR API), an Amazon S3 bucket for the raw ADT landing zone, the OR schedule prefix, the transfer-center queue prefix, the ED tracking-board prefix, the harmonized state-snapshot prefix, the inflow-forecast prefix, the outflow-forecast prefix, the Monte Carlo sample-trajectory prefix, and the model-artifact prefix (one prefix per concern, all SSE-KMS encrypted with a customer-managed key), an AWS Glue job that reads new HealthLake encounters on a 15-to-60-minute cadence, applies the timestamp reconciliation and unit normalization, and writes the per-patient feature records, an Amazon SageMaker inference endpoint per model family (one for the inflow Poisson regressors behind a multi-model endpoint, one for the survival model, one for the unit-assignment classifier) hosted in a private VPC subnet, an AWS Lambda function that runs the Monte Carlo composition (or AWS Batch for larger hospitals where Lambda's compute ceiling matters), an AWS Step Functions state machine that orchestrates the inference cycle (snapshot -> inflow -> outflow -> compose -> deliver) with retries and `Catch` blocks for transient failures, an Amazon DynamoDB table for the per-unit per-hour forecasts keyed by `unit_id` with a sort key of `forecast_for_ts`, an Amazon EventBridge schedule that triggers the Step Functions state machine every 15 to 60 minutes for inference (and weekly + monthly schedules for the inflow and outflow retraining runs), Amazon CloudWatch dashboards and alarms for pipeline failures, forecast accuracy by horizon, feature distribution drift, and operational consumption metrics, and a thin integration layer that exposes the forecasts to the bed huddle dashboard, the transfer center decision support, the OR scheduler, and the ED diversion-decision tool. The demo replaces all of these with a single in-process Python file so the focus stays on the snapshot logic, the per-source inflow forecasting, the per-patient discharge survival model, the Monte Carlo composition with overflow handling, and the per-unit prediction-interval delivery rather than on the platform plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `healthlake:SearchWithGet`, `healthlake:ReadResource`, and `healthlake:DescribeFHIRDatastore` on the inpatient FHIR datastore, scoped to the specific datastore ARN
- `s3:GetObject` and `s3:PutObject` on the raw-ADT prefix, the OR-schedule prefix, the transfer-queue prefix, the ED-board prefix, the snapshot prefix, the inflow-forecast prefix, the outflow-forecast prefix, the sample-trajectory prefix, and the model-artifact prefix
- `glue:StartJobRun` and `glue:GetJobRun` on the snapshot and feature-engineering Glue jobs, plus the Glue service role's permissions for the ETL jobs
- `sagemaker:InvokeEndpoint` on the inflow, outflow, and unit-assignment endpoints, plus `sagemaker:CreateTrainingJob`, `sagemaker:DescribeTrainingJob`, `sagemaker:CreateModel`, `sagemaker:CreateEndpointConfig`, and `sagemaker:UpdateEndpoint` on the model resources for retraining
- `lambda:InvokeFunction` on the Monte Carlo composition Lambda
- `dynamodb:BatchWriteItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, and `dynamodb:GetItem` on the `census-forecasts` table, scoped to the specific table ARN
- `events:PutEvents` on the census-forecast-events bus for emitting pipeline-lifecycle events
- `states:StartExecution` on the census-forecast Step Functions state machine for the recurring inference run and the weekly + monthly retraining runs
- `cloudwatch:PutMetricData` for the operational metrics (forecast unit-hours generated, predicted-gridlock unit-hours, generation latency per cycle, per-horizon MAPE on the rolling backtest window, prediction-interval coverage)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the HealthLake datastore, the S3 prefixes, the DynamoDB table, and the model-artifact bucket
- `bedrock:InvokeModel` on the chosen Bedrock model identifier if narrative summaries are enabled (and the BAA must explicitly cover Bedrock)

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The snapshot Glue job has read access to the HealthLake datastore and write access to the snapshot S3 prefix, but no DynamoDB or SageMaker permissions. The Monte Carlo Lambda has read access to the inflow and outflow forecast prefixes plus the snapshot prefix, write access to the sample-trajectory prefix and the `census-forecasts` DynamoDB table, and `cloudwatch:PutMetricData` permission, but no HealthLake permissions. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **ADT and FHIR Encounter resources are PHI in their entirety.** Patient identifier, admission timestamp, current location, attending physician, working DRG, planned disposition, every comorbidity flag, every consult, every discharge order. Every storage and compute service that touches this pipeline must be on the [HIPAA eligible services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/) list, every storage layer must be encrypted with customer-managed KMS keys, every network hop must be inside the institutional VPC with no public path, and CloudTrail must log every data-plane API call. The aggregated census forecasts still derive from PHI; even though a row that says "telemetry-3-east will be at 94% by 14:00" carries no patient identifier, the underlying training data and inference inputs are PHI and the forecast remains under the BAA.
- **The snapshot is the anchor for every subsequent step.** Get the current state wrong (a stale ADT message, a missed transfer, a duplicate admission) and the rest of the pipeline is calibrated to a fiction. Production runs continuous data quality checks on the snapshot (does the row count match the bed-management system's count, do the unit-level totals reconcile, are there encounters in `in-progress` status with no current location) and alarms when reconciliation fails.
- **The discharge order is the strongest single feature.** A single binary feature ("has a discharge order been entered for this encounter") carries more predictive power for the next-six-hours discharge probability than every other feature combined. The demo's `ExponentialSurvivalModel` honors this by using a steeper hazard for patients with the order in.
- **The Monte Carlo composition is what makes the prediction intervals real.** Without sampling, the pipeline produces a point estimate that will look correct on average and wrong on any given Monday. The demo's composition draws 200 samples by default to keep the run fast; production uses 500 to 1000 and runs the composition in Lambda or AWS Batch.
- **Unit assignment is the political layer.** The classifier captures the historical assignment pattern, including its inconsistencies. Production lets the bed-management team review and override the assignment probabilities for specific (diagnosis, surgery, ED-disposition) combinations through a small configuration table. The demo wires the assignment as a static probability table to keep the example readable.
- **Capacity is a hard constraint, not a soft preference.** The composition step has to apply the overflow rules at every hour or it produces unit-level forecasts that exceed capacity, which is operationally meaningless. The demo's `OVERFLOW_RULES` table maps each unit to an ordered list of overflow targets; production reads this from a configuration store the bed-management team owns.
- **DynamoDB rejects Python `float`.** Every occupancy value, capacity figure, utilization fraction, percentile, and metric value passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses many Lambdas, Glue jobs, and SageMaker endpoints into a single Python file.** In production the snapshot Glue job, the inflow SageMaker endpoint, the outflow SageMaker endpoint, the unit-assignment SageMaker endpoint, the Monte Carlo Lambda, and the DynamoDB-loader Lambda are separate units of work with their own IAM roles, error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the unit map, the unit capacities, the overflow rules, the per-source inflow rates, the unit-assignment probability table, the discharge-hour-of-day pattern, the survival-model hazard parameters, and the Monte Carlo settings are what you would change between environments.

```python
import json
import logging
import math
import random
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights for cross-call investigation. The
# snapshot, the per-patient features, and the per-patient hazard
# scores are PHI. Log structural metadata only (run_id, snapshot_ts,
# unit_id, sample_count, runtime_ms), never patient identifiers,
# never raw working DRGs, never the per-encounter feature vectors.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from S3, DynamoDB, EventBridge,
# CloudWatch, HealthLake, and SageMaker. The inference pipeline
# runs every 15 to 60 minutes; transient failures should retry
# quickly so a stuck dependency does not cascade into a missed
# cycle. The forecast going stale by twenty minutes is materially
# worse than running with a slightly degraded compute path.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across function calls within the
# pipeline so each call does not pay the connection cost. The
# demo wires up MockS3 / MockTable / MockEventBus / MockCloudWatch /
# MockHealthLake via run_demo() and never touches these real
# handles; they are staged here so production wiring is a one-line
# swap. boto3 client and resource construction is lazy (no network
# call until first use), so the unused handles are free at import.
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
HEALTHLAKE_DATASTORE_ID    = "inpatient-fhir-datastore"
RAW_ADT_BUCKET             = "census-forecast-raw-adt"
OR_SCHEDULE_BUCKET         = "census-forecast-or-schedule"
TRANSFER_QUEUE_BUCKET      = "census-forecast-transfer-queue"
ED_BOARD_BUCKET            = "census-forecast-ed-board"
SNAPSHOT_BUCKET            = "census-forecast-snapshots"
INFLOW_FORECAST_BUCKET     = "census-forecast-inflows"
OUTFLOW_FORECAST_BUCKET    = "census-forecast-outflows"
SAMPLE_TRAJECTORY_BUCKET   = "census-forecast-trajectories"
MODEL_ARTIFACT_BUCKET      = "census-forecast-models"
CENSUS_FORECAST_TABLE      = "census-forecasts"
CENSUS_EVENT_BUS_NAME      = "census-forecast-events-bus"
CLOUDWATCH_NAMESPACE       = "HospitalCensusForecast"

# --- Versioning ---
# Every forecast record carries the model versions and the rule
# version active at the time of generation. This is how a future
# audit reconstructs which inflow model, which survival model,
# and which overflow configuration produced which forecast on
# which cycle. The combined identifier is also useful when the
# bed-management team asks "are we still on the model that was
# in production three weeks ago".
PIPELINE_VERSION       = "census-pipeline-v1.0"
INFLOW_MODEL_VERSION   = "inflow-poisson-v1"
SURVIVAL_MODEL_VERSION = "outflow-exp-v1"
ASSIGNER_MODEL_VERSION = "unit-assigner-v1"
OVERFLOW_RULES_VERSION = "overflow-rules-2026-05"

# --- Forecast Horizon and Cadence ---
# The demo's horizon is 24 hours. Production runs the pipeline
# every 15 to 60 minutes (the cadence is operational policy) and
# typically forecasts 4-to-72 hours forward. The horizon is the
# inference-time choice; the model itself does not encode a
# specific horizon.
FORECAST_HORIZON_HOURS    = 24
DEFAULT_MONTE_CARLO_SAMPLES = 200    # production uses 500 to 1000

# --- Hospital Map ---
# The demo's 412-bed community hospital. Production reads the unit
# map from a configuration store the bed-management team owns; the
# unit codes here are illustrative.
UNIT_CATALOG = {
    "ed-hold":      {"display": "ED Holding",        "capacity": 12},
    "tele-3-east":  {"display": "Telemetry 3 East",  "capacity": 28},
    "medsurg-4-w":  {"display": "Med-Surg 4 West",   "capacity": 36},
    "ortho-5-n":    {"display": "Orthopedic 5 North","capacity": 24},
    "stepdown-icu": {"display": "Step-Down ICU",     "capacity": 16},
}

# --- Overflow Rules ---
# When a unit's projected occupancy exceeds capacity in a Monte
# Carlo sample, the overflow logic redistributes the excess to the
# designated overflow targets in priority order. Production reads
# this from a configuration store the bed-management team owns.
OVERFLOW_RULES = {
    "ed-hold":      ["medsurg-4-w", "tele-3-east"],
    "tele-3-east":  ["stepdown-icu", "medsurg-4-w"],
    "medsurg-4-w":  ["ortho-5-n", "tele-3-east"],
    "ortho-5-n":    ["medsurg-4-w"],
    "stepdown-icu": ["tele-3-east"],
}

# --- Inflow Rates ---
# Per-source hourly admission Poisson rates. Production fits these
# from historical ADT data with calendar, weather, and current-ED
# state features; the demo uses a static rate per source so the
# example stays readable. The rates are calibrated so the synthetic
# 412-bed hospital sees ~50 admissions per day, which is the right
# order of magnitude for a community hospital.
HOURLY_INFLOW_RATES = {
    "ed_admit":     0.95,    # ED-driven admissions per hour
    "direct_admit": 0.20,    # office or clinic direct admits per hour
    "transfer_in":  0.05,    # outside-facility transfers per hour
}

# --- Unit Assignment ---
# Probability distribution over admission units conditional on the
# admission source. Production fits these from historical ADT
# joined with EHR diagnosis and disposition; the demo encodes
# realistic-shaped distributions per source. Surgical post-op
# admits do not use this table because the OR schedule already
# specifies the target unit.
UNIT_ASSIGNMENT_PROBABILITIES = {
    "ed_admit": {
        "tele-3-east":  0.30,
        "medsurg-4-w":  0.45,
        "ortho-5-n":    0.05,
        "stepdown-icu": 0.10,
        "ed-hold":      0.10,
    },
    "direct_admit": {
        "tele-3-east":  0.20,
        "medsurg-4-w":  0.55,
        "ortho-5-n":    0.10,
        "stepdown-icu": 0.10,
        "ed-hold":      0.05,
    },
    "transfer_in": {
        "tele-3-east":  0.20,
        "medsurg-4-w":  0.30,
        "ortho-5-n":    0.10,
        "stepdown-icu": 0.40,
        "ed-hold":      0.00,
    },
}

# --- Hour-of-Day Discharge Pattern ---
# Hospitals discharge 70-80% of their volume between 10:00 and 18:00
# with a peak around 13:00-15:00. The pattern below is the relative
# discharge intensity per hour of day; the survival model's per-hour
# probability gets multiplied by this factor so the discharge times
# concentrate during the day. Production fits this from historical
# discharge timestamps; the demo uses a typical bell-shaped pattern.
HOUR_OF_DAY_DISCHARGE_INTENSITY = {
    0:  0.05, 1:  0.05, 2:  0.05, 3:  0.05, 4:  0.05, 5:  0.05,
    6:  0.10, 7:  0.20, 8:  0.40, 9:  0.70, 10: 1.20, 11: 1.50,
    12: 1.60, 13: 1.80, 14: 1.70, 15: 1.50, 16: 1.20, 17: 0.90,
    18: 0.60, 19: 0.40, 20: 0.20, 21: 0.10, 22: 0.05, 23: 0.05,
}

# --- Service Lines ---
# Per-service-line baseline length-of-stay parameters. The
# survival model uses these as its prior; production fits a
# proper survival regression that learns from history.
SERVICE_LINE_LOS_HOURS = {
    "medicine":       96.0,    # 4 days
    "cardiology":     72.0,    # 3 days
    "orthopedics":    60.0,    # 2.5 days post-joint-replacement
    "general_surgery":48.0,    # 2 days
    "neurology":      120.0,   # 5 days
    "icu_stepdown":   72.0,    # 3 days in step-down
}

# Discharge-order multiplier. A patient with a discharge order
# entered has a hazard rate roughly 6x the patient without one;
# this is the single most important feature in real survival
# models for hospital discharge.
DISCHARGE_ORDER_HAZARD_MULTIPLIER = 6.0

# --- Synthetic Data ---
SYNTHETIC_RANDOM_SEED = 42

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("HEALTHLAKE_DATASTORE_ID",    HEALTHLAKE_DATASTORE_ID),
    ("RAW_ADT_BUCKET",             RAW_ADT_BUCKET),
    ("OR_SCHEDULE_BUCKET",         OR_SCHEDULE_BUCKET),
    ("TRANSFER_QUEUE_BUCKET",      TRANSFER_QUEUE_BUCKET),
    ("ED_BOARD_BUCKET",            ED_BOARD_BUCKET),
    ("SNAPSHOT_BUCKET",            SNAPSHOT_BUCKET),
    ("INFLOW_FORECAST_BUCKET",     INFLOW_FORECAST_BUCKET),
    ("OUTFLOW_FORECAST_BUCKET",    OUTFLOW_FORECAST_BUCKET),
    ("SAMPLE_TRAJECTORY_BUCKET",   SAMPLE_TRAJECTORY_BUCKET),
    ("MODEL_ARTIFACT_BUCKET",      MODEL_ARTIFACT_BUCKET),
    ("CENSUS_FORECAST_TABLE",      CENSUS_FORECAST_TABLE),
    ("CENSUS_EVENT_BUS_NAME",      CENSUS_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",       CLOUDWATCH_NAMESPACE),
]:
    assert _value, f"{_name} must be set before deploying."

def _to_decimal(value):
    """Convert numeric values to Decimal for DynamoDB-safe writes.

    DynamoDB rejects Python float at the SDK boundary because
    floating-point cannot represent every decimal value exactly.
    Pass everything numeric through this helper before any
    PutItem, BatchWriteItem, or UpdateItem call.
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
        return Decimal(str(round(float(value), 6)))
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(f"Cannot convert {type(value).__name__} to Decimal")
```

---

## Mocks and Synthetic Data

The demo never touches a real HealthLake datastore, S3 bucket, DynamoDB table, EventBridge bus, or SageMaker endpoint. The mocks below stand in for those services so the focus stays on the census-forecasting logic. They print what they would write rather than failing, which makes the demo runnable without any AWS resources provisioned.

```python
class MockHealthLake:
    """In-memory stand-in for an Amazon HealthLake FHIR datastore.

    Production uses boto3.client('healthlake') and the FHIR REST
    API to read Encounter resources keyed by status and date.
    The mock stores encounters as a list and provides simple
    search-by-status semantics, which is what the snapshot step
    needs.
    """

    def __init__(self):
        self.encounters = []

    def put_encounter(self, encounter):
        self.encounters.append(dict(encounter))

    def search_in_progress_encounters(self, as_of_ts):
        return [
            dict(e) for e in self.encounters
            if e.get("status") == "in-progress"
            and e.get("admit_ts") <= as_of_ts
        ]

class MockS3:
    """In-memory stand-in for an S3 bucket."""

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

    Production uses boto3.resource('dynamodb').Table(name). The
    mock supports the operations the demo calls: batch_writer,
    put_item, query, get_item. It is not a complete DynamoDB
    emulation; it covers what this pipeline needs.
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
            pk = Item["unit_id"]
            sk = Item["forecast_for_ts"]
            self.table.items[(pk, sk)] = dict(Item)
            self.table.write_count += 1

    def batch_writer(self):
        return self._BatchWriter(self)

    def put_item(self, Item):
        pk = Item["unit_id"]
        sk = Item["forecast_for_ts"]
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

def generate_synthetic_inputs(now_dt, seed=SYNTHETIC_RANDOM_SEED):
    """Generate synthetic inputs for the census pipeline.

    Production reads the current state from Amazon HealthLake (or
    a continuously-updated S3 mirror), the OR schedule from the
    surgical scheduling system, the transfer queue from the
    transfer center system, and the ED tracking board from the
    ED tracking system. The demo synthesizes a realistic-shaped
    set of these so you can see the pipeline behave end-to-end.

    Returns a dict with:
      - encounters: list of currently-admitted patient encounters
      - or_schedule: list of scheduled surgical cases
      - transfer_queue: list of inbound transfer requests
      - ed_board: list of pending ED admit holds
    """
    rng = random.Random(seed)

    # --- Currently admitted patients (the snapshot population) ---
    # Distribute ~360 occupied beds across the 5 units so the
    # hospital starts at ~87% utilization. Hospital census never
    # actually runs at 100%; somewhere between 80% and 92% is the
    # operationally interesting band.
    target_occupancy = {
        "ed-hold":       8,    # 8 of 12
        "tele-3-east":  24,    # 24 of 28
        "medsurg-4-w":  31,    # 31 of 36
        "ortho-5-n":    20,    # 20 of 24
        "stepdown-icu": 14,    # 14 of 16
    }

    encounters = []
    for unit_code, count in target_occupancy.items():
        for i in range(count):
            # Sample length-of-stay so far. Most patients are
            # mid-stay; a few are day-of-admission, a few are
            # long-stay.
            los_hours = rng.choice([
                rng.uniform(2, 24),
                rng.uniform(24, 72),
                rng.uniform(72, 120),
                rng.uniform(120, 240),
            ])
            admit_ts = (now_dt - timedelta(hours=los_hours)).isoformat()

            # Service line distribution differs by unit. Telemetry
            # leans cardiology, ortho leans orthopedics, etc.
            if unit_code == "tele-3-east":
                service = rng.choices(
                    ["cardiology", "medicine"], weights=[0.7, 0.3])[0]
            elif unit_code == "ortho-5-n":
                service = rng.choices(
                    ["orthopedics", "general_surgery"], weights=[0.85, 0.15])[0]
            elif unit_code == "stepdown-icu":
                service = rng.choices(
                    ["icu_stepdown", "cardiology", "neurology"],
                    weights=[0.6, 0.25, 0.15])[0]
            elif unit_code == "ed-hold":
                service = rng.choices(
                    ["medicine", "cardiology"], weights=[0.6, 0.4])[0]
            else:    # medsurg-4-w
                service = rng.choices(
                    ["medicine", "general_surgery", "neurology"],
                    weights=[0.6, 0.25, 0.15])[0]

            # ~25% of patients have a discharge order entered.
            # Real hospitals see this fraction climb during the
            # day from near zero overnight to 35-50% by 14:00.
            discharge_order_entered = (rng.random() < 0.25)

            encounters.append({
                "encounter_id":             f"enc-{unit_code}-{i:03d}-{uuid.uuid4().hex[:6]}",
                "patient_id":               f"pt-{uuid.uuid4().hex[:8]}",
                "status":                   "in-progress",
                "current_unit":             unit_code,
                "admit_ts":                 admit_ts,
                "service_line":             service,
                "attending_id":             f"attd-{rng.randint(1, 40)}",
                "working_drg":              f"DRG-{rng.randint(100, 999)}",
                "planned_disposition":      rng.choice(
                    ["home", "home", "home", "snf", "rehab", "hospice"]),
                "discharge_order_entered":  discharge_order_entered,
                "los_hours_so_far":         los_hours,
            })

    # --- OR schedule (next 24-48 hours) ---
    # A handful of elective cases per service line. The post-op
    # admit timestamp is the scheduled end + a PACU-to-floor
    # delay. The target unit is determined by surgery type.
    or_schedule = []
    case_count = 6
    for i in range(case_count):
        scheduled_start = now_dt + timedelta(hours=rng.uniform(2, 36))
        case_duration = rng.uniform(1.5, 4.0)
        scheduled_end = scheduled_start + timedelta(hours=case_duration)
        surgery_type = rng.choices(
            ["total_knee", "cabg", "cholecystectomy", "spinal_fusion"],
            weights=[0.35, 0.25, 0.25, 0.15])[0]
        # PACU-to-floor delay varies by surgery. Shorter for minor
        # cases, longer for cardiac.
        pacu_delay = {
            "total_knee":      2.0,
            "cabg":            6.0,
            "cholecystectomy": 1.5,
            "spinal_fusion":   3.0,
        }[surgery_type]
        post_op_unit = {
            "total_knee":      "ortho-5-n",
            "cabg":            "stepdown-icu",
            "cholecystectomy": "medsurg-4-w",
            "spinal_fusion":   "ortho-5-n",
        }[surgery_type]
        or_schedule.append({
            "case_id":             f"case-{i:03d}",
            "surgery_type":        surgery_type,
            "service_line":        rng.choice(
                ["orthopedics", "cardiology", "general_surgery"]),
            "scheduled_start_ts":  scheduled_start.isoformat(),
            "scheduled_end_ts":    scheduled_end.isoformat(),
            "pacu_delay_hours":    pacu_delay,
            "target_unit":         post_op_unit,
            "show_probability":    0.94,    # historical no-show + cancellation rate
        })

    # --- Transfer queue (known inbound transfers, near-term) ---
    transfer_queue = []
    for i in range(2):
        eta = now_dt + timedelta(hours=rng.uniform(1, 6))
        transfer_queue.append({
            "transfer_id":  f"xfr-{i:03d}",
            "expected_arrival_ts": eta.isoformat(),
            "target_unit":  rng.choice(["stepdown-icu", "tele-3-east"]),
            "service_line": rng.choice(["cardiology", "neurology"]),
        })

    # --- ED tracking board (current ED admits not yet placed) ---
    ed_board = []
    for i in range(3):
        ed_board.append({
            "ed_visit_id":   f"ed-{i:03d}",
            "admit_decision_ts": (now_dt - timedelta(
                hours=rng.uniform(0.5, 3.0))).isoformat(),
            "expected_target_unit": rng.choice(
                ["tele-3-east", "medsurg-4-w"]),
            "service_line":  rng.choice(["medicine", "cardiology"]),
        })

    return {
        "encounters":     encounters,
        "or_schedule":    or_schedule,
        "transfer_queue": transfer_queue,
        "ed_board":       ed_board,
    }
```

---

## Step 1: Snapshot the Current Hospital State

This step captures every active inpatient encounter at the current time and builds the per-patient feature record the survival model will consume. In production this is an AWS Glue job that reads new HealthLake encounters on a 15-to-60-minute cadence, joins them with the EHR's encounter-class and discharge-order data, and writes the snapshot to S3. The demo does the equivalent in plain Python.

```python
def snapshot_current_state(snapshot_ts, healthlake, s3, bucket):
    """Step 1: Capture currently-admitted patients and per-patient features.

    See pseudocode Step 1 in the main recipe. Returns a list of
    state records the inflow, outflow, and composition steps
    consume. Each record carries enough context for the survival
    model to score it without a second HealthLake round trip.
    """
    iso_now = snapshot_ts.isoformat()
    active_encounters = healthlake.search_in_progress_encounters(
        as_of_ts=iso_now)

    state_records = []
    for encounter in active_encounters:
        # Build the per-patient features the survival model needs.
        # Production pulls additional FHIR resources here:
        # Condition (diagnoses), MedicationRequest (active meds),
        # ServiceRequest (pending consults), ClinicalImpression
        # (discharge planning notes). The demo's encounter dict
        # carries a curated subset that maps to those features.
        features = {
            "service_line":             encounter["service_line"],
            "attending_id":              encounter["attending_id"],
            "working_drg":               encounter["working_drg"],
            "planned_disposition":       encounter["planned_disposition"],
            "discharge_order_entered":   encounter["discharge_order_entered"],
            "los_hours_so_far":          encounter["los_hours_so_far"],
        }

        record = {
            "encounter_id":     encounter["encounter_id"],
            "patient_id":       encounter["patient_id"],
            "current_unit":     encounter["current_unit"],
            "admit_ts":         encounter["admit_ts"],
            "snapshot_ts":      iso_now,
            "features":         features,
        }
        state_records.append(record)

    # Persist the snapshot to S3 partitioned by date and hour so
    # the inference Step Functions execution and any downstream
    # backtest jobs can read it without paying the FHIR-search
    # cost a second time.
    s3_key = (f"snapshots/year={snapshot_ts.year:04d}/"
              f"month={snapshot_ts.month:02d}/"
              f"day={snapshot_ts.day:02d}/"
              f"hour={snapshot_ts.hour:02d}/"
              f"snapshot-{uuid.uuid4().hex[:8]}.json")
    s3.put_object(Bucket=bucket, Key=s3_key,
                  Body=json.dumps(state_records, default=str))

    logger.info(
        "Snapshotted %d active encounters across %d units",
        len(state_records),
        len({r["current_unit"] for r in state_records}))
    return state_records

def current_census_by_unit(state_records):
    """Count occupants per unit at snapshot time."""
    by_unit = defaultdict(int)
    for r in state_records:
        by_unit[r["current_unit"]] += 1
    return dict(by_unit)
```

---

## Step 2: Forecast Inflows by Source, Service, and Unit

For each forecast hour and each candidate admit unit, the pipeline produces an expected admission count plus a sample distribution suitable for Monte Carlo composition. Different sources use different methods: ED-driven and direct admits run through a Poisson model, the OR schedule is read deterministically and multiplied by show-rate, the transfer queue contributes a near-term known quantity plus a Poisson tail. Unit assignment runs through a multinomial classifier given the admission's source.

```python
class PoissonInflowModel:
    """Pedagogical Poisson sampler for hourly admission counts.

    Production fits a real Poisson regression (statsmodels GLM
    with the Poisson family) on calendar features (hour of day,
    day of week, month), weather features, and current-state
    features (ED census, ED holds), then samples from the fitted
    rate per hour. The demo uses a static rate per source, with
    a small day-of-week multiplier so Mondays look busier than
    Sundays.
    """

    name = "poisson_inflow"

    def __init__(self, hourly_rate, day_of_week_multipliers=None):
        self.hourly_rate = hourly_rate
        self.day_of_week_multipliers = day_of_week_multipliers or {}

    def sample_count(self, target_ts, rng):
        """Sample one admission count for one hour."""
        dow = target_ts.weekday()    # 0 = Monday
        multiplier = self.day_of_week_multipliers.get(dow, 1.0)
        rate = self.hourly_rate * multiplier
        # Poisson sampling via the Knuth algorithm; production uses
        # numpy.random.Generator.poisson which is faster and more
        # correct for large rates.
        l = math.exp(-rate)
        k = 0
        p = 1.0
        while True:
            k += 1
            p *= rng.random()
            if p <= l:
                return k - 1

class MultinomialUnitAssigner:
    """Pedagogical multinomial unit-assignment classifier.

    Production fits a real multinomial classifier (scikit-learn
    LogisticRegression(multi_class='multinomial') or SageMaker
    XGBoost) on admission features (chief complaint, diagnosis,
    service line, ED disposition). The demo encodes a static
    probability table per source.
    """

    name = "unit_assigner"

    def __init__(self, probability_table):
        self.probability_table = probability_table

    def sample_unit(self, admission_source, rng):
        probs = self.probability_table.get(admission_source, {})
        if not probs:
            return None
        units = list(probs.keys())
        weights = [probs[u] for u in units]
        return rng.choices(units, weights=weights, k=1)[0]

def forecast_inflows(snapshot_ts, horizon_hours, n_samples,
                     or_schedule, transfer_queue, ed_board,
                     inflow_models, unit_assigner,
                     s3, bucket, run_id, rng_seed=SYNTHETIC_RANDOM_SEED):
    """Step 2: Sample per-source admission counts, assign to units.

    See pseudocode Step 2 in the main recipe. Returns a 3-D array
    shaped [n_samples, horizon_hours, n_units] of admission counts.
    Index ordering uses sorted unit codes so the composition step
    can join cleanly.
    """
    rng = random.Random(rng_seed)
    unit_codes = sorted(UNIT_CATALOG.keys())
    unit_index = {u: i for i, u in enumerate(unit_codes)}
    n_units = len(unit_codes)

    # 3-D grid of admission counts.
    inflow_samples = [
        [[0 for _ in range(n_units)] for _ in range(horizon_hours)]
        for _ in range(n_samples)
    ]

    # 2a. ED-driven and direct admits: Poisson per source, then
    # sample the unit assignment from the per-source classifier.
    poisson_sources = ["ed_admit", "direct_admit", "transfer_in"]
    for sample_id in range(n_samples):
        for hour_offset in range(horizon_hours):
            target_ts = snapshot_ts + timedelta(hours=hour_offset)
            for source in poisson_sources:
                count = inflow_models[source].sample_count(target_ts, rng)
                for _ in range(count):
                    unit_code = unit_assigner.sample_unit(source, rng)
                    if unit_code is not None:
                        inflow_samples[sample_id][hour_offset][
                            unit_index[unit_code]] += 1

    # 2b. ED tracking board: pending admits expected to land in
    # the next 1-3 hours with high probability. Production uses
    # the ED's tracking-board admit-decision timestamps and
    # ED-to-floor latency. The demo treats each board entry as
    # a Bernoulli draw against a fixed probability.
    for sample_id in range(n_samples):
        for ed_entry in ed_board:
            if rng.random() < 0.92:    # very likely to admit
                # Land the admit between hour 0 and hour 2.
                hour = rng.randint(0, min(2, horizon_hours - 1))
                unit_code = ed_entry["expected_target_unit"]
                if unit_code in unit_index:
                    inflow_samples[sample_id][hour][unit_index[unit_code]] += 1

    # 2c. OR schedule: deterministic show-rate-weighted admits.
    # Each scheduled case lands in the post-op unit at scheduled_end
    # + PACU delay, with a Bernoulli draw against the show probability
    # to capture cancellations.
    for sample_id in range(n_samples):
        for case in or_schedule:
            if rng.random() < case["show_probability"]:
                end_ts = datetime.fromisoformat(case["scheduled_end_ts"])
                admit_ts = end_ts + timedelta(hours=case["pacu_delay_hours"])
                hour_offset = int((admit_ts - snapshot_ts).total_seconds() / 3600)
                if 0 <= hour_offset < horizon_hours:
                    unit_code = case["target_unit"]
                    if unit_code in unit_index:
                        inflow_samples[sample_id][hour_offset][
                            unit_index[unit_code]] += 1

    # 2d. Transfer queue: known near-term transfers with a small
    # Bernoulli draw against the chance the transfer falls through
    # (sending hospital reroutes, accepting unit declines, weather).
    for sample_id in range(n_samples):
        for xfer in transfer_queue:
            if rng.random() < 0.85:
                eta = datetime.fromisoformat(xfer["expected_arrival_ts"])
                hour_offset = int((eta - snapshot_ts).total_seconds() / 3600)
                if 0 <= hour_offset < horizon_hours:
                    unit_code = xfer["target_unit"]
                    if unit_code in unit_index:
                        inflow_samples[sample_id][hour_offset][
                            unit_index[unit_code]] += 1

    # Persist the inflow samples to S3 so the Lambda Monte Carlo
    # composition can read them as input. The shape is bulky
    # (n_samples * horizon * n_units), so production typically
    # writes Parquet; the demo writes JSON for readability.
    s3_key = (f"inflows/run_id={run_id}/"
              f"snapshot_ts={snapshot_ts.isoformat()}/inflows.json")
    s3.put_object(Bucket=bucket, Key=s3_key,
                  Body=json.dumps({
                      "inflow_samples": inflow_samples,
                      "unit_codes":     unit_codes,
                  }))

    logger.info(
        "Generated %d inflow samples across %d hours and %d units",
        n_samples, horizon_hours, n_units)
    return inflow_samples, unit_codes
```

---

## Step 3: Per-Patient Discharge Probability Over the Horizon

For every currently-admitted patient, predict the probability they discharge in each hour of the forecast horizon. A real survival model takes the per-patient features and produces a hazard function over the horizon. The demo uses an exponential survival model with a per-service-line baseline rate, a discharge-order multiplier, and an hour-of-day multiplier so the simulated discharge times concentrate in the typical 13:00-15:00 peak. Production swaps this for a Cox proportional hazards model, an XGBoost survival model (XGBSE), or a deep survival model like DeepHit.

```python
class ExponentialSurvivalModel:
    """Pedagogical exponential survival model for hospital discharge.

    Production fits a Cox proportional hazards model (lifelines
    or scikit-survival), an XGBoost survival model (XGBSE), or a
    deep survival model (DeepHit, PySurvival) on per-patient
    features. The demo computes the hazard analytically:

        hazard(h) = baseline_hazard(service_line)
                    * discharge_order_multiplier
                    * hour_of_day_intensity(target_hour)

    where baseline_hazard is the inverse of the service-line's
    expected total LOS, discharge_order_multiplier is 6.0 if the
    order is in (and 1.0 otherwise), and hour_of_day_intensity is
    the relative discharge intensity at the target hour-of-day.
    The hazard is converted to a per-hour discharge probability
    via the standard exponential decay formula.
    """

    name = "exp_survival"

    def __init__(self,
                 service_los_hours,
                 hour_of_day_intensity,
                 discharge_order_multiplier):
        self.service_los_hours       = service_los_hours
        self.hour_of_day_intensity   = hour_of_day_intensity
        self.discharge_order_multiplier = discharge_order_multiplier

    def hazard_per_hour(self, features, target_hour_of_day):
        """Compute the discharge hazard rate for one hour."""
        service = features["service_line"]
        baseline_los = self.service_los_hours.get(service, 96.0)
        baseline_hazard = 1.0 / baseline_los

        # Patients past their service-line LOS have a slightly
        # elevated hazard (they are statistically due to discharge
        # any hour now). Patients earlier in their stay have a
        # slightly suppressed hazard. The demo's adjustment is a
        # smooth function; production fits this from data.
        los_hours = features.get("los_hours_so_far", 0.0)
        los_ratio = los_hours / max(baseline_los, 1.0)
        if los_ratio < 0.3:
            stage_multiplier = 0.4
        elif los_ratio < 0.7:
            stage_multiplier = 0.9
        elif los_ratio < 1.2:
            stage_multiplier = 1.5
        else:
            stage_multiplier = 2.2

        # The discharge order is the strongest single feature.
        order_multiplier = (
            self.discharge_order_multiplier
            if features.get("discharge_order_entered") else 1.0)

        # Hour-of-day pattern. Discharges concentrate during the
        # day; overnight discharges are minimal.
        hour_multiplier = self.hour_of_day_intensity.get(
            target_hour_of_day, 1.0)

        return (baseline_hazard
                * stage_multiplier
                * order_multiplier
                * hour_multiplier)

    def discharge_probability_per_hour(self, features, snapshot_ts,
                                        horizon_hours):
        """Return the per-hour discharge probability over the horizon.

        Standard exponential survival: P(discharge in hour h) =
        S(h) * (1 - exp(-hazard(h))), where S(h) is the survival
        function (probability of not having discharged by hour h).
        """
        per_hour = []
        survival = 1.0
        for hour_offset in range(horizon_hours):
            target_ts = snapshot_ts + timedelta(hours=hour_offset)
            target_hour = target_ts.hour
            hazard = self.hazard_per_hour(features, target_hour)
            # Per-hour discharge probability conditional on
            # surviving to hour h.
            p_discharge_this_hour = 1.0 - math.exp(-hazard)
            # Marginal probability of discharging in this hour.
            marginal = survival * p_discharge_this_hour
            per_hour.append(marginal)
            survival *= (1.0 - p_discharge_this_hour)
        return per_hour, survival

def forecast_outflows(state_records, snapshot_ts, horizon_hours,
                       n_samples, survival_model, unit_codes,
                       s3, bucket, run_id,
                       rng_seed=SYNTHETIC_RANDOM_SEED + 1):
    """Step 3: Sample per-patient discharge times per Monte Carlo sample.

    See pseudocode Step 3 in the main recipe. Returns a 3-D array
    shaped [n_samples, horizon_hours, n_units] of discharge counts.
    """
    rng = random.Random(rng_seed)
    unit_index = {u: i for i, u in enumerate(unit_codes)}
    n_units = len(unit_codes)

    # Score every encounter once. The per-patient discharge
    # probability vector is reused across all Monte Carlo samples.
    scored = []
    for record in state_records:
        per_hour, survival = survival_model.discharge_probability_per_hour(
            features=record["features"],
            snapshot_ts=snapshot_ts,
            horizon_hours=horizon_hours)
        scored.append({
            "encounter_id":   record["encounter_id"],
            "current_unit":   record["current_unit"],
            "per_hour_probs": per_hour,
            "no_discharge_p": survival,    # P(stays past horizon)
        })

    # Build the [n_samples, horizon, n_units] discharge grid by
    # drawing one discharge time per patient per sample.
    outflow_samples = [
        [[0 for _ in range(n_units)] for _ in range(horizon_hours)]
        for _ in range(n_samples)
    ]
    for sample_id in range(n_samples):
        for s in scored:
            # Multinomial draw: each patient discharges in some
            # hour of the horizon, or not at all (probability =
            # s["no_discharge_p"]).
            probs = list(s["per_hour_probs"]) + [s["no_discharge_p"]]
            outcomes = list(range(horizon_hours)) + [None]
            choice = rng.choices(outcomes, weights=probs, k=1)[0]
            if choice is not None:
                unit_idx = unit_index.get(s["current_unit"])
                if unit_idx is not None:
                    outflow_samples[sample_id][choice][unit_idx] += 1

    # Persist the outflow samples for the composition step.
    s3_key = (f"outflows/run_id={run_id}/"
              f"snapshot_ts={snapshot_ts.isoformat()}/outflows.json")
    s3.put_object(Bucket=bucket, Key=s3_key,
                  Body=json.dumps({
                      "outflow_samples": outflow_samples,
                      "unit_codes":      unit_codes,
                  }))

    logger.info(
        "Scored %d patients across %d samples for outflow forecast",
        len(state_records), n_samples)
    return outflow_samples
```

---

## Step 4: Compose Census Trajectories with Monte Carlo

Walk forward sample by sample, applying inflows and outflows hour by hour against the snapshot starting point. When a unit's projected occupancy would exceed capacity, the overflow logic redistributes the excess admissions to the designated overflow targets in priority order. Aggregate across samples to produce the per-unit, per-hour expected occupancy and prediction intervals.

```python
def _percentile(values, pct):
    """Compute the pct percentile of a list of numbers."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

def _distribute_overflow(census, source_unit, overflow_count,
                         unit_index, unit_codes, capacities,
                         overflow_rules):
    """Place the excess admissions into the overflow targets.

    Walks the priority list of overflow targets in order. For
    each target, places as many of the overflow patients as fit.
    If targets fill up too, the remainder is left as a residual
    that the consumers can interpret as projected gridlock.
    Returns the number of overflow patients that could not be
    placed anywhere.
    """
    targets = overflow_rules.get(source_unit, [])
    remaining = overflow_count
    for target_unit in targets:
        if target_unit not in unit_index:
            continue
        target_idx = unit_index[target_unit]
        target_cap = capacities[target_unit]
        target_occ = census[target_idx]
        slack = max(target_cap - target_occ, 0)
        place = min(slack, remaining)
        census[target_idx] += place
        remaining -= place
        if remaining <= 0:
            return 0
    return remaining

def compose_census(state_records, inflow_samples, outflow_samples,
                   unit_codes, snapshot_ts, horizon_hours,
                   s3, bucket, run_id):
    """Step 4: Run the Monte Carlo composition over inflows and outflows.

    See pseudocode Step 4 in the main recipe. Returns a list of
    forecast records, one per (unit, forecast_for_ts).
    """
    n_samples = len(inflow_samples)
    n_units   = len(unit_codes)
    unit_index = {u: i for i, u in enumerate(unit_codes)}
    capacities = {u: UNIT_CATALOG[u]["capacity"] for u in unit_codes}

    # Initial census per unit from the snapshot.
    initial_census = [0] * n_units
    by_unit = current_census_by_unit(state_records)
    for u, count in by_unit.items():
        if u in unit_index:
            initial_census[unit_index[u]] = count

    # 4a. Walk each sample forward. The trajectory is the per-hour
    # snapshot of census across all units, after applying that
    # sample's outflows then inflows then overflow redistribution.
    sample_trajectories = []
    sample_overflow_residuals = []
    for sample_id in range(n_samples):
        census = list(initial_census)
        trajectory = []
        unplaced_total = 0
        for hour_offset in range(horizon_hours):
            # Apply this sample's outflows for this hour.
            for u_idx in range(n_units):
                census[u_idx] -= outflow_samples[sample_id][hour_offset][u_idx]
                if census[u_idx] < 0:
                    census[u_idx] = 0

            # Apply this sample's inflows for this hour with overflow.
            for u_idx in range(n_units):
                proposed_admits = inflow_samples[sample_id][hour_offset][u_idx]
                if proposed_admits == 0:
                    continue
                target_cap = capacities[unit_codes[u_idx]]
                slack = max(target_cap - census[u_idx], 0)
                fits = min(slack, proposed_admits)
                census[u_idx] += fits
                overflow = proposed_admits - fits
                if overflow > 0:
                    unplaced = _distribute_overflow(
                        census, unit_codes[u_idx], overflow,
                        unit_index, unit_codes, capacities,
                        OVERFLOW_RULES)
                    unplaced_total += unplaced

            # Snapshot the census at the end of this hour.
            trajectory.append(list(census))
        sample_trajectories.append(trajectory)
        sample_overflow_residuals.append(unplaced_total)

    # 4b. Aggregate across samples per (hour_offset, unit).
    forecast_records = []
    for hour_offset in range(horizon_hours):
        forecast_for_ts = (snapshot_ts +
                           timedelta(hours=hour_offset + 1)).isoformat()
        for u_idx, unit_code in enumerate(unit_codes):
            sample_values = [
                sample_trajectories[s][hour_offset][u_idx]
                for s in range(n_samples)
            ]
            mean_occ = sum(sample_values) / len(sample_values)
            capacity = capacities[unit_code]
            forecast_records.append({
                "unit_id":                   unit_code,
                "forecast_for_ts":           forecast_for_ts,
                "horizon_hours_from_snapshot": hour_offset + 1,
                "expected_occupancy":        round(mean_occ, 2),
                "p10_occupancy":             round(_percentile(sample_values, 10), 2),
                "p50_occupancy":             round(_percentile(sample_values, 50), 2),
                "p90_occupancy":             round(_percentile(sample_values, 90), 2),
                "capacity":                  capacity,
                "expected_utilization_pct":  round(mean_occ / capacity, 4),
                "snapshot_ts":               snapshot_ts.isoformat(),
                "generated_at_ts":           datetime.now(timezone.utc).isoformat(),
                "pipeline_version":          PIPELINE_VERSION,
                "inflow_model_version":      INFLOW_MODEL_VERSION,
                "survival_model_version":    SURVIVAL_MODEL_VERSION,
                "assigner_model_version":    ASSIGNER_MODEL_VERSION,
                "overflow_rules_version":    OVERFLOW_RULES_VERSION,
                "monte_carlo_samples":       n_samples,
            })

    # 4c. Persist the per-sample trajectories to S3 for after-the-fact
    # analysis (calibration, debugging surprising forecasts, training
    # the forecast-quality monitoring layer). Production typically
    # writes Parquet for compactness; the demo writes JSON.
    s3_key = (f"trajectories/run_id={run_id}/"
              f"snapshot_ts={snapshot_ts.isoformat()}/trajectories.json")
    s3.put_object(Bucket=bucket, Key=s3_key,
                  Body=json.dumps({
                      "trajectories":              sample_trajectories,
                      "unit_codes":                unit_codes,
                      "overflow_residuals_per_sample": sample_overflow_residuals,
                  }, default=str))

    logger.info(
        "Composed %d forecast records across %d hours and %d units",
        len(forecast_records), horizon_hours, n_units)
    return forecast_records, sample_overflow_residuals
```

---

## Step 5: Deliver Forecasts to Operational Consumers

The bed huddle dashboard, the transfer center, the OR scheduler, and the ED diversion tool all read from DynamoDB. Writing the forecast atomically per cycle (with a `generated_at_ts` attribute) lets consumers identify whether they are showing fresh or stale data. Suppressed gridlock signals go to CloudWatch as the leading indicator of operational pressure, and EventBridge gets a pipeline-completion event so any downstream consumer can refresh.

```python
def deliver_forecast(forecast_records, overflow_residuals,
                     table, event_bus, cloudwatch, run_id):
    """Step 5: Write forecasts to DynamoDB; emit metrics and events.

    See pseudocode Step 5 in the main recipe. Returns a dict of
    counts and operational metrics.
    """
    # 5a. Write forecast records to DynamoDB. Partition key is
    # unit_id; sort key is forecast_for_ts. This keeps all
    # forecasts for a given unit in one partition for efficient
    # horizon queries (a dashboard fetching the next 12 hours
    # for telemetry is a single Query with a sort-key BETWEEN
    # condition).
    written = 0
    chunk = 25
    for i in range(0, len(forecast_records), chunk):
        batch = forecast_records[i:i + chunk]
        with table.batch_writer() as bw:
            for rec in batch:
                item = {
                    "unit_id":                   rec["unit_id"],
                    "forecast_for_ts":           rec["forecast_for_ts"],
                    "horizon_hours_from_snapshot": _to_decimal(
                                                    rec["horizon_hours_from_snapshot"]),
                    "expected_occupancy":        _to_decimal(rec["expected_occupancy"]),
                    "p10_occupancy":             _to_decimal(rec["p10_occupancy"]),
                    "p50_occupancy":             _to_decimal(rec["p50_occupancy"]),
                    "p90_occupancy":             _to_decimal(rec["p90_occupancy"]),
                    "capacity":                  _to_decimal(rec["capacity"]),
                    "expected_utilization_pct":  _to_decimal(rec["expected_utilization_pct"]),
                    "snapshot_ts":               rec["snapshot_ts"],
                    "generated_at_ts":           rec["generated_at_ts"],
                    "pipeline_version":          rec["pipeline_version"],
                    "inflow_model_version":      rec["inflow_model_version"],
                    "survival_model_version":    rec["survival_model_version"],
                    "assigner_model_version":    rec["assigner_model_version"],
                    "overflow_rules_version":    rec["overflow_rules_version"],
                    "monte_carlo_samples":       _to_decimal(rec["monte_carlo_samples"]),
                    "run_id":                    run_id,
                }
                bw.put_item(Item=item)
                written += 1

    # 5b. Compute the operational signals. The two metrics that
    # operations cares about: predicted-gridlock unit-hours
    # (count of (unit, hour) where p90 occupancy exceeds capacity)
    # and predicted-tight unit-hours (count of (unit, hour) where
    # expected utilization exceeds 90%).
    gridlock_unit_hours = sum(
        1 for r in forecast_records
        if r["p90_occupancy"] > r["capacity"])
    tight_unit_hours = sum(
        1 for r in forecast_records
        if r["expected_utilization_pct"] > 0.90)

    # Per-unit max projected utilization (for the dashboard).
    per_unit_max = defaultdict(float)
    for r in forecast_records:
        if r["expected_utilization_pct"] > per_unit_max[r["unit_id"]]:
            per_unit_max[r["unit_id"]] = r["expected_utilization_pct"]

    # Mean overflow residual per sample. A non-trivial residual
    # means the hospital is projected to truly run out of beds
    # in some samples, even after applying the overflow rules.
    mean_overflow_residual = (
        sum(overflow_residuals) / len(overflow_residuals)
        if overflow_residuals else 0.0)

    # 5c. EventBridge completion event. The payload deliberately
    # carries no PHI: just the run identifier, forecast counts,
    # operational signals, and the pipeline version.
    event_bus.put_events(Entries=[{
        "Source":       "census.forecast",
        "DetailType":   "CensusForecastCycleCompleted",
        "EventBusName": CENSUS_EVENT_BUS_NAME,
        "Time":         datetime.now(timezone.utc),
        "Detail":       json.dumps({
            "run_id":                       run_id,
            "forecast_record_count":        len(forecast_records),
            "gridlock_unit_hours":          gridlock_unit_hours,
            "tight_unit_hours":             tight_unit_hours,
            "mean_overflow_residual":       round(mean_overflow_residual, 3),
            "pipeline_version":             PIPELINE_VERSION,
            "inflow_model_version":         INFLOW_MODEL_VERSION,
            "survival_model_version":       SURVIVAL_MODEL_VERSION,
            "assigner_model_version":       ASSIGNER_MODEL_VERSION,
            "overflow_rules_version":       OVERFLOW_RULES_VERSION,
        }),
    }])

    # 5d. CloudWatch metrics. The two primary operational metrics
    # are gridlock_unit_hours and tight_unit_hours; per-unit max
    # utilization gets emitted as a dimensioned metric so the
    # bed huddle dashboard can graph each unit independently.
    metric_data = [
        {"MetricName": "ForecastUnitHoursGenerated",
         "Value":      float(len(forecast_records)),
         "Unit":       "Count"},
        {"MetricName": "PredictedGridlockUnitHours",
         "Value":      float(gridlock_unit_hours),
         "Unit":       "Count"},
        {"MetricName": "PredictedTightUnitHours",
         "Value":      float(tight_unit_hours),
         "Unit":       "Count"},
        {"MetricName": "MeanOverflowResidual",
         "Value":      float(mean_overflow_residual),
         "Unit":       "Count"},
    ]
    for unit_id, max_util in per_unit_max.items():
        metric_data.append({
            "MetricName": "MaxProjectedUtilization",
            "Value":      float(max_util),
            "Unit":       "Percent",
            "Dimensions": [{"Name": "UnitId", "Value": unit_id}],
        })
    cloudwatch.put_metric_data(
        Namespace=CLOUDWATCH_NAMESPACE,
        MetricData=metric_data)

    logger.info(
        "Delivered: %d forecast records, %d gridlock unit-hours, "
        "%d tight unit-hours, mean overflow residual %.2f",
        written, gridlock_unit_hours, tight_unit_hours,
        mean_overflow_residual)
    return {
        "forecast_records_written":  written,
        "gridlock_unit_hours":       gridlock_unit_hours,
        "tight_unit_hours":          tight_unit_hours,
        "mean_overflow_residual":    mean_overflow_residual,
        "per_unit_max_utilization":  dict(per_unit_max),
    }
```

---

## Full Pipeline

Stitching the steps together. Production runs each step as a separate Step Functions task with retries, error handling, and CloudWatch alarms; the demo runs them sequentially in one process so you can see the data flow.

```python
def run_census_forecast_pipeline(table, event_bus, cloudwatch,
                                 healthlake, s3,
                                 snapshot_ts=None,
                                 horizon_hours=FORECAST_HORIZON_HOURS,
                                 n_samples=DEFAULT_MONTE_CARLO_SAMPLES):
    """End-to-end pipeline orchestration.

    The demo wires up synthetic data; production starts with a
    HealthLake search for the current in-progress encounters and
    pulls the OR schedule, transfer queue, and ED tracking board
    from their respective S3 prefixes (each populated by a
    separate streaming or scheduled ingest job).
    """
    run_id = str(uuid.uuid4())
    print(f"\n=== Hospital Census Forecast Pipeline run_id={run_id} ===\n")

    if snapshot_ts is None:
        snapshot_ts = datetime.now(timezone.utc).replace(
            tzinfo=None, microsecond=0)

    # --- Synthesize inputs (production reads from real services) ---
    inputs = generate_synthetic_inputs(snapshot_ts)
    print(f"[input] {len(inputs['encounters'])} active encounters, "
          f"{len(inputs['or_schedule'])} OR cases, "
          f"{len(inputs['transfer_queue'])} transfers queued, "
          f"{len(inputs['ed_board'])} ED holds")

    # Seed HealthLake with the synthetic encounters so the snapshot
    # step can search for them. Production has the encounters
    # arriving via the ADT stream; the demo loads them once at
    # the top of the pipeline.
    for enc in inputs["encounters"]:
        healthlake.put_encounter(enc)

    # --- Step 1: Snapshot ---
    print("\n[step 1] snapshot_current_state")
    state_records = snapshot_current_state(
        snapshot_ts, healthlake, s3, SNAPSHOT_BUCKET)
    initial_census = current_census_by_unit(state_records)
    print(f"  -> {len(state_records)} encounters captured")
    print(f"  -> initial census: {dict(sorted(initial_census.items()))}")

    # --- Step 2: Forecast inflows ---
    print("\n[step 2] forecast_inflows")
    inflow_models = {
        "ed_admit":     PoissonInflowModel(
            HOURLY_INFLOW_RATES["ed_admit"],
            day_of_week_multipliers={0: 1.15, 6: 0.85}),    # Monday up, Sunday down
        "direct_admit": PoissonInflowModel(
            HOURLY_INFLOW_RATES["direct_admit"],
            day_of_week_multipliers={5: 0.4, 6: 0.3}),     # weekends down
        "transfer_in":  PoissonInflowModel(
            HOURLY_INFLOW_RATES["transfer_in"]),
    }
    unit_assigner = MultinomialUnitAssigner(UNIT_ASSIGNMENT_PROBABILITIES)
    inflow_samples, unit_codes = forecast_inflows(
        snapshot_ts=snapshot_ts,
        horizon_hours=horizon_hours,
        n_samples=n_samples,
        or_schedule=inputs["or_schedule"],
        transfer_queue=inputs["transfer_queue"],
        ed_board=inputs["ed_board"],
        inflow_models=inflow_models,
        unit_assigner=unit_assigner,
        s3=s3, bucket=INFLOW_FORECAST_BUCKET,
        run_id=run_id)
    avg_admits_per_sample = sum(
        sum(sum(h) for h in s) for s in inflow_samples) / n_samples
    print(f"  -> avg admissions per sample over horizon: "
          f"{avg_admits_per_sample:.1f}")

    # --- Step 3: Forecast outflows ---
    print("\n[step 3] forecast_outflows")
    survival_model = ExponentialSurvivalModel(
        service_los_hours=SERVICE_LINE_LOS_HOURS,
        hour_of_day_intensity=HOUR_OF_DAY_DISCHARGE_INTENSITY,
        discharge_order_multiplier=DISCHARGE_ORDER_HAZARD_MULTIPLIER)
    outflow_samples = forecast_outflows(
        state_records=state_records,
        snapshot_ts=snapshot_ts,
        horizon_hours=horizon_hours,
        n_samples=n_samples,
        survival_model=survival_model,
        unit_codes=unit_codes,
        s3=s3, bucket=OUTFLOW_FORECAST_BUCKET,
        run_id=run_id)
    avg_discharges_per_sample = sum(
        sum(sum(h) for h in s) for s in outflow_samples) / n_samples
    print(f"  -> avg discharges per sample over horizon: "
          f"{avg_discharges_per_sample:.1f}")

    # --- Step 4: Compose ---
    print("\n[step 4] compose_census")
    forecast_records, overflow_residuals = compose_census(
        state_records=state_records,
        inflow_samples=inflow_samples,
        outflow_samples=outflow_samples,
        unit_codes=unit_codes,
        snapshot_ts=snapshot_ts,
        horizon_hours=horizon_hours,
        s3=s3, bucket=SAMPLE_TRAJECTORY_BUCKET,
        run_id=run_id)
    print(f"  -> generated {len(forecast_records)} forecast records "
          f"({horizon_hours} hours x {len(unit_codes)} units)")

    # --- Step 5: Deliver ---
    print("\n[step 5] deliver_forecast")
    delivery = deliver_forecast(
        forecast_records=forecast_records,
        overflow_residuals=overflow_residuals,
        table=table, event_bus=event_bus, cloudwatch=cloudwatch,
        run_id=run_id)
    print(f"  -> wrote {delivery['forecast_records_written']} "
          f"forecasts to DynamoDB")
    print(f"  -> {delivery['gridlock_unit_hours']} gridlock unit-hours, "
          f"{delivery['tight_unit_hours']} tight unit-hours")
    print(f"  -> emitted {len(event_bus.events)} EventBridge events")
    print(f"  -> emitted CloudWatch metrics: "
          f"{sorted(cloudwatch.metrics.keys())}")

    return forecast_records, delivery

def run_demo():
    """Run the pipeline end-to-end against the in-memory mocks.

    No AWS resources are touched; every external dependency is
    a mock. Useful for sanity-checking the snapshot, inflow,
    outflow, and composition logic before wiring to real services.
    """
    table       = MockTable(CENSUS_FORECAST_TABLE)
    event_bus   = MockEventBus(CENSUS_EVENT_BUS_NAME)
    cloudwatch  = MockCloudWatch()
    healthlake  = MockHealthLake()
    s3          = MockS3()

    forecast_records, delivery = run_census_forecast_pipeline(
        table, event_bus, cloudwatch, healthlake, s3)

    # Pretty-print the next-8-hours forecast for each unit, the
    # most operationally interesting horizon for the bed huddle.
    print("\n=== Forecast at hour 8 (operationally relevant for bed huddle) ===")
    print(f"{'Unit':<14} {'Cap':>5} {'Exp':>6} {'p10':>5} {'p50':>5} "
          f"{'p90':>5} {'Util%':>6}")
    for r in forecast_records:
        if r["horizon_hours_from_snapshot"] != 8:
            continue
        util_pct = r["expected_utilization_pct"] * 100.0
        print(f"{r['unit_id']:<14} "
              f"{r['capacity']:>5} "
              f"{r['expected_occupancy']:>6.1f} "
              f"{r['p10_occupancy']:>5.1f} "
              f"{r['p50_occupancy']:>5.1f} "
              f"{r['p90_occupancy']:>5.1f} "
              f"{util_pct:>5.1f}%")

    # Sample DynamoDB record for inspection.
    if forecast_records:
        sample_pk = forecast_records[0]["unit_id"]
        sample_sk = forecast_records[0]["forecast_for_ts"]
        ddb_view = table.items.get((sample_pk, sample_sk))
        print("\n=== Sample DynamoDB record ===")

        def _decimalify(o):
            if isinstance(o, Decimal):
                return str(o)
            if isinstance(o, datetime):
                return o.isoformat()
            return o
        print(json.dumps(ddb_view, default=_decimalify, indent=2))

    print("\n=== Operational signals ===")
    print(f"  gridlock_unit_hours:    {delivery['gridlock_unit_hours']}")
    print(f"  tight_unit_hours:       {delivery['tight_unit_hours']}")
    print(f"  mean_overflow_residual: "
          f"{delivery['mean_overflow_residual']:.2f}")
    print(f"  per_unit_max_util:      "
          f"{ {u: f'{v*100:.1f}%' for u, v in delivery['per_unit_max_utilization'].items()} }")

    return forecast_records, delivery

if __name__ == "__main__":
    run_demo()
```

---

## Sample Output

Running the demo against the in-memory mocks produces output like this. Numbers vary because of the synthetic-data noise but the structure of the forecast, the operational signals, and the DynamoDB record shape are deterministic given the seed.

```text
=== Hospital Census Forecast Pipeline run_id=8f3a... ===

[input] 97 active encounters, 6 OR cases, 2 transfers queued, 3 ED holds

[step 1] snapshot_current_state
  -> 97 encounters captured
  -> initial census: {'ed-hold': 8, 'medsurg-4-w': 31, 'ortho-5-n': 20, 'stepdown-icu': 14, 'tele-3-east': 24}

[step 2] forecast_inflows
  -> avg admissions per sample over horizon: ~32

[step 3] forecast_outflows
  -> avg discharges per sample over horizon: ~28

[step 4] compose_census
  -> generated 120 forecast records (24 hours x 5 units)

[step 5] deliver_forecast
  -> wrote 120 forecasts to DynamoDB
  -> N gridlock unit-hours, M tight unit-hours
  -> emitted 1 EventBridge events
  -> emitted CloudWatch metrics: ['HospitalCensusForecast/ForecastUnitHoursGenerated',
       'HospitalCensusForecast/MaxProjectedUtilization',
       'HospitalCensusForecast/MeanOverflowResidual',
       'HospitalCensusForecast/PredictedGridlockUnitHours',
       'HospitalCensusForecast/PredictedTightUnitHours']

=== Forecast at hour 8 (operationally relevant for bed huddle) ===
Unit             Cap    Exp   p10   p50   p90  Util%
ed-hold           12    6.5   4.0   6.0   9.0  54.2%
medsurg-4-w       36   30.4  27.0  30.0  34.0  84.5%
ortho-5-n         24   20.8  18.0  21.0  23.0  86.7%
stepdown-icu      16   14.1  12.0  14.0  16.0  88.1%
tele-3-east       28   25.6  22.0  26.0  29.0  91.4%

=== Sample DynamoDB record ===
{
  "unit_id": "tele-3-east",
  "forecast_for_ts": "2026-05-25T07:00:00",
  "horizon_hours_from_snapshot": "1",
  "expected_occupancy": "24.3",
  "p10_occupancy": "22.0",
  "p50_occupancy": "24.0",
  "p90_occupancy": "27.0",
  "capacity": "28",
  "expected_utilization_pct": "0.8679",
  ...
}

=== Operational signals ===
  gridlock_unit_hours:    N
  tight_unit_hours:       M
  mean_overflow_residual: 0.X
  per_unit_max_util:      {'ed-hold': '...', 'tele-3-east': '...', ...}
```

A real pipeline against a single hospital with 5 to 30 units, 200 to 600 active encounters, and 500 to 1000 Monte Carlo samples runs the inference cycle in tens of seconds on a small Lambda or AWS Batch job, produces the same shape of output, and writes the records straight to a real DynamoDB table that the bed huddle dashboard queries every few seconds.

---

## Gap to Production

The demo is intentionally a sketch. Here is the distance between this code and something you would deploy.

**Real statistical libraries, not demo helpers.** The `PoissonInflowModel`, `ExponentialSurvivalModel`, and `MultinomialUnitAssigner` in this file are pedagogical stand-ins. Production replaces `PoissonInflowModel` with a [statsmodels GLM with the Poisson family](https://www.statsmodels.org/stable/glm.html) trained on calendar features (hour of day, day of week, month), weather features (temperature, precipitation), holidays, and current-state features (ED census, ED holds). For multi-hospital health systems, replace per-source Poisson regressors with [SageMaker DeepAR](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html) or the [Chronos foundation model](https://github.com/amazon-science/chronos-forecasting) so the inflow forecasts learn jointly across sites. Replace `ExponentialSurvivalModel` with a Cox proportional hazards model from [lifelines](https://lifelines.readthedocs.io/) when the per-patient feature set is small, an XGBoost survival model from [XGBSE](https://github.com/loft-br/xgboost-survival-embeddings) when the feature set is rich and tabular, or a deep survival model like DeepHit from [PySurvival](https://square.github.io/pysurvival/) when the feature set includes embeddings or sequential signals. Replace `MultinomialUnitAssigner` with [scikit-learn `LogisticRegression(multi_class='multinomial')`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html) for a small feature set or the [SageMaker XGBoost built-in algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/xgboost.html) when the assignment depends on dozens of features. The demo's models produce sensible-looking samples; they are not calibrated against any real hospital's data.

**Real HealthLake datastore, not MockHealthLake.** Replace `MockHealthLake` with `boto3.client('healthlake')` calls. Production creates the FHIR datastore once with KMS encryption at creation time, ingests HL7 ADT messages via the [HealthLake Import API](https://docs.aws.amazon.com/healthlake/latest/devguide/import-fhir-data.html), and queries Encounters via the [HealthLake Search API](https://docs.aws.amazon.com/healthlake/latest/APIReference/API_SearchWithGet.html) or the FHIR REST API directly. The snapshot Glue job uses an `Encounter?status=in-progress&_lastUpdated=ge{since}` query against the datastore on a 15-to-60-minute cadence. For very large hospitals or systems where the FHIR-search latency matters, an alternative is to mirror Encounter resources to a Glue Data Catalog table backed by Iceberg on S3 and query that table directly.

**Real S3 prefixes, not MockS3.** Replace `MockS3` with `boto3.client('s3')` calls. Production has separate prefixes for each pipeline output (snapshots, inflow forecasts, outflow forecasts, sample trajectories, model artifacts, and the historical forecast records used for backtesting), all encrypted with the same customer-managed KMS key. The snapshot prefix is partitioned by date and hour; the trajectory prefix is partitioned by `run_id` so a single run's output is contiguous in S3 for after-the-fact analysis. Object-level retention policies match the institutional retention floor (typically seven years for clinical operational records).

**Real Glue ETL for the snapshot and feature-engineering steps.** The `snapshot_current_state` function loops over a Python list. Production runs the snapshot as an AWS Glue PySpark job that reads new HealthLake encounters on a 15-to-60-minute cadence, joins them with the EHR's encounter-class and discharge-order data, applies the timestamp reconciliation (this is where the unglamorous data-quality work lives), and writes the per-patient feature records partitioned by date and hour. The Glue job uses a service role with scoped HealthLake, S3, and KMS permissions.

**Real SageMaker endpoints, not in-process models.** The pipeline calls the model classes directly. Production hosts the inflow Poisson regressors as a SageMaker multi-model endpoint (one model per source, routed by a Lambda that reads the source from the request payload), the survival model as a separate SageMaker endpoint, and the unit-assignment classifier as a third endpoint. All three endpoints run in a private VPC subnet with VPC endpoints to S3, KMS, and CloudWatch Logs. Model packages are promoted via the SageMaker Model Registry with manual approval, and a shadow-deployment step runs the new model in parallel with the production model for at least a week before cutting traffic over.

**Real Lambda or AWS Batch for the Monte Carlo composition.** The `compose_census` function runs in process. Production wraps the composition logic in an AWS Lambda function for hospitals where the per-cycle compute fits in Lambda's memory and timeout limits, or in AWS Batch with a small EC2 fleet for larger hospitals where 1000 samples across 30 units exceeds Lambda's 15-minute timeout. The Lambda or Batch job reads the snapshot, the inflow samples, and the outflow samples from S3, runs the composition, writes the per-unit forecasts to DynamoDB, writes the sample trajectories to S3, and emits CloudWatch metrics.

**Real DynamoDB, not MockTable.** Replace `MockTable` with `boto3.resource('dynamodb').Table(CENSUS_FORECAST_TABLE)`. The table needs a partition key (`unit_id`, type S), a sort key (`forecast_for_ts`, type S), encryption-at-rest with a customer-managed KMS key, point-in-time recovery enabled, on-demand billing for the unpredictable load that comes with multi-hospital rollouts (or provisioned with auto-scaling for predictable single-hospital load), an item-level TTL on the historical forecasts so the table does not grow unbounded, and a global secondary index on `(snapshot_ts, unit_id)` if backtest queries scan by snapshot rather than by unit. Also handle the `BatchWriteItem` `UnprocessedItems` response with exponential backoff; `MockTable` ignores this case but DynamoDB returns unprocessed items under throttling.

**Real Step Functions orchestration.** The pipeline-orchestration logic (snapshot -> inflow -> outflow -> compose -> deliver) runs as an AWS Step Functions state machine in production. Each step is a Glue job, a Lambda, or a SageMaker invocation, with `Retry` and `Catch` blocks for transient failures, a parallel branch for the inflow and outflow steps (they are independent given the snapshot and can run concurrently), and an EventBridge schedule that fires every 15 to 60 minutes. The state machine emits `ExecutionFailed` events to a CloudWatch alarm so on-call gets paged when a cycle fails.

**Real EventBridge bus and CloudWatch alarms.** The `MockEventBus` and `MockCloudWatch` accumulate events and metrics in process. Production uses real `boto3.client('events').put_events(...)` and `boto3.client('cloudwatch').put_metric_data(...)`, plus CloudWatch alarms on per-horizon forecast accuracy (alarm if MAPE on the rolling backtest window exceeds the calibrated threshold, which is the leading indicator of a model that has drifted), pipeline-execution latency, DynamoDB write throttling, SageMaker endpoint 5xx rate, and gridlock-unit-hour spikes (alarm if predicted-gridlock unit-hours exceed the operational tolerance, which is what the bed huddle most wants to react to). The alarms feed an SNS topic that pages the on-call ML engineer.

**ADT timestamp reconciliation.** The single biggest source of subtle bugs in a real census pipeline is the ADT timestamp data. Discharge timestamps that fire when the order is entered rather than when the patient leaves. Transfer timestamps that reflect the bed assignment rather than the actual move. ADT messages dropped or arriving out of order. ADT events that conflict with the EHR's location field. The demo assumes clean timestamps; production runs a continuous data-quality monitoring layer that checks for distribution shifts in the ADT stream, alarms when timestamps look implausible, and reconciles ADT against secondary signals (bed-cleaning logs, telemetry-lead-attached events, EHR location updates).

**Discharge-order timing model.** The single biggest improvement to the forecast is a model that predicts when a discharge order will be entered, rather than just whether one has been entered. The demo's survival model uses the binary "discharge order entered" flag. Production trains a separate discharge-order-timing model on attending-rounding patterns, hospitalist workflow, and prior-day discharge patterns, and uses the predicted order timestamp as a feature in the main survival model. This compositional approach gets the next-six-hours discharge probability much closer to right for patients without orders.

**Real bed-management overflow rules.** The `OVERFLOW_RULES` table in the demo is a static priority list per unit. Real hospitals have much richer overflow rules (telemetry overflows to step-down with a downgrade order but only if the receiving unit has the right monitoring equipment; ortho post-ops can overflow to general surgery but not to medicine; ICU step-down overflows have to consider nursing ratios). Production reads overflow logic from a configuration store the bed-management team owns and updates as protocols change. The pipeline reads this configuration; it does not hardcode the rules.

**Service-line and DRG drift detection.** Service lines and DRG categories shift over time as case mix changes. A hospital that opens a new joint-replacement program changes the post-op admission distribution. Models trained on six-month-old data may forecast against a different reality than the current one. Production implements explicit drift detection on the feature distributions (LOS by service line, admit rate by source, discharge timing by attending) and triggers retraining when drift exceeds a threshold rather than relying solely on a calendar cadence. The drift detector is itself a SageMaker Model Monitor or a custom Lambda that runs on a daily schedule.

**Multi-hospital health-system rollouts.** A health system with five hospitals has both an opportunity and a complication. The opportunity: shared models trained jointly across hospitals (DeepAR or hierarchical Bayesian models) borrow strength across small-volume units and produce better forecasts at every site. The complication: each hospital has its own bed map, its own overflow rules, its own data quality issues, and its own operational practices. Production multi-hospital deployments use a layered approach: shared inflow and outflow models trained jointly with a per-hospital embedding, hospital-specific unit-assignment classifiers, hospital-specific overflow logic, and hospital-specific feedback loops.

**Operational integration is the hard part.** A forecast that nobody acts on is operational decoration. Real production deployments invest as much engineering in the consumer-facing tools (the bed huddle dashboard, the transfer center decision support, the OR scheduler integration, the ED diversion tool) as they do in the forecasting pipeline. Each consumer has different latency requirements, different visualization needs, and different feedback paths. The forecast repository is the single source of truth, but the consumers are where adoption happens or fails. Plan to spend at least as much time on the dashboard as on the model.

**Continuous calibration and feedback capture.** Every forecast cycle should write its predictions to a calibration store, and every realized outcome should be matched back to its prediction. The continuous comparison produces accuracy metrics by horizon, by unit, by service line, by hour-of-day, and by day-of-week. The demo has no calibration loop; production builds one on day one (an hourly Lambda that joins the previous day's forecasts against the realized census from ADT). Drift in any of the accuracy dimensions is a signal to retrain or to investigate.

**Bedrock narrative summaries (optional).** The bed huddle wants a one-paragraph summary of the day's projected pressure points: "Expected to hit 92% telemetry occupancy by 14:00, driven by 6 ED admits already pending and 3 elective cardiac procedures with anticipated tele admits. Discharge volume projected at 36, with peak between 13:00 and 15:00. Recommend prioritizing 4 medically-ready discharges currently held for SNF placement to free capacity before the 13:00 OR turnover." Generating that text from the structured forecast is a Bedrock invocation. The prompt construction is PHI-adjacent (per-patient counts, clinical states), so the model invocation, the prompt logging, and the output storage all need to be in the BAA-covered, KMS-encrypted, VPC-restricted boundary.

**EHR integration via CDS Hooks or FHIR Subscriptions.** The DynamoDB-backed surface is fine for a bed huddle dashboard or a transfer center decision support. For in-workflow CDS (a popup in the OR scheduler when a clinician tries to book an elective case on a day with projected gridlock), the pipeline needs a [CDS Hooks](https://cds-hooks.org/) responder fronted by API Gateway and Lambda, exposed to the EHR vendor's CDS client. The integration is highly EHR-vendor-specific; budget more time than the engineering estimate suggests.

**Idempotency and rerun safety.** The forecast pipeline can fail and need to be rerun. Each step needs to be safe to repeat: snapshot is idempotent on `snapshot_ts`; inflow inference is deterministic given inputs (use a fixed seed for the Monte Carlo sampler when reproducibility matters and a content-derived seed when run-to-run variability matters); outflow inference is deterministic given inputs; DynamoDB writes overwrite cleanly by primary key. The demo achieves this naturally because the pure-Python helpers do not retain state across runs; production has to be deliberate about each step's idempotency contract.

**HIPAA controls end-to-end.** The HealthLake datastore uses encryption with a customer-managed KMS key; the S3 prefixes use SSE-KMS with the same key family; the DynamoDB table uses encryption-at-rest with a customer-managed key; SageMaker training and inference jobs run in a VPC with VPC endpoints to S3, HealthLake, CloudWatch Logs, and KMS; the Glue job reads and writes only encrypted data; CloudTrail logs all HealthLake, S3, DynamoDB, Glue, and SageMaker API calls; CloudWatch log groups are KMS-encrypted; IAM roles are scoped to specific resource ARNs; an AWS BAA is in place. The demo touches none of this; production cannot ship without all of it.

**Audit trail.** Each pipeline run is identified by a `run_id`, all forecast records carry that run_id and the model + rule versions, the DynamoDB writes overwrite cleanly by the `(unit_id, forecast_for_ts)` key, and the model-artifact S3 writes use deterministic prefixes so a rerun produces the same output. An immutable audit log captures which rule version produced which forecast on which cycle, written through Kinesis Data Firehose into an Object-Lock S3 bucket sized to the institutional retention floor.

**Testing.** Unit tests cover the snapshot function (a known set of encounters produces the expected per-unit census), the inflow Poisson sampler (large-N samples converge to the expected rate), the survival model (a constant-rate input produces a near-flat hazard, a known-LOS input produces the expected median discharge time), the unit assigner (large-N samples converge to the expected probability distribution), the composition step (with zero inflows and zero outflows, the trajectory is constant; with known inflows and zero outflows, the trajectory grows by exactly the expected amount; the overflow rules redistribute the right number of patients to the right units), and the DynamoDB write idempotency (writing the same record twice is a no-op). Integration tests run the pipeline against a known-input synthetic dataset and assert the forecasts and the operational signals against expected values. End-to-end tests stand up real HealthLake, S3, DynamoDB, and EventBridge resources in a sandbox account and run the full Step Functions state machine.

**Structured logging.** Replace the demo's `print` calls with `logger.info(..., extra={...})` calls that emit JSON-formatted structured logs to CloudWatch Logs. Log structural metadata only (run_id, snapshot_ts, unit_id, sample_count, runtime_ms), never patient identifiers, never raw working DRGs, never the per-encounter feature vectors that include PHI by reference.

**Regulatory framing.** Hospital census forecasting that informs operational decisions sits well within the operational software boundary and is not regulated as a medical device. A pipeline that informs individual patient care decisions ("this patient should be discharged today because the model predicts a discharge in the next 6 hours") edges closer to clinical decision support territory. Production deployments are careful to frame outputs as operational ("the unit is projected to be 94% occupied by 14:00") rather than clinical ("patient X should be discharged"), and to keep the patient-level discharge probabilities as inputs to the unit-level forecast rather than surfaces consumed by clinicians making care decisions about specific patients.

**The shape of the gap.** The forecasting math in this file is a sketch but it is fundamentally correct. The plumbing around it (storage, orchestration, security, ADT timestamp reconciliation, discharge-order timing model, real overflow rules, service-line drift detection, operational integration, feedback capture, EHR integration, regulatory framing) is what takes the bulk of the engineering work. Plan for the plumbing to be 80% of the project; the forecasting math itself routinely surprises teams by being the easier part.

---

## Related Resources

- [Recipe 12.5: Hospital Census Forecasting](chapter12.05-hospital-census-forecasting): The main recipe with the full architectural walkthrough this Python companion implements.
- [Amazon HealthLake Documentation](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html): The FHIR datastore that backs the longitudinal patient timeline. ADT events surface as FHIR Encounter resources.
- [statsmodels GLM with the Poisson family](https://www.statsmodels.org/stable/glm.html): Production-grade Poisson regression. Drop-in replacement for the demo's `PoissonInflowModel`.
- [SageMaker DeepAR built-in algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html): Probabilistic time-series forecasting that learns jointly across many series; a good fit for multi-hospital health systems.
- [Chronos foundation model](https://github.com/amazon-science/chronos-forecasting): A foundation model for time-series forecasting, useful when the per-hospital training data is thin and a pretrained model can carry calendar and seasonal patterns.
- [lifelines](https://lifelines.readthedocs.io/): Survival analysis library with Cox proportional hazards and Kaplan-Meier estimators. Drop-in replacement for the demo's `ExponentialSurvivalModel` when the feature set is small.
- [XGBoost Survival Embeddings (XGBSE)](https://github.com/loft-br/xgboost-survival-embeddings): Gradient-boosted survival model with calibrated probability outputs. Drop-in replacement for the demo's survival model when the feature set is rich and tabular.
- [PySurvival](https://square.github.io/pysurvival/): Deep-learning-based survival models including DeepHit, useful when the per-patient feature set includes embeddings or sequential signals.
- [SageMaker XGBoost built-in algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/xgboost.html): Drop-in replacement for the demo's `MultinomialUnitAssigner` when the assignment depends on dozens of features.
- [scikit-learn LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html): Multinomial logistic regression for the unit-assignment classifier when the feature set is small.
- [HL7 ADT Message Specification](https://www.hl7.org/implement/standards/product_brief.cfm?product_id=185): The standard for admission, discharge, transfer messages used as the primary data input.
- [FHIR Encounter Resource](https://www.hl7.org/fhir/encounter.html): The FHIR equivalent for hospital encounters; the canonical model in HealthLake.
- [MIMIC-IV on PhysioNet](https://physionet.org/content/mimiciv/): De-identified ICU and hospital data for credentialed researchers, including encounter histories suitable for census reconstruction and survival model training.
- [Synthea Synthetic Patient Generator](https://github.com/synthetichealth/synthea): Realistic synthetic FHIR Encounter resources including admission and discharge events. Useful for development environments where real PHI is off limits.
- [Forecasting: Principles and Practice (Hyndman & Athanasopoulos)](https://otexts.com/fpp3/): Free online textbook with strong chapters on hierarchical forecasting and intermittent demand, both relevant for multi-hospital and per-unit census forecasting.
- [CDS Hooks Specification](https://cds-hooks.org/): The standard for in-EHR clinical decision support; the right interface for surfacing census-driven booking warnings to the OR scheduler.
- [AWS Step Functions Map State](https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-map-state.html): Pattern for fanning out per-patient survival inference in parallel.

---

*← [Recipe 12.5: Hospital Census Forecasting](chapter12.05-hospital-census-forecasting) · [Chapter 12 Index](chapter12-preface) · [Next: Recipe 12.6 - Revenue Cycle Cash Flow Forecasting →](chapter12.06-revenue-cycle-cash-flow-forecasting)*
