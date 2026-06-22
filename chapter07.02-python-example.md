# Recipe 7.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 7.2. It shows one way you could translate those concepts into working Python code using boto3 and SageMaker. It is not production-ready. There's no error handling, no retry logic, no input validation, and the synthetic data is intentionally small. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a revenue cycle system on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few data science libraries:

```bash
pip install boto3 pandas numpy sagemaker
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs permissions for SageMaker (training jobs, batch transform), S3 (read/write to your ML data bucket), DynamoDB (PutItem, Query), and Lambda (if deploying the strategy engine).

For SageMaker specifically, you'll need a SageMaker execution role that the training and transform jobs assume. This role needs S3 access to your data bucket and permission to write CloudWatch logs.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the pipeline. These values live at the top of your module so they're easy to find and adjust when you tune the model or change operational thresholds.

```python
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
import numpy as np
import pandas as pd
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI field values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry configuration for AWS API calls. Adaptive mode uses exponential
# backoff with jitter, which handles burst throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# S3 bucket and prefixes for the ML pipeline.
# In production, these come from environment variables or SSM Parameter Store.
ML_BUCKET = "my-propensity-to-pay-pipeline"
FEATURES_PREFIX = "features/open-balances/"
TRAINING_PREFIX = "features/training/"
MODELS_PREFIX = "models/propensity-to-pay/"
PREDICTIONS_PREFIX = "predictions/propensity-to-pay/"

# DynamoDB table for storing predictions.
PREDICTIONS_TABLE = "balance-predictions"

# SageMaker configuration.
SAGEMAKER_ROLE = "arn:aws:iam::123456789012:role/SageMakerExecutionRole"
TRAINING_INSTANCE_TYPE = "ml.m5.xlarge"
TRANSFORM_INSTANCE_TYPE = "ml.m5.large"

# Strategy engine thresholds. These are business decisions, not model decisions.
# Tune based on your collection staff capacity, payment plan administrative
# costs, and financial assistance policies.
HIGH_PROPENSITY_THRESHOLD = 0.75   # above this: patient will likely pay without intervention
MEDIUM_PROPENSITY_THRESHOLD = 0.40  # between medium and high: intervention may help
# below medium: likely needs financial assistance or will not pay

# XGBoost hyperparameters for training.
# These are reasonable defaults for a propensity-to-pay dataset.
# Slightly shallower trees than no-show prediction because payment
# behavior tends to be less non-linear (history dominates).
XGBOOST_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "auc",
    "num_round": "300",
    "max_depth": "5",
    "eta": "0.05",
    "subsample": "0.8",
    "colsample_bytree": "0.7",
    "scale_pos_weight": "0.67",  # adjust for your actual pay rate
                                  # if ~60% pay: weight = (1-0.6)/0.6 ≈ 0.67
}

# Outcome definition: "paid" means paid in full within this many days.
# This is a design choice. Talk to your revenue cycle leadership about
# what decision they're actually trying to make before changing this.
OUTCOME_WINDOW_DAYS = 90
```

---

## Step 1: Generate Synthetic Training Data

*The main recipe's Step 1 is feature engineering from billing systems. Since we don't have a real billing system here, we'll generate synthetic data that mimics the feature distributions you'd see in a real health system. This gives you something to train against and demonstrates the feature schema.*

```python
def generate_synthetic_balance_data(n_balances: int = 5000, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic patient balance data for model training.

    In production, this data comes from your billing system, patient accounting,
    EHR demographics, and portal engagement data via a Glue ETL job. Here we
    simulate realistic distributions so you can see the pipeline work end-to-end.

    The key insight: payment behavior is heavily driven by patient history and
    balance amount. We simulate that relationship so the model has something
    real to learn.

    Args:
        n_balances: Number of synthetic balance records to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with features and a binary outcome label (paid_within_90_days).
    """
    rng = np.random.default_rng(seed)

    # --- Patient Payment History Features ---
    # The strongest predictor. Patients with high historical pay rates
    # continue to pay. Patients who ignore bills continue to ignore them.
    # We simulate a bimodal distribution: most patients either pay reliably
    # or don't pay at all, with some in the middle.
    pay_rate_full = rng.beta(2, 1.5, size=n_balances)  # skewed toward paying

    # "Any payment" rate is always >= full payment rate.
    # Some patients make partial payments even when they don't pay in full.
    pay_rate_any = np.minimum(pay_rate_full + rng.uniform(0, 0.2, size=n_balances), 1.0)

    # Average days to first payment. Fast payers cluster around 10-20 days.
    # Slow payers cluster around 60-90 days.
    avg_days_to_first_payment = rng.gamma(3, 15, size=n_balances).clip(5, 120)

    # Payment plan history.
    payment_plans_completed = rng.poisson(1.0, size=n_balances).clip(0, 5)
    payment_plans_defaulted = rng.poisson(0.3, size=n_balances).clip(0, 3)

    # --- Balance Characteristics ---
    # Amount follows a log-normal distribution in healthcare.
    # Most balances are small (copays, small deductibles), but there's a
    # long tail of large surgical/procedure balances.
    balance_amount = rng.lognormal(mean=4.5, sigma=1.2, size=n_balances).clip(10, 25000)
    balance_amount_log = np.log(balance_amount + 1)

    # Balance age: how many days since the balance was created.
    balance_age_days = rng.integers(1, 180, size=n_balances)

    # Service type: 0=routine, 1=elective, 2=emergency
    service_type = rng.choice([0, 1, 2], size=n_balances, p=[0.5, 0.3, 0.2])

    # Has insurance already adjudicated this claim?
    insurance_adjudicated = rng.choice([0, 1], size=n_balances, p=[0.2, 0.8])

    # Number of statements sent (correlates with balance age).
    statements_sent = (balance_age_days // 30).clip(1, 6)

    # --- Insurance and Financial Context ---
    # Insurance type: 0=commercial, 1=medicare, 2=medicaid, 3=self-pay
    insurance_type = rng.choice([0, 1, 2, 3], size=n_balances, p=[0.45, 0.25, 0.15, 0.15])

    # Does this patient have other open balances?
    has_other_open_balances = rng.choice([0, 1], size=n_balances, p=[0.6, 0.4])

    # Total open balance across all accounts for this patient.
    total_open_balance = balance_amount * (1 + has_other_open_balances * rng.uniform(0.5, 3.0, size=n_balances))

    # --- Engagement Signals ---
    # Days since last portal login. Active patients log in frequently.
    days_since_portal_login = rng.exponential(30, size=n_balances).clip(0, 365).astype(int)

    # Did they open the last electronic statement?
    opened_last_statement = rng.choice([0, 1], size=n_balances, p=[0.4, 0.6])

    # Called billing recently? (Counterintuitively predictive of payment.)
    called_billing_recently = rng.choice([0, 1], size=n_balances, p=[0.85, 0.15])

    # Made any partial payment on this balance?
    partial_payment_made = rng.choice([0, 1], size=n_balances, p=[0.75, 0.25])

    # --- Generate the outcome label ---
    # The probability of paying is a function of the features above.
    # This simulates the real-world relationship the model will learn.
    pay_probability = (
        0.35 * pay_rate_full                          # history is king
        + 0.10 * pay_rate_any                         # any-payment history helps
        - 0.08 * (balance_amount_log / 10)            # larger balances less likely
        - 0.06 * (balance_age_days / 180)             # older balances less likely
        + 0.05 * insurance_adjudicated                # clarity helps
        + 0.04 * opened_last_statement                # engagement signal
        + 0.03 * called_billing_recently              # engagement signal
        + 0.08 * partial_payment_made                 # strong signal
        - 0.03 * (days_since_portal_login / 365)      # disengagement hurts
        - 0.02 * has_other_open_balances              # financial stress
        + 0.10                                        # base rate offset
    )
    # Clip to valid probability range and add noise.
    pay_probability = np.clip(pay_probability + rng.normal(0, 0.08, size=n_balances), 0.02, 0.98)

    # Binary outcome: did the patient pay within 90 days?
    paid_within_90_days = (rng.random(size=n_balances) < pay_probability).astype(int)

    # Assemble the DataFrame.
    df = pd.DataFrame({
        "pay_rate_full": pay_rate_full.round(3),
        "pay_rate_any": pay_rate_any.round(3),
        "avg_days_to_first_payment": avg_days_to_first_payment.round(1),
        "payment_plans_completed": payment_plans_completed,
        "payment_plans_defaulted": payment_plans_defaulted,
        "balance_amount": balance_amount.round(2),
        "balance_amount_log": balance_amount_log.round(4),
        "balance_age_days": balance_age_days,
        "service_type": service_type,
        "insurance_adjudicated": insurance_adjudicated,
        "statements_sent": statements_sent,
        "insurance_type": insurance_type,
        "has_other_open_balances": has_other_open_balances,
        "total_open_balance": total_open_balance.round(2),
        "days_since_portal_login": days_since_portal_login,
        "opened_last_statement": opened_last_statement,
        "called_billing_recently": called_billing_recently,
        "partial_payment_made": partial_payment_made,
        "paid_within_90_days": paid_within_90_days,
    })

    logger.info("Generated %d synthetic balances. Pay rate: %.1f%%",
                n_balances, paid_within_90_days.mean() * 100)
    return df
```

---

## Step 2: Upload Training Data to S3

*Before SageMaker can train a model, the data needs to be in S3. SageMaker's XGBoost algorithm expects CSV format with no header row and the label column first. This is a quirk of the built-in algorithm; if you use a custom training container, you can use whatever format you want.*

```python
import io

s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

def upload_training_data(df: pd.DataFrame) -> tuple[str, str]:
    """
    Split data into train/validation sets and upload to S3 in the format
    SageMaker's built-in XGBoost expects.

    SageMaker XGBoost wants:
    - CSV format, no header row
    - Label column FIRST (before features)
    - Train and validation as separate files (for early stopping)

    Args:
        df: Full training DataFrame with features and label.

    Returns:
        Tuple of (train_s3_uri, validation_s3_uri).
    """
    # Shuffle and split: 80% train, 20% validation.
    # The validation set is used for early stopping during training
    # (stop adding trees when validation AUC stops improving).
    df_shuffled = df.sample(frac=1, random_state=42).reset_index(drop=True)
    split_idx = int(len(df_shuffled) * 0.8)
    train_df = df_shuffled.iloc[:split_idx]
    val_df = df_shuffled.iloc[split_idx:]

    # Move label column to the front (SageMaker XGBoost requirement).
    label_col = "paid_within_90_days"
    feature_cols = [c for c in df.columns if c != label_col]
    col_order = [label_col] + feature_cols

    # Upload train set.
    train_csv = train_df[col_order].to_csv(index=False, header=False)
    train_key = f"{TRAINING_PREFIX}train/train.csv"
    s3_client.put_object(Bucket=ML_BUCKET, Key=train_key, Body=train_csv.encode())

    # Upload validation set.
    val_csv = val_df[col_order].to_csv(index=False, header=False)
    val_key = f"{TRAINING_PREFIX}validation/validation.csv"
    s3_client.put_object(Bucket=ML_BUCKET, Key=val_key, Body=val_csv.encode())

    train_uri = f"s3://{ML_BUCKET}/{TRAINING_PREFIX}train/"
    val_uri = f"s3://{ML_BUCKET}/{TRAINING_PREFIX}validation/"

    logger.info("Uploaded %d training rows to %s", len(train_df), train_uri)
    logger.info("Uploaded %d validation rows to %s", len(val_df), val_uri)

    return train_uri, val_uri
```

---

## Step 3: Train the XGBoost Model on SageMaker

*The pseudocode calls this `train_propensity_model`. We launch a SageMaker training job using the built-in XGBoost algorithm. The job reads training data from S3, trains a gradient-boosted tree classifier, and writes the model artifact back to S3. The key hyperparameters are configured for a propensity-to-pay problem: slightly shallower trees and a conservative learning rate because payment behavior is less non-linear than other prediction problems (history dominates).*

```python
import sagemaker
from sagemaker.estimator import Estimator
from sagemaker.inputs import TrainingInput

def train_propensity_model(train_uri: str, val_uri: str) -> str:
    """
    Launch a SageMaker training job for the propensity-to-pay model.

    Uses the built-in XGBoost algorithm, which is optimized for tabular
    binary classification. The model learns which feature patterns predict
    payment within 90 days.

    Args:
        train_uri: S3 URI for the training data.
        val_uri: S3 URI for the validation data.

    Returns:
        S3 URI of the trained model artifact (a tar.gz file containing
        the serialized XGBoost model).
    """
    # Get the XGBoost container image URI for the current region.
    # SageMaker maintains pre-built containers for each supported algorithm.
    session = sagemaker.Session()
    region = session.boto_region_name
    xgboost_image = sagemaker.image_uris.retrieve(
        framework="xgboost",
        region=region,
        version="1.7-1",  # use a recent stable version
    )

    # Create the estimator (the training job configuration).
    estimator = Estimator(
        image_uri=xgboost_image,
        role=SAGEMAKER_ROLE,
        instance_count=1,
        instance_type=TRAINING_INSTANCE_TYPE,
        output_path=f"s3://{ML_BUCKET}/{MODELS_PREFIX}",
        sagemaker_session=session,
        # Encrypt the training volume. In production, use a CMK ARN here.
        volume_kms_key=None,  # TODO: replace with your KMS CMK ARN
    )

    # Set hyperparameters. These control how the model learns.
    estimator.set_hyperparameters(**XGBOOST_PARAMS)

    # Define the input channels. SageMaker XGBoost expects "train" and
    # optionally "validation" channels for early stopping.
    train_input = TrainingInput(train_uri, content_type="text/csv")
    val_input = TrainingInput(val_uri, content_type="text/csv")

    # Launch the training job. This is asynchronous by default, but
    # .fit() with wait=True blocks until the job completes.
    logger.info("Starting SageMaker training job...")
    estimator.fit(
        inputs={"train": train_input, "validation": val_input},
        wait=True,
        logs="All",  # stream training logs to this console
    )

    model_artifact_uri = estimator.model_data
    logger.info("Training complete. Model artifact: %s", model_artifact_uri)
    return model_artifact_uri
```

---

## Step 4: Score Open Balances with Batch Transform

*The pseudocode calls this `score_open_balances`. Instead of deploying a persistent endpoint (which costs money 24/7), we use SageMaker Batch Transform to score all open balances in a single job. This is the right pattern when you don't need sub-second latency. Nightly scoring is fine for collection strategy decisions.*

```python
from sagemaker.transformer import Transformer

def prepare_scoring_input(df: pd.DataFrame) -> str:
    """
    Prepare open balances for scoring and upload to S3.

    The scoring input is the same feature set as training, but without
    the label column (we're predicting that). We also keep balance_id
    and patient_id in a separate lookup file so we can join predictions
    back to the original records.

    Args:
        df: DataFrame of open balances with features (no label column needed).

    Returns:
        S3 URI of the scoring input file.
    """
    # For scoring, we need features only (no label column).
    label_col = "paid_within_90_days"
    feature_cols = [c for c in df.columns if c != label_col]

    # Save the feature-only CSV for batch transform.
    scoring_csv = df[feature_cols].to_csv(index=False, header=False)
    scoring_key = f"{FEATURES_PREFIX}scoring-input.csv"
    s3_client.put_object(Bucket=ML_BUCKET, Key=scoring_key, Body=scoring_csv.encode())

    scoring_uri = f"s3://{ML_BUCKET}/{scoring_key}"
    logger.info("Uploaded %d balances for scoring to %s", len(df), scoring_uri)
    return scoring_uri

def run_batch_scoring(model_artifact_uri: str, scoring_input_uri: str) -> str:
    """
    Run SageMaker Batch Transform to score all open balances.

    Batch Transform spins up inference instances, runs every record through
    the model, writes predictions to S3, and shuts down. You only pay for
    the time the instances are running. For 100K balances, this typically
    takes 10-15 minutes on an ml.m5.large.

    Args:
        model_artifact_uri: S3 URI of the trained model artifact.
        scoring_input_uri: S3 URI of the scoring input CSV.

    Returns:
        S3 URI of the output predictions.
    """
    session = sagemaker.Session()
    region = session.boto_region_name
    xgboost_image = sagemaker.image_uris.retrieve(
        framework="xgboost",
        region=region,
        version="1.7-1",
    )

    # Create a SageMaker Model object from the training artifact.
    model = sagemaker.model.Model(
        image_uri=xgboost_image,
        model_data=model_artifact_uri,
        role=SAGEMAKER_ROLE,
        sagemaker_session=session,
    )

    # Configure the batch transform job.
    output_prefix = f"{PREDICTIONS_PREFIX}{datetime.date.today().isoformat()}/"
    output_uri = f"s3://{ML_BUCKET}/{output_prefix}"

    transformer = model.transformer(
        instance_count=1,
        instance_type=TRANSFORM_INSTANCE_TYPE,
        output_path=output_uri,
        accept="text/csv",
        strategy="MultiRecord",   # batch records together for throughput
        max_payload=6,            # MB per batch (SageMaker default is 6)
    )

    # Launch the transform job.
    logger.info("Starting batch transform job...")
    transformer.transform(
        data=scoring_input_uri,
        content_type="text/csv",
        split_type="Line",
        wait=True,
        logs=True,
    )

    logger.info("Batch transform complete. Predictions at: %s", output_uri)
    return output_uri
```

---

## Step 5: Apply Calibration and Store Predictions

*The pseudocode mentions Platt scaling for calibration. XGBoost's raw probabilities are often poorly calibrated: a predicted 0.7 might not actually mean 70% of those balances get paid. Calibration fixes this so the strategy engine's thresholds are meaningful. Here we demonstrate a simple isotonic regression calibration using the validation set, then write calibrated scores to DynamoDB.*

```python
from sklearn.isotonic import IsotonicRegression

dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

def fit_calibration_model(val_predictions: np.ndarray, val_labels: np.ndarray) -> IsotonicRegression:
    """
    Fit a calibration model (isotonic regression) on the validation set.

    Why calibration matters: the strategy engine uses probability thresholds
    to route balances. If the model says 0.75 but the true rate is 0.60,
    you'll under-intervene on balances that actually need help. Calibration
    ensures that predicted probabilities match observed frequencies.

    Isotonic regression is non-parametric and tends to work better than
    Platt scaling when the calibration curve is non-monotonic (which happens
    with XGBoost more often than you'd expect).

    Args:
        val_predictions: Raw model probabilities on the validation set.
        val_labels: True binary labels for the validation set.

    Returns:
        Fitted IsotonicRegression model.
    """
    calibrator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    calibrator.fit(val_predictions, val_labels)
    logger.info("Calibration model fitted on %d validation samples", len(val_labels))
    return calibrator

def store_predictions_in_dynamodb(
    balance_ids: list[str],
    patient_ids: list[str],
    calibrated_scores: np.ndarray,
    balance_amounts: np.ndarray,
    model_version: str,
) -> int:
    """
    Write calibrated propensity scores to DynamoDB for downstream consumption.

    The strategy engine and collection workflow read from this table to
    decide how to handle each balance. Each record includes the score,
    the assigned strategy tier, and metadata for audit.

    Args:
        balance_ids: List of balance identifiers.
        patient_ids: List of patient identifiers.
        calibrated_scores: Array of calibrated probabilities (0.0 to 1.0).
        balance_amounts: Array of balance dollar amounts.
        model_version: Version string for the model that produced these scores.

    Returns:
        Number of records written.
    """
    table = dynamodb.Table(PREDICTIONS_TABLE)
    score_date = datetime.date.today().isoformat()
    records_written = 0

    # Batch write for efficiency. DynamoDB batch_writer handles chunking
    # into 25-item batches and retries for unprocessed items.
    with table.batch_writer() as batch:
        for i in range(len(balance_ids)):
            score = float(calibrated_scores[i])

            # Determine strategy tier based on thresholds.
            if score >= HIGH_PROPENSITY_THRESHOLD:
                strategy = "standard_statements"
            elif score >= MEDIUM_PROPENSITY_THRESHOLD:
                if balance_amounts[i] > 500:
                    strategy = "financial_counselor_outreach"
                else:
                    strategy = "payment_plan_offer"
            else:
                strategy = "financial_assistance_screening"

            item = {
                "balance_id": balance_ids[i],
                "patient_id": patient_ids[i],
                "propensity_score": Decimal(str(round(score, 4))),
                # DynamoDB does not accept Python floats. You must wrap
                # numeric values in Decimal() or put_item will raise a
                # TypeError. str() first to avoid floating-point artifacts.
                "score_date": score_date,
                "model_version": model_version,
                "assigned_strategy": strategy,
                "balance_amount": Decimal(str(round(float(balance_amounts[i]), 2))),
            }

            batch.put_item(Item=item)
            records_written += 1

    logger.info("Wrote %d predictions to DynamoDB table '%s'",
                records_written, PREDICTIONS_TABLE)
    return records_written
```

---

## Step 6: Strategy Engine

*The pseudocode calls this `apply_collection_strategy`. In production, this runs as a Lambda function triggered by EventBridge after the nightly scoring completes. It reads predictions from DynamoDB and routes each balance to the appropriate collection queue. Here we show the routing logic as a standalone function.*

```python
def apply_collection_strategy(predictions: list[dict]) -> dict:
    """
    Route scored balances to collection strategy queues based on propensity.

    This is the strategy engine. It takes model predictions and turns them
    into operational decisions. The thresholds are business parameters:
    adjust them based on your staff capacity, payment plan costs, and
    financial assistance policies.

    Includes a randomization holdout: ~7% of balances get randomly assigned
    to a strategy regardless of their score. This creates counterfactual data
    to validate that model-driven routing actually outperforms random assignment
    and prevents self-fulfilling prophecy (if you never contact low-score patients,
    you can never learn whether they would have paid with outreach).

    In production, this function runs in Lambda and writes routing decisions
    to an SQS queue or directly updates the collection workflow system.

    Args:
        predictions: List of prediction dicts from DynamoDB, each containing
                     balance_id, propensity_score, balance_amount, etc.

    Returns:
        Summary dict with counts per strategy queue and holdout count.
    """
    import hashlib
    import random

    HOLDOUT_RATE = 0.07  # 7% of balances get random assignment
    ALL_STRATEGIES = [
        "standard_statements",
        "payment_plan_offer",
        "financial_counselor_outreach",
        "financial_assistance_screening",
    ]

    routing_summary = {s: 0 for s in ALL_STRATEGIES}
    routing_summary["holdout_count"] = 0
    score_date = datetime.date.today().isoformat()

    for pred in predictions:
        score = float(pred["propensity_score"])
        amount = float(pred["balance_amount"])
        balance_id = pred["balance_id"]

        # Deterministic holdout assignment: hash(balance_id + date) ensures
        # the same balance gets the same holdout decision if re-run on the
        # same day, but different decisions across days.
        holdout_hash = int(hashlib.sha256(
            f"{balance_id}{score_date}".encode()
        ).hexdigest(), 16) % 100
        is_holdout = holdout_hash < (HOLDOUT_RATE * 100)

        if is_holdout:
            strategy = random.choice(ALL_STRATEGIES)
            routing_summary[strategy] += 1
            routing_summary["holdout_count"] += 1
            logger.debug("Balance %s (score=%.3f) -> %s [HOLDOUT]",
                         balance_id, score, strategy)
            continue

        if score >= HIGH_PROPENSITY_THRESHOLD:
            # High propensity: standard statement cadence.
            # These patients typically pay without special intervention.
            strategy = "standard_statements"

        elif score >= MEDIUM_PROPENSITY_THRESHOLD:
            # Medium propensity: proactive intervention likely to help.
            if amount > 500:
                strategy = "financial_counselor_outreach"
            else:
                strategy = "payment_plan_offer"

        else:
            # Low propensity: likely unable to pay.
            # Screen for financial assistance eligibility early.
            strategy = "financial_assistance_screening"

        routing_summary[strategy] += 1

        # In production, you'd write this to SQS, update the billing system,
        # or call an API on your collection workflow tool.
        logger.debug("Balance %s (score=%.3f, amount=$%.2f) -> %s",
                     balance_id, score, amount, strategy)

    return routing_summary
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your orchestration (EventBridge + Step Functions, or a simple script) would call.

```python
def run_propensity_pipeline():
    """
    Run the full propensity-to-pay pipeline end-to-end.

    In production, Steps 1-2 are a Glue job (pulling from real billing data).
    Step 3 runs monthly (retraining). Steps 4-6 run nightly (scoring and routing).
    Here we run everything sequentially for demonstration.
    """

    # Step 1: Generate synthetic data (in production: Glue ETL from billing system).
    logger.info("=" * 60)
    logger.info("Step 1: Generating synthetic balance data")
    logger.info("=" * 60)
    df = generate_synthetic_balance_data(n_balances=5000)
    print(f"  Generated {len(df)} balances. Pay rate: {df['paid_within_90_days'].mean():.1%}")

    # Step 2: Upload training data to S3.
    logger.info("=" * 60)
    logger.info("Step 2: Uploading training data to S3")
    logger.info("=" * 60)
    train_uri, val_uri = upload_training_data(df)
    print(f"  Train: {train_uri}")
    print(f"  Validation: {val_uri}")

    # Step 3: Train the model.
    logger.info("=" * 60)
    logger.info("Step 3: Training XGBoost model on SageMaker")
    logger.info("=" * 60)
    model_artifact_uri = train_propensity_model(train_uri, val_uri)
    print(f"  Model artifact: {model_artifact_uri}")

    # Step 4: Score open balances.
    # For this demo, we'll score the same data (minus the label).
    # In production, you'd score only currently-open balances.
    logger.info("=" * 60)
    logger.info("Step 4: Scoring open balances with batch transform")
    logger.info("=" * 60)
    scoring_uri = prepare_scoring_input(df)
    predictions_uri = run_batch_scoring(model_artifact_uri, scoring_uri)
    print(f"  Predictions: {predictions_uri}")

    # Step 5: Calibrate and store predictions.
    # In a real pipeline, you'd load the raw predictions from S3,
    # apply calibration, and write to DynamoDB. Here we simulate
    # with the validation set.
    logger.info("=" * 60)
    logger.info("Step 5: Calibrating scores and storing in DynamoDB")
    logger.info("=" * 60)

    # Simulate raw predictions (in production, load from batch transform output).
    raw_scores = np.random.beta(2, 2, size=len(df))  # placeholder
    val_labels = df["paid_within_90_days"].values

    calibrator = fit_calibration_model(raw_scores, val_labels)
    calibrated = calibrator.predict(raw_scores)

    # Generate synthetic IDs for the demo.
    balance_ids = [f"BAL-2026-{i:07d}" for i in range(len(df))]
    patient_ids = [f"PAT-{i:08d}" for i in range(len(df))]

    records_written = store_predictions_in_dynamodb(
        balance_ids=balance_ids,
        patient_ids=patient_ids,
        calibrated_scores=calibrated,
        balance_amounts=df["balance_amount"].values,
        model_version="v1.0-demo",
    )
    print(f"  Wrote {records_written} predictions to DynamoDB")

    # Step 6: Apply collection strategy.
    logger.info("=" * 60)
    logger.info("Step 6: Applying collection strategy routing")
    logger.info("=" * 60)

    # Build prediction dicts as they'd come from DynamoDB.
    predictions = [
        {
            "balance_id": balance_ids[i],
            "propensity_score": Decimal(str(round(float(calibrated[i]), 4))),
            "balance_amount": Decimal(str(round(float(df["balance_amount"].iloc[i]), 2))),
        }
        for i in range(len(df))
    ]

    routing = apply_collection_strategy(predictions)
    print(f"\n  Strategy routing summary:")
    for strategy, count in routing.items():
        pct = count / len(predictions) * 100
        print(f"    {strategy}: {count} balances ({pct:.1f}%)")

    logger.info("Pipeline complete.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run_propensity_pipeline()
```

---

## The Gap Between This and Production

This example works. Run it with real AWS credentials and it will train a model, score balances, and route them to strategy queues. But there's a meaningful distance between "works in a script" and "runs in a revenue cycle system handling real patient financial data." Here's where that gap lives:

**Error handling.** Right now, if SageMaker returns an error or DynamoDB throttles, the pipeline crashes. A production system wraps every external call in try/except blocks with specific handling for throttling, service unavailability, and malformed responses. SageMaker training jobs can fail for many reasons (bad hyperparameters, data format issues, instance capacity). You need graceful failure modes and alerting.

**Retries and backoff.** The `BOTO3_RETRY_CONFIG` handles basic retries, but SageMaker training jobs and batch transform jobs have their own failure modes that need higher-level retry logic. If a training job fails due to a spot instance interruption, you want automatic retry with a different instance, not a page to the on-call engineer.

**Input validation.** This code trusts its inputs completely. A production system validates that feature values are within expected ranges (a balance amount of -$500 or $999,999,999 should be flagged), checks for missing values, and rejects records that would produce garbage predictions. Garbage in, garbage out is especially dangerous when the output drives financial decisions.

**Calibration monitoring.** The calibration model is fitted once here. In production, you need to monitor calibration drift continuously. If the relationship between raw scores and actual payment rates shifts (which it will, especially during economic downturns or policy changes), your thresholds become meaningless. Run calibration checks weekly and retrain the calibrator when drift exceeds your tolerance.

**Fairness monitoring.** Your model will learn correlations between demographics and payment behavior. Some of those correlations reflect systemic inequities, not individual behavior. In production, use SageMaker Clarify to monitor for disparate impact across protected groups. If your model systematically routes patients of certain demographics to "financial assistance screening" at higher rates, you have a fairness problem that needs investigation.

**Feedback loops.** If you stop contacting low-propensity patients, you'll never know if they would have paid with outreach. Your model's predictions become self-fulfilling prophecies. Maintain a random holdout group (5-10% of balances) that gets standard treatment regardless of score. This gives you the counterfactual data needed to measure whether your interventions actually work.

**IAM least-privilege.** The SageMaker execution role in this example is a placeholder. In production, scope it tightly: read-only access to the specific S3 prefixes containing training data, write access only to the model output prefix, and no access to anything else. The Lambda strategy engine needs DynamoDB read access and whatever permissions your downstream collection system requires. Not `AdministratorAccess`.

**VPC configuration.** Patient financial data is PHI. In production, SageMaker training and transform jobs run inside a VPC with VPC endpoints for S3 and DynamoDB. The Lambda strategy engine runs in the same VPC. No data traverses the public internet.

**Encryption key management.** This example relies on default encryption. Production uses KMS customer-managed keys (CMKs) for the S3 bucket, DynamoDB table, and SageMaker training volumes. Key rotation enabled. CloudTrail logging of every key usage.

**The outcome window is a design choice.** This example uses 90 days. Your revenue cycle team might need different models for different decision points: a 30-day model for early payment plan offers, a 90-day model for collection escalation decisions, a 180-day model for write-off predictions. Each is a separate model with separate training data.

**DynamoDB data types.** This example already wraps numeric values in `Decimal` (see Step 5), but be aware that any new numeric fields you add must also use `Decimal`. The `boto3` DynamoDB resource layer will raise a `TypeError` on any raw float in a `put_item` call. This trips up everyone at least once.

**Testing.** There are no tests here. A production pipeline has unit tests for the feature engineering logic, integration tests against SageMaker with a small synthetic dataset, calibration validation tests that check the calibration curve on a held-out set, and fairness tests that check for disparate impact. Never use real patient financial data in your test fixtures.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 7.2](chapter07.02-propensity-to-pay-scoring.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
