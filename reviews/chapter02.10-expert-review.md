# Expert Review: Recipe 2.10 - Multi-Modal Clinical Reasoning

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-12
**Recipe file:** `chapter02.10-multi-modal-clinical-reasoning.md`

---

## Overall Assessment

**Verdict: PASS**

This is the most ambitious recipe in Chapter 2 and, correctly, the most conservative in its posture. The three-layer architecture (modality-specific encoders → reasoning layer → grounding and provenance) is the defensible production pattern for this problem class; "don't put everything in one big multi-modal model" is exactly the right opening move for a healthcare reader. The failure-mode enumeration specific to multi-modal reasoning (cross-modality contradiction swallowed, missing modality ignored, stale modality treated as current, over-reliance on one modality, fabrication on the gap between modalities, specialty register mismatch, quantitative drift, grading fabrication, confidence miscommunication, scope creep, cumulative bias) is the most taxonomically complete list in the book so far and is tightly tied to specific mitigations in the prompt and validator. The regulatory section correctly stages the recipe on the edge of the FDA CDS exemption and names the conditions under which that posture becomes indefensible (imaging impression generation from pixels, diagnostic-not-management outputs, high-stakes scenarios, "replaces specialist consultation" framing, validation surface area). The "Honest Take" is publication-ready and lands the right final posture: narrow scope, cleared components where possible, ferocious grounding, visible reasoning, acknowledge absence and staleness, budget for clinical validation, commit to post-market surveillance, don't conflate fluency with correctness, keep the clinician the decision-maker.

Chapter 2 hygiene carries forward well. IAM row says scope to specific resource ARNs. VPC endpoint list is comprehensive (Bedrock Runtime and Guardrails, Comprehend Medical, HealthLake, HealthImaging, KMS, Secrets Manager, Step Functions, CloudWatch Logs, EventBridge, plus gateway endpoints for S3 and DynamoDB; SageMaker in VPC if used). Bedrock model-invocation-logging PHI store is called out in the Encryption row with the correct framing. No em dashes (direct U+2014 / U+2013 character check: zero matches). No fake Bedrock model IDs in pseudocode (`REASONING_MODEL_ID` as placeholder with `// e.g., Claude Sonnet`). No bracket-style visible-TODO markers. No marketing language ("leverage," "seamless," "unlock," "transform," "empower," "revolutionize" all absent; "state-of-the-art" appears once in a descriptive, non-promotional context). Provenance logging enumerates the full trace (trigger, inventory, retrieval trace, safety findings, prompt version, model version, raw output, validation result, rendered output, clinician engagement). Cost estimate is defensible and appropriately bracketed ($0.40-$4.00 per run) with the reasoning-layer cost correctly identified as the dominant variable.

One HIGH finding recurs from prior Chapter 2 reviews: the architecture diagram's validation-retry branch loops back to generation without a retry cap or a terminal exit to human review, despite the Step 8 pseudocode having an explicit `ROUTED_TO_HUMAN_REVIEW` terminal state. The main orchestration pattern in the prose does say "persistent failures route to human review," but neither the diagram nor the implied Step-9-is-next sequencing in the pseudocode walkthrough models what "route to human review" means as a distinct terminal state that does not flow into rendering and `DELIVERED`. This is the same safety-spine gap flagged in Recipe 2.6 and Recipe 2.7 expert reviews. The code review for this recipe confirms the same gap surfaces in the Python companion as the orchestrator delivering `REVIEW_REQUIRED` outputs. For the recipe in this chapter where the stakes of an unvalidated delivery are highest, the architecture-level fix is non-optional.

Several MEDIUM findings cluster on pseudocode precision: PHI minimization for the patient context and note content passed into the reasoning prompt (same class as Recipe 2.7 S1 and Recipe 2.8 S1); input-side Guardrails prompt-attack filters should be explicitly called out on the InvokeModel site (same class as Recipe 2.7 S2 and Recipe 2.8 S2); modality-ingestion failure modes collapse "failed to retrieve" and "genuinely absent" into a single "absent" signal, which changes clinical interpretation; reasoning-run idempotency on EventBridge at-least-once delivery is not modeled (same recurring Chapter 2 trigger-idempotency pattern); contextual-grounding threshold not named; recommended-but-missing modality handling in the scope gate is under-specified for scenarios outside the explicit "comprehensive_reasoning" branch.

LOW findings are editorial polish: `execute-api` interface endpoint not listed for a private API Gateway; CloudWatch (monitoring) endpoint not distinguished from CloudWatch Logs; sample-output eGFR value is off by ~10% from CKD-EPI 2021 for the stated creatinine (the output is explicitly labeled illustrative, so this is minor); five HTML-comment TODO markers for Chapter 7/9/12/13 cross-references and HealthBench link verification; minor ingestion-scope questions on `recent_runs` retrieval and `derive_narrower_scope` definition.

Priority breakdown: 0 CRITICAL, 1 HIGH, 6 MEDIUM, 5 LOW.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

- BAA is explicit in the Prerequisites table and correctly frames every pipeline component as handling PHI: "Patient context, imaging metadata, ECG interpretations, and the reasoning output itself all contain PHI."
- Encryption parity across all PHI stores: S3 SSE-KMS with customer-managed keys (with the useful operational note that retention policies differ per modality, so distinct CMKs per modality are worth considering); DynamoDB at-rest with CMK; OpenSearch encryption at rest and in transit with fine-grained access control and no public endpoint; Aurora encryption at rest and TLS in transit; HealthLake and HealthImaging encryption at rest with CMK; Bedrock and Comprehend Medical TLS.
- Bedrock model-invocation-logging PHI store is called out explicitly: "Bedrock model-invocation logging (if enabled) contains PHI; log destinations must be encrypted to the same standard as the archive." This addresses the recurring Chapter 2 finding flagged from 2.2 through 2.7.
- IAM row explicitly says "Scope each action to specific resource ARNs." The action list is specific and correct for the pipeline (`bedrock:InvokeModel`, `bedrock:ApplyGuardrail`, `medical-imaging:GetImageSetMetadata`, `medical-imaging:SearchImageSets`, `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM`, `comprehendmedical:InferSNOMEDCT`, etc.).
- CloudTrail data events are required for Bedrock, S3, DynamoDB, HealthLake, HealthImaging, SageMaker endpoint invocations, and Secrets Manager retrievals. Correlation to requesting clinician and patient identifier via Cognito session claims is named explicitly.
- Synthetic-data posture for development is correct: Synthea for FHIR, USPSTF/CDC/HHS for guidelines, MIMIC-CXR reports for imaging-report corpora, PhysioNet for ECG data. "Never use real PHI in dev" is explicit. Evaluation data is correctly framed as requiring clinician-domain-expert curation.
- Sample output is explicitly labeled illustrative via HTML comment block: "the specific findings, quantitative values, and guideline attributions below are illustrative. In a real deployment, every claim grounds in actual content retrieved from a real, current authoritative corpus plus the patient's actual modality records. Do not treat the sample as clinical guidance."
- Source licensing posture is substantive: "Guidelines, drug databases, and institutional protocol content each have their own licensing posture. Imaging-AI vendor outputs are typically covered under the vendor contract and have specific redistribution and retention terms. Cleared models must stay within the cleared use scope. Maintain a license registry and enforce constraints in the rendering and retention layers."
- Security-and-access-control paragraph in "Why This Isn't Production-Ready" correctly names inferred PHI: "Reasoning outputs contain PHI, including inferred PHI (a combination of lab values and imaging findings may reveal more than any single item)." The recommendation to integrate with the EHR authorization model rather than maintain a parallel system is the right posture.

#### Finding S1: PHI Minimization on Patient Context and Note Content Passed Into the Reasoning Prompt

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Step 7 `invoke_reasoning_layer`, `sources_block` construction (the prompt serializes the entire `patient_state.structured_context`, full imaging report text, full ECG machine interpretation, note content as key passages, and retrieved guideline text); the prompt's `PATIENT STRUCTURED CONTEXT` section
- **Problem:** The pseudocode serializes the entire `patient_state.structured_context` (output of `normalize_patient_context`, which the Recipe 2.9 lineage includes MRN, DOB, name, address, phone, provider NPIs) and full note text via `key_passages` (which may preserve identifiers the entity extractor did not scrub) into the reasoning prompt. The reasoning layer does not need MRN, DOB, address, phone, or payer identifiers to produce a differential or a management synthesis; it needs age band, sex if clinically relevant, active problems, current medications, derived values (eGFR, weight), relevant lab trends, and the clinical reasoning content of the notes. Bedrock is HIPAA-eligible and appropriate for PHI, but minimum-necessary applies inside the BAA boundary as well. Recipe 2.7's S1 finding and Recipe 2.8's S1 finding both flagged the same class of issue on their respective prompts. With multi-modal reasoning, the payload is larger than any prior recipe in the chapter, so the PHI exposure surface is correspondingly larger.
- **Fix:** Add a one-paragraph minimization step between Step 3 (normalize and inventory) and Step 7 (invoke reasoning layer):
  ```
  // Before serializing patient state into the reasoning prompt, strip
  // identifiers that are not needed for reasoning.
  //
  // Keep: age band, sex if clinically relevant, active problems, current
  //       medications (drug/dose/frequency/start date), allergies,
  //       derived values (eGFR, BMI, Child-Pugh), lab trends, vitals
  //       summary, imaging findings and report impressions, ECG
  //       interpretation, clinical reasoning content of notes.
  // Drop: MRN, DOB (age band is sufficient), name, address, phone,
  //       email, payer/member IDs, provider NPIs, insurance identifiers.
  //
  // The rendered output re-associates the reasoning to the patient via
  // the run_id/patient_id pointer; identifiers do not need to round-trip
  // through the reasoning prompt.
  patient_state_minimal = minimize_phi_for_reasoning(patient_state)
  ```
  Also add a line to "Why This Isn't Production-Ready" under a "PHI minimization in prompts" bullet, as Recipe 2.8's review recommended.

#### Finding S2: Input-Side Guardrails Prompt-Attack Filters Not Bound to the InvokeModel Call

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Step 7 `invoke_reasoning_layer`, the Bedrock InvokeModel call and its Guardrails comment block
- **Problem:** The reasoning prompt concatenates radiology report text, pathology report text, note key passages, retrieved guideline text, and institutional protocol text directly into the prompt body. Any of these can carry adversarial content: an institutional protocol authored by many hands, a pasted-in foreign-language appendix, an imported PDF guideline that OCR'd instruction-shaped footer text, a note template with a placeholder that survived into production, a radiology report with a testing artifact, a vendor AI output field that carries a free-text comment. The pseudocode comment block names "Denied-topics list including directive prescriptive phrasing outside of verbatim quoted guideline text" and "Content filters enabled" but does not call out input-side prompt-attack filters on the Guardrail policy. Guardrails' prompt-attack filter is configured on the policy itself, not the invocation, so a reader copying the pseudocode and creating a default Guardrail will not get the protection the prose implies. Same class as Recipe 2.7 S2 and Recipe 2.8 S2; the stakes are higher here because the retrieved-text volume is larger.
- **Fix:** Add one explicit sentence to the Guardrails comment block:
  ```
  // Prerequisite: the Guardrail referenced by MM_REASONING_GUARDRAIL_ID
  // must be configured with input-side prompt-attack filters enabled
  // (configured on the Guardrail policy itself, not the invocation), in
  // addition to the contextual grounding output check. Modality inputs
  // (reports, notes, retrieved guidelines, protocols, vendor AI outputs)
  // are untrusted input surfaces, not verified instructions.
  ```
  Optionally add one line in "The Failure Modes, Specific to Multi-Modal" noting retrieved-text as an injection surface in addition to the listed failure modes.

#### Finding S3: Contextual Grounding Threshold Not Specified

- **Severity:** LOW
- **Expert:** Security / Architecture
- **Location:** "Amazon Bedrock Guardrails for contextual grounding enforcement" paragraph; Step 7 Guardrails comment block
- **Problem:** The prose says "Every reasoning output runs through a contextual grounding check against the assembled input context... Grounding failures trigger retry or reject. For multi-modal reasoning the grounding enforcement is non-negotiable because the stakes of fabrication are higher than unimodal cases." The specific threshold (0.85, 0.9, or a scenario-tuned value) is not named. A reader configuring Guardrails will default to whatever the console picks (historically 0.5 or 0.7), which is too permissive for the claimed posture. Recipe 2.9's Python companion called this out with an explicit 0.85+ production recommendation; the main recipe prose here elides it.
- **Fix:** Add one sentence to the Guardrails paragraph: "For this recipe, a grounding threshold at or above 0.85 is the conservative starting point; tune upward for scenarios where fabrication tolerance is lowest (oncology treatment selection, critical-care decisions) and re-evaluate per scenario during clinical validation." Or add this as a line in the Prerequisites table under "Bedrock Model Access" or a dedicated "Guardrail policy configuration" row.

---

### Architecture Expert Review

#### What's Done Well

- The three-layer architecture (modality-specific encoders → reasoning layer → grounding and provenance) is correctly factored for this problem class. The "don't put everything in one big multi-modal model" framing is the right opening move for a healthcare production reader and is defended with five specific reasons (fidelity mismatch with clinical imaging, calibration and confidence, provenance opacity, specialty and institutional fit, regulatory status) that are each clinically and architecturally accurate.
- The compositional pattern (existing cleared imaging AI or cleared vendor interpretations producing structured outputs, existing lab and vitals data, existing note text, fed to a reasoning layer with enforced grounding and visible provenance) is the defensible production posture and aligns with the FDA CDS exemption framing in the regulatory subsection.
- The modality-encoder landscape discussion is honest about the state of practice: narrow FDA-cleared models (PE detection, ICH detection, pneumothorax flagging, breast density estimation) as workflow tools versus vision-language models as documentation assistants with different regulatory posture. The specific clinical examples (thousands of CT slices, T1/T2/FLAIR/DWI MRI sequences, 3D tomosynthesis) correctly frame why a general "image in, finding out" model is the wrong production posture.
- The time-dimension discussion (lab trends as derived features, prior imaging reports as separate retrieved items, temporal event timelines) correctly identifies longitudinal integration as where the reasoning pipeline can add value that clinicians under time pressure cannot.
- The cross-modality-specific failure-mode enumeration (contradiction swallowed, missing modality ignored, stale modality treated as current, over-reliance on one modality, fabrication on the gap between modalities, specialty register mismatch, quantitative drift, grading fabrication, confidence miscommunication, scope creep, cumulative bias) is the most taxonomically complete failure-mode list in the book so far and each failure mode has a specific mitigation tied to the prompt, the validator, or the scope gate.
- The reasoning-layer property list is rigorous: explicit multi-hypothesis consideration, evidence-for-and-against per hypothesis, uncertainty quantification, actionable next steps, visible provenance, explicit scope boundaries. The structured JSON output format enables downstream validation, clean UI rendering, and audit logging.
- The nine-step orchestration (trigger → ingest → normalize → inventory and scope gate → deterministic safety checks → retrieval → reasoning layer → post-generation validation → tier/render/archive) is correctly sequenced. The parallel modality ingestion is the right pattern for latency, and the scope gate as a first-class step before reasoning is a design decision that a novice implementer would likely skip and would pay for in production.
- The regulatory subsection is substantive and correctly stages the recipe at the edge of the FDA CDS exemption: imaging interpretation regulation, diagnostic-vs-management recommendation distinction, high-stakes-decision scrutiny, subspecialty-consultation-replacement framing, validation requirements scale with scope, post-market surveillance expectation. The conservative production posture recommendation (narrow scope, CDS-exemption-compatible design, rigorous validation, controlled pilot, deliberate expansion) is the right framing.
- Cost estimate is defensible ($0.40-$4.00 per run) with a clear breakdown by stage and correct identification of the reasoning layer as the dominant cost when context size is large. The fixed-infrastructure estimate ($1,000-$5,000/month) reasonably accounts for OpenSearch, Aurora, HealthLake, HealthImaging, and optional SageMaker endpoints.
- Implementation-time tiers (16-24 weeks POC; 52-78 weeks production-ready; 104-156 weeks with variations) are honest and appropriate for the scope. Most chapter-closing recipes understate timelines; this one does not.

#### Finding A1: Architecture Diagram's Validation-Retry Branch Has No Retry Cap and No Exit to Human Review

- **Severity:** HIGH
- **Expert:** Architecture / Clinical Safety
- **Location:** Architecture Diagram (Mermaid flowchart, Reason subgraph): `VAL --> RCHK{Pass?}`; `RCHK -->|No| GEN`; `RCHK -->|Yes| TIER`. Also the General Architecture Pattern prose: "Failures retry with augmented prompting; persistent failures route to human review." Also Step 8 pseudocode `RETURN { status: "ROUTED_TO_HUMAN_REVIEW", unverified: unverified }` versus the implied Step 9 (tier/render/archive) as the next step in the walkthrough.
- **Problem:** The diagram shows `RCHK -->|No| GEN` as an unbounded loop with no retry counter, no exit edge to a human-review queue, and no distinct terminal state for "validation exhausted." The Step 8 pseudocode correctly has `IF retry_count < 2: ... RETURN { status: "RETRY_NEEDED" } ... RETURN { status: "ROUTED_TO_HUMAN_REVIEW" }`, but the main orchestration flow does not model what happens when the validator returns `ROUTED_TO_HUMAN_REVIEW`: the walkthrough proceeds linearly from Step 8 to Step 9 (tier/render/archive), which updates DynamoDB to `DELIVERED`, writes the rendered payload to S3, and returns the output to the clinician UI regardless of validation status. The prose sentence "persistent failures route to human review" names the right behavior, but neither the diagram nor the pseudocode models the distinct `ROUTED_TO_HUMAN_REVIEW` terminal state or the non-delivery path. The code review for this recipe (Finding 1) confirms the Python companion implements the flow exactly as the main recipe depicts: `REVIEW_REQUIRED` breaks out of the retry loop and falls through to `tier_render_archive` with `status = "DELIVERED"`, which is the specific safety bypass the validator is designed to prevent.

  This is the same diagram and orchestration flaw flagged in Recipe 2.6 expert review and Recipe 2.7 expert review. Recipe 2.8 resolved the diagram ("the architecture diagram includes a validation-exhausted exit path routing to a human-review queue"). Recipe 2.9's equivalent code-review finding (Finding 1) called out the same orchestration bug in its Python. The pattern has recurred across multiple recipes and the fix template exists (Recipe 2.8's diagram).

  For multi-modal reasoning specifically, the stakes are higher than any previous recipe in the chapter. Validation-exhausted outputs from this pipeline can include: a graded imaging term upgraded from "mild" to "moderate" LV dysfunction; a fabricated ejection-fraction value; a silently-dropped safety finding; an inline-cited source_id that does not resolve to a retrieved source; a directive-language recommendation in the model's voice outside of verbatim-quoted guideline text. The recipe's own "Failure Modes, Specific to Multi-Modal" subsection specifically calls out quantitative drift, graded-term fabrication, and safety-finding coverage as the outcomes the architecture is built to prevent. The orchestrator is the last gate between a flagged reasoning output and the clinician UI, and the diagram (and the implied pseudocode sequencing) depicts that gate as absent.
- **Fix:** Make three changes in lockstep:
  1. **Architecture diagram:** Replace the infinite-loop edge with a bounded retry and a distinct terminal state. Use Recipe 2.8's pattern as the template:
     ```
     VAL --> RCHK{Pass?}
     RCHK -->|Yes| TIER
     RCHK -->|No, retries left| GEN
     RCHK -->|No, retries exhausted| HRQ[Human Review Queue]
     HRQ --> HRS[S3 + DynamoDB<br/>Review Queue Archive]
     ```
     The key visual cue is that the "retries exhausted" edge does NOT flow into TIER/REND/UI.
  2. **General Architecture Pattern prose:** Expand the "Post-generation validation" bullet to explicitly name the terminal state: "Failures retry with augmented prompting up to N times; retry-exhausted failures route to a distinct human-review queue (separate DynamoDB table and S3 archive) and do NOT proceed to tier/render/archive or flow to the clinician UI."
  3. **Pseudocode walkthrough:** Add a short Step 8.5 (or expand Step 9's preamble) showing the orchestrator branch:
     ```
     // The orchestrator MUST distinguish VALIDATED from ROUTED_TO_HUMAN_REVIEW.
     // Only VALIDATED proceeds to Step 9 (tier/render/archive) with
     // status = DELIVERED. ROUTED_TO_HUMAN_REVIEW is a terminal state:
     // write the trace to S3, write the status to DynamoDB as
     // ROUTED_TO_REVIEW, enqueue for a clinical reviewer, and do NOT
     // render to the clinician UI.
     IF validation_result.status == "VALIDATED":
         proceed to Step 9 (tier/render/archive)
     ELSE IF validation_result.status == "ROUTED_TO_HUMAN_REVIEW":
         write trace to S3 (KMS-encrypted)
         update DynamoDB run record with status = "ROUTED_TO_REVIEW"
         enqueue to clinical reviewer queue (SQS or DynamoDB stream)
         RETURN early; do NOT call tier_render_archive
     ```

#### Finding A2: Modality-Ingestion Failure Modes Collapse "Failed to Retrieve" and "Genuinely Absent" Into a Single "Absent" Signal

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 2 modality-ingestion functions (`ingest_imaging`, `ingest_ecg`, `ingest_labs_and_vitals`, `ingest_notes`, `ingest_structured_context`) and Step 3 `normalize_and_inventory` (the `modality_inventory.imaging.present = length(imaging) > 0`, `modality_inventory.ecg.present = length(ecg) > 0` checks)
- **Problem:** Each ingestion function is treated as a pure retrieval and the inventory is built on cardinality (did we get anything back?). There is no distinction between "the modality does not exist for this patient" (the patient has not had an ECG this encounter, so `ingest_ecg` returns `[]` correctly), "the modality exists but retrieval failed" (HealthImaging returned 500, Comprehend Medical throttled, a vendor AI API timed out, HealthLake's FHIR search failed), and "the modality exists but access is scoped out" (a cleared imaging AI vendor has a result but the contract excludes this patient's population). All three paths produce `length(imaging) == 0` with `present = false`, and the reasoning layer receives the same "modality absent" signal in all three cases.

  Clinically, these are different situations. A genuinely-absent ECG should trigger the "obtain ECG" recommendation in the reasoning output. A failed-retrieval ECG should trigger a retry at the orchestration layer, not a clinical recommendation to get an ECG that was actually done. Downstream, the scope gate's `missing_required_modalities` defer path does not distinguish these either: a pipeline that fails to retrieve an imaging study from HealthImaging will tell the clinician "required modalities missing; deferring" when the correct action is "retrying ingestion for this modality." This matters for clinical workflow integration and for alert fatigue: a scope-gate defer is a user-visible event.

  Separately, the pseudocode does not model partial-failure handling at the Step Functions level. Step Functions' Parallel state aggregates branch outputs but does not natively distinguish "branch returned empty" from "branch threw." A production implementation needs explicit error handling per ingestion branch with per-branch retries and a status payload richer than a list.
- **Fix:** Change each ingestion function to return a status-annotated record rather than a bare list:
  ```
  RETURN {
      modality_type:     "imaging",
      status:            "retrieved" | "empty" | "failed" | "scoped_out",
      records:           imaging_records,
      failure_reason:    "healthimaging_timeout" | "comprehend_throttle" | null,
      retry_attempts:    int
  }
  ```
  And update `normalize_and_inventory` to compute inventory from status, not cardinality:
  ```
  imaging_inventory = {
      present:      imaging_result.status == "retrieved",
      absent:       imaging_result.status == "empty",
      failed:       imaging_result.status == "failed",
      scoped_out:   imaging_result.status == "scoped_out",
      count:        length(imaging_result.records),
      most_recent:  most_recent_date(imaging_result.records)
  }
  ```
  And update the scope gate to distinguish these in its `missing_required_modalities` logic: a `failed` modality should route to a retry, not a defer. Add one paragraph to "The Failure Modes, Specific to Multi-Modal" covering the collapse of failed-retrieval into absent as a specific failure mode of naive implementations.

#### Finding A3: Reasoning-Run Idempotency on EventBridge At-Least-Once Delivery Is Not Modeled

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 1 `start_reasoning_run(trigger)`: `run_id = generate UUID`; Step Functions execution started with `name = run_id`
- **Problem:** EventBridge is at-least-once delivery. If the same clinical trigger (new ED presentation, lab result crossing threshold) fires twice, the current pseudocode starts two Step Functions executions with two different UUIDs, each of which runs through the full pipeline and produces a separate reasoning output. The clinician sees two reasoning runs for the same event. At $0.40-$4.00 per run, doubled invocations on duplicate deliveries are a direct cost hit. At the scope-gate level, the second run may hit the suppression window (15-60 minutes depending on scenario) and short-circuit, but only if the second delivery arrives after the first has completed and written its DynamoDB record. If the two deliveries fire close together, both will see an empty suppression-history and both will run.

  This is the same class of trigger-idempotency finding that has recurred in Chapter 2 reviews for 2.4, 2.5, 2.6, 2.7, and 2.8. The specific surface differs (per-patient EventBridge rule, ambient-documentation session, HealthScribe job name), but the pattern is shared: deterministic event-key hashing, conditional DynamoDB writes, and Step Functions execution-name derived from the event key rather than a fresh UUID.
- **Fix:** Derive the run_id from a deterministic event-key hash (or use the event key itself as the run_id) and use a DynamoDB conditional write to enforce idempotency at the orchestration layer:
  ```
  FUNCTION start_reasoning_run(trigger):
      event_key = build_event_key(trigger)
      // For ED presentation: f"{patient_id}:{encounter_id}:ed_dyspnea_workup"
      // For admission: f"{patient_id}:{admission_id}:admission_reasoning"
      // For clinician request: f"{patient_id}:{clinician_id}:{request_timestamp}"
      run_id = deterministic_hash(event_key)

      try:
          put_item to DynamoDB "mm-reasoning-runs":
              run_id = run_id
              status = "INITIATED"
              ... other fields ...
              condition_expression = "attribute_not_exists(run_id)"
      except ConditionalCheckFailedException:
          // Duplicate delivery; the original run is already in flight or complete.
          RETURN { status: "DUPLICATE_SUPPRESSED", run_id: run_id }

      start Step Functions execution:
          name = run_id   // deterministic; second invocation fails with
                          // ExecutionAlreadyExists which the caller handles
  ```
  Also add a paragraph to "Why This Isn't Production-Ready" under a "Trigger idempotency" bullet, as Recipe 2.7's review and Recipe 2.8's review both recommended a shared chapter appendix on this pattern.

#### Finding A4: Scope Gate's Recommended-But-Missing Modality Handling Is Only Defined for `comprehensive_reasoning`

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 4 `scope_gate`: the `IF scenario == "comprehensive_reasoning" AND any_recommended_missing` branch
- **Problem:** The scope gate's "scoped_to" rewriting fires only when the scenario is exactly `"comprehensive_reasoning"`. For any other scenario (including the recipe's own opening vignette `"ed_dyspnea_workup"`), a recommended-but-missing modality (ECG in the ED dyspnea case, say) has no handler. The pseudocode defines `required` and `recommended` modalities for ED dyspnea in a comment (`required = ["structured_context", "labs", "vitals", "imaging:chest"]`, `recommended = ["ecg", "notes:recent"]`), but the scope gate only uses `required` for its defer decision; `recommended` is enumerated but never consulted. The effect is that a scenario-specific run with a missing recommended modality (ED dyspnea with no ECG, which is the exact vignette) proceeds to reasoning without either scoping down or deferring; the `modalities_absent_and_relevant` field in the reasoning output is the only place the absence is communicated, and that is a model-behavior property rather than an architectural guarantee.

  The sample output in Expected Results gets this right (the ED dyspnea vignette proceeds to reasoning and flags ECG absence in `modalities_absent_and_relevant` with recommendation "Obtain 12-lead ECG before further reasoning on cardiac etiologies"), but that is a property of the reasoning model following the prompt's hard requirements. An architectural-gated flow would be more defensible: if a recommended modality is missing for a scenario, either run narrower reasoning, emit a "cannot reason confidently without X; obtain and rerun" response, or proceed with a lower-confidence label driven by the scope gate.
- **Fix:** Expand the scope gate's `recommended`-modality handling beyond `comprehensive_reasoning`:
  ```
  // Recommended-but-missing modalities affect every scenario, not just
  // comprehensive reasoning. Three options:
  //   (a) If any recommended modality is missing and scenario can be
  //       narrowed, scope down to a narrower scenario.
  //   (b) If scenario cannot be narrowed, proceed but flag the run with
  //       lower completeness_of_data at the scope-gate level (the
  //       validator enforces this at the reasoning-layer level, too).
  //   (c) For scenarios where recommended modalities are effectively
  //       required (e.g., ECG for ACS-inclusive reasoning), promote
  //       recommended to required per sub-scenario and defer.
  missing_recommended = recommended \ available_modalities
  IF length(missing_recommended) > 0:
      IF narrower_scope_exists(scenario, missing_recommended):
          decision.scoped_to = narrower_scope
          decision.reason = "scoped_down_due_to_missing_recommended_modalities"
      ELSE:
          decision.scoped_to = scenario
          decision.completeness_cap = "low"
  ```
  The production wiring here benefits from a scenario-to-modality map that distinguishes required from recommended per sub-scenario (ACS workup without ECG is a deferral; generic ED dyspnea without ECG is a narrowing with an explicit recommendation).

#### Finding A5: Reasoning-Run Suppression Depends on a `recent_runs` Lookup That Is Not Defined

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** Step 4 `scope_gate(scenario, modality_inventory, patient_id, recent_runs)`: the `recent_runs` argument; the suppression check `IF recent.scenario == scenario AND recent.age_minutes < SUPPRESSION_WINDOW_FOR(scenario) AND no_material_change_since(...)`
- **Problem:** `recent_runs` arrives as a pre-fetched argument, but neither its source nor the fetch logic is specified in the pseudocode. A production implementation must query DynamoDB by patient_id (or by patient_id plus encounter_id, depending on whether the suppression is per-patient or per-encounter) over a rolling window, and the query pattern has specific implications for DynamoDB table design (either a GSI on patient_id or a composite-key schema with patient_id as the partition key). `no_material_change_since` is similarly under-specified: it could be a last-modality-timestamp comparison, a hash comparison of the modality inventory, or a semantic-change detector on the clinical state. Different choices produce different suppression behavior.

  The suppression logic is the alert-fatigue mitigation for this pipeline; under-specifying it means a reader copying the recipe will either over-suppress (missing clinically relevant re-reasoning opportunities) or under-suppress (alert fatigue).
- **Fix:** Add two to three lines defining `recent_runs` and `no_material_change_since`:
  ```
  // recent_runs is a DynamoDB query on the mm-reasoning-runs table by
  // (patient_id, initiated_at) over the past SUPPRESSION_WINDOW_HOURS
  // (typically 24 hours). GSI on patient_id required; consider a
  // time-based partition key (patient_id + date) for high-volume
  // facilities.
  //
  // no_material_change_since compares the current modality inventory's
  // content hash to the prior run's stored inventory hash. Material
  // changes include: new imaging study, new ECG, lab value crossing a
  // clinical threshold, new note of a relevant type, medication change.
  ```

#### Finding A6: Cost Estimate Underweights Long-Context Reasoning-Layer Costs for Broad Scenarios

- **Severity:** LOW
- **Expert:** Architecture / Cost
- **Location:** Prerequisites table, Cost Estimate row: "reasoning layer $0.15-$2.50 (depends heavily on context size and model choice)"
- **Problem:** The upper bound of $2.50 for the reasoning layer is reasonable for focused scenarios with modest context sizes. For comprehensive reasoning on a patient with several years of longitudinal imaging, multiple specialty notes, full lab trend histories, and a large guideline-retrieval set, the context can push into the 100k+ token range on Claude Sonnet, where input pricing alone approaches $0.30-$0.60 per call before output tokens. A patient with multiple reasoning iterations on retry (the validator's retry loop multiplies this) can realistically exceed $5 per end-to-end run in worst-case scenarios. The $0.40-$4.00 top-line range in the header and the row may understate the ceiling for the most complex cases by roughly 25-50%.
- **Fix:** Either (a) widen the top-line range to $0.40-$6.00 with a note that the top of the range applies to comprehensive reasoning with multi-year longitudinal context and maximum retrieval breadth, or (b) keep the existing range and add one line below the table: "For broad scenarios with large longitudinal contexts and validator retry, per-run cost can exceed the top of this range; for budgeting, assume $5-$8 per run for worst-case complex scenarios."

---

### Networking Expert Review

#### What's Done Well

- The VPC row is comprehensive. Interface endpoints for Bedrock (Runtime and Guardrails), Comprehend Medical, HealthLake, HealthImaging, KMS, Secrets Manager, Step Functions, CloudWatch Logs, and EventBridge cover the HIPAA-eligible services the pipeline uses. Gateway endpoints for S3 and DynamoDB are correctly included (they are free in most accounts and don't carry the per-AZ-per-endpoint cost). Aurora and OpenSearch in VPC with security groups restricted to the Lambda execution role is the right posture. SageMaker Endpoints in VPC if used is correctly conditional.
- Per-AZ-per-endpoint cost reminder ("Factor interface endpoint costs into the cost estimate") appears in the VPC row, which is the Chapter 2 hygiene carry-forward.
- API Gateway with Cognito is correctly framed as the clinician-facing entry point. SMART on FHIR for EHR-launched flows and CDS Hooks for workflow triggers are named with their appropriate use cases.
- TLS in transit is specified across every PHI-carrying data flow (Bedrock, Comprehend Medical, HealthLake, HealthImaging explicitly; implicit for Aurora, DynamoDB, S3 via HTTPS endpoints).
- CloudTrail data events for S3, DynamoDB, HealthLake, HealthImaging, SageMaker, and Secrets Manager provide the audit plumbing for cross-service correlation.

#### Finding N1: `execute-api` Interface Endpoint Not Called Out for Private API Gateway

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites "VPC" row; "Amazon API Gateway with Amazon Cognito for the clinician-facing API" paragraph
- **Problem:** The recipe does not specify whether API Gateway is deployed as a public or private REST API. For a clinician-facing endpoint in a healthcare institution, the production posture is often private (reachable from the corporate network via VPN/Direct Connect, not from the public internet), which requires the `com.amazonaws.{region}.execute-api` interface endpoint. The VPC row lists every other interface endpoint used by the pipeline but omits this one. Same pattern as N2 in Recipe 2.7's review and N2 in Recipe 2.8's review.
- **Fix:** Add a conditional line to the VPC row: "If API Gateway is configured as a private REST API (recommended for EHR-internal clinician-facing endpoints), add `execute-api` interface endpoint." Also name the API Gateway posture (public with WAF + Cognito, or private) in the "Amazon API Gateway with Amazon Cognito" paragraph so the reader knows which pattern the recipe assumes.

#### Finding N2: CloudWatch Monitoring (Metrics) Endpoint Not Distinguished from CloudWatch Logs Endpoint

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites "VPC" row
- **Problem:** The VPC row lists "CloudWatch Logs" but the pipeline also emits custom metrics via `PutMetricData` (Step 9's CloudWatch emissions: `ReasoningRunsDelivered`, `ModalitiesUsedPerRun`, `CrossModalityContradictionsSurfaced`, `OverallUncertaintyDistribution`). CloudWatch Logs uses `com.amazonaws.{region}.logs`; CloudWatch monitoring uses `com.amazonaws.{region}.monitoring`. They are distinct endpoints. A Lambda in a private subnet without the `monitoring` endpoint will fail to publish custom metrics but continue to write logs, which produces a silent metrics-coverage gap in dashboards and alarms. Same observation from prior Chapter 2 reviews.
- **Fix:** Add `CloudWatch (monitoring)` to the interface-endpoint list in the VPC row, or rename the entry to `CloudWatch Logs and CloudWatch (monitoring)` to cover both.

---

### Voice Reviewer

#### What's Done Well

- The opening ED dyspnea vignette (62-year-old woman with anthracycline-treated breast cancer, CKD, diabetes, and rheumatoid arthritis on methotrexate, presenting with progressive dyspnea and five plausible diagnoses) is clinically dense, specific, and voice-authentic. The enumeration of competing hypotheses (heart failure exacerbation with anthracycline cardiotoxicity contribution, PE, atypical pneumonia, ACS, anthracycline cardiomyopathy) is exactly how an experienced emergency physician thinks through this presentation. The follow-through through three more scenarios (chronic primary care multi-morbidity, hepatology transplant listing, pulmonary nodule risk stratification) widens the frame without diluting it and hits the common pain points across ambulatory, specialty, and screening medicine.
- "The clinician cannot assimilate all of it in twenty minutes. Nobody can." This is the kind of plainspoken authority-statement CC's voice is built on. No hedging, no apology. The paragraph that follows correctly frames the clinical reasoning task as "running a multi-modal reasoning task on a compressed time budget with a human-sized working memory," which is engineer-language for a clinician's experience.
- "Two years ago, this was science fiction. Today, it is barely feasible for narrow scenarios with heavy engineering investment and a willingness to keep the deployment posture conservative." This is the correct temporal and risk framing and earns the reader's trust for the rest of the recipe.
- The technology section explicitly names what "multi-modal" means for this recipe ("the system integrates clinical information that lives in structurally different representations"), which is the kind of definition discipline that separates teaching prose from marketing.
- "Why Not Just Put Everything in One Big Multi-Modal Model?" is the strongest single subsection in the recipe. The five reasons (fidelity mismatch with clinical imaging, calibration and confidence, provenance opacity, specialty and institutional fit, regulatory status) are each clinically and architecturally accurate. "A model that accepts 'an image' and produces 'a finding' is usually operating on a small number of 2D images and missing most of the diagnostic signal a radiologist would use. The research publications tend to feature well-chosen 2D images that match this architecture; production clinical imaging does not." This is the kind of honest calibration that a working clinician-architect would write.
- The modality-encoder landscape paragraphs are correctly honest about the state of practice. Narrow FDA-cleared imaging AI as workflow tools versus vision-language models as documentation assistants is the right distinction, and the specific cleared-product examples (pulmonary embolism detection on CT pulmonary angiography, intracranial hemorrhage detection on CT head, pneumothorax flagging on chest radiograph, breast density estimation on mammography) are real and currently-deployed categories. The named vendors (Aidoc, Viz.ai, RapidAI) are correct placements; the recipe correctly attributes their deployments to specific indications rather than "AI radiology."
- "Grounding and Hallucination: The Problem Scales With Modalities" is the right framing and the subsection earns it. The specific failure-mode examples (a hallucinated "moderate LV hypertrophy" in a reasoning output, ejection fraction fabricated as "45%" when the source says "55% on the 2023 echo and has not been repeated since," radiology grade upgrades from "mild" to "moderate") are concrete and clinically accurate.
- "Regulatory Posture, for Real This Time" is the most substantive regulatory subsection in any recipe so far. The five considerations (imaging interpretation regulation, diagnostic-vs-management recommendation distinction, high-stakes-decision scrutiny, subspecialty-consultation-replacement framing, validation requirements scale with scope, post-market surveillance) are each clinically accurate and tied to specific design implications.
- "The Failure Modes, Specific to Multi-Modal" is the best failure-mode taxonomy in the book so far. Each of the eleven items has a mitigation tied to the prompt, the validator, or the scope gate. The architectural fidelity between the failure-mode list and the pseudocode is high.
- "Why This Isn't Production-Ready" is substantive and honest: regulatory determination, clinical validation per scope (with the realistic four-to-eight-weeks-per-scenario reviewer budget), post-market outcomes monitoring, modality-pipeline quality assurance, cleared imaging AI integration correctness, source freshness, bias and equity, prompt and model versioning, fallback and degradation, audit logs and retention, liability and licensing posture, workflow integration, patient consent and communication, cost control at scale, specialty and institutional adaptation, security and access control. Sixteen substantive bullets; no filler.
- "The Honest Take" is publication-ready. "Start with the narrowest possible scope." "Build on cleared components where possible." "Enforce grounding ferociously." "Make reasoning visible in the UI." "Acknowledge missing and stale modalities explicitly." "Budget time for clinical validation you cannot skip." "Commit to post-market surveillance." "Do not conflate fluency with correctness." "Keep the clinician the decision-maker." Each item is specific, hard-won, and consistent with the architectural and regulatory framing. The closing personal note ("the patients who benefit from this the most are the complicated ones... these are exactly the patients who experience the most documentation-driven failures in the current system. Getting this right is not a technical curiosity; it is a meaningful improvement in how care is delivered. Getting it wrong, correspondingly, hurts the patients who need it most. Build like it matters.") is the voice at its best.
- No em dashes. Direct U+2014 and U+2013 character check: zero matches. The recipe maintains the prose rules through its length (~1600 lines) without a lapse.
- 70/30 vendor balance is clean. The Problem, Technology, and General Architecture Pattern sections are vendor-neutral. AWS services enter in the AWS Implementation section and do not leak back. The "Why These Services" paragraphs connect each service to the concept it implements from the vendor-neutral discussion.
- No marketing language. No "leverage," "seamless," "unlock," "transform," "empower," "revolutionize." The one occurrence of "state-of-the-art" is descriptive, not promotional.
- Variations and Extensions section is substantive: scenario-specific reasoning modules, tumor board preparation, comparative imaging with prior studies, risk-score integration and explanation, lab trend and medication adjustment synthesis, second-opinion synthesis, genomic-informed reasoning, continuous-monitoring integration, patient-facing reasoning summaries, retrospective case review for quality improvement. Ten substantive variations, each tied to a specific clinical workflow.
- Related Recipes cross-references are voice-appropriate and correctly link back to Recipes 2.5, 2.6, 2.7, 2.8, 2.9 with one-line descriptions of the connection.

#### Finding V1: Five HTML-Comment TODO Markers in Related Recipes and Additional Resources

- **Severity:** LOW
- **Expert:** Voice / Publication Readiness
- **Location:**
  - Line 1471: `<!-- TODO (TechWriter): update to specific recipe number once Chapter 9 is drafted. -->` (Recipe 9.x Computer Vision reference)
  - Line 1472: `<!-- TODO (TechWriter): update to specific recipe number once Chapter 12 is drafted. -->` (Recipe 12.x Time Series reference)
  - Line 1473: `<!-- TODO (TechWriter): update to specific recipe number once Chapter 13 is drafted. -->` (Recipe 13.x Knowledge Graphs reference)
  - Line 1474: `<!-- TODO (TechWriter): update to specific recipe number once Chapter 7 is drafted. -->` (Recipe 7.x Predictive Analytics reference)
  - Line 1543: `<!-- TODO (TechWriter): verify current status and URL of HealthBench. -->` (HealthBench benchmark link)
- **Problem:** HTML-comment TODOs survive Markdown-to-HTML rendering paths as view-source comments but don't render visibly to readers of the published output. This is a substantially better posture than Recipe 2.8's eight bracket-style visible TODOs (which was a HIGH finding) or the similar patterns in Recipes 2.5, 2.6, 2.7. Same class as Recipe 2.8 V2. The forward-placeholder pattern ("Recipe 9.x" with a one-line description) is voice-appropriate and reads cleanly even if the TODOs are never resolved, which is the right posture for a book where later chapters are still being drafted. The HealthBench TODO is a single link verification.
- **Fix:** For the Chapter 7/9/12/13 cross-references, either (a) leave as-is with the understanding that the forward-placeholder text reads cleanly to a reader, or (b) resolve by grepping the `categories/` planning files for the corresponding recipe numbers and updating once those chapters are drafted. For HealthBench, either verify the link is current or remove the entry; as of the most recent OpenAI release cycle the URL format was stable, but periodic verification before each book revision is the right discipline.

#### Finding V2: Expected-Results Sample eGFR Value Slightly Off by CKD-EPI 2021

- **Severity:** LOW
- **Expert:** Voice / Clinical Accuracy
- **Location:** Expected Results sample JSON, `safety_findings_included` entry: "Renal function: current creatinine up from baseline [lab:2160-0]; eGFR estimated at 40 is a decrease from prior baseline of 44."
- **Problem:** The vignette describes a 62-year-old woman with creatinine 1.6 (baseline 1.3) and baseline eGFR 44. Using the CKD-EPI 2021 race-free equation for a female patient, the math works as follows:
  - Baseline creatinine 1.3, age 62: eGFR approximately 46-47 (close enough to the stated 44)
  - Current creatinine 1.6, age 62: eGFR approximately 36-37, not 40
  The sample output's "eGFR estimated at 40" understates the decrement by roughly 10%. The sample is explicitly labeled illustrative via HTML comment ("Do not treat the sample as clinical guidance"), and the recipe's framing around illustrative outputs is correct, so this is a minor polish issue rather than a clinical accuracy failure. A careful clinical reader copying the sample into a test fixture for a demo environment will notice the arithmetic inconsistency, which slightly undermines the sample's credibility.
- **Fix:** Either (a) update the sample text to "eGFR estimated at 36 is a decrease from prior baseline of 44" to match the CKD-EPI 2021 calculation, or (b) keep the current text and add a one-line note under the HTML comment ("Numeric derivations in the sample are illustrative and may not match CKD-EPI precision; do not copy into fixtures without recalculation"). Option (a) is the cleaner fix. The broader observation ("contrast protocol consideration for CT pulmonary angiography") remains clinically correct regardless of the exact eGFR value.

#### Finding V3: `REASONING_MODEL_ID` Placeholder in Pseudocode Versus Fully-Versioned ID in Python Companion

- **Severity:** LOW
- **Expert:** Voice / Publication Readiness
- **Location:** Step 7 `invoke_reasoning_layer`: `model_id = REASONING_MODEL_ID       // e.g., Claude Sonnet`; Python companion (per code review) pins `"anthropic.claude-3-5-sonnet-20241022-v2:0"`
- **Problem:** The pseudocode uses a placeholder constant with a family-name comment ("Claude Sonnet"), which is correct style for pseudocode and avoids the "fake model ID" problem that appeared in Recipes 2.7 and 2.8. The Python companion pins a specific versioned ID. The two files agree in intent but differ in representation. This is the cleanest form of the pseudocode-vs-Python model-ID gap that has recurred across the chapter, and it is not a defect; the pattern of placeholder-in-pseudocode plus versioned-ID-in-Python is the right teaching split. Flagged for cross-recipe consistency tracking rather than a fix.
- **Fix:** No fix required. Optional: add one sentence near the first Bedrock invocation noting that Bedrock model IDs are versioned and the Python companion pins a specific working example ("see the Python companion for the exact model ID used in this recipe's testing"). Same observation applies to the `SMALL_MODEL_ID` placeholder and the `EMBEDDING_MODEL_ID` placeholder.

---

## Stage 2: Expert Discussion

**Overlap: Architecture (A1) and the code review's Finding 1 (auto-deliver `REVIEW_REQUIRED`).**
The architecture-diagram infinite-loop and the prose-orchestration silence on `ROUTED_TO_HUMAN_REVIEW` are the same gap surfaced in the main recipe that, in the Python companion, becomes the specific orchestrator bug of auto-delivering `REVIEW_REQUIRED` with `status = DELIVERED`. The code review flagged the Python-side instance as a WARNING; the main recipe's architecture is the upstream cause. Fixing the main recipe's diagram and walkthrough (A1) without fixing the Python companion's orchestrator is a half-measure; fixing the Python companion's orchestrator without updating the diagram and prose leaves the main recipe misleading future readers. The editor should treat this as a linked pair and update both in the same pass.

**Overlap: Security (S1) and Architecture (A2).**
S1 (PHI minimization in prompts) and A2 (ingestion-failure vs genuine-absence distinction) are both about what information the reasoning layer should and should not receive. S1 is about removing unnecessary PHI fields before serialization; A2 is about making the inventory richer with status semantics. They do not conflict and can be applied in one localized edit to Steps 3 and 7. The minimization step from S1 and the status-annotated ingestion from A2 compose cleanly: minimize on normalize, annotate with status on ingest, build inventory from status on normalize.

**Overlap: Security (S2) and the recurring retrieved-text injection pattern.**
S2 (input-side Guardrails) is the multi-modal version of the same finding that appeared as Recipe 2.7 S2 and Recipe 2.8 S2. Across three recipes, the pattern is: the main recipe's prose describes input-side prompt-attack handling; the pseudocode only wires output-side contextual grounding; the prerequisite Guardrail-policy configuration is under-specified. The fix is small and local per recipe; the aggregate recommendation, which has recurred now in three reviews, is that Chapter 2's preface or a chapter-wide Guardrails-configuration appendix should lift the policy-level configuration checklist once rather than repeating it in each recipe's Step 7 comment block.

**Overlap: Architecture (A3) and the chapter-wide trigger-idempotency pattern.**
A3 (reasoning-run idempotency on EventBridge at-least-once delivery) is the fifth consecutive Chapter 2 finding in this class (2.4, 2.5, 2.6, 2.7, 2.8 reviews all raised the same pattern with different specifics). The per-recipe fix is small; the chapter-wide recommendation, which has now passed "recurring observation" threshold, is a shared appendix or preface section on trigger idempotency covering the conditional-write pattern, deterministic-name pre-check pattern, and execution-token suffix pattern. Each recipe's specifics differ but the underlying discipline is shared.

**Non-conflict: Architecture (A4, A5, A6).**
A4 (recommended-but-missing modality handling), A5 (recent_runs lookup definition), and A6 (cost-estimate ceiling for comprehensive-scenario contexts) are independent pseudocode-precision items. None conflict with findings in other lenses.

**Non-conflict: Networking (N1, N2).**
Each is a one-line addition to the VPC row. Same pattern as N1 and N2 in Recipe 2.7's review and Recipe 2.8's review; the chapter-wide VPC-endpoint list has stabilized enough that the remaining per-recipe gaps are the conditional endpoints (execute-api, monitoring) that a reader might forget.

**Non-conflict: Voice (V1, V2, V3).**
V1 (HTML-comment TODOs) is editorial polish; V2 (eGFR math) is illustrative-sample polish; V3 (model-ID placeholder pattern) is a non-defect observation.

**Pattern observation: the architecture is sound; the orchestration safety gap is the only HIGH finding.**
Unlike Recipe 2.5 (CRITICAL clinical inconsistency), Recipe 2.6 (four HIGH pipeline gaps), or Recipe 2.8 (three HIGH publication-readiness findings), the architecture here is mature on every axis except the validation-exhausted terminal state. The teaching is among the strongest in the chapter alongside Recipes 2.7 and 2.8. The failure-mode taxonomy is the most complete in the book. The regulatory framing is the most substantive. The "Honest Take" is publication-ready. The one HIGH finding (A1) is an architectural safety issue, not a teaching-quality issue, and the fix template from Recipe 2.8 applies directly.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

One HIGH finding, which is below the "more than 3 HIGH = FAIL" threshold. No CRITICAL findings. The architecture is sound, the teaching is among the strongest in the chapter, Chapter 2 hygiene patterns (IAM scoping to resource ARNs, VPC endpoint coverage, Bedrock model-invocation-logging PHI, no em dashes, no fake Bedrock model IDs, no bracket-style visible TODOs, source licensing posture, regulatory framing) are addressed, the failure-mode taxonomy is the most complete in the book so far, and the "Honest Take" is publication-ready.

The one HIGH finding is the recurring architecture-diagram validation-retry flaw that has appeared in Recipes 2.6 and 2.7 and was resolved in Recipe 2.8. For the recipe where validation-exhausted delivery is most consequential (multi-modal reasoning touching imaging, cross-modality synthesis, graded terms, quantitative preservation), the architecture-level gap cannot remain. The fix has three parts (diagram, prose, pseudocode) and is localized; Recipe 2.8 provides the template.

The six MEDIUM findings cluster on pseudocode precision:
- **S1** PHI minimization on patient context and note content passed into the reasoning prompt.
- **S2** input-side Guardrails prompt-attack filters bound to the InvokeModel call.
- **A2** modality-ingestion status semantics distinguishing failed-retrieval from genuinely-absent.
- **A3** reasoning-run idempotency on EventBridge at-least-once delivery.
- **A4** recommended-but-missing modality handling beyond `comprehensive_reasoning`.
- (And the adjacent scope-gate helper under-specification A5 and cost-ceiling A6 as LOW.)

The five LOW findings are polish: `execute-api` and CloudWatch monitoring endpoints (N1, N2), HTML-comment TODOs (V1), sample-output eGFR arithmetic (V2), pseudocode-vs-Python model-ID pattern (V3, non-defect).

With the A1 fix (diagram + prose + pseudocode) and a clean-up pass on the MEDIUM findings, this recipe sets the quality bar for chapter capstones across the book. The conceptual teaching, the failure-mode taxonomy, the regulatory framing, and the "Honest Take" are all publication-ready.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| A1 | HIGH | Architecture / Clinical Safety | Architecture Diagram Reason subgraph; General Architecture Pattern prose; Step 8 → Step 9 transition in pseudocode walkthrough | Architecture diagram's validation-retry branch loops back to generation with no retry cap and no exit to human review; pseudocode Step 8's `ROUTED_TO_HUMAN_REVIEW` terminal state is not modeled in the main orchestration flow; Python companion (per code review Finding 1) implements the gap as auto-delivery of `REVIEW_REQUIRED` with `status = DELIVERED`. Same pattern as Recipe 2.6 and 2.7 expert reviews; fix template in Recipe 2.8. Highest stakes in the chapter because multi-modal reasoning outputs include graded imaging terms, ejection-fraction values, safety findings, and citation discipline. |
| S1 | MEDIUM | Security | Step 7 `invoke_reasoning_layer`, `sources_block` construction and `PATIENT STRUCTURED CONTEXT` prompt section | Patient context (including potential MRN, DOB, name, address, phone, NPIs) and full note content serialized into the reasoning prompt without minimum-necessary scoping; Bedrock under BAA is compliant, but minimum-necessary applies inside the BAA boundary as well. Same class as Recipe 2.7 S1 and Recipe 2.8 S1. |
| S2 | MEDIUM | Security | Step 7 Guardrails comment block | Input-side prompt-attack filters referenced in prose but policy-level Guardrail configuration prerequisite not explicitly bound to the InvokeModel call; retrieved modality content (reports, notes, guidelines, protocols, vendor AI outputs) is an untrusted-input surface. Same class as Recipe 2.7 S2 and Recipe 2.8 S2. |
| A2 | MEDIUM | Architecture | Step 2 modality-ingestion functions; Step 3 `normalize_and_inventory` | Modality ingestion collapses "failed to retrieve" (HealthImaging timeout, Comprehend Medical throttle, vendor AI 500) into the same "absent" signal as "genuinely absent" (patient did not have this modality); clinically different situations with different correct actions (retry vs clinical recommendation). Scope gate's defer path inherits the collapse. |
| A3 | MEDIUM | Architecture | Step 1 `start_reasoning_run(trigger)` | Reasoning-run UUID generated per invocation rather than deterministically from event key; EventBridge at-least-once delivery can produce duplicate reasoning runs with different run_ids, bypassing suppression if the duplicate arrives before the first run completes. Same recurring Chapter 2 trigger-idempotency pattern (2.4, 2.5, 2.6, 2.7, 2.8 reviews all raised the same class). |
| A4 | MEDIUM | Architecture | Step 4 `scope_gate`: the `IF scenario == "comprehensive_reasoning" AND any_recommended_missing` branch | Scope gate's "scoped_to" rewriting fires only for exact `comprehensive_reasoning` scenario; for any other scenario (including ED dyspnea), a recommended-but-missing modality has no handler; the architectural behavior for "ECG recommended but missing on ED dyspnea" depends on the reasoning layer following the prompt's hard requirements, not on a scope-gate guarantee. |
| A5 | LOW | Architecture | Step 4 `scope_gate`: `recent_runs` argument and `no_material_change_since` call | `recent_runs` arrives pre-fetched but source and fetch pattern are not specified; `no_material_change_since` is not defined; both are under-specified for a reader implementing from pseudocode; suppression is the alert-fatigue mitigation for the pipeline and should be pinned. |
| A6 | LOW | Architecture / Cost | Prerequisites Cost Estimate row | Reasoning-layer top-line ceiling ($2.50 per run; $4.00 end-to-end) may understate worst-case comprehensive-scenario costs with multi-year longitudinal context by 25-50%; realistic worst case is $5-$8 per run. |
| N1 | LOW | Networking | Prerequisites VPC row | `execute-api` interface endpoint not called out for private API Gateway; API Gateway posture (public with WAF + Cognito, or private) not explicitly named. |
| N2 | LOW | Networking | Prerequisites VPC row | `CloudWatch (monitoring)` endpoint not distinguished from `CloudWatch Logs`; Lambda in a private subnet without the `monitoring` endpoint would silently fail `PutMetricData` while continuing to log. |
| V1 | LOW | Voice / Publication Readiness | Related Recipes (lines 1471-1474) and Additional Resources (line 1543) | Five HTML-comment TODO markers for Chapter 7/9/12/13 cross-references and HealthBench link verification; HTML-comment form is a substantially better posture than bracket-style TODOs; forward-placeholder text reads cleanly if unresolved. |
| V2 | LOW | Voice / Clinical Accuracy | Expected Results sample JSON, `safety_findings_included` renal-function entry | Sample-output eGFR value ("estimated at 40") is off by roughly 10% from CKD-EPI 2021 for stated creatinine 1.6 at age 62 (actual ~36); sample is explicitly labeled illustrative via HTML comment, so impact is minor. |
| V3 | LOW | Voice / Publication Readiness | Step 7 `REASONING_MODEL_ID` placeholder versus Python companion's versioned ID | Non-defect observation: pseudocode uses placeholder constant with family-name comment ("Claude Sonnet"); Python pins versioned ID. The correct teaching split, flagged for cross-recipe consistency tracking. |

---

## Recommended Actions (Priority Order)

1. **Fix the architecture diagram's validation-retry branch** (Finding A1). Three-part fix:
   (a) Update the Mermaid diagram to include a bounded retry and a distinct terminal state routing to a human-review queue that does NOT flow into TIER/REND/UI. Use Recipe 2.8's pattern as the template.
   (b) Expand the "Post-generation validation" bullet in General Architecture Pattern to explicitly name the terminal state and the non-delivery path.
   (c) Add a short orchestration gate in the pseudocode walkthrough (between Step 8 and Step 9) that explicitly distinguishes `VALIDATED` from `ROUTED_TO_HUMAN_REVIEW` and routes only `VALIDATED` to tier/render/archive.
   Coordinate with the Python companion fix from code-review Finding 1 so the two files agree.

2. **Add PHI minimization for patient context and note content passed into the reasoning prompt** (Finding S1). Introduce a `minimize_phi_for_reasoning` scoping step between Step 3 (normalize and inventory) and Step 7 (invoke reasoning layer) that strips MRN, DOB, name, address, phone, email, and payer/NPI identifiers from the serialized state before prompt construction. Add a "PHI minimization in prompts" bullet to "Why This Isn't Production-Ready."

3. **Bind input-side Guardrails prompt-attack filters to the InvokeModel call explicitly** (Finding S2). Add the prerequisite-configuration sentence to the Step 7 Guardrails comment block naming the policy-level configuration (prompt-attack filters enabled on the Guardrail, contextual grounding threshold specified, PII filters tuned for clinical content). Optionally lift to a chapter-wide Guardrails-configuration appendix.

4. **Annotate modality ingestion with status semantics** (Finding A2). Change each ingestion function's return to include `status: "retrieved" | "empty" | "failed" | "scoped_out"` plus `failure_reason` and `retry_attempts`. Update `normalize_and_inventory` to build the inventory from status, not cardinality. Update the scope gate to distinguish `failed` (retry) from `empty` (defer or proceed). Add a paragraph to "The Failure Modes, Specific to Multi-Modal" covering the collapse as a specific naive-implementation pitfall.

5. **Add reasoning-run idempotency** (Finding A3). Derive `run_id` from a deterministic event-key hash; use DynamoDB conditional write (`attribute_not_exists(run_id)`) and Step Functions deterministic execution name to reject duplicates at the orchestration layer. Add a "Trigger idempotency" bullet to "Why This Isn't Production-Ready." Consider proposing a chapter-wide trigger-idempotency appendix, as this is the fifth consecutive recipe with the same finding class.

6. **Expand the scope gate's recommended-but-missing modality handling** (Finding A4). Remove the `comprehensive_reasoning`-only restriction; handle recommended-but-missing modalities for every scenario via one of three branches (narrow scope, proceed with lower completeness cap, or defer when recommended is effectively required). Define the scenario-to-modality map more explicitly.

7. **Specify `recent_runs` lookup and `no_material_change_since`** (Finding A5). Add two to three lines of pseudocode defining the DynamoDB query pattern (GSI on patient_id) and the material-change comparison (modality inventory hash; named material changes list). Pin the suppression window values per scenario.

8. **Clarify cost estimate ceiling for comprehensive scenarios** (Finding A6). Widen the top-line range to $0.40-$6.00 with a note that the top applies to comprehensive reasoning with multi-year longitudinal context, or keep the existing range and add a worst-case note of $5-$8 per run.

9. **Close the LOW polish items** (N1, N2, V1, V2, V3). Add `execute-api` conditional endpoint and CloudWatch monitoring endpoint to the VPC row; resolve or accept the HTML-comment TODOs (HealthBench verification is the most pressing); update the sample eGFR value to match CKD-EPI 2021 (or add a disclaimer note); no action required for V3.

---

## Notes for Editor

- Finding A1 is a recurring architecture-safety issue that has now appeared in Recipes 2.6, 2.7, and 2.10, with the fix template demonstrated in Recipe 2.8. For a chapter whose capstone is multi-modal clinical reasoning, this specific flaw leaving the diagram and orchestration ambiguous is the highest-stakes issue in the chapter. The three-part fix (diagram, prose, pseudocode) should be applied in one editorial pass and coordinated with the Python companion's code-review Finding 1 so the two files agree.
- The recurring input-side Guardrails pattern (S2 here, S2 in 2.7 and 2.8) and the recurring trigger-idempotency pattern (A3 here; A3 in 2.8; similar in 2.4 through 2.7) have both now passed "repeat observation across multiple recipes" threshold. A Chapter 2 shared appendix on trigger idempotency and a shared Guardrails-policy-configuration checklist would eliminate the per-recipe recurrence and are the most effective next step. Each recipe's specifics can reference the appendix rather than repeat the pattern.
- The PHI minimization pattern (S1 here, S1 in 2.7 and 2.8) is a third recurring Chapter 2 pattern that is close to "shared appendix" worthiness. Three recipes with the same finding, always in the Bedrock prompt construction step, suggests the cookbook's teaching on PHI minimization inside the BAA boundary should be lifted once and referenced per recipe.
- No bracket-style visible TODO markers in the recipe. Five HTML-comment TODOs, all in Related Recipes or Additional Resources and all forward-placeholder. This is the cleanest TODO posture of any Chapter 2 recipe and is the right template for subsequent recipes.
- No em dashes. Direct U+2014 / U+2013 character check: zero matches. The recipe maintains the no-em-dash discipline through approximately 1600 lines without a lapse. This is the benchmark for subsequent recipes.
- No fake Bedrock model IDs in pseudocode. `REASONING_MODEL_ID`, `SMALL_MODEL_ID`, and `EMBEDDING_MODEL_ID` as placeholders with family-name comments is the right pattern and is the template for subsequent recipes. The Python companion pins versioned IDs, which is the correct split. The Chapter 2 editorial sweep recommended in Recipe 2.8's review (grep for `anthropic\.` and `amazon\.titan` string literals in pseudocode) should confirm that this recipe is clean; preliminary grep confirms no literal Bedrock model IDs in the pseudocode.
- The "Honest Take" and the closing personal note ("Build like it matters.") are the voice at its strongest and should be preserved verbatim in any editorial pass. Same for "The Failure Modes, Specific to Multi-Modal" taxonomy.
- The regulatory subsection ("Regulatory Posture, for Real This Time") is the most substantive regulatory framing in the book so far and should be the template for any subsequent recipe that touches FDA-regulated territory.
- The recipe's length (~1600 lines) is appropriate for the chapter capstone. The verbosity is earned through teaching density rather than filler, and shortening would lose substance. Recommend no length reduction in editorial pass.
- The sample JSON output in Expected Results is the clearest single artifact in the chapter for illustrating what a multi-modal reasoning output looks like to a clinician. The HTML-comment disclaimer is correctly placed. V2's eGFR arithmetic polish is the only content change worth making.
- Cross-recipe references (Related Recipes section) are voice-appropriate and linked to Recipes 2.5-2.9 with concise descriptions. The forward-looking references to Chapter 7/9/12/13 recipes are honest placeholders and should not be resolved with speculative recipe numbers before those chapters are drafted.
- The corresponding code review for the Python companion (reviews/chapter02.10-code-review.md) passed with two WARNINGs; Finding 1 (auto-deliver `REVIEW_REQUIRED`) is the Python-side instance of this review's A1, and Finding 2 (duplicate `_collect_all_citations`) is a Python-file-scope bug unrelated to the main recipe. The A1 fix in the main recipe should be coordinated with the code-review Finding 1 fix in the Python companion.
