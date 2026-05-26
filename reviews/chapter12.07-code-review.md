# Code Review: Recipe 12.7 - Vital Sign Trajectory Monitoring

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter12.07-vital-sign-trajectory-monitoring.md` (**NOT FOUND**)
- `chapter12.07-python-example.md` (**NOT FOUND**)

---

## Verdict: FAIL

The Python companion this task is meant to review does not exist. Neither does the upstream main recipe. The pipeline chain `ch12-r07-draft → ch12-r07-python → ch12-r07-code-review` has not been completed: only spec stubs exist in `specs/`, no output artifacts have been produced. I will not fabricate a review against a file that does not exist. The verdict is FAIL on the ERROR finding below until the upstream tasks land.

---

## Findings

### Issue E1 - ERROR: Python companion file missing

**Severity:** ERROR
**File:** `chapter12.07-python-example.md` (does not exist)

A filesystem-wide search for `chapter12.07*`, `*vital-sign*`, and `*12.7*` returns no source artifacts. Only the two `reviews/chapter12.07-*.md` review files exist, both of which were produced under the same blocked-upstream condition.

The most recent committed chapter 12 artifact is `chapter12.06-python-example.md`. Beyond that, only spec stubs exist for recipes 12.7 through 12.10. The draft for 12.7's main recipe has not been generated either, so the fallback path I used on 12.6 (reconstructing pseudocode from the main recipe when only the Python companion was present) is not available here.

The task spec `specs/ch12-r07-code-review.md` declares its own output target as `reviews/chapter12.07-code-review.md` and depends on `ch12-r07-python`. The upstream `specs/ch12-r07-python.md` declares output `chapter12.07-python-example.md` and depends on `ch12-r07-draft`. Both upstream outputs are absent.

**How to fix:**

1. Run `ch12-r07-draft` to produce `chapter12.07-vital-sign-trajectory-monitoring.md`. Per the chapter 12 planning doc, recipe 12.7 is Medium-Complex with named hidden challenges of real-time processing, patient-specific baselines, alert fatigue, and clinical-trigger semantics. The draft must include the standard recipe sections (Problem, Technology, General Architecture, AWS Implementation with pseudocode walkthrough, Honest Take, Variations, navigation links).
2. Run `ch12-r07-python` to produce `chapter12.07-python-example.md`. Whatever streaming or windowed-trajectory pseudocode the main recipe codifies, the Python companion must implement those same steps in the same order.
3. Re-run this code review task once both artifacts exist.

---

## Pseudocode-to-Python Mapping

Not applicable. Both the main recipe pseudocode and the Python companion are absent.

---

## What was checked

- `chapter12.07-vital-sign-trajectory-monitoring.md`: missing (filesystem search confirmed)
- `chapter12.07-python-example.md`: missing (filesystem search confirmed)
- `specs/ch12-r07-draft.md`: present, declares output `chapter12.07-vital-sign-trajectory-monitoring.md`
- `specs/ch12-r07-python.md`: present, declares output `chapter12.07-python-example.md`, depends on `ch12-r07-draft`
- `specs/ch12-r07-code-review.md`: present, declares output `reviews/chapter12.07-code-review.md`, depends on `ch12-r07-python`
- `pending_tasks.json`: empty array, no in-flight task
- `categories/12-time-series.md` 12.7 entry: confirms the recipe is Medium-Complex with real-time processing, patient-specific baselines, alert fatigue, and clinical-trigger semantics as the named complexity drivers
- All `chapter12.*` files in repo root: only 12.1 through 12.6 are present (paired main recipe + Python companion); 12.7 through 12.10 are not yet drafted

---

## Notes for the next iteration

These are the criteria the next iteration's Python companion will be measured against, derived from the chapter 12 planning doc and the failure modes that triggered findings on earlier chapter 12 reviews. They are not findings against the current (non-existent) code.

### Pseudocode-to-Python correspondence

If the main recipe's pseudocode describes a streaming consumer (Kinesis Data Streams, IoT Core, or MSK), the Python companion's mock must preserve the same call signatures (`get_records`, `get_shard_iterator`, `put_record`, etc.) with parameter names matching boto3 even when running against an in-memory stub. Folding a real-time detection path and an analytical-window path into a single function would be a misleading-pattern WARNING if the pseudocode separates them.

### Decimal at the DynamoDB boundary

Vital sign values are inherently float (heart rate 72.5, SpO2 96.4, BP 118.5/76.2, RR 14.3, temperature 37.1). Every value reaching `put_item`, `update_item`, or a `batch_writer` context must pass through a `_to_decimal` helper that:

- Quantizes to a stable scale before `Decimal(...)` (use `Decimal(str(value))` to avoid float-to-Decimal precision artifacts)
- Handles the Python `bool`-is-`int` subtlety (don't coerce booleans into Decimals)
- Recurses into dicts and lists if the schema nests measurements

A bare `Decimal(float_value)` or, worse, raw float passed into DynamoDB will trigger an ERROR.

### S3 key construction

Streaming pipelines often build keys from timestamps and patient IDs. A key template like `f"/{date}/{patient_id}/..."` is a common slip and is invalid; S3 keys must not start with a slash. Every constructed key must start with a path component. This has been an ERROR-class pattern in earlier chapter reviews.

### PHI exclusion at logging boundaries

Vital sign streams keyed to identifiable patients are PHI. Structured logs (`logger.info(...)`, `print(...)`, CloudWatch Logs payloads) must carry only run-level metadata: `run_id`, snapshot counts, sample counts, runtime, alert counts. They must not carry `patient_id`, MRN, raw measurement values, or anything else that would render the log line PHI. Hashed or salted patient identifiers in logs are acceptable only if the recipe explicitly establishes the hashing scheme.

### Patient-specific baseline math

If the recipe describes a personalized baseline (rolling-window mean and standard deviation per patient, an EWMA with a defined decay parameter, or a Kalman-filter-style state estimator), the Python implementation's update step must match the pseudocode's update step exactly. The W1 finding on 12.6 was driven by a sub-process double-counting variance that the upstream estimator had already absorbed; the same class of error is easy to make in a per-patient EWMA over vitals.

### Alert-fatigue guardrails

The chapter 12 planning doc names alert fatigue as a hidden challenge for 12.7. A naive `if score > threshold: alert()` pattern teaches a bad habit. The Python companion should demonstrate at least one of:

- Hysteresis: suppress alerts within N minutes of a prior alert for the same patient and same channel
- Tiered thresholds: e.g., a MEWS-style 3-of-N criterion, or escalation tiers (notify nurse before paging rapid response)
- Persistence requirements: require the trajectory to violate threshold for K consecutive samples before alerting

A bare threshold compare with no fatigue mitigation will at minimum draw a WARNING.

### Artifact vs. real change

The planning doc explicitly calls out "must distinguish artifact from real changes" as a complexity driver. The Python companion should at least demonstrate a sentinel filter (drop physically impossible values: HR < 20 or > 250, SpO2 < 50 or > 100, etc.) and ideally a brief-deviation filter (require K-of-N samples in the abnormal range) before scoring. A code path that scores raw measurements without artifact rejection misses the recipe's stated point.

### Real-time vs. analytical-window separation

If the pseudocode separates a streaming detection path from a batched trajectory-analysis path (a common pattern for vital signs: streaming MEWS-style alerts plus a 4-hour or 24-hour deterioration trend), the Python file must reflect that separation as two distinct functions, not a single conflated loop.

### Mock-driven end-to-end run

Per established chapter pattern, the Python companion must be runnable end-to-end against a mock without real AWS calls. The mock layer should be obvious to the reader (a `class MockKinesisClient` or `@patch('boto3.client', ...)` setup) and the runtime path should not silently skip the streaming integration in mock mode.

### Pagination, retries, and credentials

Standard checks that apply across chapters:

- Any `list_*` boto3 call must demonstrate pagination handling (paginator or explicit `NextToken` loop), even if the example dataset is small
- No hardcoded credentials, no `aws_access_key_id=...` literals
- No silent `except Exception: pass`; comments must explain why a particular exception class is acceptable to swallow

These are baseline expectations and would each draw a WARNING or ERROR depending on context.

---

## Status

This task is blocked on the upstream pipeline. Expected resolution path:

1. `ch12-r07-draft` runs and produces `chapter12.07-vital-sign-trajectory-monitoring.md`
2. `ch12-r07-python` runs and produces `chapter12.07-python-example.md`
3. `ch12-r07-code-review` re-runs against the now-present Python companion and emits a substantive PASS/FAIL with findings against actual code
