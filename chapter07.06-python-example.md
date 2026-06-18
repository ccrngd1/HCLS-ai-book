# Recipe 7.6: Rising Risk Identification (Python Example)

> **Heads up:** This is a deliberately simplified, illustrative implementation of a rising risk identification pipeline. It generates synthetic longitudinal patient data, computes trajectory metrics (slopes, deltas, acceleration), applies multi-signal detection rules, and shows how you'd store results in DynamoDB and emit alerts via EventBridge. It is not production-ready. The synthetic data is cleaner than real EHR extracts, the risk model is a placeholder (real systems use trained ML models), and we skip the Glue-based distributed processing that a 500K-patient population requires. Think of it as a sketch that shows the shape of the solution. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and standard data science libraries:

```bash
pip install boto3 pandas numpy scikit-learn
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `s3:GetObject`, `s3:PutObject` on your score history and feature store buckets
- `dynamodb:PutItem`, `dynamodb:GetItem` on your patient risk state table
- `events:PutEvents` on your EventBridge bus for rising risk alerts
- `sns:Publish` on your care manager notification topic

For the SageMaker batch scoring path, you'd also need `sagemaker:CreateTransformJob` and a SageMaker execution role. This example computes risk scores locally with scikit-learn to keep the focus on trajectory detection logic.

---

## Config and Constants

These define the trajectory thresholds, scoring parameters, and detection rules. They live at the top because they're policy decisions disguised as code. Your clinical and operational leadership will have opinions about every one of these numbers.

```python
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ─── Trajectory Detection Thresholds ────────────────────────────────────────
# These thresholds determine who gets flagged as "rising risk."
# They're calibrated to intervention capacity: if your care management team
# can absorb 50 new patients per month, tune these so roughly 50 patients
# get flagged per cycle. Start conservative and loosen as you validate.

THRESHOLDS = {
    "slope_6mo_high": 0.05,        # risk score increasing by 0.05+ per month
    "slope_6mo_moderate": 0.02,    # moderate increase
    "delta_6mo_high": 0.20,        # absolute score jump of 0.20+ over 6 months
    "delta_6mo_moderate": 0.10,    # moderate absolute increase
    "relative_delta_high": 0.50,   # 50%+ relative increase over 6 months
    "acceleration_high": 0.02,     # slope itself is increasing
    "min_current_score": 0.15,     # don't flag very low absolute risk (noise)
    "max_current_score": 0.75,     # above this = already high-risk, not "rising"
    "min_data_points": 3,          # need at least 3 scores for trajectory
    "min_signals_to_flag": 2,      # require 2+ converging signals to reduce false positives
}

# ─── Scoring Cycle Configuration ────────────────────────────────────────────
# How often you score the population and how far back you look for trajectory.
SCORING_INTERVAL_DAYS = 30         # monthly scoring cycles
TRAJECTORY_LOOKBACK_MONTHS = 12    # how far back to look for trajectory computation
WINDOWS = [3, 6, 12]              # months: compute slopes over these windows

# ─── AWS Resource Names ─────────────────────────────────────────────────────
SCORE_HISTORY_BUCKET = "my-org-risk-scores"
SCORE_HISTORY_PREFIX = "score-history/"
RISK_STATE_TABLE = "patient-risk-state"
EVENT_BUS_NAME = "care-management-events"
ALERT_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:rising-risk-alerts"
```

---

## Step 1: Generate Synthetic Longitudinal Data

*The main recipe's Step 1 assembles features from EHR, claims, and ADT data. Here we generate synthetic patient histories with realistic trajectory patterns: some stable, some rising, some declining. This gives us something to run the detection logic against.*

```python
def generate_synthetic_score_history(
    n_patients: int = 1000,
    n_cycles: int = 12,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate synthetic longitudinal risk scores for a patient population.

    Creates patients with different trajectory patterns:
    - ~60% stable (minor fluctuations around a baseline)
    - ~20% rising (genuine upward trajectory)
    - ~10% declining (improving)
    - ~10% volatile (noisy, no clear trend)

    Each patient gets one score per monthly cycle, simulating what you'd get
    from running a risk model on a regular schedule.

    Returns a DataFrame with columns: patient_id, scoring_date, risk_score
    """
    rng = np.random.default_rng(seed)

    records = []
    # Generate scoring dates: one per month going back n_cycles months
    base_date = datetime(2026, 5, 1, tzinfo=timezone.utc)
    scoring_dates = [
        base_date - timedelta(days=30 * i) for i in range(n_cycles - 1, -1, -1)
    ]

    for i in range(n_patients):
        patient_id = f"PAT-{i:06d}"

        # Assign a trajectory pattern
        pattern_roll = rng.random()
        if pattern_roll < 0.60:
            pattern = "stable"
        elif pattern_roll < 0.80:
            pattern = "rising"
        elif pattern_roll < 0.90:
            pattern = "declining"
        else:
            pattern = "volatile"

        # Base risk score (starting point)
        base_score = rng.uniform(0.05, 0.60)

        for cycle_idx, scoring_date in enumerate(scoring_dates):
            if pattern == "stable":
                # Small random walk around baseline
                noise = rng.normal(0, 0.015)
                score = base_score + noise * (cycle_idx + 1) ** 0.3
            elif pattern == "rising":
                # Upward drift with noise
                drift = rng.uniform(0.01, 0.04) * cycle_idx
                noise = rng.normal(0, 0.02)
                score = base_score + drift + noise
            elif pattern == "declining":
                # Downward drift (patient improving)
                drift = rng.uniform(0.005, 0.02) * cycle_idx
                noise = rng.normal(0, 0.015)
                score = base_score - drift + noise
            else:
                # Volatile: large random swings
                noise = rng.normal(0, 0.08)
                score = base_score + noise

            # Clamp to valid range
            score = float(np.clip(score, 0.01, 0.99))
            records.append({
                "patient_id": patient_id,
                "scoring_date": scoring_date.strftime("%Y-%m-%d"),
                "risk_score": round(score, 4),
            })

    df = pd.DataFrame(records)
    logger.info(
        "Generated %d score records for %d patients across %d cycles",
        len(df), n_patients, n_cycles,
    )
    return df
```

---

## Step 2: Compute Trajectory Metrics

*The main recipe's Step 3 computes slopes, deltas, and acceleration for each patient. This is the core math of rising risk detection. We use linear regression over multiple time windows to capture both rapid spikes and slow drift.*

```python
from sklearn.linear_model import LinearRegression

def compute_slope(scores: list, months: list) -> float:
    """
    Fit a linear regression to score vs. time and return the slope.

    The slope represents the rate of change in risk score per month.
    A slope of 0.03 means the patient's risk score is increasing by
    0.03 per month, or roughly 0.18 over six months.

    We use linear regression rather than simple (last - first) / time
    because it's more robust to noise. A single anomalous score won't
    dominate the result when you have multiple data points.
    """
    if len(scores) < 2:
        return 0.0

    X = np.array(months).reshape(-1, 1)
    y = np.array(scores)
    model = LinearRegression().fit(X, y)
    return float(model.coef_[0])

def compute_trajectories(score_history: pd.DataFrame) -> pd.DataFrame:
    """
    For each patient, compute trajectory metrics from their score history.

    Metrics computed:
    - slope_3mo, slope_6mo, slope_12mo: rate of change over each window
    - delta_3mo, delta_6mo: absolute score change
    - relative_delta_6mo: proportional change (delta / baseline)
    - acceleration: change in slope (slope_3mo - slope_6mo)
    - current_score: most recent risk score
    - data_points: number of scoring cycles available

    Returns a DataFrame with one row per patient and all trajectory metrics.
    """
    # Parse dates and sort
    df = score_history.copy()
    df["scoring_date"] = pd.to_datetime(df["scoring_date"])
    df = df.sort_values(["patient_id", "scoring_date"])

    # Most recent scoring date in the dataset (our "now")
    max_date = df["scoring_date"].max()

    results = []

    for patient_id, group in df.groupby("patient_id"):
        group = group.sort_values("scoring_date").reset_index(drop=True)
        n_points = len(group)
        current_score = group.iloc[-1]["risk_score"]

        if n_points < THRESHOLDS["min_data_points"]:
            results.append({
                "patient_id": patient_id,
                "current_score": current_score,
                "data_points": n_points,
                "status": "INSUFFICIENT_HISTORY",
            })
            continue

        # Compute months relative to most recent score for regression
        group["months_from_start"] = (
            (group["scoring_date"] - group["scoring_date"].min()).dt.days / 30.0
        )

        # Compute slopes over multiple windows
        slopes = {}
        for window in WINDOWS:
            cutoff = max_date - timedelta(days=window * 30)
            window_data = group[group["scoring_date"] >= cutoff]
            if len(window_data) >= 2:
                months_vals = (
                    (window_data["scoring_date"] - window_data["scoring_date"].min()).dt.days / 30.0
                ).tolist()
                scores_vals = window_data["risk_score"].tolist()
                slopes[f"slope_{window}mo"] = compute_slope(scores_vals, months_vals)
            else:
                slopes[f"slope_{window}mo"] = 0.0

        # Compute absolute deltas by looking back N months
        deltas = {}
        for window in [3, 6]:
            cutoff = max_date - timedelta(days=window * 30)
            past_scores = group[group["scoring_date"] <= cutoff]
            if not past_scores.empty:
                past_score = past_scores.iloc[-1]["risk_score"]
                deltas[f"delta_{window}mo"] = current_score - past_score
            else:
                deltas[f"delta_{window}mo"] = 0.0

        # Relative delta: how much did the score change proportionally?
        score_6mo_ago = current_score - deltas.get("delta_6mo", 0.0)
        relative_delta_6mo = (
            deltas["delta_6mo"] / score_6mo_ago if score_6mo_ago > 0.05 else 0.0
        )

        # Acceleration: is the rate of change itself increasing?
        # If 3-month slope > 6-month slope, deterioration is speeding up.
        acceleration = slopes.get("slope_3mo", 0.0) - slopes.get("slope_6mo", 0.0)

        # Percentile within current population (computed later at population level)
        results.append({
            "patient_id": patient_id,
            "current_score": current_score,
            "data_points": n_points,
            "status": "COMPUTED",
            **slopes,
            **deltas,
            "relative_delta_6mo": round(relative_delta_6mo, 4),
            "acceleration": round(acceleration, 4),
        })

    result_df = pd.DataFrame(results)

    # Add percentile ranking within the scored population
    computed_mask = result_df["status"] == "COMPUTED"
    result_df.loc[computed_mask, "percentile"] = (
        result_df.loc[computed_mask, "current_score"]
        .rank(pct=True)
        .multiply(100)
        .round(1)
    )

    logger.info(
        "Computed trajectories: %d patients, %d with sufficient history",
        len(result_df),
        computed_mask.sum(),
    )
    return result_df
```

---

## Step 3: Detect Rising Risk Patients

*The main recipe's Step 4 applies detection rules that require multiple converging signals. A single elevated metric might be noise. Two or more converging indicators suggest genuine deterioration.*

```python
def detect_rising_risk(trajectories: pd.DataFrame) -> pd.DataFrame:
    """
    Apply multi-signal detection rules to identify patients with rising risk.

    The logic:
    1. Filter to patients in the "actionable zone" (not too low, not already high-risk)
    2. Check each trajectory metric against thresholds
    3. Require at least 2 converging signals to flag (reduces false positives)
    4. Assign severity tier based on signal strength
    5. Sort by severity and slope for prioritization

    Returns a DataFrame of flagged patients with their signals and severity.
    """
    flagged = []

    # Only evaluate patients with computed trajectories
    computed = trajectories[trajectories["status"] == "COMPUTED"].copy()

    for _, patient in computed.iterrows():
        # Guard: only flag patients in the "rising" zone
        if patient["current_score"] < THRESHOLDS["min_current_score"]:
            continue
        if patient["current_score"] > THRESHOLDS["max_current_score"]:
            continue

        # Collect triggered signals
        signals = []

        if patient["slope_6mo"] >= THRESHOLDS["slope_6mo_high"]:
            signals.append("HIGH_SLOPE_6MO")
        elif patient["slope_6mo"] >= THRESHOLDS["slope_6mo_moderate"]:
            signals.append("MODERATE_SLOPE_6MO")

        if patient["delta_6mo"] >= THRESHOLDS["delta_6mo_high"]:
            signals.append("HIGH_DELTA_6MO")
        elif patient["delta_6mo"] >= THRESHOLDS["delta_6mo_moderate"]:
            signals.append("MODERATE_DELTA_6MO")

        if patient["relative_delta_6mo"] >= THRESHOLDS["relative_delta_high"]:
            signals.append("HIGH_RELATIVE_CHANGE")

        if patient["acceleration"] >= THRESHOLDS["acceleration_high"]:
            signals.append("ACCELERATING")

        # Require multiple converging signals
        if len(signals) >= THRESHOLDS["min_signals_to_flag"]:
            severity = "HIGH" if any("HIGH" in s for s in signals) else "MODERATE"

            flagged.append({
                "patient_id": patient["patient_id"],
                "current_score": patient["current_score"],
                "percentile": patient.get("percentile", 0),
                "severity": severity,
                "signals": signals,
                "slope_6mo": round(patient["slope_6mo"], 4),
                "delta_6mo": round(patient["delta_6mo"], 4),
                "acceleration": round(patient["acceleration"], 4),
                "data_points": patient["data_points"],
                "flagged_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })

    flagged_df = pd.DataFrame(flagged)

    if not flagged_df.empty:
        # Sort: HIGH severity first, then steepest slope
        severity_order = {"HIGH": 0, "MODERATE": 1}
        flagged_df["_sort"] = flagged_df["severity"].map(severity_order)
        flagged_df = flagged_df.sort_values(
            ["_sort", "slope_6mo"], ascending=[True, False]
        ).drop(columns=["_sort"])

    logger.info(
        "Rising risk detection: %d patients flagged out of %d evaluated "
        "(HIGH: %d, MODERATE: %d)",
        len(flagged_df),
        len(computed),
        (flagged_df["severity"] == "HIGH").sum() if not flagged_df.empty else 0,
        (flagged_df["severity"] == "MODERATE").sum() if not flagged_df.empty else 0,
    )
    return flagged_df
```

---

## Step 4: Store Results in DynamoDB

*The main recipe's Step 5 writes risk state to DynamoDB for real-time care management lookups. Each patient gets a record with their current tier, trajectory summary, and the signals that triggered the flag.*

```python
import boto3
from botocore.config import Config

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

def store_risk_state(flagged_patients: pd.DataFrame) -> int:
    """
    Write rising risk flags to DynamoDB for real-time care management access.

    Each flagged patient gets a record that the care management platform
    can query by patient_id. The record includes the trajectory summary
    so care managers have context without needing to look it up separately.

    DynamoDB gotcha: floats must be stored as Decimal. boto3's resource layer
    will raise TypeError on raw Python floats. We convert explicitly here.
    """
    table = dynamodb.Table(RISK_STATE_TABLE)
    written = 0

    for _, patient in flagged_patients.iterrows():
        item = {
            "patient_id": patient["patient_id"],
            "risk_tier": "RISING",
            "severity": patient["severity"],
            "current_score": Decimal(str(round(patient["current_score"], 4))),
            "trajectory_slope": Decimal(str(round(patient["slope_6mo"], 4))),
            "delta_6mo": Decimal(str(round(patient["delta_6mo"], 4))),
            "acceleration": Decimal(str(round(patient["acceleration"], 4))),
            "percentile": Decimal(str(round(patient["percentile"], 1))),
            "signals": patient["signals"],
            "flagged_date": patient["flagged_date"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        table.put_item(Item=item)
        written += 1

    logger.info("Wrote %d rising risk records to DynamoDB", written)
    return written
```

---

## Step 5: Emit Alerts for Newly Flagged Patients

*Only send notifications for patients who are newly flagged this cycle. Patients who were already flagged last cycle don't need another alert (that's how you get alert fatigue). The event includes enough context for the care manager to act without opening another system.*

```python
eventbridge = boto3.client("events", config=BOTO3_RETRY_CONFIG)

def emit_rising_risk_alerts(
    flagged_patients: pd.DataFrame,
    previously_flagged_ids: set,
) -> int:
    """
    Emit EventBridge events for newly flagged patients.

    Only patients who were NOT flagged in the previous cycle get an alert.
    This prevents care managers from getting the same notification every month
    for patients already in their workflow.

    EventBridge events can trigger multiple downstream consumers:
    - SNS notification to the care management team
    - Lambda to update the care management platform
    - Step Functions workflow for automated outreach
    """
    newly_flagged = flagged_patients[
        ~flagged_patients["patient_id"].isin(previously_flagged_ids)
    ]

    if newly_flagged.empty:
        logger.info("No newly flagged patients this cycle")
        return 0

    # EventBridge accepts up to 10 entries per PutEvents call
    entries = []
    for _, patient in newly_flagged.iterrows():
        detail = {
            "patient_id": patient["patient_id"],
            "severity": patient["severity"],
            "current_score": patient["current_score"],
            "percentile": patient["percentile"],
            "slope_6mo": patient["slope_6mo"],
            "delta_6mo": patient["delta_6mo"],
            "signals": patient["signals"],
            "message": (
                f"Patient risk score increased by {patient['delta_6mo']:.2f} "
                f"over 6 months. Current score: {patient['current_score']:.2f} "
                f"(percentile: {patient['percentile']:.0f}). "
                f"Signals: {', '.join(patient['signals'])}."
            ),
        }

        entries.append({
            "Source": "rising-risk-pipeline",
            "DetailType": "RisingRiskIdentified",
            "Detail": json.dumps(detail, default=str),
            "EventBusName": EVENT_BUS_NAME,
        })

    # Send in batches of 10 (EventBridge limit)
    sent = 0
    for i in range(0, len(entries), 10):
        batch = entries[i : i + 10]
        response = eventbridge.put_events(Entries=batch)
        sent += len(batch) - response.get("FailedEntryCount", 0)

    logger.info(
        "Emitted %d rising risk alerts (%d newly flagged)",
        sent, len(newly_flagged),
    )
    return sent
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. In production, this would be triggered by EventBridge Scheduler on a monthly cadence, with the feature assembly and scoring handled by Glue and SageMaker respectively.

```python
def run_rising_risk_pipeline(
    n_patients: int = 1000,
    previously_flagged_ids: set = None,
) -> dict:
    """
    Run the full rising risk identification pipeline.

    In production:
    - Step 1 would pull real features from your EHR/claims data via Glue
    - Scoring would use a trained SageMaker model via batch transform
    - Score history would be read from S3 (partitioned Parquet)
    - Results would be written to DynamoDB and events emitted to EventBridge

    Here we use synthetic data and local computation to demonstrate the
    detection logic without requiring AWS infrastructure.
    """
    if previously_flagged_ids is None:
        previously_flagged_ids = set()

    print("=" * 70)
    print("RISING RISK IDENTIFICATION PIPELINE")
    print("=" * 70)

    # Step 1: Generate synthetic score history
    # (In production: query S3 score history + run SageMaker batch scoring)
    print("\n[Step 1] Generating synthetic longitudinal score history...")
    score_history = generate_synthetic_score_history(
        n_patients=n_patients, n_cycles=12
    )
    print(f"  Generated {len(score_history)} score records")
    print(f"  Patients: {score_history['patient_id'].nunique()}")
    print(f"  Date range: {score_history['scoring_date'].min()} to "
          f"{score_history['scoring_date'].max()}")

    # Step 2: Compute trajectory metrics for each patient
    print("\n[Step 2] Computing trajectory metrics...")
    trajectories = compute_trajectories(score_history)
    computed = trajectories[trajectories["status"] == "COMPUTED"]
    insufficient = trajectories[trajectories["status"] == "INSUFFICIENT_HISTORY"]
    print(f"  Trajectories computed: {len(computed)}")
    print(f"  Insufficient history: {len(insufficient)}")
    print(f"  Mean slope_6mo: {computed['slope_6mo'].mean():.4f}")
    print(f"  Max slope_6mo: {computed['slope_6mo'].max():.4f}")

    # Step 3: Apply rising risk detection rules
    print("\n[Step 3] Detecting rising risk patients...")
    flagged = detect_rising_risk(trajectories)
    print(f"  Total flagged: {len(flagged)}")
    if not flagged.empty:
        print(f"  HIGH severity: {(flagged['severity'] == 'HIGH').sum()}")
        print(f"  MODERATE severity: {(flagged['severity'] == 'MODERATE').sum()}")
        print(f"  Flag rate: {len(flagged) / len(computed) * 100:.1f}% of population")

    # Step 4: Store results (would write to DynamoDB in production)
    print("\n[Step 4] Storing risk state...")
    print(f"  Would write {len(flagged)} records to DynamoDB table '{RISK_STATE_TABLE}'")
    # Uncomment to actually write:
    # store_risk_state(flagged)

    # Step 5: Emit alerts for newly flagged patients
    newly_flagged = flagged[~flagged["patient_id"].isin(previously_flagged_ids)]
    print("\n[Step 5] Emitting alerts...")
    print(f"  Previously flagged: {len(previously_flagged_ids)}")
    print(f"  Newly flagged this cycle: {len(newly_flagged)}")
    print(f"  Would emit {len(newly_flagged)} EventBridge events")
    # Uncomment to actually emit:
    # emit_rising_risk_alerts(flagged, previously_flagged_ids)

    # Summary
    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)

    summary = {
        "scoring_cycle": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "population_scored": n_patients,
        "trajectories_computed": len(computed),
        "insufficient_history": len(insufficient),
        "rising_risk_flagged": len(flagged),
        "newly_flagged": len(newly_flagged),
        "severity_distribution": {
            "HIGH": int((flagged["severity"] == "HIGH").sum()) if not flagged.empty else 0,
            "MODERATE": int((flagged["severity"] == "MODERATE").sum()) if not flagged.empty else 0,
        },
    }

    # Show a sample flagged patient for illustration
    if not flagged.empty:
        sample = flagged.iloc[0]
        summary["sample_flagged_patient"] = {
            "patient_id": sample["patient_id"],
            "current_score": sample["current_score"],
            "percentile": sample["percentile"],
            "severity": sample["severity"],
            "signals": sample["signals"],
            "slope_6mo": sample["slope_6mo"],
            "delta_6mo": sample["delta_6mo"],
            "acceleration": sample["acceleration"],
        }
        print(f"\nSample flagged patient:")
        print(json.dumps(summary["sample_flagged_patient"], indent=2, default=str))

    return summary

# Run the pipeline
if __name__ == "__main__":
    result = run_rising_risk_pipeline(n_patients=1000)
    print("\nFull summary:")
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example works. Run it and you'll get a ranked list of rising-risk patients with trajectory metrics and severity tiers. But there's a meaningful distance between "works in a script" and "runs monthly on a 500K-member population with real clinical data." Here's where that gap lives:

**Distributed processing.** This example processes patients in a pandas DataFrame on a single machine. A 500K-patient population with 12+ months of score history won't fit comfortably in memory, and the trajectory computation takes too long serially. Production uses AWS Glue (Spark-based) to parallelize the trajectory computation across the population. Each patient's trajectory is independent, making this embarrassingly parallel.

**Real risk model.** We generate synthetic scores here. A real system runs a trained ML model (typically gradient boosted trees or a neural network) via SageMaker batch transform to produce the underlying risk scores. The model is trained on historical claims, clinical data, and utilization patterns. Model versioning matters enormously: if you retrain the model, historical scores from the old version aren't directly comparable to new scores. You either re-score history with the new model or maintain version-specific baselines.

**Score history management.** This example generates history in memory. Production stores scores in S3 as partitioned Parquet files (partitioned by scoring date). Each monthly cycle appends a new partition. Queries like "get all scores for patient X over 24 months" use Athena or Glue to scan across partitions efficiently. Retention policy: keep at least 24 months for trajectory analysis, archive older data to Glacier.

**Irregular observation handling.** Real patients don't have scores at perfectly regular intervals. A patient who was uninsured for 6 months has a gap in their score history. The slope computation needs to handle irregular time spacing (which our linear regression approach does naturally), but you also need logic to detect and flag stale data. A patient with no new score in 6+ months should trigger a "data staleness" alert separate from the trajectory analysis.

**Error handling and retries.** The DynamoDB writes and EventBridge calls here have no error handling. Production wraps every external call in try/except with specific handling for throttling (exponential backoff), conditional check failures (concurrent updates), and service unavailability (dead-letter queue for retry).

**Threshold calibration feedback loop.** The thresholds in this example are static. Production systems need a feedback mechanism where care managers mark flags as "appropriate" or "not actionable." That signal feeds back into threshold tuning. Without it, you're guessing at the right sensitivity/specificity tradeoff.

**Regression to the mean correction.** Patients flagged as "rising" will, on average, partially revert even without intervention. This is a statistical phenomenon, not a clinical one. Production systems need either a control group (ethically complex) or statistical adjustment (propensity score matching) to measure true intervention effectiveness. Without this, you'll overestimate your program's impact.

**IAM least-privilege.** The IAM role for this pipeline should have exactly: `s3:GetObject` and `s3:PutObject` scoped to specific buckets and prefixes, `dynamodb:PutItem` and `dynamodb:GetItem` scoped to the specific table, `events:PutEvents` scoped to the specific event bus, and `sagemaker:CreateTransformJob` scoped to specific model resources. Not `s3:*`. Not `AdministratorAccess`.

**VPC and encryption.** Production: Glue jobs and Lambda functions run in a VPC with private subnets. VPC endpoints for S3, DynamoDB, EventBridge, and SageMaker keep all traffic on the AWS backbone. KMS customer-managed keys encrypt all data at rest (S3 buckets, DynamoDB table). CloudTrail logs every API call for HIPAA audit compliance.

**DynamoDB Decimal requirement.** This example already converts floats to Decimal for DynamoDB writes (see Step 4). If you add new numeric fields, they must also use Decimal. boto3's DynamoDB resource layer raises TypeError on raw Python floats. This is a known gotcha that catches everyone at least once.

**Testing.** There are no tests here. A production pipeline has: unit tests for `compute_trajectories` with known input/output pairs, integration tests against a fixed synthetic dataset to verify flag counts are stable across code changes, and regression tests that compare current cycle's flag rate to historical norms (a sudden 10x increase in flags usually means a bug, not a pandemic).

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 7.6](chapter07.06-rising-risk-identification.md) for the full architectural walkthrough, pseudocode, and honest take on where trajectory detection gets hard.*
