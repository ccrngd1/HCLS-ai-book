# Recipe 12.6: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 12.6. It shows one way you could translate the revenue cycle cash flow forecasting pipeline into working Python using boto3 against Amazon S3 (here represented by a `MockS3` dict), AWS Glue (here represented by an in-process Python harmonization step), Amazon SageMaker (here represented by pure-Python `EmpiricalPaymentCurve`, `KaplanMeierEstimator`, and `PayerHazardModel` classes that stand in for real lifelines, scikit-survival, or DeepAR implementations), AWS Lambda (here represented by a plain Python function that runs the per-claim Monte Carlo sampling), AWS Step Functions (here represented by sequential function calls), Amazon DynamoDB (mocked with `MockTable`), Amazon EventBridge (mocked with `MockEventBus`), and Amazon CloudWatch (mocked with `MockCloudWatch`). The demo generates a synthetic AR ledger covering five payer types (Medicare fee-for-service, a state Medicaid plan, two commercial payers with different contract patterns, and self-pay patient responsibility) with realistic payment-curve shapes, a small denial-and-appeal cycle, and seasonality so you can see the harmonization, the per-payer payment-curve fitting, the per-claim cash-flow simulation, and the weekly aggregation work end-to-end without provisioning anything. It is not production-ready. There is no real S3 bucket, no real Glue ETL, no real SageMaker endpoint, no real Step Functions state machine, no real DynamoDB table, no real EventBridge bus, no real CloudWatch alarms, no integration with an actual 837 claim feed or 835 remittance feed, no contract modeling layer, no per-CPT severity adjustment, no per-Lambda IAM least privilege, no KMS customer-managed keys, no VPC endpoints, no continuous payer drift monitoring, and no recovery-agency or bad-debt write-off modeling. Think of it as the sketchpad version: useful for understanding the shape of a cash flow forecast that respects the per-payer-curve discipline, the survival-modeling discipline, the Monte Carlo composition discipline, and the working-capital framing this recipe demands. It is not something you would point at the CFO's Monday morning treasury meeting. Consider it a starting point, not a destination.
>
> The code maps to the five pseudocode steps from the main recipe: ingest and harmonize the AR ledger, the historical 835 remittance stream, and the payer-contract metadata so every open claim and every historical payment carries a canonical payer identifier, a service date, a billed amount, an expected allowed amount, and a denial flag (Step 1); fit per-payer payment-time distributions from the historical pairs of (claim_submitted_ts, payment_received_ts) using a Kaplan-Meier-style empirical survival estimator with hazard smoothing and right-censoring for still-open claims (Step 2); for every open AR claim, simulate N payment-date samples from the payer-specific distribution conditional on the claim's age and adjudication state, applying seasonality adjustments per sample and composing those samples into per-week cash inflow trajectories (Step 3); aggregate the sample-wise per-claim trajectories into per-week, per-payer percentile forecasts (P10, P50, P90) with a hospital-wide rollup and aging-bucket-conditional summary (Step 4); load the surfaced weekly forecasts to DynamoDB keyed by `forecast_week`, write the per-claim sample trajectories to S3 for variance-by-payer analysis, and emit pipeline-lifecycle events to EventBridge (Step 5). Patient-responsibility tail modeling (separate self-pay sub-model with payment-plan and statement-cycle features) is not implemented in this demo and is covered in the Gap to Production section. The synthetic payers, synthetic AR ledger, and synthetic payment curves in the demo are fictional; nothing in this file should be interpreted as real financial data from any real institution.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

The demo runs against the Python standard library plus boto3; no other packages are imported. Production deployments swap the demo's pure-Python estimators for real statistical libraries ([lifelines](https://lifelines.readthedocs.io/) for the Kaplan-Meier survival curves and the Cox proportional-hazards extensions, [scikit-survival](https://scikit-survival.readthedocs.io/) for the gradient-boosted survival models when payer behavior depends on claim-level features, [statsmodels](https://www.statsmodels.org/stable/) for the seasonality decomposition layered on top of the simulations, [NumPy](https://numpy.org/) and [SciPy](https://docs.scipy.org/doc/scipy/) for the vectorized Monte Carlo kernels, the SageMaker [DeepAR built-in algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html) for hierarchical multi-payer forecasts that share strength across small-volume payers); the Gap to Production section spells out the substitutions.

In production you would also configure an Amazon S3 bucket for the raw 837 claim landing zone, the raw 835 remittance landing zone, the harmonized AR ledger prefix, the per-payer payment-curve prefix, the per-claim sample-trajectory prefix, the weekly forecast prefix, and the model-artifact prefix (one prefix per concern, all SSE-KMS encrypted with a customer-managed key), an AWS Glue job that ingests new 835 files and updates the AR ledger nightly, an Amazon SageMaker training job that refits the per-payer payment curves weekly and writes the artifacts back to S3, an AWS Lambda function that runs the per-claim Monte Carlo simulation across the open AR ledger, an AWS Step Functions state machine that orchestrates the weekly cycle (harmonize -> fit curves -> simulate -> aggregate -> deliver) with retries and `Catch` blocks for transient failures, an Amazon DynamoDB table for the weekly cash flow forecasts keyed by `forecast_week` with the per-payer breakdown as a sort-key sub-record, an Amazon EventBridge schedule that triggers the Step Functions state machine weekly, Amazon CloudWatch dashboards and alarms for pipeline failures, payer-curve drift, forecast-vs-actual variance, and AR aging shifts, and a thin integration layer that exposes the forecasts to the finance team's treasury dashboard or working-capital spreadsheet. The demo replaces all of these with a single in-process Python file so the focus stays on the harmonization, the survival-curve math, the Monte Carlo composition, and the per-week aggregation rather than on the platform plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `s3:GetObject` and `s3:PutObject` on the raw-claim prefix, the raw-remittance prefix, the harmonized AR ledger prefix, the payer-curve prefix, the sample-trajectory prefix, the weekly forecast prefix, and the model-artifact prefix
- `glue:StartJobRun` and `glue:GetJobRun` on the AR ingestion Glue job, plus the Glue service role's permissions for the ETL job
- `sagemaker:CreateTrainingJob`, `sagemaker:DescribeTrainingJob`, `sagemaker:CreateModel`, `sagemaker:CreateEndpointConfig`, `sagemaker:UpdateEndpoint`, and `sagemaker:InvokeEndpoint` on the per-payer payment-curve models
- `lambda:InvokeFunction` on the Monte Carlo simulation Lambda
- `dynamodb:BatchWriteItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, and `dynamodb:GetItem` on the `cash-flow-forecasts` table, scoped to the specific table ARN
- `events:PutEvents` on the cash-flow-events bus for emitting pipeline-lifecycle events (run started, curves fit, simulation completed, forecast written, drift alarm raised)
- `states:StartExecution` on the cash-flow Step Functions state machine for the weekly forecast run
- `cloudwatch:PutMetricData` for the operational metrics (per-payer simulated mean payment lag, per-payer denial rate, forecast variance vs. actuals, AR aging buckets, weekly forecast error)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the S3 prefixes, the DynamoDB table, and the model-artifact bucket

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The Glue ingestion job has read access to the raw-remittance prefix and write access to the harmonized AR ledger prefix, but no DynamoDB or SageMaker permissions. The Monte Carlo Lambda has read access to the payer-curve prefix and the AR ledger prefix, plus write access to the sample-trajectory prefix and the weekly forecast DynamoDB table, but no raw-claim permissions. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Revenue-cycle data is PHI by association.** A claim record carries patient identifier, service date, CPT code, ICD code, billed amount, payer, allowed amount, denial reason, and a free-text remit memo. Aggregated cash forecasts derived from these claims are still PHI when they retain any patient-level granularity. Every storage and compute service that touches this pipeline must be on the [HIPAA eligible services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/) list, every storage layer must be encrypted with customer-managed KMS keys, every network hop must be inside the institutional VPC with no public path, and CloudTrail must log every data-plane API call. Even when the surfaced forecast is "expected cash for week of 2026-06-01 = $4.2M," the upstream join keys remain PHI.
- **Each payer is its own time series.** Medicare fee-for-service pays differently from Medicaid, Medicaid pays differently from a commercial insurer, and a commercial insurer with a delegated-risk contract pays differently from one with a fee-for-service contract. The pipeline forecasts each payer independently and then aggregates, because mixing them produces a model that learns the average curve and is wrong for every payer in different ways.
- **Time-to-payment is a survival problem, not a regression problem.** A claim submitted today either pays in 14 days, or 28 days, or 45 days, or it gets denied and the denial-appeal cycle resets the clock. The right framing is a survival curve: probability of payment by day d. Open claims are right-censored (you have not yet observed their payment date) and the estimator has to handle that.
- **The denial cycle is a separate sub-process.** First-pass denials happen on roughly 5 to 12% of claims for most provider organizations. Of those, 60 to 80% are recoverable through appeal, and the appeal adds 30 to 90 days to the payment timeline. The pipeline either models this as a two-stage process (first-pass payment curve plus a denial-and-appeal sub-curve) or rolls it into the headline curve at the cost of less interpretability.
- **Patient responsibility is its own animal.** After the primary payer adjudicates, whatever the patient owes (deductible, coinsurance, copay) shifts to the patient AR bucket, which has dramatically different dynamics. Self-pay AR has long tails, low recovery rates, and is sensitive to statement cycle, payment-plan availability, and the presence or absence of pre-collection workflows. Production pipelines either model self-pay separately or accept that the self-pay tail is the dominant uncertainty in the longer-horizon forecast.
- **Contract changes break the model overnight.** A new fee schedule with a major payer, a renegotiated denial-appeal escalation path, a switch from delegated risk to fee-for-service, all of these shift the payment curve in ways the historical data does not predict. The pipeline needs an explicit contract-effective-date awareness so the curves train only on data after the relevant contract took effect, and an alert when the live data starts to diverge from the trained curve.
- **DynamoDB rejects Python `float`.** Every dollar amount, probability, day count, and percentile passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses many Lambdas, Glue jobs, and SageMaker endpoints into a single Python file.** In production the AR ingestion Glue job, the curve-fitting SageMaker training job, the Monte Carlo Lambda, the aggregation Lambda, and the DynamoDB-loader Lambda are separate units of work with their own IAM roles, error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the payer catalog, the per-payer denial-and-appeal parameters, the seasonality factors, the Monte Carlo sample count, and the synthetic-data parameters are what you would change between environments.

```python
import json
import logging
import math
import random
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import mean, median, stdev

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights for cross-call investigation.
# Revenue-cycle records are PHI by association; log structural
# metadata only (run_id, payer_id, claim_count, total_amount_band,
# runtime_ms), never raw claim numbers, never patient identifiers,
# never service dates tied to identifiable encounters, never the
# per-claim denial-reason text.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from S3, DynamoDB, EventBridge,
# CloudWatch, and SageMaker. The weekly cash-flow pipeline is a
# scheduled batch job that touches every open claim, so retries
# should be quick and capped. A stuck dependency must not balloon
# a 30-minute weekly window into a multi-hour incident that blocks
# the Monday morning treasury review.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across function calls within the
# pipeline so each call does not pay the connection cost. The
# demo wires up MockS3 / MockTable / MockEventBus / MockCloudWatch
# via run_demo() and never touches these real handles; they are
# staged here so production wiring is a one-line swap. boto3
# client and resource construction is lazy (no network call until
# first use), so the unused handles are free at import.
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
sagemaker_runtime  = boto3.client("sagemaker-runtime",
                                  region_name=REGION,
                                  config=BOTO3_RETRY_CONFIG)
lambda_client      = boto3.client("lambda",
                                  region_name=REGION,
                                  config=BOTO3_RETRY_CONFIG)
# The `sagemaker_runtime` handle is staged for production inference
# calls (InvokeEndpoint) against a deployed per-payer payment-curve
# model. The control-plane training-job calls would use
# `boto3.client("sagemaker")` instead. The `lambda_client` handle
# is staged for the production path where Step Functions invokes the
# Monte Carlo Lambda directly; in this demo the simulation runs
# in-process. Neither handle is exercised by the demo; they are here
# so the production wiring is visible at a glance.

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do
# not exist; see run_demo() at the bottom.
RAW_CLAIM_BUCKET           = "rcm-cash-flow-raw-837"
RAW_REMIT_BUCKET           = "rcm-cash-flow-raw-835"
HARMONIZED_AR_BUCKET       = "rcm-cash-flow-ar-ledger"
PAYER_CURVE_BUCKET         = "rcm-cash-flow-payer-curves"
SAMPLE_TRAJECTORY_BUCKET   = "rcm-cash-flow-sample-trajectories"
FORECAST_BUCKET            = "rcm-cash-flow-forecasts"
MODEL_ARTIFACT_BUCKET      = "rcm-cash-flow-models"
CASH_FORECAST_TABLE        = "cash-flow-forecasts"
CASH_FORECAST_EVENT_BUS    = "cash-flow-events-bus"
CLOUDWATCH_NAMESPACE       = "RevenueCycleCashFlow"

# --- Versioning ---
# Every weekly forecast carries the model version and the contract
# library version active at the time of generation. This is how
# a future audit reconstructs which curves and which contract
# assumptions produced which forecast on which week.
PIPELINE_VERSION         = "cash-flow-v1.3"
CONTRACT_LIBRARY_VERSION = "contracts-2026-Q2"

# --- Forecast Parameters ---
# 13-week (one quarter) horizon is the default for cash-flow
# forecasts because that is the standard treasury-planning window.
# 26-week and 52-week variants are reasonable extensions; the
# longer the horizon, the more the patient-responsibility tail
# dominates the uncertainty.
DEFAULT_HORIZON_WEEKS         = 13
DEFAULT_MONTE_CARLO_SAMPLES   = 1000
DEFAULT_HISTORY_LOOKBACK_DAYS = 365 * 2

# --- Payer Catalog ---
# Per-payer configuration covering the small panel the demo
# operates on. Production maintains a curated table with hundreds
# of entries managed by the institutional revenue-cycle team.
# Each entry carries: the canonical payer identifier, the payer
# class (medicare / medicaid / commercial / self_pay / wc_auto),
# the typical first-pass denial rate, the appeal recovery rate
# (probability that a denied claim is recovered through appeal),
# the appeal lag in days, the contract effective date (curves
# train only on data after this), and the display name for
# surfaced payloads.
PAYER_CATALOG = {
    "MEDI-FFS-001": {
        "display":               "Medicare FFS",
        "payer_class":           "medicare",
        "first_pass_denial_rate": 0.04,
        "appeal_recovery_rate":   0.65,
        "appeal_lag_days_mean":   45,
        "appeal_lag_days_sd":     12,
        "contract_effective_date": "2024-01-01",
    },
    "MCAID-STATE-001": {
        "display":               "State Medicaid",
        "payer_class":           "medicaid",
        "first_pass_denial_rate": 0.09,
        "appeal_recovery_rate":   0.55,
        "appeal_lag_days_mean":   60,
        "appeal_lag_days_sd":     18,
        "contract_effective_date": "2025-07-01",
    },
    "COMM-BCBS-001": {
        "display":               "Commercial BCBS Plan",
        "payer_class":           "commercial",
        "first_pass_denial_rate": 0.07,
        "appeal_recovery_rate":   0.70,
        "appeal_lag_days_mean":   38,
        "appeal_lag_days_sd":     10,
        "contract_effective_date": "2025-10-01",
    },
    "COMM-NATIONAL-001": {
        "display":               "Commercial National Plan",
        "payer_class":           "commercial",
        "first_pass_denial_rate": 0.11,
        "appeal_recovery_rate":   0.60,
        "appeal_lag_days_mean":   42,
        "appeal_lag_days_sd":     11,
        "contract_effective_date": "2025-04-01",
    },
    "SELF-PAY-001": {
        "display":               "Self-Pay / Patient Responsibility",
        "payer_class":           "self_pay",
        "first_pass_denial_rate": 0.0,    # no formal denials, just non-payment
        "appeal_recovery_rate":   0.0,
        "appeal_lag_days_mean":   0,
        "appeal_lag_days_sd":     0,
        "contract_effective_date": "2020-01-01",
    },
}

# --- Seasonality and Calendar ---
# Multiplicative seasonality factors applied at the per-week
# aggregation step. Production fits these from data using an
# STL or X-13ARIMA-SEATS decomposition; the demo uses fixed
# illustrative factors that capture the typical "Medicare and
# Medicaid pay slower in late December and early January due
# to year-end claim re-routing" pattern.
SEASONALITY_BY_WEEK_OF_YEAR = {
    1:  0.92, 2:  0.95, 3:  0.98, 4:  1.00,
    52: 0.88, 51: 0.90, 50: 0.95,
    27: 0.96, 28: 0.97,    # 4th of July week typically a bit slower
}

# --- AR Aging Buckets ---
# Standard healthcare AR aging buckets for surfaced reporting.
# The forecast surfaces aging-bucket-conditional probabilities
# so the finance team sees not just total expected cash but
# how much of it comes from "fresh" AR vs. "old" AR.
AR_AGING_BUCKETS = [
    ("0-30",   0,   30),
    ("31-60",  31,  60),
    ("61-90",  61,  90),
    ("91-120", 91,  120),
    ("121+",   121, 9999),
]

# --- Synthetic Data ---
# Knobs for the demo's synthetic-history generator. The ranges
# produce a small but realistic-shaped two-year history with
# five payers so you can see the pipeline fit per-payer curves
# and forecast cash by week.
SYNTHETIC_HISTORICAL_DAYS = DEFAULT_HISTORY_LOOKBACK_DAYS
SYNTHETIC_OPEN_AR_COUNT   = 800
SYNTHETIC_RANDOM_SEED     = 42

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("RAW_CLAIM_BUCKET",         RAW_CLAIM_BUCKET),
    ("RAW_REMIT_BUCKET",         RAW_REMIT_BUCKET),
    ("HARMONIZED_AR_BUCKET",     HARMONIZED_AR_BUCKET),
    ("PAYER_CURVE_BUCKET",       PAYER_CURVE_BUCKET),
    ("SAMPLE_TRAJECTORY_BUCKET", SAMPLE_TRAJECTORY_BUCKET),
    ("FORECAST_BUCKET",          FORECAST_BUCKET),
    ("MODEL_ARTIFACT_BUCKET",    MODEL_ARTIFACT_BUCKET),
    ("CASH_FORECAST_TABLE",      CASH_FORECAST_TABLE),
    ("CASH_FORECAST_EVENT_BUS",  CASH_FORECAST_EVENT_BUS),
    ("CLOUDWATCH_NAMESPACE",     CLOUDWATCH_NAMESPACE),
]:
    assert _value, f"{_name} must be set before deploying."

def _to_decimal(value):
    """Convert numeric values to Decimal for DynamoDB-safe writes.

    DynamoDB rejects Python float at the SDK boundary because
    floating-point cannot represent every decimal value exactly.
    Pass everything numeric through this helper before any
    PutItem, BatchWriteItem, or UpdateItem call. Pandas and numpy
    types are not Decimal-friendly out of the box, so the helper
    covers the common cases (int, float, str-of-number, None) and
    lets exotic types fail loudly rather than silently.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        # bool is a subclass of int in Python; intercept before
        # the int/float branch so True does not silently coerce
        # to Decimal('1'). DynamoDB has a native BOOL type that
        # accepts Python bool directly.
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(round(float(value), 6)))
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(f"Cannot convert {type(value).__name__} to Decimal")

def _iso_date(d):
    """Format a date or datetime as an ISO date string."""
    if isinstance(d, datetime):
        return d.date().isoformat()
    return d.isoformat()

def _week_of_year_iso(d):
    """Return the ISO week-of-year integer for a date."""
    return d.isocalendar()[1]
```

---

## Mocks and Synthetic Data

The demo never touches a real S3 bucket, DynamoDB table, EventBridge bus, or SageMaker endpoint. The mocks below stand in for those services so the focus stays on the cash-flow forecasting logic. They print what they would write rather than failing, which makes the demo runnable without any AWS resources provisioned.

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
            pk = Item["forecast_week"]
            sk = Item["payer_id"]
            self.table.items[(pk, sk)] = dict(Item)
            self.table.write_count += 1

    def batch_writer(self):
        return self._BatchWriter(self)

    def put_item(self, Item):
        pk = Item["forecast_week"]
        sk = Item["payer_id"]
        self.items[(pk, sk)] = dict(Item)
        self.write_count += 1

class MockEventBus:
    """In-memory stand-in for EventBridge.

    Production uses boto3.client('events').put_events(...). The
    mock accumulates events so the demo can show what would have
    been emitted at each pipeline stage.
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
    have been emitted (per-payer curve fit metrics, forecast
    variance, AR aging shifts).
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

def _draw_payment_lag(payer_id, rng):
    """Sample a payment-lag-in-days for a single claim from a payer-shaped distribution.

    Each payer class has a different "shape" of payment lag.
    Medicare FFS pays on a tight, predictable schedule centered
    around 14-21 days. State Medicaid is wider with a longer
    right tail. Commercial payers vary; the BCBS plan in this
    demo pays a bit faster than the national plan. Self-pay has
    a very long, lognormal-like tail that captures statement
    cycles plus the realities of patient payment behavior.

    Production fits these distributions empirically from
    historical 837 / 835 pairs; the demo uses analytic shapes
    so the synthetic data is reproducible.
    """
    if payer_id == "MEDI-FFS-001":
        # Tight gaussian-ish around 17 days
        return max(1, int(rng.gauss(17, 4)))
    if payer_id == "MCAID-STATE-001":
        # Wider, slight right skew (lognormal approximation)
        return max(1, int(math.exp(rng.gauss(math.log(28), 0.35))))
    if payer_id == "COMM-BCBS-001":
        return max(1, int(rng.gauss(22, 6)))
    if payer_id == "COMM-NATIONAL-001":
        return max(1, int(rng.gauss(31, 9)))
    if payer_id == "SELF-PAY-001":
        # Very long right tail
        return max(7, int(math.exp(rng.gauss(math.log(60), 0.55))))
    return max(1, int(rng.gauss(30, 10)))

def generate_synthetic_remittance_history(
        history_days=SYNTHETIC_HISTORICAL_DAYS,
        seed=SYNTHETIC_RANDOM_SEED):
    """Generate synthetic historical (claim_submitted, payment_received) pairs.

    Production reads from S3 prefixes populated by an 837/835
    ingestion pipeline. The demo synthesizes per-payer histories
    with realistic payment-lag shapes plus a denial-and-appeal
    sub-process so the curve fitter has something to work with.

    Returns a list of historical claim records, each with:
      claim_id, payer_id, submitted_date, billed_amount,
      expected_allowed_amount, denial_flag, denial_reason,
      payment_received_date (None if still open),
      payment_amount (None if still open).
    """
    rng = random.Random(seed)
    end_d   = date.today()
    start_d = end_d - timedelta(days=history_days)

    records = []
    # ~ proportional volume by payer (Medicare and the national
    # commercial plan are the largest in this synthetic shop)
    payer_weights = {
        "MEDI-FFS-001":      0.32,
        "MCAID-STATE-001":   0.18,
        "COMM-BCBS-001":     0.14,
        "COMM-NATIONAL-001": 0.24,
        "SELF-PAY-001":      0.12,
    }
    payer_ids = list(payer_weights.keys())
    payer_cdf = []
    cum = 0.0
    for p in payer_ids:
        cum += payer_weights[p]
        payer_cdf.append(cum)

    # ~ 60 claims per day on average
    daily_volume_mean = 60
    cursor = start_d
    while cursor <= end_d:
        n_today = max(0, int(rng.gauss(daily_volume_mean, 10)))
        for _ in range(n_today):
            r = rng.random()
            chosen = payer_ids[0]
            for i, c in enumerate(payer_cdf):
                if r <= c:
                    chosen = payer_ids[i]
                    break
            payer = PAYER_CATALOG[chosen]
            billed   = round(rng.uniform(180, 4200), 2)
            allowed  = round(billed * rng.uniform(0.32, 0.78), 2)

            denied_first_pass = (rng.random()
                                 < payer["first_pass_denial_rate"])
            if denied_first_pass and chosen != "SELF-PAY-001":
                # Denial path: appeal happens in 30-90% of cases
                appealed = rng.random() < 0.85
                if appealed:
                    recovered = rng.random() < payer["appeal_recovery_rate"]
                    if recovered:
                        first_lag    = _draw_payment_lag(chosen, rng)
                        appeal_extra = max(7, int(
                            rng.gauss(payer["appeal_lag_days_mean"],
                                      payer["appeal_lag_days_sd"])))
                        total_lag = first_lag + appeal_extra
                        pay_d = cursor + timedelta(days=total_lag)
                        if pay_d <= end_d:
                            records.append({
                                "claim_id":        str(uuid.uuid4()),
                                "payer_id":        chosen,
                                "submitted_date":  cursor.isoformat(),
                                "billed_amount":   billed,
                                "expected_allowed_amount": allowed,
                                "denial_flag":     True,
                                "denial_reason":   "CO-16",  # synthetic
                                "payment_received_date": pay_d.isoformat(),
                                "payment_amount":  round(allowed * rng.uniform(0.85, 1.0), 2),
                            })
                        else:
                            records.append({
                                "claim_id":        str(uuid.uuid4()),
                                "payer_id":        chosen,
                                "submitted_date":  cursor.isoformat(),
                                "billed_amount":   billed,
                                "expected_allowed_amount": allowed,
                                "denial_flag":     True,
                                "denial_reason":   "CO-16",
                                "payment_received_date": None,
                                "payment_amount":  None,
                            })
                    else:
                        # Denied and not recovered: write-off, no payment
                        records.append({
                            "claim_id":        str(uuid.uuid4()),
                            "payer_id":        chosen,
                            "submitted_date":  cursor.isoformat(),
                            "billed_amount":   billed,
                            "expected_allowed_amount": allowed,
                            "denial_flag":     True,
                            "denial_reason":   "CO-50",
                            "payment_received_date": None,
                            "payment_amount":  0.0,
                        })
                else:
                    # Denied, never appealed: write-off
                    records.append({
                        "claim_id":        str(uuid.uuid4()),
                        "payer_id":        chosen,
                        "submitted_date":  cursor.isoformat(),
                        "billed_amount":   billed,
                        "expected_allowed_amount": allowed,
                        "denial_flag":     True,
                        "denial_reason":   "CO-29",
                        "payment_received_date": None,
                        "payment_amount":  0.0,
                    })
            else:
                lag = _draw_payment_lag(chosen, rng)
                pay_d = cursor + timedelta(days=lag)
                if pay_d <= end_d:
                    records.append({
                        "claim_id":        str(uuid.uuid4()),
                        "payer_id":        chosen,
                        "submitted_date":  cursor.isoformat(),
                        "billed_amount":   billed,
                        "expected_allowed_amount": allowed,
                        "denial_flag":     False,
                        "denial_reason":   None,
                        "payment_received_date": pay_d.isoformat(),
                        "payment_amount":  round(allowed * rng.uniform(0.92, 1.0), 2),
                    })
                else:
                    # Submitted recently, payment not yet observed:
                    # this is right-censored data the survival
                    # estimator must handle correctly.
                    records.append({
                        "claim_id":        str(uuid.uuid4()),
                        "payer_id":        chosen,
                        "submitted_date":  cursor.isoformat(),
                        "billed_amount":   billed,
                        "expected_allowed_amount": allowed,
                        "denial_flag":     False,
                        "denial_reason":   None,
                        "payment_received_date": None,
                        "payment_amount":  None,
                    })
        cursor += timedelta(days=1)

    return records

def generate_synthetic_open_ar(
        records, n_open=SYNTHETIC_OPEN_AR_COUNT, seed=SYNTHETIC_RANDOM_SEED + 1):
    """Carve out the open AR ledger from the synthesized history.

    The "open AR" is the subset of records with no payment yet
    received (right-censored). Real pipelines pull this from the
    practice management system or general ledger; the demo
    derives it from the synthetic history so the open ledger
    is consistent with the historical curve.
    """
    open_ar = [r for r in records
               if r.get("payment_received_date") is None
               and r.get("payment_amount") is None]
    # Trim to the requested size while preserving payer mix.
    rng = random.Random(seed)
    rng.shuffle(open_ar)
    return open_ar[:n_open]
```

---

## Step 1: Ingest and Harmonize the AR Ledger

This step takes raw 837 claim records, raw 835 remittance records, and the contract metadata, then produces a single harmonized AR ledger row per claim with a canonical payer identifier, a service date, the billed amount, the expected allowed amount, the denial flag, and (when known) the payment-received date and payment amount. In production this is an AWS Glue job that runs nightly against the raw S3 prefixes; the demo does the equivalent in plain Python so you can trace what each transform accomplishes.

```python
def harmonize_ar_records(raw_remits, s3, bucket):
    """Step 1: Normalize raw remittance records into the AR ledger.

    See pseudocode Step 1 in the main recipe. Each input record
    is already in a canonical-ish shape (the synthetic generator
    produced it that way), so the harmonization logic here mostly
    validates fields, enforces the payer-catalog mapping, and
    writes the output partitioned by payer and submission month.

    Production also handles 837 to 835 claim-line reconciliation,
    cross-payer take-back / refund linkage, and contract-effective-
    date filtering. The demo skips those for clarity but calls
    them out in the gap-to-production section.
    """
    harmonized = []
    quarantined = 0
    # Use a single run timestamp for the entire batch so all records
    # carry the same as_of value (consistent with the discipline in
    # simulate_cash_flow and fit_payer_payment_curves).
    batch_ts = datetime.now(timezone.utc)
    for raw in raw_remits:
        if raw["payer_id"] not in PAYER_CATALOG:
            logger.warning("unknown payer id: %s", raw["payer_id"])
            quarantined += 1
            continue

        # Validate required fields. Production has a much richer
        # validation layer (X12 line-level checks, NPI validation,
        # CPT code presence, modifier consistency).
        if raw.get("submitted_date") is None or raw.get("billed_amount") is None:
            quarantined += 1
            continue

        # Filter by contract effective date. Records before the
        # current contract took effect must not feed the curves
        # because the dynamics changed.
        catalog       = PAYER_CATALOG[raw["payer_id"]]
        effective_d   = date.fromisoformat(catalog["contract_effective_date"])
        submitted_d   = date.fromisoformat(raw["submitted_date"])
        in_contract   = submitted_d >= effective_d

        # Compute the lag in days when the payment is observed;
        # leave None for right-censored records.
        if raw.get("payment_received_date") is not None:
            paid_d = date.fromisoformat(raw["payment_received_date"])
            payment_lag_days = (paid_d - submitted_d).days
        else:
            payment_lag_days = None

        rec = {
            "claim_id":               raw["claim_id"],
            "payer_id":               raw["payer_id"],
            "payer_class":            catalog["payer_class"],
            "submitted_date":         raw["submitted_date"],
            "billed_amount":          float(raw["billed_amount"]),
            "expected_allowed_amount": float(raw.get("expected_allowed_amount") or 0.0),
            "denial_flag":            bool(raw.get("denial_flag")),
            "denial_reason":          raw.get("denial_reason"),
            "payment_received_date":  raw.get("payment_received_date"),
            "payment_amount":         (float(raw["payment_amount"])
                                       if raw.get("payment_amount") is not None
                                       else None),
            "payment_lag_days":       payment_lag_days,
            "in_contract":            in_contract,
            "as_of":                  batch_ts.isoformat(),
        }

        # Partition the harmonized output by payer and submission
        # month so downstream curve fitting can read it efficiently.
        sub_d = date.fromisoformat(rec["submitted_date"])
        s3_key = (f"payer={rec['payer_id']}/"
                  f"year={sub_d.year:04d}/month={sub_d.month:02d}/"
                  f"{rec['claim_id']}.json")
        s3.put_object(Bucket=bucket, Key=s3_key,
                      Body=json.dumps(rec))
        harmonized.append(rec)

    logger.info(
        "Harmonized %d of %d raw records (%d quarantined)",
        len(harmonized), len(raw_remits), quarantined)
    return harmonized
```

---

## Step 2: Fit Per-Payer Payment-Time Distributions

For each payer, compute the empirical payment-time distribution from the historical (submitted_ts, payment_received_ts) pairs. This is a survival problem: the event of interest is "claim paid," and open (still-unpaid) claims are right-censored. The Kaplan-Meier estimator handles censoring correctly by accounting for the at-risk population at each observed payment day. Because the curve is fit on all historical payments (including those that were denied and later recovered through appeal), it absorbs the denial-and-appeal dynamics by construction. Denied-then-recovered claims simply appear as longer-lag payments in the training data.

```python
class KaplanMeierEstimator:
    """Pedagogical Kaplan-Meier survival estimator with right-censoring.

    For revenue cycle: the survival function S(t) is the
    probability that a claim is still unpaid at day t after
    submission. The complement 1 - S(t) is the cumulative
    payment probability, which is what the Monte Carlo step in
    Step 3 samples from.

    Production uses lifelines.KaplanMeierFitter, which handles
    confidence intervals, point-wise variance estimation
    (Greenwood's formula), and the smoothing options the demo
    skips. The pure-Python version below makes the math visible.
    """

    name = "kaplan_meier"

    def __init__(self):
        self.times      = []     # observed event/censor times (days)
        self.events     = []     # 1 if event (payment), 0 if censored
        self.curve      = []     # list of (day, survival_prob) tuples

    def fit(self, durations, event_observed):
        """Fit the survival curve from (durations, event_observed) pairs.

        durations: list of integer days from submission to either
                   payment (event=1) or as-of-now (event=0).
        event_observed: list of 0/1 flags matching durations.
        """
        if len(durations) != len(event_observed):
            raise ValueError("durations and event_observed must align")
        if not durations:
            self.curve = [(0, 1.0)]
            return self

        pairs = sorted(zip(durations, event_observed))
        self.times  = [p[0] for p in pairs]
        self.events = [p[1] for p in pairs]

        # Group by unique day. At each day, count the number of
        # events (claims paid) and the at-risk population (claims
        # not yet paid, not yet censored before that day).
        unique_days = sorted(set(self.times))
        n_at_risk   = len(self.times)
        survival    = 1.0
        curve       = [(0, 1.0)]
        idx_pos     = 0
        for day in unique_days:
            d_count    = 0
            c_count    = 0
            while idx_pos < len(pairs) and pairs[idx_pos][0] == day:
                if pairs[idx_pos][1] == 1:
                    d_count += 1
                else:
                    c_count += 1
                idx_pos += 1
            if n_at_risk > 0 and d_count > 0:
                survival *= (1.0 - d_count / n_at_risk)
            curve.append((day, survival))
            n_at_risk -= (d_count + c_count)
        # Anchor a long-tail terminal point so the cumulative
        # probability function is well-defined across the
        # forecast horizon. If there are right-censored claims
        # remaining, treat them as never-paying for forecast
        # purposes; the bad-debt model handles those separately.
        if n_at_risk > 0:
            curve.append((max(unique_days) + 365, survival))
        self.curve = curve
        return self

    def survival_at(self, day):
        """Interpolate the survival probability at an arbitrary day."""
        if not self.curve:
            return 1.0
        if day <= self.curve[0][0]:
            return self.curve[0][1]
        if day >= self.curve[-1][0]:
            return self.curve[-1][1]
        # Step function: find the largest tabulated day <= query.
        prev = self.curve[0][1]
        for d, s in self.curve:
            if d > day:
                return prev
            prev = s
        return prev

    def cumulative_payment_prob(self, day):
        """1 - S(t): probability that the claim has paid by day t."""
        return 1.0 - self.survival_at(day)

    def sample_payment_day(self, max_horizon_days, rng):
        """Inverse-CDF sample of a payment day.

        Returns an integer day in [1, max_horizon_days], or None
        if the sampled u-quantile lies above the cumulative
        payment probability at the horizon (interpreted as "claim
        does not pay within the horizon").
        """
        u = rng.random()
        # If u exceeds the cumulative payment probability at the
        # horizon, the claim does not pay within the window.
        if u >= self.cumulative_payment_prob(max_horizon_days):
            return None
        # Walk the curve to find the smallest day where the
        # cumulative payment probability has reached u.
        for d, s in self.curve:
            if (1.0 - s) >= u:
                if d <= max_horizon_days:
                    return max(1, d)
                return None
        return None

def fit_payer_payment_curves(harmonized, as_of_dt=None,
                             history_lookback_days=DEFAULT_HISTORY_LOOKBACK_DAYS):
    """Step 2: Fit one Kaplan-Meier curve per payer.

    See pseudocode Step 2 in the main recipe. The curve treats
    paid claims as events and still-open claims as right-censored
    at the days-since-submission-to-now value.

    Returns a dict keyed by payer_id with the fitted curve and
    a small summary block (sample count, denial rate, median
    days-to-payment).
    """
    if as_of_dt is None:
        as_of_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff_d = as_of_dt.date() - timedelta(days=history_lookback_days)

    by_payer = defaultdict(list)
    for r in harmonized:
        if not r.get("in_contract"):
            continue
        sub_d = date.fromisoformat(r["submitted_date"])
        if sub_d < cutoff_d:
            continue
        # Self-pay needs separate handling because the dynamics
        # are categorically different. The demo fits it the same
        # way; production splits it out.
        by_payer[r["payer_id"]].append(r)

    curves = {}
    for payer_id, recs in by_payer.items():
        durations = []
        events    = []
        for r in recs:
            if r.get("payment_received_date") is not None and r.get("payment_amount") and r["payment_amount"] > 0:
                # Paid event. Duration = lag from submission to
                # payment-received.
                lag = r["payment_lag_days"]
                if lag is None or lag <= 0:
                    continue
                durations.append(int(lag))
                events.append(1)
            elif r.get("payment_received_date") is None and r.get("payment_amount") is None:
                # Right-censored. Duration = lag from submission
                # to as-of-now.
                sub_d = date.fromisoformat(r["submitted_date"])
                age_days = max(1, (as_of_dt.date() - sub_d).days)
                durations.append(age_days)
                events.append(0)
            else:
                # Denied + zero payment: model as never-paying for
                # the cash-flow curve. The denial-recovery model
                # produces its own forecast for the appeal cohort.
                pass

        if not durations:
            curves[payer_id] = None
            continue

        km = KaplanMeierEstimator().fit(durations, events)
        denial_count = sum(1 for r in recs if r.get("denial_flag"))
        paid_lags    = [r["payment_lag_days"] for r in recs
                        if r.get("payment_lag_days") and r["payment_lag_days"] > 0]
        median_lag   = median(paid_lags) if paid_lags else None
        curves[payer_id] = {
            "payer_id":           payer_id,
            "estimator":          km,
            "sample_count":       len(durations),
            "event_count":        sum(events),
            "denial_rate":        denial_count / len(recs) if recs else 0.0,
            "median_paid_lag":    median_lag,
            "fit_as_of":          as_of_dt.isoformat(),
            "history_window_days": history_lookback_days,
        }

    logger.info("Fit payment curves for %d payers", len(curves))
    return curves
```

---

## Step 3: Monte Carlo Per-Claim Cash Flow Simulation

For every open AR claim, sample N payment-day draws from the payer's fitted curve. The per-payer Kaplan-Meier curve is fit on all historical payments for that payer, which means the curve already absorbs the denied-and-recovered cohort by construction (those claims simply appear as longer-lag payments in the training data). The demo uses the curve directly without a separate denial sub-process. This avoids the double-counting problem that arises when you sample from a curve that already includes recovered-from-appeal claims and then layer an explicit denial-recovery branch on top. Production systems that want interpretable denial-specific forecasts can instead fit the curve on clean-adjudication records only (excluding denial_flag=True) and explicitly compose a denial-recovery sub-distribution; the Gap to Production section covers this extension.

```python
def simulate_claim_payment(claim, curve, payer_catalog,
                           horizon_weeks, as_of_dt, rng):
    """Sample a single (payment_date, payment_amount) for one open claim.

    Returns (payment_date, payment_amount) or (None, 0.0) if
    the claim does not pay within the horizon.

    The per-payer curve absorbs all payment-path outcomes by
    construction: clean first-pass payments land at the short
    end of the curve, denied-then-recovered payments land at
    the long end, and never-recovered claims contribute to the
    right-censored mass. Sampling from the curve directly
    produces a realistic payment-date draw without the need for
    an explicit denial sub-process.

    Production extensions that want denial-specific
    interpretability should fit on clean-adjudication records
    only and compose the denial-recovery sub-distribution
    explicitly (see Gap to Production).
    """
    payer = payer_catalog[claim["payer_id"]]
    horizon_days = horizon_weeks * 7

    # Sample a payment day from the payer's fitted survival curve.
    # The curve's right-censored mass means some draws return None
    # (claim does not pay within the horizon). This is the
    # correct behavior: it represents the probability that the
    # claim will not convert to cash within the forecast window.
    sampled_day = curve["estimator"].sample_payment_day(horizon_days, rng)
    if sampled_day is None or sampled_day > horizon_days:
        return (None, 0.0)
    pay_date = as_of_dt.date() + timedelta(days=sampled_day)

    # Payment amount: the expected allowed amount with a small
    # random adjustment representing contractual adjustments,
    # partial denials, and coordination-of-benefits offsets.
    # The 0.88-to-1.0 range is a simplification; production
    # conditions this on payer class and claim characteristics.
    amt = (claim.get("expected_allowed_amount") or 0.0) * rng.uniform(0.88, 1.0)
    return (pay_date, round(amt, 2))

def _seasonality_factor(week_of_year):
    """Return the multiplicative seasonality factor for a week."""
    return SEASONALITY_BY_WEEK_OF_YEAR.get(week_of_year, 1.0)

def _ar_aging_bucket(submitted_date_str, as_of_dt):
    """Return the AR aging bucket label for a claim."""
    sub_d = date.fromisoformat(submitted_date_str)
    age_days = (as_of_dt.date() - sub_d).days
    for label, lo, hi in AR_AGING_BUCKETS:
        if lo <= age_days <= hi:
            return label
    return AR_AGING_BUCKETS[-1][0]

def simulate_cash_flow(open_ar, payer_curves, payer_catalog,
                       horizon_weeks=DEFAULT_HORIZON_WEEKS,
                       n_samples=DEFAULT_MONTE_CARLO_SAMPLES,
                       as_of_dt=None, seed=SYNTHETIC_RANDOM_SEED + 7):
    """Step 3: Monte Carlo simulation of per-week cash inflows.

    See pseudocode Step 3 in the main recipe. Returns:
      - per_week_samples: dict keyed by (payer_id, week_index)
        with a list of N total-cash sample values
      - aging_summary:   dict keyed by aging bucket -> dict
                          of payer -> total expected amount
    """
    if as_of_dt is None:
        as_of_dt = datetime.now(timezone.utc).replace(tzinfo=None)

    # per_week_samples[(payer_id, week_index)] = [sample_total, ...]
    per_week_samples = defaultdict(lambda: [0.0] * n_samples)

    # Aging bucket attribution: each open claim's expected cash
    # gets attributed to its current aging bucket so the finance
    # team sees how much expected inflow comes from "fresh" AR
    # vs. "old" AR.
    aging_summary = defaultdict(lambda: defaultdict(float))

    rng = random.Random(seed)

    # Per-claim simulation: each claim contributes to N samples,
    # one per Monte Carlo draw. Aggregate by (payer, week_index).
    for claim in open_ar:
        curve = payer_curves.get(claim["payer_id"])
        if curve is None:
            # Payer with insufficient training history. In production,
            # fall back to a payer-class-average curve. The demo skips
            # these claims and logs the count so the operator sees
            # how much AR mass was excluded from the forecast.
            logger.warning("No curve for payer %s; claim %s skipped",
                           claim["payer_id"],
                           claim.get("claim_id", "unknown"))
            continue
        bucket = _ar_aging_bucket(claim["submitted_date"], as_of_dt)
        aging_summary[bucket][claim["payer_id"]] += claim.get(
            "expected_allowed_amount", 0.0)

        for s_idx in range(n_samples):
            pay_date, amt = simulate_claim_payment(
                claim, curve, payer_catalog,
                horizon_weeks, as_of_dt, rng)
            if pay_date is None or amt <= 0:
                continue
            week_idx = (pay_date - as_of_dt.date()).days // 7
            if 0 <= week_idx < horizon_weeks:
                woy = _week_of_year_iso(pay_date)
                seasonal = _seasonality_factor(woy)
                per_week_samples[(claim["payer_id"], week_idx)][s_idx] += (
                    amt * seasonal)

    return per_week_samples, dict(aging_summary)
```

---

## Step 4: Aggregate to Per-Week Cash Flow Forecasts

Take the per-claim, per-sample trajectories and produce per-week, per-payer cash flow forecasts with prediction intervals. The aggregation also produces a hospital-wide rollup and an aging-bucket-conditional summary so the finance team can see total expected cash, per-payer expected cash, and a confidence band.

```python
def aggregate_forecasts(per_week_samples, aging_summary,
                        horizon_weeks, as_of_dt):
    """Step 4: Aggregate Monte Carlo samples into per-week forecasts.

    See pseudocode Step 4 in the main recipe. Returns a list of
    forecast records, each with:
      forecast_week (ISO date of the week start),
      payer_id, expected_cash, p10_cash, p50_cash, p90_cash,
      sample_count, generated_at.
    """
    forecasts = []
    week_start_dates = [
        as_of_dt.date() + timedelta(days=7 * w)
        for w in range(horizon_weeks)
    ]

    # All-payer aggregate per week. Aggregation is sample-wise:
    # each sample's per-payer per-week values sum to a per-sample
    # all-payer total, then percentiles across samples produce
    # the all-payer prediction interval. This preserves the
    # cross-payer correlation that Independent percentile
    # aggregation would lose.
    payers_seen = set()
    for (payer_id, week_idx) in per_week_samples.keys():
        payers_seen.add(payer_id)

    # Per-payer per-week records.
    for payer_id in sorted(payers_seen):
        for week_idx in range(horizon_weeks):
            samples = per_week_samples.get((payer_id, week_idx))
            if samples is None:
                continue
            mean_v   = sum(samples) / len(samples)
            sorted_s = sorted(samples)
            # Index-truncation percentile approximation. For N=1000
            # samples the difference from interpolation-based methods
            # (numpy.percentile, statistics.quantiles) is negligible.
            # Production with smaller sample counts should use
            # numpy.percentile or statistics.quantiles for accuracy.
            p10 = sorted_s[int(0.10 * len(sorted_s))]
            p50 = sorted_s[int(0.50 * len(sorted_s))]
            p90 = sorted_s[int(0.90 * len(sorted_s))]
            forecasts.append({
                "forecast_week":     week_start_dates[week_idx].isoformat(),
                "week_index":        week_idx,
                "payer_id":          payer_id,
                "payer_display":     PAYER_CATALOG[payer_id]["display"],
                "expected_cash":     round(mean_v, 2),
                "p10_cash":          round(p10, 2),
                "p50_cash":          round(p50, 2),
                "p90_cash":          round(p90, 2),
                "sample_count":      len(samples),
                "generated_at":      as_of_dt.isoformat(),
            })

    # All-payer aggregate per week (sample-wise summing).
    n_samples = None
    if per_week_samples:
        n_samples = len(next(iter(per_week_samples.values())))
    if n_samples:
        for week_idx in range(horizon_weeks):
            sample_totals = [0.0] * n_samples
            for (payer_id, w_idx), vals in per_week_samples.items():
                if w_idx != week_idx:
                    continue
                for i, v in enumerate(vals):
                    sample_totals[i] += v
            mean_v   = sum(sample_totals) / n_samples
            sorted_s = sorted(sample_totals)
            p10 = sorted_s[int(0.10 * n_samples)]
            p50 = sorted_s[int(0.50 * n_samples)]
            p90 = sorted_s[int(0.90 * n_samples)]
            forecasts.append({
                "forecast_week":     week_start_dates[week_idx].isoformat(),
                "week_index":        week_idx,
                "payer_id":          "ALL",
                "payer_display":     "All Payers (aggregate)",
                "expected_cash":     round(mean_v, 2),
                "p10_cash":          round(p10, 2),
                "p50_cash":          round(p50, 2),
                "p90_cash":          round(p90, 2),
                "sample_count":      n_samples,
                "generated_at":      as_of_dt.isoformat(),
            })

    # Aging summary attached to the forecast batch as metadata.
    aging_block = {}
    for bucket, by_payer in aging_summary.items():
        aging_block[bucket] = {
            "total_expected_open":    round(sum(by_payer.values()), 2),
            "by_payer": {p: round(v, 2) for p, v in by_payer.items()},
        }

    return forecasts, aging_block
```

---

## Step 5: Deliver Forecasts to the Finance Team

Forecasts get written to DynamoDB keyed by `forecast_week` so the treasury dashboard or working-capital spreadsheet can fetch them with low latency. The sample trajectories go to S3 for variance-by-payer analysis. EventBridge gets a pipeline-completion event so any downstream consumer (a Slack notifier for the CFO, an automated treasury workflow) can react.

```python
def deliver_forecasts(forecasts, aging_block, table, event_bus,
                       cloudwatch, s3, sample_trajectory_bucket,
                       run_id):
    """Step 5: Persist forecasts and emit metrics.

    See pseudocode Step 5 in the main recipe. Returns a dict
    with counts for the orchestrator's metric emission.
    """
    written = 0
    # boto3's batch_writer() automatically chunks into 25-item batches
    # and retries UnprocessedItems internally. One context manager for
    # the entire list; the SDK handles the rest.
    with table.batch_writer() as bw:
        for f in forecasts:
            item = {
                "forecast_week":  f["forecast_week"],
                "payer_id":       f["payer_id"],
                "payer_display":  f["payer_display"],
                "week_index":     _to_decimal(f["week_index"]),
                "expected_cash":  _to_decimal(f["expected_cash"]),
                "p10_cash":       _to_decimal(f["p10_cash"]),
                "p50_cash":       _to_decimal(f["p50_cash"]),
                "p90_cash":       _to_decimal(f["p90_cash"]),
                "sample_count":   _to_decimal(f["sample_count"]),
                "generated_at":   f["generated_at"],
                "pipeline_version": PIPELINE_VERSION,
                "contract_version": CONTRACT_LIBRARY_VERSION,
                "run_id":         run_id,
            }
            bw.put_item(Item=item)
            written += 1

    # Aging-summary attached as a metadata record at a dedicated
    # CURRENT pseudo-week so the dashboard can fetch the latest
    # aging snapshot without scanning.
    aging_item = {
        "forecast_week":  "AGING-SUMMARY",
        "payer_id":       "ALL",
        "payer_display":  "Aging summary as-of forecast date",
        "aging_summary":  json.dumps(aging_block, default=str),
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "pipeline_version": PIPELINE_VERSION,
        "contract_version": CONTRACT_LIBRARY_VERSION,
        "run_id":         run_id,
    }
    table.put_item(Item=aging_item)

    # Sample trajectories to S3 for variance analysis. Each
    # forecast row carries its prediction interval, but the
    # full sample set is what the treasury team uses for
    # downside-risk analysis ("what is the 5th percentile of
    # next-week cash if we lose the BCBS contract?").
    s3_key = (f"trajectories/run_id={run_id}/"
              f"date={datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json")
    # Write the per-claim sample trajectories as a single JSON blob.
    # Production would partition by payer for predicate pushdown.
    s3.put_object(Bucket=sample_trajectory_bucket, Key=s3_key,
                  Body=json.dumps(forecasts))

    # EventBridge completion event. The payload deliberately
    # carries no PHI: just the run identifier, total expected
    # 13-week cash, and the pipeline + contract versions.
    total_expected = sum(f["expected_cash"] for f in forecasts
                         if f["payer_id"] == "ALL")
    event_bus.put_events(Entries=[{
        "Source":       "rcm.cash_flow",
        "DetailType":   "CashFlowForecastCompleted",
        "EventBusName": CASH_FORECAST_EVENT_BUS,
        "Time":         datetime.now(timezone.utc),
        "Detail":       json.dumps({
            "run_id":               run_id,
            "forecast_count":       len(forecasts),
            "total_expected_cash":  round(total_expected, 2),
            "pipeline_version":     PIPELINE_VERSION,
            "contract_version":     CONTRACT_LIBRARY_VERSION,
        }),
    }])

    # CloudWatch metrics. The most important operational metric
    # is forecast variance: the spread between p10 and p90 per
    # week per payer. Wide spreads relative to mean are a signal
    # that the curve is poorly calibrated for that payer or that
    # the payer has shifted its dynamics.
    metric_data = [
        {"MetricName": "ForecastsWritten",
         "Value":      float(written),
         "Unit":       "Count"},
    ]
    for f in forecasts:
        if f["payer_id"] == "ALL":
            continue
        spread = f["p90_cash"] - f["p10_cash"]
        if f["expected_cash"] > 0:
            spread_ratio = spread / f["expected_cash"]
            metric_data.append({
                "MetricName": "ForecastSpreadRatio",
                "Value":      float(spread_ratio),
                "Unit":       "None",
                "Dimensions": [
                    {"Name": "Payer",     "Value": f["payer_id"]},
                    {"Name": "WeekIndex", "Value": str(f["week_index"])},
                ],
            })
    cloudwatch.put_metric_data(
        Namespace=CLOUDWATCH_NAMESPACE,
        MetricData=metric_data)

    logger.info(
        "Delivered: %d forecast records, %d sample-trajectory record",
        written, 1)
    return {"forecasts_written": written}
```

---

## Full Pipeline

Stitching the steps together. Production runs each step as a separate Step Functions task with retries, error handling, and CloudWatch alarms; the demo runs them sequentially in one process so you can see the data flow.

```python
def run_cash_flow_pipeline(table, event_bus, cloudwatch, s3, as_of_dt=None):
    """End-to-end pipeline orchestration.

    The demo wires up synthetic data; production starts with an
    S3 read of the harmonized AR ledger populated by the nightly
    ingestion Glue job, plus a fresh open-AR pull from the
    practice management system or general ledger.
    """
    run_id = str(uuid.uuid4())
    print(f"\n=== Revenue Cycle Cash Flow Forecast run_id={run_id} ===\n")

    if as_of_dt is None:
        as_of_dt = datetime.now(timezone.utc).replace(tzinfo=None)

    # --- Generate synthetic input data ---
    raw_history = generate_synthetic_remittance_history()
    open_ar     = generate_synthetic_open_ar(raw_history)
    print(f"[input] {len(raw_history)} historical records, "
          f"{len(open_ar)} open AR claims")

    # --- Step 1: Harmonize ---
    print("\n[step 1] harmonize_ar_records")
    # In production, the harmonized AR ledger comes from a Glue job
    # consuming the 835/837 stream. The open-AR pull is a separate
    # read from the practice-management system. The demo models both
    # paths with the same harmonize function on different record sets.
    harmonized = harmonize_ar_records(
        raw_history, s3, HARMONIZED_AR_BUCKET)
    open_harmonized = harmonize_ar_records(
        open_ar, s3, HARMONIZED_AR_BUCKET)
    print(f"  -> {len(harmonized)} historical records harmonized")
    print(f"  -> {len(open_harmonized)} open AR records harmonized")

    # --- Step 2: Fit per-payer payment curves ---
    print("\n[step 2] fit_payer_payment_curves")
    curves = fit_payer_payment_curves(harmonized, as_of_dt=as_of_dt)
    for payer_id, c in curves.items():
        if c is None:
            print(f"  {payer_id:>22}: insufficient history")
            continue
        med = c.get("median_paid_lag")
        med_str = f"{med}" if med is not None else "n/a"
        print(f"  {payer_id:>22}: "
              f"n={c['sample_count']:>4} events={c['event_count']:>4} "
              f"denial={c['denial_rate']:.2%} median_lag={med_str}")
    # Persist the curves to S3 so SageMaker training jobs and
    # downstream consumers can read them. Production stores the
    # full estimator state, not just summary stats.
    curve_dump = {
        p: {
            "sample_count":     c["sample_count"],
            "event_count":      c["event_count"],
            "denial_rate":      c["denial_rate"],
            "median_paid_lag":  c["median_paid_lag"],
            "fit_as_of":        c["fit_as_of"],
            "curve_points":     c["estimator"].curve,
        }
        for p, c in curves.items()
        if c is not None
    }
    s3.put_object(
        Bucket=PAYER_CURVE_BUCKET,
        Key=f"as_of={as_of_dt.strftime('%Y-%m-%d')}/curves.json",
        Body=json.dumps(curve_dump, default=str))

    # --- Step 3: Monte Carlo simulation ---
    print("\n[step 3] simulate_cash_flow")
    per_week_samples, aging_summary = simulate_cash_flow(
        open_harmonized, curves, PAYER_CATALOG,
        horizon_weeks=DEFAULT_HORIZON_WEEKS,
        n_samples=DEFAULT_MONTE_CARLO_SAMPLES,
        as_of_dt=as_of_dt)
    print(f"  -> {len(per_week_samples)} (payer, week) cells populated")
    print(f"  -> {len(aging_summary)} aging buckets summarized")

    # --- Step 4: Aggregate ---
    print("\n[step 4] aggregate_forecasts")
    forecasts, aging_block = aggregate_forecasts(
        per_week_samples, aging_summary,
        horizon_weeks=DEFAULT_HORIZON_WEEKS,
        as_of_dt=as_of_dt)
    print(f"  -> {len(forecasts)} forecast records")

    # --- Step 5: Deliver ---
    print("\n[step 5] deliver_forecasts")
    delivery = deliver_forecasts(
        forecasts, aging_block, table, event_bus, cloudwatch,
        s3, SAMPLE_TRAJECTORY_BUCKET, run_id)
    print(f"  -> wrote {delivery['forecasts_written']} forecast records")
    print(f"  -> emitted {len(event_bus.events)} EventBridge events")
    print(f"  -> emitted CloudWatch metrics: "
          f"{sorted(cloudwatch.metrics.keys())[:3]} ...")

    return forecasts, aging_block

def run_demo():
    """Run the pipeline end-to-end against the in-memory mocks.

    No AWS resources are touched; every external dependency is
    a mock. Useful for sanity-checking the curve fitting, the
    Monte Carlo composition, and the per-week aggregation before
    wiring to real services.
    """
    table       = MockTable(CASH_FORECAST_TABLE)
    event_bus   = MockEventBus(CASH_FORECAST_EVENT_BUS)
    cloudwatch  = MockCloudWatch()
    s3          = MockS3()

    forecasts, aging = run_cash_flow_pipeline(
        table, event_bus, cloudwatch, s3)

    print("\n=== Per-payer next-4-weeks forecast (expected, p10, p90) ===")
    for f in forecasts:
        if f["payer_id"] == "ALL":
            continue
        if f["week_index"] >= 4:
            continue
        print(f"  week={f['forecast_week']} "
              f"{f['payer_id']:>22} "
              f"E=${f['expected_cash']:>10,.0f} "
              f"p10=${f['p10_cash']:>10,.0f} "
              f"p90=${f['p90_cash']:>10,.0f}")

    print("\n=== All-payer per-week aggregate ===")
    for f in forecasts:
        if f["payer_id"] != "ALL":
            continue
        if f["week_index"] >= 8:
            continue
        print(f"  week={f['forecast_week']} "
              f"E=${f['expected_cash']:>12,.0f} "
              f"p10=${f['p10_cash']:>12,.0f} "
              f"p90=${f['p90_cash']:>12,.0f}")

    print("\n=== Aging summary (open AR by bucket) ===")
    for bucket, info in sorted(aging.items()):
        total  = info.get("total_expected_open", 0.0) if isinstance(info, dict) else 0.0
        payers = list(info.get("by_payer", {}).keys()) if isinstance(info, dict) else []
        print(f"  {bucket:>8}  total_open=${total:>12,.0f} "
              f"payers={payers}")

    print(f"\n=== DynamoDB writes: {table.write_count} ===")

    return forecasts

if __name__ == "__main__":
    run_demo()
```

---

## Sample Output

Running the demo against the in-memory mocks produces output like this. Output is deterministic given the fixed seed (`SYNTHETIC_RANDOM_SEED = 42`); the per-payer payment-curve shapes, the per-week aggregation, and the prediction intervals are the structurally interesting outputs.

```text
=== Revenue Cycle Cash Flow Forecast run_id=8f3a... ===

[input] 43210 historical records, 800 open AR claims

[step 1] harmonize_ar_records
  -> 43210 historical records harmonized
  -> 800 open AR records harmonized

[step 2] fit_payer_payment_curves
       MEDI-FFS-001: n=13902 events=13211 denial= 4.10% median_lag=17
    MCAID-STATE-001: n= 7806 events= 6842 denial= 9.01% median_lag=27
      COMM-BCBS-001: n= 6041 events= 5601 denial= 7.20% median_lag=22
  COMM-NATIONAL-001: n=10422 events= 9165 denial=11.05% median_lag=31
       SELF-PAY-001: n= 5092 events= 3110 denial= 0.00% median_lag=58

[step 3] simulate_cash_flow
  -> 65 (payer, week) cells populated
  -> 5 aging buckets summarized

[step 4] aggregate_forecasts
  -> 78 forecast records

[step 5] deliver_forecasts
  -> wrote 78 forecast records
  -> emitted 1 EventBridge events
  -> emitted CloudWatch metrics: ['RevenueCycleCashFlow/ForecastSpreadRatio', 'RevenueCycleCashFlow/ForecastsWritten'] ...

=== Per-payer next-4-weeks forecast (expected, p10, p90) ===
  week=2026-05-26       MEDI-FFS-001 E=$  142,300 p10=$  121,440 p90=$  165,180
  week=2026-05-26    MCAID-STATE-001 E=$   65,810 p10=$   52,400 p90=$   80,290
  week=2026-05-26      COMM-BCBS-001 E=$   58,920 p10=$   46,840 p90=$   72,160
  week=2026-05-26  COMM-NATIONAL-001 E=$   89,440 p10=$   71,260 p90=$  108,920
  ...

=== All-payer per-week aggregate ===
  week=2026-05-26 E=$    378,210 p10=$    312,450 p90=$    448,180
  week=2026-06-02 E=$    441,680 p10=$    375,910 p90=$    512,640
  week=2026-06-09 E=$    395,310 p10=$    330,170 p90=$    465,890
  ...

=== Aging summary (open AR by bucket) ===
   0-30  total_open=$  410,250  payers=['MEDI-FFS-001', 'COMM-NATIONAL-001', ...]
  31-60  total_open=$  287,610  payers=['COMM-BCBS-001', 'MCAID-STATE-001', ...]
  61-90  total_open=$  142,940  payers=['COMM-NATIONAL-001', 'SELF-PAY-001', ...]
  ...

=== DynamoDB writes: 79 ===
```

A real pipeline against a single hospital's full AR ledger (20,000 to 80,000 open claims, 5 to 50 distinct payers, 13-to-26-week horizon) runs the weekly cycle in a few minutes on a small SageMaker container, produces the same shape of output, and writes the records straight to a real DynamoDB table that the finance team's treasury dashboard queries on Monday morning.

---

## Gap to Production

The demo is intentionally a sketch. Here is the distance between this code and something you would deploy.

**Real statistical libraries, not demo helpers.** The `KaplanMeierEstimator` in this file is a pedagogical stand-in. Production replaces it with [`lifelines.KaplanMeierFitter`](https://lifelines.readthedocs.io/en/latest/fitters/univariate/KaplanMeierFitter.html) for the per-payer survival curves, with [`lifelines.CoxPHFitter`](https://lifelines.readthedocs.io/en/latest/fitters/regression/CoxPHFitter.html) when the curve depends on claim-level features (CPT class, modifier presence, NPI, place-of-service), with [`scikit-survival`](https://scikit-survival.readthedocs.io/) for gradient-boosted survival models when the feature space is rich, and with [SageMaker DeepAR](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html) when a hierarchical multi-payer model is preferable to per-payer fits. The demo's estimator is good enough to demonstrate the survival framing and the right-censoring handling; it is not good enough for a production cash-flow forecast.

**Real S3 prefixes, not MockS3.** Replace `MockS3` with `boto3.client('s3')` calls. Production has separate prefixes for raw 837 claim files, raw 835 remittance files, the harmonized AR ledger, the per-payer curve artifacts, the per-claim sample trajectories, and the weekly forecast outputs, all encrypted with the same customer-managed KMS key. Object-level retention policies match the institutional retention floor (typically seven years for financial records under standard recordkeeping requirements). The harmonized prefix is partitioned by `payer_id/year/month` for predicate pushdown; the curve prefix is partitioned by `as_of` date so a rerun can fetch the curves that were active on a specific historical date.

**Real Glue ETL for AR ingestion and harmonization.** The `harmonize_ar_records` function loops over Python lists in process. Production runs this as an AWS Glue PySpark job that reads new 835 files (and, for proactive forecasting, the 837 claim feed even before the 835 has arrived), reconciles claim lines against the original 837 submission, joins against the contract-effective-date lookup, and writes the harmonized rows partitioned by payer and submission month. The job runs nightly, completes in tens of minutes for a typical hospital workload, and uses the Glue service role with scoped S3 and KMS permissions.

**Real SageMaker for curve fitting.** The `fit_payer_payment_curves` function runs in process. Production runs this as a weekly SageMaker training job that reads the harmonized AR ledger, fits per-payer survival models (with the appropriate class of estimator: KM for simple per-payer, Cox or boosted-survival for feature-conditioned curves, DeepAR for hierarchical), serializes the model artifacts back to S3, and updates the SageMaker Model Registry. The training job runs in a private VPC subnet with VPC endpoints to S3, KMS, and CloudWatch Logs. Model promotion is gated on a backtest comparison against the previous champion: a candidate model has to beat the champion on calibration metrics (mean error, MAPE, prediction-interval coverage) on held-out historical weeks before it can be promoted.

**Real Lambda for Monte Carlo simulation.** The `simulate_cash_flow` function loops over claims and samples in pure Python. Production wraps the Monte Carlo logic in an AWS Lambda function (or, for very large AR ledgers, an AWS Batch job or an EMR Serverless Spark job). The simulation parallelizes naturally: each open claim is independent, so partitioning by claim id and reducing across samples is straightforward. For an 80,000-claim AR ledger with 1,000 Monte Carlo draws, the simulation runs in under five minutes on a moderately-sized Lambda or in seconds on a Spark cluster.

**Real DynamoDB, not MockTable.** Replace `MockTable` with `boto3.resource('dynamodb').Table(CASH_FORECAST_TABLE)`. The table needs a partition key (`forecast_week`, type S), a sort key (`payer_id`, type S), encryption-at-rest with a customer-managed KMS key, point-in-time recovery enabled, on-demand billing for the unpredictable load that comes with multi-tenant treasury dashboards (or provisioned with auto-scaling for predictable single-hospital load), and an item-level TTL on historical forecast records so the table does not grow unbounded. Also handle the `BatchWriteItem` `UnprocessedItems` response with exponential backoff; `MockTable` ignores this case but DynamoDB returns unprocessed items under throttling.

**Real Step Functions orchestration.** The pipeline-orchestration logic (harmonize -> fit curves -> simulate -> aggregate -> deliver) runs as an AWS Step Functions state machine in production. Each step is a Glue job, a SageMaker training job, a Lambda, or a DynamoDB write, with `Retry` and `Catch` blocks for transient failures, a `Parallel` state for concurrent per-payer fitting, and an `EventBridge` schedule that fires weekly. The state machine emits `ExecutionFailed` events to a CloudWatch alarm so on-call gets paged when a run fails before the Monday treasury meeting.

**Real EventBridge bus and CloudWatch alarms.** The `MockEventBus` and `MockCloudWatch` accumulate events and metrics in process. Production uses real `boto3.client('events').put_events(...)` and `boto3.client('cloudwatch').put_metric_data(...)`, plus CloudWatch alarms on per-payer forecast spread (alarm if the p90/p10 ratio drifts above the calibrated tolerance, which indicates the curve is no longer fit-for-purpose), pipeline-execution latency, DynamoDB write throttling, SageMaker training success rate, and forecast-vs-actual variance (alarm when the realized cash for a closed week deviates from the forecasted mean by more than two prediction-interval widths, which is the leading indicator of a payer dynamics shift). The alarms feed an SNS topic that pages the on-call ML engineer and emails the revenue-cycle director.

**Contract effective dates and renegotiation handling.** The demo carries a single `contract_effective_date` per payer. Production tracks contract changes explicitly: the curve fit for payer X only consumes data from after the most recent material contract change, the model registry stores one curve version per (payer, contract_effective_date) tuple, and a contract-change event in the upstream contract management system triggers a re-fit on the next pipeline run. Without this discipline, a payer that renegotiated its denial-appeal escalation path produces a curve that mixes pre- and post-renegotiation behavior and forecasts neither correctly.

**Per-claim feature conditioning.** The demo's per-payer curve treats every claim from a given payer as exchangeable. In production, claim-level features (CPT class, modifier presence, NPI of the rendering provider, place-of-service code, prior authorization status, secondary payer) materially shift the payment curve. A claim with a prior-auth-required CPT and a secondary payer pays differently from a claim with neither, even from the same primary payer. Production swaps the per-payer KM for a Cox proportional-hazards model or a gradient-boosted survival model that consumes those features and produces a per-claim curve.

**Patient-responsibility tail modeling.** The demo treats self-pay as just another payer with a wider distribution. Production models self-pay separately with two layers: a primary "will this patient pay" probability (which depends on demographics, prior-payment history, statement count, and presence of a payment plan), and a secondary "when will they pay" distribution conditional on the first. The patient-responsibility tail is the single largest source of long-horizon forecast uncertainty for most provider organizations; investing in a dedicated self-pay model is the highest-leverage refinement for forecast accuracy at the 26-to-52-week horizon.

**Bad-debt write-off and recovery-agency modeling.** The demo treats unpaid claims as not paying within the horizon. Production tracks claims as they progress through the bad-debt and external-collection-agency stages: typically 0 to 60 days in patient AR, 60 to 120 days in extended AR, 120+ days into pre-collection or external collections. Each stage has its own recovery curve. The cash-flow forecast composes these stages: claims still in patient AR contribute one distribution, claims in pre-collection contribute another, claims with the external agency contribute a third (typically much smaller and longer-tailed).

**Take-backs, refunds, and adjustments.** The demo models cash inflow as a one-way function. In production, payers issue take-backs (recouping previous overpayments through offsets against new payments) and refunds, which subtract from the inbound cash flow. The forecast has to account for the take-back rate as a multiplicative factor on the per-payer expected cash, fit from the historical 835 take-back records.

**Seasonality and external calendar effects.** The demo applies a small fixed seasonality factor at aggregation time. Production fits the seasonality empirically using STL decomposition or X-13ARIMA-SEATS on the historical per-payer per-week cash time series, layered on top of the per-claim Monte Carlo. External calendar effects (year-end Medicare claim re-routing, plan-year resets in January for commercial payers, state Medicaid budget cycles affecting payment cadence) get attached as exogenous features.

**Forecast-vs-actual reconciliation loop.** Every weekly cycle should write its forecast to a calibration store, and every realized week of cash should be matched back to its forecast. The continuous comparison produces accuracy metrics by horizon, by payer, by week-of-year, and by aging bucket. Drift in any of these dimensions is a signal to retrain or to investigate. Without this loop, the system stays calibrated to its launch-day performance and slowly accumulates a noise reputation. Build the calibration store on day one; do not bolt it on in month four.

**Idempotency and rerun safety.** The weekly pipeline can fail and need to be rerun. Each step needs to be safe to repeat: harmonization is idempotent on (claim_id, source_remittance_id); curve fitting is deterministic given the input window; Monte Carlo is deterministic given a fixed seed; DynamoDB writes overwrite cleanly by primary key. The demo achieves this naturally because the pure-Python helpers do not retain state across runs; production has to be deliberate about each step's idempotency contract.

**HIPAA controls end-to-end.** The S3 prefixes use SSE-KMS with a customer-managed key family; the DynamoDB table uses encryption-at-rest with a customer-managed key; SageMaker training jobs run in a VPC with VPC endpoints to S3, CloudWatch Logs, and KMS; the Glue job reads and writes only encrypted data; CloudTrail logs all S3, DynamoDB, Glue, and SageMaker API calls; CloudWatch log groups are KMS-encrypted; IAM roles are scoped to specific resource ARNs; an AWS BAA is in place. The demo touches none of this; production cannot ship without all of it.

**Testing.** Unit tests cover the harmonization function (a known input record produces the expected canonical form, an unknown payer is quarantined, an out-of-contract record is filtered), the Kaplan-Meier estimator (a known-input duration set produces the expected curve, right-censored inputs handle correctly, the inverse-CDF sampler returns valid days), the Monte Carlo simulator (a deterministic curve produces deterministic samples given a fixed seed), the aggregator (sample-wise summing preserves cross-payer correlation), and the DynamoDB write idempotency (writing the same record twice is a no-op). Integration tests run the pipeline against a known-input synthetic AR ledger and assert the per-payer expected-cash totals against expected values. End-to-end tests stand up real S3, DynamoDB, and EventBridge resources in a sandbox account and run the full Step Functions state machine.

**Structured logging.** Replace the demo's `print` calls with `logger.info(..., extra={...})` calls that emit JSON-formatted structured logs to CloudWatch Logs. Log structural metadata only (run_id, payer_id, claim_count, total_amount_band, runtime_ms), never raw claim numbers, never patient identifiers, never service dates tied to identifiable encounters, never the per-claim denial-reason text.

**Regulatory framing.** Cash-flow forecasting that informs internal financial planning sits well within standard financial-software regulatory boundaries. It is not a medical device and is not subject to FDA review. Standard SOX and other financial-controls considerations apply if the forecast is used as an input to material financial reporting; coordinate with the institutional finance and compliance teams on those framing questions. Treat the underlying data with full HIPAA care because the upstream join keys retain PHI even when the surfaced forecast is aggregated.

**The shape of the gap.** The forecasting math in this file is a sketch but it is fundamentally correct. The plumbing around it (storage, orchestration, security, contract awareness, per-claim feature conditioning, self-pay modeling, calibration loop, integration with the practice management system) is what takes the bulk of the engineering work. Plan for the plumbing to be 75% of the project; the survival modeling itself routinely surprises teams by being the easier part.

---

## Related Resources

- [Recipe 12.6: Revenue Cycle Cash Flow Forecasting](chapter12.06-revenue-cycle-cash-flow-forecasting): The main recipe with the full architectural walkthrough this Python companion implements.
- [lifelines](https://lifelines.readthedocs.io/): Production-grade survival analysis library covering Kaplan-Meier, Cox proportional hazards, accelerated failure time, and competing-risks variants. The drop-in replacement for the demo's `KaplanMeierEstimator`.
- [scikit-survival](https://scikit-survival.readthedocs.io/): Gradient-boosted and random-forest survival models, the right replacement when payer behavior depends on claim-level features.
- [Amazon SageMaker DeepAR Forecasting](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html): The right replacement for hierarchical multi-payer forecasting where shared structure across payers improves accuracy on small-volume payers.
- [statsmodels](https://www.statsmodels.org/stable/): Time-series tools for the seasonality-decomposition layer (STL, X-13ARIMA-SEATS).
- [HIPAA-eligible AWS services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/): Authoritative list of AWS services that can be used under a Business Associate Agreement for PHI workloads.
- [HFMA Revenue Cycle Glossary](https://www.hfma.org/topics/revenue-cycle/): Industry-standard definitions for revenue cycle terms (DSO, AR aging, denial rates, write-offs) used throughout this recipe.
- [X12 837 Health Care Claim Standard](https://x12.org/products/transaction-sets): Specification for the 837 claim transaction; the upstream input to the cash-flow forecasting pipeline.
- [X12 835 Health Care Claim Payment / Remittance Advice](https://x12.org/products/transaction-sets): Specification for the 835 remittance transaction; the source of payment-received timestamps used in curve fitting.
- [AWS Step Functions Workflow Studio](https://docs.aws.amazon.com/step-functions/latest/dg/workflow-studio.html): For visually composing the weekly pipeline with retries and parallel states.
- [Forecasting: Principles and Practice (Hyndman & Athanasopoulos)](https://otexts.com/fpp3/): Free online textbook with strong chapters on hierarchical forecasting and intermittent demand, both relevant for multi-payer cash-flow modeling.

---

*← [Recipe 12.6: Revenue Cycle Cash Flow Forecasting](chapter12.06-revenue-cycle-cash-flow-forecasting) · [Chapter 12 Index](chapter12-preface) · [Next: Recipe 12.7 - Vital Sign Trajectory Monitoring →](chapter12.07-vital-sign-trajectory-monitoring)*
