# Expert Review: Recipe 9.4 - Dermatology Lesion Triage

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter09.04-dermatology-lesion-triage.md`

---

## Overall Assessment

This is a strong recipe. The problem statement is compelling and grounded in real clinical data (30-day wait times, PCP accuracy ranges, the over-refer/under-refer dilemma). The technology section is excellent: it teaches CNNs for dermatology, the dermoscopic vs. clinical image distinction, transfer learning, and the skin tone bias problem from first principles without any vendor names. The skin tone bias discussion is particularly well-handled, treating it as a non-negotiable engineering concern rather than a footnote. The triage-vs-diagnosis regulatory framing is clear and appropriately cautious.

The architecture is sound for the stated scale. The honest take delivers genuine operational wisdom (threshold tuning as a political process, photo quality as the real enemy). The recipe correctly positions itself as a prioritization tool, not a diagnostic system, which is both clinically appropriate and regulatory-savvy.

Priority breakdown: 0 CRITICAL findings, 2 HIGH findings, 5 MEDIUM findings, 3 LOW findings.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

BAA requirement is explicitly stated. S3 SSE-KMS encryption specified. DynamoDB encryption at rest mentioned. TLS in transit for SageMaker endpoint specified. CloudTrail audit logging required. VPC deployment recommended for production. The "Never use real patient photos in development" guidance is present in the Prerequisites table. KMS is listed as a dedicated ingredient for key management. The recipe correctly identifies lesion photographs as identifiable medical images (PHI).

### Issue SEC-1: IAM Permissions Not Resource-Scoped (MEDIUM)

**Section:** Prerequisites table, "IAM Permissions" row

**The problem:** The recipe lists `sagemaker:InvokeEndpoint`, `s3:PutObject`, `s3:GetObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `sns:Publish` without resource ARN constraints. In a HIPAA environment, these must be scoped to specific resources. `s3:GetObject` on `*` allows the Lambda to read any object in any bucket in the account. `sagemaker:InvokeEndpoint` without a resource constraint allows invoking any endpoint.

**Suggested fix:** Show resource-scoped examples: "`s3:PutObject/GetObject` on `arn:aws:s3:::lesion-images/*`, `sagemaker:InvokeEndpoint` on `arn:aws:sagemaker:*:*:endpoint/lesion-classifier-*`, `dynamodb:PutItem/GetItem` on the specific `triage-cases` table ARN, `sns:Publish` on the specific `urgent-derm-triage` topic ARN."

### Issue SEC-2: No EXIF Metadata Stripping Mentioned (HIGH)

**Section:** Code Step 2 (preprocess_image), The Technology section

**The problem:** Patient-submitted smartphone photos contain EXIF metadata including GPS coordinates, device serial numbers, and potentially the photographer's name. The recipe preprocesses images (resize, normalize) but never mentions stripping EXIF metadata before storage. The original image is stored in S3 (`Store Original` step in the architecture diagram) with all metadata intact.

For a dermatology triage system where patients submit photos from home, GPS coordinates directly reveal the patient's home address. If images are later used for model retraining, research, or quality review, EXIF data travels with them unless explicitly stripped. This is PHI leakage beyond what's necessary for the clinical purpose.

**Suggested fix:** Add a step between image upload and S3 storage: "Strip EXIF metadata from submitted photographs before storage. GPS coordinates in patient-submitted photos reveal home addresses. Retain only clinically relevant metadata (timestamp, image dimensions) and discard location, device identifiers, and photographer information. If EXIF data is needed for audit purposes, store it in a separate, access-controlled record."

### Issue SEC-3: SNS Notification Contains Patient ID in Plaintext (MEDIUM)

**Section:** Code Step 5 (store_and_notify)

**The problem:** The SNS notification message includes `Patient {patient_id}` in plaintext. SNS messages may be delivered via email, SMS, or HTTP endpoints. If the SNS topic delivers to email (common for on-call notifications), the patient identifier is transmitted in an unencrypted email. This is a PHI exposure risk depending on the notification delivery mechanism.

**Suggested fix:** Either: (a) Remove patient_id from the SNS message and include only the case_id (the dermatologist can look up patient details in the secure system), or (b) Add a note: "If SNS delivers to email or SMS, ensure the notification contains only the case_id reference, not patient identifiers. Use the secure review queue for PHI access."

### Issue SEC-4: No Input Validation on Image Upload (LOW)

**Section:** Code Step 1 (validate_image_quality)

**The problem:** The quality validation checks resolution, blur, and brightness, but doesn't validate the file type or scan for malicious content. A user could upload a crafted file with a .jpg extension that exploits image parsing vulnerabilities. While this is a general web security concern (not dermatology-specific), the recipe's API Gateway endpoint accepts arbitrary uploads.

**Suggested fix:** Brief note: "Validate file type (magic bytes, not just extension) and enforce maximum file size at the API Gateway level before processing. Consider running uploaded files through an antivirus scan for defense in depth."

---

## Architecture Expert Review

### What's Done Well

The pipeline architecture (capture -> quality check -> preprocess -> classify -> triage -> queue) is clean and appropriate. The separation of quality validation from inference is correct (reject bad images before spending GPU time). The confidence calibration discussion is excellent and often overlooked. The triage threshold design as configuration rather than code is the right pattern. The cost estimate ($0.08-0.15 per image on ml.g4dn.xlarge) is reasonable. The performance benchmarks are realistic and honest (sensitivity drops for clinical photos vs. dermoscopic images are explicitly stated). The "Where it struggles" section is genuinely useful.

### Issue ARCH-1: No Dead Letter Queue or Error Handling in the Pipeline (HIGH)

**Section:** Architecture Diagram, Code walkthrough

**The problem:** The architecture shows a linear flow: API Gateway -> Lambda -> SageMaker -> DynamoDB. There's no mention of what happens when the SageMaker endpoint times out, returns an error, or is temporarily unavailable. There's no DLQ for failed triage attempts. In a clinical system, a lost triage request means a potentially urgent lesion never gets prioritized.

The Lambda orchestrator calls SageMaker synchronously. If the endpoint is scaling up (cold start on a GPU instance can take 2-5 minutes), the Lambda will timeout. The patient gets an error. The image is already in S3 but no triage record exists in DynamoDB. The case is lost.

**Suggested fix:** Add error handling guidance: "Configure a DLQ (SQS) for failed Lambda invocations. If the SageMaker endpoint is unavailable or times out, write the case to DynamoDB with status `PENDING_INFERENCE` and reprocess via a scheduled retry. For a clinical triage system, no submission should be silently lost. Alert on DLQ depth > 0."

### Issue ARCH-2: Single SageMaker Endpoint Is a Single Point of Failure (MEDIUM)

**Section:** Why These Services (SageMaker), Prerequisites

**The problem:** The recipe describes a single SageMaker real-time endpoint. If that endpoint fails (deployment error, instance failure, model corruption), the entire triage system is down. For a clinical system where urgent cases need prioritization, downtime means patients with suspicious lesions wait in the standard queue.

**Suggested fix:** Add a note: "For production, deploy the model across multiple availability zones using SageMaker's multi-AZ endpoint configuration. Consider a fallback path: if inference fails, route the case to the dermatology queue with a `MANUAL_REVIEW` flag rather than returning an error to the clinician."

### Issue ARCH-3: No Model Monitoring or Drift Detection Details (MEDIUM)

**Section:** Why These Services (CloudWatch), Expected Results

**The problem:** The recipe mentions CloudWatch for "confidence score distributions, triage category distributions, and alert on drift" but doesn't explain what drift looks like or how to detect it. For a dermatology model, drift could mean: (a) the patient population changed (more dark-skinned patients, where the model performs worse), (b) the image capture method changed (new phone cameras with different color profiles), or (c) the model is degrading. Without specific metrics and thresholds, the monitoring guidance is too vague to implement.

**Suggested fix:** Add specifics: "Monitor weekly triage category distribution. If the urgent rate shifts by more than 2 standard deviations from the 30-day rolling average, investigate. Track mean confidence scores per category; declining confidence suggests the model is seeing inputs unlike its training data. Compare model predictions against dermatologist dispositions (when available) to compute rolling accuracy metrics."

### Issue ARCH-4: Asynchronous Inference Not Discussed for Batch Scenarios (LOW)

**Section:** Code Step 3 (classify_lesion)

**The problem:** The recipe uses real-time inference exclusively. For a teledermatology workflow where patients submit photos through a portal (mentioned in Variations), the response doesn't need to be synchronous. Asynchronous inference (SageMaker Async Inference) would be cheaper and handle burst loads better. The recipe doesn't mention this option.

**Suggested fix:** Brief note in Variations or in the "Why These Services" section: "For store-and-forward teledermatology workflows where immediate response isn't required, consider SageMaker Async Inference. It handles burst loads without maintaining always-on GPU instances and costs significantly less for intermittent workloads."

### Issue ARCH-5: No Discussion of Model Explainability (MEDIUM)

**Section:** The Technology section, Code Step 4 (determine_triage)

**The problem:** The recipe outputs a triage category and confidence score, but doesn't discuss explainability. When a dermatologist reviews a case flagged as "urgent," they'll want to know why. What features did the model focus on? Was it asymmetry? Color variation? Border irregularity? Without explainability (e.g., Grad-CAM heatmaps showing which regions of the image drove the prediction), the dermatologist has no context beyond "the AI said urgent with 72% confidence."

For clinical adoption, explainability is often the difference between "useful tool" and "black box I ignore." This is especially important for the triage use case where the dermatologist is making prioritization decisions based on the AI's output.

**Suggested fix:** Add a paragraph in the Technology section or as a Variation: "Consider generating saliency maps (Grad-CAM or similar) alongside predictions. A heatmap showing which regions of the lesion drove the model's assessment gives the reviewing dermatologist actionable context. SageMaker Clarify supports model explainability for image classification. Store the heatmap alongside the original image in the review queue."

---

## Networking Expert Review

### What's Done Well

The recipe explicitly states "Production: Lambda and SageMaker endpoint in VPC with VPC endpoints for S3, DynamoDB, SageMaker Runtime, and CloudWatch Logs." This is more complete than many recipes. TLS in transit is specified for the SageMaker endpoint. The architecture keeps PHI within the AWS account boundary.

### Issue NET-1: Missing KMS VPC Endpoint (MEDIUM)

**Section:** Prerequisites table, "VPC" row

**The problem:** The VPC endpoint list includes S3, DynamoDB, SageMaker Runtime, and CloudWatch Logs, but omits KMS. The recipe specifies S3 SSE-KMS encryption. If the Lambda is in a VPC with no NAT gateway (as recommended for PHI workloads to prevent data egress), S3 operations using SSE-KMS will fail because the Lambda cannot reach the KMS service endpoint.

**Suggested fix:** Add `kms` to the VPC endpoint list: "VPC endpoints for S3 (gateway), DynamoDB (gateway), SageMaker Runtime (interface), CloudWatch Logs (interface), and KMS (interface). The KMS endpoint is required for S3 SSE-KMS operations in a VPC without NAT gateway."

### Issue NET-2: No Egress Controls Discussed (LOW)

**Section:** Prerequisites, Architecture

**The problem:** The recipe doesn't discuss egress controls. In a HIPAA environment with PHI (identifiable medical photographs), network egress should be restricted. The VPC should have no NAT gateway (or a tightly controlled one) to prevent PHI from leaving the account via unexpected paths. The recipe implies this by recommending VPC endpoints, but doesn't state the principle explicitly.

**Suggested fix:** Brief note: "For PHI workloads, restrict VPC egress. Use VPC endpoints for all AWS service communication and avoid NAT gateways unless required for specific integrations. This prevents accidental PHI egress through misconfigured Lambda functions or compromised dependencies."

### Issue NET-3: API Gateway Endpoint Type Not Specified (LOW)

**Section:** Why These Services (API Gateway), Architecture Diagram

**The problem:** The recipe mentions API Gateway but doesn't specify whether it should be a Regional, Edge-optimized, or Private endpoint. For a clinical system handling PHI, a Private API Gateway endpoint (accessible only from within the VPC) would be appropriate if the clinician portal is also in the VPC or connected via VPN/Direct Connect. A public endpoint requires additional controls (WAF, IP whitelisting, mutual TLS).

**Suggested fix:** Brief note: "For internal clinical portals, consider a Private API Gateway endpoint accessible only from the VPC. For patient-facing apps, use a Regional endpoint with AWS WAF for rate limiting and IP-based access controls."

---

## Voice Reviewer

### What's Done Well

The voice is excellent throughout. The opening paragraph ("There are roughly 3.5 billion people on Earth with access to a smartphone camera but not to a dermatologist") is a strong hook that makes the reader feel the scale of the problem. The PCP accuracy discussion is respectful ("That's not a criticism of PCPs. It's a recognition that dermatology is a visual specialty that takes years of focused training."). The parenthetical asides are well-deployed: "(ok, this is a gross oversimplification, but stay with me)" energy without being that explicit. The skin tone discussion is handled with appropriate gravity without being preachy.

The honest take is genuinely insightful. "The model is the easy part" and "Threshold tuning is a political process, not a technical one" are the kind of observations that come from real deployment experience. The writing builds momentum through accumulation of short-to-medium sentences.

The 70/30 vendor balance is well-maintained. The entire Technology section (approximately 60% of the recipe) is completely vendor-agnostic. AWS appears only in the implementation section.

### Issue VOICE-1: Em Dash Check (PASS)

Scanned the full recipe. Zero em dashes found. The recipe uses colons, semicolons, periods, and parentheses correctly as alternatives.

### Issue VOICE-2: Vendor Balance Check (PASS)

The Technology section covers CNNs, dermoscopic vs. clinical images, transfer learning, the skin tone problem, and triage vs. diagnosis without a single AWS service name. The General Architecture Pattern uses generic component names. AWS services appear only starting at "The AWS Implementation." The ratio is approximately 65/35 (slightly more AWS than the 70/30 target, but within acceptable range given the detailed code walkthrough).

### Issue VOICE-3: One Instance of Slightly Clinical Tone (LOW)

**Section:** The Technology, "Triage vs. Diagnosis" subsection

**The text:** "This triggers FDA regulatory requirements (specifically, the De Novo or 510(k) pathway for Software as a Medical Device, SaMD)."

This sentence reads slightly more like a regulatory document than an engineer explaining something. The parenthetical with three acronyms/terms in a row (De Novo, 510(k), SaMD) is dense.

**Suggested fix:** Minor. Could be: "This triggers FDA regulatory requirements. You'd be looking at the De Novo or 510(k) pathway, which is the world of Software as a Medical Device (SaMD)." Breaking it into two sentences reduces the density.

---

## Stage 2: Expert Discussion

### Conflicts and Overlaps

**SEC-2 (EXIF metadata) is the most impactful security finding.** Patient-submitted photos from home will contain GPS coordinates revealing home addresses. This is the same pattern identified in Recipe 9.3's review, and it's equally critical here. The dermatology triage use case explicitly targets patient-submitted photos, making this even more likely to occur than in a clinical setting where institutional devices might have GPS disabled.

**ARCH-1 (no DLQ/error handling) is the most impactful architecture finding.** A lost triage request in a clinical system is unacceptable. The linear synchronous architecture means any failure in the SageMaker call results in a lost case. Combined with GPU cold starts (2-5 minutes for a g4dn instance scaling from zero), this is a realistic failure mode that would occur in production.

**ARCH-5 (explainability) and clinical adoption interact.** The recipe correctly positions itself as a triage tool where the dermatologist makes the final call. But without explainability, the dermatologist has no reason to trust the prioritization. This affects whether the system achieves its stated goal (getting urgent cases seen first). If dermatologists ignore the AI's prioritization because they can't understand it, the system provides no value.

**NET-1 (KMS endpoint) and SEC-1 (IAM scoping) are independent but both affect whether the system works in a properly secured environment.** NET-1 is more urgent because it causes hard failures (S3 operations fail entirely without KMS endpoint in a no-NAT VPC).

### Priority Resolution

1. SEC-2 (EXIF metadata) and ARCH-1 (no error handling/DLQ) are HIGH because they represent real compliance gaps and operational failures respectively.
2. SEC-1 (IAM scoping), SEC-3 (SNS PHI), ARCH-2 (single endpoint), ARCH-3 (drift detection), ARCH-5 (explainability), and NET-1 (KMS endpoint) are MEDIUM because they're gaps a knowledgeable builder would catch but less experienced teams might miss.
3. SEC-4 (input validation), ARCH-4 (async inference), NET-2 (egress), NET-3 (API Gateway type), and VOICE-3 (clinical tone) are LOW polish items.

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

The recipe is clinically sound, architecturally appropriate, well-written, and provides actionable guidance for building a dermatology lesion triage system. The skin tone bias discussion is handled responsibly and thoroughly. The triage-vs-diagnosis framing is correct and appropriately cautious about regulatory implications. The two HIGH findings (EXIF metadata PHI leakage and missing error handling/DLQ for lost triage requests) are significant but correctable without restructuring the recipe. No CRITICAL findings. The recipe correctly identifies the key challenges (photo quality, skin tone bias, threshold politics, outcome tracking) and provides genuine operational wisdom.

---

### Prioritized Findings

| # | Severity | Expert | Section | Finding | Fix |
|---|----------|--------|---------|---------|-----|
| 1 | HIGH | Security | Code Step 2, Architecture Diagram | Patient-submitted smartphone photos contain EXIF GPS coordinates revealing home addresses. No mention of metadata stripping before S3 storage. | Add EXIF stripping step between upload and storage. Strip GPS, device IDs, photographer info. Retain only timestamp and dimensions. |
| 2 | HIGH | Architecture | Architecture Diagram, Code walkthrough | No DLQ or error handling for failed SageMaker calls. GPU cold starts (2-5 min) cause Lambda timeouts. Lost triage requests mean potentially urgent lesions never get prioritized. | Add SQS DLQ for failed invocations. Write `PENDING_INFERENCE` status to DynamoDB on failure. Implement scheduled retry. Alert on DLQ depth > 0. |
| 3 | MEDIUM | Security | Prerequisites (IAM row) | IAM permissions listed without resource ARN scoping. Not least-privilege for HIPAA. | Show resource-scoped ARN examples for each permission (specific bucket, endpoint ARN, table ARN, topic ARN). |
| 4 | MEDIUM | Security | Code Step 5 (store_and_notify) | SNS notification contains patient_id in plaintext. If delivered via email, this is PHI exposure. | Remove patient_id from SNS message; include only case_id. Dermatologist accesses patient details through secure review queue. |
| 5 | MEDIUM | Architecture | Why These Services (SageMaker) | Single SageMaker endpoint is a single point of failure. Endpoint failure means entire triage system is down. | Add note about multi-AZ endpoint configuration and fallback path (route to manual review queue on inference failure). |
| 6 | MEDIUM | Architecture | Why These Services (CloudWatch) | Model monitoring guidance is too vague. No specific metrics, thresholds, or drift detection approach. | Add specifics: monitor weekly category distribution (alert on 2-sigma shift), track mean confidence scores, compare predictions against dermatologist dispositions. |
| 7 | MEDIUM | Architecture | The Technology, Code Step 4 | No discussion of model explainability (Grad-CAM, saliency maps). Dermatologists need to understand why the AI flagged a case to trust the prioritization. | Add paragraph about generating saliency maps alongside predictions. Reference SageMaker Clarify. Store heatmaps in review queue. |
| 8 | MEDIUM | Networking | Prerequisites (VPC row) | Missing KMS VPC endpoint. S3 SSE-KMS operations fail in a VPC without NAT gateway if KMS endpoint is absent. | Add `kms` (interface) to the VPC endpoint list with explanation of why it's required. |
| 9 | LOW | Security | Code Step 1 (validate_image_quality) | No file type validation or malicious content scanning on uploaded images. | Brief note about validating magic bytes and enforcing max file size at API Gateway level. |
| 10 | LOW | Architecture | Code Step 3 (classify_lesion) | Async inference not mentioned for store-and-forward teledermatology workflows where immediate response isn't needed. | Brief note in Variations about SageMaker Async Inference for non-real-time workflows. |
| 11 | LOW | Voice | The Technology, "Triage vs. Diagnosis" | Dense parenthetical with three acronyms (De Novo, 510(k), SaMD) reads slightly clinical. | Split into two sentences to reduce density. |
| 12 | LOW | Networking | Prerequisites, Architecture | No explicit egress control guidance for PHI workloads. | Brief note about restricting VPC egress and avoiding NAT gateways for PHI workloads. |

---

### Summary

An excellent recipe that teaches dermatology lesion triage from first principles, handles the skin tone bias discussion responsibly, and provides genuine operational wisdom about the non-technical challenges (threshold politics, clinician trust, outcome tracking). The two HIGH findings are: (1) EXIF metadata in patient-submitted photos leaking home addresses, and (2) missing error handling that could cause lost triage requests for potentially urgent lesions. Both are correctable without restructuring. The recipe's strongest assets are its honest treatment of limitations, the clear triage-vs-diagnosis regulatory framing, and the insight that "the model is the easy part." After addressing findings 1-8, this recipe is ready for publication.
