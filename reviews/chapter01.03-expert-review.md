# Expert Review: Recipe 1.3 - Lab Requisition Form Extraction

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking)
**Date:** 2026-03-05
**Recipe file:** `chapter01.03-lab-requisition-extraction.md`

---

## Overall Assessment

This is the strongest recipe in the chapter so far. The clinical context is excellent, the two-stage pipeline rationale is well argued, and the "Why This Isn't Production-Ready" section is unusually honest. However, there are two factual errors that must be fixed before publication, a cost estimate that appears to be off by roughly an order of magnitude, and a critical networking gap (missing KMS VPC endpoint) that would silently break a production deployment.

Priority breakdown: 2 must-fix errors, 4 significant gaps, 5 improvement recommendations.

---

## Security Expert Review

### What's Done Well

The PHI handling overview is correct and covers the essentials: BAA under account-level agreement, KMS for S3, CloudTrail audit trail, "never use real PHI in development" warning. Noting that Comprehend Medical does not retain customer data is accurate and important. The NEGATION/HYPOTHETICAL/FAMILY trait explanation is genuinely useful for readers who might otherwise treat all clinical entities as current, active patient conditions.

### Issue S1: DynamoDB Encryption Inconsistency (Significant)

**The problem:** The recipe explicitly uses customer-managed KMS keys for S3 but describes DynamoDB encryption as "default." AWS default DynamoDB encryption uses AWS-owned keys, not customer-managed keys. For PHI data under HIPAA, many compliance programs require customer-managed keys (CMK) on all PHI stores so the audit trail shows key usage. Using CMK also enables key revocation if needed.

**Suggested fix:** Add an explicit note that DynamoDB should use a customer-managed KMS key (`aws/dynamodb` or a dedicated CMK), matching the S3 approach. Update the DynamoDB row in the Ingredients table to specify "encryption at rest with customer-managed KMS key" rather than "encryption at rest enabled (default)."

### Issue S2: PHI in DetectEntitiesV2 Response Not Addressed (Significant)

**The problem:** `DetectEntitiesV2` returns a `PROTECTED_HEALTH_INFORMATION` category containing entities like patient names, dates, phone numbers, geographic information, ages, and other Safe Harbor identifiers extracted from the text. The recipe's pseudocode silently includes these in the `clinical_entities` map stored in DynamoDB. No guidance is given on whether to store, drop, or log-separately these PHI entities.

**Suggested fix:** Add a note in Step 6 (or the "Why This Isn't Production-Ready" section) that the `PROTECTED_HEALTH_INFORMATION` category in `DetectEntitiesV2` output contains re-identified PHI fields and should be handled intentionally. A reader building this naively will store those entities alongside the rest of the clinical_entities map, creating a second copy of PHI in DynamoDB with no explicit policy decision behind it.

### Issue S3: Trait Confidence Threshold Is a Patient Safety Choice (Significant)

**The problem:** The pseudocode in Step 6 applies `t.Score >= 0.75` to include trait tags like NEGATION and HYPOTHETICAL. This threshold is hardcoded with no explanation of the clinical implication. Traits govern whether an entity represents a condition the patient currently has. A NEGATION trait with a score of 0.76 accepted correctly avoids coding "no chest pain" as an active diagnosis. A NEGATION trait with a score of 0.74 silently dropped means that "no diabetes" could produce a diabetes ICD-10 code. Missing a negation at 0.75 is a different kind of error than missing an OCR character.

**Suggested fix:** Add a comment explaining why this threshold was chosen and what happens when a trait is dropped below threshold (the entity is treated as an affirmative, present, first-person clinical finding). Recommend erring lower (0.60 or even logging all traits above 0.50 and reviewing) rather than higher for traits that can invert clinical meaning.

### Issue S4: IAM Resource Scope for Comprehend Medical (Minor)

**The problem:** The prerequisites list `comprehend:DetectEntitiesV2` and `comprehend:InferICD10CM` permissions. Comprehend Medical API actions do not support resource-level conditions (you cannot restrict to a specific endpoint or resource ARN). This is worth a one-line note so readers don't spend time trying to scope them down, as they would with S3 or DynamoDB. Not a bug, but omitting the note invites fruitless IAM troubleshooting.

**Suggested fix:** Add a note in the prerequisites: "Comprehend Medical IAM actions do not support resource-level conditions; the permission applies account-wide. Scope access control via VPC endpoints and Lambda execution role boundaries instead."

---

## Architecture Expert Review

### What's Done Well

The two-stage pipeline separation is well motivated. The acknowledgment that Comprehend Medical confidence scores and OCR confidence scores are on different scales is an important distinction that most recipes omit. The "medical necessity check is not a replacement for utilization management" caveat is exactly the right framing. The CPT lookup table maintenance concern is real and flagged clearly.

### Issue A1: Character Limit Contradiction (Must Fix - Factual Error)

**The problem:** The pseudocode in Step 4 contains this comment:

```
// InferICD10CM accepts up to 10,000 characters per request.
combined = first 9800 characters of combined
```

The "Why This Isn't Production-Ready" section then states:

> "`InferICD10CM` and `DetectEntitiesV2` each accept up to 20,000 UTF-8 characters per request."

These are contradictory. The AWS-documented limit for `InferICD10CM` is 10,000 UTF-8 bytes. The 20,000-byte limit applies to `DetectEntitiesV2`. The code comment is correct. The prose in the production section is wrong, and it directly undoes the correct defensive coding in Step 4.

A reader who reads the "production-ready" section and trusts it over the code comment will remove the 9,800-character clip and start sending up to 20,000 characters to `InferICD10CM`, which will result in API errors on longer documents.

**Suggested fix:** Change the production section to: "`InferICD10CM` accepts up to 10,000 UTF-8 characters per request; `DetectEntitiesV2` accepts up to 20,000 UTF-8 characters per request. The limits differ between the two APIs." Also add a note that a production implementation clips each API's input to its own limit separately, not a shared clip, to avoid unnecessarily truncating `DetectEntitiesV2` input on longer documents.

### Issue A2: Cost Estimate Math Appears Incorrect (Must Fix - Factual Error)

**The problem:** The prerequisites table states:

> "Comprehend Medical InferICD10CM: $0.01 per 100 characters, approximately $0.003 for a 200-character diagnosis field."

At $0.01 per 100 characters, a 200-character field is 2 units = $0.02, not $0.003. The same calculation applies to `DetectEntitiesV2`. The total per-form estimate of $0.008 is also hard to reconcile if Comprehend Medical charges $0.02 per call on even a modest-length text.

The pricing page confirms the $0.01-per-unit (100 characters) model with a 1-unit minimum per request.

**Suggested fix:** Recalculate the cost estimate. For a 200-character diagnosis field: Textract ~$0.003, InferICD10CM ~$0.02, DetectEntitiesV2 ~$0.02, total approximately $0.04-0.05 per form. If the intent is to show a minimal case, use a shorter example text length and show the calculation explicitly. If there's a pricing tier or first-month free tier being assumed, state it. An underestimate on cost by roughly 5x will frustrate readers when their actual AWS bills arrive.

Note: Verify current pricing against the AWS Comprehend Medical pricing page before publishing, as pricing may have changed.

### Issue A3: Idempotency Not Addressed (Significant)

**The problem:** SNS guarantees at-least-once delivery. The processing Lambda (`lab-req-process`) has no idempotency mechanism. If SNS delivers the completion notification twice (which is uncommon but guaranteed to happen occasionally at scale), the same lab requisition gets processed twice: two Comprehend Medical calls, two DynamoDB writes, potentially two entries for the same order.

**Suggested fix:** Add idempotency handling to the "Why This Isn't Production-Ready" section. The simplest approach: at the start of the processing Lambda, check DynamoDB for an existing record with the same `document_key`. If one exists, log a warning and return without processing. Use a DynamoDB conditional write (`ConditionExpression: "attribute_not_exists(document_key)"`) for the final store step to make the write itself idempotent.

### Issue A4: Lambda Timeout Not Mentioned (Significant)

**The problem:** The default Lambda timeout is 3 seconds. The processing Lambda performs paginated `GetDocumentAnalysis` calls (which can require multiple round trips for long documents), plus two Comprehend Medical API calls. For a multi-page lab requisition with clinical notes, this Lambda needs at least 30 seconds, arguably 60. A reader deploying with default settings will see mysterious Lambda timeouts and no output in the review queue.

**Suggested fix:** Add Lambda timeout configuration to the prerequisites or the "production-ready" gap list. Recommended: 60 seconds for the processing Lambda. Also note that Lambda billing is per 1ms, so a 30-second Lambda with minimal memory is inexpensive.

### Issue A5: Medical Necessity Map Clinically Inconsistent with Sample Output (Improvement)

**The problem:** The sample output flags "Lipid Panel" (CPT 80061) as having "No supporting diagnosis found." The patient has E11.9 (Type 2 diabetes) and I10 (hypertension). Looking at the MEDICAL_NECESSITY_MAP, the E11 entry does not include 80061 (lipid panel). Only the E78 (hyperlipidemia) entry does.

This is technically consistent with the map as written, but the map itself is clinically wrong. Lipid monitoring for patients with Type 2 diabetes is standard of care and is supported under most CMS LCD policies for diabetes. The example thus demonstrates a false-positive medical necessity flag caused by an incomplete map, which the recipe does acknowledge in "The Honest Take." The problem is that the MEDICAL_NECESSITY_MAP is also shown as the reference implementation readers will copy.

**Suggested fix:** Add 80061 to the E11 map entry, and note in a comment that lipid panels are widely supported for T2DM under LCD policies. Keep the teaching point about false positives in "The Honest Take," but change the sample output to show a different, genuinely ambiguous necessity flag (a test that is truly borderline without a supporting diagnosis). This avoids shipping a map that will generate false positives for one of the most common lab-order combinations in ambulatory medicine.

### Issue A6: Step Functions Not Mentioned (Improvement)

**The problem:** The pipeline has 8 steps, multiple failure modes, separate error handling for Comprehend Medical failures vs. Textract failures, and downstream routing decisions. The recipe continues the two-Lambda SNS pattern from Recipe 1.2, which is appropriate for that recipe's simpler flow. For this recipe, AWS Step Functions would provide explicit state machine visibility, built-in retry with exponential backoff, and per-step error routing without additional code.

This is not wrong. Two Lambdas works. But a reader building a production pipeline will eventually arrive at Step Functions and wish the recipe had flagged the tradeoff.

**Suggested fix:** Add a one-paragraph note in the "Variations and Extensions" section: "For pipelines this complex, AWS Step Functions provides explicit state visibility and built-in error handling per step. The two-Lambda pattern here is simpler to deploy but concentrates all orchestration logic in the processing Lambda. Step Functions becomes attractive when the pipeline adds branches (specialty test routing, payer-specific NLP rules) that make inline conditional logic hard to maintain."

---

## Networking Expert Review

### What's Done Well

The recipe correctly identifies that CloudWatch Logs requires its own VPC endpoint when Lambdas run in a private subnet. This is one of the most commonly missed operational issues in private VPC Lambda deployments, and flagging it in the prerequisites is good practice. The interface endpoint for Comprehend Medical is implied correctly by listing it alongside the other service endpoints.

### Issue N1: Missing KMS VPC Endpoint (Must Fix - Will Break Production)

**The problem:** The prerequisites list VPC endpoints for S3, Textract, DynamoDB, SNS, Comprehend Medical, and CloudWatch Logs. KMS is not listed.

When Lambda is in a private subnet (no internet egress, no NAT Gateway) and S3 uses SSE-KMS with a customer-managed key, every S3 GetObject or PutObject call requires a call to the KMS API to decrypt or generate the data key. Without a KMS VPC endpoint (`com.amazonaws.{region}.kms`), those calls have no route to KMS and the Lambda fails with `AccessDeniedException` or a timeout. The error message is not always intuitive and the root cause is not obvious from Lambda logs alone.

This is not a theoretical gap. A reader following these prerequisites exactly, deploying with a private subnet and CMK on S3, will have a pipeline that cannot read its own source documents.

**Suggested fix:** Add `com.amazonaws.{region}.kms` (interface endpoint) to the VPC endpoint list in the prerequisites. Note that KMS endpoints are interface endpoints billed per AZ per hour, unlike S3 and DynamoDB which use free gateway endpoints.

### Issue N2: Interface vs. Gateway Endpoint Distinction Not Made (Significant)

**The problem:** The prerequisites list VPC endpoints without distinguishing between the two types:

- **Gateway endpoints:** S3, DynamoDB. Free. Use route table entries. No security groups.
- **Interface endpoints (PrivateLink):** Textract, SNS, Comprehend Medical, CloudWatch Logs, KMS. Cost approximately $0.01 per AZ per hour plus data processing charges. Use elastic network interfaces. Require security group rules to allow inbound 443 from Lambda.

A reader who sets up gateway endpoints for S3/DynamoDB using the console and then tries to add "VPC endpoints for Textract" using the same process will be confused by the different configuration screens, the unexpected security group prompts, and the billing line items that appear. The setup is not hard but the difference is real and undocumented here.

**Suggested fix:** Add a note in the prerequisites (or a callout box): "S3 and DynamoDB use gateway-style VPC endpoints (free, configured via route tables). All other services listed here use interface endpoints (PrivateLink), which have hourly per-AZ costs and require security group rules allowing HTTPS inbound from the Lambda subnet."

### Issue N3: Comprehend Medical Regional Availability Not Noted (Significant)

**The problem:** Amazon Comprehend Medical is not available in all AWS regions. As of recent documentation, it is available in us-east-1, us-east-2, us-west-2, ap-southeast-2, ca-central-1, eu-west-1, eu-west-2, and a few others, but notably absent from several regions where HIPAA workloads are common (ap-southeast-1, eu-central-1, and others).

A reader deploying in a region without Comprehend Medical availability faces two bad options: send PHI cross-region to a supported region (with compliance implications they may not have considered), or use the Comprehend Medical endpoints in a region other than where their data lives. Neither option is obviously safe from a HIPAA compliance standpoint without analysis of data residency requirements.

**Suggested fix:** Add a note in the prerequisites: "Verify that Amazon Comprehend Medical is available in your target AWS region before design. If your compliance requirements restrict data to a region where Comprehend Medical is not available, see Recipe 5.2 for self-managed clinical NLP alternatives." Include a link to the Comprehend Medical regional availability table in the AWS documentation.

### Issue N4: No Mention of S3 Bucket Policy Enforcing TLS (Improvement)

**The problem:** The recipe says "All API calls over TLS." This is true by default for AWS SDK calls. However, S3 buckets can be configured to refuse non-TLS connections at the bucket policy level using the `aws:SecureTransport` condition. For PHI data, this is a defense-in-depth measure worth mentioning, since any misconfigured client or legacy integration that accesses the bucket without TLS should be rejected at the bucket level.

**Suggested fix:** Add a note under the S3/encryption prerequisites: "Consider adding a bucket policy that denies requests where `aws:SecureTransport` is false. For PHI buckets, this closes a defense-in-depth gap at the resource level regardless of client configuration."

---

## Cross-Expert Agreement

All three reviewers flag the same underlying concern independently: the recipe's production pathway has more invisible gaps than the explicit "Why This Isn't Production-Ready" section captures. The missing KMS endpoint (N1), the character limit contradiction (A1), and the cost estimate error (A2) are the three issues most likely to cause a reader to either fail silently in production or badly misestimate operational costs before building.

The security and architecture reviewers both note the PHI in DetectEntitiesV2 response (S2) as a gap: it is a security issue (unintentional PHI storage) with an architectural cause (no filtering in the entity assembly step).

---

## Prioritized Fix List

### Must Fix Before Publication

| ID | Issue | Expert |
|----|-------|--------|
| A1 | Character limit contradiction: InferICD10CM is 10,000, not 20,000 chars. Prose contradicts code. | Architecture |
| A2 | Cost estimate math: $0.003 for 200-char Comprehend Medical call does not match $0.01/100-char pricing. Total ~$0.008 per form appears to be ~5x too low. Verify and recalculate. | Architecture |
| N1 | Missing KMS VPC endpoint in prerequisites. Will silently break S3 SSE-KMS reads in a private subnet. | Networking |

### Fix Before Publication (High Impact)

| ID | Issue | Expert |
|----|-------|--------|
| S1 | DynamoDB uses "default" encryption while S3 uses CMK. PHI parity requires CMK on DynamoDB too. | Security |
| S2 | PHI category in DetectEntitiesV2 output stored silently. Needs explicit handling guidance. | Security |
| A3 | No idempotency handling for SNS at-least-once delivery. Duplicate processing risk. | Architecture |
| A4 | Lambda timeout not configured. Default 3s will fail on paginated Textract + 2 Comprehend Medical calls. | Architecture |
| N2 | Interface vs. gateway endpoint distinction not explained. Will confuse readers configuring VPC. | Networking |
| N3 | Comprehend Medical regional availability not noted. PHI cross-region compliance risk. | Networking |

### Improvement Recommendations

| ID | Issue | Expert |
|----|-------|--------|
| S3 | NEGATION trait threshold (0.75) has patient safety implications; explain the clinical stakes. | Security |
| S4 | Note that Comprehend Medical IAM actions don't support resource-level conditions (saves troubleshooting time). | Security |
| A5 | Medical necessity map incorrectly flags lipid panels for T2DM patients. Fix map or change sample output. | Architecture |
| A6 | Step Functions mention missing for readers who will outgrow the two-Lambda pattern. | Architecture |
| N4 | Add S3 bucket policy enforcing TLS (`aws:SecureTransport`) as defense-in-depth for PHI buckets. | Networking |

---

## What This Recipe Does Well

Worth preserving in final edits:

- The clinical narrative (the opening problem statement) is the best in the chapter. The description of the error chain from "T2DM" to competing ICD-10 codes to prior auth delay is exactly the right framing for a mixed clinical/technical audience.
- The explicit framing that OCR confidence and NLP confidence are different scales and require different thresholds is correct and non-obvious. Most implementations treat both as interchangeable probabilities. This recipe does not.
- The "ICD-10 specificity gap" discussion in "The Honest Take" (E11.9 when you need E11.65) is honest and accurate about a real failure mode that most NLP pipelines quietly ignore.
- The CPT table maintenance call-out is correct: the lookup table is the highest-maintenance component of this pipeline and it deserves the emphasis it gets.
- The DetectEntitiesV2 trait system explanation (NEGATION, HISTORICAL, FAMILY) adds genuine clinical value. Recipes that skip this produce pipelines that code family history as patient diagnoses.
- The reference to AWS sample repos is well chosen. The claims processing example directly parallels this pipeline.

---

*Review completed 2026-03-05. Three expert perspectives: security, architecture, networking.*
