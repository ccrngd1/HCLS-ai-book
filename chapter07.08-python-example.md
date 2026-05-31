# Recipe 7.8: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the disease progression modeling concepts from Recipe 7.8. It demonstrates the shape of the solution using synthetic CKD (chronic kidney disease) data, a survival model, and SageMaker deployment patterns. It is not production-ready. Real disease progression modeling requires years of validated longitudinal data, careful causal inference, and extensive clinical validation. Think of this as a sketchpad for understanding the architecture, not something you'd deploy to a nephrology clinic next week.

---

## Setup

You'll need the AWS SDK for Python and a few ML libraries:

```bash
pip install boto3 sagemaker pandas numpy scikit-learn lifelines shap
```

Your environment needs credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `sagemaker:CreateTrainingJob`, `sagemaker:CreateModel`, `sagemaker:CreateEndpoint`, `sagemaker:InvokeEndpoint`
- `s3:GetObject`, `s3:PutObject` (scoped to your training data and model artifact buckets)
- `dynamodb:PutItem`, `dynamodb:GetItem` (scoped to your prediction cache table)
- `healthlake:SearchWithPost` (if using HealthLake as your FHIR data source)

---

## Config and Constants

Before the logic, here's the configuration that drives the pipeline. These thresholds, feature definitions, and model parameters live at the top so they're easy to find and adjust. In production, these would come from a parameter store or config file, not hardcoded constants.

```python
import logging
import json
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
import numpy as np
import pandas as pd
from botocore.config import Config

# Structured logging. Never log PHI values (patient names, MRNs, raw lab results).
# Log patient IDs only when necessary for debugging, and ensure logs are in a
# HIPAA-compliant destination (CloudWatch Logs with encryption).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Model Configuration ---

# Prediction horizons in months. These are the time windows we predict over.
# 6 months is short-term (useful for immediate care planning).
# 36 months is the outer edge of what's clinically actionable for CKD.
PREDICTION_HORIZONS_MONTHS = [6, 12, 24, 36]

# Clinical alert threshold: if probability of progression exceeds this
# at the 12-month horizon, generate a clinical alert for the care team.
ALERT_THRESHOLD_12MO = 0.60

# Key biomarkers tracked for CKD progression modeling.
# Each gets trajectory features (slope, variability, current value).
CKD_BIOMARKERS = ["eGFR", "creatinine", "albumin", "hemoglobin", "potassium"]

# Medication classes relevant to CKD progression.
# Duration on these medications is a protective feature.
PROTECTIVE_MED_CLASSES = ["ACE_inhibitor", "ARB", "SGLT2_inhibitor"]

# DynamoDB table for prediction cache.
PREDICTION_TABLE = "disease-progression-predictions"

# S3 bucket for training data and model artifacts.
MODEL_BUCKET = "my-progression-models"

# SageMaker endpoint name for real-time inference.
ENDPOINT_NAME = "ckd-progression-v2"
```

---

## Step 1: Assemble Longitudinal Patient History

*The pseudocode calls this `assemble_patient_timeline(patient_id, lookback_years)`. This step gathers a patient's full temporal record from the clinical data store. Here we simulate it with synthetic data, but in production you'd query HealthLake or your EHR's FHIR API.*

```python
def generate_synthetic_patient_timeline(patient_id: str, progression_rate: str = "moderate") -> dict:
    """
    Generate a synthetic longitudinal patient record for CKD.

    In production, this function would query Amazon HealthLake via FHIR:
        POST https://<healthlake-endpoint>/r4/Observation/_search
        with parameters for patient, date range, and category.

    For this example, we generate realistic synthetic data that mimics
    what you'd get from a real clinical data store. The progression_rate
    parameter controls how fast the synthetic patient's kidney function
    declines, so we can test the model against different trajectories.

    Args:
        patient_id: Unique patient identifier.
        progression_rate: "slow", "moderate", or "fast" decline pattern.

    Returns:
        A timeline dict with labs, medications, conditions, and demographics.
    """
    np.random.seed(hash(patient_id) % 2**32)

    # Simulate 4 years of quarterly lab measurements (irregular intervals).
    # Real patients don't come in on a perfect schedule. We add jitter.
    n_observations = np.random.randint(10, 20)  # 10-20 lab visits over 4 years
    days_offsets = sorted(np.random.choice(range(0, 1460), size=n_observations, replace=False))
    base_date = datetime.date(2022, 1, 15)
    observation_dates = [base_date + datetime.timedelta(days=int(d)) for d in days_offsets]

    # eGFR trajectory: starts between 45-65, declines at a rate determined
    # by the progression_rate parameter. Add noise because real labs fluctuate.
    starting_egfr = np.random.uniform(48, 63)
    decline_rates = {"slow": -1.5, "moderate": -4.0, "fast": -7.0}
    annual_decline = decline_rates[progression_rate]

    egfr_values = []
    for d in days_offsets:
        years_elapsed = d / 365.25
        # True trajectory plus measurement noise (SD ~3 for eGFR)
        egfr = starting_egfr + (annual_decline * years_elapsed) + np.random.normal(0, 3)
        egfr_values.append(round(max(egfr, 8), 1))  # eGFR can't go below ~8 clinically

    # Creatinine (inversely related to eGFR, roughly)
    creatinine_values = [round(1.2 + (60 - e) * 0.02 + np.random.normal(0, 0.1), 2)
                         for e in egfr_values]

    # HbA1c (diabetes control, if diabetic)
    has_diabetes = np.random.random() > 0.4  # 60% of CKD patients have diabetes
    if has_diabetes:
        hba1c_values = [round(np.random.normal(8.2, 0.8), 1) for _ in days_offsets]
    else:
        hba1c_values = [round(np.random.normal(5.6, 0.3), 1) for _ in days_offsets]

    # Assemble labs into FHIR-like observation records
    # Note: we only simulate eGFR, creatinine, and HbA1c for brevity.
    # Albumin, hemoglobin, and potassium would come from real lab data.
    # The feature engineering step handles missing biomarkers gracefully
    # (fills with zero/sentinel values), so the pipeline still runs.
    labs = []
    for i, date in enumerate(observation_dates):
        labs.append({"code": "eGFR", "value": egfr_values[i], "unit": "mL/min/1.73m2", "date": date.isoformat()})
        labs.append({"code": "creatinine", "value": creatinine_values[i], "unit": "mg/dL", "date": date.isoformat()})
        if has_diabetes and i % 3 == 0:  # HbA1c measured less frequently
            labs.append({"code": "HbA1c", "value": hba1c_values[i], "unit": "%", "date": date.isoformat()})

    # Medication history
    medications = []
    if np.random.random() > 0.3:  # 70% on ACE/ARB
        med_start = base_date + datetime.timedelta(days=int(np.random.uniform(0, 200)))
        medications.append({
            "drug_class": "ACE_inhibitor",
            "drug_name": "lisinopril",
            "dose": "10mg daily",
            "start_date": med_start.isoformat(),
            "end_date": None,  # still active
        })
    if has_diabetes:
        medications.append({
            "drug_class": "SGLT2_inhibitor",
            "drug_name": "empagliflozin",
            "dose": "10mg daily",
            "start_date": (base_date + datetime.timedelta(days=90)).isoformat(),
            "end_date": None,
        })

    # Active conditions
    conditions = [{"code": "CKD_stage_3a", "onset": base_date.isoformat(), "status": "active"}]
    if has_diabetes:
        conditions.append({"code": "type_2_diabetes", "onset": "2019-03-01", "status": "active"})
    if np.random.random() > 0.5:
        conditions.append({"code": "hypertension", "onset": "2018-06-15", "status": "active"})

    # Demographics
    demographics = {
        "age": int(np.random.uniform(45, 78)),
        "sex": np.random.choice(["M", "F"]),
    }

    return {
        "patient_id": patient_id,
        "labs": labs,
        "medications": medications,
        "conditions": conditions,
        "demographics": demographics,
    }
```

---

## Step 2: Engineer Temporal Features

*The pseudocode calls this `engineer_progression_features(timeline)`. This transforms raw longitudinal data into the features that actually predict progression: rates of change, variability, treatment duration, and comorbidity burden.*

```python
def compute_slope(dates: list, values: list) -> float:
    """
    Compute the linear slope (rate of change per year) for a biomarker series.

    Uses simple linear regression: fit a line to (time_in_years, value) pairs.
    The slope tells you how fast the biomarker is changing on average.

    For eGFR: negative slope = declining kidney function.
    A slope of -4.0 means losing 4 eGFR points per year (concerning).
    A slope of -1.0 means losing 1 point per year (typical age-related decline).
    """
    if len(values) < 2:
        return 0.0

    # Convert dates to fractional years from the first observation.
    first_date = datetime.date.fromisoformat(dates[0])
    years = [(datetime.date.fromisoformat(d) - first_date).days / 365.25 for d in dates]

    # Simple linear regression via numpy polyfit (degree 1 = line).
    # Returns [slope, intercept].
    coefficients = np.polyfit(years, values, deg=1)
    return round(float(coefficients[0]), 3)


def engineer_progression_features(timeline: dict) -> dict:
    """
    Transform a patient timeline into model-ready features.

    The most predictive features for disease progression aren't the current
    values alone. They're the dynamics: how fast is eGFR declining? Is the
    decline accelerating? How long has the patient been on protective medications?
    How many comorbidities are compounding the kidney stress?

    This function computes all of those from the raw timeline.

    Args:
        timeline: Output of assemble_patient_timeline (or the synthetic generator).

    Returns:
        A flat dictionary of feature_name -> numeric_value, ready for model input.
    """
    features = {}
    labs = timeline["labs"]

    # Define the 12-month lookback cutoff up front. Used for recent slope
    # calculations and medication change counts.
    cutoff = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()

    # --- Biomarker trajectory features ---
    for biomarker in CKD_BIOMARKERS:
        # Extract this biomarker's time series from the labs list.
        bio_records = [l for l in labs if l["code"] == biomarker]
        if not bio_records:
            # Missing biomarker: fill with sentinel values.
            # The model should learn that missing data is informative
            # (patients with missing labs may be less engaged in care).
            features[f"{biomarker}_slope"] = 0.0
            features[f"{biomarker}_current"] = 0.0
            features[f"{biomarker}_variability"] = 0.0
            features[f"{biomarker}_n_measurements"] = 0
            continue

        dates = [r["date"] for r in bio_records]
        values = [r["value"] for r in bio_records]

        # Overall slope: average rate of change per year across full history.
        features[f"{biomarker}_slope"] = compute_slope(dates, values)

        # Recent slope: rate of change in the last 12 months only.
        # If recent slope is steeper than overall slope, the decline is accelerating.
        recent = [(d, v) for d, v in zip(dates, values) if d >= cutoff]
        if len(recent) >= 2:
            recent_dates, recent_values = zip(*recent)
            features[f"{biomarker}_recent_slope"] = compute_slope(list(recent_dates), list(recent_values))
        else:
            features[f"{biomarker}_recent_slope"] = features[f"{biomarker}_slope"]

        # Current value (most recent measurement).
        features[f"{biomarker}_current"] = values[-1]

        # Variability (standard deviation). High variability in eGFR suggests
        # unstable kidney function or acute-on-chronic episodes.
        features[f"{biomarker}_variability"] = round(float(np.std(values)), 3)

        # Number of measurements (data density). More measurements = more
        # reliable slope estimates. Also a proxy for healthcare engagement.
        features[f"{biomarker}_n_measurements"] = len(values)

    # --- Medication features ---
    meds = timeline["medications"]
    today = datetime.date.today()

    for med_class in PROTECTIVE_MED_CLASSES:
        class_meds = [m for m in meds if m["drug_class"] == med_class]
        if class_meds:
            # Duration on this medication class (in months).
            start = datetime.date.fromisoformat(class_meds[0]["start_date"])
            duration_months = (today - start).days / 30.44
            features[f"{med_class}_duration_months"] = round(duration_months, 1)
            features[f"{med_class}_active"] = 1
        else:
            features[f"{med_class}_duration_months"] = 0.0
            features[f"{med_class}_active"] = 0

    # Total medication changes in last 12 months (instability signal).
    features["medication_changes_12mo"] = sum(
        1 for m in meds
        if m.get("end_date") and m["end_date"] >= cutoff
    )

    # --- Comorbidity features ---
    conditions = timeline["conditions"]
    condition_codes = [c["code"] for c in conditions]

    features["diabetes_present"] = 1 if any("diabetes" in c for c in condition_codes) else 0
    features["hypertension_present"] = 1 if "hypertension" in condition_codes else 0
    features["heart_failure_present"] = 1 if "heart_failure" in condition_codes else 0
    features["comorbidity_count"] = len(conditions) - 1  # exclude CKD itself

    # --- Demographics ---
    features["age"] = timeline["demographics"]["age"]
    features["sex_male"] = 1 if timeline["demographics"]["sex"] == "M" else 0

    return features
```

---

## Step 3: Train the Progression Model

*The pseudocode calls this `train_progression_model(training_cohort, prediction_horizons)`. Here we train a survival model using the `lifelines` library locally. In production, you'd run this as a SageMaker training job with a much larger cohort and more sophisticated model architecture.*

```python
from lifelines import CoxPHFitter
from lifelines.utils import concordance_index


def generate_training_cohort(n_patients: int = 500) -> pd.DataFrame:
    """
    Generate a synthetic training cohort with known outcomes.

    Each patient has:
    - Features computed from their longitudinal history
    - A known outcome: did they progress to CKD Stage 4 (eGFR < 30)?
    - Time to event (or time to censoring if they didn't progress)

    In production, this cohort comes from your clinical data warehouse:
    patients with at least 2 years of follow-up after their index date,
    with outcomes determined by chart review or lab thresholds.

    The synthetic data here mimics realistic distributions so the model
    training code is exercised properly.
    """
    records = []

    for i in range(n_patients):
        patient_id = f"train-{i:04d}"

        # Assign a true progression rate (this is what the model tries to learn)
        rate = np.random.choice(["slow", "moderate", "fast"], p=[0.4, 0.35, 0.25])

        # Generate timeline and features
        timeline = generate_synthetic_patient_timeline(patient_id, progression_rate=rate)
        features = engineer_progression_features(timeline)

        # Determine outcome based on the progression rate and some randomness.
        # "event" = progressed to Stage 4. "duration" = months until event or censoring.
        if rate == "fast":
            event = 1 if np.random.random() > 0.2 else 0
            duration = np.random.uniform(6, 24) if event else np.random.uniform(12, 36)
        elif rate == "moderate":
            event = 1 if np.random.random() > 0.5 else 0
            duration = np.random.uniform(18, 42) if event else np.random.uniform(24, 48)
        else:
            event = 1 if np.random.random() > 0.8 else 0
            duration = np.random.uniform(30, 60) if event else np.random.uniform(36, 60)

        features["duration_months"] = round(duration, 1)
        features["event"] = event  # 1 = progressed, 0 = censored
        features["patient_id"] = patient_id

        records.append(features)

    return pd.DataFrame(records)


def train_progression_model(cohort_df: pd.DataFrame) -> CoxPHFitter:
    """
    Train a Cox proportional hazards model for CKD progression.

    Cox PH is the workhorse of survival analysis. It models the hazard
    (instantaneous risk of progression) as a function of patient features,
    while properly handling censored observations (patients who haven't
    progressed yet during the observation period).

    Why Cox PH for a first implementation:
    - Handles censoring natively (critical for disease progression)
    - Interpretable coefficients (clinicians can understand what drives risk)
    - Well-validated in clinical research
    - Doesn't require specifying the baseline hazard shape

    For production, you'd likely upgrade to a DeepSurv or Random Survival
    Forest for better nonlinear capture, but Cox PH is the right starting
    point for validating your data pipeline and feature engineering.

    Args:
        cohort_df: Training data with features, duration_months, and event columns.

    Returns:
        A fitted CoxPHFitter model.
    """
    # Select features for the model. Drop identifiers and the outcome columns.
    exclude_cols = ["patient_id", "duration_months", "event"]
    feature_cols = [c for c in cohort_df.columns if c not in exclude_cols]

    # Handle any missing values. Cox PH doesn't tolerate NaN.
    # In production, use more sophisticated imputation (MICE, etc.).
    model_df = cohort_df[feature_cols + ["duration_months", "event"]].fillna(0)

    # Temporal split: use first 80% of patients for training, last 20% for validation.
    # In production, split by enrollment date (train on 2018-2021, validate on 2022-2023).
    split_idx = int(len(model_df) * 0.8)
    train_df = model_df.iloc[:split_idx]
    valid_df = model_df.iloc[split_idx:]

    # Fit the Cox model.
    # penalizer adds L2 regularization to prevent overfitting on small cohorts.
    # Higher penalizer = more conservative model (fewer extreme coefficients).
    cph = CoxPHFitter(penalizer=0.1)
    cph.fit(
        train_df,
        duration_col="duration_months",
        event_col="event",
    )

    # Evaluate on validation set.
    # C-index: probability that the model correctly ranks two patients
    # (the one who progressed first gets a higher risk score).
    # 0.5 = random, 0.7+ = useful, 0.8+ = excellent.
    valid_predictions = cph.predict_partial_hazard(valid_df[feature_cols])
    c_index = concordance_index(
        valid_df["duration_months"],
        -valid_predictions.values.flatten(),
        # Negate because concordance_index expects higher values to predict
        # longer survival, but predict_partial_hazard returns higher values
        # for higher risk (shorter survival). The negation aligns the scales.
        valid_df["event"],
    )

    logger.info("Model trained. Validation C-index: %.3f", c_index)
    logger.info("Top risk factors (positive = accelerates progression):")
    # Show the top features by absolute coefficient magnitude.
    summary = cph.summary
    top_features = summary.reindex(summary["coef"].abs().sort_values(ascending=False).index)
    for idx, row in top_features.head(5).iterrows():
        direction = "accelerates" if row["coef"] > 0 else "protects"
        logger.info("  %s: coef=%.3f (%s)", idx, row["coef"], direction)

    return cph
```

---

## Step 4: Generate Individual Patient Predictions

*The pseudocode calls this `predict_progression(model, patient_features, horizons)`. Given a trained model and one patient's features, produce a trajectory prediction with uncertainty bounds and explanations.*

```python
def predict_progression(model: CoxPHFitter, patient_features: dict, patient_id: str) -> dict:
    """
    Generate a disease progression prediction for a single patient.

    This is the inference function that runs in production. Given a patient's
    current features (computed from their longitudinal history), it produces:
    - Probability of progression at each time horizon
    - Confidence intervals (uncertainty bounds)
    - Top risk factors driving this patient's prediction
    - Top protective factors slowing progression

    The output is structured for clinical consumption: a clinician should be
    able to glance at it and understand the patient's trajectory.

    Args:
        model: Trained CoxPHFitter model.
        patient_features: Feature dict from engineer_progression_features().
        patient_id: For labeling the output.

    Returns:
        Prediction dict matching the expected output format from Recipe 7.8.
    """
    # Prepare features as a single-row DataFrame (what lifelines expects).
    feature_cols = [c for c in model.params_.index]
    patient_df = pd.DataFrame([{col: patient_features.get(col, 0) for col in feature_cols}])

    # Get the survival function for this patient.
    # This gives P(survival > t) for every time point t.
    survival_fn = model.predict_survival_function(patient_df)

    # Generate predictions at each horizon.
    horizons = {}
    for months in PREDICTION_HORIZONS_MONTHS:
        # P(progression by time t) = 1 - P(survival > t)
        if months in survival_fn.index:
            survival_prob = float(survival_fn.loc[months].values[0])
        else:
            # Interpolate if exact month isn't in the survival function index.
            survival_prob = float(np.interp(months, survival_fn.index, survival_fn.values.flatten()))

        progression_prob = 1.0 - survival_prob

        # Confidence interval via bootstrap-like approach.
        # IMPORTANT: These intervals are purely illustrative placeholders.
        # They do NOT reflect actual model uncertainty. In production, use
        # cph.predict_survival_function with confidence intervals via the
        # alpha parameter in lifelines, or bootstrap resampling, or ensemble
        # disagreement across multiple trained models.
        # Wider intervals at longer horizons (uncertainty compounds over time).
        se_multiplier = 1.0 + (months / 36.0) * 0.5  # grows with horizon
        base_se = 0.08 * se_multiplier
        ci_lower = max(0.0, progression_prob - 1.645 * base_se)
        ci_upper = min(1.0, progression_prob + 1.645 * base_se)

        horizons[f"{months}_months"] = {
            "probability_of_progression": round(progression_prob, 3),
            "confidence_interval_lower": round(ci_lower, 3),
            "confidence_interval_upper": round(ci_upper, 3),
        }

    # Feature importance for this specific patient.
    # Which features are pushing this patient toward faster/slower progression?
    # Using model coefficients * feature values as a simple attribution.
    # In production, use SHAP values for more accurate per-patient explanations.
    attributions = {}
    for col in feature_cols:
        coef = float(model.params_[col])
        value = patient_features.get(col, 0)
        attributions[col] = coef * value

    # Top risk accelerators (positive attribution = increases hazard)
    sorted_attrs = sorted(attributions.items(), key=lambda x: x[1], reverse=True)
    risk_factors = [
        f"{name}: contribution={round(val, 3)}"
        for name, val in sorted_attrs[:3] if val > 0
    ]

    # Top protective factors (negative attribution = decreases hazard)
    protective_factors = [
        f"{name}: contribution={round(val, 3)}"
        for name, val in sorted_attrs[-3:] if val < 0
    ]

    prediction = {
        "patient_id": patient_id,
        "prediction_date": datetime.date.today().isoformat(),
        "current_eGFR": patient_features.get("eGFR_current", None),
        "eGFR_slope_per_year": patient_features.get("eGFR_slope", None),
        "horizons": horizons,
        "risk_factors": risk_factors,
        "protective_factors": protective_factors,
        "model_version": "ckd-progression-cox-v1",
        "data_freshness": datetime.date.today().isoformat(),
    }

    return prediction
```

---

## Step 5: Store Predictions and Generate Alerts

*The pseudocode calls this `integrate_and_monitor(prediction, patient_id)`. This stores the prediction in DynamoDB for low-latency clinical retrieval and checks whether the prediction crosses an actionable threshold. Note: the monitoring function from the main recipe's pseudocode Step 5 is omitted here for brevity; see the main recipe for the calibration and drift detection pattern.*

```python
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)


def store_prediction(prediction: dict) -> dict:
    """
    Write the progression prediction to DynamoDB for clinical retrieval.

    Clinicians need sub-second access to predictions during patient encounters.
    DynamoDB provides single-digit-millisecond reads. The TTL ensures stale
    predictions are automatically cleaned up (predictions should be refreshed
    when new lab data arrives).

    Args:
        prediction: The output of predict_progression().

    Returns:
        The stored record (with TTL and alert metadata added).
    """
    table = dynamodb.Table(PREDICTION_TABLE)

    # Add TTL: predictions expire after 30 days.
    # When new lab results arrive, the pipeline regenerates predictions.
    # Stale predictions (based on old data) should not persist indefinitely.
    ttl_timestamp = int(
        (datetime.datetime.now(timezone.utc) + datetime.timedelta(days=30)).timestamp()
    )

    # Check if this prediction crosses the clinical alert threshold.
    twelve_month_prob = prediction["horizons"].get("12_months", {}).get(
        "probability_of_progression", 0
    )
    needs_alert = twelve_month_prob > ALERT_THRESHOLD_12MO

    record = {
        "patient_id": prediction["patient_id"],
        "prediction_date": prediction["prediction_date"],
        "prediction": json.loads(json.dumps(prediction), parse_float=Decimal),
        # DynamoDB requires Decimal for numeric values, not float.
        # json round-trip with parse_float=Decimal handles nested structures.
        "ttl": ttl_timestamp,
        "needs_alert": needs_alert,
        "alert_generated_at": datetime.datetime.now(timezone.utc).isoformat() if needs_alert else None,
    }

    table.put_item(Item={k: v for k, v in record.items() if v is not None})

    if needs_alert:
        logger.info(
            "ALERT: Patient %s has %.0f%% probability of progression within 12 months. "
            "Consider nephrology referral and treatment escalation review.",
            prediction["patient_id"],
            twelve_month_prob * 100,
        )

    return record
```

---

## Step 6: Upload Training Data and Train on SageMaker

*In production, model training runs on SageMaker rather than locally. This step shows how to package your training data, upload it to S3, and kick off a SageMaker training job. For this example, we use a SageMaker built-in algorithm (Linear Learner in survival mode), but a real implementation would use a custom training container with lifelines, DeepSurv, or a Random Survival Forest.*

```python
import sagemaker
from sagemaker import Session
from sagemaker.sklearn import SKLearn


def upload_training_data(cohort_df: pd.DataFrame, s3_prefix: str = "training-data") -> str:
    """
    Upload the training cohort to S3 for SageMaker training.

    SageMaker training jobs read input data from S3. This function serializes
    the training DataFrame to CSV and uploads it to the model bucket.

    Args:
        cohort_df: The training cohort DataFrame.
        s3_prefix: S3 key prefix for the training data.

    Returns:
        The full S3 URI where the training data was uploaded.
    """
    session = Session()

    # Save to CSV (SageMaker's built-in algorithms expect CSV or RecordIO).
    local_path = "/tmp/training_cohort.csv"
    cohort_df.to_csv(local_path, index=False)

    # Upload to S3.
    s3_uri = session.upload_data(
        path=local_path,
        bucket=MODEL_BUCKET,
        key_prefix=f"{s3_prefix}/{datetime.date.today().isoformat()}",
    )

    logger.info("Training data uploaded to %s", s3_uri)
    return s3_uri


def launch_sagemaker_training(training_data_uri: str) -> str:
    """
    Launch a SageMaker training job for the progression model.

    This uses the SKLearn estimator to run a custom training script on
    SageMaker managed infrastructure. The training script would contain
    the model fitting logic from Step 3, but running on a larger instance
    with more data than you'd want to process locally.

    In production, you'd use:
    - ml.m5.xlarge for Cox PH / Random Survival Forest (CPU-bound)
    - ml.p3.2xlarge for DeepSurv / neural survival models (GPU-bound)
    - SageMaker Experiments for tracking hyperparameter tuning runs

    Args:
        training_data_uri: S3 URI of the training data.

    Returns:
        The SageMaker training job name (for tracking).
    """
    role = sagemaker.get_execution_role()  # IAM role for SageMaker

    # Define the estimator. In production, this points to your custom
    # training script that implements the full model training pipeline.
    estimator = SKLearn(
        entry_point="train_progression_model.py",  # your training script
        role=role,
        instance_count=1,
        instance_type="ml.m5.xlarge",
        framework_version="1.2-1",
        output_path=f"s3://{MODEL_BUCKET}/model-artifacts/",
        hyperparameters={
            "penalizer": 0.1,
            "horizons": "6,12,24,36",
        },
    )

    # Launch the training job.
    estimator.fit({"training": training_data_uri}, wait=False)

    job_name = estimator.latest_training_job.name
    logger.info("SageMaker training job launched: %s", job_name)
    return job_name
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable flow. This demonstrates the end-to-end process: generate data, engineer features, train a model, and produce predictions.

```python
def run_full_pipeline():
    """
    Execute the complete disease progression modeling pipeline.

    This function demonstrates the end-to-end flow:
    1. Generate a synthetic training cohort
    2. Train a survival model
    3. Generate predictions for a test patient
    4. Store predictions for clinical retrieval

    In production, steps 1-2 run as a scheduled batch job (weekly or on new data).
    Steps 3-4 run in real-time when a clinician opens a patient chart.
    """
    logger.info("=" * 60)
    logger.info("Disease Progression Modeling Pipeline")
    logger.info("=" * 60)

    # --- Training Phase (batch, runs periodically) ---

    logger.info("\n--- Phase 1: Generate Training Cohort ---")
    cohort_df = generate_training_cohort(n_patients=500)
    logger.info("Generated %d patient records", len(cohort_df))
    logger.info("Event rate: %.1f%% progressed", cohort_df["event"].mean() * 100)

    logger.info("\n--- Phase 2: Train Progression Model ---")
    model = train_progression_model(cohort_df)

    # --- Inference Phase (real-time, per patient) ---

    logger.info("\n--- Phase 3: Predict for Test Patient ---")
    # Simulate a patient with moderate-to-fast progression.
    test_timeline = generate_synthetic_patient_timeline("pat-test-001", progression_rate="moderate")
    test_features = engineer_progression_features(test_timeline)
    logger.info("Engineered %d features for test patient", len(test_features))

    prediction = predict_progression(model, test_features, "pat-test-001")

    # Display the prediction in a clinician-friendly format.
    logger.info("\n--- Prediction Results ---")
    logger.info("Patient: %s", prediction["patient_id"])
    logger.info("Current eGFR: %s", prediction["current_eGFR"])
    logger.info("eGFR slope: %s points/year", prediction["eGFR_slope_per_year"])
    logger.info("\nProgression probabilities:")
    for horizon, data in prediction["horizons"].items():
        logger.info(
            "  %s: %.0f%% [CI: %.0f%% - %.0f%%]",
            horizon,
            data["probability_of_progression"] * 100,
            data["confidence_interval_lower"] * 100,
            data["confidence_interval_upper"] * 100,
        )
    logger.info("\nRisk factors: %s", prediction["risk_factors"])
    logger.info("Protective factors: %s", prediction["protective_factors"])

    # --- Storage Phase ---
    # Note: Uncomment the following to actually write to DynamoDB.
    # Requires the table to exist and proper IAM permissions.
    # logger.info("\n--- Phase 4: Store Prediction ---")
    # store_prediction(prediction)

    return prediction


# Run the pipeline.
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run_full_pipeline()
    print("\n\nFull prediction output:")
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example trains a model, generates predictions, and produces clinically structured output. But there's a significant distance between "runs in a notebook" and "informs treatment decisions for real patients." Here's where that gap lives:

**Real longitudinal data assembly.** The synthetic data generator here produces clean, well-structured timelines. Real clinical data is fragmented across EHR systems, claims databases, lab interfaces, and pharmacy records. Assembling a complete patient timeline requires ETL pipelines that handle: different coding systems (ICD-10, SNOMED, LOINC), missing data (labs that were ordered but never resulted), duplicate records (same lab reported by multiple systems), and temporal alignment (when a medication "start date" in claims doesn't match the EHR prescription date). This is 70% of the work in a real implementation.

**Censoring and outcome definition.** The synthetic data has clean event/censoring labels. In reality, determining whether a patient "progressed" requires careful outcome definition: which eGFR threshold counts? Do you use a single measurement below 30, or two consecutive measurements? What about patients who started dialysis (which artificially changes eGFR)? What about patients who died from cardiovascular disease before reaching Stage 4? These definitional choices significantly affect model performance and clinical utility.

**Treatment confounding.** This example trains naively on observational data. A real implementation needs to account for the fact that patients who received aggressive treatment (ACE inhibitors, SGLT2 inhibitors, dietary interventions) may have had their progression slowed by that treatment. Without causal adjustment, the model learns "patients on ACE inhibitors progress slowly" rather than "ACE inhibitors slow progression." Marginal structural models or inverse probability weighting are the standard approaches.

**Model validation and fairness.** A production model requires: temporal validation (train on 2018-2021, validate on 2022-2023), subgroup analysis (does the model perform equally well across age groups, races, and sexes?), calibration assessment (when the model says 60% risk, do 60% of patients actually progress?), and comparison against clinical baselines (does the model outperform the KFRE or other established risk equations?). The C-index alone is insufficient for clinical deployment.

**Uncertainty quantification.** The confidence intervals in this example are approximated using standard errors. A production system needs proper uncertainty quantification: Bayesian posterior predictive intervals, ensemble disagreement, or conformal prediction. The intervals must be well-calibrated (90% CIs should contain the true outcome 90% of the time) and must widen appropriately with prediction horizon.

**SageMaker deployment and monitoring.** This example trains locally. Production uses SageMaker for: managed training infrastructure (GPU instances for deep survival models), model registry (versioning, approval workflows, lineage tracking), real-time endpoints (for inference during clinical encounters), and Model Monitor (detecting data drift, prediction drift, and feature distribution changes over time). When the population shifts or new treatments become available, the model needs retraining.

**Clinical integration.** Predictions need to reach clinicians at the right moment in their workflow. This means: FHIR-based integration with the EHR (writing predictions as RiskAssessment resources), CDS Hooks for real-time alerts during chart review, and careful UX design for communicating uncertainty without overwhelming the clinician. A prediction that lives in a standalone dashboard will be ignored.

**Error handling and resilience.** Every external call (HealthLake queries, SageMaker inference, DynamoDB writes) can fail. Production code wraps each in try/except with specific handling for throttling, timeouts, and service unavailability. Failed predictions should degrade gracefully (show "prediction unavailable" rather than crashing the clinical application).

**Regulatory considerations.** Disease progression models that inform treatment decisions may fall under FDA oversight as clinical decision support software. The regulatory pathway depends on whether the model provides information (lower risk) or recommendations (higher risk). Documentation of training data, validation methodology, intended use, and known limitations is required regardless of regulatory classification.

The recipe in 7.8 covers the architectural decisions and honest tradeoffs. This code shows the mechanical shape of the solution. The distance between them is where the real engineering lives.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 7.8](chapter07.08-disease-progression-modeling.md) for the full architectural walkthrough, pseudocode, and honest take on where disease progression modeling gets hard.*
