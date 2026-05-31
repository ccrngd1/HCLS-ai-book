# Expert Review: Recipe 9.3 - Wound Photography Measurement

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter09.03-wound-photography-measurement.md`

---

## Overall Assessment

This is an excellent recipe. The problem statement is vivid and clinically grounded (the inter-rater variability framing is perfect for motivating the solution). The technology section teaches wound segmentation, scale calibration, and longitudinal tracking from first principles without vendor lock-in. The honest take delivers genuine operational wisdom, particularly the insight that clinician compliance with the capture protocol is the biggest risk, not the algorithm. The architecture is appropriate for the stated scale and use case.

The recipe has no critical compliance gaps. The security posture is mostly sound (BAA, encryption, CloudTrail all mentioned), but there are gaps in IAM scoping and a missing consideration around image metadata containing PHI. The architecture is well-suited to the workload but has a subtle DynamoDB key design issue that would cause problems at scale. The voice is consistently strong throughout.

Priority breakdown: 0 CRITICAL findings, 2 HIGH findings, 4 MEDIUM findings, 3 LOW findings.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

BAA requirement is explicitly stated. S3 SSE-KMS encryption is specified. CloudTrail is required. The recipe correctly identifies wound photographs as PHI. The "Never use real patient images in development" guidance via the sample data row is present. DynamoDB encryption at rest is mentioned. TLS 1.2+ in transit is specified. The VPC requirement for SageMaker is stated.

### Issue SEC-1: IAM Permissions Not Resource-Scoped (MEDIUM)

**Section:** Prerequisites table, "IAM Permissions" row

**The problem:** The recipe lists `s3:PutObject, s3:GetObject, sagemaker:InvokeEndpoint, dynamodb:PutItem, dynamodb:Query, logs:CreateLogGroup` without resource ARN constraints. In a HIPAA environment, these must be scoped to specific resources. `s3:GetObject` on `*` allows the Lambda to read any object in any bucket in the account. `sagemaker:InvokeEndpoint` without a resource constraint allows invoking any endpoint.

**Suggested fix:** Change to resource-scoped examples: "`s3:PutObject/GetObject` on `arn:aws:s3:::wound-images/*` and `arn:aws:s3:::wound-masks/*`, `sagemaker:InvokeEndpoint` on `arn:aws:sagemaker:*:*:endpoint/wound-segmentation-*`, `dynamodb:PutItem/Query` on the specific `wound-measurements` table ARN."

### Issue SEC-2: EXIF/Image Metadata May Contain PHI or Location Data (HIGH)

**Section:** Code Step 1 (validate_wound_image), The Technology section

**The problem:** Smartphone photographs contain EXIF metadata including GPS coordinates (patient's home address for home health visits), device serial numbers, and potentially the photographer's name. The recipe stores the original image in S3 but never mentions stripping or handling EXIF metadata. For home health wound photography, GPS coordinates in the image metadata directly reveal the patient's home address. This is PHI leakage beyond what's necessary for the clinical purpose.

Additionally, if images are ever shared for research, model training, or quality review, the EXIF data travels with them unless explicitly stripped.

**Suggested fix:** Add a step between image upload and storage (or within the validation step): "Strip EXIF metadata from wound photographs before storage, or store EXIF data separately with appropriate access controls. GPS coordinates in smartphone photos taken during home health visits reveal the patient's home address. Retain only clinically relevant metadata (timestamp, image dimensions) and discard location, device identifiers, and photographer information. If EXIF data is needed for audit purposes, store it in a separate, access-controlled record rather than embedded in the image file."

### Issue SEC-3: No Mention of Access Controls on Segmentation Masks (LOW)

**Section:** Code Step 3, Expected Results

**The problem:** Segmentation masks are stored in S3 (`wound-masks/` path in the expected results). These masks, while not photographs, are derived from PHI and when overlaid on the original image reveal the wound. They should have the same access controls as the original images. The recipe doesn't explicitly state this, though it's implied by the S3 SSE-KMS configuration applying to the bucket.

**Suggested fix:** Brief note: "Segmentation masks are PHI-derived artifacts. Apply the same encryption, access controls, and retention policies as the original wound images."

### Issue SEC-4: DynamoDB Record Contains Patient ID in Plaintext (LOW)

**Section:** Code Step 5 (store_measurement)

**The problem:** The DynamoDB record stores `patient_id` as the partition key in plaintext. While DynamoDB encryption at rest protects against physical media theft, any IAM principal with `dynamodb:Query` access to the table can enumerate all measurements for any patient. The recipe doesn't discuss row-level access control or attribute-based access.

**Suggested fix:** This is acceptable for most healthcare architectures (application-layer access control is standard), but add a brief note: "Application-layer authorization must verify that the requesting clinician has a care relationship with the patient before returning wound data. DynamoDB's encryption at rest does not provide row-level access control."

---

## Architecture Expert Review

### What's Done Well

The pipeline architecture (capture -> calibrate -> segment -> measure -> store -> track) is clean and appropriate. The separation of marker detection from wound segmentation is correct (they're different problems requiring different approaches). The longitudinal tracking design with DynamoDB time-series modeling is sound. The graceful degradation pattern (flag images without markers rather than rejecting them) is excellent operational design. The cost estimate ($0.02-0.05 per image, $50-150/month at 1000 images/day) is reasonable for the stated architecture. The performance benchmarks are realistic (Dice > 0.85 is achievable, < 5 second latency is reasonable for the pipeline).

### Issue ARCH-1: DynamoDB Key Design Has a Query Problem for Wound Timeline (HIGH)

**Section:** Code Step 5 (store_measurement)

**The problem:** The recipe uses `patient_id` as the partition key and `wound_id#timestamp` as the sort key. The query to retrieve previous measurements uses:

```
partition_key=patient_id,
sort_key_begins_with=wound_id
```

This works, but it means all measurements for all wounds for a patient are in the same partition. To query a specific wound's timeline, you must use `begins_with` on the sort key. This is fine for patients with a few wounds, but the real problem is the composite sort key format: `wound_id + "#" + now()`.

If `wound_id` is something like `WND-003-sacral` and the timestamp is ISO format, the sort key becomes `WND-003-sacral#2026-05-31T14:30:22Z`. The `begins_with` query works. But the sort order is lexicographic: measurements sort by wound_id first, then by timestamp within each wound. This means you cannot efficiently query "all measurements for this patient in the last 7 days across all wounds" without a full partition scan.

More critically, the `limit=1, scan_index_forward=False` query to get the "most recent" measurement for a specific wound will actually return the most recent measurement for the *lexicographically last* wound_id, not the specified wound. The query needs a `sort_key_begins_with` filter combined with reverse scan, which DynamoDB supports, but the pseudocode's intent and the actual DynamoDB behavior may diverge.

**Suggested fix:** Clarify the key design. Either: (a) Use `patient_id#wound_id` as the partition key and `timestamp` as the sort key (simplest for per-wound queries, but requires knowing the wound_id upfront), or (b) Keep the current design but add a GSI with `wound_id` as partition key and `timestamp` as sort key for efficient per-wound timeline queries. Add a note: "For production, consider a GSI on wound_id + measurement_date to support efficient wound-specific timeline queries without partition scans."

### Issue ARCH-2: No Image Quality Gate Before Expensive Inference (MEDIUM)

**Section:** Architecture flow, Code walkthrough

**The problem:** The recipe's pipeline goes: validate (resolution, size, metadata) -> detect marker -> segment wound -> compute measurements. The validation step checks resolution and file size, but doesn't assess image quality (blur, lighting, focus) before calling the SageMaker endpoint. Recipe 9.1 (Image Quality Assessment) exists for exactly this purpose, and the Related Recipes section references it, but the architecture doesn't include it in the pipeline.

A blurry or poorly-lit wound photo will still be sent to the segmentation model, which will produce a low-confidence result, which will then be flagged for review. This wastes the inference cost ($0.02-0.05) on images that should have been rejected upfront.

**Suggested fix:** Add a note in the architecture flow or in the validation step: "For production deployments, insert an image quality assessment step (see Recipe 9.1) before segmentation. Reject or flag images that are too blurry, too dark, or poorly framed before incurring inference costs. This is especially valuable in home health settings where lighting is uncontrolled."

### Issue ARCH-3: SageMaker Endpoint Scaling Not Addressed (MEDIUM)

**Section:** Prerequisites (Cost Estimate), Why These Services

**The problem:** The cost estimate mentions "SageMaker endpoint: ~$0.05/hr for ml.m5.large" and "At 1000 images/day." But it doesn't discuss auto-scaling. A single ml.m5.large endpoint can handle ~200 images/hour (per the benchmarks table). At 1000 images/day evenly distributed, that's ~42/hour, well within capacity. But wound photography is bursty: home health nurses photograph wounds during morning and afternoon visit windows. You might get 500 images in a 2-hour morning window and 500 in a 2-hour afternoon window, meaning 250/hour peak, which exceeds the single-instance throughput.

**Suggested fix:** Add a brief note: "Configure SageMaker endpoint auto-scaling based on `InvocationsPerInstance` metric. Wound photography is bursty (concentrated during clinical visit hours). A single instance handles steady-state load, but peak hours may require 2-3 instances. Consider a scaling policy that adds capacity at 150 invocations/instance/hour."

### Issue ARCH-4: No Mention of Model Versioning or A/B Testing (LOW)

**Section:** Why These Services (SageMaker)

**The problem:** The recipe doesn't discuss how to update the segmentation model over time. As you collect more annotated wound images, you'll retrain the model. SageMaker supports model versioning and production variants for A/B testing new models. For a clinical measurement tool, you need to validate that a new model version doesn't introduce measurement drift (a new model that systematically measures 10% smaller would create false "healing" signals across all patients).

**Suggested fix:** Brief note in Variations or Honest Take: "When retraining the segmentation model, validate against a held-out test set AND compare measurements on a cohort of recent wounds against the previous model version. A model that shifts measurements systematically will create false healing or deterioration signals across your patient population."

---

## Networking Expert Review

### What's Done Well

The recipe explicitly states "SageMaker endpoint in VPC with VPC endpoints for S3 and DynamoDB." TLS 1.2+ in transit is specified. The architecture keeps PHI within the AWS account boundary.

### Issue NET-1: VPC Endpoint List Is Incomplete (MEDIUM)

**Section:** Prerequisites table, "VPC" row

**The problem:** The recipe states "SageMaker endpoint in VPC with VPC endpoints for S3 and DynamoDB." But the architecture also uses: Lambda (which needs VPC endpoints for the services it calls), API Gateway, CloudWatch Logs, and KMS. If the Lambda is in a VPC (which it should be, since it calls the VPC-hosted SageMaker endpoint), it needs VPC endpoints for all services it communicates with, or traffic will route through a NAT gateway.

The missing VPC endpoints are:
- `com.amazonaws.{region}.sagemaker.runtime` (for InvokeEndpoint; the recipe says "SageMaker" but doesn't specify the runtime endpoint vs. the API endpoint)
- `com.amazonaws.{region}.logs` (for CloudWatch Logs)
- `com.amazonaws.{region}.kms` (for S3 SSE-KMS decryption/encryption)

Without the KMS VPC endpoint, S3 operations using SSE-KMS will fail if the Lambda has no internet path, or will route through NAT if one exists.

**Suggested fix:** Expand the VPC row: "Lambda and SageMaker endpoint in VPC. Required VPC endpoints: `s3` (gateway), `dynamodb` (gateway), `sagemaker.runtime` (interface), `logs` (interface), `kms` (interface). Without the KMS endpoint, S3 SSE-KMS operations will fail in a VPC with no NAT gateway."

### Issue NET-2: No Guidance on API Gateway to Lambda VPC Connectivity (LOW)

**Section:** Architecture Diagram

**The problem:** The architecture shows API Gateway -> Lambda. If the Lambda is in a VPC (as recommended for SageMaker access), API Gateway can still invoke it (API Gateway invokes Lambda through the Lambda service, not through the VPC). But the response path and cold start implications of VPC-attached Lambdas are not mentioned. VPC-attached Lambdas historically had longer cold starts (this has improved with Hyperplane ENI improvements, but it's still a consideration for the < 5 second latency target).

**Suggested fix:** Brief note: "VPC-attached Lambda functions may have slightly longer cold starts. For the < 5 second latency target, consider provisioned concurrency during peak clinical hours to eliminate cold starts."

---

## Voice Reviewer

### What's Done Well

The voice is excellent throughout. The opening scenario (home health nurse, disposable ruler, two different measurements) is vivid, specific, and makes the reader feel the problem. The technology section teaches segmentation, scale calibration, and longitudinal tracking without a single AWS service name. The parenthetical asides are well-deployed: "(ok, this is a gross oversimplification, but stay with me)" energy without being that explicit. The honest take delivers genuine operational wisdom. The "clinician compliance with the capture protocol is your biggest risk" insight is the kind of thing you only learn from deployment experience.

The 70/30 vendor balance is well-maintained. The entire Technology section and General Architecture Pattern are vendor-agnostic. AWS appears only in the implementation section.

### Issue VOICE-1: No Em Dashes Detected (PASS)

Scanned the full recipe. Zero em dashes found. Correct.

### Issue VOICE-2: One TODO Left in the Recipe (MEDIUM)

**Section:** The Honest Take, final paragraph

**The text:** "TODO: Verify current FDA guidance on wound measurement software classification."

This is a draft artifact that should not appear in the published recipe. It breaks the voice (readers shouldn't see the author's task list) and leaves a gap in the regulatory guidance.

**Suggested fix:** Either resolve the TODO (wound measurement tools that only measure and document are generally Class I exempt or Class II 510(k); the FDA's 2022 guidance on Clinical Decision Support clarifies the boundary) or remove the TODO and rephrase: "Wound measurement tools that measure and document without recommending treatment are generally Class I or Class II devices under FDA guidance. The moment you add treatment recommendations, you enter a different regulatory category. Consult regulatory counsel for your specific claims."

### Issue VOICE-3: Second TODO in Additional Resources (LOW)

**Section:** Additional Resources, final line

**The text:** "TODO: Verify availability of specific AWS sample repos for medical image segmentation with SageMaker."

Same issue as VOICE-2. Draft artifact in published content.

**Suggested fix:** Either find and include relevant repos (e.g., `aws-samples/amazon-sagemaker-medical-imaging` if it exists) or remove the TODO and the line entirely. The existing AWS documentation links are sufficient.

### Issue VOICE-4: Vendor Balance Is Correct (PASS)

The Technology section (approximately 65% of the recipe's prose) is completely vendor-agnostic. AWS services appear only in the AWS Implementation section. The ratio is well within the 70/30 guideline.

---

## Stage 2: Expert Discussion

### Conflicts and Overlaps

**SEC-2 (EXIF/PHI) is the most impactful finding.** GPS coordinates in home health wound photos directly reveal patient home addresses. This is a real-world PHI leak that most teams wouldn't catch until a privacy audit. It's not a theoretical concern; every smartphone photo includes GPS by default unless the camera app is configured otherwise. This is HIGH because it's a compliance gap that could result in a HIPAA violation if images are shared for research or model training without EXIF stripping.

**ARCH-1 (DynamoDB key design) and the pseudocode interact.** The key design issue isn't just a scalability concern; the pseudocode's `limit=1, scan_index_forward=False` query may not behave as the author intends. A reader implementing this directly would get incorrect "previous measurement" lookups if a patient has multiple wounds. This is HIGH because it would produce incorrect healing rate calculations (comparing measurements from different wounds).

**NET-1 and SEC-1 overlap.** The incomplete VPC endpoint list (NET-1) means that without a NAT gateway, S3 SSE-KMS operations would fail entirely (no KMS endpoint). With a NAT gateway, KMS traffic routes over the public internet. The IAM scoping issue (SEC-1) is a separate control-plane concern. NET-1 is the more urgent fix because it affects whether the system works at all in a properly locked-down VPC.

**VOICE-2 (TODO in text) is a process issue, not a content issue.** The TODO about FDA guidance is actually a content gap (the recipe makes a regulatory claim without verification), but the fix is straightforward and the claim is directionally correct.

### Priority Resolution

1. SEC-2 (EXIF metadata) and ARCH-1 (DynamoDB key design) are HIGH because they represent real deployment failures or compliance gaps.
2. NET-1 (VPC endpoints), ARCH-2 (quality gate), ARCH-3 (scaling), and VOICE-2 (TODO) are MEDIUM because they're gaps that a knowledgeable builder would catch but a less experienced team might miss.
3. SEC-3, SEC-4, ARCH-4, NET-2, and VOICE-3 are LOW polish items.

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

The recipe is clinically sound, architecturally appropriate, well-written, and provides actionable guidance for building a wound measurement system. The two HIGH findings (EXIF metadata PHI leakage and DynamoDB key design causing incorrect healing rate calculations) are significant but correctable without restructuring the recipe. No CRITICAL findings. The recipe correctly identifies the key challenges (clinician compliance, lighting variation, skin tone bias in training data), provides honest operational guidance, and maintains excellent vendor balance.

---

### Prioritized Findings

| # | Severity | Expert | Section | Finding | Fix |
|---|----------|--------|---------|---------|-----|
| 1 | HIGH | Security | Code Step 1, Technology section | Smartphone wound photos contain EXIF GPS coordinates revealing patient home addresses (especially in home health). No mention of metadata stripping. | Add EXIF stripping step before storage. Strip GPS, device IDs, photographer info. Retain only timestamp and dimensions. Store EXIF separately if needed for audit. |
| 2 | HIGH | Architecture | Code Step 5 (store_measurement) | DynamoDB key design (`patient_id` PK, `wound_id#timestamp` SK) with `limit=1, scan_index_forward=False` query returns wrong "previous measurement" for patients with multiple wounds. Healing rate calculation would compare measurements from different wounds. | Use `patient_id#wound_id` as partition key with `timestamp` as sort key, OR add `sort_key_begins_with=wound_id` explicitly in the query pseudocode and add a GSI note for cross-wound queries. |
| 3 | MEDIUM | Networking | Prerequisites (VPC row) | VPC endpoint list incomplete. Missing `sagemaker.runtime` (vs ambiguous "SageMaker"), `logs`, and `kms`. Without KMS endpoint, S3 SSE-KMS operations fail in a locked-down VPC. | List explicit endpoints: `s3` (gateway), `dynamodb` (gateway), `sagemaker.runtime` (interface), `logs` (interface), `kms` (interface). |
| 4 | MEDIUM | Voice | The Honest Take (final paragraph) | TODO left in published text: "TODO: Verify current FDA guidance on wound measurement software classification." Draft artifact breaks voice and leaves regulatory gap. | Resolve with correct FDA guidance (Class I/II for measurement-only tools) or remove TODO and state the general principle with "consult regulatory counsel" caveat. |
| 5 | MEDIUM | Architecture | Architecture flow, Code walkthrough | No image quality gate before expensive SageMaker inference. Blurry/dark photos waste $0.02-0.05 per image on unusable results. | Add note referencing Recipe 9.1 as a pre-filter step for production deployments. |
| 6 | MEDIUM | Architecture | Prerequisites (Cost Estimate) | No auto-scaling guidance for SageMaker endpoint. Wound photography is bursty (concentrated during clinical visit hours); peak load may exceed single-instance throughput. | Add note about auto-scaling on `InvocationsPerInstance` metric and provisioned concurrency during peak hours. |
| 7 | MEDIUM | Security | Prerequisites (IAM row) | IAM permissions listed without resource ARN scoping. Not least-privilege for HIPAA. | Show resource-scoped ARN examples for each permission (specific bucket paths, endpoint ARN, table ARN). |
| 8 | LOW | Security | Code Step 3, Expected Results | Segmentation masks stored in S3 are PHI-derived but not explicitly called out as requiring same access controls as original images. | Brief note: masks are PHI-derived, apply same encryption and access policies. |
| 9 | LOW | Voice | Additional Resources (final line) | Second TODO: "TODO: Verify availability of specific AWS sample repos for medical image segmentation with SageMaker." | Find and include relevant repos or remove the line entirely. |
| 10 | LOW | Architecture | Why These Services (SageMaker) | No mention of model versioning or validation against measurement drift when retraining. | Brief note about validating new model versions don't introduce systematic measurement shifts. |
| 11 | LOW | Networking | Architecture Diagram | No guidance on VPC-attached Lambda cold starts affecting the < 5 second latency target. | Brief note about provisioned concurrency for latency-sensitive clinical workflows. |

---

### Summary

A strong recipe that teaches wound measurement concepts thoroughly, provides a sound architecture, and delivers genuine operational wisdom. The opening scenario and the honest take are particularly well-crafted. The two HIGH findings (EXIF metadata leaking patient home addresses, and a DynamoDB key design that would produce incorrect healing rate calculations for multi-wound patients) are the priority fixes. The EXIF issue is especially important for the home health use case that the recipe centers its narrative around. After addressing findings 1-7, this recipe is ready for publication.
