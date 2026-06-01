# Code Review: Recipe 9.6 (Diabetic Retinopathy Screening)

## Summary

The Python companion is well-structured and faithfully implements all four pseudocode steps. It uses correct boto3 API calls, handles DynamoDB Decimal conversion properly, avoids leading slashes in S3 paths, and builds understanding progressively from quality assessment through clinical decision logic. The comments are excellent for a teaching context, explaining clinical rationale (ICDR severity scale, sensitivity/specificity tradeoffs) alongside technical decisions. The synthetic test batch is a strong pedagogical addition that lets readers verify the decision logic without AWS infrastructure. One WARNING for an undeclared dependency (scipy) that would cause a runtime error.

---

## Verdict: **PASS**

---

## Findings

### Finding 1: `calculate_sharpness` imports `scipy.signal.convolve2d` but scipy is not in the prerequisites

- **Severity:** WARNING
- **Location:** Step 1, `calculate_sharpness` function, line `from scipy.signal import convolve2d`
- **What's wrong:** The Setup section lists `pip install boto3 numpy Pillow` as the required dependencies. However, `calculate_sharpness` uses `from scipy.signal import convolve2d` which requires scipy. A reader following the setup instructions would get `ModuleNotFoundError: No module named 'scipy'` when running the quality assessment step. This is the only function that uses scipy; the rest of the quality checks use only numpy and Pillow.
- **Fix:** Either add `scipy` to the pip install line in the Setup section, or replace the scipy convolution with a pure numpy implementation (e.g., `np.convolve` applied row/column-wise, or manual sliding window). Adding scipy to prerequisites is the simpler fix.

---

### Finding 2: `trigger_downstream_action` writes `image_key` from `message_base` but it's never populated

- **Severity:** WARNING
- **Location:** Step 4, `trigger_downstream_action` function, HUMAN_REVIEW_REQUIRED branch
- **What's wrong:** The `message_base` dict is constructed from `patient_id`, `screening_id`, `severity_grade`, `decision`, and `timestamp`. It does not include `image_key`. However, the HUMAN_REVIEW_REQUIRED branch writes `"image_key": message_base.get("image_key", "")` to the reading queue table. This will always store an empty string for `image_key`, which means a human grader looking at the reading queue won't know which image to review. The function signature accepts `patient_id`, `screening_id`, and `decision` but not `image_key`.
- **Fix:** Add `image_key` as a parameter to `trigger_downstream_action` and include it in `message_base`, or pass it directly in the reading queue item. The caller (`run_screening_pipeline`) has access to `image_key`.

---

### Finding 3: `store_screening_result` screening_id format uses `%m%d` without separator

- **Severity:** NOTE
- **Location:** Step 4, `store_screening_result` function, screening_id generation
- **What's wrong:** The screening_id is generated as `f"scr-{datetime.now(timezone.utc).strftime('%Y-%m%d')}-{uuid.uuid4().hex[:5]}"`. The format string `'%Y-%m%d'` produces something like `2026-0531` (missing the second hyphen between month and day). This is likely a typo; the intended format is probably `'%Y%m%d'` (no hyphens, like `20260531`) or `'%Y-%m-%d'` (ISO date, like `2026-05-31`). The current format works but produces an inconsistent date representation that could confuse readers.
- **Fix:** Change to either `'%Y%m%d'` for compact format or `'%Y-%m-%d'` for ISO format.

---

### Finding 4: DynamoDB table has no explicit partition/sort key in `store_screening_result`

- **Severity:** NOTE
- **Location:** Step 4, `store_screening_result` function
- **What's wrong:** The pseudocode specifies `partition key = patient_id` and `sort key = screening_date`. The Python code uses `results_table.put_item(Item=record)` which includes both `patient_id` and `screening_date` as fields in the record, so DynamoDB will use them correctly if the table is configured as described. However, the code doesn't make it explicit which fields serve as keys. A brief comment noting "patient_id is the partition key, screening_date is the sort key" would help readers understand the DynamoDB data model. This is purely pedagogical.
- **Fix:** Add a comment above `put_item` noting the key schema, e.g., `# DynamoDB key: patient_id (partition) + screening_date (sort)`.

---

### Finding 5: Synthetic test scenario pat-002 (Mild NPDR) expected decision may confuse readers

- **Severity:** NOTE
- **Location:** Synthetic Test Data section, pat-002 scenario
- **What's wrong:** Patient pat-002 has `mild_npdr_probability: 0.72` as the highest probability, which exceeds `CONFIDENCE_THRESHOLD` (0.60). The referable probability is 0.08 + 0.03 + 0.02 = 0.13, well below `REFERABLE_THRESHOLD` (0.80). DME is 0.05, below `DME_THRESHOLD` (0.70). So the expected decision of "NO_REFERRAL" is correct. However, a reader might initially think "mild NPDR detected" should trigger some action. The scenario description says "below referral threshold" which is accurate, but a brief inline comment explaining that mild NPDR alone doesn't trigger referral (only moderate+ does) would reinforce the clinical logic for non-ophthalmologist readers.
- **Fix:** Optional. Add a comment like `# Mild NPDR alone does not trigger referral per ICDR guidelines; only moderate+ is referable`.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Implementation | Match? |
|---|---|---|
| Step 1: `assess_image_quality(bucket, image_key)` | `assess_image_quality(bucket, image_key)` | ✓ Exact match, same logic and return structure |
| Step 2: `classify_retinal_image(bucket, image_key)` | `classify_retinal_image(bucket, image_key)` | ✓ Exact match |
| Step 3: `apply_clinical_decision(predictions)` | `apply_clinical_decision(predictions)` | ✓ Exact match, same threshold logic and branching |
| Step 4: `store_and_act(patient_id, image_key, quality_result, predictions, decision)` | `store_screening_result(...)` + `trigger_downstream_action(...)` | ✓ Split into two functions but same intent and coverage |

The full pipeline function (`run_screening_pipeline`) correctly orchestrates all steps in the same order as the pseudocode narrative. The quality gate short-circuit (return early if image is ungradable) matches the pseudocode flow. The decision logic branching order (confidence check, urgent, referable, DME, no referral) is identical between pseudocode and Python.

---

## AWS SDK Accuracy

- **`s3_client.get_object(Bucket=bucket, Key=key)`**: Correct method name and parameters. Response parsed via `response["Body"].read()`. ✓
- **`sagemaker_runtime.invoke_endpoint(EndpointName=..., ContentType=..., Body=...)`**: Correct method name (`invoke_endpoint`), correct parameter names. Response body read via `response["Body"].read().decode("utf-8")`. ✓
- **`dynamodb.Table(TABLE_NAME).put_item(Item=record)`**: Correct resource-layer usage for both tables. ✓
- **`sns_client.publish(TopicArn=..., Subject=..., Message=...)`**: Correct method name and parameters. ✓
- **`Config(retries={"max_attempts": 3, "mode": "adaptive"})`**: Valid botocore retry configuration. ✓
- **`boto3.client("sagemaker-runtime", ...)`**: Correct service name for SageMaker Runtime (inference). ✓

---

## DynamoDB Decimal Check

The `store_screening_result` function correctly handles Decimal conversion:
- `quality_score`: `Decimal(str(round(quality_result["quality_score"], 3)))` ✓
- `referable_probability`: `Decimal(str(decision["referable_probability"]))` ✓
- `dme_probability`: `Decimal(str(decision["dme_probability"]))` ✓
- `raw_predictions`: `json.loads(json.dumps(predictions), parse_float=Decimal)` ✓ (handles nested floats cleanly)

The `trigger_downstream_action` HUMAN_REVIEW_REQUIRED branch also uses `json.loads(json.dumps(decision), parse_float=Decimal)` for the reading queue write. ✓

No raw floats passed to `put_item`. ✓

---

## S3 Path Check

- S3 key referenced in pipeline: `image_key` parameter passed by caller. No hardcoded paths with leading slashes. ✓
- S3 bucket name: `"retinal-screening-images"` in constants. No leading slash. ✓
- Example usage in pipeline prints: `f"s3://{bucket}/{image_key}"` - correct URI format. ✓

---

## Comment Quality

Comments are excellent for a teaching context. Highlights:

- Clinical context explained inline: "In a screening program, you generally want HIGH sensitivity (catch more disease) even at the cost of some specificity (extra referrals that turn out normal)"
- Threshold rationale: "Lower REFERABLE_THRESHOLD = more sensitive... Higher REFERABLE_THRESHOLD = more specific"
- Quality gate reasoning: "One bad dimension makes the whole image ungradable"
- Safety design: "This is a SAFETY feature, not a failure mode" (for HUMAN_REVIEW_REQUIRED)
- DynamoDB gotcha called out: "DynamoDB requires Decimal for numeric values, not float"
- PHI awareness: "Never log PHI field values" in logging configuration comment
- Operator-friendly: Quality failure returns specific recommendations ("Refocus the camera. Ask patient to fixate on the target.")

The comments consistently explain "why" and are accessible to someone learning both Python and retinal screening concepts.

---

## Final Assessment

No ERRORs. Two WARNINGs (missing scipy dependency that would cause runtime failure; image_key not passed to reading queue). Three NOTEs (all minor pedagogical improvements). The code is correct in its clinical logic, well-commented, builds understanding progressively, and would run successfully given the stated prerequisites plus scipy. The DynamoDB Decimal handling is thorough. The synthetic test batch is a strong addition that validates the decision logic without requiring AWS infrastructure. The Gap to Production section is comprehensive. Verdict: **PASS**.
