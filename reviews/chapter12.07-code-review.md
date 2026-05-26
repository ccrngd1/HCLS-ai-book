# Code Review: Recipe 12.7 - Vital Sign Trajectory Monitoring

**Reviewer:** Tech Code Reviewer
**Files reviewed:**
- `chapter12.07-vital-sign-trajectory-monitoring.md` (**NOT FOUND** in working tree)
- `chapter12.07-python-example.md` (**NOT FOUND** in working tree)

---

## Verdict: FAIL

This review is blocked. The Python companion file that this task is supposed to review does not exist in the working tree, and neither does the upstream main recipe. The pipeline dependency chain for recipe 12.7 (`ch12-r07-draft` → `ch12-r07-python` → `ch12-r07-code-review`) has not been satisfied: only the draft and python specs exist in `specs/`, no output artifacts have been produced. I will not fabricate a review against a file that does not exist, so the verdict is FAIL on the ERROR-level finding below until the upstream tasks land.

---

## Findings

### Issue E1 - ERROR: Python companion file missing, code review is unreviewable

**Severity:** ERROR
**File:** `chapter12.07-python-example.md` (does not exist)

The validation block in `specs/ch12-r07-code-review.md` declares:

```yaml
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter12.07-code-review.md]
```

and the upstream spec `specs/ch12-r07-python.md` declares:

```yaml
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter12.07-python-example.md]
```

A filesystem-wide search confirms `chapter12.07-python-example.md` is absent (`find / -name "chapter12.07*"` returns no results). The most recent chapter 12 artifacts in the working tree are `chapter12.06-python-example.md` (committed) and the spec stubs for recipes 12.6 through 12.10. No draft for 12.7's main recipe exists either, so even reconstructing the pseudocode-to-Python mapping (the fallback I used for 12.6's review when the main recipe was missing but the Python companion was present) is not possible here.

**How to fix:**

1. Run the `ch12-r07-draft` task to produce `chapter12.07-vital-sign-trajectory-monitoring.md` per `specs/ch12-r07-draft.md`. The draft must include the five-section recipe structure (Problem, Technology, General Architecture, AWS Implementation with pseudocode walkthrough, Honest Take, Variations, navigation links) per `RECIPE-GUIDE.md` and the chapter 12 planning doc's positioning of 12.7 as Medium-Complex (real-time processing, patient-specific baselines, alert fatigue risk, clinical-trigger semantics).
2. Run the `ch12-r07-python` task to produce `chapter12.07-python-example.md` per `specs/ch12-r07-python.md`. Given the recipe's "continuously analyze vital sign streams" framing, the Python companion will likely involve at least one of: AWS IoT Core or Kinesis ingestion, a streaming feature pipeline, a per-patient baseline store, a deterioration-score model, and a clinical alert delivery surface. Whatever ingestion-and-alerting pattern the main recipe's pseudocode codifies, the Python file must implement those same steps in the same order, with the standard chapter 12 disciplines (Decimal at every DynamoDB write site, no leading slashes on S3 keys, no PHI in structured logs, mock-driven end-to-end run).
3. Re-run this code review task once both artifacts exist.

Until those upstream artifacts land, this review cannot evaluate any of the standard correctness, pseudocode-to-Python, AWS SDK accuracy, comment quality, or logical flow criteria, because there is no code to evaluate.

---

## Pseudocode-to-Python Mapping

Not applicable. Both the main recipe pseudocode and the Python companion are absent.

---

## What was checked

- `chapter12.07-vital-sign-trajectory-monitoring.md`: missing
- `chapter12.07-python-example.md`: missing
- `specs/ch12-r07-draft.md`: present, declares output `chapter12.07-vital-sign-trajectory-monitoring.md`
- `specs/ch12-r07-python.md`: present, declares output `chapter12.07-python-example.md`, depends on `ch12-r07-draft`
- `specs/ch12-r07-code-review.md`: present, declares output `reviews/chapter12.07-code-review.md`, depends on `ch12-r07-python`
- Filesystem-wide search for `chapter12.07*` and any "vital sign trajectory" candidate: no matches
- `pending_tasks.json`: empty array (no in-flight task hint)
- `categories/12-time-series.md` 12.7 entry: confirms this recipe is Medium-Complex with real-time processing, patient-specific baselines, and alert fatigue as the named hidden challenges

---

## Notes for the next iteration

Once the Python companion exists, the review should specifically watch for the chapter 12 patterns that have already triggered findings in earlier reviews:

- **Decimal at the DynamoDB boundary.** Vital sign values are floats by their nature (heart rate of 72.5, SpO2 of 96.4). Every value reaching `put_item` or `batch_writer` must go through a `_to_decimal` helper that handles the `bool`-is-`int` Python subtlety and quantizes to a stable scale.
- **No leading slashes on S3 keys.** Streaming pipelines often build keys from timestamps, and a `f"/{date}/{patient_id}/..."` template is a common slip. Every constructed key must start with a path component, not a slash.
- **PHI exclusion at logging boundaries.** Vital sign streams are PHI when keyed to identifiable patients. Structured logs must carry only run-level metadata (run_id, snapshot counts, sample counts, runtime), never patient_id or measurement values.
- **Streaming vs. batch pseudocode-to-Python correspondence.** If the main recipe's pseudocode describes a streaming Kinesis or IoT consumer, the Python companion's mock must preserve the same call signatures (e.g., `get_records`, `put_record`, `get_shard_iterator` with the right parameters) even when running against an in-memory mock.
- **Patient-specific baseline math.** If the recipe describes a personalized baseline (e.g., rolling-window mean and standard deviation per patient, or a Kalman-filter-style state estimator), the Python implementation's update-step formula must match the pseudocode's update-step formula. This was the class of issue that triggered the W1 finding on 12.6 (a sub-process double-counted population already absorbed into the upstream estimator).
- **Alert-fatigue guardrails.** The planning doc names alert fatigue as a hidden challenge for 12.7. The Python companion should at minimum demonstrate hysteresis (suppress alerts within N minutes of a prior alert for the same patient) or a tiered threshold (e.g., MEWS-style 3-of-N criterion) rather than a raw `if score > threshold: alert()` pattern that would teach a bad habit.
- **Real-time vs. analytical-window separation.** If the recipe pseudocode separates the streaming detection path from a batched trajectory-analysis path, the Python file must reflect that separation. Folding both into a single function would be a misleading-pattern WARNING.

These notes are forward-looking. They are not findings against the current (non-existent) code; they are the criteria the next iteration should be measured against once the Python companion lands.
