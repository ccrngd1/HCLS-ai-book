# Recipe 12.7: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 12.7. It shows one way you could translate the vital sign trajectory monitoring pipeline into working Python using boto3 for Kinesis ingestion, DynamoDB for patient state, Timestream for trajectory history, and SNS for alert routing. The demo uses synthetic vital sign data for a small set of patients with realistic deterioration patterns (a gradual sepsis trajectory with coordinated HR/RR rise and BP decline, a stable patient with normal variation, and a patient experiencing measurement artifact) so you can see the ingestion normalization, the per-patient baseline computation, the slope and deviation calculations, the multi-parameter pattern matching, the alert suppression logic, and the persistence and routing work end-to-end without provisioning real bedside monitors. It is not production-ready. There is no real Kinesis stream, no real Apache Flink application, no real Timestream database, no real SNS topic, no real HL7/FHIR interface, no medication administration record integration, no VPC endpoints, no KMS customer-managed keys, no per-Lambda IAM least privilege, and no clinical display integration. Think of it as the sketchpad version: useful for understanding the shape of a trajectory pipeline that respects the patient-specific-baseline discipline, the multi-parameter-correlation discipline, the suppression-before-alerting discipline, and the clinical-actionability discipline this recipe demands. Consider it a starting point, not a destination.
>
> The code maps to the six pseudocode steps from the main recipe: normalize and ingest an incoming vital sign reading (Step 1); retrieve and update the patient's rolling state including exponential moving average baselines (Step 2); compute trajectory features including slope, acceleration, deviation from baseline, and variability (Step 3); check multi-parameter correlation against known deterioration signatures (Step 4); evaluate alert conditions with suppression logic for baseline stabilization, cooldown periods, medication effects, and artifacts (Step 5); persist trajectory metrics and route alerts to the appropriate clinical channels (Step 6).

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

The demo runs against the Python standard library plus boto3. Production deployments would add [numpy](https://numpy.org/) for efficient linear regression, [scipy](https://docs.scipy.org/doc/scipy/) for statistical tests, and potentially [Apache Flink's PyFlink](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/python/overview/) for the stateful streaming computations. The demo uses pure-Python implementations of slope estimation and statistics so you can run it locally with zero extra dependencies.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `kinesis:PutRecord` on the `patient-vitals` stream
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem` on the `patient-state` table
- `timestream:WriteRecords` on the `vital-trajectories` table in your Timestream database
- `sns:Publish` on the `clinical-alerts` topic
- `cloudwatch:PutMetricData` for operational metrics

Scope each Lambda's role to the specific resource ARNs. The demo replaces all external services with in-memory mocks so you can trace the logic without provisioning anything.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Thresholds, deterioration signatures, and resource names are what you would change between environments or clinical units.

```python
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import mean, stdev

import boto3
from botocore.config import Config

# Structured logging. Never log raw vital sign values with patient identifiers.
# Log structural metadata only: patient_id_hash, parameter, alert_decision, runtime_ms.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry for throttling resilience on streaming writes.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# --- Resource Names (swap per environment) ---
KINESIS_STREAM_NAME = "patient-vitals"
DYNAMODB_TABLE_NAME = "patient-state"
TIMESTREAM_DB_NAME = "vital-signs-db"
TIMESTREAM_TABLE_NAME = "vital-trajectories"
SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:clinical-alerts"

# --- Trajectory Thresholds ---
# Baseline stabilization period: minimum hours of data before alerting.
BASELINE_STABILIZATION_HOURS = 4

# Exponential moving average alpha for baselines.
# Small alpha = slow-moving baseline that resists short-term fluctuations.
BASELINE_ALPHA = 0.05

# Alert cooldown: minimum minutes between repeated alerts for the same pattern.
ALERT_COOLDOWN_MINUTES = 60

# Artifact detection: variability threshold for readings in a very short window.
ARTIFACT_VARIABILITY_THRESHOLD = 0.15

# Single-parameter alert thresholds (deviation in standard deviations).
SINGLE_PARAM_DEVIATION_THRESHOLD = 3.0

# Per-parameter slope thresholds (units per minute) for single-param alerts.
SLOPE_THRESHOLDS = {
    "HR": 0.05,    # ~3 bpm per hour
    "RR": 0.015,   # ~1 breath/min per hour
    "SBP": 0.03,   # ~2 mmHg per hour
    "DBP": 0.02,
    "SpO2": 0.01,  # ~0.6% per hour
    "Temp": 0.005,
}

# --- Deterioration Signatures ---
# Each signature defines required and supporting parameter conditions
# that, when seen together, suggest a specific clinical concern.
DETERIORATION_SIGNATURES = {
    "early_sepsis": {
        "required": {"HR": "rising", "RR": "rising"},
        "supporting": {"SBP": "falling", "Temp": "deviating"},
        "min_required": 2,
        "min_supporting": 1,
        "severity": "alert",
        "message": "Coordinated HR/RR rise with hemodynamic compromise consistent with early sepsis",
        "recommended": "Assess patient. Consider lactate, blood cultures, and fluid resuscitation per sepsis protocol.",
    },
    "hemorrhage": {
        "required": {"HR": "rising", "SBP": "falling"},
        "supporting": {"DBP": "falling", "RR": "rising"},
        "min_required": 2,
        "min_supporting": 1,
        "severity": "alarm",
        "message": "Tachycardia with falling blood pressure suggests active hemorrhage",
        "recommended": "Immediate bedside assessment. Type and screen, large-bore IV access.",
    },
    "respiratory_failure": {
        "required": {"SpO2": "falling", "RR": "rising"},
        "supporting": {"HR": "rising"},
        "min_required": 2,
        "min_supporting": 0,
        "severity": "alert",
        "message": "Falling oxygenation with compensatory tachypnea",
        "recommended": "Assess respiratory status. Consider ABG, chest imaging, respiratory therapy.",
    },
    "cardiac_decompensation": {
        "required": {"HR": "rising", "SpO2": "falling"},
        "supporting": {"RR": "rising", "SBP": "falling"},
        "min_required": 2,
        "min_supporting": 1,
        "severity": "alert",
        "message": "Multi-parameter pattern consistent with cardiac decompensation",
        "recommended": "Cardiac assessment. Consider BNP, echocardiogram, diuretic adjustment.",
    },
}
```

---

## Mocks for Local Demonstration

These mocks replace real AWS services so you can run the full pipeline locally. In production, swap each mock for its real boto3 client call.

```python
# --- In-Memory Mocks ---
# These simulate AWS services for local execution.

class MockKinesis:
    """Simulates Kinesis PutRecord. Stores events in a list."""
    def __init__(self):
        self.records = []

    def put_record(self, StreamName, Data, PartitionKey):
        self.records.append({
            "StreamName": StreamName,
            "Data": json.loads(Data),
            "PartitionKey": PartitionKey,
        })
        return {"ShardId": "shard-0001", "SequenceNumber": str(len(self.records))}

class MockDynamoDB:
    """Simulates DynamoDB GetItem/PutItem against an in-memory dict."""
    def __init__(self):
        self.items = {}

    def get_item(self, TableName, Key):
        pk = Key.get("patient_id", {}).get("S", "")
        if pk in self.items:
            return {"Item": self.items[pk]}
        return {}

    def put_item(self, TableName, Item):
        pk = Item.get("patient_id", {}).get("S", "")
        self.items[pk] = Item
        return {}

class MockTimestream:
    """Simulates Timestream WriteRecords. Stores records in a list."""
    def __init__(self):
        self.records = []

    def write_records(self, DatabaseName, TableName, Records, CommonAttributes):
        for record in Records:
            self.records.append({**CommonAttributes, **record})
        return {"RecordsIngested": {"Total": len(Records)}}

class MockSNS:
    """Simulates SNS Publish. Stores messages in a list."""
    def __init__(self):
        self.messages = []

    def publish(self, TopicArn, Message, Subject, MessageAttributes=None):
        self.messages.append({
            "TopicArn": TopicArn,
            "Subject": Subject,
            "Message": json.loads(Message),
        })
        return {"MessageId": str(uuid.uuid4())}

# Instantiate mocks for the demo.
mock_kinesis = MockKinesis()
mock_dynamodb = MockDynamoDB()
mock_timestream = MockTimestream()
mock_sns = MockSNS()
```

---

## Step 1: Ingest Vital Sign Event

*The pseudocode calls this `ingest_vital_sign(source_event)`. It normalizes an incoming reading from any source into a standard event format and writes it to the streaming layer, partitioned by patient ID.*

```python
def ingest_vital_sign(source_event: dict) -> dict:
    """
    Normalize an incoming vital sign reading and write it to the stream.

    Different sources send data in wildly different shapes. A bedside monitor
    sends numeric arrays every second. A nurse's EHR entry sends a single
    observation with free-text context. This function unifies them into one
    consistent format so downstream processing never has to worry about source
    variability.

    Args:
        source_event: Raw event from any source (monitor, EHR, device).
            Expected keys: patient_id, timestamp (ISO string or datetime),
            parameter (HR, SBP, DBP, RR, SpO2, Temp), value (numeric),
            source_type, measurement_method (optional).

    Returns:
        The normalized event dict that was placed onto the stream.
    """
    # Normalize timestamp to UTC ISO-8601.
    ts = source_event.get("timestamp")
    if isinstance(ts, datetime):
        ts_iso = ts.astimezone(timezone.utc).isoformat()
    else:
        ts_iso = ts  # assume already ISO string

    normalized = {
        "patient_id": source_event["patient_id"],
        "timestamp": ts_iso,
        "parameter": source_event["parameter"],
        "value": float(source_event["value"]),
        "source_type": source_event.get("source_type", "nursing_assessment"),
        "measurement_method": source_event.get("measurement_method", "non_invasive"),
        "confidence": source_event.get("confidence", 1.0),
    }

    # Write to Kinesis, partitioned by patient_id so all readings
    # for one patient arrive at the same shard in order.
    mock_kinesis.put_record(
        StreamName=KINESIS_STREAM_NAME,
        Data=json.dumps(normalized),
        PartitionKey=normalized["patient_id"],
    )

    logger.info(
        "Ingested %s reading for patient %s",
        normalized["parameter"],
        normalized["patient_id"],
    )
    return normalized
```

---

## Step 2: Retrieve and Update Patient State

*The pseudocode calls this `update_patient_state(vital_event)`. It fetches the patient's rolling state from DynamoDB, updates baselines using an exponential moving average, and appends the new reading to the per-parameter rolling window.*

```python
# In-memory patient state store for the demo. In production, this is DynamoDB.
PATIENT_STATES = {}

# Maximum readings to keep in the rolling window per parameter.
MAX_WINDOW_SIZE = 60  # covers ~60 minutes of 1-min data or ~10 hours of q10min data

def update_patient_state(vital_event: dict) -> dict:
    """
    Retrieve the patient's current state, update baselines and rolling window.

    The patient state holds everything we need to compute trajectories:
    - baselines: per-parameter EMA mean and rolling std
    - last_readings: per-parameter window of recent (value, timestamp) tuples
    - alert_history: recent alerts for cooldown logic
    - baseline_stable: whether we have enough history to trust our baselines

    Args:
        vital_event: Normalized vital sign event from Step 1.

    Returns:
        The updated patient state dict.
    """
    pid = vital_event["patient_id"]
    param = vital_event["parameter"]
    value = vital_event["value"]
    ts = datetime.fromisoformat(vital_event["timestamp"])

    # Fetch or initialize state.
    if pid not in PATIENT_STATES:
        PATIENT_STATES[pid] = {
            "patient_id": pid,
            "admitted_at": ts,
            "baselines": {},
            "last_readings": defaultdict(list),
            "alert_history": [],
            "baseline_stable": False,
        }

    state = PATIENT_STATES[pid]

    # Append to rolling window for this parameter.
    state["last_readings"][param].append({"value": value, "timestamp": ts})

    # Trim window to max size.
    if len(state["last_readings"][param]) > MAX_WINDOW_SIZE:
        state["last_readings"][param] = state["last_readings"][param][-MAX_WINDOW_SIZE:]

    # Update baseline using exponential moving average.
    # Alpha = 0.05 means the baseline moves slowly, resisting short-term spikes.
    if param in state["baselines"]:
        old_mean = state["baselines"][param]["mean"]
        old_std = state["baselines"][param]["std"]
        state["baselines"][param]["mean"] = (
            (1 - BASELINE_ALPHA) * old_mean + BASELINE_ALPHA * value
        )
        deviation = abs(value - state["baselines"][param]["mean"])
        state["baselines"][param]["std"] = (
            (1 - BASELINE_ALPHA) * old_std + BASELINE_ALPHA * deviation
        )
    else:
        state["baselines"][param] = {"mean": value, "std": 0.0}

    # Check if baseline has stabilized (4+ hours of data).
    hours_since_admission = (ts - state["admitted_at"]).total_seconds() / 3600.0
    if hours_since_admission >= BASELINE_STABILIZATION_HOURS:
        state["baseline_stable"] = True

    return state
```

---

## Step 3: Compute Trajectory Features

*The pseudocode calls this `compute_trajectory(state, parameter)`. It computes slope via linear regression, acceleration as the change in slope between the early and late halves of the window, deviation from baseline in standard deviations, and variability as the coefficient of variation.*

```python
def _linear_regression_slope(times: list, values: list) -> float:
    """
    Compute the slope of a simple linear regression (least-squares fit).

    This is the core math for trajectory estimation. The slope tells us
    the rate of change in units-per-minute.

    Uses the closed-form formula: slope = (n*sum(xy) - sum(x)*sum(y)) /
                                          (n*sum(x^2) - (sum(x))^2)

    Args:
        times: List of time offsets in minutes from the first reading.
        values: List of corresponding vital sign values.

    Returns:
        Slope in units-per-minute. Positive = rising, negative = falling.
    """
    n = len(times)
    if n < 2:
        return 0.0

    sum_x = sum(times)
    sum_y = sum(values)
    sum_xy = sum(t * v for t, v in zip(times, values))
    sum_x2 = sum(t * t for t in times)

    denominator = n * sum_x2 - sum_x * sum_x
    if denominator == 0:
        return 0.0

    return (n * sum_xy - sum_x * sum_y) / denominator

def compute_trajectory(state: dict, parameter: str) -> dict:
    """
    Compute trajectory features for a single vital sign parameter.

    Returns slope (units/min), acceleration (change in slope), deviation
    from patient baseline (in sigma), and variability (coefficient of variation).

    Args:
        state: The patient's current state dict.
        parameter: Which vital sign to analyze (HR, SBP, etc.)

    Returns:
        Trajectory dict with slope, acceleration, deviation, variability,
        current value, baseline, and window duration.
        Returns None if insufficient data.
    """
    readings = state["last_readings"].get(parameter, [])

    if len(readings) < 3:
        return None  # Not enough data for trajectory estimation.

    # Build time and value arrays.
    t0 = readings[0]["timestamp"]
    times = [(r["timestamp"] - t0).total_seconds() / 60.0 for r in readings]
    values = [r["value"] for r in readings]

    # Overall slope via linear regression.
    slope = _linear_regression_slope(times, values)

    # Acceleration: compare slope of first half vs second half.
    mid = len(readings) // 2
    early_slope = _linear_regression_slope(times[:mid], values[:mid])
    late_slope = _linear_regression_slope(times[mid:], values[mid:])
    acceleration = late_slope - early_slope

    # Deviation from patient-specific baseline (in standard deviations).
    current_value = values[-1]
    baseline = state["baselines"].get(parameter, {"mean": current_value, "std": 1.0})
    baseline_mean = baseline["mean"]
    baseline_std = baseline["std"]

    if baseline_std > 0:
        deviation = (current_value - baseline_mean) / baseline_std
    else:
        deviation = 0.0

    # Variability: coefficient of variation over the window.
    window_mean = mean(values) if values else 0
    window_std = stdev(values) if len(values) >= 2 else 0
    variability = window_std / window_mean if window_mean > 0 else 0

    window_minutes = times[-1] if times else 0

    return {
        "parameter": parameter,
        "slope": slope,
        "acceleration": acceleration,
        "deviation": deviation,
        "variability": variability,
        "current": current_value,
        "baseline": baseline_mean,
        "window_minutes": window_minutes,
    }
```

---

## Step 4: Multi-Parameter Correlation Check

*The pseudocode calls this `check_multi_parameter_patterns(all_trajectories)`. It checks whether the current set of trajectories matches any known deterioration signature by evaluating the direction conditions for required and supporting parameters.*

```python
def _check_condition(trajectory: dict, condition: str) -> bool:
    """
    Evaluate whether a trajectory meets a condition string.

    Conditions:
      - "rising": slope > 0 (parameter is increasing)
      - "falling": slope < 0 (parameter is decreasing)
      - "deviating": absolute deviation > 1.5 sigma from baseline

    Args:
        trajectory: Trajectory dict from compute_trajectory().
        condition: One of "rising", "falling", "deviating".

    Returns:
        True if the condition is met.
    """
    if trajectory is None:
        return False

    if condition == "rising":
        return trajectory["slope"] > 0
    elif condition == "falling":
        return trajectory["slope"] < 0
    elif condition == "deviating":
        return abs(trajectory["deviation"]) > 1.5
    return False

def check_multi_parameter_patterns(all_trajectories: dict) -> list:
    """
    Check all trajectories against known deterioration signatures.

    This is where multi-parameter correlation dramatically improves
    specificity. Instead of alerting on "HR trending up" alone, we alert
    on "HR trending up AND RR trending up AND SBP trending down," which
    matches the early sepsis signature.

    Args:
        all_trajectories: Dict mapping parameter name to trajectory dict.

    Returns:
        List of matched pattern dicts, each containing pattern name,
        severity, clinical message, and evidence.
    """
    matched = []

    for pattern_name, signature in DETERIORATION_SIGNATURES.items():
        required_met = 0
        supporting_met = 0

        # Check required conditions.
        for param, condition in signature["required"].items():
            traj = all_trajectories.get(param)
            if _check_condition(traj, condition):
                required_met += 1

        # Check supporting conditions.
        for param, condition in signature["supporting"].items():
            traj = all_trajectories.get(param)
            if _check_condition(traj, condition):
                supporting_met += 1

        # Pattern matches if minimum thresholds are met.
        if (required_met >= signature["min_required"]
                and supporting_met >= signature["min_supporting"]):
            matched.append({
                "pattern": pattern_name,
                "severity": signature["severity"],
                "message": signature["message"],
                "recommended": signature["recommended"],
                "evidence": {
                    "required_met": required_met,
                    "supporting_met": supporting_met,
                },
            })

    return matched
```

---

## Step 5: Alert Evaluation and Suppression

*The pseudocode calls this `evaluate_alert(patient_state, trajectories, pattern_matches)`. It applies suppression logic: baseline stabilization check, cooldown period, medication effects, and artifact detection. Only alerts that pass all gates fire.*

```python
def evaluate_alert(
    patient_state: dict,
    all_trajectories: dict,
    pattern_matches: list,
) -> dict:
    """
    Decide whether to fire, suppress, or downgrade an alert.

    This is arguably the most important function in the pipeline.
    A technically correct alert that fires too often is worse than
    no alert at all because clinical staff will ignore the entire system.

    Suppression reasons:
    - Baseline not yet stable (first hours of admission)
    - Same pattern alerted within cooldown window
    - Probable measurement artifact (high variability in a very short window)

    Args:
        patient_state: Current patient state dict.
        all_trajectories: Dict of parameter -> trajectory dict.
        pattern_matches: List of matched deterioration patterns from Step 4.

    Returns:
        Decision dict with "action" (none, suppress, watch, alert, alarm)
        and supporting details.
    """
    now = datetime.now(timezone.utc)

    # Suppression check 1: baseline not yet stable.
    if not patient_state.get("baseline_stable", False):
        return {"action": "suppress", "reason": "Baseline still stabilizing"}

    # Suppression check 2: recent alert cooldown.
    if pattern_matches:
        for recent_alert in patient_state.get("alert_history", []):
            if recent_alert.get("pattern") == pattern_matches[0]["pattern"]:
                elapsed = (now - recent_alert["timestamp"]).total_seconds() / 60.0
                if elapsed < ALERT_COOLDOWN_MINUTES:
                    return {
                        "action": "suppress",
                        "reason": f"Same alert within {ALERT_COOLDOWN_MINUTES}min cooldown",
                    }

    # Suppression check 3: artifact detection.
    # If any parameter has very high variability in a window under 2 minutes,
    # it's likely a measurement artifact (probe slip, patient movement).
    for param, traj in all_trajectories.items():
        if traj is None:
            continue
        if (traj["variability"] > ARTIFACT_VARIABILITY_THRESHOLD
                and traj["window_minutes"] < 2):
            return {"action": "suppress", "reason": f"Probable artifact in {param}"}

    # Multi-parameter pattern detected: use the pattern's severity.
    if pattern_matches:
        # Use the highest severity among matched patterns.
        severities = {"watch": 0, "alert": 1, "alarm": 2}
        best = max(pattern_matches, key=lambda p: severities.get(p["severity"], 0))
        return {
            "action": best["severity"],
            "patterns": pattern_matches,
            "trajectories": all_trajectories,
        }

    # No multi-parameter pattern. Check for single-parameter deviation.
    for param, traj in all_trajectories.items():
        if traj is None:
            continue
        threshold = SLOPE_THRESHOLDS.get(param, 0.05)
        if (abs(traj["deviation"]) > SINGLE_PARAM_DEVIATION_THRESHOLD
                and abs(traj["slope"]) > threshold):
            return {
                "action": "watch",
                "reason": f"{param} deviating {traj['deviation']:.1f} sigma with slope {traj['slope']:.4f}/min",
                "trajectories": all_trajectories,
            }

    return {"action": "none"}
```

---

## Step 6: Persist Trajectory Metrics and Route Alerts

*The pseudocode calls this `persist_and_route(patient_state, trajectories, alert_decision)`. It stores all trajectory metrics in Timestream (regardless of alert status) and routes active alerts to SNS for clinical delivery.*

```python
def persist_and_route(
    patient_state: dict,
    all_trajectories: dict,
    alert_decision: dict,
) -> None:
    """
    Store trajectory metrics in Timestream and route alerts via SNS.

    Every trajectory computation is stored for retrospective analysis,
    even when no alert fires. The "show me this patient's trajectories
    for the 12 hours before the code" query is one of the most valuable
    uses of this data.

    Args:
        patient_state: Current patient state dict.
        all_trajectories: Dict of parameter -> trajectory dict.
        alert_decision: Decision dict from evaluate_alert().
    """
    pid = patient_state["patient_id"]
    now = datetime.now(timezone.utc)
    now_ms = str(int(now.timestamp() * 1000))

    # --- Persist to Timestream (always) ---
    timestream_records = []
    for param, traj in all_trajectories.items():
        if traj is None:
            continue
        timestream_records.append({
            "Dimensions": [
                {"Name": "patient_id", "Value": pid},
                {"Name": "parameter", "Value": param},
            ],
            "MeasureName": "trajectory",
            "MeasureValues": [
                {"Name": "slope", "Value": f"{traj['slope']:.6f}", "Type": "DOUBLE"},
                {"Name": "acceleration", "Value": f"{traj['acceleration']:.6f}", "Type": "DOUBLE"},
                {"Name": "deviation", "Value": f"{traj['deviation']:.2f}", "Type": "DOUBLE"},
                {"Name": "variability", "Value": f"{traj['variability']:.4f}", "Type": "DOUBLE"},
                {"Name": "current", "Value": f"{traj['current']:.1f}", "Type": "DOUBLE"},
                {"Name": "baseline", "Value": f"{traj['baseline']:.1f}", "Type": "DOUBLE"},
            ],
            "MeasureValueType": "MULTI",
            "Time": now_ms,
            "TimeUnit": "MILLISECONDS",
        })

    if timestream_records:
        mock_timestream.write_records(
            DatabaseName=TIMESTREAM_DB_NAME,
            TableName=TIMESTREAM_TABLE_NAME,
            Records=timestream_records,
            CommonAttributes={},
        )

    # --- Route alerts ---
    action = alert_decision.get("action", "none")

    if action in ("none", "suppress"):
        logger.info("Patient %s: %s (%s)", pid, action,
                    alert_decision.get("reason", ""))
        return

    if action == "watch":
        # Update patient dashboard status. No active paging.
        logger.info("Patient %s: WATCH - %s", pid, alert_decision.get("reason", ""))
        return

    if action in ("alert", "alarm"):
        # Build the alert payload for clinical delivery via SNS.
        patterns = alert_decision.get("patterns", [])
        primary_pattern = patterns[0] if patterns else {}

        # Format trajectories for clinical display.
        traj_display = {}
        for param, traj in all_trajectories.items():
            if traj is None:
                continue
            traj_display[param] = {
                "current": round(traj["current"], 1),
                "baseline": round(traj["baseline"], 1),
                "slope_per_hour": round(traj["slope"] * 60, 2),
                "deviation_sigma": round(traj["deviation"], 1),
                "window_hours": round(traj["window_minutes"] / 60, 1),
            }

        alert_payload = {
            "patient_id": pid,
            "alert_timestamp": now.isoformat(),
            "severity": action,
            "pattern": primary_pattern.get("pattern", "single_parameter"),
            "summary": primary_pattern.get("message", alert_decision.get("reason", "")),
            "recommended_action": primary_pattern.get("recommended", "Assess patient."),
            "trajectories": traj_display,
            "alert_id": f"ALT-{now.strftime('%Y%m%d-%H%M%S')}-{pid.replace('-', '')}",
        }

        mock_sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"[{action.upper()}] Trajectory alert: {pid}",
            Message=json.dumps(alert_payload, indent=2),
        )

        # Record in alert history for cooldown logic.
        patient_state["alert_history"].append({
            "pattern": primary_pattern.get("pattern"),
            "timestamp": now,
            "severity": action,
        })

        logger.info(
            "Patient %s: %s fired - %s",
            pid, action.upper(), primary_pattern.get("pattern", ""),
        )
```

---

## Putting It All Together

Here is the full pipeline assembled into a single function that processes one vital sign event end-to-end.

```python
def process_vital_sign(source_event: dict) -> dict:
    """
    Run the full vital sign trajectory pipeline for one incoming reading.

    In production, this function would be invoked by a Lambda triggered
    from Kinesis (for intermittent floor data) or embedded in a Flink
    application (for continuous ICU data).

    Args:
        source_event: Raw vital sign event from any source.

    Returns:
        The alert decision dict (action, reason, trajectories if relevant).
    """
    # Step 1: Normalize and ingest.
    normalized = ingest_vital_sign(source_event)

    # Step 2: Update patient state (baselines, rolling window).
    state = update_patient_state(normalized)

    # Step 3: Compute trajectory for the parameter that just arrived,
    # plus any other parameters with recent data (for correlation).
    all_trajectories = {}
    for param in state["last_readings"]:
        traj = compute_trajectory(state, param)
        if traj is not None:
            all_trajectories[param] = traj

    # Step 4: Check multi-parameter patterns.
    pattern_matches = check_multi_parameter_patterns(all_trajectories)

    # Step 5: Evaluate alert with suppression logic.
    alert_decision = evaluate_alert(state, all_trajectories, pattern_matches)

    # Step 6: Persist trajectory metrics and route alerts.
    persist_and_route(state, all_trajectories, alert_decision)

    return alert_decision

# --- Demo: Simulate a sepsis deterioration ---
def run_demo():
    """
    Generate synthetic vital signs for two patients:
    - Patient A: gradual sepsis trajectory over 8 hours
    - Patient B: stable patient with normal variation

    Shows how the pipeline detects the coordinated deterioration in Patient A
    while leaving Patient B alone.
    """
    print("=" * 70)
    print("VITAL SIGN TRAJECTORY MONITORING - DEMO")
    print("=" * 70)

    base_time = datetime(2026, 3, 15, 6, 0, 0, tzinfo=timezone.utc)

    # --- Patient A: gradual sepsis trajectory ---
    # HR starts at 74 and rises ~3 bpm/hr.
    # RR starts at 16 and rises ~0.8/hr.
    # SBP starts at 128 and falls ~2 mmHg/hr.
    print("\n--- Patient A: Sepsis Trajectory (8 hours of q30min vitals) ---\n")
    for i in range(16): # 16 readings over 8 hours (every 30 min)
        hours = i * 0.5
        ts = base_time + timedelta(hours=hours)

        # Simulated gradual deterioration with some noise.
        import random
        random.seed(42 + i)
        hr = 74 + (3.0 * hours) + random.uniform(-1, 1)
        rr = 16 + (0.8 * hours) + random.uniform(-0.5, 0.5)
        sbp = 128 - (2.0 * hours) + random.uniform(-2, 2)

        for param, val in [("HR", hr), ("RR", rr), ("SBP", sbp)]:
            result = process_vital_sign({
                "patient_id": "P-00847291",
                "timestamp": ts,
                "parameter": param,
                "value": val,
                "source_type": "nursing_assessment",
            })

        # Print status every 2 hours.
        if i % 4 == 3:
            state = PATIENT_STATES["P-00847291"]
            hr_traj = compute_trajectory(state, "HR")
            print(f"  Hour {hours:.0f}: HR={hr:.0f}, RR={rr:.0f}, SBP={sbp:.0f}")
            if hr_traj:
                print(f"    HR slope: {hr_traj['slope']*60:.2f} bpm/hr, "
                      f"deviation: {hr_traj['deviation']:.1f} sigma")
            print(f"    Alert decision: {result['action']}")

    # --- Patient B: stable patient ---
    print("\n--- Patient B: Stable Patient (8 hours of q30min vitals) ---\n")
    for i in range(16):
        hours = i * 0.5
        ts = base_time + timedelta(hours=hours)

        random.seed(100 + i)
        hr = 72 + random.uniform(-2, 2)
        rr = 14 + random.uniform(-1, 1)
        sbp = 122 + random.uniform(-3, 3)

        for param, val in [("HR", hr), ("RR", rr), ("SBP", sbp)]:
            result = process_vital_sign({
                "patient_id": "P-00123456",
                "timestamp": ts,
                "parameter": param,
                "value": val,
                "source_type": "nursing_assessment",
            })

    print(f"  Patient B final decision: {result['action']} (expected: none)")

    # --- Summary ---
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"\nKinesis records written: {len(mock_kinesis.records)}")
    print(f"Timestream records stored: {len(mock_timestream.records)}")
    print(f"SNS alerts published: {len(mock_sns.messages)}")

    if mock_sns.messages:
        print("\nAlert details:")
        for msg in mock_sns.messages:
            payload = msg["Message"]
            print(f"  [{payload['severity'].upper()}] {payload['pattern']}")
            print(f"    {payload['summary']}")
            print(f"    Recommended: {payload['recommended_action']}")
            print(f"    Trajectories:")
            for p, t in payload["trajectories"].items():
                print(f"      {p}: current={t['current']}, baseline={t['baseline']}, "
                      f"slope={t['slope_per_hour']}/hr, dev={t['deviation_sigma']}σ")

if __name__ == "__main__":
    run_demo()
```

---

## The Gap Between This and Production

This example works. Run it and you will see the pipeline detect Patient A's sepsis trajectory while leaving Patient B alone. But there is meaningful distance between "works in a script" and "runs in an ICU monitoring real patients." Here is where that gap lives:

**Real streaming infrastructure.** The demo processes events sequentially in memory. Production uses Kinesis Data Streams for ingestion and either Lambda (floor patients with intermittent vitals) or Apache Flink via Kinesis Data Analytics (ICU patients with continuous monitoring). Flink handles the stateful windowed computations with exactly-once semantics, maintaining per-patient state without external database calls on every event.

**HL7/FHIR integration.** Real vital signs arrive via HL7v2 ADT/OBX messages from bedside monitors or FHIR Observation resources from the EHR. The normalization step in production must parse HL7 segments, map device-specific parameter codes to standard names, handle unit conversions (Fahrenheit to Celsius, inches of mercury to mmHg), and deal with the reality that different monitors report different parameter sets.

**Medication administration awareness.** The demo omits medication-aware suppression entirely. In production, you need a feed from the Medication Administration Record (MAR). When a patient receives a beta-blocker and their HR drops, that is the drug working, not deterioration. Without this, your system will cry wolf after every Metoprolol dose. This integration alone is typically a 3-6 month project.

**Apache Flink for continuous monitoring.** For ICU patients where data arrives every second, you cannot afford a DynamoDB read/write on every event. A Flink application maintains per-patient state in memory with periodic checkpointing, computes rolling statistics over configurable windows, and only emits events downstream when trajectory features change significantly. The demo's per-event architecture is fine for floor patients with q4h vitals but will not scale to ICU data density.

**Robust statistics.** The demo uses simple linear regression for slope estimation. Production should use robust methods like Theil-Sen estimation (resistant to outliers) or weighted least squares (weighting recent readings more heavily). For irregularly sampled data, a Kalman filter provides proper handling of varying time gaps between observations.

**DynamoDB design.** The demo uses a simple patient_id key. Production needs a composite key design supporting queries like "all patients on Unit 4B with active watch or alert status" for the unit dashboard. A GSI on unit + alert_status enables this. TTL automatically expires state records for discharged patients.

**Timestream query patterns.** Storing trajectory metrics in Timestream enables powerful temporal queries: "Show me this patient's HR slope over the last 24 hours" or "Find all patients whose SpO2 deviation exceeded 2 sigma in the last shift." Production systems build CloudWatch dashboards on top of Timestream scheduled queries for unit-level situational awareness.

**Error handling and dead-letter queues.** If trajectory computation fails for one patient, it must not affect other patients. Production Lambda functions wrap each patient's processing in try/except blocks, send failures to an SQS dead-letter queue for investigation, and emit CloudWatch metrics on error rates. Both the trajectory-processor and alert-evaluator Lambdas need their own DLQ. The Flink application uses a side-output stream for events that fail parsing or state-update logic. Set CloudWatch alarms on DLQ depth > 0 with a 1-minute evaluation period. In a clinical safety system, a silently dropped reading means a patient is invisible to monitoring. Treat DLQ depth > 0 as an operational incident, not a metric to trend.

**IAM least-privilege.** The trajectory-processor Lambda needs `kinesis:GetRecords` (read from stream), `dynamodb:GetItem`/`PutItem` (patient state), `timestream:WriteRecords` (metrics), but NOT `sns:Publish` (that belongs to the alert-evaluator Lambda). Each Lambda gets exactly the permissions it needs, scoped to specific resource ARNs. Not `dynamodb:*`. Not `AdministratorAccess`.

**VPC and network isolation.** Vital signs are PHI. In production, all Lambda functions and the Flink application run inside a VPC with private subnets. VPC endpoints for DynamoDB, Timestream, SNS, and CloudWatch Logs keep traffic on the AWS backbone. The Kinesis stream uses interface endpoints. No PHI traverses the public internet.

**Encryption.** Production uses KMS customer-managed keys for the Kinesis stream (server-side encryption), DynamoDB table (encryption at rest), Timestream database (encryption at rest), and SNS topic (encrypted messages). Key rotation enabled. CloudTrail logs every key usage for the HIPAA audit trail.

**Alert delivery confirmation.** When SNS publishes a clinical alert, production tracks whether it was delivered and acknowledged. If a nurse does not acknowledge an alert within a configured window, the system escalates to the charge nurse. This requires a delivery tracking mechanism (SNS delivery status logging + a separate Lambda checking acknowledgment state).

**Clinical display integration.** The demo prints to stdout. Production integrates with the EHR (via SMART on FHIR or CDS Hooks), the unit's patient status board, and the paging system. Each integration has its own latency characteristics and failure modes.

**Testing.** There are no tests here. A production pipeline has unit tests for `compute_trajectory` (with known synthetic data), integration tests for the full pipeline with MIMIC-III derived scenarios, and a validation suite that compares trajectory alerts against historical rapid response events to measure sensitivity and specificity. Never use real patient data in test fixtures.

**Tuning and feedback.** Production systems log every alert decision (fire, suppress, and why) for retrospective analysis. Clinical teams review false positives and missed events monthly, adjusting thresholds, cooldown windows, and deterioration signatures based on their patient population. The configuration constants at the top of this file are starting points. They will need tuning per unit, per acuity level, and over time.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 12.7](chapter12.07-vital-sign-trajectory-monitoring.md) for the full architectural walkthrough, pseudocode, deterioration signatures, and honest take on why alert fatigue is the real enemy.*
