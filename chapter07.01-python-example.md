# Recipe 7.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 7.1. It shows one way you could translate those concepts into working Python code using boto3 and SageMaker. It is not production-ready. There's no error handling, no retry logic, no input validation, and the synthetic data is intentionally small. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a scheduling system on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few data science libraries:

```bash
pip install boto3 pandas numpy sagemaker
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs permissions for SageMaker (training jobs, batch transform), S3 (read/write to your ML data bucket), Glue (if using managed ETL), DynamoDB (PutItem, Query), and Lambda (if deploying the action engine).

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
from boto3.dynamodb.conditions import Key
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
ML_BUCKET = "my-noshow-ml-pipeline"
FEATURES_PREFIX = "features/upcoming/"
TRAINING_PREFIX = "features/training/"
MODELS_PREFIX = "models/no-show/"
PREDICTIONS_PREFIX = "predictions/"

# DynamoDB table for storing predictions.
PREDICTIONS_TABLE = "appointment-predictions"

# SageMaker configuration.
SAGEMAKER_ROLE = "arn:aws:iam::123456789012:role/SageMakerExecutionRole"
TRAINING_INSTANCE_TYPE = "ml.m5.xlarge"
TRANSFORM_INSTANCE_TYPE = "ml.m5.large"

# Risk tier thresholds. These are operational decisions, not model decisions.
# Tune based on your reminder capacity and tolerance for false positives.
# A clinic with abundant staff for phone calls might lower the "high" threshold.
# A clinic with only automated SMS might raise it.
HIGH_RISK_THRESHOLD = 0.7    # above this: aggressive intervention (call + SMS + overbook flag)
MEDIUM_RISK_THRESHOLD = 0.4  # above this: automated reminder supplement

# XGBoost hyperparameters for training.
# These are reasonable defaults for a no-show dataset with 10K-500K rows.
XGBOOST_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "auc",
    "num_round": "200",
    "max_depth": "6",
    "eta": "0.1",
    "subsample": "0.8",
    "colsample_bytree": "0.8",
    "scale_pos_weight": "5.5",  # adjust for your actual no-show rate
                                 # formula: (1 - no_show_rate) / no_show_rate
                                 # for 15% no-show: 0.85/0.15 ≈ 5.67
}

# Feature columns the model expects, in order.
# This must match exactly what the training data provides.
FEATURE_COLUMNS = [
    "no_show_rate_last_10",
    "lead_time_days",
    "day_of_week",
    "hour_of_day",
    "visit_type_encoded",
    "distance_miles",
    "insurance_type_encoded",
    "age",
    "days_since_last_visit",
    "prior_cancellations",
]

# Category encoding maps. In production, these come from your feature store
# or a shared config. They must be consistent between training and inference.
VISIT_TYPE_ENCODING = {
    "new_patient": 0,
    "follow_up": 1,
    "wellness": 2,
    "urgent": 3,
    "procedure": 4,
}

INSURANCE_TYPE_ENCODING = {
    "commercial": 0,
    "medicare": 1,
    "medicaid": 2,
    "self_pay": 3,
    "tricare": 4,
}
```

---

## Step 1: Generate Synthetic Training Data

*The main recipe's Step 1 computes features from your scheduling system via a Glue job. Here, we generate synthetic data that mimics what that Glue job would produce. This lets you run the full pipeline without connecting to a real EHR.*

```python
def generate_synthetic_appointments(n_appointments: int = 10000, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic appointment data with realistic no-show patterns.

    The synthetic data encodes the known correlations from no-show research:
    - Higher no-show rate for patients with prior no-shows
    - Higher no-show rate for longer lead times
    - Higher no-show rate for certain days/times
    - Higher no-show rate for follow-up vs. urgent visits

    Args:
        n_appointments: Number of synthetic appointments to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with feature columns and a binary 'no_show' target column.
    """
    rng = np.random.default_rng(seed)

    # Generate base features from realistic distributions.
    # Each feature's distribution is based on what you'd see in a real
    # scheduling system for a mid-size outpatient practice.

    # Historical no-show rate: most patients have low rates, some have high.
    # Beta distribution gives us a nice right-skewed shape.
    no_show_rate_last_10 = rng.beta(a=2, b=8, size=n_appointments)

    # Lead time: days between booking and appointment.
    # Exponential-ish distribution: many same-week bookings, fewer 6+ weeks out.
    lead_time_days = rng.exponential(scale=14, size=n_appointments).astype(int)
    lead_time_days = np.clip(lead_time_days, 0, 90)

    # Day of week: uniform across weekdays (0=Mon through 4=Fri).
    day_of_week = rng.integers(0, 5, size=n_appointments)

    # Hour of day: clustered around business hours (8 AM to 5 PM).
    hour_of_day = rng.integers(8, 17, size=n_appointments)

    # Visit type: weighted toward follow-ups (most common in outpatient).
    visit_types = rng.choice(
        list(VISIT_TYPE_ENCODING.keys()),
        size=n_appointments,
        p=[0.15, 0.45, 0.20, 0.15, 0.05],
    )
    visit_type_encoded = np.array([VISIT_TYPE_ENCODING[v] for v in visit_types])

    # Distance to clinic: log-normal distribution (most patients are close, some far).
    distance_miles = rng.lognormal(mean=1.5, sigma=0.8, size=n_appointments)
    distance_miles = np.clip(distance_miles, 0.5, 50.0)

    # Insurance type: weighted distribution.
    insurance_types = rng.choice(
        list(INSURANCE_TYPE_ENCODING.keys()),
        size=n_appointments,
        p=[0.45, 0.25, 0.15, 0.10, 0.05],
    )
    insurance_type_encoded = np.array([INSURANCE_TYPE_ENCODING[i] for i in insurance_types])

    # Age: normal distribution centered around 45, clipped to realistic range.
    age = rng.normal(loc=45, scale=18, size=n_appointments).astype(int)
    age = np.clip(age, 2, 95)

    # Days since last visit: exponential (most patients seen recently, some lapsed).
    days_since_last_visit = rng.exponential(scale=60, size=n_appointments).astype(int)
    days_since_last_visit = np.clip(days_since_last_visit, 0, 730)

    # Prior cancellations in last year.
    prior_cancellations = rng.poisson(lam=0.8, size=n_appointments)

    # Now generate the target variable (no_show) based on realistic correlations.
    # The probability of no-show is a function of the features above.
    # This simulates the real-world relationship the model will learn.
    logit = (
        -2.0                                          # base rate (intercept)
        + 3.0 * no_show_rate_last_10                  # strongest predictor
        + 0.02 * lead_time_days                       # longer lead = higher risk
        + 0.1 * (day_of_week == 0).astype(float)      # Monday effect
        + 0.1 * (day_of_week == 4).astype(float)      # Friday effect
        + 0.3 * (visit_type_encoded == 1).astype(float)   # follow-ups no-show more
        - 0.5 * (visit_type_encoded == 3).astype(float)   # urgent visits no-show less
        + 0.01 * distance_miles                       # farther = higher risk
        + 0.3 * (insurance_type_encoded == 2).astype(float)  # access barriers
        + 0.005 * days_since_last_visit               # lapsed patients higher risk
        + 0.1 * prior_cancellations                   # cancellation history
        + rng.normal(0, 0.5, size=n_appointments)     # noise (human behavior is stochastic)
    )

    # Convert logit to probability via sigmoid function.
    probability = 1.0 / (1.0 + np.exp(-logit))

    # Sample binary outcome from the probability.
    no_show = rng.binomial(1, probability)

    # Assemble into a DataFrame.
    df = pd.DataFrame({
        "no_show_rate_last_10": np.round(no_show_rate_last_10, 3),
        "lead_time_days": lead_time_days,
        "day_of_week": day_of_week,
        "hour_of_day": hour_of_day,
        "visit_type_encoded": visit_type_encoded,
        "distance_miles": np.round(distance_miles, 1),
        "insurance_type_encoded": insurance_type_encoded,
        "age": age,
        "days_since_last_visit": days_since_last_visit,
        "prior_cancellations": prior_cancellations,
        "no_show": no_show,
    })

    logger.info(
        "Generated %d synthetic appointments. No-show rate: %.1f%%",
        n_appointments,
        100.0 * no_show.mean(),
    )

    return df
```

---

## Step 2: Upload Training Data to S3

*The Glue job in production writes features directly to S3. Here we upload our synthetic data in the CSV format that SageMaker's XGBoost expects: target column first, no header row.*

```python
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)


def upload_training_data(df: pd.DataFrame) -> str:
    """
    Format and upload training data to S3 in SageMaker XGBoost format.

    SageMaker's built-in XGBoost expects CSV with:
    - No header row
    - Target variable in the first column
    - Feature columns following in order

    Args:
        df: DataFrame with feature columns and 'no_show' target.

    Returns:
        The S3 URI where the training data was uploaded.
    """
    # Reorder columns: target first, then features.
    # SageMaker XGBoost reads the first column as the label.
    columns_ordered = ["no_show"] + FEATURE_COLUMNS
    training_df = df[columns_ordered]

    # Convert to CSV without header or index.
    csv_buffer = training_df.to_csv(index=False, header=False)

    # Upload to S3.
    today = datetime.date.today().isoformat()
    s3_key = f"{TRAINING_PREFIX}{today}/train.csv"

    s3_client.put_object(
        Bucket=ML_BUCKET,
        Key=s3_key,
        Body=csv_buffer.encode("utf-8"),
        ServerSideEncryption="aws:kms",  # encrypt at rest with KMS
    )

    s3_uri = f"s3://{ML_BUCKET}/{s3_key}"
    logger.info("Uploaded training data to %s (%d rows)", s3_uri, len(training_df))
    return s3_uri
```

---

## Step 3: Train the Model with SageMaker

*The pseudocode calls this `train_model(training_data_path)`. It launches a SageMaker training job using the built-in XGBoost algorithm. SageMaker handles provisioning the instance, running training, and saving the model artifact to S3.*

```python
import sagemaker
from sagemaker import image_uris
from sagemaker.inputs import TrainingInput


def train_noshow_model(training_data_uri: str) -> str:
    """
    Launch a SageMaker training job for the no-show prediction model.

    Uses SageMaker's built-in XGBoost algorithm, which is optimized for
    tabular binary classification. The training job:
    1. Provisions an ml.m5.xlarge instance
    2. Downloads training data from S3
    3. Trains an XGBoost model with our hyperparameters
    4. Saves the model artifact back to S3
    5. Terminates the instance (you only pay for training time)

    Args:
        training_data_uri: S3 URI of the training CSV file.

    Returns:
        S3 URI of the trained model artifact (.tar.gz).
    """
    # Get the SageMaker session and determine the XGBoost container image
    # for our region. SageMaker maintains pre-built containers for each
    # supported algorithm and framework version.
    session = sagemaker.Session()
    region = session.boto_region_name

    xgboost_image = image_uris.retrieve(
        framework="xgboost",
        region=region,
        version="1.7-1",  # use a recent stable version
    )

    # Create the Estimator: SageMaker's abstraction for a training job.
    # The estimator knows which container to use, what instance to run on,
    # where to put the output, and what hyperparameters to pass.
    today = datetime.date.today().isoformat()
    estimator = sagemaker.estimator.Estimator(
        image_uri=xgboost_image,
        role=SAGEMAKER_ROLE,
        instance_count=1,
        instance_type=TRAINING_INSTANCE_TYPE,
        output_path=f"s3://{ML_BUCKET}/{MODELS_PREFIX}",
        sagemaker_session=session,
        base_job_name=f"noshow-train-{today}",
        # Encrypt the training volume. PHI-adjacent data (appointment patterns)
        # should be encrypted even during transient training.
        volume_kms_key=None,  # in production: your KMS key ARN
    )

    # Set hyperparameters. These are passed to the XGBoost container as
    # command-line arguments. All values must be strings.
    estimator.set_hyperparameters(**XGBOOST_PARAMS)

    # Define the training input channel. SageMaker downloads this data
    # to the training instance before starting the algorithm.
    train_input = TrainingInput(
        s3_data=training_data_uri,
        content_type="text/csv",
    )

    # Launch the training job and wait for completion.
    # This typically takes 5-15 minutes for datasets under 500K rows:
    # ~2 min for instance provisioning, ~1-10 min for actual training,
    # ~1 min for model upload.
    logger.info("Starting SageMaker training job...")
    estimator.fit({"train": train_input}, wait=True)

    # The model artifact is a .tar.gz file in S3 containing the serialized
    # XGBoost model. We'll reference this path when creating batch transform jobs.
    model_artifact_uri = estimator.model_data
    logger.info("Training complete. Model artifact: %s", model_artifact_uri)

    return model_artifact_uri
```

---

## Step 4: Score Upcoming Appointments with Batch Transform

*The pseudocode calls this `score_upcoming_appointments(model_path, features_path)`. Batch transform is the cost-effective choice when you need predictions once daily rather than continuously. SageMaker spins up an instance, loads the model, scores all rows in the input file, writes predictions to S3, and shuts down.*

```python
def prepare_scoring_input(df: pd.DataFrame) -> str:
    """
    Prepare upcoming appointments for batch scoring.

    Takes a DataFrame of upcoming appointments (with features computed but
    no target column) and uploads it to S3 in the format batch transform expects.

    Args:
        df: DataFrame with feature columns for upcoming appointments.
            Must also contain 'appointment_id' for joining predictions back.

    Returns:
        S3 URI of the scoring input file.
    """
    # Batch transform input: features only, no target column, no header.
    # We keep appointment_id separate so we can join predictions back later.
    scoring_df = df[FEATURE_COLUMNS]
    csv_buffer = scoring_df.to_csv(index=False, header=False)

    today = datetime.date.today().isoformat()
    s3_key = f"{FEATURES_PREFIX}{today}/scoring_input.csv"

    s3_client.put_object(
        Bucket=ML_BUCKET,
        Key=s3_key,
        Body=csv_buffer.encode("utf-8"),
        ServerSideEncryption="aws:kms",
    )

    s3_uri = f"s3://{ML_BUCKET}/{s3_key}"
    logger.info("Uploaded scoring input to %s (%d appointments)", s3_uri, len(scoring_df))
    return s3_uri


def score_appointments(model_artifact_uri: str, scoring_input_uri: str) -> str:
    """
    Run SageMaker batch transform to score all upcoming appointments.

    Batch transform is cheaper than a real-time endpoint for once-daily scoring:
    - No idle endpoint costs between scoring runs
    - Processes all appointments in one pass
    - Automatically handles instance provisioning and teardown

    Args:
        model_artifact_uri: S3 URI of the trained model (.tar.gz).
        scoring_input_uri: S3 URI of the scoring input CSV.

    Returns:
        S3 URI prefix where predictions were written.
    """
    session = sagemaker.Session()
    region = session.boto_region_name

    xgboost_image = image_uris.retrieve(
        framework="xgboost",
        region=region,
        version="1.7-1",
    )

    # Create a SageMaker Model object from the trained artifact.
    # This tells SageMaker which container + model weights to use for inference.
    today = datetime.date.today().isoformat()
    model = sagemaker.model.Model(
        image_uri=xgboost_image,
        model_data=model_artifact_uri,
        role=SAGEMAKER_ROLE,
        sagemaker_session=session,
    )

    # Configure and run the batch transform job.
    output_prefix = f"s3://{ML_BUCKET}/{PREDICTIONS_PREFIX}{today}/"

    transformer = model.transformer(
        instance_count=1,
        instance_type=TRANSFORM_INSTANCE_TYPE,
        output_path=output_prefix,
        accept="text/csv",
        strategy="MultiRecord",       # process multiple rows per request (faster)
        max_payload=6,                 # MB per request to the container
    )

    logger.info("Starting batch transform job...")
    transformer.transform(
        data=scoring_input_uri,
        content_type="text/csv",
        split_type="Line",             # one row per line in the input
        wait=True,
    )

    logger.info("Batch transform complete. Predictions at: %s", output_prefix)
    return output_prefix
```

---

## Step 5: Store Predictions in DynamoDB

*The pseudocode calls this `store_predictions(predictions)`. We read the batch transform output from S3, pair each prediction with its appointment ID, classify into risk tiers, and write to DynamoDB for fast downstream access.*

```python
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)


def classify_risk(probability: float) -> str:
    """
    Convert a continuous no-show probability into an actionable risk tier.

    These thresholds are operational decisions. They determine which
    appointments get extra outreach and which get flagged for overbooking.
    Tune them based on your reminder capacity and false-positive tolerance.
    """
    if probability >= HIGH_RISK_THRESHOLD:
        return "high"
    elif probability >= MEDIUM_RISK_THRESHOLD:
        return "medium"
    return "low"


def store_predictions(
    predictions: list[float],
    appointment_ids: list[str],
    scheduled_dates: list[str],
    model_version: str = "v1.0.0",
) -> int:
    """
    Write scored predictions to DynamoDB for downstream consumption.

    Each record contains the appointment ID (primary key), the no-show
    probability, the risk tier, and metadata for auditability. The action
    engine and scheduling UI both read from this table.

    Args:
        predictions: List of no-show probabilities (0.0 to 1.0).
        appointment_ids: Corresponding appointment IDs.
        scheduled_dates: Corresponding scheduled dates (ISO format strings).
        model_version: Version string for the model that produced these scores.

    Returns:
        Number of predictions stored.
    """
    table = dynamodb.Table(PREDICTIONS_TABLE)
    scored_at = datetime.datetime.now(timezone.utc).isoformat()
    count = 0

    # Use batch_writer for efficient bulk writes.
    # DynamoDB batch_writer handles chunking into 25-item batches
    # and automatic retries for unprocessed items.
    with table.batch_writer() as batch:
        for appt_id, probability, sched_date in zip(
            appointment_ids, predictions, scheduled_dates
        ):
            risk_tier = classify_risk(probability)

            item = {
                "appointment_id": appt_id,
                "scheduled_date": sched_date,
                # DynamoDB does not accept Python floats. Wrap in Decimal.
                # str() first to avoid floating-point representation artifacts.
                "no_show_probability": Decimal(str(round(probability, 4))),
                "risk_tier": risk_tier,
                "model_version": model_version,
                "scored_at": scored_at,
                # The main recipe also stores top contributing features (features_used)
                # for explainability. Computing per-prediction feature importance
                # requires SHAP values, which adds complexity beyond this example.
                # See SageMaker Clarify for production feature attribution.
            }

            batch.put_item(Item=item)
            count += 1

    logger.info("Stored %d predictions in DynamoDB", count)
    return count
```

---

## Step 6: Action Engine (Query and Intervene)

*The pseudocode calls this `run_action_engine(target_date)`. This Lambda function queries DynamoDB for high-risk appointments and triggers the appropriate intervention. In production, this sends real SMS/email via SNS/SES. Here we simulate the logic.*

```python
sns_client = boto3.client("sns", config=BOTO3_RETRY_CONFIG)


def query_high_risk_appointments(target_date: str) -> list[dict]:
    """
    Query DynamoDB for appointments on the target date that need intervention.

    Uses a Global Secondary Index on scheduled_date to efficiently find
    all appointments for a given day, then filters to actionable risk tiers.

    Args:
        target_date: ISO date string (e.g., "2026-06-02").

    Returns:
        List of appointment prediction records with risk_tier "high" or "medium".
    """
    table = dynamodb.Table(PREDICTIONS_TABLE)

    # Query using the scheduled_date GSI.
    # In production, this index must exist on the table.
    # NOTE: For a teaching example, we read a single page of results.
    # In production, loop while 'LastEvaluatedKey' is present in the response
    # to handle days with more appointments than fit in one 1MB page.
    response = table.query(
        IndexName="scheduled-date-index",
        KeyConditionExpression=Key("scheduled_date").eq(target_date),
    )

    items = response.get("Items", [])

    # Filter to actionable risk tiers.
    actionable = [
        item for item in items
        if item.get("risk_tier") in ("high", "medium")
    ]

    logger.info(
        "Found %d actionable appointments for %s (of %d total)",
        len(actionable), target_date, len(items),
    )
    return actionable


def run_action_engine(target_date: str) -> dict:
    """
    Execute interventions for high-risk appointments on the target date.

    This is the function your Lambda handler calls. It:
    1. Queries predictions for the target date
    2. Separates into high-risk and medium-risk groups
    3. Triggers appropriate interventions for each group

    In production, "send_reminder" calls SNS (for SMS) or SES (for email).
    Here we log the actions that would be taken.

    Args:
        target_date: ISO date string for the day to process.

    Returns:
        Summary of actions taken.
    """
    actionable = query_high_risk_appointments(target_date)

    high_risk = [a for a in actionable if a["risk_tier"] == "high"]
    medium_risk = [a for a in actionable if a["risk_tier"] == "medium"]

    actions_taken = {"high_risk_interventions": 0, "medium_risk_interventions": 0}

    # High-risk: aggressive intervention.
    # In production: personal phone call + SMS + flag for overbooking.
    for appointment in high_risk:
        appt_id = appointment["appointment_id"]
        probability = float(appointment["no_show_probability"])

        logger.info(
            "HIGH RISK: %s (%.0f%% no-show probability). "
            "Actions: SMS reminder + staff notification + overbook flag.",
            appt_id, probability * 100,
        )

        # In production, this publishes to an SNS topic that triggers
        # your reminder service. The message includes the appointment details
        # and a reschedule link.
        #
        # sns_client.publish(
        #     TopicArn="arn:aws:sns:us-east-1:123456789012:appointment-reminders",
        #     Message=json.dumps({
        #         "appointment_id": appt_id,
        #         "action": "high_risk_reminder",
        #         "include_reschedule_link": True,
        #     }),
        # )

        actions_taken["high_risk_interventions"] += 1

    # Medium-risk: automated reminder supplement.
    for appointment in medium_risk:
        appt_id = appointment["appointment_id"]
        probability = float(appointment["no_show_probability"])

        logger.info(
            "MEDIUM RISK: %s (%.0f%% no-show probability). "
            "Action: automated SMS reminder.",
            appt_id, probability * 100,
        )
        actions_taken["medium_risk_interventions"] += 1

    logger.info(
        "Action engine complete for %s. High-risk: %d, Medium-risk: %d",
        target_date,
        actions_taken["high_risk_interventions"],
        actions_taken["medium_risk_interventions"],
    )
    return actions_taken
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. In production, each step would be a separate component (Glue job, SageMaker training job, batch transform, Lambda), orchestrated by EventBridge. Here we run them sequentially to demonstrate the end-to-end flow.

```python
import json


def run_full_pipeline() -> dict:
    """
    Run the complete no-show prediction pipeline end-to-end.

    This demonstrates the full flow:
    1. Generate synthetic data (replaces Glue feature engineering)
    2. Upload training data to S3
    3. Train the XGBoost model via SageMaker
    4. Prepare and score upcoming appointments
    5. Store predictions in DynamoDB
    6. Run the action engine for tomorrow's appointments

    Returns:
        Summary of the pipeline run.
    """
    logger.info("=" * 60)
    logger.info("NO-SHOW PREDICTION PIPELINE - FULL RUN")
    logger.info("=" * 60)

    # Step 1: Generate synthetic training data.
    # In production, this is a Glue job pulling from your scheduling system.
    logger.info("\nStep 1: Generating synthetic training data...")
    training_data = generate_synthetic_appointments(n_appointments=10000)
    logger.info("  No-show rate in training data: %.1f%%", 100.0 * training_data["no_show"].mean())

    # Step 2: Upload training data to S3.
    logger.info("\nStep 2: Uploading training data to S3...")
    training_uri = upload_training_data(training_data)

    # Step 3: Train the model.
    logger.info("\nStep 3: Training XGBoost model via SageMaker...")
    model_uri = train_noshow_model(training_uri)

    # Step 4: Generate and score upcoming appointments.
    # In production, these come from your scheduling system for the next 48 hours.
    logger.info("\nStep 4: Scoring upcoming appointments...")
    upcoming = generate_synthetic_appointments(n_appointments=200, seed=99)
    # Remove the target column (we're predicting, not training).
    upcoming_features = upcoming.drop(columns=["no_show"])
    # Add appointment IDs and scheduled dates for the prediction records.
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    upcoming_features["appointment_id"] = [f"APT-{i:05d}" for i in range(len(upcoming_features))]
    upcoming_features["scheduled_date"] = tomorrow

    scoring_uri = prepare_scoring_input(upcoming_features)
    predictions_prefix = score_appointments(model_uri, scoring_uri)

    # In a real pipeline, you'd read the predictions from S3 here.
    # For this demo, we'll simulate predictions using the model locally.
    # (Batch transform writes a .csv.out file to the output prefix.)
    logger.info("  (Simulating prediction read from S3 for demo purposes)")
    simulated_predictions = np.random.default_rng(123).beta(2, 5, size=len(upcoming_features))

    # Step 5: Store predictions in DynamoDB.
    logger.info("\nStep 5: Storing predictions in DynamoDB...")
    store_predictions(
        predictions=simulated_predictions.tolist(),
        appointment_ids=upcoming_features["appointment_id"].tolist(),
        scheduled_dates=[tomorrow] * len(upcoming_features),
        model_version="v1.0.0",
    )

    # Step 6: Run the action engine.
    logger.info("\nStep 6: Running action engine for %s...", tomorrow)
    actions = run_action_engine(tomorrow)

    # Summary
    summary = {
        "training_rows": len(training_data),
        "appointments_scored": len(upcoming_features),
        "model_artifact": model_uri,
        "predictions_stored": len(simulated_predictions),
        "actions_taken": actions,
    }

    logger.info("\n" + "=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info(json.dumps(summary, indent=2, default=str))

    return summary


# Run the pipeline.
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = run_full_pipeline()
```

---

## The Gap Between This and Production

This example demonstrates the shape of the solution. Run it and you'll see the full flow from data generation through prediction to action. But there's a meaningful distance between "works as a demo" and "runs nightly for a 50-provider practice." Here's where that gap lives:

**Error handling.** Every AWS API call can fail: throttling, service unavailability, malformed responses, permission errors. A production pipeline wraps each step in try/except blocks with specific handling for each failure mode. SageMaker training jobs can fail due to data format issues, instance capacity, or hyperparameter problems. Each failure needs a different recovery strategy.

**Retries and backoff.** The `BOTO3_RETRY_CONFIG` handles basic retries, but SageMaker training and transform jobs have their own failure modes that require job-level retry logic (not just API-level). If a training job fails, you need to decide: retry with the same data? Check for data corruption first? Alert an engineer?

**Real feature engineering.** The synthetic data generator here is a placeholder for what's actually the hardest part of the pipeline: connecting to your scheduling system, computing rolling statistics across patient history, handling missing data, encoding categorical variables consistently, and keeping features fresh. In production, this is a Glue job (or Spark job) that runs nightly and handles all the edge cases: new patients with no history, patients who transferred from another clinic, appointments that were rescheduled multiple times.

**Model monitoring.** A production system tracks prediction quality over time. If the model's AUC drops below a threshold (measured against actual outcomes as they come in), an alarm fires and triggers retraining. Without monitoring, your model silently degrades as patient behavior shifts, new providers join, or your practice adds telehealth options.

**Fairness evaluation.** Before deploying, evaluate model performance across patient subgroups: by insurance type, by race/ethnicity, by age, by zip code. If the model performs significantly worse for certain groups, or if its predictions would lead to those groups receiving less outreach, you have a fairness problem to address. This isn't optional; it's an ethical requirement for any model that influences patient access.

**A/B testing.** How do you know the model-driven reminders actually reduce no-shows? You need a controlled experiment: randomly assign some high-risk appointments to receive the model-triggered intervention and others to receive standard care. Measure the difference. Without this, you're assuming the model helps without evidence.

**Input validation.** This code trusts its inputs completely. A production system validates that feature values are within expected ranges, that appointment IDs are well-formed, that dates are in the future, and that the scoring input has the correct number of columns in the correct order.

**Logging and observability.** The `logger.info()` calls here are a start, but production needs structured JSON logging with consistent fields (pipeline_run_id, step_name, duration_ms, record_count, error_type). You want dashboards showing: predictions generated per day, risk tier distribution, action engine trigger counts, and model performance metrics. This is what your on-call engineer looks at when the operations team says "we didn't get reminders last night."

**IAM least-privilege.** The SageMaker execution role should have exactly the permissions it needs: read from the training data prefix, write to the models prefix, and nothing else. The Lambda action engine role needs DynamoDB read access scoped to the predictions table and SNS publish access scoped to the reminder topic. Not `AmazonSageMakerFullAccess`. Not `AdministratorAccess`.

**VPC configuration.** In production, SageMaker training and transform jobs run in a VPC with VPC endpoints for S3. The Lambda action engine runs in a VPC with endpoints for DynamoDB and SNS. Appointment data contains PHI (patient names, dates of birth, contact information). It should never traverse the public internet.

**DynamoDB capacity planning.** For a mid-size practice (200-500 appointments/day), on-demand capacity is fine. For a large health system (10,000+ appointments/day), you'll want provisioned capacity with auto-scaling to avoid throttling during the nightly batch write. The GSI on scheduled_date also needs its own capacity allocation.

**The cold start problem.** New patients have no appointment history. The model's strongest feature (historical no-show rate) is undefined for them. Production systems handle this with a fallback: use population-average features for new patients, or a separate simpler model trained only on features available at first booking (lead time, visit type, demographics). Don't let the model silently predict 0.5 for everyone it doesn't know.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 7.1](chapter07.01-appointment-no-show-prediction) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
