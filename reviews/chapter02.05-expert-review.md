# Expert Review: Recipe 2.5 - After-Visit Summary Generation

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-07
**Recipe file:** `chapter02.05-after-visit-summary-generation.md`

---

## Overall Assessment

**Verdict: FAIL**

This is a strong recipe in many respects. The grounded-generation framing ("the model is a writer, not a decision maker") is exactly right for patient-facing content. The health literacy discussion is substantive and correctly identifies reading level as a design constraint rather than a nice-to-have. The structured extraction-first pattern (turn the encounter into a fielded object, then generate from the object) is architecturally sound and reusable. The "Honest Take" delivers real production wisdom: the "subtle errors that erode trust" pattern is the exact failure mode this use case actually hits in the field. Clinical accuracy across most of the recipe is high, and the references (AHRQ, Joint Commission, Plain Writing Act, CDC CCI, HL7 FHIR) are real and relevant.

However, two issues cross into CRITICAL territory for a healthcare recipe, and they trigger the automatic-FAIL rule:

1. **A clinical inconsistency between the Problem narrative and the Sample Output.** The Problem section vividly describes counseling on a warfarin patient (dietary greens interaction, lab draw to check clotting, INR draw), but the Sample Output generates a summary for **apixaban** (a DOAC that does not interact with leafy greens and does not require INR monitoring). For a recipe whose core teaching is "every specific claim must trace to source," a recipe-internal mismatch between narrated clinical facts and a showcase output is the exact failure mode the recipe warns against.
2. **SMS delivery of clinical PHI content without a consent framework or content-limitation guidance.** The pseudocode and architecture ship medication names, dosing, warning signs, and follow-up instructions through Amazon Pinpoint SMS, with no mention of the HIPAA-required patient consent for unencrypted treatment communication, and no mention of the content-restriction patterns most health systems enforce (appointment-reminder-only for SMS, or notification-plus-portal-link for clinical content). Per the "healthcare compliance issues are always CRITICAL" rule, this is an automatic FAIL finding.

In addition, there are three HIGH findings (recurring Chapter 2 patterns: missing VPC endpoints, IAM permissions not scoped to resource ARNs, and the Bedrock model-invocation-logging PHI store) and a cluster of MEDIUM findings (idempotency, bounded regeneration, Step Functions HITL pattern, incomplete provenance in the sample output, inaccurate description of Bedrock Guardrails' capabilities).

Priority breakdown: 2 critical, 3 high, 6 medium, 5 low.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

- BAA is explicit in the Prerequisites table with all services in the pipeline named.
- S3 SSE-KMS with customer-managed keys is specified. DynamoDB CMK is specified. CloudWatch Logs KMS is specified. Parity across services.
- CloudTrail with data events is explicitly called out for Bedrock invocations, S3, and DynamoDB.
- Synthetic data warning is present; Synthea is referenced for test data.
- The "Log for audit" stage in the General Architecture Pattern correctly identifies that every version, edit, and delivery is PHI-relevant and must be retained for six-plus years.
- The grounding model ("the model is a writer, not a decision maker") is the right security posture for patient-facing content.

#### Finding S1: SMS Delivery of Clinical Content Without Consent Framework or Content Limitation

- **Severity:** CRITICAL
- **Expert:** Security / Compliance
- **Location:** "The Technology" section bullet on Delivery channel (line 59); "The General Architecture Pattern" Render for delivery channel + Deliver to patient paragraphs (lines 155, 157); Architecture Diagram (line 225); Ingredients table "Amazon Pinpoint" row (line 269); Step 7 pseudocode `render_and_deliver` (lines 579-603); "Why This Isn't Production-Ready" section (no discussion of SMS/PHI consent)
- **Problem:** The pipeline sends the generated clinical summary content through SMS. The pseudocode chunks the summary at `max_chars=320` and calls `Pinpoint.SendMessages` with each chunk. Chunked AVS content includes medication names, doses, warning signs, follow-up dates, and return-precaution instructions, which constitute PHI for treatment purposes. Under HIPAA, unencrypted SMS of treatment content to a patient requires the patient's informed consent after disclosure of the security risks (HHS OCR guidance on patient communication preferences, 45 CFR 164.522(b)). The recipe does not mention:
  1. That SMS is not encrypted end-to-end at the carrier level (it isn't, and that matters for PHI).
  2. That the patient must opt into SMS delivery of clinical content with informed consent, and that consent must be documented.
  3. That many health systems cap SMS content at non-PHI notifications (for example, "Your after-visit summary is ready, log in at [portal link]") rather than transmitting the clinical content itself.
  4. That specific jurisdictions (California, Texas, Washington with its new My Health My Data Act) have additional requirements on health data via SMS that go beyond HIPAA.
  
  A reader following this recipe ships a system that quietly transmits medication names and warning signs over an unencrypted channel whenever `patient_prefs.delivery_channel == "sms"`, with no consent gate and no content-minimization step. This is the kind of gap a compliance audit catches in week one, and it is exactly the class of issue the "healthcare compliance issues are always CRITICAL" rule is meant to flag.
  
- **Fix:** Do one of the following, ideally both:
  1. Change the SMS pattern in the pseudocode and the prose to the "notification-plus-portal-link" model: `rendered["sms_messages"] = [localize("Your after-visit summary is ready. Open it in the patient portal: {portal_link}", patient_prefs.language)]`. No clinical content in the SMS payload.
  2. If direct-to-SMS clinical content is retained as a pattern (some practices support it), add an explicit section in "Why This Isn't Production-Ready" titled "SMS and PHI" that names the consent requirement, the lack of end-to-end encryption on SMS, the content-minimization best practice, and the jurisdiction-specific overlays. Add a prerequisite check in Step 7 pseudocode: `IF "sms" in patient_prefs.delivery_channels AND patient_prefs.sms_phi_consent != "granted": fall back to notification-plus-link pattern.`
  
  Either fix is acceptable. Fix (1) is safer by default. Fix (2) is more flexible but must not ship without the consent gate and the warning section.

#### Finding S2: Clinical Inconsistency (Warfarin Narrative vs Apixaban Sample Output)

- **Severity:** CRITICAL
- **Expert:** Clinical Accuracy (filed under Security because it undermines the recipe's central safety argument)
- **Location:** Problem section, lines 9-15 (warfarin-style counseling: "diet (greens interact)," "lab draw in three days to check clotting," "they don't go for the INR draw"); Expected Results sample JSON, ~line 624 (apixaban 5 mg, CBC/kidney check in 3 days)
- **Problem:** The Problem section describes the cardiologist's counseling in specific clinical terms that only fit warfarin:
  - "careful attention to diet (greens interact)" → this is warfarin's vitamin K interaction with leafy greens. Apixaban has no such dietary restriction.
  - "a lab draw in three days to check clotting" → this is INR (PT/INR) monitoring, which only warfarin requires. Apixaban does not use INR monitoring.
  - "They don't go for the INR draw because the paper didn't mention it" → INR is warfarin-specific.
  
  The Sample Output in Expected Results shows the AVS generated for apixaban (Eliquis) 5 mg twice daily, with a "Blood test (CBC and kidney check) in 3 days" that is baseline safety labs for a DOAC, not a coagulation monitor. The Sample Output does not mention a dietary restriction, and correctly so for apixaban. So the Sample Output is clinically correct for apixaban, but it contradicts the counseling described in the Problem section, which is clinically correct only for warfarin.
  
  This is a recipe-internal inconsistency in the exact domain (anticoagulation counseling) where the recipe's central safety argument ("every specific claim must trace to source") is being made. A careful clinical reader will notice. More importantly, a reader following the "validate every claim against source" pattern cannot reconcile the narrative (warfarin facts) with the output (apixaban prescription) because the extraction step would produce one or the other, not both. The recipe is teaching grounding while simultaneously modeling a failure of grounding between its own sections.
  
- **Fix:** Pick one anticoagulant and use it consistently across the Problem narrative and the Sample Output.
  
  **Option A (warfarin throughout, recommended for the narrative strength):** Keep the Problem section as-is. Change the Sample Output to show warfarin (Coumadin) as the new medication, with dosing ("5 mg each evening"), INR monitoring ("INR draw in 3 days to check how fast your blood is clotting"), dietary instruction ("Keep your diet steady on leafy green vegetables. Do not suddenly start eating a lot more or a lot less."), and the same bleeding-warning list.
  
  **Option B (apixaban throughout):** Keep the Sample Output as-is. Rewrite the Problem section to describe apixaban counseling: stroke-risk discussion, twice-daily dosing, bleeding warning signs, baseline CBC/renal function lab, and no dietary restriction. The narrative loses the "INR draw" and "greens" specifics but gains a more modern clinical picture.
  
  Either fix works; the critical thing is internal consistency. A small additional fix: if the Problem section is meant to highlight "no specific information reached the paper," then the concrete items the cardiologist discussed should all be representable in the structured summary object and present in the Sample Output, so the reader can see the before-and-after contrast directly.

#### Finding S3: IAM Permissions Not Scoped to Resource ARNs

- **Severity:** HIGH
- **Expert:** Security
- **Location:** Prerequisites table, "IAM Permissions" row (~line 244)
- **Problem:** The permissions list (`bedrock:InvokeModel`, `bedrock:ApplyGuardrail`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:UpdateItem`, `states:StartExecution`, `healthlake:SearchWithGet`, `comprehendmedical:DetectEntitiesV2`, `ses:SendRawEmail`, `mobiletargeting:SendMessages`, `events:PutEvents`) is listed as bare actions with no resource-ARN scoping. A reader who implements these directly grants Lambda roles access to every bucket, table, model, datastore, and messaging endpoint in the account. This is the same finding that came up in Recipes 2.2, 2.3, and 2.4 reviews and has not been addressed as a cross-chapter pattern.
- **Fix:** Add a note beneath the permissions list: "Scope each action to specific resource ARNs. Examples: `s3:GetObject`/`s3:PutObject` scoped to the specific AVS bucket and extraction-archive bucket ARNs; `dynamodb:*` scoped to the `avs-summaries` and `patient-preferences` table ARNs; `bedrock:InvokeModel` scoped to the specific foundation-model ARNs for extraction and generation models (for example, `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-*` and `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-*`); `bedrock:ApplyGuardrail` scoped to the specific Guardrail ARN; `healthlake:SearchWithGet` scoped to the specific datastore ARN; `comprehendmedical:DetectEntitiesV2` does not support resource-level IAM but can be restricted via SCP or condition keys; `ses:SendRawEmail` scoped to the verified identity ARNs used for patient email. Add `kms:Decrypt` and `kms:GenerateDataKey` scoped to the specific CMKs used for S3, DynamoDB, and CloudWatch Logs."

#### Finding S4: Bedrock Model-Invocation-Logging Creates an Unaddressed PHI Store

- **Severity:** HIGH
- **Expert:** Security
- **Location:** Prerequisites table "Encryption" and "CloudTrail" rows; Steps 3 and 4 pseudocode (every Bedrock call)
- **Problem:** Each AVS generation makes at least two Bedrock calls (extraction and generation), plus zero-to-N regeneration calls if validation or readability fails. Each prompt carries PHI: structured clinical facts, diagnoses, medication doses, follow-up details, and patient identifiers (preferred name at minimum). If a reader enables Bedrock model-invocation-logging to monitor drift, debug quality issues, or satisfy internal audit requirements (a common production choice), the logged prompts and responses land in an S3 bucket or CloudWatch Logs log group, creating an additional PHI store that is not in the recipe's prerequisites. The same finding was raised for Recipe 2.4 and is specifically called out in Recipe 2.1. It has not propagated to this recipe.
- **Fix:** Add a short paragraph either in the Prerequisites "Encryption" row or in the "Why This Isn't Production-Ready" section: "If Bedrock model-invocation-logging is enabled for quality monitoring or drift detection, the logged prompts contain PHI (structured clinical facts, patient identifiers, medication details). The log-destination S3 bucket or CloudWatch log group must be KMS-encrypted with the same CMK used for other PHI stores, access-controlled equivalently, and subject to the same retention policy. Consider sampling rather than logging every invocation."

#### Finding S5: PHI Minimization in Prompts Not Discussed

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Step 3 `extract_summary_object`; Step 4 `generate_summary`
- **Problem:** Step 3 sends the full concatenated clinical note text to Bedrock (`note_text = concatenate all encounter_data.notes[*].content`). Step 4 sends the extracted summary object, which typically includes the patient's preferred name and may include other identifiers. For an AVS, the note is the authoritative source, so some PHI exposure to the LLM is unavoidable, but the "minimum necessary" principle still applies: the patient's MRN, date of birth, address, phone number, and insurance-card identifiers are not needed by the generation step and should not be sent. The recipe does not discuss this.
- **Fix:** Add a short paragraph in the Step 3 walkthrough or in "Why This Isn't Production-Ready": "The minimum-necessary principle applies to prompts. The generation step needs diagnoses, medications, orders, and follow-up details; it does not need the patient's MRN, DOB, address, phone number, or insurance identifiers. Consider redacting non-clinical PHI from the extracted object before the generation call, either via a regex allow-list on the object's fields or via Amazon Comprehend Medical's `DetectPHI` API as a pre-flight check. The preferred name is an exception because it appears in the salutation; keep that and strip the rest."

#### Finding S6: Sample Output Not Labeled Synthetic

- **Severity:** LOW
- **Expert:** Security
- **Location:** Expected Results section (sample JSON, ~line 624)
- **Problem:** The sample output contains `"summary_id": "AVS-2026-05-07-01284"` and includes "Dr. Nguyen" with a May 21 follow-up date and a phone number `(555) 123-4567`. These are clearly synthetic but the JSON block is not labeled as such. This matches the same minor issue called out in Recipe 2.4.
- **Fix:** Add a one-line comment above the JSON block: `// All identifiers, dates, and provider names in this sample are synthetic. Never use real patient data in development or test fixtures.`

---

### Architecture Expert Review

#### What's Done Well

- Structured-extraction-first (turn the note into a fielded object) is the right architectural move for safety-critical patient-facing content. It's what makes the validation step feasible.
- Per-section generation is correctly identified as more controllable than single-prompt generation for multi-topic documents. The trade-off is named honestly.
- Step Functions for orchestration is the correct choice for a workflow with branching logic (review-or-not, regeneration loops, multi-channel delivery).
- The decision to split model tiers (cheaper Haiku for extraction, stronger Sonnet for generation) is sound and cost-aware.
- Cost estimate appears reasonable. Unlike Recipe 2.4 which had a multi-criterion loop, this pipeline is mostly a one-shot generation. At Claude Sonnet 4 pricing (~$3/M in, $15/M out), a generation call with ~2.5K input tokens and up to 6K output tokens is roughly $0.10. Add Haiku extraction (~$0.005) and optional Comprehend Medical (~$0.01). End-to-end $0.03-0.10 is defensible.
- The "Why This Isn't Production-Ready" section correctly identifies the real killers: note quality, "what's new today" extraction across EHR representations, reading-level validation for non-English languages, clinician-review workflow governance, portal integration, and legal review of auto-generated patient content. All six are accurate.

#### Finding A1: Regeneration Loop Is Unbounded

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 5 `validate_summary` (status `VALIDATION_FAILED` triggers regeneration); Step 6 `check_readability` ("If the readability check fails, the pipeline loops back to Step 4"); General Architecture Pattern validation-fail and readability-fail branches
- **Problem:** Two feedback loops exist (validation → regenerate, readability → regenerate) with no retry cap specified in the pseudocode. Same prompt, same temperature, same inputs can produce the same failure indefinitely. At $0.03-$0.10 per attempt, this is financially bounded at small-fleet scale, but at 1,000 visits per day an infinite loop on a pathological encounter costs real money and delays delivery past the patient's departure from the parking lot. The Python companion's code reviewer already flagged a related issue: the orchestrator has `MAX_GENERATION_ATTEMPTS` but handles the exhaustion case unsafely. The main recipe's pseudocode doesn't declare a cap at all.
- **Fix:** Add to Step 5 and Step 6 pseudocode: "Cap regeneration at 2-3 attempts. Vary the strategy on each retry: first retry with a stronger grounding instruction that names the previously-unverified claims; second retry at temperature=0 for determinism; third retry falls through to clinician review rather than continuing to regenerate. Track retry count per summary in DynamoDB and emit a CloudWatch metric when a summary exhausts retries. Never auto-deliver an exhausted-retry summary without clinician sign-off."

#### Finding A2: Step Functions Human-in-the-Loop Pattern Not Described

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Architecture Diagram "Clinician Review UI" node; "AWS Step Functions for orchestration" paragraph (line ~177); General Architecture Pattern "Optional clinician review" stage
- **Problem:** The diagram shows a "Clinician Review UI" branch and the text mentions Step Functions "makes the state machine explicit and observable," but no pattern is specified for how the workflow pauses while waiting for a human signature. Step Functions supports the `waitForTaskToken` callback pattern for exactly this. Without that pattern, a reader will implement polling (expensive in state transitions) or a second workflow with EventBridge (workable but more moving parts). Same finding was flagged in Recipe 2.4 review.
- **Fix:** Add a sentence to the Step Functions paragraph: "For the clinician-review branch, use the Step Functions `waitForTaskToken` pattern. The Lambda that completes the generation hands off a task token when it routes to review; the review UI calls `SendTaskSuccess` with the signed summary (and any edits) when the clinician completes review, or `SendTaskFailure` if the summary is rejected. Token lifetime on Step Functions supports extended hold times, which is useful for review SLAs longer than a few minutes."

#### Finding A3: Idempotency Not Discussed

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 1 `receive_note_signed_event`; EventBridge ingress
- **Problem:** Note-signed events can arrive twice. Reasons: EHR integration retry on perceived timeout, operator un-sign/re-sign during a correction, duplicate subscription from the integration layer. Each duplicate triggers a fresh Step Functions execution with a new `summary_id` and produces an additional summary, a duplicate LLM bill, and potentially duplicate delivery to the patient (two portal documents, two emails, two SMS bursts). The recipe does not discuss idempotency. Same finding raised for Recipe 2.4.
- **Fix:** Add to Step 1 pseudocode or "Why This Isn't Production-Ready": "Derive a deterministic fingerprint from `(encounter_id, note_version_or_signed_at)` and use a DynamoDB conditional write (`attribute_not_exists(fingerprint)`) before starting a new Step Functions execution. If the fingerprint already exists, return the existing `summary_id` and skip. This prevents duplicate summaries when the EHR publishes the note-signed event more than once."

#### Finding A4: "Contextual Grounding" Confused with Bedrock Guardrails Capabilities

- **Severity:** MEDIUM
- **Expert:** Architecture / Accuracy
- **Location:** "Amazon Bedrock Guardrails for safety constraints" paragraph (~line 172): "For patient-facing output, you can configure denied topics (e.g., block generation of content that contradicts the source note)"
- **Problem:** The parenthetical example is incorrect as stated. Bedrock Guardrails "denied topics" are defined by natural-language topic descriptions and blocklist phrases; they cannot detect "content that contradicts the source note" because that requires per-request comparison against the note, which denied-topics does not perform. The feature the recipe is actually reaching for is Bedrock Guardrails' **contextual grounding check**, which is a separate Guardrails policy that compares the model output against a reference context provided at invocation time and rejects outputs below configurable grounding/relevance thresholds. A reader following the recipe as written will configure a denied topic that does nothing useful for the stated goal.
- **Fix:** Change the parenthetical to: "contextual grounding checks (which compare the model's output to the source note and reject outputs that are ungrounded or off-topic), denied topics (for example, blocking any language that recommends specific treatments not originally prescribed), PII detection (to catch accidental disclosure of other patients' data), and content filters (standard safety filters)." Keep the point that Guardrails is a policy layer and not a substitute for the explicit validation step.

#### Finding A5: Sample Output Provenance Is Sparse Relative to Summary Content

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Expected Results sample JSON, `"factual_claims"` array (~line 624)
- **Problem:** The sample summary contains roughly 20+ specific claims (atrial fibrillation diagnosis, stroke-risk framing, apixaban name, dose, timing, start instruction, CBC/kidney-check instruction, result-delivery phrasing, follow-up date and time, follow-up clinician, full call-911 warning list, full call-during-day list, three lifestyle instructions, practice phone number, practice hours). The provenance list in the JSON contains only 5 entries. For a recipe that teaches "every specific claim must trace to source," the showcase output models an incomplete trace. A reader following this pattern would build a validator that catches only 5 of the 20+ claims the model actually made, which misses the whole point of the architecture.
- **Fix:** Expand the `factual_claims` array in the sample output to enumerate the full set of specific claims with source-field paths: diagnoses[0] for the atrial fibrillation name, warning_signs[*] for each bleeding-warning item, education_topics[*] or lifestyle_instructions[*] for "Tell any doctor or dentist...", "Avoid contact sports...", and similar, practice_info for the phone number and hours, and so on. A dozen-plus entries, not five. Alternatively, add a note beneath the sample: "The `factual_claims` array in this sample is abbreviated for readability. A production validator enumerates every specific claim, typically 15-30 per AVS."

#### Finding A6: EventBridge Delivery Not Idempotent by Default

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** Architecture Diagram (EventBridge → Step Functions); "Amazon EventBridge for note-signed events" paragraph
- **Problem:** EventBridge has at-least-once delivery. Without idempotency at the workflow entry point (see Finding A3), a single EHR publish can produce two Step Functions executions. This is the engineering detail that makes Finding A3 necessary; flagging it here as context, and it can be folded into A3's fix.
- **Fix:** Covered by A3's fingerprint pattern.

---

### Networking Expert Review

#### What's Done Well

- VPC with VPC endpoints is listed as a production prerequisite rather than an afterthought.
- TLS in transit is listed.
- CloudTrail data-events requirement is specific about which operations must be logged.

#### Finding N1: VPC Endpoint List Is Incomplete for the Services the Recipe Uses

- **Severity:** HIGH
- **Expert:** Networking
- **Location:** Prerequisites table, "VPC" row (~line 249): "Production: Lambda functions in VPC with VPC endpoints for S3, Bedrock, DynamoDB, HealthLake, Comprehend Medical."
- **Problem:** The listed endpoints cover only five of the services the recipe actively integrates with. Missing endpoints for a private-subnet deployment:
  - `com.amazonaws.{region}.kms` — required for every S3 SSE-KMS read, DynamoDB CMK read, and CloudWatch Logs KMS write. Without it, Lambda in a private subnet cannot decrypt any KMS-protected resource. Same finding from Recipes 2.2, 2.3, 2.4.
  - `com.amazonaws.{region}.logs` — CloudWatch Logs writes from Lambda.
  - `com.amazonaws.{region}.states` — Step Functions API calls from within a VPC-resident Lambda (`SendTaskSuccess` and `SendTaskFailure` for the HITL pattern in Finding A2).
  - `com.amazonaws.{region}.events` — EventBridge `PutEvents` if any Lambda publishes downstream events (delivery-confirmed, regeneration-exhausted).
  - `com.amazonaws.{region}.email-smtp` or SES interface endpoint — SES calls for secure email delivery.
  - `com.amazonaws.{region}.sms-voice` — End User Messaging SMS (successor to Pinpoint SMS) interface endpoint. If the recipe's SMS pattern is kept per Finding S1, this endpoint is required for private-subnet SMS dispatch.
  - `com.amazonaws.{region}.translate` — if the Translate fallback path is used for non-English generation.
  - `com.amazonaws.{region}.monitoring` — CloudWatch metrics emission for operational dashboards.
  
  Note: Bedrock Knowledge Bases is NOT used in this recipe (extraction-from-note pattern, not RAG over a corpus), so `bedrock-agent-runtime` is correctly absent. This is the correct distinction from the Recipe 2.4 finding.
  
  A reader who provisions only the listed five endpoints will have Lambda that can pull encounter data from HealthLake, call Bedrock, and read/write S3 and DynamoDB, and will then fail on the first KMS data-key operation, CloudWatch Logs write, Step Functions task-token callback, SES call, or SMS call.
- **Fix:** Expand the VPC row to: "Production: Lambda functions in VPC with interface VPC endpoints for `bedrock-runtime`, `kms`, `healthlake`, `comprehendmedical`, `states`, `events`, `logs`, `monitoring`, `sms-voice` (if SMS is used), `email-smtp` (if SES is used), `translate` (if the Translate fallback is used), and gateway endpoints for `s3` and `dynamodb`. Interface endpoints are billed per AZ per hour (~$7-10/month each); this adds a meaningful line item to the cost estimate at production scale."

#### Finding N2: EHR Connectivity Not Discussed

- **Severity:** MEDIUM
- **Expert:** Networking
- **Location:** Prerequisites "EHR Integration" row (~line 247); "Why This Isn't Production-Ready" section (no network discussion for EHR integration)
- **Problem:** The recipe correctly identifies that AVS generation must fire on the note-signed event, which requires a reliable path from the EHR to EventBridge (or to a bridging component that republishes as EventBridge events). The network path is not discussed. For cloud EHRs (Epic on Azure, athenaOne), this typically means TLS egress to the vendor's cloud or webhook delivery via the vendor's outbound integration. For on-premises EHRs (Meditech, Allscripts Professional, Cerner Millennium still on-prem), it typically means a local integration engine (Mirth, Rhapsody, Corepoint) reaching AWS via Direct Connect, VPN, or PrivateLink. Each path has different security posture and different PHI-in-transit considerations.
- **Fix:** Add a sentence or two in "Why This Isn't Production-Ready" near the portal-integration paragraph: "Connectivity from the EHR to your pipeline also matters. For cloud EHRs, the note-signed event and the FHIR pull typically cross TLS-encrypted connections to the vendor's public endpoints, with egress security groups and vendor credentials in Secrets Manager. For on-premises EHRs, plan for Direct Connect or site-to-site VPN, with the FHIR gateway reachable over private IPs only. PHI in transit must never traverse the public internet unencrypted, and inbound traffic to your VPC should be scoped by source IP or by PrivateLink."

#### Finding N3: Patient Email Delivery Pathway and Deliverability Not Discussed

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Step 7 `render_and_deliver`, SES call; "Amazon Pinpoint or Amazon SES for delivery" paragraph
- **Problem:** SES delivery of a PDF attachment to a patient's personal email (Gmail, iCloud, Outlook.com) is not end-to-end encrypted unless the patient's mail provider honors opportunistic TLS and both ends negotiate it successfully. For PHI content in the attachment, health systems typically use a secure-email gateway that pushes a notification to the patient with a link to a portal-style reader, not the PHI itself in the message body or attachment. The recipe does not distinguish these patterns and says only "Secure email delivery with PDF attachment."
- **Fix:** Add a sentence in the SES row of the Ingredients table or in the Step 7 walkthrough: "Direct SES delivery of a PDF-attachment AVS to a patient's personal mailbox is secure only if both mail servers enforce TLS, which is not guaranteed. Production deployments typically route AVS email through a HIPAA-grade secure-email gateway (Zix, Proofpoint Encryption, or an EHR-provided patient-email channel) or use SES only for a notification-plus-portal-link pattern similar to the recommended SMS pattern."

---

### Voice Reviewer

#### What's Done Well

- Opening scenario (the 68-year-old, the folded piece of paper, the boilerplate summary, the things actually said in the room versus what reached the paper) is concrete, specific, and emotionally engaging. Exactly the voice the style guide asks for.
- "This is the kind of problem that LLMs are uncommonly good at" is the right turn for the Problem-to-Technology handoff.
- No em dashes detected anywhere in the file (scan for U+2014 returned zero matches).
- 70/30 vendor balance is maintained. Part 1 (Problem, Technology, General Architecture) is entirely vendor-neutral. AWS service names enter cleanly in the implementation section and do not leak backward into the conceptual material.
- "The Honest Take" is genuinely excellent. The "quietly wrong in small ways" pattern is the real production failure mode for this use case. The three lessons (validation-before-generation, don't over-automate clinician review, plain-language-is-the-point) are hard-won wisdom.
- No marketing language detected ("leverage," "empower," "seamless," "unlock," "transform" all absent).
- The Variations section offers five concrete extensions with real technical substance (discharge summaries with structured handoff, audio via Polly, medication-reconciliation reminders, teach-back verification, chronic-disease protocol integration). All five are genuinely useful and not fluff.

#### Finding V1: Three Unresolved TODO Markers in Published Prose

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Line 13 (Kessels-style forgetting statistics), Line 17 (readmission statistics), ~Line 650 (portal open rate), ~Line 730 (Recipe 11.x cross-reference)
- **Problem:** Four unresolved TODO markers remain as HTML comments in prose that is otherwise ready for editing. Style-guide rule "No fake GitHub URLs. Only verified links." extends by implication to unverified statistics that are flagged but not resolved. The forgetting-percentages TODO and the readmission-rate TODO are load-bearing for the Problem section's rhetorical weight; readers see confident numbers (40-80%, 20-25%) that the author's own comment flags as unverified. HTML comments can leak to view-source or to certain Markdown-to-HTML pipelines.
- **Fix:** Resolve the TODOs before publication:
  - Kessels forgetting percentages: cite Kessels RP, "Patients' memory for medical information," J R Soc Med 2003;96:219-222 for the 40-80% and add a parenthetical "still widely cited, though the original studies are dated; a 2018 meta-analysis (Laws et al.) confirmed the range."
  - Readmission statistics: cite CMS Hospital Readmissions Reduction Program (HRRP) data for a specific recent year; the ~22-24% figure for heart failure has been stable.
  - Portal open rate: either cite a specific case study (Epic MyChart or Cerner HealtheLife published data) or remove the row and replace with a prose sentence: "Portal open rates for AVSs vary by practice and implementation; plan to measure your own baseline rather than rely on a single vendor's case-study number."
  - Recipe 11.x: pick the correct Chapter 11 recipe or remove the cross-reference.

#### Finding V2: Informal Bedrock Model IDs in Pseudocode

- **Severity:** LOW
- **Expert:** Voice / Accuracy
- **Location:** Step 3 (`model_id = "anthropic.claude-haiku-4"`), Step 4 (`model_id = "anthropic.claude-sonnet-4"`)
- **Problem:** Pseudocode uses family-style model IDs. Real Bedrock model IDs are versioned (for example, `anthropic.claude-3-5-sonnet-20241022-v2:0`) and in most regions now require an inference-profile prefix (for example, `us.anthropic.claude-3-5-sonnet-20241022-v2:0`). A reader copying the pseudocode directly will hit `ValidationException: The provided model identifier is invalid.` Same finding from Recipe 2.4; Python companion uses the full versioned form per the code review.
- **Fix:** Add a one-line comment on first use in Step 3 pseudocode: `// In production, use the versioned model ID with inference profile prefix. See the Python companion for a current working example.` No code change required beyond the comment.

#### Finding V3: "8th-grade reading level" Statistic Is Dated

- **Severity:** LOW
- **Expert:** Voice / Accuracy
- **Location:** Problem section, line 13: "The average American adult reads at roughly an 8th-grade level."
- **Problem:** This statistic traces back to the NAAL 2003 survey, where "Intermediate" adult literacy was interpreted as roughly 8th grade. Subsequent PIAAC surveys (most recent: 2017 PIAAC, with a 2023 update in progress) frame adult literacy in terms of five proficiency levels; roughly 54% of US adults score at Level 3 or below, and about 1-in-5 at Level 1. The "8th-grade level" shorthand is still widely used by CDC and AHRQ and is not wrong, but it is shorthand, not a directly measurable quantity. Given that the broader Problem section is arguing for reading-level precision, the shorthand deserves a light hedge.
- **Fix:** Optional. Consider "AHRQ and CDC recommend targeting a 6th-to-8th-grade reading level for patient materials; survey data on adult reading proficiency (NAAL, PIAAC) consistently shows that a large fraction of US adults struggle with text written above that range." This keeps the point without the contestable "average" framing.

#### Finding V4: Polly Audio Variation Lacks BAA/PHI Note

- **Severity:** LOW
- **Expert:** Voice / Accuracy
- **Location:** Variations and Extensions, "Video or audio summary for low-literacy patients" paragraph
- **Problem:** The variation says "Amazon Polly converts the generated text to speech with natural-sounding voices in dozens of languages." Polly is HIPAA-eligible, but the audio output is PHI and must be stored (or streamed) with the same protections as the text AVS. The paragraph does not mention this. A reader following this variation might put audio files on a non-HIPAA-encrypted bucket.
- **Fix:** Add a one-line note: "Polly is HIPAA-eligible; the generated audio is PHI and must be stored with the same KMS encryption and access controls as the rest of the AVS archive."

---

## Stage 2: Expert Discussion

**Conflict: Security (SMS consent/content limitation) vs. Architecture (multi-channel delivery convenience).**
The security expert marks SMS of clinical content as CRITICAL because the absence of a consent gate and content-minimization pattern is a HIPAA exposure. The architecture expert notes that SMS delivery is commonly offered by health systems for patients without portal access or smartphone access, and removing the option entirely reduces the recipe's real-world applicability. Resolution: the security concern wins because compliance is non-negotiable, but the recommended fix preserves SMS as a delivery path by pivoting to "notification-plus-portal-link" rather than removing the channel. Both experts support this fix.

**Overlap: Clinical accuracy (warfarin/apixaban) and the recipe's central safety argument.**
The clinical inconsistency and the grounding-architecture teaching are tightly coupled. The recipe's case for its architectural pattern is "every specific claim must trace to source," but the Problem narrative and the Sample Output describe specific claims that don't trace to each other. Fixing the inconsistency is not optional; the fix strengthens the teaching rather than softening it.

**Overlap: Architecture (Bedrock Guardrails confusion) and the recipe's grounding claim.**
If the recipe is going to claim Guardrails as a safety layer for "ungrounded content," it needs to reference the correct feature (contextual grounding check, a specific Guardrails policy type) rather than misstate denied-topics as solving the grounding problem. The fix improves both technical accuracy and the recipe's credibility.

**Overlap: Networking (VPC endpoints) and Security (KMS-via-endpoint).**
The KMS encryption posture in the security section requires the KMS VPC endpoint in the networking section. Treated as a coupled pair; addressing one without the other yields a non-functional private-subnet deployment.

**No conflicts on the rest of the architecture.** The structured-extraction-first pattern, the per-section generation trade-off, the Step Functions orchestration choice, and the model-tier split are all validated across experts.

---

## Stage 3: Synthesized Feedback

## Verdict: FAIL

Two CRITICAL findings auto-fail the recipe per the review rubric. The critical issues are not structural design flaws; they are (1) a clinical inconsistency that is fixable with a small rewrite of either the Problem narrative or the Sample Output, and (2) a compliance gap in SMS delivery that is fixable by shifting to a notification-plus-portal-link pattern or adding an explicit consent/content-limitation section. Both fixes are well-scoped and leave the recipe's core architecture and teaching value intact.

Three HIGH findings (VPC endpoints, IAM scoping, Bedrock model-invocation-logging PHI) are the same recurring Chapter 2 pattern that has appeared across 2.2, 2.3, 2.4 reviews. These are production-hardening gaps, not design flaws. The MEDIUM findings (bounded regeneration, Step Functions HITL pattern, idempotency, Guardrails capability description, sample-output provenance completeness, PHI minimization in prompts) are meaningful but tractable. The LOW findings are polish items.

Once the CRITICAL and HIGH findings are addressed, this recipe has a clear path to PASS. It is one of the stronger use-case recipes in Chapter 2 in terms of clinical framing, architectural pattern, and honest-take quality.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| S1 | CRITICAL | Security/Compliance | Step 7, Architecture Diagram, Ingredients, Technology section | SMS ships clinical PHI without consent framework or content-minimization pattern |
| S2 | CRITICAL | Clinical Accuracy | Problem (lines 9-15) vs Sample Output (~line 624) | Problem describes warfarin counseling; Sample Output shows apixaban prescription |
| S3 | HIGH | Security | Prerequisites, IAM row | Permissions not scoped to resource ARNs (recurring Chapter 2 pattern) |
| S4 | HIGH | Security | Prerequisites Encryption row; all Bedrock calls | Model-invocation-logging creates PHI store not addressed |
| N1 | HIGH | Networking | Prerequisites, VPC row | Missing `kms`, `logs`, `states`, `events`, `sms-voice`, `email-smtp`, `translate`, `monitoring` endpoints |
| A1 | MEDIUM | Architecture | Step 5, Step 6, General Architecture Pattern | Regeneration loops unbounded; no retry cap or strategy variation |
| A2 | MEDIUM | Architecture | Architecture Diagram; Step Functions paragraph | Human-in-the-loop pattern (task token vs polling) not specified |
| A3 | MEDIUM | Architecture | Step 1 `receive_note_signed_event` | No idempotency against duplicate note-signed events |
| A4 | MEDIUM | Architecture/Accuracy | Bedrock Guardrails paragraph (~line 172) | "Denied topics" miscast as grounding check; correct feature is contextual grounding check |
| A5 | MEDIUM | Architecture | Expected Results sample JSON `factual_claims` | Provenance array covers ~5 of ~20+ specific claims; under-teaches validation |
| S5 | MEDIUM | Security | Step 3, Step 4 | PHI minimization in prompts not discussed (MRN, DOB, address unnecessary) |
| N2 | MEDIUM | Networking | Prerequisites EHR row; Production-Ready section | EHR network connectivity (Direct Connect, PrivateLink, VPN) not discussed |
| A6 | LOW | Architecture | EventBridge ingress | At-least-once delivery needs idempotency (folded into A3) |
| S6 | LOW | Security | Sample Output JSON | Synthetic labels not called out on sample identifiers |
| N3 | LOW | Networking | Step 7 SES path; Ingredients | Patient email deliverability/TLS-to-personal-mailbox not discussed |
| V1 | LOW | Voice | Lines 13, 17, 650, 730 | Three unresolved TODO markers in published prose |
| V2 | LOW | Voice/Accuracy | Step 3, Step 4 pseudocode | Informal Bedrock model IDs (`anthropic.claude-haiku-4`, etc.) |
| V3 | LOW | Voice/Accuracy | Problem section line 13 | "8th-grade reading level" shorthand from NAAL 2003 is dated |
| V4 | LOW | Voice/Accuracy | Variations section, Polly audio | HIPAA eligibility and PHI handling for Polly output not mentioned |

---

## Recommended Actions (Priority Order)

1. **Resolve the clinical inconsistency** (Finding S2). Pick one anticoagulant (warfarin or apixaban) and use it consistently across Problem narrative and Sample Output. Recommended: warfarin throughout, because the Problem section's specific details (greens, INR, three-day clotting check) are all clinically strong teaching points and are easier to keep than to replace.

2. **Fix SMS PHI delivery** (Finding S1). Change the SMS pattern to "notification-plus-portal-link" by default in the pseudocode and prose. If direct-to-SMS clinical content is retained as an option, add a dedicated subsection in "Why This Isn't Production-Ready" on SMS/PHI consent, content-minimization best practice, and the patient-consent gate at delivery time.

3. **Expand the VPC endpoint list** (Finding N1) to include `kms`, `logs`, `states`, `events`, `sms-voice`/`email-smtp` (as applicable), `translate`, `monitoring`.

4. **Scope IAM permissions** (Finding S3) with resource-ARN guidance. Consider making this a standard Chapter 2 appendix pattern since it has now appeared across four consecutive reviews.

5. **Add the Bedrock model-invocation-logging PHI note** (Finding S4) in the Prerequisites Encryption row or "Why This Isn't Production-Ready."

6. **Correct the Bedrock Guardrails description** (Finding A4) to reference contextual grounding check, not denied topics, for the grounding use case.

7. **Cap regeneration loops** (Finding A1) at 2-3 attempts with strategy variation and explicit fallback to clinician review.

8. **Specify the Step Functions HITL pattern** (Finding A2): `waitForTaskToken` callback, not polling.

9. **Add idempotency guidance** (Finding A3) via fingerprint + conditional DynamoDB write in Step 1.

10. **Expand the sample-output provenance array** (Finding A5) or add a note that the array is abbreviated for readability.

11. **Add PHI minimization guidance** (Finding S5) for LLM prompts.

12. **Add EHR connectivity paragraph** (Finding N2) in "Why This Isn't Production-Ready."

13. **Resolve the TODO markers** (Finding V1): Kessels citation, readmission data citation, portal open-rate removal or citation, Recipe 11.x cross-reference.

14. **Add model-ID versioning note** (Finding V2) in pseudocode.

15. Optional polish: hedge the 8th-grade-level claim (V3), add Polly HIPAA note to the audio variation (V4), label sample output as synthetic (S6), add SES-to-personal-mailbox deliverability note (N3).

---

## Notes for Editor

- The two CRITICAL findings are both fixable with targeted rewrites. The clinical inconsistency is the higher-leverage fix because it lands directly on the recipe's core teaching point (grounding). The SMS fix is also straightforward and preserves SMS as a delivery channel via the notification-plus-link pattern.
- The three HIGH findings (VPC endpoints, IAM scoping, model-invocation-logging PHI) have now appeared in Recipes 2.2, 2.3, 2.4, and 2.5. This is a clear pattern. Consider a Chapter 2 preface or appendix that captures the "standard production hardening checklist" once, so each individual recipe can reference it rather than re-state it and each per-recipe review can stop rediscovering it.
- The recipe is long (~4,000+ words). The length is earned. The Problem section, the Technology section, and the Honest Take all do real work. The General Architecture Pattern is correctly vendor-neutral. The AWS Implementation section is appropriately detailed without becoming a documentation dump.
- The code reviewer has already caught related issues in the Python companion (UTF-8 mojibake in non-English instruction strings, orchestrator fail-open on exhausted regeneration attempts, Comprehend Medical byte-vs-character truncation). Ensure those fixes land alongside the main-recipe fixes so the two files stay consistent.
- The references (AHRQ Universal Precautions, Joint Commission, Plain Writing Act, CDC Clear Communication Index, HL7 FHIR Encounter, SMART on FHIR) are all real and correctly cited.
- No em dashes found in the file. Voice reviewer confirms the file passes on the prose rules.
- The Variations section is unusually strong (discharge summaries, audio, med-rec reminders, teach-back, chronic-disease protocols). Five substantive extensions, each with enough detail to act on. Editor may want to consider whether teach-back and med-rec reminders deserve their own future recipes because they are large enough topics to stand alone.
