# Recipe 3.8: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 3.8. It shows one way you could translate the post-discharge readmission-risk anomaly-detection pattern into working Python using Amazon API Gateway plus AWS Lambda (for RPM device webhooks), Amazon Kinesis (for the canonical patient-event stream), Amazon DynamoDB (for the patient-state and worklist-state stores), Amazon Timestream (for the trajectory history of weights, blood pressures, glucoses, and symptom scores), Amazon SageMaker (for the composite anomaly model endpoint, Feature Store, and Clarify SHAP explanations), Amazon Bedrock (for outreach-narrative generation), Amazon EventBridge (for scoring and worklist fan-out), Amazon OpenSearch Service (for the worklist audit index), Amazon S3 (for the raw-event lake and training labels), and Amazon CloudWatch (for operational metrics). It is not production-ready. There is no real RPM-vendor webhook validator (BodyTrace, A&D Medical, iHealth, Withings each have their own signature schemes), no FHIR R4 ingestion for the EHR feed (HL7 ADT, ORU, encounter resources), no HIE or claims integration, no care-management workflow integration (Salesforce Health Cloud, Epic Healthy Planet, Innovaccer), no SMS or IVR patient-communication vendor wiring, and no Step Functions retraining orchestration. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you would wire into a hospital's transitions-of-care workflow next week.
>
> The code maps to the eight core pseudocode steps from the main recipe: enroll a patient at discharge, ingest RPM measurements and patient-reported outcomes, update the patient-state store and trajectory history, run the daily scoring pipeline, compute the feature vector with patient-specific baselines and cohort priors for cold-start, score the feature vector and apply calibration plus tier assignment, build the per-prediction explanation (SHAP plus Bedrock outreach narrative), build the worklist with suppression and de-duplication, and capture interventions plus eventual outcomes for the retraining loop. The LSTM/transformer time-series variant, the closed-loop pharmacist-titration extension, the conversational-AI patient check-in path, and the multi-cohort orchestration layer are not in this file; they are covered in the Variations and Why-This-Isn't-Production-Ready sections of the main recipe and share infrastructure with other chapter recipes (3.5 for lab features, 3.7 for the inpatient-deterioration analog, 12.x for time-series modeling, 2.x for LLM-assisted explanations).

---

## Setup

You will need the AWS SDK for Python plus scikit-learn, pandas, numpy, and joblib for the local demonstration model:

```bash
pip install boto3 scikit-learn pandas numpy joblib
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the `patient-state`, `worklist-state`, `scoring-history`, and `intervention-history` tables
- `dynamodb:DescribeStream`, `dynamodb:GetRecords`, `dynamodb:GetShardIterator`, `dynamodb:ListStreams` on the `patient-state` stream (for event-driven re-scoring on urgent events like ED visits)
- `kinesis:PutRecord`, `kinesis:PutRecords`, `kinesis:GetRecords`, `kinesis:GetShardIterator` on the `patient-events` stream
- `timestream:WriteRecords` on the `post-discharge` database, `timestream:Select` on the `rpm_measurements` and `pro_symptom_scores` tables
- `s3:GetObject` on the model-artifacts bucket; `s3:PutObject` on the raw-events lake and training-labels buckets
- `sagemaker-runtime:InvokeEndpoint` on the readmission anomaly model endpoint ARN
- `sagemaker-featurestore-runtime:GetRecord`, `sagemaker-featurestore-runtime:PutRecord` on the `post-discharge-features-online` feature group
- `bedrock:InvokeModel` on the specific Bedrock model ARN you use (scope tightly; do not use `bedrock:*`)
- `events:PutEvents` on the `post-discharge-scoring` and `post-discharge-events` buses
- `cloudwatch:PutMetricData` for operational metrics
- The OpenSearch domain policy must allow the executing role to `es:ESHttpPost` and `es:ESHttpPut` on the `worklist-index`, `scoring-index`, and `intervention-index` indices

Scope each role to the specific resource ARNs it touches. The permissions above are fine for learning and will fail any serious IAM review. In production, each component (device-ingest Lambda, ehr-event-ingest Lambda, enrollment-handler Lambda, event-normalizer Lambda, feature-engine Lambda, scoring-orchestrator Lambda, explanation-builder Lambda, worklist-builder Lambda, intervention-capture Lambda, outcome-capture Lambda, retraining Step Functions workflow) gets its own role with the minimum permissions for its job.

A few things worth knowing upfront:

- **No real RPM-vendor webhook validation.** Production validates HMAC signatures (BodyTrace, A&D Medical), JWT tokens (Withings), or vendor-specific schemes per vendor before parsing the payload. The vendor's documentation and the BAA agreement spell out the validation rules. Skipping validation is how you end up ingesting payloads from anyone on the internet who finds your webhook URL. This example accepts an already-validated payload as a Python dict.
- **No FHIR R4 ingestion or HL7 v2 parsing.** EHR-side events (ED visits, post-discharge clinic visits, refills, orders) flow in via FHIR Observation, Encounter, MedicationDispense, and ServiceRequest resources, plus HL7 v2 ADT for admissions. Use a maintained library (`fhir.resources` or `python-hl7`) and a real integration engine (Mirth, Rhapsody, Cloverleaf, or a vendor-supplied platform). The teaching example accepts a pre-shaped event dict.
- **No HIE or claims integration.** External-facility readmissions live in your regional HIE (where it exists) or the ACO/value-based-care claims feed (where you have one). Both involve contract-specific data-sharing agreements and per-region integration engineering. The example assumes only your own EHR feed plus RPM and PRO data.
- **No care-management workflow integration.** Salesforce Health Cloud, Epic Healthy Planet, Innovaccer, Lumeris, ZeOmega Jiva, and Lightbeam each have their own API patterns and data models. The example writes the worklist to DynamoDB and OpenSearch and calls it done; production publishes to whichever care management tool the program actually runs on.
- **DynamoDB table schemas.** `patient-state` is keyed on `patient_id` (partition) and `encounter_id` (sort), with a global secondary index on `is_active` for the daily-scoring sweep and DynamoDB Streams enabled for urgent-event re-scoring. `scoring-history` is keyed on `patient_id` (partition) and `scored_at` (sort) with a TTL attribute for automatic expiration after the audit retention window. `worklist-state` is keyed on `worklist_id` (partition only). `intervention-history` is keyed on `patient_id` (partition) and `occurred_at` (sort). You create these once, up front; this file does not do that for you.
- **All numeric values must be Decimal going into DynamoDB.** DynamoDB rejects Python `float` for numeric attributes. A weight of `198.4` becomes `Decimal("198.4")` on the way in and back to float on the way out. The helper functions below handle this so you see the pattern. For a readmission-anomaly pipeline this matters operationally: a calibrated probability stored as `0.5999999999` from float drift, compared against a `0.60` tier-1 cut, produces the wrong outreach intensity today and might produce the right one tomorrow if the threshold moves. That kind of drift is exactly the bug class clinical safety review will flag.
- **All example patient, vital, lab, and care-management data is synthetic.** Patient IDs, encounter IDs, NPIs, and device IDs in the sample data are illustrative and do not refer to any real people, providers, or facilities. LOINC codes for the tracked metrics (29463-7 body weight, 8480-6 systolic BP, 8462-4 diastolic BP, 2708-6 oxygen saturation, 2345-7 glucose, 33452-4 peak flow) are real LOINC identifiers used as the canonical metric codes. Use [Synthea](https://github.com/synthetichealth/synthea) for synthetic discharge-and-readmission events in development. Never use real PHI in a teaching example.
- **The model in this example is a tiny in-process scikit-learn model.** Real deployments host the model behind a SageMaker batch transform pipeline (daily cadence) or a real-time endpoint (event-driven re-scoring). We train a logistic regression on a small synthetic feature matrix at the bottom of the file so the scoring path runs end-to-end without a deployed endpoint. The `score_via_sagemaker_endpoint` function shows the production-shape boto3 call.
- **Calibration is shown as isotonic regression on a small held-out set.** Real calibration uses isotonic or Platt scaling fit on a substantial held-out validation set, then frozen and versioned alongside the model. Calibration drift over time is monitored by SageMaker Model Monitor; this example does not demonstrate that monitoring, only the application of frozen calibration parameters.
- **Outreach-staffing realities are not simulated here.** The main recipe spends a lot of time on capacity-bounded prioritization for good reason. The example code generates a worklist regardless of available care-manager capacity. In production, a capacity-cap step trims the worklist to the top-N rows the team can realistically work, with the next-N rows held in a backlog list that gets re-evaluated tomorrow.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here: thresholds, metric-code maps, baseline-window sizes, resource names, and routing tables. These are the knobs that move most often between dev, test, and production, and between clinical-governance threshold reviews. Keep them at the top of the file so a reviewer can see the levers without wading through function bodies.

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
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression

# Structured logging. Ship JSON records to CloudWatch Logs Insights. Weights,
# blood pressures, symptom scores, patient identifiers, and care-management
# notes are PHI. Log structural metadata only. Never log full measurement
# values with patient identifiers, raw RPM payloads, free-text symptom
# concerns, or full feature vectors in application logs. The audit indexes
# (OpenSearch) and the patient-state store (DynamoDB) are the right home
# for full payloads, behind KMS and CloudTrail data events.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry mode handles throttling across DynamoDB, Timestream,
# Kinesis, SageMaker, and Bedrock with exponential backoff and jitter.
# RPM webhooks are bursty (devices upload at consistent times of day, often
# clustered around morning weigh-ins on weight-tracking programs), and
# adaptive mode keeps burst windows from cascading into retry storms
# against the patient-state cache and the scoring endpoint.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=BOTO3_RETRY_CONFIG)
kinesis = boto3.client("kinesis", region_name=REGION, config=BOTO3_RETRY_CONFIG)
timestream_write = boto3.client("timestream-write", region_name=REGION, config=BOTO3_RETRY_CONFIG)
timestream_query = boto3.client("timestream-query", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch = boto3.client("cloudwatch", region_name=REGION, config=BOTO3_RETRY_CONFIG)
eventbridge = boto3.client("events", region_name=REGION, config=BOTO3_RETRY_CONFIG)
featurestore_runtime = boto3.client(
    "sagemaker-featurestore-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG
)
sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG)
bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill in with your actual resource names. These are placeholders.
PATIENT_STATE_TABLE = "patient-state"
SCORING_HISTORY_TABLE = "scoring-history"
WORKLIST_STATE_TABLE = "worklist-state"
INTERVENTION_HISTORY_TABLE = "intervention-history"

PATIENT_EVENTS_STREAM = "patient-events"
TIMESTREAM_DATABASE = "post-discharge"
TIMESTREAM_RPM_TABLE = "rpm_measurements"
TIMESTREAM_PRO_TABLE = "pro_symptom_scores"

POST_DISCHARGE_FEATURES_FG = "post-discharge-features-online"

RAW_EVENTS_BUCKET = "my-post-discharge-raw-events"
TRAINING_LABELS_BUCKET = "my-post-discharge-training-labels"
MODEL_ARTIFACTS_BUCKET = "my-post-discharge-model-artifacts"

POST_DISCHARGE_SCORING_BUS = "post-discharge-scoring"
POST_DISCHARGE_EVENTS_BUS = "post-discharge-events"
SAGEMAKER_ENDPOINT_NAME = "post-discharge-anomaly-model-prod"
BEDROCK_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

# --- Tracked Metric Codes ---
# LOINC codes are the canonical reference. Real deployments load these from
# a managed reference set rather than hardcoding. Weight, blood pressure,
# oxygen saturation, glucose, and peak flow are the universally-tracked
# RPM modalities for the high-value cohorts (heart failure, hypertension,
# diabetes, COPD).
RPM_LOINC = {
    "WEIGHT":    "29463-7",   # Body weight
    "SBP":       "8480-6",    # Systolic blood pressure
    "DBP":       "8462-4",    # Diastolic blood pressure
    "SPO2":      "2708-6",    # Oxygen saturation
    "GLUCOSE":   "2345-7",    # Glucose
    "PEAK_FLOW": "33452-4",   # Peak expiratory flow rate
    "HR":        "8867-4",    # Heart rate
}
CORE_RPM_KEYS = list(RPM_LOINC.keys())

# Cohort to monitored-modality map. A real program tracks more per cohort
# (heart failure also tracks heart rate and symptom scores; diabetes also
# tracks medication adherence) but this subset is enough to demonstrate
# the cohort-driven feature pipeline.
COHORT_MODALITIES = {
    "heart_failure":   ["WEIGHT", "SBP", "DBP", "HR"],
    "hypertension":    ["SBP", "DBP", "HR"],
    "diabetes":        ["GLUCOSE", "WEIGHT"],
    "copd":            ["PEAK_FLOW", "SPO2", "HR"],
    "post_op_cardiac": ["WEIGHT", "SBP", "DBP", "HR", "SPO2"],
}

# --- Window Sizes ---
# Trajectory features look at recent history; baseline features look at
# the first several days post-discharge. The exact windows are clinical-
# governance decisions and vary by cohort.
TRAJECTORY_WINDOW_DAYS = 14         # rolling-window trajectory features
BASELINE_ESTABLISHMENT_DAYS = 5     # how many days post-discharge to use for the patient baseline
MIN_BASELINE_OBSERVATIONS = 3       # below this, fall back to cohort priors
PROGRAM_WINDOW_DAYS = 30            # how long a patient stays in the program
ENGAGEMENT_DECAY_THRESHOLD_DAYS = 2 # days without data before the engagement-decay flag fires

# --- Calibration and Tier Thresholds ---
# Tier thresholds are cohort-stratified in production. A heart-failure
# patient and a post-op orthopedic patient have different baseline
# readmission rates, different intervention palettes, and different
# tolerable false-positive rates. The dictionary below shows the shape;
# production loads thresholds from a versioned DynamoDB table so the
# clinical governance committee can update them without a code deploy.
DEFAULT_TIER_THRESHOLDS = {
    "heart_failure":   {"tier_1": 0.60, "tier_2": 0.35, "tier_3": 0.18},
    "hypertension":    {"tier_1": 0.55, "tier_2": 0.32, "tier_3": 0.16},
    "diabetes":        {"tier_1": 0.55, "tier_2": 0.32, "tier_3": 0.16},
    "copd":            {"tier_1": 0.58, "tier_2": 0.34, "tier_3": 0.17},
    "post_op_cardiac": {"tier_1": 0.55, "tier_2": 0.32, "tier_3": 0.16},
    "DEFAULT":         {"tier_1": 0.60, "tier_2": 0.35, "tier_3": 0.18},
}

# Suppression windows.
SUPPRESSION_AFTER_INTERVENTION_HOURS = 24   # do not re-surface a patient who was just contacted
OUTCOME_LINKAGE_WINDOW_HOURS = 72            # outcome events link back to alerts within this window
HF_WEIGHT_3LB_3D_THRESHOLD = 3.0             # textbook heart-failure self-monitoring teaching threshold
```

A quick note on the thresholds block. The values above are defaults chosen to make the teaching example produce a sensible mix of tier-1, tier-2, and tier-3 worklist rows on a small synthetic dataset. A real deployment tunes them against a labeled backtest, then validates them prospectively in shadow mode before any row routes to a care manager. The right cuts depend on the cohort's readmission base rate, the care management team's daily capacity, and the alert-fatigue budget. These are dials, not physical constants, and the clinical governance committee owns them.

---

## Step 1: Enroll the Patient at Discharge

Discharge events from the EHR feed enroll patients into the post-discharge monitoring program. The discharge-time risk score (computed by a separate model, often the Chapter 7 readmission model) sets the initial monitoring tier. The condition cohort drives which trajectory metrics will be tracked over the next 30 days. This step is where the program gets its substrate: every patient who matters to the post-discharge pipeline starts here, and missing this step means the pipeline never sees them.

```python
def _to_decimal(value, precision="0.001"):
    """Convert numeric input to Decimal for DynamoDB and threshold storage.

    DynamoDB rejects Python float for numeric attributes because float
    arithmetic introduces rounding drift that makes threshold comparisons
    unreliable over time. Always pass weights, blood pressures, calibrated
    probabilities, and trajectory slopes through Decimal on the way in
    and back out.
    """
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(precision))


def _decimalize(obj):
    """Recursively convert floats to Decimals for DynamoDB write."""
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


def determine_cohorts(discharge_event):
    """Map a discharge event to one or more cohorts.

    A patient discharged for heart failure with a CABG history shows up in
    both the heart_failure and post_op_cardiac cohorts. Cohort membership
    drives which metrics get tracked and which thresholds apply at scoring
    time. Production maps from primary diagnosis ICD-10 codes plus
    procedure history; the teaching example uses a coarse rules-based
    classifier that fits in one function.
    """
    primary_dx = (discharge_event.get("primary_diagnosis_code") or "").upper()
    procedures = [p.upper() for p in discharge_event.get("procedure_codes") or []]

    cohorts = []
    # Heart failure family of ICD-10 codes (I50.x).
    if primary_dx.startswith("I50"):
        cohorts.append("heart_failure")
    # Hypertension family (I10-I16).
    if any(primary_dx.startswith(p) for p in ("I10", "I11", "I12", "I13", "I15", "I16")):
        cohorts.append("hypertension")
    # Diabetes-related admissions (E10-E14, plus DKA-coded admits).
    if any(primary_dx.startswith(p) for p in ("E10", "E11", "E13")):
        cohorts.append("diabetes")
    # COPD / chronic respiratory (J44, J43, J45).
    if any(primary_dx.startswith(p) for p in ("J44", "J43", "J45")):
        cohorts.append("copd")
    # Post-cardiac surgery cohort, by procedure history.
    if any(p in procedures for p in ("0210093", "0210493", "02RG07Z")):  # CABG, valve repair examples
        cohorts.append("post_op_cardiac")

    if not cohorts:
        cohorts = ["general"]   # fallback bucket; thresholds default to DEFAULT
    return cohorts


def tier_from_discharge_score(score, cohorts, program_caps=None):
    """Pick the initial monitoring tier from the discharge-time risk score.

    The discharge-time score (Chapter 7 territory) sets the initial tier
    before any post-discharge data has flowed in. As trajectory data
    accumulates over the next several days, the post-discharge anomaly
    model takes over and the tier moves based on the composite score.
    """
    # Pick the most-aggressive cohort thresholds when a patient lands in
    # multiple cohorts. Heart failure patients with concurrent diabetes
    # get heart-failure thresholds, which tend to be the more conservative.
    cohort_priority = ["heart_failure", "post_op_cardiac", "copd", "diabetes",
                       "hypertension", "general"]
    primary_cohort = next((c for c in cohort_priority if c in cohorts), "general")
    thresholds = DEFAULT_TIER_THRESHOLDS.get(primary_cohort,
                                             DEFAULT_TIER_THRESHOLDS["DEFAULT"])

    if score >= thresholds["tier_1"]:
        return "tier_1"
    if score >= thresholds["tier_2"]:
        return "tier_2"
    if score >= thresholds["tier_3"]:
        return "tier_3"
    return "below_threshold"


def on_discharge_event(discharge_event):
    """Enroll a patient into the post-discharge monitoring program.

    Production wires this as a Lambda subscribed to ADT-discharge events
    from the EHR integration. Pull discharge-time features and the
    discharge-time risk score (from a separate model service), build the
    state record, and notify the care management system that a new
    patient has been enrolled.
    """
    patient_id   = discharge_event["patient_id"]
    encounter_id = discharge_event["encounter_id"]

    cohorts             = determine_cohorts(discharge_event)
    discharge_features  = discharge_event.get("discharge_features") or {}
    discharge_risk      = float(discharge_event.get("discharge_risk_score", 0.3))
    initial_tier        = tier_from_discharge_score(discharge_risk, cohorts)
    discharge_time      = discharge_event["discharge_time"]
    discharge_dt        = datetime.fromisoformat(discharge_time.replace("Z", "+00:00"))
    program_end_dt      = discharge_dt + timedelta(days=PROGRAM_WINDOW_DAYS)

    state = {
        "patient_id":             patient_id,
        "encounter_id":           encounter_id,
        "is_active":              "true",   # GSI partition keys are strings
        "enrolled_at":            datetime.now(timezone.utc).isoformat(),
        "discharge_at":           discharge_time,
        "discharged_to":          discharge_event.get("discharge_disposition", "home"),
        "cohorts":                cohorts,
        "discharge_risk_score":   discharge_risk,
        "discharge_features":     discharge_features,
        "current_tier":           initial_tier,
        "last_contact_at":        None,
        "last_data_at":           None,
        "last_score_at":          None,
        "latest_values":          {},     # modality -> {value, observed_at, quality}
        "latest_pro":             None,   # most recent symptom check-in
        "recent_acute_events":    [],     # ED visits, external admissions
        "medication_events":      [],     # refills, missed refills
        "intervention_history":   [],     # outreach attempts, contacts, interventions
        "device_assignments":     discharge_event.get("assigned_devices", []),
        "program_end_at":         program_end_dt.isoformat(),
        "is_currently_inpatient": False,
        "has_active_program_hold": False,
        "updated_at":             datetime.now(timezone.utc).isoformat(),
    }

    table = dynamodb.Table(PATIENT_STATE_TABLE)
    table.put_item(Item=_decimalize(state))

    # Notify the care management system. The downstream subscriber is the
    # outreach scheduler, which slots the day-1 introductory call and
    # confirms RPM-device pairing.
    eventbridge.put_events(Entries=[{
        "Source":      "post-discharge.enrollment-handler",
        "DetailType":  "PatientEnrolled",
        "Detail":      json.dumps({
            "patient_id":           patient_id,
            "encounter_id":         encounter_id,
            "cohorts":              cohorts,
            "current_tier":         initial_tier,
            "discharge_at":         discharge_time,
            "program_end_at":       program_end_dt.isoformat(),
        }, default=str),
        "EventBusName": POST_DISCHARGE_EVENTS_BUS,
    }])

    logger.info("patient enrolled", extra={
        "event":         "on_discharge_event",
        "patient_id":    patient_id,
        "encounter_id":  encounter_id,
        "cohorts":       cohorts,
        "current_tier":  initial_tier,
    })
    return state
```

The cohort determination is deliberately coarse here. A real program runs the discharge against a clinical-rules engine that knows about admit-source, prior-encounter history, current medication regimen, and SDOH flags. Heart-failure-with-acute-kidney-injury is operationally distinct from heart-failure-without-AKI; post-op-cardiac at day 5 is operationally distinct from post-op-cardiac at day 25. Treat the cohort label as a routing key, not a clinical category.

---

## Step 2: Ingest RPM Measurements and Patient-Reported Outcomes

RPM device vendors push measurements via webhook. Patient-reported outcomes (symptom check-ins, medication adherence reports) flow in from the patient-facing app, SMS vendor, or IVR vendor. Both paths normalize into the same canonical patient-event format that the rest of the pipeline consumes. This is the highest-volume data source in the program, and getting the normalization right is what separates a pipeline that produces clean trajectory features from one that quietly accumulates unit-conversion bugs.

```python
def verify_vendor_signature(webhook_request):
    """Validate the RPM-vendor's webhook signature.

    Production checks vendor-specific HMAC or JWT signatures. Skipping
    this is how unauthenticated payloads end up in your data store.
    BodyTrace, A&D Medical, iHealth, and Withings each have their own
    schemes; the BAA spells out the validation rules. The teaching
    example is a stub that always returns True.
    """
    # In production: verify HMAC-SHA256 against the vendor secret in
    # AWS Secrets Manager, check the timestamp window, reject replays.
    return True


def resolve_patient_id_from_device(device_id):
    """Look up the enrolled patient for a device serial number.

    Devices are assigned to patients at enrollment. Production maintains
    a device-to-patient table; this stub returns the device_id as the
    patient_id for the demo, which obviously is not how real assignments
    work.
    """
    # In production:
    #   table = dynamodb.Table("device-assignments")
    #   response = table.get_item(Key={"device_id": device_id})
    #   return response.get("Item", {}).get("patient_id")
    return device_id


def convert_to_canonical_units(value, units, modality):
    """Convert vendor-specific units to the canonical unit per modality.

    Weight: store kilograms canonically. Some vendors send pounds. A
    silent unit-conversion bug here multiplies every weight feature by
    2.2 and the model still produces nonsense scores that look superficially
    sensible. This is the single most common bug class in RPM pipelines.
    """
    v = float(value)
    if modality == "WEIGHT":
        if units in ("kg", "Kg", "KG", "kilogram"):
            return v
        if units in ("lb", "lbs", "LB", "pound"):
            return v * 0.45359237
        raise ValueError(f"unrecognized weight units: {units}")
    if modality in ("SBP", "DBP"):
        if units in ("mmHg", "mm[Hg]"):
            return v
        raise ValueError(f"unrecognized BP units: {units}")
    if modality == "GLUCOSE":
        if units in ("mg/dL", "mg/dl"):
            return v
        if units in ("mmol/L", "mmol/l"):
            return v * 18.0182   # mmol/L to mg/dL canonical
        raise ValueError(f"unrecognized glucose units: {units}")
    # Other modalities (SPO2 percentage, peak flow L/min, heart rate bpm)
    # are unit-stable in practice but a real implementation still validates
    # the units field and rejects mismatches.
    return v


def parse_vendor_payload(webhook_request):
    """Normalize a vendor-specific payload to a uniform internal shape.

    Each vendor's schema is different. Production runs a vendor-specific
    parser; this stub assumes the webhook body already arrived in the
    target shape so we can focus on the canonical-event construction.
    """
    return webhook_request


def on_rpm_webhook(webhook_request):
    """Receive an RPM measurement webhook and put it on the event stream.

    Production wires this behind API Gateway, with the Lambda doing the
    signature verification, the patient-id resolution, the unit
    normalization, and the Kinesis put. The stream is consumed downstream
    by the event-normalizer Lambda that updates state and trajectory.
    """
    if not verify_vendor_signature(webhook_request):
        return {"statusCode": 401}

    parsed = parse_vendor_payload(webhook_request)
    modality_loinc = parsed["measurement_code"]
    canonical_key = next(
        (k for k, v in RPM_LOINC.items() if v == modality_loinc), None
    )
    if canonical_key is None:
        # Unknown LOINC: route to quarantine queue. Production logs a
        # metric and a DLQ message rather than dropping silently.
        logger.warning("unknown RPM LOINC", extra={"loinc": modality_loinc})
        return {"statusCode": 202}

    patient_id = resolve_patient_id_from_device(parsed["device_id"])
    if patient_id is None:
        logger.warning("device not assigned to a patient",
                       extra={"device_id": parsed["device_id"]})
        return {"statusCode": 202}

    canonical_event = {
        "event_id":        parsed.get("event_id") or str(uuid.uuid4()),
        "patient_id":      patient_id,
        "event_type":      "rpm_measurement",
        "modality":        canonical_key,
        "value":           convert_to_canonical_units(
                              parsed["value"], parsed["units"], canonical_key
                           ),
        "units":           parsed["units"],
        "observed_at":     parsed["measurement_time"],
        "received_at":     datetime.now(timezone.utc).isoformat(),
        "device_id":       parsed["device_id"],
        "quality_flags":   parsed.get("quality_flags", []),
    }

    kinesis.put_record(
        StreamName=PATIENT_EVENTS_STREAM,
        Data=json.dumps(canonical_event, default=str).encode("utf-8"),
        PartitionKey=patient_id,
    )

    return {"statusCode": 200}


def compute_symptom_score(responses, template_id):
    """Aggregate a check-in response set into a single symptom score.

    Cohort-specific templates produce cohort-specific scores. The heart-
    failure check-in scores dyspnea, orthopnea, edema, and weight-change
    self-report. The COPD check-in scores dyspnea on exertion, sputum
    color, rescue-inhaler use, and activity tolerance. Production uses
    validated instruments (KCCQ-12 for heart failure, CAT for COPD) where
    they fit; this stub is a simple weighted sum.
    """
    if template_id == "hf_symptom_check":
        return (
            int(responses.get("dyspnea_score", 0)) * 1.5
            + int(responses.get("orthopnea_score", 0)) * 1.2
            + int(responses.get("edema_score", 0)) * 1.0
            + int(responses.get("medication_adherence", 0)) * 0.5
        )
    if template_id == "copd_symptom_check":
        return (
            int(responses.get("dyspnea_score", 0)) * 1.5
            + int(responses.get("rescue_inhaler_uses", 0)) * 1.0
            + int(responses.get("activity_tolerance", 0)) * 1.0
        )
    # Generic fallback.
    return float(sum(int(v) for v in responses.values() if str(v).isdigit()))


def on_pro_check_in(check_in_event):
    """Receive a patient-reported outcome submission.

    PRO data flows from the patient-facing app, SMS vendor, or IVR vendor.
    Each vendor has its own webhook format; the parser is per-vendor. The
    canonical event format is uniform across vendors so downstream code
    does not need to know which channel delivered the check-in.
    """
    canonical_event = {
        "event_id":        check_in_event.get("event_id") or str(uuid.uuid4()),
        "patient_id":      check_in_event["patient_id"],
        "event_type":      "pro_check_in",
        "modality":        check_in_event["template_id"],
        "responses":       check_in_event["responses"],
        "symptom_score":   compute_symptom_score(
                              check_in_event["responses"],
                              check_in_event["template_id"]
                           ),
        "free_text":       check_in_event.get("free_text_concerns"),
        "observed_at":     check_in_event["submitted_at"],
        "received_at":     datetime.now(timezone.utc).isoformat(),
    }

    kinesis.put_record(
        StreamName=PATIENT_EVENTS_STREAM,
        Data=json.dumps(canonical_event, default=str).encode("utf-8"),
        PartitionKey=canonical_event["patient_id"],
    )

    return canonical_event
```

Two things worth highlighting. First, the unit-conversion logic is paranoid for a reason. Mixed-unit data is the silent killer of RPM pipelines: a single ward (or a single device firmware version) emitting weights in pounds while everything else emits kilograms produces a per-patient bias that no amount of per-modality control-charting will catch. Validate units at ingest, never later. Second, the patient-id resolution from device serial number is its own integration project. Devices get reassigned, returned, replaced, and shared; the device-to-patient table needs lifecycle hooks for all of those events, and production deployments often build a dedicated device-management service.

---

## Step 3: Update Patient State and Trajectory History

The event normalizer reads from the Kinesis stream, applies the canonical event to the patient-state record (latest values, recent acute events, intervention history), and writes time-series records to Timestream for trajectory analysis. The state store is the substrate the worklist UI reads; the trajectory store is what the feature engine queries when scoring runs.

```python
def _is_more_recent(new_observed_at, existing):
    """Out-of-order delivery guard. Only overwrite a snapshot value if the
    new observation has a later observed_at than the one already stored.
    Kinesis is at-least-once, so duplicates and lagged deliveries happen.
    """
    if existing is None:
        return True
    return new_observed_at > existing.get("observed_at", "")


def _trim_recent_acute_events(events, lookback_days=14):
    """Keep recent ED visits and external admissions. Older events fall
    out of the state record (they live in the audit index for retrospective
    queries) so DynamoDB item size stays bounded."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    return [e for e in events if e.get("occurred_at", "") >= cutoff]


def _trim_medication_events(events, lookback_days=21):
    """Keep recent medication events; older ones fall out of state."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    return [e for e in events if e.get("occurred_at", "") >= cutoff]


def classify_medication(rxnorm_code):
    """Map an RxNorm code to a therapeutic class.

    Production uses a medication knowledge base (First Databank, Lexicomp,
    or RxNorm + custom mappings). The stub returns a few high-value
    classes that drive the heart-failure features.
    """
    # In production, this is a lookup against a versioned reference table.
    HF_DIURETICS = {"4603", "4278", "8629"}    # furosemide, bumetanide, etc.
    HF_GDMT = {"6918", "298869"}                # carvedilol, sacubitril/valsartan
    INSULIN_CLASSES = {"5856", "253182"}        # insulin glargine, insulin lispro
    if rxnorm_code in HF_DIURETICS:
        return "diuretic"
    if rxnorm_code in HF_GDMT:
        return "hf_gdmt"
    if rxnorm_code in INSULIN_CLASSES:
        return "insulin"
    return "other"


def should_rescore_immediately(canonical_event):
    """Decide whether an event triggers immediate re-scoring.

    Most events ride the daily scoring tick. A few are urgent enough to
    warrant immediate re-evaluation: ED visits at our facility, external
    admissions captured via HIE, and patient-reported critical-symptom
    flags. The daily run picks up everything else.
    """
    if canonical_event["event_type"] == "ed_visit":
        return True
    if canonical_event["event_type"] == "external_admission":
        return True
    if canonical_event["event_type"] == "pro_check_in":
        # A symptom score that crosses the urgent threshold gets re-scored.
        if canonical_event.get("symptom_score", 0) >= 8:
            return True
    return False


def on_canonical_event(canonical_event):
    """Apply a canonical event to patient state and trajectory history."""
    patient_id = canonical_event["patient_id"]

    table = dynamodb.Table(PATIENT_STATE_TABLE)
    # TODO (TechWriter): Code review WARNING 1. Limit=1 with FilterExpression silently misses the active record when an older inactive encounter exists for this patient (DynamoDB applies Limit before the filter). After a single readmit-and-rediscarge cycle, every subsequent canonical event for this patient routes through the silent-loss branch. Fix: use a composite GSI keyed on (patient_id, is_active) so the active-flag becomes a key condition, or drop Limit=1 and let the filter scan all encounters for the patient (small partition is fine). Use Attr (not Key) on FilterExpression while we're here.
    response = table.query(
        KeyConditionExpression=Key("patient_id").eq(patient_id),
        FilterExpression=Key("is_active").eq("true"),
        Limit=1,
    )
    items = response.get("Items", [])
    if not items:
        # No active enrollment for this patient. Could be a late-arriving
        # device reading after program graduation, or a device assigned
        # to the wrong patient. Log and drop; production routes to a DLQ.
        logger.info("event for non-enrolled patient",
                    extra={"patient_id": patient_id, "event_id": canonical_event["event_id"]})
        return None

    state = _undecimalize(items[0])
    encounter_id = state["encounter_id"]
    event_type = canonical_event["event_type"]

    if event_type == "rpm_measurement":
        modality = canonical_event["modality"]
        existing_latest = state.get("latest_values", {}).get(modality)
        if _is_more_recent(canonical_event["observed_at"], existing_latest):
            state.setdefault("latest_values", {})[modality] = {
                "value":        canonical_event["value"],
                "observed_at":  canonical_event["observed_at"],
                "quality":      canonical_event.get("quality_flags", []),
            }
        state["last_data_at"] = canonical_event["observed_at"]

        # Trajectory write to Timestream. The trajectory store is what the
        # feature engine queries for slope, max, min, and baseline features.
        observed_dt = datetime.fromisoformat(
            canonical_event["observed_at"].replace("Z", "+00:00")
        )
        timestream_write.write_records(
            DatabaseName=TIMESTREAM_DATABASE,
            TableName=TIMESTREAM_RPM_TABLE,
            Records=[{
                "Dimensions": [
                    {"Name": "patient_id",  "Value": patient_id},
                    {"Name": "modality",    "Value": modality},
                ],
                "MeasureName":      modality,
                "MeasureValue":     str(canonical_event["value"]),
                "MeasureValueType": "DOUBLE",
                "Time":             str(int(observed_dt.timestamp() * 1000)),
                "TimeUnit":         "MILLISECONDS",
            }],
        )

    elif event_type == "pro_check_in":
        state["latest_pro"] = {
            "template":       canonical_event["modality"],
            "responses":      canonical_event.get("responses", {}),
            "symptom_score":  canonical_event.get("symptom_score"),
            "free_text":      canonical_event.get("free_text"),
            "observed_at":    canonical_event["observed_at"],
        }
        state["last_data_at"] = canonical_event["observed_at"]

        # Trajectory write for symptom-score time-series.
        observed_dt = datetime.fromisoformat(
            canonical_event["observed_at"].replace("Z", "+00:00")
        )
        if canonical_event.get("symptom_score") is not None:
            timestream_write.write_records(
                DatabaseName=TIMESTREAM_DATABASE,
                TableName=TIMESTREAM_PRO_TABLE,
                Records=[{
                    "Dimensions": [
                        {"Name": "patient_id", "Value": patient_id},
                        {"Name": "template",   "Value": canonical_event["modality"]},
                    ],
                    "MeasureName":      "symptom_score",
                    "MeasureValue":     str(canonical_event["symptom_score"]),
                    "MeasureValueType": "DOUBLE",
                    "Time":             str(int(observed_dt.timestamp() * 1000)),
                    "TimeUnit":         "MILLISECONDS",
                }],
            )

    elif event_type in ("ed_visit", "external_admission"):
        state.setdefault("recent_acute_events", []).append({
            "type":          event_type,
            "facility":      canonical_event.get("facility"),
            "occurred_at":   canonical_event["observed_at"],
        })
        state["recent_acute_events"] = _trim_recent_acute_events(
            state["recent_acute_events"]
        )

    elif event_type in ("refill", "refill_missed"):
        rxnorm = canonical_event.get("rxnorm_code", "")
        state.setdefault("medication_events", []).append({
            "rx_norm_code":      rxnorm,
            "event_subtype":     event_type,
            "occurred_at":       canonical_event["observed_at"],
            "therapeutic_class": classify_medication(rxnorm),
        })
        state["medication_events"] = _trim_medication_events(
            state["medication_events"]
        )

    elif event_type == "care_management_interaction":
        state["last_contact_at"] = canonical_event["observed_at"]
        # The intervention-capture function (Step 8) is the canonical
        # writer of intervention records. This branch updates the snapshot
        # for the worklist suppression logic.

    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    table.put_item(Item=_decimalize(state))

    # Persist to the raw event lake for retrospective analysis.
    s3_client.put_object(
        Bucket=RAW_EVENTS_BUCKET,
        Key=(
            f"event_type={event_type}/"
            f"year={canonical_event['observed_at'][:4]}/"
            f"month={canonical_event['observed_at'][5:7]}/"
            f"day={canonical_event['observed_at'][8:10]}/"
            f"{canonical_event['event_id']}.json"
        ),
        Body=json.dumps(canonical_event, default=str).encode("utf-8"),
        ServerSideEncryption="aws:kms",
    )

    if should_rescore_immediately(canonical_event):
        eventbridge.put_events(Entries=[{
            "Source":      "post-discharge.event-normalizer",
            "DetailType":  "RescoreRequest",
            "Detail":      json.dumps({
                "patient_id":    patient_id,
                "encounter_id":  encounter_id,
                "trigger":        "event_driven",
                "reason":         event_type,
            }, default=str),
            "EventBusName": POST_DISCHARGE_SCORING_BUS,
        }])

    return state
```

The out-of-order-delivery guard matters here for the same reason it does in Recipe 3.7: patients sometimes upload weights twice from a device that retried the sync, and a delayed delivery can land an older measurement after a newer one. The state record reflects the most-recent observation by `observed_at`, not by arrival order, so the snapshot that the worklist UI reads is correct even when deliveries arrive scrambled.

---

## Step 4: Run the Daily Scoring Pipeline

Once a day (typically very early morning so the worklist is ready before the care-management team starts their shift), the scoring pipeline iterates every active patient, computes their feature vector, runs the composite scoring model plus per-modality detectors, and produces tier-stratified scoring records that feed the worklist builder. Step Functions orchestrates this in production; the teaching example runs it inline.

```python
def daily_scoring_pipeline(scoring_handler):
    """Iterate every active patient and dispatch a scoring request.

    Production wires this as an EventBridge scheduled rule (typically 4-6
    AM local time) that triggers a Step Functions state machine. The
    state machine queries the active-patients GSI in batches, dispatches
    per-patient scoring tasks in parallel, and waits for all to complete
    before invoking the worklist builder.
    """
    table = dynamodb.Table(PATIENT_STATE_TABLE)
    # TODO (TechWriter): Code review WARNING 2. GSI query lacks pagination; silently drops patients past 1MB DynamoDB response limit. The 2,000-patient program target this recipe names is comfortably above this threshold once you account for discharge_features, latest_values, intervention_history, and recent_acute_events on each record. Patients with rich intervention histories (the highest-risk subset) drop out first. Fix: wrap in a LastEvaluatedKey loop that paginates until the GSI is exhausted; in production replace the in-process accumulation with a Step Functions Map state.
    response = table.query(
        IndexName="is_active-index",
        KeyConditionExpression=Key("is_active").eq("true"),
    )

    score_records = []
    for item in response.get("Items", []):
        item = _undecimalize(item)
        score_record = scoring_handler(
            patient_id=item["patient_id"],
            encounter_id=item["encounter_id"],
            trigger="daily",
        )
        if score_record is not None:
            score_records.append(score_record)

    return score_records


def run_modality_detector(modality, history, baseline, cohort_prior):
    """Per-modality control-chart anomaly detector.

    A patient-specific control chart on the modality time series. Compute
    the rolling mean and the rolling standard deviation, then flag the
    most recent observation if it deviates more than k sigma from the
    baseline. When patient-specific baseline data is insufficient, fall
    back to the cohort prior with appropriate uncertainty inflation.
    """
    if not history:
        return {"deviation_score": 0.0, "baseline_age_days": None,
                "baseline_source": "none"}

    values = [h["value"] for h in history]
    latest = values[-1]
    if baseline is not None and len(history) >= MIN_BASELINE_OBSERVATIONS:
        # Patient-specific baseline. Use the trimmed mean of the
        # baseline-establishment window.
        center = baseline["mean"]
        spread = max(baseline["std"], 1e-3)   # avoid div-by-zero on perfectly stable series
        baseline_age_days = baseline.get("age_days")
        baseline_source = "patient_specific"
    else:
        # Cold-start fallback: use the cohort prior's expected value and
        # spread, inflated for the uncertainty of using a population value
        # for a specific patient.
        center = cohort_prior["expected_value"]
        spread = cohort_prior["expected_std"] * 1.5
        baseline_age_days = None
        baseline_source = "cohort_prior"

    z = (latest - center) / spread
    deviation_score = float(min(1.0, abs(z) / 3.0))   # cap at 3-sigma equivalent

    return {
        "deviation_score":   deviation_score,
        "z_score":           float(z),
        "latest_value":      latest,
        "center":            float(center),
        "spread":            float(spread),
        "baseline_source":   baseline_source,
        "baseline_age_days": baseline_age_days,
    }


def cohort_prior_for(cohorts, modality):
    """Return the cohort-level prior for a modality.

    Cohort priors are the population-level expected value and spread for
    each modality, fit on the program's historical data. Production loads
    these from a versioned reference table; the teaching example hardcodes
    representative values.
    """
    # Heart-failure-specific priors are tighter and centered higher than
    # general-population priors for weight (these patients are usually
    # heavier than population mean and the post-discharge dry weight is
    # what the program tracks).
    if "heart_failure" in cohorts:
        if modality == "WEIGHT":
            return {"expected_value": 95.0, "expected_std": 18.0}    # kg
        if modality in ("SBP", "DBP"):
            return {"expected_value": 125.0 if modality == "SBP" else 75.0,
                    "expected_std": 18.0 if modality == "SBP" else 12.0}
        if modality == "HR":
            return {"expected_value": 78.0, "expected_std": 14.0}
    if "diabetes" in cohorts:
        if modality == "GLUCOSE":
            return {"expected_value": 145.0, "expected_std": 45.0}
    if "copd" in cohorts:
        if modality == "PEAK_FLOW":
            return {"expected_value": 320.0, "expected_std": 75.0}
        if modality == "SPO2":
            return {"expected_value": 94.0, "expected_std": 3.0}
    # Generic fallbacks.
    return {"expected_value": 0.0, "expected_std": 1.0}


def map_to_tier(calibrated_probability, cohorts):
    """Map a calibrated probability to a tier using cohort thresholds."""
    cohort_priority = ["heart_failure", "post_op_cardiac", "copd", "diabetes",
                       "hypertension"]
    primary = next((c for c in cohort_priority if c in cohorts), "DEFAULT")
    thresholds = DEFAULT_TIER_THRESHOLDS.get(primary, DEFAULT_TIER_THRESHOLDS["DEFAULT"])
    if calibrated_probability >= thresholds["tier_1"]:
        return "tier_1"
    if calibrated_probability >= thresholds["tier_2"]:
        return "tier_2"
    if calibrated_probability >= thresholds["tier_3"]:
        return "tier_3"
    return "below_threshold"


def score_patient(patient_id, encounter_id, trigger, model, calibrator,
                  feature_order):
    """End-to-end scoring for a single patient on a single tick.

    Computes features (Step 5), runs per-modality detectors and the
    composite model, applies calibration, assigns a tier, and persists
    the scoring record. The explanation builder (Step 6) and the worklist
    builder (Step 7) consume this output.
    """
    table = dynamodb.Table(PATIENT_STATE_TABLE)
    state = _undecimalize(table.get_item(
        Key={"patient_id": patient_id, "encounter_id": encounter_id}
    ).get("Item", {}))
    if not state or state.get("is_active") != "true":
        return None

    as_of = datetime.now(timezone.utc).isoformat()
    features = compute_features(state, as_of)

    # Per-modality detectors. Each cohort tracks its own subset; a
    # heart-failure patient runs WEIGHT, SBP, DBP, and HR detectors,
    # while a COPD patient runs PEAK_FLOW, SPO2, and HR detectors. Output
    # feeds into both the composite features (deviation_score) and the
    # explanation layer (per-modality breakdown).
    per_modality = {}
    for modality in modalities_for_cohorts(state["cohorts"]):
        history = fetch_modality_history(patient_id, modality,
                                         days=TRAJECTORY_WINDOW_DAYS,
                                         as_of=as_of)
        baseline = compute_patient_baseline(history)
        cohort_prior = cohort_prior_for(state["cohorts"], modality)
        per_modality[modality] = run_modality_detector(
            modality, history, baseline, cohort_prior
        )
        features[f"{modality}_deviation_score"] = per_modality[modality]["deviation_score"]

    # Composite scoring. Production uses a SageMaker batch transform run
    # (or real-time endpoint for event-driven re-scoring). The teaching
    # example invokes a small in-process model so this file runs without
    # a deployed endpoint.
    if model == "ENDPOINT":
        raw_score = score_via_sagemaker_endpoint(features, feature_order)
    else:
        raw_score = score_via_local_model(features, feature_order, model)

    calibrated = float(calibrator.predict(np.array([raw_score]))[0]) if calibrator else raw_score
    tier = map_to_tier(calibrated, state["cohorts"])
    days_post = days_between(state["discharge_at"], as_of)

    score_record = {
        "score_id":               str(uuid.uuid4()),
        "patient_id":             patient_id,
        "encounter_id":           encounter_id,
        "scored_at":              as_of,
        "trigger":                trigger,
        "composite_raw":          _to_decimal(raw_score),
        "composite_calibrated":   _to_decimal(calibrated),
        "tier":                   tier,
        "cohorts":                state["cohorts"],
        "days_post_discharge":    days_post,
        "per_modality_scores":    _decimalize(per_modality),
        "feature_count":          sum(1 for v in features.values() if v is not None),
        "model_version":          "post-discharge-anomaly-v1.2",
        "calibration_version":    "calib-v1.2-2026-04",
    }

    history_table = dynamodb.Table(SCORING_HISTORY_TABLE)
    history_table.put_item(Item=_decimalize(score_record))

    # Update last_score_at on the state record so the next periodic tick
    # knows we already scored this patient today.
    table.update_item(
        Key={"patient_id": patient_id, "encounter_id": encounter_id},
        UpdateExpression="SET last_score_at = :ts",
        ExpressionAttributeValues={":ts": as_of},
        ConditionExpression="attribute_exists(patient_id)",
    )

    # Publish for explanation and worklist fan-out.
    eventbridge.put_events(Entries=[{
        "Source":      "post-discharge.scoring-service",
        "DetailType":  "ScoreProduced",
        "Detail":      json.dumps({
            "patient_id":             patient_id,
            "encounter_id":           encounter_id,
            "score_id":               score_record["score_id"],
            "scored_at":              as_of,
            "tier":                   tier,
            "composite_calibrated":   calibrated,
            "trigger":                trigger,
        }, default=str),
        "EventBusName": POST_DISCHARGE_SCORING_BUS,
    }])

    _emit_metric("ScoresProduced", 1)
    _emit_metric(f"Tier_{tier}", 1)

    # Carry the features through so the explanation builder does not
    # need to recompute them. In production, features land in the Feature
    # Store and the explanation builder fetches them by snapshot ID.
    score_record["_features_for_explanation"] = features
    return score_record


def days_between(start_iso, end_iso):
    """Days between two ISO-8601 timestamps, fractional."""
    s = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    e = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    return (e - s).total_seconds() / 86400.0


def modalities_for_cohorts(cohorts):
    """Union of monitored modalities across the patient's cohorts."""
    out = set()
    for c in cohorts:
        out.update(COHORT_MODALITIES.get(c, []))
    return sorted(out)


def _emit_metric(metric_name, value, unit="Count"):
    """Emit a CloudWatch metric for operational monitoring."""
    try:
        cloudwatch.put_metric_data(
            Namespace="PostDischarge/Scoring",
            MetricData=[{
                "MetricName": metric_name,
                "Value":      float(value),
                "Unit":       unit,
                "Timestamp":  datetime.now(timezone.utc),
            }],
        )
    except Exception as e:
        logger.warning("metric emit failed",
                       extra={"metric": metric_name, "error": str(e)})
```

The split between the daily sweep and event-driven re-scoring matters for the same reason it does in Recipe 3.7. The daily sweep catches steady-state drift (a slowly-rising weight that crosses a tier boundary not because of any new event but because of accumulated trajectory). Event-driven re-scoring catches acute changes (a fresh ED visit; a critical-symptom check-in). Pipelines that do only one of the two miss patients in the other regime.

---

## Step 5: Compute the Feature Vector

The feature engine reads patient state and trajectory history, and produces the model's input feature vector. Cold-start logic falls back to cohort priors when patient-specific baselines are not yet established. The feature vector is persisted to Feature Store so the same features are reproducible for governance review and so online and offline paths stay consistent.

```python
def _compute_slope(timestamped_values):
    """Linear regression slope of value over time, in units per day.

    Captures whether weights are trending up or down. A weight that has
    climbed from 198 to 204 over 3 days produces slope ~2 lb/day, which
    is much more informative than the current value alone.
    """
    if len(timestamped_values) < 2:
        return None
    t = np.array([v["t_days"] for v in timestamped_values], dtype=float)
    y = np.array([v["value"]   for v in timestamped_values], dtype=float)
    if t.std() < 1e-6:
        return 0.0
    return float(np.cov(t, y, ddof=0)[0, 1] / t.var())


def fetch_modality_history(patient_id, modality, days, as_of):
    """Query Timestream for a modality's history within the lookback window."""
    as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    start_dt = as_of_dt - timedelta(days=days)
    query = f'''
        SELECT time, measure_value::double AS value
        FROM "{TIMESTREAM_DATABASE}"."{TIMESTREAM_RPM_TABLE}"
        WHERE patient_id = '{patient_id}'
          AND modality = '{modality}'
          AND time BETWEEN from_iso8601_timestamp('{start_dt.isoformat()}')
                       AND from_iso8601_timestamp('{as_of_dt.isoformat()}')
        ORDER BY time
    '''
    response = timestream_query.query(QueryString=query)

    series = []
    for row in response.get("Rows", []):
        t_str = row["Data"][0]["ScalarValue"]
        v_str = row["Data"][1]["ScalarValue"]
        observed_dt = datetime.fromisoformat(t_str.replace(" ", "T") + "+00:00")
        series.append({
            "observed_at": observed_dt.isoformat(),
            "value":       float(v_str),
            "t_days":      (observed_dt - as_of_dt).total_seconds() / 86400.0,
        })
    return series


def compute_patient_baseline(history):
    """Build a patient-specific baseline from the first several days of
    post-discharge data. Returns None when too few observations exist;
    the caller falls back to cohort priors.
    """
    if len(history) < MIN_BASELINE_OBSERVATIONS:
        return None
    # Use the earliest observations within the baseline-establishment
    # window. Trimmed mean reduces sensitivity to single outliers.
    sorted_obs = sorted(history, key=lambda h: h["observed_at"])
    baseline_obs = sorted_obs[:max(MIN_BASELINE_OBSERVATIONS,
                                    int(len(sorted_obs) * 0.4))]
    values = [b["value"] for b in baseline_obs]
    trimmed = sorted(values)[1:-1] if len(values) >= 5 else values
    return {
        "mean":       float(np.mean(trimmed)) if trimmed else None,
        "std":        float(np.std(trimmed)) if len(trimmed) > 1 else 0.5,
        "n_obs":      len(values),
        "age_days":   1.0,   # baseline is anchored to early post-discharge
    }


def compute_features(state, as_of):
    """Compute the model's input feature vector.

    Reads from the state record (current snapshots, intervention history,
    medication events) and from Timestream (trajectory history). Cold-
    start patients fall back to cohort priors for per-modality baselines.
    """
    features = {}
    as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    discharge_dt = datetime.fromisoformat(state["discharge_at"].replace("Z", "+00:00"))
    days_post = (as_of_dt - discharge_dt).total_seconds() / 86400.0
    features["days_post_discharge"]   = days_post
    features["discharge_risk_score"]  = float(state.get("discharge_risk_score", 0.3))

    # Cohort indicators.
    for cohort_name in ["heart_failure", "hypertension", "diabetes",
                         "copd", "post_op_cardiac"]:
        features[f"cohort_{cohort_name}"] = cohort_name in state["cohorts"]

    # Per-modality trajectory features for each cohort-relevant modality.
    for modality in modalities_for_cohorts(state["cohorts"]):
        history = fetch_modality_history(
            state["patient_id"], modality, TRAJECTORY_WINDOW_DAYS, as_of
        )

        latest = state.get("latest_values", {}).get(modality)
        if latest:
            features[f"{modality}_current"] = latest["value"]
            obs_dt = datetime.fromisoformat(latest["observed_at"].replace("Z", "+00:00"))
            features[f"{modality}_age_hours"] = (as_of_dt - obs_dt).total_seconds() / 3600.0
        else:
            features[f"{modality}_current"]   = None
            features[f"{modality}_age_hours"] = None

        # Trajectory features at multiple windows.
        for window_days in (3, 7, 14):
            window_cutoff = -float(window_days)
            window_values = [v for v in history if v["t_days"] >= window_cutoff]
            if window_values:
                values_only = [v["value"] for v in window_values]
                features[f"{modality}_slope_{window_days}d"] = _compute_slope(window_values)
                features[f"{modality}_max_{window_days}d"]   = max(values_only)
                features[f"{modality}_min_{window_days}d"]   = min(values_only)
                features[f"{modality}_count_{window_days}d"] = len(window_values)
            else:
                for stat in ("slope", "max", "min", "count"):
                    features[f"{modality}_{stat}_{window_days}d"] = None

        # Patient-specific baseline. Use the first several days of post-
        # discharge data if available; fall back to cohort priors.
        baseline = compute_patient_baseline(history)
        if baseline and baseline["mean"] is not None:
            features[f"{modality}_baseline"]        = baseline["mean"]
            features[f"{modality}_baseline_source"] = "patient_specific"
        else:
            prior = cohort_prior_for(state["cohorts"], modality)
            features[f"{modality}_baseline"]        = prior["expected_value"]
            features[f"{modality}_baseline_source"] = "cohort_prior"

        if features[f"{modality}_current"] is not None:
            features[f"{modality}_delta_from_baseline"] = (
                features[f"{modality}_current"] - features[f"{modality}_baseline"]
            )
        else:
            features[f"{modality}_delta_from_baseline"] = None

    # --- Cohort-specific composite features ---
    if "heart_failure" in state["cohorts"]:
        # Textbook heart-failure deterioration signal: 3-lb-in-3-days rule.
        # Historically the patient-self-management threshold; still useful
        # as a model feature.
        weight_max_3d = features.get("WEIGHT_max_3d") or 0.0
        weight_min_3d = features.get("WEIGHT_min_3d") or 0.0
        # The Timestream values are in canonical kilograms; convert to
        # pounds for the textbook 3-lb threshold for comparability with
        # patient-education materials.
        weight_change_lb = (weight_max_3d - weight_min_3d) * 2.20462
        features["hf_weight_3d_increase_lb"] = weight_change_lb
        features["hf_weight_3lb_3d_alert"]   = (
            weight_change_lb >= HF_WEIGHT_3LB_3D_THRESHOLD
        )
        # Symptom-score features from the latest PRO check-in.
        latest_pro = state.get("latest_pro") or {}
        features["hf_dyspnea_score"] = (
            latest_pro.get("responses", {}).get("dyspnea_score")
            if latest_pro.get("template") == "hf_symptom_check" else None
        )
        features["hf_orthopnea_score"] = (
            latest_pro.get("responses", {}).get("orthopnea_score")
            if latest_pro.get("template") == "hf_symptom_check" else None
        )

    if "diabetes" in state["cohorts"]:
        glucose_max_3d = features.get("GLUCOSE_max_3d") or 0
        glucose_min_3d = features.get("GLUCOSE_min_3d") or float("inf")
        features["dm_recent_high_glucose"] = glucose_max_3d >= 300 if glucose_max_3d else False
        features["dm_recent_low_glucose"]  = glucose_min_3d <= 70 if glucose_min_3d != float("inf") else False

    if "copd" in state["cohorts"]:
        pf_delta = features.get("PEAK_FLOW_delta_from_baseline")
        features["copd_peak_flow_decline"] = (pf_delta is not None and pf_delta < -50)
        latest_pro = state.get("latest_pro") or {}
        features["copd_dyspnea_score"] = (
            latest_pro.get("responses", {}).get("dyspnea_score")
            if latest_pro.get("template") == "copd_symptom_check" else None
        )

    # --- Engagement features ---
    # The single most underrated feature class in post-discharge programs.
    # A patient who stops checking in is communicating; the model just
    # has to listen.
    last_data_at = state.get("last_data_at")
    if last_data_at:
        last_data_dt = datetime.fromisoformat(last_data_at.replace("Z", "+00:00"))
        features["days_since_last_data"] = (as_of_dt - last_data_dt).total_seconds() / 86400.0
    else:
        features["days_since_last_data"] = days_post

    last_contact_at = state.get("last_contact_at")
    if last_contact_at:
        last_contact_dt = datetime.fromisoformat(last_contact_at.replace("Z", "+00:00"))
        features["days_since_last_contact"] = (as_of_dt - last_contact_dt).total_seconds() / 86400.0
    else:
        features["days_since_last_contact"] = days_post

    features["engagement_decay_flag"] = (
        features["days_since_last_data"] >= ENGAGEMENT_DECAY_THRESHOLD_DAYS
    )

    # --- EHR-derived features ---
    recent_acute = state.get("recent_acute_events") or []
    features["ed_visits_since_discharge"] = sum(
        1 for e in recent_acute if e.get("type") == "ed_visit"
    )
    features["external_admissions_since_discharge"] = sum(
        1 for e in recent_acute if e.get("type") == "external_admission"
    )

    # --- Medication features ---
    med_events = state.get("medication_events") or []
    features["missed_refills_count"] = sum(
        1 for m in med_events if m.get("event_subtype") == "refill_missed"
    )
    therapeutic_classes = {m.get("therapeutic_class") for m in med_events
                            if m.get("event_subtype") == "refill"}
    features["has_diuretic_refill"]   = "diuretic" in therapeutic_classes
    features["has_hf_gdmt_refill"]    = "hf_gdmt" in therapeutic_classes
    features["has_insulin_refill"]    = "insulin" in therapeutic_classes

    # --- Care management interaction features ---
    interventions = state.get("intervention_history") or []
    features["outreach_attempts_total"] = sum(
        1 for i in interventions if i.get("interaction_type") == "outreach_attempted"
    )
    features["successful_contacts_total"] = sum(
        1 for i in interventions if i.get("contact_outcome") == "connected"
    )
    features["interventions_delivered_total"] = sum(
        1 for i in interventions if i.get("interaction_type") == "intervention_delivered"
    )

    # --- Demographic and SDOH features (loaded from discharge features) ---
    discharge_feats = state.get("discharge_features") or {}
    features["age_years"]            = discharge_feats.get("age_years")
    features["sex_band"]              = discharge_feats.get("sex_band")
    features["lives_alone"]           = discharge_feats.get("lives_alone", False)
    features["primary_language"]      = discharge_feats.get("primary_language", "en")
    features["adi_state_decile"]      = discharge_feats.get("adi_state_decile")
    features["transportation_flag"]   = discharge_feats.get("transportation_flag", False)
    features["food_insecurity_flag"]  = discharge_feats.get("food_insecurity_flag", False)

    # Persist to Feature Store. Online and offline parity is what makes
    # historical-prediction reproduction reliable for governance review.
    feature_record = [
        {"FeatureName": "patient_encounter_id",
         "ValueAsString": f"{state['patient_id']}:{state['encounter_id']}"},
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
            FeatureGroupName=POST_DISCHARGE_FEATURES_FG,
            Record=feature_record,
        )
    except Exception as e:
        # Production treats Feature Store write failures as a metric and
        # a DLQ; the teaching example continues so the demo runs without
        # a feature group provisioned.
        logger.warning("feature store write failed", extra={"error": str(e)})

    return features
```

A model with 50-150 features is typical for this problem. Trajectory features at multiple windows (3-day, 7-day, 14-day) plus patient-specific baselines plus engagement decay plus discharge-time features lands in that range. Past 200 features the marginal lift is usually small and the operational pain is large: drift detection becomes harder, feature pipeline maintenance becomes harder, and the feature-store data volume grows quickly enough that retraining queries get slow.

---

## Step 6: Score and Build the Explanation

The scoring service runs the composite model against the feature vector. The explanation builder combines SHAP values with a Bedrock-generated outreach narrative. The narrative is decision support: it suggests what the care manager should ask about, never what they should prescribe.

```python
def _feature_vector_to_array(features, feature_order):
    """Convert the dict-of-features into a numpy row vector for the model."""
    row = []
    for name in feature_order:
        v = features.get(name)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            row.append(0.0)
        elif isinstance(v, bool):
            row.append(1.0 if v else 0.0)
        elif isinstance(v, (int, float)):
            row.append(float(v))
        else:
            row.append(0.0)   # categorical features encoded upstream in production
    return np.array([row], dtype=float)


def score_via_sagemaker_endpoint(features, feature_order):
    """Invoke the deployed SageMaker endpoint with a feature vector.

    Production typically uses SageMaker batch transform for the daily
    sweep (cheaper at this cadence) and a real-time endpoint for the
    event-driven re-scoring path. Both accept the same feature payload;
    the difference is how invocation is triggered.
    """
    payload = ",".join(str(v) for v in _feature_vector_to_array(features, feature_order)[0])
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT_NAME,
        ContentType="text/csv",
        Body=payload,
    )
    body = response["Body"].read().decode("utf-8").strip()
    return float(body.split(",")[0])


def score_via_local_model(features, feature_order, local_model):
    """Score against a tiny in-process model, for the teaching example."""
    X = _feature_vector_to_array(features, feature_order)
    if hasattr(local_model, "predict_proba"):
        return float(local_model.predict_proba(X)[0, 1])
    return float(1.0 / (1.0 + math.exp(-float(local_model.decision_function(X)[0]))))


# Human-readable feature descriptions for the explanation layer. In
# production this is loaded from a versioned reference table maintained
# alongside the feature catalog.
FEATURE_DESCRIPTIONS = {
    "WEIGHT_current":                 "current weight (kg)",
    "WEIGHT_slope_3d":                "3-day weight slope (kg/day)",
    "WEIGHT_slope_7d":                "7-day weight slope (kg/day)",
    "WEIGHT_delta_from_baseline":     "weight delta from patient's baseline (kg)",
    "WEIGHT_deviation_score":         "weight deviation score from per-modality detector",
    "hf_weight_3d_increase_lb":        "3-day weight increase (lb)",
    "hf_weight_3lb_3d_alert":         "3-lb-in-3-days teaching threshold crossed",
    "hf_dyspnea_score":               "patient-reported dyspnea score",
    "hf_orthopnea_score":              "patient-reported orthopnea score",
    "SBP_current":                    "current systolic blood pressure",
    "SBP_slope_3d":                   "3-day systolic BP slope",
    "SBP_delta_from_baseline":        "systolic BP delta from baseline",
    "GLUCOSE_current":                 "current glucose",
    "GLUCOSE_max_3d":                 "3-day glucose maximum",
    "PEAK_FLOW_delta_from_baseline":  "peak flow delta from baseline",
    "SPO2_current":                   "current oxygen saturation",
    "days_since_last_data":           "days since last RPM or PRO data",
    "days_since_last_contact":        "days since last care management contact",
    "engagement_decay_flag":          "patient has stopped checking in",
    "ed_visits_since_discharge":      "ED visits since discharge",
    "missed_refills_count":           "missed prescription refills since discharge",
    "discharge_risk_score":           "discharge-time readmission risk score",
    "days_post_discharge":            "days since discharge",
    "transportation_flag":            "transportation barrier flag",
    "food_insecurity_flag":           "food insecurity flag",
}


def humanize_driver(feature_name, value):
    """Build a clinical-meaning string for a single driver."""
    description = FEATURE_DESCRIPTIONS.get(feature_name, feature_name)
    if isinstance(value, bool):
        value_str = "yes" if value else "no"
    elif isinstance(value, float):
        value_str = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        value_str = str(value)
    return f"{description}: {value_str}"


def compute_top_drivers(features, feature_order, model, top_n=5):
    """Compute approximate top contributing features.

    Production uses SageMaker Clarify (or SHAP directly against the
    deployed model) for per-prediction Shapley values. The teaching
    example uses a coefficient-times-standardized-value proxy.
    """
    X = _feature_vector_to_array(features, feature_order)[0]

    importances = None
    if hasattr(model, "feature_importances_"):
        importances = np.asarray(model.feature_importances_)
    elif hasattr(model, "coef_"):
        importances = np.asarray(model.coef_).flatten()

    contributions = []
    if importances is not None and len(importances) == len(X):
        # TODO (TechWriter): Code review WARNING 3. Within-sample standardization is mathematically nonsensical: np.mean(X) and np.std(X) compute the mean and standard deviation across feature values within a single observation (mixed scales: weight in kg, scores 0-1, day counts), not against training-data statistics per feature. The resulting "contributions" have no model-explanation meaning yet ship into worklist rows as the clinical_meaning column. The explanation_version field claims "shap_proxy" semantics the math does not deliver. Fix: replace with coef_ * X (linear models, partial contribution to logit) or feature_importances_ * X (tree models, importance-weighted feature value); update explanation_version to "importance_heuristic_plus_bedrock_v1" so the audit trail accurately names what was used.
        x_std = (X - np.mean(X)) / (np.std(X) + 1e-6)
        contribs = importances * x_std
        for i, name in enumerate(feature_order):
            contributions.append({
                "feature":       name,
                "value":         float(X[i]),
                "contribution":  float(contribs[i]),
            })

    contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)
    return contributions[:top_n]


def suggested_outreach_for(cohorts, top_drivers, engagement_status):
    """Build a structured outreach suggestion based on the top drivers
    and the patient's engagement status.

    The suggestion is decision support, not a decision. The care manager
    decides what to actually do; the suggestion just ranks what to ask
    about and what intervention options are typically available for the
    pattern.
    """
    primary_focus = "general_check_in"
    key_questions = []
    intervention_options = []

    driver_features = {d["feature"] for d in top_drivers}

    if "heart_failure" in cohorts:
        if "hf_weight_3lb_3d_alert" in driver_features or "WEIGHT_slope_3d" in driver_features:
            primary_focus = "weight_trend"
            key_questions.extend([
                "Are you taking your diuretic every morning as prescribed?",
                "Have you been more short of breath, especially walking or lying flat?",
                "How many pillows are you sleeping on?",
                "Any swelling in your ankles or legs?",
                "Any salty meals over the last few days?",
            ])
            intervention_options.extend([
                {"intervention": "diuretic_titration_per_standing_orders",
                 "applicability": "if_pharmacy_protocol_in_place"},
                {"intervention": "same_day_transitions_clinic_add_on",
                 "applicability": "if_capacity_today"},
                {"intervention": "home_health_visit_request",
                 "applicability": "if_eligible"},
            ])

    if "diabetes" in cohorts:
        if "GLUCOSE_max_3d" in driver_features or "dm_recent_high_glucose" in driver_features:
            primary_focus = "glucose_trend"
            key_questions.extend([
                "How are your glucose readings looking compared to your usual?",
                "Are you taking your insulin as prescribed?",
                "Any sick days or new medications since discharge?",
            ])

    if engagement_status.get("engagement_decay"):
        if primary_focus == "general_check_in":
            primary_focus = "engagement_drop"
        key_questions.insert(0, "We noticed you stopped checking in. Is everything okay?")

    return {
        "primary_focus":          primary_focus,
        "key_questions":          key_questions,
        "intervention_options":   intervention_options,
        "escalation_to_provider": (
            "Suggest provider review if trajectory continues despite "
            "intervention or if patient reports worsening symptoms at rest."
        ),
    }


def build_explanation(score_record, model, feature_order):
    """Assemble structured drivers plus a Bedrock-generated narrative."""
    features = score_record.get("_features_for_explanation") or {}
    state_table = dynamodb.Table(PATIENT_STATE_TABLE)
    state = _undecimalize(state_table.get_item(
        Key={"patient_id": score_record["patient_id"],
             "encounter_id": score_record["encounter_id"]}
    ).get("Item", {}))

    top_drivers = compute_top_drivers(features, feature_order, model, top_n=5)
    structured_drivers = [{
        "feature":           d["feature"],
        "value":             d["value"],
        "contribution":      round(d["contribution"], 4),
        "clinical_meaning":  humanize_driver(d["feature"], d["value"]),
    } for d in top_drivers if d["contribution"] > 0]

    engagement_status = {
        "engagement_decay":         features.get("engagement_decay_flag", False),
        "days_since_last_data":     features.get("days_since_last_data"),
        "days_since_last_contact":  features.get("days_since_last_contact"),
    }

    suggested = suggested_outreach_for(
        state.get("cohorts", []), structured_drivers, engagement_status
    )

    narrative = invoke_bedrock_narrative(
        score_record, structured_drivers, engagement_status,
        cohorts=state.get("cohorts", []),
        days_post_discharge=score_record["days_post_discharge"],
    )

    return {
        "score_id":             score_record["score_id"],
        "structured": {
            "composite_score":      float(score_record["composite_calibrated"]),
            "tier":                 score_record["tier"],
            "top_risk_drivers":     structured_drivers,
            "engagement_status":    engagement_status,
            "days_post_discharge":  score_record["days_post_discharge"],
        },
        "narrative":          narrative,
        "suggested_outreach": suggested,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "explanation_version": "shap_proxy_plus_bedrock_v1",
    }


def invoke_bedrock_narrative(score_record, top_drivers, engagement_status,
                              cohorts, days_post_discharge):
    """Generate a care-manager-facing narrative via Bedrock.

    Constrained prompt: cite drivers, suggest outreach focus areas, never
    recommend specific treatments. Always with human review; the LLM
    produces decision support, not decisions. Confirm the chosen Bedrock
    model is HIPAA-eligible under your AWS BAA before deploying.
    """
    drivers_text = "\n".join(
        f"- {d['clinical_meaning']} (contribution: {d['contribution']:+.3f})"
        for d in top_drivers
    ) or "(no strong drivers identified)"

    engagement_text = (
        f"Engagement decay flag: {engagement_status['engagement_decay']}; "
        f"days since last data: {engagement_status['days_since_last_data']}; "
        f"days since last contact: {engagement_status['days_since_last_contact']}."
    )

    prompt = (
        "You are summarizing a post-discharge readmission-risk score for "
        "a hospital care manager. You are not making a clinical judgment "
        "and you are not recommending specific treatments. You are "
        "translating the model's feature drivers into a care-manager-"
        "readable narrative that suggests outreach focus areas and the "
        "questions to ask. Cite the drivers. Note any pattern that is "
        "consistent with the drivers (heart-failure decompensation, "
        "diabetes-control issue, COPD exacerbation, engagement drop). "
        "End with the phrase 'This is decision support; clinical judgment "
        "governs.'\n\n"
        f"Cohorts: {', '.join(cohorts)}\n"
        f"Days post-discharge: {days_post_discharge:.1f}\n"
        f"Risk tier: {score_record['tier']}\n"
        f"Calibrated probability: {float(score_record['composite_calibrated']):.2f}\n"
        f"{engagement_text}\n\n"
        f"Top risk drivers:\n{drivers_text}\n\n"
        "Produce 2-4 sentences of plain narrative. No bullet points. "
        "No specific drug or dose recommendations."
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
        # Bedrock failure does not block worklist generation. Log, emit a
        # metric, and fall back to a structured-only summary.
        logger.warning("bedrock invocation failed", extra={"error": str(e)})
        _emit_metric("BedrockNarrativeFailed", 1)
        top_three = ", ".join(d["clinical_meaning"] for d in top_drivers[:3])
        return (
            f"Tier {score_record['tier']} with calibrated probability "
            f"{float(score_record['composite_calibrated']):.2f} at day "
            f"{days_post_discharge:.1f} post-discharge. Top drivers: "
            f"{top_three or 'none identified'}. This is decision support; "
            f"clinical judgment governs."
        )
```

A note on the SHAP proxy. The `coefficient times standardized value` shortcut is only directionally informative; production wires SageMaker Clarify (or the SHAP library directly against the deployed model) so the contribution numbers reflect actual local Shapley values. Without real SHAP, the explanation degrades from "useful" to "directionally correct," and the care management team's trust in the worklist drops accordingly.

---

## Step 7: Build and Publish the Worklist

The worklist builder ranks patients by composite tier, applies suppression rules, attaches explanations and suggested outreach, and produces the daily worklist that the care management team works through. This is the actual product. A perfect model with a worklist that nobody opens has zero value; a simple model with a clear, prioritized, actionable worklist that the team works religiously has substantial value.

```python
def check_suppression(state, score):
    """Apply suppression rules. A suppressed row is logged, not surfaced.

    Suppression categories:
    - Patient currently inpatient (already readmitted; the inpatient team
      has them)
    - Recently delivered intervention (cool-down window so we do not
      double-surface a patient who was just contacted)
    - Program window has ended (the patient graduated)
    - Explicit clinical-team-set hold (hospice, opt-out, etc.)
    """
    if state.get("is_currently_inpatient"):
        return {"suppressed": True, "reason": "patient_currently_inpatient"}

    interventions = state.get("intervention_history") or []
    if interventions:
        last = interventions[-1]
        last_at = last.get("occurred_at")
        if last_at and last.get("interaction_type") == "intervention_delivered":
            last_dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            cool_down = timedelta(hours=SUPPRESSION_AFTER_INTERVENTION_HOURS)
            if (datetime.now(timezone.utc) - last_dt) < cool_down:
                return {"suppressed": True, "reason": "recent_successful_intervention"}

    program_end_at = state.get("program_end_at")
    if program_end_at and datetime.now(timezone.utc).isoformat() > program_end_at:
        return {"suppressed": True, "reason": "program_window_ended"}

    if state.get("has_active_program_hold"):
        return {"suppressed": True, "reason": state.get("program_hold_reason", "explicit_hold")}

    return {"suppressed": False}


def current_capacity_for_cohorts(cohorts):
    """Return the daily worklist capacity for a cohort.

    Production loads this from a versioned table that the program
    operations team updates as staffing changes. Capacity caps the size
    of the daily worklist so the care management team works the top of
    the list with intent rather than skimming a long unmanageable list.
    """
    # Defaults for the demo: 25 rows per cohort per day. Real programs
    # vary substantially based on staffing.
    return {"max_rows": 25}


def apply_capacity_caps(sorted_rows, capacity):
    """Trim the worklist to the top N rows the team can realistically work."""
    return sorted_rows[: capacity.get("max_rows", 25)]


def build_worklist(date_iso, score_records, model, feature_order):
    """Build the daily worklist from a batch of scoring records.

    Production runs this as a Step Functions task after the scoring sweep
    completes. It pulls the latest score per patient from the scoring
    history, attaches explanations, applies suppression and de-duplication,
    sorts by tier, applies capacity caps, and publishes the worklist.
    """
    rows = []
    for score in score_records:
        if score is None:
            continue
        if score["tier"] == "below_threshold":
            continue

        state_table = dynamodb.Table(PATIENT_STATE_TABLE)
        state = _undecimalize(state_table.get_item(
            Key={"patient_id": score["patient_id"],
                 "encounter_id": score["encounter_id"]}
        ).get("Item", {}))

        suppression = check_suppression(state, score)
        if suppression["suppressed"]:
            logger.info("worklist row suppressed", extra={
                "patient_id":    score["patient_id"],
                "tier":          score["tier"],
                "reason":        suppression["reason"],
            })
            _emit_metric(f"Suppressed_{suppression['reason']}", 1)
            continue

        explanation = build_explanation(score, model, feature_order)

        rows.append({
            "patient_id":             score["patient_id"],
            "encounter_id":           score["encounter_id"],
            "cohorts":                state.get("cohorts", []),
            "tier":                   score["tier"],
            "composite_score":        float(score["composite_calibrated"]),
            "days_post_discharge":    score["days_post_discharge"],
            "top_drivers":            explanation["structured"]["top_risk_drivers"],
            "narrative":              explanation["narrative"],
            "suggested_outreach":     explanation["suggested_outreach"],
            "engagement_status":      explanation["structured"]["engagement_status"],
            "last_contact_at":        state.get("last_contact_at"),
            "last_data_at":           state.get("last_data_at"),
            "scoring_record_id":      score["score_id"],
        })

    # Sort by tier (tier_1 first), then by composite score descending
    # within tier. Care managers work top-down.
    tier_rank = {"tier_1": 0, "tier_2": 1, "tier_3": 2}
    sorted_rows = sorted(
        rows,
        key=lambda r: (tier_rank.get(r["tier"], 99), -r["composite_score"]),
    )

    capacity = current_capacity_for_cohorts(None)
    capped_rows = apply_capacity_caps(sorted_rows, capacity)

    worklist = {
        "worklist_id":             f"WL-{date_iso[:10]}-{uuid.uuid4().hex[:6]}",
        "date":                    date_iso[:10],
        "generated_at":            datetime.now(timezone.utc).isoformat(),
        "rows":                    capped_rows,
        "total_active_patients":   len(score_records),
        "total_surfaced":          len(capped_rows),
        "total_suppressed":        len(rows) - len(capped_rows) + (
            len(score_records) - len(rows)
        ),
    }

    table = dynamodb.Table(WORKLIST_STATE_TABLE)
    table.put_item(Item=_decimalize(worklist))

    eventbridge.put_events(Entries=[{
        "Source":      "post-discharge.worklist-builder",
        "DetailType":  "WorklistGenerated",
        "Detail":      json.dumps({
            "worklist_id":      worklist["worklist_id"],
            "date":             worklist["date"],
            "total_surfaced":   worklist["total_surfaced"],
        }, default=str),
        "EventBusName": POST_DISCHARGE_EVENTS_BUS,
    }])

    _emit_metric("WorklistsGenerated", 1)
    _emit_metric("WorklistRowsSurfaced", worklist["total_surfaced"])
    return worklist
```

The `total_suppressed` count in the worklist record matters more than the total surfaced count for governance review. A spike in suppressed rows ("recent_successful_intervention" jumped 40% this week) often means the team is working its head off and patients are getting interventions that the model would otherwise re-surface. A drop in suppressed rows can mean the team is short-staffed and not getting through their list. Track both numbers; report them weekly.

---

## Step 8: Capture Interventions and Outcomes

Care managers act on the worklist; their actions are recorded. Subsequent outcomes (readmission, ED visit, mortality, program graduation) are linked back to the alerts and interventions so the model has labels to learn from. Without this loop, the model drifts and nobody finds out until clinicians stop trusting the worklist.

```python
def on_care_manager_action(action_event):
    """Record a care manager's action on a worklist row.

    action_type is one of: outreach_attempted, contact_made,
    intervention_delivered, escalated.
    """
    valid_actions = {
        "outreach_attempted",
        "contact_made",
        "intervention_delivered",
        "escalated",
    }
    if action_event["action_type"] not in valid_actions:
        raise ValueError(f"invalid action_type: {action_event['action_type']}")

    intervention_record = {
        "intervention_id":    str(uuid.uuid4()),
        "patient_id":         action_event["patient_id"],
        "encounter_id":       action_event["encounter_id"],
        "worklist_id":        action_event.get("worklist_id"),
        "scoring_record_id":  action_event.get("scoring_record_id"),
        "action_type":        action_event["action_type"],
        "interaction_type":   action_event["action_type"],   # alias used by feature engine
        "intervention":       action_event.get("intervention"),
        "contact_outcome":    action_event.get("contact_outcome"),
        "notes":              action_event.get("notes"),
        "staff_id":           action_event.get("staff_id"),
        "occurred_at":        action_event["occurred_at"],
        "logged_at":          datetime.now(timezone.utc).isoformat(),
    }

    # Persist to the intervention-history table for audit and for the
    # feature engine to read on next scoring tick.
    table = dynamodb.Table(INTERVENTION_HISTORY_TABLE)
    table.put_item(Item=_decimalize(intervention_record))

    # Update the patient state with last-contact tracking. Idempotent.
    state_table = dynamodb.Table(PATIENT_STATE_TABLE)
    state = _undecimalize(state_table.get_item(
        Key={"patient_id": action_event["patient_id"],
             "encounter_id": action_event["encounter_id"]}
    ).get("Item", {}))
    if state:
        if action_event["action_type"] in ("contact_made", "intervention_delivered"):
            state["last_contact_at"] = action_event["occurred_at"]
        state.setdefault("intervention_history", []).append(intervention_record)
        # Trim to the last 30 entries to keep state-record size bounded.
        state["intervention_history"] = state["intervention_history"][-30:]
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        state_table.put_item(Item=_decimalize(state))

    _emit_metric(f"Action_{action_event['action_type']}", 1)
    if action_event.get("contact_outcome") == "connected":
        _emit_metric("SuccessfulContacts", 1)

    return intervention_record


def on_outcome_event(outcome_event):
    """Record a downstream clinical outcome and link it to recent alerts.

    outcome_event keys:
      type:        readmission | ed_visit | death | program_graduation |
                   observation_stay
      patient_id, encounter_id
      occurred_at: ISO8601 UTC
      details:     dict
    """
    state_table = dynamodb.Table(PATIENT_STATE_TABLE)
    state = _undecimalize(state_table.get_item(
        Key={"patient_id":   outcome_event["patient_id"],
             "encounter_id": outcome_event["encounter_id"]}
    ).get("Item", {}))
    if not state:
        logger.warning("outcome for unknown encounter",
                       extra={"patient_id": outcome_event["patient_id"]})
        return None

    occurred_dt = datetime.fromisoformat(
        outcome_event["occurred_at"].replace("Z", "+00:00")
    )
    discharge_dt = datetime.fromisoformat(
        state["discharge_at"].replace("Z", "+00:00")
    )
    days_post_discharge = (occurred_dt - discharge_dt).total_seconds() / 86400.0

    # Find recent alerts and interventions in the linkage window.
    history_table = dynamodb.Table(SCORING_HISTORY_TABLE)
    window_start = (occurred_dt - timedelta(hours=OUTCOME_LINKAGE_WINDOW_HOURS)).isoformat()
    score_response = history_table.query(
        KeyConditionExpression=(
            Key("patient_id").eq(outcome_event["patient_id"])
            & Key("scored_at").gte(window_start)
        ),
    )
    recent_score_ids = [_undecimalize(s)["score_id"]
                        for s in score_response.get("Items", [])
                        if _undecimalize(s).get("encounter_id") == outcome_event["encounter_id"]]

    intervention_table = dynamodb.Table(INTERVENTION_HISTORY_TABLE)
    intervention_response = intervention_table.query(
        KeyConditionExpression=(
            Key("patient_id").eq(outcome_event["patient_id"])
            & Key("occurred_at").gte(window_start)
        ),
    )
    recent_intervention_ids = [
        _undecimalize(i)["intervention_id"]
        for i in intervention_response.get("Items", [])
        if _undecimalize(i).get("encounter_id") == outcome_event["encounter_id"]
    ]

    # Label derivation. Readmission, ED visit (within window), death are
    # positive labels. Program graduation is a negative label. Observation
    # stay is positive in the composite outcome.
    label = 1 if outcome_event["type"] in {
        "readmission", "ed_visit", "death", "observation_stay"
    } else 0

    label_record = {
        "label_id":                  str(uuid.uuid4()),
        "patient_id":                outcome_event["patient_id"],
        "encounter_id":              outcome_event["encounter_id"],
        "outcome_type":              outcome_event["type"],
        "occurred_at":               outcome_event["occurred_at"],
        "days_post_discharge":       days_post_discharge,
        "cohorts":                   state.get("cohorts", []),
        "recent_score_ids":          recent_score_ids,
        "recent_intervention_ids":   recent_intervention_ids,
        "label":                     label,
        "details":                   outcome_event.get("details", {}),
        "labeled_at":                datetime.now(timezone.utc).isoformat(),
    }

    s3_client.put_object(
        Bucket=TRAINING_LABELS_BUCKET,
        Key=(
            f"outcomes/year={outcome_event['occurred_at'][:4]}/"
            f"month={outcome_event['occurred_at'][5:7]}/"
            f"{label_record['label_id']}.json"
        ),
        Body=json.dumps(label_record).encode("utf-8"),
        ServerSideEncryption="aws:kms",
    )

    # Readmissions close the program window for this encounter.
    if outcome_event["type"] in ("readmission", "death"):
        state["is_active"] = "false"
        state["program_end_reason"] = outcome_event["type"]
        state["program_end_at"] = outcome_event["occurred_at"]
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        state_table.put_item(Item=_decimalize(state))

    eventbridge.put_events(Entries=[{
        "Source":      "post-discharge.outcome-capture",
        "DetailType":  "OutcomeCaptured",
        "Detail":      json.dumps(label_record, default=str),
        "EventBusName": POST_DISCHARGE_EVENTS_BUS,
    }])

    _emit_metric(f"Outcome_{outcome_event['type']}", 1)
    return label_record
```

The label-derivation choice ("readmission OR ED visit OR death OR observation stay" as the positive class) is a clinical-governance decision. Some programs separate these (a 30-day readmission is the HRRP-relevant outcome; an ED visit is operationally informative but distinct). Audit a random sample of labeled cases monthly with the lead clinician and ask whether the label matches their expectation. Disagreement rate over 10% means the schema needs revisiting before the next retrain.

---

## Full Pipeline

Now string the pieces together. In production this function does not exist as a single callable; each step runs in its own compute container, orchestrated by EventBridge fan-out and Step Functions for the daily sweep. The single-function version here makes the data flow visible for teaching.

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
        "days_post_discharge", "discharge_risk_score",
        "cohort_heart_failure", "cohort_diabetes", "cohort_copd",
        "WEIGHT_current", "WEIGHT_slope_3d", "WEIGHT_slope_7d",
        "WEIGHT_delta_from_baseline", "WEIGHT_deviation_score",
        "hf_weight_3d_increase_lb", "hf_weight_3lb_3d_alert",
        "hf_dyspnea_score",
        "SBP_current", "SBP_slope_3d", "SBP_delta_from_baseline",
        "SBP_deviation_score",
        "HR_current", "HR_slope_3d",
        "GLUCOSE_current", "GLUCOSE_max_3d", "dm_recent_high_glucose",
        "PEAK_FLOW_delta_from_baseline", "SPO2_current", "copd_dyspnea_score",
        "days_since_last_data", "days_since_last_contact",
        "engagement_decay_flag", "ed_visits_since_discharge",
        "missed_refills_count", "has_diuretic_refill",
        "outreach_attempts_total", "successful_contacts_total",
        "transportation_flag", "food_insecurity_flag",
    ]

    # Synthesize a feature matrix with rough realistic ranges. Heart-failure
    # weight in kg, blood pressures in mmHg, glucose in mg/dL.
    X = np.column_stack([
        rng.uniform(1, 30, num_synthetic_patients),         # days_post_discharge
        rng.beta(2, 4, num_synthetic_patients),             # discharge_risk_score
        rng.binomial(1, 0.4, num_synthetic_patients),       # cohort_heart_failure
        rng.binomial(1, 0.3, num_synthetic_patients),       # cohort_diabetes
        rng.binomial(1, 0.2, num_synthetic_patients),       # cohort_copd
        rng.normal(95, 18, num_synthetic_patients),         # WEIGHT_current
        rng.normal(0.0, 0.4, num_synthetic_patients),       # WEIGHT_slope_3d
        rng.normal(0.0, 0.25, num_synthetic_patients),      # WEIGHT_slope_7d
        rng.normal(0.0, 1.5, num_synthetic_patients),       # WEIGHT_delta_from_baseline
        rng.beta(2, 6, num_synthetic_patients),             # WEIGHT_deviation_score
        rng.normal(0.5, 1.5, num_synthetic_patients),       # hf_weight_3d_increase_lb
        rng.binomial(1, 0.08, num_synthetic_patients),      # hf_weight_3lb_3d_alert
        rng.integers(0, 10, num_synthetic_patients),        # hf_dyspnea_score (0-10)
        rng.normal(125, 18, num_synthetic_patients),        # SBP_current
        rng.normal(0, 3, num_synthetic_patients),           # SBP_slope_3d
        rng.normal(0, 8, num_synthetic_patients),           # SBP_delta_from_baseline
        rng.beta(2, 6, num_synthetic_patients),             # SBP_deviation_score
        rng.normal(78, 14, num_synthetic_patients),         # HR_current
        rng.normal(0, 1.5, num_synthetic_patients),         # HR_slope_3d
        rng.normal(145, 45, num_synthetic_patients),        # GLUCOSE_current
        rng.normal(180, 60, num_synthetic_patients),        # GLUCOSE_max_3d
        rng.binomial(1, 0.1, num_synthetic_patients),       # dm_recent_high_glucose
        rng.normal(-10, 25, num_synthetic_patients),        # PEAK_FLOW_delta
        rng.normal(95, 3, num_synthetic_patients),          # SPO2_current
        rng.integers(0, 10, num_synthetic_patients),        # copd_dyspnea_score
        rng.exponential(1.5, num_synthetic_patients),       # days_since_last_data
        rng.exponential(3.0, num_synthetic_patients),       # days_since_last_contact
        rng.binomial(1, 0.15, num_synthetic_patients),      # engagement_decay_flag
        rng.binomial(1, 0.07, num_synthetic_patients),      # ed_visits_since_discharge
        rng.binomial(1, 0.05, num_synthetic_patients),      # missed_refills_count
        rng.binomial(1, 0.4, num_synthetic_patients),       # has_diuretic_refill
        rng.integers(0, 5, num_synthetic_patients),         # outreach_attempts_total
        rng.integers(0, 4, num_synthetic_patients),         # successful_contacts_total
        rng.binomial(1, 0.15, num_synthetic_patients),      # transportation_flag
        rng.binomial(1, 0.10, num_synthetic_patients),      # food_insecurity_flag
    ])

    # Synthesize a label that correlates with the readmission signature:
    # weight up + hf_3lb alert + engagement decay + ED visit + missed refill.
    risk_score = (
        0.7 * X[:, 6]                                # weight slope 3d
        + 0.6 * X[:, 10] / 3.0                       # 3-lb increase
        + 1.0 * X[:, 11]                              # 3-lb alert flag
        + 0.5 * X[:, 12] / 5.0                        # dyspnea score
        + 0.4 * X[:, 27]                              # engagement_decay
        + 1.0 * X[:, 28]                              # ed_visits
        + 0.5 * X[:, 29]                              # missed_refills
        + 0.6 * X[:, 1]                               # discharge risk score
        + rng.normal(0, 0.3, num_synthetic_patients)
    )
    y = (risk_score > np.percentile(risk_score, 78)).astype(int)

    model = LogisticRegression(max_iter=1000, random_state=random_state)
    model.fit(X, y)

    raw_probs = model.predict_proba(X)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_probs, y)

    return model, calibrator, feature_order


def run_post_discharge_pipeline(discharge_events, rpm_events, pro_events,
                                 ehr_events, model, calibrator, feature_order):
    """End-to-end post-discharge pipeline against a batch of events.

    Returns the worklist plus per-patient scoring records. Prints per-step
    progress so readers can trace the data flow.
    """
    print(f"[1/8] enrolling {len(discharge_events)} discharged patients")
    for d_event in discharge_events:
        on_discharge_event(d_event)

    print(f"[2/8] ingesting {len(rpm_events)} RPM measurements and "
          f"{len(pro_events)} PRO check-ins")
    canonical_events = []
    for raw in rpm_events:
        result = on_rpm_webhook(raw)
        # In production this returns immediately and the event flows
        # through Kinesis to the normalizer; the teaching example
        # publishes-and-also-applies in step 3.
        if result.get("statusCode") == 200:
            # Reconstruct the canonical event for inline processing.
            canonical_events.append({
                "event_id":     raw.get("event_id") or str(uuid.uuid4()),
                "patient_id":   resolve_patient_id_from_device(raw["device_id"]),
                "event_type":   "rpm_measurement",
                "modality":     next((k for k, v in RPM_LOINC.items()
                                       if v == raw["measurement_code"]), None),
                "value":        convert_to_canonical_units(
                                    raw["value"], raw["units"],
                                    next((k for k, v in RPM_LOINC.items()
                                          if v == raw["measurement_code"]), "WEIGHT")
                                ),
                "observed_at":  raw["measurement_time"],
                "units":        raw["units"],
                "device_id":    raw["device_id"],
                "quality_flags": raw.get("quality_flags", []),
                "received_at":  datetime.now(timezone.utc).isoformat(),
            })
    for raw in pro_events:
        canonical_events.append(on_pro_check_in(raw))
    for raw in ehr_events:
        # EHR-derived events are already in canonical shape for the demo.
        canonical_events.append(raw)

    print(f"[3/8] applying {len(canonical_events)} canonical events to state")
    for canonical in canonical_events:
        on_canonical_event(canonical)

    print("[4/8] running daily scoring sweep")
    score_records = []
    table = dynamodb.Table(PATIENT_STATE_TABLE)
    # TODO (TechWriter): Code review WARNING 2. GSI sweep without pagination here too; same silent-truncation risk as the daily_scoring_pipeline call site. Wrap in a LastEvaluatedKey loop or replace with a Step Functions Map state in production.
    response = table.query(
        IndexName="is_active-index",
        KeyConditionExpression=Key("is_active").eq("true"),
    )
    for item in response.get("Items", []):
        item = _undecimalize(item)
        print(f"[5-6/8] scoring {item['patient_id']}/{item['encounter_id']}")
        score_record = score_patient(
            patient_id=item["patient_id"],
            encounter_id=item["encounter_id"],
            trigger="daily",
            model=model,
            calibrator=calibrator,
            feature_order=feature_order,
        )
        if score_record is not None:
            score_records.append(score_record)

    print(f"[7/8] building worklist from {len(score_records)} scoring records")
    today_iso = datetime.now(timezone.utc).isoformat()
    worklist = build_worklist(today_iso, score_records, model, feature_order)
    print(f"   worklist: {worklist['total_surfaced']} rows surfaced of "
          f"{worklist['total_active_patients']} active patients")

    print("[8/8] intervention and outcome capture are event-triggered; "
          "call on_care_manager_action and on_outcome_event from "
          "the appropriate handlers")

    return worklist, score_records
```

Run this end-to-end against synthetic events from Synthea and you will see the full shape of the pipeline in your console. The output is a worklist record in DynamoDB, a set of scoring records with attached explanations, and a few CloudWatch metrics. In production the volume is orders of magnitude larger and the compute is orders of magnitude more distributed, but the function boundaries do not change.

---

## Gap to Production

Several things would need to change before you would deploy any of this against a live post-discharge program.

**Real RPM-vendor webhook validation.** The teaching example accepts an already-validated payload. Production validates each vendor's signature scheme (HMAC-SHA256 against a vendor secret in AWS Secrets Manager for BodyTrace and A&D Medical, JWT for Withings, etc.), rejects replays via timestamp windowing, and rate-limits per source IP. Skipping validation is how unauthenticated payloads end up in your data store.

**Real device-to-patient resolution.** The stub returns the device_id as the patient_id. Production maintains a device-assignments table keyed on device_id with the current patient_id, the assignment date, the program enrollment ID, and the device-vendor metadata. The lifecycle hooks (assign at enrollment, reassign on device replacement, unassign at program graduation, quarantine on suspected misuse) are their own integration project.

**Real FHIR R4 ingestion and HL7 v2 parsing.** EHR-side events flow as FHIR Observation, Encounter, MedicationDispense, and ServiceRequest resources, plus HL7 v2 ADT messages. Use a maintained library (`fhir.resources` or `python-hl7`) and a real integration engine (Mirth, Rhapsody, Cloverleaf, or vendor-supplied platform). The parser bug-class is silent corruption; invest in test cases that compare parsed output against vendor-supplied reference messages.

**Real SageMaker endpoint instead of in-process model.** Production hosts the composite model on a SageMaker batch transform job (cheaper for the daily cadence) plus a real-time endpoint for event-driven re-scoring, with model artifacts registered in the SageMaker Model Registry with versioning and approval workflow. The `score_via_sagemaker_endpoint` function shows the production-shape boto3 call; replacing the in-process call site is the swap, and the rest of the pipeline does not change.

**SageMaker Clarify for real SHAP explanations.** The `compute_top_drivers` function uses a crude proxy. Production uses SageMaker Clarify (or SHAP directly against the deployed model) to compute per-prediction Shapley values that reflect the model's actual reasoning. Without real SHAP, the explanation degrades to "directionally plausible" and care-manager trust drops.

**SageMaker Feature Store with point-in-time correctness.** The example writes a feature record but does not exercise the offline-online consistency or the point-in-time joins that production needs for retraining. A real deployment uses time-aware joins so historical worklist rows can be reproduced exactly, which is a clinical-governance requirement, not a nicety.

**SageMaker Model Monitor for drift and calibration tracking.** Production runs Model Monitor on the endpoint with baseline statistics from training data. Data drift (RPM device adoption shifts; cohort mix shifts), prediction drift (the model's score distribution shifts even when inputs do not), and quality drift (when labeled outcomes catch up) all produce CloudWatch alarms that the model team triages. Calibration drift is the one that bites quietly and matters most for operational threshold tuning.

**HIE and claims integration.** The teaching example sees only your own EHR feed, your own RPM, and your own PRO data. External-facility readmissions live in your regional HIE (where it exists) or the ACO/value-based-care claims feed (where you have one). Both involve contract-specific data-sharing agreements and per-region integration engineering. Without HIE or claims, your readmission outcome label is biased toward "patients who came back to us," which biases the model and the program effectiveness measurement.

**Care-management workflow integration.** The teaching example writes the worklist to DynamoDB and OpenSearch. Production publishes to Salesforce Health Cloud, Epic Healthy Planet, Innovaccer, Lumeris, ZeOmega Jiva, Lightbeam, or a custom-built tool. Each has its own API patterns, data models, and configuration constraints. Plan for substantial integration engineering. Some programs choose to build a thin care-manager-facing UI directly on AppSync rather than integrate with an existing CMS platform; this is reasonable when the existing platform cannot accommodate the data model but is its own significant build.

**Patient-facing SMS, IVR, and app integration.** PRO check-ins are delivered through specialist healthcare communication vendors (CipherHealth, GetWellNetwork, Memora Health, Cipher) that have BAAs and clinical-grade workflow features. AWS End User Messaging works for plain SMS. The integration boundary matters: keep PHI in HIPAA-eligible services; the patient-facing channel needs a BAA that explicitly covers the message content.

**Idempotency on every write.** RPM webhooks retry on network errors. Kinesis is at-least-once. Care-management UIs sometimes double-submit. Use `ConditionExpression` with `attribute_not_exists` on intervention creation, version counters on state updates that should overwrite by sequence, and recent-events deduplication caches keyed by event_id.

**IAM scoping per component.** The device-ingest Lambda needs Kinesis put on the patient-events stream and Secrets Manager read on the vendor secrets; it does not need Bedrock. The worklist-builder Lambda needs DynamoDB read/write on worklist-state and Bedrock invoke on the narrative model; it does not need Timestream write. Each role gets the minimum permissions for its job. Annual access review is the floor.

**VPC deployment.** Lambdas, SageMaker endpoints, Bedrock invocations, Comprehend Medical calls, and Timestream queries run inside a VPC with VPC endpoints for DynamoDB, S3, Kinesis, Timestream, SageMaker Runtime, Bedrock, EventBridge, and KMS. RPM vendor webhooks typically traverse the public internet (TLS-protected); some hospital networks require AWS PrivateLink-style routing for these.

**KMS customer-managed keys.** Every data-at-rest store (raw events lake, patient-state table, scoring history, worklist state, intervention history, training labels bucket, OpenSearch indices, Timestream database, CloudWatch Logs) is encrypted with customer-managed KMS keys scoped by role. Key policies restrict usage to the specific roles that need each key; CloudTrail data events audit the usage.

**Care management governance is not optional.** The detection pipeline is roughly 30% of the work. Care management governance, outreach protocols, equity considerations, the staffing model, and ongoing operational discipline are the other 70%. A pipeline without an active governance committee that meets monthly, reviews subgroup performance, reviews recent worklist outcomes, approves model updates, and owns the deployment criteria will not produce sustained results. Build the governance before the technology.

**Local validation before clinical deployment.** Whether the model is built in-house or supplied by a vendor (Epic readmission risk, LACE+, HOSPITAL, various commercial models), local validation against the hospital's own population is required. The validation should use a hold-out time period (not just patient split). It should include subgroup-stratified analysis. It should compare against the existing standard of care (the existing transitions-of-care program). Replicate the published model's reported AUROC on your own population before deploying; the absolute numbers usually drop, sometimes substantially, and the program operations team needs to know what to expect.

**Prospective shadow deployment.** Before any worklist routes to a care manager, run the model in shadow mode for several weeks: scoring patients, generating worklists, but not routing them to humans. Shadow worklists get reviewed retrospectively by the lead clinician to confirm the right patients are being surfaced. This catches feature-pipeline bugs, calibration issues that did not show up in retrospective validation, and operational integration problems. Shadow review is also when worklist volume gets calibrated to operational capacity. Skipping shadow has produced more failed deployments than any single technical issue.

**Subgroup performance monitoring.** Build dashboards that show AUROC, calibration ECE, alert rate, contact rate, intervention rate, and (when measurable) readmission-rate-change by age band, sex, race and ethnicity (where structurally captured), language, insurance status, neighborhood-level SES, and dual-eligibility status. If the program disproportionately under-surfaces a subgroup, that is a patient-safety and equity issue. If it over-surfaces a subgroup, that is also a problem (different problem, same signal). The clinical governance committee reviews these monthly.

**Equity-aware deployment design.** The deployment design matters as much as the model design. Some programs explicitly weight outreach toward higher-social-vulnerability populations regardless of model output; some run parallel non-digital monitoring tracks (community health workers, in-home check-ins) for populations that do not use digital channels well; some provide devices and language-appropriate engagement materials proactively. The right answer depends on the population and the program's mission. The wrong answer is to ignore the question and hope the model handles it.

**FDA SaMD determination.** Most "flag risk for care-manager review with transparent reasoning" deployments qualify for the 21st Century Cures Act CDS exemption. Higher-autonomy variants (closed-loop diuretic titration triggered by the model under standing orders) move closer to FDA medical device territory. Get the regulatory determination in writing from your regulatory affairs team before clinical deployment. Higher-autonomy or closed-loop variants may not qualify for the exemption.

**RPM and CCM CPT-code documentation.** RPM and chronic care management have specific CPT codes (99453, 99454, 99457, 99458 in the US, with documentation requirements). Production captures the time spent, the qualifying conditions, the signed consents, and the patient interactions in a way that supports the billing requirements. Programs that do not capture RPM-billable activity correctly leave revenue on the table that often funds the program.

**Decommissioning criteria.** A model can stop working. Performance can degrade enough that it should be turned off. Decommissioning criteria (calibration ECE above X, subgroup AUROC below Y, intervention success rate below Z) should be defined and pre-approved by the governance committee before deployment. Without pre-approved criteria, decommissioning becomes a political conversation rather than a clinical safety decision.

**Bedrock input and output handling.** Log the model ID, the prompt template version, and the response length. Never log the full prompt (contains clinical context and PHI-adjacent feature values) or the full response. Add a PHI scanner on the output path to catch accidental patient-identifier leakage if the LLM produces unexpected text; do not trust the model to be clean every time.

**Feedback loop hygiene.** The outcome-capture path writes labels. The retraining job reads them. Retraining can drift badly if labels are wrong, so audit quality monthly: sample 25 outcome events, ask the lead clinician whether the outcome type and timestamp match their memory, and track the disagreement rate. Over 10% disagreement and the label schema needs revisiting before the next retrain cycle.

**Monitoring and alarms.** Wire CloudWatch alarms on: end-to-end pipeline latency (event ingest to worklist update) p95 above target, worklist volume per care manager outside target range, intervention-success rate drifting, subgroup alert-rate ratios above fairness thresholds, Bedrock throttle rate above baseline, SageMaker endpoint p95 latency outside service-level targets, DynamoDB consumed capacity nearing provisioned, EventBridge delivery failures, Timestream query failures. Page the on-call data-engineering team and the model team's lead when critical alarms fire. Page the clinical lead when patient-safety-relevant alarms fire (worklist volume crashes to zero, calibration ECE above threshold, end-to-end latency way above target).

**Retention and legal hold.** Worklist records, scoring history, feature snapshots, and label files all carry PHI. Retain for the HIPAA baseline (6 years) plus any clinical-safety retention requirements. Use S3 Object Lock in COMPLIANCE mode for the training-labels bucket in production; GOVERNANCE is fine for dev and test. Apply legal hold for the duration of any active patient-safety event review.

**Multi-AZ and disaster recovery.** Post-discharge programs are less time-critical than inpatient deterioration, but they are still operationally important. The endpoint runs multi-AZ. The patient-state table replicates across AZs by default. The worklist builder runs in multiple AZs. Plan a DR drill quarterly; the fallback to the existing transitions-of-care program (manual call lists from the discharge planner) must be documented and the staff need to know that fallback exists when the system is down.

**Testing.** Table-driven unit tests on `map_to_tier`, `check_suppression`, `_compute_slope`, `compute_patient_baseline`, `convert_to_canonical_units`, and the cohort classifier; integration tests against DynamoDB Local and moto for the full state-update plus scoring flow; golden-path regression tests on a small labeled dataset run on every retrain so a model that breaks a subgroup does not slip through.

**Cost awareness.** API Gateway, Kinesis, Timestream, SageMaker endpoint hosting, Bedrock, OpenSearch, and Comprehend Medical (when used) are the major line items. Track cost-per-prevented-readmission (total monthly infrastructure cost divided by confirmed prevented-event count) alongside dollar-value-of-prevented-events (typical 30-day readmission cost in the US is $10,000-20,000). The infrastructure cost for a moderately-sized program (2,000 patients monitored at any time) is roughly in the $1,500-4,000/month range; preventing one to two readmissions per month covers the infrastructure. Outreach staffing (care managers, transitions nurses) is the dominant cost; one care manager at typical loaded cost runs more in a single month than the entire infrastructure.

None of this is unique to readmission risk anomaly detection. It is the cost of running any PHI-adjacent prediction service that influences care decisions at scale. The good news is that the infrastructure (event normalization, patient-state store, time-series feature engine, scoring endpoint, calibration layer, explanation builder, worklist builder, audit index) amortizes across Recipe 3.5 (lab outliers), 3.7 (inpatient deterioration), 7.x (predictive analytics), and 12.x (time-series forecasting). Build it once carefully, reuse it everywhere. The hard part is not the model. The hard part is the workflow integration, the outreach staffing, and the clinical governance, and that part starts on day one, not after the model passes validation.

---

*← [Main Recipe 3.8](chapter03.08-readmission-risk-anomaly-detection) · [Chapter 3 Preface](chapter03-preface)*
