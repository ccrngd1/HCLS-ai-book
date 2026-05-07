# Expert Review: Recipe 2.1 - Patient Message Response Drafting

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-07
**Recipe file:** `chapter02.01-patient-message-response-drafting.md`

---

## Overall Assessment

**Verdict: PASS**

This is one of the stronger recipes in the book so far. The problem statement is visceral and human (the 5:30 PM inbox of 47 messages is instantly relatable), the LLM failure-mode section is genuinely educational rather than hand-wavy, and the human-in-the-loop design is the correct safety posture. The VPC prerequisites are notably more complete than in recipes 2.2 and 2.3: KMS endpoint is listed, interface vs. gateway distinction is made, external EHR egress is addressed with mTLS guidance, and the Bedrock runtime endpoint name is spelled out correctly. The Bedrock model-invocation-logging paragraph is the cleanest treatment of "audit logs are PHI too" anywhere in the book.

That said, there are real gaps a production implementer would hit: Lambda timeout is never specified and the default (3 seconds) is nowhere near enough for this pipeline, PHI retention on the drafts table is silently absent, the SQS DLQ in the architecture diagram is carrying PHI but encryption isn't called out, and the keyword intent classifier is a safety-relevant component whose failure mode is under-discussed. No critical findings. Priority breakdown: 0 critical, 2 high, 7 medium, 4 low.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

- BAA requirement is explicitly called out with the reason ("patient messages contain PHI"). Good.
- IAM permissions are scoped: "Scope each permission to specific resource ARNs (prompt bucket, draft table, model ARN, guardrail ARN)." This is better than prior recipes which listed actions without resource scoping guidance.
- DynamoDB encryption specifies customer-managed KMS key (not "default"). This matches S3 SSE-KMS and closes the CMK-parity gap that tripped up recipes 2.2 and 2.3.
- Bedrock model-invocation-logging paragraph correctly identifies that the logged prompts/responses are PHI and that the target S3 bucket must be KMS-encrypted, access-controlled, and subject to retention policy. The "do not enable prompt caching for PHI prompts unless caching is BAA-covered" caveat is a nice catch most recipes miss.
- Prompt injection is named as a failure mode with Guardrails + human review + output length/topic bounds as layered mitigations.
- "Never use real patient messages in dev" is explicit.
- CloudTrail logging for Bedrock invocations is required.

#### Issue S1: No Retention Policy or TTL for PHI Drafts in DynamoDB (HIGH)

**Location:** Step 5 (Store Draft) pseudocode; Prerequisites table; Ingredients table (DynamoDB row).

**The problem:** The DynamoDB draft record stores the original patient message, the assembled patient context (current medications, appointments, lab results, active conditions), the generated draft, and the provider identity. Every field is PHI or PHI-adjacent. The `store_draft` function writes `draft_status = "pending_review"` with a `generation_ts` but never sets a TTL, archival path, or retention boundary. The Prerequisites table addresses S3 log retention ("subject to your PHI retention policy") but says nothing about DynamoDB draft retention. A reader implementing this exactly will accumulate PHI drafts indefinitely.

This matters both for minimum-necessary principles under HIPAA and because the drafts table will become a large, growing PHI store with no defined lifecycle. After a provider approves and sends a draft, the operational value of retaining the full original message, context snapshot, and draft text is time-limited (quality monitoring, audit trail), but that time boundary needs to be defined.

**Suggested fix:** Add a one-line retention note in Step 5 or the Prerequisites Encryption row. Example wording: "Configure DynamoDB TTL on the drafts table aligned with your organization's PHI retention policy. A common pattern is to keep drafts hot for 30-90 days (the window where quality review of approved/edited drafts is useful), then archive to S3 Glacier with KMS encryption for the longer audit-retention period." Also mention that drafts for messages that fail generation (routed to the manual queue) may have a different retention requirement than approved drafts.

#### Issue S2: Provider Review Queue Authorization Not Discussed (MEDIUM)

**Location:** General Architecture Pattern ("Provider Review Queue" paragraph); Architecture Diagram (Provider Inbox UI node); DynamoDB schema in Step 5.

**The problem:** The drafts table stores `provider_id` on each record, and the "Why These Services" section notes that the access pattern is "lookup by message ID or by provider ID for their review queue." But the recipe never addresses how the Provider Inbox UI enforces that Dr. Martinez sees only drafts for their own patients (or for the care team they're covering), and not drafts belonging to Dr. Patel. This is a classic multi-tenant PHI access control problem.

A naive implementation that queries the drafts table by `provider_id` from URL parameters (rather than from an authenticated session principal) is trivially exploitable. A slightly less naive one that uses session principal still needs to handle cross-coverage scenarios (Dr. Martinez is covering for Dr. Patel this weekend). Neither is addressed.

**Suggested fix:** Add a short note in the Provider Review Queue paragraph or in a new bullet under the AWS implementation's Ingredients table: "The Provider Inbox UI must enforce authorization on every draft fetch. The authenticated provider identity drives the query; `provider_id` should never come from the client. Cross-coverage (shared inboxes, call pools) is an application-layer concern and should be modeled explicitly rather than loosened at the query layer." An even better treatment would mention row-level access policies in the UI's backend.

#### Issue S3: SQS DLQ Carries PHI, Encryption Not Explicitly Required (MEDIUM)

**Location:** Architecture Diagram (SQS Dead-Letter Queue node); Ingredients table (Amazon SQS row); Error Handling paragraph.

**The problem:** The DLQ receives messages that failed processing, and those messages contain the original patient message payload (PHI) at minimum. The Encryption row in Prerequisites lists S3 (SSE-KMS), DynamoDB (CMK), and CloudWatch Logs (KMS), but SQS is not mentioned. AWS-managed SQS encryption is available by default in newer queues, but customer-managed-key (SSE-KMS) encryption on SQS is an explicit configuration choice and is typically required by HIPAA compliance programs for parity with other PHI stores.

**Suggested fix:** Add SQS to the Encryption row: "SQS DLQ: SSE-KMS with customer-managed key, since DLQ messages contain PHI." Also add `kms:Decrypt` scoped to the DLQ key in the IAM permissions when consumers read from the DLQ.

#### Issue S4: Input-Side Guardrails and Prompt Injection Mitigation Could Be Stronger (MEDIUM)

**Location:** Failure Modes section ("Prompt injection" paragraph); Step 4 pseudocode (generate_draft).

**The problem:** The failure-modes section correctly names prompt injection as a risk and notes Guardrails + human review + output length/topic validation as mitigations. Good. But the pseudocode only applies `guardrail_id` on the generation call, which by default filters the output. Bedrock Guardrails also support input filters (PII detection, prompt-attack detection, denied-topics on input), and the recipe never mentions configuring them on the input side. For a pipeline that takes patient-portal free text (the most untrusted input channel in this architecture), input-side filtering is a meaningful defense-in-depth layer, not a duplicate of output filtering.

**Suggested fix:** In the Failure Modes section or in Step 4, note that the Guardrail should be configured with both input and output filters. Specifically mention the prompt-attack filter (designed for this exact scenario) and suggest reviewing the PII filter settings (some "PII" like medication names is clinically necessary and shouldn't be redacted). One sentence is enough; this is about closing the mental model loop for the reader.

#### Issue S5: EHR Context Cache Mentioned Without Encryption Guidance (LOW)

**Location:** Step 2 (Gather Context), the "A note on latency" paragraph.

**The problem:** The recipe suggests "maintain a pre-fetched patient context cache (refreshed on clinical events) to keep end-to-end latency under 5 seconds." If a reader implements this with ElastiCache, DAX, or a similar cache, that cache now holds PHI (medications, conditions, appointments). The recipe doesn't mention that the cache must be encrypted at rest, use TLS in transit, run in the VPC, and carry an appropriate TTL.

**Suggested fix:** Add a parenthetical to the cache suggestion: "(the cache is a PHI store: encrypt at rest with KMS, enforce TLS, deploy in the VPC, and set a TTL consistent with your PHI retention and staleness policies)."

#### Issue S6: Guardrail Intervention Logging for Audit (LOW)

**Location:** Step 4 pseudocode; Ingredients table (CloudWatch row).

**The problem:** When the guardrail blocks a generation, the pseudocode returns `status: "blocked", reason: response.guardrail_reason` but doesn't record that intervention anywhere auditable. For healthcare AI, a guardrail block is a safety event. You want to know which patient messages triggered which guardrail policies at which rates, both for quality improvement (are we over-filtering?) and for compliance (can we demonstrate the safety layer is doing something?).

**Suggested fix:** Add a brief note in Step 4 or 5 that guardrail interventions should be logged to CloudWatch with dimensions (intent, guardrail policy that fired) and that the reason string itself may contain PHI (it often echoes the patient message) and should be handled accordingly. The recipe already has a "DraftGenerated" metric in Step 5; a parallel "DraftBlocked" metric with guardrail-policy dimension is a natural addition.

---

### Architecture Expert Review

#### What's Done Well

- The human-in-the-loop framing ("It's not a chatbot. It's a drafting assistant.") is the correct safety posture and is stated clearly enough that a product manager reading this won't try to "improve" it by auto-sending.
- Intent classification is separated from generation, which is both a good latency optimization and a good cost decision (no LLM call for routing).
- Context gathering is intent-driven rather than a chart dump. The recipe explicitly calls out why this matters (relevance, token budget, avoiding spurious references).
- Temperature (0.3) and max-tokens (300) are reasonable defaults for this use case and the rationale is given.
- Idempotency is addressed in Step 5 with the conditional-write suggestion for at-least-once delivery. Good catch that many recipes miss.
- DLQ with depth monitoring as an operational alert is called out in the Error Handling paragraph.
- The "approval rate as north star metric" insight in The Honest Take is the right operational framing and tells a reader what to actually measure.
- Fallback model for resilience is in Variations. Reasonable scope for MVP.
- Cost estimate ($0.01-0.03 per message) is aligned with current Claude Haiku pricing.

#### Issue A1: Lambda Timeout Not Specified; Default Will Fail (HIGH)

**Location:** Prerequisites table (no Lambda timeout row); pipeline latency discussion in Step 2.

**The problem:** The default Lambda timeout is 3 seconds. This pipeline performs:
- Intent classification (negligible)
- Prompt template load from S3 (50-200 ms if not cached in the Lambda)
- One or more EHR/FHIR queries for patient context (the recipe itself says 200 ms in the best case, 1-3 seconds under load)
- A Bedrock InvokeModel or Converse call with guardrail applied (typically 1.5-4 seconds for Claude Haiku with 300 max tokens)
- DynamoDB put

Realistic end-to-end Lambda execution is 3-7 seconds on a good path, longer when the EHR is slow or Bedrock is throttled. A reader deploying with the Lambda default timeout will see every single invocation fail with `Task timed out after 3.00 seconds`, no drafts generated, and a DLQ that fills up silently until the depth alarm trips.

**Suggested fix:** Add a Lambda timeout row to the Prerequisites table: "Lambda timeout: 30 seconds minimum (60 seconds recommended) to accommodate EHR context gathering and Bedrock inference latency." Also note that Lambda memory should be sized for the Bedrock SDK payload rather than the default 128 MB (512 MB is a reasonable floor; the extra memory also buys proportionally more CPU, which reduces the JSON marshalling overhead on larger context objects).

#### Issue A2: Keyword Intent Classifier Has No Confidence or Ambiguity Handling (MEDIUM)

**Location:** Step 1 (Classify message intent); The Honest Take ("the intent classification step matters more than the model choice").

**The problem:** The pseudocode classifier is a first-match-wins substring search against per-intent keyword lists. The Honest Take correctly elevates classification to the most important component, but the implementation shown has no:
- Confidence or match-count score
- Tie-breaking for messages that match multiple intents
- Ambiguity detection (e.g., "multiple categories matched, route to provider for manual triage")
- Handling of messages that match no keywords (these fall through to `general`, which the recipe correctly notes causes the model to work from message text alone with minimal context)

The practical effect: a message like "I keep getting these bad headaches, I think I need something stronger than what you gave me" has no keyword matches in any of the defined intents, falls through to `general`, and gets drafted with only the last 30 days of visits as context. The LLM has no visibility into the patient's current medications or active conditions and generates a response that the provider will rewrite. The Honest Take says to "classify as general when in doubt," and the implementation does exactly that, but it doesn't flag the resulting draft to the provider as "generated from minimal context, review carefully."

**Suggested fix:** Two options. (a) In Step 1 pseudocode, track the matched intents and their keyword-match counts. If more than one intent matches, either pick a primary and log a warning, or route to manual triage. If no intents match, still generate a draft but attach a `context_confidence: low` flag in the stored record so the UI can surface it. (b) In The Honest Take or Variations, explicitly describe the upgrade path from keyword matching to a small classifier (logistic regression on TF-IDF, or a distilled model) and note the data collection that would support it. Option (a) is the minimum; option (b) is the ideal if space allows.

#### Issue A3: Provider Decision Audit Trail Not Modeled (MEDIUM)

**Location:** Step 5 (Store Draft) schema; General Architecture Pattern ("Every action is logged for quality monitoring"); The Honest Take (approval rate as north star).

**The problem:** The architecture promises that "Every action is logged for quality monitoring" and The Honest Take identifies approval rate as the primary metric. But the stored schema has a single `draft_status` field set to `pending_review`, and there's no explicit mechanism for capturing what the provider did next: approved as-is, edited and sent (and what the edits were), or rejected and wrote from scratch. Without this, the north-star metric can't actually be computed, prompt-drift detection is impossible, and the provider-feedback-loop variation can't be built.

**Suggested fix:** Either (a) add a brief schema note in Step 5 showing the provider-action fields that get filled in on review (`reviewed_ts`, `provider_action` one of `approved|edited|rejected`, `final_sent_text` for edited drafts, `edit_diff_summary` for lightweight prompt-drift tracking), or (b) describe this as an append-only event log in a companion table (`message-review-events`) keyed by `message_id`. Option (b) is friendlier to audit requirements because updates to the primary record tend to overwrite history. Even a two-sentence mention of the capture mechanism would close this gap.

#### Issue A4: EHR Failure Mode and Circuit Breaker Not Discussed (MEDIUM)

**Location:** Error Handling paragraph; Step 2 (Gather Context) latency note.

**The problem:** The pipeline synchronously calls the EHR/FHIR server for every message. The Error Handling paragraph says "When any step fails (EHR unavailable, LLM service throttled, guardrail blocks the draft), the message routes to the provider's manual queue with a note indicating why auto-drafting failed." This is the correct behavior at a conceptual level, but the recipe doesn't address the operationally harder scenario: the EHR is slow (not down). At 2-3 seconds per call, without a circuit breaker or per-call timeout, every Lambda invocation blocks on the EHR and the overall throughput of the pipeline collapses during EHR slowness windows. Since EHR slowness is often correlated with peak clinical hours (morning rounds, shift change), this is exactly when the pipeline should be keeping up.

**Suggested fix:** Add a note in Error Handling (or in Variations and Extensions as a resilience pattern): "Wrap EHR calls in a short per-call timeout (e.g., 2 seconds) and a circuit breaker. When the circuit is open, route messages to the manual queue immediately rather than waiting for timeouts. This preserves Lambda concurrency headroom for messages that can still be drafted (e.g., general-intent messages that need no EHR context)."

#### Issue A5: Concurrent Messages from Same Patient Not Addressed (LOW)

**Location:** General Architecture Pattern; Step 5.

**The problem:** If a patient sends two messages in quick succession (common in practice: "quick question about my refill" followed 30 seconds later by "forgot to mention, also I need a new prescription for my inhaler"), the pipeline will process them independently and produce two separate drafts in the provider's queue. This isn't wrong, but it's often not what the provider wants; they'd prefer to see the conversation grouped. The recipe doesn't address this at all.

**Suggested fix:** One sentence in Variations and Extensions: "Conversation grouping: messages from the same patient within a short window (e.g., 5 minutes) can be batched into a single draft generation. This improves draft quality (the model sees the full context) and reduces provider review burden (one thread instead of two unrelated drafts)." This is a known enhancement, not a critical gap.

#### Issue A6: Prompt Version Promotion and Rollback Not Discussed (LOW)

**Location:** Step 3 (Assemble the prompt); "Amazon S3 for prompt template storage" paragraph; Variations (A/B testing).

**The problem:** The recipe stores `prompt_version = "v2"` on each draft and mentions A/B testing prompts in Variations. Good. But it doesn't address the operational question: how do you promote a new prompt version to production without regressing approval rate? A/B testing is the answer, but the rollback path (when the new version tanks approval rate at 3 AM) isn't called out. For a safety-sensitive system, prompt changes should have a well-defined rollback plan.

**Suggested fix:** Add a short note in Variations alongside the A/B testing item: "Automate rollback on approval-rate regression. If the new prompt version's approval rate drops below a threshold (e.g., 10 percentage points below the incumbent) over a meaningful sample, automatically route new messages back to the prior version. Prompt promotion should look more like feature flags than deployments."

---

### Networking Expert Review

#### What's Done Well

- VPC endpoints listed explicitly: Bedrock (`bedrock-runtime` named correctly), KMS, CloudWatch Logs (interface endpoints); S3 and DynamoDB (gateway endpoints). This closes the KMS gap that was the #1 production-breaking finding in recipes 2.2 and 2.3.
- Interface vs. gateway endpoint distinction is explicitly made. Reader knows which are free and which are billed.
- External EHR egress path is addressed with both NAT Gateway and PrivateLink options, and mTLS is recommended for PHI-carrying external APIs.
- Security group requirement for interface endpoints (HTTPS inbound from Lambda subnet) is called out.
- Bedrock endpoint name `com.amazonaws.{region}.bedrock-runtime` is spelled out (not the ambiguous `bedrock`).

#### Issue N1: SQS VPC Endpoint Not Listed (MEDIUM)

**Location:** Prerequisites table, VPC row.

**The problem:** The recipe uses SQS as the DLQ but does not list the SQS VPC endpoint (`com.amazonaws.{region}.sqs`). This matters in two cases: (a) if any downstream Lambda (e.g., a DLQ reprocessor or an alerting Lambda that reads DLQ depth) is in the same private subnet and calls SQS directly, and (b) if the Lambda code is written to explicitly send failed messages to the DLQ rather than relying on the Lambda service's built-in async DLQ. Lambda's service-level DLQ for async invocations does not require an SQS endpoint from the function's VPC (the service writes on the function's behalf), but any code-initiated `SendMessage` to the DLQ does.

The recipe's architecture diagram shows the DLQ as a downstream consumer ("K -->|Route to manual| I"), which implies something reads from it. Whatever reads from it needs SQS connectivity.

**Suggested fix:** Add SQS to the interface endpoint list: "Interface endpoints for Bedrock (`com.amazonaws.{region}.bedrock-runtime`), KMS, CloudWatch Logs, and SQS." If the DLQ is intentionally only fed by the Lambda service's built-in async DLQ mechanism (no code-initiated writes), note that explicitly so readers don't over-provision endpoints.

#### Issue N2: EventBridge Ingress Path Not Explained (LOW)

**Location:** Prerequisites table; Architecture Diagram.

**The problem:** The diagram shows `Patient Portal / EHR -->|New Message Event| EventBridge -->|Route| Lambda`. EventBridge invokes the Lambda; the Lambda does not call EventBridge. So the Lambda's VPC does not need an EventBridge endpoint for this flow, which is fine. But a reader unfamiliar with EventBridge-to-Lambda invocation might assume they need the endpoint. A half-sentence of clarification is cheap.

**Suggested fix:** Add a footnote or a parenthetical to the EventBridge entry in Ingredients: "(EventBridge invokes Lambda via the Lambda service; the Lambda's VPC does not need an EventBridge endpoint for this flow. An endpoint is only required if the Lambda puts events back to EventBridge, which this pipeline does not.)"

#### Issue N3: Bedrock Guardrails Endpoint Name (LOW)

**Location:** Prerequisites table, VPC row.

**The problem:** The recipe correctly lists `com.amazonaws.{region}.bedrock-runtime` for InvokeModel. The `ApplyGuardrail` action is also served by the `bedrock-runtime` endpoint, which is correct, but this isn't obvious from endpoint names alone (some readers expect a separate `bedrock-guardrails` endpoint that does not exist). A one-line note preempts confusion.

**Suggested fix:** Add a parenthetical: "(`bedrock-runtime` covers both InvokeModel and ApplyGuardrail; there is no separate `bedrock-guardrails` endpoint.)"

---

### Voice Reviewer

#### What's Done Well

- The opening is excellent. "Patient portal has a messaging feature. Patients love it. Staff hate it." is the right length, the right voice, and the right hook. The 5:30 PM inbox scene is specific and vivid. The "47 unread messages" and "90-180 minutes of unpaid after-hours work" numbers are the kind of specificity that makes a VP of Operations nod.
- The tone stays engineer-at-the-whiteboard throughout. "Not auto-sending. Never auto-sending." is exactly the right kind of punchy aside for the voice guide.
- The LLM failure-mode section is educational without being defensive. Hallucination, tone drift, over-helpfulness, prompt injection, context window, inconsistency. Each one gets a concrete example rather than an abstract description.
- The Honest Take delivers real production wisdom. "Dr. Martinez signs off with 'Take care.' Dr. Patel uses 'Best regards.' Dr. Chen is more informal and uses the patient's first name." This is the signature CC texture.
- "It's not a chatbot. It's a drafting assistant." earns its place.
- Vendor balance is approximately 70/30. The first three major sections (Problem, Technology, General Architecture Pattern) are entirely vendor-agnostic. AWS service names arrive in the AWS Implementation section and stay there.

#### Issue V1: No Em Dashes

Confirmed: a full-file scan for U+2014 found zero matches. Clean.

#### Issue V2: Bedrock Guardrails Blog URL Flagged TODO Should Be Resolved (MEDIUM)

**Location:** Additional Resources, AWS Solutions and Blogs section.

**The problem:** The entry reads:

> `[Build a Robust Text-Based Toxicity Detector with Amazon Bedrock Guardrails](https://aws.amazon.com/blogs/machine-learning/build-a-robust-text-based-toxicity-detector-with-amazon-sagemaker/)` with an inline HTML comment `<!-- TODO: Verify this URL; it may point to a SageMaker post rather than a Bedrock Guardrails post. Find the correct Bedrock Guardrails blog or remove. -->`

The link text claims it's about Bedrock Guardrails, but the URL slug is `toxicity-detector-with-amazon-sagemaker`. These are almost certainly inconsistent. The TODO comment acknowledges the problem but the recipe can't ship with a link whose title and URL disagree. This is exactly the kind of "no fake URLs" failure mode the style guide warns about.

**Suggested fix:** Either find a real Bedrock Guardrails blog post (candidates: posts from the AWS ML blog on Guardrails configuration, the Bedrock Guardrails launch posts, or the AWS HCLS blog) and update both the link text and URL, or remove the entry entirely. Do not ship with the TODO intact.

#### Issue V3: Recipe 11.1 Reference Has TODO (LOW)

**Location:** Related Recipes, third bullet.

**The problem:** The bullet references "Recipe 11.1 (Patient FAQ Chatbot)" with an inline TODO: "Verify recipe number against final chapter 11 index." Since chapter 11 isn't written yet, this is unavoidable for now. Acceptable as-is if it's caught during the book's final cross-reference pass. Flagging it as a known issue for the editor.

**Suggested fix:** No action in this recipe pass. Track it in the editor's cross-reference sweep before book publication. If chapter 11 ends up changing numbering, this will need to be updated.

#### Issue V4: Minor Doc-Voice Creep in Architecture Step Descriptions (LOW)

**Location:** General Architecture Pattern section, the bullet list explaining each pipeline stage.

**The problem:** The stage descriptions (Classify Intent, Gather Context, Generate Draft, Safety Check, Provider Review Queue) are slightly more neutral in register than the surrounding prose. Not wrong, but a beat less conversational than the Problem section and The Honest Take. The "critical design principle" line that closes the section ("the LLM never communicates directly with the patient") brings the voice back.

**Suggested fix:** This is borderline. If the editor is doing a tone pass, consider adding a touch more personality to one or two of the stage descriptions. Not a blocker.

---

## Stage 2: Expert Discussion

### Overlapping Concerns

**PHI retention and lifecycle (S1, S3, S5):** Three findings touch the same underlying gap: the recipe is strong on "encrypt the PHI store" but thin on "define when PHI gets deleted or archived." DynamoDB drafts (S1), SQS DLQ encryption (S3), and EHR context cache encryption (S5) are all PHI stores that need lifecycle policies and encryption parity. The editor can fix these with a unified "PHI stores have retention policies" paragraph in Prerequisites rather than three separate edits.

**Lambda behavior under failure (A1, A4, N1):** The Lambda timeout finding (A1), the EHR circuit breaker finding (A4), and the SQS endpoint finding (N1) all describe what happens when the pipeline encounters a slow or failing dependency. A1 will cause silent production failures on day one. A4 will cause a slow degradation under peak load. N1 depends on whether the DLQ has code-initiated writers. Collectively these matter for operational robustness; A1 is the one that will definitely break a fresh deployment.

**Provider layer is under-specified (S2, A3):** Both the provider review UI authorization (S2) and the provider decision audit trail (A3) are "the provider half of the pipeline isn't fully specified." The recipe treats the Provider Inbox UI as out of scope, which is reasonable, but the drafts-table schema and access patterns do fall within scope and deserve tighter treatment.

### Priority Resolution

A1 (Lambda timeout) is the highest-priority fix because it causes immediate production failure with no ambiguity. S1 (PHI retention) is the highest-priority compliance finding because it represents a HIPAA gap that doesn't surface as a bug but will surface as an audit finding. Both are HIGH. Everything else is addressable in a focused editing pass and doesn't affect whether the recipe is publishable.

No conflicts between experts.

---

## Stage 3: Synthesized Findings

### Verdict: PASS

No critical findings. Two HIGH findings (threshold for FAIL is more than 3). The recipe is publishable with the fixes below applied.

---

### Prioritized Fix List

#### HIGH (Fix Before Publication)

| ID | Finding | Expert | Location | Fix |
|----|---------|--------|----------|-----|
| A1 | Lambda timeout not specified; default (3s) will fail every invocation. | Architecture | Prerequisites table | Add Lambda timeout row: 30s minimum, 60s recommended. Note memory sizing (512 MB floor). |
| S1 | No retention policy or TTL for PHI drafts in DynamoDB. HIPAA minimum-necessary gap. | Security | Step 5; Prerequisites | Add TTL/retention policy guidance. Define hot window (30-90 days) and archive path (S3 Glacier with KMS). |

#### MEDIUM (Should Fix)

| ID | Finding | Expert | Location | Fix |
|----|---------|--------|----------|-----|
| S2 | Provider review queue authorization model not discussed. | Security | General Architecture Pattern; Ingredients | Note that UI must enforce authz server-side from authenticated session; `provider_id` never from client. Mention cross-coverage as explicit concern. |
| S3 | SQS DLQ carries PHI; encryption not specified. | Security | Prerequisites (Encryption row) | Add SQS SSE-KMS with customer-managed key. Scope `kms:Decrypt` to DLQ key for consumers. |
| S4 | Input-side Guardrails filtering not explicitly mentioned. | Security | Step 4 or Failure Modes | Note that Guardrail should be configured with prompt-attack and PII filters on input, not just output filters. |
| A2 | Keyword intent classifier has no confidence, tie-breaking, or ambiguity handling. | Architecture | Step 1; The Honest Take | Track match counts, surface ambiguous classifications as a flag on the stored draft, or route to manual triage. |
| A3 | Provider decision audit trail (approve/edit/reject) not captured in schema. | Architecture | Step 5 schema | Add provider-action fields or describe an append-only event log. Required to compute approval-rate north-star metric. |
| A4 | No circuit breaker or per-call timeout for synchronous EHR calls. | Architecture | Error Handling; Step 2 | Wrap EHR calls in 2-second timeout and circuit breaker; open-circuit routes to manual queue immediately. |
| N1 | SQS VPC endpoint not listed in Prerequisites. | Networking | Prerequisites (VPC row) | Either add `com.amazonaws.{region}.sqs` to interface endpoint list or explicitly state that DLQ is fed only by Lambda's built-in async DLQ (no code-initiated writes). |
| V2 | Bedrock Guardrails blog URL has TODO; link text and URL slug disagree. | Voice | Additional Resources | Replace with a real, verified Bedrock Guardrails blog post, or remove. Do not ship with TODO intact. |

#### LOW (Improvement Recommendations)

| ID | Finding | Expert | Location | Fix |
|----|---------|--------|----------|-----|
| S5 | EHR context cache PHI protection not discussed. | Security | Step 2 latency note | One-line parenthetical: cache is PHI, encrypt at rest, TLS in transit, VPC, TTL. |
| S6 | Guardrail interventions not explicitly logged as safety events. | Security | Step 4/5 | Add a `DraftBlocked` CloudWatch metric with guardrail-policy dimension. Note that the reason string may be PHI. |
| A5 | Concurrent messages from same patient not batched. | Architecture | Variations and Extensions | One-sentence note on conversation grouping by patient within a short window. |
| A6 | Prompt version rollback plan not described. | Architecture | Variations (A/B testing) | Add automated rollback on approval-rate regression. |
| N2 | EventBridge endpoint clarification. | Networking | Ingredients | Parenthetical: EventBridge invokes Lambda; Lambda's VPC does not need an EventBridge endpoint in this flow. |
| N3 | Bedrock Guardrails endpoint name clarification. | Networking | Prerequisites (VPC row) | Parenthetical: `bedrock-runtime` covers both InvokeModel and ApplyGuardrail. |
| V3 | Recipe 11.1 cross-reference TODO. | Voice | Related Recipes | Track in book-wide cross-reference sweep before publication. |
| V4 | Minor register drift in General Architecture stage bullets. | Voice | General Architecture Pattern | Optional touch-up; not a blocker. |

---

## What This Recipe Does Well

Worth preserving through editing:

- The 5:30 PM inbox opening is the best recipe opener in the book so far. Specific, human, immediately relatable. Keep it.
- The LLM failure-mode section is a reusable teaching unit. Hallucination, tone drift, over-helpfulness, prompt injection, context window, inconsistency. Concrete examples, not abstract warnings. Other chapters should reference this section rather than restate it.
- "It's not a chatbot. It's a drafting assistant." is the right framing for the human-in-the-loop design and should show up in any future recipe that needs the same posture.
- The VPC prerequisites are the strongest in any recipe so far. KMS endpoint included, interface vs. gateway distinction made, external EHR egress addressed, Bedrock endpoint name spelled out. This section can serve as the reference template for subsequent LLM recipes in Chapter 2.
- The Bedrock model-invocation-logging paragraph correctly identifies that audit logs are themselves PHI and that prompt caching has BAA implications. This nuance is missed in many real-world production systems.
- The Honest Take delivers: "the intent classification step matters more than the model choice" is exactly the kind of counterintuitive production insight the book promises. "Approval rate is your north star metric" gives the reader a concrete operational goal.
- The variations are genuinely useful (multi-language, smart routing, feedback loop, model fallback) rather than filler.
- Idempotency callout in Step 5 is the right level of detail for an MVP recipe: mentioned, with a one-line rationale, without going into full at-least-once-semantics theory.
- Cost estimate is realistic and verifiable.

---

*Review completed 2026-05-07. Four expert perspectives: security, architecture, networking, voice.*
