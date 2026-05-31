# Expert Review: Recipe 6.7 - Clinical Trial Patient Matching

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter06.07-clinical-trial-patient-matching.md`

---

## Overall Assessment

This is a strong recipe. The problem statement is compelling and grounded in real clinical trial recruitment pain. The technology section is genuinely educational, covering criteria decomposition, structured vs. unstructured data, NLP challenges (especially negation detection), temporal reasoning, and the staged filtering architecture. The 70/30 vendor balance is well maintained. The "Honest Take" section is one of the best in the book so far: the medication list reliability insight and the multi-trial ROI observation are the kind of hard-won production knowledge that makes this cookbook valuable.

The architecture is sound for the stated scale. The staged approach (structured pre-screen then NLP deep screen) is the correct pattern for cost and performance. The recipe correctly identifies the human-in-the-loop requirement and doesn't oversell automation.

However: there are gaps in consent/IRB governance that need stronger treatment given the regulatory sensitivity of research screening, a missing VPC endpoint for Comprehend Medical, and the IAM permissions list is too broad for a system touching PHI for research purposes. No critical findings, but several high-severity items that need attention.

Priority breakdown: 0 must-fix critical errors, 3 high-severity gaps, 5 medium improvements, 2 low suggestions.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

The recipe correctly requires BAA coverage, S3 SSE-KMS encryption at rest, DynamoDB encryption at rest, TLS 1.2+ in transit, SageMaker endpoint encryption, CloudTrail for all API calls, and VPC placement for SageMaker and Glue. The "never use real PHI in development" warning is present. The Synthea recommendation for test data is appropriate. The explicit mention of "Log who queried which patients and when" in CloudTrail requirements shows awareness of research audit needs.

#### Issue S1: IAM Permissions Are Not Least-Privilege for Research Use Case (HIGH)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The IAM permissions listed are: `sagemaker:InvokeEndpoint`, `comprehend:DetectEntities`, `glue:StartJobRun`, `athena:StartQueryExecution`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `states:StartExecution`. These are listed without resource constraints. In a research screening context, the principle of least privilege is especially important because:

1. The system accesses PHI for research purposes (not treatment), which has stricter regulatory scrutiny
2. `s3:GetObject` without resource scoping means the pipeline role can read any object in any bucket in the account
3. `athena:StartQueryExecution` without a workgroup constraint means the role can query any data source configured in Athena
4. `comprehend:DetectEntities` should be `comprehendmedical:DetectEntitiesV2` (the recipe uses Comprehend Medical, not standard Comprehend)

A builder following this recipe will create an overly permissive role that can access patient data beyond what's needed for trial matching.

**Suggested fix:** Add resource ARN constraints to each permission. Scope `s3:GetObject` and `s3:PutObject` to specific bucket/prefix patterns (e.g., `arn:aws:s3:::trial-matching-*`). Scope `sagemaker:InvokeEndpoint` to the specific endpoint ARN. Use `comprehendmedical:DetectEntitiesV2` (correct API action). Add a note: "In research contexts, IAM policies should be scoped to the minimum data access required for the specific trial matching function. Consider separate roles for the pre-screen stage (read structured data) and the NLP stage (read clinical notes) to enforce separation of access."

#### Issue S2: Research Consent and IRB Governance Needs Stronger Treatment (HIGH)

**Location:** "Why This Isn't Production-Ready" section, first paragraph

**The problem:** The recipe mentions consent and IRB in one paragraph: "Some institutions require explicit patient consent for research screening. Others operate under a waiver of consent for pre-screening activities. Your legal and IRB teams need to weigh in before you screen a single patient." This is accurate but insufficient for a recipe that will be used to build actual research screening systems.

The regulatory landscape for automated research screening is more nuanced:
- 45 CFR 46.116(f) allows waiver of informed consent for screening activities under specific conditions
- HIPAA's research provisions (45 CFR 164.512(i)) allow use of PHI for research with IRB/Privacy Board approval
- Many institutions distinguish between "pre-screening" (identifying potentially eligible patients from existing data) and "screening" (actively evaluating a specific patient for a specific trial), with different consent requirements for each
- The Common Rule revision (2018) introduced changes to broad consent that affect how patient data can be used for future research identification

The recipe's system performs pre-screening (automated identification from existing records), not screening (which involves patient contact). This distinction matters for regulatory compliance and should be explicit.

**Suggested fix:** Expand the consent/regulatory paragraph into a dedicated subsection or add a callout box. Specify: "This system performs automated pre-screening: identifying potentially eligible patients from existing EHR data. It does not constitute screening (which requires patient contact and informed consent). Most institutions can operate pre-screening under a waiver of consent per 45 CFR 46.116(f) or under HIPAA's preparatory-to-research provision (45 CFR 164.512(i)(1)(ii)), but this requires documented IRB or Privacy Board approval. Document your institution's determination before deploying. The system's audit trail (CloudTrail logs of which patients were evaluated) supports the accountability requirements of both provisions."

#### Issue S3: No Data Retention or Minimization Policy for Matching Results (MEDIUM)

**Location:** Step 4 pseudocode (DynamoDB writes) and Expected Results

**The problem:** The scoring step writes per-patient matching results to DynamoDB with criterion-level detail including evidence strings that contain clinical information ("DOB: 1972-03-15", "No mentions of pancreatitis found in 47 clinical notes"). These records persist indefinitely. For research pre-screening data:

1. There's no stated retention policy (how long do matching results persist after a trial closes enrollment?)
2. The evidence strings contain derived PHI that creates a secondary data store
3. If a patient is determined ineligible, their data should arguably be purged sooner than eligible candidates

**Suggested fix:** Add a note in the DynamoDB section or in "Why This Isn't Production-Ready": "Define a retention policy for matching results. When a trial closes enrollment, archive or delete candidate records. Consider DynamoDB TTL on the `trial-candidates` table keyed to the trial's expected enrollment close date plus a buffer for audit purposes. Evidence strings containing PHI should be treated with the same retention controls as the source clinical data."

#### Issue S4: Comprehend Medical API Action Name Is Incorrect in Prerequisites (MEDIUM)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The permission listed is `comprehend:DetectEntities`. Amazon Comprehend Medical is a separate service from Amazon Comprehend. The correct IAM action for Comprehend Medical's entity detection is `comprehendmedical:DetectEntitiesV2`. A builder using `comprehend:DetectEntities` in their IAM policy will get AccessDenied when calling the Comprehend Medical API.

**Suggested fix:** Change `comprehend:DetectEntities` to `comprehendmedical:DetectEntitiesV2` in the prerequisites table.

---

### Architecture Expert Review

#### What's Done Well

The staged filtering architecture is the correct pattern. Running structured pre-screen first (cheap, fast, deterministic) before NLP deep screen (expensive, slow, probabilistic) is sound cost engineering. The recipe correctly identifies that this reduces the NLP workload by ~99% (180K to ~2K patients). The performance benchmarks are realistic and well-calibrated. The scoring approach with per-criterion confidence is architecturally sound. The multi-trial extension note ("Build the system to handle multiple concurrent trials from day one") is excellent forward-looking architecture advice.

#### Issue A1: No Dead Letter Queue or Error Handling in the NLP Stage (MEDIUM)

**Location:** Step 3 pseudocode (NLP Deep Screen)

**The problem:** The NLP deep screen iterates over candidates and calls Comprehend Medical for each patient's notes. The pseudocode has no error handling for:
- Comprehend Medical throttling (the service has per-account TPS limits)
- Individual patient processing failures (corrupt notes, encoding issues, timeout)
- Partial pipeline failures (what happens if the pipeline fails after processing 1,500 of 2,000 candidates?)

In a Step Functions orchestration, a single failed patient in the NLP stage could fail the entire pipeline execution if not handled. At 2,000 candidates with 3-8 seconds each, the pipeline runs for 15-30 minutes. A failure at minute 25 with no checkpointing means reprocessing everything.

**Suggested fix:** Add a note in the pseudocode or in "Why This Isn't Production-Ready": "The NLP stage should process candidates in batches with per-patient error isolation. Use Step Functions Map state with `maxConcurrency` to control parallelism and `toleratedFailurePercentage` to allow the pipeline to complete even if some patients fail NLP processing. Failed patients should be written to a DLQ (SQS or a separate DynamoDB status) for retry or manual review. Consider checkpointing progress so a pipeline restart doesn't reprocess already-screened candidates."

#### Issue A2: Athena Cost Estimate May Be Misleading for Large Patient Datasets (LOW)

**Location:** Prerequisites table, "Cost Estimate" row; Performance benchmarks table

**The problem:** The cost estimate states "Athena: ~$5/TB scanned." For a 180K patient registry with demographics, labs, medications, and diagnoses, the data volume depends heavily on format and partitioning. If the patient data lake stores clinical notes alongside structured data (as implied by the architecture), a naive Athena query could scan significantly more data than expected. The recipe doesn't mention partitioning strategy or columnar format (Parquet/ORC) for cost optimization.

**Suggested fix:** Add a brief note: "Athena costs depend on data scanned. Store structured patient data in Parquet format partitioned by relevant dimensions (e.g., patient cohort, data type) to minimize scan volume. Separate clinical notes from structured data in the S3 layout so the structured pre-screen doesn't scan note text."

#### Issue A3: EventBridge Trigger for Re-Screening Lacks Architectural Detail (LOW)

**Location:** "Why These Services" section, EventBridge paragraph

**The problem:** The recipe mentions EventBridge triggers re-screening "when new trials open or criteria change" but doesn't explain the source of these events. ClinicalTrials.gov doesn't push events. The architecture diagram shows a "ClinicalTrials.gov Feed" but doesn't explain how that feed is implemented (polling schedule? RSS? API polling Lambda?).

**Suggested fix:** Add one sentence: "A scheduled Lambda polls the ClinicalTrials.gov API daily for new or amended trials matching your therapeutic areas, and publishes events to EventBridge when changes are detected."

---

### Networking Expert Review

#### What's Done Well

The recipe specifies VPC placement for SageMaker endpoints and Glue jobs in private subnets. VPC endpoints are mentioned for S3, DynamoDB, and SageMaker Runtime. TLS 1.2+ is required for all data in transit.

#### Issue N1: Missing VPC Endpoint for Comprehend Medical (HIGH)

**Location:** Prerequisites table, "VPC" row

**The problem:** The VPC prerequisites state: "SageMaker endpoints and Glue jobs in private subnets. VPC endpoints for S3, DynamoDB, and SageMaker Runtime." The recipe uses Amazon Comprehend Medical for clinical entity extraction in the NLP deep screen stage. If Lambda functions calling Comprehend Medical are in a VPC (which they should be, given they're processing PHI), they need either a NAT Gateway or a VPC endpoint for Comprehend Medical to reach the service.

The recipe lists VPC endpoints for S3, DynamoDB, and SageMaker Runtime but omits Comprehend Medical. A builder who places their Lambda functions in private subnets (correct for PHI processing) and only creates the listed VPC endpoints will find that Comprehend Medical calls time out.

The VPC endpoint for Comprehend Medical is: `com.amazonaws.{region}.comprehendmedical`.

**Suggested fix:** Add Comprehend Medical to the VPC endpoints list: "VPC endpoints for S3, DynamoDB, SageMaker Runtime, and Comprehend Medical." Also consider adding Step Functions (`com.amazonaws.{region}.states`) and Lambda (`com.amazonaws.{region}.lambda`) VPC endpoints if the orchestration components are VPC-bound.

#### Issue N2: No Mention of Egress Controls for Clinical Notes (MEDIUM)

**Location:** Architecture section generally

**The problem:** Clinical notes containing PHI flow from S3 to Lambda/SageMaker for NLP processing. If any component has internet egress (via NAT Gateway), there's a theoretical exfiltration path. The recipe doesn't mention security group egress rules or VPC flow logs for monitoring data movement.

**Suggested fix:** Add a brief note in prerequisites or "Why This Isn't Production-Ready": "Restrict security group egress to VPC endpoints only (no internet egress) for Lambda functions and SageMaker endpoints processing clinical notes. Enable VPC Flow Logs to monitor data movement patterns."

---

### Voice Reviewer

#### What's Done Well

The recipe nails CC's voice throughout. The opening scenario (research coordinator, 180K patients, 20 charts per hour) is vivid and makes the reader feel the pain. Parenthetical asides are used well ("(ok, this is a gross oversimplification, but stay with me)" energy without being that exact phrase). The "Honest Take" section is excellent: the medication list reliability insight ("The 'active medication list' is aspirational, not factual") is peak CC voice. The precision/recall tradeoff discussion is practical and non-academic. No documentation-voice detected.

#### Issue V1: No Em Dashes Found (PASS)

Searched the entire recipe. Zero em dashes. Clean.

#### Issue V2: Vendor Balance Is Well Maintained (PASS)

The Problem and Technology sections are entirely vendor-agnostic. AWS services first appear in "The AWS Implementation" section. The General Architecture Pattern section uses no vendor names. Estimated 72/28 split (slightly over the 70/30 target but within acceptable range).

#### Issue V3: One Sentence Slightly Documentation-Voice (LOW)

**Location:** "Why These Services" section, first sentence about SageMaker

**The problem:** "The clinical NLP pipeline (entity extraction, negation detection, temporal reasoning) requires custom models trained on clinical text. SageMaker provides the training infrastructure and real-time inference endpoints." The second sentence is slightly flat/documentation-voice compared to the rest of the recipe.

**Suggested fix:** Minor. Could be: "SageMaker gives you the training infrastructure and real-time inference endpoints for those custom models." But this is nitpicking; the overall voice is strong.

---

## Stage 2: Expert Discussion

### Conflicts and Overlaps

1. **Security (S2) and Architecture overlap on governance:** The IRB/consent issue (S2) is both a security/compliance concern and an architectural concern (the system needs to enforce access controls that align with the IRB-approved protocol). Resolution: treat as a security/compliance finding since the fix is primarily documentation and governance framing, not architectural change.

2. **Networking (N1) and Architecture overlap on VPC design:** The missing Comprehend Medical VPC endpoint (N1) would cause a functional failure, not just a security gap. Resolution: classify as HIGH because it's a deployment blocker (the NLP stage won't work without it in a properly secured VPC).

3. **Security (S1) and Networking (N1) reinforce each other:** Both point to the same theme: the recipe's security posture is stated at a high level but lacks the specificity needed for a builder to implement correctly on the first try. The IAM permissions are too broad and the VPC endpoints are incomplete.

### Priority Resolution

The three HIGH findings are all independently important and non-overlapping:
- S1 (IAM least-privilege): affects who can access what
- S2 (IRB governance): affects whether you can legally operate the system
- N1 (VPC endpoint): affects whether the system functions at all in a secure deployment

None are CRITICAL because: S1 is a hardening gap (the system works but is over-permissioned), S2 is a documentation gap (the recipe acknowledges the issue but underweights it), and N1 is a deployment gap (fixable with one VPC endpoint creation).

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

No CRITICAL findings. 3 HIGH findings (threshold for FAIL is >3 HIGH). The recipe is architecturally sound, clinically accurate, well-written, and provides actionable guidance. The HIGH findings are all addressable without restructuring the recipe.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Prerequisites, IAM Permissions | IAM permissions are not least-privilege and use wrong Comprehend action name | Scope all permissions to specific resource ARNs; change `comprehend:DetectEntities` to `comprehendmedical:DetectEntitiesV2`; consider separate roles for pre-screen and NLP stages |
| 2 | HIGH | Security | "Why This Isn't Production-Ready" | IRB/consent governance is acknowledged but insufficiently detailed for a research screening system | Expand into a dedicated subsection covering 45 CFR 46.116(f), HIPAA 164.512(i), and the pre-screening vs. screening distinction |
| 3 | HIGH | Networking | Prerequisites, VPC row | Missing VPC endpoint for Comprehend Medical; system will fail in properly secured VPC | Add `com.amazonaws.{region}.comprehendmedical` to VPC endpoints list |
| 4 | MEDIUM | Security | Step 4 pseudocode, DynamoDB writes | No data retention policy for matching results containing derived PHI | Add retention policy guidance; suggest DynamoDB TTL keyed to trial enrollment close date |
| 5 | MEDIUM | Security | Prerequisites, IAM Permissions | Comprehend Medical API action name is incorrect (`comprehend:DetectEntities` vs `comprehendmedical:DetectEntitiesV2`) | Correct the action name (also covered in finding #1) |
| 6 | MEDIUM | Architecture | Step 3 pseudocode | No error handling, throttling protection, or checkpointing in NLP stage | Add guidance on Map state with maxConcurrency, toleratedFailurePercentage, and per-patient error isolation |
| 7 | MEDIUM | Networking | Architecture generally | No egress controls or flow log monitoring mentioned for PHI-processing components | Add note on restricting security group egress to VPC endpoints only; enable VPC Flow Logs |
| 8 | LOW | Architecture | Prerequisites, Cost Estimate | Athena cost estimate doesn't mention partitioning or columnar format for cost control | Add note on Parquet format and partitioning strategy |
| 9 | LOW | Architecture | "Why These Services", EventBridge | EventBridge trigger source (ClinicalTrials.gov polling) not explained | Add one sentence explaining the polling Lambda pattern |
| 10 | LOW | Voice | "Why These Services", SageMaker sentence | One slightly flat/documentation-voice sentence | Minor rewording for consistency with surrounding voice |

---

### Summary

This is a well-crafted recipe that teaches clinical trial matching effectively. The staged architecture is correct, the clinical context is accurate, the NLP challenges are honestly presented, and the voice is strong throughout. The three HIGH findings are all "hardening" issues rather than fundamental design flaws: tighten IAM, add a VPC endpoint, and expand the regulatory governance section. The recipe is ready for editing after these fixes are applied.
