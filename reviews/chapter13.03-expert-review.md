# Expert Review: Recipe 13.3 - ICD/CPT Hierarchy Navigation

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter13.03-icd-cpt-hierarchy-navigation.md`

---

## Overall Assessment

This is a strong recipe. The problem statement is vivid and clinically grounded, the technology section teaches graph databases from first principles without vendor lock-in, and the version management discussion addresses a real operational pain point that most implementations discover too late. The recipe correctly identifies that the hard part is ETL, not the graph queries, which is honest and useful.

However, there are security gaps around IAM scoping, a networking issue with missing VPC endpoints, and several architectural concerns around the openCypher query correctness and cache invalidation strategy. The voice is consistent and the vendor balance is well maintained.

Priority breakdown: 0 must-fix factual errors, 4 significant gaps, 6 improvement recommendations.

---

## Verdict: PASS

---

## Security Expert Review

### What's Done Well

The recipe correctly identifies that code assignments linked to patients are part of the designated record set (PHI-adjacent). BAA requirement is stated. Encryption at rest for Neptune (noted as must-enable-at-creation, which is accurate and important), S3 SSE-KMS, and ElastiCache in-transit and at-rest encryption are all specified. CloudTrail for Neptune API calls and S3 access logging is mentioned. The VPC requirement for Neptune is correctly stated.

### Issue S1: IAM Permissions Overly Broad (HIGH)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The recipe specifies `neptune-db:*` scoped to cluster. While scoped to the cluster ARN, `neptune-db:*` grants all data-plane actions including `neptune-db:DeleteDataViaQuery`, `neptune-db:ResetDatabase`, and `neptune-db:GetEngineStatus`. The query handler Lambda only needs read access (`neptune-db:ReadDataViaQuery`). The ETL Lambda needs write access (`neptune-db:WriteDataViaQuery`). Granting both Lambdas `neptune-db:*` violates least-privilege.

**Suggested fix:** Split IAM permissions by function:
- Query handler Lambda: `neptune-db:ReadDataViaQuery`, `neptune-db:GetQueryStatus`
- ETL Lambda: `neptune-db:WriteDataViaQuery`, `neptune-db:ReadDataViaQuery`, `neptune-db:GetLoaderStatus`
- Neither needs `neptune-db:DeleteDataViaQuery` or `neptune-db:ResetDatabase`

Add a note that Neptune IAM data-plane actions are scoped to the cluster ARN and optionally to specific query actions.

### Issue S2: Redis Cache Contains PHI-Adjacent Data Without Access Controls (MEDIUM)

**Location:** Step 4 pseudocode, cache storage section

**The problem:** The cache stores traversal results (code hierarchies, cross-walks) which are not themselves PHI. However, if the query API is extended to include patient-specific queries (e.g., "what codes has this patient been assigned?"), the same caching pattern would store PHI in Redis without additional access controls. The recipe doesn't draw this boundary explicitly.

More immediately: the cache key construction (`build_cache_key(code, query_type, depth, version)`) doesn't include any tenant or authorization context. If the API serves multiple payers with different cross-walk rules, cached results from one payer's query could be served to another payer.

**Suggested fix:** Add a note that cache keys must include the payer/tenant context when payer-specific cross-walk edges are queried. The current implementation is safe for the base case (public ICD/CPT hierarchy is not payer-specific), but the "Payer-specific rule overlays" variation in the Extensions section would break the cache isolation. Flag this explicitly: "If you implement payer-specific cross-walks, include the payer ID in the cache key to prevent cross-tenant data leakage."

### Issue S3: No Input Validation on Code Parameter (MEDIUM)

**Location:** Step 4 pseudocode, `handle_query` function

**The problem:** The `code` parameter from the REST request is passed directly into the openCypher query string via parameter binding (`$code`). Parameter binding prevents injection (good), but there's no validation that the code parameter matches expected formats (ICD-10 pattern: letter + digits + optional dot + digits; CPT pattern: 5 digits or "CPT:" prefix). Without input validation, the API will execute graph queries for arbitrary strings, which wastes Neptune compute on guaranteed-empty traversals and could be used for enumeration attacks or denial-of-service via expensive wildcard-like patterns.

**Suggested fix:** Add input validation before query construction: validate that the code matches `^[A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$` for ICD-10 or `^(CPT:)?[0-9]{4,5}$` for CPT. Return 400 for invalid formats. Mention this in the pseudocode as a comment: "Validate code format before querying. Reject malformed codes at the API layer."

### Issue S4: Audit Logging for Query Access Not Addressed (LOW)

**Location:** General architecture

**The problem:** CloudTrail captures Neptune API management calls but does not capture individual openCypher queries executed against the database. For compliance auditing ("who queried what codes and when?"), you need Neptune's audit logging feature enabled, which writes query logs to CloudWatch Logs. This is separate from CloudTrail and must be explicitly enabled via a Neptune cluster parameter group (`neptune_enable_audit_log = 1`).

**Suggested fix:** Add to prerequisites: "Enable Neptune audit logging via cluster parameter group (`neptune_enable_audit_log = 1`) for query-level audit trail. CloudTrail captures management-plane actions only; audit logs capture data-plane queries."

---

## Architecture Expert Review

### What's Done Well

The technology section is excellent. The explanation of why medical code systems are naturally graphs, the comparison of property graphs vs. RDF triple stores, and the traversal pattern taxonomy are all well-structured and genuinely educational. The version management approach (SUPERSEDED_BY edges with effective dates rather than table-per-version or valid_from/valid_to columns) is the right architectural choice and well-argued. The honest acknowledgment that ETL is harder than the graph queries is accurate and saves readers from underestimating the project.

### Issue A1: openCypher Query Syntax Errors (HIGH)

**Location:** Step 4 pseudocode, "children" and "crosswalks" queries

**The problem:** The "children" query uses:
```
MATCH path = (start {id: $code})<-[:IS_CHILD_OF*1..$depth]-(descendant)
```

Neptune's openCypher implementation does not support parameterized variable-length path bounds (`*1..$depth`). The upper bound in a variable-length relationship pattern must be a literal integer in Neptune openCypher. You cannot pass it as a parameter. This query will fail at execution time with a syntax error.

Additionally, the "crosswalks" query references `relationship.payer` but the MATCH clause doesn't bind the relationship to a variable:
```
MATCH (start {id: $code})-[:CROSS_WALKS_TO]->(target)
```
Should be:
```
MATCH (start {id: $code})-[r:CROSS_WALKS_TO]->(target)
RETURN ... r.payer AS payer, r.effective AS effective_date
```

**Suggested fix:** For the depth parameter, note that Neptune requires literal bounds. The pseudocode should either use a fixed maximum depth (e.g., `*1..10`) with post-query filtering, or note that the application layer must construct the query string with the depth value interpolated (safely, since it's validated as an integer). For the crosswalks query, bind the relationship to a variable `r` and reference `r.payer` and `r.effective`.

### Issue A2: Cache Invalidation Strategy Incomplete (HIGH)

**Location:** Step 4 pseudocode, cache TTL section

**The problem:** The recipe sets a 24-hour TTL on cached results as a "safety" measure, with the comment that traversals are deterministic per version. But the version update process (Step 5) doesn't invalidate the cache. After the annual ICD update loads new nodes and edges, the cache continues serving stale results for up to 24 hours. For a coding tool, this means a coder could get yesterday's hierarchy for a full day after the October 1 update.

Worse: the cache key includes `version` as a parameter, but the query handler defaults `version` to "current" when not specified. If "current" resolves to the new version after the update, the cache key changes and you get a cold cache (correct but slow). If "current" is a literal string used as the cache key, then the same key maps to different data before and after the update (incorrect).

**Suggested fix:** Clarify the cache invalidation strategy:
1. After Step 5 (version update), flush the Redis cache or at minimum flush keys matching the updated version.
2. Define how "current" resolves in the cache key: either resolve it to the actual version string before cache lookup (so FY2025 and FY2026 are different keys), or use a version pointer that changes atomically when the update completes.
Add a note: "The annual version transition requires cache invalidation. Either flush the entire cache after a successful bulk load, or version-stamp all cache keys with the resolved fiscal year rather than the literal string 'current'."

### Issue A3: Neptune Bulk Loader Idempotency Claim Needs Qualification (MEDIUM)

**Location:** Step 3 pseudocode, comment about idempotency

**The problem:** The recipe states: "The load is idempotent if you use consistent IDs: reloading the same file updates existing nodes rather than creating duplicates." This is partially correct for Neptune's CSV bulk loader in `OVERSUBSCRIBE` mode, but the default mode (`RESUME`) does not update existing nodes. It skips them. And in `NEW` mode, duplicate IDs cause errors.

The behavior depends on the `updateSingleCardinalityProperties` parameter and the load mode. Without specifying these, the idempotency claim is misleading.

**Suggested fix:** Add a note that Neptune bulk loader idempotency depends on the `mode` parameter. For true upsert behavior (update existing nodes with new property values), use `mode=AUTO` with `updateSingleCardinalityProperties=TRUE`. Without this, reloading a file with changed descriptions will not update existing nodes.

### Issue A4: Cost Estimate Missing Neptune I/O Costs (MEDIUM)

**Location:** Prerequisites table, "Cost Estimate" row

**The problem:** The cost estimate lists Neptune instance cost (~$254/month) and ElastiCache (~$50/month) but omits Neptune I/O costs. Neptune charges per I/O request ($0.20 per million I/O requests for on-demand, or provisioned IOPS). For a graph with 500,000 edges and active traversal queries, I/O costs can be significant, especially during cold-cache periods or after version updates when the cache hit rate drops.

**Suggested fix:** Add a line for Neptune I/O: "Neptune I/O: ~$0.20 per million requests. At 1M queries/month with 85% cache hit rate, expect ~150K Neptune I/O requests = negligible. During cache-cold periods (post-update), I/O costs spike temporarily." This helps readers understand why the cache is architecturally important, not just a performance optimization.

### Issue A5: No Pagination in Query Results (LOW)

**Location:** Step 4 pseudocode, Expected Results section

**The problem:** The expected results show `"total_results": 147, "truncated": true` but the pseudocode has no pagination mechanism. There's no `SKIP`/`LIMIT` in the openCypher queries and no cursor-based pagination in the API. A client receiving `"truncated": true` has no way to get the remaining results.

**Suggested fix:** Add `SKIP $offset LIMIT $page_size` to the openCypher queries and accept `offset`/`limit` (or cursor) parameters in the REST API. Mention this in the pseudocode comments: "Production APIs need pagination. Add LIMIT/SKIP to queries and return a cursor or next_offset in the response."

---

## Networking Expert Review

### What's Done Well

The recipe correctly states that Neptune requires VPC deployment and that Lambda functions must be in the same VPC with appropriate security groups. VPC endpoints for S3 and CloudWatch Logs are mentioned. The architecture keeps all data-plane traffic within the VPC (Lambda to Neptune, Lambda to ElastiCache, Lambda to S3 via endpoint).

### Issue N1: Missing VPC Endpoints for API Gateway and KMS (HIGH)

**Location:** Prerequisites table, "VPC" row

**The problem:** The prerequisites mention "VPC endpoints for S3 and CloudWatch Logs" but omit two critical endpoints:

1. **KMS endpoint** (`com.amazonaws.{region}.kms`): S3 uses SSE-KMS. When Lambda in a private subnet reads from or writes to S3 with KMS encryption, it needs to call KMS to decrypt/generate data keys. Without a KMS VPC endpoint, these calls have no route and fail with timeouts or access denied errors.

2. **ElastiCache connectivity**: ElastiCache is accessed via its cluster endpoint within the VPC (no VPC endpoint needed, just security group rules). This is fine but worth a clarifying note since readers might wonder why it's not in the endpoint list.

The recipe also doesn't mention whether the Lambda functions have internet access (NAT Gateway) or are fully private. If fully private (no NAT), the Neptune Loader API call in Step 3 (which is a management-plane HTTPS call to the Neptune service endpoint, not a data-plane call to the cluster) also needs a VPC endpoint for Neptune management (`com.amazonaws.{region}.neptune`).

**Suggested fix:** Add to the VPC prerequisites:
- `com.amazonaws.{region}.kms` (interface endpoint) for S3 SSE-KMS operations
- `com.amazonaws.{region}.execute-api` (interface endpoint) if API Gateway is invoked from within the VPC
- Note that ElastiCache is accessed directly via cluster endpoint within the VPC (no VPC endpoint needed)
- If Lambdas have no internet egress, add `com.amazonaws.{region}.neptune` for the bulk loader management API

### Issue N2: Security Group Rules Not Specified (MEDIUM)

**Location:** Prerequisites table and architecture diagram

**The problem:** The recipe says Lambda must be "in the same VPC with appropriate security groups" but doesn't specify what those security groups need. Neptune, ElastiCache, and VPC interface endpoints all need inbound rules. Readers unfamiliar with VPC networking will struggle to configure this correctly.

Neptune listens on port 8182 (Bolt/HTTP). ElastiCache Redis listens on port 6379. Interface endpoints listen on port 443.

**Suggested fix:** Add a brief security group specification:
- Lambda SG: outbound to Neptune SG on port 8182, outbound to ElastiCache SG on port 6379, outbound to VPC endpoint SG on port 443
- Neptune SG: inbound from Lambda SG on port 8182
- ElastiCache SG: inbound from Lambda SG on port 6379
- VPC Endpoint SG: inbound from Lambda SG on port 443

### Issue N3: Neptune Cluster Endpoint vs. Reader Endpoint Not Discussed (LOW)

**Location:** Architecture section

**The problem:** Neptune clusters have a cluster endpoint (routes to primary/writer) and a reader endpoint (routes to read replicas). The query handler Lambda should use the reader endpoint for traversal queries (read-only). The ETL Lambda should use the cluster endpoint for bulk loads (write). Using the cluster endpoint for all traffic means read queries hit the writer instance, which limits read scalability and can impact write performance during bulk loads.

**Suggested fix:** Add a note in the "Why These Services" section or the code walkthrough: "Use Neptune's reader endpoint for the query handler Lambda (read-only traversals) and the cluster endpoint for the ETL Lambda (bulk loads). This separates read and write traffic and allows adding read replicas for query scaling without impacting the loader."

---

## Voice Reviewer

### What's Done Well

The recipe nails the voice throughout. The opening problem statement ("A coder is staring at a clinical note...") is exactly the right register: specific, human, and builds empathy for the problem before introducing the solution. The technology section teaches without condescending. Parenthetical asides are used well ("(ok, this is a gross oversimplification, but stay with me)" energy without being that explicit). "The Honest Take" section is genuinely honest and self-aware. The 70/30 vendor balance is well maintained: the entire Technology section is vendor-agnostic, and AWS only appears in the implementation half.

### Issue V1: No Em Dashes Found (PASS)

Zero em dashes in the recipe. Clean.

### Issue V2: Minor Doc-Voice Creep in Prerequisites Table (LOW)

**Location:** Prerequisites table, "BAA" row

**The problem:** "AWS BAA signed. Code assignments linked to patients are part of the designated record set." This is fine but slightly more formal/documentation-voice than the rest of the recipe. The rest of the recipe would say something like "You need a BAA in place. Code assignments tied to specific patients are part of the designated record set, which means they're PHI for HIPAA purposes."

**Suggested fix:** Minor. Could be left as-is since tables are naturally more terse. If editing, make it slightly more conversational: "BAA must be signed. Code assignments linked to patients are PHI (part of the designated record set)."

### Issue V3: Vendor Balance Well Maintained (PASS)

The Technology section (approximately 60% of the recipe's prose) is completely vendor-agnostic. AWS services appear only in the implementation section. A reader on GCP (using Cloud Spanner Graph or Neo4j on GKE) or Azure (using Cosmos DB Gremlin API) would learn the graph modeling concepts, traversal patterns, and version management approach without any AWS-specific knowledge. This exceeds the 70/30 target.

---

## Cross-Expert Agreement

The security and networking reviewers both flag the missing KMS VPC endpoint (S1's IAM concern and N1's routing concern are related: even with correct IAM permissions, the call fails without network connectivity to KMS).

The architecture and security reviewers both note the cache key construction issue: A2 (cache invalidation) and S2 (tenant isolation in cache) are two facets of the same problem: the cache key design is too simple for production use.

The architecture reviewer's openCypher syntax issues (A1) would be caught during development but could waste significant debugging time for a reader following the recipe as written.

---

## Prioritized Fix List

### HIGH Severity

| ID | Issue | Expert |
|----|-------|--------|
| S1 | IAM permissions use `neptune-db:*`. Split to read-only for query handler, write for ETL. Least-privilege violation. | Security |
| A1 | openCypher queries have syntax errors: parameterized depth bounds not supported in Neptune; crosswalk query doesn't bind relationship variable. | Architecture |
| A2 | Cache invalidation strategy incomplete. No flush after version update; "current" version resolution in cache key is ambiguous. | Architecture |
| N1 | Missing KMS VPC endpoint (and potentially Neptune management endpoint). Will break S3 SSE-KMS operations in private subnet. | Networking |

### MEDIUM Severity

| ID | Issue | Expert |
|----|-------|--------|
| S2 | Redis cache keys don't include tenant/payer context. Payer-specific cross-walk variation would leak data across tenants. | Security |
| S3 | No input validation on code parameter. Allows arbitrary strings to execute graph queries. | Security |
| A3 | Neptune bulk loader idempotency claim needs qualification. Depends on mode and `updateSingleCardinalityProperties` parameter. | Architecture |
| A4 | Cost estimate omits Neptune I/O costs. Incomplete picture of operational costs. | Architecture |
| N2 | Security group rules not specified. Readers won't know which ports to open between Lambda, Neptune, ElastiCache, and endpoints. | Networking |

### LOW Severity

| ID | Issue | Expert |
|----|-------|--------|
| S4 | Neptune audit logging (`neptune_enable_audit_log`) not mentioned. Needed for query-level compliance auditing. | Security |
| A5 | No pagination mechanism in query API despite showing truncated results. | Architecture |
| N3 | Neptune reader endpoint vs. cluster endpoint not discussed. Read/write traffic separation for scalability. | Networking |
| V2 | Minor doc-voice in Prerequisites table BAA row. Slightly more formal than surrounding prose. | Voice |

---

## What This Recipe Does Well

Worth preserving in final edits:

- The opening problem statement is outstanding. The progression from individual coder frustration to population health analytics to version management builds the case for graphs naturally without feeling like a sales pitch.
- The "Why Medical Code Systems Are Naturally Graphs" subsection is the best explanation of this concept I've seen in a cookbook format. The ICD-10 code structure breakdown (E11 → E11.6 → E11.65 → E11.65x1) makes the hierarchy tangible.
- The comparison of property graphs vs. RDF triple stores is balanced and practical. The recommendation to use property graphs for this use case while acknowledging RDF's strength for SNOMED-CT integration is nuanced and correct.
- The traversal pattern taxonomy (ancestor/descendant, sibling, cross-walk, exclusion, path, temporal) gives readers a vocabulary for their own requirements gathering.
- "The Honest Take" correctly identifies ETL as the hard part and the GEMs mapping ambiguity as the version transition gotcha. Both are genuine production surprises.
- The version management approach (SUPERSEDED_BY edges with effective dates) is architecturally sound and well-explained.
- The cost estimate for Neptune is in the right ballpark for a db.r5.large instance (verified against current pricing).
- All URLs in Additional Resources are real and point to correct AWS documentation pages.

---

*Review completed 2026-05-31. Four expert perspectives: security, architecture, networking, voice.*
