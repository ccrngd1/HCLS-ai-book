# Recipe 3.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 3.2. It shows one way you could translate the patient no-show pattern-detection recipe into working Python using scikit-learn (for the model), Amazon DynamoDB (for patient baselines and intervention queues), Amazon S3 (for label archives), Amazon SageMaker Feature Store (for consistent features between training and serving), and Amazon Pinpoint (for outreach). It is not production-ready. There is no real EHR scheduling integration, no Step Functions orchestration, no SageMaker Batch Transform infrastructure wrapping the scorer, no QuickSight dashboards, no subgroup fairness monitoring harness, no override/appeal workflow, and no care-coordinator UI. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you would wire into a health system's scheduling operations on Monday morning.
>
> The code maps to the five core pseudocode steps from the main recipe: assemble features for an upcoming appointment, score the appointment with a trained model, compute the patient-baseline deviation and apply routing thresholds, execute the intervention and log what was done, and capture the outcome and update labels and baselines. A small `retrain_monthly` sketch is included at the end to close the loop. Everything else (monitoring, drift detection, alarm wiring, per-subgroup performance tracking) is covered in the Gap to Production section.

---

## Setup

You will need the AWS SDK for Python plus scikit-learn, pandas, and numpy for the model code:

```bash
pip install boto3 scikit-learn pandas numpy
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:BatchGetItem` on the `patient-baselines`, `intervention-queue`, `investigation-queue`, `intervention-log`, and `predictions-archive` tables
- `s3:GetObject` on the features and model-artifacts buckets, `s3:PutObject` on the labels bucket
- `sagemaker-featurestore-runtime:GetRecord` for online-feature reads
- `sagemaker-featurestore-runtime:PutRecord` for feature writes (if you use Feature Store as the persistence layer for patient-level features)
- `mobiletargeting:SendMessages` on your Pinpoint application (this is the Pinpoint service's IAM prefix)
- `cloudwatch:PutMetricData` for operational metrics
- `events:PutEvents` on the EventBridge bus (for publishing outcome events from the EHR integration side)

Scope each Lambda's IAM role to the specific resource ARNs it touches. The permissions above are fine for learning and will fail any serious IAM review. In production, each component (feature-assembly job, scorer, router Lambda, outreach Lambda, outcome-joiner Lambda, retraining job) gets its own role with the minimum permissions for its job.

A few things worth knowing upfront:

- **No real EHR integration in this example.** The scheduling export is the long pole in any production deployment, and each EHR vendor (Epic, Cerner, athena, NextGen, Meditech, and the rest) has its own conventions. This example starts from appointment dictionaries that look like the output of a normalized export. In production, a Glue job (or a vendor-provided integration) writes those dictionaries to S3 on a nightly cadence.
- **scikit-learn here, SageMaker in production.** The example trains and scores a logistic regression in-process with scikit-learn. In a real deployment, you would wrap the same model in a SageMaker training job and score with Batch Transform (for nightly scoring) or a real-time endpoint (for scoring at booking time). The model math is identical; the infrastructure wrapping is what SageMaker provides. Keeping the model logic pure Python here makes the teaching example runnable without spinning up AWS resources just to see it work.
- **DynamoDB table schemas.** `patient-baselines` is keyed on `patient_id` (partition key only). `intervention-queue`, `investigation-queue`, and `predictions-archive` are keyed on `appointment_id`. `intervention-log` is keyed on `intervention_id` with a GSI on `appointment_id` so outcome-joining can find every intervention for a given appointment. You create these once, up front; this file does not do that for you.
- **Probabilities and rates must be Decimal.** DynamoDB rejects Python `float` for numeric attributes (precision loss, which for rolling-rate math is a quiet disaster over thousands of updates). Every rate, probability, and score value passes through `Decimal` on its way into DynamoDB and back out. This is the same gotcha that bites every DynamoDB tutorial reader at least once; the example code handles it so you see the pattern.
- **All example patient data is synthetic.** Patient IDs, provider IDs, clinic IDs, and appointment IDs in the sample output are illustrative and do not refer to any real patients, providers, or services. Use [Synthea](https://github.com/synthetichealth/synthea) in a development environment and never use real PHI in a teaching example.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here: thresholds, feature lists, decay factors, resource names, and the cohort prior for cold-start patients. These are the knobs you will change most often between environments.

```python
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import boto3
import numpy as np
import pandas as pd
from botocore.config import Config
from boto3.dynamodb.conditions import Key

# Structured logging. In production, ship JSON-formatted records to CloudWatch
# Logs Insights. Appointment records are PHI (a patient ID plus a provider
# plus a date is re-identifying), so we log structural metadata only. Never
# log the full appointment body, the full feature vector, or any patient
# demographic fields in regular application logs.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry mode handles DynamoDB and SageMaker throttling with
# exponential backoff and jitter. Nightly scoring is naturally bursty
# (one big batch once a day), and adaptive mode keeps burst windows from
# cascading into retry storms against the feature store.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch = boto3.client("cloudwatch", region_name=REGION, config=BOTO3_RETRY_CONFIG)
eventbridge = boto3.client("events", region_name=REGION, config=BOTO3_RETRY_CONFIG)
# Pinpoint's IAM service prefix is `mobiletargeting`; the client name is `pinpoint`.
pinpoint = boto3.client("pinpoint", region_name=REGION, config=BOTO3_RETRY_CONFIG)
# SageMaker Feature Store runtime, used for online (low-latency) feature reads.
featurestore_runtime = boto3.client(
    "sagemaker-featurestore-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG
)

# --- Resource Names ---
# Fill in with your actual resource names.
PATIENT_BASELINES_TABLE = "patient-baselines"
INTERVENTION_QUEUE_TABLE = "intervention-queue"
INVESTIGATION_QUEUE_TABLE = "investigation-queue"
INTERVENTION_LOG_TABLE = "intervention-log"
PREDICTIONS_ARCHIVE_TABLE = "predictions-archive"

PATIENT_FEATURES_FG = "patient-features"          # SageMaker Feature Store feature group
LABELS_BUCKET = "my-no-show-labels"
MODEL_ARTIFACTS_BUCKET = "my-no-show-model-artifacts"
PINPOINT_APPLICATION_ID = "0123456789abcdef0123456789abcdef"
PINPOINT_VOICE_LONG_CODE = "+15555550100"         # origination number for voice messages
EVENT_BUS_NAME = "appointment-events"

# Deploy-time guardrail: catch unreplaced example values.
assert PINPOINT_APPLICATION_ID != "0123456789abcdef0123456789abcdef" or __name__ != "__production__", \
    "PINPOINT_APPLICATION_ID still uses the example placeholder. Replace before deploying."

# --- Model Version ---
# Every prediction, routing decision, and captured label records the scorer
# version. This is how retraining picks its training window and how
# monitoring attributes regressions to a specific model.
SCORER_VERSION = "logreg-v1.0"
LABEL_DERIVATION_VERSION = "label-v1.0"

# --- Feature List ---
# The ordered list of features the model expects. The serving-time
# feature-assembly step must produce a vector in exactly this order.
# Any mismatch between training-time and serving-time feature ordering
# is a subtle accuracy bug that is painful to debug.
FEATURE_COLUMNS = [
    "lead_time_days",
    "hour_of_day",
    "is_morning",
    "is_followup",
    "was_rescheduled",
    "reschedule_count",
    "prior_no_shows_12m",
    "prior_completions_12m",
    "rolling_no_show_rate",
    "last_engagement_days_ago",
    "phone_bounce_count",
    "portal_active_flag",
    "distance_to_clinic_km",
    "patient_provider_no_show_rate",
    "age",
]

# Features that are naturally categorical; the training code one-hot-encodes
# these. Listed here so the pipeline is in one place.
CATEGORICAL_COLUMNS = ["visit_type", "day_of_week", "insurance_type"]

# --- Routing Thresholds ---
# HIGH_RISK_THRESHOLD: absolute risk above which we queue for outreach.
# DEVIATION_FLAG_THRESHOLD: appointment-specific risk this far above the
# patient's rolling baseline is a contextual anomaly, even if absolute risk
# is not high enough to cross the outreach threshold.
# INTERVENTION_CAPACITY_PER_DAY caps the outreach queue so the operations
# team does not receive more work than they can execute; excess flagged
# appointments spill to the investigation queue.
#
# These are placeholders. Tune against your own ROC curve and the operations
# team's actual capacity. Make them config-driven so you can adjust without
# a code deploy.
HIGH_RISK_THRESHOLD = Decimal("0.35")
DEVIATION_FLAG_THRESHOLD = Decimal("0.25")
INTERVENTION_CAPACITY_PER_DAY = 120
MIN_BASELINE_OBSERVATIONS = 3        # below this, baseline is considered cold-start

# --- Rolling Baseline Math ---
# Exponential decay factor. Higher ALPHA means the baseline responds more
# quickly to recent behavior. 0.05 is a reasonable starting point
# (about 20 appointments to half-life).
BASELINE_ALPHA = Decimal("0.05")

# --- Cohort Prior for Cold-Start Patients ---
# For brand-new patients with no appointment history, we need a default
# baseline. The cleanest approach is a Bayesian prior informed by cohort
# statistics (insurance type, age band, clinic). For the example we use a
# single population-level prior. In production this should be a lookup
# against a cohort-prior table refreshed monthly.
POPULATION_PRIOR_NO_SHOW_RATE = Decimal("0.15")

# --- Label Schema ---
# Derived labels for training. "no_show" and "late_cancellation" are the
# positive class for the binary model; others are negative or excluded.
# See "The Label Problem" in the main recipe for the discussion.
POSITIVE_LABELS = {"no_show", "late_cancellation"}
VALID_LABELS = {
    "showed",
    "no_show",
    "late_arrival_accepted",
    "late_cancellation",
    "rescheduled_with_lead_time",
}

# Channels the outreach step may attempt, in fallback order. Replaced at
# runtime by the patient's preferences where available.
DEFAULT_CHANNEL_LADDER = ["sms", "voice", "email"]

def _to_decimal(value) -> Decimal:
    """
    Coerce numeric input into Decimal for DynamoDB and for downstream math.

    DynamoDB rejects float. Always pass Decimal. Quantizing to four decimal
    places keeps the storage format predictable without losing meaningful
    precision for probabilities or rates.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value)).quantize(Decimal("0.0001"))
```

---

## Step 1: Assemble Features for the Upcoming Appointment

*The pseudocode calls this `assemble_features(appointment)`. The function merges patient-level features (from the online Feature Store) with appointment-level features (derived from the appointment record itself) into a single feature vector ready for the scorer.*

The correctness property that matters here is **point-in-time-correctness**: every feature must reflect what was known at the moment the appointment was scored, not what becomes known later. For serving-time scoring on tomorrow's schedule this is automatic (the Feature Store returns the current online snapshot). For training data, point-in-time joins on historical feature snapshots are required to avoid leakage; SageMaker Feature Store's `batch_get_record` with an `as_of` timestamp handles that. For brevity, the example shows only the serving-time pattern.

```python
def assemble_features(appointment: dict) -> dict:
    """
    Build the feature vector for one upcoming appointment.

    Expected input keys on `appointment`:
      appointment_id, patient_id, scheduled_time (ISO 8601 string),
      scheduled_at (ISO 8601 string; when the appointment was booked),
      provider_id, clinic_id, visit_type, reschedule_count (int)
    """
    # --- Pull patient-level features from the online Feature Store ---
    # The feature store is the source of truth for features that are the
    # same across any appointment for a given patient: demographics,
    # historical no-show counts, engagement recency, portal activity.
    patient_record = _get_patient_features(appointment["patient_id"])

    # --- Derive appointment-level features from the record itself ---
    scheduled_time = datetime.fromisoformat(appointment["scheduled_time"])
    scheduled_at = datetime.fromisoformat(appointment["scheduled_at"])
    lead_time_days = max((scheduled_time - scheduled_at).days, 0)

    appointment_features = {
        "lead_time_days":        lead_time_days,
        "hour_of_day":           scheduled_time.hour,
        "is_morning":            1 if scheduled_time.hour < 12 else 0,
        "is_followup":           1 if appointment["visit_type"].endswith("-followup") else 0,
        "was_rescheduled":       1 if appointment.get("reschedule_count", 0) > 0 else 0,
        "reschedule_count":      appointment.get("reschedule_count", 0),
        "visit_type":            appointment["visit_type"],
        "day_of_week":           scheduled_time.strftime("%A").lower(),
    }

    # --- Patient-provider pair rate ---
    # How often has this specific patient no-showed for this specific
    # provider? This is one of the strongest pair-level features but
    # cannot be stored in the patient-features group (the feature key is
    # patient_id, not patient_id + provider_id). Compute on demand.
    pair_rate = _patient_provider_no_show_rate(
        patient_id=appointment["patient_id"],
        provider_id=appointment["provider_id"],
    )
    appointment_features["patient_provider_no_show_rate"] = pair_rate

    # --- Merge and stamp ---
    features = {**patient_record, **appointment_features}
    features["appointment_id"] = appointment["appointment_id"]
    features["patient_id"] = appointment["patient_id"]
    features["scheduled_time"] = appointment["scheduled_time"]
    features["scored_at"] = datetime.now(timezone.utc).isoformat()
    features["scorer_version"] = SCORER_VERSION

    return features

def _get_patient_features(patient_id: str) -> dict:
    """
    Read the patient's record from the online Feature Store. If the patient
    has no record (brand-new patient), return a cold-start default vector
    derived from the cohort prior.

    In production, cold-start values come from a cohort-specific prior
    keyed on insurance type + age band + clinic. The single-prior version
    here is a teaching simplification.
    """
    try:
        response = featurestore_runtime.get_record(
            FeatureGroupName=PATIENT_FEATURES_FG,
            RecordIdentifierValueAsString=patient_id,
        )
    except featurestore_runtime.exceptions.ResourceNotFound:
        # New patient. Return cold-start defaults.
        return _cold_start_patient_features()

    record = response.get("Record", [])
    if not record:
        return _cold_start_patient_features()

    # Feature Store returns a list of {FeatureName, ValueAsString}.
    # Decode into a dict and cast numeric fields. In production, a helper
    # or typed schema handles the casts; doing it inline here for clarity.
    raw = {item["FeatureName"]: item["ValueAsString"] for item in record}

    return {
        "prior_no_shows_12m":       int(raw.get("prior_no_shows_12m", 0)),
        "prior_completions_12m":    int(raw.get("prior_completions_12m", 0)),
        "rolling_no_show_rate":     float(raw.get("rolling_no_show_rate", float(POPULATION_PRIOR_NO_SHOW_RATE))),
        "last_engagement_days_ago": int(raw.get("last_engagement_days_ago", 999)),
        "phone_bounce_count":       int(raw.get("phone_bounce_count", 0)),
        "portal_active_flag":       int(raw.get("portal_active_flag", 0)),
        "distance_to_clinic_km":    float(raw.get("distance_to_clinic_km", 10.0)),
        "age":                      int(raw.get("age", 45)),
        "insurance_type":           raw.get("insurance_type", "commercial"),
    }

def _cold_start_patient_features() -> dict:
    """
    Defaults for a patient with no history. The values below are
    intentionally conservative. In production, derive these from a cohort
    prior table refreshed monthly from the warehouse.
    """
    return {
        "prior_no_shows_12m":       0,
        "prior_completions_12m":    0,
        "rolling_no_show_rate":     float(POPULATION_PRIOR_NO_SHOW_RATE),
        "last_engagement_days_ago": 999,
        "phone_bounce_count":       0,
        "portal_active_flag":       0,
        "distance_to_clinic_km":    10.0,
        "age":                      45,
        "insurance_type":           "commercial",
    }

def _patient_provider_no_show_rate(patient_id: str, provider_id: str) -> float:
    """
    Compute the historical no-show rate for this (patient, provider) pair.

    In production, this is a precomputed feature kept in a pair-level feature
    table, queried with single-digit-millisecond latency. For the example,
    we return a neutral default so the function is runnable; swap in a real
    lookup (Athena on the warehouse for batch, DynamoDB for online) in your
    own build.
    """
    # TODO: replace with a real lookup. The neutral default means this
    # feature contributes no signal in the example; that is intentional so
    # the illustrative run does not depend on historical data.
    return 0.0
```

---

## Step 2: Run Inference

*The pseudocode calls this the `SageMaker Batch Transform` step. The feature file for all upcoming appointments lands in S3; Batch Transform reads it, scores each record, and writes predictions back to S3. In this example, we show what the scorer does in-process, using scikit-learn; the SageMaker Batch Transform wrapper runs the same code inside a managed job.*

```python
# Module-level model handle. Loaded once per process from S3 so that
# subsequent calls reuse the deserialized estimator. In a Lambda, this
# lives outside the handler so warm containers skip the load.
import joblib
import os
import io

_MODEL = None
_MODEL_META = None

def _load_model(model_key: str = "current/model.joblib") -> None:
    """
    Download the current model artifact from S3 and deserialize it. The
    artifact is produced by the retraining job; see `retrain_monthly()`.
    """
    global _MODEL, _MODEL_META
    response = s3_client.get_object(Bucket=MODEL_ARTIFACTS_BUCKET, Key=model_key)
    buf = io.BytesIO(response["Body"].read())
    payload = joblib.load(buf)
    _MODEL = payload["pipeline"]          # fitted sklearn Pipeline
    _MODEL_META = payload["meta"]         # dict with version, training_window, etc.
    logger.info("model_loaded", extra={"version": _MODEL_META.get("version")})

def score_appointment(features: dict) -> dict:
    """
    Score a single appointment. Returns a dict with the probability of
    no-show and the scorer version that produced it.

    For batch mode, wrap this in a loop over a DataFrame and write the
    output as JSONL to S3. For real-time mode, this is what the SageMaker
    endpoint returns per request.
    """
    if _MODEL is None:
        _load_model()

    # Build a single-row DataFrame matching the training schema. Using a
    # DataFrame rather than a raw vector makes the training-serving contract
    # explicit: the feature names carry through the sklearn Pipeline and
    # mismatches fail fast rather than silently scoring the wrong column.
    row = {col: features.get(col, 0) for col in FEATURE_COLUMNS}
    for col in CATEGORICAL_COLUMNS:
        row[col] = features.get(col, "unknown")

    df = pd.DataFrame([row])

    # predict_proba returns a (1, 2) array of [P(negative), P(positive)].
    # Positive class is "no-show" by training convention.
    probabilities = _MODEL.predict_proba(df)
    risk_score = float(probabilities[0, 1])

    return {
        "appointment_id": features["appointment_id"],
        "patient_id":     features["patient_id"],
        "risk_score":     _to_decimal(risk_score),
        "scorer_version": SCORER_VERSION,
        "scored_at":      features["scored_at"],
    }

def archive_prediction(features: dict, prediction: dict) -> None:
    """
    Persist the prediction alongside a snapshot of the features that
    produced it. This archive is what the outcome-joiner reads later to
    build the training row; skipping it means you cannot retrain.
    """
    table = dynamodb.Table(PREDICTIONS_ARCHIVE_TABLE)
    # The feature snapshot may contain numeric values that are Python
    # float; convert to Decimal for DynamoDB.
    feature_snapshot = {
        k: _to_decimal(v) if isinstance(v, (int, float)) else v
        for k, v in features.items()
        if k not in ("appointment_id", "patient_id")  # keys already stored separately
    }
    table.put_item(Item={
        "appointment_id":    prediction["appointment_id"],
        "patient_id":        prediction["patient_id"],
        "scheduled_time":    features["scheduled_time"],
        "scored_at":         prediction["scored_at"],
        "scorer_version":    prediction["scorer_version"],
        "risk_score":        prediction["risk_score"],
        "features_snapshot": feature_snapshot,
    })
```

---

## Step 3: Compute Baseline Deviation and Route

*The pseudocode calls this `route_scored_appointments`. For each scored appointment, pull the patient's current baseline from DynamoDB, compute the deviation between the appointment-specific risk and the patient's rolling rate, and apply routing thresholds. High absolute risk goes to the outreach queue; high deviation (even at moderate absolute risk) goes to the investigation queue; everything else rides the default reminder path.*

The routing logic looks simple and is the part of the recipe that drives real operational impact. The deviation flag is the piece pure-prediction pipelines miss: a usually-reliable patient with an elevated risk for this specific appointment is a high-value courtesy-call target who does not show up in a straight sort-by-risk view.

```python
def route_predictions(predictions: list) -> list:
    """
    Apply deviation computation and threshold-based routing to a batch of
    scored appointments.

    Input: list of prediction dicts from score_appointment().
    Output: list of decision dicts, one per appointment.
    """
    # --- Hydrate patient baselines in bulk ---
    patient_ids = list({p["patient_id"] for p in predictions})
    baselines = _batch_get_baselines(patient_ids)

    decisions = []
    for pred in predictions:
        baseline = baselines.get(pred["patient_id"])

        if baseline and baseline["observation_count"] >= MIN_BASELINE_OBSERVATIONS:
            baseline_rate = _to_decimal(baseline["rolling_no_show_rate"])
            deviation = pred["risk_score"] - baseline_rate
        else:
            # Cold start. No reliable baseline; we route on absolute risk
            # only and record the fact that deviation was not evaluated.
            baseline_rate = None
            deviation = Decimal("0.0")

        if pred["risk_score"] >= HIGH_RISK_THRESHOLD:
            action = "outreach"
            reason = "high_absolute_risk"
        elif deviation >= DEVIATION_FLAG_THRESHOLD:
            action = "investigate"
            reason = "contextual_anomaly"
        else:
            action = "standard"
            reason = "default_reminder"

        decisions.append({
            "appointment_id":  pred["appointment_id"],
            "patient_id":      pred["patient_id"],
            "risk_score":      pred["risk_score"],
            "baseline_rate":   baseline_rate,
            "deviation":       _to_decimal(deviation),
            "action":          action,
            "reason":          reason,
            "scorer_version":  pred["scorer_version"],
            "scored_at":       pred["scored_at"],
        })

    # --- Cap outreach at daily capacity ---
    # Excess outreach appointments drop to the investigation queue so
    # someone still sees them; they do not disappear. Sort by risk desc
    # so the highest-risk stay in the outreach queue.
    outreach = [d for d in decisions if d["action"] == "outreach"]
    outreach.sort(key=lambda d: d["risk_score"], reverse=True)
    if len(outreach) > INTERVENTION_CAPACITY_PER_DAY:
        for bumped in outreach[INTERVENTION_CAPACITY_PER_DAY:]:
            bumped["action"] = "investigate"
            bumped["reason"] = "capacity_bump"

    # --- Persist routing decisions and emit metrics ---
    for d in decisions:
        if d["action"] == "outreach":
            _put_queue_item(INTERVENTION_QUEUE_TABLE, d)
            _emit_metric("intervention_queued", dimensions={"risk_band": "high"})
        elif d["action"] == "investigate":
            _put_queue_item(INVESTIGATION_QUEUE_TABLE, d)
            _emit_metric("investigation_flagged", dimensions={"reason": d["reason"]})
        else:
            _emit_metric("standard_reminder")

    return decisions

def _batch_get_baselines(patient_ids: list) -> dict:
    """
    Fetch the current baseline record for a batch of patients. Returns a
    dict keyed by patient_id. Missing patients are absent from the dict;
    the caller treats them as cold-start.
    """
    if not patient_ids:
        return {}

    table_name = PATIENT_BASELINES_TABLE
    result = {}
    # DynamoDB BatchGetItem caps at 100 keys per request; chunk accordingly.
    for i in range(0, len(patient_ids), 100):
        chunk = patient_ids[i:i + 100]
        request = {table_name: {
            "Keys": [{"patient_id": pid} for pid in chunk],
            "ConsistentRead": False,
        }}
        response = dynamodb.batch_get_item(RequestItems=request)
        for item in response["Responses"].get(table_name, []):
            result[item["patient_id"]] = item

        # UnprocessedKeys happens under throttling; a production-grade loop
        # retries with backoff. For the example we log and move on.
        if response.get("UnprocessedKeys"):
            logger.warning("unprocessed_keys_on_batch_get", extra={
                "count": len(response["UnprocessedKeys"].get(table_name, {}).get("Keys", [])),
            })
    return result

def _put_queue_item(table_name: str, decision: dict) -> None:
    """
    Write a routing decision to the appropriate queue table. The queue
    tables are read by the outreach Lambda (intervention-queue) and the
    care-coordinator UI (investigation-queue).
    """
    table = dynamodb.Table(table_name)
    item = {
        "appointment_id": decision["appointment_id"],
        "patient_id":     decision["patient_id"],
        "risk_score":     decision["risk_score"],
        "baseline_rate":  decision["baseline_rate"] if decision["baseline_rate"] is not None else Decimal("-1"),
        "deviation":      decision["deviation"],
        "action":         decision["action"],
        "reason":         decision["reason"],
        "scorer_version": decision["scorer_version"],
        "scored_at":      decision["scored_at"],
        "enqueued_at":    datetime.now(timezone.utc).isoformat(),
    }
    table.put_item(Item=item)

def _emit_metric(metric_name: str, value: int = 1, dimensions: dict = None) -> None:
    """
    Publish an operational metric to CloudWatch. Includes the scorer
    version as a standard dimension so regressions can be attributed to a
    specific model.
    """
    metric_dims = [{"Name": "ScorerVersion", "Value": SCORER_VERSION}]
    if dimensions:
        for k, v in dimensions.items():
            metric_dims.append({"Name": k, "Value": str(v)})
    try:
        cloudwatch.put_metric_data(
            Namespace="NoShowScorer",
            MetricData=[{
                "MetricName": metric_name,
                "Value":      value,
                "Unit":       "Count",
                "Dimensions": metric_dims,
            }],
        )
    except Exception as ex:
        # Metric emission failures must never take down the scoring path.
        logger.warning("metric_emit_failed", extra={"metric": metric_name, "error": str(ex)})
```

---

## Step 4: Execute Interventions

*The pseudocode calls this `execute_outreach(intervention)`. The outreach Lambda picks up each item in the intervention queue, selects a channel based on the patient's preferences with a fallback ladder, sends the message via Pinpoint, and writes a record to the intervention log so the feedback loop can later separate "the patient would have shown anyway" from "the patient showed because we called them."*

```python
def execute_outreach(queue_item: dict, patient_preferences: dict) -> dict:
    """
    Execute an outbound intervention for one appointment.

    `queue_item` is the dict written to INTERVENTION_QUEUE_TABLE by the
    router. `patient_preferences` is a dict describing the patient's
    channel preferences and addresses (phone, email, preferred language).
    In production, patient_preferences comes from a canonical patient-
    preference store; Recipe 4.1 treats that infrastructure in depth.

    Returns an intervention record describing what was attempted.
    """
    intervention_id = str(uuid.uuid4())
    channels = _pick_channels(patient_preferences)

    attempts = []
    for channel in channels:
        try:
            if channel == "sms":
                _send_sms_reminder(queue_item, patient_preferences, intervention_id)
            elif channel == "voice":
                _send_voice_reminder(queue_item, patient_preferences, intervention_id)
            elif channel == "email":
                _send_email_reminder(queue_item, patient_preferences, intervention_id)
            attempts.append({"channel": channel, "status": "sent"})
            # Break on first successful send. A real policy may continue
            # through all preferred channels; keep it simple for the example.
            break
        except pinpoint.exceptions.BadRequestException as ex:
            # Invalid destination (disconnected number, malformed email).
            # Log the failure and try the next channel.
            attempts.append({"channel": channel, "status": "failed", "error": str(ex)})
            logger.warning("outreach_channel_failed", extra={
                "intervention_id": intervention_id,
                "channel":         channel,
            })
            continue

    record = {
        "intervention_id":       intervention_id,
        "appointment_id":        queue_item["appointment_id"],
        "patient_id":            queue_item["patient_id"],
        "intervention_type":     "outbound_reminder",
        "channels_attempted":    attempts,
        "executed_at":           datetime.now(timezone.utc).isoformat(),
        "executed_by":           "pinpoint_automation",
        "scorer_version":        queue_item["scorer_version"],
        "risk_score_at_decision": queue_item["risk_score"],
    }

    dynamodb.Table(INTERVENTION_LOG_TABLE).put_item(Item=record)

    _emit_metric("intervention_executed", dimensions={
        "channel": attempts[-1]["channel"] if attempts else "none",
        "status":  attempts[-1]["status"] if attempts else "none",
    })

    return record

def _pick_channels(preferences: dict) -> list:
    """
    Determine which channels to try and in what order. Patient preference
    overrides the default ladder; opt-outs are removed entirely. A production
    implementation also honors quiet-hours windows and regulatory constraints
    on SMS/voice contact frequency (TCPA, state-specific rules).
    """
    preferred = preferences.get("preferred_channels") or DEFAULT_CHANNEL_LADDER
    opt_outs = set(preferences.get("opt_outs") or [])
    return [c for c in preferred if c not in opt_outs]

def _send_sms_reminder(queue_item: dict, prefs: dict, intervention_id: str) -> None:
    """
    Send an SMS reminder via Pinpoint. The message body intentionally
    omits clinical detail; an SMS is effectively unencrypted in transit
    over the carrier network. "Your appointment tomorrow at 9 AM" is
    acceptable; "Your oncology follow-up tomorrow" is not.
    """
    destination = prefs["phone_number"]
    body = _build_sms_body(queue_item, prefs)

    pinpoint.send_messages(
        ApplicationId=PINPOINT_APPLICATION_ID,
        MessageRequest={
            "Addresses": {destination: {"ChannelType": "SMS"}},
            "MessageConfiguration": {
                "SMSMessage": {
                    "Body":        body,
                    "MessageType": "TRANSACTIONAL",
                },
            },
            # The Context field is surfaced on delivery receipt events so
            # the outcome-joiner can tie a delivery back to a specific
            # intervention without parsing the message body.
            "Context": {"intervention_id": intervention_id},
        },
    )

def _send_voice_reminder(queue_item: dict, prefs: dict, intervention_id: str) -> None:
    """
    Send a voice reminder via Pinpoint. Voice messages carry the same
    minimum-PHI rule as SMS: appointment time and clinic name, not visit
    reason. The SSML payload is built by a separate template function.
    """
    pinpoint.send_messages(
        ApplicationId=PINPOINT_APPLICATION_ID,
        MessageRequest={
            "Addresses": {prefs["phone_number"]: {"ChannelType": "VOICE"}},
            "MessageConfiguration": {
                "VoiceMessage": {
                    "Body":                 _build_voice_ssml(queue_item, prefs),
                    "OriginationNumber":    PINPOINT_VOICE_LONG_CODE,
                    "LanguageCode":         prefs.get("language_code", "en-US"),
                    "VoiceId":              "Joanna",
                },
            },
            "Context": {"intervention_id": intervention_id},
        },
    )

def _send_email_reminder(queue_item: dict, prefs: dict, intervention_id: str) -> None:
    """
    Send an email reminder via Pinpoint. Email can carry slightly more
    detail than SMS/voice when delivered over TLS to a verified address,
    but still follow minimum-necessary principles for the visit description.
    """
    pinpoint.send_messages(
        ApplicationId=PINPOINT_APPLICATION_ID,
        MessageRequest={
            "Addresses": {prefs["email"]: {"ChannelType": "EMAIL"}},
            "MessageConfiguration": {
                "EmailMessage": {
                    "SimpleEmail": {
                        "Subject":     {"Charset": "UTF-8", "Data": "Appointment Reminder"},
                        "HtmlPart":    {"Charset": "UTF-8", "Data": _build_email_html(queue_item, prefs)},
                        "TextPart":    {"Charset": "UTF-8", "Data": _build_email_text(queue_item, prefs)},
                    },
                    "FromAddress": "reminders@example.com",
                },
            },
            "Context": {"intervention_id": intervention_id},
        },
    )

def _build_sms_body(queue_item: dict, prefs: dict) -> str:
    """Minimal-PHI SMS body. In production this is template-driven and localized."""
    return (
        "Reminder: you have an appointment tomorrow. "
        "Reply Y to confirm, N to cancel, or call your clinic to reschedule."
    )

def _build_voice_ssml(queue_item: dict, prefs: dict) -> str:
    """Minimal-PHI voice SSML. Template-driven and localized in production."""
    return (
        "<speak>Hello. This is a courtesy reminder of your appointment tomorrow. "
        "Please press 1 to confirm, 2 to cancel, or stay on the line to speak with "
        "a scheduler.</speak>"
    )

def _build_email_html(queue_item: dict, prefs: dict) -> str:
    """Minimal-PHI email body. Template-driven in production."""
    return (
        "<p>Reminder: your appointment is scheduled for tomorrow.</p>"
        "<p>Use our patient portal to confirm or reschedule.</p>"
    )

def _build_email_text(queue_item: dict, prefs: dict) -> str:
    return (
        "Reminder: your appointment is scheduled for tomorrow.\n"
        "Use our patient portal to confirm or reschedule."
    )
```

---

## Step 5: Capture Outcomes and Close the Loop

*The pseudocode calls this `on_appointment_outcome(event)`. When the EHR records an outcome (showed, no-show, late-cancelled, rescheduled), an event flows to EventBridge; a Lambda consumer pulls the original prediction, joins any intervention records, writes the labeled training row, and updates the patient's rolling baseline.*

The label derivation is the contentious bit. See "The Label Problem" in the main recipe for the discussion on late arrivals, same-day cancellations, reschedules, and walk-in-later scenarios. The simple version below codes "no-show" and "late_cancellation" as positives; the important property is that the definition is stable across the training window, not that it is clever.

```python
def on_appointment_outcome(event: dict) -> None:
    """
    Consumer for appointment-outcome events. Builds the training row,
    updates the patient's rolling baseline, and writes both artifacts
    durably. Any failure before both writes succeed must be retryable.
    """
    appointment_id = event["appointment_id"]

    # --- Pull the original prediction ---
    pred_response = dynamodb.Table(PREDICTIONS_ARCHIVE_TABLE).get_item(
        Key={"appointment_id": appointment_id},
    )
    prediction = pred_response.get("Item")
    if not prediction:
        # Outcome arrived for an appointment we never scored (edge case:
        # appointment was booked after the nightly scoring cutoff).
        # Record the outcome but skip label generation.
        logger.info("outcome_without_prediction", extra={"appointment_id": appointment_id})
        _update_patient_baseline(event["patient_id"], event["outcome"])
        return

    # --- Find any interventions for this appointment ---
    interventions = _query_interventions_for_appointment(appointment_id)

    # --- Derive the training label ---
    label = _derive_label(
        outcome=event["outcome"],
        actual_arrival_time=event.get("actual_arrival_time"),
        scheduled_time=prediction["scheduled_time"],
    )

    # --- Write the training row ---
    training_row = {
        "appointment_id":           appointment_id,
        "patient_id":               prediction["patient_id"],
        "scored_at":                prediction["scored_at"],
        "outcome_recorded_at":      event["outcome_recorded_at"],
        "features_snapshot":        _decimal_to_jsonable(prediction["features_snapshot"]),
        "risk_score_at_scoring":    float(prediction["risk_score"]),
        "scorer_version":           prediction["scorer_version"],
        "interventions_applied":    [i["intervention_type"] for i in interventions],
        "intervention_count":       len(interventions),
        "label":                    label,
        "label_derivation_version": LABEL_DERIVATION_VERSION,
    }

    _write_label_to_s3(training_row, event["outcome_recorded_at"])

    # --- Update the patient baseline ---
    _update_patient_baseline(prediction["patient_id"], event["outcome"])

    # --- Metrics for the operational dashboard ---
    _emit_metric("outcome_recorded", dimensions={"label": label})
    _emit_metric("intervention_outcome", dimensions={
        "label":       label,
        "intervened":  "yes" if interventions else "no",
    })

def _derive_label(outcome: str, actual_arrival_time: Optional[str], scheduled_time: str) -> str:
    """
    Map raw EHR outcomes to the training label schema. See the main
    recipe's "Label Problem" section for the full rationale.

    Simple decision rules:
      "completed"  -> "showed"
      "arrived_late":
          within 15 min       -> "showed" (grace window)
          later               -> "late_arrival_accepted"
      "no_show"    -> "no_show"
      "cancelled_same_day"    -> "late_cancellation"
      "rescheduled" with >24h lead -> "rescheduled_with_lead_time"
      otherwise -> "late_cancellation"
    """
    if outcome == "completed":
        if actual_arrival_time:
            arrival = datetime.fromisoformat(actual_arrival_time)
            scheduled = datetime.fromisoformat(scheduled_time)
            delay_minutes = (arrival - scheduled).total_seconds() / 60.0
            if delay_minutes > 15:
                return "late_arrival_accepted"
        return "showed"
    if outcome == "no_show":
        return "no_show"
    if outcome == "cancelled_same_day":
        return "late_cancellation"
    if outcome == "rescheduled":
        # Reschedules with good lead time are a separate cohort; short-
        # lead-time reschedules count as late cancellations.
        return "rescheduled_with_lead_time"
    # Conservative default for anything unexpected.
    return "late_cancellation"

def _update_patient_baseline(patient_id: str, outcome: str) -> None:
    """
    Update the rolling no-show rate with exponential decay. The baseline
    is how the anomaly-detection framing computes the patient-specific
    deviation score during routing.

    This is a read-modify-write. In a high-throughput system, protect
    against concurrent updates with an optimistic-lock attribute
    (`version` field + ConditionExpression). Simpler version shown here.
    """
    is_positive = outcome in {"no_show", "cancelled_same_day"}
    table = dynamodb.Table(PATIENT_BASELINES_TABLE)

    current = table.get_item(Key={"patient_id": patient_id}).get("Item")
    if current:
        prior_rate = _to_decimal(current["rolling_no_show_rate"])
        observation_count = int(current.get("observation_count", 0))
    else:
        # Seed the baseline with the cohort prior so the first update
        # moves from a defensible starting point rather than zero.
        prior_rate = POPULATION_PRIOR_NO_SHOW_RATE
        observation_count = 0

    new_rate = (Decimal("1.0") - BASELINE_ALPHA) * prior_rate + BASELINE_ALPHA * (
        Decimal("1.0") if is_positive else Decimal("0.0")
    )

    table.put_item(Item={
        "patient_id":           patient_id,
        "rolling_no_show_rate": _to_decimal(new_rate),
        "observation_count":    observation_count + 1,
        "last_updated_at":      datetime.now(timezone.utc).isoformat(),
    })

def _query_interventions_for_appointment(appointment_id: str) -> list:
    """
    Return every intervention recorded for the given appointment.
    The intervention-log table has a GSI on appointment_id (partition key)
    exactly for this query pattern.
    """
    table = dynamodb.Table(INTERVENTION_LOG_TABLE)
    response = table.query(
        IndexName="appointment_id_index",
        KeyConditionExpression=Key("appointment_id").eq(appointment_id),
    )
    return response.get("Items", [])

def _write_label_to_s3(training_row: dict, outcome_recorded_at: str) -> None:
    """
    Append the labeled training row to the labels S3 bucket, partitioned
    by date. In production we write Parquet (better compression, columnar
    access for Athena); JSON here for clarity.
    """
    recorded_dt = datetime.fromisoformat(outcome_recorded_at)
    key = (
        f"labels/year={recorded_dt.year:04d}/month={recorded_dt.month:02d}/"
        f"day={recorded_dt.day:02d}/{uuid.uuid4()}.json"
    )
    s3_client.put_object(
        Bucket=LABELS_BUCKET,
        Key=key,
        Body=json.dumps(training_row, default=str).encode("utf-8"),
        ContentType="application/json",
        # Customer-managed KMS key required for anything carrying PHI.
        ServerSideEncryption="aws:kms",
    )

def _decimal_to_jsonable(value):
    """Recursively coerce Decimals to floats for JSON output."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _decimal_to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimal_to_jsonable(v) for v in value]
    return value
```

---

## The Full Nightly Pipeline

Here is the end-to-end `run_nightly_scoring` function that wires all five steps together. In production this is the body of a Step Functions state machine with each stage as a separate task; the Python version collapses them into a single driver for teaching.

```python
def run_nightly_scoring(upcoming_appointments: list) -> list:
    """
    Score tomorrow's schedule and populate the intervention and
    investigation queues.

    Input: list of appointment dicts from the nightly EHR export.
    Output: list of routing decisions.
    """
    print(f"[1/4] Assembling features for {len(upcoming_appointments)} appointments...")
    feature_records = [assemble_features(a) for a in upcoming_appointments]

    print(f"[2/4] Scoring with {SCORER_VERSION}...")
    predictions = []
    for features in feature_records:
        pred = score_appointment(features)
        archive_prediction(features, pred)
        predictions.append(pred)

    print("[3/4] Computing baseline deviations and routing...")
    decisions = route_predictions(predictions)

    print("[4/4] Summary:")
    counts = {}
    for d in decisions:
        counts[d["action"]] = counts.get(d["action"], 0) + 1
    for action, count in counts.items():
        print(f"       {action}: {count}")

    return decisions

# --- Example usage ---
#
# A minimal example appointment batch shaped like what a normalized EHR
# export would produce. Values are synthetic and do not refer to any real
# person, provider, or service. Use Synthea in a development environment;
# never use real PHI in a teaching example.
if __name__ == "__main__":
    sample_appointments = [
        {
            "appointment_id":   "APT-2026-0050123",
            "patient_id":       "PAT-00441297",
            "scheduled_time":   "2026-05-14T09:00:00",
            "scheduled_at":     "2026-04-02T14:15:00",     # 6-week lead time
            "provider_id":      "PRV-0172",
            "clinic_id":        "CLN-03",
            "visit_type":       "primary-care-followup",
            "reschedule_count": 0,
        },
        {
            "appointment_id":   "APT-2026-0050998",
            "patient_id":       "PAT-00301105",
            "scheduled_time":   "2026-05-14T16:30:00",
            "scheduled_at":     "2026-03-31T10:00:00",     # 6-week lead time
            "provider_id":      "PRV-0084",
            "clinic_id":        "CLN-07",
            "visit_type":       "cardiology-new",
            "reschedule_count": 1,                         # rescheduled once
        },
    ]

    decisions = run_nightly_scoring(sample_appointments)
    print()
    print("=== DECISIONS ===")
    print(json.dumps([
        {
            "appointment_id": d["appointment_id"],
            "risk_score":     str(d["risk_score"]),
            "baseline_rate":  str(d["baseline_rate"]) if d["baseline_rate"] is not None else None,
            "deviation":      str(d["deviation"]),
            "action":         d["action"],
            "reason":         d["reason"],
        } for d in decisions
    ], indent=2))
```

Running this against empty DynamoDB tables and with a freshly-trained model will route appointments based purely on the absolute risk score; the deviation path activates once patient baselines accumulate through the outcome loop.

---

## A Sketch of the Monthly Retrain

The main recipe's `retrain_monthly` function is not fully implemented here because a production retrain is a SageMaker Training Job plus a feature-engineering pipeline plus a model-registry update plus subgroup evaluation, and each is a multi-hundred-line block that does not teach anything specific to no-show detection. What follows is the shape of the job so you can see what the label-writer code above is ultimately feeding.

```python
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

def retrain_monthly(training_window_days: int = 365) -> dict:
    """
    Retrain the no-show classifier from the rolling window of labels.

    This function stays in-process for the teaching example. In production,
    the same logic runs as a SageMaker Training Job: the label S3 prefix
    becomes the training input channel, the fitted artifact goes to the
    model registry, and subgroup evaluation is gated by a model-approval
    step before the endpoint update.
    """
    # 1. Pull the labeled training data from S3. In production this is an
    #    Athena query against the labels Parquet lake; here we glob the
    #    JSON files for simplicity.
    training_df = _load_labels(training_window_days)

    # 2. Exclude appointments that received interventions; see "The
    #    Feedback Loop" in the main recipe for why naive inclusion causes
    #    the model to progressively downweight the features that correctly
    #    identified risk.
    training_df = training_df[training_df["intervention_count"] == 0].copy()

    # 3. Build X, y. Positive class = "no-show" or "late_cancellation".
    training_df["label_positive"] = training_df["label"].isin(POSITIVE_LABELS).astype(int)
    X = pd.json_normalize(training_df["features_snapshot"])
    y = training_df["label_positive"].values

    # 4. Patient-stratified split. A patient appears in exactly one of
    #    train or val; prevents leakage where the same patient is on both
    #    sides (which would flatter the AUC in ways that do not hold up
    #    on unseen patients).
    train_idx, val_idx = _patient_stratified_split(training_df["patient_id"].values, test_size=0.2)
    X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
    y_train, y_val = y[train_idx], y[val_idx]

    # 5. Fit the sklearn Pipeline. The ColumnTransformer handles numeric
    #    scaling and categorical one-hot encoding with the same feature
    #    schema the scorer will see at serving time.
    numeric_cols = [c for c in FEATURE_COLUMNS]
    preprocessor = ColumnTransformer([
        ("num", StandardScaler(), numeric_cols),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_COLUMNS),
    ])
    pipeline = Pipeline([
        ("prep", preprocessor),
        ("clf", LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced")),
    ])
    pipeline.fit(X_train, y_train)

    # 6. Evaluate. The overall AUC is the headline metric; subgroup AUC
    #    is the required precondition for promotion.
    y_val_pred = pipeline.predict_proba(X_val)[:, 1]
    overall_auc = roc_auc_score(y_val, y_val_pred)

    subgroup_auc = _evaluate_subgroups(pipeline, X_val, y_val, training_df.iloc[val_idx])

    # 7. Promotion gate. Only ship if overall AUC beats the incumbent
    #    AND no subgroup regresses materially. Numerical thresholds here
    #    are placeholders; tune against your own floor.
    incumbent = _fetch_incumbent_metrics()
    if (overall_auc > incumbent.get("auc", 0.0) + 0.005
            and _no_subgroup_regression(subgroup_auc, incumbent.get("subgroup_auc", {}))):
        _publish_model(pipeline, overall_auc, subgroup_auc)
        return {"promoted": True, "auc": overall_auc}

    return {"promoted": False, "auc": overall_auc, "reason": "failed_gate"}

def _patient_stratified_split(patient_ids, test_size=0.2):
    """Split row indices such that each patient appears in exactly one split."""
    unique = np.array(sorted(set(patient_ids)))
    np.random.shuffle(unique)
    cutoff = int(len(unique) * (1 - test_size))
    train_patients = set(unique[:cutoff])
    train_idx = [i for i, p in enumerate(patient_ids) if p in train_patients]
    val_idx = [i for i, p in enumerate(patient_ids) if p not in train_patients]
    return train_idx, val_idx

def _evaluate_subgroups(pipeline, X_val, y_val, val_meta) -> dict:
    """
    Compute AUC by subgroup. Subgroups are defined by the columns your
    equity team decides are in scope; insurance type and age band are
    common starting points when race/ethnicity data quality is insufficient
    for reliable subgroup analysis.
    """
    results = {}
    for column in ["insurance_type", "age_band"]:
        if column not in val_meta.columns:
            continue
        for value, mask in val_meta.groupby(column).groups.items():
            group_idx = [i for i in range(len(val_meta)) if val_meta.iloc[i].name in mask]
            if len(group_idx) < 30:
                # Too few samples for a reliable subgroup AUC; skip.
                continue
            preds = pipeline.predict_proba(X_val.iloc[group_idx])[:, 1]
            results[f"{column}={value}"] = roc_auc_score(y_val[group_idx], preds)
    return results

def _no_subgroup_regression(new_subgroups: dict, incumbent_subgroups: dict, tolerance: float = 0.02) -> bool:
    """
    Promotion is blocked if any subgroup regresses by more than `tolerance`
    AUC points compared to the incumbent. This is the fairness gate.
    """
    for group, new_auc in new_subgroups.items():
        incumbent_auc = incumbent_subgroups.get(group)
        if incumbent_auc is None:
            continue
        if incumbent_auc - new_auc > tolerance:
            return False
    return True

def _publish_model(pipeline, overall_auc, subgroup_auc):
    """Serialize the pipeline to S3 and update the 'current' pointer."""
    buf = io.BytesIO()
    joblib.dump({
        "pipeline": pipeline,
        "meta": {
            "version":      SCORER_VERSION,
            "trained_at":   datetime.now(timezone.utc).isoformat(),
            "overall_auc":  float(overall_auc),
            "subgroup_auc": subgroup_auc,
        },
    }, buf)
    buf.seek(0)
    version_key = f"versions/{SCORER_VERSION}/model.joblib"
    s3_client.put_object(
        Bucket=MODEL_ARTIFACTS_BUCKET,
        Key=version_key,
        Body=buf.read(),
        ServerSideEncryption="aws:kms",
    )
    # In production, register in the SageMaker Model Registry and promote
    # via a deployment pipeline rather than copying over 'current' directly.
    s3_client.copy_object(
        Bucket=MODEL_ARTIFACTS_BUCKET,
        Key="current/model.joblib",
        CopySource={"Bucket": MODEL_ARTIFACTS_BUCKET, "Key": version_key},
        ServerSideEncryption="aws:kms",
    )

def _load_labels(training_window_days: int) -> pd.DataFrame:
    """
    Load labels from S3 for the training window. Placeholder; in production,
    run an Athena query against the labels Parquet lake with partition
    pruning on year/month/day.
    """
    # TODO: replace with Athena query or S3 select against Parquet archive.
    return pd.DataFrame()

def _fetch_incumbent_metrics() -> dict:
    """Load incumbent model metrics from the model registry."""
    try:
        response = s3_client.get_object(Bucket=MODEL_ARTIFACTS_BUCKET, Key="current/metadata.json")
        return json.loads(response["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        return {"auc": 0.0, "subgroup_auc": {}}
```

---

## Gap to Production

Several things would need to change before you would deploy any of this.

**Real EHR integration.** The nightly scoring pipeline starts from a list of appointment dicts that looks like a normalized export. In production, the export itself is a Glue job reading from the EHR's analytical mirror (Epic Clarity, Cerner HealtheIntent, or an equivalent data warehouse tap) plus incremental updates throughout the day as appointments are booked, cancelled, or rescheduled. Timezone handling is a classic bug farm; always store UTC and render local time only at display. Budget weeks for this integration, not days.

**Idempotency.** The scoring and outcome-joiner paths write unconditionally. In production, S3 events may deliver the same object more than once (at-least-once semantics) and Step Functions tasks may retry after transient failures. Use DynamoDB `ConditionExpression` with `attribute_not_exists(appointment_id)` on prediction writes to make them idempotent, and handle the `ConditionalCheckFailedException` as success. Outcome updates need an optimistic-lock attribute (version counter + ConditionExpression) so concurrent outcome events for the same patient do not corrupt the rolling baseline.

**Error handling.** The example's error handling is minimal. In production, wrap each external call in try/except with structured logging, emit a failure metric, and route the appointment to a dead-letter queue for operations review. Do not silently swallow DynamoDB throttling, Pinpoint send failures, or S3 access-denied errors; each is a different class of problem with a different mitigation.

**Structured logging with PHI discipline.** The `logger.info` calls above log structural metadata only (appointment IDs, queue actions, channel names). In production, use a JSON log formatter, ship logs to CloudWatch Logs with a log group encrypted by a customer-managed KMS key, and audit log content with a regular scan for unexpected PHI patterns (patient names, DOB-looking strings, diagnosis codes). A single accidental `logger.info("features: %s", features)` call during debugging can create a PHI disclosure that survives in CloudWatch until your retention policy clears it.

**IAM scoping.** The permissions list in the Setup section covers what this code does, but production roles are scoped tightly. The feature-assembly Lambda's role needs no Pinpoint permissions. The router Lambda's role needs no training-data write permissions. The outreach Lambda's role needs no Feature Store read permissions. Scope to specific resource ARNs rather than service-level wildcards and review the roles annually.

**VPC deployment.** In production, Lambdas run inside a VPC with VPC endpoints for DynamoDB, S3, SageMaker Runtime, Feature Store Runtime, EventBridge, KMS, and CloudWatch Logs. The SageMaker Batch Transform jobs run in the same VPC. Pinpoint is a managed edge service and does not run in a VPC; ensure the data flowing to Pinpoint is the minimum needed for the message (appointment time, clinic name, confirm/cancel prompt), not the patient's full record.

**KMS customer-managed keys.** All data at rest (DynamoDB tables, S3 buckets, Feature Store offline/online, CloudWatch Logs) is encrypted with customer-managed KMS keys. The key policy restricts usage to the specific roles that need it; audit who is using each key via CloudTrail data events.

**SageMaker wrapping for the scorer.** The scikit-learn in-process scorer here is for teaching. Production deployments wrap the same model in a SageMaker Batch Transform job for nightly scoring (spin up, score, shut down, no always-on cost) or a real-time endpoint for booking-time scoring. The model code is identical; the infrastructure wrapping is what SageMaker provides. Model version tagging, endpoint update safety (canary or blue-green), and model-monitor drift detection come along for free.

**SageMaker Feature Store, not stubbed.** The `_get_patient_features` function uses the Feature Store runtime client correctly; the cold-start default returns a neutral vector so the example runs even without Feature Store populated. In production, populate the patient-features feature group from the nightly warehouse export, and let the scorer rely on it; cold-start should hit a cohort-prior lookup, not a single population prior.

**Pinpoint configuration.** Pinpoint requires specific configuration to remain HIPAA-compliant: SMS carrier routing with dedicated short codes (not shared), voice origination numbers registered for the relevant regulatory regimes, TLS for email, and opt-out handling that respects TCPA and state-specific rules. Review the Pinpoint service-level compliance documentation before going live. The example code ignores all of this; consider it illustrative only for the message-sending shape.

**Patient preference storage.** The `execute_outreach` function takes a `patient_preferences` dict as input. In production that dict comes from a canonical patient-preference store that consolidates preferences from the EHR, CRM, and portal opt-ins into a single queryable record. Recipe 4.1 treats that infrastructure in depth; reference it rather than rebuilding it from scratch here.

**Monitoring and alarms.** The `_emit_metric` function drops metrics into CloudWatch. Production requires CloudWatch alarms on top: prediction distribution drift beyond a configurable floor, intervention-queue depth outside target range, no metrics emitted for 30 minutes, Pinpoint send-failure rate above threshold. Wire alarms to SNS topics that page the on-call.

**Subgroup fairness monitoring.** The `retrain_monthly` sketch includes subgroup AUC as a promotion gate. Production also needs an ongoing dashboard that tracks subgroup performance on predictions made in the current week, subgroup intervention rates, and subgroup outcome improvement. QuickSight over an Athena view on the labels bucket is the simplest pattern; make this part of the operations dashboard, not a nice-to-have.

**Intervention effect measurement.** The model answers "who is likely to no-show." It does not answer "did the outreach change the outcome." Measuring intervention effect requires either a randomized holdout (some high-risk appointments randomly not intervened on) or a matched-pair quasi-experimental design. Budget for this analysis explicitly; it is how you justify the program to finance and how you detect when the interventions stop working as patient behavior adapts.

**Appeal and override workflow.** Sometimes the operations team will want to override the model ("do not call this patient, we already reached them yesterday"). Provide an override mechanism that records who overrode, when, and why. Overrides are training data in their own right; patterns in override behavior are a signal that the model or thresholds need adjustment.

**Retention and legal hold.** The `predictions-archive`, `intervention-log`, and labels S3 bucket all carry PHI. Apply retention policies that match HIPAA baseline (6 years) and extend for legal holds when required. Use S3 Object Lock in COMPLIANCE mode for the labels bucket in production; GOVERNANCE is fine for dev/test so you can clean up.

**Testing.** A real codebase has unit tests for every derivation function (label derivation for the full outcome matrix, baseline update math, deviation computation, routing-threshold edges), integration tests for the full pipeline against DynamoDB Local and Pinpoint mocks, and property-based tests on the scorer (probability in [0, 1], monotonicity properties where applicable). Add golden-path regression tests that run on every retrain so a model that silently breaks a subgroup does not slip through.

**Decimal serialization.** The example code serializes `Decimal` to strings for JSON payloads. In production, use a single consistent custom JSON encoder across the entire codebase so the boundary between Python-side math (Decimal) and JSON-side representation (string) is explicit. Mixing `default=str` in one place and a custom encoder in another is a subtle source of bugs that show up as rounding drift months later.

None of this is unique to no-show prediction. It is the cost of running any PHI-handling prediction service in production. The good news: once you have the infrastructure for one pattern (this one), it amortizes across Recipe 4.1 (channel optimization), Recipe 4.5 (adherence targeting), Recipe 7.4 (readmission risk), and the other patient-engagement recipes that share this architecture.

---

*← [Main Recipe 3.2](chapter03.02-patient-no-show-pattern-detection) · [Chapter 3 Preface](chapter03-preface)*
