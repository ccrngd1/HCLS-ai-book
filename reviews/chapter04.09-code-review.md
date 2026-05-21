# Code Review: Recipe 4.9 - Personalized Care Plan Generation

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-21
**Files reviewed:**
- `chapter04.09-personalized-care-plan-generation.md` (main recipe pseudocode)
- `chapter04.09-python-example.md` (Python companion)

**Validation performed:**
- Walked the six pseudocode steps against Python functions one-to-one
- Verified boto3 API call shapes for DynamoDB resource (`get_item`, `put_item`, `update_item`, `scan`), Bedrock Runtime (Anthropic Messages API), Kinesis (`put_record`), CloudWatch (`put_metric_data`), S3, EventBridge
- Traced numeric values flowing into DynamoDB through `_to_decimal` / `_to_decimal_dict` / `_from_decimal`
- Walked the demo runner end-to-end against Linda (the index patient) to verify the demo path
- Traced the four-layer validator logic against the curated mock narrative outputs
- Computed the expected goal weights, retained action set, burden compression, and capacity substitution decisions for the index patient
- Verified opaque-ID discipline, PHI handling at the LLM boundary, eligibility/contraindication filters, customer-managed KMS posture, structured-then-narrative direction

---

## Summary

The Python companion is structurally faithful to the main recipe's six pseudocode steps and the architectural picture (frozen plan-input record, condition-driven goal derivation with goals-of-care alignment and quality-program weighting, multi-condition reconciliation pipeline with interactions/deprescribing/burden compression/capacity substitution/schedule sequencing, structured plan record as system of record, three audience-specific narratives with four-layer validator and templated fallback, activation/feedback/periodic-review loop). The Decimal-at-the-DynamoDB-boundary discipline is consistent (with proper bool guards), the structured-then-narrative direction is enforced at every boundary (the LLM never makes clinical decisions), the opaque-ID pattern is correct (UUID-based, no embedded patient_id), the burden-threshold computation is patient-specific and respects functional/cognitive/social signals, the capacity-substitution logic correctly preserves the original owner role for the audit trail, and the deprescribing-as-action-with-prescriber-owner pattern is the right design.

That said, two WARNINGs need attention before this goes to readers, plus a handful of NOTEs. The first WARNING is that `_check_fact_grounding` builds `valid_action_ids` only from `plan["final_actions"]`, but the clinician-facing prompt explicitly directs the LLM to reference suppressed actions, deprescribing candidates, and capacity-substitution decisions through the `care_team_attention` and `what_changed_since_prior` fields. When the LLM faithfully follows the prompt and mentions `naproxen_for_oa_pain` (suppressed) or `egfr_under_45` (a contraindication code), the validator rejects the output as "ungrounded_id_reference" even though those tokens come from the structured reconciliation record. In the demo run, the curated mock clinician narrative fails validation on both attempts and falls back to the templated path, so the print statement reports `validator_passed=False` for the clinician audience. This contradicts the recipe's claim of an 85-94 percent first-attempt pass rate and teaches a learner that the validator design is correct when it is actually misclassifying valid grounded references. The second WARNING is that `finalize_plan` calls `_cohort_features_from_profile(plan_input_record["patient_features"])`, but `patient_features` is the clinical/numeric feature dict (age, frailty index, chf_severity, bmi, away-from-home cap), not the patient profile. The cohort fields the helper looks up (`preferred_language`, `race_ethnicity_self_report`, `sdoh_cohort`, `age_band`) live on the `patients` profile dict, which is never passed to `finalize_plan`. As a result, every CloudWatch metric emitted from the plan-finalization path carries `language=en, race_ethnicity_self_report=unknown, sdoh_cohort=unknown, age_band=unknown` regardless of the actual patient cohort, silently breaking the cohort fairness instrumentation that the recipe describes as "non-negotiable."

Beyond those, six NOTEs cover the demo runner's print-vs-reality mismatch (same as 4.6 / 4.7 / 4.8), two Scan paths where Query suffices (`_update_action_status` and `run_periodic_plan_review`), the missing `globals()` mock-injection comment (chapter-wide pattern), the absence of any reading-level or language enforcement in the patient validator despite the prompt promising both, the bare `try/except: pass` patterns inside several Kinesis emits and DynamoDB writes, and the `_compute_plan_quality_metrics` stub returning hard-coded values without an in-function comment naming it as such.

---

## Verdict: PASS

No ERRORs. Two WARNINGs (under the FAIL threshold of more than three). Six NOTEs.

The two WARNINGs are localized, well-scoped, and do not block the demo from running to completion (it gracefully falls back to templated narrative for the clinician audience and emits cohort-blind metrics for the dashboards). They should be addressed before the recipe ships, because they teach incorrect design patterns to a reader who copies the example into a real deployment.

---

## Findings

### Finding 1: `_check_fact_grounding` Rejects Valid References to Suppressed Actions, Deprescribing Candidates, and Contraindication Codes; Curated Mock Clinician Narrative Always Falls Back to Templated

- **Severity:** WARNING
- **File:** `chapter04.09-python-example.md`
- **Locations:** `_check_fact_grounding` (the `valid_action_ids` / `valid_goal_ids` set construction), the clinician prompt in `_clinician_prompt`, the context construction in `generate_narratives`, the `_extract_attention_items` helper that feeds the prompt
- **Description:**

  The clinician prompt directs the LLM to surface specific structured-plan elements that are not in `final_actions`:

  ```
  Hard rules:
  ...
  4. Surface the to-be-assigned items, suppressed actions, and
     deprescribing candidates in the care_team_attention block.
  ```

  And the prompt context built by `generate_narratives` includes:

  ```python
  clinician_context = {
      "audience":           "clinician",
      "plan_record":        plan_record,
      "what_changed":       _compute_what_changed(plan_record),
      "care_team_attention": _extract_attention_items(plan_record),
  }
  ```

  Where `_extract_attention_items` returns strings like `"Suppressed: naproxen_for_oa_pain - contraindicated: chf_severe, egfr_under_45"` and `_compute_what_changed` returns `"Suppressed naproxen_for_oa_pain (contraindicated: chf_severe, egfr_under_45)"`. The LLM is told these are valid items and must reference them.

  The fact-grounding validator then runs:

  ```python
  def _check_fact_grounding(parsed: dict, context: dict,
                              issues: list) -> bool:
      plan = context["plan_record"]
      valid_action_ids = {a["action_id"] for a in plan["final_actions"]}
      valid_goal_ids = {g["goal_id"] for g in plan["goal_set"]}
      ...
      for token in suspicious_tokens:
          if token in valid_action_ids or token in valid_goal_ids:
              continue
          if token.count("_") >= 2 and not _is_safe_keyword(token):
              issues.append(f"ungrounded_id_reference: {token}")
              return False
  ```

  `valid_action_ids` only includes actions in `final_actions`. Suppressed actions live in `plan["reconciliation_record"]["suppressed_actions"]`. Deprescribing candidates do end up in `final_actions` (they are added to `retained` in `_generate_deprescribing_actions`), so `deprescribe_ppi_long_term` passes; but `naproxen_for_oa_pain` does not, and `egfr_under_45` is a contraindication code that is not an action_id at all.

  Tracing the demo:

  1. `re.findall(r"\b[a-z][a-z0-9_]{8,40}\b", text)` over the flattened mock clinician narrative includes `chf_avoid_readmission` (valid goal_id, passes), `naproxen_for_oa_pain` (3 underscores, not in valid sets, not in `_is_safe_keyword`), `egfr_under_45` (2 underscores, same problem), `cardiac_rehab_enrollment` (valid action_id, passes), `deprescribe_ppi_long_term` (valid action_id, passes).
  2. `naproxen_for_oa_pain` is hit first in iteration order; the validator returns False with `issues = ["ungrounded_id_reference: naproxen_for_oa_pain"]`.
  3. `_generate_one_narrative` retries with `strict_mode=True`. The mock returns the same JSON. The validator fails identically.
  4. `_generate_one_narrative` falls through to `_templated_narrative_fallback`. The narrative record's `validator_status` stays False.
  5. The demo's print line shows `validator_passed=False; layers_passed=['schema']` for the clinician audience.

  This contradicts what the recipe text claims:

  > | Validator first-attempt pass rate (patient narrative) | n/a | 85-94% |

  And the prose in the main recipe explicitly frames the validator as catching "the common failure modes": ungrounded clinical claims, prohibited recommendation language, missing required content. Rejecting a faithful reference to `naproxen_for_oa_pain` (which the LLM was instructed to mention in care_team_attention) is a false positive, not a caught failure.

  Two consequences:

  1. **The demo's curated mock narrative cannot pass validation.** A reader who runs the example sees the templated fallback every time and concludes that either the LLM is producing bad output or the validator design is intentionally strict. Neither is correct.
  2. **The validator design is broken on its own terms.** Production traffic where the LLM correctly follows the prompt would face the same false-positive rate. A team that ships this validator unmodified will see Bedrock spend on regeneration loops that always fail, with the templated fallback rate driven by the validator design, not by LLM quality.

- **Suggested fix:** Expand `valid_action_ids` and `valid_goal_ids` to include every structured-plan element the prompt instructs the LLM to reference. Sketch:

  ```python
  def _check_fact_grounding(parsed: dict, context: dict,
                              issues: list) -> bool:
      plan = context["plan_record"]
      rec = plan.get("reconciliation_record", {})

      # Every action_id that appears anywhere in the structured plan,
      # whether retained, suppressed, deprescribing-added, or
      # to-be-assigned. The LLM is instructed to reference suppressed
      # actions and deprescribing candidates in the clinician
      # narrative; those references are grounded.
      valid_action_ids = (
          {a["action_id"] for a in plan.get("final_actions", [])}
          | {a["action_id"] for a in plan.get("to_be_assigned", [])}
          | {a["action_id"] for a in rec.get("suppressed_actions", [])}
          | {a["action_id"] for a in rec.get("deprescribing_added", [])}
      )

      # Every goal_id, including goals removed by goals-of-care.
      valid_goal_ids = {g["goal_id"] for g in plan.get("goal_set", [])}

      # Contraindication codes and clinical-state tokens the
      # reconciliation engine surfaces (e.g., chf_severe, egfr_under_45).
      # These are not action_ids; treat them as a separate allowlist
      # populated from the clinical-content catalog. The demo's small
      # set is enumerated below.
      valid_clinical_codes = {
          "chf_severe", "egfr_under_45", "cognitive_impairment_moderate",
          "geriatric_frail", "palliative_focused",
      }
      ...
      for token in suspicious_tokens:
          if (token in valid_action_ids
              or token in valid_goal_ids
              or token in valid_clinical_codes):
              continue
          if token.count("_") >= 2 and not _is_safe_keyword(token):
              issues.append(f"ungrounded_id_reference: {token}")
              return False
      return True
  ```

  Production should take this further: the `valid_clinical_codes` set is itself a clinical-content artifact that the catalog maintains alongside the goal and action templates. A real fact-grounding layer uses NER and structured-claim matching against the plan record rather than the substring heuristic the demo runs; the recipe text already names this as a Gap to Production. The minimum demo-correctness fix is to include the four sources above so the curated mock narrative passes validation as written, and the prompt-and-validator contract is internally consistent.

  Verify the fix by re-running the demo and confirming `validator_passed=True` for all three audiences. If `validator_passed=False` for any audience, either the prompt is asking for content the validator does not allow (prompt bug) or the validator is rejecting allowed content (validator bug); either gap needs to be closed before the recipe ships.

---

### Finding 2: `_cohort_features_from_profile` Called With `patient_features` (Clinical Dict) Instead of Patient Profile; Cohort Metric Dimensions Are Always Defaults

- **Severity:** WARNING
- **File:** `chapter04.09-python-example.md`
- **Locations:** `finalize_plan` (the `_emit_metric` block at the bottom of the function), `_cohort_features_from_profile` (the helper)
- **Description:**

  `_cohort_features_from_profile` is documented as pulling cohort attributes off the patient profile:

  ```python
  def _cohort_features_from_profile(patient: dict) -> dict:
      """Pull cohort features for fairness instrumentation from the profile."""
      return {
          "language":                 patient.get("preferred_language", "en"),
          "race_ethnicity_self_report": patient.get(
              "race_ethnicity_self_report", "unknown"),
          "sdoh_cohort":              patient.get("sdoh_cohort", "unknown"),
          "age_band":                 patient.get("age_band", "unknown"),
      }
  ```

  In the demo, the `patients` profile dict for Linda contains exactly those fields:

  ```python
  linda = {
      "patient_id":              "pat-007842",
      "age":                     67,
      "age_band":                "65-74",
      "preferred_language":      "en",
      "race_ethnicity_self_report": "non_hispanic_white",
      "sdoh_cohort":             "transportation_barrier",
      ...
  }
  ```

  But `finalize_plan` calls the helper with the wrong dict:

  ```python
  cohort = _cohort_features_from_profile(
      plan_input_record.get("patient_features", {}))
  _emit_metric(
      "plan_finalized", value=1,
      dimensions={
          "language":    cohort.get("language"),
          "sdoh_cohort": cohort.get("sdoh_cohort"),
          "age_band":    cohort.get("age_band"),
          "action_count_band": _band_int(len(final_actions),
                                            [5, 10, 15]),
      },
  )
  ```

  `plan_input_record["patient_features"]` is the clinical/numeric feature dict populated by the demo runner from `_DEMO_FEATURE_STORE[patient_id]`:

  ```python
  _DEMO_FEATURE_STORE[patient_id] = {
      "age":                          67,
      "frailty_index":                0.30,
      "chf_severity":                 "severe",
      "bmi":                          29.0,
      "away_from_home_per_week_cap":  3,
  }
  ```

  None of `preferred_language`, `race_ethnicity_self_report`, `sdoh_cohort`, or `age_band` is present, so every `patient.get(...)` call returns the default. The CloudWatch dimensions emitted from plan finalization will always be:

  ```
  language=en
  sdoh_cohort=unknown
  age_band=unknown
  ```

  Regardless of whether the patient is Linda (English, transportation_barrier, 65-74), a Spanish-preferred patient with food-security barriers (40-49), or any other cohort. Cohort fairness instrumentation, which the recipe describes as "non-negotiable," is silently broken.

  Two consequences:

  1. **The fairness dashboard is cohort-blind.** Plan-ambition parity, plan-complexity parity, action-assignment parity (the metrics the recipe says must be monitored across cohorts) cannot be sliced by cohort because the dimension values are constants. A QuickSight dashboard built on this data shows "all-cohort" averages with the appearance of cohort-stratification.
  2. **The bug is silent.** No exception, no warning, no metric-publish failure. The metric publishes successfully with bad dimension values. Detection requires a human noticing that one cohort bucket holds 100 percent of the volume.

- **Suggested fix:** Pass the patient profile into `finalize_plan` and use it for the cohort lookup. Either as a separate parameter, as a field on the plan-input record, or by inlining the cohort fields into `patient_features` at aggregation time. Sketch (parameter approach):

  ```python
  def finalize_plan(goal_set: list,
                      retained_actions: list,
                      reconciliation_record: dict,
                      plan_input_record: dict,
                      patient_profile: dict) -> dict:
      ...
      cohort = _cohort_features_from_profile(patient_profile)
      _emit_metric(
          "plan_finalized", value=1,
          dimensions={
              "language":    cohort.get("language"),
              ...
          },
      )
  ```

  And update the runner to pass `patients[patient_id]` through. Alternative (plan-input-record approach): add a `patient_profile` field to the plan-input record during `aggregate_plan_inputs` (already pulled from a synthetic side dict in the demo, would be from the patient-profile DynamoDB table in production), then read from there in `finalize_plan`.

  As a structural fix, the helper could be defensive against the wrong dict shape:

  ```python
  def _cohort_features_from_profile(patient: dict) -> dict:
      """..."""
      if not any(k in patient for k in (
          "preferred_language", "race_ethnicity_self_report",
          "sdoh_cohort", "age_band",
      )):
          logger.warning(
              "_cohort_features_from_profile called with dict "
              "lacking any cohort attribute; cohort metrics will "
              "be defaults. Caller is likely passing the wrong "
              "dict (clinical features instead of patient profile)."
          )
      return {...}
  ```

  This makes the silent failure noisy and saves the next person from chasing the same bug.

---

### Finding 3: Demo Runner's Print Statements Imply Operations Persisted When DynamoDB Tables Don't Exist

- **Severity:** NOTE
- **File:** `chapter04.09-python-example.md`
- **Location:** Demo runner (`if __name__ == "__main__":` block) and `run_full_demo_cycle`
- **Description:**

  Same class of issue flagged in 4.6, 4.7, and 4.8 reviews. The demo runs against unprovisioned DynamoDB tables and S3 buckets; every persistence call is wrapped in `try/except Exception as exc: logger.warning(...)` (good discipline, better than 4.8 which had four unwrapped get_items), so the demo runs to completion. But the print statements imply that the underlying state transitions actually happen:

  ```
  Step 1: aggregate plan inputs...
    Plan input id: input-...; conditions: 5; meds: 8
  Step 2: derive goal set...
    Goals: 6 total; 6 retained after goals-of-care alignment
  Step 3: assemble and reconcile actions...
    Actions retained: ...; suppressed: 1; deprescribing added: 1; ...
  Step 4: finalize plan record...
    Plan id: plan-...; version: 1; final actions: ...; ...
  Step 5: generate narratives...
    Narrative audience=clinician: validator_passed=False; layers_passed=['schema']
    Narrative audience=patient: validator_passed=True; layers_passed=[...]
    Narrative audience=care_team_internal: validator_passed=True; layers_passed=[...]
  Step 6: activate plan...
    Activation id: act-...
  Step 6: record action-completion feedback...
    Feedback id: fb-...; kind: action_completed
  Step 6: periodic-review sweep...
    Surveillance alerts: 0
  ```

  In practice against unprovisioned tables:

  - Steps 1-4 compute correctly (the state lives in Python dicts; persistence fails silently with warnings).
  - Step 5 narrative persistence fails silently. The narratives never reach the `plan-narratives` table.
  - Step 6 activation: `_safe_get_item` returns `{}` because the plan-records table doesn't exist. The function logs a warning and returns `{}`. The print line shows `Activation id: None` because `activation.get("activation_id")` returns None, but the print is `f"  Activation id: {activation.get('activation_id')}"` which renders `Activation id: None`. Closer to honest, but still implies the activation flow ran.
  - Step 6 feedback: `feedback_table.put_item` fails silently. `_update_action_status`'s scan fails silently (the table doesn't exist). `eventbridge_client.put_events` may or may not fail depending on bus existence. The print shows the synthesized feedback_id from `_make_feedback_id()` even though nothing persisted.
  - Step 6 periodic review: `plans_table.scan()` fails silently. Zero alerts is a vacuous truth.

  None of the Step 4-6 prints reflect what actually happened in storage.

- **Suggested fix:** Same suggestion as 4.7 / 4.8 reviews:

  1. **Lighter fix:** Add a clear "running offline against unprovisioned tables" disclaimer at the top of the demo runner, and reframe the prints to describe what each step would do in a provisioned environment rather than what executes in the offline run. The pattern from 4.7 / 4.8 reviews applies here too.
  2. **Heavier fix:** Provide a DynamoDB-Local + Kinesis-Local docker-compose snippet in Setup so the demo can be exercised end-to-end. Recipes 4.7 and 4.8 deferred this; consistency suggests deferring here too unless the project plans to retrofit it across the chapter.

  Adjacent cleanup: the `try/except Exception: pass` patterns around several Kinesis emits should become `try/except Exception as exc: logger.warning(...)` so a developer with `logger.setLevel(logging.WARNING)` sees the failures. The 4.7 review made the same recommendation.

---

### Finding 4: Two Scan Paths Where Query Would Suffice

- **Severity:** NOTE
- **File:** `chapter04.09-python-example.md`
- **Locations:**
  - `_update_action_status` (Scan over `plan-action-records` to find a row by `(plan_id, action_id)`)
  - `run_periodic_plan_review` (Scan over `plan-records` to find active plans whose `review_due_at` is in the past)
- **Description:**

  Same pattern flagged in 4.6 Finding 2 and 4.8 Finding 6.

  1. **`_update_action_status`** scans the entire `plan-action-records` table to find the row matching `(plan_id, action_id)`. The table can grow to millions of rows over time as actions accumulate from every plan ever generated. The proper pattern is a `(plan_id, action_id)` GSI Query, or making `(plan_id, action_id)` the composite key on the table directly so a `get_item` works. The function comment acknowledges the problem ("Production: use the (plan_id, action_id) GSI; the demo scans because the example does not provision indexes") but the demo's pragmatic shortcut becomes the reference pattern a reader carries forward.

  2. **`run_periodic_plan_review`** scans the entire `plan-records` table looking for active plans whose `review_due_at` is in the past. At 50,000 active plans (the recipe's stated cohort size), with prior plan versions accumulating, the Scan dominates cost and latency for the periodic-review run. The proper pattern is a `(plan_status, review_due_at)` GSI Query with `KeyConditionExpression="plan_status = :s AND review_due_at <= :d"`. Again, the function comment names the production fix.

  Plus there's no pagination handling on either Scan (1MB limit), so production-scale runs silently truncate.

- **Suggested fix:** For `_update_action_status`, use a `(plan_id, action_id)` GSI Query:

  ```python
  from boto3.dynamodb.conditions import Key

  try:
      response = par_table.query(
          IndexName="plan-id-action-id-index",
          KeyConditionExpression=(
              Key("plan_id").eq(plan_id)
              & Key("action_id").eq(action_id)
          ),
      )
      items = response.get("Items", [])
      if items:
          item = _from_decimal(items[0])
          par_table.update_item(
              Key={"plan_action_record_id":
                    item["plan_action_record_id"]},
              ...
          )
  except Exception as exc:
      logger.warning("Action-status update failed: %s", exc)
  ```

  For `run_periodic_plan_review`, use a `(plan_status, review_due_at)` GSI Query and document the GSI in a comment. Pagination via `LastEvaluatedKey` is the standard pattern; the example can call it out without fully implementing it ("production: page through `LastEvaluatedKey` until exhausted").

  Document both GSIs in the `Setup` IAM permissions list.

---

### Finding 5: `globals()` Mock Injection Without Explanatory Comment (Same Pattern as 4.5/4.6/4.7/4.8)

- **Severity:** NOTE
- **File:** `chapter04.09-python-example.md`
- **Location:** Demo runner (`if __name__ == "__main__":` block)
- **Description:**

  ```python
  globals()["_bedrock_invoke_narrative"] = _mock_invoke
  ```

  The pattern works (same-module name resolution against module globals at call time), but isn't explained. Same finding as 4.6 Finding 7, 4.7 Finding 9, and 4.8 Finding 8. A learner who tries to apply the pattern across module boundaries discovers it doesn't work the same way.

- **Suggested fix:** Add the comment used in (or recommended for) prior reviews:

  ```python
  # Patch the module-level Bedrock helper for the offline demo.
  # This works because the calling functions resolve the
  # _bedrock_invoke_narrative name against the module global
  # namespace at call time, and globals() in __main__ returns this
  # module's dict. Production never bypasses this; the real Bedrock
  # calls run.
  globals()["_bedrock_invoke_narrative"] = _mock_invoke
  ```

---

### Finding 6: Patient Validator Promises Reading-Level and Language Enforcement But Checks Neither

- **Severity:** NOTE
- **File:** `chapter04.09-python-example.md`
- **Locations:** `_patient_prompt`, `_validate_narrative` (the patient branch in `_check_required_content` and `_check_prohibited_language`)
- **Description:**

  The patient prompt makes two promises the validator does not enforce:

  ```
  Hard rules:
  1. Match the reading-level target ({reading_level}). Use short
     sentences. Use everyday words instead of clinical jargon.
  2. Output language: {language}. If language != "en", produce the
     narrative in that language.
  ```

  And the recipe text explicitly lists reading-level enforcement as a validator concern:

  > Reading-level matching applies the same pattern as Recipe 4.2.

  The actual validator runs:

  - **Layer 1 (schema):** required fields present, no oversize text. Does not check reading level or language.
  - **Layer 2 (fact grounding):** id-shaped tokens against valid sets. Does not check reading level or language.
  - **Layer 3 (prohibited language):** patterns like `\bguaranteed\b`, `\bcure[ds]?\b`, `\bcontraindication\b`, `\biatrogenic\b`. The jargon list is a thin proxy for reading-level scoring; it is not a reading-level metric.
  - **Layer 4 (required content):** `questions` field length >= 20, `contact.phone` present, audience-specific shapes. Does not check reading level or language.

  No Flesch-Kincaid score, no syllable count, no word-frequency check, no language-detection (e.g., comparing the configured language against detected language). A patient narrative output in English when the patient prefers Spanish would pass validation cleanly. A patient narrative scoring at grade 12 reading level when the target is grade 6 would also pass.

  The Expected Results section in the main recipe even reports a measured reading-level value:

  ```json
  "reading_level_target": "grade_6",
  "reading_level_measured": "grade_6.2"
  ```

  But the Python validator never measures reading level. The Expected Results JSON implies a measurement that does not happen.

- **Suggested fix:** Either (a) add a reading-level scoring layer to `_check_required_content` for the patient audience, using a Python library like `textstat` (Flesch-Kincaid grade level) or a hand-rolled syllable counter, comparing the score against `context["reading_level_target"]`; (b) add a basic language detection check (compare the script of the headline / this_week strings against the configured language); or (c) acknowledge the gap explicitly in a comment above the validator and in the Gap to Production section, noting that production must add reading-level scoring and language enforcement and that the Expected Results' `reading_level_measured` field is an aspirational illustration.

  The lightest fix is (c) plus a TODO; the highest-fidelity fix is (a) with `textstat` listed in Setup. Either should land before the recipe ships, because a reader looking at the Expected Results JSON and the validator code today is given two contradictory descriptions of what the system measures.

---

### Finding 7: Bare `try/except: pass` Patterns Hide Persistence Failures From Local Development

- **Severity:** NOTE
- **File:** `chapter04.09-python-example.md`
- **Locations:** five Kinesis `put_record` blocks (in `aggregate_plan_inputs`, `derive_goal_set`, `assemble_and_reconcile_actions`, `finalize_plan`, `activate_plan`, `record_feedback`) and `eventbridge_client.put_events` in `run_periodic_plan_review`'s loop
- **Description:**

  Every Kinesis emit follows this shape:

  ```python
  try:
      kinesis_client.put_record(
          StreamName=CP_EVENTS_STREAM_NAME,
          PartitionKey=plan_input_record["patient_id"],
          Data=json.dumps({...}, default=str).encode("utf-8"),
      )
  except Exception:
      pass
  ```

  The `try/except: pass` swallows the failure silently with no log entry. A developer running the demo locally with `logger.setLevel(logging.WARNING)` sees no indication that the Kinesis stream doesn't exist; in production, a transient Kinesis throttling event would also be invisible. The DynamoDB and S3 write paths in this same file use the better pattern (`logger.warning`); the inconsistency is a hazard.

  Same pattern flagged in 4.7 Finding 6 and 4.8 Finding 5.

- **Suggested fix:** Replace each `except Exception: pass` with the file's existing logging pattern:

  ```python
  except Exception as exc:
      logger.warning(
          "Kinesis put_record for event %s failed: %s",
          event_type, exc,
      )
  ```

  Apply across all six call sites for consistency.

---

### Finding 8: `_compute_plan_quality_metrics` Stub Returns Hard-Coded Values; No In-Function Comment Naming It

- **Severity:** NOTE
- **File:** `chapter04.09-python-example.md`
- **Location:** `_compute_plan_quality_metrics`
- **Description:**

  ```python
  def _compute_plan_quality_metrics(plans_table, run_date: str) -> dict:
      """
      Stub. Production: cohort-stratified plan-ambition parity, plan-
      complexity parity, action-assignment parity, and outcome-
      trajectory parity. Demo: a single synthetic axis.
      """
      return {
          "plan_ambition_by_language": {
              "language_en_avg_action_count": 9.4,
              "language_es_avg_action_count": 7.1,
              "disparity":                    0.24,   # below threshold in this demo
          },
      }
  ```

  The function signature accepts `plans_table` and `run_date` but uses neither. The hard-coded `disparity: 0.24` sits one-hundredth below the `COHORT_DISPARITY_ALERT_THRESHOLD = 0.25`, so the demo never fires an alert. A reader skimming the demo runner sees `Surveillance alerts: 0` and concludes the system found no fairness issues; a more curious reader who tweaks the threshold to 0.20 to see what an alert looks like changes the constant rather than realizing the underlying metric is fabricated.

  The docstring does say "Stub" but a learner glancing at this without reading the docstring takes the values at face value. The pattern looks like real code (it returns a structured dict with realistic-looking metric names).

- **Suggested fix:** Either (a) make the function name self-explanatory (`_compute_plan_quality_metrics_stub` or `_demo_plan_quality_metrics`), (b) add an explicit warning at the top of the function body that lights up in logs:

  ```python
  def _compute_plan_quality_metrics(plans_table, run_date: str) -> dict:
      """..."""
      logger.warning(
          "_compute_plan_quality_metrics is a demo stub returning "
          "hard-coded values. Production replaces this with cohort-"
          "stratified analytics over the plans and feedback tables."
      )
      return {...}
  ```

  Or (c) implement a minimal real computation that scans the recent plans and counts actions per cohort, even if naive. Option (b) is the lowest-effort fix that prevents a learner from copying the stub into production thinking it's a real implementation.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Function | Consistent? |
|----------------|-----------------|-------------|
| `aggregate_plan_inputs(patient_id, request_context)` | `aggregate_plan_inputs(patient_id, request_context)` | Yes (clinical state via FHIR stub, patient features via Feature Store stub, upstream signals from Recipes 4.1-4.8 via `_try_fetch_upstream`, goals-of-care, SDOH, functional status, family caregivers, prior plan; immutable persist to DynamoDB + S3 archive). |
| `derive_goal_set(plan_input_record)` | `derive_goal_set(plan_input_record, goal_templates)` | Yes (condition match with cohort overrides, goals-of-care alignment with retain/remove/reweight, quality-program weighting, patient-stated-preference goal addition, deduplication, ranking). The `stay_at_home` goal addition in Step 2D after the goals-of-care alignment loop is correct (it would be circular to apply goc adjustment to a goal that IS the goc preference). |
| `assemble_and_reconcile_actions(goal_set, plan_input_record)` | `assemble_and_reconcile_actions(goal_set, plan_input_record, action_templates)` | Yes (per-goal candidate generation with cohort overrides, contraindication suppression with audit trail, deprescribing candidate generation, burden estimation with patient-specific threshold, prioritization compression, capacity reconciliation with substitution and deferral, schedule reconciliation). The `_DEMO_CAPACITY` snapshot makes capacity-substitution exercise correctly for Linda. |
| `finalize_plan(goal_set, retained_actions, reconciliation_record, plan_input_record)` | `finalize_plan(goal_set, retained_actions, reconciliation_record, plan_input_record)` | Yes for the structural pieces (horizon bucketing, owner-and-fallback verification with to-be-assigned surfacing, plan-record assembly with provenance and plan_version). **Cohort metric dimension bug per Finding 2.** The `ConditionExpression="attribute_not_exists(plan_id)"` idempotency guard is a nice touch the pseudocode does not require but production benefits from. |
| `generate_narratives(plan_record)` | `generate_narratives(plan_record, patients)` | Yes for the audience-specific contexts and the regeneration-then-fallback flow. The four-layer validator structure matches the pseudocode (schema, fact grounding, prohibited language, required content). **Validator fact-grounding rejects valid references per Finding 1.** **Reading-level and language enforcement are claimed but not implemented per Finding 6.** |
| `activate_plan(plan_id, activation_payload)` | `activate_plan(plan_id, activation_payload)` | Yes (identity-boundary check on `approved_action_ids` against `final_actions`, per-action operational dispatch via `_dispatch_action_to_operational_system`, plan-action-record persistence, plan-status update). The approved-action subset check correctly drops invalid IDs and logs them. |
| `record_feedback(plan_id, feedback_payload)` | `record_feedback(plan_id, feedback_payload)` | Yes for feedback persistence, action-status update, revision-trigger evaluation, EventBridge emission. The Scan in `_update_action_status` is Finding 4. |
| `run_periodic_plan_review(run_date)` | `run_periodic_plan_review(run_date)` | Yes for the active-plan filtering and revision-trigger emission, plus the cohort-fairness alert path. The Scan in the active-plan filter is Finding 4; the hard-coded stub in `_compute_plan_quality_metrics` is Finding 8. |

Intentional deviations clearly framed:

- The pseudocode's `HealthLake.GetPatientBundle(...)` becomes `_normalize_clinical_state(_DEMO_HEALTHLAKE_BUNDLES.get(patient_id, {}))` so the demo runs offline. Documented in the function comment.
- The pseudocode's `SageMaker.FeatureStore.GetRecord(...)` becomes `_DEMO_FEATURE_STORE.get(patient_id, {})`. Documented.
- The pseudocode's `try_fetch("recipe-4.1", ...)` etc. become `_try_fetch_upstream(...)` against module-level dicts. The pattern of returning defaults on missing signals (so a plan can be generated without all upstream signals available) matches the recipe text's framing.
- The pseudocode's `Bedrock.InvokeModel(...)` is wrapped in `_bedrock_invoke_narrative` and monkey-patched by the demo runner via `globals()` per Finding 5.
- The pseudocode's `validate_narrative(...)` four layers map to `_check_schema`, `_check_fact_grounding`, `_check_prohibited_language`, `_check_required_content`. Each layer returns a single boolean; the fact-grounding layer's substring heuristic is acknowledged in the comment.

---

## AWS SDK Accuracy

| API Call | Method | Notes |
|----------|--------|-------|
| DynamoDB GetItem | `_safe_get_item(table, {"plan_id": plan_id})` | Correct. The `_safe_get_item` helper wraps `get_item` in try/except, returning `{}` on failure. Used in `activate_plan`. |
| DynamoDB PutItem | `table.put_item(Item=_to_decimal_dict(...))` | Correct. All numeric values flow through `_to_decimal_dict`; bool guards prevent `Decimal(True)`. |
| DynamoDB PutItem with idempotency | `plans_table.put_item(Item=..., ConditionExpression="attribute_not_exists(plan_id)")` | Correct. The idempotency guard means a Step Functions retry that re-invokes `finalize_plan` with the same `plan_id` is a no-op rather than a duplicate (when production seeds `plan_id` deterministically). |
| DynamoDB UpdateItem | `plans_table.update_item(Key, UpdateExpression="SET ...", ExpressionAttributeValues=...)` | Correct shapes. Two call sites (in `activate_plan` and `_update_action_status`) use SET-only expressions; no ADD on List attributes (the 4.7 Finding 1 issue is not present here). |
| DynamoDB UpdateItem with reserved word | `UpdateExpression="SET #s = :s, last_feedback_at = :t", ExpressionAttributeNames={"#s": "status"}` | Correct in `_update_action_status`. `status` is a reserved word; aliasing via `#s` is the right pattern. |
| DynamoDB Scan | `par_table.scan()` and `plans_table.scan()` | Functional but the right call is Query in two places per Finding 4. No pagination handling. |
| Bedrock InvokeModel | `bedrock_runtime.invoke_model(modelId=..., body=...)` with `anthropic_version="bedrock-2023-05-31"`, `max_tokens=2000`, `temperature=0.0`, `messages=[{"role": "user", "content": prompt}]` | Correct. Model IDs `anthropic.claude-3-5-sonnet-20241022-v2:0` and `anthropic.claude-3-5-haiku-20241022-v1:0` are current; Setup notes the cross-region inference profile caveat. |
| Bedrock response parsing | `payload["content"][0]["text"]` and `re.search(r"\{.*\}", completion, re.DOTALL)` | Correct for Anthropic Messages API on Bedrock. Greedy regex match of the outer JSON object handles Bedrock's tendency to wrap completions in prose. |
| Kinesis PutRecord | `kinesis_client.put_record(StreamName, PartitionKey=..., Data=json.dumps(..., default=str).encode("utf-8"))` | Correct. PartitionKey is `patient_id` for patient-scoped events; choice is reasonable. The bare `try/except: pass` pattern is Finding 7. |
| EventBridge PutEvents | `eventbridge_client.put_events(Entries=[{Source, DetailType, EventBusName, Detail}])` | Correct shape. `Detail` is JSON-serialized; bus name is configured. |
| CloudWatch PutMetricData | `cloudwatch_client.put_metric_data(Namespace, MetricData=[...])` with low-cardinality dimensions | Correct shape. The `_emit_metric` helper filters None-valued dimensions, which avoids the present-with-None trap flagged in 4.5/4.6/4.7/4.8 reviews (positive note). The cohort-dimension-source bug is Finding 2, separate from the helper itself. |
| S3 PutObject | `s3_client.put_object(Bucket, Key, Body)` | Correct. Bucket constants do not include leading slashes or `s3://` schemes; Body is bytes-encoded. Keys use forward slashes (`inputs/`, `plans/`) without leading slash. |

The SDK-level concerns are: Finding 4 (Scan-where-Query-suffices and no pagination), Finding 7 (bare except). All other API surfaces are current and correct.

---

## DynamoDB and Data Type Check

- `_to_decimal` correctly uses `Decimal(str(value))` and short-circuits on already-Decimal inputs.
- `_to_decimal_dict` recursively converts nested dicts and lists, with the `not isinstance(v, bool)` guard so booleans don't flow into Decimal. Lists are walked element-by-element with the same guards.
- `_from_decimal` recursively unwraps Decimals to floats and traverses dict and list containers.
- All `update_item` and `put_item` writes route numerics through `_to_decimal_dict` at the persistence boundary.
- Numeric values (priority weights like `9.5`, burden scores like `1.5`, `2.5`, `4.0`, the `0.30` frailty index, the `38` ejection fraction, the `8.4` A1c, the `39` eGFR, the `1.10` and `1.20` quality program weight multipliers) all flow through `_to_decimal_dict` correctly.
- The `removed_by_goals_of_care` boolean and similar bool-typed flags are preserved as Python bool (the bool guard prevents `Decimal(True)`).
- No floats are persisted to DynamoDB.

The Decimal discipline is correct. No type-handling bugs.

---

## S3 and Credentials Check

- The example uses S3 in `aggregate_plan_inputs` (cohort/input archive) and `finalize_plan` (plan archive). Both are wrapped in `try/except`.
- No leading slashes in the bucket name constants or the S3 key paths (`inputs/{plan_input_id}.json`, `plans/{plan_id}.json`).
- No hardcoded credentials. Module-level boto3 clients use the documented environment credential chain.
- The IAM permissions list in Setup matches the API surface used by the code: DynamoDB on the eight named tables; S3 on the cp-archives bucket; Bedrock on the named foundation-model ARNs; Kinesis on the cp-events stream; EventBridge on the cp-revision-bus; HealthLake (read-only); SageMaker Feature Store; Pinpoint; CloudWatch; Logs.

Pass.

---

## Comment Quality Assessment

Comments consistently explain the "why":

- The Heads-up at the top names every major production gap before the code starts (no real EHR/claims/lab/pharmacy/registry feed integration, no real upstream-recipe signal aggregation, no clinically curated goal-template or action-template library, no real interaction database integration, no validated burden-scoring model, no real capacity-and-schedule reconciliation against staffing systems, no SMART on FHIR plan-review surface, no patient portal integration, no real activation dispatcher, no FHIR `CarePlan`-with-linked-resources persistence in HealthLake, no clinical-content-team-led template review, no regulatory analysis).
- The PHI-logging guidance at the module level: *"Never log a raw (patient_id, plan_id, goal_set, action_set) join. The row implicitly identifies the patient, the active condition list, the goals-of-care posture, and the care-team plan; the plan-records, plan-narratives, and plan-feedback-records tables are clinical-record-equivalent PHI."*
- The structured-then-narrative discipline framing in the Setup section: *"The LLM produces words about decisions the structured logic has already made. The structured plan record is the system of record; the narratives are rendered on top with strict validator enforcement. Skip this and the LLM becomes the source of truth, which is the failure mode that makes care plan generation systems clinically unsafe."*
- The four-layer validator framing: *"The four-layer validator is non-negotiable. Schema, fact grounding, prohibited-language patterns, and required content. Failed validations regenerate with feedback or fall back to a deterministic templated narrative that always passes."*
- The clinical-content library framing: *"The clinical-content library is the substrate of the system. Goal templates and action templates are the artifacts the rest of the pipeline operates on. ... Production maintains hundreds of templates with cohort overrides, evidence references, versioning, and a clinical-content review committee that approves changes."*
- The opaque-ID rationale in `_make_plan_id`: *"NOTE: A PHI-safe id. Production-equivalent guidance: never embed plain-text patient_id, plan_version, or condition strings into identifiers that travel in URLs, EHR responses, event payloads, or logs. Use UUIDs or HMAC-SHA256 over the composite with a per-environment secret. Mirror the language flagged in 4.4 through 4.8."*
- The Bedrock de-identification stance in `_redact_for_llm`: *"Strip patient and clinician identifiers from a payload before sending to an LLM. The LLM does not need them, and stripping at the boundary limits any vendor-side logging exposure. Bedrock service terms commit to not training on prompts, but defense-in-depth still applies."*
- The freezing-for-reproducibility comment in `aggregate_plan_inputs`: *"Plan generation depends on a snapshot of the patient's state and the upstream signals from Recipes 4.1 through 4.8. The aggregation is at a single point in time, with the inputs frozen so the plan can be reproduced and audited."*
- The independent-fetch policy comment in Step 1C: *"Each signal is fetched independently; missing signals are recorded as such rather than failing the whole aggregation. A care plan can be generated without (e.g.) Recipe 4.8 treatment-response predictions if those are not available for this patient; the plan should reflect what is and is not available."*
- The goals-of-care alignment rationale in `derive_goal_set`: *"Skip the goals-of-care alignment and you produce an aggressive disease-management plan for a patient who has elected comfort-focused care, which is exactly the failure mode that erodes patient trust."*
- The reconciliation rationale in `assemble_and_reconcile_actions`: *"Reconciliation is where the multi-condition synthesis actually happens; skip it and you produce an action set that looks comprehensive on paper and is unworkable in practice."*
- The deprescribing framing: *"A polypharmacy-aware care plan looks at the current medication list and surfaces deprescribing candidates: medications that are no longer indicated, are duplicative, or violate Beers/STOPP geriatric criteria."*
- The patient-specific burden threshold rationale: *"Production: a function of functional status, cognitive status, social support, and stated preferences. Demo: start from a default and reduce for frailty, cognitive impairment, and low social support."*
- The capacity-substitution audit-trail explanation (`action["original_owner_role"]` preserved alongside the new owner role).
- The four validator layers documented inline in `_validate_narrative` with explicit rationale for each: schema and length, fact grounding (the LLM cannot introduce claims absent from the structured context), prohibited-language patterns (audience-specific), required content (audience-specific).
- The templated-fallback rationale in `_templated_narrative_fallback`: *"Deterministic fallback narrative when LLM generation or the validator fails. Lists the structured plan in the audience-appropriate shape without LLM narration."*
- The activation identity-boundary check: validates that approved_action_ids is a subset of plan.final_actions; rejects attempts to approve actions not in the structured plan.
- The frozen-at-decision-time predictions discipline (carried via `predictions_at_decision` is not present in this recipe but the analogous discipline of preserving `original_owner_role` on capacity-substituted actions plays the same audit role).
- The synthetic-data labeling: *"All sample patients, conditions, medications, goals, actions, narratives, and feedback events in the example are synthetic."*
- The collapse-to-single-file note: *"The example collapses Step Functions, Lambda, EventBridge, and Bedrock into a single Python file for readability. In production these are separate workflow stages with their own error handling, IAM, and DLQs."*

The Gap to Production section is unusually thorough (20+ items spanning clinical-content library curation, FHIR-native plan persistence in HealthLake, real interaction database integration, validated burden scoring, real capacity-and-schedule reconciliation, SageMaker Feature Store wiring, SMART on FHIR plan-review surface, patient portal and channel integration, activation dispatcher, validator extension and per-layer alarms, Bedrock cost and latency budget, cohort fairness instrumentation, plan-revision trigger calibration, cross-recipe orchestration, operational privacy, tracking-ID privacy, Step Functions DLQ coverage, idempotency, VPC / encryption / audit, synthetic data and testing, cold-start handling, patient-driven plan editing, caregiver-facing narrative, multi-language patient narratives, regulatory pathway, patient consent, adverse-event surveillance). The breadth honestly tells the reader how much sits between the recipe and a production deployment.

Calibration is appropriate for a mixed audience.

---

## Healthcare-Specific Requirements

- **PHI logging discipline.** Module-level logger comment is explicit. Logger calls in the file mostly stay on the safe side; cohort_features are scoped on the metric-emit path only.
- **Synthetic data labeling.** All sample patient IDs (`pat-007842`), condition codes, medications, goals, actions, and feedback events are obviously synthetic. The Heads-up section warns explicitly.
- **Eligibility / cohort-override filters as hard constraints.** Step 2's `_apply_cohort_overrides` returns None to suppress goal templates when a cohort override sets `removal_flag: True` (e.g., colon-cancer-screening removed for palliative-focused patients). Step 3's `_check_contraindications` similarly removes contraindicated actions before the action enters the retained set. Hard constraints, not soft features.
- **Decimal at the DynamoDB boundary.** Consistent. Bool guards prevent boolean-to-Decimal conversion.
- **Goals-of-care discipline.** The `_compute_goc_adjustment` function correctly handles the comfort-focused flag (down-weighting aggressive disease-management goals), the explicit-decline list (removing goals the patient has declined), and the stay-at-home preference (up-weighting goals that align). The `removed_by_goals_of_care` flag is set rather than silently dropping goals, so the clinician-facing narrative can surface what was removed and why.
- **Tracking-ID privacy.** All `_make_*_id` functions use UUID-based opaque format (`plan-{uuid.uuid4().hex[:16]}`, `narr-{...}`, `par-{...}`, `fb-{...}`, `act-{...}`, `input-{...}`). The discipline is intentional: patient_id, plan_version, and clinical content are never embedded in the identifier. The comment in `_make_plan_id` explicitly names the discipline.
- **Bedrock de-identification.** `_redact_for_llm` strips patient/clinician identifiers before LLM calls. `_strip_field` walks the nested dict/list structure recursively. Defense-in-depth pattern even though Bedrock service terms commit to not training on prompts.
- **Cohort-features sensitivity.** Recommendation log carries cohort_features (language, race_ethnicity_self_report, sdoh_cohort, age_band) for fairness monitoring. Gap to Production names the SDOH-cohort PHI boundary and the elevated audit posture for care-plan artifacts. **Cohort-source bug per Finding 2.**
- **Customer-managed KMS posture.** Documented in Setup and Gap to Production.
- **Validator strictness on no-recommendation language.** The patient-facing prompt and validator collaboratively avoid recommendation-language patterns; the prohibited list (`\bguaranteed\b`, `\bcure[ds]?\b`, `\b100%\s+(?:effective|safe)\b`, `\bdefinitely will\b`, `\bnever fail`) plus the patient-specific jargon list (`\bcontraindication\b`, `\biatrogenic\b`, `\bidiopathic\b`) is reasonable. Gap to Production names the per-layer alarms and validator extension work.
- **Structured-then-narrative direction.** The LLM never makes clinical decisions; the structured plan record is built deterministically through Steps 1-4 and the LLM only renders narrative on top. The validator's fact-grounding layer (with the Finding 1 caveat) enforces that the LLM cannot introduce clinical claims absent from the structured plan.
- **Templated fallback as respectable artifact.** The `_templated_narrative_fallback` produces a clean, structured presentation that lists the plan elements without LLM narration. The recipe's "Honest Take" section explicitly argues for investing in the templated fallback so the clinical team prefers it to a polished-but-uncertain LLM narrative; the Python honors that.
- **Frozen-at-decision predictions discipline.** Less central in this recipe than in 4.8 (no CATE estimates being preserved), but the analogous discipline of preserving `original_owner_role` on capacity-substituted actions and `cohort_overrides_applied` on every goal/action plays the same audit role. The reconciliation_record on the plan record captures every decision that shaped the plan.
- **Plan-revision trigger calibration.** `_evaluate_feedback_for_revision` distinguishes adverse_event (always triggers), action_failed (always triggers), and outcome_observed (triggers only on alert_threshold_crossed). Production needs cohort tuning; the demo names the gap in the Gap to Production section.

Pass on healthcare-specific handling, with Findings 1 and 2 being the operational gaps.

---

## Logical Flow

The file reads top-to-bottom in pedagogical order matching the pseudocode numbering: Setup, Configuration and Constants, Reference Data (synthetic clinical content library with goal templates and action templates carrying cohort overrides, contraindications, and fallback metadata), Shared Helpers, Step 1 (input aggregation with FHIR / Feature Store / upstream-recipe / goals-of-care / SDOH / functional-status / family-caregiver / prior-plan freezing), Step 2 (goal derivation with condition match, cohort overrides, goals-of-care alignment, quality-program weighting, patient-stated-preference goals, deduplication, ranking), Step 3 (action assembly and multi-stage reconciliation with contraindications, deprescribing, burden compression, capacity substitution, schedule sequencing), Step 4 (plan finalization with horizon bucketing, owner-and-fallback verification, plan-record assembly with idempotency guard, S3 archive), Step 5 (three audience-specific narrative generation with regeneration loop, four-layer validator, templated fallback), Step 6 (activation with identity-boundary check and operational dispatch, feedback recording with revision-trigger evaluation, periodic-review pass with cohort-fairness alerting), Putting It All Together, Demo Runner, Gap Between This and Production.

Each step opens with a short italic prose paragraph that restates the pseudocode step before the code block, matching the cookbook's established pattern.

The demo runner builds Linda from the recipe's opening narrative (67yo, T2D / CHF / CKD3b / depression / mild cognitive impairment / osteoarthritis / hypertension, recently discharged from CHF admission, lives alone in a second-floor walk-up, daughter out of state, prefers to stay at home, transportation barrier) with the full clinical state (eight medications including the long-term PPI, six conditions, recent labs showing A1c 8.4 / eGFR 39 / EF 38), feature store entries, goals-of-care, SDOH, functional status, family caregivers, prior plan, and upstream signals from Recipes 4.1 / 4.6 / 4.7. The synthetic patient is well-chosen to exercise every reconciliation path (NSAID suppression by drug-disease interaction, long-term PPI deprescribing, cardiac-rehab capacity substitution, burden compression, stay-at-home preference up-weighting CHF readmission goal).

---

## What Is Done Particularly Well

Worth calling out explicitly:

- The structured-then-narrative discipline is enforced rigorously. Steps 1-4 build the plan record deterministically; Step 5 only renders narrative on top. The validator's fact-grounding layer (with the Finding 1 expansion) prevents the LLM from introducing clinical claims. The Honest Take's framing of "the LLM produces words about decisions that the structured logic has already made" is operationalized in code.
- The reconciliation pipeline is thorough and well-ordered: contraindication filtering, deprescribing candidate generation, burden estimation with patient-specific threshold, prioritization compression, capacity substitution, schedule sequencing. Each stage has an audit-trail entry on the reconciliation_record so the clinician-facing narrative can surface what was decided and why.
- The patient-specific burden threshold (`_compute_burden_threshold`) correctly weights frailty, cognitive impairment, social support, and transportation access. The threshold is patient-specific, not global, which is the right design for the recipe's "naive burden score systematically deprioritizes the wrong actions for patients with the least support" concern.
- The deprescribing-as-action-with-prescriber-owner pattern is the right design. Deprescribing candidates surface as actions in their own right (rather than as warnings that get ignored), with the PCP as the owner and a fallback chain (pharmacist consult). The `_generate_deprescribing_actions` function adds them to retained_actions before burden estimation, so they participate in the compression decision rather than being a separate "stale alerts" channel.
- The `_apply_cohort_overrides` function correctly handles both the removal-flag case (template suppressed for this cohort) and the merge-fields case (template fields overridden for this cohort), with the applied-overrides list tracked for audit. The pattern works the same way in goal derivation and action assembly.
- The capacity-substitution preserves the original owner role (`action["original_owner_role"]`) alongside the new owner role, plus a `capacity_substitution` block on the action with the reason. The audit trail of "this action was originally owned by the cardiology scheduler but was substituted to the care manager because the scheduler was at capacity" is preserved end-to-end.
- The goals-of-care alignment correctly distinguishes retain-with-reweight (goal stays in the plan with adjusted priority) from removal (goal flagged with `removed_by_goals_of_care: True` and a reason). The flagged-rather-than-dropped pattern lets the clinician-facing narrative surface "we removed colon-cancer screening because of the patient's palliative-focused preference"; silently dropping would obscure the decision.
- The four-layer validator structure cleanly separates concerns: schema (structural), fact grounding (truthfulness), prohibited language (safety), required content (completeness). The audience-specific extensions (jargon for patient, what-changed for clinician, escalation-path for internal) are right.
- The templated fallback is a respectable artifact, not a degraded one. It explicitly lists the plan structure in the audience-appropriate shape so the clinical team can read the plan even when the LLM narrative is unavailable. The "templated narrative is better than a polished LLM narrative the validator was uncertain about" stance from the Honest Take is operationalized.
- The opaque-ID discipline is consistent across every `_make_*_id` helper. No patient_id, plan_version, or clinical content is embedded in identifiers. The `_make_plan_id` comment explicitly names the production guidance.
- The independent-fetch policy in `aggregate_plan_inputs` (each upstream signal can be missing without failing the whole aggregation) matches the recipe's framing that "the plan should reflect what is and is not available." A plan generator that requires all eight upstream recipes to be live would have an availability problem; the recipe's design is more forgiving.
- The Heads-up's enumeration of production gaps is unusually candid: *"no real EHR, claims, lab, pharmacy, or registry feed integration, no real upstream-recipe signal aggregation, no clinically curated goal-template or action-template library (the example ships a small synthetic catalog), no real drug-drug or drug-disease interaction database integration, no validated burden-scoring model, no real capacity-and-schedule reconciliation against staffing systems, no SMART on FHIR plan-review surface, no patient portal integration, no real activation dispatcher to e-prescribing or scheduling systems, no FHIR `CarePlan`-with-linked-`Goal`-`Task`-`ServiceRequest` persistence in HealthLake, no clinical-content-team-led template review, no regulatory analysis."*
- The Bedrock model-ID separation by use case (Sonnet for clinician-facing narratives because the prompt is long-context and the validator is strict; Haiku for patient-facing and disagreement narratives where the cost / latency tradeoff favors the smaller model) is well-tuned for the highest-cost recipe in the chapter.
- The `_emit_metric` helper already filters None-valued dimensions (`for k, v in dimensions.items() if v is not None`), avoiding the present-with-None CloudWatch dashboard split flagged in 4.5/4.6/4.7/4.8 reviews. Positive note.

---

## Closing Assessment

The teaching content is well-organized and faithful to the main recipe in structure, prose framing, and pedagogical ordering. The six pseudocode steps map onto Python functions with helpers in the right places. The Bedrock + DynamoDB + Kinesis + EventBridge + CloudWatch + S3 API call shapes are correct. The structured-then-narrative discipline is rigorously enforced. The reconciliation pipeline is thorough, well-ordered, and produces an audit trail that supports the clinician-facing narrative. The opaque-ID discipline is consistent. The four-layer validator structure cleanly separates concerns. The templated fallback is treated as a respectable artifact rather than a degraded one.

The two WARNINGs are localized. Finding 1 (`_check_fact_grounding` rejects valid references to suppressed actions, deprescribing candidates, and contraindication codes) is the more consequential because it makes the curated mock clinician narrative always fall back to templated and teaches a learner that the validator design is correct when it is misclassifying valid grounded references; the fix is to expand `valid_action_ids` and `valid_goal_ids` to include every structured-plan element the prompt instructs the LLM to reference, plus a small allowlist for clinical-state codes like `chf_severe` and `egfr_under_45`. Finding 2 (`_cohort_features_from_profile` called with `patient_features` instead of the patient profile) silently breaks cohort fairness instrumentation; the fix is to pass the patient profile through to `finalize_plan` or merge cohort fields into `patient_features` at aggregation time, with an optional defensive log warning in the helper.

The six NOTEs are smaller items: the demo-runner print-vs-reality mismatch (same as 4.6 / 4.7 / 4.8), Scan-where-Query-suffices in two locations (`_update_action_status` and `run_periodic_plan_review`), the `globals()` mock-injection pattern without a comment (chapter pattern), the patient validator's missing reading-level and language enforcement despite the prompt promising both, the bare `try/except: pass` patterns around Kinesis emits, and the `_compute_plan_quality_metrics` stub returning hard-coded values without an in-function warning.

PASS verdict per the persona's rule: no ERRORs, two WARNINGs (under the FAIL threshold of more than three). The two WARNINGs and several NOTEs should be addressed before the recipe ships, because they teach incorrect design patterns to a reader who copies the example into a real deployment, but they do not block the demo from running to completion.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** `_check_fact_grounding` builds `valid_action_ids` from the union of `final_actions`, `to_be_assigned`, `suppressed_actions`, and `deprescribing_added` (the last two pulled from `reconciliation_record`). A small `valid_clinical_codes` allowlist covers contraindication codes and clinical-state tokens like `chf_severe`, `egfr_under_45`, `cognitive_impairment_moderate`, `geriatric_frail`, `palliative_focused`. The curated mock clinician narrative passes validation on the first attempt, and the demo's print line shows `validator_passed=True; layers_passed=['schema', 'fact_grounding', 'prohibited_language', 'required_content']` for all three audiences.
2. **(WARNING)** `finalize_plan` either takes `patient_profile` as a separate parameter, or reads cohort fields from a `patient_profile` field on the plan-input record, or merges cohort fields into `patient_features` at aggregation time. The CloudWatch metric for `plan_finalized` carries the actual cohort dimension values for Linda (`language=en, sdoh_cohort=transportation_barrier, age_band=65-74`) rather than the defaults. As a structural improvement, `_cohort_features_from_profile` logs a warning when called with a dict that contains none of the expected cohort keys.
3. **(NOTE)** The demo runner's print messages either acknowledge that operations are structural-not-persisted when run offline against unprovisioned tables, or a DynamoDB-Local + Kinesis-Local + EventBridge-Local docker-compose snippet is provided in Setup so the demo can be exercised end-to-end.
4. **(NOTE)** The two Scan call sites (`_update_action_status` and `run_periodic_plan_review`) are replaced with appropriate Query patterns (with GSIs documented in comments and IAM permissions), or pagination is handled if a Scan is retained.
5. **(NOTE)** The `globals()` mock-injection block carries an explanatory comment matching the pattern from 4.5 / 4.6 / 4.7 / 4.8.
6. **(NOTE)** The patient validator either adds a reading-level scoring layer (using `textstat` or equivalent) and a basic language-detection check, or the recipe acknowledges the gap explicitly in a comment above the validator and in the Gap to Production section, with the Expected Results JSON's `reading_level_measured` field reframed as aspirational.
7. **(NOTE)** The bare `try/except: pass` patterns around Kinesis emits and EventBridge calls are replaced with `try/except Exception as exc: logger.warning(...)` so failures surface during local development.
8. **(NOTE)** `_compute_plan_quality_metrics` either gets a self-explanatory name (`_demo_plan_quality_metrics_stub`) or an explicit `logger.warning` at the top of the function body warning that the values are hard-coded, or a minimal real computation is implemented.

After the WARNING fixes, re-run the demo end-to-end and confirm:
- All six steps execute (already true; the demo was already complete-but-with-fallback on the clinician audience).
- `validator_passed=True` for all three audiences.
- The `plan_finalized` metric carries non-default cohort dimensions.
- Print output remains coherent.
