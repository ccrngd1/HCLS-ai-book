# Expert Review: Recipe 2.3 - Clinical Documentation Improvement Suggestions

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-06
**Recipe file:** `chapter02.03-clinical-documentation-improvement.md`

---

## Overall Assessment

This is a strong recipe. The clinical context is excellent, the CDI domain is explained with genuine depth, and the RAG architecture pattern is well-motivated. The "Honest Take" section is one of the best in the book so far: the insight about suggestion phrasing mattering more than accuracy is the kind of hard-won production wisdom that makes this cookbook valuable. The recipe correctly frames CDI as a documentation accuracy problem rather than a revenue optimization tool, which is both clinically appropriate and compliance-safe.

However, there are security gaps around IAM scoping and PHI handling in prompts, an architectural concern about the synchronous Lambda pattern at scale, and a missing VPC endpoint that would break production deployments. No critical findings, but several high-severity items that need attention before publication.

Priority breakdown: 0 critical, 3 high, 4 medium, 3 low.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA requirement is explicitly stated in prerequisites. Correct.
- SSE-KMS encryption for S3 is specified. Correct.
- CloudTrail logging for Bedrock invocations is mentioned. Correct.
- The recipe correctly notes that suggestions must be phrased as questions, not assertions, which is both a compliance and a clinical safety requirement.
- Synthetic data warning is present ("Never use real patient notes in development").
- DynamoDB encryption at rest is noted (though see finding below).

### Finding 1: PHI Sent to LLM Without Data Minimization Guidance

- **Severity:** HIGH
- **Expert:** Security
- **Location:** Step 2 (Extract Clinical Elements) and Step 4 (Generate CDI Suggestions), pseudocode
- **Problem:** The full clinical note content is sent to Bedrock in both Step 2 and Step 4. The recipe provides no guidance on data minimization. Clinical notes contain PHI beyond what's needed for CDI analysis: patient names, dates of birth, SSNs (occasionally in older systems), addresses, and other Safe Harbor identifiers. While Bedrock under BAA is HIPAA-eligible, the principle of minimum necessary applies. Sending the full unredacted note when only the clinical content is needed for gap analysis violates minimum necessary standards that many compliance programs enforce.
- **Fix:** Add a note (in the "Why This Isn't Production-Ready" section or as a comment in Step 2) that production implementations should consider de-identifying or redacting non-clinical PHI (patient name, DOB, MRN) before sending to the LLM. The CDI analysis doesn't need the patient's name to identify a specificity gap in the pneumonia documentation. Reference Amazon Comprehend Medical's `DetectPHI` API or regex-based redaction as pre-processing options.

### Finding 2: IAM Permissions Not Scoped to Specific Resources

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Prerequisites table, "IAM Permissions" row
- **Problem:** The IAM permissions listed (`bedrock:InvokeModel`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, etc.) are listed without resource ARN scoping. A reader implementing these permissions as-is will grant the Lambda role access to all S3 buckets, all DynamoDB tables, and all Bedrock models in the account. This violates least-privilege.
- **Fix:** Add resource-level scoping examples or a note: "Scope `s3:*` actions to the specific bucket ARN (`arn:aws:s3:::your-cdi-bucket/*`). Scope `dynamodb:*` actions to the specific table ARN. Scope `bedrock:InvokeModel` to the specific model ARN (`arn:aws:bedrock:*::foundation-model/anthropic.claude-3-sonnet*`). Scope `bedrock:Retrieve` to the specific knowledge base ARN."

### Finding 3: DynamoDB Encryption Described as "Default" Without CMK Specification

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Prerequisites table, "Encryption" row
- **Problem:** The recipe states "DynamoDB: encryption at rest (default)." AWS default DynamoDB encryption uses AWS-owned keys, which do not appear in CloudTrail and cannot be revoked. For PHI data (CDI suggestions contain diagnosis text, clinical evidence quotes, and encounter IDs), many HIPAA compliance programs require customer-managed KMS keys (CMK) for auditability and key lifecycle control.
- **Fix:** Change to "DynamoDB: encryption at rest with customer-managed KMS key" to match the S3 SSE-KMS approach. Add the KMS key ARN to the IAM permissions list (`kms:Decrypt`, `kms:GenerateDataKey` scoped to the CMK).

### Finding 4: Suggestion Expiration Without Secure Deletion

- **Severity:** LOW
- **Expert:** Security
- **Location:** Step 6 pseudocode, `expires_at = current timestamp + 72 hours`
- **Problem:** Suggestions expire after 72 hours but the recipe doesn't address what happens to expired items. DynamoDB TTL deletes items eventually (within 48 hours of expiration, not immediately). During that window, expired suggestions containing clinical content remain queryable. For audit purposes this may be fine, but the recipe should explicitly state whether expired suggestions should be retained (for audit trail) or deleted (for data minimization).
- **Fix:** Add a brief note: "DynamoDB TTL can auto-delete expired suggestions, but consider retaining them in a cold archive (S3 Glacier) for audit trail purposes. Your data retention policy should specify how long CDI suggestions are kept."

---

## Architecture Expert Review

### What's Done Well

- The RAG pattern is well-motivated: using retrieved coding guidelines rather than relying on model training data for specificity rules is the correct architectural choice.
- The prioritization and filtering step (Step 5) addresses alert fatigue, which is the #1 operational risk for CDI systems.
- The feedback loop requirement is correctly identified in "Why This Isn't Production-Ready."
- Cost estimates are reasonable for the stated architecture ($0.02-0.08 per note for Bedrock inference).
- The separation between concurrent and retrospective CDI is clearly explained with appropriate complexity warnings.

### Finding 5: Single Lambda Doing All Work Creates Timeout and Debugging Risks

- **Severity:** HIGH
- **Expert:** Architecture
- **Location:** Architecture Diagram and overall pipeline design
- **Problem:** The architecture shows a single Lambda (`cdi-analyzer`) performing all six steps: note parsing, LLM extraction call, knowledge base retrieval (multiple queries per diagnosis), LLM suggestion generation call, prioritization, and DynamoDB writes. With multiple Bedrock API calls (each 2-5 seconds) and multiple knowledge base retrievals, this Lambda will routinely take 10-20 seconds. The recipe doesn't mention Lambda timeout configuration. Default timeout is 3 seconds. Even with increased timeout, a single Lambda doing sequential LLM calls is fragile: any single API timeout or throttle fails the entire pipeline with no partial progress saved.
- **Fix:** Either (a) add Lambda timeout configuration to prerequisites (recommend 60-90 seconds), or (b) recommend a Step Functions orchestration for production that separates extraction, retrieval, and generation into individual steps with retry logic per step. At minimum, add a note in "Why This Isn't Production-Ready" that production deployments should use Step Functions or SQS-based decomposition to handle partial failures gracefully. Also note that Lambda's 15-minute max timeout is sufficient, but the cost model changes for long-running functions.

### Finding 6: No Dead Letter Queue for Failed Processing

- **Severity:** HIGH
- **Expert:** Architecture
- **Location:** Architecture Diagram (S3 Event -> Lambda)
- **Problem:** If the Lambda fails (Bedrock throttling, timeout, malformed note), the S3 event notification is lost. There's no DLQ, no retry mechanism, and no visibility into which notes failed CDI analysis. At scale (hundreds of notes per day), silent failures mean missed CDI opportunities with no alerting.
- **Fix:** Add an SQS queue between S3 events and Lambda invocation, with a DLQ for failed messages. Alternatively, use S3 event -> SQS -> Lambda with a redrive policy (e.g., 3 retries before DLQ). Add a CloudWatch alarm on DLQ depth. Mention this in the architecture diagram or "Why This Isn't Production-Ready" section.

### Finding 7: Knowledge Base Query Strategy May Hit Retrieval Limits

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 3 pseudocode (retrieve_guidelines)
- **Problem:** The pseudocode queries the knowledge base once per diagnosis plus one template query. A note with 5 diagnoses generates 6 knowledge base retrieval calls. Each retrieval call adds latency (500ms-2s). More importantly, Bedrock Knowledge Bases has per-account TPS limits. A burst of notes (morning rounds, shift change) could throttle retrieval calls. The recipe doesn't address batching or caching of frequently-retrieved guidelines.
- **Fix:** Add a note suggesting: (1) batch common diagnoses into fewer, broader retrieval queries, (2) cache frequently-retrieved guideline sections (heart failure, pneumonia, diabetes specificity rules are queried constantly), and (3) implement exponential backoff on retrieval calls. A simple in-memory or ElastiCache layer for the top 50 diagnosis guidelines would eliminate most retrieval calls.

### Finding 8: No Idempotency Handling

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 6 (store_and_notify)
- **Problem:** If the same note triggers the pipeline twice (duplicate S3 events, EHR re-sends, or Lambda retry after partial failure), the system generates duplicate suggestions in DynamoDB. Each invocation generates new UUIDs, so there's no natural deduplication. CDI specialists would see the same suggestions twice in their workqueue.
- **Fix:** Add idempotency via a conditional DynamoDB write using `encounter_id + diagnosis` as a composite check, or use a DynamoDB conditional expression (`attribute_not_exists(encounter_id_diagnosis_hash)`) on the first write. Mention this in "Why This Isn't Production-Ready."

---

## Networking Expert Review

### What's Done Well

- VPC requirement is stated in prerequisites: "Production: Lambda in VPC with VPC endpoints for S3, Bedrock, DynamoDB, and CloudWatch Logs."
- TLS in transit is implied by all AWS SDK calls (HTTPS by default).

### Finding 9: Missing VPC Endpoint for Bedrock Agent Runtime (Knowledge Bases)

- **Severity:** MEDIUM
- **Expert:** Networking
- **Location:** Prerequisites table, "VPC" row
- **Problem:** The prerequisites mention VPC endpoints for "S3, Bedrock, DynamoDB, and CloudWatch Logs." However, Bedrock Knowledge Bases retrieval uses the `bedrock-agent-runtime` endpoint, which is a separate VPC endpoint from the `bedrock-runtime` endpoint used for model invocation. A reader who creates a VPC endpoint for `com.amazonaws.{region}.bedrock-runtime` but not `com.amazonaws.{region}.bedrock-agent-runtime` will have working model invocations but failing knowledge base retrievals when Lambda is in a VPC with no internet access.
- **Fix:** Explicitly list both VPC endpoints: `com.amazonaws.{region}.bedrock-runtime` (for InvokeModel) and `com.amazonaws.{region}.bedrock-agent-runtime` (for Knowledge Base Retrieve). Update the prerequisites VPC row to enumerate all required endpoints.

### Finding 10: No Egress Discussion for EHR Integration

- **Severity:** LOW
- **Expert:** Networking
- **Location:** "Why This Isn't Production-Ready" section, EHR integration paragraph
- **Problem:** The recipe mentions EHR integration (HL7 FHIR, ADT feeds) as the "hard part" but doesn't discuss the networking implications. EHR systems are typically on-premises or in a separate VPC. Receiving clinical notes from an EHR requires either AWS PrivateLink, VPN/Direct Connect, or an integration engine in a DMZ. PHI transiting between the EHR and AWS must stay encrypted and within controlled network paths. This is a significant architectural decision that deserves at least a sentence.
- **Fix:** Add a brief note in the EHR integration paragraph: "Network connectivity to your EHR (Direct Connect, Site-to-Site VPN, or PrivateLink) must be established with TLS encryption and restricted security groups. PHI should never traverse the public internet between your EHR and AWS, even encrypted."

---

## Voice Reviewer

### What's Done Well

- The opening problem statement is excellent. "Clinically, this is fine. The patient gets treated. But from a coding and reimbursement perspective, this note is a disaster." This is exactly the right voice: direct, slightly irreverent, immediately engaging.
- The technology section teaches CDI from first principles without assuming the reader knows what ICD-10-CM specificity means. Good.
- The "Honest Take" section is genuinely insightful and reads like hard-won experience, not documentation.
- The 70/30 vendor balance is well-maintained: the first half is entirely vendor-agnostic, AWS enters only in the implementation section.
- No marketing language detected. No "leverage," no "empower," no "seamless."

### Finding 11: One Em Dash Detected

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Related Recipes section, Recipe 7.3 entry
- **Problem:** "TODO: verify recipe number" is fine as a placeholder, but the text "Predicts DRG assignment, which CDI suggestions aim to improve through better documentation" is acceptable. However, scanning the full document, I found no em dashes (U+2014). The recipe uses colons, periods, and parentheses correctly throughout. Pass on em dashes.
- **Correction:** No em dashes found. This finding is withdrawn. Replacing with:

### Finding 11: Minor Doc-Voice Creep in One Sentence

- **Severity:** LOW
- **Expert:** Voice
- **Location:** "The Technology" section, paragraph 3 under "Why LLMs Work Here"
- **Problem:** "This dramatically reduces false-positive queries." The word "dramatically" is slightly hyperbolic/marketing-adjacent. The rest of the section maintains the measured, engineer-explaining tone well.
- **Fix:** Replace with "This significantly reduces false-positive queries" or better: "This cuts false-positive queries substantially" for a more conversational register.

---

## Stage 2: Expert Discussion

**Conflict: Security (data minimization) vs. Architecture (simplicity)**
The security expert recommends PHI redaction before sending notes to Bedrock. The architecture expert notes this adds a pre-processing step (Comprehend Medical DetectPHI or regex) that increases latency and cost. Resolution: the security concern wins for production, but the recipe should frame it as a production requirement rather than changing the pseudocode (which is pedagogical). Add it to "Why This Isn't Production-Ready."

**Overlap: Architecture (DLQ) and Networking (EHR integration)**
Both experts flag reliability concerns about the note ingestion path. The DLQ finding addresses Lambda-level failures; the networking finding addresses the EHR-to-S3 path. These are complementary, not conflicting. Both should be addressed.

**Priority alignment:** All experts agree the recipe's core CDI logic and RAG pattern are sound. The findings are primarily about production hardening (DLQ, idempotency, VPC endpoints) and security posture (IAM scoping, PHI minimization, CMK). The recipe's pedagogical value is high regardless of these gaps.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

The recipe is architecturally sound, clinically accurate, and well-written. The three HIGH findings are production-hardening gaps that should be addressed (either in the main architecture or in "Why This Isn't Production-Ready") but do not represent fundamental design flaws. The CDI domain expertise demonstrated is genuine and the RAG pattern is correctly applied.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| 1 | HIGH | Security | Steps 2 & 4 | PHI sent to LLM without data minimization guidance |
| 5 | HIGH | Architecture | Architecture Diagram | Single Lambda timeout risk; no timeout config mentioned |
| 6 | HIGH | Architecture | Architecture Diagram | No DLQ for failed note processing; silent failures |
| 2 | MEDIUM | Security | Prerequisites, IAM | IAM permissions not scoped to resource ARNs |
| 3 | MEDIUM | Security | Prerequisites, Encryption | DynamoDB encryption should specify CMK, not "default" |
| 7 | MEDIUM | Architecture | Step 3 pseudocode | Knowledge base query strategy lacks caching/batching |
| 8 | MEDIUM | Architecture | Step 6 pseudocode | No idempotency handling for duplicate events |
| 9 | MEDIUM | Networking | Prerequisites, VPC | Missing bedrock-agent-runtime VPC endpoint |
| 4 | LOW | Security | Step 6 pseudocode | Suggestion expiration without retention policy guidance |
| 10 | LOW | Networking | Production-Ready section | No egress/connectivity discussion for EHR integration |
| 11 | LOW | Voice | Technology section | Minor hyperbolic word choice ("dramatically") |

---

## Recommended Actions (Priority Order)

1. **Add Lambda timeout to prerequisites** (60-90 seconds) and note Step Functions as the production pattern for multi-LLM-call pipelines.
2. **Add DLQ architecture** (SQS between S3 event and Lambda, with redrive policy) either in the diagram or in "Why This Isn't Production-Ready."
3. **Add PHI minimization note** to "Why This Isn't Production-Ready": recommend redacting non-clinical PHI before LLM calls in production.
4. **Scope IAM permissions** in the prerequisites table with resource ARN examples or a note about least-privilege scoping.
5. **Change DynamoDB encryption** from "default" to "customer-managed KMS key" in prerequisites.
6. **Add `bedrock-agent-runtime` VPC endpoint** explicitly to the VPC prerequisites row.
7. **Add idempotency and caching notes** to "Why This Isn't Production-Ready" section.
8. **Add EHR network connectivity sentence** to the EHR integration paragraph.
9. **Replace "dramatically"** with a less hyperbolic word in the LLM advantages section.

---

## Notes for Editor

- The "TODO: verify recipe number" in Related Recipes (Recipe 7.3) needs resolution before publication.
- The AHIMA revenue loss statistic (1-5%) should be verified against a specific, citable source. The current reference is to AHIMA generally without a specific publication or year.
- The recipe is one of the longer ones in the book (~3,500 words). This is appropriate given the domain complexity, but the editor should verify it doesn't feel padded. (My assessment: it doesn't. The length is earned.)
