# Code Review: Recipe 7.6 - Rising Risk Identification

**Reviewed:** `chapter07.06-python-example.md`
**Against:** `chapter07.06-rising-risk-identification.md`
**Severity levels:** ERROR (code won't work), WARNING (misleading), NOTE (improvement)

---

## Verdict: FAIL

The Python companion file `chapter07.06-python-example.md` does not exist. There is no code to review.

The main recipe (`chapter07.06-rising-risk-identification.md`) contains well-structured pseudocode across 5 steps (feature assembly, batch scoring, trajectory computation, rising risk detection, store and route). The pseudocode is pedagogically sound and internally consistent. However, the recipe references a Python companion at the bottom ("check out the [Python Example](chapter07.06-python-example)") that has not been written.

---

## Findings

### ERROR 1: Python companion file missing entirely

**Location:** Expected at `chapter07.06-python-example.md`

The file does not exist in the repository. The main recipe explicitly references it in the "Code" section with a link to `chapter07.06-python-example`. Readers following the recipe will hit a dead link.

**Fix:** Write the Python companion implementing the 5 pseudocode steps with boto3 calls for SageMaker batch transform, S3 score history storage, Glue-style trajectory computation (can be demonstrated with pandas at teaching scale), DynamoDB risk state writes, and EventBridge event emission.

---

## Pseudocode Quality Assessment (for when the Python companion is written)

The main recipe's pseudocode is well-structured and provides a solid blueprint. Key points the Python companion should address:

1. **Step 2 (batch scoring):** SageMaker `create_transform_job` API (not `invoke_endpoint`, since this is batch). Verify the Python uses the correct batch transform API, not real-time inference.

2. **Step 3 (trajectory computation):** Linear regression slope calculation over irregular time intervals. The pseudocode calls `linear_regression_slope(history, window)` which needs to handle variable spacing between scoring cycles.

3. **Step 4 (detection):** The threshold constants and multi-signal convergence logic. DynamoDB writes must use `Decimal` for all numeric fields (`current_score`, `trajectory_slope`, etc.).

4. **Step 5 (store and route):** EventBridge `put_events` API call. Verify the `Entries` parameter structure is correct (Source, DetailType, Detail as JSON string).

5. **S3 paths:** Score history paths like `s3://score-history/date={scoring_date}/` should not have leading slashes in the key portion.

---

## No Further Findings

Cannot assess boto3 accuracy, comment quality, logical flow, or pseudocode-to-Python consistency without the Python companion file.

---

*Review blocked. Python companion must be written before code review can proceed.*
