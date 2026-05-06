# Expert Review: Recipe 2.2 - Medical Terminology Simplification

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-06
**Recipe file:** `chapter02.02-medical-terminology-simplification.md`

---

## Overall Assessment

**Verdict: PASS**

This is a strong recipe. The problem statement is compelling and well-grounded in health literacy research. The technology section is genuinely educational, the architecture is sound for the stated complexity level (Simple/MVP), and the honest take section delivers on its promise. The entity validation pattern using Comprehend Medical is a smart safety layer that most simplification tutorials skip entirely.

That said, there are meaningful gaps: a missing KMS VPC endpoint that would break production deployments, an entity validation approach that has a significant blind spot the recipe doesn't fully acknowledge, and a Bedrock Guardrails service that appears in the Ingredients table but is never actually used in the architecture or code. No critical findings. Priority breakdown: 0 critical, 3 high, 4 medium, 3 low.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

- BAA requirement is explicitly stated in the prerequisites. Good.
- Encryption at rest (SSE-KMS for S3, DynamoDB encryption) and in transit (TLS) are specified.
- "Never use real patient documents in dev" is stated clearly.
- CloudTrail logging for Bedrock invocations and Comprehend Medical calls is required.
- The recipe correctly identifies that clinical text sent to Bedrock is PHI and must stay within the compliance perimeter.
- IAM permissions are listed with specific actions, not wildcards.

#### Issue S1: Missing KMS VPC Endpoint in Prerequisites (HIGH)

**Location:** Prerequisites table, VPC row.

**The problem:** The prerequisites list VPC endpoints for "Bedrock, Comprehend Medical, S3, DynamoDB, SQS, and CloudWatch Logs." KMS is not listed. When Lambda runs in a private subnet with no internet egress and S3 uses SSE-KMS, every S3 GetObject/PutObject requires a KMS API call to decrypt or generate the data key. Without a KMS VPC endpoint (`com.amazonaws.{region}.kms`), those calls have no route and the Lambda fails with an `AccessDeniedException` or timeout. This is the same issue identified in Recipe 1.3 and it applies identically here.

**Suggested fix:** Add `KMS` to the VPC endpoint list: "Lambda in VPC with VPC endpoints for Bedrock, Comprehend Medical, S3, DynamoDB, SQS, CloudWatch Logs, and KMS."

#### Issue S2: PHI Stored in DynamoDB Without Explicit Encryption Specification (MEDIUM)

**Location:** Prerequisites table, Encryption row; Ingredients table, DynamoDB row.

**The problem:** The Encryption row says "DynamoDB: encryption at rest (default)." AWS default DynamoDB encryption uses AWS-owned keys, not customer-managed keys. For PHI data under HIPAA, many compliance programs require customer-managed KMS keys (CMK) on all PHI stores for audit trail visibility and key revocation capability. The S3 configuration correctly specifies SSE-KMS, creating an inconsistency in the PHI encryption posture.

**Suggested fix:** Change to "DynamoDB: encryption at rest with customer-managed KMS key" to match the S3 approach. Add a brief note that CMK enables key usage auditing via CloudTrail and key revocation if needed.

#### Issue S3: Prompt Injection Risk Not Addressed (MEDIUM)

**Location:** Step 2 (Build the Simplification Prompt), specifically the user_prompt construction.

**The problem:** The clinical text is inserted directly into the user prompt between delimiter markers (`---`). If the clinical text contains adversarial content (unlikely from a legitimate EHR, but possible from user-submitted text in a patient portal), the model could be manipulated to ignore simplification constraints and produce harmful output. The recipe mentions Bedrock Guardrails in the Ingredients table but never shows how they're configured or applied. For a recipe that processes PHI and produces patient-facing output, the injection risk deserves at least a mention.

**Suggested fix:** Add a brief note in the "Failure Modes" section or "The Honest Take" acknowledging that input sanitization matters if the source text comes from user-submitted content (as opposed to structured EHR exports). Reference Bedrock Guardrails as the mitigation layer and either show its configuration or remove it from the Ingredients table if it's not actually part of this recipe's implementation.

#### Issue S4: No Mention of Data Retention Policy (LOW)

**Location:** Step 7 (Store Results).

**The problem:** The recipe stores both original clinical text and simplified versions in DynamoDB indefinitely. For PHI, data retention policies are a HIPAA requirement. There's no mention of TTL, lifecycle policies, or retention period considerations.

**Suggested fix:** Add a one-line note in Step 7 or the "Gap to Production" equivalent: "In production, configure DynamoDB TTL or a scheduled cleanup process aligned with your organization's PHI retention policy."

---

### Architecture Expert Review

#### What's Done Well

- The pipeline is well-structured: classify, generate, validate, score, gate, store. Each step has a clear purpose.
- The retry logic is sound: retry on readability failures (fixable), route to human on accuracy failures (not safely fixable by retry).
- The content type classification driving prompt selection is a good pattern that avoids one-size-fits-all prompting.
- The readability scoring as a computational check (not another LLM call) is the right choice for speed and determinism.
- Cost estimates are reasonable for the stated architecture ($0.01-0.04 per document).
- The "transformation task, not a generation task" framing is an important safety distinction that's well articulated.

#### Issue A1: Bedrock Guardrails Listed but Never Used (HIGH)

**Location:** Ingredients table lists "Amazon Bedrock Guardrails" with role "Content filtering and safety constraints on model output." Architecture diagram does not show Guardrails. Code walkthrough does not reference Guardrails. "Why These Services" section describes Guardrails but the implementation never applies them.

**The problem:** A reader following this recipe will set up Bedrock, Comprehend Medical, Lambda, DynamoDB, and SQS. They will not set up Guardrails because there's no step that uses them. The Ingredients table creates an expectation that isn't fulfilled. Either Guardrails is part of this recipe or it isn't.

**Suggested fix:** Either (a) add a Guardrails configuration step showing how to create a guardrail that blocks outputs containing clinical recommendations not in the source text, and reference the guardrail ID in the `generate_simplification` call, or (b) remove Bedrock Guardrails from the Ingredients table and "Why These Services" section, and instead mention it in "Variations and Extensions" as a production enhancement. Option (b) is simpler and more honest for an MVP-complexity recipe.

#### Issue A2: Entity Validation Blind Spot Understated (HIGH)

**Location:** Step 4 (Validate Accuracy), "The Honest Take" section.

**The problem:** The entity comparison approach has a fundamental limitation that the recipe acknowledges but underplays. Comprehend Medical extracts entities as text spans. The original says "myocardial infarction" and the simplified version says "heart attack." These are the same concept but different text. The pseudocode's `find_matching_entity` function is hand-waved without explaining how it handles synonyms. The Python companion uses substring matching, which will miss this case entirely.

The recipe says in "The Honest Take" that entity preservation is "a proxy for meaning preservation, not the same thing." True, but the bigger issue is that entity preservation itself doesn't work reliably when the whole point of the recipe is to replace medical terms with plain language equivalents. The validation step will flag "myocardial infarction" as missing from the simplified text because "heart attack" doesn't substring-match. This means the validation will produce false positives on every successful simplification of a medical term.

**Suggested fix:** Address this directly in Step 4. Acknowledge that the entity comparison will produce false positives when the model correctly replaces a medical term with its lay equivalent. Describe the mitigation: (1) maintain a medical synonym map for common term pairs, (2) use a secondary LLM call to verify semantic equivalence of flagged "missing" entities, or (3) focus validation on medications and dosages (where exact text preservation is expected) rather than conditions and procedures (where synonym substitution is the goal). The Python companion's "Gap to Production" section mentions this, but the main recipe's Step 4 should be upfront about it.

#### Issue A3: No Dead Letter Queue in Architecture Diagram (MEDIUM)

**Location:** Architecture diagram, Ingredients table.

**The problem:** SQS is listed in the Ingredients table with role "Dead letter queue for failed simplifications; human review queue." The architecture diagram shows a "Human Review Queue" node but no DLQ. The code walkthrough doesn't show DLQ configuration. For an MVP recipe this is acceptable, but the Ingredients table creates an expectation of DLQ handling that isn't delivered.

**Suggested fix:** Either add a DLQ path to the architecture diagram (Lambda failure routes to SQS DLQ) or simplify the SQS description in the Ingredients table to just "Human review queue for accuracy failures" and mention DLQ in "Variations and Extensions."

#### Issue A4: Readability Retry Prompt Doesn't Adjust System Prompt (LOW)

**Location:** Step 6 (Quality Gate), retry logic description.

**The problem:** The recipe says "retry with a more aggressive simplification prompt" but doesn't specify what changes. The Python companion appends extra instructions to the user prompt on retry, but the system prompt (which defines the target grade level) stays the same. A more effective retry would lower the target grade in the system prompt itself (e.g., from grade 6 to grade 4) rather than just adding "simplify further" to the user message.

**Suggested fix:** Add a brief note that retry prompts should adjust the target grade level in the system prompt, not just append instructions. This is a minor point but affects retry effectiveness.

---

### Networking Expert Review

#### What's Done Well

- VPC endpoints are listed for all services that handle PHI.
- The recipe correctly identifies that clinical text is PHI and cannot leave the compliance perimeter.
- CloudWatch Logs VPC endpoint is included (commonly missed).

#### Issue N1: Missing KMS VPC Endpoint (HIGH)

*Same as S1. See Security Expert Review. Cross-listed because it's both a security gap and a networking gap that will cause production failures.*

#### Issue N2: Interface vs. Gateway Endpoint Distinction Not Made (MEDIUM)

**Location:** Prerequisites table, VPC row.

**The problem:** The VPC row lists six services needing endpoints without distinguishing between gateway endpoints (S3, DynamoDB: free, route-table based) and interface endpoints (Bedrock, Comprehend Medical, SQS, CloudWatch Logs, KMS: billed per AZ per hour, require security groups). A reader setting up VPC endpoints for the first time will encounter different configuration screens and unexpected billing for interface endpoints.

**Suggested fix:** Add a parenthetical or footnote: "S3 and DynamoDB use gateway endpoints (free). Bedrock, Comprehend Medical, SQS, CloudWatch Logs, and KMS use interface endpoints (PrivateLink, ~$0.01/AZ/hour plus data processing)."

#### Issue N3: Bedrock VPC Endpoint Availability (LOW)

**Location:** Prerequisites table, VPC row.

**The problem:** Amazon Bedrock runtime VPC endpoints (`com.amazonaws.{region}.bedrock-runtime`) are available in most regions but this is relatively new. A reader deploying in a less common region should verify availability. Additionally, the endpoint name is not obvious (it's `bedrock-runtime`, not `bedrock`).

**Suggested fix:** Add a note in the prerequisites or "Why These Services" section: "The Bedrock VPC endpoint is `com.amazonaws.{region}.bedrock-runtime` (not `bedrock`). Verify availability in your target region."

---

### Voice Reviewer

#### What's Done Well

- The opening problem statement is excellent. The cardiac discharge example is vivid and immediately relatable. The progression from specific example to systemic problem to health outcome data is well-paced.
- The tone is consistently engineer-explaining-something-cool throughout. "What if you could take any piece of clinical text and automatically produce a patient-friendly version..." has the right energy.
- The technology section is genuinely educational and vendor-agnostic. A reader on GCP or Azure learns the concepts before seeing any AWS service names.
- "The Honest Take" delivers real self-deprecating expertise: "patients don't just want simpler words. They want structure."
- No documentation-voice detected. No "this recipe demonstrates how to leverage..." patterns.

#### Issue V1: No Em Dashes Found

Confirmed: zero em dashes in the recipe. Clean.

#### Issue V2: Vendor Balance Is Appropriate

The recipe is well-structured with clear vendor-agnostic sections (The Problem, The Technology, failure modes, readability scoring, general architecture pattern) followed by the AWS-specific implementation. Estimated split is approximately 65-70% vendor-agnostic, 30-35% AWS-specific. Within acceptable range.

#### Issue V3: Minor Tone Inconsistency in Step Descriptions (LOW)

**Location:** Code walkthrough, step introductions (bold paragraphs before each pseudocode block).

**The problem:** The step descriptions oscillate between two voices. Some are conversational and opinionated ("This is where the magic happens," "Skip this step and you'll get generic simplifications"). Others are more neutral and instructional ("Combine the validation result and readability score to make a pass/fail decision"). The conversational ones are better and match the style guide. The neutral ones read slightly more like documentation.

**Suggested fix:** Review Steps 5, 6, and 7 introductions and add a touch more personality. Not a major issue; the overall voice is strong.

---

## Stage 2: Expert Discussion

### Overlapping Concerns

1. **KMS VPC Endpoint (S1/N1):** Both Security and Networking experts independently flagged the missing KMS endpoint. This is the single most likely production-breaking gap in the recipe. A reader following the prerequisites exactly will have a non-functional pipeline if they use SSE-KMS on S3 (which the recipe tells them to do).

2. **Bedrock Guardrails phantom (A1/S3):** The Architecture expert flags Guardrails as listed-but-unused. The Security expert flags prompt injection risk and notes Guardrails as the stated mitigation that's never implemented. These are the same gap from different angles. Resolution: either implement Guardrails or remove it and acknowledge the gap.

3. **Entity validation false positives (A2):** This is the most architecturally significant finding. The validation step is designed to catch meaning loss, but it will also flag every successful synonym substitution as a "missing entity." This doesn't make the recipe wrong (the concept is sound), but the implementation guidance needs to be more honest about the false positive rate and how to handle it. Without this acknowledgment, a reader will deploy the pipeline, see 30-40% of simplifications flagged as "accuracy failures," and either (a) route everything to human review (defeating the purpose) or (b) disable validation (removing the safety net).

### Priority Resolution

The KMS endpoint is the highest-priority fix because it causes silent production failure. The Guardrails/entity-validation issues are high priority because they affect whether the recipe's stated architecture actually works as described. The DynamoDB encryption and data retention issues are medium priority compliance gaps that won't break functionality but matter for audit.

---

## Stage 3: Synthesized Findings

### Verdict: PASS

No critical findings. Three high findings (threshold for FAIL is more than 3). The recipe is publishable with the fixes below applied.

---

### Prioritized Fix List

#### HIGH (Fix Before Publication)

| ID | Finding | Expert | Location | Fix |
|----|---------|--------|----------|-----|
| S1/N1 | Missing KMS VPC endpoint. Will break S3 SSE-KMS operations in private subnet Lambda. | Security + Networking | Prerequisites table, VPC row | Add KMS to the VPC endpoint list. |
| A1 | Bedrock Guardrails listed in Ingredients and "Why These Services" but never used in architecture, diagram, or code. Creates false expectation. | Architecture | Ingredients table, "Why These Services" section | Either implement Guardrails in the pipeline (add to diagram and code) or move to "Variations and Extensions" as a production enhancement. Recommend the latter for MVP complexity. |
| A2 | Entity validation will produce false positives on every successful medical term simplification (e.g., "myocardial infarction" replaced with "heart attack" flagged as missing). The recipe doesn't address this. | Architecture | Step 4 (Validate Accuracy) | Add explicit acknowledgment that synonym substitution causes false positives. Describe mitigation options: synonym map, secondary LLM verification, or scoping validation to medications/dosages only. |

#### MEDIUM (Should Fix)

| ID | Finding | Expert | Location | Fix |
|----|---------|--------|----------|-----|
| S2 | DynamoDB uses "default" encryption while S3 uses CMK. PHI parity requires CMK. | Security | Prerequisites table, Encryption row | Specify customer-managed KMS key for DynamoDB. |
| S3 | Prompt injection risk unaddressed. Guardrails mentioned as mitigation but not implemented. | Security | Step 2, Failure Modes section | Add a note about input sanitization for user-submitted text sources. |
| N2 | Interface vs. gateway endpoint distinction not explained. Readers will encounter different setup flows and unexpected billing. | Networking | Prerequisites table, VPC row | Add parenthetical distinguishing free gateway endpoints (S3, DynamoDB) from billed interface endpoints (all others). |
| A3 | SQS DLQ listed in Ingredients but not shown in diagram or code. | Architecture | Ingredients table, Architecture diagram | Simplify Ingredients description to match what's actually implemented, or add DLQ to diagram. |

#### LOW (Improvement Recommendations)

| ID | Finding | Expert | Location | Fix |
|----|---------|--------|----------|-----|
| S4 | No data retention policy mentioned for PHI stored in DynamoDB. | Security | Step 7 | Add one-line note about TTL or retention policy alignment. |
| A4 | Retry logic doesn't adjust system prompt target grade level. | Architecture | Step 6 | Note that effective retries should lower the target grade in the system prompt. |
| N3 | Bedrock VPC endpoint name (`bedrock-runtime`) is non-obvious. | Networking | Prerequisites | Add endpoint name clarification. |
| V3 | Steps 5-7 introductions slightly more neutral/doc-voice than Steps 1-3. | Voice | Code walkthrough, Steps 5-7 | Add personality to match the energy of earlier steps. |

---

## What This Recipe Does Well

Worth preserving in final edits:

- The opening problem statement is the best kind of healthcare AI motivation: specific, human, backed by data (the 2019 systematic review citation, the NIH reading level recommendation, the 50% readmission increase). It makes a VP of Patient Experience and an engineer both nod.
- The "transformation task, not a generation task" distinction is an important safety framing that most LLM recipes skip. It correctly identifies why simplification is safer than open-ended generation and sets appropriate expectations.
- The failure modes section is genuinely useful. "Meaning drift," "over-simplification," "under-simplification," and "confidence without accuracy" are the real failure modes, described with concrete examples. This section alone justifies the recipe's existence for a reader evaluating whether to build this.
- The readability scoring explanation (Flesch-Kincaid, Flesch Reading Ease, SMOG) with the honest caveat that they measure surface complexity, not conceptual complexity, is exactly the right level of nuance.
- The sample output (cardiac discharge summary, original vs. simplified) is convincing and demonstrates real value. The simplified version is genuinely better for a patient.
- "The Honest Take" delivers a non-obvious insight: "patients don't just want simpler words. They want structure." This is the kind of production experience that makes the cookbook valuable.
- The cost estimate ($0.02-0.04 per document) is reasonable and verifiable against current Bedrock and Comprehend Medical pricing.
- The Python companion is well-structured, uses the correct Bedrock Converse API (not the older InvokeModel with raw JSON), handles DynamoDB Decimal conversion correctly, and has a thorough "Gap to Production" section.

---

*Review completed 2026-05-06. Four expert perspectives: security, architecture, networking, voice.*
