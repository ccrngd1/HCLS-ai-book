# Code Review: Recipe 5.3 - Address Standardization and Household Linkage

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-22
**Files reviewed:**
- `chapter05.03-address-standardization-household-linkage.md` (main recipe pseudocode)
- `chapter05.03-python-example.md` (Python companion)

**Validation performed:**
- Walked the five pseudocode steps against the Python functions one-to-one
- Verified boto3 API call shapes for DynamoDB resource (`get_item`, `put_item`, `query`), S3 (`put_object`), EventBridge (`put_events`), CloudWatch (`put_metric_data`)
- Verified `boto3.dynamodb.conditions.Key` usage in the GSI query for `_query_records_at_canonical`
- Traced numeric values flowing into DynamoDB through `_to_decimal` and `_serialize_for_dynamodb`
- Walked the canonicalization path (`_canonical_form` -> `_sha256` -> `_build_canonical_hash`) against the `MockAddressValidator._KNOWN_ADDRESSES` dictionary keys to confirm cache hits and dict lookups will resolve
- Traced the in-memory address registry through Phase 1 (initial standardization), Phase 2 (NCOA mover simulation), and Phase 3 (USPS reference-data refresh) of the demo
- Verified Decimal-at-the-DynamoDB-boundary discipline, S3 key formation (no leading slashes), and PHI handling in audit-archive writes
- Verified that the privacy-suppression branches behave consistently with the documented `PRIVACY_POLICY` values

---

## Summary

The Python companion is structurally faithful to the main recipe's five pseudocode steps and the architectural picture (ingest from any source system, standardize through a CASS-certified vendor with six-way classification, persist with provenance and emit change events, infer graded household membership with first-class privacy suppression and building-type classification, refresh on a USPS / NCOA cadence). The Decimal-at-the-DynamoDB-boundary discipline is consistent with `_serialize_for_dynamodb`, S3 keys do not carry leading slashes, the standardization-status classifier maps DPV codes (Y / S / D / N) to the recipe's six well-defined statuses correctly, the building-type classifier uses the standardization metadata the way the recipe text describes, the graded-confidence household contract (HIGH / MEDIUM / CO_LOCATED / SUPPRESSED / SINGLE_PATIENT) is honored at every persistence write, and the corroborating-evidence assessment (last-name overlap, insurance-subscriber overlap, age-pattern consistency, secondary-unit completeness) maps cleanly to the recipe's Step 4D. The MockAddressValidator response shape is a reasonable approximation of the major vendors' (Smarty, Melissa, Loqate, Experian) actual responses, and the privacy-suppression-as-first-class-case discipline is implemented at the start of `infer_household_for_address` rather than as a downstream filter.

That said, one WARNING needs attention before this goes to readers, plus four NOTEs. The WARNING is that the demo's NCOA simulation (`simulate_ncoa_processing`) and monthly USPS refresh (`monthly_usps_refresh`) both call `persist_standardized_record` directly rather than going through `run_standardize_pipeline_for_patient`, and `persist_standardized_record` does not update the demo-only `_IN_MEMORY_ADDRESS_REGISTRY`. The result is that after Phase 2's NCOA mover simulation, the in-memory registry still has the moved patient at the old canonical address, so the household re-inference for both the old and the new canonical hashes produces silently-wrong results in demo mode. The recipe's prose makes an explicit claim ("the household re-inference runs for both the old canonical (where the patient left, so the Patel household at Apt 3B re-evaluates without them) and the new canonical (where the patient arrives, so the SINGLE_PATIENT result at Apt 5A re-evaluates with two patients now)") that the code does not deliver in the demo. The bug is silent because the demo prints only the count of affected canonicals, not the post-refresh household state.

The four NOTEs cover smaller items: an unused `from dateutil import parser as dateparser` import; the `_build_canonical_hash` function passes both `delivery_line_1` (which already contains the secondary number in standardized output like "1421 ELM ST APT 3B") and `secondary_number` separately to `_canonical_form`, producing a redundant hash input where the unit number appears twice; the pseudocode's Step 3E (trigger household re-inference inside `persist_standardized_record`) is hoisted to the pipeline wrapper `run_standardize_pipeline_for_patient` without an inline comment explaining why a learner comparing pseudocode to Python line-by-line will be momentarily confused; and the deploy-time `assert` covers only `AUDIT_BUCKET`, leaving the other resource-name constants without the same guardrail (chapter pattern from 5.2's Finding 8).

---

## Verdict: PASS

No ERRORs. One WARNING (under the FAIL threshold of more than three). Four NOTEs.

The WARNING and the load-bearing NOTEs (Findings 2 and 3) should be addressed before the recipe ships, because the demo's NCOA path silently produces incorrect post-mover household-inference results in demo mode and the canonical-hash-input redundancy teaches a slightly odd hashing pattern. None of these block the demo from running to completion. Recipe 5.3 is the third simple-tier recipe in Chapter 5 and inherits its operational discipline (graded household contract, audit-archive every decision, provenance on every record, drift-event fan-out) from recipes 5.1 and 5.2, so getting the address-and-household-specific behavior (standardization status classification, building-type classification, household-confidence assignment, NCOA-driven mover propagation) faithful to the pseudocode is what differentiates it from the patient and provider matchers.

---

## Findings

### Finding 1: `simulate_ncoa_processing` and `monthly_usps_refresh` Bypass the In-Memory Registry Update; Post-Move Household Re-Inference Produces Silently-Wrong Results in Demo Mode

- **Severity:** WARNING
- **File:** `chapter05.03-python-example.md`
- **Locations:** `simulate_ncoa_processing`, `monthly_usps_refresh`, and `persist_standardized_record`
- **Description:**

  The demo uses `_IN_MEMORY_ADDRESS_REGISTRY` as a stand-in for the `patient-address` DynamoDB table. The `_query_records_at_canonical` helper falls back to this registry when the real DynamoDB GSI query fails (which is the expected path in demo mode without provisioned tables):

  ```python
  def _query_records_at_canonical(canonical_hash: str) -> list:
      try:
          resp = dynamodb.Table(ADDRESS_TABLE).query(
              IndexName=CANONICAL_HASH_INDEX,
              KeyConditionExpression=Key("canonical_hash").eq(canonical_hash),
          )
          return resp.get("Items", [])
      except Exception as exc:
          logger.info("GSI query skipped; using in-memory registry", ...)
          return [r for r in _IN_MEMORY_ADDRESS_REGISTRY.values()
                  if r.get("canonical_hash") == canonical_hash]
  ```

  The registry is populated by `run_standardize_pipeline_for_patient` after each `persist_standardized_record` call:

  ```python
  def run_standardize_pipeline_for_patient(source_event: dict) -> dict:
      raw = ingest_address_record(source_event)
      standardized = standardize_address(raw)
      persist_summary = persist_standardized_record(...)

      # Maintain the in-memory registry so the household-inference
      # GSI-fallback path works in the demo.
      if standardized.get("canonical_hash"):
          key = (source_event["patient_id"], ...)
          _IN_MEMORY_ADDRESS_REGISTRY[key] = {...}
  ```

  But `simulate_ncoa_processing` does not go through `run_standardize_pipeline_for_patient`. It calls `persist_standardized_record` directly:

  ```python
  def simulate_ncoa_processing(movers: list) -> dict:
      for mover in movers:
          ...
          new_standardized = standardize_address(new_raw)
          old = _IN_MEMORY_ADDRESS_REGISTRY.get((patient_id, "physical"), {})
          old_canonical = old.get("standardized", {}).get("canonical_hash")
          result = persist_standardized_record(patient_id, new_raw, new_standardized)
          # NOTE: registry is never updated here.
          ...
          if old_canonical:
              affected_canonicals.add(old_canonical)
          if new_standardized.get("canonical_hash"):
              affected_canonicals.add(new_standardized["canonical_hash"])

      for canon in affected_canonicals:
          infer_household_for_address(canon)
  ```

  Trace through Phase 2 of the demo with `patient-internal-00874` moving from Apt 3B (canonical `a3f5b8c2...`) to Apt 5A (canonical `b4c6d2e1...`):

  1. `new_standardized` is the Apt 5A record. Good.
  2. `old_canonical = a3f5b8c2...` (read from the registry, which still has 00874 at Apt 3B). Good.
  3. `persist_standardized_record` writes to DynamoDB (fails silently in demo mode without a real table) and emits an event. Crucially, **the in-memory registry is not touched.** 00874 is still at Apt 3B in the registry.
  4. `affected_canonicals = {a3f5b8c2..., b4c6d2e1...}`.
  5. `infer_household_for_address(a3f5b8c2...)` queries the registry, finds 00874 (still at the old canonical along with the rest of the Patels) plus 00875, 00876, 00877, and 01100, runs the household-inference path, and produces the SAME result as Phase 1 (SUPPRESSED because 01100 is still in the group). The "Patel household at Apt 3B re-evaluates without them" claim from the prose is false: 00874 is still in the group.
  6. `infer_household_for_address(b4c6d2e1...)` queries the registry, finds only 00990 (because 00874 is still showing as Apt 3B in the registry), and produces SINGLE_PATIENT. The "SINGLE_PATIENT result at Apt 5A re-evaluates with two patients now" claim from the prose is false: only 00990 is found at the new canonical.

  The same pattern affects `monthly_usps_refresh`. It also calls `persist_standardized_record` directly without updating the registry. In the demo, the mock returns the same response on a second call, so `drift_count` is 0 and the bug is dormant; if a learner extended the demo to mutate the mock's response between calls, the same silent miscompute would surface.

  Three consequences:

  1. **The prose's claim is not delivered by the code in demo mode.** A learner who reads the explanatory paragraph after the demo's expected-output block, then runs the code under a debugger to verify, will find the household state unchanged after the NCOA simulation. The prose says one thing; the code does another.
  2. **The demo prints only `processed=1 affected_canonicals=2` without showing the household-inference outcomes**, so the bug is silent. A learner who trusts the prose will trust that the household re-inference behaved as described.
  3. **The asymmetry between the pipeline wrapper and the NCOA / refresh paths is itself a confusing pattern to teach.** Why does `run_standardize_pipeline_for_patient` know to update the registry but the NCOA path does not? The answer ("it is a demo workaround for missing DynamoDB") is not visible in the code or the comments.

- **Suggested fix:** Move the in-memory registry update inside `persist_standardized_record` so every code path that persists a standardized record also updates the demo's registry. The cleanest version:

  ```python
  def persist_standardized_record(patient_id: str, raw: dict,
                                    standardized: dict) -> dict:
      ...
      try:
          dynamodb.Table(ADDRESS_TABLE).put_item(Item=item)
      except Exception as exc:
          logger.error("address put failed", ...)

      # Demo-mode mirror so the in-memory registry stays consistent
      # with the persisted record. In production this is the role
      # of the canonical-hash GSI on the patient-address table; the
      # registry is purely a stand-in for the GSI in demo mode.
      if standardized.get("canonical_hash"):
          _IN_MEMORY_ADDRESS_REGISTRY[(patient_id, address_role)] = {
              "patient_id":     patient_id,
              "address_role":   address_role,
              "canonical_hash": standardized["canonical_hash"],
              "standardized":   standardized,
          }
      ...
  ```

  Then drop the parallel registry update from `run_standardize_pipeline_for_patient` (the wrapper no longer needs it because `persist_standardized_record` handles it).

  Verify the fix by re-running the demo and inspecting the household state after Phase 2: the Patel household at Apt 3B should re-evaluate to the four-record group without 00874, and the Apt 5A canonical should re-evaluate from SINGLE_PATIENT to a two-record group containing 00874 and 00990. Optionally extend the demo's print output to surface the post-NCOA household-inference results so the success of the fix is visible without reaching for a debugger.

---

### Finding 2: `_build_canonical_hash` Passes Both `delivery_line_1` (Which Already Contains the Secondary Number) and `secondary_number` Separately, Producing a Redundant Hash Input

- **Severity:** NOTE
- **File:** `chapter05.03-python-example.md`
- **Location:** `_build_canonical_hash` and the call site in `standardize_address`
- **Description:**

  The function:

  ```python
  def _build_canonical_hash(delivery_line_1: str, secondary_number: Optional[str],
                              last_line: str) -> str:
      canon = _canonical_form(delivery_line_1, secondary_number, last_line)
      return _sha256(canon)
  ```

  And the call site:

  ```python
  standardized["canonical_hash"] = _build_canonical_hash(
      vr.get("delivery_line_1") or "",
      (vr.get("components") or {}).get("secondary_number"),
      vr.get("last_line") or "",
  )
  ```

  For the Patel address, `delivery_line_1 = "1421 ELM ST APT 3B"` (which already includes the unit number), `secondary_number = "3B"`, and `last_line = "ANYTOWN ST 12345-1234"`. The `_canonical_form(*parts)` function joins these with spaces, lowercases, strips diacritics, and collapses whitespace:

  ```
  "1421 elm st apt 3b 3b anytown st 12345-1234"
  ```

  The unit number "3b" appears twice in the canonical form. The hash is deterministic and idempotent (same input always produces the same hash, so household grouping still works), but the redundancy is pedagogically odd: a reader who inspects the canonical form (perhaps while debugging a hash collision) will see "3b 3b" and wonder if it is intentional.

  For the PO Box record (`delivery_line_1 = "PO BOX 4421"`, `secondary_number = None`, `last_line = "ANYTOWN ST 12345-4421"`), the canonical form is `"po box 4421 anytown st 12345-4421"` (no duplicate because secondary_number is None and `str(None or "").strip()` produces an empty string that the join then collapses). So the redundancy only appears when there is a secondary unit and the vendor's `delivery_line_1` already includes it (which is the standard behavior for CASS-certified vendors).

  Two consequences:

  1. **The canonical hash is not the simplest function of "address identity."** A learner who looks at the function and asks "what is the canonical form a hash of?" gets the answer "the delivery line plus the unit number again plus the last line" rather than "the standardized form of the full address." The simpler answer is also the right answer; the implementation does not deliver it.
  2. **The redundancy obscures the design intent.** The recipe text frames the canonical hash as the substrate for household grouping: same address with same unit produces the same hash. The right hash inputs are exactly the parts that capture "same physical address with same unit": a single delivery line that already includes the unit (which is what CASS-certified vendors return), plus the last line. The separate `secondary_number` parameter is unnecessary for the hash; it is useful for the per-component metadata stored elsewhere on the record.

- **Suggested fix:** Drop the `secondary_number` parameter from `_build_canonical_hash` and update the call site:

  ```python
  def _build_canonical_hash(delivery_line_1: str, last_line: str) -> str:
      """
      Stable hash for the canonical address. Same physical address
      with the same secondary unit produces the same hash because
      delivery_line_1 from a CASS-certified vendor already includes
      the unit number when present.
      """
      canon = _canonical_form(delivery_line_1, last_line)
      return _sha256(canon)
  ```

  And the call site:

  ```python
  standardized["canonical_hash"] = _build_canonical_hash(
      vr.get("delivery_line_1") or "",
      vr.get("last_line") or "",
  )
  ```

  This relies on the CASS-vendor invariant that `delivery_line_1` includes the unit number. The invariant is documented in the recipe text: *"`delivery_line_1`: the primary delivery line (street number, predirectional, street name, suffix, postdirectional, secondary unit if combined with the primary line)."* The simplification matches the documented data model.

  Note that this changes the canonical hash for any address that previously had a secondary unit. If the change lands after the demo has been run, any persisted records would need a one-time re-hash. For pedagogical code that is not yet shipped, the change is safe.

---

### Finding 3: Pseudocode Step 3E (Trigger Household Re-Inference) Is Hoisted From `persist_standardized_record` to the Pipeline Wrapper Without an Inline Comment

- **Severity:** NOTE
- **File:** `chapter05.03-python-example.md`
- **Location:** `persist_standardized_record` and `run_standardize_pipeline_for_patient`
- **Description:**

  The pseudocode's Step 3E in the main recipe lives inside `persist_standardized_record`:

  ```
  // Step 3E: trigger household re-inference for affected
  // canonical addresses. The previous-address group loses this
  // patient; the new-address group gains them.
  IF previous IS NOT NULL AND
     previous.standardized.canonical_hash != standardized.canonical_hash:
      invoke_household_inference(previous.standardized.canonical_hash)
  invoke_household_inference(standardized.canonical_hash)
  ```

  The Python's `persist_standardized_record` ends after the event emission (Step 3D); the household re-inference call is moved to the pipeline wrapper:

  ```python
  def run_standardize_pipeline_for_patient(source_event: dict) -> dict:
      ...
      household_summary = None
      if standardized.get("canonical_hash"):
          # Re-infer for the new canonical hash.
          household_summary = infer_household_for_address(
              standardized["canonical_hash"])
          # Re-infer for the old canonical hash if it changed.
          if (persist_summary["canonical_changed"]
                  and persist_summary["previous_canonical_hash"]):
              infer_household_for_address(
                  persist_summary["previous_canonical_hash"])
  ```

  The hoist is defensible. In production, persistence and household-inference are typically separate Lambdas wired by EventBridge or Step Functions, so persistence emitting an event and a separate consumer running household-inference is the right layering. The wrapper pattern makes the demo's call structure visible. But the file does not explain the deviation. A reader walking the pseudocode line-by-line against the Python (which is the explicit pedagogical approach the recipe encourages by calling out each step) reaches Step 3E in the pseudocode, looks for the corresponding code in `persist_standardized_record`, finds nothing, and has to discover by reading further that the work has been moved elsewhere.

  The ambiguity is reinforced by the existing TODO comment in `persist_standardized_record` that promises a future transactional outbox pattern but says nothing about the household-inference hoist:

  ```python
  # TODO (TechWriter): wrap the DynamoDB write, the S3 audit
  # write, and the EventBridge emit in a transactional outbox
  # pattern (TransactWriteItems plus a Streams-driven event
  # emitter) so partial failures cannot leave the address table
  # out of sync with downstream consumers. ...
  ```

- **Suggested fix:** Two reasonable options:

  1. **Add a short comment in `persist_standardized_record` explaining where Step 3E went**, so a reader walking the pseudocode line-by-line finds the explanation in the right place:

     ```python
     # In the pseudocode, Step 3E triggers household re-inference
     # here. In the Python the trigger is hoisted to the pipeline
     # wrapper run_standardize_pipeline_for_patient because in
     # production persistence and household-inference are separate
     # Lambdas wired by EventBridge / Step Functions; the wrapper
     # represents the orchestration layer.
     ```

  2. **Inline the household-inference call inside `persist_standardized_record`** so the Python tracks the pseudocode literally. This is closer to the pseudocode but couples persistence and inference more tightly than the production architecture suggests.

  Option 1 is the smaller fix and aligns with the recipe's already-established pattern of calling out architectural deviations in inline comments rather than in prose around the code.

---

### Finding 4: Unused Import `from dateutil import parser as dateparser`

- **Severity:** NOTE
- **File:** `chapter05.03-python-example.md`
- **Location:** the imports block at the top of the Configuration and Constants section
- **Description:**

  The imports block includes:

  ```python
  from dateutil import parser as dateparser
  ```

  No code in the file calls `dateparser.parse()` or any other method on the imported alias. The Setup section's `pip install` line includes `python-dateutil`, presumably to support the import:

  ```bash
  pip install boto3 python-dateutil
  ```

  Recipes 5.1 and 5.2 use `python-dateutil` in their date-parsing helpers (`_parse_iso_date`); recipe 5.3 does not need it because all dates are already ISO-formatted strings produced by `_now_iso()` and `datetime.now(timezone.utc).date().isoformat()`, with no ambiguous-format inputs to parse.

  Two consequences:

  1. **The `pip install python-dateutil` instruction is unnecessary**, which is a small but real friction for a learner who is following the Setup section literally.
  2. **A linter would flag the unused import**, which is the kind of thing a careful learner notices and wonders about.

- **Suggested fix:** Remove the unused import and drop `python-dateutil` from the `pip install` line:

  ```python
  # remove this line entirely:
  # from dateutil import parser as dateparser
  ```

  ```bash
  pip install boto3
  ```

  If a future iteration of the recipe adds a date-parsing helper that needs `python-dateutil`, restore the import at that time.

---

### Finding 5: Deploy-Time Guardrail Covers Only `AUDIT_BUCKET`; Other Resource Names Could Silently Be Empty Strings

- **Severity:** NOTE
- **File:** `chapter05.03-python-example.md`
- **Location:** the resource-name constant block
- **Description:**

  The constants block has a single deploy-time assertion:

  ```python
  ADDRESS_TABLE          = "patient-address"
  HOUSEHOLD_TABLE        = "household-membership"
  CANONICAL_HASH_INDEX   = "canonical-hash-index"
  AUDIT_BUCKET           = "my-address-standardization-audit"
  EVENTS_BUS_NAME        = "address-and-household-drift"
  CLOUDWATCH_NAMESPACE   = "Address/Standardization"

  # Deploy-time guardrail.
  # TODO (TechWriter): Extend the guardrail to cover every resource-name
  # constant so a missing value produces an actionable assertion message
  # rather than a downstream boto3 ValidationException.
  assert AUDIT_BUCKET != "", "AUDIT_BUCKET must be set before deploying."
  ```

  The TODO comment already names the gap. The same pattern showed up in recipe 5.2's Finding 8 and the resolution recommended there applies here: extend the guardrail to cover every resource name so misconfiguration produces a clean assertion message rather than a downstream `ValidationException` from boto3.

- **Suggested fix:** Replace the single assertion with a loop covering every resource-name constant:

  ```python
  for name, value in [
      ("ADDRESS_TABLE", ADDRESS_TABLE),
      ("HOUSEHOLD_TABLE", HOUSEHOLD_TABLE),
      ("CANONICAL_HASH_INDEX", CANONICAL_HASH_INDEX),
      ("AUDIT_BUCKET", AUDIT_BUCKET),
      ("EVENTS_BUS_NAME", EVENTS_BUS_NAME),
      ("CLOUDWATCH_NAMESPACE", CLOUDWATCH_NAMESPACE),
  ]:
      assert value, f"{name} must be set before deploying."
  ```

  Drop the TODO once the loop replaces the single assertion.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Function | Consistent? |
|----------------|-----------------|-------------|
| `ingest_address_record(source_event)` | `ingest_address_record` plus `_archive_raw_to_s3` | Yes (raw-input shape with patient_id, address_role, line1, line2, city, state, zip, country, source, source_record_id, ingested_at; S3 archive write to `address-raw/{source}/{date}/{patient_id}_{role}_{uuid}.json`). |
| `standardize_address(raw)` (sub-steps 2A-2F) | `standardize_address` plus `_classify_vendor_response`, `_build_canonical_hash`, `check_standardization_cache`, `write_to_standardization_cache` | Yes (2A non-US short-circuit, 2B cache check, 2C vendor call, 2D classification mapping DPV codes to the six statuses, 2E structured-form-and-metadata capture for usable statuses, 2F cache and return). **The canonical-hash construction passes the secondary number redundantly per Finding 2.** |
| `persist_standardized_record(patient_id, raw, standardized)` (sub-steps 3A-3E) | `persist_standardized_record` plus `_serialize_for_dynamodb`, `_emit_metric`, `_write_audit` | Mostly yes for 3A (read previous), 3B (write current with `previous_canonical_hash`, `last_updated_at`, `next_revalidation_due_at`), 3C (S3 audit archive), 3D (EventBridge change event). **Step 3E (trigger household re-inference) is hoisted from `persist_standardized_record` to the pipeline wrapper `run_standardize_pipeline_for_patient` without an inline comment per Finding 3.** |
| `infer_household_for_address(canonical_hash)` (sub-steps 4A-4F) | `infer_household_for_address` plus `_query_records_at_canonical`, `_patient_privacy_flags`, `classify_building_type`, `_last_name_overlap`, `_subscriber_overlap`, `_age_pattern_consistent`, `_assign_confidence`, `_enumerate_evidence`, `_derive_household_id` | Yes (4A canonical-hash query with single-patient short-circuit, 4B privacy suppression with both policy options, 4C building-type classification with the building-type-to-eligibility map, 4D corroborating-evidence assessment with confidence assignment, 4E per-record household-membership writes, 4F household-changed event emission). The single-patient case correctly persists a `SINGLE_PATIENT` confidence record so downstream consumers see a consistent shape regardless of group size. |
| `monthly_usps_refresh()` and `quarterly_ncoa_processing()` | `monthly_usps_refresh` and `simulate_ncoa_processing` plus `_classify_drift` | Mostly yes for the structural flow (re-standardize, classify drift, persist, emit drift events, recompute household for affected canonicals; NCOA: ingest new address, standardize, persist, emit mover event). **Both paths bypass the in-memory registry update so post-mover household re-inference produces silently-wrong results in demo mode per Finding 1.** The drift-type classifier handles `became_invalid`, `validated_now`, `zip4_changed`, `building_type_changed`, and `other_change`; the NCOA path emits `ncoa_mover_detected` events with the previous and new canonicals plus the move date and match type. |

Intentional deviations clearly framed:

- The CASS-certified vendor SDK becomes `MockAddressValidator` with a small `_KNOWN_ADDRESSES` dictionary covering the demo's six exemplar inputs (clean validated, family member at different unit, typo correction, missing-secondary, PO Box, shelter). Documented in the Heads-up section and in Gap to Production.
- The DynamoDB GSI query falls back to `_IN_MEMORY_ADDRESS_REGISTRY` when the real table is not provisioned. Documented in `_query_records_at_canonical` and in Gap to Production.
- The standardization cache is in-process (Python dict) rather than DynamoDB / ElastiCache. Documented in the comment block above `_STANDARDIZATION_CACHE`.
- Real NCOA integration is replaced by `simulate_ncoa_processing` with hard-coded movers. Documented at the top of the file and in Gap to Production.
- KMS / VPC / Secrets Manager / CloudTrail wiring is deferred to Gap to Production.
- The privacy-suppression policy is shown as a runtime constant rather than a privacy-officer-approved policy decision. Documented in the constants block.

The substantive deviation (Finding 1) is the consistency gap that carries pedagogical consequence. The acknowledged simplifications (mock validator, in-memory registry, in-process cache, simulated NCOA) are clearly framed.

---

## AWS SDK Accuracy

| API Call | Method | Notes |
|----------|--------|-------|
| DynamoDB GetItem | `dynamodb.Table(NAME).get_item(Key={...})` | Correct. `persist_standardized_record` reads the previous record by `(patient_id, address_role)`. |
| DynamoDB PutItem | `dynamodb.Table(NAME).put_item(Item=_serialize_for_dynamodb(...))` | Correct. All numeric values flow through `_serialize_for_dynamodb`. The `patient-address` and `household-membership` items both route through serialization. |
| DynamoDB Query | `dynamodb.Table(ADDRESS_TABLE).query(IndexName=CANONICAL_HASH_INDEX, KeyConditionExpression=Key("canonical_hash").eq(canonical_hash))` | Correct shape. The GSI is named `canonical-hash-index` keyed on `canonical_hash`. The query does not paginate, which is fine for the typical household-size population (1-10 records per canonical hash) but a NOTE-worthy item for very large multi-unit-no-unit collapses. |
| S3 PutObject | `s3_client.put_object(Bucket=AUDIT_BUCKET, Key=key, Body=body, ServerSideEncryption="aws:kms")` | Correct. Body is bytes-encoded JSON. Keys use `address-raw/{source}/{date}/{patient_id}_{role}_{uuid}.json` and `audit/{partition}/{today}/{uuid.uuid4()}.json` with no leading slashes. SSE-KMS without explicit `SSEKMSKeyId` defaults to the AWS-managed KMS key, an acceptable demo simplification per the recipe's note that production uses customer-managed CMKs. |
| EventBridge PutEvents | `eventbridge_client.put_events(Entries=[{Source, DetailType, EventBusName, Detail}])` | Correct. `Detail` is JSON-serialized with `default=str` to handle Decimal serialization. Four event types are emitted: `address_standardized`, `address_drift_detected`, `ncoa_mover_detected`, `household_inferred`. |
| CloudWatch PutMetricData | `cloudwatch_client.put_metric_data(Namespace=CLOUDWATCH_NAMESPACE, MetricData=[{MetricName, Value, Unit, Dimensions}])` | Correct shape. The `Dimensions` list is built from `(dimensions or {}).items()`. Three metric names are emitted (`StandardizationOutcome`, `HouseholdInferred`, `USPSRefreshProcessed`, `USPSRefreshDriftCount`). |

The SDK-level concerns are: Finding 1 (the in-memory registry bypass affects what the demo claims for post-NCOA state, but the SDK calls themselves are well-formed). All API surfaces are current and correct.

---

## DynamoDB and Data Type Check

- `_to_decimal` correctly uses `Decimal(str(value))` and short-circuits on already-Decimal inputs.
- `_serialize_for_dynamodb` recursively walks dicts and lists, converts floats to Decimal, and preserves tuples as lists. Booleans are unaffected (`isinstance(True, float)` is False in Python; bool is a subclass of int, not float). The pattern is safe.
- The `correction_confidence` field is wrapped in `_to_decimal` at the point of capture inside `standardize_address`, so it is already Decimal by the time `_serialize_for_dynamodb` walks the record.
- All `put_item` writes route values through `_serialize_for_dynamodb` at the persistence boundary.
- The CloudWatch `Value: float` parameter is correct (CloudWatch accepts native floats; only DynamoDB requires Decimal).
- The `next_revalidation_due_at` field uses `datetime.now(timezone.utc).date().isoformat()` so it stores as a string. Correct for DynamoDB.

The Decimal discipline is correct. No type-handling bugs.

---

## S3 and Credentials Check

- The example uses S3 only for raw-input archive (`address-raw/{source}/{date}/{patient_id}_{role}_{uuid}.json`) and curated audit archive (`audit/{partition}/{today}/{uuid.uuid4()}.json`). No leading slash on any key.
- The deploy-time guardrail (`assert AUDIT_BUCKET != "", "AUDIT_BUCKET must be set before deploying."`) catches one of the placeholder cases. **Other resource names lack the same guardrail per Finding 5.**
- No hardcoded credentials. Module-level boto3 clients use the documented environment credential chain.
- The IAM permissions list in Setup matches the API surface used by the code (DynamoDB on the two named tables plus the `canonical-hash-index` GSI, S3 PutObject on the audit-archive bucket, EventBridge PutEvents on the events bus, CloudWatch PutMetricData, Secrets Manager GetSecretValue for the production vendor-API-key path).
- The Setup section explicitly names that "tutorial-level permissions above are fine for learning and will fail any serious IAM review" with the right framing about per-Lambda role scoping.

Pass.

---

## Comment Quality Assessment

Comments consistently explain the "why":

- The Heads-up at the top names every major production gap before the code starts (no real CASS validator, no NCOAlink, no Glue / Spark batch pipeline, no real geocoder, no SDOH joins, no privacy-officer-approved suppression policy, no review-queue UI, no IAM / KMS / VPC / CloudTrail wiring).
- The PHI framing for standardized addresses is honest and specific: *"Standardized addresses are PHI in their structured form. The combination of standardized address + DOB + sex is highly re-identifying, and HIPAA's de-identification standards treat geographic subdivisions smaller than state (with limited exceptions for the first three digits of ZIP code) as identifiers."*
- The vendor-call PHI transmission framing is appropriate: *"CASS-certified vendor calls are billable PHI transmissions. Each call to the vendor API sends the patient identifier (you must) and the address (the whole point) outside your VPC. The vendor must have a BAA in place; the call must go through a controlled egress path..."*
- The Decimal-at-the-DynamoDB-boundary discipline is documented: *"DynamoDB rejects Python `float`. Every probability, confidence score, and numeric metadata field passes through `Decimal` on its way in and on its way out. Same gotcha as recipes 5.1 and 5.2; the same `_to_decimal` helper handles it."*
- The cache rationale is named: *"Standardization results should be cached. Many addresses repeat across patient records (family members at the same address, address copied from one record to another). A small cache keyed on the input hash dramatically reduces vendor cost."*
- The privacy-policy decision framing is explicit: *"Privacy suppression is a deliberate policy choice. The demo implements both options (suppress entire group when any record is suppressed, vs exclude suppressed records from the group). The right one depends on the institution's clinical and legal context. Pick one and document it; do not leave it as a coin flip per deployment."*
- The vendor-API key handling: *"the API key must live in Secrets Manager, not in code or environment variables. The demo skips this wiring for readability but the production pattern is non-negotiable."*
- The international-address short-circuit is documented inline: *"short-circuit non-US addresses. The CASS vendor covers US addresses only; international addresses go through a different validator path or no validator at all if no international vendor is licensed."*
- The classification-status mapping is documented with the recipe-text-aligned semantics for each status (VALIDATED / CORRECTED / MISSING_SECONDARY / AMBIGUOUS / NOT_VALIDATED / INVALID).
- The privacy-suppression branch handling is documented: *"Privacy suppression. Apply policy."* with a clear branch per `PRIVACY_POLICY` value.
- The building-type-to-eligibility map is annotated: `"multi_unit_no_unit": False  # ambiguous; declare CO_LOCATED only`, `"unknown": False  # be conservative on unknowns`.
- The graded-confidence scoring rules in `_assign_confidence` are documented step by step (which building types short-circuit to CO_LOCATED, which add to the score, which thresholds map to HIGH / MEDIUM / CO_LOCATED).
- The drift-classification function names the categories the recipe text identifies (`became_invalid`, `validated_now`, `zip4_changed`, `building_type_changed`, `other_change`).
- The synthetic-data labeling at the top of the file: *"All patients, addresses, and demographics in this demo are fictional. The mock validator returns hand-crafted responses that exercise the full classification range; do not point this demo at real registration data."*

The Gap to Production section is unusually thorough (15+ items spanning real CASS-vendor SDK integration, real DynamoDB schema with the canonical-hash GSI, TransactWriteItems for atomic writes, vendor-cost monitoring, Glue-on-Spark batch pipeline, real NCOA integration, Step Functions orchestration, real geocoding and SDOH joins, privacy-officer-approved policy, cohort-stratified accuracy monitoring, registration-time correction-confirmation UX, patient-portal address-confirmation flow, KMS-encrypted everything, VPC + endpoints, CloudTrail data events, international handling, idempotency keys, outreach-list scrubbing, backfill strategy).

The comments that would benefit from updates per the findings:

- `persist_standardized_record` lacks an inline comment naming where Step 3E went per Finding 3.
- The constants block's deploy-time assertion has a TODO comment naming the gap but does not implement the loop per Finding 5.
- The unused `dateparser` import is silent per Finding 4.

Calibration is otherwise appropriate for a mixed audience.

---

## Healthcare-Specific Requirements

- **PHI discipline.** The opening "things worth knowing upfront" block correctly names that standardized addresses are PHI in their structured form, with the HIPAA Safe Harbor reference for geographic subdivisions and the encryption-and-access-control framing.
- **Synthetic data labeling.** Sample patient IDs (`patient-internal-00874`, etc.), addresses (`1421 Elm St`, `100 Main St`, `200 Hope Way`, `PO Box 4421`), and demographics are obviously synthetic. The Heads-up section warns explicitly. The MockAddressValidator's `_KNOWN_ADDRESSES` dictionary uses the same set of synthetic inputs.
- **Decimal at the DynamoDB boundary.** Consistent. Defensive float-to-Decimal coercion in `_serialize_for_dynamodb` and at the `correction_confidence` capture point.
- **Privacy-suppression-as-first-class-case.** `infer_household_for_address` checks privacy flags before any building-type classification or evidence assessment; the suppression branches run before the rest of the pipeline. Honors the recipe text's *"The privacy contract is part of the architecture, not a downstream filter; suppressing late is much harder to get right than suppressing early."*
- **Audit-archive every operation.** `_write_audit` writes a partitioned record per persist; `_archive_raw_to_s3` writes the original input per ingest. Forensic-grade traceability.
- **Provenance on every record.** Standardized records carry `vendor`, `vendor_software_version`, `cass_certification_cycle`, `usps_reference_data_release`, `normalizer_version`, `standardized_at`, `original_input`, and `raw_input_hash`. Household-membership records carry `inference_basis`, `inference_version`, `building_type`, `inferred_at`, and `canonical_hash`.
- **Building-type-aware household inference.** PO Boxes, commercial buildings, shelters, and nursing homes correctly map to CO_LOCATED rather than HOUSEHOLD; multi-unit-no-unit collapses also map to CO_LOCATED so a 200-record apartment-building collapse does not produce a "200-person household."
- **Graded household confidence contract.** The `confidence_level` field on every household-membership record uses the recipe-text-aligned vocabulary (HIGH, MEDIUM, CO_LOCATED, SUPPRESSED, SINGLE_PATIENT). Downstream consumers see a consistent shape and can gate on confidence.
- **Drift-event surface.** Four event types are emitted (`address_standardized`, `address_drift_detected`, `ncoa_mover_detected`, `household_inferred`), matching the recipe's Step 3D and Step 5 enumerations. Note: the demo's bypass of the in-memory registry update per Finding 1 means the demo does not produce realistic post-drift household-inferred events, but the event-emission code itself is correct.
- **Versioning.** `NORMALIZER_VERSION` and `HOUSEHOLD_INFERENCE_VERSION` are stored on the relevant records so a future investigation can attribute drift to a specific release.
- **Customer-managed KMS posture.** Documented in Setup and Gap to Production.
- **International-address handling.** The pipeline short-circuits non-US addresses to `INTERNATIONAL_NOT_PROCESSED`, with the recipe-text-aligned discussion of when an institution should license a multi-country service.
- **Equity instrumentation.** The recipe text spends substantial space on cohort-stratified accuracy monitoring. The Python emits per-status and per-confidence counters to CloudWatch but does not stratify by cohort. Acknowledged in Gap to Production.

Pass on healthcare-specific handling. The demo-only registry-bypass gap (Finding 1) is the operationally-relevant gap.

---

## Logical Flow

The file reads top-to-bottom in pedagogical order matching the pseudocode numbering: Setup, Configuration and Constants (logger, retry config, module-level clients, resource names, normalizer-and-inference versions, cache TTL, re-validation cadence, building-type-to-eligibility map, privacy policy, building-type heuristics, helper utilities), Mock CASS-Certified Validator (with the small `_KNOWN_ADDRESSES` dictionary covering the demo's six exemplar address inputs), Step 1 (ingest with raw-input archive), Step 2 (standardize with classification, structured-form capture, provenance, and cache), Step 3 (persist with previous-record read, change detection, audit archive, change event), Step 4 (household inference with privacy suppression, building-type classification, corroborating-evidence assessment, graded-confidence assignment, household-membership writes, household-inferred event), Step 5 (monthly USPS refresh and simulated quarterly NCOA), Full Pipeline (`run_standardize_pipeline_for_patient` plus the in-memory registry stand-in), Synthetic Data (PATIENT_DEMOGRAPHICS, PATIENT_PRIVACY_FLAGS, SYNTHETIC_SOURCE_EVENTS, NCOA mover scenario), Demo Runner (`run_demo` with three phases), Gap to Production.

Each step opens with a short italic prose paragraph that restates the pseudocode step before the code block, matching the cookbook's established pattern. The italic paragraphs name the step's role and the failure mode that step prevents.

The demo runner builds eleven synthetic source events covering five scenarios: the Patel family at 1421 Elm St Apt 3B (HIGH-confidence household, but the suppressed Doe record forces the SUPPRESSED branch under the demo's active policy), the Kim record at 1421 Elm St Apt 5A (different unit, different canonical, SINGLE_PATIENT), the privacy-suppressed Doe record at 1421 Elm St Apt 3B (forces the suppress-entire-group branch), the PO Box patient (CO_LOCATED via building-type), the shelter patient (CO_LOCATED via business-name keyword), three unrelated patients at 100 Main St with no unit numbers (CO_LOCATED via multi-unit-no-unit), and the typo'd Patel record at "1421 elm stret apt 3b" (CORRECTED with the canonical hash colliding with the family's hash). The roster choice exercises every code path the recipe wants to demonstrate. **The NCOA simulation in Phase 2 does not actually deliver the post-mover state described in the prose per Finding 1.**

---

## What Is Done Particularly Well

Worth calling out explicitly:

- The standardization-status classification is precise and recipe-aligned. `_classify_vendor_response` maps DPV codes (`Y` with no correction → VALIDATED, `Y` with correction → CORRECTED, `S` → MISSING_SECONDARY, `D` → AMBIGUOUS, `N` or `no_match` → NOT_VALIDATED, anything else → INVALID) onto the recipe text's six well-defined statuses. Each status carries the right downstream metadata (`candidate_addresses` only for AMBIGUOUS, `correction_confidence` only for CORRECTED, full structured form for VALIDATED / CORRECTED / MISSING_SECONDARY).
- The privacy-suppression-as-first-class-case discipline is implemented at the right place. `infer_household_for_address` checks privacy flags before building-type classification or evidence assessment. The two policy options (`suppress_entire_group_if_any_suppressed` and `exclude_suppressed_from_group`) are honest about the decision being deferred to the institution rather than implemented one way and called done.
- The building-type-to-household-eligibility map is the right pattern. Some building types (PO Box, commercial, shelter, nursing home, multi-unit-no-unit, unknown) do not produce meaningful household inferences. Encoding this in a constant dictionary makes the decision visible and auditable, and makes per-institution overrides (a hospital that wants to attempt household inference at long-term-care facilities, for example) a one-line change.
- The corroborating-evidence assessment is granular and recipe-aligned. `_last_name_overlap`, `_subscriber_overlap`, `_age_pattern_consistent`, and `_assign_confidence` together produce the recipe text's *"Same address (high confidence) and corroborating evidence (high confidence): infer household"* graded-confidence behavior. The point thresholds in `_assign_confidence` are exposed and tunable.
- The shelter detection via business-name keyword (`SHELTER_KEYWORDS = ["shelter", "rescue mission", "transitional housing"]`) is honest about being a heuristic. The docstring on `classify_building_type` calls out that *"Production refines this with parcel data, address-quality vendor classifications, and (for nursing homes and shelters) a curated facility list."* This is the right level of pedagogical honesty.
- The standardization cache pattern catches the recipe-text-named common case. *"Many addresses repeat across patient records (family members at the same address, address copied from one record to another)."* The cache keyed on `raw_input_hash` correctly hits on repeats. The TTL is exposed as a constant tied to the USPS reference-data refresh cadence.
- The TechWriter TODO comments are precise and operationally useful. The transactional-outbox TODO in `persist_standardized_record` names exactly the right pattern; the deploy-time guardrail TODO in the constants block names exactly the right extension.
- The Gap to Production section enumerates the dozens of items between the demo and a production deployment with appropriate breadth: real CASS vendor SDK and BAA, real DynamoDB schema with the canonical-hash GSI, TransactWriteItems for atomic writes, vendor-cost monitoring with per-workflow tagging, Glue-on-Spark for batch pipelines, real NCOA integration, Step Functions orchestration with retry / timeout / DLQ, real geocoding and SDOH joins, privacy-officer-approved suppression policy, cohort-stratified accuracy monitoring, registration-time correction-confirmation UX, patient-portal self-service confirmation flow, KMS / VPC / Secrets Manager / CloudTrail posture, international-address handling, idempotency keys on every write, outreach-list scrubbing, backfill strategy. The breadth honestly tells the reader how much sits between the recipe and a production deployment.
- The synthetic source events exercise the full classification range. The eleven records cover VALIDATED, CORRECTED, MISSING_SECONDARY, PO Box, shelter, multi-unit-no-unit collapse, single-patient, family unit, privacy-suppressed group member, and same-building-different-unit. A learner running the demo sees every code path fire.
- The mock validator's response shape is a faithful approximation of what real CASS-certified vendors return. The DPV codes, the `delivery_line_1` / `last_line` / `components` / `metadata` structure, the `dpv_footnotes` list, the `record_type` and `is_residential` / `is_business` / `is_po_box` flags, the `congressional_district` and `census_block` and `carrier_route` fields are all real fields the production vendors expose. A learner who later swaps to a real SDK has a clear mental model.

---

## Closing Assessment

The teaching content is well-organized and faithful to the main recipe in structure, prose framing, and pedagogical ordering. The five pseudocode steps map onto Python functions with helpers in the right places. The DynamoDB + S3 + EventBridge + CloudWatch API call shapes are correct. The Decimal-at-the-DynamoDB-boundary discipline is consistent. The standardization-status classification, building-type classification, graded-confidence household contract, privacy-suppression-as-first-class-case discipline, drift-classification, and event-fan-out patterns are all structurally correct. The mock validator response shape is a faithful approximation of the production CASS vendor APIs.

The single WARNING is localized and well-scoped. Finding 1 (the in-memory registry bypass in `simulate_ncoa_processing` and `monthly_usps_refresh`) is the consistency gap with the most pedagogical consequence: the prose makes an explicit claim about post-NCOA household state that the demo does not deliver. The fix is small (move the registry update inside `persist_standardized_record`) and validates against re-running the demo and inspecting the post-NCOA household state for the Patel household at Apt 3B and the previously-SINGLE_PATIENT canonical at Apt 5A.

The four NOTEs are smaller items: the canonical-hash construction's redundant secondary-number parameter, the missing inline comment explaining where pseudocode Step 3E went, the unused `dateparser` import, and the partial deploy-time guardrail covering only `AUDIT_BUCKET`.

PASS verdict per the persona's rule: no ERRORs, one WARNING (under the FAIL threshold of more than three). The WARNING and the more load-bearing NOTEs (Findings 2 and 3) should be addressed before the recipe ships, because they teach a demo whose NCOA path silently produces wrong results, a canonical-hash construction with an avoidable redundancy, and a pseudocode-to-Python mapping that omits an inline explanation for the Step 3E hoist. None of these block the demo from running to completion.

Recipe 5.3 is the third simple-tier recipe in Chapter 5; the recipe text frames it explicitly: *"It is in the Simple-Medium tier because the address standardization piece is largely a solved problem (USPS publishes the rules, vendors are CASS-certified to implement them, the failure modes are well-documented), but the household-linkage piece introduces real ambiguity (same address does not always mean same household, and the wrong inference can leak privacy or violate consent)."* Closing the WARNING and the most-load-bearing NOTEs brings the example up to the standard the recipe text claims, which is appropriate given that the address-and-household-specific deviations (the standardization-status classification, the building-type-aware household inference, the privacy-suppression-as-first-class-case discipline, the NCOA-driven mover propagation) are the entire reason this is a separate recipe from 5.1 and 5.2.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** `persist_standardized_record` updates `_IN_MEMORY_ADDRESS_REGISTRY` after every successful persist, so `simulate_ncoa_processing` and `monthly_usps_refresh` propagate registry state correctly. Re-run the demo and confirm: after Phase 2's NCOA mover detection, the Patel household at Apt 3B re-evaluates without `patient-internal-00874`, and the canonical at Apt 5A re-evaluates from SINGLE_PATIENT to a two-record group containing `patient-internal-00874` and `patient-internal-00990`. Optionally extend the demo's print output to surface post-NCOA household-inference results so the success of the fix is visible.
2. **(NOTE)** `_build_canonical_hash` accepts only `delivery_line_1` and `last_line` (no separate `secondary_number` parameter), and the canonical form does not contain the unit number twice for any input.
3. **(NOTE)** `persist_standardized_record` includes an inline comment naming where pseudocode Step 3E went, or the household-inference call is inlined back into `persist_standardized_record` to track the pseudocode literally.
4. **(NOTE)** The `from dateutil import parser as dateparser` import is removed and the `pip install` line drops `python-dateutil`.
5. **(NOTE)** The deploy-time guardrail is extended to cover all resource-name constants (`ADDRESS_TABLE`, `HOUSEHOLD_TABLE`, `CANONICAL_HASH_INDEX`, `AUDIT_BUCKET`, `EVENTS_BUS_NAME`, `CLOUDWATCH_NAMESPACE`).

After the WARNING fix, re-run the demo end-to-end and confirm the post-NCOA household state matches the prose's explicit claim. The other NOTEs are low-risk cleanups that improve pedagogical clarity but do not change observable behavior.
