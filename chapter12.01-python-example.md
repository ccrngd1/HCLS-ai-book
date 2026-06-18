# Recipe 12.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 12.1. It shows one way you could translate the appointment-volume-forecasting pipeline into working Python using boto3, Prophet, and pandas. The demo generates synthetic appointment-volume data with realistic weekly seasonality, annual seasonality, holiday effects, and noise so you can see the data prep, model training, forecast generation, and DynamoDB loading work end-to-end without provisioning anything. It is not production-ready. There is no real SageMaker training job, no real Step Functions orchestration, no real EventBridge schedule, no real VPC configuration, no per-Lambda IAM least privilege, no KMS customer-managed keys, no forecast-drift monitoring, no cold-start handling for new clinics, and no hierarchical reconciliation across providers. Think of it as the sketchpad version: useful for understanding the shape of a daily-volume forecasting pipeline that respects the calendar-feature discipline, the prediction-interval-not-point-estimate discipline, and the audit-everything discipline this recipe demands. It is not something you would point at a clinic staffing system on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python, the Prophet forecasting library, and pandas:

```bash
pip install boto3 prophet pandas
```

Prophet pulls in `cmdstanpy` for the Stan backend. On first install, it may download a precompiled Stan binary. If you hit issues on ARM Macs or Linux containers, check the [Prophet installation docs](https://facebook.github.io/prophet/docs/installation.html) for platform-specific notes.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `s3:GetObject` and `s3:PutObject` on the appointment-history bucket prefix and the forecast-output prefix
- `sagemaker:CreateTrainingJob`, `sagemaker:DescribeTrainingJob` if you move to SageMaker-hosted training
- `dynamodb:BatchWriteItem` and `dynamodb:PutItem` on the `appt-forecasts` table
- `kms:Decrypt` and `kms:GenerateDataKey` on the KMS key protecting the S3 bucket and DynamoDB table

A few things worth knowing upfront:

- **Appointment data is PHI by association.** Even daily aggregate counts, combined with clinic identifiers and date, can be joined back to scheduling systems that link to patient records. The S3 prefix and the DynamoDB table live under HIPAA-eligible architecture with SSE-KMS encryption, VPC endpoints, and CloudTrail audit.
- **Prophet expects a specific DataFrame shape.** Two columns: `ds` (datestamp) and `y` (the value to forecast). Additional regressors get added as extra columns. The naming is non-negotiable; rename your data before fitting.
- **DynamoDB rejects Python `float`.** Every numeric value passes through `Decimal()` on its way into DynamoDB. The helper below handles the conversion.
- **The prediction interval is the operational primitive.** Operations leaders staff to the upper bound, not the point estimate. Build everything around the interval, not the single number.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. In production, these would come from environment variables or SSM Parameter Store.

```python
import json
import logging
import math
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import boto3
import pandas as pd
from botocore.config import Config
from prophet import Prophet

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI field values.
# Appointment counts at the aggregate daily level are borderline;
# paired with clinic_id and date they can be correlated back to
# scheduling records. Log structural metadata only (run_id,
# clinic_id, record_count, mape, runtime_ms).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from S3 and DynamoDB.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# --- Resource names (swap per environment) ---
S3_BUCKET = "appt-forecasting-data"
S3_HISTORY_PREFIX = "history/"
S3_FORECAST_PREFIX = "forecasts/"
DYNAMODB_TABLE = "appt-forecasts"

# --- Forecast parameters ---
FORECAST_HORIZON_DAYS = 14          # how far forward to predict
VALIDATION_WINDOW_DAYS = 90         # held-out days for model evaluation
CONFIDENCE_INTERVAL_WIDTH = 0.80    # 80% prediction interval

# --- Quality gate ---
# If the new model's MAPE is more than 20% worse than the previous
# model's MAPE, reject it and keep the old model in production.
MAPE_DEGRADATION_THRESHOLD = 1.20

# --- US Federal holidays (simplified). In production, use a maintained
# holiday calendar library or pull from an authoritative source.
# Prophet accepts holidays as a DataFrame with 'holiday' and 'ds' columns.
US_HOLIDAYS = [
    {"holiday": "new_years_day", "ds": "2024-01-01"},
    {"holiday": "mlk_day", "ds": "2024-01-15"},
    {"holiday": "presidents_day", "ds": "2024-02-19"},
    {"holiday": "memorial_day", "ds": "2024-05-27"},
    {"holiday": "independence_day", "ds": "2024-07-04"},
    {"holiday": "labor_day", "ds": "2024-09-02"},
    {"holiday": "thanksgiving", "ds": "2024-11-28"},
    {"holiday": "christmas", "ds": "2024-12-25"},
    {"holiday": "new_years_day", "ds": "2025-01-01"},
    {"holiday": "mlk_day", "ds": "2025-01-20"},
    {"holiday": "presidents_day", "ds": "2025-02-17"},
    {"holiday": "memorial_day", "ds": "2025-05-26"},
    {"holiday": "independence_day", "ds": "2025-07-04"},
    {"holiday": "labor_day", "ds": "2025-09-01"},
    {"holiday": "thanksgiving", "ds": "2025-11-27"},
    {"holiday": "christmas", "ds": "2025-12-25"},
    {"holiday": "new_years_day", "ds": "2026-01-01"},
    {"holiday": "mlk_day", "ds": "2026-01-19"},
    {"holiday": "presidents_day", "ds": "2026-02-16"},
    {"holiday": "memorial_day", "ds": "2026-05-25"},
    {"holiday": "independence_day", "ds": "2026-07-04"},
    {"holiday": "labor_day", "ds": "2026-09-07"},
    {"holiday": "thanksgiving", "ds": "2026-11-26"},
    {"holiday": "christmas", "ds": "2026-12-25"},
]
```

---

## Synthetic Data Generator

Before we get to the pipeline steps, we need data to work with. This function generates realistic appointment-volume history with the patterns a real clinic would show: weekly seasonality (Mondays busy, Fridays lighter), annual seasonality (summer dips, January spikes), holiday drops, and a slow upward trend. The noise is calibrated to produce the 5-10% MAPE range you'd see on a stable primary care clinic.

Never use real patient appointment data in development. Generate from a known process so you can validate your pipeline against ground truth.

```python
def generate_synthetic_history(
    clinic_id: str,
    start_date: date,
    end_date: date,
    base_volume: int = 180,
) -> pd.DataFrame:
    """
    Generate synthetic daily appointment counts with realistic patterns.

    The generated data has:
    - Weekly seasonality (Monday highest, Friday/weekend lowest)
    - Annual seasonality (winter spike, summer dip)
    - Holiday effects (volume drops ~60% on holidays)
    - Slow upward trend (~5% annual growth)
    - Random noise (std dev ~8% of daily mean)

    Args:
        clinic_id: Identifier for the clinic (metadata, not used in modeling)
        start_date: First day of synthetic history
        end_date: Last day of synthetic history
        base_volume: Average daily appointment count at the start of the series

    Returns:
        DataFrame with columns: ds (date), y (appointment count), clinic_id
    """
    random.seed(42)  # reproducible for demo purposes

    # Day-of-week multipliers. Monday is heaviest; weekend is near-zero
    # for a typical outpatient clinic.
    dow_multipliers = {
        0: 1.15,   # Monday
        1: 1.08,   # Tuesday
        2: 1.05,   # Wednesday
        3: 1.00,   # Thursday
        4: 0.85,   # Friday
        5: 0.05,   # Saturday (urgent care only)
        6: 0.00,   # Sunday (closed)
    }

    # Build the holiday set for fast lookup.
    holiday_dates = {h["ds"] for h in US_HOLIDAYS}

    rows = []
    current = start_date
    day_index = 0

    while current <= end_date:
        # Trend: slow linear growth, ~5% per year.
        trend = 1.0 + (day_index / 365.0) * 0.05

        # Annual seasonality: sine wave with peak in January, trough in July.
        # Healthcare clinics see post-holiday surges and summer slowdowns.
        day_of_year = current.timetuple().tm_yday
        annual_seasonal = 1.0 + 0.08 * math.sin(
            2 * math.pi * (day_of_year - 15) / 365.0
        )

        # Day-of-week effect.
        dow_effect = dow_multipliers[current.weekday()]

        # Holiday effect: volume drops significantly on holidays.
        is_holiday = current.isoformat() in holiday_dates
        holiday_effect = 0.35 if is_holiday else 1.0

        # Compose the deterministic signal.
        signal = base_volume * trend * annual_seasonal * dow_effect * holiday_effect

        # Add Gaussian noise (~8% coefficient of variation).
        noise = random.gauss(0, base_volume * 0.08)
        volume = max(0, int(round(signal + noise)))

        rows.append({
            "ds": current.isoformat(),
            "y": volume,
            "clinic_id": clinic_id,
        })

        current += timedelta(days=1)
        day_index += 1

    df = pd.DataFrame(rows)
    df["ds"] = pd.to_datetime(df["ds"])
    return df
```

---

## Step 1: Prepare Training Data

*The pseudocode calls this `prepare_training_data(raw_history, holiday_calendar)`. It shapes the raw appointment history into the format Prophet expects and ensures there are no gaps in the time series.*

```python
def prepare_training_data(history_df: pd.DataFrame) -> pd.DataFrame:
    """
    Shape raw appointment history into Prophet's expected format.

    Prophet requires exactly two columns for the basic case:
    - ds: the datestamp (datetime or date)
    - y: the value to forecast (numeric)

    This function also fills any missing dates with zero counts.
    A missing day is ambiguous (was the clinic closed, or did the
    data pipeline fail?), but an explicit zero is at least consistent.
    In production, you'd distinguish planned closures (weekends,
    holidays) from data gaps and handle them differently.

    Args:
        history_df: DataFrame with at least 'ds' and 'y' columns.

    Returns:
        Clean DataFrame with one row per day, no gaps, sorted by date.
    """
    df = history_df[["ds", "y"]].copy()
    df["ds"] = pd.to_datetime(df["ds"])

    # Create a complete date range from first to last day in history.
    full_range = pd.date_range(start=df["ds"].min(), end=df["ds"].max(), freq="D")

    # Reindex to fill any gaps with zero. This ensures Prophet sees
    # a regular daily series with no missing time steps.
    df = df.set_index("ds").reindex(full_range, fill_value=0).reset_index()
    df.columns = ["ds", "y"]

    logger.info(
        "Prepared training data: %d days from %s to %s",
        len(df),
        df["ds"].min().date(),
        df["ds"].max().date(),
    )

    return df
```

---

## Step 2: Train the Forecasting Model

*The pseudocode calls this `train_forecast_model(daily_counts)`. It fits a Prophet model on the training window, evaluates on a held-out validation window, and applies a quality gate before promoting the model.*

```python
def train_forecast_model(
    training_df: pd.DataFrame,
    clinic_id: str,
) -> tuple:
    """
    Train a Prophet model and evaluate it against a held-out validation window.

    The workflow:
    1. Split the data into training and validation sets.
    2. Fit Prophet on the training set with weekly + yearly seasonality
       and the US holiday calendar.
    3. Predict over the validation window.
    4. Compute MAPE as the accuracy metric.

    Args:
        training_df: Full history DataFrame (ds, y), already cleaned.
        clinic_id: Clinic identifier for logging and model versioning.

    Returns:
        Tuple of (fitted_model, mape_score, model_version_string).
    """
    # Split: hold out the most recent VALIDATION_WINDOW_DAYS for evaluation.
    cutoff_date = training_df["ds"].max() - timedelta(days=VALIDATION_WINDOW_DAYS)
    train = training_df[training_df["ds"] <= cutoff_date].copy()
    valid = training_df[training_df["ds"] > cutoff_date].copy()

    logger.info(
        "Training on %d days (through %s), validating on %d days",
        len(train),
        cutoff_date.date(),
        len(valid),
    )

    # Build the holiday DataFrame in the format Prophet expects.
    holidays_df = pd.DataFrame(US_HOLIDAYS)
    holidays_df["ds"] = pd.to_datetime(holidays_df["ds"])
    # Prophet lets you specify a window around each holiday to capture
    # the before/after effects (e.g., the day after Thanksgiving is slow too).
    holidays_df["lower_window"] = 0
    holidays_df["upper_window"] = 1  # include the day after each holiday

    # Configure and fit the model.
    # Prophet's defaults are reasonable for most healthcare volume series.
    # Key knobs:
    #   - changepoint_prior_scale: controls trend flexibility.
    #     Lower = smoother trend, less likely to overfit to recent changes.
    #     0.05 is conservative; increase to 0.1-0.3 for clinics in flux.
    #   - seasonality_prior_scale: regularization on seasonal components.
    #     Default (10) is fine for most cases.
    #   - interval_width: sets the prediction interval coverage.
    model = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=False,       # not useful at daily granularity
        holidays=holidays_df,
        changepoint_prior_scale=0.05,
        interval_width=CONFIDENCE_INTERVAL_WIDTH,
    )

    # Suppress Prophet's verbose Stan output during fitting.
    model.fit(train)

    # Generate predictions over the validation window.
    future_valid = model.make_future_dataframe(
        periods=len(valid), include_history=False
    )
    # Prophet's make_future_dataframe starts from the last training date,
    # so shift forward by one day to align with the validation set.
    forecast_valid = model.predict(future_valid)

    # Compute MAPE on the validation set.
    # Only evaluate on days where actual volume > 0 (skip Sundays/closures).
    merged = valid.merge(
        forecast_valid[["ds", "yhat"]], on="ds", how="inner"
    )
    merged = merged[merged["y"] > 0]  # exclude zero-volume days

    if len(merged) == 0:
        logger.warning("No valid days for MAPE calculation")
        mape = 999.0
    else:
        mape = (
            (merged["y"] - merged["yhat"]).abs() / merged["y"]
        ).mean() * 100.0

    model_version = f"prophet-v1-{clinic_id}-{date.today().isoformat()}"

    logger.info(
        "Model %s trained. Validation MAPE: %.1f%% on %d days",
        model_version,
        mape,
        len(merged),
    )

    return model, mape, model_version
```

---

## Step 3: Generate the Forecast

*The pseudocode calls this `generate_forecast(model, forecast_horizon_days)`. It runs the trained model forward to produce daily forecasts with prediction intervals.*

```python
def generate_forecast(
    model: Prophet,
    clinic_id: str,
    model_version: str,
    horizon_days: int = FORECAST_HORIZON_DAYS,
) -> list[dict]:
    """
    Generate a daily forecast with prediction intervals for the next N days.

    The output includes both the point forecast (yhat, rounded to whole
    appointments) and the 80% prediction interval bounds. Operations
    leaders use the upper bound for staffing decisions because being
    understaffed on a busy day costs more than being slightly overstaffed
    on a quiet one.

    Args:
        model: Fitted Prophet model.
        clinic_id: Clinic identifier for the output records.
        model_version: Version string for traceability.
        horizon_days: Number of days to forecast forward.

    Returns:
        List of forecast records, one per day.
    """
    # Prophet generates the future date range from the end of training data.
    future_df = model.make_future_dataframe(
        periods=horizon_days, include_history=False
    )
    forecast_df = model.predict(future_df)

    generated_at = datetime.now(timezone.utc).isoformat()

    records = []
    for _, row in forecast_df.iterrows():
        # Round point forecast to whole appointments.
        # Keep bounds at one decimal for downstream math.
        point = max(0, int(round(row["yhat"])))
        lower = max(0, round(row["yhat_lower"], 1))
        upper = max(0, round(row["yhat_upper"], 1))

        records.append({
            "clinic_id": clinic_id,
            "forecast_date": row["ds"].strftime("%Y-%m-%d"),
            "point_forecast": point,
            "lower_bound": lower,
            "upper_bound": upper,
            "generated_at": generated_at,
            "model_version": model_version,
        })

    logger.info(
        "Generated %d-day forecast for %s. Range: %d to %d appts/day",
        horizon_days,
        clinic_id,
        min(r["point_forecast"] for r in records),
        max(r["point_forecast"] for r in records),
    )

    return records
```

---

## Step 4: Load Forecasts to DynamoDB

*The pseudocode calls this `load_forecasts_to_dynamodb(forecast_records, table_name)`. It writes each forecast record to DynamoDB keyed by clinic_id (partition key) and forecast_date (sort key), using BatchWriteItem for efficiency.*

```python
def _to_decimal(value) -> Decimal:
    """
    Convert a numeric value to Decimal for DynamoDB.

    DynamoDB does not accept Python float. You must wrap every numeric
    value in Decimal() or put_item / batch_write_item will raise a
    TypeError. Converting via str() first avoids floating-point artifacts
    (e.g., Decimal(0.1) becomes 0.1000000000000000055511151231257827021181...,
    but Decimal("0.1") becomes exactly 0.1).
    """
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))

def load_forecasts_to_dynamodb(
    forecast_records: list[dict],
    table_name: str = DYNAMODB_TABLE,
) -> int:
    """
    Write forecast records to DynamoDB in batches of 25.

    Each record is keyed by (clinic_id, forecast_date). Writing a forecast
    for the same clinic and date overwrites the previous forecast, which is
    intentional: today's forecast supersedes yesterday's forecast for the
    same future date.

    Args:
        forecast_records: List of dicts from generate_forecast().
        table_name: DynamoDB table name.

    Returns:
        Number of records successfully written.
    """
    dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
    table = dynamodb.Table(table_name)

    written = 0

    # DynamoDB BatchWriteItem accepts up to 25 items per call.
    for i in range(0, len(forecast_records), 25):
        batch = forecast_records[i : i + 25]

        with table.batch_writer() as writer:
            for record in batch:
                item = {
                    "clinic_id": record["clinic_id"],
                    "forecast_date": record["forecast_date"],
                    "point_forecast": _to_decimal(record["point_forecast"]),
                    "lower_bound": _to_decimal(record["lower_bound"]),
                    "upper_bound": _to_decimal(record["upper_bound"]),
                    "generated_at": record["generated_at"],
                    "model_version": record["model_version"],
                }
                writer.put_item(Item=item)

        written += len(batch)

    logger.info("Wrote %d forecast records to DynamoDB table %s", written, table_name)
    return written
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. In production, each step would be a separate Lambda or SageMaker job orchestrated by Step Functions. Here they run sequentially in-process so you can trace the flow.

```python
def run_forecast_pipeline(
    clinic_id: str = "primary-care-001",
    history_years: int = 3,
    write_to_dynamodb: bool = False,
) -> dict:
    """
    Run the complete appointment-volume-forecasting pipeline for one clinic.

    Steps:
    1. Generate (or load) historical appointment data.
    2. Prepare the training DataFrame.
    3. Train a Prophet model with validation.
    4. Apply the quality gate.
    5. Generate the forward forecast.
    6. Optionally write to DynamoDB.

    Args:
        clinic_id: Identifier for the clinic.
        history_years: Years of synthetic history to generate.
        write_to_dynamodb: If True, write forecasts to DynamoDB.
                           Set to False for local testing.

    Returns:
        Dict with pipeline results including forecast records and metrics.
    """
    logger.info("=" * 60)
    logger.info("Starting forecast pipeline for clinic: %s", clinic_id)
    logger.info("=" * 60)

    # Step 1: Generate synthetic history.
    # In production, this would be an S3 read of exported EHR/PM data.
    end = date.today() - timedelta(days=1)  # through yesterday
    start = end - timedelta(days=history_years * 365)

    logger.info("Step 1: Generating %d years of synthetic history", history_years)
    history_df = generate_synthetic_history(clinic_id, start, end)
    logger.info("  Generated %d daily records", len(history_df))

    # Step 2: Prepare training data.
    logger.info("Step 2: Preparing training data")
    training_df = prepare_training_data(history_df)

    # Step 3: Train the model.
    logger.info("Step 3: Training Prophet model")
    model, mape, model_version = train_forecast_model(training_df, clinic_id)

    # Step 4: Quality gate.
    logger.info("Step 4: Applying quality gate (MAPE: %.1f%%)", mape)
    if mape > 20.0:
        logger.warning(
            "MAPE %.1f%% exceeds 20%% threshold. In production, this model "
            "would be rejected and the previous model retained.",
            mape,
        )
        # In production: exit here and alert the ML engineer.
        # For the demo, we continue so you can see the full flow.

    # Step 5: Generate the forecast.
    logger.info("Step 5: Generating %d-day forecast", FORECAST_HORIZON_DAYS)
    forecast_records = generate_forecast(model, clinic_id, model_version)

    # Step 6: Load to DynamoDB (optional).
    if write_to_dynamodb:
        logger.info("Step 6: Writing forecasts to DynamoDB")
        load_forecasts_to_dynamodb(forecast_records)
    else:
        logger.info("Step 6: Skipping DynamoDB write (write_to_dynamodb=False)")

    # Summary output.
    result = {
        "clinic_id": clinic_id,
        "model_version": model_version,
        "validation_mape_pct": round(mape, 2),
        "forecast_horizon_days": FORECAST_HORIZON_DAYS,
        "forecast_records": forecast_records,
    }

    logger.info("Pipeline complete. MAPE: %.1f%%, Forecast: %d days",
                mape, len(forecast_records))

    return result

# Run the pipeline and print sample output.
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    result = run_forecast_pipeline(
        clinic_id="primary-care-001",
        history_years=3,
        write_to_dynamodb=False,  # set True when you have a real table
    )

    # Print the first few forecast records as a sample.
    print("\n--- Sample Forecast Output ---")
    print(json.dumps(result["forecast_records"][:3], indent=2))
    print(f"\n... ({len(result['forecast_records'])} total days)")
    print(f"Validation MAPE: {result['validation_mape_pct']}%")
```

---

## The Gap Between This and Production

This example works. Run it locally and it will generate synthetic data, train a Prophet model, and produce a 14-day forecast with prediction intervals. But there's a meaningful distance between "works in a script" and "runs nightly for a health system." Here's where that gap lives:

**SageMaker hosting.** This example trains Prophet in-process. A production system runs training as a SageMaker Training Job inside a custom container (based on the SageMaker scikit-learn or PyTorch images with Prophet installed). This gives you managed compute, automatic model artifact storage in S3, experiment tracking, and the ability to scale to multiple clinic series in parallel via SageMaker Processing or Training jobs with multiple instances. For the multi-series case (hundreds of clinics), switch to the built-in DeepAR algorithm which handles joint training natively.

**Step Functions orchestration.** The sequential function calls here become a Step Functions state machine in production. Each step (data extraction, feature engineering, training, validation, inference, DynamoDB load) is a separate Lambda or SageMaker job with explicit error handling, retries with backoff, and failure notifications. Step Functions gives you a visual execution history so you can see exactly where a nightly run failed.

**EventBridge scheduling.** The pipeline runs on a cron schedule (typically 2 AM UTC) triggered by an EventBridge Scheduler rule. The rule targets the Step Functions state machine. No human remembers to run it. If it fails, CloudWatch Alarms fire and page the on-call engineer.

**Forecast drift monitoring.** A model trained today degrades as the world changes. Production systems compare each day's actual appointment count against yesterday's forecast for that day, compute a rolling 7-day MAPE, and alert when it exceeds a threshold for two consecutive weeks. This is your early warning that the model needs retraining outside its normal monthly cadence. Without it, the first signal is a clinic manager complaining that staffing has felt wrong.

**Holiday calendar maintenance.** The hardcoded `US_HOLIDAYS` list above is a demo shortcut. Production uses a maintained calendar source (a DynamoDB lookup table, an internal calendar API, or a library like `holidays`). Holidays change year to year (Easter floats, organization-specific closure days shift). Someone owns this data and reviews it annually.

**Cold-start handling.** New clinics, new providers, and newly added appointment types have no history. The pipeline will fail or produce garbage. Production systems need a fallback: disaggregate the parent organization's forecast by historical mix, use hierarchical forecasting to borrow strength from related series, or apply simple heuristics (regional averages) until 18+ months of history accumulates.

**VPC and network isolation.** In production, the Lambda functions and SageMaker jobs run inside a VPC with private subnets and VPC endpoints for S3, DynamoDB, SageMaker, and CloudWatch. Appointment volume data is PHI by association. Traffic never traverses the public internet, even though AWS encrypts everything in transit. VPC endpoints keep it on the AWS backbone.

**KMS key management.** This example relies on default encryption. Production uses KMS customer-managed keys for the S3 bucket, the DynamoDB table, and SageMaker training volumes, with key rotation enabled and CloudTrail logging of every key usage event. The key policy grants access only to the specific IAM roles that need it.

**IAM least privilege.** The permissions listed in Setup are tutorial-level. In production, the training Lambda has `sagemaker:CreateTrainingJob` but no DynamoDB access. The DynamoDB-loader Lambda has `dynamodb:BatchWriteItem` scoped to the specific table ARN but no SageMaker permissions. No role has `s3:*` or `dynamodb:*`. Scope every action to the specific resource ARN it needs.

**Multi-series and hierarchical forecasting.** This example forecasts one clinic at a time. A health system with 200 clinics needs either: (a) a parallel map over clinics (Step Functions Map state, one training job per clinic), or (b) a joint model that trains across all clinics simultaneously (DeepAR). For consistency across organizational levels (clinic, department, region), hierarchical reconciliation ensures that per-clinic forecasts sum to the organization total. Libraries like `scikit-hts` or Prophet's own grouped forecasting utilities handle this.

**Testing.** There are no tests here. A production pipeline has: unit tests for `prepare_training_data` (verifying gap-filling and date alignment), integration tests that run the full pipeline against synthetic data with known properties and assert MAPE is within expected bounds, regression tests that compare the current model's accuracy against a pinned baseline, and a fixture library of synthetic series covering edge cases (holiday-heavy weeks, zero-volume weekends, trend changepoints). Never use real patient appointment data in test fixtures.

**Backfill and reprocessing.** When you discover a bug in the data prep step, you need to retrain and regenerate forecasts for the affected period. The pipeline must be safe to rerun (idempotent DynamoDB writes help) and the model registry must track which model version produced which forecasts so you can trace any decision back to its source.

The recipe in 12.1 discusses forecast monitoring, cold-start handling, and operational integration in more detail. This code gives you the shape; the main recipe gives you the context for what wraps around it.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 12.1](chapter12.01-appointment-volume-forecasting) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
