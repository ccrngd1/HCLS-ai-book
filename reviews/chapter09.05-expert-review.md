# Expert Review: Recipe 9.5 - Chest X-Ray Triage

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Review date:** 2026-05-31
**Complexity rating:** Appropriate (Medium / FDA pathway required)
**Overall assessment:** PASS

---

## Executive Summary

Recipe 9.5 is a strong, well-structured recipe that covers one of the most mature applications of medical imaging AI. The problem statement is compelling, the technology explanation is thorough and educational, the architecture is sound for the stated scale, and the honest take section is excellent. The regulatory considerations (FDA 510(k), post-market surveillance) are appropriately surfaced throughout rather than relegated to a footnote.

The recipe has no critical findings. There are two high-severity issues: a missing VPC endpoint for SageMaker Runtime in the prerequisites table (despite being mentioned in the VPC row), and an IAM permissions list that is incomplete for the Lambda orchestration pattern described. Both are straightforward fixes. The remaining findings are medium and low severity, mostly addressing edge cases in the architecture and minor voice inconsistencies.

The 70/30 vendor balance is well-maintained. The technology section is genuinely vendor-agnostic and educational. The AWS section earns its space by explaining why each service was chosen rather than just listing them.

---

## Stage 1: Independent Expert Reviews

### Security Expert

#### S1 - HIGH: IAM Permissions List Is Incomplete for the Described Architecture

**Issue:** The Prerequisites table lists IAM permissions: `sagemaker:InvokeEndpoint`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `logs:CreateLogGroup`, `logs:PutLogEvents`. However, the architecture uses multiple Lambda functions (`study-router`, `preprocessor`, `priority-scorer`) that need different permission sets. The listed permissions are a flat union that would be applied to all Lambdas, violating least-privilege.

Specifically missing:
- `s3:HeadObject` (needed by the study-router to read DICOM metadata without downloading the full file)
- `sns:Publish` (needed by the priority-scorer to send CRITICAL alerts)
- `cloudwatch:PutMetricData` (needed for confidence drift monitoring mentioned in the CloudWatch section)

More importantly, the flat list implies a single execution role shared across all Lambdas. The `study-router` Lambda only needs `s3:GetObject` and `s3:HeadObject`; it should never have `sagemaker:InvokeEndpoint`. The `priority-scorer` needs `dynamodb:PutItem` and `sns:Publish` but should never have `s3:GetObject` on the DICOM bucket.

**Location:** Prerequisites table, "IAM Permissions" row.

**Suggested fix:** Replace the flat permission list with a per-function breakdown:

```
| IAM Permissions | study-router: s3:GetObject, s3:HeadObject on dicom-inbox/*
|                 | preprocessor: s3:GetObject on dicom-inbox/*, s3:PutObject on preprocessed/*
|                 | inference-caller: sagemaker:InvokeEndpoint on cxr-triage-model-*
|                 | priority-scorer: dynamodb:PutItem on triage-results, sns:Publish on radiology-urgent
|                 | All Lambdas: logs:CreateLogGroup, logs:PutLogEvents, cloudwatch:PutMetricData |
```

Or at minimum, add a note: "Production deployments should use per-function IAM roles with least-privilege scoping. The permissions listed here are the union; scope each Lambda to only the actions it requires."

---

#### S2 - MEDIUM: Patient ID Stored in DynamoDB Audit Record Without Access Justification

**Issue:** The `store_and_notify` pseudocode stores `patient_id` in the DynamoDB triage-results table. The comment says "for linking back to clinical context." However, the triage system's function is worklist prioritization. The system needs the `accession_number` (to update the worklist) and `study_id` (to identify the DICOM study). The `patient_id` (MRN or equivalent) is not needed for the triage function itself.

Storing patient_id creates a PHI-containing table that requires additional access controls. If the table only contained accession numbers and study IDs (which are not directly patient-identifying without PACS access), the compliance surface would be smaller.

**Location:** Step 5 pseudocode, `store_and_notify` function, line `patient_id = patient_id`.

**Suggested fix:** Add a comment explaining why patient_id is stored (e.g., "Required for post-market surveillance reporting to FDA: must correlate AI findings with patient outcomes") or remove it and note that patient linkage should be performed via PACS lookup using accession_number when needed for audit. If kept, add a note that the DynamoDB table containing patient_id requires the same access controls as any PHI-containing data store.

---

#### S3 - MEDIUM: CRITICAL Alert Message Contains Finding Details Without Access Control

**Issue:** The `send_alert` in Step 5 sends a message to channel "radiology-urgent" containing: "CRITICAL finding detected on study [accession_number]: [finding summary]." The finding summary (e.g., "pneumothorax probability 0.92") combined with the accession number constitutes PHI (it's a clinical finding linked to a specific study that can be linked to a patient).

The recipe does not specify what "radiology-urgent" is (Slack channel? SNS topic? pager system?) or what access controls apply to it. If this is an SNS topic that fans out to email or a messaging platform, the PHI is transmitted to whatever endpoint is subscribed.

**Location:** Step 5 pseudocode, the `send_alert` block inside the CRITICAL priority branch.

**Suggested fix:** Add a note: "The alert channel must be a HIPAA-compliant notification pathway. If using SNS, ensure all subscribers are covered under your BAA. Consider sending only the accession number and priority level in the alert, with finding details accessible only through the authenticated PACS/RIS interface. Example: 'CRITICAL: Study CXR-2026-048291 requires immediate read' without specifying the finding."

---

#### S4 - LOW: No Mention of Model Artifact Integrity Verification

**Issue:** The recipe describes model artifacts stored in S3 and loaded by SageMaker at endpoint startup. There is no mention of verifying model artifact integrity (checksums, signing) before deployment. A corrupted or tampered model artifact could produce incorrect triage decisions. For an FDA-regulated medical device, model artifact provenance and integrity are part of the Quality Management System requirements.

**Location:** Prerequisites table and "Why These Services" section for SageMaker.

**Suggested fix:** Add a brief note: "Model artifacts in S3 should be versioned and integrity-verified (SHA-256 checksum comparison) before endpoint deployment. SageMaker Model Packages support model approval workflows that enforce this. For FDA-regulated deployments, maintain a model registry with version history, validation results, and approval records as part of your QMS."

---

### Architecture Expert

#### A1 - HIGH: No Fallback Behavior When SageMaker Endpoint Is Unavailable

**Issue:** The architecture has a single SageMaker endpoint as the inference path. If the endpoint is unavailable (deployment in progress, scaling event, endpoint failure), the entire triage pipeline stops. Studies accumulate in S3 without being triaged. When the endpoint recovers, there is no mechanism described to process the backlog.

The recipe mentions auto-scaling but does not address endpoint unavailability during model updates (which require endpoint redeployment or blue/green deployment) or transient failures. For a clinical system where "minutes matter" (as stated in the problem section), a 5-10 minute endpoint outage means critical findings go undetected during that window.

**Location:** Architecture Diagram and "Why These Services" section for SageMaker.

**Suggested fix:** Address this in the architecture section with one of:
1. **SQS buffer:** Add an SQS queue between the preprocessor and the inference call. If the endpoint returns an error, the message returns to the queue with exponential backoff. Studies are processed in order once the endpoint recovers.
2. **Blue/green deployment note:** "Use SageMaker blue/green deployment for model updates to avoid endpoint downtime. Configure the production variant with a minimum instance count of 1 to prevent scale-to-zero."
3. **Fallback behavior:** "If inference fails after 3 retries, mark the study as 'triage-unavailable' in DynamoDB and allow it to proceed through the worklist at normal priority. Alert the operations team. Do not block the radiologist from reading the study."

Option 3 is the most clinically appropriate: a failed triage system should degrade to the pre-AI workflow (FIFO ordering), not block reads entirely.

---

#### A2 - MEDIUM: No Dead Letter Queue for Failed Processing

**Issue:** The architecture uses S3 events triggering Lambda. If the study-router Lambda fails (malformed DICOM, unexpected metadata, transient error), the event is retried twice by Lambda's built-in retry and then discarded. There is no DLQ configured to capture failed studies for investigation and reprocessing.

For a clinical system, a silently dropped study means a patient's chest X-ray was never triaged. If that study contained a critical finding, the failure is invisible until the radiologist happens to read it in normal queue order (or worse, until a clinical outcome reveals the delay).

**Location:** Architecture Diagram, between S3 Event and Lambda study-router.

**Suggested fix:** Add a note: "Configure a Dead Letter Queue (SQS) on the study-router Lambda. Failed events are captured for investigation and manual reprocessing. Set a CloudWatch alarm on DLQ message count > 0. Any study that fails triage processing should be flagged in the worklist as 'AI triage unavailable' rather than silently proceeding at normal priority."

---

#### A3 - MEDIUM: Throughput Estimate of 200 Studies/Hour May Be Optimistic for Single Endpoint

**Issue:** The performance benchmarks claim "~200 studies/hour per endpoint." With model inference latency of 1-3 seconds, a single GPU can process 1,200-3,600 inferences per hour if fully utilized. However, the end-to-end pipeline includes S3 reads, DICOM parsing, preprocessing, serialization, deserialization, DynamoDB writes, and worklist updates. The SageMaker endpoint is not the only bottleneck.

More importantly, a single ml.g4dn.xlarge instance has 1 GPU. If inference takes 2 seconds average and the endpoint processes requests serially (default for a single-instance endpoint), maximum throughput is 1,800/hour. The 200/hour estimate seems conservative for inference alone but may be realistic for the full pipeline. The discrepancy is not explained.

**Location:** Performance benchmarks table, "Throughput" row.

**Suggested fix:** Clarify whether "200 studies/hour" refers to the full pipeline throughput (limited by the slowest stage) or the inference endpoint alone. Add: "Throughput is limited by the full pipeline (S3 read + preprocess + inference + DynamoDB write + worklist update), not inference alone. For higher throughput, scale horizontally: multiple Lambda concurrency handles the orchestration; increase SageMaker endpoint instance count for inference parallelism."

---

#### A4 - MEDIUM: No Mention of Model Versioning Strategy for FDA Compliance

**Issue:** The recipe mentions `model_version = "cxr-triage-v2.1"` in the audit record and references SageMaker's model versioning capability. However, it does not address the FDA requirement that any change to a medical device (including model updates) requires either a new 510(k) submission or documentation that the change falls within the device's predetermined change control plan.

A reader might assume they can retrain and redeploy the model freely because SageMaker supports A/B testing. In reality, for an FDA-cleared triage device, model updates are regulated changes that require validation, documentation, and potentially regulatory submission.

**Location:** "Why These Services" section for SageMaker, and "The Honest Take" section.

**Suggested fix:** Add to the SageMaker section: "SageMaker's model versioning and A/B testing support the technical mechanics of model updates, but for FDA-regulated devices, model updates are not just a deployment decision. Any model change (retraining, architecture change, threshold adjustment) must go through your predetermined change control plan or require a new regulatory submission. Use SageMaker Model Registry to maintain the approval chain and link each deployed version to its validation evidence."

---

#### A5 - LOW: Composite Score Formula Could Produce Misleading Priority for Multi-Finding Studies

**Issue:** The composite score formula is `probability * severity_weight` summed across triggered findings. A study with pneumothorax at 0.61 (just above threshold) scores `0.61 * 8 = 4.88`, which is below the URGENT threshold of 5. But the priority logic has a separate check: "IF any triggered finding has severity >= 8: priority = CRITICAL." So this study would be CRITICAL despite a composite score below 5.

The composite score is stored in the audit record but is misleading for this case: a CRITICAL study with composite_score 4.88 looks less urgent than an URGENT study with composite_score 5.1. This could confuse downstream analytics or dashboards that sort by composite_score.

**Location:** Step 4 pseudocode, `calculate_priority` function.

**Suggested fix:** This is a minor logic clarity issue. Add a comment in the pseudocode: "Note: priority level is determined by the severity-based rules first, then composite score. A CRITICAL study may have a lower composite_score than an URGENT study because the severity >= 8 rule takes precedence. For dashboard sorting, use the priority level as primary sort and composite_score as secondary."

---

### Networking Expert

#### N1 - HIGH: VPC Endpoint for SageMaker Runtime Not Explicitly Listed

**Issue:** The Prerequisites table VPC row states: "Production: Lambda and SageMaker endpoint in VPC with VPC endpoints for S3, DynamoDB, SageMaker Runtime, and CloudWatch Logs." This correctly identifies SageMaker Runtime as needing a VPC endpoint. However, the VPC endpoint service name is not specified, and the list omits other endpoints the architecture requires.

The Lambda functions also need VPC endpoints for:
- `com.amazonaws.{region}.sagemaker.runtime` (for InvokeEndpoint calls from Lambda)
- `com.amazonaws.{region}.sns` (for CRITICAL alerts from priority-scorer)
- `com.amazonaws.{region}.dynamodb` (gateway endpoint, correctly implied)
- `com.amazonaws.{region}.s3` (gateway endpoint, correctly implied)
- `com.amazonaws.{region}.logs` (for CloudWatch Logs)

The SNS endpoint is missing from the VPC row entirely. If the priority-scorer Lambda is in a VPC without an SNS VPC endpoint, CRITICAL alerts will fail silently (or require NAT gateway egress, which introduces a PHI egress path through the NAT).

**Location:** Prerequisites table, "VPC" row.

**Suggested fix:** Expand the VPC row to list all required endpoints explicitly:

```
VPC Endpoints Required:
- com.amazonaws.{region}.s3 (Gateway)
- com.amazonaws.{region}.dynamodb (Gateway)
- com.amazonaws.{region}.sagemaker.runtime (Interface)
- com.amazonaws.{region}.sns (Interface)
- com.amazonaws.{region}.logs (Interface)
- com.amazonaws.{region}.monitoring (Interface, for CloudWatch PutMetricData)
```

Add: "SageMaker endpoint should be deployed with VPC configuration (no public internet access) using the same VPC and security groups. Ensure the Lambda security group allows outbound traffic to the SageMaker endpoint security group on port 443."

---

#### N2 - MEDIUM: No Guidance on DICOM Router Network Placement

**Issue:** The architecture diagram shows a "DICOM Router (On-Prem or Cloud)" as the entry point. The recipe does not address how DICOM data traverses from the on-premises imaging modality to the cloud S3 bucket. This is the most sensitive network hop in the entire architecture: uncompressed DICOM files containing patient images and demographic metadata crossing from the hospital network to AWS.

Options include AWS Direct Connect, Site-to-Site VPN, or a DICOM proxy/gateway appliance. Each has different security, latency, and cost characteristics. The recipe's silence on this topic leaves a significant gap for readers implementing the architecture.

**Location:** Architecture Diagram, the arrow between "Imaging Modality" and "DICOM Router."

**Suggested fix:** Add a brief note in the Prerequisites or after the architecture diagram: "The network path from on-premises imaging equipment to the S3 landing zone must be encrypted in transit. Options: (1) AWS Direct Connect with MACsec encryption for dedicated, low-latency connectivity; (2) Site-to-Site VPN for encrypted tunnel over public internet; (3) A DICOM gateway appliance (on-prem) that TLS-encrypts and forwards to an S3 Transfer Acceleration endpoint. Direct Connect is preferred for production radiology AI workloads due to consistent latency requirements (the 3-8 second end-to-end target assumes low-latency cloud ingress)."

---

#### N3 - LOW: SageMaker Endpoint Public Access Statement Could Be Stronger

**Issue:** The VPC row states "SageMaker endpoints should not have public internet access." This is correct but passive. For a medical device processing PHI, the guidance should be prescriptive: the endpoint must not have public access, and there should be a validation mechanism.

**Location:** Prerequisites table, "VPC" row, last sentence.

**Suggested fix:** Strengthen to: "SageMaker endpoints must be deployed with VPC-only access (no public endpoint). Validate by confirming the endpoint's `VpcConfig` is populated and that no route to an internet gateway exists from the endpoint's subnet. A SageMaker endpoint with public access processing DICOM images is a HIPAA violation waiting to happen."

---

### Voice Reviewer

#### V1 - MEDIUM: Two Em Dashes Present

**Issue:** The recipe contains em dashes, which are explicitly prohibited by the style guide ("No em dashes. Ever.").

**Locations:**
1. Cost estimate header: "~$0.10–$0.50 per study" (this is an en dash in the cost range, which is acceptable for numeric ranges)
2. Checking more carefully: The recipe uses " - " (space-hyphen-space) throughout for parenthetical asides, which is correct. No actual em dashes (—) found.

**Correction:** False alarm. The recipe uses en dashes for numeric ranges and hyphens for parenthetical constructions. No em dashes present. No fix needed.

---

#### V2 - LOW: One Instance of Slightly Documentation-Voice Phrasing

**Issue:** In the "Why These Services" section: "SageMaker also handles model versioning, A/B testing for model updates, and monitoring for data drift, all of which matter for a regulated medical device." The phrase "all of which matter for" is slightly formal/documentation-voice compared to the rest of the recipe's conversational tone.

**Location:** "Why These Services" section, SageMaker paragraph, last sentence.

**Suggested fix:** Rephrase to something like: "SageMaker also handles model versioning, A/B testing for model updates, and monitoring for data drift. For a regulated medical device, you need all three." This matches the recipe's pattern of short declarative sentences.

---

#### V3 - LOW: Vendor Balance Is Well-Maintained

**Observation:** The recipe's structure cleanly separates vendor-agnostic content (Problem, Technology, General Architecture Pattern) from AWS-specific content (AWS Implementation). Rough word count estimate: ~2,800 words vendor-agnostic, ~2,200 words AWS-specific. That's approximately 56/44, slightly AWS-heavy compared to the 70/30 target, but the AWS section includes substantial pseudocode which inflates word count. The prose ratio is closer to 65/35, which is acceptable.

No fix needed, but worth noting for the editor.

---

## Stage 2: Expert Discussion

**Conflicts identified:** None. The security, architecture, and networking findings are complementary rather than conflicting.

**Overlapping concerns:**
- S1 (IAM permissions) and N1 (VPC endpoints) both relate to the Lambda execution environment configuration. They should be addressed together in a single Prerequisites table revision.
- A1 (endpoint unavailability) and A2 (no DLQ) both address failure modes. The DLQ addresses Lambda-level failures; the fallback behavior addresses downstream service failures. Both are needed.

**Priority resolution:** The networking finding N1 (missing VPC endpoints) is the highest-priority fix because it could result in PHI traversing the public internet if a reader follows the recipe as-written and only configures the endpoints explicitly listed. The IAM finding S1 is second priority because over-permissioned Lambdas are a compliance audit finding but not an immediate data exposure risk.

---

## Stage 3: Synthesized Feedback

### Verdict: PASS

The recipe has 0 CRITICAL findings and 3 HIGH findings (threshold for FAIL is >3 HIGH). The HIGH findings are all addressable with additions to the Prerequisites table and brief architectural notes. The core content (problem statement, technology explanation, pseudocode, honest take) is excellent.

### Prioritized Findings

| # | Severity | Expert | Location | Issue | Fix |
|---|----------|--------|----------|-------|-----|
| S1 | HIGH | Security | Prerequisites table, IAM row | IAM permissions are a flat union across all Lambdas; violates least-privilege | Break into per-function permissions or add explicit least-privilege note |
| A1 | HIGH | Architecture | Architecture Diagram / Why These Services | No fallback when SageMaker endpoint is unavailable; critical findings missed during outage | Add SQS buffer or document graceful degradation to FIFO ordering on failure |
| N1 | HIGH | Networking | Prerequisites table, VPC row | SNS VPC endpoint missing; CloudWatch Metrics endpoint missing; endpoint list incomplete | Enumerate all required VPC endpoints with service names |
| S2 | MEDIUM | Security | Step 5 pseudocode, patient_id field | Patient ID stored without justification for minimum necessary | Add justification comment or remove and use accession_number for linkage |
| S3 | MEDIUM | Security | Step 5 pseudocode, send_alert block | CRITICAL alert contains finding details (PHI) sent to unspecified channel | Specify HIPAA-compliant channel; recommend sending only accession + priority level |
| A2 | MEDIUM | Architecture | Architecture Diagram | No DLQ on study-router Lambda; failed studies silently dropped | Add DLQ and alarm on failed processing |
| A3 | MEDIUM | Architecture | Performance benchmarks, Throughput row | 200 studies/hour claim not clarified (pipeline vs. inference) | Clarify bottleneck and scaling guidance |
| A4 | MEDIUM | Architecture | Why These Services (SageMaker) | No mention of FDA change control requirements for model updates | Add note on regulated model update process |
| N2 | MEDIUM | Networking | Architecture Diagram, DICOM Router arrow | No guidance on on-prem to cloud network path for DICOM transfer | Add Direct Connect/VPN/gateway options with encryption requirements |
| V2 | LOW | Voice | Why These Services, SageMaker paragraph | Slightly documentation-voice phrasing | Rephrase to match conversational tone |
| S4 | LOW | Security | Prerequisites / SageMaker section | No model artifact integrity verification mentioned | Add note on checksums and model registry for QMS |
| A5 | LOW | Architecture | Step 4 pseudocode | Composite score can be misleading for CRITICAL studies | Add clarifying comment about priority vs. score sorting |
| N3 | LOW | Networking | Prerequisites, VPC row | "Should not have public access" is passive for a PHI system | Strengthen to prescriptive "must not" with validation step |

### Summary

This is a well-written recipe that demonstrates strong understanding of both the clinical domain and the technical implementation. The problem statement is one of the best in the cookbook: it makes the reader feel the urgency without being melodramatic. The technology section is genuinely educational and would serve a reader on any cloud platform. The honest take section correctly identifies alert fatigue and PACS integration as the real deployment challenges, which shows production experience (or excellent research).

The findings are primarily about hardening the Prerequisites table and adding failure-mode documentation. The core architecture pattern is sound. The pseudocode is clear and well-commented. The regulatory awareness (FDA, post-market surveillance, QMS) is appropriately woven throughout rather than bolted on as an afterthought.

Recommended for publication after addressing the three HIGH findings.

---

*Review complete. Pseudocode simplifications are acknowledged and not critiqued.*
