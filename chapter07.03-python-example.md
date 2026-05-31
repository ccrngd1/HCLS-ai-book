# Recipe 7.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 7.3. It shows one way you could translate those concepts into working Python code using boto3 and SageMaker. It is not production-ready. There's no error handling, no retry logic, no input validation, and the synthetic data is intentionally small. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a health plan's retention program on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few data science libraries:

```bash
pip install boto3 pandas numpy sagemaker scikit-learn
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs permissions for SageMaker (training jobs, batch transform), S3 (read/write to your ML data bucket), DynamoDB (PutItem, GetItem), and EventBridge (PutEvents).

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
ML_BUCKET = "my-churn-ml-pipeline"
FEATURES_PREFIX = "features/members/"
TRAINING_PREFIX = "features/training/"
MODELS_PREFIX = "models/churn/"
PREDICTIONS_PREFIX = "predictions/"

# DynamoDB table for storing member churn risk scores.
RISK_TABLE = "member-churn-risk"

# SageMaker configuration.
SAGEMAKER_ROLE = "arn:aws:iam::123456789012:role/SageMakerExecutionRole"
TRAINING_INSTANCE_TYPE = "ml.m5.xlarge"
TRANSFORM_INSTANCE_TYPE = "ml.m5.large"

# Risk tier thresholds. These are operational decisions, not model decisions.
# Tune based on your retention team's capacity and intervention costs.
# A plan with a large care coordination team might lower the "high" threshold
# to catch more at-risk members. A plan with limited outreach capacity raises it.
HIGH_RISK_THRESHOLD = 0.60    # above this: proactive retention outreach
MEDIUM_RISK_THRESHOLD = 0.35  # above this: automated engagement nudges

# XGBoost hyperparameters for training.
# These are reasonable defaults for a churn dataset with 50K-500K members.
XGBOOST_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "aucpr",       # precision-recall AUC, better for imbalanced data
    "num_round": "500",
    "max_depth": "6",
    "eta": "0.05",                # slower learning rate for better generalization
    "subsample": "0.8",
    "colsample_bytree": "0.8",
    "scale_pos_weight": "9.0",    # adjust for your actual churn rate
                                   # formula: (1 - churn_rate) / churn_rate
                                   # for 10% churn: 0.90/0.10 = 9.0
}

# Feature columns the model expects, in order.
# This must match exactly what the training data provides.
FEATURE_COLUMNS = [
    "utilization_trend_ratio",
    "rx_fill_gap_days",
    "rx_fills_last_90d",
    "annual_wellness_completed",
    "months_since_last_pcp_visit",
    "grievances_last_6m",
    "unresolved_grievances",
    "call_center_contacts_last_90d",
    "repeat_call_same_issue",
    "pcp_in_network",
    "pcp_changed_last_6m",
    "out_of_network_pct_last_6m",
    "total_oop_last_6m",
    "denied_claims_last_6m",
    "denied_claim_amount_last_6m",
    "tenure_months",
    "age",
    "plan_type_encoded",
    "zip3_market_competition",
    "portal_logins_last_90d",
    "portal_login_trend",
]

# Plan type encoding. Must be consistent between training and inference.
PLAN_TYPE_ENCODING = {
    "HMO": 0,
    "PPO": 1,
    "HDHP": 2,
    "MA_HMO": 3,
    "MA_PPO": 4,
    "POS": 5,
}
```

---

## Step 1: Generate Synthetic Member Data

*The pseudocode calls this `assemble_member_features(member_id, as_of_date)`. In a real system, you'd pull from claims, eligibility, call center, portal, and grievance databases. Here we generate synthetic data that mimics the statistical properties of a real health plan population.*

```python
def generate_synthetic_members(n_members: int = 5000, churn_rate: float = 0.10) -> pd.DataFrame:
    """
    Generate synthetic member data with realistic feature distributions.

    Real health plan data comes from 6+ source systems. This function creates
    a single DataFrame that simulates what you'd get after the Glue feature
    assembly job runs. The distributions are loosely based on published
    literature on health plan disenrollment patterns.

    Args:
        n_members: Number of synthetic members to generate.
        churn_rate: Fraction of members who will be labeled as churned.
                    Real rates vary: 8-12% for commercial, 10-15% for MA.

    Returns:
        DataFrame with one row per member, all features, and a 'churned' label.
    """
    np.random.seed(42)  # reproducibility for the example

    n_churned = int(n_members * churn_rate)
    n_stayed = n_members - n_churned

    # Generate features for members who STAYED (label = 0).
    # These members tend to have stable engagement, fewer grievances,
    # and intact provider networks.
    stayed = pd.DataFrame({
        "member_id": [f"MBR-{i:07d}" for i in range(n_stayed)],
        "utilization_trend_ratio": np.random.normal(1.0, 0.3, n_stayed).clip(0.1, 3.0),
        "rx_fill_gap_days": np.random.exponential(15, n_stayed).clip(0, 180),
        "rx_fills_last_90d": np.random.poisson(3, n_stayed),
        "annual_wellness_completed": np.random.binomial(1, 0.7, n_stayed),
        "months_since_last_pcp_visit": np.random.exponential(3, n_stayed).clip(0, 24),
        "grievances_last_6m": np.random.poisson(0.2, n_stayed),
        "unresolved_grievances": np.random.binomial(1, 0.05, n_stayed),
        "call_center_contacts_last_90d": np.random.poisson(1.0, n_stayed),
        "repeat_call_same_issue": np.random.binomial(1, 0.08, n_stayed),
        "pcp_in_network": np.random.binomial(1, 0.95, n_stayed),
        "pcp_changed_last_6m": np.random.binomial(1, 0.05, n_stayed),
        "out_of_network_pct_last_6m": np.random.beta(1, 20, n_stayed),
        "total_oop_last_6m": np.random.exponential(400, n_stayed).clip(0, 10000),
        "denied_claims_last_6m": np.random.poisson(0.5, n_stayed),
        "denied_claim_amount_last_6m": np.random.exponential(200, n_stayed).clip(0, 5000),
        "tenure_months": np.random.exponential(36, n_stayed).clip(6, 240),
        "age": np.random.normal(45, 15, n_stayed).clip(18, 90).astype(int),
        "plan_type_encoded": np.random.choice(list(PLAN_TYPE_ENCODING.values()), n_stayed),
        "zip3_market_competition": np.random.poisson(4, n_stayed).clip(1, 12),
        "portal_logins_last_90d": np.random.poisson(5, n_stayed),
        "portal_login_trend": np.random.normal(1.0, 0.3, n_stayed).clip(0.0, 3.0),
        "churned": 0,
    })

    # Generate features for members who CHURNED (label = 1).
    # These members show disengagement signals: declining utilization,
    # more grievances, network gaps, and reduced digital engagement.
    churned = pd.DataFrame({
        "member_id": [f"MBR-{i:07d}" for i in range(n_stayed, n_members)],
        "utilization_trend_ratio": np.random.normal(0.4, 0.3, n_churned).clip(0.0, 2.0),
        "rx_fill_gap_days": np.random.exponential(45, n_churned).clip(0, 180),
        "rx_fills_last_90d": np.random.poisson(1, n_churned),
        "annual_wellness_completed": np.random.binomial(1, 0.3, n_churned),
        "months_since_last_pcp_visit": np.random.exponential(8, n_churned).clip(0, 24),
        "grievances_last_6m": np.random.poisson(1.5, n_churned),
        "unresolved_grievances": np.random.binomial(1, 0.35, n_churned),
        "call_center_contacts_last_90d": np.random.poisson(3.0, n_churned),
        "repeat_call_same_issue": np.random.binomial(1, 0.4, n_churned),
        "pcp_in_network": np.random.binomial(1, 0.6, n_churned),
        "pcp_changed_last_6m": np.random.binomial(1, 0.3, n_churned),
        "out_of_network_pct_last_6m": np.random.beta(3, 10, n_churned),
        "total_oop_last_6m": np.random.exponential(900, n_churned).clip(0, 15000),
        "denied_claims_last_6m": np.random.poisson(2.0, n_churned),
        "denied_claim_amount_last_6m": np.random.exponential(600, n_churned).clip(0, 8000),
        "tenure_months": np.random.exponential(24, n_churned).clip(6, 240),
        "age": np.random.normal(42, 15, n_churned).clip(18, 90).astype(int),
        "plan_type_encoded": np.random.choice(list(PLAN_TYPE_ENCODING.values()), n_churned),
        "zip3_market_competition": np.random.poisson(6, n_churned).clip(1, 12),
        "portal_logins_last_90d": np.random.poisson(1.5, n_churned),
        "portal_login_trend": np.random.normal(0.4, 0.3, n_churned).clip(0.0, 2.0),
        "churned": 1,
    })

    # Combine and shuffle.
    df = pd.concat([stayed, churned], ignore_index=True)
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    logger.info("Generated %d synthetic members (%d churned, %.1f%% rate)",
                n_members, n_churned, churn_rate * 100)

    return df
```

---

## Step 2: Prepare Training Data and Upload to S3

*The pseudocode calls this `create_training_dataset(members, label_date, observation_cutoff)`. In a real system, you'd split by time (train on older data, validate on newer). Here we do a stratified split on the synthetic data and upload to S3 in the CSV format SageMaker's built-in XGBoost expects.*

```python
from sklearn.model_selection import train_test_split

# Create S3 client for uploading training data.
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)


def prepare_and_upload_training_data(df: pd.DataFrame) -> tuple[str, str]:
    """
    Split data into train/validation sets and upload to S3.

    SageMaker's built-in XGBoost algorithm expects CSV files with no header,
    where the first column is the label (target variable) and the remaining
    columns are features in the exact order specified by FEATURE_COLUMNS.

    In production, you'd use time-based splitting: train on data from earlier
    periods, validate on the most recent period. This prevents data leakage
    and simulates how the model will actually be used (predicting the future
    from the past). For this synthetic example, we use stratified random split.

    Args:
        df: Full DataFrame with features and 'churned' label.

    Returns:
        Tuple of (train_s3_uri, validation_s3_uri) pointing to the uploaded files.
    """
    # Separate features and label.
    X = df[FEATURE_COLUMNS]
    y = df["churned"]

    # Stratified split preserves the churn rate in both sets.
    # 80% train, 20% validation.
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    logger.info("Train set: %d rows (%d churned)", len(X_train), y_train.sum())
    logger.info("Validation set: %d rows (%d churned)", len(X_val), y_val.sum())

    # SageMaker XGBoost expects: label as first column, no header.
    train_data = pd.concat([y_train.reset_index(drop=True),
                            X_train.reset_index(drop=True)], axis=1)
    val_data = pd.concat([y_val.reset_index(drop=True),
                          X_val.reset_index(drop=True)], axis=1)

    # Write to local CSV (no header, no index).
    train_path = "/tmp/churn_train.csv"
    val_path = "/tmp/churn_validation.csv"
    train_data.to_csv(train_path, header=False, index=False)
    val_data.to_csv(val_path, header=False, index=False)

    # Upload to S3.
    train_key = f"{TRAINING_PREFIX}train/churn_train.csv"
    val_key = f"{TRAINING_PREFIX}validation/churn_validation.csv"

    s3_client.upload_file(train_path, ML_BUCKET, train_key)
    s3_client.upload_file(val_path, ML_BUCKET, val_key)

    train_uri = f"s3://{ML_BUCKET}/{train_key}"
    val_uri = f"s3://{ML_BUCKET}/{val_key}"

    logger.info("Uploaded training data to %s", train_uri)
    logger.info("Uploaded validation data to %s", val_uri)

    return train_uri, val_uri
```

---

## Step 3: Train the XGBoost Model on SageMaker

*The pseudocode calls this `train_churn_model(training_data)`. We use SageMaker's built-in XGBoost algorithm, which saves us from managing training infrastructure. The key decisions: handling class imbalance with `scale_pos_weight`, using `aucpr` as the evaluation metric (better than AUC-ROC for imbalanced problems), and early stopping to prevent overfitting.*

```python
import sagemaker
from sagemaker.estimator import Estimator
from sagemaker.inputs import TrainingInput


def train_churn_model(train_uri: str, val_uri: str) -> str:
    """
    Launch a SageMaker training job for the churn prediction model.

    This uses SageMaker's built-in XGBoost algorithm container. The training
    job runs on a managed instance, trains the model, and saves the artifact
    to S3. You don't manage any infrastructure.

    The hyperparameters in XGBOOST_PARAMS are tuned for a typical health plan
    churn dataset. In production, you'd run a hyperparameter tuning job
    (SageMaker HPO) to find optimal values for your specific population.

    Args:
        train_uri: S3 URI of the training CSV.
        val_uri: S3 URI of the validation CSV.

    Returns:
        S3 URI of the trained model artifact (a tar.gz file).
    """
    session = sagemaker.Session()

    # Get the URI for the built-in XGBoost container image.
    # This is maintained by AWS and includes optimized XGBoost builds.
    region = session.boto_region_name
    container = sagemaker.image_uris.retrieve(
        framework="xgboost",
        region=region,
        version="1.7-1",  # latest stable XGBoost version on SageMaker
    )

    # Define the estimator (the training job configuration).
    estimator = Estimator(
        image_uri=container,
        role=SAGEMAKER_ROLE,
        instance_count=1,
        instance_type=TRAINING_INSTANCE_TYPE,
        output_path=f"s3://{ML_BUCKET}/{MODELS_PREFIX}",
        sagemaker_session=session,
        # Encrypt training volume with KMS. In production, use a CMK.
        # volume_kms_key="arn:aws:kms:us-east-1:123456789012:key/your-key-id",
    )

    # Set hyperparameters.
    estimator.set_hyperparameters(**XGBOOST_PARAMS)

    # Define training inputs. "content_type" tells SageMaker how to parse the data.
    train_input = TrainingInput(
        s3_data=train_uri,
        content_type="text/csv",
    )
    val_input = TrainingInput(
        s3_data=val_uri,
        content_type="text/csv",
    )

    # Launch the training job. This blocks until training completes.
    # Typical runtime for 50K-500K rows on ml.m5.xlarge: 3-10 minutes.
    logger.info("Starting SageMaker training job...")
    estimator.fit({"train": train_input, "validation": val_input})

    # The model artifact is saved to S3 automatically.
    model_uri = estimator.model_data
    logger.info("Model artifact saved to: %s", model_uri)

    return model_uri
```

---

## Step 4: Score Current Membership with Batch Transform

*The pseudocode calls this `score_membership(model, calibrator, active_members, scoring_date)`. SageMaker Batch Transform applies the trained model to a large dataset without deploying a persistent endpoint. This is ideal for weekly scoring of the full membership: you pay only for the compute time used during the batch job.*

```python
from sagemaker.transformer import Transformer


def score_membership_batch(model_uri: str, members_df: pd.DataFrame, scoring_date: str) -> str:
    """
    Score all active members using SageMaker Batch Transform.

    Batch Transform is the right choice for weekly scoring of the full
    membership. It spins up instances, processes all the data, writes results
    to S3, and shuts down. No persistent endpoint to pay for between runs.

    For real-time scoring of individual members (e.g., when a high-signal
    event occurs), you'd deploy a SageMaker real-time endpoint instead.

    Args:
        model_uri: S3 URI of the trained model artifact.
        members_df: DataFrame of current members with features.
        scoring_date: ISO date string for partitioning results.

    Returns:
        S3 URI where the scoring results are written.
    """
    session = sagemaker.Session()

    # Prepare the scoring input: features only, no label, no header.
    # Same column order as training.
    scoring_data = members_df[FEATURE_COLUMNS]
    scoring_path = "/tmp/churn_scoring_input.csv"
    scoring_data.to_csv(scoring_path, header=False, index=False)

    # Upload scoring input to S3.
    scoring_key = f"{FEATURES_PREFIX}scoring_date={scoring_date}/members.csv"
    s3_client.upload_file(scoring_path, ML_BUCKET, scoring_key)
    scoring_uri = f"s3://{ML_BUCKET}/{scoring_key}"

    # Create a SageMaker model from the training artifact.
    region = session.boto_region_name
    container = sagemaker.image_uris.retrieve(
        framework="xgboost",
        region=region,
        version="1.7-1",
    )

    model = sagemaker.model.Model(
        image_uri=container,
        model_data=model_uri,
        role=SAGEMAKER_ROLE,
        sagemaker_session=session,
    )

    # Configure the batch transform job.
    output_uri = f"s3://{ML_BUCKET}/{PREDICTIONS_PREFIX}scoring_date={scoring_date}/"

    transformer = model.transformer(
        instance_count=1,
        instance_type=TRANSFORM_INSTANCE_TYPE,
        output_path=output_uri,
        accept="text/csv",
        strategy="MultiRecord",     # process multiple records per request (faster)
        max_payload=6,              # MB per request batch
    )

    # Launch the transform job. Blocks until complete.
    logger.info("Starting batch transform for %d members...", len(members_df))
    transformer.transform(
        data=scoring_uri,
        content_type="text/csv",
        split_type="Line",
    )
    transformer.wait()

    logger.info("Batch transform complete. Results at: %s", output_uri)
    return output_uri
```

---

## Step 5: Assign Risk Tiers and Identify Top Risk Factors

*The pseudocode calls this `assign_tier(probability)` and uses SHAP values for explainability. In this simplified version, we assign tiers based on the probability thresholds and use feature value heuristics to identify likely churn drivers. A production system would compute actual SHAP values using the `shap` library.*

```python
def assign_risk_tiers(members_df: pd.DataFrame, probabilities: np.ndarray) -> pd.DataFrame:
    """
    Combine member data with model predictions, assign risk tiers,
    and identify the top contributing factors for each high-risk member.

    The tier thresholds are operational decisions calibrated to your retention
    team's capacity. If you can handle 200 outreach calls per week and your
    high-risk tier produces 500 members, either raise the threshold or
    prioritize within the tier.

    Args:
        members_df: DataFrame with member IDs and features.
        probabilities: Array of churn probabilities from the model.

    Returns:
        DataFrame with predictions, tiers, and top risk factors added.
    """
    results = members_df[["member_id"]].copy()
    results["churn_probability"] = probabilities

    # Assign risk tiers based on probability thresholds.
    results["risk_tier"] = "low"
    results.loc[results["churn_probability"] >= MEDIUM_RISK_THRESHOLD, "risk_tier"] = "medium"
    results.loc[results["churn_probability"] >= HIGH_RISK_THRESHOLD, "risk_tier"] = "high"

    # For high-risk members, identify the top contributing factors.
    # In production, you'd compute SHAP values for proper feature attribution.
    # Here we use a simplified heuristic: flag features that deviate most from
    # the "healthy" baseline for retained members.
    risk_factors = []
    for idx, row in results.iterrows():
        if row["risk_tier"] == "high":
            factors = _identify_risk_factors(members_df.iloc[idx])
        else:
            factors = []
        risk_factors.append(factors)

    results["top_risk_factors"] = risk_factors

    # Recommend intervention type based on the dominant risk factor.
    results["intervention_type"] = results["top_risk_factors"].apply(_recommend_intervention)

    tier_counts = results["risk_tier"].value_counts()
    logger.info("Risk distribution: high=%d, medium=%d, low=%d",
                tier_counts.get("high", 0),
                tier_counts.get("medium", 0),
                tier_counts.get("low", 0))

    return results


def _identify_risk_factors(member_row: pd.Series) -> list[dict]:
    """
    Identify the top risk factors for a single member based on feature values.

    This is a simplified heuristic. In production, use SHAP values from the
    trained model for proper feature attribution. SHAP tells you exactly how
    much each feature contributed to this specific prediction.

    The heuristic here flags features that cross known risk thresholds.
    """
    factors = []

    if member_row.get("pcp_in_network", 1) == 0:
        factors.append({"feature": "pcp_in_network", "value": 0,
                        "explanation": "PCP is no longer in network"})

    if member_row.get("unresolved_grievances", 0) > 0:
        factors.append({"feature": "unresolved_grievances",
                        "value": int(member_row["unresolved_grievances"]),
                        "explanation": "Has unresolved grievances"})

    if member_row.get("utilization_trend_ratio", 1.0) < 0.5:
        factors.append({"feature": "utilization_trend_ratio",
                        "value": round(float(member_row["utilization_trend_ratio"]), 2),
                        "explanation": "Significant drop in utilization"})

    if member_row.get("portal_login_trend", 1.0) < 0.4:
        factors.append({"feature": "portal_login_trend",
                        "value": round(float(member_row["portal_login_trend"]), 2),
                        "explanation": "Sharp decline in portal engagement"})

    if member_row.get("denied_claims_last_6m", 0) >= 2:
        factors.append({"feature": "denied_claims_last_6m",
                        "value": int(member_row["denied_claims_last_6m"]),
                        "explanation": "Multiple denied claims"})

    if member_row.get("grievances_last_6m", 0) >= 2:
        factors.append({"feature": "grievances_last_6m",
                        "value": int(member_row["grievances_last_6m"]),
                        "explanation": "Multiple grievances filed"})

    # Return top 5 factors (sorted by severity, most impactful first).
    return factors[:5]


def _recommend_intervention(factors: list[dict]) -> str:
    """
    Route to the appropriate intervention team based on the dominant risk factor.

    In production, this routing logic is often more sophisticated: it considers
    the member's communication preferences, prior intervention history, and
    the retention team's current capacity.
    """
    if not factors:
        return "standard_engagement"

    # Check the top factor and route accordingly.
    top_feature = factors[0]["feature"]

    routing = {
        "pcp_in_network": "network_adequacy_outreach",
        "unresolved_grievances": "member_services_escalation",
        "utilization_trend_ratio": "care_coordinator_outreach",
        "portal_login_trend": "digital_engagement_campaign",
        "denied_claims_last_6m": "benefits_counseling",
        "grievances_last_6m": "member_services_escalation",
    }

    return routing.get(top_feature, "general_retention_outreach")
```

---

## Step 6: Store Results in DynamoDB

*The pseudocode calls this `store_and_serve(results, scoring_date)`. We write each member's risk score to DynamoDB so operational systems (call center apps, care management platforms, member portals) can look up churn risk in real time. The TTL ensures stale scores auto-expire if the weekly scoring job fails.*

```python
from decimal import Decimal
import json

# Create DynamoDB resource.
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)


def store_results_dynamodb(results_df: pd.DataFrame, scoring_date: str) -> int:
    """
    Write member churn risk scores to DynamoDB for real-time operational lookup.

    Downstream systems query this table when a member calls in, logs into
    the portal, or is being reviewed by a care manager. The risk tier and
    top factors help the agent or system decide how to handle the interaction.

    Each put_item overwrites the previous score for that member. Only the
    current risk matters for intervention routing. Historical scores are
    preserved in S3 (Parquet) for trend analysis.

    Args:
        results_df: DataFrame with member_id, churn_probability, risk_tier,
                    top_risk_factors, and intervention_type.
        scoring_date: ISO date string for the scored_at timestamp.

    Returns:
        Number of records written.
    """
    table = dynamodb.Table(RISK_TABLE)
    written = 0

    # Calculate TTL: 30 days from scoring date.
    # If the weekly scoring job fails for multiple weeks, stale scores
    # auto-expire rather than persisting indefinitely.
    scoring_dt = datetime.datetime.fromisoformat(scoring_date)
    ttl_dt = scoring_dt + datetime.timedelta(days=30)
    ttl_epoch = int(ttl_dt.timestamp())

    # Write each member's score. In production, use batch_writer for efficiency.
    with table.batch_writer() as batch:
        for _, row in results_df.iterrows():
            item = {
                "member_id": row["member_id"],
                "churn_probability": Decimal(str(round(row["churn_probability"], 4))),
                "risk_tier": row["risk_tier"],
                "top_risk_factors": json.dumps(row["top_risk_factors"]),
                "intervention_type": row["intervention_type"],
                "scored_at": scoring_date,
                "ttl": ttl_epoch,
            }
            batch.put_item(Item=item)
            written += 1

    logger.info("Wrote %d member risk scores to DynamoDB", written)
    return written
```

---

## Step 7: Publish High-Risk Events to EventBridge

*The pseudocode publishes high-risk members to EventBridge with `detail_type = "MemberChurnRiskHigh"`. Downstream rules route these events to the appropriate intervention queues: network team, member services, care coordination, or benefits counseling.*

```python
# Create EventBridge client.
events_client = boto3.client("events", config=BOTO3_RETRY_CONFIG)


def publish_high_risk_events(results_df: pd.DataFrame, scoring_date: str) -> int:
    """
    Publish EventBridge events for high-risk members to trigger interventions.

    EventBridge rules downstream route these events to the appropriate
    intervention queue based on the intervention_type field. For example:
    - "network_adequacy_outreach" -> Network team's SQS queue
    - "member_services_escalation" -> Priority member services queue
    - "care_coordinator_outreach" -> Care management platform

    EventBridge accepts up to 10 entries per PutEvents call.
    For large batches, we chunk accordingly.

    Args:
        results_df: Full results DataFrame (we filter to high-risk here).
        scoring_date: ISO date string for event metadata.

    Returns:
        Number of events published.
    """
    high_risk = results_df[results_df["risk_tier"] == "high"]

    if high_risk.empty:
        logger.info("No high-risk members to publish")
        return 0

    published = 0
    entries = []

    for _, row in high_risk.iterrows():
        entry = {
            "Source": "churn-prediction-pipeline",
            "DetailType": "MemberChurnRiskHigh",
            "Detail": json.dumps({
                "member_id": row["member_id"],
                "churn_probability": round(row["churn_probability"], 4),
                "risk_tier": row["risk_tier"],
                "top_risk_factors": row["top_risk_factors"],
                "intervention_type": row["intervention_type"],
                "scoring_date": scoring_date,
            }),
            "EventBusName": "default",
        }
        entries.append(entry)

        # PutEvents accepts max 10 entries per call.
        if len(entries) == 10:
            events_client.put_events(Entries=entries)
            published += len(entries)
            entries = []

    # Flush remaining entries.
    if entries:
        events_client.put_events(Entries=entries)
        published += len(entries)

    logger.info("Published %d high-risk events to EventBridge", published)
    return published
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. In production, this would be orchestrated by Step Functions with each step as a separate Lambda or Glue job. Here we run it sequentially for clarity.

```python
def run_churn_prediction_pipeline():
    """
    Run the full churn prediction pipeline end-to-end.

    In a real deployment:
    - Step 1 (feature assembly) is a Glue job pulling from 6+ source systems
    - Step 2 (training) runs quarterly or when model performance degrades
    - Steps 3-6 (scoring, tiers, storage, events) run weekly via Step Functions
    - EventBridge schedules the weekly run

    This function combines everything for demonstration purposes.
    """
    scoring_date = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info("=== Churn Prediction Pipeline: %s ===", scoring_date)

    # Step 1: Generate synthetic member data.
    # In production: Glue job assembles features from claims, eligibility,
    # call center, portal, grievance, and network data sources.
    logger.info("Step 1: Generating synthetic member data...")
    members_df = generate_synthetic_members(n_members=5000, churn_rate=0.10)
    logger.info("  Generated %d members", len(members_df))

    # Step 2: Prepare training data and upload to S3.
    # In production: uses time-based split (train on older, validate on recent).
    logger.info("Step 2: Preparing training data...")
    train_uri, val_uri = prepare_and_upload_training_data(members_df)

    # Step 3: Train the model on SageMaker.
    # In production: runs quarterly or triggered by model monitoring alerts.
    logger.info("Step 3: Training XGBoost model on SageMaker...")
    model_uri = train_churn_model(train_uri, val_uri)

    # Step 4: Score current membership.
    # In production: scores all active members weekly via batch transform.
    # Here we score the same synthetic data for demonstration.
    logger.info("Step 4: Scoring membership with batch transform...")
    output_uri = score_membership_batch(model_uri, members_df, scoring_date)

    # For this example, we'll simulate the predictions locally since
    # batch transform writes to S3 and we'd need to download/parse.
    # In production, you'd read the transform output from S3.
    logger.info("  (Simulating predictions locally for demonstration)")
    from sklearn.ensemble import GradientBoostingClassifier
    X = members_df[FEATURE_COLUMNS]
    y = members_df["churned"]
    local_model = GradientBoostingClassifier(n_estimators=200, max_depth=6, random_state=42)
    local_model.fit(X, y)
    probabilities = local_model.predict_proba(X)[:, 1]

    # Step 5: Assign risk tiers and identify top factors.
    logger.info("Step 5: Assigning risk tiers...")
    results_df = assign_risk_tiers(members_df, probabilities)

    # Step 6: Store results in DynamoDB.
    logger.info("Step 6: Storing results in DynamoDB...")
    store_results_dynamodb(results_df, scoring_date)

    # Step 7: Publish high-risk events to EventBridge.
    logger.info("Step 7: Publishing high-risk events...")
    publish_high_risk_events(results_df, scoring_date)

    # Print summary.
    logger.info("=== Pipeline Complete ===")
    logger.info("Total members scored: %d", len(results_df))
    logger.info("High risk: %d", (results_df["risk_tier"] == "high").sum())
    logger.info("Medium risk: %d", (results_df["risk_tier"] == "medium").sum())
    logger.info("Low risk: %d", (results_df["risk_tier"] == "low").sum())

    # Show a few example high-risk members.
    high_risk_sample = results_df[results_df["risk_tier"] == "high"].head(3)
    for _, member in high_risk_sample.iterrows():
        print(f"\n  Member: {member['member_id']}")
        print(f"  Churn probability: {member['churn_probability']:.2%}")
        print(f"  Intervention: {member['intervention_type']}")
        print(f"  Top factors: {member['top_risk_factors'][:2]}")

    return results_df


# Run the pipeline.
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    results = run_churn_prediction_pipeline()
```

---

## The Gap Between This and Production

This example works. Run it locally and it will generate synthetic data, train a model, score members, and produce risk tiers. But there's a meaningful distance between "works in a script" and "runs at a health plan handling real member data." Here's where that gap lives:

**Error handling.** Right now, if SageMaker returns an error or DynamoDB throttles, the pipeline crashes and members don't get scored. A production system wraps every external call in try/except blocks with specific handling for throttling, service unavailability, and malformed responses. Step Functions provides built-in retry and error handling at the orchestration level.

**Retries and backoff.** The `BOTO3_RETRY_CONFIG` handles basic retries, but SageMaker training jobs can fail for transient reasons (spot instance interruptions, capacity issues). Production pipelines use Step Functions retry policies with exponential backoff and maximum attempt limits. DynamoDB batch writes should handle `UnprocessedItems` in the response.

**Input validation.** This code trusts its inputs completely. A production system validates that source data is fresh (not stale from a failed upstream job), checks for unexpected nulls or distributions that suggest data quality issues, and rejects scoring runs where feature coverage drops below a threshold.

**Model monitoring.** Models degrade over time as member behavior shifts. SageMaker Model Monitor can detect data drift (feature distributions changing) and prediction drift (score distributions shifting). When drift exceeds thresholds, trigger a retraining job. Without monitoring, you'll deploy a model that slowly becomes useless and not know until retention numbers drop.

**Calibration.** This example skips probability calibration entirely. In production, you must calibrate the model's raw probabilities using isotonic regression or Platt scaling on a held-out calibration set. Without calibration, a predicted "0.7" might actually correspond to 40% churn, making your tier thresholds meaningless.

**SHAP values for explainability.** The `_identify_risk_factors` function uses simple heuristics. A production system computes actual SHAP values using the `shap` library, which provides mathematically rigorous feature attribution for each individual prediction. This matters for compliance (explaining why a member was flagged) and for routing (knowing the true driver, not just a heuristic guess).

**Time-based train/validation split.** The stratified random split used here leaks temporal information. Production models must use time-based splitting: train on data from months 1-9, validate on months 10-12. This simulates how the model will actually be used and gives honest performance estimates.

**IAM least-privilege.** The IAM role for this pipeline should have exactly the permissions it needs: `sagemaker:CreateTrainingJob` and `sagemaker:CreateTransformJob` scoped to specific resource prefixes, `s3:GetObject` and `s3:PutObject` scoped to the ML bucket, `dynamodb:PutItem` and `dynamodb:BatchWriteItem` scoped to the risk table, `events:PutEvents` scoped to the default bus. Not `s3:*`. Not `AdministratorAccess`.

**VPC configuration.** In production, SageMaker training jobs and Glue ETL jobs run inside a VPC with private subnets and VPC endpoints for S3, DynamoDB, CloudWatch Logs, and SageMaker API. Member behavioral data is PHI. It should never traverse the public internet.

**Encryption key management.** This example relies on default encryption. Production uses KMS customer-managed keys (CMKs) for S3 buckets (feature store, model artifacts, predictions), DynamoDB tables, and SageMaker training volumes. Key rotation enabled. CloudTrail logging of every key usage.

**Fairness monitoring.** Churn models can encode demographic biases. If members in underserved areas have worse network adequacy and higher churn, the model learns "zip code predicts churn" without distinguishing between fixable network gaps and inherent geographic challenges. Monitor prediction distributions across demographic groups and ensure interventions address root causes.

**DynamoDB data types.** DynamoDB doesn't accept Python floats. This example already wraps probabilities in `Decimal` (see Step 6), but be aware that any new numeric fields must also use `Decimal`. The `boto3` DynamoDB resource layer will raise a `TypeError` on any raw float in a `put_item` call.

**Testing.** There are no tests here. A production pipeline has unit tests for feature engineering logic (with known input/output pairs), integration tests for the SageMaker training job (with a small synthetic dataset), validation tests that check model performance metrics before promoting a new model version, and end-to-end tests that verify the full pipeline produces expected outputs.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 7.3](chapter07.03-patient-churn-disenrollment-prediction.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
