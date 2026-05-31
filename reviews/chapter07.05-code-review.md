# Code Review: Recipe 7.5 - 30-Day Readmission Risk

**Reviewed:** `chapter07.05-python-example.md`
**Against:** `chapter07.05-30-day-readmission-risk.md`
**Lines of Python:** ~550 (across 9 code blocks)
**Severity levels:** ERROR (code won't work), WARNING (misleading), NOTE (improvement)

---

## Verdict: PASS

The Python companion is well-structured, pedagogically sound, and faithfully implements the main recipe's pseudocode. The synthetic data generation produces realistic distributions, the model training pipeline is correct, top-level DynamoDB numerics use Decimal properly, and boto3 API calls are accurate. Two warnings and several notes below, but nothing that would cause the runnable pipeline to fail or seriously mislead a reader.

---

## Findings

### WARNING 1: `score_patient` uses -999 sentinel but model was trained with median imputation

**Location:** `score_patient` function, missing value handling

During training (`train_readmission_model`), missing lab values are imputed with column medians and binary `_missing` indicators are added. But `score_patient` replaces missing values with `-999` and comments "sentinel for missing (XGBoost handles this)."

scikit-learn's `GradientBoostingClassifier` does NOT handle missing value sentinels natively like XGBoost does. Passing -999 for `albumin_last` (training range 1.5-5.0) would produce wildly incorrect tree splits.

The full pipeline in `run_scoring_pipeline` correctly imputes before calling `score_patient`, so end-to-end execution is correct. But the comment is misleading, and a reader calling `score_patient` directly (as its docstring implies is valid) would get garbage predictions.

**Fix:** Add a prominent comment at the top of `score_patient` noting the caller must impute missing values first, and change the -999 comment from "XGBoost handles this" to "safety fallback for unexpected nulls; caller should impute before calling."

---

### WARNING 2: `store_risk_score` passes floats inside nested `risk_drivers` list to DynamoDB

**Location:** `store_risk_score` function, line where `risk_drivers` is included in the item

```python
item = {
    ...
    "risk_drivers": score_result["risk_drivers"],
    ...
}
```

The `risk_drivers` list contains dicts with `"value": features[i]` (numpy int/float) and `"importance": round(float(importances[i]), 4)` (Python float). DynamoDB's `TypeSerializer` rejects float types even when nested inside lists and maps. This would raise `TypeError: Float types are not supported. Use Decimal types instead` if `store_risk_score` were called with actual score results.

The `__main__` pipeline never calls `store_risk_score` (it prints a note that scores "would be written to DynamoDB"), so this won't manifest during execution. But a reader copying this function into their code would hit the error immediately.

**Fix:** Convert numeric values in `risk_drivers` to Decimal or cast to plain Python int/str before insertion:

```python
"risk_drivers": [
    {
        "feature": d["feature"],
        "value": Decimal(str(d["value"])),
        "importance": Decimal(str(d["importance"])),
    }
    for d in score_result["risk_drivers"]
],
```

---

### NOTE 1: `fit_platt_scaling` is defined but never called in the pipeline

**Location:** Step 3, `fit_platt_scaling` function

The function teaches how calibration parameters are learned, but the pipeline uses hardcoded `CALIBRATION_A` and `CALIBRATION_B` constants. The connection between fitting and applying is never demonstrated. Adding a call in `__main__` (even just to print the fitted parameters) would complete the pedagogical arc.

---

### NOTE 2: Platt scaling applied to probabilities rather than logits

**Location:** `platt_scale` function

Standard Platt scaling transforms raw decision function outputs (logits) through a sigmoid. Here it's applied to `predict_proba` output which is already a probability in [0, 1]. This is mathematically valid but unconventional. With `a = -1.2, b = 0.3`, the transform compresses the output range significantly (input 0.5 maps to ~0.43). Since the parameters are synthetic and `fit_platt_scaling` would learn appropriate values for whatever input space is used, this isn't wrong, but a reader familiar with calibration literature might be confused.

---

### NOTE 3: `risk_drivers` uses global feature importance, not per-patient explanations

**Location:** `score_patient`, risk drivers section

The code uses `model.feature_importances_` (global, same for every patient) filtered by a threshold. Every patient with the same non-missing features gets the same "top drivers" regardless of their specific values. The comment correctly notes SHAP would be used in production. Acceptable simplification for teaching.

---

### NOTE 4: Encounter ID generation allows potential duplicates

**Location:** `generate_synthetic_discharges`, encounter_id column

```python
"encounter_id": [f"ENC-{rng.integers(1000000, 9999999)}" for _ in range(n_patients)],
```

Drawing 3000 IDs from a 9M range has low but nonzero collision probability. Fine for synthetic teaching data.

---

## Verification of Key Technical Claims

**boto3 API calls verified:**
- `dynamodb.Table(name).put_item(Item={...})` - correct resource API usage
- `sns_client.publish(TopicArn=..., Subject=..., Message=..., MessageAttributes={...})` - correct. `MessageAttributes` structure with `DataType` and `StringValue` keys is correct
- `sagemaker_runtime.invoke_endpoint(EndpointName=..., ContentType="text/csv", Body=...)` - correct service name (`sagemaker-runtime`), correct method, correct parameters. Response parsing via `response["Body"].read().decode("utf-8")` is correct

**DynamoDB Decimal handling:** Top-level numerics (`probability`, `raw_score`) correctly use `Decimal(str(round(value, 4)))`. Nested floats in `risk_drivers` are not converted (see WARNING 2).

**S3 paths:** No S3 operations in this example. No leading-slash issues.

**scikit-learn API usage:** All correct - `GradientBoostingClassifier`, `predict_proba`, `roc_auc_score`, `brier_score_loss`, `calibration_curve`, `train_test_split` with `stratify`, `LogisticRegression`.

**Retry configuration:** `Config(retries={"max_attempts": 3, "mode": "adaptive"})` is valid botocore config.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Implementation | Match |
|-----------------|----------------------|-------|
| Step 1: Discharge Event Detection | Synthetic data generation (appropriate stand-in) | Yes |
| Step 2: Feature Assembly | Inline imputation in `run_scoring_pipeline` | Yes |
| Step 3: Model Scoring + Calibration | `score_patient` + `platt_scale` | Yes |
| Step 4: Risk Stratification + Routing | `score_patient` tiers + `route_interventions` | Yes |
| Step 5: Outcome Tracking | Omitted (noted in Gap to Production) | Acceptable |

Intervention routing logic matches between pseudocode and Python: HIGH tier gets nurse callback + condition-specific interventions (medication, CHF, social), MEDIUM tier gets automated check-in + follow-up scheduling, LOW tier gets nothing additional. Threshold values (0.35, 0.20) match.

---

*Review complete. Two warnings, neither blocking the runnable pipeline. Code is pedagogically sound and executes correctly end-to-end via `__main__`.*
