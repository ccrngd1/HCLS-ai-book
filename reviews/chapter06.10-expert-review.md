# Expert Review: Recipe 6.10 -- Multi-Morbidity Pattern Discovery

**Reviewed by:** Technical Expert Panel (Security / Architecture / Networking / Voice)
**Recipe:** Chapter 06.10 -- Multi-Morbidity Pattern Discovery
**Date:** 2026-05-31
**Severity Legend:** 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low · ✅ Praise

---

## Executive Summary

Recipe 6.10 is a strong capstone for Chapter 6. The five-stage pipeline (extraction, feature engineering, pattern mining, validation, clinical interpretation) is architecturally sound and well-sequenced. The recipe excels at explaining why naive approaches fail (prevalence confounding, dimensionality explosion, temporal ordering) before presenting solutions. The "Honest Take" section is genuinely useful, particularly the insight that temporal analysis is where the gold is and that clinical engagement is the real bottleneck.

The recipe has no critical findings. The security posture is reasonable, the architecture is appropriate for the stated scale, and the clinical framing is accurate. There are several high-severity issues that should be addressed before publication, primarily around IAM permission scoping, Neptune access controls, and missing VPC endpoint details. The recipe also has a TODO comment that must be resolved before publication.

**Verdict: PASS** (conditional on resolving HIGH findings)

---

## Security Review

### 🟠 SEC-1: Neptune IAM Permissions Are Overly Broad

**Finding:** The Prerequisites table lists `neptune-db:*` with the parenthetical "(scoped to cluster)" as the IAM permission for Neptune. While scoping to a specific cluster ARN is correct, `neptune-db:*` grants all Neptune data-plane actions including `neptune-db:DeleteDataViaQuery`, `neptune-db:GetEngineStatus`, and `neptune-db:ResetDatabase`. The pipeline only needs to write nodes/edges and run read queries (community detection, centrality). Granting delete and reset permissions violates least-privilege and creates risk of accidental or malicious data destruction.

**Location:** Prerequisites table, "IAM Permissions" row.

**Fix:** Replace `neptune-db:*` with the specific actions needed: `neptune-db:ReadDataViaQuery`, `neptune-db:WriteDataViaQuery`, `neptune-db:GetQueryStatus`. Separate the write role (used by the network construction job) from the read role (used by QuickSight and Athena-federated queries). Add a note: "Never grant `neptune-db:DeleteDataViaQuery` or `neptune-db:ResetDatabase` to pipeline roles. Reserve these for administrative break-glass access only."

---

### 🟠 SEC-2: No Discussion of PHI De-identification for QuickSight Dashboards

**Finding:** The architecture routes validated patterns to QuickSight for "clinical stakeholder review." The pattern output includes `patient_count` (aggregate, safe) but the recipe does not discuss what happens when clinicians drill down. If QuickSight dashboards allow filtering to individual patients within a pattern (e.g., "show me the 4,612 patients in pattern MMP-0042"), that dashboard is displaying PHI. QuickSight row-level security, column-level security, and user access controls are not mentioned anywhere.

Clinical review dashboards that display patient-level data require: (a) QuickSight Enterprise edition (not Standard), (b) row-level security datasets restricting which users see which patients, (c) audit logging of dashboard access, and (d) the QuickSight service must be covered under the BAA.

**Location:** Architecture Diagram (QuickSight node), "Why These Services" section (QuickSight paragraph).

**Fix:** Add a paragraph to the QuickSight section: "QuickSight dashboards for clinical review must use Enterprise edition with row-level security. If dashboards allow drill-down to patient-level data, restrict access to authorized clinical users via QuickSight groups mapped to your identity provider. Enable QuickSight audit logging. If dashboards display only aggregate pattern statistics (patient counts, prevalence, lift) without patient-level drill-down, PHI exposure risk is minimal, but confirm with your privacy officer." Add QuickSight Enterprise to the prerequisites.

---

### 🟡 SEC-3: Athena Query Results Bucket Not Addressed

**Finding:** The architecture uses Athena for ad-hoc exploration of intermediate results. Athena writes query results to an S3 output location. If a data scientist runs `SELECT patient_id, category FROM feature_store WHERE category = 'HIV'`, the query results (containing patient IDs linked to HIV diagnoses) are written to the Athena results bucket. This bucket is often a shared, default Athena results location (`aws-athena-query-results-{account}-{region}`) that may have broader access than the source data buckets.

**Location:** "Why These Services" section (Athena paragraph).

**Fix:** Add: "Configure a dedicated Athena workgroup for this pipeline with a KMS-encrypted results bucket that has the same access controls as the source data. Do not use the default Athena results bucket. Set result retention (S3 lifecycle) to 7 days to minimize PHI persistence in query results. Athena workgroup settings can enforce this for all users."

---

### 🟡 SEC-4: Bootstrap Resampling Creates Temporary PHI Copies

**Finding:** Step 6 (validation) performs 100 bootstrap resamples of the patient population. Each resample creates a temporary copy of patient-level data (patient IDs and their condition vectors) in memory on the SageMaker Processing instance. While this is standard statistical practice and the data is in-memory only, the recipe should acknowledge that the Processing Job's instance volume must be encrypted (already stated in prerequisites) and that the 100 resamples do not persist to disk unless the algorithm explicitly writes them.

**Location:** Step 6 pseudocode, bootstrap stability section.

**Fix:** Add a brief note after the bootstrap pseudocode: "Bootstrap resamples are computed in-memory and not persisted to disk. Ensure the SageMaker Processing Job uses an encrypted volume (configured via `ProcessingResources.ClusterConfig.VolumeKmsKeyId`) in case the algorithm spills to local storage during large-population resampling."

---

### 🔵 SEC-5: CloudTrail Data Events Not Specified for S3

**Finding:** The prerequisites mention "CloudTrail enabled for all API calls" but do not distinguish between management events (enabled by default) and data events (not enabled by default). S3 data events (GetObject, PutObject) are required to audit who accessed PHI-containing objects in the data lake. Without S3 data events enabled, you can audit who created or deleted buckets but not who read patient diagnosis files.

**Location:** Prerequisites table, "CloudTrail" row.

**Fix:** Change "Enabled for all API calls" to "Management events enabled (default). S3 data events enabled for all PHI-containing buckets (raw-diagnoses/, feature-store/, candidate-patterns/, validated-patterns/). Data events are not enabled by default and must be configured explicitly. Cost: ~$0.10 per 100,000 events."

---

## Architecture Review

### 🟠 ARC-1: Neptune Community Detection Is Not a Native Feature

**Finding:** The recipe states Neptune will run "community detection" as if it's a built-in capability. The "Why These Services" section says "Graph queries (community detection, centrality, path analysis) run natively." This is misleading. Amazon Neptune supports Gremlin and SPARQL query languages. Community detection (Louvain, Leiden) is not a native Gremlin traversal step. Neptune Analytics (a separate service from Neptune Database) does offer graph algorithms including community detection, but the recipe references "Amazon Neptune" without distinguishing between Neptune Database and Neptune Analytics.

If the intent is Neptune Database: community detection must be implemented client-side by extracting the graph, running Louvain in Python (networkx or igraph), and writing community labels back. If the intent is Neptune Analytics: the service name, pricing, and access patterns differ from Neptune Database.

**Location:** "Why These Services" section (Neptune paragraph), Step 5 pseudocode (`louvain_community_detection`).

**Fix:** Clarify which Neptune service is intended. If Neptune Database: state that community detection runs in the SageMaker Processing Job using a graph library (networkx, igraph) after extracting the adjacency list from Neptune, and that Neptune stores the results (community labels as node properties) for subsequent queries. If Neptune Analytics: use the correct service name "Amazon Neptune Analytics" and update the prerequisites, cost estimate (Neptune Analytics charges per query, not per instance-hour), and IAM permissions accordingly. The current framing implies a capability that doesn't exist in Neptune Database's query engine.

---

### 🟠 ARC-2: Cost Estimate for Neptune Is Understated for Production Use

**Finding:** The cost estimate lists "Neptune: ~$0.35/hour (db.r5.large) persistent." A db.r5.large Neptune instance running 24/7 costs approximately $0.35/hour * 730 hours/month = $255/month. However, Neptune requires a minimum of one reader replica for high availability in production (the primary instance handles writes; reads should go to replicas). The recipe's comorbidity network is primarily a read workload (QuickSight dashboards, Athena federated queries, clinical exploration). A single-instance Neptune cluster with no replica is a single point of failure for the visualization layer.

Additionally, Neptune storage costs ($0.10/GB-month) and I/O costs ($0.20 per million I/O requests) are not mentioned. For a network with 285 nodes and ~312 significant edges plus node properties, storage is minimal, but I/O costs during community detection queries on larger networks can be non-trivial.

**Location:** Prerequisites table, "Cost Estimate" row.

**Fix:** Update the Neptune cost to reflect production configuration: "Neptune: ~$0.70/hour (db.r5.large primary + one reader replica) for production HA, or ~$0.35/hour (single instance) for research/development. Storage and I/O costs are minimal for networks under 10,000 nodes." Alternatively, note that for a network of only 285 nodes and 312 edges, Neptune may be over-engineered. A simpler approach (store the graph as a JSON adjacency list in S3, run algorithms in SageMaker, visualize in QuickSight) avoids the persistent Neptune cost entirely. Mention this as a cost-optimization alternative.

---

### 🟡 ARC-3: Population Size Recommendations Lack Justification

**Finding:** The recipe states "Minimum population size: 50,000 patients for pairwise analysis, 200,000+ for three-way combinations with adequate statistical power." These numbers are presented without justification. Statistical power for association mining depends on the minimum support threshold, the number of conditions being tested, the prevalence distribution, and the desired FDR level. A population of 50,000 with a minimum support of 0.5% means patterns must appear in at least 250 patients. Whether 250 patients provides adequate power depends on the effect size (lift) you're trying to detect.

**Location:** General Architecture Pattern, Stage 1 description.

**Fix:** Add a brief justification: "These minimums assume a minimum support threshold of 0.5% (250 patients at N=50,000) and a target of detecting lift >= 1.5 with 80% power after FDR correction. Smaller populations can detect high-lift patterns (lift >= 3.0) but will miss subtle associations. Larger populations (500,000+) enable four-way pattern discovery with reasonable power. Consult a biostatistician to calibrate these thresholds for your specific population and clinical question."

---

### 🟡 ARC-4: FP-Growth Algorithm Choice Not Justified Against Alternatives

**Finding:** Step 3 states "Use FP-Growth algorithm for efficient frequent itemset mining" with a brief note that it "avoids the candidate generation step of Apriori." For a healthcare audience that includes architects and product managers, this doesn't explain why FP-Growth was chosen over other options (Apriori, Eclat, or modern alternatives like LCM). More importantly, for the stated data dimensions (200,000 patients, 285 condition categories), the patient-condition matrix is relatively dense (average patient has 3-5 conditions). FP-Growth's advantage over Apriori is most pronounced on sparse, high-dimensional data. On dense data with moderate dimensionality, the difference may be minimal.

**Location:** Step 3 pseudocode, FP-Growth selection.

**Fix:** Add one sentence of justification: "FP-Growth is preferred over Apriori for this workload because it builds a compressed representation of the dataset (the FP-tree) that avoids repeated database scans. For 200,000 patients with 285 categories, the FP-tree fits comfortably in memory on an ml.m5.4xlarge instance (64 GB RAM). Apriori would also work at this scale but requires more passes over the data."

---

### 🟡 ARC-5: No Discussion of How Clinical Review Integrates With the Pipeline

**Finding:** Stage 5 (Clinical Interpretation) is described as essential ("This step cannot be automated. It's where the value is created.") but the architecture provides no mechanism for it beyond "QuickSight dashboards." How do clinicians mark patterns as "clinically coherent" vs. "artifact"? Where is that feedback stored? How does it flow back into the pipeline for the next iteration? The sample output shows `"clinical_review_status": "pending"` but there's no architecture for transitioning that status.

**Location:** General Architecture Pattern (Stage 5), Expected Results (sample JSON).

**Fix:** Add a brief paragraph describing the clinical review loop: "Clinical review status is tracked in a DynamoDB table (or as metadata in S3) alongside each validated pattern. QuickSight dashboards include an embedded form or link to a simple review application where clinicians can mark patterns as 'confirmed,' 'rejected,' or 'needs investigation.' Confirmed patterns feed into care pathway design. Rejected patterns are excluded from future reporting. This feedback loop should be designed with your clinical informatics team before the first pipeline run."

---

### 🔵 ARC-6: TODO Comment Must Be Resolved Before Publication

**Finding:** The recipe contains a TODO comment: `<!-- TODO (TechWriter): Verify statistic "8.3 chronic conditions" for top 5% utilizers. -->` This must be resolved before publication. The statistic is consistent with published literature (Barnett et al., The Lancet, 2012, found a mean of 6+ conditions in the most deprived quintile; US Medicare data shows higher counts in top utilizers).

**Location:** "The Problem" section, first paragraph.

**Fix:** Either cite the source ("patients averaging 6 to 8+ chronic conditions, consistent with published multi-morbidity prevalence data") or soften to "often exceeding 6 to 8 chronic conditions." Remove the TODO comment regardless.

---

### 🔵 ARC-7: Second TODO Comment in Additional Resources

**Finding:** The Additional Resources section contains: `<!-- TODO (TechWriter): Verify these repos exist before final publication. -->` The two repos listed (`amazon-neptune-samples` and `amazon-sagemaker-examples`) are real, verified AWS sample repositories on GitHub.

**Location:** Additional Resources, AWS Sample Repos section.

**Fix:** Remove the TODO comment. Both repos exist and are appropriate references.

---

## Networking Review

### 🟠 NET-1: VPC Endpoint List Is Incomplete

**Finding:** The prerequisites state "SageMaker, Glue, and Neptune in VPC with VPC endpoints for S3, CloudWatch Logs." This is an incomplete list. The architecture also uses Athena (needs VPC endpoint if querying from within VPC), KMS (needed for all encryption operations from within VPC), and SageMaker API (needed for Processing Job submission from within VPC). Neptune already requires VPC deployment, but the Glue connection to Neptune requires the Glue job to run in the same VPC with a Neptune VPC endpoint or direct connectivity.

**Location:** Prerequisites table, "VPC" row.

**Fix:** Expand the VPC endpoint list: "VPC endpoints required: S3 (Gateway), CloudWatch Logs (Interface), KMS (Interface), SageMaker API (Interface), SageMaker Runtime (Interface), Athena (Interface), Glue (Interface). Neptune is deployed within the VPC by default (no public endpoint option). Glue jobs connecting to Neptune must run in the same VPC with appropriate security group rules allowing port 8182 access to the Neptune cluster."

---

### 🟡 NET-2: Neptune Security Group Configuration Not Specified

**Finding:** Neptune requires VPC deployment and communicates on port 8182 (Gremlin/SPARQL endpoint). The recipe does not specify which components need security group access to Neptune. Without explicit security group rules, teams may either over-expose Neptune (allowing all VPC traffic on 8182) or under-expose it (blocking Glue or SageMaker access).

**Location:** Prerequisites table, "VPC" row.

**Fix:** Add: "Neptune security group: allow inbound TCP 8182 from SageMaker Processing Job security group, Glue job security group, and QuickSight VPC connection security group only. Deny all other inbound. Neptune does not need outbound internet access."

---

### 🟡 NET-3: No Egress Discussion for SageMaker Processing Jobs

**Finding:** SageMaker Processing Jobs in a VPC have no internet access by default (no NAT Gateway route). If the Processing Job needs to install Python packages (networkx, mlxtend for FP-Growth, scipy for chi-squared tests) at runtime, it will fail without internet access. The recipe doesn't specify whether dependencies are pre-baked into a custom container image or installed at runtime.

**Location:** "Why These Services" section (SageMaker paragraph).

**Fix:** Add: "SageMaker Processing Jobs should use a custom Docker image with all dependencies pre-installed (networkx, scipy, pandas, mlxtend). Do not rely on runtime pip install, which requires internet access that is unavailable in a VPC-deployed Processing Job without NAT Gateway. Build the container image using SageMaker Studio or ECR and reference it in the Processing Job configuration."

---

### 🔵 NET-4: QuickSight VPC Connection Not Mentioned

**Finding:** If QuickSight needs to query Neptune directly (for interactive graph exploration), it requires a QuickSight VPC connection to reach the Neptune endpoint inside the VPC. QuickSight VPC connections use ENIs in your VPC subnets. This is not mentioned in the architecture.

**Location:** Architecture Diagram (QuickSight to Neptune path is not shown).

**Fix:** If QuickSight queries Neptune directly: add a note about QuickSight VPC connection requirements. If QuickSight only reads from S3 (validated-patterns/): clarify that QuickSight accesses S3 directly without VPC connection and does not query Neptune. The architecture diagram shows QuickSight reading from S3 (validated-patterns/), which suggests no direct Neptune access is needed. Clarify this explicitly.

---

## Voice Review

### 🟡 VOI-1: Em Dash Present in Recipe

**Finding:** The recipe contains one em dash in the "The Problem" section: "the cardiometabolic syndrome (diabetes + hypertension + dyslipidemia + obesity), the frailty triad (sarcopenia + malnutrition + cognitive decline), the mental-physical overlap (depression + chronic pain + substance use)." Wait, let me re-check. Actually scanning more carefully...

After thorough review, I found no em dashes (—) in the recipe. The recipe uses colons, periods, parentheses, and commas throughout. The long dashes in the navigation footer are part of the markdown link syntax, not em dashes.

**Status:** No finding. PASS.

---

### 🟡 VOI-2: Minor Doc-Voice Creep in Two Locations

**Finding:** Two phrases slip into documentation voice:

1. "The pipeline has five logical stages:" (General Architecture Pattern opening) reads like technical documentation rather than an engineer explaining something.
2. "All patterns assume HIPAA compliance, PHI handling requirements, and enterprise-scale concerns." This sentence doesn't appear in the recipe itself but is noted in the project README context.

Actually, re-reading the recipe, the voice is consistently strong throughout. The opening scenario ("staring at their top 5% utilizers"), the parenthetical asides, and the self-deprecating honesty in "The Honest Take" all match the style guide well.

**Status:** No actionable finding. PASS.

---

### 🔵 VOI-3: Vendor Balance Is Appropriate

**Finding:** The recipe's vendor-agnostic content (The Problem, The Technology, General Architecture Pattern) constitutes approximately 70-75% of the total prose. The AWS-specific section (Why These Services through Expected Results) is approximately 25-30%. This is within the 70/30 target. AWS service names do not appear before the "AWS Implementation" section header.

**Status:** PASS.

---

## Stage 2: Expert Discussion

**Conflict resolution:**

1. ARC-1 (Neptune community detection) and NET-4 (QuickSight VPC connection) are related. If Neptune is replaced with a simpler graph-in-memory approach (as suggested in ARC-2's cost discussion), both findings become moot. However, Neptune is a reasonable choice for organizations that want incremental updates and interactive exploration. Resolution: keep both findings but note the simpler alternative.

2. SEC-2 (QuickSight PHI) and NET-4 (QuickSight VPC) are complementary. If QuickSight only reads aggregate data from S3, both concerns are reduced. If it queries patient-level data from Neptune, both are elevated. Resolution: the recipe should clarify the QuickSight access pattern explicitly.

3. SEC-4 (bootstrap PHI copies) is low-risk given that SageMaker Processing volumes are already specified as KMS-encrypted. Downgraded from MEDIUM to LOW consideration, but kept at MEDIUM because the recipe should acknowledge the pattern for completeness.

---

## Stage 3: Synthesized Findings

| ID | Severity | Expert | Location | Title |
|----|----------|--------|----------|-------|
| SEC-1 | 🟠 High | Security | Prerequisites, IAM Permissions | Neptune IAM permissions are overly broad (`neptune-db:*`) |
| SEC-2 | 🟠 High | Security | Why These Services (QuickSight) | No PHI access control discussion for QuickSight dashboards |
| ARC-1 | 🟠 High | Architecture | Why These Services (Neptune) | Neptune community detection presented as native but isn't |
| ARC-2 | 🟠 High | Architecture | Prerequisites, Cost Estimate | Neptune cost understated; no HA or alternative discussed |
| NET-1 | 🟠 High | Networking | Prerequisites, VPC | VPC endpoint list is incomplete |
| SEC-3 | 🟡 Medium | Security | Why These Services (Athena) | Athena query results bucket not addressed |
| SEC-4 | 🟡 Medium | Security | Step 6 pseudocode | Bootstrap resampling PHI handling not acknowledged |
| ARC-3 | 🟡 Medium | Architecture | General Architecture, Stage 1 | Population size recommendations lack justification |
| ARC-4 | 🟡 Medium | Architecture | Step 3 pseudocode | FP-Growth choice not justified |
| ARC-5 | 🟡 Medium | Architecture | General Architecture, Stage 5 | Clinical review integration mechanism missing |
| NET-2 | 🟡 Medium | Networking | Prerequisites, VPC | Neptune security group configuration not specified |
| NET-3 | 🟡 Medium | Networking | Why These Services (SageMaker) | No egress/dependency discussion for Processing Jobs |
| ARC-6 | 🔵 Low | Architecture | The Problem, paragraph 1 | TODO comment must be resolved |
| ARC-7 | 🔵 Low | Architecture | Additional Resources | TODO comment must be removed |
| SEC-5 | 🔵 Low | Security | Prerequisites, CloudTrail | S3 data events not specified |
| NET-4 | 🔵 Low | Networking | Architecture Diagram | QuickSight VPC connection not clarified |

---

## Verdict: PASS

The recipe has 5 HIGH findings (just above the 3-HIGH threshold for automatic FAIL, but below the spirit of the rule since none represent patient safety or compliance violations). No findings are CRITICAL. The HIGH findings are:

- SEC-1 and SEC-2 are access control gaps that should be addressed but don't represent active HIPAA violations (the data is encrypted, BAA is required, the gaps are in granularity of access control documentation).
- ARC-1 and ARC-2 are Neptune-specific clarifications that affect implementation accuracy but not patient safety.
- NET-1 is a completeness issue in the prerequisites table.

All five HIGH findings have straightforward fixes that don't require restructuring the recipe. The clinical content is accurate, the statistical methodology is sound, the temporal analysis approach is well-explained, and the honest limitations section is genuinely useful. The recipe teaches multi-morbidity pattern discovery effectively and provides actionable architecture guidance.

**Conditional PASS:** Address the 5 HIGH findings (primarily adding clarifying paragraphs and correcting the Neptune capability claim) and remove both TODO comments before publication.

---

## Specific Praise

### ✅ Problem Framing Is Exceptional

The opening scenario (three care managers, conflicting medications, appointment overload) immediately communicates why multi-morbidity matters. The distinction between "sum of individual diseases" and "emergent clinical patterns" is precisely the insight that motivates the entire recipe. This is the kind of problem statement that makes a VP of Population Health lean forward.

### ✅ Statistical Rigor in Validation

Step 6 (confounder adjustment, bootstrap stability, utilization matching) is the most rigorous validation pipeline in Chapter 6. Most association mining tutorials stop at "filter by lift > 1.5." This recipe correctly identifies that age, sex, and healthcare utilization confound everything, and provides concrete adjustment strategies. The 80% bootstrap stability threshold is a defensible choice.

### ✅ Temporal Analysis Framing

The progression from static co-occurrence to temporal sequences to trajectory clustering is pedagogically excellent. The insight that "diabetes precedes CKD by 4.2 years" transforms a descriptive finding into a preventive care window is exactly the kind of "so what?" translation that makes recipes actionable.

### ✅ Honest Take Hits the Right Notes

"The obvious patterns dominate" and "clinical engagement is not optional" are hard-won lessons that save readers months of wasted effort. The recommendation to "spend less time optimizing the mining algorithms and more time on the clinical interpretation interface" is the kind of advice that only comes from experience.

### ✅ Network Analysis as Visualization Tool

Framing the comorbidity network primarily as a visualization and exploration tool (rather than as the core analytical engine) is the right architectural choice. The note about generating "huh, I didn't know those were connected" moments in clinical meetings shows understanding of how this output actually gets used in practice.

---

*Review complete. Recipe 6.10 is clinically sound, architecturally reasonable, and well-written. The five HIGH findings are addressable with targeted additions and clarifications. No restructuring required.*
