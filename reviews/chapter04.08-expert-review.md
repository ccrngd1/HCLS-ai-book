# Expert Review: Recipe 4.8 - Treatment Response Prediction

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-21
**Recipe file:** `chapter04.08-treatment-response-prediction.md`

---

## Overall Assessment

This is the methodologically deepest recipe in Chapter 4 and the highest-stakes from a clinical and regulatory perspective. It correctly graduates the per-program scoring + uplift + LLM-packaging pattern from 4.4-4.7 into causal-inference territory: the unit of decision is a per-treatment-comparator CATE estimate, the consumer is a prescribing clinician at the point of care, the regulatory framing is FDA Software as a Medical Device versus 21st Century Cures Act CDS exemption, and the ethical wrinkle (the prediction directly affects what drug a real patient takes home) is the chapter's most acute. The Marcus vignette in The Problem is excellent: 58 years old, A1c 8.7 climbing despite metformin, eGFR 64 declining, calcium score 240, albuminuria, the five-way fork between sulfonylurea, DPP-4, GLP-1, SGLT2, and basal insulin, the seven-minute slot, the manufacturer-rep / formulary / EHR-default that actually drives the prescribing decision, and the explicit framing that thousands of patients exactly like Marcus exist in the plan's panel and the data on what happened to them is sitting in a warehouse not being consulted in the moment. The "fundamentally a causal question, not a correlational one" framing is exactly right and earns the recipe's right to spend the next twenty pages on methodology.

The Technology section is the chapter's strongest single methodological treatment: the Neyman-Rubin potential outcomes formalism, the CATE-versus-ITE distinction (correctly framed as "individualized is aspirational; conditional-average is what the math delivers"), the curse of dimensionality / confounding by indication / hidden subgroups / treatment-effect heterogeneity / selection bias / calibration drift failure-mode taxonomy, the survey of method families (meta-learners, causal forests, BART, deep learning, target trial emulation, TMLE, IPTW), the multi-source uncertainty quantification (sampling, model, unmeasured-confounding, distributional shift, outcome-definition), and the "Where the Field Has Moved" subsection (target trial emulation as gold standard, doubly-robust meta-learners maturing, calibration of CATE estimators emerging, FDA SaMD framework evolving, federated/consortium approaches, foundation-model patient embeddings) collectively make the Technology section publishable as a standalone methodological primer. The "Where LLMs Fit (and Don't)" subsection correctly draws a sharper line than 4.5-4.7: the LLM packages, the LLM does not pick, and "treatment-response prediction is the highest-stakes recipe in this chapter, so the line is even more important." The validator gets a tighter rule (no recommendation language, period) than in any prior recipe.

The architecture's six logical components (treatment catalog, feature pipeline and cohort construction, causal modeling, cohort retrieval and scoring, clinician-facing decision support, feedback and surveillance) are the right shape for the problem. The treatment catalog as governance-not-engineering framing extends the program-registry pattern from 4.7 to a more structured artifact (treatment_id, comparator_id, eligibility predicates, outcome definitions, evidence level, formulary status, supply constraints, model risk tier). The seven-stage causal-modeling pipeline (target trial emulation, propensity, outcome, CATE ensemble, uncertainty, calibration, governance gate) is the chapter's most operationally rigorous training workflow. The on-demand scoring path with eligible-pair determination, per-pair ensemble inference, similar-patient cohort summary (with the explicit "full-cohort retrieval would be PHI-leaking; only summaries leave the cohort store" framing later in the code review), uncertainty composition, OOD flagging, and sensitivity-bound widening is the chapter's most disciplined inference path. The clinician-facing decision support with strict no-recommendation validator, regeneration loop with stricter prompts, and templated fallback that always passes is the chapter's most defensive LLM-output path.

The Honest Take is, by a clear margin, the chapter's strongest. Eight observations stand out: (1) the ATE-versus-CATE-versus-ITE distinction with the explicit "for you, GLP-1 will lower A1c by 1.4 percentage points" versus "for patients similar to you, the average A1c reduction on GLP-1 was 1.4 pp greater than on SGLT2" framing ("the difference looks small. It is everything."); (2) the propensity-overlap diagnostic as a hard gate rather than a warning ("the difference between an honest output and a confidently wrong one"); (3) estimator agreement is not the sole signal of robustness ("Estimators from the same method family will agree because they are making correlated assumptions"); (4) the invest-in-causal-inference-depth staffing recommendation as the highest-leverage decision; (5) the validator's no-recommendation rule as non-negotiable with the "less readable templated fallback is acceptable" framing; (6) the "expand the catalog only as fast as the surveillance infrastructure can support, not as fast as the modeling team can train new models" discipline; (7) the override-rate-as-diagnostic-not-problem framing ("a clinician who looks at the briefing and chooses a different treatment is doing exactly what the system is designed to support"); and (8) the closing acknowledgement that "treatment response prediction tools, even when they are technically advisory, change clinical practice" with the "build the system as if it will change practice, because it will" directive. The closing "the hardest decision in this work is not whether to ship the model. It is whether to keep it shipped after watching what it actually does" is the chapter's strongest closing sentence on voice grounds.

That said, four correctness gaps need attention before publication, and the medium and low items round out the review. (1) `match_outcome` (Step 6) and the calibration-drift detection (also Step 6) conflate the per-pair CATE estimate (a treatment-effect *difference*, e.g., E[Y(GLP-1) - Y(SGLT2) | X]) with the patient's actual single-arm observed outcome (Y(chosen_treatment)). The pseudocode writes the CATE point estimate into `predicted_outcome` and the single-arm outcome into `actual_outcome` and feeds them into `compare_calibrations`. These are not directly comparable quantities. The methodological centerpiece of this recipe (target trial emulation, CATE estimation with proper identification) collapses back to the naive observational comparison the recipe spends 1,500 words warning against. The Python code review flagged this as Finding 3 / WARNING; the issue is upstream, in the architectural pseudocode the Python implements. (2) The `record_decision` and `match_outcome` consumer paths have no patient-identity-boundary checks against the decision_payload arriving from API Gateway. A misrouted clinician event recording a decision for the wrong patient (or an authorization-bypass attempt) silently mutates the wrong record. The chapter pattern from 4.4-4.7 enforces an identity-check immediately after the source-record lookup; both 4.8 consumer paths skip it. (3) The `governance-review-tasks` workflow has an `sla_review_by` field but no auto-default behavior, escalation logic, or per-cohort review-latency monitoring on stale tasks. A model artifact stuck in `pending_review` indefinitely consumes governance attention without producing a decision; meanwhile the prior model continues to serve potentially-stale predictions, and prediction-error-by-cohort patterns concentrate in the governance latency rather than in the eventual outcome. The 4.7 SLA finding has direct sibling consequences here. (4) The OOD severity threshold is computed (`compute_ood_flag` returns severity) and the prose discusses suppression versus presentation, but the pseudocode does not specify the band cutoffs that route between presentation, warning, and suppression at the briefing layer. The Python companion picks 0.50 and 0.85 reasonably; the recipe pseudocode is silent. For the chapter's highest-stakes recipe, the suppression policy belongs in the architecture, not the implementation.

Eleven chapter-wide patterns repeat (briefing/decision/scoring-ID privacy, validator four-layer specification, SDOH cohort PHI promotion, IAM ARN scoping, `0.0.0.0/0` egress, identity-boundary checks, governance-task SLA, model-promotion path, cross-recipe orchestration, DLQ coverage, EHR integration credential posture). Several are explicitly TODO'd in the recipe text; this review carries them forward at LOW or MEDIUM severity reflecting the chapter editor's eventual consolidation responsibility.

Voice is excellent. Em dash count: 0 (verified). En dash count: 0 (verified). 70/30 vendor balance is maintained. Marcus is the consistent named patient throughout (no Mr. Garcia / Linda continuity break). Marcus's clinical scenario is internally consistent and clinically accurate (A1c 8.7 on metformin monotherapy after 8 years is a classic second-line decision point; eGFR 64 with declining trajectory and albuminuria is appropriate KDIGO CKD 2-3a with risk of progression; calcium score 240 is intermediate-risk for cardiovascular events; the GLP-1/SGLT2 cardiorenal indication framing is consistent with current ADA Standards of Care; the metformin dose accommodation at eGFR 30-45 issue is an authentic polypharmacy concern though not central to this recipe's framing). The illustrative CATE estimates in the sample scoring result (-0.62 pp for GLP-1 vs SGLT2 at 90 days, with CI -0.94 to -0.31) are clinically plausible and consistent with the published GLP-1/SGLT2 head-to-head observational literature; the secondary outcome figures (8-11% weight reduction on GLP-1, 14% GI-intolerance discontinuation, 6% genitourinary infection on SGLT2) are reasonable mid-range estimates rather than vendor-favorable cherry-picks. The E-values quoted (1.84 for GLP-1 vs SGLT2, 1.21 for GLP-1 vs sulfonylurea) are illustrative but appropriate-magnitude for an observational study with well-controlled confounders.

Priority breakdown: 0 critical, 4 high, 11 medium, 6 low. PASS by a narrow margin (4 HIGH is at the threshold; > 3 = FAIL means 4 fails. Re-checking: the persona rule says "more than 3 HIGH findings means FAIL." 4 is more than 3. **The verdict is FAIL.**)

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA explicitly named with HIPAA-eligibility TODOs for SageMaker, Bedrock, HealthLake, and EHR-integration components. Continues the chapter pattern.
- Customer-managed KMS keys for every PHI store with explicit framing of `scoring-results`, `decision-records`, and `prediction-outcome-pairs` as "highly inferential PHI" because they join patient identifiers with predicted treatment outcomes. The framing is correctly sharper than analytical-PHI: a row indicating "patient has a predicted 1.4 pp greater A1c reduction on GLP-1 versus SGLT2" implicitly reveals diabetes diagnosis, current treatment regimen, and the clinical inadequacy of current therapy. Briefing text in DynamoDB is explicitly named as PHI.
- CloudTrail data events on `treatment-catalog`, `scoring-results`, `decision-records`, `prediction-outcome-pairs`, and `briefings`. The "audit posture for treatment-recommendation artifacts approaches clinical-record audit standards" framing is the recipe-specific sharpening that distinguishes 4.8 from 4.4-4.7.
- Bedrock paragraph: confirmation that prompts and completions are not used to train foundation models. Continues chapter pattern.
- The validator's four conceptual layers (schema and length, fact grounding, recommendation language, uncertainty completeness, required caveats) are named. The "no-recommendation language" rule is the most aggressively-policed LLM constraint in Chapter 4, appropriate for the recipe with the highest clinical stakes.
- The de-identification posture for LLM calls is explicit: `build_clinical_summary(scoring.patient_id)` returns "de-identified for the LLM call: condition, key labs, current medications, key trajectory features." Mirrors the chapter pattern.
- Patient consent for shared decision-making and ongoing data use is named in the production-gaps section as a TODO with substantive framing (consent to model-derived predictions in care, consent to ongoing data use, capture of patient-stated preferences, right to withdraw).
- Regulatory posture (FDA SaMD versus Cures Act CDS exemption, predetermined change control plan, Good Machine Learning Practice principles, postmarket surveillance, complaint handling) is treated as a first-class architectural concern rather than a footnote.

### Finding S1: `record_decision` and `match_outcome` Have No Patient-Identity Boundary Checks Against the Inbound Payload

- **Severity:** HIGH
- **Expert:** Security (PHI integrity boundary, authorization)
- **Location:** Step 6 pseudocode, the `record_decision(scoring_run_id, decision_payload)` function: `scoring = DynamoDB.GetItem("scoring-results", scoring_run_id)` followed by state-machine mutations on `scoring.patient_id` and `decision_payload.clinician_id` with no identity-boundary check; the `match_outcome(decision_id, run_date)` function: `decision = DynamoDB.GetItem("decision-records", decision_id)` followed by reads of `decision.patient_id` for outcome matching, with no validation that `run_date` and the matching context belong to the same operational context.
- **Problem:** The chapter pattern from 4.2, 4.3, 4.4, 4.5, 4.6, and 4.7 enforces an identity-boundary check on engagement-event consumers and human-action consumers: when an event or action references a recommendation, briefing, or decision by ID, the consumer reads the source record and validates that the action's metadata is consistent with the source before applying any state change. Both 4.8 consumer paths skip this check, and the consequences here are sharper than in any prior recipe because the artifact being mutated is closer to a clinical record than any prior recipe's artifact:

  1. **`record_decision` is the single most security-sensitive write path in Chapter 4.** It receives a `decision_payload` that includes `clinician_id`, `chosen_treatment_id`, `clinician_rationale`, and `patient_consent_recorded` over the API Gateway / Cognito path, then writes a `decision-records` row that is treated as audit-grade. A `decision_payload` arriving with mismatched metadata (a clinician submits a decision-payload referencing scoring_run_id A but for chosen_treatment_id B that is not in scoring_run_id A's `eligible_pairs`; a misrouted event from a different clinician's session; an authorization-bypass attempt that submits a scoring_run_id the calling clinician should not have access to) would silently apply the wrong decision to the wrong patient, freeze the wrong predictions into the audit trail, fire a Kinesis `treatment_decision_recorded` event that flows into surveillance, and contaminate the prediction-outcome-pairs table 90 days later when `match_outcome` runs.

  2. **The downstream blast radius is the regulated-decision audit trail.** Recipe 4.7's disenrollment audit was sensitive (Finding S1 there); 4.8's decision audit is the same posture *plus* the FDA SaMD-or-Cures-Act framing. A contaminated `decision-records` row is not an analytics issue; it is a clinical-decision audit-trail issue. Plans operating under FDA postmarket surveillance commitments depend on this audit trail being accurate per-patient per-decision; under quality-system-regulation expectations, a misrouted decision is a complaint-handling event.

  3. **The pattern is not just defensive coding.** It is the architectural primitive that the Cures Act CDS exemption depends on. The exemption requires that the clinician be able to "independently review the basis of the recommendation" and that the basis be associated with the right patient. A system that lets a clinician's decision attach to the wrong patient's basis breaks the exemption argument, regardless of whether the misrouting was malicious.

  4. **`match_outcome` is the same posture, executed asynchronously.** It runs in batch 90 days after a decision; the inputs are `decision_id` and `run_date`. The function reads `decision.patient_id` and writes a `prediction-outcome-pairs` row. If a stale or replayed `decision_id` flows into the matcher (for instance, a reprocessing job that re-emits an old batch), the matcher writes a new prediction-outcome row keyed on `(decision_id, patient_id)` against an outcome computed at a wrong as-of date. The existing pseudocode does not guard against this because there is no version or freshness check on the decision-record at match time.

- **Fix:** Add the identity check immediately after the scoring/decision lookup in `record_decision`:

  ```
  scoring = DynamoDB.GetItem("scoring-results", scoring_run_id)
  IF scoring is null:
      LOG("scoring-results lookup failed", scoring_run_id=scoring_run_id)
      RETURN error("scoring_not_found")

  // Validate clinician's authorization to record a decision against this
  // scoring run: the calling clinician's session must have access to the
  // patient (treatment-relationship check), and the chosen_treatment_id
  // must be in the scoring run's eligible_pairs list (the clinician
  // cannot record a decision for a treatment the model did not score).
  IF NOT clinician_has_treatment_relationship(decision_payload.clinician_id,
                                                 scoring.patient_id):
      LOG("decision_payload clinician_id without treatment relationship",
          clinician = decision_payload.clinician_id,
          patient   = scoring.patient_id)
      emit_metric("decision_authorization_violation", value = 1)
      RETURN error("clinician_not_authorized")

  IF decision_payload.chosen_treatment_id != "none" AND
     decision_payload.chosen_treatment_id NOT IN
        [pair.treatment_id FOR pair in scoring.pair_results]:
      LOG("decision_payload chosen_treatment_id not in scoring eligible pairs",
          chosen   = decision_payload.chosen_treatment_id,
          eligible = scoring.eligible_pairs)
      emit_metric("decision_treatment_mismatch", value = 1)
      RETURN error("treatment_not_in_scope")

  IF decision_payload.scoring_run_id is not null AND
     decision_payload.scoring_run_id != scoring_run_id:
      LOG("decision_payload scoring_run_id mismatch; dropping",
          submitted = decision_payload.scoring_run_id,
          stored    = scoring_run_id)
      emit_metric("decision_scoring_run_mismatch", value = 1)
      RETURN error("scoring_run_mismatch")
  ```

  Add an analogous check to `match_outcome`: validate that the `decision_id` being matched has not already been matched (no duplicate prediction-outcome-pair), that the `run_date` is consistent with the decision's primary-outcome timing window per the protocol, and that the decision-record version has not been superseded by a replay or reprocessing event.

  Reference 4.4 Finding S1, 4.5 Finding S1, 4.6 Finding S1, 4.7 Finding S1 as the chapter-wide pattern; the chapter editor should consolidate the identity-check guidance into a chapter-4 preface that all recipes reference. For 4.8 specifically, the regulated-decision audit-trail posture earns the HIGH severity rather than the MEDIUM severity used in prior recipes.

### Finding S2: Briefing-ID, Decision-ID, and Scoring-Run-ID Embed Patient ID and Date in Plain Text (Chapter-Wide Pattern; Already TODO'd)

- **Severity:** MEDIUM
- **Expert:** Security (PHI minimization)
- **Location:** Sample scoring result `"scoring_run_id": "score-2026-04-22-pat-007842-7c3a"`; sample briefing `"briefing_id": "brief-2026-04-22-pat-007842-2f1a"`; sample prediction-outcome pair `"pair_id": "po-2026-07-21-pat-007842-glp1"` and `"decision_id": "dec-2026-04-22-pat-007842-glp1"`; existing TODO in production-gaps section.
- **Problem:** Same finding as 4.4 Finding 2, 4.5 Finding S2, 4.6 Finding S2, 4.7 Finding S2. The recipe acknowledges the gap with a TODO that mirrors the chapter-wide fix language.

  Treatment-response-specific sharpening: the scoring_run_id is carried in the EHR integration via SMART on FHIR or CDS Hooks responses, where it travels through clinician inboxes, EHR audit logs, and any third-party EHR-integration vendor logging. The combination of an identifier that reveals patient identity *and* a timestamp that can be correlated with a clinic visit is more sensitive than the analytics-event-bus IDs from 4.4-4.6. Additionally, the `pair_id: po-2026-07-21-pat-007842-glp1` format reveals that the patient was prescribed GLP-1, which is highly inferential for diabetes diagnosis; for analogous pairs in stigmatized clinical areas (HIV antiretrovirals, antipsychotics, addiction-medicine MAT), the disclosure intersects with state-specific confidentiality statutes (42 CFR Part 2 for substance-use, state mental-health-confidentiality laws, etc.). The "treatment_class embedded in identifier" pattern is sharper than any analogous pattern in 4.4-4.7.

- **Fix:** Same as 4.4-4.7 Finding S2. Replace string-concatenation IDs with opaque UUID or HMAC-SHA256 over the composite with a per-environment secret. For SMART on FHIR / CDS Hooks responses specifically, the opaque ID requirement is non-negotiable; document this explicitly in the privacy paragraph rather than as a TODO. The Python code review's Finding 2 names the parsing-bug consequence of carrying the identifier as plain-text: a string-split parser on `score-{run_date}-{patient_id}-{suffix}` is incorrect because both `run_date` and `patient_id` contain hyphens; the architectural fix (opaque ID + persisted GSI lookup) and the implementation fix (carry patient_id through the call chain) are the same fix.

### Finding S3: Briefing Validator's Four Layers Are Named in Comments but Not Specified

- **Severity:** MEDIUM
- **Expert:** Security (regulatory, hallucination guardrails, prescribing safety)
- **Location:** Step 5 pseudocode, the `validate_briefing(briefing_parsed, observed_context = briefing_context)` call with an inline TODO that begins to specify the four-layer structure; the prose surrounding it.
- **Problem:** The four-layer structure (schema and length, fact grounding, recommendation language, uncertainty completeness, required caveats) is named in comments but not specified to the level of detail that 4.7 Finding S3 recommended. For the highest-stakes LLM-output surface in Chapter 4, the validator specification deserves more text than a comment block.

  Treatment-response-specific sharpening:

  1. **The recommendation-language layer must be the strictest in the chapter.** A briefing for an enrollment program can tolerate a phrase like "this patient is a strong candidate for the HF program" in a way that a treatment-decision briefing cannot tolerate "this patient is a strong candidate for GLP-1." The validator should reject any phrasing that crosses from comparison ("the model estimates greater 90-day A1c reduction on GLP-1 than on SGLT2") into selection ("the patient should be prescribed GLP-1"; "the evidence supports GLP-1"; "GLP-1 is the better choice"; "consider initiating GLP-1"; "we recommend GLP-1"). The pattern set should include eleven or more aggressive-recommendation patterns (the Python companion lists eleven; the architectural pseudocode should match).

  2. **The fact-grounding layer must be sharper than 4.7's.** Treatment-effect estimates are precise quantities (point estimate, CI, cohort size, OOD severity, calibration status); a briefing that quotes a slightly-different number than the scoring result is a hallucination with direct prescribing consequences. The validator must enforce that *every numeric claim* in the briefing matches a corresponding field in `observed_context.pair_results`, byte-for-byte. The pattern in 4.7 (which validates that "every cited engagement-history fact appears in the engagement history") is too loose for 4.8; the 4.8 pattern is "every numeric value cited must be drawn directly from the structured scoring fields."

  3. **The uncertainty-completeness layer must require both CI and OOD/disagreement disclosure.** A briefing that cites a point estimate without its CI is misleading; a briefing that omits an active OOD flag is dangerous. The validator must enforce that:
     - Every point estimate cited has its CI cited.
     - Any pair with `ood_flag.is_ood = true` is either explicitly described as "outside the model's reliable estimation range" or suppressed entirely from the briefing.
     - Any pair with `disagreement_flag = true` is explicitly described as "the methods underlying the estimate disagree more than usual; treat with extra clinical skepticism" or similar.

  4. **The required-caveats layer must include the conditional-average framing.** The briefing must contain language equivalent to "estimates are for patients similar to this one, not individual guarantees" (the Honest Take's central methodological framing) and "estimates are derived from observational data with target trial emulation" (the methodological-honesty caveat). A briefing that omits these caveats fails validation.

  5. **The high-stakes-fallback semantics differ from 4.7.** A briefing-validator failure in 4.7 falls back to a templated briefing. In 4.8 the same fallback applies, but the templated fallback must render the structured comparison faithfully (per-treatment estimate, CI, cohort size, OOD flag, formulary status, evidence level) rather than narrating in prose. A "less readable templated fallback" that lists facts is acceptable; a templated fallback that produces no comparison at all is not, because the clinician has already opened the chart and is waiting for the system's input.

- **Fix:** Specify the four-layer template inline in the recipe pseudocode:

  ```
  FUNCTION validate_briefing(briefing_parsed, observed_context):
      // Layer 1: schema and length
      // Required fields: headline, comparison_paragraph, per_treatment_summary,
      //   uncertainty_summary, caveats, suggested_clinician_review_points
      // Length caps: headline <= 200 chars, comparison_paragraph <= 1500 chars,
      //   per_treatment_summary entries <= 400 chars each, caveats array
      //   contains at least 3 entries
      IF any required field missing OR over length: REJECT

      // Layer 2: fact grounding
      // Every numeric value cited in the briefing must appear in
      // observed_context.pair_results. Hallucinated numbers (estimates not
      // present in the structured scoring) are rejected.
      FOR each numeric_claim in extract_numeric_claims(briefing_parsed):
          IF numeric_claim NOT IN flatten_numeric_fields(observed_context.pair_results):
              REJECT (hallucinated numeric claim)
      // Every named treatment must appear in observed_context.eligible_pairs.
      FOR each treatment_mention in extract_treatment_mentions(briefing_parsed):
          IF treatment_mention NOT IN [pair.treatment_id FOR pair in observed_context.pair_results]:
              REJECT (treatment not in scope)

      // Layer 3: recommendation language
      // Aggressive pattern list, case-insensitive:
      //   "should prescribe", "we recommend", "is the best choice",
      //   "is the better choice", "recommended treatment", "is preferred",
      //   "the evidence supports starting", "consider initiating",
      //   "clearly the better", "superior choice", "optimal treatment"
      // Plus institution-specific extensions per pharmacy and therapeutics
      // committee. Any match causes REJECT.

      // Layer 4: uncertainty completeness
      FOR each point_estimate cited in briefing_parsed:
          IF its CI is not also cited within 200 chars: REJECT
      IF any pair_result.ood_flag.is_ood AND no OOD acknowledgment text
         present: REJECT
      IF any pair_result.disagreement_flag AND no disagreement-acknowledgment
         text present: REJECT
      IF observational-data caveat not present in caveats: REJECT
      IF conditional-average caveat not present in caveats: REJECT

      RETURN PASS
  ```

  Specify the failure-handling: first failure regenerates with the validator's feedback in the prompt; second failure regenerates with strict_mode = true; third failure falls back to a templated briefing that lists the structured comparison faithfully. The templated fallback is deterministic and always passes validation; the failure event is logged and the per-pair fallback rate is monitored as a CloudWatch metric. Reference the chapter-wide validator pattern from 4.4 Finding 3, 4.5 Finding S3, 4.6 Finding S3 / A7, 4.7 Finding S3.

### Finding S4: De-Identification at LLM Boundary Is Stated but Not Specified for Treatment-Response Context

- **Severity:** MEDIUM
- **Expert:** Security (PHI minimization at LLM boundary)
- **Location:** Step 5 pseudocode `build_briefing_prompt(briefing_context, BRIEFING_OUTPUT_SCHEMA)`; the `briefing_context.patient_summary` field which `build_clinical_summary(scoring.patient_id)` returns "de-identified for the LLM call: condition, key labs, current medications, key trajectory features."
- **Problem:** The chapter pattern from 4.4-4.7 names de-identification at the LLM boundary as a discipline. In 4.8 the de-identification is named in a comment but the meaning of "de-identified" in this context is more contested than in prior recipes:

  1. **A patient with eGFR 64, BMI 34, A1c 8.7, calcium score 240, and a urine ACR-watching nephrologist relationship is highly identifying when the cohort is small.** The clinical detail necessary to produce a useful CATE estimate is precisely the detail that, in combination, identifies an individual patient. The "de-identified" framing is misleading if the LLM call still includes all the clinical features the model used.

  2. **The cohort_features attribute (language, race_ethnicity_self_report, sdoh_cohort, age_band) carried into briefing context is more sensitive in 4.8 than in 4.4-4.7 because the briefing is a clinical-decision-support artifact, not an analytics artifact.** Including race_ethnicity_self_report in a briefing that may shape prescribing has direct fairness implications: clinician-facing materials that mention demographic attributes can introduce bias into the decision the system is trying to inform. The validator should consider stripping demographic attributes from the briefing prompt by default, with explicit opt-in only when the demographic attribute is clinically relevant (e.g., HLA testing for carbamazepine, where ancestry is a pharmacogenomic predictor).

  3. **The "key labs" framing leaves the level of granularity unspecified.** A briefing that includes "A1c trajectory: 7.1 → 7.4 → 8.1 → 8.7 over 14 months" is more identifying than "A1c trajectory: rising over the past year"; the right level of detail depends on what the briefing actually needs. Treatment-effect estimates condition on the patient's covariates; the briefing references them, but the briefing does not need to recite every lab value back to the clinician (the clinician is already looking at the chart). A briefing that says "for a patient with this profile (eGFR 64 declining, BMI 34, calcium score 240, albuminuria)" is reasonable; a briefing that recites "A1c values 7.1, 7.4, 8.1, 8.7 with measurement dates ..." is unnecessary and increases vendor-side logging exposure.

- **Fix:** Add a paragraph in the privacy section specifying the de-identification posture for treatment-response briefings:

  ```
  De-identification at the LLM boundary for treatment-response briefings is
  stricter than for engagement-program briefings (4.4-4.7) because the
  briefing is a clinical-decision-support artifact. The patient_summary
  passed to the LLM:

  - Uses banded clinical features (eGFR_band: "60-69 declining", BMI_band:
    "30-35", A1c_band: "8.0-9.0 increasing") rather than precise lab values.
  - Excludes free-text clinical notes, problem-list entries with timestamps,
    medication-administration records with dates, and any field that uniquely
    identifies the patient against a small cohort.
  - Excludes demographic attributes (race, ethnicity, language, SDOH cohort)
    by default, with explicit opt-in per pharmacy-and-therapeutics-committee
    review when the attribute is clinically relevant (pharmacogenomic
    indications). The committee documents the rationale for each opt-in;
    the validator enforces that opted-out attributes do not appear in
    briefing prompts.
  - Includes the patient's clinical condition, current treatment regimen,
    high-level trajectory, and the structured pair-result fields the
    briefing must surface. No more.

  The patient_id and clinician_id are stripped from the prompt; they are
  re-attached in the persisted briefing record. Bedrock is HIPAA-eligible
  under BAA, but minimum-necessary disclosure remains the architectural
  posture even for compliant services.
  ```

  Reference 4.4-4.7 chapter pattern; the chapter editor should consolidate the de-identification guidance into the chapter-4 preface.

### Finding S5: SDOH-Cohort PHI Sensitivity TODO Should Be Promoted to Main Privacy Paragraph (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Implicit in the `cohort_features` field on prediction-outcome-pairs and decision-records; chapter-wide pattern from 4.4-4.7.
- **Problem:** Same finding as 4.4-4.7. Promote the chapter-wide TODO content into the main privacy paragraph and add the minimum-necessary cohort axes framing. For 4.8 specifically, the per-cohort fairness instrumentation is most-developed, so the consequences of carrying unnecessary cohort attributes are sharper than in prior recipes.
- **Fix:** Promote the TODO into the main paragraph. Reference 4.4-4.7 Finding S4/S5 for the consolidated chapter-4 preface treatment.

### Finding S6: IAM "Never `*`" Stated Without Scoped ARN Examples (Chapter-Wide Pattern, Already TODO'd)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites IAM Permissions row.
- **Problem:** Same finding as 4.1-4.7.
- **Fix:** Inline one or two scoped resource ARN examples for the highest-stakes actions (`bedrock:InvokeModel` on the comparison-briefing model ARN, `dynamodb:UpdateItem` on `decision-records`, `sagemaker:InvokeEndpoint` on the per-pair CATE inference endpoints). Or consolidate into the chapter-4 preface.

---

## Architecture Expert Review

### What's Done Well

- The six-component architecture (treatment catalog, feature pipeline and cohort construction, causal modeling, cohort retrieval and scoring, clinician-facing decision support, feedback and surveillance) is the right shape for the problem. The framing of the treatment catalog as governance-not-engineering extends the program-registry pattern from 4.7 to a richer artifact (treatment_id keyed to RxNorm, comparator_id structure, eligibility predicates, outcome definitions with explicit timing, target patient phenotype, evidence level, formulary status, supply constraints, model-risk tier) that correctly encodes the most-overlooked design decision in the recipe (which comparator to estimate the effect against).
- The seven-stage causal-modeling pipeline (target trial protocol specification, propensity score model, outcome model, CATE estimator ensemble, uncertainty quantification, calibration assessment, governance gate) is the chapter's most operationally rigorous training workflow. The propensity-overlap diagnostic as a hard gate (`IF overlap_check.severe ... suspend further training`) is correctly motivated and is the methodological primitive the rest of the recipe rests on. The estimator-ensemble framing (causal forest + DR-learner + BART, with explicit "different method families") is the right design for surfacing structural uncertainty rather than papering over it.
- The on-demand scoring path with eligible-pair determination, contraindication filtering, per-pair ensemble inference, similar-patient cohort summary (with full-cohort retrieval explicitly named as PHI-leaking), uncertainty composition, OOD flagging, and sensitivity-bound widening is the chapter's most disciplined inference path. The "no eligible pairs" → return structured `scoring_status: no_eligible_pairs` rather than producing a low-confidence estimate is the correct fail-loud behavior for high-stakes inference.
- The clinician-facing decision support with strict no-recommendation validator, regeneration loop with stricter prompts, and templated fallback that always passes is the chapter's most defensive LLM-output path. The "the validator allows the LLM to *describe* the comparison but not to *recommend* a specific treatment, and any text that crosses into recommendation is rewritten or suppressed" framing is the chapter's most pointed validator constraint.
- The feedback-and-surveillance pipeline with prediction-to-outcome matching, calibration drift detection, cohort-stratified performance monitoring, and adverse-event surveillance is the right shape. The post-deployment-surveillance posture as both regulatory expectation (SaMD) and ethical expectation (regardless of regulatory classification) is correctly framed.
- Equity instrumentation explicitly named: calibration parity across cohorts, estimate parity at clinical equipoise, adverse-event parity per cohort. The Obermeyer scenario is named as the canonical concern with explicit framing that "for treatment recommendations specifically, biased predictions can directly cause inferior care."
- Regulatory-aware governance layer: model-risk tier, predetermined change control plan, postmarket surveillance, complaint handling, quality system documentation. The "decide the tier early; retrofitting regulatory compliance onto a system not designed for it is expensive" framing is the operational-veteran insight that the recipe earns its right to make.
- Cross-recipe coordination explicitly addressed: the per-treatment CATE estimate from 4.8 feeds the care plan in 4.9, the predicted adherence from 4.5 feeds 4.8's caveat about adherence assumptions, the care-management enrollment in 4.7 may include monitoring for the chosen treatment's outcomes. The integration-points-need-explicit-design framing is correct.
- The "Where it struggles" section is the chapter's most clinically-honest list: patients outside support, treatments with rapid evolution in clinical use (GLP-1 as the canonical example), outcomes that take years to materialize, treatments with strong covariate-unexplained heterogeneity (antidepressants), regulatory and formulary friction, off-label use, temporal confounding from concurrent care changes, cohort fairness in the response model, clinician override patterns concentrated in specific cohorts, adverse-event surveillance at low base rates. Each item is operationally specific and methodologically grounded.

### Finding A1: `match_outcome` and `compare_calibrations` Conflate Per-Pair CATE Estimates With Single-Arm Observed Outcomes

- **Severity:** HIGH
- **Expert:** Architecture (methodological correctness, the recipe's central methodological discipline)
- **Location:** Step 6 pseudocode `match_outcome(decision_id, run_date)` writes:
  ```
  predicted_outcome:     chosen_prediction.point_estimate,
  predicted_ci:          [chosen_prediction.ci_low, chosen_prediction.ci_high],
  actual_outcome:        actual_outcome.value,
  ```
  And Step 6 pseudocode `run_calibration_drift_detection(run_date)` then calls:
  ```
  current_calibration = compute_calibration_in_groups(recent_pairs)
  ```
  ...where `recent_pairs` is the prediction-outcome-pairs collection from above.
- **Problem:** This is the methodologically central recipe in Chapter 4. The Technology section spends approximately 1,500 words distinguishing:

  - The **individualized treatment effect** (ITE), which is `Y(A) - Y(B)` for a single patient (unobservable for any individual; "fundamentally unobservable: Marcus will get one drug, not all five, and the others are counterfactuals we never see").
  - The **conditional average treatment effect** (CATE), which is `E[Y(A) - Y(B) | X]`, the expected difference within the patient's covariate-defined subpopulation. This is what the CATE-ensemble actually estimates.
  - The patient's **single-arm observed outcome**, which is `Y(A_chosen)` only, the post-decision lab measurement.

  The Honest Take is explicit: *"What we estimate is the conditional average treatment effect given Marcus's covariates. The 'individualized' label is aspirational; the conditional-average framing is what the math delivers. ... A briefing that says 'for you, GLP-1 will lower A1c by 1.4 percentage points' is overstating what the model knows. A briefing that says 'for patients similar to you, the average A1c reduction on GLP-1 was 1.4 percentage points greater than on SGLT2, with this confidence interval and these caveats' is the truth, as best the system can tell. The difference looks small. It is everything."*

  The pseudocode in Step 6 then collapses this distinction. `chosen_prediction.point_estimate` is the per-pair CATE: `E[Y(GLP-1) - Y(SGLT2) | X]`. The sample scoring result has `point_estimate: -0.62`, which is the *difference* between the two arms. `actual_outcome.value` is the patient's single-arm observed A1c change at 90 days: the sample shows `actual_outcome: -1.62`, which is `Y(GLP-1)` only. Marcus did not receive SGLT2; the counterfactual `Y(SGLT2)` for him is forever unobserved.

  The pseudocode writes `predicted_outcome: -0.62` and `actual_outcome: -1.62` into a `prediction-outcome-pairs` row. These are not the same quantity, and there is no combination of single-arm Marcus observations that produces an estimate of the treatment effect for Marcus alone. Then `compute_calibration_in_groups(recent_pairs)` is invoked on the collection of such rows. The function is unspecified in the recipe pseudocode; the Python companion implements it as `mean_actual / mean_predicted`, which for Marcus's row alone produces `-1.62 / -0.62 = 2.61` and reports a "calibration slope" of 2.61. The resulting drift signal is meaningless: the apparent miscalibration reflects the fact that the predicted quantity (treatment effect) and the observed quantity (single-arm outcome) measure different things, not that the model is poorly calibrated.

  The methodological fix in production-grade real-world evidence pipelines uses one of:

  1. **IPTW-based estimation of population CATE on the matched outcome data**: weight each observed outcome by inverse propensity, compute the weighted average outcome per arm, take the difference, compare to the predicted CATE.
  2. **Outcome-model-based comparison**: train a per-arm outcome model from the prediction-outcome rows, compute model-predicted outcomes per arm for the index covariates, take the difference, compare to the predicted CATE.
  3. **Doubly-robust variants** combining (1) and (2).

  None of these match a single observed `Y` to a single predicted `E[Y(A) - Y(B)]`.

  This is the most consequential finding in the review for two reasons:

  1. **The Python companion implements what the architectural pseudocode prescribes.** The Python code review (Finding 3) flagged the same conflation in the Python; the architectural pseudocode is the upstream source. Fixing only the Python and not the architecture leaves the next implementation team to recreate the bug.

  2. **The recipe is the chapter's flagship methodological recipe.** Readers building real treatment-recommender systems will reference this pseudocode. The matching/calibration step is exactly the part where existing observational pipelines go wrong; a recipe that gets the methodology right in The Technology section and then collapses it in the architecture section produces worse outcomes than a recipe that is methodologically silent throughout.

- **Fix:** Two ways to address this honestly without rewriting the entire surveillance pipeline. Either is acceptable; pick one.

  **Option A (lighter fix, honest framing).** Acknowledge the simplification explicitly in the pseudocode. Persist both quantities (per-arm observed outcome AND the predicted CATE), and rename `predicted_outcome` to `predicted_treatment_effect`:

  ```
  DynamoDB.PutItem("prediction-outcome-pairs", {
      pair_id:                       new UUID,
      decision_id:                   decision_id,
      patient_id:                    decision.patient_id,
      scoring_run_id:                decision.scoring_run_id,
      chosen_treatment_id:           decision.chosen_treatment_id,
      chosen_pair_id:                pair.pair_id,
      // The CATE estimate at decision time. This is a treatment-effect
      // *difference*, not a per-arm prediction. It cannot be directly
      // compared to a single observed outcome.
      predicted_treatment_effect:    chosen_prediction.point_estimate,
      predicted_treatment_ci:        [chosen_prediction.ci_low,
                                       chosen_prediction.ci_high],
      // The patient's single-arm observed outcome on the chosen treatment.
      observed_outcome:              actual_outcome.value,
      outcome_status:                "observed",
      ood_flag_at_decision:          chosen_prediction.ood_flag,
      cohort_features:               lookup_cohort_features(decision.patient_id),
      recorded_at:                   run_date
  })
  ```

  And update the surveillance step to compute calibration via aggregate-level CATE re-estimation rather than naive per-row ratio:

  ```
  FUNCTION run_calibration_drift_detection(run_date):
      // Aggregate the prediction-outcome pairs since last run. For each
      // treatment-comparator pair, group accumulated rows by treatment
      // arm using chosen_treatment_id, compute IPTW-weighted mean outcome
      // per arm using the propensity scores from training, take the
      // difference (the surveillance-period CATE estimate), compare to
      // the production-cohort CATE estimate. The comparison is between
      // two CATE estimates (predicted vs surveillance-observed), not
      // between a CATE estimate and a single-arm outcome.
      FOR each pair in CATALOG.list_production_pairs():
          recent_pairs = DynamoDB.Query(...)
          IF len(recent_pairs) < MIN_DRIFT_DETECTION_SAMPLE:
              CONTINUE
          surveillance_cate = compute_iptw_weighted_arm_difference(
              recent_pairs,
              propensity_model = pair.production_propensity_model)
          baseline_cate = pair.production_cohort_cate
          drift_signal = compare_cates(surveillance_cate, baseline_cate)
          ...
  ```

  Add a paragraph to the architecture pattern naming the methodological constraint:

  *"The prediction-outcome-pairs table persists two distinct quantities: the per-pair CATE estimate at decision time (a predicted treatment-effect difference) and the patient's single-arm observed outcome (the post-treatment lab value). These are not directly comparable. Calibration drift detection compares two CATE estimates: the production-cohort baseline CATE versus a surveillance-period CATE re-estimated from the accumulated prediction-outcome pairs using IPTW-weighted per-arm aggregation or an equivalent estimator. Naive comparison of single-arm outcomes to predicted treatment effects produces a misleading 'calibration slope' that conflates the fundamental units of analysis. This is the methodological discipline the rest of the recipe rests on; the surveillance pipeline preserves it rather than collapsing it."*

  **Option B (heavier fix, methodologically correct).** Build the IPTW-weighted aggregation as a first-class component of the surveillance pipeline, with explicit per-cohort weighting and propensity-model-versioning so the surveillance CATE is comparable to the production-cohort CATE. This is closer to what production target-trial-emulation surveillance actually does.

  Option A is sufficient for the recipe as long as the rename and the IPTW-weighted-aggregation block are unambiguous. Option B is closer to honest production discipline. Both fixes also satisfy the Python code review's Finding 3.

### Finding A2: Governance-Review-Tasks Have `sla_review_by` Field but No Auto-Default, Escalation, or Stale-Task Sweep Logic

- **Severity:** HIGH
- **Expert:** Architecture (correctness, operational integrity, regulatory)
- **Location:** Step 3 pseudocode (`evaluate_and_gate_pair_models`), the `sla_review_by: run_date + GOVERNANCE.review_sla_days` field on persisted governance-review-tasks, paired with `status: "pending_review"`. Step 3 prose: *"On approval, the promotion logic moves the new artifacts to the production alias in the model registry and the production pointers in the treatment-comparison-pairs table. On rejection, the training-status is set to evaluation-failed and the team investigates."* No prose for the no-action case.
- **Problem:** The architecture has a critical human-in-the-loop decision point (the governance gate that promotes a trained model artifact from pending_review to production) with no SLA enforcement, no escalation, no default action when the human review is delayed, and no stale-task sweep logic. Three pathological outcomes are possible:

  1. **A new model artifact stuck in `pending_review` indefinitely.** A trained model that has passed calibration and fairness tests but has not been reviewed by the governance committee remains in pending_review while the prior production model continues to serve. If the prior production model has known calibration drift (which is exactly why the new model was trained), patients continue to be scored against the drifted predictions for the duration of the governance latency. The drift can concentrate in protected cohorts; the cohort-stratified surveillance dashboard fires alerts; the alerts pile up while the new model that would address the drift sits unreviewed.

  2. **The pattern concentrates in pairs the governance committee finds most contentious.** Treatment-comparator pairs that are clinically uncontroversial (well-evidenced, low-stakes) get reviewed quickly; pairs that are contentious (clinically debated, high-stakes, with potential cohort-fairness implications) sit longer in the queue. The disparate-promotion-latency dimension is a fairness signal that the chapter-wide equity instrumentation (which monitors prediction outcomes, not governance latency) does not catch.

  3. **The 4.8 governance gate has FDA SaMD postmarket-surveillance implications.** Tier-2-and-above SaMD-classified models require a predetermined change control plan; a pattern of stale governance reviews that delay model updates is a postmarket-surveillance compliance concern, not just an operational concern. The "complaint handling" expectation in the regulatory governance row of the prerequisites table requires that complaints (which can include "the model's prediction in my case was wrong") be addressed within documented timeframes; a stale-review queue that delays response to a documented complaint is a quality-system-regulation finding.

  4. **The 4.7 review's Finding A3 (`human_review_pending` SLA on disenrollment decisions and cross-program transitions) is the direct analog.** In 4.7, the consequence was patients stuck in enrollment limbo. In 4.8, the consequence is models stuck in promotion limbo. The architectural primitive (SLA-with-escalation-with-default) is the same; the per-action defaults differ.

  5. **The pseudocode mentions but does not specify the decision-event Lambda.** Step 3 says: *"The governance review's decision is processed in a separate Lambda triggered by a review-decision event; on approval, the promotion logic moves the new artifacts to the production alias in the model registry and the production pointers in the treatment-comparison-pairs table. On rejection, the training-status is set to evaluation-failed and the team investigates."* The no-action case is silent. A reader implementing the recipe sees the approval and rejection paths and assumes the no-action case is implicit "remain pending"; that is the broken default.

- **Fix:** Architect the SLA-and-escalation pathway explicitly. Add to the architecture pattern:

  ```
  Governance-review SLA and escalation:

  - Pending-review SLA: 14 calendar days for tier-1 (low-risk advisory)
    pairs; 28 calendar days for tier-2 and above (likely SaMD)
    pairs; the longer SLA acknowledges the review depth required for
    SaMD-classified models. SLA is documented per pair in the
    treatment-comparison-pairs registry.

  - Escalation: at 75% of SLA, automated notification to the medical
    director and the responsible methodologist. At 100% of SLA, automated
    escalation to the cross-functional review committee chair with the
    review report attached and a dashboard link to the cohort-stratified
    calibration plots.

  - Default action at SLA expiry: NEVER auto-promote (model promotion
    requires explicit human approval; an unreviewed model is not promoted
    by default). The default action is auto-defer for one additional SLA
    cycle with explicit committee notification. After two consecutive SLA
    expiries, the new model artifact is retired (training-status set to
    "evaluation_expired_unreviewed") and the responsible team is required
    to investigate why the review did not happen. The prior production
    model continues to serve until a new artifact passes review.

  - Cohort-stratified review-latency monitoring: the time from
    evaluation-report-published to governance-decision-recorded is
    tracked per pair and per pair's clinical area. Disparate latencies
    across pairs (e.g., behavioral-health pairs reviewed slower than T2D
    pairs) are surfaced quarterly to the equity-review committee.

  All defaults err toward NOT promoting a new model rather than
  auto-promoting an unreviewed one. The asymmetry mirrors the chapter's
  general "fail loudly rather than silently degrade" posture and matches
  the FDA SaMD predetermined-change-control-plan expectation that
  changes go through documented review.
  ```

  Add the SLA-sweep logic to the pseudocode:

  ```
  FUNCTION sweep_pending_governance_tasks(run_date):
      pending = DynamoDB.Query("governance-review-tasks",
                                  filter = "status = :s",
                                  params = {:s = "pending_review"})
      FOR each task in pending:
          age_days = run_date - task.created_at
          sla_days = SLA[task.tier]
          IF age_days >= 0.75 * sla_days AND NOT task.notified_at_75:
              notify_committee(task, level = "75pct")
              DynamoDB.UpdateItem("governance-review-tasks",
                                    key = task.task_id,
                                    set = "notified_at_75 = :t",
                                    params = {:t = run_date})
          IF age_days >= sla_days AND NOT task.notified_at_100:
              notify_committee(task, level = "100pct_breach")
              DynamoDB.UpdateItem("governance-review-tasks",
                                    key = task.task_id,
                                    set = "notified_at_100 = :t",
                                    params = {:t = run_date})
              emit_metric("governance_sla_breach", value = 1, dimensions = {
                  pair_id:    task.treatment_pair_id,
                  tier:       task.tier
              })
          IF age_days >= 2 * sla_days:
              auto_retire_artifact(task)
              emit_metric("governance_artifact_retired_unreviewed", value = 1,
                          dimensions = { pair_id: task.treatment_pair_id })
  ```

  Reference Recipe 4.7 Finding A3 as the direct chapter sibling pattern; the chapter editor should land both fixes together.

### Finding A3: OOD-Severity Banding (Presentation / Warning / Suppression) Is Discussed in Prose but Not Specified in Pseudocode

- **Severity:** HIGH
- **Expert:** Architecture (clinical safety, the recipe's most distinctive defensive mechanism)
- **Location:** Step 4 pseudocode `compute_ood_flag(patient_features, pair, cohort_summary)` returns `{ is_ood, severity, reasons }`. The Honest Take and "Where it struggles" sections discuss suppression: *"Estimates flagged as extrapolation should be presented with explicit warnings or suppressed entirely."* No threshold or band cutoffs in the pseudocode.
- **Problem:** OOD flagging is the recipe's most distinctive clinical-safety mechanism: the model's prediction is least reliable exactly for patients who are not well-represented in the training data, and presenting a confidently-wrong estimate to a clinician for an OOD patient is the most consequential failure mode this recipe can produce. The Honest Take names this explicitly: *"The OOD flag catches the obvious cases (very high or very low propensity score, large extrapolation distance). The harder cases are patients who are technically in-distribution on each individual feature but in an unusual combination of features. The flag has false negatives, and the briefing's required uncertainty caveats are partial protection at best."*

  Despite the prominence in prose, the pseudocode is silent on how OOD severity translates into presentation behavior. The Python companion picks two thresholds (0.50 for warning, 0.85 for suppression) reasonably, but the architectural recipe should specify the bands rather than leaving them to implementation. Three reasons this matters at HIGH severity:

  1. **Clinical safety.** A patient with an OOD severity of 0.80 should not be presented with a numeric estimate as if it were reliable. A patient with severity 0.50-0.85 should be presented with prominent warnings. A patient with severity below 0.50 can be presented normally. The cutoffs are policy, not implementation, and policy belongs in the architecture.

  2. **Validator coupling.** The validator's uncertainty-completeness layer (Finding S3) requires that any pair with `ood_flag.is_ood = true` be either acknowledged in the briefing or suppressed. The validator and the OOD policy must be co-specified; if the OOD threshold is implementation-defined, the validator cannot enforce a consistent contract.

  3. **The Python code review's Finding 3 partial-recovery argument depends on the suppression band.** When `predicted_outcome` and `actual_outcome` are not directly comparable (Finding A1), one partial protection is to suppress OOD-flagged predictions from the calibration-drift surveillance, so at least the calibration metric is computed only on rows where the model claimed the prediction was reliable. The Python companion does this; the architectural pseudocode should specify the policy.

- **Fix:** Specify the bands in the pseudocode. Add to Step 4 (`compute_ood_flag`) and Step 5 (`generate_briefing`):

  ```
  // OOD severity bands (per chapter-wide policy; per-pair overrides
  // possible for clinically-unusual treatment-comparator pairs):
  //   severity < 0.50: present normally; the briefing's standard
  //                     uncertainty caveats are sufficient.
  //   0.50 <= severity < 0.85: present with explicit OOD warning;
  //                              the briefing must contain "this
  //                              patient is at the edge of the model's
  //                              reliable estimation range" or
  //                              equivalent language.
  //   severity >= 0.85: suppress. The pair is excluded from the
  //                      structured comparison and the briefing
  //                      contains "the model's estimate for this
  //                      treatment-comparator pair is suppressed
  //                      because the patient is outside the range
  //                      where the model produces reliable estimates."
  //                      No numeric estimate is presented.

  IF ood_flag.severity >= OOD_SEVERITY_SUPPRESS_THRESHOLD:
      pair_result.scoring_status = "suppressed_oodflag"
      pair_result.suppress_reason = "ood_severity_above_suppress_threshold"
      // The pair is still persisted in scoring-results for audit, but
      // the briefing renderer and the validator both consume the
      // scoring_status field and exclude suppressed pairs from the
      // numeric comparison.
  ELIF ood_flag.severity >= OOD_SEVERITY_WARNING_THRESHOLD:
      pair_result.scoring_status = "warn_oodflag"
      pair_result.warning_reason = "ood_severity_above_warning_threshold"
  ELSE:
      pair_result.scoring_status = "ok"
  ```

  Add a paragraph to the architecture pattern:

  *"OOD severity bands are policy, not implementation. The chapter-wide defaults (suppress at >= 0.85, warn at >= 0.50, present normally below) are starting points; per-pair overrides are available in the treatment-catalog when clinically warranted (e.g., a pair with a very narrow training-cohort distribution may need a tighter suppress threshold). Suppression is the chapter's most defensive clinical-safety primitive: a numeric estimate that the model itself does not believe is reliable should not be presented to a clinician at the point of care, even with a caveat. The validator (Finding S3) and the OOD bands (this finding) are co-specified; changes to one require corresponding changes to the other."*

  Reference the Python companion's implementation for the working defaults.

### Finding A4: Cohort-Stratified Calibration Drift Threshold Is Referenced but Not Specified

- **Severity:** HIGH
- **Expert:** Architecture (fairness, equity instrumentation, civil-rights implications)
- **Location:** Step 6 pseudocode `run_calibration_drift_detection(run_date)`:
  ```
  IF cohort_drift.severity >= COHORT_DRIFT_ALERT_THRESHOLD:
      DynamoDB.PutItem("surveillance-alerts", {...})
  ```
  The threshold is referenced but not defined; the prose surrounding it does not specify the value or the rationale.
- **Problem:** The recipe's central fairness instrumentation (cohort-stratified calibration drift detection) depends on a threshold that the pseudocode references without defining. The "even if overall calibration is stable, cohort-specific drift may be widening disparities" framing in the pseudocode comment is correct; the threshold is the operational primitive that turns this framing into actionable monitoring.

  Three reasons this matters at HIGH severity:

  1. **The threshold is the difference between catching the Obermeyer scenario and missing it.** The recipe names Obermeyer 2019 as the canonical cautionary tale and explicitly says: *"The Obermeyer-style failure mode is the canonical concern; for treatment recommendations specifically, biased predictions can directly cause inferior care, so the instrumentation has to be built in from the beginning."* A threshold set too high silences the alert; a threshold set too low produces alarm fatigue and the alert is ignored. Either failure mode allows the disparate impact to continue.

  2. **The threshold should be different for different cohort axes.** Calibration drift on the language axis (English versus Spanish patients) may have different acceptable bands than drift on the SDOH axis (food security tiers) or the race-ethnicity axis. Setting a single chapter-wide threshold may miss axis-specific patterns. The architecture should specify per-axis thresholds at minimum, ideally with the framing that the per-axis threshold is set by the cross-functional review committee per pair.

  3. **The fairness threshold is co-specified with the overall drift threshold.** The `DRIFT_ALERT_THRESHOLD` for overall drift is similarly unspecified. If overall drift triggers at one severity and cohort drift at another, the relationship between them matters. A pair where overall drift is low and cohort drift is high is exactly the disparate-impact-without-overall-effect case; the alerting policy must catch this.

- **Fix:** Specify the thresholds in the pseudocode and add a paragraph to the architecture pattern:

  ```
  // Drift thresholds (per chapter-wide policy; per-pair-per-axis
  // overrides set by the cross-functional review committee):
  //   DRIFT_ALERT_THRESHOLD = 0.15
  //     // Overall calibration slope deviation from baseline by 0.15
  //     // or more triggers a drift alert. Tunable based on
  //     // historically-observed slope volatility in stable cohorts.
  //   COHORT_DRIFT_ALERT_THRESHOLD = 0.10
  //     // Per-cohort calibration slope deviation from cohort baseline
  //     // by 0.10 or more triggers a cohort-specific drift alert.
  //     // The cohort threshold is tighter than the overall threshold
  //     // because the equity-relevant disparity can be hidden in
  //     // overall stability.
  //   MIN_DRIFT_DETECTION_SAMPLE = 100 per cohort, 500 overall
  //     // Below these sample sizes, drift detection is suppressed
  //     // and the suppression is logged for cohort under-representation
  //     // surveillance; chronic suppression is itself a fairness signal.
  ```

  Add a paragraph:

  *"Cohort-stratified calibration drift detection is the chapter's primary defense against the Obermeyer-style failure mode. The thresholds are deliberately tighter than the overall drift threshold because disparate impact can hide in overall stability. Per-axis-per-pair thresholds are set by the cross-functional review committee at model promotion, with the default values above as the starting point. Chronic suppression of drift detection in a cohort due to insufficient sample size is itself a surveillance signal: a cohort whose enrollment is structurally low across pairs is a cohort the system is systematically under-serving, and the equity dashboard should surface that pattern at quarterly committee review."*

### Finding A5: Adverse-Event Surveillance Is Discussed in Prose but Not Architected in Pseudocode

- **Severity:** MEDIUM
- **Expert:** Architecture (regulatory, safety)
- **Location:** Architecture description: *"Adverse-event surveillance flags when patients who received the recommended treatment had unexpected adverse events at higher-than-expected rates."* "Where it struggles" final bullet: *"Adverse-event surveillance at low base rates ... requires either a large patient population or a long surveillance window or both."* No pseudocode for the adverse-event surveillance pipeline.
- **Problem:** Adverse-event surveillance is a first-class regulatory expectation for SaMD-classified treatment-recommendation tools (the FDA's postmarket surveillance framework includes adverse-event monitoring as a core requirement; the Sentinel Initiative is named in the Additional Resources for exactly this purpose). The architecture description names it; the "Where it struggles" section names the methodological challenge (low base rates require consortium-scale data); the pseudocode is silent on how the system actually does this.

  Treatment-response-specific reasons this matters:

  1. **The most consequential model failures are unexpected adverse events.** A model that recommends a treatment because the average effect is favorable but misses a heterogeneous-effect subgroup that experiences disproportionate adverse events is exactly the kind of failure that produces real patient harm. Adverse-event surveillance is the architectural primitive that catches this.

  2. **The architecture as drawn does not have a path from adverse-event signals to model retraining or retirement.** The mermaid diagram shows surveillance outputs landing in S3 and powering QuickSight dashboards. The path from "adverse event detected at higher-than-expected rate for cohort X on pair Y" to "model-pair Y is suspended pending review" is not drawn or pseudocoded.

  3. **The surveillance-alert table is named in Step 6 (`surveillance-alerts`) but only for calibration drift and cohort drift.** Adverse-event alerts should also flow through this table with a `alert_type: adverse_event` value and a documented trigger threshold.

- **Fix:** Add a brief subsection to the architecture pattern (200-300 words) and a corresponding pseudocode block:

  ```
  Adverse-event surveillance: For each treatment-comparator pair, the
  surveillance pipeline ingests adverse-event records (from the institution's
  adverse-event reporting system, from claims, from FDA Sentinel-network
  data where the institution participates) and matches them against the
  pool of patients who received the treatment after a model-supported
  decision. A statistical control chart per pair tracks the adverse-event
  rate per million patient-days of treatment exposure; rates exceeding
  the control limits trigger an `adverse_event_alert` in the
  surveillance-alerts table.

  Specifically:

  - Per pair: define the adverse events of interest at model promotion
    (canonical examples: GLP-1 -- pancreatitis, gallbladder disease,
    severe GI events; SGLT2 -- DKA, severe genitourinary infection,
    Fournier's gangrene; sulfonylurea -- severe hypoglycemia
    hospitalization; basal insulin -- severe hypoglycemia hospitalization).
  - Per pair-event: establish the expected rate from training data and
    from published trial data. The expected rate is the surveillance
    baseline.
  - Per surveillance window: compute the observed rate in patients who
    received the treatment within window. Use exact binomial or
    Poisson test for low-base-rate events.
  - Trigger an alert when observed exceeds expected at p < 0.01
    (one-sided), conditional on at least 1000 patient-days of exposure
    in the window.
  - Cohort-stratified version: compute per-cohort observed rates;
    alert if any cohort's rate exceeds expected at p < 0.01 even when
    overall rate is normal.
  - Single-institution surveillance is underpowered for many adverse
    events; consortium surveillance (Sentinel, OHDSI) is the
    methodologically appropriate response and is a recommended
    integration for institutions reaching the surveillance scale.
  ```

  Update Step 6 pseudocode:

  ```
  FUNCTION run_adverse_event_surveillance(run_date):
      FOR each pair in CATALOG.list_production_pairs():
          FOR each event_def in pair.adverse_events_of_interest:
              observed = compute_observed_event_rate(pair, event_def, run_date)
              expected = event_def.expected_rate
              IF len(observed.exposure_patient_days) < MIN_AE_EXPOSURE:
                  CONTINUE  // suppressed; below detection floor
              p = poisson_test(observed, expected)
              IF p < AE_ALERT_P_THRESHOLD:
                  DynamoDB.PutItem("surveillance-alerts", {
                      alert_id:           new UUID,
                      alert_type:         "adverse_event",
                      treatment_pair_id:  pair.pair_id,
                      event_id:           event_def.event_id,
                      observed_rate:      observed.rate,
                      expected_rate:      expected,
                      p_value:            p,
                      triggered_at:       run_date,
                      review_status:      "pending",
                      review_sla_days:    AE_REVIEW_SLA_DAYS
                  })
              // Cohort-stratified
              FOR each cohort_axis_value in observed.per_cohort:
                  ...
  ```

  Reference the Sentinel Initiative and OHDSI as the consortium-scale path; the recipe already cites both in Additional Resources.

### Finding A6: Patient Consent Flow Is Mentioned in Production-Gaps but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (regulatory, ethical, the recipe's most-acknowledged gap)
- **Location:** Why This Isn't Production-Ready: *"Patient consent and shared decision-making. ... Whether and how the patient-facing version is shared, whether the patient's preferences are captured back into the decision record, and whether the patient consents to having their data used for ongoing model improvement are all design decisions that have legal, ethical, and operational implications."* Existing TODO acknowledging the gap in the same section.
- **Problem:** Patient consent is the regulatory and ethical centerpiece of the recipe. The Honest Take frames the system as one that "informs the clinician with individualized treatment-effect estimates" and "the patient consents." The recipe correctly identifies the gap but does not architect the primitives:

  1. **Three distinct consent layers are needed.** Consent to the use of model-derived predictions in clinical care (institutional informed consent at care-relationship establishment; per-pair consent if a pair is high-stakes enough to warrant it). Consent to ongoing data use for model retraining (separable from clinical-care consent; HIPAA permits research use with appropriate authorization). Consent to having model predictions shared with the patient (the patient-facing summary path).

  2. **Consent withdrawal must propagate to retraining cohorts.** A patient who withdraws consent for ongoing data use must be excluded from future training cohorts; the cohort-construction pipeline (Step 1) needs the consent state as a hard filter. The current pseudocode does not show this.

  3. **The consent state is per-(patient, pair) potentially, not just per-patient.** A patient may consent to participation in a T2D second-line therapy CATE model but not in a depression treatment CATE model. The consent state needs the granularity to support per-pair opt-in/opt-out.

  4. **Patient-stated preferences influencing the decision record.** The pseudocode's `decision_payload.shared_decision_indicators` is named but not specified. The captured indicators determine whether the system considers the decision "shared" (which has fairness instrumentation implications: a clinician who never marks decisions as shared is exhibiting a clinician-engagement pattern that should be surfaced to the chief medical officer).

  5. **The right-to-withdraw is regulatorily binding.** HIPAA authorization is revocable; institutional consent is generally revocable; consent for research use is revocable per IRB protocol. The architecture must support the revoke-and-purge flow within the regulatorily-required timeframes.

- **Fix:** Add a brief subsection to the architecture pattern (300-400 words) and a corresponding pseudocode sketch. Mirror the language flagged in 4.5-4.7's existing TODOs but with treatment-response-specific extensions:

  ```
  Patient consent and shared decision-making: Three consent layers are
  captured in a `patient-consent-state` table keyed on patient_id with
  per-layer fields:

  1. `clinical_care_consent`: institutional consent at care-relationship
     establishment; includes consent to model-derived predictions
     informing clinical decisions. Some pairs (high-stakes,
     SaMD-classified, or in regulated areas) require additional per-pair
     consent at first prediction; the catalog flags this.

  2. `ongoing_data_use_consent`: separable from clinical-care consent;
     governs whether the patient's data feeds future training cohorts,
     surveillance pipelines, and consortium pooling. Default is opt-out
     in jurisdictions with stricter privacy frames (e.g., per state
     law); opt-in elsewhere; the catalog flags the per-jurisdiction
     default.

  3. `patient_facing_summary_consent`: governs whether the
     patient-facing version of a briefing is shared with the patient
     when the clinician chooses to share. Default opt-in for most
     populations; opt-out by patient preference.

  Each consent has a recorded effective_date and revoke_date (nullable);
  consent withdrawal is processed within institutional timeframes
  (typically 7-30 days depending on jurisdiction). Withdrawal triggers:

  - Exclusion from future cohort construction (Step 1's `eligibility_query`
    filters out patients without ongoing_data_use_consent).
  - Suppression of patient-facing summaries for that patient.
  - Retention of historical predictions for audit (HIPAA preserves audit
    obligations even on consent withdrawal) but exclusion from retraining
    inputs.

  The decision record's `shared_decision_indicators` field captures
  whether the clinician shared the briefing with the patient, whether
  the patient's stated preference influenced the decision, and which
  preferences (cost, modality, side-effect tolerance, others). The
  fields are structured rather than free-text so the fairness
  instrumentation can stratify decisions by shared-decision flag and
  surface clinician-engagement patterns.
  ```

  Add to Step 1 pseudocode:

  ```
  // In construct_cohort, the candidate_query filter excludes patients
  // who have withdrawn ongoing_data_use_consent. The exclusion is
  // applied at cohort-construction time so retraining cohorts respect
  // consent state at construction; it does not retroactively remove
  // historical patients from prior cohorts.
  ```

  Reference 4.5-4.7 chapter pattern; the chapter editor should consolidate the consent guidance into the chapter-4 preface, with the 4.8-specific multi-layer extension preserved.

### Finding A7: Patient-Facing Summary Validator Is Implied but Not Differentiated From Clinician-Facing Validator

- **Severity:** MEDIUM
- **Expert:** Architecture (clinical safety, patient-experience, reading-level)
- **Location:** Step 5 pseudocode focuses on clinician-facing briefing validation; "Why These Services" mentions: *"Patient-facing summary. When the clinician chooses to share, a patient-facing summary translates the comparison into lay language. ... avoids probabilistic statements that may be misread as guarantees."* No separate validator pseudocode for the patient-facing path.
- **Problem:** The patient-facing path has different validation requirements than the clinician-facing path:

  1. **Reading-level enforcement.** Clinician-facing briefings can use clinical terminology; patient-facing summaries must match the patient's reading level (per Recipe 4.2's pattern). The validator must enforce this.

  2. **Probabilistic-statement avoidance.** Clinician-facing briefings present confidence intervals as "95 percent CI 0.31 to 0.94"; patient-facing summaries should not present numeric probabilities that may be misread as guarantees. The validator must enforce a "no point estimates as percentages" rule for patient summaries.

  3. **Cohort-based phrasing requirement.** Patient summaries must use "patients similar to you" framing rather than "you will" framing. The validator must enforce this.

  4. **Approved-claim-language enforcement.** Patient-facing materials in regulated contexts (especially when the patient is enrolled in research, or the institution operates under FDA postmarket surveillance) require approved claim language. The validator must check against the institution's approved-claim-language list.

  5. **Shared-decision framing.** Patient summaries must include language equivalent to "the final decision is shared between you and your clinician" rather than presenting the system's output as authoritative.

  None of these are addressed in the current pseudocode. The patient-facing path is referenced in Step 5's three Bedrock use cases but the validator is implicitly the same as the clinician-facing one. It should be different.

- **Fix:** Add a separate `validate_patient_summary` function to the pseudocode:

  ```
  FUNCTION validate_patient_summary(summary_parsed, observed_context,
                                       reading_level_target):
      // Layer 1: schema and reading level
      IF reading_level(summary_parsed.text) > reading_level_target: REJECT
      // Layer 2: fact grounding (same as clinician validator)
      ...
      // Layer 3: prohibited language for patient context
      // No probabilistic point estimates as percentages.
      // No "you will [outcome]" framing; require "patients similar
      // to you" or equivalent cohort-based phrasing.
      IF probability_phrasing detected: REJECT
      IF "you will" or analogous phrase detected: REJECT
      // No recommendation language (same patterns as clinician
      // validator, plus extensions).
      ...
      // Layer 4: required content
      IF "shared decision" framing not present: REJECT
      IF approved-claim-language requirements not met: REJECT
      RETURN PASS
  ```

  Reference Recipe 4.2 for the reading-level pattern; reference 4.5-4.7 for the validator-fallback pattern.

### Finding A8: Cohort-Feature Lookup in Per-Pair Loop Repeats Per Patient (Same Pattern as 4.4-4.7)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 6 pseudocode `match_outcome`: `cohort_features = lookup_cohort_features(decision.patient_id)`; per-pair loops in Step 4 implicitly perform the same lookup.
- **Problem:** Same finding as 4.4 Finding 13, 4.5 Finding A4, 4.6 Finding A4, 4.7 Finding A4. With 5-10 eligible pairs per patient and thousands of patients per surveillance run, the gap multiplies redundant DynamoDB reads.
- **Fix:** Hoist the cohort-feature cache out of the per-pair loop; compute once per patient. Reference 4.4-4.7 chapter pattern.

### Finding A9: Multiple Outcomes Per Pair Are Defined but Only Primary Outcome Is Matched in Surveillance

- **Severity:** MEDIUM
- **Expert:** Architecture (surveillance completeness)
- **Location:** Step 1 pseudocode `protocol.outcomes` (multiple outcomes per pair); Step 2 trains outcome models per outcome_def; Step 6 `match_outcome` only reads `pair.primary_outcome`.
- **Problem:** The architecture supports multiple outcomes per pair (primary, secondary, safety) and trains outcome models per outcome. The surveillance pipeline only matches the primary outcome; secondary and safety outcomes are ignored. For T2D second-line therapy, the primary 90-day A1c outcome is necessary but insufficient; weight change at 90 days, hypoglycemia events, GI tolerance, and cardiovascular events at 1-year-plus are all clinically important and trained outcomes that the surveillance pipeline should match. Skipping them means the post-deployment evidence base for the model is narrower than the training evidence base, and adverse-event-via-secondary-outcome patterns are missed.

  Specific consequences:

  1. **A model that predicts A1c well but cardiovascular outcomes poorly will pass calibration drift detection on the primary outcome and quietly produce inferior cardiovascular outcomes.** The 90-day cardiovascular event signal is rare but the cumulative pattern over thousands of patients is detectable; not matching the secondary outcome silences the signal.

  2. **The training-cohort-vs-surveillance-cohort comparison is asymmetric.** Training matches all outcomes; surveillance matches only the primary. The drift detection is therefore looking at one of several relevant signals and may declare stability when secondary-outcome drift is occurring.

- **Fix:** Update `match_outcome` to iterate over all outcomes defined for the pair:

  ```
  FOR each outcome_def in pair.outcomes:
      actual_outcome = compute_actual_outcome(
          patient_id = decision.patient_id,
          outcome_def = outcome_def,
          index_date = decision.decision_recorded_at,
          as_of_date = run_date)
      ...
      DynamoDB.PutItem("prediction-outcome-pairs", {
          ...
          outcome_id:                    outcome_def.outcome_id,
          predicted_treatment_effect:    chosen_prediction_per_outcome[outcome_def.outcome_id].point_estimate,
          ...
      })
  ```

  And update `run_calibration_drift_detection` to compute drift per outcome per pair, with cohort-stratified versions for each. The dashboard surfaces per-outcome drift; alerts fire on any outcome's drift exceeding threshold.

### Finding A10: 30+ Model Artifacts (3 Families × 10-30 Pairs) Without Coordinated Promotion or Rollback Semantics (Same Pattern as 4.4-4.7, Sharper Here)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** "Why These Services" Amazon SageMaker description; existing TODO acknowledging the model-promotion gap.
- **Problem:** Same chapter-wide pattern, sharper here because the model count is materially larger (10-30 treatment-comparator pairs × 3 model families = 30-90 model artifacts per portfolio refresh cycle). The 4.7 review's Finding A5 named the same gap with 15 artifacts; here the multiple is 2-6x.

  Treatment-response-specific reasons:

  1. **The promotion path's clinical-validation suite is more demanding.** The 4.7 promotion required cohort-calibration parity. The 4.8 promotion requires cohort-calibration parity, propensity-overlap re-verification, sensitivity-analysis re-execution, and cross-method-family agreement. The promotion gate is multi-test, and the test ordering and gating logic is non-trivial.

  2. **Model retirement and supersession are first-class.** Some models will, over time, lose calibration faster than retraining can recover, become structurally biased in ways that fairness instrumentation cannot fully correct, or be superseded by a regulatory-cleared alternative. The catalog needs an explicit sunset path: a treatment-comparator pair can be retired from production with explicit rationale, and the retirement triggers downstream cleanup. The Honest Take's "models that quietly degrade in production because nobody is responsible for retiring them" framing is the right operational concern; the architecture should encode the retirement primitive explicitly.

  3. **Rollback timeliness matters more.** A misranked uplift model in 4.7 deferred a program-enrollment decision; a misranked CATE model in 4.8 may have already produced a recommendation that the clinician acted on. Rollback-within-hours rather than rollback-within-days is the operational expectation; the alias-pointer change in SageMaker Model Registry is the right primitive but the runbook needs to be documented.

- **Fix:** Same as 4.4-4.7. Specify the per-pair-per-family promotion path with multi-test gating, rollback-as-alias-change, and a documented retirement workflow. Add 200-300 words to the architecture pattern. Reference Recipe 7.x for full lifecycle treatment.

### Finding A11: `lookup_pair_for_treatment` and `find_prediction_for_treatment` Are Referenced but Undefined; Multi-Pair Mapping for Single Treatment Is Implicit

- **Severity:** MEDIUM
- **Expert:** Architecture (specification gap)
- **Location:** Step 6 pseudocode `match_outcome`: `pair = lookup_pair_for_treatment(decision.chosen_treatment_id)`; `chosen_prediction = find_prediction_for_treatment(decision.predictions_at_decision, decision.chosen_treatment_id)`.
- **Problem:** The chosen_treatment_id from a clinician's decision can correspond to multiple pairs in the scoring run (e.g., GLP-1 was scored against SGLT2, against sulfonylurea, and against basal insulin in three separate pairs). The `lookup_pair_for_treatment` and `find_prediction_for_treatment` functions are referenced as if there is a deterministic mapping; the mapping is actually one-to-many and the architectural choice of which pair to match against is not specified. Three plausible interpretations:

  1. **Match against the most-recently-trained pair containing the chosen treatment as the treatment_id.** Simple but may not be the most clinically relevant.

  2. **Match against the pair the clinician actually compared (i.e., the comparator the clinician chose against).** Requires that the decision_payload capture which comparator the clinician was evaluating; the current pseudocode does not capture this.

  3. **Match against all pairs containing the chosen treatment, producing multiple prediction-outcome rows per decision.** More complete but introduces statistical dependence (the same patient's outcome appearing in multiple rows).

  The choice has consequences for the calibration drift detection and the surveillance pipeline; without specifying it, the implementation will pick one and the recipe's intended methodology will be implementation-defined.

- **Fix:** Specify the mapping. The methodologically-correct choice is option 3 with explicit handling of the per-patient repeated-measures structure (the calibration analysis should account for the repeated measures):

  ```
  FUNCTION match_outcome(decision_id, run_date):
      decision = ...
      // The chosen treatment may be the treatment_id in multiple pairs.
      // Match against all pairs to preserve the full evidence base for
      // surveillance; the calibration analysis handles the repeated-
      // measures structure.
      pairs_for_treatment = lookup_all_pairs_for_treatment(decision.chosen_treatment_id)
      FOR each pair in pairs_for_treatment:
          chosen_prediction = find_prediction_for_pair(
              decision.predictions_at_decision, pair.pair_id)
          IF chosen_prediction is null:
              CONTINUE  // Pair was not in the eligible_pairs at decision time
          ...
          DynamoDB.PutItem("prediction-outcome-pairs", {
              ...
              chosen_pair_id:    pair.pair_id,  // Multiple rows per decision_id
          })
  ```

  Add a paragraph to the architecture pattern naming the repeated-measures structure and the surveillance pipeline's adjustment for it.


---

## Networking Expert Review

### What's Done Well

- VPC endpoint list is comprehensive: *"VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis, Firehose, KMS, CloudWatch Logs, SageMaker Runtime, Step Functions, EventBridge, Glue, Athena, STS, HealthLake, API Gateway."*
- EHR-integration connectivity is explicitly addressed: *"EHR integration typically arrives via PrivateLink, Direct Connect, or the institution's existing private network."* The SMART on FHIR / CDS Hooks integration pattern is correctly framed as the typical EHR-side endpoint.
- Encryption in transit specified throughout (TLS, KMS at rest, customer-managed keys for the highest-sensitivity stores).
- VPC Flow Logs enabled.
- CloudTrail data events on the highest-sensitivity tables.
- API Gateway + Cognito authentication for the on-demand scoring API. Clinician identity flows from the institution's IdP via SAML or OIDC.

### Finding N1: `0.0.0.0/0` Egress Disallow Not Stated Explicitly (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row.
- **Problem:** Same finding as 4.1-4.7. The VPC row says "restrict egress with security groups" but doesn't explicitly disallow `0.0.0.0/0` egress on Lambda subnets.
- **Fix:** Add chapter-wide language: *"No `0.0.0.0/0` egress from any Lambda subnet. NAT egress restricted by security group to specific IP ranges or hostnames (vendor APIs without PrivateLink, EHR-integration endpoints if not via PrivateLink). All other outbound traffic must go through VPC endpoints. SMART on FHIR and CDS Hooks integrations typically arrive via PrivateLink or institution-private networks; document the specific network path per integration."*

### Finding N2: SMART on FHIR / CDS Hooks Integration Credential Posture Not Specified

- **Severity:** MEDIUM
- **Expert:** Networking
- **Location:** Architecture description: *"The EHR integration is typically through a SMART on FHIR app or a CDS Hooks endpoint, both of which the API supports."* "Why This Isn't Production-Ready": *"EHR integration and clinician workflow design."*
- **Problem:** The clinician-facing scoring API is the highest-stakes integration in Chapter 4, and the credential posture is treated at a higher level of abstraction than the chapter's other integrations. SMART on FHIR and CDS Hooks have specific credential and connectivity patterns that the architecture should address:

  1. **SMART on FHIR app launch flow.** The patient-context launch from the EHR carries a fhirContext + patient_id + encounter_id that the scoring API consumes. The OAuth flow uses the EHR's authorization server; the scoring API trusts the EHR's identity assertions; the trust boundary is the EHR's identity provider, not the institution's directly. The credential posture: (a) OAuth client credentials managed in Secrets Manager with KMS encryption and rotation; (b) JWKS endpoint for verifying EHR-issued JWTs; (c) audience/issuer validation against the institution's EHR registration.

  2. **CDS Hooks call.** The EHR makes a synchronous HTTPS POST to the scoring service with patient context; the response contains the briefing card. Authentication is typically mutual TLS or a bearer token issued by the EHR. The credential posture: (a) per-EHR-tenant TLS certificates managed via ACM; (b) HMAC verification on the EHR-signed payload if the EHR supports it; (c) replay-attack protection via timestamp + nonce.

  3. **Treatment-response-specific concerns.** The scoring API is invoked at the point of care with PHI in the request payload; the response contains predictions with treatment-class implications. The credential rotation cadence, the JWKS-cache invalidation policy, and the per-EHR-tenant audit logging are all operationally important.

  The "EHR integration typically arrives via PrivateLink, Direct Connect, or the institution's existing private network" framing is correct at the network-path level. The credential posture is the next level of detail and the architecture should address it.

- **Fix:** Add a paragraph to the architecture description or to the production-gaps section:

  *"EHR integration credential posture: SMART on FHIR launches use OAuth 2.0 with PKCE; the scoring API validates EHR-issued JWTs against the EHR's JWKS endpoint with audience/issuer checks pinned to the institution's EHR registration. CDS Hooks calls use mutual TLS or bearer tokens; per-EHR-tenant TLS certificates are managed via AWS Certificate Manager with documented rotation cadence. Bearer-token verification uses HMAC over the request payload with replay protection via timestamp + nonce. OAuth client secrets and HMAC keys are stored in AWS Secrets Manager with KMS encryption and 90-day rotation; rotation events are logged and the rotation succeeds or fails atomically without service interruption. Per-EHR-tenant audit logging captures the launch context, the requesting clinician, the patient context, and the scoring API response; logs are retained per institutional policy and per BAA terms with the EHR vendor."*

### Finding N3: HealthLake FHIR API Encryption / mTLS Posture Not Specified (Same Pattern as 4.6-4.7)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** "Why These Services" AWS HealthLake paragraph; existing TODO on HealthLake pricing/HIPAA eligibility.
- **Problem:** Same finding as 4.6 N3 and 4.7 N3.
- **Fix:** Same. Add the TLS / mTLS / PrivateLink / Direct Connect language.

---

## Voice Reviewer

### What's Done Well

- The Marcus vignette is the chapter's strongest opening on technical-density grounds. The clinical specificity (A1c 7.1 → 8.7 over 14 months, eGFR 64 declining from 78 over 3 years, calcium score 240, urinary ACR-watching nephrologist, BMI 34), the five-way pharmacological fork with each option's tradeoffs (sulfonylurea: cheap, hypoglycemia, weight gain; DPP-4: modest, weight neutral, expensive; GLP-1: substantial, weight loss, cardiovascular and renal benefit, injectable, GI side effects, supply-constrained; SGLT2: moderate, weight loss, cardioprotective, GU infection, ketoacidosis; basal insulin: most-effective at higher A1c, hypoglycemia, weight gain, injectable, accessible), and the operational specificity (seven-minute slot, manufacturer-rep visit, local formulary, EHR-default, six-week follow-up) make the recipe's central methodological argument concrete before the reader hits the technology section.
- The "fundamentally a causal question, not a correlational one" framing in the opening establishes the methodological stance that the rest of the recipe earns.
- *"What ends up happening, much of the time, is that the PCP picks one of the options based on a combination of factors: their own clinical experience with similar patients, the most recent manufacturer rep visit, what's on the local formulary, what they think the patient will be willing and able to take, what they remember from a recent CME, and, sometimes, what's just easiest to prescribe in the EHR."* This is the chapter's most concrete articulation of the gap between guideline-backed care and what actually happens at the point of care.
- *"And here is the thing that should have been bothering us the entire time: there are *thousands* of patients exactly like Marcus in this plan's panel. ... The data exists. The data is *messy* ... but the data exists. And nobody, in the moment Marcus is sitting in front of his PCP, is consulting that data in a structured way."* The "should have been bothering us" framing is exactly the CC voice the chapter rewards: indignant-but-precise.
- *"The 'individualized' framing is aspirational; the conditional-average framing is what the math can actually deliver."* The single-sentence framing of the methodological core is the recipe's most-quotable line.
- *"The cloud infrastructure is comparatively easy."* Closing of "The Honest Take" first paragraph. Sets the right expectations.
- *"A briefing that says 'for you, GLP-1 will lower A1c by 1.4 percentage points' is overstating what the model knows. A briefing that says 'for patients similar to you, the average A1c reduction on GLP-1 was 1.4 percentage points greater than on SGLT2, with this confidence interval and these caveats' is the truth, as best the system can tell. The difference looks small. It is everything."* The chapter's strongest articulation of why the recipe's methodological discipline matters at the briefing layer.
- *"The validator's no-recommendation-language rule is non-negotiable."* Single line. Clear.
- *"The hardest decision in this work is not whether to ship the model. It is whether to keep it shipped after watching what it actually does."* The closing sentence of the Honest Take is the chapter's strongest closing sentence on voice grounds and makes a case for leadership accountability that the rest of the chapter has been building toward.
- The "Where it struggles" list is the chapter's most clinically-specific, with each item operationally concrete and methodologically grounded. The GLP-1-as-rapid-evolution example, the antidepressant-as-covariate-unexplained-heterogeneity example, the temporal-confounding-from-concurrent-care example, and the cohort-fairness-in-the-response-model example are all earned with specific clinical detail rather than abstract framing.
- The Variations and Extensions section (multi-outcome scoring, subgroup-conditional CATE, federated learning across institutions, adaptive trial integration, patient-reported outcome integration, pharmacogenomic integration, cost-effectiveness extensions, sequencing and trial-and-error optimization, real-world evidence pipeline integration, negative-control and falsification analyses, time-varying treatment effects) is the chapter's most methodologically ambitious. The framing of each as "what you'd build at higher sophistication levels" rather than "additional features" preserves the recipe's discipline about scope.
- Em dash count: 0 (verified). En dash count: 0 (verified). 70/30 vendor balance is clean. Marketing-language scan: two "high-leverage" hits (lines 1506 and 1536); both colloquial uses meaning "leverage point" rather than "leverage AWS services" verb. Acceptable in context. Same chapter pattern as 4.6 and 4.7.

### Finding V1: The Closing "Build the System as If It Will Change Practice" Paragraph Is the Chapter's Strongest Closing; Preserve Verbatim

- **Severity:** N/A (call-out)
- **Expert:** Voice
- **Location:** Honest Take, final paragraph: *"Last point, because it is specific to this use case: treatment response prediction tools, even when they are technically advisory, change clinical practice. ... Build the system as if it will change practice, because it will. Document the intended changes. Monitor for the unintended changes. Be willing to ship the system back to a more limited scope if the unintended changes outweigh the intended ones. The hardest decision in this work is not whether to ship the model. It is whether to keep it shipped after watching what it actually does."*
- **Problem:** Not a finding. Worth flagging to the editor: this paragraph synthesizes the recipe's central tension (advisory tools that change practice) into a clear call-to-action. The closing sentence is the chapter's strongest single line on accountability grounds.
- **Fix:** None. Note for editor: keep verbatim.

### Finding V2: "High-Leverage" Phrasing Twice; Defensible as Colloquial

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Line 1506 (`high-leverage`); line 1536 (`high-leverage covariate`).
- **Problem:** Same colloquial-versus-corporate-marketing tension as 4.6 V3 and 4.7 V3. Both uses are the "leverage point" sense, not the "leverage AWS services" verb. Acceptable in context. If the editor's pass tightens marketing-adjacent terminology generally, these are the candidates.
- **Fix:** Optional. If changed: *"the highest-impact staffing decision"* and *"a high-impact covariate"* preserve the meaning.

---

## Stage 2: Expert Discussion

**Overlap: Architecture A1 (CATE-vs-outcome conflation), Security S3 (validator specification), Architecture A3 (OOD bands).** Three findings touch the recipe's central methodological discipline. A1 is the surveillance pipeline collapsing the CATE-vs-outcome distinction the recipe spends 1,500 words establishing; S3 is the briefing validator that must enforce the same distinction at the LLM-output layer; A3 is the OOD policy that determines whether unreliable predictions reach the validator at all. The three findings are co-dependent: fixing A1 without fixing S3 leaves the methodological honesty intact at surveillance time but compromised at briefing time; fixing S3 without fixing A3 means the validator gets predictions that should never have reached it; fixing A3 without fixing A1 means the OOD-suppressed predictions are still feeding a miscalibrated drift signal. The three should be fixed together, with the methodological-honesty thread running through all three.

**Overlap: Security S1 (identity-boundary), Architecture A2 (governance SLA), Architecture A11 (multi-pair lookup).** Three findings touch the question of "what does the system do when an input is unverified, stale, or ambiguous." S1 is unverified-event-attribution at the decision endpoint; A2 is unenforced-SLA on a stale governance task; A11 is unspecified-mapping when the chosen treatment maps to multiple pairs. The architectural pattern is the same: defensive verification should be explicit in pseudocode rather than implicit, and unspecified semantics propagate into mis-specified or unsafe implementations. Resolution: in all three cases, the pseudocode should show the defensive check or the explicit specification rather than referencing functions whose behavior is left to implementers.

**Overlap: Architecture A5 (adverse-event surveillance) and Architecture A9 (multi-outcome surveillance).** Both are about completeness of the post-deployment evidence base. A5 names the missing primitive (adverse-event surveillance pipeline); A9 names the partial primitive (multi-outcome match in surveillance). The combined fix is a surveillance-completeness paragraph that names both: per-pair matching of all defined outcomes, plus per-pair adverse-event surveillance with cohort stratification, with explicit handling of the repeated-measures structure (Finding A11) when the chosen treatment maps to multiple pairs.

**Overlap: Architecture A6 (consent flow), Security S4 (de-identification at LLM boundary), Architecture A7 (patient-facing validator).** Three findings touch patient-experience and consent. A6 is the consent state itself; S4 is what gets transmitted to the LLM; A7 is what gets returned to the patient. The combined story: the consent state determines whether patient-facing summaries are generated at all; the de-identification posture determines what context the LLM sees; the patient-facing validator determines what the patient receives. The chapter editor should land all three together with a unified patient-experience subsection.

**Overlap: Architecture A10 (model promotion path) and the chapter-wide pattern.** Same as 4.4-4.7, materially sharper here because the artifact count is 30-90 versus 4-15. The chapter editor should consolidate the model-promotion pattern into the chapter-4 preface with the 4.8 multiple noted as a key scaling consideration.

**Cross-recipe overlap: chapter-wide hardening patterns.** Tracking-ID privacy (S2 here, 4.4 Finding 2, 4.5 Finding S2, 4.6 Finding S2, 4.7 Finding S2), validator specification (S3 here, 4.4 Finding 3, 4.5 Finding S3, 4.6 Finding S3 / A7, 4.7 Finding S3), de-identification at LLM boundary (S4 here, chapter pattern from 4.4-4.7), SDOH cohort PHI promotion (S5 here, chapter pattern), IAM ARN scoping (S6 here, chapter pattern), `0.0.0.0/0` egress (N1 here, chapter pattern), identity-boundary checks (S1 here, chapter pattern), governance/human-review SLA (A2 here, 4.7 Finding A3), cohort-feature dedup (A8 here, chapter pattern), model-promotion path (A10 here, chapter pattern). Eleven chapter-wide patterns repeating. The chapter editor should consolidate these into a chapter-4 preface or shared "Chapter 4 production-hardening" section that all recipes reference; each per-recipe review is currently re-litigating the same gaps without resolution propagating across recipes.

Positive cross-recipe progress: the `scoring-results`, `decision-records`, and `prediction-outcome-pairs` "highly inferential PHI" framing is the chapter's sharpest articulation; the regulated-decision audit-trail posture (FDA SaMD vs Cures Act CDS exemption) is the chapter's most rigorous regulatory framing; the multi-source uncertainty quantification (sampling, model, unmeasured-confounding, distributional shift, outcome-definition) is the chapter's most methodologically complete; the "no recommendation language" validator constraint is the chapter's most aggressive LLM-output constraint; the "build the system as if it will change practice" closing is the chapter's most operationally honest call-to-action.

**No major conflicts among experts.** Security and Architecture both want stronger constraints on signal-quality, identity verification, and downstream gating, and these align. Networking is about endpoint topology and credentials. Voice is cosmetic. Priority alignment is clean.

**Priority alignment.** Four HIGH findings (A1 CATE-vs-outcome conflation, A2 governance SLA, A3 OOD bands, A4 cohort-stratified drift threshold) plus one Security HIGH (S1 identity-boundary). The Security S1 elevates from MEDIUM (where it sat in 4.7) to HIGH because the regulated-decision audit-trail posture in 4.8 sharpens the consequences. **5 HIGH findings exceed the > 3 = FAIL threshold.** The recipe verdict is FAIL. The three-or-fewer threshold is structural; even if individual findings are addressable in localized fixes, the cumulative count requires the recipe to land the fixes before final editing.

---

## Stage 3: Synthesized Feedback

## Verdict: FAIL

Zero CRITICAL findings. Five HIGH findings (S1 identity-boundary, A1 CATE-vs-outcome conflation, A2 governance SLA, A3 OOD bands, A4 cohort-stratified drift threshold), exceeding the > 3 = FAIL threshold. Eleven MEDIUM findings. Six LOW findings.

The five HIGH findings are correctness gaps with localized fixes:

- **Finding S1 (identity-boundary checks at `record_decision` and `match_outcome`)** continues the chapter pattern from 4.4-4.7 but elevates to HIGH because the artifact being mutated is closer to a clinical-decision audit record than any prior recipe's artifact. Fix is local to the two consumer functions: validate clinician treatment-relationship, validate chosen_treatment_id against the scoring run's eligible_pairs, validate scoring_run_id consistency, log and metric the violation cases.

- **Finding A1 (CATE-vs-outcome conflation in match_outcome and surveillance)** is the recipe-internal methodological inconsistency: the Technology section spends 1,500 words establishing the CATE-vs-ITE distinction, then the pseudocode in Step 6 collapses it. The Python code review's Finding 3 implements the upstream architectural bug. Fix is to rename `predicted_outcome` to `predicted_treatment_effect`, persist both the CATE estimate and the single-arm observed outcome separately, and replace the naive ratio-of-means slope computation with IPTW-weighted aggregate-CATE re-estimation (or acknowledge the simplification with an explicit "demo-only proxy" comment with the production replacement spec'd).

- **Finding A2 (governance SLA, escalation, default action)** is genuinely 4.8-specific in operational consequence even though the pattern is shared with 4.7's Finding A3. Without SLA enforcement, model artifacts sit indefinitely in pending_review while drifted prior models continue to serve. Fix is per-tier SLA (14 days for tier-1, 28 days for tier-2-and-above), 75%/100% notification escalation, default-deferral after first SLA expiry, default-retirement after second SLA expiry (never auto-promote), per-cohort review-latency monitoring as part of equity instrumentation.

- **Finding A3 (OOD-severity banding)** is the recipe's most distinctive clinical-safety mechanism, named in prose but not specified in pseudocode. The Python companion picks reasonable defaults (0.50 warn, 0.85 suppress); the architectural recipe should specify the bands as policy. Fix is to add band cutoffs to the pseudocode, name suppression as the chapter's most defensive clinical-safety primitive, and co-specify the validator's uncertainty-completeness layer (S3) with the OOD policy.

- **Finding A4 (cohort-stratified calibration drift threshold)** is the recipe's primary defense against the Obermeyer scenario, named in prose but referenced as `COHORT_DRIFT_ALERT_THRESHOLD` without definition. Fix is to specify the threshold (default 0.10, tighter than overall drift's 0.15), name per-axis-per-pair overrides, and document chronic-suppression-via-insufficient-sample as itself a fairness signal.

The teaching arc (the Marcus vignette, the six-component architecture, the seven-stage causal-modeling pipeline with target trial emulation, the per-pair CATE ensemble with multi-source uncertainty quantification, the on-demand scoring path with OOD flagging and similar-patient cohort summary, the strict no-recommendation validator with templated fallback, the prediction-outcome matching, the calibration drift detection with cohort stratification, the regulatory-aware governance layer, the methodological-discipline closing) is solid and publishable. The HIGH findings should be addressed in the main text before the editor finalizes; the chapter-wide hardening MEDIUM and LOW findings are best resolved at chapter level rather than re-litigated per recipe.

The recipe's security and architectural posture continues the chapter-wide trajectory: prior reviewers' chapter-pattern gaps are increasingly resolved in main text (audit-grade CloudTrail data events, customer-managed KMS, SMART on FHIR / CDS Hooks integration framing, regulatory pathway as first-class), and the remaining gaps are explicit TODOs rather than silent omissions. The Honest Take is the chapter's strongest, the Marcus vignette is the chapter's most methodologically grounded opening, and the closing "the hardest decision is whether to keep it shipped after watching what it actually does" is the chapter's most operationally honest call-to-action.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| S1 | HIGH | Security | Step 6 pseudocode `record_decision`, `match_outcome` | No patient-identity-boundary checks against inbound payload; chapter pattern from 4.4-4.7 elevated here because the artifact is a clinical-decision audit record |
| A1 | HIGH | Architecture | Step 6 pseudocode `match_outcome`, `run_calibration_drift_detection` | CATE estimate (treatment-effect difference) and single-arm observed outcome conflated in prediction-outcome-pairs and calibration drift detection; the methodological centerpiece of the recipe is silently broken in surveillance |
| A2 | HIGH | Architecture | Step 3 pseudocode governance-review-tasks | `sla_review_by` field present but no auto-default, escalation, or stale-task sweep logic; model artifacts can stick in pending_review indefinitely while drifted prior models continue serving |
| A3 | HIGH | Architecture | Step 4 / Step 5 pseudocode | OOD severity bands (presentation/warning/suppression) discussed in prose but not specified in pseudocode; the recipe's most distinctive clinical-safety mechanism is implementation-defined |
| A4 | HIGH | Architecture | Step 6 pseudocode `run_calibration_drift_detection` | `COHORT_DRIFT_ALERT_THRESHOLD` referenced but undefined; the recipe's primary defense against the Obermeyer scenario is silent on the operational threshold |
| S2 | MEDIUM | Security | Sample IDs in Expected Results; production-gaps TODO | scoring_run_id, briefing_id, decision_id, pair_id embed patient_id, date, and treatment_class in plain text; treatment-class-in-identifier sharper than prior recipes |
| S3 | MEDIUM | Security | Step 5 pseudocode | Briefing validator's four layers named in comments but not specified; recommendation-language patterns and uncertainty-completeness rules deserve full spec |
| S4 | MEDIUM | Security | Step 5 pseudocode `build_clinical_summary` | De-identification at LLM boundary stated but not specified; banded-features framework needed for treatment-response context |
| A5 | MEDIUM | Architecture | "Why These Services" / Step 6 / "Where it struggles" | Adverse-event surveillance discussed in prose but not architected in pseudocode; first-class regulatory expectation for SaMD-classified tools |
| A6 | MEDIUM | Architecture | Why This Isn't Production-Ready | Patient consent flow mentioned in production-gaps but not architected; three-layer consent model needed for treatment-response context |
| A7 | MEDIUM | Architecture | Step 5 pseudocode | Patient-facing summary validator implied but not differentiated from clinician-facing validator; reading-level, no-probabilistic-statements, cohort-based-phrasing rules needed |
| A8 | MEDIUM | Architecture | Step 6 pseudocode | Cohort-feature lookup repeats per pair; chapter-wide pattern from 4.4-4.7 |
| A9 | MEDIUM | Architecture | Step 6 pseudocode `match_outcome` | Multiple outcomes per pair are defined but only primary outcome is matched in surveillance; secondary and safety outcomes are ignored |
| A10 | MEDIUM | Architecture | "Why These Services" / production-gaps | 30-90 model artifacts (3 families × 10-30 pairs) without coordinated promotion path or rollback semantics; chapter pattern, sharper here |
| A11 | MEDIUM | Architecture | Step 6 pseudocode `match_outcome` | `lookup_pair_for_treatment` referenced as if one-to-one; chosen_treatment_id can map to multiple pairs; mapping not specified |
| N2 | MEDIUM | Networking | Architecture description / production-gaps | SMART on FHIR / CDS Hooks integration credential posture (OAuth, JWKS, mTLS, HMAC, replay protection) not specified |
| S5 | LOW | Security | Production-gaps implicit | SDOH cohort PHI sensitivity should be promoted from chapter-pattern TODO into main Privacy paragraph |
| S6 | LOW | Security | Prerequisites IAM row | "Never *" stated but scoped ARN examples not shown; chapter-wide pattern, already TODO'd |
| N1 | LOW | Networking | Prerequisites VPC row | `0.0.0.0/0` egress disallow not stated explicitly; chapter-wide pattern |
| N3 | LOW | Networking | HealthLake paragraph | FHIR API encryption / mTLS posture not specified for HealthLake; same as 4.6 N3 / 4.7 N3 |
| V1 | N/A | Voice | Honest Take closing paragraph | Not a finding; "build the system as if it will change practice" closing is the chapter's strongest call-to-action; preserve verbatim |
| V2 | LOW | Voice | Lines 1506, 1536 | "High-leverage" phrasing twice; colloquial sense; defensible; optional editor tightening |

---

## Recommended Actions (Priority Order)

1. **Fix the CATE-vs-outcome conflation** (Finding A1) by renaming `predicted_outcome` to `predicted_treatment_effect`, persisting both quantities separately, and replacing the naive ratio-of-means slope computation with IPTW-weighted aggregate-CATE re-estimation (Option A) or by adding a clear "demo-only proxy" comment with the production replacement spec'd alongside (Option B). This is the recipe's central methodological discipline; surveillance must preserve it. Coordinate with the Python companion's Finding 3 fix.

2. **Add patient-identity-boundary checks** (Finding S1) to `record_decision` and `match_outcome`: validate clinician's treatment-relationship to the patient, validate chosen_treatment_id is in scoring run's eligible_pairs, validate scoring_run_id consistency, validate decision-version freshness in match_outcome. Reference 4.4-4.7 chapter pattern; the regulated-decision audit-trail posture earns the HIGH severity.

3. **Architect the governance SLA-and-escalation pathway** (Finding A2): per-tier SLAs (14 days tier-1, 28 days tier-2+), 75%/100% notification escalation, default-deferral after first expiry, default-retirement after second expiry (never auto-promote), per-cohort review-latency monitoring in equity instrumentation. Reference 4.7 Finding A3 as the chapter sibling.

4. **Specify the OOD severity bands in pseudocode** (Finding A3): suppress at >= 0.85, warn at >= 0.50, present normally below; pair-result.scoring_status field; co-specify with validator's uncertainty-completeness layer (S3). Document suppression as the chapter's most defensive clinical-safety primitive.

5. **Specify the cohort-stratified calibration drift threshold** (Finding A4): default 0.10 (tighter than overall drift's 0.15), per-axis-per-pair overrides set by cross-functional review committee, MIN_DRIFT_DETECTION_SAMPLE per cohort with chronic-suppression-as-fairness-signal framing. Reference Obermeyer 2019 as the canonical concern.

6. **Replace string-concatenation tracking IDs with opaque identifiers** (Finding S2): scoring_run_id, briefing_id, decision_id, pair_id should not embed patient_id, date, or treatment_class in plain text. The treatment-class-in-identifier pattern is sharper than prior recipes; document explicitly in the privacy paragraph rather than as a TODO. Update Expected Results samples accordingly. Coordinates with Python companion's Finding 2 fix.

7. **Specify the four-layer briefing validator template** (Finding S3): inline the schema/length, fact-grounding (every numeric claim must trace to scoring result), recommendation-language (eleven-plus aggressive patterns), uncertainty-completeness (CIs required, OOD/disagreement disclosure required, observational-data and conditional-average caveats required), required-caveats layers; specify the failure-handling progression (regenerate with feedback, regenerate strict-mode, templated fallback). Co-specify with OOD bands (A3).

8. **Specify the de-identification posture for treatment-response briefings** (Finding S4): banded clinical features rather than precise lab values; demographic attributes excluded by default with pharmacy-and-therapeutics opt-in; no patient_id or clinician_id in prompts. Reference chapter pattern.

9. **Architect the adverse-event surveillance pipeline** (Finding A5): per-pair adverse-events-of-interest, per-event expected/observed rate computation, exact binomial or Poisson testing, cohort-stratified version, alert-threshold p-value, integration with surveillance-alerts table. Reference Sentinel and OHDSI as the consortium-scale path.

10. **Architect the patient consent flow** (Finding A6): three-layer consent (clinical-care, ongoing-data-use, patient-facing-summary), per-(patient, pair) granularity where appropriate, withdrawal propagation to retraining cohorts, structured shared-decision-indicators on decision records.

11. **Specify the patient-facing summary validator** (Finding A7) separately from the clinician-facing validator: reading-level enforcement (per Recipe 4.2 pattern), no probabilistic point estimates, cohort-based phrasing requirement, approved-claim-language enforcement, shared-decision framing requirement.

12. **Update match_outcome to handle multiple outcomes per pair and multiple pairs per chosen treatment** (Findings A9 and A11): iterate per outcome_def in pair.outcomes; iterate per pair in pairs_for_treatment; preserve repeated-measures structure in surveillance pipeline.

13. **Specify the model-promotion path with cohort-calibration hard gate, multi-test gating, and rollback semantics** (Finding A10): per-pair-per-family promotion granularity with bulk-promotion option, rollback as alias-pointer change, retirement workflow with downstream cleanup. Reference Recipe 7.x.

14. **Specify SMART on FHIR / CDS Hooks integration credential posture** (Finding N2): OAuth client credentials in Secrets Manager with KMS encryption and rotation, JWKS endpoint validation, mTLS or HMAC on CDS Hooks calls, replay protection via timestamp+nonce, per-EHR-tenant audit logging.

15. **Deduplicate cohort-feature lookups by patient** (Finding A8): hoist cache out of per-pair loop. Chapter-wide pattern.

16. **Promote SDOH cohort PHI paragraph from TODO into main Privacy paragraph** (Finding S5); chapter-wide pattern.

17. **Add scoped IAM ARN examples** (Finding S6); chapter-wide pattern, already TODO'd.

18. **Disallow `0.0.0.0/0` egress on Lambda subnets explicitly** (Finding N1); chapter-wide pattern.

19. **Specify FHIR API encryption / mTLS posture for HealthLake** (Finding N3); same as 4.6 N3 / 4.7 N3.

20. **Optional voice polish on "high-leverage"** (Finding V2); not blocking.

---

## Notes for Editor

- The recipe runs long (~21,500 words including the architecture diagram, code blocks, and Expected Results JSON). Length is earned: the Marcus vignette, the methodological depth of The Technology section, the six-component architecture with seven-stage causal-modeling pipeline, the on-demand scoring path with OOD/uncertainty/sensitivity layers, the strict no-recommendation validator with templated fallback, the prediction-outcome matching and calibration drift detection, the regulatory-aware governance layer, the eleven-item Variations and Extensions, and the closing methodological-discipline narrative are all pedagogically essential. Do not trim any of them.

- The recipe carries forward 4.4-4.7 chapter-wide hardening progress and adds treatment-response-specific sharpenings: the `scoring-results` / `decision-records` / `prediction-outcome-pairs` "highly inferential PHI" framing is the chapter's sharpest articulation; the regulated-decision audit-trail posture is the chapter's most rigorous regulatory framing; the multi-source uncertainty quantification is the chapter's most methodologically complete; the "no recommendation language" validator constraint is the chapter's most aggressive LLM-output constraint; the OOD-severity banding (when fully specified per Finding A3) is the chapter's most distinctive clinical-safety primitive. The teaching density is high.

- Several `<!-- TODO -->` markers are present and appropriate: FDA Clinical Decision Support guidance / SaMD framework / Cures Act exemption (these references genuinely change frequently), Bedrock service terms / model eligibility, HealthLake pricing / HIPAA eligibility / FHIR specification version, IAM ARN examples (chapter-wide), SageMaker Real-Time Inference and Batch Transform HIPAA eligibility, validator four-layer specification, contact-cap / counter reconciliation (chapter-wide), tracking-ID privacy (chapter-wide), patient consent flow, cohort-feature dedup, model-promotion path, DLQ coverage, foundation-model-for-EHR citation work, NCQA / aws-samples URL verification, AWS blog and Solutions Library URLs (replace with verified specifics). These are realistic verification tasks and not blockers.

- The Cost Estimate range ($8,000-$25,000/month for a regional system, before staff and EHR integration) is reasonable for the architecture described; the per-line items are realistic. The "before the (substantial) modeling-team and clinical-informatics costs that dominate this recipe" framing is correctly honest.

- The Related Recipes section forward-references future recipes (4.9, 4.10, 7.x, 12.x, 13.x, 14.x, 15.x). Standard practice for the book.

- The Footer link to Recipe 4.9 (Personalized Care Plan Generation) references a future recipe that doesn't exist yet. Standard placeholder.

- All external links are appropriately hedged with TODOs where verification is needed: FDA SaMD / CDS / GMLP guidance pages, EconML / DoWhy / causalml / grf / bcf GitHub repos, Hernán-Robins textbook, Yadlowsky et al. arxiv reference (TODO suggests confirming a stable URL at build time), Obermeyer 2019 (canonical and verified DOI), OHDSI / PCORnet / Sentinel landing pages. The aws-samples repo references are appropriately hedged.

- Cross-recipe coherence with 4.1-4.7 is strong: the patient-feature pipeline (extended with treatment-response-relevant features), the cohort fairness instrumentation (sharpened to civil-rights framing), the validator pattern (extended with no-recommendation rule), the per-treatment CATE estimate as input to 4.9 (care plan synthesis), the integration of 4.5's predicted adherence as a 4.8 caveat, the cross-recipe orchestration framing in production-gaps. The "Where This Sits in the Chapter" framing is accurate and helps the chapter narrative.

- The Python code review (`reviews/chapter04.08-code-review.md`) returned FAIL with one ERROR (four `get_item` calls not wrapped in try/except, demo crashes), three WARNINGs (`_scoring_run_patient` parser bug, `match_outcome` CATE-vs-outcome conflation, `_compute_agreement` ill-defined across pairs with different comparators), six NOTEs. The CATE-vs-outcome conflation (Python WARNING 3) is the same finding as this expert review's HIGH A1; the architectural fix is upstream of the Python implementation. The Python code review and this expert review together name a coordinated set of fixes spanning recipe text, pseudocode, and Python implementation.

- Voice and 70/30 vendor balance: clean. Em dash count: 0 (verified). En dash count: 0 (verified). Recipe is publishable on voice grounds without any additional fixes.

- Marcus is the consistent named patient throughout. No Mr. Garcia / Linda continuity break (the issue flagged in 4.7 review's Finding V2 does not recur here).

- The closing "the hardest decision in this work is not whether to ship the model. It is whether to keep it shipped after watching what it actually does" sentence (Finding V1) is the strongest closing sentence in the chapter and arguably in the book to date. Preserve verbatim.

---

*Review complete. Findings prioritized; FAIL verdict because 5 HIGH findings exceed the > 3 = FAIL threshold. The five HIGH findings are correctness gaps with localized fixes (most of them surfaced in well-specified prose elsewhere in the recipe, requiring the pseudocode to be brought into alignment with the prose); chapter-wide hardening progress continues to mature from prior recipes' TODOs into this recipe's main text. The Marcus vignette and the closing methodological-discipline paragraph make this the chapter's strongest recipe on voice grounds; the seven-stage causal-modeling pipeline with multi-source uncertainty quantification makes it the chapter's strongest on architectural-distinctiveness grounds; the no-recommendation validator with templated fallback makes it the chapter's most defensive on LLM-output grounds. The HIGH findings are surface-level alignment between the prose (which gets the methodology right) and the pseudocode (which collapses parts of it); fixes are local and a re-review pass would be quick.*
