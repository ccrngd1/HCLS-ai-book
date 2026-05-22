# Code Review: Recipe 5.5 - Cross-Facility Patient Matching

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-22
**Files reviewed:**
- `chapter05.05-cross-facility-patient-matching.md` (main recipe pseudocode)
- `chapter05.05-python-example.md` (Python companion)

**Validation performed:**
- Walked the six pseudocode steps against the Python functions one-to-one
- Verified boto3 API call shapes for DynamoDB resource (`put_item`, `BatchGetItem` semantics), S3 (`put_object`), SQS (`send_message`), EventBridge (`put_events`), CloudWatch (`put_metric_data`)
- Hand-computed the composite match score for each Phase 1 trigger, plus the Phase 2 outage-mode trigger, and compared against the demo's expected printed output
- Traced the blocking-key generation through `_build_blocking_index_if_needed` and `normalize_query` for each trigger to confirm candidate generation
- Walked the consent-and-sensitivity branches (consent permitted, consent expired, registry unavailable, discoverability blocked) for the demo triggers
- Verified Decimal-at-the-DynamoDB-boundary discipline through `_serialize_for_dynamodb`, S3 key formation (no leading slashes), and the cohort-bucket dimension on CloudWatch metrics
- Walked the invalidation pipeline for `consent_revocation`, `local_mpi_merge`, `name_change_5_7`, `address_change_5_3`, and `participating_org_offboarded` event sources
- Verified the audit-log `put_item` ConditionExpression for append-only behavior on the composite (query_id, event_seq) key

---

## Summary

The Python companion is structurally faithful to the main recipe's six pseudocode steps and the architectural picture (ingest from any source with mTLS-or-JWT-stand-in plus purpose-of-use validation, normalize per-org demographic search criteria with multi-strategy blocking-key generation, evaluate against the local cross-org MPI using the same probabilistic-record-linkage scorer pattern from recipes 5.1 and 5.4 with conservatively-calibrated thresholds, apply the consent-then-sensitivity filter chain with fail-closed posture on registry unavailability, persist with append-only audit and emit the resolved event, and react to invalidation triggers from consent revocation, local MPI merges, demographic changes, and partner offboarding). The Decimal-at-the-DynamoDB-boundary discipline is consistent with `_serialize_for_dynamodb`, S3 keys do not carry leading slashes, the graded-confidence threshold-and-review-band routing (HIGH / MED / DEFERRED_REVIEW / REJECT / NO_CANDIDATE) is honored at every persistence write, the conservative thresholds (HIGH=0.92, MED=0.80, REJECT=0.55) are calibrated more conservatively than the internal-matcher thresholds in recipe 5.1 as the recipe text claims, the per-feature score weights weight DOB and last_name highest with cross_org_id as the deterministic tie-breaker, and the cohort-bucket dimension on CloudWatch metrics is the substrate for the per-cohort accuracy monitoring discussed in the main recipe. The MockConsentRegistry, MockSensitivityFilter, and MockPartnerOrg replacements for production dependencies are clearly framed and exercise the major paths (permitted, expired, revoked, registry-unavailable, sensitive-category filtered, partner-side match-and-no-match).

That said, one WARNING needs attention before this goes to readers, plus six NOTEs. The WARNING is a parenthesization bug in `_address_similarity`'s prior-address fallback formula: the `0.9` "Slight penalty for matching prior over current" multiplier is applied only to the `p_street_sim * 0.5` component rather than to the full `(p_zip_match * 0.5 + p_street_sim * 0.5)` prior_score, because of Python's operator-precedence rules (`*` binds tighter than `+`). The bug does not affect any of the demo's printed outputs (in every demo trigger either the primary address matches better than the prior, or the candidate has no prior addresses), but a reader who copies this comparator into a different recipe or a real deployment carries forward a formula whose effect does not match its comment, and a recently-moved patient whose prior address matches the query exactly would receive an inflated address score because the zip_match component (often 1.0 when the patient still lives in the same ZIP) bypasses the penalty entirely.

The six NOTEs cover smaller items: the Phase 1 Trigger #3 inline setup comment ("Med-confidence path. ... Sensitivity filter blocks behavioral_health_notes") is misleading because the trigger actually lands in the deferred-review band where the sensitivity filter is never reached (the closing prose paragraph correctly identifies the deferred-review behavior, but the inline comment teaches the reader the wrong path); `MockConsentRegistry.get` accepts a `requested_data_categories` parameter that is never consulted inside the mock (the mock returns the consent's full permitted-categories list and the eligibility intersection happens in `apply_consent_and_sensitivity`); the pseudocode's Step 1 SQS send specifies `MessageDeduplicationId=compute_query_dedup_key(...)` which only works on FIFO queues but the Python uses `MessageAttributes` for the same hash without an inline comment explaining the deviation; the discoverability-blocked branch in `_build_response_payload` checks `decision["reason"] == "consent_does_not_permit"` before applying the discoverability-NO_MATCH masking, which means an `consent_expired` outcome with `discoverability_permitted=False` reveals the patient's existence as `MATCHED_NOT_RELEASABLE` rather than concealing it as the pseudocode's discoverability-first ordering implies; the `from datetime import datetime, timedelta, timezone` line imports `timedelta` which is not used anywhere in the file; and the NO_CANDIDATE branch in `evaluate_match` emits the `MatchOutcome` metric without a `CohortBucket` dimension (because there is no candidate to read the cohort from), which means the per-cohort no-match-rate the recipe text discusses cannot be computed from this metric alone.

---

## Verdict: PASS

No ERRORs. One WARNING (under the FAIL threshold of more than three). Six NOTEs.

The WARNING and the most-load-bearing NOTEs (Findings 2 and 3) should be addressed before the recipe ships, because they teach a comparator formula whose behavior does not match its comment, an inline trigger comment that misrepresents which code path is exercised, and a discoverability-masking branch ordering that diverges from the pseudocode's intent without an explanation. None of these block the demo from running to completion. Recipe 5.5 is the fifth recipe in Chapter 5 and inherits its operational discipline (graded confidence with deferred review, fail-closed consent posture, audit-everything substrate, drift-event fan-out, cohort-stratified telemetry) from recipes 5.1, 5.2, 5.3, and 5.4, so getting the cross-facility-specific behavior (mTLS-or-JWT requester validation, purpose-of-use enforcement, conservative thresholds with med-confidence release-scope downgrade, consent-then-sensitivity filter chain with fail-closed posture, discoverability semantics, partner-org fan-out with timeout handling, and per-source invalidation) faithful to the pseudocode is what differentiates it from the patient, provider, address, and eligibility matchers.

---

## Findings

### Finding 1: `_address_similarity` Prior-Score Formula Has a Parenthesization Bug; the 0.9 Penalty Multiplier Is Applied Only to the Street Component, Not the Full Prior Score

- **Severity:** WARNING
- **File:** `chapter05.05-python-example.md`
- **Location:** `_address_similarity`, the `for prior in candidate_prior_addrs or []:` loop
- **Description:**

  The function intends to apply a 0.9 penalty multiplier when scoring against a candidate's prior addresses (so that matching the current address scores higher than matching a prior address):

  ```python
  prior_score = ((p_zip_match * Decimal("0.5"))
                    + (p_street_sim * Decimal("0.5"))
                    # Slight penalty for matching prior over current.
                    * Decimal("0.9"))
  ```

  Python operator precedence binds `*` tighter than `+`. The expression evaluates as:

  ```python
  prior_score = (p_zip_match * Decimal("0.5")) + ((p_street_sim * Decimal("0.5")) * Decimal("0.9"))
  ```

  Equivalent to:

  ```python
  prior_score = (p_zip_match * Decimal("0.5")) + (p_street_sim * Decimal("0.45"))
  ```

  The 0.9 penalty applies only to the street-similarity component. The zip-match component is unaffected. The comment "Slight penalty for matching prior over current" implies the penalty applies to the full prior_score; the code does not deliver that.

  The bug does not affect any printed demo output:

  - Trigger #1 (Jane Doe): primary address matches exactly (zip 12345 == 12345, street identical), so `primary_score = 1.0` and `max(1.0, best_prior_score) = 1.0` regardless of the prior calculation.
  - Trigger #2 (Maria Garcia-Lopez): same MPI record, same address-match outcome.
  - Trigger #3 (Alex Johnson): candidate `local-patient-internal-03050` has empty `prior_addresses`, so the inner loop does not execute and `best_prior_score = 0.0`.
  - Trigger #5 (Pat Nobody): no candidates clear blocking, so the comparator is never called.
  - Phase 2 (outage Jane Doe): same address-match outcome as Trigger #1.

  But the bug does affect what the comparator teaches, and a recently-moved patient case exercises it. Suppose a query arrives with `zip="12345", line1="999 NEW STREET"` and the candidate has `standardized_address={"line1": "55 OAK AVE", "zip": "67890"}` and `prior_addresses=[{"line1": "999 NEW STREET", "zip": "12345"}]`:

  - `primary_score`: q_zip=12345 != c_zip=67890, zip_match=0.0; street_sim of "999 NEW STREET" vs "55 OAK AVE" is low (~0.4). primary = 0.5*0 + 0.5*0.4 = 0.2.
  - `prior_score` with the bug: p_zip=12345==q_zip, p_zip_match=1.0; p_street_sim of "999 NEW STREET" vs "999 NEW STREET" = 1.0. With the bug: 1.0*0.5 + (1.0*0.5)*0.9 = 0.5 + 0.45 = 0.95.
  - `prior_score` with the fix: (1.0*0.5 + 1.0*0.5) * 0.9 = 0.9.
  - `max(0.2, 0.95) = 0.95` (with the bug) vs `max(0.2, 0.9) = 0.9` (with the fix).

  The difference is 0.05 in the address sub-score, which translates to 0.005 in the composite (address weight is 0.10). This is small but consistent in direction (the bug always biases toward a higher prior-address score) and it pushes patients with a strong prior-address match closer to the next confidence threshold. Combined with the conservative cross-facility threshold posture the recipe text emphasizes (false positives have clinical-safety consequences), the formula's behavior diverging from its stated intent is the kind of bug that a careful reader will catch and a careless reader will copy.

- **Suggested fix:** Move the closing parenthesis so the 0.9 multiplier applies to the full prior_score:

  ```python
  prior_score = (
      (p_zip_match * Decimal("0.5"))
      + (p_street_sim * Decimal("0.5"))
  ) * Decimal("0.9")  # Slight penalty for matching prior over current.
  ```

  Verify the fix by adding a unit test (or a fourth Phase 1 trigger to the demo) that exercises a recently-moved patient: query supplies the prior address, candidate's `standardized_address` is the new address, candidate's `prior_addresses` contains the prior. Confirm the address sub-score is 0.9 (not 0.95) and the composite score reflects the 0.9 not the 0.95.

---

### Finding 2: Trigger #3's Inline Setup Comment Says "Med-Confidence Path. Sensitivity Filter Blocks behavioral_health_notes" But the Trigger Actually Lands at NO_MATCH_DEFERRED_REVIEW and Never Reaches the Sensitivity Filter

- **Severity:** NOTE
- **File:** `chapter05.05-python-example.md`
- **Location:** `run_demo`, Phase 1 trigger #3 setup block; the demo's expected-output prose paragraph
- **Description:**

  The trigger setup comment says:

  ```python
  # 3. Med-confidence path: Alex Johnson with mismatched
  # address (moved). Sensitivity filter blocks
  # behavioral_health_notes.
  ```

  But the trace through the matcher lands the score below the MED threshold:

  - first_name (`ALEX` vs `ALEX`): 1.0
  - last_name (`JOHNSON` vs `JOHNSON`): 1.0
  - dob (`19951102` vs `19951102`): 1.0
  - sex (`M` vs `M`): 1.0
  - address (`999 NEW STREET, 67890` vs `55 OAK AVE, 12345`, no prior addresses): zip_match=0.0, street_sim ~0.4, primary_score ~0.2, prior loop empty, max ~0.2
  - phone (None vs `["+15557776666"]`): query has no phone → 0.5 (neutral)
  - ssn (None vs None on candidate): 0.5 (neutral)
  - prior_cross_org_id (None vs `xorg-7a3b9c2e-3333`): 0.5

  Composite: `0.12*1 + 0.20*1 + 0.25*1 + 0.05*1 + 0.10*0.2 + 0.05*0.5 + 0.08*0.5 + 0.15*0.5 = 0.78`

  0.78 falls between AUTO_REJECT (0.55) and AUTO_ACCEPT_MED (0.80), so the outcome is `NO_MATCH_DEFERRED_REVIEW`. The expected demo output confirms this:

  ```
  med-confidence + sensitivity-filter path                status=NO_MATCH_DEFERRED_REVIEW  conf=n/a    release=no
  ```

  Two consequences:

  1. **The inline comment teaches the wrong path.** A reader who walks the demo by reading the trigger setup expects the trigger to land in the MED band and demonstrate the sensitivity-filter blocking `behavioral_health_notes`. The actual behavior is that the matcher routes the case to deferred review without ever invoking `apply_consent_and_sensitivity` for the matched-not-released branches; `apply_consent_and_sensitivity` short-circuits at the top:

     ```python
     if (query.get("is_linkage_submission")
             or match["status"] in {"NO_MATCH",
                                        "NO_MATCH_DEFERRED_REVIEW",
                                        "NO_CANDIDATE"}):
         query["release_decision"] = {
             "release": False,
             "reason":  "no_match_or_linkage_submission",
         }
         return query
     ```

     So `behavioral_health_notes` is never filtered by the sensitivity policy in this trigger; it is bypassed entirely along with every other category in the requested list.

  2. **The closing prose paragraph correctly identifies the deferred-review behavior**, but the inline comment and the closing prose paragraph are inconsistent with each other. The inline comment is what a reader sees first when scanning the trigger setup. A learner who copies the trigger pattern into their own demo carries forward a misleading label.

  The demo *does* exercise the sensitivity-filter path elsewhere (Trigger #2's filter-then-release path with the high-value-only downgrade), so the trigger #3 mislabel is a pedagogical bug rather than a coverage gap. The closing prose paragraph mentions:

  > Trigger #3 demonstrates the deferred-review path. Alex Johnson queried with a totally different address (the patient moved or the registration captured a wrong address); the address comparator drops to a low value, and the composite score lands between AUTO_REJECT and MED.

  Which is the right characterization. The inline comment should match.

- **Suggested fix:** Update the inline comment to match the actual path:

  ```python
  # 3. Deferred-review path: Alex Johnson with mismatched
  # address (moved or wrong-captured). Score lands between
  # AUTO_REJECT and AUTO_ACCEPT_MED, so the matcher returns
  # NO_MATCH_DEFERRED_REVIEW; the case is queued for
  # asynchronous human review and the requester gets a
  # NO_MATCH response in real time.
  ```

  If the recipe wants a separate trigger that exercises the sensitivity-filter behavioral-health blocking path, add a sixth trigger that lands at MED or HIGH confidence with `behavioral_health_notes` in the requested data categories. For example, a query that matches Alex Johnson on every feature (current address, valid phone) lands at HIGH confidence; if the requested categories include `behavioral_health_notes`, the sensitivity filter applies the institutional restriction and the released set excludes that category.

---

### Finding 3: `_build_response_payload`'s Discoverability-Blocked NO_MATCH Branch Only Triggers When `reason == "consent_does_not_permit"`; Pseudocode's Discoverability-First Ordering Is Lost

- **Severity:** NOTE
- **File:** `chapter05.05-python-example.md`
- **Location:** `_build_response_payload`
- **Description:**

  The pseudocode's Step 5A response-payload construction:

  ```
  IF decision.release:
      response_payload = {match: ..., data: ..., ...}
  ELIF decision.discoverability_permitted == FALSE:
      # Cannot acknowledge the patient is in our system.
      response_payload = {match_status: "NO_MATCH"}
  ELSE:
      # Patient is in our system but consent does not permit
      # release. The framework-specific response indicates
      # "found but not releasable."
      response_payload = {
          match_status: "MATCHED_NOT_RELEASABLE",
          withhold_reason: decision.reason
      }
  ```

  The Python implementation:

  ```python
  if decision["release"]:
      ...
      return {...}

  consent_summary = decision.get("consent_state_summary") or {}
  if (decision["reason"] == "consent_does_not_permit"
          and not consent_summary.get("discoverability_permitted")):
      return {"match_status": "NO_MATCH"}

  if decision["reason"] in {"consent_does_not_permit",
                                "consent_expired"}:
      return {
          "match_status":   "MATCHED_NOT_RELEASABLE",
          "withhold_reason": decision["reason"],
      }

  if decision["reason"] == "consent_registry_unavailable":
      return {
          "match_status":   "TEMPORARY_UNAVAILABLE",
          "withhold_reason": "consent_registry_unavailable",
          "should_retry":    True,
      }

  return {"match_status": match["status"]}
  ```

  The discoverability-NO_MATCH masking is gated by `reason == "consent_does_not_permit"`. If the consent has expired AND `discoverability_permitted == False`, the Python returns `MATCHED_NOT_RELEASABLE`, which reveals to the requester that the patient is in the system. The pseudocode's discoverability-first branch would return `NO_MATCH` regardless of whether the underlying reason is `consent_does_not_permit` or `consent_expired`.

  The implication is operationally subtle but real: a patient whose consent expired and who has separately flagged "do not acknowledge my presence in this system" gets their existence revealed under the Python's branching, and concealed under the pseudocode's. Most jurisdictions' consent framework treats discoverability as an independent signal that overrides the release-status response category.

  The closing prose section "The thing about the discoverability semantics" in the main recipe explicitly underscores this:

  > In some frameworks, the difference between those two responses leaks information that the patient did not consent to share (the fact of being seen at this organization, even without the clinical detail). The discoverability flag in the consent registry controls this, and the responder's match-and-release pipeline has to honor it. Most implementations get this wrong on the first pass and discover the issue when the first patient files a complaint about it.

  The Python implementation gets it wrong the same way the prose warns against. Trigger-level demo coverage does not exercise the consent-expired path, so the divergence is not surfaced in the printed output, but a reader who builds on this code carries forward the bug pattern.

- **Suggested fix:** Apply the discoverability-first masking before checking specific reason codes:

  ```python
  consent_summary = decision.get("consent_state_summary") or {}

  # Discoverability check fires first: if discoverability is
  # not permitted, conceal the patient's existence regardless
  # of why the release is being withheld.
  if not consent_summary.get("discoverability_permitted", True):
      # Default discoverability_permitted=True is a deliberate
      # choice for cases where the consent state did not
      # populate the field (registry-unavailable path).
      return {"match_status": "NO_MATCH"}

  if decision["reason"] in {"consent_does_not_permit",
                                "consent_expired"}:
      return {
          "match_status":   "MATCHED_NOT_RELEASABLE",
          "withhold_reason": decision["reason"],
      }

  if decision["reason"] == "consent_registry_unavailable":
      return {
          "match_status":   "TEMPORARY_UNAVAILABLE",
          "withhold_reason": "consent_registry_unavailable",
          "should_retry":    True,
      }

  return {"match_status": match["status"]}
  ```

  And ensure the `consent_state_summary` is populated with `discoverability_permitted` for the consent-expired path in `apply_consent_and_sensitivity` (it already is, via the `consent_state["discoverability_permitted"]` lookup).

---

### Finding 4: `MockConsentRegistry.get` Accepts a `requested_data_categories` Parameter That the Mock Never Consults

- **Severity:** NOTE
- **File:** `chapter05.05-python-example.md`
- **Location:** `MockConsentRegistry.get`
- **Description:**

  The signature accepts `requested_data_categories`:

  ```python
  def get(self, patient_local_id: str, requesting_org: str,
           purpose_of_use: str, requested_data_categories: list,
           timeout_ms: int = 500) -> dict:
  ```

  But the body never references the parameter. The mock returns the consent's full `permitted_data_categories` list, and the eligibility intersection happens later in `apply_consent_and_sensitivity`:

  ```python
  eligible_data_categories = list(
      set(consent_state["permitted_data_categories"])
      & set(query["requested_data_categories"])
  )
  ```

  The pseudocode is similarly structured (the registry returns permitted categories; the matcher intersects), so the parameter on the mock's signature is a vestigial copy that does not exercise anything.

  Two consequences:

  1. **The signature suggests the registry consults the requested list**, which is a plausible design: a real registry might filter its return based on what was requested (to avoid revealing what the patient has consented to share that the requester did not ask about). The mock does not implement this; the docstring or an inline comment should clarify that the parameter is reserved for the production registry's filtering pattern.
  2. **A reader who walks the registry interface looking for the eligibility-intersection logic** finds nothing in the mock and has to discover that the intersection happens in the caller. Not a bug, but a small pedagogical roughness.

- **Suggested fix:** Either remove the unused parameter from the mock's signature (and from the call site in `apply_consent_and_sensitivity`), or add an inline comment naming the production behavior:

  ```python
  def get(self, patient_local_id: str, requesting_org: str,
           purpose_of_use: str, requested_data_categories: list,
           timeout_ms: int = 500) -> dict:
      """
      The requested_data_categories parameter is preserved on
      the signature for production parity: a real registry may
      filter its returned permitted_data_categories list to
      only those overlapping with the request, so the requester
      cannot learn what other categories the patient has
      consented to share. The mock returns the full permitted
      list and lets the caller intersect.
      """
      ...
  ```

  Either option is fine; the inline comment is the smaller change.

---

### Finding 5: Pseudocode's `MessageDeduplicationId` SQS Send Maps to `MessageAttributes` in Python Without an Inline Comment Explaining the Deviation

- **Severity:** NOTE
- **File:** `chapter05.05-python-example.md`
- **Location:** `ingest_query`, the SQS `send_message` call
- **Description:**

  The pseudocode's Step 1 specifies SQS deduplication:

  ```
  SQS.SendMessage(queue_url, normalized_query,
      MessageDeduplicationId=compute_query_dedup_key(normalized_query))
  ```

  The Python uses `MessageAttributes`:

  ```python
  sqs_client.send_message(
      QueueUrl=queue_url,
      MessageBody=json.dumps(query, default=str),
      MessageAttributes={
          "query_hash": {
              "DataType":    "String",
              "StringValue": query["query_hash"],
          },
      },
  )
  ```

  The deviation is correct: `MessageDeduplicationId` is a FIFO-only parameter; standard SQS queues reject it. The Python's choice to use `MessageAttributes` for the hash is appropriate for standard queues (where deduplication, if needed, must be implemented downstream by checking the attribute against an idempotency table).

  But the Python does not flag the deviation. A reader walking the pseudocode line-by-line against the Python sees the pseudocode's `MessageDeduplicationId` and looks for the corresponding `MessageDeduplicationId=...` argument in the Python; not finding it, the reader has to figure out that (a) the queues are standard, not FIFO, and (b) `MessageAttributes` is the standard-queue substitute. The downstream consumer's idempotency story is also implicit: the demo does not show a `query_id`-keyed idempotency check at the receiver, which is the production pattern.

- **Suggested fix:** Add an inline comment naming the deviation:

  ```python
  sqs_client.send_message(
      QueueUrl=queue_url,
      MessageBody=json.dumps(query, default=str),
      MessageAttributes={
          # The pseudocode shows MessageDeduplicationId, which
          # is FIFO-queue-only. For standard queues we ship
          # the hash on a MessageAttribute and enforce
          # idempotency at the consumer (a query_id-keyed
          # DynamoDB conditional put on the audit-log table,
          # which the release-and-audit step does).
          "query_hash": {
              "DataType":    "String",
              "StringValue": query["query_hash"],
          },
      },
  )
  ```

  The comment connects the pseudocode's intent (deduplication) to the production-realistic implementation (consumer-side idempotency via the audit-log condition expression).

---

### Finding 6: `from datetime import datetime, timedelta, timezone` Imports Unused `timedelta`

- **Severity:** NOTE
- **File:** `chapter05.05-python-example.md`
- **Location:** the imports block at the top of the Configuration and Constants section
- **Description:**

  The imports include:

  ```python
  from datetime import datetime, timedelta, timezone
  ```

  No code path uses `timedelta`. The file uses `datetime.now(timezone.utc)` and `datetime.fromisoformat(...)` for the consent expiration check, but no relative-time arithmetic. A linter would flag this; a careful reader notices the import and looks for the corresponding use, finding none.

  Same chapter pattern as recipe 5.4's Finding 4 (unused `Key` import).

- **Suggested fix:** Remove `timedelta` from the import list:

  ```python
  from datetime import datetime, timezone
  ```

  Or, if a future refactor will use `timedelta` (e.g., to compute consent expiration windows or the response-window deadline), add the use at the same time.

---

### Finding 7: NO_CANDIDATE Branch in `evaluate_match` Emits the `MatchOutcome` Metric Without a `CohortBucket` Dimension; Per-Cohort No-Match-Rate Cannot Be Computed From This Metric

- **Severity:** NOTE
- **File:** `chapter05.05-python-example.md`
- **Location:** `evaluate_match`, the `if not scored:` branch
- **Description:**

  The cohort-stratified instrumentation pattern is consistent across the matched / med / rejected / deferred branches (every branch emits `MatchOutcome` with `CohortBucket`):

  ```python
  cohort_bucket = best["candidate"].get("cohort_bucket", "unknown")
  ...
  _emit_metric("MatchOutcome", 1.0,
                dimensions={"Status": outcome["status"],
                              "CohortBucket": cohort_bucket})
  ```

  But the NO_CANDIDATE branch (no candidates clear blocking) emits without the cohort dimension:

  ```python
  if not scored:
      outcome = {
          "status": "NO_CANDIDATE",
          "interpretation": "no_candidate_in_blocking",
          ...
      }
      _emit_metric("MatchOutcome", 1.0,
                    dimensions={"Status": outcome["status"]})
      query["match_outcome"] = outcome
      return query
  ```

  The omission is structurally understandable: there is no candidate to read the cohort from. But the recipe text emphasizes per-cohort accuracy monitoring as a load-bearing operational concern, and the per-cohort no-match-rate is a primary equity-monitoring signal:

  > Per-cohort match success rate, per-cohort review-queue rate, and per-cohort downstream-error rate (clinician-reported wrong-patient retrieval, mistakenly-filed cross-org documents) all need monitoring with disparity thresholds.

  Without a cohort dimension on the NO_CANDIDATE metric, the per-cohort match-success-rate dashboard cannot distinguish "cohort A had higher no-candidate rates than cohort B" from "cohort A had fewer queries than cohort B." The cohort label has to come from somewhere: the requesting query's demographics (which the matcher has just normalized), or the requesting principal (which carries the requesting organization's cohort attribution context if the institution has wired it).

  Two consequences:

  1. **The equity-monitoring story has a blind spot at the most operationally-significant outcome class** (no-candidate is typically the largest outcome class for cross-facility queries; the recipe's Honest Take section calls out the long tail of "patients whose providers cannot find their history" as a cohort-disparity concern).
  2. **The metric is structurally inconsistent across branches**, which surfaces as a dimension-mismatch warning in CloudWatch dashboards if the user tries to facet by `CohortBucket`.

- **Suggested fix:** Compute a query-side cohort bucket from the normalized demographics or the requesting principal, and emit it on the NO_CANDIDATE branch:

  ```python
  def _query_side_cohort_bucket(normalized: dict, principal: dict) -> str:
      # Stand-in for a real cohort attribution. Production reads
      # from an institutional cohort registry. The bucket is
      # non-reversible and is shipped as a metric dimension.
      ...
      return "unknown"

  ...

  if not scored:
      outcome = {...}
      cohort_bucket = _query_side_cohort_bucket(
          query["normalized"],
          query.get("requesting_principal") or {})
      _emit_metric("MatchOutcome", 1.0,
                    dimensions={"Status": outcome["status"],
                                  "CohortBucket": cohort_bucket})
      query["match_outcome"] = outcome
      return query
  ```

  The query-side cohort attribution is the more general mechanism; production extends it to include the requesting organization's population profile when the responder is the institution and the requester is an out-of-network partner.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Function | Consistent? |
|----------------|-----------------|-------------|
| `ingest_query(inbound)` | `ingest_query` plus `_verify_requester`, `_is_purpose_permitted`, `_archive_raw_to_s3` | Mostly yes (source-branched parsing into a normalized query record with `query_id`, `source`, `is_linkage_submission`, `requesting_principal`, `purpose_of_use`, `search_demographics`, `requested_data_categories`, `response_window_ms`, `received_at`, plus an idempotency hash). The mTLS-or-JWT validation is mocked with `_verify_requester` returning a trusted assertion; production replaces with real cert/JWT validation as the comments note. **The pseudocode's `MessageDeduplicationId` SQS argument maps to `MessageAttributes` in the Python without an inline comment naming the deviation per Finding 5.** |
| `normalize_query(query)` | `normalize_query` plus `_normalize_name`, `_normalize_dob`, `_normalize_phone`, `_hyphenation_alternates`, `_soundex_stub`, `_nickname_alternates` | Yes (per-feature normalization with phonetic-and-nickname alternates, partial-DOB precision flag, hyphenation-tolerant alternates, multi-strategy blocking-key generation: ln_soundex_yob, ln_initial_fn_initial, zip3_dob_md, prior_xorg_id; the prior-name blocking via the candidate's `prior_last_names` is wired in `_build_blocking_index_if_needed`). |
| `evaluate_match(query)` (sub-steps 3A-3F) | `evaluate_match` plus `_jaro_winkler`, `_nickname_aware_first_name_score`, `_cross_org_last_name_score`, `_dob_match_grade`, `_sex_match`, `_address_similarity`, `_phone_match`, `_ssn_match`, `_prior_cross_org_id_match`, `_composite_score` | Mostly yes (3A blocking-key candidate generation with union, 3B BatchGet-equivalent, 3C per-feature scoring, 3D no-candidate handling, 3E cohort-stratified telemetry, 3F threshold-band routing with HIGH / MED / DEFERRED / REJECT). The conservative thresholds (HIGH=0.92, MED=0.80, REJECT=0.55) match the recipe text's "calibrated more conservatively than internal matching" framing. **The `_address_similarity` prior_score formula has the parenthesization bug per Finding 1 and the NO_CANDIDATE metric emission lacks the CohortBucket dimension per Finding 7.** |
| `apply_consent_and_sensitivity(query)` (sub-steps 4A-4F) | `apply_consent_and_sensitivity` plus `MockConsentRegistry.get`, `MockSensitivityFilter.filter` | Mostly yes (4A linkage-and-no-match short-circuit, 4B fail-closed registry read, 4C consent-permitted-or-expired branching, 4D eligibility intersection, 4E sensitivity filter application, 4F med-confidence release-scope downgrade). **The `MockConsentRegistry.get` accepts `requested_data_categories` but never consults it per Finding 4.** |
| `release_and_audit(query)` (sub-steps 5A-5F) | `release_and_audit` plus `_build_response_payload`, `_serialize_for_dynamodb`, `_archive_raw_to_s3` | Mostly yes (5A response-payload construction with discoverability and release-scope handling, 5B append-only audit-log put with ConditionExpression, 5C raw-and-curated S3 archive, 5D EventBridge emit, 5E response transmission). The TODO comment flags the partial-failure consistency concern (Expert review A1) for follow-up. **The discoverability-NO_MATCH branch ordering deviates from the pseudocode's discoverability-first intent per Finding 3.** |
| `invalidate_on_event(event)` | `invalidate_on_event` plus blocking-index reset and EventBridge emit | Yes (`consent_revocation` walks the in-memory audit log and counts affected queries, `local_mpi_merge` redirects via `superseded_by`, `name_change_5_7` appends `prior_last_names` and clears the blocking index for rebuild, `address_change_5_3` appends `prior_addresses`, `participating_org_offboarded` records the action, all branches emit the aggregated `cross_facility_match_invalidated` event). The in-memory walk is a reasonable demo-mode stand-in for the production DynamoDB Query against the audit-log table. |

Intentional deviations clearly framed:

- The HIE intermediary, partner organizations, consent registry, and sensitivity-filter policy engine become `MockHIEIntermediary` (implicit in the test fixtures), `MockPartnerOrg`, `MockConsentRegistry`, and `MockSensitivityFilter` with hand-crafted responses covering the major paths. Documented in the Heads-up section and in Gap to Production.
- The DynamoDB read path falls back to `_IN_MEMORY_AUDIT_LOG` when the real table is not provisioned. Documented inline.
- The blocking index is an in-process dict (`_BLOCKING_INDEX`) rather than ElastiCache. Documented in the comments.
- The cross-org MPI is `SYNTHETIC_CROSS_ORG_MPI` rather than DynamoDB. Documented at the call site.
- Step Functions orchestration, Glue/Spark batch reconciliation, KMS / VPC / Secrets Manager / WAF / CloudTrail wiring, real FHIR Patient `$match` parsing, IHE PIX/PDQ v2 connectivity, real review-queue UI, longitudinal-record-assembler integration, patient-access-report generator are deferred to Gap to Production.

The substantive deviations (Findings 1, 3) are the consistency gaps that carry pedagogical consequence. The acknowledged simplifications (mock partners, mock consent registry, in-memory MPI, in-process blocking index) are clearly framed.

---

## AWS SDK Accuracy

| API Call | Method | Notes |
|----------|--------|-------|
| DynamoDB PutItem | `dynamodb.Table(NAME).put_item(Item=_serialize_for_dynamodb(...), ConditionExpression="attribute_not_exists(query_id)")` | Correct. The condition fires the expected append-only behavior on the composite (query_id, event_seq) key: PutItem at the same composite key would be rejected because the existing item's query_id attribute already exists. The `_serialize_for_dynamodb` helper handles the Decimal coercion at the boundary. |
| DynamoDB BatchGetItem | (referenced in pseudocode for candidate retrieval, not in the demo Python) | The Python's `evaluate_match` reads candidates from the in-memory `SYNTHETIC_CROSS_ORG_MPI` dict rather than calling `dynamodb.batch_get_item(...)`. The pseudocode shows the production form. Acknowledged as a demo simplification. |
| DynamoDB UpdateItem | (referenced in pseudocode for `superseded_by` redirect on local_mpi_merge, prior_last_names append on name_change_5_7, prior_addresses append on address_change_5_3) | The Python's `invalidate_on_event` mutates the in-memory dict directly rather than calling `dynamodb.Table().update_item(...)`. The pseudocode shows the production form (with the `list_append` UpdateExpression). Acknowledged as a demo simplification. |
| S3 PutObject | `s3_client.put_object(Bucket=..., Key=key, Body=body, ServerSideEncryption="aws:kms")` | Correct. Body is bytes-encoded JSON with `default=str` to handle Decimal. Keys use `{partition}/{date}/{query_id}.json` with no leading slashes. The bucket selection routes by partition prefix (`raw-...` to `RAW_BUCKET`, anything else to `CURATED_BUCKET`). |
| SQS SendMessage | `sqs_client.send_message(QueueUrl, MessageBody, MessageAttributes)` | Correct shape for standard queues. **The pseudocode's `MessageDeduplicationId` is FIFO-only and is replaced with a `MessageAttributes` query_hash without an inline explanation per Finding 5.** The deferred-review queue send shape is also correct. |
| EventBridge PutEvents | `eventbridge_client.put_events(Entries=[{Source, DetailType, EventBusName, Detail}])` | Correct. `Detail` is JSON-serialized with `default=str` to handle Decimal. Two event types are emitted: `cross_facility_query_resolved` from `release_and_audit` and `cross_facility_match_invalidated` from `invalidate_on_event`. |
| CloudWatch PutMetricData | `cloudwatch_client.put_metric_data(Namespace, MetricData=[{MetricName, Value, Unit, Dimensions}])` | Correct shape. Six metric names appear in the file: `UnauthenticatedRequester`, `PurposeNotPermitted`, `QueryIngested`, `QueryTruncatedCandidates`, `MatchScore`, `MatchOutcome`, `ConsentRegistryUnavailable`, `MatchInvalidations`. **The NO_CANDIDATE branch emits MatchOutcome without the CohortBucket dimension per Finding 7.** |

The SDK-level concerns are: Finding 5 (MessageDeduplicationId vs MessageAttributes deviation) and Finding 7 (cohort dimension omitted on NO_CANDIDATE). All API surfaces are current and correct.

---

## DynamoDB and Data Type Check

- `_to_decimal` correctly uses `Decimal(str(value))` and short-circuits on already-Decimal inputs.
- `_serialize_for_dynamodb` recursively walks dicts, lists, and tuples, converts floats to Decimal. Booleans pass through (`isinstance(True, float)` is False; bool is an int subclass, not float). The pattern is safe.
- All match-outcome composite scores, feature scores (first_name, last_name, dob, sex, address, phone, ssn, prior_cross_org_id), and threshold values (`AUTO_ACCEPT_HIGH_THRESHOLD`, `AUTO_ACCEPT_MED_THRESHOLD`, `AUTO_REJECT_THRESHOLD`) are constructed as Decimals via `_to_decimal` or `Decimal("...")` literals at the boundary, so they pass through `_serialize_for_dynamodb` unchanged at the DynamoDB write.
- The audit_record is serialized through `_serialize_for_dynamodb` before the put_item, including the nested match_outcome's score_breakdown Decimals.
- The `match_confidence` in the EventBridge `Detail` flows through `json.dumps(..., default=str)`, which avoids the `TypeError: Object of type Decimal is not JSON serializable` that would otherwise raise.
- The CloudWatch `Value` parameter uses `float(best["composite"])`. Correct (CloudWatch accepts native floats; only DynamoDB requires Decimal).
- The `match_confidence` in `_build_response_payload` uses `str(match["match_confidence"])` to coerce Decimal to string for the FHIR-shaped response payload, which is correct (FHIR Patient $match search scores are typically serialized as JSON numbers or strings; the demo sends a string for safety).
- `f"{conf:.2f}"` works correctly on Decimal in Python 3.x; the print-summary code in `run_demo` is safe.

The Decimal discipline is correct. No type-handling bugs.

---

## S3 and Credentials Check

- The example uses S3 only for audit-archive writes (`raw-inbound`, `curated-normalized`, `raw-outbound`, `curated-audit`, `curated-consent-failures`). No leading slash on any key.
- The deploy-time guardrail covers every resource-name constant via the `for _name, _value in [...]: assert _value` loop. **No constant can silently be empty.** Same discipline as recipe 5.4.
- No hardcoded credentials. Module-level boto3 clients use the documented environment credential chain.
- The IAM permissions list in Setup matches the API surface used by the code.
- The Setup section explicitly names that "tutorial-level permissions above are fine for learning and will fail any serious IAM review" with the right framing about per-Lambda role scoping and the audit-log writer's append-only IAM.
- The PHI framing is unambiguous: *"Cross-facility queries and responses are PHI. The inbound query contains a patient's full demographics. The outbound response contains the patient's match status plus (when consent permits) a slice of their clinical record. Both are PHI; both are sensitive in different ways."*
- The fail-closed posture is correctly emphasized: *"Consent checks are fail-closed. If the consent registry is unavailable, the matcher MUST NOT release data."*
- The mock-partner credentials handling is appropriately deferred: *"Mutual TLS (mTLS) certificates from the institution's certificate authority, signed JWTs against the HIE's JWKS, or HIE-issued credentials drive the authentication."*

Pass.

---

## Comment Quality Assessment

Comments consistently explain the "why":

- The Heads-up at the top names every major production gap before the code starts (no real FHIR `$match` operation handler, no real IHE PIX/PDQ v2 parser, no real mTLS validator, no Step Functions orchestration, no Glue/Spark batch reconciliation, no real consent-registry connector, no longitudinal-record-assembler, no patient-access-report generator, no review-queue UI, and no IAM, KMS, VPC, WAF, or CloudTrail wiring).
- The PHI framing is honest and specific: *"The inbound query contains a patient's full demographics. The outbound response contains the patient's match status plus (when consent permits) a slice of their clinical record. Both are PHI; both are sensitive in different ways. Encrypt at rest with a customer-managed KMS key, encrypt in transit with TLS 1.2 or higher (mutual TLS where the partner requires it), and apply tighter access controls than you would for the internal matcher."*
- The audit-log-as-legal-record framing is explicit: *"The audit log is the legal record. Every query, every match decision, every consent check, every release, every withhold. The patient has a right to see who queried about them and what was released."*
- The Decimal-at-the-DynamoDB-boundary discipline is documented: *"DynamoDB rejects Python `float`. Every confidence score, score-breakdown component, and numeric metadata field passes through `Decimal` on its way in and on its way out."*
- The fail-closed posture is named: *"Consent checks are fail-closed. If the consent registry is unavailable, the matcher MUST NOT release data."*
- The conservative-threshold rationale is explicit: *"Cross-facility match thresholds are calibrated more conservatively than internal-matcher thresholds. A wrong cross-facility match produces a misfiled clinical document or a wrong-patient overlay in the consuming organization's chart, with clinical-safety consequences."*
- The async-decomposition deferral is acknowledged: *"The example collapses Step Functions, multiple Lambdas, the SQS-driven worker pattern, and the inbound-and-outbound query orchestration into a single Python file for readability."*
- The mock-as-stand-in framing is clear in every mock class docstring (MockConsentRegistry, MockSensitivityFilter, MockPartnerOrg).
- The synthetic-data labeling is unambiguous: *"All patients, organizations, and HIE responses in this demo are fictional. The mock consent registry, sensitivity filter, and partner orgs return hand-crafted responses that exercise the full classification range; do not point this demo at a live HIE."*
- The 42 CFR Part 2 special handling note is included in `MockSensitivityFilter.filter`: *"42 CFR Part 2 requires a re-disclosure prohibition notice when SUD records are released; we are not releasing SUD records here, but the audit log records that the filter considered them."*
- The transactional-outbox TODO is precise and operationally useful: *"Wrap the audit-log put, the S3 audit archive, the EventBridge emit, and the response transmission in a TransactWriteItems plus an outbox row drained by a separate Lambda or DynamoDB Streams consumer so partial failures cannot leave the audit log out of sync with the released response."*
- The discoverability semantics are flagged in the closing prose: *"In some frameworks, even acknowledging that the patient is in our system requires consent. The 'discoverability_permitted' flag controls whether the response is 'no record found' (which does not reveal whether the patient is in our system) or 'found but not releasable' (which does reveal that)."* (The Python implementation of this point has Finding 3 to address.)
- The blocking-and-recall framing is named: *"Multiple complementary keys for blocking-recall, the matcher unions the candidates."*
- The cohort-bucketed metrics framing is consistent: the cohort label is read from the candidate's MPI snapshot rather than being computed from raw demographics at the metric-emission boundary, matching the recipe's expert-review S5 guidance about bucketed non-reversible cohort labels.

The Gap to Production section is unusually thorough (15+ items spanning real consent-registry connector, real sensitivity-filter policy engine, real partner connectivity, real DynamoDB schema with the audit-log-and-MPI tables, real ElastiCache for blocking-index cache, FHIR Patient `$match` generation and parsing, IHE PIX/PDQ legacy connectivity, TransactWriteItems for atomic audit-and-release, Step Functions orchestration, idempotency keys on every write, mTLS and signed-JWT validation, threshold calibration and approval governance, cohort-stratified accuracy monitoring, deferred-review queue tooling, longitudinal-record-assembler integration, patient-access reports, initial backfill and onboarding, KMS-encrypted everything, VPC + VPC endpoints, CloudTrail data events, WAF + Shield + enumeration-attack defense, HIE participation agreement operationalization, compliance and operational ownership). The breadth honestly tells the reader how much sits between the recipe and a production deployment.

The comments that would benefit from updates per the findings:

- `_address_similarity` would benefit from rewriting the prior_score formula so the comment matches the code per Finding 1.
- The Trigger #3 setup comment would benefit from being rewritten to match the deferred-review path the trigger actually exercises per Finding 2.
- `_build_response_payload` would benefit from a docstring sentence naming the discoverability-first ordering per Finding 3.
- `MockConsentRegistry.get` would benefit from a docstring sentence naming why the unused `requested_data_categories` parameter is retained per Finding 4.
- The SQS `send_message` call site in `ingest_query` would benefit from a comment naming the FIFO-vs-standard-queue deviation per Finding 5.

Calibration is otherwise appropriate for a mixed audience.

---

## Healthcare-Specific Requirements

- **PHI discipline.** The opening "things worth knowing upfront" block correctly names that the cross-facility query and response are PHI, with the encryption-and-access-control framing.
- **Synthetic data labeling.** Sample patient IDs (`local-patient-internal-00874`, etc.), addresses (`1421 ELM ST APT 3B`, `55 OAK AVE`), member IDs, and demographics are obviously synthetic. The Heads-up section warns explicitly. The `MockConsentRegistry`, `MockSensitivityFilter`, and `MockPartnerOrg` use the same synthetic inputs.
- **Decimal at the DynamoDB boundary.** Consistent. Defensive float-to-Decimal coercion in `_serialize_for_dynamodb` and at the score-construction boundary in `evaluate_match`.
- **Audit-archive every operation.** `_archive_raw_to_s3` is called at ingest (raw-inbound), normalize (curated-normalized), release-and-audit (raw-outbound and curated-audit), and consent-registry-unavailable (curated-consent-failures). Every operational state of the query is captured.
- **Provenance on every record.** Match-outcome records carry `matcher_config_version`, `thresholds_version`, and the audit-log records add `sensitivity_policy_version`, `received_at`, `completed_at`, `requesting_org`, `purpose_of_use`, `response_correlation_id`. Versioning lives at the audit boundary so a future investigation can attribute behavior to a specific release.
- **Fail-closed consent.** The `ConsentRegistryUnavailable` exception is raised by the mock when `simulate_outage = True`, caught in `apply_consent_and_sensitivity`, and produces a `release: False, reason: consent_registry_unavailable, should_retry: True` decision plus a separate audit archive (`curated-consent-failures` partition). The fail-closed posture is exercised in Phase 2 of the demo.
- **Append-only audit log.** The DynamoDB put_item uses `ConditionExpression="attribute_not_exists(query_id)"` so a duplicate write at the same composite (query_id, event_seq) key is rejected. The closing TODO acknowledges that production extends with TransactWriteItems and signature chaining.
- **42 CFR Part 2 awareness.** The `MockSensitivityFilter.INSTITUTIONAL_RESTRICTED_CATEGORIES` includes `substance_use_disorder_records` with reason `42_cfr_part_2`, and the filter emits the `42_cfr_part_2_filter_applied` note when SUD records are considered. The recipe's prose connects this to the framework-required disclosure.
- **Discoverability semantics.** The recipe's closing prose flags the "patient is in our system" disclosure as itself sensitive information. The Python implements a `discoverability_permitted` field on the consent state and a discoverability-NO_MATCH branch in `_build_response_payload`. **Finding 3 calls out the ordering deviation.**
- **Conservative threshold posture.** AUTO_ACCEPT_HIGH=0.92, AUTO_ACCEPT_MED=0.80, AUTO_REJECT=0.55. These are higher than the typical internal-matcher thresholds (recipe 5.1 uses 0.85 for HIGH), matching the recipe text's "calibrated more conservatively than internal matching" framing.
- **Med-confidence release-scope downgrade.** `HIGH_VALUE_DATA_AT_MED_CONFIDENCE` narrows the released set to `allergies, active_medications, problem_list_active, advance_directives` for med-confidence matches; the `release_scope_modifier == "downgrade_to_high_value_only"` branch in `apply_consent_and_sensitivity` filters the eligible set. The trauma-team-clinical-safety motivation is explicit in the recipe text.
- **Cohort-stratified telemetry.** `evaluate_match` emits `MatchScore` and `MatchOutcome` with a `CohortBucket` dimension, which is the substrate for the per-cohort accuracy monitoring discussed in the main recipe. Aggregation, alarming, and disparity calculation are appropriately deferred to Gap to Production. **Finding 7 calls out the NO_CANDIDATE branch missing the cohort dimension.**
- **Information-blocking awareness.** The recipe text (in the Honest Take section) names the 21st Century Cures Act information-blocking rules; the architecture's posture (low latency, high availability, fail-soft on partner timeouts) is shaped by the regulatory backdrop. The Python's `response_window_ms` distinction (3 seconds for realtime, 30 seconds for linkage) reflects the latency budgets that information-blocking compliance imposes.
- **Patient-access-report substrate.** The audit-log records are written before the response is transmitted (Phase 5C in the pseudocode and the corresponding Python in `release_and_audit`); the recipe text explicitly calls out that the audit log is the source of the patient's right-to-know report. The Python builds the substrate; the access-report generator is appropriately deferred to Gap to Production.

Pass on healthcare-specific handling. The discoverability-ordering deviation (Finding 3) is the most healthcare-specific gap and is the one the recipe's Honest Take section warns will be the first regulatory complaint surface.

---

## Logical Flow

The file reads top-to-bottom in pedagogical order matching the pseudocode numbering: Setup, Configuration and Constants (logger, retry config, module-level clients, resource names with deploy-time guardrail, versioning, conservative confidence thresholds, per-feature score weights, latency budgets, blocking cap, med-confidence release scope, helper utilities), Mock Consent Registry / Sensitivity Filter / Partner Orgs / MPI Registry (with the small `SYNTHETIC_CROSS_ORG_MPI`, `_BLOCKING_INDEX`, `MockConsentRegistry`, `MockSensitivityFilter`, and `MockPartnerOrg` registries), Step 1 (ingest with raw archive and SQS routing), Step 2 (normalize with multi-strategy blocking-key generation), Step 3 (evaluate match with blocking, scoring, threshold band routing, cohort-stratified telemetry), Step 4 (consent + sensitivity with fail-closed posture and med-confidence release-scope downgrade), Step 5 (release + audit with append-only audit-log put, raw and curated S3 archive, EventBridge emit), Step 6 (invalidate on event with multi-source branching), Full Pipeline (`run_pipeline` plus the synthetic patient and consent registry), Demo Runner (`run_demo` with five phases), Gap to Production.

Each step opens with a short italic prose paragraph that restates the pseudocode step before the code block, matching the cookbook's established pattern. The italic paragraphs name the step's role and the failure mode that step prevents (e.g., *"Skip the authentication and you have an enumeration-attack surface; skip the purpose-of-use check and you release data for purposes the participation agreement does not permit."*).

The demo runner builds five Phase 1 triggers (high-confidence trauma-team query, maiden-name to prior-name match landing at MED, address-mismatch deferred-review, unauthorized-purpose rejection, no-match), one Phase 2 simulated outage demonstrating fail-closed posture, one Phase 3 outbound fan-out to partners, one Phase 4 invalidation event (consent revocation), and one Phase 5 invalidation event (name change). The trigger choice exercises every classification branch the recipe wants to demonstrate, plus the consent fail-closed path and the multi-source invalidation paths. **The Trigger #3 inline comment calls itself a "Med-confidence path" but actually exercises the deferred-review path per Finding 2.**

---

## What Is Done Particularly Well

Worth calling out explicitly:

- **The deploy-time guardrail covers every resource-name constant.** The for-loop pattern that asserts every constant is non-empty is consistent with recipe 5.4. A misconfigured constant produces a clean assertion message rather than a downstream `ValidationException` from boto3 or SQS.
- **The conservative-threshold posture is explicit in the constants and in the comments.** The `AUTO_ACCEPT_HIGH_THRESHOLD = Decimal("0.92")` and `AUTO_ACCEPT_MED_THRESHOLD = Decimal("0.80")` values are higher than recipe 5.1's internal-matcher equivalents, with the comment naming why: *"the cost of false positives is higher (a misfiled cross-org document or a wrong-patient overlay in the consuming organization's chart is a clinical-safety event)."* The recipe's framing of the threshold as institutional-discipline rather than magic-number is preserved.
- **The med-confidence release-scope downgrade is implemented faithfully.** `HIGH_VALUE_DATA_AT_MED_CONFIDENCE` defines the narrower set, and the `release_scope_modifier == "downgrade_to_high_value_only"` branch in `apply_consent_and_sensitivity` applies the intersection. The clinical-safety motivation (limit the blast radius of a possibly-wrong match) is explicit in the comments.
- **The fail-closed consent posture is exercised in the demo.** Phase 2 sets `consent_registry.simulate_outage = True` and runs a query that would otherwise match high-confidence; the demo shows `release=False, reason=consent_registry_unavailable`. A learner sees the fail-closed path execute without having to imagine the outage scenario.
- **The probabilistic-record-linkage scorer is a recognizable cousin of recipe 5.1 and 5.4's matcher**, with cross-facility-specific feature weights (DOB and last_name dominate, prior_cross_org_id is a strong deterministic tie-breaker, address is meaningful but not dominant). The score weights live in a constant dictionary so a per-institution recalibration is a one-line change.
- **The matcher's `_cross_org_last_name_score` handles three grade levels** (exact match, candidate prior-name match at 0.92, hyphenation-alternate match at 0.95 or candidate prior-via-alternate at 0.88) faithfully to the recipe text's *"prior_last_names list (from recipe 5.7) catches maiden-and-married-name patterns."* The Trigger #2 demo exercises the prior-name path correctly: query "GARCIA", candidate "GARCIA-LOPEZ" with `prior_last_names=["GARCIA"]` scores 0.92 on the last-name comparator.
- **The blocking-key strategy is multi-pronged** (last-name-soundex + year-of-birth, last-name-initial + first-name-initial, ZIP3 + DOB-month-day, prior cross-org identifier, plus a prior-last-names variant of the soundex-yob block). The union semantics produce the right candidate set for the Trigger #2 maiden-name case (query "GARCIA" with yob 1972 finds candidate 02100 via the prior-last-name block).
- **The cohort-bucketed CloudWatch metric is wired correctly for the matched-and-rejected paths.** `MatchScore` and `MatchOutcome` both emit with a `CohortBucket` dimension read from the candidate's MPI snapshot. **Finding 7 calls out the NO_CANDIDATE branch missing the cohort dimension.**
- **The MockConsentRegistry exercises the major consent states.** Permitted-with-full-categories (Jane Doe), permitted-with-patient-flagged-sensitive (Maria Garcia-Lopez with `reproductive_health` flagged), permitted-with-patient-flagged-behavioral-health (Alex Johnson). The simulate_outage flag exercises the fail-closed path. The `discoverability_permitted` field is wired through.
- **The multi-source invalidation branching is faithful to the pseudocode.** All five sources (`consent_revocation`, `local_mpi_merge`, `name_change_5_7`, `address_change_5_3`, `participating_org_offboarded`) have explicit branches with documented actions; the Phase 4 and Phase 5 demo phases exercise two of them and the cross-source EventBridge emit.
- **The TODO comments are precise and operationally useful.** The transactional-outbox TODO in `release_and_audit` names exactly the right pattern (TransactWriteItems plus a Streams-driven event emitter) with the right justification for why the consequence is sharper here than in earlier chapter-5 recipes (the audit log is the legal record of cross-organizational data flow; any divergence between what was sent and what the audit log claims was sent is a compliance incident).
- **The Gap to Production section is exceptionally thorough.** Real consent-registry connector, real sensitivity-filter policy engine, real partner connectivity (mTLS + JWT + NAT-with-allow-list + PrivateLink), real DynamoDB schema, real ElastiCache, FHIR Patient `$match` generation, IHE PIX/PDQ legacy connectivity, TransactWriteItems atomic writes, Step Functions orchestration, idempotency keys on every write, mTLS and signed-JWT validation, threshold calibration governance, cohort-stratified accuracy monitoring with disparity alarms, deferred-review queue tooling, longitudinal-record-assembler integration, patient-access reports, initial backfill, KMS / VPC / Secrets Manager / WAF / CloudTrail posture, HIE participation agreement operationalization, compliance and operational ownership. The breadth honestly tells the reader how much operational discipline sits between the recipe and a production deployment.
- **The Phase 1 / Phase 2 / Phase 3 / Phase 4 / Phase 5 demo structure is pedagogically strong.** Phase 1 walks the major classification branches; Phase 2 demonstrates fail-closed consent; Phase 3 shows the outbound fan-out; Phase 4 demonstrates consent-revocation invalidation; Phase 5 demonstrates name-change propagation from recipe 5.7. A learner who runs the demo sees the full lifecycle exercised in a single run.
- **The closing prose accurately walks each Phase 1 trigger through the matcher logic**, with explicit references to which feature scores produced the composite. The narrative connects the trigger setup to the printed output to the architectural intent.
- **The cohort-stratified instrumentation is wired in `evaluate_match` rather than at the metric-emission boundary at the end of `release_and_audit`.** This matters because the cohort-bucket lookup is correct even when the persist path fails (a metric emit is not blocked by a downstream persist error).

---

## Closing Assessment

The teaching content is well-organized and faithful to the main recipe in structure, prose framing, and pedagogical ordering. The six pseudocode steps map onto Python functions with helpers in the right places. The DynamoDB + S3 + SQS + EventBridge + CloudWatch API call shapes are correct. The Decimal-at-the-DynamoDB-boundary discipline is consistent. The conservative-threshold-with-graded-confidence routing, the consent-then-sensitivity filter chain, the fail-closed posture on consent-registry unavailability, the med-confidence release-scope downgrade, and the multi-source invalidation pipeline are all structurally correct. The MockConsentRegistry, MockSensitivityFilter, and MockPartnerOrg replacements are reasonable approximations that exercise the major paths.

The single WARNING is localized and pedagogically meaningful. Finding 1 (the `_address_similarity` prior_score formula has a parenthesization bug that applies the 0.9 penalty multiplier only to the street component, not the full prior_score) does not affect any printed demo output, but it teaches a comparator pattern whose behavior does not match its comment, and a recently-moved-patient case (where the prior address matches the query and the current address does not) would receive an inflated address sub-score. The fix is one set of parentheses; verification is a unit test or a sixth Phase 1 trigger that exercises the recently-moved patient path.

The six NOTEs are smaller items: the Trigger #3 setup comment misrepresenting which path the trigger exercises, the discoverability-NO_MATCH branch ordering deviating from the pseudocode's discoverability-first intent, the unused `requested_data_categories` parameter on `MockConsentRegistry.get`, the unexplained pseudocode-to-Python deviation from `MessageDeduplicationId` to `MessageAttributes`, the unused `timedelta` import, and the missing `CohortBucket` dimension on the `MatchOutcome` metric for the NO_CANDIDATE branch.

PASS verdict per the persona's rule: no ERRORs, one WARNING (under the FAIL threshold of more than three). The WARNING and the most-load-bearing NOTEs (Findings 2 and 3) should be addressed before the recipe ships, because they teach a comparator formula whose behavior does not match its comment, an inline trigger comment that misrepresents which code path is exercised, and a discoverability-masking branch ordering that diverges from the pseudocode's intent without explanation. None of these block the demo from running to completion.

Recipe 5.5 is the fifth recipe in Chapter 5; the recipe text frames it explicitly as *"the recipe in this chapter where the gap between 'we have the technology' and 'we have the operational capacity to deploy it well' is the widest."* Closing the WARNING and the most-load-bearing NOTEs brings the example up to the standard the recipe text claims, which is appropriate given that the cross-facility-specific deviations (mTLS-or-JWT requester validation, conservative thresholds with med-confidence release-scope downgrade, fail-closed consent posture, sensitivity-filter policy chaining, discoverability semantics, multi-source invalidation, and outbound partner fan-out) are the entire reason this is a separate recipe from 5.1, 5.2, 5.3, and 5.4.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** `_address_similarity`'s prior_score formula applies the 0.9 penalty to the full `(p_zip_match * 0.5 + p_street_sim * 0.5)` score rather than to `p_street_sim * 0.5` alone. Add a unit test or a sixth Phase 1 trigger that exercises a recently-moved patient (query supplies prior address; candidate has prior address in `prior_addresses` and a different current address); confirm the address sub-score reflects the full 0.9 penalty.
2. **(NOTE)** The Trigger #3 inline comment is rewritten to match the deferred-review path the trigger actually exercises. Optionally, add a sixth trigger that exercises the MED-confidence-with-sensitivity-filter path (matching Alex Johnson at his current address with `behavioral_health_notes` in the requested categories).
3. **(NOTE)** `_build_response_payload` applies the discoverability-NO_MATCH masking before checking the specific reason code (consent_does_not_permit / consent_expired), so the discoverability-first intent of the pseudocode is honored regardless of why the release is being withheld.
4. **(NOTE)** `MockConsentRegistry.get` either drops the unused `requested_data_categories` parameter or adds a docstring sentence naming why the parameter is preserved (production-parity hint).
5. **(NOTE)** The `ingest_query` SQS `send_message` call site adds an inline comment naming the FIFO-vs-standard-queue deviation from the pseudocode's `MessageDeduplicationId`.
6. **(NOTE)** `from datetime import datetime, timedelta, timezone` drops `timedelta` if no use is added in the same change.
7. **(NOTE)** The NO_CANDIDATE branch in `evaluate_match` emits the `MatchOutcome` metric with a `CohortBucket` dimension (computed from query-side demographics or the requesting principal's attribution context).

After the WARNING fix, re-run the demo end-to-end and confirm the Phase 1 / Phase 2 outputs match the existing expected output (the bug fix should not alter the printed numbers because the demo's triggers do not exercise the prior-address fallback path; if any number changes, that is itself a signal that a new test case is needed). The other NOTEs are low-risk cleanups that improve pedagogical clarity but do not change observable behavior in the existing demo.
