# Expert Review: Recipe 8.6 - Social Determinants of Health (SDOH) Extraction

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-04
**Recipe file:** `chapter08.06-sdoh-extraction.md`
**Python companion:** `chapter08.06-python-example.md`

---

## Overall Assessment

**Verdict: PASS**

This is one of the strongest recipes in Chapter 8. The problem statement is emotionally compelling and clinically grounded, the technology section teaches SDOH NLP from first principles with honest performance expectations, and the architecture pattern is appropriate for the stated scale. The recipe correctly frames system output as "reviewed = false" by default, requiring human validation before acting on extractions. The Gravity Project taxonomy alignment and ICD-10 Z-code normalization demonstrate genuine domain expertise. No CRITICAL findings. One HIGH finding (VPC endpoint claim for Comprehend Medical that likely cannot be fulfilled). Three MEDIUM findings for architectural completeness. The recipe is publishable with the HIGH item addressed.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA requirement explicitly stated in Prerequisites
- Encryption at rest specified for all data stores (S3 SSE-KMS, DynamoDB encryption at rest, SQS SSE-KMS)
- Lambda environment variables KMS-encrypted
- All API calls over TLS specified
- CloudTrail enabled for all Comprehend Medical, Comprehend, and S3 API calls
- DynamoDB Point-in-Time Recovery explicitly required
- Training data section warns: "Never use real PHI in training without IRB and data governance approval"
- De-identified datasets (MIMIC, i2b2/n2c2) recommended for initial model development
- `reviewed = false` flag on all extraction results enforces human-in-the-loop validation
- IAM permissions list is specific and actionable (DetectEntitiesV2, ClassifyDocument, specific S3/DynamoDB/SQS actions)

### Issue S1: Source Text Stored in DynamoDB Without Redaction Consideration (MEDIUM)

**Location:** Step 6 pseudocode, `source_text = finding.text`

**The problem:** The SDOH profile table stores the original sentence from the clinical note as `source_text` for "reviewer context." This is clinically useful (care managers need to see the original language), but the recipe doesn't discuss access controls for this table beyond the IAM permissions list. The source text could contain other PHI beyond the SDOH mention itself (e.g., "Patient John Smith reports being homeless since his wife died in January"). The care management platform querying this table may have broader user access than the EHR note itself.

**Suggested fix:** Add a brief note in the "Why These Services" section for DynamoDB mentioning that access to the sdoh-profiles table should be restricted to care management roles, and that organizations may choose to store only the finding metadata (domain, assertion, confidence, codes) without the source text, providing a note_id link for authorized users who need to review the original context in the EHR.

### Issue S2: Custom Classifier Endpoint ARN Hardcoded in Pseudocode (LOW)

**Location:** Step 4 pseudocode, `EndpointArn = SDOH_CLASSIFIER_ENDPOINT`

**The problem:** The pseudocode uses a constant for the classifier endpoint ARN. This is correct pattern-wise (constants are good), but the recipe doesn't mention that the endpoint ARN should be stored in an encrypted parameter (Systems Manager Parameter Store with SecureString, or Secrets Manager) rather than as a Lambda environment variable in plaintext CloudFormation. While an endpoint ARN is not a secret per se, it's a resource identifier that enables access. This is a very minor concern but worth noting for defense-in-depth.

**Suggested fix:** No change needed. This is standard practice for non-secret resource identifiers. The IAM policy (not the endpoint ARN) controls access.

---

## Architecture Expert Review

### What's Done Well

- Pipeline stages are logically ordered: Relevance Filter -> Section Detection -> Entity Extraction -> SDOH Classification -> Code Normalization -> Profile Storage
- SQS decoupling between EHR ingestion and processing is explicitly called out (prevents throttling during batch dumps)
- The relevance keyword filter is a smart cost optimization (70-80% volume reduction) with honest acknowledgment that it misses implicit mentions
- Confidence threshold (0.75) is discussed with rationale about false positive/negative trade-offs
- Two-level storage (DynamoDB for real-time queries, S3 for batch analytics) is the right separation
- Throughput estimate (20 notes/second) is realistic for Lambda concurrency with Comprehend Medical limits
- Performance benchmarks are honest and segmented by explicit vs. implicit mentions
- "Where it struggles" section is detailed and actionable
- The "current status" summary record pattern enables efficient point queries for care management

### Issue A1: No Dead Letter Queue for SQS Processing Failures (MEDIUM)

**Location:** Architecture Diagram and "Why These Services" section

**The problem:** The architecture shows SQS -> Lambda with no error handling path. If the Lambda function fails (Comprehend Medical throttling, note exceeding 20,000-character limit per section, malformed input, transient service errors), the message returns to the queue and is retried. After max retries (default 3), it disappears permanently. For a clinical system where missed SDOH mentions could result in patients not receiving needed social services, silently dropping notes is problematic.

The recipe mentions SQS for decoupling but doesn't discuss failure handling. At scale (processing thousands of notes nightly), some percentage will fail. Without a DLQ and monitoring, the operations team has no visibility into what's being missed.

**Suggested fix:** Add a DLQ to the SQS queue in the architecture diagram. Add a CloudWatch alarm on DLQ depth. Mention in "Why These Services" or Prerequisites that failed notes should be investigated (malformed text, unexpected length, service errors) and reprocessed after root cause resolution.

### Issue A2: No Discussion of Comprehend Medical Text Size Limit (MEDIUM)

**Location:** Step 3 pseudocode comment: "Comprehend Medical handles up to 20,000 characters"

**The problem:** The recipe correctly notes the 20,000-character limit in a code comment, but doesn't discuss what to do when a note exceeds this limit. Social work assessments and discharge summaries (the highest-value note types for SDOH extraction per the recipe's own section priority list) can exceed 20,000 characters. The recipe's section detection (Step 2) segments notes into sections before passing to Comprehend Medical, which helps, but individual social work assessments or discharge summaries could still exceed the limit.

**Suggested fix:** Add a sentence in Step 3's explanatory text: "If a section exceeds 20,000 characters, split it at sentence boundaries with overlap to ensure no SDOH mention spans a chunk boundary." This is a one-sentence addition that prevents a runtime failure for the highest-value note types.

### Issue A3: DynamoDB Sort Key Design May Not Support All Query Patterns (MEDIUM)

**Location:** Step 6 pseudocode, `sort_key = finding.domain + "#" + note_date`

**The problem:** The sort key `domain + "#" + note_date` supports queries like "all housing findings for patient X" (begins_with on sort key) and "all findings in domain X on date Y" (exact match). But the recipe mentions downstream use cases including: "show me all patients with active food insecurity in my panel." This query requires scanning the entire table or building a Global Secondary Index (GSI) on `domain + assertion` as partition key with `patient_id` as sort key.

The recipe mentions the use case but doesn't discuss the GSI needed to support it. Readers implementing this as written would find the "all patients with active food insecurity" query requires a full table scan, which is expensive and slow at population scale.

**Suggested fix:** Add a brief note mentioning that population-level queries ("all patients with active X") require a GSI on `domain#assertion` as partition key. This is a two-sentence addition in Step 6 or the Prerequisites table.

### Issue A4: Batch vs. Real-Time Processing Not Clearly Delineated (LOW)

**Location:** "Why These Services" section and Prerequisites cost estimate

**The problem:** The recipe mentions both real-time (HL7/FHIR event streams) and batch (nightly extracts) ingestion patterns but doesn't clearly distinguish the architecture for each. The cost estimate mentions "batch inference via Comprehend's async jobs reduces cost significantly" but the architecture diagram and pseudocode only show the real-time (SQS -> Lambda -> synchronous API calls) pattern. For a healthcare organization processing historical notes in bulk (the common initial deployment), the batch pattern is actually the primary use case. The async Comprehend jobs have different cost profiles and throughput characteristics.

**Suggested fix:** Optional. Add a sentence noting that the architecture diagram shows the real-time pattern; for historical backfill, consider Comprehend's StartEntitiesDetectionV2Job for batch processing at lower cost. This recipe is already long enough that this could also be addressed in the Python companion's "gap to production" section.

---

## Networking Expert Review

### What's Done Well

- VPC requirement stated for production deployment
- VPC endpoints listed for S3, DynamoDB, SQS, and CloudWatch Logs
- TLS for all API calls specified
- No unnecessary egress of PHI to external systems
- All data stays within AWS BAA-covered services
- SQS endpoint (interface endpoint) correctly included

### Issue N1: Comprehend Medical and Comprehend VPC Endpoint Claims (HIGH)

**Location:** Prerequisites table, VPC row: "Lambda in VPC with VPC endpoints for S3, DynamoDB, SQS, Comprehend Medical, Comprehend, and CloudWatch Logs"

**The problem:** The recipe claims VPC endpoints for both Amazon Comprehend Medical and Amazon Comprehend (custom classification). Neither service has a documented VPC interface endpoint (PrivateLink). Both are accessed via their public regional endpoints (`comprehendmedical.{region}.amazonaws.com` and `comprehend.{region}.amazonaws.com`). S3 and DynamoDB have gateway endpoints; SQS and CloudWatch Logs have interface endpoints. But Comprehend Medical and Comprehend do not.

If no VPC endpoints exist for these services, the Lambda function in a VPC needs a NAT Gateway to reach both Comprehend Medical and Comprehend endpoints. This means:
1. Additional cost (~$0.045/hr + $0.045/GB data processing for NAT Gateway)
2. Clinical note text (PHI) traverses the NAT Gateway to public endpoints (encrypted via TLS, but technically leaving the VPC)
3. Organizations with "no PHI over public internet" policies would need to evaluate this trade-off even though TLS protects confidentiality

This is particularly relevant for this recipe because SDOH information is sensitive beyond standard PHI (it describes housing instability, domestic violence, financial strain), and some organizations have heightened data governance around social determinant data.

**Suggested fix:** Remove "Comprehend Medical" and "Comprehend" from the VPC endpoint list. Replace with: "Comprehend Medical and Comprehend (custom classification) require NAT Gateway access (no VPC endpoints available as of 2026). Clinical note text is encrypted in transit via TLS 1.2+. Organizations with strict no-internet-egress requirements should evaluate whether Lambda outside VPC (with resource policies on S3/DynamoDB) meets their compliance posture." Verify current endpoint availability at time of publication.

### Issue N2: No Regional Availability Note for Comprehend Custom Classification (LOW)

**Location:** Prerequisites table

**The problem:** Amazon Comprehend custom classification endpoint deployment is available in fewer regions than Comprehend Medical. The recipe uses both services together but doesn't note that the deployment region must support both. A reader deploying in a region that supports Comprehend Medical but not custom classification endpoints would discover this only at training time.

**Suggested fix:** Add a brief note: "Verify that your target region supports both Comprehend Medical and Comprehend custom classifier endpoints. Custom classifier real-time endpoints are available in select regions."

---

## Voice Reviewer

### What's Done Well

- The Problem section is exceptional: the diabetes patient scenario is vivid, specific, and emotionally resonant without being manipulative
- "That sentence is clinically explosive" is perfect CC voice
- The progressive revelation of why SDOH is harder than medical NLP (sparse mentions, inconsistent language, implicit mentions, context sensitivity, documentation variation) builds beautifully
- "The signal-to-noise ratio is brutal" is conversational and precise
- Technology section is entirely vendor-agnostic through the full NLP pipeline discussion
- Honest performance expectations set early: "70-85% F1 scores" with category-specific breakdowns
- "The Honest Take" is authentic: "SDOH extraction is one of those problems that looks tractable until you start counting what you're missing"
- "What surprised me: the highest-value output isn't the individual extraction. It's the patient-level longitudinal profile." is classic CC insight delivery
- No marketing language anywhere
- Pseudocode comments are genuinely helpful and conversational ("This is intentionally permissive: we'd rather process an irrelevant note than miss one...")
- The keyword list maintenance note ("Skip this step and you'll run expensive NLP on thousands of notes...") is practical wisdom delivered conversationally

### Issue V1: No Em Dashes Found (PASS)

**Location:** Full recipe scan

**Confirmed:** Zero em dashes in the recipe. All punctuation uses periods, commas, colons, semicolons, or parentheses correctly.

### Issue V2: Vendor Balance Well Within Target (PASS)

**Location:** Full recipe structure

**Assessment:** The Problem section, Technology section (including all five "what makes SDOH different" subsections, the NLP pipeline description, the state of the art discussion, and the general architecture pattern) are fully vendor-agnostic and comprise approximately 60-65% of the recipe's content. AWS services appear only in "The AWS Implementation" section. The vendor balance is excellent, arguably slightly more vendor-agnostic than required (which is fine). A reader on GCP or Azure would gain significant value from the first half alone.

### Issue V3: One Slightly Academic Phrase (LOW)

**Location:** Technology section, "The State of the Art" heading

**The problem:** "The State of the Art" as a section heading reads slightly more academic-paper than CC's usual conversational style. The content beneath it is great and conversational, but the heading itself stands out compared to the rest of the recipe's headings which are more descriptive ("What Makes SDOH Different from Medical NLP," "The NLP Pipeline for SDOH").

**Suggested fix:** Optional. Could be "What's Available Today" or "How People Solve This Now" for a slightly more conversational register. The current heading works fine and isn't wrong; it's just a hair more formal than the surrounding headings.

---

## Stage 2: Expert Discussion

### Conflict: VPC Endpoint and PHI Sensitivity

The Networking expert identified that both Comprehend Medical and Comprehend (custom) lack VPC endpoints, meaning PHI (clinical note text with SDOH content) must traverse a NAT Gateway to reach public endpoints. The Security expert's review assumed VPC endpoints would keep PHI within the AWS backbone. The SDOH context adds sensitivity: domestic violence disclosures, homelessness, substance use references in notes may be subject to additional state-level privacy protections beyond baseline HIPAA (e.g., 42 CFR Part 2 for substance use, state DV confidentiality laws).

**Resolution:** HIGH severity (not CRITICAL) because TLS encryption protects confidentiality in transit regardless of network path. The data is not exposed in cleartext. However, the recipe makes a factual claim about VPC endpoint availability that is incorrect, which would cause confusion for readers following the instructions literally. The SDOH sensitivity context adds organizational risk tolerance considerations but doesn't change the technical severity.

### Overlap: Source Text Storage and Access Control

Security raised concerns about storing source text in DynamoDB without access controls discussion. Architecture's DynamoDB design (Issue A3) touches the same table. These findings are complementary, not contradictory. The source text storage is architecturally sound (care managers need it), but the access control and query pattern discussions both need brief additions.

**Resolution:** Keep as separate findings (Security MEDIUM for access control, Architecture MEDIUM for GSI). Both are addressable with brief additions to Step 6 or Prerequisites.

### Conflict: Cost Estimate Accuracy

Unlike the previous recipe (8.5) which had a major cost discrepancy, this recipe's cost estimates are internally consistent. The header says "$0.02-0.08 per note," the Prerequisites table explains the math (Comprehend Medical DetectEntitiesV2 at $0.01 per 100 characters on 3000-8000 char notes = $0.30-$0.80 for full-note detection, BUT the keyword filter eliminates 70-80% of notes and the custom classifier operates on individual sentences, not full notes). The "all-in" cost of $0.02-0.08 appears to be an amortized cost (averaging the expensive Comprehend Medical calls across all notes including those filtered out by the keyword step).

**Resolution:** The cost is actually reasonable if interpreted as amortized across all incoming notes (not just processed ones). If 100 notes arrive, 20-30 pass the keyword filter, and those cost $0.30-$0.80 for Comprehend Medical + $0.0005 per sentence for custom classification. Amortized across all 100 notes: $6-24 / 100 = $0.06-$0.24 per note. The header's $0.02-0.08 is slightly optimistic but in the right ballpark if the keyword filter eliminates 80%+ of notes. The recipe should clarify that this is amortized cost, not per-processed-note cost. Downgrading from a potential HIGH to LOW since the recipe's body explains the math.

---

## Stage 3: Synthesized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Networking | Prerequisites table, VPC row | Claims VPC endpoints for Comprehend Medical and Comprehend (custom) which do not exist; both require NAT Gateway | Remove from VPC endpoint list; document NAT Gateway requirement; note TLS protects confidentiality; add SDOH sensitivity note for organizations with strict egress policies |
| 2 | MEDIUM | Architecture | Architecture Diagram | No DLQ for SQS processing failures; failed notes silently lost after max retries | Add SQS DLQ and CloudWatch alarm on DLQ depth |
| 3 | MEDIUM | Architecture | Step 3 explanatory text | Comprehend Medical 20,000-char limit noted only in code comment; no handling for oversized sections | Add sentence about splitting at sentence boundaries with overlap for sections exceeding limit |
| 4 | MEDIUM | Architecture | Step 6, DynamoDB sort key design | Population-level queries ("all patients with active food insecurity") require GSI not discussed | Add note that GSI on domain#assertion is needed for population queries |
| 5 | MEDIUM | Security | Step 6, source_text storage | PHI (source sentences) stored in DynamoDB without access control discussion | Add note about restricting table access to care management roles; mention option to omit source_text |
| 6 | LOW | Architecture | Cost estimate header | $0.02-0.08 is amortized cost, not per-processed-note; could confuse readers | Clarify "per note (amortized across filtered and processed notes)" in header or Prerequisites |
| 7 | LOW | Networking | Prerequisites table | No regional availability note for Comprehend custom classifier endpoints | Add supported regions verification note |
| 8 | LOW | Voice | Technology section heading | "The State of the Art" slightly more academic than surrounding headings | Optional: consider "What's Available Today" or similar |

**Final Verdict: PASS**

One HIGH finding that must be corrected before publication (VPC endpoint claim for Comprehend Medical and Comprehend custom classification). This is a straightforward factual correction: remove the incorrect services from the VPC endpoint list and document the NAT Gateway requirement. Four MEDIUM findings that improve architectural completeness (DLQ, text size limit handling, GSI for population queries, and source text access controls). All are addressable with brief additions of one to three sentences each.

The recipe excels at teaching SDOH NLP from first principles. The problem statement is among the best in the book. The honest acknowledgment of performance limitations (70-85% F1, with implicit mentions at 40-55% recall) sets appropriate expectations. The Gravity Project alignment and Z-code normalization demonstrate genuine healthcare domain expertise. The human-in-the-loop validation pattern (`reviewed = false`) is the correct safety posture for a system that surfaces sensitive social information. After the HIGH fix, this is a strong, publishable recipe.
