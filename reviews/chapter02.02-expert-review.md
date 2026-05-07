# Expert Review: Recipe 2.2 - Medical Terminology Simplification

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-07
**Recipe file:** `chapter02.02-medical-terminology-simplification.md`

---

## Overall Assessment

**Verdict: PASS**

This recipe has meaningfully improved since the prior review pass. Bedrock Guardrails are now actually wired into the Step 3 pseudocode instead of being a phantom in the Ingredients table. Entity preservation logic is smarter: verbatim-required entities (medications, dosages, frequencies) get strict matching, while translatable entities (conditions, procedures) get a lower severity with an honest acknowledgment that "perfect verification would need NLI models." DynamoDB encryption now specifies customer-managed KMS keys, matching S3 parity. The problem statement (the cardiac discharge scenario) remains one of the stronger openings in the book, and the "transformation task, not generation task" framing does real work in setting safety expectations.

That said, three gaps from the prior review were not closed and two new accuracy issues surfaced. The KMS VPC endpoint is still missing from the prerequisites (will break production). The Lambda timeout is still unspecified (the recipe itself cites 3-6 second end-to-end latency, which fails against Lambda's default 3-second timeout). The per-document cost estimate in the header and performance benchmark table is off by roughly an order of magnitude because it appears to omit Comprehend Medical from the total. Two TODO comments are still inline in the published prose, including one on an AWS Solutions URL that the style guide explicitly prohibits shipping unverified. The recipe's own "Honest Take" promises a retry loop that the pseudocode does not implement, and the caching behavior claimed in the Expected Results is not reflected in the Code walkthrough. Priority breakdown: 0 critical, 3 high, 6 medium, 5 low.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

- BAA requirement is explicitly called out with the reason ("clinical text contains PHI"). Good.
- DynamoDB encryption now specifies customer-managed KMS key, closing the prior parity gap with S3 SSE-KMS.
- CloudWatch Logs KMS encryption is explicit.
- IAM permissions are listed with specific actions (`bedrock:InvokeModel`, `bedrock:ApplyGuardrail`, `comprehendmedical:DetectEntitiesV2`, etc.) and the Prerequisites entry notes "Scope each to specific resource ARNs."
- Bedrock Guardrails are now actually invoked in Step 3 (`guardrail_id = "terminology-simplification-guardrail"`), closing the prior phantom-service gap.
- "Never use real patient documents in dev" is stated clearly.
- CloudTrail logging for Bedrock and Comprehend Medical is required.
- The `comprehendmedical:` (not `comprehend:`) IAM namespace is correct, matching the code reviewer's separate finding on the Python companion.

#### Issue S1: KMS VPC Endpoint Still Missing From Prerequisites (HIGH)

**Location:** Prerequisites table, VPC row (line 139):

> "Production: Lambda in VPC with VPC endpoints for Bedrock, Comprehend Medical, S3, DynamoDB, and CloudWatch Logs"

**The problem:** The Encryption row mandates SSE-KMS on S3, a customer-managed KMS key on DynamoDB, and KMS encryption on CloudWatch Logs. Every decryption of an S3 prompt template, every DynamoDB GetItem or PutItem, and every CloudWatch Logs write requires a KMS API call to generate or decrypt a data key. With Lambda in a private subnet and no internet egress (the correct production posture), those KMS calls have no route. Without a KMS interface endpoint (`com.amazonaws.{region}.kms`), the Lambda will fail with `AccessDeniedException` or a timeout on the first S3 GetObject for the prompt templates, before the pipeline can even call Bedrock.

This is the same finding as the prior review. It was not addressed in the current revision, and is the single most likely thing that will break a reader's first production deployment.

**Suggested fix:** Add KMS to the VPC endpoint list: "VPC endpoints for Bedrock, Comprehend Medical, S3, DynamoDB, KMS, and CloudWatch Logs." Also note that KMS is an interface endpoint (billed per AZ per hour) because some readers expect all four to be gateway endpoints.

#### Issue S2: Input-Side Prompt Injection Mitigation Not Discussed (MEDIUM)

**Location:** Step 3 pseudocode (`simplify_segment`); "Failure Modes" subsection of "The Technology."

**The problem:** The segment text is injected directly into the user message of the Bedrock call. Depending on the source, that text carries different trust levels. A clean EHR discharge summary is low-risk. But the recipe's upstream examples in Related Recipes include "Recipe 1.6 (Handwritten Clinical Note Digitization)," where OCR output can contain arbitrary reconstruction artifacts, and clinical text in the real world sometimes includes patient-supplied free text (intake forms, portal messages copy-pasted into an addendum). Adversarial content in that text could attempt to override simplification constraints, insert instructions to exfiltrate other patient data, or add fabricated clinical recommendations.

The recipe applies Bedrock Guardrails on the output (Step 3 passes `guardrail_id` to the Bedrock call, which filters the response), but does not mention configuring input-side filters. Bedrock Guardrails supports input filters (prompt-attack detection, denied-topic matching on user input) that are a defense-in-depth layer for exactly this scenario. This was flagged in the prior review as well.

**Suggested fix:** Add a sentence in the "Failure Modes" section or Step 3 narrative: "When the source text originates from untrusted channels (OCR of handwritten notes, patient-supplied free text, addenda entered through a portal), configure the Bedrock Guardrail with input-side prompt-attack filters in addition to the output filters. Input filtering catches injection attempts before the model sees the manipulated text. For clean EHR-sourced text this is less critical but is a low-cost layer to add."

#### Issue S3: PHI Retention Policy Not Discussed for Cached Simplified Documents (MEDIUM)

**Location:** Step 5 (`assemble_and_store`); Prerequisites table.

**The problem:** Step 5 writes to a DynamoDB table named `simplified-documents` with `original_text`, `simplified_text`, `entities_preserved` (a list of medications, dosages, conditions), and `model_id`. Every field is PHI. The cache key is a hash of source text plus target grade, which means cache hits are served indefinitely by design. The Expected Results section claims "30-50% cache hit rate after warm-up," so this table is expected to grow and be retained.

No TTL, archival path, or retention boundary is defined. Under HIPAA minimum-necessary principles, PHI stores need an explicit lifecycle. For simplified outputs that back a patient portal, you likely want hot retention for as long as the patient might re-request the document (months), then archive to a colder tier with appropriate controls, then delete per the organization's retention schedule. The recipe silently encourages perpetual accumulation.

**Suggested fix:** Add one or two sentences to Step 5 or a new row in Prerequisites: "The `simplified-documents` table stores PHI. Configure DynamoDB TTL aligned with your organization's PHI retention policy (a common pattern is hot retention for 6-12 months matching portal access windows, then archival to S3 Glacier with KMS encryption for longer-term audit retention). Separately, define a deletion path for patient-initiated data deletion requests under state privacy laws."

#### Issue S4: Bedrock Model-Invocation-Logging and Prompt PHI Not Addressed (LOW)

**Location:** Step 3 pseudocode; Prerequisites (CloudTrail row).

**The problem:** The system prompt constructed in Step 3 embeds the `must_preserve` list, which contains medication names, dosages, and condition names from the source text. That system prompt is a PHI-carrying string that gets sent to Bedrock. If a reader enables Bedrock model-invocation-logging for quality monitoring or prompt-drift analysis (a reasonable and common production choice), the logged prompts and responses land in S3 or CloudWatch Logs, creating a new PHI store that needs encryption, access control, and retention parity with the primary data stores. Recipe 2.1 handles this nuance explicitly; Recipe 2.2 doesn't mention it.

**Suggested fix:** Add one sentence near the Step 3 pseudocode or in the Prerequisites Encryption row: "If Bedrock model-invocation-logging is enabled for quality monitoring, the logged prompts will contain PHI (the embedded must-preserve list). The log destination bucket or log group must be KMS-encrypted, access-controlled, and subject to the same retention policy as other PHI stores."

#### Issue S5: Guardrail Interventions Not Captured as Safety Events (LOW)

**Location:** Step 3 pseudocode (`simplify_segment` returns `reason: response.guardrail_reason` but does not log it); Step 5 (metrics block).

**The problem:** When the guardrail blocks a segment's simplification, the pseudocode returns `simplified: false, reason: response.guardrail_reason` and falls through. Step 5 emits a `SimplificationCompleted` metric and a `SimplificationNeedsReview` metric but does not emit a guardrail-specific metric. For a PHI-carrying pipeline, guardrail blocks are safety events; you want to know which segments triggered which policies at which rates, both for quality improvement (are we over-filtering?) and for compliance (can we demonstrate the safety layer is doing work?).

**Suggested fix:** Add a brief mention in Step 3 or Step 5 that guardrail blocks should emit a distinct CloudWatch metric (e.g., `SegmentBlockedByGuardrail` with dimensions for segment type and triggered policy), and that the `guardrail_reason` string may itself echo PHI from the segment and should be handled accordingly (not logged verbatim into an un-encrypted channel).

---

### Architecture Expert Review

#### What's Done Well

- Segmentation-before-simplification is the right design and is explained clearly. The insight in "The Honest Take" that "the segmentation step matters more than the model choice" is the kind of production wisdom this book promises.
- Type-specific prompts (medications, diagnosis, instructions, results, narrative) give the model the right constraints per content type instead of a single generic prompt.
- Readability validation as a deterministic, non-LLM check (Flesch-Kincaid) is correct for speed and cost.
- The distinction between `preserve_verbatim: true` (medications, dosages, frequencies) requiring exact match and `preserve_verbatim: false` (conditions, procedures) allowing translation is a meaningful improvement over the prior version, and the self-aware parenthetical "(This is a heuristic; perfect verification would need NLI models)" is honest about the limits.
- Cache key construction (`hash(original_text + "|" + target_grade)`) is correctly scoped so changes to target grade don't cause false cache hits.
- Temperature of 0.2 for a constrained transformation task is appropriate.
- The sample output and before/after discharge summary example make the recipe concrete.

#### Issue A1: Lambda Timeout Not Specified; Default Will Fail (HIGH)

**Location:** Prerequisites table (no Lambda timeout row); Expected Results ("End-to-end latency | 3-6 seconds per document").

**The problem:** The default Lambda timeout is 3 seconds. The recipe's own Expected Results table says typical end-to-end latency is 3-6 seconds per document, and the pipeline performs, in order: Comprehend Medical `DetectEntitiesV2` (200-800 ms), S3 GetObject for prompt templates (50-200 ms if not cached in memory), one Bedrock Converse call per segment with guardrail applied (1-4 seconds per segment, and a segmented document has 3-6 segments), readability scoring (negligible), and DynamoDB PutItem (50 ms). Realistic Lambda execution is 5-20 seconds on a good path, longer when segments retry or Bedrock throttles.

A reader who deploys with Lambda defaults will see every single invocation fail with `Task timed out after 3.00 seconds`. This was flagged in the prior Recipe 2.1 review and not addressed here despite this recipe's longer per-document latency profile.

**Suggested fix:** Add a Lambda timeout row to the Prerequisites table: "Lambda timeout: 60 seconds minimum (multi-segment simplification with guardrail-applied Bedrock calls runs 3-6 seconds end-to-end and can spike higher under throttling). Lambda memory: 512 MB floor (the Bedrock SDK payload and segment reassembly work don't run well at 128 MB)." If multi-segment concurrency is a production concern, consider noting that Step Functions or parallel Lambda invocations per segment would trade cost for latency.

#### Issue A2: Per-Document Cost Estimate Is Off By Roughly 10x (HIGH)

**Location:** Recipe header ("Estimated Cost: ~$0.005–0.02 per document"); Performance benchmarks table ("Cost per document (1-page discharge summary) | $0.005-0.02"); Prerequisites table (Cost Estimate row).

**The problem:** The header and performance-benchmark table state a total per-document cost of $0.005-0.02. The Prerequisites Cost Estimate row, when read carefully, decomposes this differently: "Bedrock (Claude Haiku): ~$0.005-0.02 per document depending on length. Comprehend Medical: $0.01 per 100 characters." The Comprehend Medical rate quoted is correct per the current AWS pricing page (verified: $0.01 per 100-character unit for NERe in the first tier, with a 1-unit minimum charge per request).

The problem is the arithmetic on a 1-page discharge summary. The AWS pricing examples on the Comprehend Medical pricing page use 1,700 characters per page as their reference. At $0.01 per 100-character unit, one page is 17 units = $0.17 for a single `DetectEntitiesV2` call. Bedrock Claude Haiku at current rates adds roughly $0.002-0.01 for a simplification of that length. Total per-document cost is approximately $0.17-0.18, not $0.005-0.02. The recipe is approximately 10x optimistic on total cost.

This matters for three reasons. First, it's internally inconsistent: the Prerequisites line about Comprehend Medical rates contradicts the top-line cost estimate. Second, it affects build-vs-buy decisions and scale planning: at 35,000 documents per month (the scale from the AWS pricing page examples), the recipe implies $700/month; reality at first-tier NERe pricing is approximately $6,000/month. Third, the architecture diagram shows a second Comprehend Medical arrow (`H -->|Check Preservation| C`) that would double the Comprehend Medical cost if the pipeline actually re-extracts entities from the simplified text (Step 4's pseudocode uses string matching, not a second Comprehend Medical call, so either the diagram or the pseudocode is wrong; see Issue A3).

**Suggested fix:** Correct the header and benchmark table. A realistic total per-document cost for a 1-page (1,700-char) discharge summary is approximately $0.18-0.25, dominated by Comprehend Medical. For multi-page documents (discharge summaries of 3-5 pages are common), the cost scales linearly with Comprehend Medical character count. The Prerequisites row should explicitly total the components rather than leaving the reader to add them. If the Expected Results cache hit rate of 30-50% is real, the effective amortized cost with caching is meaningful to report separately.

#### Issue A3: Architecture Diagram and Pseudocode Disagree on Second Comprehend Medical Call (MEDIUM)

**Location:** Architecture Diagram (`H -->|Check Preservation| C` where C is Comprehend Medical); Step 4 pseudocode (`validate_output`).

**The problem:** The architecture diagram shows the validation step calling Comprehend Medical a second time to check preservation, with an arrow from the validate-and-assemble Lambda back to Comprehend Medical. The Step 4 pseudocode instead performs string matching (`IF lowercase(entity.text) NOT found in simplified_lower`) on the simplified text using the entity list extracted in Step 1. No second Comprehend Medical call happens in the pseudocode.

This matters because the two implementations have different cost, correctness, and latency implications. A second Comprehend Medical call doubles the Comprehend Medical spend and adds 200-800 ms of latency, but it handles morphological variations better (e.g., "aspirin" vs "Aspirin" vs "aspirin tablets"). String matching is cheaper and faster but brittle around case, whitespace, and Unicode normalization. The recipe picks string matching in code but implies the other choice in the diagram.

**Suggested fix:** Either remove the `H -->|Check Preservation| C` arrow from the diagram (if string matching is the intended implementation, which is consistent with the pseudocode) or add a second Comprehend Medical extraction step to Step 4 (if re-extraction is the intended implementation, which is consistent with the diagram and would also affect Issue A2's cost estimate). The pseudocode is likely the correct intent; the diagram should be updated to show Step 4 consuming the `must_preserve` list from Step 1 rather than calling Comprehend Medical again.

#### Issue A4: "Honest Take" Claims a Retry Loop That the Pseudocode Doesn't Implement (MEDIUM)

**Location:** "The Honest Take" paragraph 3: "The validation loop (simplify, score, re-simplify if needed) adds latency but is worth it." Also The Technology section: the "simplify, score, re-simplify if needed" cadence is implied throughout the narrative.

**The problem:** The Step 4 `validate_output` function returns an `issues` list with severity levels, and Step 5 `assemble_and_store` handles validation failures by appending the original (un-simplified) segment to the final document with a `needs_review` flag. There is no re-simplification loop. A segment that fails readability validation once falls through to human review; it is never re-attempted at a lower target grade or with a more aggressive prompt, despite The Honest Take's claim.

This also contradicts the benchmark claim: "Readability target hit rate | 85-92% of segments on first pass." The phrasing "on first pass" implies there's a second pass that isn't in the code.

Either the retry loop should be added to the pseudocode (and the cost and latency estimates adjusted accordingly), or The Honest Take and the benchmark phrasing should be revised to match the "one pass, then human review" behavior actually implemented.

**Suggested fix:** Option (a): add a retry loop in Step 5 that, on a readability-severity `error`, re-invokes Step 3 with a lower target grade (e.g., target - 1) up to a maximum retry count (typically 2). Update the narrative to describe this loop and note the latency and cost implications. Option (b): rewrite The Honest Take's claim to match the current behavior: "The validation step flags segments that missed the target grade for human review rather than retrying them. In practice, a retry loop with a stricter prompt can reclaim 50-70% of flagged segments, and is a reasonable first enhancement in production."

#### Issue A5: Cache Lookup Not Integrated Into the Pipeline (MEDIUM)

**Location:** Expected Results ("Cache hit rate (standard templates) | 30-50% after warm-up"); "Why These Services" ("Amazon DynamoDB for result storage and caching. Store simplified outputs keyed by a hash of the source text. If the same discharge instruction template gets simplified repeatedly ... serve the cached version instead of calling Bedrock again."); Code walkthrough (no cache-lookup step).

**The problem:** The "Why These Services" section promises that repeat simplifications of the same source text are served from cache, saving cost and latency. The Expected Results table claims a 30-50% cache hit rate. Both claims materially affect cost and throughput numbers. But the pseudocode walkthrough has no cache-lookup step at the front of the pipeline. Step 1 goes straight to Comprehend Medical. Step 5 writes the result with a cache key but never shows a reader where that key is consulted on a subsequent invocation.

A reader implementing this recipe exactly will get zero cache hits. The cost per document will also be closer to the uncached value (relevant to Issue A2).

**Suggested fix:** Add a Step 0 before Step 1: "Check cache. Compute `cache_key = hash(original_text + '|' + target_grade)`. If a cached simplified document exists in the `simplified-documents` table, return it directly. Otherwise proceed to Step 1." Also note in the pseudocode narrative that templated content (standard discharge instructions with only name/date/dosage variations) benefits most from this, and that more sophisticated caching (hashing only the template portion while re-simplifying variable portions) is an MVP-follow-on described in Variations.

#### Issue A6: Segment Classifier Has No Ambiguity or Confidence Handling (MEDIUM)

**Location:** Step 2 pseudocode (`segment_document`); "The Honest Take" (which elevates segmentation as "more important than the model choice").

**The problem:** The classifier iterates `SEGMENT_TYPES` and does first-match-wins substring search. A section with text like "Please take this medication and follow up in 2 weeks" matches both `medications` ("medication") and `instructions` ("follow up"). The iteration order of the dictionary determines which wins. A section that matches nothing silently falls through to `narrative`, which gets the most generic prompt. There's no tie-breaking, no match-count score, and no "route to manual review when ambiguous" escape hatch.

The Honest Take correctly identifies segmentation as the most leveraged component, but the implementation shown doesn't treat it with the care that framing implies. This is a particularly acute concern because misclassification causes the wrong prompt to be applied, which changes what the model preserves verbatim. If a medication list is misclassified as `narrative`, the `preserve_verbatim` constraint on dosages isn't applied in the prompt.

**Suggested fix:** Either (a) in Step 2 pseudocode, track how many keywords matched and for which types, and if more than one type matches meaningfully, run the segment through both prompts and pick the better-validating output, or log a warning and apply the stricter prompt (`medications` over `instructions` when both match), or (b) describe the upgrade path in The Honest Take or Variations as a small classifier (TF-IDF + logistic regression, or a distilled model fine-tuned on labeled segments). Option (a) is the minimum; option (b) is the better long-term framing.

---

### Networking Expert Review

#### What's Done Well

- VPC endpoints are explicitly listed for services that handle PHI (Bedrock, Comprehend Medical, S3, DynamoDB, CloudWatch Logs).
- The recipe correctly identifies that clinical text is PHI and cannot leave the compliance perimeter.
- CloudTrail logging is mandated for Bedrock and Comprehend Medical.

#### Issue N1: KMS VPC Endpoint Still Missing (HIGH, cross-listed with S1)

Same finding as Security Expert S1. Cross-listed because it's both a security-posture gap and a networking-configuration gap that will cause silent production failure. The KMS endpoint is required for Lambda to decrypt S3 SSE-KMS objects, write to a KMS-encrypted DynamoDB table, and emit logs to a KMS-encrypted CloudWatch Logs group from within a private subnet.

#### Issue N2: Interface vs. Gateway Endpoint Distinction Not Made (MEDIUM)

**Location:** Prerequisites table, VPC row.

**The problem:** The VPC row lists endpoints without distinguishing between gateway endpoints (S3, DynamoDB: free, route-table-based) and interface endpoints (Bedrock, Comprehend Medical, KMS, CloudWatch Logs: billed per AZ per hour plus data processing, require security groups). A first-time VPC-endpoint configurator will hit two different configuration flows and see unexpected billing for the interface endpoints. The prior Recipe 2.2 review flagged this; the prior Recipe 2.1 review addressed it with a parenthetical. This recipe still omits it.

**Suggested fix:** Add a parenthetical to the VPC row: "S3 and DynamoDB use gateway endpoints (free, route-table-based). Bedrock (`com.amazonaws.{region}.bedrock-runtime`), Comprehend Medical, KMS, and CloudWatch Logs use interface endpoints (PrivateLink, approximately $0.01/AZ/hour plus data processing charges; require a security group allowing HTTPS from the Lambda subnet)."

#### Issue N3: Bedrock Endpoint Name Not Specified (LOW)

**Location:** Prerequisites table, VPC row.

**The problem:** The recipe lists "Bedrock" as a VPC endpoint. The actual service endpoint name for the InvokeModel and ApplyGuardrail actions is `com.amazonaws.{region}.bedrock-runtime` (not `bedrock`). Recipe 2.1 correctly spells this out. A reader comparing the two recipes side by side will notice the inconsistency.

**Suggested fix:** Spell the endpoint name out: "Bedrock (`com.amazonaws.{region}.bedrock-runtime`, which serves both InvokeModel and ApplyGuardrail; there is no separate `bedrock-guardrails` endpoint)."

---

### Voice Reviewer

#### What's Done Well

- The opening cardiac-discharge paragraph is strong. The specific jargon-dense quote followed by "The patient nods, walks to their car, and has absolutely no idea what just happened to them" is the right voice: specific, vivid, low key devastating.
- "Health literacy is not about intelligence. A PhD in literature still won't know what 'apical hypokinesis' means." This is the engineer-at-whiteboard register CC uses.
- The Technology section earns its space. Three properties that make LLMs good at this task (contextual understanding, graduated simplification, structural preservation) are concrete, not hand-wavy.
- The failure modes list (over-simplification, hallucinated explanations, inconsistent terminology, cultural assumptions, loss of actionable specifics) is the kind of teaching that makes this cookbook valuable. "Your blood thinner twice a day" as an example of an over-simplified dosage instruction is exactly the right kind of concrete failure.
- The Honest Take delivers: "Early in development, I watched the model simplify 'ticagrelor 90mg BID' into 'your blood thinner twice a day.' Technically simpler. Also completely useless if the patient needs to verify their prescription at the pharmacy." That's CC voice.
- Vendor balance is approximately 70/30. The Problem, The Technology, and General Architecture Pattern sections stay vendor-agnostic. AWS service names appear in "The AWS Implementation" and stay there.

#### Issue V1: No Em Dashes

Confirmed: full-file scan for U+2014 returned zero matches. Clean.

#### Issue V2: Inline TODO on AWS Solutions URL Must Not Ship (MEDIUM)

**Location:** Additional Resources, AWS Solutions and Blogs section (line 543):

> `[Guidance for Generative AI Text Summarization using LLMs on AWS](https://aws.amazon.com/solutions/guidance/generative-ai-text-summarization-using-large-language-models-on-aws/): Reference architecture for text transformation pipelines <!-- TODO: Verify this URL exists -->`

**The problem:** The style guide is explicit: "Only real, verified URLs. Never make up GitHub repos or doc links." An inline TODO on a live URL reference means the author hasn't verified it, which is exactly the condition the rule prohibits. Either the URL exists and the TODO should be removed, or it doesn't exist and the entry should be replaced or removed. The recipe cannot ship with the TODO intact.

**Suggested fix:** Verify the URL now. If it resolves, delete the TODO comment. If it doesn't, replace with a verified alternative (candidates: an AWS ML blog post on text simplification or transformation with Bedrock, or the `amazon-bedrock-samples` repo that is already linked and does cover transformation patterns).

#### Issue V3: Recipe 8.1 Cross-Reference TODO (LOW)

**Location:** Related Recipes, third bullet (line 520):

> `Recipe 8.1 (Medical Entity Extraction): Uses Comprehend Medical for entity extraction, the same technique used here for preservation verification <!-- TODO: Verify recipe number against final chapter 8 index -->`

**The problem:** Chapter 8 isn't written yet, so the recipe number can't be pinned. This is the same unavoidable situation as Recipe 2.1's reference to Recipe 11.1 and is acceptable on the same grounds (tracked in the book-wide cross-reference sweep before publication). Flagging for the editor.

**Suggested fix:** No action in this recipe pass. Track for the editor's cross-reference sweep.

#### Issue V4: "Let me map out" and Similar Mild Doc-Voice Creep in Step Narratives (LOW)

**Location:** Step introductions in the Code walkthrough (bolded paragraphs before each pseudocode block).

**The problem:** Most step narratives are in the right voice ("Skip this step and you have no way to automatically detect when simplification accidentally drops a medication or changes a dosage" in Step 1). A few are a beat more neutral than the surrounding prose ("This is the core transformation step. Each segment gets a tailored system prompt that tells the model exactly how to handle that content type" in Step 3). Not wrong; slightly cooler in register.

**Suggested fix:** Optional touch-up in the editing pass. One or two of the Step 3 and Step 5 intros could absorb a little more personality.

#### Issue V5: Cost Claim in the Header Sets an Expectation the Architecture Doesn't Meet (LOW, echoes A2)

**Location:** Recipe header ("Estimated Cost: ~$0.005–0.02 per document").

**The problem:** From a voice-and-expectations perspective, the header is the first impression of the recipe's economics, and it's inconsistent with the Prerequisites detail. A reader who reads the header, commits to the architecture, and later discovers the real per-document cost is closer to $0.18 will feel misled. The voice of the book is honest-engineer-explaining; that voice is compromised when the cost advertisement doesn't match the cost math.

**Suggested fix:** Covered under Issue A2. Correcting the cost estimate resolves the voice concern.

---

## Stage 2: Expert Discussion

### Overlapping Concerns

**KMS endpoint (S1, N1):** Security and Networking independently flagged the same gap. This is the single most-likely-to-break-production finding in the recipe and was unaddressed from the prior review. One edit fixes both.

**Cost accuracy and cache (A2, A5, V5):** Three findings trace to the same root issue: the recipe's cost and throughput claims don't match the architecture actually implemented. A2 finds the arithmetic error (Comprehend Medical is dominant and omitted from the top-line cost). A5 finds that the cache-lookup step needed to justify the lower effective cost isn't in the code. V5 notes the voice issue of a first-impression cost that the rest of the recipe doesn't support. Resolution: correct the header cost to reflect Comprehend Medical, add the cache-lookup step as Step 0, and then re-derive the amortized cost with the cache hit rate (which is reasonable if cached properly).

**Pipeline behavior under failure (A1, A4, A6):** The Lambda timeout finding (A1) causes immediate deployment failure. The missing retry loop (A4) is a discrepancy between the narrative promise and the implementation, not a failure mode. The segment classifier ambiguity (A6) causes subtle misclassification failures that compound downstream (wrong prompt leads to wrong preservation rules). A1 is the highest priority because it's deterministic on day one. A4 is a fix to either the code or the prose so they match. A6 is a real architectural gap that merits a Variations note at minimum.

**Diagram vs. pseudocode consistency (A3):** Separate from the above, the architecture diagram shows a second Comprehend Medical call that the pseudocode doesn't make. This contributes to the cost confusion (A2) and to reader uncertainty about what the pipeline actually does. One-line fix.

### Priority Resolution

Three HIGH findings: KMS endpoint (S1/N1), Lambda timeout (A1), and cost estimate (A2). The threshold for FAIL is more than 3 HIGH findings; the recipe is at 3, which passes. However, the three HIGH findings are tightly coupled: all three are accuracy or correctness issues that will visibly fail or mislead a reader on first deployment. Every one of them is a one-to-three-line edit.

No conflicts between experts. All four reviewers converged on the same theme: the recipe is well-conceived and well-written, but a handful of cross-cutting accuracy gaps were not closed in this revision and should be before publication.

---

## Stage 3: Synthesized Findings

### Verdict: PASS

No critical findings. Three HIGH findings (threshold for FAIL is more than 3). The recipe is publishable with the fixes below applied. All three HIGH fixes are small, targeted edits to the Prerequisites table and the cost summary rows.

---

### Prioritized Fix List

#### HIGH (Fix Before Publication)

| ID | Finding | Expert | Location | Fix |
|----|---------|--------|----------|-----|
| S1/N1 | Missing KMS VPC endpoint will break S3 SSE-KMS, DynamoDB CMK, and CloudWatch Logs KMS operations from private-subnet Lambda. Same finding as prior review; not addressed. | Security + Networking | Prerequisites table, VPC row | Add KMS to the endpoint list, noting it is an interface endpoint. |
| A1 | Lambda timeout not specified; default (3s) will fail every invocation against the recipe's own stated 3-6s latency. | Architecture | Prerequisites table | Add Lambda timeout row: 60s minimum. Also note memory sizing (512 MB floor). |
| A2 | Per-document cost estimate ($0.005-0.02) excludes dominant Comprehend Medical cost. Real cost for 1-page discharge at $0.01/100-char × 17 units = $0.17 minimum. Header and benchmark contradict Prerequisites detail. | Architecture | Recipe header; Performance benchmarks table | Correct the total to approximately $0.18-0.25 per 1-page document. Break down by component in the Prerequisites row. Separately note amortized cost with caching once the cache lookup is actually in the pseudocode (see A5). |

#### MEDIUM (Should Fix)

| ID | Finding | Expert | Location | Fix |
|----|---------|--------|----------|-----|
| S2 | Input-side Guardrails not mentioned. Output-only filtering leaves a defense-in-depth gap for OCR or patient-sourced text. | Security | Step 3; Failure Modes | Add a sentence on input-side prompt-attack filters when the source text originates from untrusted channels. |
| S3 | No PHI retention policy or TTL on the `simplified-documents` table. | Security | Step 5; Prerequisites | Add a retention-policy line: hot retention window, archival path, deletion path for data-subject requests. |
| A3 | Architecture diagram shows second Comprehend Medical call (`H -->|Check Preservation| C`); Step 4 pseudocode uses string matching. | Architecture | Architecture Diagram; Step 4 | Remove the diagram arrow or add a second Comprehend Medical call to Step 4. Align diagram with pseudocode. |
| A4 | "Honest Take" claims a validation retry loop that the pseudocode doesn't implement. | Architecture | Step 5; The Honest Take | Either add the retry loop in the pseudocode or revise the narrative claim to match the current single-pass-plus-flag behavior. |
| A5 | Caching is claimed in Expected Results (30-50% hit rate) and "Why These Services" but no cache-lookup step exists in the pseudocode. | Architecture | Code walkthrough | Add a Step 0: compute cache key and return cached result if present. Update the narrative and cost discussion accordingly. |
| A6 | Segment classifier is first-match-wins substring search with no tie-breaking or ambiguity handling. Misclassification changes which preservation constraints get applied. | Architecture | Step 2 | Track match counts, flag ambiguous segments, and either apply the stricter prompt or route to manual review. Describe the upgrade path to a learned classifier in Variations. |
| N2 | Interface vs. gateway endpoint distinction not made. Readers face different setup flows and unexpected billing for interface endpoints. | Networking | Prerequisites, VPC row | Add parenthetical distinguishing free gateway endpoints (S3, DynamoDB) from billed interface endpoints (all others). |
| V2 | `<!-- TODO: Verify this URL exists -->` inline on an AWS Solutions link. Style guide prohibits shipping with unverified URLs. | Voice | Additional Resources | Verify the URL; remove the TODO or replace the entry. Do not ship with the TODO intact. |

#### LOW (Improvement Recommendations)

| ID | Finding | Expert | Location | Fix |
|----|---------|--------|----------|-----|
| S4 | Bedrock model-invocation-logging produces PHI-containing logs (the system prompt embeds the must-preserve list). Not discussed. | Security | Step 3; Prerequisites | One-line note that invocation logs are PHI if enabled and need KMS-encrypted destinations. |
| S5 | Guardrail interventions should be surfaced as a distinct safety metric. | Security | Step 3 or Step 5 | Add a `SegmentBlockedByGuardrail` metric with segment-type and policy dimensions. Note that `guardrail_reason` may echo PHI. |
| N3 | Bedrock endpoint name `bedrock-runtime` (not `bedrock`) not spelled out. Recipe 2.1 fixes this; Recipe 2.2 does not. | Networking | Prerequisites, VPC row | Spell out the endpoint name and note it serves both InvokeModel and ApplyGuardrail. |
| V3 | Recipe 8.1 cross-reference TODO. | Voice | Related Recipes | Track in book-wide cross-reference sweep before publication. Acceptable for now. |
| V4 | Minor register drift in Step 3 and Step 5 intros. | Voice | Code walkthrough | Optional touch-up in editing pass. |

---

## What This Recipe Does Well

Worth preserving through editing:

- The cardiac-discharge opening is specific, vivid, and immediately motivates the use case. "The patient nods, walks to their car, and has absolutely no idea what just happened to them" is exactly the register the book should hold. Keep it.
- The Failure Modes subsection (over-simplification, hallucinated explanations, inconsistent terminology, cultural assumptions, loss of actionable specifics) is a reusable teaching unit. Subsequent LLM recipes in Chapter 2 can reference this rather than re-derive it.
- The `preserve_verbatim: true/false` distinction in the entity preservation logic is a meaningful safety improvement and shows thoughtful handling of the synonym-substitution blind spot flagged in the prior review. The parenthetical "(This is a heuristic; perfect verification would need NLI models)" is honest in the right way.
- The "transformation task, not a generation task" framing is the correct safety posture and is stated clearly enough that a reader won't misuse it.
- The Honest Take delivers production insight: "the segmentation step matters more than the model choice" is non-obvious and true. The ticagrelor "your blood thinner twice a day" story is the exact texture this book trades in.
- Type-specific prompts per segment (medications, diagnosis, instructions, results, narrative) with explicit preservation rules in each prompt are the right pattern for constrained transformation.
- Bedrock Guardrails are actually integrated into the pipeline now, not just listed in Ingredients. This closes a significant prior-review gap.
- Variations and Extensions are practical (multi-language, interactive re-simplification, EHR integration) rather than filler.
- The AWS Sample Repos section lists repos that actually exist and are relevant (amazon-bedrock-samples, amazon-comprehend-medical-fhir-integration, amazon-bedrock-workshop).

---

*Review completed 2026-05-07. Four expert perspectives: security, architecture, networking, voice.*
