# Code Review: Recipe 3.10 Epidemic / Outbreak Detection (Python Companion)

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-14
**Files reviewed:**
- `chapter03.10-epidemic-outbreak-detection.md` (main recipe pseudocode)
- `chapter03.10-python-example.md` (Python companion)

**Validation performed:**
- Walked the nine pseudocode steps against Python functions one-to-one
- Verified boto3 API call shapes for DynamoDB resource, Kinesis, Timestream Write, S3, EventBridge, CloudWatch, Comprehend Medical, SageMaker Runtime, Bedrock Runtime, and Amazon Location Service
- Traced numeric values flowing into DynamoDB for Python-float writes (cell-state, cluster-state, geocode cache, suppression rules)
- Inspected S3 keys for leading slashes and `s3://` scheme leakage
- Checked the multi-source fusion candidate-to-signal matching for cross-source concordance behavior
- Verified healthcare-specific requirements: PHI logging discipline, synthetic data labeling, BAA-eligible services, encryption posture, suppression semantics, outcome label derivation, public health authority framing

---

## Verdict: PASS

Zero ERROR findings, three WARNING findings, ten NOTE findings. Three WARNINGs lands at PASS per persona policy (more than 3 WARNINGs would mean FAIL).

The three WARNINGs are correctness gaps in cluster lookup, suppression-rule lookup, and the multi-source fusion mechanic. `find_existing_open_cluster` uses `table.scan` with a `FilterExpression` and no pagination, so when the cluster-state table grows beyond 1MB the open-cluster match silently misses items past the response cap and the cluster builder opens duplicates against the same geography x syndrome. `check_recent_dismissal` uses `table.scan` without pagination on the suppression-rules table, with the same silent-loss failure mode once the table is non-trivial. `max_score_for` and `candidate_geo_windows` together implement multi-source fusion via direct string equality on `geo_id`, so a clinical census-tract candidate (geo_id `36055-001100`), a wastewater sewershed signal (geo_id `ROC-CENTRAL`), and a school-district absenteeism signal (geo_id `ROC-CITY`) never fuse into the same candidate row; the concordance bonus that the recipe makes the headline value-add of the chapter never triggers in the demo because the geo_id strings never match across source classes.

The ten NOTEs cluster around editorial and operational hygiene: unused imports (including a logistic-regression import the Heads-up references but the file never trains), a missing logger handler, S3 `put_object` calls without `SSEKMSKeyId`, EventBridge `put_events` responses not inspected for `FailedEntryCount`, a Bedrock model ID two generations old, OpenSearch indexing named in the Setup permissions block but never implemented in code, address-geocode-cache items written without a TTL attribute despite the prose recommending TTL-based expiration, naive county-FIPS-prefix string slicing for spatial grouping in `aggregate_adjacent_flags`, the `find_existing_open_cluster` exact-match comparison keyed on geo_id only (not on (type, id)), and a Heads-up reference to a `score_via_sagemaker_endpoint` function that doesn't exist in the file (the actual function is `score_via_syndrome_classifier`).

The Decimal discipline at the DynamoDB boundary is consistent with Recipes 3.7, 3.8, and 3.9: the recursive `_decimalize` walker handles nested dicts and lists correctly, `_to_decimal` routes through `Decimal(str(value)).quantize(...)` to avoid binary-precision drift, and every DynamoDB write site goes through one or the other. The PHI logging discipline (logger comment names encounter payloads, chief-complaint text, line lists, lab results, and Bedrock prompts as PHI) is in good shape; nothing in the example dumps full payloads or feature vectors. The Bedrock prompt constraints (no public-health-action recommendations, no assertions of specific pathogens beyond what the lab and genomic context indicates, required end-phrase "This is decision support; investigator judgment governs the public health response.", `temperature=0.0`) are appropriate for an investigator-facing summary, and the Bedrock-failure fallback to a structured-only summary preserves cluster-builder functionality.

The nine-step pseudocode-to-Python mapping is faithful in shape. Step boundaries align between the recipe and the companion, helper functions appear just before they're used, and the prose between code blocks names what's simplified for teaching, what's deferred to production, and what's a deliberate teaching choice. The Heads-up section names every production gap before the code starts; the Gap to Production section repeats the production-readiness checklist with concrete actionable items, including the public-health-authority and cross-jurisdictional governance work that has to happen alongside the technology.

---

## Findings

### Finding 1: `find_existing_open_cluster` uses `table.scan` with `FilterExpression` and no pagination; silently misses open clusters past the 1MB response limit and produces duplicate clusters

- **Severity:** WARNING
- **Location:** `chapter03.10-python-example.md`, `find_existing_open_cluster` (Step 8)
- **Description:** The cluster-grouping lookup is implemented as:

  ```python
  response = cluster_table.scan(
      FilterExpression=Attr("status").eq("open_for_review"),
  )
  for item in response.get("Items", []):
      existing = _undecimalize(item)
      existing_geo_ids = sorted([g["id"] for g in existing.get("geographies", [])])
      existing_syndromes = sorted(existing.get("syndromes", []))
      if (existing_geo_ids == geo_ids
              and existing_syndromes == syndromes):
          return existing
  return None
  ```

  DynamoDB caps each `scan` response at 1MB. Without a `LastEvaluatedKey` pagination loop, every cluster past the truncation boundary is silently dropped from the lookup. A surveillance program operating at the recipe's stated scale (a state-level surveillance system covering 5-10 million population, with per-cluster records that include line-list summary, multi-source concordance, demographic breakdown, lab and genomic context, and a Bedrock-generated narrative) accumulates thousands of cluster records per year. State records of this size hit the 1MB scan cap quickly. Once there, `find_existing_open_cluster` returns `None` for any open cluster that lives past the truncation boundary, `build_clusters` proceeds to the new-cluster branch, and a duplicate cluster is opened against the same geography x syndrome.

  The recipe explicitly relies on cluster grouping: a continuing outbreak that re-flags day after day should land as updates to a single open cluster (via `update_existing_cluster`) rather than fragmenting into many separate cluster records. Fragmentation has three operational consequences. First, the surveillance team queue inflates with multiple rows pointing at the same outbreak; the joint governance committee's "clusters per investigator-day" metric is corrupted. Second, the `Suppressed_RecentDismissal` metric understates suppression effectiveness because each fragment is evaluated independently against the suppression rules. Third, the LLM-generated narrative for each fragment loses the cumulative trajectory the recipe describes ("3.6 times the historical baseline ... excess of approximately 17 cases ... 12 of 23 cases"); the investigator reading fragmented narratives sees disconnected evidence rather than a single accumulating cluster.

  Same finding pattern as Recipe 3.8 Finding 2 and Recipe 3.9 Finding 1, but for the cluster-state table rather than user-state or case-state. The fix is the same: a GSI-backed query keyed on `(status, opened_at)` or similar, or at minimum a pagination loop on the scan.

- **How to fix:** Provision a GSI on the cluster-state table keyed on `(status, opened_at)` and replace the scan with a paginated query:

  ```python
  active_clusters = []
  last_evaluated_key = None
  while True:
      kwargs = dict(
          IndexName="status-opened-at-index",
          KeyConditionExpression=Key("status").eq("open_for_review"),
      )
      if last_evaluated_key:
          kwargs["ExclusiveStartKey"] = last_evaluated_key
      response = cluster_table.query(**kwargs)
      active_clusters.extend(response.get("Items", []))
      last_evaluated_key = response.get("LastEvaluatedKey")
      if not last_evaluated_key:
          break

  for item in active_clusters:
      existing = _undecimalize(item)
      ...
  ```

  Or, if the demo wants to avoid prerequisite GSI provisioning, wrap the scan in a `LastEvaluatedKey` loop with a comment that production must use the GSI. Either way, the Setup section's table-schema notes should mention the GSI.

---

### Finding 2: `check_recent_dismissal` uses `table.scan` without pagination; silently misses suppression rules past the 1MB response limit

- **Severity:** WARNING
- **Location:** `chapter03.10-python-example.md`, `check_recent_dismissal` (Step 8)
- **Description:** The suppression-rule lookup is:

  ```python
  response = suppression_table.scan()
  for item in response.get("Items", []):
      rule = _undecimalize(item)
      if rule.get("valid_until", "") < now_iso:
          continue
      if rule.get("reason_class") != reason_class:
          continue
      ...
  ```

  Same root cause as Finding 1: a `scan` without a `LastEvaluatedKey` pagination loop drops any rule past the 1MB response cap. Suppression rules accumulate over years; the recipe's prose calls out that "after a few years of operation, the suppression-rule store can contain thousands of entries, some still valid, some stale, some legitimately superseded." Once thousands of rules are present, the scan truncates and the recently-dismissed-pattern check silently fails for every rule past the cap. A flagged proto-cluster that exactly matches a still-valid suppression rule (because, for example, last week's coding-mapping change at four facilities is still rolling out) opens as a fresh cluster instead of being suppressed. The surveillance team gets paged on the same false-alarm pattern they already adjudicated.

  The fix shape is identical to Finding 1: a GSI keyed on `(reason_class, valid_until)` so the time-window scan becomes a key condition, or a pagination loop on the scan with a comment that production must index. The TTL attribute on the rule (`"ttl": int(valid_until_dt.timestamp())`) is correctly set, so DynamoDB will eventually expire the rules, but the per-call lookup must still be paginated.

- **How to fix:** Either provision a GSI keyed on `(reason_class, valid_until)`:

  ```python
  response = suppression_table.query(
      IndexName="reason-class-valid-until-index",
      KeyConditionExpression=(
          Key("reason_class").eq(reason_class)
          & Key("valid_until").gte(now_iso)
      ),
  )
  ```

  Or, at minimum, wrap the scan in a pagination loop:

  ```python
  rules = []
  last_evaluated_key = None
  while True:
      kwargs = {"FilterExpression": Attr("reason_class").eq(reason_class)
                                    & Attr("valid_until").gte(now_iso)}
      if last_evaluated_key:
          kwargs["ExclusiveStartKey"] = last_evaluated_key
      response = suppression_table.scan(**kwargs)
      rules.extend(response.get("Items", []))
      last_evaluated_key = response.get("LastEvaluatedKey")
      if not last_evaluated_key:
          break
  ```

  And add the GSI to the Setup section's table-schema notes.

---

### Finding 3: Multi-source fusion candidate-to-signal matching uses raw `geo_id` string equality; cross-source concordance never fires because clinical, wastewater, and absenteeism signals have different geography types and IDs

- **Severity:** WARNING
- **Location:** `chapter03.10-python-example.md`, `candidate_geo_windows` and `max_score_for` (Step 7)
- **Description:** `candidate_geo_windows` builds candidates keyed on `(geo_type, geo_id, syndrome)` from each source's results. Clinical candidates take their `geo_id` from the cell key (`census_tract`, `36055-001100`). Wastewater candidates take it from the sewershed (`sewershed`, `ROC-CENTRAL`). Absenteeism candidates take it from the school district (`school_district`, `ROC-CITY`). Each source's signal lives at a different geography level with a different identifier scheme.

  `max_score_for` then matches a candidate to per-source results by direct string comparison:

  ```python
  for result in results:
      ...
      cell = result.get("cell")
      if cell and cell.get("geo_id") == candidate["geo_id"]:
          ...
      elif result.get("sewershed") == candidate["geo_id"]:
          ...
      elif result.get("district") == candidate["geo_id"]:
          ...
  ```

  And the fusion driver then computes:

  ```python
  clinical_signal     = max_score_for(clinical_results, candidate)
  wastewater_signal   = max_score_for(auxiliary_results, candidate, "wastewater")
  absenteeism_signal  = max_score_for(auxiliary_results, candidate, "school_absenteeism")
  ...
  composite = (
      FUSION_WEIGHTS["clinical"]    * clinical_signal
    + FUSION_WEIGHTS["wastewater"]  * wastewater_signal
    + ...
  )
  concordance_bonus = (
      count_concordant_sources(
          clinical_signal, wastewater_signal,
          pharmacy_signal, absenteeism_signal,
          threshold=CONCORDANCE_SIGNAL_THRESHOLD,
      )
      * CONCORDANCE_BONUS_PER_SOURCE
  )
  ```

  The string-equality match means a clinical candidate with `geo_id="36055-001100"` only ever pulls a non-zero `clinical_signal` from cells whose `geo_id` is also `"36055-001100"`; `wastewater_signal` looks for results with `sewershed="36055-001100"`, which doesn't exist; `absenteeism_signal` looks for `district="36055-001100"`, which also doesn't exist. So the clinical candidate's wastewater_signal and absenteeism_signal are both zero. Symmetrically, a wastewater candidate with `geo_id="ROC-CENTRAL"` only ever matches wastewater results; the clinical_signal lookup checks `cell.get("geo_id") == "ROC-CENTRAL"`, which is never true for a census-tract clinical cell.

  The downstream effect is structural: no candidate in the demo ever has more than one non-zero source signal. `concordant_source_count` is always 1 (the originating source). The concordance bonus is `1 * CONCORDANCE_BONUS_PER_SOURCE = 0.05` for every candidate, regardless of whether other sources are also signaling in the same geographic neighborhood. The headline value of multi-source fusion that the recipe spends pages establishing ("Multi-source fusion is the biggest leverage point I've seen in the last decade") never materializes in the demo flow.

  A reader who runs the demo and inspects the cluster's `multi_source_concordance` field sees `"concordant_sources": 1` for every cluster. They might reasonably conclude either that the demo data is too sparse to demonstrate concordance (which is wrong; the demo includes both clinical encounters in the affected tracts and synthetic wastewater plus absenteeism data for the corresponding sewershed and district) or that the fusion logic is correct but tuned to require more concordance than the demo produces. The actual problem is that the demo data does include concordant signals; the matching logic just can't see them because the geo_id strings differ across source types.

  Production handles this through the spatial-relationships layer the recipe describes: "Production runs spatial proximity testing in PostGIS to identify cells whose geographies share boundaries or are within a distance threshold." The teaching example doesn't have to ship a full PostGIS implementation, but it does need at least a geo_id-to-related-geographies mapping so that a clinical candidate at census tract `36055-001100` can pull the wastewater signal from sewershed `ROC-CENTRAL` (because that tract drains into that sewershed) and the absenteeism signal from school district `ROC-CITY` (because that tract is in that district). The synthetic geography in `_DEMO_GEOGRAPHY` already encodes these relationships (every demo tract has `sewershed="ROC-CENTRAL"` and `school_district="ROC-CITY"`), so the data is there; the fusion code just doesn't use it.

  Pedagogical impact is substantial because multi-source fusion is the chapter-level teaching point, and the demo as written produces clusters that look the same as a single-source detector would produce.

- **How to fix:** Pass the geographic-relationship mapping (already stored in the geocode cache as `admin_geographies`) into the fusion layer and make `max_score_for` resolve cross-source matches through it. Sketch:

  ```python
  def candidate_geo_windows(clinical_results, auxiliary_results):
      candidates = {}
      for result in clinical_results:
          if not result.get("flagged"): continue
          cell = result.get("cell")
          if cell:
              # Look up the related geographies for this tract.
              related = lookup_related_geographies(cell["geo_type"], cell["geo_id"])
              key = (cell["geo_type"], cell["geo_id"], cell["syndrome"])
              candidates.setdefault(key, {
                  "geo_type":         cell["geo_type"],
                  "geo_id":           cell["geo_id"],
                  "syndrome":         cell["syndrome"],
                  "syndrome_class":   classify_syndrome_class(cell["syndrome"]),
                  "geo_class":        classify_geo_class(cell["geo_type"]),
                  "related_sewershed":      related.get("sewershed"),
                  "related_school_district": related.get("school_district"),
              })
      ...

  def max_score_for(results, candidate, detector=None):
      max_score = 0.0
      for result in results:
          if detector and result.get("detector") != detector: continue
          if not result.get("flagged"): continue
          cell = result.get("cell")
          if cell and cell.get("geo_id") == candidate["geo_id"]:
              ...
          elif result.get("sewershed") == candidate.get("related_sewershed"):
              ...
          elif result.get("district") == candidate.get("related_school_district"):
              ...
      return max_score
  ```

  Document the simplification: production runs PostGIS spatial-proximity queries; the demo uses a static admin-geography crosswalk that's the same crosswalk the geocoder produces.

---

### Finding 4: Several unused imports, including a logistic-regression import the Heads-up references but the file never trains

- **Severity:** NOTE
- **Location:** `chapter03.10-python-example.md`, imports block at the top of Configuration
- **Description:** The imports block declares modules and classes the file never exercises:

  - `import io` — never used
  - `from datetime import ..., date` — `date` never used directly (the file uses `datetime.now(...).date()` and `today.date()` method calls but never the bare `date` constructor or class reference)
  - `from typing import Optional` — never used (no type hints)
  - `from sklearn.linear_model import LogisticRegression` — never instantiated. The Heads-up section says: "We train a logistic regression on a small synthetic feature matrix at the bottom of the file so the scoring path runs end-to-end without a deployed endpoint." But there is no training code at the bottom of the file; the demo's `__main__` block just calls `seed_demo_history()` and `run_outbreak_detection_pipeline(encounters, ...)`. The logistic regression is imported and never trained, never used.
  - `from sklearn.isotonic import IsotonicRegression` — never instantiated. No calibration model is fit anywhere in the file (the recipe doesn't have a calibration step in the same shape as Recipes 3.7-3.9, but the import is left over from those siblings).

  Same lint-cleanliness pattern flagged in Recipes 3.7, 3.8, and 3.9. The bigger concern here is the contradiction between the Heads-up text ("We train a logistic regression...at the bottom of the file") and the actual file: a reader looking for the training code will not find it, and may spend time hunting for what they think they missed. Either remove the import and update the Heads-up to drop the logistic-regression sentence, or implement the small training stub the Heads-up claims.

- **How to fix:** Remove all five unused imports. Update the Heads-up bullet about the in-process scikit-learn model to match what the file actually contains:

  ```
  - **The model in this example is a tiny in-process heuristic.** Real deployments host the syndrome classifier behind a SageMaker real-time endpoint plus the regression-based detector as a SageMaker Processing job (daily cadence). For teaching, we use a keyword-based fallback inside `score_via_syndrome_classifier` so the scoring path runs end-to-end without a deployed endpoint. The production path's boto3 call is the body of `score_via_syndrome_classifier`'s `try` block.
  ```

  Note: while we're here, the Heads-up reference to a `score_via_sagemaker_endpoint` function should be updated to `score_via_syndrome_classifier` (the actual function name in the file). See Finding 11.

---

### Finding 5: Module logger has no handler configured; structured logs drop silently when running directly

- **Severity:** NOTE
- **Location:** `chapter03.10-python-example.md`, Configuration block (logger setup)
- **Description:** Same pattern flagged in earlier Chapter 3 reviews. The module-level logger is configured with a level but no handler:

  ```python
  logger = logging.getLogger(__name__)
  logger.setLevel(logging.INFO)
  ```

  Without `logging.basicConfig` or an attached handler, `logger.info`, `logger.warning`, and `logger.debug` calls (Comprehend Medical failed, syndrome classifier endpoint unavailable, Bedrock invocation failed, Timestream write fallback, baseline S3 write skipped, training label S3 write skipped, cluster suppressed, outcome for unknown cluster, GLM fit failed, eventbridge publish failed, metric emit failed) do not reach the console when the file runs as `__main__`. The print-based narration in `run_outbreak_detection_pipeline` keeps step-by-step output visible, but the diagnostic logs that would help a reader trace anomalies do not appear. This matters more here than in some earlier recipes because the demo deliberately runs many `try/except` blocks to handle missing AWS resources gracefully; the diagnostic value of those `except` branches is precisely the log line that names what fell through.

- **How to fix:** Add one line near the top of Configuration:

  ```python
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  ```

  Document with a one-liner: "Visible when running this file directly; Lambda configures its own root handler and this becomes a no-op there."

---

### Finding 6: S3 `put_object` calls set `ServerSideEncryption="aws:kms"` without `SSEKMSKeyId`

- **Severity:** NOTE
- **Location:** `chapter03.10-python-example.md`, three call sites: `ingest_encounter` (raw events lake), `compute_baselines` (baseline store), `on_investigator_action` (training labels)
- **Description:** All three S3 writes request KMS encryption without specifying a customer-managed key:

  ```python
  s3_client.put_object(
      Bucket=RAW_EVENTS_BUCKET,
      Key=...,
      Body=json.dumps(parsed, default=str).encode("utf-8"),
      ServerSideEncryption="aws:kms",
  )
  ```

  When `ServerSideEncryption="aws:kms"` is set without `SSEKMSKeyId`, S3 encrypts with the AWS-managed default key (`aws/s3` alias). For PHI, customer-managed keys are required: rotation on a documented schedule, scoping grants per bucket, auditing `kms:Decrypt` per principal via CloudTrail, and the ability to disable the key to revoke access immediately. The AWS-managed default cannot be disabled, scoped, or revoked.

  Surveillance is one of the more sensitive PHI-handling pipelines in the cookbook: the raw events lake holds encounter detail across the entire population of a state including chief complaints, patient addresses, and demographics; the baseline store holds historical count series that can be re-identifying in small geographies; the training-labels bucket holds adjudicated cluster outcomes. The Gap to Production section in this file explicitly says "Every data-at-rest store ... is encrypted with customer-managed KMS keys scoped by role." The example doesn't demonstrate the pattern the prose requires. Same finding pattern as Recipes 3.7, 3.8, and 3.9; a coordinated chapter-wide fix plus a STYLE-GUIDE.md addition would be more durable than re-litigating this once per recipe.

- **How to fix:** Add KMS key ARN constants and pass them through:

  ```python
  RAW_EVENTS_CMK_ARN       = "arn:aws:kms:REGION:ACCOUNT:key/..."
  BASELINE_STORE_CMK_ARN   = "arn:aws:kms:REGION:ACCOUNT:key/..."
  TRAINING_LABELS_CMK_ARN  = "arn:aws:kms:REGION:ACCOUNT:key/..."

  s3_client.put_object(
      Bucket=RAW_EVENTS_BUCKET,
      Key=...,
      Body=...,
      ServerSideEncryption="aws:kms",
      SSEKMSKeyId=RAW_EVENTS_CMK_ARN,
  )
  ```

---

### Finding 7: `eventbridge.put_events` response not checked for `FailedEntryCount`

- **Severity:** NOTE
- **Location:** `chapter03.10-python-example.md`, multiple call sites: `run_detector_bank`, `build_clusters` (ClusterOpened), `on_investigator_action` (ExternalReportingTriggered, CrossJurisdictionalNotification, ResponseCoordinationInitiated, ClusterClosed)
- **Description:** Every `put_events` call discards the response. EventBridge's `put_events` returns `FailedEntryCount` plus per-entry `ErrorCode` and `ErrorMessage`. A failed publish is silent if the response is not inspected: upstream code thinks the event went out, downstream subscribers never see it. Same finding pattern as Recipes 3.7, 3.8, and 3.9.

  The consequence in a public-health surveillance pipeline ranges from "the surveillance UI back end never gets the new cluster" (failed `ClusterOpened`) to "the eCR / NEDSS / NORS connector never gets the confirmed-outbreak handoff and the notifiable-condition reporting clock doesn't start" (failed `ExternalReportingTriggered`) to "neighboring jurisdictions are never notified of the cross-boundary cluster" (failed `CrossJurisdictionalNotification`) to "the response coordination workflow never receives the confirmed outbreak" (failed `ResponseCoordinationInitiated`). All silent. The notifiable-condition reporting failure is particularly serious because state public health statutes typically specify reporting timelines (immediate, within 24 hours, within a week depending on the condition); a silent EventBridge failure on `ExternalReportingTriggered` means the reporting clock never starts ticking, and the program is technically out of statutory compliance even though the surveillance team has done its part.

- **How to fix:** Wrap call sites in a small helper that inspects the response:

  ```python
  def _put_events_checked(entries, *, source):
      response = eventbridge.put_events(Entries=entries)
      if response.get("FailedEntryCount", 0) > 0:
          for entry in response.get("Entries", []):
              if entry.get("ErrorCode"):
                  logger.error("eventbridge entry failed", extra={
                      "source":        source,
                      "error_code":    entry["ErrorCode"],
                      "error_message": entry.get("ErrorMessage"),
                  })
          _emit_metric(f"EventBridgeFailedEntries_{source}",
                       response["FailedEntryCount"])
      return response
  ```

  Replace the direct `eventbridge.put_events(Entries=[...])` call sites with `_put_events_checked([...], source="...")`.

---

### Finding 8: Bedrock model ID hardcoded to a two-generations-old Claude version

- **Severity:** NOTE
- **Location:** `chapter03.10-python-example.md`, Configuration block
- **Description:** The Configuration pins:

  ```python
  BEDROCK_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"
  ```

  The main recipe's TODO calls out the need to "confirm the current set of HIPAA-eligible Bedrock foundation models." The Python pins to one specific version without surfacing the verification need. By the time of writing (2026), Claude 3 Sonnet is two generations old; Claude 3.5 Sonnet, 3.5 Haiku, and 3.7 Sonnet have all shipped on Bedrock with better instruction-following for the kind of structured-output prompt this recipe uses (a constrained narrative that must end with a specific phrase and must not assert specific pathogens beyond what the lab and genomic context indicate). Same finding as Recipes 3.7, 3.8, and 3.9.

- **How to fix:** Load from environment with a recent default and document the verification path:

  ```python
  import os
  # HIPAA-eligible Bedrock model ID. Verify availability under the AWS BAA
  # for your deployment region. The Bedrock console's model-access page is
  # the source of truth; the AWS HIPAA Eligible Services Reference confirms
  # BAA coverage.
  BEDROCK_MODEL_ID = os.environ.get(
      "BEDROCK_MODEL_ID",
      "anthropic.claude-3-5-sonnet-20241022-v2:0",
  )
  ```

---

### Finding 9: OpenSearch indexing named in Setup permissions but never implemented in code

- **Severity:** NOTE
- **Location:** `chapter03.10-python-example.md`, Setup section vs full pipeline
- **Description:** The Setup section explicitly enumerates OpenSearch permissions:

  > The OpenSearch domain policy must allow the executing role to `es:ESHttpPost` and `es:ESHttpPut` on the `cluster-index`, `line-list-search`, and `detector-results` indices

  And the main recipe pseudocode shows OpenSearch.Index calls in Steps 6, 8, and 9:

  ```
  OpenSearch.Index("detector-results", result)
  ...
  OpenSearch.Index("cluster-index", cluster)
  ...
  OpenSearch.Index("cluster-index", cluster)
  ```

  But the Python file never imports `opensearchpy` and never instantiates an OpenSearch client. `run_detector_bank`, `build_clusters`, and `on_investigator_action` all write only to DynamoDB (and EventBridge). The audit-index value-add the recipe relies on (governance queries, ad-hoc surveillance review, cross-cluster analytics, the "show me every fever-respiratory ED visit in this ZIP in the last 14 days" investigator query) is not demonstrated. A reader looking to understand "where does the line-list search live" or "how does the surveillance team's ad-hoc query interface query the cluster archive" sees the IAM permissions and the recipe pseudocode but no code path that actually writes there. Same finding pattern as Recipe 3.8 Finding 10.

- **How to fix:** Either add a small OpenSearch indexing helper called from the same sites that write to DynamoDB:

  ```python
  from opensearchpy import OpenSearch, RequestsHttpConnection

  OPENSEARCH_HOST = "search-...es.amazonaws.com"

  def _index_to_opensearch(index_name, document_id, document):
      """Index a document into OpenSearch for audit and ad-hoc queries.
      Wrap in try/except; index failures are logged and metric'd but
      do not block the upstream DynamoDB write."""
      try:
          client = OpenSearch(
              hosts=[{"host": OPENSEARCH_HOST, "port": 443}],
              http_auth=...,   # AWS4Auth in production
              use_ssl=True,
              connection_class=RequestsHttpConnection,
          )
          client.index(index=index_name, id=document_id, body=document)
      except Exception as e:
          logger.warning("opensearch index failed", extra={
              "index":       index_name,
              "document_id": document_id,
              "error":       str(e),
          })
          _emit_metric(f"OpenSearchIndexFailed_{index_name}", 1)
  ```

  And call from `run_detector_bank` (per detector result), `build_clusters` (per opened cluster), and `on_investigator_action` (per cluster close). Or remove the OpenSearch references from the Setup permissions and the recipe pseudocode if they are out of teaching scope; the inconsistency is what trips readers up.

---

### Finding 10: Address-geocode-cache items written without a TTL attribute despite the prose recommending TTL-based expiration

- **Severity:** NOTE
- **Location:** `chapter03.10-python-example.md`, `geocode_and_stratify` (Step 2) vs the prose immediately after Step 2
- **Description:** The geocode-cache write is:

  ```python
  cache_table.put_item(Item=_decimalize({
      "address_hash":      address_hash,
      "coords":            coords,
      "admin_geographies": admin_geographies,
      "geocoded_at":       datetime.now(timezone.utc).isoformat(),
  }))
  ```

  And the prose immediately after the Step 2 code block says:

  > Patient addresses change. Census tract boundaries change at the decennial census and occasionally between censuses. ... The cache is therefore not "set once and forget"; entries should expire on a configurable TTL (typical: 90-180 days) and the system should handle the case where a patient's residence has moved between encounters.

  TTL on DynamoDB requires an attribute holding a Unix epoch timestamp; without one, the cache accumulates entries indefinitely. A patient who moves from ZIP `14620` to ZIP `14622` between encounters will, in the demo as written, continue to be matched against the cached old-address geographies for every subsequent encounter; the cache never invalidates. Same pattern as Recipe 3.8 Finding 11 (TTL named in setup but not set on records).

  Adding the TTL attribute is one line; not adding it contradicts the prose that the reader will read in the same step.

- **How to fix:** Add a TTL attribute when the record is written:

  ```python
  cache_ttl_days = 120
  expiration_epoch = int(
      (datetime.now(timezone.utc) + timedelta(days=cache_ttl_days)).timestamp()
  )
  cache_table.put_item(Item=_decimalize({
      "address_hash":      address_hash,
      "coords":            coords,
      "admin_geographies": admin_geographies,
      "geocoded_at":       datetime.now(timezone.utc).isoformat(),
      "expires_at":        expiration_epoch,
  }))
  ```

  Document the chosen window with a one-liner that ties it to the prose. The Setup section's table-schema notes should mention that the cache table has TTL configured on the `expires_at` attribute.

---

### Finding 11: Heads-up references a `score_via_sagemaker_endpoint` function that doesn't exist in the file

- **Severity:** NOTE
- **Location:** `chapter03.10-python-example.md`, Heads-up bullet about the in-process model vs Step 3 (`score_via_syndrome_classifier`)
- **Description:** The Heads-up says:

  > The `score_via_sagemaker_endpoint` function shows the production-shape boto3 call.

  No function named `score_via_sagemaker_endpoint` exists in the file. The actual function is `score_via_syndrome_classifier`, which does show the production-shape boto3 call (`sagemaker_runtime.invoke_endpoint(...)` against `SYNDROME_CLASSIFIER_ENDPOINT`) inside its `try` block, with a keyword-heuristic fallback in the `except` branch. The Heads-up reference looks like it was copy-pasted from Recipe 3.7's or 3.8's Heads-up (both of which have a function literally called `score_via_sagemaker_endpoint`).

  A reader hunting for the named function will not find it and may waste time before realizing the Heads-up is wrong. This is a low-stakes editorial inconsistency but it's the kind of thing readers encounter immediately, before they've built familiarity with the file's structure.

- **How to fix:** Update the Heads-up bullet to name the actual function:

  ```
  ...The `score_via_syndrome_classifier` function shows the production-shape
  boto3 call (`sagemaker_runtime.invoke_endpoint`); the demo path falls
  through to a keyword-heuristic fallback when the endpoint is not
  available.
  ```

---

### Finding 12: `aggregate_adjacent_flags` uses naive county-FIPS-prefix string slicing for spatial grouping

- **Severity:** NOTE
- **Location:** `chapter03.10-python-example.md`, `aggregate_adjacent_flags` (Step 8)
- **Description:** The proto-cluster grouping uses a string-slice heuristic to derive a county-equivalent key from the geo_id:

  ```python
  county_key = (candidate["geo_id"][:5]
                if candidate["geo_type"] == "census_tract"
                else candidate["geo_id"])
  group_key = (county_key, candidate["syndrome"])
  groups[group_key].append(signal)
  ```

  This works in the demo because the synthetic census-tract IDs are `36055-001100`-style and the first 5 characters happen to be the county FIPS code. In real census-tract identifiers the FIPS code is a 5-digit prefix (state FIPS + county FIPS), so the heuristic happens to be correct for U.S. tracts. But the implementation is fragile in three ways. First, the format check is purely on `geo_type == "census_tract"`; if a different geography type is later added with a similar-looking ID, the slice does the wrong thing silently. Second, sewersheds, school districts, and hospital service areas use the entire `geo_id` as the county key, which means a sewershed proto-cluster never groups with a census-tract proto-cluster in the same county even though the recipe's "spatial proximity" framing implies they should. Third, the comment in the function ("The teaching example groups by syndrome and county; a real spatial proximity check is what scales") names the production answer but the code shape doesn't expose where the production fix would land.

  Combined with Finding 3, this means the Step 7 candidate construction and the Step 8 cluster aggregation both rely on string equality rather than geographic relationships, and a reader doesn't get a working example of either pattern.

- **How to fix:** Either factor the county-key derivation into a small named helper that takes the geo_type and geo_id and consults the same admin-geography crosswalk used elsewhere:

  ```python
  def derive_county_for_grouping(geo_type, geo_id):
      """Return the county FIPS this geography belongs to, for cluster grouping.

      Production runs a spatial join in PostGIS. The teaching example uses the
      synthetic geography crosswalk; for census tracts the county FIPS is the
      5-character prefix of the tract ID by U.S. Census convention.
      """
      if geo_type == "census_tract":
          return geo_id.split("-")[0]
      # For sewershed, school_district, hospital_service_area, look up the
      # county from the synthetic crosswalk.
      return _DEMO_GEOGRAPHY_TO_COUNTY.get((geo_type, geo_id), geo_id)
  ```

  Or, document the simplification explicitly with an inline comment that names the FIPS-prefix assumption and the production-shape fix. Either way, the function should not silently return the entire geo_id for non-tract types.

---

### Finding 13: `find_existing_open_cluster` compares geographies by `id` only (not by `(type, id)` tuple)

- **Severity:** NOTE
- **Location:** `chapter03.10-python-example.md`, `find_existing_open_cluster` (Step 8)
- **Description:** The cluster-equality check is:

  ```python
  geo_ids = sorted([g["id"] for g in proto["geographies"]])
  syndromes = sorted(proto["syndromes"])
  ...
  for item in response.get("Items", []):
      existing = _undecimalize(item)
      existing_geo_ids = sorted([g["id"] for g in existing.get("geographies", [])])
      existing_syndromes = sorted(existing.get("syndromes", []))
      if (existing_geo_ids == geo_ids
              and existing_syndromes == syndromes):
          return existing
  ```

  The comparison strips the `type` field from each geography dict and compares only the `id` strings. If two clusters happen to have geographies with the same set of `id` values but different `type` values (a sewershed named `ROC-CENTRAL` and, hypothetically, a hospital service area also named `ROC-CENTRAL`), the equality check would match them. Identifier collisions across geography types are uncommon but not impossible: census tract IDs and ZCTA IDs are disjoint by Census convention, but operationally-defined geographies (sewersheds, school districts, hospital service areas) often use organization-specific identifier schemes that don't have global uniqueness guarantees.

  The fix is straightforward: include the type in the comparison key.

- **How to fix:**

  ```python
  geo_keys = sorted([(g["type"], g["id"]) for g in proto["geographies"]])
  syndromes = sorted(proto["syndromes"])
  ...
  for item in response.get("Items", []):
      existing = _undecimalize(item)
      existing_geo_keys = sorted([(g["type"], g["id"])
                                   for g in existing.get("geographies", [])])
      existing_syndromes = sorted(existing.get("syndromes", []))
      if (existing_geo_keys == geo_keys
              and existing_syndromes == syndromes):
          return existing
  ```

---

## Pseudocode-to-Python Consistency

| Step | Pseudocode | Python | Match |
|------|-----------|--------|-------|
| 1 | `ingest_encounter` | `ingest_encounter` + `parse_by_source` + `pseudonymize` + `bucket_age` + `generate_event_id` | Yes; pseudonymization-at-ingest pattern preserved; raw-event lake write included |
| 2 | `geocode_and_stratify` | `geocode_and_stratify` + `geocode_with_amazon_location` + `query_postgis_for_admin_geographies` + `format_address` + `hash_address` | Mostly; geocode-cache TTL not set (Finding 10); production-shape SQL documented in `query_postgis_for_admin_geographies` docstring |
| 3 | `classify_syndrome` | `classify_syndrome` + `apply_icd_rules` + `call_comprehend_medical` + `apply_entity_rules` + `score_via_syndrome_classifier` + `apply_lab_rules` + `lookup_recent_lab_results` | Yes; multi-label classification preserved; Comprehend Medical and SageMaker endpoint paths both stubbed with documented fallbacks |
| 4 | `update_cell_counters` | `update_cell_counters` + `cell_keys_for` + `cell_partition_key` + `increment_cell` + `write_to_timestream` + `stratifications_for` | Yes; cell-key cardinality (geographies × stratifications × syndromes × windows) captured; Timestream write has in-memory fallback for the demo |
| 5 | `compute_baselines` | `compute_baselines` + `query_timestream_for_history` + `fit_negative_binomial_glm` + `predict_baseline_for_date` + `downscale_parent` + `get_parent_baseline_model` + `enumerate_active_cells` + `known_outbreak_dates` | Yes; cold-start fallback to parent-pooled baseline implemented; known-outbreak-dates exclusion is a stub but documented |
| 6 | `run_detector_bank` | `run_detector_bank` + `run_control_chart_detectors` + `run_farrington_flexible_detector` + `run_satscan_detectors` + `compute_cusum` + `compute_ewma` + `submit_satscan_batch_job` + `get_recent_counts` + `load_baseline_for_cell` | Yes; control charts, regression-based, and SaTScan all wired in parallel; SaTScan stub is honestly labeled |
| 7 | `run_auxiliary_and_fuse` | `run_auxiliary_and_fuse` + `run_wastewater_detector` + `run_absenteeism_detector` + `run_pharmacy_detector` + `candidate_geo_windows` + `max_score_for` + `count_concordant_sources` + `apply_fusion_calibration` + `classify_syndrome_class` + `classify_geo_class` | Mostly; cross-source string-equality matching breaks the concordance bonus (Finding 3) |
| 8 | `build_clusters` | `build_clusters` + `aggregate_adjacent_flags` + `find_existing_open_cluster` + `update_existing_cluster` + `check_recent_dismissal` + `log_suppression` + `line_list_build` + `line_list_summary` + `persist_line_list` + `sum_of_expected_for` + `summarize_demographics` + `build_geo_payload` + `lookup_lab_results_for_cases` + `lookup_genomic_clusters` + `build_cluster_narrative_prompt` + `parse_bedrock_response` + `invoke_bedrock_narrative` + `_emit_metric` + `generate_cluster_id` + `tier_from_composite` | Mostly; `find_existing_open_cluster` scan lacks pagination (Finding 1); `check_recent_dismissal` scan lacks pagination (Finding 2); cluster geography comparison strips type (Finding 13); county-prefix grouping is fragile (Finding 12) |
| 9 | `on_investigator_action` | `on_investigator_action` + `initiate_external_reporting` + `notify_neighboring_jurisdictions` + `initiate_response_coordination` + `add_suppression_rule` + `cluster_feature_snapshot` | Yes; valid-outcome enumeration enforced; suppression rule added on dismissal; downstream eCR / cross-jurisdictional / response-coordination handoffs in place |

The nine-step framing in the prose lines up exactly with the nine code sections. The `run_outbreak_detection_pipeline` driver wires Steps 1-8 in sequence with print-based narration; Step 9 is documented as event-triggered and exposed as a standalone callable.

---

## AWS SDK Accuracy

- **DynamoDB resource API:** `Table.get_item`, `Table.put_item`, `Table.update_item`, `Table.scan` shapes are correct. `UpdateExpression` syntax correct. `ExpressionAttributeNames` and `ExpressionAttributeValues` used correctly for reserved words (`count`, `window`). TTL via epoch-int `ttl` attribute used in suppression rules. `find_existing_open_cluster` and `check_recent_dismissal` use `scan` without pagination (Findings 1 and 2); both should be GSI-backed `query` calls in production.
- **Kinesis:** `put_record(StreamName, Data, PartitionKey)` correct. `PartitionKey=surveillance_pid` provides per-patient ordering for repeat encounters, which matters for the syndrome classifier's recent-lab-result lookup.
- **Timestream Write:** `write_records` shape correct: `Dimensions` list of name/value pairs, `MeasureName`, `MeasureValue` (string), `MeasureValueType="BIGINT"`, `Time` (string milliseconds), `TimeUnit="MILLISECONDS"`. The demo wraps the call in `try/except` and falls back to an in-memory store when the database isn't available; this is honestly labeled.
- **Timestream Query:** `query_timestream_for_history` is a stub that reads from the in-memory store; production-shape SQL is documented in the docstring. No actual `timestream_query.query` call in the demo, so parameterized-query hygiene (Recipe 3.7 Finding 6, Recipe 3.8 Finding 6) doesn't apply.
- **S3:** `put_object` parameter names and key paths are correct. No leading slashes; sensible date partitioning (`source=...`, `year=...`, `month=...`, `day=...` in raw events; `baseline/...` in baseline store; `outcomes/year=.../month=...` in training labels). `SSEKMSKeyId` missing on all three write sites (Finding 6). `ContentType` not set (minor; S3 defaults are usually fine for JSON archives that Athena reads).
- **EventBridge:** `put_events` shape correct at all call sites. Entry fields all valid (`Source`, `DetailType`, `Detail`, `EventBusName`). `FailedEntryCount` not inspected (Finding 7).
- **CloudWatch:** `put_metric_data` shape correct. `Value=float(value)` matches the float requirement; `Unit="Count"` default is sensible. Metrics emitted at `ComprehendMedicalFailed`, `BedrockNarrativeFailed`, `ClustersOpened_<tier>`, `Suppressed_<reason>`, `Outcome_<outcome>`.
- **Comprehend Medical:** `detect_entities_v2(Text=...)` correct. Response parsing accesses `response.get("Entities", [])` then iterates entities with `Category` and `Text` fields; matches the API contract.
- **SageMaker Runtime:** `invoke_endpoint` shape correct in `score_via_syndrome_classifier`: `EndpointName`, `ContentType`, `Body` (encoded JSON). Response decoded via `response["Body"].read().decode("utf-8")` then `json.loads`; the format assumed (a dict with `predictions`) is endpoint-implementation-specific but documented.
- **Bedrock Runtime:** `invoke_model` shape correct. Anthropic Claude 3 messages-API request body (`anthropic_version`, `max_tokens`, `temperature`, `messages` with `role`/`content`) is the right shape for Bedrock-hosted Claude. Response parsing matches the response format. Model ID is two generations old (Finding 8). Bedrock-failure fallback to a structured-only summary is the right pattern for a non-critical narrative layer.
- **Amazon Location Service:** `search_place_index_for_text` shape correct in the documented production path; the demo uses a ZIP-to-coords stub with the production call commented out for reference.
- **Boto3 Config:** `Config(retries={"max_attempts": 5, "mode": "adaptive"})` parameter names current. Adaptive-mode rationale tied to ED-flush burstiness and morning-rounds lab spikes is well documented.

---

## DynamoDB Decimal Check

- `_to_decimal` routes through `Decimal(str(value)).quantize(Decimal(precision))`, avoiding binary-precision drift; default `"0.0001"` is sensible for composite scores in [0, 1] and standardized z-scores.
- `_decimalize` recursively walks dict and list trees converting `float -> Decimal`; strings, ints, bools, None pass through unchanged. Decimal inputs pass through unchanged because the `isinstance(obj, float)` check is false for Decimal.
- `_undecimalize` is the symmetric inverse, used at every state read site (`load_baseline_for_cell`, `find_existing_open_cluster`, `check_recent_dismissal`, `on_investigator_action`).
- `geocode_and_stratify` writes the cache record through `_decimalize` (the `coords` dict has float `lon`/`lat` that the recursive walker handles correctly).
- `compute_baselines` writes the cell-state update via explicit `_to_decimal` on `expected`, `upper_95`, `upper_99` values from `predict_baseline_for_date` (which returns floats).
- `update_existing_cluster` uses `_to_decimal(composite)` for the explicit single-field update value.
- `build_clusters` writes the cluster record through `_decimalize(cluster)` after the cluster dict has float `composite_score`, `relative_risk`, `excess`, and the nested `multi_source_concordance` and `lab_context` dicts with float values.
- `add_suppression_rule` writes through `_decimalize(rule)` (the `ttl` integer is preserved correctly through the walker; the `geographies` list of strings and `syndromes` list of strings pass through unchanged).
- `on_investigator_action` writes through `_decimalize(cluster)` after the cluster's float fields are preserved through the read-modify-write cycle.

Result: clean. The recursive walker handles the nested dict structures (multi-source concordance, lab context, demographic breakdown, geo visualization, line list summary) correctly. The Decimal precision-vs-routing-threshold framing in the Heads-up names the operational concern explicitly: "a baseline upper-99 of `5.9999999999` from float drift, compared against an observed count of `6` for a tier-1 cut, produces inconsistent flagging today and might produce different results tomorrow if the threshold moves."

---

## S3 Key Check

Keys inspected:

- `f"source={source_id}/year={obs_at[:4]}/month={obs_at[5:7]}/day={obs_at[8:10]}/{canonical['event_id']}.json"` (raw events lake, in `ingest_encounter`)
- `f"baseline/{cell['geo_type']}/{cell['geo_id']}/{cell['strat']}/{cell['syndrome']}/{reference_date.isoformat()}.json"` (baseline store, in `compute_baselines`)
- `f"outcomes/year={cluster['outcome_at'][:4]}/month={cluster['outcome_at'][5:7]}/{label_record['label_id']}.json"` (training labels, in `on_investigator_action`)

Forward-slash partitioning, no leading slashes, no `s3://` scheme leakage. Athena and Glue can prune at the partition level for the raw events lake and the training labels. The baseline store key is hierarchical rather than partition-formatted, which is fine because baseline records are accessed by full path during the daily detector run rather than via partition pruning. Pass.

---

## Healthcare-Specific Requirements

- **PHI logging discipline.** Logger comment names encounter payloads, chief-complaint text, line lists, lab results, and Bedrock prompts as PHI: "Log structural metadata only. Never log full encounter payloads with patient identifiers, full chief-complaint text, full line lists, or Bedrock prompts in application logs." Logger calls in the example respect this; nothing dumps full payloads or feature vectors. The `cluster suppressed` log emits geography IDs and syndrome names (aggregate; not per-patient). Consistent with the comment.
- **Synthetic data labeling.** Heads-up section names every category of identifier as synthetic (patient identifiers, facility identifiers, ZIP codes, census tracts, sewersheds, school districts, addresses, chief-complaint text). The synthetic geography (`_DEMO_GEOGRAPHY`), synthetic wastewater (`_DEMO_WASTEWATER`), and synthetic absenteeism (`_DEMO_ABSENTEEISM`) all use obviously synthetic IDs (`36055-001100`, `ROC-CENTRAL`, `ROC-CITY`).
- **BAA / HIPAA context.** All services used (Kinesis, Lambda, DynamoDB, Aurora PostGIS, Timestream, OpenSearch, S3, EventBridge, SageMaker, Bedrock, Comprehend Medical, Amazon Location Service, CloudWatch) are HIPAA-eligible under the AWS BAA. The recipe TODOs point to verifying current Bedrock model HIPAA eligibility, current Timestream HIPAA eligibility, and current Neptune HIPAA eligibility.
- **Pseudonymization-at-ingest.** Critical for the privacy-by-design architecture the recipe describes: surveillance analytic data is pseudonymized at ingest; the clinical patient identifier stays in the case-detail store, accessed only when an investigator opens a cluster under appropriate authority. The `pseudonymize(patient_identifier)` function uses a deterministic hash; production uses a keyed HMAC with the key in KMS / Secrets Manager (documented in the docstring). Consistent with the recipe's "PHI lives in a separate, tightly controlled case-detail store" framing.
- **Public health authority.** The Heads-up explicitly says "Public health authority is not simulated here. ... In production, the surveillance program must operate under a documented and current legal authority before the technology runs against PHI; coordinate with the state public health legal team before deployment." Correctly placed in prose rather than code; the legal authority isn't a technology concern.
- **Suppressed-cell rules.** The recipe spends substantial prose on the requirement that public-facing dashboards must not publish counts below the jurisdiction's suppression threshold (typically 5 or 10) at fine geographies. The Python implementation doesn't include a public-facing dashboard component; suppression in the code refers to the per-cluster suppression-rule mechanism. The two senses of "suppression" are different and the prose is clear about which one is in scope.
- **Multi-source fusion.** Architecturally captured (Step 7) but the cross-source matching breaks because of the geo_id string-equality issue (Finding 3). The recipe makes multi-source fusion the headline value-add; the demo as written undermines that teaching point.
- **Calibration discipline.** The `apply_fusion_calibration` function is a stub that clips to [0, 1]; production fits per-cohort calibration curves on labeled historical adjudications. Less central than calibration in Recipes 3.7-3.9 because the surveillance program's primary output is a cluster candidate rather than a calibrated probability; the tier mapping (`tier_from_composite`) is the operational analog.
- **Tier mapping.** Cohort-stratified thresholds via `TIER_THRESHOLDS["DEFAULT"]`; `tier_from_composite` looks up per-cohort with default fallback. Recipe requires this; implementation matches.
- **Suppression.** Two documented cases (matches existing open cluster, matches recent dismissal) implemented in `find_existing_open_cluster` and `check_recent_dismissal`. Both have pagination bugs (Findings 1 and 2). Suppression-rule TTL is correctly set on the rule via the `ttl` attribute.
- **Outcome label derivation.** `confirmed_outbreak` maps to label=1; everything else (false_alarm, indeterminate, continuing_investigation, hai_cluster, etc.) is treated uniformly as label=0. The recipe's Honest Take section names the label nuance: "indeterminate cases are not the same as false_alarm cases" and "the false-alarm rate during the early phase of a real outbreak ... means some 'false alarms' in the training data are actually real outbreaks that didn't get adjudicated as such." The prose acknowledges this; the code treats all non-confirmed outcomes uniformly. Acceptable teaching simplification given the recipe's explicit acknowledgement of the labeling problem.
- **Notifiable-condition reporting.** `NOTIFIABLE_CONDITIONS` set captures the major federal-and-state notifiable conditions; `initiate_external_reporting` is triggered when `outcome == "confirmed_outbreak"` and `condition` is in the set. The integration is stubbed (publishes to EventBridge with a generic event); production wires NEDSS / eCR / NORS / NHSN / NMI connectors per condition class.
- **Encryption at rest.** S3 missing `SSEKMSKeyId` on all write sites (Finding 6). Other store encryption is out of code scope; the prerequisites table names the customer-managed-key requirement for every PHI-bearing store.
- **Bedrock prompt constraint.** "You are not making an outbreak determination and you are not asserting a specific pathogen." Required end-phrase: "This is decision support; investigator judgment governs the public health response." `temperature=0.0`. Strong enough to keep the LLM in the decision-support lane and prevent specific-pathogen attribution that would create press-conference exposure if the cluster turns out to involve a different agent than the LLM speculated about.
- **Cross-jurisdictional coordination.** `notify_neighboring_jurisdictions` is triggered when `cluster.crosses_jurisdictions` is true. The integration is stubbed; production publishes to a federated notification bus with appropriate data-sharing constraints per the receiving jurisdiction's data use agreement.
- **Subgroup performance and equity audits.** Not implemented in Python; named as a continuous operational requirement in Gap to Production. Same posture as earlier Chapter 3 recipes.

---

## Comment Quality

The file's narrative comments consistently explain *why*, not just *what*. High-value examples:

- The Decimal-precision-vs-routing-threshold framing in the Heads-up: "For an outbreak-detection pipeline this matters operationally: a baseline upper-99 of `5.9999999999` from float drift, compared against an observed count of `6` for a tier-1 cut, produces inconsistent flagging today and might produce different results tomorrow if the threshold moves. The kind of bug that the surveillance team will track down for two days during their next rounding-mismatch crisis."
- Adaptive retry rationale tied to ingest burstiness: "Encounter ingest is bursty (EDs flush large batches at top-of-hour boundaries; lab results spike during morning rounds), and adaptive mode keeps burst windows from cascading into retry storms against Comprehend Medical and the syndrome classifier endpoint."
- Pseudonymization-at-ingest framing: "the analytic event uses surveillance_pid (pseudonym), not the clinical patient identifier. The clinical identifier stays in the case-detail store, accessed only when an investigator opens a cluster under appropriate authority."
- Cell-cardinality framing: "A single event might update dozens of cells. The cardinality is: geographies (5-6) x stratifications (3-4) x syndromes (1-3) x temporal windows (4). Production keeps the cell-counter table sized for the resulting volume; daily writes can run into hundreds of millions per state-level program."
- Baseline-contamination warning: "Baseline contamination is a real problem: if last winter's flu season is in the training window, the baseline absorbs it and the detector under-flags the next flu season. Production maintains a known-outbreak registry (curated by the surveillance team) and excludes those date windows during baseline fitting."
- Fusion-as-leverage framing: "The fusion layer is the biggest leverage point in the whole pipeline. Single-source detectors are noisy; multi-source concordance compresses noise and elevates real signals."
- Suppression-lifecycle rationale: "Suppression rules accumulate over years; without a periodic review and renewal process the rule store either over-suppresses (concealing real signals) or under-suppresses (re-flagging known patterns). Build the audit-and-renewal process into the program from the start."
- Label-derivation nuance: "'Confirmed_outbreak' as the positive class and everything else as negative is the simplest schema, but it hides nuance. 'Indeterminate' cases are not the same as 'false_alarm' cases ... noisy negative for retraining. Some surveillance programs use a three-class label (positive / negative / indeterminate) and exclude indeterminate cases from the supervised retraining set."
- Geocode-cache lifecycle: "Patient addresses change. Census tract boundaries change at the decennial census. ... The cache is therefore not 'set once and forget'; entries should expire on a configurable TTL."

Section headers (`## Step 1: Ingest a Clinical Encounter and Produce a Canonical Event`, ...) make cross-file navigation between recipe and companion easy.

---

## Logical Flow

Top-to-bottom progression:

1. Heads-up block (production gaps, decimal discipline, synthetic data labeling, in-process model, public-health-authority caveat)
2. Configuration and constants (resource names, syndromic categories, ICD-to-syndrome rules, entity-to-syndrome rules, pathogen-to-syndrome rules, detector thresholds, fusion weights, tier thresholds, window sizes)
3. Step 1: ingest and produce canonical event
4. Step 2: geocode and stratify
5. Step 3: classify syndrome
6. Step 4: update per-cell counters
7. Step 5: compute baselines
8. Step 6: detector bank
9. Step 7: auxiliary-source detectors and fusion
10. Step 8: cluster builder
11. Step 9: outcome capture and learning loop
12. Full pipeline driver (with synthetic baseline-history seeding and demo encounter batch)

Helper functions appear just before their first use. Prose between code blocks consistently calls out what's simplified for teaching, what's deferred to production, and why. Pseudocode-to-Python step boundaries are explicit.

---

## What Is Clean

- Recursive `_decimalize` and `_undecimalize` handle nested dict/list structures correctly across cell-state, cluster-state, geocode-cache, and suppression-rule writes
- Pseudonymization-at-ingest pattern preserved with a separate analytic identifier; the clinical patient identifier stays in the case-detail store accessed only by authorized investigators under specific authority
- Multi-resolution geocoding (census tract, ZCTA, county, school district, sewershed, hospital service area) wired through the synthetic Shapely lookup with a documented production-shape PostGIS query
- Multi-label syndrome classification combines ICD-10 patterns, Comprehend Medical NLP entity rules, custom SageMaker classifier predictions, and lab-confirmed pathogen promotion; the layered approach matches the recipe's framing
- Cell-counter cardinality (geographies × stratifications × syndromes × temporal windows) explicitly documented with the operational scale framing
- Baseline computation handles cold-start via parent-pooled fallback (`get_parent_baseline_model` plus `downscale_parent`) when per-cell history is insufficient
- Detector bank runs CUSUM, EWMA, Farrington Flexible, and SaTScan in parallel; the SaTScan stub is honestly labeled as a stand-in for the real binary
- Multi-source fusion architecture (clinical + wastewater + pharmacy + absenteeism with weighted combination plus concordance bonus) matches the recipe's framing, even if the cross-source matching breaks for the reasons in Finding 3
- Cluster builder assembles structured evidence (line list summary, demographic breakdown, lab context, genomic context, geo visualization) before invoking the Bedrock narrative; the LLM narrates structured data rather than generating facts
- Bedrock prompt is appropriately constrained: no outbreak determination, no specific pathogen assertion, required end-phrase, `temperature=0.0`, max_tokens=800
- Bedrock-failure fallback to a structured-only summary preserves cluster-builder functionality when Bedrock throttles or returns errors
- Outcome capture includes a defined enumeration of valid outcomes (`VALID_OUTCOMES`) with explicit downstream workflow handoffs for `confirmed_outbreak` (external reporting, cross-jurisdictional notification, response coordination)
- Suppression rules use DynamoDB TTL via the `ttl` attribute for automatic expiration after the validity window
- Adaptive retry config with documented rationale tied to ED-flush and morning-rounds burst patterns
- CloudWatch metrics emitted at `ComprehendMedicalFailed`, `BedrockNarrativeFailed`, `ClustersOpened_<tier>`, `Suppressed_<reason>`, `Outcome_<outcome>`
- Heads-up + Gap to Production sections together name every major production gap (HL7 v2 / FHIR ingestion, eCR / NEDSS / NHSN / NORS / NMI integration, NWSS wastewater integration, Aurora PostGIS, Timestream, SaTScan, Farrington Flexible, syndrome-classifier endpoint, Comprehend Medical, Feature Store, Model Monitor, surveillance UI, public-health authority, cross-jurisdictional coordination, geographic reference data, syndrome-taxonomy governance, idempotency, IAM scoping, VPC deployment, KMS, suppressed-cell rules, public-health governance, capacity-bounded prioritization, equity audits, public-communication infrastructure, notifiable-condition integration, suppression-rule lifecycle, multi-AZ DR, self-monitoring, decommissioning criteria, retention and legal hold, testing, cost awareness)

---

## Closing Assessment

The teaching content is substantial and the architectural fidelity to the main recipe is high. The nine pseudocode steps map onto Python functions, the multi-resolution geocoding and multi-label syndromic classification are surface-level simple but high-yield (which the recipe argues is exactly the right teaching emphasis), the cold-start fallback to parent-pooled baselines implements the recipe's framing, the detector bank's parallel-detector pattern matches the recipe's "ensemble surveillance" framing, the cluster-building-then-suppression-then-LLM-narrative sequencing in `build_clusters` matches the recipe, and the outcome-capture path closes the feedback loop with the external-reporting, cross-jurisdictional, and response-coordination handoffs the recipe describes. The Decimal discipline at the DynamoDB boundary is consistent with Recipes 3.7, 3.8, and 3.9's clean posture.

The three WARNINGs are operational-correctness gaps. Finding 1 (`find_existing_open_cluster` scan without pagination) is a high-impact silent-loss bug that produces fragmented clusters once the cluster-state table grows beyond 1MB; the recipe's stated scale (state-level surveillance covering 5-10 million population) hits this threshold quickly. Finding 2 (`check_recent_dismissal` scan without pagination) is the same root cause for the suppression-rule lookup, with the same silent-loss failure mode. Finding 3 (multi-source fusion never fires concordance bonus because of geo_id string-equality matching) is the most pedagogically consequential because multi-source fusion is the chapter-level teaching point and the demo as written produces clusters that look identical to single-source detection.

The ten NOTEs are editorial or hygiene items. Findings 4 (unused imports), 5 (logger no handler), 6 (S3 SSE without `SSEKMSKeyId`), 7 (EventBridge response not checked), 8 (older Bedrock model), 9 (OpenSearch in setup but not in code), and 11 (Heads-up references nonexistent function) repeat patterns flagged in earlier Chapter 2 and 3 reviews; the cookbook would benefit from a coordinated chapter-wide fix on the SSE-KMS and EventBridge-response patterns plus a STYLE-GUIDE.md addition. Findings 10 (geocode-cache TTL), 12 (county-prefix string slicing), and 13 (geography type stripped in cluster comparison) are smaller polish.

PASS verdict. The fixes are localized; a re-review pass would be quick.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** `find_existing_open_cluster` either uses a GSI-backed `query` keyed on `(status, opened_at)` or wraps the `scan` in a `LastEvaluatedKey` pagination loop. GSI documented in the Setup section's table-schema notes.
2. **(WARNING)** `check_recent_dismissal` either uses a GSI-backed `query` keyed on `(reason_class, valid_until)` or wraps the `scan` in a `LastEvaluatedKey` pagination loop with an `Attr`-based filter on `reason_class` and `valid_until`. GSI documented in Setup.
3. **(WARNING)** `candidate_geo_windows` and `max_score_for` resolve cross-source matches through the admin-geography crosswalk (already populated by `geocode_and_stratify`) rather than direct `geo_id` string equality. The teaching example produces at least one cluster in the demo with `concordant_source_count >= 2` to demonstrate that fusion actually works.
4. **(NOTE)** Unused imports (`io`, `date`, `Optional`, `LogisticRegression`, `IsotonicRegression`) removed; the Heads-up bullet about training a logistic regression updated to match what the file actually contains.
5. **(NOTE)** `logging.basicConfig(...)` added near the top of Configuration with a one-liner explaining when it's a no-op.
6. **(NOTE)** S3 `put_object` calls in `ingest_encounter`, `compute_baselines`, and `on_investigator_action` pass `SSEKMSKeyId` with documented customer-managed-key constants.
7. **(NOTE)** All `eventbridge.put_events` call sites inspect the response for `FailedEntryCount > 0`, ideally via a shared helper.
8. **(NOTE)** `BEDROCK_MODEL_ID` updated to a more recent Claude version (3.5 Sonnet v2 or newer) and either pinned with a verification comment or loaded from environment.
9. **(NOTE)** OpenSearch indexing implemented at the `run_detector_bank`, `build_clusters`, and `on_investigator_action` write sites, or removed from Setup and recipe pseudocode if out of teaching scope.
10. **(NOTE)** Geocode-cache items include an `expires_at` epoch attribute; cache TTL window documented in Setup's table-schema notes.
11. **(NOTE)** Heads-up bullet updated to reference `score_via_syndrome_classifier` (the actual function name) rather than the nonexistent `score_via_sagemaker_endpoint`.
12. **(NOTE)** `aggregate_adjacent_flags` either factors county-key derivation into a small helper that consults the admin-geography crosswalk, or documents the FIPS-prefix assumption explicitly with an inline comment.
13. **(NOTE)** `find_existing_open_cluster` cluster-equality check uses `(type, id)` tuples rather than just `id` strings.
