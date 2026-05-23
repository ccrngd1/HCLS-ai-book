# Code Review: Recipe 5.7 - Longitudinal Patient Matching Across Name Changes

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-22
**Files reviewed:**
- `chapter05.07-longitudinal-patient-matching-name-changes.md` (main recipe pseudocode)
- `chapter05.07-python-example.md` (Python companion)

**Validation performed:**
- Walked the six pseudocode steps against the Python functions one-to-one
- Verified boto3 API call shapes for DynamoDB resource (`put_item`), S3 (`put_object`), SQS (`send_message`), EventBridge (`put_events`), CloudWatch (`put_metric_data`)
- Hand-computed detection scores for all four trigger events and compared against the demo's documented expected output
- Traced the `explicit_sensitivity_class` field from `trigger_4` through `detect_name_change_candidate` to `_classify_sensitivity` to verify its propagation
- Walked the threshold-band routing for each detection score against the DIRECT/INDIRECT thresholds
- Walked the `apply_sensitivity_and_consent_envelope` derivation of permitted_display_contexts, permitted_release_scopes, and audit_rules under each sensitivity class and patient-preference combination
- Walked the propagation fan-out (9 standard consumers vs 6 restricted consumers) under each envelope class
- Verified the DynamoDB `ConditionExpression` against the schema described in the Setup section (partition key `identity_id`, sort key `event_version` for the event-history table)
- Walked the five invalidation-event source branches and verified each emits the aggregate `identity_name_change_invalidated` event
- Verified Decimal-at-the-DynamoDB-boundary discipline through `_serialize_for_dynamodb`, threshold constants (`Decimal("0.85")` etc.), and S3 key formation (no leading slashes)

---

## Summary

The Python companion is structurally faithful to the main recipe's six pseudocode steps and the architectural picture (detect a name-change candidate from the trigger event with direct-vs-indirect classification and source-strength weighting; resolve the candidate using name-change-specific thresholds calibrated separately from the demographic-match thresholds in recipe 5.1; apply the sensitivity-classification access-control envelope honoring patient preferences and jurisdictional overlays; persist the resolved event with append-only history; propagate the resolution to dependent stores via EventBridge with restricted vs general fan-out; react to invalidation events that supersede prior resolutions). The Decimal-at-the-DynamoDB-boundary discipline is consistent with `_serialize_for_dynamodb`, S3 keys do not carry leading slashes, the `MockReferenceData` / `MockPatientPreferences` / `MockJurisdictionalOverlays` replacements for production dependencies are clearly framed and exercise the major paths.

That said, this companion ships with a real correctness bug that breaks Trigger 4's documented expected output end-to-end. The `explicit_sensitivity_class` field is set on the trigger event, read by `_classify_sensitivity` on the detection envelope, but never propagated through `detect_name_change_candidate` from one to the other. The chain breaks silently: `_classify_sensitivity` always returns "GENERAL", `apply_sensitivity_and_consent_envelope` builds the envelope under the GENERAL defaults and the patient's `display_scope: "masked"` preference, the resulting `permitted_display_contexts` collapses to `[]` (no GENERAL display context survives the masked filter), the audit rules retain the GENERAL defaults of `every_disclosure_logged: False`, and `propagate_to_dependents` selects the 9-consumer GENERAL fan-out instead of the 6-consumer restricted fan-out. A reader who runs the demo gets visibly different output from what the recipe prints under "Expected console output," and a reader who copies the pattern carries forward a sensitivity-classification path that does not actually classify by the trigger's explicit class. This is the most pedagogically harmful kind of bug because it teaches a sensitivity-aware architecture that is in fact insensitive.

In addition, the DynamoDB `ConditionExpression` on the event-history put_item references an attribute name (`expected_event_version`) that does not exist on either the new item or any existing item at the same primary key. The combined condition `attribute_not_exists(event_id) AND expected_event_version = :ev` evaluates to false on every put because the second comparison fails for any missing attribute, which means every put_item against the EVENT_HISTORY_TABLE would raise `ConditionalCheckFailedException`. The bug is masked in the demo by a try/except that swallows the exception at info log level, but the code teaches a confused condition pattern that a reader copying into production would carry forward as a put-fails-everywhere bug.

The detection score values printed in the documented "Expected console output" (0.943, 0.808, 0.879, 0.951) do not match what the toy scoring functions actually produce (~0.892, ~0.78, ~0.82, ~0.88 by hand-computation). The threshold-band routing outcomes (AUTO_RESOLVE_HIGH, REVIEW_PENDING_DIRECT, REVIEW_PENDING_INDIRECT, AUTO_RESOLVE_HIGH) still land correctly because the scores cross the right thresholds either way, but a reader running the demo and comparing to the recipe sees consistently divergent score values, which is the kind of pedagogical anomaly that makes a careful reader question whether the rest of the math is right.

Three NOTEs cover smaller items: `_classify_sensitivity` drops the `jurisdictional_overlays` parameter that the pseudocode names; the persistence step's comment claims a `TransactWriteItems` pattern that the code does not implement (uses three separate `put_item` calls in one try/except); and the `Unit="Count"` on the `DetectionScore` and `ResolutionOutcome` metrics is misleading for 0-1 confidence scores.

---

## Verdict: FAIL

One ERROR (the `explicit_sensitivity_class` propagation bug, which breaks Trigger 4's documented sensitivity-classified path end-to-end), two WARNINGs (the DynamoDB `ConditionExpression` references a non-existent attribute and would always fail in production; the documented expected detection scores do not match the toy implementation's output), and three NOTEs.

ERROR findings automatically mean FAIL per the persona's rule. The ERROR is a real correctness bug, not a stylistic concern: a reader running the demo gets output that materially diverges from what is printed under "Expected console output," and a reader who copies the sensitivity-classification path into production gets a path that is silently insensitive to the explicit class on the trigger.

The fix is mechanical: add `"explicit_sensitivity_class": trigger_event.get("explicit_sensitivity_class")` to the dict returned by `detect_name_change_candidate`, so `_classify_sensitivity` can read it from the candidate. After the fix, re-run the demo and verify Trigger 4's printed `sensitivity_class` is `GENDER_AFFIRMING`, the `permitted_display_contexts` is `['treatment_with_clinical_relevance']`, the audit rules include `every_disclosure_logged: True` and `every_query_logged: True`, and the consumer fan-out is the 6-consumer restricted set.

---

## Findings

### Finding 1: `explicit_sensitivity_class` Is Set on Trigger 4 and Read by `_classify_sensitivity`, but `detect_name_change_candidate` Never Propagates It Through the Detection Envelope; Trigger 4's Sensitivity-Classified Path Silently Defaults to GENERAL

- **Severity:** ERROR
- **File:** `chapter05.07-python-example.md`
- **Location:** `detect_name_change_candidate` return dict; `_classify_sensitivity`; the entire Trigger 4 documented-output block
- **Description:**

  The trigger event for Trigger 4 carries an explicit class:

  ```python
  trigger_4 = {
      ...
      "source_type":     "court_order",
      ...
      "explicit_sensitivity_class": "GENDER_AFFIRMING",
  }
  ```

  And `_classify_sensitivity` reads exactly that field name:

  ```python
  def _classify_sensitivity(candidate: dict, identity: dict) -> str:
      explicit = candidate.get("explicit_sensitivity_class")
      if explicit:
          return explicit
      return "GENERAL"
  ```

  The `candidate` parameter to `_classify_sensitivity` is the detection envelope returned by `detect_name_change_candidate`. The detection envelope's return dict enumerates 14 fields (`classification`, `candidate_identity_id`, `candidate_identity`, `asserted_name`, `asserted_prior_name`, `asserted_change_date`, `supporting_document_ref`, `source_type`, `source_strength`, `source_record_id`, `detection_score`, `evidence_summary`, `reference_data_versions`, `matcher_config_version`, `trigger_event_id`, `detected_at`); none of them is `explicit_sensitivity_class`. The trigger's class field never makes it into the envelope and `_classify_sensitivity` always returns `"GENERAL"`.

  Demo trace for Trigger 4:
  1. `detect_name_change_candidate(trigger_4)` returns an envelope with no `explicit_sensitivity_class` key.
  2. `resolve_name_change(detection)` calls `_classify_sensitivity(candidate, identity)`. `candidate.get("explicit_sensitivity_class")` is `None`. Function returns `"GENERAL"`.
  3. `new_event["sensitivity_class"] = "GENERAL"`.
  4. `apply_sensitivity_and_consent_envelope(resolution)`:
     - `sensitivity_class = "GENERAL"`.
     - `patient_pref = patient_preferences_db.get_for_identity("id-internal-07331")` returns `{"display_scope": "masked", "patient_consented_for_audit": True, "monthly_summary_to_patient_portal": True}` (set just before Trigger 4 fires).
     - `_derive_display_contexts("GENERAL", patient_pref, overlays)`:
       - `base = ["treatment", "operations"]` (the GENERAL default).
       - `pref == "masked"` -> `base = [c for c in base if c == "treatment_with_clinical_relevance" or c == "audit_only"]` -> `[]`. Neither GENERAL default context survives the masked filter.
     - `_derive_release_scopes("GENERAL", patient_pref, overlays)`: filters to `["patient_access_api"]` (matches expected output by coincidence).
     - `_derive_audit_rules("GENERAL", patient_pref, overlays)`:
       - `base = {"every_disclosure_logged": False, "every_query_logged": False}` (GENERAL default).
       - `MockJurisdictionalOverlays.applicable_overlays` checks `new_event.get("sensitivity_class") == "GENDER_AFFIRMING"`. Since the class is now `"GENERAL"`, no overlays are returned, so the GENDER_AFFIRMING overlay's elevated audit posture never applies.
       - `patient_pref` adds `"monthly_summary_to_patient_portal": True`.
       - Final: `{"every_disclosure_logged": False, "every_query_logged": False, "monthly_summary_to_patient_portal": True}`.
  5. `propagate_to_dependents`: `if envelope.get("sensitivity_class") == "GENERAL" or not envelope:` -> the GENERAL branch fires, fan-out is the 9 standard consumers.

  Comparison to documented expected console output:

  | Field | Documented (recipe says it should print) | Actual (what the code prints) |
  |---|---|---|
  | `sensitivity_class` | `GENDER_AFFIRMING` | `GENERAL` |
  | `permitted_display_contexts` | `['treatment_with_clinical_relevance']` | `[]` (empty) |
  | `permitted_release_scopes` | `['patient_access_api']` | `['patient_access_api']` (matches by coincidence) |
  | `audit_rules` | `{'every_disclosure_logged': True, 'every_query_logged': True, 'monthly_summary_to_patient_portal': True}` | `{'every_disclosure_logged': False, 'every_query_logged': False, 'monthly_summary_to_patient_portal': True}` |
  | `consumers fanned to` | 6 restricted consumers (`local_mpi_recipe_5_1, chart_rendering, release_of_information, patient_portal, healthlake_fhir, audit_summary_to_patient`) | 9 standard consumers (the GENERAL set including `eligibility_xref_5_4`, `cross_facility_matcher_5_5`, `claims_clinical_5_6`, `quality_risk_adj` plus the 5 also in the restricted set, except for `audit_summary_to_patient`) |

  Pedagogical impact:

  1. **The reader who runs the demo gets visibly different output than the recipe prints.** Trigger 4's whole point is to demonstrate the sensitivity-classified path; the documented output asserts `GENDER_AFFIRMING`, the actual output produces `GENERAL`. A reader can hand-trace this in 60 seconds and conclude the recipe is wrong about its own output.
  2. **A reader who copies the pattern into production gets a sensitivity-aware architecture that is silently insensitive.** The whole architectural posture of "the matcher always knows the linkage; specific users may not see the prior name" depends on the access-control envelope being correctly classified at resolution time. With this bug, the envelope is GENERAL for every event, regardless of what the trigger asserts. Patient-facing dignity failures (the witness-protection / IPV / gender-affirming cases the recipe spends thousands of words on) become indistinguishable from routine name changes at the persistence boundary, with downstream consumers receiving the wider 9-consumer fan-out and treating prior-name disclosures as routine.
  3. **The `MockJurisdictionalOverlays` is dead code in the demo as written.** The overlay only fires for `sensitivity_class == "GENDER_AFFIRMING"`, but no event ever has that classification under the bug. The demo's overlay machinery never exercises any path. A reader cannot tell from the printed output whether the overlay system works.

- **Suggested fix:** Add `explicit_sensitivity_class` to the detection envelope returned by `detect_name_change_candidate`:

  ```python
  return {
      "classification":           change_type,
      "candidate_identity_id":    candidate_identity["identity_id"],
      "candidate_identity":       candidate_identity,
      "asserted_name":            asserted_name,
      "asserted_prior_name":      asserted_prior_name,
      "asserted_change_date":     asserted_change_date,
      "supporting_document_ref":  supporting_document_ref,
      "source_type":              source_type,
      "source_strength":          source_strength,
      "source_record_id":         trigger_event.get("source_record_id"),
      "detection_score":          detection_score,
      "evidence_summary": {...},
      "reference_data_versions":  reference_data.versions_used(),
      "matcher_config_version":   MATCHER_CONFIG_VERSION,
      "trigger_event_id":         trigger_event.get("event_id"),
      # Propagate the explicit sensitivity class from the trigger
      # so _classify_sensitivity can read it from the candidate.
      # Production extends this with classification logic that
      # consults the patient's identity flags, the gender-affirming-
      # care service-line workflow signals, and protective-custody
      # tags from risk-management; the demo's logic is deliberately
      # small.
      "explicit_sensitivity_class":
          trigger_event.get("explicit_sensitivity_class"),
      "detected_at":              _now_iso(),
  }
  ```

  After the fix, hand-trace Trigger 4 again to confirm:
  - `_classify_sensitivity` returns `"GENDER_AFFIRMING"`.
  - The envelope's `sensitivity_class` is `GENDER_AFFIRMING`.
  - The `permitted_display_contexts` derives from the GENDER_AFFIRMING default `["treatment_with_clinical_relevance"]`; the masked filter preserves it (since `"treatment_with_clinical_relevance"` is in the masked filter's keep-set).
  - The audit rules merge the GENDER_AFFIRMING defaults (`every_disclosure_logged: True, every_query_logged: True, monthly_summary_to_patient_portal: True`) with the patient-pref's portal-summary preference (already True).
  - The `MockJurisdictionalOverlays.applicable_overlays` now returns the elevated-audit overlay because the class is `GENDER_AFFIRMING`; the `_derive_audit_rules` loop merges the overlay's `every_*_logged: True` into base, which is already True from defaults.
  - `propagate_to_dependents` enters the `else` branch (`sensitivity_class != "GENERAL"`) and selects the 6-consumer restricted fan-out, including `audit_summary_to_patient`.

  Verification is the printed output now matching the documented expected output for Trigger 4.

---

### Finding 2: `persist_resolved_name_change` ConditionExpression References a Non-Existent Attribute `expected_event_version`; Every Real put_item Against the EVENT_HISTORY_TABLE Would Fail With ConditionalCheckFailedException

- **Severity:** WARNING
- **File:** `chapter05.07-python-example.md`
- **Location:** `persist_resolved_name_change`, the `dynamodb.Table(EVENT_HISTORY_TABLE).put_item(...)` call
- **Description:**

  The persistence step builds an event record with an `event_version` attribute and writes it with this conditional put:

  ```python
  identity_event_record = _serialize_for_dynamodb({
      "identity_id":            updated_identity["identity_id"],
      "event_version":          updated_identity["current_event_version"],
      "event_id":               new_event["event_id"],
      ...
  })

  dynamodb.Table(EVENT_HISTORY_TABLE).put_item(
      Item=identity_event_record,
      ConditionExpression=(
          "attribute_not_exists(event_id) AND "
          "expected_event_version = :ev"),
      ExpressionAttributeValues={
          ":ev": _to_decimal(
              identity.get("current_event_version", 0))},
  )
  ```

  Two problems with the condition:

  1. **There is no attribute named `expected_event_version` anywhere.** The new item has `event_version` (not `expected_event_version`); any existing item at the same primary key would also have `event_version` (because the application uses that attribute name consistently). The comparison `expected_event_version = :ev` references an attribute that does not exist, which DynamoDB evaluates to false. Combined with `attribute_not_exists(event_id) AND ...`, every put_item raises `ConditionalCheckFailedException`.

  2. **`attribute_not_exists(event_id)` does not enforce primary-key uniqueness on this table.** The Setup section names the EVENT_HISTORY_TABLE with partition key `identity_id` and sort key `event_version`. The standard idiom for "this is a new (identity_id, event_version) row" is `attribute_not_exists(identity_id)` (or `attribute_not_exists(event_version)`); on a put_item, `attribute_not_exists(<any key attribute>)` evaluates to true if and only if no item exists at that primary key. The current code's `attribute_not_exists(event_id)` is the wrong attribute (event_id is a non-key attribute on this table) and does not protect against duplicate (identity_id, event_version) writes.

  The bug is masked in the demo by:

  ```python
  except Exception as exc:
      logger.info("persist skipped (demo mode is fine to ignore)",
                   extra={"error": str(exc)})
  ```

  The exception is caught at the function-level try/except, logged at info level, and the in-memory state (`SYNTHETIC_IDENTITY_STORE`, `_IN_MEMORY_EVENT_LOG`, `_IN_MEMORY_OUTBOX`) is updated regardless. So the demo continues running and prints the expected console output.

  In a production deployment with the real DynamoDB tables provisioned, every persist call would throw the conditional-check exception, the put_item would never succeed, and the in-memory fallback path would not exist. A reader who copies this pattern into production discovers the bug only after a real put fails; tracing the cause back to the wrong attribute name is non-trivial.

  The comment block immediately above the put says:

  ```
  # 4C: write event + index update + outbox row in one
  # transaction. Production uses DynamoDB TransactWriteItems
  # with a condition expression on the expected_event_version
  # to prevent concurrent updates from clobbering one another.
  ```

  The intended pattern (optimistic concurrency: "the existing row's version equals what I read") is clear. The execution is wrong: the condition references the new item's attribute name with an `expected_` prefix that exists nowhere. The intent reads as "check that the existing row's `event_version` equals the value I observed when I started," which is a perfectly valid optimistic-concurrency pattern; the code says something different.

- **Suggested fix:** The cleanest correction depends on which table the optimistic-concurrency check is supposed to fire on:

  - If the intent is to enforce "this (identity_id, event_version) row is new" on the EVENT_HISTORY_TABLE (append-only event log keyed on `(identity_id, event_version)`), the right condition is:

    ```python
    dynamodb.Table(EVENT_HISTORY_TABLE).put_item(
        Item=identity_event_record,
        ConditionExpression="attribute_not_exists(identity_id)",
    )
    ```

    No `ExpressionAttributeValues` needed. The condition fires the standard "first writer wins on a new (partition_key, sort_key) pair" semantics that DynamoDB documents.

  - If the intent is to enforce "the IDENTITY_TABLE's current_event_version is what I observed" (optimistic-concurrency on the computed-current-state row keyed on `identity_id`), the condition belongs on the IDENTITY_TABLE put, not on the EVENT_HISTORY_TABLE put, and the attribute name is `current_event_version` (the actual attribute), not `expected_event_version`:

    ```python
    dynamodb.Table(IDENTITY_TABLE).put_item(
        Item=_serialize_for_dynamodb(updated_identity),
        ConditionExpression="current_event_version = :ev",
        ExpressionAttributeValues={
            ":ev": _to_decimal(
                identity.get("current_event_version", 0))},
    )
    ```

    The IDENTITY_TABLE's row carries the version; the put then succeeds only if the version on disk still matches what the resolver read at the start. The EVENT_HISTORY_TABLE put then enforces append-only via `attribute_not_exists(identity_id)` (or equivalent on the sort key) without an additional version comparison.

  Either fix is sound. The current code combines the two intents into one condition that references a non-existent attribute, which is the bug.

  Optionally, add an inline comment naming why the condition fires (the demo's persistence is nominally append-only, but the DynamoDB schema requires the condition to be expressed on attributes that actually exist on the row).

  Re-run the demo after the fix and confirm no info-level "persist skipped" log lines appear when the real tables exist; the in-memory fallback should be unreachable in production but should remain available for the demo's "tables not provisioned" mode.

---

### Finding 3: Documented "Expected Console Output" Detection Scores Diverge From What the Toy Scoring Functions Actually Compute

- **Severity:** WARNING
- **File:** `chapter05.07-python-example.md`
- **Location:** The "Expected console output" block at the end of the demo section
- **Description:**

  The recipe documents specific detection-score values in its expected console output:

  ```
  Trigger 1: ... detection_score:           0.943
  Trigger 2: ... detection_score:           0.808
  Trigger 3: ... detection_score:           0.879
  Trigger 4: ... detection_score:           0.951
  ```

  Hand-tracing each trigger through the actual scoring functions produces different values:

  **Trigger 1 (Catherine Wilson -> Catherine Hernandez, court order):**
  - `_name_pair_plausibility`: given_score=1.0 (exact match), middle_score=1.0 (Marie matches Marie), family_score=0.6 (`detect_surname_pattern("Wilson", "Hernandez")` returns `"maiden_to_married_or_replacement"` -> 0.6). Combined: 0.30*1.0 + 0.10*1.0 + 0.60*0.6 = **0.76**.
  - `_demographic_match_strength`: dob match (0.50), ssn match (0.25), address match (0.15), phone match (0.10) summing to 1.00 / 1.00 weight = **1.00**.
  - `_temporal_plausibility`: asserted_change_date >= current_from -> **1.0**.
  - `source_strength_multiplier["STRONG"]` = 1.00.
  - `detection_score = (0.45*0.76 + 0.35*1.00 + 0.20*1.00) * 1.00 = 0.892`.
  - **Documented: 0.943, Actual: 0.892, Difference: 0.051.**

  **Trigger 2 (Maria Garcia -> Garcia-Lopez, self-assertion):**
  - name_pair: given=1.0, middle=0.5, family=0.9 (hyphenation_added). Combined: 0.30+0.05+0.54 = 0.89.
  - demographic: 1.00. temporal: 1.0 (change_date 2026-04-15 >= creation 2010-05-12).
  - source_strength_multiplier["MEDIUM-WEAK"] = 0.82.
  - `detection_score = (0.45*0.89 + 0.35*1.0 + 0.20*1.0) * 0.82 = 0.9505 * 0.82 = 0.779`.
  - **Documented: 0.808, Actual: 0.779, Difference: 0.029.**

  **Trigger 3 (Margaret Chen -> Chen-Patel, payer eligibility):**
  - name_pair: given=1.0, middle=0.5, family=0.9 (hyphenation_added). Combined: 0.89.
  - demographic: 1.00. temporal: 0.7 (asserted_change_date is None -> default 0.7).
  - source_strength_multiplier["MEDIUM"] = 0.92.
  - `detection_score = (0.45*0.89 + 0.35*1.0 + 0.20*0.7) * 0.92 = 0.8905 * 0.92 = 0.819`.
  - **Documented: 0.879, Actual: 0.819, Difference: 0.060.**

  **Trigger 4 (Alex -> Avery, court order):**
  - name_pair: given=0.30 (no exact match, no nickname, but first letter 'a' matches), middle=0.5, family=1.0 (Mitchell == Mitchell). Combined: 0.09+0.05+0.60 = 0.74.
  - demographic: 1.00. temporal: 1.0.
  - source_strength_multiplier["STRONG"] = 1.00.
  - `detection_score = (0.45*0.74 + 0.35*1.0 + 0.20*1.0) * 1.00 = 0.883`.
  - **Documented: 0.951, Actual: 0.883, Difference: 0.068.**

  All four documented scores are higher than what the code computes, by 3-7 percentage points. The threshold-band routing outcomes (AUTO_RESOLVE_HIGH for Triggers 1 and 4, REVIEW_PENDING_DIRECT for Trigger 2, REVIEW_PENDING_INDIRECT for Trigger 3) still match because the actual scores cross the right threshold boundaries, but a reader running the demo and reading the documented output side-by-side sees consistent divergence.

  The recipe's note "Detection scores include the source-strength multiplier, so a court-order trigger scores higher than the same demographic-and-name-pair signals would score with a self-assertion source" is correct in principle but does not explain why the documented values are systematically higher than what the toy scoring produces. A learner who tries to extend the scoring (add a feature, adjust a weight) and re-runs the demo cannot calibrate against documented numbers because the documented numbers do not correspond to the implemented math.

- **Suggested fix:** Two paths, either is acceptable:

  1. **Re-run the demo, capture the actual console output, and replace the "Expected console output" block with the actual values.** This is the smaller change and keeps the toy scoring as is. Add a parenthetical note that the scoring is illustrative and that production replaces the toy scorers with Splink / `recordlinkage` / `jellyfish`-based comparators.

  2. **Adjust the toy scoring functions to produce the documented values.** This is more involved (the family-name pattern detection's `maiden_to_married_or_replacement` -> 0.6 and the given-name first-letter fallback -> 0.30 are the load-bearing stand-ins; raising either would push the scores up). The trade-off is that the scoring becomes less honest about how weak the toy approximation is.

  Either way, hand-trace each of the four triggers after the fix to confirm the documented values match the code's actual output. Add a one-line note in the prose immediately following the expected output block clarifying that the scores depend on the toy reference data (specifically the surname-change-pattern detector, the nickname dictionary, and the per-feature weights) and that small changes to any of these reproduce as score differences.

  Same family of issue as the recipe-text claim "Sample direct, high-confidence name-change resolution: ... 'detection_score': 0.96, 'name_pair_plausibility': 0.92, ..." — the recipe's expected-output JSON also does not match what the toy code produces. Whichever direction the fix goes (update prose or update code), the recipe's expected-output JSON and the Python's documented console output should be reconciled in one pass.

---

### Finding 4: `_classify_sensitivity` Drops the `jurisdictional_overlays` Parameter Named in the Pseudocode; Overlay Inputs Cannot Influence the Class Selection

- **Severity:** NOTE
- **File:** `chapter05.07-python-example.md`
- **Location:** `_classify_sensitivity` signature; the call site in `resolve_name_change`
- **Description:**

  The pseudocode for Step 2C names three inputs to the sensitivity-classification call:

  ```
  sensitivity_class: classify_sensitivity(
      candidate, identity, jurisdictional_overlays),
  ```

  The Python signature drops `jurisdictional_overlays`:

  ```python
  def _classify_sensitivity(candidate: dict, identity: dict) -> str:
      explicit = candidate.get("explicit_sensitivity_class")
      if explicit:
          return explicit
      return "GENERAL"
  ```

  The overlay information IS consumed downstream in `apply_sensitivity_and_consent_envelope` (which calls `jurisdictional_overlays.applicable_overlays(identity, new_event)` to derive the audit-rules), so the bug-shaped concern from Finding 1 is not exclusively about losing access to overlays at classification time. But the pseudocode's intent is that classification can be jurisdiction-aware (e.g., a state-level rule that elevates the class to PROTECTIVE_CUSTODY for a specific category of patient, even if the trigger did not assert it explicitly), and the Python's signature does not support that intent.

  Demo impact: none, because the demo's classification logic is just "did the trigger explicitly tell us?" and the patient-preference layer happens to live elsewhere. But a reader extending the recipe to add jurisdiction-aware classification has to thread `jurisdictional_overlays` through the call chain, and the gap between the pseudocode and the Python is one more place the reader has to inspect.

- **Suggested fix:** Take the third argument and document it:

  ```python
  def _classify_sensitivity(candidate: dict, identity: dict,
                                jurisdictional_overlays) -> str:
      """Default sensitivity classification. Production extends
      this with patient-portal preference capture, gender-affirming-
      care service-line workflow signals, legal-hold tags from the
      institution's risk-management system, protective-custody
      flags from law-enforcement coordination, and per-jurisdiction
      classification overlays (e.g., a state-level rule that
      classifies all reproductive-health-related changes under a
      specific protective class). The demo's logic is deliberately
      small."""
      # Trigger event may carry an explicit class (set by the
      # gender-affirming-care intake workflow, the patient portal,
      # or a compliance officer).
      explicit = candidate.get("explicit_sensitivity_class")
      if explicit:
          return explicit
      # Production: walk jurisdictional_overlays here for any
      # overlay that classifies based on the identity's home
      # jurisdiction, the patient's flag set, or the encounter
      # context. The demo's MockJurisdictionalOverlays only fires
      # downstream in the envelope step.
      return "GENERAL"
  ```

  And update the call site:

  ```python
  "sensitivity_class": _classify_sensitivity(
      candidate, identity,
      jurisdictional_overlays),
  ```

  The fix is mechanical but matches the pseudocode's intent and lets future readers extend the classification logic without restructuring the signature.

---

### Finding 5: `persist_resolved_name_change` Comment Names "TransactWriteItems" but the Code Uses Three Separate `put_item` Calls; the Linkage Table, Search Index, and Outbox Can Diverge on Partial Failure

- **Severity:** NOTE
- **File:** `chapter05.07-python-example.md`
- **Location:** `persist_resolved_name_change`, the try block around the three `put_item` calls
- **Description:**

  The comment block claims a transactional write:

  ```python
  # 4C: write event + index update + outbox row in one
  # transaction. Production uses DynamoDB TransactWriteItems
  # with a condition expression on the expected_event_version
  # to prevent concurrent updates from clobbering one another.
  ```

  The code uses four separate `put_item` calls inside one try:

  ```python
  try:
      # In production: dynamodb.meta.client.transact_write_items(...).
      # The demo writes per table for readability.
      dynamodb.Table(EVENT_HISTORY_TABLE).put_item(...)
      for entry in search_index_entries:
          dynamodb.Table(SEARCH_INDEX_TABLE).put_item(
              Item=_serialize_for_dynamodb(entry))
      dynamodb.Table(IDENTITY_TABLE).put_item(
          Item=_serialize_for_dynamodb(updated_identity))
      dynamodb.Table(EVENT_OUTBOX_TABLE).put_item(
          Item=_serialize_for_dynamodb(outbox_row))
  except Exception as exc:
      logger.info("persist skipped (demo mode is fine to ignore)",
                   extra={"error": str(exc)})
  ```

  Three consequences:

  1. **The four writes are not atomic.** If the EVENT_HISTORY put succeeds and any of the SEARCH_INDEX puts, the IDENTITY put, or the OUTBOX put fails (transient throttling, connection reset, conditional-check failure), the persistence is partial. The event log carries an entry that the IDENTITY_TABLE's computed-current-state row does not reflect, or the SEARCH_INDEX has an entry pointing at an event that the IDENTITY row does not yet know about, or the OUTBOX never gets the row that triggers the EventBridge emit. Each of these is a "the system is silently inconsistent" failure mode that the recipe text explicitly warns against:

     > Skip the transactional discipline and you produce identity records whose name history disagrees with the search index, which causes the matcher to make decisions on stale data and the analytics layer to deduplicate incorrectly.

  2. **The acknowledgment is in a comment, not at the call site.** A reader walking the comment-to-code mapping sees "in one transaction" in the leading comment and "four separate puts" immediately below. The single inline comment "In production: dynamodb.meta.client.transact_write_items(...). The demo writes per table for readability." is correct but easy to miss given the volume of code in `persist_resolved_name_change`.

  3. **Same chapter pattern as recipes 5.5 and 5.6.** Recipe 5.5's `release_and_audit` and recipe 5.6's `persist_and_emit` carry similar TransactWriteItems-aspirational comments without the actual transactional write. Recipe 5.7 inherits the same gap and benefits from the same explicit TODO.

  The catch-and-log-at-info-level pattern around the puts also adds a separate concern (Finding 2 already names the ConditionExpression bug that this swallow masks); even with the ConditionExpression fixed, the `except Exception as exc: logger.info(...)` swallows real production failures and reports them at the wrong level. Per the explicit "demo mode is fine to ignore" comment this is a deliberate teaching choice; for a production-ready version the catch should at least log at warning or error level, distinguish ConditionalCheckFailedException from other exceptions, and re-raise the unexpected categories.

- **Suggested fix:** Add an explicit TODO at the call site naming the production pattern:

  ```python
  try:
      # TODO (production): wrap all four writes in a
      # TransactWriteItems call so the event log, the search
      # index, the computed-current-state IDENTITY_TABLE row, and
      # the outbox stay consistent on partial failure. The demo
      # uses four separate put_item calls for readability and to
      # exercise per-table conditional-check semantics; the
      # production path is:
      #
      #   dynamodb.meta.client.transact_write_items(
      #       TransactItems=[
      #           {"Put": {"TableName": EVENT_HISTORY_TABLE, ...}},
      #           {"Put": {"TableName": SEARCH_INDEX_TABLE, ...}}
      #             # one TransactItems entry per search-index row
      #             # (max 100 items per transaction; production
      #             # batches when more entries are needed)
      #           {"Put": {"TableName": IDENTITY_TABLE, ...,
      #                       "ConditionExpression":
      #                           "current_event_version = :ev"}},
      #           {"Put": {"TableName": EVENT_OUTBOX_TABLE, ...}},
      #       ])
      #
      # The transaction also handles the version-bump optimistic-
      # concurrency check on the IDENTITY_TABLE so concurrent
      # name-change resolutions cannot clobber one another.
      dynamodb.Table(EVENT_HISTORY_TABLE).put_item(...)
      ...
  except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
      # Expected when a concurrent resolver wrote first; production
      # re-reads the identity, re-runs the resolver, and retries.
      logger.warning("persist conditional check failed; re-evaluation needed",
                     extra={"identity_id": identity["identity_id"]})
      raise
  except Exception as exc:
      logger.info("persist skipped (demo mode is fine to ignore)",
                   extra={"error": str(exc)})
  ```

  Optionally implement the TransactWriteItems path when all real tables exist and fall back to the per-table puts for the demo's "no tables provisioned" mode. Same TODO posture as recipe 5.6's review-checklist Finding 6.

---

### Finding 6: `_emit_metric` Hardcodes `Unit="Count"` for Continuous-Score Metrics Like `DetectionScore` That Are 0-1 Confidence Values

- **Severity:** NOTE
- **File:** `chapter05.07-python-example.md`
- **Location:** `_emit_metric` helper; the `DetectionScore` emit in `detect_name_change_candidate`
- **Description:**

  The helper hardcodes the unit:

  ```python
  cloudwatch_client.put_metric_data(
      Namespace=CLOUDWATCH_NAMESPACE,
      MetricData=[{
          "MetricName": metric_name,
          "Value": value,
          "Unit": "Count",
          "Dimensions": [...],
      }],
  )
  ```

  Some emit sites use the helper for actual counts:

  ```python
  _emit_metric("DetectionResult", 1.0, dimensions={"Outcome": "no_existing_identity"})
  _emit_metric("ResolutionOutcome", 1.0, dimensions={...})
  _emit_metric("EventsPersisted", 1.0, dimensions={...})
  _emit_metric("Invalidations", 1.0, dimensions={"Source": ...})
  ```

  These are correct: each emit represents one event of the named class.

  But the `DetectionScore` emit publishes a continuous 0-1 confidence value with the same `Unit="Count"`:

  ```python
  _emit_metric("DetectionScore", float(detection_score),
                dimensions={"CohortBucket":   cohort_bucket,
                              "ChangeType":     change_type,
                              "SourceStrength": source_strength})
  ```

  CloudWatch accepts the data (the `Count` unit does not constrain the value range), but the metric's unit field is misleading: a viewer browsing the metric in the CloudWatch console sees `Count` and reasonably assumes the value is "how many of something." For a 0-1 score, the right unit is `None` (or `Percent` if the value is multiplied by 100).

  Demo impact: small. The cohort-stratified-disparity dashboards described in the main recipe consume these metrics through Athena queries against the underlying CloudWatch metric data, where the unit field is mostly informational. A reader copying the helper into a different metric where unit-correctness matters (e.g., latency in milliseconds) might miss that the unit is hardcoded.

- **Suggested fix:** Add an optional `unit` parameter to `_emit_metric` with a `Count` default, and pass `None` for the continuous-score metrics:

  ```python
  def _emit_metric(metric_name: str, value: float,
                    dimensions: dict = None,
                    unit: str = "Count") -> None:
      try:
          cloudwatch_client.put_metric_data(
              Namespace=CLOUDWATCH_NAMESPACE,
              MetricData=[{
                  "MetricName": metric_name,
                  "Value": value,
                  "Unit": unit,
                  "Dimensions": [
                      {"Name": k, "Value": v}
                      for k, v in (dimensions or {}).items()
                  ],
              }],
          )
      except Exception as exc:
          logger.warning("metric emit failed",
                          extra={"metric": metric_name,
                                  "error": str(exc)})
  ```

  And:

  ```python
  _emit_metric("DetectionScore", float(detection_score),
                dimensions={"CohortBucket":   cohort_bucket,
                              "ChangeType":     change_type,
                              "SourceStrength": source_strength},
                unit="None")
  ```

  Same applies to any future metric that publishes a continuous score (composite confidence, name-pair plausibility, etc.). This is a minor pedagogical-clarity change; CloudWatch behavior does not depend on it.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Function | Consistent? |
|----------------|-----------------|-------------|
| `detect_name_change_candidate(trigger_event)` | `detect_name_change_candidate` plus `_classify_source_strength`, `_identity_lookup_by_local_id`, `_identity_lookup_by_member_id`, `_identity_search_by_name_and_demographics`, `_name_pair_plausibility`, `_demographic_match_strength`, `_temporal_plausibility`, `_combine_detection_signals` | Mostly yes (1A candidate-identity lookup walks local_patient_id, then member_id via cross-reference, then asserted-prior-name search, then asserted-name search; 1B classifies DIRECT vs INDIRECT based on the presence of explicit assertion signals or known direct source types; 1C combines the three feature scores with source-strength multiplier). **The detection envelope omits `explicit_sensitivity_class` per Finding 1.** |
| `resolve_name_change(detection_envelope, matcher_config)` | `resolve_name_change` plus `_classify_sensitivity`, `_infer_effective_date`, `_compute_updated_identity_state` | Mostly yes (2A applies DIRECT vs INDIRECT thresholds; 2B routes to AUTO_RESOLVE_HIGH / AUTO_RESOLVE_MED_DOCUMENTED / AUTO_RESOLVE_INDIRECT_HIGH / REVIEW_PENDING_DIRECT / REVIEW_PENDING_INDIRECT / REJECT bands; 2C builds the new event with all metadata fields; 2D writes pending items to the review queue). **`_classify_sensitivity` always returns "GENERAL" because `explicit_sensitivity_class` is not propagated per Finding 1; signature drops jurisdictional_overlays per Finding 4.** |
| `apply_sensitivity_and_consent_envelope(resolution_envelope, identity, patient_preferences, jurisdictional_overlays)` | `apply_sensitivity_and_consent_envelope` plus `_derive_display_contexts`, `_derive_release_scopes`, `_derive_audit_rules` | Yes (the envelope carries sensitivity_class, patient_preference, jurisdictional_overlays, permitted_display_contexts, permitted_release_scopes, audit_rules; the derive helpers honor patient preferences as restrict-only-never-expand on the defaults). **The envelope is consistently GENERAL because the upstream classification always returns GENERAL per Finding 1.** |
| `persist_resolved_name_change(resolution_envelope, access_control_envelope)` | `persist_resolved_name_change` plus `_build_search_index_entries`, `_archive_to_s3` | Mostly yes (4A canonical event-record construction with append-only event log shape; 4B search-index entry construction; 4C atomic write across event-history, search-index, identity-table, and outbox; 4D archive to audit S3 bucket). **The ConditionExpression references a non-existent attribute per Finding 2; the four writes are not transactional per Finding 5.** |
| `propagate_to_dependents(identity_event_record, access_control_envelope)` | `propagate_to_dependents` | Yes (5A emit canonical event to the resolved-event bus via EventBridge; 5B simulate downstream consumer fan-out, with 9 standard consumers for GENERAL events and 6 restricted consumers for non-GENERAL events; 5C archive the curated payload to the derived snapshot bucket). The consumer-call list is recorded in-memory rather than dispatched to real Lambdas; comment names the simplification. **The fan-out is always the GENERAL set because the upstream classification always returns GENERAL per Finding 1.** |
| `invalidate_on_event(invalidation_event)` | `invalidate_on_event` | Yes (seven event-source branches: correction, reversal, identity_merge, identity_unmerge, sensitivity_update, document_upgrade, cross_facility_match_invalidated, plus the aggregate identity_name_change_invalidated emit). The demo's invalidate-on-event records what would be done rather than actually re-resolving against the affected identities; the simplification is acknowledged. |

Intentional deviations clearly framed:

- The Splink / `recordlinkage` / `jellyfish` probabilistic-record-linkage core becomes toy `_demographic_match_strength`, `_name_pair_plausibility`, and `_temporal_plausibility` functions. Documented in the Heads-up section and in Gap to Production.
- The production reference-data store (commercial vendors plus institution-maintained references) becomes `MockReferenceData` with a small nickname dictionary and a few surname-change-pattern detectors. Documented inline.
- The patient-portal preference-capture flow becomes `MockPatientPreferences` with an in-memory dict. Documented inline.
- The institutional jurisdictional-policy store becomes `MockJurisdictionalOverlays` with one example state-level overlay. Documented inline.
- The Glue / Spark periodic-reconciliation pipeline becomes "the demo runs in-process for a handful of trigger events." Documented in Gap to Production.
- The Step Functions orchestration, multiple Lambdas, and SQS-driven worker pattern collapse into a single Python file. Documented at the top.
- The DynamoDB read path falls back to in-memory dicts and lists when the real tables are not provisioned. Documented.
- The supporting-document upload-and-extraction pipeline (Amazon Textract or commercial document-AI) is omitted; document references are passed as opaque S3 URIs. Documented.
- The FHIR-native HealthLake integration is named in the propagation step but is a no-op in the demo. Documented.
- The patient-portal upload UI, patient-preference UI, three-queue review tooling, and information-blocking-compliant patient-access read path are deferred to Gap to Production. Documented.

The substantive deviation (Finding 1) is the consistency gap that carries pedagogical consequence. The acknowledged simplifications (mock reference data, mock preferences, mock overlays, in-memory tables) are clearly framed.

---

## AWS SDK Accuracy

| API Call | Method | Notes |
|----------|--------|-------|
| DynamoDB PutItem (event history) | `dynamodb.Table(EVENT_HISTORY_TABLE).put_item(Item=..., ConditionExpression="attribute_not_exists(event_id) AND expected_event_version = :ev", ExpressionAttributeValues=...)` | **The condition references a non-existent attribute per Finding 2**; in production this raises ConditionalCheckFailedException on every call. The Item structure is correct (Decimals via `_serialize_for_dynamodb`). |
| DynamoDB PutItem (search index) | `dynamodb.Table(SEARCH_INDEX_TABLE).put_item(Item=_serialize_for_dynamodb(entry))` | Correct shape. No condition (search index is rebuilt from the canonical store on every change). |
| DynamoDB PutItem (identity table) | `dynamodb.Table(IDENTITY_TABLE).put_item(Item=_serialize_for_dynamodb(updated_identity))` | Correct shape. No condition (production should add `current_event_version = :ev` for optimistic concurrency per Finding 2's suggested fix). |
| DynamoDB PutItem (outbox) | `dynamodb.Table(EVENT_OUTBOX_TABLE).put_item(Item=_serialize_for_dynamodb(outbox_row))` | Correct shape. No condition (each outbox row has a fresh UUID). |
| S3 PutObject | `s3_client.put_object(Bucket=..., Key=key, Body=body, ServerSideEncryption="aws:kms")` | Correct. Body is bytes-encoded JSON with `default=str` to handle Decimal. Keys use `{partition}/{date}/{key_id}.json` with no leading slashes. The supporting_document_ref strings (`"s3://my-name-change-supporting-documents/.../court-order-...pdf"`) are stored as opaque references in record payloads, not used as actual S3 keys. |
| SQS SendMessage | `sqs_client.send_message(QueueUrl=..., MessageBody=...)` | Correct shape for standard queues. The name-change review queue receives pending items as JSON-serialized dicts. |
| EventBridge PutEvents | `eventbridge_client.put_events(Entries=[{Source, DetailType, EventBusName, Detail}])` | Correct shape. `Detail` is JSON-serialized with `default=str` to handle Decimal. Two detail-types: `identity_name_change_resolved` and `identity_name_change_resolved_restricted` from `propagate_to_dependents`, plus `identity_name_change_invalidated` from `invalidate_on_event`. **The detail-type selection depends on `envelope.get("sensitivity_class") != "GENERAL"`, which always evaluates to false per Finding 1.** |
| CloudWatch PutMetricData | `cloudwatch_client.put_metric_data(Namespace, MetricData=[{MetricName, Value, Unit, Dimensions}])` | Correct shape. Five metric names appear: `DetectionResult`, `DetectionScore`, `ResolutionOutcome`, `EventsPersisted`, `Invalidations`. **`Unit="Count"` is hardcoded for `DetectionScore` which is a continuous 0-1 score per Finding 6.** |

The SDK-level concerns are: Finding 2 (ConditionExpression bug on the EVENT_HISTORY_TABLE put), Finding 5 (TransactWriteItems pattern not implemented), and Finding 6 (Unit hardcoded). All API surfaces are current and correct.

---

## DynamoDB and Data Type Check

- `_to_decimal` correctly uses `Decimal(str(value))` and short-circuits on already-Decimal inputs.
- `_serialize_for_dynamodb` recursively walks dicts, lists, tuples, and sets, converts floats to Decimal. Booleans pass through (`isinstance(True, float)` is False; bool is an int subclass, not float). The pattern is safe.
- Threshold constants are constructed as Decimals (`Decimal("0.85")`, `Decimal("0.70")`, etc.) at module load time. The detection-score weights and source-strength multipliers are also Decimals.
- All match-feature scores (`name_pair_plausibility`, `demographic_match_strength`, `temporal_plausibility`) are constructed as Decimals via direct Decimal literals or `_to_decimal`.
- `_combine_detection_signals` does Decimal arithmetic throughout; the return value is a Decimal.
- The CloudWatch `Value` parameter uses `float(detection_score)`. Correct (CloudWatch accepts native floats; only DynamoDB requires Decimal).
- The EventBridge `Detail` flows through `json.dumps(..., default=str)`, which avoids the `TypeError: Object of type Decimal is not JSON serializable` that would otherwise raise.
- The S3 archive flow through `json.dumps(payload, default=str)` similarly handles Decimals.

The Decimal discipline is correct. No type-handling bugs.

---

## S3 and Credentials Check

- The example uses S3 only for archive writes (`name-change-events`, `name-change-snapshots`). No leading slash on any key.
- The deploy-time guardrail covers every resource-name constant via the `for _name, _value in [...]: assert _value` loop. **No constant can silently be empty.** Same discipline as recipes 5.4, 5.5, and 5.6.
- No hardcoded credentials. Module-level boto3 clients use the documented environment credential chain.
- The IAM permissions list in Setup matches the API surface used by the code (PutItem on the four DynamoDB tables, PutObject on the three S3 buckets, SendMessage on the four review/invalidation queues, PutEvents on the two event buses, PutMetricData for CloudWatch).
- The Setup section explicitly names that "tutorial-level permissions above are fine for learning and will fail any serious IAM review" with the right framing about per-Lambda role scoping and the persistence Lambda's append-only IAM (no `dynamodb:DeleteItem`, no `dynamodb:UpdateItem` on existing version items).
- The PHI framing is clear: identity records are PHI; prior-name disclosures may be sensitivity-classified; logging is structural-metadata-only per the `logger` setup comment.
- The Heads-up section names the synthetic-data discipline: "The synthetic patients, name changes, and supporting documents in the demo are fictional; the names, MRNs, court-order references, and document references are obviously made-up and should not match anyone real."
- The Gap to Production section names the patient-preference UI and consent capture, the reference-data sourcing, the threshold-calibration governance, the three review queues, the patient-portal upload flow, the information-blocking-compliant patient-access read path, the cross-organizational propagation policy, the vital-records integration, the FHIR-native HealthLake integration, the KMS-encrypted-everything posture, the VPC + VPC endpoints, the CloudTrail data events, and the Lake Formation column-and-row-level access control on the analytics surface.

Pass.

---

## Comment Quality Assessment

Comments consistently explain the "why":

- The Heads-up at the top names every major production gap before the code starts (no Splink-or-`recordlinkage` probabilistic-record-linkage core, no FHIR Patient resource serializer, no document-extraction pipeline, no Glue/Spark periodic-reconciliation pipeline, no Step Functions orchestration, no SageMaker calibration loop, no patient-portal UI, no review-queue UI, no FHIR-native HealthLake integration, no IAM / KMS / VPC / WAF / CloudTrail wiring).
- The "things worth knowing upfront" list correctly names the temporal-name-as-event-history posture, the direct-vs-indirect detection split, the source-strength-weighted resolution thresholds, the sensitivity-classification-as-access-control-envelope distinction, the reversibility-is-the-architecture posture, and the Decimal-at-the-DynamoDB-boundary discipline as the load-bearing structural commitments.
- The matcher-always-knows-the-linkage / specific-users-may-not framing is restated several times throughout the file, including in step prose and inline comments. This is the most pedagogically important architectural commitment and the file's emphasis is appropriate.
- The reversibility-is-not-a-feature framing is named in the architectural-commitment list and in Step 6 ("Name-change events are append-only history; superseding events update the *computed* current state without losing the underlying log.").
- The DynamoDB-rejects-Python-float gotcha is documented inline ("Same gotcha as recipes 5.1 / 5.2 / 5.3 / 5.4 / 5.5 / 5.6; the same `_to_decimal` helper handles it.").
- The async-decomposition deferral is acknowledged: "The example collapses Step Functions, multiple Glue jobs, multiple Lambdas, and the SQS-driven worker pattern into a single Python file for readability."
- The mock-as-stand-in framing is clear in `MockReferenceData`, `MockPatientPreferences`, and `MockJurisdictionalOverlays` with explicit production-extension notes ("Real deployments encode state law, institutional policy, and HIE participation-agreement constraints with attorney-reviewed rules.").
- The synthetic-data labeling is unambiguous in the demo runner ("All patients, names, and supporting documents in this demo are fictional.").
- The threshold-calibration discipline is named in the threshold constants' inline comment ("Calibrated separately from the demographic-match thresholds in recipe 5.1. The cost-benefit profile is different here: false acceptances of name changes corrupt the longitudinal record; false rejections fragment it.").
- The cohort-stratified-disparity monitoring is named in `_emit_metric` ("Cohort-bucket dimensions feed the cohort-stratified accuracy monitoring; production aggregates by CohortBucket and alarms on per-cohort detection-rate or false-acceptance-rate disparities.").
- The append-only-IAM discipline is named in Setup ("The persistence Lambda gets append-only IAM on the identity-event history (no `dynamodb:DeleteItem`, no `dynamodb:UpdateItem` on existing version items) enforced through condition keys plus DynamoDB resource-based policy.").
- The information-blocking-compliance framing is named in the Gap-to-Production section, with explicit reference to the 21st Century Cures Act.

The Gap to Production section is unusually thorough (15+ items). The breadth honestly tells the reader how much sits between the recipe and a production deployment.

The comments that would benefit from updates per the findings:

- `detect_name_change_candidate`'s return dict needs `explicit_sensitivity_class` propagation per Finding 1.
- The DynamoDB ConditionExpression on the EVENT_HISTORY_TABLE put needs a corrected attribute name per Finding 2.
- The expected console output values (detection scores) need to be reconciled with what the code actually computes per Finding 3.
- `_classify_sensitivity` would benefit from accepting `jurisdictional_overlays` per Finding 4.
- The persistence-step try block would benefit from an inline TODO naming the production transactional-outbox pattern per Finding 5.
- The `_emit_metric` helper would benefit from an optional `unit` parameter per Finding 6.

Calibration is otherwise appropriate for a mixed audience.

---

## Healthcare-Specific Requirements

- **PHI discipline.** The Heads-up section names that identity records are PHI; logging is structural-metadata-only (identity_id, event_id, resolution status, confidence band, sensitivity_class) per the `logger` setup comment. Patient-name strings, raw demographics, and supporting-document contents are not logged.
- **Synthetic data labeling.** Sample patient IDs (`id-internal-00874`, etc.), MRNs, member IDs, ICD-10 codes, court-order references, and supporting-document references are obviously synthetic. The Heads-up section warns explicitly. The `MockReferenceData`, `MockPatientPreferences`, and `MockJurisdictionalOverlays` use the same synthetic inputs.
- **Decimal at the DynamoDB boundary.** Consistent. Defensive float-to-Decimal coercion in `_serialize_for_dynamodb` and at the score-construction boundary throughout the matcher.
- **Audit-archive every operation.** `_archive_to_s3` is called at persistence time (canonical event archive to the AUDIT_ARCHIVE_BUCKET) and at propagation time (curated snapshot to the DERIVED_SNAPSHOT_BUCKET). Every operational state of the resolved name change is captured, including the `current_name_redacted` flag for non-GENERAL events on the analytics-zone snapshot.
- **Provenance on every record.** Identity-event records carry `matcher_config_version`, `reference_data_versions`, `resolved_at`, `resolved_by`, plus the detection score, evidence summary, and source-strength tier. A future audit can attribute a name-change decision to the matcher version and the reference-data versions active at decision time.
- **Append-only persistence (intent).** The DynamoDB put on the EVENT_HISTORY_TABLE intends to enforce append-only via the ConditionExpression. The intent is correct; **the implementation is broken per Finding 2.**
- **Cohort-stratified telemetry.** `DetectionScore` and `ResolutionOutcome` emit with `CohortBucket` dimensions sourced from the identity's `cohort_bucket` field. The cohort buckets in the synthetic data (`english_traditional`, `spanish_double_surname`, `east_asian_traditional`) match the recipe's stated cohort axes.
- **Sensitivity-classification posture (architectural intent).** The matcher-always-knows-the-linkage / specific-users-may-not split is correctly enumerated in the access-control envelope, with patient preferences honored as restrict-only-never-expand on the per-class defaults. **The classification path is broken per Finding 1, so the envelope is consistently GENERAL even when the trigger asserts otherwise.**
- **Information-blocking awareness.** The recipe text names the 21st Century Cures Act information-blocking obligation as load-bearing for the patient-access release path. The `_derive_release_scopes` function correctly preserves `patient_access_api` across all sensitivity classes (a restricted patient still has the right to access her own records). The architectural posture is consistent with the regulatory backdrop.
- **Reversibility-is-the-architecture posture.** The append-only event log, the superseding-events-update-computed-state pattern, and the seven-source invalidation pipeline (correction, reversal, identity_merge, identity_unmerge, sensitivity_update, document_upgrade, cross_facility_match_invalidated) are all structurally present.
- **Patient-preference and consent metadata.** The access-control envelope carries patient_preference, jurisdictional_overlays, permitted_display_contexts, permitted_release_scopes, and audit_rules. The shape is right. **The classification that drives them is broken per Finding 1.**

Pass on the structural healthcare requirements (PHI handling, synthetic-data labeling, Decimal discipline, audit archive, provenance, cohort telemetry, append-only intent, information-blocking awareness, reversibility). Fail on the operational healthcare requirements that depend on correct sensitivity classification (Finding 1's effect on the patient-experience-and-dignity layer).

---

## Logical Flow

The file reads top-to-bottom in pedagogical order matching the pseudocode numbering: Setup, Configuration and Constants (logger, retry config, module-level clients, resource names with deploy-time guardrail, versioning, source-strength tiers, name-change confidence thresholds, per-feature weights, sensitivity classes, default envelopes by class), Helpers (Decimal coercion, name canonicalization, S3 archive, CloudWatch metrics), Mock Identity Store / Reference Data / Patient Preferences / Jurisdictional Overlays, Step 1 (detect name-change candidate from trigger event), Step 2 (resolve candidate with name-change-specific thresholds), Step 3 (apply sensitivity envelope), Step 4 (persist resolved event atomically with audit log), Step 5 (propagate to dependent stores), Step 6 (react to invalidation events), Full Pipeline (`run_pipeline` plus four trigger phases plus five invalidation triggers), Gap to Production.

Each step opens with a short italic prose paragraph that restates the pseudocode step before the code block, matching the cookbook's established pattern. The italic paragraphs name the step's role and the failure mode the step prevents.

The demo runner builds two phases. Phase 1 runs the end-to-end pipeline over four representative trigger events: a court-ordered direct change with high confidence (Trigger 1, Catherine Wilson -> Catherine Hernandez), a self-asserted direct change with medium confidence routed to review (Trigger 2, Maria Garcia -> Garcia-Lopez), an indirect change from a payer eligibility refresh routed to review (Trigger 3, Margaret Chen -> Chen-Patel), and a sensitivity-classified court-ordered change with masked-display preferences (Trigger 4, Alex Mitchell -> Avery Mitchell). Phase 2 exercises the five invalidation triggers (correction, reversal, identity_merge, sensitivity_update, document_upgrade). The trigger choice exercises the three resolution outcome bands (auto-resolve, review-pending, ...rejection is not exercised in the demo) and four of the seven invalidation source types.

The closing prose paragraph after the expected output walks each trigger through the matcher logic with explicit references to which feature scores produced the composite. The narrative connects the trigger setup to the printed output to the architectural intent. **The Trigger 4 narrative claims the envelope honors the patient's masked preference and elevates the audit posture, which is what the code SHOULD do; the actual code does not, per Finding 1.**

---

## What Is Done Particularly Well

Worth calling out explicitly:

- **The deploy-time guardrail covers every resource-name constant.** The for-loop pattern that asserts every constant is non-empty is consistent with recipes 5.4, 5.5, and 5.6. A misconfigured constant produces a clean assertion message rather than a downstream `ValidationException` from boto3 or DynamoDB.
- **The temporal-name-as-event-history posture is implemented faithfully.** Each identity has a current name plus zero or more prior names with effective spans; resolved name changes append to the event log; the computed current state is rebuilt from the log; superseding events update the current state without losing the underlying log. The `_compute_updated_identity_state` function does the right thing structurally.
- **The direct-vs-indirect detection split is correctly encoded.** `direct_signals` checks for explicit prior-name assertion, asserted change date, supporting document, or known direct source types; the resulting `change_type` drives differential threshold routing in `resolve_name_change`. The architectural commitment that indirect detection at the same confidence band requires more demographic alignment than direct detection is preserved through the higher INDIRECT_NAME_CHANGE_HIGH threshold (0.90 vs 0.85).
- **The source-strength-weighted scoring is correctly implemented.** Source-strength tiers (`STRONG`, `MEDIUM`, `MEDIUM-WEAK`, `WEAK`) map to multipliers (1.00, 0.92, 0.82, 0.70) that scale the composite detection score. The architectural commitment that "a court-order PDF beats a verbal patient assertion; both are valid; the resolver behaves differently for each" is preserved through the multiplier.
- **The sensitivity-classification access-control envelope is structurally correct (when the upstream classification works).** The envelope carries patient_preference, jurisdictional_overlays, permitted_display_contexts, permitted_release_scopes, and audit_rules. Patient preferences restrict-only-never-expand on the per-class defaults. The information-blocking obligation is preserved by always including `patient_access_api` in the release scopes regardless of class.
- **The reversibility pipeline covers the seven invalidation source types.** Correction, reversal, identity_merge, identity_unmerge, sensitivity_update, document_upgrade, cross_facility_match_invalidated all have explicit branches with documented actions. The aggregate `identity_name_change_invalidated` event is emitted for downstream consumers to refresh their derived state.
- **The CohortBucket dimension is wired on the operational metrics.** `DetectionScore` and `ResolutionOutcome` carry cohort-bucket dimensions sourced from the identity's cohort axis, which feeds the per-cohort detection-rate and false-acceptance-rate disparity dashboards described in the recipe text.
- **The synthetic identity store covers the major name-change cohorts.** English-traditional (Catherine Wilson, sample marriage-driven change), Spanish-double-surname (Maria Garcia, sample hyphenation-driven change), East-Asian-traditional (Margaret Chen, sample hyphenation-driven change), and a sensitivity-classified case (Alex Mitchell, sample gender-affirming change). A learner sees the major cohort axes exercised in a single demo run.
- **The default envelope per sensitivity class is encoded as configuration.** `DEFAULT_ENVELOPE_BY_CLASS` carries permitted_display_contexts, permitted_release_scopes, and audit_rules per class. The patient-preference layer honors them as restrict-only-never-expand. A learner sees the structural separation between per-class defaults and per-patient overrides cleanly.
- **The Gap to Production section is unusually thorough.** Real Splink-or-`recordlinkage` and `jellyfish` matcher core, real DynamoDB schema with the four tables, TransactWriteItems for atomic event-and-search-index writes, append-only IAM on the event-history table, real S3 supporting-document and audit-archive buckets, Glue and Spark for the periodic-reconciliation pipeline, Step Functions orchestration, idempotency keys on every write, threshold calibration and approval governance, cohort-stratified accuracy monitoring with disparity alarms, three review queues with sensitivity-aware tooling, patient-portal upload flow, patient-preference UI and consent capture, information-blocking-compliant patient-access read path, cross-organizational propagation policy, vital-records integration where available, FHIR-native HealthLake integration, KMS-encrypted everything, VPC + VPC endpoints, CloudTrail data events, Lake Formation, per-event consent metadata, producer-signed envelope on the patient-self-assertion path, compliance and operational ownership. The breadth honestly tells the reader how much operational discipline sits between the recipe and a production deployment.

---

## Closing Assessment

The teaching content is well-organized and faithful to the main recipe in structure, prose framing, and pedagogical ordering. The six pseudocode steps map onto Python functions with helpers in the right places. The DynamoDB + S3 + SQS + EventBridge + CloudWatch API call shapes are correct. The Decimal-at-the-DynamoDB-boundary discipline is consistent. The temporal-name-as-event-history posture, the direct-vs-indirect detection split, the source-strength-weighted scoring, the sensitivity-classification access-control envelope (when classification works), and the seven-source invalidation pipeline are all structurally correct. The `MockReferenceData`, `MockPatientPreferences`, and `MockJurisdictionalOverlays` replacements are reasonable approximations that exercise the major paths.

The ERROR (Finding 1) is the most pedagogically harmful kind of bug because it teaches a sensitivity-aware architecture that is in fact insensitive. Trigger 4 is the trigger whose entire purpose is to exercise the GENDER_AFFIRMING path with elevated audit posture and restricted consumer fan-out; under the bug, every Trigger 4 invocation produces the GENERAL path with the standard 9-consumer fan-out. The patient-experience-and-dignity layer that the recipe spends thousands of words on is silently bypassed. The fix is mechanical (one line in the detection envelope's return dict) and verification is hand-tracing one trigger.

The two WARNINGs are localized and pedagogically meaningful. Finding 2 (the EVENT_HISTORY_TABLE put's ConditionExpression references a non-existent attribute, causing every production put to fail) is masked in the demo by an exception swallow but produces a try/except-and-skip pattern that, copied into production, produces a put-fails-everywhere bug. Finding 3 (documented detection scores diverge from what the toy code computes) does not flip any threshold-band routing in the demo but undermines the credibility of the prose for a careful reader.

The three NOTEs are smaller items: `_classify_sensitivity` drops the jurisdictional_overlays parameter the pseudocode names; the persistence step's TransactWriteItems claim is aspirational; the metric unit is hardcoded.

FAIL verdict per the persona's rule: one ERROR (which automatically means FAIL). Two WARNINGs (under the FAIL threshold of more than three). Three NOTEs.

Recipe 5.7 is the seventh recipe in Chapter 5 and inherits the chapter's operational discipline (graded confidence with deferred review, audit-everything substrate, drift-event fan-out, cohort-stratified telemetry, transactional-outbox eventing, conservative threshold posture, append-only persistence intent) from recipes 5.1-5.6. The longitudinal-name-change-specific behaviors that differentiate it (temporal-name-as-event-history, direct-vs-indirect detection split, source-strength-weighted scoring, sensitivity-classification access-control envelope, multi-source reversibility pipeline) are all structurally present. Closing the ERROR brings the example up to the standard the recipe text claims and is appropriate given that this recipe is the substrate the chapter's remaining recipes (5.8, 5.9, 5.10) implicitly assume exists.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(ERROR)** `detect_name_change_candidate`'s return dict includes `"explicit_sensitivity_class": trigger_event.get("explicit_sensitivity_class")`, so `_classify_sensitivity` can read it from the candidate. Re-run the demo and confirm Trigger 4's printed `sensitivity_class` is `GENDER_AFFIRMING`, the `permitted_display_contexts` is `['treatment_with_clinical_relevance']`, the audit rules include `every_disclosure_logged: True` and `every_query_logged: True`, and the consumer fan-out is the 6-consumer restricted set including `audit_summary_to_patient`.
2. **(WARNING)** The EVENT_HISTORY_TABLE put's ConditionExpression is corrected to reference an attribute that actually exists on the row. Either `attribute_not_exists(identity_id)` (for the append-only-on-new-key intent) or move the optimistic-concurrency check to the IDENTITY_TABLE put with `current_event_version = :ev` (matching the actual attribute name). Verify by provisioning the real DynamoDB tables and confirming no info-level "persist skipped" log lines appear; the persistence path now succeeds end-to-end.
3. **(WARNING)** The documented "Expected console output" detection scores match what the code actually computes. Either re-run the demo and replace the documented scores with the actual values, or adjust the toy scoring to produce the documented values. Hand-trace each trigger after the fix to confirm match.
4. **(NOTE)** `_classify_sensitivity` accepts `jurisdictional_overlays` as a third parameter, even if the demo's logic does not yet consume it. The signature matches the pseudocode.
5. **(NOTE)** The persistence-step try block carries an inline TODO naming the production transactional-outbox pattern (TransactWriteItems on the four tables, drained by a separate Lambda or DynamoDB Streams consumer). Optionally, the code is extended to use `dynamodb.meta.client.transact_write_items` when all real tables exist.
6. **(NOTE)** `_emit_metric` accepts an optional `unit` parameter with a `Count` default; `DetectionScore` and `ResolutionOutcome` (where applicable) emit with `unit="None"` since they publish continuous-score values rather than counts.

After the ERROR fix, re-run the demo end-to-end and confirm:
- Trigger 1 (Catherine Wilson -> Catherine Hernandez): unchanged (GENERAL classification, 9-consumer fan-out, AUTO_RESOLVE_HIGH).
- Trigger 2 (Maria Garcia -> Garcia-Lopez): unchanged (no envelope built, REVIEW_PENDING_DIRECT).
- Trigger 3 (Margaret Chen -> Chen-Patel): unchanged (no envelope built, REVIEW_PENDING_INDIRECT).
- Trigger 4 (Alex -> Avery): now correctly produces sensitivity_class GENDER_AFFIRMING, permitted_display_contexts ['treatment_with_clinical_relevance'], audit_rules with every_*_logged True, restricted 6-consumer fan-out.

The other findings are low-to-medium risk cleanups that improve pedagogical clarity, align the code with the pseudocode's stated signatures and contracts, and reduce the chance that a reader copies the wrong pattern into production. None of them block the demo from running to completion under the demo-mode-tables-not-provisioned path.
