# Expert Review: Recipe 9.6 - Diabetic Retinopathy Screening

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter09.06-diabetic-retinopathy-screening.md`

---

## Overall Assessment

This is an excellent recipe. The Problem section is genuinely compelling and well-motivated. The Technology section teaches fundus photography, the ICDR grading scale, and deep learning classification from first principles without vendor names. The clinical decision logic is thoughtful, with appropriate confidence gating and the critical DME detection pathway. The Honest Take section is one of the best in the book so far: the paradox about patients who most need screening being hardest to image is a real insight that demonstrates domain expertise.

The recipe handles the FDA regulatory dimension well, correctly distinguishing autonomous diagnosis (requires clearance) from physician-reviewed triage (different regulatory path). The architecture is sound for the stated scale.

However: there are IAM permission gaps that would leave a builder stuck, a missing VPC endpoint for Step Functions, a cost estimate that doesn't account for the always-on nature of GPU endpoints in low-volume deployments, and several TODO placeholders in the Additional Resources section that should not ship. No critical compliance issues found.

**Verdict: PASS**

Priority breakdown: 0 critical, 3 high, 4 medium, 3 low.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

The PHI baseline is strong: BAA requirement explicitly stated with rationale (retinal images are PHI), SSE-KMS on S3, KMS encryption for SageMaker model artifacts and inference data, DynamoDB encryption at rest, TLS for all API calls, CloudTrail for audit trail. The recipe correctly identifies that retinal images are PHI (they are biometric identifiers under HIPAA Safe Harbor). The "never use real patient images in dev without IRB approval and proper de-identification" warning is appropriate and specific. The audit trail design (storing model version, raw predictions, and clinical decision together) supports FDA post-market surveillance requirements.

#### Issue S1: IAM Permissions Missing Step Functions Execution Role (HIGH)

**Location:** Prerequisites table, IAM Permissions row

**The problem:** The IAM permissions listed are: `sagemaker:InvokeEndpoint`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `sns:Publish`, `states:StartExecution`. These appear to be the permissions for the Lambda execution role. But the architecture uses Step Functions to orchestrate Lambda functions. The Step Functions state machine itself needs an execution role with `lambda:InvokeFunction` on each Lambda ARN. This is a separate IAM role from the Lambda execution role.

A builder following this recipe will create the Lambda role, create the Step Functions state machine, and get `States.TaskFailed` on the first Lambda invocation because the state machine has no permission to call Lambda.

**Suggested fix:** Split the IAM Permissions row into two: (1) Lambda execution role: `sagemaker:InvokeEndpoint`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `sns:Publish`; (2) Step Functions execution role: `lambda:InvokeFunction` scoped to the specific Lambda function ARNs, plus `states:StartExecution` if the Lambda needs to start the workflow (which is the trigger pattern shown in the architecture diagram where S3 event triggers Step Functions, not Lambda).

Additionally, `states:StartExecution` is listed as a Lambda permission but the architecture diagram shows S3 Event triggering Step Functions directly. If S3 triggers Step Functions via EventBridge, the EventBridge service role needs `states:StartExecution`, not Lambda. Clarify the trigger mechanism.

#### Issue S2: DynamoDB Encryption Not Specified as Customer-Managed Key (MEDIUM)

**Location:** Prerequisites table, Encryption row

**The problem:** The encryption row states "DynamoDB: encryption at rest" without specifying the key type. AWS default DynamoDB encryption uses AWS-owned keys, which do not appear in CloudTrail and cannot be revoked. For a table storing clinical screening results (severity grades, referral decisions, patient IDs), many HIPAA compliance programs require customer-managed KMS keys for audit visibility and key lifecycle control.

The S3 encryption correctly specifies "SSE-KMS" and the SageMaker encryption specifies "KMS encryption." DynamoDB should be consistent.

**Suggested fix:** Change to "DynamoDB: encryption at rest with customer-managed KMS key (CMK)" to align with the S3 and SageMaker encryption specifications. Note that the AWS-managed key (`aws/dynamodb`) is acceptable as a minimum but a dedicated CMK provides CloudTrail key-usage logging.

#### Issue S3: No Mention of S3 Bucket Policy Restricting Access (LOW)

**Location:** Prerequisites / S3 configuration

**The problem:** The recipe mentions SSE-KMS encryption for S3 but does not mention bucket policies. Retinal images are sensitive biometric PHI. The S3 bucket storing them should have a bucket policy that denies unencrypted uploads (`aws:SecureTransport` condition), enforces KMS encryption on PutObject, and restricts access to specific IAM roles/principals. This is standard for PHI-containing buckets.

**Suggested fix:** Add a brief note in the Prerequisites or in the "Why These Services" S3 paragraph: "Apply a bucket policy enforcing SSE-KMS on all uploads and restricting access to the Lambda execution role and authorized administrative principals."

---

### Architecture Expert Review

#### What's Done Well

The pipeline decomposition (Quality Assessment, Classification, Clinical Decision, Storage/Action) is clean and maps well to the general architecture pattern described in the vendor-agnostic section. The confidence gating with HUMAN_REVIEW_REQUIRED as a distinct decision path is architecturally sound and clinically appropriate. The DynamoDB partition key (patient_id) with sort key (screening_date) supports the primary access pattern (patient screening history) efficiently. The Step Functions choice for workflow orchestration is well-motivated given the branching logic. The cost estimate is grounded in real instance pricing.

#### Issue A1: Cost Estimate Assumes Endpoint Is Always Running But Doesn't Address Low-Volume Scenarios (HIGH)

**Location:** Prerequisites table, Cost Estimate row; also "Expected Results" cost per screening

**The problem:** The recipe states: "SageMaker GPU endpoint (ml.g4dn.xlarge): ~$0.74/hour. At 100 images/day with 5-second inference: endpoint cost dominates at ~$530/month." This is correct math ($0.74 * 24 * 30 = ~$533/month). But the recipe doesn't address the fundamental cost problem: a GPU endpoint running 24/7 for 100 images/day means you're paying for 24 hours of GPU time to process ~8 minutes of actual inference (100 images * 5 seconds = 500 seconds).

For a small clinic or pilot program doing 20-50 screenings per day, the always-on endpoint cost is the dominant expense and may be prohibitive. The recipe mentions SageMaker Batch Transform for "end-of-day reads" in the "Why These Services" section but doesn't integrate this into the cost analysis or architecture.

More importantly, SageMaker now supports Serverless Inference endpoints and asynchronous inference, both of which would dramatically reduce costs for low-volume screening programs (scale to zero when idle). For a screening program where latency of 10-30 seconds is acceptable (the patient is still in the clinic), asynchronous inference with auto-scaling to zero is a much better cost profile.

**Suggested fix:** Add a cost comparison note: "For programs processing fewer than 50 images/day, consider SageMaker Asynchronous Inference or Serverless Inference endpoints, which scale to zero when idle. The tradeoff is higher per-inference latency (10-30 seconds vs. 2-5 seconds) but dramatically lower monthly cost for low-volume deployments. The always-on real-time endpoint becomes cost-effective above approximately 200 images/day." This also strengthens the recipe's applicability to the rural/underserved settings described in the Problem section.

#### Issue A2: No Dead Letter Queue or Error Handling on SNS Notifications (MEDIUM)

**Location:** Architecture diagram and Step 4 pseudocode

**The problem:** The clinical decision logic publishes to SNS topics for urgent referrals, routine referrals, and normal results. If an SNS publish fails (throttling, misconfigured subscription, endpoint down), the screening result is stored in DynamoDB but the notification is lost. For urgent referrals (proliferative DR, sight-threatening disease), a lost notification means a patient who needs immediate ophthalmology care doesn't get flagged.

The recipe doesn't mention DLQs on the SNS topics, retry logic for failed publishes, or a reconciliation mechanism to detect screenings where the result was stored but the notification was never delivered.

**Suggested fix:** Add a note in the Step Functions workflow description: "Configure a dead-letter queue (SQS) on each SNS topic. For the urgent-referrals topic specifically, add a CloudWatch alarm on the DLQ message count: any message landing in the urgent referral DLQ should trigger an immediate operational alert. Consider a daily reconciliation Lambda that queries DynamoDB for URGENT_REFERRAL decisions and verifies corresponding notification delivery."

#### Issue A3: Quality Check Lambda May Exceed Memory/Timeout for Large Images (MEDIUM)

**Location:** "Why These Services" Lambda section and Step 1 pseudocode

**The problem:** The recipe states: "For the quality assessment step, a lightweight model can run on Lambda with up to 10GB ephemeral storage." Fundus images are 2-10MB, and the quality assessment involves computing Laplacian variance (sharpness), histogram analysis (illumination), and potentially a lightweight CNN for artifact detection. If the quality model is a CNN (even a small one like MobileNet), loading the model weights into Lambda memory on cold start could take several seconds, and inference on a high-resolution fundus image (typically 2048x1536 or larger) requires significant memory.

The recipe doesn't specify Lambda memory configuration or timeout. A default 128MB Lambda will fail immediately. Even at 1GB, a CNN-based quality check on a full-resolution fundus image may be tight.

**Suggested fix:** Add a note: "Configure the quality assessment Lambda with at least 2048MB memory and 30-second timeout. If using a CNN-based quality model, consider provisioned concurrency to avoid cold-start latency on the first screening of the day. Alternatively, run the quality check on the same SageMaker endpoint as a multi-model endpoint (quality model + DR classification model) to avoid Lambda memory constraints entirely."

---

### Networking Expert Review

#### What's Done Well

The VPC configuration is well-specified: "SageMaker endpoint in VPC, Lambda in VPC with VPC endpoints for S3, DynamoDB, SageMaker Runtime, SNS, and CloudWatch Logs." This covers the major services that handle PHI. The recipe correctly identifies that the SageMaker endpoint should be in a VPC (preventing internet-routable access to the inference endpoint).

#### Issue N1: Missing VPC Endpoint for Step Functions (HIGH)

**Location:** Prerequisites table, VPC row

**The problem:** The VPC row lists VPC endpoints for: S3, DynamoDB, SageMaker Runtime, SNS, and CloudWatch Logs. The architecture uses Step Functions as the orchestration layer, and Lambda (running in VPC) needs to interact with Step Functions (at minimum, Step Functions calls Lambda, and the S3 event trigger starts the state machine). If Lambda is in a VPC and needs to report task success/failure back to Step Functions (which is the case for callback patterns), it needs a VPC endpoint for Step Functions (`com.amazonaws.{region}.states`).

More importantly, if the S3 event triggers Step Functions via EventBridge (the modern pattern), EventBridge also needs a VPC endpoint or the trigger must be configured outside the VPC path. The recipe should clarify the trigger mechanism and ensure all service-to-service communication paths are covered.

**Suggested fix:** Add `Step Functions (com.amazonaws.{region}.states)` to the VPC endpoints list. If using EventBridge for the S3-to-Step Functions trigger, note that EventBridge rules execute in the AWS service plane and don't require a VPC endpoint for the trigger itself, but Lambda callbacks to Step Functions do require the endpoint.

#### Issue N2: No Mention of NAT Gateway or Internet Access Requirements (LOW)

**Location:** Prerequisites table, VPC row

**The problem:** The recipe places Lambda in a VPC with VPC endpoints for AWS services. This is correct for PHI isolation. However, if the screening system needs to send notifications to external systems (e.g., webhook to an EHR system, email via SES, or SMS via SNS to a provider's phone), the Lambda functions in a private subnet would need either a NAT Gateway or additional VPC endpoints.

The recipe mentions "webhook to EHR" as a notification channel but doesn't address how a VPC-isolated Lambda reaches an external EHR endpoint.

**Suggested fix:** Add a brief note: "If EHR integration requires outbound HTTPS calls to external endpoints (HL7 FHIR server, webhook), configure a NAT Gateway in the VPC or use a dedicated integration Lambda in a subnet with internet access. Keep the PHI-processing Lambdas in private subnets with no internet route."

---

### Voice Reviewer

#### What's Done Well

The voice is strong throughout. The Problem section is passionate and specific ("The reasons are depressingly predictable"). The Technology section teaches from first principles without vendor names (no AWS services mentioned until "The AWS Implementation"). The Honest Take is genuinely insightful, especially the closing paradox about patients who most need screening being hardest to image. The 70/30 vendor balance is well-maintained: the first ~3000 words are entirely vendor-agnostic.

Parenthetical asides are used effectively: "(those annoying drops that blur your vision for hours)", "(ok, this is a gross oversimplification, but stay with me)" energy without being forced.

#### Issue V1: TODO Placeholders in Additional Resources (MEDIUM)

**Location:** Additional Resources section, "Clinical and Regulatory References" and "Public Datasets"

**The problem:** The recipe contains six TODO items:
- "TODO: Verify current FDA guidance document URL for AI/ML-based Software as a Medical Device (SaMD)"
- "TODO: Verify URL for IDx-DR (Digital Diagnostics) FDA De Novo clearance summary"
- "TODO: Verify URL for AAO Diabetic Retinopathy Preferred Practice Pattern"
- "TODO: Verify current Kaggle EyePACS dataset URL"
- "TODO: Verify Messidor-2 dataset access URL"
- "TODO: Verify APTOS 2019 Blindness Detection challenge URL"

These are appropriate placeholders during drafting (the RECIPE-GUIDE.md says "Only real, verified URLs"), but they cannot ship. The recipe is otherwise complete and polished; these TODOs are the only unfinished elements.

**Suggested fix:** Verify and fill in all six URLs before publication. If a URL cannot be verified (e.g., dataset has moved or been taken down), remove the entry or replace with a description of how to find the resource.

#### Issue V2: One Instance of Documentation-Voice Creep (LOW)

**Location:** Ingredients table header description for Amazon SageMaker

**The problem:** "Hosts the DR classification model on GPU endpoint; provides model versioning and A/B testing" is slightly documentation-voice (feature listing). Compare to the "Why These Services" paragraph for SageMaker, which is conversational and well-motivated. The Ingredients table is inherently terse, so this is minor, but the semicolon-separated feature list reads like a product page.

**Suggested fix:** Minor. Could rephrase to "Runs the DR model on GPU; handles versioning when you retrain" but this is cosmetic and the table format constrains voice. No action required.

---

## Stage 2: Expert Discussion

### Conflicts and Overlaps

**IAM/Architecture overlap (S1 + A2):** The IAM permissions gap (S1) and the missing DLQ concern (A2) are related. The Step Functions execution role issue means the entire workflow won't run as-is. The DLQ issue means that even once it runs, notification failures are silent. Together, these represent the two biggest "builder will get stuck" moments in the recipe. Priority: fix S1 first (it's a blocker), then A2 (it's a reliability gap).

**Networking/Architecture overlap (N1 + A3):** The missing Step Functions VPC endpoint (N1) compounds with the Lambda configuration gap (A3). A Lambda in a VPC without the Step Functions endpoint cannot report task completion back to Step Functions, causing the workflow to hang. These should be addressed together.

**Cost/Architecture alignment (A1):** The cost issue is architecturally significant because the recipe's Problem section emphasizes rural and underserved settings where cost sensitivity is highest. The always-on GPU endpoint at $530/month may be prohibitive for exactly the deployment scenarios the recipe motivates. This is a coherence issue between the Problem framing and the Implementation.

### Priority Resolution

The three HIGH findings are all "builder will get stuck or make a bad decision" issues rather than compliance violations. None rise to CRITICAL because:
- S1 (IAM): Builder will hit an error and can debug it, but it's a frustrating gap in a recipe that should be copy-paste ready
- A1 (Cost): Doesn't affect correctness but could lead to a failed pilot due to budget
- N1 (VPC endpoint): Builder will hit a timeout and can debug it, but it's a gap in the networking prerequisites

No CRITICAL findings. The recipe is compliant, clinically sound, and architecturally reasonable. The issues are completeness gaps, not fundamental flaws.

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

The recipe is well-written, clinically accurate, architecturally sound, and appropriately handles the FDA regulatory dimension. The vendor-agnostic Technology section is one of the strongest in the book. The three HIGH findings are completeness gaps that would cause builder friction but do not represent compliance violations or fundamental architectural errors.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Prerequisites, IAM Permissions | Step Functions execution role missing. Builder will get `States.TaskFailed` on first Lambda invocation. Also, `states:StartExecution` is listed as Lambda permission but the trigger mechanism (S3 event to Step Functions) is unclear. | Split IAM into Lambda role and Step Functions role. Clarify trigger: S3 Event → EventBridge → Step Functions (EventBridge needs `states:StartExecution`). |
| 2 | HIGH | Architecture | Prerequisites, Cost Estimate | Always-on GPU endpoint at $530/month is cost-prohibitive for low-volume/rural deployments that the Problem section motivates. No mention of serverless or async inference alternatives. | Add cost comparison noting SageMaker Async/Serverless Inference for <50 images/day. Note the always-on endpoint becomes cost-effective above ~200 images/day. |
| 3 | HIGH | Networking | Prerequisites, VPC row | Missing VPC endpoint for Step Functions (`com.amazonaws.{region}.states`). Lambda in VPC cannot report task completion to Step Functions without it, causing workflow hangs. | Add Step Functions to the VPC endpoints list. Clarify that EventBridge triggers execute in the service plane and don't require a VPC endpoint for the trigger path. |
| 4 | MEDIUM | Security | Prerequisites, Encryption row | DynamoDB encryption not specified as customer-managed KMS key. Inconsistent with S3 (SSE-KMS) and SageMaker (KMS) specifications. | Change to "DynamoDB: encryption at rest with customer-managed KMS key" for consistency and CloudTrail audit visibility. |
| 5 | MEDIUM | Architecture | Architecture diagram, Step 4 | No DLQ or error handling on SNS notifications. Failed urgent referral notification means sight-threatening disease goes unflagged. | Add DLQ (SQS) on SNS topics. CloudWatch alarm on urgent-referral DLQ. Daily reconciliation for undelivered notifications. |
| 6 | MEDIUM | Architecture | Step 1 pseudocode, Lambda config | No Lambda memory/timeout specification for quality check. Default 128MB will fail. CNN-based quality model on full-resolution fundus image needs 2048MB+. | Specify 2048MB memory, 30-second timeout. Mention provisioned concurrency for cold starts or multi-model endpoint alternative. |
| 7 | MEDIUM | Voice | Additional Resources | Six TODO placeholders for URLs that cannot ship. Recipe is otherwise publication-ready. | Verify and fill all six URLs. Remove entries where URLs cannot be confirmed. |
| 8 | LOW | Security | S3 configuration | No mention of bucket policy enforcing encryption and restricting access to authorized principals. | Add brief note about bucket policy with `aws:SecureTransport` condition and principal restrictions. |
| 9 | LOW | Networking | VPC configuration | No mention of NAT Gateway for outbound EHR integration calls from VPC-isolated Lambda. | Note that external EHR webhooks require NAT Gateway or dedicated integration subnet. |
| 10 | LOW | Voice | Ingredients table, SageMaker row | Minor documentation-voice creep in feature listing. | Cosmetic. No action required given table format constraints. |

---

### Summary

Strong recipe with excellent clinical grounding and voice. The three HIGH findings are all "builder will get stuck" gaps in the Prerequisites section (IAM roles, cost guidance, VPC endpoints) rather than fundamental design flaws. Fix the Prerequisites table and this recipe is ready for publication (pending URL verification for the TODO items).
