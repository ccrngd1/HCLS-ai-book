# Code Review: Recipe 7.3 - Patient Churn / Disenrollment Prediction

**Reviewer:** Tech Code Reviewer
**Date:** 2026-05-31
**Files reviewed:**
- `chapter07.03-patient-churn-disenrollment-prediction.md` (pseudocode)
- `chapter07.03-python-example.md` (Python)

**Validation performed:**
- Python syntax check across all 8 code blocks: PASSED
- boto3 API signatures verified (SageMaker, S3, DynamoDB, EventBridge)
- SageMaker built-in XGBoost hyperparameter names confirmed
- DynamoDB Decimal usage confirmed
- S3 key prefixes checked for leading slashes (none found)

---

## Summary

Solid implementation. Four issues found: no runtime-breaking errors, two misleading patterns that could confuse readers, and two minor notes. All five pseudocode steps are correctly mapped to the seven Python steps (the split into finer-grained steps is well-motivated and documented). boto3 method names, parameter names, and response structures are accurate. DynamoDB correctly uses `Decimal`. S3 paths have no leading slashes.

---

## Verdict: PASS

---

## Issues

### Issue 1: Misleading comment says "In production, use batch_writer" but code already uses batch_writer

**Severity:** WARNING
**File:** `chapter07.03-python-example.md`
**Location:** Step 6, line above `with table.batch_writer() as batch:`

The comment reads:

```python
# Write each member's score. In production, use batch_writer for efficiency.
with table.batch_writer() as batch:
```

The code IS using `batch_writer`. A reader will be confused: "Wait, isn't this already production-ready in that regard?" The comment implies the current code is doing something simpler (like individual `put_item` calls) when it's not.

**Fix:** Change the comment to explain what `batch_writer` does rather than suggesting it as a future improvement:

```python
# Write scores in batches. batch_writer() automatically buffers items and
# sends them in groups of 25 (DynamoDB's BatchWriteItem limit), handling
# UnprocessedItems retries internally.
with table.batch_writer() as batch:
```

---

### Issue 2: Pseudocode specifies early stopping but Python omits it

**Severity:** WARNING
**File:** `chapter07.03-python-example.md`
**Location:** Config section, `XGBOOST_PARAMS` dict

The pseudocode in the main recipe explicitly includes:

```
early_stopping   = 50 rounds           // stop if validation metric plateaus
```

The Python `XGBOOST_PARAMS` dict does not include the corresponding SageMaker hyperparameter. For SageMaker's built-in XGBoost, this would be `"early_stopping_rounds": "50"`. Without it, the model trains for all 500 rounds regardless of validation performance, which contradicts what the pseudocode teaches and can lead to overfitting.

This is a pseudocode-to-Python consistency gap. A reader who follows the pseudocode's guidance about early stopping won't find it implemented in the Python.

**Fix:** Add to `XGBOOST_PARAMS`:

```python
XGBOOST_PARAMS = {
    ...
    "early_stopping_rounds": "50",  # stop if validation aucpr doesn't improve for 50 rounds
}
```

---

### Issue 3: Step 7 uses `json.dumps()` without importing `json`

**Severity:** NOTE
**File:** `chapter07.03-python-example.md`
**Location:** Step 7 code block

Step 7 starts a new code block that uses `json.dumps()` in the EventBridge entry construction. The `import json` statement only appears in Step 6's code block. A reader who copies Step 7 in isolation gets `NameError: name 'json' is not defined`.

The Config/Setup block at the top also doesn't import `json`. Since the cookbook format encourages readers to copy individual blocks, either add `import json` to the Config block (preferred, since it's used in two steps) or add it to Step 7's block header.

**Fix:** Add `import json` to the Config section imports alongside the other standard library imports:

```python
import logging
import datetime
import json
from datetime import timezone
from decimal import Decimal
```

---

### Issue 4: TTL calculation uses naive datetime, producing timezone-dependent epoch values

**Severity:** NOTE
**File:** `chapter07.03-python-example.md`
**Location:** Step 6, TTL calculation

```python
scoring_dt = datetime.datetime.fromisoformat(scoring_date)
ttl_dt = scoring_dt + datetime.timedelta(days=30)
ttl_epoch = int(ttl_dt.timestamp())
```

`scoring_date` is a date-only string like `"2026-05-31"`. `datetime.fromisoformat("2026-05-31")` produces a naive datetime (midnight, no timezone). Calling `.timestamp()` on a naive datetime uses the system's local timezone to compute the epoch, which means the TTL value changes depending on where the code runs. A pipeline running in `us-east-1` (UTC-4/5) produces a different TTL than one in `eu-west-1`.

For a teaching example this won't cause a runtime error, but it teaches an imprecise pattern. The pipeline already imports `timezone` from `datetime` and uses it correctly in `run_churn_prediction_pipeline`.

**Fix:** Make the TTL calculation timezone-aware:

```python
scoring_dt = datetime.datetime.fromisoformat(scoring_date).replace(tzinfo=timezone.utc)
```

---

## Validation Details

### Syntax check
All 8 Python code blocks parse without syntax errors.

### boto3 / SageMaker SDK method names
- `s3_client.upload_file(path, bucket, key)`: correct
- `sagemaker.image_uris.retrieve(framework, region, version)`: correct
- `Estimator(image_uri, role, instance_count, instance_type, output_path, sagemaker_session)`: correct
- `estimator.set_hyperparameters(**params)`: correct
- `TrainingInput(s3_data, content_type)`: correct
- `estimator.fit({"train": ..., "validation": ...})`: correct channel names for built-in XGBoost
- `sagemaker.model.Model(image_uri, model_data, role, sagemaker_session)`: correct
- `model.transformer(instance_count, instance_type, output_path, accept, strategy, max_payload)`: correct
- `transformer.transform(data, content_type, split_type)`: correct
- `transformer.wait()`: correct
- `dynamodb.Table(name).batch_writer()`: correct
- `batch.put_item(Item=item)`: correct
- `events_client.put_events(Entries=entries)`: correct

### SageMaker XGBoost hyperparameters
All parameter names in `XGBOOST_PARAMS` are valid for SageMaker's built-in XGBoost 1.7:
- `objective`, `eval_metric`, `num_round`, `max_depth`, `eta`, `subsample`, `colsample_bytree`, `scale_pos_weight`: all correct
- Values are strings (required by SageMaker's hyperparameter interface): correct

### DynamoDB Decimal usage
- `churn_probability` is wrapped in `Decimal(str(round(..., 4)))`: correct
- `ttl` is an `int`: correct (DynamoDB accepts int for Number type)
- `top_risk_factors` is serialized as JSON string (not stored as a DynamoDB list with floats): correct, avoids Decimal issues in nested structures

### S3 paths
- `FEATURES_PREFIX = "features/members/"`: no leading slash
- `TRAINING_PREFIX = "features/training/"`: no leading slash
- `MODELS_PREFIX = "models/churn/"`: no leading slash
- `PREDICTIONS_PREFIX = "predictions/"`: no leading slash
- All constructed keys use f-strings with these prefixes: no leading slashes introduced

### EventBridge PutEvents structure
- `Source`: string, correct
- `DetailType`: string, correct
- `Detail`: JSON string via `json.dumps()`, correct
- `EventBusName`: string, correct
- Batch size limit of 10 entries per call: correctly implemented with chunking

### Pseudocode-to-Python mapping
| Pseudocode Step | Python Step(s) | Consistent? |
|----------------|----------------|-------------|
| `assemble_member_features` | Step 1: `generate_synthetic_members` | Yes (synthetic substitute, clearly documented) |
| `create_training_dataset` | Step 2: `prepare_and_upload_training_data` | Yes (stratified split noted as simplification of time-based) |
| `train_churn_model` | Step 3: `train_churn_model` | Mostly (missing early_stopping_rounds, see Issue 2) |
| `score_membership` + `assign_tier` | Steps 4-5: `score_membership_batch` + `assign_risk_tiers` | Yes |
| `store_and_serve` | Steps 6-7: `store_results_dynamodb` + `publish_high_risk_events` | Yes |

---

## What Is Clean

- The synthetic data generation produces realistic feature distributions with clear separation between churned/stayed populations. Good for a reader to understand what the features look like.
- Risk tier thresholds are externalized as constants with clear comments about how to tune them. Pedagogically sound.
- The `_identify_risk_factors` heuristic is clearly documented as a simplification of SHAP, with the production approach explained in comments and the Gap section.
- DynamoDB TTL pattern is correctly implemented (epoch seconds, auto-expire stale scores).
- EventBridge batching respects the 10-entry limit with proper flush logic.
- The "Gap Between This and Production" section is thorough and covers calibration, SHAP, time-based splitting, VPC, encryption, and fairness monitoring.
- Comments explain "why" not just "what" throughout. Accessible to a Python learner.
- The pipeline function clearly documents which steps run on different cadences in production (quarterly training vs. weekly scoring).
