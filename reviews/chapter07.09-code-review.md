# Code Review: Recipe 7.9 - Mortality Risk Scoring (ICU)

**Reviewed:** `chapter07.09-python-example.md`
**Against:** `chapter07.09-mortality-risk-scoring-icu.md`
**Severity levels:** ERROR (code won't work), WARNING (misleading), NOTE (improvement)

---

## Verdict: FAIL

The Python companion has strong pedagogical structure and correctly implements most of the main recipe's pseudocode steps. However, there is one ERROR (incorrect SOFA renal scoring that produces wrong clinical values) and four WARNINGs (DynamoDB float issue, deprecated XGBoost parameter, SHAP API incompatibility, and feature schema mismatch). The ERROR alone triggers FAIL, and the WARNING count (4) independently exceeds the threshold.

---

## Findings

### ERROR 1: `sofa_renal` computed using liver scoring function

**Location:** `chapter07.09-python-example.md`, Step 2, `engineer_features()` function

```python
features["sofa_renal"] = compute_sofa_liver(features.get("creatinine_latest"))  # simplified
```

The code calls `compute_sofa_liver()` (which uses bilirubin thresholds: 1.2, 2.0, 6.0, 12.0 mg/dL) to score the renal component using creatinine. This produces clinically incorrect SOFA renal scores. The SOFA renal thresholds are: creatinine <1.2 = 0, 1.2-1.9 = 1, 2.0-3.4 = 2, 3.5-4.9 = 3, >=5.0 = 4. The liver thresholds happen to partially overlap numerically but the logic is inverted (`< threshold` vs `>=` threshold) and the clinical meaning is completely wrong.

A learner copying this pattern would produce a model with incorrect organ failure scoring. The comment says "simplified" but it's not simplified, it's wrong. A creatinine of 3.0 would score 2 via the liver function (bilirubin 3.0 < 6.0 = score 2), but the correct SOFA renal score for creatinine 3.0 is also 2 by coincidence. However, creatinine of 1.5 would score 1 via liver (1.5 > 1.2, < 2.0 = score 1), and the correct renal score is also 1. The numerical coincidence masks the conceptual error for some values, but for creatinine >= 5.0 the liver function returns 3 (bilirubin 5.0 < 6.0) while the correct renal score is 4.

**Fix:** Add a `compute_sofa_renal(creatinine)` function with the correct thresholds:
```python
SOFA_RENAL_THRESHOLDS = [
    (1.2, 0), (2.0, 1), (3.5, 2), (5.0, 3), (float("inf"), 4)
]
```

---

### WARNING 1: `top_contributors` contains float values that DynamoDB will reject

**Location:** `chapter07.09-python-example.md`, Step 5, `build_prediction_record()` function

The `build_prediction_record` function correctly converts top-level numeric fields to `Decimal`:

```python
"mortality_probability": Decimal(str(score_result["mortality_probability"])),
```

But `top_contributors` is stored directly from `score_result["top_contributors"]`, which contains `"shap_contribution": round(float(shap_val), 4)` and `"value": round(float(feat_val), 2)`. DynamoDB rejects Python `float` types. The code comment acknowledges this ("For nested structures (top_contributors), we'd need to recursively convert") but since the function is presented as the pattern for building the record, a learner would hit this error when they uncomment the `table.put_item(Item=record)` call.

**Fix:** Either recursively convert floats in `top_contributors` to `Decimal`, or add a helper function demonstrating the conversion pattern (e.g., `json.loads(json.dumps(top_contributors), parse_float=Decimal)`). The comment acknowledges the gap but the teaching value is lost if the record as-built would fail on write.

---

### WARNING 2: `use_label_encoder=False` removed in XGBoost 2.0+

**Location:** `chapter07.09-python-example.md`, Step 3, `train_mortality_model()` function

```python
raw_model = XGBClassifier(
    ...
    use_label_encoder=False,
    ...
)
```

The `use_label_encoder` parameter was deprecated in XGBoost 1.6 and removed in XGBoost 2.0. Since the `pip install` at the top doesn't pin a version, readers installing current xgboost (2.x) will get a `TypeError: __init__() got an unexpected keyword argument 'use_label_encoder'`. This is a common stumbling block for learners following older tutorials.

**Fix:** Remove `use_label_encoder=False` from the constructor. Add a comment noting that this parameter was required in XGBoost <2.0 but is no longer needed.

---

### WARNING 3: SHAP `shap_values` return format changed for binary classifiers

**Location:** `chapter07.09-python-example.md`, Step 4, `score_patient()` function

```python
shap_values = explainer.shap_values(feature_df)
shap_array = shap_values[0]  # single patient
```

In SHAP >=0.42 with `TreeExplainer` on a binary `XGBClassifier`, `shap_values()` returns a 2D numpy array of shape `(n_samples, n_features)` for the positive class, not a list of arrays indexed by class. The code `shap_values[0]` would return the SHAP values for the first feature across all samples (a single float), not the SHAP values for the first patient across all features.

The correct pattern for current SHAP versions is:
```python
shap_values = explainer.shap_values(feature_df)
shap_array = shap_values[0]  # works if shape is (1, n_features)
```

This actually works correctly when `feature_df` has exactly 1 row (which it does here), because `shap_values` has shape `(1, n_features)` and `shap_values[0]` gives the first (only) row. However, the comment "single patient" is misleading. If SHAP returns a list of two arrays (one per class, as in older versions), `shap_values[0]` gives the class-0 SHAP values, not the first patient. The code is ambiguous about which SHAP version it targets.

**Fix:** Use the `shap.Explainer` API which is version-stable, or add a version check comment. At minimum, change the comment to clarify: "shap_values shape is (1, n_features) for our single-row input; index [0] gets that row."

---

### WARNING 4: Feature engineering generates features not aligned with FEATURE_SCHEMA

**Location:** `chapter07.09-python-example.md`, Step 2, `engineer_features()` function

The vital signs loop iterates over `["heart_rate", "sbp", "map", "resp_rate", "spo2", "temp"]` and generates `_min_6h`, `_max_6h`, `_mean_6h` for all of them, plus `_std_6h` for `heart_rate` and `sbp`. This produces features like `spo2_max_6h`, `temp_mean_6h`, `resp_rate_std_6h` (wait, no, std is only for hr/sbp). Let me be precise:

The loop generates `temp_mean_6h` but FEATURE_SCHEMA only has `temp_min_6h` and `temp_max_6h`. It generates `spo2_max_6h` but FEATURE_SCHEMA only has `spo2_min_6h` and `spo2_mean_6h`. It generates `resp_rate_min_6h`, `resp_rate_max_6h`, `resp_rate_mean_6h` which are all in FEATURE_SCHEMA, so those are fine.

The mismatch means `engineer_features()` produces extra keys not in FEATURE_SCHEMA, and when `score_patient()` builds the feature vector via `[features.get(f, np.nan) for f in FEATURE_SCHEMA]`, the extra features are silently ignored. This isn't an error (the code runs), but it's misleading for a learner who might think all computed features feed the model.

Additionally, `map_min_6h` and `map_max_6h` are computed twice: once in the general loop and once explicitly afterward. The explicit computation overwrites the loop values with identical results, which is confusing.

**Fix:** Either adjust the loop to only compute the features actually in FEATURE_SCHEMA (using a config dict per vital), or add a comment explaining that the loop over-generates and the schema acts as a filter. Remove the duplicate `map_min_6h`/`map_max_6h` computation.

---

### NOTE 1: Pseudocode Step 4 (calibration) is merged into Step 3 in Python

**Location:** `chapter07.09-python-example.md`, Step 3

The main recipe has a distinct Step 4 "Apply local calibration" with its own function (`calibrate_score`) that loads hospital-specific calibration parameters from DynamoDB. The Python companion merges calibration into the training step (using `CalibratedClassifierCV` on the test set) and then applies it directly in `score_patient()`. This is a reasonable simplification for a local demo, but the structural difference from the pseudocode isn't called out.

A brief comment noting "In production, calibration is a separate step that loads hospital-specific parameters (see main recipe Step 4). Here we combine it with training for simplicity" would help readers map between the two files.

---

### NOTE 2: Confidence interval is not a Wilson score interval

**Location:** `chapter07.09-python-example.md`, Step 4, `score_patient()` function

The comment says "Wilson score interval approximation" but the code implements a normal approximation (Wald interval):

```python
ci_width = 1.96 * np.sqrt(calibrated_prob * (1 - calibrated_prob) / n_cal)
```

The Wilson score interval has a different formula that adjusts the center point. This is the standard Wald interval for a binomial proportion. The distinction matters pedagogically because the Wilson interval is specifically recommended over the Wald interval for extreme probabilities (near 0 or 1), which is exactly the regime where ICU mortality predictions often land.

**Fix:** Either rename the comment to "Wald interval approximation" (accurate for what the code does), or implement the actual Wilson interval if that's what's intended.

---

### NOTE 3: `run_full_pipeline()` uses `roc_auc_score` without import at point of use

**Location:** `chapter07.09-python-example.md`, "Putting It All Together" section

`roc_auc_score` and `brier_score_loss` are imported in Step 3's code block but used again in `run_full_pipeline()`. Since each code block in a cookbook is somewhat standalone, a reader assembling the final pipeline might miss that these were imported earlier. This is minor since the full file would have them imported, but for copy-paste learners it could cause confusion.

---

## Summary

The code is well-structured pedagogically, builds understanding progressively, and demonstrates the full ICU mortality scoring pipeline clearly. The synthetic data generation is realistic, the feature engineering is clinically sound (aside from the SOFA renal error), and the SHAP explanation layer is a strong teaching example. The "Gap to Production" section is excellent and comprehensive.

The ERROR (wrong SOFA renal scoring) is a clinical correctness issue that would produce incorrect organ failure assessments. The WARNINGs cover a DynamoDB type issue that would fail on actual writes, a deprecated XGBoost parameter that breaks on current versions, a SHAP API ambiguity, and feature schema misalignment. Together these would cause confusion or failures for learners following the code.

boto3 API calls (commented out) use correct method names and parameter structures: `dynamodb.Table().put_item(Item=...)`, `cloudwatch.put_metric_data(Namespace=..., MetricData=[...])`. S3 paths are not used directly. DynamoDB top-level numerics correctly use `Decimal`, though nested structures do not (WARNING 1).

---

*Reviewed 2026-05-31. Verdict: FAIL (1 ERROR, 4 WARNINGs, 3 NOTEs)*
