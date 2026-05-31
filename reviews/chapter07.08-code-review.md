# Code Review: Recipe 7.8 - Disease Progression Modeling

**Reviewed:** `chapter07.08-python-example.md`
**Against:** `chapter07.08-disease-progression-modeling.md`
**Severity levels:** ERROR (code won't work), WARNING (misleading), NOTE (improvement)

---

## Verdict: PASS

The Python companion is well-structured, pedagogically sound, and correctly implements the pseudocode steps from the main recipe. The code would run given the stated prerequisites. DynamoDB writes correctly use `Decimal`. No S3 paths have leading slashes. boto3 API calls are accurate. The lifelines survival analysis usage is correct.

---

## Findings

### WARNING 1: `cutoff` variable used before definition in `engineer_progression_features`

**Location:** `chapter07.08-python-example.md`, Step 2, `engineer_progression_features()` function, medication_changes_12mo section

The variable `cutoff` is defined inside the biomarker loop (`cutoff = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()`) but is then referenced outside that loop context in the medication changes calculation:

```python
features["medication_changes_12mo"] = sum(
    1 for m in meds
    if m.get("end_date") and m["end_date"] >= cutoff
)
```

If `CKD_BIOMARKERS` is empty (it won't be given the constant, but structurally), `cutoff` would be undefined. More importantly for a learner: the variable's definition is buried inside a loop iteration for a different purpose, making it non-obvious where it comes from.

**Fix:** Define `cutoff` at the top of the function body, before the biomarker loop, since it's used in multiple contexts. This also improves readability for learners.

---

### WARNING 2: Confidence interval approximation is misleading for learners

**Location:** `chapter07.08-python-example.md`, Step 4, `predict_progression()` function

The confidence intervals are computed using a hardcoded base standard error of 0.08 with a linear multiplier:

```python
se_multiplier = 1.0 + (months / 36.0) * 0.5
base_se = 0.08 * se_multiplier
ci_lower = max(0.0, progression_prob - 1.645 * base_se)
ci_upper = min(1.0, progression_prob + 1.645 * base_se)
```

The comment says "In production, use the model's variance estimates or ensemble disagreement" but doesn't clarify that this approximation has no statistical basis and produces intervals that are completely disconnected from the model's actual uncertainty. A learner might carry this pattern forward thinking it's a reasonable placeholder.

**Fix:** Add a comment explicitly stating: "These intervals are purely illustrative placeholders. They do NOT reflect actual model uncertainty. In production, use `cph.predict_survival_function` with confidence intervals via the `alpha` parameter in lifelines, or bootstrap resampling."

---

### WARNING 3: `concordance_index` sign convention may confuse learners

**Location:** `chapter07.08-python-example.md`, Step 3, `train_progression_model()` function

```python
valid_predictions = cph.predict_partial_hazard(valid_df[feature_cols])
c_index = concordance_index(
    valid_df["duration_months"],
    -valid_predictions.values.flatten(),  # negative because higher hazard = shorter time
    valid_df["event"],
)
```

The negation is correct (higher partial hazard means shorter survival, so you negate to align with the concordance_index expectation that higher predicted value = longer time). However, the comment "negative because higher hazard = shorter time" is incomplete. The `concordance_index` from lifelines expects that a higher predicted value corresponds to a longer event time. The negation converts "higher hazard" to "lower predicted survival time" which then needs to be negated again to become "higher value = longer time." The comment should explain the full chain.

**Fix:** Expand the comment to: "Negate because concordance_index expects higher values to predict longer survival, but predict_partial_hazard returns higher values for higher risk (shorter survival)."

---

### NOTE 1: Pseudocode Step 5 monitoring function not implemented in Python

**Location:** `chapter07.08-python-example.md`, Step 5

The main recipe's pseudocode Step 5 includes a `monitor_model_performance()` function that retrieves old predictions, compares against actual outcomes, computes calibration error, and triggers alarms. The Python companion only implements the `store_prediction()` portion and omits the monitoring function entirely.

This is acceptable since the "Gap to Production" section mentions monitoring, but a brief comment noting "monitoring logic omitted; see the main recipe's pseudocode Step 5 for the pattern" would help readers understand the gap.

---

### NOTE 2: `generate_synthetic_patient_timeline` doesn't generate all biomarkers in `CKD_BIOMARKERS`

**Location:** `chapter07.08-python-example.md`, Step 1

The constant `CKD_BIOMARKERS = ["eGFR", "creatinine", "albumin", "hemoglobin", "potassium"]` lists 5 biomarkers, but the synthetic data generator only produces `eGFR`, `creatinine`, and `HbA1c` (which isn't even in the list). The feature engineering step will hit the "missing biomarker" branch for albumin, hemoglobin, and potassium every time.

This isn't an error (the code handles missing biomarkers gracefully), but it means the model will never have trajectory features for 3 of the 5 declared biomarkers during the demo run. A learner might wonder why those features are always zero.

**Fix:** Either add a brief comment in the generator noting "we only simulate eGFR and creatinine for brevity; albumin, hemoglobin, and potassium would come from real lab data" or generate simple synthetic values for the remaining biomarkers.

---

### NOTE 3: SageMaker `SKLearn` framework version may be outdated

**Location:** `chapter07.08-python-example.md`, Step 6, `launch_sagemaker_training()`

```python
estimator = SKLearn(
    entry_point="train_progression_model.py",
    ...
    framework_version="1.2-1",
    ...
)
```

The `framework_version="1.2-1"` corresponds to scikit-learn 1.2. Current SageMaker SKLearn containers support up to 1.2-1 as of the latest documentation, so this is technically correct. However, the SageMaker SDK import path `from sagemaker.sklearn import SKLearn` is correct and current.

No action needed; just confirming accuracy.

---

## Summary

The code is pedagogically well-structured, builds understanding top-to-bottom, and correctly demonstrates the disease progression modeling pipeline. The lifelines API usage (`CoxPHFitter`, `predict_survival_function`, `predict_partial_hazard`, `concordance_index`) is accurate. DynamoDB writes properly use `Decimal` via the `json.loads(json.dumps(...), parse_float=Decimal)` pattern. S3 paths in `upload_training_data` use `session.upload_data()` which handles path construction correctly. The boto3 retry configuration and resource/client usage patterns are sound.

The three WARNINGs are all "misleading for learners" issues rather than correctness problems. The code would execute successfully given the stated prerequisites.

---

*Reviewed 2026-05-31. Verdict: PASS (0 ERRORs, 3 WARNINGs, 3 NOTEs)*
