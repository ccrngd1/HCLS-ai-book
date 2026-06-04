# Expert Review: Recipe 8.5 - Problem List Extraction

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-04
**Recipe file:** `chapter08.05-problem-list-extraction.md`
**Python companion:** `chapter08.05-python-example.md`

---

## Overall Assessment

**Verdict: PASS**

This is an excellent recipe. The clinical problem statement is vivid and well-motivated, the technology section teaches NER and assertion detection from first principles without vendor lock-in, and the pipeline architecture is logically sound with clear separation of concerns. The "clinician-in-the-loop" framing for reconciliation is the correct clinical safety posture. The recipe correctly positions this as recommendation generation, not autonomous documentation. No CRITICAL findings. Two HIGH findings (cost estimate discrepancy between header and body, and a VPC endpoint claim that likely cannot be fulfilled). Four MEDIUM findings for architectural completeness. The recipe is publishable with the HIGH items addressed.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA requirement explicitly stated in Prerequisites
- Encryption at rest specified for all data stores (S3 SSE-KMS, DynamoDB encryption at rest)
- CloudWatch log group KMS encryption called out with correct rationale (logs may contain extracted clinical data)
- CloudTrail audit logging required for HIPAA compliance
- VPC requirement stated for production deployment
- Sample data section warns "Never use real patient notes in dev without proper IRB/DUA"
- The reconciliation output is "PENDING_REVIEW" status by default, enforcing human-in-the-loop
- No auto-modification of clinical data without physician review (explicitly stated in "The Honest Take")

### Issue S1: IAM Permissions Missing `dynamodb:UpdateItem` Usage Context (LOW)

**Location:** Prerequisites table, IAM Permissions row

**The problem:** The IAM permissions list includes `dynamodb:UpdateItem` but the pseudocode in Steps 5-6 only shows `PutItem`-style writes (new records to "problem-list-recommendations" table). The `UpdateItem` permission is presumably for when a clinician accepts/rejects a recommendation and the status changes from "PENDING_REVIEW" to "ACCEPTED" or "REJECTED," but this workflow isn't shown in the pseudocode. This is not wrong (it's forward-looking), but the disconnect between documented permissions and demonstrated operations could confuse readers constructing least-privilege policies.

**Suggested fix:** Add a brief comment in the Prerequisites table noting that `UpdateItem` is used by the downstream clinician review workflow (not shown in this recipe's pipeline code).

### Issue S2: DynamoDB Patient Problem Table Access Pattern Not Scoped (LOW)

**Location:** Step 5 pseudocode, reconciliation function

**The problem:** The reconciliation function queries DynamoDB for `patient_id where status == "ACTIVE"`. This implies the Lambda function has broad query access to the patient-problems table. In a multi-tenant or large-scale deployment, the IAM policy should scope access using condition keys or resource-level ARNs. The recipe doesn't mention this, which is typical for a cookbook recipe (not a production deployment guide), but worth noting for the "gap to production" context.

**Suggested fix:** No change required for the recipe itself. The Python companion's "gap to production" section should mention least-privilege scoping if it doesn't already.

---

## Architecture Expert Review

### What's Done Well

- Pipeline stages are logically ordered: Section Detection -> Problem NER -> Assertion Classification -> Terminology Normalization -> Reconciliation -> Storage
- The two-table approach (S3 for full audit trail, DynamoDB for actionable recommendations) is the right separation
- Step Functions for batch backfill is correctly separated from real-time Lambda processing
- The reconciliation logic covers three valuable scenarios: add candidates, resolve candidates, and specificity upgrades
- The SNOMED hierarchy traversal for specificity upgrades (`is_child_of`) is architecturally correct
- Throughput estimate (30 notes/second) is realistic for Lambda concurrency with Comprehend Medical API limits
- The "Where it struggles" section is honest and actionable

### Issue A1: Cost Estimate Header vs. Body Discrepancy (HIGH)

**Location:** Header line ("~$0.002-0.01 per note") vs. Prerequisites table ("A typical 3000-character note: ~$0.60 for detection + $0.05-0.20 for normalization calls per extracted problem") vs. Performance benchmarks ("Cost per note: ~$0.30-0.80")

**The problem:** The header claims $0.002-0.01 per note. The Prerequisites table calculates ~$0.60 for DetectEntitiesV2 alone on a 3000-character note. The Performance benchmarks table says $0.30-0.80 per note. The header is off by 30-100x from the body calculations.

Working the math: Comprehend Medical DetectEntitiesV2 prices at ~$0.01 per 100-character unit (1 unit = 100 chars, minimum 3 units per request). A 3000-character note = 30 units * $0.01 = $0.30 for detection. The Prerequisites table says $0.60, which may account for calling multiple APIs (DetectEntitiesV2 + InferICD10CM + InferSNOMEDCT on the full note text) or may be using outdated pricing. InferICD10CM and InferSNOMEDCT are called per extracted problem text (not the full note), so those are much smaller: a 30-char problem mention = 1 unit * $0.01 = $0.01 per problem per API.

Reasonable total: $0.30 (detection) + $0.02-0.10 (normalization for 1-5 problems, 2 APIs each) = $0.32-0.40 per note. The benchmarks' $0.30-0.80 range is plausible. The header's $0.002-0.01 is not.

**Suggested fix:** Update the header to "~$0.30-0.80 per note" to match the body calculations. Verify current Comprehend Medical pricing and make all three locations consistent. The Prerequisites table's $0.60 for detection alone seems high if using current pricing ($0.30 for a 3000-char note); clarify whether this includes all three API calls on the full text.

### Issue A2: No Dead Letter Queue or Error Handling Path (MEDIUM)

**Location:** Architecture Diagram and "Why These Services" section

**The problem:** The architecture shows a linear path: S3 Event -> Lambda -> Comprehend Medical -> DynamoDB/S3. No error handling path is shown. If the Lambda function fails (Comprehend Medical throttling during batch loads, malformed notes exceeding the 20,000-character API limit, transient service errors), the event is lost. For a clinical system where problem list gaps have patient safety implications, silently dropping notes is unacceptable.

**Suggested fix:** Add an SQS DLQ for Lambda invocation failures. Mention a CloudWatch alarm on DLQ depth so operations knows when notes are failing extraction. A single sentence in "Why These Services" and an additional box in the Mermaid diagram would suffice.

### Issue A3: No Idempotency Discussion for Reprocessing (MEDIUM)

**Location:** Step 6 (store_results) and DynamoDB design

**The problem:** If the same note triggers extraction twice (S3 event at-least-once delivery, manual reprocessing, or pipeline redeployment), the system creates duplicate recommendations in DynamoDB. The sort key uses `recommendation_id = generate unique ID` which would be different on each run. Clinicians would then see duplicate "ADD_CANDIDATE" recommendations for the same problem from the same note.

**Suggested fix:** Add a note that the `recommendation_id` should incorporate `note_id + snomed_code + type` to enable conditional writes (PutItem with condition `attribute_not_exists(recommendation_id)`). This makes reprocessing safe.

### Issue A4: Missing Discussion of Comprehend Medical Text Size Limit (MEDIUM)

**Location:** Code section (Step 2) and "Where it struggles"

**The problem:** Amazon Comprehend Medical DetectEntitiesV2 has a 20,000-character limit per request. The recipe processes notes by section, which helps (individual sections are typically under 20K), but doesn't explicitly handle the case where a single section exceeds the limit. Discharge summaries and operative notes can have individual sections over 20K characters. The previous recipe (8.4) apparently discussed this in its "Honest Take," but this recipe doesn't mention it at all.

**Suggested fix:** Add a note in Step 2's text that sections exceeding 20,000 characters need chunking with overlap. Alternatively, mention the limit in "Where it struggles" with a note that long sections need splitting at sentence boundaries.

### Issue A5: Reconciliation Logic Assumes Single-Code Matching (MEDIUM)

**Location:** Step 5, reconciliation pseudocode

**The problem:** The reconciliation checks `IF extracted.snomed[0].Code not in current_list codes`. This uses only the top-1 SNOMED code for matching. But the normalization step returns top-3 candidates. If the existing problem list uses a different (but semantically equivalent) SNOMED code that happens to be the model's #2 or #3 candidate, the reconciliation will generate a false "ADD_CANDIDATE" recommendation for a problem already on the list under a slightly different code.

Example: The problem list has "Essential hypertension" (38341003). The note says "high blood pressure" which normalizes to top-1: "High blood pressure" (38341003) but could also return top-1: "Hypertensive disorder" (59621000) depending on the text. If the top-1 doesn't match, you'd recommend adding what's already there.

**Suggested fix:** Check all top-3 candidates against the existing problem list, or implement SNOMED hierarchy-aware matching (check if any candidate is an ancestor/descendant of an existing list item). The recipe already mentions `is_child_of` for specificity upgrades; extend this concept to deduplication.

---

## Networking Expert Review

### What's Done Well

- VPC requirement stated for production
- VPC endpoints listed for S3, DynamoDB, and CloudWatch Logs
- TLS for all API calls specified
- No unnecessary egress of PHI to external systems
- All data stays within AWS services covered by the BAA

### Issue N1: Comprehend Medical VPC Endpoint Claim Likely Invalid (HIGH)

**Location:** Prerequisites table, VPC row: "Lambda in VPC with VPC endpoints for S3, Comprehend Medical, DynamoDB, and CloudWatch Logs"

**The problem:** The recipe claims a VPC endpoint should be used for Comprehend Medical. Amazon Comprehend Medical does not have a documented VPC interface endpoint (PrivateLink). The service is accessed via its public regional endpoint (`comprehendmedical.{region}.amazonaws.com`). S3 and DynamoDB have gateway endpoints, CloudWatch Logs has an interface endpoint, but Comprehend Medical's VPC endpoint availability is not documented in AWS's current VPC endpoint service list.

If no VPC endpoint exists, the Lambda function in a VPC needs a NAT Gateway to reach Comprehend Medical. This means: (1) additional cost (~$0.045/hr + data processing charges), (2) the clinical note text traverses the NAT Gateway to a public endpoint (encrypted via TLS, but technically leaving the VPC). For organizations with "no PHI egress to public internet" policies, this is a compliance discussion point even though TLS protects confidentiality.

**Suggested fix:** Remove "Comprehend Medical" from the VPC endpoint list. Add: "Comprehend Medical requires NAT Gateway access (no VPC endpoint available). Clinical text is encrypted in transit via TLS. Alternatively, run Lambda outside VPC for simplicity (S3 and DynamoDB access can use resource policies, CloudWatch Logs has interface endpoint)." Verify current endpoint availability at time of publication.

### Issue N2: No Regional Availability Note (LOW)

**Location:** Prerequisites table

**The problem:** Amazon Comprehend Medical is not available in all AWS regions. Healthcare organizations with data residency requirements (Canadian data in ca-central-1, EU data in eu-west-1) need to know which regions support the service. A reader deploying in an unsupported region would discover this only at runtime.

**Suggested fix:** Add a brief note: "Verify Comprehend Medical availability in your target region. The service is available in select regions (us-east-1, us-east-2, us-west-2, eu-west-1, eu-west-2, ap-southeast-2, ca-central-1 as of 2024)."

---

## Voice Reviewer

### What's Done Well

- The Problem section is outstanding: the specific patient scenario (diabetes, hypertension, CKD, depression, resolved pneumonia) immediately grounds the reader in clinical reality
- Statistics are cited naturally ("sensitivity for known diagnoses ranging from 40-70%")
- The Technology section is entirely vendor-agnostic through the full NER, assertion classification, and normalization discussion
- "The Honest Take" section is authentic and practically useful, especially the insight about section detection's outsized impact
- Parenthetical asides used well: "(ok, this is a gross oversimplification, but stay with me)" energy throughout
- No documentation-voice detected anywhere
- No marketing language
- The progressive build of negation complexity (simple -> distant -> implicit -> double -> negation of negation) is excellent teaching
- Cross-references to other recipes are natural and informative

### Issue V1: No Em Dashes Found (PASS)

**Location:** Full recipe scan

**Confirmed:** Zero em dashes in the recipe. All punctuation uses periods, commas, colons, semicolons, or parentheses correctly.

### Issue V2: Vendor Balance Well Within Target (PASS)

**Location:** Full recipe structure

**Assessment:** The Technology section (NER, assertion classification, negation detection, terminology normalization, general architecture pattern) is substantial and fully vendor-agnostic, comprising approximately 65-70% of the recipe's educational content. AWS services appear only in "The AWS Implementation" section (Part 2). The pseudocode references `ComprehendMedical` by name but is correctly placed within the AWS section. This maintains the 70/30 balance.

### Issue V3: Minor Prose Consideration (LOW)

**Location:** The Problem section, final paragraph

**The problem:** "That extraction and classification problem is what we're solving here." This sentence is slightly more summary/thesis-statement than the conversational voice typically uses. It's not documentation-voice, but it's a hair more structured than CC's usual style of just launching into the technology explanation. Very minor.

**Suggested fix:** Optional. Could be trimmed to let the technology section speak for itself, or could be rewritten as something more conversational like "So that's the gap we're filling." But the current version works fine.

---

## Stage 2: Expert Discussion

### Conflict: VPC Endpoint and Security Posture

The Networking expert identified that Comprehend Medical likely lacks a VPC endpoint, meaning PHI (clinical note text) must traverse a NAT Gateway to reach the public Comprehend Medical endpoint. The Security expert's review assumed VPC endpoints would keep PHI within the AWS backbone. 

**Resolution:** This is HIGH severity (not CRITICAL) because TLS encryption protects confidentiality in transit regardless of network path. The data is not exposed in cleartext. However, the recipe makes a factual claim about VPC endpoint availability that appears incorrect, which would cause deployment failures for readers following the instructions literally. Organizations with strict "no internet egress for PHI" policies would need to evaluate this trade-off. The recipe should accurately document the actual network path.

### Conflict: Cost Estimate Severity

The Architecture expert flagged the cost header discrepancy as HIGH. Could this be CRITICAL? Unlike Recipe 8.4 where the discrepancy was 50-100x, here the discrepancy is 30-80x (header $0.002-0.01 vs. body $0.30-0.80). The magnitude is similar.

**Resolution:** HIGH is the correct severity rather than CRITICAL. The body of the recipe provides correct, detailed cost calculations that a careful reader would find. The header is misleading but the recipe self-corrects in the Prerequisites and Performance tables. A reader who only reads the header to estimate budget would be misled, but one who reads the full Prerequisites table would catch the real numbers. Still, headers should be accurate. HIGH mandates correction before publication.

### Overlap: Reconciliation Accuracy

Both Architecture and Voice reviewers noted the reconciliation logic. Architecture found a technical gap (single-code matching misses semantic equivalents). The clinical accuracy concern is real: generating "ADD_CANDIDATE" recommendations for problems already on the list (just coded differently) would erode clinician trust in the system. This reinforces the Architecture finding as MEDIUM (trust erosion, not patient harm).

---

## Stage 3: Synthesized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Architecture | Header vs. Prerequisites vs. Benchmarks | Cost estimate discrepancy: header says $0.002-0.01/note, body says $0.30-0.80/note (30-80x off) | Update header to ~$0.30-0.80/note; verify and harmonize all three cost locations |
| 2 | HIGH | Networking | Prerequisites table, VPC row | Claims VPC endpoint for Comprehend Medical which likely does not exist | Remove from VPC endpoint list; document NAT Gateway requirement with TLS note |
| 3 | MEDIUM | Architecture | Architecture Diagram | No DLQ or error handling for failed Lambda executions | Add SQS DLQ and CloudWatch alarm on DLQ depth |
| 4 | MEDIUM | Architecture | Step 6, DynamoDB design | No idempotency for note reprocessing; duplicates possible | Use deterministic recommendation_id based on note_id + snomed_code + type |
| 5 | MEDIUM | Architecture | Step 2 and "Where it struggles" | No mention of Comprehend Medical 20,000-char limit per request | Add chunking note for oversized sections |
| 6 | MEDIUM | Architecture | Step 5, reconciliation logic | Single top-1 code matching misses semantic equivalents already on list | Check top-3 candidates or use SNOMED hierarchy-aware deduplication |
| 7 | LOW | Networking | Prerequisites table | No mention of Comprehend Medical regional availability | Add supported regions note |
| 8 | LOW | Security | Prerequisites table, IAM Permissions | UpdateItem permission listed but not used in shown pseudocode | Add note that UpdateItem supports downstream review workflow |
| 9 | LOW | Voice | The Problem section, final paragraph | Slightly thesis-statement sentence style | Optional: make more conversational |

**Final Verdict: PASS**

Two HIGH findings that must be corrected before publication (cost header discrepancy and VPC endpoint claim), but no CRITICAL findings. Both HIGH items are straightforward factual corrections: update the cost header to match the body calculations, and fix the VPC endpoint claim to accurately document the NAT Gateway requirement. The recipe is architecturally sound, clinically accurate in its framing, properly positions the system as recommendation-only (no autonomous problem list modification), and teaches the underlying NLP concepts thoroughly before introducing AWS services. After the two HIGH fixes, this is a strong recipe.
