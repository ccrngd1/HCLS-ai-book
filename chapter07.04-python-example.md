<!-- TODO (TechWriter): Expert review C1 (CRITICAL). The main recipe file chapter07.04-ed-visit-prediction.md does not exist. Write it following RECIPE-GUIDE.md structure before this recipe pair can pass. The Python companion is ready and references it. -->

# Recipe 7.4: ED Visit Prediction (Python Example)

> **Heads up:** This is a deliberately simplified, illustrative implementation of an ED visit prediction pipeline. It generates synthetic patient data, trains a gradient boosted tree model, and scores patients for 30-day ED visit risk. It is not production-ready. The feature engineering is minimal, the synthetic data is unrealistically clean, and the model evaluation skips half the things you'd need for a real deployment (fairness audits, calibration curves, clinical validation). Think of it as a sketch that shows the shape of the solution. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few standard ML libraries:

```bash
pip install boto3 pandas numpy scikit-learn
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `s3:GetObject`, `s3:PutObject` on your data bucket
- `sagemaker:CreateTrainingJob`, `sagemaker:CreateEndpoint`, `sagemaker:InvokeEndpoint`
- `dynamodb:PutItem`, `dynamodb:Query` on your patient risk score table

For the SageMaker training path, you'll also need a SageMaker execution role with S3 access. This example runs the model locally with scikit-learn for clarity, then shows how you'd deploy via SageMaker.

---

## Config and Constants

These define the feature schema, risk thresholds, and model parameters. They live at the top because they're really configuration decisions, not logic. Readers should see what levers exist before seeing the code that uses them.

```python
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

# ─── Risk Tier Thresholds ───────────────────────────────────────────────────
# These thresholds determine which patients get outreach. They're not magic
# numbers: you calibrate them based on your care management team's capacity.
# If you can only call 200 patients per week, set HIGH_RISK_THRESHOLD so that
# roughly 200 patients land above it in each scoring run.
#
# The gap between medium and high matters operationally. High-risk patients
# get a nurse call within 48 hours. Medium-risk get a mailer and a pharmacy
# check-in. Low-risk get nothing (for now).

HIGH_RISK_THRESHOLD = 0.70    # top tier: proactive nurse outreach
MEDIUM_RISK_THRESHOLD = 0.40  # middle tier: automated outreach
# Below 0.40: no intervention (standard care)

# ─── Feature Configuration ──────────────────────────────────────────────────
# These are the features we'll engineer from claims and clinical data.
# In production, you'd pull these from a feature store. Here we generate
# synthetic versions to demonstrate the pipeline shape.

FEATURE_COLUMNS = [
    "age",
    "ed_visits_last_12m",          # prior ED utilization (strongest signal)
    "ed_visits_last_3m",           # recent acceleration
    "chronic_condition_count",     # comorbidity burden
    "has_diabetes",
    "has_chf",
    "has_copd",
    "has_mental_health_dx",
    "missed_appointments_last_6m", # engagement proxy
    "days_since_last_pcp_visit",   # care continuity gap
    "rx_fills_last_3m",            # medication adherence proxy
    "inpatient_admits_last_12m",   # hospitalization history
    "lives_alone",                 # social isolation (if available)
    "distance_to_nearest_ed_miles",# geographic access
]

# ─── Model Parameters ───────────────────────────────────────────────────────
# Gradient boosted trees work well here because:
# 1. They handle mixed feature types (continuous + binary) without scaling
# 2. They capture non-linear interactions (age + CHF + lives alone)
# 3. They produce feature importance rankings for clinical explainability
# 4. They're robust to missing values (common in claims data)

MODEL_PARAMS = {
    "n_estimators": 200,
    "max_depth": 5,           # shallow trees reduce overfitting on small cohorts
    "learning_rate": 0.1,
    "min_samples_leaf": 20,   # prevents fitting to tiny subgroups
    "subsample": 0.8,         # row sampling for regularization
    "random_state": 42,
}

# ─── Prediction Window ──────────────────────────────────────────────────────
PREDICTION_WINDOW_DAYS = 30  # predict ED visits within next 30 days
```

---

## Step 1: Generate Synthetic Patient Data

*In production, this data comes from your claims warehouse, EHR extracts, and ADT feeds. Here we generate realistic synthetic data to demonstrate the pipeline without touching any real PHI. The distributions are loosely based on published literature on ED utilization patterns.*

```python
def generate_synthetic_patients(n_patients: int = 2000, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic patient data with realistic ED visit patterns.

    The key insight: ED visits cluster. A small percentage of patients account
    for a disproportionate share of ED utilization. Our synthetic data reflects
    this: roughly 15-20% of patients will have the outcome (ED visit in next
    30 days), with prior ED use being the strongest predictor.

    Args:
        n_patients: Number of synthetic patients to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with features and a binary outcome column.
    """
    rng = np.random.default_rng(seed)

    # Age distribution: skewed toward older adults (higher ED utilization)
    age = rng.normal(loc=58, scale=15, size=n_patients).clip(18, 95).astype(int)

    # Chronic conditions: prevalence increases with age
    age_factor = (age - 18) / 77  # normalized 0-1
    has_diabetes = rng.binomial(1, 0.15 + 0.15 * age_factor, n_patients)
    has_chf = rng.binomial(1, 0.05 + 0.12 * age_factor, n_patients)
    has_copd = rng.binomial(1, 0.06 + 0.10 * age_factor, n_patients)
    has_mental_health_dx = rng.binomial(1, 0.20, n_patients)

    chronic_condition_count = has_diabetes + has_chf + has_copd + has_mental_health_dx
    # Add some additional conditions not individually tracked
    chronic_condition_count += rng.poisson(0.5, n_patients)

    # Prior ED utilization: the single strongest predictor of future ED use.
    # Most patients have 0-1 visits. A small group has 4+.
    ed_base_rate = 0.3 + 0.4 * (chronic_condition_count / 6)
    ed_visits_last_12m = rng.poisson(ed_base_rate * 1.5, n_patients)
    ed_visits_last_3m = rng.poisson(ed_base_rate * 0.4, n_patients)
    # Ensure 3-month count doesn't exceed 12-month count
    ed_visits_last_3m = np.minimum(ed_visits_last_3m, ed_visits_last_12m)

    # Care engagement signals
    missed_appointments_last_6m = rng.poisson(0.8, n_patients)
    days_since_last_pcp_visit = rng.exponential(90, n_patients).clip(0, 730).astype(int)
    rx_fills_last_3m = rng.poisson(3 + chronic_condition_count, n_patients)

    # Hospitalization history
    inpatient_admits_last_12m = rng.poisson(0.2 + 0.3 * (chronic_condition_count / 4), n_patients)

    # Social/geographic factors
    lives_alone = rng.binomial(1, 0.25 + 0.15 * (age > 70).astype(float), n_patients)
    distance_to_nearest_ed_miles = rng.exponential(8, n_patients).clip(0.5, 60)

    # ─── Generate outcome (ED visit in next 30 days) ────────────────────────
    # The outcome is driven by a combination of factors with realistic weights.
    # This is NOT how you'd build a real model (that's circular). This just
    # creates a dataset where the features have predictive signal.
    log_odds = (
        -2.5                                          # base rate ~8%
        + 0.6 * ed_visits_last_12m                    # strongest signal
        + 0.9 * ed_visits_last_3m                     # recent acceleration
        + 0.15 * chronic_condition_count
        + 0.3 * has_chf
        + 0.2 * has_copd
        + 0.25 * has_mental_health_dx
        + 0.1 * missed_appointments_last_6m
        + 0.003 * days_since_last_pcp_visit
        - 0.05 * rx_fills_last_3m                     # adherence is protective
        + 0.4 * inpatient_admits_last_12m
        + 0.2 * lives_alone
        + rng.normal(0, 0.5, n_patients)              # noise
    )
    probability = 1 / (1 + np.exp(-log_odds))
    ed_visit_next_30d = rng.binomial(1, probability, n_patients)

    df = pd.DataFrame({
        "patient_id": [f"SYN-{i:06d}" for i in range(n_patients)],
        "age": age,
        "ed_visits_last_12m": ed_visits_last_12m,
        "ed_visits_last_3m": ed_visits_last_3m,
        "chronic_condition_count": chronic_condition_count,
        "has_diabetes": has_diabetes,
        "has_chf": has_chf,
        "has_copd": has_copd,
        "has_mental_health_dx": has_mental_health_dx,
        "missed_appointments_last_6m": missed_appointments_last_6m,
        "days_since_last_pcp_visit": days_since_last_pcp_visit,
        "rx_fills_last_3m": rx_fills_last_3m,
        "inpatient_admits_last_12m": inpatient_admits_last_12m,
        "lives_alone": lives_alone,
        "distance_to_nearest_ed_miles": distance_to_nearest_ed_miles.round(1),
        "ed_visit_next_30d": ed_visit_next_30d,
    })

    return df
```

---

## Step 2: Train the Prediction Model

*This step trains a gradient boosted classifier on historical data. In production, you'd run this on SageMaker with a larger dataset and proper cross-validation. Here we use scikit-learn locally to keep the focus on the pipeline logic rather than infrastructure.*

```python
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    roc_auc_score,
    precision_recall_curve,
    average_precision_score,
    classification_report,
)
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def train_ed_prediction_model(df: pd.DataFrame) -> tuple:
    """
    Train a gradient boosted tree model to predict 30-day ED visits.

    Why gradient boosting over logistic regression? Two reasons:
    1. It captures interactions automatically. A 75-year-old with CHF who
       lives alone is much higher risk than any of those factors individually.
       Logistic regression needs you to manually specify those interactions.
    2. It handles the non-linear relationship between features and risk.
       The jump from 0 to 1 prior ED visits matters more than 5 to 6.

    Why not a neural network? For tabular data with <50 features and <100k rows,
    gradient boosting consistently matches or beats deep learning. It's also
    far easier to explain to clinicians ("prior ED visits was the top factor").

    Args:
        df: DataFrame with features and 'ed_visit_next_30d' outcome column.

    Returns:
        Tuple of (trained_model, X_test, y_test) for evaluation.
    """
    X = df[FEATURE_COLUMNS]
    y = df["ed_visit_next_30d"]

    # 80/20 train/test split. Stratify to maintain outcome ratio in both sets.
    # IMPORTANT: This random split is for demonstration only. In production,
    # you MUST use a temporal split (e.g., train on months 1-9, test on months
    # 10-12). Random splits leak future information and produce optimistically
    # biased AUC estimates for time-dependent outcomes like ED visits. A model
    # that shows AUC 0.82 on a random split may drop to 0.72 on a temporal split.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    logger.info("Training set: %d patients (%d positive, %.1f%% prevalence)",
                len(y_train), y_train.sum(), 100 * y_train.mean())
    logger.info("Test set: %d patients (%d positive, %.1f%% prevalence)",
                len(y_test), y_test.sum(), 100 * y_test.mean())

    # Train the model. GradientBoostingClassifier builds trees sequentially,
    # each one correcting the errors of the previous ensemble.
    model = GradientBoostingClassifier(**MODEL_PARAMS)
    model.fit(X_train, y_train)

    return model, X_test, y_test
```

---

## Step 3: Evaluate Model Performance

*Before deploying any risk model, you need to understand how well it discriminates (AUC), how well it's calibrated (do patients scored at 0.7 actually have ~70% event rates?), and whether it performs equitably across subgroups. This step covers discrimination. Calibration and fairness audits are noted in the gap-to-production section.*

```python
def evaluate_model(model, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
    """
    Evaluate the trained model on held-out test data.

    Key metrics for ED prediction:
    - AUC-ROC: Overall discrimination. How well does the model rank patients?
      An AUC of 0.75+ is typical for ED prediction models in the literature.
    - Average Precision (AUC-PR): More informative than AUC-ROC when the
      outcome is imbalanced (which it always is for ED visits).
    - Precision at the high-risk threshold: Of patients we flag for outreach,
      what fraction actually visits the ED? This drives care manager workload.

    Args:
        model: Trained GradientBoostingClassifier.
        X_test: Test features.
        y_test: Test outcomes.

    Returns:
        Dictionary of evaluation metrics.
    """
    # Get predicted probabilities (not binary predictions).
    # For risk scoring, we always want probabilities. Binary yes/no loses
    # the information about HOW high-risk someone is.
    y_prob = model.predict_proba(X_test)[:, 1]

    # AUC-ROC: probability that a randomly chosen positive patient is scored
    # higher than a randomly chosen negative patient.
    auc_roc = roc_auc_score(y_test, y_prob)

    # Average precision: area under the precision-recall curve.
    # More sensitive to performance on the minority class (ED visitors).
    avg_precision = average_precision_score(y_test, y_prob)

    # TODO (TechWriter): Expert review A3 (MEDIUM). Add a brief calibration
    # check here (sklearn.calibration.calibration_curve) since the risk tiers
    # are probability-based and GBTs produce poorly calibrated probabilities
    # out of the box. Show predicted vs. actual event rates in 5 bins.

    # Apply our operational thresholds to see tier distribution
    high_risk_count = (y_prob >= HIGH_RISK_THRESHOLD).sum()
    medium_risk_count = ((y_prob >= MEDIUM_RISK_THRESHOLD) & (y_prob < HIGH_RISK_THRESHOLD)).sum()
    low_risk_count = (y_prob < MEDIUM_RISK_THRESHOLD).sum()

    # Precision at high-risk threshold: of patients we'd call, how many
    # actually have an ED visit? This is the "positive predictive value"
    # that care managers care about most.
    high_risk_mask = y_prob >= HIGH_RISK_THRESHOLD
    if high_risk_mask.sum() > 0:
        precision_at_high = y_test[high_risk_mask].mean()
    else:
        precision_at_high = 0.0

    # Feature importance: which factors drive the model's predictions?
    # This is critical for clinical buy-in. If the model says "prior ED visits"
    # is the top factor, clinicians nod. If it says "distance to ED" is #1,
    # they'll (rightly) question whether it's capturing access vs. acuity.
    importances = pd.Series(
        model.feature_importances_, index=FEATURE_COLUMNS
    ).sort_values(ascending=False)

    metrics = {
        "auc_roc": round(auc_roc, 4),
        "average_precision": round(avg_precision, 4),
        "precision_at_high_risk": round(precision_at_high, 4),
        "high_risk_count": int(high_risk_count),
        "medium_risk_count": int(medium_risk_count),
        "low_risk_count": int(low_risk_count),
        "top_features": importances.head(5).to_dict(),
    }

    logger.info("AUC-ROC: %.4f", auc_roc)
    logger.info("Average Precision: %.4f", avg_precision)
    logger.info("Precision at high-risk threshold: %.4f", precision_at_high)
    logger.info("Risk tier distribution: %d high / %d medium / %d low",
                high_risk_count, medium_risk_count, low_risk_count)
    logger.info("Top 5 features: %s", importances.head(5).to_dict())

    return metrics
```

---

## Step 4: Score New Patients

*This is the inference step that runs on a schedule (daily or weekly). It takes the trained model and scores the current patient population, assigning each patient a risk tier and generating an outreach list for care management.*

```python
def score_patients(model, patients_df: pd.DataFrame) -> pd.DataFrame:
    """
    Score a batch of patients and assign risk tiers.

    In production, this runs as a scheduled job (daily or weekly). It pulls
    the latest feature values from your feature store, runs inference, and
    writes results to a table that the care management platform reads from.

    The output is an actionable worklist: patient ID, risk score, risk tier,
    and the top contributing factors for that specific patient.

    Args:
        model: Trained model (or SageMaker endpoint in production).
        patients_df: DataFrame with current feature values for each patient.

    Returns:
        DataFrame with risk scores, tiers, and top contributing factors.
    """
    X = patients_df[FEATURE_COLUMNS]

    # Get probability of ED visit in next 30 days
    risk_scores = model.predict_proba(X)[:, 1]

    # Assign risk tiers based on operational thresholds
    def assign_tier(score):
        if score >= HIGH_RISK_THRESHOLD:
            return "HIGH"
        elif score >= MEDIUM_RISK_THRESHOLD:
            return "MEDIUM"
        return "LOW"

    results = patients_df[["patient_id"]].copy()
    results["risk_score"] = risk_scores.round(4)
    results["risk_tier"] = [assign_tier(s) for s in risk_scores]
    results["scored_at"] = datetime.now(timezone.utc).isoformat()
    results["prediction_window_days"] = PREDICTION_WINDOW_DAYS

    # For each patient, identify the top 3 contributing factors.
    # WARNING: This approach (feature_value * global_importance) is dominated
    # by feature scale and produces incorrect per-patient attributions. A patient
    # with age=75 (importance 0.05) gets contribution 3.75, while
    # ed_visits_last_12m=4 (importance 0.30) gets contribution 1.2. The code
    # would incorrectly report "age" as the top factor. Do NOT show these
    # explanations to clinicians. Use SHAP values for any patient-facing or
    # clinician-facing explanations in production.
    feature_importances = model.feature_importances_
    X_min = X.min().values
    X_max = X.max().values
    for idx in results.index:
        patient_features = X.iloc[idx].values
        # Normalize to 0-1 range so feature scale doesn't dominate
        patient_normalized = (patient_features - X_min) / (X_max - X_min + 1e-8)
        contributions = patient_normalized * feature_importances
        top_indices = np.argsort(contributions)[-3:][::-1]
        top_factors = [FEATURE_COLUMNS[i] for i in top_indices]
        results.at[idx, "top_factors"] = ", ".join(top_factors)

    return results
```

---

## Step 5: Store Risk Scores (DynamoDB)

*Risk scores need to be queryable by patient ID (for point-of-care alerts) and by risk tier (for generating outreach worklists). DynamoDB handles both access patterns with a partition key on patient_id and a GSI on risk_tier.*

```python
import boto3
from decimal import Decimal
from botocore.config import Config

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# In a VPC with no internet egress (required for PHI workloads), ensure gateway
# VPC endpoints exist for S3 and DynamoDB, and interface VPC endpoints for
# SageMaker Runtime. Without these, boto3 calls will timeout silently.
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Table name. In production, this comes from environment variables or
# SSM Parameter Store, not hardcoded strings.
RISK_SCORES_TABLE = "ed-risk-scores"


def store_risk_scores(scored_df: pd.DataFrame) -> int:
    """
    Write patient risk scores to DynamoDB for downstream consumption.

    Two consumers read this table:
    1. Care management platform: queries by risk_tier (via GSI) to build
       daily outreach worklists.
    2. EHR integration: queries by patient_id to show risk badges at the
       point of care (e.g., a red flag on the patient chart).

    Args:
        scored_df: DataFrame from score_patients() with risk scores and tiers.

    Returns:
        Number of records written.
    """
    table = dynamodb.Table(RISK_SCORES_TABLE)
    records_written = 0

    # Batch write for efficiency. DynamoDB batch_writer handles chunking
    # into groups of 25 and retries for unprocessed items.
    with table.batch_writer() as batch:
        for _, row in scored_df.iterrows():
            # Only store medium and high risk patients. Low-risk patients
            # don't need to be in the outreach table (saves cost and keeps
            # the worklist focused).
            if row["risk_tier"] == "LOW":
                continue

            item = {
                "patient_id": row["patient_id"],
                "risk_score": Decimal(str(row["risk_score"])),
                "risk_tier": row["risk_tier"],
                "scored_at": row["scored_at"],
                "prediction_window_days": PREDICTION_WINDOW_DAYS,
                "top_factors": row["top_factors"],
                # TTL: auto-expire records after the prediction window passes.
                # No point keeping a "30-day risk" score that's 45 days old.
                "ttl": int(
                    (datetime.now(timezone.utc) + timedelta(days=PREDICTION_WINDOW_DAYS)).timestamp()
                ),
            }

            batch.put_item(Item=item)
            records_written += 1

    logger.info("Wrote %d risk scores to DynamoDB (medium + high risk only)",
                records_written)
    return records_written
```

---

## Step 6: Upload Training Data to S3 (for SageMaker)

*When you're ready to move from local scikit-learn to SageMaker training (larger datasets, GPU instances, automated retraining), you'll need your data in S3. This step shows the handoff.*

```python
import io

s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

DATA_BUCKET = "my-healthcare-ml-data"
MODEL_PREFIX = "ed-prediction/v1"


def upload_training_data(df: pd.DataFrame, bucket: str = DATA_BUCKET) -> str:
    """
    Upload training data to S3 in CSV format for SageMaker consumption.

    SageMaker's built-in XGBoost algorithm expects CSV with the target column
    first and no header row. So that's what we give it.

    Args:
        df: Training DataFrame with features and outcome.
        bucket: S3 bucket for ML artifacts.

    Returns:
        S3 URI of the uploaded training data.
    """
    # SageMaker XGBoost expects: target_column, feature_1, feature_2, ...
    # No header row. Target must be first column.
    columns_ordered = ["ed_visit_next_30d"] + FEATURE_COLUMNS
    training_data = df[columns_ordered]

    # Write to CSV in memory, then upload
    csv_buffer = io.StringIO()
    training_data.to_csv(csv_buffer, index=False, header=False)

    s3_key = f"{MODEL_PREFIX}/train/training_data.csv"
    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=csv_buffer.getvalue().encode("utf-8"),
        ServerSideEncryption="aws:kms",  # encrypt at rest with KMS
    )

    s3_uri = f"s3://{bucket}/{s3_key}"
    logger.info("Uploaded training data to %s", s3_uri)
    return s3_uri
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable flow. This demonstrates the end-to-end sequence from data generation through scoring and storage.

```python
def run_ed_prediction_pipeline():
    """
    Run the complete ED visit prediction pipeline.

    In production, this would be split across multiple components:
    - Training: SageMaker training job (runs weekly or monthly)
    - Scoring: Lambda or SageMaker batch transform (runs daily)
    - Storage: DynamoDB write (part of scoring job)

    Here we run everything sequentially for demonstration.
    """
    print("=" * 60)
    print("ED Visit Prediction Pipeline")
    print("=" * 60)

    # Step 1: Generate synthetic patient data
    print("\n[Step 1] Generating synthetic patient data...")
    df = generate_synthetic_patients(n_patients=2000)
    print(f"  Generated {len(df)} patients")
    print(f"  ED visit rate (outcome): {df['ed_visit_next_30d'].mean():.1%}")

    # Step 2: Train the model
    print("\n[Step 2] Training gradient boosted model...")
    model, X_test, y_test = train_ed_prediction_model(df)
    print("  Training complete.")

    # Step 3: Evaluate
    print("\n[Step 3] Evaluating model performance...")
    metrics = evaluate_model(model, X_test, y_test)
    print(f"  AUC-ROC: {metrics['auc_roc']}")
    print(f"  Average Precision: {metrics['average_precision']}")
    print(f"  Precision at high-risk: {metrics['precision_at_high_risk']}")
    print(f"  Risk tiers: {metrics['high_risk_count']} high / "
          f"{metrics['medium_risk_count']} medium / {metrics['low_risk_count']} low")
    print(f"  Top features: {list(metrics['top_features'].keys())}")

    # Step 4: Score a new batch of patients (simulating daily scoring run)
    print("\n[Step 4] Scoring patient population...")
    # In production, you'd pull fresh feature values here.
    # For demo, we score the test set as if they're today's population.
    scoring_df = df.iloc[X_test.index].copy()
    scored = score_patients(model, scoring_df)
    print(f"  Scored {len(scored)} patients")
    print(f"  High risk: {(scored['risk_tier'] == 'HIGH').sum()}")
    print(f"  Medium risk: {(scored['risk_tier'] == 'MEDIUM').sum()}")

    # Show sample high-risk patients (the outreach worklist)
    high_risk = scored[scored["risk_tier"] == "HIGH"].sort_values(
        "risk_score", ascending=False
    ).head(5)
    print("\n  Sample high-risk patients (top 5):")
    for _, row in high_risk.iterrows():
        print(f"    {row['patient_id']}: score={row['risk_score']:.3f}, "
              f"factors=[{row['top_factors']}]")

    # Step 5: Store results (uncomment when DynamoDB table exists)
    # print("\n[Step 5] Storing risk scores in DynamoDB...")
    # records = store_risk_scores(scored)
    # print(f"  Wrote {records} records")

    # Step 6: Upload training data to S3 (uncomment when bucket exists)
    # print("\n[Step 6] Uploading training data to S3...")
    # s3_uri = upload_training_data(df)
    # print(f"  Uploaded to {s3_uri}")

    print("\n" + "=" * 60)
    print("Pipeline complete.")
    print("=" * 60)

    return metrics, scored


# Run the pipeline
if __name__ == "__main__":
    metrics, scored = run_ed_prediction_pipeline()
```

---

## The Gap Between This and Production

This example trains a model, scores patients, and produces an outreach worklist. It works. But there's a meaningful distance between "runs in a notebook" and "drives clinical interventions for 50,000 patients." Here's where that gap lives:

**Feature engineering from raw data.** This example starts with pre-computed features. A real pipeline starts with raw claims (837/835 files), ADT feeds, pharmacy data, and EHR extracts. The feature engineering layer (computing "ED visits in last 12 months" from individual claim records) is often 80% of the work. You'd typically use a feature store (SageMaker Feature Store or a custom solution on Athena/Glue) to maintain point-in-time-correct features.

**Synthetic data performance is not a benchmark.** This synthetic data produces artificially high AUC because the outcome was generated from the same features the model uses. Real-world ED prediction models typically achieve AUC 0.70-0.78 due to unmeasured confounders, data quality issues, and temporal drift. Don't use synthetic-data performance as a benchmark for production readiness.

**Temporal validation.** We used a random train/test split. In production, you must validate temporally: train on data from months 1-9, test on months 10-12. Random splits leak future information and produce optimistic AUC estimates. A model that looks great on random splits can fail badly when deployed forward in time.

**Calibration.** Our model outputs probabilities, but are they calibrated? If the model says "0.70 risk," do 70% of those patients actually visit the ED? Calibration matters because care managers make resource allocation decisions based on these numbers. Use Platt scaling or isotonic regression to calibrate, and plot reliability diagrams to verify.

**Fairness and bias auditing.** ED prediction models can encode existing disparities. If Black patients historically face longer wait times and are more likely to leave without being seen (not counted as an "ED visit"), the model learns a lower baseline for that group. You must evaluate AUC, calibration, and false negative rates across demographic subgroups. SageMaker Clarify provides bias detection, but you still need to decide what to do when you find disparities.

**SHAP values for explainability.** The "top factors" approach in Step 4 is a rough approximation. For clinical deployment, use SHAP (SHapley Additive exPlanations) to generate proper per-patient feature attributions. Clinicians need to understand why a specific patient was flagged, not just that they were.

**Model monitoring and drift detection.** Patient populations change. New chronic disease codes get introduced. Flu season shifts utilization patterns. You need automated monitoring that tracks prediction distribution, feature distributions, and actual vs. predicted rates over time. SageMaker Model Monitor handles this, but you still need to define what "drift" means for your use case and what action to take when it's detected.

**Retraining cadence.** How often do you retrain? Monthly is typical for ED prediction. You need an automated pipeline (SageMaker Pipelines or Step Functions) that retrains, evaluates against the current production model, and promotes the new version only if it improves on key metrics.

**Integration with care management workflows.** The DynamoDB table is just storage. The real integration is with whatever system your care managers use to manage their worklists. That might be an Epic BPA (Best Practice Alert), a Salesforce Health Cloud task, or a custom outreach platform. The "last mile" of getting a risk score into a clinician's workflow is often harder than building the model.

**Consumer-specific field access.** The `top_factors` field exposes behavioral and social determinant data (e.g., "lives_alone"). An EHR risk badge showing this to patients in a portal may be inappropriate. Consider separating detailed explanations into a DynamoDB attribute that requires elevated IAM permissions. The EHR badge may only need `risk_tier` (HIGH/MEDIUM/LOW), while care managers need the full explanation. Use IAM conditions or application-layer filtering to restrict field access by consumer identity.

**Consent and opt-out.** Some patients may opt out of predictive analytics or proactive outreach. Your scoring pipeline needs to respect those preferences, which means checking a consent registry before writing scores and before triggering outreach.

**Error handling and retries.** If the feature store query fails mid-batch, do you skip those patients (dangerous: they might be high-risk) or retry (could delay the entire scoring run)? If DynamoDB throttles during the write, do stale scores remain visible to care managers? These operational edge cases matter when the system runs daily at scale.

**IAM least-privilege.** The scoring Lambda needs `sagemaker:InvokeEndpoint` for the specific endpoint ARN, `dynamodb:PutItem` and `dynamodb:BatchWriteItem` for the specific table, and `s3:GetObject` for the feature data. Not `sagemaker:*`. Not `AmazonDynamoDBFullAccess`. Split into separate roles: a SageMaker execution role (S3 read/write on model bucket, KMS decrypt), a scoring role (InvokeEndpoint, DynamoDB write), and a data upload role (S3 PutObject on training prefix only).

**DynamoDB encryption for PHI.** DynamoDB encrypts at rest by default with an AWS-owned key. For PHI tables (like `ed-risk-scores`, which stores patient_id linked to health predictions), use a customer-managed KMS key (CMK) to maintain control over key rotation, access policies, and CloudTrail audit of key usage. Specify this when creating the table, not after.

**VPC and network isolation.** Patient data (even derived risk scores) is PHI. The scoring job runs in a private subnet with VPC endpoints for SageMaker, DynamoDB, and S3. No internet egress. CloudTrail logs every API call for the audit trail.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 7.4](chapter07.04-ed-visit-prediction) for the full architectural walkthrough, pseudocode, and honest take on where ED prediction gets complicated.*
