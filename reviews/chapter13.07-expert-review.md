# Expert Review: Recipe 13.7 - Disease-Gene-Drug Relationship Graph

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Review date:** 2026-06-01
**Complexity rating:** Appropriate (Medium-Complex / Production)
**Overall assessment:** PASS

---

## Executive Summary

Recipe 13.7 is an excellent entry in the Knowledge Graphs chapter. The pharmacogenomics framing is clinically accurate and well-motivated. The opening scenario (CYP2D6 poor metabolizer on tamoxifen) is a textbook precision medicine case that immediately grounds the reader in real clinical impact. The technology section is outstanding: it teaches biomedical knowledge graph fundamentals, entity types, evidence grading, and source integration challenges without any vendor references. The AWS implementation is well-architected with appropriate service choices for the stated workload.

The recipe has no critical findings. The domain modeling is correct (CPIC evidence levels, diplotype-to-phenotype translation, phenoconversion). The architecture handles the core challenge (multi-source entity resolution into a versioned, evidence-graded graph) with a sound pipeline pattern. A few high-severity items around IAM scoping, missing VPC endpoint details, and a gap in GINA compliance discussion need attention before publication. Voice is consistent and strong throughout.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review

#### S1 - HIGH: IAM Permission `neptune-db:*` Is Over-Scoped

**Location:** Prerequisites table, "IAM Permissions" row

**Issue:** The recipe specifies `neptune-db:*` as a required permission. This grants all Neptune data-plane actions (ReadDataViaQuery, WriteDataViaQuery, DeleteDataViaQuery, GetQueryStatus, etc.) to any principal that assumes this role. The patient query Lambda (Step 5) only needs read access to the graph. The ETL/bulk load process needs write access. These are fundamentally different trust levels and should not share a single permission set.

Patient genomic data queries should never run under a role that can also modify the knowledge graph. A compromised query Lambda could corrupt the entire pharmacogenomic knowledge base.

**Suggested fix:** Split into role-specific permissions:
- Query Lambda: `neptune-db:ReadDataViaQuery`, `neptune-db:GetQueryStatus`
- Bulk Load Role (Step Functions/Glue): `neptune-db:ReadDataViaQuery`, `neptune-db:WriteDataViaQuery`, `neptune-db:DeleteDataViaQuery`, `neptune-db:GetGraphSummary`
- Add a note: "Never grant `neptune-db:*` in production. The query path (patient-facing) must be read-only. Only the ETL pipeline needs write access, and only during scheduled update windows."

---

#### S2 - HIGH: GINA (Genetic Information Nondiscrimination Act) Compliance Not Adequately Addressed

**Location:** Prerequisites table, "BAA" row

**Issue:** The recipe mentions "Genetic information also protected under GINA" in passing but does not elaborate on the architectural implications. GINA imposes restrictions beyond HIPAA for genetic information, particularly around employment and health insurance discrimination. The system stores patient genetic variants, metabolizer phenotypes, and pharmacogenomic recommendations. This data has heightened sensitivity under GINA.

Specific architectural implications not addressed:
- Access to genetic data should be more restricted than general PHI (not all clinicians with EHR access should see pharmacogenomic results)
- Audit logging for genetic data access may need to be retained longer or reported differently than general PHI access logs
- The API response (Expected Results section) returns `patient_diplotype` and specific variant data; the CDS integration should consider whether the full genotype or only the clinical recommendation needs to be exposed to the ordering clinician

**Suggested fix:** Add a dedicated paragraph after the BAA row or in the Prerequisites section: "GINA considerations: Genetic information (variants, diplotypes, metabolizer phenotypes) has heightened protection under GINA. Implement role-based access control on the query API: pharmacists and pharmacogenomics-trained clinicians receive full genotype detail; ordering physicians receive only the clinical recommendation and evidence level. Log all access to genetic data separately for GINA compliance auditing. Consult your organization's privacy officer for state-specific genetic privacy laws (some states impose stricter requirements than federal GINA)."

---

#### S3 - MEDIUM: No Input Validation on Patient Variant Data in Query Path

**Location:** Step 5 pseudocode, `query_patient_pharmacogenomics`

**Issue:** The query function accepts `patient_variants` and `current_medications` as inputs and passes them into graph queries. The openCypher query in Step 5b uses `$drug_cui` directly in the MATCH clause. While parameterized queries (using `$variable` syntax) prevent Cypher injection, the recipe does not mention input validation on the variant data itself.

Malformed variant identifiers (e.g., an rsID that doesn't match the expected pattern `rs[0-9]+`) could cause unexpected query behavior or return misleading "no findings" results. More critically, if the patient variant data comes from an external lab interface (HL7 feed, FHIR resource), it should be validated against expected formats before graph traversal.

**Suggested fix:** Add input validation before the graph query loop:
```
// Validate input formats before querying
FOR EACH variant IN patient_variants:
    IF NOT matches_pattern(variant.rsid, "rs[0-9]+"):
        log_warning("Invalid rsID format: " + variant.rsid)
        SKIP variant
    IF variant.gene_symbol NOT IN known_pharmacogenes:
        SKIP variant  // Not a pharmacogene, no graph edges to traverse
```

Add a note: "Always validate variant identifiers against expected patterns before graph traversal. Malformed inputs from lab interfaces should be logged and skipped, not passed to Neptune."

---

#### S4 - MEDIUM: Neptune Audit Logging Not Explicitly Enabled

**Location:** Prerequisites table, "CloudTrail" row

**Issue:** The recipe states "All API calls logged. Neptune audit logs enabled for query tracking." This is good guidance but does not specify how to enable Neptune audit logs. Neptune audit logging requires setting `neptune_enable_audit_log=1` in the DB cluster parameter group. It is not enabled by default. The audit logs capture query strings, which in this recipe will contain patient variant identifiers and medication RxNorm codes (PHI).

**Suggested fix:** Expand the CloudTrail row: "CloudTrail for API-level calls. Neptune audit logs enabled via cluster parameter group (`neptune_enable_audit_log=1`), published to CloudWatch Logs. Note: Neptune audit logs will contain patient identifiers embedded in queries; encrypt the CloudWatch Log Group with the same KMS CMK used for Neptune. Set log retention to match your organization's HIPAA audit retention policy (typically 6-7 years)."

---

#### S5 - LOW: No Mention of KMS Key Rotation

**Location:** Prerequisites table, "Encryption" row

**Issue:** The recipe specifies "S3 SSE-KMS for all data at rest. Neptune encryption at rest enabled. TLS 1.2+ in transit." This is correct but does not mention whether to use AWS-managed keys or customer-managed keys (CMKs), nor whether automatic key rotation should be enabled.

**Suggested fix:** Add: "Use a customer-managed KMS key (CMK) with automatic annual rotation enabled. Apply the same CMK to S3, Neptune (specified at cluster creation, cannot be changed later), and CloudWatch Logs. Document the key policy to restrict decrypt access to the specific Lambda execution roles and Glue job roles."

---

### Architecture Expert Review

#### A1 - MEDIUM: Neptune Bulk Load Strategy Lacks Blue-Green Detail

**Location:** Step 6 pseudocode, `run_graph_update_pipeline`

**Issue:** The recipe mentions "using a staging cluster or snapshot-restore" in a comment but does not commit to a strategy. The pseudocode calls `neptune_bulk_load` which loads data into the live cluster. Neptune bulk load is not atomic: during the load, the graph is in an inconsistent state (some new edges loaded, some old edges not yet replaced). If a patient query executes during the load window, it could get partial results from the new version mixed with the old version.

The recipe correctly identifies versioning as important (graph_version in the output) but the actual update mechanism does not guarantee query consistency during updates.

**Suggested fix:** Commit to a specific strategy. Recommended approach for this workload:

"Use Neptune's cloneCluster feature for zero-downtime updates:
1. Clone the production cluster (takes minutes, copy-on-write)
2. Bulk load new data into the clone
3. Run integration tests against the clone
4. Swap the cluster endpoint (update the Lambda environment variable pointing to the Neptune endpoint)
5. Terminate the old cluster after a cooldown period

This ensures production queries always hit a consistent graph version. The clone approach costs ~2x Neptune for the duration of the update window (typically 1-2 hours for a full rebuild)."

Alternatively, if cost is a concern: "Use named graphs or version-tagged subgraphs within a single cluster, and update the query filter to point to the new version atomically (a single Lambda environment variable change)."

---

#### A2 - MEDIUM: No Dead Letter Queue for Failed Patient Queries

**Location:** Architecture diagram, Query Layer

**Issue:** The architecture shows API Gateway to Lambda to Neptune for patient queries. If Neptune is temporarily unavailable (during maintenance, failover, or network partition), the Lambda will fail and the API will return a 500 error to the CDS system. The recipe does not address what happens to the clinical query in this case.

For a clinical decision support system, a failed pharmacogenomics query should not silently disappear. The CDS system needs to know whether the query succeeded (and found no actionable findings) or failed (and the patient might have undetected pharmacogenomic risks). These are clinically different outcomes.

**Suggested fix:** Add error handling guidance: "Configure the Lambda to distinguish between 'no findings' (HTTP 200 with empty findings array) and 'query failed' (HTTP 503 with retry-after header). For failed queries, the CDS system should display a notification: 'Pharmacogenomic check unavailable; manual review recommended.' Log failed queries to an SQS queue for retry when Neptune recovers. Add a CloudWatch alarm on query failure rate exceeding 1% over 5 minutes."

---

#### A3 - MEDIUM: Entity Resolution Ambiguity Handling Is Under-Specified

**Location:** Step 2 pseudocode, `resolve_entities`

**Issue:** The pseudocode calls `queue_for_review(ambiguous)` when entity resolution produces ambiguous mappings. This is correct in principle but the recipe does not address what happens to the graph edges that depend on these ambiguous entities. Are they:
- Excluded from the graph until resolved (conservative, may miss valid relationships)?
- Included with a flag (permissive, may introduce incorrect relationships)?
- Included with reduced evidence level (compromise)?

For a clinical system, this matters. An ambiguous drug mapping that incorrectly merges two different drugs could produce a false pharmacogenomic alert (or worse, miss a real one).

**Suggested fix:** Add after the ambiguous mapping detection:
```
// Ambiguous mappings are EXCLUDED from the graph load until resolved
// This is the conservative approach: better to miss a relationship
// than to create an incorrect one in a clinical system
FOR EACH record IN ambiguous:
    record.status = "pending_review"
    EXCLUDE from graph_load_files

// Track exclusion metrics
log_metric("ambiguous_mappings_excluded", ambiguous.count)
// Alert if exclusion rate exceeds threshold (possible source data issue)
IF ambiguous.count / total_records > 0.05:
    alert_team("Entity resolution ambiguity rate exceeds 5%")
```

---

#### A4 - MEDIUM: Cost Estimate Lacks Neptune Read Replica Consideration

**Location:** Prerequisites table, "Cost Estimate" row

**Issue:** The recipe estimates "Neptune db.r5.large (~$0.58/hr)" which is ~$418/month. For a production pharmacogenomics CDS system that serves real-time queries during clinical workflows, a single Neptune instance is a single point of failure. Neptune supports read replicas for both high availability and read scaling. The recipe does not mention whether a read replica is recommended.

Given that the query workload (patient pharmacogenomics lookups) is entirely read-only and the write workload (graph updates) is periodic (weekly/quarterly), a read replica makes architectural sense: queries hit the replica, bulk loads hit the primary.

**Suggested fix:** Add to the cost estimate: "Production recommendation: Add one read replica (~$0.58/hr additional) for high availability and to separate query traffic from bulk load operations. Total Neptune cost: ~$836/month. The read replica also provides automatic failover if the primary instance fails during a graph update."

---

#### A5 - LOW: Performance Benchmark of 200-500ms Lacks Context

**Location:** Expected Results, Performance Benchmarks table

**Issue:** The "200-500ms" query latency is stated without specifying whether this includes Lambda cold start, API Gateway overhead, or just the Neptune traversal time. For a CDS integration, the end-to-end latency (from EHR request to response) matters more than the Neptune query time alone. Lambda cold start in a VPC adds 1-3 seconds. API Gateway adds 10-30ms.

**Suggested fix:** Clarify: "Query latency (Neptune traversal only): 200-500ms. End-to-end latency (API Gateway + Lambda + Neptune): 500-800ms warm, 2-4 seconds on cold start. For CDS integration requiring sub-second response, configure Lambda Provisioned Concurrency (2-5 instances) to eliminate cold starts."

---

### Networking Expert Review

#### N1 - HIGH: VPC Endpoint List Is Incomplete

**Location:** Prerequisites table, "VPC" row

**Issue:** The recipe states "VPC endpoints for S3 and Glue." This is incomplete. The architecture uses Lambda in a VPC connecting to multiple AWS services. Without VPC endpoints, the Lambda functions need a NAT Gateway for internet access, which introduces PHI egress risk and adds cost.

Missing VPC endpoints:
- `com.amazonaws.{region}.kms` (Interface) - Lambda needs KMS for envelope encryption/decryption
- `com.amazonaws.{region}.logs` (Interface) - Lambda needs CloudWatch Logs for logging
- `com.amazonaws.{region}.monitoring` (Interface) - CloudWatch metrics
- `com.amazonaws.{region}.states` (Interface) - Step Functions state reporting
- `com.amazonaws.{region}.events` (Interface) - EventBridge for schedule triggers

The recipe mentions "VPC endpoints for S3 and Glue" but Glue does not have a VPC endpoint for the Glue API itself (Glue jobs run in their own managed VPC). The correct endpoint is for the Glue Data Catalog if Lambda needs to access it.

**Suggested fix:** Replace the VPC endpoint statement with:
```
VPC Endpoints Required:
- com.amazonaws.{region}.s3              (Gateway - for bulk load files, source data)
- com.amazonaws.{region}.dynamodb        (Gateway - if using DynamoDB for query caching)
- com.amazonaws.{region}.neptune-db      (Interface - Neptune query access, if using IAM auth)
- com.amazonaws.{region}.kms             (Interface - envelope encryption)
- com.amazonaws.{region}.logs            (Interface - CloudWatch Logs)
- com.amazonaws.{region}.monitoring      (Interface - CloudWatch Metrics)
- com.amazonaws.{region}.states          (Interface - Step Functions)
- com.amazonaws.{region}.events          (Interface - EventBridge)

Neptune is VPC-native and accessed via its cluster endpoint DNS within the VPC.
No NAT Gateway should be required for the query path.
```

---

#### N2 - MEDIUM: No Security Group Guidance

**Location:** Prerequisites table, "VPC" row

**Issue:** The recipe states "Neptune must run in VPC. Lambda in same VPC with Neptune access" but provides no security group configuration. Neptune listens on port 8182. Without explicit guidance, implementers may open port 8182 to the entire VPC CIDR or even 0.0.0.0/0 within the VPC.

**Suggested fix:** Add: "Security groups: Neptune cluster SG allows inbound TCP 8182 only from the Lambda SG. Lambda SG allows outbound TCP 8182 to Neptune SG and outbound TCP 443 to VPC endpoint SGs. No inbound rules on Lambda SG (Lambda is invoked by the service, not by inbound connections). Glue ETL jobs run in a Glue-managed VPC and access Neptune via a Glue connection configured with the Neptune SG."

---

#### N3 - LOW: No Mention of Multi-AZ for Neptune

**Location:** Architecture section

**Issue:** Neptune supports Multi-AZ deployments with automatic failover. For a clinical decision support system, a single-AZ deployment means a full AZ outage takes down pharmacogenomic queries. The recipe does not mention AZ considerations.

**Suggested fix:** Add a brief note: "Deploy Neptune with a read replica in a different AZ for automatic failover. Neptune Multi-AZ failover typically completes in under 30 seconds. The query Lambda should use the Neptune reader endpoint for read queries to automatically route to available replicas."

---

### Voice Reviewer

#### V1 - MEDIUM: Slight Doc-Voice in "Why These Services" Neptune Paragraph

**Location:** "Why These Services" section, first paragraph

**Issue:** The opening sentence "Neptune supports both property graph (openCypher/Gremlin) and RDF (SPARQL) query models" reads like AWS documentation. The rest of the recipe has excellent voice (the CYP2D6 career-questioning joke in "The Honest Take" is peak CC voice), but this section is noticeably more formal.

**Quoted text:** "Neptune supports both property graph (openCypher/Gremlin) and RDF (SPARQL) query models. For a biomedical knowledge graph with complex ontological relationships and evidence-graded edges, the property graph model (openCypher) provides a good balance of expressiveness and query performance."

**Suggested fix:** Rewrite with more personality: "Neptune speaks two graph languages: property graph (openCypher or Gremlin) and RDF (SPARQL). For pharmacogenomics, property graph wins. Your queries read like the clinical question you're actually asking: 'start at this variant, traverse to the gene, find drugs metabolized by that gene, filter by evidence level.' openCypher makes that traversal pattern natural. RDF would work but you'd be fighting the query language instead of the biology."

---

#### V2 - LOW: No Em Dashes Found

**Location:** Full recipe

**Issue:** None. Scanned the entire recipe for em dashes (U+2014). Zero found. The recipe uses colons, semicolons, parentheses, and sentence restructuring throughout. Well done.

---

#### V3 - LOW: Vendor Balance Is Excellent

**Location:** Full recipe

**Issue:** None. The recipe structure follows the 70/30 split exceptionally well. "The Problem" and "The Technology" sections (which constitute roughly 60% of the recipe's word count) are entirely vendor-agnostic. The technology section teaches biomedical knowledge graph concepts, entity types, evidence grading frameworks (CPIC, ClinVar, PharmGKB levels), and source integration challenges without mentioning any cloud provider. A reader building on Neo4j, Azure Cosmos DB Gremlin API, or JanusGraph would learn the pharmacogenomics domain modeling equally well.

---

#### V4 - LOW: Voice Is Strong and Consistent

**Location:** Full recipe

**Issue:** None. The recipe demonstrates excellent CC voice throughout. Specific highlights:
- "CYP2D6 alone will make you question your career choices" (The Honest Take)
- "The entity resolution is 60% of the work" (honest, specific, saves the reader time)
- "Evidence levels are political, not just scientific" (insight that only comes from experience)
- The opening patient scenario is compelling without being melodramatic

The recipe reads like an engineer who has actually built a pharmacogenomics system explaining what they learned. This is exactly the target voice.

---

## Stage 2: Expert Discussion

**Conflict: None identified.** The security, architecture, and networking findings are complementary and non-overlapping. The GINA finding (S2) is healthcare-specific and does not conflict with any architectural recommendation.

**Overlap: Networking N1 (VPC endpoints) and Architecture A4 (read replica).** If a read replica is added per A4, the VPC endpoint configuration in N1 applies to both the primary and replica subnets. These are additive, not conflicting.

**Priority resolution:** The GINA compliance gap (S2) is the most healthcare-specific finding and represents a regulatory risk unique to genetic data. The IAM over-scoping (S1) is the most likely to be flagged in a security review. The VPC endpoint incompleteness (N1) is the most likely to cause deployment failures (Lambda timeouts in VPC without proper endpoints). All three HIGH items address different risk categories and all require fixes.

**Domain accuracy note:** The pharmacogenomics content is clinically accurate. The CYP2D6/tamoxifen example is correct (CPIC Level A, strong recommendation to use alternative). The evidence level framework (CPIC, ClinVar, PharmGKB) is accurately described. The diplotype-to-phenotype translation discussion correctly identifies the complexity of star allele systems. The phenoconversion concept (drug-induced enzyme inhibition changing effective phenotype) is a real clinical concern that many pharmacogenomics systems miss. The recipe demonstrates genuine domain expertise.

---

## Stage 3: Synthesized Feedback

### Verdict: PASS

The recipe has 0 CRITICAL findings and 3 HIGH findings (threshold for FAIL is >3 HIGH). The recipe passes with required fixes before publication.

### Prioritized Findings

| # | Severity | Expert | Location | Issue | Fix |
|---|----------|--------|----------|-------|-----|
| S1 | HIGH | Security | Prerequisites, IAM row | `neptune-db:*` grants all data-plane actions to query and ETL roles alike | Split into read-only (query Lambda) and read-write (ETL pipeline) roles |
| S2 | HIGH | Security | Prerequisites, BAA row | GINA compliance implications for genetic data not architecturally addressed | Add GINA-specific access control, audit logging, and data minimization guidance |
| N1 | HIGH | Networking | Prerequisites, VPC row | VPC endpoint list incomplete (missing KMS, Logs, States, Events, Monitoring) | Enumerate all required VPC endpoints; remove incorrect Glue endpoint reference |
| S3 | MEDIUM | Security | Step 5 pseudocode | No input validation on patient variant data before graph queries | Add format validation for rsIDs, gene symbols, and RxNorm CUIs |
| S4 | MEDIUM | Security | Prerequisites, CloudTrail row | Neptune audit log enablement not specified | Add parameter group setting and PHI-in-logs encryption guidance |
| A1 | MEDIUM | Architecture | Step 6 pseudocode | Bulk load strategy lacks consistency guarantee during updates | Commit to clone-and-swap or versioned subgraph approach |
| A2 | MEDIUM | Architecture | Architecture diagram, Query Layer | No error handling or DLQ for failed patient queries | Add failure mode distinction and retry queue for CDS integration |
| A3 | MEDIUM | Architecture | Step 2 pseudocode | Ambiguous entity resolution handling under-specified | Specify conservative exclusion strategy with alerting threshold |
| A4 | MEDIUM | Architecture | Prerequisites, Cost row | No read replica recommendation for HA | Add read replica for failover and query/write separation |
| N2 | MEDIUM | Networking | Prerequisites, VPC row | No security group configuration guidance | Add port 8182 restriction and Lambda SG outbound rules |
| V1 | MEDIUM | Voice | "Why These Services" section | Doc-voice creep in Neptune description | Rewrite with conversational tone matching rest of recipe |
| S5 | LOW | Security | Prerequisites, Encryption row | No KMS key rotation or CMK vs AWS-managed guidance | Specify CMK with automatic annual rotation |
| A5 | LOW | Architecture | Performance Benchmarks | 200-500ms latency lacks cold start context | Clarify Neptune-only vs end-to-end latency; mention Provisioned Concurrency |
| N3 | LOW | Networking | Architecture section | No Multi-AZ guidance for Neptune | Add Multi-AZ with read replica for automatic failover |
| V2 | LOW | Voice | Full recipe | Em dash check | None found. Pass. |
| V3 | LOW | Voice | Full recipe | Vendor balance check | Excellent 70/30 split. Pass. |
| V4 | LOW | Voice | Full recipe | Voice consistency check | Strong CC voice throughout. Pass. |

### Priority Fixes Before Publication

1. **IAM least-privilege (S1)** - Query path must be read-only. A compromised query Lambda should not be able to corrupt the knowledge graph.
2. **GINA compliance (S2)** - Genetic data has heightened regulatory protection. The recipe must address this architecturally, not just mention it in passing.
3. **VPC endpoint completeness (N1)** - Missing endpoints will cause Lambda timeouts in VPC deployment. The current list is incorrect (Glue doesn't have a relevant endpoint for this pattern).
4. **Bulk load consistency (A1)** - Clinical queries during graph updates could return partial/incorrect results. Commit to a zero-downtime update strategy.
5. **Query failure handling (A2)** - CDS systems must distinguish "no findings" from "system unavailable" for patient safety.

### Strengths Worth Noting

- The pharmacogenomics domain modeling is clinically accurate and comprehensive. The CYP2D6/tamoxifen scenario, evidence level frameworks, diplotype-to-phenotype translation, and phenoconversion discussion all demonstrate genuine domain expertise.
- The technology section is one of the strongest in the cookbook. It teaches biomedical knowledge graph concepts from first principles, explains why each entity type and relationship type matters, and honestly addresses the challenges (evolving knowledge, population-specific frequencies, conflicting evidence) without hand-waving.
- The "Honest Take" section is exceptional. "CYP2D6 alone will make you question your career choices" is both funny and true. The observation that entity resolution is 60% of the work will save readers months of misallocated planning effort.
- The evidence grading discussion (CPIC levels, ClinVar classifications, PharmGKB levels) is accurate and practically useful. The guidance to never fire CDS alerts on Level 4 case reports directly addresses the alert fatigue problem that plagues pharmacogenomics implementations.
- The phenoconversion discussion (Step 5c) is a sophisticated clinical concept that many pharmacogenomics systems miss entirely. Including it demonstrates that the recipe was written by someone who understands the clinical workflow, not just the technology.
- Cross-references to related recipes (13.4 Drug-Drug Interaction, 13.8 Concept Normalization, 13.9 Literature-Derived KG) create a coherent chapter narrative and show how the recipes build on each other.

---

*Review complete. Pseudocode simplifications are acknowledged and not critiqued as such.*
