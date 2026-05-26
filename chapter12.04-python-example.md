# Recipe 12.4: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 12.4. It shows one way you could translate the lab-result trend-analysis pipeline into working Python using boto3 against Amazon HealthLake (here represented by an in-memory `MockHealthLake` that stores FHIR Observation resources in a dict), Amazon S3 (here represented by a `MockS3` dict), AWS Glue (here represented by an in-process Python harmonization step), Amazon SageMaker (here represented by pure-Python `TheilSenDetector`, `MannKendallDetector`, `CUSUMDetector`, and `KalmanDetector` classes that stand in for real statsmodels, scipy, and pykalman implementations), AWS Lambda (here represented by a plain Python function that applies the clinical-relevance rules), AWS Step Functions (here represented by sequential function calls), Amazon DynamoDB (mocked with `MockTable`), Amazon EventBridge (mocked with `MockEventBus`), and Amazon CloudWatch (mocked with `MockCloudWatch`). The demo generates synthetic longitudinal lab results for a small panel of patients with realistic chronic-disease trajectories (slowly rising creatinine in a CKD progression case, drifting hemoglobin A1c in a diabetes case, stable thyroid function in a euthyroid case, falling platelets in a bone-marrow-suppression case) so you can see the harmonization, the per-patient baseline, the per-lab trend detection, and the clinical relevance filtering work end-to-end without provisioning anything. It is not production-ready. There is no real HealthLake datastore, no real Glue ETL, no real SageMaker endpoint, no real Step Functions state machine, no real DynamoDB table, no real EventBridge bus, no real CloudWatch alarms, no real CDS Hooks responder, no per-Lambda IAM least privilege, no KMS customer-managed keys, no VPC endpoints, no medication-aware change-point handling, no clinician-feedback capture, no panel-level joint reasoning, and no continuous harmonization quality monitoring. Think of it as the sketchpad version: useful for understanding the shape of a lab-trend pipeline that respects the harmonization-first discipline, the patient-as-their-own-control discipline, the acute-vs-chronic separation discipline, the magnitude-and-duration-and-direction triple-gate discipline, and the explanation-is-the-product discipline this recipe demands. It is not something you would point at a real PCP's inbox on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the five pseudocode steps from the main recipe: harmonize each incoming lab result by mapping the source-system test code to a canonical LOINC code, converting the unit to the canonical UCUM unit, and tagging the encounter context as acute or chronic (Step 1); maintain per-patient rolling baselines computed only from chronic-context history using a robust statistic over a 12-month window (Step 2); run a lab-appropriate trend detector (Theil-Sen plus Mann-Kendall for slow chronic-disease slopes, CUSUM for change-point detection, a Kalman-filter state-space model for irregularly sampled labs) and produce a normalized trend object with slope, slope p-value, deviation from baseline, trend duration, and method-specific diagnostics (Step 3); apply per-LOINC clinical relevance rules that gate on direction, magnitude, duration, and deviation from baseline (Step 4); load the surfaced trends to DynamoDB keyed by `patient_id` with a sort key combining `loinc_code` and `generated_at`, log the suppressed trends to S3 for tuning, and emit pipeline-lifecycle events to EventBridge (Step 5). The synthetic patients, the synthetic LOINC mappings, the synthetic clinical rules, and the synthetic acute-vs-chronic encounter tagging in the demo are fictional; nothing in this file should be interpreted as real clinical data from any real institution.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

The demo runs against the Python standard library plus boto3; no other packages are imported. Production deployments swap the demo's pure-Python detectors for real statistical libraries ([statsmodels](https://www.statsmodels.org/stable/) for the GLM and OLS fits underlying the Mann-Kendall and Theil-Sen variants, [scipy](https://docs.scipy.org/doc/scipy/) for the Kendall tau test and CUSUM helpers, [pykalman](https://pykalman.github.io/) or [filterpy](https://filterpy.readthedocs.io/) for the Kalman state-space model, [PyMC](https://www.pymc.io/) or [Stan](https://mc-stan.org/) for the Bayesian online change-point detection variants, the SageMaker [DeepAR built-in algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html) when you want a learned multi-series neural model layered on top of the per-patient methods); the Gap to Production section spells out the substitutions.

In production you would also configure an Amazon HealthLake datastore for the FHIR Observation resources (or an Amazon S3 prefix populated by an HL7 ORU-R01 ingestion pipeline if you do not need the full FHIR API), an Amazon S3 bucket for the raw HL7 landing zone, the harmonized-result prefix, the per-patient-baseline prefix, the trend-score prefix, the suppressed-trend prefix, and the model-artifact prefix (one prefix per concern, all SSE-KMS encrypted with a customer-managed key), an AWS Glue job that reads new HealthLake observations on a schedule, applies the LOINC + UCUM harmonization, and writes the harmonized rows partitioned by LOINC code and date, an Amazon SageMaker inference endpoint that serves the per-LOINC trend detectors behind a private VPC endpoint (one endpoint per detector family, or a single multi-model endpoint for the combined library), an AWS Lambda function that applies the per-LOINC clinical relevance rules to the trend scores and produces the surfaced-trend payloads, an AWS Step Functions state machine that orchestrates the nightly cycle (harmonize -> baseline -> detect -> filter -> deliver) with retries and `Catch` blocks for transient failures, an Amazon DynamoDB table for the surfaced trends keyed by `patient_id` with a sort key combining `loinc_code` and `generated_at`, an Amazon EventBridge schedule that triggers the Step Functions state machine nightly for chronic-trend analysis (and faster cadences for any acute-monitoring sub-pipelines), Amazon CloudWatch dashboards and alarms for pipeline failures, surfaced-trend volume per clinician, baseline drift, and harmonization quality, and a thin integration layer that exposes the surfaced trends to the EHR via CDS Hooks during chart open or to an inbox aggregator for asynchronous review. The demo replaces all of these with a single in-process Python file so the focus stays on the harmonization, the baseline math, the trend detection, the clinical relevance scoring, and the surface-vs-suppress decision rather than on the platform plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `healthlake:CreateFHIRDatastore`, `healthlake:DescribeFHIRDatastore`, `healthlake:StartFHIRImportJob`, `healthlake:DescribeFHIRImportJob`, `healthlake:SearchWithGet`, `healthlake:ReadResource` on the lab-results FHIR datastore, scoped to the specific datastore ARN
- `s3:GetObject` and `s3:PutObject` on the raw-HL7 prefix, the harmonized-result prefix, the per-patient-baseline prefix, the trend-score prefix, the suppressed-trend prefix, and the model-artifact prefix
- `glue:StartJobRun` and `glue:GetJobRun` on the harmonization Glue job, plus the Glue service role's permissions for the ETL job
- `sagemaker:CreateTrainingJob`, `sagemaker:DescribeTrainingJob`, `sagemaker:CreateModel`, `sagemaker:CreateEndpointConfig`, `sagemaker:UpdateEndpoint`, and `sagemaker:InvokeEndpoint` on the per-LOINC trend-detector models
- `lambda:InvokeFunction` on the clinical-relevance Lambda
- `dynamodb:BatchWriteItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, and `dynamodb:GetItem` on the `patient-lab-trends` table, scoped to the specific table ARN
- `events:PutEvents` on the lab-trend-events bus for emitting pipeline-lifecycle events (run started, harmonization completed, trend detected, surface-vs-suppress decision made, drift alarm raised)
- `states:StartExecution` on the lab-trend Step Functions state machine for the nightly chronic-trend run
- `cloudwatch:PutMetricData` for the operational metrics (per-LOINC surfaced-vs-suppressed counts, harmonization mapping coverage, baseline-readiness rate, per-patient surface count per month, alert-volume-per-clinician)
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the HealthLake datastore, the S3 prefixes, the DynamoDB table, and the model-artifact bucket

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The harmonization Glue job has read access to the HealthLake datastore and write access to the harmonized-result S3 prefix, but no DynamoDB or SageMaker permissions. The clinical-relevance Lambda has read access to the trend-score S3 prefix and write access to the surfaced-trend DynamoDB table and the suppressed-trend S3 prefix, but no HealthLake permissions. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Lab results are PHI in their entirety.** Patient identifier, test code, value, collection timestamp, encounter context. Every storage and compute service that touches this pipeline must be on the [HIPAA eligible services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/) list, every storage layer must be encrypted with customer-managed KMS keys, every network hop must be inside the institutional VPC with no public path, and CloudTrail must log every data-plane API call. The aggregated trend records still carry the patient identifier; they remain PHI even after the underlying values are summarized into a slope.
- **LOINC is the canonical test-code spine.** Source-system codes vary by EHR, by lab, and by analyzer. The harmonization layer maps every result to a canonical LOINC code or quarantines it for manual review. A pipeline that skips this step compares apples to oranges and generates noise that no clinician will trust. The demo's LOINC mapping table is small but illustrative; production institutions maintain a curated mapping with thousands of entries.
- **UCUM unit conversion is mostly mechanical with a few traps.** Glucose mg/dL to mmol/L requires the molecular weight of glucose; serum creatinine mg/dL to umol/L requires the molecular weight of creatinine. A library that assumes linear conversion factors will silently produce wrong numbers for these analytes. The demo's `_convert_units` helper carries the analyte-specific factors for the small panel it covers.
- **Acute-context measurements do not belong in chronic-trend baselines.** A patient's inpatient creatinine is a different distribution than their outpatient creatinine; mixing them produces unstable baselines and miscalibrated alerts. The harmonization layer tags each result with the encounter context, and the baseline computation filters to chronic-context only. The trend detector also runs only on chronic-context history.
- **The patient is their own control.** The population reference range is useful context for the surfaced payload but is not the primary anchor for trend detection. The pipeline compares each patient's recent trajectory to their own 12-month rolling baseline, computed with a robust statistic (interquartile mean by default) so a single outlier does not destabilize it.
- **Different labs need different detectors.** Slow chronic-disease slopes (creatinine in CKD, A1c in diabetes) are best detected with Theil-Sen plus Mann-Kendall. Step changes in stable patients (platelet drop on a marrow-suppressing regimen) are best detected with CUSUM. Irregularly sampled labs are best detected with a Kalman-filter state-space model. The demo's `DETECTOR_BY_LOINC` configuration routes each LOINC to the appropriate detector.
- **Statistical significance is not clinical relevance.** A slope of 0.01 mg/dL/month for creatinine is statistically significant on enough data and clinically meaningless. The relevance layer gates on a per-LOINC magnitude, a per-LOINC minimum trend duration, and a per-LOINC minimum deviation from baseline before a trend gets surfaced. Without this layer, the pipeline drowns the clinician in true positives that nobody cares about.
- **The explanation is the product.** A surfaced trend that says "creatinine is rising" is too thin. A surfaced trend that says "creatinine has risen at 0.06 mg/dL per month for fourteen months, current value 1.62 vs 12-month baseline 1.18, all chronic ambulatory" is something the clinician can reason with in eight seconds. The demo's `compose_clinician_explanation` helper produces that narrative form.
- **DynamoDB rejects Python `float`.** Every slope, p-value, baseline value, deviation, threshold, and confidence value passes through `Decimal` on its way in and on its way out. The `_to_decimal` helper handles it.
- **The example collapses many Lambdas, Glue jobs, and SageMaker endpoints into a single Python file.** In production the harmonization Glue job, the baseline-update Glue job, the per-LOINC SageMaker trend-detector endpoints, the clinical-relevance Lambda, the DynamoDB-loader Lambda, and the suppressed-trend logger are separate units of work with their own IAM roles, error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the LOINC mapping, the per-LOINC unit conversion factors, the per-LOINC clinical-relevance rules, the per-LOINC detector selection, the baseline window length, and the synthetic-data parameters are what you would change between environments.

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
# to CloudWatch Logs Insights for cross-call investigation. Lab
# results are PHI in their entirety. Log structural metadata only
# (run_id, patient_id_hash, loinc_code, surface_decision,
# runtime_ms), never raw values, never collection timestamps tied
# to identifiable visits, never the per-LOINC clinical rule payload
# that includes the institution's calibration choices.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from S3, DynamoDB, EventBridge,
# CloudWatch, HealthLake, and SageMaker. The nightly chronic-trend
# pipeline is a scheduled batch job that touches every active
# patient, so retries should be quick and capped. A stuck dependency
# must not balloon a 90-minute nightly window into a multi-hour
# incident that delays the morning's clinician inboxes.
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
HEALTHLAKE_DATASTORE_ID    = "lab-results-fhir-datastore"
RAW_HL7_BUCKET             = "lab-trend-raw-hl7"
HARMONIZED_BUCKET          = "lab-trend-harmonized"
PATIENT_BASELINE_BUCKET    = "lab-trend-baselines"
TREND_SCORE_BUCKET         = "lab-trend-scores"
SUPPRESSED_TREND_BUCKET    = "lab-trend-suppressed"
MODEL_ARTIFACT_BUCKET      = "lab-trend-models"
PATIENT_TRENDS_TABLE       = "patient-lab-trends"
TREND_EVENT_BUS_NAME       = "lab-trend-events-bus"
CLOUDWATCH_NAMESPACE       = "LabTrendAnalysis"

# --- Versioning ---
# Every surfaced trend carries the model version and the rule
# version active at the time of generation. This is how a future
# audit reconstructs which detector and which calibration produced
# which inbox surface on which night.
PIPELINE_VERSION   = "lab-trend-v1.2"
RULE_LIBRARY_VERSION = "clinical-rules-2026-04"

# --- Window and Cadence ---
# 12-month baseline window is the default for chronic-disease
# labs. Some labs (vitamin D, seasonal markers) use a 24-month
# window to span seasonal variation; the per-LOINC config can
# override the default.
DEFAULT_BASELINE_WINDOW_MONTHS = 12
DEFAULT_RECENT_WINDOW_MONTHS   = 6
DEFAULT_BASELINE_MIN_SAMPLES   = 4

# --- Acute Encounter Classes ---
# Encounter classes that get tagged "acute" and excluded from
# chronic-trend baselines. The exact list depends on the EHR's
# encounter-class vocabulary; this is illustrative.
ACUTE_ENCOUNTER_CLASSES = {"inpatient", "emergency", "observation"}

# --- LOINC Mapping ---
# Per-LOINC configuration covering the small panel the demo
# operates on. Production maintains a curated table with thousands
# of entries managed by the institutional terminology team.
# Each entry carries: the canonical UCUM unit, the per-analyte
# molecular-weight factor (or None for linear conversion), the
# detector to use, the clinical-relevance rules, and the display
# name for surfaced payloads.
LOINC_CATALOG = {
    "2160-0": {   # Creatinine, Serum or Plasma
        "display":             "Creatinine, Serum",
        "canonical_unit":      "mg/dL",
        "molecular_weight":    113.12,    # for mg/dL <-> umol/L
        "umol_factor":         88.4,      # 1 mg/dL = 88.4 umol/L for creatinine
        "detector":            "theil_sen",
        "rules": {
            "minimum_slope_per_month":       0.04,
            "minimum_duration_days":         90,
            "minimum_deviation_from_baseline": 0.20,
            "concerning_direction":          "rising",
            "minimum_slope_significance":    0.05,
        },
    },
    "4548-4": {   # Hemoglobin A1c
        "display":             "Hemoglobin A1c",
        "canonical_unit":      "%",
        "molecular_weight":    None,
        "umol_factor":         None,
        "detector":            "theil_sen",
        "rules": {
            "minimum_slope_per_month":       0.04,
            "minimum_duration_days":         180,
            "minimum_deviation_from_baseline": 0.50,
            "concerning_direction":          "rising",
            "minimum_slope_significance":    0.05,
        },
    },
    "718-7": {    # Hemoglobin
        "display":             "Hemoglobin",
        "canonical_unit":      "g/dL",
        "molecular_weight":    None,
        "umol_factor":         None,
        "detector":            "theil_sen",
        "rules": {
            "minimum_slope_per_month":       0.10,
            "minimum_duration_days":         90,
            "minimum_deviation_from_baseline": 0.80,
            "concerning_direction":          "falling",
            "minimum_slope_significance":    0.05,
        },
    },
    "777-3": {    # Platelets
        "display":             "Platelet Count",
        "canonical_unit":      "10*3/uL",
        "molecular_weight":    None,
        "umol_factor":         None,
        "detector":            "cusum",
        "rules": {
            "minimum_slope_per_month":       8.0,
            "minimum_duration_days":         60,
            "minimum_deviation_from_baseline": 30.0,
            "concerning_direction":          "falling",
            "minimum_slope_significance":    0.05,
        },
    },
    "3016-3": {   # TSH
        "display":             "Thyroid Stimulating Hormone",
        "canonical_unit":      "mIU/L",
        "molecular_weight":    None,
        "umol_factor":         None,
        "detector":            "kalman",
        "rules": {
            "minimum_slope_per_month":       0.20,
            "minimum_duration_days":         180,
            "minimum_deviation_from_baseline": 1.50,
            "concerning_direction":          "either",
            "minimum_slope_significance":    0.05,
        },
    },
}

# --- Source-System to LOINC Mapping ---
# Local lab dictionaries vary; production maintains a curated
# mapping table with vendor-specific source codes. The demo's
# entries cover a few realistic source codes per LOINC.
SOURCE_CODE_TO_LOINC = {
    ("EPIC", "CREAT"):     "2160-0",
    ("EPIC", "CR"):        "2160-0",
    ("CERNER", "11572"):   "2160-0",
    ("EPIC", "HBA1C"):     "4548-4",
    ("EPIC", "A1C"):       "4548-4",
    ("CERNER", "13458"):   "4548-4",
    ("EPIC", "HGB"):       "718-7",
    ("CERNER", "10001"):   "718-7",
    ("EPIC", "PLT"):       "777-3",
    ("CERNER", "10024"):   "777-3",
    ("EPIC", "TSH"):       "3016-3",
    ("CERNER", "10058"):   "3016-3",
}

# --- Synthetic Data ---
# Knobs for the demo's synthetic-history generator. The ranges
# produce a small but realistic-shaped two-year history with
# four illustrative chronic-disease trajectories so you can see
# the pipeline detect (and not detect) the patterns it should.
SYNTHETIC_HISTORY_DAYS = 730     # two years of history
SYNTHETIC_RANDOM_SEED  = 42

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("HEALTHLAKE_DATASTORE_ID",    HEALTHLAKE_DATASTORE_ID),
    ("RAW_HL7_BUCKET",             RAW_HL7_BUCKET),
    ("HARMONIZED_BUCKET",          HARMONIZED_BUCKET),
    ("PATIENT_BASELINE_BUCKET",    PATIENT_BASELINE_BUCKET),
    ("TREND_SCORE_BUCKET",         TREND_SCORE_BUCKET),
    ("SUPPRESSED_TREND_BUCKET",    SUPPRESSED_TREND_BUCKET),
    ("MODEL_ARTIFACT_BUCKET",      MODEL_ARTIFACT_BUCKET),
    ("PATIENT_TRENDS_TABLE",       PATIENT_TRENDS_TABLE),
    ("TREND_EVENT_BUS_NAME",       TREND_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",       CLOUDWATCH_NAMESPACE),
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
        # bool is a subclass of int in Python; route it explicitly
        # so True does not become Decimal('1') unexpectedly.
        return value
    if isinstance(value, (int, float)):
        # Round float through string to avoid the float->Decimal
        # repr surprise (Decimal(0.1) is not Decimal('0.1')).
        return Decimal(str(round(float(value), 6)))
    if isinstance(value, str):
        return Decimal(value)
    raise TypeError(f"Cannot convert {type(value).__name__} to Decimal")
```

---

## Mocks and Synthetic Data

The demo never touches a real HealthLake datastore, S3 bucket, DynamoDB table, EventBridge bus, or SageMaker endpoint. The mocks below stand in for those services so the focus stays on the trend-analysis logic. They print what they would write rather than failing, which makes the demo runnable without any AWS resources provisioned.

```python
class MockHealthLake:
    """In-memory stand-in for an Amazon HealthLake FHIR datastore.

    Production uses boto3.client('healthlake') and the FHIR REST
    API to read Observation resources keyed by patient and code.
    The mock stores observations as a list and provides simple
    search-by-patient-and-code semantics, which is what the
    harmonization and baseline steps need.
    """

    def __init__(self):
        self.observations = []    # list of FHIR Observation dicts

    def put_observation(self, observation):
        self.observations.append(dict(observation))

    def search_observations(self, patient_id, loinc_code,
                            from_ts=None, to_ts=None):
        out = []
        for obs in self.observations:
            if obs.get("subject_reference") != f"Patient/{patient_id}":
                continue
            if obs.get("code_loinc") != loinc_code:
                continue
            if from_ts is not None and obs["effective_dt"] < from_ts:
                continue
            if to_ts is not None and obs["effective_dt"] > to_ts:
                continue
            out.append(obs)
        out.sort(key=lambda o: o["effective_dt"])
        return out


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
            pk = Item["patient_id"]
            sk = Item["loinc_code_generated_at"]
            self.table.items[(pk, sk)] = dict(Item)
            self.table.write_count += 1

    def batch_writer(self):
        return self._BatchWriter(self)

    def put_item(self, Item):
        pk = Item["patient_id"]
        sk = Item["loinc_code_generated_at"]
        self.items[(pk, sk)] = dict(Item)
        self.write_count += 1


class MockEventBus:
    """In-memory stand-in for EventBridge.

    Production uses boto3.client('events').put_events(...). The
    mock accumulates events so the demo can show what would have
    been emitted to the lab-trend-events bus at each pipeline
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
    have been emitted (per-LOINC surfaced/suppressed counts,
    harmonization mapping coverage, baseline-readiness rate).
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


def generate_synthetic_lab_results(history_days=SYNTHETIC_HISTORY_DAYS,
                                   seed=SYNTHETIC_RANDOM_SEED):
    """Generate synthetic longitudinal lab results for a small panel of patients.

    Production reads from Amazon HealthLake (or an HL7 ORU-R01
    landing zone on S3). The demo synthesizes four illustrative
    chronic-disease trajectories so you can see the pipeline
    detect what it should and ignore what it should:

      patient-CKD-001  - Slowly rising creatinine over 14 months
                         (should surface).
      patient-DM-002   - Drifting A1c with a recent regimen-change
                         uplift (should surface).
      patient-BMS-003  - Falling platelets on a marrow-suppressing
                         regimen (should surface as change-point).
      patient-EUTH-004 - Stable TSH and creatinine, normal patient
                         (should not surface).

    Each result is emitted as a synthetic source-system row with
    the source code, raw value, raw unit, encounter class, and
    issuing-lab reference range. The harmonization step is what
    turns these into canonical LOINC + UCUM observations.
    """
    rng = random.Random(seed)
    end_d   = date.today()
    start_d = end_d - timedelta(days=history_days)

    raw_results = []

    # --- patient-CKD-001: slowly rising creatinine ---
    # Most chronic ambulatory results, a few inpatient acute
    # results sprinkled in (which the chronic pipeline must
    # exclude). Slope around 0.06 mg/dL per month, baseline 1.18,
    # current value around 1.6.
    creat_dates = []
    cursor = start_d + timedelta(days=14)
    while cursor <= end_d:
        creat_dates.append(cursor)
        # Every ~90 days for chronic monitoring.
        cursor += timedelta(days=rng.randint(78, 102))
    base_creat = 1.18
    slope_per_day_ckd = 0.06 / 30.0
    for i, d in enumerate(creat_dates):
        # Small per-result noise plus the long-term slope.
        days_in = (d - creat_dates[0]).days
        value = base_creat + slope_per_day_ckd * days_in + rng.gauss(0, 0.05)
        # Most results from EPIC, ambulatory.
        raw_results.append({
            "patient_id":          "patient-CKD-001",
            "source_system":       "EPIC",
            "source_test_code":    "CR",
            "value":               round(value, 2),
            "unit":                "mg/dL",
            "ref_low":             0.70,
            "ref_high":            1.30,
            "ref_unit":            "mg/dL",
            "collection_ts":       datetime(d.year, d.month, d.day, 8, 0, 0).isoformat(),
            "encounter_class":     "ambulatory",
            "lab_id":              "central-lab-A",
            "method_or_analyzer":  "enzymatic",
        })
    # Two acute-context results during a hospitalization that
    # should NOT be in the chronic baseline. These are spikes
    # the chronic pipeline must exclude.
    for offset_days in (220, 222):
        d = start_d + timedelta(days=offset_days)
        raw_results.append({
            "patient_id":          "patient-CKD-001",
            "source_system":       "EPIC",
            "source_test_code":    "CR",
            "value":               2.4 + rng.gauss(0, 0.1),
            "unit":                "mg/dL",
            "ref_low":             0.70,
            "ref_high":            1.30,
            "ref_unit":            "mg/dL",
            "collection_ts":       datetime(d.year, d.month, d.day, 14, 0, 0).isoformat(),
            "encounter_class":     "inpatient",
            "lab_id":              "central-lab-A",
            "method_or_analyzer":  "enzymatic",
        })

    # --- patient-DM-002: drifting A1c ---
    # Quarterly A1c, baseline 7.2, recent uplift to 8.4 over the
    # last 9 months (regimen quietly failing).
    a1c_dates = []
    cursor = start_d + timedelta(days=21)
    while cursor <= end_d:
        a1c_dates.append(cursor)
        cursor += timedelta(days=rng.randint(85, 100))
    n = len(a1c_dates)
    breakpoint_idx = max(0, n - 4)
    base_a1c = 7.2
    for i, d in enumerate(a1c_dates):
        if i < breakpoint_idx:
            value = base_a1c + rng.gauss(0, 0.15)
        else:
            months_since_break = (i - breakpoint_idx + 1) * 3
            value = base_a1c + 0.13 * months_since_break + rng.gauss(0, 0.15)
        raw_results.append({
            "patient_id":          "patient-DM-002",
            "source_system":       "CERNER",
            "source_test_code":    "13458",
            "value":               round(value, 2),
            "unit":                "%",
            "ref_low":             4.0,
            "ref_high":            5.6,
            "ref_unit":            "%",
            "collection_ts":       datetime(d.year, d.month, d.day, 9, 0, 0).isoformat(),
            "encounter_class":     "ambulatory",
            "lab_id":              "central-lab-B",
            "method_or_analyzer":  "HPLC",
        })

    # --- patient-BMS-003: falling platelets (change-point) ---
    # Stable around 220 for 18 months, then a sustained drop to
    # ~120 over the last 4 months on a marrow-suppressing regimen.
    plt_dates = []
    cursor = start_d + timedelta(days=10)
    while cursor <= end_d:
        plt_dates.append(cursor)
        cursor += timedelta(days=rng.randint(28, 35))
    n = len(plt_dates)
    breakpoint_idx = max(0, n - 5)
    for i, d in enumerate(plt_dates):
        if i < breakpoint_idx:
            value = 220 + rng.gauss(0, 12)
        else:
            steps_after = i - breakpoint_idx
            value = 220 - 22 * steps_after + rng.gauss(0, 8)
            value = max(50, value)
        raw_results.append({
            "patient_id":          "patient-BMS-003",
            "source_system":       "EPIC",
            "source_test_code":    "PLT",
            "value":               round(value, 0),
            "unit":                "10*3/uL",
            "ref_low":             150.0,
            "ref_high":            450.0,
            "ref_unit":            "10*3/uL",
            "collection_ts":       datetime(d.year, d.month, d.day, 8, 30, 0).isoformat(),
            "encounter_class":     "ambulatory",
            "lab_id":              "central-lab-A",
            "method_or_analyzer":  "impedance",
        })

    # --- patient-EUTH-004: stable, no concerning trend ---
    # Routine annual TSH around 2.0 mIU/L with normal noise.
    tsh_dates = []
    cursor = start_d + timedelta(days=30)
    while cursor <= end_d:
        tsh_dates.append(cursor)
        cursor += timedelta(days=rng.randint(330, 380))
    for d in tsh_dates:
        raw_results.append({
            "patient_id":          "patient-EUTH-004",
            "source_system":       "EPIC",
            "source_test_code":    "TSH",
            "value":               round(2.0 + rng.gauss(0, 0.4), 2),
            "unit":                "mIU/L",
            "ref_low":             0.4,
            "ref_high":            4.5,
            "ref_unit":            "mIU/L",
            "collection_ts":       datetime(d.year, d.month, d.day, 9, 0, 0).isoformat(),
            "encounter_class":     "ambulatory",
            "lab_id":              "central-lab-A",
            "method_or_analyzer":  "immunoassay",
        })
    # Plus quarterly creatinine that stays stable.
    creat_stable_dates = []
    cursor = start_d + timedelta(days=14)
    while cursor <= end_d:
        creat_stable_dates.append(cursor)
        cursor += timedelta(days=rng.randint(85, 100))
    for d in creat_stable_dates:
        raw_results.append({
            "patient_id":          "patient-EUTH-004",
            "source_system":       "EPIC",
            "source_test_code":    "CR",
            "value":               round(0.95 + rng.gauss(0, 0.06), 2),
            "unit":                "mg/dL",
            "ref_low":             0.70,
            "ref_high":            1.30,
            "ref_unit":            "mg/dL",
            "collection_ts":       datetime(d.year, d.month, d.day, 9, 30, 0).isoformat(),
            "encounter_class":     "ambulatory",
            "lab_id":              "central-lab-A",
            "method_or_analyzer":  "enzymatic",
        })

    # Sort chronologically across all patients so the demo's
    # ingest loop sees them in the order a real stream would.
    raw_results.sort(key=lambda r: r["collection_ts"])

    return raw_results
```

---

## Step 1: Harmonize Incoming Lab Results

This step takes raw source-system results, maps each test code to a canonical LOINC code, converts the unit to the canonical UCUM unit per LOINC, and tags the encounter context. In production this is an AWS Glue job that reads new HealthLake Observations on a schedule and writes the harmonized rows to S3 partitioned by LOINC and date. The demo does the equivalent in plain Python so you can trace what each transform accomplishes.

```python
def _convert_units(value, from_unit, to_unit, loinc_code):
    """Convert a numeric value between units for a specific LOINC code.

    UCUM conversion is mostly mechanical. A few analytes need a
    molecular-weight factor because the conversion crosses mass
    and molar units (mg/dL vs mmol/L for glucose, mg/dL vs umol/L
    for creatinine). The per-LOINC catalog carries those factors
    so the helper picks the right one.

    Returns the converted value, or None if the conversion is
    unsupported for this LOINC code (which should quarantine the
    record for manual review rather than guess).
    """
    if value is None:
        return None
    if from_unit == to_unit:
        return float(value)

    catalog = LOINC_CATALOG.get(loinc_code)
    if not catalog:
        return None

    # Creatinine: mg/dL <-> umol/L using umol_factor.
    if loinc_code == "2160-0":
        if from_unit == "umol/L" and to_unit == "mg/dL":
            return float(value) / catalog["umol_factor"]
        if from_unit == "mg/dL" and to_unit == "umol/L":
            return float(value) * catalog["umol_factor"]

    # Glucose-like analytes: mg/dL <-> mmol/L using molecular weight.
    # Not exercised by the demo's synthetic data; covered here so
    # production extension is straightforward.
    if from_unit == "mg/dL" and to_unit == "mmol/L":
        mw = catalog.get("molecular_weight")
        if mw:
            return float(value) * 10.0 / mw   # mg/dL -> mmol/L
    if from_unit == "mmol/L" and to_unit == "mg/dL":
        mw = catalog.get("molecular_weight")
        if mw:
            return float(value) * mw / 10.0

    # Hemoglobin: g/dL <-> g/L is a linear x10 / /10 conversion.
    if loinc_code == "718-7":
        if from_unit == "g/L" and to_unit == "g/dL":
            return float(value) / 10.0
        if from_unit == "g/dL" and to_unit == "g/L":
            return float(value) * 10.0

    # Platelet count: 10*3/uL == K/uL == 10^9/L are equivalent
    # numeric values; only the canonical unit string differs.
    if loinc_code == "777-3":
        equivalent_units = {"10*3/uL", "K/uL", "10^9/L", "10*9/L"}
        if from_unit in equivalent_units and to_unit in equivalent_units:
            return float(value)

    # Unsupported conversion. Better to quarantine than to guess.
    return None


def harmonize_lab_result(raw_result, healthlake, s3, bucket):
    """Step 1: Map source code to LOINC, convert units, tag context.

    See pseudocode Step 1 in the main recipe. Returns the
    harmonized record on success, or None if mapping or conversion
    failed (in which case the record is logged for manual review).
    """
    # 1a. Look up the canonical LOINC code for the source-system
    # test code. Failing the mapping is far better than guessing;
    # an unmapped record gets quarantined for manual review.
    key = (raw_result["source_system"], raw_result["source_test_code"])
    canonical_loinc = SOURCE_CODE_TO_LOINC.get(key)
    if canonical_loinc is None:
        logger.warning("unmapped source test code: %s/%s",
                       raw_result["source_system"],
                       raw_result["source_test_code"])
        # Production writes this to a quarantine prefix for the
        # terminology team's daily review.
        return None

    catalog = LOINC_CATALOG.get(canonical_loinc)
    if catalog is None:
        logger.warning("LOINC %s not in catalog", canonical_loinc)
        return None

    # 1b. Convert the value and the lab's reference range to the
    # canonical UCUM unit. The patient's own baseline drives
    # trend analysis, but the lab's reference range is still
    # useful context on the surfaced payload.
    canonical_unit = catalog["canonical_unit"]
    canonical_value = _convert_units(
        raw_result["value"], raw_result["unit"],
        canonical_unit, canonical_loinc)
    if canonical_value is None:
        logger.warning(
            "unit conversion failed: %s %s -> %s for LOINC %s",
            raw_result["value"], raw_result["unit"],
            canonical_unit, canonical_loinc)
        return None
    canonical_ref_low = _convert_units(
        raw_result.get("ref_low"), raw_result.get("ref_unit"),
        canonical_unit, canonical_loinc)
    canonical_ref_high = _convert_units(
        raw_result.get("ref_high"), raw_result.get("ref_unit"),
        canonical_unit, canonical_loinc)

    # 1c. Tag the encounter context. Inpatient and emergency
    # results are tagged acute and excluded from chronic-trend
    # baselines. Ambulatory and outpatient lab visits are tagged
    # chronic. The exact list depends on the EHR's encounter-
    # class vocabulary; the demo uses a small illustrative set.
    encounter_class = raw_result.get("encounter_class", "ambulatory")
    context_tag = ("acute"
                   if encounter_class in ACUTE_ENCOUNTER_CLASSES
                   else "chronic")

    harmonized = {
        "patient_id":          raw_result["patient_id"],
        "loinc_code":          canonical_loinc,
        "value":               round(canonical_value, 4),
        "unit":                canonical_unit,
        "collection_ts":       raw_result["collection_ts"],
        "encounter_class":     encounter_class,
        "context_tag":         context_tag,
        "source_system":       raw_result["source_system"],
        "source_test_code":    raw_result["source_test_code"],
        "source_lab":          raw_result.get("lab_id"),
        "source_method":       raw_result.get("method_or_analyzer"),
        "source_ref_low":      canonical_ref_low,
        "source_ref_high":     canonical_ref_high,
        "source_ref_unit":     canonical_unit,
    }

    # 1d. Persist to HealthLake as a FHIR Observation (production
    # does this via the FHIR REST API; the mock stores a plain
    # dict the search helper can return). Also write a copy of
    # the harmonized row to S3 partitioned by LOINC code and
    # date so the downstream baseline and trend jobs can read it
    # as Parquet without paying the FHIR-search cost.
    fhir_observation = {
        "resourceType":      "Observation",
        "subject_reference": f"Patient/{harmonized['patient_id']}",
        "code_loinc":        harmonized["loinc_code"],
        "value_quantity":    harmonized["value"],
        "value_unit":        harmonized["unit"],
        "effective_dt":      harmonized["collection_ts"],
        "encounter_class":   harmonized["encounter_class"],
        "context_tag":       harmonized["context_tag"],
        "ref_low":           harmonized["source_ref_low"],
        "ref_high":          harmonized["source_ref_high"],
        "method":            harmonized["source_method"],
    }
    healthlake.put_observation(fhir_observation)

    # Partition by LOINC + year/month so the baseline job can
    # do predicate pushdown when reading.
    eff_dt = datetime.fromisoformat(harmonized["collection_ts"])
    s3_key = (f"loinc={harmonized['loinc_code']}/"
              f"year={eff_dt.year:04d}/month={eff_dt.month:02d}/"
              f"{harmonized['patient_id']}-{uuid.uuid4()}.json")
    s3.put_object(Bucket=bucket, Key=s3_key,
                  Body=json.dumps(harmonized))

    return harmonized


def harmonize_lab_results(raw_results, healthlake, s3, bucket):
    """Convenience wrapper that runs harmonization across a batch.

    Production calls per-record harmonization inside a Glue job
    that reads the source-system feed in micro-batches; the demo
    iterates a Python list.
    """
    harmonized = []
    quarantined = 0
    for raw in raw_results:
        h = harmonize_lab_result(raw, healthlake, s3, bucket)
        if h is None:
            quarantined += 1
        else:
            harmonized.append(h)
    logger.info(
        "Harmonized %d of %d raw results (%d quarantined)",
        len(harmonized), len(raw_results), quarantined)
    return harmonized
```

---

## Step 2: Maintain Per-Patient Baselines

For each (patient, LOINC code) pair, the pipeline keeps a rolling baseline computed only from chronic-context measurements over a configurable window. The robust statistic (interquartile mean) resists outliers, so a single weird value does not destabilize the comparison. Acute-context values are intentionally excluded; including a patient's hospitalization labs in their outpatient creatinine baseline produces unstable comparisons.

```python
def _interquartile_mean(values):
    """Mean of the values between the 25th and 75th percentile.

    A robust central-tendency statistic that resists outliers.
    Production uses scipy.stats.trim_mean(values, 0.25) which is
    the standard implementation; the demo computes it from
    primitives so the math is visible.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n < 4:
        # Too few values for meaningful trimming. Fall back to mean.
        return sum(sorted_vals) / n
    lo = int(n * 0.25)
    hi = int(n * 0.75)
    if hi <= lo:
        return sorted_vals[lo]
    trimmed = sorted_vals[lo:hi]
    return sum(trimmed) / len(trimmed) if trimmed else sum(sorted_vals) / n


def _median_absolute_deviation(values):
    """Robust dispersion measure: median of |x - median(x)|.

    More resistant to outliers than standard deviation. Production
    uses scipy.stats.median_abs_deviation; the demo computes it
    from primitives.
    """
    if not values:
        return 0.0
    m = median(values)
    return median([abs(v - m) for v in values])


def update_patient_baseline(patient_id, loinc_code, healthlake, s3,
                            baseline_bucket,
                            window_months=DEFAULT_BASELINE_WINDOW_MONTHS,
                            now_dt=None):
    """Step 2: Compute the per-patient rolling baseline for a single lab.

    See pseudocode Step 2 in the main recipe. Returns the baseline
    dict on success. Insufficient-history baselines are written
    too, with status="insufficient_history", so the downstream
    detector can short-circuit cleanly.
    """
    if now_dt is None:
        now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    from_dt = (now_dt - timedelta(days=int(window_months * 30.5))).isoformat()
    to_dt   = now_dt.isoformat()

    # Pull the chronic-context history for this (patient, lab)
    # over the window. Production queries HealthLake with a FHIR
    # Search request:
    #     GET /Observation?subject=Patient/{patient_id}
    #         &code=http://loinc.org|{loinc_code}
    #         &date=ge{from}&date=le{to}
    # plus a custom extension or tag for context_tag=chronic.
    all_obs = healthlake.search_observations(
        patient_id=patient_id, loinc_code=loinc_code,
        from_ts=from_dt, to_ts=to_dt)
    chronic = [o for o in all_obs if o.get("context_tag") == "chronic"]

    catalog = LOINC_CATALOG.get(loinc_code, {})
    minimum = catalog.get("baseline_min_samples", DEFAULT_BASELINE_MIN_SAMPLES)
    if len(chronic) < minimum:
        baseline = {
            "patient_id":   patient_id,
            "loinc_code":   loinc_code,
            "status":       "insufficient_history",
            "sample_count": len(chronic),
            "updated_ts":   now_dt.isoformat(),
        }
        # Persist insufficient-history baselines too. Downstream
        # consumers want to know the baseline exists with that
        # status rather than missing entirely.
        s3_key = f"baselines/{patient_id}/{loinc_code}.json"
        s3.put_object(Bucket=baseline_bucket, Key=s3_key,
                      Body=json.dumps(baseline))
        return baseline

    values = [o["value_quantity"] for o in chronic]
    baseline_value      = _interquartile_mean(values)
    baseline_dispersion = _median_absolute_deviation(values)

    baseline = {
        "patient_id":          patient_id,
        "loinc_code":          loinc_code,
        "status":              "ready",
        "baseline_value":      round(baseline_value, 4),
        "baseline_dispersion": round(baseline_dispersion, 4),
        "sample_count":        len(chronic),
        "window_start_ts":     min(o["effective_dt"] for o in chronic),
        "window_end_ts":       max(o["effective_dt"] for o in chronic),
        "updated_ts":          now_dt.isoformat(),
    }

    s3_key = f"baselines/{patient_id}/{loinc_code}.json"
    s3.put_object(Bucket=baseline_bucket, Key=s3_key,
                  Body=json.dumps(baseline))

    return baseline


def update_all_baselines(harmonized, healthlake, s3,
                         baseline_bucket, now_dt=None):
    """Compute baselines for every (patient, lab) seen in the batch.

    Production runs this as a Glue job that scans the
    harmonized-results prefix and updates baselines for every
    affected (patient, lab) pair. The demo iterates the in-memory
    harmonized list.
    """
    pairs = {(h["patient_id"], h["loinc_code"]) for h in harmonized}
    baselines = {}
    for patient_id, loinc_code in pairs:
        baselines[(patient_id, loinc_code)] = update_patient_baseline(
            patient_id, loinc_code, healthlake, s3,
            baseline_bucket, now_dt=now_dt)
    logger.info("Updated %d baselines", len(baselines))
    return baselines
```

---

## Step 3: Run Trend Detection

Different labs benefit from different detectors. The demo implements four pedagogical detectors that share a common `run` interface so the per-LOINC routing is straightforward:

- **Theil-Sen plus Mann-Kendall** for slow chronic-disease slopes (creatinine, A1c, hemoglobin). Theil-Sen is a non-parametric slope estimator robust to outliers; Mann-Kendall is a non-parametric rank test for monotonic trend significance.
- **CUSUM (cumulative sum)** for change-point detection on previously-stable patients (platelets dropping after a regimen change).
- **Kalman state-space filter** for irregularly sampled labs that benefit from continuous-time estimation with calibrated uncertainty (TSH).

Production swaps these for the corresponding statsmodels, scipy, and pykalman implementations. The interface (`run(recent_values, baseline_value, baseline_dispersion) -> trend dict`) is what matters for the routing logic.

```python
def _days_between_iso(ts_a, ts_b):
    """Days from ts_a to ts_b, both ISO strings."""
    a = datetime.fromisoformat(ts_a)
    b = datetime.fromisoformat(ts_b)
    return (b - a).total_seconds() / 86400.0


class TheilSenDetector:
    """Pedagogical Theil-Sen + Mann-Kendall detector.

    Production uses scipy.stats.theilslopes for the slope and
    scipy.stats.kendalltau (or pymannkendall.original_test) for
    the trend-significance test. The demo computes both from
    primitives so the math is visible.
    """

    name = "theil_sen"

    def run(self, recent, baseline_value, baseline_dispersion):
        """Compute a normalized trend object for a recent series."""
        if len(recent) < 3:
            return {"trend_status": "insufficient_data"}

        # Convert to (days_from_start, value) pairs so the slope
        # is per day and easy to convert to per-month.
        first_ts = recent[0]["effective_dt"]
        points = [
            (_days_between_iso(first_ts, o["effective_dt"]),
             float(o["value_quantity"]))
            for o in recent
        ]

        # Theil-Sen slope: median of all pairwise slopes. Robust
        # to outliers and does not assume normality. The demo's
        # pure-Python version is O(n^2); scipy has an O(n log n)
        # variant when n is large.
        pairwise = []
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                dx = points[j][0] - points[i][0]
                dy = points[j][1] - points[i][1]
                if dx > 0:
                    pairwise.append(dy / dx)
        if not pairwise:
            return {"trend_status": "insufficient_data"}
        slope_per_day = median(pairwise)
        slope_per_month = slope_per_day * 30.0

        # Mann-Kendall S statistic and a normal-approximation
        # p-value. For each pair (i, j) with i < j: +1 if
        # values[j] > values[i], -1 if less, 0 if tied.
        n = len(points)
        s = 0
        for i in range(n):
            for j in range(i + 1, n):
                vi, vj = points[i][1], points[j][1]
                if   vj > vi: s += 1
                elif vj < vi: s -= 1
        # Variance under H0 of no trend (no ties correction).
        var_s = (n * (n - 1) * (2 * n + 5)) / 18.0
        if var_s <= 0:
            z = 0.0
        else:
            sd = math.sqrt(var_s)
            if   s > 0: z = (s - 1) / sd
            elif s < 0: z = (s + 1) / sd
            else:       z = 0.0
        # Two-sided normal approximation for the p-value.
        p_value = 2.0 * (1.0 - _normal_cdf(abs(z)))
        # Floor the p-value so log/format calls do not surprise.
        p_value = max(min(p_value, 1.0), 1e-6)

        latest_value = points[-1][1]
        deviation = latest_value - baseline_value

        # Trend duration approximated as the span of the recent
        # window (days between first and last point). Production
        # may run a change-point detection upstream and use the
        # detected change-point as the trend start.
        duration_days = points[-1][0] - points[0][0]

        return {
            "trend_status":              "ok",
            "method":                    self.name,
            "slope_per_month":           slope_per_month,
            "slope_p_value":             p_value,
            "deviation_from_baseline":   deviation,
            "trend_duration_days":       duration_days,
            "most_recent_value":         latest_value,
            "baseline_value":            baseline_value,
            "method_diagnostics": {
                "mann_kendall_s":         s,
                "mann_kendall_z":         z,
                "sample_count_recent":    n,
                "theil_sen_pairwise":     len(pairwise),
            },
        }


def _normal_cdf(z):
    """Standard normal CDF using the error function approximation."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


class CUSUMDetector:
    """Pedagogical CUSUM change-point detector.

    Tracks the cumulative sum of deviations from the baseline.
    A run that exceeds a control-limit multiple of the baseline
    dispersion signals a change point. Production uses
    scipy.signal-style implementations or ruptures.detection.Pelt
    for more sophisticated change-point detection.
    """

    name             = "cusum"
    K_FACTOR         = 0.5     # slack parameter (multiples of dispersion)
    H_FACTOR         = 4.0     # control limit (multiples of dispersion)

    def run(self, recent, baseline_value, baseline_dispersion):
        if len(recent) < 4:
            return {"trend_status": "insufficient_data"}
        if baseline_dispersion <= 0:
            baseline_dispersion = max(0.05 * abs(baseline_value), 1e-3)

        first_ts = recent[0]["effective_dt"]
        points = [
            (_days_between_iso(first_ts, o["effective_dt"]),
             float(o["value_quantity"]))
            for o in recent
        ]

        # Standardize the slack and limit by the baseline dispersion.
        k = self.K_FACTOR * baseline_dispersion
        h = self.H_FACTOR * baseline_dispersion

        # Track the high-side and low-side cumulative sums.
        cusum_pos = 0.0
        cusum_neg = 0.0
        change_idx_pos = None
        change_idx_neg = None
        for i, (_, v) in enumerate(points):
            cusum_pos = max(0.0, cusum_pos + (v - baseline_value) - k)
            cusum_neg = min(0.0, cusum_neg + (v - baseline_value) + k)
            if cusum_pos > h and change_idx_pos is None:
                change_idx_pos = i
            if cusum_neg < -h and change_idx_neg is None:
                change_idx_neg = i

        # Decide which direction (if any) triggered the alarm.
        change_idx = None
        direction  = None
        if change_idx_pos is not None and change_idx_neg is None:
            change_idx = change_idx_pos; direction = "rising"
        elif change_idx_neg is not None and change_idx_pos is None:
            change_idx = change_idx_neg; direction = "falling"
        elif change_idx_pos is not None and change_idx_neg is not None:
            # Whichever fired first wins.
            if change_idx_pos <= change_idx_neg:
                change_idx = change_idx_pos; direction = "rising"
            else:
                change_idx = change_idx_neg; direction = "falling"

        latest_value = points[-1][1]
        deviation    = latest_value - baseline_value
        # Trend slope is the average slope from the change point
        # forward, scaled to per-month for the consumer.
        slope_per_month = 0.0
        duration_days   = 0.0
        if change_idx is not None and change_idx < len(points) - 1:
            change_day  = points[change_idx][0]
            latest_day  = points[-1][0]
            duration_days = latest_day - change_day
            if duration_days > 0:
                slope_per_day = ((points[-1][1] - points[change_idx][1])
                                 / duration_days)
                slope_per_month = slope_per_day * 30.0
        else:
            # No change point fired. Report the trend as flat.
            duration_days = points[-1][0] - points[0][0]

        # Approximate p-value: a Z-style ratio of the final
        # CUSUM magnitude over the control limit. Production uses
        # the proper ARL-based threshold; this is illustrative.
        max_cusum = max(abs(cusum_pos), abs(cusum_neg))
        z_like    = max_cusum / max(h, 1e-6)
        p_value   = max(min(2.0 * (1.0 - _normal_cdf(z_like)), 1.0), 1e-6)

        return {
            "trend_status":              "ok" if change_idx is not None else "stable",
            "method":                    self.name,
            "slope_per_month":           slope_per_month,
            "slope_p_value":             p_value,
            "deviation_from_baseline":   deviation,
            "trend_duration_days":       duration_days,
            "most_recent_value":         latest_value,
            "baseline_value":            baseline_value,
            "method_diagnostics": {
                "cusum_pos_final":  cusum_pos,
                "cusum_neg_final":  cusum_neg,
                "control_limit_h":  h,
                "change_point_idx": change_idx,
                "change_direction": direction,
                "sample_count_recent": len(points),
            },
        }


class KalmanDetector:
    """Pedagogical local-level Kalman filter for irregularly sampled labs.

    Tracks a hidden 'true' value and updates it with each new
    observation. The slope is the recovered drift between the
    latest filtered estimate and the baseline. Production uses
    pykalman, filterpy, or a state-space module from statsmodels;
    this version computes the Kalman update in primitives so the
    math is visible.
    """

    name = "kalman"
    PROCESS_VARIANCE_PER_DAY = 0.0001
    OBSERVATION_VARIANCE     = 0.05

    def run(self, recent, baseline_value, baseline_dispersion):
        if len(recent) < 3:
            return {"trend_status": "insufficient_data"}

        # Initialize the filter at the baseline with a wide prior.
        x = float(baseline_value)
        p = max(baseline_dispersion ** 2, 0.1)
        last_ts = None
        smoothed = []
        for o in recent:
            v       = float(o["value_quantity"])
            this_ts = o["effective_dt"]
            if last_ts is not None:
                dt_days = max(_days_between_iso(last_ts, this_ts), 0.0)
                p += self.PROCESS_VARIANCE_PER_DAY * dt_days
            # Kalman gain and update.
            k_gain = p / (p + self.OBSERVATION_VARIANCE)
            x      = x + k_gain * (v - x)
            p      = (1 - k_gain) * p
            smoothed.append((this_ts, x))
            last_ts = this_ts

        first_ts = smoothed[0][0]
        last_ts  = smoothed[-1][0]
        duration_days = _days_between_iso(first_ts, last_ts)
        if duration_days > 0:
            slope_per_day   = (smoothed[-1][1] - smoothed[0][1]) / duration_days
            slope_per_month = slope_per_day * 30.0
        else:
            slope_per_month = 0.0

        latest_value = float(recent[-1]["value_quantity"])
        deviation    = latest_value - baseline_value

        # Approximate p-value from the filter's uncertainty: the
        # ratio of the smoothed deviation to the posterior
        # standard deviation. Production fits the model under a
        # null hypothesis of zero drift and uses the proper
        # likelihood-ratio test.
        post_sd = math.sqrt(max(p, 1e-9))
        z_like  = abs(smoothed[-1][1] - baseline_value) / max(post_sd, 1e-6)
        p_value = max(min(2.0 * (1.0 - _normal_cdf(z_like)), 1.0), 1e-6)

        return {
            "trend_status":              "ok",
            "method":                    self.name,
            "slope_per_month":           slope_per_month,
            "slope_p_value":             p_value,
            "deviation_from_baseline":   deviation,
            "trend_duration_days":       duration_days,
            "most_recent_value":         latest_value,
            "baseline_value":            baseline_value,
            "method_diagnostics": {
                "smoothed_latest":      smoothed[-1][1],
                "posterior_variance":   p,
                "sample_count_recent":  len(recent),
            },
        }


# Registry that maps detector names to instances. Production loads
# this from the model registry and the per-LOINC catalog drives
# the selection.
DETECTOR_REGISTRY = {
    "theil_sen": TheilSenDetector(),
    "cusum":     CUSUMDetector(),
    "kalman":    KalmanDetector(),
}


def detect_trend(patient_id, loinc_code, baseline, healthlake,
                 s3, trend_score_bucket,
                 recent_window_months=DEFAULT_RECENT_WINDOW_MONTHS,
                 now_dt=None):
    """Step 3: Run the lab-appropriate trend detector.

    See pseudocode Step 3 in the main recipe. Returns a normalized
    trend dict that the relevance layer in Step 4 consumes.
    """
    if now_dt is None:
        now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    if baseline.get("status") != "ready":
        return {
            "patient_id":    patient_id,
            "loinc_code":    loinc_code,
            "trend_status":  "insufficient_data",
            "computed_at":   now_dt.isoformat(),
        }

    # Pull the recent chronic-context history for this lab.
    from_dt = (now_dt - timedelta(days=int(recent_window_months * 30.5))).isoformat()
    to_dt   = now_dt.isoformat()
    all_obs = healthlake.search_observations(
        patient_id=patient_id, loinc_code=loinc_code,
        from_ts=from_dt, to_ts=to_dt)
    recent = [o for o in all_obs if o.get("context_tag") == "chronic"]

    if len(recent) < 3:
        return {
            "patient_id":    patient_id,
            "loinc_code":    loinc_code,
            "trend_status":  "insufficient_data",
            "computed_at":   now_dt.isoformat(),
        }

    catalog       = LOINC_CATALOG.get(loinc_code, {})
    detector_name = catalog.get("detector", "theil_sen")
    detector      = DETECTOR_REGISTRY.get(detector_name)
    if detector is None:
        logger.warning("no detector registered for %s", detector_name)
        return {
            "patient_id":    patient_id,
            "loinc_code":    loinc_code,
            "trend_status":  "no_detector",
            "computed_at":   now_dt.isoformat(),
        }

    raw_trend = detector.run(
        recent=recent,
        baseline_value=baseline["baseline_value"],
        baseline_dispersion=baseline["baseline_dispersion"])
    raw_trend["patient_id"]   = patient_id
    raw_trend["loinc_code"]   = loinc_code
    raw_trend["detector"]     = detector_name
    raw_trend["computed_at"]  = now_dt.isoformat()

    # Persist the raw trend score so the suppressed-trend log in
    # Step 4 has the full diagnostic record to refer back to.
    s3_key = (f"trends/{patient_id}/{loinc_code}/"
              f"{now_dt.strftime('%Y%m%d')}.json")
    s3.put_object(Bucket=trend_score_bucket, Key=s3_key,
                  Body=json.dumps(raw_trend, default=str))

    return raw_trend


def detect_all_trends(baselines, healthlake, s3,
                      trend_score_bucket, now_dt=None):
    """Run trend detection for every (patient, lab) pair with a baseline."""
    trends = {}
    for (patient_id, loinc_code), baseline in baselines.items():
        trends[(patient_id, loinc_code)] = detect_trend(
            patient_id, loinc_code, baseline,
            healthlake, s3, trend_score_bucket, now_dt=now_dt)
    logger.info("Computed %d trend scores", len(trends))
    return trends
```

---

## Step 4: Apply the Clinical Relevance Rule Layer

Statistically significant trends are not always clinically meaningful. The relevance rule layer is a per-LOINC configuration that filters trends to those that meet a clinical threshold. The threshold combines magnitude, direction, duration, and deviation from baseline. This is where most teams underinvest and end up with alert fatigue. Get this layer right and the surfaced trends become trustworthy nudges.

```python
def _check_direction(slope_per_month, concerning_direction):
    """True if the slope direction matches the concerning direction."""
    if concerning_direction == "rising":
        return slope_per_month > 0
    if concerning_direction == "falling":
        return slope_per_month < 0
    if concerning_direction == "either":
        return slope_per_month != 0
    return False


def _severity_band(trend, rules):
    """Choose info / advisory / urgent based on how far over threshold."""
    slope_excess = (abs(trend["slope_per_month"])
                    / max(rules["minimum_slope_per_month"], 1e-6))
    deviation_excess = (abs(trend["deviation_from_baseline"])
                        / max(rules["minimum_deviation_from_baseline"], 1e-6))
    overall = max(slope_excess, deviation_excess)
    if overall >= 3.0:
        return "urgent"
    if overall >= 1.5:
        return "advisory"
    return "info"


def compose_clinician_explanation(trend, catalog, baseline_window_months):
    """Plain-language narrative that fits in the eight-second look.

    The clinician is a pattern-matcher under time pressure. The
    explanation has to give them the magnitude, the duration, the
    current value, the patient's own baseline, and the source
    context all in one sentence so they can reason with it
    quickly. The narrative is the product, not the math.
    """
    direction = "rising" if trend["slope_per_month"] > 0 else "falling"
    months_duration = max(round(trend["trend_duration_days"] / 30.0, 1), 0.1)
    return (
        f"{catalog['display']} has been {direction} at approximately "
        f"{abs(trend['slope_per_month']):.2f} {catalog['canonical_unit']} per month "
        f"over the last {months_duration} months. "
        f"Most recent value ({trend['most_recent_value']:.2f}) is "
        f"{trend['deviation_from_baseline']:+.2f} from the patient's "
        f"{baseline_window_months}-month rolling baseline "
        f"({trend['baseline_value']:.2f}). All recent values are from "
        f"chronic ambulatory care."
    )


def apply_clinical_relevance(trend, catalog,
                             baseline_window_months=DEFAULT_BASELINE_WINDOW_MONTHS):
    """Step 4: Gate the trend through the per-LOINC clinical rules.

    See pseudocode Step 4 in the main recipe. Returns a dict with
    a `surface` boolean and either the surfaced payload or the
    suppressed-reason list.
    """
    if trend.get("trend_status") in ("insufficient_data", "no_detector"):
        return {
            "surface":       False,
            "suppressed":    True,
            "reasons":       [trend["trend_status"]],
            "patient_id":    trend["patient_id"],
            "loinc_code":    trend["loinc_code"],
            "computed_at":   trend.get("computed_at"),
        }

    rules = catalog["rules"]
    failed = []

    direction_match = _check_direction(
        trend["slope_per_month"], rules["concerning_direction"])
    if not direction_match:
        failed.append("direction_mismatch")

    magnitude_pass = (
        abs(trend["slope_per_month"]) >= rules["minimum_slope_per_month"]
        and trend["slope_p_value"] <= rules["minimum_slope_significance"])
    if not magnitude_pass:
        failed.append("magnitude_or_significance_below_threshold")

    duration_pass = (
        trend["trend_duration_days"] >= rules["minimum_duration_days"])
    if not duration_pass:
        failed.append("duration_below_threshold")

    deviation_pass = (
        abs(trend["deviation_from_baseline"])
        >= rules["minimum_deviation_from_baseline"])
    if not deviation_pass:
        failed.append("deviation_below_threshold")

    if failed:
        return {
            "surface":     False,
            "suppressed":  True,
            "reasons":     failed,
            "patient_id":  trend["patient_id"],
            "loinc_code":  trend["loinc_code"],
            "computed_at": trend["computed_at"],
            "trend":       trend,
        }

    payload = {
        "patient_id":              trend["patient_id"],
        "loinc_code":               trend["loinc_code"],
        "test_display_name":        catalog["display"],
        "trend_direction":          "rising" if trend["slope_per_month"] > 0 else "falling",
        "slope_per_month":          round(trend["slope_per_month"], 4),
        "slope_p_value":            round(trend["slope_p_value"], 4),
        "trend_duration_days":      round(trend["trend_duration_days"], 1),
        "most_recent_value":        round(trend["most_recent_value"], 3),
        "most_recent_unit":         catalog["canonical_unit"],
        "baseline_value":           round(trend["baseline_value"], 3),
        "baseline_window_months":   baseline_window_months,
        "deviation_from_baseline":  round(trend["deviation_from_baseline"], 3),
        "explanation_text":         compose_clinician_explanation(
                                        trend, catalog, baseline_window_months),
        "severity_band":            _severity_band(trend, rules),
        "detector":                 trend["detector"],
        "generated_at":             trend["computed_at"],
        "model_version":            f"{trend['detector']}-{RULE_LIBRARY_VERSION}",
        "pipeline_version":         PIPELINE_VERSION,
    }
    return {
        "surface":   True,
        "suppressed": False,
        "patient_id": trend["patient_id"],
        "loinc_code": trend["loinc_code"],
        "computed_at": trend["computed_at"],
        "payload":    payload,
    }


def apply_relevance_to_all(trends):
    """Apply the relevance layer across the full trend batch."""
    surfaced  = []
    suppressed = []
    for (patient_id, loinc_code), trend in trends.items():
        catalog = LOINC_CATALOG.get(loinc_code)
        if catalog is None:
            suppressed.append({
                "patient_id":  patient_id,
                "loinc_code":  loinc_code,
                "suppressed":  True,
                "reasons":     ["loinc_not_in_catalog"],
            })
            continue
        result = apply_clinical_relevance(trend, catalog)
        if result["surface"]:
            surfaced.append(result["payload"])
        else:
            suppressed.append(result)
    logger.info(
        "Relevance results: %d surfaced, %d suppressed",
        len(surfaced), len(suppressed))
    return surfaced, suppressed
```

---

## Step 5: Deliver Surfaced Trends

The trends that pass the clinical relevance bar get written to DynamoDB keyed by patient and lab so the EHR-integrated CDS Hooks service or the inbox aggregator can fetch them with low latency. Suppressed trends go to S3 for after-the-fact analysis and rule tuning. EventBridge gets a pipeline-completion event so any downstream consumer (a population-health dashboard, a care-coordinator worklist) can refresh.

```python
def deliver_trends(surfaced, suppressed, table, event_bus,
                   cloudwatch, s3, suppressed_bucket, run_id):
    """Step 5: Write surfaced trends to DynamoDB; log suppressed trends.

    See pseudocode Step 5 in the main recipe. Returns a dict with
    counts for the orchestrator's metric emission.
    """
    # 5a. Surfaced trends to DynamoDB. The sort key combines the
    # LOINC code with the generated-at timestamp so a query for
    # the latest trend per (patient, lab) is a Query with prefix
    # condition and Limit=1 in descending order, and the historical
    # record is preserved for after-action reviews.
    written = 0
    chunk = 25
    for i in range(0, len(surfaced), chunk):
        batch = surfaced[i:i + chunk]
        with table.batch_writer() as bw:
            for payload in batch:
                sk = f"{payload['loinc_code']}#{payload['generated_at']}"
                item = {
                    "patient_id":               payload["patient_id"],
                    "loinc_code_generated_at":  sk,
                    "loinc_code":               payload["loinc_code"],
                    "generated_at":             payload["generated_at"],
                    "test_display_name":        payload["test_display_name"],
                    "trend_direction":          payload["trend_direction"],
                    "slope_per_month":          _to_decimal(payload["slope_per_month"]),
                    "slope_p_value":            _to_decimal(payload["slope_p_value"]),
                    "trend_duration_days":      _to_decimal(payload["trend_duration_days"]),
                    "most_recent_value":        _to_decimal(payload["most_recent_value"]),
                    "most_recent_unit":         payload["most_recent_unit"],
                    "baseline_value":           _to_decimal(payload["baseline_value"]),
                    "baseline_window_months":   _to_decimal(payload["baseline_window_months"]),
                    "deviation_from_baseline":  _to_decimal(payload["deviation_from_baseline"]),
                    "explanation_text":         payload["explanation_text"],
                    "severity_band":            payload["severity_band"],
                    "detector":                 payload["detector"],
                    "model_version":            payload["model_version"],
                    "pipeline_version":         payload["pipeline_version"],
                    "run_id":                   run_id,
                }
                bw.put_item(Item=item)
                written += 1

    # 5b. CURRENT pointer per (patient, lab) so the dashboard can
    # do a single GetItem instead of querying and sorting client-side.
    for payload in surfaced:
        sk = f"CURRENT#{payload['loinc_code']}"
        item = {
            "patient_id":               payload["patient_id"],
            "loinc_code_generated_at":  sk,
            "loinc_code":               payload["loinc_code"],
            "generated_at":             payload["generated_at"],
            "test_display_name":        payload["test_display_name"],
            "trend_direction":          payload["trend_direction"],
            "slope_per_month":          _to_decimal(payload["slope_per_month"]),
            "slope_p_value":            _to_decimal(payload["slope_p_value"]),
            "trend_duration_days":      _to_decimal(payload["trend_duration_days"]),
            "most_recent_value":        _to_decimal(payload["most_recent_value"]),
            "most_recent_unit":         payload["most_recent_unit"],
            "baseline_value":           _to_decimal(payload["baseline_value"]),
            "baseline_window_months":   _to_decimal(payload["baseline_window_months"]),
            "deviation_from_baseline":  _to_decimal(payload["deviation_from_baseline"]),
            "explanation_text":         payload["explanation_text"],
            "severity_band":            payload["severity_band"],
            "detector":                 payload["detector"],
            "model_version":            payload["model_version"],
            "pipeline_version":         payload["pipeline_version"],
            "run_id":                   run_id,
        }
        table.put_item(Item=item)

    # 5c. Suppressed trends to S3 for tuning. The suppressed log
    # is at least as informative as the surfaced one; build it
    # in from day one rather than realizing in month four that
    # you need it for rule calibration.
    suppressed_key = (
        f"suppressed/run_id={run_id}/"
        f"date={datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json")
    s3.put_object(Bucket=suppressed_bucket, Key=suppressed_key,
                  Body=json.dumps(suppressed, default=str))

    # 5d. EventBridge completion event. The payload deliberately
    # carries no PHI: just the run identifier, surfaced and
    # suppressed counts, and the pipeline version.
    event_bus.put_events(Entries=[{
        "Source":       "lab.trend",
        "DetailType":   "TrendBatchCompleted",
        "EventBusName": TREND_EVENT_BUS_NAME,
        "Time":         datetime.now(timezone.utc),
        "Detail":       json.dumps({
            "run_id":            run_id,
            "surfaced_count":    len(surfaced),
            "suppressed_count":  len(suppressed),
            "pipeline_version":  PIPELINE_VERSION,
            "rule_version":      RULE_LIBRARY_VERSION,
        }),
    }])

    # 5e. CloudWatch metrics. Per-LOINC surfaced and suppressed
    # counts let the operations team monitor alert volume per
    # clinician and per panel. Alert volume is the single most
    # important operational metric because alert fatigue is the
    # main failure mode.
    surfaced_by_loinc = defaultdict(int)
    for payload in surfaced:
        surfaced_by_loinc[payload["loinc_code"]] += 1
    suppressed_by_loinc = defaultdict(int)
    for s in suppressed:
        if "loinc_code" in s:
            suppressed_by_loinc[s["loinc_code"]] += 1

    metric_data = [
        {"MetricName": "TrendsSurfaced",
         "Value":      float(len(surfaced)),
         "Unit":       "Count"},
        {"MetricName": "TrendsSuppressed",
         "Value":      float(len(suppressed)),
         "Unit":       "Count"},
    ]
    for loinc, count in surfaced_by_loinc.items():
        metric_data.append({
            "MetricName": "TrendsSurfacedByLoinc",
            "Value":      float(count),
            "Unit":       "Count",
            "Dimensions": [{"Name": "LoincCode", "Value": loinc}],
        })
    cloudwatch.put_metric_data(
        Namespace=CLOUDWATCH_NAMESPACE,
        MetricData=metric_data)

    logger.info(
        "Delivered: %d surfaced to DynamoDB, %d suppressed to S3",
        written, len(suppressed))
    return {
        "surfaced_written":  written,
        "suppressed_logged": len(suppressed),
    }
```

---

## Full Pipeline

Stitching the steps together. Production runs each step as a separate Step Functions task with retries, error handling, and CloudWatch alarms; the demo runs them sequentially in one process so you can see the data flow.

```python
def run_lab_trend_pipeline(table, event_bus, cloudwatch,
                           healthlake, s3, now_dt=None):
    """End-to-end pipeline orchestration.

    The demo wires up synthetic data; production starts with a
    HealthLake search for the day's new Observations or an S3
    read of the harmonized prefix populated by the streaming
    ingest job.
    """
    run_id = str(uuid.uuid4())
    print(f"\n=== Lab Result Trend Analysis Pipeline run_id={run_id} ===\n")

    if now_dt is None:
        now_dt = datetime.now(timezone.utc).replace(tzinfo=None)

    # --- Generate synthetic input data (production reads from HealthLake) ---
    raw_results = generate_synthetic_lab_results()
    print(f"[input] {len(raw_results)} synthetic raw lab results")

    # --- Step 1: Harmonize ---
    print("\n[step 1] harmonize_lab_results")
    harmonized = harmonize_lab_results(
        raw_results, healthlake, s3, HARMONIZED_BUCKET)
    print(f"  -> {len(harmonized)} harmonized rows")
    distinct_pairs = {(h["patient_id"], h["loinc_code"]) for h in harmonized}
    print(f"  -> {len(distinct_pairs)} distinct (patient, lab) pairs")

    # --- Step 2: Update baselines ---
    print("\n[step 2] update_all_baselines")
    baselines = update_all_baselines(
        harmonized, healthlake, s3,
        PATIENT_BASELINE_BUCKET, now_dt=now_dt)
    ready_count = sum(1 for b in baselines.values() if b.get("status") == "ready")
    print(f"  -> {ready_count} baselines ready, "
          f"{len(baselines) - ready_count} insufficient")

    # --- Step 3: Detect trends ---
    print("\n[step 3] detect_all_trends")
    trends = detect_all_trends(
        baselines, healthlake, s3, TREND_SCORE_BUCKET, now_dt=now_dt)
    runnable = sum(1 for t in trends.values() if t.get("trend_status") == "ok")
    print(f"  -> {runnable} of {len(trends)} trends produced an 'ok' score")

    # --- Step 4: Apply clinical relevance ---
    print("\n[step 4] apply_relevance_to_all")
    surfaced, suppressed = apply_relevance_to_all(trends)
    print(f"  -> {len(surfaced)} surfaced, {len(suppressed)} suppressed")

    # --- Step 5: Deliver ---
    print("\n[step 5] deliver_trends")
    delivery = deliver_trends(
        surfaced, suppressed, table, event_bus, cloudwatch,
        s3, SUPPRESSED_TREND_BUCKET, run_id)
    print(f"  -> wrote {delivery['surfaced_written']} surfaced records")
    print(f"  -> logged {delivery['suppressed_logged']} suppressed records")
    print(f"  -> emitted {len(event_bus.events)} EventBridge events")
    print(f"  -> emitted CloudWatch metrics: "
          f"{sorted(cloudwatch.metrics.keys())}")

    return surfaced, suppressed


def run_demo():
    """Run the pipeline end-to-end against the in-memory mocks.

    No AWS resources are touched; every external dependency is
    a mock. Useful for sanity-checking the trend-detection logic
    and the relevance gating before wiring to real services.
    """
    table       = MockTable(PATIENT_TRENDS_TABLE)
    event_bus   = MockEventBus(TREND_EVENT_BUS_NAME)
    cloudwatch  = MockCloudWatch()
    healthlake  = MockHealthLake()
    s3          = MockS3()

    surfaced, suppressed = run_lab_trend_pipeline(
        table, event_bus, cloudwatch, healthlake, s3)

    print("\n=== Surfaced trends ===")
    for payload in surfaced:
        print(f"  {payload['patient_id']:>20} "
              f"{payload['loinc_code']:>8} "
              f"{payload['trend_direction']:>7} "
              f"slope={payload['slope_per_month']:+.3f}/mo "
              f"dur={payload['trend_duration_days']:>5.0f}d "
              f"dev={payload['deviation_from_baseline']:+.2f} "
              f"sev={payload['severity_band']:>8}")

    if surfaced:
        print("\n=== Sample surfaced payload ===")
        sample = surfaced[0]
        # Add the DynamoDB CURRENT-record view for comparison.
        sample_pk = sample["patient_id"]
        sample_sk = f"CURRENT#{sample['loinc_code']}"
        ddb_view  = table.items.get((sample_pk, sample_sk))

        def _decimalify(o):
            if isinstance(o, Decimal):
                return str(o)
            if isinstance(o, datetime):
                return o.isoformat()
            return o
        print(json.dumps(ddb_view, default=_decimalify, indent=2))

    print("\n=== Sample suppressed reasons ===")
    for s in suppressed[:5]:
        reasons = s.get("reasons", ["unknown"])
        print(f"  {s.get('patient_id', '?'):>20} "
              f"{s.get('loinc_code', '?'):>8} "
              f"reasons={reasons}")

    return surfaced, suppressed


if __name__ == "__main__":
    run_demo()
```

---

## Sample Output

Running the demo against the in-memory mocks produces output like this. Numbers vary because of the synthetic-data noise but the surface-vs-suppress decisions, the detector selection, and the explanation narrative are deterministic given the seed.

```text
=== Lab Result Trend Analysis Pipeline run_id=8f3a... ===

[input] 102 synthetic raw lab results

[step 1] harmonize_lab_results
  -> 102 harmonized rows
  -> 5 distinct (patient, lab) pairs

[step 2] update_all_baselines
  -> 5 baselines ready, 0 insufficient

[step 3] detect_all_trends
  -> 5 of 5 trends produced an 'ok' score

[step 4] apply_relevance_to_all
  -> 3 surfaced, 2 suppressed

[step 5] deliver_trends
  -> wrote 3 surfaced records
  -> logged 2 suppressed records
  -> emitted 1 EventBridge events
  -> emitted CloudWatch metrics: ['LabTrendAnalysis/TrendsSurfaced', 'LabTrendAnalysis/TrendsSurfacedByLoinc', 'LabTrendAnalysis/TrendsSuppressed']

=== Surfaced trends ===
       patient-CKD-001    2160-0  rising slope=+0.061/mo dur=  ...d dev=+0.43 sev= advisory
        patient-DM-002    4548-4  rising slope=+0.148/mo dur=  ...d dev=+1.23 sev= advisory
       patient-BMS-003     777-3 falling slope=-21.804/mo dur= 120d dev=-95.0 sev=   urgent

=== Sample surfaced payload ===
{
  "patient_id": "patient-CKD-001",
  "loinc_code_generated_at": "CURRENT#2160-0",
  "loinc_code": "2160-0",
  "test_display_name": "Creatinine, Serum",
  "trend_direction": "rising",
  "slope_per_month": "0.061",
  "slope_p_value": "0.000001",
  "trend_duration_days": "..." ,
  "most_recent_value": "1.61",
  "most_recent_unit": "mg/dL",
  "baseline_value": "1.18",
  "baseline_window_months": "12",
  "deviation_from_baseline": "0.43",
  "explanation_text": "Creatinine, Serum has been rising at approximately 0.06 mg/dL per month over the last ... months. ...",
  "severity_band": "advisory",
  "detector": "theil_sen",
  "model_version": "theil_sen-clinical-rules-2026-04",
  "pipeline_version": "lab-trend-v1.2",
  ...
}

=== Sample suppressed reasons ===
     patient-EUTH-004    3016-3 reasons=['magnitude_or_significance_below_threshold', 'duration_below_threshold', 'deviation_below_threshold']
     patient-EUTH-004    2160-0 reasons=['magnitude_or_significance_below_threshold', 'deviation_below_threshold']
```

A real pipeline against a single PCP panel of a few thousand active patients runs the nightly cycle in a few tens of minutes on a small SageMaker endpoint, produces the same shape of output, and writes the records straight to a real DynamoDB table that the EHR's CDS Hooks responder queries during chart open.

---

## Gap to Production

The demo is intentionally a sketch. Here is the distance between this code and something you would deploy.

**Real statistical libraries, not demo helpers.** The `TheilSenDetector`, `CUSUMDetector`, and `KalmanDetector` in this file are pedagogical stand-ins. Production replaces `TheilSenDetector` with [`scipy.stats.theilslopes`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.theilslopes.html) for the slope and [`scipy.stats.kendalltau`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kendalltau.html) (or [`pymannkendall.original_test`](https://github.com/mmhs013/pyMannKendall)) for the Mann-Kendall significance test. Replace `CUSUMDetector` with a [`ruptures`](https://centre-borelli.github.io/ruptures-docs/) or [`changepy`](https://github.com/ruipgil/changepy) implementation that handles tied values, ties correction, and the proper ARL-based control limits. Replace `KalmanDetector` with [`pykalman`](https://pykalman.github.io/), [`filterpy`](https://filterpy.readthedocs.io/), or a [`statsmodels` state-space model](https://www.statsmodels.org/stable/tsa.html#module-statsmodels.tsa.statespace) that handles continuous-time formulations, missing observations, and the proper likelihood-based hypothesis testing. The demo's detectors are good enough to demonstrate the routing and the relevance layer; they are not good enough to drive real clinician inboxes.

**Real HealthLake datastore, not MockHealthLake.** Replace `MockHealthLake` with `boto3.client('healthlake')` calls. Production creates the FHIR datastore once with KMS encryption at creation time, then ingests HL7 ORU-R01 messages via the [HealthLake Import API](https://docs.aws.amazon.com/healthlake/latest/devguide/import-fhir-data.html), and queries Observations via the [HealthLake Search API](https://docs.aws.amazon.com/healthlake/latest/APIReference/API_SearchWithGet.html) or the FHIR REST API directly. The harmonization Glue job runs the LOINC + UCUM mapping during ingest so the datastore stores already-canonical resources; alternatively, the mapping runs as a downstream Glue job that writes the canonical form to a separate S3 prefix. Either approach is defensible; the choice depends on whether downstream consumers query HealthLake directly or read the canonical S3 store.

**Real S3 prefixes, not MockS3.** Replace `MockS3` with `boto3.client('s3')` calls. Production has separate prefixes for the raw HL7 landing zone, the harmonized output, the per-patient baselines, the trend scores, the suppressed-trend log, and the model artifacts, all encrypted with the same customer-managed KMS key. Object-level retention policies match the institutional retention floor (typically seven years for clinical operational records). The harmonized prefix is partitioned by `loinc_code/year/month` for predicate pushdown; the baseline prefix is partitioned by `patient_id` so a single-patient lookup is cheap.

**Real Glue ETL for harmonization and baseline updates.** The `harmonize_lab_results` and `update_all_baselines` functions loop over Python lists in process. Production runs each as an AWS Glue PySpark job. The harmonization job reads new HealthLake Observations on a five-minute or hourly cadence, applies the LOINC + UCUM mapping, joins against the per-patient encounter context, and writes harmonized rows partitioned by LOINC and date. The baseline job runs on a nightly cadence, scans the harmonized prefix for any (patient, lab) pair affected by new chronic-context values, and writes updated baselines to S3 partitioned by patient. Both jobs use the Glue service role with scoped HealthLake, S3, and KMS permissions.

**Real SageMaker endpoints, not in-process detectors.** The `detect_all_trends` function calls the detector classes directly. Production hosts the detector library as one or more SageMaker endpoints. A common pattern: a single multi-model SageMaker endpoint that loads the appropriate detector by LOINC code at invocation time, fronted by a Lambda that handles the LOINC-to-detector routing. The endpoint runs in a private VPC subnet with VPC endpoints to S3, KMS, and CloudWatch Logs. Model packages are promoted via SageMaker Model Registry with manual approval, and a shadow-deployment step runs the new model in parallel for at least a week before cutting traffic over.

**Real Lambda for clinical relevance.** The `apply_relevance_to_all` function runs in process. Production wraps the relevance logic in an AWS Lambda function triggered by the Step Functions workflow. The Lambda reads the per-LOINC catalog from a config object in S3 (or from AWS AppConfig if the rules change frequently), reads each trend score from S3, applies the rules, writes surfaced trends to DynamoDB, and writes suppressed trends to a separate S3 prefix. Updating a rule is a config change rather than a Lambda redeploy, which is the right mode for the calibration cycle the relevance layer goes through.

**Real DynamoDB, not MockTable.** Replace `MockTable` with `boto3.resource('dynamodb').Table(PATIENT_TRENDS_TABLE)`. The table needs a partition key (`patient_id`, type S), a sort key (`loinc_code_generated_at`, type S), encryption-at-rest with a customer-managed KMS key, point-in-time recovery enabled, on-demand billing for the unpredictable load that comes with a multi-clinic rollout (or provisioned with auto-scaling for predictable single-clinic load), a global secondary index on `(loinc_code, generated_at)` if dashboards filter by lab across patients, and an item-level TTL on the historical (non-CURRENT) records so the table does not grow unbounded. Also handle the `BatchWriteItem` `UnprocessedItems` response with exponential backoff; `MockTable` ignores this case but DynamoDB returns unprocessed items under throttling.

**Real Step Functions orchestration.** The pipeline-orchestration logic (harmonize -> baseline -> detect -> filter -> deliver) runs as an AWS Step Functions state machine in production. Each step is a Glue job, a Lambda, or a SageMaker invocation, with `Retry` and `Catch` blocks for transient failures, a `Map` state for parallel per-patient detection, and an `EventBridge` schedule that fires nightly. The state machine emits `ExecutionFailed` events to a CloudWatch alarm so on-call gets paged when a run fails.

**Real EventBridge bus and CloudWatch alarms.** The `MockEventBus` and `MockCloudWatch` accumulate events and metrics in process. Production uses real `boto3.client('events').put_events(...)` and `boto3.client('cloudwatch').put_metric_data(...)`, plus CloudWatch alarms on per-LOINC surfaced volume (alarm if surfaced count per clinician per day exceeds tolerance, which is the leading indicator of alert fatigue creeping in), pipeline-execution latency, DynamoDB write throttling, SageMaker endpoint 5xx rate, and harmonization mapping coverage (alarm if coverage drops below the calibrated threshold, which indicates a new source code has appeared without a mapping). The alarms feed an SNS topic that pages the on-call ML engineer.

**Medication and intervention awareness.** A patient whose creatinine is climbing because they were started on an ACE inhibitor for blood pressure control is on an expected trajectory, not a concerning one. The demo has no concept of medication context. Production integrates medication history either as features in the detector (treat the start of an ACE inhibitor as a known regime change point) or as a post-detection filter (suppress trends temporally adjacent to relevant medication starts). This is the single most important refinement after the basic pipeline works.

**Baseline reset events.** Some clinical events legitimately reset the patient's baseline: starting a new chronic medication, transitioning between therapy lines, a major surgery, a new diagnosis. The demo computes a single rolling baseline. Production tracks these reset events explicitly (event-driven baseline resets) or detects them via change-point analysis upstream of the trend detector and resets the baseline at the detected change point. Without this, a patient's old baseline can produce misleading "trends" that are really just regime changes the system should have known about.

**Triage / encounter-class reconciliation.** The demo assumes the encounter class is known at result time and never changes. In production, the encounter class can be reclassified after the fact (an outpatient visit upgraded to observation, an observation downgraded to ambulatory follow-up). The pipeline either runs a reconciliation pass that updates the context tag and recomputes affected baselines, or accepts that the chronic-context tag is a snapshot at result time and tolerates the small bias that introduces. Most production teams choose reconciliation because the bias is operationally meaningful.

**Multi-lab joint reasoning.** Some trends matter much more in combination than in isolation. A rising creatinine plus a falling hemoglobin plus an unchanged platelet count is a different story than any one of those alone. The demo surfaces each trend independently. Production runs panel-level rules that look for combinations and surfaces the integrated finding. This is where Recipe 7.x (predictive analytics) starts to overlap; the architecture extension is straightforward but the rule-engineering effort is non-trivial.

**Clinician feedback capture.** Every surfaced trend should have a feedback path: was this useful, did you take action, did you dismiss it. The demo has no feedback loop. Production captures the clinician's interaction with each surfaced trend (via CDS Hooks accept/reject signals or an inbox aggregator's UI), writes those signals to a feedback table, and feeds them into the rule-tuning pipeline. Without this, the system stays calibrated to its launch-day rules forever.

**EHR integration via CDS Hooks or FHIR Subscriptions.** The DynamoDB-backed surface is fine for an inbox aggregator or a population-health dashboard. For in-workflow CDS, the pipeline needs a [CDS Hooks](https://cds-hooks.org/) responder fronted by API Gateway and Lambda, exposed to the EHR vendor's CDS client. The Lambda receives the `patient-view` hook fired during chart open, queries DynamoDB for the patient's CURRENT trends, and returns CDS Hooks Card responses. The integration is highly EHR-vendor-specific; budget more time than the engineering estimate suggests.

**Lab harmonization quality assurance.** The harmonization layer is the single biggest source of subtle bugs in the pipeline. Production runs continuous quality checks on the harmonized output: distribution shifts in a LOINC code over time (a sign that a new source is sending different values), sudden changes in unit distribution (a sign that a source switched analyzers without telling you), new source codes appearing without a mapping (a sign that the mapping table needs to be updated), and a small number of canary "known answer" results that the pipeline should map identically every time (an integration test against the live mapping). Catching a harmonization error in week three is two weeks of bad trends; catching it in month three is a much bigger cleanup.

**Idempotency and rerun safety.** The nightly pipeline can fail and need to be rerun. Each step needs to be safe to repeat: harmonization is idempotent on (patient_id, source_code, collection_ts); baseline computation is deterministic given the input; trend detection is deterministic given the inputs; DynamoDB writes overwrite cleanly by primary key. The demo achieves this naturally because the pure-Python helpers do not retain state across runs; production has to be deliberate about each step's idempotency contract.

**HIPAA controls end-to-end.** The HealthLake datastore uses encryption with a customer-managed KMS key; the S3 prefixes use SSE-KMS with the same key family; the DynamoDB table uses encryption-at-rest with a customer-managed key; SageMaker training and inference jobs run in a VPC with VPC endpoints to S3, HealthLake, CloudWatch Logs, and KMS; the Glue job reads and writes only encrypted data; CloudTrail logs all HealthLake, S3, DynamoDB, Glue, and SageMaker API calls; CloudWatch log groups are KMS-encrypted; IAM roles are scoped to specific resource ARNs; an AWS BAA is in place. The demo touches none of this; production cannot ship without all of it.

**Audit trail.** Each pipeline run is identified by a `run_id`, all surfaced records carry that run_id and the model + rule versions, the DynamoDB writes overwrite cleanly by the `(patient_id, loinc_code_generated_at)` key, and the model-artifact S3 writes use deterministic prefixes so a rerun produces the same output. An immutable audit log captures which rule version produced which surface on which night, written through Kinesis Data Firehose into an Object-Lock S3 bucket sized to the institutional retention floor.

**Testing.** Unit tests cover the harmonization function (a known source code and unit produce the expected canonical form, an unmapped code is quarantined, an unsupported unit conversion is rejected), the baseline calculation (insufficient history returns the right status, a known-input series produces the expected interquartile mean), the detectors (a constant-rate input produces a near-zero slope, a known-slope input produces the expected slope, a step-change input produces the expected change-point), the relevance gate (a borderline-significant trend is suppressed when below the magnitude threshold, surfaced when above), and the DynamoDB write idempotency (writing the same record twice is a no-op). Integration tests run the pipeline against a known-input synthetic dataset and assert the surfaced and suppressed sets against expected values. End-to-end tests stand up real HealthLake, S3, DynamoDB, and EventBridge resources in a sandbox account and run the full Step Functions state machine.

**Structured logging.** Replace the demo's `print` calls with `logger.info(..., extra={...})` calls that emit JSON-formatted structured logs to CloudWatch Logs. Log structural metadata only (run_id, patient_id_hash, loinc_code, surface_decision, runtime_ms), never raw values, never collection timestamps tied to identifiable visits, never the per-LOINC clinical rule payload that includes the institution's calibration choices.

**Regulatory framing.** Lab trend analysis that triggers actionable clinical decisions sits in a gray zone of FDA software-as-a-medical-device (SaMD) regulation. A pipeline that surfaces "your patient's creatinine is rising; consider nephrology referral" can be characterized as clinical decision support, which is largely exempt from FDA premarket review under the 21st Century Cures Act if it meets specific transparency and explainability requirements (the explanation text on the surfaced payload is doing real work here). A pipeline that says "diagnose CKD progression" is not exempt. Working with regulatory counsel on the framing of the surfaced output is non-negotiable for any deployment that goes beyond a research pilot.

**The shape of the gap.** The trend math in this file is a sketch but it is fundamentally correct. The plumbing around it (storage, orchestration, security, harmonization quality, medication awareness, feedback capture, EHR integration, regulatory framing) is what takes the bulk of the engineering work. Plan for the plumbing to be 80% of the project; the trend detection itself routinely surprises teams by being the easier part.

---

## Related Resources

- [Recipe 12.4: Lab Result Trend Analysis](chapter12.04-lab-result-trend-analysis): The main recipe with the full architectural walkthrough this Python companion implements.
- [Amazon HealthLake Documentation](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html): The FHIR datastore that backs the longitudinal patient timeline. Lab Observations are textbook FHIR resources.
- [scipy.stats.theilslopes](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.theilslopes.html): Production-grade Theil-Sen slope estimator. Drop-in replacement for the demo's `TheilSenDetector` slope math.
- [scipy.stats.kendalltau](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kendalltau.html): Kendall tau correlation coefficient with significance test. Drop-in replacement for the demo's Mann-Kendall calculation.
- [pyMannKendall](https://github.com/mmhs013/pyMannKendall): Comprehensive Mann-Kendall implementation including the seasonal and the trend-free pre-whitening variants for autocorrelated series.
- [ruptures](https://centre-borelli.github.io/ruptures-docs/): Change-point detection library covering CUSUM, PELT, and Bayesian online change-point methods. The right replacement for the demo's `CUSUMDetector`.
- [pykalman](https://pykalman.github.io/) and [filterpy](https://filterpy.readthedocs.io/): Kalman filter implementations. Drop-in replacement for the demo's `KalmanDetector`. Statsmodels also has a [state-space module](https://www.statsmodels.org/stable/statespace.html) for more elaborate models.
- [LOINC Documentation](https://loinc.org/): The standard for lab test codes; essential for the harmonization layer. The terminology team uses the official LOINC database to maintain the source-code mapping.
- [UCUM Specification](https://ucum.org/): The unit code standard used for canonical unit conversions.
- [Synthea Synthetic Patient Generator](https://github.com/synthetichealth/synthea): Realistic synthetic FHIR patient records including longitudinal lab results. Useful for development environments where real PHI is off limits.
- [CDS Hooks Specification](https://cds-hooks.org/): The standard for in-EHR clinical decision support; the right interface for surfacing trends in chart-open workflows.
- [AWS Step Functions Map State](https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-map-state.html): Pattern for fanning out per-patient detection in parallel.
- [Forecasting: Principles and Practice (Hyndman & Athanasopoulos)](https://otexts.com/fpp3/): Free online textbook covering classical and state-space methods relevant to longitudinal lab modeling, especially the chapters on irregularly-sampled time series.
- [MIMIC-IV on PhysioNet](https://physionet.org/content/mimiciv/): De-identified ICU and hospital data for credentialed researchers, including extensive longitudinal lab time series suitable for prototyping.

---

*← [Recipe 12.4: Lab Result Trend Analysis](chapter12.04-lab-result-trend-analysis) · [Chapter 12 Index](chapter12-index) · [Next: Recipe 12.5 - Hospital Census Forecasting →](chapter12.05-hospital-census-forecasting)*
