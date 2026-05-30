# Code Review: Recipe 12.10 - Physiological Waveform Analysis

**Reviewer:** Tech Code Reviewer
**Files reviewed:**
- `chapter12.10-physiological-waveform-analysis.md` (main recipe with five-step pseudocode)
- `chapter12.10-python-example.md` (Python implementation)

---

## Verdict: PASS

No ERROR-level findings. Two WARNING-level findings (under the FAIL threshold of >3). Several NOTE-level improvements. The five pseudocode steps map cleanly to the Python functions, S3 keys are constructed without leading slashes, the demo runs end-to-end against in-memory mocks, and the boto3 API calls use correct method names and parameter structures. The signal processing logic (bandpass filtering, notch filtering, SQI computation, windowed classification, persistence-based alerting with cooldown suppression) is pedagogically sound and correctly simplified for teaching purposes. No DynamoDB usage in this recipe (Timestream is the primary store), so the Decimal check is not applicable to the main data path.

---

## Pseudocode-to-Python Mapping

| Step | Recipe Pseudocode | Python Function | Status |
|------|-------------------|-----------------|--------|
| 1 | `ingest_waveform_sample` (Kinesis put_record with partition key, S3 archive with time-partitioned key) | `ingest_waveform_batch` | ✓ |
| 2 | `preprocess_waveform` (bandpass filter, notch filter, SQI computation, quality gate, windowing) | `preprocess_waveform` + `apply_bandpass_filter` + `apply_notch_filter` + `compute_signal_quality_index` + `segment_into_windows` | ✓ |
| 3 | `classify_waveform` (invoke SageMaker endpoint per window, return classification + confidence) | `classify_waveform_windows` | ✓ |
| 4 | `apply_alert_logic` (persistence counting, known-condition suppression, cooldown enforcement, SNS publish) | `apply_alert_logic` + `count_consecutive` + `is_in_cooldown` + `set_cooldown` + `load_patient_context` | ✓ |
| 5 | `store_and_expose` (write all classifications to Timestream, write system metrics) | `store_classifications` | ✓ |

The pseudocode's partition key strategy (patient_id + waveform_type) is faithfully implemented. The preprocessing sub-steps (2a-2e) map one-to-one to the Python implementation. The classification step correctly shows the SageMaker `invoke_endpoint` call in a comment with proper parameter names (`EndpointName`, `ContentType`, `Body`) and response parsing (`response["Body"].read()`). The alert logic implements all three suppression mechanisms from the pseudocode: persistence thresholds, known-condition suppression, and cooldown enforcement. The storage step batches Timestream writes at 100 records per call, matching the Timestream API limit.

---

## Findings

### Issue 1 - WARNING: Timestream `Time` field uses ISO 8601 string but `TimeUnit` is set to `MILLISECONDS`

**Severity:** WARNING (misleading)
**File:** `chapter12.10-python-example.md`, `store_classifications` function

```python
"Time": result["window_timestamp"],
"TimeUnit": "MILLISECONDS",
```

The `window_timestamp` value is an ISO 8601 string (e.g., `"2026-03-01T14:22:00+00:00"`). However, when `TimeUnit` is `MILLISECONDS`, Timestream expects the `Time` field to be a string representation of epoch milliseconds (e.g., `"1709302920000"`), not an ISO 8601 timestamp.

This code would fail with a `ValidationException` from the Timestream API in production. For a teaching example, this is misleading because a reader copying this pattern would hit a runtime error.

**Fix:** Convert the ISO timestamp to epoch milliseconds:

```python
from datetime import datetime, timezone

ts_dt = datetime.fromisoformat(result["window_timestamp"].replace("Z", "+00:00"))
epoch_ms = str(int(ts_dt.timestamp() * 1000))

# Then in the record:
"Time": epoch_ms,
"TimeUnit": "MILLISECONDS",
```

Or use `TimeUnit: "SECONDS"` with epoch seconds, which is also valid.

---

### Issue 2 - WARNING: `count_consecutive` returns the longest run anywhere in the batch, not the trailing run

**Severity:** WARNING (misleading)
**File:** `chapter12.10-python-example.md`, `count_consecutive` function and `apply_alert_logic`

The pseudocode says: "Count consecutive windows with the same high-confidence classification." The intent (and the clinical logic) is that the most recent N consecutive windows must agree for an alert to fire. The implementation finds the *longest* run anywhere in the batch:

```python
def count_consecutive(results, classification, min_confidence):
    max_run = 0
    current_run = 0
    for r in results:
        if (r["classification"] == classification
                and r["confidence"] >= min_confidence):
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0
    return max_run
```

If a batch has windows `[AFib, AFib, AFib, Normal, Normal, AFib, AFib]`, this returns 3 (the early run), even though the current state is only 2 consecutive AFib windows. In a real-time streaming system, you want the trailing run (the most recent consecutive detections) because that represents the current patient state.

For a teaching example this is not catastrophically wrong (it's conservative in that it might alert slightly earlier than intended), but it teaches a pattern that could produce stale alerts based on historical runs that have already resolved.

**Fix:** Count from the end of the results list backward, or track only the trailing run:

```python
def count_trailing_consecutive(results, classification, min_confidence):
    count = 0
    for r in reversed(results):
        if (r["classification"] == classification
                and r["confidence"] >= min_confidence):
            count += 1
        else:
            break
    return count
```

---

### Issue 3 - NOTE: Step 5 does not write system metrics as described in the pseudocode

**Severity:** NOTE (improvement)
**File:** `chapter12.10-python-example.md`, `store_classifications` function

The pseudocode Step 5 explicitly writes to two Timestream tables: `waveform-classifications` (per-window results) and `waveform-system-metrics` (alert rate, mean signal quality, classifications per minute). The Python implementation only writes to the classifications table. The `TIMESTREAM_TABLE_METRICS` constant is defined but never used.

This is a minor gap since the demo is already long, but a reader following the pseudocode step-by-step would notice the omission.

**Fix:** Add a brief system metrics write after the classification records, or add a comment noting the omission:

```python
# NOTE: Production also writes to TIMESTREAM_TABLE_METRICS with
# aggregate stats (alert_rate, mean_sqi, classifications_per_minute).
# Omitted here for brevity; see pseudocode Step 5 for the full pattern.
```

---

### Issue 4 - NOTE: SageMaker `invoke_endpoint` comment shows correct API but response parsing could confuse learners

**Severity:** NOTE (improvement)
**File:** `chapter12.10-python-example.md`, `classify_waveform_windows` function

The commented-out SageMaker call is correct:

```python
# response = sagemaker_runtime.invoke_endpoint(
#     EndpointName=SAGEMAKER_ENDPOINT,
#     ContentType="application/json",
#     Body=json.dumps({...}),
# )
# prediction = json.loads(response["Body"].read())
```

This is accurate for the current boto3 `sagemaker-runtime` client. The `response["Body"]` is a `StreamingBody` and `.read()` returns bytes. `json.loads()` accepts bytes in Python 3.6+. Correct and clear.

No fix needed. Noting for completeness that this is verified correct.

---

### Issue 5 - NOTE: The `Decimal` import is unused

**Severity:** NOTE (improvement)
**File:** `chapter12.10-python-example.md`, Configuration section

```python
from decimal import Decimal
```

`Decimal` is imported but never used anywhere in the code. The setup notes mention "DynamoDB and Timestream both reject Python `float`" but this recipe uses Timestream (which accepts float for measure values via string conversion) and does not use DynamoDB. The unused import could confuse a reader into thinking they missed where Decimal is needed.

**Fix:** Remove the `Decimal` import, or add a comment explaining it would be needed if DynamoDB were used for alert state persistence (as mentioned in the Step 4 comments about production using DynamoDB for cross-invocation state).

---

### Issue 6 - NOTE: `botocore.config.Config` import is good practice but `boto3` module-level clients are created unconditionally

**Severity:** NOTE (improvement)
**File:** `chapter12.10-python-example.md`, Configuration section

The module-level boto3 clients (`kinesis_client`, `s3_client`, etc.) are created at import time. If a reader copies this file and runs it without AWS credentials configured, they'll get a `NoCredentialsError` at import time before reaching the demo code that uses mocks.

The demo's `run_pipeline` function accepts mock overrides for each client, which is the right pattern. But the module-level client creation could trip up learners who just want to read and run the demo.

This is a minor ergonomic issue. The demo's `run_demo()` function passes mocks explicitly, so it works regardless. But a comment at the module-level client section would help:

```python
# Module-level clients. These require AWS credentials to be configured.
# The demo's run_demo() function bypasses these by passing mock objects.
# If you see NoCredentialsError on import, that's expected when running
# the demo standalone.
```

---

## Summary

The code is well-structured, pedagogically sound, and faithfully implements the five-step pipeline from the main recipe. The two WARNING findings (Timestream time format mismatch and longest-vs-trailing consecutive count) represent patterns that would produce runtime errors or subtly wrong behavior if copied to production, but neither prevents the demo from running against its mocks. The NOTE findings are minor improvements that would enhance clarity for learners. Overall, this is a solid teaching implementation of a complex real-time waveform analysis pipeline.
