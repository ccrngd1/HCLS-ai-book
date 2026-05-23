# Code Review: Recipe 5.8 - Privacy-Preserving Record Linkage

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-22
**Files reviewed:**
- `chapter05.08-privacy-preserving-record-linkage.md` (main recipe pseudocode)
- `chapter05.08-python-example.md` (Python companion)

**Validation performed:**
- Walked the six pseudocode steps against the Python functions one-to-one
- Verified boto3 API call shapes for S3 (`put_object`), SQS (`send_message`), EventBridge (`put_events`), CloudWatch (`put_metric_data`), KMS (referenced)
- Hand-traced the encoding flow (standardize → encode → exchange → match → disclose) for Catherine, Maria, Margaret, Theodore, Patricia (consent withdrawn) on the A side and Catherine, Maria, Margaret, Robert on the B side
- Hand-computed per-feature Sørensen-Dice for the Catherine A vs Catherine B identical pair (composite = 1.0) and Maria A vs Maria B near-identical pair (middle name = "" on both sides)
- Walked the missing-feature handling path through `_per_feature_bloom_filter_from_envelope`, `_compute_per_feature_similarities`, and `_sorensen_dice_coefficient` to verify the comment-vs-implementation gap
- Verified the parameterization-version and salt-key-version mismatch checks at exchange time
- Walked the disclosure-form dispatch (per_record_match_flags, intersection_count, k_anonymous_aggregate, plus the "not implemented" else branch for differentially_private_aggregate and encrypted_match_indicator)
- Verified the dual-control approval enforcement on `MockSaltCustody.rotate_salt`
- Walked the six invalidation-event source branches (salt_rotation, parameterization_upgrade, consent_withdrawal, identity_merge_recipe_5_1, name_change_recipe_5_7, re_identification_risk_model_update)
- Verified Decimal-at-the-DynamoDB-boundary discipline (no actual DynamoDB writes in demo, but threshold constants and similarity scores are Decimals throughout)
- Verified S3 keys do not carry leading slashes (`f"{partition}/{today}/{kid}.json"` pattern)
- Verified deploy-time guardrail asserts every resource-name constant is non-empty

---

## Summary

The Python companion is structurally faithful to the main recipe's six pseudocode steps and the architectural picture (standardize and prepare per-participant demographic-feature set with consent filtering and cohort-axis-hash derivation; apply CLK Bloom-filter encoding under the pinned protocol parameterization with per-feature bit allocation; exchange encoded records under the trust architecture with parameterization and salt-key version validation; match encoded records using Sørensen-Dice over per-feature filters combined Fellegi-Sunter-style with encoded-data thresholds; apply the disclosure policy and route in the protocol-authorized form; react to invalidation events that supersede prior linkages). The Decimal-at-the-DynamoDB-boundary discipline is consistent (though no actual DynamoDB writes happen in the demo), S3 keys do not carry leading slashes, the parameterization-version-and-salt-key-version pinning prevents the silent-failure mode at exchange time, the dual-control approval requirement on salt rotation is enforced and demonstrated, and the `MockSaltCustody`, `MockProtocolParameterizationStore`, `MockConsentStore`, and `MockJurisdictionalOverlays` replacements for production dependencies are clearly framed and exercise the major paths.

That said, this companion ships with one WARNING and several NOTEs. The WARNING concerns the missing-feature handling in `_compute_per_feature_similarities`: the function's comments claim the `len(filter_a) == 0` branches handle missing-both-features (returning 0.5) and one-feature-missing (returning 0.0), but neither branch ever fires because `_encode_per_feature_bloom_filter` always returns a non-zero-size bytearray for any feature that has a non-zero allocation in the parameterization (even when the feature value is empty, the function returns an all-zero bit array of the per-feature size). The actual behavior for both missing-both and one-missing cases is to fall through to `_sorensen_dice_coefficient`, which returns Decimal("0") via the `set_a + set_b == 0` branch. The bug is silent in the demo because Maria's missing middle name (both A and B records have middle_name=None) drags her composite from ~0.96 to ~0.92, but she still lands well above the 0.85 MATCH_HIGH threshold so no decision band flips. A reader copying this missing-feature pattern into production carries forward a matcher whose comments describe behavior the code does not deliver, with the specific consequence that records with missing features get systematically lower scores than the architecture's intent.

The NOTEs cover smaller items: the `clk_payload` is computed in the encoder but never read by the matcher (the matcher uses `per_feature_filters` directly), so the combined CLK is dead data in the envelope; the `defensive_measures` flags in the parameterization (`random_hashing_enabled`, `balanced_encoding_enabled`, `hardening_enabled`) are present in the configuration but `_encode_per_feature_bloom_filter` does not check or apply them, so toggling the flags has no effect (this is acknowledged in the Heads-up but the dead flags are misleading); the `encoded_record_id` prefix uses `participant_id[:1]` which produces "p" for both participants because both names start with "participant-"; the `match_rate_lower_bound` and `match_rate_upper_bound` in `_build_intersection_count` have no guaranteed ordering relative to each other (lower-bound uses A's denominator, upper-bound uses B's; if A's denominator is smaller, the labeled "lower" bound is actually larger); and `_emit_metric` hardcodes `Unit="Count"` for all metrics, which is consistent with the demo's actual emissions (all use value=1.0 as counts) but constrains future score-emit additions.

---

## Verdict: PASS

No ERRORs. One WARNING (the missing-feature dead-code-with-misleading-comment, which produces 0 instead of the documented 0.5 for missing-both and behaves identically to the one-missing case the comment treats as a separate condition). Five NOTEs.

The WARNING and the most-load-bearing NOTEs (Findings 2 and 3) should be addressed before the recipe ships, because they teach a missing-feature handling pattern whose comments do not match the code's behavior, a CLK-payload field that is computed but never consumed, and a defensive-measures configuration that has no effect on encoding. None of these block the demo from running to completion or flip any decision band in the documented expected output.

Recipe 5.8 is the eighth recipe in Chapter 5 and inherits the chapter's operational discipline (graded confidence with deferred review, audit-everything substrate, drift-event fan-out, cohort-stratified telemetry, transactional-outbox eventing, conservative threshold posture) from recipes 5.1-5.7. The PPRL-specific behaviors that differentiate it (CLK Bloom-filter encoding before exchange, parameterization-version-pinning to prevent silent linkage failures, salt-rotation with dual-control approval ceremony, multi-form disclosure policy with per-cohort-axis-hash derivation that lets the matcher stratify accuracy without learning the underlying axis values, six-source invalidation pipeline including salt-rotation and parameterization-upgrade events) are all structurally present.

---

## Findings

### Finding 1: `_compute_per_feature_similarities` Missing-Feature Branches Are Dead Code; Missing-Both and One-Missing Both Silently Return 0 Instead of the Commented-Intent 0.5 and 0.0

- **Severity:** WARNING
- **File:** `chapter05.08-python-example.md`
- **Location:** `_compute_per_feature_similarities`; the `if len(filter_a) == 0 and len(filter_b) == 0:` and `elif len(filter_a) == 0 or len(filter_b) == 0:` branches; `_encode_per_feature_bloom_filter` for the `if not value:` return path; `_per_feature_bloom_filter_from_envelope`
- **Description:**

  The matcher's per-feature comparison enumerates three cases:

  ```python
  def _compute_per_feature_similarities(envelope_a, envelope_b, parameterization):
      similarities = {}
      for feature_name in parameterization["per_feature_bit_allocation"].keys():
          filter_a = _per_feature_bloom_filter_from_envelope(envelope_a, feature_name)
          filter_b = _per_feature_bloom_filter_from_envelope(envelope_b, feature_name)
          if len(filter_a) == 0 and len(filter_b) == 0:
              similarities[feature_name] = Decimal("0.5")  # missing both
          elif len(filter_a) == 0 or len(filter_b) == 0:
              similarities[feature_name] = Decimal("0.0")  # one missing
          else:
              similarities[feature_name] = _sorensen_dice_coefficient(filter_a, filter_b)
      return similarities
  ```

  The intent is clear from the comments: a feature missing on both sides should score 0.5 (no information either way), a feature missing on one side should score 0.0 (mismatch), and otherwise compute Sørensen-Dice on the bit-encoded filters.

  The implementation does not deliver this. Trace through the encoder for a missing value:

  ```python
  def _encode_per_feature_bloom_filter(value, feature_name, parameterization, salt):
      per_feature_size = _compute_per_feature_size(parameterization, feature_name)
      if per_feature_size == 0:
          return bytearray(0)
      feature_filter = _bit_array(per_feature_size)
      if not value:
          return feature_filter   # all-zero filter of the feature's allocation
      ...
  ```

  For the demo's parameterization, every feature in `per_feature_bit_allocation` has a non-zero size (200, 100, 300, 150, 150, 50, 50, 24). So `_encode_per_feature_bloom_filter` for an empty value returns `_bit_array(per_feature_size)`, which is a bytearray of size `(per_feature_size + 7) // 8` bytes filled with zeros. For middle_name with size 100, that's a 13-byte bytearray with all bits zero.

  The envelope stores it as `bytes(filter)`:

  ```python
  "per_feature_filters": {
      f: bytes(filt) for f, filt in per_feature_filters.items()
  },
  ```

  `bytes(13-byte bytearray of zeros)` is `b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'` — 13 bytes. Truthy because non-empty (Python truthiness on bytes is based on length, not content).

  The matcher reads it back:

  ```python
  def _per_feature_bloom_filter_from_envelope(envelope, feature_name):
      raw = envelope["per_feature_filters"].get(feature_name)
      return bytearray(raw) if raw else bytearray(0)
  ```

  `raw` is the 13-byte bytes object (truthy), so `bytearray(raw)` is returned with length 13. The `len(filter_a) == 0` checks in `_compute_per_feature_similarities` therefore evaluate to False for every feature in the parameterization, regardless of whether the underlying value was present or empty. The Decimal("0.5") and Decimal("0.0") branches are dead code.

  The actual missing-feature behavior falls through to `_sorensen_dice_coefficient`:

  ```python
  def _sorensen_dice_coefficient(bits_a, bits_b):
      set_a = _count_set_bits(bits_a)   # 0 for an all-zero filter
      set_b = _count_set_bits(bits_b)   # 0 for an all-zero filter
      if set_a + set_b == 0:
          return Decimal("0")
      intersection = _bitwise_and_count(bits_a, bits_b)
      return Decimal("2") * Decimal(intersection) / Decimal(set_a + set_b)
  ```

  For missing-both (both filters all zero): `set_a = set_b = 0`, returns `Decimal("0")` — NOT 0.5 as the comment intends.

  For one-missing (one filter all zero, one with bits set): `set_a + set_b > 0`, `intersection = 0` (any bit AND zero-bit = zero), returns `2 * 0 / (set_a + set_b) = 0` — coincidentally matches the comment's intended 0.0, but for the wrong reason.

  Demo impact:

  - **Maria A vs Maria B (middle_name=None on both sides):** both records normalize middle_name to "" via `_canonical_name(source_record.get("middle_name") or "")`. Both encoded filters for middle_name are all-zero 13-byte bytearrays. `len(filter_a) == 0` is False on both sides (length is 13). The first two branches in `_compute_per_feature_similarities` do not fire. Falls through to Sørensen-Dice, returns 0. With middle_name weight 0.08, Maria's composite drops from ~0.96 (if 0.5 fired as the comment intends) to ~0.92 (with the actual 0). Still above 0.85, still MATCH_HIGH. No band flip.
  - **Margaret A vs Margaret B (middle_name=None on both sides):** same path, same drop, same MATCH_HIGH. No band flip.
  - **Catherine A vs Catherine B (middle_name="Marie" on both):** middle_name filters have bits set on both sides, fall through to Sørensen-Dice, return ~1.0. No impact.
  - **Theodore A (middle_name="James") vs any B record (middle_name=None):** Theodore's filter has bits, B's is all zero. Sørensen-Dice returns 0 (the one-missing case the comment intends to handle). Coincidentally matches the comment's 0.0, but only because Sørensen-Dice happens to produce 0 on a zero-AND-anything intersection.

  Pedagogical impact:

  1. **The reader sees a missing-feature handling pattern that is documented to handle three cases distinctly but in fact collapses all three into "Sørensen-Dice on whatever bytearray is in the envelope."** A reader who extends the matcher with more nuanced missing-feature logic (per-feature missing-feature weights, sentinel filters, missing-feature-aware Fellegi-Sunter combiner) inherits the dead-check pattern and assumes it works.
  2. **The architectural intent is wrong about what the demo does.** The Heads-up section says "the matcher's Fellegi-Sunter combiner handles missing-feature cases under specific weights"; the encoder's `if not value:` comment says "Missing feature gets an empty filter; the matcher's Fellegi-Sunter combiner handles missing-feature cases under specific weights. Production has explicit missing-feature sentinel handling; the demo uses an empty filter as the simplest stand-in." But the matcher's combiner does NOT handle missing features under specific weights; it just runs Sørensen-Dice on whatever bytearray is in the envelope, with no awareness that the bytearray represents an empty value.
  3. **The pseudocode's Step 2C explicitly produces a "missing_feature_filter" sentinel via `produce_missing_feature_filter(parameterization, feature_name)`** that the matcher would distinguish from a real filter. The Python's empty-bytearray approach is cited as a simplification, but the simplification is silent; a reader looking at the comment in `_compute_per_feature_similarities` sees the three-case branching and reasonably assumes the simplification preserves the semantic distinction. It does not.

- **Suggested fix:** Either implement the comment's intent or remove the dead branches.

  Option A (preserve the intent, smallest change): use a set-bit count of zero as the "missing" indicator instead of a bytearray length of zero, since an all-zero bytearray is what the encoder actually produces for missing values:

  ```python
  def _compute_per_feature_similarities(envelope_a, envelope_b, parameterization):
      similarities = {}
      for feature_name in parameterization["per_feature_bit_allocation"].keys():
          filter_a = _per_feature_bloom_filter_from_envelope(envelope_a, feature_name)
          filter_b = _per_feature_bloom_filter_from_envelope(envelope_b, feature_name)
          # An all-zero filter is the encoder's missing-value sentinel
          # (the encoder returns _bit_array(per_feature_size) for empty
          # input). Test for the sentinel by population count rather
          # than bytearray length, since the bytearray is sized to
          # the per-feature allocation regardless of input.
          set_a = _count_set_bits(filter_a)
          set_b = _count_set_bits(filter_b)
          if set_a == 0 and set_b == 0:
              similarities[feature_name] = Decimal("0.5")  # missing both
          elif set_a == 0 or set_b == 0:
              similarities[feature_name] = Decimal("0.0")  # one missing
          else:
              similarities[feature_name] = _sorensen_dice_coefficient(filter_a, filter_b)
      return similarities
  ```

  After the fix, hand-trace Maria's middle_name comparison: both `set_a` and `set_b` are 0 (all-zero filters), the first branch fires, similarity = Decimal("0.5"), Maria's composite climbs from ~0.92 to ~0.96. Still MATCH_HIGH. The composite reflects the architectural intent.

  Option B (acknowledge the simplification, minimal change): drop the dead branches entirely and rely on Sørensen-Dice's natural behavior (returns 0 for missing-both, returns 0 for one-missing). Add an inline comment that the demo treats missing features as zero-similarity for both sides; production extends with explicit missing-feature weights:

  ```python
  def _compute_per_feature_similarities(envelope_a, envelope_b, parameterization):
      """Per-feature Sørensen-Dice similarity. The encoder's
      missing-value sentinel is an all-zero filter; Sørensen-Dice
      naturally returns 0 for such filters (set_a + set_b == 0 or
      intersection == 0 path). Production uses explicit missing-
      feature weights in the Fellegi-Sunter combiner instead of
      treating missing as zero-similarity, which systematically
      under-scores records with missing features; the demo's
      simplification is acceptable for illustration but should
      not be carried into production."""
      similarities = {}
      for feature_name in parameterization["per_feature_bit_allocation"].keys():
          filter_a = _per_feature_bloom_filter_from_envelope(envelope_a, feature_name)
          filter_b = _per_feature_bloom_filter_from_envelope(envelope_b, feature_name)
          similarities[feature_name] = _sorensen_dice_coefficient(filter_a, filter_b)
      return similarities
  ```

  Option A is preferred because it preserves the architectural intent the prose describes. Either way, re-run the demo after the fix and confirm the printed `match_score: 1.000` for the Catherine MATCH_HIGH sample is unchanged (Catherine has no missing features), and that the consent_dropped count and the 13 review pairs are unchanged.

---

### Finding 2: `clk_payload` Is Computed by `_combine_per_feature_filters` and Stored in the Envelope but Never Read by the Matcher; the Combined CLK Is Dead Data in Every Encoded-Record Envelope

- **Severity:** NOTE
- **File:** `chapter05.08-python-example.md`
- **Location:** `encode_record`'s `clk = _combine_per_feature_filters(...)` and `"clk_payload": bytes(clk)` envelope field; `_per_feature_bloom_filter_from_envelope` for the matcher's read path
- **Description:**

  The encoder produces both a record-level CLK (the combined Bloom filter, sized at `parameterization["bloom_filter_size"] = 1024` bits) and a per-feature filter dict:

  ```python
  # 2D: combine into the record-level CLK.
  clk = _combine_per_feature_filters(per_feature_filters, parameterization)

  encoded_record_envelope = {
      ...
      "clk_payload":             bytes(clk),  # serialized as base64 in DDB/S3
      "per_feature_filters":     {  # retained for per-feature scoring
          f: bytes(filt) for f, filt in per_feature_filters.items()
      },
      ...
  }
  ```

  The matcher reads only the per-feature filters:

  ```python
  def _per_feature_bloom_filter_from_envelope(envelope, feature_name):
      raw = envelope["per_feature_filters"].get(feature_name)
      return bytearray(raw) if raw else bytearray(0)
  ```

  Grep across the file confirms `clk_payload` is referenced only at the assignment site in `encode_record` and never read.

  Pedagogical impact:

  1. **The combined CLK is the recipe's headline cryptographic artifact** — the prose spends thousands of words explaining what a CLK is and why it is the matcher's input. A reader who follows the prose expects the matcher to operate on the CLK; the Python's matcher operates on the per-feature filters instead. Both produce equivalent results in the simple Sørensen-Dice case, but the demonstration of CLK semantics is structurally absent from the matcher path.
  2. **The per-feature filter approach is a legitimate alternative that the recipe text actually advocates** for the per-feature Fellegi-Sunter combiner step ("The matcher consumes these similarity scores in the same Fellegi-Sunter-style probabilistic combiner that recipe 5.1 uses, with the per-feature similarity scores derived from per-feature Bloom-filter comparisons"). So the matcher's actual approach is correct; the dead `clk_payload` is the issue, not the matcher's choice.
  3. **The serialization comment is misleading.** `# serialized as base64 in DDB/S3` implies the CLK gets persisted. In the demo, the entire envelope is in-memory only; nothing reaches DynamoDB or S3. A reader inspecting the envelope shape sees `clk_payload` as a load-bearing field when it is in fact unused.

- **Suggested fix:** Two options:

  **Option A (use the CLK in the matcher):** rewrite `_per_feature_bloom_filter_from_envelope` to extract the per-feature slice from the combined CLK using the same cursor-walking logic as `_combine_per_feature_filters`. This is more faithful to the architectural posture (the matcher consumes the CLK; the per-feature filters are an encoder-side intermediate) but requires more code.

  **Option B (drop clk_payload from the envelope):** remove the unused field and update the Heads-up to note that the demo's matcher operates on per-feature filters directly rather than on the combined CLK. This is the smaller change:

  ```python
  encoded_record_envelope = {
      "participant_id":          prepared_record["participant_id"],
      "encoded_record_id":       encoded_record_id,
      # The demo's matcher reads per_feature_filters directly for
      # per-feature Sørensen-Dice + Fellegi-Sunter scoring.
      # Production with a single-CLK matcher (faster, since one
      # bitwise AND across the full record-level filter beats per-
      # feature accounting) would store clk_payload here and
      # extract per-feature slices at scoring time using the same
      # cursor logic as _combine_per_feature_filters.
      "per_feature_filters": {
          f: bytes(filt) for f, filt in per_feature_filters.items()
      },
      ...
  }
  ```

  Either option resolves the dead-data concern. Option B is preferred for a teaching snippet because it reduces the cognitive load (one fewer field for the reader to trace) and explicitly names the architectural choice.

---

### Finding 3: `defensive_measures` Configuration Flags Are Read From the Parameterization but Never Consulted in the Encoder; Toggling random_hashing_enabled, balanced_encoding_enabled, or hardening_enabled Has No Effect

- **Severity:** NOTE
- **File:** `chapter05.08-python-example.md`
- **Location:** `PROTOCOL_PARAMETERIZATION` constant; `_encode_per_feature_bloom_filter`; the parameterization-upgrade invalidation phase that flips `random_hashing_enabled` to True
- **Description:**

  The parameterization carries three defensive-measure flags:

  ```python
  PROTOCOL_PARAMETERIZATION = {
      ...
      "defensive_measures": {
          "random_hashing_enabled":   False,
          "balanced_encoding_enabled": False,
          "hardening_enabled":         False,
      },
  }
  ```

  The pseudocode's Step 2C explicitly applies these defensive measures based on the flags:

  ```
  IF parameterization.defensive_measures.random_hashing_enabled:
      feature_filter = apply_random_hashing(...)
  IF parameterization.defensive_measures.balanced_encoding_enabled:
      feature_filter = apply_balanced_encoding(...)
  IF parameterization.defensive_measures.hardening_parameters.enabled:
      feature_filter = apply_hardening(...)
  ```

  The Python's `_encode_per_feature_bloom_filter` does not consult any of these flags. There are no `apply_random_hashing`, `apply_balanced_encoding`, or `apply_hardening` functions in the file (grep confirms two hits total: the parameterization config itself and the parameterization-upgrade invalidation event that flips `random_hashing_enabled` to True for a new version).

  This is acknowledged in the Heads-up section ("the demo uses simplified Bloom filters that illustrate the construction without the production-grade defensive measures like random hashing, balanced encoding, or hardening") and again in the parameterization config's inline comment ("The demo's defensive measures are deliberately simple; production uses clkhash which implements current-best-practice variants"). So the simplification is documented at the architectural level.

  But the parameterization-upgrade phase in the demo's Phase 2 invalidation triggers explicitly publishes a new parameterization version with `random_hashing_enabled = True`:

  ```python
  new_param_config["defensive_measures"]["random_hashing_enabled"] = True
  inv_3 = invalidate_on_event({
      "source": "parameterization_upgrade",
      "event_id": "inv-2026-04-30-003",
      "new_parameterization_version": "pprl-clk-v2.4.0",
      "new_parameterization": new_param_config,
  })
  ```

  This action publishes the new parameterization to the config store and triggers a `schedule_coordinated_re_encoding` action. A reader following the demo expects that re-encoding under the new version would actually apply random hashing — the parameterization-upgrade event's whole point is to demonstrate the "the privacy team has updated the re-identification-risk model; defensive measures may need to be strengthened" path. Because the encoder doesn't honor the flags, re-encoding under the new version produces identically-behaved encoded records.

  Pedagogical impact: a reader who copies the recipe's defensive-measures-flag pattern into production has a configuration that is read but not honored. Toggling flags in the institutional governance committee meeting accomplishes nothing operational. The downstream impact is "we increased the parameterization version because the privacy team recommended hardening, but the encoder does not actually harden."

- **Suggested fix:** Either drop the flags from the demo's parameterization (acknowledging that the simplification omits them) or add stub function calls that demonstrate the flag-checking pattern even if the stubs are no-ops:

  ```python
  # Apply defensive measures per the parameterization. Production
  # implements these via clkhash; the demo's stubs document where
  # the calls would go without implementing the cryptographic
  # primitives.
  if parameterization["defensive_measures"]["random_hashing_enabled"]:
      feature_filter = _apply_random_hashing_stub(feature_filter)
  if parameterization["defensive_measures"]["balanced_encoding_enabled"]:
      feature_filter = _apply_balanced_encoding_stub(feature_filter)
  if parameterization["defensive_measures"]["hardening_enabled"]:
      feature_filter = _apply_hardening_stub(feature_filter)
  ```

  Where the stubs log the intent and pass through:

  ```python
  def _apply_random_hashing_stub(feature_filter):
      """Stub. Production randomizes the hash-function-to-bit-
      position mapping per record using clkhash; the stub
      preserves the call site so a reader extending the demo
      knows where to wire in the real primitive."""
      logger.debug("random hashing stub invoked (no-op in demo)")
      return feature_filter
  ```

  This preserves the demo's simplicity while making the configuration-toggle path observable. Alternatively, drop the flags from the config entirely and remove the parameterization-upgrade phase's `random_hashing_enabled` flip; the upgrade event then demonstrates only the version-bump-and-re-encode pattern.

---

### Finding 4: `encoded_record_id` Prefix Uses `participant_id[:1]` Which Produces "p" for Both Participants Because Both Names Start With "participant-"

- **Severity:** NOTE
- **File:** `chapter05.08-python-example.md`
- **Location:** `encode_record`'s `encoded_record_id` construction
- **Description:**

  The encoder generates the per-cycle pseudonymous identifier:

  ```python
  encoded_record_id = (
      f"enc-{cycle_id}-"
      f"{prepared_record['participant_id'][:1]}-"
      f"{uuid.uuid4().hex[:12]}")
  ```

  `participant_id[:1]` takes the first character. For both `"participant-A"` and `"participant-B"`, the first character is `"p"`. So every encoded_record_id has the format `enc-<cycle_id>-p-<uuid12>`, with no participant disambiguation in the prefix.

  The demo's expected output confirms this: the sample MATCH_HIGH lines print

  ```
  encoded_record_a_id: enc-cycle-2026-q2-research-001-p-XXXXXXXXXXXX
  encoded_record_b_id: enc-cycle-2026-q2-research-001-p-XXXXXXXXXXXX
  ```

  Both have the `-p-` prefix.

  Pedagogical impact: a reader reasonably expects the prefix to disambiguate the participant (e.g., `-A-` vs `-B-`). The demo's actual output makes the encoded_record_id participant-anonymous in its prefix, which is consistent with the recipe's "per-cycle pseudonym; not the source_record_id and not derived from the demographics" intent (since the participant-id is technically demographic), but it is also unhelpful for a reader debugging the demo's match results.

  This is a minor labeling issue, not a correctness bug. The code works as intended (the participant-id is on the envelope as a separate field, so the matcher can attribute records correctly).

- **Suggested fix:** If the intent is genuinely to anonymize the participant in the prefix, drop the `participant_id[:1]` substring entirely:

  ```python
  encoded_record_id = (
      f"enc-{cycle_id}-"
      f"{uuid.uuid4().hex[:12]}")
  ```

  If the intent is to disambiguate participants for demo readability, take the last character (or a hash of the full participant_id) instead:

  ```python
  encoded_record_id = (
      f"enc-{cycle_id}-"
      f"{prepared_record['participant_id'][-1].lower()}-"  # 'a' or 'b'
      f"{uuid.uuid4().hex[:12]}")
  ```

  Update the documented expected console output to match whichever choice the recipe makes. The current state (uniform "p" prefix) is internally consistent but pedagogically opaque.

---

### Finding 5: `_build_intersection_count` Names "match_rate_lower_bound" and "match_rate_upper_bound" but the Two Computations Have No Guaranteed Ordering Relative to Each Other

- **Severity:** NOTE
- **File:** `chapter05.08-python-example.md`
- **Location:** `_build_intersection_count`
- **Description:**

  The intersection-count disclosure form computes two match rates:

  ```python
  return {
      "intersection_count":  len(confirmed_matches),
      "participant_a_total": len(set(m["encoded_record_a_id"] for m in matches)),
      "participant_b_total": len(set(m["encoded_record_b_id"] for m in matches)),
      "match_rate_lower_bound":
          float(Decimal(a_count) / Decimal(max(len(set(m["encoded_record_a_id"] for m in matches)), 1))),
      "match_rate_upper_bound":
          float(Decimal(b_count) / Decimal(max(len(set(m["encoded_record_b_id"] for m in matches)), 1))),
  }
  ```

  `match_rate_lower_bound` is `a_count / a_total`. `match_rate_upper_bound` is `b_count / b_total`. Whether the A-side rate is actually lower than the B-side rate depends on which participant has more records.

  Conceptually: if A has 1000 records and B has 500, with 300 confirmed matches in the intersection, then a_count/a_total = 300/1000 = 0.3 and b_count/b_total = 300/500 = 0.6. The "lower" label is correct for A's denominator and the "upper" label is correct for B's denominator only because A's denominator is bigger.

  In the demo, both participants have 4 records and the intersection is 3, so a_count/a_total = b_count/b_total = 0.75 and the printed output says both bounds are 0.750. The labeling is internally consistent but the bounds-ordering is coincidental.

  In the general case where a_total != b_total, the labeling can be wrong. For example, if A has 500 records and B has 1000, the labeled "lower bound" is the higher value (3/5 = 0.6) and the labeled "upper bound" is the lower value (3/10 = 0.3).

  Pedagogical impact: a reader copying this pattern into production with imbalanced participant sizes gets a disclosure envelope where the lower-bound and upper-bound labels are not actually ordered. A consumer reading the disclosure expects `lower_bound <= upper_bound` and may compute downstream analytics on that assumption.

- **Suggested fix:** Either compute true bounds with min/max:

  ```python
  a_total = len(set(m["encoded_record_a_id"] for m in matches))
  b_total = len(set(m["encoded_record_b_id"] for m in matches))
  a_rate = float(Decimal(a_count) / Decimal(max(a_total, 1)))
  b_rate = float(Decimal(b_count) / Decimal(max(b_total, 1)))
  return {
      "intersection_count":  len(confirmed_matches),
      "participant_a_total": a_total,
      "participant_b_total": b_total,
      "match_rate_a":        a_rate,  # what fraction of A is in the intersection
      "match_rate_b":        b_rate,  # what fraction of B is in the intersection
      "match_rate_lower_bound": min(a_rate, b_rate),
      "match_rate_upper_bound": max(a_rate, b_rate),
  }
  ```

  Or rename the fields to remove the bounds framing if the intent is per-participant rates rather than bounds:

  ```python
  return {
      "intersection_count":  len(confirmed_matches),
      "participant_a_total": a_total,
      "participant_b_total": b_total,
      "intersection_rate_for_a": a_rate,
      "intersection_rate_for_b": b_rate,
  }
  ```

  Either fix makes the disclosure envelope's semantics match its labeling. Update the demo's printed output and the recipe's "Sample disclosure envelope (intersection-count form)" JSON to match.

---

### Finding 6: `_emit_metric` Hardcodes `Unit="Count"` for All Metrics; Demo Emissions Are All Counts but Future Score Emissions Will Be Mis-Labeled

- **Severity:** NOTE
- **File:** `chapter05.08-python-example.md`
- **Location:** `_emit_metric` helper
- **Description:**

  The helper hardcodes the unit:

  ```python
  def _emit_metric(metric_name, value, dimensions=None):
      try:
          cloudwatch_client.put_metric_data(
              Namespace=CLOUDWATCH_NAMESPACE,
              MetricData=[{
                  "MetricName": metric_name,
                  "Value": value,
                  "Unit": "Count",
                  "Dimensions": [...],
              }],
          )
      ...
  ```

  All current emit sites in the demo use the helper for actual counts (`StandardizeAndPrepare.Filtered`, `StandardizeAndPrepare.Prepared`, `EncodedRecords`, `ExchangeCompleted`, `MatchDecision`, `DisclosureCompleted`, `Invalidations`), so `Unit="Count"` is correct for the demo's actual emissions.

  But the recipe text describes per-cohort linkage-rate disparity dashboards, which would benefit from emitting the match_score itself as a continuous-value metric for distribution analysis. Same chapter pattern as recipe 5.7's Finding 6: a reader extending the demo with score-distribution metrics inherits the hardcoded `Unit="Count"`, which is misleading for 0-1 confidence values.

- **Suggested fix:** Add an optional `unit` parameter with a `Count` default, matching the recipe 5.7 fix:

  ```python
  def _emit_metric(metric_name, value, dimensions=None, unit="Count"):
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
                          extra={"metric": metric_name, "error": str(exc)})
  ```

  The fix is mechanical and makes the helper composable for future score-emit additions.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Function | Consistent? |
|----------------|-----------------|-------------|
| `standardize_and_prepare(source_record_batch, participant_id, consent_filter_policy, cohort_axis_specification)` | `standardize_and_prepare` plus `_normalize_address`, `_normalize_phone`, `_canonical_name`, `_strip_diacritics`, `_compute_cohort_axis_hashes` | Yes (1A applies the consent filter via `consent_store.is_consent_active`; 1B normalizes the demographic features under the protocol's shared schema; 1C computes cohort-axis hashes locally; 1D tags the record with the metadata the matcher needs but that does not expose demographics). The pseudocode's `consent_filter_policy.permits()` becomes `consent_store.is_consent_active(record, purpose)`; behaviorally equivalent. |
| `encode_record(prepared_record, parameterization_version)` | `encode_record` plus `_encode_per_feature_bloom_filter`, `_combine_per_feature_filters`, `_hash_to_bit_position`, `_set_bit`, `_bit_array` | Mostly yes (2A loads the pinned parameterization; 2B loads the salt key for this cycle; 2C produces the per-feature Bloom filters by tokenizing into n-grams and hashing each n-gram by k functions; 2D combines into the record-level CLK; 2E builds the encoded-record envelope; 2F persists the per-cycle local mapping at the participant). **The defensive-measures application path (Step 2C's `apply_random_hashing`, `apply_balanced_encoding`, `apply_hardening`) is omitted entirely per Finding 3**; the pseudocode's `produce_missing_feature_filter` sentinel becomes an all-zero filter which the matcher does not distinguish from real filters per Finding 1. The combined `clk_payload` is computed but the matcher does not consume it per Finding 2. |
| `exchange_encoded_records(encoded_record_envelopes, trust_architecture_config, cycle_id)` | `exchange_encoded_records` | Yes (3A validates that every envelope's parameterization and salt-key version match the cycle's pinned versions, raising on mismatch; 3B routes per the trust architecture with branches for tokenizer_model, linkage_broker_model, tee_attested_endpoint, smpc_protocol_runner, with the demo defaulting to linkage_broker_model and storing in `_IN_MEMORY_EXCHANGE_BUCKET`; 3C logs the exchange to the audit store via `_archive_to_s3`). The pseudocode's TEE attestation verification and SMPC protocol-runner invocation are stubbed (no `verify_attestation` or `smpc_runner.execute_protocol` exists in the demo); the demo runs all participants in one process so the exchange is logically rather than physically separate. |
| `match_encoded_records(encoded_record_sets, parameterization, threshold_calibration, cohort_axis_specification)` | `match_encoded_records` plus `_candidate_pairs`, `_compute_per_feature_similarities`, `_combine_with_fellegi_sunter`, `_sorensen_dice_coefficient`, `_bitwise_and_count` | Mostly yes (4A candidate generation via Cartesian product; 4B per-feature similarity scoring with Sørensen-Dice over Bloom filters; 4C Fellegi-Sunter combination as weighted-average across per-feature similarities; 4D applies encoded-data thresholds to route to MATCH_HIGH / MATCH_MED_REVIEW / REJECT / REVIEW; 4E builds the per-pair result with evidence summary and cohort-axis hashes). **The missing-feature handling in `_compute_per_feature_similarities` is dead code per Finding 1.** The pseudocode's locality-sensitive-hashing candidate generation is replaced with full Cartesian product (acknowledged in the demo's comment "the demo iterates the full Cartesian product because the demo population is small"). |
| `disclose_linkage_results(match_results, disclosure_policy, cycle_id)` | `disclose_linkage_results` plus `_filter_by_consent`, `_build_per_record_match_flags`, `_build_intersection_count`, `_build_k_anonymous_aggregate` | Mostly yes (5A consent-and-purpose filter; 5B disclosure-form transformation with branches for per_record_match_flags, intersection_count, k_anonymous_aggregate, with differentially_private_aggregate and encrypted_match_indicator falling to a "not implemented in demo" else branch; 5C routes to the target consumer via logging stub; 5D emits the cycle-completion event for cross-recipe consumers; 5E logs the disclosure to the audit archive). The pseudocode's `build_differentially_private_aggregate` and `build_encrypted_match_indicator` are deliberately omitted; the comment explicitly names "production uses real DP / encryption primitives." **The intersection_count's match_rate_lower_bound and match_rate_upper_bound have no guaranteed ordering per Finding 5.** |
| `invalidate_on_event(invalidation_event)` | `invalidate_on_event` | Yes (six event-source branches: salt_rotation, parameterization_upgrade, consent_withdrawal, identity_merge_recipe_5_1, name_change_recipe_5_7, re_identification_risk_model_update, plus an unknown-source fallback; the aggregate `pprl_linkage_invalidated` event is emitted for downstream consumers). The salt_rotation branch correctly enforces dual-control approval through `MockSaltCustody.rotate_salt`'s `if len(dual_control_approvers) < 2:` check, demonstrating the rejection path on insufficient approvers. The demo's invalidate-on-event records what would be re-evaluated rather than actually re-encoding and re-matching; the simplification is acknowledged in the comments. |

Intentional deviations clearly framed:

- The `clkhash` and `anonlink` toolkits become toy `_encode_per_feature_bloom_filter`, `_combine_per_feature_filters`, and `_sorensen_dice_coefficient` functions. Documented in the Heads-up section and in Gap to Production.
- Production-grade defensive measures (random hashing, balanced encoding, hardening) are not implemented; flags in the parameterization are present but unused. Documented in the Heads-up. **Finding 3 names the gap explicitly.**
- The HSM-backed salt custody becomes `MockSaltCustody` with in-memory plaintext salt. Documented inline ("a production deployment would never have plaintext salt visible to Python application code").
- The versioned configuration store becomes `MockProtocolParameterizationStore` with an in-memory dict. Documented inline.
- The institutional consent-management workflow becomes `MockConsentStore` with an in-memory dict and a simple `is_consent_active` policy engine. Documented inline.
- The institutional policy-overlay store becomes `MockJurisdictionalOverlays` with a single example post-Dobbs overlay. Documented inline.
- The Glue / Spark population-scale encoding becomes "the demo iterates in-process for a handful of records." Documented in Gap to Production.
- The Step Functions orchestration, multiple Lambdas, multiple Glue jobs, and SQS-driven worker pattern collapse into a single Python file. Documented at the top.
- The Nitro Enclave attestation flow is named in the trust-architecture branching but is a stub (no `verify_attestation` or `request_enclave_attestation` exists). Documented inline.
- The SMPC protocol runner is named in the trust-architecture branching but is a stub. Documented inline.
- The PrivateLink cross-account exchange becomes "all participants run in one process." Documented at the top.
- The DynamoDB read/write paths fall back to in-memory dicts (`_IN_MEMORY_CYCLE_METADATA`, `_IN_MEMORY_EXCHANGE_BUCKET`, `_IN_MEMORY_LINKAGE_RESULTS`, `_IN_MEMORY_PARTICIPANT_LOCAL_MAPPINGS`). Documented.

The substantive deviations (Findings 1, 2, 3) are the consistency gaps that carry pedagogical consequence, two of them (2 and 3) are NOTEs that the Heads-up section already partially acknowledges. The acknowledged simplifications (mock salt custody, mock config store, mock consent, mock overlays, in-memory tables) are clearly framed.

---

## AWS SDK Accuracy

| API Call | Method | Notes |
|----------|--------|-------|
| S3 PutObject | `s3_client.put_object(Bucket=..., Key=key, Body=body, ServerSideEncryption="aws:kms")` | Correct. Body is bytes-encoded JSON with `default=str` to handle Decimal. Keys use `{partition}/{date}/{key_id}.json` with no leading slashes. The audit-archive S3 writes for exchange events and disclosure events follow the same pattern. |
| EventBridge PutEvents | `eventbridge_client.put_events(Entries=[{Source, DetailType, EventBusName, Detail}])` | Correct shape. `Detail` is JSON-serialized with `default=str` to handle Decimal. Two detail-types: `pprl_linkage_cycle_completed` from `disclose_linkage_results` and `pprl_linkage_invalidated` from `invalidate_on_event`. |
| CloudWatch PutMetricData | `cloudwatch_client.put_metric_data(Namespace, MetricData=[{MetricName, Value, Unit, Dimensions}])` | Correct shape. Eight metric names appear: `StandardizeAndPrepare.Filtered`, `StandardizeAndPrepare.Prepared`, `EncodedRecords`, `ExchangeCompleted`, `MatchDecision`, `DisclosureCompleted`, `Invalidations`. **`Unit="Count"` is hardcoded per Finding 6, but is correct for all current emissions.** |
| KMS / DynamoDB / SQS | (referenced in setup; not actually called) | The Setup section names the IAM permissions on the four DynamoDB tables, the encoded-records buckets, the audit archive, and the SQS queues. The demo does not actually call these services; the in-memory replacements stand in. The boto3 client setup is correct (clients constructed at module level with adaptive retries). |

The SDK-level concerns are limited to Finding 6 (Unit hardcoded). All API surfaces named in the demo are current and correct.

---

## DynamoDB and Data Type Check

- `_to_decimal` correctly uses `Decimal(str(value))` and short-circuits on already-Decimal inputs.
- `_serialize_for_dynamodb` recursively walks dicts, lists, tuples, and sets, converts floats to Decimal, base64-encodes bytes/bytearrays. Booleans pass through (`isinstance(True, float)` is False). The pattern is safe.
- Threshold constants are constructed as Decimals (`Decimal("0.85")`, `Decimal("0.72")`, `Decimal("0.50")`) at module load time. The per-feature weights and DP epsilon/delta defaults are also Decimals.
- Match scores returned from `_combine_with_fellegi_sunter` are Decimals throughout. Comparison with the threshold constants is Decimal-vs-Decimal. No int/float coercion issues.
- The Sørensen-Dice computation in `_sorensen_dice_coefficient` returns Decimal via `Decimal("2") * Decimal(intersection) / Decimal(set_a + set_b)`. Correct.
- The CloudWatch `Value` parameter uses `float(...)` casts where needed. Correct (CloudWatch accepts native floats).
- The EventBridge `Detail` flows through `json.dumps(..., default=str)`, which handles Decimal serialization.
- The S3 archive flow through `json.dumps(payload, default=str)` similarly handles Decimals.
- The base64-encoding of bytes/bytearrays in `_serialize_for_dynamodb` is correct for transit through JSON-serializable surfaces (S3, EventBridge); DynamoDB's binary type would also accept the raw bytes, but the demo never actually writes to DynamoDB.

The Decimal discipline is correct. No type-handling bugs. Note that the demo never actually writes to DynamoDB (all persistence is in-memory), so the Decimal discipline is preserved as a teaching pattern rather than a runtime requirement.

---

## S3 and Credentials Check

- The example uses S3 only for archive writes (`AUDIT_ARCHIVE_BUCKET`, `DERIVED_SNAPSHOT_BUCKET`). No leading slash on any key. The `_archive_to_s3` helper formats keys as `f"{partition}/{today}/{kid}.json"` where `partition` is a non-slashed prefix.
- The deploy-time guardrail covers every resource-name constant via the `for _name, _value in [...]: assert _value` loop. **No constant can silently be empty.** Same discipline as recipes 5.4, 5.5, 5.6, 5.7.
- No hardcoded credentials. Module-level boto3 clients use the documented environment credential chain.
- The IAM permissions list in Setup matches the API surface used by the code (PutItem on the four DynamoDB tables, PutObject on the encoded-records and audit-archive S3 buckets, SendMessage on the four SQS queues, PutEvents on the pprl-events bus, PutMetricData for CloudWatch, KMS Decrypt and Sign on the per-cycle salt-key version, Glue StartJobRun, and the Nitro Enclaves operations for the TEE-based variant).
- The Setup section explicitly names that "tutorial-level permissions above are fine for learning and will fail any serious IAM review" with the right framing about per-cycle bound roles, time-bound salt-key access, and cross-account read-only matcher access through bucket policies.
- The PHI framing is clear: encoded data is NOT PHI by construction (the cryptographic transform is the privacy claim) but per-record consent posture, cohort-axis hashes, and source-record identifiers (locally retained at each participant) carry information that should not leak through logs.
- The Heads-up section names the synthetic-data discipline: "All patients, demographics, and consent records in this demo are fictional. The mock salt custody, protocol parameterization store, participant data sources, consent store, and jurisdictional overlays return hand-crafted data that exercises the encoding, matching, and disclosure paths; do not point this demo at a live data-sharing collaboration."
- The Gap to Production section names the trust-framework artifact and operational governance rhythm, the salt-management ceremony with HSM-backed custody and dual-control rotation, the threshold-calibration and approval governance, the re-identification-risk review on a periodic cadence, the three review queues with cohort-and-cycle-aware tooling, the patient-consent capture and withdrawal pathways, the information-blocking compliance posture, the cross-jurisdictional overlay automation, the KMS-encrypted-everything posture, the VPC + VPC endpoints + PrivateLink, the CloudTrail data events on every salt-related operation, the Lake Formation column-level access control on the analytics surface, the Step Functions orchestration with idempotency keys, and the compliance and operational ownership across participating organizations.

Pass.

---

## Comment Quality Assessment

Comments consistently explain the "why":

- The Heads-up at the top names every major production gap before the code starts (no real `clkhash` or `anonlink` integration, no real CLK encoding with production-grade defensive measures, no real Nitro Enclave attestation, no real cross-account exchange or PrivateLink, no real Glue/Spark population-scale encoding, no Step Functions orchestration, no SageMaker calibration loop, no commercial tokenization vendor integration, no SMPC protocol runner, no homomorphic encryption, no IAM/KMS/VPC/WAF/CloudTrail wiring).
- The "things worth knowing upfront" list correctly names the encoding-step-happens-before-any-exchange posture, the cryptographic-salt-as-protocol-root-of-trust framing, the matcher-operates-on-similarity-over-Bloom-filters constraint, the disclosure-form-constrains-what-the-consumer-learns commitment, the cohort-stratified-accuracy-monitoring-without-demographic-visibility constraint, the re-encoding-as-the-primary-mitigation posture, and the Decimal-at-the-DynamoDB-boundary discipline as the load-bearing structural commitments.
- The encoded-data-thresholds-calibrated-separately commitment is named in the threshold constants' inline comment ("Calibrated SEPARATELY from the conventional matcher's thresholds in recipe 5.1 / 5.5. The encoded-data scoring function is different (Sørensen-Dice over Bloom filters combined Fellegi-Sunter-style) and the absolute scale of similarity scores is different. Re-using the recipe 5.5 thresholds for PPRL produces silent linkage failures").
- The protocol parameterization's bit allocation is documented inline ("Each feature gets a share of the total filter. Names get more bits because they're the most discriminating feature; DOB and SSN-last-4 are tokenized (set-bit-exact) rather than n-gram-encoded so they don't need a wide allocation").
- The defensive-measures simplification is acknowledged inline ("Production CLK encoders apply random hashing (varies the hash-function-to-bit-position mapping per record), balanced encoding (ensures each filter has a similar number of set bits to defeat frequency analysis), and hardening (deliberate noise injection that defeats specific known attacks). The demo's defensive measures are deliberately simple; production uses clkhash which implements current-best-practice variants"). **However per Finding 3, the parameterization-flags themselves are read but never honored.**
- The async-decomposition deferral is acknowledged at the top: "The example collapses Step Functions, multiple Glue jobs, multiple Lambdas, the Nitro Enclave matcher path, the cross-account exchange, and the SQS-driven worker pattern into a single Python file for readability."
- The mock-as-stand-in framing is clear in `MockSaltCustody`, `MockProtocolParameterizationStore`, `MockConsentStore`, and `MockJurisdictionalOverlays` with explicit production-extension notes ("a production deployment would never have plaintext salt visible to Python application code"; "Real deployments encode state law, institutional policy, and trust-framework constraints with attorney-reviewed rules").
- The synthetic-data labeling is unambiguous in the demo runner.
- The salt-rotation dual-control-approval requirement is named in the `MockSaltCustody.rotate_salt` comment ("Production requires dual-control approval (two HSM operators from non-overlapping organizations); rotation is audit-logged with both operator identities") and demonstrated in the Phase 2 invalidation triggers.
- The parameterization-and-salt-key-version-pinning silent-failure-prevention is named in the `exchange_encoded_records` validation comment ("Mis-coordinated versions are the most common operational failure mode for PPRL; catch them at exchange time before the matcher silently returns zero matches").
- The cohort-axis-hash-without-demographic-visibility commitment is named in `_compute_cohort_axis_hashes` ("Each participant computes its own cohort-axis values locally and contributes the hashes (not the values) in the encoded payload. The matcher receives the hashes and can stratify accuracy metrics by hash without learning the underlying axis values").
- The disclosure-form-constrains-privacy-properties commitment is named in the disclosure-form set definition ("Each form has its own privacy properties. The protocol's trust framework specifies which form(s) a particular linkage is authorized to produce").
- The consent-withdrawal-is-forward-only commitment is named in the `MockConsentStore.withdraw_consent` comment ("Forward-only: future cycles exclude the record; prior cycles' results remain in the consumer's possession") and again in the invalidation pipeline's consent_withdrawal branch.
- The trust-framework-as-the-load-bearing-artifact commitment is named in the Gap to Production section ("It is a contract that enumerates the participants, the protocol parameterization, the salt-management ceremony, the linkage-result-disclosure policy, the audit posture, the re-identification-risk model, the dispute-resolution mechanism, the consent-and-purpose-of-use governance, the cross-jurisdictional overlay handling, and the operational rhythms").

The Gap to Production section is unusually thorough (15+ items spanning real `clkhash` and `anonlink` integration, real Splink-or-`recordlinkage` and `jellyfish` for the calibration path, HSM-backed salt custody with dual-control rotation ceremony, real DynamoDB schema with the four primary tables, TransactWriteItems for atomic cycle-completion writes, real cross-account S3 buckets with PrivateLink for the encoded-data exchange, Nitro Enclaves for the TEE-based variant, real EventBridge bus with cross-recipe consumer subscriptions, Step Functions orchestration for the full cycle, Glue and Spark for the population-scale encoding and matching, idempotency keys on every write, threshold calibration and approval governance, cohort-stratified accuracy monitoring with disparity alarms, re-identification-risk review on a periodic cadence, three review queues with cohort-and-cycle-aware tooling, patient-consent capture and withdrawal pathways, information-blocking compliance posture, cross-jurisdictional overlay automation, KMS-encrypted everything, VPC + VPC endpoints + PrivateLink, CloudTrail data events on every salt-related operation, Lake Formation column-level and row-level access control on the analytics surface, trust-framework artifact and operational governance rhythm, compliance and operational ownership). The breadth honestly tells the reader how much operational discipline sits between the recipe and a production deployment.

The comments that would benefit from updates per the findings:

- `_compute_per_feature_similarities` would benefit from either implementing the comment's intent (test by `_count_set_bits` rather than `len`) or dropping the dead branches per Finding 1.
- `encode_record`'s envelope construction would benefit from either using `clk_payload` in the matcher path or removing it from the envelope per Finding 2.
- `_encode_per_feature_bloom_filter` would benefit from either implementing the defensive-measures stubs or dropping the flags from the parameterization per Finding 3.
- `encoded_record_id` construction would benefit from either dropping the participant prefix or using a participant-disambiguating substring per Finding 4.
- `_build_intersection_count` would benefit from either computing true min/max bounds or renaming the fields to remove the bounds framing per Finding 5.
- `_emit_metric` would benefit from an optional `unit` parameter per Finding 6.

Calibration is otherwise appropriate for a mixed audience.

---

## Healthcare-Specific Requirements

- **PHI discipline.** The Heads-up section frames the encoded data's PHI status correctly: "Encoded records are not PHI by themselves (the cryptographic transform is the privacy claim), but the per-record consent posture, the cohort-axis hashes, and the source-record identifiers (retained locally at each participant) all carry information that should not leak through logs." The logger setup correctly limits logging to structural metadata (cycle_id, encoded_record_id, parameterization_version, salt_key_version, decision band) and explicitly excludes CLK payloads, raw demographics, and source-record identifiers from cross-participant context.
- **Synthetic data labeling.** Sample patient IDs (`academic-mc-mrn-00284271`, etc.), member IDs (`MEM-100874-A`), DOBs, SSN-last-4 values, addresses, and phone numbers are obviously synthetic. The Heads-up section warns explicitly. The `MockSaltCustody`, `MockProtocolParameterizationStore`, `MockConsentStore`, and `MockJurisdictionalOverlays` use the same synthetic inputs.
- **Decimal at the DynamoDB boundary.** Consistent. Defensive float-to-Decimal coercion in `_serialize_for_dynamodb` and at the score-construction boundary throughout the matcher. Note that the demo never actually writes to DynamoDB; the discipline is preserved as a teaching pattern.
- **S3 paths.** No leading slashes on any S3 key. The `_archive_to_s3` helper formats keys as `f"{partition}/{today}/{kid}.json"`.
- **Audit-archive every operation.** `_archive_to_s3` is called at exchange time (per-participant exchange events) and at disclosure time (per-disclosure events). The audit log captures the disclosure-form, the target-consumer, the per-record count, and the cohort-stratified-accuracy summary, but does NOT log the actual disclosure payload (which would duplicate the consumer's copy).
- **Provenance on every record.** Encoded-record envelopes carry `parameterization_version`, `salt_key_version`, `cycle_id`, `encoded_at`. Match results carry the same plus `feature_weights_version`. A future audit can attribute a linkage decision to the matcher version, the parameterization version, and the salt-key version active at decision time.
- **Append-only audit.** The audit-archive S3 writes are append-only by design (each event gets a unique S3 key under the `{partition}/{date}/{key_id}.json` pattern). Production extends with Object Lock in Compliance mode for immutability; the demo's append-only intent is correct.
- **Cohort-stratified telemetry.** `MatchDecision` emits with `Decision`, `CohortBucketHash` (truncated to 8 chars), and `CycleId` dimensions. The `CohortBucketHash` dimension is what makes per-cohort linkage-rate disparity monitoring possible without the matcher learning the underlying axis values.
- **Conservative thresholds.** ENCODED_MATCH_HIGH=0.85, MED=0.72, REJECT=0.50. The recipe text frames PPRL thresholds as "calibrated separately from the conventional thresholds because the underlying scoring function is different"; the Python's threshold values reflect the encoded-data-scoring framing.
- **Salt rotation with dual-control approval.** `MockSaltCustody.rotate_salt` enforces `if len(dual_control_approvers) < 2: raise ValueError(...)`. The Phase 2 invalidation triggers demonstrate both the success path (two approvers from non-overlapping organizations) and the rejection path (only one approver). This is a healthcare-specific operational discipline the recipe spends thousands of words on, and the demo demonstrates it cleanly.
- **Consent-and-purpose-of-use filtering.** The standardize-and-prepare step filters records whose consent posture does not permit inclusion for the specified purpose; the disclose step also filters by consent (defense-in-depth). Patricia Murphy's consent-withdrawn record demonstrates the standardize-time filter (she does not appear in the encoded set).
- **Cross-jurisdictional overlay metadata.** The `MockJurisdictionalOverlays` carries the post-Dobbs reproductive-health-care state-law overlay; the encoded-record envelope captures `applicable_overlays`. The matcher doesn't act on the overlay (the demo's overlay logic is "audit_every_disclosure" / "audit_every_query" flags), but the metadata flow through encoding, matching, and disclosure is preserved.
- **Information-blocking awareness.** The Gap to Production section names the 21st Century Cures Act information-blocking obligation as load-bearing for the patient-access release path. The demo doesn't include the patient-access release path explicitly; it is acknowledged as deferred to production.
- **Re-encoding-as-primary-mitigation posture.** The invalidation pipeline includes salt_rotation, parameterization_upgrade, and re_identification_risk_model_update branches that all schedule `coordinated_re_encoding`. The demo records the actions rather than re-running the encoding (acknowledged simplification).
- **Cross-recipe coordination.** The invalidation pipeline includes `identity_merge_recipe_5_1` and `name_change_recipe_5_7` branches, demonstrating the upstream-event consumption pattern. Recipe 5.1 merging two identities or recipe 5.7 resolving a name change invalidates the encoded records under the prior identity state; the demo's queue records the affected records for re-encoding in the next cycle.

Pass on the structural healthcare requirements (PHI handling, synthetic-data labeling, Decimal discipline at DynamoDB boundary intent, S3 path discipline, audit archive append-only intent, provenance on every record, cohort-stratified telemetry, conservative threshold posture, salt-rotation dual-control approval, consent-and-purpose-of-use filtering, cross-jurisdictional overlay metadata, information-blocking awareness in Gap to Production, re-encoding-as-primary-mitigation posture, cross-recipe coordination).

---

## Logical Flow

The file reads top-to-bottom in pedagogical order matching the pseudocode numbering: Setup, Configuration and Constants (logger, retry config, module-level clients, resource names with deploy-time guardrail, versioning, protocol parameterization with per-feature bit allocation, encoded-data thresholds, per-feature weights, disclosure forms, default k-anonymity and DP parameters, cohort axes), Helpers (Decimal coercion, name canonicalization, n-gram tokenization, bit-array primitives, Sørensen-Dice computation, S3 archive, CloudWatch metrics), Mock Salt Custody / Protocol Parameterization Store / Participant Data Sources / Consent Store / Jurisdictional Overlays, Step 1 (standardize and prepare with consent filter and cohort-axis hashing), Step 2 (apply cryptographic encoding under pinned parameterization), Step 3 (exchange encoded records with parameterization-version validation), Step 4 (match encoded records with Sørensen-Dice and Fellegi-Sunter), Step 5 (apply disclosure policy and route in protocol-authorized form), Step 6 (react to invalidation events), Full Pipeline (`run_cycle` plus three representative cycles plus six invalidation triggers), Gap to Production.

Each step opens with a short italic prose paragraph that restates the pseudocode step before the code block, matching the cookbook's established pattern. The italic paragraphs name the step's role and the failure mode the step prevents.

The demo runner builds two phases. Phase 1 runs three representative linkage cycles: Cycle 1 (research linkage with per_record_match_flags disclosure to participant A), Cycle 2 (public-health surveillance with intersection_count to a state public-health department), and Cycle 3 (ACO out-of-network analytics with k_anonymous_aggregate to an ACO analytics team). Phase 2 exercises six invalidation triggers (salt_rotation with dual-control success, salt_rotation rejection on insufficient approvers, parameterization_upgrade, consent_withdrawal, identity_merge_recipe_5_1, name_change_recipe_5_7). The trigger choice exercises the three implemented disclosure forms, the dual-control salt-rotation pattern, and four of the six invalidation source types.

The closing prose paragraph after the expected output walks each cycle's behavior with explicit references to the matcher's score-band routing (3 MATCH_HIGH for Catherine/Maria/Margaret, 13 MATCH_MED_REVIEW from the cross-product non-matches), the cohort-axis-hash flow through the disclosure step, the consent-filter behavior at standardize time (Patricia dropped before encoding), the dual-control salt-rotation pattern, the parameterization-upgrade publishing a new version, and the cross-recipe invalidation coordination. The narrative connects the synthetic data to the printed output to the architectural intent.

---

## What Is Done Particularly Well

Worth calling out explicitly:

- **The deploy-time guardrail covers every resource-name constant.** The for-loop pattern that asserts every constant is non-empty is consistent with recipes 5.4-5.7. A misconfigured constant produces a clean assertion message rather than a downstream `ValidationException` from boto3 or DynamoDB.
- **The encoding-before-any-exchange posture is implemented faithfully.** The standardize, encode, and exchange steps run in sequence with the encoded-record envelope as the boundary; the matcher operates on the encoded representations only.
- **The parameterization-version-and-salt-key-version pinning is implemented as a hard validation at exchange time.** The `ParameterizationMismatchError` and `SaltKeyMismatchError` paths catch the silent-failure mode the recipe spends prose on. The errors carry actionable messages ("This is the silent-failure mode the version-pinning is designed to catch; do not proceed"; "The cycle's salt-key version may have rotated mid-cycle; re-encode under the active salt and re-run the cycle") that a reader would actually find useful in production.
- **The dual-control salt-rotation ceremony is enforced and demonstrated.** The `MockSaltCustody.rotate_salt` rejects single-approver rotations with a clear error; the Phase 2 invalidation triggers demonstrate both the success and the rejection paths. The recipe text spends substantial prose on dual-control as load-bearing operational discipline; the demo demonstrates it.
- **The cohort-axis-hash-without-demographic-visibility constraint is implemented faithfully.** Each participant computes its own cohort-axis values locally and contributes the hashes; the matcher receives the hashes and stratifies metrics by them. The `CohortBucketHash` dimension on `MatchDecision` makes per-cohort disparity monitoring possible. Same chapter pattern as recipes 5.5-5.7's cohort-bucket-hash discipline, with the recipe-specific matcher-cannot-see-the-axis-values constraint.
- **The disclosure-form-as-privacy-property posture is structurally correct.** The disclosure step has explicit branches for per_record_match_flags, intersection_count, and k_anonymous_aggregate, with differentially_private_aggregate and encrypted_match_indicator falling to a "not implemented in demo" else branch. The framing that "the protocol's trust framework specifies which form(s) a particular linkage is authorized to produce" is preserved through the per-cycle disclosure_form parameter.
- **The consent-and-purpose-of-use filter at standardize time is the primary enforcement point** with a defense-in-depth filter at disclosure time. Patricia Murphy's consent-withdrawn record demonstrates the standardize-time filter (she does not appear in the encoded set; the matcher never sees her).
- **The CLK Bloom-filter encoding is correctly implemented at the level the demo claims.** Bigram tokenization with start-and-end markers, k=30 hash functions per bigram, salted HMAC-SHA-256 for the per-bigram hashing, modulo into the per-feature bit array. The construction matches the recipe text's "Walk through the Bloom-filter-based encoding" section.
- **The Sørensen-Dice computation is correct.** `2 * |A AND B| / (|A| + |B|)` over bytearrays. Both filters are validated to have the same length before the AND-and-count operation; the mismatch raises `ValueError("Bloom filter size mismatch (parameterization mis-coordination)")` with a clear message.
- **The Fellegi-Sunter combiner is honestly framed as a simpler weighted-average** with the production extension explicitly named ("The production Fellegi-Sunter implementation uses log-likelihood ratios with EM-trained per-feature m-and-u parameters; the demo uses a simpler weighted-average that illustrates the structure without the parameter-estimation complexity").
- **The synthetic data covers the major matching scenarios.** Catherine (exact match including middle name), Maria (matching primary features but missing middle name), Margaret (matching primary features with phone-number variation testing the encoding's robustness to legitimate noise), Theodore (participant-A-only, no match), Patricia (consent withdrawn, filtered at standardize time), Robert (participant-B-only, no match). A learner sees the major paths exercised in a single demo run.
- **The dual-control salt-rotation rejection path** is explicitly demonstrated in Phase 2 — the second salt_rotation invalidation event provides only one approver and the demo shows the rejection. This is unusual for a teaching snippet and pedagogically valuable.
- **The encoded-record envelope's local-mapping store** (`_IN_MEMORY_PARTICIPANT_LOCAL_MAPPINGS`) demonstrates the "the source_record_id is retained locally at each participant; it is never included in the encoded-record envelope or the cross-participant exchange" architectural commitment. The mapping enables the participant to later resolve match results back to the source records under its own access controls without exposing the mapping cross-participant.
- **The Phase 1 / Phase 2 demo structure is pedagogically strong.** Phase 1 walks the three implemented disclosure forms; Phase 2 exercises the salt-rotation, parameterization-upgrade, consent-withdrawal, and cross-recipe invalidation paths. A learner who runs the demo sees the full lifecycle exercised in a single run.
- **The closing prose accurately describes what each cycle and trigger demonstrates**, with explicit acknowledgment of the threshold-band-behavior caveat ("Production CLK encoders with `clkhash` and proper defensive measures (random hashing, balanced encoding, hardening) produce a much sharper match-vs-non-match separation; calibration against a real pilot population sets the REJECT threshold high enough that unrelated pairs are correctly rejected. The demo's behavior is itself a useful teaching point: PPRL thresholds are not the same as plaintext-matching thresholds, and the calibration discipline is non-optional"). This honest acknowledgment of the toy-implementation's limitations is exactly the right framing for a teaching snippet.
- **The Gap to Production section is unusually thorough.** Real `clkhash` and `anonlink` integration, real Splink-or-`recordlinkage` and `jellyfish` for the calibration path, HSM-backed salt custody with dual-control rotation ceremony, real DynamoDB schema, TransactWriteItems for atomic cycle-completion, real cross-account S3 buckets with PrivateLink, Nitro Enclaves for the TEE-based variant, real EventBridge bus, Step Functions orchestration, Glue and Spark for population-scale encoding, idempotency keys, threshold calibration governance, cohort-stratified disparity alarms, re-identification-risk review cadence, three review queues, patient-consent capture, information-blocking compliance, cross-jurisdictional overlay automation, KMS-encrypted everything, VPC + PrivateLink, CloudTrail data events, Lake Formation, trust-framework artifact, compliance and operational ownership across participating organizations. The breadth honestly tells the reader how much operational discipline sits between the recipe and a production deployment.

---

## Closing Assessment

The teaching content is well-organized and faithful to the main recipe in structure, prose framing, and pedagogical ordering. The six pseudocode steps map onto Python functions with helpers in the right places. The S3 + EventBridge + CloudWatch API call shapes are correct (DynamoDB and SQS are referenced in setup but not actually called; the demo's persistence is in-memory). The Decimal-at-the-DynamoDB-boundary discipline is consistent. The encoding-before-any-exchange posture, the parameterization-version-and-salt-key-version pinning, the dual-control salt-rotation ceremony, the cohort-axis-hash-without-demographic-visibility constraint, the disclosure-form-as-privacy-property posture, the consent-and-purpose-of-use filter at standardize time, the CLK Bloom-filter encoding construction, and the six-source invalidation pipeline are all structurally correct. The `MockSaltCustody`, `MockProtocolParameterizationStore`, `MockConsentStore`, and `MockJurisdictionalOverlays` replacements are reasonable approximations that exercise the major paths.

The WARNING is localized and pedagogically meaningful. Finding 1 (the missing-feature handling in `_compute_per_feature_similarities` is dead code with misleading comments — the `len(filter_a) == 0` branches never fire because the encoder always returns a non-zero-size bytearray for any feature in the parameterization, and the actual missing-both and one-missing behavior both fall through to Sørensen-Dice's `set_a + set_b == 0` branch which returns 0) does not flip any threshold-band routing in the demo because Maria's middle_name=None case still lands well above the 0.85 MATCH_HIGH threshold even with the 0.04 composite reduction. But the comment describes a three-case decision tree that the implementation does not deliver, and a reader extending the matcher with more sophisticated missing-feature handling carries the dead-check pattern forward.

The five NOTEs are smaller items: the `clk_payload` is computed but never read by the matcher (Finding 2); the `defensive_measures` configuration flags are present in the parameterization but `_encode_per_feature_bloom_filter` does not check them, so toggling the flags in the parameterization-upgrade event has no effect (Finding 3); the `encoded_record_id` prefix uses `participant_id[:1]` which produces "p" for both participants (Finding 4); the `_build_intersection_count`'s `match_rate_lower_bound` and `match_rate_upper_bound` have no guaranteed ordering relative to each other (Finding 5); the `_emit_metric` helper hardcodes `Unit="Count"` which is correct for current emissions but constrains future score-emit additions (Finding 6).

PASS verdict per the persona's rule: no ERRORs, one WARNING (under the FAIL threshold of more than three). The WARNING and the most-load-bearing NOTEs (Findings 2 and 3) should be addressed before the recipe ships, because they teach a missing-feature handling pattern whose comments do not match the code's behavior, a CLK-payload field that is computed but never consumed, and a defensive-measures configuration that has no effect on encoding. None of these block the demo from running to completion.

Recipe 5.8 is the eighth recipe in Chapter 5 and inherits the chapter's operational discipline (graded confidence with deferred review, audit-everything substrate, drift-event fan-out, cohort-stratified telemetry, transactional-outbox eventing, conservative threshold posture, append-only persistence intent) from recipes 5.1-5.7. The PPRL-specific behaviors that differentiate it (CLK Bloom-filter encoding before exchange, parameterization-version-pinning to prevent silent linkage failures, salt-rotation with dual-control approval ceremony, multi-form disclosure policy with per-cohort-axis-hash derivation that lets the matcher stratify accuracy without learning the underlying axis values, six-source invalidation pipeline including salt-rotation and parameterization-upgrade events, trust-framework-as-load-bearing-artifact framing) are all structurally present. Closing the WARNING brings the example up to the standard the recipe text claims and is appropriate given that this recipe is the substrate for several of the chapter's later recipes.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** `_compute_per_feature_similarities` either tests for the encoder's all-zero-filter sentinel via `_count_set_bits(filter_a) == 0` (matching the comment's intent) or drops the dead branches and acknowledges the simplification inline. After the fix, hand-trace Maria's middle_name comparison: if Option A (preserve intent), both filters have set_count == 0, the first branch fires, similarity = Decimal("0.5"), Maria's composite climbs from ~0.92 to ~0.96. If Option B (drop branches), similarity = 0 (Sørensen-Dice on two zero-set filters), Maria's composite stays at ~0.92. Either way, Maria still lands MATCH_HIGH; the consent_dropped count and the 13 review pairs are unchanged.
2. **(NOTE)** Either the matcher reads `clk_payload` (extracting per-feature slices via the same cursor logic as `_combine_per_feature_filters`) or the `clk_payload` field is dropped from the encoded-record envelope with an inline comment explaining the demo's per-feature-filter approach. The current state (computed but unread) is dead data.
3. **(NOTE)** The defensive-measures application path either implements stub functions for `_apply_random_hashing_stub`, `_apply_balanced_encoding_stub`, `_apply_hardening_stub` that the encoder calls based on the parameterization flags (preserving the configuration-toggle pattern), or the flags are dropped from the parameterization (acknowledging that the demo omits them). The current state (flags read but not honored) is misleading.
4. **(NOTE)** The `encoded_record_id` prefix either drops the participant substring entirely or uses a participant-disambiguating substring (e.g., `participant_id[-1].lower()`). The documented expected console output is updated to match whichever choice the recipe makes.
5. **(NOTE)** `_build_intersection_count` either computes true min/max bounds with `min(a_rate, b_rate)` and `max(a_rate, b_rate)`, or renames the fields to `intersection_rate_for_a` and `intersection_rate_for_b` to remove the bounds framing. The recipe's "Sample disclosure envelope (intersection-count form)" JSON is updated to match.
6. **(NOTE)** `_emit_metric` accepts an optional `unit` parameter with a `Count` default. Future score-emit additions can pass `unit="None"` for 0-1 confidence values.

After the WARNING fix, re-run the demo end-to-end and confirm:
- Cycle 1: unchanged (`match_high pairs: 3`, `review pairs: 13`, sample MATCH_HIGH still shows `match_score: 1.000` for Catherine, all per-feature similarities at 1.000).
- Cycle 2: unchanged (intersection_count: 3, match_rate_lower_bound: 0.750, match_rate_upper_bound: 0.750).
- Cycle 3: unchanged (all cohort cells suppressed under the 5-record threshold).
- Phase 2 invalidation triggers: unchanged (salt_rotation succeeds with two approvers, fails with one approver, parameterization_upgrade publishes new version, consent_withdrawal marks the source record as withdrawn, identity_merge_recipe_5_1 queues records for re-encoding, name_change_recipe_5_7 queues record for re-encoding).

The other findings are low-risk cleanups that improve pedagogical clarity, align the code with the comments and the pseudocode's stated behavior, and reduce the chance that a reader copies a misleading pattern into production. None of them block the demo from running to completion under the demo-mode-tables-not-provisioned path.
