# Code Review: Recipe 7.2

## Summary

The Python companion for Propensity to Pay Scoring is well-structured, pedagogically sound, and faithfully implements the pseudocode from the main recipe. The code builds understanding progressively, comments explain "why" not just "what," and boto3/SageMaker API calls are correct. DynamoDB numeric values are properly wrapped in `Decimal`. S3 keys have no leading slashes. The calibration step correctly uses isotonic regression (a reasonable alternative to the Platt scaling mentioned in the pseudocode, and the code explains why). One minor inconsistency exists between the pseudocode's batch transform instance type and the Python's, and a few notes for improvement, but nothing that would prevent the code from running or mislead a reader.

---

## Issues

### Issue 1: Batch Transform Instance Type Mismatch with Pseudocode

- **File:** Python companion (`chapter07.02-python-example.md`)
- **Location:** Config section (`TRANSFORM_INSTANCE_TYPE`) and `run_batch_scoring` function
- **Severity:** NOTE
- **Description:** The pseudocode in the main recipe specifies `instance_type: "ml.m5.xlarge"` for the batch transform job. The Python companion uses `TRANSFORM_INSTANCE_TYPE = "ml.m5.large"` (one size smaller). This is a trivial difference that doesn't affect correctness, but a reader cross-referencing the two files might wonder which is correct. Both work fine for the stated workload.
- **Suggested fix:** Either align the Python to `ml.m5.xlarge` to match the pseudocode, or add a brief comment noting the smaller instance is sufficient for the demo dataset.

---

### Issue 2: Calibration Uses Simulated Random Scores Instead of Actual Model Output

- **File:** Python companion (`chapter07.02-python-example.md`)
- **Location:** `run_propensity_pipeline`, Step 5 section
- **Severity:** WARNING
- **Description:** In the "Putting It All Together" function, Step 5 generates calibration inputs with `raw_scores = np.random.beta(2, 2, size=len(df))` and a comment saying "placeholder." The calibration model is then fitted on these random scores against the true labels, and the calibrated output is used for DynamoDB storage and strategy routing. While the code acknowledges this is a placeholder, a reader running the full pipeline end-to-end will get meaningless propensity scores that have no relationship to the actual model's predictions. The strategy routing summary will appear to work but the numbers will be nonsensical. A more pedagogically honest approach would be to either (a) load the actual batch transform output from S3, or (b) use the synthetic data's `pay_probability` array (which was used to generate labels) as a stand-in for raw model output, which would produce meaningful calibration behavior.
- **Suggested fix:** Replace `raw_scores = np.random.beta(2, 2, size=len(df))` with something derived from the synthetic data generation, e.g.:
  ```python
  # Simulate raw model predictions using the underlying pay probability
  # (in production, these come from the batch transform output in S3).
  raw_scores = pay_probability + np.random.normal(0, 0.05, size=len(df))
  raw_scores = np.clip(raw_scores, 0.01, 0.99)
  ```
  This would require returning `pay_probability` from `generate_synthetic_balance_data` or recomputing it. Alternatively, add a more prominent warning that the scores in Steps 5-6 are not meaningful when run end-to-end.

---

### Issue 3: `pay_probability` Not Accessible in Pipeline Function

- **File:** Python companion (`chapter07.02-python-example.md`)
- **Location:** `run_propensity_pipeline`, Step 5
- **Severity:** NOTE
- **Description:** Related to Issue 2. The `generate_synthetic_balance_data` function computes `pay_probability` internally but only returns the DataFrame (which contains the binary outcome, not the underlying probability). If a reader wanted to use the true probability as a stand-in for model output (the natural pedagogical choice), they'd need to modify the function signature. This is a minor structural issue that slightly reduces the "run it and learn" value of the example.
- **Suggested fix:** No change required for correctness. If Issue 2 is addressed, consider returning `pay_probability` as a second return value from `generate_synthetic_balance_data`.

---

### Issue 4: Isotonic Regression vs. Platt Scaling Terminology

- **File:** Python companion (`chapter07.02-python-example.md`)
- **Location:** Step 5, `fit_calibration_model` function
- **Severity:** NOTE
- **Description:** The main recipe's pseudocode explicitly calls for "Platt scaling" (`fit_platt_scaling`). The Python companion uses isotonic regression instead and includes a good explanation of why ("tends to work better than Platt scaling when the calibration curve is non-monotonic"). This is a defensible pedagogical choice and the explanation is clear, but a reader following the pseudocode step-by-step might be confused by the switch. The comment adequately addresses this, so no fix is needed, but noting it for completeness.
- **Suggested fix:** None required. The inline comment explaining the choice is sufficient.

---

### Issue 5: `scoring_input_uri` Points to Object, Not Prefix

- **File:** Python companion (`chapter07.02-python-example.md`)
- **Location:** `prepare_scoring_input` function return value and `run_batch_scoring` `data` parameter
- **Severity:** WARNING
- **Description:** `prepare_scoring_input` returns `f"s3://{ML_BUCKET}/{scoring_key}"` which is a full object URI (e.g., `s3://bucket/features/open-balances/scoring-input.csv`). This is passed to `transformer.transform(data=scoring_input_uri, ...)`. SageMaker Batch Transform's `data` parameter accepts either an S3 object URI or an S3 prefix. Passing a single object URI works correctly, so this is not a bug. However, the main recipe's pseudocode passes `feature_file_path` which is described as a path to the feature file, so this is consistent. No actual error, but worth noting that in production with multiple input files, you'd pass the prefix instead.
- **Suggested fix:** None required for correctness. Optionally add a comment noting that for multiple input files, pass the S3 prefix instead of a single object URI.

---

## Pseudocode vs. Python Consistency

The Python implementation follows the pseudocode's logical flow faithfully:

**Step 1 (Feature Engineering):** The pseudocode defines `compute_payment_features` pulling from billing/history/engagement systems. The Python generates synthetic data with the same feature schema. All 18 features from the pseudocode are present in the synthetic data. Consistent.

**Step 2 (Model Training):** The pseudocode's `train_propensity_model` maps to the Python's `train_propensity_model`. Hyperparameters match exactly (objective, eval_metric, num_round, max_depth, eta, subsample, colsample_bytree, scale_pos_weight). The Python adds the upload step (Step 2 in Python) which is implicit in the pseudocode. Consistent.

**Step 3 (Batch Scoring):** The pseudocode's `score_open_balances` maps to the Python's `run_batch_scoring`. Both use batch transform with CSV content type and Line split. The Python separates input preparation into its own function, which is a reasonable structural choice. Consistent.

**Step 4 (Strategy Engine):** The pseudocode's `apply_collection_strategy` maps directly to the Python's `apply_collection_strategy`. Thresholds match (0.75 high, 0.40 medium). Routing logic matches (high -> standard_statements, medium+high_amount -> financial_counselor_outreach, medium+low_amount -> payment_plan_offer, low -> financial_assistance_screening). The $500 amount threshold for counselor vs. payment plan is consistent. Consistent.

**Calibration:** The pseudocode uses Platt scaling; the Python uses isotonic regression with an explanation. Acceptable pedagogical deviation (see Issue 4).

---

## Verdict

**PASS**

- 0 ERROR findings
- 2 WARNING findings (below the 3-WARNING threshold for FAIL)
- 3 NOTE findings

The code is correct, would run without errors given AWS credentials, teaches the right patterns, and faithfully implements the main recipe's architecture. The two warnings are about pedagogical clarity in the end-to-end demo (random placeholder scores making the full pipeline output meaningless) and a minor terminology note. Neither would cause runtime failures or teach bad habits. The DynamoDB Decimal handling is correct throughout. S3 keys are clean. boto3 API calls use correct method names and parameters.
