# Expert Review: Recipe 6.8 - Disease Subtype Discovery

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter06.08-disease-subtype-discovery.md`

---

## Overall Assessment

This is an excellent recipe. The problem framing is compelling and clinically grounded (the heart failure heterogeneity example is well-chosen and immediately resonant). The technology section is one of the strongest in the cookbook: it teaches unsupervised clustering from first principles, covers algorithm selection with genuine nuance, and the validation discussion is intellectually honest about the fundamental challenge of unsupervised discovery (no ground truth). The pseudocode is thorough, well-commented, and accessible. The "Honest Take" section is genuinely self-deprecating and contains hard-won wisdom about publication bias and feature selection pitfalls.

The recipe correctly frames this as research-grade work requiring clinical collaboration, which is the right positioning. The AWS implementation is well-motivated and the service choices are appropriate. The consensus clustering approach is the gold standard for this problem and it's good to see it featured prominently.

However: there are gaps in the security posture around research data governance, a missing discussion of IRB/ethics requirements that is critical for this use case, and some architectural concerns around the transition from research discovery to production classifier deployment. The voice is strong and consistent throughout.

**Verdict: PASS**

Priority breakdown: 0 critical, 2 high, 5 medium, 4 low.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review

#### What's Done Well

BAA requirement is explicit in the prerequisites. Encryption at rest (SSE-KMS for S3, DynamoDB encryption, KMS-encrypted SageMaker volumes and endpoints) and in transit (TLS) are specified. CloudTrail for audit logging is included. The "never use real PHI in dev/research without IRB approval" warning is present. VPC placement for SageMaker notebooks and training jobs is recommended with VPC endpoints for S3, DynamoDB, and SageMaker API. The "no internet egress for PHI workloads" statement is explicit and correct. The MIMIC-IV reference for development data is appropriate.

#### Issue S1: IAM Permissions Are Not Resource-Scoped (MEDIUM)

**Location:** Prerequisites table, IAM Permissions row

**The problem:** The permissions listed (`sagemaker:CreateTrainingJob`, `s3:GetObject`, `s3:PutObject`, `glue:StartJobRun`, `dynamodb:PutItem`, etc.) are action-level without resource constraints. A builder following this literally might grant `s3:PutObject` on `*` rather than scoping to the specific data lake bucket and prefix. For a research workload handling PHI, overly broad permissions increase the blast radius of a compromised notebook or training job.

**Suggested fix:** Add a note: "Scope all permissions to specific resource ARNs. Example: `s3:GetObject` on `arn:aws:s3:::patient-features-bucket/cohort-*`, `sagemaker:CreateTrainingJob` scoped to specific training job name prefixes, `dynamodb:PutItem` on the specific subtype assignment table ARN." One sentence of guidance is sufficient.

#### Issue S2: SageMaker Notebook Security Posture Underspecified (MEDIUM)

**Location:** Prerequisites table and "Why These Services" (SageMaker section)

**The problem:** SageMaker notebooks are the primary interface for this research workflow. The recipe mentions VPC placement but doesn't address: (1) notebook lifecycle configuration to enforce security controls, (2) root access disabling on notebook instances, (3) whether SageMaker Studio or classic notebook instances are recommended (Studio has better IAM session isolation), (4) the risk of researchers installing arbitrary packages that could exfiltrate data. For a research workload where data scientists have interactive access to PHI-derived feature matrices, the notebook is the highest-risk attack surface.

**Suggested fix:** Add one paragraph in prerequisites or a note in "Why These Services": recommend SageMaker Studio with domain-level VPC configuration, disable root access on notebook instances, use lifecycle configurations to restrict pip/conda to approved package mirrors, and enable SageMaker audit logging for notebook activity. This is particularly important because research workflows involve more interactive exploration than production pipelines.

#### Issue S3: No Data Retention or Deletion Policy for Intermediate Results (MEDIUM)

**Location:** General architecture, S3 data lake storage

**The problem:** The recipe stores patient feature matrices, intermediate clustering results, consensus matrices, and model artifacts in S3. For a research workflow, these artifacts accumulate over weeks or months of experimentation. The recipe mentions S3 versioning for reproducibility but provides no guidance on: (1) when intermediate results should be deleted, (2) how to handle the case where a patient exercises their HIPAA right to amendment or deletion, (3) lifecycle policies for moving old experiment artifacts to Glacier or deleting them. A research team running 50+ experiments will accumulate significant PHI-derived data without a retention policy.

**Suggested fix:** Add a note in the S3 section: "Implement S3 lifecycle policies to transition experiment artifacts older than [retention period] to Glacier and delete after [maximum retention]. Maintain a manifest of which patient IDs are included in each experiment's feature matrix to support HIPAA amendment and accounting-of-disclosures requests. Consider S3 Object Lock for audit-critical artifacts (final validated results) and aggressive lifecycle policies for exploratory intermediate results."

#### Issue S4: Subtype Classifier Endpoint Serves PHI-Derived Predictions Without Access Logging (LOW)

**Location:** Step 7 (classifier deployment), DynamoDB subtype store

**The problem:** The deployed classifier assigns patients to subtypes in real time, and results are stored in DynamoDB for downstream consumption. The recipe mentions CloudTrail for API calls but doesn't address application-level access logging: which downstream system queried which patient's subtype, when, and for what purpose. If subtypes carry clinical implications (e.g., "this subtype has 60% readmission rate"), the subtype assignment itself is clinically meaningful derived PHI that should be subject to access controls and audit logging.

**Suggested fix:** Add a note that the DynamoDB subtype store should have application-level access logging (not just CloudTrail API logging) and that downstream consumers should authenticate and be logged. This is especially important if subtype assignments are surfaced in clinical decision support tools.

---

### Architecture Expert Review

#### What's Done Well

The architecture is sound and well-motivated. The multi-algorithm approach with consensus clustering is the correct methodology for disease subtype discovery. The separation of concerns (Glue for ETL, SageMaker for ML, Step Functions for orchestration) is clean. The progression from exploration to production classifier is well-paced. The cost estimates are reasonable. The "Where it struggles" section is honest and specific about real failure modes (continuous spectrums, high missingness, small cohorts, treatment confounding). The performance benchmarks are realistic (silhouette scores of 0.25-0.45 for clinical data is exactly right).

#### Issue A1: Research-to-Production Transition Is Architecturally Underspecified (HIGH)

**Location:** Step 7 (classifier training and deployment), general architecture

**The problem:** The recipe jumps from "validated subtypes" (a research output) to "deployed SageMaker endpoint serving real-time predictions" (a production system) without addressing the significant architectural and governance gap between these two states. In healthcare, deploying a research finding as a clinical tool requires:

1. **Clinical validation beyond the discovery cohort:** The recipe validates within the discovery cohort but doesn't discuss prospective validation on a held-out temporal cohort (patients diagnosed after the discovery period).
2. **Regulatory considerations:** If the subtype classifier influences treatment decisions, it may be subject to FDA oversight as a Clinical Decision Support (CDS) tool. The recipe doesn't mention this.
3. **Model governance:** Who approves the transition from "interesting research finding" to "production classifier that labels patients"? What's the approval workflow?
4. **Monitoring for concept drift:** The recipe mentions "monitor for drift" in passing but doesn't specify what drift looks like for a subtype classifier (new patient populations that don't fit existing subtypes, changing treatment patterns that alter the feature distributions).

**Suggested fix:** Add a subsection between Step 6 and Step 7 (or expand Step 7's introduction) addressing the research-to-production transition: (1) prospective validation requirement (test on patients not in the discovery cohort), (2) FDA CDS considerations (reference 21st Century Cures Act criteria for non-regulated CDS), (3) clinical governance approval workflow, (4) drift monitoring strategy (feature distribution monitoring, periodic re-clustering to check stability, outcome monitoring for deployed subtypes). This doesn't need to be exhaustive but the gap between "we found clusters" and "we're labeling patients in production" needs explicit acknowledgment.

#### Issue A2: No Discussion of IRB/Ethics Review Requirements (HIGH)

**Location:** The Problem section, general architecture, Prerequisites

**The problem:** Disease subtype discovery using patient clinical data is research. The recipe mentions "IRB approval" once in the sample data prerequisite ("Never use real PHI in dev/research without IRB approval") but doesn't address the broader question: does the subtype discovery project itself require IRB review?

The answer depends on how the work is framed:
- If it's a quality improvement (QI) project, IRB review may not be required but institutional QI committee approval typically is.
- If it's research (generating generalizable knowledge, potential publication), full IRB review is required.
- If it's clinical operations (building a tool for care management), it may fall under a different governance framework.

The recipe frames this as "research-grade work" in the Problem section, which implies IRB review is required. But the architecture proceeds directly to production deployment without addressing this governance step. A builder following this recipe might skip IRB review entirely because it's only mentioned in the context of sample data, not the project itself.

**Suggested fix:** Add a paragraph in the Problem section or as a prerequisite: "Disease subtype discovery using patient data typically requires IRB review (or a determination of exemption) before accessing real patient data. Even if the initial analysis is framed as quality improvement, publishing results or deploying a classifier that influences care decisions may trigger research classification. Engage your institution's IRB or research governance office early. The timeline for IRB approval (4-12 weeks) should be factored into the 'Basic' implementation estimate."

#### Issue A3: Consensus Clustering Compute Cost May Be Underestimated (MEDIUM)

**Location:** Step 5 pseudocode, Performance benchmarks table

**The problem:** The recipe estimates "1-3 hours depending on cohort size" for consensus clustering with 100 iterations. For a cohort of 14,000 patients (the example in the Problem section) with 42 features, each iteration involves: subsample 80% (11,200 patients), run K-means, update the co-clustering matrix (which is 14,000 x 14,000 = 196 million entries). The consensus matrix alone requires ~1.5 GB of memory (196M entries x 8 bytes). With 100 iterations, this is computationally feasible but the memory requirement for the consensus matrix may exceed the ml.m5.4xlarge's 64 GB RAM if the cohort is larger (50,000 patients = 2,500M entries = 20 GB just for the matrix, plus working memory).

**Suggested fix:** Add a note in Step 5 or the performance benchmarks: "Consensus clustering memory scales quadratically with cohort size (N x N consensus matrix). For cohorts > 20,000 patients, consider: (1) block-diagonal approximation (cluster subsets independently), (2) sparse consensus matrix (only store entries above a threshold), or (3) mini-batch consensus (subsample both patients and iterations). For the 14,000-patient example, an ml.m5.4xlarge (64 GB RAM) is sufficient."

#### Issue A4: Step Functions Orchestration Doesn't Account for Human-in-the-Loop Step (MEDIUM)

**Location:** Architecture diagram, Step Functions description

**The problem:** The architecture diagram shows Step Functions orchestrating the pipeline including "Clinical Validation (Human-in-the-Loop)." But Step Functions is designed for automated workflows. The human-in-the-loop step (clinicians reviewing cluster profiles and providing feedback) doesn't fit naturally into a state machine. The recipe doesn't explain how this step is implemented: Is it a manual approval gate? A callback pattern with a task token? An external notification that pauses the state machine?

**Suggested fix:** Add a note that the clinical validation step uses Step Functions' callback pattern (`.waitForTaskToken`) or a manual approval gate. The state machine pauses, sends a notification (SNS/email) to the clinical review team with the cluster characterization report, and resumes when the clinician approves or requests re-analysis with different parameters. This is a common pattern but non-obvious for readers unfamiliar with Step Functions' async capabilities.

#### Issue A5: No Guidance on Handling Patients Who Don't Fit Any Subtype (LOW)

**Location:** Step 7 (classifier deployment), Expected Results

**The problem:** The classifier assigns every new patient to one of the discovered subtypes. But some patients may genuinely not fit any subtype well (boundary patients, patients with novel presentations). The recipe discusses soft assignments from GMM (probability distributions across subtypes) in the Technology section but the deployed classifier in Step 7 uses gradient boosting, which produces hard assignments. There's no discussion of confidence thresholds or "unclassifiable" handling.

**Suggested fix:** Add a note in Step 7: "Consider adding a confidence threshold to the classifier output. If the maximum predicted probability is below a threshold (e.g., 0.6), flag the patient as 'unclassifiable' or 'boundary' rather than forcing assignment to a subtype. These patients may represent emerging subtypes not captured in the original discovery cohort."

---

### Networking Expert Review

#### What's Done Well

VPC placement for SageMaker notebooks and training jobs is explicit. VPC endpoints for S3, DynamoDB, and SageMaker API are specified. "No internet egress for PHI workloads" is stated clearly. The architecture keeps all PHI processing within the VPC boundary. The Glue ETL jobs connect to source systems (EHR) which implies VPC connectivity to on-premises or VPC-peered data sources, which is architecturally correct.

#### Issue N1: Glue ETL VPC Configuration Not Specified (MEDIUM)

**Location:** Prerequisites table, "Why These Services" (Glue section)

**The problem:** AWS Glue ETL jobs that access data within a VPC (e.g., connecting to an RDS-based EHR data warehouse or an on-premises data source via Direct Connect) require explicit VPC configuration: Glue connections with subnet and security group specifications. The recipe mentions Glue for ETL but doesn't specify that Glue jobs need VPC connectivity to reach the EHR source systems. Without VPC configuration, Glue jobs run in AWS-managed networking and cannot reach VPC-resident data sources. Conversely, if the source data is already in S3, VPC configuration for Glue is less critical but the recipe implies EHR source systems as the origin.

**Suggested fix:** Add to the VPC prerequisite: "Configure Glue connections with VPC subnet and security group for jobs that access VPC-resident data sources (EHR databases, data warehouses). Glue jobs writing to S3 use the S3 VPC endpoint. If source data is already in S3, Glue VPC configuration is optional but recommended for consistency."

#### Issue N2: No Discussion of Cross-Account Data Access Patterns (LOW)

**Location:** General architecture

**The problem:** In many healthcare organizations, the EHR data lake and the ML research environment are in separate AWS accounts (data lake account vs. analytics/research account). The recipe assumes a single-account architecture. Cross-account access patterns (S3 bucket policies, cross-account IAM roles, VPC peering or PrivateLink between accounts) are not discussed. This is a common enterprise pattern that readers will encounter.

**Suggested fix:** Add one sentence in the prerequisites or architecture section: "In multi-account architectures (common in healthcare enterprises), use cross-account IAM roles for Glue and SageMaker to access the data lake account's S3 buckets. VPC peering or AWS PrivateLink enables network connectivity between accounts without internet transit."

---

### Voice Reviewer

#### What's Done Well

The voice is excellent throughout. The opening scenario (14,000 heart failure patients who all get the same treatment but respond differently) is immediately compelling. The progression from clinical intuition ("cardiologists know this") to the technical challenge ("there are no labels") is masterfully paced. The Technology section is one of the best in the cookbook: it teaches clustering from first principles without condescending, covers algorithm tradeoffs with genuine nuance, and the validation discussion is intellectually honest.

Specific highlights:
- "The 'might' is doing a lot of work in that sentence, and we'll come back to it." (Perfect parenthetical aside)
- "Feature selection is the entire ballgame." (Punchy, memorable)
- "The subtypes are not 'in the data' waiting to be discovered. They're a function of which data you choose to look at and how you represent it." (This is the key insight, delivered perfectly)
- The Honest Take section is genuinely self-deprecating: "I've seen teams spend months on sophisticated clustering algorithms only to realize their features were dominated by age and sex."

The 70/30 vendor balance is well-maintained. The entire Technology section (which is substantial) is vendor-agnostic. AWS appears only in the implementation half.

#### Issue V1: No Em Dashes Found (PASS)

After thorough scan: zero em dashes. The recipe uses colons, semicolons, periods, and parentheses consistently. Clean pass.

#### Issue V2: One Instance of Slightly Academic Register (LOW)

**Location:** Technology section, "Validation: The Hard Part" subsection

**The text:** "Internal validation metrics measure cluster quality without external labels"

**The problem:** This sentence reads slightly like a textbook definition rather than an engineer explaining something. The rest of the section immediately recovers with concrete examples and the conversational "These metrics tell you whether the clusters are well-separated in feature space. They do not tell you whether the clusters are clinically meaningful." But the opening sentence of that paragraph could be warmer.

**Suggested fix:** Minor. Consider: "Internal validation metrics tell you whether your clusters are well-formed, without needing external labels to compare against." This is a polish item.

#### Issue V3: "Non-Negotiable" Appears Once (LOW)

**Location:** Technology section, Feature Engineering Problem subsection

**The text:** "This is why clinical collaboration is non-negotiable."

**The problem:** Same note as Recipe 6.6 review: "non-negotiable" has a slightly corporate/LinkedIn tone. The rest of the recipe avoids this register.

**Suggested fix:** Consider "This is why you absolutely need clinical collaboration from day one" or "This is why clinical collaboration isn't optional." Minor tone adjustment.

#### Issue V4: The Lancet Reference Is Appropriate But Unverifiable (LOW)

**Location:** The Problem section, paragraph 3

**The text:** "The Lancet published a landmark study in 2018 identifying five distinct clusters within Type 2 diabetes..."

**The problem:** This appears to reference Ahlqvist et al. (2018), which is a real and landmark study. The description (five clusters, 8,980 patients, six clinical variables) matches the actual paper. However, the recipe doesn't provide a citation or link. For a cookbook that prohibits fake URLs, this is fine (no fake citation is better than a potentially broken DOI link). But the specificity of the claim (8,980 patients, six variables) without attribution could be seen as presenting someone else's research without credit.

**Suggested fix:** Consider adding "(Ahlqvist et al., The Lancet Diabetes & Endocrinology, 2018)" inline. This is a well-known paper and the citation adds credibility without requiring a URL. Alternatively, leave as-is since the cookbook format doesn't typically include academic citations.

---

## Stage 2: Expert Discussion

**Overlap between Architecture (A1) and Architecture (A2):** Both address the governance gap between research and production. A1 focuses on the technical/regulatory transition (FDA, prospective validation, drift monitoring). A2 focuses on the ethical/institutional governance (IRB review). These are complementary: IRB approval is typically required before the research begins, while FDA/clinical governance considerations arise when transitioning to production. Both should be addressed but at different points in the recipe.

**Priority resolution:** A2 (IRB/ethics) should be addressed earlier in the recipe (Problem section or Prerequisites) because it's a gate that must be cleared before any patient data is accessed. A1 (research-to-production transition) should be addressed between Steps 6 and 7 because it's the governance gate between discovery and deployment.

**Security (S2) and Architecture (A1) overlap:** The notebook security concerns (S2) are particularly relevant because this is a research workflow where data scientists have interactive access. The research-to-production transition (A1) should include a security posture change: research notebooks with broad exploratory access should not be the same environment that serves production predictions.

**No conflicts between experts.** All findings are additive and reinforce each other.

---

## Stage 3: Synthesized Findings

| ID | Severity | Expert | Location | Finding | Recommended Fix |
|----|----------|--------|----------|---------|-----------------|
| A1 | HIGH | Architecture | Step 7, general architecture | Research-to-production transition is architecturally underspecified: no prospective validation, FDA CDS considerations, governance approval, or drift monitoring strategy | Add subsection addressing prospective validation, FDA 21st Century Cures Act CDS criteria, clinical governance workflow, and drift monitoring |
| A2 | HIGH | Architecture | Problem section, Prerequisites | No discussion of IRB/ethics review requirements for disease subtype discovery using patient data | Add paragraph on IRB requirements, QI vs. research classification, and timeline implications |
| S1 | MEDIUM | Security | Prerequisites, IAM Permissions | IAM permissions listed at action level without resource scoping | Add resource-scoping guidance with example ARN patterns |
| S2 | MEDIUM | Security | Prerequisites, "Why These Services" | SageMaker notebook security posture underspecified for research workload with interactive PHI access | Add paragraph on Studio vs. classic instances, root access, package restrictions, notebook audit logging |
| S3 | MEDIUM | Security | S3 data lake storage | No data retention or deletion policy for intermediate research artifacts containing PHI-derived data | Add lifecycle policy guidance, patient amendment support, and retention period recommendations |
| A3 | MEDIUM | Architecture | Step 5, Performance benchmarks | Consensus clustering memory scales quadratically; may exceed instance memory for large cohorts | Add memory scaling note and mitigation strategies for cohorts > 20,000 patients |
| A4 | MEDIUM | Architecture | Architecture diagram, Step Functions | Human-in-the-loop clinical validation step doesn't fit automated state machine without callback pattern | Add note on Step Functions callback pattern or manual approval gate for clinical review |
| N1 | MEDIUM | Networking | Prerequisites, Glue section | Glue ETL VPC configuration not specified for accessing VPC-resident EHR data sources | Add Glue connection VPC configuration to prerequisites |
| S4 | LOW | Security | Step 7, DynamoDB subtype store | Deployed classifier serves PHI-derived predictions without application-level access logging | Add application-level audit logging for subtype assignment queries |
| N2 | LOW | Networking | General architecture | No cross-account data access pattern discussion for common enterprise multi-account setups | Add one sentence on cross-account IAM roles and VPC peering |
| V2 | LOW | Voice | Technology, "Validation: The Hard Part" | One sentence reads slightly academic rather than conversational | Rephrase opening of validation metrics paragraph |
| V3 | LOW | Voice | Technology, Feature Engineering | "Non-negotiable" has slightly corporate tone | Rephrase to match conversational register |

---

## Priority Actions Before Publication

1. **Address A2 (HIGH):** Add IRB/ethics discussion early in the recipe (Problem section or Prerequisites). This is a gate that must be cleared before any real patient data is accessed. One paragraph covering: research vs. QI classification, IRB timeline (4-12 weeks), and the implication that the "Basic" implementation estimate should account for this.

2. **Address A1 (HIGH):** Add a research-to-production transition discussion between Steps 6 and 7. Cover: prospective validation on a temporal holdout, FDA CDS considerations (most subtype classifiers will qualify as non-regulated CDS under 21st Century Cures Act criteria, but this should be explicitly stated), clinical governance approval, and drift monitoring strategy.

3. **Address S2 and S3 (MEDIUM):** Strengthen the security posture for the research environment. SageMaker notebook hardening and data retention policies are particularly important for research workflows where data scientists have broad exploratory access over extended periods.

4. **Address A3 and A4 (MEDIUM):** Add the memory scaling note for consensus clustering and the Step Functions callback pattern for human-in-the-loop. Both are implementation details that readers will hit in practice.

5. **Remaining MEDIUM and LOW items** are improvements that strengthen the recipe but don't represent gaps that would mislead a builder or create compliance risk.

---

*Review complete. Recipe 6.8 is exceptionally well-written, clinically grounded, and technically rigorous. The Technology section is among the best in the cookbook for teaching a complex topic from first principles. The HIGH findings are governance gaps (IRB and research-to-production transition) that are specific to the research nature of this use case, not fundamental architectural flaws. The recipe correctly identifies this as research-grade work but needs to make the governance implications of that framing more explicit. With the IRB and transition gaps addressed, this is ready for publication.*
