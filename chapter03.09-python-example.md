# Recipe 3.9: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 3.9. It shows one way you could translate the cybersecurity / access-pattern anomaly detection pattern into working Python using Amazon Kinesis (for the canonical audit-event stream), Amazon DynamoDB (for the workforce-identity, patient-context, user-state, and case-state stores), Amazon Neptune (for the relationship graph; here represented by a tiny in-process NetworkX graph so the demo runs without a deployed cluster), Amazon Timestream (for per-user behavioral baselines), Amazon SageMaker (for the composite anomaly endpoint and Clarify SHAP explanations), Amazon Bedrock (for case-narrative generation), Amazon EventBridge (for case fan-out), Amazon OpenSearch Service (for the case audit index), Amazon S3 (for the raw-event lake and training labels), and Amazon CloudWatch (for operational metrics). It is not production-ready. There is no real EHR audit-log connector (Epic Audit Log API, Cerner Behavior Tracker, MEDITECH audit reports, athenahealth audit feeds each have their own authentication, schema, and pagination quirks), no FHIR R4 AuditEvent ingestion, no IdP integration (Okta, Azure AD, Active Directory each emit different token and event formats), no HRIS integration (Workday, UKG, SAP SuccessFactors), no scheduling-system integration (Kronos, Symplr, API Healthcare), no SIEM connector (Splunk HEC, Microsoft Sentinel Log Analytics, IBM QRadar, Chronicle), and no privacy-office case-management UI integration (Protenus, Imprivata FairWarning, Iatric, or a custom AppSync front end). Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you would wire into a hospital's privacy-monitoring program next week.
>
> The code maps to the eight core pseudocode steps from the main recipe: ingest and normalize an audit event from the EHR feed, enrich the event with identity and patient context, run the rules-engine detector for the policy-defined patterns (same-name, VIP, self-access, break-glass, off-hours), compute per-user behavioral baselines and per-feature deviation scores, run the graph-based relationship detector against the workforce-patient-encounter graph, combine detector outputs into a calibrated composite case score, build the investigator-facing case package with SHAP drivers and a Bedrock-generated narrative, and capture investigator outcomes for the retraining loop. The sequence-model variant (LSTM/Transformer over per-session click streams), the GNN-based representation-learning variant, the privileged-user monitoring program, and the patient-portal access monitoring path are not in this file; they are covered in the Variations and Why-This-Isn't-Production-Ready sections of the main recipe and share infrastructure with several other chapter recipes (3.6 for graph-based fraud patterns, 3.7 for calibration and tier mapping, 3.8 for engagement-decay and outcome-capture patterns, 13.x for knowledge-graph foundations).

---

## Setup

You will need the AWS SDK for Python plus scikit-learn, pandas, numpy, joblib, and NetworkX for the local demonstration:

```bash
pip install boto3 scikit-learn pandas numpy joblib networkx
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the `workforce-identity`, `workforce-schedule`, `patient-context`, `user-state`, `case-state`, and `suppression-rules` tables
- `kinesis:PutRecord`, `kinesis:PutRecords`, `kinesis:GetRecords`, `kinesis:GetShardIterator` on the `audit-events` stream
- `timestream:WriteRecords` on the `access-monitoring` database, `timestream:Select` on the `user_behavioral_baselines` table
- `neptune-db:ReadDataViaQuery`, `neptune-db:WriteDataViaQuery` on the relationship-graph cluster (when wired to real Neptune)
- `s3:GetObject` on the model-artifacts bucket; `s3:PutObject` on the raw-events lake and training-labels buckets
- `sagemaker-runtime:InvokeEndpoint` on the access-anomaly endpoint ARN
- `sagemaker-featurestore-runtime:GetRecord`, `sagemaker-featurestore-runtime:PutRecord` on the `access-anomaly-features-online` feature group
- `bedrock:InvokeModel` on the specific Bedrock model ARN you use (scope tightly; do not use `bedrock:*`)
- `events:PutEvents` on the `access-anomaly-events` and `case-bus` buses
- `cloudwatch:PutMetricData` for operational metrics
- The OpenSearch domain policy must allow the executing role to `es:ESHttpPost` and `es:ESHttpPut` on the `case-index`, `audit-event-archive`, and `score-history` indices

Scope each role to the specific resource ARNs it touches. The permissions above are fine for learning and will fail any serious IAM review. In production, each component (ehr-audit-ingest Lambda, app-audit-ingest Lambda, identity-log-ingest Lambda, break-glass-ingest Lambda, identity-context-loader Lambda, event-normalizer Lambda, enrichment Lambda, rules-engine Lambda, baseline-detector Lambda, graph-detector Lambda, composite-scoring Lambda, calibration Lambda, case-builder Lambda, outcome-capture Lambda, retraining Step Functions workflow) gets its own role with the minimum permissions for its job. The system ironically has to apply the same access-monitoring discipline to itself that it monitors elsewhere.

A few things worth knowing upfront:

- **No real EHR audit-log connector.** Production pulls events from Epic's Audit Log API, Cerner Behavior Tracker, MEDITECH audit reports, or athenahealth audit feeds. Each has its own authentication scheme, pagination model, schema, and latency profile. Plan 3-6 months of integration work per EHR vendor in scope, plus ongoing maintenance as the EHR upgrades. The teaching example accepts a pre-shaped event dict.
- **No FHIR R4 AuditEvent ingestion.** When the EHR exposes audit data through FHIR R4 AuditEvent resources, use a maintained library (`fhir.resources`) and a real integration engine (Mirth, Rhapsody, Cloverleaf, or a vendor-supplied platform) rather than hand-rolling the parser. The same library handles the related Provenance and Encounter resources that contribute to enrichment.
- **No IdP / HRIS / scheduling integration.** The enrichment pipeline is the project. Workday, Oracle HCM, SAP SuccessFactors, UKG, Kronos, Active Directory, Okta, Microsoft Entra ID each have their own data models and integration mechanisms. Refresh cadence matters: an HR record refreshed monthly produces stale enrichment for users who changed roles last week. The teaching example pre-loads tiny synthetic identity, schedule, and patient-context records into DynamoDB.
- **No real Neptune cluster.** Production runs the relationship graph on Amazon Neptune with Gremlin queries. The teaching example builds an in-process NetworkX graph so the relationship-detector path is runnable without provisioning a Neptune cluster. The `query_neptune_for_paths` function shows the production-shape Gremlin call you would use.
- **No SIEM or vendor patient-privacy-monitoring integration.** Production publishes high-tier cases to the SIEM (Splunk HEC, Microsoft Sentinel Log Analytics, IBM QRadar, Chronicle) and to the privacy-office case management system (Protenus, Imprivata FairWarning, Iatric, or a custom AppSync UI). The teaching example writes cases to DynamoDB and OpenSearch and stops.
- **DynamoDB table schemas.** `workforce-identity` is keyed on `workforce_id`. `workforce-schedule` is keyed on `workforce_id` (partition) and `shift_date` (sort). `patient-context` is keyed on `patient_id`. `user-state` is keyed on `workforce_id` and stores the rolling baseline summary, recent flag history, and a trailing window of suppression-pertinent metadata. `case-state` is keyed on `case_id`. `suppression-rules` is keyed on `workforce_id` (partition) and `rule_id` (sort) with a TTL attribute for automatic expiration after the validity window. You create these once, up front; this file does not do that for you.
- **All numeric values must be Decimal going into DynamoDB.** DynamoDB rejects Python `float` for numeric attributes. A composite calibrated score of `0.8137` becomes `Decimal("0.8137")` on the way in and back to float on the way out. The helper functions below handle this so you see the pattern. For an access-monitoring pipeline this matters operationally: a calibrated probability stored as `0.7999999999` from float drift, compared against a `0.80` tier-1 cut, produces the wrong privacy-office routing today and might produce the right one tomorrow if the threshold moves. That kind of drift is exactly the bug class clinical-governance review will flag, except here the governance is the joint privacy-and-infosec committee.
- **All example workforce, patient, and access-event data is synthetic.** Workforce IDs, patient IDs, encounter IDs, NPIs, device IDs, IP addresses, ZIP codes, and last names in the sample data are illustrative and do not refer to any real people, providers, or facilities. Never use real PHI or real workforce data in a teaching example.
- **The model in this example is a tiny in-process scikit-learn model.** Real deployments host the model behind a SageMaker batch transform pipeline (nightly cadence) or a real-time endpoint (event-driven re-scoring on high-priority triggers). We train a logistic regression on a small synthetic feature matrix at the bottom of the file so the scoring path runs end-to-end without a deployed endpoint. The `score_via_sagemaker_endpoint` function shows the production-shape boto3 call.
- **Calibration is shown as isotonic regression on a small held-out set.** Real calibration uses isotonic or Platt scaling fit on a substantial held-out validation set, then frozen and versioned alongside the model. Subgroup-stratified calibration (per role, per department) catches the systematic over- or under-confidence that a single calibration curve hides.
- **Privacy-office capacity is not simulated here.** The main recipe spends a lot of time on capacity-bounded prioritization for good reason. The example code generates cases regardless of available investigator capacity. In production, a capacity-cap step trims the case queue to the top-N rows the office can realistically work, with the next-N rows held in a backlog list that gets re-evaluated tomorrow.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here: thresholds, rule weights, peer-group definitions, baseline-window sizes, resource names, and routing tables. These are the knobs that move most often between dev, test, and production, and between joint privacy-and-infosec governance threshold reviews. Keep them at the top of the file so a reviewer can see the levers without wading through function bodies.

```python
import io
import json
import logging
import math
import uuid
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import boto3
import joblib
import networkx as nx
import numpy as np
import pandas as pd
from botocore.config import Config
from boto3.dynamodb.conditions import Key
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression

# Structured logging. Ship JSON records to CloudWatch Logs Insights. Audit
# events, workforce identities, patient identities, break-glass reasons,
# and case narratives all contain PHI or workforce PII. Log structural
# metadata only. Never log full audit payloads with workforce-and-patient
# identifiers, full feature vectors, raw break-glass reason text, or
# Bedrock prompts in application logs. The audit indexes (OpenSearch) and
# the case-state store (DynamoDB) are the right home for full payloads,
# behind KMS and CloudTrail data events.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling across DynamoDB, Timestream, Kinesis,
# SageMaker, and Bedrock with exponential backoff and jitter. Audit-event
# ingest is bursty (EHRs flush large batches at quarter-hour or top-of-hour
# boundaries; IdP and VPN logs spike at shift change), and adaptive mode
# keeps burst windows from cascading into retry storms against the
# enrichment cache and the scoring endpoint.
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
WORKFORCE_IDENTITY_TABLE = "workforce-identity"
WORKFORCE_SCHEDULE_TABLE = "workforce-schedule"
PATIENT_CONTEXT_TABLE    = "patient-context"
USER_STATE_TABLE         = "user-state"
CASE_STATE_TABLE         = "case-state"
SUPPRESSION_RULES_TABLE  = "suppression-rules"

AUDIT_EVENTS_STREAM = "audit-events"
TIMESTREAM_DATABASE = "access-monitoring"
TIMESTREAM_BASELINE_TABLE = "user_behavioral_baselines"

ACCESS_ANOMALY_FEATURES_FG = "access-anomaly-features-online"

RAW_EVENTS_BUCKET     = "my-access-monitoring-raw-events"
TRAINING_LABELS_BUCKET = "my-access-monitoring-training-labels"
MODEL_ARTIFACTS_BUCKET = "my-access-monitoring-model-artifacts"

CASE_BUS                  = "access-anomaly-events"
SAGEMAKER_ENDPOINT_NAME    = "access-anomaly-composite-prod"
BEDROCK_MODEL_ID           = "anthropic.claude-3-sonnet-20240229-v1:0"

# --- Detector Weights ---
# The composite scorer is a weighted sum of per-detector outputs. Per-cohort
# tuning catches systematic differences in how each detector class performs
# for different role categories. Production loads these from a versioned
# table that the joint privacy-and-infosec governance committee owns.
DEFAULT_DETECTOR_WEIGHTS = {
    "DEFAULT": {"rules": 0.40, "baseline": 0.20, "graph": 0.30, "sequence": 0.10},
    # Privileged users (DBAs, integration engineers) get more weight on
    # graph and baseline, less on rules, because the rule library is
    # designed primarily for clinical workforce behavior.
    "privileged_user": {"rules": 0.20, "baseline": 0.30, "graph": 0.40, "sequence": 0.10},
    # Clinical workforce gets the standard mix. Same-name and VIP rules
    # are high-yield here.
    "clinical_workforce": {"rules": 0.45, "baseline": 0.20, "graph": 0.25, "sequence": 0.10},
    # New users (under 90 days) get reduced rules weight because their
    # search-and-explore behavior trips the baseline detector for
    # learning reasons, not snooping reasons.
    "new_user": {"rules": 0.50, "baseline": 0.10, "graph": 0.30, "sequence": 0.10},
}

# --- Tier Thresholds ---
# Tier thresholds are cohort-stratified in production. Different role
# categories have different base rates of confirmed violation and
# different review costs per case. Production loads thresholds from a
# versioned DynamoDB table so the governance committee can update them
# without a code deploy.
DEFAULT_TIER_THRESHOLDS = {
    "DEFAULT":            {"tier_1": 0.80, "tier_2": 0.60, "tier_3": 0.40},
    "clinical_workforce": {"tier_1": 0.78, "tier_2": 0.58, "tier_3": 0.38},
    "privileged_user":    {"tier_1": 0.85, "tier_2": 0.65, "tier_3": 0.45},
    "new_user":           {"tier_1": 0.82, "tier_2": 0.62, "tier_3": 0.42},
}

# --- Rule Severity Weights ---
# Each rule emits a severity. The composite layer maps severity to a
# numeric confidence floor that the rules-block contributes to the
# composite. High-severity rules with high confidence dominate; low-
# severity rules add modestly.
RULE_SEVERITY_FLOOR = {
    "high":              0.90,
    "medium":            0.70,
    "low":               0.45,
    "policy_dependent":  0.50,   # interpretation depends on org policy
}

# --- Window Sizes ---
# Trajectory and baseline windows. Matching the main recipe; tunable per
# cohort in production.
BASELINE_LOOKBACK_DAYS         = 30   # rolling window for the per-user behavioral baseline
PEER_GROUP_LOOKBACK_DAYS       = 60   # peer-group baseline window (longer; smooths noise)
MIN_BASELINE_DAYS              = 14   # below this, fall back to peer-group baseline only
ACTIVITY_AGGREGATION_WINDOWS   = [1, 8, 24, 168, 720]   # hours; 1h, 8h, 1d, 7d, 30d

# --- Suppression Windows ---
SUPPRESSION_AFTER_DISMISSAL_DAYS = 30
CASE_GROUPING_WINDOW_DAYS         = 7   # group same user-patient cases within this window

# --- Name Uniqueness Reference (toy, for the demo) ---
# Production uses a real surname-frequency reference (US Census or
# equivalent regional dataset). Higher uniqueness = stronger same-name
# signal. Smith and Johnson are very common; Wojnarowski is uncommon.
SURNAME_UNIQUENESS = {
    "smith":         0.05,
    "johnson":       0.06,
    "williams":      0.07,
    "garcia":        0.08,
    "miller":        0.09,
    "davis":         0.10,
    "wojnarowski":   0.92,
    "kovalenko":     0.88,
    "abernathy":     0.78,
    "okonkwo":       0.85,
    "fitzgerald":    0.55,
    "DEFAULT":       0.40,   # fallback when surname is not in the reference
}

# --- ZIP Population Density Reference (toy, for the demo) ---
# Production uses Census tract or ZCTA population data. Small ZIPs
# (rural, small-town) are higher-signal for same-neighborhood detection
# because the prior probability of two unrelated people sharing the ZIP
# is lower.
SMALL_ZIP_THRESHOLD = 15000   # population
ZIP_POPULATION = {
    "14620": 9400,    # small-zip example used in the recipe sample case
    "10001": 24000,
    "60601": 12500,
    "94110": 32000,
    "DEFAULT": 25000,
}

# --- Cohort Inference ---
# The user role and tenure determine which threshold and detector-weight
# cohort the user lands in. Production loads this mapping from a
# governance-approved table.
PRIVILEGED_ROLES = {
    "database_administrator", "integration_engineer", "data_engineer",
    "it_analyst", "system_administrator", "ehr_analyst",
}
CLINICAL_ROLES = {
    "registered_nurse", "physician", "resident", "fellow", "physician_assistant",
    "nurse_practitioner", "pharmacist", "respiratory_therapist", "medical_assistant",
    "social_worker", "case_manager",
}
```

A quick note on the thresholds block. The values above are defaults chosen to make the teaching example produce a sensible mix of tier-1, tier-2, and tier-3 cases on a small synthetic dataset. A real deployment tunes them against a labeled backtest of historical privacy-office adjudications, then validates them prospectively in shadow mode before any case routes to a privacy-office investigator. The right cuts depend on the organization's confirmed-violation base rate, the privacy office's daily review capacity, the alert-fatigue budget, and the joint privacy-and-infosec governance committee's risk tolerance. These are dials, not physical constants, and the committee owns them.

---

## Step 1: Ingest and Normalize an Audit Event

The EHR audit feed publishes events on a near-real-time cadence. The ingest function parses the source-specific format, validates the schema, resolves the workforce identifier from the EHR-internal user ID to enterprise identity (Active Directory SID, Okta user ID), resolves the EHR-internal patient ID to the enterprise master patient identifier (EMPI), builds a canonical event, and writes it to the Kinesis stream. Every downstream component consumes the canonical shape; the source-specific differences live only in the parsers.

```python
def _to_decimal(value, precision="0.0001"):
    """Convert numeric input to Decimal for DynamoDB storage.

    DynamoDB rejects Python float for numeric attributes because float
    arithmetic introduces rounding drift that makes threshold comparisons
    unreliable over time. Always pass calibrated probabilities, deviation
    z-scores, and confidence values through Decimal on the way in and
    back out.
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

def resolve_workforce_id(ehr_user_id, source_format):
    """Map EHR-internal user ID to enterprise identity.

    Production maintains a per-source mapping table from EHR user
    identifier to Active Directory SID, Okta user ID, or the equivalent
    enterprise identifier. The teaching example assumes the EHR user
    ID already matches the enterprise identifier.
    """
    # In production:
    #   table = dynamodb.Table("user-id-mapping")
    #   response = table.get_item(Key={"source_user_id": ehr_user_id,
    #                                  "source_system":  source_format})
    #   return response.get("Item", {}).get("workforce_id")
    return ehr_user_id

def resolve_patient_id(ehr_patient_id, source_format):
    """Map EHR-internal patient ID to enterprise master patient identifier.

    Production calls the EMPI service (Verato, NextGate, vendor-specific
    Mirth-driven matching) for cross-system patient identity. The
    teaching example assumes the EHR patient ID is the EMPI.
    """
    return ehr_patient_id

def normalize_event_type(action_type):
    """Normalize source-specific action verbs to a canonical set."""
    canonical = {
        "view":          "view",
        "open":          "view",
        "read":          "view",
        "edit":          "edit",
        "modify":        "edit",
        "update":        "edit",
        "print":         "print",
        "export":        "export",
        "download":      "export",
        "search":        "search",
        "login":         "login",
        "auth":          "login",
        "break_glass":   "break_glass",
    }
    return canonical.get(action_type.lower(), action_type.lower())

def normalize_resource_type(resource):
    """Normalize source-specific resource labels to a canonical set."""
    canonical = {
        "chart":          "chart",
        "encounter":      "chart",
        "demographic":    "demographics",
        "demographics":   "demographics",
        "medication":     "medication_list",
        "medications":    "medication_list",
        "lab":            "lab_result",
        "lab_result":     "lab_result",
        "image":          "image",
        "imaging":        "image",
        "note":           "note",
        "progress_note":  "note",
        "order":          "order",
        "discharge":      "discharge_summary",
        "discharge_summary": "discharge_summary",
    }
    return canonical.get(resource.lower(), resource.lower())

def on_ehr_audit_event(raw_event, source_format):
    """Receive an EHR audit event, normalize, and put on the event stream.

    Production wires this as a Lambda triggered by the EHR audit-feed
    connector. The Lambda parses the source-specific payload, performs
    identity and patient resolution, builds the canonical event, and
    writes to Kinesis. The downstream enrichment Lambda picks it up.
    """
    workforce_id = resolve_workforce_id(raw_event["user_id"], source_format)
    if workforce_id is None:
        # Unknown workforce user. Could be a service account that lost its
        # mapping, a stale identifier, or a misconfigured feed. Production
        # routes to a quarantine queue for investigation; the teaching
        # example logs and drops.
        logger.warning("unknown workforce user",
                       extra={"ehr_user_id": raw_event["user_id"],
                              "source_format": source_format})
        return {"statusCode": 202, "reason": "unknown_workforce_user"}

    patient_id = resolve_patient_id(raw_event["patient_id"], source_format)

    canonical_event = {
        "event_id":             raw_event.get("event_id") or str(uuid.uuid4()),
        "workforce_id":         workforce_id,
        "patient_id":           patient_id,
        "source_system":        source_format,
        "event_type":           normalize_event_type(raw_event["action_type"]),
        "resource_type":        normalize_resource_type(raw_event["resource"]),
        "action":               raw_event["action_type"],
        "observed_at":          raw_event["event_time"],
        "received_at":          datetime.now(timezone.utc).isoformat(),
        "device_id":            raw_event.get("workstation_id"),
        "application_context":  raw_event.get("application_screen"),
        "ip_address":           raw_event.get("source_ip"),
        "session_id":           raw_event.get("session_id"),
        "break_glass":          bool(raw_event.get("break_glass_override", False)),
        "break_glass_reason":   raw_event.get("break_glass_reason"),
    }

    kinesis.put_record(
        StreamName=AUDIT_EVENTS_STREAM,
        Data=json.dumps(canonical_event, default=str).encode("utf-8"),
        PartitionKey=workforce_id,   # partition by user for ordering within a session
    )

    # Persist to the raw event lake for retrospective analysis and
    # retraining. Partitioning by date and source keeps Athena and
    # Glue happy.
    obs_at = canonical_event["observed_at"]
    s3_client.put_object(
        Bucket=RAW_EVENTS_BUCKET,
        Key=(
            f"source={source_format}/year={obs_at[:4]}/"
            f"month={obs_at[5:7]}/day={obs_at[8:10]}/"
            f"{canonical_event['event_id']}.json"
        ),
        Body=json.dumps(canonical_event, default=str).encode("utf-8"),
        ServerSideEncryption="aws:kms",
    )

    return {"statusCode": 200, "event_id": canonical_event["event_id"]}
```

Two things worth noting on this step. First, identifier resolution is where most production bugs live. Workforce IDs change when users move between facilities, Active Directory accounts get re-issued, and EHR user records sometimes outlive the underlying AD account. Patient identifiers change when EMPI matching merges duplicate records or splits incorrectly-merged ones. Each of these change events produces a window where audit events may resolve to the wrong workforce or patient identity. Production builds explicit handling for the change events and a reconciliation process for the historical audit log when a merge or split happens. Second, partitioning Kinesis by `workforce_id` preserves ordering within a session for the same user, which matters for the sequence-based detector that cares about click-path order. Partitioning by `event_id` would parallelize better but breaks the sequence assumption.

---

## Step 2: Enrich the Event with Identity, Schedule, and Patient Context

The enrichment Lambda joins the canonical event against the identity, scheduling, care-team, and patient-flag stores. Enrichment quality drives detection quality. Most production deployments report that the enrichment plumbing is the larger engineering investment than the detection algorithms, and the enrichment quality is the larger driver of false-positive rate.

```python
def is_off_hours(observed_at_iso, role):
    """Decide whether an access falls outside the user's typical working hours.

    A registered nurse on a normal day shift accessing at 3 a.m. is off-hours.
    A registered nurse on a night shift accessing at 3 a.m. is normal. The
    decision depends on the role's typical shift pattern. Production loads
    role-to-shift-window mappings from a versioned table.
    """
    obs_dt = datetime.fromisoformat(observed_at_iso.replace("Z", "+00:00"))
    hour = obs_dt.hour
    role_normal_windows = {
        "registered_nurse_day": (7, 19),
        "registered_nurse_night": (19, 7),
        "physician_day": (7, 19),
        "physician_night": (19, 7),
        "billing_analyst": (8, 18),
        "database_administrator": (8, 18),
        "default": (7, 19),
    }
    # Without per-user shift-pattern data, fall back to role default. The
    # cleaner production path is to use the actual scheduled-shift data
    # from Step 2's `scheduled_to_work` enrichment, which the rules
    # engine has access to.
    start, end = role_normal_windows.get(role, role_normal_windows["default"])
    if start < end:
        return not (start <= hour < end)
    # Wraps midnight (e.g., 19 to 7).
    return not (hour >= start or hour < end)

def is_off_shift(observed_at_iso, schedule):
    """Decide whether an access occurred while the user was off-shift."""
    if schedule is None:
        return True   # no scheduled shift on this date
    shift_start = schedule.get("shift_start")
    shift_end   = schedule.get("shift_end")
    if not shift_start or not shift_end:
        return False
    obs_dt = datetime.fromisoformat(observed_at_iso.replace("Z", "+00:00"))
    start_dt = datetime.fromisoformat(shift_start.replace("Z", "+00:00"))
    end_dt   = datetime.fromisoformat(shift_end.replace("Z", "+00:00"))
    return not (start_dt <= obs_dt <= end_dt)

def check_care_relationship(workforce_id, patient_id, as_of):
    """Look up documented care-relationship paths.

    Production queries Neptune for relationship paths through care_team,
    encounter, on_call, scheduling, order_signature, and documentation
    edges. The teaching example queries the in-process NetworkX graph
    that a later step builds. Returns a structured result with strength
    score (0..1).
    """
    graph = _global_graph()
    if graph is None:
        return {"has_any": False, "types": [], "strength_score": 0.0}

    # Direct path: workforce_id -> patient_id with up to 2 hops via care
    # relationship edges. Strength is graded by edge type.
    edge_strength = {
        "care_team":               1.0,
        "assigned_attending":      1.0,
        "assigned_nurse":          1.0,
        "on_call":                 0.9,
        "consult":                 0.85,
        "order_signature":         0.85,
        "documentation_authorship": 0.85,
        "scheduling":              0.7,
        "transitions_team":        0.65,
        "case_management":         0.65,
        "cross_coverage":          0.6,
        "team_membership":         0.5,
    }
    relationship_types_found = []
    best_strength = 0.0
    if graph.has_node(workforce_id) and graph.has_node(patient_id):
        # Direct edge
        if graph.has_edge(workforce_id, patient_id):
            edge_data = graph.get_edge_data(workforce_id, patient_id)
            edge_type = edge_data.get("type", "team_membership")
            relationship_types_found.append(edge_type)
            best_strength = max(best_strength,
                                edge_strength.get(edge_type, 0.5))
        # Two-hop path through encounter or department
        for neighbor in graph.neighbors(workforce_id):
            if graph.has_edge(neighbor, patient_id):
                first_hop = graph.get_edge_data(workforce_id, neighbor).get("type", "team_membership")
                second_hop = graph.get_edge_data(neighbor, patient_id).get("type", "team_membership")
                hop_strength = min(
                    edge_strength.get(first_hop, 0.4),
                    edge_strength.get(second_hop, 0.4),
                ) * 0.85   # decay across hops
                if hop_strength > best_strength:
                    best_strength = hop_strength
                    relationship_types_found.extend([first_hop, second_hop])

    return {
        "has_any":          len(relationship_types_found) > 0,
        "types":            list(set(relationship_types_found)),
        "strength_score":   best_strength,
    }

_GRAPH = None

def _global_graph():
    """Return the in-process relationship graph for the demo.

    Production reads from Amazon Neptune. The teaching example builds an
    in-process NetworkX graph at pipeline-init time so the relationship
    detector path is runnable without provisioning a Neptune cluster.
    """
    return _GRAPH

def geolocate_ip(ip_address):
    """Return a coarse geolocation label for an IP address.

    Production uses a maintained IP-to-geo service (MaxMind, IP2Location,
    or AWS Location Service) to identify country, region, and ISP. The
    teaching example returns a placeholder that distinguishes corporate
    vs external IPs by a CIDR prefix.
    """
    if ip_address is None:
        return {"network": "unknown", "country": "unknown"}
    if ip_address.startswith("10.") or ip_address.startswith("192.168."):
        return {"network": "corporate", "country": "us"}
    return {"network": "external", "country": "unknown"}

def is_unusual_for_user(workforce_id, geo):
    """Return True if the geo label is unusual for this user's history.

    Production queries Timestream or DynamoDB for the user's geo history
    and flags genuinely-new locations. The teaching example is a stub
    that flags any non-corporate network as unusual.
    """
    return geo.get("network") != "corporate"

def enrich_event(event):
    """Attach identity, schedule, care-team, and patient-flag enrichments."""
    identity_table = dynamodb.Table(WORKFORCE_IDENTITY_TABLE)
    identity_response = identity_table.get_item(
        Key={"workforce_id": event["workforce_id"]}
    )
    identity = _undecimalize(identity_response.get("Item")) or {}

    event["user_role"]         = identity.get("role")
    event["user_department"]   = identity.get("department")
    event["user_manager"]      = identity.get("manager_id")
    event["user_employment"]   = identity.get("employment_type")
    event["user_address_zip"]  = identity.get("address_zip")
    event["user_last_name"]    = (identity.get("last_name") or "").lower()
    event["user_hire_date"]    = identity.get("hire_date")

    days_since_hire = None
    if identity.get("hire_date"):
        hire_dt = datetime.fromisoformat(
            identity["hire_date"].replace("Z", "+00:00")
        )
        obs_dt = datetime.fromisoformat(
            event["observed_at"].replace("Z", "+00:00")
        )
        days_since_hire = (obs_dt - hire_dt).total_seconds() / 86400.0
    event["days_since_hire"] = days_since_hire

    # Workforce-link to patient identity. Some patients are also workforce
    # members (an employee who is a patient at the same facility); some
    # patients have a workforce-link via a household ID. Production
    # maintains both linkages with appropriate access controls.
    schedule_table = dynamodb.Table(WORKFORCE_SCHEDULE_TABLE)
    schedule_response = schedule_table.get_item(Key={
        "workforce_id": event["workforce_id"],
        "shift_date":   event["observed_at"][:10],
    })
    schedule = _undecimalize(schedule_response.get("Item"))
    event["scheduled_to_work"] = schedule is not None
    event["scheduled_unit"]    = schedule.get("unit") if schedule else None
    event["is_off_shift"]       = is_off_shift(event["observed_at"], schedule)
    event["is_off_hours"]       = is_off_hours(
        event["observed_at"],
        f"{event['user_role']}_day" if event.get("user_role") else "default",
    )

    # Care-relationship enrichment. The single most important enrichment
    # for distinguishing legitimate from problematic access.
    care = check_care_relationship(
        event["workforce_id"], event["patient_id"], event["observed_at"]
    )
    event["has_care_relationship"]      = care["has_any"]
    event["care_relationship_types"]    = care["types"]
    event["care_relationship_strength"] = care["strength_score"]

    # Patient context.
    patient_table = dynamodb.Table(PATIENT_CONTEXT_TABLE)
    patient_response = patient_table.get_item(
        Key={"patient_id": event["patient_id"]}
    )
    patient = _undecimalize(patient_response.get("Item")) or {}
    event["patient_sensitivity_flags"] = patient.get("sensitivity_flags", [])
    event["patient_is_employee"]       = bool(patient.get("is_workforce_member", False))
    event["patient_last_name"]         = (patient.get("last_name") or "").lower()
    event["patient_address_zip"]       = patient.get("address_zip")
    event["patient_household_id"]      = patient.get("household_id")
    event["patient_is_deceased"]       = bool(patient.get("is_deceased", False))
    event["patient_id_workforce_link"] = patient.get("workforce_id_link")

    # Network and device context.
    geo = geolocate_ip(event.get("ip_address"))
    event["geo_location"]    = geo
    event["is_off_network"]  = geo.get("network") != "corporate"
    event["is_unusual_geo"]  = is_unusual_for_user(event["workforce_id"], geo)

    return event
```

A note on enrichment failure modes. When the workforce-identity record is missing, the rules engine cannot evaluate same-name or off-hours rules. When the patient-context record is missing, sensitivity flags and same-address rules are silent. When the schedule record is missing, the off-shift rule defaults to "off-shift," which produces a flood of false positives for anyone whose schedule data wasn't loaded. Production wires explicit handling for each missing-data case (route to quarantine, default to a conservative interpretation, or both) and tracks the missing-enrichment rate as an operational metric. A spike in missing schedule records means the workforce-management feed is broken, not that the workforce suddenly started working off-shift.

---

## Step 3: Run the Rules-Engine Detector

The rules engine evaluates the explicit policy rules. Each rule is versioned, has a precise definition, and produces a flag with a per-rule confidence and a human-readable explanation. This is the highest-precision detector class for the bulk of healthcare-specific patterns: same-name, VIP, self-access, break-glass, off-hours. Don't dismiss the simple rules as unsophisticated; they're often the highest-precision component of the system.

```python
def compute_name_uniqueness(surname):
    """Return a 0..1 uniqueness score for a surname.

    Higher means rarer. Production uses a real surname-frequency reference
    (US Census or equivalent regional data); the demo uses the small
    SURNAME_UNIQUENESS table at the top of the file.
    """
    if not surname:
        return 0.0
    return SURNAME_UNIQUENESS.get(surname.lower(), SURNAME_UNIQUENESS["DEFAULT"])

def zip_population(zip_code):
    """Return population for a ZIP code (or a default if not in the table)."""
    if not zip_code:
        return ZIP_POPULATION["DEFAULT"]
    return ZIP_POPULATION.get(zip_code, ZIP_POPULATION["DEFAULT"])

def is_member_of_household(workforce_id, household_id):
    """Lookup whether a workforce member is in a household.

    Production maintains a workforce-to-household linkage table fed from
    HRIS dependent and address data, with appropriate access controls.
    The teaching example returns False; the household_id linkage path is
    documented but not exercised in the demo.
    """
    return False

def severity_from_break_glass_reason(reason_text):
    """Infer severity from the documented break-glass reason text.

    Specific clinical reasons get medium severity (the override is
    plausibly justified). Vague or absent reasons get high severity
    (the override may not be justified). Production uses a tuned
    classifier; the teaching example uses keyword heuristics.
    """
    if not reason_text:
        return "high"
    reason_lower = reason_text.lower()
    specific_keywords = [
        "code blue", "rapid response", "stroke alert", "trauma",
        "cardiac arrest", "consult requested by", "transfer of care",
        "covering for", "on-call coverage", "emergency consult",
    ]
    vague_keywords = [
        "review", "check", "look up", "verify", "see patient",
    ]
    if any(k in reason_lower for k in specific_keywords):
        return "medium"
    if any(k in reason_lower for k in vague_keywords):
        return "high"
    return "medium"

def run_rules_engine(event):
    """Evaluate the rule library against the enriched event.

    Returns a list of flag dicts with rule_id, severity, confidence, and
    a structured evidence payload. The composite scorer combines the
    flag list into a rules-confidence number and the case builder uses
    the evidence payloads in the investigator-facing display.
    """
    flags = []

    # RULE-001: Same last name with no documented care relationship.
    # Family-relationship access is the most common policy violation by
    # volume; same-name is the strongest single signal. Weighted by name
    # uniqueness so a Smith-on-Smith hit is much weaker than a
    # Wojnarowski-on-Wojnarowski hit.
    if (event.get("user_last_name")
            and event.get("patient_last_name")
            and event["user_last_name"] == event["patient_last_name"]
            and not event.get("has_care_relationship")):
        uniqueness = compute_name_uniqueness(event["user_last_name"])
        flags.append({
            "rule_id":     "RULE-001-SAME-LAST-NAME-NO-CARE",
            "severity":    "high",
            "confidence":  uniqueness,
            "evidence": {
                "user_last_name":     event["user_last_name"],
                "patient_last_name":  event["patient_last_name"],
                "name_uniqueness":    uniqueness,
            },
            "explanation": (
                f"User and patient share last name '{event['user_last_name']}' "
                f"(uniqueness {uniqueness:.2f}); no documented care "
                f"relationship found at access time."
            ),
        })

    # RULE-002 / RULE-003: Same household / same neighborhood.
    if (event.get("user_address_zip")
            and event.get("patient_address_zip")
            and event["user_address_zip"] == event["patient_address_zip"]):
        if (event.get("patient_household_id")
                and is_member_of_household(event["workforce_id"],
                                            event["patient_household_id"])):
            flags.append({
                "rule_id":    "RULE-002-SAME-HOUSEHOLD-NO-CARE",
                "severity":   "high",
                "confidence": 0.95,
                "evidence": {
                    "household_id": event["patient_household_id"],
                },
                "explanation": (
                    "User and patient share an HR-linked household; "
                    "no care relationship found."
                ),
            })
        elif (zip_population(event["user_address_zip"]) < SMALL_ZIP_THRESHOLD
              and not event.get("has_care_relationship")):
            flags.append({
                "rule_id":    "RULE-003-SAME-NEIGHBORHOOD-NO-CARE",
                "severity":   "medium",
                "confidence": 0.65,
                "evidence": {
                    "zip":              event["user_address_zip"],
                    "zip_population":   zip_population(event["user_address_zip"]),
                },
                "explanation": (
                    f"User home ZIP and patient home ZIP both "
                    f"{event['user_address_zip']} (small ZIP, "
                    f"{zip_population(event['user_address_zip'])} residents); "
                    f"no care relationship."
                ),
            })

    # RULE-010: Self-access. Severity is policy-dependent: some orgs allow
    # self-access for accessing one's own records, some forbid it.
    if (event.get("patient_id_workforce_link")
            and event["patient_id_workforce_link"] == event["workforce_id"]):
        flags.append({
            "rule_id":    "RULE-010-SELF-ACCESS",
            "severity":   "policy_dependent",
            "confidence": 1.0,
            "evidence": {
                "workforce_id":  event["workforce_id"],
                "patient_id":    event["patient_id"],
            },
            "explanation": (
                "User is accessing their own patient record. "
                "Severity depends on org policy."
            ),
        })

    # RULE-020: Sensitive-patient access without strong care relationship.
    if ("VIP" in (event.get("patient_sensitivity_flags") or [])
            and event.get("care_relationship_strength", 0.0) < 0.8):
        flags.append({
            "rule_id":    "RULE-020-VIP-WEAK-CARE",
            "severity":   "high",
            "confidence": 0.85,
            "evidence": {
                "sensitivity_flags": event["patient_sensitivity_flags"],
                "care_strength":      event.get("care_relationship_strength"),
            },
            "explanation": (
                "Access to VIP-flagged patient without a strong care "
                "relationship."
            ),
        })

    # RULE-021: Co-worker access without strong care relationship.
    if (event.get("patient_is_employee")
            and event.get("care_relationship_strength", 0.0) < 0.8):
        flags.append({
            "rule_id":    "RULE-021-EMPLOYEE-PATIENT-WEAK-CARE",
            "severity":   "high",
            "confidence": 0.80,
            "evidence": {
                "care_strength": event.get("care_relationship_strength"),
            },
            "explanation": (
                "Access to a workforce-member patient without a strong "
                "care relationship."
            ),
        })

    # RULE-030: Break-glass override. Always flagged for review; severity
    # tuned by reason quality.
    if event.get("break_glass"):
        severity = severity_from_break_glass_reason(
            event.get("break_glass_reason")
        )
        flags.append({
            "rule_id":    "RULE-030-BREAK-GLASS-OVERRIDE",
            "severity":   severity,
            "confidence": 1.0,
            "evidence": {
                "reason":             event.get("break_glass_reason"),
                "care_relationship":  event.get("has_care_relationship"),
                "sensitivity_flags":  event.get("patient_sensitivity_flags"),
            },
            "explanation": (
                f"Break-glass override used. Reason: "
                f"'{event.get('break_glass_reason') or '(none provided)'}'."
            ),
        })

    # RULE-040: Off-hours access by users on standard daytime schedules
    # without scheduled coverage.
    if (event.get("is_off_hours")
            and not event.get("scheduled_to_work")
            and event.get("user_employment") in ("employee", "contractor")):
        flags.append({
            "rule_id":    "RULE-040-OFF-HOURS-NO-SCHEDULE",
            "severity":   "low",
            "confidence": 0.50,
            "evidence": {
                "observed_at":  event["observed_at"],
                "user_role":    event.get("user_role"),
            },
            "explanation": (
                "Access outside the user's role-typical hours and no "
                "scheduled shift on this date."
            ),
        })

    # RULE-050: Deceased patient access without care relationship.
    if (event.get("patient_is_deceased")
            and not event.get("has_care_relationship")):
        flags.append({
            "rule_id":    "RULE-050-DECEASED-PATIENT-NO-CARE",
            "severity":   "medium",
            "confidence": 0.70,
            "evidence": {},
            "explanation": (
                "Access to a deceased patient's record without a "
                "documented care relationship."
            ),
        })

    # RULE-060: Print or export with weak care relationship or sensitivity
    # flags.
    if (event.get("event_type") in ("print", "export")
            and (event.get("patient_sensitivity_flags")
                 or event.get("care_relationship_strength", 0.0) < 0.5)):
        flags.append({
            "rule_id":    "RULE-060-EXPORT-WEAK-CARE",
            "severity":   "medium",
            "confidence": 0.70,
            "evidence": {
                "event_type":         event["event_type"],
                "sensitivity_flags":  event.get("patient_sensitivity_flags"),
                "care_strength":      event.get("care_relationship_strength"),
            },
            "explanation": (
                f"{event['event_type'].title()} action on a record with "
                f"weak care relationship or sensitivity flags."
            ),
        })

    return flags

def max_severity_confidence(flags):
    """Combine a flag list into a single rules-confidence score."""
    if not flags:
        return 0.0
    # Take the maximum confidence weighted by severity floor. A high-
    # severity rule with confidence 0.81 beats a low-severity rule with
    # confidence 1.0.
    max_score = 0.0
    for f in flags:
        floor = RULE_SEVERITY_FLOOR.get(f["severity"], 0.5)
        score = max(f.get("confidence", 0.0), floor)
        if score > max_score:
            max_score = score
    return max_score
```

The rule-set above is a small subset of what production runs. A mature program has dozens to hundreds of rules covering same-employer access, public-figure access driven by a news-watch feed, search-without-chart-open patterns, deceased-patient access patterns, account-abandonment-then-reactivation patterns, and many more. Rules are precise, explainable, defensible in front of a workforce member ("you triggered the same-last-name rule and the access does not match a documented care relationship"), and fast to compute. The rules engine does the bulk of the practical detection. Treat it as first-class, not as a fallback.

---

## Step 4: Compute Per-User Behavioral Baselines and Detect Deviations

For each workforce member, the baseline detector establishes a multi-dimensional profile of normal behavior (typical hours, volume, sequence, resource mix) and flags deviations against the user's own history and against a peer-group distribution. This is the classic UEBA backbone, applied with healthcare-specific feature engineering.

```python
def derive_peer_group(role, department, shift_pattern):
    """Compose a peer-group identifier from role, department, and shift.

    Peer-group definition is one of the most consequential design choices
    in the entire system. Bad peer groups produce bad baselines and bad
    alerts. Production tunes peer groups against historical adjudicated
    cases; this stub uses a simple concatenation.
    """
    return f"{role or 'unknown'}|{department or 'unknown'}|{shift_pattern or 'unknown'}"

def aggregate_user_activity(workforce_id, window_hours, ending_at):
    """Aggregate a user's recent activity over a window.

    Production reads from Timestream for the per-user time-series of
    counts, plus DynamoDB for the per-user state record that holds the
    rolling counters. The teaching example reads from the user-state
    table only and synthesizes the per-window aggregates from a small
    in-memory event window.
    """
    table = dynamodb.Table(USER_STATE_TABLE)
    response = table.get_item(Key={"workforce_id": workforce_id})
    state = _undecimalize(response.get("Item")) or {}

    recent_events = state.get("recent_events", [])
    end_dt = datetime.fromisoformat(ending_at.replace("Z", "+00:00"))
    start_dt = end_dt - timedelta(hours=window_hours)

    in_window = []
    for e in recent_events:
        e_dt = datetime.fromisoformat(e["observed_at"].replace("Z", "+00:00"))
        if start_dt <= e_dt <= end_dt:
            in_window.append(e)

    if not in_window:
        return {
            "event_count":                       0,
            "unique_patients":                   0,
            "unique_resource_types":             0,
            "export_count":                      0,
            "print_count":                       0,
            "break_glass_count":                 0,
            "off_hours_fraction":                0.0,
            "never_seen_before_fraction":        0.0,
            "sensitive_patient_fraction":        0.0,
            "weak_care_relationship_fraction":   0.0,
        }

    unique_patients = {e["patient_id"] for e in in_window}
    unique_resources = {e.get("resource_type") for e in in_window if e.get("resource_type")}
    seen_before = set(state.get("known_patients", []))
    sensitive = sum(1 for e in in_window if e.get("patient_sensitivity_flags"))
    weak_care = sum(1 for e in in_window
                    if e.get("care_relationship_strength", 1.0) < 0.5)
    off_hours = sum(1 for e in in_window if e.get("is_off_hours"))

    return {
        "event_count":                     len(in_window),
        "unique_patients":                 len(unique_patients),
        "unique_resource_types":           len(unique_resources),
        "export_count":                    sum(1 for e in in_window if e.get("event_type") == "export"),
        "print_count":                     sum(1 for e in in_window if e.get("event_type") == "print"),
        "break_glass_count":               sum(1 for e in in_window if e.get("break_glass")),
        "off_hours_fraction":              off_hours / len(in_window),
        "never_seen_before_fraction":      sum(1 for p in unique_patients if p not in seen_before) / max(len(unique_patients), 1),
        "sensitive_patient_fraction":      sensitive / len(in_window),
        "weak_care_relationship_fraction": weak_care / len(in_window),
    }

def get_user_baseline(workforce_id):
    """Load the per-user historical baseline from the user-state store.

    Production stores the baseline as a rolling-window summary refreshed
    nightly (or on a faster cadence for very active users). The summary
    holds the mean and standard deviation per feature, plus the first-
    observed timestamp for cold-start handling.
    """
    table = dynamodb.Table(USER_STATE_TABLE)
    response = table.get_item(Key={"workforce_id": workforce_id})
    state = _undecimalize(response.get("Item")) or {}
    baseline = state.get("behavioral_baseline") or {}
    return {
        "mean":              baseline.get("mean", {}),
        "std":               baseline.get("std", {}),
        "first_observed":    baseline.get("first_observed"),
        "shift_pattern":     state.get("shift_pattern", "unknown"),
    }

def get_peer_baseline(peer_group_id):
    """Load the peer-group baseline.

    Production maintains peer-group baselines in a versioned reference
    table refreshed nightly from the aggregated user-state data. The
    teaching example returns a synthetic baseline.
    """
    table = dynamodb.Table(USER_STATE_TABLE)
    response = table.get_item(Key={"workforce_id": f"PEER_BASELINE::{peer_group_id}"})
    state = _undecimalize(response.get("Item")) or {}
    baseline = state.get("behavioral_baseline") or {}
    return {
        "mean":  baseline.get("mean", {}),
        "std":   baseline.get("std", {}),
    }

# Feature weights tune which deviations matter most. Export volume and
# sensitive-patient fraction are weighted higher because they represent
# higher-stakes patterns; off-hours fraction is weighted lower because
# it has higher false-positive rate in clinical workforce.
FEATURE_WEIGHTS = {
    "events_count_24_hour":             1.0,
    "events_count_1_hour":              0.8,
    "unique_patients_24_hour":          1.0,
    "unique_patients_7_day":            0.8,
    "export_count_24_hour":             2.0,
    "export_count_7_day":               2.0,
    "print_count_24_hour":              1.5,
    "break_glass_count_7_day":          1.5,
    "off_hours_fraction_24_hour":       0.6,
    "new_patient_fraction_24_hour":     1.2,
    "sensitive_patient_fraction_24_hour": 1.8,
    "weak_care_fraction_24_hour":       1.5,
}

def weighted_max_z(per_feature_z, weights):
    """Compute a weighted aggregate of feature z-scores.

    Max-of-z catches the strongest single deviation; the per-feature
    weight skews the aggregate toward the higher-stakes features. A
    weighted Mahalanobis distance would be more theoretically clean
    but max-of-z works well in practice and explains better.
    """
    weighted = []
    for feature, z in per_feature_z.items():
        w = weights.get(feature, 1.0)
        weighted.append(abs(z) * w)
    return max(weighted) if weighted else 0.0

def days_since(timestamp_iso):
    """Compute days since an ISO-8601 timestamp."""
    if timestamp_iso is None:
        return 0.0
    obs_dt = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
    now_dt = datetime.now(timezone.utc)
    return (now_dt - obs_dt).total_seconds() / 86400.0

def run_baseline_detector(event):
    """Compute per-user and peer-group deviation scores.

    Multiple windows in parallel catch fast and slow shifts. The weighted
    max-of-z aggregate gives a single deviation score that the composite
    layer consumes. SHAP-style feature attribution is preserved in the
    per-feature z-score dict for the explanation layer.
    """
    workforce_id = event["workforce_id"]
    feature_vector = {}

    # Aggregate per-window features. Production runs these queries against
    # Timestream and DynamoDB; the teaching example uses an in-memory
    # event window.
    windows = [(1, "1_hour"), (8, "8_hour"), (24, "24_hour"),
               (168, "7_day"), (720, "30_day")]
    for window_hours, suffix in windows:
        agg = aggregate_user_activity(workforce_id, window_hours, event["observed_at"])
        feature_vector[f"events_count_{suffix}"]              = agg["event_count"]
        feature_vector[f"unique_patients_{suffix}"]            = agg["unique_patients"]
        feature_vector[f"unique_resources_{suffix}"]           = agg["unique_resource_types"]
        feature_vector[f"export_count_{suffix}"]               = agg["export_count"]
        feature_vector[f"print_count_{suffix}"]                = agg["print_count"]
        feature_vector[f"break_glass_count_{suffix}"]          = agg["break_glass_count"]
        feature_vector[f"off_hours_fraction_{suffix}"]         = agg["off_hours_fraction"]
        feature_vector[f"new_patient_fraction_{suffix}"]       = agg["never_seen_before_fraction"]
        feature_vector[f"sensitive_patient_fraction_{suffix}"]  = agg["sensitive_patient_fraction"]
        feature_vector[f"weak_care_fraction_{suffix}"]         = agg["weak_care_relationship_fraction"]

    # Patient-specific baseline.
    user_baseline = get_user_baseline(workforce_id)
    per_feature_z = {}
    for feature_name, feature_value in feature_vector.items():
        baseline_mean = user_baseline["mean"].get(feature_name, feature_value)
        baseline_std  = user_baseline["std"].get(feature_name, 1.0) or 1.0
        per_feature_z[feature_name] = (feature_value - baseline_mean) / max(baseline_std, 1e-6)

    # Peer-group baseline.
    peer_group_id = derive_peer_group(
        event.get("user_role"),
        event.get("user_department"),
        user_baseline["shift_pattern"],
    )
    peer_baseline = get_peer_baseline(peer_group_id)
    per_feature_peer_z = {}
    for feature_name, feature_value in feature_vector.items():
        peer_mean = peer_baseline["mean"].get(feature_name, feature_value)
        peer_std  = peer_baseline["std"].get(feature_name, 1.0) or 1.0
        per_feature_peer_z[feature_name] = (feature_value - peer_mean) / max(peer_std, 1e-6)

    composite_user_z = weighted_max_z(per_feature_z, FEATURE_WEIGHTS)
    composite_peer_z = weighted_max_z(per_feature_peer_z, FEATURE_WEIGHTS)

    # Cold-start handling: new users with insufficient history fall back
    # to peer-group comparison only.
    baseline_age_days = days_since(user_baseline.get("first_observed"))
    if baseline_age_days < MIN_BASELINE_DAYS:
        composite = composite_peer_z
        baseline_source = "peer_only_cold_start"
    else:
        composite = max(composite_user_z, composite_peer_z)
        baseline_source = "patient_specific_and_peer"

    # Sigmoid maps the unbounded weighted-z to a 0..1 score.
    deviation_score = 1.0 / (1.0 + math.exp(-composite / 3.0))

    return {
        "deviation_score":     deviation_score,
        "per_feature_z":       per_feature_z,
        "per_feature_peer_z":  per_feature_peer_z,
        "peer_group_id":       peer_group_id,
        "baseline_source":     baseline_source,
        "baseline_age_days":   baseline_age_days,
        "feature_snapshot":    feature_vector,
    }
```

The cold-start handling matters because every new role assignment is a cold start. A nurse who transfers from cardiology to oncology has a perfectly good baseline for "cardiology nurse activity" and a useless one for "oncology nurse activity," and the detector needs to avoid producing six weeks of false positives during the transition. The peer-group fallback gives a reasonable starting point; the per-user baseline takes over once enough data accumulates. Programs that don't handle cold-start gracefully end up with a flood of "anomaly" alerts every time someone changes role, which trains the privacy office to ignore the system.

---

## Step 5: Run the Graph-Based Detector

The relationship graph captures the documented connections between workforce members and patients. The graph detector evaluates whether the access has any plausible relationship path. Patterns where a user accesses patients with no graph connection to their documented work are flagged. This is the catcher for relationship-based access (the user is accessing someone they have an off-system relationship with), credential-compromise reconnaissance (a user accessing a scattered set of patients with no shared workflow), and family-relationship access not captured by surname or address.

```python
def query_neptune_for_paths(workforce_id, patient_id, max_hops=3):
    """Query Amazon Neptune for relationship paths between user and patient.

    Production sends Gremlin to Neptune. The teaching example queries
    the in-process NetworkX graph. This function is structured to make
    the production swap straightforward: replace the body with a Neptune
    Gremlin call and the rest of the detector works unchanged.

    Production Gremlin (illustrative):
        g.V().has('workforce', 'workforce_id', workforce_id)
          .repeat(both('care_team', 'on_call', 'consult', 'scheduling',
                       'order_signature', 'documentation_authorship',
                       'team_membership', 'cross_coverage'))
          .times(max_hops)
          .has('patient', 'patient_id', patient_id)
          .path()
          .limit(5)
    """
    graph = _global_graph()
    if graph is None or not graph.has_node(workforce_id) or not graph.has_node(patient_id):
        return []

    paths = []
    try:
        # nx.all_simple_paths is fine for the small demo graph; a real
        # Neptune query is what scales.
        for p in nx.all_simple_paths(graph, source=workforce_id,
                                      target=patient_id, cutoff=max_hops):
            paths.append({"length": len(p) - 1, "nodes": p})
            if len(paths) >= 5:
                break
    except nx.NetworkXNoPath:
        pass
    return paths

def query_unit_overlap(workforce_id, patient_id, observed_at, lookback_days=7):
    """Check whether the patient was on a unit that the user covers.

    Department-level relationship: was the patient on a unit this user's
    department covers, even if the user wasn't directly assigned? Captures
    floor-coverage, cross-coverage, and pre-admission-prep patterns that
    the EHR's care-team module misses.
    """
    graph = _global_graph()
    if graph is None:
        return False

    user_dept = graph.nodes[workforce_id].get("department") if graph.has_node(workforce_id) else None
    if not user_dept:
        return False

    # Walk patient's recent unit assignments and check department overlap.
    if not graph.has_node(patient_id):
        return False
    for neighbor in graph.neighbors(patient_id):
        edge = graph.get_edge_data(patient_id, neighbor)
        if edge.get("type") == "admitted_to_unit":
            unit_dept = graph.nodes[neighbor].get("department")
            if unit_dept == user_dept:
                return True
    return False

def get_user_recent_patient_set(workforce_id, hours=24):
    """Return the set of patients this user has accessed in the last N hours."""
    table = dynamodb.Table(USER_STATE_TABLE)
    response = table.get_item(Key={"workforce_id": workforce_id})
    state = _undecimalize(response.get("Item")) or {}
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(hours=hours)
    patients = set()
    for e in state.get("recent_events", []):
        e_dt = datetime.fromisoformat(e["observed_at"].replace("Z", "+00:00"))
        if start_dt <= e_dt <= end_dt:
            patients.add(e["patient_id"])
    return patients

def compute_graph_cohesion(patient_set):
    """Return a 0..1 cohesion score for a set of patients.

    High cohesion means the patients share care teams, units, or
    diagnosis groups (a clinical workflow). Low cohesion means the
    patients are scattered with no shared structural connection
    (a credential-compromise reconnaissance pattern).
    """
    graph = _global_graph()
    if graph is None or len(patient_set) < 2:
        return 1.0   # too small to evaluate; assume cohesive

    # Count how many pairs share at least one unit or care-team neighbor.
    patient_list = list(patient_set)
    cohesive_pairs = 0
    total_pairs = 0
    for i in range(len(patient_list)):
        for j in range(i + 1, len(patient_list)):
            total_pairs += 1
            p1, p2 = patient_list[i], patient_list[j]
            if not (graph.has_node(p1) and graph.has_node(p2)):
                continue
            shared = set(graph.neighbors(p1)) & set(graph.neighbors(p2))
            if shared:
                cohesive_pairs += 1
    if total_pairs == 0:
        return 1.0
    return cohesive_pairs / total_pairs

def check_family_link(workforce_id, patient_id):
    """Look up an HR-linked household connection between user and patient.

    Production checks the workforce-to-household linkage table fed from
    HRIS dependent and address data. Returns True for documented family
    relationships (spouse, dependent, declared dependent contact). The
    teaching example returns False; the linkage path is documented but
    not exercised in the demo.
    """
    return False

CLUSTER_THRESHOLD = 8
CLUSTER_COHESION_THRESHOLD = 0.3

def run_graph_detector(event):
    """Evaluate the relationship-graph detector for a single event."""
    paths = query_neptune_for_paths(
        event["workforce_id"], event["patient_id"], max_hops=3
    )
    has_direct = any(p["length"] <= 2 for p in paths)
    has_indirect = any(p["length"] <= 4 for p in paths)

    department_overlap = query_unit_overlap(
        event["workforce_id"], event["patient_id"], event["observed_at"]
    )

    recent_patients = get_user_recent_patient_set(event["workforce_id"])
    cluster_cohesion = None
    cluster_anomaly = False
    if len(recent_patients) >= CLUSTER_THRESHOLD:
        cluster_cohesion = compute_graph_cohesion(recent_patients)
        cluster_anomaly = cluster_cohesion < CLUSTER_COHESION_THRESHOLD

    family_match = check_family_link(event["workforce_id"], event["patient_id"])

    relationship_evidence = {
        "has_direct_relationship":    has_direct,
        "has_indirect_relationship":  has_indirect,
        "department_overlap":         department_overlap,
        "cluster_cohesion_score":     cluster_cohesion,
        "cluster_anomaly":            cluster_anomaly,
        "family_match":               family_match,
        "path_count":                 len(paths),
    }

    if has_direct:
        graph_score = 0.05
    elif has_indirect or department_overlap:
        graph_score = 0.30
    elif family_match:
        graph_score = 0.95
    elif cluster_anomaly:
        graph_score = 0.85
    else:
        graph_score = 0.65   # no documented connection at all

    return {
        "graph_score":            graph_score,
        "relationship_evidence":  relationship_evidence,
    }
```

The cluster-cohesion check is one of the most useful detectors for credential-compromise patterns. A legitimate user's recent patient set typically has high cohesion: the patients are on the same unit, are part of the same care team, share a hospitalist or specialist. A compromised credential being used to enumerate records produces a low-cohesion patient set. The threshold has to be tuned per cohort: a hospitalist's panel is typically high-cohesion (whole-unit coverage), while a billing analyst's set is naturally low-cohesion (patients across the entire facility appear in their work). Get the cohort partitioning right and the detector is high-precision; get it wrong and it floods the queue with billing-analyst false positives.

---

## Step 6: Combine Detectors into a Composite Case Score

Each detector produces a score (rules confidence, baseline deviation, graph relationship, sequence model). The composite scorer combines them with calibrated weights. Calibration ensures that a composite score of 0.8 corresponds to roughly the same probability of being a confirmed violation across cohorts. Subgroup-stratified thresholds matter when calibration drift differs between role categories.

```python
def cohort_for_user(role, days_since_hire):
    """Map a user to a scoring cohort.

    The cohort drives detector weighting and tier thresholds. Privileged
    users get different weights than clinical workforce; new users (under
    90 days since hire) get reduced rules weight because their
    discovery-and-search behavior trips baselines for learning reasons.
    """
    if role in PRIVILEGED_ROLES:
        return "privileged_user"
    if days_since_hire is not None and days_since_hire < 90:
        return "new_user"
    if role in CLINICAL_ROLES:
        return "clinical_workforce"
    return "DEFAULT"

def cohort_weights_for(role, days_since_hire):
    """Return the detector weights for a user's cohort."""
    cohort = cohort_for_user(role, days_since_hire)
    return DEFAULT_DETECTOR_WEIGHTS.get(cohort, DEFAULT_DETECTOR_WEIGHTS["DEFAULT"])

def apply_calibration(raw_score, calibrator, subgroup):
    """Apply a (subgroup-aware) calibration mapping.

    Production maintains per-subgroup calibration curves (per role, per
    department) when calibration drift differs across cohorts. The
    teaching example uses a single isotonic regressor and ignores
    subgroup; the function signature shows the production shape.
    """
    if calibrator is None:
        return raw_score
    return float(calibrator.predict(np.array([raw_score]))[0])

def tier_from_score(score, role, days_since_hire):
    """Map a calibrated score to a privacy-office tier."""
    cohort = cohort_for_user(role, days_since_hire)
    thresholds = DEFAULT_TIER_THRESHOLDS.get(cohort, DEFAULT_TIER_THRESHOLDS["DEFAULT"])
    if score >= thresholds["tier_1"]:
        return "tier_1"
    if score >= thresholds["tier_2"]:
        return "tier_2"
    if score >= thresholds["tier_3"]:
        return "tier_3"
    return "below_threshold"

def composite_score(event, rules_flags, baseline_output, graph_output,
                    sequence_output, calibrator):
    """Combine detector outputs into a single calibrated case score."""
    weights = cohort_weights_for(event.get("user_role"),
                                 event.get("days_since_hire"))
    rules_confidence = max_severity_confidence(rules_flags)
    sequence_score   = sequence_output.get("sequence_score", 0.0)

    raw_composite = (
        weights["rules"]    * rules_confidence
      + weights["baseline"] * baseline_output["deviation_score"]
      + weights["graph"]    * graph_output["graph_score"]
      + weights["sequence"] * sequence_score
    )

    calibrated = apply_calibration(
        raw_composite, calibrator,
        subgroup=cohort_for_user(event.get("user_role"),
                                 event.get("days_since_hire")),
    )
    tier = tier_from_score(
        calibrated, event.get("user_role"), event.get("days_since_hire")
    )

    return {
        "score_id":                generate_score_id(),
        "event_id":                event["event_id"],
        "workforce_id":            event["workforce_id"],
        "patient_id":              event["patient_id"],
        "scored_at":               datetime.now(timezone.utc).isoformat(),
        "rules_flags":             rules_flags,
        "rules_confidence":        rules_confidence,
        "baseline_deviation_score": baseline_output["deviation_score"],
        "graph_score":             graph_output["graph_score"],
        "sequence_score":          sequence_score,
        "composite_raw":           raw_composite,
        "composite_calibrated":    calibrated,
        "tier":                    tier,
        "per_feature_z":           baseline_output["per_feature_z"],
        "relationship_evidence":   graph_output["relationship_evidence"],
        "feature_snapshot":        baseline_output["feature_snapshot"],
        "model_version":           "access-anomaly-composite-v3.1",
        "calibration_version":     "calib-v3.1-2026-04",
        "cohort":                  cohort_for_user(event.get("user_role"),
                                                    event.get("days_since_hire")),
    }

def generate_score_id():
    """Generate a score identifier."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"SCORE-{today}-{uuid.uuid4().hex[:8]}"

def score_via_sagemaker_endpoint(features, feature_order):
    """Invoke the deployed SageMaker endpoint for the composite anomaly model.

    Production typically uses SageMaker batch transform for the nightly
    user-graph rescoring (cheaper at this cadence) and a real-time
    endpoint for event-driven re-scoring on high-priority triggers.
    Both accept the same feature payload; the difference is how
    invocation is triggered.
    """
    payload = ",".join(
        str(features.get(f, 0.0)) for f in feature_order
    )
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT_NAME,
        ContentType="text/csv",
        Body=payload,
    )
    body = response["Body"].read().decode("utf-8").strip()
    return float(body.split(",")[0])
```

A note on calibration drift. Calibration is typically the first thing to break in production. A model that was perfectly calibrated at deployment time slowly drifts as the workforce composition changes (new hires, retirements, role changes), as the EHR upgrades change click paths, and as the rule library evolves. SageMaker Model Monitor catches this when ground-truth labels arrive, but the lag between the drift and the labels means that operational thresholds can be wrong for weeks before the monitor notices. Production programs run a parallel "shadow" calibration fit on the most recent labeled cases and alert when the shadow calibration disagrees substantially with the deployed calibration. The shadow gives a faster signal than waiting for the formal Model Monitor cadence.

---

## Step 7: Build the Investigator-Facing Case Package

The case builder turns scored events into reviewable cases. It groups related events (the same user accessing the same patient over multiple sessions becomes one case, not many), checks suppression rules, attaches the supporting evidence, generates the LLM narrative, and persists the case for the privacy-office case queue. This is the actual product. A perfect score with no case package and no narrative is no use to an investigator.

```python
def find_existing_case(workforce_id, patient_id, within_window_days):
    """Search for an open case grouping this user-patient pair.

    Production indexes case_state by (workforce_id, patient_id) for this
    lookup. The teaching example does a small in-memory scan.
    """
    table = dynamodb.Table(CASE_STATE_TABLE)
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=within_window_days)).isoformat()
    # In production, query via a GSI on (workforce_id, patient_id, opened_at).
    response = table.scan(
        FilterExpression=(
            (Key("workforce_id").eq(workforce_id))
            & (Key("patient_id").eq(patient_id))
            & (Key("status").eq("open_for_review"))
            & (Key("opened_at").gte(cutoff))
        ),
        Limit=10,
    )
    items = response.get("Items", [])
    return _undecimalize(items[0]) if items else None

def update_existing_case(existing_case, score_record):
    """Append a new score to an existing case and refresh evidence."""
    table = dynamodb.Table(CASE_STATE_TABLE)
    score_ids = existing_case.get("scoring_record_ids", []) + [score_record["score_id"]]
    composite = max(
        existing_case.get("composite_score", 0.0),
        float(score_record["composite_calibrated"]),
    )
    table.update_item(
        Key={"case_id": existing_case["case_id"]},
        UpdateExpression="SET scoring_record_ids = :s, composite_score = :c, updated_at = :t",
        ExpressionAttributeValues={
            ":s": score_ids,
            ":c": _to_decimal(composite),
            ":t": datetime.now(timezone.utc).isoformat(),
        },
    )

def check_recent_dismissal(score_record):
    """Was this same pattern recently dismissed for this user?"""
    table = dynamodb.Table(SUPPRESSION_RULES_TABLE)
    response = table.query(
        KeyConditionExpression=Key("workforce_id").eq(score_record["workforce_id"]),
    )
    for item in response.get("Items", []):
        rule = _undecimalize(item)
        valid_until = rule.get("valid_until")
        if valid_until and valid_until > datetime.now(timezone.utc).isoformat():
            # Match if the rule scope includes the patient or the patient
            # set this score touches.
            if rule.get("patient_id") == score_record["patient_id"]:
                return True
            if rule.get("scope") == "all_patients":
                return True
    return False

def add_suppression_rule(workforce_id, patient_id, reason, valid_for_days):
    """Add a suppression rule so a recently-dismissed pattern doesn't re-flag."""
    table = dynamodb.Table(SUPPRESSION_RULES_TABLE)
    valid_until_dt = datetime.now(timezone.utc) + timedelta(days=valid_for_days)
    rule = {
        "workforce_id":     workforce_id,
        "rule_id":          str(uuid.uuid4()),
        "patient_id":       patient_id,
        "scope":            "patient_specific",
        "reason":            reason,
        "added_at":         datetime.now(timezone.utc).isoformat(),
        "valid_until":       valid_until_dt.isoformat(),
        "ttl":               int(valid_until_dt.timestamp()),   # DynamoDB TTL
    }
    table.put_item(Item=_decimalize(rule))

def fetch_workforce_record(workforce_id):
    """Return the full workforce identity record for case display."""
    table = dynamodb.Table(WORKFORCE_IDENTITY_TABLE)
    response = table.get_item(Key={"workforce_id": workforce_id})
    return _undecimalize(response.get("Item")) or {}

def fetch_patient_record(patient_id):
    """Return the full patient context record for case display."""
    table = dynamodb.Table(PATIENT_CONTEXT_TABLE)
    response = table.get_item(Key={"patient_id": patient_id})
    return _undecimalize(response.get("Item")) or {}

def fetch_recent_user_activity(workforce_id, days):
    """Return a summary of the user's recent activity."""
    table = dynamodb.Table(USER_STATE_TABLE)
    response = table.get_item(Key={"workforce_id": workforce_id})
    state = _undecimalize(response.get("Item")) or {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [e for e in state.get("recent_events", [])
              if e.get("observed_at", "") >= cutoff]
    return {
        "event_count":           len(recent),
        "unique_patients":       len({e["patient_id"] for e in recent}),
        "export_count":           sum(1 for e in recent if e.get("event_type") == "export"),
        "break_glass_count":      sum(1 for e in recent if e.get("break_glass")),
        "off_hours_count":        sum(1 for e in recent if e.get("is_off_hours")),
    }

def top_n_drivers(per_feature_z, n=5):
    """Return the top-N features by absolute z-score."""
    items = [(name, z) for name, z in per_feature_z.items() if z is not None]
    items.sort(key=lambda x: abs(x[1]), reverse=True)
    return [{"feature": name, "z_score": float(z)} for name, z in items[:n]]

def build_case_narrative_prompt(evidence):
    """Build the Bedrock prompt for case-narrative generation.

    Constrained: cite the evidence, describe the access pattern, never
    assert intent or recommend an outcome. Always with human review;
    the LLM produces decision support, not decisions.
    """
    triggering = evidence.get("triggering_events", [])
    if triggering:
        first = triggering[0]
        access_summary = (
            f"At {first.get('observed_at')}, workforce member "
            f"{evidence['workforce_record'].get('workforce_id')} "
            f"({evidence['workforce_record'].get('role') or 'unknown role'}, "
            f"{evidence['workforce_record'].get('department') or 'unknown department'}) "
            f"accessed the chart of patient "
            f"{evidence['patient_record'].get('patient_id')}."
        )
    else:
        access_summary = "Multiple access events flagged in this case."

    rules_summary = "\n".join(
        f"- {f.get('explanation', f.get('rule_id'))}"
        for f in evidence.get("rules_flags", [])
    ) or "(no rules-engine flags)"

    care_summary = (
        f"Care relationship at access time: "
        f"{'documented' if evidence['care_relationship'].get('has_direct_relationship') else 'not documented'}; "
        f"department overlap: "
        f"{evidence['care_relationship'].get('department_overlap')}; "
        f"path count: {evidence['care_relationship'].get('path_count', 0)}."
    )

    baseline_summary = (
        f"Baseline deviation score: "
        f"{evidence['baseline_evidence']['deviation_score']:.2f}. "
        f"Top deviation features: "
        + ", ".join(d["feature"] for d in evidence["baseline_evidence"]["top_z_features"])
    )

    return (
        "You are summarizing a healthcare access-anomaly case for a "
        "privacy-office investigator. You are not making a determination "
        "of policy violation and you are not asserting intent. You are "
        "translating the structured evidence into a 2-4 sentence "
        "investigator-readable narrative that cites the evidence and "
        "describes the access pattern. End with the phrase 'This is "
        "decision support; investigator judgment governs.'\n\n"
        f"Composite score: {evidence['composite_score']:.2f} (tier {evidence['tier']})\n"
        f"{access_summary}\n\n"
        f"Rules-engine flags:\n{rules_summary}\n\n"
        f"{care_summary}\n\n"
        f"{baseline_summary}\n\n"
        "Produce 2-4 sentences of plain narrative. No bullet points. "
        "No assertions of intent. No recommended employment actions."
    )

def invoke_bedrock_narrative(evidence):
    """Generate the investigator-facing case narrative via Bedrock.

    Confirm the chosen Bedrock model is HIPAA-eligible under your AWS
    BAA before deploying.
    """
    prompt = build_case_narrative_prompt(evidence)
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
        logger.warning("bedrock invocation failed", extra={"error": str(e)})
        _emit_metric("BedrockNarrativeFailed", 1)
        # Fall back to a structured-only summary so case-builder doesn't fail.
        return (
            f"Tier {evidence['tier']} case with composite score "
            f"{evidence['composite_score']:.2f}. "
            f"Rules flags: {len(evidence.get('rules_flags', []))}. "
            f"Care relationship: "
            f"{'documented' if evidence['care_relationship'].get('has_direct_relationship') else 'not documented'}. "
            "This is decision support; investigator judgment governs."
        )

def _emit_metric(metric_name, value, unit="Count"):
    """Emit a CloudWatch metric for operational monitoring."""
    try:
        cloudwatch.put_metric_data(
            Namespace="AccessAnomaly/CaseBuilder",
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

def build_case(score_record, enriched_event):
    """Group, suppress, assemble evidence, and persist a case."""
    if score_record["tier"] == "below_threshold":
        return None

    existing_case = find_existing_case(
        score_record["workforce_id"], score_record["patient_id"],
        within_window_days=CASE_GROUPING_WINDOW_DAYS,
    )
    if existing_case:
        update_existing_case(existing_case, score_record)
        return existing_case["case_id"]

    if check_recent_dismissal(score_record):
        logger.info("case suppressed by recent dismissal",
                    extra={"workforce_id": score_record["workforce_id"],
                           "patient_id":   score_record["patient_id"]})
        _emit_metric("Suppressed_RecentDismissal", 1)
        return None

    workforce_record = fetch_workforce_record(score_record["workforce_id"])
    patient_record   = fetch_patient_record(score_record["patient_id"])
    recent_activity  = fetch_recent_user_activity(score_record["workforce_id"], days=30)

    evidence = {
        "triggering_events":  [enriched_event],
        "workforce_record":   {
            "workforce_id":      score_record["workforce_id"],
            "role":              workforce_record.get("role"),
            "department":        workforce_record.get("department"),
            "manager":           workforce_record.get("manager_id"),
            "employment_type":   workforce_record.get("employment_type"),
            "hire_date":         workforce_record.get("hire_date"),
        },
        "patient_record": {
            "patient_id":         score_record["patient_id"],
            "sensitivity_flags":  patient_record.get("sensitivity_flags", []),
            "is_workforce_member": patient_record.get("is_workforce_member", False),
            "is_deceased":         patient_record.get("is_deceased", False),
        },
        "care_relationship":  score_record["relationship_evidence"],
        "user_recent_activity": recent_activity,
        "rules_flags":        score_record["rules_flags"],
        "baseline_evidence": {
            "deviation_score":  score_record["baseline_deviation_score"],
            "top_z_features":   top_n_drivers(score_record["per_feature_z"], n=5),
        },
        "graph_evidence":     score_record["relationship_evidence"],
        "composite_score":    float(score_record["composite_calibrated"]),
        "tier":               score_record["tier"],
        "model_version":      score_record["model_version"],
        "calibration_version": score_record["calibration_version"],
    }

    evidence["narrative"] = invoke_bedrock_narrative(evidence)

    case = {
        "case_id":            f"CASE-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:8]}",
        "opened_at":          datetime.now(timezone.utc).isoformat(),
        "workforce_id":       score_record["workforce_id"],
        "patient_id":         score_record["patient_id"],
        "tier":               score_record["tier"],
        "composite_score":    float(score_record["composite_calibrated"]),
        "scoring_record_ids":  [score_record["score_id"]],
        "evidence":            evidence,
        "status":              "open_for_review",
        "assigned_to":         None,
        "outcome":             None,
        "outcome_notes":       None,
    }

    table = dynamodb.Table(CASE_STATE_TABLE)
    table.put_item(Item=_decimalize(case))

    eventbridge.put_events(Entries=[{
        "Source":      "access-anomaly.case-builder",
        "DetailType":  "CaseOpened",
        "Detail":      json.dumps({
            "case_id":          case["case_id"],
            "tier":             case["tier"],
            "composite_score":  case["composite_score"],
        }, default=str),
        "EventBusName": CASE_BUS,
    }])

    _emit_metric(f"CasesOpened_{case['tier']}", 1)
    return case["case_id"]
```

The case-grouping window (7 days by default) matters for two reasons. First, the same user repeatedly accessing the same patient within a short window is one investigation, not many; the privacy office should see a single case with multiple events, not a flood of duplicate cases. Second, after the window expires, a new spike of access on the same user-patient pair should re-open as a new case rather than silently appending to an aging one. The 7-day default works well for the typical curiosity-snooping pattern; programs that primarily track methodical credential-compromise patterns sometimes use longer windows (14-30 days) to keep the slower-burn cases in a single investigation.

---

## Step 8: Capture Investigator Outcomes and Feed the Learning Loop

Investigators adjudicate cases. Outcomes flow back as labels for retraining, suppression rule updates, threshold tuning, and subgroup-performance analysis. Without this loop, the model drifts and nobody finds out until the privacy office stops trusting the case queue.

```python
VALID_OUTCOMES = {
    "confirmed_violation",
    "dismissed_legitimate",
    "dismissed_inconclusive",
    "escalated_to_hr",
    "escalated_to_legal",
    "escalated_to_law_enforcement",
}

def initiate_breach_review(case):
    """Start the HIPAA breach-notification workflow.

    Production publishes to an EventBridge rule that triggers a Step
    Functions workflow with breach review, OCR notification clock
    tracking, and legal-coordination handoff. The teaching example
    just emits the event.
    """
    eventbridge.put_events(Entries=[{
        "Source":      "access-anomaly.outcome-capture",
        "DetailType":  "BreachReviewInitiated",
        "Detail":      json.dumps({
            "case_id":      case["case_id"],
            "workforce_id": case["workforce_id"],
            "patient_id":   case["patient_id"],
            "started_at":   datetime.now(timezone.utc).isoformat(),
        }, default=str),
        "EventBusName": CASE_BUS,
    }])

def refer_to_hr(case):
    """Hand off a confirmed-violation case to HR for employment review.

    Production publishes to a separate EventBridge rule that the HR
    integration consumes. The case package (evidence, narrative,
    investigator notes) goes with the referral. Workforce-equity and
    due-process considerations apply.
    """
    eventbridge.put_events(Entries=[{
        "Source":      "access-anomaly.outcome-capture",
        "DetailType":  "HRReferral",
        "Detail":      json.dumps({
            "case_id":      case["case_id"],
            "workforce_id": case["workforce_id"],
            "tier":         case["tier"],
            "referred_at":  datetime.now(timezone.utc).isoformat(),
        }, default=str),
        "EventBusName": CASE_BUS,
    }])

def update_user_state_with_prior_violation(workforce_id):
    """Mark the user as having a prior confirmed violation.

    Used as a feature in subsequent scoring (a user with a recent
    confirmed violation gets elevated scrutiny within policy bounds).
    Subject to organizational policy; some programs do not retain this
    flag indefinitely.
    """
    table = dynamodb.Table(USER_STATE_TABLE)
    table.update_item(
        Key={"workforce_id": workforce_id},
        UpdateExpression="SET prior_violation = :v, prior_violation_at = :t",
        ExpressionAttributeValues={
            ":v": True,
            ":t": datetime.now(timezone.utc).isoformat(),
        },
    )

def on_investigator_action(action):
    """Record an investigator's adjudication and feed the learning loop.

    action keys:
      case_id, outcome, notes, investigator_id
      dismissal_reason (when outcome is dismissed_legitimate)
    """
    if action["outcome"] not in VALID_OUTCOMES:
        raise ValueError(f"invalid outcome: {action['outcome']}")

    table = dynamodb.Table(CASE_STATE_TABLE)
    response = table.get_item(Key={"case_id": action["case_id"]})
    case = _undecimalize(response.get("Item"))
    if case is None:
        logger.warning("outcome for unknown case",
                       extra={"case_id": action["case_id"]})
        return None

    case["outcome"]      = action["outcome"]
    case["outcome_notes"] = action.get("notes")
    case["outcome_at"]   = datetime.now(timezone.utc).isoformat()
    case["assigned_to"]  = action["investigator_id"]
    case["status"]        = "closed"

    if action["outcome"] == "confirmed_violation":
        initiate_breach_review(case)
        refer_to_hr(case)
        update_user_state_with_prior_violation(case["workforce_id"])

    if action["outcome"] == "dismissed_legitimate":
        add_suppression_rule(
            workforce_id=case["workforce_id"],
            patient_id=case["patient_id"],
            reason=action.get("dismissal_reason", "investigator_cleared"),
            valid_for_days=SUPPRESSION_AFTER_DISMISSAL_DAYS,
        )

    table.put_item(Item=_decimalize(case))

    label_record = {
        "label_id":              str(uuid.uuid4()),
        "case_id":               case["case_id"],
        "workforce_id":          case["workforce_id"],
        "patient_id":            case["patient_id"],
        "scoring_record_ids":    case.get("scoring_record_ids", []),
        "composite_score":       float(case["composite_score"]),
        "tier":                  case["tier"],
        "outcome":               case["outcome"],
        "outcome_at":            case["outcome_at"],
        "time_to_adjudication_seconds": (
            (datetime.fromisoformat(case["outcome_at"].replace("Z", "+00:00"))
             - datetime.fromisoformat(case["opened_at"].replace("Z", "+00:00"))).total_seconds()
        ),
        "label":                 1 if case["outcome"] == "confirmed_violation" else 0,
        "investigator_id":       case["assigned_to"],
    }

    s3_client.put_object(
        Bucket=TRAINING_LABELS_BUCKET,
        Key=(
            f"outcomes/year={case['outcome_at'][:4]}/"
            f"month={case['outcome_at'][5:7]}/"
            f"{label_record['label_id']}.json"
        ),
        Body=json.dumps(label_record, default=str).encode("utf-8"),
        ServerSideEncryption="aws:kms",
    )

    eventbridge.put_events(Entries=[{
        "Source":      "access-anomaly.outcome-capture",
        "DetailType":  "CaseClosed",
        "Detail":      json.dumps(label_record, default=str),
        "EventBusName": CASE_BUS,
    }])

    _emit_metric(f"Outcome_{case['outcome']}", 1)
    return label_record
```

The label-derivation choice ("confirmed_violation" as the positive class, everything else as negative) hides nuance the joint privacy-and-infosec governance committee should be aware of. "Dismissed_inconclusive" cases are not the same as "dismissed_legitimate" cases: an inconclusive dismissal means the investigator could not determine whether a violation occurred, which is a noisy negative for retraining purposes. Some programs use a three-class label (positive / negative / inconclusive) and exclude inconclusive cases from the supervised retraining set rather than treating them as negatives. Audit a random sample of labeled cases monthly with the lead investigator and ask whether the label matches their reading of the case; disagreement rates over 10% mean the schema needs revisiting before the next retrain.

---

## Full Pipeline

Now string the pieces together. In production this function does not exist as a single callable; each step runs in its own compute container, orchestrated by EventBridge fan-out and Step Functions for the nightly graph rescoring. The single-function version here makes the data flow visible for teaching.

```python
def build_demo_relationship_graph():
    """Build a small in-process relationship graph for the demo.

    Production reads from Amazon Neptune. The graph here illustrates the
    structure: workforce nodes (with role and department), patient nodes,
    encounter and unit nodes, and edges representing care_team, on_call,
    documentation_authorship, admitted_to_unit, and similar relationships.
    """
    g = nx.DiGraph()

    # Workforce nodes.
    g.add_node("WF-NURSE-001",
               type="workforce", role="registered_nurse", department="cardiology")
    g.add_node("WF-NURSE-002",
               type="workforce", role="registered_nurse", department="cardiology")
    g.add_node("WF-MD-001",
               type="workforce", role="physician", department="cardiology")
    g.add_node("WF-DBA-001",
               type="workforce", role="database_administrator", department="it")
    g.add_node("WF-WOJ-001",
               type="workforce", role="registered_nurse", department="cardiology")

    # Patient nodes.
    g.add_node("PT-001", type="patient")
    g.add_node("PT-002", type="patient")
    g.add_node("PT-WOJ-001", type="patient")
    g.add_node("PT-VIP-001", type="patient")

    # Unit nodes.
    g.add_node("UNIT-CARDIO-SD",
               type="unit", department="cardiology")

    # Care relationships (directed: workforce -> patient).
    g.add_edge("WF-NURSE-001", "PT-001", type="care_team")
    g.add_edge("WF-NURSE-002", "PT-002", type="care_team")
    g.add_edge("WF-MD-001", "PT-001", type="assigned_attending")
    g.add_edge("WF-MD-001", "PT-002", type="assigned_attending")

    # Patient -> unit edges (for department overlap detection).
    g.add_edge("PT-001",     "UNIT-CARDIO-SD", type="admitted_to_unit")
    g.add_edge("PT-002",     "UNIT-CARDIO-SD", type="admitted_to_unit")
    g.add_edge("PT-WOJ-001", "UNIT-CARDIO-SD", type="admitted_to_unit")

    # Note: WF-WOJ-001 has NO care relationship to PT-WOJ-001. The
    # rules-engine same-name detector should flag this; the graph
    # detector should report no documented relationship (graph_score
    # closer to 0.65). Together they should produce a tier-1 case.

    return g

def seed_demo_data():
    """Seed the workforce, patient, schedule, and user-state tables with
    a tiny synthetic dataset so the pipeline runs end-to-end.
    """
    workforce_table = dynamodb.Table(WORKFORCE_IDENTITY_TABLE)
    patient_table   = dynamodb.Table(PATIENT_CONTEXT_TABLE)
    schedule_table  = dynamodb.Table(WORKFORCE_SCHEDULE_TABLE)
    user_state_table = dynamodb.Table(USER_STATE_TABLE)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    workforce_records = [
        {"workforce_id": "WF-NURSE-001", "role": "registered_nurse",
         "department":  "cardiology", "manager_id": "MGR-001",
         "employment_type": "employee", "address_zip": "10001",
         "last_name": "Garcia", "hire_date": "2020-03-15"},
        {"workforce_id": "WF-NURSE-002", "role": "registered_nurse",
         "department":  "cardiology", "manager_id": "MGR-001",
         "employment_type": "employee", "address_zip": "10001",
         "last_name": "Davis", "hire_date": "2019-09-01"},
        {"workforce_id": "WF-MD-001", "role": "physician",
         "department":  "cardiology", "manager_id": "MGR-MD",
         "employment_type": "employee", "address_zip": "94110",
         "last_name": "Smith", "hire_date": "2015-07-01"},
        {"workforce_id": "WF-DBA-001", "role": "database_administrator",
         "department":  "it", "manager_id": "MGR-IT",
         "employment_type": "employee", "address_zip": "10001",
         "last_name": "Johnson", "hire_date": "2018-01-10"},
        {"workforce_id": "WF-WOJ-001", "role": "registered_nurse",
         "department":  "cardiology", "manager_id": "MGR-001",
         "employment_type": "employee", "address_zip": "14620",
         "last_name": "Wojnarowski", "hire_date": "2022-06-15"},
    ]
    for record in workforce_records:
        workforce_table.put_item(Item=_decimalize(record))

    patient_records = [
        {"patient_id": "PT-001", "last_name": "Brown", "address_zip": "10002",
         "sensitivity_flags": [], "is_workforce_member": False,
         "is_deceased": False},
        {"patient_id": "PT-002", "last_name": "Lee", "address_zip": "10002",
         "sensitivity_flags": [], "is_workforce_member": False,
         "is_deceased": False},
        {"patient_id": "PT-WOJ-001", "last_name": "Wojnarowski",
         "address_zip": "14620", "sensitivity_flags": [],
         "is_workforce_member": False, "is_deceased": False},
        {"patient_id": "PT-VIP-001", "last_name": "Anderson",
         "address_zip": "94110", "sensitivity_flags": ["VIP"],
         "is_workforce_member": False, "is_deceased": False},
    ]
    for record in patient_records:
        patient_table.put_item(Item=_decimalize(record))

    # Day-shift schedules. WF-WOJ-001 deliberately has no schedule for
    # tonight so the off-hours rule should fire on a late-night access.
    schedule_records = [
        {"workforce_id": "WF-NURSE-001", "shift_date": today,
         "shift_start": f"{today}T07:00:00Z", "shift_end": f"{today}T19:00:00Z",
         "unit": "UNIT-CARDIO-SD"},
        {"workforce_id": "WF-NURSE-002", "shift_date": today,
         "shift_start": f"{today}T07:00:00Z", "shift_end": f"{today}T19:00:00Z",
         "unit": "UNIT-CARDIO-SD"},
        {"workforce_id": "WF-MD-001", "shift_date": today,
         "shift_start": f"{today}T07:00:00Z", "shift_end": f"{today}T19:00:00Z",
         "unit": "UNIT-CARDIO-SD"},
    ]
    for record in schedule_records:
        schedule_table.put_item(Item=_decimalize(record))

    # Seed initial user-state with an empty baseline; the daily baseline
    # refresh job populates this in production.
    for w in workforce_records:
        user_state_table.put_item(Item=_decimalize({
            "workforce_id":          w["workforce_id"],
            "shift_pattern":         "day",
            "behavioral_baseline": {
                "mean":              {},   # populated by nightly baseline job
                "std":               {},
                "first_observed":    "2024-01-01T00:00:00Z",
            },
            "recent_events":         [],
            "known_patients":        [],
            "prior_violation":       False,
        }))

def append_to_user_state(workforce_id, enriched_event):
    """Append an enriched event to the per-user state record.

    Production trims the recent_events list to a bounded window (e.g.,
    1000 most-recent events or 30 days) to keep DynamoDB item size in
    check. The teaching example keeps the last 200.
    """
    table = dynamodb.Table(USER_STATE_TABLE)
    response = table.get_item(Key={"workforce_id": workforce_id})
    state = _undecimalize(response.get("Item")) or {"workforce_id": workforce_id}
    recent = state.get("recent_events", [])
    recent.append({
        "event_id":                    enriched_event["event_id"],
        "patient_id":                  enriched_event["patient_id"],
        "event_type":                  enriched_event["event_type"],
        "resource_type":               enriched_event["resource_type"],
        "observed_at":                 enriched_event["observed_at"],
        "is_off_hours":                enriched_event.get("is_off_hours", False),
        "break_glass":                 enriched_event.get("break_glass", False),
        "patient_sensitivity_flags":   enriched_event.get("patient_sensitivity_flags", []),
        "care_relationship_strength":  enriched_event.get("care_relationship_strength", 0.0),
    })
    recent = recent[-200:]
    state["recent_events"] = recent

    known = set(state.get("known_patients", []))
    known.add(enriched_event["patient_id"])
    state["known_patients"] = list(known)[-1000:]

    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    table.put_item(Item=_decimalize(state))

def train_demo_model(num_synthetic_events=500, random_state=42):
    """Train a tiny in-process composite model on synthetic feature vectors.

    Production replaces this with a SageMaker Training Job that reads
    historical features from the offline Feature Store and produces a
    versioned model artifact in the SageMaker Model Registry. The
    teaching example trains a small logistic regression on synthetic
    data so the scoring path is runnable in a notebook.
    """
    rng = np.random.default_rng(random_state)
    feature_order = [
        "rules_confidence", "baseline_deviation_score", "graph_score",
        "sequence_score", "off_hours", "break_glass",
        "care_relationship_strength", "name_uniqueness_match",
    ]

    X = np.column_stack([
        rng.beta(2, 5, num_synthetic_events),                # rules_confidence
        rng.beta(2, 5, num_synthetic_events),                # baseline_deviation
        rng.beta(2, 4, num_synthetic_events),                # graph_score
        rng.beta(2, 6, num_synthetic_events),                # sequence_score
        rng.binomial(1, 0.15, num_synthetic_events),         # off_hours
        rng.binomial(1, 0.05, num_synthetic_events),         # break_glass
        rng.beta(5, 3, num_synthetic_events),                # care_strength (skewed high)
        rng.binomial(1, 0.02, num_synthetic_events),         # name_uniqueness_match
    ])

    # Synthesize a label that correlates with the violation signature:
    # high rules confidence + low care strength + high graph score + match.
    risk_score = (
        1.5 * X[:, 0]                          # rules_confidence
      + 1.0 * X[:, 1]                          # baseline_deviation
      + 1.2 * X[:, 2]                          # graph_score
      + 0.5 * X[:, 3]                          # sequence_score
      + 0.4 * X[:, 4]                          # off_hours
      + 0.6 * X[:, 5]                          # break_glass
      - 1.3 * X[:, 6]                          # care_strength (negative weight)
      + 1.5 * X[:, 7]                          # name_uniqueness_match
      + rng.normal(0, 0.3, num_synthetic_events)
    )
    y = (risk_score > np.percentile(risk_score, 88)).astype(int)

    model = LogisticRegression(max_iter=1000, random_state=random_state)
    model.fit(X, y)

    raw_probs = model.predict_proba(X)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_probs, y)

    return model, calibrator, feature_order

def run_access_anomaly_pipeline(audit_events, model, calibrator, feature_order,
                                 graph):
    """End-to-end pipeline against a batch of audit events.

    Each event flows through ingest, enrich, detect, score, and case-build.
    Returns the list of opened case IDs plus the per-event scoring records.
    """
    global _GRAPH
    _GRAPH = graph

    case_ids = []
    score_records = []

    print(f"[1-3/8] processing {len(audit_events)} audit events through "
          "ingest, enrich, and rules-engine")
    for raw_event in audit_events:
        ingest_result = on_ehr_audit_event(raw_event, source_format="epic")
        if ingest_result.get("statusCode") != 200:
            continue

        # In production the canonical event flows through Kinesis to the
        # enrichment Lambda; here we reconstruct it inline for teaching.
        canonical = {
            "event_id":            ingest_result["event_id"],
            "workforce_id":        resolve_workforce_id(raw_event["user_id"], "epic"),
            "patient_id":          resolve_patient_id(raw_event["patient_id"], "epic"),
            "source_system":       "epic",
            "event_type":          normalize_event_type(raw_event["action_type"]),
            "resource_type":       normalize_resource_type(raw_event["resource"]),
            "action":              raw_event["action_type"],
            "observed_at":         raw_event["event_time"],
            "received_at":         datetime.now(timezone.utc).isoformat(),
            "device_id":           raw_event.get("workstation_id"),
            "ip_address":          raw_event.get("source_ip"),
            "session_id":          raw_event.get("session_id"),
            "break_glass":         bool(raw_event.get("break_glass_override", False)),
            "break_glass_reason":  raw_event.get("break_glass_reason"),
        }
        enriched = enrich_event(canonical)
        rules_flags = run_rules_engine(enriched)

        # Update user-state before computing baselines so the windows
        # include the current event.
        append_to_user_state(enriched["workforce_id"], enriched)

        print(f"[4-5/8] running baseline + graph detectors for "
              f"{enriched['workforce_id']}/{enriched['patient_id']}")
        baseline_output = run_baseline_detector(enriched)
        graph_output    = run_graph_detector(enriched)
        sequence_output = {"sequence_score": 0.0}   # not implemented in demo

        print(f"[6/8] scoring composite for "
              f"{enriched['workforce_id']}/{enriched['patient_id']}")
        score_record = composite_score(
            enriched, rules_flags, baseline_output,
            graph_output, sequence_output, calibrator,
        )
        score_records.append(score_record)

        print(f"   tier={score_record['tier']} "
              f"composite={float(score_record['composite_calibrated']):.2f} "
              f"rules={float(score_record['rules_confidence']):.2f} "
              f"baseline={float(score_record['baseline_deviation_score']):.2f} "
              f"graph={float(score_record['graph_score']):.2f}")

        print(f"[7/8] building case (if tier above threshold)")
        case_id = build_case(score_record, enriched)
        if case_id:
            case_ids.append(case_id)

    print(f"[8/8] outcome capture is event-triggered; call "
          "on_investigator_action from the case management UI handler")

    return case_ids, score_records
```

Run this end-to-end against synthetic audit events and you will see the full shape of the pipeline in your console. The output is a set of case records in DynamoDB, a set of scoring records with attached evidence, and a few CloudWatch metrics. In production the volume is orders of magnitude larger and the compute is orders of magnitude more distributed, but the function boundaries do not change.

A demonstration invocation might look like this:

```python
if __name__ == "__main__":
    # Build the demo graph and seed the supporting tables.
    graph = build_demo_relationship_graph()
    seed_demo_data()

    # Train the tiny model.
    model, calibrator, feature_order = train_demo_model()

    # A small set of synthetic audit events.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    audit_events = [
        # Legitimate access: nurse with care relationship to her assigned patient.
        {"user_id": "WF-NURSE-001", "patient_id": "PT-001",
         "action_type": "view", "resource": "chart",
         "event_time": f"{today}T10:30:00Z",
         "workstation_id": "WS-CARDIO-04", "source_ip": "10.1.2.3",
         "session_id": "SESS-001"},
        # Same-name pattern: nurse Wojnarowski accesses patient Wojnarowski
        # at 23:47 (off-hours) with no documented care relationship.
        {"user_id": "WF-WOJ-001", "patient_id": "PT-WOJ-001",
         "action_type": "view", "resource": "chart",
         "event_time": f"{today}T23:47:00Z",
         "workstation_id": "WS-CARDIO-09", "source_ip": "10.1.2.7",
         "session_id": "SESS-002"},
        # VIP access without strong care relationship.
        {"user_id": "WF-NURSE-002", "patient_id": "PT-VIP-001",
         "action_type": "view", "resource": "chart",
         "event_time": f"{today}T14:15:00Z",
         "workstation_id": "WS-CARDIO-04", "source_ip": "10.1.2.5",
         "session_id": "SESS-003"},
    ]

    case_ids, scores = run_access_anomaly_pipeline(
        audit_events, model, calibrator, feature_order, graph
    )
    print(f"\nOpened {len(case_ids)} case(s): {case_ids}")
    print(f"Scored {len(scores)} event(s)")
```

The output illustrates the contrast between a clear flag (the same-name access) and a clean access (the assigned-nurse view). The VIP-access example tests the policy-rule path. Real workloads run thousands of events per minute, and the same function boundaries scale up; production uses Kinesis fan-out with multiple shards rather than a Python for-loop.

---

## Gap to Production

Several things would need to change before you would deploy any of this against a live healthcare access-monitoring program.

**Real EHR audit-feed integration.** The teaching example accepts a pre-shaped event dict. Production pulls events from Epic's Audit Log API, Cerner Behavior Tracker, MEDITECH audit reports, or athenahealth audit feeds. Each has its own authentication scheme, pagination model, schema, and latency profile. Plan 3-6 months of integration work per EHR vendor in scope, plus ongoing maintenance as the EHR upgrades. Test the integration's completeness: missing event types, sampled audit logs (some EHR configurations sample rather than log every event), and latency variability are common gotchas.

**Real FHIR R4 AuditEvent ingestion.** When the EHR exposes audit data through FHIR R4 AuditEvent resources, use a maintained library (`fhir.resources`) and a real integration engine (Mirth, Rhapsody, Cloverleaf, or a vendor-supplied platform) rather than hand-rolling the parser. The same library handles the related Provenance and Encounter resources that contribute to enrichment.

**Real IdP, HRIS, and scheduling integrations.** The enrichment data is the project. Workday, Oracle HCM, SAP SuccessFactors, UKG, Kronos, Active Directory, Okta, Microsoft Entra ID each have their own data models and integration mechanisms. Refresh cadence matters: an HR record refreshed monthly produces stale enrichment for users who changed roles last week. Production wires lifecycle hooks for role changes, terminations, leave-of-absence, and contractor onboarding/offboarding so the enrichment store reflects current ground truth.

**Real Amazon Neptune cluster.** The teaching example uses an in-process NetworkX graph. Production hosts the relationship graph on Neptune with Gremlin queries, with continuous updates from the EHR care-team feed, the on-call schedule, the order-signature stream, and the documentation-authorship stream. The graph build is a multi-quarter project; the queries are then sub-second. Confirm Neptune is HIPAA-eligible under your AWS BAA at deployment time.

**Real SageMaker endpoint instead of in-process model.** Production hosts the composite model on a SageMaker batch transform job (cheaper for the nightly cadence) plus a real-time endpoint for event-driven re-scoring on high-priority triggers, with model artifacts registered in the SageMaker Model Registry with versioning and approval workflow. The `score_via_sagemaker_endpoint` function shows the production-shape boto3 call; replacing the in-process call site is the swap, and the rest of the pipeline does not change.

**SageMaker Clarify for real SHAP explanations.** The `top_n_drivers` function returns z-score-based feature attribution. Production uses SageMaker Clarify (or SHAP directly against the deployed model) to compute per-prediction Shapley values that reflect the model's actual reasoning. Without real SHAP, the explanation degrades to "directionally plausible" and investigator trust drops.

**SageMaker Feature Store with point-in-time correctness.** The example does not exercise Feature Store at all. A real deployment writes feature snapshots so historical case rows can be reproduced exactly, which is an audit and clinical-governance requirement. Time-aware joins prevent feature leakage during retraining.

**SageMaker Model Monitor for drift and calibration tracking.** Production runs Model Monitor on the endpoint with baseline statistics from training data. Data drift (workforce composition shifts, EHR upgrades that change click paths), prediction drift (the model's score distribution shifts even when inputs do not), and quality drift (when adjudicated outcomes catch up) all produce CloudWatch alarms that the model team triages. Calibration drift is the one that bites quietly and matters most for operational threshold tuning.

**Sequence-model variant for workflow-vs-curiosity detection.** The teaching example sets sequence_score to 0.0. Production runs an LSTM, Transformer, or similar sequence model trained on per-session click streams to distinguish workflow patterns ("opened chart, navigated to assessment, wrote notes, signed orders") from curiosity patterns ("opened chart, jumped to demographics, jumped to address, closed chart"). The model is more expensive to train and operate than tabular models; usually deployed as a second-pass technique on candidates surfaced by simpler detectors.

**SIEM integration.** Cybersecurity teams want access anomalies in the same case management system as the rest of the SOC's work. Production publishes high-tier cases to Splunk HEC, Microsoft Sentinel Log Analytics, IBM QRadar, or Chronicle in addition to the privacy-office workflow. Decide explicitly which case classes go to the privacy office, which go to the SOC, and which go to both. Each SIEM integration has its own engineering effort.

**Privacy-office case-management UI.** The teaching example writes cases to DynamoDB and OpenSearch and stops. Production publishes to Protenus, Imprivata FairWarning, MaizeAnalytics, Iatric, or a custom-built tool (often AppSync-based when the organization wants a tailored UI). Each platform has its own API patterns, data models, and configuration constraints. Many programs run a hybrid: a vendor product for the bulk of standard detection plus AWS-native components for organization-specific patterns.

**HR coordination workflow.** When a confirmed violation occurs, the handoff to HR for employment-action review needs a defined process, defined documentation, and defined timelines. Production wires this as a structured EventBridge handoff with a case package that includes the evidence, narrative, and investigator notes. Inconsistent handoffs produce inconsistent outcomes, which produce labor and legal exposure. Tabletop the process before relying on it for real cases.

**Legal coordination and breach-notification clock.** The teaching example calls `initiate_breach_review` as a stub. Production tracks the time from initial detection to confirmed unauthorized access and from confirmed unauthorized access to notification, with explicit handling of the HIPAA 60-day window plus any state-specific shorter windows (California's 15-business-day rule for medical information, for example). The legal-coordination process for cases that may involve criminal conduct (medical identity theft schemes, organized credential abuse) needs to be clear before it is needed in an active case.

**Workforce notification and acceptable-use policy.** Workforce members must be informed that monitoring exists. Quietly deploying a behavioral-monitoring system is a labor and legal disaster, regardless of the technology's quality. The acceptable-use policy must be reviewed by employment counsel, must comply with applicable state statutes, must align with collective bargaining agreements where relevant, and should be communicated through the same channels as other major policy updates. The policy and the technology deploy together.

**Idempotency on every write.** EHR audit feeds retry on network errors. Kinesis is at-least-once. The case-management UI sometimes double-submits adjudications. Use `ConditionExpression` with `attribute_not_exists` on case creation, version counters on case-state updates that should overwrite by sequence, and event-id deduplication caches keyed by `event_id`. The teaching example does not handle these; production must.

**IAM scoping per component.** The ingest Lambda needs Kinesis put on the audit-events stream and Secrets Manager read on the EHR API credentials; it does not need Bedrock. The case-builder Lambda needs DynamoDB read/write on case-state and Bedrock invoke on the narrative model; it does not need Timestream write. Each role gets the minimum permissions for its job. Annual access review is the floor. The system has to apply the same access-monitoring discipline to itself that it monitors elsewhere.

**VPC deployment.** Lambdas, SageMaker endpoints, Bedrock invocations, Comprehend Medical calls, and Neptune queries run inside a VPC with VPC endpoints for DynamoDB, S3, Kinesis, Timestream, Neptune, SageMaker Runtime, Bedrock, EventBridge, and KMS. EHR audit-feed integrations typically use site-to-site VPN or AWS Direct Connect; the topology depends on the EHR's deployment.

**KMS customer-managed keys.** Every data-at-rest store (raw events lake, workforce-identity table, patient-context table, user-state table, case-state table, suppression-rules table, training labels bucket, OpenSearch case index, Timestream baseline database, Neptune cluster, CloudWatch Logs) is encrypted with customer-managed KMS keys scoped by role. Key policies restrict usage to the specific roles that need each key; CloudTrail data events audit the usage. Audit-event payloads include PHI (the patient identifier and patient demographics) and workforce PII (the workforce member's identifier and HR-linked data); both categories must be protected.

**Privacy-office and infosec joint governance is not optional.** The detection pipeline is roughly 30% of the work. The joint privacy-and-infosec governance committee, the workforce policy, the investigation procedures, the HR coordination, the legal coordination, the appeals process, and the ongoing program review are the other 70%. A pipeline without an active joint committee that meets monthly, reviews subgroup performance, reviews recent case outcomes, approves model updates, and owns the deployment criteria will not produce sustained results. Build the governance before the technology.

**Privileged-user monitoring is its own program.** Database administrators, integration engineers, IT analysts, and researchers have access patterns fundamentally different from clinical workforce. Their monitoring should use different baselines, different feature sets, and different review processes. Some health systems run a separate privileged-access management (PAM) program with session recording, just-in-time access provisioning, and dedicated investigators. The detection patterns described in this recipe apply less directly to this population.

**Service-account and integration-account inventory.** Service accounts, integration accounts, and shared accounts must be inventoried and modeled separately from human users. Many programs discover unexpected service accounts during inventory, some with overly broad permissions. The inventory itself produces actionable findings before the detection pipeline does. The teaching example does not differentiate; production must.

**Capacity-bounded prioritization.** The teaching example generates a case for every above-threshold score. Production caps the daily case queue to the privacy office's actual review capacity, with the next-N rows held in a backlog list that gets re-evaluated tomorrow. The metric that matters most is "the privacy office can review the surfaced cases without falling behind." Threshold tuning should match the privacy office's actual throughput.

**Equity and subgroup performance audits.** Build dashboards that show flag rates, case-confirmation rates, and adjudication time by role, department, demographic group (where structurally captured and policy-permitted), employment type, and shift. Wide variation warrants investigation. Consult with employment counsel on disparate-impact considerations before formalizing thresholds that produce different rates across protected categories. The joint governance committee reviews these monthly.

**Local validation before deployment.** Before any case routes to a privacy-office investigator, run the model in shadow mode for several weeks: scoring events, generating cases, but not routing them to humans. Shadow cases get reviewed retrospectively by the lead investigator to confirm the right cases are being surfaced. This catches feature-pipeline bugs, calibration issues that did not show up in retrospective validation, and operational integration problems. Shadow review is also when case volume gets calibrated to operational capacity.

**Prospective shadow deployment.** Same lesson as Recipe 3.7 and 3.8. Skipping shadow has produced more failed deployments than any single technical issue. Plan for it in the rollout schedule rather than treating it as a problem to fix after go-live.

**Bedrock input and output handling.** Log the model ID, the prompt template version, and the response length. Never log the full prompt (contains workforce identity, patient identity, and feature evidence) or the full response. Add a PHI scanner on the output path to catch accidental patient-identifier leakage if the LLM produces unexpected text; do not trust the model to be clean every time.

**Feedback loop hygiene.** The outcome-capture path writes labels. The retraining job reads them. Retraining can drift badly if labels are wrong, so audit quality monthly: sample 25 outcome events, ask the lead investigator whether the outcome type and the dismissal reason match their reading of the case, and track the disagreement rate. Over 10% disagreement and the label schema needs revisiting before the next retrain cycle.

**Monitoring and alarms.** Wire CloudWatch alarms on: end-to-end pipeline latency (event ingest to case open) p95 above target, case volume per investigator outside target range, dismissal rate drifting, subgroup case-rate ratios above fairness thresholds, Bedrock throttle rate above baseline, SageMaker endpoint p95 latency outside service-level targets, DynamoDB consumed capacity nearing provisioned, EventBridge delivery failures, and Neptune query latency. Page the on-call data-engineering team and the model team's lead when critical alarms fire. Page the privacy-office lead and the CISO when patient-safety-relevant alarms fire (case volume crashes to zero, calibration ECE above threshold, end-to-end latency way above target).

**Records retention and legal hold.** Audit-event archives, scoring history, case data, and outcome records must be retained per applicable retention policies, and may be subject to legal hold during active investigations or litigation. Retention policies often require multi-year retention for audit data and longer for investigation records. Build retention and legal-hold capabilities into the storage layer from the start; retrofitting them later is painful. Use S3 Object Lock in COMPLIANCE mode for the audit-event lake in production; GOVERNANCE is fine for dev and test.

**Multi-AZ and disaster recovery.** Access-monitoring is operationally important even when not time-critical. Endpoints run multi-AZ. State tables replicate across AZs by default. The fallback during system outage is the EHR vendor's native audit-log review (which is slow and manual) and the privacy office's pre-existing process. Both should be documented and exercised, because the system will be down sometime and the breach-notification clock does not stop.

**Self-monitoring of the monitoring system.** The monitoring system itself contains highly sensitive data: workforce identity, patient identity, behavioral baselines, case histories, investigation outcomes. Access to the monitoring system must be tightly controlled, fully audited, and regularly reviewed. The system should monitor itself: a privacy-office investigator's access to case data is itself an audit event, and access patterns within the monitoring system warrant the same scrutiny applied to the EHR.

**Decommissioning criteria.** A model can stop working. Performance can degrade enough that it should be turned off. Decommissioning criteria (calibration ECE above X, subgroup case-confirmation rate below Y, dismissal rate above Z) should be defined and pre-approved by the joint governance committee before deployment. Without pre-approved criteria, decommissioning becomes a political conversation rather than a clinical-safety and program-effectiveness decision.

**Testing.** Table-driven unit tests on `compute_name_uniqueness`, `severity_from_break_glass_reason`, `tier_from_score`, `cohort_for_user`, `weighted_max_z`, and the rules engine; integration tests against DynamoDB Local and moto for the full ingest-enrich-detect-score-build flow; golden-path regression tests on a small labeled dataset run on every retrain so a model that breaks a subgroup does not slip through.

**Cost awareness.** Kinesis ingest, Lambda compute, DynamoDB capacity, Neptune cluster hosting, OpenSearch case index, SageMaker endpoint hosting, Bedrock invocations, and Timestream are the major line items. Track cost-per-confirmed-violation and (where measurable) cost-per-prevented-breach alongside the dollar value of avoided OCR settlements. The infrastructure cost for a moderate-size program (10,000 active workforce, 30 million audit events per day) is roughly in the $6,500-17,000/month range; preventing a single OCR settlement (settlements involving inadequate audit controls have ranged from hundreds of thousands to several million dollars per published resolution agreement) covers years of infrastructure. Privacy-office staffing (investigators, privacy analysts, the CPO function) is the dominant program cost; one investigator at typical loaded cost can equal several months of infrastructure.

None of this is unique to access-pattern anomaly detection. It is the cost of running any PHI-and-PII-adjacent prediction service that influences employment decisions and breach-notification timelines at scale. The good news is that the infrastructure (event normalization, identity-and-patient enrichment, time-series feature engine, scoring endpoint, calibration layer, explanation builder, case builder, audit index) amortizes across Recipe 3.6 (fraud-and-abuse), 3.7 (deterioration warning), 3.8 (readmission risk), and 13.x (knowledge graphs). Build it once carefully, reuse it everywhere. The hard part is not the model. The hard part is the workflow integration, the joint privacy-and-infosec governance, the privacy-office staffing, and the workforce-policy work, and that part starts on day one, not after the model passes validation.

---

*← [Main Recipe 3.9](chapter03.09-cybersecurity-access-pattern-anomalies) · [Chapter 3 Preface](chapter03-preface)*
