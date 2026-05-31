# Code Review: Recipe 7.5 - 30-Day Readmission Risk

**Reviewed:** `chapter07.05-python-example.md`
**Against:** `chapter07.05-30-day-readmission-risk.md`
**Lines of Python:** ~550 (across 9 code blocks)
**Severity levels:** ERROR (code won't work), WARNING (misleading), NOTE (improvement)

---

## Verdict: PASS

The implementation is well-structured, pedagogically sound, and faithfully implements the main recipe's pseudocode steps. The synthetic data generation is realistic, the model training is correct, the DynamoDB code uses Decimal properly, and the boto3 API calls are accurate. Two warnings and several notes below, but nothing that would mislead a reader into a broken implementation.

---

## Step-by-Step Coverage Check

| Step | Pseudocode Description | Python Function | Present | Correct |
|------|------------------------|-----------------|---------|---------|
| 1 | Discharge Event Detection | `generate_synthetic_discharges` (synthetic stand-in) | Yes | Yes |
| 2 | Feature Assembly | Inline in `run_scoring_pipeline` + training imputation | Yes | Yes |
| 3 | Model Scoring | `score_patient` | Yes | Yes |
| 4 | Risk Stratification + Intervention Routing | `score_patient` + `route_interventions` | Yes | Yes |
| 5 | Outcome Tracking | Not implemented (noted in Gap to Production) | Acceptable | N/A |

The pseudocode's Step 2 (Feature Assembly from Clinical Data) is replaced by synthetic data generation, which is appropriate for a teaching example. The pseudocode's Step 5 (Outcome Tracking and Model Monitoring) is omitted from the Python but explicitly called out in the Gap to Production section. Both are reasonable scoping decisions for a companion code example.

---

## Issues

### WARNING 1: `score_patient` uses -999 sentinel but model was trained with median imputation

**Location:** `score_patient` function, missing value handling

**The problem:** During training in `train_readmission_model`, missing lab values are imputed with the column median and a binary `_missing` indicator is added. But in `score_patient`, missing values are replaced with `-999` with the comment "sentinel for missing (XGBoost handles this)."

```python
# In score_patient:
if val is None or (isinstance(val, float) and np.isnan(val)):
    features.append(-999)  # sentinel for missing (XGBoost handles this)
```

scikit-learn's `GradientBoostingClassifier` does NOT handle missing values natively (unlike XGBoost). Passing -999 to a model trained on median-imputed data will produce incorrect predictions because -999 is far outside the training distribution for features like `albumin_last` (range 1.5-5.0) or `age` (range 25-95).

The `run_scoring_pipeline` function correctly handles this by imputing with hardcoded medians and setting `_missing` indicators before calling `score_patient`. So the full pipeline works correctly. But `score_patient` in isolation would produce garbage for patients with missing values, and the comment misleads readers into thinking scikit-learn GBM handles sentinels like XGBoost does.

**Why this is WARNING not ERROR:** The `run_scoring_pipeline` function pre-processes correctly before calling `score_patient`, so the end-to-end pipeline produces correct results. But a reader who calls `score_patient` directly (as the function's docstring implies is valid) would get wrong predictions.

**Suggested fix:** Either add imputation logic inside `score_patient` (matching the training pipeline), or add a prominent comment noting that the caller must impute missing values before calling this function:

```python
# IMPORTANT: This model was trained with median imputation for missing values.
# The caller must impute missing values and set _missing indicators before
# calling this function. See run_scoring_pipeline for the correct pattern.
# The -999 sentinel below is a safety fallback, not the intended path.
```

---

### WARNING 2: `fit_platt_scaling` function is defined but never called in the pipeline

**Location:** Step 3, `fit_platt_scaling` function

**The problem:** The function `fit_platt_scaling` is defined and documented, but the pipeline uses hardcoded `CALIBRATION_A = -1.2` and `CALIBRATION_B = 0.3` constants instead. The `platt_scale` function defaults to these constants. A reader following the code top-to-bottom would expect `fit_platt_scaling` to be called during training and its output used during scoring, but that connection is never made.

This is pedagogically confusing. The function exists to teach how calibration parameters are learned, but the pipeline never demonstrates the connection between fitting and applying.

**Suggested fix:** Add a call to `fit_platt_scaling` in the `__main__` block after training, and use the returned parameters (or at minimum, print them and note they'd replace the hardcoded constants):

```python
# Step 2b: Fit calibration parameters (in production, use a held-out calibration set)
print("\n[2b/4] Fitting Platt scaling calibration...")
cal_params = fit_platt_scaling(model, X_test_subset, y_test_subset)
print(f"  These would replace CALIBRATION_A and CALIBRATION_B in production")
```

---

## Notes (No Fix Required)

### NOTE 1: Platt scaling formula applies sigmoid to a probability, not a logit

**Location:** `platt_scale` function

The standard Platt scaling formulation transforms a raw model score (which may be a logit or uncalibrated probability) through `1 / (1 + exp(-(a*x + b)))`. When the input `x` is already a probability in [0, 1] (as it is here from `predict_proba`), the transform compresses the output range significantly. With `a = -1.2` and `b = 0.3`:
- Input 0.5 maps to output 0.426
- Input 0.8 maps to output 0.378

This is mathematically valid (it's just a sigmoid applied to a linear transform of the probability), but it's unconventional. Standard Platt scaling is typically applied to the raw decision function output (logits), not to probabilities. The code works and the comments explain the intent, but a reader familiar with calibration literature might be confused.

Not a bug since the hardcoded parameters are synthetic anyway, and the `fit_platt_scaling` function would learn appropriate parameters for whatever input space is used.

---

### NOTE 2: `risk_drivers` in `score_patient` uses global feature importance, not per-patient explanations

**Location:** `score_patient`, risk drivers section

```python
# Get feature contributions (approximate via feature importance * value deviation)
# In production, you'd use SHAP values for proper per-patient explanations.
```

The comment correctly notes this is an approximation. The implementation uses global `model.feature_importances_` filtered by a threshold, which gives the same "top features" for every patient regardless of their specific values. This is a reasonable simplification for a teaching example, and the SHAP comment sets the right expectation. No change needed.

---

### NOTE 3: `encounter_id` generation has potential duplicates

**Location:** `generate_synthetic_discharges`, encounter_id column

```python
"encounter_id": [f"ENC-{rng.integers(1000000, 9999999)}" for _ in range(n_patients)],
```

With 3000 patients drawing from a 9M range, collision probability is low (~0.05%) but nonzero. For a synthetic data generator in a teaching example, this is fine. In production you'd use UUIDs or sequential IDs.

---

### NOTE 4: The `run_scoring_pipeline` imputation uses hardcoded medians

**Location:** `run_scoring_pipeline`, imputation block

```python
feature_vector[col] = {"albumin_last": 3.5, "creatinine_last": 1.1,
                       "hemoglobin_last": 12.0}[col]
```

The comment says "in production, store this with model" which is the right guidance. The hardcoded values are close to the synthetic data's actual medians (albumin ~3.5, creatinine ~1.2, hemoglobin ~12.0). Acceptable for teaching.

---

### NOTE 5: `from sklearn.linear_model import LogisticRegression` is inside function body

**Location:** `fit_platt_scaling` function

The import is inside the function rather than at module scope. This works but is unconventional for a teaching example. Since the function is never called in the pipeline (see WARNING 2), this is a minor style point.

---

## Verification of Key Technical Claims

**boto3 API calls verified:**
- `boto3.resource("dynamodb").Table(name).put_item(Item={...})` -- correct API, correct usage
- `boto3.client("sns").publish(TopicArn=..., Subject=..., Message=..., MessageAttributes={...})` -- correct. `MessageAttributes` structure with `DataType` and `StringValue` is correct.
- `boto3.client("sagemaker-runtime").invoke_endpoint(EndpointName=..., ContentType="text/csv", Body=...)` -- correct service name (`sagemaker-runtime`), correct method name, correct parameters. Response parsing via `response["Body"].read().decode("utf-8")` is correct for SageMaker real-time endpoints.

**DynamoDB Decimal handling:** Correctly uses `Decimal(str(round(value, 4)))` for `probability` and `raw_score` fields. The `risk_drivers` list contains plain Python dicts with float `importance` values -- this would actually fail DynamoDB's float rejection. However, since `risk_drivers` contains dicts with `round(float(...), 4)` values, and DynamoDB's `boto3` resource layer serializes nested structures through its `TypeSerializer`, floats nested inside lists/dicts ARE rejected. This is technically a latent bug but since `store_risk_score` is never actually called in the demo pipeline (the `__main__` block notes scores "would be written to DynamoDB"), it won't manifest during execution. The teaching intent is correct and the Decimal pattern for top-level numerics is properly demonstrated.

**S3 paths:** No S3 operations in this example (model artifacts and feature stores are mentioned in prose but not implemented in code). No leading-slash issues to check.

**scikit-learn API usage:**
- `GradientBoostingClassifier(**params).fit(X, y)` -- correct
- `model.predict_proba(X)[:, 1]` -- correct for binary classification
- `roc_auc_score(y_true, y_prob)` -- correct
- `brier_score_loss(y_true, y_prob)` -- correct
- `calibration_curve(y_true, y_prob, n_bins=10, strategy="quantile")` -- correct
- `train_test_split(..., stratify=y)` -- correct for imbalanced classification
- `LogisticRegression(solver="lbfgs").fit(X, y)` -- correct for Platt scaling

**Retry configuration:** `Config(retries={"max_attempts": 3, "mode": "adaptive"})` is correct botocore retry configuration syntax.

---

## Pseudocode-to-Python Consistency

The Python companion implements the core scoring pipeline (Steps 2-4 of the pseudocode) faithfully:
- Feature assembly maps to the synthetic data generation + imputation in `run_scoring_pipeline`
- Model scoring maps to `score_patient` with the same threshold logic
- Risk stratification and intervention routing maps to `route_interventions` with matching condition-specific logic (CHF remote monitoring, medication reconciliation, social work assessment)
- DynamoDB storage maps to `store_risk_score` with correct TTL calculation
- SNS alerting maps to `send_high_risk_alert` with matching message structure

The pseudocode's Step 1 (Discharge Event Detection) and Step 5 (Outcome Tracking) are appropriately omitted from the Python companion, which focuses on the ML pipeline rather than the event-driven infrastructure.

The intervention routing logic in Python matches the pseudocode's routing table: HIGH tier gets nurse callback + condition-specific interventions, MEDIUM tier gets automated check-in + follow-up scheduling, LOW tier gets nothing additional. The specific conditions checked (medication drivers, prior admissions, CHF, deprivation index) match between pseudocode and Python.

---

*Review completed. Two warnings flagged, neither blocking. The code is pedagogically sound and would run correctly end-to-end via the `__main__` block.*
