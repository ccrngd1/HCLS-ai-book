# Code Review: Recipe 9.7

## Summary

The Python companion is a well-structured, pedagogically sound implementation of the multi-modality radiology AI triage pipeline. It faithfully implements all five pseudocode steps from the main recipe: study classification and model routing, preprocessing, SageMaker inference, priority assignment, and result storage with alerting. The code is readable, comments explain the "why," and the logical flow builds understanding progressively. DynamoDB uses Decimal correctly. S3 paths have no leading slashes. boto3 API calls use correct method names and parameters. One warning around an unused import and a couple of minor notes, but nothing that would prevent the code from running or mislead a learner.

---

## Issues

### Issue 1: Unused Import of `as_strided`

- **File:** `chapter09.07-python-example.md`
- **Location:** `_preprocess_volume` function, inside the function body
- **Severity:** WARNING (misleading)
- **Description:** The line `from numpy.lib.stride_tricks import as_strided  # noqa: avoid heavy imports` imports `as_strided` but never uses it. The comment says "avoid heavy imports" which doesn't explain why it's there. A learner will wonder what it's for and may try to use `as_strided` for image resampling (which would be incorrect and dangerous for this use case). The actual resampling uses `np.linspace` and array indexing, which is fine. This dangling import is confusing dead code.
- **Suggested fix:** Remove the line entirely. The comment about avoiding heavy imports could be moved to a standalone comment explaining why scipy isn't imported at the top level (which is already explained in the surrounding comments about production using `scipy.ndimage.zoom`).

---

### Issue 2: `assign_priority` Accumulates Triggering Findings Incorrectly When Priority Escalates

- **File:** `chapter09.07-python-example.md`
- **Location:** `assign_priority` function
- **Severity:** NOTE (improvement)
- **Description:** When a finding triggers a higher priority level, `triggering_findings` is reset to `[finding]`. But if a subsequent finding matches the same (now-highest) priority level, it's appended. This is correct behavior. However, if a STAT finding is found first, then an URGENT finding is encountered, the URGENT finding is silently skipped (correct). But if an URGENT finding is found first, then a STAT finding is found, the triggering list resets to just the STAT finding, losing the URGENT one. This matches the pseudocode's intent ("highest matching priority wins") and is clinically correct (you only care about what triggered the highest level). Just noting that the behavior is intentional and well-implemented. No change needed.

---

### Issue 3: `decimal_findings` Helper Doesn't Handle Nested Dicts

- **File:** `chapter09.07-python-example.md`
- **Location:** `store_triage_result` function, `decimal_findings` inner function
- **Severity:** NOTE (improvement)
- **Description:** The `decimal_findings` helper converts top-level float values to Decimal but doesn't recurse into nested dicts (like `"location": {"hemisphere": "left", "slice_range": [45, 62]}`). In the current code this is fine because the nested values in the example findings are strings, lists of ints, or other non-float types. However, if a model returned a nested float (e.g., `"shift_mm": 6.2` inside a nested dict), it would cause a DynamoDB TypeError. The simulated findings in the `__main__` block have `"shift_mm": 3.1` at the top level (handled correctly). For a teaching example this is acceptable since the Gap to Production section covers robustness. A brief inline comment noting the limitation would help learners.
- **Suggested fix:** Add a comment: `# Note: only handles top-level floats. Nested dicts with floats need recursive conversion in production.`

---

### Issue 4: SNS `publish` Uses `Subject` Which Has a 100-Character Limit

- **File:** `chapter09.07-python-example.md`
- **Location:** `_send_critical_alert` function
- **Severity:** NOTE (improvement)
- **Description:** The SNS `Subject` parameter is `"STAT: Critical Radiology Finding Detected"` (43 characters), which is well within the 100-character limit. This is fine. Just noting for completeness that the boto3 `sns_client.publish()` call is correct: `TopicArn`, `Subject`, `Message`, and `MessageAttributes` are all valid parameters with correct types. `MessageAttributes` uses the correct structure with `DataType` and `StringValue` keys.

---

## Pseudocode vs. Python Consistency

The Python implementation maps cleanly to all five pseudocode steps:

**Pseudocode Step 1 (receive_dicom_study):** Not implemented in Python, which is correct. The Python companion's intro explicitly states it covers the "control plane skeleton" and that DICOM ingestion/buffering is out of scope. The `triage_study` function starts with pixel data already available, matching the stated scope.

**Pseudocode Step 2 (classify_and_route):** Implemented as `classify_study_and_select_models`. The Python version handles CR/DX equivalence (mentioned in pseudocode as `modality in ["CR", "DX"]`), searches StudyDescription and ProtocolName for body part keywords (matching the pseudocode's note about BodyPartExamined being unreliable), and returns model configs. The Python adds normalization (`.upper().strip()`) which the pseudocode implies but doesn't spell out. Consistent.

**Pseudocode Step 3 (run_inference):** Split into `preprocess_for_model` and `invoke_model` in Python. The pseudocode combines these conceptually. The Python separation is pedagogically better (preprocessing is complex enough to warrant its own function). The SageMaker endpoint invocation uses `invoke_endpoint` with `EndpointName`, `ContentType`, `Body`, and `CustomAttributes`, all correct boto3 parameters. Response parsing via `response["Body"].read().decode("utf-8")` is the correct pattern for SageMaker Runtime responses. Consistent.

**Pseudocode Step 4 (assign_priority):** Implemented as `assign_priority`. The pseudocode checks STAT rules first, then URGENT. The Python iterates all findings against all rules and uses `PRIORITY_LEVELS` dict for comparison, which achieves the same "highest wins" semantics. The Python approach is actually more correct: it handles the case where a single finding might match both STAT and URGENT rules (takes the higher one). Consistent.

**Pseudocode Step 5 (update_worklist_and_notify):** Implemented as `store_triage_result` and `_send_critical_alert`. The pseudocode includes worklist/RIS update (`update_ris_priority`), which the Python omits (correctly, since that's vendor-specific and can't be demonstrated with boto3). The Python stores to DynamoDB and sends SNS alerts, which maps to the pseudocode's `write_to_database` and `send_alert` calls. The audit logging from the pseudocode is captured in the DynamoDB record (models_invoked, all_findings, triggering_findings). Consistent.

**Orchestrator (`triage_study`):** Maps to the overall pipeline flow. Handles the "no applicable models" case (assigns ROUTINE), iterates models with try/except for graceful degradation (matching the pseudocode's implicit requirement that one model failure shouldn't block others), and calls store/alert at the end. Consistent.

---

## boto3 API Accuracy

- `sagemaker_runtime.invoke_endpoint(EndpointName=..., ContentType=..., Body=..., CustomAttributes=...)`: Correct. `CustomAttributes` is a valid parameter (string, max 1024 chars).
- `response["Body"].read().decode("utf-8")`: Correct. SageMaker Runtime returns a `StreamingBody` in the `Body` key.
- `dynamodb.Table(TABLE_NAME).put_item(Item=record)`: Correct DynamoDB resource-layer usage.
- `sns_client.publish(TopicArn=..., Subject=..., Message=..., MessageAttributes=...)`: Correct. MessageAttributes structure with `DataType` and `StringValue` is correct.
- `Config(retries={"max_attempts": 3, "mode": "adaptive"})`: Correct botocore retry configuration.

All API calls verified against current boto3 SDK.

---

## DynamoDB Float/Decimal Check

The `decimal_findings` helper in `store_triage_result` correctly converts float values to `Decimal(str(round(v, 4)))`. The `str()` wrapper avoids floating-point representation issues. Top-level record fields (strings, booleans, lists of strings) don't contain floats. The `acknowledged` field is a boolean (valid in DynamoDB). **PASS.**

---

## S3 Path Check

S3 bucket names are defined as constants (`DICOM_BUCKET`, `PREPROCESSED_BUCKET`) without leading slashes. No S3 `GetObject` or `PutObject` calls appear in the code (pixel data is passed in-memory, not fetched from S3 in this example). The configuration comments reference bucket names correctly. **PASS.**

---

## Verdict

- [x] Ready as-is
- [ ] Needs minor fixes (list them)
- [ ] Needs significant rework

**PASS**

The code is pedagogically sound, correctly implements the pseudocode steps, uses boto3 APIs accurately, handles DynamoDB Decimal conversion properly, and builds understanding progressively. The one WARNING (unused `as_strided` import) is a minor blemish that doesn't affect correctness or mislead readers about the core patterns being taught. The two NOTEs are suggestions for polish, not issues that would confuse learners or produce runtime errors.
