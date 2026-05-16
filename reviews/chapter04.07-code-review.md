# Code Review: Recipe 4.7 - Care Management Program Enrollment

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-16
**Files reviewed:**
- `chapter04.07-care-management-program-enrollment.md` (main recipe pseudocode)
- `chapter04.07-python-example.md` (Python companion)

**Validation performed:**
- Walked the six pseudocode steps against Python functions
- Verified boto3 API call shapes for DynamoDB resource (`get_item`, `put_item`, `update_item`, `scan`), Bedrock Runtime, Kinesis, CloudWatch
- Traced numeric values through `_to_decimal` / `_to_decimal_dict` / `_from_decimal`
- Verified DynamoDB `UpdateExpression` syntax against the AWS DynamoDB documentation
- Walked the demo runner end-to-end against the seeded synthetic patients

---

## Summary

The Python companion is structurally faithful to the main recipe's six pseudocode steps and the architectural picture (program registry, eligibility evaluation, per-program response enrichment, multi-stage capacity-aware allocation, briefing dispatch with templated fallback, engagement-and-retention worker, disenrollment decision-support, cross-program transitions, post-graduation observation). The Decimal-at-the-DynamoDB-boundary discipline is consistent, the four-layer LLM validator pattern is uniform across briefings and disenrollment rationales, the multi-stage allocator threads capacity, equity floors, single-active-primary, and add-on caps in the right order, and the canonical-source semantics for outreach-result transitions are correctly handled.

That said, two ERRORs need to be fixed before this goes to readers. The first is a chapter-wide DynamoDB usage bug: `ADD state_history :history_event` is invalid `UpdateExpression` syntax because `ADD` only supports Number and Set data types, not Lists. The pattern appears in ten places in this file and the call would raise `ValidationException` against any real DynamoDB table. The demo masks this because the tables don't exist (so `ResourceNotFoundException` is what actually fires, and `try/except` swallows both). The second is a `record_outreach_attempt` decrement path that references an undefined `:zero` placeholder in `ConditionExpression` and passes `ExpressionAttributeNames=None`; this would also raise `ValidationException` against a real table. Beyond the ERRORs, the demo runner's print messages imply simulations that don't actually run because no tables exist, the `recommend_cross_program_transitions` implementation deviates silently from the pseudocode, and a handful of smaller issues mirror findings from the 4.5 and 4.6 reviews.

---

## Verdict: FAIL

Two ERRORs (each is automatically a FAIL per persona rules), one WARNING, six NOTEs.

---

## Findings

### Finding 1: `ADD state_history :history_event` Is Invalid DynamoDB UpdateExpression Syntax

- **Severity:** ERROR
- **File:** `chapter04.07-python-example.md`
- **Locations:** ten `update_item` calls, including:
  - `allocate_enrollments` (recommendation persistence loop)
  - `dispatch_outreach` (state transition to `outreach_in_progress`)
  - `record_outreach_attempt` (consented, declined, unreachable terminal, deferred branches)
  - `score_engagement` (state transition to engaged/at_risk)
  - `_persist_disenrollment` (helper used by graduation, disenrollment-for-cause, disenroll-incomplete, transition-out branches)
  - `process_disenrollment_decision` (graduation and extension branches)
- **Description:**

  Each of these calls uses an UpdateExpression of the form:

  ```python
  UpdateExpression=(
      "SET #s = :recommended, ... "
      "ADD state_history :history_event"
  ),
  ExpressionAttributeValues=_to_decimal_dict({
      ...
      ":history_event": [{
          "event": "transitioned_eligible_to_recommended",
          "timestamp": run_date,
          "stage": row["stage_name"],
          "allocation_reason": row["allocation_reason"],
      }],
  }),
  ```

  The intent is to append the `:history_event` entry to a List-typed `state_history` attribute. The DynamoDB documentation is unambiguous on this:

  > The `ADD` action only supports Number and set data types.

  Lists are not supported. boto3's resource API serializes a Python `list` containing a `dict` as a DynamoDB List of Maps (the L type), because dicts cannot be set members. When DynamoDB receives `ADD state_history :history_event` with `:history_event` typed as L, it returns:

  ```
  ValidationException: Invalid UpdateExpression: Incorrect operand type
  for operator or function; operator: ADD, operand type: L
  ```

  Every one of the ten call sites would fail at runtime against a real DynamoDB table. The demo runner doesn't surface this because it runs without provisioned tables, so the boto3 client raises `ResourceNotFoundException` first, and the surrounding `try/except Exception as exc: logger.warning(...)` blocks swallow both error types identically. A reader who provisions the tables described in the Setup section and re-runs the demo would see the warnings fire on every state transition and would discover the state machine never persists.

  Two consequences:

  1. **State history never gets appended through these paths.** The state machine is the source of truth for downstream consumers (engagement tracker, disenrollment evaluator, post-graduation observation, equity dashboard). Every `state_history.append(...)` operation in the pseudocode is an audit-trail entry; with this pattern, the audit trail is empty for every state transition that goes through `update_item`.
  2. **A learner copies the pattern.** The 4.6 review explicitly endorsed this same pattern as "correct semantics." Both reviews are wrong on this point, and shipping 4.7 with the same pattern reinforces the misuse.

- **Suggested fix:** Replace `ADD state_history :history_event` with `SET state_history = list_append(if_not_exists(state_history, :empty), :history_event)`, defining `:empty` as `[]` in `ExpressionAttributeValues`. The pattern looks like:

  ```python
  state_table.update_item(
      Key={"patient_id": row["patient_id"],
            "program_id": row["program_id"]},
      UpdateExpression=(
          "SET #s = :recommended, recommended_run_date = :rd, "
          "allocation_reason = :ar, allocation_stage = :stg, "
          "policy_version = :pv, "
          "state_history = list_append("
          "    if_not_exists(state_history, :empty), :history_event"
          ")"
      ),
      ExpressionAttributeNames={"#s": "state"},
      ExpressionAttributeValues=_to_decimal_dict({
          ":recommended": "recommended",
          ":rd":          run_date,
          ":ar":          row["allocation_reason"],
          ":stg":         row["stage_name"],
          ":pv":          POLICY_VERSION,
          ":empty":       [],
          ":history_event": [{
              "event":             "transitioned_eligible_to_recommended",
              "timestamp":         run_date,
              "stage":             row["stage_name"],
              "allocation_reason": row["allocation_reason"],
          }],
      }),
  )
  ```

  Apply the same transformation to all ten call sites. The `if_not_exists` wrapper ensures the first write (when `state_history` does not yet exist) initializes the list correctly; subsequent writes append. This same fix should be propagated to Recipe 4.6's Python example, which has the same bug.

  As a smoke test, drop a `boto3-stubs`-enabled or DynamoDB-Local-backed test for one transition path before re-running.

---

### Finding 2: Decrement of `cm_outreach_recent_30d_count` References Undefined `:zero` Placeholder; Also Passes `ExpressionAttributeNames=None`

- **Severity:** ERROR
- **File:** `chapter04.07-python-example.md`
- **Location:** `record_outreach_attempt`, the `unreachable` terminal branch:

  ```python
  try:
      profile_table.update_item(
          Key={"patient_id": patient_id},
          UpdateExpression=(
              "ADD cm_outreach_recent_30d_count :neg "
          ),
          ExpressionAttributeValues={":neg": Decimal("-1")},
          ConditionExpression="cm_outreach_recent_30d_count > :zero",
          ExpressionAttributeNames=None,
      )
  except Exception:
      pass
  ```

- **Description:**

  Two bugs collocated:

  1. **Missing `:zero` placeholder.** The `ConditionExpression` references `:zero`, but `ExpressionAttributeValues` only defines `:neg`. DynamoDB returns `ValidationException: An expression attribute value used in expression is not defined; attribute value: :zero`. Every invocation through this branch fails. The catchall `except Exception: pass` then swallows the error silently, with no log entry, no metric, and no operator visibility. The CM outreach budget counter is never decremented after an unreachable-terminal outcome.

  2. **`ExpressionAttributeNames=None`.** boto3 accepts the absence of the parameter (i.e., not passing it at all), but explicitly passing `None` when the parameter is expected to be a `dict` is, at minimum, defensive-cargo-cult code. Some boto3 versions tolerate it; some surface a `ParamValidationError` before the request is sent. Either way, the parameter is unused here (no expression-attribute-names appear in the UpdateExpression or ConditionExpression), so the parameter should simply be omitted.

  Beyond the bugs, the silent-failure design means the patient's CM outreach budget remains incremented after every unreachable terminal, which prevents future enrollment outreach for that patient. The cumulative effect on a population scale is that patients who become unreachable on first attempt are silently locked out of all CM enrollment outreach for 30 days, regardless of whether the original outreach actually consumed a slot.

- **Suggested fix:** Define `:zero`, drop `ExpressionAttributeNames`, and change the catch to log a warning rather than `pass`. The recipe's "Why This Isn't Production-Ready" section already names the contact-budget reconciliation gap; this fix aligns the code with the explicitly-named pattern from 4.5's review:

  ```python
  try:
      profile_table.update_item(
          Key={"patient_id": patient_id},
          UpdateExpression="ADD cm_outreach_recent_30d_count :neg",
          ConditionExpression="cm_outreach_recent_30d_count > :zero",
          ExpressionAttributeValues={
              ":neg":  Decimal("-1"),
              ":zero": Decimal("0"),
          },
      )
  except Exception as exc:
      logger.warning(
          "Failed to decrement CM outreach counter for %s: %s",
          patient_id, exc,
      )
  ```

  The `:zero` value as a `Decimal` matches the column's persisted type (the demo seeds `cm_outreach_recent_30d_count` as `Decimal("0")`). The `ConditionExpression` prevents the counter from going negative if the original increment failed.

---

### Finding 3: Demo Runner's Print Messages Imply Simulations That Don't Actually Run

- **Severity:** WARNING
- **File:** `chapter04.07-python-example.md`
- **Location:** Demo runner (`if __name__ == "__main__":` block)
- **Description:**

  The demo runs offline (Bedrock helpers patched via `globals()`), but the rest of the boto3 calls are real. No DynamoDB tables exist in the offline run, so every `get_item`, `put_item`, `update_item`, `scan`, and Kinesis `put_record` raises `ResourceNotFoundException` and is silently caught by surrounding `try/except` blocks.

  The print statements imply simulations actually execute end-to-end:

  ```
  Simulating outreach result: Linda consents to HF program
  ...
  Simulating engagement scoring at week 4 (Step 5)...
  ...
  Simulating disenrollment evaluation and human decision (Step 6)...
  ```

  In practice:
  - `record_outreach_attempt`'s state-transition `update_item` call fails (`ResourceNotFoundException`); the state never advances to `enrolled`, no `program_outreach_attempted` Kinesis event is emitted (Kinesis stream doesn't exist either), the consent metadata is never persisted.
  - `score_engagement` first calls `state_table.get_item(...)`, which returns no Item (table doesn't exist, exception caught, `state_record = {}`). The `if state_record.get("state") not in ("enrolled", ...)` check fails (`None not in (...)`), and the function returns `{}` without scoring engagement. The engagement profile seeded into `_DEMO_ENGAGEMENT_PROFILES` is never read.
  - `evaluate_disenrollment` similarly reads an empty `state_record` and returns `{}` after the `if not state_record` guard. The `print(f"  Disenrollment decision: {decision.get('recommended_action')}")` line prints `Disenrollment decision: None`.
  - `process_disenrollment_decision` is only called when `decision.get("decision_id")` is truthy, which it never is. So that path is skipped entirely.
  - `recommend_cross_program_transitions` works (it doesn't read state), but the `put_item` to `cross-program-transitions` and the Kinesis `put_record` both fail silently.
  - `post_graduation_observation` does a full `state_table.scan()` which returns nothing (table doesn't exist), so no relapses are detected.

  The demo prints `Demo complete` at the end. A reader sees the prints, assumes the simulations exercised the success paths, and never realizes nothing actually persisted. This is the same class of issue Recipe 4.6's review flagged (the pneumococcal-age mismatch silently no-oping Step 5), but broader: every state-transition path here silently no-ops because the underlying tables don't exist.

- **Suggested fix:** Two reasonable options, pick one:

  1. **Add an explicit "running offline against unprovisioned tables" disclaimer** at the top of the demo runner and after each phase's print:

     ```python
     print("=" * 70)
     print("Note: this demo runs OFFLINE. DynamoDB and Kinesis calls fail")
     print("with ResourceNotFoundException because the tables and stream")
     print("do not exist; failures are caught and logged at WARNING. The")
     print("demo prints below describe what each step WOULD do against")
     print("a provisioned environment, not what the code persists in")
     print("this run.")
     print("=" * 70)
     ```

     This is the lighter fix and matches the pedagogical convention of "this is the shape of the code; provision the infrastructure to actually run it."

  2. **Provide a DynamoDB-Local + Kinesis-Local docker-compose snippet** in the Setup section (or in a separate appendix) so the demo can be exercised end-to-end. Heavier, but the demo prints would then accurately reflect what runs.

  Option 1 is sufficient for a teaching example; Option 2 is closer to production-grade. Either way, the current message wording ("Linda consents," "engagement scoring at week 4," "disenrollment evaluation and human decision") needs to be reframed to acknowledge that the simulation is structural, not behavioral.

  Adjacent cleanup: at minimum, change the `try/except Exception: pass` patterns inside DynamoDB calls to `try/except Exception as exc: logger.warning(...)` so a reader running with `logger.setLevel(logging.WARNING)` (which is the default at the top of the file) can at least see the failures.

---

### Finding 4: `recommend_cross_program_transitions` Deviates From Pseudocode Without Acknowledgment

- **Severity:** NOTE
- **File:** `chapter04.07-python-example.md`
- **Location:** `recommend_cross_program_transitions`
- **Description:**

  The pseudocode in the main recipe (Step 6) describes a priority-based cross-program-transition recommender:

  ```
  current_eligibility = read_current_eligibility(patient_id)
  current_uplifts = read_current_uplifts(patient_id)
  candidates = []
  FOR each program_id, eligibility in current_eligibility:
      IF eligibility != "eligible": CONTINUE
      IF program_id == prior_program_id: CONTINUE
      priority = synthesize_priority(current_uplifts[program_id], context)
      candidates.append({...})
  candidates_sorted = sort candidates by priority DESC
  IF len(candidates_sorted) > 0:
      top_candidate = candidates_sorted[0]
      DynamoDB.PutItem(...)
  ```

  The Python implementation skips the priority-and-eligibility computation entirely and looks up a static map:

  ```python
  candidate_program_ids = CROSS_PROGRAM_TRANSITIONS_MAP.get(
      (prior_program_id, context), [],
  )
  if not candidate_program_ids:
      return {}
  chosen = None
  for pid in candidate_program_ids:
      if pid in program_lookup:
          chosen = pid
          break
  ```

  The reference-data section describes the map as "the simplest mappings" with a note that "production: a knowledge graph." That comment names the simplification at the data-definition site but not at the function-implementation site. A reader looking at the function in isolation does not see the deviation.

  Two consequences:

  1. **Missing priority and eligibility checks.** The pseudocode picks the highest-priority eligible program for the patient at run time. The Python picks the first program in a static-map list, regardless of whether the patient is currently eligible for it, and regardless of which other transitions would have higher priority. For the demo's HF graduation, the static map suggests `polypharmacy-management`. If the patient does not meet polypharmacy inclusion criteria (8+ active meds, 2+ prescribers in 180d), the Python recommends polypharmacy anyway.
  2. **The deviation is invisible to the function reader.** The reader of `recommend_cross_program_transitions` does not see "priority is not computed" anywhere in the function or its docstring.

- **Suggested fix:** Add a comment block at the top of the function naming the simplification:

  ```python
  def recommend_cross_program_transitions(patient_id: str,
                                            prior_program_id: str,
                                            context: str,
                                            program_lookup: dict) -> dict:
      """
      Recommend a cross-program transition based on the configured
      transition map. Surface for human review; the human decides
      whether to act.

      NOTE: The pseudocode computes priority across all currently
      eligible programs and picks the highest. This implementation
      uses a static (prior_program, context) -> [candidates] map
      and picks the first map-listed program that exists in the
      registry. It does NOT verify the patient meets the candidate
      program's eligibility criteria. Production replaces with the
      priority-based pseudocode pattern, scored against the
      patient's current eligibility from `patient-program-state`
      and current uplifts from the enrichment pipeline.
      """
      ...
  ```

  Alternatively, implement the priority-based version: read `patient-program-state` rows for this patient, filter to `eligibility == "eligible"`, compute priority via the existing scorers, and pick the top. The reference data could remain as a fallback when no eligibility data is available.

---

### Finding 5: CloudWatch Dimension Defaults Surface as `"None"` When the Cohort Field Is Present-With-None

- **Severity:** NOTE
- **File:** `chapter04.07-python-example.md`
- **Location:** `allocate_enrollments`, the metric emission block
- **Description:**

  Same trap as the 4.5 and 4.6 reviews:

  ```python
  cohort = row.get("cohort_features", {})
  _emit_metric(
      "program_recommended",
      value=1,
      dimensions={
          "program_id":   row["program_id"],
          "stage":        row["stage_name"],
          "engagement_q": str(cohort.get("engagement_history_quartile",
                                            "unknown")),
          "language":     str(cohort.get("language", "unknown")),
          "sdoh_cohort":  str(cohort.get("sdoh_cohort", "unknown")),
      },
  )
  ```

  `dict.get(key, "unknown")` returns the default only when the key is absent. If the key is present with value `None` (a real-world occurrence when the SDOH cohort attribute is explicitly null in the patient profile rather than missing), `cohort.get("sdoh_cohort", "unknown")` returns `None`, and `str(None)` yields the string `"None"`. The CloudWatch dashboard then has two distinct buckets for what should be one cohort: `"unknown"` and `"None"`.

  The demo data has all three cohort fields populated, so this path doesn't fire in the offline run. Production traffic with a mix of explicitly-null and missing cohort attributes will produce both buckets and a confused dashboard.

- **Suggested fix:** Coalesce explicitly:

  ```python
  def _safe_dim(value, fallback="unknown"):
      return str(value) if value not in (None, "") else fallback

  dimensions={
      "program_id":   row["program_id"],
      "stage":        row["stage_name"],
      "engagement_q": _safe_dim(cohort.get("engagement_history_quartile")),
      "language":     _safe_dim(cohort.get("language")),
      "sdoh_cohort":  _safe_dim(cohort.get("sdoh_cohort")),
  },
  ```

  Same fix should propagate to the equivalent CloudWatch emit sites in 4.4, 4.5, and 4.6 if not already applied (4.5's review flagged the same pattern; 4.6's review re-flagged it).

---

### Finding 6: `_compute_program_fit` Returns 0.0 for TCM When `last_discharge_date` Is Missing, Even Though TCM Inclusion Uses `last_admission_date`

- **Severity:** NOTE
- **File:** `chapter04.07-python-example.md`
- **Location:** `_compute_program_fit`, the `transitional-care-management` branch
- **Description:**

  TCM inclusion logic in `_evaluate_inclusion` gates on `inpatient_admission_within_days`, comparing against `patient.get("last_admission_date")`. A patient without a `last_discharge_date` (admitted but not yet discharged, or discharged but the discharge feed is delayed) can still pass inclusion if `last_admission_date` is recent.

  Then `_compute_program_fit` reads:

  ```python
  if program_id == "transitional-care-management":
      last_discharge = patient.get("last_discharge_date")
      if not last_discharge:
          return 0.0
      ...
  ```

  Returning 0.0 for fit drives the priority synthesis to a low value, and the patient is unlikely to be allocated. So a TCM-eligible patient (passed inclusion) silently disqualifies from allocation if the discharge date is missing. The behavior is not wrong (TCM after discharge is the program's whole point), but the inconsistency between inclusion-on-admission-date and fit-on-discharge-date is not explained.

  The demo's pat-002148 has both fields populated, so the path produces fit=1.0 for a 18-day-since-discharge case. (Note: the TCM fit table returns 0.4 at days <= 21 and 0.1 at days > 21, but the demo's 18 days actually returns 0.4 from the lookup, not 1.0; the comment is correct.)

- **Suggested fix:** Either change inclusion to also require `last_discharge_date`, or add a comment to `_compute_program_fit`:

  ```python
  if program_id == "transitional-care-management":
      # TCM fit is anchored to discharge date (the program targets
      # the post-discharge window). A patient who passed inclusion
      # via last_admission_date but lacks last_discharge_date returns
      # 0.0 here; in production, add a discharge-feed-completeness
      # check at inclusion time instead of relying on this fit-side
      # filter.
      last_discharge = patient.get("last_discharge_date")
      if not last_discharge:
          return 0.0
      ...
  ```

---

### Finding 7: `score_engagement` Accepts `program_lookup` But Does Not Use the Program Object

- **Severity:** NOTE
- **File:** `chapter04.07-python-example.md`
- **Location:** `score_engagement`
- **Description:**

  ```python
  def score_engagement(patient_id: str, program_id: str, run_date: str,
                        program_lookup: dict) -> dict:
      ...
      program = program_lookup.get(program_id, {})
      profile = _build_engagement_profile(patient_id, program_id, run_date)
      engagement_score = _engagement_scoring_function(profile, program_id)

      threshold = ENGAGEMENT_PROFILES.get(
          program_id, {}).get("at_risk_threshold", 0.50)
      ...
  ```

  `program` is bound but never read. `at_risk_threshold` is read from the module-level `ENGAGEMENT_PROFILES` constant, not from the registry-loaded program record. The intent looks like the scoring function should read program-specific signals (the `program["engagement_scoring_function"]` reference in the pseudocode), but the implementation hard-codes those into `_engagement_scoring_function` and `ENGAGEMENT_PROFILES`.

  Two consequences:

  1. **Dead parameter.** A reader extending the function might wonder why `program_lookup` is passed. The function signature suggests it's used.
  2. **The pseudocode-to-Python correspondence drifts.** The pseudocode says `program.engagement_scoring_function(profile)`, implying the function comes from the registry. The Python uses a hard-coded table.

- **Suggested fix:** Either remove the unused parameter, or use the program record consistently. The most useful fix is to read the `at_risk_threshold` from `program` first (with the `ENGAGEMENT_PROFILES` constant as fallback), which keeps the registry as the source of truth:

  ```python
  program = program_lookup.get(program_id, {})
  threshold = program.get(
      "at_risk_threshold",
      ENGAGEMENT_PROFILES.get(program_id, {}).get(
          "at_risk_threshold", 0.50),
  )
  ```

  And add a comment explaining why the scoring function itself is module-level rather than registry-driven (training-pipeline produces program-specific weights; the demo embeds them inline for clarity).

---

### Finding 8: `_validate_briefing` Sentinel-Condition Check Is Fragile

- **Severity:** NOTE
- **File:** `chapter04.07-python-example.md`
- **Location:** `_validate_briefing`
- **Description:**

  ```python
  observed_conditions = set(
      observed_context["patient_summary"]["active_conditions"]
  )
  sentinel_conditions = {
      "heart_failure", "diabetes_type_1", "diabetes_type_2",
      "ckd", "copd", "hypertension", "hyperlipidemia",
  }
  for sentinel in sentinel_conditions:
      sentinel_phrase = sentinel.replace("_", " ")
      if sentinel_phrase in full_text and sentinel not in observed_conditions:
          return False
  ```

  The validator checks for `"heart failure"`, `"diabetes type 1"`, `"diabetes type 2"`, `"ckd"`, etc. as substrings in the full briefing text. Two failure modes:

  1. **Underscore-to-space transformation produces awkward sentinels.** `"diabetes_type_1"` becomes `"diabetes type 1"`, which the LLM is unlikely to write naturally. An LLM is more likely to write "type 2 diabetes" or "T2DM" or "diabetes." None of these match the sentinel, so a hallucination of "type 2 diabetes" on a patient without diabetes goes undetected.
  2. **Substring matching has false positives.** `"hypertension"` is a substring of `"pulmonary hypertension"`, which is a related-but-distinct condition. A briefing about a patient with pulmonary hypertension (not in the sentinel list, not in observed_conditions) that happens to mention "pulmonary hypertension" would match the `"hypertension"` sentinel and reject correctly only if `"hypertension"` is also not in observed_conditions.

  The demo's mock briefing avoids medical sentinels (uses "heart-failure decompensation" framing only via the `program_name` field, which is part of `_build_briefing_context`), so the offline path doesn't trigger the failure. Production usage with a real LLM is more exposed.

- **Suggested fix:** Use word boundaries and a richer synonym map:

  ```python
  import re as _re

  CONDITION_SYNONYMS = {
      "heart_failure": [
          r"\bheart failure\b", r"\bhf\b", r"\bchf\b",
          r"\bcardiomyopathy\b",
      ],
      "diabetes_type_2": [
          r"\btype 2 diabetes\b", r"\bt2dm\b", r"\bt2d\b",
          r"\btype ii diabetes\b",
      ],
      "diabetes_type_1": [
          r"\btype 1 diabetes\b", r"\bt1dm\b", r"\bt1d\b",
          r"\btype i diabetes\b",
      ],
      "ckd": [r"\bckd\b", r"\bchronic kidney disease\b"],
      "copd": [r"\bcopd\b",
                r"\bchronic obstructive pulmonary disease\b"],
      "hypertension": [r"\bhypertension\b(?! .*pulmonary)",
                        r"\bhtn\b"],
      "hyperlipidemia": [r"\bhyperlipidemia\b", r"\bdyslipidemia\b"],
  }
  for sentinel, patterns in CONDITION_SYNONYMS.items():
      if any(_re.search(p, full_text, _re.IGNORECASE) for p in patterns)\
          and sentinel not in observed_conditions:
          return False
  ```

  Or simpler: name the simplification in a comment so a reader doesn't assume the validator is robust.

---

### Finding 9: `globals()` Mock Injection Without Explanatory Comment (Same Pattern as 4.5, 4.6)

- **Severity:** NOTE
- **File:** `chapter04.07-python-example.md`
- **Location:** Demo runner (`if __name__ == "__main__":` block)
- **Description:**

  ```python
  globals()["_bedrock_enrollment_briefing"] = _mock_briefing
  globals()["_bedrock_disenrollment_rationale"] = _mock_rationale
  ```

  The pattern works (callers resolve names against module globals at call time) but isn't explained. A learner who tries to apply the same pattern across module boundaries (patch `recipe_lib.py`'s `_bedrock_*` from `runner.py`) discovers it doesn't work the same way. The 4.6 review flagged this exact issue and suggested adopting the comment from 4.5.

- **Suggested fix:** Add the same explanatory comment used in 4.5 and 4.6 (per the 4.6 review's Finding 7):

  ```python
  # Patch the module-level Bedrock helpers for the offline demo. This
  # works because the calling functions resolve _bedrock_* names against
  # the module global namespace at call time, and globals() in __main__
  # returns this module's dict. Production never bypasses these; the
  # real Bedrock calls run.
  globals()["_bedrock_enrollment_briefing"] = _mock_briefing
  globals()["_bedrock_disenrollment_rationale"] = _mock_rationale
  ```

---

## Pseudocode-to-Python Consistency

Six pseudocode steps map onto Python functions, with one substantive deviation (Finding 4):

| Pseudocode Step | Python Function | Consistent? |
|----------------|-----------------|-------------|
| `evaluate_program_eligibility(patients, run_date)` | `evaluate_program_eligibility(patients_list, run_date)` | Yes (helpers `_load_active_programs`, `_evaluate_denominator`, `_evaluate_inclusion`, `_evaluate_exclusions`, `_compute_eligibility_transition`, `_assess_source_completeness`; offline path falls back to `SAMPLE_PROGRAM_REGISTRY`) |
| `enrich_eligible_candidates(eligibility_records, run_date)` | `enrich_eligible_candidates(run_date, patients, program_lookup)` | Yes (per-program uplift, likelihood, engagement, fit; priority synthesis with weighted components; rule-based proxies for the SageMaker calls; comments are explicit) |
| `allocate_enrollments(enriched_candidates, run_date, policy)` | `allocate_enrollments(enriched_candidates, run_date, program_lookup)` | Yes (four-stage allocation: time-sensitive, disease-specific, complex-care, add-ons; per-stage greedy-by-priority; capacity, equity floors, single-active-primary, add-on cap, operational feasibility; cohort-sliced metric) |
| `dispatch_outreach(allocated_recommendations, run_date)` | `dispatch_outreach(allocated_recommendations, run_date, patients, program_lookup)` | Yes (briefing context build, Bedrock call with templated fallback, validator, briefing persist, care-manager routing, outreach state, optimistic CM-budget increment, state transition, Kinesis emit) |
| `record_outreach_attempt(outreach_id, attempt_result)` | `record_outreach_attempt(outreach_id, attempt_result, run_date)` | Yes for the four branches (consented/declined/unreachable/deferred); but the unreachable-terminal decrement has the bug in Finding 2, and the state-transition `update_item` calls have the bug in Finding 1 |
| `score_engagement(patient_id, program_id, run_date)` | `score_engagement(patient_id, program_id, run_date, program_lookup)` | Yes (engagement profile build, scoring, decline classification, retention trigger; `program_lookup` is unused per Finding 7) |
| `evaluate_disenrollment(patient_id, program_id, run_date)` | `evaluate_disenrollment(patient_id, program_id, run_date, program_lookup)` | Yes (decision policy, Bedrock rationale with fallback, decision-pending persistence, Kinesis emit) |
| `process_disenrollment_decision(decision_id, human_decision)` | `process_disenrollment_decision(decision_id, human_decision, program_lookup)` | Yes (graduate, disenroll-for-cause, disenroll-incomplete, transition-to-higher-acuity, extend-or-transition; cross-program transition recommend after graduation/deterioration) |
| `recommend_cross_program_transitions(...)` | `recommend_cross_program_transitions(...)` | **Deviates per Finding 4** (uses static map instead of priority-based pseudocode) |
| `post_graduation_observation(run_date)` | `post_graduation_observation(run_date)` | Yes (window-filtered scan, relapse-signal detection, state transition, Kinesis emit) |

Intentional deviations clearly framed:
- Athena query templates in eligibility (pseudocode Step 1) become in-memory filters with comments naming the production replacement.
- SageMaker Batch Transform calls (pseudocode Step 2) become rule-based proxies (`_score_uplift`, `_score_enrollment_likelihood`, `_score_engagement_prediction`).
- Bedrock calls are wrapped in helpers and patched for the offline demo (Finding 9 flags the comment gap).

---

## AWS SDK Accuracy

| API Call | Method | Notes |
|----------|--------|-------|
| DynamoDB GetItem | `table.get_item(Key={...})` | Composite PK on `patient-program-state` (patient_id, program_id), `outreach-state` (outreach_id), etc. Correct. |
| DynamoDB PutItem | `table.put_item(Item=_to_decimal_dict(...))` | Correct. All numeric values flow through `_to_decimal_dict`. |
| DynamoDB UpdateExpression with ADD on List | Multiple sites | **INVALID** per Finding 1. ADD does not support List type. |
| DynamoDB UpdateExpression with ADD on Number | `ADD cm_outreach_recent_30d_count :one` (`dispatch_outreach`); `ADD cm_outreach_recent_30d_count :neg` (Finding 2) | Number-typed ADD is correct in principle. The decrement path has the missing-`:zero` bug per Finding 2. |
| DynamoDB UpdateExpression with reserved word | `UpdateExpression="SET #s = ...", ExpressionAttributeNames={"#s": "state"}` | Correct. `state` is a reserved word; aliasing via `#s` is the right pattern. |
| Bedrock InvokeModel | `bedrock_runtime.invoke_model(modelId=..., body=...)` with `anthropic_version="bedrock-2023-05-31"`, `max_tokens=700`, `temperature=0.0`, `messages=[{"role": "user", "content": prompt}]` | Correct. Model ID `anthropic.claude-3-5-haiku-20241022-v1:0` is current. Setup notes the cross-region inference profile caveat for some regions. |
| Kinesis PutRecord | `kinesis_client.put_record(StreamName, PartitionKey=patient_id, Data=json.dumps(..., default=str).encode("utf-8"))` | Correct. Patient-keyed partitioning preserves ordering per patient. |
| CloudWatch PutMetricData | `cloudwatch_client.put_metric_data(Namespace, MetricData=[...])` with low-cardinality dimensions | Correct shape. Finding 5 flags the present-with-None default trap. |
| Athena GetQueryExecution | `athena_client.get_query_execution(QueryExecutionId)` | Correct (helper unused in offline run but shape is right). |
| SageMaker DescribeTransformJob | `sagemaker_client.describe_transform_job(TransformJobName)` | Correct (helper unused in offline run but shape is right). |

The two SDK-level bugs are both in the DynamoDB UpdateExpression handling (Findings 1 and 2). All other API surfaces are current and correct.

---

## DynamoDB and Data Type Check

- `_to_decimal` correctly uses `Decimal(str(value))` and short-circuits on already-Decimal inputs.
- `_to_decimal_dict` recursively converts nested dicts and lists, with the `not isinstance(v, bool)` guard so booleans don't flow into Decimal.
- `_from_decimal` recursively unwraps Decimals back to floats.
- All `update_item` and `put_item` writes route numerics through `_to_decimal_dict` at the persistence boundary.
- The seeded `cm_outreach_recent_30d_count` and `outreach_recent_30d_count` use `Decimal("0")`; the orchestrator's `int(patient.get("cm_outreach_recent_30d_count", 0))` cast is correct (`int(Decimal("0"))` is `0`).
- The CM-budget decrement in `dispatch_outreach` uses `Decimal("1")` and the `ADD :one` expression. Correct numeric ADD.
- No floats are persisted to DynamoDB.

The Decimal discipline is correct. The bugs are in the UpdateExpression itself (Findings 1 and 2), not in the type handling.

---

## S3 and Credentials Check

- The example uses S3 only via configuration constants (`CM_DATA_LAKE_BUCKET`, `CM_FEATURE_STORE_OFFLINE_BUCKET`, etc.); no actual S3 client calls are made in the executable code path. This is correct for the demo (Athena and SageMaker Batch Transform paths are not exercised offline).
- No leading slashes in any constant.
- No hardcoded credentials. Module-level boto3 clients use the documented environment credential chain.
- The IAM permissions list in Setup matches the API surface used by the code (DynamoDB on the nine named tables, Bedrock on the four named model uses, Kinesis on the cm-engagement-stream, SageMaker on per-program model ARNs, S3 on five named buckets, Athena, Glue, SES, Pinpoint, Connect, CloudWatch, CloudWatch Logs).

Pass.

---

## Comment Quality Assessment

Comments consistently explain the "why":

- The Heads-up at the top names every major production gap before the code starts (no real claims/EHR/lab/pharmacy/discharge feed integration, no propensity-matched difference-in-differences evaluation, no causal-inference-grade response models, no live randomized hold-out cohort, no Connect contact-flow integration, no real consent capture and HIPAA authorization workflow, no actual cohort-aware fairness instrumentation).
- The PHI-logging guidance at the module level: *"Never log a raw (patient_id, program_id, state, uplift_score, priority_components) join along with clinical context; the row implicitly identifies the patient, the suspected diagnosis pattern, and the program's theory of change. The patient-program-state and enrollment-briefings tables are highly inferential PHI."*
- The program-registry framing: *"The program registry is the source of truth for what each program is and who it's for. ... Production needs structured change management with clinical operations, program leadership, and contracts review, with parallel evaluation against the prior registry version when significant changes ship."*
- The causal-inference framing: *"Per-program response (uplift) modeling is the hardest part and the part most teams skip. Production-grade response estimation requires either randomized enrollment in a fraction of slots or careful causal-inference tooling (propensity matching, doubly-robust estimation, instrumental variables) on observational enrollment data. ... The example uses rule-based proxies."*
- The engagement-tracker framing: *"The engagement-and-retention worker is the part that determines whether enrollment actually translates into outcomes."*
- The Decimal-at-the-boundary discipline: *"DynamoDB does not accept Python floats. Going through str avoids binary-precision issues. Wrap floats at the persistence boundary and forget about it. (This is the SDK gotcha that bites every boto3 newcomer; fixed at the boundary, not in business logic.)"*
- The briefing-ID PHI-leakage warning in `_make_briefing_id`: *"Production must replace this with an opaque, non-reversible identifier (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plain-text patient_ids and program_ids embedded in IDs (carried in care-manager queues, EHR inboxes, and engagement events) are PHI leakage."*
- The Bedrock de-identification stance in `_redact_identifiers`: *"Strip patient/provider identifiers from a list of records before sending to an LLM. The LLM doesn't need them, and stripping at the boundary limits any vendor-side logging exposure."*
- The state-machine semantics throughout `record_outreach_attempt` and `score_engagement` are clearly named (transitioned-A-to-B labels, decline-pattern classification rationale).
- The Bedrock model-ID note in Setup: *"Bedrock model IDs change over time. Some regions require cross-region inference profile IDs (prefixed `us.` or `eu.`)."*
- The synthetic-data labeling: *"All sample patients, programs, eligibility records, engagement events, and outcome events in the example are synthetic."*
- The collapse-to-single-file note: *"The example collapses Step Functions, Glue, Athena, and SageMaker Batch Transform into a single Python file for readability. In production these are separate workflow stages with their own error handling, IAM, and DLQs."*

Calibration is appropriate for a mixed audience. The Gap to Production section is unusually thorough (40+ items spanning program-registry curation, causal-inference rigor, multi-source data ingestion, Feature Store integration, Batch Transform output schema, training-job triggers, Glue-not-application-code eligibility, Step Functions DLQ coverage, Bedrock cost/latency, Connect integration, consent workflows, tracking-ID privacy, Decimal discipline, cohort-feature PHI sensitivity, equity floor design, cross-recipe coordination, outreach attempt management, disenrollment governance, cohort fairness review, cold-start handling, data-quality flag propagation, idempotency, mid-program deterioration detection, re-engagement-after-disenrollment, real-time post-discharge enrollment, care-team feedback loop). The breadth tells the reader honestly how much sits between the recipe and a production deployment.

---

## Healthcare-Specific Requirements

- **PHI logging discipline.** Module-level logger comment is explicit. Logger calls in the file mostly stay on the safe side (patient_id appears in some warning paths but clinical context isn't co-logged); cohort_features are scoped on the recommendation log only.
- **Synthetic data labeling.** All sample patient IDs (`pat-002148`, `pat-002149`, `pat-002150`), program IDs, and engagement events are obviously synthetic. The Heads-up section warns explicitly.
- **Eligibility filters as hard constraints.** Step 1's denominator/inclusion/exclusion logic enforces age, condition, continuous-enrollment, discharge-window, A1c-window, multi-condition-count, admission-probability, language-support, and categorical exclusion (hospice, palliative care). Hard constraints, not soft features.
- **Decimal at the DynamoDB boundary.** Consistent. Bool guards prevent boolean-to-Decimal conversion.
- **State-machine canonical-source semantics.** `record_outreach_attempt` correctly distinguishes consented (state → enrolled with consent metadata), declined, unreachable terminal vs pending retry, and deferred outcomes. The state machine is the source of truth.
- **Tracking-ID privacy.** `_make_briefing_id` carries an explicit NOTE about PHI leakage in plaintext composite IDs; `_make_outreach_id` and `_make_decision_id` use UUID-based opaque format. Gap to Production repeats the briefing-ID fix.
- **Bedrock de-identification.** `_redact_identifiers` strips patient/provider identifiers before LLM calls; briefing context uses `age_band` rather than `age`, no patient_id, no name, no address.
- **Cohort-features sensitivity.** Recommendation log carries cohort_features (engagement quartile, language, SDOH cohort, age band) for fairness monitoring; Gap to Production names the SDOH-cohort PHI boundary and the minimum-necessary principle.
- **Customer-managed KMS posture.** Documented in Setup and Gap to Production.
- **Outreach validator.** `_validate_briefing` enforces structural shape and the observed-context invariant; Finding 8 flags the sentinel-condition fragility.
- **Multi-program cross-recipe coordination.** Documented (CM outreach uses a separate budget from 4.4-4.6 routine outreach). The optimistic-increment pattern is consistent with 4.5/4.6; the decrement-on-unreachable path has the bug in Finding 2.
- **Override-suppression semantics.** Disenrollment decisions are persisted with `human_review_pending: true` and require explicit human approval before state changes apply. This is decision support, not autonomous disenrollment, matching the recipe's framing.

Pass on healthcare-specific handling, with Findings 2, 3, and 8 being the operational gaps.

---

## Logical Flow

The file reads top-to-bottom in pedagogical order matching the pseudocode numbering: Setup, Configuration and Constants, Reference Data (synthetic program registry with denominator/inclusion/exclusion/capacity/equity-floor/engagement-profile data), Shared Helpers, Step 1 (eligibility evaluation with state-machine transition), Step 2 (per-program response/likelihood/engagement/fit + priority synthesis), Step 3 (multi-stage capacity-and-equity allocation), Step 4 (briefing generation, outreach dispatch, outreach-attempt processing), Step 5 (engagement scoring with decline-pattern classification and retention trigger), Step 6 (disenrollment evaluation with LLM rationale, decision processing, cross-program-transition recommendation, post-graduation observation), Putting It All Together, Demo Runner, Gap Between This and Production.

Each step opens with a short italic prose paragraph that restates the pseudocode step before the code block, matching the cookbook's established pattern.

The demo runner builds three patients with deliberately different cohort and clinical profiles (Linda Garcia at 72 with HF/DM/CKD/AFib/HTN and recent admission; pat-002149 at 58 with diabetes only, low food security, q1 engagement, Spanish-preferred; pat-002150 at 80 with multi-system complexity and transportation barrier) so a reader can trace eligibility across multiple programs, the multi-stage allocator's stage-1-vs-stage-2-vs-stage-3 routing, and the equity-floor mechanics.

---

## What Is Done Particularly Well

- The multi-stage allocator's stage decomposition (time-sensitive → disease-specific high-fit → complex-care residual → add-ons) is faithful to the pseudocode and respects program semantics. The per-stage greedy-by-priority with capacity, equity floor, single-active-primary, and add-on-cap constraints threads cleanly. A reader extending the orchestrator with a new constraint follows the existing pattern.
- The four-layer validator pattern is uniform across the two LLM use cases (enrollment briefing, disenrollment rationale). Each validator has a fail-safe templated fallback so the dispatch path never produces nothing on validator failure.
- The `_compute_program_fit` heuristic encodes program semantics explicitly per program (TCM fit decays with days-since-discharge, HF fit weakens when many other major problems coexist, complex-care fit grows with condition count). A reader extending this with a new program has the schema to follow.
- The disenrollment policy is decision-supported, not autonomous: every triggering rule produces a `human_review_pending: true` row, and `process_disenrollment_decision` requires an explicit human approval (or override) before state changes apply. The `final_action == decision.recommended_action if human_decision == "approve" else human_decision.actual_action` branch correctly preserves human override.
- The `_DEMO_*` synthetic data dicts (`_DEMO_FRAGMENTATION_FLAGS`, `_DEMO_HISTORY_COUNT`, `_DEMO_ENGAGEMENT_PROFILES`, `_DEMO_FAILED_RETENTION_COUNTS`, `_DEMO_GOALS_MET`, `_DEMO_DETERIORATION`, `_DEMO_RELAPSE_SIGNALS`, `_DEMO_PATIENTS_FOR_RATIONALE`) make the demo's data dependencies explicit. A reader can trace which seed data drives which behavior.
- The Gap to Production section explicitly calls out idempotency and DLQ coverage, naming the operational damage of dropped state-transition events: *"a missed `program_at_risk` event delays retention; a missed `program_enrolled` event leaves the engagement scorer unarmed; a missed disenrollment decision leaves the slot tied up indefinitely."*
- The cross-recipe coordination note (CM outreach budget separate from 4.4-4.6 routine outreach) is explicit, with the rationale that the enrollment conversation is a distinct, infrequent interaction.

---

## Closing Assessment

The teaching content is well-organized and faithful to the main recipe in structure, prose framing, and pedagogical ordering. The six pseudocode steps map onto Python functions with helpers in the right places, the Bedrock + DynamoDB + Kinesis + CloudWatch API call shapes are current except for the two UpdateExpression bugs, the multi-stage allocator with capacity and equity floors is implemented faithfully, and the four-layer validator pattern is uniform across the LLM use cases.

Two ERRORs are the items to fix before this goes to readers. Finding 1 is the chapter-wide `ADD state_history :history_event` bug: ADD only supports Number and Set data types, so all ten state-transition `update_item` calls fail at runtime against a real DynamoDB table. The same bug exists in 4.6 (which the prior reviewer incorrectly endorsed); the fix should propagate. Finding 2 is the `record_outreach_attempt` decrement path that references undefined `:zero` in `ConditionExpression` and explicitly passes `ExpressionAttributeNames=None`; both need to be fixed and the `except Exception: pass` should become a logged warning so failures are visible.

The single WARNING (Finding 3) is the demo runner's print-vs-reality mismatch: phrases like "Simulating outreach result: Linda consents" and "Simulating disenrollment evaluation and human decision" suggest simulations execute, but no DynamoDB tables exist offline, so every state transition silently no-ops. Reframing the prints (or providing a DynamoDB-Local setup) addresses this.

The six NOTEs are smaller items: pseudocode deviation in `recommend_cross_program_transitions`, the present-with-None CloudWatch dimension trap, the TCM fit-vs-inclusion field inconsistency, the unused `program_lookup` parameter in `score_engagement`, the brittle sentinel-condition validator, and the missing `globals()` mock-injection comment.

FAIL verdict per the persona's rule that any ERROR is automatically a FAIL. A re-review pass after the two ERRORs are addressed would be quick.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(ERROR)** All ten `ADD state_history :history_event` (and `ADD state_history :he`) call sites have been replaced with `SET state_history = list_append(if_not_exists(state_history, :empty), :history_event)` patterns. The `:empty` placeholder is defined as `[]` in `ExpressionAttributeValues`. A smoke test (DynamoDB-Local or moto) confirms one path persists state history across two writes. The same fix is propagated to Recipe 4.6's Python example.
2. **(ERROR)** `record_outreach_attempt`'s unreachable-terminal decrement defines `:zero` in `ExpressionAttributeValues`, drops `ExpressionAttributeNames=None`, and replaces `except Exception: pass` with `except Exception as exc: logger.warning(...)`. A smoke test confirms the decrement path no longer raises.
3. **(WARNING)** The demo runner's print messages either acknowledge that simulations are structural-not-behavioral when run offline, or a DynamoDB-Local + Kinesis-Local setup is provided in Setup. The `try/except Exception: pass` patterns inside DynamoDB calls are replaced with `try/except Exception as exc: logger.warning(...)` so failures surface.
4. **(NOTE)** `recommend_cross_program_transitions` either (a) carries a docstring/comment naming the static-map simplification and the deviation from the priority-based pseudocode, or (b) is rewritten to match the pseudocode by reading current `patient-program-state` rows for the patient and computing priority across eligible programs.
5. **(NOTE)** CloudWatch dimension defaults use a `_safe_dim` helper (or equivalent) so present-with-None values map to `"unknown"` rather than `"None"`. Same fix propagated to other emit sites if needed.
6. **(NOTE)** `_compute_program_fit` for TCM either gates on `last_admission_date` (matching inclusion logic) or carries a comment explaining the discharge-date dependency.
7. **(NOTE)** `score_engagement` either uses `program_lookup` to read `at_risk_threshold` from the registry, or removes the unused parameter.
8. **(NOTE)** `_validate_briefing` either uses regex with word boundaries and a synonym map for sentinel conditions, or carries a comment naming the substring-matching simplification.
9. **(NOTE)** The `globals()` mock injection block carries the explanatory comment used in 4.5 and 4.6.
