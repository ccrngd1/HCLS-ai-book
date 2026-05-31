# Code Review: Recipe 7.2

## Summary

The Python companion for Propensity to Pay Scoring is well-constructed, pedagogically clear, and faithfully implements the main recipe's pseudocode pipeline. The code correctly uses `Decimal` for DynamoDB numeric values, avoids leading slashes in S3 keys, and demonstrates accurate boto3/SageMaker SDK usage throughout. The synthetic data generation is particularly strong, encoding realistic correlations between payment history features and outcomes that teach readers what the model should learn. The calibration step (isotonic regression) is a valuable addition that goes beyond many teaching examples. One warning-level issue around the `run_propensity_pipeline` function using simulated predictions instead of actual batch transform output, which could confuse readers about how the pieces connect in practice.

---

## Issues

### Issue 1: Step 5 Uses Simulated Scores Instead of Actual Batch Transform Output

- **File:** Python companion (`chapter07.02-python-example.md`)
- **Location:** `run_propensity_pipeline`, Step 5 block
- **Severity:** WARNING (misleading)
- **Description:** After running batch transform in Step 4 (which writes real predictions to S3), Step 5 ignores those predictions entirely and generates random scores with `np.random.beta(2, 2, size=len(df))`. The comment says "Simulate raw predictions (in production, load from batch transform output)" but a reader following along would expect the pipeline to actually use the output from the previous step. This breaks the pedagogical flow: the reader just learned how batch transform works, then the pipeline throws away its output. It makes the calibration step appear disconnected from the scoring step.
- **Suggested fix:** Add a helper function that loads the batch transform output from S3 (even if it's just reading the CSV back), or add a more prominent comment explaining why the demo shortcuts this:
  ```python
  # In a real pipeline, you'd load predictions from the batch transform output:
  #   raw_scores = load_predictions_from_s3(predictions_uri)
  # Here we simulate because parsing batch transform output requires knowing
  # the exact output format, which depends on your SageMaker container version.
  raw_scores = np.random.beta(2, 2, size=len(df))
  ```

---

### Issue 2: `prepare_scoring_input` Returns a File URI, Not a Directory URI

- **File:** Python companion (`chapter07.02-python-example.md`)
- **Location:** `prepare_scoring_input` and `run_batch_scoring`
- **Severity:** WARNING (code may not work as expected)
- **Description:** `prepare_scoring_input` returns `f"s3://{ML_BUCKET}/{scoring_key}"` which points to a specific file (e.g., `s3://bucket/features/open-balances/scoring-input.csv`). This is then passed to `transformer.transform(data=scoring_input_uri, ...)`. SageMaker Batch Transform's `data` parameter accepts either a file URI or a directory URI (prefix). While a single-file URI does work, the SageMaker documentation and most examples use a directory prefix. More importantly, if a reader later adds multiple scoring files to the prefix, the single-file URI pattern won't pick them up. This is a minor point but could confuse readers who compare against AWS documentation examples.
- **Suggested fix:** Either change to use the directory prefix pattern (upload to a specific subdirectory and pass the prefix), or add a comment noting that a single-file URI is valid:
  ```python
  # Batch Transform accepts either a single file URI or a directory prefix.
  # For simplicity, we point directly to the file. In production with
  # multiple input files, use the directory prefix instead.
  ```

---

### Issue 3: Calibration Model Fitted on Random Data, Not Actual Model Output

- **File:** Python companion (`chapter07.02-python-example.md`)
- **Location:** `run_propensity_pipeline`, Step 5
- **Severity:** WARNING (misleading pattern)
- **Description:** The calibration model is fitted using `raw_scores = np.random.beta(2, 2, ...)` against `val_labels = df["paid_within_90_days"].values`. This means the calibrator is learning a mapping from random numbers to actual labels, which produces a calibration function that has no relationship to the actual model's output distribution. A reader who understands calibration will find this confusing: the calibrator should be fitted on the actual model's predictions on a held-out set, not on random noise. The teaching value of the calibration step is undermined because the calibrator isn't doing what calibration actually does.
- **Suggested fix:** This is related to Issue 1. If you can't load actual batch transform output, at least generate synthetic scores that correlate with the labels (simulating what a trained model would produce):
  ```python
  # Simulate model outputs that correlate with true labels (as a trained
  # model would). Random scores would make calibration meaningless.
  noise = rng.normal(0, 0.15, size=len(df))
  raw_scores = np.clip(df["paid_within_90_days"].values * 0.6 + 0.2 + noise, 0.01, 0.99)
  ```

---

### Issue 4: Missing `import datetime` Usage Inconsistency

- **File:** Python companion (`chapter07.02-python-example.md`)
- **Location:** Config section and `run_batch_scoring`
- **Severity:** NOTE (minor clarity issue)
- **Description:** The imports include `import datetime` and `from datetime import timezone`, but `timezone` is never used anywhere in the code. Meanwhile, `run_batch_scoring` uses `datetime.date.today().isoformat()` which works correctly with the `import datetime` statement. The unused `timezone` import is harmless but may confuse a reader who wonders where it's supposed to be used (perhaps for timezone-aware score timestamps in DynamoDB).
- **Suggested fix:** Either remove `from datetime import timezone` or add a comment noting it would be used in production for timezone-aware timestamps:
  ```python
  from datetime import timezone  # used in production for UTC-aware score_date
  ```

---

### Issue 5: Pseudocode Includes `top_features` (SHAP Values) Not in Python

- **File:** Python companion (`chapter07.02-python-example.md`)
- **Location:** `store_predictions_in_dynamodb`, Step 5
- **Severity:** NOTE (minor inconsistency with pseudocode)
- **Description:** The main recipe's pseudocode Step 3 (`score_open_balances`) writes `top_features = prediction.feature_contributions` to DynamoDB, and the Expected Results section shows a `top_features` array with SHAP-like values. The Python companion omits this field entirely from the DynamoDB item. The "Gap to Production" section doesn't specifically mention this omission either.
- **Suggested fix:** Add a comment in `store_predictions_in_dynamodb`:
  ```python
  # The main recipe also stores top contributing features (SHAP values)
  # for explainability in the collection staff UI. Computing per-prediction
  # SHAP values requires the shap library and adds significant complexity.
  # See SageMaker Clarify for production feature attribution.
  ```

---

### Issue 6: `sklearn` Dependency Not Listed in Setup

- **File:** Python companion (`chapter07.02-python-example.md`)
- **Location:** Setup section (pip install line)
- **Severity:** NOTE (would fail on import)
- **Description:** The Setup section lists `pip install boto3 pandas numpy sagemaker` but Step 5 imports `from sklearn.isotonic import IsotonicRegression`. A reader following the setup instructions exactly would get an `ImportError` when reaching the calibration step. While `scikit-learn` is commonly installed in data science environments, the explicit setup section should be complete.
- **Suggested fix:** Update the pip install line:
  ```bash
  pip install boto3 pandas numpy sagemaker scikit-learn
  ```

---

## Pseudocode vs. Python Consistency

The Python implementation follows the main recipe's pipeline structure:

| Pseudocode Step | Python Function(s) | Match? |
|---|---|---|
| `compute_payment_features` | `generate_synthetic_balance_data` | ✓ (synthetic replacement, clearly explained) |
| `train_propensity_model` | `upload_training_data` + `train_propensity_model` | ✓ (split into data prep and training, logical) |
| `score_open_balances` | `prepare_scoring_input` + `run_batch_scoring` | ✓ (split into prep and execution) |
| Calibration (in pseudocode Step 2-3) | `fit_calibration_model` + `store_predictions_in_dynamodb` | Partial (calibration fitted on simulated data, see Issue 1/3) |
| `apply_collection_strategy` | `apply_collection_strategy` | ✓ (same thresholds, same routing logic) |

**Feature schema match:** The synthetic data generator produces exactly the same feature columns described in the pseudocode's `compute_payment_features`: `pay_rate_full`, `pay_rate_any`, `avg_days_to_first_payment`, `payment_plans_completed/defaulted`, `balance_amount`, `balance_amount_log`, `balance_age_days`, `service_type`, `insurance_adjudicated`, `statements_sent`, `insurance_type`, `has_other_open_balances`, `total_open_balance`, `days_since_portal_login`, `opened_last_statement`, `called_billing_recently`, `partial_payment_made`. All present and correctly typed.

**Strategy engine match:** The Python `apply_collection_strategy` uses the same thresholds (0.75, 0.40) and the same routing logic (including the $500 amount split for medium-propensity balances) as the pseudocode. Exact match.

---

## AWS SDK Accuracy

| API Call | Correct? | Notes |
|----------|----------|-------|
| `s3_client.put_object(Bucket, Key, Body)` | ✓ | Parameters correct, Body accepts encoded string |
| `sagemaker.image_uris.retrieve(framework, region, version)` | ✓ | Current SDK pattern |
| `Estimator(image_uri, role, instance_count, instance_type, output_path, ...)` | ✓ | All params valid |
| `estimator.set_hyperparameters(**dict)` | ✓ | Correct method, string values for built-in algo |
| `TrainingInput(s3_data, content_type)` | ✓ | Correct class and params |
| `estimator.fit(inputs={"train": ..., "validation": ...}, wait=True)` | ✓ | Both channels correct for XGBoost early stopping |
| `estimator.model_data` | ✓ | Returns S3 URI of model artifact |
| `sagemaker.model.Model(image_uri, model_data, role, sagemaker_session)` | ✓ | Correct constructor |
| `model.transformer(instance_count, instance_type, output_path, accept, strategy, max_payload)` | ✓ | All params valid |
| `transformer.transform(data, content_type, split_type, wait, logs)` | ✓ | Correct method and params |
| `dynamodb.Table(name).batch_writer()` | ✓ | Correct context manager, handles 25-item chunking |
| `batch.put_item(Item=dict)` | ✓ | Correct method within batch_writer context |

**XGBoost hyperparameters:** All hyperparameter names (`objective`, `eval_metric`, `num_round`, `max_depth`, `eta`, `subsample`, `colsample_bytree`, `scale_pos_weight`) are valid XGBoost parameters. Values passed as strings, which is correct for SageMaker's built-in algorithm.

---

## DynamoDB Data Types

The code correctly uses `Decimal` for all numeric values in DynamoDB:
- `Decimal(str(round(score, 4)))` for propensity_score
- `Decimal(str(round(float(balance_amounts[i]), 2)))` for balance_amount

The `str()` wrapping before `Decimal()` is correct practice to avoid floating-point representation artifacts. The code also includes an explicit comment explaining why: "DynamoDB does not accept Python floats. You must wrap numeric values in Decimal()..." This is excellent for a teaching example.

---

## S3 Paths

All S3 keys use relative paths without leading slashes:
- `features/open-balances/scoring-input.csv` ✓
- `features/training/train/train.csv` ✓
- `features/training/validation/validation.csv` ✓
- `models/propensity-to-pay/` ✓
- `predictions/propensity-to-pay/{date}/` ✓

No issues.

---

## Comment Quality

Comments are strong throughout, consistently explaining "why" rather than "what":
- The `scale_pos_weight` comment explains the formula with a concrete example
- The synthetic data generator comments explain which real-world correlations each feature encodes
- The DynamoDB `Decimal` comment explains the failure mode readers would hit
- The strategy engine comments explain the operational rationale for each tier
- The calibration section explains why calibration matters for threshold-based decisions

The "Gap to Production" section is comprehensive, covering error handling, calibration monitoring, fairness, feedback loops, VPC, encryption, and testing.

---

## Logical Flow

The code reads top-to-bottom in a pedagogically sound order:
1. Config and constants (establishes vocabulary and tunable parameters)
2. Synthetic data generation (gives the reader something to work with)
3. S3 upload (shows the data format SageMaker expects)
4. Model training (the core ML step)
5. Batch scoring (applying the model at scale)
6. Calibration and DynamoDB storage (bridging ML to operations)
7. Strategy engine (turning predictions into collection decisions)
8. Full pipeline (ties it all together)

Each function builds on the previous one, and the `run_propensity_pipeline` function provides an end-to-end demonstration.

---

## Verdict

**PASS**

No ERROR-level findings. Three WARNINGs (simulated scores in pipeline, file vs. directory URI, calibration on random data) and three NOTEs. The three WARNINGs are all related to the same underlying issue: the demo pipeline shortcuts the connection between batch transform output and calibration. While this is clearly labeled as a teaching example and the "Gap to Production" section is thorough, the disconnect between Steps 4 and 5 weakens the pedagogical flow. However, the individual functions are all correct and well-documented, and a reader who understands the stated limitation can still learn the full pattern.

**Recommended improvements (not blocking):**
1. Replace `np.random.beta(2, 2, ...)` with synthetic scores that correlate with labels, making the calibration step meaningful
2. Add a comment in `prepare_scoring_input` noting that single-file URIs are valid for Batch Transform
3. Add `scikit-learn` to the pip install line in Setup
4. Add a comment acknowledging the omitted `top_features` field
5. Remove unused `from datetime import timezone` import
