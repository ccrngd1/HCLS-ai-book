# Expert Review: Recipe 13.1 - Drug Formulary Navigation

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter13.01-drug-formulary-navigation.md`

---

## Overall Assessment

This is an excellent opening recipe for the Knowledge Graphs chapter. The problem statement is vivid and relatable, the technology explanation is genuinely educational (the relational-vs-graph comparison is the best I've seen in this cookbook), and the honest take section delivers real operational wisdom about the 20/80 split between building and maintaining the graph. The formulary domain is well-chosen: structured source data, clear graph traversal patterns, and measurable business value.

However, there are security gaps around PHI handling at query time, an architectural concern about Neptune IAM permissions being overly broad, and a networking gap that would break the Lambda-to-Neptune connection in a properly locked-down VPC. No critical findings, but several high-severity issues that need attention before publication.

Priority breakdown: 0 must-fix factual errors, 3 significant gaps, 5 improvement recommendations.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

The recipe correctly identifies that formulary data alone may not be PHI but becomes PHI-adjacent when combined with patient plan membership at query time. The BAA requirement is noted. Encryption at rest for Neptune, S3, and ElastiCache is specified. The note that Neptune encryption must be enabled at cluster creation (cannot be added later) is a valuable gotcha that saves readers from a painful discovery. CloudTrail logging is required.

### Issue S1: IAM Permissions Are Not Least-Privilege (HIGH)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The recipe specifies `neptune-db:*` scoped to the cluster. This grants all Neptune data-plane actions including `neptune-db:DeleteDataViaQuery`, `neptune-db:GetEngineStatus`, and administrative operations. The query Lambda only needs `neptune-db:ReadDataViaQuery` (and possibly `neptune-db:WriteDataViaQuery` for the loader Lambda, separately). Granting `neptune-db:*` to the query resolver violates least-privilege and would fail a SOC 2 or HITRUST audit.

**Suggested fix:** Split into two IAM policies:
- Query Lambda: `neptune-db:ReadDataViaQuery`, `neptune-db:connect` (scoped to cluster ARN)
- Loader Lambda: `neptune-db:ReadDataViaQuery`, `neptune-db:WriteDataViaQuery`, `neptune-db:connect` (scoped to cluster ARN)

Add a note that Neptune IAM authentication should be enabled on the cluster (`--enable-iam-db-authentication`) to enforce these permissions.

### Issue S2: PHI Exposure in Redis Cache Keys and Values (HIGH)

**Location:** Step 4 pseudocode (caching section) and ElastiCache architecture

**The problem:** The cache key is `"alternatives:" + drug_id + ":" + plan_id`. The plan_id identifies a specific patient's insurance plan. When combined with the drug being queried, this creates a record of "patient X's plan was queried for drug Y," which is arguably a medication inquiry linked to a covered entity's member. The cached result also contains the full alternative list, which in context reveals what the patient was prescribed.

More critically, there's no mention of Redis AUTH or access control. ElastiCache Redis in a VPC is network-isolated, but if any other workload shares that VPC, the cache is readable without authentication.

**Suggested fix:** 
1. Add a note that ElastiCache AUTH (Redis AUTH token or IAM-based access control via ElastiCache for Redis 7.0+) should be enabled.
2. Acknowledge that cache keys containing plan_id create an access pattern log. If the plan_id is member-specific (not just a plan type identifier), the cache effectively logs medication inquiries per member. Recommend using a plan-type identifier rather than a member-specific plan ID in cache keys where possible, or document the PHI implications if member-specific caching is required.
3. Mention that ElastiCache encryption in-transit (TLS) is required for the Lambda-to-Redis connection, not just at-rest.

### Issue S3: No Input Validation on API Parameters (MEDIUM)

**Location:** Step 5 pseudocode (`handle_formulary_query` function)

**The problem:** The API handler extracts `drug_id` and `plan_id` directly from request parameters and passes them into an openCypher query. While openCypher parameterized queries (using `$drug_id`) prevent injection in the same way SQL parameterized queries do, the recipe doesn't mention this protection or explain why it matters. A reader unfamiliar with graph query injection might build a string-concatenated query instead of using parameters.

Additionally, there's no validation that `drug_id` and `plan_id` conform to expected formats (RxNorm CUI pattern, plan ID pattern). Malformed inputs could cause confusing Neptune errors rather than clean API responses.

**Suggested fix:** Add a brief comment in the pseudocode noting that parameterized queries prevent injection, and add input validation (regex check on drug_id format, plan_id format) before the query executes. A one-liner in the honest take about graph injection being a real concern if you build queries via string concatenation would also help.

### Issue S4: Audit Logging at the Application Layer (MEDIUM)

**Location:** Prerequisites table mentions CloudTrail, but no application-level audit logging

**The problem:** CloudTrail logs API calls to AWS services (Neptune API operations, S3 access), but it does not log individual openCypher queries or which drug/plan combinations were queried. For HIPAA audit requirements, you need to know "who queried what drug for which plan at what time." This requires application-level logging in the query Lambda, not just CloudTrail.

**Suggested fix:** Add a note in the Prerequisites or the Honest Take that the query Lambda should log each request (timestamp, requesting user/system, drug_id, plan_id) to CloudWatch Logs or a dedicated audit store. Mention that these logs themselves may contain PHI-adjacent data and should be encrypted and retained per HIPAA retention policies.

---

## Architecture Expert Review

### What's Done Well

The architecture is sound for the stated scale. The separation of concerns (parse pipeline vs. query API vs. cache layer) is clean. The cache-in-front-of-graph pattern is the right call for a read-heavy workload with infrequent writes. The honest acknowledgment of Neptune cold-start latency with Lambda is valuable. The versioned subgraph suggestion for temporal data is architecturally mature. The cost estimate is reasonable for a single-plan deployment.

### Issue A1: Missing Dead Letter Queue for Formulary Parse Pipeline (HIGH)

**Location:** Architecture diagram and Step 1-2 pipeline description

**The problem:** The pipeline is: S3 event -> Lambda parser -> Neptune bulk load. If the parser Lambda fails (malformed file, Neptune connection timeout, partial load), there's no retry mechanism or dead letter queue. A failed formulary load is a significant operational event: prescribers would be querying stale data without knowing it. The recipe doesn't mention error handling for the ingest pipeline at all.

**Suggested fix:** Add an SQS dead letter queue on the S3 event notification (or on the Lambda's async invocation configuration). Mention that a failed load should trigger a CloudWatch alarm. For the quarterly full reload, recommend Step Functions (already mentioned as optional) as mandatory for production, since it provides built-in retry, error handling, and execution history. Add a brief note about idempotency: if the load is retried, MERGE operations prevent duplicates, but partial loads could leave the graph in an inconsistent state without transaction boundaries.

### Issue A2: Single-AZ Redis Creates Availability Gap (MEDIUM)

**Location:** Architecture diagram and ElastiCache description

**The problem:** The recipe mentions ElastiCache but doesn't specify Multi-AZ replication. Neptune is described as Multi-AZ, but if Redis is single-AZ and the AZ fails, all queries become cache misses simultaneously, causing a thundering herd on Neptune. For a system that prescribers depend on at the point of care, this availability gap matters.

**Suggested fix:** Specify ElastiCache with Multi-AZ automatic failover (replication group with at least one replica in a different AZ). One sentence in the Prerequisites or Ingredients table is sufficient.

### Issue A3: Cost Estimate Doesn't Scale to Multi-Plan Reality (LOW)

**Location:** Prerequisites table, "Cost Estimate" row

**The problem:** The estimate says "~$400/month for a single-plan deployment." But the recipe discusses multi-plan support in the Variations section and the Honest Take mentions "many plans with different formularies" affecting cache hit rate. A health system or PBM would have dozens to hundreds of plans. The cost estimate doesn't acknowledge that Neptune instance size needs to grow with graph size (more plans = more vertices and edges) or that cache memory needs grow with plan count.

**Suggested fix:** Add a brief scaling note: "For multi-plan deployments (10+ plans), expect Neptune db.r5.xlarge or larger (~$500-700/month) and proportionally larger Redis instances. Graph size scales roughly linearly with plan count."

---

## Networking Expert Review

### What's Done Well

The recipe correctly states that Neptune requires VPC deployment and that Lambda resolvers must be in the same VPC. VPC endpoints for S3 and CloudWatch Logs are mentioned. TLS for all API calls is specified.

### Issue N1: Missing Neptune VPC Endpoint Configuration (HIGH)

**Location:** Prerequisites table, "VPC" row

**The problem:** The recipe says "Lambda resolvers must be in the same VPC with appropriate security groups" but doesn't mention that Lambda functions in a VPC lose internet access by default. The query Lambda needs to reach Neptune (VPC-internal, fine), Redis (VPC-internal, fine), but also needs to write CloudWatch Logs and potentially reach other AWS services. The recipe mentions "VPC endpoints for S3 and CloudWatch Logs" but doesn't mention that without a NAT gateway or these VPC endpoints, the Lambda function cannot write logs or access any AWS service outside the VPC.

More specifically, Neptune's endpoint is accessed via its cluster endpoint DNS name within the VPC. There's no "VPC endpoint for Neptune" in the same sense as S3 or DynamoDB gateway endpoints. The Lambda connects directly to Neptune's private IP within the VPC. This is fine, but the recipe should clarify the networking model.

**Suggested fix:** Expand the VPC section to specify:
1. Lambda functions in private subnets (no direct internet access)
2. VPC endpoints required: S3 (gateway), CloudWatch Logs (interface), and optionally STS (interface, if IAM auth is used for Neptune)
3. Security group configuration: Lambda SG -> Neptune SG on port 8182 (Bolt/WebSocket), Lambda SG -> Redis SG on port 6379
4. If the Lambda needs internet access (e.g., for RxNorm API calls during enrichment), a NAT gateway is required

### Issue N2: No Mention of Neptune Endpoint Type (LOW)

**Location:** Architecture section

**The problem:** Neptune offers cluster endpoints (writer), reader endpoints (read replicas), and instance endpoints. For the query Lambda (read-only), the reader endpoint should be used to distribute load across read replicas. For the loader Lambda (write), the cluster endpoint is required. The recipe doesn't distinguish between these, which means a reader might point both Lambdas at the cluster (writer) endpoint, missing the read scaling benefit.

**Suggested fix:** One sentence noting that the query Lambda should use the reader endpoint (`your-cluster.cluster-ro-xxxxx.region.neptune.amazonaws.com`) and the loader Lambda should use the writer endpoint (`your-cluster.cluster-xxxxx.region.neptune.amazonaws.com`).

---

## Voice Reviewer

### What's Done Well

The voice is strong throughout. The opening scenario (atorvastatin/rosuvastatin) is exactly the right hook: specific, relatable, and it builds frustration before offering the solution. The "That's a graph problem" pivot is clean. The relational-vs-graph comparison is genuinely educational without being condescending. The Honest Take section delivers the signature self-deprecating expertise ("building the graph is maybe 20% of the work"). Parenthetical asides are used well. No documentation-voice detected. No marketing language.

### Issue V1: No Em Dashes Found (PASS)

Zero em dashes in the document. Clean.

### Issue V2: Vendor Balance Is Appropriate (PASS)

The Technology section is fully vendor-agnostic (mentions Neo4j, TigerGraph, Blazegraph, Stardog alongside Neptune). The General Architecture Pattern section has no AWS service names. AWS enters only in "The AWS Implementation" section. Estimated split: ~65% vendor-agnostic, ~35% AWS-specific. Within acceptable range of the 70/30 target.

### Issue V3: Minor Tone Inconsistency in "Where the Field Is Today" (LOW)

**Location:** Last paragraph of "Where the Field Is Today" subsection

**The problem:** The sentence "The main challenge isn't the technology. It's the data pipeline" is good, but the paragraph then shifts to a slightly more formal register ("reconciling differences between the formulary file... and the actual adjudication behavior") compared to the conversational tone of the rest. It reads like a summary paragraph from a white paper rather than the engineer-at-the-whiteboard voice.

**Suggested fix:** Minor rewrite to maintain the conversational register. Something like: "The main challenge isn't the technology. It's keeping the graph honest. The formulary file says one thing; the PBM's adjudication system sometimes does another. More on that gap in the honest take."

---

## Stage 2: Expert Discussion

### Overlapping Concerns

1. **Security (S2) and Architecture (A2) overlap on Redis:** The security concern about PHI in cache and the architecture concern about single-AZ both point to Redis needing more attention. The fix is complementary: add Multi-AZ, add AUTH, add TLS in-transit, and document the PHI implications of cache keys.

2. **Security (S1) and Networking (N1) overlap on Neptune access control:** The IAM least-privilege issue (S1) and the VPC endpoint/security group issue (N1) are two layers of the same defense-in-depth story. Neptune IAM auth + proper security groups + VPC isolation together provide the access control model. The recipe should present these as a coherent security posture, not isolated checkboxes.

3. **Architecture (A1) and the Honest Take overlap on operational concerns:** The missing DLQ (A1) connects to the recipe's own acknowledgment that "keeping it current is 80%." The recipe identifies the problem (mid-quarter amendments, keeping the graph fresh) but doesn't provide the architectural guardrails (error handling, retry, alerting) to make that maintenance reliable.

### Priority Resolution

The Security and Networking issues around Neptune access (S1, N1) should be addressed together as a coherent "securing Neptune access" subsection in Prerequisites. The Redis issues (S2, A2) should be addressed together. The DLQ issue (A1) is independent and should be added to the architecture diagram and pipeline description.

---

## Stage 3: Synthesized Feedback

## Verdict: **PASS**

The recipe is architecturally sound, clinically accurate in its formulary domain modeling, and well-written. The knowledge graph approach is clearly the right tool for this problem, and the recipe does an excellent job explaining why. No critical findings. Three HIGH findings that should be addressed before publication but none that indicate fundamental architectural or clinical errors.

---

## Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Prerequisites, IAM row | `neptune-db:*` is not least-privilege; grants delete and admin operations to query Lambda | Split into read-only (query) and read-write (loader) IAM policies; enable Neptune IAM authentication |
| 2 | HIGH | Security | Step 4, caching section | PHI exposure risk in Redis: no AUTH, no TLS in-transit mentioned, cache keys with plan_id create medication inquiry logs | Add Redis AUTH, require TLS in-transit, document PHI implications of cache key design |
| 3 | HIGH | Architecture | Steps 1-2, ingest pipeline | No error handling, DLQ, or alerting for failed formulary loads; stale data served silently | Add SQS DLQ, CloudWatch alarm on load failure, recommend Step Functions for production loads |
| 4 | MEDIUM | Security | Step 5, API handler | No input validation on drug_id/plan_id; no mention of parameterized query protection against injection | Add input validation, add comment explaining parameterized queries prevent injection |
| 5 | MEDIUM | Security | Prerequisites | No application-level audit logging for individual queries; CloudTrail doesn't capture openCypher query content | Add requirement for query-level audit logging in Lambda with PHI-appropriate retention |
| 6 | MEDIUM | Architecture | ElastiCache config | Single-AZ Redis creates thundering herd risk on AZ failure | Specify Multi-AZ replication group with automatic failover |
| 7 | MEDIUM | Networking | Prerequisites, VPC row | Incomplete VPC guidance: missing security group rules, endpoint types, NAT gateway consideration | Expand VPC section with specific SG rules, required interface endpoints, and NAT guidance |
| 8 | LOW | Architecture | Prerequisites, Cost row | Cost estimate only covers single-plan; doesn't acknowledge multi-plan scaling | Add scaling note for 10+ plan deployments |
| 9 | LOW | Networking | Architecture section | No distinction between Neptune reader and writer endpoints | Add one sentence directing query Lambda to reader endpoint, loader to writer endpoint |
| 10 | LOW | Voice | "Where the Field Is Today" | Minor register shift to white-paper tone in final paragraph | Rewrite to maintain conversational voice |

---

## Summary

Strong recipe. The formulary domain modeling is accurate (P&T committees, quarterly refresh cycles, PBM adjudication gaps are all real). The graph approach is well-justified and the relational comparison is genuinely educational. The three HIGH findings are all security/reliability hardening issues rather than fundamental design problems. Address the IAM scoping, Redis security posture, and ingest pipeline error handling, and this is ready for publication.
