# Expert Review: Recipe 8.2 - Patient Sentiment Analysis

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-03
**Recipe file:** `chapter08.02-patient-sentiment-analysis.md`

---

## Overall Assessment

This is an excellent recipe. The problem statement immediately connects with anyone who has worked in patient experience. The technology section is genuinely educational, teaching sentiment analysis fundamentals, aspect-based analysis, and healthcare-specific challenges without vendor names. The "What Makes Healthcare Sentiment Different" subsection is a standout: cultural variation in sentiment expression, indirectness as a masking pattern, and PHI contamination are all real-world issues that most generic sentiment tutorials ignore.

The architecture is clean and appropriate for the "Simple/MVP" classification. PHI detection before analysis is correctly positioned as non-negotiable. The pseudocode is accessible and production-minded. The honest take section delivers authentic wisdom about aggregate intelligence mattering more than individual accuracy.

No critical findings. A few high-severity issues around IAM scoping, a missing data retention/lifecycle concern, and an incomplete discussion of the Comprehend custom classifier training loop. Overall: a solid recipe ready for publication with minor fixes.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review

#### What's Done Well

PHI handling is the centerpiece of the preprocessing step, which is correct. The recipe explicitly states "Skip this step and you're running PHI through analytics services without proper safeguards." BAA is called out in prerequisites with a clear rationale (patient feedback routinely contains PHI). Encryption at rest is specified for S3 (SSE-KMS), DynamoDB (default), and CloudWatch (KMS-encrypted log groups). All API calls over TLS. CloudTrail enabled for audit. The architecture flow ensures PHI is redacted before sentiment analysis, so downstream services never see identifiable information.

#### Issue S1: IAM Permissions Listed Without Resource Scoping (HIGH)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The recipe lists IAM permissions as a flat set: `comprehend:DetectSentiment`, `comprehend:ClassifyDocument`, `comprehendmedical:DetectPHI`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:Query`. No resource ARNs are specified. The architecture uses multiple S3 buckets (`feedback-raw/`, `feedback-redacted/`) and a DynamoDB table (`sentiment-results`). A single Lambda role with `s3:PutObject` on `*` can write to any bucket in the account.

More critically: the PHI detection Lambda needs `s3:GetObject` on the raw bucket (which contains PHI) and `s3:PutObject` on the redacted bucket. The sentiment analysis Lambda should only have `s3:GetObject` on the redacted bucket (no PHI). If both Lambdas share a role (common in quick implementations), the sentiment Lambda has read access to raw PHI, which violates least-privilege and the recipe's own design intent of isolating PHI.

**Suggested fix:** Specify separate IAM roles for each Lambda function. PHI-detection Lambda: `s3:GetObject` on `feedback-raw/*`, `s3:PutObject` on `feedback-redacted/*`, `comprehendmedical:DetectPHI`. Sentiment Lambda: `s3:GetObject` on `feedback-redacted/*`, `comprehend:DetectSentiment`. Aspect Lambda: `comprehend:ClassifyDocument`, `dynamodb:PutItem` on the `sentiment-results` table ARN. Add a note: "Each Lambda function should have its own execution role scoped to the minimum resources it needs. This is especially important here because the PHI boundary between raw and redacted buckets is the core security control."

#### Issue S2: No Data Retention or Lifecycle Policy for PHI-Containing Buckets (MEDIUM)

**Location:** Prerequisites table; architecture diagram (S3 buckets)

**The problem:** The `feedback-raw/` S3 bucket contains unredacted patient feedback (PHI). The recipe specifies no data retention policy, lifecycle rules, or deletion schedule. HIPAA requires covered entities to maintain policies for PHI retention and disposal. Indefinite storage of raw patient feedback in S3 without a lifecycle policy means PHI accumulates without governance.

The `feedback-redacted/` bucket also needs consideration: if redaction is lossy (PHI replaced with placeholders), the redacted text may still contain indirect identifiers depending on the feedback content.

**Suggested fix:** Add to Prerequisites: "S3 Lifecycle: Configure lifecycle rules on `feedback-raw/` to transition objects to Glacier after 30 days and expire after your organization's retention period (typically 6-7 years for non-clinical operational data, verify with compliance). Enable S3 Object Lock if regulatory hold is required. The `feedback-redacted/` bucket has lower sensitivity but should still have a defined lifecycle."

#### Issue S3: EventBridge Alert Payload May Leak PHI (MEDIUM)

**Location:** Step 4 pseudocode, the EventBridge emit section

**The problem:** The `store_analysis_result` function emits an EventBridge event with `detail = { feedback_id, department, facility, top_negative_aspect }`. This is safe as written (no text content in the event). However, the recipe doesn't explicitly warn against including the feedback text in alerts. An implementer extending this pattern might include the negative sentence text in the alert for context, which would send PHI through EventBridge to SNS/Slack/PagerDuty (potentially unencrypted endpoints outside the BAA perimeter).

**Suggested fix:** Add a brief inline comment in the pseudocode: "// IMPORTANT: Do not include feedback text in the event payload. The alert routes to external systems (Slack, PagerDuty) that may not be BAA-covered. Include only the feedback_id so reviewers can look up the full text through the authorized dashboard."

#### Issue S4: Comprehend Medical DetectPHI Link May Use Incorrect URL Path (LOW)

**Location:** Additional Resources, AWS Documentation

**The problem:** The link `https://docs.aws.amazon.com/comprehend-medical/latest/dev/textract-phi.html` has "textract" in the path, which suggests it may be a Textract-related page rather than the Comprehend Medical DetectPHI API reference. The correct DetectPHI documentation is at `https://docs.aws.amazon.com/comprehend-medical/latest/dev/how-medical-phi.html` or the API reference.

**Suggested fix:** Verify the URL resolves correctly. If it redirects or 404s, replace with the correct Comprehend Medical PHI detection documentation link.

---

### Architecture Expert Review

#### What's Done Well

The pipeline architecture is clean: Collect, Preprocess (PHI), Analyze, Extract Aspects, Aggregate, Visualize/Alert. Each step is a separate Lambda triggered by S3 events, which is appropriately decoupled for this scale. The confidence threshold (0.6 for aspect classification, 0.85 for attention flagging) is well-chosen and explained. The "mixed" sentiment handling is correct for healthcare context. DynamoDB for results with QuickSight for visualization is appropriate for the access patterns described. The cost estimate ($550/month at 50K items) is reasonable and well-broken-down.

#### Issue A1: Custom Classifier Endpoint Hosting Cost Not Addressed (HIGH)

**Location:** Prerequisites "Cost Estimate" row; Step 3 pseudocode using `ClassifyDocument` with `endpoint_arn`

**The problem:** The cost estimate breaks down Comprehend DetectSentiment ($0.0001/unit), PHI detection (~$0.01/item), and custom classification ($0.0005/item). The $0.0005/item figure is the per-request inference cost. However, Comprehend Custom Classification requires a real-time endpoint to serve `ClassifyDocument` requests, and that endpoint costs $0.50/hour per inference unit (minimum 1 unit = $360/month).

The total cost estimate of "$550/month" does not include the $360/month endpoint hosting. The actual cost is closer to $910/month. At lower volumes, the endpoint cost dominates even more dramatically.

**Suggested fix:** Add to the cost estimate: "Custom classification endpoint hosting: $0.50/hour per inference unit ($360/month minimum, always-on). Total realistic cost at 50,000 items/month: ~$910/month. For batch processing (non-real-time), use Comprehend async classification jobs instead of a real-time endpoint to eliminate hosting cost (pay only per-document). Consider endpoint auto-scaling or scheduled start/stop for off-hours if latency requirements allow."

#### Issue A2: No Error Handling or Dead Letter Queue in the Event-Driven Pipeline (MEDIUM)

**Location:** Architecture diagram; Step-by-step walkthrough

**The problem:** The architecture shows S3 events triggering Lambdas in sequence: S3 event triggers PHI detection Lambda, which writes to redacted bucket, which triggers sentiment Lambda, which calls aspect Lambda. If any Lambda fails (Comprehend throttling, transient network error, malformed input), the feedback item is silently dropped. There's no DLQ, no retry mechanism, and no visibility into processing failures.

For patient experience analytics, a silently dropped item is acceptable in isolation. But systematic failures (a new feedback format from a new survey vendor that causes parsing errors) could silently drop thousands of items, creating a misleading aggregate trend (apparent improvement because negative feedback is being dropped).

**Suggested fix:** Add to the architecture: "Configure DLQs (SQS) on each Lambda function. Failed items are routed to DLQ for investigation and replay. CloudWatch alarm on DLQ message count > 0 alerts the operations team. For the S3 event trigger pattern, enable S3 event notification error destinations to capture delivery failures."

#### Issue A3: Aspect Classifier Training Data Requirements Not Specified (MEDIUM)

**Location:** Step 3 pseudocode references `ASPECT_CLASSIFIER_ENDPOINT`; Prerequisites section

**The problem:** The recipe uses a Comprehend custom classifier for aspect detection but provides no guidance on training data requirements. How many labeled examples per aspect category? What format does the training data need? How long does training take? How do you validate the model before deploying it?

The Technology section mentions "you need training data that's labeled at the aspect level, which is more expensive to create than simple positive/negative labels" and the Honest Take says "at minimum a few hundred labeled examples per aspect category." But the Prerequisites table doesn't list training data as a requirement, and there's no architectural step for training the custom classifier.

**Suggested fix:** Add to Prerequisites table: "Training Data: Minimum 200 labeled examples per aspect category (10 categories = 2,000+ examples minimum). Format: CSV with text and category columns per Comprehend Custom Classification requirements. Training time: 30-60 minutes for a dataset of this size. Budget 2-4 weeks for initial labeling by patient experience staff who understand both the aspect taxonomy and clinical context."

#### Issue A4: Sentence Splitting in Aspect Extraction Is Under-Specified (LOW)

**Location:** Step 3 pseudocode, `split_into_sentences(redacted_text)` call

**The problem:** The pseudocode calls `split_into_sentences()` without discussing what this means in practice. Sentence boundary detection is non-trivial for patient feedback: "Dr. Smith was great. Billing dept. sucks." has an abbreviation that naive period-splitting will break on. Patient feedback also contains fragments, run-on sentences, and bullet-point lists that don't follow standard sentence structure.

**Suggested fix:** Add a brief comment: "// Sentence splitting is non-trivial. Simple period-splitting fails on abbreviations (Dr., dept., etc.). Use a sentence tokenizer that handles abbreviations (like NLTK's punkt or spaCy's sentencizer). For very short feedback (< 2 sentences), classify the entire text as one unit rather than splitting."

---

### Networking Expert Review

#### What's Done Well

The recipe explicitly recommends Lambda in VPC with VPC endpoints for S3, Comprehend, DynamoDB, and CloudWatch Logs. All data in transit over TLS. The architecture keeps PHI within the VPC perimeter (raw feedback in S3, accessed via gateway endpoint; Comprehend Medical called via interface endpoint).

#### Issue N1: Comprehend Medical VPC Endpoint Listed Under "Comprehend" (HIGH)

**Location:** Prerequisites table, "VPC" row: "Lambda in VPC with VPC endpoints for S3, Comprehend, DynamoDB, and CloudWatch Logs"

**The problem:** The recipe uses both Amazon Comprehend (DetectSentiment, ClassifyDocument) and Amazon Comprehend Medical (DetectPHI). These are separate AWS services with separate VPC endpoints:
- `com.amazonaws.{region}.comprehend` for Amazon Comprehend
- `com.amazonaws.{region}.comprehendmedical` for Amazon Comprehend Medical

The prerequisites list "Comprehend" as a single VPC endpoint. A builder deploying in a VPC will create the Comprehend endpoint and find that the PHI detection Lambda (calling Comprehend Medical) fails to connect. This is a deployment-blocking issue for VPC configurations.

**Suggested fix:** Change the VPC prerequisite to: "Lambda in VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), Comprehend (interface), Comprehend Medical (interface), and CloudWatch Logs (interface). Note: Amazon Comprehend and Amazon Comprehend Medical are separate services requiring separate VPC endpoints."

#### Issue N2: No Mention of EventBridge VPC Endpoint (LOW)

**Location:** Prerequisites "VPC" row; Step 4 emitting to EventBridge

**The problem:** The results-storage Lambda emits events to EventBridge for alerting. If this Lambda is in a VPC, it needs connectivity to EventBridge. The recipe doesn't list EventBridge as a VPC endpoint. EventBridge does not have a VPC endpoint; it requires NAT Gateway or internet connectivity for VPC-deployed Lambda.

However, reviewing more carefully: EventBridge is invoked via the AWS SDK using the public endpoint. A VPC-deployed Lambda without internet access or a NAT Gateway cannot reach EventBridge. This is a less common issue because many teams have a NAT Gateway, but for a pure VPC-endpoint deployment (as the recipe implies), it breaks.

**Suggested fix:** Add a note: "EventBridge does not support VPC endpoints. The alerting Lambda either needs NAT Gateway connectivity or should write alert records to DynamoDB (reachable via VPC endpoint) and have a separate non-VPC Lambda poll for alerts and emit to EventBridge." Alternatively, use SNS (which does have a VPC endpoint) for the alerting step instead of EventBridge.

---

### Voice Reviewer

#### What's Done Well

This recipe nails the voice. The opening paragraph ("Every healthcare organization collects patient feedback. HCAHPS surveys, Press Ganey scores...") immediately draws the reader into the scale of the problem. "A 3 out of 5 rating flattens all of that into noise" is exactly the kind of insight that makes a reader nod. The technology section teaches without condescension: the LLM aside ("You don't need a rocket to deliver a pizza") is perfect CC energy. "What Makes Healthcare Sentiment Different" is a standout subsection that demonstrates genuine domain expertise. The Honest Take is authentic and specific: "the aggregate trends are far more valuable than individual predictions" is real-world wisdom.

#### Issue V1: Vendor Balance Is Well Within Range (NO ISSUE)

The recipe dedicates roughly 65% of prose to vendor-agnostic technology explanation (The Problem, The Technology including all subsections, General Architecture Pattern) and 35% to AWS implementation. The 35% is driven by the pseudocode walkthrough which requires service-specific calls. This is within acceptable range of the 70/30 target.

#### Issue V2: No Em Dashes Found (NO ISSUE)

Confirmed: zero em dashes in the recipe. Colons, semicolons, periods, commas, and parentheses used as alternatives throughout.

#### Issue V3: Minor Documentation-Voice in Prerequisites Table (LOW)

**Location:** Prerequisites table rows

**The problem:** Phrases like "Required: patient feedback often contains PHI" and "S3: SSE-KMS; DynamoDB: encryption at rest (default); Lambda logs: KMS-encrypted CloudWatch log groups; all API calls over TLS" are terse and documentation-flavored. This is acceptable for table format and consistent with Recipe 8.1's approach. Tables are inherently more concise and don't need to match full conversational tone.

**Verdict:** No change needed. Consistent with established table conventions.

#### Issue V4: One Sentence in Technology Section Is Slightly Long (LOW)

**Location:** "The Technology" section, paragraph beginning "Modern approaches use machine learning."

**The problem:** "The dominant architecture for the past few years has been transformer-based models (BERT and its variants), fine-tuned on domain-specific data." This is one of the longer sentences in the recipe. It's still clear, but the parenthetical plus the comma-clause plus the participial phrase makes it denser than the surrounding sentences.

**Verdict:** No change needed. The sentence is clear and accurate. One slightly-long sentence is not a pattern problem.

---

## Stage 2: Expert Discussion

**Conflicts and overlaps:**

1. **N1 (Comprehend Medical VPC endpoint) reinforces S1 (IAM scoping):** Both findings relate to the separation between Comprehend and Comprehend Medical as distinct services. The IAM permissions list them as separate actions (`comprehend:DetectSentiment` vs. `comprehendmedical:DetectPHI`), which is correct. But the VPC section treats them as one. Fixing N1 reinforces the mental model that these are separate services with separate access patterns.

2. **A1 (endpoint hosting cost) is independent of other findings** but the most impactful for reader trust. A decision-maker who reads "$550/month" and gets a $910/month bill has a trust problem with the cookbook. This is the same class of issue found in Recipe 8.1 and should be a standard checklist item.

3. **A2 (missing DLQ) and S3 (EventBridge PHI leakage)** are both about what happens when the pipeline encounters edge cases. A2 handles technical failures; S3 handles data leakage in the success path. Both are about defensive patterns the recipe should encourage.

4. **N2 (EventBridge no VPC endpoint) is a real deployment issue** that contradicts the recipe's stated VPC architecture. If all Lambdas are in VPC with only VPC endpoints (no NAT), the EventBridge call in Step 4 will silently fail or timeout. This needs either an architectural change (use SNS instead) or a clear note about NAT Gateway requirement for alerting.

**Priority resolution:** A1 (cost) and N1 (VPC endpoint) are the highest priority because they cause deployment failures or budget surprises. S1 (IAM scoping) is next as a compliance gap. A2 (DLQ) and N2 (EventBridge connectivity) are architectural completeness issues.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

No CRITICAL findings. Three HIGH findings that should be addressed before publication. The recipe's core architecture is sound, the PHI handling approach is correct, and the educational content is strong. The findings are about precision (cost estimates, VPC endpoint naming, IAM scoping) rather than fundamental design flaws.

---

## Prioritized Findings

| ID | Severity | Expert | Location | Issue | Fix |
|----|----------|--------|----------|-------|-----|
| A1 | HIGH | Architecture | Prerequisites "Cost Estimate" | Custom classifier endpoint hosting ($360/month) not included in $550/month total estimate. Actual cost is ~$910/month. | Add endpoint hosting to cost estimate. Mention async classification as cost-saving alternative. |
| N1 | HIGH | Networking | Prerequisites "VPC" row | Comprehend Medical is a separate service needing its own VPC endpoint (`com.amazonaws.{region}.comprehendmedical`). Listed under generic "Comprehend." | List Comprehend and Comprehend Medical as separate VPC endpoints. |
| S1 | HIGH | Security | Prerequisites "IAM Permissions" | IAM permissions not resource-scoped. PHI detection and sentiment Lambdas should have separate roles with different S3 bucket access. Sentiment Lambda should never see raw PHI bucket. | Specify per-Lambda roles with resource ARNs. The PHI boundary between raw/redacted buckets is the core security control. |
| S2 | MEDIUM | Security | Prerequisites; S3 bucket architecture | No data retention or lifecycle policy for PHI-containing `feedback-raw/` bucket. PHI accumulates without governance. | Add S3 lifecycle rules: transition to Glacier after 30 days, expire per retention policy. |
| A2 | MEDIUM | Architecture | Architecture diagram; pipeline flow | No DLQ or error handling. Failed Lambda invocations silently drop feedback items. Systematic failures create misleading aggregate trends. | Add DLQ on each Lambda. CloudWatch alarm on DLQ depth. |
| S3 | MEDIUM | Security | Step 4 pseudocode, EventBridge emit | No explicit warning against including feedback text in alert payload. Alerts route to non-BAA systems (Slack, PagerDuty). | Add inline comment warning not to include text in event payload. |
| A3 | MEDIUM | Architecture | Step 3; Prerequisites | Custom classifier training data requirements not specified in Prerequisites. No architectural step for training the model. | Add training data requirements (200+ examples per category, 2-4 week labeling sprint). |
| N2 | LOW | Networking | Prerequisites "VPC"; Step 4 EventBridge | EventBridge has no VPC endpoint. VPC-deployed Lambda cannot reach EventBridge without NAT Gateway. Contradicts pure VPC-endpoint architecture. | Note NAT Gateway requirement for alerting, or suggest SNS (which has VPC endpoint) as alternative. |
| S4 | LOW | Security | Additional Resources | Comprehend Medical DetectPHI documentation link URL path contains "textract" which may be incorrect. | Verify link resolves to correct page. |
| A4 | LOW | Architecture | Step 3 pseudocode | `split_into_sentences()` under-specified. Patient feedback contains abbreviations and fragments that break naive splitting. | Add comment about using a proper sentence tokenizer. |
| V3 | LOW | Voice | Prerequisites table | Minor documentation-voice in table format. | No change needed. Tables exempt from full voice matching. |

---

## Additional Observations

### GitHub Repo Links Are Valid

Both `amazon-comprehend-examples` and `amazon-comprehend-medical-fhir-integration` are known aws-samples repositories. The `amazon-comprehend-custom-entity` repo is also valid. All three are appropriately framed as "demonstrate patterns used here."

### The "What Makes Healthcare Sentiment Different" Section Is Exceptional

The subsection covering mixed sentiment as norm, clinical/emotional language intersection, indirectness patterns, cultural variation, and PHI contamination is genuinely educational. This is the kind of content that makes the cookbook valuable beyond a typical AWS tutorial. A reader building a healthcare sentiment system will avoid real pitfalls because of this section.

### Cross-Chapter References Are Well-Chosen

The related recipes section connects to Recipe 8.1 (same chapter foundation), Recipe 2.1 (LLM alternative), Recipe 4.2 (downstream use of sentiment), and Recipe 10.2 (voice-to-text feeding this pipeline). These create useful navigation paths for readers with different starting points.

### The Honest Take Section Is Authentic

"The demo looks amazing and production looks humbling" is exactly right. The advice about aggregate trends surviving individual errors, and the guidance about who should see raw comments versus aggregated themes, demonstrates real operational experience. This section alone justifies the cookbook's existence over generic documentation.

### Cost Estimate Methodology Is Good (With the Endpoint Fix)

Once the endpoint hosting cost is added, the cost breakdown is well-structured: per-unit costs for each service, a monthly total at stated volume, and implicit scaling behavior. This is the right level of detail for architectural planning.

---

## Priority Actions Before Publication

1. **Fix A1:** Add endpoint hosting to cost estimate. The $360/month gap between stated and actual cost is significant for budget planning.

2. **Fix N1:** List Comprehend Medical as a separate VPC endpoint. Without this, VPC-deployed PHI detection Lambda will fail.

3. **Fix S1:** Specify per-Lambda IAM roles with resource-scoped permissions. The PHI boundary between raw and redacted S3 buckets is the recipe's core security design; IAM should enforce it.

4. **Fix S2, A2, S3:** Data lifecycle, DLQ, and alert payload guidance are compliance and reliability improvements that strengthen the recipe without changing the architecture.

5. **Fix A3:** Training data requirements in Prerequisites give builders realistic expectations for the custom classifier investment.

The remaining findings (N2, S4, A4, V3) improve precision but don't block a competent builder.

---

*Review complete. Recipe 8.2 is a well-crafted recipe that teaches sentiment analysis fundamentals effectively while providing a practical, PHI-aware AWS implementation. The findings are refinements to an already-solid foundation. The educational content, particularly the healthcare-specific sentiment challenges section, is among the best in the cookbook so far.*
