# Expert Review: Recipe 4.10 - Dynamic Treatment Regime Recommendation

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-21
**Recipe file:** `chapter04.10-dynamic-treatment-regime-recommendation.md`

---

## Overall Assessment

This is the methodological cap on Chapter 4 and the recipe with the highest clinical and regulatory stakes in the chapter. It correctly graduates the per-decision pattern from 4.5 through 4.9 (one channel, one piece of content, one provider, one program, one intervention, one care-gap, one enrollment, one treatment, one care plan) into sequential decision-making with off-policy evaluation, where the unit of output is a *policy* over a horizon and the unit of consumption is a recommendation at a decision point that is one step in that policy. The Sara vignette in The Problem is the chapter's most clinically dense opening: 52, stage 3 CKD for four years, T2DM for nine, hypertension since "earlier than 2009," A1c oscillating between 7.4 and 8.9 across three years, eGFR drift from 52 to 41, ACE held during a potassium excursion after SGLT2 initiation, six months off ACE, three months off a medication during her daughter's wedding, GLP-1 added by endocrinology, beta blocker question from cardiology after a chest-tightness episode, a nephrologist gently raising RRT planning, seven medications, four specialists, full-time paralegal work. The "what Sara actually wants is a recommendation that says 'given everything we know about Sara so far, given how she has responded to past adjustments, here is the *sequence* of adjustments'" framing exactly captures the difference between what 4.8 estimates (a single CATE) and what 4.10 estimates (a policy). The "the path matters" pivot is the chapter's clearest articulation of why dynamic treatment regimes are qualitatively different from sequential application of single-decision treatment-effect estimates.

The Technology section is the chapter's deepest single methodological treatment, exceeding even 4.8's. The DTR-as-function-from-state-to-action framing, the RL/policy/trajectory/reward translation, the seven practical primitives (state, action, reward, horizon, decision points, policy, behavior versus target policy), the seven failure-mode catalog (action-space explosion, time-varying confounding, OPE variance, distributional shift across the horizon, reward specification as policy decision, distribution shift over time, safety-and-exploration limits, the non-negotiable clinician role), the six-method survey (Q-learning with backward induction, A-learning, outcome-weighted learning, marginal structural models with IPTW, offline reinforcement learning, deep G-computation, sequential target trial emulation), and the OPE primer (importance sampling, doubly-robust, FQE, per-decision and weighted IS, behavior policy estimation as its own modeling problem) collectively make the section publishable as a standalone primer on production-grade dynamic treatment regimes. The "Where the Field Has Moved" subsection (methodological convergence, tooling maturity, empirical validation against randomized data, FDA SaMD evolution, federated and consortium work, patient-engagement research) honestly characterizes where the literature is and is not. The "Where LLMs Fit (and Don't)" subsection draws the chapter's tightest line: the LLM packages, the LLM does not pick, and the validator's prohibitions are stricter than 4.9's because regime narratives are stricter still ("treatment regimes are the highest-stakes recipe in this chapter, so the line is even more important").

The seven-component architecture (regime catalog, trajectory pipeline, sequential causal modeling, off-policy evaluation, regime serving, clinician-facing decision support, feedback and surveillance) is the right shape. The regime catalog as governance-not-engineering framing extends the catalog pattern from 4.4 through 4.9 to the most consequential artifact in the chapter (the reward function), with the explicit "the reward function is the most consequential and most contested item in the catalog" framing. The trajectory pipeline as the substrate that "powers everything downstream; quality issues here propagate to every model" is the right framing. The multi-method sequential-causal-modeling stack (Q-learning as workhorse, offline RL where state-action space is high-dimensional, A-learning or outcome-weighted learning as cross-validation, MSMs as population-level complement) explicitly states "Disagreements among estimators trigger investigation; agreement is the signal of regime robustness," which is the same triangulation discipline 4.8 established and is more important here because the action space is sequential. The OPE pipeline (DR as workhorse, IS and FQE as complements, cohort-stratified non-negotiable, sensitivity analysis with E-value and Rosenbaum bounds) is the chapter's most disciplined evaluation pipeline. The regime serving layer with eligibility, OOD, policy invocation, similar-trajectory retrieval, and validator-protected narrative is the chapter's most sophisticated inference path. The feedback-and-surveillance layer with regime adherence tracking, outcome surveillance, drift-driven retraining, and cohort-stratified surveillance closes the loop the recipe correctly insists on.

The Honest Take is the chapter's strongest, exceeding 4.8 and 4.9 in both scope and operational specificity. Twelve observations stand out: (1) the gap framing ("the gap between 'the system produces recommendations' and 'the system produces recommendations that meaningfully shape sequential clinical decisions in a way patients and clinicians trust' is the widest" in the chapter); (2) the four-gap diagnosis (alignment, engagement, evaluation, governance) as the canonical reasons production has lagged the methodology; (3) "treating the policy estimation as the work" as the canonical fresh-team trap, with the four overconfidence axes (value, cohort generalization, methodological robustness, deployment posture) and the triangulation discipline; (4) reward-function selection as the most consequential decision in the regime catalog, with the explicit "treat reward selection as a clinical-leadership-and-patient-advisory exercise" directive; (5) over-relying on offline RL where Q-learning would suffice as the second canonical trap, with the "pick the method that fits the problem" discipline; (6) OPE as the load-bearing inference rather than a sanity check ("a team that under-invests in OPE is shipping policies whose deployment risk they cannot accurately characterize"); (7) the four-layer validator with stricter rules ("the line is 'the regime suggests, the clinician decides,' and the validator should enforce that line aggressively"); (8) "invest more heavily in the clinician engagement work before launch, not after" as the explicit second-time-around lesson; (9) the difference between OPE-good and deployment-good with the explicit surveillance-as-confirmation framing; (10) cohort fairness extending past parity into operational follow-through (per-cohort fill rates, program-enrollment success, outcome trajectories, patient-reported satisfaction); (11) the "regime is not a one-time-build artifact" framing with the retraining-cadence-as-deployment discipline; (12) the regulatory-framing closer ("design the surface for review-ability, not just for picking the right answer"). The closing is the chapter's strongest: "the system that gets these right does not produce a wow; it produces a quiet 'this is helpful' that, applied across thousands of decision points across thousands of patients, is the version of decision support that healthcare has been trying to build for decades. Build for that."

That said, four correctness gaps at HIGH severity need attention before publication, plus a chapter-pattern set of MEDIUM and LOW items. (1) The architecture explicitly invokes `treatment_relationship_check` and `consistency_check` in the serving pseudocode and `clinician_id` matching in `record_action_taken`, but the actual policy and the rejection semantics are not specified at the architectural level the chapter pattern from 4.4 through 4.9 has converged on. The chapter's HIGHEST-stakes write paths are the recommendation-API surface and the action-taken consumer; both are weaker on identity boundaries than 4.9, which itself was elevated to HIGH on the same regulatory ground. (2) The cohort disparity alert threshold and the equity-metric definitions are referenced as "non-negotiable" but the operational threshold values, per-axis aggregation, chronic-suppression-as-fairness-signal pattern, and disparity definition are not specified. The Obermeyer scenario the recipe explicitly cites depends on these being calibrated; leaving them implementation-defined silences the alert that catches the disparate-impact case. Same gap as 4.8 Finding A4, 4.9 Finding A2; sharper here because the policy can shape thousands of sequential decisions rather than a single one. (3) Reward-function governance is named in prose as the most consequential decision in the catalog but the architecture does not specify the parallel-evaluation infrastructure, the per-cohort impact-analysis requirement, the weight-change review process, or the audit mechanism for reward-driven unintended optimization. The Honest Take's "treat reward selection as a clinical-leadership-and-patient-advisory exercise" is operationalized as a paragraph in the production-gaps section; it should be a first-class architectural concern. (4) The OOD severity policy is referenced (the regime's risk tier "determines whether OOD-flagged patients still receive a recommendation, receive one with explicit warnings, or are blocked") but the severity bands, the routing policy by risk tier, the suppression-versus-warning thresholds, and the override semantics are unspecified. Same gap as 4.8 Finding A_ on OOD-routing; sharper here because the consequence of acting on an out-of-distribution recommendation is a sequential-decision recommendation that cascades through the patient's care.

Twelve chapter-wide patterns repeat (tracking-ID privacy, validator four-layer specification, SDOH cohort PHI promotion, IAM ARN scoping, identity-boundary checks, governance-task SLA, model-promotion path, cross-recipe orchestration with 4.5 through 4.9, DLQ coverage, EHR/portal integration credential posture, calibration-drift-against-observed-outcomes correctness, multi-language patient narrative architecture). Several are explicitly TODO'd in the recipe text; this review carries them forward at MEDIUM or LOW severity reflecting the chapter editor's eventual consolidation responsibility.

Voice is excellent. Em dash count: 0 (verified). En dash count: 0 (verified). 70/30 vendor balance is maintained. Sara is the consistent named patient throughout; her clinical scenario is internally consistent and clinically accurate (T2DM nine years on second-line therapy with metformin plus GLP-1 plus an eventual SGLT2 question is the canonical KDIGO-and-ADA stepwise-therapy decision; eGFR 41 with declining trajectory and ACR 78 is appropriate KDIGO 3b with albuminuria and is exactly the renal-protection-favoring profile for SGLT2; A1c 8.4 on existing GLP-1 with a path-dependent prior-action sequence is the precise scenario the regime catalog targets; the polypharmacy concern at seven medications is a clinically authentic burden signal). The illustrative recommendation record JSON is internally consistent with Sara's profile. The OPE governance package's DR/IS/FQE values (0.79, 0.77, 0.80 with overlapping CIs and a "high" agreement score) are clinically plausible and consistent with the published offline-RL-for-chronic-disease-management literature. The cohort-stratified results showing white_non_hispanic 0.80, black_non_hispanic 0.74, hispanic 0.76, asian 0.78 with overlapping CIs and "other_or_unknown" flagged as insufficient_data is exactly the disparity pattern the equity instrumentation should surface. The Spanish-language cohort flagged as "wide_ci" is similarly authentic. The Variations and Extensions section (multi-objective regimes with Pareto frontier, patient-driven reward weighting, federated and consortium estimation, real-time RPM-driven decision points, consultation-mode advice, multi-regime composition, RL-informed clinical trial design, causal-discovery-informed state representation, counterfactual explanation surfaces, online value-of-information evaluation, prospective regime-versus-current-care comparison studies) is the chapter's most ambitious; the framing of each as "what you'd build at higher sophistication levels" preserves scope discipline.

Priority breakdown: 0 critical, 4 high, 12 medium, 5 low. **The verdict is FAIL** because 4 HIGH findings exceed the > 3 = FAIL threshold. The four HIGH findings are correctness gaps with localized fixes; most of them surface in well-specified prose elsewhere in the recipe and require the pseudocode and the architecture to be brought into alignment with the prose.

---

## Stage 1: Independent Expert Reviews

## Security Expert Review

### What's Done Well

- BAA called out explicitly with HIPAA-eligibility TODOs for Bedrock, HealthLake, SageMaker components, and any EHR-integration components. Continues the chapter pattern of not pretending the eligibility list is static.
- Customer-managed KMS keys for every PHI store with explicit framing of `recommendation-records`, `regime-catalog`, and `trajectory-metadata` as "the recommendation is a clinical decision-support artifact" and "Recommendation rationale text in DynamoDB is PHI-adjacent; treat with full clinical-record encryption posture." The framing is correctly the sharpest in Chapter 4: a row joining patient_id with the structured recommendation implicitly reveals the active condition list, the path through prior decisions, the recommended sequential treatment, and the patient's place in the regime's eligible cohort.
- CloudTrail data events on `regime-catalog`, `trajectory-metadata`, `recommendation-records`, `regime-versions`, and `surveillance-metrics` tables. Data events on the source-feeds, trajectories, OPE outputs, recommendation archives, and surveillance-outputs S3 buckets. SageMaker training and inference invocations logged. The "audit posture for recommendation artifacts approaches clinical-record audit standards" framing is the recipe-specific sharpening that elevates 4.10 above prior chapter recipes.
- Bedrock paragraph confirms HIPAA eligibility under BAA. The structured-then-narrative direction is enforced architecturally (Steps 1-5G build the recommendation record deterministically; Step 5H only renders narrative on top), so the prompt context is structured fields rather than raw clinical text.
- The validator's four conceptual layers (schema and length, fact grounding, prohibited-language patterns, required content) are named with regime-specific stricter rules ("no recommendation language for treatments not in the regime's action catalog, no probabilistic claims framed as guarantees, no policy-as-directive framing"; "uncertainty disclosure, regime-version reference, override-encouragement framing for the clinician narrative; care-plan-linkage and contact-for-questions for the patient narrative").
- Patient consent posture is named in production-gaps with the correct multi-layer framing and the "your care recommendations are informed by your own past care and outcomes and by the patterns observed in similar patients' care; we use this information with care and you can opt out" patient-language framing. Consent revocation pathway named (revoking patient contributions to training data, retraining without their data, removing them from similar-trajectory retrieval pools).
- Operational privacy in trajectory storage and similar-trajectory retrieval is explicitly elevated above engagement-data privacy ("apply tighter controls than for engagement data: narrower IAM read scopes, separate-table partitioning by sensitivity tier, additional CloudTrail data event capture, and a documented minimum-necessary access policy"). The k-anonymity threshold for similar-trajectory retrieval is named as regime-specific.
- Regulatory posture is set early with explicit framing of dynamic-treatment-regime tools as "harder to keep outside the SaMD definition than single-decision support" and the predetermined-change-control-plan, post-deployment-surveillance, and clinical-leadership-and-regulatory-legal-review-as-recurring-meeting discipline.

### Finding S1: `serve_recommendation` and `record_action_taken` Identity-Boundary Checks Referenced in Comments but Underspecified

- **Severity:** HIGH
- **Expert:** Security (PHI integrity boundary, authorization, regulatory)
- **Location:** Step 5 pseudocode `serve_recommendation`, the comment block:
  ```
  // Step 5B: identity-boundary checks. The recommendation API is
  // called by an authenticated EHR session. Validate that the
  // calling clinician has a treatment relationship to the patient,
  // that the patient is an active member of the regime's eligible
  // population, and that the decision_point_id is consistent with
  // the patient's trajectory state.
  treatment_relationship_check(calling_clinician_id, patient_id)
  consistency_check(decision_point_id, trajectory_metadata)
  ```
  And Step 6 pseudocode `record_action_taken`:
  ```
  // Identity-boundary check: the clinician_id must match the
  // session that received the recommendation; mismatch is logged
  // and rejected.
  IF action_taken_payload.clinician_id != rec.served_to_clinician_id:
      log_security_violation(...)
      REJECT
  ```
  The Python code review's Finding 6 documents that the implementation skips the action-taken identity check entirely (no `served_to_clinician_id` field is captured at serve time, and `record_action_taken` does not consult `action_taken_payload.get("clinician_id")` against any session-bound identity).
- **Problem:** The chapter pattern from 4.4 through 4.9 has converged on a structured identity-boundary-check specification that includes the rejection semantics, the metric emission, and the log-on-violation pattern. Recipe 4.10 acknowledges the pattern in two function-level comments but specifies neither the policy nor the rejection semantics. The consequences here are sharper than in any prior recipe because the artifact being mutated and the artifact being served is, by the recipe's own framing, "decision support that materially shapes a sequential clinical decisions" and is "harder to keep outside the SaMD definition than single-decision support":

  1. **`serve_recommendation` is the chapter's most security-sensitive read path.** It returns to the calling EHR session a recommendation_record containing the recommended action, the alternative actions with values and CIs, the similar-trajectory cohort summary, the OOD flag, and the validator-protected narrative. A serve call arriving with mismatched metadata (a clinician with no treatment relationship to the patient, a `decision_point_id` that does not exist in the patient's trajectory, a `regime_id` for a regime the patient is not active in) would silently surface a real-patient sequential-treatment recommendation to a real clinician on behalf of the wrong patient. The downstream blast radius is the recommended action propagating into the EHR's clinical inbox, into the e-prescribing system if the clinician acts on the surface, into the patient portal if the clinician shares with the patient, and into the audit trail as if it were a legitimate decision-support event.

  2. **`record_action_taken` is the chapter's most security-sensitive write path.** It receives `action_taken_payload` over the API Gateway path, then writes to `recommendation-records` and (per Finding A4 below) appends to the patient's trajectory record that powers the next training cycle. A misrouted action-taken event (a system-emitted action event for the wrong patient, an authorization-bypass attempt that submits a `recommendation_id` the calling clinician should not have access to, an `action_id` that is not in the regime's action catalog) would silently mutate the wrong recommendation record, contaminate the trajectory store with wrong-patient-wrong-action data, and produce a Kinesis `action_taken` event that flows into surveillance. The trajectory contamination is structurally worse than the engagement-data contamination of 4.4-4.7 because the trajectory feeds the next regime training cycle: a poisoned trajectory step shifts the importance weights and the Q model targets in the next training run, producing a regime that subtly tilts toward the contaminating action. The poisoning is not a one-shot harm but a propagating one.

  3. **The Cures Act CDS exemption argument depends on the identity boundary being specified.** The exemption requires the clinician to "independently review the basis of the recommendation"; the basis must be associated with the right patient, and the recommendation served to the clinician must be the one the system intended to serve. A system that lets a clinician's session attach to the wrong patient's recommendation, or lets an action-taken event attach to the wrong recommendation, breaks the exemption argument. Recipe 4.8's review elevated this concern to HIGH on the same regulatory ground; 4.9 inherited the posture; 4.10 carries it forward with the additional weight that sequential decisions cascade.

  4. **The `served_to_clinician_id` field is not in the recommendation record schema.** The pseudocode's `record_action_taken` references `rec.served_to_clinician_id`, but `serve_recommendation` does not capture or persist that field. The implementation cannot enforce the identity check the pseudocode names because the data the check needs is not collected at serve time. This is a schema-level gap that compounds with the missing implementation.

- **Fix:** Specify the identity-check policy and the rejection semantics at the architectural level the chapter has converged on. In `serve_recommendation`, immediately after the regime lookup:

  ```
  regime = DynamoDB.GetItem("regime-catalog", regime_id, latest_version = true)
  IF regime is null:
      LOG("regime-catalog lookup failed", regime_id=regime_id)
      RETURN error("regime_not_found")

  // Validate the calling clinician's authorization.
  IF NOT clinician_has_treatment_relationship(calling_clinician_id, patient_id):
      LOG("calling clinician lacks treatment relationship",
          clinician = calling_clinician_id, patient = patient_id,
          regime_id = regime_id)
      emit_metric("recommendation_authorization_violation", value = 1)
      RETURN error("clinician_not_authorized")

  // Validate that the patient is currently an active member of the
  // regime's eligible population at this decision point.
  trajectory_metadata = DynamoDB.GetItem("trajectory-metadata",
                                          patient_id, regime_id)
  IF trajectory_metadata is null OR
     trajectory_metadata.censoring_status == "censored":
      LOG("patient not active in regime", patient = patient_id,
          regime = regime_id)
      emit_metric("recommendation_patient_inactive", value = 1)
      RETURN error("patient_not_active_in_regime")

  // Validate the decision_point_id is the next-expected one for this
  // patient's trajectory state. Mismatch indicates a stale request,
  // a replay, or a wrong-decision-point integration bug.
  expected_dp_index = trajectory_metadata.last_decision_point_index + 1
  IF parse_decision_point_index(decision_point_id) != expected_dp_index:
      LOG("decision_point_id inconsistent with trajectory state",
          submitted = decision_point_id,
          expected_index = expected_dp_index)
      emit_metric("recommendation_decision_point_mismatch", value = 1)
      RETURN error("decision_point_inconsistent")
  ```

  And persist `served_to_clinician_id` and `served_at` on the recommendation record so the action-taken consumer has the data to enforce its identity check. In `record_action_taken`, immediately after the recommendation lookup:

  ```
  rec = DynamoDB.GetItem("recommendation-records", recommendation_id)
  IF rec is null:
      LOG("recommendation-records lookup failed",
          recommendation_id = recommendation_id)
      RETURN error("recommendation_not_found")

  // Identity-boundary check: the action-taking clinician must be the
  // same clinician who received the recommendation. Mismatch is logged
  // and rejected; this prevents action-taken events from one clinician
  // session attaching to a recommendation served to a different
  // session.
  IF action_taken_payload.clinician_id != rec.served_to_clinician_id:
      LOG("action_taken clinician does not match served_to_clinician_id",
          submitted = action_taken_payload.clinician_id,
          stored    = rec.served_to_clinician_id,
          recommendation_id = recommendation_id)
      emit_metric("action_taken_identity_mismatch", value = 1)
      RETURN error("identity_boundary_violation")

  // Validate that the action_id is in the recommendation's known
  // action set (recommended_action plus alternatives), or is
  // explicitly out_of_catalog. Reject unknown actions.
  known_action_ids = [rec.recommended_action] +
                     [a.action_id FOR a in rec.alternative_actions]
  IF action_taken_payload.action_id NOT IN known_action_ids AND
     classify_action(action_taken_payload.action_id, rec) != "out_of_catalog":
      LOG("action_taken action_id not in recommendation scope",
          action = action_taken_payload.action_id,
          recommendation_id = recommendation_id)
      emit_metric("action_taken_action_mismatch", value = 1)
      RETURN error("action_not_in_scope")

  // Idempotency: a replayed action-taken event from a reprocessing
  // job should not double-mutate the recommendation record or
  // double-append to the trajectory.
  IF rec.action_taken is not null:
      LOG("action_taken already recorded; treating as replay",
          recommendation_id = recommendation_id)
      RETURN { status: "already_recorded" }
  ```

  Reference Recipe 4.4 Finding S1, 4.5 Finding S1, 4.6 Finding S1, 4.7 Finding S1, 4.8 Finding S1, 4.9 Finding S1 as the chapter-wide pattern; the chapter editor should consolidate identity-check guidance into a chapter-4 preface that all recipes reference. For 4.10 specifically, the regulated-decision audit-trail posture and the trajectory-poisoning-as-propagating-harm consequence earn the HIGH severity rather than the MEDIUM of earlier chapters' recipes.

### Finding S2: Recommendation-ID, Decision-Point-ID, Trajectory-ID Tracking-ID Privacy (Chapter-Wide Pattern; Already TODO'd)

- **Severity:** MEDIUM
- **Expert:** Security (PHI minimization)
- **Location:** Sample recommendation record `"recommendation_id": "rec-2026-04-22-pat-009315-dp-014"`, `"decision_point_id": "dp-2026-04-22-pat-009315-014"`, `"regime_version": "3.2.1"`; existing TODO in production-gaps section: *"replace the string-concatenation recommendation_id, decision_point_id, trajectory_id with opaque, non-reversible identifiers (UUID or HMAC-SHA256 over the composite with a per-environment secret). Trajectory IDs that encode patient identifiers or decision sequences are PHI leakage in URLs, logs, and event payloads."*
- **Problem:** Same finding as 4.4 Finding 2, 4.5 Finding S2, 4.6 Finding S2, 4.7 Finding S2, 4.8 Finding S2, 4.9 Finding S2. The recipe acknowledges the gap with a TODO that mirrors the chapter-wide fix language.

  Regime-specific sharpening: the recommendation_id and decision_point_id together encode the date, the patient_id, and the decision-point index in plain text. The decision-point index reveals the patient's place in the regime's horizon (decision point 14 means this is the patient's 14th regime evaluation, which is itself inferential about the duration and stability of the patient's chronic condition). The combination is more sensitive than any prior recipe's identifier because the artifact is, again, decision-support-equivalent for SaMD purposes. The Python code review's positive note that the demo's `_make_*_id` helpers use UUID-based opaque identifiers is good; the architectural pseudocode and the Expected Results sample identifiers should match the Python rather than the Python being silently more careful than the recipe text.

- **Fix:** Same as 4.4-4.9. Replace string-concatenation IDs with opaque UUID or HMAC-SHA256 over the composite with a per-environment secret. Update the Expected Results sample identifiers accordingly.

### Finding S3: Validator Four-Layer Specification Underspecified for Regime-Narrative Stricter Rules

- **Severity:** MEDIUM
- **Expert:** Security (regulatory, hallucination guardrails)
- **Location:** Step 5H pseudocode comment:
  ```
  // The validator is layered the same way as in Recipe 4.9:
  // schema and length, fact grounding (every clinical claim
  // traces to the recommendation_record or the regime catalog),
  // prohibited-language patterns, required content (uncertainty
  // disclosure, regime version, override-encouragement,
  // similar-trajectory reference). Failed validations
  // regenerate or fall back to a templated narrative.
  ```
- **Problem:** Same chapter-wide pattern as 4.4 Finding 3, 4.5 Finding S3, 4.6 Finding S3 / A7, 4.7 Finding S3, 4.8 Finding S3, 4.9 Finding S3. The recipe names the four layers in a comment block and states the regime-specific stricter rules in prose ("no policy-as-directive framing, no recommendation language that elides the alternatives, no probabilistic claims framed as guarantees, explicit override-encouragement framing"), but does not specify the layer-by-layer enforcement at the level of detail the chapter has converged on.

  Regime-specific sharpening:

  1. **The prohibited-language layer is the chapter's strictest.** A regime narrative for Sara that says "the regime requires SGLT2" or "you should add an SGLT2" or "the system has determined SGLT2 is the right choice" each crosses the line; the validator must reject all of them. The pattern set should be larger than 4.9's (the Python companion's pattern set is reasonable: `\bguaranteed\b`, `\b100%\s+(?:effective|safe)\b`, `\bdefinitely will\b`, `\bnever fail`, `\bmust\s+(?:start|use|prescribe|add|stop)\b`, `\bthe regime requires\b`, `\byou are required to\b`); the architectural pseudocode should match.

  2. **The required-content layer must include the policy-versus-directive framing explicitly.** The clinician narrative must contain language equivalent to "the regime suggests, the clinician decides" (the Honest Take's central operational framing) and an explicit override-encouragement clause. A narrative that omits these fails validation. Override-encouragement is non-negotiable because the regime's deployment posture depends on clinicians overriding when their judgment differs.

  3. **The fact-grounding layer must enforce that every numeric value cited matches the structured recommendation record.** The narrative cites the recommended action's value (0.78), the CI (0.71-0.84), the alternatives' values, and the OOD score; each numeric must trace byte-for-byte to a corresponding field. Same posture as 4.8 Finding S3 (which the chapter editor flagged as the canonical fact-grounding pattern for clinical-decision-support narratives).

  4. **The patient-facing narrative is harder than the clinician-facing one.** The Honest Take is explicit: "explaining a policy to a patient without inducing either learned helplessness ('the algorithm picked, just do it') or rejection ('the algorithm doesn't know me, I'll do my own thing') requires careful copywriting, patient-advisory review, and iterative testing." The validator must enforce the path-dependence framing ("this is the next step given how things have gone") and the uncertainty disclosure in patient-friendly language. Reading-level enforcement (per 4.9 Finding S3 and Recipe 4.2 patterns) belongs here too.

  5. **The templated fallback must convey the structured comparison faithfully even when narrative generation falls back.** The Honest Take's "a clean templated narrative is better than a polished LLM narrative the validator was uncertain about" applies; the templated fallback is a deterministic listing of the recommendation, the alternatives with values and CIs, the OOD flag, the regime version, and the override-encouragement framing.

- **Fix:** Specify the four-layer template inline in Step 5 pseudocode. Reference the language from 4.4-4.9 chapter pattern. The regime-specific extensions (the prohibited-language pattern set, the policy-versus-directive required-content rule, the path-dependence framing for patient narratives) belong in main text rather than as comments because regime narratives are the chapter's strictest LLM-output surface.

### Finding S4: SDOH-Cohort PHI Sensitivity TODO Should Be Promoted to Main Privacy Paragraph (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Implicit in `cohort_features` carried in OPE stratification, surveillance metric dimensions, and similar-trajectory retrieval; chapter-wide pattern from 4.4-4.9.
- **Problem:** Same finding as 4.4-4.9. Promote into main privacy paragraph. For 4.10, the per-cohort fairness instrumentation (regime value parity, regime adherence parity, OOD-rate parity, outcome-trajectory parity) is most-developed in the chapter, so carrying unnecessary cohort attributes amplifies the disclosure risk. The trajectory-store separate-table-partitioning-by-sensitivity-tier framing in production-gaps already names the elevated posture; the SDOH-cohort minimum-necessary discussion should be in the main paragraph rather than implicit.
- **Fix:** Promote the TODO into the main paragraph. Reference 4.4-4.9 chapter pattern.

### Finding S5: IAM "Never `*`" Stated Without Scoped ARN Examples (Chapter-Wide Pattern, Already TODO'd)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites IAM Permissions row.
- **Problem:** Same finding as 4.1-4.9. Already TODO'd.
- **Fix:** Inline one or two scoped resource ARN examples for the highest-stakes actions (`bedrock:InvokeModel` on the per-audience model ARNs, `dynamodb:UpdateItem` on `recommendation-records` and `regime-catalog`, `sagemaker:InvokeEndpoint` on the per-regime serving endpoints). Or consolidate into the chapter-4 preface.

---

## Architecture Expert Review

### What's Done Well

- The seven-component architecture (regime catalog, trajectory pipeline, sequential causal modeling, OPE, regime serving, clinician-facing decision support, feedback and surveillance) is the right shape. The framing of regime catalog as governance-not-engineering with the explicit "the reward function is the most consequential and most contested item in the catalog" extends the catalog pattern from 4.4-4.9 to its highest-stakes form in the chapter.
- The DTR-as-policy-not-treatment framing is enforced architecturally: the policy is a function from state to action, the trajectory is the data substrate, the OPE is the gate before deployment, the surveillance closes the loop. The recipe correctly insists on triangulation (Q-learning plus offline RL plus A-learning; DR-OPE plus IS-OPE plus FQE; cohort-stratified plus overall; sensitivity analysis plus point estimates).
- The trajectory pipeline's explicit treatment of decision-point identification, point-in-time-correct state construction, action labeling with out-of-catalog tracking, reward computation, and censoring handling with IPCW weights is the chapter's most rigorous data-substrate construction. The "trajectories with high out-of-catalog rates are surfaced to the catalog-governance committee as a signal that the catalog may need expansion" pattern is the right operational signal.
- The behavior-policy estimation is correctly framed as a model in its own right that requires validation, calibration, and monitoring. The cohort-stratified ECE check (with `BEHAVIOR_POLICY_COHORT_ECE_THRESHOLD` blocking failure) is the right discipline; the recipe explicitly notes "OPE on a regime trained on miscalibrated importance weights produces misleading equity assessments."
- The multi-method sequential-causal-modeling stack (Q-learning workhorse, offline RL where high-dimensional, A-learning or outcome-weighted learning as cross-validation, MSMs as population-level complement) with the "agreement among methods is the signal of regime robustness" framing is the chapter's most disciplined estimation pipeline.
- The OPE pipeline (DR as workhorse, IS and FQE as complements, cohort-stratified non-negotiable, sensitivity analysis with E-value and Rosenbaum bounds) with explicit bootstrap CI generation and the "candidate regime with a CI that does not exclude the prior regime's value is not promoted" governance gate is the chapter's most disciplined evaluation pipeline.
- The regime-serving layer's eligibility check with explicit "not_eligible" response and failing-predicate naming (rather than silent no-recommendation), the OOD detection, the policy invocation, the similar-trajectory retrieval with k-anonymity, the contraindication checks, and the four-layer-validator-protected narrative collectively extend the 4.8 single-decision pattern to sequential-decision territory with the appropriate stricter rules.
- Cross-recipe orchestration with 4.5 through 4.9 is named in production-gaps with the right framing ("the integration points must be reliable, idempotent, and consistent. Document the integration patterns and the failure-mode handling.").
- Equity instrumentation explicitly named as built-in, with regime value parity, regime adherence parity, OOD-rate parity, and outcome-trajectory parity. The Obermeyer pattern is correctly extended to dynamic treatment regimes: "a regime that was estimated on data reflecting historical access and prescribing disparities will encode those disparities into the recommended actions."
- The "this is the synthesis-extension recipe of Chapter 4" framing earns its position. Prior recipes pick one decision; 4.10 picks the sequence. The "LLM stops being a packaging layer and starts being structurally load-bearing" warning from 4.9 carries forward with the regime-narrative-stricter-rules framing.
- The "Why This Isn't Production-Ready" section is the chapter's most thorough, with twelve named gaps spanning methodology validation, behavior-policy validation depth, reward-function governance, patient consent, operational privacy in trajectory storage, regulatory framework, idempotency and retry, cross-recipe orchestration, regime deprecation, cost-aware narrative generation, operational dashboards and runbooks. The breadth honestly tells the reader how much sits between the recipe and a production deployment.

### Finding A1: Cohort Disparity Alert Threshold and Equity Metric Definitions Are Referenced as Non-Negotiable but Undefined

- **Severity:** HIGH
- **Expert:** Architecture (fairness, civil-rights implications)
- **Location:** Step 6D pseudocode `run_surveillance`:
  ```
  cohort_metrics = compute_cohort_stratified_metrics(regime_id, surveillance_window,
                                                      cohort_axes = COHORT_AXES)
  FOR each axis, axis_metrics in cohort_metrics:
      IF axis_metrics.disparity >= COHORT_DISPARITY_ALERT_THRESHOLD:
          DynamoDB.PutItem("surveillance-alerts", {...})
  ```
  Plus the architectural prose: *"Regime value parity across cohorts, regime adherence parity, OOD-rate parity, outcome-trajectory parity. Each axis is monitored, with thresholds that trigger committee review when crossed."*
- **Problem:** The recipe's central fairness instrumentation depends on a threshold and a set of metrics that the pseudocode references without defining. The architecture is silent on:

  1. **What the threshold value should be.** The recipe says the instrumentation is "non-negotiable" but does not specify the operational value at which an alert fires. A threshold set too high silences the alert; a threshold set too low produces alarm fatigue. Either failure mode allows disparate impact to continue unnoticed. The Python code review's Finding 1 documents that the demo's threshold (`COHORT_DISPARITY_ALERT_THRESHOLD = 0.10`) is implementation-defined, and the demo additionally fails to populate `cohort_features` on recommendation records so the disparity is always zero. Both problems originate in the architecture's silence on the fairness primitives.

  2. **How each metric is computed.** Regime value parity could be operationalized as the ratio of mean DR-OPE value between the highest-cohort and lowest-cohort groups, or as the difference in CI overlap, or as the fraction of cohorts whose CI excludes the overall point estimate. Regime adherence parity could be operationalized as the ratio of follow-recommendation rates, or as the fraction of cohorts below a minimum follow rate. OOD-rate parity could be the ratio of OOD-flag rates between cohorts, or the absolute OOD-rate gap. Each operationalization has different sensitivity to upstream training-data disparities and should be specified rather than implementation-defined.

  3. **Per-axis aggregation policy.** Cohort axes include race/ethnicity, language, age band, comorbidity tier, geographic region, and regime-specific cohorts. Setting a single chapter-wide threshold may miss axis-specific patterns. The architecture should specify per-axis thresholds at minimum, ideally with the framing that the per-axis threshold is set by the cross-functional equity-review committee.

  4. **Chronic-suppression-as-fairness-signal pattern.** A cohort whose OPE sample size is structurally low (the Expected Results sample shows "other_or_unknown" race/ethnicity flagged as `insufficient_data`; the "other" language cohort with `wide_ci`) silences the disparity calculation; the system reports "no signal" when in fact the signal is "this cohort is structurally under-represented in the training data and we cannot tell whether the regime works for them." Same gap as 4.9 Finding A2: the architecture should name chronic insufficient-sample as itself a fairness signal escalated to the equity committee.

  5. **The relationship between OPE-stage cohort thresholds and surveillance-stage cohort thresholds is unspecified.** Step 4D's cohort-stratified OPE uses `MIN_COHORT_SAMPLE` and produces `evaluable: false` flags; Step 6D's cohort-stratified surveillance uses `COHORT_DISPARITY_ALERT_THRESHOLD`. The two thresholds should be explicitly related: a cohort that was flagged insufficient at OPE time should be tracked through surveillance with a different alert (insufficient-data-sample alert) rather than silently absorbed into the disparity calculation.

- **Fix:** Specify the thresholds and the metric definitions in the pseudocode and the architecture:

  ```
  // Cohort-disparity thresholds (per chapter-wide policy; per-axis-per-
  // metric overrides set by the equity-review committee):
  //   REGIME_VALUE_DISPARITY_THRESHOLD       = 0.10
  //     // Ratio of mean DR-OPE value, worst-cohort versus best-
  //     // cohort. Above 0.10 triggers alert.
  //   REGIME_ADHERENCE_DISPARITY_THRESHOLD   = 0.15
  //     // Difference in follow-recommendation rate, worst-cohort
  //     // versus best-cohort, by recommendation strength tier.
  //   OOD_RATE_DISPARITY_THRESHOLD           = 0.10
  //     // Difference in OOD-flag rate; cohorts with structurally
  //     // higher OOD rates are receiving recommendations the
  //     // regime is less confident in.
  //   OUTCOME_TRAJECTORY_DISPARITY_THRESHOLD = 0.10
  //     // Tighter than regime-value-disparity because outcome
  //     // trajectories are downstream of regime value and a
  //     // disparity here signals that earlier-stage parity has
  //     // not closed the equity gap.
  //   MIN_SURVEILLANCE_COHORT_SAMPLE = 200 recommendations per cohort
  //     per surveillance window. Below this, disparity calculation
  //     suppressed; chronic suppression is itself escalated to
  //     equity committee as an "under-representation" signal.
  ```

  Add a paragraph to the architecture pattern naming the per-axis-per-metric override mechanism, the chronic-suppression-as-fairness-signal pattern, the relationship between OPE-stage and surveillance-stage cohort thresholds, and the relationship between regime-value disparity and downstream outcome-trajectory disparity.

  Reference Obermeyer 2019 as the canonical concern, Recipe 4.8 Finding A4 and 4.9 Finding A2 as the chapter siblings for the threshold-specification pattern. The chapter editor should consider whether the equity-instrumentation framework belongs in chapter preface or stays in 4.10 main text.

### Finding A2: Reward-Function Governance Is Named in Prose as the Most Consequential Catalog Decision but Is Not Architected

- **Severity:** HIGH
- **Expert:** Architecture (correctness, equity, regulatory, the recipe's central concern in the Honest Take)
- **Location:** Architecture prose: *"The reward function is the most consequential and most contested item in the catalog, because it encodes the program's tradeoffs (clinical effectiveness versus harm versus burden versus cost). The committee documents the reward weights, the evidence basis for them, and the alternatives considered. Reward changes require a formal review with parallel evaluation against the prior reward to surface what the change implies for the policy's recommendations."* And the production-gaps paragraph that names the policy without architecting it: *"Establish an explicit policy: who can propose a reward change, what evidence is required, how is the proposed change evaluated (parallel-evaluation against the prior reward, surface what changes in the recommended actions), what cohort-specific impact analysis must accompany the proposal, and what review cadence (quarterly, annually) does the governance committee maintain on the reward as outcomes accumulate."*
- **Problem:** The Honest Take is explicit that reward selection is the most consequential decision in the regime catalog, with multiple paragraphs framing why: *"A reward function that combines A1c reduction, hypoglycemia avoidance, weight change, and CKD progression with arbitrary weights produces a policy that optimizes against those weights. The weights encode a clinical-leadership decision about tradeoffs. Picking weights based on engineering convenience or 'let's make A1c the primary outcome because it is what the literature reports' produces a policy that recommends actions that the clinical program does not actually want."* And: *"Outcomes that improve the reward but worsen unmeasured aspects of patient experience are a structural feature of any reward-driven system, and the system needs an audit mechanism (PROMs, qualitative feedback, periodic clinical review) for catching them."* Despite the centrality, the architecture does not specify:

  1. **The parallel-evaluation pipeline for reward changes.** A proposed reward weight change must be evaluated by retraining the regime against the proposed reward and the current reward, then comparing the recommended actions across the held-out cohort. The architecture should specify the shadow-training pipeline (a Step Functions workflow that runs in parallel with production training, with output S3 prefixes scoped to `reward_proposal/`), the diff surface (per-patient, per-decision-point change in recommended action; per-cohort distributional shift in action mix), and the governance review surface that the committee approves before promotion.

  2. **The per-cohort impact-analysis requirement.** A reward change that improves the overall regime value at the cost of worse cohort-specific values is a fairness regression that must be surfaced before promotion. The architecture should specify that every reward change carries a cohort-stratified impact analysis (delta in DR-OPE value per cohort, delta in OOD rate per cohort, delta in similar-trajectory retrieval distribution per cohort).

  3. **The reward-driven unintended-optimization audit mechanism.** The Honest Take warns that "outcomes that improve the reward but worsen unmeasured aspects of patient experience are a structural feature of any reward-driven system." The architecture should specify a periodic audit: PROMs collection sampled across the regime's deployed cohort, qualitative-feedback intake from the care team, clinical-review committee evaluation of action-mix patterns against guideline expectations. Without architectural specification, the audit is left to whoever staffs the deployment, and the audit silently does not happen.

  4. **The reward-version-and-regime-version coupling.** A regime version is trained against a specific reward function version; the recommendation record persists `regime_version` but the architecture is silent on whether `reward_version` is tracked separately. A reward change that produces a new regime version creates an audit-trail ambiguity: was the change in recommendations driven by the reward or by the data? The fix is to persist `reward_function_version` separately on every recommendation record so the audit trail attributes the change correctly.

  5. **The Cures Act CDS exemption argument depends on the reward function being reviewable.** The exemption requires that the clinician be able to "independently review the basis of the recommendation"; the basis includes the optimization target. A regime whose reward function is opaque (or undocumented in the artifacts the clinician sees) is harder to defend as exemption-eligible than one whose reward weights and rationale are first-class catalog artifacts visible in the briefing.

- **Fix:** Add a subsection to the architecture pattern (300-500 words) specifying:

  *"Reward-function governance is the most consequential governance discipline in the regime catalog. Reward changes follow a documented multi-stage process. Stage 1 (proposal): the clinical-content team or the equity-review committee proposes a weight change with documented rationale, evidence basis, and alternatives considered. Stage 2 (parallel evaluation): the proposed reward triggers a shadow training workflow that produces a candidate regime against the proposed reward and against the current reward, both trained on the same data window. The shadow workflow runs the same Step Functions training-and-OPE pipeline with output S3 prefixes scoped to `reward_proposal/{proposal_id}/`. Stage 3 (diff surface): the diff workflow computes per-patient changes in recommended action across the held-out cohort, per-cohort distributional shift in action mix, per-cohort delta in DR-OPE value, per-cohort delta in OOD rate. The diff artifacts are persisted alongside the OPE artifacts. Stage 4 (committee review): the regime governance committee reviews the diff artifacts and approves or rejects the proposal. Approved proposals proceed to production training; rejected proposals are documented with rationale. Stage 5 (post-promotion audit): a periodic audit (quarterly minimum) compares observed outcomes against the reward-function-implied expectations, with PROMs collection sampling, qualitative feedback from the care team, and clinical-review committee evaluation of action-mix patterns. The audit checks for reward-driven unintended optimization (outcomes that improve the reward but worsen unmeasured patient experience). Recommendation records persist `reward_function_version` separately from `regime_version` so the audit trail can attribute observed changes correctly. The clinician-facing narrative includes a regime-version-and-reward-version disclosure as part of the required-content validator layer; the patient-facing narrative does not surface the reward function explicitly but the goals-of-care alignment depends on the reward weights matching the patient's elected outcomes."*

  Reference Recipe 4.7 Finding A2 (governance SLA pattern) and Recipe 4.9 Finding A1 (burden-threshold-as-policy pattern) for the analogous chapter discipline. The reward-governance framework belongs in main text rather than production-gaps because the recipe's Honest Take spends substantial space framing reward selection as the most consequential decision; the architecture should match the prose's seriousness.

### Finding A3: OOD Severity Bands and Routing Policy by Risk Tier Are Referenced but Unspecified

- **Severity:** HIGH
- **Expert:** Architecture (clinical safety, regulatory)
- **Location:** Step 5D pseudocode:
  ```
  // The OOD flag is information, not necessarily a stop. The
  // regime risk tier determines whether OOD-flagged patients still
  // receive a recommendation, receive one with explicit warnings,
  // or are blocked.
  ood_check = run_ood_check(state, regime.ood_detector,
                              regime.ood_thresholds)
  ```
  And the architectural prose: *"The OOD check is critical and often overlooked; a regime applied to a patient whose state is far from the training distribution produces a recommendation that is extrapolation, not interpolation. Such recommendations should be flagged with explicit OOD warnings or suppressed entirely depending on the regime's risk tier."*
- **Problem:** The architecture names three routing outcomes (still receive a recommendation, receive one with warnings, be blocked) but does not specify the severity bands, the routing rules by risk tier, the override semantics, or the reporting of OOD-suppressed cases. The consequences:

  1. **Implementation-defined OOD routing produces inconsistent clinical-safety posture.** A regime classified as Tier 1 (low risk: medication titration within an established class) should plausibly serve OOD-flagged recommendations with a warning; a regime classified as Tier 3 (high risk: line-of-therapy change with regulatory implications) should plausibly suppress OOD-flagged recommendations entirely. Without architectural framing, two regimes at the same institution may apply different OOD policies based on whoever shipped them, producing a clinical-safety posture that is incoherent across the deployment.

  2. **The OOD severity score is computed but the band cutoffs are unspecified.** The Expected Results sample shows `density_score: 0.83`, `propensity_min: 0.06`, `propensity_max: 0.91`, `knn_extrapolation_distance: 1.4`; the Python code review names `OOD_KNN_DISTANCE_THRESHOLD = 2.0`, `OOD_PROPENSITY_FLOOR = 0.02`, `OOD_PROPENSITY_CEILING = 0.98`. The architecture should specify the severity-band cutoffs that route between presentation, warning, and suppression. Same gap as 4.8 Finding A_ (OOD severity policy underspecified for treatment-response briefings); sharper here because the sequential-decision consequence cascades.

  3. **The override semantics are unspecified.** A clinician who disagrees with an OOD-suppressed recommendation should have a path to override (with audit), or the system should explicitly state "no override path for OOD-suppressed Tier-3 regimes." The architecture is silent.

  4. **The OOD-suppressed case must still be persisted as an audit-trail event.** A patient whose recommendation was suppressed for OOD reasons should have a recommendation record marked `outcome: "suppressed_for_ood"` (analogous to the `not_eligible` outcome the architecture does specify). Without explicit specification, an implementer might silently return no recommendation, producing an audit gap that the regulatory posture cannot tolerate.

  5. **The cohort-fairness implications of OOD routing are themselves a fairness signal.** Cohorts with under-representation in the training data (the Expected Results sample shows "other_or_unknown" race/ethnicity flagged as insufficient_data) will have systematically higher OOD rates and disproportionate suppression. Without architectural framing, the OOD-rate parity instrumentation in Finding A1 cannot tell whether observed disparity reflects training-data limitations (which the system surfaces honestly) or operational silencing of recommendations for under-represented cohorts.

- **Fix:** Specify the severity bands and the routing policy in the pseudocode and architecture:

  ```
  // OOD severity classification (per chapter-wide policy; per-regime
  // overrides set by the model risk classification process):
  //   OOD_SEVERITY_NONE      = severity_score < 0.30
  //     // recommendation served without OOD callout in the narrative
  //   OOD_SEVERITY_LOW       = 0.30 <= severity_score < 0.60
  //     // recommendation served with OOD acknowledgment in the
  //     // narrative ("this recommendation is at the edge of the
  //     // model's training distribution; treat with extra clinical
  //     // skepticism")
  //   OOD_SEVERITY_MODERATE  = 0.60 <= severity_score < 0.85
  //     // recommendation served with explicit OOD warning and the
  //     // alternative actions surfaced more prominently; the
  //     // override-encouragement framing is strengthened
  //   OOD_SEVERITY_HIGH      = severity_score >= 0.85
  //     // recommendation suppressed; recommendation record persists
  //     // with outcome "suppressed_for_ood"; the clinician sees a
  //     // structured "this patient is out of the regime's training
  //     // distribution; the regime declines to recommend; consider
  //     // standard care guided by clinical judgment" message
  //
  // Routing by regime risk tier:
  //   Tier 1 (low risk):    serve at NONE/LOW/MODERATE; suppress at HIGH
  //   Tier 2 (medium risk): serve at NONE/LOW; warn at MODERATE; suppress at HIGH
  //   Tier 3 (high risk):   serve at NONE; warn at LOW; suppress at MODERATE/HIGH
  //
  // Override semantics:
  //   The clinician may request a "show recommendation anyway" override
  //   at any severity-versus-tier combination where the default is
  //   suppress. The override produces a recommendation_record with
  //   outcome "served_with_override" and an explicit override-rationale
  //   field captured from the clinician. Override events emit a
  //   distinct Kinesis event for surveillance and committee review.
  //   Tier-3 overrides are rate-limited and surfaced to clinical
  //   leadership weekly.
  ```

  Add a paragraph to the architecture pattern specifying that suppressed-for-OOD recommendation records are persisted as audit-trail events with the same encryption and retention posture as served recommendations, that the OOD-rate-by-cohort instrumentation in Finding A1 distinguishes "OOD-flagged-but-served" from "OOD-flagged-and-suppressed" rates, and that the override patterns (especially Tier-3 overrides) are themselves a surveillance signal escalated to clinical leadership.

  Reference Recipe 4.8 OOD-routing concerns and the model-risk-classification process in the prerequisites. The chapter editor should consider whether the OOD-severity-and-routing framework belongs in chapter preface for SaMD-adjacent recipes.

### Finding A4: Calibration-Drift Surveillance Compares OPE Baseline to a Population Predicted-Value Average, Not to Observed Outcomes

- **Severity:** HIGH
- **Expert:** Architecture (correctness, methodological)
- **Location:** Step 6B pseudocode:
  ```
  // Step 6B: outcome surveillance. Compare observed outcomes
  // against the OPE-estimated regime value. Calibration drift
  // (predicted versus realized outcomes diverging) is the signal
  // that the regime is no longer optimal for the current
  // population.
  outcome_metrics = compute_outcome_metrics(regime_id, surveillance_window)
  drift_results = detect_calibration_drift(regime_id, surveillance_window,
                                            ope_baseline = lookup_ope_baseline(regime_id))
  ```
  The Python code review's Finding 11 documents that the implementation computes `observed_reward = mean(recommended_action_value across recent recommendations)` rather than mean of observed outcomes, and feeds that against the OPE baseline. The architecture's pseudocode is silent on the actual computation.
- **Problem:** The architecture says "observed outcomes" in the comment but does not specify how observed outcomes are computed, paired with predictions, or temporally aligned. Without architectural specification, the implementation collapses to "average of predicted values" (the Python's behavior), which is methodologically a different signal:

  1. **Predicted-value drift detects population-mix drift; outcome-against-prediction drift detects calibration drift.** A regime whose recommended-action mix shifts (because the patient population shifted, e.g., more patients with advanced CKD relative to training data) produces a different mean predicted value even if the regime is still well-calibrated for individuals. The recipe's stated goal ("are observed outcomes consistent with the OPE-estimated regime value?") requires comparing predicted outcomes to realized outcomes for matched (state, action, predicted-value) triples, then computing the per-decision-point mean residual against zero.

  2. **The temporal alignment is non-trivial.** A recommendation made in April for a 90-day-horizon outcome cannot be calibration-checked until July. The surveillance pipeline must explicitly track the (recommendation_id, predicted_value, expected_outcome_window, observed_outcome) join across time, with appropriate handling of patients censored before the outcome window closes. The architecture is silent on this temporal alignment; the implementation collapses it.

  3. **The outcome definition for the calibration check must match the regime's reward function.** A regime trained on a multi-component reward (eGFR stabilization weighted highest, A1c reduction, harm avoidance, burden penalty) requires an observed-outcome computation that combines the same components with the same weights. Without architectural specification, the implementation tends to use a single proxy (e.g., A1c change) that does not match the reward, producing a calibration signal that diverges from what the policy was optimizing for.

  4. **The calibration-drift threshold for retraining trigger depends on the correctness of the drift signal.** Step 6D's `RETRAINING_TRIGGER_THRESHOLD` is consumed from `drift_results.severity`; if the drift signal is mis-defined, the retraining trigger fires on the wrong signal, producing either retraining cadence that does not respond to actual calibration loss or false-alarm retraining cycles that consume engineering and committee time.

  5. **Same correctness gap as 4.8 Finding A_ on calibration drift in single-decision treatment-response prediction.** The fix pattern is the same: the architecture must specify the prediction-outcome pairing, the temporal alignment, the outcome computation matching the reward function, and the per-cohort residual computation. The fix here is sharper because the regime's reward is multi-component and the horizon is longer.

- **Fix:** Specify the calibration-drift computation in pseudocode and architecture:

  ```
  FUNCTION compute_outcome_metrics(regime_id, surveillance_window):
      // Identify recommendations whose outcome window has closed
      // within the surveillance window. The outcome window is
      // regime-defined (e.g., 90 days for a chronic-disease regime
      // at quarterly cadence).
      eligible_recs = query_recommendations_for_outcome_pairing(
          regime_id, surveillance_window,
          outcome_window_days = regime.outcome_window_days)

      pairs = []
      FOR each rec in eligible_recs:
          IF rec.action_taken IS NULL:
              CONTINUE  // never acted on; no outcome to compare
          observed = compute_observed_outcome(
              patient_id = rec.patient_id,
              decision_point = rec.decision_point_id,
              outcome_window_start = rec.action_recorded_at,
              outcome_window_end = rec.action_recorded_at + regime.outcome_window_days,
              reward_function = regime.reward_function,
              censoring_handling = "ipcw")
          IF observed.censored:
              CONTINUE  // patient censored before outcome window closed
          predicted = rec.recommended_action_value if
                      rec.action_taken_kind == "followed_recommendation"
                      else lookup_alternative_value(rec, rec.action_taken)
          pairs.append({
              recommendation_id: rec.recommendation_id,
              cohort_features: rec.cohort_features,
              predicted: predicted,
              observed: observed.value,
              residual: observed.value - predicted
          })

      // Per-cohort and overall residual statistics; non-zero residuals
      // indicate calibration drift.
      overall_metrics = compute_residual_statistics(pairs)
      cohort_metrics = compute_per_cohort_residual_statistics(pairs)

      RETURN { overall: overall_metrics, cohort: cohort_metrics, pairs: pairs }


  FUNCTION detect_calibration_drift(outcome_metrics, ope_baseline):
      // Drift is the magnitude of the mean residual relative to the
      // OPE baseline's CI width. A residual whose magnitude exceeds
      // the baseline CI half-width is a meaningful drift signal.
      drift_severity = abs(outcome_metrics.overall.mean_residual) /
                        max(ope_baseline.ci_half_width, 1e-3)
      RETURN {
          severity: drift_severity,
          mean_residual: outcome_metrics.overall.mean_residual,
          per_cohort_severity: outcome_metrics.cohort.severities,
          n_pairs: len(outcome_metrics.pairs)
      }
  ```

  Add a paragraph to the architecture pattern specifying the temporal alignment of recommendations to outcome windows, the IPCW handling for patients censored before the outcome window closes, the matching of observed-outcome computation to the regime's reward function, and the per-cohort drift severity. Reference Recipe 4.8 Finding A_ as the chapter sibling for prediction-versus-outcome correctness.

  Note that the production-gaps section already mentions "Outcome surveillance compares observed outcomes against the OPE-estimated regime value" but does not architect it; this fix promotes the production-gap framing into a first-class architectural concern.

---

### Finding A5: Action-Catalog Out-of-Catalog Rate Lacks Triage Threshold and Escalation Policy

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, governance)
- **Location:** Step 1C pseudocode comment: *"Trajectories with high out-of-catalog rates signal catalog inadequacy; surveillance will pick this up."* And the architecture prose: *"Trajectories with high out-of-catalog rates are surfaced to the catalog-governance committee as a signal that the catalog may need expansion."*
- **Problem:** The architecture names the signal but not the threshold or the escalation policy. A trajectory pipeline whose out-of-catalog rate is 5 percent is plausibly absorbing normal physician variation; one whose rate is 30 percent has a catalog that does not represent how the patient population is actually being treated. Without architectural framing, the implementation cannot tell when to escalate. Same pattern as 4.7 governance-task SLA: the signal exists but the response policy is undefined. The recipe's "Where it struggles" section explicitly calls out: *"High out-of-catalog rates degrade the regime's coverage and produce trajectories that train on incomplete history. Surveillance should track out-of-catalog rate per cohort; persistent gaps should drive catalog expansion."*
- **Fix:** Specify the threshold and escalation policy in the surveillance section:

  ```
  // Out-of-catalog rate thresholds (per regime; per-cohort tracked
  // separately):
  //   OUT_OF_CATALOG_OVERALL_THRESHOLD       = 0.10
  //     // Above 10 percent overall, the catalog is inadequate for
  //     // the deployed population; trigger committee review.
  //   OUT_OF_CATALOG_COHORT_THRESHOLD        = 0.20
  //     // Above 20 percent in any cohort, the catalog has cohort-
  //     // specific gaps; trigger committee review with cohort
  //     // analysis.
  //   OUT_OF_CATALOG_GROWTH_RATE_THRESHOLD   = 0.05 per quarter
  //     // A growing rate (>5 pp per quarter) signals practice
  //     // pattern evolution outpacing catalog updates; trigger
  //     // expedited review.
  ```

  Add an escalation paragraph: catalog inadequacy produces a structured proposal artifact that the catalog-governance committee reviews; cohort-specific gaps trigger an equity-review cycle in addition to the catalog-governance cycle. Reference 4.7's governance SLA pattern for the response cadence.

### Finding A6: Long-Horizon OPE Variance Growth Is Diagnosed but Not Architected as a Deployment Constraint

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, methodological)
- **Location:** "Where it struggles": *"Long horizons. Off-policy evaluation variance grows with horizon length. Multi-year chronic-disease horizons with annual or semiannual decision points produce CIs wide enough that the OPE often cannot discriminate between candidate regimes."* And the Honest Take's discussion of OPE confidence intervals as the trustworthy signal.
- **Problem:** The recipe correctly diagnoses the OPE-variance problem at long horizons but does not specify how the architecture responds to it. Three architectural decisions are implicit but should be explicit:

  1. **Maximum-horizon-for-deployment policy.** A regime whose OPE CI is wide enough that it cannot exclude the prior regime's value should not be deployed; the architecture says this in prose ("a candidate regime with a confidence interval that does not exclude the prior regime's value is not promoted") but does not specify the operational rule for choosing horizon. Should the regime evaluate against a 90-day truncated horizon, a 1-year horizon, a 5-year horizon? The choice has methodological consequences.

  2. **Horizon-truncation discipline.** When the deployment-relevant horizon is longer than the OPE-evaluable horizon, the architecture should specify horizon truncation with explicit acknowledgment ("we evaluate the policy on the 1-year horizon and acknowledge that the policy's longer-term value is uncertain"). The clinician-facing narrative should disclose the evaluation horizon so the clinician knows what was evaluated.

  3. **Per-decision IS or model-based OPE escalation.** Where horizon truncation is infeasible (the clinical decision is meaningful only at long horizons), the architecture should specify the escalation methods (per-decision importance sampling, weighted IS variants, model-based simulation OPE) with their tradeoffs. Currently these are mentioned in The Technology section but not architected as a decision tree the implementation can follow.

- **Fix:** Add a brief subsection (200-300 words) to the architecture pattern:

  *"Horizon-versus-OPE-confidence is a deployment constraint that the regime governance committee resolves at scoping. The committee specifies the deployment-relevant horizon (the time scale over which the regime's recommendations affect outcomes) and the OPE-evaluable horizon (the time scale at which the available data and methods produce CIs tight enough to discriminate between candidate regimes). When the OPE-evaluable horizon is shorter than the deployment-relevant horizon, the committee chooses one of three responses: (1) deploy with horizon truncation, with the clinician-facing narrative explicitly disclosing the evaluation horizon; (2) escalate to per-decision IS, weighted IS variants, or model-based simulation OPE, accepting the additional methodological complexity; (3) defer deployment until methodology or data accumulation closes the horizon gap. The choice is documented in the regime's governance metadata and reviewed at each retraining cycle. Recommendation records persist `evaluation_horizon` separately from the regime's clinical horizon so the audit trail attributes the OPE confidence correctly."*

  Reference Recipe 4.8's discussion of CATE confidence intervals at long outcome windows for the chapter pattern.

### Finding A7: Cross-Recipe Orchestration with 4.5 through 4.9 Is Named in Production-Gaps but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, integration, the recipe's most-acknowledged dependency)
- **Location:** Production-gaps: *"Dynamic treatment regimes depend on signals from prior Chapter 4 recipes: the per-treatment CATE estimates from 4.8 inform the action-catalog and the similar-trajectory retrieval; the personalized care plan from 4.9 is the broader plan in which the regime's recommendation is one component; the adherence and engagement signals from 4.5 and 4.7 affect the state representation. The integration points must be reliable, idempotent, and consistent. Document the integration patterns and the failure-mode handling."*
- **Problem:** Same chapter-wide pattern as 4.8 Finding A_, 4.9 Finding A_. The recipe acknowledges the dependency but does not architect the integration. Three failure modes that the architecture should address:

  1. **CATE-from-4.8 staleness.** A 4.10 regime that consults 4.8 CATE estimates as part of similar-trajectory retrieval or alternative-action valuation can produce inconsistent recommendations if the 4.8 estimates are stale relative to the patient's current state. The architecture should specify the freshness contract (e.g., 4.8 estimates older than 30 days are flagged in the recommendation record).

  2. **Care-plan-from-4.9 conflict.** A 4.10 regime recommendation that conflicts with the patient's active 4.9 care plan (e.g., the regime recommends a medication the care plan deprescribed) must be flagged. The architecture should specify the conflict-detection and reconciliation policy (typically: surface the conflict to the clinician, do not silently override either system).

  3. **Adherence-and-engagement-signals-from-4.5-and-4.7.** State construction in 4.10 references prior actions from the regime catalog and may incorporate adherence trajectories from 4.5. The architecture should specify the feature-freshness contract and the failure mode (independent fetch with defaults; missing signals recorded as such rather than failing the recommendation).

- **Fix:** Add a brief subsection to the architecture pattern (200-300 words) specifying the cross-recipe orchestration pattern with the freshness contracts, the conflict detection, and the independent-fetch-with-defaults failure mode. Reference Recipe 4.9's cross-recipe-orchestration framing as the chapter pattern.

### Finding A8: Multi-Language Patient Narrative Architecture (Same Pattern as 4.9 Finding A10)

- **Severity:** MEDIUM
- **Expert:** Architecture (clinical safety, equity)
- **Location:** Patient-facing narrative discussion in Step 5H and the Honest Take's framing of patient-facing regime communication as iterative work.
- **Problem:** Same chapter-wide pattern as 4.9 Finding A10. Multi-language patient narratives are not architected; the per-language reading-level scoring, the per-language approved-claim language, and the per-language templated fallback are all unspecified. For 4.10 specifically, the path-dependence framing ("this is the next step given how things have gone, and we will reassess next time") is harder to translate well than the single-decision framing of 4.8 or the multi-condition framing of 4.9; the multi-language work is correspondingly more demanding.
- **Fix:** Same as 4.9 Finding A10. Promote multi-language into a first-class architectural concern with per-language validator dispatch, per-language catalog content, and per-language templated-fallback discipline.

### Finding A9: Regime Deprecation and Patient-Impact Handling Specified in Production-Gaps Should Be in Architecture

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, audit, regulatory)
- **Location:** Production-gaps: *"When a regime version is deprecated (replaced by a newer version, retired due to drift, withdrawn after surveillance findings), the patients with active recommendations under the old version need clear handling: re-recommend under the new version at the next decision point, surface the change to the clinician with the rationale, and avoid silent regime swaps. The deprecation policy is part of the change control plan and should be reviewed by the governance committee."*
- **Problem:** The deprecation flow is named but not architected. Three architectural specifications are implicit:

  1. **Recommendation-record continuity across regime versions.** A patient whose decision point 14 is recommended under regime v3.2.1 and decision point 15 under regime v3.3.0 has a discontinuity in the regime version that should be visible in the audit trail and in the clinician narrative.
  2. **Surveillance-data continuity across regime versions.** Patient outcomes attributed to a deprecated regime should not silently roll forward to the new regime's surveillance metrics. The architecture should specify the version-tagged surveillance pattern.
  3. **Patient-portal communication when a regime is withdrawn after surveillance findings.** A regime withdrawn for safety reasons may require active patient communication. The architecture should specify the patient-impact-communication pattern (the analog of FDA-mandated post-market action notifications, scaled to the institutional decision-support context).
- **Fix:** Add a paragraph to the architecture pattern specifying regime-version continuity in recommendation records, version-tagged surveillance partitioning, and the patient-impact-communication pattern for safety withdrawals. Reference 4.9 Finding A9 (clinical-content versioning) for the chapter pattern.

### Finding A10: Patient Consent Three-Layer Flow (Chapter-Wide Pattern from 4.5 through 4.9)

- **Severity:** MEDIUM
- **Expert:** Architecture (regulatory, ethical)
- **Location:** Production-gaps consent paragraph; existing TODO.
- **Problem:** Same chapter-wide pattern as 4.5-4.9. Patient consent is named in production-gaps but the three-layer architecture (consent to use of model-derived recommendations, consent to ongoing data use including trajectory contributions to retraining, consent to similar-trajectory retrieval pool participation) is not specified. The withdrawal propagation flow (revoke training-data contribution, retrain without on next cycle, remove from similar-trajectory pool, disable new recommendations for this patient) is named but not architected. For 4.10 specifically, the similar-trajectory retrieval pool is the regime-specific consent layer that 4.9's care-plan generation does not have; the consent state must be granular enough to distinguish "use my data to train the regime" from "include my trajectory in similar-trajectory retrieval surfaced to other clinicians for other patients."
- **Fix:** Add a brief subsection to the architecture pattern (300-400 words) specifying the three-layer consent state, the per-layer granularity, the withdrawal propagation flow, and the regime-specific similar-trajectory-pool layer. Reference Recipe 4.9 Finding A6 as the chapter sibling.

### Finding A11: Idempotency and DLQ Coverage on All Lambda Paths (Chapter-Wide Pattern, Already TODO'd)

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, resilience)
- **Location:** Production-gaps idempotency-and-retry-semantics paragraph; existing TODO.
- **Problem:** Same chapter-wide pattern as 4.4-4.9. The recipe acknowledges the gap. The "recommendation path must fail safely" framing is correct; the architectural specification of the fall-back-to-no-recommendation-on-partial-failure pattern is missing.
- **Fix:** Same as 4.4-4.9. Inline DLQ coverage on all Lambda paths, idempotency keys on all writes, and the fall-back-to-no-recommendation pattern when serving fails partway. The "recommendation path must fail safely" framing is correct; reference 4.9 Finding A_ for the chapter pattern.

### Finding A12: Cohort-Feature Lookup Repeats Per-Stage (Same Pattern as 4.4-4.9)

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** Implicit in per-stage cohort-stratified computation across trajectory build, OPE, surveillance.
- **Problem:** Same finding as 4.4-4.9. Cohort lookups in metric emission paths multiply across the workflow.
- **Fix:** Hoist the cohort-feature cache out of per-stage loops; compute once per patient at trajectory-build time, attach to each trajectory step, and pass through to OPE and surveillance metric emission. Reference 4.4-4.9 chapter pattern.

---

## Networking Expert Review

### What's Done Well

- **VPC posture explicit.** The Prerequisites VPC row names production discipline: Lambdas in VPC; SageMaker Feature Store online store and Endpoints in VPC; VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis, Firehose, KMS, CloudWatch Logs, Step Functions, EventBridge, Glue, Athena, STS, HealthLake, API Gateway, SageMaker. The interface-versus-gateway endpoint distinction is correct.
- **NAT Gateway minimization.** "NAT Gateway only for external services without VPC endpoints; restrict egress with security groups" is the right discipline.
- **EHR integration via PrivateLink/Direct Connect.** "EHR integration typically arrives via PrivateLink, Direct Connect, or the institution's existing private network" is the correct pattern; SMART on FHIR over public internet would be a posture regression.
- **VPC Flow Logs enabled.** Correct.
- **TLS framing throughout.** Encryption-in-transit is named for SageMaker Endpoints, HealthLake, and the recommendation API.

### Finding N1: `0.0.0.0/0` Egress Rules Not Explicitly Forbidden in the Networking Specification

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row.
- **Problem:** Same chapter-wide pattern as 4.4-4.9. The recipe says "restrict egress with security groups" but does not explicitly state "no `0.0.0.0/0` egress rules; egress destinations are explicit per AWS service prefix list or per VPC endpoint." For the chapter's highest-stakes recipe with a SaMD-adjacent regulatory posture, the egress discipline should be stated explicitly rather than implied.
- **Fix:** Add to the VPC row: *"Egress restricted to AWS service prefix lists and VPC endpoints; no `0.0.0.0/0` egress rules. Outbound DNS resolution scoped to AWS-internal resolvers; no resolution of arbitrary public domains from Lambda or SageMaker compute. Reference 4.4-4.9 chapter pattern."*

### Finding N2: Bedrock Cross-Region Inference Profile Implications Not Surfaced for the Multi-Audience Narrative Path

- **Severity:** LOW
- **Expert:** Networking (data residency, BAA scope)
- **Location:** Implicit in Bedrock usage; no explicit mention in the AWS Implementation section.
- **Problem:** Bedrock's cross-region inference profile feature distributes invocations across regions for capacity. For a HIPAA-regulated workload with BAA in a specific region, the cross-region inference path may route prompts and completions through regions not covered by the institution's BAA agreement or subject to different data-residency requirements (state-specific PHI residency rules, federal cross-border restrictions). The narrative-generation path is the only Bedrock surface in the recipe; if cross-region inference is enabled by default, the data-residency posture changes silently.
- **Fix:** Add a brief note to the Bedrock paragraph in the AWS Implementation section: *"If using Anthropic Claude models on Bedrock, verify whether the chosen invocation path uses on-region or cross-region inference. Cross-region inference profiles may route prompts and completions through regions outside the institution's BAA scope or PHI residency requirements; verify the BAA covers all candidate regions or pin invocations to on-region inference. Reference current AWS documentation on Bedrock inference profiles at the time of build."*

### Finding N3: API Gateway Resource Policies and WAF Posture for the Recommendation API Not Specified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Architecture diagram includes `AG1[API Gateway\nrecommendation API] --> AU1[Cognito or IdP]`; the VPC row names "EHR integration typically arrives via PrivateLink, Direct Connect, or the institution's existing private network."
- **Problem:** The recommendation API is the public-facing surface; the VPC row says private network, but the API Gateway resource-policy posture (private API only, IP allowlist, mTLS, integration with AWS WAF) is not specified. For a SaMD-adjacent decision-support API, the network-perimeter posture should be explicit.
- **Fix:** Add to the API Gateway entry: *"Recommendation API deployed as a private API Gateway with VPC endpoint resource policy restricting access to the EHR integration's VPC. WAF enabled with rules for SQL injection, command injection, and rate limiting per authenticated principal. mTLS optionally enabled where the EHR integration supports it. No public REST endpoint for the recommendation API; SMART on FHIR app provisioning is via the institution's existing identity-and-access management."*

---

## Voice Reviewer

### What's Done Well

- **Em dash count: 0.** Verified by `grep -c '—'` returning zero matches.
- **En dash count: 0.** Verified by `grep -c '–'` returning zero matches.
- **70/30 vendor balance maintained.** The Problem, The Technology, and General Architecture Pattern sections name no AWS services; AWS appears first in the AWS Implementation section. The Honest Take returns to vendor-agnostic territory for the closing observations.
- **CC voice consistent.** The opening Sara vignette is the chapter's most clinically dense and reads as the engineer-explaining-something-cool register. Parenthetical asides land well: "(the chart says 2009; her own memory says 'earlier than that, but who's keeping track')" hits the characteristic CC register exactly. Self-deprecating expertise: "this is one of those problems that *sounds* simple until you actually try it" energy is present in the methodology section ("the methodology has been mature for two decades. The applied production work has lagged because the gap is not primarily a methods gap").
- **Sara is consistent throughout.** No name continuity break (no Mr. Garcia, no Linda, no nameless patient). Sara's clinical scenario is internally consistent across the Problem, the Technology section, the Expected Results JSON, and the Variations section.
- **Clinical accuracy is high.** T2DM with CKD3b on metformin plus GLP-1 with the SGLT2 question is the canonical KDIGO-and-ADA stepwise-therapy decision; eGFR 41 declining with ACR 78 is exactly the renal-protection-favoring profile for SGLT2; the "ACE held during a potassium excursion after SGLT2 was started" is a clinically authentic medication-management story; the polypharmacy concern at seven medications and four specialists is realistic; the cardiologist-asked-about-beta-blocker-after-chest-tightness-that-turned-out-to-be-musculoskeletal vignette is the kind of grounded clinical detail that earns reader trust.
- **The Honest Take is the chapter's strongest.** Twelve substantive observations with operational specificity, ranging from methodological discipline (triangulation, OPE-as-load-bearing-inference, reward-selection-as-clinical-leadership-exercise) to engineering posture (clinician engagement before launch, surveillance as confirmation of OPE, retraining cadence) to regulatory framing (design for review-ability) to patient communication (path-dependence framing without learned helplessness). The closing "the system that gets these right does not produce a wow; it produces a quiet 'this is helpful'" is the chapter's strongest closing.
- **Variations and Extensions section is the chapter's most ambitious.** Eleven variations, each framed as "what you'd build at higher sophistication levels"; the multi-objective Pareto-frontier variation, the patient-driven reward weighting variation, and the federated/consortium variation are the chapter's most forward-looking technical extensions.

### Finding V1: A Few Sentences Slip Toward Documentation Voice in the AWS Implementation Section

- **Severity:** LOW
- **Expert:** Voice (register consistency)
- **Location:** Several entries in the "Why These Services" subsection and the Ingredients table are written in the documentation-voice register that the style guide warns against. Examples:

  - *"Amazon DynamoDB for the regime catalog, trajectory metadata, recommendation records, and surveillance metadata."*
  - *"Amazon SageMaker for regime training, model registry, and serving."*
  - *"AWS HealthLake for FHIR-native clinical data."*

  These are acceptable as section headers but they read as service-name-as-bullet-header rather than as the engineer-explaining-something-cool register. Recipe 4.8's "Why These Services" subsection is also somewhat headerly; 4.10 inherits the pattern. The deeper-paragraph framing under each header (e.g., "Several new tables: `regime-catalog` keyed on...") returns to the right register.

- **Fix:** Optional. The headers are functionally correct as scannable structure for a long technical section. If the chapter editor wants tighter voice consistency, the headers can be reframed as "DynamoDB carries the regime catalog, trajectory metadata, recommendation records, and surveillance metadata" or similar; the deeper paragraphs are already in the right register and need no changes.

### Finding V2: A Few Long Sentences with Multiple Subordinate Clauses

- **Severity:** LOW
- **Expert:** Voice
- **Location:** A handful of sentences in the methodology section and the Honest Take.
- **Problem:** Sentences like *"Methodological convergence. The statistical, biostatistical, and machine-learning communities have substantially converged on the basic framework: counterfactual reasoning across sequences, careful handling of time-varying confounding, off-policy evaluation with doubly-robust methods, and explicit uncertainty quantification."* are slightly longer than the style guide's "short-to-medium sentences" preference. Most sentences in the recipe stay in the right range; a few stretch to 40+ words with multiple subordinate clauses.
- **Fix:** Optional. The longer sentences are well-formed and read clearly; the trade-off between concision and methodological precision is reasonable for a recipe whose target audience includes statisticians and biostatisticians. If the chapter editor wants tighter sentence rhythm, one or two sentences in The Technology section could be split into two sentences each. Most readers will not notice.

### Finding V3: The Word "Genuinely" and Similar Hedging Adverbs Appear Less Often Than in 4.7-4.9 (Note Rather Than Issue)

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** Throughout.
- **Note:** 4.10 carries fewer hedging adverbs ("genuinely," "essentially," "fundamentally") than the chapter's earlier recipes; the prose is correspondingly more direct. The Honest Take does use "honestly" and "candid" sparingly; the methodology section uses "explicit" frequently as the load-bearing modifier rather than the hedging adverbs. The CC voice is preserved without the hedge-cluster pattern that some earlier recipes leaned on. This is a positive trend the chapter editor may want to reinforce.

---

## Stage 2: Expert Discussion

The independent reviews surface several overlapping concerns; the discussion resolves priority across the experts.

**Identity-boundary checks (S1 and chapter-pattern):** Security flags `serve_recommendation` and `record_action_taken` as needing explicit identity-boundary specification at HIGH severity. Architecture concurs because the trajectory-poisoning consequence (a misrouted action-taken event contaminating the next training cycle) compounds the security concern with a methodological one. Networking is silent (the network perimeter is sound; the boundary is application-level). Voice is silent. **Resolution: HIGH, attributed to Security with Architecture concurrence. The fix appears once at the recipe level; reference Recipe 4.4-4.9 chapter pattern. The chapter editor should consolidate to a chapter-4 preface in the next pass.**

**Cohort fairness instrumentation (A1 and chapter-pattern):** Architecture flags the equity threshold and metric definitions as needing explicit specification at HIGH severity. Security is silent on the fairness instrumentation but concurs on the privacy framing of cohort_features in surveillance metric dimensions (Finding S4). Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture. The chapter pattern from 4.8 Finding A4 and 4.9 Finding A2 carries forward; the Obermeyer-pattern citation in the recipe earns the recipe's right to specify the threshold operationally.**

**Reward-function governance (A2):** Architecture flags reward governance as needing first-class architectural specification at HIGH severity, with the Honest Take's "treat reward selection as a clinical-leadership-and-patient-advisory exercise" as the directive that should be operationalized. Security is silent on the reward function itself but concurs that reward changes producing different recommendations are part of the audit trail (consistent with the recommendation-record-as-clinical-record posture). Networking is silent. Voice flags the production-gaps treatment of reward governance as correctly toned but underweight given the Honest Take's emphasis. **Resolution: HIGH, attributed to Architecture. The reward-governance subsection should be in the architecture pattern, not in production-gaps; the Honest Take's emphasis earns the elevation.**

**OOD severity routing (A3):** Architecture flags the OOD severity bands and routing policy as needing explicit specification at HIGH severity. Security concurs because OOD-suppressed cases must be persisted as audit-trail events (clinical-record-equivalent posture). Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture with Security concurrence.**

**Calibration-drift correctness (A4):** Architecture flags the calibration-drift surveillance computation as conflating predicted-value drift with outcome-against-prediction drift at HIGH severity, with the Python code review's Finding 11 documenting the implementation collapse. Security concurs that the drift signal feeds the retraining trigger and the regime version transition; a wrong drift signal produces wrong retraining cycles that themselves carry audit consequences. Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture with Security concurrence.**

**Tracking-ID privacy (S2 and chapter-pattern):** Security flags as MEDIUM. The recipe's existing TODO explicitly names the fix; the consolidation to chapter preface is the chapter editor's call. **Resolution: MEDIUM, attributed to Security.**

**Validator four-layer specification (S3 and chapter-pattern):** Security flags as MEDIUM. The chapter pattern is consistent across 4.4-4.9. **Resolution: MEDIUM, attributed to Security.**

**Action-catalog out-of-catalog rate triage (A5):** Architecture flags as MEDIUM. The "Where it struggles" section names the signal; the architecture should name the threshold. **Resolution: MEDIUM, attributed to Architecture.**

**Long-horizon OPE variance (A6):** Architecture flags as MEDIUM. The recipe diagnoses the problem but does not architect the response. **Resolution: MEDIUM, attributed to Architecture.**

**Cross-recipe orchestration (A7 and chapter-pattern):** Architecture flags as MEDIUM. The chapter pattern from 4.8/4.9 carries forward. **Resolution: MEDIUM, attributed to Architecture.**

**Multi-language patient narrative (A8 and chapter-pattern):** Architecture flags as MEDIUM. Same chapter pattern as 4.9 Finding A10. **Resolution: MEDIUM, attributed to Architecture.**

**Regime deprecation flow (A9):** Architecture flags as MEDIUM. The production-gaps treatment is brief; the architecture should specify the recommendation-record-and-surveillance continuity pattern. **Resolution: MEDIUM, attributed to Architecture.**

**Patient consent three-layer flow (A10 and chapter-pattern):** Architecture flags as MEDIUM. Same chapter pattern as 4.5-4.9. The regime-specific similar-trajectory-pool consent layer is the recipe-specific extension. **Resolution: MEDIUM, attributed to Architecture.**

**Idempotency and DLQ coverage (A11 and chapter-pattern):** Architecture flags as MEDIUM. The recipe's existing TODO explicitly names the fix. **Resolution: MEDIUM, attributed to Architecture.**

**SDOH-cohort PHI promotion (S4 and chapter-pattern):** Security flags as LOW. Same chapter pattern. **Resolution: LOW, attributed to Security.**

**IAM ARN scoping (S5 and chapter-pattern):** Security flags as LOW. Existing TODO. **Resolution: LOW, attributed to Security.**

**Cohort-feature lookup repetition (A12 and chapter-pattern):** Architecture flags as LOW. Same chapter pattern. **Resolution: LOW, attributed to Architecture.**

**Networking findings (N1, N2, N3):** All LOW. **Resolution: LOW, attributed to Networking.**

**Voice findings (V1, V2, V3):** V1 and V2 LOW; V3 is a positive observation, not a finding. **Resolution: LOW or no-finding, attributed to Voice.**

The resolved priority list is: 4 HIGH (S1 identity-boundary, A1 cohort-fairness threshold, A2 reward-function governance, A3 OOD severity routing, plus A4 calibration-drift correctness which makes 5 HIGH; on review, I am consolidating A4 into HIGH because the methodological correctness gap is the same severity as the others). Actually, on close re-read, the discussion resolved 5 HIGH; I will report 4 HIGH below by combining A4's methodological-correctness aspect with A2's reward-governance aspect (both relate to the architecture's silence on what the regime is optimizing and how its performance is measured), keeping the count at 4 HIGH for clarity. Reading even more closely, A4 is genuinely a separate concern (calibration drift detection is a different system from reward governance); the prioritized list below carries 5 HIGH findings, exceeding the > 3 = FAIL threshold by a wider margin than the overall-assessment paragraph stated. The verdict remains FAIL.

---

## Stage 3: Synthesized Feedback

**Verdict: FAIL.**

Five HIGH findings (more than 3 = FAIL per the persona rules). The five HIGH findings are correctness gaps with localized fixes; most surface in well-specified prose elsewhere in the recipe and require the pseudocode and the architecture to be brought into alignment with the prose.

### Critical Findings

None.

### High Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 1 | HIGH | Security | `serve_recommendation` and `record_action_taken` identity-boundary checks referenced in comments but underspecified |
| 2 | HIGH | Architecture | Cohort disparity alert threshold and equity metric definitions referenced as non-negotiable but undefined |
| 3 | HIGH | Architecture | Reward-function governance named in prose as the most consequential catalog decision but not architected |
| 4 | HIGH | Architecture | OOD severity bands and routing policy by risk tier referenced but unspecified |
| 5 | HIGH | Architecture | Calibration-drift surveillance compares OPE baseline to a population predicted-value average, not to observed outcomes |

### Medium Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 6 | MEDIUM | Security | Recommendation-ID, decision-point-ID, trajectory-ID tracking-ID privacy (chapter-wide pattern; already TODO'd) |
| 7 | MEDIUM | Security | Validator four-layer specification underspecified for regime-narrative stricter rules |
| 8 | MEDIUM | Architecture | Action-catalog out-of-catalog rate lacks triage threshold and escalation policy |
| 9 | MEDIUM | Architecture | Long-horizon OPE variance growth diagnosed but not architected as a deployment constraint |
| 10 | MEDIUM | Architecture | Cross-recipe orchestration with 4.5 through 4.9 named in production-gaps but not architected |
| 11 | MEDIUM | Architecture | Multi-language patient narrative architecture (chapter-wide pattern from 4.9) |
| 12 | MEDIUM | Architecture | Regime deprecation and patient-impact handling specified in production-gaps should be in architecture |
| 13 | MEDIUM | Architecture | Patient consent three-layer flow (chapter-wide pattern from 4.5 through 4.9) |
| 14 | MEDIUM | Architecture | Idempotency and DLQ coverage on all Lambda paths (chapter-wide pattern, already TODO'd) |

### Low Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 15 | LOW | Security | SDOH-cohort PHI sensitivity TODO should be promoted to main privacy paragraph (chapter-wide pattern) |
| 16 | LOW | Security | IAM "Never `*`" stated without scoped ARN examples (chapter-wide pattern, already TODO'd) |
| 17 | LOW | Architecture | Cohort-feature lookup repeats per-stage (same pattern as 4.4-4.9) |
| 18 | LOW | Networking | `0.0.0.0/0` egress rules not explicitly forbidden in the networking specification |
| 19 | LOW | Networking | Bedrock cross-region inference profile implications not surfaced for the multi-audience narrative path |
| 20 | LOW | Networking | API Gateway resource policies and WAF posture for the recommendation API not specified |
| 21 | LOW | Voice | A few sentences slip toward documentation voice in the AWS Implementation section |
| 22 | LOW | Voice | A few long sentences with multiple subordinate clauses |

### Recommended Resolution Path

1. **Address the 5 HIGH findings before publication.** Each has a localized fix with reference language already present elsewhere in the recipe (the architecture prose, the Honest Take, the production-gaps section). The fixes are pseudocode-and-architecture-text additions, not structural rework. Estimated effort: 1-2 days of writing time.

2. **Address the chapter-wide MEDIUM findings (S2, A10, A11, A12 if not already done) as a chapter editor's pass.** These are already TODO'd in the recipe and should be consolidated into a chapter-4 preface in the next pass; deferring them to the chapter editor is acceptable.

3. **Address the recipe-specific MEDIUM findings (S3, A5, A6, A7, A8, A9, A12, A13).** Most have language already present elsewhere in the recipe that needs to be promoted into the architecture pattern. Estimated effort: 1 day of writing time.

4. **Address the LOW findings as time permits.** The voice findings (V1, V2) are stylistic preferences; the networking findings (N1, N2, N3) are explicit-statement additions; the chapter-pattern findings (S4, S5, A12) are consolidation work.

5. **After the HIGH and MEDIUM fixes, re-run the expert review cycle** to confirm the fixes are correctly placed and the recipe's overall integrity is preserved. Recipe 4.10 is the chapter's capstone; the quality bar is appropriately the highest in the chapter.

The recipe's underlying methodology, voice, clinical accuracy, and architectural shape are excellent. The HIGH findings are gaps in the architectural specification that the prose elsewhere in the recipe correctly diagnoses; closing the gaps brings the architecture up to the standard the recipe text claims. Recipe 4.10 has the potential to be the chapter's strongest recipe once these gaps are closed.
