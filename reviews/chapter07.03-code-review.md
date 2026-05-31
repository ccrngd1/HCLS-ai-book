# Code Review: Recipe 7.3 - Patient Churn / Disenrollment Prediction

**Reviewer:** Tech Code Reviewer
**Date:** 2026-05-31
**Files reviewed:**
- `chapter07.03-patient-churn-disenrollment-prediction.md` (pseudocode)
- `chapter07.03-python-example.md` (Python)

**Validation performed:**
- Python syntax check via `ast.parse()` across all 8 code blocks: PASSED
- boto3 API signatures verified (S3, DynamoDB, EventBridge)
- SageMaker SDK usage verified (Estimator, TrainingInput, Model, Transformer)
- DynamoDB Decimal handling verified
- S3 key paths checked for leading slashes

---

## Summary

Solid implementation. The Python companion faithfully implements all five pseudocode steps and adds appropriate operational steps (EventBridge publishing, DynamoDB storage). DynamoDB correctly uses `Decimal` for numeric values. S3 paths have no leading slashes. Two warnings found: one regarding a pedagogically misleading pattern in the pipeline orchestration (training on the same data you score), and one regarding the EventBridge `put_events` response not being checked for `FailedEntryCount`. One note on a minor inconsistency between pseudocode calibration and the Python implementation.

---

## Verdict: PASS

---

## Issues

### Issue 1: Misleading pattern - Pipeline trains and scores on the same synthetic data

**Severity:** WARNING
**File:** `chapter07.03-python-example.md`, Step 4 / "Putting It All Together"

In `run_churn_prediction_pipeline()`, the code trains a model on the synthetic data and then scores the exact same data:

```python
members_df = generate_synthetic_members(n_members=5000, churn_rate=0.10)
# ... trains on members_df ...
# ... then scores members_df again ...
local_model.fit(X, y)
probabilities = local_model.predict_proba(X)[:, 1]
```

This trains on the full dataset (including labels) and then predicts on the same rows. A reader might not realize this produces artificially perfect-looking results. The code does note `"(Simulating predictions locally for demonstration)"` but doesn't explicitly warn that scoring training data produces unrealistically optimistic probabilities.

The "Gap Between This and Production" section mentions time-based splitting but doesn't call out this specific issue in the demo code.

**Fix:** Add a comment at the local simulation point:

```python
# WARNING: We're scoring the same data we trained on. In production, you'd
# never do this -- it produces unrealistically high accuracy. This is only
# to demonstrate the pipeline flow. Real scoring uses the batch transform
# output on unseen members.
```

---

### Issue 2: EventBridge `put_events` response not checked for `FailedEntryCount`

**Severity:** WARNING
**File:** `chapter07.03-python-example.md`, Step 7 (`publish_high_risk_events`)

The `put_events` API can partially succeed: some entries may fail while others succeed. The response includes a `FailedEntryCount` field and per-entry error codes. The current code ignores the response entirely:

```python
if len(entries) == 10:
    events_client.put_events(Entries=entries)
    published += len(entries)
    entries = []
```

A reader who copies this pattern into production will silently lose events. For a teaching example, this is a misleading pattern because it teaches "fire and forget" for EventBridge without acknowledging that partial failures are possible.

**Fix:** Add a comment acknowledging the gap, or check the response:

```python
response = events_client.put_events(Entries=entries)
# In production, check response["FailedEntryCount"] and retry failed entries.
# Partial failures are possible (e.g., event too large, throttling).
published += len(entries) - response.get("FailedEntryCount", 0)
```

---

### Issue 3: Pseudocode includes calibration step but Python skips it entirely

**Severity:** NOTE
**File:** `chapter07.03-python-example.md`, overall pipeline

The pseudocode Step 3 (`train_churn_model`) explicitly includes isotonic regression calibration:

```
calibrator = IsotonicRegression()
calibrator.fit(model.predict_proba(val_set.features), val_set.labels)
RETURN model, calibrator
```

And Step 4 (`score_membership`) applies it:

```
calibrated_probability = calibrator.transform(raw_probability)
```

The Python companion skips calibration entirely. The "Gap Between This and Production" section does call this out explicitly ("This example skips probability calibration entirely"), which is good. However, the local simulation in `run_churn_prediction_pipeline` uses raw `predict_proba` output directly for tier assignment without any note that these are uncalibrated.

This is acknowledged in the gap section, so it's not misleading per se, but a brief inline comment at the point where probabilities are used would help readers connect the dots.

**Fix:** Add a comment where probabilities are assigned to tiers:

```python
# These probabilities are uncalibrated. In production, apply isotonic
# regression (see pseudocode Step 3) before using for tier assignment.
probabilities = local_model.predict_proba(X)[:, 1]
```

---

## Validation Details

### Syntax check
All 8 Python code blocks (Config, Steps 1-7, Putting It All Together) passed `ast.parse()` without errors.

### boto3 / SageMaker SDK method names
- `s3_client.upload_file(path, bucket, key)`: correct signature
- `dynamodb.Table(name).batch_writer()`: correct context manager usage
- `batch.put_item(Item=...)`: correct
- `events_client.put_events(Entries=[...])`: correct, `Entries` is the right parameter name
- `sagemaker.image_uris.retrieve(framework=, region=, version=)`: correct
- `Estimator(image_uri=, role=, instance_count=, instance_type=, output_path=)`: correct
- `estimator.set_hyperparameters(**params)`: correct
- `estimator.fit({"train": ..., "validation": ...})`: correct channel names for XGBoost
- `TrainingInput(s3_data=, content_type=)`: correct
- `sagemaker.model.Model(image_uri=, model_data=, role=)`: correct
- `model.transformer(instance_count=, instance_type=, output_path=, accept=, strategy=, max_payload=)`: correct parameters
- `transformer.transform(data=, content_type=, split_type=)`: correct
- `transformer.wait()`: correct

### XGBoost hyperparameters
- `objective: "binary:logistic"`: valid
- `eval_metric: "aucpr"`: valid (area under precision-recall curve)
- `num_round: "500"`: correct (string format required for SageMaker built-in)
- `max_depth: "6"`: correct
- `eta: "0.05"`: correct (learning rate alias)
- `subsample: "0.8"`: valid
- `colsample_bytree: "0.8"`: valid
- `scale_pos_weight: "9.0"`: valid

All hyperparameters are passed as strings, which is correct for SageMaker's built-in algorithm container.

### DynamoDB Decimal handling
Step 6 correctly wraps the float probability in `Decimal`:
```python
"churn_probability": Decimal(str(round(row["churn_probability"], 4))),
```
The `str()` wrapper prevents floating-point representation issues. The `ttl` field is an `int` (epoch seconds), which DynamoDB accepts natively. No raw floats are passed to `put_item`. Correct.

### S3 path validation
All S3 keys are constructed without leading slashes:
- `f"{TRAINING_PREFIX}train/churn_train.csv"` -> `features/training/train/churn_train.csv`
- `f"{TRAINING_PREFIX}validation/churn_validation.csv"` -> `features/training/validation/churn_validation.csv`
- `f"{FEATURES_PREFIX}scoring_date={scoring_date}/members.csv"` -> `features/members/scoring_date=.../members.csv`
- `f"{PREDICTIONS_PREFIX}scoring_date={scoring_date}/"` -> `predictions/scoring_date=.../`

No leading slashes found. Correct.

### Pseudocode-to-Python consistency
| Pseudocode Step | Python Implementation | Match? |
|---|---|---|
| Step 1: `assemble_member_features` | `generate_synthetic_members` (synthetic equivalent) | Yes |
| Step 2: `create_training_dataset` | `prepare_and_upload_training_data` | Yes |
| Step 3: `train_churn_model` | `train_churn_model` | Yes (minus calibration, acknowledged) |
| Step 4: `score_membership` | `score_membership_batch` | Yes |
| Step 5: `store_and_serve` (DynamoDB) | `store_results_dynamodb` | Yes |
| Step 5: `store_and_serve` (EventBridge) | `publish_high_risk_events` | Yes |
| `assign_tier` | `assign_risk_tiers` | Yes |

All pseudocode steps are represented. The Python adds `assign_risk_tiers` as a separate function (Step 5 in the Python), which is a reasonable decomposition of the pseudocode's `score_membership` + `assign_tier` combination.

### Comment quality
Comments are consistently helpful and explain the "why" throughout. Examples of good pedagogical comments:
- Explaining `scale_pos_weight` formula and when to adjust it
- Noting that SageMaker XGBoost expects CSV with label as first column, no header
- Explaining TTL purpose (stale score expiration if pipeline fails)
- Noting EventBridge 10-entry limit per `put_events` call

---

## What Is Clean

- The code flows top-to-bottom in a logical order that builds understanding incrementally.
- Config/constants are separated at the top with clear explanations of each value.
- The synthetic data generation creates realistic distributions that differ meaningfully between churned and retained members, making the example pedagogically useful.
- DynamoDB `batch_writer()` is used correctly for bulk writes (handles batching and unprocessed items internally).
- The `Decimal(str(round(...)))` pattern is the correct way to handle DynamoDB numeric types.
- The "Gap Between This and Production" section is thorough and honest about what's missing.
- Feature column ordering is explicitly defined and consistent between training and scoring.
- The plan type encoding dictionary ensures consistency between training and inference.
- Logging is used appropriately throughout without exposing PHI values.
