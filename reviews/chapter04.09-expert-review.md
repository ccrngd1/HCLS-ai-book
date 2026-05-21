# Expert Review: Recipe 4.9 - Personalized Care Plan Generation

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-21
**Recipe file:** `chapter04.09-personalized-care-plan-generation.md`

---

## Overall Assessment

This is the synthesis recipe of Chapter 4. It correctly graduates the per-decision pattern from 4.5 through 4.8 (one channel, one piece of content, one provider, one program, one intervention, one care-gap, one enrollment, one treatment) into a multi-actor, multi-condition, multi-horizon orchestration whose unit of output is a structured care plan and whose unit of consumption is a patient living with multiple chronic conditions for the next several months. The Linda vignette is the strongest opening in Chapter 4 by content density: 67yo with type 2 diabetes (A1c 8.4 on metformin and a GLP-1), HFrEF (EF 38, on guideline-directed medical therapy), CKD 3b (eGFR 39, declining), depression managed by the PCP since her husband died two years ago, mild cognitive impairment, knee osteoarthritis on topical NSAIDs because the cardiologist asked her to stay off oral, controlled hypertension, an overdue colonoscopy, second-floor walk-up in a transit-poor neighborhood, six prescriptions, four specialists, monthly care manager check-in, and a recent CHF admission likely triggered by a missed diuretic dose. The closing observation that her current care plan is "a document, not a plan" frames the recipe's central thesis exactly and earns the reader's trust before the methodology starts.

The Technology section is the chapter's clearest articulation of structured care plans as a directed graph of goals, actions, and owners with horizons, dependencies, and accountability metadata. The HL7 FHIR `CarePlan` / `Goal` / `Task` / `ServiceRequest` mapping is correctly named as the standard structured representation. The multi-condition reconciliation problem (drug-drug, drug-disease, care-gap conflict, therapeutic-burden weighting via the Cumulative Complexity Model, goals-of-care alignment, cohort-stratified appropriateness, conflict-resolution defaults) is the chapter's most thorough reconciliation framework. The personalization section's "denser than any prior recipe" framing (stated preferences, implied preferences, social determinants, clinical complexity and trajectory, cognitive and functional status, family and caregiver involvement, cultural and faith context) earns its length. The "LLMs as Load-Bearing, with Strict Constraints" subsection draws the sharpest line in the chapter on what the LLM does and does not do: sequencing, drafting goal statements, tailoring instructions, assembling narrative; *not* introducing recommendations, *not* changing priority weights, *not* changing clinical content of action instructions, *not* selecting among comparator treatments, *not* generating prognostic statements beyond approved templates, *not* producing recommendation language for treatments where evidence does not support it. The "structured-then-narrative direction" is operationalized as the architectural primitive that makes the recipe defensible.

The seven-component architecture (clinical content, inputs aggregation, goal derivation, action assembly and reconciliation, plan finalization, narrative generation and validation, review/delivery/activation, feedback/adaptation/evaluation) is the right shape for the problem. The clinical-content layer as governance-not-engineering framing extends the catalog pattern from 4.4 through 4.8 to a richer artifact (goal templates with horizon/measurable_outcome/priority_weight/evidence_level/cohort_overrides; action templates with owner_role/duration/due_date_logic/success_criteria/fallback_chain/dependencies/burden_score/contraindications). The action-assembly-and-reconciliation layer is the chapter's most operationally rigorous synthesis pipeline: contraindication filtering with deprescribing-as-action surfacing, burden estimation with patient-specific threshold and prioritization compression, capacity reconciliation with substitution and deferral, schedule reconciliation with sequencing. Each reconciliation decision is logged with provenance for clinician review. The narrative generation layer with three audience-specific outputs (clinician-facing, patient-facing, care-team-internal disagreement) and a four-layer validator (schema/length, fact grounding, prohibited-language patterns, required content) with a respectable templated fallback is the chapter's most defensive LLM-output path; the Honest Take's "a clean templated narrative is better than a polished LLM narrative that the validator was uncertain about" is the right posture and is operationalized in the architecture.

The Honest Take is, by a clear margin, the chapter's strongest. Eight observations stand out: (1) "what most care plan generators ship is a document. The document goes into the EHR. The document is opened occasionally. The document is updated rarely. The document does not, in any honest accounting, change what happens to the patient" — the chapter's most pointed framing of why this recipe matters; (2) the LLM-as-structural-assembly-engine trap diagnosed precisely ("a team that hands the LLM the patient's record, the guidelines, and the prompt 'generate a personalized care plan' will get a plausible-looking output that is not auditable, not reproducible, and not safe to act on"); (3) goals-of-care alignment as "not glamorous work but the work that makes the plan reflect the patient rather than reflect the algorithm's best guess about a typical patient"; (4) burden estimation explicitly called out as where naive scores systematically deprioritize "the wrong actions for the patients with the least support"; (5) "the clinical-content library, the multi-condition reconciliation rules, the cohort overrides, the burden scoring, the activation integrations, the channel integrations, the consent posture, the regulatory analysis: each is multi-month work. The ML and the LLM are the easier parts"; (6) the templated-fallback-as-respectable-artifact discipline explicitly framed as defensible against the polished-but-uncertain LLM narrative; (7) cross-recipe event-flow resilience as a pre-launch investment, not a retrofit; (8) the closing call-to-action that the system is "a co-author of the patient's care" with the corresponding seriousness expectation. The closing "the system that gets these right does not produce a wow; it produces a quiet 'this works for me' that, scaled across thousands of patients, is the version of healthcare personalization the chapter has been pointing at all along" is the strongest closing in Chapter 4.

That said, four correctness gaps need attention before publication, and the medium and low items round out the review. (1) `activate_plan` and `record_feedback` rely on commented-but-not-coded identity-boundary checks; the activation pseudocode comments "validate the calling clinician has a treatment relationship to plan.patient_id; validate that approved_action_ids is a subset of plan.final_actions" but the actual pseudocode that follows the comment performs neither check, and `record_feedback` has no identity-boundary discussion at all even though feedback can mark actions failed and trigger plan revision. The chapter pattern from 4.4-4.8 elevates here because the artifact being mutated (plan-records, plan-action-records, plan-feedback-records) is, by the recipe's own framing, "clinical-record-equivalent PHI." (2) `compute_burden_threshold(plan_input_record)` is referenced as "patient-specific: a function of functional status, cognitive status, social support, and stated preferences" but the actual computation is undefined in the pseudocode. The Honest Take explicitly warns that "naive burden scoring (count of actions, sum of touch points)" produces compression decisions that "quietly disadvantage the patients who most need a thoughtful plan." Without an explicit threshold-derivation policy in the architecture, implementation will hand-tune constants — which is exactly the failure mode the recipe diagnoses. (3) `COHORT_DISPARITY_ALERT_THRESHOLD` and the equity-monitoring metric definitions (plan ambition parity, plan complexity parity, action assignment parity, outcome trajectory parity) are referenced in pseudocode and described as "non-negotiable" in prose, but the operational thresholds, the per-axis aggregation policy, and the chronic-suppression-as-fairness-signal pattern are not specified. The Obermeyer scenario the recipe explicitly cites depends on these thresholds being calibrated; leaving them implementation-defined silences the alert that catches the disparate-impact case. (4) `evaluate_feedback_for_revision(plan_id, feedback_record)` returns `revision_signal.should_revise` with no specification of what triggers revision; the production-gaps section names trigger calibration as ongoing work, but the architecture should at minimum specify the always-trigger events (adverse events, hospitalizations, new diagnoses), the threshold-trigger events (weight gain above threshold persistent over time), and the suppress-trigger events (single missed dose). The Honest Take warns that "too-sensitive triggers cause plan churn that erodes the plan's stability" and "too-insensitive triggers leave the plan stale through changes that should drive revision"; without architectural framing, the calibration is left to whoever implements the pseudocode first.

Eleven chapter-wide patterns repeat (tracking-ID privacy, validator four-layer specification, SDOH cohort PHI promotion, IAM ARN scoping, `0.0.0.0/0` egress, identity-boundary checks, governance-task SLA, model-promotion path, cross-recipe orchestration, DLQ coverage, EHR/portal integration credential posture). Several are explicitly TODO'd in the recipe text; this review carries them forward at MEDIUM or LOW severity reflecting the chapter editor's eventual consolidation responsibility.

Voice is excellent. Em dash count: 0 (verified). En dash count: 0 (verified). 70/30 vendor balance is maintained. Linda is the consistent named patient throughout; her clinical scenario is internally consistent and clinically accurate (HFrEF with EF 38 on GDMT including the SGLT2-class addition implied by the GLP-1 mention is appropriate for current ADA/AHA guidelines; CKD 3b eGFR 39 with declining trajectory is a clinically authentic concern; metformin contraindication at eGFR < 30 is correctly framed in the deprescribing context; topical NSAIDs avoiding oral NSAIDs in CHF is correct cardiac advice; A1c 8.4 with depression and mild cognitive impairment is exactly the multi-morbid profile the recipe targets). The illustrative plan record JSON is internally consistent with Linda's profile. The "third-party EHR/portal/channel integration is the longest-pole project" framing is operationally honest. The Variations and Extensions section (multi-language patient narratives, caregiver-facing narrative, condition-specific deep-dives, goals-of-care prompts, outcomes-based effectiveness reporting, federated benchmarking, patient-driven plan editing, real-time RPM-driven adjustments, preventive-health variants, care-transition variants) is the chapter's most ambitious; the framing of each as "what you'd build at higher sophistication levels" preserves the recipe's discipline about scope.

Priority breakdown: 0 critical, 4 high, 11 medium, 5 low. **The verdict is FAIL** because 4 HIGH findings exceed the > 3 = FAIL threshold. The four HIGH findings are correctness gaps with localized fixes; most of them surface in well-specified prose elsewhere in the recipe and require the pseudocode to be brought into alignment with the prose.

---

## Stage 1: Independent Expert Reviews

## Security Expert Review

### What's Done Well

- BAA called out explicitly with HIPAA-eligibility TODOs for Bedrock, HealthLake, Pinpoint per channel, and any EHR integration components. Continues the chapter pattern of not pretending the eligibility list is static.
- Customer-managed KMS keys for every PHI store with explicit framing of `plan-records`, `plan-narratives`, and `plan-feedback-records` as "highly inferential PHI" and "clinical-record-equivalent." The framing is correctly the sharpest in Chapter 4: a row joining patient_id with the structured plan implicitly reveals the active condition list, the goals-of-care posture, the medication regimen, the social context, and the care-team assignments. The "narrative text stored in DynamoDB is PHI; treat with full clinical-record encryption posture" framing is correct.
- CloudTrail data events on `goal-templates`, `action-templates`, `plan-records`, `plan-narratives`, `plan-action-records`, `plan-feedback-records`, plus the S3 buckets containing source feeds, plan archives, and review outputs. Plan-review API invocations logged at API Gateway and Lambda layers; activations logged through the activation-dispatcher Lambda. The "audit posture for care-plan artifacts approaches clinical-record audit standards" framing is the recipe-specific sharpening that distinguishes 4.9 from prior recipes.
- Bedrock paragraph confirms prompts and completions are not used to train foundation models. Continues the chapter pattern.
- The validator's four conceptual layers (schema and length, fact grounding, prohibited-language patterns, required content) are named with audience-specific extensions (the patient-facing list is broader than the clinician-facing list, including reading-level enforcement; the disagreement narrative requires an escalation path; the clinician narrative requires change-since-prior-plan callouts).
- De-identification at the LLM boundary is implied by the structured-then-narrative direction; the LLM receives the structured plan and renders narrative on top, so the prompt context is the structured plan rather than raw clinical text.
- Patient consent for data use is named in production-gaps with the correct multi-layer framing (clinical-care use, ongoing data use, plan-generation participation), with the right discipline that "the institution's existing consent infrastructure typically does not have all of these granularities; expect to extend it."
- Regulatory posture is set early with explicit framing of the clinician-mediated default versus the direct-to-patient delivery as a regulatory-tightening case.

### Finding S1: `activate_plan` and `record_feedback` Comment-But-Don't-Code Identity-Boundary Checks

- **Severity:** HIGH
- **Expert:** Security (PHI integrity boundary, authorization)
- **Location:** Step 6 pseudocode, the `activate_plan(plan_id, activation_payload)` function: the comment block reads
  ```
  // Identity-boundary checks: validate the calling clinician has a
  // treatment relationship to plan.patient_id; validate that
  // approved_action_ids is a subset of plan.final_actions; reject
  // attempts to approve actions not in the structured plan.
  ```
  but the pseudocode that follows the comment performs neither check. The `record_feedback(plan_id, feedback_payload)` function has no identity-boundary discussion at all.
- **Problem:** The chapter pattern from 4.4 through 4.8 enforces an identity-boundary check on consumers that mutate clinical state from inbound payloads. Recipe 4.9 acknowledges the pattern in a comment for `activate_plan` and skips it entirely for `record_feedback`. The consequences here are sharper than in any prior recipe because the artifact being mutated is, by the recipe's own framing, "clinical-record-equivalent PHI":

  1. **`activate_plan` is the most security-sensitive write path in Chapter 4.** It receives an `activation_payload` that includes `approving_clinician_id`, `approved_action_ids`, `clinician_edits`, `patient_acknowledgment`, and `teach_back_results` over the API Gateway path, then dispatches actions to the e-prescribing system, the scheduling system, the program registry, and the patient-portal channel. An `activation_payload` arriving with mismatched metadata (a clinician submits an `approving_clinician_id` who has no treatment relationship to the patient; an authorization-bypass attempt that submits a `plan_id` the calling clinician should not have access to; an `approved_action_ids` list that contains an action_id not present in the plan's `final_actions`) would silently dispatch real-world actions to real-world systems on behalf of the wrong patient. The downstream blast radius is the e-prescribing system (a misdispatched medication change), the scheduling system (a misdispatched appointment), and the program registry (a misdispatched enrollment), each of which has its own audit trail and its own remediation cost.

  2. **`record_feedback` writes to `plan-feedback-records` and can update action status to `failed`, which can trigger plan revision via `evaluate_feedback_for_revision`.** A misrouted feedback event (a system-emitted `action_completed` event for the wrong patient, a malformed PROM ingest, a replayed event from a reprocessing job) would mark actions complete or failed against the wrong plan, propagate the corruption into the action-status table, and potentially trigger a plan-revision cycle on a stale or wrong-patient signal. The trigger calibration concern in Finding A3 compounds with this: an unverified feedback event that triggers revision burns clinician review time on a phantom signal.

  3. **The Cures Act CDS exemption argument depends on the identity boundary.** The exemption requires that the clinician be able to "independently review the basis of the recommendation" and that the basis be associated with the right patient. A system that lets a clinician's activation attach to the wrong patient's plan or that lets feedback attach to the wrong plan-action-record breaks the exemption argument. Recipe 4.8's review elevated this concern to HIGH on the same regulatory ground; 4.9 inherits the same regulatory posture.

  4. **The Python code review (Finding 1) flagged a related but narrower issue in 4.9's narrative validator (false-positive rejection of valid grounded references), and observed that the activation function does perform the `approved_action_ids` subset check; the clinician-treatment-relationship check is what's missing in both architecture and Python.** The architectural fix (specify the check in pseudocode) and the implementation fix (add it to the Python) need to land together.

- **Fix:** Add the identity check in pseudocode immediately after the plan lookup in `activate_plan`:

  ```
  plan = DynamoDB.GetItem("plan-records", plan_id)
  IF plan is null:
      LOG("plan-records lookup failed", plan_id=plan_id)
      RETURN error("plan_not_found")

  // Validate the calling clinician's authorization.
  IF NOT clinician_has_treatment_relationship(activation_payload.approving_clinician_id,
                                                 plan.patient_id):
      LOG("activation_payload approving_clinician_id without treatment relationship",
          clinician = activation_payload.approving_clinician_id,
          patient   = plan.patient_id)
      emit_metric("plan_activation_authorization_violation", value = 1)
      RETURN error("clinician_not_authorized")

  // Validate that every approved action is in the structured plan.
  valid_action_ids = [a.action_id FOR a in plan.final_actions]
  invalid = [aid FOR aid in activation_payload.approved_action_ids
              IF aid NOT IN valid_action_ids]
  IF len(invalid) > 0:
      LOG("activation_payload approved_action_ids contains invalid IDs",
          invalid = invalid, plan_id = plan_id)
      emit_metric("plan_activation_action_mismatch", value = 1)
      RETURN error("action_ids_not_in_plan")

  // Validate plan_id consistency in the payload.
  IF activation_payload.plan_id is not null AND
     activation_payload.plan_id != plan_id:
      LOG("activation_payload plan_id mismatch; dropping",
          submitted = activation_payload.plan_id, stored = plan_id)
      emit_metric("plan_activation_plan_id_mismatch", value = 1)
      RETURN error("plan_id_mismatch")
  ```

  Add an analogous check in `record_feedback`: validate that the feedback's `target_action_id` (when present) belongs to the plan referenced by `plan_id`; validate that the feedback's `source` is consistent with the kind (a `clinician`-sourced `action_completed` event must include a clinician_id with treatment relationship; a `system`-sourced event must come from an authenticated upstream pipeline); validate that the feedback is not a replay of an already-recorded feedback event (idempotency on `(plan_id, feedback_kind, target_action_id, recorded_at)` deduplicates replayed feedback from reprocessing jobs). Reject mismatches and emit metrics.

  Reference Recipe 4.4 Finding S1, 4.5 Finding S1, 4.6 Finding S1, 4.7 Finding S1, 4.8 Finding S1 as the chapter-wide pattern; the chapter editor should consolidate identity-check guidance into a chapter-4 preface that all recipes reference. For 4.9 specifically, the clinical-record-equivalent posture earns the HIGH severity rather than the MEDIUM of earlier recipes.

### Finding S2: Plan-ID, Narrative-ID, Plan-Action-Record-ID Tracking-ID Privacy (Chapter-Wide Pattern; Already TODO'd)

- **Severity:** MEDIUM
- **Expert:** Security (PHI minimization)
- **Location:** Sample plan record `"plan_id": "plan-2026-04-22-pat-007842-v07"`; sample narrative `"narrative_id": "narr-2026-04-22-pat-007842-patient"`; existing TODO in the production-gaps section: *"replace the string-concatenation plan_id, narrative_id, plan_action_record_id with opaque, non-reversible identifiers (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plan-version-and-patient-id-in-identifier patterns are PHI leakage in URLs, logs, and event payloads."*
- **Problem:** Same finding as 4.4 Finding 2, 4.5 Finding S2, 4.6 Finding S2, 4.7 Finding S2, 4.8 Finding S2. The recipe acknowledges the gap with a TODO that mirrors the chapter-wide fix language.

  Care-plan-specific sharpening: the plan_id is carried in the EHR integration via SMART on FHIR, in the patient portal links, in mailed-letter print runs, and in the activation-dispatcher payloads to the e-prescribing and scheduling systems. The plan_version embedded in `v07` reveals that this is the patient's seventh plan revision, which is itself inferential about clinical instability. The narrative_id with `patient` audience suffix reveals that this is the patient-facing copy of a clinical document. The combination is more sensitive than any prior recipe's identifier because the artifact is, again, clinical-record-equivalent.

- **Fix:** Same as 4.4-4.8. Replace string-concatenation IDs with opaque UUID or HMAC-SHA256 over the composite with a per-environment secret. Update the Expected Results sample identifiers accordingly. The Python code review's positive note that all `_make_*_id` helpers already use opaque UUID-based identifiers is good; the architectural pseudocode should match the Python rather than the Python being silently more careful than the recipe text.

### Finding S3: Validator Four-Layer Specification Underspecified for Patient-Facing Reading-Level and Language Enforcement

- **Severity:** MEDIUM
- **Expert:** Security (regulatory, hallucination guardrails, patient-experience equity)
- **Location:** Step 5 pseudocode `finalize_narrative` describes four validator layers in a comment block but does not specify them at the level the chapter has converged on (4.4 Finding 3, 4.5 Finding S3, 4.6 Finding S3 / A7, 4.7 Finding S3, 4.8 Finding S3). The Python code review's Finding 6 observes that the patient validator's reading-level and language-enforcement promises are not implemented in code despite the prompt explicitly stating: *"Match the reading-level target ({reading_level}). Use short sentences. Use everyday words instead of clinical jargon. Output language: {language}. If language != 'en', produce the narrative in that language."*
- **Problem:** Care-plan-specific sharpening of the chapter-wide validator gap:

  1. **Reading-level enforcement is non-trivial in this recipe and named in the Expected Results JSON.** The sample patient-facing narrative includes:
     ```json
     "reading_level_target": "grade_6",
     "reading_level_measured": "grade_6.2"
     ```
     which implies a measurement that the Python validator does not perform. A reader looking at the Expected Results and the Python validator code is given two contradictory descriptions of what the system measures. Recipe 4.2 (Patient Education Content Matching) establishes the reading-level pattern; Recipe 4.9's patient-facing narrative is the load-bearing application of that pattern, and the validator should enforce it explicitly via Flesch-Kincaid scoring (e.g., `textstat`) or an equivalent grade-level metric.

  2. **Language enforcement is a fairness primitive.** A patient who has stated Spanish as their preferred language and receives an English narrative is failed by the system in a way that disproportionately affects non-English-preferring patients (a cohort fairness failure); the validator should detect language mismatches by comparing the configured language against language-detected output (e.g., `langdetect`). For multi-language deployments, the validator should also enforce that the language-specific reading-level target is met by a language-specific scoring algorithm (Flesch-Huerta-Macuso scoring for Spanish, etc.).

  3. **Fact grounding for care-plan narratives is broader than for the engagement-program briefings of 4.4-4.7.** The clinician-facing narrative is instructed to surface `care_team_attention` items (suppressed actions, deprescribing candidates, capacity-substitution decisions) that are not in `final_actions` but are in the reconciliation_record; the Python code review's Finding 1 documents that the current validator rejects valid grounded references to these elements. The architectural fix is to specify in pseudocode that the fact-grounding allowlist is the union of `final_actions`, `to_be_assigned`, `suppressed_actions` from reconciliation_record, `deprescribing_added` from reconciliation_record, the goal_set, and a clinical-codes allowlist (`chf_severe`, `egfr_under_45`, etc.) maintained alongside the templates.

  4. **Required-content layer is audience-specific and the asymmetry should be specified.** The patient-facing narrative requires shared-decision framing, contact-for-questions, and the next-action callout; the clinician-facing narrative requires change-since-prior-plan, care-team-attention, and a prose paragraph; the disagreement narrative requires the conflict description, candidate resolutions, and the recommended escalation path. Each is specified in prose; specify in pseudocode.

  5. **The templated fallback's reading-level discipline must match the LLM-generated discipline.** The templated fallback should not produce content that scores at grade 12 when the target is grade 6; the Python code review's Finding 6 implies the templated path may quietly fail the same enforcement the validator demands of the LLM path. The architecture should specify that templated fallback content is itself reading-level-controlled at template-authoring time and enforced at render time.

- **Fix:** Specify the four layers inline in the Step 5 pseudocode:

  ```
  FUNCTION validate_narrative(parsed, observed_context, audience):
      // Layer 1: schema and length
      // Required fields per audience-specific schema; length caps per
      // section. Required: every audience needs headline + structured
      // body. Patient: this_week, this_month, this_quarter, ongoing,
      // what_changed, questions, contact. Clinician: headline,
      // what_changed_since_v{N-1}, care_team_attention, narrative_paragraph.
      // Disagreement: conflict_description, candidate_resolutions,
      // escalation_path. Length caps: headline <= 200 chars; body
      // bullet items <= 400 chars each.

      // Layer 2: fact grounding
      // Allowlists:
      //   valid_action_ids = final_actions
      //                    ∪ to_be_assigned
      //                    ∪ reconciliation_record.suppressed_actions
      //                    ∪ reconciliation_record.deprescribing_added
      //   valid_goal_ids   = goal_set
      //   valid_clinical_codes = catalog-maintained set including
      //     contraindication codes (chf_severe, egfr_under_45, etc.)
      //     and clinical-state tokens.
      // Every id-shaped token in the narrative must appear in the
      // union of the three allowlists. Hallucinated tokens REJECT.

      // Layer 3: prohibited-language patterns
      // Audience-shared: no "guaranteed", no "100 percent effective",
      //   no "definitely will", no recommendation language for
      //   treatments not in the structured plan.
      // Patient-specific extensions: no clinical jargon ("contraindication",
      //   "iatrogenic", "idiopathic"); no probabilistic point estimates
      //   as percentages; no "you will [outcome]" framing (use
      //   cohort-based phrasing).
      // Clinician-specific extensions: no recommendation language that
      //   contradicts the structured action set (the LLM does not
      //   override what the deterministic logic decided).

      // Layer 4: required content
      // Patient-facing:
      //   - shared-decision framing present ("if anything in this plan
      //     does not work for you, please call ...")
      //   - contact information present (care_manager_name, phone,
      //     portal_link)
      //   - reading-level compliance: Flesch-Kincaid grade level
      //     <= reading_level_target + 0.5; computed by textstat or
      //     equivalent. Language-specific scoring algorithm for non-
      //     English narratives.
      //   - language compliance: detected language matches configured
      //     language (langdetect or equivalent).
      // Clinician-facing:
      //   - what_changed_since_v{N-1} present
      //   - care_team_attention items match reconciliation_record
      //   - narrative_paragraph references at least one structured
      //     action and one structured goal
      // Disagreement narrative:
      //   - escalation_path present with a documented role
      //   - candidate_resolutions count >= 2

      // Failure handling:
      // First failure: regenerate with strict_mode = true and the
      //   validator's per-layer failure summary in the prompt.
      // Second failure: fall back to render_templated_narrative.
      // Templated narrative: deterministic; reading-level-controlled
      //   at template-authoring time; always passes validation.
  ```

  Reference Recipe 4.2 for the reading-level pattern; reference 4.4-4.8 for the per-layer template. The chapter editor should consolidate the validator pattern into a chapter-4 preface; for 4.9 specifically, the reading-level and language-enforcement layers are the recipe's distinctive additions and belong in main text.

### Finding S4: SDOH-Cohort PHI Sensitivity TODO Should Be Promoted to Main Privacy Paragraph (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Implicit in `cohort_features` carried in CloudWatch metric dimensions; chapter-wide pattern from 4.4-4.8.
- **Problem:** Same finding as 4.4-4.8. Promote into main privacy paragraph. For 4.9, the per-cohort fairness instrumentation is most-developed (plan ambition parity, plan complexity parity, action assignment parity, outcome trajectory parity), so carrying unnecessary cohort attributes amplifies the disclosure risk.
- **Fix:** Promote the TODO into the main paragraph. Reference 4.4-4.8 chapter pattern.

### Finding S5: IAM "Never `*`" Stated Without Scoped ARN Examples (Chapter-Wide Pattern, Already TODO'd)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites IAM Permissions row.
- **Problem:** Same finding as 4.1-4.8. Already TODO'd.
- **Fix:** Inline one or two scoped resource ARN examples for the highest-stakes actions (`bedrock:InvokeModel` on the per-audience model ARNs, `dynamodb:UpdateItem` on `plan-records` and `plan-action-records`, `pinpoint:SendMessages` on the patient-facing application). Or consolidate into the chapter-4 preface.

---

## Architecture Expert Review

### What's Done Well

- The seven-component architecture (clinical content, inputs aggregation, goal derivation, action assembly and reconciliation, plan finalization, narrative generation and validation, review/delivery/activation, feedback/adaptation/evaluation) is the right shape for the problem. The framing of clinical content as governance-not-engineering ("templates owned by engineering and updated as part of feature work" diagnosed as the canonical failure mode) is the operational discipline the recipe earns its right to make.
- The directed-graph framing of the structured plan (goals, actions, owners with horizons, dependencies, accountability metadata) maps cleanly to FHIR `CarePlan` / `Goal` / `Task` / `ServiceRequest`, with the recipe explicitly acknowledging that "the structured representation is well-trodden ground; what differs across implementations is the richness of the graph and how dynamically it is maintained." HealthLake as the FHIR-native home for the plan is the natural choice; the portability-across-care-settings argument is the right framing for why FHIR-native matters.
- Multi-condition reconciliation as a multi-stage pipeline (drug-drug + drug-disease + drug-allergy interaction filtering, deprescribing surfacing, burden estimation with patient-specific threshold, prioritization compression, capacity reconciliation, schedule reconciliation) is the chapter's most thorough reconciliation framework. Each stage has explicit failure-mode framing in prose (the Honest Take's "naive burden score systematically deprioritizes the wrong actions for the patients with the least support" is the canonical example). Each reconciliation decision is logged in `reconciliation_record` with provenance for clinician review.
- The structured-then-narrative direction is enforced architecturally (Steps 1-4 build the plan record deterministically; Step 5 only renders narrative on top). The Honest Take's "the LLM produces words about decisions that the structured logic has already made. That sounds like a small distinction. It is the recipe" is operationalized in the architecture rather than left as a slogan.
- Three audience-specific narratives (clinician-facing, patient-facing, care-team-internal disagreement) with audience-specific validators and a respectable templated fallback. The "templated narrative is better than a polished LLM narrative the validator was uncertain about" stance from the Honest Take is the right defensive posture for the chapter's most LLM-dependent recipe.
- Cross-recipe orchestration explicitly addressed: every prior recipe in Chapter 4 contributes signals (channel preferences from 4.1, content matches from 4.2, provider relationships from 4.3, wellness candidates from 4.4, adherence interventions from 4.5, care gaps from 4.6, care management enrollment from 4.7, treatment-response predictions from 4.8). The independent-fetch-with-defaults policy ("missing signals are recorded as such rather than failing the whole aggregation") is the right resilience pattern; the recipe correctly notes that "a plan generator that requires all eight upstream recipes to be live would have an availability problem."
- The activation layer's multi-system dispatch (e-prescribing, scheduling, program registry, patient-portal, care-management) is correctly framed as the operational integration that distinguishes "shipping a document" from "changing what happens to the patient." The "Where it struggles" entry on multi-actor coordination is operationally honest.
- Equity instrumentation explicitly named as "non-negotiable": plan ambition parity, plan complexity parity, action assignment parity, outcome trajectory parity. The Obermeyer pattern is correctly extended to care-plan generation: "a care plan generation system that aims its plans at what the model thinks the patient can do, where what-the-patient-can-do is conflated with what-the-patient-has-historically-had-access-to, will produce systematically less ambitious plans for patients in under-resourced cohorts."
- The "this is a Complex recipe" framing earns its position in the chapter: prior recipes pick one thing; 4.9 picks all of them, simultaneously, for the same patient, and reconciles. The "LLM stops being a packaging layer and starts being structurally load-bearing" framing is the chapter's most pointed articulation of why discipline matters here even more than in prior recipes.

### Finding A1: `compute_burden_threshold` Is Referenced as Patient-Specific but the Computation Is Undefined; Burden Compression Is Where the Recipe's Most-Vulnerable Patients Are Disadvantaged

- **Severity:** HIGH
- **Expert:** Architecture (correctness, equity, the recipe's central concern in the Honest Take)
- **Location:** Step 3 pseudocode `assemble_and_reconcile_actions`:
  ```
  burden_threshold = compute_burden_threshold(plan_input_record)
      // patient-specific: a function of functional status, cognitive
      // status, social support, and stated preferences. The
      // threshold for Linda is lower than the threshold for a
      // 45-year-old with the same conditions and full social
      // support.
  IF cumulative_burden > burden_threshold:
      compression_decisions = compress_for_burden(...)
  ```
  The function is referenced in pseudocode and described in prose; the actual derivation of the threshold is undefined. `compress_for_burden` is similarly unspecified.
- **Problem:** Burden compression is the architectural primitive that decides which actions get dropped or deferred when the candidate action set exceeds the patient's feasible total. The Honest Take frames this as the central concern: *"A naive burden score (count of actions, sum of touch points) misses that some actions are higher-burden in a specific patient's life (the colonoscopy is high-burden for a patient without transportation; low-burden for one with), and the compression decisions made on a naive score will systematically defer the wrong actions for the patients with the least support."* The pseudocode then specifies the framework but not the policy:

  1. **The "patient-specific threshold" is the difference between equitable and inequitable compression.** A threshold computed as `base - functional_status_penalty - cognitive_penalty - social_support_penalty - stated_preferences_penalty` produces lower thresholds for patients with frailty, cognitive impairment, low social support, or stated low capacity. The patients with the lowest thresholds are exactly the patients whose plans get compressed most aggressively. Without an explicit derivation policy in the architecture, implementation will hand-tune constants — and the constants will be tuned by whoever ships the system, not by the clinical-content team or the equity-review committee.

  2. **The compression decision policy is itself an equity question.** When the cumulative burden exceeds the threshold, the system drops or defers some actions. The default ("drop the lowest-priority-weight actions") is not equity-neutral: actions for goals the patient has explicitly elected (e.g., advance care planning) may be lower-priority-weight than condition-driven goals (e.g., A1c control), but dropping them undermines the goals-of-care alignment that earlier in the recipe is correctly framed as the discipline that "makes the plan reflect the patient rather than reflect the algorithm's best guess." A policy of "drop quality-program-linked goals last" is a different equity statement than "drop patient-stated-preference-linked goals last." The architecture should specify the policy or explicitly defer it to the cross-functional review committee with documented framing.

  3. **The Cumulative Complexity Model named in The Technology section is a calibration framework, not a constant.** The recipe correctly cites May, Montori, and Mair, and the production-gaps section notes that "Burden scoring requires a calibrated model (the Treatment Burden Questionnaire, the Patient Experience with Treatment and Self-Management measure, or an internally-validated equivalent) rather than a hand-tuned constant." That production-gap discipline should propagate into the architecture: specify that the threshold and the per-action burden score are calibrated artifacts maintained by the clinical-content team, not implementation constants.

  4. **The Python code review (positive note) observed that `_compute_burden_threshold` correctly weights frailty, cognitive impairment, social support, and transportation access in the demo.** The Python implements a reasonable starting point; the architecture should specify the policy framework so a production implementation does not silently regress to "count of actions" in a refactor.

- **Fix:** Specify the burden-threshold derivation in pseudocode and the compression-decision policy in prose:

  ```
  FUNCTION compute_burden_threshold(plan_input_record):
      // Baseline threshold (patients with average capacity):
      threshold = BASELINE_BURDEN_THRESHOLD  // catalog-defined; e.g., 12.0

      // Functional status penalty (per ADL/IADL deficit):
      threshold -= FUNCTIONAL_STATUS_WEIGHT *
                    count_deficits(plan_input_record.functional_status)

      // Cognitive impairment penalty (per severity tier):
      threshold -= COGNITIVE_PENALTY[plan_input_record.functional_status.cognitive_status]

      // Social support penalty (per support tier):
      threshold -= SOCIAL_SUPPORT_PENALTY[plan_input_record.sdoh.social_support]

      // SDOH-driven penalties (transportation, food security, financial
      // strain, digital literacy). Each contributes additively because
      // each independently constrains feasible action volume.
      threshold -= sum_sdoh_penalties(plan_input_record.sdoh)

      // Stated-preference adjustment: patients who have explicitly
      // stated low capacity reduce further; patients who have stated
      // they can take on more do not exceed the baseline (the system
      // does not push the patient harder than the baseline allows).
      threshold = min(threshold + stated_capacity_adjustment(plan_input_record),
                       BASELINE_BURDEN_THRESHOLD)

      // Floor: patients in palliative or hospice care have a
      // minimum-burden threshold; the plan focuses on comfort and
      // explicitly elected goals.
      IF plan_input_record.goals_of_care.comfort_focused_flag:
          threshold = min(threshold, COMFORT_FOCUSED_BURDEN_CAP)

      RETURN max(threshold, MINIMUM_THRESHOLD_FLOOR)
  ```

  And specify the compression-decision policy:

  *"Burden compression decisions are policy, not implementation. The chapter-wide default ('drop the lowest-priority-weight actions') is a starting point that the clinical leadership and the equity-review committee must review. Per-pair-or-per-goal overrides may apply: actions linked to patient-stated-preference goals are protected from compression by default; actions linked to quality-program-incentivized goals may or may not be protected (the program may absorb the under-performance signal as the patient's elected outcome). Compression decisions are logged in the reconciliation_record with explicit rationale, and the cohort-stratified plan-quality monitoring (Finding A2) tracks differential compression rates across cohorts. Chronic over-compression in a specific cohort is itself a fairness signal that the equity dashboard surfaces at quarterly committee review."*

  The threshold-and-policy specification belongs in the architecture, not the implementation, because the policy choices have civil-rights implications. Reference the Cumulative Complexity Model and the Treatment Burden Questionnaire as the calibration anchors; reference Recipe 4.8's Finding A4 as the analogous chapter pattern for cohort-fairness threshold specification.

### Finding A2: `COHORT_DISPARITY_ALERT_THRESHOLD` and Equity Metric Definitions Are Referenced but Undefined

- **Severity:** HIGH
- **Expert:** Architecture (fairness, civil-rights implications)
- **Location:** Step 6 pseudocode `run_periodic_plan_review`:
  ```
  FOR each axis, metric in quality_metrics:
      IF metric.disparity >= COHORT_DISPARITY_ALERT_THRESHOLD:
          DynamoDB.PutItem("surveillance-alerts", {...})
  ```
  Plus the architectural prose: *"Plan ambition parity (the plan does not systematically aim lower for some cohorts than others). Plan complexity parity (the plan is not systematically simpler or more burdensome for some cohorts than others). Action assignment parity (some cohorts are not systematically assigned more self-management actions while other cohorts get more clinician-led actions). Outcome trajectory parity (plan-attributable outcome improvements are not concentrated in some cohorts)."*
- **Problem:** The recipe's central fairness instrumentation depends on a threshold and a set of metrics that the pseudocode references without defining. The architecture is silent on:

  1. **What the threshold value should be.** The recipe says the instrumentation is "non-negotiable" but does not specify the operational value at which an alert fires. A threshold set too high silences the alert; a threshold set too low produces alarm fatigue and the alert is ignored. Either failure mode allows disparate impact to continue. Recipe 4.8's review elevated the same gap to HIGH severity (Finding A4) on the same Obermeyer-canonical-concern reasoning; 4.9 inherits the concern and the severity.

  2. **How each metric is computed.** Plan ambition parity could be operationalized as the ratio of the median goal_count per patient between the highest-cohort and lowest-cohort groups, or as the ratio of mean priority_weight, or as the ratio of high-evidence-level goal counts. The choice of operationalization affects what the alert catches. Plan complexity parity could be operationalized as the ratio of total burden_score, the ratio of action count per plan, or the ratio of cross-system activation count. Each operationalization has different sensitivity to compression decisions (Finding A1 above), and the choice should be specified rather than implementation-defined.

  3. **Per-axis aggregation policy.** Cohort axes include language, race/ethnicity self-report, SDOH cohort, age band, primary insurance, primary language. Setting a single chapter-wide threshold may miss axis-specific patterns. The architecture should specify per-axis thresholds at minimum, ideally with the framing that the per-axis threshold is set by the cross-functional equity-review committee.

  4. **Chronic-suppression-as-fairness-signal pattern.** A cohort whose plan-generation volume is structurally low (fewer plans generated, smaller cohort sample size) silences the disparity calculation; the system reports "no signal" when in fact the signal is "this cohort is structurally under-served by the plan-generation pipeline upstream." The architecture should name chronic insufficient-sample as itself a fairness signal that is escalated to the equity committee.

  5. **The Python code review's Finding 8 noted that `_compute_plan_quality_metrics` is a hard-coded stub returning `disparity: 0.24` (one-hundredth below the threshold of 0.25), so the demo never fires an alert.** That the demo's threshold is implementation-defined (`COHORT_DISPARITY_ALERT_THRESHOLD = 0.25`) and that the metric values are stubbed is acceptable for a demo; that the architectural recipe leaves the threshold and metric definitions implementation-defined is not.

- **Fix:** Specify the thresholds and the metric definitions in the pseudocode and the architecture:

  ```
  // Cohort-disparity thresholds (per chapter-wide policy; per-axis-per-
  // metric overrides set by the equity-review committee):
  //   PLAN_AMBITION_DISPARITY_THRESHOLD     = 0.15
  //     // Ratio of median goal-set priority-weight sum, worst-cohort
  //     // versus best-cohort. Above 0.15 triggers alert.
  //   PLAN_COMPLEXITY_DISPARITY_THRESHOLD   = 0.20
  //     // Ratio of median action count or median burden_score, worst-
  //     // cohort versus best-cohort. Above 0.20 triggers alert.
  //   ACTION_ASSIGNMENT_DISPARITY_THRESHOLD = 0.15
  //     // Ratio of the patient-self-management action share, worst-
  //     // cohort versus best-cohort. Above 0.15 indicates one cohort
  //     // is being given more self-management work versus clinician-
  //     // led work.
  //   OUTCOME_TRAJECTORY_DISPARITY_THRESHOLD = 0.10
  //     // Ratio of plan-attributable outcome improvement, tighter
  //     // because outcomes are downstream of plan quality and a
  //     // disparity here signals that earlier-stage parity has not
  //     // closed the equity gap.
  //   MIN_COHORT_SAMPLE = 100 plans per cohort per surveillance window
  //     // Below this, disparity calculation suppressed; chronic
  //     // suppression is itself escalated to equity committee.
  ```

  Add a paragraph to the architecture pattern naming the per-axis-per-metric override mechanism (the equity-review committee documents the threshold per (axis, metric) at deployment), the chronic-suppression-as-fairness-signal pattern, and the relationship to the burden-compression policy in Finding A1 (cohort disparities in plan complexity are downstream of cohort disparities in burden compression, so the two should be analyzed together).

  Reference Obermeyer 2019 as the canonical concern and Recipe 4.8 Finding A4 as the chapter sibling for the threshold-specification pattern.

### Finding A3: `evaluate_feedback_for_revision` Trigger Calibration Is Undefined; the Recipe Names the Failure Modes But Does Not Architect Them

- **Severity:** HIGH
- **Expert:** Architecture (clinical safety, plan-stability vs staleness tradeoff)
- **Location:** Step 6 pseudocode `record_feedback`:
  ```
  revision_signal = evaluate_feedback_for_revision(plan_id, feedback_record)
  IF revision_signal.should_revise:
      EventBridge.PutEvents([{...detail_type: "plan_revision_triggered"...}])
  ```
  The function is referenced; the trigger policy is undefined. Production-gaps acknowledges the gap: *"too-sensitive triggers cause plan churn that erodes the plan's stability and the patient's understanding of it; too-insensitive triggers leave the plan stale through changes that should drive revision. The trigger calibration is operationally tuned, not a one-time configuration."*
- **Problem:** Plan-revision triggering determines whether the plan stays alive or stales out. The Honest Take is explicit: *"Skip the feedback loop and the plan is a one-shot artifact that ages out of relevance, which is the most common reason care plans become the stale document Linda's plan started as."* The architecture's silence on trigger policy compounds with three concrete consequences:

  1. **Adverse-event triggers must always fire; the architecture should say so.** A hospitalization, a fall, a serious medication side effect, a new clinical diagnosis are events where the plan should revise without question; the clinical risk of leaving the plan unchanged exceeds the operational cost of revision. Without architectural framing, an implementer who is concerned about plan churn might quietly suppress a "single hospitalization" trigger and silence a real signal.

  2. **Threshold-trigger events need explicit threshold policy.** A weight gain of three pounds is a CHF self-management trigger; a weight gain of three pounds in three days specifically is the cardiology-defined threshold; a weight gain of three pounds over thirty days may be diet-driven and not require revision. The plan is set up with a per-action `success_criteria` and `fallback_chain`; the trigger calibration should specify how those criteria failures translate to revision. Without architectural framing, implementers will silently calibrate this differently across deployments, which makes the cohort-fairness analysis (Finding A2) harder because the underlying revision rate is implementation-noise.

  3. **Suppress-trigger events should be named.** A single missed self-management dose, a single missed monthly-checkin, a single PROM completion: these are normal patient behavior and should not trigger revision. The architecture should specify suppression policy explicitly so the system does not over-trigger on within-normal-variation feedback.

  4. **The cohort-fairness implications of trigger calibration are themselves a fairness signal.** Cohorts with worse access to remote monitoring (which produces more frequent feedback events) may see lower-frequency revision triggering than cohorts with widespread RPM enrollment, producing a paradoxical pattern where well-monitored patients get more responsive plans and less-monitored patients get stale plans. The architecture should specify cohort-stratified trigger-rate monitoring as part of the equity instrumentation.

  5. **The activation-and-feedback flow's idempotency depends on the trigger policy.** A replayed `action_completed` event from a reprocessing job should not trigger revision. The architecture should specify that revision triggering is idempotent on the feedback event's deterministic key.

- **Fix:** Specify the trigger calibration framework in pseudocode and architecture:

  ```
  FUNCTION evaluate_feedback_for_revision(plan_id, feedback_record):
      // Always-trigger events (clinical-acuity-driven; revision is
      // always the safer path):
      IF feedback_record.feedback_kind == "adverse_event":
          RETURN { should_revise: true,
                    reason: "adverse_event_always_triggers" }
      IF feedback_record.feedback_kind == "outcome_observed" AND
         feedback_record.feedback_data.event_class == "hospitalization":
          RETURN { should_revise: true,
                    reason: "hospitalization_always_triggers" }
      IF feedback_record.feedback_kind == "outcome_observed" AND
         feedback_record.feedback_data.event_class == "new_diagnosis":
          RETURN { should_revise: true,
                    reason: "new_diagnosis_always_triggers" }

      // Threshold-trigger events (calibrated; per-pair, per-cohort
      // tunable. Default thresholds in catalog; per-cohort tighter
      // thresholds for older or higher-acuity patients):
      IF feedback_record.feedback_kind == "outcome_observed":
          plan = lookup_plan(plan_id)
          alert = check_outcome_against_thresholds(
                      feedback_record.feedback_data,
                      catalog_thresholds_for(plan, feedback_record))
          IF alert.severity >= THRESHOLD_TRIGGER_SEVERITY:
              RETURN { should_revise: true,
                        reason: "outcome_threshold_crossed",
                        alert: alert }

      IF feedback_record.feedback_kind == "action_failed":
          // A single missed action does not trigger revision; persistent
          // failure does. The fallback_chain on the action handles
          // first-line failures; revision triggers when the fallback
          // is also failing or when failure persists across the
          // catalog-defined window (e.g., 14 days for a daily action).
          persistent_failure = check_persistent_action_failure(
              plan_id, feedback_record.target_action_id,
              window_days = catalog_persistence_window(...))
          IF persistent_failure:
              RETURN { should_revise: true,
                        reason: "persistent_action_failure" }

      // Suppress-trigger events (within-normal-variation; do not trigger):
      // - Single missed dose / missed log day
      // - Single missed monthly check-in
      // - Single normal PROM
      RETURN { should_revise: false,
                reason: "within_normal_variation" }
  ```

  Add a paragraph to the architecture pattern:

  *"Plan-revision trigger calibration is policy, not implementation. The chapter-wide framework names always-trigger events (adverse events, hospitalizations, new diagnoses), threshold-trigger events (outcome thresholds defined per pair in the catalog, with per-cohort tunable severity), persistent-failure triggers (action failure persisting beyond the catalog-defined fallback window), and suppress-trigger events (within-normal-variation feedback). The thresholds, the persistence windows, and the per-cohort tuning are catalog-maintained artifacts that the clinical-content team and the equity-review committee jointly approve. Cohort-stratified trigger-rate monitoring is part of the equity instrumentation: chronic over-triggering in some cohorts (often correlated with intensive remote monitoring availability) and chronic under-triggering in other cohorts (often correlated with low access to monitoring) are paradoxical equity signals that the dashboard surfaces at quarterly committee review. Trigger evaluation is idempotent on the feedback event's deterministic key so replayed events from reprocessing jobs do not re-fire revisions."*

  Reference Recipe 4.8 Finding A2 (governance SLA pattern) for the analogous chapter discipline. The chapter editor should consider whether the trigger-calibration framework belongs in chapter preface or stays in 4.9 main text.

### Finding A4: Activation-Dispatch Status From Downstream Operational Systems Is Not Persisted; "Where It Struggles" Names the Gap But Architecture Does Not Address It

- **Severity:** HIGH
- **Expert:** Architecture (clinical safety, multi-system propagation, plan-vs-reality drift)
- **Location:** Step 6 pseudocode `activate_plan`: dispatches actions via `dispatch_action_to_operational_system(effective_action, plan_id, activation_record.activation_id)` and immediately writes `plan-action-records` with `status: "active"`. The "Where it struggles" entry on multi-actor coordination acknowledges the failure mode: *"Plans that activate cleanly in one system and fail to propagate to another are the hardest failure mode to detect; the activation-dispatcher should produce structured success/failure events per integration, and the plan-action-records should reflect propagation status."*
- **Problem:** The "Where it struggles" passage names the architectural primitive that is missing from the architecture. The activation-dispatcher dispatches actions to multiple downstream systems (e-prescribing, scheduling, program registry, patient-portal channel sender, care-management); each has its own success/failure semantics; the pseudocode marks the plan-action-record `status: "active"` immediately, which assumes successful propagation everywhere. The consequences:

  1. **The plan-action-record is the operational source of truth, but it diverges from the operational reality.** A plan-action with `status: "active"` and a failed e-prescribing dispatch (network failure, formulary rejection, e-prescribing system queue saturation) shows in the dashboard as live, but the prescription was never sent to the pharmacy. The patient never gets the medication. The care manager calling to follow up six weeks later discovers the gap. The plan generator's metrics show "100 percent activation" while the patient experience is silent failure.

  2. **The patient-facing narrative makes promises the system cannot verify.** "The care manager will help you schedule your colonoscopy and arrange the ride that your plan covers" is rendered into the patient narrative based on the structured action; if the scheduling-system dispatch failed silently, the care manager has nothing in their queue, and the patient calls expecting follow-up that has not happened. The promise-vs-delivery gap is the fastest way to lose patient trust.

  3. **The Honest Take's "the system that gets these right does not produce a wow; it produces a quiet 'this works for me'" depends on activation propagation actually working.** Without verifiable propagation status, the "this works for me" signal cannot be measured, and the system shipped to thousands of patients silently degrades for those whose actions did not propagate.

  4. **The trigger-calibration concern in Finding A3 compounds.** A `persistent_action_failure` revision trigger requires that "action failure" be observable. If the activation-dispatch failed silently (the action never reached the operational system), then "action failure" is not observable; the revision trigger does not fire; the plan stays "active" against an action that was never actually live.

- **Fix:** Architect the activation-dispatch status pipeline in pseudocode and architecture:

  ```
  FOR each action_id in activation_payload.approved_action_ids:
      action = find_action(plan, action_id)
      ...
      // Initial state: pending operational-system propagation.
      DynamoDB.PutItem("plan-action-records", {
          plan_action_record_id: new UUID,
          plan_id:               plan_id,
          action_id:             action_id,
          effective_action:      effective_action,
          status:                "pending_dispatch",
          owner_role:            effective_action.owner_role,
          ...
      })

      // Dispatch is asynchronous. The activation-dispatcher Lambda
      // calls each integration; each integration responds with
      // structured success/failure. Updates the plan-action-record
      // status and emits per-integration metrics.
      dispatch_handle = activation_dispatcher.dispatch(
          effective_action, plan_id, activation_record.activation_id)
      // dispatch_handle is awaited asynchronously; the dispatcher
      // updates plan-action-records with one of:
      //   "active" (operational system confirmed)
      //   "active_partial" (multi-system action where some propagated)
      //   "dispatch_failed" (terminal failure; revision trigger fires)
      //   "pending_dispatch" (still in flight; SLA-driven retry)

  // Aggregate activation-record status reflects the propagation reality:
  per_action_statuses = await_dispatch_results(activation_record.activation_id,
                                                  timeout = ACTIVATION_DISPATCH_SLA)
  activation_record.dispatch_summary = per_action_statuses
  activation_record.activation_status = aggregate_status(per_action_statuses)
  // activation_status is one of "fully_active", "partially_active", or
  // "dispatch_failed_pending_review".
  ```

  And add a paragraph to the architecture pattern:

  *"Activation propagation is not a one-shot event. The activation-dispatcher dispatches each action to its operational system (e-prescribing, scheduling, program registry, patient-portal channel sender, care-management); each system responds asynchronously with structured success/failure semantics. The plan-action-record's status field reflects the propagation reality, not the dispatch optimism: a status of 'active' requires the operational system's confirmation; a status of 'pending_dispatch' triggers SLA-driven retry; a status of 'dispatch_failed' surfaces to the care team and (per Finding A3) triggers plan revision evaluation. The patient-facing narrative is rendered after the activation reaches a stable state; promises the system cannot verify are not made to the patient. Per-integration success-rate dashboards (e-prescribing dispatch success, scheduling dispatch success, program-registry dispatch success, patient-portal dispatch success) are part of the operational metrics, with cohort stratification because dispatch failures may concentrate in cohorts with specific channel preferences (e.g., mailed-letter dispatch failures concentrating in low-digital-literacy cohorts)."*

  Reference Recipe 4.4-4.7's optimistic-counter-without-reconciliation findings as the chapter pattern; in 4.9 the issue is propagation status rather than counters, but the architectural primitive (close the loop with the operational system before claiming the action is live) is the same.

### Finding A5: Goals-of-Care Data Quality Flag Is Not Computed or Surfaced

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, clinical safety)
- **Location:** Step 1 pseudocode aggregates `goals_of_care` from POLST, advance directive, ACP conversations, and stated preferences. Step 2's `compute_goals_of_care_adjustment(goal, plan_input_record.goals_of_care)` consumes the aggregate without distinguishing rich-structured-input cases from sparse-or-inferred-input cases.
- **Problem:** The recipe is explicit that goals-of-care preferences are "partially structured (POLST, advance directives), partially semi-structured (patient-portal questionnaires, structured ACP conversation notes), and partially unstructured (free-text notes about what the patient said in the visit)." The Honest Take expands: *"A trap I keep seeing fresh teams fall into: skimping on the goals-of-care alignment because the data is messier than the disease-specific guidelines. ... Skip it and the plan optimizes for clinical outcomes the patient did not pick."*

  The architectural pseudocode does not produce a `goals_of_care_quality_flag` that distinguishes:
  - High quality: signed POLST or advance directive plus explicit stated preferences from a structured ACP conversation within the past 12 months.
  - Medium quality: stated preferences from a structured questionnaire without a POLST.
  - Low quality: inferred preferences only (from prior decisions or visit-note free text).
  - Sparse: no preference data captured.

  Three consequences:

  1. **The clinician-facing narrative cannot honestly tell the clinician how confident the goals-of-care alignment was.** A clinician reviewing the plan does not know whether the "comfort_focused_flag = true" that re-weighted multiple goals was based on a recent signed POLST (high confidence) or on a single visit-note interpretation from two years ago (low confidence). Without the quality flag, clinicians either over-trust the system or under-trust it; both are suboptimal.

  2. **The plan-revision trigger calibration (Finding A3) should escalate goals-of-care reassessment when the data is sparse.** A patient with sparse goals-of-care data should have an action in the plan to schedule a structured ACP conversation; the recipe's Variations and Extensions section names this as "Goals-of-care conversation prompts," but the architecture does not produce the data-quality signal that triggers it.

  3. **The cohort-fairness instrumentation (Finding A2) should monitor goals-of-care data quality per cohort.** If goals-of-care data quality is systematically lower for some cohorts (older patients, non-English-preferring patients, cohorts with less primary-care continuity), the plan-generation system silently substitutes algorithmic defaults for patient preferences in exactly those cohorts. That is a fairness failure that the recipe's stated equity instrumentation does not currently catch.

- **Fix:** Add `goals_of_care_quality_flag` computation in Step 1 and propagate through Step 2:

  ```
  plan_input_record.goals_of_care = HealthLake.GetGoalsOfCare(patient_id)
  plan_input_record.goals_of_care.quality_flag = compute_goc_quality(
      polst              = plan_input_record.goals_of_care.polst,
      advance_directive  = plan_input_record.goals_of_care.advance_directive,
      acp_conversations  = plan_input_record.goals_of_care.acp_conversations,
      stated_preferences = plan_input_record.goals_of_care.stated_preferences,
      last_updated       = plan_input_record.goals_of_care.last_updated)
      // Returns one of: "high", "medium", "low", "sparse".
  ```

  And surface the flag in the clinician-facing narrative as a required-content layer 4 element:

  *"The clinician-facing narrative includes a goals-of-care confidence callout: 'Goals-of-care alignment based on signed POLST + ACP conversation 4 months ago' (high), or 'Goals-of-care alignment based on portal questionnaire 14 months ago, no signed advance directive' (medium), or 'Goals-of-care preferences are sparse; recommend structured ACP conversation' (low/sparse). The callout is not optional; the clinician should never review a plan without knowing the goals-of-care data quality."*

  Add a structured ACP conversation action (the Variations and Extensions section names this; the architecture should specify when it fires) when `quality_flag in ['low', 'sparse']` and the patient is not in active palliative care. Add cohort-stratified goals-of-care data quality monitoring to the equity dashboard.

### Finding A6: Patient Consent Flow Architected at Production-Gap Level; Three-Layer Consent Should Be in Architecture

- **Severity:** MEDIUM
- **Expert:** Architecture (regulatory, ethical, the recipe's most-acknowledged gap)
- **Location:** "Why This Isn't Production-Ready": *"Patient consent for data use and plan-generation participation. The plan uses goals-of-care preferences, SDOH data, functional and cognitive status, family-caregiver involvement, and longitudinal engagement signals. ... The institution's existing consent infrastructure typically does not have all of these granularities; expect to extend it."* Existing TODO acknowledging the gap.
- **Problem:** Same chapter pattern as Recipe 4.8 Finding A6, sharper here because the data inputs are broader. Patient consent is the regulatory and ethical centerpiece of the recipe. Three distinct consent layers are needed:

  1. **Consent to use of model-derived predictions, signals, and structured plan in clinical care.** Some institutions treat this as part of standard institutional consent; others require per-patient consent at care-relationship establishment.
  2. **Consent to ongoing data use for cohort-fairness instrumentation, plan-quality monitoring, and (where applicable) cross-recipe model retraining.** Separable from clinical-care consent; HIPAA permits research use with appropriate authorization but the patient should know.
  3. **Consent to family/caregiver narrative sharing.** A patient may consent to family-caregiver involvement in their plan without consenting to having every detail shared (a depression diagnosis, an SUD history, an end-of-life preference). The recipe's Variations and Extensions section names "Caregiver-facing narrative" as a variant; the consent state must be granular enough to support per-attribute sharing.

  Consent withdrawal must propagate to the inputs aggregation (a withdrawn-consent patient is excluded from cohort-fairness aggregations going forward; the historical plans are retained for audit but excluded from retraining cohorts), to the activation pipeline (a withdrawn-consent patient does not have new plans generated), and to the patient-facing delivery (the patient-portal access is disabled per the institution's consent-withdrawal policy).

- **Fix:** Add a brief subsection to the architecture pattern (300-400 words) specifying the three-layer consent state, the per-(patient, layer, attribute) granularity, and the withdrawal propagation flow. Mirror the language flagged in 4.5-4.8 chapter pattern. Reference Recipe 4.8 Finding A6 as the chapter sibling.

### Finding A7: Action Fallback-Chain Execution Is Defined but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, the recipe's central success-or-fail-loudly primitive)
- **Location:** Action templates carry `fallback_chain`. Step 4 verifies actions have a fallback when required. Step 6 records feedback that may include `action_failed`. The pseudocode does not specify how a failed action transitions to its fallback.
- **Problem:** The fallback_chain is the recipe's "fail loudly" primitive: when `colonoscopy_with_transport` fails (patient declines, scheduling impossible), the catalog specifies `fit_test_if_colonoscopy_declined` as the fallback. The architecture does not specify:

  1. **When the fallback fires.** On `action_failed` feedback (a system or clinician event marking the action failed), the fallback should be activated; this is not just plan-revision, this is in-flight action substitution.
  2. **Who owns the fallback decision.** Should the fallback fire automatically (the system substitutes the FIT test for the colonoscopy), or should it surface to the care team for review (the care manager confirms with the patient that the colonoscopy is declined before substituting)? The choice is policy, not implementation, and it varies by action class (medication substitutions probably want clinician review; care-gap-screening substitutions may not).
  3. **How the fallback interacts with the plan-revision trigger.** A failed action with a successful fallback may not require plan revision (the fallback handles it); a failed action with no fallback or a failed fallback always triggers revision. Finding A3's trigger calibration depends on this being specified.
  4. **What the patient-facing narrative says when a fallback fires.** "We were not able to schedule your colonoscopy; we are switching to a stool-based screening test that you can do at home" is the right framing; "Your action 'colonoscopy_with_transport' has been failed and replaced with 'fit_test_if_colonoscopy_declined'" is exactly the document-not-plan failure the recipe is trying to escape.

- **Fix:** Add a `fallback_dispatcher` Lambda to the architecture and specify the policy:

  *"When a plan-action-record transitions to status `failed`, the fallback dispatcher consumes the failure event and evaluates the action's fallback_chain. Fallback firing policy is per-action-class and catalog-defined: medication substitutions require clinician review (the dispatcher creates a review task in the EHR's clinical inbox and waits for approval); care-gap-screening substitutions and self-management-action substitutions can fire automatically with care-team notification; appointment-substitutions surface to the scheduling system for re-booking. When a fallback fires, the corresponding plan-action-record (the original) is marked `failed_fallback_active` and a new plan-action-record (the fallback) is activated through the standard activation-dispatch flow (Finding A4). The patient-facing narrative, on the next refresh, includes a what-changed entry describing the substitution in plain language. Failed fallbacks (the fallback also fails, or the fallback_chain is exhausted) trigger plan revision via Finding A3's mechanism."*

### Finding A8: Cohort-Feature Lookup Repeats Per-Action and Per-Goal (Same Pattern as 4.4-4.8)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Implicit in the per-goal and per-action loops in Step 2 and Step 3 where cohort overrides are applied; in metric emission paths in Steps 3-6.
- **Problem:** Same finding as 4.4 Finding 13, 4.5 Finding A4, 4.6 Finding A4, 4.7 Finding A4, 4.8 Finding A8. With multiple goals (6+ for Linda) and many actions per goal (10-30 candidates before reconciliation) and cohort lookups in metric emission paths (per stage), the redundant DynamoDB reads multiply across the plan-generation workflow.
- **Fix:** Hoist the cohort-feature cache out of the per-goal and per-action loops; compute once per patient at the start of `aggregate_plan_inputs`, attach to `plan_input_record.cohort_features`, and pass through to metric emission. Reference 4.4-4.8 chapter pattern.

### Finding A9: Clinical Content Versioning Across Plan Generation and Plan Revision Is Underspecified

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, audit, regulatory)
- **Location:** Goal templates and action templates carry `version`. Plan finalization persists `source_template_version` per goal and per action. The architecture is silent on what happens when a template version updates between a plan's first activation and a subsequent revision.
- **Problem:** Three scenarios where versioning matters:

  1. **A goal template updates between v6 and v7 of Linda's plan.** v6 used `chf_avoid_readmission` template version 2026.01; v7 is generated against version 2026.04 with stricter weight-monitoring criteria. The clinician-facing narrative's `what_changed_since_v6` should distinguish "patient's clinical state changed" from "template content changed" so the clinician understands which changes are about Linda and which are about the catalog.
  2. **A template is retired (effective_dates expire) while Linda has an active plan referencing it.** The active plan-action-record references a template that no longer applies. The architecture should specify whether the action continues to run against the retired template's content or migrates to the successor template.
  3. **Parallel evaluation policy (named in the prerequisites under "Clinical Content Governance") needs to be operationalized.** The architecture says the clinical-content review committee runs new templates against prior plans on a held-out cohort; the architecture does not specify the parallel-evaluation infrastructure (a shadow plan-generation pipeline, a diff surface, a review surface for the committee).

- **Fix:** Add a paragraph to the architecture pattern specifying:

  *"Clinical-content version transitions are managed through the catalog's effective-dates discipline. A plan's plan_input_record freezes the effective template versions at generation time; the plan-record persists `source_template_version` per goal and per action. On plan revision, the inputs aggregation re-fetches the current template versions; the goal-derivation and action-assembly stages produce the new plan against the new versions; the clinician-facing narrative's `what_changed_since_v{N-1}` distinguishes patient-state changes from template-content changes via per-element diff against the prior plan-record. Retired templates do not cause active plans to fail; the activation-dispatcher continues to dispatch actions against the retired template's content until the next plan revision migrates them. Parallel evaluation runs the new template version through a shadow plan-generation pipeline against a held-out cohort of prior patients; the diff surface produces per-cohort difference summaries that the clinical-content review committee approves before promoting the new version to production. The shadow pipeline reuses the same Step Functions workflow, with output S3 prefixes scoped to `shadow/`."*

### Finding A10: Multi-Language Patient Narrative Validation Is Discussed in Variations but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (clinical safety, equity)
- **Location:** Variations and Extensions section: *"Multi-language patient-facing narratives. The patient-facing narrative is generated in the patient's preferred language. Beyond simple machine translation, the variation includes: language-specific reading-level scoring, cultural-context overrides for goal framing, idiomatic localization, and language-specific approved-claim language. The catalog supports per-language template variants. The validator applies language-specific reading-level checks. Plan for in-language clinical content review for the languages you support; machine translation alone is not sufficient for clinical content."*
- **Problem:** Multi-language is named as a variation, but the architectural impact is broader than a variation framing suggests. For Spanish-, Mandarin-, Vietnamese-, Tagalog-, Russian-, and other-language-preferring patient cohorts (frequently the cohorts that the equity instrumentation should be most sensitive to), the patient-facing narrative is the surface area where the system either earns trust or breaks it. Three architectural decisions need explicit framing:

  1. **The validator's language-specific reading-level scoring requires language-specific scoring algorithms** (Flesch-Huerta-Macuso for Spanish, INFLESZ for Spanish-but-medical, syllabification differs by language). The architecture should specify that the validator's reading-level-scoring layer dispatches per-language.
  2. **The approved-claim-language enforcement is per-language.** "We were not able to schedule" translates to different acceptable phrasings in different languages; some languages require formality registers that English does not. The catalog should maintain per-language prohibited-pattern lists and required-content templates.
  3. **The fallback templated narrative is per-language.** A templated fallback in English for a Spanish-preferring patient is a fairness failure: the patient gets neither the LLM narrative nor a meaningful fallback.

- **Fix:** Promote the multi-language variation into a first-class architectural concern with a paragraph specifying the per-language validator dispatch, the per-language catalog content, and the per-language templated-fallback discipline. Reference Recipe 4.2 (educational content matching) for the multi-language reading-level pattern; reference 4.1 (channel optimization) for the language-as-channel-attribute pattern.

### Finding A11: 30+ Goal Templates × 5+ Cohort Overrides Without Coordinated Promotion Path (Same Pattern as 4.4-4.8, Sharper Here)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Goal templates and action templates with cohort overrides; production-gaps clinical-content library curation; chapter-wide TODO.
- **Problem:** Same chapter-wide pattern, sharper here because the artifact count is materially larger. A production deployment covering the most common chronic-condition combinations (T2D + CKD, CHF + T2D, CHF + CKD, depression + chronic pain, polypharmacy in elderly) with cohort overrides for pediatric/geriatric/palliative/pregnancy populations produces 50-200 goal templates and 200-1000 action templates. Without coordinated promotion path (versioning, rollback, retirement, parallel evaluation), the catalog accumulates inconsistencies.
- **Fix:** Same as 4.4-4.8. The Recipe 4.9-specific extension is parallel evaluation (Finding A9) and per-language variants (Finding A10). Reference Recipe 7.x for full lifecycle treatment.

