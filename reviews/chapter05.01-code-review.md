# Code Review: Recipe 5.1 - Internal Duplicate Patient Detection

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-22
**Files reviewed:**
- `chapter05.01-internal-duplicate-patient-detection.md` (main recipe pseudocode)
- `chapter05.01-python-example.md` (Python companion)

**Validation performed:**
- Walked the five pseudocode steps against the Python functions one-to-one
- Verified boto3 API call shapes for DynamoDB resource (`get_item`, `put_item`, `update_item`, `query`), S3 (`put_object`), EventBridge (`put_events`), CloudWatch (`put_metric_data`)
- Verified `boto3.dynamodb.conditions.Key` usage in the GSI query
- Traced numeric values flowing into DynamoDB through `_to_decimal` and `_serialize_for_dynamodb`
- Verified `jellyfish` library function names against the published jellyfish API reference (jaro_winkler_similarity, damerau_levenshtein_distance, metaphone)
- Hand-computed the Fellegi-Sunter composite scores for the demo's three duplicate-pair cases against the file's M/U probability tables to check the "expected output" block
- Walked the five-step pipeline end-to-end against the seven-record synthetic roster
- Verified Decimal-at-the-DynamoDB-boundary discipline, S3 key formation (no leading slashes), and PHI handling in audit-archive writes

---

## Summary

The Python companion is structurally faithful to the main recipe's five pseudocode steps and the architectural picture (normalize, multi-pass blocking, per-field comparators feeding a Fellegi-Sunter combiner, three-way threshold routing, merge with survivorship and audit). The Decimal-at-the-DynamoDB-boundary discipline is consistent with bool guards via `_serialize_for_dynamodb`, S3 keys do not carry leading slashes, the routing thresholds are exposed as configuration, the per-field comparators handle the common entry-error patterns the recipe enumerates (month-day swap, one-digit-off, hyphenated-partial last names, nickname expansion via the small dictionary), and the merge function correctly handles the three identity-cluster cases (idempotent re-confirmation, cluster merge with both clusters present, fresh assignment when neither side has an mpi_id). The audit-archive pattern (per-decision JSON in S3, partitioned by routing decision and date) is the right shape for forensic-grade traceability.

That said, two WARNINGs need attention before this goes to readers, plus eight NOTEs. The first WARNING is that the file claims to use double metaphone in three places (the `_double_metaphone` function name, the function docstring, and the Setup section's claim that "`jellyfish` provides the Jaro-Winkler, Damerau-Levenshtein, and double-metaphone implementations") but `jellyfish.metaphone` is regular metaphone, not double metaphone. The published jellyfish API has soundex, metaphone, NYSIIS, and match-rating-codex but not double metaphone; the recipe's prose repeatedly emphasizes double metaphone as the modern, more accurate phonetic encoder. A reader copying the example into production would carry forward an incorrect understanding of what algorithm the code uses. The second WARNING is that the demo's "Expected console output" block shows composite scores (14.21, 11.04, 15.83) that are roughly a third of what the file's actual M_PROBABILITIES and U_PROBABILITIES tables produce when the comparators run. Hand-computing the score for the MRN-009315 vs MRN-014203 pair (both "maria garcia" with identical normalized addresses, phones, emails, and DOB) sums to roughly 42.8 against the published m/u table, not 14.21. The disclaimer says "scores will vary slightly with the m/u probability values," but a 3x mismatch is not slight; a learner running the demo and seeing 42 where the docs say 14 will lose confidence in the example.

The eight NOTEs cover smaller items: the synthesized "secondary" metaphone code that is computed and stored on the normalized record but never read by any comparator (dead attribute), `_query_cluster_members` not paginating the GSI query, `apply_merge`'s `put_item` to `mpi-master` not being wrapped in try/except so a failure aborts before the dependent xref updates run, the demo's print-vs-reality mismatch when the underlying tables don't exist (chapter pattern from 4.6/4.7/4.8/4.9/4.10), the `_compare_address` returning a `same_zip` level where the recipe's pseudocode and the sample candidate-pair JSON both name the level `same_zip_different_street` (pseudocode-to-Python consistency), `_log_likelihood_ratio`'s docstring promising a `log((1-m)/(1-u))` fallback that is never implemented, `_compare_dob`'s redundant double-check on the quality flags (the first conditional is dead), and `unmerge` raising `NotImplementedError` despite the recipe text emphasizing reversibility as non-negotiable.

---

## Verdict: PASS

No ERRORs. Two WARNINGs (under the FAIL threshold of more than three). Eight NOTEs.

The two WARNINGs and several NOTEs should be addressed before the recipe ships, because they teach incorrect terminology (double metaphone) and produce expected outputs a learner cannot reproduce. Neither blocks the demo from running to completion. Recipe 5.1 is the foundation recipe for the entire chapter (the recipe text says: "If you read only one recipe in Chapter 5, read this one") so getting the canonical phonetic-algorithm name right and producing reproducible expected output is worth the small fix cost.

---

## Findings

### Finding 1: `jellyfish.metaphone` Is Not Double Metaphone; Function Name, Docstring, and Setup Prose All Mislabel the Algorithm

- **Severity:** WARNING
- **File:** `chapter05.01-python-example.md`
- **Locations:** the `_double_metaphone` helper, the Setup section's "`jellyfish` provides..." sentence, the inline comment in `normalize_record` about computing double-metaphone codes
- **Description:**

  The Python helper is named `_double_metaphone`, has a docstring that says "Return the (primary, secondary) double-metaphone codes for the string," and is presented as the file's phonetic-encoder primitive. The body calls `jellyfish.metaphone(s)`:

  ```python
  def _double_metaphone(s: str) -> tuple:
      """
      Return the (primary, secondary) double-metaphone codes for the
      string. ...
      """
      if not s:
          return ("", "")
      primary, secondary = jellyfish.metaphone(s), None
      ...
  ```

  Per the [published jellyfish API reference](https://jamesturk.github.io/jellyfish/functions/), the library's phonetic-encoding functions are American Soundex, Metaphone, NYSIIS, and Match Rating Approach codex. There is no `double_metaphone` function in jellyfish. `jellyfish.metaphone(s)` is the original Lawrence Philips 1990 metaphone algorithm; double metaphone is the 2000 successor algorithm with substantially different output (it returns a `(primary, secondary)` tuple where the secondary captures alternative pronunciations for words of foreign origin, which is the whole point of the "double" in the name). The two algorithms are not interchangeable; for the recipe's most-cited example, the original metaphone codes "Catherine" as "K0RN" and "Katherine" as "K0RN" (same code, the comment is correct), but for words like "Pawel" / "Pavel" the original metaphone produces different codes while double metaphone produces a shared secondary code.

  Three places in the file claim double metaphone:

  1. The function name `_double_metaphone`.
  2. The function docstring (quoted above).
  3. The Setup section's introductory sentence: *"`jellyfish` provides the Jaro-Winkler, Damerau-Levenshtein, and double-metaphone implementations used in the comparators."*

  The recipe's main text reinforces the framing: in The Technology section under String Similarity, *"Double metaphone is the more modern, more accurate one,"* and the architecture diagram's normalization stage explicitly calls for *"Phonetic encoding (double metaphone) for names; precompute for use as blocking keys."* So the recipe text, the function name, the docstring, and the Setup prose all promise double metaphone; the implementation delivers original metaphone.

  Three consequences:

  1. **The implementation is misnamed.** `jellyfish.metaphone` is not double metaphone. A reader who later wants to swap to a real double-metaphone implementation (the `metaphone` PyPI package, the `phonetics` package, the `dedupeio/doublemetaphone` C++ wrapper, or the `splink` library's built-in version) is set up to expect a drop-in replacement, but the call signature and return value are different (real double metaphone returns a 2-tuple of strings; jellyfish.metaphone returns a single string).
  2. **The synthesized "secondary" code is not what double metaphone produces.** The function tries to compensate for the missing secondary by re-running metaphone on the first space-separated token of the input (`jellyfish.metaphone(first_token)`). For a single-token input like "Smith" or "Garcia," this produces the same code as the primary (`first_token == s`, so the assignment to `secondary` is short-circuited), and the secondary stays None. For a multi-token input like "Garcia Lopez," the secondary is metaphone("Garcia") which is a different code than metaphone("Garcia Lopez"). Neither behavior matches what real double metaphone would produce.
  3. **The blocking and comparator quality is degraded for the cases double metaphone was designed for.** The recipe text frames the choice deliberately: *"Double metaphone is the more modern, more accurate one. Phonetic encoders are how you catch 'Catherine' matching 'Katherine' and 'Smith' matching 'Smyth.'"* For the simple cases (Catherine/Katherine, Smith/Smyth), original metaphone happens to produce the same code, so the demo works. For names from naming conventions outside the dominant culture (which the recipe text explicitly flags as an equity concern: *"Names from naming conventions outside the dominant culture (Hispanic surnames with multiple components, Asian names with order variations, Arabic names with transliteration variations) match worse on average"*), double metaphone's secondary-code feature provides materially better recall. The demo claims to be doing this; it isn't.

- **Suggested fix:** Two reasonable options:

  1. **Use a real double-metaphone library** and update the function. The `metaphone` PyPI package (also known as `Metaphone` on PyPI) provides `doublemetaphone(s) -> (primary, secondary)`. Update Setup to add `metaphone` to the pip install line and import:

     ```python
     from metaphone import doublemetaphone
     ```

     Then:

     ```python
     def _double_metaphone(s: str) -> tuple:
         """Return the (primary, secondary) double-metaphone codes."""
         if not s:
             return ("", "")
         primary, secondary = doublemetaphone(s)
         return (primary or "", secondary or "")
     ```

     This honors the recipe text's claim and gives the demo the recall benefit double metaphone is meant to provide. Splink, the library the recipe text recommends for production, also uses double metaphone; this keeps the example aligned with the production guidance.

  2. **Honestly rename to metaphone and update the prose.** Rename the helper to `_metaphone`, fix the docstring to "Return the metaphone code for the string," update the Setup sentence to *"`jellyfish` provides the Jaro-Winkler, Damerau-Levenshtein, and metaphone implementations used in the comparators,"* and update the recipe text's pseudocode and architecture diagram to say `metaphone(...)` instead of `double_metaphone(...)`. Add a `# TODO` block in the function naming the choice and pointing to double metaphone as a production upgrade with the equity rationale.

  Option 1 is the better fix because it aligns the implementation with the recipe text and gives the demo the recall benefit on the equity-relevant cases. Option 2 is the lower-effort fix that closes the inconsistency without adding a dependency. Either way, all three places that claim double metaphone need to land on the same algorithm.

---

### Finding 2: Demo's "Expected Console Output" Composite Scores Are Roughly One-Third of What the Code Actually Produces Against the Published m/u Tables

- **Severity:** WARNING
- **File:** `chapter05.01-python-example.md`
- **Locations:** the "Expected console output" block at the end of the Full Pipeline section
- **Description:**

  The demo block at the end of the Python companion shows expected scores and routing decisions:

  ```
  Auto-matched pairs (3):
    MRN-009315 <-> MRN-014203  score=14.21
    MRN-009315 <-> MRN-018747  score=11.04
    MRN-031876 <-> MRN-040912  score=15.83
  Review-queued pairs (1):
    MRN-009315 <-> MRN-022104  score=2.65
  Auto-non-match pair count: 2
  ```

  The disclaimer above the block says *"Expected console output (scores will vary slightly with the m/u probability values)."* "Slightly" is doing too much work.

  Hand-computing for the MRN-009315 vs MRN-014203 pair (both records normalize to "maria garcia" with identical DOB 1972-03-14, identical normalized address "1421 ELM ST APT 4, ANYTOWN ST 12345", identical phone "5551234567", identical email "mgarcia@example.com", and both with null SSN) against the file's `M_PROBABILITIES` and `U_PROBABILITIES` tables:

  | Field | Comparison | log(m/u) |
  |-------|-----------|----------|
  | first_name | exact | log(0.85/0.005) = 5.135 |
  | last_name | exact | log(0.78/0.002) = 5.966 |
  | dob | exact | log(0.92/0.0001) = 9.127 |
  | sex | exact | log(0.97/0.5) = 0.663 |
  | address | exact | log(0.55/0.001) = 6.310 |
  | phone | exact | log(0.50/0.0005) = 6.908 |
  | ssn | one_null | 0 |
  | email | exact | log(0.30/0.00005) = 8.700 |
  | **Total** | | **42.81** |

  The demo's expected output says 14.21. The actual code, against the actual tables, produces ~42.8. That is a 28-point gap, more than 3x.

  Spot-checking the MRN-009315 vs MRN-018747 pair (Maria Garcia vs Maria Garcia-Lopez, same DOB, different street same ZIP, different full phone but same last 4 "4567", same email):

  | Field | Comparison | log(m/u) |
  |-------|-----------|----------|
  | first_name | exact | 5.135 |
  | last_name | hyphen_partial (Garcia is a token of Garcia-Lopez) | log(0.04/0.003) = 2.590 |
  | dob | exact | 9.127 |
  | sex | exact | 0.663 |
  | address | same_zip (different street, same ZIP) | log(0.20/0.05) = 1.386 |
  | phone | last_4_match | log(0.10/0.005) = 2.996 |
  | ssn | one_null | 0 |
  | email | exact | 8.700 |
  | **Total** | | **30.60** |

  Demo expected: 11.04. Actual code: ~30.6.

  Three consequences:

  1. **Learners will lose confidence.** A reader who runs the demo and sees ~30 and ~42 where the docs promise 11 and 14 will spend time wondering what they did wrong. The reasonable conclusion is "the docs are wrong," which is correct but undermines the rest of the recipe.
  2. **The reasoning chain about thresholds breaks.** The demo's `HIGH_THRESHOLD = Decimal("8.0")` is correctly above the expected scores (11.04, 14.21, 15.83) by a small margin, which lets a reader see the auto-match-vs-review-queue decision boundary in action. With actual scores in the 30+ range, the threshold is wildly conservative; everything plausibly auto-matches without the threshold meaningfully discriminating. A reader looking at the demo's threshold tuning loses the pedagogical signal.
  3. **The disclaimer overstates what "slightly" means.** A 3x discrepancy is not the result of small m/u tweaks; it is the result of the expected output being generated under a different m/u table than the one currently published, or being computed by hand without actually running the code.

- **Suggested fix:** Two options:

  1. **Run the demo and update the expected output to match.** The simplest fix. Re-run the demo against the published tables, paste the actual output into the block, and adjust `HIGH_THRESHOLD` upward to a value that produces the same routing-decision pattern (auto-match for the three duplicate pairs, review for the same-name-different-person pair). For instance, with actual scores in the 30+ range for true duplicates and ~5 for the same-name-different-DOB-pair, a `HIGH_THRESHOLD` of around 20.0 would preserve the same auto-match / review boundary the recipe is teaching.
  2. **Tighten the m/u tables until the expected scores match.** If the goal is to keep the threshold at 8.0 for pedagogical legibility, lower the m probabilities or raise the u probabilities until the resulting scores cluster in the 10-15 range. This is the more invasive fix and changes the demo's quantitative meaning.

  Option 1 is the right fix. Most of the educational value is in the structure (per-field comparators feeding a probabilistic combiner producing a composite log-likelihood-ratio score that drives a three-way routing decision), not in the specific numbers. Honest numbers that a reader can reproduce by running the demo are worth more than aspirational numbers tuned to fit a chosen threshold.

  Verify the fix by running the demo end-to-end with the published m/u tables and confirming the printed `score=...` values match the expected-output block exactly.

---

### Finding 3: `last_name_metaphone_sec` Is Computed and Persisted on Every Normalized Record but Never Read by Any Comparator

- **Severity:** NOTE
- **File:** `chapter05.01-python-example.md`
- **Locations:** `_double_metaphone` (synthesizes the secondary), `normalize_record` (stores it on every record under `last_name_metaphone_sec`), `_compare_last_name` (reads only `last_name_metaphone`)
- **Description:**

  Every normalized record carries a `last_name_metaphone_sec` field:

  ```python
  return {
      ...
      "last_name_metaphone":   last_metaphone_pri,
      "last_name_metaphone_sec": last_metaphone_sec or "",
      ...
  }
  ```

  No comparator reads it. `_compare_last_name` only consults `a["last_name_metaphone"]` and `b["last_name_metaphone"]`. The blocking passes only key on `r["last_name_metaphone"]`. The audit archive captures the full normalized snapshot, so the dead attribute does take up bytes in S3, but it does no comparator work.

  Same pattern for `first_name_metaphone_sec` would also be a candidate, but the file does not even compute that one (`_double_metaphone` is called and the secondary code is computed but only the primary is stored for first names, see `normalize_record` which stores `first_name_metaphone` but no `_sec` companion).

  The dead attribute is a vestige of the double-metaphone framing in Finding 1: real double metaphone returns a `(primary, secondary)` tuple where the secondary is a different code that captures alternative pronunciations, and the proper comparator pattern is "match on primary OR match on secondary." The Python computes a fake secondary, persists it, but never uses it.

- **Suggested fix:** Two options, dependent on Finding 1:

  1. **If Finding 1 is fixed by adopting real double metaphone**, update `_compare_last_name` (and add a comparable check to `_compare_first_name`) to match on either code:

     ```python
     a_codes = {a["last_name_metaphone"], a.get("last_name_metaphone_sec", "")} - {""}
     b_codes = {b["last_name_metaphone"], b.get("last_name_metaphone_sec", "")} - {""}
     if a_codes & b_codes:
         return "metaphone_match"
     ```

  2. **If Finding 1 is fixed by honestly renaming to metaphone**, drop the `_sec` synthesis from `_double_metaphone` (rename to `_metaphone`), drop the `last_name_metaphone_sec` field from the normalized record schema, and remove the dead reference. The "secondary" was always synthetic; removing it cleans up the schema.

  Option 2 is the smaller change if Finding 1 lands on Option 2 (rename to metaphone). Either way, no normalized-record field should be present-and-unused.

---

### Finding 4: `_query_cluster_members` Does Not Paginate; Large Clusters Silently Truncate at 1MB

- **Severity:** NOTE
- **File:** `chapter05.01-python-example.md`
- **Location:** `_query_cluster_members`
- **Description:**

  ```python
  def _query_cluster_members(mpi_id: str) -> list:
      """All xref entries currently assigned to this mpi_id."""
      if not mpi_id:
          return []
      try:
          resp = dynamodb.Table(MPI_XREF_TABLE).query(
              IndexName=MPI_ID_INDEX,
              KeyConditionExpression=Key("mpi_id").eq(mpi_id),
          )
          return resp.get("Items", [])
      except Exception as exc:
          logger.error("mpi-xref cluster query failed", extra={"error": str(exc)})
          return []
  ```

  DynamoDB's `query` returns at most 1MB of items per call. For a large cluster (a patient with many cross-system source records linked into one MPI identity), the result is silently truncated. `apply_merge` then reads only the truncated cluster, updates the xrefs it sees, and leaves the remainder pointing at the deprecated `mpi_id`. The deprecated-cluster tombstone (`active: false, merged_into: surviving_mpi_id`) provides a recovery path, but the cross-references for the missed members never get updated, so subsequent lookups via `(source_system, source_record_id) -> mpi_id` route through the deprecated record.

  Same pattern as 4.6 Finding 2, 4.7 Finding 5, and 4.10 Finding 5: scan/query without `LastEvaluatedKey` pagination. For most patients with a handful of source records, the cluster fits in a single response; for the long-tail patients with dozens of cross-system linkages (the patients most affected by duplicate-record cleanup, who often have the largest clusters), the silent truncation hits exactly the wrong cohort.

- **Suggested fix:** Add a `LastEvaluatedKey` pagination loop:

  ```python
  def _query_cluster_members(mpi_id: str) -> list:
      """All xref entries currently assigned to this mpi_id."""
      if not mpi_id:
          return []
      items = []
      kwargs = {
          "IndexName": MPI_ID_INDEX,
          "KeyConditionExpression": Key("mpi_id").eq(mpi_id),
      }
      try:
          while True:
              resp = dynamodb.Table(MPI_XREF_TABLE).query(**kwargs)
              items.extend(resp.get("Items", []))
              if "LastEvaluatedKey" not in resp:
                  break
              kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
      except Exception as exc:
          logger.error("mpi-xref cluster query failed", extra={"error": str(exc)})
      return items
  ```

---

### Finding 5: `apply_merge` Does Not Wrap the `mpi-master` `put_item` in try/except; A Failure There Aborts Before Cross-Reference Updates, Leaving the State Half-Updated

- **Severity:** NOTE
- **File:** `chapter05.01-python-example.md`
- **Location:** `apply_merge`, the master-write block
- **Description:**

  Most DynamoDB calls in the file are wrapped in try/except with logged warnings (the read paths via `_get_xref` and `_query_cluster_members`, the per-xref update inside the merge loop, the deprecated-cluster tombstone update). The two `put_item` and `update_item` calls in `apply_merge` that persist the merged master record are NOT wrapped:

  ```python
  # Persist the merged master and update cross-references for every
  # source record in either cluster. ...
  dynamodb.Table(MPI_MASTER_TABLE).put_item(Item=merged_master)
  ```

  If this raises (the bucket doesn't exist in the demo, throttling in production, an IAM error), the function aborts before the loop that updates the cross-references runs. The deprecated-cluster tombstone updates also do not run. The audit-archive write does not run. The EventBridge merge-event emit does not run. The downstream consumers (EHR chart linkage, data warehouse, billing) never learn about the merge.

  In production, this means a single transient master-write failure leaves: the deprecated cluster's master record still active, no merged master, the cross-references still pointing at the deprecated mpi_id, and no audit trail of the attempt. The next merge attempt would redo the work, but if the recovery is manual (the engineer has to know the previous attempt failed), the system silently produces a half-merge.

  The recipe's "Why This Isn't Production-Ready" section names `TransactWriteItems` as the production fix, and the comment above the put_item names it explicitly:

  ```python
  # A real implementation does this in a TransactWriteItems call to
  # keep the master and xref writes atomic; the demo splits them
  # for readability.
  ```

  The demo's intent is correct (split for readability). The problem is that the demo's split is also unwrapped, so partial-failure scenarios are silent rather than logged. A reader running the demo offline (no provisioned tables) sees the function raise out of `apply_merge`, the surrounding `run_dedup_pipeline` catches it, and the merge count is 0 rather than the printed "merges applied: 3."

- **Suggested fix:** Wrap the master and xref writes in try/except with logged warnings, matching the pattern used elsewhere in the file:

  ```python
  try:
      dynamodb.Table(MPI_MASTER_TABLE).put_item(Item=merged_master)
  except Exception as exc:
      logger.error(
          "merged master write failed",
          extra={"surviving_mpi_id": surviving_mpi_id, "error": str(exc)},
      )
      raise  # or route to DLQ; do not silently lose the merge
  ```

  The `raise` after the log preserves the abort semantics so the audit archive and event emit do not run with an inconsistent state. Production replaces the whole block with `TransactWriteItems`, as the comment already names. At minimum, the demo should not silently produce different output (`merges applied: 3` printed) than what actually happened (zero merges, all aborted at the master write).

---

### Finding 6: Demo Runner's Print Output Implies Persistence That Does Not Happen When Run Offline Against Unprovisioned Tables

- **Severity:** NOTE
- **File:** `chapter05.01-python-example.md`
- **Locations:** `run_demo`, `run_dedup_pipeline`, the "Expected console output" block
- **Description:**

  Same pattern flagged in 4.6 Finding 4, 4.7 Finding 3, 4.8, 4.9, and 4.10 Finding 4. The demo runs against unprovisioned DynamoDB tables, S3 buckets, EventBridge buses, and CloudWatch namespaces; every persistence call either fails silently with a logged warning (read paths, audit S3 puts, metric emits) or aborts the merge function entirely (the master write per Finding 5). The print output in `run_demo`:

  ```python
  print(f"Auto-matched pairs ({len(summary['auto_match'])}):")
  for p in summary["auto_match"]:
      print(f"  {p['record_a_id']} <-> {p['record_b_id']}  "
            f"score={float(p['composite_score']):.2f}")
  ```

  prints the routing decisions correctly because they are computed in-memory and do not depend on persistence. But the implied "merges applied: 3" line in the expected output assumes `apply_merge` succeeded three times. Per Finding 5, `apply_merge`'s unwrapped `put_item` raises on the first call against the unprovisioned `mpi-master` table, the surrounding `try/except` in `run_dedup_pipeline` catches and logs, and `summary["merges_applied"]` stays empty. The actual offline run prints "merges applied: 0," not "merges applied: 3."

  Same applies to the audit-archive S3 writes (the bucket `my-mpi-audit` does not exist), the EventBridge merge events (the bus does not exist), the review-queue DynamoDB writes, and the CloudWatch metric emits. All fail silently, none of the printed routing decisions are persisted anywhere.

- **Suggested fix:** Same as the chapter pattern, two reasonable options:

  1. **Lighter fix:** Add a clear "running offline against unprovisioned tables" disclaimer at the top of `run_demo`, and reframe the expected output to acknowledge that the routing decisions are computed in-memory while the persistence calls fail silently:

     ```python
     print("=" * 70)
     print("Note: this demo runs OFFLINE. DynamoDB, S3, EventBridge, and")
     print("CloudWatch calls fail with ResourceNotFoundException because")
     print("the underlying resources do not exist; failures are caught")
     print("and logged at WARNING. The demo prints describe what each")
     print("step WOULD do against a provisioned environment, not what")
     print("the code persists in this run.")
     print("=" * 70)
     ```

  2. **Heavier fix:** Provide a docker-compose snippet (DynamoDB-Local + minio for S3 + LocalStack for EventBridge / CloudWatch) so the demo can be exercised end-to-end. Recipes 4.6 through 4.10 deferred this; consistency suggests deferring here too unless the project plans to retrofit it across the chapter.

  Adjacent fix per Finding 5: wrap the master and xref writes in try/except so the offline run produces logged warnings rather than an aborted merge.

---

### Finding 7: `_compare_address` Returns `same_zip` Where the Recipe Pseudocode and Sample JSON Both Name the Level `same_zip_different_street`

- **Severity:** NOTE
- **File:** `chapter05.01-internal-duplicate-patient-detection.md` and `chapter05.01-python-example.md`
- **Locations:** the recipe's pseudocode in Step 3 (the `compare_address` block), the recipe's "Expected Results" sample candidate-pair JSON, and the Python file's `_compare_address` function and `M_PROBABILITIES["address"]` table
- **Description:**

  The main recipe's pseudocode for the address comparator lists comparison levels as:

  ```
  field_comparisons.address = compare_address(record_a.address_usps,
                                              record_b.address_usps)
      // returns: exact, same_zip_plus_4, same_street_different_apt,
      // same_zip_different_street, mismatch, one_null, both_null
  ```

  And the Expected Results section's sample JSON uses the explicit name:

  ```json
  "field_comparisons": {
      ...
      "address": "same_zip_different_street",
      ...
  }
  ```

  The Python file's `_compare_address` returns `"same_zip"` (without the `_different_street` suffix), and the M/U probability tables key on `same_zip`:

  ```python
  "address": {
      "exact":            Decimal("0.55"),
      "same_zip":         Decimal("0.20"),
      "same_street":      Decimal("0.10"),
      ...
  }
  ```

  Three small inconsistencies:

  1. **Level names diverge.** Pseudocode says `same_zip_different_street`; Python says `same_zip`. The semantics are the same (same ZIP, different street), but a reader cross-checking the Python against the pseudocode is left wondering whether `same_zip` is a different level or a renaming.
  2. **Pseudocode mentions `same_zip_plus_4` and `same_street_different_apt` levels.** The Python doesn't implement these. The pseudocode comment is illustrative, but the Python flattens the level set without a comment naming the simplification.
  3. **Pseudocode mentions `both_null` separately from `one_null`.** The Python collapses both to `one_null` (since the M/U tables only key on `one_null`). Same pattern as the dob comparator (Finding 8).

- **Suggested fix:** Either rename the Python's level names to match the recipe's pseudocode and update the M/U tables, or add a comment in `_compare_address` naming the demo's simplification:

  ```python
  def _compare_address(a: dict, b: dict) -> str:
      """
      Compare normalized addresses. ...

      NOTE: The recipe's pseudocode names levels `exact`,
      `same_zip_plus_4`, `same_street_different_apt`,
      `same_zip_different_street`, `mismatch`, `one_null`, and
      `both_null`. The demo collapses these into `exact`,
      `same_street` (same ZIP and same leading 3 tokens; covers
      same-street-different-apt and same-zip-plus-4 in practice
      since the demo's coarse normalizer doesn't surface ZIP+4),
      `same_zip` (same ZIP, different street), `mismatch`, and
      `one_null` (both nulls and one-null collapsed). Production
      reads ZIP+4 from a CASS-certified standardizer and exposes
      the finer-grained levels.
      """
      ...
  ```

  Either fix closes the inconsistency.

---

### Finding 8: `_log_likelihood_ratio` Docstring Promises a `log((1-m)/(1-u))` Fallback That Is Never Implemented

- **Severity:** NOTE
- **File:** `chapter05.01-python-example.md`
- **Location:** `_log_likelihood_ratio`
- **Description:**

  The docstring says:

  ```python
  def _log_likelihood_ratio(field: str, level: str) -> Decimal:
      """
      Per-field, per-comparison-level log-likelihood-ratio contribution.
      Look up m and u; return log(m/u) when both are positive, fall back
      to log((1-m)/(1-u)) for null-handling.
      ...
      """
  ```

  The body never computes `log((1-m)/(1-u))`. It returns `log(m/u)` for positive levels and `Decimal("0")` for null and zero-probability cases:

  ```python
  if m is None or u is None:
      return Decimal("0")
  if level == "one_null":
      return Decimal("0")
  if m <= 0 or u <= 0:
      return Decimal("0")
  return _to_decimal(math.log(float(m) / float(u)))
  ```

  The implementation is internally consistent with the way the M/U tables are parameterized: each comparison level (exact, jaro_winkler_high, mismatch, etc.) has its own `m` and `u`, so `log(m_level / u_level)` is the right formula uniformly. The classical Fellegi-Sunter formulation (where the choice between `log(m/u)` and `log((1-m)/(1-u))` depends on whether the field is observed-as-match or observed-as-non-match) is implicitly absorbed by the per-level parameterization. So the implementation is fine; the docstring is wrong about a fallback that never happens.

  The docstring will mislead a reader trying to understand what the demo's null-handling actually does. The next paragraph of the docstring even contradicts itself:

  ```
  Null-on-one-side contributes nothing (zero) under standard Fellegi-Sunter.
  ```

  which is what the code actually does. So the first sentence is residue from an earlier version of the function that did implement the fallback.

- **Suggested fix:** Update the docstring to match the implementation:

  ```python
  def _log_likelihood_ratio(field: str, level: str) -> Decimal:
      """
      Per-field, per-comparison-level log-likelihood-ratio contribution.

      Each comparison level (exact, jaro_winkler_high, mismatch, etc.)
      has its own (m, u) entry in M_PROBABILITIES / U_PROBABILITIES, so
      log(m_level / u_level) is the correct contribution uniformly: a
      "match" level (m > u) contributes positively, a "mismatch" level
      (m < u) contributes negatively. Null-on-one-side contributes zero
      under standard Fellegi-Sunter (no information about identity).

      Returns Decimal("0") for null cases and for missing or
      zero-probability table entries (defensive against table
      misconfiguration).
      """
  ```

---

### Finding 9: `_compare_dob` Has a Redundant Logical Check on the Quality Flags

- **Severity:** NOTE
- **File:** `chapter05.01-python-example.md`
- **Location:** `_compare_dob`
- **Description:**

  The function opens with two consecutive flag checks:

  ```python
  # Implausible values do not contribute information; treat as null.
  if a_flag != "ok" and b_flag != "ok":
      return "one_null"
  if a_flag != "ok" or b_flag != "ok":
      return "one_null"
  if not a_dob or not b_dob:
      return "one_null"
  ```

  The first conditional (`and`) is a strict subset of the second (`or`): any case where both flags are not "ok" is also a case where at least one flag is not "ok". The second conditional already catches the both-bad case; the first is dead code.

  The intent might have been to distinguish a "both null" comparison level from a "one null" level (the recipe's pseudocode mentions "both_null" as a distinct level), but `M_PROBABILITIES["dob"]` only keys on `one_null`, not `both_null`. So even if the first conditional returned a different string, there would be nowhere for it to feed into.

- **Suggested fix:** Drop the first conditional:

  ```python
  # Implausible or missing values do not contribute information;
  # treat as null. Standard Fellegi-Sunter null-handling: null on
  # one or both sides contributes zero log-likelihood.
  if a_flag != "ok" or b_flag != "ok":
      return "one_null"
  if not a_dob or not b_dob:
      return "one_null"
  ```

  If a future iteration wants to distinguish both-null from one-null (which would let the m/u tables carry separate entries for the two cases), add the level to the M/U tables first and then split the conditional.

---

### Finding 10: `unmerge` Raises `NotImplementedError` Despite the Recipe's Strong Reversibility Framing

- **Severity:** NOTE
- **File:** `chapter05.01-python-example.md`
- **Location:** the `unmerge` function at the end of Step 5
- **Description:**

  The function body is a TODO comment block that raises:

  ```python
  def unmerge(merge_id: str, reason: str, operator_id: str) -> None:
      """..."""
      # TODO: fetch the audit record from S3 / audit table by merge_id.
      # ...
      raise NotImplementedError(
          "unmerge requires the institution-specific audit-record "
          "lookup path; see Gap to Production."
      )
  ```

  The recipe text spends substantial space on reversibility, framing it as non-negotiable:

  > Even with conservative thresholds and human review, some merges will be wrong. ... When that happens, you need to be able to **unmerge** the records cleanly. ... You cannot bolt this on later. The data structures need to support reversibility from day one, because once you have done a year of merges without provenance, the reverse-engineering is painful and lossy.

  The pseudocode in the main recipe includes a complete `unmerge` implementation. The Python omits it. The omission is acknowledged in the comment and in the Gap to Production section, which is good, but the function body is the recipe's load-bearing claim that "the data structures support reversibility from day one." The Python data structures do support it (the audit record carries `pre_merge_master_a`, `pre_merge_master_b`, `source_records_in_merge`, and the per-xref `previous_mpi_id_history`), so the unmerge is implementable. Leaving it unimplemented loses the demonstration that the substrate works.

  Two consequences:

  1. **The pseudocode-to-Python consistency drifts on the recipe's most prominently emphasized property.** A reader copying the demo into production carries forward a pipeline that cannot reverse a wrong merge.
  2. **The audit-archive partition `unmerge` has no producer.** The `_write_audit_archive` helper takes a `partition` parameter; the merge path uses `partition="merge"`. Nothing writes to `partition="unmerge"`. The S3 partitioning by routing decision and merge-action is set up but not exercised.

- **Suggested fix:** Implement the function. The audit record contains everything needed:

  ```python
  def unmerge(merge_id: str, reason: str, operator_id: str) -> None:
      """
      Reverse a previously-applied merge using the audit record.
      Restores the pre-merge masters and re-points the cross-references
      back to their pre-merge mpi_ids. Records the unmerge as a
      reversible action.
      """
      audit_record = _fetch_audit_record_by_merge_id(merge_id)
      if not audit_record:
          raise ValueError(f"No audit record for merge_id {merge_id}")

      # Restore pre-merge masters.
      for pre_merge in [audit_record["pre_merge_master_a"],
                        audit_record["pre_merge_master_b"]]:
          if pre_merge.get("mpi_id"):
              try:
                  dynamodb.Table(MPI_MASTER_TABLE).put_item(Item=pre_merge)
              except Exception as exc:
                  logger.error("master restore failed", extra={"error": str(exc)})

      # Restore cross-references.
      for source_ref in audit_record["source_records_in_merge"]:
          previous = (source_ref.get("previous_mpi_id_history") or [None])[-1]
          if not previous:
              continue
          try:
              dynamodb.Table(MPI_XREF_TABLE).update_item(
                  Key={
                      "source_system":    source_ref["source_system"],
                      "source_record_id": source_ref["source_record_id"],
                  },
                  UpdateExpression=(
                      "SET mpi_id = :prev, last_reassigned_at = :ts"
                  ),
                  ExpressionAttributeValues={
                      ":prev": previous,
                      ":ts":   _now_iso(),
                  },
              )
          except Exception as exc:
              logger.error("xref restore failed", extra={"error": str(exc)})

      # Mark the survivor as no-longer-active-as-survivor.
      try:
          dynamodb.Table(MPI_MASTER_TABLE).update_item(
              Key={"mpi_id": audit_record["surviving_mpi_id"]},
              UpdateExpression="SET unmerged_at = :ts, unmerge_reason = :r",
              ExpressionAttributeValues={
                  ":ts": _now_iso(), ":r": reason,
              },
          )
      except Exception as exc:
          logger.error("survivor unmerge update failed", extra={"error": str(exc)})

      # Audit and event.
      _write_audit_archive({
          "unmerge_id":       str(uuid.uuid4()),
          "original_merge_id": merge_id,
          "operator_id":      operator_id,
          "reason":           reason,
          "unmerged_at":      _now_iso(),
      }, partition="unmerge")

      try:
          eventbridge_client.put_events(Entries=[{
              "Source":       "mpi-deduplication",
              "DetailType":   "patient_records_unmerged",
              "EventBusName": MERGE_EVENTS_BUS_NAME,
              "Detail":       json.dumps({
                  "original_merge_id": merge_id,
                  "operator_id":       operator_id,
                  "reason":            reason,
                  "unmerged_at":       _now_iso(),
              }, default=str),
          }])
      except Exception as exc:
          logger.error("unmerge event emit failed", extra={"error": str(exc)})
  ```

  The `_fetch_audit_record_by_merge_id` helper is the institution-specific bit (S3 prefix scan keyed on `merge_id`, or a dedicated DynamoDB audit table indexed by `merge_id`); the demo can stub it to return `None` with a `# TODO` block naming the lookup pattern. Even an unimplemented lookup helper plus a working unmerge body is more useful than a `NotImplementedError` because it demonstrates the unmerge mechanics with the audit record's data structures.

  At minimum, if the function stays as `NotImplementedError`, add the demo runner a single call to `unmerge(some_merge_id, "test", "demo-operator")` wrapped in try/except so the reader sees what error the function raises and can wire up the lookup helper to make it work.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Function | Consistent? |
|----------------|-----------------|-------------|
| `normalize_record(raw_record)` | `normalize_record(raw_record)` plus the per-field helpers (`_normalize_name`, `_normalize_suffix`, `_expand_nicknames`, `_double_metaphone`, `_normalize_dob`, `_normalize_phone`, `_normalize_ssn`, `_normalize_email`, `_normalize_address`) | Mostly yes (canonicalization, nickname expansion, phonetic encoding, date parsing, address normalization, SSN validation with quality flag, email normalization, phone normalization with last-7 / last-4 derivations, provenance fields). **The phonetic encoder is metaphone, not double metaphone, per Finding 1.** **The `last_name_metaphone_sec` field is computed and stored but never read by any comparator per Finding 3.** |
| `generate_candidate_pairs(normalized_records)` | `generate_candidate_pairs` plus `_block_and_collect`, `_make_pair_key` | Yes for the five blocking passes (lastname-metaphone + DOB-year, firstname-metaphone + last-initial + DOB-year, last-initial + full-DOB, ZIP + last-initial, phone-last-4 + DOB-year). The pair-key dedup, the oversized-block skip with logging, and the empty-key skip are all faithful. |
| `score_pair(record_a, record_b, model)` | `score_pair` plus the `_compare_*` per-field helpers and `_log_likelihood_ratio` | Yes for the per-field comparator levels and the Fellegi-Sunter combination. **`_compare_address` returns `same_zip` where the recipe's pseudocode and sample JSON name the level `same_zip_different_street` per Finding 7.** **`_log_likelihood_ratio`'s docstring promises a `log((1-m)/(1-u))` fallback that is never implemented per Finding 8.** **`_compare_dob` has a redundant first conditional per Finding 9.** The match-probability sigmoid for human-friendly display is added (not in the pseudocode but reasonable). |
| `route_pair(pair_score, thresholds)` | `route_pair` plus `_serialize_for_dynamodb`, `_write_audit_archive`, `_emit_metric` | Yes (three-bucket routing, audit-archive write per decision, review-queue write for the middle band, CloudWatch metric per routing decision, priority computation linear in score). The recipe's pseudocode includes a `compute_priority(pair_score, thresholds)` call that is inlined in the Python; the inlining is reasonable. |
| `apply_merge(record_a, record_b, decision_metadata)` | `apply_merge` plus `_get_xref`, `_query_cluster_members`, `_pick_surviving_mpi_id`, `_seed_master_from_record`, `_combine_history_lists`, `_merge_with_rule` | Yes for the cluster-merge logic (idempotency check, surviving-mpi_id selection, master loading, survivorship-rule application, xref reassignment, deprecated-cluster tombstone, audit-archive write, EventBridge merge event). **`_query_cluster_members` does not paginate per Finding 4.** **The master `put_item` is unwrapped per Finding 5.** **`unmerge` is `NotImplementedError` per Finding 10.** The pseudocode's `TransactWriteItems` for atomic master+xref writes is acknowledged in comments and explicitly deferred to production. |

Intentional deviations clearly framed:

- The pseudocode's `expand_nicknames` returns a set of plausible legal-name equivalents; the Python returns a sorted list (set ordering is not deterministic for JSON serialization). Reasonable for the audit-archive write.
- The pseudocode's `usps_standardize` becomes `_normalize_address`, a coarse regex-based normalizer. Documented in the function comment and in Setup.
- The pseudocode's EM-based m/u estimation becomes hand-set values in `M_PROBABILITIES` / `U_PROBABILITIES`. Acknowledged in Configuration and Constants and in Gap to Production.
- The pseudocode's OpenSearch-backed real-time candidate index is replaced with the in-process blocker. Documented in Gap to Production.
- The pseudocode's Spark-backed Splink batch matcher is collapsed to in-process Python. Documented in Gap to Production.

The substantive deviations (Findings 1, 7, 8, 10) are the consistency gaps that have the most pedagogical consequence.

---

## AWS SDK Accuracy

| API Call | Method | Notes |
|----------|--------|-------|
| DynamoDB GetItem | `dynamodb.Table(NAME).get_item(Key={...})` | Correct. Composite-key reads on `mpi-xref` use `(source_system, source_record_id)`. Single-key reads on `mpi-master` use `mpi_id`. |
| DynamoDB PutItem | `dynamodb.Table(NAME).put_item(Item=_serialize_for_dynamodb(...))` | Correct. All numeric values flow through `_serialize_for_dynamodb`, which routes floats to `Decimal(str(...))` and preserves Decimals as-is. |
| DynamoDB UpdateItem with SET and list_append | `UpdateExpression="SET mpi_id = :new_mpi, last_reassigned_at = :ts, previous_mpi_id_history = list_append(if_not_exists(previous_mpi_id_history, :empty), :prev)"` | **Correct shape.** The `list_append(if_not_exists(history, :empty), :prev)` pattern is the right way to append to a List attribute on first or subsequent writes. This is the pattern that should propagate to Recipes 4.6 and 4.7 to fix the `ADD state_history :history_event` ERROR flagged in those reviews. |
| DynamoDB Query on GSI | `dynamodb.Table(MPI_XREF_TABLE).query(IndexName=MPI_ID_INDEX, KeyConditionExpression=Key("mpi_id").eq(mpi_id))` | Correct shape. **No pagination per Finding 4.** Uses `boto3.dynamodb.conditions.Key` correctly. |
| S3 PutObject | `s3_client.put_object(Bucket=AUDIT_BUCKET, Key=audit_key, Body=body, ServerSideEncryption="aws:kms")` | Correct. Body is bytes-encoded. Key uses `audit/{partition}/{today}/{uuid.uuid4()}.json` with no leading slash. `ServerSideEncryption="aws:kms"` without an explicit `SSEKMSKeyId` defaults to the AWS-managed key for SSE-KMS; production should specify the customer-managed key explicitly per the recipe's Encryption posture, but the demo's choice is an acceptable simplification. |
| EventBridge PutEvents | `eventbridge_client.put_events(Entries=[{Source, DetailType, EventBusName, Detail}])` | Correct. `Detail` is JSON-serialized via `json.dumps(..., default=str)` to handle Decimal serialization. |
| CloudWatch PutMetricData | `cloudwatch_client.put_metric_data(Namespace=CLOUDWATCH_NAMESPACE, MetricData=[{MetricName, Value, Unit, Dimensions}])` | Correct shape. The `Dimensions` list is built from `dimensions or {}.items()`; cardinality is low (one dimension `Decision` with three possible values). |

The SDK-level concerns are: Finding 4 (no pagination on the Query) and Finding 5 (the unwrapped `put_item` to `mpi-master`). All other API surfaces are current and correct. Notably, this file's `list_append` pattern for appending to the `previous_mpi_id_history` list is the textbook-correct DynamoDB approach and should be propagated to the Recipe 4.6 and 4.7 examples to fix the `ADD state_history :history_event` ERRORs flagged in those reviews.

---

## DynamoDB and Data Type Check

- `_to_decimal` correctly uses `Decimal(str(value))` and short-circuits on already-Decimal inputs.
- `_serialize_for_dynamodb` recursively walks dicts and lists, converts floats to Decimal, and preserves tuples as lists. Booleans are unaffected (not coerced to Decimal). Worth noting: the function does not have an explicit `isinstance(obj, bool)` guard before the float check, but in Python `isinstance(True, float)` is `False` (bool is a subclass of int, not float), so booleans pass through unchanged. The pattern is safe; a defensive `bool` guard like the one in 4.x reviews would be more explicit but is not required here.
- All `update_item` and `put_item` writes route numerics through `_serialize_for_dynamodb` at the persistence boundary.
- The hand-set m/u probability tables use `Decimal(str("..."))` directly. Correct.
- The composite score is computed as `sum(per_field_log_ratios.values(), Decimal("0"))` where each per-field ratio is `_to_decimal(math.log(...))`. Decimal arithmetic preserves precision; the float bridge in `math.log` is acknowledged in the comment.
- `match_probability = Decimal(str(1.0 / (1.0 + math.exp(-float(composite)))))` round-trips through float for the sigmoid, which loses precision relative to the Decimal score, but the value is for human-friendly display only and the approximation is fine.
- The `priority` computation in `route_pair` uses Decimal arithmetic consistently: `Decimal("100") * (score - low_threshold) / (high_threshold - low_threshold)`. Correct.
- The `_combine_history_lists` helper deduplicates entries by `value` and keeps the most recent `as_of`. The comparison is string lexicographic on the `as_of` ISO timestamp, which is correct for ISO 8601 (lexicographic order matches chronological order when the timestamps include a Z suffix or are otherwise consistently formatted).

The Decimal discipline is correct. No type-handling bugs.

---

## S3 and Credentials Check

- The example uses S3 only for the audit archive (`AUDIT_BUCKET`). Keys use `audit/{partition}/{today}/{uuid.uuid4()}.json`. No leading slash on any key.
- The deploy-time guardrail (`assert AUDIT_BUCKET != "", "AUDIT_BUCKET must be set before deploying."`) is a nice touch for catching unreplaced placeholder values.
- No hardcoded credentials. Module-level boto3 clients use the documented environment credential chain.
- The IAM permissions list in Setup matches the API surface used by the code (DynamoDB on the three named tables and the GSI, S3 PutObject on the audit-archive bucket, EventBridge PutEvents on the merge-events bus, CloudWatch PutMetricData for the queue-depth and disparity metrics).
- The Setup section explicitly names that "tutorial-level permissions above are fine for learning and will fail any serious IAM review" with the right framing about per-Lambda role scoping.

Pass.

---

## Comment Quality Assessment

Comments consistently explain the "why":

- The Heads-up at the top names every major production gap before the code starts (no real EHR or registration-system feed, no Splink or Spark-based batch pipeline, no OpenSearch-backed real-time candidate index, no USPS address standardization beyond a coarse regex, no EM-based m/u estimation, no review-queue UI, no IAM / KMS / VPC / CloudTrail wiring).
- The PHI-logging guidance at the module level: *"The MPI tables are clinical-record-equivalent PHI. ... These are the most sensitive data structures in the pipeline. Encrypt with a customer-managed KMS key, gate every read with CloudTrail data events, and apply tighter-than-default access control. Never log raw record values from these tables in application logs."*
- The Decimal-at-the-DynamoDB-boundary discipline: *"DynamoDB rejects Python float. Every probability, similarity score, and likelihood ratio passes through Decimal on its way in and on its way out. Floats in money or in probabilistic match scores are precision-loss bugs waiting to happen; Decimal is the safe and the correct choice for both."*
- The hand-set m/u disclaimer: *"Hand-set m/u probabilities, not EM-estimated. The probabilistic scorer below uses fixed m and u values per (field, comparison_level) pair. They are reasonable starting values illustrative of what an EM-trained model produces, but they are not tuned to your data. In production, fit them with splink or the recordlinkage library on a labeled gold set and re-fit on a documented cadence (typically quarterly)."*
- The blocking-strategy rationale per pass: each pass's comment names the failure mode it catches (last-name change for marriage / divorce, name spelling variations via metaphone, DOB data-quality issues, name-but-stable-phone). A reader extending the blocking strategy with a new pass has the schema to follow.
- The implausible-DOB framing in `_normalize_dob`: *"Common garbage values to flag: 1900-01-01, 9999-12-31, 0001-01-01, or a year more than 130 years in the past or in the future. These are common garbage values entered when the registration clerk did not have a real DOB and the system required a value; they should not be used as matching evidence."*
- The SSN validation rationale: *"Known-garbage patterns: all zeros, all nines, sequential. Area number 000 or 666 are reserved/invalid."* The flagged-but-preserved approach (return the digits but mark `invalid_pattern`) is consistent with the "treat as null in comparators but keep for forensics" pattern.
- The hyphenated-last-name comparator rationale: *"Hyphenated-partial: 'garcia' vs 'garcia-lopez' should match if either side is a token of the other side. This is a common marriage / divorce / cultural-naming pattern."* The recipe's equity discussion makes this comparator central; the comment honors that.
- The month/day swap rationale in `_compare_dob`: *"Check for month/day swap: a_dob has month X day Y, b_dob has month Y day X. ... month_day_swap is a common entry error worth catching."*
- The conservative-thresholds discipline in the threshold-routing constants: *"Thresholds set by clinical leadership in consultation with HIM. ... false merges are a safety hazard, false splits are a cost-and-quality issue, so favor false splits over false merges."*
- The audit-archive write rationale: *"All decisions are written to the audit archive regardless of routing. The archive is partitioned by date and routing decision for efficient cohort-stratified analytics."*
- The merge-pseudocode three-case enumeration: *"There are three cases: both records already point to the same mpi_id (idempotent; no work), both records point to different mpi_ids (a 'cluster merge'; both clusters now combine under a single mpi_id), at least one record has no mpi_id yet (assign one or adopt the other's)."*
- The `apply_merge` idempotency-check rationale: *"Real-time matching is event-driven and will see the same pair more than once; the merge must be safe to call repeatedly."*
- The synthetic-data labeling at the top of the file: *"All sample patients in the demo are synthetic, including the three 'Maria Garcia' variants from the recipe's opening narrative; do not treat any specific patient_id, mpi_id, or merge_id in the sample output as real."*
- The collapse-to-single-file note: *"The example collapses Step Functions, Lambda, and EventBridge into a single Python file for readability. In production the normalize, score, route, and merge-application stages are separate Lambda functions, orchestrated by Step Functions, with their own error handling, retries, and DLQs. Comments call out where the boundaries should fall."*

The Gap to Production section is unusually thorough (20+ items spanning EM-based m/u estimation, OpenSearch-backed candidate generation, Splink-on-Glue batch pipeline, Step Functions orchestration with retry / timeout / DLQ, USPS address standardization, curated nickname dictionary, TransactWriteItems for atomic merge writes, idempotency keys on every Lambda, KMS / VPC / CloudTrail posture, cohort-stratified accuracy monitoring, review queue UI, active-learning gold-set construction, threshold tuning, drift monitoring, unmerge implementation, identity-fraud detection, HIM staffing, backfill strategy, patient-facing identity self-service). The breadth honestly tells the reader how much sits between the recipe and a production deployment.

The comments that would benefit from updates per the findings:

- `_double_metaphone`'s docstring contradicts its implementation (Finding 1).
- `last_name_metaphone_sec`'s presence on the normalized record schema is unexplained (Finding 3).
- `_log_likelihood_ratio`'s docstring promises a fallback that never runs (Finding 8).
- The `unmerge` function's `NotImplementedError` is acknowledged but the recipe's strong reversibility framing makes the gap more conspicuous than the comment suggests (Finding 10).

Calibration is otherwise appropriate for a mixed audience.

---

## Healthcare-Specific Requirements

- **PHI logging discipline.** Module-level logger comment is explicit. Logger calls in the file mostly stay on the safe side; raw demographic field values are not logged in application logs (the structured-metadata logging pattern is honored).
- **Synthetic data labeling.** All sample patient IDs (`MRN-009315`, `MRN-014203`, etc.) are obviously synthetic. The Heads-up section warns explicitly. The three Maria Garcia variants from the recipe's opening narrative are reproduced faithfully in the synthetic roster.
- **Decimal at the DynamoDB boundary.** Consistent. Defensive float-to-Decimal coercion in `_serialize_for_dynamodb`.
- **Conservative-thresholds discipline.** `HIGH_THRESHOLD = Decimal("8.0")` and `LOW_THRESHOLD = Decimal("-2.0")` are exposed as module-level constants with the patient-safety asymmetry rationale documented inline. Production tuning is deferred to Gap to Production.
- **Audit-archive every decision.** `_write_audit_archive` runs for auto_match, review, and auto_non_match outcomes; the partition discriminates routing decisions for cohort-stratified analytics.
- **Provenance on every record.** Normalized records carry `source_system`, `source_record_id`, `normalized_at`, and `normalizer_version`. Merge audit records carry `merge_id`, `surviving_mpi_id`, `deprecated_mpi_ids`, `source_records_in_merge`, `decision_metadata`, `survivorship_decisions`, `pre_merge_master_a`, `pre_merge_master_b`, and `survivorship_rules_version`.
- **Reversibility framing.** The data structures support unmerge (audit record carries pre-merge masters and the `previous_mpi_id_history` list). **The `unmerge` function itself raises `NotImplementedError` per Finding 10.**
- **Versioning.** `NORMALIZER_VERSION`, `MODEL_VERSION`, and `SURVIVORSHIP_RULES_VERSION` are stored on the relevant records so a future investigation can attribute drift to a specific release.
- **Implausible-value flagging.** `dob_quality_flag` and `ssn_quality_flag` distinguish present-and-suspect from genuinely-null. `_compare_dob` and `_compare_ssn` correctly treat flagged values as null rather than as low-confidence matches.
- **Equity instrumentation.** The recipe text spends substantial space on cohort-stratified accuracy monitoring, framing it as "first-class concern, not a bolt-on." The Python emits a per-routing-decision counter to CloudWatch but does not stratify by cohort. Acknowledged in Gap to Production: *"Cohort-stratified accuracy monitoring. The demo emits a per-routing-decision counter to CloudWatch but does not stratify by cohort. Production computes match rate, false-positive rate, and review-queue depth by demographic cohort."*
- **Customer-managed KMS posture.** Documented in Setup and Gap to Production.
- **Multi-stage atomicity.** The pseudocode's `TransactWriteItems` for atomic master+xref writes is explicitly deferred to production with a comment on the unwrapped writes.

Pass on healthcare-specific handling. The unmerge gap (Finding 10) and the cohort-stratification deferral are the operationally-relevant gaps.

---

## Logical Flow

The file reads top-to-bottom in pedagogical order matching the pseudocode numbering: Setup, Configuration and Constants (logger, retry config, module-level clients, resource names, versioning, routing thresholds, blocking parameters, nickname dictionary, suffix canonicalization, M/U probability tables, helper utilities), Step 1 (normalize each patient record, with per-field helpers), Step 2 (generate candidate pairs through multiple blocking passes), Step 3 (score each candidate pair with per-field comparators and Fellegi-Sunter combiner), Step 4 (route each pair by threshold, with audit-archive writes and CloudWatch metrics), Step 5 (apply the merge with survivorship and full audit, plus the unmerge stub), Full Pipeline (run_dedup_pipeline assembling the five steps), Demo Runner (synthetic roster including the three Maria Garcia variants from the recipe's opening narrative), Gap to Production.

Each step opens with a short italic prose paragraph that restates the pseudocode step before the code block, matching the cookbook's established pattern. The italic paragraphs are slightly heavier on framing than 4.x's, which fits the recipe's "if you read only one recipe in Chapter 5" framing.

The demo runner builds seven synthetic records across four scenarios: three Maria Garcia variants of the same person (testing exact match, hyphenated-name match, and same-name-different-DOB-different-person discrimination), a fourth Maria Garcia who is a different person (testing the same-name-but-different-other-fields discrimination), a Bob/Robert Smith pair (testing nickname expansion), and an Aaron Patel as an unrelated control (testing that blocking correctly excludes unrelated records). The roster is well-chosen to exercise the blocking strategies and the per-field comparators.

---

## What Is Done Particularly Well

Worth calling out explicitly:

- The blocking-pass design enumerates five passes with explicit failure-mode rationales for each. Pass 1 (lastname-metaphone + DOB-year) catches name spelling variations; pass 2 (firstname-metaphone + last-initial + DOB-year) catches last-name change; pass 3 (last-initial + full-DOB) catches first-name nickname mismatches; pass 4 (ZIP + last-initial) catches DOB data-quality issues; pass 5 (phone-last-4 + DOB-year) catches major name typos with stable phone. A reader extending with a new pass has a template to follow.
- The `_block_and_collect` helper handles the empty-key skip and the oversized-block skip with logging. `MAX_BLOCK_SIZE = 200` is exposed as a tunable constant with the rationale that common-name blocks (Smith with common DOBs) explode the comparison count without contributing useful candidates; the other passes catch the duplicates that matter.
- The per-field comparator design is granular enough to capture failure modes that matter: month/day swap, one-digit-off, hyphenated partial (token-level overlap on multi-word last names), nickname expansion (set-overlap on the expanded forms), phonetic match on names, last-7 / last-4 phone partials, local-part email match, single-digit-off SSN.
- The Fellegi-Sunter combiner uses per-(field, level) m/u tables rather than per-field-only m/u tables, which captures the fact that "exact match on first name" is a different evidence level than "Jaro-Winkler-high match on first name." The implementation cleanly maps comparison levels to log-likelihood-ratio contributions.
- The three-bucket routing is faithful to the recipe text. Auto-match, review, and auto-non-match are all preserved in the audit archive (the archive is partitioned by routing decision so the auto-non-match cases are not silently dropped).
- The review-queue priority computation (`Decimal("100") * (score - low_threshold) / (high_threshold - low_threshold)`) is linear in score within the middle band, which lets reviewers work the queue in priority order to maximize impact per unit time. The recipe text frames this as the operational core of the system: *"The review queue is the product, often more than the score is."*
- The merge function correctly handles the three identity-cluster cases (idempotent re-confirmation when both records already point to the same mpi_id, cluster merge when the two records are in different clusters, fresh assignment when neither side has an mpi_id). The `_seed_master_from_record` helper keeps the merge-application logic uniform regardless of which case applies.
- The `_combine_history_lists` helper preserves the union of address / phone / email history with deduplication on value and most-recent timestamp wins. This is the textbook-correct pattern for clinical-history-style fields where wrong survivorship can lose clinically significant data; the helper plus the per-field rule selection gives a reader a reusable pattern.
- The audit record carries the full `pre_merge_master_a` and `pre_merge_master_b` snapshots, which is the substrate that supports unmerge. The data structure is correct even though the unmerge function itself isn't wired up (Finding 10).
- The `previous_mpi_id_history` list-append pattern using `list_append(if_not_exists(previous_mpi_id_history, :empty), :prev)` is the textbook-correct DynamoDB approach for appending to a List attribute on first or subsequent writes. This pattern is what the Recipe 4.6 and 4.7 examples should adopt to fix the `ADD state_history :history_event` ERRORs flagged in those reviews.
- The Gap to Production section's enumeration of unfinished work is candid: EM-based m/u estimation, OpenSearch real-time index, Splink-on-Glue batch pipeline, Step Functions orchestration, USPS address standardization, curated nickname dictionary, TransactWriteItems atomicity, idempotency keys, KMS / VPC / CloudTrail, cohort-stratified accuracy monitoring, review queue UI, active-learning gold-set, threshold tuning, drift monitoring and re-tuning automation, unmerge implementation, identity-fraud detection branch, HIM staffing, backfill strategy, patient-facing self-service.
- The synthetic roster intentionally includes the same-name-different-DOB confounder (the fourth Maria Garcia at MRN-022104), which exercises the score-routes-to-review path. Most demo data either avoids the confounder or hand-waves; this one bakes it in deliberately, demonstrating that the conservative-thresholds discipline produces the right behavior on borderline cases.

---

## Closing Assessment

The teaching content is well-organized and faithful to the main recipe in structure, prose framing, and pedagogical ordering. The five pseudocode steps map onto Python functions with helpers in the right places. The DynamoDB + S3 + EventBridge + CloudWatch API call shapes are correct (modulo the no-pagination item in Finding 4 and the unwrapped put_item in Finding 5). The Decimal-at-the-DynamoDB-boundary discipline is consistent. The blocking-pass design, per-field comparator selection, Fellegi-Sunter combiner, three-bucket routing, and survivorship-rule application are all structurally correct. The audit-archive substrate supports reversibility even though the unmerge function itself is unimplemented.

The two WARNINGs are localized and well-scoped. Finding 1 (jellyfish.metaphone is not double metaphone, but the function name, docstring, and Setup prose all claim it is) is the consistency gap with the most pedagogical consequence: a reader copying the example into production carries forward incorrect terminology and expectations. The fix is either to adopt a real double-metaphone library (the `metaphone` PyPI package) or to honestly rename the helper to `_metaphone`. Finding 2 (the demo's expected output shows scores roughly a third of what the code produces against the published m/u tables) is the consistency gap that will burn the most learner-confidence: a 3x discrepancy is not "slight." The fix is to run the demo against the published tables and paste the actual output into the expected-output block.

The eight NOTEs are smaller items: the dead `last_name_metaphone_sec` attribute, the no-pagination GSI Query, the unwrapped master `put_item`, the demo print-vs-reality mismatch (chapter pattern), the `same_zip` vs `same_zip_different_street` level-name inconsistency, the docstring promising a fallback that never runs, the redundant first conditional in `_compare_dob`, and the unimplemented `unmerge`.

PASS verdict per the persona's rule: no ERRORs, two WARNINGs (under the FAIL threshold of more than three). The two WARNINGs and several NOTEs should be addressed before the recipe ships, because they teach incorrect terminology (double metaphone), produce expected output a learner cannot reproduce, and leave the recipe's most prominently-emphasized property (reversibility) unimplemented, but they do not block the demo from running to completion.

Recipe 5.1 is the foundation recipe for Chapter 5; the recipe text says *"If you read only one recipe in Chapter 5, read this one. If you build only one recipe in this chapter, this is the one."* Closing the WARNINGs and the most-load-bearing NOTEs (Findings 5, 7, 10) brings the example up to the standard the recipe text claims.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** The phonetic-encoder claim is consistent across the function name, docstring, Setup section, and recipe text. Either the `_double_metaphone` helper is rewritten to use a real double-metaphone implementation (the `metaphone` PyPI package, exposing `doublemetaphone(s) -> (primary, secondary)`), or it is renamed to `_metaphone` with the docstring, Setup sentence, and recipe pseudocode updated to say "metaphone" rather than "double metaphone." Either way, all three places land on the same algorithm name, and the synthesized "secondary" is either real (Option 1) or removed (Option 2).
2. **(WARNING)** The "Expected console output" block has been regenerated by actually running the demo against the published `M_PROBABILITIES` and `U_PROBABILITIES` tables. The printed scores match the run output exactly; the disclaimer is updated to say that scores depend on the m/u table values and that the values shown reflect the table at time of writing. `HIGH_THRESHOLD` is adjusted upward (or the m/u tables are tightened downward) so the auto-match / review-queue boundary still falls between the duplicate-pair scores and the same-name-different-person score.
3. **(NOTE)** Either `last_name_metaphone_sec` is read by `_compare_last_name` (matching on either the primary or secondary code), or the field is dropped from the normalized-record schema. No present-and-unused field remains.
4. **(NOTE)** `_query_cluster_members` paginates the GSI Query via `LastEvaluatedKey`, with a smoke test (or comment) demonstrating that clusters larger than ~1MB are retrieved completely.
5. **(NOTE)** The `mpi-master` `put_item` and the deprecated-cluster `update_item` calls in `apply_merge` are wrapped in try/except with logged warnings (or routed to a DLQ in production). The function does not silently abort with no audit trail when the master write fails.
6. **(NOTE)** The demo runner's print messages either acknowledge that the offline run does not persist any state, or a docker-compose snippet is provided in Setup so the demo can be exercised end-to-end. The implied "merges applied: N" line does not overstate what actually happens against unprovisioned tables.
7. **(NOTE)** Either `_compare_address` returns level names matching the recipe's pseudocode (`same_zip_different_street`, `same_street_different_apt`, etc.) and `M_PROBABILITIES` / `U_PROBABILITIES` are updated correspondingly, or `_compare_address` carries a comment naming the demo's level-name simplification and pointing to the production-grade levels.
8. **(NOTE)** `_log_likelihood_ratio`'s docstring is updated to match the implementation (no `log((1-m)/(1-u))` fallback; the per-level m/u parameterization absorbs the match-vs-non-match distinction).
9. **(NOTE)** `_compare_dob`'s redundant first conditional is removed; the second conditional alone covers the both-bad case.
10. **(NOTE)** `unmerge` either has a working implementation that uses the audit record's `pre_merge_master_a`, `pre_merge_master_b`, and `source_records_in_merge` to restore pre-merge state and emits an unmerge audit record plus EventBridge event, or the demo runner exercises the `NotImplementedError` path so the reader sees what's missing and can wire up the institution-specific lookup helper.

After the WARNING fixes, re-run the demo end-to-end and confirm:
- The phonetic-encoder claim is consistent across function name, docstring, Setup, and recipe text.
- The printed scores match the expected-output block exactly.
- The routing decisions are unchanged (three auto-matches, one review, two auto-non-matches against the seven-record synthetic roster).
- Print output remains coherent.
