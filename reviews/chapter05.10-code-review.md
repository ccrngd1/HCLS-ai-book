# Code Review: Recipe 5.10 - Deceased Patient Resolution and Record Reconciliation

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-23
**Files reviewed:**
- `chapter05.10-deceased-patient-resolution-reconciliation.md` (main recipe pseudocode)
- `chapter05.10-python-example.md` (Python companion)

**Validation performed:**
- Walked the six pseudocode steps against the Python functions one-to-one
- Verified boto3 API call shapes for S3 (`put_object`), EventBridge (`put_events`), CloudWatch (`put_metric_data`)
- Hand-traced the four demo flows (Flow 1 multi-source corroboration, Flow 2 hidden-duplicate revelation, Flow 3 premature-death-report verification routing, Flow 4 reversal under dual-control)
- Hand-computed the Robert Anderson match scores against the synthetic MPI: state-vital-records event scores 1.00 against both `mrn-3387221` and `mrn-7782441` (full feature match, both at HIGH_CONFIDENCE 0.85 threshold); LADMF event scores 0.88 against the same two records (no address/zip in payload, but ssn_last_4 anchor present), still HIGH_CONFIDENCE
- Hand-traced the date-of-death conflict resolution: both events report `2026-02-08`, no conflict flagged, `consolidated_source_count = 2` after LADMF arrival
- Hand-traced the premature-death-report routing for Flow 3: ssa-ladmf has `premature_death_report_rate_baseline = Decimal("0.013")`, threshold is `Decimal("0.010")`, `0.013 > 0.010` AND `len(prior_events) == 0`, routed to verification queue without applying death status
- Verified the dual-control approval enforcement on `execute_premature_death_report_reversal` (two non-overlapping organizational units required)
- Verified Decimal-at-the-DynamoDB-boundary discipline (no actual DynamoDB writes in demo, but `SOURCE_QUALITY_CLASSIFICATIONS`, `SOURCE_MATCHING_TOLERANCE`, `FEATURE_WEIGHTS`, and `PREMATURE_DEATH_REPORT_VERIFICATION_THRESHOLD` are all Decimals throughout)
- Verified S3 keys do not carry leading slashes (`f"{partition}/{today}/{kid}.json"` pattern)
- Verified deploy-time guardrail asserts every resource-name constant is non-empty
- Verified `_to_decimal` uses `Decimal(str(value))` to avoid float precision issues
- Verified FEATURE_WEIGHTS sum to 1.00 (0.16+0.20+0.25+0.08+0.04+0.20+0.07)

---

## Summary

The Python companion is structurally faithful to the main recipe's six pseudocode steps and the architectural picture (ingest from heterogeneous sources with per-event provenance capture, match against the local MPI under per-source matching tolerance with hidden-duplicate-revelation detection, multi-source reconcile with date-of-death conflict resolution and premature-death-report flagging, apply the death-status update to the MPI atomically, propagate the cascade to per-system consumers on each system's appropriate cadence, handle premature-death-report verification and reversal with dual-control approval). The Decimal-at-the-DynamoDB-boundary discipline is consistent (though no actual DynamoDB writes happen in the demo), S3 keys do not carry leading slashes, the per-source matching tolerance is calibrated separately per source as the recipe text requires, the date-of-death conflict-resolution policy uses per-use-case selection (legal-billing vs clinical-event-timing vs earliest-plausible), and the cascade fan-out drives per-system handlers with per-event acknowledgment to the cascade-ack-store.

That said, this companion ships with one WARNING and several NOTEs. The WARNING concerns a field-naming asymmetry between the recipe text's "Sample inbound death event from a state vital-records FHIR-based feed" example payload (which uses `address_line_1` per the VRDR Implementation Guide approximation) and the Python's normalizer and matcher (both of which read only `address_line`). A reader following the recipe text's normalized-event format and pointing the demo at a payload that uses the VRDR-approximate `address_line_1` field name would silently get an empty address feature on every event. The bug is invisible in the demo because the demo's source records all use `address_line` to match what the normalizer expects.

The NOTEs cover smaller items: Flow 1 silently fires hidden-duplicate-revelation against the third Robert record (`mrn-7782441`) in the synthetic MPI, but the flow's narrative description and printed expected-output don't acknowledge it (the duplicate-revelation pattern is then redundantly demonstrated in Flow 2 with a reset MPI); the LOW_CONFIDENCE branch in `match_death_event_against_mpi` is unreachable because the matcher only includes scored candidates with score >= candidate_acceptance_threshold (which is the same threshold that classifies MEDIUM); the cross-recipe-5.1 fan-out is only triggered by the hidden-duplicate-revelation handler, so non-duplicate-revealing death events don't signal recipe 5.1 even though the recipe text says the deceased-patient signal flows to 5.1; the hidden-duplicate handler signals recipe 5.1 to "merge" but doesn't actually mutate the local MPI to consolidate the duplicate's data, so the merged record's appointments and prescriptions survive untouched while only the survivor's data flows through the cascade; `timedelta` from `datetime` and `Key` from `boto3.dynamodb.conditions` are imported but never used.

---

## Verdict: PASS

No ERRORs. One WARNING (the `address_line` vs `address_line_1` mismatch between the recipe text's normalized-event sample and the Python's normalizer/matcher, both of which read only `address_line`; pointing this code at a payload that uses the VRDR-approximate field name silently drops the address feature). Five NOTEs.

The WARNING and the most-load-bearing NOTEs (Findings 2 and 4) should be addressed before the recipe ships, because they teach a field-naming pattern that fails silently when the wire format follows the recipe text's stated VRDR-approximate sample, and they leave a pedagogical inconsistency where Flow 1's narrative claims one behavior while the code exercises a richer behavior the reader doesn't see called out. None of these block the demo from running to completion or flip any decision band in the documented expected output.

Recipe 5.10 is the tenth and final recipe in Chapter 5 and inherits the chapter's operational discipline (graded confidence with deferred review, audit-everything substrate, drift-event fan-out, transactional-outbox eventing, conservative threshold posture, append-only persistence intent) from recipes 5.1-5.9. The deceased-patient-resolution-specific behaviors that differentiate it (per-source quality classification driving per-source matching tolerance, multi-source reconciliation with date-of-death conflict resolution per use case, premature-death-report verification routing as a hard gate before MPI mutation, hidden-duplicate-revelation as a cross-recipe-5.1 coordination point, per-system cascade with per-system cadence configuration and per-system acknowledgment, premature-death-report reversal pathway with named verifier role and dual-control approval from non-overlapping organizational units, family-experience touchpoints throughout) are all structurally present.

---

## Findings

### Finding 1: `address_line` vs `address_line_1` Field-Naming Mismatch Between Recipe Text's Normalized-Event Sample and the Python's Normalizer and Matcher; A Reader Following the Recipe Text's VRDR-Approximate Sample Format Silently Drops the Address Feature

- **Severity:** WARNING
- **File:** `chapter05.10-python-example.md`
- **Location:** `_normalize_to_common_schema` (line 924); `_compute_per_feature_similarities` address-feature normalization (line 1118); `chapter05.10-deceased-patient-resolution-reconciliation.md` "Sample inbound death event from a state vital-records FHIR-based feed (illustrative; conforms approximately to the VRDR Implementation Guide)"
- **Description:**

  The recipe text's normalized-event sample for the state vital-records FHIR feed shows `address_line_1`:

  ```json
  "normalized_event": {
    "given_name": "Robert",
    "middle_name": "James",
    "family_name": "Anderson",
    "dob": "1942-05-14",
    "sex": "M",
    "address_line_1": "1247 Oak Street",
    "city": "Richmond",
    "state": "VA",
    "zip_code": "23220",
    "date_of_death": "2026-02-08",
    "state_of_death": "VA",
    "cause_of_death_underlying": "I25.10",
    "death_certifier_identifier": "npi-1234567890"
  }
  ```

  The annotation explicitly says "conforms approximately to the VRDR Implementation Guide," so `address_line_1` is the recipe-text-canonical normalized field name.

  But the Python's `_normalize_to_common_schema` reads only `address_line`:

  ```python
  normalized = {
      "given_name":   source_specific_record.get("given_name"),
      "middle_name":  source_specific_record.get("middle_name"),
      "family_name":  source_specific_record.get("family_name"),
      "dob":          source_specific_record.get("dob"),
      "sex":          source_specific_record.get("sex"),
      "address_line": source_specific_record.get("address_line"),
      ...
  }
  ```

  And `_compute_per_feature_similarities` reads only `address_line` from both query and MPI record:

  ```python
  s["address_line"] = _jaro_winkler(
      _normalize_address(query.get("address_line") or ""),
      _normalize_address(mpi_record.get("address_line") or ""))
  ```

  The asymmetry produces three outcomes depending on the inbound source-record format:

  1. **Demo's hand-crafted source records (use `address_line`):** the normalizer reads the field correctly and the address contributes to the match score. Works.
  2. **Recipe-text-approximate VRDR payload (uses `address_line_1`):** the normalizer's `source_specific_record.get("address_line")` returns `None`, the normalized event holds `"address_line": None`, the matcher's `query.get("address_line") or ""` falls through to the empty string, `_normalize_address("")` returns `""`, and the address-feature similarity score is `0.0` for every event regardless of how well the address actually matches.
  3. **Production VRDR ingestion connector that follows the implementation guide:** same silent drop as case 2.

  Demo impact:

  - **Flow 1's state-VR event (`address_line: "1247 Oak St"`):** the normalizer reads it, the matcher normalizes both sides to "1247 oak st", scores 1.0 on address. Composite stays at 1.00. Matches expected output.
  - **Hypothetical VRDR-spec payload (`address_line_1: "1247 Oak Street"`):** the normalizer's `get("address_line")` returns None. The address feature scores 0.0. Composite drops by 0.08 weight: 1.00 - 0.08 = 0.92. Still above the high-confidence threshold of 0.85 for state-vital-records-virginia, so the match still resolves correctly. But for sparser payloads with weaker anchors (e.g., a payload missing ssn_last_4 and zip_code), the address drop can flip a candidate from accepted to rejected.

  Pedagogical impact:

  1. **The recipe text explicitly establishes `address_line_1` as the VRDR-approximate normalized format,** but the Python's normalizer doesn't accept it. A reader following the recipe text's example into a real ingestion pipeline carries this gap forward.
  2. **No error or audit signal indicates the silent drop.** A payload whose `address_line_1` is dropped because the normalizer reads only `address_line` still produces a "successful" normalized event with the address field as `None`; no `WARNING` log line, no rejection, no audit-event hint that the matcher saw an empty address where a populated one existed in the wire format.
  3. **The same field-naming asymmetry was a finding in recipe 5.9's review** (the local handler read `address_line` while the outbound formulator and mock-other-participant handlers used the QTF-canonical `address_line_1`). Recipe 5.10 has the same teaching gap in a different shape: the recipe text's sample payload format diverges from what the code reads.

- **Suggested fix:** Update `_normalize_to_common_schema` to read either field name, with `address_line_1` taking precedence as the recipe-text-canonical name:

  ```python
  normalized = {
      "given_name":   source_specific_record.get("given_name"),
      "middle_name":  source_specific_record.get("middle_name"),
      "family_name":  source_specific_record.get("family_name"),
      "dob":          source_specific_record.get("dob"),
      "sex":          source_specific_record.get("sex"),
      # Accept either the VRDR-approximate address_line_1 (the
      # canonical normalized field name per the recipe text's
      # sample payload) or the legacy address_line. Production
      # ingestion connectors normalize the wire format to the
      # canonical field at the per-source-normalizer layer; the
      # demo collapses the per-source-normalizer step into this
      # function, so the function itself accepts both.
      "address_line": (
          source_specific_record.get("address_line_1")
          or source_specific_record.get("address_line")),
      "city":         source_specific_record.get("city"),
      ...
  }
  ```

  After the fix, hand-trace Flow 1's state-VR event (uses `address_line`): the `or` chain picks up `address_line` and the composite stays at 1.00. Matches expected output. Hand-trace a hypothetical VRDR-spec payload with `address_line_1`: the `or` chain picks up `address_line_1` and the address contributes to scoring as the recipe text's sample-payload format intends. The fix is mechanical and preserves the demo's expected output exactly.

  Alternatively, update the recipe text's sample payload to use `address_line` (matching the Python) and acknowledge inline that production VRDR ingestion connectors translate the VRDR Implementation Guide's field naming to the institution's internal normalized schema before dispatching to the matcher. The inline `or` chain is the right teaching pattern for the demo because it demonstrates the wire-format-tolerance discipline a reader will need in production.

---

### Finding 2: Flow 1 Silently Triggers Hidden-Duplicate-Revelation Against the Third Robert Anderson Record in the Synthetic MPI; The Flow's Narrative and Expected Output Do Not Acknowledge the Coordination With Recipe 5.1, So a Reader Inspecting the Audit Log or Cross-Recipe-5.1 Mock Sees Behavior the Demo Description Does Not Mention

- **Severity:** NOTE
- **File:** `chapter05.10-python-example.md`
- **Location:** `SYNTHETIC_LOCAL_MPI_RECORDS` (line 690 contains the third record `amc-richmond-mrn-7782441` flagged in-line as the duplicate-chain candidate); `run_demo` Flow 1 (line 2125) and Flow 2 (line 2225)
- **Description:**

  The synthetic MPI is initialized with three records:

  ```python
  SYNTHETIC_LOCAL_MPI_RECORDS = [
      {"local_record_id": "amc-richmond-mrn-3387221",  # Robert
       "address_line": "1247 Oak St", ...},
      {"local_record_id": "amc-richmond-mrn-5544102",  # Margaret
       "address_line": "412 Maple Ave", ...},
      # A duplicate-chain candidate for Robert Anderson: same
      # demographics under a different MRN that the institution's
      # internal matching has not surfaced. The death event from
      # an authoritative source will reveal the duplicate.
      {"local_record_id": "amc-richmond-mrn-7782441",  # Robert dup
       "address_line": "1247 Oak Street", ...},
  ]
  ```

  Flow 1 runs first against this full MPI without resetting it. The state-vital-records death event for Robert Anderson scores 1.0 against both `mrn-3387221` and `mrn-7782441` (full feature match: given_name=1.0, family_name=1.0, dob=1.0, address normalized to "1247 oak st" on both sides=1.0, zip=1.0, ssn_last_4=1.0, sex=1.0). Both candidates land HIGH_CONFIDENCE (>= 0.85 threshold for state-vital-records-virginia).

  In `match_death_event_against_mpi`:

  ```python
  high_confidence = [c for c in scored
                        if c["match_confidence_tier"]
                        == HIGH_CONFIDENCE]

  if len(high_confidence) > 1:
      # Hidden-duplicate-revelation case
      duplicate_ids = [c["candidate_record_id"]
                          for c in high_confidence]
      _DEATH_EVENT_LOG[event_id]["resolution_status"] = (
          RES_HIDDEN_DUPLICATE)
      _DEATH_EVENT_LOG[event_id]["all_matched_record_ids"] = (
          duplicate_ids)
      ...
      consolidated_record_id = handle_hidden_duplicate_revelation(
          event_id, duplicate_ids)
      ...
      reconcile_multi_source_death_events(
          event_id, consolidated_record_id)
      return
  ```

  So Flow 1 fires the hidden-duplicate path: the audit log gets a `HIDDEN_DUPLICATE_REVEALED_BY_DEATH_EVENT` event, `cross_recipe_5_1.record_action` records a `merge_duplicate_chain` action with `survivor_record_id="amc-richmond-mrn-3387221"` and `merged_record_ids=["amc-richmond-mrn-7782441"]`, and only after that does `reconcile_multi_source_death_events` run against the survivor.

  The expected output for Flow 1 makes no mention of any of this:

  ```
  vrf event_id:      death-event-state-vi-XXXXXXXXXXXX
  resolution_status: applied
  matched_record_id: amc-richmond-mrn-3387221
  legal_billing_dod: 2026-02-08
  source_count:      1
  ```

  `matched_record_id` is correctly the survivor (because hidden-duplicate sets it after the cross-recipe-5.1 call). `resolution_status: applied` is correct because `apply_death_status_to_mpi` runs after the hidden-duplicate handler and sets the status. So the printed values are accurate. But the flow's narrative description (`"Flow 1: state vital-records death event arrives, then LADMF arrives later for the same patient (corroboration)"`) does not mention duplicate revelation, and Flow 2's narrative (`"Flow 2: same patient appears under two MRNs in the MPI; LADMF death event reveals the duplicate chain"`) is identical to what Flow 1 actually does.

  Flow 2 then resets the MPI to only the two Robert records:

  ```python
  local_mpi = MockLocalMPI([
      r for r in SYNTHETIC_LOCAL_MPI_RECORDS
      if r["local_record_id"] in (
          "amc-richmond-mrn-3387221",
          "amc-richmond-mrn-7782441")
  ])
  _DEATH_EVENT_LOG.clear()
  ```

  And demonstrates the duplicate-revelation pattern again, this time printing the cross-recipe-5.1 fields:

  ```
  cross-recipe-5.1 action: merge_duplicate_chain
  survivor_record_id: amc-richmond-mrn-3387221
  merged_record_ids: ['amc-richmond-mrn-7782441']
  ```

  Pedagogical impact:

  1. **The reader reads Flow 1 as a clean multi-source-corroboration demonstration but the code is also exercising hidden-duplicate-revelation.** A reader inspecting `cross_recipe_5_1.get_actions()` after Flow 1 sees a `merge_duplicate_chain` action that the flow narrative didn't lead them to expect.
  2. **Flow 2 redundantly demonstrates the same code path Flow 1 already exercised.** The pedagogical value of having two flows is reduced when one is silently a superset of the other.
  3. **The cascade fan-out for Flow 1 cancels appointments only for the survivor `mrn-3387221` (3 appointments) but the duplicate `mrn-7782441` retains its `appt-99001` appointment** because the demo's `handle_hidden_duplicate_revelation` records a `merge_duplicate_chain` action on the cross-recipe-5.1 mock but doesn't actually consolidate the duplicate's data into the survivor (see Finding 4). The reader sees `appointments_cancelled: 3` and may not realize the duplicate's appointment is still active.

- **Suggested fix:** Either reset the MPI to exclude the duplicate before Flow 1, or update Flow 1's narrative and expected output to acknowledge the duplicate revelation that occurs.

  **Option A (preferred, isolate Flow 1 from the duplicate):** initialize Flow 1's MPI with only the two non-duplicate records:

  ```python
  # --- Flow 1: multi-source-corroborated death ---
  print("-" * 72)
  print("Flow 1: state vital-records death event arrives, then LADMF")
  print("        arrives later for the same patient (corroboration)")
  print("-" * 72)

  # Reset MPI to a clean state without the duplicate-chain
  # candidate (which is exercised in Flow 2).
  global local_mpi  # already declared at the top of run_demo
  local_mpi = MockLocalMPI([
      r for r in SYNTHETIC_LOCAL_MPI_RECORDS
      if r["local_record_id"] != "amc-richmond-mrn-7782441"
  ])

  vrf_event_id = ingest_death_event_from_source(...)
  ```

  After the fix, Flow 1's matcher returns only `mrn-3387221` at high confidence (the duplicate isn't in the MPI); no hidden-duplicate path fires; `cross_recipe_5_1.get_actions()` is empty after Flow 1; the cascade cancels exactly the 3 appointments for `mrn-3387221`. The flow's narrative description matches what the code does. Flow 2's reset and demonstration of duplicate revelation becomes the unique demonstration of that pattern.

  **Option B (acknowledge the duplicate revelation in Flow 1's narrative):** update Flow 1's printed output to include the cross-recipe-5.1 action and acknowledge it in the narrative:

  ```python
  print(f"  cross-recipe-5.1 action: merge_duplicate_chain "
        f"(hidden-duplicate revealed by the state-VR event)")
  ```

  And add an inline comment that Flow 1 demonstrates two patterns simultaneously: multi-source corroboration AND hidden-duplicate revelation. This is honest about what the demo does but loses the clean separation between Flow 1 and Flow 2.

  Option A is preferred because it preserves the pedagogical-clarity intent: Flow 1 is the corroboration story, Flow 2 is the duplicate story, they don't overlap. The cost is a small MPI reset before Flow 1, mirroring the resets that already exist before Flows 2, 3, and 4.

---

### Finding 3: The LOW_CONFIDENCE Branch in `match_death_event_against_mpi` Is Unreachable Because the Matcher Filters Candidates by `candidate_acceptance_threshold` Before Scoring Them, and `_classify_confidence_tier` Uses the Same Threshold to Distinguish MEDIUM from LOW

- **Severity:** NOTE
- **File:** `chapter05.10-python-example.md`
- **Location:** `match_death_event_against_mpi` step 2C scoring loop (line 1041) and step 2E confidence-tier routing (line 1085); `_classify_confidence_tier` (line 1135)
- **Description:**

  The matcher filters candidates by the acceptance threshold during scoring:

  ```python
  for mpi_record in blocked:
      per_feature_similarities = _compute_per_feature_similarities(
          normalized, mpi_record)
      match_score = _combine_with_fellegi_sunter(
          per_feature_similarities, FEATURE_WEIGHTS)
      if match_score >= tolerance["candidate_acceptance_threshold"]:
          confidence_tier = _classify_confidence_tier(
              match_score, tolerance)
          scored.append({
              "candidate_record_id":
                  mpi_record["local_record_id"],
              "match_score":         match_score,
              "match_confidence_tier": confidence_tier,
          })
  ```

  Records that score below `candidate_acceptance_threshold` are not added to `scored`. So every entry in `scored` has `match_score >= candidate_acceptance_threshold`.

  `_classify_confidence_tier` then uses the same threshold to distinguish MEDIUM from LOW:

  ```python
  def _classify_confidence_tier(match_score: Decimal,
                                    tolerance: dict) -> str:
      if match_score >= tolerance["high_confidence_threshold"]:
          return HIGH_CONFIDENCE
      if match_score >= tolerance["candidate_acceptance_threshold"]:
          return MEDIUM_CONFIDENCE
      return LOW_CONFIDENCE
  ```

  Since every scored entry has `match_score >= candidate_acceptance_threshold`, the function returns either HIGH or MEDIUM for every entry in the scored list. It never returns LOW for an entry that's actually in scored.

  The routing logic at the end of step 2E:

  ```python
  if dominant["match_confidence_tier"] == HIGH_CONFIDENCE:
      # Auto-resolution path: dispatch to the multi-source
      # reconciler (Step 3).
      reconcile_multi_source_death_events(...)
  elif dominant["match_confidence_tier"] == MEDIUM_CONFIDENCE:
      # Verification-queue path: route to the human-review
      # queue.
      ...
  else:
      # Low-confidence: park the event in the no-match
      # archive with the candidate set for audit.
      _DEATH_EVENT_LOG[event_id]["resolution_status"] = (
          RES_LOW_CONF_NO_MATCH)
      _audit_log({
          "event_type": "DEATH_EVENT_LOW_CONFIDENCE_NO_MATCH",
          ...
      })
  ```

  The `else` branch is unreachable. `RES_LOW_CONF_NO_MATCH` and the `DEATH_EVENT_LOW_CONFIDENCE_NO_MATCH` audit-event type are dead code.

  Demo impact: none. The demo never exercises the dead branch because the demo's payloads either match high-confidence (Flow 1, Flow 2, Flow 3) or no-match (a hypothetical `len(scored) == 0` path that the demo doesn't exercise either).

  Pedagogical impact:

  1. **A reader inspecting the matcher routing sees three branches but only two are reachable.** The third branch's existence implies the code handles a case that the rest of the matcher's structure doesn't actually produce.
  2. **A reader extending the demo with a separate "below acceptance but above some lower-bound" routing tier** (e.g., a "watchlist" tier for candidates that score below acceptance but might be worth tracking) inherits a precedent that doesn't actually work. The reader might add a new "watchlist" classification by lowering the candidate-evaluation threshold below `candidate_acceptance_threshold` and adding the records to scored anyway, then expect the `else` branch to handle them; but the `else` branch was never actually exercising the LOW path.
  3. **The pseudocode in the main recipe (`match_death_event_against_mpi`) does include a low-confidence routing decision,** so the Python is faithful to the pseudocode in shape. The dead-code finding is in the Python's specific implementation, not in the pseudocode-to-Python consistency.

- **Suggested fix:** Either remove the unreachable branch, or restructure the matcher to actually produce candidates below the acceptance threshold and route them through the `else` branch.

  **Option A (remove the unreachable branch):**

  ```python
  if dominant["match_confidence_tier"] == HIGH_CONFIDENCE:
      reconcile_multi_source_death_events(
          event_id, dominant["candidate_record_id"])
  else:
      # Medium-confidence: route to the human-review queue.
      # The matcher only adds candidates with score >=
      # candidate_acceptance_threshold to the scored list, so
      # every dominant candidate is HIGH or MEDIUM here. There
      # is no LOW path because LOW candidates were filtered
      # out at scoring time.
      _DEATH_EVENT_LOG[event_id]["resolution_status"] = (
          RES_QUEUED_FOR_REVIEW)
      _VERIFICATION_QUEUE.append({...})
      ...
  ```

  And remove `RES_LOW_CONF_NO_MATCH` from the resolution-status enumeration.

  **Option B (restructure to produce LOW candidates):** lower the candidate-evaluation gate to a "watchlist" threshold that's strictly below `candidate_acceptance_threshold`, add a `WATCHLIST_THRESHOLD` constant, and route candidates above the watchlist but below acceptance to the LOW branch:

  ```python
  WATCHLIST_THRESHOLD = Decimal("0.40")  # Below acceptance but
                                          # worth audit retention.

  for mpi_record in blocked:
      ...
      if match_score >= WATCHLIST_THRESHOLD:
          confidence_tier = _classify_confidence_tier(
              match_score, tolerance)
          scored.append({...})
  ```

  Then the `else` branch in routing actually fires for watchlist candidates, and `RES_LOW_CONF_NO_MATCH` becomes a meaningful state.

  Option A is preferred because the demo's pedagogical focus isn't watchlist tracking; the dead branch is just clutter that suggests a routing path the matcher doesn't produce. Removing it tightens the matcher's logic without losing teaching value.

---

### Finding 4: Cross-Recipe-5.1 Is Only Signaled From the Hidden-Duplicate-Revelation Handler; Non-Duplicate-Revealing Death Events Don't Signal Recipe 5.1 Even Though the Recipe Text Says the Deceased-Patient Signal Flows to 5.1

- **Severity:** NOTE
- **File:** `chapter05.10-python-example.md`
- **Location:** `propagate_to_downstream_systems` cascade handler list (line 1419); `_summarize_cascade_completeness` expected-consumers set (line 1657); `chapter05.10-deceased-patient-resolution-reconciliation.md` "Cross-recipe coordination signals are first-class architectural concerns" paragraph
- **Description:**

  The recipe text says:

  > The deceased-patient signal flows to recipe 5.1 (the consolidated record's death status drives the duplicate-resolution decisions that follow), recipe 5.5 (the cross-facility matcher suppresses deceased-patient candidates per the use-case-appropriate handling), recipe 5.7 (the longitudinal-name-change history is closed at the date of death; the post-death sensitivity classification is applied), recipe 5.8 (the privacy-preserving-linkage encoded payloads are updated to reflect the deceased status with the appropriate freshness signaling), and recipe 5.9 (the cross-network match infrastructure suppresses deceased-patient candidates with appropriate per-jurisdiction handling).

  Five recipes are named: 5.1, 5.5, 5.7, 5.8, 5.9.

  But the Python's cascade handler list signals only four of them:

  ```python
  cascade_handlers = [
      ("appointment-system",
       cascade_appointment_cancellation),
      ("prescription-system",
       cascade_active_prescription_review),
      ("outreach-platform",
       cascade_communication_path_switch),
      ("billing-system",
       cascade_billing_episode_closure),
      ("patient-portal",
       cascade_portal_access_handler),
      ("care-management",
       cascade_care_management_panel_removal),
      ("analytics-platform",
       cascade_analytics_platform_handler),
      ("cross-recipe-5.5",
       lambda *args: cascade_cross_recipe_signal("5.5", *args)),
      ("cross-recipe-5.7",
       lambda *args: cascade_cross_recipe_signal("5.7", *args)),
      ("cross-recipe-5.8",
       lambda *args: cascade_cross_recipe_signal("5.8", *args)),
      ("cross-recipe-5.9",
       lambda *args: cascade_cross_recipe_signal("5.9", *args)),
  ]
  ```

  No `cross-recipe-5.1` entry. The `_summarize_cascade_completeness` helper explicitly excludes it from expected consumers:

  ```python
  expected_consumers = set(CASCADE_CONSUMER_CONFIG.keys()) - {
      "cross-recipe-5.1"  # handled in hidden-duplicate flow
  }
  ```

  The inline comment correctly identifies that cross-recipe-5.1 is signaled only from the hidden-duplicate-revelation flow:

  ```python
  def handle_hidden_duplicate_revelation(
          event_id: str, duplicate_ids: list) -> str:
      ...
      cross_recipe_5_1.record_action({
          "action":       "merge_duplicate_chain",
          ...
      })
  ```

  But this means a death event that does NOT reveal hidden duplicates (e.g., Flow 3's premature-death-report case for Margaret Chen, or the LADMF event in Flow 1 if the MPI had no duplicate Robert record) doesn't signal recipe 5.1 at all.

  The recipe text says recipe 5.1 receives the deceased-patient signal so that "the consolidated record's death status drives the duplicate-resolution decisions that follow." The implication is that future duplicate-resolution work in 5.1 should know which records are deceased so the merge logic handles deceased-patient identity merges differently from live-patient merges. That's a use case independent of hidden-duplicate-revelation: any deceased-patient signal should reach 5.1, not just signals tied to revealed duplicates.

  Demo impact: in the demo, Flow 1 fires hidden-duplicate (per Finding 2) so cross-recipe-5.1 gets signaled there. Flow 2 explicitly fires hidden-duplicate. Flow 3 doesn't apply the death status (it's routed to verification queue) so no cross-recipe signal at all. Flow 4's reversal does fan out via `propagate_reversal_to_downstream_systems`, which iterates `CASCADE_REGISTRY` (which DOES include `cross-recipe-5.1`):

  ```python
  for consumer_id, consumer in CASCADE_REGISTRY.items():
      consumer.record_action({
          "action":          "reverse_deceased_status",
          ...
      })
  ```

  So cross-recipe-5.1 receives a `reverse_deceased_status` action during Flow 4 even though it never received a `deceased_patient_resolved` action via the standard cascade. That's an asymmetry: recipe 5.1 knows about reversals but not about original applications (unless they revealed duplicates).

  Pedagogical impact:

  1. **The recipe text and the code disagree on whether recipe 5.1 is a standard cascade consumer.** The recipe text lists 5.1 alongside 5.5, 5.7, 5.8, 5.9; the code excludes 5.1 with the comment "handled in hidden-duplicate flow."
  2. **A reader extending the demo to add a downstream recipe 5.1 deceased-aware merge logic** would expect the deceased signal to arrive on every death event, not just hidden-duplicate events. The current code structure forces the reader to either (a) add 5.1 to the cascade list, (b) accept that 5.1 only learns about deceased patients when their death event reveals a duplicate, or (c) infer the deceased status indirectly from the MPI on every merge attempt.
  3. **The reversal cascade DOES signal 5.1 (via `CASCADE_REGISTRY` iteration) so the asymmetry is more confusing than a clean "5.1 isn't a cascade consumer" rule would be.** Either 5.1 is a cascade consumer or it isn't; the current code treats it as one for reversals but not for applications.

- **Suggested fix:** Add `cross-recipe-5.1` to the standard cascade handler list and remove the exclusion in `_summarize_cascade_completeness`:

  ```python
  cascade_handlers = [
      ...,
      ("cross-recipe-5.1",
       lambda *args: cascade_cross_recipe_signal("5.1", *args)),
      ("cross-recipe-5.5",
       lambda *args: cascade_cross_recipe_signal("5.5", *args)),
      ("cross-recipe-5.7",
       lambda *args: cascade_cross_recipe_signal("5.7", *args)),
      ...
  ]
  ```

  And:

  ```python
  expected_consumers = set(CASCADE_CONSUMER_CONFIG.keys())
  ```

  After the fix, every applied death event (whether or not it revealed a duplicate) signals recipe 5.1 with a `deceased_patient_signal_for_recipe_5.1` action. The hidden-duplicate-revelation handler still emits its own `merge_duplicate_chain` action separately for the merge coordination; the two signals serve different purposes (the standard cascade tells 5.1 "this patient is deceased going forward," the hidden-duplicate handler tells 5.1 "merge these specific records atomically with this death event").

  Alternatively, update the recipe text to clarify that recipe 5.1 receives the deceased-patient signal only via the hidden-duplicate-revelation handler, and that 5.1's deceased-aware logic operates by re-reading the MPI's deceased_status field on every merge attempt rather than by subscribing to a separate event stream. This is a documentation-only fix that aligns the recipe text with the current code behavior.

  Adding 5.1 to the standard cascade is the architecturally cleaner choice because it matches the symmetric pattern the other cross-recipe consumers (5.5, 5.7, 5.8, 5.9) already follow.

---

### Finding 5: `handle_hidden_duplicate_revelation` Records a `merge_duplicate_chain` Action on the Cross-Recipe-5.1 Mock but Doesn't Mutate the Local MPI to Consolidate the Duplicate's Data; The "Merged" Record's Appointments and Prescriptions Survive Untouched After the Cascade Runs

- **Severity:** NOTE
- **File:** `chapter05.10-python-example.md`
- **Location:** `handle_hidden_duplicate_revelation` (line 1170); the cascade handlers that read from the MPI (`cascade_appointment_cancellation` line 1480, `cascade_active_prescription_review` line 1535, `cascade_billing_episode_closure` line 1617)
- **Description:**

  The hidden-duplicate handler "merges" by recording a single action on the cross-recipe-5.1 mock:

  ```python
  def handle_hidden_duplicate_revelation(
          event_id: str, duplicate_ids: list) -> str:
      ...
      survivor_id = sorted(duplicate_ids)[0]
      merged_into = [d for d in duplicate_ids if d != survivor_id]

      # Signal recipe 5.1 (the cross-recipe consumer for internal
      # duplicates).
      cross_recipe_5_1.record_action({
          "action":       "merge_duplicate_chain",
          "event_id":     event_id,
          "survivor_record_id": survivor_id,
          "merged_record_ids":  merged_into,
          "reason":       "death_event_revealed_duplicates",
      })
      ...
      return survivor_id
  ```

  The function returns `survivor_id` but does not mutate the local MPI. The duplicate record (`mrn-7782441` in Flow 2) retains its original fields:

  ```python
  {"local_record_id": "amc-richmond-mrn-7782441",
   "active_appointments": [
       {"appointment_id": "appt-99001",
        "scheduled_for": "2026-03-15T11:00:00Z",
        "type": "specialty_consult"},
   ],
   ...}
  ```

  When `apply_death_status_to_mpi` runs against the survivor, it updates the survivor's deceased_status. The duplicate's record is untouched: its `appt-99001` appointment remains active, and if Flow 2 had checked `local_mpi.get("amc-richmond-mrn-7782441")`, the appointment would still be there.

  The cascade Lambdas (cascade_appointment_cancellation, cascade_active_prescription_review, cascade_billing_episode_closure) read from the local MPI by `matched_record_id`:

  ```python
  def cascade_appointment_cancellation(
          event_id, matched_record_id, date_of_death):
      record = local_mpi.get(matched_record_id) or {}
      future_appointments = [...]
      ...
  ```

  They read only the survivor's data, never the duplicate's. So the duplicate's `appt-99001` is never cancelled, never appears in the `future_appointments` list, never gets a `cancellation_reason: "deceased_patient"` action.

  In production, the recipe-5.1 merge would consolidate the duplicate's appointments, prescriptions, billing episodes, etc. into the survivor's record before the cascade runs (or the cascade would iterate the entire merged-record-set, picking up data from both records). The demo's "merge" is just a record_action call; no consolidation actually happens.

  Demo impact: in Flow 1's full-MPI run, the cascade reports `appointments_cancelled: 3` (for `mrn-3387221`'s 3 appointments). The duplicate `mrn-7782441`'s `appt-99001` is not cancelled. A reader running the demo and inspecting the appointment_system actions would see exactly 3 cancellations for Flow 1 even though the recipe text and the cross-recipe-5.1 action description claim the duplicate chain was merged.

  In Flow 2 (which explicitly resets to only the two Robert records), the cascade still runs only against `mrn-3387221`, so `mrn-7782441`'s `appt-99001` is still active afterward.

  Pedagogical impact:

  1. **The demo's narrative says "duplicate merged" but the data isn't actually consolidated.** A reader extending the demo to verify post-cascade state would find the duplicate record's appointments still active.
  2. **The recipe text frames hidden-duplicate revelation as an atomic coordination with recipe 5.1, where the resolution applies to a "consolidated record":** "The institution then has both a deceased-patient resolution to apply and a duplicate-patient resolution (recipe 5.1) to apply at the same time, and the operational discipline has to handle both atomically." The demo's implementation breaks this atomicity: the death status is applied only to the survivor, the duplicate is left in a half-merged state.
  3. **A reader accustomed to chapter 5's "transactional discipline prevents the operational anomaly where one part of the resolution is applied and the other is not" framing** (from recipe 5.10's main pseudocode in step 4) would expect the demo to demonstrate the atomic consolidation. The demo's `handle_hidden_duplicate_revelation` doesn't.

- **Suggested fix:** Either implement the consolidation in `handle_hidden_duplicate_revelation` to mutate the survivor's record, or update the function's docstring and the recipe-text framing to acknowledge that the actual consolidation is delegated to recipe 5.1's pipeline (which the demo doesn't implement) and the demo's signal is the trigger.

  **Option A (implement consolidation in the handler):**

  ```python
  def handle_hidden_duplicate_revelation(
          event_id: str, duplicate_ids: list) -> str:
      """..."""
      survivor_id = sorted(duplicate_ids)[0]
      merged_into = [d for d in duplicate_ids if d != survivor_id]

      # Consolidate the duplicate's appointments, prescriptions,
      # and billing episodes into the survivor. Production
      # delegates this consolidation to recipe 5.1's merge
      # pipeline; the demo performs an inline consolidation so
      # the cascade-propagation step sees the consolidated state.
      survivor = local_mpi.get(survivor_id) or {}
      consolidated_appointments = list(
          survivor.get("active_appointments") or [])
      consolidated_prescriptions = list(
          survivor.get("active_prescriptions") or [])
      consolidated_episodes = list(
          survivor.get("open_billing_episodes") or [])

      for merged_id in merged_into:
          merged_record = local_mpi.get(merged_id) or {}
          consolidated_appointments.extend(
              merged_record.get("active_appointments") or [])
          consolidated_prescriptions.extend(
              merged_record.get("active_prescriptions") or [])
          consolidated_episodes.extend(
              merged_record.get("open_billing_episodes") or [])

      local_mpi.update_record(survivor_id, {
          "active_appointments":   consolidated_appointments,
          "active_prescriptions":  consolidated_prescriptions,
          "open_billing_episodes": consolidated_episodes,
      })

      cross_recipe_5_1.record_action({...})
      ...
      return survivor_id
  ```

  After the fix, Flow 1's `appointments_cancelled` count would be 4 (3 from the survivor + 1 from the merged duplicate), Flow 2's expected output would similarly show the consolidated count.

  **Option B (acknowledge the gap in docstring and Gap to Production):** add an inline comment in `handle_hidden_duplicate_revelation` that the function only emits the merge signal and does not actually consolidate the records, and add to the Gap to Production section:

  > **Real recipe-5.1 merge pipeline integration.** The demo's `handle_hidden_duplicate_revelation` records a merge action on the cross-recipe-5.1 mock but does not actually consolidate the duplicate's appointments, prescriptions, or billing episodes into the survivor. Production delegates the consolidation to recipe 5.1's merge pipeline, which mutates the MPI atomically with the death-status application. The demo's cascade therefore acts only on the survivor's pre-merge data; a production deployment would see the cascade act on the consolidated post-merge data.

  Option B is preferable for a teaching snippet because the consolidation logic is recipe 5.1's domain rather than recipe 5.10's, and the demo's pedagogical focus is the deceased-patient pipeline rather than the duplicate-merge pipeline. The fix is documentation-only and aligns the demo's framing with what it actually does.

---

### Finding 6: `timedelta` From `datetime` and `Key` From `boto3.dynamodb.conditions` Are Imported but Never Used

- **Severity:** NOTE
- **File:** `chapter05.10-python-example.md`
- **Location:** Imports block (lines 11-19)
- **Description:**

  The Configuration and Constants section imports two symbols that the demo never uses:

  ```python
  from datetime import datetime, timedelta, timezone
  ...
  from boto3.dynamodb.conditions import Key
  ```

  `timedelta` is not referenced anywhere in the file. `Key` is the DynamoDB query-condition builder for partition-key and sort-key expressions; it would be used in a real `dynamodb_table.query(KeyConditionExpression=Key("event_id").eq(...))` call, but the demo never calls a real DynamoDB query (the death-event-log query is implemented as in-memory dict iteration in `_query_prior_events_for_record`).

  Demo impact: none. Unused imports compile and don't affect runtime behavior. Static analyzers (pyflakes, ruff) flag them but the demo doesn't run such tools.

  Pedagogical impact:

  1. **The unused `Key` import suggests a DynamoDB query path that the demo doesn't implement.** A reader seeing the import might expect a `dynamodb_table.query(...)` call somewhere; the demo's `_query_prior_events_for_record` function uses dict iteration instead.
  2. **The unused `timedelta` import is just clutter.** It's not load-bearing for any teaching point.

- **Suggested fix:** Either drop the unused imports or use them where the demo currently uses raw arithmetic.

  **Option A (drop the unused imports):**

  ```python
  from datetime import datetime, timezone
  ...
  # boto3.dynamodb.conditions.Key is not used in the demo because
  # the death-event-log query is implemented as in-memory dict
  # iteration. Production uses Key() with DynamoDB query for the
  # GSI-on-matched_record_id lookup; the demo simplifies.
  ```

  **Option B (use `Key` in the prior-events query helper to model the production pattern):**

  ```python
  def _query_prior_events_for_record(matched_record_id: str,
                                            exclude_event_id: str = None
                                            ) -> list:
      """Query prior death events that resolved against the same
      matched record. Production indexes the death-event-log by
      matched_record_id with a GSI; the production query is:

          death_event_log_table.query(
              IndexName="matched-record-id-index",
              KeyConditionExpression=Key("matched_record_id").eq(
                  matched_record_id),
          )

      The demo iterates the in-memory dict instead."""
      return [...]
  ```

  Option A is preferred for cleanliness; Option B preserves the import as a teaching anchor for the production query pattern. Either approach resolves the unused-import smell.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Function | Consistent? |
|----------------|-----------------|-------------|
| `ingest_death_event_from_source(source_id, source_specific_record)` | `ingest_death_event_from_source` plus `_normalize_to_common_schema` | Mostly yes (1A loads the per-source schema definition; 1B normalizes the source-specific record to the common schema; 1C captures the per-event provenance with source-quality classification, source submission timestamp, institution ingestion timestamp, supporting-evidence reference; 1D persists into the death-event-log; 1E dispatches to the matcher). **The `address_line_1` vs `address_line` mismatch per Finding 1 is a pseudocode-to-Python consistency issue: the recipe text's normalized-event sample uses `address_line_1` but the Python's normalizer reads only `address_line`.** |
| `match_death_event_against_mpi(event_id)` | `match_death_event_against_mpi` plus `_compute_per_feature_similarities`, `_combine_with_fellegi_sunter`, `_classify_confidence_tier` | Mostly yes (2A loads the per-source matching tolerance; 2B candidate generation through MPI blocking; 2C per-candidate scoring with Fellegi-Sunter weighted-average over per-feature similarities; 2D hidden-duplicate detection routing to `handle_hidden_duplicate_revelation`; 2E confidence-tier routing to multi-source-reconciler / verification-queue / no-match). **The LOW_CONFIDENCE branch in step 2E is unreachable per Finding 3.** **The middle_name feature is in the source record and the MPI but not in `_compute_per_feature_similarities`; the matcher ignores middle name.** |
| `reconcile_multi_source_death_events(event_id, matched_record_id)` | `reconcile_multi_source_death_events` plus `_compute_consolidated_dates`, `_query_prior_events_for_record`, `_summarize_dates` | Yes (3A applies the date-of-death-conflict-resolution policy with per-use-case selection: legal-billing-date for state-vital-records authoritative source, clinical-event-timing-date for ehr-internal, earliest-plausible-date for cohort-survival; 3B premature-death-report detection: source's `premature_death_report_rate_baseline > PREMATURE_DEATH_REPORT_VERIFICATION_THRESHOLD` AND `len(prior_events) == 0` routes to verification queue; 3C builds consolidated death-event view; 3D dispatches to MPI-update handler). The threshold-exceeded date-of-death conflict path is correctly distinct from the premature-death-report path. |
| `apply_death_status_to_mpi(event_id, matched_record_id, consolidated_view)` | `apply_death_status_to_mpi` | Mostly yes (4A loads current MPI record; 4B builds updated record state with deceased_status and death_event_history append; 4C executes the transactional write with rollback on exception; 4D emits the `deceased_patient_resolved` EventBridge event with the consolidated date-of-death and per-source provenance; 4E drives the downstream cascade via `propagate_to_downstream_systems`). The transactional discipline is illustrative (the demo's MockLocalMPI doesn't actually wrap the writes in a database transaction; `pre_update_snapshot` is captured but never used to roll back on the in-memory dict). The recipe text's commitment to atomicity is honored in shape; the demo's MockLocalMPI doesn't actually need transaction semantics because there's no concurrent writer. |
| `cascade_*` per-system handlers | `cascade_appointment_cancellation`, `cascade_active_prescription_review`, `cascade_communication_path_switch`, `cascade_billing_episode_closure`, `cascade_portal_access_handler`, `cascade_care_management_panel_removal`, `cascade_analytics_platform_handler`, `cascade_cross_recipe_signal` | Mostly yes. Each handler reads the matched_record_id's current state from the MPI, applies the system-specific behavior change (cancel appointment, cancel auto-refill, suppress default communications, close billing episode, suspend patient account, remove from active panel, mark for deceased handling), and emits a per-system acknowledgment to `_CASCADE_ACK_STORE`. **The cross-recipe-5.1 signal is missing from the standard cascade per Finding 4.** **The hidden-duplicate handler doesn't actually consolidate the duplicate's data into the survivor before the cascade runs per Finding 5, so the cascade acts only on the survivor's pre-merge data.** |
| `execute_premature_death_report_reversal(event_id, matched_record_id, verifier_identity, reversal_reason)` | `execute_premature_death_report_reversal` plus `queue_dual_control_approval`, `_verify_dual_control_approval`, `_validate_verifier_authorization`, `propagate_reversal_to_downstream_systems` | Yes (6A validates the verifier's authorization with role membership check; 6B validates the dual-control approval requiring two operators from non-overlapping organizational units; 6C loads current MPI record; 6D applies the reversal restoring deceased_status to None and annotating the death-event history with the reversal context; 6E executes the transactional reversal; 6F emits the `deceased_status_reversed` EventBridge event; propagates to downstream systems via `propagate_reversal_to_downstream_systems` which iterates `CASCADE_REGISTRY` and records `reverse_deceased_status` actions on every consumer). The audit-and-attribution discipline is correct: every step is audit-logged with the verifier identity summary. |

Intentional deviations clearly framed:

- The real LADMF subscription, the real state-vital-records FHIR feed integration, the real CMS Medicare Beneficiary Database integration, the real EHR death-of-patient event consumption, and the real family-reported-death intake call-center capture are all named in the Heads-up as out-of-scope.
- The Step Functions orchestration, multiple Lambdas, multiple Glue jobs, the EventBridge cross-account fan-out, and the SQS-driven cascade workers collapse into a single Python file. Documented at the top.
- The `MockLocalMPI`, `MockDownstreamSystem`, in-memory dicts (`_DEATH_EVENT_LOG`, `_VERIFICATION_QUEUE`, `_CASCADE_ACK_STORE`, `_DUAL_CONTROL_APPROVALS`) replacements for production dependencies are clearly framed.
- The hand-rolled `_jaro_winkler` stands in for `jellyfish`. Documented inline.
- The Fellegi-Sunter combiner is a weighted-average rather than the production log-likelihood-ratio implementation. Documented inline.
- The cohort-stratified-accuracy-monitoring is mentioned in the Gap to Production section but not exercised in the demo. Acknowledged.
- The HIPAA-posthumous-protection-period access-control engine and the personal-representative-portal Cognito IdP are described in the Gap to Production section but not implemented in the demo. Acknowledged.

The substantive deviations (Findings 1, 2, 4, 5) are the consistency gaps that carry pedagogical consequence. The acknowledged simplifications (mock MPI, mock downstream systems, in-memory tables, hand-rolled approximate string matching, weighted-average Fellegi-Sunter) are clearly framed.

---

## AWS SDK Accuracy

| API Call | Method | Notes |
|----------|--------|-------|
| S3 PutObject | `s3_client.put_object(Bucket=..., Key=key, Body=body, ServerSideEncryption="aws:kms")` | Correct shape. Body is bytes-encoded JSON with `default=str` to handle Decimal. Keys use `{partition}/{date}/{key_id}.json` with no leading slashes. The `_archive_to_s3` helper formats keys consistently. **Note:** `ServerSideEncryption="aws:kms"` is specified without `SSEKMSKeyId`, which would default to the AWS-managed `aws/s3` key rather than a customer-managed key. Production should pass `SSEKMSKeyId` per the recipe text's "customer-managed KMS keys at rest" commitment. The demo's omission is a pedagogical simplification. |
| EventBridge PutEvents | `eventbridge_client.put_events(Entries=[{Source, DetailType, EventBusName, Detail}])` | Correct shape. `Detail` is JSON-serialized with `default=str` to handle Decimal. Two detail-types emitted: `deceased_patient_resolved` from `apply_death_status_to_mpi`, and `deceased_status_reversed` from `execute_premature_death_report_reversal`. The recipe text mentions additional event types (`hidden_duplicate_revealed`, `personal_representative_authorized`, `posthumous_access_granted`, `cross_source_disagreement_flagged`) but the demo emits only the resolved and reversed events; the rest are acknowledged as Gap to Production. |
| CloudWatch PutMetricData | `cloudwatch_client.put_metric_data(Namespace, MetricData=[{MetricName, Value, Unit, Dimensions}])` | Correct shape. Ten metric names appear: `DeathEventIngested`, `HiddenDuplicateRevealed`, `DeathEventNoMatch`, `DeathEventQueuedForReview`, `DateOfDeathConflictFlagged`, `PrematureDeathReportFlagged`, `DeathEventReconciled`, `DeathEventApplied`, `AppointmentsCancelled`, `DeathEventReversed`. **`Unit="Count"` is hardcoded in `_emit_metric` but is correct for all current emissions** (every metric is a count, not a rate; the demo doesn't emit any 0-1 rate values). Unlike recipes 5.7, 5.8, 5.9 where the hardcoded unit was a finding because of rate metrics, recipe 5.10's metric set is uniformly count-typed and the hardcoding is appropriate. |
| KMS / DynamoDB / SQS / Step Functions / Secrets Manager | (referenced in setup; not actually called) | The Setup section names IAM permissions on `death-event-log`, `verification-queue`, `cascade-ack-store`, `personal-representative-authorization` DynamoDB tables; per-source landing-zone and audit-archive S3 buckets; cascade-acknowledgment and verification-review SQS queues; deceased-patient-events EventBridge bus; per-source-credentials Secrets Manager secrets; customer-managed KMS keys; deceased-patient-resolution-orchestrator Step Functions state machine. The demo does not call these services; the in-memory dicts and best-effort S3/EventBridge/CloudWatch calls stand in. The boto3 client setup is correct (clients constructed at module level with adaptive retries via `BOTO3_RETRY_CONFIG`). |

The SDK-level concerns are minimal. All API surfaces named in the demo are current and correct. The KMS-key-id omission on S3 PutObject is the only architectural gap, and it's acknowledged in the recipe text's "customer-managed KMS keys" commitment as something production tightens.

---

## DynamoDB and Data Type Check

- `_to_decimal` correctly uses `Decimal(str(value))` and short-circuits on already-Decimal inputs.
- `_serialize_for_dynamodb` recursively walks dicts, lists, tuples, and sets; converts floats to Decimal. The pattern is safe for serializing match scores and similarity scores into DynamoDB-bound payloads, though the demo never actually writes to DynamoDB.
- `SOURCE_QUALITY_CLASSIFICATIONS` constants are constructed as Decimals (`Decimal("0.013")`, `Decimal("0.78")`, etc.) at module load time. `SOURCE_MATCHING_TOLERANCE` thresholds, `FEATURE_WEIGHTS`, and `PREMATURE_DEATH_REPORT_VERIFICATION_THRESHOLD` are also Decimals.
- Match scores returned from `_combine_with_fellegi_sunter` are Decimals throughout. Comparison with the threshold constants is Decimal-vs-Decimal. No int/float coercion issues.
- Per-feature similarity scores from `_compute_per_feature_similarities` are Decimals (`Decimal("1.0")`, `Decimal("0.0")`, or `_jaro_winkler` Decimal output). Correct.
- The `_jaro_winkler` computation does Decimal arithmetic throughout. Returns Decimal.
- `DATE_CONFLICT_THRESHOLD_DAYS = 7` is a Python int, not a Decimal; this is correct because it's used only in `_days_between(...) > DATE_CONFLICT_THRESHOLD_DAYS` integer comparisons, never persisted to DynamoDB.
- The CloudWatch `Value` parameter uses `float(...)` casts where needed. Correct (CloudWatch accepts native floats).
- The EventBridge `Detail` flows through `json.dumps(..., default=str)`, which handles Decimal serialization.
- The S3 archive flow through `json.dumps(payload, default=str)` similarly handles Decimals.

The Decimal discipline is correct. No type-handling bugs. The demo never actually writes to DynamoDB (all persistence is in-memory), so the Decimal discipline is preserved as a teaching pattern rather than a runtime requirement.

---

## S3 and Credentials Check

- The example uses S3 only for archive writes (`AUDIT_ARCHIVE_BUCKET`). No leading slash on any key. The `_archive_to_s3` helper formats keys as `f"{partition}/{today}/{kid}.json"` where `partition` is a non-slashed prefix.
- The deploy-time guardrail covers every resource-name constant via the `for _name, _value in [...]: assert _value` loop. **No constant can silently be empty.** Same discipline as recipes 5.4-5.9.
- No hardcoded credentials. Module-level boto3 clients use the documented environment credential chain.
- The IAM permissions list in Setup matches the API surface used by the code (DynamoDB GetItem/PutItem/UpdateItem/Query/TransactWriteItems on the four named tables, S3 PutObject/GetObject on the per-source landing-zone and audit-archive buckets, SQS SendMessage/ReceiveMessage on the cascade-acknowledgment and verification-review queues, EventBridge PutEvents on the deceased-patient-events bus, CloudWatch PutMetricData, KMS Decrypt/GenerateDataKey on the customer-managed keys, Secrets Manager GetSecretValue on the rotation-pinned secrets, Cognito AdminGetUser for personal-representative authentication, Step Functions StartExecution/DescribeExecution).
- The Setup section explicitly names that "tutorial-level permissions above are fine for learning and will fail any serious IAM review" with the right framing about per-Lambda role scoping (death-event-matcher Lambda has read-only access to the local MPI; mutations go through mpi-update-handler Lambda; premature-death-report-verification-router Lambda has scoped access to the verification queue and audit archive but no MPI write access; per-system-cascade Lambdas have scoped access to their respective operational systems).
- The PHI framing is clear: the death-event payload carries the patient's name, DOB, SSN-last-4, address, the date and cause of death, and per-source supporting-evidence references all of which should not leak through logs. The logger setup correctly limits logging to structural metadata (event_id, source_id, matched_record_id summary, decision band, resolution status), and the `_summarize_event_for_audit` helper records WHAT features were present (not their values), the payload's structural shape, and a content hash for dispute resolution.
- The Heads-up section names the synthetic-data discipline: "The synthetic patients, sources, organizations, and identifiers in the demo are fictional; the names, DOBs, addresses, and other identifiers are obviously made-up and should not match anyone real."
- The Gap to Production section names the LADMF NTIS certification or authorized-intermediary subscription as a multi-month operational program, the per-jurisdiction state-vital-records-feed onboarding per data-use agreement, the per-payer-death-feed integration per data-use agreement, the family-reported-death intake operational discipline with bereavement-aware-communications training, the HIPAA-posthumous-protection-period access-control engine over the 50-year horizon, the personal-representative-portal authorization-mediation workflow with Cognito and institutional release-of-information integration, the dual-control-approval workflow surface, the per-source quality-drift monitoring with disparity alarms, the cross-network-deceased-patient-event propagation through TEFCA, the KMS-encrypted-everything posture, the VPC + VPC endpoints + PrivateLink, the CloudTrail data events on every consequential operation, the Lake Formation column-level access control on the analytics surface, and the federation-participation governance program with named owners. The breadth honestly tells the reader how much operational discipline sits between the recipe and a production deployment.

Pass.

---

## Comment Quality Assessment

Comments consistently explain the "why":

- The Heads-up at the top names every major production gap before the code starts (no real LADMF subscription, no real state-vital-records FHIR feed, no real CMS MBD connection, no real EHR integration, no Step Functions orchestration, no real DynamoDB or Aurora wiring, no real EventBridge cross-account fan-out, no SageMaker calibration loop, no Glue jobs, no posthumous-protection access-control engine, no personal-representative-portal Cognito integration, no IAM/KMS/VPC/WAF/CloudTrail wiring).
- The "things worth knowing upfront" list correctly names the per-source-provenance-as-audit-substrate posture, the per-source-matching-tolerance-calibrated-separately discipline, the premature-death-report-verification-and-reversal pathway, the hidden-duplicate-revelation-as-first-class-pattern framing, the date-of-death-conflict-resolution per-use-case policy, the per-system-cascade-cadence configuration, and the Decimal-at-the-DynamoDB-boundary discipline as the load-bearing structural commitments.
- The per-source-quality-classifications inline comment explains the calibration rationale ("The per-source-quality classifications drive the matching tolerance and the verification-routing decisions. The classifications are versioned and reviewed periodically as source quality drifts (the LADMF's premature-death-report rate has shifted historically; per-state vital-records-feed accuracy improves as states modernize)").
- The per-source-matching-tolerance inline comment names the calibration discipline ("The SSA LADMF has high-quality demographics and SSN-last-4 anchoring; tolerance can be tighter (higher acceptance threshold means fewer candidates but those candidates are more reliable). Family-reported intake has variable completeness; tolerance must be looser (lower acceptance threshold) but the resulting candidates always route to verification before action because the source quality is variable").
- The date-of-death-conflict-resolution policy is named with the per-use-case selection rationale ("legal-and-billing date is the death-certificate date when available (state vital-records is the authoritative source); the clinical-event-timing date is the EHR-recorded date when available; the earliest-plausible date is the minimum of all reported dates (used for right-censoring in cohort-survival analyses)").
- The premature-death-report-verification-threshold rationale is named ("When a death event arrives from a source with premature-death-report rate above this threshold AND no corroboration from other sources, route to the verification queue before applying the death status. The threshold balances the false-positive impact (incorrectly disrupted patients) against the recognition latency (additional days waiting for verification)").
- The per-cascade-consumer cadence configuration is named with per-system rationale ("Real-time means the cascade Lambda fires immediately on the EventBridge event; batched means the cascade waits for the next batch window; on-demand means the cascade fires only when the consumer system pulls").
- The structured logging note explicitly excludes demographic content from logs ("The deceased-patient-resolution pipeline operates on heavily PHI-adjacent data: the death-event payload carries the patient's name, DOB, SSN-last-4, address, the date and cause of death, and the per-source supporting-evidence references all of which should not leak through logs. Log structural metadata only (event_id, source_id, matched_record_id summary, decision band, resolution status), never the actual demographic values, never the cause of death, never the supporting-evidence content").
- The synchronous-demo simplifications are acknowledged at the top: "The example collapses Step Functions, multiple Lambdas, the per-source ingestion, the EventBridge fan-out, the SQS-driven cascade workers, and the personal-representative-portal Cognito IdP into a single Python file for readability."
- The mock-as-stand-in framing is clear in `MockLocalMPI`, `MockDownstreamSystem`, `MockDeathEventSource` (referenced in the prose) with explicit production-extension notes.
- The synthetic-data labeling is unambiguous in the demo runner.
- The dual-control-approval requirement on premature-death-report reversals is named in `_verify_dual_control_approval` ("Two operators from non-overlapping organizational units must approve") and demonstrated in Flow 4.
- The forward-only nature of the death-event-history append (the reversal annotates the prior history entry rather than removing it) is named in `execute_premature_death_report_reversal` step 6D ("The deceased_status field is cleared but the death-event-history retains the original event with a reversal annotation so the audit trail captures the false-positive history").
- The Gap to Production section is unusually thorough (15+ items) covering real per-source ingestion connectors, real LADMF NTIS certification, real DynamoDB schema with the four primary tables, TransactWriteItems for atomic cross-table writes, real Aurora PostgreSQL local MPI, real Step Functions orchestration, real EventBridge bus with cross-recipe consumer subscriptions, real cascade Lambdas with per-system integration code, premature-death-report verification queue review tooling, dual-control approval workflow surface, family-reported-death intake operational discipline, HIPAA-posthumous-protection-period access-control engine, personal-representative-portal authorization-mediation workflow, idempotency keys on every write, per-source quality-drift monitoring with disparity alarms, cohort-stratified accuracy monitoring, cross-network deceased-patient-event propagation through TEFCA, KMS-encrypted everything, VPC + VPC endpoints + PrivateLink, CloudTrail data events, Lake Formation access control, federation-participation governance program. The breadth honestly tells the reader how much operational discipline sits between the recipe and a production deployment.

The comments that would benefit from updates per the findings:

- `_normalize_to_common_schema` would benefit from accepting either `address_line` or `address_line_1` per Finding 1.
- `run_demo` Flow 1 narrative and pre-Flow-1 MPI reset would benefit from clarifying whether Flow 1 exercises hidden-duplicate revelation per Finding 2.
- `match_death_event_against_mpi`'s LOW_CONFIDENCE branch would benefit from removal or restructuring per Finding 3.
- `propagate_to_downstream_systems` and `_summarize_cascade_completeness` would benefit from including cross-recipe-5.1 in the standard cascade per Finding 4.
- `handle_hidden_duplicate_revelation` would benefit from either implementing the consolidation or acknowledging the gap in the docstring per Finding 5.
- The imports block would benefit from dropping `timedelta` and `Key` per Finding 6.

Calibration is otherwise appropriate for a mixed audience.

---

## Healthcare-Specific Requirements

- **PHI discipline.** The Heads-up section frames the PHI-adjacent posture correctly: the death-event payload carries the patient's name, DOB, SSN-last-4, address, the date and cause of death, and per-source supporting-evidence references all of which should not leak through logs. The logger setup correctly limits logging to structural metadata (event_id, source_id, matched_record_id summary, decision band, resolution status), and the `_summarize_event_for_audit` helper records WHAT features were present (not their values), the payload's structural shape, and a content hash for dispute resolution.
- **Synthetic data labeling.** Sample patient IDs (`amc-richmond-mrn-3387221`, `amc-richmond-mrn-5544102`, `amc-richmond-mrn-7782441`), DOBs, SSN-last-4 values, addresses, and phone numbers are obviously synthetic. The Heads-up section warns explicitly. The institution identifier (`academic-medical-center-richmond`) and source identifiers (`ssa-ladmf`, `state-vital-records-virginia`, `payer-cms-mbd`, `ehr-internal`, `family-reported-intake`, `obituary-aggregator`) follow obvious example-only naming.
- **Decimal at the DynamoDB boundary.** Consistent. Defensive float-to-Decimal coercion in `_serialize_for_dynamodb` and at the score-construction boundary throughout the matcher. Note that the demo never actually writes to DynamoDB; the discipline is preserved as a teaching pattern.
- **S3 paths.** No leading slashes on any S3 key. The `_archive_to_s3` helper formats keys as `f"{partition}/{today}/{kid}.json"`.
- **Audit-archive every operation.** `_audit_log` is called at every consequential operation: death event ingested, hidden duplicate revealed, hidden duplicate resolution coordinated, death event no-match, death event queued for review, death event date conflict flagged, death event premature report flagged, death event reconciled, death event applied, death event transaction failed, cascade applied (per-system), reversal authorization rejected, reversal dual-control incomplete, dual-control approval recorded, death event reversed, cascade failed. The audit log captures the structural metadata; the actual demographic content is not duplicated into the audit log.
- **Provenance on every record.** Death-event log entries carry per-source provenance (source_id, source_record_id, source_submission_timestamp, institution_ingestion_timestamp, source_quality_classification, supporting_evidence_reference). Audit-event records carry `matcher_config_version`, `tolerance_version`, and `conflict_policy_version` (set as defaults in `_audit_log`). A future audit can attribute a deceased-patient-resolution decision to the matcher version, the tolerance version, and the conflict-policy version active at decision time.
- **Append-only audit.** The audit-archive S3 writes are append-only by design (each event gets a unique S3 key under the `{partition}/{date}/{key_id}.json` pattern). Production extends with Object Lock in Compliance mode for immutability per the recipe text's "Object Lock in Compliance mode" commitment for the 50-year posthumous-protection-period retention floor; the demo's append-only intent is correct.
- **Conservative thresholds.** Per-source acceptance and high-confidence thresholds are calibrated separately: ssa-ladmf (0.70/0.88), state-vital-records-virginia (0.65/0.85), payer-cms-mbd (0.70/0.88), ehr-internal (0.95/0.99), family-reported-intake (0.55/0.85), obituary-aggregator (0.60/0.85). The ehr-internal source has the highest precision (rightly, because the institution's own EHR-recorded deaths are the lowest-latency-highest-quality source for the institution's own patients), and the family-reported-intake has the lowest acceptance threshold (rightly, because the family's call may carry incomplete demographics but is the most operationally-actionable signal).
- **Premature-death-report verification routing.** The verification threshold (0.010) and the per-source `premature_death_report_rate_baseline` values produce the correct routing for the demo's flows: state-vital-records-virginia (0.002) is below threshold so its events apply directly; ssa-ladmf (0.013) is above threshold so unsupported events route to verification; ehr-internal (0.0005) is below threshold; family-reported-intake (0.020) and obituary-aggregator (0.030) are above threshold. The Flow 3 demonstration of routing the LADMF's solo Margaret Chen event to the verification queue (rather than applying the death status) is the canonical premature-death-report-prevention pattern.
- **Date-of-death conflict resolution.** The per-use-case date selection (legal-billing, clinical-event-timing, earliest-plausible, default) is implemented per `SOURCE_DATE_AUTHORITY_RANKING` and the `authoritative_for_legal_billing` flag in `SOURCE_QUALITY_CLASSIFICATIONS`. The 7-day threshold for flagging conflicts is a reasonable choice for the typical source-reporting-lag tolerance.
- **Hidden-duplicate-revelation handling.** The matcher detects multiple high-confidence candidates as a hidden-duplicate-revelation case and routes to the coordinated-resolution pipeline. **The actual MPI consolidation does not happen in the demo per Finding 5.**
- **Per-system cascade with per-system cadence.** The `CASCADE_CONSUMER_CONFIG` table specifies real-time, near-real-time, and batch cadences per system with per-system SLAs (60 seconds for appointment cancellation, 300 seconds for prescription review, 3600 seconds for billing-episode closure, 86400 seconds for analytics-platform). The recipe text emphasizes per-system cadence configuration; the demo's table reflects this.
- **Dual-control approval for reversals.** The reversal pathway requires (a) a verifier with the `deceased_patient_resolution_verifier` role, (b) two dual-control approvals from non-overlapping organizational units (the demo uses `compliance` and `patient_advocacy`), (c) execution under the verifier's identity. The Flow 4 demonstration shows the canonical pattern.
- **Append-only death-event history.** The reversal annotates the prior death-event-history entry rather than removing it: the entry is updated with `"reversed": True`, `"reversed_at": _now_iso()`, `"reversal_reason": ...`, and `"reversed_by": _summarize_for_audit(verifier_identity)`. The audit trail captures the false-positive history, supporting the recipe text's "the audit trail captures the false-positive history" commitment.
- **Family-experience touchpoints.** The communication-path-switch cascade explicitly stops default communications and initializes the bereavement-aware communication path; the bereavement-aware path is institutionally-defined and is opt-in for the family. The demo's framing ("the institution does not assume bereavement-aware contact authorization without an explicit family signal") respects the family's autonomy.
- **HIPAA-posthumous-protection-period framing.** The recipe text and Gap to Production section name the 50-year posthumous-protection period as the longest single retention requirement in the chapter; the demo doesn't implement the access-control engine but the framing is consistent with the chapter's compliance posture.
- **Personal-representative framing.** The Heads-up section names the personal-representative-portal Cognito-and-IAM integration as a Gap-to-Production item. The cascade_portal_access_handler suspends the patient's own account and notes that "the personal-representative's access is provisioned through the institutional release-of-information process (separate workflow)." The framing is consistent with the recipe text's institutional-release-of-information-mediated authorization.

Pass on the structural healthcare requirements (PHI handling, synthetic-data labeling, Decimal discipline at DynamoDB boundary intent, S3 path discipline, audit archive append-only intent, provenance on every record, conservative threshold posture per source, premature-death-report verification routing, date-of-death conflict resolution per use case, hidden-duplicate-revelation routing intent, per-system cascade with per-system cadence, dual-control approval for reversals, append-only death-event history, family-experience touchpoints, HIPAA-posthumous-protection-period framing, personal-representative framing).

---

## Logical Flow

The file reads top-to-bottom in pedagogical order matching the pseudocode numbering: Setup, Configuration and Constants (logger, retry config, module-level clients, resource names with deploy-time guardrail, versioning, source-quality classifications, per-source matching tolerance, per-feature weights, date-of-death conflict resolution policy, premature-death-report verification threshold, per-cascade-consumer cadence configuration, confidence tier classifications, resolution status values), Helpers (Decimal coercion, name canonicalization, address normalization, ISO date parsing, days-between calculation, Jaro-Winkler computation, SHA-256, DynamoDB serialization, audit-payload summary, CloudWatch metrics, S3 archive, audit-log helper), Mock Local MPI / Downstream Systems / In-Memory Stores, Step 1 (ingest a death event from a source feed with normalization, provenance capture, persistence, dispatch), Step 2 (match the death event against the MPI with per-source tolerance, per-feature similarities, Fellegi-Sunter combination, hidden-duplicate detection, confidence-tier routing), Step 3 (reconcile multi-source death events with date-of-death conflict resolution and premature-death-report detection), Step 4 (apply the death-status update to the MPI atomically with EventBridge fan-out), Step 5 (propagate to downstream systems via per-system cascade Lambdas with per-system acknowledgments), Step 6 (handle premature-death-report verification and reversal with dual-control approval), Full Pipeline (`run_demo` plus four representative flows), Gap to Production.

Each step opens with a short italic prose paragraph that restates the pseudocode step before the code block, matching the cookbook's established pattern. The italic paragraphs name the step's role and the failure mode the step prevents.

The demo runner builds four flows. Flow 1 demonstrates the canonical multi-source-corroborated death (state-vital-records first, LADMF later) — though it silently exercises hidden-duplicate revelation per Finding 2. Flow 2 demonstrates the hidden-duplicate-revelation case explicitly with a reset MPI containing only the two Robert records. Flow 3 demonstrates the premature-death-report verification routing for a single-source LADMF event lacking corroboration. Flow 4 demonstrates the reversal pathway with dual-control approval.

The closing prose paragraph after the expected output walks each flow's behavior with explicit references to the matcher's score-band routing, the multi-source-reconciliation pattern, the verification-queue routing for premature-death-reports, the dual-control-approval discipline, the audit-log capture at every consequential operation, the Decimal discipline, and the per-system cascade with per-system cadence configuration. The narrative connects the synthetic data to the printed output to the architectural intent.

---

## What Is Done Particularly Well

Worth calling out explicitly:

- **The deploy-time guardrail covers every resource-name constant.** The for-loop pattern that asserts every constant is non-empty is consistent with recipes 5.4-5.9. A misconfigured constant produces a clean assertion message rather than a downstream `ValidationException` from boto3 or DynamoDB.
- **The per-source quality classification is a first-class architectural concern.** The `SOURCE_QUALITY_CLASSIFICATIONS` table holds per-source `premature_death_report_rate_baseline`, `data_completeness_score`, `matching_anchor_strength_class`, `supporting_document_certainty`, and `authoritative_for_legal_billing`. The downstream pipeline consumes these classifications at every decision point: matching-tolerance loading, premature-death-report routing, date-of-death authority ranking. The recipe text spends substantial prose on per-source provenance discipline; the demo demonstrates it.
- **The per-source matching tolerance is calibrated separately per source.** The `SOURCE_MATCHING_TOLERANCE` table reflects the recipe text's commitment that "the SSA LADMF (which has high-quality demographics) the same as the family-reported intake (which has variable demographics), with the consequent matching-quality compromise" is exactly what calibration-by-source prevents. The demo's per-source thresholds (ehr-internal 0.95/0.99 for highest precision, family-reported 0.55/0.85 for variable input acceptance) demonstrate the discipline.
- **The premature-death-report verification routing is structurally correct.** The threshold of 0.010 against the per-source baseline (LADMF 0.013, state-VR 0.002, family-reported 0.020) produces the right routing decisions: LADMF and family-reported events without corroboration go to verification, state-VR events apply directly. Flow 3's demonstration is the canonical premature-death-report-prevention pattern.
- **The date-of-death conflict resolution is per-use-case.** The `_compute_consolidated_dates` function selects the legal-billing date from the authoritative-for-legal-billing source (state-vital-records-virginia per the death-certificate-as-authoritative principle), the clinical-event-timing date from ehr-internal (per the EHR-recorded-event-time principle), the earliest-plausible date as the minimum across sources (for cohort-survival right-censoring), and the default date by the source-authority ranking. The 7-day conflict-flagging threshold is a reasonable operational choice.
- **The dual-control approval for reversals is institutionally-named.** `_verify_dual_control_approval` requires two approvers from non-overlapping organizational units; `_validate_verifier_authorization` requires the `deceased_patient_resolution_verifier` role; the audit log captures both approver identities and the reversal verifier identity. Flow 4's demonstration uses `compliance` and `patient_advocacy` as the two organizational units, which is the canonical institutional pattern (compliance for regulatory ownership, patient-advocacy for the family-experience perspective).
- **The reversal annotates rather than removes the death-event history.** The recipe text's commitment to retaining the false-positive history for the audit trail is preserved: the deceased_status field is cleared but the death-event-history list keeps the original event with the `"reversed": True`, `"reversed_at"`, `"reversal_reason"`, and `"reversed_by"` annotations.
- **The per-system cascade has per-system cadence configuration.** The `CASCADE_CONSUMER_CONFIG` table holds per-consumer cadence (real_time, near_real_time, batch) and per-consumer SLA (60 seconds for appointment cancellation up to 86400 seconds for analytics-platform refresh). The recipe text frames this as a chapter-pattern commitment; the demo's per-system cadence configuration demonstrates the discipline.
- **The bereavement-aware communication path is opt-in.** The `cascade_communication_path_switch` action initializes the path with the date-of-death but the implementation's framing ("the institution does not assume bereavement-aware contact authorization without an explicit family signal") respects family autonomy. The recipe text's "family-bereavement-aware-communication-path opt-in framework" variation is honored in the demo's design.
- **The audit log captures the version metadata.** `_audit_log` automatically enriches every event with `matcher_config_version`, `tolerance_version`, and `conflict_policy_version`. A future audit can attribute a particular resolution decision to the calibration active at that time.
- **The demo's four flows cover the major operational paths.** Multi-source corroboration (Flow 1), hidden-duplicate revelation (Flow 2), premature-death-report verification routing (Flow 3), and reversal under dual-control approval (Flow 4). The reader sees the four canonical patterns exercised in sequence with explicit expected output for each.
- **Flow 3 demonstrates the premature-death-report prevention pattern correctly.** The LADMF event for live-patient Margaret Chen lacks corroboration; the verification threshold and absence-of-prior-events both gate the application; the event routes to the verification queue without the MPI being mutated. The reader sees the patient correctly NOT marked deceased.
- **Flow 4 demonstrates the reversal pathway with realistic institutional-detail.** The reversal requires the verifier role, two dual-control approvals from non-overlapping units, execution under the verifier's identity, and propagation of the reversal to all downstream consumers via `propagate_reversal_to_downstream_systems`. The reader sees the reversal complete with `cascade reversal actions: 12` (all 12 entries in `CASCADE_REGISTRY`) and the death-event history retained with the reversal annotation.
- **The synthetic data covers the major matching scenarios.** Robert Anderson (high-confidence match across multiple sources, with a duplicate-chain candidate `mrn-7782441`), Margaret Chen (live-patient receiving a premature LADMF death event). The demo's local MPI population stresses the right architectural axes (per-source provenance discipline, hidden-duplicate-revelation, premature-death-report handling, reversal under dual-control).
- **The Gap to Production section is unusually thorough.** Real per-source ingestion connectors (LADMF, per-state vital-records, payer-feeds, EHR, hospice, family-reported, obituary, provider-reported), real LADMF NTIS certification, real DynamoDB schema with the four primary tables, TransactWriteItems for atomic cross-table writes, real Aurora PostgreSQL local MPI, real Step Functions orchestration, real EventBridge bus, real cascade Lambdas with per-system integration code, premature-death-report verification queue review tooling, dual-control approval workflow surface, family-reported-death intake operational discipline, HIPAA-posthumous-protection-period access-control engine, personal-representative-portal authorization-mediation workflow, idempotency keys on every write, per-source quality-drift monitoring, cohort-stratified accuracy monitoring, cross-network deceased-patient-event propagation through TEFCA, KMS-encrypted everything, VPC + VPC endpoints + PrivateLink, CloudTrail data events, Lake Formation access control, federation-participation governance program. The breadth honestly tells the reader how much operational discipline sits between the recipe and a production deployment.

---

## Closing Assessment

The teaching content is well-organized and faithful to the main recipe in structure, prose framing, and pedagogical ordering. The six pseudocode steps map onto Python functions with helpers in the right places. The S3 + EventBridge + CloudWatch API call shapes are correct (DynamoDB and SQS are referenced in setup but not actually called; the demo's persistence is in-memory). The Decimal-at-the-DynamoDB-boundary discipline is consistent. The per-source provenance capture, per-source matching tolerance calibration, hidden-duplicate-revelation detection, multi-source reconciliation with date-of-death conflict resolution, premature-death-report verification routing, MPI update with EventBridge fan-out, per-system cascade with per-system cadence, and reversal under dual-control approval are all structurally correct. The `MockLocalMPI` and `MockDownstreamSystem` replacements are reasonable approximations that exercise the major paths.

The WARNING is localized and pedagogically meaningful. Finding 1 (the `address_line_1` vs `address_line` mismatch between the recipe text's normalized-event sample and the Python's normalizer) does not flip any decision band in the demo because the demo's source records all use `address_line` to match what the normalizer expects. But following the recipe text's VRDR-approximate sample format into a real ingestion pipeline would silently drop the address feature on every event, with no error and no audit signal. The fix (accept either field name in the normalizer, with `address_line_1` taking precedence) is mechanical and preserves the demo's expected output.

The five NOTEs are smaller items: Flow 1 silently triggers hidden-duplicate revelation that the flow narrative doesn't acknowledge (Finding 2); the LOW_CONFIDENCE branch in `match_death_event_against_mpi` is unreachable (Finding 3); cross-recipe-5.1 is only signaled from the hidden-duplicate-revelation handler, not the standard cascade (Finding 4); the hidden-duplicate handler doesn't actually consolidate the duplicate's data into the survivor (Finding 5); two unused imports (Finding 6).

PASS verdict per the persona's rule: no ERRORs, one WARNING (under the FAIL threshold of more than three). The WARNING and the most-load-bearing NOTEs (Findings 2 and 4) should be addressed before the recipe ships. None of these block the demo from running to completion.

Recipe 5.10 is the tenth and final recipe in Chapter 5 and inherits the chapter's operational discipline (graded confidence with deferred review, audit-everything substrate, drift-event fan-out, transactional-outbox eventing, conservative threshold posture, append-only persistence intent) from recipes 5.1-5.9. The deceased-patient-resolution-specific behaviors that differentiate it (per-source quality classification driving per-source matching tolerance, multi-source reconciliation with date-of-death conflict resolution per use case, premature-death-report verification routing as a hard gate before MPI mutation, hidden-duplicate-revelation as a cross-recipe-5.1 coordination point, per-system cascade with per-system cadence configuration and per-system acknowledgment, premature-death-report reversal pathway with named verifier role and dual-control approval from non-overlapping organizational units, family-experience touchpoints throughout) are all structurally present. Closing the WARNING brings the example up to the standard the recipe text claims and is appropriate given that this recipe is the chapter's capstone for entity-resolution pipelines.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** `_normalize_to_common_schema` reads either `address_line_1` or `address_line` via `source_specific_record.get("address_line_1") or source_specific_record.get("address_line")`. After the fix, hand-trace Flow 1's state-VR event (which uses `address_line`): the `or` chain picks up `address_line` and the composite stays at 1.00. Hand-trace a hypothetical VRDR-spec payload with `address_line_1`: the `or` chain picks up `address_line_1` and the address contributes to scoring. Or, alternatively, the recipe text's "Sample inbound death event" example is updated to use `address_line` to match the Python.
2. **(NOTE)** Either Flow 1 resets the MPI to exclude `mrn-7782441` before running (so Flow 1's narrative description of "multi-source corroboration" matches the actual code path), or Flow 1's narrative and expected output are updated to acknowledge the hidden-duplicate revelation that occurs.
3. **(NOTE)** The unreachable LOW_CONFIDENCE branch in `match_death_event_against_mpi` is removed (and `RES_LOW_CONF_NO_MATCH` is removed from the resolution-status enumeration), or the matcher is restructured to actually produce LOW candidates by lowering the candidate-evaluation gate to a watchlist threshold.
4. **(NOTE)** `cross-recipe-5.1` is added to the standard cascade handler list and the exclusion is removed from `_summarize_cascade_completeness`'s `expected_consumers`. Or, alternatively, the recipe text is updated to clarify that recipe 5.1 receives the deceased-patient signal only via the hidden-duplicate-revelation handler.
5. **(NOTE)** `handle_hidden_duplicate_revelation` either implements the actual MPI consolidation (mutates the survivor with merged data from the duplicates) or acknowledges the gap in the docstring and Gap to Production. After the consolidation fix, Flow 1's `appointments_cancelled` count would reflect the consolidated data.
6. **(NOTE)** `timedelta` and `Key` imports are removed from the imports block. Or, `Key` is used in `_query_prior_events_for_record` to model the production GSI-on-matched_record_id query pattern.

After the WARNING fix, re-run the demo end-to-end and confirm:

- Flow 1: unchanged (`resolution_status: applied`, `matched_record_id: amc-richmond-mrn-3387221`, `legal_billing_dod: 2026-02-08`, `source_count: 1` for first event, `source_count: 2` for LADMF arrival).
- Flow 2: unchanged (`cross-recipe-5.1 action: merge_duplicate_chain`, `survivor_record_id: amc-richmond-mrn-3387221`, `merged_record_ids: ['amc-richmond-mrn-7782441']`).
- Flow 3: unchanged (`resolution_status: premature_death_report_flagged`, `verification_queue_depth: 1`, `queued_reason: premature_death_report_candidate`, `mpi.deceased_status: None`).
- Flow 4: unchanged (`after reversal: deceased_status=None`, `history retained: 1 entry`, `history.reversed: True`, `cascade reversal actions: 12`).

The other findings are low-risk cleanups that improve pedagogical clarity, align the code with the recipe text's stated semantics, and reduce the chance that a reader copies a misleading pattern into production. None of them block the demo from running to completion under the demo-mode-tables-not-provisioned path.
