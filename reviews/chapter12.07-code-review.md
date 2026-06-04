# Code Review: Recipe 12.7 - Vital Sign Trajectory Monitoring

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter12.07-vital-sign-trajectory-monitoring.md` (pseudocode reference)
- `chapter12.07-python-example.md` (Python companion)

---

## Verdict: PASS

The Python companion is well-structured, pedagogically sound, and faithfully implements all six pseudocode steps from the main recipe. The trajectory math is correct, the multi-parameter correlation logic works as described, and the alert suppression demonstrates the discipline the recipe demands. Two warnings and several notes are documented below, but none rise to the level of blocking publication.

---

## Findings

### Issue W1 - WARNING: Kinesis `Data` parameter should be bytes, not str

**Severity:** WARNING
**File:** `chapter12.07-python-example.md`, Step 1 (`ingest_vital_sign`)
**Section:** `mock_kinesis.put_record(...)` call

The code passes `Data=json.dumps(normalized)` which produces a Python string. The real boto3 Kinesis `put_record` API requires `Data` to be `bytes` or a file-like object. A learner copying this pattern verbatim into production code would get a `ParamValidationError` from botocore's parameter validation.

**How to fix:** Change to `Data=json.dumps(normalized).encode("utf-8")`. The mock's `__init__` would then need to decode in its `put_record` method (or store raw bytes). Since the mock already calls `json.loads(Data)`, the simplest fix is encoding on the write side and documenting that real Kinesis requires bytes.

---

### Issue W2 - WARNING: Logging contradicts its own PHI guidance

**Severity:** WARNING
**File:** `chapter12.07-python-example.md`, Configuration section and Steps 1/5/6
**Section:** Logger comment vs. actual log statements

The configuration section explicitly states: "Never log raw vital sign values with patient identifiers. Log structural metadata only: patient_id_hash, parameter, alert_decision, runtime_ms." However, the code then logs raw `patient_id` values in multiple places:

- `logger.info("Ingested %s reading for patient %s", normalized["parameter"], normalized["patient_id"])`
- `logger.info("Patient %s: %s (%s)", pid, action, ...)`
- `logger.info("Patient %s: %s fired - %s", pid, action.upper(), ...)`

For a teaching example focused on HIPAA-compliant healthcare pipelines, this contradiction could confuse learners about what the actual expectation is.

**How to fix:** Either (a) hash the patient_id before logging (e.g., `pid_hash = hashlib.sha256(pid.encode()).hexdigest()[:8]`) to match the stated guidance, or (b) soften the comment to say "In production, hash patient identifiers in logs" and add a brief inline note at the first log call explaining the demo uses synthetic IDs so raw logging is acceptable here.

---

### Issue N1 - NOTE: `import random` inside the demo loop body

**Severity:** NOTE
**File:** `chapter12.07-python-example.md`, `run_demo()` function
**Section:** Patient A simulation loop

`import random` appears inside the `for i in range(16)` loop. Python caches module imports so this has no runtime cost, but it's unusual placement that may confuse learners about import conventions. Moving it to the top-level imports (alongside `json`, `logging`, etc.) would be cleaner.

---

### Issue N2 - NOTE: MockDynamoDB class is defined but never used by the pipeline

**Severity:** NOTE
**File:** `chapter12.07-python-example.md`, Mocks section and Step 2

The code defines `MockDynamoDB` with `get_item`/`put_item` methods and instantiates `mock_dynamodb`, but the actual pipeline uses the in-memory `PATIENT_STATES` dict directly. This is not incorrect (the code works), but a learner might be confused about why the DynamoDB mock exists if it's never called. A one-line comment like `# In a production Lambda, you'd replace PATIENT_STATES with DynamoDB calls via mock_dynamodb` would clarify the intent.

---

### Issue N3 - NOTE: Demo could show DynamoDB Decimal discipline

**Severity:** NOTE
**File:** `chapter12.07-python-example.md`, Step 2 and Mocks section

The code imports `Decimal` at the top but never uses it because patient state lives in a Python dict rather than flowing through DynamoDB. Since the recipe's AWS architecture specifies DynamoDB for patient state, demonstrating the `Decimal(str(value))` pattern (even in a comment or a brief helper function) would reinforce the DynamoDB-specific lesson for learners who will hit the float-to-Decimal issue in production.

---

### Issue N4 - NOTE: `stdev` requires at least 2 data points but `compute_trajectory` gate checks for 3

**Severity:** NOTE
**File:** `chapter12.07-python-example.md`, Step 3 (`compute_trajectory`)

The function returns `None` if `len(readings) < 3`, and later calls `stdev(values)` which requires `len(values) >= 2`. The gate is sufficient (3 > 2), so this is safe. Just noting the implicit dependency is covered.

---

## Pseudocode-to-Python Mapping

| Pseudocode Step | Python Function | Consistent? |
|-----------------|----------------|-------------|
| Step 1: `ingest_vital_sign(source_event)` | `ingest_vital_sign(source_event)` | Yes |
| Step 2: `update_patient_state(vital_event)` | `update_patient_state(vital_event)` | Yes |
| Step 3: `compute_trajectory(state, parameter)` | `compute_trajectory(state, parameter)` | Yes |
| Step 4: `check_multi_parameter_patterns(all_trajectories)` | `check_multi_parameter_patterns(all_trajectories)` | Yes |
| Step 5: `evaluate_alert(patient_state, trajectories, pattern_matches)` | `evaluate_alert(patient_state, all_trajectories, pattern_matches)` | Yes (medication suppression omitted, acknowledged in Gap section) |
| Step 6: `persist_and_route(patient_state, trajectories, alert_decision)` | `persist_and_route(patient_state, all_trajectories, alert_decision)` | Yes |

The pseudocode's medication-aware suppression (Step 5, check 3) is intentionally omitted from the Python companion. This is documented in the "Gap Between This and Production" section with a clear explanation of why (requires MAR integration, 3-6 month project). Acceptable scope reduction for a teaching example.

---

## Checklist Results

| Check | Result |
|-------|--------|
| Code runs without errors (given mocks) | PASS - sequential processing against in-memory stores works end-to-end |
| Pseudocode steps all implemented | PASS - all 6 steps present in same order |
| No hardcoded credentials | PASS - no `aws_access_key_id` literals; ARN uses example account |
| No silent exception swallowing | PASS - no bare `except:` blocks |
| DynamoDB uses Decimal not float | N/A - DynamoDB mock defined but not used in pipeline path |
| S3 paths no leading slash | N/A - no S3 usage in this recipe |
| Pagination handled for list calls | N/A - no `list_*` calls |
| Comments explain "why" not just "what" | PASS - comments are pedagogically strong throughout |
| Logical flow builds understanding | PASS - top-to-bottom progression matches the recipe's narrative arc |
| Alert fatigue mitigation demonstrated | PASS - cooldown, baseline stabilization, artifact detection all present |
| Artifact rejection demonstrated | PASS - variability threshold + short window check in Step 5 |
| boto3 API method names correct | PASS - `put_record`, `write_records`, `publish` all correct |
| boto3 parameter names correct | PASS with W1 caveat (Data type) |
| Timestream multi-measure format correct | PASS - `MeasureValues` array with `MeasureValueType: "MULTI"` is correct |

---

## Summary

Strong Python companion that faithfully translates the recipe's architecture into runnable code. The trajectory math (linear regression slope, EMA baselines, multi-parameter correlation) is correct and clearly explained. The demo generates a convincing sepsis deterioration scenario that shows the pipeline detecting coordinated vital sign changes. The two warnings (Kinesis bytes encoding, PHI logging contradiction) are real but non-blocking for a teaching example; both are easy one-line fixes if the author wants to tighten them up before publication.
