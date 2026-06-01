# Expert Review: Recipe 13.8 — Medical Concept Normalization and Mapping

**Reviewer:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Document:** `chapter13.08-medical-concept-normalization-mapping.md`
**Review Date:** 2026-06-01
**Focus Areas:** Clinical terminology accuracy, knowledge graph architecture, HIPAA compliance, production readiness, vendor balance

---

## Overall Assessment

Recipe 13.8 is a strong entry. The problem statement is genuinely excellent: it makes the reader feel the pain of multi-terminology chaos in healthcare data integration without oversimplifying. The technology section is thorough, accurate, and teaches the UMLS/SNOMED/ICD-10/LOINC landscape at the right level of depth. The knowledge graph approach is the correct architectural choice for this problem. The pseudocode is well-structured and the progression from ingestion through normalization to temporal queries is logical.

That said, several issues need attention. The security posture around query-level PHI exposure is underspecified. The architecture has a cache invalidation gap that could produce stale mappings during terminology transitions. And the clinical domain modeling, while mostly correct, has a few inaccuracies that a terminologist would catch immediately.

---

## Stage 1: Independent Expert Reviews

---

## Security Review

### FINDING S-1: Query-Level PHI Exposure Not Addressed in Architecture (Severity: HIGH)

**Location:** Prerequisites table, BAA row

**Issue:** The recipe correctly notes: "Concept mappings themselves aren't PHI, but normalization queries in context (which patient maps to which concept) can constitute PHI." This is accurate. However, the architecture provides no mechanism to prevent query-level PHI from being logged, cached, or exposed. Specifically:

1. The Redis cache key is built from `code + terminology + target_terminologies + version`. This is safe. But if a consumer passes patient identifiers alongside the concept code (e.g., in a batch normalization request that includes patient IDs for correlation), those identifiers could end up in CloudWatch Logs via Lambda logging.
2. API Gateway access logs capture request parameters by default. If a consumer includes patient context in query parameters or headers, those are logged in plaintext unless explicitly excluded.
3. Neptune audit logging (mentioned in Prerequisites) captures full query text. If a consumer constructs a query that embeds patient identifiers in the Cypher query string rather than using parameters, Neptune audit logs become a PHI data store.

**Risk:** Under HIPAA, any system that stores or transmits PHI must be covered by the BAA and meet the Security Rule requirements. If Neptune audit logs or API Gateway access logs inadvertently capture patient identifiers, those log stores become PHI repositories requiring encryption, access controls, and retention policies.

**Suggested Fix:** Add a "PHI Boundary" callout in the Architecture section specifying: (1) The normalization API accepts only terminology codes, never patient identifiers. Correlation with patient records happens in the calling system, not in this service. (2) API Gateway request validation should reject requests containing fields outside the defined schema. (3) Lambda logging should use structured logging with an explicit allowlist of loggable fields. (4) Neptune parameterized queries (already shown in the pseudocode) prevent query-string injection of arbitrary data. Frame this as a design principle: the normalization service is a reference data service, not a clinical data service.

---

### FINDING S-2: IAM Permissions Not Resource-Scoped (Severity: MEDIUM)

**Location:** Prerequisites table, IAM Permissions row

**Issue:** The IAM permissions list includes `neptune-db:*` with the note "(scoped to cluster)" but the other permissions (`glue:StartJobRun`, `s3:GetObject`, `s3:PutObject`, `elasticache:*`) have no resource scoping guidance. A Lambda with `s3:GetObject` on `*` can read any S3 object in the account. In a healthcare AWS account that likely contains PHI in other buckets, this is an unnecessary blast radius.

**Suggested Fix:** Add resource ARN patterns for each permission: `s3:GetObject` on `arn:aws:s3:::terminology-raw/*` and `arn:aws:s3:::terminology-processed/*`, `s3:PutObject` on the processed bucket only, `elasticache:*` scoped to the specific cluster ARN, `glue:StartJobRun` scoped to the specific job names. One sentence per permission with the ARN pattern.

---

### FINDING S-3: No Authentication/Authorization on Normalization API (Severity: MEDIUM)

**Location:** Architecture section, "Normalization API" component

**Issue:** The recipe describes API Gateway providing "the REST interface, request validation, and throttling" but never mentions authentication or authorization. In a healthcare enterprise, a terminology normalization service is internal infrastructure. It should not be publicly accessible. The recipe does not specify whether the API Gateway is private (VPC-only), uses IAM authorization, API keys, or Cognito. For a service that could reveal what conditions an organization is querying about (which could be considered business-sensitive even if not PHI), access control matters.

**Suggested Fix:** Specify that the API Gateway should use IAM authorization (SigV4) for service-to-service calls, deployed as a private API accessible only within the VPC. Add a one-line note that API keys alone are insufficient for authorization (they're for throttling, not security). This is a two-sentence addition to the "Why These Services" section under API Gateway.

---

### FINDING S-4: Terminology License Compliance Not Tracked in System (Severity: LOW)

**Location:** Prerequisites table, Terminology Licenses row

**Issue:** The recipe lists licensing requirements (UMLS free with registration, SNOMED free in US, CPT paid, etc.) but the architecture has no mechanism to enforce or track license compliance. If a consumer queries for CPT code mappings and the organization's AMA license has lapsed, the system happily returns results. More critically, if the system is deployed in a non-US jurisdiction where SNOMED CT requires a separate national license, the system has no jurisdiction-awareness.

**Suggested Fix:** Add a note in "The Honest Take" that production deployments should include a terminology access control layer that can restrict which terminologies are queryable based on active licenses. This is a one-paragraph operational consideration, not an architecture change.

---

## Architecture Review

### FINDING A-1: Cache Invalidation Strategy Is Incomplete (Severity: HIGH)

**Location:** Step 4 pseudocode, `redis.set(cache_key, result, ttl=86400)`

**Issue:** The recipe uses a 24-hour TTL on cached normalization results with the justification "terminology releases are at most monthly." This is correct for steady-state operation. However, during a terminology update (when the Step Functions ingestion pipeline loads new data into Neptune), the cache contains stale mappings for up to 24 hours. The recipe acknowledges this problem in "The Honest Take" ("The cache invalidation problem is also non-trivial") but provides no solution in the architecture.

The real danger: during the ICD-10 annual update (October 1 each year), codes are retired and replaced. A cached mapping for a retired code returns the old (now incorrect) result for up to 24 hours after the new terminology is loaded. For a quality reporting system running on October 1, this produces incorrect measure calculations during the cache TTL window.

**Risk:** Silent incorrect results during terminology transitions. The system returns stale mappings with no indication that the underlying data has changed.

**Suggested Fix:** Add a cache invalidation step to the Step Functions ingestion orchestrator. After Neptune bulk load completes successfully: (1) Compute the set of changed concept codes from the terminology delta. (2) Delete the corresponding Redis cache keys. (3) If the delta is too large for selective invalidation (e.g., the annual ICD-10 update touches thousands of codes), flush the entire cache and accept the thundering herd, or implement a cache warming step that pre-populates the top-N most-queried concepts. Add this as Step 7 in the pseudocode walkthrough.

---

### FINDING A-2: SNOMED CT CUI Mapping Confidence of 1.0 Is Incorrect (Severity: HIGH)

**Location:** Step 3 pseudocode, `confidence: 1.0` comment "UMLS CUI-based links are high confidence"

**Issue:** The pseudocode assigns confidence 1.0 to all UMLS CUI-based cross-terminology links. This is clinically incorrect. UMLS CUI assignments are not all equivalence relationships. The UMLS Metathesaurus groups terms under a CUI based on synonymy judgments that are sometimes contested. Specifically:

1. ICD-10-CM codes are often broader than their SNOMED CT counterparts. E11 ("Type 2 diabetes mellitus") maps to CUI C0011860, but SNOMED concept 44054006 is more specific (it excludes certain subtypes that ICD-10 E11 includes). This is a "broader than" relationship, not equivalence, yet the CUI grouping treats them as synonymous.
2. UMLS contains known errors in CUI assignment. The NLM publishes errata with each release. A blanket confidence of 1.0 implies perfect accuracy.
3. The MRREL.RRF file in UMLS provides explicit relationship attributes (REL and RELA fields) that distinguish "SY" (synonymy), "RB" (broader), "RN" (narrower), and "RO" (other related). The pseudocode's `determine_relationship_type` function references these, but then the confidence is set to 1.0 regardless of the relationship type.

**Risk:** Downstream consumers that filter on `confidence >= 0.9` will treat all UMLS-derived mappings as equivalent, including broader-than and narrower-than relationships. This produces incorrect cohort definitions and quality measure calculations.

**Suggested Fix:** Assign confidence based on relationship type: exact synonymy (SY) = 0.95 (not 1.0, because UMLS synonymy judgments have a known error rate of ~2-3%), broader-than (RB) = 0.8, narrower-than (RN) = 0.8, other-related (RO) = 0.6. Reserve confidence 1.0 for manually curated mappings from the curation interface. Update the Expected Results JSON example to show the 0.95 confidence on the SNOMED equivalent rather than the current 0.95 (which is already correct in the example but contradicts the pseudocode's 1.0).

---

### FINDING A-3: Value Set Expansion Has No Result Size Limit (Severity: MEDIUM)

**Location:** Step 5 pseudocode, `expand_value_set` function

**Issue:** The function accepts `max_depth=5` as a traversal limit but has no limit on the number of returned concepts. The "Where it struggles" section correctly notes that broad concepts like "Clinical finding" have hundreds of thousands of descendants. However, the pseudocode has no guard against this. A caller requesting expansion of SNOMED concept 404684003 ("Clinical finding") with `max_depth=5` would attempt to return the majority of SNOMED CT's clinical hierarchy. This would: (1) time out the Neptune query, (2) exhaust Lambda memory if it somehow completes, (3) produce a response too large for API Gateway's 10MB payload limit.

**Suggested Fix:** Add a `max_results` parameter (default 10,000) to the function. After the Neptune query returns, if `len(descendants) > max_results`, return the first `max_results` with a `truncated: true` flag and a `total_available` count. Add a note that callers requesting very broad expansions should use pagination or pre-computed value sets rather than real-time traversal.

---

### FINDING A-4: Neptune Instance Sizing Guidance Is Insufficient (Severity: MEDIUM)

**Location:** Prerequisites table, Cost Estimate row; "Where it struggles" section

**Issue:** The recipe recommends `db.r5.large` (~$700/month) for Neptune. A full UMLS subset with 5M nodes and 20M edges (stated in the performance benchmarks) requires careful instance sizing. The r5.large has 16GB RAM. Neptune's performance is heavily dependent on the working set fitting in the buffer cache. With 5M nodes averaging ~500 bytes each and 20M edges averaging ~200 bytes each, the raw data is approximately 6.5GB. With indexes, the working set is likely 10-12GB. This fits in 16GB, but barely, leaving little headroom for query execution memory.

More critically, the recipe provides no guidance on Neptune read replicas. The normalization API serves real-time queries while the ingestion pipeline performs bulk loads. Without a read replica, bulk loading degrades query performance. The recipe's stated SLA of "sub-100ms for point lookups" is unlikely to hold during a SNOMED CT bulk load (30-60 minutes of sustained write I/O).

**Suggested Fix:** Recommend `db.r5.xlarge` (32GB) as the minimum for a full UMLS deployment, with a read replica for the normalization API. Route API queries to the read replica; route ingestion writes to the primary. Add this to the "Why These Services" section under Neptune. Update the cost estimate to reflect the replica (~$1,400/month for primary + replica).

---

### FINDING A-5: No Fallback for Neptune Unavailability (Severity: MEDIUM)

**Location:** Architecture diagram and Step 4 pseudocode

**Issue:** The normalization service has a single dependency chain: API Gateway -> Lambda -> Redis (cache) -> Neptune (on miss). If Neptune is unavailable (maintenance window, failover, or outage), cache misses result in failed normalization queries. For a service described as "foundational infrastructure" that "every analytics pipeline, every CDS rule, every quality measure depends on," there is no degraded-mode operation.

**Suggested Fix:** Add a fallback strategy in the Lambda: if Neptune is unreachable, return a response with `"source": "cache_only", "stale": true` for cached results, and `"status": "service_degraded"` for cache misses. Consumers can decide whether to proceed with stale data or queue for retry. Mention Neptune's multi-AZ deployment option (automatic failover) in the Prerequisites as the primary availability mechanism, with the cache-only fallback as the secondary.

---

### FINDING A-6: Batch Processing Pattern Not Addressed (Severity: LOW)

**Location:** Step 4 pseudocode (point lookup only)

**Issue:** The recipe provides only a point-lookup API. The "Expected Results" section mentions "batch operations" as a requirement, and the Python companion includes a `batch_normalize` function, but the main recipe's architecture has no batch endpoint. Healthcare analytics pipelines typically need to normalize millions of codes in a batch run (e.g., normalizing all ICD-10 codes on a month's worth of claims). Calling the point-lookup API millions of times is inefficient. The recipe should at least acknowledge the batch pattern architecturally.

**Suggested Fix:** Add a brief "Batch Normalization" subsection under the architecture noting that batch consumers should use a direct Neptune connection (bypassing API Gateway and Lambda) with parallelized Cypher queries, or a pre-computed mapping table exported from Neptune to S3/Athena for SQL-based batch joins. One paragraph is sufficient.

---

## Networking Review

### FINDING N-1: VPC Endpoint for Neptune Not Discussed (Severity: MEDIUM)

**Location:** Prerequisites table, VPC row

**Issue:** The recipe states "Neptune requires VPC deployment. Lambda in same VPC with VPC endpoints for S3 and CloudWatch Logs." This is correct but incomplete. Neptune itself does not use a VPC endpoint (it's accessed via its cluster endpoint within the VPC). However, the recipe does not mention that the Lambda needs a security group allowing outbound TCP 8182 (Neptune's default port) to the Neptune security group. It also does not mention that the ElastiCache Redis cluster needs a security group allowing inbound TCP 6379 from the Lambda security group. These are basic VPC networking requirements that a reader deploying this for the first time would need.

**Suggested Fix:** Add a "Security Groups" row to the Prerequisites table specifying: Lambda SG allows outbound 8182 to Neptune SG, outbound 6379 to ElastiCache SG, and outbound 443 to VPC endpoints. Neptune SG allows inbound 8182 from Lambda SG and Glue SG. ElastiCache SG allows inbound 6379 from Lambda SG. This is a table, not prose.

---

### FINDING N-2: Glue ETL VPC Connectivity to Neptune Not Specified (Severity: MEDIUM)

**Location:** "Why These Services" section, AWS Glue paragraph

**Issue:** The recipe says Glue handles "parsing, transformation, and bulk loading into Neptune." However, Neptune bulk loading uses the Neptune Bulk Loader API, which is an HTTP call to the Neptune cluster endpoint. Glue ETL jobs run in a managed VPC by default and cannot reach resources in your VPC unless you configure a Glue Connection with the appropriate VPC, subnet, and security group. The recipe does not mention this requirement.

Additionally, the Neptune bulk loader reads from S3 directly (Neptune fetches the files, not Glue). So the actual flow is: Glue writes processed files to S3, then calls the Neptune bulk loader API, which tells Neptune to read from S3. Neptune needs an S3 VPC endpoint (Gateway type) and an IAM role with S3 read permissions. None of this is specified.

**Suggested Fix:** Clarify the data flow in the "Why These Services" section: Glue writes to S3, then the Step Functions orchestrator calls the Neptune bulk loader API (not Glue). Neptune reads from S3 using its own IAM role. Add Neptune's S3 access requirements: S3 VPC Gateway endpoint in Neptune's VPC, and a Neptune IAM role with `s3:GetObject` on the processed files bucket. This corrects a subtle but important architectural misunderstanding.

---

### FINDING N-3: No Egress Control Discussion (Severity: LOW)

**Location:** Architecture diagram

**Issue:** The architecture shows terminology sources (UMLS, SNOMED, ICD-10, LOINC, RxNorm) downloading into S3. These downloads come from external NLM/CMS/Regenstrief servers over the public internet. In a healthcare VPC with strict egress controls (common in enterprise environments), these downloads require either a NAT Gateway or a proxy. The recipe does not address how terminology files get into S3 in the first place.

**Suggested Fix:** Add a one-line note that terminology file downloads should happen outside the production VPC (e.g., via a CI/CD pipeline or a separate download Lambda with NAT Gateway access) and land in S3, which is then accessible from the private VPC via the S3 Gateway endpoint. This separates the internet-facing download from the private-VPC processing.

---

## Voice Review

### FINDING V-1: Two Em Dashes Present (Severity: MEDIUM)

**Location:** Multiple locations

**Issue:** The style guide explicitly states "No em dashes. Ever." The recipe contains em dashes in at least two locations:

1. Problem section: "Every one of these systems is describing the same clinical reality (a patient has Type 2 diabetes, takes metformin, had an HbA1c drawn last month) but they're describing it in completely different languages." — No em dash here, this is fine.

Actually, upon careful re-reading, I cannot find em dashes (—) in this recipe. The recipe uses parentheses, colons, and periods as alternatives throughout. The long dashes in the text are hyphens in compound modifiers (e.g., "many-to-many", "version-dependent") which are correct.

**Status:** WITHDRAWN. No em dashes found.

---

### FINDING V-2: Vendor Balance Is Appropriate (Severity: N/A — PASS)

**Location:** Full recipe

**Assessment:** The recipe structure follows the 70/30 split well. The Problem section (~800 words) is entirely vendor-agnostic. The Technology section (~2,500 words) is entirely vendor-agnostic. The General Architecture Pattern (~300 words) is vendor-agnostic. The AWS Implementation section (~3,000 words including pseudocode) is the AWS-specific portion. Rough split: ~3,600 words vendor-agnostic, ~3,000 words AWS-specific. This is closer to 55/45 than 70/30, slightly AWS-heavy.

**Suggested Fix:** The Technology section is strong enough that the slight imbalance is acceptable. If anything, the "Why These Services" section could be trimmed slightly (the Neptune justification is thorough but could lose a sentence or two). Not a blocking issue.

---

### FINDING V-3: Tone Is Consistent and Appropriate (Severity: N/A — PASS)

**Assessment:** The recipe maintains the engineer-explaining-something-cool voice throughout. Good examples: "This is one of those projects where the first 80% feels deceptively easy," "the SQL gets ugly fast and the performance degrades," "You don't get an error message when your diabetes cohort is missing 15% of patients." No documentation-voice creep detected. No marketing language. The parenthetical asides are well-placed and natural.

---

## Stage 2: Expert Discussion

**Conflict: S-1 vs. A-6 (PHI boundary vs. batch processing).** The security review recommends that the normalization API never accept patient identifiers. The architecture review notes that batch consumers need efficient access. These are compatible: batch consumers should use direct Neptune access (which is within the VPC and subject to Neptune's own access controls) rather than the API. The API remains a clean reference-data service. No conflict.

**Overlap: A-1 (cache invalidation) and A-5 (Neptune unavailability).** Both relate to the system's behavior during state transitions. The cache invalidation issue is about data correctness during updates. The Neptune unavailability issue is about service availability. The solutions are complementary: cache invalidation ensures correctness when Neptune is available but data has changed; the degraded-mode fallback ensures availability when Neptune is unreachable. Both should be implemented.

**Priority resolution: A-2 (confidence scoring) vs. A-1 (cache invalidation).** Both are HIGH. A-2 is more dangerous because it produces silently incorrect results in steady-state operation (not just during transitions). A confidence of 1.0 on a broader-than relationship will cause every consumer that trusts high-confidence mappings to treat non-equivalent concepts as equivalent. This is a clinical accuracy issue that affects every query, not just queries during a 24-hour window. A-2 should be fixed first.

---

## Stage 3: Synthesized Feedback

## Verdict: **PASS**

The recipe is architecturally sound, clinically informed, and well-written. The knowledge graph approach is correct for this problem. The UMLS-based normalization strategy is the industry-standard approach. The pseudocode is clear and the progression is logical. The two HIGH findings (A-1 and A-2) are significant but fixable without restructuring the recipe. Neither represents a fundamental architectural flaw.

---

## Prioritized Findings

| ID | Lens | Severity | Title |
|----|------|----------|-------|
| A-2 | Architecture | HIGH | UMLS CUI confidence of 1.0 is clinically incorrect for non-equivalence relationships |
| A-1 | Architecture | HIGH | Cache invalidation during terminology updates produces stale mappings for up to 24 hours |
| S-1 | Security | HIGH | Query-level PHI exposure not addressed; no PHI boundary defined in architecture |
| S-2 | Security | MEDIUM | IAM permissions lack resource-level ARN scoping |
| S-3 | Security | MEDIUM | No authentication/authorization specified on normalization API |
| A-3 | Architecture | MEDIUM | Value set expansion has no result size limit; broad concepts crash the service |
| A-4 | Architecture | MEDIUM | Neptune instance sizing insufficient for full UMLS; no read replica for query isolation |
| A-5 | Architecture | MEDIUM | No fallback for Neptune unavailability on a service described as foundational |
| N-1 | Networking | MEDIUM | Security group requirements for Lambda/Neptune/ElastiCache not specified |
| N-2 | Networking | MEDIUM | Glue-to-Neptune connectivity and Neptune bulk loader S3 access not specified |
| S-4 | Security | LOW | Terminology license compliance not tracked in system |
| A-6 | Architecture | LOW | Batch processing pattern not addressed despite being stated as a requirement |
| N-3 | Networking | LOW | No egress control discussion for terminology file downloads |

---

## Priority Fix List (Recommended Order)

1. **A-2 (Confidence scoring):** Replace blanket 1.0 confidence with relationship-type-based scores. This is a clinical accuracy issue affecting every query. Change the pseudocode comment and the confidence assignment logic. Two-line fix in Step 3.

2. **A-1 (Cache invalidation):** Add a cache invalidation step to the Step Functions orchestrator. Describe selective invalidation for small deltas and full flush for large updates (annual ICD-10). Add as Step 7 in the walkthrough. One paragraph of prose plus a short pseudocode block.

3. **S-1 (PHI boundary):** Add a "PHI Boundary" design principle callout specifying that the normalization service accepts only terminology codes, never patient identifiers. Three sentences in the architecture section plus a note in Prerequisites.

4. **N-2 (Neptune bulk loader flow):** Clarify that Glue writes to S3 and Step Functions calls the bulk loader API. Neptune reads from S3 using its own IAM role. This corrects a subtle architectural misunderstanding that would cause deployment failures.

5. **S-2 (IAM scoping):** Add resource ARN patterns to the IAM permissions row. One sentence per permission.

6. **S-3 (API auth):** Specify IAM authorization (SigV4) and private API deployment. Two sentences in the API Gateway paragraph.

7. **A-3 (Value set size limit):** Add `max_results` parameter to `expand_value_set`. Three lines of pseudocode change.

8. **A-4 (Neptune sizing):** Recommend r5.xlarge + read replica. Update cost estimate. One paragraph.

---

## What the Recipe Gets Right

The problem statement is one of the best in the cookbook so far. It makes a deeply technical infrastructure problem feel urgent and relatable. The "you don't get an error message when your diabetes cohort is missing 15% of patients" line is perfect.

The technology section's explanation of why mapping is hard (granularity mismatch, context dependence, temporal drift, many-to-many, semantic types, composite concepts) is comprehensive and accurate. This is genuinely educational content that would be valuable to anyone entering the healthcare data space.

The choice of Neptune over a relational database is well-justified. The recipe correctly identifies that multi-hop traversals and hierarchy navigation are the core access patterns, and that these are graph-native operations.

The UMLS as starting point, with curation for the last 20%, is the correct operational model. The recipe avoids the trap of presenting UMLS as a complete solution.

The "Honest Take" section is excellent. The observation about version management ("why did this patient's risk score change between last month and this month when nothing clinical changed?") is a real production scenario that most architecture documents miss entirely.

The temporal query capability (Step 6) is a sophisticated feature that most terminology services lack. Including it elevates this recipe above a basic "build a lookup service" tutorial.

---

*Review prepared by the Technical Expert Panel. All findings include actionable fix recommendations.*
