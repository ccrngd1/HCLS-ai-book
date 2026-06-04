# Expert Review: Recipe 9.10 - Multi-Modal Imaging Fusion and Analysis

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Review date:** 2026-06-04
**Complexity rating:** Appropriate (Complex / Research-Production boundary)
**Overall assessment:** PASS

---

## Executive Summary

Recipe 9.10 is an excellent capstone recipe for the Computer Vision chapter. The problem statement is compelling and clinically grounded (radiation oncology treatment planning), the technology section provides genuinely educational coverage of image registration from first principles, and the architecture is well-suited to the stated requirements. The pseudocode is thorough and demonstrates deep understanding of the clinical workflow.

The recipe has 0 CRITICAL findings and 2 HIGH findings (below the FAIL threshold of >3 HIGH). The HIGH findings concern an overly broad IAM permissions list that violates least-privilege, and a missing discussion of how DICOM data transits from institutional PACS to the cloud (a significant PHI-in-transit concern). The remaining findings are medium and low severity, covering quality threshold documentation, model retraining governance, and minor architectural hardening.

The 70/30 vendor balance is well-maintained. The Technology section (registration methods, similarity metrics, fusion strategies) is entirely vendor-agnostic and would educate a reader on any cloud. The Honest Take section is one of the strongest in the chapter, correctly identifying preprocessing quality and failure detection as the real production challenges.

---

## Stage 1: Independent Expert Reviews

### Security Expert

#### S1 - HIGH: IAM Permissions Are Overly Broad and Not Scoped per Component

**Issue:** The Prerequisites table lists IAM permissions as: `medical-imaging:*` (HealthImaging), `s3:GetObject/PutObject`, `sagemaker:InvokeEndpoint`, `states:StartExecution`, `ecs:RunTask`, `dynamodb:PutItem/GetItem/Query`, `logs:CreateLogGroup/PutLogEvents`.

Two problems:
1. `medical-imaging:*` is a wildcard grant on all HealthImaging actions. This includes `DeleteImageSet`, `UpdateImageSetMetadata`, and `TagResource`. The pipeline only needs `GetImageSet`, `GetImageFrame`, `CreateDatastore`, and `StartDICOMImportJob` (for output). A wildcard here allows an ECS task or Step Functions execution to delete imaging data.
2. The permissions are listed as a flat set with no indication of which component (ECS preprocessing, SageMaker endpoint, Step Functions, Lambda triggers) receives which permissions. The ECS preprocessing container needs `s3:GetObject/PutObject` and `medical-imaging:GetImageFrame` but should never have `sagemaker:InvokeEndpoint`. The SageMaker endpoint role needs only `s3:GetObject` for model artifacts and input, never `medical-imaging:*`.

**Location:** Prerequisites table, "IAM Permissions" row.

**Suggested fix:** Replace the flat list with per-component scoping:

```text
| IAM Permissions | Step Functions: states:StartExecution, ecs:RunTask, sagemaker:InvokeEndpoint, dynamodb:PutItem/UpdateItem/GetItem
|                 | ECS (Preprocessing): medical-imaging:GetImageSet/GetImageFrame, s3:GetObject/PutObject on processing-bucket/*
|                 | ECS (Post-processing): s3:GetObject on processing-bucket/*, medical-imaging:StartDICOMImportJob, dynamodb:UpdateItem
|                 | SageMaker Endpoint: s3:GetObject on processing-bucket/*/preprocessed*, s3:PutObject on processing-bucket/*/registered*
|                 | All: logs:CreateLogGroup, logs:PutLogEvents |
```

Or add a note: "Production deployments must scope each component (ECS tasks, SageMaker execution role, Step Functions role) to only the actions and resources it requires. The list above is the permission union; never apply it as a single shared role."

---

#### S2 - MEDIUM: Quality Thresholds Are Hardcoded Without Clinical Governance Discussion

**Issue:** Step 4 (validate_registration_quality) uses hardcoded thresholds: `MI_THRESHOLD` (commented as "typically 1.0-1.5"), folding fraction > 0.001, and mean TRE > 3.0mm. These thresholds directly determine whether a registration is accepted for clinical use in treatment planning. The AAPM TG-132 report recommends < 2mm accuracy for treatment planning fusion, and the recipe uses 3mm as the alert threshold.

The problem is not the specific values (3mm as an automated alert is reasonable with physicist review as the safety net). The problem is that there is no discussion of how these thresholds should be governed: who sets them, how they are validated, how changes are controlled, and where they are stored. In a clinical system, modifying `MI_THRESHOLD` from 1.0 to 0.8 could cause the system to accept registrations that were previously flagged for review. That is a clinical safety decision, not a software configuration decision.

**Location:** Step 4 pseudocode, threshold constants and the comment "typically 1.0-1.5."

**Suggested fix:** Add a paragraph after the Step 4 pseudocode or in The Honest Take: "Quality thresholds (MI, TRE, folding fraction) are clinical parameters, not software configurations. Changes to these values alter the safety boundary of the system. In production, store thresholds in a versioned configuration with change audit trail. Any threshold modification should require medical physics sign-off and documented validation on a test cohort before deployment. Treat threshold changes with the same governance as model updates."

---

#### S3 - MEDIUM: No Mention of De-identification for Development and Testing

**Issue:** The Prerequisites table mentions "Never use real patient images in dev without proper IRB and de-identification" under Sample Data. This is correct but insufficient. The recipe does not address what de-identification means for multi-modal imaging specifically. DICOM headers contain extensive PHI (patient name, DOB, MRN, referring physician, institution). Even "anonymized" DICOM may retain burned-in text in pixel data (patient name on ultrasound, or demographics overlay on older CT scouts).

For a recipe specifically about fusing multiple imaging studies from the same patient, de-identification must be coordinated across studies: if you assign a new pseudonym to the CT, the MRI must get the same pseudonym or the fusion pipeline will reject the pair (patient ID mismatch validation in Step 1).

**Location:** Prerequisites table, "Sample Data" row.

**Suggested fix:** Expand the note: "For development: use TCIA public datasets (already de-identified with consistent pseudonyms across modalities). For institutional test data: coordinate de-identification across all studies in a fusion set using consistent pseudonym mapping. Standard DICOM de-identification must strip UIDs, dates, and all demographic tags while preserving spatial metadata (ImagePositionPatient, ImageOrientationPatient, PixelSpacing) that registration depends on. Tools like CTP (Clinical Trial Processor) or DicomCleaner handle this, but verify that geometry tags survive the de-identification process."

---

#### S4 - LOW: SageMaker Endpoint Encryption Specified but No Inter-Container Traffic Encryption

**Issue:** The Prerequisites table specifies "SageMaker endpoint: KMS-encrypted volumes." This addresses data at rest on the endpoint instance. However, the architecture has ECS tasks communicating with SageMaker via the VPC endpoint. The data transmitted (volumetric arrays of patient anatomy) is PHI in transit. The recipe correctly notes "all transit over TLS" but does not specify that the SageMaker endpoint must have `EnableInterContainerTrafficEncryption` set if multi-instance endpoints are used.

For a single-instance endpoint (likely for this workload given the per-study inference pattern), this is not relevant. But the recipe mentions `ml.g5.2xlarge for production throughput` and throughput of "15-30 studies/hour" which might motivate multi-instance deployment.

**Location:** Prerequisites table, "Encryption" row.

**Suggested fix:** Add: "If using multi-instance SageMaker endpoints for throughput scaling, enable inter-container traffic encryption to ensure PHI is encrypted when distributed across instances."

---

### Architecture Expert

#### A1 - MEDIUM: No Discussion of Concurrent Fusion Job Handling or Resource Contention

**Issue:** The architecture uses SageMaker endpoints for GPU inference and ECS Fargate for preprocessing. In a radiation therapy department, multiple patients may have planning imaging completed within the same hour. If 5 CT-MRI pairs arrive simultaneously, the pipeline needs to handle concurrent execution.

Step Functions will start multiple executions. ECS Fargate will spin up containers (within account/cluster limits). But the SageMaker endpoint is the bottleneck: with a single `ml.g4dn.xlarge` instance processing one inference at a time (30-120 seconds for deformable registration), 5 concurrent requests will queue. The performance benchmarks acknowledge "15-30 studies/hour" for deformable, but the architecture does not discuss queuing behavior, SageMaker's internal request queue depth, or how to prevent timeout failures when the queue backs up.

**Location:** Architecture Diagram and Performance Benchmarks section.

**Suggested fix:** Add a note after the architecture diagram or in performance benchmarks: "For concurrent fusion jobs, the SageMaker endpoint queues requests internally. With deformable registration taking 30-120 seconds, a single-instance endpoint queues more than 2-3 concurrent requests will experience latency. For departments processing >10 fusion studies/hour, configure SageMaker auto-scaling with a target of InvocationsPerInstance < 2. Alternatively, use SageMaker Asynchronous Inference for long-running registration jobs, which provides built-in queuing with SNS notification on completion rather than blocking the Step Functions execution."

---

#### A2 - MEDIUM: No Error Handling Strategy for Partial Pipeline Failures

**Issue:** The pipeline has 5 steps. If Step 3 (registration) succeeds but Step 4 (quality validation) fails, the registered output exists in S3 but is flagged as failed. If Step 5 (DICOM export) fails after quality passes, the registration is validated but clinical systems never receive it. The recipe mentions Step Functions retry logic in the "Why These Services" section but does not describe what happens on partial failure.

Specific scenarios not addressed:
- Registration succeeds, QA fails: routed to physicist review (covered). But what about cleanup of the registered output in S3? Is it retained for physicist review or deleted?
- QA passes, DICOM export to HealthImaging fails (e.g., DICOM validation error): the DynamoDB record shows "QA_PASSED" but the clinician never sees the output. Is there a retry? An alert?
- Step Functions execution times out (default 1 year, but if configured shorter): what state is the job left in?

**Location:** Step Functions orchestrator section and the walkthrough introduction.

**Suggested fix:** Add a paragraph in the Step Functions discussion: "Configure Step Functions error handling per step: preprocessing failures retry 2x with backoff then fail the job; registration failures retry 1x (GPU operations are expensive to retry blindly) then route to manual queue; QA failures route to physicist review with all intermediate outputs retained in S3; export failures retry 3x then alert operations with the validated registration available for manual export. Use Step Functions ResultPath to preserve intermediate outputs in the execution state for debugging."

---

#### A3 - MEDIUM: Cost Estimate Does Not Account for Data Transfer or Storage Duration

**Issue:** The cost estimate states "$2.50-8.00 per fusion study" broken down as: HealthImaging ($0.50), SageMaker GPU ($1.00-3.00), ECS ($0.30), Step Functions/S3/DynamoDB ($0.10). This accounts for compute but not:

1. **S3 storage of intermediate volumes:** A single preprocessed volume (brain at 1mm isotropic) is ~250MB. With fixed + moving + registered + deformation field, one job produces ~1GB of intermediate data. At $0.023/GB/month, this is negligible if cleaned up promptly, but if retained for 30 days (for physicist review or audit), 100 studies/month = 100GB = $2.30/month in storage alone.
2. **HealthImaging storage:** Input studies (CT + MRI + PET) might be 2-5GB per patient. HealthImaging pricing is separate from S3.
3. **Data transfer:** If studies are transferred from on-prem via the internet (not Direct Connect), data transfer costs for multi-GB imaging studies add up.

The per-study cost is reasonable for compute. But a reader budgeting for production might be surprised by storage and transfer costs at scale.

**Location:** Prerequisites table, "Cost Estimate" row.

**Suggested fix:** Add a note: "Cost estimate covers per-study compute. Additional costs: S3 intermediate storage (~1GB/study, implement lifecycle policy to transition to Glacier or delete after QA acceptance); HealthImaging storage for input and output studies (see HealthImaging pricing); data transfer from on-prem if not using Direct Connect. For a department processing 50 studies/day: compute ~$125-400/day; storage accumulation requires lifecycle management."

---

#### A4 - LOW: Performance Benchmarks Could Note Warm-Start vs. Cold-Start Latency

**Issue:** The performance benchmarks show "Registration time: 5-15 seconds (rigid), 30-120 seconds (deformable)." These are GPU inference times. But if the SageMaker endpoint scales to zero (or scales up a new instance), there is a cold-start penalty of 3-5 minutes for model loading. The "Total pipeline time" of 30-60 seconds (rigid) or 2-5 minutes (deformable) would be significantly longer on a cold start.

**Location:** Performance benchmarks table.

**Suggested fix:** Add a footnote: "Pipeline times assume a warm SageMaker endpoint. Cold-start (first request after scale-up) adds 3-5 minutes for model loading. For predictable latency in clinical use, configure minimum instance count = 1 to avoid scale-to-zero."

---

### Networking Expert

#### N1 - HIGH: No Discussion of PACS-to-Cloud Data Path for Multi-GB Imaging Studies

**Issue:** The architecture diagram shows `PACS / Imaging Archive` connecting to `AWS HealthImaging` via "DICOM Push / DICOMweb." This arrow represents multi-gigabyte PHI transfers (a CT + MRI + PET set for one patient can easily be 3-8GB) traversing from the hospital network to AWS. The recipe provides no guidance on how this connection should be secured, what bandwidth is required, or what network architecture supports it.

For a radiation therapy department that needs fusion results within 30 minutes of scan completion (to avoid delaying the planning workflow), the network path must support reliable, low-latency transfer of large imaging datasets. A hospital with 100Mbps internet can transfer 3GB in ~4 minutes, which is acceptable. But many facilities share bandwidth with other clinical systems, and congestion during peak hours could delay transfers.

More critically: DICOMweb over public internet means PHI traverses the public network. While TLS encrypts it in transit, some healthcare compliance officers require private network paths for bulk imaging data.

**Location:** Architecture Diagram, the connection between "PACS / Imaging Archive" and "AWS HealthImaging."

**Suggested fix:** Add after the architecture diagram: "The network path from institutional PACS to AWS HealthImaging must support reliable transfer of multi-GB imaging studies with PHI encryption in transit. Options: (1) AWS Direct Connect for dedicated bandwidth and private connectivity (preferred for production radiation oncology workflows requiring predictable latency); (2) Site-to-Site VPN for encrypted tunnel over existing internet (acceptable if bandwidth is sufficient); (3) AWS HealthImaging supports DICOMweb over TLS, which encrypts data in transit over public internet but may not satisfy institutional requirements for private network paths. For departments requiring fusion results within 30 minutes of scan completion, ensure the network path can sustain 50-100 Mbps dedicated to imaging transfer."

---

#### N2 - MEDIUM: VPC Endpoint List Is Correct but Missing CloudWatch Metrics Endpoint

**Issue:** The Prerequisites table VPC row states: "VPC endpoints for S3, DynamoDB, SageMaker, HealthImaging, and CloudWatch Logs." The CloudWatch Logs endpoint (`com.amazonaws.{region}.logs`) is listed, but the architecture also requires CloudWatch Metrics for the dashboard and alarms described in the architecture diagram. Without a `com.amazonaws.{region}.monitoring` VPC endpoint, `PutMetricData` calls from ECS tasks in private subnets will fail (or require NAT gateway egress).

Additionally, the Step Functions VPC endpoint (`com.amazonaws.{region}.states`) is not listed. If the ECS tasks need to send task tokens back to Step Functions (for callback patterns), they need this endpoint. The architecture uses Step Functions invoking ECS (not ECS calling back to Step Functions), so this may not be needed, but it is worth clarifying.

**Location:** Prerequisites table, "VPC" row.

**Suggested fix:** Expand: "VPC endpoints for S3 (Gateway), DynamoDB (Gateway), SageMaker Runtime (Interface), HealthImaging (Interface), CloudWatch Logs (Interface), and CloudWatch Monitoring (Interface). If ECS tasks use callback patterns with Step Functions, also add States endpoint (Interface)."

---

#### N3 - LOW: No Security Group Guidance for SageMaker Endpoint

**Issue:** The Prerequisites specify VPC deployment for SageMaker but do not describe security group configuration. The SageMaker endpoint needs inbound rules allowing HTTPS (port 443) from the Step Functions/ECS task security groups, and should deny all other inbound traffic. Without this guidance, a reader might configure the endpoint with a permissive security group.

**Location:** Prerequisites table, "VPC" row.

**Suggested fix:** Add: "SageMaker endpoint security group: allow inbound TCP 443 from ECS task security group and Step Functions VPC endpoint ENI security group only. Deny all other inbound. No outbound internet access required (model artifacts loaded at deploy time from S3 via VPC endpoint)."

---

### Voice Reviewer

#### V1 - LOW: One Blog URL Has a Placeholder Comment

**Issue:** In the Additional Resources section under "AWS Solutions and Blogs," there is a link to the AWS ML Blog with an HTML comment: `<!-- TODO: verify specific blog post URL exists -->`. This should not appear in the published recipe. It indicates an unverified resource.

**Location:** Additional Resources, "AWS Solutions and Blogs" subsection, last bullet.

**Suggested fix:** Either verify and provide the specific blog post URL, or remove the entry entirely. The style guide prohibits fake or unverified URLs. A TODO comment is better than a broken link, but neither should ship.

---

#### V2 - LOW: Vendor Balance Is Excellent

**Observation:** The recipe's vendor-agnostic content (Problem, Technology, General Architecture Pattern) is approximately 3,500 words. The AWS-specific content (Implementation section) is approximately 2,500 words including pseudocode. The prose ratio is roughly 60/40 if you count pseudocode, or 70/30 for explanatory prose only. This is well within the style guide's target. The Technology section is genuinely educational and cloud-agnostic. A reader implementing on Azure or GCP would learn registration fundamentals, similarity metrics, and fusion strategies without needing to mentally filter out vendor references.

No fix needed.

---

#### V3 - LOW: Tone Is Consistently Strong Throughout

**Observation:** The recipe maintains the engineer-explaining-something-cool voice throughout. Highlights: "Think of it like this: if I point to a voxel in the MRI..." (relatable analogy), "Here's what makes multi-modal fusion fundamentally harder..." (building intrigue), "Skip bias field correction on MRI and your registration will be biased by the artifact" (practical consequence). The Honest Take section is particularly strong: "Multi-modal fusion is one of those problems where the 80% solution is straightforward...and the last 20% will consume your entire career."

No em dashes found. No documentation-voice detected. No marketing language.

No fix needed.

---

## Stage 2: Expert Discussion

**Conflicts identified:** None. All expert findings are complementary.

**Overlapping concerns:**
- S1 (IAM wildcard) and N2 (VPC endpoints) both relate to the Prerequisites table and should be addressed together in a single revision.
- A2 (partial pipeline failure) and the quality validation step (Step 4) overlap: when QA fails, the error handling path is defined (physicist review), but when other steps fail, it is not.
- N1 (PACS-to-cloud network) and A3 (cost estimate) overlap: data transfer costs depend on the network path chosen, which is not discussed.

**Priority resolution:** N1 (PACS-to-cloud data path) is the highest-priority fix because it represents a gap in PHI-in-transit guidance. A reader who implements DICOMweb over public internet without understanding the compliance implications could create an institutional risk. S1 (IAM wildcard) is second priority because `medical-imaging:*` grants destructive permissions that are never needed by the pipeline.

---

## Stage 3: Synthesized Feedback

### Verdict: PASS

The recipe has 0 CRITICAL findings and 2 HIGH findings (threshold for FAIL is >3 HIGH). The HIGH findings are addressable with additions to the Prerequisites table and a brief architectural note on network connectivity. The core content (problem statement, technology explanation, pseudocode, honest take) is outstanding.

### Prioritized Findings

| # | Severity | Expert | Location | Issue | Fix |
|---|----------|--------|----------|-------|-----|
| S1 | HIGH | Security | Prerequisites table, IAM row | `medical-imaging:*` is a wildcard grant including destructive actions; permissions not scoped per component | Break into per-component roles; replace wildcard with specific HealthImaging actions |
| N1 | HIGH | Networking | Architecture Diagram, PACS-to-HealthImaging arrow | No guidance on network path for multi-GB PHI transfers from institutional PACS to cloud | Add Direct Connect/VPN/DICOMweb options with bandwidth and compliance considerations |
| S2 | MEDIUM | Security | Step 4 pseudocode, threshold constants | Quality thresholds are clinical safety parameters with no governance discussion | Add paragraph on threshold governance, versioning, and medical physics sign-off requirements |
| S3 | MEDIUM | Security | Prerequisites, Sample Data row | De-identification guidance insufficient for multi-modal fusion (must coordinate across studies) | Expand with coordinated de-identification guidance preserving geometry tags |
| A1 | MEDIUM | Architecture | Architecture Diagram / Performance Benchmarks | No discussion of concurrent job handling or SageMaker queue behavior under load | Add note on auto-scaling triggers and async inference option for high-volume departments |
| A2 | MEDIUM | Architecture | Step Functions orchestrator | No error handling strategy for partial pipeline failures (registration succeeds, export fails) | Add per-step error handling configuration with retry/alert/cleanup guidance |
| A3 | MEDIUM | Architecture | Prerequisites, Cost Estimate row | Cost estimate covers compute only; misses storage accumulation and data transfer | Add storage lifecycle and transfer cost notes for production budgeting |
| N2 | MEDIUM | Networking | Prerequisites, VPC row | CloudWatch Monitoring VPC endpoint missing from list | Add `com.amazonaws.{region}.monitoring` interface endpoint |
| S4 | LOW | Security | Prerequisites, Encryption row | No inter-container encryption note for multi-instance SageMaker endpoints | Add note on EnableInterContainerTrafficEncryption for multi-instance deployments |
| A4 | LOW | Architecture | Performance benchmarks table | Cold-start latency not mentioned; pipeline times assume warm endpoint | Add footnote on cold-start penalty and minimum instance count recommendation |
| V1 | LOW | Voice | Additional Resources, AWS Blogs bullet | TODO comment in published content; unverified URL | Verify and provide specific URL, or remove the entry |
| N3 | LOW | Networking | Prerequisites, VPC row | No security group guidance for SageMaker endpoint | Add inbound rule specification (443 from ECS/Step Functions SGs only) |

### Summary

This is an excellent recipe that demonstrates mastery of both the clinical domain (radiation oncology treatment planning, AAPM standards, multi-modal registration challenges) and the technical implementation. The technology section is one of the most educational in the entire cookbook: it builds from "what is registration?" through rigid/affine/deformable/deep-learning methods with clear explanations of why each matters clinically. The similarity metrics discussion (mutual information, NCC, deep learning similarity) is genuinely useful for someone new to multi-modal imaging.

The pseudocode is well-structured with clear business-level explanations before each block. The quality validation step (Step 4) is particularly strong, correctly identifying Jacobian determinant analysis as the key safety check for deformable registration. The Honest Take section nails the real production challenge: not making registration faster, but reliably detecting when it has failed.

The findings are primarily about security hardening (IAM scoping, threshold governance), network guidance (the PACS-to-cloud path is a real gap), and operational completeness (error handling, cost estimation). The core technical content and architecture pattern are sound and ready for publication after these additions.

Recommended for publication after addressing the two HIGH findings.

---

*Review complete. Pseudocode simplifications are acknowledged and not critiqued.*
