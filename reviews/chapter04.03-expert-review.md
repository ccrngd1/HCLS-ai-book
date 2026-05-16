# Expert Review: Recipe 4.3 - Provider Directory Search Optimization

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-15
**Recipe file:** `chapter04.03-provider-directory-search-optimization.md`

---

## Overall Assessment

This is the strongest recipe in Chapter 4 so far on the security-and-compliance axis. Several of the chapter-level production-hardening gaps that the panel flagged in Recipes 4.1 and 4.2 have been resolved here in the main recipe text rather than punted to "Why This Isn't Production-Ready":

- The verbatim search query is explicitly split from the patient-joined `search-log` row into a separate audit channel, with the security rationale spelled out in the pseudocode. This is the resolution of 4.2's HIGH Finding 1 (`intent_text` minimization) applied as an architectural primitive, not a postscript.
- The engagement attribution Lambda explicitly validates `event.patient_id == search.patient_id` before persisting, which is the resolution of 4.2's MEDIUM Finding 3 (engagement event integrity).
- The API Gateway paragraph names the patient-id authorization boundary explicitly: *"The search Lambda must validate that the caller is allowed to act on the requested patient_id; do not rely on the upstream service."* That's 4.2's MEDIUM Finding 2 directly addressed.
- The Bedrock paragraph states the data-retention and training-stance posture explicitly with a TODO to verify per-model coverage, which is the resolution of 4.2's MEDIUM Finding 4.
- The VPC endpoint list is comprehensive: DynamoDB, S3, Bedrock, Kinesis, KMS, CloudWatch Logs, SageMaker Runtime, Step Functions (`states`), EventBridge (`events`), Location Service, STS. That covers 4.1's Findings 12-13 and 4.2's Finding 12 chapter-wide, and goes further by addressing external SaaS credentialing systems via Direct Connect / PrivateLink.
- DLQ coverage is enumerated with the right level of specificity in a TODO at the bottom of the recipe: API Gateway → search-orchestrator (synchronous-API tradeoff), Step Functions → ingestion (per-stage failure queue keyed on `(provider_id, stage, failure_reason)`), and Kinesis → attribution (event-source-mapping `OnFailure` destination). The third one's silent-failure mode is called out as the most insidious. That resolves the chapter-wide DLQ pattern from 4.1 Finding 6 and 4.2 Finding 6.
- SageMaker model promotion path TODO is explicit and asks the right questions (Lambda-layer publish + alias canary, or endpoint variant weights). That resolves 4.2 Finding 8.

The teaching content is also strong. The seven-stage pipeline (query understanding → eligibility → retrieval → feature joining → LTR → fairness re-rank → result assembly) is the right shape for a production directory search and pedagogically clean. The structural-fairness framing (exposure caps, safety-net floors, near-duplicate suppression as policy decisions calibrated by network operations rather than data science) is a hard-won opinion that will save readers from a foot-gun. The label-problem section honestly addresses position bias and complaint events as gold-standard negative signals. The Honest Take's "the LTR model is not where the value comes from" is the kind of contrarian-but-correct take CC's voice is built for, and the closing observation about directory search setting the trust baseline for the entire member relationship is genuine production wisdom.

That said, three architectural gaps need attention before publication, and a handful of medium and low items round out the review:

1. **The eligibility-filter list in the pseudocode does not implement the "age-credentialed for the patient" rule that the prose claims is enforced.** The Stage 2 description says "a pediatrician can't see a 50-year-old" and the architecture diagram lists "age-appropriate" as an eligibility filter, but the `eligibility_filters` list in `retrieve_candidates` has no age check. A reader following the pseudocode will ship a directory that returns pediatricians for adult searches and adult internists for pediatric searches.
2. **Multi-location providers are not addressed by the indexing model.** The annotation step has a comment *"a provider may have multiple"* locations and assigns a `location_id`, but the OpenSearch indexing writes a single `location: annotated.location.lat_lon`. A primary-care doc with three offices is indexed at one address, and the geographic radius filter sees only that one. Multi-location is the common case, not the edge case.
3. **The fairness re-ranker depends on a windowed exposure aggregate (`get_exposure_window(provider_ids, window = "last_24h")`) that is never defined or implemented anywhere in the recipe.** The Code Review caught the same gap on the Python side (the `_24h`-suffixed counters are written but never windowed). The pseudocode hides the windowing in a black-box helper and the Gap to Production section discusses cap *calibration* but not windowing *implementation*. Without windowing, the cap fires on every popular provider permanently and stops differentiating fit. The fairness story collapses.

A handful of medium and low findings round out the review: search-log retention period is unspecified, per-patient WAF rate limiting isn't addressed (chapter pattern), patient-address geocoding isn't shown as a cached-once operation (cost trap), the per-search batch read of exposure aggregates may push the 500ms latency budget, the provider catalog crosses into PHI-bearing the moment claims-derived features land in it, the `accepts_new_patients` hard filter relies on a notoriously stale signal, and there's a small pseudocode typo (`rerorted` / `reranked` undefined return) plus one stray en-dash in the cost line.

The voice is clean throughout: zero em dashes (verified), 70/30 vendor balance maintained, no marketing-language creep.

Priority breakdown: 0 critical, 3 high, 7 medium, 6 low.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA explicitly stated; HIPAA-eligibility status called out for every service in the architecture (with TODOs to verify Bedrock per-model and Location Service entries, both appropriate).
- Customer-managed KMS keys for every PHI-containing store: DynamoDB, OpenSearch (encryption at rest plus node-to-node), Kinesis, Firehose, S3 (SSE-KMS bucket-level keys). Lambda log groups KMS-encrypted with the explicit reason that the search log "may include PHI."
- The verbatim search query string is explicitly routed away from the patient-joined `search-log` row to a separate audit channel with stricter access controls and shorter retention. This is the resolution of 4.2's HIGH Finding 1 applied as an architectural primitive: *"do NOT persist the verbatim query string into the same record as the patient_id; the raw query may include the patient's own name, a prior provider's name, or other identifying free text."* The pseudocode's `AuditLog.Append("search-query-audit", ...)` carries no `patient_id` directly, and reconstruction requires going through `search_id` via the audit access workflow that itself logs the joiner.
- Engagement event integrity: `process_engagement_event` validates that `event.patient_id == search.patient_id` and drops mismatches. That resolves 4.2's Finding 3 directly and applies the chapter-wide "events must be cross-validated against the originating decision record" pattern.
- Patient-id authorization at the API: *"The search Lambda must validate that the caller is allowed to act on the requested patient_id; do not rely on the upstream service."* That resolves 4.2's Finding 2 directly.
- Bedrock data-retention posture stated explicitly: *"Confirm in your BAA acceptance and Bedrock service terms that customer prompts and completions are not used to train the underlying foundation models and are not retained beyond the request lifecycle."* That resolves 4.2's Finding 4.
- CloudTrail data events called out for the patient-profile, search-log, and engagement-event tables. Provider-catalog data events flagged as appropriate "once it contains attributes derived from PHI (e.g., patient-overlap counts)." That captures the contamination risk most directory implementations miss.
- The eligibility-vs-optimization split is correct security posture: hard filters (out-of-network, panel closed, age-inappropriate by description, status under review) live above the ranker so it can't override them.
- The free-text profile fields fed to the embedding model are bounded by what the catalog already exposes (specialty + bio + services); no claims-derived patient context goes to the embedding endpoint at index time.

### Finding 1: Search-Log Retention Period Is Unspecified, and the Log Will Become a Substantial Inferentially-Identifying PHI Corpus

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** "Why This Isn't Production-Ready," the *Privacy in the search log* paragraph; also "Prerequisites" → CloudTrail row.
- **Problem:** The recipe acknowledges the search log as PHI ("patterns of search behavior (a member repeatedly searching for 'oncologist' or 'addiction medicine') are inferentially identifying") and applies the right confidentiality and audit controls (customer-managed KMS, CloudTrail data events, narrow IAM read scopes). It does not specify a retention period or a deletion mechanism. At the illustrative scale the recipe uses (500K searches per month), the search log accumulates 6M rows per year. After three years that's 18M rows of `(patient_id, parsed_intent, ranked_provider_ids, feature_snapshot, model_version)` joined to patient identity. The longer the corpus exists, the more inferentially identifying it becomes, and the more attractive a target for both insider abuse and external compromise.

  The Recipe 4.1 review flagged the same concern for the reminder-decisions table (Finding 3 there). The chapter-wide pattern is that personalization systems accumulate rich behavioral records that are PHI at rest and PHI when joined, and that retention has to be defined explicitly.

- **Fix:** Add to the *Privacy in the search log* paragraph: "Define an explicit retention policy (e.g., 90 days for individually-attributed search logs, longer only after de-identification per HIPAA Safe Harbor or expert determination). The retention period should be approved by privacy and compliance, with a CloudWatch alarm on the deletion job and a documented re-attestation cadence. The verbatim query audit channel should have a shorter retention than the patient-joined search log (typically 30 days) since its purpose is incident investigation, not analytics."

### Finding 2: WAF Mentioned But No Per-Patient Throttling

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** "Why These Services," Amazon API Gateway paragraph.
- **Problem:** Same finding pattern as 4.2's Finding 9. The recipe specifies API Gateway with WAF but does not address per-caller rate limiting. A buggy "Find a Doctor" page that re-renders in a loop, a member-services tool with a polling bug, or a credential-stuffing attack with a valid Cognito token can each blow through the per-account TPS quotas for Bedrock (query parsing) and Location Service (geocoding), degrading the service for every other patient. WAF can rate-limit on a custom request header populated by the Lambda authorizer with the resolved patient identifier.
- **Fix:** Add a sentence to the API Gateway paragraph: "Apply WAF rate-limiting rules keyed on the resolved patient identifier from the Lambda authorizer (e.g., a request header populated by the authorizer). A reasonable starting point is 10 requests per patient per minute and 100 per patient per hour. This protects shared backend quotas (Bedrock for query parsing, Location Service for geocoding, OpenSearch read capacity) from a single misbehaving caller and is cheaper than discovering the issue via a Bedrock or Location Service throttling exception during business hours."

### Finding 3: Provider Catalog Becomes PHI-Bearing the Moment Claims-Derived Features Are Persisted, but the Persistence Boundary Is Ambiguous

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** "Prerequisites," CloudTrail row: *"Provider-catalog table data events are recommended once it contains attributes derived from PHI (e.g., patient-overlap counts)."* Also the feature-joining step in the pseudocode, which references `patient_context.claims_summary.visits_by_provider.get(c.provider_id, 0)`.
- **Problem:** The recipe correctly notes that provider-catalog attributes derived from PHI cross the catalog into PHI-bearing territory, and recommends CloudTrail data events as a control. The architectural ambiguity is whether such features should be persisted in the provider catalog at all. Two possible designs:

  1. **Compute-at-query.** The "prior visits" feature is computed at query time from the patient's claims summary and is never stored on the provider record. Provider catalog stays non-PHI. This is the pseudocode's actual approach in `join_features` (the lookup is `patient_context.claims_summary.visits_by_provider`, not a provider-side aggregate).
  2. **Persist-aggregated.** Provider-side patient-overlap counts (e.g., "this provider sees 423 patients from this plan") are computed and stored on the provider record for ranker features or operational dashboards. Provider catalog becomes PHI-adjacent: an aggregate count of plan-attributed patients per provider is not directly identifying, but combined with other provider-side aggregates it can be re-identifying for small panels.

  The pseudocode does design (1), but the prerequisites and the production-gaps section lean toward design (2). A reader implementing this will guess wrong on the boundary and may persist patient-derived aggregates onto the provider record without realizing the catalog has just changed PHI status.

- **Fix:** Add a paragraph (either in the feature-joining walkthrough or in the production-gaps section): "The recipe computes patient-side personalization features at query time from the patient profile (e.g., `prior_visits` is read from `patient_context.claims_summary.visits_by_provider`). Do not persist patient-derived aggregates onto the provider record without first deciding whether the provider catalog should become PHI-bearing. Aggregated counts can be re-identifying for providers with small panels (e.g., a rare-specialty provider with three patients from a particular plan). If you choose to persist provider-side patient aggregates, treat the entire provider catalog as PHI from that point: KMS, CloudTrail data events, narrow IAM read scopes, defined retention. The cleaner default is to keep the provider catalog non-PHI and compute personalization features at query time."

### Finding 4: `accepts_new_patients` as a Hard Eligibility Filter Sits on a Notoriously Stale Signal

- **Severity:** MEDIUM
- **Expert:** Security (compliance accuracy)
- **Location:** Stage 2 description ("The provider's accepting-new-patients flag is false and the patient is new") and `retrieve_candidates`'s eligibility filter (`{ term: { "accepts_new_patients": true } }` when intent confirms).
- **Problem:** The recipe opens by acknowledging that "accepting-new-patients flag completely fictional" is one of the canonical directory failures CMS audits catch. It then turns around and uses that flag as a hard eligibility filter. Two failure modes compound:

  1. When the flag is stale-true (provider's panel actually closed but the directory still shows open), patients get sent to a closed panel, call, and bounce. That's the "ghost provider" failure the No Surprises Act was designed to address.
  2. When the flag is stale-false (provider has reopened their panel but the directory still shows closed), the filter excludes them entirely. The patient never sees a viable option that should have been viable. This is the more insidious failure because there's no engagement signal to catch it (the provider was never shown).

  The recipe's freshness penalty addresses (1) implicitly (stale records get demoted) but does nothing for (2). A hard filter on a noisy signal is fail-closed for the wrong direction.

- **Fix:** Two options.
  1. **Soften to a strong soft filter.** Make `accepts_new_patients` a should-clause boost rather than a filter. Stale-false providers still appear at lower rank, the ranker can compensate when other signals are strong, and the patient sees the result with a clear "panel may be closed" annotation.
  2. **Tier the filter by freshness.** Apply the hard filter only when the `accepts_new_patients` field has been verified within the last N days (e.g., 30). Older records with `accepts_new_patients: false` get a soft demotion instead of a hard exclusion.

  Either option deserves a paragraph in the eligibility-filtering walkthrough that calls out the tension explicitly. The recipe's existing language ("Filters from intent are required only when the intent system is confident") gestures at this for the *intent-derived* version of the filter, but not for the *provider-attribute* version.

### Finding 5: IAM "Never *" Stated Without Scoped ARN Examples

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites, "IAM Permissions" row.
- **Problem:** Same finding as 4.1 Finding 5 and 4.2 Finding 5. The row says "Never `*`" and lists actions, but doesn't pair them with example resource ARNs. A reader copying this into an IAM policy may default to `Resource: *`. The TODO acknowledging the OpenSearch action confusion (`es:*` vs `aoss:*`) is helpful but doesn't address the broader pattern.
- **Fix:** Add one or two example ARNs inline. For example: `bedrock:InvokeModel on arn:aws:bedrock:{region}::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0`; `dynamodb:GetItem on arn:aws:dynamodb:{region}:{account}:table/provider-catalog`; `geo:SearchPlaceIndexForText on arn:aws:geo:{region}:{account}:place-index/Healthcare-Geocoder`. A coordinated chapter-wide fix on this would be more durable than re-litigating per recipe.

### Finding 6: Member-Services-Agent Authorization Path Is Mentioned But Not Specified

- **Severity:** LOW
- **Expert:** Security
- **Location:** "Why These Services," Amazon API Gateway paragraph; also "Where it struggles," the *member services agents* bullet.
- **Problem:** The recipe correctly notes that member services agents "doing dozens of searches per shift" need to be tagged separately so they don't poison the personalization signal. The personalization-signal aspect is solved by the tag. The authorization aspect is not addressed: a call-center agent searching on behalf of a member needs an authorization mechanism that is not "the agent has the patient's session token." Common patterns include a delegated-authorization claim ("agent X is acting on behalf of patient Y"), an opaque per-call delegation token issued by member-services tooling, or a per-agent role with scoped resource policies that allow patient lookups within an attribution window. The recipe is silent.
- **Fix:** Add a sentence to the API Gateway paragraph or the production-gaps section: "Member-services agent calls require their own authorization model: an agent acts on behalf of a member, so the request carries both the agent's identity (for audit and rate-limiting) and the member's identity (for the recommendation context). The Lambda must verify the agent is authorized to act on behalf of the requested member at the time of the call (typically via a short-lived delegation token issued by the member-services platform). Do not let an agent enumerate patients by reusing patient session tokens."

---

## Architecture Expert Review

### What's Done Well

- The seven-stage pipeline (query understanding → eligibility → candidate retrieval → feature joining → LTR → fairness re-rank → result assembly) is the correct shape for a hybrid IR + personalization workload at directory scale. The eligibility-vs-optimization split is articulated as a correctness boundary, not a feature.
- Hard filters applied BEFORE the candidate-retrieval and ranking steps. Same correct ordering as 4.1 and 4.2.
- Three-policy fairness re-rank (exposure caps, safety-net floor, near-duplicate suppression) is the right shape, and the framing of fairness as a policy decision calibrated by network operations and compliance (not a hyperparameter) is the framing that will save readers from a foot-gun.
- The label problem is treated honestly: position-bias correction, sparse explicit feedback, downstream signals (calls, bookings, complaints), and provider-side correctness signals are each named and the failure modes called out.
- The LTR section's "you don't need a transformer, you need clean data and a tree-based ranker" is the contrarian-but-correct take that this domain needs.
- Catalog quality treated as the dominant problem rather than the ranker. The Honest Take's "the LTR scoring is the last 15% of the lift" reads as production wisdom.
- DLQ coverage is enumerated with the right specificity in the production-gaps TODO: API Gateway → orchestrator (synchronous-API tradeoff with structured logging and CloudWatch 5xx alarms), Step Functions → ingestion (each task `Catch` to SQS keyed on `(provider_id, stage, failure_reason)`), and Kinesis → attribution (event-source-mapping `OnFailure` destination with DLQ-depth alarm). The third one's silent failure mode is named explicitly.
- SageMaker training trigger and model-promotion path are flagged as gaps in a TODO, with the right options enumerated (EventBridge schedule vs CloudWatch threshold for trigger; Lambda-layer publish + alias canary vs endpoint variant weights for promotion).
- Lambda-layer ceiling for the LTR ranker is called out explicitly, with the graduation path to a SageMaker Endpoint flagged.
- Reusing the patient profile, engagement bus, and feature store from 4.1 and 4.2 keeps the chapter cohesive and reduces the operational footprint.

### Finding 7: Eligibility-Filter List in Pseudocode Does Not Implement the "Age-Credentialed" Rule the Prose Claims

- **Severity:** HIGH
- **Expert:** Architecture (correctness)
- **Location:** Stage 2 description in "The Logical Stages" (*"The provider is not credentialed for the patient's age (a pediatrician can't see a 50-year-old)"*); architecture diagram (*"age-appropriate"* listed under Stage 2); the `eligibility_filters` list in `retrieve_candidates` (which contains status, network_tier, language, gender, accepts_new_patients, geo_distance, and nothing age-related).
- **Problem:** The prose makes a specific claim about an eligibility rule that the architecture does not implement. The architecture diagram lists "age-appropriate" alongside "network match" and "accepting new patients" in Stage 2's eligibility filters, suggesting parity with the other hard filters. But the pseudocode for `retrieve_candidates` has no age check anywhere, and the provider record schema in `on_provider_event` has no `age_groups_served` or `min_age` / `max_age` field. A reader following the pseudocode will:

  1. Index providers without an age-served attribute.
  2. Wire up the eligibility filter without an age clause.
  3. Ship a directory that returns pediatricians for 50-year-old patients searching "primary care" and adult internists for parents searching "pediatrician" (the latter is filtered out only by specialty match, which is a softer signal than the prose implies).

  The downstream patient experience is exactly the failure mode the recipe's opening vignette criticizes: "a doctor whose specialty was misclassified in the directory ingest five years ago and who is, in fact, an adult internist who occasionally sees teenagers." Without a structural age filter, the architecture cannot prevent that case.

  This is HIGH because (a) the prose makes a correctness claim the architecture doesn't fulfill, (b) the failure mode is real and high-frequency in production directories, and (c) a reader is unlikely to notice the gap without prior directory experience.

- **Fix:** Two changes.
  1. **Add an `age_groups_served` attribute** to the provider catalog schema. Encode either as a list of age bands (`["pediatric", "adolescent", "adult", "geriatric"]`) or as a `min_age` / `max_age` pair. The annotation step populates it from credentialing data and source-system specialty rules (a Pediatrics taxonomy code defaults to `min_age=0, max_age=21`; Internal Medicine defaults to `min_age=18, max_age=null`; Family Medicine defaults to `min_age=0, max_age=null`).
  2. **Add the eligibility clause** to `retrieve_candidates`:

     ```
     eligibility_filters.append({
         range: {
             "min_age": { lte: patient_context.age }
         }
     })
     eligibility_filters.append({
         bool: {
             should: [
                 { range: { "max_age": { gte: patient_context.age } } },
                 { bool: { must_not: { exists: { field: "max_age" } } } }
             ]
         }
     })
     ```

     The bool/should/must_not wrap handles the "no max age" case (Family Medicine, Internal Medicine for adults) without excluding providers who simply lack a `max_age` field.

  Update the architecture diagram so "age-appropriate" remains accurate. Consider adding a sentence in the Stage 2 walkthrough acknowledging the practical messiness (pediatricians often retain patients into early 20s; family medicine handles all ages; "age-credentialed" is in practice a soft band with provider-level overrides). The eligibility filter should err on the side of inclusivity for ambiguous cases.

### Finding 8: Multi-Location Providers Are Not Addressed by the Indexing Model

- **Severity:** HIGH
- **Expert:** Architecture (correctness)
- **Location:** Step 1 pseudocode (`on_provider_event`), the annotated record's `location` field; OpenSearch indexing call.
- **Problem:** The annotated record acknowledges the issue with a comment: *"location_id: hash(candidate_record.address) // a provider may have multiple"*. Then the OpenSearch indexing writes `location: annotated.location.lat_lon`, a single geo_point. So a provider with three offices gets indexed as one document at one address. Two failure modes:

  1. **The geo_distance filter sees only one location.** Patient searches in a 10-mile radius around address A. Provider has an office at address A (in radius), an office at address B (out of radius), and an office at address C (out of radius). Provider gets indexed at address C (the latest record from credentialing happened to use that address). The patient never sees this provider, even though they have an in-radius office. Real-world impact: substantial under-recall for multi-location providers, which are common in primary care, pediatrics, and most specialty groups.

  2. **The displayed address is wrong for the patient's geography.** Even if the patient sees the provider (e.g., the indexed address happens to be in radius), the displayed address is the indexed one, which may not be the office the provider works at on the day the patient wants. The patient calls the wrong number, drives to the wrong address, or shows up at a closed office.

  Multi-location is the common case, not the edge case. A primary-care doc with two offices is normal. A specialty group with eight offices and a roving panel of physicians is normal. The architecture has to model `(provider, location)` as the indexed unit, not `provider`.

  The Honest Take section acknowledges that "the catalog is small but high-stakes" and "every result needs to be defensible." A directory that silently mis-indexes multi-location providers fails both criteria.

- **Fix:** Index the catalog at the `(provider_id, location_id)` granularity. Each `(provider, location)` pair is a separate OpenSearch document with its own geo_point and own `last_verified_at`. Two implementation styles:

  1. **Per-pair documents.** Each `(provider, location)` is a top-level document. The `provider_id` is a non-unique field so query results may include the same provider at multiple locations; result assembly deduplicates to the closest location per provider, or shows the same provider at each in-radius location depending on UX. This is the cleaner shape for the geo filter.

  2. **Provider documents with nested locations.** Each provider is one document with a nested `locations[]` array, each with its own `lat_lon` and `last_verified_at`. OpenSearch's nested-field query returns the matching nested object for each hit. Slightly more complex query DSL, but keeps the deduplication at index time.

  Update the pseudocode to index at this granularity, and update Stage 7's result assembly to render the location that matched the geographic filter (not whichever address the catalog happens to cite first). Update the architecture diagram if needed.

  Add a note: stale or duplicate addresses across source systems are a recurring data-quality issue. The match-and-merge step should produce a deduplicated `locations[]` array per provider, with an `is_primary` flag for cases where the patient-facing UX needs a single canonical address.

### Finding 9: Exposure Window Is Referenced But Never Defined; Without It, the Fairness Cap Permanently Breaks

- **Severity:** HIGH
- **Expert:** Architecture
- **Location:** Step 6 pseudocode (`fairness_rerank`), the call `exposure_window = get_exposure_window(provider_ids = [...], window = "last_24h")`; "Why This Isn't Production-Ready," the *Exposure-cap calibration* paragraph.
- **Problem:** The pseudocode delegates the windowing semantics to a black-box helper (`get_exposure_window(window="last_24h")`). The helper is never defined, never described, and never implemented in the recipe. The Code Review caught the same gap on the Python companion: the exposure aggregates table is written with attribute names suffixed `_24h` but the counters are never reset, never windowed, and never bounded.

  The architectural failure mode this produces is specific and bad. Without windowing:

  1. On day 1, every popular provider is below the cap. The fairness re-rank does nothing observable.
  2. On day 30, the most-trafficked subset of providers has accumulated counts above the cap. The dampening fires for them on every search.
  3. On day 90, every provider with non-trivial traffic is permanently above the cap. The fairness re-rank becomes a global score reducer for the popular subset, with no windowing benefit. Concentration drifts back in (because all popular providers are dampened equally, the relative order among them is unchanged), but is now masked by the cap "firing."
  4. By month six, the dashboard says "fairness cap fires on 84% of searches" and the operations team concludes the cap is correctly calibrated when in fact it's broken.

  The "Why This Isn't Production-Ready" section discusses *cap calibration* (what value to set for `policy.max_top3_impressions`) but not *cap implementation* (what the windowing infrastructure looks like). A reader who reads the production-gaps section carefully will not realize that the missing piece is the windowing primitive itself.

  This is HIGH because the entire fairness-re-rank story depends on windowing being correct, and the recipe's pedagogical focus is on the policy decisions (caps, floors, suppression) not the windowing infrastructure. A reader who builds the cap as the pseudocode shows will produce a system that quietly fails its fairness mission within a few months.

- **Fix:** Two changes.
  1. **Define `get_exposure_window` semantics.** Add a paragraph in the Stage 6 walkthrough or in a sidebar explaining the windowing options:

     - Per-event row table with DynamoDB TTL on a 24-hour expiry, aggregated on read via a query.
     - Sliding-window aggregation via Kinesis Data Analytics or a scheduled Lambda decay job that runs hourly and ages out buckets older than 24 hours.
     - Bucketed-counter schema (`impressions_at_top_3.{yyyy-MM-ddTHH}` map) summed over the last 24 hour-buckets at read time. (This option has the cold-start nested-map issue Recipe 4.2 flagged; the same `SET ... if_not_exists(impressions_at_top_3, :empty)` pattern would apply.)

     Pick one as the canonical recipe pattern and describe the tradeoff. The pseudocode's `get_exposure_window(window="last_24h")` call shape is the right facade; what's missing is one of the implementation options behind it.

  2. **Add an explicit production-gaps paragraph** on windowing implementation, separate from the cap-calibration paragraph. Frame it as: "The cap value in `policy.max_top3_impressions` is one knob; the windowing infrastructure that produces the count fed into the comparison is a separate piece of work, often more important than the cap value. Without windowing, the cap stops differentiating providers within months of launch."

  Coordinate this fix with the Code Review's WARNING (Finding 1 in the code review) so the pseudocode and the Python teach the same approach.

### Finding 10: Per-Search Exposure Aggregate Read Is in the Hot Path and May Push the 500ms Latency Budget

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 6 pseudocode (`fairness_rerank`), the `get_exposure_window(provider_ids = [r.provider_id for r in sorted_rows], window = "last_24h")` call.
- **Problem:** The fairness re-ranker reads exposure aggregates for every candidate provider on every search. With 100-300 candidates per search after Stage 3, that's a 100-300-key read against the exposure-aggregates store on every search. Even a batched DynamoDB read costs 30-80ms at typical p95, and the read is sequential after the LTR scoring, not parallel. The recipe's claim *"the whole pipeline fits in 500 milliseconds for a typical query"* is plausible only if this read is fast and cached.

  At the illustrative 500K searches/month (and bursty intra-day distributions; "Find a Doctor" traffic clusters around evenings and weekends), the exposure-aggregate read becomes a hot table. DynamoDB cost stays manageable but latency becomes the constraint, especially under load.

- **Fix:** Add a paragraph to the Stage 6 walkthrough or to "Why These Services": "The exposure aggregate read is in the hot path. For a 200-candidate search, the batched DynamoDB read costs roughly 30-80ms at p95. Cache aggressively at the search-orchestrator Lambda (per-container LRU keyed on `provider_id`, TTL of 60-120 seconds since the cap is 24-hour-windowed) so warm Lambda containers don't re-read the same providers repeatedly. For very high traffic, consider an in-memory cache (ElastiCache for Redis) fronted by the orchestrator; the consistency window is forgiving (the cap is fairness, not correctness, so a 1-2 minute lag in the count is acceptable)."

  Optional: note that the windowing-bucket schema from Finding 9 makes the read pattern more cache-friendly (the bucket keys for the last hour are stable for that hour) which is a separate point worth making.

### Finding 11: Patient Address Geocoding Caching Pattern Not Shown

- **Severity:** MEDIUM
- **Expert:** Architecture (cost)
- **Location:** "Why These Services," Amazon Location Service paragraph; the cost estimate row mentioning "$0.50 per 1000 geocoding requests."
- **Problem:** The recipe says "Patient location strings ('123 Main St, Springfield') need to become coordinates for distance calculation. Provider addresses need the same. Amazon Location Service handles both." That's true, but the architecture doesn't show that the patient's *home address* (the most common search-location source for an authenticated patient) should be geocoded once at profile creation and cached on the patient profile, not re-geocoded on every search.

  The pseudocode treats `patient_context.search_location` as a pre-resolved input, which is the right shape. But the prose and the cost estimate ($0.50 per 1000 geocoding requests at "typical volumes" landing under $300/month at 500K searches) imply that 500K geocoding calls are happening. If the implementer reads "geocoded on every search," they'll spend 50x more on Location Service than they need to and add 30-50ms of latency per search.

  Provider addresses are geocoded once at ingestion (the pseudocode shows this). Patient addresses should follow the same pattern: geocoded once at profile creation or address update, persisted to the patient-profile table, and read on every search.

- **Fix:** Add a sentence to the Location Service paragraph: "Geocode patient home addresses once at profile creation or address-update events, persist the lat/lon to the patient-profile table, and read on every search. Geocode patient-typed location overrides ('show me providers near 123 Other St') at search time, but cache by address string so a patient who searches the same off-profile address repeatedly doesn't re-incur the geocoding cost. Provider addresses are geocoded once at ingestion (see Step 1)."

  Update the cost estimate to reflect the cached-at-profile pattern: at 12K providers + occasional re-geocoding plus a small fraction of searches with off-profile location overrides, Location Service costs land in the under-$50/month range, not under $300/month.

### Finding 12: Pseudocode Bug in `fairness_rerank` Return Path

- **Severity:** LOW
- **Expert:** Architecture (pedagogy)
- **Location:** Step 6 pseudocode (`fairness_rerank`), the last few lines.
- **Problem:**

  ```
  rerorted = sort sorted_rows by relevance_score DESC
  RETURN reranked
  ```

  Two bugs:
  1. `rerorted` is a typo of `reranked` (or `resorted`).
  2. The function returns `reranked`, which is never assigned. The intended variable is the one assigned in the line above.

  This is pseudocode, not code, but the bug will confuse a reader who is following the assignments closely. It also propagates into the editor's polish pass and risks landing in print.

- **Fix:** Rename to a single consistent variable and fix the return:

  ```
  reranked = sort sorted_rows by relevance_score DESC
  RETURN reranked
  ```

---

## Networking Expert Review

### What's Done Well

- Lambdas in VPC with Flow Logs enabled.
- OpenSearch domain in VPC, not public. Correct for a HIPAA-eligible service holding the searchable index of providers (which becomes PHI-bearing once any patient-derived feature joins to it).
- TLS in transit specified (HTTPS-only access to OpenSearch, node-to-node encryption inside the cluster).
- Comprehensive VPC endpoint list: DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis, KMS, CloudWatch Logs, SageMaker Runtime, Step Functions (`states`), EventBridge (`events`), Location Service, STS. That covers 4.1's Findings 12 and 13 and 4.2's Finding 12 chapter-wide. Especially good catches: Step Functions and STS, which are easy to miss; Location Service, which the prior recipes didn't need; EventBridge, which has tripped up multiple healthcare implementations.
- External SaaS credentialing systems addressed explicitly: *"Provider data feeds from external SaaS credentialing systems may need a Direct Connect tunnel or PrivateLink connection rather than NAT egress."* That's the right answer for the common case where credentialing is in a vendor SaaS (Verisys, Symplr, etc.) and the data is sensitive enough that NAT egress with IP allow-listing is not enough.
- VPC Flow Logs called out.
- NAT Gateway scoped explicitly to "external services without VPC endpoints (e.g., NPPES public API)" with restricted egress security groups.

### Finding 13: Public vs Private API Gateway Posture for Mixed Caller Contexts Not Specified

- **Severity:** MEDIUM
- **Expert:** Networking
- **Location:** "Why These Services," Amazon API Gateway paragraph: *"Other consumers include member services tooling (the call-center rep searching on behalf of a member) and the appointment-reminder pipeline (Recipe 4.1) when it's checking in-network alternatives."*
- **Problem:** Same finding pattern as 4.2 Finding 13. The recipe identifies three caller contexts (patient portal, member-services tooling, Recipe 4.1's reminder pipeline) without specifying their network posture. For the patient portal, public regional API Gateway is appropriate (the portal lives outside the VPC). For member-services tooling, it depends on whether the agent desktop runs inside the corporate VPC or via a SaaS portal. For Recipe 4.1's reminder pipeline (a Lambda inside the same AWS account), private API Gateway via VPC interface endpoint keeps the entire request path inside AWS networking, avoids unnecessary public DNS resolution, and simplifies WAF rules.
- **Fix:** Add a paragraph: "Different caller contexts call for different API Gateway deployments. Deploy a public regional REST API with WAF and Cognito authorizer for portal callers; a private REST API exposed via a VPC interface endpoint for service-to-service callers (the Recipe 4.1 reminder pipeline, the post-visit summary generator from Recipe 2.5); and a third, separately-scoped endpoint for member-services tooling depending on whether the agent desktop is inside the corporate VPC. The Lambda code is the same; the request paths and authn mechanisms are not."

### Finding 14: NPPES Public API Egress Pattern Not Specified Beyond NAT

- **Severity:** LOW
- **Expert:** Networking
- **Location:** "Prerequisites," VPC row (NPPES mention); also Step 1 pseudocode (`check_NPPES_active(candidate_record.NPI)`).
- **Problem:** The recipe correctly notes that NPPES is a public API requiring NAT egress when the validating Lambda is in a VPC. What's missing is the rate-limiting and batching guidance: NPPES public API has no formal SLA, has been observed to throttle large polling clients, and is not a service to call synchronously inside the patient-facing search path. The "schedules in EventBridge also drive the periodic refresh tasks: nightly NPPES status checks" sentence implies a polling pattern, which is right, but the rate and batching details are absent.

  Also worth noting: NPPES queries are by NPI, which is a provider-side identifier and not PHI. Egress to NPPES does not cross PHI boundaries; the prose could be slightly clearer that NAT egress to NPPES is not an exfiltration risk, only a reliability and rate-limiting concern.

- **Fix:** Add a sentence to the VPC row or the EventBridge paragraph: "NPPES public API calls are by NPI (provider identifier, not PHI) and egress through NAT. Batch queries (typically 5-10 NPIs per request, observed rate-limit safe), schedule them off-peak (overnight), and back off aggressively on 5xx responses. The provider-validation Lambda should never call NPPES synchronously from the patient-facing search path."

### Finding 15: Egress Allow-List Posture Not Stated for Lambda Subnets

- **Severity:** LOW
- **Expert:** Networking
- **Location:** "Prerequisites," VPC row.
- **Problem:** Same low-severity finding pattern as 4.1 Finding 14. The VPC row says "VPC Flow Logs enabled" and "restrict egress security groups" but doesn't explicitly disallow `0.0.0.0/0` egress on Lambda subnets. The chapter-wide pattern is worth capturing once.
- **Fix:** Add: "No `0.0.0.0/0` egress from any Lambda subnet. NAT egress restricted by security group to specific IP ranges or hostnames (NPPES public registry, the SaaS credentialing system if applicable). All other outbound traffic must go through VPC endpoints."

---

## Voice Reviewer

### What's Done Well

- The opening vignette is excellent. The four results that go wrong on the patient's "Find a Doctor" page each illustrate a distinct directory failure mode (panel closure, stale availability, specialty misclassification, sort-by-distance overriding existing relationship), and the closing detail ("the patient writes the name down... the kid sleeps... the receptionist says: 'I'm so sorry, that doctor left the practice in October'") lands with the same human specificity as 4.1's four-personas opener and 4.2's folder vignette.
- "This is not a hypothetical. Provider directories are notoriously, hilariously, regulator-attentively bad." The triple-adverb construction is exactly the cadence the style guide calls for. "Regulator-attentively" is a hard-earned word.
- "The catalog is small but high-stakes. A regional plan has thousands to tens of thousands of providers, not millions. You don't need fancy distributed search. You do need every result to be defensible." Clean structural insight, in voice.
- "The data is dirty in known ways... You can build a brilliant ranker on bad data and produce a brilliantly ordered list of wrong answers." Memorable.
- "The objective function is a committee, not a single number." Same kind of one-liner the chapter has been collecting.
- "Recipe 4.3 is information retrieval on a noisy catalog with regulatory implications" is the one-sentence framing the rest of the recipe earns.
- "The honest hard part of LTR is getting labels." Direct, in voice, sets up the section without filler.
- "Treat tier-aware ranking as a policy decision that needs explicit governance, not as a feature you silently add." The kind of opinion that comes from having seen the alternative.
- "The compliance team needs to be in the room when ranking policy gets set, not consulted afterward." Earns its place.
- "The LTR scoring is the last 15% of the lift, and you spend disproportionate time on it because it's the part that feels like data science. If your team is gravitating toward 'let's tune the ranker more' while the catalog still has 30% staleness, redirect them." Best paragraph in the Honest Take.
- "And the trap worth flagging: confusing CTR with success." Closes the chapter's structural-fairness arc cleanly.
- The structural turning point framing in "Where This Sits in the Chapter" is the right level of meta: it tells the reader why this recipe matters relative to 4.1 and 4.2 without being preachy.
- Em dash check: scanned for U+2014 (em dash). Zero present. Pass.
- 70/30 vendor balance: The Problem, Technology, and General Architecture Pattern sections are fully vendor-neutral. AWS enters in "The AWS Implementation" and stays there. Clean.
- No marketing-language creep: scanned for "leverage," "seamlessly," "robust," "cutting-edge," "state-of-the-art," "industry-leading." Zero matches. Clean.

### Finding 16: One En Dash Survives in the Cost Line

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Line 3: *"**Estimated Cost:** ~$0.001–0.005 per ranked search response (depends on personalization depth)"*
- **Problem:** The character between `0.001` and `0.005` is a U+2013 en dash. The style guide explicitly prohibits em dashes (U+2014); the prior reviews (4.1 Finding 17 cadence, 4.2 voice scan) have applied the same prohibition to en dashes for chapter consistency. Other cost ranges in the recipe use `-` (hyphen-minus) consistently: "$200-300/month range", "$50-150/month", "$1,000-2,500/month range". The complexity-line en dash is the one inconsistency.
- **Fix:** Replace with `-` (hyphen-minus): `~$0.001-0.005 per ranked search response`. One-character change.

### Finding 17: "Notoriously, Hilariously, Regulator-Attentively Bad" Earns Its Place, but Once Is Plenty

- **Severity:** LOW
- **Expert:** Voice (rhythm)
- **Location:** "The Problem," paragraph 4: *"Provider directories are notoriously, hilariously, regulator-attentively bad."*
- **Problem:** Not a fix request. Worth flagging that the triple-adverb construction is striking precisely because the rest of the recipe doesn't lean on the same trick. If the editor is tempted to add similar constructions elsewhere for symmetry, resist. This is the right kind of voice flourish: occasional, earned, and load-bearing.
- **Fix:** None. Note for the editor: keep it singular.

### Finding 18: "Compliance Spine" in Subhead Is One Mild Doc-Voice Adjacent Phrase

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Section heading: *"## The Technology: Search Plus Ranking, with a Compliance Spine"*
- **Problem:** "Compliance spine" reads slightly more like a McKinsey deck slide than CC's voice. The body of the section delivers exactly what the heading promises (compliance as a structural concern, not a sidebar), so the heading is actually accurate. It's just the one phrase in the recipe that pattern-matches to consultancy English.
- **Fix:** Optional. Alternative headings: "Search Plus Ranking, with Compliance Baked In" or "Search Plus Ranking, with the Compliance Layer Always On." Or leave as-is; the body earns it. Lowest-priority finding in the review.

---

## Stage 2: Expert Discussion

**Overlap: Architecture Finding 7 (age-eligibility) and Architecture Finding 8 (multi-location).** Both are correctness gaps where the prose makes a claim the architecture does not implement. The patterns are independent but illustrate a chapter-wide habit worth flagging to the editor: pseudocode for a complex pipeline tends to elide the catalog-schema details that the eligibility filters depend on. A coordinated review of every "filter the candidate set" claim in the recipe against the actual `eligibility_filters` list and the actual provider record schema would catch both.

**Overlap: Architecture Finding 9 (exposure windowing undefined) and Code Review Finding 1 (Python `_24h` counters never reset).** Same gap, two views. The pseudocode delegates windowing to a black-box helper (`get_exposure_window`) and the Python implements unwindowed counters with `_24h`-suffixed names. Resolution: pick one windowing implementation pattern and align the pseudocode and the Python to teach it. The fairness re-rank is the recipe's flagship architectural contribution; the windowing primitive that makes it work cannot be silent.

**Overlap: Security Finding 2 (per-patient WAF rate limiting) and Architecture Finding 10 (per-search exposure aggregate read latency).** Both touch the operational protections needed to keep a shared backend healthy under load. The security view is about preventing a single misbehaving caller from blowing through Bedrock and Location Service quotas; the architecture view is about keeping the read pattern fast enough that the 500ms latency budget holds. Resolution: address them together with a paragraph on operational protections (WAF rate limits + exposure-aggregate caching + reserved Lambda concurrency) in the production-gaps section.

**Overlap: Security Finding 3 (provider catalog as PHI when claims-derived) and Security Finding 4 (`accepts_new_patients` as hard filter on a noisy signal).** Both touch the question of where the patient/provider data boundary actually sits and how brittle the "non-PHI catalog" assumption is. They don't conflict; the fixes are independent.

**Overlap: Security Finding 6 (member-services agent auth) and Networking Finding 13 (public vs private API Gateway).** Both touch the member-services tooling integration. Resolution: address them together with a paragraph that covers both the network posture (private API Gateway via VPC interface endpoint if the agent desktop is inside the corporate VPC, otherwise public with WAF) and the authorization model (delegation token, agent-on-behalf-of-member claim).

**Cross-recipe overlap: chapter-wide hardening patterns.** Findings on IAM ARN scoping (Finding 5 here, Finding 5 in 4.1, Finding 5 in 4.2), per-patient WAF rate limiting (Finding 2 here, Finding 9 in 4.2), and `0.0.0.0/0` egress disallow (Finding 15 here, Finding 14 in 4.1) all repeat across the chapter. Worth capturing once in a Chapter 4 preface section on shared production-hardening guidance, rather than re-litigating per recipe. The DLQ coverage and VPC endpoint completeness items are the chapter's success stories: they were re-flagged in 4.2 and have now been resolved in this recipe's main text.

**No major conflicts among experts.** Security and Architecture both want stronger constraints on the catalog/eligibility boundary; Networking is about endpoint topology and egress; Voice is cosmetic. Priority alignment is clean.

**Priority alignment:** Three HIGH findings (age-eligibility filter prose vs pseudocode mismatch, multi-location indexing not addressed, exposure-windowing undefined) are the must-fix-before-publication items. Seven MEDIUM findings are production-hardening that the editor or the next pipeline pass should address. The six LOW findings are cosmetic, edge-case, or chapter-pattern items.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

Zero CRITICAL findings. Three HIGH findings (Findings 7, 8, 9), which is at the threshold (more than 3 = FAIL, exactly 3 is acceptable). The three HIGH findings are real correctness gaps, not fundamental design flaws: the pseudocode and the architecture diagram agree with each other on what the system is supposed to do; they just leave out the implementation details for "age-credentialed eligibility," "multi-location provider indexing," and "windowed exposure aggregates." The teaching arc (seven-stage pipeline, eligibility-vs-optimization split, learning-to-rank, structural-fairness re-rank, label-problem honesty, catalog-quality-is-half-the-problem framing) is solid and publishable. The HIGH findings should be addressed in the main text before the editor finalizes the recipe.

The recipe's security and architectural posture is the strongest in Chapter 4 so far. Several chapter-wide gaps from 4.1 and 4.2 reviews (DLQ coverage, VPC endpoint completeness, patient-id authorization, Bedrock data-retention posture, search-log/audit-channel split, engagement event integrity) are resolved in the main text rather than punted to "Why This Isn't Production-Ready." That progression is worth flagging to the chapter editor as a positive signal: the panel feedback loop is tightening across recipes.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| 7 | HIGH | Architecture | Stage 2 prose, architecture diagram, `retrieve_candidates` filter list | Eligibility filter prose claims age-credentialing rule; pseudocode does not implement it |
| 8 | HIGH | Architecture | Step 1 pseudocode, OpenSearch indexing | Multi-location providers indexed at one location; geo_distance filter under-recalls |
| 9 | HIGH | Architecture | Step 6 pseudocode, production-gaps section | `get_exposure_window` referenced but never defined; without windowing, fairness cap permanently breaks |
| 1 | MEDIUM | Security | Production-gaps, *Privacy in the search log* paragraph | Search-log retention period unspecified; corpus accumulates indefinitely |
| 2 | MEDIUM | Security | Why These Services / API Gateway | No per-patient WAF rate limiting; risk of single caller blowing Bedrock and Location Service quotas |
| 3 | MEDIUM | Security | Prerequisites / CloudTrail row, `join_features` | Provider catalog crosses into PHI when claims-derived features persisted; persistence boundary ambiguous |
| 4 | MEDIUM | Security | Stage 2 prose, `retrieve_candidates` filter list | `accepts_new_patients` as hard filter sits on a notoriously stale signal; soften or tier by freshness |
| 10 | MEDIUM | Architecture | Step 6 pseudocode | Per-search exposure aggregate read in hot path; may push 500ms latency budget |
| 11 | MEDIUM | Architecture | Why These Services / Location Service | Patient-address geocoding caching pattern not shown; risk of 500K geocoding calls/month at scale |
| 13 | MEDIUM | Networking | Why These Services / API Gateway | Public vs private API Gateway posture not specified for mixed caller contexts |
| 5 | LOW | Security | Prerequisites / IAM row | "Never *" stated but scoped ARN examples not shown (chapter-wide pattern) |
| 6 | LOW | Security | Why These Services / API Gateway, Where it struggles | Member-services agent delegation auth model not specified |
| 12 | LOW | Architecture | Step 6 pseudocode | Pseudocode typo: `rerorted` assigned, `reranked` returned (undefined) |
| 14 | LOW | Networking | Prerequisites / VPC row | NPPES rate-limiting and batching guidance not specified |
| 15 | LOW | Networking | Prerequisites / VPC row | `0.0.0.0/0` egress disallow not stated explicitly |
| 16 | LOW | Voice | Line 3 (cost line) | One en dash survives in cost range (consistency with rest of recipe) |
| 17 | LOW | Voice | The Problem paragraph 4 | Note for editor: triple-adverb construction is good; keep it singular |
| 18 | LOW | Voice | Section heading | "Compliance spine" is mild consultancy English; optional rewording |

---

## Recommended Actions (Priority Order)

1. **Add age-credentialing to the eligibility filters** (Finding 7): introduce `age_groups_served` (or `min_age` / `max_age`) on the provider record; populate at annotation time from credentialing data and source-system specialty rules; add the corresponding range clause to `retrieve_candidates`. Update the architecture diagram to keep "age-appropriate" accurate. Add a sentence in the Stage 2 walkthrough acknowledging the practical messiness (pediatricians often retain patients to early 20s; Family Medicine handles all ages; the filter should err on inclusivity for ambiguous cases).
2. **Index providers at the `(provider_id, location_id)` granularity** (Finding 8): pick the per-pair documents pattern or the provider-with-nested-locations pattern, document the tradeoff, and update Step 1's pseudocode and the architecture diagram. Update Stage 7 result assembly to render the location that matched the geographic filter.
3. **Define the exposure window primitive** (Finding 9): pick one windowing implementation (per-event row table with TTL aggregated on read; sliding-window aggregation via Kinesis Data Analytics or scheduled Lambda decay; bucketed-counter map summed at read time), document the tradeoff in a Stage 6 sidebar, and align the pseudocode and the Python (per Code Review Finding 1) on the chosen approach. Add a separate production-gaps paragraph distinguishing cap calibration from cap implementation.
4. **Define search-log retention policy** (Finding 1): add an explicit retention period (e.g., 90 days for patient-joined search logs; 30 days for the verbatim query audit channel) with a CloudWatch alarm on the deletion job and a re-attestation cadence.
5. **Add per-patient WAF rate limiting** (Finding 2): WAF custom rule keyed on resolved patient identifier; starter values 10/min and 100/hour.
6. **Clarify the provider-catalog PHI boundary** (Finding 3): default to compute-at-query for patient-derived features; if persisting provider-side aggregates, explicitly elevate the entire catalog to PHI status with full controls.
7. **Soften `accepts_new_patients` as eligibility** (Finding 4): freshness-tiered hard filter (only fail-closed when verified within N days), or convert to a strong should-clause boost with a "panel may be closed" annotation in result assembly.
8. **Address the hot-path read latency** (Finding 10): in-Lambda LRU cache on exposure aggregates; 60-120 second TTL; optional ElastiCache for Redis at higher traffic tiers.
9. **Cache patient address geocoding at profile creation** (Finding 11): geocode once at profile/address-update events; persist lat/lon to patient profile; update the cost estimate.
10. **Specify public vs private API Gateway posture for mixed callers** (Finding 13): two API Gateway deployments with appropriate authn per caller class.
11. **Add scoped IAM ARN examples** (Finding 5); one or two examples is enough.
12. **Specify member-services agent delegation auth** (Finding 6): short-lived delegation token, agent-on-behalf-of-member claim, separate audit and rate-limit dimensions.
13. **Fix pseudocode typo in `fairness_rerank`** (Finding 12): rename `rerorted` to `reranked` and ensure the return references the assigned variable.
14. **Add NPPES rate-limiting and batching guidance** (Finding 14).
15. **Disallow `0.0.0.0/0` egress on Lambda subnets explicitly** (Finding 15).
16. **Replace en dash with hyphen-minus in cost line** (Finding 16).
17. **Optional voice polish** (Findings 17, 18): leave the triple-adverb singular; optionally reword "compliance spine."

---

## Notes for Editor

- The recipe runs long (~6,500 words before the footer). Length is earned: the Problem section's vignette, the seven-stage logical breakdown, the LTR primer, the label-problem section, and the structural-fairness section are all pedagogically essential. Do not trim any of them.
- Several `<!-- TODO -->` markers are present and appropriate: No Surprises Act provisions verification, OpenSearch / Bedrock / Location Service HIPAA eligibility entries, AWS sample repo names, AWS pricing calculator validation, NDCG/CTR/complaint-rate illustrative numbers, current MA provider directory requirements, counterfactual LTR reference, current AWS ML blog post URLs. These are all realistic verification tasks and not blockers.
- The Cost Estimate is acknowledged as illustrative and TODO'd. The Location Service number ($300/month at typical volumes) is the line that should be revised down once Finding 11's caching pattern is documented; cached at profile, the right number is closer to $30-50/month.
- The Related Recipes section forward-references future recipes (4.4, 4.7, 5.x, 6.x, 11.x) that haven't been written yet. Standard practice for the book.
- The Footer link to Recipe 4.4 references a future recipe that doesn't exist yet. Standard placeholder.
- All external links are real and verified: NPPES NPI Registry, NUCC Healthcare Provider Taxonomy, CMS Medicare Advantage page, CMS No Surprises Act page, Synthea, Learning to Rank Wikipedia, Counterfactual LTR arxiv (with appropriate TODO to verify the most appropriate up-to-date reference), AWS OpenSearch / Bedrock / Location Service / SageMaker / API Gateway / Step Functions docs, AWS HIPAA Eligible Services list, Architecting for HIPAA whitepaper. No fake URLs detected.
- The aws-samples repo references (`amazon-opensearch-service-samples`, `amazon-bedrock-workshop`, `amazon-sagemaker-examples`) are appropriately hedged with TODO markers acknowledging the aws-samples reorganization. Appropriate.
- Cross-recipe coherence with 4.1 and 4.2 is strong: the patient-profile store, engagement event bus, cohort dashboard infrastructure, and Bedrock / OpenSearch / DynamoDB primitives are all reused consistently. The "Where This Sits in the Chapter" section's framing of 4.3 as a structural turning point is accurate and helps the chapter narrative.
- The Python code review (`reviews/chapter04.03-code-review.md`) passed with one WARNING and six NOTEs, which is below the FAIL threshold. The WARNING (exposure counters never windowed despite `_24h`-suffixed names) shares root cause with this review's HIGH Finding 9; aligning the pseudocode and the Python on a single windowing pattern resolves both.
- Voice and 70/30 vendor balance: clean. Em dash count: 0. Recipe is publishable on voice grounds with one one-character en-dash fix.

---

*Review complete. Findings prioritized; PASS verdict at threshold. The three HIGH findings are correctness gaps to close in the main recipe text before final editing; the chapter-wide hardening progress (DLQ coverage, VPC endpoints, patient-id authorization, Bedrock data-retention posture, search-log/audit-channel split, engagement event integrity) is worth noting as a positive signal.*
