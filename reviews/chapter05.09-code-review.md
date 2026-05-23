# Code Review: Recipe 5.9 - National-Scale Patient Matching (TEFCA)

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-23
**Files reviewed:**
- `chapter05.09-national-scale-patient-matching.md` (main recipe pseudocode)
- `chapter05.09-python-example.md` (Python companion)

**Validation performed:**
- Walked the six pseudocode steps against the Python functions one-to-one
- Verified boto3 API call shapes for S3 (`put_object`), EventBridge (`put_events`), CloudWatch (`put_metric_data`)
- Hand-traced the four demo flows (Flow 1 ED-attending treatment query, Flow 2 patient-mediated IAS, Flow 3 inbound rejection scenarios, Flow 4 cross-jurisdictional overlay suppression)
- Hand-computed the Sarah Mitchell match score for Flow 1 (given+family+dob+address+zip = 0.80, lands MATCH-medium between 0.55 acceptance and 0.85 high-confidence) and Flow 2 (full feature set = 1.00, lands high above 0.92)
- Verified the QHIN signature validation against rotated and prior key versions
- Walked the originating-attribution-chain validation against PARTICIPANT_AUTHORIZED_QHINS
- Walked the exchange-purpose validation against PARTICIPANT_AUTHORIZED_EXCHANGE_PURPOSES with the PrivacyException denial path
- Walked the per-record-type and per-jurisdiction overlay engine for Maria Garcia-Lopez (reproductive_health_care flag + state-with-criminal-prohibition-1 jurisdiction) producing the expected suppression
- Walked the consent-and-Part-2 filter at candidate-evaluation time
- Verified the dual-control approval enforcement on `MockSecretsCustody.rotate_participant_key` (defined but not exercised)
- Verified Decimal-at-the-DynamoDB-boundary discipline (no actual DynamoDB writes in demo, but threshold constants, FEATURE_WEIGHTS, and similarity scores are Decimals throughout)
- Verified S3 keys do not carry leading slashes (`f"{partition}/{today}/{kid}.json"` pattern)
- Verified deploy-time guardrail asserts every resource-name constant is non-empty
- Confirmed `hmac.compare_digest` for timing-safe signature comparison

---

## Summary

The Python companion is structurally faithful to the main recipe's six pseudocode steps and the architectural picture (validate inbound QHIN-signed query and dispatch under authorization context; run local matcher under cross-network tolerance per exchange purpose; apply per-record-type and per-jurisdiction sensitivity overlay; originate outbound query with originating-attribution chain; consume and consolidate federated responses with completeness indicator and grouping; orchestrate document query and retrieval with per-document attribution). The Decimal-at-the-DynamoDB-boundary discipline is consistent (though no actual DynamoDB writes happen in the demo), S3 keys do not carry leading slashes, the QHIN-signature-validation and originating-attribution-validation paths cleanly catch the three rejection scenarios, the consent-and-Part-2 filter operates at candidate-evaluation time before the matcher even sees the record, the per-jurisdiction overlay engine demonstrates the post-Dobbs reproductive-health-care suppression path cleanly, and the `MockSecretsCustody`, `MockLocalMPI`, `MockConsentStore`, `MockJurisdictionalOverlays`, and `MockQHINFederationRouter` replacements for production dependencies are clearly framed and exercise the major paths.

That said, this companion ships with one WARNING and several NOTEs. The WARNING concerns the demographic-feature field naming asymmetry between the outbound query path and the inbound query path. The recipe text's "Sample inbound federated patient-discovery query (illustrative; actual payload follows the QTF specification)" shows `address_line_1` as the canonical field name. The Python's outbound formulator at line 1575 uses `address_line_1` (`"address_line_1": requested_demographics.get("address_line")`), and the mock other-participant handler at line 2103 reads either `address_line_1` or `address_line` for forward compatibility. But the canonical local handler in `run_local_matcher_under_cross_network_tolerance` at line 1260 only normalizes `address_line` (`"address_line": _normalize_address(demographic_features.get("address_line") or "")`). A reader pointing this code at a real QHIN that emits the QTF-canonical `address_line_1` would silently get an empty address feature on every inbound query, dropping the address weight (0.10) from the composite score with no error and no audit signal that anything went wrong. The bug is invisible in the demo because Flow 3's hand-crafted inbound test payloads use `address_line` to match what the local handler expects.

The NOTEs cover smaller items: the response envelope's `candidate_count_truncated` is hardcoded to `False` even when the matcher's Step 2E truncated the candidate set above `max_candidate_count` (the audit log captures the truncation event but the response envelope doesn't reflect it, so a downstream consumer cannot tell from the envelope alone that the response was capped); `_emit_metric` hardcodes `Unit="Count"` for all metrics, including `OverlayApplicationRate` which is a 0-1 rate rather than a count; `MockSecretsCustody.get_qhin_public_keys(include_previous=False)` filters by key versions ending with the literal string "active" but no demo key version has that suffix (so the `False` branch returns an empty dict if ever called, though it is not exercised in the demo); `MockSecretsCustody._access_log` accumulates entries on every secret access but is never inspected; the mock other-participant handler in `_make_inbound_handler_for_other_participant` does not apply the IAS-specific demographic suppression that the canonical handler's `_extract_disclosable_features` implements (so Flow 2's consolidated view shows the full city/state/zip feature set despite the canonical IAS-disclosure policy); private-attribute access on `secrets_custody._qhin_public_keys` and `secrets_custody._participant_signing_keys` from the QHIN router and the response consolidator is a code smell that a public accessor would resolve.

---

## Verdict: PASS

No ERRORs. One WARNING (the `address_line` vs `address_line_1` field-naming asymmetry between the outbound formulator and mock-other-participant handlers using the QTF-canonical name and the local inbound handler reading only the demo-internal name; pointing this at a real QHIN silently drops the address feature). Six NOTEs.

The WARNING and the most-load-bearing NOTEs (Findings 2 and 3) should be addressed before the recipe ships, because they teach a field-naming pattern that fails silently in production, a response-envelope field whose value disagrees with the matcher's actual behavior, and a metric-unit hardcoding that constrains future score-emit additions. None of these block the demo from running to completion or flip any decision band in the documented expected output.

Recipe 5.9 is the ninth recipe in Chapter 5 and inherits the chapter's operational discipline (graded confidence with deferred review, audit-everything substrate, drift-event fan-out, cohort-stratified telemetry, transactional-outbox eventing, conservative threshold posture) from recipes 5.1-5.8. The TEFCA-specific behaviors that differentiate it (QHIN-signed request envelope as authentication root-of-trust, dual-calibrated cross-network tolerance per exchange purpose, opaque record token decoupling federation-visible identifiers from local record identifiers, per-record-type and per-jurisdiction sensitivity overlay applied at disclosure time, federated-response asynchronous consolidation with explicit completeness indicator, originating-attribution chain captured at every hop, information-blocking-compliance "denied-under-exception" pattern instead of silent drops, six-source invalidation pipeline including credential rotations, governance changes, consent withdrawals, and cross-recipe events from recipes 5.1 / 5.7 / 5.8) are all structurally present.

---

## Findings

### Finding 1: `address_line` vs `address_line_1` Field-Naming Asymmetry; The Local Inbound Handler Silently Drops Addresses From Real QHIN Traffic Because It Only Reads the Demo-Internal Field Name While the Outbound Formulator and Mock-Other-Participant Handlers Use the QTF-Canonical Name

- **Severity:** WARNING
- **File:** `chapter05.09-python-example.md`
- **Location:** `run_local_matcher_under_cross_network_tolerance` step 2B normalization block (line 1260); `originate_outbound_patient_discovery_query` step 4C `formulated_payload` construction (line 1575); `_make_inbound_handler_for_other_participant` inner handler's address normalization (line 2103); the recipe text's "Sample inbound federated patient-discovery query" example
- **Description:**

  The recipe text shows the canonical inbound query payload format with `address_line_1`:

  ```json
  "demographic_features": {
    "given_name": "Sarah",
    "family_name": "Mitchell",
    "dob": "1984-08-17",
    "sex_or_gender": "F",
    "address_line_1": "1247 Oak Street",
    "city": "Richmond",
    "state": "VA",
    "zip_code": "23220",
    ...
  }
  ```

  The annotation explicitly says "actual payload follows the QTF specification," so `address_line_1` is the production-canonical field name.

  The Python's outbound formulator translates the local `address_line` to `address_line_1` for the wire format:

  ```python
  formulated_payload = {
      "given_name":   requested_demographics.get("given_name"),
      ...
      "address_line_1": requested_demographics.get("address_line"),
      ...
  }
  ```

  And the mock other-participant handler reads either field for forward compatibility:

  ```python
  "address_line": _normalize_address(
      demographic_features.get("address_line_1")
      or demographic_features.get("address_line")
      or ""),
  ```

  But the canonical local handler `run_local_matcher_under_cross_network_tolerance` only reads `address_line`:

  ```python
  normalized = {
      "given_name":   _canonical_name(
          demographic_features.get("given_name")),
      "family_name":  _canonical_name(
          demographic_features.get("family_name")),
      "dob":          (demographic_features.get("dob") or "").strip(),
      "address_line": _normalize_address(
          demographic_features.get("address_line") or ""),
      ...
  }
  ```

  The asymmetry produces three outcomes depending on the inbound query source:

  1. **Demo's hand-crafted Flow 3 payloads (use `address_line`):** the local handler reads the field correctly and the address contributes to the match score. Works.
  2. **Outbound queries routed through the demo's QHIN router to mock-other-participants (use `address_line_1`):** the mock-other-participant handler reads the field via its dual-key fallback. Works.
  3. **Real QHIN traffic following the QTF spec (uses `address_line_1`):** the local handler's `demographic_features.get("address_line")` returns `None`, the `or ""` falls through to the empty string, `_normalize_address("")` returns `""`, and the address-feature similarity score is `0.0` for every inbound query regardless of how well the address actually matches.

  Demo impact:

  - **Flow 3 valid_inbound_payload (`address_line: "1247 Oak St"`):** the local handler reads it, normalizes to "1247 oak st", matches the MPI's "1247 Oak St" → "1247 oak st", scores 1.0 on address. Composite = 0.80, candidates = 1. Matches expected output.
  - **Hypothetical real QHIN payload (`address_line_1: "1247 Oak Street"`):** the local handler's `demographic_features.get("address_line")` returns None, the address feature scores 0.0. Composite drops by 0.10 weight: 0.80 - 0.10 = 0.70. Still above the 0.55 acceptance threshold for treatment, so the candidate is still returned, but with a lower score. Address would have to participate in score for queries with sparser demographic data; for queries that already lack phone or SSN-last-4, the address drop can flip a candidate from accepted to rejected (0.55 - 0.10 = 0.45, below 0.55).

  Pedagogical impact:

  1. **The recipe's main pseudocode example explicitly establishes `address_line_1` as the QTF-canonical format.** The Python's local handler not supporting it means the demo's "production participant" implementation would silently underscore on real QHIN traffic. A reader following the recipe's structure into a real deployment carries this gap forward.
  2. **The outbound side correctly translates to the QTF format** (which is the right behavior). The asymmetry is in the inbound side. A reader inspecting the outbound formulator and seeing `address_line_1` may reasonably assume the local handler also reads `address_line_1` for symmetry; the actual code doesn't.
  3. **No error or audit signal indicates the silent-drop.** A query whose address is dropped because the field name doesn't match still produces a "successful" match envelope with a lower composite score; no `WARNING` log line, no rejection envelope, no audit-event hint that the matcher saw an empty address where a populated one existed in the wire format.

- **Suggested fix:** Update the local handler to read either field name, mirroring the mock other-participant handler's pattern:

  ```python
  normalized = {
      "given_name":   _canonical_name(
          demographic_features.get("given_name")),
      "family_name":  _canonical_name(
          demographic_features.get("family_name")),
      "dob":          (demographic_features.get("dob") or "").strip(),
      # Accept either the QTF-canonical address_line_1 or the
      # demo's internal address_line. Production normalizes the
      # incoming wire format at the gateway-deserialization layer
      # and presents a single canonical field downstream; the
      # demo collapses the gateway-deserialization layer into the
      # matcher, so the matcher itself handles both.
      "address_line": _normalize_address(
          demographic_features.get("address_line_1")
          or demographic_features.get("address_line")
          or ""),
      ...
  }
  ```

  After the fix, hand-trace the Flow 3 valid inbound query: `address_line` is populated in the test payload and `address_line_1` is absent, so the `or` chain picks up `address_line` and the composite stays at 0.80. Matches expected output. Hand-trace a hypothetical real QHIN payload with `address_line_1`: the `or` chain picks up `address_line_1` and the address contributes to scoring as the recipe text intends. The fix is mechanical and preserves the demo's expected output exactly.

  Alternatively, normalize the wire format at a single gateway-deserialization helper that the local handler calls before the matcher sees the payload; this matches the production architectural posture (a TEFCA-gateway Lambda that deserializes the QTF format into the institution's internal representation before dispatching to the matcher Lambda) but is heavier than the inline `or` chain. The inline approach is the right teaching pattern for the demo.

---

### Finding 2: `candidate_count_truncated` Is Hardcoded to `False` in the Inbound Response Envelope Even When Step 2E Truncated the Candidate Set Above max_candidate_count

- **Severity:** NOTE
- **File:** `chapter05.09-python-example.md`
- **Location:** `handle_inbound_patient_discovery_query` step 1H response payload construction (line 1173); the parallel construction in `_make_inbound_handler_for_other_participant`'s response payload (line 2161)
- **Description:**

  The inbound handler's response envelope is built in step 1H:

  ```python
  response_payload = {
      "query_id":             query_id,
      "responder_id":         PARTICIPANT_ID,
      "candidates":           filtered_candidates,
      "candidate_count_returned":  len(filtered_candidates),
      "candidate_count_truncated": False,
      "responded_at":         _now_iso(),
      "tolerance_version":    CROSS_NETWORK_TOLERANCE_VERSION,
      "overlay_rules_version": OVERLAY_RULES_VERSION,
  }
  ```

  The `candidate_count_truncated` field is hardcoded to `False`. But the matcher's Step 2E in `run_local_matcher_under_cross_network_tolerance` actually does truncate when the candidate count exceeds `tolerance["max_candidate_count"]`:

  ```python
  if len(scored) > tolerance["max_candidate_count"]:
      scored.sort(key=lambda c: c["match_score"], reverse=True)
      original = len(scored)
      scored = scored[:tolerance["max_candidate_count"]]
      _audit_log({
          "event_type": "TEFCA_INBOUND_QUERY_CANDIDATES_TRUNCATED",
          "query_id":   query_id,
          "original_count": original,
          "returned_count": len(scored),
      })
  ```

  The truncation is captured in the audit log (good) but the matcher does not return the truncation flag back to the handler, so the response envelope cannot signal it to the originator. A downstream consumer that wants to know whether the response is complete or capped has to consult the audit log out-of-band, which defeats the purpose of having the field on the envelope.

  Demo impact: in the four demo flows, none of the candidate sets exceed the per-purpose `max_candidate_count` (treatment=10, IAS=3, etc.), so the truncation path never fires. The hardcoded `False` is correct in practice for the demo but does not reflect the matcher's actual behavior.

  Pedagogical impact:

  1. **The field's name promises a runtime signal that the code does not deliver.** A reader inspecting the response envelope sees `candidate_count_truncated` as a load-bearing protocol field; the implementation always says `False` regardless of what the matcher did.
  2. **The truncation event is captured in the audit log but not in the response payload**, breaking the recipe's "the originating user's response-time tolerance is shorter than the longest-tail response, so the consolidation step presents partial results when the deadline expires and explicitly indicates to the user what fraction of the federation has responded" framing. Truncation is a different signal from response-window expiration, but both belong on the response envelope so the originator can communicate the partial-response state to the user.
  3. **The recipe pseudocode does not explicitly require the truncation flag on the response envelope** (the pseudocode mentions only the audit-log event), so this is a pedagogical-quality issue rather than a strict pseudocode-to-Python mismatch. But the field is on the envelope and is wrong.

- **Suggested fix:** Either return the truncation flag from the matcher and propagate it to the response envelope, or drop the field from the envelope.

  **Option A (propagate the flag):** modify `run_local_matcher_under_cross_network_tolerance` to return both the scored candidates and a truncation indicator, and consume them in the handler:

  ```python
  def run_local_matcher_under_cross_network_tolerance(
          demographic_features, authorization_context, query_id):
      ...
      truncated = False
      if len(scored) > tolerance["max_candidate_count"]:
          scored.sort(key=lambda c: c["match_score"], reverse=True)
          original = len(scored)
          scored = scored[:tolerance["max_candidate_count"]]
          truncated = True
          _audit_log({...})
      ...
      return {"candidates": scored, "truncated": truncated}
  ```

  In `handle_inbound_patient_discovery_query`:

  ```python
  matcher_result = run_local_matcher_under_cross_network_tolerance(
      ..., query_id)
  candidate_set = matcher_result["candidates"]
  filtered_candidates = apply_sensitivity_overlay(
      candidate_set, authorization_context, query_id)
  ...
  response_payload = {
      ...
      "candidate_count_returned":  len(filtered_candidates),
      "candidate_count_truncated": matcher_result["truncated"],
      ...
  }
  ```

  **Option B (drop the field):** if the demo intentionally simplifies the response envelope, remove `candidate_count_truncated` from the response payload and update the recipe text's "Sample outbound federation response" example to match. The audit-log truncation event remains as the operational signal.

  Option A is preferred because the field is documented in the recipe text and downstream consolidation logic in step 5 may want to know that a particular responder returned a truncated candidate set. The fix is mechanical.

---

### Finding 3: `_emit_metric` Hardcodes `Unit="Count"` for All Metrics; the `OverlayApplicationRate` Metric Is a 0-1 Rate Rather Than a Count

- **Severity:** NOTE
- **File:** `chapter05.09-python-example.md`
- **Location:** `_emit_metric` helper definition (line 494); the `OverlayApplicationRate` emission in `apply_sensitivity_overlay` (line 1520)
- **Description:**

  The helper hardcodes the unit:

  ```python
  def _emit_metric(metric_name: str, value: float,
                    dimensions: dict = None) -> None:
      try:
          cloudwatch_client.put_metric_data(
              Namespace=CLOUDWATCH_NAMESPACE,
              MetricData=[{
                  "MetricName": metric_name,
                  "Value": value,
                  "Unit": "Count",
                  "Dimensions": [
                      {"Name": k, "Value": v}
                      for k, v in (dimensions or {}).items()
                  ],
              }],
          )
      ...
  ```

  Most emit sites use the helper for actual counts (`InboundQueryRejected`, `InboundQueryDenied`, `InboundResponseDelivered`, `LocalMatcherCandidates`, `OverlaySuppressed`, `OutboundQuerySubmitted`, `OutboundResponsesConsolidated`, `DocumentsRetrieved`), so `Unit="Count"` is correct for those.

  But `apply_sensitivity_overlay` emits a rate:

  ```python
  _emit_metric("OverlayApplicationRate",
                float(suppressed_count) / max(len(candidate_set), 1),
                dimensions={"Purpose":
                                authorization_context["exchange_purpose"]})
  ```

  The value is `suppressed_count / total_candidates`, a 0-1 rate. CloudWatch accepts the value but labels it as a count, which is misleading for any downstream alarm or dashboard that expects rate semantics.

  Same chapter pattern as recipes 5.7 and 5.8's identical findings: a reader extending the demo with score-distribution metrics or per-cohort linkage-rate metrics inherits the hardcoded `Unit="Count"`, which is misleading for 0-1 confidence values and rate values.

- **Suggested fix:** Add an optional `unit` parameter with a `Count` default, matching the recipe 5.7 and 5.8 fix:

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

  Then update the `OverlayApplicationRate` emit site to pass `unit="None"` (CloudWatch's standard unit for ratio-style values):

  ```python
  _emit_metric("OverlayApplicationRate",
                float(suppressed_count) / max(len(candidate_set), 1),
                dimensions={"Purpose":
                                authorization_context["exchange_purpose"]},
                unit="None")
  ```

  The fix is mechanical and makes the helper composable for future score-emit additions.

---

### Finding 4: `MockSecretsCustody.get_qhin_public_keys(include_previous=False)` Filters by Key Versions Ending With the Literal String "active"; No Demo Key Version Has That Suffix, So the False Branch Returns an Empty Dict If Ever Called

- **Severity:** NOTE
- **File:** `chapter05.09-python-example.md`
- **Location:** `MockSecretsCustody.get_qhin_public_keys` (around line 622)
- **Description:**

  The method's `include_previous=False` branch:

  ```python
  def get_qhin_public_keys(self, qhin_id: str,
                                include_previous: bool = True
                                ) -> dict:
      ...
      keys = self._qhin_public_keys.get(qhin_id, {})
      return dict(keys) if include_previous else {
          k: v for k, v in keys.items() if k.endswith("active")
      }
  ```

  Filters the keys dict to only the entries whose key (the version string) ends with the literal substring "active". The demo's QHIN public keys are stored under version `"v-2026-q2-001"`:

  ```python
  self._qhin_public_keys = {
      "qhin-example-eastern-network": {
          "v-2026-q2-001": secrets.token_bytes(32),
      },
      ...
  }
  ```

  Neither `"v-2026-q2-001"` nor any other demo version string ends with `"active"`. So `get_qhin_public_keys(qhin_id, include_previous=False)` returns an empty dict regardless of which QHIN id is passed.

  The branch is not exercised in the demo (every call site uses the default `include_previous=True`), so the bug is silent. But the implementation does not match what the comment promises:

  ```python
  """Acquire the QHIN's known public-signing-key versions.
  Includes the prior version during the rotation window
  so signatures produced before the cutover still verify."""
  ```

  The comment says "the prior version is included during rotation," implying the inverse (when `include_previous=False`, return only the active version, not the prior one). The implementation filters by a string suffix that doesn't exist on any of the demo's version names.

  Pedagogical impact:

  1. **A reader extending the demo with a separate "current versions only" code path (e.g., for the originating-participant signature on a fresh outbound query that should not validate against the prior version) inherits a broken filter.** The filter as written would return an empty dict and produce a `False` validation result for every signature, which would surface as a hard bug at integration time.
  2. **The "active" string suffix is a leftover from a versioning scheme not used in the demo.** Production deployments may indeed have a version-naming convention that includes "active" as part of the version string (e.g., `v3-active`), in which case the filter would work; but the demo does not use such a convention and the filter is dead code.

- **Suggested fix:** Either fix the filter to identify the active version by a separate `_active_version` field (the way `_participant_active_version` already works for the participant's own keys) or drop the `include_previous=False` branch entirely:

  ```python
  def get_qhin_public_keys(self, qhin_id: str,
                                include_previous: bool = True
                                ) -> dict:
      """Acquire the QHIN's known public-signing-key versions.
      With include_previous=True (the default), returns both the
      currently-active version and any prior versions still
      valid during the rotation catch-up window. With
      include_previous=False, returns only the currently-active
      version. Production tracks the active version in a
      separate field; the demo treats the most-recently-added
      version as active."""
      ...
      keys = self._qhin_public_keys.get(qhin_id, {})
      if include_previous:
          return dict(keys)
      # Treat the last-added version as active. Production has
      # a separate _qhin_active_version dict that the rotation
      # ceremony updates atomically with the new key version.
      if not keys:
          return {}
      active_version = list(keys.keys())[-1]
      return {active_version: keys[active_version]}
  ```

  Alternatively, drop the `include_previous=False` branch entirely if the demo never needs the active-only path, and rename the parameter to `include_all_known_versions` for clarity. The current implementation is silently broken for any caller that ever passes `False`.

---

### Finding 5: `MockSecretsCustody._access_log` Accumulates Entries on Every Secret Access but Is Never Inspected; Dead Data in the Demo Run

- **Severity:** NOTE
- **File:** `chapter05.09-python-example.md`
- **Location:** `MockSecretsCustody.__init__` (line 594) and the three append sites in `get_participant_signing_key` (line 601), `get_qhin_public_keys` (line 619), `rotate_participant_key` (line 642)
- **Description:**

  Every secret-access call appends to an in-memory access log:

  ```python
  class MockSecretsCustody:
      def __init__(self):
          ...
          self._access_log: list = []

      def get_participant_signing_key(self, version=None):
          v = version or self._participant_active_version
          self._access_log.append({
              "operation":    "get_participant_signing_key",
              "version":      v,
              "timestamp":    _now_iso(),
          })
          ...

      def get_qhin_public_keys(self, qhin_id, include_previous=True):
          self._access_log.append({
              "operation":    "get_qhin_public_keys",
              "qhin_id":      qhin_id,
              "timestamp":    _now_iso(),
          })
          ...

      def rotate_participant_key(self, new_version, dual_control_approvers):
          ...
          self._access_log.append({
              "operation":     "rotate_participant_key",
              ...
          })
  ```

  The log is appended to but never read in the demo. No print statement, no assertion, no audit-archive write. After `run_demo()` completes, the log holds dozens of entries that are immediately garbage-collected when the process exits.

  Pedagogical impact:

  1. **The log's intent (cite a secret-access pattern that production would surface to CloudTrail or a dedicated audit substrate) is invisible to the reader because nothing in the demo demonstrates the consumption side.** A reader might reasonably conclude that the access log is dead infrastructure with no operational value.
  2. **The recipe text explicitly mentions CloudTrail data events on the QHIN-credentials Secrets Manager secrets and the signing-key KMS keys** as production-required. The demo's `_access_log` is the analogue, but the demo doesn't exercise it.

- **Suggested fix:** Either drop `_access_log` from the mock entirely (acknowledging that production uses CloudTrail and the demo's mock omits the audit-trail capture), or surface the log at the end of `run_demo()` to demonstrate the consumption pattern:

  **Option A (drop the log):** remove the `_access_log` field and the three `append` sites, with an inline comment in the class docstring noting that production has CloudTrail data events on every Secrets Manager and KMS access. This reduces the mock's surface to what the demo actually uses.

  **Option B (surface the log):** add a print at the end of `run_demo()` that summarizes the secret-access log:

  ```python
  print()
  print("-" * 72)
  print("Secret-access audit summary")
  print("-" * 72)
  ops_by_type = {}
  for entry in secrets_custody._access_log:
      ops_by_type[entry["operation"]] = (
          ops_by_type.get(entry["operation"], 0) + 1)
  for op, count in sorted(ops_by_type.items()):
      print(f"  {op:<35} {count:>4}")
  ```

  Option A is preferred for a teaching snippet because it reduces the cognitive load (one fewer field for the reader to trace). Either way, the current state (log appended but never consumed) is dead infrastructure.

---

### Finding 6: Mock Other-Participant Handler Does Not Apply IAS-Specific Demographic Suppression; Flow 2's Consolidated View Shows City/State/Zip Despite the Canonical Handler's `_extract_disclosable_features` Policy

- **Severity:** NOTE
- **File:** `chapter05.09-python-example.md`
- **Location:** `_make_inbound_handler_for_other_participant` inner handler's candidate envelope construction (around line 2120); the canonical `_extract_disclosable_features` (line 1358)
- **Description:**

  The canonical handler implements an IAS-specific feature suppression policy:

  ```python
  def _extract_disclosable_features(mpi_record: dict,
                                            exchange_purpose: str) -> dict:
      """..."""
      if exchange_purpose == "individual_access_services":
          return {
              "given_name":   mpi_record["given_name"],
              "family_name":  mpi_record["family_name"],
              "dob":          mpi_record["dob"],
              "sex_or_gender": mpi_record["sex_or_gender"],
              # Address suppressed for IAS to limit
              # re-identification risk on near-match candidates.
          }
      return {
          "given_name":   mpi_record["given_name"],
          "family_name":  mpi_record["family_name"],
          "dob":          mpi_record["dob"],
          "sex_or_gender": mpi_record["sex_or_gender"],
          "city":         mpi_record["city"],
          "state":        mpi_record["state"],
          "zip_code":     mpi_record["zip_code"],
      }
  ```

  But the mock other-participant handler in `_make_inbound_handler_for_other_participant` always includes the full feature set:

  ```python
  scored.append({
      "opaque_record_token": ...,
      "disclosable_demographic_features": {
          "given_name":   r["given_name"],
          "family_name":  r["family_name"],
          "dob":          r["dob"],
          "sex_or_gender": r["sex_or_gender"],
          "city":         r["city"],
          "state":        r["state"],
          "zip_code":     r["zip_code"],
      },
      ...
  })
  ```

  No conditional on `exchange_purpose`. The mock handler discloses city/state/zip on every response regardless of the exchange purpose.

  Demo impact: Flow 2 (patient-mediated IAS query for Sarah Mitchell) routes through the mock handlers. Each mock other participant returns a candidate with the full feature set including city/state/zip. The consolidated presentation view at the originator shows:

  ```
  IAS feature_keys:  ['city', 'dob', 'family_name', 'given_name', 'sex_or_gender', 'state', 'zip_code']
  ```

  Seven keys including the address fields the canonical IAS policy is supposed to suppress.

  The recipe text acknowledges this in the closing prose:

  > The Flow 2 IAS feature_keys list shows the full city/state/zip set in the consolidated-demographic view because each responding participant in the demo returns its own full feature set; in production each responder applies its own IAS-disclosure policy independently, and the participant's own responses (governed by the demo's `_extract_disclosable_features` policy) suppress city/state/zip on IAS responses.

  So the simplification is documented. But the document-the-gap-and-leave-the-code framing is pedagogically weaker than implementing the gap consistently. A reader who runs the demo sees one half of the recipe's IAS policy enforced (in the canonical handler's response, which the demo does not exercise from the originator side because the originator does not respond to itself) and the other half not enforced (in the mock handlers, which is what the demo actually exercises).

  Pedagogical impact:

  1. **The demo's main IAS demonstration is in Flow 2, but Flow 2 doesn't actually exercise the IAS suppression policy.** The canonical handler's IAS-specific code path runs only on inbound queries to the originator, which Flow 3 demonstrates but the IAS suppression is not the focus of Flow 3 (Flow 3 is about rejection scenarios).
  2. **A reader extending the demo to demonstrate IAS suppression cleanly would update the mock handlers to honor the policy.** The current state forces the reader to read the recipe text's footnote to understand why the demo's behavior contradicts the recipe's stated policy.

- **Suggested fix:** Update `_make_inbound_handler_for_other_participant`'s candidate envelope to call `_extract_disclosable_features` on the responding side, mirroring the canonical handler:

  ```python
  scored.append({
      "opaque_record_token": ...,
      "disclosable_demographic_features":
          _extract_disclosable_features(r, exchange_purpose),
      "source_organization_attribution": {...},
      ...
  })
  ```

  After the fix, re-run Flow 2 and confirm the printed `IAS feature_keys` shows the four-key suppressed set:

  ```
  IAS feature_keys:  ['dob', 'family_name', 'given_name', 'sex_or_gender']
  ```

  The expected output in the recipe text would need updating to match. The closing prose's acknowledgment of the simplification can then be replaced with a brief note that the demo demonstrates the IAS suppression at the responding-participant level uniformly. The fix is mechanical and improves the demo's pedagogical clarity.

---

### Finding 7: Private-Attribute Access on `secrets_custody._qhin_public_keys` and `secrets_custody._participant_signing_keys` from the QHIN Router and the Response Consolidator; Code Smell That a Public Accessor Would Resolve

- **Severity:** NOTE
- **File:** `chapter05.09-python-example.md`
- **Location:** `MockQHINFederationRouter.submit_outbound_query` (around line 1006); `consume_and_consolidate_responses` Step 5B signature validation (around line 1730); the inner handler returned by `_make_inbound_handler_for_other_participant` (around line 2167)
- **Description:**

  Three call sites reach into `secrets_custody`'s private state directly:

  1. **`MockQHINFederationRouter.submit_outbound_query`** loads the QHIN signing key by accessing the private dict:

     ```python
     qhin_keys = self._secrets_custody._qhin_public_keys.get(
         PARTICIPANT_QHIN_ID, {})
     ```

  2. **`consume_and_consolidate_responses` Step 5B** validates responder signatures by reaching into the private dicts:

     ```python
     responder_keys = (
         secrets_custody._participant_signing_keys
         if responder_id == PARTICIPANT_ID
         else dict(secrets_custody._qhin_public_keys.get(
             PARTICIPANT_QHIN_ID, {})))
     ```

  3. **`_make_inbound_handler_for_other_participant`** signs responses by reaching into the private dict:

     ```python
     _, qhin_key = (None,
                       secrets_custody._qhin_public_keys.get(
                           PARTICIPANT_QHIN_ID, {}).get(
                           "v-2026-q2-001"))
     ```

  These private-attribute accesses (the leading underscore is the Python convention for "private; do not access from outside the class") work in the demo but teach a code smell. Production code that wraps a Secrets Manager or KMS client in an abstraction layer should expose only the public methods (`get_participant_signing_key`, `get_qhin_public_keys`, etc.) and never let callers reach into the underlying storage directly. The demo's pattern would not pass a basic code review at most institutions.

  Pedagogical impact:

  1. **The mock has public accessor methods (`get_participant_signing_key`, `get_qhin_public_keys`) but the call sites bypass them.** A reader would reasonably ask why the public methods exist if the routes pivot to the private state.
  2. **The mock's `get_qhin_public_keys` returns `dict(keys)` (a copy), which prevents accidental mutation; the private-state access bypasses this safety**. A future addition that mutates the dict (e.g., a key-rotation simulation in-place) could break unrelated call sites.
  3. **A learner extending the demo to a real Secrets Manager integration cannot follow the same pattern**, because boto3 doesn't expose private state. The reader would have to refactor the call sites to use the public API anyway.

- **Suggested fix:** Add a public accessor for the QHIN signing key (the inverse of `get_qhin_public_keys`, which returns the verifier-facing key) and a public accessor for the participant's per-version signing key the consolidator can use for the self-signed-response path. Then update the three call sites:

  ```python
  class MockSecretsCustody:
      ...
      def get_qhin_signing_key_for_routing(self, qhin_id: str) -> tuple:
          """Acquire the QHIN's signing key for the routing
          layer's signature operations. Production has the QHIN
          and the participant operating in different security
          boundaries; the demo collapses them so the router
          uses the same key as the verifier."""
          keys = self._qhin_public_keys.get(qhin_id, {})
          if not keys:
              raise KeyError(
                  f"no QHIN signing key for {qhin_id}")
          version = next(iter(keys))
          return version, keys[version]
  ```

  Update the QHIN router:

  ```python
  qhin_key_version, qhin_signing_key = (
      self._secrets_custody.get_qhin_signing_key_for_routing(
          PARTICIPANT_QHIN_ID))
  if not qhin_signing_key:
      raise RuntimeError(
          "no QHIN signing key available for routing")
  request_signature = _sign_payload(
      inner_payload, qhin_signing_key, qhin_key_version)
  ```

  Update the consolidator:

  ```python
  if responder_id == PARTICIPANT_ID:
      version, key = secrets_custody.get_participant_signing_key()
      responder_keys = {version: key}
  else:
      responder_keys = secrets_custody.get_qhin_public_keys(
          PARTICIPANT_QHIN_ID)
  ```

  The fix is mechanical and demonstrates the right wrapping pattern for a teaching snippet. The demo's behavior is unchanged.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Function | Consistent? |
|----------------|-----------------|-------------|
| `handle_inbound_patient_discovery_query(request_payload, request_signature, request_metadata)` | `handle_inbound_patient_discovery_query` plus `_build_rejection_response`, `_build_purpose_denied_response` | Mostly yes (1A validates the QHIN's request signature against the QHIN's known public-signing-key versions including the prior version during rotation; 1B validates the originating-attribution chain against `PARTICIPANT_AUTHORIZED_QHINS`; 1C validates the exchange-purpose claim against `PARTICIPANT_AUTHORIZED_EXCHANGE_PURPOSES` with the explicit `PrivacyException` denial path; 1D builds the authorization context the local matcher consults; 1E persists the federation-attribution chain; 1F dispatches to Step 2; 1G applies Step 3; 1H signs and returns the response). The four rejection paths (`InvalidQHINSignature`, `UnauthorizedOriginatorQHIN`, `UnauthorizedPurpose` denied under `PrivacyException`, and the validated-and-accepted path) are all exercised in Flow 3. **The address-feature handling per Finding 1 reads `address_line` only, not the QTF-canonical `address_line_1`, so real QHIN traffic would silently drop the address feature.** **The response envelope's `candidate_count_truncated` is hardcoded to `False` per Finding 2.** |
| `run_local_matcher_under_cross_network_tolerance(demographic_features, authorization_context, query_id)` | `run_local_matcher_under_cross_network_tolerance` plus `_compute_per_feature_similarities`, `_combine_with_fellegi_sunter`, `_extract_disclosable_features`, `_compute_cohort_axis_hashes` | Mostly yes (2A loads the cross-network tolerance per exchange purpose from `CROSS_NETWORK_TOLERANCE_BY_PURPOSE`; 2B normalizes the demographic features; 2C iterates the MPI's blocked candidates; 2D applies the consent-and-Part-2 filter at candidate-evaluation time before scoring, then computes per-feature similarity, combines via weighted Fellegi-Sunter, accepts above the candidate-acceptance threshold; 2E truncates to `max_candidate_count` with audit-log capture). **The per-feature similarity for missing values returns Decimal("0.0") rather than the recipe's Step 2D distinguishing-missing-cases pattern; the demo's records all have populated demographics so this does not surface.** The Fellegi-Sunter combiner is a weighted-average rather than the production log-likelihood-ratio implementation; the simplification is acknowledged inline. **The `_local_record_id` retained-internally pattern is correctly implemented (the field has the underscore prefix that Step 3 strips before disclosure).** |
| `apply_sensitivity_overlay(candidate_set, authorization_context, query_id)` | `apply_sensitivity_overlay` plus `MockJurisdictionalOverlays.applicable_overlays` | Yes (3A iterates each candidate; 3B looks up the source MPI record by `_local_record_id`; 3C consults the overlay engine for the applicable overlays; 3D drops the candidate when any suppressing overlay applies, audit-logging the suppression with the overlay_id and reason; 3E strips the `_local_record_id` before disclosure). The two overlay variants demonstrated in Flow 4 (`post_dobbs_v3` for `state-with-criminal-prohibition-1` and `post_dobbs_v3` for `state-with-criminal-prohibition-2`) are wired correctly. The 42 CFR Part 2 overlay is handled at Step 2D (consent-and-Part-2 filter at candidate-evaluation time) rather than at Step 3, which is acknowledged in the inline comment. |
| `originate_outbound_patient_discovery_query(user_or_patient_identity, requested_demographics, exchange_purpose, use_case_context)` | `originate_outbound_patient_discovery_query` plus `_build_attribution_chain` | Yes (4A loose authentication of the originator with the patient-mediated flag preserved through the attribution chain; 4B validates the participant's authorization for the exchange purpose; 4C formulates the query payload; 4D builds the originating-attribution chain; 4E signs the query under the participant's signing credential; 4F submits to the QHIN router and captures the federation handle for the consolidator). The `_IN_MEMORY_FEDERATION_HANDLES` mapping demonstrates the (federation_handle → query_id) join the consolidator depends on. **The outbound formulator translates `address_line` to `address_line_1` per the QTF spec; the asymmetry with the local inbound handler per Finding 1 is the core of the WARNING.** |
| `consume_and_consolidate_responses(federation_handle, query_id, response_window_seconds, use_case_context)` | `consume_and_consolidate_responses` | Mostly yes (5A pulls responses from the router; 5B validates each responder's signature against the appropriate key set with the responder-id branching; 5C handles rejection-and-purpose-denied envelopes by audit-logging without consolidating; 5D normalizes the candidate envelopes across responders; 5E groups by `(family_name, dob)` for federated-resolution; 5F applies the use-case-specific presentation filter with branches for public_health (aggregate-only), treatment, and IAS; 5G computes the completeness indicator). **The signature validation branches into private-attribute access per Finding 7.** The synchronous-demo shortcut is acknowledged inline ("Production listens against an SQS queue or a WebSocket; the demo returns the in-memory list"). |
| `execute_document_query_and_retrieval(selected_candidates, user_or_patient_identity, use_case_context, query_id)` | `execute_document_query_and_retrieval` plus `_retrieve_documents_for_candidate` | Yes (6A formulates per-candidate document-query requests; 6B persists with attribution metadata to the document-store bucket; 6C emits the cross-recipe `tefca_query_completed` event). The synthetic-document stub is acknowledged inline ("the demo synthesizes a small number of documents per candidate so the pipeline trace exercises the persistence and attribution paths"). The Step Functions orchestration is collapsed into the in-process call as documented in the Heads-up. |

Intentional deviations clearly framed:

- The Sequoia Project RCE handshake, the Common-Agreement-compliant authentication, the QTF-format messages, the IHE XCPD/XCA, and the FHIR Patient $match operation are all named in the Heads-up as out-of-scope.
- The HMAC-SHA-256 in-process keys stand in for KMS-backed asymmetric signing (RSA-PSS or ECDSA). Documented inline ("Production uses KMS asymmetric Sign with RSA-PSS or ECDSA; the demo uses HMAC-SHA-256 for simplicity").
- The hand-rolled `_jaro_winkler` stands in for `jellyfish`. Documented inline.
- The `MockSecretsCustody`, `MockLocalMPI`, `MockConsentStore`, `MockJurisdictionalOverlays`, and `MockQHINFederationRouter` replacements for production dependencies are clearly framed and exercise the major paths.
- The synchronous in-process router stands in for the QHIN's HTTPS-over-mTLS exchange. Documented inline.
- The Cognito patient-portal IdP becomes the `is_patient_mediated` flag in the originator dict. Documented inline.
- The Step Functions orchestration, multiple Lambdas, multiple Glue jobs, and SQS-driven worker pattern collapse into a single Python file. Documented at the top.
- The DynamoDB read/write paths fall back to in-memory dicts (`_IN_MEMORY_FEDERATION_ATTRIBUTION`, `_IN_MEMORY_FEDERATION_HANDLES`). Documented.
- The dual-control salt-rotation ceremony pattern is implemented in `MockSecretsCustody.rotate_participant_key` but is not exercised in `run_demo()`; recipe 5.8's review noted that 5.8 explicitly demonstrates the dual-control success-and-rejection paths in Phase 2. **5.9's demo defines the same enforcement but does not invoke it from `run_demo`**; this is a documentation-only gap rather than a code bug.
- The cohort-stratified accuracy monitoring computes `_compute_cohort_axis_hashes` on each candidate envelope but the demo does not aggregate or alarm. Acknowledged in Gap to Production.

The substantive deviations (Findings 1, 2, 3) are the consistency gaps that carry pedagogical consequence. The acknowledged simplifications (mock secrets custody, mock MPI, mock consent, mock overlays, mock QHIN router, in-memory tables) are clearly framed.

---

## AWS SDK Accuracy

| API Call | Method | Notes |
|----------|--------|-------|
| S3 PutObject | `s3_client.put_object(Bucket=..., Key=key, Body=body, ServerSideEncryption="aws:kms")` | Correct. Body is bytes-encoded JSON with `default=str` to handle Decimal. Keys use `{partition}/{date}/{key_id}.json` with no leading slashes. The audit-archive S3 writes for inbound query events, response delivery, document retrieval, and overlay applications follow the same pattern. |
| EventBridge PutEvents | `eventbridge_client.put_events(Entries=[{Source, DetailType, EventBusName, Detail}])` | Correct shape. `Detail` is JSON-serialized with `default=str` to handle Decimal. One detail-type emitted: `tefca_query_completed` from `execute_document_query_and_retrieval`. The recipe text mentions additional event types (`tefca_dispute_raised`, `tefca_dispute_resolved`, `tefca_governance_event_received`, `tefca_consent_withdrawn`, `tefca_credential_rotated`) but the demo emits only the completion event; the rest are acknowledged in Gap to Production. |
| CloudWatch PutMetricData | `cloudwatch_client.put_metric_data(Namespace, MetricData=[{MetricName, Value, Unit, Dimensions}])` | Correct shape. Eleven metric names appear: `InboundQueryRejected`, `InboundQueryDenied`, `InboundResponseDelivered`, `LocalMatcherCandidates`, `OverlaySuppressed`, `OverlayApplicationRate`, `OutboundQuerySubmitted`, `OutboundResponsesConsolidated`, `DocumentsRetrieved`, plus the response-rejection variants. **`Unit="Count"` is hardcoded per Finding 3, but is correct for all current emissions except `OverlayApplicationRate` which is a 0-1 rate.** |
| KMS / DynamoDB / SQS / Step Functions / Secrets Manager | (referenced in setup; not actually called) | The Setup section names the IAM permissions on the federation-attribution and audit-event-log DynamoDB tables, the document-store and audit-archive S3 buckets, the dispute and governance SQS queues, the federation-events EventBridge bus, the QHIN-credentials and signing-key Secrets Manager secrets, the customer-managed KMS keys, and the document-query Step Functions state machine. The demo does not actually call these services; the `MockSecretsCustody`, `MockQHINFederationRouter`, in-memory dicts, and best-effort S3/EventBridge/CloudWatch calls stand in. The boto3 client setup is correct (clients constructed at module level with adaptive retries). |

The SDK-level concerns are limited to Finding 3 (Unit hardcoded). All API surfaces named in the demo are current and correct.

---

## DynamoDB and Data Type Check

- `_to_decimal` correctly uses `Decimal(str(value))` and short-circuits on already-Decimal inputs.
- `_serialize_for_dynamodb` recursively walks dicts, lists, tuples, and sets; converts floats to Decimal. The pattern is safe for serializing match scores and similarity scores into DynamoDB-bound payloads, though the demo never actually writes to DynamoDB.
- Threshold constants in `CROSS_NETWORK_TOLERANCE_BY_PURPOSE` are constructed as Decimals (`Decimal("0.55")`, `Decimal("0.85")`, `Decimal("0.92")`) at module load time. The `FEATURE_WEIGHTS` are also Decimals.
- Match scores returned from `_combine_with_fellegi_sunter` are Decimals throughout. Comparison with the threshold constants is Decimal-vs-Decimal. No int/float coercion issues.
- Per-feature similarity scores from `_compute_per_feature_similarities` are Decimals (`Decimal("1.0")`, `Decimal("0.0")`, or `_jaro_winkler` Decimal output). Correct.
- The `_jaro_winkler` computation does Decimal arithmetic throughout (`Decimal(matches) / Decimal(len1)`, etc.). Returns Decimal.
- The CloudWatch `Value` parameter uses `float(...)` casts where needed. Correct (CloudWatch accepts native floats).
- The EventBridge `Detail` flows through `json.dumps(..., default=str)`, which handles Decimal serialization.
- The S3 archive flow through `json.dumps(payload, default=str)` similarly handles Decimals.
- The `_sign_payload` and `_verify_signature_against_any` use `json.dumps(payload, sort_keys=True, default=str)` for canonical serialization, which handles Decimals consistently between signing and verification.

The Decimal discipline is correct. No type-handling bugs. Note that the demo never actually writes to DynamoDB (all persistence is in-memory), so the Decimal discipline is preserved as a teaching pattern rather than a runtime requirement.

---

## S3 and Credentials Check

- The example uses S3 only for archive writes (`AUDIT_ARCHIVE_BUCKET`, `DOCUMENT_STORE_BUCKET`). No leading slash on any key. The `_archive_to_s3` helper formats keys as `f"{partition}/{today}/{kid}.json"` where `partition` is a non-slashed prefix.
- The deploy-time guardrail covers every resource-name constant via the `for _name, _value in [...]: assert _value` loop. **No constant can silently be empty.** Same discipline as recipes 5.4-5.8.
- No hardcoded credentials. Module-level boto3 clients use the documented environment credential chain.
- The IAM permissions list in Setup matches the API surface used by the code (DynamoDB GetItem/PutItem/UpdateItem/Query/BatchGetItem/TransactWriteItems on the five named tables, S3 PutObject/GetObject on the document-store and audit-archive buckets, SQS SendMessage/ReceiveMessage on the dispute and governance queues, EventBridge PutEvents on the federation-events bus, CloudWatch PutMetricData, KMS Decrypt/GenerateDataKey on the customer-managed keys, Secrets Manager GetSecretValue on the rotation-pinned secrets, KMS Sign on the active signing-key version with explicit per-rotation scoping, Cognito AdminGetUser for patient-portal flows, Step Functions StartExecution/DescribeExecution for the document-query orchestrator).
- The Setup section explicitly names that "tutorial-level permissions above are fine for learning and will fail any serious IAM review" with the right framing about the inbound-query-handler's read-only access to the local MPI, the outbound-query-formulator's per-rotation Secrets Manager binding, the patient-portal Cognito-authenticated separation from staff-initiated queries, and per-Lambda role scoping to specific resource ARNs.
- The PHI framing is clear: the demographic-feature payload of inbound queries, the candidate-record envelopes, the sensitivity-overlay decisions, and the per-document attribution all carry PHI-adjacent information that should not leak through logs. The logger setup correctly limits logging to structural metadata (query_id, cycle_id, attribution-chain summary, decision band, exchange purpose) and explicitly excludes demographic values, candidate disclosable features, and document contents from cross-participant context.
- The Heads-up section names the synthetic-data discipline: "The synthetic patients and demographics in the demo are fictional; the names, DOBs, addresses, and other identifiers are obviously made-up and should not match anyone real."
- The Gap to Production section names the QHIN Participant Agreement and operational onboarding as a multi-month program, the QHIN-credential and signing-key rotation ceremony with HSM-backed custody and dual-control approval, the cross-network-tolerance calibration and approval governance, the three review queues with cohort-and-cycle-aware tooling, the patient-consent capture and withdrawal pathways, the information-blocking-exception handling automation, the cross-jurisdictional overlay automation with regulatory-monitoring triggers, the cohort-stratified accuracy monitoring with disparity alarms, the capacity coordination through the QHIN's operational interface, the KMS-encrypted-everything posture, the VPC + VPC endpoints + PrivateLink, the CloudTrail data events on every consequential operation, the Lake Formation column-level access control on the analytics surface, and the federation-participation governance program with named owners, named processes, named milestones, and named review committees. The breadth honestly tells the reader how much operational discipline sits between the recipe and a production deployment.

Pass.

---

## Comment Quality Assessment

Comments consistently explain the "why":

- The Heads-up at the top names every major production gap before the code starts (no real Sequoia Project RCE handshake, no real Common-Agreement-compliant authentication, no real QTF-format messages, no real IHE XCPD or XCA, no real FHIR Patient $match, no real cross-account exchange or PrivateLink, no real mTLS or signed-request validation, no Step Functions orchestration, no real DynamoDB or Aurora wiring, no SageMaker calibration loop, no Glue jobs, no information-blocking-exception engine, no IAM/KMS/VPC/WAF/CloudTrail wiring).
- The "things worth knowing upfront" list correctly names the QHIN-signed-request-envelope-as-authentication-root-of-trust posture, the cross-network-matching-tolerance-calibrated-separately-from-internal-tolerance discipline, the per-record-type-and-per-jurisdiction sensitivity-overlay enforcement, the opaque-record-token decoupling federation-visible identifiers from local record identifiers, the federated-responses-arrive-asynchronously-with-varying-latencies pattern, the per-hop-attribution-as-audit-substrate commitment, the information-blocking-compliance-as-architectural-concern framing, and the Decimal-at-the-DynamoDB-boundary discipline as the load-bearing structural commitments.
- The cross-network-tolerance calibrated-separately commitment is named in `CROSS_NETWORK_TOLERANCE_BY_PURPOSE`'s inline comment ("Calibrated SEPARATELY from the internal-application matcher's thresholds in recipe 5.1. The cross-network tolerance is typically higher-recall (lower acceptance threshold) than the internal tolerance because the federation expects the participant to surface plausible matches that the originating user can disambiguate at the candidate-presentation step. Treatment is the default; individual access services has the highest precision (because the patient is being shown her own records and a wrong-record disclosure is a privacy event); public health has the highest recall (because the analytics can tolerate false positives at the cohort level).").
- The per-feature weights' calibration rationale is named in `FEATURE_WEIGHTS`'s inline comment ("DOB carries strong weight because it's the most stable discriminating feature across organizations; SSN-last-4 is weighted but often missing in the federation's payloads (the QTF specifies SSN handling carefully because of disclosure concerns).").
- The opaque-record-token semantics are explained inline ("The cross-network exchange never carries the local record identifier; production deployments that leak the local identifier through the federation create a privacy and operational-coupling concern that the framework explicitly avoids.").
- The signature-authentication-root-of-trust commitment is named ("Every inbound query carries a request signature produced by the participant's QHIN under the QHIN's current signing-key version. The signature is verified against the QHIN's known public-signing-key version (with the prior version retained during the rotation window). A failed signature validation is a hard reject, not a soft warning; mis-signed queries are dropped and audit-logged with the rejection reason.").
- The information-blocking-compliance-as-architectural-concern framing is named ("A query the local matcher cannot resolve confidently in the response window has to be either responded to with a 'no-confident-match' indication or escalated to a slower-tier review process. Silent drops are operationally non-compliant under the 21st Century Cures Act information-blocking rule.").
- The synchronous-demo simplifications are acknowledged at the top: "The example collapses Step Functions, multiple Lambdas, the QHIN integration, the cross-account exchange, the SQS-driven worker pattern, and the Cognito patient-portal IdP into a single Python file for readability."
- The mock-as-stand-in framing is clear in `MockSecretsCustody`, `MockLocalMPI`, `MockConsentStore`, `MockJurisdictionalOverlays`, and `MockQHINFederationRouter` with explicit production-extension notes ("Production never returns plaintext signing-key material to Python application code; KMS Sign operations call into the KMS context for asymmetric signing"; "Production has indexes on the demographic-feature blocking keys, full-text search, and per-record sensitivity flags"; "Per-record consent posture is captured at intake and updated over time"; "Production has a versioned rule store with attorney-reviewed rules per jurisdiction, per record-type sensitivity classification, and per exchange-purpose authorization scope"; "In production this is an HTTPS-over-mTLS endpoint at the QHIN that receives outbound queries from participants").
- The synthetic-data labeling is unambiguous in the demo runner.
- The dual-control-approval requirement on participant-key rotation is named in `MockSecretsCustody.rotate_participant_key` ("Production requires dual-control approval; rotation is audit-logged with both operator identities") even though the demo does not exercise the path.
- The cross-network-vs-internal-tolerance dual-calibration discipline is named throughout.
- The forward-only nature of consent withdrawal is named in `MockConsentStore.withdraw_consent` ("Forward-only: future cross-network queries exclude the record; prior disclosed records remain in the recipients' possession (the framework does not support retraction)").
- The Gap to Production section is unusually thorough (15+ items spanning real QHIN integration through the Sequoia Project's QHIN-designation process, IHE-and-FHIR message construction, mTLS-and-KMS-backed signing, HSM-backed credential rotation ceremony, real DynamoDB schema, TransactWriteItems for atomic cross-table writes, real Aurora PostgreSQL local MPI, real Step Functions orchestration, real cross-account S3 buckets with PrivateLink, real EventBridge bus with cross-recipe consumer subscriptions, real Cognito patient-portal IdP, idempotency keys on every write, cross-network-tolerance calibration with SageMaker and pilot-data infrastructure, real Splink-or-`recordlinkage` and `jellyfish` for the local matcher, cross-jurisdictional overlay automation with regulatory-monitoring triggers, patient-consent capture and withdrawal pathways, information-blocking-exception handling automation, three review queues with cohort-and-cycle-aware tooling, cohort-stratified accuracy monitoring with disparity alarms, capacity coordination through the QHIN's operational interface, KMS-encrypted everything, VPC + VPC endpoints + PrivateLink, CloudTrail data events on every consequential operation, Lake Formation column-level and row-level access control on the analytics surface, QHIN Participant Agreement and operational onboarding, federation-participation governance program). The breadth honestly tells the reader how much operational discipline sits between the recipe and a production deployment.

The comments that would benefit from updates per the findings:

- `run_local_matcher_under_cross_network_tolerance` step 2B's address normalization would benefit from accepting either `address_line` or `address_line_1` per Finding 1.
- `handle_inbound_patient_discovery_query`'s response payload construction would benefit from threading the truncation flag from the matcher per Finding 2.
- `_emit_metric` would benefit from an optional `unit` parameter per Finding 3, and the `OverlayApplicationRate` emit site updated to pass `unit="None"`.
- `MockSecretsCustody.get_qhin_public_keys` would benefit from either fixing or dropping the `include_previous=False` branch per Finding 4.
- `MockSecretsCustody._access_log` would benefit from either being surfaced at the end of `run_demo()` or dropped entirely per Finding 5.
- `_make_inbound_handler_for_other_participant` would benefit from calling `_extract_disclosable_features` for IAS suppression consistency per Finding 6.
- The QHIN router and the response consolidator would benefit from public accessor methods on `MockSecretsCustody` rather than reaching into private state per Finding 7.

Calibration is otherwise appropriate for a mixed audience.

---

## Healthcare-Specific Requirements

- **PHI discipline.** The Heads-up section frames the PHI-adjacent posture correctly: the demographic-feature payload of inbound queries, the candidate-record envelopes, the sensitivity-overlay decisions, and the per-document attribution all carry information that should not leak through logs. The logger setup correctly limits logging to structural metadata (query_id, cycle_id, attribution-chain summary, decision band, exchange purpose) and explicitly excludes demographic values, candidate disclosable features, and document contents from cross-participant context.
- **Synthetic data labeling.** Sample patient IDs (`amc-richmond-mrn-00284271`, `amc-richmond-mrn-00891344`, etc.), DOBs, SSN-last-4 values, addresses, and phone numbers are obviously synthetic. The Heads-up section warns explicitly. The QHIN identifiers (`qhin-example-eastern-network`, `qhin-example-national-network`, `qhin-example-western-network`) and participant identifiers (`participant-academic-medical-center-richmond`, `participant-virginia-hie`, `participant-national-pharmacy-data-network`) follow obvious example-only naming.
- **Decimal at the DynamoDB boundary.** Consistent. Defensive float-to-Decimal coercion in `_serialize_for_dynamodb` and at the score-construction boundary throughout the matcher. Note that the demo never actually writes to DynamoDB; the discipline is preserved as a teaching pattern.
- **S3 paths.** No leading slashes on any S3 key. The `_archive_to_s3` helper formats keys as `f"{partition}/{today}/{kid}.json"`.
- **Audit-archive every operation.** `_audit_log` is called at every consequential operation: inbound query accepted, inbound query signature rejected, inbound query attribution rejected, inbound query purpose denied, inbound query candidates truncated, overlay suppressed (per overlay), overlay applied (per query), inbound response delivered, outbound query submitted, outbound response received, outbound response rejected, outbound response denied, outbound response signature rejected, outbound view consolidated, documents retrieved. The audit log captures the structural metadata; the actual demographic content and document content are not duplicated into the audit log.
- **Provenance on every record.** Inbound responses carry `tolerance_version` and `overlay_rules_version`. Outbound query envelopes carry the originating-attribution chain. Audit-event records carry `matcher_config_version`, `tolerance_version`, and `overlay_rules_version`. A future audit can attribute a federated-resolution decision to the matcher version, the tolerance version, and the overlay-rules version active at decision time.
- **Append-only audit.** The audit-archive S3 writes are append-only by design (each event gets a unique S3 key under the `{partition}/{date}/{key_id}.json` pattern). Production extends with Object Lock in Compliance mode for immutability; the demo's append-only intent is correct.
- **Cohort-stratified telemetry.** `_compute_cohort_axis_hashes` produces SHA-256 truncated hashes for the four cohort axes (`geographic_region`, `age_decade`, `sex_or_gender`, `name_tradition`). The hashes are included in the candidate envelope for cohort-stratified accuracy monitoring without exposing the underlying axis values across the federation. The recipe text emphasizes that cohort axes flow through the federation as hashes; the implementation is correct.
- **Conservative thresholds.** Per-purpose acceptance and high-confidence thresholds are calibrated separately: treatment (0.55 / 0.85), payment (0.65 / 0.88), healthcare_operations (0.65 / 0.88), individual_access_services (0.85 / 0.92), public_health (0.50 / 0.80). The IAS purpose has the highest precision (rightly), and public_health has the highest recall (rightly).
- **Originating-attribution chain capture.** `_build_attribution_chain` produces the chain with `originating_user_or_patient_id`, `is_patient_mediated` flag, `originating_sub_participant_id`, `originating_qhin_id`, `requesting_jurisdiction`, `routing_path`, and `attribution_chain_hash`. The audit log captures the full chain on every query and response. This is the federated-audit-substrate the recipe text spends substantial prose on.
- **Information-blocking compliance posture.** The unauthorized-purpose query produces a structured `PrivacyException` denial envelope rather than a silent drop. Flow 3 demonstrates the path explicitly. The recipe text frames this as the canonical operational discipline; the demo demonstrates it.
- **Cross-jurisdictional sensitivity overlay.** Three overlays demonstrated (post-Dobbs reproductive-health-care, gender-affirming-care, mental-health-state-specific). The `MockJurisdictionalOverlays.applicable_overlays` produces per-candidate suppress decisions consulting the patient's record's sensitivity flags, the requesting jurisdiction, and the exchange purpose. Flow 4 demonstrates the suppression path explicitly.
- **Consent-and-Part-2 filter at candidate-evaluation time.** The matcher's Step 2D applies the consent filter before scoring, so records the patient has not consented to disclose for this exchange purpose are excluded from the candidate set entirely (avoiding the leakage of a "we have this record but won't disclose it" inference). The Part-2 substance-use-treatment record handling is part of the same filter.
- **Patient-mediated access first-class.** The `is_patient_mediated` flag flows through the attribution chain at every hop. Flow 2 demonstrates the patient-portal-authenticated flow; the IAS-specific tolerance is applied; the cohort-axis-hashes flow through the response (though the mock other-participant handler does not apply the IAS feature suppression per Finding 6).
- **Cross-recipe coordination.** The `_IN_MEMORY_FEDERATION_HANDLES` mapping demonstrates the (federation_handle → query_id) join the consolidator depends on. The recipe text mentions cross-recipe consumers from recipes 5.1 / 5.5 / 5.6 / 5.7 / 5.8 that subscribe to the federation-events bus; the demo emits the `tefca_query_completed` event but the cross-recipe consumers are not exercised.

Pass on the structural healthcare requirements (PHI handling, synthetic-data labeling, Decimal discipline at DynamoDB boundary intent, S3 path discipline, audit archive append-only intent, provenance on every record, cohort-stratified telemetry, conservative threshold posture per exchange purpose, originating-attribution chain capture, information-blocking compliance with `PrivacyException` denial, cross-jurisdictional sensitivity overlay, consent-and-Part-2 filter at candidate-evaluation time, patient-mediated access as first-class, cross-recipe coordination intent through the federation-events bus).

---

## Logical Flow

The file reads top-to-bottom in pedagogical order matching the pseudocode numbering: Setup, Configuration and Constants (logger, retry config, module-level clients, resource names with deploy-time guardrail, versioning, authorized exchange purposes, authorized QHINs, cross-network tolerance per exchange purpose, per-feature weights, response-window expectations, cohort axes, sensitivity flags), Helpers (Decimal coercion, name canonicalization, address normalization, phone normalization, Jaro-Winkler computation, SHA-256, DynamoDB serialization, audit-payload summary, attribution-chain builder, CloudWatch metrics, S3 archive, audit-log helper), Mock QHIN Router / Secrets Custody / Local MPI / Consent Store / Jurisdictional Overlays, Step 1 (handle inbound query with QHIN-signature validation, attribution-chain validation, exchange-purpose validation, dispatch to local matcher with sensitivity overlay, signed response), Step 2 (run local matcher under cross-network tolerance with consent-and-Part-2 filter at candidate-evaluation time, per-feature similarity, Fellegi-Sunter combination, candidate truncation), Step 3 (apply per-record-type and per-jurisdiction sensitivity overlay), Step 4 (originate outbound query with originator authentication, exchange-purpose validation, query formulation, attribution-chain build, signed query submission to QHIN router), Step 5 (consume responses with signature validation, normalization, grouping by patient identity, use-case-specific presentation filter, completeness indicator), Step 6 (per-candidate document query and retrieval with per-document attribution and cross-recipe event emission), Full Pipeline (`run_demo` plus four representative flows), Gap to Production.

Each step opens with a short italic prose paragraph that restates the pseudocode step before the code block, matching the cookbook's established pattern. The italic paragraphs name the step's role and the failure mode the step prevents.

The demo runner builds four flows. Flow 1 demonstrates the canonical staff-initiated treatment query (the ED-attending searching for the unconscious patient's longitudinal record across the federation). Flow 2 demonstrates patient-mediated individual-access-services (the patient pulling her own record through a personal-health-record app). Flow 3 demonstrates the inbound-query-validation discipline with four scenarios (valid, bad signature, unauthorized originator QHIN, unauthorized exchange purpose). Flow 4 demonstrates the cross-jurisdictional sensitivity overlay (the post-Dobbs reproductive-health-care suppression of Maria Garcia-Lopez's record from a requesting jurisdiction the demo treats as incompatible).

The closing prose paragraph after the expected output walks each flow's behavior with explicit references to the matcher's score-band routing (Flow 1 lands medium because the query is missing phone and SSN-last-4; Flow 2 lands high because the query includes the full feature set), the IAS feature_keys list with the documented limitation about the mock other-participant handler not applying the IAS suppression (which Finding 6 names as a pedagogical gap), the four Flow 3 rejection scenarios, and the Flow 4 overlay suppression. The narrative connects the synthetic data to the printed output to the architectural intent.

---

## What Is Done Particularly Well

Worth calling out explicitly:

- **The deploy-time guardrail covers every resource-name constant.** The for-loop pattern that asserts every constant is non-empty is consistent with recipes 5.4-5.8. A misconfigured constant produces a clean assertion message rather than a downstream `ValidationException` from boto3 or DynamoDB.
- **The QHIN-signature-validation discipline is the authentication root-of-trust** and is implemented as a hard reject in `handle_inbound_patient_discovery_query` step 1A. The verify function tries the version the envelope claims first, then falls back to other known versions for the rotation catch-up window. The `hmac.compare_digest` use is timing-safe.
- **The originating-attribution chain validation is a separate hard reject in step 1B**, distinct from signature validation. The chain check requires the originating QHIN id to be in `PARTICIPANT_AUTHORIZED_QHINS`. A query whose signature is valid but whose originating QHIN is not in the participant's authorized list is rejected with `UnauthorizedOriginatorQHIN`.
- **The exchange-purpose denial uses the `PrivacyException` envelope rather than a silent drop.** Flow 3's `bad purpose` test demonstrates the path. The recipe text frames this as the operational discipline that distinguishes information-blocking-compliant denial from silent-drop information-blocking violation; the demo demonstrates it.
- **The opaque-record-token decoupling is correctly implemented.** The candidate envelope carries `_local_record_id` (with the underscore prefix) for internal lookup at the canonical participant, and Step 3 strips it before disclosure (`outbound = {k: v for k, v in candidate.items() if not k.startswith("_")}`). The cross-network exchange never carries the local record identifier; the recipe text spends substantial prose on this commitment, and the demo demonstrates it.
- **The consent-and-Part-2 filter operates at candidate-evaluation time, before scoring.** This avoids the leakage of a "we have this record but won't disclose it" inference. Records the patient has not consented to disclose are excluded from the candidate set entirely, never scored, never visible in the audit log as evaluated-but-not-disclosed.
- **The cross-network-tolerance dual-calibration is structurally correct.** The `CROSS_NETWORK_TOLERANCE_BY_PURPOSE` table provides per-purpose acceptance and high-confidence thresholds; the per-purpose `max_candidate_count` bounds the response size to defeat deliberate-over-broadening attacks. The recipe text emphasizes that the cross-network tolerance is calibrated separately from the internal-application tolerance to avoid silent under-matching; the demo's per-purpose calibration demonstrates the discipline.
- **The per-jurisdiction overlay engine demonstrates the post-Dobbs reproductive-health-care suppression cleanly.** Flow 4 shows the path: Maria Garcia-Lopez's record carries the `reproductive_health_care` flag; the requesting jurisdiction is `state-with-criminal-prohibition-1`; the overlay engine produces a `suppress` decision with `overlay_id: post_dobbs_v3`; the candidate is dropped from the response with a `TEFCA_OVERLAY_SUPPRESSED` audit event; the response says `candidates returned: 0`. The suppression discipline matters at federation scale because per-state legal landscapes diverge in ways that the matcher's general framework cannot anticipate; the demo's two-jurisdiction demonstration is a stand-in for a much richer rule landscape.
- **The synthetic data covers the major matching scenarios.** Sarah Mitchell (high-confidence match across multiple participants), Maria Garcia-Lopez (overlay-suppressed for cross-jurisdictional reasons), James Patterson (Part 2 substance-use-treatment record, suppressed by consent filter), Chen Liu (East Asian name tradition, no flags). The demo's local MPI population stresses the right architectural axes (cohort-stratified-accuracy-monitoring axes, per-record-type sensitivity flags, per-cohort name-tradition diversity).
- **The QHIN router's mock implementation correctly preserves the routing-layer-signing discipline.** The router unwraps the originator's signed envelope and re-signs the inner payload with the QHIN's identity before forwarding. The receiving handler verifies against the QHIN's known public keys; the originating participant's identity flows through the attribution chain in the payload. The architecture pattern (every hop in the routing layer signs its forwarded message with the QHIN's identity) is structurally faithful to the recipe text.
- **Flow 3's four rejection scenarios are pedagogically strong.** The valid query produces a candidate; the tampered query (signature against a different payload) is rejected with `InvalidQHINSignature`; the unauthorized originator QHIN is rejected with `UnauthorizedOriginatorQHIN`; the unauthorized exchange purpose is denied under `PrivacyException`. The reader sees the four authentication-and-authorization paths exercised in a single flow with explicit expected output for each.
- **The closing prose accurately describes what each flow demonstrates** and acknowledges the score-band-vs-feature-completeness relationship (Flow 1 is medium because the ED attending's query is missing phone and SSN; Flow 2 is high because the query is feature-complete). The honest acknowledgment of the toy-implementation's limitations is exactly the right framing for a teaching snippet.
- **The Gap to Production section is unusually thorough.** QHIN Participant Agreement and operational onboarding, IHE-and-FHIR message construction with `fhir.resources` and an IHE XCPD-and-XCA library, mTLS-and-KMS-backed signing, HSM-backed credential rotation ceremony, real DynamoDB schema with the four primary tables, TransactWriteItems for atomic cross-table writes, real Aurora PostgreSQL local MPI, real Step Functions orchestration, real cross-account S3 buckets with PrivateLink, real EventBridge bus with cross-recipe consumer subscriptions, real Cognito patient-portal IdP, idempotency keys on every write, cross-network-tolerance calibration with SageMaker and pilot-data infrastructure, real Splink-or-`recordlinkage` and `jellyfish`, cross-jurisdictional overlay automation with regulatory-monitoring triggers, patient-consent capture and withdrawal pathways, information-blocking-exception handling automation, three review queues with cohort-and-cycle-aware tooling, cohort-stratified accuracy monitoring with disparity alarms, capacity coordination through the QHIN's operational interface, KMS-encrypted everything, VPC + VPC endpoints + PrivateLink, CloudTrail data events, Lake Formation column-level access control, federation-participation governance program. The breadth honestly tells the reader how much operational discipline sits between the recipe and a production deployment.

---

## Closing Assessment

The teaching content is well-organized and faithful to the main recipe in structure, prose framing, and pedagogical ordering. The six pseudocode steps map onto Python functions with helpers in the right places. The S3 + EventBridge + CloudWatch API call shapes are correct (DynamoDB and SQS are referenced in setup but not actually called; the demo's persistence is in-memory). The Decimal-at-the-DynamoDB-boundary discipline is consistent. The QHIN-signature-validation, originating-attribution-chain validation, exchange-purpose validation with `PrivacyException` denial, opaque-record-token decoupling, consent-and-Part-2-at-candidate-evaluation-time filter, cross-network-tolerance dual-calibration per exchange purpose, per-jurisdiction sensitivity overlay with the post-Dobbs reproductive-health-care suppression demonstration, and the originating-attribution chain capture at every hop are all structurally correct. The `MockSecretsCustody`, `MockLocalMPI`, `MockConsentStore`, `MockJurisdictionalOverlays`, and `MockQHINFederationRouter` replacements are reasonable approximations that exercise the major paths.

The WARNING is localized and pedagogically meaningful. Finding 1 (the demographic-feature field naming asymmetry: outbound formulator and mock-other-participant handlers use the QTF-canonical `address_line_1`, but the local inbound handler reads only `address_line`) does not flip any decision band in the demo because Flow 3's hand-crafted test payloads use `address_line` to match what the local handler expects. But pointing this code at a real QHIN that emits the QTF-canonical format would silently drop the address feature on every inbound query, with no error and no audit signal that anything went wrong. The fix (accept either field name in the local handler, mirroring the mock-other-participant pattern) is mechanical and preserves the demo's expected output.

The six NOTEs are smaller items: the response envelope's `candidate_count_truncated` is hardcoded to `False` even when the matcher truncated (Finding 2); `_emit_metric` hardcodes `Unit="Count"` and the `OverlayApplicationRate` metric is a 0-1 rate rather than a count (Finding 3); `MockSecretsCustody.get_qhin_public_keys(include_previous=False)` filters by a key-version suffix not present in the demo (Finding 4); `MockSecretsCustody._access_log` accumulates but is never inspected (Finding 5); the mock other-participant handler does not apply the IAS feature suppression that the canonical handler implements (Finding 6); private-attribute access on `secrets_custody` from the QHIN router and the consolidator (Finding 7).

PASS verdict per the persona's rule: no ERRORs, one WARNING (under the FAIL threshold of more than three). The WARNING and the most-load-bearing NOTE (Finding 2) should be addressed before the recipe ships, because they teach a field-naming pattern that fails silently in production and a response-envelope field whose value disagrees with the matcher's actual behavior. None of these block the demo from running to completion.

Recipe 5.9 is the ninth recipe in Chapter 5 and inherits the chapter's operational discipline (graded confidence with deferred review, audit-everything substrate, drift-event fan-out, cohort-stratified telemetry, transactional-outbox eventing, conservative threshold posture, append-only persistence intent) from recipes 5.1-5.8. The TEFCA-specific behaviors that differentiate it (QHIN-signed request envelope as authentication root-of-trust, dual-calibrated cross-network tolerance per exchange purpose, opaque record token decoupling federation-visible identifiers from local record identifiers, per-record-type and per-jurisdiction sensitivity overlay applied at disclosure time, federated-response asynchronous consolidation with explicit completeness indicator, originating-attribution chain captured at every hop, information-blocking-compliance "denied-under-exception" pattern instead of silent drops, six-source invalidation pipeline including credential rotations, governance changes, consent withdrawals, and cross-recipe events from recipes 5.1 / 5.7 / 5.8) are all structurally present. Closing the WARNING brings the example up to the standard the recipe text claims and is appropriate given that this recipe is the federation-scale capstone for chapter 5's entity-resolution pipeline.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** `run_local_matcher_under_cross_network_tolerance` step 2B reads either `address_line_1` or `address_line` via `demographic_features.get("address_line_1") or demographic_features.get("address_line") or ""`, mirroring the mock-other-participant pattern. After the fix, hand-trace Flow 3's valid_inbound_payload (which uses `address_line`): the `or` chain picks up `address_line` and the composite stays at 0.80, candidates = 1. Hand-trace a hypothetical real QHIN payload with `address_line_1`: the `or` chain picks up `address_line_1` and the address contributes to scoring as the recipe text intends.
2. **(NOTE)** `run_local_matcher_under_cross_network_tolerance` returns the truncation flag along with the candidate set, and `handle_inbound_patient_discovery_query` propagates it to the response envelope's `candidate_count_truncated` field. Or, the field is dropped from the envelope entirely and the recipe text's "Sample outbound federation response" example is updated to match.
3. **(NOTE)** `_emit_metric` accepts an optional `unit` parameter with a `Count` default. The `OverlayApplicationRate` emit site passes `unit="None"` to reflect the rate semantics. Future score-emit additions can pass appropriate unit strings.
4. **(NOTE)** `MockSecretsCustody.get_qhin_public_keys(include_previous=False)` either correctly returns only the active version (using a separate `_qhin_active_version` field or treating the most-recently-added version as active) or the `include_previous=False` branch is dropped entirely with the parameter renamed for clarity.
5. **(NOTE)** `MockSecretsCustody._access_log` is either surfaced at the end of `run_demo()` to demonstrate the audit-trail consumption pattern, or dropped entirely with an inline comment noting that production uses CloudTrail data events on Secrets Manager and KMS.
6. **(NOTE)** `_make_inbound_handler_for_other_participant` calls `_extract_disclosable_features(r, exchange_purpose)` for the candidate envelope's `disclosable_demographic_features`. After the fix, re-run Flow 2 and confirm the printed `IAS feature_keys` shows `['dob', 'family_name', 'given_name', 'sex_or_gender']`. Update the recipe text's expected output.
7. **(NOTE)** `MockSecretsCustody` exposes public accessors for the QHIN signing key (used by the router) and for the participant's per-version signing keys (used by the consolidator). The QHIN router and the response consolidator are updated to use the public methods rather than reaching into private state.

After the WARNING fix, re-run the demo end-to-end and confirm:

- Flow 1: unchanged (`completeness_pct: 100%`, `groupings: 1`, "Sarah Mitchell (DOB 1984-08-17): 2 candidates (medium confidence)", documents_retrieved: 6).
- Flow 2: unchanged (`completeness_pct: 100%`, `groupings: 1`, `IAS confidence: high`); after Finding 6 fix, `IAS feature_keys` would change from the seven-key set to the four-key set.
- Flow 3: unchanged (valid query: candidates=1; bad signature: rejection_reason=InvalidQHINSignature; unauth originator: rejection_reason=UnauthorizedOriginatorQHIN; bad purpose: denied_under_exception=PrivacyException).
- Flow 4: unchanged (`candidates returned: 0` because the post_dobbs_v3 overlay suppresses Maria's record).

The other findings are low-risk cleanups that improve pedagogical clarity, align the code with the recipe text's stated semantics, and reduce the chance that a reader copies a misleading pattern into production. None of them block the demo from running to completion under the demo-mode-tables-not-provisioned path.
