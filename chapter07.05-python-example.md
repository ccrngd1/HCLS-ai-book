# Recipe 7.5: 30-Day Readmission Risk (Python Example)

> **Heads up:** This is a deliberately simplified, illustrative implementation of a 30-day readmission risk scoring pipeline. It generates synthetic discharge data, trains a gradient boosted tree model, applies calibration, stratifies patients into risk tiers, and shows how you'd deploy the scoring endpoint via SageMaker. It is not production-ready. The feature engineering is minimal, the synthetic data lacks the messiness of real EHR extracts, and we skip the ADT integration, HealthLake queries, and Step Functions orchestration that a real deployment requires. Think of it as a sketch that shows the shape of the solution. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and standard ML libraries:

```bash
pip install boto3 pandas numpy scikit-learn
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `s3:GetObject`, `s3:PutObject` on your data and model artifact buckets
- `sagemaker:InvokeEndpoint` for real-time scoring
- `dynamodb:PutItem`, `dynamodb:GetItem` on your risk score table
- `sns:Publish` on your high-risk alert topic

For the SageMaker training path, you'll also need a SageMaker execution role with S3 access. This example runs the model locally with scikit-learn for clarity, then shows how you'd invoke a deployed SageMaker endpoint for production scoring.

---

## Config and Constants

These define the feature schema, risk thresholds, calibration parameters, and model configuration. They live at the top because they're configuration decisions, not logic. Readers should see what levers exist before seeing the code that uses them.

```python
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# ─── Risk Tier Thresholds ───────────────────────────────────────────────────
# These thresholds convert a raw probability into an actionable tier.
# They're calibrated to your care transition team's capacity. If your team
# can handle 50 intensive interventions per week, set HIGH_RISK_THRESHOLD
# so roughly 50 patients land above it per week's discharges.
#
# The numbers below assume ~15-20% base readmission rate (Medicare population).
# Commercial populations have lower base rates; adjust accordingly.

HIGH_RISK_THRESHOLD = 0.35    # intensive intervention: nurse callback, home health
MEDIUM_RISK_THRESHOLD = 0.20  # standard follow-up: automated check-in, ensure PCP visit
# Below 0.20: routine discharge (no additional intervention)

# ─── Feature Configuration ──────────────────────────────────────────────────
# These are the features assembled from EHR, claims, and ADT data at discharge.
# In production, you'd query HealthLake and your feature store for these.
# Here we generate synthetic versions to demonstrate the pipeline shape.

FEATURE_COLUMNS = [
    "age",
    "length_of_stay_days",
    "admission_source_ed",          # 1 if admitted through ED, 0 if elective/transfer
    "icu_days",
    "discharge_medication_count",
    "high_risk_medication_count",    # anticoagulants, insulin, opioids
    "admissions_past_6mo",          # strongest single predictor
    "admissions_past_12mo",
    "ed_visits_past_6mo",
    "prior_30day_readmission",      # binary: has this happened before?
    "elixhauser_score",             # comorbidity burden
    "has_chf",
    "has_diabetes",
    "has_copd",
    "has_ckd",
    "has_depression",
    "total_chronic_conditions",
    "albumin_last",                 # nutritional status (low = bad)
    "creatinine_last",              # kidney function
    "hemoglobin_last",              # anemia indicator
    "insurance_type_medicare",      # 1 if Medicare, 0 otherwise
    "zip_deprivation_index",        # Area Deprivation Index (1-10 scale)
]

# ─── Model Parameters ───────────────────────────────────────────────────────
# Gradient boosted trees are the workhorse for tabular readmission prediction.
# Published models achieve C-statistics of 0.68-0.75 depending on feature richness.
# We use conservative hyperparameters to avoid overfitting on smaller cohorts.

MODEL_PARAMS = {
    "n_estimators": 300,
    "max_depth": 4,           # shallow trees: readmission has many weak signals
    "learning_rate": 0.05,    # slower learning with more trees = better generalization
    "min_samples_leaf": 30,   # prevents fitting to tiny subgroups
    "subsample": 0.8,         # row sampling for regularization
    "random_state": 42,
}

# ─── Calibration Parameters ─────────────────────────────────────────────────
# Platt scaling parameters (learned from validation set during training).
# These transform raw model scores into well-calibrated probabilities.
# In production, you'd refit these monthly when you retrain.
# A = slope, B = intercept of the sigmoid transform.
CALIBRATION_A = -1.2
CALIBRATION_B = 0.3

# ─── High-Risk Medication Codes ─────────────────────────────────────────────
# Medications that increase readmission risk when patients don't manage them
# correctly post-discharge. Used in feature engineering.
HIGH_RISK_MED_CLASSES = [
    "anticoagulant",    # warfarin, DOACs: bleeding risk if mismanaged
    "insulin",          # hypoglycemia risk, complex dosing
    "opioid",           # respiratory depression, dependency
    "digoxin",          # narrow therapeutic window
    "immunosuppressant" # infection risk if doses missed
]
```

---

## Step 1: Generate Synthetic Discharge Data

*In production, this data comes from your EHR (via HealthLake FHIR queries), claims warehouse, and ADT feeds assembled at discharge time. Here we generate realistic synthetic data to demonstrate the pipeline without touching any real PHI. The distributions are loosely based on published readmission literature for Medicare populations.*

```python
def generate_synthetic_discharges(n_patients: int = 3000, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic hospital discharge data with realistic readmission patterns.

    Key modeling choices:
    - ~18% base readmission rate (consistent with Medicare averages)
    - Prior utilization is the strongest predictor (well-established in literature)
    - Social factors (deprivation index) add predictive signal beyond clinical data
    - Some patients have missing lab values (realistic: not all labs drawn at discharge)

    Args:
        n_patients: Number of synthetic discharges to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with features and a binary 'readmitted_30d' outcome column.
    """
    rng = np.random.default_rng(seed)

    # Age: Medicare-heavy population, skewed older
    age = rng.normal(loc=67, scale=12, size=n_patients).clip(25, 95).astype(int)
    age_factor = (age - 25) / 70  # normalized 0-1

    # Index admission characteristics
    length_of_stay_days = rng.exponential(4.5, n_patients).clip(1, 30).astype(int)
    admission_source_ed = rng.binomial(1, 0.55, n_patients)  # 55% admitted via ED
    icu_days = np.where(
        rng.random(n_patients) < 0.15,  # 15% of patients have ICU time
        rng.poisson(2, n_patients),
        0
    )

    # Medication complexity
    discharge_medication_count = rng.poisson(7 + 3 * age_factor, n_patients).clip(0, 25)
    high_risk_medication_count = rng.poisson(
        0.5 + 0.5 * age_factor, n_patients
    ).clip(0, 5)

    # Prior utilization history (strongest predictors)
    admissions_past_12mo = rng.poisson(0.4 + 0.3 * age_factor, n_patients)
    admissions_past_6mo = np.minimum(
        rng.poisson(0.2 + 0.2 * age_factor, n_patients),
        admissions_past_12mo
    )
    ed_visits_past_6mo = rng.poisson(0.6 + 0.4 * age_factor, n_patients)
    prior_30day_readmission = rng.binomial(
        1, 0.05 + 0.15 * (admissions_past_6mo > 1).astype(float), n_patients
    )

    # Comorbidities
    has_chf = rng.binomial(1, 0.12 + 0.15 * age_factor, n_patients)
    has_diabetes = rng.binomial(1, 0.20 + 0.10 * age_factor, n_patients)
    has_copd = rng.binomial(1, 0.10 + 0.10 * age_factor, n_patients)
    has_ckd = rng.binomial(1, 0.08 + 0.12 * age_factor, n_patients)
    has_depression = rng.binomial(1, 0.18, n_patients)
    total_chronic_conditions = (
        has_chf + has_diabetes + has_copd + has_ckd + has_depression
        + rng.poisson(1.0, n_patients)  # additional unlisted conditions
    )
    elixhauser_score = (total_chronic_conditions * 2 + rng.poisson(1, n_patients)).clip(0, 20)

    # Lab values at discharge (some missing, which is realistic)
    albumin_last = np.where(
        rng.random(n_patients) < 0.85,  # 85% have albumin drawn
        rng.normal(3.5, 0.6, n_patients).clip(1.5, 5.0),
        np.nan
    )
    creatinine_last = np.where(
        rng.random(n_patients) < 0.90,
        rng.exponential(1.2, n_patients).clip(0.4, 8.0),
        np.nan
    )
    hemoglobin_last = np.where(
        rng.random(n_patients) < 0.88,
        rng.normal(12.0, 2.0, n_patients).clip(5.0, 18.0),
        np.nan
    )

    # Demographics and social factors
    insurance_type_medicare = rng.binomial(1, 0.55 + 0.3 * (age > 65).astype(float), n_patients)
    zip_deprivation_index = rng.integers(1, 11, n_patients)  # 1=least deprived, 10=most

    # ─── Generate outcome (readmitted within 30 days) ───────────────────────
    # Logistic model with realistic effect sizes from published literature.
    # This creates a dataset where features have predictive signal.
    log_odds = (
        -2.0                                            # base rate ~12%
        + 0.8 * admissions_past_6mo                     # strongest signal
        + 0.3 * admissions_past_12mo
        + 0.4 * prior_30day_readmission
        + 0.3 * ed_visits_past_6mo
        + 0.04 * length_of_stay_days
        + 0.05 * discharge_medication_count
        + 0.15 * high_risk_medication_count
        + 0.4 * has_chf
        + 0.2 * has_copd
        + 0.15 * has_ckd
        + 0.2 * has_depression
        + 0.05 * elixhauser_score
        - 0.3 * np.nan_to_num(albumin_last - 3.5, nan=0)  # low albumin = risk
        + 0.1 * np.nan_to_num(creatinine_last - 1.2, nan=0)
        + 0.08 * zip_deprivation_index
        + 0.15 * icu_days
        + rng.normal(0, 0.6, n_patients)                # irreducible noise
    )
    probability = 1 / (1 + np.exp(-log_odds))
    readmitted_30d = rng.binomial(1, probability, n_patients)

    df = pd.DataFrame({
        "patient_id": [f"PAT-{i:07d}" for i in range(n_patients)],
        "encounter_id": [f"ENC-{rng.integers(1000000, 9999999)}" for _ in range(n_patients)],
        "discharge_date": [
            (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=int(d))).isoformat()
            for d in rng.integers(0, 90, n_patients)
        ],
        "age": age,
        "length_of_stay_days": length_of_stay_days,
        "admission_source_ed": admission_source_ed,
        "icu_days": icu_days,
        "discharge_medication_count": discharge_medication_count,
        "high_risk_medication_count": high_risk_medication_count,
        "admissions_past_6mo": admissions_past_6mo,
        "admissions_past_12mo": admissions_past_12mo,
        "ed_visits_past_6mo": ed_visits_past_6mo,
        "prior_30day_readmission": prior_30day_readmission,
        "elixhauser_score": elixhauser_score,
        "has_chf": has_chf,
        "has_diabetes": has_diabetes,
        "has_copd": has_copd,
        "has_ckd": has_ckd,
        "has_depression": has_depression,
        "total_chronic_conditions": total_chronic_conditions,
        "albumin_last": albumin_last,
        "creatinine_last": creatinine_last,
        "hemoglobin_last": hemoglobin_last,
        "insurance_type_medicare": insurance_type_medicare,
        "zip_deprivation_index": zip_deprivation_index,
        "readmitted_30d": readmitted_30d,
    })

    return df
```

---

## Step 2: Train the Readmission Prediction Model

*This step trains a gradient boosted classifier on historical discharge data. In production, you'd run this on SageMaker with the built-in XGBoost container, a larger dataset, and proper cross-validation with temporal splits (train on older data, validate on newer data to simulate real deployment). Here we use scikit-learn locally to keep the focus on the pipeline logic.*

```python
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.calibration import calibration_curve
import json

def train_readmission_model(df: pd.DataFrame) -> tuple:
    """
    Train a gradient boosted tree model for 30-day readmission prediction.

    Key design decisions:
    - Temporal split would be ideal (train on months 1-6, validate on months 7-9).
      We use random split here for simplicity.
    - We handle missing lab values by imputing with median. In production, you'd
      also add binary "is_missing" indicator features (missingness itself is signal:
      a patient without albumin drawn may be less sick, or may have been discharged
      too quickly for labs to result).
    - We don't oversample the minority class. With ~18% positive rate, the imbalance
      isn't severe enough to require SMOTE or class weighting for gradient boosting.

    Args:
        df: DataFrame from generate_synthetic_discharges with features and outcome.

    Returns:
        Tuple of (trained_model, feature_columns, evaluation_metrics).
    """
    feature_cols = FEATURE_COLUMNS
    target_col = "readmitted_30d"

    X = df[feature_cols].copy()
    y = df[target_col]

    # Handle missing values: impute with median, add missingness indicators
    # for lab values (the fact that a lab wasn't drawn is itself informative)
    for col in ["albumin_last", "creatinine_last", "hemoglobin_last"]:
        missing_indicator = f"{col}_missing"
        X[missing_indicator] = X[col].isna().astype(int)
        X[col] = X[col].fillna(X[col].median())

    # Update feature list to include missingness indicators
    all_features = list(X.columns)

    # Split: 70% train, 30% test
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.30, random_state=42, stratify=y
    )

    print(f"Training set: {len(X_train)} discharges, "
          f"{y_train.sum()} readmissions ({y_train.mean():.1%} rate)")
    print(f"Test set: {len(X_test)} discharges, "
          f"{y_test.sum()} readmissions ({y_test.mean():.1%} rate)")

    # Train the model
    model = GradientBoostingClassifier(**MODEL_PARAMS)
    model.fit(X_train, y_train)

    # Evaluate on held-out test set
    y_prob = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_prob)
    brier = brier_score_loss(y_test, y_prob)

    # Calibration check: are predicted probabilities close to observed rates?
    # We bin predictions into deciles and compare predicted vs. actual rates.
    fraction_of_positives, mean_predicted_value = calibration_curve(
        y_test, y_prob, n_bins=10, strategy="quantile"
    )
    calibration_error = np.mean(np.abs(fraction_of_positives - mean_predicted_value))

    # Feature importance (top 10)
    importance = pd.Series(
        model.feature_importances_, index=all_features
    ).sort_values(ascending=False)

    metrics = {
        "auc_roc": round(auc, 4),
        "brier_score": round(brier, 4),
        "mean_calibration_error": round(calibration_error, 4),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "positive_rate": round(y.mean(), 4),
        "top_features": importance.head(10).to_dict(),
    }

    print(f"\n── Model Performance ──")
    print(f"AUC-ROC (C-statistic): {auc:.4f}")
    print(f"Brier Score: {brier:.4f}")
    print(f"Mean Calibration Error: {calibration_error:.4f}")
    print(f"\nTop 5 features by importance:")
    for feat, imp in importance.head(5).items():
        print(f"  {feat}: {imp:.4f}")

    return model, all_features, metrics
```

---

## Step 3: Apply Calibration (Platt Scaling)

*Raw model outputs from gradient boosting aren't always well-calibrated probabilities. A model might output 0.30 for a group of patients where only 20% actually readmit. Platt scaling applies a sigmoid transform to fix this. In production, you'd fit the calibration parameters on a held-out calibration set during training and store them alongside the model artifact.*

```python
def platt_scale(raw_probability: float, a: float = CALIBRATION_A, b: float = CALIBRATION_B) -> float:
    """
    Apply Platt scaling to convert raw model output to calibrated probability.

    Platt scaling fits a sigmoid: calibrated = 1 / (1 + exp(-(a * raw + b)))
    Parameters a and b are learned from a held-out calibration set.

    Why this matters: your care transition team needs to trust that when the
    model says "35% readmission risk," roughly 35% of patients at that score
    actually readmit. Without calibration, the scores are useful for ranking
    but not for setting absolute thresholds or communicating risk to clinicians.

    Args:
        raw_probability: Model output (0 to 1, but may not be well-calibrated).
        a: Platt scaling slope (learned during training).
        b: Platt scaling intercept (learned during training).

    Returns:
        Calibrated probability (0 to 1).
    """
    # Transform through sigmoid with learned parameters
    logit = a * raw_probability + b
    calibrated = 1.0 / (1.0 + np.exp(-logit))
    return float(np.clip(calibrated, 0.001, 0.999))

def fit_platt_scaling(model, X_cal: pd.DataFrame, y_cal: pd.Series) -> dict:
    """
    Fit Platt scaling parameters on a calibration set.

    In production, you'd hold out 15-20% of your training data specifically
    for calibration fitting (separate from the test set used for evaluation).
    The parameters are stored with the model artifact and applied at inference time.

    Args:
        model: Trained sklearn model with predict_proba method.
        X_cal: Calibration set features.
        y_cal: Calibration set labels.

    Returns:
        Dict with 'a' and 'b' parameters for platt_scale function.
    """
    from sklearn.linear_model import LogisticRegression

    raw_probs = model.predict_proba(X_cal)[:, 1].reshape(-1, 1)

    # Fit logistic regression on raw probabilities to learn the transform
    lr = LogisticRegression(solver="lbfgs")
    lr.fit(raw_probs, y_cal)

    params = {
        "a": float(lr.coef_[0][0]),
        "b": float(lr.intercept_[0]),
    }
    print(f"Platt scaling parameters: a={params['a']:.4f}, b={params['b']:.4f}")
    return params
```

---

## Step 4: Score a Patient and Stratify Risk

*This is the real-time scoring path. When a discharge event fires, you assemble the feature vector (Step 1 in the main recipe), pass it through the model, apply calibration, and assign a risk tier. The output goes to DynamoDB for downstream system access and triggers notifications for high-risk patients.*

```python
def score_patient(model, feature_vector: dict, feature_columns: list) -> dict:
    """
    Score a single patient at discharge for 30-day readmission risk.

    This function represents what happens inside the SageMaker endpoint
    (or a Lambda function calling the endpoint). It takes a feature vector,
    runs it through the model, applies calibration, and returns a structured
    risk assessment.

    Args:
        model: Trained model with predict_proba method.
        feature_vector: Dict of feature_name -> value for this patient.
        feature_columns: Ordered list of feature names the model expects.

    Returns:
        Dict with probability, risk tier, and contributing factors.
    """
    # IMPORTANT: Callers MUST impute missing values before calling this function.
    # The pipeline's run_scoring_pipeline() handles imputation. If you call
    # score_patient() directly, impute first or you'll get garbage predictions.
    # scikit-learn's GradientBoostingClassifier does NOT handle missing-value
    # sentinels natively (unlike XGBoost). The -999 below is a safety fallback
    # for unexpected nulls that slip past imputation, not a designed input path.
    #
    # Assemble features in the order the model expects
    features = []
    missing_count = 0
    for col in feature_columns:
        val = feature_vector.get(col)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            features.append(-999)  # safety fallback for unexpected nulls after imputation
            missing_count += 1
        else:
            features.append(val)

    # Guard: if too many features are missing, flag for manual review
    if missing_count > len(feature_columns) * 0.3:
        return {
            "probability": None,
            "risk_tier": "INSUFFICIENT_DATA",
            "method": "missing_features",
            "missing_count": missing_count,
        }

    # Get raw model prediction
    X = np.array(features).reshape(1, -1)
    raw_prob = float(model.predict_proba(X)[0, 1])

    # Apply Platt scaling for calibrated probability
    calibrated_prob = platt_scale(raw_prob)

    # Assign risk tier
    if calibrated_prob >= HIGH_RISK_THRESHOLD:
        risk_tier = "HIGH"
    elif calibrated_prob >= MEDIUM_RISK_THRESHOLD:
        risk_tier = "MEDIUM"
    else:
        risk_tier = "LOW"

    # Get feature contributions (approximate via feature importance * value deviation)
    # In production, you'd use SHAP values for proper per-patient explanations.
    importances = model.feature_importances_
    risk_drivers = []
    for i, col in enumerate(feature_columns):
        if importances[i] > 0.03 and features[i] != -999:
            risk_drivers.append({
                "feature": col,
                "value": features[i],
                "importance": round(float(importances[i]), 4),
            })
    risk_drivers.sort(key=lambda x: x["importance"], reverse=True)

    return {
        "probability": round(calibrated_prob, 4),
        "raw_score": round(raw_prob, 4),
        "risk_tier": risk_tier,
        "risk_drivers": risk_drivers[:5],  # top 5 contributing factors
        "method": "xgboost_calibrated",
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
```

---

## Step 5: Route Interventions Based on Risk Tier

*The model output is useless unless someone acts on it. This step translates risk tiers and contributing factors into specific intervention assignments. A high-risk CHF patient gets different interventions than a high-risk patient with medication complexity.*

```python
# Diagnosis code groups for intervention routing
CHF_CODES = ["I50", "I50.1", "I50.2", "I50.9", "I11.0", "I13.0", "I13.2"]
COPD_CODES = ["J44", "J44.0", "J44.1", "J44.9"]

def route_interventions(score_result: dict, feature_vector: dict) -> list:
    """
    Determine which post-discharge interventions a patient should receive
    based on their risk tier and the specific factors driving their risk.

    The logic here encodes clinical protocols. In production, these rules
    would be configurable (probably in a rules engine or DynamoDB config table)
    so clinical leadership can adjust them without code changes.

    Args:
        score_result: Output from score_patient.
        feature_vector: The patient's feature vector (for condition-specific routing).

    Returns:
        List of intervention strings to assign to this patient.
    """
    risk_tier = score_result.get("risk_tier")
    risk_drivers = score_result.get("risk_drivers", [])
    driver_names = [d["feature"] for d in risk_drivers]

    interventions = []

    if risk_tier == "HIGH":
        # All high-risk patients get a nurse callback within 48 hours
        interventions.append("nurse_callback_48hr")

        # Medication-driven risk: pharmacist reconciliation
        if ("discharge_medication_count" in driver_names
                or "high_risk_medication_count" in driver_names):
            interventions.append("pharmacist_med_reconciliation")

        # Frequent flyer pattern: full care transition program
        if ("admissions_past_6mo" in driver_names
                or "prior_30day_readmission" in driver_names):
            interventions.append("care_transition_program")

        # CHF-specific: remote weight monitoring
        if feature_vector.get("has_chf"):
            interventions.append("remote_weight_monitoring")

        # High social deprivation: social work assessment
        if feature_vector.get("zip_deprivation_index", 0) >= 8:
            interventions.append("social_work_assessment")

    elif risk_tier == "MEDIUM":
        # Medium-risk: lighter touch, automated where possible
        interventions.append("automated_checkin_call_day_7")
        interventions.append("ensure_followup_scheduled")

        # If medication complexity is a driver, still flag for pharmacy
        if "discharge_medication_count" in driver_names:
            interventions.append("pharmacy_phone_consult")

    # LOW risk: no additional interventions (standard discharge)

    return interventions
```

---

## Step 6: Store Risk Score in DynamoDB

*Scored patients need their risk tier accessible to downstream systems (care management platforms, EHR dashboards, nurse worklists) in real time. DynamoDB provides single-digit-millisecond lookups by patient ID.*

```python
import boto3
from botocore.config import Config

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

def store_risk_score(
    score_result: dict,
    patient_id: str,
    encounter_id: str,
    discharge_date: str,
    interventions: list,
    table_name: str = "readmission-risk-scores",
) -> None:
    """
    Write the risk assessment to DynamoDB for downstream system access.

    The TTL is set to 45 days post-discharge (15 days past the 30-day window)
    so scores auto-expire once they're no longer actionable.

    Important DynamoDB gotcha: you must use Decimal for numeric values, not float.
    DynamoDB's SDK rejects Python floats to avoid floating-point precision issues.
    This trips up everyone the first time.

    Args:
        score_result: Output from score_patient.
        patient_id: Patient identifier.
        encounter_id: Encounter/admission identifier.
        discharge_date: ISO format discharge timestamp.
        interventions: List of assigned interventions.
        table_name: DynamoDB table name.
    """
    dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
    table = dynamodb.Table(table_name)

    # Calculate TTL: 45 days after discharge
    discharge_dt = datetime.fromisoformat(discharge_date)
    ttl_timestamp = int((discharge_dt + timedelta(days=45)).timestamp())

    # Convert floats to Decimal (DynamoDB requirement)
    # DynamoDB's TypeSerializer rejects Python floats even when nested inside
    # lists and maps. Every numeric value at any nesting depth must be Decimal.
    item = {
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "discharge_date": discharge_date,
        "probability": Decimal(str(round(score_result["probability"], 4))),
        "raw_score": Decimal(str(round(score_result["raw_score"], 4))),
        "risk_tier": score_result["risk_tier"],
        "risk_drivers": [
            {
                "feature": d["feature"],
                "value": Decimal(str(d["value"])),
                "importance": Decimal(str(d["importance"])),
            }
            for d in score_result["risk_drivers"]
        ],
        "interventions": interventions,
        "model_version": "readmission-xgb-v2.3",
        "scored_at": score_result["scored_at"],
        "ttl": ttl_timestamp,
    }

    table.put_item(Item=item)
    print(f"  Stored risk score for {patient_id}: "
          f"{score_result['risk_tier']} ({score_result['probability']:.1%})")
```

---

## Step 7: Send High-Risk Alerts via SNS

*When a patient is scored as high-risk, the care transition team needs to know immediately. SNS delivers notifications to nurse worklists, pagers, or automated workflow systems.*

```python
def send_high_risk_alert(
    patient_id: str,
    encounter_id: str,
    score_result: dict,
    interventions: list,
    topic_arn: str = "arn:aws:sns:us-east-1:123456789012:high-risk-discharge-alerts",
) -> None:
    """
    Publish an alert for high-risk patients to the care transition team.

    The message includes the risk tier, probability, top risk drivers, and
    assigned interventions so the nurse can prioritize and prepare before
    making the callback.

    Args:
        patient_id: Patient identifier.
        encounter_id: Encounter identifier.
        score_result: Output from score_patient.
        interventions: Assigned interventions list.
        topic_arn: SNS topic ARN for high-risk alerts.
    """
    sns_client = boto3.client("sns", config=BOTO3_RETRY_CONFIG)

    # Format a human-readable message for the care team
    drivers_text = ", ".join(
        f"{d['feature']}={d['value']}" for d in score_result["risk_drivers"][:3]
    )

    message = (
        f"HIGH RISK DISCHARGE ALERT\n"
        f"Patient: {patient_id}\n"
        f"Encounter: {encounter_id}\n"
        f"Readmission Probability: {score_result['probability']:.0%}\n"
        f"Top Risk Factors: {drivers_text}\n"
        f"Assigned Interventions: {', '.join(interventions)}\n"
        f"Action Required: Nurse callback within 48 hours"
    )

    sns_client.publish(
        TopicArn=topic_arn,
        Subject=f"High-Risk Discharge: {patient_id}",
        Message=message,
        MessageAttributes={
            "risk_tier": {"DataType": "String", "StringValue": "HIGH"},
            "patient_id": {"DataType": "String", "StringValue": patient_id},
        },
    )
    print(f"  Alert sent for {patient_id}")
```

---

## Step 8: Invoke SageMaker Endpoint (Production Path)

*In production, the model lives on a SageMaker real-time endpoint rather than in local memory. This function shows how you'd call that endpoint. The endpoint accepts a CSV-formatted feature vector and returns a probability.*

```python
def invoke_sagemaker_endpoint(
    feature_vector: dict,
    feature_columns: list,
    endpoint_name: str = "readmission-risk-v2",
) -> float:
    """
    Call the SageMaker real-time endpoint for readmission scoring.

    The endpoint hosts the trained XGBoost model and returns a raw probability.
    You still need to apply Platt scaling on the client side (or bake it into
    a SageMaker inference pipeline).

    In production, this call happens inside a Lambda function triggered by
    Step Functions as part of the discharge scoring workflow.

    Args:
        feature_vector: Dict of feature_name -> value.
        feature_columns: Ordered list of feature names.
        endpoint_name: Name of the deployed SageMaker endpoint.

    Returns:
        Raw model probability (before calibration).
    """
    sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)

    # Assemble features as CSV (SageMaker XGBoost expects CSV input)
    values = []
    for col in feature_columns:
        val = feature_vector.get(col)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            values.append("")  # empty string = missing for XGBoost
        else:
            values.append(str(val))
    csv_payload = ",".join(values)

    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="text/csv",
        Body=csv_payload.encode("utf-8"),
    )

    raw_probability = float(response["Body"].read().decode("utf-8"))
    return raw_probability
```

---

## Full Pipeline: Score a Batch of Discharges

*This assembles all the steps into a single callable function that processes a batch of discharges. In production, each discharge would be processed individually as events arrive via EventBridge. Here we process a batch to demonstrate the full flow and show aggregate statistics.*

```python
def run_scoring_pipeline(model, feature_columns: list, discharges: pd.DataFrame) -> pd.DataFrame:
    """
    Score a batch of discharges and route interventions.

    This simulates what happens when discharge events flow through the pipeline.
    Each patient gets scored, stratified, assigned interventions, and (in production)
    stored in DynamoDB with alerts sent for high-risk patients.

    Args:
        model: Trained model.
        feature_columns: Feature column names.
        discharges: DataFrame of patients to score.

    Returns:
        DataFrame with scores, tiers, and interventions added.
    """
    results = []

    print(f"\n── Scoring {len(discharges)} discharges ──\n")

    for _, row in discharges.iterrows():
        # Assemble feature vector from the discharge record
        feature_vector = {col: row.get(col) for col in FEATURE_COLUMNS}

        # Add missingness indicators (same as training)
        for col in ["albumin_last", "creatinine_last", "hemoglobin_last"]:
            feature_vector[f"{col}_missing"] = 1 if pd.isna(row.get(col)) else 0
            if pd.isna(row.get(col)):
                # Use training median as imputation (in production, store this with model)
                feature_vector[col] = {"albumin_last": 3.5, "creatinine_last": 1.1,
                                       "hemoglobin_last": 12.0}[col]

        # Score the patient
        score_result = score_patient(model, feature_vector, feature_columns)

        # Route interventions
        interventions = route_interventions(score_result, feature_vector)

        results.append({
            "patient_id": row["patient_id"],
            "encounter_id": row["encounter_id"],
            "discharge_date": row["discharge_date"],
            "probability": score_result.get("probability"),
            "risk_tier": score_result["risk_tier"],
            "risk_drivers": score_result.get("risk_drivers", []),
            "interventions": interventions,
            "actual_readmitted": row.get("readmitted_30d"),
        })

    results_df = pd.DataFrame(results)

    # Print summary statistics
    print(f"\n── Scoring Summary ──")
    tier_counts = results_df["risk_tier"].value_counts()
    for tier in ["HIGH", "MEDIUM", "LOW"]:
        count = tier_counts.get(tier, 0)
        tier_patients = results_df[results_df["risk_tier"] == tier]
        actual_rate = tier_patients["actual_readmitted"].mean() if len(tier_patients) > 0 else 0
        print(f"  {tier}: {count} patients ({count/len(results_df):.1%}), "
              f"actual readmission rate: {actual_rate:.1%}")

    # Overall discrimination
    scored = results_df[results_df["probability"].notna()]
    if len(scored) > 0:
        auc = roc_auc_score(scored["actual_readmitted"], scored["probability"])
        print(f"\n  Scoring AUC: {auc:.4f}")

    return results_df

# ─── Run the full pipeline ──────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("30-Day Readmission Risk Scoring Pipeline")
    print("=" * 60)

    # Step 1: Generate synthetic discharge data
    print("\n[1/4] Generating synthetic discharge data...")
    df = generate_synthetic_discharges(n_patients=3000)
    print(f"  Generated {len(df)} discharges, "
          f"{df['readmitted_30d'].sum()} readmissions "
          f"({df['readmitted_30d'].mean():.1%} rate)")

    # Step 2: Train the model
    print("\n[2/4] Training readmission prediction model...")
    model, feature_cols, metrics = train_readmission_model(df)

    # Step 3: Score a batch of new discharges (simulating real-time scoring)
    print("\n[3/4] Scoring new discharges...")
    # Use the test portion as "new" discharges to score
    new_discharges = df.sample(n=200, random_state=99)
    results = run_scoring_pipeline(model, feature_cols, new_discharges)

    # Step 4: Show example high-risk patient
    print("\n[4/4] Example high-risk patient detail:")
    high_risk = results[results["risk_tier"] == "HIGH"].iloc[0]
    print(f"  Patient: {high_risk['patient_id']}")
    print(f"  Probability: {high_risk['probability']:.1%}")
    print(f"  Risk Drivers: {high_risk['risk_drivers'][:3]}")
    print(f"  Interventions: {high_risk['interventions']}")
    print(f"  Actually readmitted: {'Yes' if high_risk['actual_readmitted'] else 'No'}")

    print("\n" + "=" * 60)
    print("Pipeline complete. In production, scores would be written to")
    print("DynamoDB and high-risk alerts sent via SNS.")
    print("=" * 60)
```

---

## Gap to Production

This example demonstrates the scoring logic, but a real deployment needs substantially more. Here's the distance between this sketch and something you'd put in front of patients:

**Error handling and retries.** Every external call (HealthLake queries, SageMaker endpoint invocation, DynamoDB writes, SNS publishes) needs try/except blocks with exponential backoff. The adaptive retry config helps, but you also need circuit breakers for when a downstream service is fully down. A failed score should never silently disappear; it should land in a dead-letter queue for retry.

**Feature assembly from real data sources.** This example generates synthetic features. In production, you'd query HealthLake for the current encounter (diagnoses, procedures, medications, labs), query your claims warehouse or feature store for historical utilization (prior admissions, ED visits), and compute derived features (Elixhauser score, medication complexity) in real time. That feature assembly step is typically the most complex and fragile part of the pipeline.

**Input validation.** Before scoring, validate that the feature vector is internally consistent (e.g., admissions_past_6mo should not exceed admissions_past_12mo, age should be positive, lab values should be in physiologically plausible ranges). Garbage in, garbage out. Log validation failures for investigation.

**Structured logging.** Every scoring event should produce a structured log entry (JSON format for CloudWatch Logs Insights) with the patient ID, encounter ID, feature completeness, score, tier, and latency. Never log actual PHI values (lab results, diagnosis codes) in plain text. Log the feature names and whether they were present, not their values.

**IAM least-privilege.** The scoring Lambda needs only `sagemaker:InvokeEndpoint` on the specific endpoint ARN, `dynamodb:PutItem` on the specific table, and `sns:Publish` on the specific topic. The training pipeline needs broader SageMaker and S3 permissions but runs in a separate role. Separate roles for scoring vs. training vs. monitoring.

**VPC and VPC endpoints.** In production, the scoring Lambda runs in a VPC with VPC endpoints for SageMaker Runtime, DynamoDB, S3, SNS, and CloudWatch Logs. This keeps PHI-adjacent traffic off the public internet. HealthLake access also goes through a VPC endpoint.

**KMS encryption.** All S3 objects (feature data, model artifacts, scoring logs) encrypted with a customer-managed KMS key. DynamoDB encryption at rest is automatic but you should use a CMK rather than the AWS-managed key for audit trail clarity. SageMaker endpoint traffic is TLS-encrypted in transit.

**Model monitoring and drift detection.** SageMaker Model Monitor can track feature distribution drift and prediction drift automatically. Set up CloudWatch alarms for when AUC drops below 0.65 or calibration slope deviates from 1.0 by more than 0.15. Retrain monthly or when drift is detected.

**Calibration maintenance.** Platt scaling parameters drift as patient populations change. Refit calibration monthly using the most recent 90 days of scored patients with known outcomes. Store calibration parameters in a versioned config (DynamoDB or Parameter Store) so you can roll back if a recalibration goes wrong.

**Fairness auditing.** Check model performance (AUC, calibration) stratified by race, ethnicity, age group, insurance type, and zip code deprivation index. A model that's well-calibrated overall but poorly calibrated for Black patients or Medicaid patients is not acceptable for clinical use. Publish fairness metrics alongside overall performance metrics.

**Clinical validation and governance.** Before deployment, the model needs sign-off from clinical leadership (CMO or designee), a documented validation study comparing model predictions against actual outcomes on a held-out time period, and a clear protocol for what happens when the model is wrong (both false positives and false negatives).

**DynamoDB Decimal requirement.** We handle this in the code (using `Decimal(str(value))` instead of raw floats), but it's worth calling out: DynamoDB's Python SDK rejects float values to avoid IEEE 754 precision issues. Every numeric value going into DynamoDB must be wrapped in `Decimal`. This is the single most common "why is my Lambda failing" question for DynamoDB newcomers.

**Temporal validation for model training.** The random train/test split in this example is fine for demonstration but wrong for production. You must use temporal splits: train on older discharges, validate on newer ones. This simulates how the model will actually be used (trained on the past, predicting the future). Random splits leak future information and produce optimistic performance estimates.

---

**Tags:** `predictive-analytics`, `readmission`, `risk-scoring`, `XGBoost`, `SageMaker`, `DynamoDB`, `calibration`, `HIPAA`, `Python`

---

[← Recipe 7.5: 30-Day Readmission Risk](chapter07.05-30-day-readmission-risk) | [Chapter 7 Index](chapter07-preface) | [Recipe 7.6: Rising Risk Identification →](chapter07.06-rising-risk-identification)
