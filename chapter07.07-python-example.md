# Recipe 7.7: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 7.7. It shows one way you could translate those concepts into working Python code using SageMaker, Feature Store, and DynamoDB. It is not production-ready. The synthetic data is tiny, the feature engineering is minimal, and the model is trained on fake patients. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a hospital bed management system on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few ML libraries:

```bash
pip install boto3 sagemaker pandas numpy scikit-learn xgboost
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `sagemaker:CreateTrainingJob`, `sagemaker:CreateModel`, `sagemaker:CreateEndpoint`, `sagemaker:InvokeEndpoint`
- `sagemaker:CreateFeatureGroup`, `sagemaker:PutRecord`, `sagemaker:GetRecord`
- `s3:GetObject`, `s3:PutObject` (scoped to your training data bucket)
- `dynamodb:PutItem`, `dynamodb:Query`
- `iam:PassRole` (to pass the SageMaker execution role)

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the pipeline. These constants define feature schemas, model hyperparameters, and operational thresholds. They live at the top of your module so they're easy to find and tune.

```python
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
import numpy as np
import pandas as pd
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI (patient names,
# MRNs, diagnosis text).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS API calls. Adaptive mode uses exponential backoff
# with jitter, which handles burst throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Feature Schema ---
# These are the features the model expects, in order. The training pipeline
# and inference pipeline must produce features in this exact schema, or you
# get training-serving skew (the #1 silent killer of ML model accuracy).

ADMISSION_FEATURES = [
    "age", "sex_encoded", "admission_source_encoded", "admission_type_encoded",
    "drg_geometric_mean_los", "charlson_score", "elixhauser_count",
    "prior_admits_12mo", "prior_ed_visits_12mo", "insurance_category_encoded",
    "day_of_week_admit", "hour_of_admit"
]

DAILY_FEATURES = [
    "current_day_of_stay", "wbc_latest", "creatinine_latest", "albumin_latest",
    "temp_max_24h", "hr_variability_24h", "o2_requirement",
    "iv_antibiotics_active", "vasopressors_active", "procedures_pending",
    "abnormal_lab_count"
]

ALL_FEATURES = ADMISSION_FEATURES + DAILY_FEATURES

# --- Model Hyperparameters ---
# These are reasonable defaults for hospital LOS prediction with XGBoost.
# Tune them on your actual data. The key tradeoffs:
# - max_depth: deeper trees capture more interactions but overfit faster
# - learning_rate: lower = more trees needed but better generalization
# - min_child_weight: higher = more conservative splits, less overfitting to rare cases
MODEL_PARAMS = {
    "max_depth": 6,
    "learning_rate": 0.05,
    "n_estimators": 500,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 10,
    "objective": "reg:squarederror",
    "eval_metric": "mae",
    "early_stopping_rounds": 20,
    "random_state": 42,
}

# --- Operational Thresholds ---
# When a patient's predicted total LOS exceeds their DRG geometric mean by
# this many days, fire an early warning alert to discharge planning.
EXTENDED_STAY_ALERT_THRESHOLD_DAYS = 1.5

# Model performance threshold. If daily MAE exceeds this, trigger a
# retraining alert. 2.5 days is generous; tighten as your model matures.
PERFORMANCE_ALERT_THRESHOLD_MAE = 2.5

# DynamoDB table for storing predictions
PREDICTIONS_TABLE = "los-predictions"

# S3 bucket for training data and model artifacts
TRAINING_BUCKET = "my-hospital-ml-data"
```

---

## Step 1: Generate Synthetic Training Data

*The pseudocode calls this `prepare_training_data`. In a real system, you'd extract this from your EHR data warehouse. Here we generate realistic synthetic encounters so you can run the full pipeline without access to patient data. Never use real PHI in development.*

```python
def generate_synthetic_encounters(n_encounters: int = 2000, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic hospital encounters with realistic LOS distributions.

    Real hospital LOS data is right-skewed: most stays are 2-5 days, with a
    long tail extending to 30+ days. We simulate this using a log-normal
    distribution, which matches the empirical shape well.

    The features are correlated with LOS in ways that mirror clinical reality:
    - Older patients stay longer (more comorbidities, slower recovery)
    - Higher Charlson scores correlate with longer stays
    - ED admissions tend to be sicker than direct admits
    - Emergent admissions have wider LOS variance than elective

    Args:
        n_encounters: Number of synthetic encounters to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with one row per encounter, including features and actual_los.
    """
    rng = np.random.default_rng(seed)

    # Demographics
    ages = rng.integers(18, 95, size=n_encounters)
    sex = rng.choice([0, 1], size=n_encounters)  # 0=female, 1=male

    # Admission characteristics
    # ED admits are ~60% of hospital admissions nationally
    admission_source = rng.choice([0, 1, 2], size=n_encounters, p=[0.6, 0.3, 0.1])
    # 0=ED, 1=direct, 2=transfer

    admission_type = rng.choice([0, 1, 2], size=n_encounters, p=[0.5, 0.35, 0.15])
    # 0=emergent, 1=elective, 2=urgent

    # Comorbidity burden (Charlson index: 0-15 range, most patients 0-5)
    charlson = rng.poisson(lam=2, size=n_encounters).clip(0, 15)
    elixhauser = rng.poisson(lam=3, size=n_encounters).clip(0, 12)

    # Prior utilization
    prior_admits = rng.poisson(lam=0.5, size=n_encounters)
    prior_ed = rng.poisson(lam=1.2, size=n_encounters)

    # Insurance (0=commercial, 1=Medicare, 2=Medicaid, 3=self-pay)
    insurance = rng.choice([0, 1, 2, 3], size=n_encounters, p=[0.35, 0.40, 0.20, 0.05])

    # DRG geometric mean LOS (national average for the assigned DRG)
    # This is the single strongest predictor of actual LOS.
    drg_mean_los = rng.uniform(2.0, 8.0, size=n_encounters)

    # Timing
    day_of_week = rng.integers(0, 7, size=n_encounters)
    hour_of_admit = rng.integers(0, 24, size=n_encounters)

    # --- Generate actual LOS ---
    # Base LOS is driven by DRG mean, modified by patient factors.
    # This is a simplified version of reality, but captures the key relationships.
    base_log_los = (
        np.log(drg_mean_los)
        + 0.01 * (ages - 50)           # older = longer
        + 0.05 * charlson               # sicker = longer
        + 0.1 * (admission_source == 0).astype(float)  # ED admits slightly longer
        + 0.15 * (admission_type == 0).astype(float)   # emergent = longer
        + rng.normal(0, 0.3, size=n_encounters)        # noise
    )

    # Exponentiate to get actual LOS (log-normal distribution)
    actual_los = np.exp(base_log_los).clip(1, 60).round(0).astype(int)

    # Build the DataFrame
    encounters = pd.DataFrame({
        "encounter_id": [f"ENC-{i:06d}" for i in range(n_encounters)],
        "age": ages,
        "sex_encoded": sex,
        "admission_source_encoded": admission_source,
        "admission_type_encoded": admission_type,
        "drg_geometric_mean_los": drg_mean_los.round(1),
        "charlson_score": charlson,
        "elixhauser_count": elixhauser,
        "prior_admits_12mo": prior_admits,
        "prior_ed_visits_12mo": prior_ed,
        "insurance_category_encoded": insurance,
        "day_of_week_admit": day_of_week,
        "hour_of_admit": hour_of_admit,
        "actual_los": actual_los,
    })

    return encounters
```

---

## Step 2: Generate Daily Features for Training

*The pseudocode calls this `extract_daily_features`. For training, we need to create examples at multiple time points during each stay. A patient who stayed 7 days generates examples at day 0 (target: 7), day 1 (target: 6), day 2 (target: 5), etc. This teaches the model to predict remaining LOS from any point during the stay.*

```python
def generate_daily_features_for_training(encounters: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """
    Expand each encounter into multiple training examples (one per day of stay).

    This is the key insight for LOS prediction: you don't just train on
    admission-time features. You train on features at every point during the
    stay, with the target being REMAINING days (not total days). This lets
    the model update predictions as clinical data accumulates.

    The daily features simulate lab values, vital signs, and treatment
    intensity that evolve during the stay. In a real system, these come
    from your EHR data warehouse.

    Args:
        encounters: DataFrame from generate_synthetic_encounters.
        seed: Random seed.

    Returns:
        DataFrame with one row per (encounter, day) pair, including all
        features and the target variable (remaining_los).
    """
    rng = np.random.default_rng(seed)
    rows = []

    for _, enc in encounters.iterrows():
        actual_los = enc["actual_los"]

        # Generate an example for each day of the stay (day 0 through day actual_los-1)
        for day in range(actual_los):
            # Remaining LOS is the target: how many more days from this point?
            remaining = actual_los - day

            # Simulate daily clinical features that evolve during the stay.
            # In reality, these come from lab results, vital signs, and orders.

            # WBC (white blood cell count): elevated early in infection, normalizes
            wbc = max(4.0, 12.0 - day * 0.5 + rng.normal(0, 2))

            # Creatinine: kidney function marker, may be elevated in sick patients
            creatinine = max(0.5, 1.2 + 0.1 * enc["charlson_score"] - day * 0.05 + rng.normal(0, 0.3))

            # Albumin: nutritional status, drops during acute illness
            albumin = max(1.5, 3.5 - 0.1 * day + rng.normal(0, 0.3))

            # Temperature: fever early, resolves over stay
            temp_max = max(36.5, 38.5 - day * 0.3 + rng.normal(0, 0.5))

            # Heart rate variability: higher when unstable
            hr_var = max(5, 20 - day * 1.5 + rng.normal(0, 5))

            # O2 requirement: liters per minute, decreases as patient improves
            o2 = max(0, 3 - day * 0.5 + rng.normal(0, 1))

            # Treatment intensity flags (binary)
            iv_abx = 1 if (day < actual_los * 0.6 and rng.random() > 0.3) else 0
            vasopressors = 1 if (day < 2 and enc["charlson_score"] > 4 and rng.random() > 0.5) else 0

            # Pending procedures: more early in stay
            procedures_pending = max(0, int(3 - day + rng.integers(-1, 2)))

            # Abnormal lab count: decreases as patient improves
            abnormal_labs = max(0, int(4 - day * 0.5 + rng.integers(-1, 2)))

            row = {
                # Admission features (static, same for all days of this encounter)
                "encounter_id": enc["encounter_id"],
                "age": enc["age"],
                "sex_encoded": enc["sex_encoded"],
                "admission_source_encoded": enc["admission_source_encoded"],
                "admission_type_encoded": enc["admission_type_encoded"],
                "drg_geometric_mean_los": enc["drg_geometric_mean_los"],
                "charlson_score": enc["charlson_score"],
                "elixhauser_count": enc["elixhauser_count"],
                "prior_admits_12mo": enc["prior_admits_12mo"],
                "prior_ed_visits_12mo": enc["prior_ed_visits_12mo"],
                "insurance_category_encoded": enc["insurance_category_encoded"],
                "day_of_week_admit": enc["day_of_week_admit"],
                "hour_of_admit": enc["hour_of_admit"],
                # Daily features (change each day)
                "current_day_of_stay": day,
                "wbc_latest": round(wbc, 1),
                "creatinine_latest": round(creatinine, 2),
                "albumin_latest": round(albumin, 1),
                "temp_max_24h": round(temp_max, 1),
                "hr_variability_24h": round(hr_var, 1),
                "o2_requirement": round(o2, 1),
                "iv_antibiotics_active": iv_abx,
                "vasopressors_active": vasopressors,
                "procedures_pending": procedures_pending,
                "abnormal_lab_count": abnormal_labs,
                # Target
                "remaining_los": remaining,
            }
            rows.append(row)

    return pd.DataFrame(rows)
```

---

## Step 3: Train the XGBoost Model

*The pseudocode calls this `train_los_model`. We train a gradient boosted tree to predict remaining LOS from the combined admission + daily features. In production, you'd train separate models per service line. Here we train one model on the full synthetic population to keep things simple.*

```python
from xgboost import XGBRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score


def train_los_model(training_df: pd.DataFrame) -> tuple:
    """
    Train an XGBoost regressor to predict remaining length of stay.

    Uses a temporal-style split (last 20% of data for test) to simulate
    how the model would perform on future patients. In production, you'd
    do a proper time-based split: train on months 1-10, validate on month 11,
    test on month 12.

    Args:
        training_df: Output of generate_daily_features_for_training.

    Returns:
        Tuple of (trained model, test metrics dict, test DataFrame with predictions).
    """
    # Separate features from target and metadata
    feature_cols = ALL_FEATURES
    target_col = "remaining_los"

    X = training_df[feature_cols].copy()
    y = training_df[target_col].copy()

    # Split: 80% train, 20% test.
    # In production, use a time-based split to prevent data leakage.
    # Random split is acceptable for this synthetic demonstration.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    logger.info("Training set: %d examples, Test set: %d examples", len(X_train), len(X_test))

    # Train XGBoost regressor
    model = XGBRegressor(
        max_depth=MODEL_PARAMS["max_depth"],
        learning_rate=MODEL_PARAMS["learning_rate"],
        n_estimators=MODEL_PARAMS["n_estimators"],
        subsample=MODEL_PARAMS["subsample"],
        colsample_bytree=MODEL_PARAMS["colsample_bytree"],
        min_child_weight=MODEL_PARAMS["min_child_weight"],
        objective=MODEL_PARAMS["objective"],
        random_state=MODEL_PARAMS["random_state"],
        eval_metric="mae",
        early_stopping_rounds=MODEL_PARAMS["early_stopping_rounds"],
    )

    # Fit with early stopping on a validation subset
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # Evaluate on test set
    predictions = model.predict(X_test)

    # Predictions should never be negative (can't have negative remaining days)
    predictions = np.maximum(predictions, 0)

    mae = mean_absolute_error(y_test, predictions)
    r2 = r2_score(y_test, predictions)

    # "Within N days" accuracy: what percentage of predictions are within
    # 1 or 2 days of the actual remaining LOS? This is often more meaningful
    # to operations teams than MAE.
    within_1 = np.mean(np.abs(y_test.values - predictions) <= 1) * 100
    within_2 = np.mean(np.abs(y_test.values - predictions) <= 2) * 100

    metrics = {
        "mae": round(mae, 2),
        "r_squared": round(r2, 3),
        "within_1_day_pct": round(within_1, 1),
        "within_2_days_pct": round(within_2, 1),
        "n_train": len(X_train),
        "n_test": len(X_test),
    }

    logger.info("Model metrics: MAE=%.2f days, R²=%.3f, Within 1 day=%.1f%%",
                mae, r2, within_1)

    # Feature importance: which features drive predictions?
    # This is critical for clinician trust. If the model says "DRG mean LOS"
    # is the top feature, that makes clinical sense. If it says "hour of admit"
    # is the top feature, something is wrong.
    importances = dict(zip(feature_cols, model.feature_importances_))
    top_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]
    logger.info("Top 5 features: %s", [(f, round(v, 3)) for f, v in top_features])

    return model, metrics, top_features
```

---

## Step 4: Run Inference for a Current Inpatient

*The pseudocode calls this `predict_remaining_los`. Given a patient's current features, produce a prediction with a confidence interval. In production, features come from the SageMaker Feature Store. Here we simulate the feature retrieval and show the inference pattern.*

```python
def predict_remaining_los(model, patient_features: dict) -> dict:
    """
    Generate a LOS prediction for a single current inpatient.

    In production, this function would:
    1. Pull features from SageMaker Feature Store (online store)
    2. Invoke a SageMaker endpoint
    3. Write the result to DynamoDB

    Here we call the local model directly to demonstrate the logic.

    Args:
        model: Trained XGBRegressor.
        patient_features: Dict with keys matching ALL_FEATURES.

    Returns:
        Prediction dict with point estimate, confidence bounds, and metadata.
    """
    # Build feature vector in the correct order
    feature_vector = pd.DataFrame([patient_features])[ALL_FEATURES]

    # Point prediction
    predicted_remaining = float(model.predict(feature_vector)[0])
    predicted_remaining = max(0, predicted_remaining)  # can't be negative

    # Confidence interval estimation.
    # XGBoost doesn't natively produce prediction intervals. In production,
    # you'd use one of these approaches:
    # 1. Train quantile regression models (objective="reg:quantileerror")
    # 2. Use conformal prediction for distribution-free intervals
    # 3. Bootstrap: train multiple models on resampled data, use spread
    #
    # Here we use a simple heuristic: +/- 1.5 days for short predicted stays,
    # wider for longer predicted stays. This is a placeholder. Do not ship this.
    uncertainty = max(1.0, predicted_remaining * 0.4)
    lower_bound = max(0, predicted_remaining - uncertainty)
    upper_bound = predicted_remaining + uncertainty

    # Calculate predicted discharge date
    current_day = patient_features["current_day_of_stay"]
    drg_expected = patient_features["drg_geometric_mean_los"]
    total_predicted_los = current_day + predicted_remaining

    result = {
        "predicted_remaining_days": round(predicted_remaining, 1),
        "confidence_lower": round(lower_bound, 1),
        "confidence_upper": round(upper_bound, 1),
        "current_day_of_stay": current_day,
        "total_predicted_los": round(total_predicted_los, 1),
        "drg_expected_los": drg_expected,
        "exceeds_expected": total_predicted_los > drg_expected,
        "prediction_timestamp": datetime.datetime.now(timezone.utc).isoformat(),
    }

    return result
```

---

## Step 5: Store Prediction in DynamoDB

*The pseudocode calls this `write_to_prediction_store`. The prediction store is what operational dashboards query. It needs to support queries by unit, by predicted discharge date, and by individual encounter.*

```python
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)


def store_prediction(encounter_id: str, unit: str, bed: str, prediction: dict) -> dict:
    """
    Write a LOS prediction to DynamoDB for operational consumption.

    The table design supports two access patterns:
    1. Get prediction for a specific encounter (partition key = encounter_id)
    2. Query all predictions for a unit (GSI on unit + predicted_discharge_date)

    DynamoDB requires Decimal for numeric values, not float. Every numeric
    field must be wrapped in Decimal() or put_item raises a TypeError.
    We convert via str() first to avoid floating-point representation artifacts
    (e.g., Decimal(0.1) becomes 0.1000000000000000055511151231257827021181583404541015625).

    Args:
        encounter_id: Unique encounter identifier.
        unit: Hospital unit (e.g., "4-North Medical").
        bed: Bed assignment (e.g., "4N-12").
        prediction: Output of predict_remaining_los.

    Returns:
        The full record written to DynamoDB.
    """
    table = dynamodb.Table(PREDICTIONS_TABLE)

    record = {
        "encounter_id": encounter_id,
        "unit": unit,
        "bed": bed,
        "predicted_remaining_days": Decimal(str(prediction["predicted_remaining_days"])),
        "confidence_lower": Decimal(str(prediction["confidence_lower"])),
        "confidence_upper": Decimal(str(prediction["confidence_upper"])),
        "current_day_of_stay": prediction["current_day_of_stay"],
        "total_predicted_los": Decimal(str(prediction["total_predicted_los"])),
        "drg_expected_los": Decimal(str(prediction["drg_expected_los"])),
        "exceeds_expected": prediction["exceeds_expected"],
        "prediction_timestamp": prediction["prediction_timestamp"],
    }

    table.put_item(Item=record)
    logger.info("Stored prediction for %s: %.1f days remaining",
                encounter_id, prediction["predicted_remaining_days"])

    return record
```

---

## Step 6: Daily Monitoring (Compare Predictions to Outcomes)

*The pseudocode calls this `daily_batch_refresh` (the monitoring portion). When patients are discharged, you can compare yesterday's prediction against reality. This is how you detect model drift before it becomes a problem.*

```python
def evaluate_prediction_accuracy(
    predictions_with_outcomes: list[dict],
) -> dict:
    """
    Compare predictions against actual outcomes for discharged patients.

    This runs daily on patients who were discharged in the last 24 hours.
    Each entry has the prediction that was active at the start of their
    final day and the actual remaining LOS (which we now know was 0 or 1).

    Args:
        predictions_with_outcomes: List of dicts, each with:
            - "predicted_remaining": what the model said
            - "actual_remaining": what actually happened (0 if discharged that day)

    Returns:
        Monitoring metrics dict.
    """
    if not predictions_with_outcomes:
        return {"n_evaluated": 0, "status": "no_discharges"}

    errors = []
    for entry in predictions_with_outcomes:
        error = entry["predicted_remaining"] - entry["actual_remaining"]
        errors.append(error)

    errors_arr = np.array(errors)
    abs_errors = np.abs(errors_arr)

    metrics = {
        "n_evaluated": len(errors),
        "mae": round(float(np.mean(abs_errors)), 2),
        "bias": round(float(np.mean(errors_arr)), 2),  # positive = overpredicting
        "within_1_day_pct": round(float(np.mean(abs_errors <= 1) * 100), 1),
        "within_2_days_pct": round(float(np.mean(abs_errors <= 2) * 100), 1),
        "max_error": round(float(np.max(abs_errors)), 1),
        "evaluation_date": datetime.date.today().isoformat(),
    }

    # Alert if performance is degrading
    if metrics["mae"] > PERFORMANCE_ALERT_THRESHOLD_MAE:
        logger.warning(
            "Model performance degradation detected. MAE=%.2f exceeds threshold=%.2f. "
            "Consider triggering retraining pipeline.",
            metrics["mae"], PERFORMANCE_ALERT_THRESHOLD_MAE
        )

    return metrics
```

---

## Putting It All Together

Here's the full pipeline assembled into a single runnable script. This demonstrates the end-to-end flow: generate data, train a model, make predictions, and evaluate.

```python
def run_full_pipeline():
    """
    Execute the complete LOS prediction pipeline end-to-end.

    This demonstrates:
    1. Synthetic data generation (stand-in for EHR data extraction)
    2. Feature engineering (expanding encounters into daily training examples)
    3. Model training (XGBoost regression)
    4. Inference (predicting remaining LOS for a simulated current inpatient)
    5. Monitoring (evaluating prediction accuracy)

    In production, steps 1-3 run as a SageMaker Training Job (weekly/monthly).
    Steps 4-5 run continuously via Lambda triggers and daily batch jobs.
    """
    print("=" * 60)
    print("LOS Prediction Pipeline - Full Demonstration")
    print("=" * 60)

    # --- Step 1: Generate synthetic encounters ---
    print("\n[Step 1] Generating synthetic hospital encounters...")
    encounters = generate_synthetic_encounters(n_encounters=2000)
    print(f"  Generated {len(encounters)} encounters")
    print(f"  LOS distribution: mean={encounters['actual_los'].mean():.1f}, "
          f"median={encounters['actual_los'].median():.0f}, "
          f"max={encounters['actual_los'].max()}")

    # --- Step 2: Expand into daily training examples ---
    print("\n[Step 2] Generating daily features for training...")
    training_df = generate_daily_features_for_training(encounters)
    print(f"  Created {len(training_df)} training examples "
          f"from {len(encounters)} encounters")
    print(f"  (average {len(training_df)/len(encounters):.1f} examples per encounter)")

    # --- Step 3: Train the model ---
    print("\n[Step 3] Training XGBoost model...")
    model, metrics, top_features = train_los_model(training_df)
    print(f"  MAE: {metrics['mae']} days")
    print(f"  R²: {metrics['r_squared']}")
    print(f"  Within 1 day: {metrics['within_1_day_pct']}%")
    print(f"  Within 2 days: {metrics['within_2_days_pct']}%")
    print(f"  Top features:")
    for feat, importance in top_features:
        print(f"    {feat}: {importance:.3f}")

    # --- Step 4: Predict for a simulated current inpatient ---
    print("\n[Step 4] Running inference for a simulated inpatient...")
    # Simulate a 68-year-old Medicare patient, admitted from ED on day 3,
    # with moderate comorbidity burden and some abnormal labs.
    sample_patient = {
        "age": 68,
        "sex_encoded": 1,
        "admission_source_encoded": 0,  # ED
        "admission_type_encoded": 0,    # emergent
        "drg_geometric_mean_los": 5.2,
        "charlson_score": 4,
        "elixhauser_count": 5,
        "prior_admits_12mo": 1,
        "prior_ed_visits_12mo": 3,
        "insurance_category_encoded": 1,  # Medicare
        "day_of_week_admit": 2,           # Tuesday
        "hour_of_admit": 14,
        "current_day_of_stay": 3,
        "wbc_latest": 9.2,
        "creatinine_latest": 1.4,
        "albumin_latest": 3.0,
        "temp_max_24h": 37.2,
        "hr_variability_24h": 12.0,
        "o2_requirement": 1.0,
        "iv_antibiotics_active": 1,
        "vasopressors_active": 0,
        "procedures_pending": 1,
        "abnormal_lab_count": 2,
    }

    prediction = predict_remaining_los(model, sample_patient)
    print(f"  Patient: 68yo male, day 3, admitted from ED, Charlson=4")
    print(f"  Predicted remaining LOS: {prediction['predicted_remaining_days']} days")
    print(f"  Confidence interval: [{prediction['confidence_lower']}, "
          f"{prediction['confidence_upper']}] days")
    print(f"  Total predicted LOS: {prediction['total_predicted_los']} days")
    print(f"  DRG expected LOS: {prediction['drg_expected_los']} days")
    print(f"  Exceeds expected: {prediction['exceeds_expected']}")

    # --- Step 5: Simulate monitoring ---
    print("\n[Step 5] Simulating prediction accuracy monitoring...")
    # Pretend we had predictions for 20 patients who were discharged yesterday
    simulated_outcomes = [
        {"predicted_remaining": 1.5, "actual_remaining": 1},
        {"predicted_remaining": 2.0, "actual_remaining": 2},
        {"predicted_remaining": 0.8, "actual_remaining": 0},
        {"predicted_remaining": 3.2, "actual_remaining": 4},
        {"predicted_remaining": 1.0, "actual_remaining": 1},
        {"predicted_remaining": 5.5, "actual_remaining": 3},
        {"predicted_remaining": 2.1, "actual_remaining": 2},
        {"predicted_remaining": 1.3, "actual_remaining": 1},
        {"predicted_remaining": 4.0, "actual_remaining": 5},
        {"predicted_remaining": 0.5, "actual_remaining": 0},
    ]

    monitoring = evaluate_prediction_accuracy(simulated_outcomes)
    print(f"  Evaluated {monitoring['n_evaluated']} discharged patients")
    print(f"  MAE: {monitoring['mae']} days")
    print(f"  Bias: {monitoring['bias']} days (positive = overpredicting)")
    print(f"  Within 1 day: {monitoring['within_1_day_pct']}%")

    print("\n" + "=" * 60)
    print("Pipeline complete.")
    print("=" * 60)

    return {
        "model_metrics": metrics,
        "sample_prediction": prediction,
        "monitoring_metrics": monitoring,
    }


if __name__ == "__main__":
    results = run_full_pipeline()
    print("\n\nFull results as JSON:")
    # Convert any non-serializable types for display
    print(json.dumps(results, indent=2, default=str))
```

---

## The Gap Between This and Production

This example runs end-to-end on synthetic data. It trains a model, makes predictions, and evaluates accuracy. But there's a meaningful distance between "works in a script" and "runs in a hospital bed management system." Here's where that gap lives:

**Real data integration.** The synthetic data here is a pale shadow of real EHR data. Real feature engineering requires connecting to HL7/FHIR feeds, parsing ADT events, joining lab results from multiple systems, and handling the messiness of clinical documentation. AWS HealthLake can normalize FHIR data, but the ETL from your EHR to HealthLake is its own project.

**SageMaker deployment.** This example trains and predicts locally. In production, you'd use SageMaker Training Jobs for scalable training, SageMaker Model Registry for versioning, and SageMaker Endpoints for real-time inference. The model artifact gets stored in S3, and the endpoint auto-scales based on inference load.

**Feature Store.** The most critical piece missing here is SageMaker Feature Store. In production, features are computed once and served consistently to both training (offline store) and inference (online store). Without this, you get training-serving skew: the model sees slightly different feature distributions in production than it saw during training, and accuracy degrades silently. This is the #1 cause of "the model worked great in the notebook but is terrible in production."

**Service-line stratification.** This example trains one model on all patients. Real hospitals train separate models per service line (general medicine, cardiac surgery, orthopedics, etc.) because the LOS drivers are fundamentally different. A joint replacement patient's LOS is driven by mobility milestones. A pneumonia patient's LOS is driven by oxygen requirements. One model can't capture both well.

**Confidence intervals.** The uncertainty estimate here is a crude heuristic. Production systems use quantile regression (train separate models for the 10th, 50th, and 90th percentiles) or conformal prediction (distribution-free coverage guarantees). Operations teams need to know the difference between "probably 2 more days" and "could be anywhere from 1 to 8 days."

**Error handling and retries.** Every AWS API call can fail. SageMaker endpoints return 5xx errors under load. DynamoDB can throttle writes. Feature Store reads can timeout. Production code wraps every external call in try/except with exponential backoff and dead-letter queues for failed predictions.

**IAM least-privilege.** The permissions listed in Setup are broader than necessary. Production IAM policies scope each permission to specific resources: the SageMaker endpoint ARN, the specific DynamoDB table, the specific S3 prefix. Not `sagemaker:*`. Not `s3:*`.

**VPC and encryption.** All components run in a VPC with private subnets. VPC endpoints for SageMaker Runtime, S3, DynamoDB, and Feature Store keep traffic off the public internet. KMS customer-managed keys encrypt training data, model artifacts, feature store data, and prediction records. Key rotation is enabled.

**Model monitoring and drift detection.** SageMaker Model Monitor can track feature distributions and prediction distributions over time. When the input data drifts (seasonal changes, new patient populations, process changes), the model needs retraining. This example's `evaluate_prediction_accuracy` function is a simplified version of what Model Monitor does automatically.

**Explainability.** Clinicians won't trust a black-box prediction. Production systems use SHAP values (SageMaker Clarify supports this natively) to show which features drove each individual prediction. "This patient is predicted to stay 3 extra days because: elevated creatinine (+1.2 days), IV antibiotics still active (+0.8 days), pending procedure (+1.0 days)." That's what gets clinician buy-in.

**Testing.** There are no tests here. A production pipeline has unit tests for feature engineering functions, integration tests against SageMaker endpoints with known inputs, regression tests that verify model accuracy doesn't degrade across retraining cycles, and data validation tests that catch schema changes in the EHR feed before they corrupt the feature store.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 7.7](chapter07.07-length-of-stay-prediction) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
