# Recipe 7.11: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the claim denial prediction pipeline from Recipe 7.11. It demonstrates the core concepts (synthetic claims generation, gradient-boosted classification with class imbalance handling, SHAP explainability, and SageMaker integration) using synthetic data and a locally-trained model. It is not production-ready. Real denial prediction systems require validated feature engineering against actual payer behavior, continuous retraining, and months of threshold calibration with your billing team. Think of this as the whiteboard sketch, not the deployment blueprint.

---

## Setup

You'll need the following packages:

```bash
pip install boto3 numpy pandas scikit-learn xgboost shap matplotlib
```

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `sagemaker:CreateTrainingJob`, `sagemaker:CreateModel`, `sagemaker:CreateEndpointConfig`, `sagemaker:CreateEndpoint`, `sagemaker:InvokeEndpoint` (for SageMaker training and inference)
- `sagemaker:CreateTransformJob` (for batch scoring)
- `s3:GetObject`, `s3:PutObject` (for training data, model artifacts, and batch outputs)
- `dynamodb:PutItem`, `dynamodb:Query` (for prediction storage)
- `iam:PassRole` (to pass the SageMaker execution role)

For this example, we train locally with synthetic data first, then show how you'd wire it into SageMaker. The local version lets you see the full pipeline without incurring AWS costs.

---

## Config and Constants

These thresholds and lookup tables control the synthetic data generation and model behavior. In production, these would come from your actual claims history and payer contracts.

```python
import logging
from decimal import Decimal

# Structured logging. Never log PHI (patient names, MRNs, specific diagnosis
# details in combination with identifying info). Log claim_id for tracing.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- Risk thresholds ---
# These define the operational cutoffs for routing claims to review queues.
# Start conservative (lower thresholds = more flags) and loosen as your
# billing team develops trust in the model.
HIGH_RISK_THRESHOLD = 0.70    # Route to supervisor review
MEDIUM_RISK_THRESHOLD = 0.40  # Surface warning to coder
LOW_RISK_THRESHOLD = 0.20     # Auto-clear, no flag

# --- Synthetic data parameters ---
# Realistic claim volume for a mid-size health system.
# Denial rates vary by payer; 10-15% overall is typical.
NUM_CLAIMS = 50000
OVERALL_DENIAL_RATE = 0.12    # 12% base denial rate

# --- Payer-specific denial rates ---
# In production, you'd compute these from actual claims history.
# These are illustrative but realistic ranges.
PAYER_DENIAL_RATES = {
    "BCBS": 0.09,
    "UnitedHealthcare": 0.14,
    "Aetna": 0.11,
    "Cigna": 0.10,
    "Humana": 0.13,
    "Medicare": 0.07,
    "Medicaid": 0.16,
    "Tricare": 0.08,
}

# --- Common CPT codes with rough denial risk multipliers ---
# Higher multiplier = more likely to be denied without proper documentation/PA.
CPT_RISK_MULTIPLIERS = {
    "99213": 0.5,   # Office visit, established (low risk)
    "99214": 0.6,   # Office visit, moderate (low risk)
    "99215": 0.9,   # Office visit, high complexity (slightly elevated)
    "27447": 1.8,   # Total knee replacement (PA-sensitive)
    "29881": 1.6,   # Knee arthroscopy (PA-sensitive)
    "43239": 1.4,   # Upper GI endoscopy with biopsy
    "70553": 1.5,   # Brain MRI (medical necessity scrutiny)
    "72148": 1.3,   # Lumbar spine MRI
    "90837": 0.7,   # Psychotherapy, 60 min
    "99283": 0.4,   # ED visit, moderate
    "99285": 0.6,   # ED visit, high severity
    "20610": 0.8,   # Joint injection
    "64483": 1.5,   # Epidural injection (PA-sensitive)
    "77067": 0.3,   # Screening mammography (preventive, rarely denied)
    "36415": 0.2,   # Venipuncture (almost never denied)
}

# --- Place of service codes ---
PLACE_OF_SERVICE = {
    "11": "Office",
    "21": "Inpatient Hospital",
    "22": "Outpatient Hospital",
    "23": "Emergency Room",
    "24": "Ambulatory Surgical Center",
    "31": "Skilled Nursing Facility",
    "81": "Independent Lab",
}

# --- SageMaker configuration ---
SAGEMAKER_ROLE_ARN = "arn:aws:iam::123456789012:role/SageMakerExecutionRole"
S3_BUCKET = "claim-denial-ml"
MODEL_PREFIX = "models/denial-prediction"
DATA_PREFIX = "data/features"
```

---

## Step 1: Generate Synthetic Claims Data

*The main recipe's Step 1 computes features from real claims history. Here we generate realistic synthetic claims data with the same structure. The key property to get right is the class imbalance: most claims are paid, and denial probability depends on interactions between payer, procedure, PA status, and provider.*

```python
import numpy as np
import pandas as pd

def generate_synthetic_claims(n_claims: int = NUM_CLAIMS, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic claims data with realistic denial patterns.

    The denial probability for each claim is driven by interactions between
    features, mimicking how real payer adjudication works:
    - Certain payer + procedure combinations have high denial rates
    - Missing prior auth when required almost guarantees denial
    - Provider history and place of service modify risk

    Returns a DataFrame with features and a binary 'denied' label.
    """
    rng = np.random.default_rng(seed)

    # --- Generate base features ---
    payers = list(PAYER_DENIAL_RATES.keys())
    cpt_codes = list(CPT_RISK_MULTIPLIERS.keys())
    pos_codes = list(PLACE_OF_SERVICE.keys())
    provider_types = ["MD", "DO", "NP", "PA", "Facility"]
    specialties = [
        "Family Medicine", "Internal Medicine", "Orthopedics",
        "Cardiology", "Radiology", "Emergency Medicine",
        "Psychiatry", "General Surgery", "Gastroenterology",
        "Neurology",
    ]

    # Sample ICD-10 codes (simplified; real data has 70k+ codes)
    icd10_codes = [
        "M17.11", "M54.5", "I10", "E11.9", "J06.9",
        "K21.0", "G43.909", "F32.1", "M79.3", "R10.9",
        "Z00.00", "Z12.31", "S82.001A", "M25.511", "J18.9",
    ]

    # Modifiers that affect denial risk
    modifier_options = [None, "25", "26", "59", "76", "LT", "RT"]

    # Build the claims DataFrame
    data = {
        "claim_id": [f"CLM-{i:07d}" for i in range(n_claims)],
        "payer": rng.choice(payers, n_claims),
        "cpt_code": rng.choice(cpt_codes, n_claims),
        "icd10_primary": rng.choice(icd10_codes, n_claims),
        "num_diagnoses": rng.integers(1, 6, n_claims),
        "place_of_service": rng.choice(pos_codes, n_claims),
        "provider_type": rng.choice(provider_types, n_claims),
        "specialty": rng.choice(specialties, n_claims),
        "patient_age": rng.integers(18, 90, n_claims),
        "claim_amount": np.round(rng.lognormal(mean=6.0, sigma=1.2, size=n_claims), 2),
        "num_line_items": rng.integers(1, 8, n_claims),
        "modifier_1": rng.choice(modifier_options, n_claims),
        "has_secondary_insurance": rng.choice([0, 1], n_claims, p=[0.7, 0.3]),
        "is_resubmission": rng.choice([0, 1], n_claims, p=[0.92, 0.08]),
        "days_since_service": rng.integers(1, 45, n_claims),
    }

    df = pd.DataFrame(data)

    # --- Assign prior-auth requirement and status ---
    # High-risk CPT codes (multiplier > 1.3) are more likely to require PA.
    pa_required_prob = df["cpt_code"].map(
        lambda c: 0.7 if CPT_RISK_MULTIPLIERS.get(c, 1.0) > 1.3 else 0.1
    )
    df["pa_required"] = rng.binomial(1, pa_required_prob)

    # If PA is required, it's present ~70% of the time (some are missed).
    df["pa_on_file"] = np.where(
        df["pa_required"] == 1,
        rng.binomial(1, 0.70, n_claims),
        0  # If not required, field is 0
    )

    # --- Compute denial probability as a function of feature interactions ---
    # This is the "oracle" that mimics payer adjudication logic.

    # Start with payer base denial rate
    denial_prob = df["payer"].map(PAYER_DENIAL_RATES).values.astype(float)

    # Apply CPT risk multiplier (interaction: payer rate * procedure risk)
    cpt_mult = df["cpt_code"].map(CPT_RISK_MULTIPLIERS).fillna(1.0).values
    denial_prob = denial_prob * cpt_mult

    # PA required but missing is a near-guarantee of denial
    pa_missing = (df["pa_required"] == 1) & (df["pa_on_file"] == 0)
    denial_prob = np.where(pa_missing, np.clip(denial_prob + 0.55, 0, 0.95), denial_prob)

    # Place of service interactions (outpatient surgery scrutinized more)
    outpatient_surgical = df["place_of_service"].isin(["22", "24"])
    denial_prob = np.where(outpatient_surgical, denial_prob * 1.2, denial_prob)

    # High claim amounts get more scrutiny
    high_amount = df["claim_amount"] > 5000
    denial_prob = np.where(high_amount, denial_prob * 1.15, denial_prob)

    # Resubmissions have slightly lower denial (issue was fixed)
    denial_prob = np.where(df["is_resubmission"] == 1, denial_prob * 0.7, denial_prob)

    # Late submissions (>30 days) get timely filing denials
    late_filing = df["days_since_service"] > 30
    denial_prob = np.where(late_filing, denial_prob + 0.10, denial_prob)

    # Add noise and clip to [0, 1]
    denial_prob = np.clip(denial_prob + rng.normal(0, 0.03, n_claims), 0.01, 0.95)

    # Generate binary outcome
    df["denied"] = rng.binomial(1, denial_prob)

    logger.info(
        "Generated %d claims. Denial rate: %.1f%% (%d denied, %d paid)",
        n_claims,
        df["denied"].mean() * 100,
        df["denied"].sum(),
        (1 - df["denied"]).sum(),
    )

    return df
```

---

## Step 2: Feature Engineering and Encoding

*The main recipe discusses how categorical features (CPT codes, payers, etc.) need careful encoding for tree models. Here we handle that encoding plus derived interaction features that carry most of the predictive signal.*

```python
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

def prepare_features(df: pd.DataFrame) -> tuple:
    """
    Encode categorical features and split into train/test sets.

    For gradient-boosted trees, we use label encoding for categoricals
    (trees can split on ordinal-encoded categoricals just fine, unlike
    linear models which need one-hot encoding). For the logistic regression
    baseline, we'll one-hot encode separately.

    Returns:
        X_train, X_test, y_train, y_test, feature_names, label_encoders
    """
    # Create a copy so we don't mutate the original
    features = df.copy()

    # --- Derived interaction features ---
    # These capture the payer-procedure interactions that drive most denials.

    # Payer + CPT interaction (the single most predictive feature)
    features["payer_cpt"] = features["payer"] + "_" + features["cpt_code"]

    # PA gap: required but not on file
    features["pa_gap"] = (
        (features["pa_required"] == 1) & (features["pa_on_file"] == 0)
    ).astype(int)

    # Log-transformed claim amount (reduces skew for the model)
    features["claim_amount_log"] = np.log1p(features["claim_amount"])

    # --- Label-encode categoricals ---
    categorical_cols = [
        "payer", "cpt_code", "icd10_primary", "place_of_service",
        "provider_type", "specialty", "modifier_1", "payer_cpt",
    ]

    label_encoders = {}
    for col in categorical_cols:
        le = LabelEncoder()
        # Handle None/NaN in modifier column
        features[col] = features[col].fillna("NONE")
        features[col] = le.fit_transform(features[col])
        label_encoders[col] = le

    # --- Select model features ---
    feature_cols = [
        "payer", "cpt_code", "icd10_primary", "place_of_service",
        "provider_type", "specialty", "modifier_1", "payer_cpt",
        "num_diagnoses", "patient_age", "claim_amount_log",
        "num_line_items", "pa_required", "pa_on_file", "pa_gap",
        "has_secondary_insurance", "is_resubmission", "days_since_service",
    ]

    X = features[feature_cols]
    y = features["denied"]

    # Stratified split preserves the class imbalance ratio in both sets
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    logger.info(
        "Train set: %d claims (%.1f%% denied). Test set: %d claims (%.1f%% denied)",
        len(y_train), y_train.mean() * 100,
        len(y_test), y_test.mean() * 100,
    )

    return X_train, X_test, y_train, y_test, feature_cols, label_encoders
```

---

## Step 3: Train Logistic Regression Baseline

*Always start with a simple baseline. Logistic regression gives you a floor to beat and helps validate that the signal is in the data. If logistic regression gets 0.75+ AUC, you know a more complex model will do even better.*

```python
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, average_precision_score

def train_baseline(X_train, X_test, y_train, y_test) -> dict:
    """
    Train a logistic regression baseline with class weighting.

    Logistic regression needs scaled features (unlike trees) and handles
    class imbalance via the class_weight parameter. It's fast, interpretable,
    and sets a performance floor.
    """
    # Scale features for logistic regression (trees don't need this)
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # class_weight='balanced' adjusts weights inversely proportional to
    # class frequency. Equivalent to oversampling the minority class.
    lr_model = LogisticRegression(
        class_weight="balanced",
        max_iter=1000,
        random_state=42,
        solver="lbfgs",
    )
    lr_model.fit(X_train_scaled, y_train)

    # Predict probabilities (not hard labels) for threshold-independent evaluation
    y_pred_proba = lr_model.predict_proba(X_test_scaled)[:, 1]

    roc_auc = roc_auc_score(y_test, y_pred_proba)
    pr_auc = average_precision_score(y_test, y_pred_proba)

    logger.info("Logistic Regression baseline: ROC-AUC=%.4f, PR-AUC=%.4f", roc_auc, pr_auc)

    return {
        "model": lr_model,
        "scaler": scaler,
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
    }
```

---

## Step 4: Train XGBoost with Class Imbalance Handling

*This is the main model. XGBoost handles the heterogeneous feature landscape (categoricals, numerics, binary flags) and discovers non-linear interactions automatically. The critical parameter for imbalanced data is `scale_pos_weight`, which tells the model to penalize misclassifying the minority class more heavily.*

```python
import xgboost as xgb

def train_xgboost(X_train, X_test, y_train, y_test) -> dict:
    """
    Train an XGBoost classifier with class imbalance handling.

    Key choices:
    - scale_pos_weight: ratio of negative to positive examples. Tells the
      model that missing a denial is ~7x worse than a false alarm.
    - eval_metric 'aucpr': optimizes for precision-recall AUC, which is
      more informative than ROC-AUC for imbalanced data.
    - early_stopping_rounds: prevents overfitting by stopping when
      validation performance plateaus.
    """
    # Compute class weight ratio
    # If 12% denial rate: (1 - 0.12) / 0.12 = 7.3
    n_positive = y_train.sum()
    n_negative = len(y_train) - n_positive
    scale_pos_weight = n_negative / n_positive

    logger.info(
        "Class balance: %d denied (%.1f%%), %d paid. scale_pos_weight=%.2f",
        n_positive, (n_positive / len(y_train)) * 100,
        n_negative, scale_pos_weight,
    )

    # Create DMatrix objects (XGBoost's optimized data structure)
    dtrain = xgb.DMatrix(X_train, label=y_train)
    dtest = xgb.DMatrix(X_test, label=y_test)

    params = {
        "objective": "binary:logistic",
        "eval_metric": "aucpr",            # precision-recall AUC
        "max_depth": 6,                    # tree depth (6 is a good default)
        "eta": 0.03,                       # learning rate (low for stability)
        "subsample": 0.8,                  # row subsampling per tree
        "colsample_bytree": 0.7,           # feature subsampling per tree
        "scale_pos_weight": scale_pos_weight,
        "min_child_weight": 10,            # minimum samples per leaf
        "gamma": 0.1,                      # minimum loss reduction for split
        "tree_method": "hist",             # faster training with histograms
        "random_state": 42,
    }

    # Train with early stopping on validation set
    model = xgb.train(
        params,
        dtrain,
        num_boost_round=500,
        evals=[(dtrain, "train"), (dtest, "val")],
        early_stopping_rounds=20,
        verbose_eval=50,                   # print every 50 rounds
    )

    # Evaluate
    y_pred_proba = model.predict(dtest)
    roc_auc = roc_auc_score(y_test, y_pred_proba)
    pr_auc = average_precision_score(y_test, y_pred_proba)

    logger.info("XGBoost: ROC-AUC=%.4f, PR-AUC=%.4f", roc_auc, pr_auc)

    return {
        "model": model,
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "best_iteration": model.best_iteration,
    }
```

---

## Step 5: Evaluate with Imbalance-Appropriate Metrics

*Raw accuracy is meaningless for imbalanced data. A model predicting "paid" for everything gets 88% accuracy but catches zero denials. We evaluate with precision-recall curves, PR-AUC, confusion matrices at chosen thresholds, and threshold-specific operating points.*

```python
from sklearn.metrics import (
    precision_recall_curve,
    confusion_matrix,
    classification_report,
)

def evaluate_model(y_test, y_pred_proba, threshold: float = 0.40) -> dict:
    """
    Evaluate predictions with metrics appropriate for class imbalance.

    Key metrics:
    - PR-AUC: area under precision-recall curve (the single best summary
      statistic for imbalanced binary classification)
    - Precision at chosen recall: "if we want to catch X% of denials,
      what fraction of our flags are correct?"
    - Confusion matrix at operational threshold: shows the actual
      true/false positive/negative counts at the threshold you'd deploy with
    """
    # --- Precision-Recall curve ---
    precision, recall, thresholds = precision_recall_curve(y_test, y_pred_proba)
    pr_auc = average_precision_score(y_test, y_pred_proba)
    roc_auc = roc_auc_score(y_test, y_pred_proba)

    # --- Find operational points ---
    # "At what threshold do we catch 80% of denials?"
    recall_target = 0.80
    idx_80_recall = np.argmin(np.abs(recall - recall_target))
    threshold_at_80_recall = thresholds[idx_80_recall] if idx_80_recall < len(thresholds) else 0.5
    precision_at_80_recall = precision[idx_80_recall]

    # --- Confusion matrix at the chosen operational threshold ---
    y_pred_binary = (y_pred_proba >= threshold).astype(int)
    cm = confusion_matrix(y_test, y_pred_binary)
    tn, fp, fn, tp = cm.ravel()

    report = classification_report(y_test, y_pred_binary, target_names=["Paid", "Denied"])

    results = {
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "threshold_used": threshold,
        "precision_at_80_recall": precision_at_80_recall,
        "threshold_for_80_recall": threshold_at_80_recall,
        "confusion_matrix": {
            "true_negatives": int(tn),
            "false_positives": int(fp),
            "false_negatives": int(fn),
            "true_positives": int(tp),
        },
        "classification_report": report,
    }

    logger.info("ROC-AUC: %.4f | PR-AUC: %.4f", roc_auc, pr_auc)
    logger.info("At threshold %.2f: TP=%d, FP=%d, FN=%d, TN=%d", threshold, tp, fp, fn, tn)
    logger.info(
        "To catch 80%% of denials, use threshold=%.3f (precision=%.2f at that point)",
        threshold_at_80_recall, precision_at_80_recall,
    )
    print(report)

    return results
```

---

## Step 6: SHAP Explainability

*Every flagged claim needs a human-readable reason. SHAP decomposes each prediction into per-feature contributions so a biller can see exactly why the model flagged the claim and decide what to fix. Without this, the model is a black box that nobody trusts.*

```python
import shap

def explain_prediction(model, X_test, feature_names: list, claim_index: int = 0) -> dict:
    """
    Generate SHAP explanations for a single claim prediction.

    SHAP values tell you: "This feature pushed the denial probability
    up by 0.15" or "This feature pushed it down by 0.08." The sum of
    all SHAP values plus the base rate equals the final prediction.

    For operational use, we translate the top contributing features into
    natural-language explanations that a biller can act on.
    """
    # TreeExplainer is optimized for tree models (exact, fast)
    explainer = shap.TreeExplainer(model)

    # TreeExplainer accepts DataFrames directly for xgb.train() models
    shap_values = explainer.shap_values(X_test)

    # Get the explanation for one specific claim
    claim_shap = shap_values[claim_index]
    claim_features = X_test.iloc[claim_index]
    base_value = explainer.expected_value

    # Sort features by absolute SHAP contribution (most important first)
    feature_importance = sorted(
        zip(feature_names, claim_shap, claim_features),
        key=lambda x: abs(x[1]),
        reverse=True,
    )

    # Build human-readable explanation for top 5 contributors
    explanations = []
    for feat_name, shap_val, feat_val in feature_importance[:5]:
        direction = "increases" if shap_val > 0 else "decreases"
        explanations.append({
            "feature": feat_name,
            "shap_value": round(float(shap_val), 4),
            "feature_value": feat_val,
            "direction": direction,
            "narrative": _feature_to_narrative(feat_name, shap_val, feat_val),
        })

    prediction = float(base_value + sum(claim_shap))

    logger.info(
        "Claim %d: prediction=%.3f (base=%.3f + shap_sum=%.3f)",
        claim_index, prediction, base_value, sum(claim_shap),
    )
    for exp in explanations:
        logger.info("  %s: SHAP=%.4f (%s)", exp["feature"], exp["shap_value"], exp["narrative"])

    return {
        "claim_index": claim_index,
        "prediction": round(prediction, 4),
        "base_value": round(float(base_value), 4),
        "top_factors": explanations,
    }


def _feature_to_narrative(feature_name: str, shap_value: float, feature_value) -> str:
    """
    Map a SHAP feature contribution to a human-readable explanation.

    In production, this mapping would be much richer, pulling in actual
    payer names, procedure descriptions, and historical rates from your
    feature store. This simplified version shows the pattern.
    """
    direction = "higher" if shap_value > 0 else "lower"

    narratives = {
        "pa_gap": f"Prior auth gap (required but missing) pushes denial risk {direction}",
        "pa_required": f"PA requirement status pushes denial risk {direction}",
        "pa_on_file": f"PA on file status pushes denial risk {direction}",
        "payer_cpt": f"This payer-procedure combination pushes denial risk {direction}",
        "payer": f"This payer's overall denial behavior pushes risk {direction}",
        "cpt_code": f"This procedure code's denial history pushes risk {direction}",
        "claim_amount_log": f"Claim amount pushes denial risk {direction}",
        "days_since_service": f"Days since service pushes risk {direction}",
        "place_of_service": f"Place of service pushes denial risk {direction}",
        "modifier_1": f"Modifier status pushes denial risk {direction}",
    }

    return narratives.get(feature_name, f"{feature_name} pushes denial risk {direction}")
```

---

## Step 7: SageMaker Training Integration

*This shows how you'd train the same model on SageMaker instead of locally. SageMaker handles distributed training, automatic model artifact storage, and seamless deployment to endpoints. The built-in XGBoost container matches our local training exactly.*

```python
import boto3
import sagemaker
from sagemaker.inputs import TrainingInput
from sagemaker.xgboost import XGBoost

def train_on_sagemaker(
    training_data_s3_uri: str,
    validation_data_s3_uri: str,
    denial_rate: float = OVERALL_DENIAL_RATE,
) -> str:
    """
    Train the denial prediction model on SageMaker.

    This mirrors the local XGBoost training but runs on managed infrastructure.
    The model artifact is stored in S3 and can be deployed directly to an endpoint.

    Args:
        training_data_s3_uri: S3 path to training CSV (no header, label in first column)
        validation_data_s3_uri: S3 path to validation CSV
        denial_rate: observed denial rate for computing scale_pos_weight

    Returns:
        S3 URI of the trained model artifact
    """
    sess = sagemaker.Session()
    scale_pos_weight = (1 - denial_rate) / denial_rate

    # The SageMaker XGBoost framework estimator runs a custom training script.
    # For the built-in algorithm (no custom code), use sagemaker.estimator.Estimator
    # with the XGBoost image URI and omit entry_point.
    xgb_estimator = XGBoost(
        entry_point="train.py",        # Required for framework estimator mode (custom preprocessing)
        framework_version="1.7-1",     # XGBoost version in the container
        role=SAGEMAKER_ROLE_ARN,
        instance_count=1,
        instance_type="ml.m5.2xlarge",
        output_path=f"s3://{S3_BUCKET}/{MODEL_PREFIX}/",
        sagemaker_session=sess,
        hyperparameters={
            "objective": "binary:logistic",
            "eval_metric": "aucpr",
            "num_round": 500,
            "max_depth": 6,
            "eta": 0.03,
            "subsample": 0.8,
            "colsample_bytree": 0.7,
            "scale_pos_weight": scale_pos_weight,
            "min_child_weight": 10,
            "gamma": 0.1,
            "early_stopping_rounds": 20,
        },
        # Encrypt training volume with KMS (PHI requirement)
        volume_kms_key="alias/sagemaker-training-key",
        # Run in VPC for network isolation
        subnets=["subnet-abc123"],
        security_group_ids=["sg-xyz789"],
    )

    # SageMaker expects data in specific channels
    train_input = TrainingInput(
        training_data_s3_uri,
        content_type="text/csv",
    )
    val_input = TrainingInput(
        validation_data_s3_uri,
        content_type="text/csv",
    )

    xgb_estimator.fit({"train": train_input, "validation": val_input})

    model_artifact = xgb_estimator.model_data
    logger.info("Model artifact stored at: %s", model_artifact)

    return model_artifact
```

---

## Step 8: Deploy Real-Time Endpoint and Score Claims

*Once trained, the model needs to serve predictions in real-time (when a coder finalizes a claim) and in batch (nightly scoring of all pending claims). This shows both patterns.*

```python
def deploy_realtime_endpoint(model_artifact_s3: str) -> str:
    """
    Deploy the trained model as a SageMaker real-time endpoint.

    Real-time inference adds ~50-150ms latency per claim, which is
    acceptable for inline billing system integration.
    """
    sess = sagemaker.Session()
    sm_client = boto3.client("sagemaker")

    # Create model object pointing to the artifact
    model_name = "denial-prediction-model-latest"
    sm_client.create_model(
        ModelName=model_name,
        PrimaryContainer={
            "Image": sagemaker.image_uris.retrieve("xgboost", sess.boto_region_name, "1.7-1"),
            "ModelDataUrl": model_artifact_s3,
        },
        ExecutionRoleArn=SAGEMAKER_ROLE_ARN,
        # VPC config for PHI data isolation
        VpcConfig={
            "SecurityGroupIds": ["sg-xyz789"],
            "Subnets": ["subnet-abc123"],
        },
    )

    # Create endpoint config
    endpoint_config_name = "denial-prediction-endpoint-config"
    sm_client.create_endpoint_config(
        EndpointConfigName=endpoint_config_name,
        ProductionVariants=[{
            "VariantName": "primary",
            "ModelName": model_name,
            "InstanceType": "ml.m5.xlarge",
            "InitialInstanceCount": 1,
        }],
        # Encrypt model artifacts on the endpoint instance
        KmsKeyId="alias/sagemaker-endpoint-key",
    )

    # Create (or update) the endpoint
    endpoint_name = "denial-prediction-prod"
    sm_client.create_endpoint(
        EndpointName=endpoint_name,
        EndpointConfigName=endpoint_config_name,
    )

    logger.info("Endpoint '%s' creating. Wait for InService status.", endpoint_name)
    return endpoint_name


def score_claim_realtime(endpoint_name: str, claim_features: dict) -> dict:
    """
    Score a single claim against the real-time endpoint.

    Called by the billing system when a coder finalizes a claim.
    Returns the denial probability for immediate display.
    """
    sm_runtime = boto3.client("sagemaker-runtime")

    # Serialize features as CSV (SageMaker XGBoost expects CSV input).
    # CRITICAL: order must match training feature order exactly.
    # Use a canonical feature list, not the dictionary's key order.
    FEATURE_ORDER = [
        "payer", "cpt_code", "icd10_primary", "place_of_service",
        "provider_type", "specialty", "modifier_1", "payer_cpt",
        "num_diagnoses", "patient_age", "claim_amount_log",
        "num_line_items", "pa_required", "pa_on_file", "pa_gap",
        "has_secondary_insurance", "is_resubmission", "days_since_service",
    ]
    feature_values = [str(claim_features.get(f, 0)) for f in FEATURE_ORDER]
    payload = ",".join(feature_values)

    response = sm_runtime.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="text/csv",
        Body=payload.encode("utf-8"),
    )

    denial_probability = float(response["Body"].read().decode("utf-8"))

    return {
        "denial_probability": round(denial_probability, 4),
        "risk_tier": _classify_risk(denial_probability),
    }


def _classify_risk(probability: float) -> str:
    """Map probability to operational risk tier."""
    if probability >= HIGH_RISK_THRESHOLD:
        return "HIGH"
    if probability >= MEDIUM_RISK_THRESHOLD:
        return "MEDIUM"
    return "LOW"
```

---

## Step 9: Batch Scoring with SageMaker Batch Transform

*Nightly batch scoring evaluates all pending claims and populates worklists for the next day. Batch transform is more cost-effective than keeping a real-time endpoint running for overnight scoring of large claim volumes.*

```python
def run_batch_scoring(model_artifact_s3: str, input_s3_uri: str, output_s3_uri: str):
    """
    Run batch transform to score all pending claims overnight.

    Batch transform is ideal for the nightly scoring run:
    - Spins up compute, scores all claims, writes results, shuts down
    - More cost-effective than keeping an endpoint running for large batch jobs
    - Handles arbitrarily large claim volumes with automatic splitting

    Args:
        model_artifact_s3: S3 URI of the trained model
        input_s3_uri: S3 path containing claim feature CSVs to score
        output_s3_uri: S3 path to write prediction results
    """
    sess = sagemaker.Session()
    sm_client = boto3.client("sagemaker")

    model_name = "denial-prediction-batch-model"

    # Create model (reuse artifact from training)
    sm_client.create_model(
        ModelName=model_name,
        PrimaryContainer={
            "Image": sagemaker.image_uris.retrieve("xgboost", sess.boto_region_name, "1.7-1"),
            "ModelDataUrl": model_artifact_s3,
        },
        ExecutionRoleArn=SAGEMAKER_ROLE_ARN,
    )

    # Launch batch transform job
    transform_job_name = f"denial-scoring-nightly-{pd.Timestamp.now().strftime('%Y%m%d')}"

    sm_client.create_transform_job(
        TransformJobName=transform_job_name,
        ModelName=model_name,
        TransformInput={
            "DataSource": {
                "S3DataSource": {
                    "S3DataType": "S3Prefix",
                    "S3Uri": input_s3_uri,
                }
            },
            "ContentType": "text/csv",
            "SplitType": "Line",       # Each line is one claim
        },
        TransformOutput={
            "S3OutputPath": output_s3_uri,
            "AssembleWith": "Line",
        },
        TransformResources={
            "InstanceType": "ml.m5.2xlarge",
            "InstanceCount": 1,
        },
    )

    logger.info(
        "Batch transform job '%s' started. Input: %s, Output: %s",
        transform_job_name, input_s3_uri, output_s3_uri,
    )
    return transform_job_name
```

---

## Putting It All Together

Here's the full local pipeline assembled into a single function. This demonstrates the end-to-end flow: generate data, train both models, evaluate, and explain.

```python
def run_full_pipeline():
    """
    Run the complete claim denial prediction pipeline locally.

    This demonstrates the end-to-end workflow:
    1. Generate synthetic claims with realistic denial patterns
    2. Engineer features and encode categoricals
    3. Train logistic regression baseline
    4. Train XGBoost with class imbalance handling
    5. Evaluate both models with imbalance-appropriate metrics
    6. Generate SHAP explanations for flagged claims
    """
    print("=" * 70)
    print("CLAIM DENIAL PREDICTION PIPELINE")
    print("=" * 70)

    # Step 1: Generate synthetic claims
    print("\n[Step 1] Generating synthetic claims data...")
    claims_df = generate_synthetic_claims(n_claims=NUM_CLAIMS)
    print(f"  Generated {len(claims_df)} claims")
    print(f"  Denial rate: {claims_df['denied'].mean():.1%}")
    print(f"  Denied: {claims_df['denied'].sum()}, Paid: {(1 - claims_df['denied']).sum()}")

    # Step 2: Feature engineering
    print("\n[Step 2] Preparing features and train/test split...")
    X_train, X_test, y_train, y_test, feature_names, encoders = prepare_features(claims_df)
    print(f"  Train: {len(X_train)} claims | Test: {len(X_test)} claims")
    print(f"  Features: {len(feature_names)}")

    # Step 3: Logistic regression baseline
    print("\n[Step 3] Training logistic regression baseline...")
    lr_results = train_baseline(X_train, X_test, y_train, y_test)
    print(f"  Baseline ROC-AUC: {lr_results['roc_auc']:.4f}")
    print(f"  Baseline PR-AUC: {lr_results['pr_auc']:.4f}")

    # Step 4: XGBoost model
    print("\n[Step 4] Training XGBoost with class imbalance handling...")
    xgb_results = train_xgboost(X_train, X_test, y_train, y_test)
    print(f"  XGBoost ROC-AUC: {xgb_results['roc_auc']:.4f}")
    print(f"  XGBoost PR-AUC: {xgb_results['pr_auc']:.4f}")
    print(f"  Improvement over baseline: +{xgb_results['roc_auc'] - lr_results['roc_auc']:.4f} ROC-AUC")

    # Step 5: Detailed evaluation at operational threshold
    print("\n[Step 5] Evaluating at operational threshold...")
    dtest = xgb.DMatrix(X_test)
    y_pred_proba = xgb_results["model"].predict(dtest)
    eval_results = evaluate_model(y_test, y_pred_proba, threshold=MEDIUM_RISK_THRESHOLD)

    # Step 6: SHAP explanation for a high-risk claim
    print("\n[Step 6] Generating SHAP explanations for a flagged claim...")
    # Find a high-risk claim to explain
    high_risk_indices = np.where(y_pred_proba > HIGH_RISK_THRESHOLD)[0]
    if len(high_risk_indices) > 0:
        explain_idx = high_risk_indices[0]
        explanation = explain_prediction(
            xgb_results["model"], X_test, feature_names, claim_index=explain_idx
        )
        print(f"\n  Explaining claim at index {explain_idx}:")
        print(f"  Prediction: {explanation['prediction']:.3f} (base: {explanation['base_value']:.3f})")
        for factor in explanation["top_factors"][:3]:
            print(f"    {factor['feature']}: SHAP={factor['shap_value']:+.4f} -> {factor['narrative']}")
    else:
        print("  No claims above HIGH threshold in test set.")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Logistic Regression: ROC-AUC={lr_results['roc_auc']:.4f}, PR-AUC={lr_results['pr_auc']:.4f}")
    print(f"  XGBoost: ROC-AUC={xgb_results['roc_auc']:.4f}, PR-AUC={xgb_results['pr_auc']:.4f}")
    print(f"  Claims flagged (>{MEDIUM_RISK_THRESHOLD:.0%} threshold): {(y_pred_proba > MEDIUM_RISK_THRESHOLD).sum()}")
    print(f"  High-risk (>{HIGH_RISK_THRESHOLD:.0%}): {(y_pred_proba > HIGH_RISK_THRESHOLD).sum()}")
    print("\n  For SageMaker deployment, use train_on_sagemaker() and deploy_realtime_endpoint().")
    print("  For nightly batch scoring, use run_batch_scoring().")


if __name__ == "__main__":
    run_full_pipeline()
```

---

## Gap to Production

This example demonstrates the core ML pipeline, but deploying a claim denial prediction system to production requires substantial additional engineering. Here's the distance between this sketch and something you'd put in front of your billing team.

**Error handling and retries.** Every AWS API call (SageMaker endpoint invocation, DynamoDB writes, S3 reads) needs retry logic with exponential backoff. Use `botocore.config.Config(retries={"max_attempts": 3, "mode": "adaptive"})` for boto3 calls. Handle SageMaker endpoint `ModelError` exceptions (malformed input) separately from throttling errors.

**Input validation.** Validate every claim feature before sending to the model. CPT codes should match a known code set. Payer IDs should exist in your payer master. Claim amounts should be positive. Reject or flag claims with missing critical features rather than letting the model predict on garbage.

**Real feature engineering.** The synthetic data here uses static lookup tables. Production features require rolling historical computations: payer-procedure denial rates over trailing 6 months, provider-specific denial patterns, and temporal trends. This is a Glue or Spark ETL job that runs daily, writing to a feature store (SageMaker Feature Store or a simple S3-backed table).

**Model monitoring and drift detection.** Payer rules change. New PA requirements appear. Coverage policies shift quarterly. Monitor prediction distributions daily. Compare predicted denial rates to actual denial rates (once adjudication results arrive, typically 14-30 days later). Trigger retraining when accuracy degrades by more than 2-3 points of AUC. SageMaker Model Monitor automates much of this.

**The feedback loop problem.** If your model flags claims and coders fix them before submission, the "fixed" claims get paid. Your training data then shows these payer-procedure combinations as low-risk (because you fixed them). You need to track which claims were modified based on model predictions and either exclude them from training or use counterfactual labels ("would have been denied if not modified"). This is the hardest engineering problem in the system.

**Structured logging (not print statements).** Replace all `print()` calls with structured JSON logging. Log claim_id, prediction, risk_tier, and model_version for every scoring event. Never log PHI field values (patient name, DOB, specific diagnosis text in combination with identifiers). Use CloudWatch Logs Insights for querying.

**IAM least-privilege.** The example uses a single broad role. Production needs separate roles: (1) Glue ETL role with S3 read/write and data source access, (2) SageMaker training role with S3 and KMS access, (3) Lambda scoring role with SageMaker InvokeEndpoint and DynamoDB write, (4) Worklist Lambda role with DynamoDB read and downstream queue write. Each scoped to specific resource ARNs.

**VPC and network isolation.** All components that touch claims data must run in a VPC with no internet access. Use VPC endpoints for S3, DynamoDB, SageMaker, CloudWatch Logs, and KMS. Security groups should restrict traffic to minimum required ports between components.

**KMS encryption.** Use customer-managed KMS keys (not AWS-managed) for all data at rest. Separate keys for training data, model artifacts, and prediction storage. Rotate annually. Audit key usage via CloudTrail.

**Testing.** Unit tests for feature engineering logic (the encoding, interaction features, and derived metrics). Integration tests that score a known claim and verify the output format. Load tests for the real-time endpoint (how many concurrent claims per second before latency degrades?). Fairness tests: does model performance vary across patient demographics?

**Threshold calibration.** The thresholds (0.40, 0.70) in this example are arbitrary. Production thresholds need calibration against your specific coder capacity. If you flag 2,000 claims per day but your team can only review 200, you need a higher threshold. If you flag 50 but your team has capacity for 500, lower it. This is an ongoing tuning process, not a one-time setting.

**DynamoDB numeric types.** DynamoDB does not accept Python floats. Convert all numeric values to `Decimal` before calling `put_item`. The `Decimal` import at the top of this file is there for this reason. Wrap prediction probabilities and dollar amounts with `Decimal(str(value))` to avoid `TypeError` at write time.

**Batch vs. real-time tradeoffs.** Real-time scoring (at claim creation) gives instant feedback but costs more (endpoint running 24/7). Batch scoring (nightly) is cheaper but means claims created today don't get scored until tonight. Most organizations start with nightly batch, then add real-time for high-volume billers or specific high-risk procedure categories.

**Multi-class extension.** Binary denied/paid is the starting point. Production systems benefit from predicting the denial reason code (CO-4 coding error, CO-16 missing info, CO-50 medical necessity, CO-197 PA required). This changes the output from "likely denied" to "likely denied for reason X," which is far more actionable. Requires sufficient training examples per reason code.

---

*← [Recipe 7.11: Claim Denial and Prior-Auth Determination Prediction](chapter07.11-claim-denial-prediction) · [Chapter 7 Index](chapter07-preface)*
