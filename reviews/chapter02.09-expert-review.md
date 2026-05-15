# Expert Review: Recipe 2.9 - Clinical Decision Support Synthesis

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-15
**Recipe file:** `chapter02.09-clinical-decision-support-synthesis.md`

---

## Overall Assessment

**Verdict: PASS**

The recipe is one of the most clinically substantive in the chapter. The five opening vignettes (2 AM ICU sepsis with CKD and apixaban, primary care diabetes intensification with multiple specialty-society-guideline emphases, oncology first-line therapy with QT prolongation and SSRI interaction, vancomycin nephrotoxicity lost in alert noise, alert fatigue as the design force) are the chapter's most authentic clinician-language opening, and they each tee up a specific architectural property the body of the recipe defends. The CDS-vs-literature-search comparison ("Recipe 2.7 was descriptive; this is patient-specific and prescriptive") is the right framing and is delivered with five concrete divergences (source types, patient context as primary retrieval driver, contradictions as first class, regulatory posture, alert fatigue as design force). The "FDA CDS Rule: Where This Becomes a Medical Device" subsection lays out the four-part exemption test, calls the "independently review the basis" criterion as the one doing the most work, and translates the test into specific architectural implications (sources prominent, framing as suggestions, UI invites judgment, documentation comprehensive). The "Failure Modes You Have to Design Around" enumeration (fabricated recommendation, fabricated dose, missed interaction, missed contraindication, population mismatch, wrong side of equipoise, stale guidance, over-confident recommendation, recommendation bypasses clinician judgment, recommendation out of scope, formulary mismatch, regulatory drift) is dense, specific, and each item has a real mitigation tied to either deterministic checks, retrieval design, prompt discipline, or post-generation validation. The deterministic-safety-check layer (Step 4) is the architecturally correct posture: drug interactions, allergy conflicts, renal/hepatic dosing, contraindications, and duplicate therapy are structured database operations whose results become hard-coded inputs to the generation step, not LLM-derived findings; the validator in Step 9 then enforces that the deterministic findings appear in the synthesis output. This is exactly the architecture the recipe's prose argues for, and it is exactly the architecture the chapter's working CDS deployments use.

Chapter 2 hygiene patterns mostly carry through. No em dashes (direct U+2014 / U+2013 character check: zero matches across approximately 1450 lines). No bracket-style visible TODO markers; the five surviving TODOs are all HTML-comment placeholders for cross-references into chapters 5, 7, and 13 that have not been drafted yet. No marketing language ("leverage," "seamless," "unlock," "transform," "empower," "revolutionize" all absent; "state-of-the-art" absent). IAM row says "Scope every action to specific resource ARNs." Bedrock model-invocation-logging PHI store is called out in the Encryption row with the correct framing. The 70/30 vendor balance is clean: the conceptual sections (Problem, Technology, General Architecture Pattern) are vendor-neutral; AWS service names enter in the AWS Implementation section and stay there. The "Honest Take" is publication-ready and lands the right final posture: avoid breadth-over-depth, invest in the retrieval layer, build safety as deterministic checks (not LLM prompts), measure clinician engagement and outcomes (not delivery counts), defer regulatory review at your peril, ship without clinician buy-in at your peril, foreground reasoning over recommendations.

One HIGH finding stands out: the architecture diagram's validation-retry branch has the same shape as Recipes 2.6 and 2.7, with a `S17 -->|No| S15` edge that loops back to generation with no retry cap, no exit edge to a human-review queue, and no distinct terminal state for "validation exhausted." Step 9's pseudocode does have a `VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW` terminal state, but the orchestration walkthrough between Step 9 (validation) and Step 10 (tier/suppress/render) does not model what happens when validation returns that state. The corresponding code review for the Python companion (`reviews/chapter02.09-code-review.md`, Finding 1) confirms the Python-side instance: the orchestrator's retry loop breaks on both `VALIDATED` and `REVIEW_REQUIRED`, then falls through to render and archive with `status = DELIVERED`, so a synthesis flagged with `safety_finding_not_represented`, `contradicts_contraindication`, `contradicts_allergy`, `dose_not_in_structured_source`, or `citation_not_in_retrieved_set` ships to the clinician UI marked as a successful delivery. For a recipe whose architecture is explicitly built to prevent missed contraindications and missed interactions, this is exactly the safety-rail miswire the architecture is designed to prevent. Recipe 2.8 demonstrated the diagram-and-prose fix template; the multi-modal Recipe 2.10 expert review surfaced the same finding and recommended applying that template to its capstone. This recipe needs the same three-part fix: bounded retry edge in the diagram, a distinct terminal state routing to a human-review queue that does NOT flow into rendering, and an explicit orchestration gate in the pseudocode walkthrough. This finding should be coordinated with code-review Finding 1 so the main recipe and the Python companion agree.

Several MEDIUM findings cluster on pseudocode precision and recurring chapter-wide patterns: PHI minimization on the patient context and source content serialized into the synthesis prompt (same class as Recipe 2.7 S1 and Recipe 2.8 S1 and Recipe 2.10 S1); input-side Guardrails prompt-attack filters not bound to the InvokeModel call (same class as Recipe 2.7 S2, Recipe 2.8 S2, Recipe 2.10 S2); synthesis-run idempotency on EventBridge at-least-once delivery is not modeled (same recurring Chapter 2 trigger-idempotency pattern flagged in 2.4 through 2.10); Bedrock model IDs in pseudocode use literal string values (`anthropic.claude-haiku-4`, `anthropic.claude-sonnet-4`, `amazon.titan-embed-text-v2`) rather than the placeholder-with-comment pattern that Recipe 2.10 successfully demonstrated; contextual-grounding threshold not named in the Guardrails configuration block.

LOW findings are editorial polish: VPC interface-endpoint list missing `execute-api` for private API Gateway, missing CloudWatch monitoring (PutMetricData) endpoint, and missing `rds-data` for the Aurora Data API path that the IAM row explicitly references; cost-estimate ceiling potentially understates worst-case complex-scenario costs by 25-50%; five HTML-comment TODO markers for forward chapter cross-references and FDA-guidance-status verification.

Priority breakdown: 0 CRITICAL, 1 HIGH, 5 MEDIUM, 5 LOW.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

- BAA is explicit in Prerequisites and correctly frames the synthesis output itself as PHI: "The synthesized recommendation contains PHI (it references the patient's conditions, medications, labs)." This is the right framing because a CDS output that names "this patient's eGFR is 28" plus "this patient's apixaban therapy" is, taken together, identified PHI even when the demographic identifiers are stripped.
- Encryption parity across all PHI stores: S3 SSE-KMS with separate CMKs for corpus vs PHI archive (the right key separation given the corpus is less sensitive than the per-synthesis archive); DynamoDB encryption at rest with CMK; OpenSearch encryption at rest and in transit with fine-grained access control and no public endpoint; Aurora encryption at rest, SSL/TLS in transit; HealthLake encryption at rest with CMK; Bedrock and Comprehend Medical TLS in transit and encryption at rest.
- Bedrock model-invocation-logging PHI exposure called out explicitly in the Encryption row: "Bedrock model-invocation logging (if enabled) contains PHI in the prompt (patient context); log destination must be encrypted to the same standard as the archive." This addresses the recurring Chapter 2 finding from 2.2 through 2.10.
- IAM row says "Scope every action to specific resource ARNs." The action list is appropriate and granular (`bedrock:InvokeModel`, `bedrock:ApplyGuardrail`, `rds-data:ExecuteStatement`, `healthlake:ReadResource`, `healthlake:SearchWithGet`, `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM`, `comprehendmedical:InferSNOMEDCT`, etc.).
- CloudTrail data events for Bedrock, S3, DynamoDB, HealthLake, and Secrets Manager are required, and correlation to clinician identity and patient identifier via Cognito session claims is named explicitly. This is the audit-trail discipline a regulator or institutional safety review needs.
- Synthetic data posture for development is correct: Synthea for FHIR-shaped synthetic patients, USPSTF/CDC/HHS for guidelines, DDInter and DrugBank research for open drug data. "Never use real PHI in dev environments" is explicit. Evaluation data is correctly framed as requiring clinician-domain-expert curation.
- Sample output is explicitly labeled illustrative via HTML comment block: "the specific sources, recommendations, dose values, and guideline quotes below are illustrative. Do not treat them as production-ready clinical guidance." The illustrative-output discipline the chapter has settled into is preserved.
- Source licensing posture is substantive: commercial drug databases (Lexicomp, First Databank) and commercial guideline content with redistribution and API-use terms; open alternatives (DDInter, DrugBank, FDA SPLs); the recommendation to maintain a license registry per source and audit quarterly is the right operational posture and shows up again in "Why This Isn't Production-Ready."

#### Finding S1: PHI Minimization on Patient Context Serialized Into the Synthesis Prompt

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Step 8 `generate_synthesis`, the synthesis prompt's `PATIENT CONTEXT: {structured_context}` substitution; upstream Step 2 `normalize_patient_context` returns `structured_context` containing demographics, active conditions, current medications, allergies, recent labs, and derived values.
- **Problem:** Step 8 serializes the full `structured_context` from Step 2 into the synthesis prompt. The `demographics` field is built from the FHIR Patient resource and (per the FHIR Patient model) typically includes name, MRN, DOB, address, phone, and contact-related identifiers; the `current_medications` field includes prescribed-on dates and prescriber NPI references via the FHIR MedicationRequest; the active conditions may carry encounter-linked identifiers. The synthesis layer does not need MRN, DOB, name, address, phone, prescriber NPIs, or insurance identifiers to reason about empiric antibiotic selection or chronic-disease management; it needs age band, sex when clinically relevant, active problems, current medications (drug/dose/frequency), allergies, derived values (eGFR, BMI), recent lab values, and derived clinical state. Bedrock under BAA is HIPAA-compliant infrastructure, but minimum-necessary applies inside the BAA boundary as well, and unnecessary identifiers traveling through the prompt expand the model-invocation-logging PHI surface that the Encryption row already calls out as a sensitive store. Same class as Recipe 2.7 S1, Recipe 2.8 S1, and Recipe 2.10 S1; the recurrence across four recipes is now a chapter-wide pattern.
- **Fix:** Add a one-paragraph minimization step between Step 2 (normalize) and Step 8 (synthesis). Roughly:
  ```
  // Before serializing structured_context into the synthesis prompt, strip
  // identifiers that are not needed for reasoning.
  //
  // Keep: age band, sex when clinically relevant, active problems with
  //       SNOMED/ICD-10 codes, current medications (drug/dose/frequency/
  //       route), allergies, derived values (eGFR, BMI, Child-Pugh, QTc),
  //       recent lab values with LOINC codes.
  // Drop: MRN, DOB (age band is sufficient), name, address, phone, email,
  //       payer/member IDs, prescriber NPIs, encounter-linked identifiers,
  //       insurance identifiers.
  //
  // The rendered output re-associates the synthesis to the patient via the
  // synthesis_id/patient_id pointer; identifiers do not need to round-trip
  // through the synthesis prompt.
  structured_context_minimal = minimize_phi_for_synthesis(structured_context)
  ```
  Add a "PHI minimization in prompts" bullet to "Why This Isn't Production-Ready." Given this is the fourth Chapter 2 recipe with the same finding, propose a chapter-wide appendix or preface section on minimum-necessary-inside-the-BAA that each subsequent recipe can reference rather than repeat.

#### Finding S2: Input-Side Guardrails Prompt-Attack Filters Not Bound to the InvokeModel Call

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Step 8 `generate_synthesis`, the Bedrock InvokeModel call and its Guardrails comment block.
- **Problem:** The synthesis prompt concatenates the deterministic safety-findings block, retrieved guideline chunks (from OpenSearch), retrieved protocol chunks (institutional protocols authored by many hands over multiple years), retrieved drug-database records (serialized structured records from Aurora), and the patient context. Any of these can carry adversarial content: an institutional protocol that imported a PDF appendix where OCR'd footer text contains instruction-shaped phrasing, a guideline chunk re-ingested from an open source where the footer was treated as content, a vendor-supplied drug-database record with a free-text comment field, a clinician-authored note that the corpus pipeline was not strict about scrubbing. The pseudocode comment block names "Custom denied-topics list including prescriptive directive language outside of verbatim quoted guidelines" and "Content filters enabled" but does not call out input-side prompt-attack filters on the Guardrail policy. Guardrails' prompt-attack filter is configured on the policy itself, not on the invocation, so a reader copying the pseudocode and creating a default Guardrail will not get the protection the prose implies. Same class as Recipe 2.7 S2, Recipe 2.8 S2, and Recipe 2.10 S2.
- **Fix:** Add one explicit sentence to the Guardrails comment block:
  ```
  // Prerequisite: the Guardrail referenced by CDS_GUARDRAIL_ID must be
  // configured with input-side prompt-attack filters enabled (configured
  // on the Guardrail policy itself, not on the invocation), in addition
  // to the contextual grounding output check. Retrieved guideline chunks,
  // institutional protocols, drug-database records, and patient note
  // content are untrusted input surfaces, not verified instructions.
  ```
  Optionally add one line in "The Failure Modes You Have to Design Around" naming retrieved-text injection as an additional failure mode the architecture mitigates. Given this is the fourth Chapter 2 recipe with this finding, lifting it to a chapter appendix or preface checklist would be more efficient than repeating the per-recipe edit.

#### Finding S3: Contextual Grounding Threshold Not Specified

- **Severity:** LOW
- **Expert:** Security / Architecture
- **Location:** Step 8 Guardrails comment block; "Amazon Bedrock Guardrails for grounding and safety enforcement" paragraph in Why These Services.
- **Problem:** The prose says Guardrails' contextual grounding check is "non-negotiable" for CDS, and the Step 8 comment block describes the grounding source as "sources_block + safety_block, tagged with the Guardrails API so grounding check runs against the authoritative content only (not the prompt instructions)." The specific threshold is not named. A reader configuring Guardrails will default to whatever the console picks (historically 0.5 or 0.7), which is too permissive for a CDS surface where fabrication tolerance should be near-zero. Recipe 2.9's Python companion (per the code review) implicitly aligns with a higher threshold, but the main recipe's prose elides it.
- **Fix:** Add one sentence to the Guardrails Why These Services paragraph or the Step 8 comment block: "For a CDS surface, a grounding threshold at or above 0.85 is the conservative starting point; tune upward for scenarios where fabrication tolerance is lowest (oncology dosing, anticoagulation management, critical-care empiric antibiotic selection) and re-evaluate per scenario during clinical validation." Or add a "Guardrail policy configuration" row to the Prerequisites table.

---

### Architecture Expert Review

#### What's Done Well

- The 11-stage orchestration (trigger → fetch → normalize → scope determination → deterministic safety checks → scenario classification → multi-source retrieval → rank/filter → grounded synthesis → post-generation validation → tier/render/archive) is correctly factored. Each stage maps to a Lambda and Step Functions encodes the parallelism (deterministic safety checks across drug interactions, allergy, renal/hepatic dose) and the branching (scope determination short-circuit, validation retry).
- The deterministic-safety-check layer (Step 4) is the architecturally correct posture. Drug-drug interactions, allergy conflicts, renal/hepatic dosing flags, contraindications, and duplicate-therapy checks are structured database operations against Aurora, not LLM-derived findings. Their outputs become hard-coded inputs to the synthesis prompt, and the validator in Step 9 enforces that every deterministic finding appears in the synthesis output. This is exactly the architecture the recipe's prose argues for: "treat the drug database as infrastructure that needs its own quality assurance."
- The hybrid-retrieval pattern (OpenSearch for guidelines and protocols with vectors plus BM25 plus metadata filters; Aurora pgvector for structured drug-database records with vector-embedded prose) is the right factoring. Drug interaction tables, dose tables, contraindication lists are tabular and should be queried with SQL; guidelines and protocols are prose and benefit from hybrid vector + keyword + metadata-filter retrieval. The Architecture Pattern paragraph "structured retrieval against tabular sources with vector/keyword search against prose sources is the right architecture" is the correct teaching.
- Source authority ranking is explicit and clinically correct: institutional protocol outranks society guideline for institution-specific decisions; guideline outranks package insert for clinical questions; drug database trumps everything for interaction specifics. The patient-specificity-and-recency layered scoring is the right pattern.
- The structured JSON synthesis output (overall_assessment, ranked recommendations with citations and reasoning, safety_findings_included, competing_recommendations, what_to_ask_or_check, insufficient_evidence_items, overall_uncertainty) is the right shape for downstream validation, alert-fatigue tiering, and rendering. The "competing_recommendations" field is the architectural representation of the prose's "contradictions are first-class" claim.
- The alert-fatigue mitigation is genuinely architectural, not aspirational: scope determination as the first content-producing step, suppression based on prior synthesis history with the same patient/encounter, recommendation tiering (critical/important/informational) tied to delivery decisions, rejection with reason tracked per patient. The "if all recommendations are in suppressed tiers, flag as minor-update-only" decision is the correct reduction.
- Cost estimate is defensible ($0.15-$1.20 per synthesis, $75-$600/day variable at 500 syntheses, $500-$3,500/month fixed for OpenSearch/Aurora/HealthLake) and the per-stage breakdown is accurate. The recognition that the synthesis-with-stronger-model stage dominates ($0.08-$0.80) is honest.
- The implementation-time tiers (10-14 weeks POC, 36-52 weeks production-ready, 60-90 weeks with variations) are appropriate for the scope and resist the optimism-bias most CDS estimates fall into.
- The "Why This Isn't Production-Ready" section is the most substantive in the chapter on the operations and governance side: regulatory determination and documentation, source licensing, clinical validation per scope, post-market surveillance, prompt and model versioning, guideline freshness, drug-database integrity, FHIR-integration quirks, alert fatigue continuous calibration, bias surfacing, cost control at scale, fallback and degradation modes, EHR-level authorization integration, workflow integration, specialty adaptation, audit logs and retention, liability insurance. Sixteen substantive bullets with no filler.

#### Finding A1: Architecture Diagram's Validation-Retry Branch Has No Retry Cap and No Exit to Human Review

- **Severity:** HIGH
- **Expert:** Architecture / Clinical Safety
- **Location:** Architecture Diagram (Mermaid flowchart, Synthesis subgraph): `S15 --> S16[Lambda<br/>Post-Generation Validation]`; `S16 --> S17{Pass?}`; `S17 -->|No| S15`; `S17 -->|Yes| S18[Lambda<br/>Tiering + Suppression]`. Also Step 9 pseudocode `RETURN { status: "VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW" }` versus the implied Step 10 (tier/suppress/render) as the next step in the walkthrough. Also the General Architecture Pattern prose: "Validation failures trigger retry with stricter prompting, or route to human review."
- **Problem:** The diagram shows `S17 -->|No| S15` as an unbounded loop with no retry counter, no exit edge to a human-review queue, and no distinct terminal state for "validation exhausted." The Step 9 pseudocode correctly enforces a retry cap (`IF retry_count < 2: ... RETURN { status: "RETRY_NEEDED" } ... RETURN { status: "VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW" }`), but the orchestration walkthrough does not model what happens when validation returns the exhausted state: the walkthrough proceeds linearly from Step 9 to Step 10 (tier/suppress/render), which calls `archive_and_log` and updates DynamoDB to `status = "DELIVERED"` and returns the rendered payload to the clinician UI regardless of validation status. The prose sentence "Validation failures trigger retry with stricter prompting, or route to human review" names the right behavior, but neither the diagram nor the orchestration models the distinct `VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW` terminal state or the non-delivery path. The corresponding code review (Finding 1) confirms the Python companion implements the flow exactly as the main recipe depicts: the orchestrator's retry loop breaks on both `VALIDATED` and `REVIEW_REQUIRED`, then falls through to render and archive with `status = "DELIVERED"`.

  This is the same diagram and orchestration flaw flagged in Recipe 2.6 expert review and Recipe 2.7 expert review. Recipe 2.8 resolved its diagram. Recipe 2.10 expert review surfaced the same finding as A1 with the same priority. The fix template exists.

  For a CDS recipe specifically, the stakes are clinical-safety-critical. The Step 9 validation failure modes the architecture is built to catch include: `safety_finding_not_represented` (a deterministic interaction or contraindication finding that the model dropped), `dose_not_in_structured_source` (a fabricated dose), `contradicts_contraindication` (a recommended drug for which the safety-check found a contraindication), `contradicts_allergy` (a recommended drug that conflicts with a documented allergy), `directive_language_in_model_voice` (a regulatory-posture violation that erodes the FDA CDS exemption), `out_of_scope` (a recommendation outside the intended CDS surface). The recipe's "Failure Modes You Have to Design Around" subsection specifically names "missed interaction," "missed contraindication," and "fabricated dose or dosing frequency" as the outcomes the architecture is built to prevent. The orchestrator is the last gate between a flagged synthesis and the clinician UI, and the diagram (and the implied pseudocode sequencing) depicts that gate as absent. A clinician-facing CDS surface delivering a synthesis where the validator caught a contraindication-conflict is precisely the safety-rail bypass the architecture exists to prevent.
- **Fix:** Make three changes in lockstep:
  1. **Architecture diagram:** Replace the infinite-loop edge with a bounded retry and a distinct terminal state. Use Recipe 2.8's pattern as the template:
     ```
     S15 --> S16[Lambda<br/>Post-Generation Validation]
     S16 --> S17{Pass?}
     S17 -->|Yes| S18[Lambda<br/>Tiering + Suppression]
     S17 -->|No, retries left| S15
     S17 -->|No, retries exhausted| HRQ[Human Review Queue]
     HRQ --> HRS[S3 + DynamoDB<br/>Review Queue Archive]
     ```
     The key visual cue: the "retries exhausted" edge does NOT flow into S18, S19, S20, or S22.
  2. **General Architecture Pattern prose:** Expand the "Post-generation validation" bullet to explicitly name the terminal state: "Failures retry with augmented prompting up to N times; retry-exhausted failures route to a distinct human-review queue (separate DynamoDB table and S3 archive) and do NOT proceed to tier/suppress/render or flow to the clinician UI."
  3. **Pseudocode walkthrough:** Add a short Step 9.5 (or expand Step 10's preamble) showing the orchestrator branch:
     ```
     // The orchestrator MUST distinguish VALIDATED from
     // VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW. Only VALIDATED proceeds
     // to Step 10 (tier/suppress/render) with status = DELIVERED.
     // VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW is a terminal state:
     // write the trace to S3 (KMS-encrypted), update DynamoDB with
     // status = "ROUTED_TO_REVIEW", enqueue to a clinical reviewer
     // queue (SQS or DynamoDB stream), and do NOT call
     // tier_suppress_render or archive_and_log with delivered=true.
     IF validation_result.status == "VALIDATED":
         proceed to Step 10 (tier/suppress/render)
     ELSE IF validation_result.status == "VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW":
         write trace to S3 (KMS-encrypted, distinct prefix from delivered)
         update DynamoDB synthesis record with status = "ROUTED_TO_REVIEW"
         enqueue to clinical reviewer queue
         RETURN early; do NOT call tier_suppress_render or proceed
                       to archive_and_log with status = "DELIVERED"
     ```
     Coordinate with the Python companion fix from code-review Finding 1 so the two files agree.

#### Finding A2: Synthesis-Run Idempotency on EventBridge At-Least-Once Delivery Is Not Modeled

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 1 `trigger_synthesis(trigger)`: `synthesis_id = generate UUID`; the DynamoDB `cds-syntheses` write that follows.
- **Problem:** EventBridge is at-least-once delivery. If the same clinical trigger fires twice (a `medication_order` event that EventBridge re-delivers because the first delivery's downstream Lambda timed out at the API Gateway boundary, or an `admission` event whose source emitter retried), the current pseudocode generates a fresh UUID per invocation and starts two full synthesis pipelines for the same logical trigger. Each runs through scope determination, retrieval, generation, validation, render, and archive; each writes a DynamoDB record; each delivers to the clinician UI. The clinician sees two recommendation panels for the same trigger. At $0.15-$1.20 per synthesis, doubled invocations on duplicate deliveries are a direct cost hit. The scope-gate suppression check (`for recent in recent_synthesis_history: IF recent.trigger_signature == trigger.signature AND recent.age_minutes < SUPPRESSION_WINDOW_MINUTES: RETURN`) provides the right pattern at the application layer, but it depends on the first run completing and writing its record before the second starts. If the two deliveries fire close together (which is the realistic at-least-once delivery pattern), both will see an empty suppression history and both will run.

  This is the same trigger-idempotency finding flagged in Recipe 2.4, Recipe 2.5, Recipe 2.6, Recipe 2.7, Recipe 2.8, and Recipe 2.10 expert reviews. Six recipes with the same finding class is now firmly past "recurring observation" threshold. The specific surface differs (per-patient EventBridge rule for trigger types, ambient-documentation session, clinician-request-via-API), but the underlying discipline is shared: deterministic event-key hashing, conditional DynamoDB writes, and Step Functions execution-name derived from the event key.
- **Fix:** Derive `synthesis_id` from a deterministic event-key hash and use a DynamoDB conditional write to enforce idempotency at the orchestration layer:
  ```
  FUNCTION trigger_synthesis(trigger):
      event_key = build_event_key(trigger)
      // For admission: f"{patient_id}:{encounter_id}:admission_synthesis"
      // For medication order: f"{patient_id}:{order_id}:med_order_review"
      // For lab result: f"{patient_id}:{lab_observation_id}:lab_triggered_synthesis"
      // For clinician request: include a request timestamp or request UUID provided by the UI
      synthesis_id = deterministic_hash(event_key)

      try:
          put_item to DynamoDB "cds-syntheses":
              synthesis_id    = synthesis_id
              ... other fields ...
              condition_expression = "attribute_not_exists(synthesis_id)"
      except ConditionalCheckFailedException:
          // Duplicate delivery; the original synthesis is in flight or complete.
          RETURN { status: "DUPLICATE_SUPPRESSED", synthesis_id: synthesis_id }

      start Step Functions execution:
          name = synthesis_id   // deterministic; second invocation fails with
                                // ExecutionAlreadyExists
  ```
  Add a "Trigger idempotency" bullet to "Why This Isn't Production-Ready." Strongly recommend a chapter-wide trigger-idempotency appendix to consolidate this recurring finding rather than repeating the per-recipe edit.

#### Finding A3: Bedrock Model IDs in Pseudocode Use Literal Strings Rather Than Placeholder Constants

- **Severity:** MEDIUM
- **Expert:** Architecture / Publication Readiness
- **Location:**
  - Step 5 (`classify_and_plan`): `model_id = "anthropic.claude-haiku-4"` (line 692)
  - Step 6 (`multi_source_retrieval`): `model_id = "amazon.titan-embed-text-v2"` (line 738)
  - Step 8 (`generate_synthesis`): `model_id = "anthropic.claude-sonnet-4"` (line 940)
- **Problem:** All three Bedrock calls in the pseudocode use literal string model IDs that are not valid Bedrock model identifiers. The real Bedrock model-ID format requires a date and version suffix (e.g., `anthropic.claude-sonnet-4-20250514-v1:0`, `anthropic.claude-haiku-4-5-20251001-v1:0`, `amazon.titan-embed-text-v2:0`). The bare forms in the pseudocode are invalid as written: a reader copying these strings into a Python script will get `ResourceNotFoundException` or `ValidationException`. Recipe 2.10's expert review explicitly commended its pseudocode for using placeholder constants (`REASONING_MODEL_ID`, `SMALL_MODEL_ID`, `EMBEDDING_MODEL_ID`) with family-name comments ("// e.g., Claude Sonnet"), framing the pattern as the chapter template that subsequent recipes should follow. Recipe 2.9 predates the Recipe 2.10 review chronologically but was clearly drafted under a less-disciplined model-ID convention; the Python companion (per the code review) does pin a specific working ID, so the pattern of "placeholder in pseudocode plus versioned ID in Python" is the correct teaching split that Recipe 2.10 demonstrates.

  The risk is twofold. First, a learner copying the pseudocode into a real implementation gets non-working API calls. Second, the literal IDs date the recipe in a way that placeholder constants do not: if the reader sees "claude-sonnet-4" in pseudocode, they may assume that exact ID is current; once Bedrock deprecates that family or releases a successor, the recipe reads as out-of-date even where the architectural reasoning is timeless. Same publication-readiness consideration the Recipe 2.10 review flagged for the entire chapter.
- **Fix:** Replace the three literal IDs with placeholder constants and family-name comments:
  ```
  // Step 5
  model_id = SMALL_MODEL_ID         // e.g., Claude Haiku, Nova Lite

  // Step 6
  model_id = EMBEDDING_MODEL_ID     // e.g., Titan Text Embeddings v2

  // Step 8
  model_id = SYNTHESIS_MODEL_ID     // e.g., Claude Sonnet
  ```
  Optionally add one sentence near the first Bedrock invocation noting that Bedrock model IDs are versioned and the Python companion pins specific working IDs ("see the Python companion for the exact model IDs used in this recipe's testing"). This brings Recipe 2.9 into alignment with the Recipe 2.10 chapter template and removes the dated-string risk.

#### Finding A4: Cost Estimate Ceiling May Understate Worst-Case Comprehensive-Scenario Costs

- **Severity:** LOW
- **Expert:** Architecture / Cost
- **Location:** Prerequisites table, Cost Estimate row: "End-to-end: $0.15-$1.20 per synthesized recommendation set" and the per-stage breakdown ("synthesis with stronger model $0.08-$0.80").
- **Problem:** The upper bound of $1.20 per synthesis is reasonable for focused scenarios with modest retrieval breadth and a single generation pass. For complex multi-scenario syntheses (the recipe explicitly mentions "complex multi-scenario syntheses" in the Performance Benchmarks table) on a patient with dense longitudinal context, broad retrieval (47 guideline chunks + 12 protocol chunks + 14 drug-DB records is the example from the sample output), and validator retry on first attempt, end-to-end cost can push past $2 in the worst case. The reasoning-layer-with-Sonnet at large context size and a retry adds non-trivial input-token cost. The recipe's own "Cost control at scale" bullet in "Why This Isn't Production-Ready" hints at this ("multiply by triggered syntheses... the cost can run several hundred dollars a day per facility"), but the per-synthesis ceiling does not align.
- **Fix:** Either (a) widen the top-line range to $0.15-$2.00 with a note that the top of the range applies to complex multi-scenario syntheses with broad retrieval and validator retry, or (b) keep the existing range and add one line below the table: "For complex multi-scenario syntheses with large retrieval contexts and validator retry, per-synthesis cost can approach $2; for budgeting at scale, assume an average of $0.50 per synthesis with a long tail to $2."

---

### Networking Expert Review

#### What's Done Well

- The VPC row is comprehensive on the core HIPAA-eligible services. Interface endpoints for Bedrock (Runtime, Agent Runtime if using Knowledge Bases), Bedrock Guardrails, Comprehend Medical, HealthLake, KMS, Secrets Manager, Step Functions, CloudWatch Logs, and EventBridge cover the synthesis pipeline's inline calls. Gateway endpoints for S3 and DynamoDB are correctly included (free in most accounts, no per-AZ-per-endpoint cost). Aurora and OpenSearch in VPC with security groups restricted to the Lambda execution role is the right posture for the structured-and-prose retrieval stores. The per-AZ-per-endpoint cost reminder ("Interface endpoints run roughly $7-10/month per AZ per endpoint; reflect this in the cost estimate") is the Chapter 2 hygiene carry-forward.
- Aurora and OpenSearch network posture (in-VPC, security-group-restricted to Lambda execution role, encryption in transit) is named correctly. No public endpoint for OpenSearch, fine-grained access control, encryption at rest with CMK is the right HIPAA-aligned posture.
- TLS in transit is specified across every PHI-carrying data flow. CloudTrail data events for Bedrock, S3, DynamoDB, HealthLake, and Secrets Manager provide cross-service correlation for the audit trail.
- API Gateway with Cognito is correctly framed as the clinician-facing entry point. SMART on FHIR for EHR-launched flows and CDS Hooks for workflow triggers are named with their appropriate use cases (CDS Hooks for "EHR-triggered CDS calls," SMART on FHIR for "EHR-launched apps").

#### Finding N1: `execute-api` Interface Endpoint Not Called Out for Private API Gateway

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row; "Amazon API Gateway and Amazon Cognito for the clinician-facing API" paragraph in Why These Services.
- **Problem:** The recipe does not specify whether API Gateway is public (with WAF and Cognito) or private (reachable from the corporate network via VPN/Direct Connect with `execute-api` interface endpoint). For a clinician-facing CDS endpoint inside a healthcare institution, the production posture is often private; the corporate network is the trust boundary, and the public-internet attack surface is narrowed accordingly. A private REST API requires the `com.amazonaws.{region}.execute-api` interface endpoint, which the VPC row does not list. Same pattern as Recipe 2.7 N2, Recipe 2.8 N2, and Recipe 2.10 N1.
- **Fix:** Add a conditional line to the VPC row: "If API Gateway is configured as a private REST API (recommended for EHR-internal clinician-facing endpoints), add `execute-api` interface endpoint." Optionally name the API Gateway posture (public with WAF + Cognito, or private) in the "Amazon API Gateway and Amazon Cognito" paragraph so the reader knows which pattern the recipe assumes.

#### Finding N2: CloudWatch Monitoring (PutMetricData) Endpoint Not Distinguished from CloudWatch Logs

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row.
- **Problem:** The VPC row lists "CloudWatch Logs" but the pipeline also emits custom metrics via `PutMetricData` (Step 11's CloudWatch emissions: `SynthesisDelivered` namespace `ClinicalDecisionSupport`, `SafetyFindingsSurfaced`). CloudWatch Logs uses `com.amazonaws.{region}.logs`; CloudWatch monitoring (PutMetricData) uses `com.amazonaws.{region}.monitoring`. They are distinct interface endpoints. A Lambda in a private subnet without the `monitoring` endpoint will succeed at writing logs but silently fail to publish custom metrics, which produces a metrics-coverage gap in dashboards and alarms; the failure is silent because `PutMetricData` errors are typically swallowed by the CloudWatch SDK helper. Same observation as Recipe 2.7, Recipe 2.8, and Recipe 2.10 reviews.
- **Fix:** Add `CloudWatch (monitoring)` to the interface-endpoint list in the VPC row, or rename the entry to `CloudWatch Logs and CloudWatch (monitoring)` to cover both.

#### Finding N3: `rds-data` Interface Endpoint Not Listed for Aurora Data API Path

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row; IAM Permissions row references `rds-data:ExecuteStatement` for Aurora Data API.
- **Problem:** The IAM Permissions row explicitly lists `rds-data:ExecuteStatement` as an option ("for Aurora Data API (or database credentials via Secrets Manager)"). The Aurora Data API path requires the `com.amazonaws.{region}.rds-data` interface endpoint for a Lambda in a private subnet to reach the Data API without going through a NAT gateway. The VPC row does not list it. A reader who selects the Data API path (which is the simpler integration for Lambda + Aurora and avoids managing connection pooling) will hit a connection failure in production unless they discover the endpoint requirement separately. If the alternative pattern (database credentials via Secrets Manager + direct PostgreSQL connection) is selected, the `rds-data` endpoint is not needed but the existing security-group-restricted-to-Lambda configuration covers it.
- **Fix:** Add a conditional line to the VPC row: "If Aurora Data API path is used (`rds-data:ExecuteStatement`), add `rds-data` interface endpoint. If direct PostgreSQL connection via Secrets Manager is used, the in-VPC security-group-restricted Aurora cluster does not require an additional endpoint." This makes the two integration paths' networking requirements explicit.

---

### Voice Reviewer

#### What's Done Well

- The five-vignette opening is the chapter's most authentic clinician-language opening. Each vignette is clinically dense, specific, and resists the temptation to oversimplify. The 2 AM ICU sepsis case (74-year-old with CKD, atrial fibrillation on apixaban, HFrEF, sulfa allergy with rash, prior C. diff colitis) is the kind of patient an experienced hospitalist sees often and reasons about under time pressure exactly the way the vignette describes; the hospitalist "has roughly four minutes to decide on an empiric antibiotic regimen before the next rapid response pages her" lands because it is true. The chronic primary-care diabetes intensification case ("She'll make a good decision, probably. It will take her about six of those eleven minutes to do it well, leaving five for everything else the visit needed to cover") is the most clinically honest framing of the time-budget problem in the chapter. The oncology QT-prolongation vignette ("the oncologist needs to decide: proceed with osimertinib and tighter cardiac monitoring, switch the ondansetron to a different antiemetic, attempt escitalopram substitution, or some combination") names a real specialty intersection (cardio-oncology) without over-claiming that AI will solve it. The vancomycin nephrotoxicity vignette ("the alert was correct. The alert was also one of 180 alerts that the hospitalist saw that shift, and the cognitive load of discriminating signal from noise is the actual problem") is the chapter's clearest single-paragraph framing of why alert fatigue is the design constraint.
- "What clinicians have been asking for, for about as long as there have been EHRs, is a decision support system that reasons about the whole patient, prioritizes what's actually clinically important right now, synthesizes across guidelines that have different emphases, surfaces the reasoning so the clinician can audit it, and lets the clinician disagree with an intact line of argument. Not more alerts. Smarter, fewer, better-explained, patient-specific recommendations." This is the kind of plain-English authority statement the chapter's voice is built on; no hedging.
- The Technology section's evolution-of-CDS paragraph (rule-based → statistical/ML-for-narrow-prediction → grounded LLM synthesis) is the right historical framing and resists the "everything is now solved" trap.
- "How CDS Synthesis Differs From Literature Search" is the strongest single subsection in the recipe. The five divergences (source types, patient context as primary retrieval driver, contradictions as first-class, regulatory posture, alert fatigue as design force) are each architecturally accurate and each tied to a specific design decision later in the recipe. The framing of CDS as patient-specific-and-prescriptive vs literature search as descriptive is the kind of teaching distinction a working architect would make.
- The "FDA CDS Rule" subsection is clinically and regulatorily accurate. The four-part exemption test is quoted verbatim, the "independently review the basis" criterion is correctly identified as the one doing the most work, and the translation to architecture (sources prominent, framing as suggestions, UI invites judgment, documentation comprehensive) is exactly right. The "Get your regulatory affairs team involved from day one. Do not build the thing and then ask whether it's a medical device" sentence is publication-ready voice.
- "Alert Fatigue As a Design Principle" is the chapter's most substantive treatment of an operational constraint that most CDS recipes elide. The five design moves (trigger on clinical scenarios not every order; suppress when addressed; tier by clinical importance; respect rejection; measure engagement not delivery) are concrete and each has a corresponding architectural mechanism in the pseudocode.
- The failure-modes-you-have-to-design-around enumeration is clinically dense and architecturally tied. Each item names a real failure mode (fabricated recommendation, fabricated dose, missed interaction, missed contraindication, population mismatch, wrong side of equipoise, stale guidance, over-confident recommendation on limited evidence, recommendation bypasses clinician judgment, recommendation out of scope, formulary mismatch, regulatory drift) and pairs it with a specific mitigation. "Regulatory drift" as the last item is voice at its best: the recognition that prompt iteration over time can erode the exemption posture if not governed.
- The "Why This Isn't Production-Ready" section is the chapter's most substantive on operations and governance. Sixteen substantive bullets with no filler.
- "The Honest Take" is publication-ready. The six failure-pattern enumeration (chasing breadth over depth, under-investing in retrieval, building safety as LLM prompts, not measuring the right things, deferring regulatory review, shipping without clinician buy-in) is the kind of hard-won wisdom that distinguishes the chapter's voice. The five things-that-have-worked enumeration (start with deterministic-check-driven scenarios, foreground reasoning over recommendations, treat every synthesis as an artifact, invest in clinician feedback loops, design for the 2 AM failure mode, don't pretend the system replaces judgment) is the kind of framing that earns the reader's trust. The closing "Build toward that. Everything else flows from it" lands the right final posture.
- No em dashes (direct U+2014 / U+2013 character check: zero matches across approximately 1450 lines). No marketing language. The 70/30 vendor balance is clean: AWS service names enter in the AWS Implementation section and stay there; the conceptual sections are vendor-neutral.
- Variations and Extensions is substantive: scenario-specific CDS modules, guideline change monitoring with population-health triggering, prior-auth-aware recommendations, CDS Hooks integration, order set optimization, second-opinion synthesis, multi-agent deliberation for ambiguous scenarios, patient-facing explanations, audio-delivered CDS for rounding, integration with population-health triggering. Ten substantive variations, each tied to a specific clinical workflow.
- Related Recipes cross-references are voice-appropriate and link backward (2.4, 2.5, 2.6, 2.7, 2.8, 2.10) and forward (Chapter 5, 7, 13) with concise descriptions of the connection.

#### Finding V1: Five HTML-Comment TODO Markers

- **Severity:** LOW
- **Expert:** Voice / Publication Readiness
- **Location:**
  - Line 124: `<!-- TODO (TechWriter): verify current status of FDA generative-AI CDS guidance as of writing; check for recent updates to the September 2022 CDS guidance. -->` (FDA generative-AI CDS guidance status)
  - Line 1436: `<!-- TODO (TechWriter): update to specific recipe number once Chapter 5 is drafted. -->` (Recipe 5.x Entity Resolution reference)
  - Line 1437: `<!-- TODO (TechWriter): update to specific recipe number once Chapter 13 is drafted. -->` (Recipe 13.x Knowledge Graphs reference)
  - Line 1438: `<!-- TODO (TechWriter): update to specific recipe number once Chapter 7 is drafted. -->` (Recipe 7.x Predictive Analytics reference)
  - Line 1501: `<!-- TODO (TechWriter): verify current status and URL of HealthBench. -->` (HealthBench benchmark link)
- **Problem:** HTML-comment TODOs survive Markdown-to-HTML rendering paths as view-source comments but do not render visibly to readers of the published output. This is a substantially better posture than the bracket-style visible TODOs flagged as HIGH in Recipe 2.5, 2.6, and 2.8 expert reviews; same class as Recipe 2.10 V1. The forward-placeholder pattern ("Recipe 5.x" / "Recipe 7.x" / "Recipe 13.x" with a one-line description) is voice-appropriate and reads cleanly to a published-output reader even if the TODOs are never resolved. The FDA-guidance-status TODO is the most pressing of the five because regulatory guidance does evolve and a stale claim that "FDA has not issued generative-AI-specific guidance as of this writing" risks becoming inaccurate during the book's shelf life.
- **Fix:** For the Chapter 5/7/13 cross-references, leave as-is with the understanding that the forward-placeholder text reads cleanly. For the FDA generative-AI CDS guidance TODO (line 124), verify and resolve before publication; the September 2022 guidance is the current version as of mid-2026 to the best of public reporting, but check for FDA AI/ML Software-as-a-Medical-Device updates and the FDA's "Artificial Intelligence/Machine Learning (AI/ML)-Based Software as a Medical Device (SaMD) Action Plan" follow-up documents. For HealthBench (line 1501), verify the URL is current; periodic verification before each book revision is the right discipline.

#### Finding V2: Sample Output's Cefepime Renal Dosing Citation Should Be Cross-Checked Against an Actual Source

- **Severity:** LOW
- **Expert:** Voice / Clinical Accuracy
- **Location:** Expected Results sample JSON, Option B's recommendation text: "Cefepime 1 g IV every 12 hours is consistent with [5] for eGFR 11-29."
- **Problem:** The HTML-comment block at the top of the Expected Results section explicitly disclaims the sample as illustrative ("Do not treat them as production-ready clinical guidance"), so this is a polish observation rather than a clinical defect. Cefepime renal dosing in the eGFR 11-29 range varies somewhat by source: the package insert and many institutional references support 1 g q12h or 0.5-1 g q24h depending on infection severity; the 1 g q12h dosing in the sample is in the range some references support but is not a single canonical dose. A clinical reader reproducing the sample as a fixture for a demo environment (or mistakenly treating it as guidance) might land on a dose that disagrees with their institutional reference. The illustrative disclaimer is correctly placed, so the impact is minor; the cleaner posture is to either verify the sample against an explicit named source (FDA SPL for cefepime, with the eGFR-binned dosing table) or add a one-line addition to the disclaimer noting that dose values in the sample are illustrative and may not match every institutional reference's tiered dosing.
- **Fix:** Either (a) verify the cefepime dose against the FDA Structured Product Label for cefepime and update the sample if the SPL's eGFR-binned dose differs, or (b) keep the sample as-is and add to the existing HTML-comment disclaimer: "Numeric dose values in the sample are illustrative; do not copy into production fixtures without recalculation against the cited source for the actual deployment's drug-database integration."

#### Finding V3: "Recipe 2.10" Forward Reference in Related Recipes Without Direct Link

- **Severity:** LOW
- **Expert:** Voice / Publication Readiness
- **Location:** Related Recipes section, Recipe 2.10 entry: "Recipe 2.10 (Multi-Modal Clinical Reasoning): Extends CDS into multi-modal inputs..."
- **Problem:** Recipe 2.10 exists as a sibling recipe in this chapter and was reviewed (chapter02.10-expert-review.md). The Related Recipes entry names it but does not include a link to the rendered file. By contrast, the navigation footer at the bottom of the recipe correctly links to it ("Next: Recipe 2.10 - Multi-Modal Clinical Reasoning"). Same chapter recipes should consistently use either link-with-anchor or link-with-filename. A reader scanning Related Recipes for navigation will see other Recipe 2.x entries listed without links and assume the entire section is non-clickable, which understates the chapter's connectedness.
- **Fix:** Either (a) add markdown links to the Recipe 2.x entries that already have rendered files (Recipe 2.4, 2.5, 2.6, 2.7, 2.8, 2.10), matching the navigation-footer pattern, or (b) leave as-is and let the navigation footer carry the linking burden. Option (a) is the cleaner editorial pass.

---

## Stage 2: Expert Discussion

**Overlap: Architecture (A1) and the code review's Finding 1 (auto-deliver `REVIEW_REQUIRED`).**
The architecture-diagram infinite-loop and the prose-orchestration silence on `VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW` are the same gap surfaced in the main recipe that, in the Python companion, becomes the specific orchestrator bug of auto-delivering `REVIEW_REQUIRED` with `status = DELIVERED`. The code review flagged the Python-side instance as a WARNING; the main recipe's architecture is the upstream cause. Fixing the main recipe's diagram and walkthrough (A1) without fixing the Python companion's orchestrator is a half-measure; fixing the Python companion's orchestrator without updating the diagram and prose leaves the main recipe misleading future readers. The editor should treat this as a linked pair and update both in the same pass. Recipe 2.8 demonstrated the diagram-and-prose fix template; Recipe 2.10's expert review surfaced the same finding in its capstone. This is now the recurring "validation-retry safety bypass" pattern that has appeared in five Chapter 2 recipes (2.6, 2.7, 2.8, 2.9, 2.10).

**Overlap: Security (S1) and Architecture (A2).**
S1 (PHI minimization in the synthesis prompt) and A2 (synthesis-run idempotency) do not conflict but are independent edits at adjacent stages of the pipeline. S1 is a one-paragraph minimization step between Step 2 and Step 8; A2 is a deterministic-event-key change at Step 1. They compose cleanly with no ordering constraint between them. Both are recurring chapter-wide patterns (S1 from 2.7/2.8/2.10; A2 from 2.4 through 2.10).

**Overlap: Security (S2) and the recurring retrieved-text injection pattern.**
S2 (input-side Guardrails prompt-attack filters) is the fourth Chapter 2 finding in the same class (2.7 S2, 2.8 S2, 2.10 S2). The per-recipe fix is a single sentence in the Step 8 Guardrails comment block; the chapter-wide aggregate recommendation, which has now passed "recurring observation" threshold by a wide margin, is that Chapter 2's preface or a chapter-wide Guardrails-configuration appendix should consolidate the policy-level configuration checklist (input-side prompt-attack filters enabled, contextual grounding threshold specified, PII filters tuned for clinical content, denied-topics list scoped per recipe) once rather than repeating it in each recipe's Step 8 comment block. Each recipe can reference the appendix for the policy-level configuration and only call out recipe-specific configuration in its own Guardrails block.

**Overlap: Architecture (A2) and the chapter-wide trigger-idempotency pattern.**
A2 is the sixth consecutive Chapter 2 expert-review finding in this class (2.4 through 2.10 reviews all raised the same pattern with different specifics). The per-recipe fix is small; the chapter-wide recommendation, which has now been raised across six consecutive reviews, is a shared appendix or preface section on trigger idempotency covering the conditional-write pattern, deterministic-name pre-check pattern, and execution-token suffix pattern. Each recipe's specifics differ (per-patient EventBridge rule, ambient-documentation session, HealthScribe job name, multi-modal reasoning event, CDS trigger), but the underlying discipline is shared.

**Overlap: Security (S1) and the chapter-wide PHI-minimization pattern.**
S1 is the fourth Chapter 2 expert-review finding in the same class (2.7 S1, 2.8 S1, 2.10 S1, 2.9 S1). Like the Guardrails-policy and trigger-idempotency patterns, this has stabilized into a "shared appendix candidate" rather than a per-recipe fix. The recurring observation suggests the cookbook's teaching on minimum-necessary-inside-the-BAA-boundary should be lifted once and referenced per recipe. The pattern is shared (Bedrock prompt construction step, full structured patient context serialized, Bedrock model-invocation logging contains PHI), and the fix template is the same (minimization helper that strips MRN/DOB/name/address/phone/NPIs/payer-IDs while keeping age band, sex when clinically relevant, problems, medications, allergies, derived values).

**Overlap: Architecture (A3) and the chapter-wide model-ID precision pattern.**
A3 (Bedrock model IDs as literal strings rather than placeholder constants) is the second Chapter 2 expert-review finding in this class. Recipe 2.10's review explicitly named placeholder-with-comment as the chapter template; Recipe 2.9 (drafted earlier, before that template was settled) uses literal IDs. Recipes 2.7 and 2.8 had similar issues with versioned-but-stale IDs. The chapter editor should be running a chapter-wide grep for `anthropic\.` and `amazon\.titan` string literals in pseudocode and applying the placeholder pattern uniformly. This is the smallest-diff fix on the list and brings Recipe 2.9 into alignment with the established chapter convention.

**Non-conflict: Architecture (A4).**
A4 (cost ceiling for complex syntheses) is independent of the safety-rail and minimization findings. A one-line addition to the Cost Estimate row.

**Non-conflict: Networking (N1, N2, N3).**
Each is a one-line addition to the VPC row. N1 (`execute-api`) and N2 (CloudWatch monitoring) are recurring findings from Recipes 2.7, 2.8, 2.10. N3 (`rds-data` for Aurora Data API) is unique to recipes that use Aurora as a structured store; this is the first Chapter 2 recipe with that path, and the conditional-endpoint guidance is the right addition.

**Non-conflict: Voice (V1, V2, V3).**
V1 is editorial polish (HTML-comment TODOs); V2 is illustrative-sample polish (cefepime dose against canonical SPL); V3 is link-consistency polish (Related Recipes hyperlinks).

**Pattern observation: the architecture is sound; the orchestration safety gap is the only HIGH finding.**
Like Recipe 2.10's review, this recipe is mature on every axis except the validation-exhausted terminal state. The teaching is among the strongest in the chapter alongside Recipe 2.7 (literature search) and Recipe 2.10 (multi-modal). The failure-mode taxonomy is dense and architecturally tied. The regulatory framing is the most substantive in the chapter on the FDA CDS exemption specifically. The "Honest Take" is publication-ready. The one HIGH finding (A1) is a recurring architectural safety issue with a known fix template (Recipe 2.8's diagram), not a teaching-quality issue.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

One HIGH finding, which is below the "more than 3 HIGH = FAIL" threshold. No CRITICAL findings. The architecture is sound, the teaching is among the strongest in the chapter, Chapter 2 hygiene patterns (IAM scoping to resource ARNs, VPC endpoint coverage on core services, Bedrock model-invocation-logging PHI, no em dashes, no bracket-style visible TODOs, source licensing posture, regulatory framing) are addressed, the failure-mode taxonomy is dense and architecturally tied, the FDA CDS exemption framing is the most substantive in the chapter, and the "Honest Take" is publication-ready.

The one HIGH finding (A1) is the recurring architecture-diagram validation-retry flaw that has now appeared in Recipes 2.6, 2.7, 2.9, and 2.10, with the fix template demonstrated in Recipe 2.8. For a CDS recipe whose architecture is explicitly built to prevent missed contraindications, missed interactions, and fabricated doses, the architecture-level gap that allows a synthesis flagged with `safety_finding_not_represented` or `contradicts_contraindication` to ship to the clinician UI as `DELIVERED` cannot remain. The fix has three parts (diagram, prose, pseudocode) and is localized; Recipe 2.8 provides the template, and the Python companion's code-review Finding 1 should be coordinated in the same editorial pass.

The five MEDIUM findings cluster on pseudocode precision and recurring chapter-wide patterns:
- **S1** PHI minimization on patient context serialized into the synthesis prompt.
- **S2** input-side Guardrails prompt-attack filters bound to the InvokeModel call.
- **A2** synthesis-run idempotency on EventBridge at-least-once delivery.
- **A3** Bedrock model IDs as placeholder constants rather than literal strings (alignment with Recipe 2.10's chapter template).

The four LOW findings (S3 grounding threshold, A4 cost ceiling, N1 `execute-api`, N2 CloudWatch monitoring, N3 `rds-data`) and three V findings (V1 HTML-comment TODOs, V2 sample dose verification, V3 Related Recipes link consistency) are editorial polish that cleans the recipe up but does not affect its architectural or teaching soundness.

With the A1 fix (diagram + prose + pseudocode coordinated with code-review Finding 1) and a clean-up pass on the MEDIUM findings, this recipe is publication-ready and sits at the same quality bar as Recipe 2.10 as a Chapter 2 capstone. The conceptual teaching, the failure-mode taxonomy, the regulatory framing, and the "Honest Take" are all publication-ready. The clinical density of the opening vignettes is the chapter's strongest single attribute on the voice axis.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| A1 | HIGH | Architecture / Clinical Safety | Architecture Diagram Synthesis subgraph (`S17 -->|No| S15`); General Architecture Pattern prose ("Validation failures trigger retry... or route to human review"); Step 9 → Step 10 transition in pseudocode walkthrough | Architecture diagram's validation-retry branch loops back to generation with no retry cap and no exit to human review; pseudocode Step 9's `VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW` terminal state is not modeled in the orchestration walkthrough; Python companion (per code review Finding 1) implements the gap as auto-delivery of `REVIEW_REQUIRED` with `status = DELIVERED`. Same pattern as Recipe 2.6, 2.7, 2.10 expert reviews; fix template in Recipe 2.8. Highest stakes for a CDS recipe because the validator catches `safety_finding_not_represented`, `contradicts_contraindication`, `contradicts_allergy`, `dose_not_in_structured_source`, `directive_language_in_model_voice`, and `out_of_scope` failures, all of which would ship to the clinician UI as a successful delivery without the fix. |
| S1 | MEDIUM | Security | Step 8 `generate_synthesis`, the synthesis prompt's `PATIENT CONTEXT: {structured_context}` substitution; upstream Step 2 `normalize_patient_context` | Patient context (including potential MRN, DOB, name, address, phone, NPIs from FHIR resources) and full retrieval set serialized into the synthesis prompt without minimum-necessary scoping; Bedrock under BAA is compliant, but minimum-necessary applies inside the BAA boundary, and unnecessary identifiers expand the model-invocation-logging PHI surface. Same class as Recipe 2.7 S1, Recipe 2.8 S1, Recipe 2.10 S1. Fourth Chapter 2 recipe with this finding; chapter appendix candidate. |
| S2 | MEDIUM | Security | Step 8 Guardrails comment block | Input-side prompt-attack filters referenced in prose but policy-level Guardrail configuration prerequisite not explicitly bound to the InvokeModel call; retrieved guideline chunks, institutional protocols, drug-database records, and patient note content are untrusted-input surfaces. Same class as Recipe 2.7 S2, Recipe 2.8 S2, Recipe 2.10 S2. Fourth Chapter 2 recipe with this finding; chapter appendix candidate. |
| A2 | MEDIUM | Architecture | Step 1 `trigger_synthesis(trigger)`: `synthesis_id = generate UUID` | Synthesis ID generated per invocation rather than deterministically from event key; EventBridge at-least-once delivery can produce duplicate synthesis runs with different synthesis_ids, bypassing scope-gate suppression if the duplicate arrives before the first run completes. Same recurring Chapter 2 trigger-idempotency pattern (2.4 through 2.10 expert reviews all raised the same class). Sixth consecutive Chapter 2 finding in this class. |
| A3 | MEDIUM | Architecture / Publication Readiness | Step 5 (`anthropic.claude-haiku-4`); Step 6 (`amazon.titan-embed-text-v2`); Step 8 (`anthropic.claude-sonnet-4`) | Bedrock model IDs in pseudocode use literal string values that are not valid Bedrock identifiers (real format includes a date and version suffix). Recipe 2.10's review explicitly named placeholder-with-comment (`SYNTHESIS_MODEL_ID // e.g., Claude Sonnet`) as the chapter template; Recipe 2.9 predates that convention. A reader copying these strings into a real implementation gets `ResourceNotFoundException` or `ValidationException`. |
| S3 | LOW | Security / Architecture | Step 8 Guardrails comment block; "Amazon Bedrock Guardrails for grounding and safety enforcement" paragraph | Contextual grounding threshold not specified; reader configuring Guardrails will default to whatever the console picks (historically 0.5 or 0.7), which is too permissive for a CDS surface. Recipe 2.10's S3. |
| A4 | LOW | Architecture / Cost | Prerequisites Cost Estimate row | End-to-end ceiling ($1.20 per synthesis) may understate worst-case complex multi-scenario costs with broad retrieval and validator retry; realistic worst case approaches $2 per synthesis. |
| N1 | LOW | Networking | Prerequisites VPC row | `execute-api` interface endpoint not called out for private API Gateway; API Gateway posture (public with WAF + Cognito, or private) not explicitly named. Same as Recipe 2.7 N2, Recipe 2.8 N2, Recipe 2.10 N1. |
| N2 | LOW | Networking | Prerequisites VPC row | `CloudWatch (monitoring)` endpoint not distinguished from `CloudWatch Logs`; Lambda in a private subnet without the `monitoring` endpoint would silently fail `PutMetricData` while continuing to log. Same observation as Recipe 2.7, 2.8, 2.10. |
| N3 | LOW | Networking | Prerequisites VPC row | `rds-data` interface endpoint not listed for the Aurora Data API path that the IAM Permissions row explicitly references via `rds-data:ExecuteStatement`. First Chapter 2 recipe to use Aurora as a structured retrieval store. |
| V1 | LOW | Voice / Publication Readiness | Lines 124, 1436, 1437, 1438, 1501 | Five HTML-comment TODO markers for FDA generative-AI CDS guidance status, Chapter 5/7/13 forward references, and HealthBench link verification; HTML-comment form is a substantially better posture than bracket-style TODOs; FDA-guidance-status TODO is the most pressing because regulatory guidance evolves over the book's shelf life. |
| V2 | LOW | Voice / Clinical Accuracy | Expected Results sample JSON, Option B's cefepime renal dose | Sample's cefepime renal dose (1 g q12h at eGFR 11-29) is in the range some references support but is not a single canonical dose; sample is explicitly labeled illustrative via HTML comment, so impact is minor. |
| V3 | LOW | Voice / Publication Readiness | Related Recipes section | Recipe 2.x entries list filenames in the prose ("Recipe 2.10 (Multi-Modal Clinical Reasoning)") but do not include markdown links; the navigation footer at the bottom does link correctly; same-chapter recipes should consistently link or not. |

---

## Recommended Actions (Priority Order)

1. **Fix the architecture diagram's validation-retry branch** (Finding A1). Three-part fix:
   (a) Update the Mermaid diagram to include a bounded retry and a distinct terminal state routing to a human-review queue that does NOT flow into S18/S19/S20/S22. Use Recipe 2.8's pattern as the template.
   (b) Expand the "Post-generation validation" bullet in General Architecture Pattern to explicitly name the terminal state and the non-delivery path.
   (c) Add a short orchestration gate in the pseudocode walkthrough (between Step 9 and Step 10) that explicitly distinguishes `VALIDATED` from `VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW` and routes only `VALIDATED` to tier/suppress/render.
   Coordinate with the Python companion fix from code-review Finding 1 so the two files agree.

2. **Add PHI minimization for patient context serialized into the synthesis prompt** (Finding S1). Introduce a `minimize_phi_for_synthesis` scoping step between Step 2 (normalize) and Step 8 (generate) that strips MRN, DOB, name, address, phone, email, and payer/NPI identifiers from the serialized state before prompt construction. Add a "PHI minimization in prompts" bullet to "Why This Isn't Production-Ready." Strongly recommend a chapter-wide appendix on minimum-necessary-inside-the-BAA, given this is the fourth Chapter 2 recipe with the same finding.

3. **Bind input-side Guardrails prompt-attack filters to the InvokeModel call explicitly** (Finding S2). Add the prerequisite-configuration sentence to the Step 8 Guardrails comment block naming the policy-level configuration (prompt-attack filters enabled on the Guardrail, contextual grounding threshold specified, PII filters tuned for clinical content). Strongly recommend a chapter-wide Guardrails-policy-configuration appendix, given this is the fourth Chapter 2 recipe with the same finding.

4. **Add synthesis-run idempotency** (Finding A2). Derive `synthesis_id` from a deterministic event-key hash; use DynamoDB conditional write (`attribute_not_exists(synthesis_id)`) and Step Functions deterministic execution name to reject duplicates at the orchestration layer. Add a "Trigger idempotency" bullet to "Why This Isn't Production-Ready." Strongly recommend a chapter-wide trigger-idempotency appendix, given this is the sixth consecutive Chapter 2 recipe with the same finding.

5. **Replace literal Bedrock model IDs with placeholder constants** (Finding A3). Update the three Bedrock invocation sites in the pseudocode to use `SMALL_MODEL_ID`, `EMBEDDING_MODEL_ID`, and `SYNTHESIS_MODEL_ID` placeholder constants with family-name comments. Aligns Recipe 2.9 with the Recipe 2.10 chapter template and removes the dated-string risk.

6. **Specify the contextual grounding threshold** (Finding S3). Add one sentence to the Step 8 Guardrails comment block or the Why These Services paragraph naming a conservative threshold at or above 0.85 with scenario-specific tuning guidance.

7. **Clarify cost estimate ceiling for complex syntheses** (Finding A4). Either widen the top-line range to $0.15-$2.00 with a complex-scenario note, or keep the existing range and add a worst-case note ("approach $2 for complex multi-scenario syntheses with validator retry").

8. **Close the LOW networking and voice items** (N1, N2, N3, V1, V2, V3). Add `execute-api` (conditional, private API Gateway), CloudWatch monitoring (PutMetricData), and `rds-data` (conditional, Aurora Data API path) to the VPC row. Verify the FDA generative-AI CDS guidance status (V1) and HealthBench URL (V1) before publication. Either verify the cefepime sample dose against the FDA SPL or add a dose-illustrative disclaimer (V2). Add markdown links to the same-chapter Recipe 2.x entries in Related Recipes (V3) for consistency with the navigation footer.

---

## Notes for Editor

- Finding A1 is now a recurring architecture-safety issue across five Chapter 2 recipes (2.6, 2.7, 2.9, 2.10, with 2.8 demonstrating the fix). For a CDS recipe whose architecture is explicitly built to prevent missed contraindications and missed interactions, this specific flaw leaving the diagram and orchestration ambiguous is the highest-stakes issue in the recipe. The three-part fix (diagram, prose, pseudocode) should be applied in one editorial pass and coordinated with the Python companion's code-review Finding 1 so the two files agree.
- The recurring chapter-wide patterns (PHI minimization S1, input-side Guardrails S2, trigger idempotency A2) have all now passed "repeat observation across multiple recipes" threshold by a wide margin (four recipes with S1, four with S2, six with A2). Three Chapter 2 shared appendices (PHI minimization inside the BAA, Guardrails policy configuration, trigger idempotency) would consolidate these findings and stop the per-recipe recurrence. Each recipe's specifics can reference the appendices rather than repeat the discipline.
- The model-ID precision pattern (A3) is the second Chapter 2 recipe with this finding. Recipe 2.10's review explicitly named placeholder-with-comment as the chapter template. The chapter editor should run a chapter-wide grep for `anthropic\.` and `amazon\.titan` literal strings in pseudocode (not in Python companions, which correctly pin versioned IDs) and apply the placeholder pattern uniformly across earlier chapter recipes that predate the 2.10 convention.
- No bracket-style visible TODO markers in the recipe. Five HTML-comment TODOs, all in the Technology section's FDA paragraph or in Related Recipes / Additional Resources, all forward-placeholder. This is a clean TODO posture; the FDA-guidance-status TODO (line 124) is the most pressing because regulatory guidance evolves over the book's shelf life.
- No em dashes. Direct U+2014 / U+2013 character check: zero matches across approximately 1450 lines. The recipe maintains the no-em-dash discipline cleanly.
- The "Honest Take" section is publication-ready and should be preserved verbatim in any editorial pass. The six failure-pattern enumeration (chasing breadth over depth, under-investing in retrieval, building safety as LLM prompts, not measuring the right things, deferring regulatory review, shipping without clinician buy-in) is the kind of hard-won wisdom the chapter's voice is built on. The five things-that-have-worked enumeration and the closing "Build toward that. Everything else flows from it" land the right final posture.
- The five-vignette opening is the chapter's most authentic clinician-language opening. Each vignette is clinically dense and architecturally tied to a property the body of the recipe defends. Recommend no length reduction in any editorial pass; the verbosity is earned through teaching density rather than filler.
- The "FDA CDS Rule" subsection is the most substantive regulatory framing in the chapter on the FDA exemption specifically. The four-part exemption test is correctly quoted and translated into architectural implications. The "Get your regulatory affairs team involved from day one. Do not build the thing and then ask whether it's a medical device" sentence is publication-ready voice.
- The deterministic-safety-check layer (Step 4) is the architecturally correct posture and is the right teaching move. The validator in Step 9 enforcing that every deterministic finding appears in the synthesis output is the safety-rail the architecture is built around. The diagram-and-orchestration gap in A1 is what undermines the safety-rail; once fixed, the architecture is sound.
- The sample JSON output in Expected Results is dense and clinically authentic. The HTML-comment disclaimer is correctly placed. V2 (cefepime dose verification) is the only content change worth making in the sample.
- Cross-recipe references (Related Recipes section) link backward to Recipes 2.4 through 2.10 and forward to Chapter 5, 7, 13 with concise descriptions. The forward-looking references are honest placeholders and should not be resolved with speculative recipe numbers before those chapters are drafted. The link-consistency observation (V3) applies to the existing back-references, where adding markdown links would match the navigation footer's pattern.
- The corresponding code review for the Python companion (`reviews/chapter02.09-code-review.md`) passed with two WARNINGs; Finding 1 (auto-deliver `REVIEW_REQUIRED`) is the Python-side instance of this review's A1, and Finding 2 (citation substring-match bug in `_replace_citations`) is a Python-file-scope bug unrelated to the main recipe. The A1 fix in the main recipe should be coordinated with the code-review Finding 1 fix in the Python companion.
