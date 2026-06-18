# Recipe 7.10: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the optimal intervention timing pipeline from Recipe 7.10. It demonstrates the core concepts (longitudinal feature engineering, survival modeling, intervention window scoring) using synthetic data and a basic hazard model. It is not production-ready. Real intervention timing systems require validated causal models, clinical oversight, and months of calibration against actual outcomes. Think of this as the sketch on the whiteboard, not the blueprint for construction.

---

## Setup

You'll need the following packages:

```bash
pip install boto3 numpy pandas scikit-learn
```

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `sagemaker:InvokeEndpoint` (for model inference in the AWS-integrated version)
- `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:UpdateItem` (for patient state storage)
- `s3:GetObject`, `s3:PutObject` (for timeline data and model artifacts)

For this example, we'll build the entire pipeline locally with synthetic data. The SageMaker integration points are noted where you'd swap in real endpoint calls.

---

## Config and Constants

These thresholds and parameters control the intervention timing logic. In production, these would be tuned based on clinical validation studies and care team feedback. Start conservative (higher thresholds, longer cooldown periods) and loosen as you build confidence in the model's calibration.

```python
import logging
from decimal import Decimal

# Structured logging. Never log PHI field values (patient names, MRNs, etc.).
# Log patient_id only when necessary for debugging, and ensure logs are
# stored in HIPAA-compliant destinations with appropriate access controls.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- Hazard thresholds ---
# These define what "high risk" and "moderate risk" mean in terms of daily hazard.
# A daily hazard of 0.05 means roughly a 5% chance of the target event on that day,
# given the patient has survived to that day.
HIGH_RISK_THRESHOLD = 0.05
MODERATE_RISK_THRESHOLD = 0.02

# --- Intervention scoring thresholds ---
# These control when the system recommends action vs. continued monitoring.
URGENT_THRESHOLD = 80.0       # Score above this = "intervene today or tomorrow"
ACTION_THRESHOLD = 40.0       # Score above this = "intervene this week"

# --- Intervention fatigue parameters ---
# Minimum days between outreach attempts to avoid patient fatigue.
# Calling a patient every 3 days trains them to ignore you.
MIN_INTERVENTION_GAP_DAYS = 14
FATIGUE_DAMPENING = 0.3       # Multiply score by this if within cooldown period
DECLINED_DAMPENING = 0.1      # Multiply score by this if patient recently declined

# --- Model parameters ---
FORECAST_HORIZON_DAYS = 30    # How many days ahead the model predicts
LOOKBACK_DAYS = 730           # How far back to look for patient history (2 years)

# --- DynamoDB table name ---
PATIENT_STATE_TABLE = "intervention-timing-patient-state"
```

---

## Step 1: Generate Synthetic Patient Timelines

*The main recipe's Step 1 assembles patient timelines from EHR, claims, pharmacy, and lab systems. Here we generate realistic synthetic data that mimics the structure of those timelines. In production, this step would be a Glue ETL job pulling from your actual data sources.*

```python
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

def generate_synthetic_timeline(patient_id: str, risk_profile: str = "rising") -> dict:
    """
    Generate a synthetic patient timeline for demonstration purposes.

    Creates a realistic sequence of clinical events over 2 years, with
    different risk profiles to show how the timing model responds to
    different trajectory shapes.

    Args:
        patient_id: Unique patient identifier
        risk_profile: One of "rising", "stable_high", "sudden_spike", "improving"
                      Controls the shape of the risk trajectory in the synthetic data.

    Returns:
        A patient timeline dict matching the schema from the main recipe.
    """
    np.random.seed(hash(patient_id) % 2**32)

    end_date = datetime(2026, 5, 31)
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    events = []

    # Generate encounters (office visits, ED visits, inpatient stays)
    # Frequency depends on risk profile: sicker patients have more encounters.
    if risk_profile == "rising":
        # Encounters accelerate over time: quarterly early, monthly later
        encounter_dates = []
        current = start_date
        gap_days = 90  # start with quarterly visits
        while current < end_date:
            encounter_dates.append(current)
            # Gradually decrease gap (more frequent visits as risk rises)
            gap_days = max(14, gap_days - np.random.randint(5, 15))
            current += timedelta(days=gap_days + np.random.randint(-5, 5))
    elif risk_profile == "stable_high":
        # Consistent monthly encounters
        encounter_dates = [
            start_date + timedelta(days=30 * i + np.random.randint(-3, 3))
            for i in range(24)
        ]
    elif risk_profile == "sudden_spike":
        # Quarterly visits, then a burst of activity in the last 2 weeks
        encounter_dates = [
            start_date + timedelta(days=90 * i + np.random.randint(-5, 5))
            for i in range(8)
        ]
        # Add sudden burst
        for i in range(4):
            encounter_dates.append(end_date - timedelta(days=np.random.randint(1, 14)))
    else:  # improving
        # Frequent early, tapering off
        encounter_dates = []
        current = start_date
        gap_days = 14
        while current < end_date:
            encounter_dates.append(current)
            gap_days = min(120, gap_days + np.random.randint(3, 10))
            current += timedelta(days=gap_days)

    for enc_date in encounter_dates:
        # Most encounters are outpatient; sprinkle in ED visits for high-risk profiles
        enc_type = "outpatient"
        if risk_profile in ("rising", "stable_high") and np.random.random() < 0.1:
            enc_type = "ED"
        elif risk_profile == "sudden_spike" and enc_date > end_date - timedelta(days=14):
            enc_type = "ED" if np.random.random() < 0.3 else "outpatient"

        events.append({
            "timestamp": enc_date.isoformat(),
            "event_type": "encounter",
            "event_subtype": enc_type,
            "attributes": {
                "diagnosis_codes": ["E11.9"],  # Type 2 diabetes, simplified
                "provider_type": "endocrinology" if np.random.random() < 0.3 else "primary_care",
            }
        })

    # Generate A1C lab results (quarterly, with trajectory based on risk profile)
    a1c_dates = [start_date + timedelta(days=90 * i) for i in range(9)]
    for i, lab_date in enumerate(a1c_dates):
        if lab_date > end_date:
            break

        if risk_profile == "rising":
            # A1C drifts upward: 7.2 -> 9.1 over 2 years
            a1c_value = 7.2 + (i * 0.25) + np.random.normal(0, 0.1)
        elif risk_profile == "stable_high":
            # A1C stays elevated around 8.5
            a1c_value = 8.5 + np.random.normal(0, 0.3)
        elif risk_profile == "sudden_spike":
            # A1C stable then jumps
            a1c_value = 7.0 + (0.3 if i >= 7 else 0) + np.random.normal(0, 0.1)
            if i == 8:
                a1c_value = 9.5  # sudden spike
        else:  # improving
            a1c_value = 9.0 - (i * 0.2) + np.random.normal(0, 0.1)

        events.append({
            "timestamp": lab_date.isoformat(),
            "event_type": "lab",
            "event_subtype": "A1C",
            "attributes": {
                "value": round(a1c_value, 1),
                "reference_low": 4.0,
                "reference_high": 5.6,
                "abnormal_flag": "H" if a1c_value > 5.6 else "N",
            }
        })

    # Generate medication fills (monthly for adherent, gaps for non-adherent)
    med_date = start_date + timedelta(days=np.random.randint(0, 30))
    while med_date < end_date:
        events.append({
            "timestamp": med_date.isoformat(),
            "event_type": "medication",
            "event_subtype": "fill",
            "attributes": {
                "drug_name": "metformin",
                "days_supply": 30,
                "refill_number": len([e for e in events if e["event_type"] == "medication"]),
            }
        })

        # Introduce gaps for rising-risk patients (missed refills)
        if risk_profile == "rising" and med_date > end_date - timedelta(days=120):
            # Increasingly likely to miss refills as risk rises
            gap = 30 + np.random.randint(5, 20)  # overdue refills
        elif risk_profile == "sudden_spike" and med_date > end_date - timedelta(days=30):
            gap = 45  # missed a refill entirely
        else:
            gap = 30 + np.random.randint(-2, 3)  # normal adherence

        med_date += timedelta(days=gap)

    # Sort all events chronologically
    events.sort(key=lambda e: e["timestamp"])

    return {
        "patient_id": patient_id,
        "timeline": events,
        "event_count": len(events),
        "span_days": (end_date - start_date).days,
    }
```

---

## Step 2: Engineer Temporal Features

*The main recipe's Step 2 transforms raw timelines into features that capture temporal dynamics: velocity, acceleration, gaps, and recency. This is where static data becomes timing-aware.*

```python
def engineer_temporal_features(timeline: dict, observation_date: datetime) -> dict:
    """
    Compute temporal features from a patient timeline at a specific observation point.

    These features capture not just current state but rate of change, acceleration,
    and gaps. The timing model needs these dynamics to predict when risk will peak.

    Args:
        timeline: Patient timeline dict from Step 1 (or from your data pipeline)
        observation_date: The date at which to compute features (today for inference,
                         historical dates for training)

    Returns:
        Dictionary of feature name -> value. Null values indicate missing data
        (the model should handle nulls gracefully via imputation or masking).
    """
    events = timeline["timeline"]
    features = {}

    # Parse timestamps and filter to events before observation_date
    # (we can't use future events when making predictions)
    parsed_events = []
    for event in events:
        event_date = datetime.fromisoformat(event["timestamp"])
        if event_date <= observation_date:
            parsed_events.append({**event, "_parsed_date": event_date})

    # --- Recency features ---
    # How long since key event types? Longer gaps often signal disengagement.
    encounters = [e for e in parsed_events if e["event_type"] == "encounter"]
    ed_visits = [e for e in parsed_events
                 if e["event_type"] == "encounter" and e["event_subtype"] == "ED"]
    med_fills = [e for e in parsed_events if e["event_type"] == "medication"]
    labs = [e for e in parsed_events if e["event_type"] == "lab"]

    features["days_since_last_encounter"] = (
        (observation_date - encounters[-1]["_parsed_date"]).days
        if encounters else None
    )
    features["days_since_last_ed_visit"] = (
        (observation_date - ed_visits[-1]["_parsed_date"]).days
        if ed_visits else None
    )
    features["days_since_last_med_fill"] = (
        (observation_date - med_fills[-1]["_parsed_date"]).days
        if med_fills else None
    )
    features["days_since_last_lab"] = (
        (observation_date - labs[-1]["_parsed_date"]).days
        if labs else None
    )

    # --- Velocity features: rate of change in key lab values ---
    # Extract A1C values and compute slope over recent measurements.
    a1c_results = [
        (e["_parsed_date"], e["attributes"]["value"])
        for e in parsed_events
        if e["event_type"] == "lab" and e["event_subtype"] == "A1C"
    ]

    if len(a1c_results) >= 2:
        features["a1c_current"] = a1c_results[-1][1]

        # Compute slope using last 3 measurements (or all if fewer)
        recent_a1c = a1c_results[-3:]
        if len(recent_a1c) >= 2:
            # Simple linear slope: (last - first) / days between them
            days_span = (recent_a1c[-1][0] - recent_a1c[0][0]).days
            if days_span > 0:
                value_change = recent_a1c[-1][1] - recent_a1c[0][1]
                features["a1c_slope_per_day"] = value_change / days_span
            else:
                features["a1c_slope_per_day"] = 0.0
        else:
            features["a1c_slope_per_day"] = None
    else:
        features["a1c_current"] = None
        features["a1c_slope_per_day"] = None

    # --- Acceleration features: is utilization rate changing? ---
    thirty_days_ago = observation_date - timedelta(days=30)
    sixty_days_ago = observation_date - timedelta(days=60)

    encounters_last_30 = len([
        e for e in encounters if e["_parsed_date"] > thirty_days_ago
    ])
    encounters_prior_30 = len([
        e for e in encounters
        if sixty_days_ago < e["_parsed_date"] <= thirty_days_ago
    ])
    features["encounter_acceleration"] = encounters_last_30 - encounters_prior_30

    # --- Gap features: missed expected events ---
    # Check if the patient is overdue for a medication refill.
    if med_fills:
        last_fill = med_fills[-1]
        days_supply = last_fill["attributes"].get("days_supply", 30)
        expected_refill = last_fill["_parsed_date"] + timedelta(days=days_supply)
        if observation_date > expected_refill:
            features["med_gap_days"] = (observation_date - expected_refill).days
        else:
            features["med_gap_days"] = 0
    else:
        features["med_gap_days"] = None

    # --- Pattern features ---
    features["total_encounters_180d"] = len([
        e for e in encounters
        if e["_parsed_date"] > observation_date - timedelta(days=180)
    ])
    features["ed_visits_365d"] = len([
        e for e in ed_visits
        if e["_parsed_date"] > observation_date - timedelta(days=365)
    ])

    return features
```

---

## Step 3: Predict Hazard Trajectory

*The main recipe's Step 3 trains an LSTM-based survival model. Here we use a simplified hazard estimation approach that demonstrates the concept without requiring GPU training infrastructure. In production, you'd replace this with a SageMaker-hosted model endpoint.*

```python
def predict_hazard_trajectory(features: dict, horizon_days: int = FORECAST_HORIZON_DAYS) -> list:
    """
    Predict the daily hazard trajectory for the next N days.

    This is a SIMPLIFIED hazard model for demonstration. It uses the temporal
    features to estimate a baseline hazard and a trajectory shape. A real
    implementation would call a SageMaker endpoint hosting a trained LSTM or
    transformer survival model.

    The key insight this demonstrates: hazard isn't flat. It has a shape over time
    that depends on the patient's current trajectory. A patient with rising A1C
    and a missed medication refill has a hazard that accelerates over the next
    few weeks, not a constant elevated risk.

    Args:
        features: Temporal feature dict from Step 2
        horizon_days: How many days ahead to forecast

    Returns:
        List of daily hazard values (probability of event on each day,
        conditional on survival to that day). Length = horizon_days.
    """
    # --- Compute baseline hazard from current state ---
    # In a real model, this comes from the neural network's output layer.
    # Here we use a simple logistic combination of features.
    baseline = 0.01  # population average daily hazard

    # A1C contribution: higher A1C = higher baseline hazard
    a1c = features.get("a1c_current")
    if a1c is not None:
        # Hazard increases exponentially above A1C of 7.0
        if a1c > 7.0:
            baseline += 0.005 * (a1c - 7.0) ** 1.5

    # Medication gap contribution: overdue refills increase hazard
    med_gap = features.get("med_gap_days")
    if med_gap is not None and med_gap > 0:
        # Hazard grows with days overdue (non-linear: worse the longer you wait)
        baseline += 0.002 * (med_gap / 7) ** 1.2

    # ED visit recency: recent ED visit indicates instability
    days_since_ed = features.get("days_since_last_ed_visit")
    if days_since_ed is not None and days_since_ed < 30:
        baseline += 0.01 * (1 - days_since_ed / 30)

    # --- Compute trajectory shape from velocity features ---
    # The slope determines whether hazard is rising, flat, or falling.
    a1c_slope = features.get("a1c_slope_per_day", 0) or 0
    encounter_accel = features.get("encounter_acceleration", 0) or 0

    # Daily hazard growth rate: how much the hazard changes per day
    # Positive slope + accelerating encounters = rising hazard
    daily_growth = (a1c_slope * 50) + (encounter_accel * 0.003)

    # --- Generate the trajectory ---
    trajectory = []
    current_hazard = baseline

    for day in range(horizon_days):
        # Apply growth (hazard changes over time based on trajectory)
        current_hazard += daily_growth

        # Clamp to reasonable bounds (hazard can't be negative or > 1)
        current_hazard = max(0.001, min(0.5, current_hazard))

        trajectory.append(round(current_hazard, 6))

    return trajectory

# --- SageMaker integration point ---
# In production, replace predict_hazard_trajectory with a call to your
# trained model endpoint:
#
# import boto3
# from botocore.config import Config
#
# sagemaker_runtime = boto3.client(
#     "sagemaker-runtime",
#     config=Config(retries={"max_attempts": 3, "mode": "adaptive"})
# )
#
# def predict_hazard_trajectory_sagemaker(features: dict) -> list:
#     """Call the SageMaker endpoint hosting the trained survival model."""
#     import json
#     response = sagemaker_runtime.invoke_endpoint(
#         EndpointName="intervention-timing-model-v1",
#         ContentType="application/json",
#         Body=json.dumps({"features": features}),
#     )
#     result = json.loads(response["Body"].read())
#     return result["hazard_trajectory"]
```

---

## Step 4: Score Intervention Windows

*The main recipe's Step 4 applies decision logic to the hazard trajectory. This is where "risk prediction" becomes "timing recommendation." The scoring function identifies whether the patient is in an optimal intervention window based on the shape of their predicted trajectory.*

```python
def score_intervention_window(
    patient_id: str,
    hazard_trajectory: list,
    days_since_last_intervention: int = 30,
    last_intervention_outcome: str = "engaged",
) -> dict:
    """
    Determine whether now is the right time to intervene for this patient.

    The core logic: interventions work best when risk is rising but hasn't peaked.
    You want to catch the patient on the upslope, not at the top (too late) or
    on the flat (too early, they won't engage).

    Args:
        patient_id: Patient identifier
        hazard_trajectory: List of daily hazard values from Step 3
        days_since_last_intervention: Days since care team last reached out
        last_intervention_outcome: "engaged", "no_answer", or "declined"

    Returns:
        Intervention scoring result with recommended action and timing window.
    """
    # Compute trajectory characteristics
    current_hazard = hazard_trajectory[0]
    peak_hazard = max(hazard_trajectory)
    peak_day = hazard_trajectory.index(peak_hazard)

    # Slope over first 7 days (is risk rising in the near term?)
    if len(hazard_trajectory) >= 7:
        hazard_slope = (hazard_trajectory[6] - hazard_trajectory[0]) / 7
    else:
        hazard_slope = 0.0

    # --- Decision logic ---
    intervention_score = 0.0
    recommended_action = "monitor"
    action_window_days = None

    # Case 1: Rising risk with peak ahead. This is the prime intervention window.
    # The patient is deteriorating, but we still have time to change the trajectory.
    # Threshold is lower than the pseudocode's 0.01 because our simplified
    # hazard model produces smaller absolute slope values than a trained LSTM would.
    if hazard_slope > 0.001 and 2 < peak_day < 14:
        # Score scales with how fast risk is rising and how much worse it will get
        intervention_score = hazard_slope * 100 * (peak_hazard / max(current_hazard, 0.001))

    # Case 2: Already at or past peak. Window may be closing.
    # Intervene urgently if current risk is high, but acknowledge we may be late.
    elif peak_day <= 2 and current_hazard > HIGH_RISK_THRESHOLD:
        intervention_score = current_hazard * 50
        recommended_action = "urgent_outreach"
        action_window_days = 1

    # Case 3: Flat high risk. Chronically elevated but not acutely changing.
    # Timing is less critical here; schedule outreach at convenience.
    elif current_hazard > MODERATE_RISK_THRESHOLD and abs(hazard_slope) < 0.0005:
        intervention_score = current_hazard * 20
        recommended_action = "scheduled_outreach"
        action_window_days = 7

    # --- Apply intervention fatigue dampening ---
    # Patients who were recently contacted (or who declined) get lower urgency.
    # This prevents the "boy who cried wolf" problem.
    if days_since_last_intervention < MIN_INTERVENTION_GAP_DAYS:
        intervention_score *= FATIGUE_DAMPENING
    if last_intervention_outcome == "declined":
        intervention_score *= DECLINED_DAMPENING

    # --- Determine final recommendation ---
    if intervention_score > URGENT_THRESHOLD:
        recommended_action = "immediate_outreach"
        action_window_days = 2
    elif intervention_score > ACTION_THRESHOLD:
        recommended_action = "outreach_this_week"
        action_window_days = max(1, peak_day - 1)

    return {
        "patient_id": patient_id,
        "intervention_score": round(intervention_score, 1),
        "recommended_action": recommended_action,
        "action_window_days": action_window_days,
        "current_hazard": round(current_hazard, 4),
        "predicted_peak_day": peak_day,
        "peak_hazard": round(peak_hazard, 4),
        "trajectory_slope": round(hazard_slope, 6),
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
```

---

## Step 5: Generate Explanations and Recommendations

*The main recipe's Step 5 assembles scored patients into an actionable worklist with "why now" explanations. Care managers won't act on a number without understanding what changed.*

```python
def generate_explanation(scored_result: dict, features: dict) -> str:
    """
    Build a human-readable explanation of why this patient needs outreach now.

    This is critical for adoption. A care manager looking at a worklist of 8
    patients needs to understand, in 10 seconds, why each patient is there today
    and not yesterday or next week. The explanation should reference specific
    clinical changes, not model internals.

    Args:
        scored_result: Output from score_intervention_window
        features: Temporal features from Step 2 (used to identify clinical drivers)

    Returns:
        A plain-English explanation string suitable for display in a care
        management platform.
    """
    parts = []

    # Trajectory shape explanation
    if scored_result["trajectory_slope"] > 0.002:
        parts.append("Risk trajectory is rising sharply")
    elif scored_result["trajectory_slope"] > 0.0005:
        parts.append("Risk trajectory is trending upward")

    # Peak timing
    peak_day = scored_result["predicted_peak_day"]
    if 0 < peak_day < 14:
        parts.append(f"Predicted risk peak within {peak_day} days")

    # Current risk level
    if scored_result["current_hazard"] > HIGH_RISK_THRESHOLD:
        parts.append("Current risk level is elevated")

    # Clinical drivers from features
    a1c = features.get("a1c_current")
    a1c_slope = features.get("a1c_slope_per_day")
    if a1c is not None and a1c > 8.0:
        if a1c_slope and a1c_slope > 0:
            parts.append(f"A1C at {a1c} and rising")
        else:
            parts.append(f"A1C elevated at {a1c}")

    med_gap = features.get("med_gap_days")
    if med_gap and med_gap > 7:
        parts.append(f"Medication refill overdue by {med_gap} days")

    days_since_enc = features.get("days_since_last_encounter")
    if days_since_enc and days_since_enc > 90:
        parts.append(f"No encounter in {days_since_enc} days")

    return ". ".join(parts) + "." if parts else "Risk score elevated above action threshold."

def generate_worklist(scored_patients: list, features_by_patient: dict,
                      capacity: int = 8) -> list:
    """
    Assemble the final care team worklist from scored patients.

    Applies capacity constraints and generates explanations. The output is
    what the care manager sees in their workflow tool each morning.

    Args:
        scored_patients: List of scoring results from Step 4
        features_by_patient: Dict mapping patient_id -> features from Step 2
        capacity: Maximum number of recommendations to generate (care team slots)

    Returns:
        List of recommendation dicts, sorted by urgency, capped at capacity.
    """
    # Filter to actionable recommendations only
    actionable = [s for s in scored_patients if s["recommended_action"] != "monitor"]

    # Sort by intervention score (most urgent first)
    actionable.sort(key=lambda x: x["intervention_score"], reverse=True)

    # Cap at team capacity
    recommendations = actionable[:capacity]

    # Add explanations
    for rec in recommendations:
        patient_features = features_by_patient.get(rec["patient_id"], {})
        rec["explanation"] = generate_explanation(rec, patient_features)
        rec["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(days=rec["action_window_days"] or 7)
        ).isoformat()
        rec["status"] = "pending"

    return recommendations
```

---

## Step 6: Store Results in DynamoDB

*In production, recommendations are written to DynamoDB for the care management platform to consume. This step shows the storage pattern with proper Decimal handling and TTL for automatic expiration of stale recommendations.*

```python
import boto3
from botocore.config import Config
import json

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

def store_recommendation(recommendation: dict) -> dict:
    """
    Write an intervention recommendation to DynamoDB.

    The care management platform reads from this table to populate the
    care manager's daily worklist. TTL ensures stale recommendations
    (where the action window has passed) are automatically cleaned up.

    Args:
        recommendation: A single recommendation dict from generate_worklist

    Returns:
        The stored record (with DynamoDB-compatible types).
    """
    table = dynamodb.Table(PATIENT_STATE_TABLE)

    # Convert floats to Decimal (DynamoDB requirement).
    # boto3 will raise TypeError on raw floats in put_item.
    record = {
        "patient_id": recommendation["patient_id"],
        "scored_at": recommendation["scored_at"],
        "intervention_score": Decimal(str(recommendation["intervention_score"])),
        "recommended_action": recommendation["recommended_action"],
        "action_window_days": recommendation.get("action_window_days"),
        "current_hazard": Decimal(str(recommendation["current_hazard"])),
        "predicted_peak_day": recommendation["predicted_peak_day"],
        "peak_hazard": Decimal(str(recommendation["peak_hazard"])),
        "trajectory_slope": Decimal(str(recommendation["trajectory_slope"])),
        "explanation": recommendation["explanation"],
        "expires_at": recommendation["expires_at"],
        "status": recommendation["status"],
    }

    # TTL: DynamoDB will automatically delete expired recommendations.
    # This prevents stale items from cluttering the worklist.
    expiry_dt = datetime.fromisoformat(recommendation["expires_at"].replace("Z", "+00:00"))
    record["ttl"] = int(expiry_dt.timestamp())

    table.put_item(Item=record)
    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. This is what you'd invoke daily (for batch scoring) or on-demand (when a real-time event triggers rescoring for a specific patient).

```python
def run_intervention_timing_pipeline(patient_ids: list, capacity: int = 8) -> list:
    """
    Run the full optimal intervention timing pipeline for a panel of patients.

    This orchestrates all steps: timeline assembly, feature engineering,
    hazard prediction, intervention window scoring, and worklist generation.

    In production, Steps 1-2 would pull from your data lake (S3/Glue),
    Step 3 would call a SageMaker endpoint, and Steps 4-6 would run in Lambda.

    Args:
        patient_ids: List of patient IDs to score
        capacity: Care team outreach capacity (max recommendations to generate)

    Returns:
        Final worklist of intervention recommendations, sorted by urgency.
    """
    print(f"=== Intervention Timing Pipeline ===")
    print(f"Scoring {len(patient_ids)} patients, capacity = {capacity} slots\n")

    scored_patients = []
    features_by_patient = {}

    # Assign risk profiles for demonstration purposes.
    # In production, you'd just pull real timelines from your data lake.
    profiles = ["rising", "stable_high", "sudden_spike", "improving", "rising"]

    for i, patient_id in enumerate(patient_ids):
        profile = profiles[i % len(profiles)]
        print(f"Patient {patient_id} (profile: {profile})")

        # Step 1: Assemble timeline
        timeline = generate_synthetic_timeline(patient_id, risk_profile=profile)
        print(f"  Timeline: {timeline['event_count']} events over {timeline['span_days']} days")

        # Step 2: Engineer features at current observation date
        observation_date = datetime(2026, 5, 31)
        features = engineer_temporal_features(timeline, observation_date)
        features_by_patient[patient_id] = features
        print(f"  Features: A1C={features.get('a1c_current')}, "
              f"med_gap={features.get('med_gap_days')}d, "
              f"slope={features.get('a1c_slope_per_day')}")

        # Step 3: Predict hazard trajectory
        trajectory = predict_hazard_trajectory(features)
        print(f"  Trajectory: current={trajectory[0]:.4f}, "
              f"peak={max(trajectory):.4f} on day {trajectory.index(max(trajectory))}")

        # Step 4: Score intervention window
        # Simulate varying intervention histories
        days_since = 30 if i % 3 != 0 else 7  # some patients were recently contacted
        outcome = "engaged" if i % 4 != 0 else "declined"

        score = score_intervention_window(
            patient_id, trajectory,
            days_since_last_intervention=days_since,
            last_intervention_outcome=outcome,
        )
        scored_patients.append(score)
        print(f"  Score: {score['intervention_score']} -> {score['recommended_action']}")
        print()

    # Step 5: Generate worklist with explanations
    print("=== Generating Worklist ===\n")
    worklist = generate_worklist(scored_patients, features_by_patient, capacity=capacity)

    for i, rec in enumerate(worklist, 1):
        print(f"{i}. [{rec['recommended_action']}] Patient {rec['patient_id']}")
        print(f"   Score: {rec['intervention_score']} | "
              f"Window: {rec['action_window_days']} days")
        print(f"   Why: {rec['explanation']}")
        print()

    print(f"Total actionable: {len(worklist)} of {len(scored_patients)} patients scored")
    return worklist

# --- Run the demo ---
if __name__ == "__main__":
    # Simulate a care manager's panel of 10 patients
    patient_ids = [f"PAT-{1000 + i}" for i in range(10)]

    worklist = run_intervention_timing_pipeline(patient_ids, capacity=8)

    # Print final worklist as JSON (what the care management platform would consume)
    print("\n=== JSON Output (for care management platform) ===\n")
    # Convert for JSON serialization (Decimal -> float for display)
    for rec in worklist:
        for key, val in rec.items():
            if isinstance(val, Decimal):
                rec[key] = float(val)
    print(json.dumps(worklist[:3], indent=2))  # show first 3 for brevity
```

---

## The Gap Between This and Production

This example demonstrates the concepts. It generates synthetic data, computes temporal features, predicts hazard trajectories, and scores intervention windows. But there's a significant distance between this sketch and a system you'd deploy to a care management team. Here's where that gap lives:

**The survival model is a heuristic, not a trained model.** The `predict_hazard_trajectory` function uses hand-coded rules to approximate what a trained LSTM survival model would produce. A real implementation trains on thousands of patient timelines with known outcomes, learning the complex non-linear relationships between temporal features and event timing. You'd train this in SageMaker with GPU instances, validate it against held-out data, and deploy it as a real-time endpoint.

**No causal inference.** This example predicts when events are likely to occur, but it doesn't estimate the causal effect of intervention at different time points. A production system would incorporate inverse probability weighting or G-computation to estimate "if we intervene on day X, how much does the event probability decrease?" That's a fundamentally harder problem requiring careful study design and statistical methodology.

**Error handling and retries.** Every external call (SageMaker endpoint, DynamoDB, S3) can fail. Production code wraps each call in try/except with specific handling for throttling (exponential backoff), service unavailability (circuit breaker), and malformed responses (graceful degradation). A failed scoring for one patient shouldn't crash the entire batch.

**Input validation.** This code trusts its inputs completely. Production validates that patient timelines have minimum data density (enough events to make meaningful predictions), that feature values are within expected ranges, and that the model endpoint is healthy before sending requests.

**Model monitoring and drift detection.** Survival models degrade over time as patient populations change, treatment patterns evolve, and intervention strategies shift. Production systems monitor the C-index on recent predictions, track calibration drift (are predicted probabilities matching observed event rates?), and alert when performance drops below acceptable thresholds.

**The feedback loop problem.** When your model successfully identifies patients at the right time and you intervene, those patients don't have events. Your next training cycle sees "model flagged, no event" and interprets it as a false positive. Production systems maintain a small randomized holdout (patients who are flagged but not intervened on) to preserve the training signal. This raises ethical questions that require IRB review and clinical leadership buy-in.

**IAM least-privilege.** The Lambda running this scoring logic needs exactly: `sagemaker:InvokeEndpoint` on the specific model endpoint, `dynamodb:PutItem` and `dynamodb:GetItem` on the specific table, and `s3:GetObject` on the specific timeline data prefix. Not `sagemaker:*`. Not `dynamodb:*`.

**VPC and encryption.** Patient timelines contain PHI. All data movement stays within a VPC using VPC endpoints for S3, DynamoDB, and SageMaker Runtime. KMS customer-managed keys encrypt data at rest in all stores. TLS encrypts everything in transit. VPC Flow Logs capture all network activity for audit.

**Structured logging without PHI.** Log the patient_id, scoring timestamp, intervention score, and recommended action. Never log the clinical features themselves (A1C values, medication names, diagnosis codes). Those are PHI. If you need to debug a specific patient's scoring, use a secure, audited query against the feature store, not log grep.

**Testing.** This example has no tests. Production needs: unit tests for feature engineering (given this timeline, do I get these features?), integration tests for the model endpoint (does it return valid trajectories?), calibration tests (are predicted hazards matching observed event rates in the validation cohort?), and end-to-end tests (does the full pipeline produce reasonable worklists for known patient scenarios?).

**Clinical validation.** Before deploying intervention timing recommendations to care teams, you need a prospective validation study: run the model in shadow mode (generate recommendations but don't show them), compare model-recommended timing against actual intervention timing, and measure whether model-timed interventions would have been more effective. This takes months and requires clinical research methodology, not just engineering.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 7.10](chapter07.10-optimal-intervention-timing-prediction) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
