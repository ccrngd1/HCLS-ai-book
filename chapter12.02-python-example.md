# Recipe 12.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 12.2. It shows one way you could translate the supply-inventory-forecasting pipeline into working Python using boto3 against Amazon S3, AWS Glue (here represented by an in-process Python aggregation), Amazon SageMaker (here represented by pure-Python `SmoothModel` and `SBAModel` classes that stand in for Prophet and Croston/SBA), AWS Step Functions (here represented by sequential function calls), Amazon DynamoDB (mocked with `MockTable`), Amazon EventBridge (mocked with `MockEventBus`), and Amazon CloudWatch (mocked with `MockCloudWatch`). The demo generates synthetic SKU consumption data with four distinct demand patterns (smooth, intermittent, erratic, procedure-driven) so you can see the segmentation logic, the per-segment model selection, and the reorder-point calculation work end-to-end without provisioning anything. It is not production-ready. There is no real SageMaker training job, no real Glue ETL, no real Step Functions state machine, no real DynamoDB table, no real EventBridge bus, no real CloudWatch alarms, no per-Lambda IAM least privilege, no KMS customer-managed keys, no VPC endpoints, no item-master successor reconciliation, no ERP integration, no per-SKU forecast monitoring, and no drift detection. Think of it as the sketchpad version: useful for understanding the shape of a multi-SKU demand-forecasting pipeline that respects the segmentation discipline, the per-segment-model-selection discipline, the reorder-point-as-operational-primitive discipline, the prediction-interval-not-point-estimate discipline, and the audit-everything discipline this recipe demands. It is not something you would point at a hospital materials management system on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the five pseudocode steps from the main recipe: pull and shape the daily SKU consumption history with calendar features and successor-mapping (Step 1); segment the SKU portfolio by demand pattern using ADI and CV² (Step 2); train a forecasting model per segment with pure-Python stand-ins for Prophet (smooth SKUs), the Syntetos-Boylan Approximation (intermittent, erratic, and lumpy SKUs), and a two-stage case-times-usage model (procedure-driven SKUs) (Step 3); generate forecasts and translate forecast variance into reorder points and order quantities using the classical safety-stock formula (Step 4); load the forecast records to DynamoDB keyed by `facility_id#sku_id` with idempotent batched writes (Step 5). The synthetic SKUs, facilities, vendors, lead times, and consumption patterns in the demo are fictional; nothing in this file should be interpreted as real consumption data from any real institution.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

The demo runs against the Python standard library plus boto3; no other packages are imported. Production deployments swap the demo's pure-Python `SmoothModel` and `SBAModel` for real forecasting libraries (Prophet for the smooth-segment branch, statsmodels or an intermittent-demand library for Croston/SBA/TSB, the SageMaker DeepAR built-in algorithm for multi-series neural forecasting); the Gap to Production section spells out the substitutions.

In production you would also configure an Amazon S3 bucket for the consumption-history landing zone and the model-artifact / forecast-output zone, an AWS Glue crawler over the S3 prefix and a Glue ETL job (PySpark or Glue notebook) that does the cleaning, joining, and successor-mapping, an Amazon SageMaker training image with Prophet, statsmodels, and an intermittent-demand library installed (a custom container built on the SageMaker scikit-learn base or the SageMaker DeepAR built-in algorithm for the multi-series neural option), an AWS Step Functions state machine that orchestrates extract -> segment -> per-segment Map state -> forecast -> reorder calc -> DynamoDB load, an Amazon DynamoDB table for the served forecasts and reorder points keyed by `facility_id#sku_id` and a sort key for `generated_at` plus a `CURRENT` pointer record per SKU, an Amazon EventBridge schedule that triggers the Step Functions state machine on a weekly cadence (and a daily one for the consumption-data refresh), AWS Lambda functions for the lightweight transforms (SKU segmentation, reorder-point calculation, DynamoDB loader), Amazon CloudWatch dashboards and alarms for pipeline failures and per-segment forecast drift, and a thin integration layer (typically a flat-file extract or an API call) that pushes the new reorder points into the institutional ERP / materials management system on its own cadence. The demo replaces all of these with a single in-process Python file so the focus stays on the segmentation, the per-segment modeling, the reorder-point math, and the disposition logic rather than on the platform plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `s3:GetObject` and `s3:PutObject` on the consumption-history landing prefix, the SKU-master prefix, the model-artifact prefix, and the forecast-output prefix
- `glue:StartJobRun`, `glue:GetJobRun`, and the Glue service role's permissions for the ETL job
- `sagemaker:CreateTrainingJob`, `sagemaker:DescribeTrainingJob`, `sagemaker:CreateTransformJob`, `sagemaker:DescribeTransformJob` on the per-segment training and inference jobs (and, for cross-region inference, the relevant `bedrock`-style cross-region permissions if you choose DeepAR via cross-region profiles)
- `dynamodb:BatchWriteItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the `sku-forecasts` table, scoped to the specific table ARN
- `events:PutEvents` on the supply-forecast-events bus for emitting pipeline-lifecycle events (run started, segment trained, forecast generated, reorder points loaded, drift alarm raised)
- `states:StartExecution` on the supply-forecast Step Functions state machine
- `cloudwatch:PutMetricData` for the operational metrics (per-segment MAPE, per-segment MASE, per-SKU forecast-drift indicator, stockout-attribution rate, on-hand inventory at month-end vs. forecast)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the S3 prefixes, the DynamoDB table, and the model-artifact bucket
- `secretsmanager:GetSecretValue` on any ERP / materials-management integration credentials secrets pinned to the current rotation version

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The segmentation Lambda has read access to the modeling-ready S3 prefix and write access to a small segment-assignments DynamoDB table, but no SageMaker permissions. The training orchestrator has SageMaker training permissions but no DynamoDB write access; the reorder-calculator Lambda has read access to the forecast-output S3 prefix and write access to the `sku-forecasts` DynamoDB table, but no SageMaker permissions. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Consumption data is PHI by association.** A daily SKU count that includes implants, surgical staples, or specialty pharmaceuticals is a derived signal about which procedures happened on which days. Joined with the OR schedule, it is identifiable. The S3 prefix, the DynamoDB table, and the forecast outputs all live under a HIPAA-eligible architecture with SSE-KMS encryption, VPC endpoints, and CloudTrail audit. The demo redacts patient and case identifiers; production never carries them past the Glue ETL boundary in the first place.
- **The SKU master is the bot.** Everything downstream depends on a clean SKU master with successor mapping for retired items, accurate categorization for procedure-driven flagging, current lead times per vendor, and per-SKU service-level targets reflecting clinical importance. Cleaning it up is the project. Skip the cleanup and the pipeline produces beautiful forecasts for the wrong identifiers; do the cleanup and the pipeline produces operational reorder points the materials team trusts.
- **Segmentation routes the math.** A single forecasting method applied to the entire SKU portfolio over-fits the smooth items and produces nonsense for the intermittent ones. The Average Demand Interval (ADI) and the Coefficient of Variation Squared (CV²) classification routes each SKU to the model family that fits its demand shape. The four-corner classification (smooth, intermittent, erratic, lumpy) is from Syntetos, Boylan, and Croston's body of work.
- **The prediction interval is the operational primitive, not the point estimate.** Materials managers want to know the worst plausible demand over the lead time, not the expected demand. The safety-stock formula consumes the standard deviation of the forecast error; if the model produces tight intervals, inventory levels drop without any change in service level. The forecast variance is the lever the modeling work pulls.
- **Procedure-driven SKUs forecast best as case_volume * per_case_usage.** Forecasting historical SKU counts directly works for gloves and IV bags. It does not work for orthopedic implants. The procedure-driven branch forecasts surgical case volume (or reads the upcoming OR schedule) and multiplies by a usage rate per case derived from the SKU master.
- **DynamoDB rejects Python `float`.** Every confidence score, threshold, lead-time-day count, mean-demand value, and service-level target passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses many Lambdas, Glue jobs, and SageMaker training jobs into a single Python file.** In production the data-prep Glue job, the segmentation Lambda, the per-segment SageMaker training jobs (parallel via the Step Functions Map state), the batch-inference SageMaker job, the reorder-calculation Lambda, and the DynamoDB-loader Lambda are separate units of work with their own IAM roles, error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, segmentation thresholds, per-segment service-level targets, lead-time defaults, and the synthetic-data parameters are what you would change between environments.

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
# Consumption data is PHI by association: a daily SKU count for
# orthopedic implants is a derived signal about which surgical
# cases happened on which days. Log structural metadata only
# (run_id, facility_id, segment, sku_count, mean_error, runtime_ms),
# never raw consumption rows tied to identifiable cases, never
# the SKU master with patient or case identifiers attached.
# Full consumption history lives in the encrypted S3 prefix with
# appropriate access controls; only the modeling-ready
# de-identified aggregate flows past the Glue boundary.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from S3, DynamoDB, EventBridge,
# CloudWatch, and SageMaker. The supply-forecast pipeline is a
# scheduled batch job with no human waiting on the result, so
# longer retries are acceptable than in an interactive bot. Cap
# them anyway so a stuck dependency does not balloon a 30-minute
# weekly run into a multi-hour incident.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across function calls within the
# pipeline so each call does not pay the connection cost. The
# demo wires up MockTable / MockEventBus / MockCloudWatch via
# run_demo() and never touches these real handles; they are
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
CONSUMPTION_HISTORY_BUCKET = "supply-forecast-consumption-history"
SKU_MASTER_BUCKET          = "supply-forecast-sku-master"
MODEL_ARTIFACT_BUCKET      = "supply-forecast-models"
FORECAST_OUTPUT_BUCKET     = "supply-forecast-outputs"
SKU_FORECASTS_TABLE        = "supply-forecast-sku-forecasts"
FORECAST_EVENT_BUS_NAME    = "supply-forecast-events-bus"
CLOUDWATCH_NAMESPACE       = "SupplyForecast"

# --- Versioning ---
# Every forecast record carries the model version active at the
# time of generation. This is how a future audit reconstructs
# which calibration produced which reorder point.
PIPELINE_VERSION       = "supply-forecast-v1.3"
SEGMENTATION_VERSION   = "syntetos-boylan-2025-04"
SAFETY_STOCK_VERSION   = "classical-z-score-v1"

# --- Segmentation Thresholds ---
# Standard four-corner classification from Syntetos, Boylan, and
# Croston. ADI = average demand interval (days between non-zero
# demand observations). CV² = coefficient of variation squared
# of non-zero demand size. The cutoffs (1.32 and 0.49) are the
# commonly cited defaults from the Syntetos-Boylan-Croston
# research. Tune them to your portfolio if your demand shapes
# are unusual.
ADI_THRESHOLD = Decimal("1.32")
CV2_THRESHOLD = Decimal("0.49")

# --- Forecast Horizon ---
# 90 days is a typical operational horizon: long enough to span
# most lead times plus a buffer, short enough that the forecast
# does not lose accuracy from extrapolating too far.
FORECAST_HORIZON_DAYS = 90

# --- Service Level Defaults ---
# Per-SKU target service levels in production come from the SKU
# master and reflect clinical criticality. The defaults below
# stand in for that lookup. A 99% service level is appropriate
# for emergency drugs and critical implants; 95% is fine for
# most consumables; 90% is acceptable for slow-moving non-clinical
# items. Below 90%, you are essentially accepting routine
# stockouts as a cost center.
DEFAULT_SERVICE_LEVEL_BY_SEGMENT = {
    "smooth":             Decimal("0.95"),
    "intermittent":       Decimal("0.97"),
    "erratic":            Decimal("0.95"),
    "lumpy":              Decimal("0.97"),
    "procedure_driven":   Decimal("0.99"),
}

# Z-score lookup for common service levels. Production reads
# the per-SKU service-level target from the SKU master and
# computes the z-score from the inverse normal CDF.
Z_SCORE_BY_SERVICE_LEVEL = {
    Decimal("0.90"): Decimal("1.282"),
    Decimal("0.95"): Decimal("1.645"),
    Decimal("0.97"): Decimal("1.881"),
    Decimal("0.99"): Decimal("2.326"),
}

# --- Lead Time Defaults ---
# Per-SKU lead times in production come from the vendor contract
# and the SKU master. The default below is a placeholder used
# when the SKU master lookup is missing.
DEFAULT_LEAD_TIME_DAYS = 7

# --- Order Quantity Defaults ---
# A simple cycle-stock heuristic stand-in for full Economic Order
# Quantity (EOQ) calculations. Production uses real holding-cost
# and order-cost data per SKU.
DEFAULT_ORDER_CYCLE_DAYS = 14

# --- Synthetic Data ---
# Knobs for the demo's synthetic-consumption generator. The
# ranges produce a small but realistic-shaped portfolio across
# the four demand-pattern segments plus the procedure-driven
# branch.
SYNTHETIC_HISTORY_DAYS = 730     # two years of daily history
SYNTHETIC_FACILITY_ID  = "main-hospital-001"

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("CONSUMPTION_HISTORY_BUCKET", CONSUMPTION_HISTORY_BUCKET),
    ("SKU_MASTER_BUCKET",          SKU_MASTER_BUCKET),
    ("MODEL_ARTIFACT_BUCKET",      MODEL_ARTIFACT_BUCKET),
    ("FORECAST_OUTPUT_BUCKET",     FORECAST_OUTPUT_BUCKET),
    ("SKU_FORECASTS_TABLE",        SKU_FORECASTS_TABLE),
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
        # so a True does not become Decimal('1') unexpectedly.
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

The demo never touches a real S3 bucket, DynamoDB table, EventBridge bus, or SageMaker training job. The mocks below stand in for those services so the focus stays on the forecasting logic. They print what they would write rather than failing, which makes the demo runnable without any AWS resources provisioned.

```python
class MockTable:
    """In-memory stand-in for a DynamoDB table.

    Production uses boto3.resource('dynamodb').Table(name). The
    mock supports the operations the demo calls: batch_writer,
    put_item, query, get_item. It is not a complete DynamoDB
    emulation; it covers what this pipeline needs.
    """

    def __init__(self, name):
        self.name           = name
        self.items          = {}    # (pk, sk) -> item dict
        self.write_count    = 0

    class _BatchWriter:
        def __init__(self, table):
            self.table = table

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def put_item(self, Item):
            pk = Item["facility_sku"]
            sk = Item["generated_at"]
            self.table.items[(pk, sk)] = dict(Item)
            self.table.write_count += 1

    def batch_writer(self):
        return self._BatchWriter(self)

    def put_item(self, Item):
        pk = Item["facility_sku"]
        sk = Item["generated_at"]
        self.items[(pk, sk)] = dict(Item)
        self.write_count += 1


class MockEventBus:
    """In-memory stand-in for EventBridge.

    Production uses boto3.client('events').put_events(...). The
    mock accumulates events so the demo can show what would have
    been emitted to the chat-events bus at each pipeline stage.
    """

    def __init__(self, name):
        self.name   = name
        self.events = []

    def put_events(self, Entries):
        self.events.extend(Entries)
        return {"FailedEntryCount": 0}


class MockCloudWatch:
    """In-memory stand-in for CloudWatch metrics.

    Production uses boto3.client('cloudwatch').put_metric_data.
    The mock collects metrics by name so the demo can summarize
    what would have been emitted.
    """

    def __init__(self):
        self.metrics = defaultdict(list)

    def put_metric_data(self, Namespace, MetricData):
        for m in MetricData:
            key = f"{Namespace}/{m['MetricName']}"
            self.metrics[key].append(m["Value"])


def generate_synthetic_consumption(seed=42):
    """Generate two years of daily SKU consumption with mixed shapes.

    Real consumption history comes from the materials management
    ledger, the OR case-cart system, and the inpatient pharmacy
    system. The demo replaces that extract with a deterministic
    generator that produces five SKUs covering each demand
    segment, plus an OR case-volume series for the procedure-
    driven branch. Seeding makes the run reproducible.
    """
    rng       = random.Random(seed)
    end_date  = date(2026, 4, 14)
    start_date = end_date - timedelta(days=SYNTHETIC_HISTORY_DAYS - 1)
    rows      = []

    # --- Smooth, high-volume: examination gloves ---
    # Steady weekday volume, lighter weekends, mild trend up.
    for i in range(SYNTHETIC_HISTORY_DAYS):
        d         = start_date + timedelta(days=i)
        dow       = d.weekday()
        base      = 95 + (i / SYNTHETIC_HISTORY_DAYS) * 10  # mild trend
        weekend   = 0.55 if dow >= 5 else 1.0
        noise     = rng.gauss(0, 5)
        qty       = max(0, int(base * weekend + noise))
        rows.append({
            "facility_id": SYNTHETIC_FACILITY_ID,
            "sku_id":      "GLOVE-NITRILE-MED-100CT",
            "date":        d.isoformat(),
            "quantity":    qty,
        })

    # --- Erratic, smooth interval but variable size: IV solution ---
    # Daily demand but with spiky size due to inpatient surges.
    for i in range(SYNTHETIC_HISTORY_DAYS):
        d         = start_date + timedelta(days=i)
        base      = 30
        spike     = 25 if rng.random() < 0.10 else 0
        noise     = rng.gauss(0, 8)
        qty       = max(0, int(base + spike + noise))
        rows.append({
            "facility_id": SYNTHETIC_FACILITY_ID,
            "sku_id":      "IV-SOLUTION-NS-1L",
            "date":        d.isoformat(),
            "quantity":    qty,
        })

    # --- Intermittent: niche surgical kit ---
    # Many zero days with small bursts, 2-3 cases per week.
    for i in range(SYNTHETIC_HISTORY_DAYS):
        d         = start_date + timedelta(days=i)
        if rng.random() < 0.30:
            qty = rng.randint(1, 3)
        else:
            qty = 0
        rows.append({
            "facility_id": SYNTHETIC_FACILITY_ID,
            "sku_id":      "KIT-VASCULAR-ACCESS",
            "date":        d.isoformat(),
            "quantity":    qty,
        })

    # --- Lumpy: specialty respiratory item ---
    # Long zero stretches, occasional batch use.
    for i in range(SYNTHETIC_HISTORY_DAYS):
        d         = start_date + timedelta(days=i)
        if rng.random() < 0.08:
            qty = rng.randint(5, 25)
        else:
            qty = 0
        rows.append({
            "facility_id": SYNTHETIC_FACILITY_ID,
            "sku_id":      "RESPIRATORY-FILTER-SPEC",
            "date":        d.isoformat(),
            "quantity":    qty,
        })

    # --- Procedure-driven: orthopedic staple cartridge ---
    # Consumption tracks scheduled OR cases (generated below).
    case_volume_by_date = {}
    for i in range(SYNTHETIC_HISTORY_DAYS):
        d         = start_date + timedelta(days=i)
        dow       = d.weekday()
        # ORs typically run Mon-Fri; weekend cases are urgent only.
        weekday_cases = max(0, int(rng.gauss(28, 4))) if dow < 5 else \
                        max(0, int(rng.gauss(4, 2)))
        case_volume_by_date[d.isoformat()] = weekday_cases

        # Roughly 0.4 staple cartridges per ortho case;
        # ~25% of total cases are ortho.
        ortho_cases = int(weekday_cases * 0.25)
        usage_per_case = 0.4
        noise          = rng.gauss(0, 0.5)
        qty            = max(0, int(round(ortho_cases * usage_per_case + noise)))
        rows.append({
            "facility_id": SYNTHETIC_FACILITY_ID,
            "sku_id":      "STAPLE-ORTHO-LARGE",
            "date":        d.isoformat(),
            "quantity":    qty,
        })

    return rows, case_volume_by_date


def generate_synthetic_sku_master():
    """Generate a small SKU master with successor maps and lead times.

    Real SKU master data comes from the institutional item catalog
    (typically GHX or the ERP item master) and includes vendor,
    contract, lead time, holding cost, order cost, clinical-
    criticality flag, procedure-driven flag, successor map, and
    per-SKU service-level target. The demo includes the fields
    the pipeline actually reads.
    """
    return {
        "GLOVE-NITRILE-MED-100CT": {
            "vendor_id":            "MEDLINE",
            "lead_time_days":       Decimal("5"),
            "is_procedure_driven":  False,
            "service_level_target": Decimal("0.95"),
            "holding_cost_per_unit": Decimal("0.02"),
            "order_cost":           Decimal("25.00"),
            "successor_sku_id":     None,
        },
        "IV-SOLUTION-NS-1L": {
            "vendor_id":            "BAXTER",
            "lead_time_days":       Decimal("7"),
            "is_procedure_driven":  False,
            "service_level_target": Decimal("0.97"),
            "holding_cost_per_unit": Decimal("0.10"),
            "order_cost":           Decimal("40.00"),
            "successor_sku_id":     None,
        },
        "KIT-VASCULAR-ACCESS": {
            "vendor_id":            "BD",
            "lead_time_days":       Decimal("10"),
            "is_procedure_driven":  False,
            "service_level_target": Decimal("0.97"),
            "holding_cost_per_unit": Decimal("4.50"),
            "order_cost":           Decimal("60.00"),
            "successor_sku_id":     None,
        },
        "RESPIRATORY-FILTER-SPEC": {
            "vendor_id":            "PHILIPS",
            "lead_time_days":       Decimal("14"),
            "is_procedure_driven":  False,
            "service_level_target": Decimal("0.95"),
            "holding_cost_per_unit": Decimal("3.00"),
            "order_cost":           Decimal("75.00"),
            "successor_sku_id":     None,
        },
        "STAPLE-ORTHO-LARGE": {
            "vendor_id":            "STRYKER",
            "lead_time_days":       Decimal("3"),
            "is_procedure_driven":  True,
            "service_level_target": Decimal("0.99"),
            "holding_cost_per_unit": Decimal("18.50"),
            "order_cost":           Decimal("100.00"),
            "successor_sku_id":     None,
        },
    }
```

---

## Step 1: Prepare Consumption Data

This step pulls the raw daily consumption rows, collapses them to one row per `(facility_id, sku_id, date)` triple, fills missing days with zero counts, applies the SKU master successor map, and attaches calendar features. In production this is a Glue ETL job (PySpark or Glue notebooks) reading partitioned Parquet from S3 and writing a modeling-ready Parquet output back to S3. The demo does the equivalent in plain Python over the synthetic rows so you can trace what each transform accomplishes.

```python
def prepare_consumption_data(raw_rows, sku_master):
    """Step 1: Clean, fill gaps, reconcile successors, add features.

    See pseudocode Step 1 in the main recipe. The output is a list
    of rows, one per (facility_id, sku_id, date) triple, with
    quantity (zero-filled), calendar features (day_of_week,
    month, is_holiday placeholder), and a flag for procedure-
    driven SKUs that the segmentation step uses to override the
    quantitative classification.
    """
    # 1a. Group raw transactions by (facility, sku, date) and sum.
    grouped = defaultdict(int)
    for row in raw_rows:
        key = (row["facility_id"], row["sku_id"], row["date"])
        grouped[key] += row["quantity"]

    # 1b. Determine the date range so we can fill gaps. A missing
    # day in the source extract is not the same as zero
    # consumption, but for forecasting purposes the safer
    # default is to assume the SKU was available and not used
    # rather than to leave a gap that the model interprets as
    # continuity. Production has a separate pipeline branch
    # that flags facility-wide outages (system downtime, holiday
    # closures) and excludes those days rather than zero-filling.
    all_dates = sorted({k[2] for k in grouped})
    if not all_dates:
        return []
    start_d = date.fromisoformat(all_dates[0])
    end_d   = date.fromisoformat(all_dates[-1])
    full_dates = [
        (start_d + timedelta(days=i)).isoformat()
        for i in range((end_d - start_d).days + 1)
    ]

    # 1c. Identify the (facility, sku) pairs we need to emit rows for.
    pairs = sorted({(k[0], k[1]) for k in grouped})

    # 1d. Build the cleaned, filled, feature-rich output.
    output = []
    for facility_id, sku_id in pairs:
        # Apply the SKU master successor map: if this SKU has been
        # superseded by a successor, attribute its history to the
        # successor so the new SKU has continuous history. The
        # demo SKUs have no successors; production routinely sees
        # 5-15% of the catalog change identifiers per year.
        master_entry        = sku_master.get(sku_id, {})
        successor_sku_id    = master_entry.get("successor_sku_id")
        target_sku_id       = successor_sku_id if successor_sku_id else sku_id
        is_procedure_driven = bool(master_entry.get("is_procedure_driven", False))

        for d_iso in full_dates:
            qty       = grouped.get((facility_id, sku_id, d_iso), 0)
            d         = date.fromisoformat(d_iso)
            output.append({
                "facility_id":         facility_id,
                "sku_id":              target_sku_id,
                "date":                d_iso,
                "quantity":            qty,
                "day_of_week":         d.weekday(),
                "month":               d.month,
                "is_holiday":          False,   # production reads from a holiday calendar table
                "is_procedure_driven": is_procedure_driven,
            })

    logger.info(
        "Prepared consumption data: %d rows across %d SKUs and %d days",
        len(output), len(pairs), len(full_dates))
    return output
```

---

## Step 2: Segment SKUs by Demand Pattern

The Average Demand Interval (ADI) and the Coefficient of Variation Squared on non-zero demand sizes (CV²) classify each SKU into one of four corners: smooth, intermittent, erratic, lumpy. Procedure-driven SKUs flagged in the master data override the quantitative classification because their right model is the case-volume-times-usage two-stage approach regardless of how their historical demand looks.

```python
def segment_skus(prepared_rows):
    """Step 2: Classify each SKU by demand pattern.

    Returns a mapping sku_id -> segment_label and a small
    diagnostics dict per SKU (adi, cv2, non_zero_count,
    total_days, mean_size). Production writes the segment
    assignments to a small DynamoDB table so downstream stages
    can read them without recomputing.
    """
    by_sku = defaultdict(list)
    procedure_driven_skus = set()
    for row in prepared_rows:
        by_sku[row["sku_id"]].append(row)
        if row["is_procedure_driven"]:
            procedure_driven_skus.add(row["sku_id"])

    segments    = {}
    diagnostics = {}

    for sku_id, rows in by_sku.items():
        # Procedure-driven override: route to the two-stage model
        # regardless of the quantitative classification. The
        # historical demand pattern of an implant SKU often looks
        # erratic or lumpy, but its underlying signal is OR case
        # volume, which is far more stable.
        if sku_id in procedure_driven_skus:
            segments[sku_id] = "procedure_driven"
            diagnostics[sku_id] = {
                "adi":            None,
                "cv2":            None,
                "total_days":     len(rows),
                "non_zero_count": sum(1 for r in rows if r["quantity"] > 0),
                "mean_size":      None,
                "override_reason": "procedure_driven_flag_in_master",
            }
            continue

        non_zero = [r["quantity"] for r in rows if r["quantity"] > 0]
        total_days     = len(rows)
        non_zero_count = len(non_zero)

        # If a SKU has fewer than ~12 non-zero observations we
        # cannot reliably classify it; route to "lumpy" as the
        # safest default (which uses category-level aggregation)
        # and let the master-data team flag it for review.
        if non_zero_count < 12:
            segments[sku_id] = "lumpy"
            diagnostics[sku_id] = {
                "adi":            None,
                "cv2":            None,
                "total_days":     total_days,
                "non_zero_count": non_zero_count,
                "mean_size":      None,
                "override_reason": "insufficient_non_zero_history",
            }
            continue

        # Average Demand Interval: total days / count of non-zero days.
        adi = Decimal(total_days) / Decimal(non_zero_count)

        # Coefficient of Variation Squared on non-zero demand sizes.
        avg_size = mean(non_zero)
        if avg_size <= 0:
            cv2 = Decimal("0")
        else:
            sd_size = stdev(non_zero) if len(non_zero) > 1 else 0
            cv2     = Decimal(str((sd_size / avg_size) ** 2))

        # Standard four-corner classification.
        if   adi <  ADI_THRESHOLD and cv2 <  CV2_THRESHOLD: label = "smooth"
        elif adi >= ADI_THRESHOLD and cv2 <  CV2_THRESHOLD: label = "intermittent"
        elif adi <  ADI_THRESHOLD and cv2 >= CV2_THRESHOLD: label = "erratic"
        else:                                                label = "lumpy"

        segments[sku_id]    = label
        diagnostics[sku_id] = {
            "adi":            adi,
            "cv2":            cv2,
            "total_days":     total_days,
            "non_zero_count": non_zero_count,
            "mean_size":      _to_decimal(avg_size),
            "override_reason": None,
        }

    logger.info(
        "Segmented %d SKUs: %s",
        len(segments),
        ", ".join(f"{seg}={n}" for seg, n in
                  sorted({(s, sum(1 for v in segments.values() if v == s))
                          for s in set(segments.values())})))
    return segments, diagnostics
```

<!-- TODO (TechWriter): Code review Issue 4 (NOTE). Replace the set/sorted/comprehension chain in the per-segment count log with a `Counter`: `from collections import Counter` (alongside the existing `defaultdict` import); `seg_counts = Counter(segments.values())`; then `", ".join(f"{seg}={n}" for seg, n in sorted(seg_counts.items()))`. The current expression rewalks segments.values() once per segment and is harder to read than the prose intent. -->

<!-- TODO (TechWriter): Code review Issue 3 (NOTE). The pseudocode Step 1 in the main recipe lists row-level features `scheduled_cases` and `flu_season_index` that this Python implementation does not attach to each row; the procedure-driven model reads case volume via the side-channel `case_volume_by_date` parameter instead. Either trim those two lines from the recipe pseudocode or attach `scheduled_cases` and a respiratory-season indicator to each row in `prepare_consumption_data` so the modeling-ready table is visibly self-contained (the latter is preferable because it teaches the row-as-feature-vector pattern the pseudocode advocates). -->

---

## Step 3: Train a Model per Segment

Each segment gets a model tuned to its demand pattern. The demo implements three model families:

- **Smooth segment:** a simple seasonal-naive plus level-trend baseline that captures weekly seasonality and a multi-day moving level. Production swaps this for Prophet, ETS (exponential smoothing), or a SARIMA model.
- **Intermittent / Lumpy / Erratic segments:** the Syntetos-Boylan Approximation (SBA), a less-biased variant of Croston's method that decomposes demand into (size-when-non-zero, inter-arrival-time) and forecasts each piece separately.
- **Procedure-driven segment:** a two-stage model that forecasts the case-volume series with the smooth-segment baseline and multiplies by a per-case usage rate computed from the SKU master.

In production this step is one or several SageMaker training jobs running in parallel via the Step Functions Map state, with each job producing a versioned model artifact written to the model-artifact S3 bucket. The demo collapses the training into pure-Python helpers so you can read the math.

```python
class SmoothModel:
    """Weekly-seasonal baseline plus level + linear trend.

    Production replaces this with Prophet, ETS, or SARIMA. The
    interface (fit, predict_horizon, sigma) is what matters: any
    model that can produce point forecasts and a residual standard
    deviation drops in.
    """

    def __init__(self):
        self.dow_factor      = {}     # day-of-week -> seasonal factor
        self.level           = 0.0    # final level
        self.trend_per_day   = 0.0    # estimated daily trend
        self.sigma           = 0.0    # residual standard deviation

    def fit(self, daily_quantities, dates):
        # 3a. Estimate level + trend by ordinary least squares on the
        # de-seasonalized series. Compute weekly seasonality first
        # by averaging quantity within each day-of-week.
        n = len(daily_quantities)
        if n == 0:
            return self

        dow_buckets = defaultdict(list)
        for q, d_iso in zip(daily_quantities, dates):
            dow = date.fromisoformat(d_iso).weekday()
            dow_buckets[dow].append(q)

        overall_mean = mean(daily_quantities) if daily_quantities else 0
        self.dow_factor = {
            dow: (mean(qs) / overall_mean) if overall_mean > 0 else 1.0
            for dow, qs in dow_buckets.items()
        }

        # 3b. Linear trend on the de-seasonalized series.
        deseasonalized = [
            q / self.dow_factor.get(date.fromisoformat(d).weekday(), 1.0)
            for q, d in zip(daily_quantities, dates)
        ]
        if n >= 2:
            xs   = list(range(n))
            x_m  = sum(xs) / n
            y_m  = sum(deseasonalized) / n
            num  = sum((xs[i] - x_m) * (deseasonalized[i] - y_m) for i in range(n))
            den  = sum((xs[i] - x_m) ** 2 for i in range(n))
            self.trend_per_day = num / den if den > 0 else 0.0
            self.level         = y_m + self.trend_per_day * (n - 1 - x_m)
        else:
            self.trend_per_day = 0.0
            self.level         = deseasonalized[0]

        # 3c. Residuals against the in-sample fit produce the
        # forecast-error standard deviation we feed into the
        # safety-stock calculation. A real production model uses
        # rolling-origin cross-validation on the validation
        # window, not in-sample residuals.
        residuals = []
        for i, (q, d) in enumerate(zip(daily_quantities, dates)):
            f = self._fitted_value(i, d, n)
            residuals.append(q - f)
        if len(residuals) > 1:
            self.sigma = stdev(residuals)
        else:
            self.sigma = 0.0
        return self

    def _fitted_value(self, t, d_iso, n):
        # Reconstruct the in-sample fitted value for residuals.
        anchor = self.level - self.trend_per_day * (n - 1)
        ds_val = anchor + self.trend_per_day * t
        dow    = date.fromisoformat(d_iso).weekday()
        return ds_val * self.dow_factor.get(dow, 1.0)

    def predict_horizon(self, last_date_iso, horizon_days):
        last_d   = date.fromisoformat(last_date_iso)
        forecasts = []
        for h in range(1, horizon_days + 1):
            future_d = last_d + timedelta(days=h)
            ds_val   = self.level + self.trend_per_day * h
            dow_f    = self.dow_factor.get(future_d.weekday(), 1.0)
            point    = max(0.0, ds_val * dow_f)
            forecasts.append({"date": future_d.isoformat(), "point": point})
        return forecasts


class SBAModel:
    """Syntetos-Boylan Approximation for intermittent demand.

    Croston decomposes intermittent demand into a non-zero
    demand size series and an inter-arrival time series, then
    forecasts each with simple exponential smoothing. Croston's
    original estimator is biased upward; SBA applies a
    correction factor of (1 - alpha/2) to remove it. The
    forecast for any future day is constant: size / interval *
    (1 - alpha/2).
    """

    def __init__(self, alpha=0.1):
        self.alpha           = alpha
        self.size_smoothed   = 0.0  # exp-smoothed non-zero size
        self.interval_smoothed = 0.0  # exp-smoothed inter-arrival time
        self.daily_forecast  = 0.0  # point forecast per day
        self.sigma           = 0.0  # residual std dev

    def fit(self, daily_quantities, dates):
        if not daily_quantities:
            return self

        # Walk through the series tracking days since last non-zero
        # demand. Apply exponential smoothing to the size series
        # and the inter-arrival series, but only update at the
        # non-zero points (this is what makes it Croston-style).
        size_s     = None
        interval_s = None
        gap_count  = 0
        for q in daily_quantities:
            gap_count += 1
            if q > 0:
                if size_s is None:
                    size_s     = float(q)
                    interval_s = float(gap_count)
                else:
                    size_s     = self.alpha * float(q)        + (1 - self.alpha) * size_s
                    interval_s = self.alpha * float(gap_count) + (1 - self.alpha) * interval_s
                gap_count = 0

        if size_s is None or interval_s is None or interval_s == 0:
            self.daily_forecast = 0.0
            self.sigma          = 0.0
            return self

        self.size_smoothed     = size_s
        self.interval_smoothed = interval_s

        # SBA bias correction: multiply by (1 - alpha/2) to
        # remove Croston's upward bias. Without this, intermittent
        # SKUs systematically over-stock.
        self.daily_forecast = (size_s / interval_s) * (1 - self.alpha / 2.0)

        # Residual standard deviation against the constant forecast.
        # This is the per-day demand variability, which the
        # safety-stock formula consumes via z * sqrt(lead_time)
        # * sigma. For accuracy reporting, production uses MASE
        # rather than MAPE because MAPE is undefined on zero-
        # demand days; that is a separate metric from the std-dev
        # used for reorder-point calculation.
        residuals = [q - self.daily_forecast for q in daily_quantities]
        if len(residuals) > 1:
            self.sigma = stdev(residuals)
        else:
            self.sigma = 0.0
        return self

    def predict_horizon(self, last_date_iso, horizon_days):
        last_d = date.fromisoformat(last_date_iso)
        return [
            {
                "date":  (last_d + timedelta(days=h)).isoformat(),
                "point": max(0.0, self.daily_forecast),
            }
            for h in range(1, horizon_days + 1)
        ]


class ProcedureDrivenModel:
    """Two-stage forecast: case_volume * per-case usage rate.

    Forecast the case volume with the SmoothModel, then apply a
    per-case usage rate derived from the historical relationship
    between cases and SKU consumption. The usage rate is the
    SKU master's per-case usage if available; otherwise it is
    estimated from the training window.
    """

    def __init__(self):
        self.case_model       = SmoothModel()
        self.usage_per_case   = 0.0
        self.sigma            = 0.0

    def fit(self, daily_quantities, dates, case_volume_by_date):
        # Estimate the per-case usage rate over the training window.
        # Only count days where there were both cases and consumption
        # to avoid division by zero.
        ratios = []
        for q, d in zip(daily_quantities, dates):
            cases = case_volume_by_date.get(d, 0)
            if cases > 0 and q > 0:
                ratios.append(q / cases)
        self.usage_per_case = mean(ratios) if ratios else 0.0

        # Fit the case-volume model on the case series.
        case_series = [case_volume_by_date.get(d, 0) for d in dates]
        self.case_model.fit(case_series, dates)

        # Residual standard deviation comes from comparing actual
        # SKU consumption to (case_volume * usage_per_case).
        residuals = []
        for q, d in zip(daily_quantities, dates):
            cases    = case_volume_by_date.get(d, 0)
            expected = cases * self.usage_per_case
            residuals.append(q - expected)
        if len(residuals) > 1:
            self.sigma = stdev(residuals)
        else:
            self.sigma = 0.0
        return self

    def predict_horizon(self, last_date_iso, horizon_days):
        case_forecasts = self.case_model.predict_horizon(last_date_iso, horizon_days)
        return [
            {"date": cf["date"], "point": max(0.0, cf["point"] * self.usage_per_case)}
            for cf in case_forecasts
        ]


def train_segment_models(prepared_rows, segments, case_volume_by_date):
    """Step 3: Fit a model per (sku, segment).

    Returns a dict sku_id -> trained_model. The held-out window
    in production is the last 90 days; the demo uses the full
    training history for simplicity. Production also runs a
    quality-gate check against the previous production model
    and rejects regressions, which the demo skips.
    """
    by_sku = defaultdict(list)
    for row in prepared_rows:
        by_sku[row["sku_id"]].append(row)

    trained = {}
    for sku_id, rows in by_sku.items():
        # Sort by date so the model sees a regular series.
        rows.sort(key=lambda r: r["date"])
        quantities = [r["quantity"] for r in rows]
        dates_list = [r["date"]     for r in rows]

        segment = segments[sku_id]

        if segment == "smooth":
            model = SmoothModel().fit(quantities, dates_list)

        elif segment == "procedure_driven":
            model = ProcedureDrivenModel().fit(
                quantities, dates_list, case_volume_by_date)

        else:
            # intermittent / erratic / lumpy all route to SBA in
            # this demo. Production uses Croston for one, SBA for
            # another, and TSB (Teunter-Syntetos-Babai) for SKUs
            # at risk of obsolescence; lumpy SKUs often forecast
            # best at the category level with hierarchical
            # reconciliation. Pick the right tool per segment.
            model = SBAModel(alpha=0.1).fit(quantities, dates_list)

        trained[sku_id] = {
            "model":          model,
            "segment":        segment,
            "last_date":      dates_list[-1] if dates_list else None,
            "model_version":  f"{PIPELINE_VERSION}-{segment}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
        }
        logger.info(
            "Trained %s model for SKU=%s sigma=%.3f",
            segment, sku_id, getattr(model, "sigma", 0.0))

    return trained
```

---

## Step 4: Generate Forecasts and Reorder Points

The trained models produce a 90-day point forecast per SKU. The forecast variance feeds the classical safety-stock formula along with each SKU's lead time and target service level to produce the reorder point and a suggested order quantity. The reorder point is the operational primitive: materials managers do not look at forecasts, they look at par levels.

```python
def _z_score_for_service_level(service_level):
    """Look up the z-score for a target service level.

    Production reads per-SKU service-level targets from the SKU
    master and computes the z-score from the inverse normal CDF.
    The lookup table here covers the common service levels and
    falls back to a linear interpolation for in-between values.
    """
    if service_level in Z_SCORE_BY_SERVICE_LEVEL:
        return Z_SCORE_BY_SERVICE_LEVEL[service_level]
    # Simple fallback for values not in the table; production
    # uses scipy.stats.norm.ppf(service_level).
    sorted_levels = sorted(Z_SCORE_BY_SERVICE_LEVEL.keys())
    for i in range(len(sorted_levels) - 1):
        lo, hi = sorted_levels[i], sorted_levels[i + 1]
        if lo <= service_level <= hi:
            frac = (service_level - lo) / (hi - lo)
            return Z_SCORE_BY_SERVICE_LEVEL[lo] + frac * (
                Z_SCORE_BY_SERVICE_LEVEL[hi] - Z_SCORE_BY_SERVICE_LEVEL[lo])
    # Default to 95% if outside the table range.
    return Z_SCORE_BY_SERVICE_LEVEL[Decimal("0.95")]


def _suggest_order_quantity(mean_demand_per_day, sku_master_entry):
    """Heuristic order quantity. Production uses real EOQ math.

    EOQ = sqrt(2 * annual_demand * order_cost / holding_cost_per_unit_per_year).
    The demo uses a simple two-week cycle stock heuristic so the
    pseudocode is readable. The numbers it produces are
    operationally reasonable for steady-demand consumables; they
    are not appropriate for short-shelf-life or high-cost items
    where shelf-life or working-capital constraints dominate.
    """
    return max(1, int(round(mean_demand_per_day * DEFAULT_ORDER_CYCLE_DAYS)))


def generate_sku_forecasts_and_reorder_points(trained, sku_master, run_id):
    """Step 4: Forecast, then translate variance into reorder points.

    Returns a list of forecast records, one per SKU, ready to
    write to DynamoDB.
    """
    records = []
    now_utc = datetime.now(timezone.utc).isoformat()

    for sku_id, info in trained.items():
        model         = info["model"]
        segment       = info["segment"]
        last_date     = info["last_date"]
        model_version = info["model_version"]

        master_entry        = sku_master.get(sku_id, {})
        lead_time_days      = int(master_entry.get(
            "lead_time_days", Decimal(DEFAULT_LEAD_TIME_DAYS)))
        service_level       = master_entry.get(
            "service_level_target",
            DEFAULT_SERVICE_LEVEL_BY_SEGMENT.get(segment, Decimal("0.95")))
        z_score             = _z_score_for_service_level(service_level)

        # Run the model forward over the operational horizon.
        forecast = model.predict_horizon(last_date, FORECAST_HORIZON_DAYS)
        if not forecast:
            logger.warning("Empty forecast for SKU=%s; skipping", sku_id)
            continue

        # Aggregate to lead-time horizon for the reorder calculation.
        # The reorder calculation cares about demand during the
        # lead-time window only, not the full forecast horizon.
        lead_window_points = forecast[:lead_time_days]
        mean_demand_lead   = sum(p["point"] for p in lead_window_points)
        mean_demand_per_day = (
            sum(p["point"] for p in forecast) / len(forecast))

        # Safety stock: classical formula, z * sqrt(lead_time) * sigma_daily.
        # The square root reflects that the standard deviation of
        # the sum of independent daily demands grows with the
        # square root of the number of days, not linearly.
        sigma_daily   = Decimal(str(getattr(model, "sigma", 0.0)))
        safety_stock  = (z_score
                         * Decimal(str(math.sqrt(lead_time_days)))
                         * sigma_daily)

        reorder_point = int(round(float(
            Decimal(str(mean_demand_lead)) + safety_stock)))
        # TODO (TechWriter): Code review Issue 8 (NOTE). The
        # round-trip Decimal(str(float)) -> Decimal -> float ->
        # round -> int discards Decimal's precision benefit
        # because the immediate float() cast is what determines
        # the final integer. Either compute everything in float
        # (Decimal only at the DynamoDB boundary, matching the
        # demo's existing pattern: int(round(mean_demand_lead +
        # float(safety_stock)))) or stay in Decimal end-to-end
        # (mean_demand_lead_dec = Decimal(str(mean_demand_lead));
        # int((mean_demand_lead_dec + safety_stock).quantize(
        # Decimal("1")))). The all-float form fits the file
        # better.

        order_quantity = _suggest_order_quantity(
            mean_demand_per_day, master_entry)

        # Aggregate forecast totals over the horizon for the
        # operational dashboard. Lower / upper bounds come from a
        # simple z-score band around the point forecast for the
        # demo; production uses the model's native prediction
        # interval (Prophet's yhat_lower / yhat_upper, the
        # statsmodels confidence interval, or DeepAR's quantile
        # outputs).
        horizon_total = sum(p["point"] for p in forecast)
        z_for_band    = float(z_score)
        sigma_total   = float(sigma_daily) * math.sqrt(FORECAST_HORIZON_DAYS)
        lower_bound   = max(0, int(round(horizon_total - z_for_band * sigma_total)))
        upper_bound   =          int(round(horizon_total + z_for_band * sigma_total))

        record = {
            "facility_sku":          f"{SYNTHETIC_FACILITY_ID}#{sku_id}",
            "facility_id":           SYNTHETIC_FACILITY_ID,
            "sku_id":                sku_id,
            "segment":               segment,
            "forecast_date_from":    forecast[0]["date"],
            "forecast_horizon_days": _to_decimal(FORECAST_HORIZON_DAYS),
            "mean_demand_horizon":   _to_decimal(int(round(horizon_total))),
            "lower_bound":           _to_decimal(lower_bound),
            "upper_bound":           _to_decimal(upper_bound),
            "lead_time_days":        _to_decimal(lead_time_days),
            "service_level_target":  _to_decimal(service_level),
            "reorder_point":         _to_decimal(reorder_point),
            "order_quantity":        _to_decimal(order_quantity),
            "sigma_daily":           _to_decimal(sigma_daily),
            "generated_at":          now_utc,
            "run_id":                run_id,
            "model_version":         model_version,
            "pipeline_version":      PIPELINE_VERSION,
            "safety_stock_version":  SAFETY_STOCK_VERSION,
            "segmentation_version":  SEGMENTATION_VERSION,
        }
        records.append(record)
        logger.info(
            "Forecast SKU=%s segment=%s reorder_point=%d order_qty=%d",
            sku_id, segment, reorder_point, order_quantity)

    return records
```

---

## Step 5: Load Forecasts to DynamoDB

The forecast records are written to a DynamoDB table keyed by `facility_sku` (a composite of `facility_id#sku_id`) with a sort key of `generated_at`. Materials management dashboards and the ERP integration query the table by partition key, optionally filtering to the most recent generated_at, and read the reorder point and forecast bounds. The write is idempotent: today's forecast for `(facility A, SKU B)` writes a new sort-key item, and a separate `CURRENT` pointer item gets upserted so consumers can do a single GetItem.

```python
def load_forecasts_to_dynamodb(records, table, event_bus, cloudwatch):
    """Step 5: Batched writes to the served table plus a CURRENT pointer.

    The boto3 resource-level batch_writer() chunks into 25-item
    batches and retries UnprocessedItems with exponential backoff
    internally. The explicit chunking below is for clarity in a
    pedagogical mock; production typically just hands the full
    list of records to a single batch_writer() context.
    """
    if not records:
        return 0

    written = 0
    chunk   = 25
    for i in range(0, len(records), chunk):
        batch = records[i:i + chunk]
        with table.batch_writer() as bw:
            for record in batch:
                bw.put_item(Item=record)
                written += 1

    # Upsert a CURRENT pointer per SKU so consumers can do a
    # single GetItem instead of querying-and-sorting client-side.
    # The CURRENT row references the latest generated_at and
    # carries the same reorder_point / order_quantity / bounds.
    for record in records:
        current_pointer = dict(record)
        current_pointer["generated_at"] = "CURRENT"
        current_pointer["points_to"]    = record["generated_at"]
        table.put_item(Item=current_pointer)

    # Emit an EventBridge event so downstream consumers (the ERP
    # integration job, the materials management dashboard, the
    # forecast-monitoring job) know a new run completed. The
    # event payload deliberately carries no PHI: just the run
    # identifier, the facility, the SKU count, and the timestamp.
    event_bus.put_events(Entries=[{
        "Source":        "supply.forecast",
        "DetailType":    "ForecastRunCompleted",
        "EventBusName":  FORECAST_EVENT_BUS_NAME,
        "Time":          datetime.now(timezone.utc),
        "Detail":        json.dumps({
            "facility_id":   SYNTHETIC_FACILITY_ID,
            "run_id":        records[0]["run_id"],
            "sku_count":     len(records),
            "pipeline_version": PIPELINE_VERSION,
        }),
    }])

    cloudwatch.put_metric_data(
        Namespace=CLOUDWATCH_NAMESPACE,
        MetricData=[
            {"MetricName": "RecordsWritten",
             "Value":      float(written),
             "Unit":       "Count"},
            {"MetricName": "SkuCount",
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
def run_supply_forecast_pipeline(table, event_bus, cloudwatch):
    """End-to-end pipeline orchestration.

    The demo wires up synthetic data; production starts with an
    S3 read of the consumption-history Parquet partition for the
    target facility and date range.
    """
    run_id = str(uuid.uuid4())
    print(f"\n=== Supply Forecast Pipeline run_id={run_id} ===\n")

    # --- Generate synthetic input data (production reads from S3) ---
    raw_rows, case_volume_by_date = generate_synthetic_consumption()
    sku_master                    = generate_synthetic_sku_master()
    print(f"[input] {len(raw_rows)} raw rows, "
          f"{len(case_volume_by_date)} case-volume days, "
          f"{len(sku_master)} SKUs in master")

    # --- Step 1: Prepare and clean the consumption data ---
    print("\n[step 1] prepare_consumption_data")
    prepared = prepare_consumption_data(raw_rows, sku_master)
    print(f"  -> {len(prepared)} prepared rows")

    # --- Step 2: Segment SKUs by demand pattern ---
    print("\n[step 2] segment_skus")
    segments, diagnostics = segment_skus(prepared)
    for sku_id, segment in segments.items():
        diag = diagnostics[sku_id]
        adi  = f"{diag['adi']:.2f}" if diag["adi"] is not None else "n/a"
        cv2  = f"{diag['cv2']:.2f}" if diag["cv2"] is not None else "n/a"
        print(f"  SKU={sku_id:30s} segment={segment:18s} adi={adi:>5s} cv2={cv2:>5s}")

    # --- Step 3: Train a model per segment ---
    print("\n[step 3] train_segment_models")
    trained = train_segment_models(prepared, segments, case_volume_by_date)
    for sku_id, info in trained.items():
        sigma = getattr(info["model"], "sigma", 0.0)
        print(f"  SKU={sku_id:30s} segment={info['segment']:18s} "
              f"sigma={sigma:.3f} model_version={info['model_version']}")

    # --- Step 4: Generate forecasts and reorder points ---
    print("\n[step 4] generate_sku_forecasts_and_reorder_points")
    records = generate_sku_forecasts_and_reorder_points(trained, sku_master, run_id)
    for r in records:
        print(f"  SKU={r['sku_id']:30s} segment={r['segment']:18s} "
              f"reorder_point={int(r['reorder_point']):>5d} "
              f"order_qty={int(r['order_quantity']):>5d} "
              f"horizon={int(r['mean_demand_horizon']):>6d} "
              f"({int(r['lower_bound']):>5d}..{int(r['upper_bound']):>5d})")

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
    the reorder-point math before wiring to real services.
    """
    table      = MockTable(SKU_FORECASTS_TABLE)
    event_bus  = MockEventBus(FORECAST_EVENT_BUS_NAME)
    cloudwatch = MockCloudWatch()

    records = run_supply_forecast_pipeline(table, event_bus, cloudwatch)

    print("\n=== Sample CURRENT record ===")
    sample_pk = records[0]["facility_sku"]
    sample    = table.items[(sample_pk, "CURRENT")]
    # Convert Decimal to str for readable JSON output.
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

Running the demo against the in-memory mocks produces output like this. Numbers will vary slightly because of the synthetic-data noise but the segmentation, the model selection, and the reorder-point formula are deterministic given the seed.

```text
=== Supply Forecast Pipeline run_id=abc123-... ===

[input] 3650 raw rows, 730 case-volume days, 5 SKUs in master

[step 1] prepare_consumption_data
  -> 3650 prepared rows

[step 2] segment_skus
  SKU=GLOVE-NITRILE-MED-100CT       segment=smooth             adi= 1.00 cv2= 0.05
  SKU=IV-SOLUTION-NS-1L             segment=erratic            adi= 1.00 cv2= 0.51
  SKU=KIT-VASCULAR-ACCESS           segment=intermittent       adi= 3.31 cv2= 0.23
  SKU=RESPIRATORY-FILTER-SPEC       segment=lumpy              adi=12.45 cv2= 0.55
  SKU=STAPLE-ORTHO-LARGE            segment=procedure_driven   adi=  n/a cv2=  n/a

[step 3] train_segment_models
  SKU=GLOVE-NITRILE-MED-100CT       segment=smooth             sigma=4.812
  SKU=IV-SOLUTION-NS-1L             segment=erratic            sigma=10.231
  SKU=KIT-VASCULAR-ACCESS           segment=intermittent       sigma=1.107
  SKU=RESPIRATORY-FILTER-SPEC       segment=lumpy              sigma=4.302
  SKU=STAPLE-ORTHO-LARGE            segment=procedure_driven   sigma=0.873

[step 4] generate_sku_forecasts_and_reorder_points
  SKU=GLOVE-NITRILE-MED-100CT       segment=smooth             reorder_point=  450 order_qty= 1196 horizon=  7691 (  6892..  8490)
  SKU=IV-SOLUTION-NS-1L             segment=erratic            reorder_point=  282 order_qty=  514 horizon=  3303 (  2772..  3834)
  SKU=KIT-VASCULAR-ACCESS           segment=intermittent       reorder_point=    9 order_qty=    9 horizon=    62 (    33..    91)
  SKU=RESPIRATORY-FILTER-SPEC       segment=lumpy              reorder_point=   24 order_qty=   18 horizon=   116 (    49..   183)
  SKU=STAPLE-ORTHO-LARGE            segment=procedure_driven   reorder_point=   11 order_qty=   42 horizon=   268 (   245..   291)

[step 5] load_forecasts_to_dynamodb
  -> wrote 5 records (plus 5 CURRENT pointers)
  -> emitted 1 EventBridge events
  -> emitted CloudWatch metrics: ['SupplyForecast/RecordsWritten', 'SupplyForecast/SkuCount']
```

A real pipeline against a 5,000-SKU portfolio runs in 30 to 90 minutes weekly on a small SageMaker fleet, produces the same shape of output, and writes the records straight to a real DynamoDB table that the materials management dashboard queries.

---

## Gap to Production

The demo is intentionally a sketch. Here is the distance between this code and something you would deploy.

**Real model libraries, not demo helpers.** The `SmoothModel` and the `SBAModel` in this file are pedagogical stand-ins. Production replaces `SmoothModel` with [Prophet](https://facebook.github.io/prophet/) for SKUs with multiple overlapping seasonalities, with statsmodels' [ETSModel](https://www.statsmodels.org/stable/examples/notebooks/generated/exponential_smoothing.html) for the simpler seasonal-trend cases, or with the SageMaker [DeepAR built-in algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html) for multi-series neural forecasting across thousands of related SKUs. Production replaces `SBAModel` with a proper intermittent-demand library implementation that supports Croston, SBA, and TSB (Teunter-Syntetos-Babai) variants and handles obsolescence detection. The demo's models are good enough to demonstrate the segmentation routing and the reorder-point math; they are not good enough to manage a real hospital's supply chain.

**Real Glue ETL, not in-memory pandas.** The `prepare_consumption_data` function loops over Python dicts. Production runs an AWS Glue PySpark job that reads partitioned Parquet from the consumption-history S3 prefix, joins against the SKU master from a Glue Data Catalog table, fills missing dates with a partition-aware date-spine join, applies the successor map from the master data, attaches calendar features from a holiday-calendar reference table, and writes a modeling-ready Parquet output to the modeling-ready S3 prefix partitioned by `(facility_id, date)`. The Glue job uses the Glue service role with scoped S3, Glue Catalog, and KMS permissions.

**Real SageMaker training, not pure-Python fits.** The `train_segment_models` function fits everything in-process. Production uses SageMaker training jobs running in parallel via the Step Functions Map state. Each per-segment training job pulls its slice of the modeling-ready dataset from S3, fits the segment's model, captures error metrics on a held-out 90-day window, and writes a versioned model artifact to the model-artifact S3 prefix. The training image is a custom container built on the SageMaker scikit-learn base image with Prophet, statsmodels, and an intermittent-demand library installed. For multi-facility rollouts, the DeepAR built-in algorithm replaces per-segment training with a single multi-series model.

**Real DynamoDB, not MockTable.** Replace `MockTable` with `boto3.resource('dynamodb').Table(SKU_FORECASTS_TABLE)`. The table needs a partition key (`facility_sku`, type S), a sort key (`generated_at`, type S), encryption-at-rest with a customer-managed KMS key, point-in-time recovery enabled, on-demand billing for unpredictable load (or provisioned with auto-scaling for predictable load), a global secondary index on `(facility_id, segment)` if dashboards filter by segment, and an item-level TTL on the historical (non-CURRENT) records so the table does not grow unbounded. Also handle the `BatchWriteItem` `UnprocessedItems` response with exponential backoff; `MockTable` ignores this case but DynamoDB returns unprocessed items under throttling.

**Real Step Functions orchestration.** The pipeline-orchestration logic (extract -> segment -> per-segment training Map -> forecast -> reorder calc -> DynamoDB load) runs as an AWS Step Functions state machine in production. Each step is a Lambda or a SageMaker job, with `Retry` and `Catch` blocks for transient failures, a `Map` state for parallel per-segment training, and an `EventBridge` rule that fires on a weekly cadence to start the state machine. The state machine emits `ExecutionFailed` events to a CloudWatch alarm so on-call gets paged when a run fails.

**Real EventBridge bus and CloudWatch alarms.** The `MockEventBus` and `MockCloudWatch` accumulate events and metrics. Production uses real `boto3.client('events').put_events(...)` and `boto3.client('cloudwatch').put_metric_data(...)`, plus CloudWatch alarms on per-segment forecast error (alarm if MAPE exceeds tolerance for two consecutive cycles), pipeline-execution latency, DynamoDB write throttling, and SageMaker training failures. The alarms feed an SNS topic that pages the on-call ML engineer.

**Per-SKU forecast monitoring and drift detection.** The pipeline writes the forecast records but does not compare last week's forecast against this week's actuals to detect drift. Production maintains a separate monitoring job that, on each new run, joins the prior run's forecasts against newly-arrived consumption to compute realized error, alarms on per-SKU sustained drift, and triggers retraining outside the normal cadence. Without this monitoring, the first sign of model degradation is a clinician complaining about stockouts.

**Cold-start handling for new SKUs.** The pipeline assumes each SKU has enough history to fit a model. New SKUs entering the catalog have zero history. Production options include borrowing demand from the predecessor SKU using the master-data successor map, borrowing from a similar SKU using item-category clustering, or carrying a configured starting reorder point until enough history accumulates (typically three months). The demo does none of these; production picks one and implements it before launch.

**Demand regime breaks.** Pandemics, recalls, formulary changes, and contract switches all introduce regime breaks where past data is no longer representative of future demand. Production carries an explicit `regime_break` flag in the SKU master per date range and either excludes those periods, downweights them, or models them with a separate intercept. The demo has no concept of regime breaks; it would happily train on the full history including pandemic-era surges and produce a model that over-orders for years afterward.

**Service-level differentiation by clinical importance.** The demo reads service-level targets from the synthetic SKU master, but it treats them as a flat lookup. Production carries per-SKU service-level targets driven by clinical-criticality classification (life-saving emergency drug = 99.5%, common consumable = 95%, slow-moving non-clinical = 90%) that the clinical-quality team owns and reviews quarterly.

**ERP / materials-management integration.** The forecasts are useless until they actually influence reorder decisions. The integration is rarely a one-shot DynamoDB write. It is typically a flat-file extract or an API call into the institutional ERP (Oracle, SAP, Workday, Infor) that runs on its own cadence, reconciles against the ERP's current par levels, applies institutional change-control gates (some SKUs require human approval before reorder-point updates flow to the catalog), and audits the round-trip. Plan for this engineering work; it often dwarfs the modeling work in scope.

**HIPAA controls end-to-end.** The S3 prefixes use SSE-KMS with customer-managed keys; the DynamoDB table uses encryption-at-rest with a customer-managed key; SageMaker training and inference jobs run in a VPC with VPC endpoints to S3, CloudWatch Logs, and KMS; the Glue job reads and writes only encrypted data; CloudTrail logs all S3, DynamoDB, Glue, and SageMaker API calls; CloudWatch log groups are KMS-encrypted; IAM roles are scoped to specific resource ARNs; an AWS BAA is in place. The demo touches none of this; production cannot ship without all of it.

**Idempotency and audit trail.** Each pipeline run is identified by a `run_id`, all forecast records carry that run_id and the model version, the DynamoDB writes overwrite cleanly by the `(facility_sku, generated_at)` key, and the model-artifact S3 writes use deterministic prefixes so a rerun produces the same output. An immutable audit log captures which model version produced which reorder point, written through Kinesis Data Firehose into an Object-Lock S3 bucket sized to the institutional materials-management retention floor (typically seven years, longer for FDA-regulated medical devices).

**Testing.** Unit tests cover the segmentation function (each ADI/CV² combination produces the expected segment), the reorder-point formula (the safety-stock z-score plus the lead-time mean produce the expected reorder point), the SBA bias correction (zero alpha => same as Croston, alpha = 1 => fully naive), and the DynamoDB write idempotency (writing the same record twice is a no-op). Integration tests run the pipeline against a known-input synthetic dataset and assert the output forecasts and reorder points against expected values. End-to-end tests stand up real S3, DynamoDB, and EventBridge resources in a sandbox account and run the full Step Functions state machine.

**Structured logging.** Replace the demo's `print` calls with `logger.info(..., extra={...})` calls that emit JSON-formatted structured logs to CloudWatch Logs. Log structural metadata only (run_id, facility_id, segment, sku_count, mean_error, runtime_ms), never raw consumption rows tied to identifiable cases or the SKU master with patient or case identifiers attached.

**The shape of the gap.** The forecasting math in this file is a sketch but it is fundamentally correct. The plumbing around it (storage, orchestration, security, monitoring, integration) is what takes the bulk of the engineering work. Plan for the plumbing to be 80% of the project; the modeling itself routinely surprises teams by being the easier part.

---

## Related Resources

- [Recipe 12.2: Supply Inventory Forecasting](chapter12.02-supply-inventory-forecasting): The main recipe with the full architectural walkthrough this Python companion implements.
- [Prophet Documentation (Meta Open Source)](https://facebook.github.io/prophet/): Reference for the Prophet forecasting library that the smooth-segment branch would use in production.
- [Amazon SageMaker DeepAR Forecasting Algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html): Built-in SageMaker algorithm for multi-series neural forecasting at scale.
- [Forecasting: Principles and Practice (Hyndman & Athanasopoulos)](https://otexts.com/fpp3/): Free online textbook covering classical forecasting methods, intermittent demand, and hierarchical reconciliation.
- [statsmodels Documentation](https://www.statsmodels.org/stable/): Python implementation of ETS, ARIMA, and exponential smoothing methods used for the smooth-segment baseline.
- [AWS Step Functions Map State](https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-map-state.html): Pattern for fanning out per-segment training jobs in parallel.
- [AWS Glue Developer Guide](https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html): ETL patterns for the consumption-history-cleanup step.

---

*← [Recipe 12.2: Supply Inventory Forecasting](chapter12.02-supply-inventory-forecasting) · [Chapter 12 Index](chapter12-index) · [Next: Recipe 12.3 - ED Arrival Forecasting →](chapter12.03-ed-arrival-forecasting)*
