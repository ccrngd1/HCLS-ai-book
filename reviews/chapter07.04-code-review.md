# Code Review: Recipe 7.4 - ED Visit Prediction

**Reviewer:** Tech Code Reviewer
**Date:** 2026-06-04
**Files reviewed:**
- `chapter07.04-python-example.md` (Python companion)
- `chapter07.04-ed-visit-prediction.md` (Main recipe pseudocode)

**Validation performed:**
- Python syntax check across all 7 code blocks: PASSED
- boto3 API signatures verified (S3, DynamoDB)
- DynamoDB Decimal usage confirmed
- S3 key prefixes checked for leading slashes (none found)
- scikit-learn API usage verified
- Pseudocode-to-Python consistency checked

---

## Summary

Solid implementation with excellent pedagogical flow. The pipeline progresses logically from synthetic data through training, evaluation, scoring, and storage. Comments are outstanding throughout, consistently explaining clinical rationale and operational context. The code correctly uses `Decimal` for DynamoDB, timezone-aware datetimes, and proper boto3 API signatures. One warning about a misleading explanation pattern (despite normalization fix), and one note about a feature set mismatch between the pseudocode and Python. No runtime-breaking errors.

---

## Verdict: PASS

---

## Issues

### Issue 1: Per-patient "top factors" still misleading despite normalization

**Severity:** WARNING
**File:** `chapter07.04-python-example.md`
**Location:** Step 4, `score_patients()`, contribution calculation

```python
patient_normalized = (patient_features - X_min) / (X_max - X_min + 1e-8)
contributions = patient_normalized * feature_importances
top_indices = np.argsort(contributions)[-3:][::-1]
```

The code now normalizes features to 0-1 before multiplying by global importances, which is an improvement over raw values. However, this still produces incorrect per-patient attributions. Global feature importance measures how much a feature contributes to the model's overall predictive power, not how much it contributes to a specific patient's score. A patient with `ed_visits_last_12m=0` (normalized to 0.0) correctly gets zero contribution for that feature, but a patient at the median (normalized ~0.5) gets credited half the global importance even if that median value is exactly what pushes the model toward "low risk" for them.

The inline WARNING comment is excellent and clearly states "Do NOT show these explanations to clinicians." However, the code then stores the result in `top_factors` and the pipeline runner prints it as part of the "outreach worklist." A reader following the example sees clinician-facing output built on a method the code itself warns against.

**Fix:** Consider adding a comment at the print statement in `run_ed_prediction_pipeline()` reinforcing this caveat:

```python
# NOTE: These "top factors" are approximate. See the WARNING in score_patients()
# about why SHAP values are required for any clinician-facing deployment.
```

No code change required. The warning is present but could be more visible at the output point.

---

### Issue 2: Feature set mismatch between pseudocode and Python

**Severity:** NOTE
**File:** `chapter07.04-python-example.md` vs `chapter07.04-ed-visit-prediction.md`
**Location:** Feature engineering (Step 2 pseudocode vs Python FEATURE_COLUMNS)

The main recipe's pseudocode (Step 2) engineers derived features like `ed_acceleration`, `ed_to_total_ratio`, `med_risk_score`, `ed_recency`, `pcp_disengaged`, and `complexity_adherence_interaction`. The Python companion uses a different, simpler feature set: raw counts (`ed_visits_last_12m`, `ed_visits_last_3m`), binary indicators (`has_diabetes`, `has_chf`), and direct measurements (`distance_to_nearest_ed_miles`).

This is a deliberate pedagogical choice (the Python companion states it's "deliberately simplified"), and the main recipe's pseudocode explicitly calls out feature engineering as the "80% of the work" step. The Python skips that complexity to focus on the model training/scoring pipeline shape. This is acceptable but worth noting for readers who expect the Python to mirror the pseudocode exactly.

The scoring step (Step 3 pseudocode) references SHAP values (`model.explain(input_vector)`) which the Python replaces with the normalized-importance approximation. This is called out in the gap-to-production section.

**Fix:** No action required. The difference is intentional and pedagogically sound. The Python companion's intro paragraph explicitly warns it's "deliberately simplified."

---

### Issue 3: `X_min` and `X_max` computed from scoring batch, not training data

**Severity:** WARNING
**File:** `chapter07.04-python-example.md`
**Location:** Step 4, `score_patients()`, lines computing normalization bounds

```python
X_min = X.min().values
X_max = X.max().values
```

These min/max values are computed from the current scoring batch (`patients_df`), not from the training data. This means the normalization is inconsistent across scoring runs: if tomorrow's batch has a patient with `ed_visits_last_12m=20` (shifting `X_max`), every other patient's normalized value changes. In production, normalization bounds should come from training data statistics.

For a teaching example this is minor (the explanation output is already flagged as unreliable), but it teaches an anti-pattern: data-dependent normalization at inference time. A reader might carry this pattern into a real pipeline where feature scaling should be fixed at training time.

**Fix:** Add a brief comment noting this limitation:

```python
# In production, use min/max from training data (stored with the model artifact)
# so normalization is consistent across scoring runs.
X_min = X.min().values
X_max = X.max().values
```

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

### Datetime handling
- `datetime.now(timezone.utc).isoformat()`: correct, timezone-aware, no deprecated `utcnow()`
- TTL calculation uses `datetime.now(timezone.utc) + timedelta(...)`: correct

### scikit-learn API usage
- `GradientBoostingClassifier(**MODEL_PARAMS)`: all params valid (`n_estimators`, `max_depth`, `learning_rate`, `min_samples_leaf`, `subsample`, `random_state`)
- `model.fit(X_train, y_train)`: correct
- `model.predict_proba(X)[:, 1]`: correct (returns probability of class 1)
- `model.feature_importances_`: correct attribute name for fitted GBT
- `train_test_split(X, y, test_size, random_state, stratify)`: correct
- `roc_auc_score(y_test, y_prob)`: correct (takes true labels and probabilities)
- `average_precision_score(y_test, y_prob)`: correct
- `calibration_curve(y_test, y_prob, n_bins=5, strategy="uniform")`: correct

### Pseudocode-to-Python consistency

| Pseudocode Step | Python Step | Consistent? |
|-----------------|-------------|-------------|
| Step 1: Data aggregation | Step 1: generate_synthetic_patients() | Yes (synthetic replaces real ETL, appropriate for demo) |
| Step 2: Feature engineering | Skipped (uses raw features) | Intentional simplification, documented |
| Step 3: Model scoring | Steps 2-4: train + evaluate + score | Yes (Python separates training from inference, pseudocode combines) |
| Step 4: Calibration & stratification | Step 4: score_patients() assigns tiers | Partial (Python uses fixed thresholds, pseudocode uses capacity-based ranking). Acceptable simplification. |
| Step 5: Store and route | Step 5: store_risk_scores() | Yes (DynamoDB write, TTL, tier filtering all match) |

The Python companion correctly implements a simplified version of the pseudocode pipeline. All simplifications are explicitly called out in prose.

### Logical flow
The pipeline follows a clear pedagogical progression:
1. Config (what levers exist) -> 2. Data (what inputs look like) -> 3. Training (how the model learns) -> 4. Evaluation (how we know it works) -> 5. Scoring (how we use it) -> 6. Storage (where results go) -> 7. S3 upload (SageMaker handoff)

This ordering builds understanding incrementally. Each step's comments reference why it exists in the broader clinical workflow.

---

## What Is Clean

- Synthetic data generation produces realistic distributions with clinically motivated correlations. The outcome generation via logistic model is clearly documented as synthetic, not circular.
- Risk tier thresholds are externalized as constants with operational context explaining how to calibrate them to care management capacity.
- The `evaluate_model` function covers clinically relevant metrics (precision at threshold, calibration error, tier distribution) alongside standard ML metrics.
- DynamoDB TTL pattern correctly auto-expires stale predictions.
- Filtering LOW risk patients before DynamoDB write is a smart operational choice, well-explained.
- The "Gap Between This and Production" section is comprehensive: temporal validation, calibration, fairness, SHAP, drift detection, consent, VPC isolation, IAM least-privilege, and DynamoDB encryption.
- Comments consistently explain clinical "why" (why gradient boosting over LR, why calibration matters for care managers, why temporal splits matter).
- The `batch_writer` correctly handles DynamoDB's 25-item batch limit internally.
- KMS encryption on S3 upload demonstrates security-by-default for PHI-adjacent data.
- The temporal validation caveat in `train_ed_prediction_model` is prominently placed and well-explained.
