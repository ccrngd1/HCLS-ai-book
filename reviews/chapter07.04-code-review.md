# Code Review: Recipe 7.4 - ED Visit Prediction

**Reviewer:** Tech Code Reviewer
**Date:** 2026-05-31
**Files reviewed:**
- `chapter07.04-python-example.md` (Python companion)
- Main recipe file (`chapter07.04-ed-visit-prediction.md`) not yet available for pseudocode consistency check

**Validation performed:**
- Python syntax check across all 7 code blocks: PASSED
- boto3 API signatures verified (S3, DynamoDB)
- DynamoDB Decimal usage confirmed
- S3 key prefixes checked for leading slashes (none found)
- scikit-learn API usage verified

---

## Summary

Clean, well-structured implementation. The pipeline flows logically from synthetic data generation through model training, evaluation, scoring, and storage. Comments are excellent throughout, explaining clinical rationale and operational context. Three issues found: one misleading pattern in the per-patient explanation approach, one deprecated API usage that teaches a pattern being phased out, and one note about a missing consistency check. No runtime-breaking errors.

---

## Verdict: PASS

---

## Issues

### Issue 1: Per-patient "top factors" calculation is misleading

**Severity:** WARNING
**File:** `chapter07.04-python-example.md`
**Location:** Step 4, `score_patients()`, contribution calculation

```python
contributions = patient_features * feature_importances
top_indices = np.argsort(contributions)[-3:][::-1]
```

This multiplies raw feature values by global feature importances to approximate per-patient explanations. The problem: feature scale dominates the result. A patient with `age=75` and feature importance 0.05 gets contribution 3.75, while `ed_visits_last_12m=4` with importance 0.30 gets contribution 1.2. The code would report "age" as the top factor when the model actually relies more on ED visit history for that prediction.

The comment correctly notes this is a simplification and points to SHAP, but a reader copying this pattern gets actively wrong explanations for individual patients. Since the output feeds a care manager worklist with "top contributing factors," this could mislead clinical users in a real deployment.

**Fix:** Either normalize features before multiplying (so scale doesn't dominate):

```python
# Normalize feature values to 0-1 range so scale doesn't dominate
X_min = X.min()
X_max = X.max()
patient_normalized = (X.iloc[idx].values - X_min.values) / (X_max.values - X_min.values + 1e-8)
contributions = patient_normalized * feature_importances
```

Or replace with a simpler heuristic that's less wrong, like reporting the top global feature importances for features where the patient has non-zero/above-median values. Add a stronger caveat that this approach produces incorrect attributions and should never be shown to clinicians without SHAP.

---

### Issue 2: `datetime.utcnow()` is deprecated in Python 3.12+

**Severity:** WARNING
**File:** `chapter07.04-python-example.md`
**Location:** Step 4 (`scored_at` timestamp) and Step 5 (TTL calculation)

Two occurrences:

```python
results["scored_at"] = datetime.utcnow().isoformat() + "Z"
```

```python
"ttl": int(
    (datetime.utcnow() + timedelta(days=PREDICTION_WINDOW_DAYS)).timestamp()
),
```

`datetime.utcnow()` was deprecated in Python 3.12 (PEP 587). It returns a naive datetime, which can cause subtle bugs when `.timestamp()` is called (it assumes local timezone). For a teaching example, this teaches a pattern that's actively being removed from the language.

**Fix:** Use timezone-aware UTC:

```python
from datetime import datetime, timedelta, timezone

# Step 4:
results["scored_at"] = datetime.now(timezone.utc).isoformat()

# Step 5:
"ttl": int(
    (datetime.now(timezone.utc) + timedelta(days=PREDICTION_WINDOW_DAYS)).timestamp()
),
```

The `.isoformat()` on a timezone-aware datetime already includes the `+00:00` suffix, so the manual `+ "Z"` concatenation is no longer needed.

---

### Issue 3: Cannot verify pseudocode-to-Python consistency

**Severity:** NOTE
**File:** `chapter07.04-python-example.md`
**Location:** Entire file

The main recipe file (`chapter07.04-ed-visit-prediction.md`) does not exist yet. This means pseudocode-to-Python consistency cannot be verified. The Python companion references it at the bottom: "See [Recipe 7.4](chapter07.04-ed-visit-prediction) for the full architectural walkthrough, pseudocode..."

Once the main recipe is written, a follow-up review should confirm that all pseudocode steps map correctly to the Python implementation.

**Fix:** No action needed on the Python file. Flag for re-review after the main recipe is drafted.

---

## Validation Details

### Syntax check
All 7 Python code blocks (Config, Steps 1-6, pipeline runner) parse without syntax errors.

### boto3 API method names and parameters
- `boto3.resource("dynamodb", config=...)`: correct
- `dynamodb.Table(name)`: correct
- `table.batch_writer()`: correct
- `batch.put_item(Item=item)`: correct
- `boto3.client("s3", config=...)`: correct
- `s3_client.put_object(Bucket, Key, Body, ServerSideEncryption)`: correct parameter names
- `Config(retries={"max_attempts": 3, "mode": "adaptive"})`: correct botocore retry config

### DynamoDB Decimal usage
- `Decimal(str(row["risk_score"]))`: correct pattern (string conversion avoids float precision issues)
- `PREDICTION_WINDOW_DAYS` stored as plain int: correct (DynamoDB accepts int for Number type)
- `ttl` stored as int (epoch seconds): correct for DynamoDB TTL feature

### S3 paths
- `MODEL_PREFIX = "ed-prediction/v1"`: no leading slash
- `s3_key = f"{MODEL_PREFIX}/train/training_data.csv"`: produces `ed-prediction/v1/train/training_data.csv`, no leading slash
- `s3_uri = f"s3://{bucket}/{s3_key}"`: correct URI format

### scikit-learn API usage
- `GradientBoostingClassifier(**MODEL_PARAMS)`: all params valid (`n_estimators`, `max_depth`, `learning_rate`, `min_samples_leaf`, `subsample`, `random_state`)
- `model.fit(X_train, y_train)`: correct
- `model.predict_proba(X)[:, 1]`: correct (returns probability of class 1)
- `model.feature_importances_`: correct attribute name for fitted GBT
- `train_test_split(X, y, test_size, random_state, stratify)`: correct
- `roc_auc_score(y_test, y_prob)`: correct (takes true labels and probabilities)
- `average_precision_score(y_test, y_prob)`: correct

### SageMaker references
- Step 6 mentions SageMaker XGBoost expects "target column first, no header row": correct for built-in XGBoost algorithm
- `ServerSideEncryption="aws:kms"` on `put_object`: correct parameter value for KMS encryption
- IAM permissions listed in Setup section are appropriate and specific

### Logical flow
The pipeline follows a clear pedagogical progression:
1. Config (what levers exist) -> 2. Data (what inputs look like) -> 3. Training (how the model learns) -> 4. Evaluation (how we know it works) -> 5. Scoring (how we use it) -> 6. Storage (where results go) -> 7. S3 upload (SageMaker handoff)

This ordering builds understanding incrementally. Each step's comments reference why it exists in the broader clinical workflow.

---

## What Is Clean

- Synthetic data generation produces realistic distributions with clinically motivated correlations (age drives chronic conditions, chronic conditions drive ED utilization). The outcome generation via logistic model is clearly documented as synthetic, not circular.
- Risk tier thresholds are externalized with operational context (nurse capacity, outreach cadence). A reader understands these are business decisions, not model outputs.
- The `evaluate_model` function focuses on metrics that matter clinically (precision at threshold, tier distribution) rather than just academic metrics (accuracy).
- DynamoDB TTL pattern correctly auto-expires stale predictions after the prediction window.
- The filtering of LOW risk patients before DynamoDB write is a smart operational choice, well-explained.
- The "Gap Between This and Production" section is comprehensive and covers temporal validation, calibration, fairness, SHAP, drift detection, consent, and network isolation.
- Comments consistently explain clinical "why" (e.g., why gradient boosting over logistic regression, why precision matters more than recall for care managers).
- The `batch_writer` usage correctly handles DynamoDB's 25-item batch limit internally.
- KMS encryption on S3 upload demonstrates security-by-default for PHI-adjacent data.
