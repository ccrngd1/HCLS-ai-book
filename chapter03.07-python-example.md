# Recipe 3.7: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 3.7. It shows one way you could translate the patient-deterioration-early-warning pattern into working Python using Amazon Kinesis (for the clinical-event stream), Amazon DynamoDB (for the patient-state store, the alert-state table, and the suppression registry), Amazon Timestream (for vitals and lab time-series history), Amazon SageMaker (for the deterioration model endpoint, Feature Store, and Clarify SHAP explanations), Amazon Bedrock (for narrative explanation generation), Amazon EventBridge (for scoring fan-out), Amazon SNS (for pager-tier notifications), Amazon OpenSearch Service (for the alert audit index), Amazon S3 (for the raw-event lake and training labels), and Amazon CloudWatch (for operational metrics). It is not production-ready. There is no real HL7 v2 / FHIR / bedside monitor parser (those are maintained libraries and projects in themselves, not teaching-example code), no SageMaker Training Job wrapper for monthly retraining, no Step Functions retraining orchestration, no clinical-governance dashboard, no real EHR banner integration, and no paging-system integration (Vocera, TigerConnect, Spok, Mobile Heartbeat each have their own SDKs and contracts). Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you would wire into a hospital's rapid response workflow on Monday morning.
>
> The code maps to the eight core pseudocode steps from the main recipe: normalize a raw clinical event into a canonical representation, update the patient-state store, trigger scoring on event or periodic schedule, compute the feature vector (current vitals, trajectory features, patient-specific baselines, lab features, medication context), score the feature vector and apply post-hoc calibration, build the per-prediction explanation (SHAP plus Bedrock narrative), route alerts through tiered destinations with suppression rules, and capture clinician acknowledgments plus eventual clinical outcomes for the retraining loop. The bedside-monitor integration, the LSTM/transformer time-series model variant, the phenotype-specific (sepsis-only, respiratory-failure-only) models, and the multi-AZ failover topology are not in this file; they are covered in the Variations and Why-This-Isn't-Production-Ready sections of the main recipe and share infrastructure with other chapter recipes (3.5 for lab features, 12.x for time-series modeling, 2.x for LLM-assisted explanations).

---

## Setup

You will need the AWS SDK for Python plus scikit-learn, pandas, numpy, and joblib for the local demonstration model:

```bash
pip install boto3 scikit-learn pandas numpy joblib
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the `patient-state`, `alert-state`, `scoring-history`, and `suppression-registry` tables
- `dynamodb:DescribeStream`, `dynamodb:GetRecords`, `dynamodb:GetShardIterator`, `dynamodb:ListStreams` on the `patient-state` stream (for the event-driven scoring trigger)
- `kinesis:PutRecord`, `kinesis:PutRecords`, `kinesis:GetRecords`, `kinesis:GetShardIterator` on the `clinical-events` stream
- `timestream:WriteRecords` on the `deterioration-history` database, `timestream:Select` on the `vitals` and `labs` tables
- `s3:GetObject` on the model-artifacts bucket; `s3:PutObject` on the raw-events lake and training-labels buckets
- `sagemaker-runtime:InvokeEndpoint` on the deterioration-model endpoint ARN
- `sagemaker-featurestore-runtime:GetRecord`, `sagemaker-featurestore-runtime:PutRecord` on the `patient-features-online` feature group
- `bedrock:InvokeModel` on the specific Bedrock model ARN you use (scope tightly; do not use `bedrock:*`)
- `events:PutEvents` on the `deterioration-scoring` bus
- `sns:Publish` on the rapid-response notification topic
- `cloudwatch:PutMetricData` for operational metrics
- The OpenSearch domain policy must allow the executing role to `es:ESHttpPost` and `es:ESHttpPut` on the `alert-index` and `scoring-index` indices

Scope each role to the specific resource ARNs it touches. The permissions above are fine for learning and will fail any serious IAM review. In production, each component (event-normalizer Lambda, scoring-orchestrator Lambda, feature-engine Lambda, calibration-layer Lambda, explanation-builder Lambda, alert-router Lambda, ack-capture Lambda, outcome-capture Lambda, retraining Step Functions workflow) gets its own role with the minimum permissions for its job.

A few things worth knowing upfront:

- **No real HL7 v2 or FHIR parsing.** Parsing HL7 v2 ADT (admit/transfer/discharge), ORU (observation results), ORM (orders), and RDE (pharmacy) messages, and parsing FHIR R4 Observation/MedicationAdministration/Encounter resources, are substantial engineering projects and belong in maintained libraries (HAPI FHIR on the JVM side, `fhir.resources` or `python-hl7` on the Python side, plus vendor integration engines like Mirth, Rhapsody, or Cloverleaf for the message routing). This example starts from a clinical event already shaped as a Python dictionary. In production, a Lambda triggered by a Kinesis record from the integration engine calls the parsing library and feeds the parsed event into the normalization step.
- **No bedside monitor integration.** Pulling vitals from EHR-charted observations is the easy path. Pulling continuous waveforms from bedside monitors (Philips IntelliVue, GE Carescape, Mindray, Drager) is a separate biomedical-engineering project that uses HL7 RxR, IHE PCD profiles, or vendor-specific protocols, often with bridge appliances (Capsule Medical, Cerner CareAware iBus, Bernoulli). The marginal feature richness of waveform data is real; the integration cost is also real. The teaching example uses EHR-charted vitals only.
- **DynamoDB table schemas.** `patient-state` is keyed on `patient_id` (partition) and `encounter_id` (sort), with a global secondary index on `is_active` for periodic-tick queries and DynamoDB Streams enabled for event-driven scoring. `alert-state` is keyed on `alert_id` (partition only), with a GSI on `patient_id` plus `triggered_at` for per-patient alert history. `scoring-history` is keyed on `patient_id` (partition) and `scored_at` (sort) with a TTL attribute for automatic expiration after the audit retention window. `suppression-registry` is keyed on `patient_id` (partition) and `suppression_type` (sort) with TTL on `expires_at`. You create these once, up front; this file does not do that for you.
- **All numeric values must be Decimal going into DynamoDB.** DynamoDB rejects Python `float` for numeric attributes. A heart rate of `92.5` becomes `Decimal("92.5")` on the way in and back to float on the way out. The helper functions below handle this so you see the pattern. For a deterioration pipeline this matters operationally: a calibrated probability stored as `0.5999999999` from float drift, compared against a `0.60` high-tier cut, produces the wrong routing today and might produce the right routing tomorrow if the threshold moves; that kind of drift is exactly the bug class clinical safety review will flag.
- **All example patient, vital, lab, and medication data is synthetic.** Patient IDs, encounter IDs, NPIs, and order IDs in the sample data are illustrative and do not refer to any real people, providers, or facilities. LOINC codes for vitals (8867-4 heart rate, 9279-1 respiratory rate, 8480-6 systolic BP, 8462-4 diastolic BP, 8310-5 body temperature, 2708-6 oxygen saturation) are real LOINC identifiers used as the canonical vital codes. Use [MIMIC-IV](https://physionet.org/content/mimiciv/) (with the required CITI training and data use agreement) or [Synthea](https://github.com/synthetichealth/synthea) for synthetic vitals trajectories in development. Never use real PHI in a teaching example.
- **The model in this example is a tiny in-process scikit-learn model.** Real deployments host the model behind a SageMaker real-time endpoint (multi-AZ for clinical reliability) or a SageMaker batch transform pipeline. We train an Isolation Forest plus a logistic regression on a small synthetic feature matrix at the bottom of the file so the scoring path runs end-to-end without a deployed endpoint. The `score_via_sagemaker_endpoint` function shows the production-shape boto3 call.
- **Calibration is shown as Platt-scaling-equivalent on a tiny held-out set.** Real calibration uses isotonic regression or Platt scaling fit on a substantial held-out validation set, then frozen and versioned alongside the model. Calibration drift over time is monitored by SageMaker Model Monitor; this example does not demonstrate that monitoring, only the application of frozen calibration parameters.
- **Alert fatigue is not simulated here.** The main recipe spends a lot of time on alert fatigue for good reason. The example code generates a tiered alert whenever the model fires above threshold. In production, a severity-tiering layer, suppression rules for known-benign patterns (active comfort care, ICU patients, recent rapid response activations), and disposition-rate monitoring sit between the raw scores and the pager-tier alerts. Building the detection is the easy part; getting the alert volume right is where the actual work happens.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here: thresholds, vital-sign code maps, baseline-window sizes, resource names, and routing tables. These are the knobs that move most often between dev, test, and production, and between clinical-governance threshold reviews. Keep them at the top of the file so a reviewer can see the levers without wading through function bodies.

```python
import io
import json
import logging
import math
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import boto3
import joblib
import numpy as np
import pandas as pd
from botocore.config import Config
from boto3.dynamodb.conditions import Key
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression

# Structured logging. Ship JSON records to CloudWatch Logs Insights. Vitals,
# labs, patient identifiers, and unit assignments are PHI. Log structural
# metadata only. Never log full vital values with patient identifiers, raw
# clinical event payloads, lab result values, or full feature vectors in
# application logs. The audit indexes (OpenSearch) and the patient-state
# store (DynamoDB) are the right home for full payloads, behind KMS and
# CloudTrail data events.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry mode handles throttling across DynamoDB, Timestream,
# Kinesis, SageMaker, and Bedrock with exponential backoff and jitter.
# Vitals charting is bursty (med-pass rounds at 0600/1200/1800/2200 on
# inpatient units, plus admission/transfer surges), and adaptive mode keeps
# burst windows from cascading into retry storms against the patient-state
# cache and the scoring endpoint.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=BOTO3_RETRY_CONFIG)
kinesis = boto3.client("kinesis", region_name=REGION, config=BOTO3_RETRY_CONFIG)
timestream_write = boto3.client("timestream-write", region_name=REGION, config=BOTO3_RETRY_CONFIG)
timestream_query = boto3.client("timestream-query", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch = boto3.client("cloudwatch", region_name=REGION, config=BOTO3_RETRY_CONFIG)
sns = boto3.client("sns", region_name=REGION, config=BOTO3_RETRY_CONFIG)
eventbridge = boto3.client("events", region_name=REGION, config=BOTO3_RETRY_CONFIG)
featurestore_runtime = boto3.client(
    "sagemaker-featurestore-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG
)
sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG)
bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill in with your actual resource names. These are placeholders.
PATIENT_STATE_TABLE = "patient-state"
ALERT_STATE_TABLE = "alert-state"
SCORING_HISTORY_TABLE = "scoring-history"
SUPPRESSION_REGISTRY_TABLE = "suppression-registry"

CLINICAL_EVENTS_STREAM = "clinical-events"
TIMESTREAM_DATABASE = "deterioration-history"
TIMESTREAM_VITALS_TABLE = "vitals"
TIMESTREAM_LABS_TABLE = "labs"

PATIENT_FEATURES_FG = "patient-features-online"

RAW_EVENTS_BUCKET = "my-deterioration-raw-events"
TRAINING_LABELS_BUCKET = "my-deterioration-training-labels"
MODEL_ARTIFACTS_BUCKET = "my-deterioration-model-artifacts"

DETERIORATION_SCORING_BUS = "deterioration-scoring"
RAPID_RESPONSE_TOPIC_ARN = (
    "arn:aws:sns:us-east-1:123456789012:rapid-response-notifications"
)
SAGEMAKER_ENDPOINT_NAME = "deterioration-model-prod"
BEDROCK_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

# --- Vital Sign Codes ---
# LOINC codes are the canonical reference. Real deployments load these from a
# managed reference set rather than hardcoding. Heart rate, respiratory rate,
# systolic and diastolic blood pressure, temperature, and oxygen saturation
# are the universally-collected vitals that anchor every deterioration model.
VITAL_LOINC = {
    "HR":   "8867-4",   # Heart rate
    "RR":   "9279-1",   # Respiratory rate
    "SBP":  "8480-6",   # Systolic blood pressure
    "DBP":  "8462-4",   # Diastolic blood pressure
    "TEMP": "8310-5",   # Body temperature
    "SPO2": "2708-6",   # Oxygen saturation in arterial blood
    "FIO2": "3150-0",   # Inhaled oxygen concentration
}
CORE_VITAL_KEYS = list(VITAL_LOINC.keys())

# Lab codes for the trajectory-feature subset. Production deployments include
# many more (BNP, troponin, procalcitonin, liver function panels, etc.); this
# subset is enough to demonstrate the pattern.
LAB_LOINC = {
    "WBC":        "6690-2",   # White blood cell count
    "HGB":        "718-7",    # Hemoglobin
    "PLT":        "777-3",    # Platelets
    "CREATININE": "2160-0",   # Creatinine in serum
    "LACTATE":    "32693-4",  # Lactate
    "GLUCOSE":    "2345-7",   # Glucose
    "BICARB":     "1963-8",   # Bicarbonate
}
CORE_LAB_KEYS = list(LAB_LOINC.keys())

# --- Window Sizes ---
# Trajectory features look at recent history; baseline features look at a
# longer window. The exact windows are clinical-governance decisions and
# vary by population.
LEAKAGE_BUFFER_MINUTES = 30        # observations must precede as_of by this margin
TRAJECTORY_WINDOW_HOURS = 24       # vitals trajectory features
LAB_TRAJECTORY_WINDOW_HOURS = 48   # lab trajectory features
BASELINE_WINDOW_HOURS = 72         # patient-specific baseline window
LAB_BASELINE_WINDOW_HOURS = 168    # one week for lab baselines
ACTIVE_MED_WINDOW_HOURS = 12       # medication considered "active"
MED_HISTORY_WINDOW_HOURS = 48      # how much med history to keep in state record
PERIODIC_TICK_MIN_INTERVAL_MINUTES = 30  # do not re-score patient more often

# --- Calibration and Tier Thresholds ---
# Tier thresholds are unit-stratified in production. A medical floor and a
# step-down unit have different baseline acuity, different rapid-response
# capacity, and different tolerable false-positive rates. The dictionary
# below shows the shape; production loads thresholds from a versioned
# DynamoDB table so the clinical governance committee can update them
# without a code deploy.
DEFAULT_TIER_THRESHOLDS = {
    "MEDICAL_FLOOR":  {"high": 0.60, "medium": 0.30, "low": 0.15},
    "SURGICAL_FLOOR": {"high": 0.55, "medium": 0.28, "low": 0.14},
    "STEP_DOWN":      {"high": 0.50, "medium": 0.25, "low": 0.12},
    "TELEMETRY":      {"high": 0.55, "medium": 0.28, "low": 0.14},
    "DEFAULT":        {"high": 0.60, "medium": 0.30, "low": 0.15},
}

DELTA_ALERT_THRESHOLD = 0.20      # delta in calibrated probability that triggers a delta alert
REPAGE_MIN_INTERVAL_MINUTES = 60  # do not re-page same patient inside this window
SUPPRESSION_AFTER_RRT_MINUTES = 240   # suppress alerts for 4h after rapid response activation
OUTCOME_LINKAGE_WINDOW_HOURS = 24     # outcome events link back to alerts within this window
```

A quick note on the thresholds block. The values above are defaults chosen to make the teaching example produce a sensible mix of high/medium/low alerts on a small synthetic dataset. A real deployment tunes them against a labeled backtest, then validates them prospectively in shadow mode before any alert routes to a clinician. The right cuts depend on the population's deterioration base rate, the rapid response team's capacity, and the alert-fatigue budget. These are dials, not physical constants, and the clinical governance committee owns them.

---

## Step 1: Normalize a Clinical Event

Vitals, labs, medications, and orders arrive from the EHR integration layer in heterogeneous formats (HL7 v2 ORU/RDE/ADT, FHIR R4 Observation/MedicationAdministration/Encounter, sometimes proprietary CSV drops). Before any feature computation runs, every event is converted into a canonical structure with consistent field names, canonical units, and a single timestamp convention. This step is boring and absolutely critical. If a heart rate arrives in some feeds as `bpm` and others as raw `count/min`, if temperatures arrive in Celsius from one ward and Fahrenheit from another, or if `observed_at` is sometimes UTC and sometimes local, every downstream feature is wrong at scale.

```python
def _to_decimal(value, precision="0.001"):
    """Convert numeric input to Decimal for DynamoDB and threshold storage.

    DynamoDB rejects Python float for numeric attributes because float
    arithmetic introduces rounding drift that makes threshold comparisons
    unreliable over time. Always pass dollar amounts, calibrated probabilities,
    z-scores, and vital values through Decimal on the way in and back out.
    """
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(precision))

def _redact_for_logs(canonical_event):
    """Produce a log-safe structural summary of a clinical event.

    Keeps event_id, event_type, observed_at, and unit_id. Drops patient
    identifier, value, and any free-text payload. Full event bodies live
    in the S3 raw-event lake under the canonical event prefix.
    """
    return {
        "event_id": canonical_event.get("event_id"),
        "event_type": canonical_event.get("event_type"),
        "observed_at": canonical_event.get("observed_at"),
        "unit_id": canonical_event.get("unit_id"),
        "source_system": canonical_event.get("source_system"),
    }

def _convert_temperature_to_celsius(value, units):
    """Vitals normalization helper. Temperatures travel in either Celsius or
    Fahrenheit depending on the source system; the canonical store is Celsius.
    Wrong-unit storage is the silent bug class that ruins trajectory features
    six months after deployment.
    """
    if units in ("Cel", "C", "celsius", "Celsius"):
        return float(value)
    if units in ("[degF]", "F", "fahrenheit", "Fahrenheit"):
        return (float(value) - 32.0) * 5.0 / 9.0
    raise ValueError(f"unrecognized temperature units: {units}")

def normalize_clinical_event(raw_event):
    """Convert a raw EHR-integration-layer event into the canonical shape used
    by every downstream step.

    In production, raw_event is the output of an HL7 v2 or FHIR parser
    invoked by a Lambda triggered from the Kinesis clinical-events stream.
    This example accepts a dict in the approximate shape that parser output
    takes so you can see the normalization logic without reading the HL7 v2
    or FHIR specs.
    """
    event_type = raw_event["event_type"]   # vital | lab | med_admin | order | adt | nursing_note

    canonical = {
        "event_id":       raw_event.get("event_id") or str(uuid.uuid4()),
        "patient_id":     raw_event["patient_id"],
        "encounter_id":   raw_event["encounter_id"],
        "event_type":     event_type,
        "observed_at":    raw_event["observed_at"],   # canonical UTC ISO8601
        "recorded_at":    raw_event.get("recorded_at"),
        "received_at":    datetime.now(timezone.utc).isoformat(),
        "unit_id":        raw_event.get("unit_id"),
        "source_system":  raw_event.get("source_system"),
    }

    if event_type == "vital":
        # Map source-specific codes to canonical vital keys via LOINC.
        loinc = raw_event["measurement_code"]
        canonical_key = next(
            (k for k, v in VITAL_LOINC.items() if v == loinc), None
        )
        if canonical_key is None:
            # Unknown vital code; route to quarantine queue. Production
            # logs a metric and a DLQ message rather than dropping silently.
            logger.warning("unknown vital LOINC", extra={"loinc": loinc})
            return None

        value = float(raw_event["value"])
        units = raw_event.get("units", "")
        if canonical_key == "TEMP":
            value = _convert_temperature_to_celsius(value, units)
        # Other vitals (HR, RR, SBP, DBP, SPO2, FIO2) are unit-stable in
        # practice but a real implementation still validates the units
        # field and rejects mismatches.

        canonical["payload"] = {
            "vital_key":         canonical_key,
            "loinc":              loinc,
            "value":              value,
            "method":             raw_event.get("method"),     # automated_cuff | arterial_line | manual
            "position":           raw_event.get("position"),    # sitting | supine | semi-fowler
            "quality_flags":      raw_event.get("quality_flags", []),
        }

    elif event_type == "lab":
        loinc = raw_event["test_code"]
        canonical_key = next(
            (k for k, v in LAB_LOINC.items() if v == loinc), None
        )
        # Labs are intentionally permissive: a lab not in our core feature
        # set is still archived to the raw-events lake but does not flow
        # into the feature engine.
        canonical["payload"] = {
            "lab_key":         canonical_key,
            "loinc":           loinc,
            "value":           float(raw_event["value"]),
            "units":           raw_event.get("units"),
            "reference_range": raw_event.get("reference_range"),
            "critical_flag":   bool(raw_event.get("critical_flag", False)),
        }

    elif event_type == "med_admin":
        # Therapeutic class is essential for the medication-context features
        # (has_active_antibiotic, has_active_vasopressor, etc.). In production
        # this comes from a medication knowledge base (First Databank, Lexicomp,
        # or RxNorm + custom mappings).
        canonical["payload"] = {
            "rxnorm":             raw_event.get("rxnorm"),
            "generic_name":       raw_event.get("generic_name"),
            "dose":               float(raw_event.get("dose", 0)),
            "dose_units":         raw_event.get("dose_units"),
            "route":              raw_event.get("route"),
            "therapeutic_class":  raw_event.get("therapeutic_class"),
        }

    elif event_type == "adt":
        canonical["payload"] = {
            "adt_type":           raw_event["adt_type"],   # admit | transfer | discharge
            "new_unit":           raw_event.get("new_unit"),
            "new_unit_type":      raw_event.get("new_unit_type"),
            "new_room":           raw_event.get("new_room"),
            "new_bed":            raw_event.get("new_bed"),
            "attending_provider": raw_event.get("attending_provider"),
        }

    elif event_type == "order":
        canonical["payload"] = {
            "order_type":         raw_event.get("order_type"),
            "order_code":         raw_event.get("order_code"),
            "ordering_provider":  raw_event.get("ordering_provider"),
        }

    elif event_type == "nursing_note":
        # Free-text nursing notes feed Comprehend Medical for entity
        # extraction in production. The canonical event keeps a hash of
        # the note text plus metadata; the full text lives in the encrypted
        # raw-events lake and is fetched only by the assessment-extraction
        # Lambda, never by routine application logs.
        canonical["payload"] = {
            "note_id":           raw_event.get("note_id"),
            "note_type":         raw_event.get("note_type"),
            "note_text":         raw_event.get("note_text"),     # PHI; do not log
            "author_role":       raw_event.get("author_role"),
        }

    else:
        logger.warning("unknown event type", extra={"event_type": event_type})
        return None

    # Persist to the raw event lake. In production this is the durable copy
    # of every clinical event for retrospective analysis and replay.
    s3_client.put_object(
        Bucket=RAW_EVENTS_BUCKET,
        Key=(
            f"event_type={event_type}/"
            f"year={canonical['observed_at'][:4]}/"
            f"month={canonical['observed_at'][5:7]}/"
            f"day={canonical['observed_at'][8:10]}/"
            f"{canonical['event_id']}.json"
        ),
        Body=json.dumps(canonical, default=str).encode("utf-8"),
        ServerSideEncryption="aws:kms",
    )

    # Append vital and lab events to Timestream so trajectory features
    # have a queryable time-series store. ADT, medication, and order events
    # update DynamoDB state directly.
    if event_type == "vital" and canonical["payload"]["vital_key"] is not None:
        timestream_write.write_records(
            DatabaseName=TIMESTREAM_DATABASE,
            TableName=TIMESTREAM_VITALS_TABLE,
            Records=[{
                "Dimensions": [
                    {"Name": "patient_id",   "Value": canonical["patient_id"]},
                    {"Name": "encounter_id", "Value": canonical["encounter_id"]},
                    {"Name": "vital_key",    "Value": canonical["payload"]["vital_key"]},
                ],
                "MeasureName":  canonical["payload"]["vital_key"],
                "MeasureValue": str(canonical["payload"]["value"]),
                "MeasureValueType": "DOUBLE",
                "Time":             str(int(datetime.fromisoformat(
                                        canonical["observed_at"].replace("Z", "+00:00")
                                    ).timestamp() * 1000)),
                "TimeUnit":         "MILLISECONDS",
            }],
        )
    elif event_type == "lab" and canonical["payload"].get("lab_key") is not None:
        timestream_write.write_records(
            DatabaseName=TIMESTREAM_DATABASE,
            TableName=TIMESTREAM_LABS_TABLE,
            Records=[{
                "Dimensions": [
                    {"Name": "patient_id",   "Value": canonical["patient_id"]},
                    {"Name": "encounter_id", "Value": canonical["encounter_id"]},
                    {"Name": "lab_key",      "Value": canonical["payload"]["lab_key"]},
                ],
                "MeasureName":  canonical["payload"]["lab_key"],
                "MeasureValue": str(canonical["payload"]["value"]),
                "MeasureValueType": "DOUBLE",
                "Time":             str(int(datetime.fromisoformat(
                                        canonical["observed_at"].replace("Z", "+00:00")
                                    ).timestamp() * 1000)),
                "TimeUnit":         "MILLISECONDS",
            }],
        )

    logger.info(
        "event normalized",
        extra={"event": "normalize_clinical_event", **_redact_for_logs(canonical)},
    )
    return canonical
```

In a real deployment, `normalize_clinical_event` runs as a Lambda triggered by Kinesis records from the EHR integration layer. The output is written to S3 (Parquet partitioned by date and event type for retrospective analytics) and to Timestream (for trajectory feature queries). A metric is emitted for every event type, source system, and day so data engineers see ingestion lag, parser failure rate, and silent schema drift early. Schema drift on the EHR side is the single most common cause of model degradation that nobody noticed for three weeks.

---

## Step 2: Update the Patient State Store

The patient state store carries the current snapshot of every admitted patient: latest vitals, recent labs, active medications, current location, and active orders. Updates from clinical events refresh the relevant fields. The state store is the substrate the feature engine reads from when a scoring request arrives, and its read latency directly bounds end-to-end alert latency.

```python
def _decimalize(obj):
    """Recursively convert floats to Decimals for DynamoDB write.

    DynamoDB rejects native Python float. Walk the structure and convert.
    Strings, ints, bools, and None pass through unchanged.
    """
    if isinstance(obj, float):
        return _to_decimal(obj)
    if isinstance(obj, dict):
        return {k: _decimalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimalize(v) for v in obj]
    return obj

def _undecimalize(obj):
    """Inverse of _decimalize for read-side conversion to Python-native types."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _undecimalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_undecimalize(v) for v in obj]
    return obj

def _filter_recent_meds(med_list, hours):
    """Keep only medications administered within the last `hours` window.

    State records do not need infinite medication history. The trajectory
    features that matter look back hours, not days. Trimming the state
    record keeps DynamoDB item size bounded.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return [m for m in med_list if m.get("administered_at", "") >= cutoff]

def _create_initial_patient_state(adt_event):
    """Initialize a patient-state record from an admit ADT event.

    Encounter-level metadata (admission diagnosis, attending, surgical
    status) is normally enriched by a separate encounter-resource pull;
    we stub the structure here to keep the example self-contained.
    """
    return {
        "patient_id":            adt_event["patient_id"],
        "encounter_id":          adt_event["encounter_id"],
        "is_active":             "true",   # GSI partition keys are strings
        "admission_time":        adt_event["observed_at"],
        "current_unit":          adt_event["payload"].get("new_unit"),
        "current_unit_type":     adt_event["payload"].get("new_unit_type", "DEFAULT"),
        "current_unit_at":       adt_event["observed_at"],
        "current_room":          adt_event["payload"].get("new_room"),
        "current_bed":           adt_event["payload"].get("new_bed"),
        "attending":             adt_event["payload"].get("attending_provider"),
        "current_vitals":        {},                 # vital_key -> {value, observed_at, recorded_at}
        "recent_labs":           {},                 # lab_key -> {value, observed_at, critical_flag}
        "recent_medications":    [],                 # list of recent administrations
        "recent_orders":         [],                 # list of recent orders for context
        "demographics":          {},                 # age_years, sex_band, bmi (loaded from encounter resource)
        "encounter_meta":        {},                 # admission_diagnosis_category, surgical_status
        "is_comfort_care":       False,
        "last_rrt_activation_at": None,
        "last_scored_at":        None,
        "discharge_at":          None,
        "updated_at":            datetime.now(timezone.utc).isoformat(),
    }

def update_patient_state(canonical_event):
    """Update the patient-state record for the encounter in the event.

    State updates are idempotent. The same event re-delivered (Kinesis
    at-least-once) produces the same state; vital observations are keyed
    by observed_at so duplicates collapse cleanly.
    """
    table = dynamodb.Table(PATIENT_STATE_TABLE)
    key = {
        "patient_id":   canonical_event["patient_id"],
        "encounter_id": canonical_event["encounter_id"],
    }
    response = table.get_item(Key=key)
    state = response.get("Item")

    if state is None:
        # No existing state record. Only an admit ADT can create one;
        # anything else for an unknown encounter is quarantined.
        if (canonical_event["event_type"] == "adt"
                and canonical_event["payload"]["adt_type"] == "admit"):
            state = _create_initial_patient_state(canonical_event)
        else:
            logger.warning(
                "event for unknown encounter; quarantining",
                extra={"event_id": canonical_event["event_id"]},
            )
            return None
    else:
        state = _undecimalize(state)

    event_type = canonical_event["event_type"]
    payload = canonical_event.get("payload", {})

    if event_type == "vital":
        vital_key = payload["vital_key"]
        # Only overwrite if the new observation is more recent than the
        # one currently in the snapshot. Out-of-order delivery is a real
        # thing (delayed charting, batch backfills); the snapshot must
        # always reflect the most-recent observation.
        existing = state["current_vitals"].get(vital_key)
        if existing is None or canonical_event["observed_at"] > existing.get("observed_at", ""):
            state["current_vitals"][vital_key] = {
                "value":        payload["value"],
                "observed_at":  canonical_event["observed_at"],
                "recorded_at":  canonical_event.get("recorded_at"),
            }

    elif event_type == "lab":
        lab_key = payload.get("lab_key")
        if lab_key:
            existing = state["recent_labs"].get(lab_key)
            if existing is None or canonical_event["observed_at"] > existing.get("observed_at", ""):
                state["recent_labs"][lab_key] = {
                    "value":           payload["value"],
                    "observed_at":     canonical_event["observed_at"],
                    "critical_flag":   payload.get("critical_flag", False),
                    "reference_range": payload.get("reference_range"),
                }

    elif event_type == "med_admin":
        state["recent_medications"].append({
            "rxnorm":             payload.get("rxnorm"),
            "therapeutic_class":  payload.get("therapeutic_class"),
            "dose":               payload.get("dose"),
            "dose_units":         payload.get("dose_units"),
            "route":              payload.get("route"),
            "administered_at":    canonical_event["observed_at"],
        })
        state["recent_medications"] = _filter_recent_meds(
            state["recent_medications"], MED_HISTORY_WINDOW_HOURS
        )

    elif event_type == "adt":
        adt_type = payload["adt_type"]
        if adt_type in ("admit", "transfer"):
            state["current_unit"]      = payload.get("new_unit") or state["current_unit"]
            state["current_unit_type"] = payload.get("new_unit_type") or state.get("current_unit_type", "DEFAULT")
            state["current_unit_at"]   = canonical_event["observed_at"]
            state["current_room"]      = payload.get("new_room") or state.get("current_room")
            state["current_bed"]       = payload.get("new_bed") or state.get("current_bed")
            state["attending"]         = payload.get("attending_provider") or state.get("attending")
        elif adt_type == "discharge":
            state["discharge_at"] = canonical_event["observed_at"]
            state["is_active"]    = "false"

    elif event_type == "order":
        state["recent_orders"].append({
            "order_type":      payload.get("order_type"),
            "order_code":      payload.get("order_code"),
            "ordered_at":      canonical_event["observed_at"],
        })
        # Keep only orders within a relevant lookback window (concerning
        # orders include lactate, blood culture, oxygen titration; these
        # signals decay in informativeness after a day or so).
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        state["recent_orders"] = [
            o for o in state["recent_orders"] if o.get("ordered_at", "") >= cutoff
        ]

    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    table.put_item(Item=_decimalize(state))
    return state
```

Note the out-of-order delivery handling. Kinesis records arrive in shard order, but at-least-once delivery plus retries means a lagged delivery can land an older observation after a newer one. The snapshot logic only overwrites if the new observation has a later `observed_at`, so the patient-state record always reflects the most-recent measurement for each vital. That guard is the difference between "vitals jumped, then jumped back, then jumped again" feature artifacts and a clean trajectory.

---

## Step 3: Trigger Scoring on Event or Schedule

Two paths produce scoring requests. Event-driven scoring fires from DynamoDB Streams when the patient-state record changes in a clinically relevant way (a new vital, a new lab, a unit transfer, a new concerning order). Periodic scoring fires every 30-60 minutes from a scheduled rule to capture elapsed-time effects (a heart rate trend continues when no new vital is charted; a baseline-comparison feature can shift just because time passed). Both paths converge on the same scoring orchestrator.

```python
def should_rescore_on_state_change(new_state, old_state):
    """Decide whether a state change is significant enough to re-score.

    Significant changes: any new vital, any new lab, a unit transfer, a
    new concerning order, a comfort-care or DNR order, an RRT activation.
    Trivial changes (an updated_at touch with no field change) do not
    trigger scoring; the periodic tick will catch them at next interval.
    """
    if old_state is None:
        return True

    # Unit type change is a significant context shift; always re-score.
    if new_state.get("current_unit_type") != old_state.get("current_unit_type"):
        return True

    # Comfort-care toggle changes the suppression decision; re-score so
    # the alert path can short-circuit on the next event.
    if new_state.get("is_comfort_care") != old_state.get("is_comfort_care"):
        return True

    # New vital detected: any vital_key has a more recent observed_at than
    # the old snapshot.
    new_vitals = new_state.get("current_vitals") or {}
    old_vitals = old_state.get("current_vitals") or {}
    for k, v in new_vitals.items():
        if v.get("observed_at") != (old_vitals.get(k) or {}).get("observed_at"):
            return True

    # New lab detected with the same logic.
    new_labs = new_state.get("recent_labs") or {}
    old_labs = old_state.get("recent_labs") or {}
    for k, v in new_labs.items():
        if v.get("observed_at") != (old_labs.get(k) or {}).get("observed_at"):
            return True

    # New medication administration.
    if len(new_state.get("recent_medications", [])) > len(old_state.get("recent_medications", [])):
        return True

    return False

def on_state_change(stream_record, scoring_handler):
    """DynamoDB Streams handler for event-driven scoring triggers.

    Production wires this as a Lambda triggered from the patient-state
    DynamoDB Stream. Pull the new and old images, decide whether to
    score, and call into the scoring orchestrator.
    """
    new_image = _undecimalize(stream_record.get("NewImage", {}))
    old_image = _undecimalize(stream_record.get("OldImage", {}))

    if not new_image:
        return

    if new_image.get("is_active") != "true":
        # Discharged patients do not need scoring. Production also has a
        # short post-discharge window for late-arriving outcome events,
        # but that is not the scoring path.
        return

    if should_rescore_on_state_change(new_image, old_image):
        scoring_handler(
            patient_id=new_image["patient_id"],
            encounter_id=new_image["encounter_id"],
            trigger="event_driven",
        )

def on_periodic_tick(scoring_handler):
    """Scheduled scoring trigger.

    Production wires this as an EventBridge scheduled rule (every 30-60
    minutes) that invokes a Lambda which queries the active-patients GSI
    and dispatches scoring requests for any patient not scored recently.
    """
    table = dynamodb.Table(PATIENT_STATE_TABLE)
    response = table.query(
        IndexName="is_active-index",
        KeyConditionExpression=Key("is_active").eq("true"),
    )

    cutoff = (datetime.now(timezone.utc)
              - timedelta(minutes=PERIODIC_TICK_MIN_INTERVAL_MINUTES)).isoformat()

    for item in response.get("Items", []):
        item = _undecimalize(item)
        last_scored = item.get("last_scored_at")
        if last_scored is None or last_scored < cutoff:
            scoring_handler(
                patient_id=item["patient_id"],
                encounter_id=item["encounter_id"],
                trigger="periodic",
            )

def invoke_scoring_orchestrator(patient_id, encounter_id, trigger):
    """Publish a scoring request to EventBridge.

    The scoring orchestrator subscribes to this and runs the feature
    engine plus the scoring service. Decoupling via EventBridge means the
    state-change Lambda and the periodic-tick Lambda do not need to know
    where the scoring service lives or how it is implemented; they just
    publish a ScoreRequest event.
    """
    eventbridge.put_events(Entries=[{
        "Source":      "deterioration.scoring-orchestrator",
        "DetailType":  "ScoreRequest",
        "Detail": json.dumps({
            "patient_id":   patient_id,
            "encounter_id": encounter_id,
            "trigger":      trigger,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }),
        "EventBusName": DETERIORATION_SCORING_BUS,
    }])
```

The split between event-driven and periodic scoring matters operationally. Event-driven scoring keeps latency low for changing patients. Periodic scoring catches the steady-state-but-drifting pattern (a slowly-rising heart rate that stays above a feature threshold but does not generate new events). A pipeline that does only event-driven scoring will miss patients whose deterioration is gradual; a pipeline that does only periodic scoring will be slow to catch acute changes. Both paths exist in every production deterioration system.

---

## Step 4: Compute the Feature Vector

The feature engine reads patient state and time-series history, computes the model's input vector, and writes it to the Feature Store for both online use (this scoring) and offline reproduction (retraining, governance review of past predictions). Feature engineering is where most of the actual modeling work lives, and where the deterioration-specific clinical insight gets encoded.

```python
def _compute_slope(timestamped_values):
    """Linear regression slope of value over time, in units per hour.

    Captures whether vitals are trending up or down. A heart rate that
    has climbed from 75 to 95 over 4 hours produces slope ~5 bpm/hr,
    which is much more informative than the current value alone.
    """
    if len(timestamped_values) < 2:
        return None
    t = np.array([v["t_hours"] for v in timestamped_values], dtype=float)
    y = np.array([v["value"]   for v in timestamped_values], dtype=float)
    if t.std() < 1e-6:
        return 0.0
    # Simple closed-form OLS slope.
    return float(np.cov(t, y, ddof=0)[0, 1] / t.var())

def _query_vital_history(patient_id, encounter_id, vital_key, hours_back, as_of):
    """Query Timestream for a vital's history within the lookback window."""
    as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    start_dt = as_of_dt - timedelta(hours=hours_back)
    query = f'''
        SELECT time, measure_value::double AS value
        FROM "{TIMESTREAM_DATABASE}"."{TIMESTREAM_VITALS_TABLE}"
        WHERE patient_id = '{patient_id}'
          AND encounter_id = '{encounter_id}'
          AND vital_key = '{vital_key}'
          AND time BETWEEN from_iso8601_timestamp('{start_dt.isoformat()}')
                       AND from_iso8601_timestamp('{as_of_dt.isoformat()}')
        ORDER BY time
    '''
    # Production handles pagination; teaching example does not.
    response = timestream_query.query(QueryString=query)

    series = []
    for row in response.get("Rows", []):
        t_str = row["Data"][0]["ScalarValue"]
        v_str = row["Data"][1]["ScalarValue"]
        observed_dt = datetime.fromisoformat(t_str.replace(" ", "T") + "+00:00")
        series.append({
            "observed_at": observed_dt.isoformat(),
            "value":       float(v_str),
            "t_hours":     (observed_dt - as_of_dt).total_seconds() / 3600.0,
        })
    return series

def compute_features(patient_id, encounter_id, as_of):
    """Compute the model's input feature vector.

    Reads from DynamoDB patient-state for current snapshots and Timestream
    for trajectory history. Persists the result to Feature Store so the
    same feature vector is reproducible for governance review and so the
    online and offline paths stay consistent.
    """
    table = dynamodb.Table(PATIENT_STATE_TABLE)
    state = _undecimalize(table.get_item(
        Key={"patient_id": patient_id, "encounter_id": encounter_id}
    ).get("Item", {}))
    if not state:
        raise ValueError(f"no patient state for {patient_id}/{encounter_id}")

    features = {}
    as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))

    # --- Current vitals features ---
    for vital_key in CORE_VITAL_KEYS:
        latest = state.get("current_vitals", {}).get(vital_key)
        if latest:
            features[f"vital_{vital_key}_current"] = latest["value"]
            obs_dt = datetime.fromisoformat(latest["observed_at"].replace("Z", "+00:00"))
            features[f"vital_{vital_key}_age_minutes"] = (as_of_dt - obs_dt).total_seconds() / 60.0
        else:
            features[f"vital_{vital_key}_current"] = None
            features[f"vital_{vital_key}_age_minutes"] = None

    # --- Vitals trajectory features ---
    # Slope, max, min, std over windows. Rolling windows of 1, 4, and 12
    # hours capture acute, subacute, and shift-scale changes respectively.
    for vital_key in CORE_VITAL_KEYS:
        full_history = _query_vital_history(
            patient_id, encounter_id, vital_key, TRAJECTORY_WINDOW_HOURS, as_of
        )
        for window_hours in [1, 4, 12]:
            window_cutoff = -float(window_hours)
            window_values = [v for v in full_history if v["t_hours"] >= window_cutoff]
            if window_values:
                values_only = [v["value"] for v in window_values]
                features[f"vital_{vital_key}_slope_{window_hours}h"] = _compute_slope(window_values)
                features[f"vital_{vital_key}_max_{window_hours}h"]   = max(values_only)
                features[f"vital_{vital_key}_min_{window_hours}h"]   = min(values_only)
                features[f"vital_{vital_key}_std_{window_hours}h"]   = (
                    float(np.std(values_only)) if len(values_only) > 1 else 0.0
                )
                features[f"vital_{vital_key}_count_{window_hours}h"] = len(window_values)
            else:
                for stat in ["slope", "max", "min", "std", "count"]:
                    features[f"vital_{vital_key}_{stat}_{window_hours}h"] = None

    # --- Patient-specific baselines ---
    # Median value over the long lookback window. The single biggest
    # accuracy improvement over population thresholds is replacing them
    # with patient-specific deltas. A heart rate of 95 in a patient whose
    # baseline is 75 carries different information than the same number
    # in a patient whose baseline is 90.
    for vital_key in CORE_VITAL_KEYS:
        baseline_history = _query_vital_history(
            patient_id, encounter_id, vital_key, BASELINE_WINDOW_HOURS, as_of
        )
        if len(baseline_history) >= 5:   # need enough points for a stable baseline
            baseline = float(np.median([v["value"] for v in baseline_history]))
            features[f"vital_{vital_key}_baseline"] = baseline
            current = features.get(f"vital_{vital_key}_current")
            features[f"vital_{vital_key}_delta_from_baseline"] = (
                (current - baseline) if current is not None else None
            )
        else:
            features[f"vital_{vital_key}_baseline"] = None
            features[f"vital_{vital_key}_delta_from_baseline"] = None

    # --- Composite vitals features ---
    # Hand-crafted clinical composites. Shock index, pulse pressure, MAP,
    # ROX index. These encode clinical reasoning that pure ML sometimes
    # has to learn from scratch and sometimes never quite does.
    hr   = features.get("vital_HR_current")
    sbp  = features.get("vital_SBP_current")
    dbp  = features.get("vital_DBP_current")
    rr   = features.get("vital_RR_current")
    spo2 = features.get("vital_SPO2_current")
    fio2 = features.get("vital_FIO2_current")
    if hr is not None and sbp is not None and sbp > 0:
        features["composite_shock_index"] = hr / sbp
    else:
        features["composite_shock_index"] = None
    if sbp is not None and dbp is not None:
        features["composite_pulse_pressure"] = sbp - dbp
        features["composite_map"]            = (sbp + 2 * dbp) / 3
    else:
        features["composite_pulse_pressure"] = None
        features["composite_map"]            = None
    if (spo2 is not None and fio2 is not None and rr is not None
            and fio2 > 0 and rr > 0):
        features["composite_rox_index"] = (spo2 / fio2) / rr
    else:
        features["composite_rox_index"] = None

    # --- Lab features ---
    # Current value plus age plus 24h slope. Lab trajectories matter
    # (rising creatinine over 48h, falling hemoglobin over the same
    # window) more than the absolute current value for many phenotypes.
    for lab_key in CORE_LAB_KEYS:
        latest = state.get("recent_labs", {}).get(lab_key)
        if latest:
            features[f"lab_{lab_key}_current"] = latest["value"]
            obs_dt = datetime.fromisoformat(latest["observed_at"].replace("Z", "+00:00"))
            features[f"lab_{lab_key}_age_hours"] = (as_of_dt - obs_dt).total_seconds() / 3600.0
        else:
            features[f"lab_{lab_key}_current"] = None
            features[f"lab_{lab_key}_age_hours"] = None

    # --- Medication context features ---
    # Recent medications from the state record. Active classes are useful
    # both as direct features (a vasopressor was just started; this is a
    # marker of clinical concern) and as confounders (a beta-blocker
    # masks tachycardia; an opioid explains a respiratory rate change).
    cutoff_iso = (as_of_dt - timedelta(hours=ACTIVE_MED_WINDOW_HOURS)).isoformat()
    active_meds = [
        m for m in state.get("recent_medications", [])
        if m.get("administered_at", "") >= cutoff_iso
    ]
    active_classes = {m.get("therapeutic_class") for m in active_meds if m.get("therapeutic_class")}
    for cls in ["antibiotic", "vasopressor", "opioid", "sedative",
                "betablocker", "insulin", "anticoagulant"]:
        features[f"has_active_{cls}"] = cls in active_classes

    # --- Patient and unit context features ---
    demo = state.get("demographics") or {}
    enc  = state.get("encounter_meta") or {}
    features["age_years"]    = demo.get("age_years")
    features["sex_band"]      = demo.get("sex_band")
    features["bmi"]           = demo.get("bmi")
    features["admission_diagnosis_category"] = enc.get("admission_diagnosis_category")
    features["surgical_status"] = enc.get("surgical_status", "none")

    admission_at = state.get("admission_time")
    unit_at      = state.get("current_unit_at")
    if admission_at:
        admission_dt = datetime.fromisoformat(admission_at.replace("Z", "+00:00"))
        features["los_hours"] = (as_of_dt - admission_dt).total_seconds() / 3600.0
    else:
        features["los_hours"] = None
    if unit_at:
        unit_dt = datetime.fromisoformat(unit_at.replace("Z", "+00:00"))
        features["hours_on_current_unit"] = (as_of_dt - unit_dt).total_seconds() / 3600.0
    else:
        features["hours_on_current_unit"] = None
    features["unit_type"]   = state.get("current_unit_type", "DEFAULT")
    features["hour_of_day"] = as_of_dt.hour
    features["day_of_week"] = as_of_dt.weekday()

    # --- Order context features ---
    # Recent concerning orders (lactate, blood culture, oxygen titration)
    # often precede formal deterioration recognition by hours; the team
    # acts on suspicion before they call rapid response. The "the team
    # has just ordered a lactate" feature is sometimes one of the highest-
    # importance features in production models.
    recent_orders = state.get("recent_orders") or []
    six_hour_cutoff = (as_of_dt - timedelta(hours=6)).isoformat()
    four_hour_cutoff = (as_of_dt - timedelta(hours=4)).isoformat()
    features["recent_lactate_order"] = any(
        o.get("order_type") == "lab"
        and "LACTATE" in (o.get("order_code") or "").upper()
        and o.get("ordered_at", "") >= four_hour_cutoff
        for o in recent_orders
    )
    features["recent_blood_culture_order"] = any(
        o.get("order_type") == "lab"
        and "BLOOD_CULTURE" in (o.get("order_code") or "").upper()
        and o.get("ordered_at", "") >= six_hour_cutoff
        for o in recent_orders
    )

    # Persist to Feature Store. This is what makes online and offline
    # consistent: the exact feature vector that scored a patient is the
    # one available for retraining and for governance-review reproduction.
    feature_record = [
        {"FeatureName": "patient_encounter_id",
         "ValueAsString": f"{patient_id}:{encounter_id}"},
        {"FeatureName": "event_time", "ValueAsString": as_of},
    ]
    for k, v in features.items():
        if v is None:
            continue
        if isinstance(v, bool):
            feature_record.append({"FeatureName": k, "ValueAsString": str(v).lower()})
        else:
            feature_record.append({"FeatureName": k, "ValueAsString": str(v)})

    try:
        featurestore_runtime.put_record(
            FeatureGroupName=PATIENT_FEATURES_FG,
            Record=feature_record,
        )
    except Exception as e:
        # In production, a feature-store write failure is a metric and a
        # DLQ. The teaching example logs and continues so the demo runs
        # without a real feature group provisioned.
        logger.warning("feature store write failed", extra={"error": str(e)})

    return features
```

A model with 80-150 features is typical. The list above (current vitals, trajectories at three time scales, patient-specific baselines, composites, lab features, medication context, patient/unit/time context, order context) lands roughly in that range. More features past this point produce diminishing returns and operational pain: drift detection becomes harder, feature pipeline maintenance becomes harder, missingness patterns multiply, and model-monitoring dashboards turn into a wall of charts that nobody reads.

---

## Step 5: Score the Feature Vector and Apply Calibration

The scoring service invokes the SageMaker endpoint with the feature vector, then a calibration layer maps the raw model output to a calibrated probability and a risk tier. Calibration matters as much as discrimination here. A clinician who sees "deterioration risk: 23%" needs to know that across patients with that score, roughly 23% really do deteriorate. A miscalibrated score makes operational threshold tuning impossible.

```python
def _feature_vector_to_array(features, feature_order):
    """Convert the dict-of-features into a numpy row vector for the model.

    Production uses a frozen feature_order pinned to the deployed model
    version. Mismatched feature order against the trained model is the
    silent bug class that produces nonsense scores at scale.
    """
    row = []
    for name in feature_order:
        v = features.get(name)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            row.append(0.0)   # imputation; LightGBM handles missing natively
        elif isinstance(v, bool):
            row.append(1.0 if v else 0.0)
        elif isinstance(v, (int, float)):
            row.append(float(v))
        else:
            row.append(0.0)   # string features encoded upstream in production
    return np.array([row], dtype=float)

def score_via_sagemaker_endpoint(features, feature_order):
    """Invoke the deployed SageMaker endpoint with a feature vector.

    Production uses a real-time SageMaker endpoint (multi-AZ for clinical
    reliability) hosting a gradient-boosted-trees model. The endpoint
    accepts CSV or JSON depending on the inference container; this
    example uses CSV which is the default for the SKLearn container.
    """
    payload = ",".join(str(v) for v in _feature_vector_to_array(features, feature_order)[0])
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT_NAME,
        ContentType="text/csv",
        Body=payload,
    )
    body = response["Body"].read().decode("utf-8").strip()
    # The CSV inference output is typically the predicted probability.
    raw_score = float(body.split(",")[0])
    return raw_score

def score_via_local_model(features, feature_order, local_model):
    """Score against a tiny in-process model, for the teaching example.

    Same shape of return as the SageMaker version. Production replaces
    this with score_via_sagemaker_endpoint and the rest of the pipeline
    is unchanged.
    """
    X = _feature_vector_to_array(features, feature_order)
    if hasattr(local_model, "predict_proba"):
        return float(local_model.predict_proba(X)[0, 1])
    # Isolation Forest path: convert decision_function (higher = more
    # normal) into a 0-1 risk-like score.
    raw_anomaly = -float(local_model.decision_function(X)[0])
    return float(1.0 / (1.0 + math.exp(-raw_anomaly)))

def apply_calibration(raw_score, calibrator):
    """Apply post-hoc calibration to the raw model output.

    Production uses isotonic regression or Platt scaling fit on a held-out
    validation set, then frozen and versioned alongside the model. The
    calibrator object is loaded from S3 at scoring-service startup and
    cached.
    """
    if calibrator is None:
        return raw_score
    return float(calibrator.predict(np.array([raw_score]))[0])

def map_to_tier(calibrated_probability, unit_type):
    """Map a calibrated probability to a tier using unit-stratified thresholds.

    Different unit types tolerate different false-positive rates because
    the rapid response capacity and baseline acuity differ.
    """
    thresholds = DEFAULT_TIER_THRESHOLDS.get(unit_type, DEFAULT_TIER_THRESHOLDS["DEFAULT"])
    if calibrated_probability >= thresholds["high"]:
        return "high"
    if calibrated_probability >= thresholds["medium"]:
        return "medium"
    if calibrated_probability >= thresholds["low"]:
        return "low"
    return "below_threshold"

def score_patient(patient_id, encounter_id, features, feature_order,
                  trigger, model, calibrator):
    """Run the scoring step end-to-end for a single patient.

    Computes the raw score, applies calibration, maps to a tier, persists
    a scoring history record, and publishes a ScoreProduced event for
    downstream consumers (the explanation builder and the alert router).
    """
    # The teaching example accepts either a deployed-endpoint stub or a
    # local model object. Production uses the endpoint version exclusively.
    if model == "ENDPOINT":
        raw_score = score_via_sagemaker_endpoint(features, feature_order)
    else:
        raw_score = score_via_local_model(features, feature_order, model)

    calibrated = apply_calibration(raw_score, calibrator)
    unit_type = features.get("unit_type") or "DEFAULT"
    tier = map_to_tier(calibrated, unit_type)

    score_record = {
        "patient_id":              patient_id,
        "encounter_id":            encounter_id,
        "score_id":                str(uuid.uuid4()),
        "scored_at":               datetime.now(timezone.utc).isoformat(),
        "trigger":                 trigger,
        "raw_score":               _to_decimal(raw_score),
        "calibrated_probability":  _to_decimal(calibrated),
        "tier":                    tier,
        "unit_type":               unit_type,
        "model_version":           "deterioration-v3.2",
        "calibration_version":     "calib-v3.2-2026-04",
        "feature_count":           sum(1 for v in features.values() if v is not None),
    }

    table = dynamodb.Table(SCORING_HISTORY_TABLE)
    table.put_item(Item=_decimalize(score_record))

    # Update last_scored_at on the patient state so the periodic-tick
    # query knows not to re-score this patient inside the min interval.
    state_table = dynamodb.Table(PATIENT_STATE_TABLE)
    state_table.update_item(
        Key={"patient_id": patient_id, "encounter_id": encounter_id},
        UpdateExpression="SET last_scored_at = :ts",
        ExpressionAttributeValues={":ts": score_record["scored_at"]},
        ConditionExpression="attribute_exists(patient_id)",
    )

    # Publish for alert routing fan-out. The explanation builder also
    # subscribes to this so the explanation runs in parallel with routing
    # rather than on the critical path.
    eventbridge.put_events(Entries=[{
        "Source":      "deterioration.scoring-service",
        "DetailType":  "ScoreProduced",
        "Detail": json.dumps({
            "patient_id":             patient_id,
            "encounter_id":           encounter_id,
            "score_id":               score_record["score_id"],
            "scored_at":              score_record["scored_at"],
            "raw_score":              raw_score,
            "calibrated_probability": calibrated,
            "tier":                   tier,
            "unit_type":              unit_type,
            "trigger":                trigger,
        }, default=str),
        "EventBusName": DETERIORATION_SCORING_BUS,
    }])

    _emit_metric("ScoresProduced", 1)
    _emit_metric(f"Tier_{tier}", 1)
    return score_record

def _emit_metric(metric_name, value, unit="Count"):
    """Emit a CloudWatch metric for operational monitoring."""
    try:
        cloudwatch.put_metric_data(
            Namespace="Deterioration/Scoring",
            MetricData=[{
                "MetricName": metric_name,
                "Value":      float(value),
                "Unit":       unit,
                "Timestamp":  datetime.now(timezone.utc),
            }],
        )
    except Exception as e:
        logger.warning("metric emit failed", extra={"metric": metric_name, "error": str(e)})
```

The `last_scored_at` update with a `ConditionExpression` is a small but important safety. If a patient was discharged between the scoring request and the state write, the `attribute_exists(patient_id)` clause fails the update and the scoring path does not silently re-create state for a discharged patient. Without this guard, race conditions between discharge events and in-flight scoring requests can produce zombie patient-state records that the periodic tick keeps scoring forever.

---

## Step 6: Build the Explanation

Per-prediction explanations combine technical drivers (SHAP values from the model) with a clinician-readable narrative generated by an LLM. The narrative is decision support, not a decision, and the structured drivers are always present alongside the narrative so the clinician can trace the score back to specific features.

```python
def compute_top_drivers(features, feature_order, model, top_n=7):
    """Compute approximate top contributing features.

    Production uses SageMaker Clarify (or SHAP directly against the model)
    to get per-prediction Shapley values. This teaching version uses a
    crude proxy: for tree-based or linear models that expose
    `feature_importances_` or `coef_`, multiply the importance/coefficient
    by the standardized feature value to approximate the contribution.
    Real SHAP gives much better local explanations; this is a placeholder
    so the pipeline runs end-to-end.
    """
    X = _feature_vector_to_array(features, feature_order)[0]

    importances = None
    if hasattr(model, "feature_importances_"):
        importances = np.asarray(model.feature_importances_)
    elif hasattr(model, "coef_"):
        importances = np.asarray(model.coef_).flatten()

    contributions = []
    if importances is not None and len(importances) == len(X):
        # Approximate contribution = standardized feature value * importance.
        # The standardization is rough; SHAP is the production answer.
        x_std = (X - np.mean(X)) / (np.std(X) + 1e-6)
        contribs = importances * x_std
        for i, name in enumerate(feature_order):
            contributions.append({
                "feature":      name,
                "value":        float(X[i]),
                "contribution": float(contribs[i]),
            })

    contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)
    return contributions[:top_n]

# Human-readable feature descriptions for the explanation layer. In
# production this is loaded from a versioned reference table maintained
# alongside the feature catalog so a feature rename does not silently
# produce uninformative explanations.
FEATURE_DESCRIPTIONS = {
    "vital_HR_current":             "current heart rate",
    "vital_HR_slope_4h":            "4-hour heart rate slope",
    "vital_HR_delta_from_baseline": "heart rate delta from patient's baseline",
    "vital_RR_current":             "current respiratory rate",
    "vital_RR_slope_4h":            "4-hour respiratory rate slope",
    "vital_SBP_current":            "current systolic blood pressure",
    "vital_SBP_slope_4h":           "4-hour systolic blood pressure slope",
    "vital_TEMP_current":           "current temperature",
    "vital_TEMP_delta_from_baseline":"temperature delta from baseline",
    "vital_SPO2_current":           "current oxygen saturation",
    "lab_LACTATE_current":          "current lactate",
    "lab_WBC_current":              "current white blood cell count",
    "lab_CREATININE_current":       "current creatinine",
    "composite_shock_index":        "shock index (HR/SBP)",
    "composite_rox_index":          "ROX index (SpO2/FiO2/RR)",
    "recent_lactate_order":         "lactate ordered recently",
    "recent_blood_culture_order":   "blood cultures ordered recently",
    "has_active_antibiotic":        "patient on active antibiotic",
    "has_active_vasopressor":       "patient on active vasopressor",
}

def humanize_driver(driver):
    """Build a clinical-meaning string for a single driver."""
    description = FEATURE_DESCRIPTIONS.get(driver["feature"], driver["feature"])
    value = driver["value"]
    if isinstance(value, float):
        value_str = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        value_str = str(value)
    return f"{description} ({value_str})"

def build_explanation(score_record, features, feature_order, model):
    """Assemble structured drivers plus a Bedrock-generated narrative."""
    top_positive = compute_top_drivers(features, feature_order, model, top_n=7)
    top_drivers_pos = [d for d in top_positive if d["contribution"] > 0][:5]
    top_drivers_neg = [d for d in top_positive if d["contribution"] < 0][:3]

    # Get the previous score to compute the delta. Useful for the narrative
    # ("score has increased substantially over the last 4 hours").
    history_table = dynamodb.Table(SCORING_HISTORY_TABLE)
    history = history_table.query(
        KeyConditionExpression=Key("patient_id").eq(score_record["patient_id"]),
        ScanIndexForward=False,    # most recent first
        Limit=2,
    )
    prior_score = None
    items = history.get("Items", [])
    if len(items) >= 2:
        # items[0] is the current score we just wrote; items[1] is prior.
        prior_score = float(items[1].get("calibrated_probability", 0))

    structured = {
        "top_risk_drivers": [
            {
                "feature":          d["feature"],
                "value":            d["value"],
                "contribution":     round(d["contribution"], 4),
                "clinical_meaning": humanize_driver(d),
            }
            for d in top_drivers_pos
        ],
        "top_protective_factors": [
            {
                "feature":          d["feature"],
                "value":            d["value"],
                "contribution":     round(d["contribution"], 4),
                "clinical_meaning": humanize_driver(d),
            }
            for d in top_drivers_neg
        ],
        "score_change_from_last": (
            round(float(score_record["calibrated_probability"]) - prior_score, 4)
            if prior_score is not None else None
        ),
    }

    # Bedrock narrative. The prompt is constrained: cite features, suggest
    # evaluation steps, never recommend specific treatments. The LLM is
    # producing decision support, not decisions.
    narrative = invoke_bedrock_narrative(score_record, structured, features)

    explanation = {
        "score_id":              score_record["score_id"],
        "structured":            structured,
        "narrative":             narrative,
        "generated_at":          datetime.now(timezone.utc).isoformat(),
        "explanation_version":   "shap_proxy_plus_bedrock_v1",
    }
    return explanation

def invoke_bedrock_narrative(score_record, structured, features):
    """Generate a clinician-readable narrative via Bedrock.

    Constrained prompt: cite drivers, suggest evaluation steps, never
    recommend specific treatments. Always with human review; the LLM is
    producing decision support, not decisions. Confirm the chosen Bedrock
    model is HIPAA-eligible under your AWS BAA before deploying.
    """
    drivers_text = "\n".join(
        f"- {d['clinical_meaning']} (contribution: {d['contribution']:+.3f})"
        for d in structured["top_risk_drivers"]
    )
    protective_text = "\n".join(
        f"- {d['clinical_meaning']}"
        for d in structured["top_protective_factors"]
    ) or "(none)"

    delta_text = (
        f"Score change from prior: {structured['score_change_from_last']:+.3f}"
        if structured["score_change_from_last"] is not None
        else "No prior score available."
    )

    prompt = (
        "You are summarizing a patient deterioration risk score for a hospital "
        "clinician. You are not making a clinical judgment and you are not "
        "recommending specific treatments. You are translating the model's "
        "feature drivers into a clinician-readable narrative that suggests "
        "evaluation steps. Cite the drivers. Note any phenotype pattern that "
        "is consistent with the drivers (sepsis, respiratory failure, "
        "circulatory compromise). End with the phrase 'This is decision "
        "support; clinical judgment governs.'\n\n"
        f"Risk tier: {score_record['tier']}\n"
        f"Calibrated probability: {float(score_record['calibrated_probability']):.2f}\n"
        f"{delta_text}\n"
        f"Unit type: {features.get('unit_type', 'unknown')}\n"
        f"Surgical status: {features.get('surgical_status', 'none')}\n\n"
        f"Top risk drivers:\n{drivers_text}\n\n"
        f"Top protective factors:\n{protective_text}\n\n"
        "Produce 2-4 sentences of plain narrative. No bullet points. No "
        "specific drug or dose recommendations."
    )

    try:
        response = bedrock_runtime.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens":        500,
                "temperature":       0.0,
                "messages":          [{"role": "user", "content": prompt}],
            }),
        )
        body = json.loads(response["body"].read())
        return body["content"][0]["text"].strip()
    except Exception as e:
        # Bedrock failure does not block alert routing. Log, emit a metric,
        # fall back to a structured-only explanation.
        logger.warning("bedrock invocation failed", extra={"error": str(e)})
        _emit_metric("BedrockNarrativeFailed", 1)
        return (
            f"Risk tier {score_record['tier']} with calibrated probability "
            f"{float(score_record['calibrated_probability']):.2f}. "
            "Top drivers: " + ", ".join(
                d["clinical_meaning"] for d in structured["top_risk_drivers"][:3]
            ) + ". This is decision support; clinical judgment governs."
        )
```

Two design points worth highlighting. First, the explanation runs in parallel with alert routing rather than on its critical path. If Bedrock is throttled or unavailable, the alert still routes with the structured explanation only; the narrative is enriched after the fact. Second, the SHAP-proxy fallback is intentionally crude. Production wires SageMaker Clarify (or a SHAP library against the deployed model) so the contribution numbers reflect actual local Shapley values. Without real SHAP, the explanation degrades from "useful" to "directionally correct," and clinician trust drops accordingly.

---

## Step 7: Route Alerts Based on Tier and Suppression Rules

The alert router is the product. Receiving scores for every patient is one thing; getting the right alert to the right human at the right time without burying them in noise is the actual problem. Tier-based routing decides where the alert goes; suppression rules silence alerts that the model would otherwise generate but that are not operationally actionable; delta detection catches the score-just-jumped pattern that matters more than the steady-state-high pattern.

```python
def check_suppression_rules(patient_id, encounter_id):
    """Apply suppression rules. A suppressed alert is logged, not delivered.

    Suppression categories:
    - Patient already in ICU: receiving deterioration alerts on an ICU
      patient is operationally meaningless; the ICU team has eyes on them.
    - Active comfort care: care goals are not deterioration prevention.
    - Recent rapid response activation: team is already aware.
    - Explicit clinical-team-set suppression with valid expiration.
    """
    state_table = dynamodb.Table(PATIENT_STATE_TABLE)
    state = _undecimalize(state_table.get_item(
        Key={"patient_id": patient_id, "encounter_id": encounter_id}
    ).get("Item", {}))

    if state.get("current_unit_type") == "ICU":
        return {"suppressed": True, "reason": "patient_in_icu"}

    if state.get("is_comfort_care"):
        return {"suppressed": True, "reason": "comfort_care_active"}

    rrt_at = state.get("last_rrt_activation_at")
    if rrt_at:
        rrt_dt = datetime.fromisoformat(rrt_at.replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - rrt_dt) < timedelta(
                minutes=SUPPRESSION_AFTER_RRT_MINUTES):
            return {"suppressed": True, "reason": "recent_rrt_activation"}

    # Explicit suppression registry. The clinical team can request a
    # time-bounded suppression for known-benign patterns (e.g., a patient
    # in active titration where rapidly-changing vitals are expected).
    suppression_table = dynamodb.Table(SUPPRESSION_REGISTRY_TABLE)
    response = suppression_table.query(
        KeyConditionExpression=Key("patient_id").eq(patient_id),
    )
    now = datetime.now(timezone.utc).isoformat()
    for item in response.get("Items", []):
        item = _undecimalize(item)
        if item.get("expires_at", "9999") > now:
            return {
                "suppressed": True,
                "reason":     "explicit_suppression",
                "details":    item.get("suppression_reason"),
            }

    return {"suppressed": False}

def get_last_alert_for_patient(patient_id):
    """Look up the most recent alert for the patient (for delta detection
    and re-page interval enforcement).
    """
    table = dynamodb.Table(ALERT_STATE_TABLE)
    response = table.query(
        IndexName="patient_id-triggered_at-index",
        KeyConditionExpression=Key("patient_id").eq(patient_id),
        ScanIndexForward=False,
        Limit=1,
    )
    items = response.get("Items", [])
    return _undecimalize(items[0]) if items else None

def get_last_score(patient_id, exclude_score_id=None):
    """Look up the second-most-recent score for delta computation."""
    table = dynamodb.Table(SCORING_HISTORY_TABLE)
    response = table.query(
        KeyConditionExpression=Key("patient_id").eq(patient_id),
        ScanIndexForward=False,
        Limit=5,
    )
    for item in response.get("Items", []):
        item = _undecimalize(item)
        if exclude_score_id is None or item.get("score_id") != exclude_score_id:
            return item
    return None

def route_alert(score_record, explanation):
    """Apply tier routing, suppression, delta detection, and channel fan-out.

    Production publishes channel-specific events to EventBridge with
    different rules subscribed by the pager-integration Lambda, the
    dashboard Lambda, the EHR-banner Lambda, and the audit indexer.
    Channels are loosely coupled; adding a new channel does not require
    changes to this function.
    """
    patient_id    = score_record["patient_id"]
    encounter_id  = score_record["encounter_id"]
    tier          = score_record["tier"]
    calibrated    = float(score_record["calibrated_probability"])

    if tier == "below_threshold":
        # No alert generated. Score is recorded for audit but not surfaced.
        return None

    suppression = check_suppression_rules(patient_id, encounter_id)
    if suppression["suppressed"]:
        logger.info("alert suppressed", extra={
            "patient_id":    patient_id,
            "tier":          tier,
            "reason":        suppression["reason"],
        })
        _emit_metric(f"Suppressed_{suppression['reason']}", 1)
        return None

    # Delta detection. A score that jumped substantially since the last
    # score is more actionable than a steady-state-high score; pages key
    # on substantial deltas plus high-tier steady states.
    prior = get_last_score(patient_id, exclude_score_id=score_record["score_id"])
    score_delta = (
        calibrated - float(prior.get("calibrated_probability", 0)) if prior else 0.0
    )
    is_delta_alert = score_delta >= DELTA_ALERT_THRESHOLD

    alert_id = f"DETER-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:8]}"
    alert = {
        "alert_id":         alert_id,
        "patient_id":       patient_id,
        "encounter_id":     encounter_id,
        "score_id":         score_record["score_id"],
        "unit_type":        score_record.get("unit_type"),
        "tier":             tier,
        "score":            calibrated,
        "score_delta":      score_delta,
        "is_delta_alert":   is_delta_alert,
        "triggered_at":     datetime.now(timezone.utc).isoformat(),
        "model_version":    score_record.get("model_version"),
        "ack_status":       "pending",
        "explanation":      explanation,
    }

    # Channel decisions. Page tier is the smallest set; dashboard is the
    # next tier; EHR banner is everything that fires; audit captures all.
    last_alert = get_last_alert_for_patient(patient_id)
    cooled_down = True
    if last_alert and last_alert.get("triggered_at"):
        last_dt = datetime.fromisoformat(last_alert["triggered_at"].replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - last_dt) < timedelta(
                minutes=REPAGE_MIN_INTERVAL_MINUTES):
            cooled_down = False

    should_page = (
        (tier == "high" or (is_delta_alert and tier in ("high", "medium")))
        and cooled_down
    )

    channels = []
    if should_page:
        send_pager_notification(alert)
        channels.append("pager")
    if tier in ("high", "medium"):
        publish_to_dashboard(alert)
        channels.append("dashboard")
    publish_to_ehr_banner(alert)
    channels.append("ehr_banner")

    alert["routing_channels"] = channels

    # Persist and audit. The alert-state table is the system of record;
    # OpenSearch is the audit and search index.
    table = dynamodb.Table(ALERT_STATE_TABLE)
    table.put_item(
        Item=_decimalize(alert),
        ConditionExpression="attribute_not_exists(alert_id)",
    )
    # OpenSearch index call is omitted for brevity; production uses the
    # opensearch-py client with sigv4 auth. The same alert dict is
    # indexed for search and analytics.

    _emit_metric("AlertsGenerated", 1)
    _emit_metric(f"AlertTier_{tier}", 1)
    if is_delta_alert:
        _emit_metric("DeltaAlerts", 1)

    return alert

def send_pager_notification(alert):
    """Send pager-tier notification via SNS.

    SNS topic subscribers are the rapid response team's pagers, the
    on-call hospitalist, and the charge nurse. Each subscriber has its
    own delivery protocol (SMS, email-to-pager-gateway, vendor API).

    The pager channel carries ONLY the alert_id, tier, and unit. No
    patient_id, no vital values, no narrative. PHI does not transit
    lock-screen-visible channels or the logs they generate. The clinician
    fetches the full alert by alert_id through the authenticated
    dashboard or EHR banner.
    """
    # Minimal payload: alert_id, tier, unit. No PHI.
    summary = (
        f"[{alert['tier'].upper()}] Deterioration alert on {alert.get('unit_type', 'unknown unit')}. "
        f"Alert ID: {alert['alert_id']}. Open dashboard for details."
    )
    sns.publish(
        TopicArn=RAPID_RESPONSE_TOPIC_ARN,
        Subject=f"[{alert['tier'].upper()}] Deterioration: {alert['alert_id']}",
        Message=summary,
    )

def publish_to_dashboard(alert):
    """Publish to the charge-nurse dashboard event channel.

    Production routes through EventBridge to an AppSync subscription that
    pushes to the dashboard via WebSocket. The dashboard shows the unit's
    high-and-medium-tier alerts in real time so the charge nurse has
    situational awareness.
    """
    eventbridge.put_events(Entries=[{
        "Source":      "deterioration.alert-router",
        "DetailType":  "DashboardAlert",
        "Detail":      json.dumps({
            "alert_id":       alert["alert_id"],
            "patient_id":     alert["patient_id"],
            "tier":           alert["tier"],
            "score":          alert["score"],
            "triggered_at":   alert["triggered_at"],
        }, default=str),
        "EventBusName": DETERIORATION_SCORING_BUS,
    }])

def publish_to_ehr_banner(alert):
    """Publish to the EHR-banner integration.

    Production integrates via SMART on FHIR (Epic) or vendor-specific
    Cogito / BPA mechanisms. The banner shows in the patient's chart so
    the bedside nurse, attending, and resident covering all see the alert
    when they open the chart.
    """
    eventbridge.put_events(Entries=[{
        "Source":      "deterioration.alert-router",
        "DetailType":  "EHRBannerAlert",
        "Detail":      json.dumps({
            "alert_id":       alert["alert_id"],
            "patient_id":     alert["patient_id"],
            "encounter_id":   alert["encounter_id"],
            "tier":           alert["tier"],
            "score":          alert["score"],
            "narrative":      alert["explanation"]["narrative"],
            "triggered_at":   alert["triggered_at"],
        }, default=str),
        "EventBusName": DETERIORATION_SCORING_BUS,
    }])
```

The repage interval and the delta threshold are the two operational dials that get tuned the most. Set them too tight and the same patient pages every ten minutes for the same reason; set them too loose and a substantial score jump that warrants a fresh page gets swallowed by cooldown. Production deployments ship with conservative defaults, then adjust per unit based on the alert disposition data captured in the next step.

---

## Step 8: Capture Acknowledgments and Outcomes

Every alert generates an acknowledgment requirement. The clinician who looked at the alert dispositions it (acknowledged-monitoring, escalated, intervention, dismissed-as-noise). Subsequent clinical events (ICU transfer, code blue, sepsis bundle initiation) are captured and linked to recent alerts as the eventual outcome. The combined alert + disposition + outcome record is the labeled data that drives retraining and threshold tuning. Without this loop, the model drifts and nobody finds out until clinicians stop trusting it.

```python
def on_clinician_acknowledgment(alert_id, clinician_id, disposition,
                                intervention=None, notes=None):
    """Record a clinician's acknowledgment of an alert.

    disposition ∈ {acknowledged_monitoring, escalated, intervention,
                   dismissed_as_noise, deferred_handoff}
    """
    valid_dispositions = {
        "acknowledged_monitoring",
        "escalated",
        "intervention",
        "dismissed_as_noise",
        "deferred_handoff",
    }
    if disposition not in valid_dispositions:
        raise ValueError(f"invalid disposition: {disposition}")

    table = dynamodb.Table(ALERT_STATE_TABLE)
    now_iso = datetime.now(timezone.utc).isoformat()

    # ConditionExpression ensures we only acknowledge an existing alert,
    # and only once. EventBridge delivers at-least-once, so the same ack
    # event may arrive multiple times; the version-counter pattern keeps
    # the record idempotent.
    response = table.update_item(
        Key={"alert_id": alert_id},
        UpdateExpression=(
            "SET ack_status = :ack, acknowledged_by = :clin, "
            "acknowledged_at = :ts, disposition = :disp, "
            "intervention = :inter, ack_notes = :notes "
            "ADD ack_version :one"
        ),
        ExpressionAttributeValues={
            ":ack":   "acknowledged",
            ":clin":  clinician_id,
            ":ts":    now_iso,
            ":disp":  disposition,
            ":inter": intervention or "",
            ":notes": notes or "",
            ":one":   1,
        },
        ConditionExpression="attribute_exists(alert_id)",
        ReturnValues="ALL_NEW",
    )
    updated = _undecimalize(response.get("Attributes", {}))

    _emit_metric("AcksReceived", 1)
    _emit_metric(f"Disposition_{disposition}", 1)

    # Compute time-to-acknowledge for operational monitoring.
    if updated.get("triggered_at"):
        triggered_dt = datetime.fromisoformat(
            updated["triggered_at"].replace("Z", "+00:00")
        )
        ttak_minutes = (datetime.now(timezone.utc) - triggered_dt).total_seconds() / 60.0
        _emit_metric("TimeToAcknowledgeMinutes", ttak_minutes, unit="None")

    # Dismissed-as-noise is the gold-mine signal. Every dismissal tells
    # the model team something about thresholds, features, or subgroup
    # performance. Forward to the workflow bus for the operational
    # tuning pipeline.
    if disposition == "dismissed_as_noise":
        eventbridge.put_events(Entries=[{
            "Source":     "deterioration.alert-router",
            "DetailType": "AlertDismissed",
            "Detail":     json.dumps({
                "alert_id":   alert_id,
                "tier":       updated.get("tier"),
                "score":      float(updated.get("score", 0)),
                "unit_type":  updated.get("unit_type"),
                "notes":      notes or "",
            }, default=str),
            "EventBusName": DETERIORATION_SCORING_BUS,
        }])

    return updated

def on_clinical_outcome(patient_id, encounter_id, outcome_event):
    """Record a downstream clinical outcome and link it to recent alerts.

    outcome_event keys:
      event_id:    unique event identifier from the source system
      type:        icu_transfer | code_blue | unexpected_death |
                   sepsis_bundle_initiated | rapid_response_activated |
                   uneventful_discharge
      occurred_at: ISO8601 UTC
      details:     dict
    """
    # Idempotency guard. EventBridge delivers at-least-once; redelivered
    # outcome events must not double-link outcomes or double-write S3 label
    # rows, which would bias the retraining distribution toward redelivered
    # cases on a rare positive class.
    processed_table = dynamodb.Table("processed-outcome-events")
    outcome_event_key = f"{outcome_event.get('event_id', '')}:{outcome_event['type']}"
    try:
        processed_table.put_item(
            Item={
                "event_key": outcome_event_key,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_not_exists(event_key)",
        )
    except processed_table.meta.client.exceptions.ConditionalCheckFailedException:
        logger.info("duplicate outcome event, skipping", extra={
            "event_key": outcome_event_key,
        })
        return None

    table = dynamodb.Table(ALERT_STATE_TABLE)
    occurred_at = outcome_event["occurred_at"]
    occurred_dt = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    window_start = (occurred_dt - timedelta(hours=OUTCOME_LINKAGE_WINDOW_HOURS)).isoformat()

    # Find recent alerts for this encounter in the linkage window.
    response = table.query(
        IndexName="patient_id-triggered_at-index",
        KeyConditionExpression=(
            Key("patient_id").eq(patient_id) & Key("triggered_at").gte(window_start)
        ),
    )

    linked_alert_ids = []
    for item in response.get("Items", []):
        item = _undecimalize(item)
        if item.get("encounter_id") != encounter_id:
            continue

        triggered_dt = datetime.fromisoformat(
            item["triggered_at"].replace("Z", "+00:00")
        )
        time_from_alert = (occurred_dt - triggered_dt).total_seconds() / 60.0

        # Update the alert with the linked outcome. UpdateExpression keeps
        # this idempotent on duplicate outcome events.
        table.update_item(
            Key={"alert_id": item["alert_id"]},
            UpdateExpression=(
                "SET linked_outcome = :outcome, outcome_linked_at = :ts"
            ),
            ExpressionAttributeValues={
                ":outcome": _decimalize({
                    "outcome_type":                       outcome_event["type"],
                    "occurred_at":                        occurred_at,
                    "time_from_alert_minutes":            time_from_alert,
                    "details":                            outcome_event.get("details", {}),
                }),
                ":ts": datetime.now(timezone.utc).isoformat(),
            },
        )
        linked_alert_ids.append(item["alert_id"])

    # Write a label row for retraining. One label per outcome event with
    # its linked alerts (or none if there were no alerts in the window;
    # that case is informative too: a missed outcome).
    label_record = {
        "label_id":            str(uuid.uuid4()),
        "patient_id":          patient_id,
        "encounter_id":        encounter_id,
        "outcome_type":        outcome_event["type"],
        "occurred_at":         occurred_at,
        "linked_alert_ids":    linked_alert_ids,
        "label":               (1 if outcome_event["type"] in {
            "icu_transfer",
            "code_blue",
            "unexpected_death",
            "sepsis_bundle_initiated",
            "rapid_response_activated",
        } else 0),
        "labeled_at":          datetime.now(timezone.utc).isoformat(),
    }

    s3_client.put_object(
        Bucket=TRAINING_LABELS_BUCKET,
        Key=(
            f"outcomes/year={occurred_at[:4]}/month={occurred_at[5:7]}/"
            f"{label_record['label_id']}.json"
        ),
        Body=json.dumps(label_record).encode("utf-8"),
        ServerSideEncryption="aws:kms",
    )

    eventbridge.put_events(Entries=[{
        "Source":      "deterioration.outcome-capture",
        "DetailType":  "OutcomeCaptured",
        "Detail":      json.dumps(label_record, default=str),
        "EventBusName": DETERIORATION_SCORING_BUS,
    }])

    _emit_metric("OutcomesCaptured", 1)
    _emit_metric(f"Outcome_{outcome_event['type']}", 1)
    return label_record
```

The label derivation here treats ICU transfer, code blue, unexpected death, sepsis bundle initiation, and rapid response activation all as positive outcomes for retraining. That mapping is a clinical-governance decision and may not match every program; some hospitals separate "rapid response that turned out to be nothing" from "rapid response that escalated to ICU." Audit the label distribution monthly and ask the lead clinician whether a random sample of labeled cases matches their expectation. If the disagreement rate is over 10%, the label schema needs revisiting before the next retrain.

---

## Full Pipeline

Now string the pieces together. In production this function does not exist as a single callable; each step runs in its own compute container, orchestrated by EventBridge fan-out between stages. The single-function version here makes the data flow visible for teaching.

```python
def train_demo_model(num_synthetic_patients=400, random_state=42):
    """Train a tiny in-process model on synthetic feature vectors.

    Production replaces this with a SageMaker Training Job that reads
    historical features from the offline Feature Store and produces a
    versioned model artifact in the SageMaker Model Registry. The
    teaching example trains a small logistic regression on synthetic
    data so the scoring path is runnable in a notebook.
    """
    rng = np.random.default_rng(random_state)
    feature_order = [
        "vital_HR_current", "vital_HR_slope_4h", "vital_HR_delta_from_baseline",
        "vital_RR_current", "vital_RR_slope_4h",
        "vital_SBP_current", "vital_SBP_slope_4h",
        "vital_TEMP_current", "vital_TEMP_delta_from_baseline",
        "vital_SPO2_current",
        "lab_LACTATE_current", "lab_WBC_current", "lab_CREATININE_current",
        "composite_shock_index", "composite_rox_index",
        "recent_lactate_order", "recent_blood_culture_order",
        "has_active_antibiotic", "has_active_vasopressor",
    ]

    # Synthetic feature matrix. Rough realistic ranges; this is a teaching
    # demonstration, not a clinically validated cohort.
    X = np.column_stack([
        rng.normal(85, 15, num_synthetic_patients),     # HR_current
        rng.normal(0, 3, num_synthetic_patients),       # HR_slope_4h
        rng.normal(0, 10, num_synthetic_patients),      # HR_delta_from_baseline
        rng.normal(18, 4, num_synthetic_patients),      # RR_current
        rng.normal(0, 1.5, num_synthetic_patients),     # RR_slope_4h
        rng.normal(125, 18, num_synthetic_patients),    # SBP_current
        rng.normal(0, 5, num_synthetic_patients),       # SBP_slope_4h
        rng.normal(37.0, 0.7, num_synthetic_patients),  # TEMP_current
        rng.normal(0, 0.6, num_synthetic_patients),     # TEMP_delta_from_baseline
        rng.normal(96, 3, num_synthetic_patients),      # SPO2_current
        rng.lognormal(0.4, 0.5, num_synthetic_patients),# LACTATE
        rng.normal(8, 3, num_synthetic_patients),       # WBC
        rng.normal(1.0, 0.4, num_synthetic_patients),   # CREATININE
        np.zeros(num_synthetic_patients),               # placeholder shock_index
        np.zeros(num_synthetic_patients),               # placeholder rox_index
        rng.binomial(1, 0.05, num_synthetic_patients),  # recent_lactate_order
        rng.binomial(1, 0.04, num_synthetic_patients),  # recent_blood_culture_order
        rng.binomial(1, 0.20, num_synthetic_patients),  # has_active_antibiotic
        rng.binomial(1, 0.02, num_synthetic_patients),  # has_active_vasopressor
    ])
    # Compute composites from the synthetic data so they are realistic.
    X[:, 13] = X[:, 0] / np.clip(X[:, 5], 1, None)             # shock index
    X[:, 14] = (X[:, 9] / 0.21) / np.clip(X[:, 3], 1, None)    # ROX (assume FiO2=0.21)

    # Synthesize a label that loosely correlates with the deterioration
    # signature: rising HR + RR, elevated lactate, recent blood culture.
    risk_score = (
        0.6 * (X[:, 0] - 85) / 15
        + 0.5 * X[:, 1]
        + 0.4 * (X[:, 3] - 18) / 4
        + 0.5 * X[:, 4]
        + 0.7 * (np.log(X[:, 10]) - 0.4) / 0.5
        + 0.8 * X[:, 16]
        + 0.5 * X[:, 15]
        + rng.normal(0, 0.4, num_synthetic_patients)
    )
    y = (risk_score > np.percentile(risk_score, 80)).astype(int)

    model = LogisticRegression(max_iter=1000, random_state=random_state)
    model.fit(X, y)

    # Calibrate via isotonic regression on a held-out chunk. Production
    # holds out a separate validation set and freezes the calibrator with
    # the model artifact. Here we calibrate on the training data for a
    # demo and accept the (small) optimistic bias.
    raw_probs = model.predict_proba(X)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_probs, y)

    return model, calibrator, feature_order

def run_deterioration_pipeline(raw_events, model, calibrator, feature_order):
    """End-to-end deterioration pipeline against a batch of raw events.

    Returns a list of (score_record, alert) tuples, with alert == None
    when the score did not produce an alert. Prints per-step progress so
    readers can trace the data flow.
    """
    print(f"[1/8] normalizing {len(raw_events)} clinical events")
    canonical_events = []
    for raw in raw_events:
        normalized = normalize_clinical_event(raw)
        if normalized is not None:
            canonical_events.append(normalized)

    print("[2/8] updating patient state store")
    encounters_touched = set()
    for canonical in canonical_events:
        update_patient_state(canonical)
        encounters_touched.add((canonical["patient_id"], canonical["encounter_id"]))

    print(f"[3/8] dispatching scoring requests for {len(encounters_touched)} encounters")
    # Production publishes ScoreRequest events to EventBridge; the
    # scoring orchestrator Lambda subscribes and runs steps 4-7. Here
    # we run them inline for a single-process demo.

    results = []
    for patient_id, encounter_id in encounters_touched:
        as_of = datetime.now(timezone.utc).isoformat()

        print(f"[4/8] computing features for {patient_id}/{encounter_id}")
        features = compute_features(patient_id, encounter_id, as_of)

        print(f"[5/8] scoring {patient_id}/{encounter_id}")
        score_record = score_patient(
            patient_id, encounter_id, features, feature_order,
            trigger="event_driven", model=model, calibrator=calibrator,
        )

        print(f"[6/8] building explanation for score {score_record['score_id']}")
        explanation = build_explanation(score_record, features, feature_order, model)

        print(f"[7/8] routing alert for tier {score_record['tier']}")
        alert = route_alert(score_record, explanation)

        results.append((score_record, alert))

    print("[8/8] acknowledgment and outcome capture are event-triggered; "
          "call on_clinician_acknowledgment and on_clinical_outcome from "
          "the appropriate handlers")

    return results
```

Run this end-to-end against synthetic events from MIMIC-IV or Synthea and you will see the full shape of the pipeline in your console. The output is a handful of scoring records and alerts in DynamoDB, a set of events on the deterioration-scoring bus, and a few metrics in CloudWatch. In production the volume is orders of magnitude larger and the compute is orders of magnitude more distributed, but the function boundaries do not change.

---

## Gap to Production

Several things would need to change before you would deploy any of this against a live clinical-event stream.

**Real HL7 v2 and FHIR parsing.** The example starts from a clinical event already shaped as a Python dict. In production, the upstream integration parses HL7 v2 ADT (admit/transfer/discharge), ORU (observation results), ORM (orders), and RDE (pharmacy) messages, and FHIR R4 Observation, MedicationAdministration, Encounter, and DiagnosticReport resources. Use a maintained library (HAPI FHIR for JVM-side, `fhir.resources` or `python-hl7` for Python, plus the integration engine of choice: Mirth, Rhapsody, Cloverleaf, or a vendor-supplied integration platform). The spec is large, the edge cases are many, and the consequences of a parser bug are silent data corruption hours or days downstream.

**Real SageMaker endpoint instead of in-process model.** The teaching example trains a logistic regression in-process and scores against it directly. Production hosts the model on a multi-AZ SageMaker real-time endpoint with auto-scaling, model-monitor enabled for data and prediction drift, and the model artifact registered in the SageMaker Model Registry with versioning and approval workflow. The `score_via_sagemaker_endpoint` function shows the production-shape boto3 call; replacing the in-process call site with that function is the swap, and the rest of the pipeline does not change.

**SageMaker Clarify for real SHAP explanations.** The `compute_top_drivers` function uses a crude proxy. Production uses SageMaker Clarify (or SHAP directly against the deployed model) to compute per-prediction Shapley values that reflect the model's actual reasoning. Without real SHAP, the explanation degrades to "directionally plausible" and clinicians lose trust faster than the program can recover.

**SageMaker Feature Store with point-in-time correctness.** The example writes a feature record to Feature Store but does not exercise the offline-online consistency or the point-in-time join that production needs for retraining. A real deployment uses the offline store's time-aware joins so historical predictions can be reproduced exactly, which is a clinical-safety-and-governance requirement, not a nicety.

**SageMaker Model Monitor for drift and calibration tracking.** Production has Model Monitor running on the endpoint with baseline statistics from training data. Data drift on input features (vital distributions shift over a season), prediction drift on output scores (the model's score distribution shifts even when the inputs do not), and quality drift (when labeled outcomes are available) all produce CloudWatch alarms that the model team triages. Calibration drift is the one that bites quietly and matters most for operational threshold tuning.

**Bedside monitor integration.** The teaching example reads vitals from the EHR-charted observations only. Bedside monitors (Philips IntelliVue, GE Carescape, Mindray, Drager) emit continuous waveforms and sub-minute granularity through HL7 RxR, IHE PCD, or vendor protocols, often via bridge appliances (Capsule Medical, Cerner CareAware iBus, Bernoulli). The marginal feature richness is real (closer-to-real-time alerting, much richer trajectory features) but the integration project is substantial. Some programs go this route; others do not. The right answer depends on the population and the workflow.

**EHR banner integration is vendor-specific.** Epic, Cerner (Oracle Health), Meditech, and Allscripts have different ways of integrating external decision support into the chart view. Epic supports SMART on FHIR plus their proprietary Cogito and Best Practice Advisory mechanisms; Cerner supports Discern and SMART on FHIR; Meditech is more limited. The chosen integration method affects user experience, development effort, and the operational support burden. Plan for vendor-specific integration testing per EHR target.

**Paging and clinical communication platform integration.** The example sends a generic SNS message. Production integrates with Vocera, TigerConnect, Spok, Mobile Heartbeat, or whichever clinical communication platform the hospital uses. Each has its own SDK, its own escalation rules, and its own failure modes. Plan for integration testing, escalation testing, after-hours testing, and failure-mode testing (what happens when the paging system is down).

**OpenSearch alert audit indexing.** The example writes alerts to DynamoDB but stops short of indexing them in OpenSearch. Production uses the `opensearch-py` client with sigv4 auth to index every alert, every disposition, and every linked outcome for retrospective analysis, governance review, and case-by-case quality improvement. The OpenSearch domain runs in a VPC with fine-grained access control restricted to the model team and the clinical governance committee.

**Idempotency everywhere.** Alert creation, score persistence, acknowledgment capture, and outcome linking all need to handle duplicate delivery. The example uses `ConditionExpression` with `attribute_not_exists` on alert creation (treat `ConditionalCheckFailedException` as success) and version counters on acknowledgment (so the same ack delivered twice does not overwrite the disposition). Add a recent-events deduplication cache on the consumer side keyed by event ID for further protection.

**IAM scoping.** Each pipeline component (event-normalizer Lambda, scoring-orchestrator Lambda, feature-engine Lambda, calibration Lambda, explanation builder, alert router, ack capture, outcome capture, retraining) gets its own role with minimum permissions. The explanation builder needs Bedrock InvokeModel on the specific model ARN; it does not need DynamoDB write access to the patient-state table. The outcome-capture role does not need Bedrock access. Scope tightly and review roles annually.

**VPC deployment.** Lambdas, SageMaker endpoints, Comprehend Medical calls, Bedrock invocations, and Timestream queries all run inside a VPC with VPC endpoints for DynamoDB, S3, Kinesis, Timestream, SageMaker Runtime, Bedrock, EventBridge, and KMS. SNS is an edge service; ensure the notification payload is minimal (alert ID, tier, patient identifier) rather than the full explanation. EHR integrations typically use AWS Direct Connect or Site-to-Site VPN to the hospital network rather than public-internet egress.

**KMS customer-managed keys.** Every data-at-rest store (raw events lake, patient-state table, alert-state table, scoring history, feature store offline and online, training labels bucket, OpenSearch indices, Timestream database, CloudWatch Logs) is encrypted with customer-managed KMS keys scoped by role. Key policies restrict usage to the specific roles that need each key; CloudTrail data events audit the usage.

**Clinical governance is not optional.** The detection pipeline is roughly 30% of the work. Clinical governance, alert workflow design, change management for clinical staff, ongoing performance review, and safety-event review are the other 70%. A pipeline without an active governance committee that meets monthly, reviews subgroup performance, reviews recent alerts and dispositions, approves model updates, and owns the deployment criteria will not last in clinical operation. Build the governance before the technology.

**Local validation before clinical deployment.** Whether the model is built in-house or supplied by a vendor (Epic Deterioration Index, eCART, etc.), local validation against the hospital's own population is required before clinical deployment. The validation should use a hold-out time period (not just patient split) to capture temporal effects. It should include subgroup-stratified analysis. It should compare against the existing standard of care (typically the in-use NEWS2 or MEWS implementation). The Epic Deterioration Index COVID-era underperformance was a public lesson; learn from it.

**Prospective shadow deployment.** Before any alert reaches a clinician, the model runs in shadow mode for several weeks: scoring patients, logging alerts, but not routing them to humans. Shadow alerts get reviewed retrospectively. This catches feature-pipeline bugs, calibration issues that did not show up in retrospective validation, and operational integration problems. Shadow review is also when alert volume gets calibrated to operational capacity. Skipping shadow has produced more failed deployments than any single technical issue.

**Subgroup performance monitoring.** Build dashboards that show AUROC, calibration ECE, alert rate, and dismissal rate by age band, sex, race and ethnicity (where structurally captured), language, insurance status, and unit type. If the pipeline disproportionately under-alerts on a subgroup, that is a patient-safety issue. If it disproportionately over-alerts on a subgroup, that is also a patient-safety issue. The clinical governance committee reviews these dashboards monthly.

**FDA SaMD determination.** Clinical decision support software that influences treatment decisions may fall under FDA medical device regulation. Most "flag risk for clinician review with transparent reasoning" deployments qualify for the 21st Century Cures Act CDS exemption, but the boundary has shifted with FDA guidance updates. Get the regulatory determination in writing from your regulatory affairs team before clinical deployment. Higher-autonomy or closed-loop variants may not qualify for the exemption.

**Decommissioning criteria.** A model can stop working. Performance can degrade enough that it should be turned off. Decommissioning criteria (calibration ECE above X, subgroup AUROC below Y, dismissal rate above Z, time-to-acknowledge above target) should be defined and pre-approved by the governance committee before deployment. Without pre-approved criteria, decommissioning becomes a political decision rather than a clinical safety decision.

**Bedrock input and output handling.** Log the model ID, the prompt template version, and the response length. Never log the full prompt (contains clinical context and PHI-adjacent feature values) or the full response. Add a PHI scanner on the output path to catch accidental patient-identifier leakage if the LLM produces unexpected text; do not trust the model to be clean every time.

**Feedback loop hygiene.** The outcome-capture path writes labels. The retraining job reads them. Retraining can drift badly if labels are wrong, so audit quality monthly: sample 25 outcome events, ask the lead clinician whether the outcome type and timestamp match their memory, and track the disagreement rate. Over 10% disagreement and the label schema needs revisiting before the next retrain cycle.

**Monitoring and alarms.** Wire CloudWatch alarms on: end-to-end alert latency (event ingest to alert delivery) p95 above target, alert volume per unit per shift outside target range, dismissal rate drifting beyond historical bounds, subgroup alert-rate ratios above fairness thresholds, Bedrock throttle rate above baseline, SageMaker endpoint p95 latency outside service-level targets, DynamoDB consumed capacity nearing provisioned, EventBridge delivery failures, Timestream query failures. Page the on-call data-engineering team and the model team's lead when critical alarms fire. Page the clinical lead when patient-safety-relevant alarms fire (alert volume crash to zero, calibration ECE above threshold, end-to-end latency way above target).

**Retention and legal hold.** Alert records, scoring history, feature snapshots, and label files all carry PHI. Retain for the HIPAA baseline (6 years) plus any clinical-safety retention requirements. Use S3 Object Lock in COMPLIANCE mode for the training-labels bucket in production; GOVERNANCE is fine for dev and test. Apply legal hold for the duration of any active patient-safety event review.

**Multi-AZ and disaster recovery.** Deterioration scoring is a 24/7 service. The endpoint runs multi-AZ. The patient-state table replicates across AZs by default. The alert router runs in multiple AZs. Plan a DR drill quarterly; the fallback to the existing track-and-trigger system (NEWS2 charted in the flowsheet) must be documented and the staff need to know that fallback exists when the system is down.

**Testing.** Table-driven unit tests on `map_to_tier`, `check_suppression_rules`, `_compute_slope`, `_filter_recent_meds`, and the normalization functions; integration tests against DynamoDB Local and moto for the full state-update plus scoring flow; golden-path regression tests on a small labeled dataset run on every retrain so a model that breaks a subgroup does not slip through into production.

**Cost awareness.** Kinesis, Timestream, SageMaker endpoint hosting, Bedrock, OpenSearch, and Comprehend Medical (when used) are the major line items. Track cost-per-prevented-deterioration (total monthly infrastructure cost divided by confirmed prevented-event count) alongside dollar-value-of-prevented-events (typical ICU bed-day costs are $3,000-5,000/day). The infrastructure cost for a 300-bed hospital is roughly in the $3,000-8,000/month range; preventing one preventable ICU transfer per month covers the infrastructure. The harder cost is people: clinical informatics, model team, governance committee time.

None of this is unique to deterioration prediction. It is the cost of running any PHI-adjacent prediction service that influences clinical decisions at scale. The good news is that the infrastructure (event normalization, patient-state store, time-series feature engine, scoring endpoint, calibration layer, explanation builder, alert router, audit index) amortizes across Recipe 3.5 (lab outliers), 3.8 (readmission risk), 7.x (predictive analytics), and 12.x (time-series forecasting). Build it once carefully, reuse it everywhere. The hard part is not the model. The hard part is the workflow integration and the clinical governance, and that part starts on day one, not after the model passes validation.

---

*← [Main Recipe 3.7](chapter03.07-patient-deterioration-early-warning) · [Chapter 3 Preface](chapter03-preface)*
