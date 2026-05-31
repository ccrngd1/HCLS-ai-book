# Recipe 7.9: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 7.9. It demonstrates how you might build an ICU mortality risk scoring pipeline using boto3, synthetic data, and a gradient boosted tree model. It is not production-ready. Real ICU mortality models require extensive validation, clinical oversight, IRB approval, and calibration against your specific patient population before anyone should act on their outputs. Consider this a starting point for understanding the architecture, not something you'd deploy to a unit on Monday morning.

---

## Setup

You'll need the following Python packages:

```bash
pip install boto3 numpy pandas scikit-learn xgboost shap
```

Your environment needs AWS credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `sagemaker:InvokeEndpoint`
- `healthlake:SearchWithGet`, `healthlake:ReadResource`
- `dynamodb:PutItem`, `dynamodb:GetItem`
- `cloudwatch:PutMetricData`

For local development and testing (which is what this example does), you only need `numpy`, `pandas`, `scikit-learn`, `xgboost`, and `shap`. The boto3 calls are shown but wrapped so you can run the core logic without an AWS account.

---

## Config and Constants

These go at the top of your module. They define the feature schema, clinical thresholds, and model parameters that the rest of the code references.

```python
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Feature schema: the ordered list of features the model expects.
# This must match exactly what the model was trained on.
# Changing the order or adding/removing features without retraining = garbage predictions.
FEATURE_SCHEMA = [
    # Vital sign summaries (6-hour window)
    "heart_rate_min_6h", "heart_rate_max_6h", "heart_rate_mean_6h", "heart_rate_std_6h",
    "sbp_min_6h", "sbp_max_6h", "sbp_mean_6h", "sbp_std_6h",
    "map_min_6h", "map_max_6h", "map_mean_6h",
    "resp_rate_min_6h", "resp_rate_max_6h", "resp_rate_mean_6h",
    "spo2_min_6h", "spo2_mean_6h",
    "temp_min_6h", "temp_max_6h",

    # Vital sign trends (24-hour slopes)
    "heart_rate_trend_24h", "sbp_trend_24h", "map_trend_24h",

    # Laboratory values (most recent)
    "lactate_latest", "creatinine_latest", "bilirubin_latest",
    "platelets_latest", "wbc_latest", "hemoglobin_latest",
    "pao2_latest", "ph_latest", "bicarbonate_latest",
    "sodium_latest", "potassium_latest", "glucose_latest",
    "inr_latest", "bun_latest",

    # Lab trends
    "lactate_trend", "creatinine_trend",

    # Missing indicators (1 = never measured during stay)
    "lactate_missing", "pao2_missing",

    # Derived indices
    "pf_ratio", "shock_index",

    # Vasopressor and ventilation status
    "vasopressor_count", "norepinephrine_dose", "on_vasopressors",
    "on_mechanical_ventilation", "fio2_latest",

    # Demographics and admission context
    "age", "sex_male", "hours_in_icu", "surgical_admission",

    # Comorbidities
    "comorbidity_count", "has_cancer", "has_ckd", "has_chf",
    "has_copd", "has_diabetes", "has_liver_disease",

    # SOFA components and total
    "sofa_respiratory", "sofa_coagulation", "sofa_liver",
    "sofa_cardiovascular", "sofa_cns", "sofa_renal",
    "sofa_total", "sofa_trend_24h",
]

# SOFA score thresholds (used in feature engineering)
# These are the standard SOFA scoring criteria from Vincent et al. 1996.
SOFA_RESPIRATORY_THRESHOLDS = [
    (400, 0), (300, 1), (200, 2), (100, 3), (0, 4)
]  # P/F ratio thresholds -> SOFA points

SOFA_COAGULATION_THRESHOLDS = [
    (150, 0), (100, 1), (50, 2), (20, 3), (0, 4)
]  # Platelets (x10^3/uL) -> SOFA points

SOFA_LIVER_THRESHOLDS = [
    (1.2, 0), (2.0, 1), (6.0, 2), (12.0, 3), (float("inf"), 4)
]  # Bilirubin (mg/dL) -> SOFA points

SOFA_RENAL_THRESHOLDS = [
    (1.2, 0), (2.0, 1), (3.5, 2), (5.0, 3), (float("inf"), 4)
]  # Creatinine (mg/dL) -> SOFA points

# Model configuration
MODEL_ENDPOINT_NAME = "icu-mortality-model-v2"
DYNAMODB_TABLE_NAME = "icu-mortality-predictions"
CALIBRATION_TABLE_NAME = "calibration-parameters"
CLOUDWATCH_NAMESPACE = "ICU/MortalityModel"
```

---

## Step 1: Generate Synthetic ICU Data

*The main recipe's Step 1 queries HealthLake for real patient data. Here we generate realistic synthetic ICU data so you can run the full pipeline locally without a FHIR store or real PHI. The distributions are loosely based on published ICU population statistics.*

```python
def generate_synthetic_icu_patient(patient_id: str, hours_in_icu: float = 72.0,
                                    severity: str = "moderate") -> dict:
    """
    Generate a synthetic ICU patient with realistic vital signs, labs, and metadata.

    This is for demonstration only. Real patients are messier: values arrive
    at irregular intervals, labs are missing for clinical reasons, and the
    temporal patterns are far more complex than what we simulate here.

    Args:
        patient_id: An identifier for this synthetic patient.
        hours_in_icu: How many hours since ICU admission. Affects data volume.
        severity: One of "mild", "moderate", "severe". Controls how abnormal
                  the generated values are.

    Returns:
        A dictionary mimicking what you'd get from a HealthLake query:
        vitals, labs, medications, demographics, and comorbidities.
    """
    rng = np.random.default_rng(hash(patient_id) % (2**32))

    # Severity multipliers shift vital signs and labs toward abnormal ranges.
    severity_configs = {
        "mild":     {"hr_base": 80,  "sbp_base": 120, "lactate_base": 1.2, "pf_base": 350},
        "moderate": {"hr_base": 100, "sbp_base": 100, "lactate_base": 2.8, "pf_base": 220},
        "severe":   {"hr_base": 120, "sbp_base": 80,  "lactate_base": 5.5, "pf_base": 110},
    }
    cfg = severity_configs[severity]

    # Generate vital sign time series (one reading every 15 minutes)
    n_vitals = int(hours_in_icu * 4)  # 4 readings per hour
    timestamps = [datetime.now(timezone.utc) - timedelta(hours=hours_in_icu)
                  + timedelta(minutes=15 * i) for i in range(n_vitals)]

    vitals = {
        "heart_rate": cfg["hr_base"] + rng.normal(0, 12, n_vitals),
        "sbp": cfg["sbp_base"] + rng.normal(0, 15, n_vitals),
        "dbp": (cfg["sbp_base"] * 0.6) + rng.normal(0, 8, n_vitals),
        "map": (cfg["sbp_base"] * 0.73) + rng.normal(0, 10, n_vitals),
        "resp_rate": 18 + rng.normal(0, 4, n_vitals),
        "spo2": np.clip(97 - (3 if severity == "severe" else 0) + rng.normal(0, 2, n_vitals), 70, 100),
        "temp": 37.2 + rng.normal(0, 0.5, n_vitals),
        "timestamps": timestamps,
    }

    # Add a trend for severe patients: things get worse over time
    if severity == "severe":
        trend = np.linspace(0, 15, n_vitals)
        vitals["heart_rate"] += trend
        vitals["sbp"] -= trend * 0.5

    # Generate lab values (typically 4-8 draws per day in ICU)
    n_labs = int(hours_in_icu / 6)  # roughly every 6 hours
    lab_timestamps = [datetime.now(timezone.utc) - timedelta(hours=hours_in_icu)
                      + timedelta(hours=6 * i) for i in range(n_labs)]

    labs = {
        "lactate": np.clip(cfg["lactate_base"] + rng.normal(0, 0.8, n_labs), 0.5, 20),
        "creatinine": np.clip(1.0 + (1.5 if severity == "severe" else 0.3) + rng.normal(0, 0.3, n_labs), 0.3, 12),
        "bilirubin": np.clip(0.8 + (3.0 if severity == "severe" else 0.2) + rng.normal(0, 0.5, n_labs), 0.1, 30),
        "platelets": np.clip(200 - (120 if severity == "severe" else 20) + rng.normal(0, 30, n_labs), 5, 500),
        "wbc": np.clip(10 + (8 if severity == "severe" else 2) + rng.normal(0, 3, n_labs), 0.5, 50),
        "hemoglobin": np.clip(11 - (3 if severity == "severe" else 0.5) + rng.normal(0, 1, n_labs), 4, 18),
        "pao2": np.clip(cfg["pf_base"] * 0.4 + rng.normal(0, 10, n_labs), 40, 500),
        "ph": np.clip(7.38 - (0.1 if severity == "severe" else 0) + rng.normal(0, 0.03, n_labs), 6.8, 7.6),
        "bicarbonate": np.clip(24 - (6 if severity == "severe" else 1) + rng.normal(0, 2, n_labs), 8, 40),
        "sodium": np.clip(140 + rng.normal(0, 3, n_labs), 120, 160),
        "potassium": np.clip(4.2 + (0.8 if severity == "severe" else 0) + rng.normal(0, 0.4, n_labs), 2.5, 7.0),
        "glucose": np.clip(130 + (50 if severity == "severe" else 10) + rng.normal(0, 30, n_labs), 40, 500),
        "inr": np.clip(1.1 + (0.8 if severity == "severe" else 0.1) + rng.normal(0, 0.2, n_labs), 0.8, 6.0),
        "bun": np.clip(20 + (30 if severity == "severe" else 5) + rng.normal(0, 5, n_labs), 5, 120),
        "timestamps": lab_timestamps,
    }

    # Medications
    medications = {
        "on_vasopressors": severity == "severe" or (severity == "moderate" and rng.random() > 0.6),
        "vasopressor_count": 2 if severity == "severe" else (1 if severity == "moderate" and rng.random() > 0.6 else 0),
        "norepinephrine_dose": 0.15 if severity == "severe" else (0.05 if severity == "moderate" else 0.0),
        "on_mechanical_ventilation": severity in ("severe", "moderate"),
        "fio2": 0.80 if severity == "severe" else (0.50 if severity == "moderate" else 0.21),
    }

    # Demographics
    age = int(rng.integers(45, 88))
    demographics = {
        "age": age,
        "sex_male": int(rng.random() > 0.45),
        "surgical_admission": int(rng.random() > 0.7),
    }

    # Comorbidities (more likely in severe patients)
    comorbidity_prob = 0.4 if severity == "severe" else 0.2
    comorbidities = {
        "has_cancer": int(rng.random() < comorbidity_prob * 0.5),
        "has_ckd": int(rng.random() < comorbidity_prob),
        "has_chf": int(rng.random() < comorbidity_prob),
        "has_copd": int(rng.random() < comorbidity_prob * 0.7),
        "has_diabetes": int(rng.random() < comorbidity_prob * 1.2),
        "has_liver_disease": int(rng.random() < comorbidity_prob * 0.4),
    }
    comorbidities["comorbidity_count"] = sum(comorbidities.values())

    return {
        "patient_id": patient_id,
        "hours_in_icu": hours_in_icu,
        "vitals": vitals,
        "labs": labs,
        "medications": medications,
        "demographics": demographics,
        "comorbidities": comorbidities,
    }
```

---

## Step 2: Engineer Temporal Features

*The main recipe's Step 2 transforms raw time-series clinical data into model-ready features. This includes temporal aggregations, trend calculations, derived physiological indices, and SOFA component scores. The key insight: a heart rate of 110 means something completely different depending on whether it's been 110 for three days or jumped from 70 in the last hour.*

```python
def compute_sofa_respiratory(pf_ratio: float) -> int:
    """Compute SOFA respiratory component from P/F ratio."""
    if pf_ratio is None or np.isnan(pf_ratio):
        return 0  # can't score without data
    for threshold, score in SOFA_RESPIRATORY_THRESHOLDS:
        if pf_ratio >= threshold:
            return score
    return 4


def compute_sofa_coagulation(platelets: float) -> int:
    """Compute SOFA coagulation component from platelet count."""
    if platelets is None or np.isnan(platelets):
        return 0
    for threshold, score in SOFA_COAGULATION_THRESHOLDS:
        if platelets >= threshold:
            return score
    return 4


def compute_sofa_liver(bilirubin: float) -> int:
    """Compute SOFA liver component from bilirubin."""
    if bilirubin is None or np.isnan(bilirubin):
        return 0
    for threshold, score in SOFA_LIVER_THRESHOLDS:
        if bilirubin < threshold:
            return score
    return 4


def compute_sofa_renal(creatinine: float) -> int:
    """Compute SOFA renal component from creatinine."""
    if creatinine is None or np.isnan(creatinine):
        return 0
    for threshold, score in SOFA_RENAL_THRESHOLDS:
        if creatinine < threshold:
            return score
    return 4


def compute_sofa_cardiovascular(mean_map: float, norepi_dose: float) -> int:
    """
    Compute SOFA cardiovascular component.
    Based on MAP and vasopressor requirements.
    """
    if norepi_dose > 0.1:
        return 4
    elif norepi_dose > 0:
        return 3
    elif mean_map is not None and mean_map < 70:
        return 1
    return 0


def compute_trend(values: np.ndarray) -> float:
    """
    Compute linear trend (slope) of a time series using least squares.
    Returns slope in units-per-hour. Positive = increasing.
    """
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    # Simple linear regression: slope = cov(x,y) / var(x)
    slope = np.polyfit(x, values, 1)[0]
    return float(slope)


def engineer_features(raw_data: dict) -> dict:
    """
    Transform raw ICU data into the feature vector the model expects.

    This is where clinical knowledge meets data engineering. Each feature
    is chosen because it has demonstrated predictive value for ICU mortality
    in published literature or in our own model development.

    Args:
        raw_data: Output of generate_synthetic_icu_patient (or a real HealthLake query).

    Returns:
        A dictionary mapping feature names to float values, matching FEATURE_SCHEMA.
    """
    vitals = raw_data["vitals"]
    labs = raw_data["labs"]
    meds = raw_data["medications"]
    demo = raw_data["demographics"]
    comorbidities = raw_data["comorbidities"]

    features = {}

    # --- Vital sign summaries (last 6 hours) ---
    # In a real system, you'd filter by timestamp. Here we take the last 24 readings
    # (6 hours * 4 readings/hour) as our 6-hour window.
    # Note: the loop below generates all summary stats for each vital, but only
    # features listed in FEATURE_SCHEMA are used by the model. Extra features are
    # silently ignored when building the feature vector in score_patient().
    window_6h = 24  # last 24 readings = 6 hours at 15-min intervals

    for vital_name in ["heart_rate", "sbp", "map", "resp_rate", "spo2", "temp"]:
        values = np.array(vitals[vital_name][-window_6h:])
        features[f"{vital_name}_min_6h"] = float(np.nanmin(values))
        features[f"{vital_name}_max_6h"] = float(np.nanmax(values))
        features[f"{vital_name}_mean_6h"] = float(np.nanmean(values))
        if vital_name in ("heart_rate", "sbp"):
            features[f"{vital_name}_std_6h"] = float(np.nanstd(values))

    # DBP summary (needed for derived calculations)
    dbp_6h = np.array(vitals["dbp"][-window_6h:])

    # --- Vital sign trends (24-hour window) ---
    window_24h = 96  # 24 hours * 4 readings/hour
    for vital_name in ["heart_rate", "sbp", "map"]:
        values_24h = np.array(vitals[vital_name][-window_24h:])
        features[f"{vital_name}_trend_24h"] = compute_trend(values_24h)

    # --- Laboratory values ---
    for lab_name in ["lactate", "creatinine", "bilirubin", "platelets", "wbc",
                     "hemoglobin", "pao2", "ph", "bicarbonate", "sodium",
                     "potassium", "glucose", "inr", "bun"]:
        values = labs[lab_name]
        features[f"{lab_name}_latest"] = float(values[-1]) if len(values) > 0 else np.nan
        # Missing indicator
        if lab_name in ("lactate", "pao2"):
            features[f"{lab_name}_missing"] = 0  # synthetic data always has values

    # Lab trends (for key markers)
    for lab_name in ["lactate", "creatinine"]:
        values = np.array(labs[lab_name])
        features[f"{lab_name}_trend"] = compute_trend(values)

    # --- Derived physiological indices ---
    fio2 = meds["fio2"] if meds["fio2"] > 0 else 0.21
    pao2 = features.get("pao2_latest", np.nan)
    features["pf_ratio"] = float(pao2 / fio2) if not np.isnan(pao2) and fio2 > 0 else np.nan
    features["shock_index"] = (
        features["heart_rate_mean_6h"] / features["sbp_mean_6h"]
        if features["sbp_mean_6h"] > 0 else np.nan
    )

    # --- Vasopressor and ventilation ---
    features["vasopressor_count"] = meds["vasopressor_count"]
    features["norepinephrine_dose"] = meds["norepinephrine_dose"]
    features["on_vasopressors"] = int(meds["on_vasopressors"])
    features["on_mechanical_ventilation"] = int(meds["on_mechanical_ventilation"])
    features["fio2_latest"] = fio2

    # --- Demographics ---
    features["age"] = demo["age"]
    features["sex_male"] = demo["sex_male"]
    features["hours_in_icu"] = raw_data["hours_in_icu"]
    features["surgical_admission"] = demo["surgical_admission"]

    # --- Comorbidities ---
    for key, val in comorbidities.items():
        features[key] = val

    # --- SOFA component scores ---
    features["sofa_respiratory"] = compute_sofa_respiratory(features.get("pf_ratio"))
    features["sofa_coagulation"] = compute_sofa_coagulation(features.get("platelets_latest"))
    features["sofa_liver"] = compute_sofa_liver(features.get("bilirubin_latest"))
    features["sofa_cardiovascular"] = compute_sofa_cardiovascular(
        features.get("map_mean_6h"), meds["norepinephrine_dose"]
    )
    # GCS not available in synthetic data; default to 0 (normal)
    features["sofa_cns"] = 0
    # Urine output not modeled; default renal scoring to creatinine only
    features["sofa_renal"] = compute_sofa_renal(features.get("creatinine_latest"))

    features["sofa_total"] = (
        features["sofa_respiratory"] + features["sofa_coagulation"] +
        features["sofa_liver"] + features["sofa_cardiovascular"] +
        features["sofa_cns"] + features["sofa_renal"]
    )
    # SOFA trend: difference from 24h ago. Positive = worsening.
    # In synthetic data we approximate this.
    features["sofa_trend_24h"] = 2.0 if raw_data["hours_in_icu"] > 24 else 0.0

    return features
```

---

## Step 3: Train a Mortality Model (Local Demo)

*In production, model training happens in SageMaker with historical ICU data (thousands of admissions with known outcomes). Here we train a small XGBoost model on synthetic data so you can see the full pipeline end-to-end. The model won't be clinically valid, but the code patterns are identical to what you'd use with real data.*

```python
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, brier_score_loss


def generate_training_dataset(n_patients: int = 2000) -> tuple[pd.DataFrame, np.ndarray]:
    """
    Generate a synthetic training dataset of ICU patients with mortality outcomes.

    The outcome (died vs. survived) is determined by severity:
    - mild patients: ~5% mortality
    - moderate patients: ~25% mortality
    - severe patients: ~60% mortality

    This is a gross simplification. Real mortality depends on hundreds of factors
    and their interactions. But it gives us a dataset where the model can learn
    that sicker-looking patients are more likely to die, which is enough to
    demonstrate the pipeline.
    """
    rng = np.random.default_rng(42)

    records = []
    outcomes = []

    for i in range(n_patients):
        # Assign severity with realistic ICU distribution
        severity_roll = rng.random()
        if severity_roll < 0.35:
            severity = "mild"
            mortality_prob = 0.05
        elif severity_roll < 0.75:
            severity = "moderate"
            mortality_prob = 0.25
        else:
            severity = "severe"
            mortality_prob = 0.60

        hours = float(rng.integers(12, 168))  # 12 hours to 7 days
        patient = generate_synthetic_icu_patient(f"train-{i}", hours, severity)
        features = engineer_features(patient)

        # Ensure feature vector matches schema
        row = [features.get(f, np.nan) for f in FEATURE_SCHEMA]
        records.append(row)

        # Determine outcome (with some noise)
        died = int(rng.random() < mortality_prob)
        outcomes.append(died)

    df = pd.DataFrame(records, columns=FEATURE_SCHEMA)
    labels = np.array(outcomes)

    logger.info("Generated %d patients. Mortality rate: %.1f%%",
                n_patients, 100 * labels.mean())
    return df, labels


def train_mortality_model(X: pd.DataFrame, y: np.ndarray) -> tuple:
    """
    Train an XGBoost mortality model with isotonic calibration.

    Returns both the raw model (for SHAP explanations) and the calibrated
    model (for honest probability estimates).

    In production, this runs in a SageMaker Training Job with:
    - Hyperparameter tuning (Bayesian optimization over learning rate, depth, etc.)
    - Cross-validation for stability estimates
    - Stratified splits to preserve mortality rate in each fold
    - Subgroup performance analysis before promoting to production
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    # XGBoost with conservative hyperparameters.
    # In production you'd tune these with SageMaker Automatic Model Tuning.
    raw_model = XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=10,  # conservative to avoid overfitting on small groups
        reg_alpha=0.1,
        reg_lambda=1.0,
        eval_metric="logloss",
        random_state=42,
    )

    raw_model.fit(X_train, y_train)

    # Evaluate discrimination (AUC)
    y_pred_raw = raw_model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_pred_raw)
    brier = brier_score_loss(y_test, y_pred_raw)
    logger.info("Raw model - AUC: %.3f, Brier: %.3f", auc, brier)

    # Calibrate using isotonic regression on the test set.
    # This makes the predicted probabilities honest: if the model says 30%,
    # approximately 30% of those patients should actually die.
    # In production, calibration is a separate step that loads hospital-specific
    # parameters from DynamoDB (see main recipe Step 4). Here we combine it
    # with training for simplicity.
    calibrated_model = CalibratedClassifierCV(
        raw_model, method="isotonic", cv="prefit"
    )
    calibrated_model.fit(X_test, y_test)

    y_pred_cal = calibrated_model.predict_proba(X_test)[:, 1]
    brier_cal = brier_score_loss(y_test, y_pred_cal)
    logger.info("Calibrated model - Brier: %.3f (lower is better)", brier_cal)

    return raw_model, calibrated_model, X_test, y_test
```

---

## Step 4: Score a Patient and Explain the Prediction

*The main recipe's Steps 3 and 4 invoke a SageMaker endpoint and apply local calibration. Here we use the locally trained model directly. The SHAP explanation is the critical piece: clinicians don't trust a number without knowing why.*

```python
import shap


def score_patient(features: dict, raw_model, calibrated_model) -> dict:
    """
    Score a single patient and generate SHAP explanations.

    Args:
        features: The engineered feature dictionary from engineer_features().
        raw_model: The uncalibrated XGBoost model (needed for SHAP).
        calibrated_model: The isotonic-calibrated model (for honest probabilities).

    Returns:
        A dictionary with the calibrated mortality probability, confidence interval,
        and the top contributing features with plain-language explanations.
    """
    # Build the feature vector in the correct order
    feature_vector = np.array([[features.get(f, np.nan) for f in FEATURE_SCHEMA]])
    feature_df = pd.DataFrame(feature_vector, columns=FEATURE_SCHEMA)

    # Get calibrated probability
    calibrated_prob = float(calibrated_model.predict_proba(feature_df)[:, 1][0])

    # Compute SHAP values for explainability.
    # TreeExplainer is exact for tree-based models (no approximation needed).
    explainer = shap.TreeExplainer(raw_model)
    shap_values = explainer.shap_values(feature_df)

    # Get the top 5 contributing features by absolute SHAP value.
    # shap_values has shape (1, n_features) for our single-row input;
    # index [0] gets that row's SHAP values across all features.
    shap_array = shap_values[0]
    feature_importance = list(zip(FEATURE_SCHEMA, shap_array, feature_vector[0]))
    feature_importance.sort(key=lambda x: abs(x[1]), reverse=True)

    top_contributors = []
    for feat_name, shap_val, feat_val in feature_importance[:5]:
        direction = "increasing risk" if shap_val > 0 else "decreasing risk"
        plain_text = _explain_feature(feat_name, feat_val, shap_val)
        top_contributors.append({
            "feature": feat_name,
            "value": round(float(feat_val), 2) if not np.isnan(feat_val) else None,
            "shap_contribution": round(float(shap_val), 4),
            "direction": direction,
            "plain_text": plain_text,
        })

    # Confidence interval (Wald interval approximation).
    # In production, use the Wilson score interval or Bayesian calibration
    # for better coverage at extreme probabilities (near 0 or 1).
    # Here we use the simpler Wald interval for demonstration.
    n_cal = 500  # approximate calibration sample size
    ci_width = 1.96 * np.sqrt(calibrated_prob * (1 - calibrated_prob) / n_cal)
    ci_lower = max(0.0, calibrated_prob - ci_width)
    ci_upper = min(1.0, calibrated_prob + ci_width)

    return {
        "mortality_probability": round(calibrated_prob, 3),
        "confidence_interval": [round(ci_lower, 3), round(ci_upper, 3)],
        "top_contributors": top_contributors,
    }


def _explain_feature(feature_name: str, value: float, shap_val: float) -> str:
    """
    Translate a feature name and value into plain language a clinician can read.

    This is where data science meets clinical communication. The explanations
    need to be medically meaningful, not just statistically descriptive.
    """
    explanations = {
        "sofa_total": f"Total organ failure score: {int(value)} (higher = more organ systems failing)",
        "sofa_trend_24h": f"Organ failure trend: {'worsening' if value > 0 else 'stable/improving'} over 24h",
        "lactate_latest": f"Lactate: {value:.1f} mmol/L ({'elevated, suggesting tissue hypoperfusion' if value > 2 else 'normal'})",
        "vasopressor_count": f"On {int(value)} vasopressor(s) for blood pressure support",
        "on_vasopressors": "Requiring vasopressor support" if value else "No vasopressor requirement",
        "pf_ratio": f"P/F ratio: {value:.0f} ({'severe ARDS' if value < 100 else 'moderate' if value < 200 else 'mild' if value < 300 else 'normal'})",
        "shock_index": f"Shock index: {value:.2f} ({'concerning' if value > 1.0 else 'normal'})",
        "age": f"Age: {int(value)} years",
        "creatinine_latest": f"Creatinine: {value:.1f} mg/dL ({'elevated, kidney dysfunction' if value > 1.5 else 'normal'})",
        "heart_rate_mean_6h": f"Mean heart rate (6h): {value:.0f} bpm",
        "sbp_mean_6h": f"Mean systolic BP (6h): {value:.0f} mmHg",
        "norepinephrine_dose": f"Norepinephrine dose: {value:.2f} mcg/kg/min",
        "hours_in_icu": f"Hours in ICU: {value:.0f}",
        "sofa_cardiovascular": f"Cardiovascular SOFA: {int(value)}/4",
        "sofa_respiratory": f"Respiratory SOFA: {int(value)}/4",
        "fio2_latest": f"FiO2: {value:.0%} ({'high oxygen requirement' if value > 0.5 else 'low/room air'})",
    }

    if feature_name in explanations:
        return explanations[feature_name]

    # Generic fallback
    direction = "elevated" if shap_val > 0 else "low/protective"
    return f"{feature_name}: {value:.2f} ({direction})"
```

---

## Step 5: Store Prediction (DynamoDB)

*The main recipe's Step 5 writes the prediction to DynamoDB for audit, outcome tracking, and clinical display. Here we show the boto3 call structure. In local testing, you can skip the actual write and just inspect the record.*

```python
from decimal import Decimal


def _convert_floats_to_decimal(obj):
    """Recursively convert float values to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(round(obj, 6)))
    elif isinstance(obj, dict):
        return {k: _convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_floats_to_decimal(i) for i in obj]
    return obj


def build_prediction_record(patient_id: str, admission_id: str,
                            score_result: dict, features: dict) -> dict:
    """
    Assemble the complete prediction record for DynamoDB storage.

    This record serves three purposes:
    1. Clinical display: the probability and explanations shown to clinicians
    2. Audit trail: who was scored, when, with what model version
    3. Outcome tracking: the actual_outcome field gets filled in later for monitoring
    """
    prediction_id = f"pred-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{patient_id[-5:]}"

    record = {
        "prediction_id": prediction_id,
        "patient_id": patient_id,
        "admission_id": admission_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_version": "icu-mortality-v2.3-demo",

        # The prediction
        "mortality_probability": Decimal(str(score_result["mortality_probability"])),
        "confidence_interval_lower": Decimal(str(score_result["confidence_interval"][0])),
        "confidence_interval_upper": Decimal(str(score_result["confidence_interval"][1])),

        # Explainability
        "top_contributors": _convert_floats_to_decimal(score_result["top_contributors"]),

        # Context
        "hours_since_admission": Decimal(str(features.get("hours_in_icu", 0))),
        "sofa_total": int(features.get("sofa_total", 0)),

        # Outcome tracking (filled in when patient is discharged or dies)
        "actual_outcome": None,
        "goals_of_care_changed": None,
    }

    return record


def store_prediction_dynamodb(record: dict) -> None:
    """
    Write the prediction record to DynamoDB.

    In production, this table has:
    - Partition key: prediction_id
    - GSI on patient_id + timestamp (for patient-level queries)
    - GSI on model_version + timestamp (for model monitoring queries)
    - TTL on a retention_expiry field (for data lifecycle management)
    """
    # DynamoDB requires Decimal for numeric types, not float.
    # The build_prediction_record function handles this for all fields,
    # including nested structures (top_contributors), using _convert_floats_to_decimal.
    # Skipping the actual write here since this is a local demo.

    # In production:
    # dynamodb = boto3.resource("dynamodb")
    # table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    # table.put_item(Item=record)

    logger.info("Would write prediction %s to DynamoDB (skipped in demo mode)",
                record["prediction_id"])
```

---

## Step 6: Publish Monitoring Metrics (CloudWatch)

*The main recipe emphasizes continuous monitoring of prediction distribution and calibration drift. This step publishes custom CloudWatch metrics so you can alarm on shifts in model behavior.*

```python
def publish_prediction_metric(mortality_prob: float, model_version: str,
                               hospital_id: str = "demo-hospital") -> None:
    """
    Publish the predicted mortality probability as a CloudWatch custom metric.

    Why this matters: if the average predicted mortality across your ICU suddenly
    shifts (say, from 25% to 40% over a week), something changed. Either your
    patient population got sicker (possible), your data pipeline broke (check first),
    or the model is drifting (retrain). Without this metric, you won't notice
    until someone complains that the scores "feel wrong."

    In production, you'd also publish:
    - Feature distribution metrics (detect data pipeline issues)
    - Prediction latency (detect infrastructure problems)
    - Calibration metrics (weekly, comparing predictions to outcomes)
    """
    # In production:
    # cloudwatch = boto3.client("cloudwatch")
    # cloudwatch.put_metric_data(
    #     Namespace=CLOUDWATCH_NAMESPACE,
    #     MetricData=[{
    #         "MetricName": "PredictedMortality",
    #         "Value": mortality_prob,
    #         "Unit": "None",
    #         "Dimensions": [
    #             {"Name": "HospitalId", "Value": hospital_id},
    #             {"Name": "ModelVersion", "Value": model_version},
    #         ],
    #     }]
    # )

    logger.info("Would publish metric: PredictedMortality=%.3f (hospital=%s, model=%s)",
                mortality_prob, hospital_id, model_version)
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. This trains a model on synthetic data, scores a new patient, explains the prediction, and shows what would be stored and monitored.

```python
def run_full_pipeline():
    """
    Demonstrate the complete ICU mortality risk scoring pipeline.

    This function:
    1. Generates synthetic training data (stand-in for historical ICU admissions)
    2. Trains and calibrates an XGBoost mortality model
    3. Generates a new synthetic patient (stand-in for a real-time HealthLake query)
    4. Engineers features from the patient's ICU data
    5. Scores the patient with SHAP explanations
    6. Builds the prediction record for storage
    7. Shows what would be published to CloudWatch for monitoring

    In production, steps 1-2 happen in a SageMaker Training Pipeline (monthly).
    Steps 3-7 happen on every scoring event (every 4 hours per patient, or on
    significant clinical change).
    """
    print("=" * 70)
    print("ICU Mortality Risk Scoring Pipeline (Demo)")
    print("=" * 70)

    # --- Training phase (happens offline in SageMaker) ---
    print("\n[Phase 1] Training mortality model on synthetic ICU data...")
    X_train_full, y_train_full = generate_training_dataset(n_patients=2000)
    raw_model, calibrated_model, X_test, y_test = train_mortality_model(X_train_full, y_train_full)

    # Report model performance
    y_pred = calibrated_model.predict_proba(X_test)[:, 1]
    print(f"  Model AUC: {roc_auc_score(y_test, y_pred):.3f}")
    print(f"  Brier Score: {brier_score_loss(y_test, y_pred):.3f}")
    print(f"  Mortality rate in test set: {y_test.mean():.1%}")

    # --- Scoring phase (happens in real-time) ---
    print("\n[Phase 2] Scoring a new ICU patient...")

    # Generate a severe patient (simulating a real-time HealthLake query)
    patient = generate_synthetic_icu_patient(
        patient_id="patient-72849",
        hours_in_icu=72.0,
        severity="severe"
    )
    print(f"  Patient: {patient['patient_id']}, {patient['hours_in_icu']:.0f}h in ICU")
    print(f"  Age: {patient['demographics']['age']}, "
          f"Vasopressors: {patient['medications']['vasopressor_count']}, "
          f"Ventilated: {patient['medications']['on_mechanical_ventilation']}")

    # Engineer features
    print("\n[Phase 3] Engineering temporal features...")
    features = engineer_features(patient)
    print(f"  Total features: {len(features)}")
    print(f"  SOFA total: {features['sofa_total']}")
    print(f"  P/F ratio: {features.get('pf_ratio', 'N/A')}")
    print(f"  Shock index: {features.get('shock_index', 'N/A'):.2f}")

    # Score with explanations
    print("\n[Phase 4] Scoring patient and generating explanations...")
    score_result = score_patient(features, raw_model, calibrated_model)

    print(f"\n  *** Mortality Probability: {score_result['mortality_probability']:.1%} ***")
    print(f"  95% CI: [{score_result['confidence_interval'][0]:.1%}, "
          f"{score_result['confidence_interval'][1]:.1%}]")
    print(f"\n  Top contributing factors:")
    for i, contrib in enumerate(score_result["top_contributors"], 1):
        print(f"    {i}. {contrib['plain_text']}")
        print(f"       (SHAP contribution: {contrib['shap_contribution']:+.4f})")

    # Build prediction record
    print("\n[Phase 5] Building prediction record for storage...")
    record = build_prediction_record(
        patient_id=patient["patient_id"],
        admission_id="enc-2026-03-12-4821",
        score_result=score_result,
        features=features,
    )
    print(f"  Prediction ID: {record['prediction_id']}")
    print(f"  Model version: {record['model_version']}")

    # Store (demo mode: just logs)
    store_prediction_dynamodb(record)

    # Publish monitoring metric (demo mode: just logs)
    publish_prediction_metric(
        score_result["mortality_probability"],
        model_version="icu-mortality-v2.3-demo"
    )

    # --- Show the full output as JSON ---
    print("\n[Output] Full prediction record (as JSON):")
    # Convert Decimals to floats for JSON serialization
    output = {
        "prediction_id": record["prediction_id"],
        "patient_id": record["patient_id"],
        "admission_id": record["admission_id"],
        "timestamp": record["timestamp"],
        "model_version": record["model_version"],
        "mortality_probability": float(record["mortality_probability"]),
        "confidence_interval": [
            float(record["confidence_interval_lower"]),
            float(record["confidence_interval_upper"]),
        ],
        "top_contributors": score_result["top_contributors"],
        "sofa_total": record["sofa_total"],
        "hours_since_admission": float(record["hours_since_admission"]),
        "actual_outcome": None,
        "goals_of_care_changed": None,
    }
    print(json.dumps(output, indent=2, default=str))

    print("\n" + "=" * 70)
    print("Pipeline complete. See 'Gap to Production' below for what's missing.")
    print("=" * 70)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run_full_pipeline()
```

---

## The Gap Between This and Production

This example demonstrates the architecture and code patterns. It trains a model, scores a patient, explains the prediction, and shows the storage and monitoring structure. But there's a significant distance between this demo and something you'd deploy in an ICU. Here's where that gap lives:

**Real training data.** This uses synthetic data with simplistic mortality correlations. A production model trains on thousands of real ICU admissions (MIMIC-IV for development, your local EHR data for deployment). The feature engineering is the same, but the model learns real physiological relationships rather than our manufactured severity buckets.

**HealthLake integration.** Step 1 here generates fake data. In production, you query Amazon HealthLake via FHIR APIs to get real-time vital signs, labs, and medications. The FHIR query patterns are well-documented, but handling the data quality issues (missing timestamps, duplicate observations, coding inconsistencies) is a project in itself.

**SageMaker deployment.** The model here lives in memory. In production, it's deployed to a SageMaker real-time endpoint (ml.m5.large is sufficient for XGBoost inference). You'd use SageMaker Model Registry for versioning, SageMaker Pipelines for automated retraining, and SageMaker Model Monitor for drift detection. Configure the endpoint to return both predictions and SHAP values in a single call to reduce latency.

**Local calibration.** The calibration here uses the test set (which is cheating, statistically). Production calibration uses a held-out dataset of recent local outcomes, refreshed monthly. The isotonic regression calibrator is stored in DynamoDB (or S3) and loaded at inference time. Different hospitals get different calibration functions.

**Error handling and retries.** Every external call (HealthLake query, SageMaker invoke, DynamoDB write, CloudWatch publish) needs try/except with specific handling for throttling, timeouts, and service errors. Use exponential backoff with jitter. boto3's adaptive retry mode handles most cases, but you'll want application-level retries for the full pipeline.

**Input validation.** Before scoring, validate that the feature vector has reasonable values. A heart rate of 500 or a negative creatinine indicates a data pipeline issue, not a sick patient. Reject or flag predictions based on obviously invalid inputs.

**Structured logging.** Replace print statements with structured JSON logging (AWS Lambda Powertools is excellent for this). Log the prediction ID, patient ID, model version, and latency for every scoring event. Never log actual clinical values (PHI). Log feature counts and summary statistics instead.

**IAM least-privilege.** The Lambda running this pipeline needs exactly: `sagemaker:InvokeEndpoint` on the specific endpoint ARN, `healthlake:SearchWithGet` on the specific data store, `dynamodb:PutItem` on the predictions table, `cloudwatch:PutMetricData` on the specific namespace. Nothing more.

**VPC and network isolation.** The inference Lambda runs in a VPC with private subnets. VPC endpoints for SageMaker Runtime, HealthLake, DynamoDB, and CloudWatch Logs keep all traffic off the public internet. ICU data is PHI; treat the network path accordingly.

**KMS encryption.** All data at rest (HealthLake, DynamoDB, S3 model artifacts, SageMaker endpoint storage) uses KMS customer-managed keys with automatic rotation. CloudTrail logs every key usage for HIPAA audit.

**Subgroup validation.** Before deployment, evaluate calibration separately for: age groups (especially 85+), sex, race/ethnicity, admission type (medical vs. surgical vs. cardiac), and primary diagnosis category. A model that's well-calibrated overall but systematically overestimates mortality for Black patients is not acceptable.

**Self-fulfilling prophecy tracking.** The `goals_of_care_changed` field in the prediction record must be populated by clinical workflow integration. When a patient transitions to comfort care after a high-risk prediction, that case needs special handling in retraining (either exclusion or explicit modeling of the treatment decision).

**Clinical governance.** A mortality model needs IRB review, clinical champion sign-off, a defined escalation path for model failures, and a kill switch. The technical deployment is the easy part. The institutional governance is what takes months.

**Testing.** Unit tests for feature engineering (known inputs produce known outputs). Integration tests against a HealthLake sandbox with synthetic FHIR data. Model performance tests that verify AUC and calibration haven't degraded after retraining. End-to-end tests that exercise the full Lambda pipeline with mocked external services.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 7.9](chapter07.09-mortality-risk-scoring-icu) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
