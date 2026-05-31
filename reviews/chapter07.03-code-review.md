# Code Review: Recipe 7.3

## Summary

The Python companion for Patient Churn / Disenrollment Prediction is well-structured, pedagogically sound, and faithfully implements the pseudocode from the main recipe. The code builds understanding progressively from synthetic data generation through model training, batch scoring, risk stratification, DynamoDB storage, and EventBridge publishing. Comments are generous and explain "why" not just "what." DynamoDB numeric values are properly wrapped in `Decimal`. S3 keys have no leading slashes. boto3 and SageMaker API calls use correct method names and parameters. The main concern is that the `put_events` call doesn't check for `FailedEntryCount` in the response, which could silently lose events in a teaching context where a reader might not realize failures are possible.

---

## Issues

### Issue 1: EventBridge `put_events` Does Not Check `FailedEntryCount`

- **File:** Python companion (`chapter07.03-python-example.md`)
- **Location:** Step 7, `publish_high_risk_events` function
- **Severity:** WARNING
- **Description:** The `put_events` API can partially succeed: some entries in a batch may fail while others succeed. The response includes a `FailedEntryCount` field. The code increments `published += len(entries)` unconditionally without checking whether any entries actually failed. A reader might carry this pattern into production and silently lose intervention triggers for high-risk members. For a teaching example, at minimum a log warning when `FailedEntryCount > 0` would demonstrate awareness of partial failures.
- **Suggested fix:** After each `put_events` call, add:
  ```python
  response = events_client.put_events(Entries=entries)
  failed = response.get("FailedEntryCount", 0)
  if failed:
      logger.warning("%d events failed to publish", failed)
  published += len(entries) - failed
  ```

---

### Issue 2: Pseudocode Includes Calibration Step; Python Skips It Entirely

- **File:** Python companion (`chapter07.03-python-example.md`)
- **Location:** Step 3 (training) and Step 4 (scoring)
- **Severity:** WARNING
- **Description:** The main recipe's pseudocode explicitly includes a calibration step in `train_churn_model`: "Calibrate probabilities using isotonic regression on the validation set" and then applies `calibrator.transform(raw_probability)` during scoring. The Python companion omits calibration entirely. The "Gap to Production" section mentions calibration as something missing, but the pseudocode presents it as part of the core pipeline, not a production enhancement. A reader comparing the two files will notice this discrepancy. The main recipe also emphasizes that "calibration is non-negotiable but often skipped" in the Honest Take section, making the omission more conspicuous.
- **Suggested fix:** Either add a simple calibration step after the local model training in the "Putting It All Together" section (even a comment-only placeholder showing where it would go), or add an explicit inline comment in Step 3 noting: "The pseudocode includes a calibration step here. We omit it in this demo because the local GradientBoostingClassifier's predict_proba is already reasonably calibrated for synthetic data. In production with XGBoost, calibration is essential."

---

### Issue 3: `top_risk_factors` Stored as JSON String in DynamoDB but as List in EventBridge

- **File:** Python companion (`chapter07.03-python-example.md`)
- **Location:** Step 6 (`store_results_dynamodb`) vs Step 7 (`publish_high_risk_events`)
- **Severity:** NOTE
- **Description:** In Step 6, `top_risk_factors` is serialized with `json.dumps(row["top_risk_factors"])` before storing in DynamoDB (stored as a string attribute). In Step 7, the same field is passed directly as `row["top_risk_factors"]` inside a `json.dumps` call for the EventBridge Detail. This works correctly in both cases (DynamoDB gets a string, EventBridge gets the list serialized as part of the Detail JSON). However, a reader might wonder why the DynamoDB version needs explicit serialization while EventBridge doesn't. A brief comment explaining that DynamoDB doesn't natively support nested lists of dicts as a single attribute (without using a Map type) would help.
- **Suggested fix:** Add a comment above the `json.dumps` in Step 6:
  ```python
  # Serialize as JSON string because DynamoDB doesn't natively support
  # lists of maps as a single attribute without complex type definitions.
  "top_risk_factors": json.dumps(row["top_risk_factors"]),
  ```

---

### Issue 4: Local Model in "Putting It All Together" Uses Different Algorithm Than SageMaker Steps

- **File:** Python companion (`chapter07.03-python-example.md`)
- **Location:** `run_churn_prediction_pipeline`, after Step 4
- **Severity:** NOTE
- **Description:** The pipeline function trains an XGBoost model on SageMaker (Step 3) and runs batch transform (Step 4), but then simulates predictions locally using `sklearn.GradientBoostingClassifier` instead of XGBoost. The code includes a comment explaining this is for demonstration, which is fine. However, the local model uses `n_estimators=200, max_depth=6` while the SageMaker config uses `num_round=500, max_depth=6, eta=0.05`. The different algorithm and hyperparameters mean the local predictions won't match what SageMaker would produce. This is acknowledged but could confuse a reader who expects the downstream steps (risk tiers, DynamoDB writes) to reflect the actual trained model's behavior.
- **Suggested fix:** No code change needed. The existing comment is adequate. Optionally, add a note: "Predictions from this local model will differ from the SageMaker XGBoost model. The downstream steps demonstrate the pipeline mechanics, not the model's actual performance."

---

### Issue 5: `scoring_dt` Timezone Handling in TTL Calculation

- **File:** Python companion (`chapter07.03-python-example.md`)
- **Location:** Step 6, `store_results_dynamodb` function
- **Severity:** NOTE
- **Description:** The `scoring_date` parameter is a plain date string (e.g., "2026-05-31") created with `.strftime("%Y-%m-%d")`. The function parses it with `datetime.datetime.fromisoformat(scoring_date)`, which produces a naive datetime (midnight, no timezone). The `.timestamp()` call on a naive datetime uses the local system timezone, which could produce different TTL values depending on where the code runs. This is fine for a teaching example but worth noting. The `scoring_date` in the pipeline is generated from `datetime.datetime.now(timezone.utc)`, so the date itself is UTC-based, but the TTL calculation doesn't preserve that.
- **Suggested fix:** No change required for a teaching example. If desired, make the TTL calculation timezone-explicit:
  ```python
  scoring_dt = datetime.datetime.fromisoformat(scoring_date).replace(tzinfo=timezone.utc)
  ```

---

## Pseudocode vs. Python Consistency

The Python implementation follows the pseudocode's logical flow faithfully with one notable omission:

**Step 1 (Feature Assembly):** The pseudocode's `assemble_member_features` defines 21 features across engagement, satisfaction, network, financial, demographic, and digital categories. The Python's `generate_synthetic_members` produces all 21 features with the same names. The synthetic distributions are reasonable (churned members show worse values). Consistent.

**Step 2 (Training Data Preparation):** The pseudocode's `create_training_dataset` describes time-based splitting. The Python uses stratified random split with an inline comment explaining why (synthetic data has no temporal dimension). The deviation is explained. Consistent.

**Step 3 (Model Training):** The pseudocode's `train_churn_model` includes XGBoost configuration and a calibration step. The Python implements the XGBoost training via SageMaker with matching hyperparameters (objective, eval_metric, max_depth, learning_rate/eta, scale_pos_weight). **Calibration is omitted** (see Issue 2). Partially consistent.

**Step 4 (Scoring):** The pseudocode's `score_membership` uses batch transform and applies calibration. The Python implements batch transform correctly but skips calibration. The local simulation fallback is clearly marked. Partially consistent (calibration gap).

**Step 5 (Risk Stratification):** The pseudocode's `assign_tier` uses thresholds 0.60/0.35. The Python uses identical thresholds. The pseudocode uses SHAP values; the Python uses heuristic-based risk factors with a clear comment explaining the simplification. The intervention routing logic matches the pseudocode's concept. Consistent.

**Step 6 (Storage):** The pseudocode's `store_and_serve` writes to DynamoDB with TTL. The Python implements this with `batch_writer`, proper `Decimal` wrapping, and TTL. The S3 Parquet write from the pseudocode is omitted (the Python only writes to DynamoDB), but this is a reasonable simplification for the demo. Consistent.

**Step 7 (EventBridge):** The pseudocode publishes high-risk members to EventBridge with `detail_type = "MemberChurnRiskHigh"`. The Python implements this with correct batching (10 entries per call) and matching detail type. Consistent.

---

## Verdict

**PASS**

- 0 ERROR findings
- 2 WARNING findings (below the 3-WARNING threshold for FAIL)
- 3 NOTE findings

The code is correct, would run without errors given AWS credentials and infrastructure, teaches the right patterns, and faithfully implements the main recipe's architecture. The two warnings are about silent event publishing failures (a misleading pattern a reader might carry forward) and the omission of the calibration step that the pseudocode explicitly includes. Neither would cause runtime failures. DynamoDB Decimal handling is correct throughout. S3 keys are clean (no leading slashes). boto3 API calls use correct method names, parameters, and response parsing. The SageMaker SDK usage (Estimator, TrainingInput, Model, Transformer) follows current patterns. The pedagogical flow builds understanding progressively and comments are genuinely helpful for learners.
