# Expert Review: Recipe 4.7 - Care Management Program Enrollment

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-16
**Recipe file:** `chapter04.07-care-management-program-enrollment.md`

---

## Overall Assessment

This recipe is the apex of Chapter 4 in operational, clinical, and ethical complexity. It takes the uplift-and-allocation pattern from 4.4, the barrier classification from 4.5, and the multi-pathway orchestration from 4.6, and graduates them to the hardest problem class in the chapter: care management program enrollment, where the unit of decision is multi-month enrollment in a specific program for a specific duration, the resource cost is 10 to 100 times higher and the duration 10 to 30 times longer than any prior recipe, and the rationing reality (18,000 eligible patients, 1,400 slots, 1-in-13 ratio) makes every misallocation a patient who could have benefited and didn't. The Linda vignette in The Problem is the strongest opening in Chapter 4 by a margin: 72 years old, HFrEF EF 35%, T2DM A1c 8.4%, CKD 3b eGFR 38, AFib on apixaban, two recent admissions each preceded by signals the system noticed too late, the explicit contrast between the unlucky version (top-1400-by-risk-list, regression-to-the-mean reduction reported as program success) and the lucky version (HF program for the destabilization, polypharmacy in parallel for the metformin-not-adjusted-for-eGFR issue, transitional care after each admission, complex-care held in reserve for patients whose problems are less program-tractable). The closing tension ("Both versions of Linda's story are real. The first version is, regrettably, more common.") frames the recipe's central thesis exactly.

The recipe carries forward the chapter-wide hardening progress and adds care-management-specific sharpenings: the `patient-program-state` table is named as highly inferential PHI ("a row indicating 'patient recommended for high-risk complex-care program' is more sensitive than a row indicating 'patient eligible for wellness program'"), high-sensitivity programs (behavioral health, substance use, palliative care, HIV-related) get explicit tighter-controls discussion, the multi-stage allocator's program semantics (time-sensitive transitional care first, disease-specific high-fit second, complex-care third, parallel add-ons fourth) is the chapter's most operationally distinctive piece, the post-graduation observation pathway with relapse-signal detection is novel architectural content, and the "care management is rationing" closing paragraph is the chapter's most direct ethics framing yet ("There are 18,000 eligible patients and 1,400 slots; the recommender is making the choice. The way that choice gets made is the choice itself.").

The Honest Take is the strongest in Chapter 4. Six observations stand out: (1) the Obermeyer scenario is named as the canonical cautionary tale and as the chapter's central ethical concern, with explicit framing that the fix is "the combined design of the eligibility logic, the response model, the allocation rules, and the equity instrumentation"; (2) the operational-vs-modeling 75/25 ratio framing ("A program with an excellent uplift model and poor operations under-delivers. A program with mediocre modeling and excellent operations over-delivers. The order of investment is operations first, modeling second"); (3) the post-graduation observation framing ("Most care management programs spend 90 percent of their attention on the enrollment funnel and 10 percent on what happens after graduation. Build the observation pathway early"); (4) the LLM scope discipline ("They earn their keep on packaging and on rationale generation. The recommender picks. The LLM packages."); (5) the "we'll do randomization later" trap explicitly named as the worst version of the program's measurement; (6) the "highest-risk-first" reflex under capacity contraction explicitly diagnosed as a math-versus-intuition conflict that operations leadership tends to lose without explicit instrumentation.

That said, three correctness gaps need attention before publication, and the medium and low items round out the review. (1) The optimistic `cm_outreach_recent_30d_count` increment in Step 4's `dispatch_outreach` block has no reconciliation path implemented in the pseudocode for delivery failures (bounced calls, undeliverable messages, terminal-unreachable outcomes); the same High finding from 4.4, 4.5, and 4.6 is propagated forward unresolved, with sharper care-management-specific consequences because every unsuccessful outreach attempt accumulates phantom counter consumption that excludes the patient from future enrollment outreach for 30 days. (2) The `data_quality_flag` is computed in Step 1, persisted to `patient-program-state`, named in "Where it struggles" as something downstream consumers should gate on ("the `data_quality_flag` exposes this; downstream consumers should gate harder when quality is low"), and never gated in the pseudocode anywhere; the same High finding from 4.5 and 4.6 is propagated forward, and in 4.7 it is materially worse because the disenrollment evaluator's decisions have civil-rights implications and operate on patients whose data is most likely to be sparse. (3) The `human_review_pending` workflow on disenrollment decisions and cross-program transition recommendations has no SLA, no escalation, and no default action; a patient stuck in `at_risk` with a pending decision that no one reviews can either remain enrolled indefinitely consuming a slot, or be silently disenrolled when the eventual review happens with stale data; this is a 4.7-specific operational gap that does not appear in 4.4 through 4.6.

Ten chapter-wide patterns repeat (briefing/decision-ID privacy, validator specification, SDOH cohort PHI promotion, IAM ARN scoping, `0.0.0.0/0` egress, counter windowing, cohort-feature dedup, model-promotion path, cross-recipe orchestration, DLQ coverage). Voice is clean. Em dash count: 0 (verified). En dash count: 0 (verified). 70/30 vendor balance is maintained. Linda's clinical scenario is internally consistent and clinically accurate (HFrEF EF 35% is appropriate, CKD 3b eGFR 38 is correct, metformin dose adjustment for eGFR is a real polypharmacy issue, antibiotic-warfarin interaction causing bleeding is plausible, the warfarin-to-apixaban switch after the interaction is appropriate). The cost figures (HF program ~$1,800/patient, complex-care ~$400/month indefinite, TCM ~$350/episode, polypharmacy ~$600) are reasonable; the 240,000 / 18,000 / 1,400 ratios are realistic for a regional MA plan.

Priority breakdown: 0 critical, 3 high, 9 medium, 6 low. PASS by a narrow margin (3 HIGH is at the threshold; > 3 = FAIL).

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA called out explicitly with HIPAA-eligibility TODOs for SageMaker Batch Transform, Bedrock per-model coverage, SES, Pinpoint, Connect, and HealthLake. Continues the chapter pattern of not pretending any of these are static.
- Customer-managed KMS keys for every PHI store: DynamoDB tables (especially `patient-program-state`, `engagement-state`, and `enrollment-briefings` with the explicit "the per-(patient, program) state plus engagement scoring is highly inferential PHI" framing), S3 (SSE-KMS bucket-level keys), Kinesis and Firehose (server-side encryption), SageMaker training/Batch Transform/Feature Store (VPC-only with KMS keys for model artifacts and offline storage), Lambda log groups KMS-encrypted, and explicit acknowledgment that the `enrollment-briefings` table contains PHI ("the briefing contains diagnoses, social context, and clinical-trajectory framing").
- The `patient-program-state` table is framed as inferential PHI in language sharper than 4.4, 4.5, or 4.6: *"A row indicating 'patient recommended for high-risk complex-care program' is more sensitive than a row indicating 'patient eligible for wellness program.'"* The recommendation that high-sensitivity programs (behavioral health, substance use, palliative care, HIV-related) get tighter controls (narrower IAM read scopes, optional separate-table partitioning, additional CloudTrail data event capture, documented minimum-necessary access policy) is correct and earns its place in the production-gaps section. This is the chapter's strongest articulation of the program-state-as-inferential-PHI principle.
- CloudTrail data events on `patient-program-state`, `program-registry`, `enrollment-briefings`, `outreach-state`, `engagement-state`, `recommendation-log`, and `patient-profile`. Comprehensive.
- LLM prompt construction explicitly de-identifies before the Bedrock call: *"De-identify before the LLM call; re-attach identifiers in the persisted briefing."* Step 4's `briefing_context` block (with `build_clinical_summary(row.patient_id)` returning de-identified context) is the explicit place this happens, mirroring 4.4-4.6.
- Bedrock paragraph: *"Confirm in service terms that prompts and completions are not used to train the underlying foundation models."* Continues the chapter pattern.
- Patient consent and HIPAA authorization called out as a regulated communication category requiring multiple consent artifacts (HIPAA authorization for cross-program data sharing, program-specific informed consent, consent for external entity referrals). Explicit TODO to engage compliance counsel before launch.
- Production-gaps section names the chapter-wide TODOs: tracking-ID privacy, DLQ coverage, validator specification, SDOH-cohort PHI minimization, IAM ARN scoping, model-promotion path, cross-recipe orchestration, patient-facing message governance. The chapter-wide hardening pattern is preserved.

### Finding S1: `process_disenrollment_decision` and `recommend_cross_program_transitions` Have No Patient-Identity Boundary Checks

- **Severity:** MEDIUM
- **Expert:** Security (PHI integrity boundary)
- **Location:** Step 6 pseudocode, the `process_disenrollment_decision(decision_id, human_decision)` function: `decision = DynamoDB.GetItem("disenrollment-decisions", decision_id)` followed by state-machine mutations on `decision.patient_id` with no identity-boundary check on `human_decision`; the `recommend_cross_program_transitions(patient_id, prior_program_id, context)` function reads `patient-program-state` rows and writes new transition records with no validation that the calling context's `patient_id` matches the prior_program_id's recorded patient.
- **Problem:** The chapter pattern from 4.2, 4.3, 4.4, 4.5, and 4.6 enforces an identity-boundary check on engagement-event consumers and human-action consumers: when an event or action references a recommendation, briefing, or decision by ID, the consumer reads the source record and validates that the action's metadata is consistent with the source before applying any state change. Both 4.7-specific consumer paths skip this check.

  The disenrollment-decision path is the most security-sensitive consumer in this recipe because:
  1. **It writes to `disenrollment-decisions` and `patient-program-state`**, both of which are part of the audit trail. A `human_decision` arriving with mismatched metadata (a clinical lead approves disenrollment for decision_id A but the payload references decision_id B) would silently apply the wrong action to the wrong patient, then mark `human_review_pending: false` against the wrong record, contaminating both the audit trail and the patient's enrollment state.
  2. **It triggers downstream cross-program transitions** for `graduate` and `transition_to_higher_acuity` actions. A misapplied action cascades: a graduation event that should have fired for patient A fires for patient B, recommending a maintenance pathway that patient B is not actually eligible for, consuming a slot patient B's care manager has to then unwind.
  3. **It feeds the `disenrollment-decisions` audit trail** that gets read back during the monthly disenrollment-review committee cadence (named in production-gaps). A contaminated audit trail means the committee reviews disenrollment patterns against the wrong patients in the wrong cohorts, which can cause systematic equity issues to be missed or misattributed.

  The `recommend_cross_program_transitions` function is similarly exposed: it's invoked from `process_disenrollment_decision` with parameters that haven't been identity-checked, and it writes to `cross-program-transitions` keyed on `patient_id` from its caller's parameter. A bug or malformed event upstream propagates into the transition record without any defense-in-depth check.

- **Fix:** Add the identity check immediately after the decision lookup:

  ```
  decision = DynamoDB.GetItem("disenrollment-decisions", decision_id)
  IF decision is null:
      LOG("disenrollment decision lookup failed", decision_id=decision_id)
      RETURN
  IF human_decision.decision_id != decision.decision_id:
      LOG("human_decision decision_id mismatch with stored decision; dropping",
          submitted = human_decision.decision_id,
          stored    = decision.decision_id)
      emit_metric("disenrollment_identity_mismatch", value = 1)
      RETURN
  IF human_decision.reviewer_id is null:
      LOG("human_decision missing reviewer attribution; dropping")
      RETURN
  ```

  Add the same check to `recommend_cross_program_transitions`: validate that the `patient_id` parameter matches the `prior_program_id`'s recorded patient in `patient-program-state` before any cross-program candidate evaluation. Reject mismatches and emit a metric.

  Reference 4.4 Finding S1, 4.5 Finding S1, 4.6 Finding S1 as the chapter-wide pattern; the chapter editor should consolidate the identity-check guidance into a chapter-4 preface that all recipes reference.

### Finding S2: Briefing-ID, Decision-ID, and Transition-ID Embed Patient ID and Program ID in Plain Text (Chapter-Wide Pattern, Already TODO'd)

- **Severity:** MEDIUM
- **Expert:** Security (PHI minimization)
- **Location:** Step 4 pseudocode `build_briefing_id(row, run_date)`; Step 6 pseudocode `decision_id: new UUID` (acceptable here) but `transition_id: new UUID` paired with `patient_id` plus `prior_program_id` in the same record (carried in engagement events); existing TODO in production-gaps acknowledging the chapter-wide pattern.
- **Problem:** Same finding as 4.4 Finding 2, 4.5 Finding S2, 4.6 Finding S2. The recipe acknowledges the gap with a TODO that mirrors the chapter-wide fix language. Care-management-specific sharpening: the briefing_id embeds `patient_id` and the briefing's content is, by the recipe's own framing, "diagnoses, social context, and clinical-trajectory framing." The combination of an identifier that reveals patient identity and a payload that reveals stigmatized clinical content is the most sensitive ID-leakage scenario in the chapter. For the high-sensitivity programs the recipe explicitly flags (behavioral health, substance use, palliative care, HIV-related), the briefing_id format `brief-2026-04-15-pat-002148-hf` reveals patient and program category in clear text; an analogous briefing_id for a behavioral-health enrollment would reveal that the patient was being enrolled in a behavioral-health program, which is the kind of disclosure that intersects with state mental-health-confidentiality statutes (e.g., 42 CFR Part 2 for substance-use disorder records).

  The cross-program-transition record is similarly sensitive: a transition_id paired with `prior_program_id` and `recommended_program_id` in plain text reveals the patient's clinical trajectory across programs (e.g., "graduated from HF program; recommended for complex-care") which is highly inferential.

- **Fix:** Same as 4.4-4.6 Finding S2. Replace string-concatenation IDs with opaque UUID or HMAC-SHA256 over the composite. Update the Expected Results sample identifiers accordingly. For high-sensitivity programs (behavioral health, substance use, palliative care, HIV-related), the opaque-identifier requirement is non-negotiable; document this explicitly in the privacy paragraph rather than as a TODO. The cohort_features serialization carried in engagement events must be reviewed for the same minimum-necessary principle (only the cohort axes the equity dashboard consumes).

### Finding S3: Two Validators (`validate_briefing`, `validate_rationale`) Named with Inline TODOs but Not Fully Specified

- **Severity:** MEDIUM
- **Expert:** Security (regulatory, hallucination guardrails)
- **Location:** Step 4 pseudocode: `validate_briefing(briefing_parsed, observed_context = briefing_context)` with inline TODO that begins to specify the four-layer structure; Step 5 pseudocode: `validate_rationale(rationale_parsed, observed_context = rationale_context)` with an inline TODO that defers to "the chapter-wide validator pattern" without local specification.
- **Problem:** Two LLM-output validators named in pseudocode, both with inline TechWriter TODOs that acknowledge the gap and reference the chapter-wide validator pattern from 4.4-4.6. The TODOs are appropriate, but the pseudocode-as-published lacks the four-layer structure that the chapter has converged on (schema, required disclosures, prohibited content, required references). Care-management-specific reasons this matters more here than in prior recipes:

  1. **The disenrollment-rationale validator has unique stakes.** When the deterministic policy recommends disenrollment, the LLM-generated rationale is the document a clinical lead reads before deciding whether to disenroll the patient. A rationale that omits a countervailing factor (e.g., the patient just had a clinical event that explains the engagement decline; the patient's care manager went on leave for two of the four missed contacts; the patient's preferred modality was incorrectly set), or that confidently cites a policy-rule trigger that doesn't actually apply, can lead a busy clinical lead to approve a disenrollment that should not have happened. The validator must enforce that every cited engagement-history fact appears in `observed_context.engagement_history`, every cited clinical event appears in `observed_context.recent_clinical_events`, and the cited `policy_rule` matches the deterministic policy's actual triggering rule (not a hallucinated rule name).

  2. **The enrollment-briefing validator must enforce that the LLM does not propose alternative program assignments.** The recipe says explicitly: *"The LLM is decision support for a human, not autonomous disenrollment."* The same principle applies to enrollment briefings: a briefing that suggests "consider complex-care instead of HF program" overrides the deterministic ranker's choice and undermines the architectural separation between recommender and packager. The validator's prohibited-content layer must catch this.

  3. **For high-sensitivity programs, the validator must enforce additional restrictions.** A behavioral-health enrollment briefing's anticipated_concerns section that suggests "expect the patient to deny substance use" or "patient may be evasive about depression history" is appropriate for a clinical lead but inappropriate for a care manager who hasn't had cultural-competency training, and may violate stigma-reduction principles encoded in some state mental-health statutes. The validator should be configurable per program-category (high-sensitivity programs use a stricter prohibited-content list) and should require an additional human approval layer when the briefing crosses certain thresholds.

  4. **The validator's failure-handling matters substantively in 4.7.** A briefing-validator failure should fall back to a templated briefing (the recipe's TODO names this correctly: "fall back to templated fallback that lists the structured context without LLM narration"). A rationale-validator failure should NOT silently fall back to a templated rationale; it should defer the disenrollment decision with reason `validator_failed` and route to a manual-review queue, because the failure mode is "the LLM said something the validator wouldn't approve" and a silent fallback hides the signal that the prompt or model needs adjustment for a high-stakes decision path.

- **Fix:** Specify the four-layer template once and specialize per validator:

  ```
  // Shared four-layer template:
  // Layer 1: schema and length
  // Layer 2: required disclosures and identifications
  // Layer 3: prohibited content (PHI not in source, prescriber names other than
  //          the patient's, suggestions that override the deterministic policy)
  // Layer 4: required references (every fact cited must trace to observed_context)

  FUNCTION validate_briefing(briefing_parsed, observed_context):
      // Layer 1
      IF briefing_parsed.headline length > MAX_HEADLINE_LENGTH: REJECT
      // Layer 2
      IF "subject to clinical judgment" NOT IN briefing_parsed.confidence_notes: REJECT
      // Layer 3
      IF briefing suggests an alternative program assignment: REJECT
      IF briefing contains PII outside observed_context.patient_summary: REJECT
      // Layer 4
      FOR each cited_event in briefing_parsed.lead_with + .anticipated_concerns:
          IF cited_event NOT IN observed_context.recent_clinical_events
             AND NOT IN observed_context.anticipated_barriers
             AND NOT IN observed_context.patient_summary.conditions:
              REJECT (hallucinated fact)
      // High-sensitivity overlay
      IF program.category in HIGH_SENSITIVITY_CATEGORIES:
          IF briefing contains stigma-flagged language per HIGH_SENSITIVITY_BLOCKLIST: REJECT
      RETURN PASS

  FUNCTION validate_rationale(rationale_parsed, observed_context):
      // Layers 1-3 mirror validate_briefing
      // Layer 4 is sharper:
      FOR each evidence in rationale_parsed.evidence_summary:
          IF evidence NOT IN observed_context.engagement_history.events: REJECT
      IF rationale_parsed.policy_rule != observed_context.policy_rule_triggered: REJECT
      // Required: countervailing factors must include the most recent
      // clinical event if any occurred during the at-risk window
      IF observed_context has recent_clinical_event_during_at_risk_window:
          IF that event NOT IN rationale_parsed.countervailing_factors: REJECT
      RETURN PASS
  ```

  Specify failure-handling per validator: briefing failure → templated fallback that lists `briefing_context` items without LLM narration; rationale failure → defer the disenrollment decision with reason `validator_failed:<reason>` and route to manual review (do NOT silent-fallback). Reference the chapter-wide validator pattern from 4.4 Finding 3, 4.5 Finding S3, 4.6 Finding S3 / A7.

### Finding S4: SDOH-Cohort PHI Sensitivity TODO Should Be Promoted to Main Privacy Paragraph (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** TechWriter TODO in Why This Isn't Production-Ready, mirroring 4.4 Finding 6, 4.5 Finding S4, 4.6 Finding S4.
- **Problem:** Same finding as 4.4-4.6. SDOH cohort labels carried in the engagement-event payload, the recommendation log, and the per-(patient, program) state are reidentifying for small cohorts in specific geographies. In 4.7 the cohort_features attribute is referenced explicitly in `priority_components`, in the equity-floor allocator, and in the cohort-stratified outcome evaluation, making the gap especially visible. Promote the TODO content into the main *Privacy in program state and enrollment briefings* paragraph, and add the chapter-wide framing about minimum-necessary cohort axes.
- **Fix:** Promote the TODO into the main paragraph. Reference 4.4-4.6 Finding S4 for the consolidated chapter-4 preface treatment.

### Finding S5: IAM "Never `*`" Stated Without Scoped ARN Examples (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites IAM Permissions row.
- **Problem:** Same finding as 4.1-4.6. The IAM row says "Never `*`" but doesn't show scoped resource ARN examples. The TODO acknowledges the chapter-wide pattern.
- **Fix:** Either inline one or two scoped resource ARN examples for the highest-stakes actions in this recipe (`dynamodb:UpdateItem` on `patient-program-state`, `bedrock:InvokeModel` on the briefing and rationale model ARNs, `connect:*` on the care-management contact flow, `sagemaker:CreateTransformJob` on per-program model ARNs), or consolidate into a chapter-4 preface that all recipes reference.


---

## Architecture Expert Review

### What's Done Well

- The seven-component architecture (program registry, eligibility evaluation, per-program response enrichment, enrollment-decision orchestrator, outreach-and-enrollment workflow, engagement-and-retention tracking, longitudinal state and outcome evaluation) is the right shape for the problem class. The framing of *"the program registry is governance, not engineering"* extends the measure-registry pattern from 4.6 to a more complex artifact (programs have capacity, theory-of-change tags, target duration, expected per-patient cost, language and geographic support).
- Multi-stage enrollment-decision orchestrator that respects program semantics: time-sensitive transitional care first, disease-specific high-fit second, complex-care third for residual high-uplift patients, parallel add-ons fourth. This is the chapter's most operationally distinctive piece of architecture and is correctly motivated: the staging mirrors the programs' theories of change, and the per-stage greedy-by-priority allocation under capacity, equity-floor, single-active-primary, add-on-cap, and operational-feasibility constraints produces an allocation that is both auditable and explainable per-decision.
- Per-program response stack: per-program uplift (CATE) models, per-program enrollment-likelihood models, per-program engagement-prediction models, plus a program-fit score combining hard-coded theory-of-change-alignment with a learned component. The recipe correctly identifies that the response model is per-program (the HF program's uplift drivers differ from the polypharmacy program's), the enrollment-likelihood is per-program (a patient may consent to low-friction and decline high-friction), and the program-fit score forces the architecture to encode program semantics rather than treating programs as interchangeable.
- Causal-inference rigor framed correctly: propensity-matched difference-in-differences as the workhorse for evaluation, doubly-robust estimation when feasible, randomized enrollment in a fraction of slots as the gold standard, quasi-experimental designs (regression discontinuity, instrumental variables, difference-in-differences on natural experiments) as feasible alternatives. The recipe correctly names EconML and DoWhy as the workhorses, references Obermeyer 2019 as the canonical cautionary tale, and explicitly identifies that observational uplift models confound program effect with selection bias.
- Longitudinal state machine: eligible → recommended → outreach_in_progress → enrolled → engaged → at_risk → disenrolled / graduated → in_observation → re_eligible. The state machine is the source of truth for downstream consumers (program dashboards, clinician inboxes, billing, equity monitoring, outcome evaluation), and the recipe correctly identifies state-machine drift between the recommender and the case-management system as a chronic operational pain.
- Engagement-decline classification taxonomy (`no_initial_engagement`, `gradual_drop_off`, `event_driven_drop`, `modality_mismatch`, `staffing_disruption`) with retention-strategy mappings per pattern is the correct level of operational specificity. The "staffing_disruption" pattern in particular (the disruption is on the program side, not the patient's; address it operationally) is an insight that distinguishes a senior care-management architect from a junior one.
- LLM scope kept tight: enrollment briefings (decision support for care managers), patient-facing enrollment messages, mid-program engagement summaries (decision support for case rounds), disenrollment-decision rationales (decision support for clinical leads who make the actual call). Not picking the program. Not deciding to disenroll. *"The recommender picks. The LLM packages."*
- Cross-recipe coordination explicitly addressed with a stated exception: care management enrollment outreach has a separate contact budget from 4.4-4.6 routine outreach because the enrollment conversation is a distinct, infrequent interaction. The exception is correct and operationally important; documenting it in shared chapter-level config is the right approach.
- Post-graduation observation pathway with relapse-signal detection (admission, ED visit, abnormal lab, missed follow-up appointment, sharp engagement drop on related ongoing programs) is novel architectural content that's not in 4.4-4.6. The Honest Take's framing ("Most care management programs spend 90 percent of their attention on the enrollment funnel and 10 percent on what happens after graduation. The result is a population with a good first run through the program and a relapse-without-anyone-noticing problem afterward") is the correct operational insight.
- Equity instrumentation explicitly named and architected: enrollment-rate parity by cohort, per-cohort uplift, per-cohort engagement and retention and graduation, per-cohort outcome (post-program admission rate, ED rate, total cost change). The Obermeyer scenario is named explicitly as the canonical concern; the equity floors, cohort-aware retraining, and cohort-stratified evaluation are correctly identified as the combined design that makes the failure mode tractable.

### Finding A1: Optimistic `cm_outreach_recent_30d_count` Increment Has No Reconciliation Path on Delivery Failure

- **Severity:** HIGH
- **Expert:** Architecture (correctness, fairness, equity)
- **Location:** Step 4 pseudocode (`dispatch_outreach`) increments `cm_outreach_recent_30d_count` (per the Python companion's review of the implementation; the recipe's pseudocode does not show the explicit increment but the production-gaps section names the cross-recipe-coordination requirement). Step 4's `record_outreach_attempt` function shows decrement-worthy outcomes (`unreachable_terminal`, `declined`, `unreachable_pending_retry`) without any matching counter decrement. Production-gaps section's *Cross-recipe orchestration with Recipes 4.4, 4.5, and 4.6* paragraph names the cross-recipe contact-budget gap but does not specify the reconciliation path.
- **Problem:** Same High finding as 4.4 Finding 9, 4.5 Finding A1, 4.6 Finding A1, propagated forward unresolved. The chapter editor has now seen this finding at HIGH severity in four consecutive recipes; the gap has not closed.

  Care-management-specific reasons this is HIGH despite the chapter pattern:

  1. **The 4.7 counter is recipe-specific (not the cross-recipe global), but the failure mode is more durable.** The recipe correctly establishes that 4.7 enrollment outreach has a separate contact budget from 4.4-4.6. The 4.7-specific counter (`cm_outreach_recent_30d_count` per the Python companion) increments on outreach attempt and does not decrement on delivery failure or terminal-unreachable. Care management enrollment outreach typically caps at 3-5 attempts before the patient is considered unreachable; every bounce or unreachable attempt that increments without a matching decrement consumes a slot of the 30-day enrollment-outreach budget, locking the patient out of future enrollment outreach for 30 days when the original outreach never actually reached the patient.

  2. **The cohorts most affected are exactly the cohorts the equity floors are trying to protect.** Members with flaky channels (transient housing, prepaid phones with intermittent service, language-mismatch with assigned care manager, mobility limitations preventing call-back), members whose contact information is stale (recent plan-change, recent move), and members in cohorts with historical mistrust of clinical outreach are disproportionately likely to produce bounce/unreachable outcomes. They accumulate phantom counter consumption proportional to their bounce rate; after 2-3 weeks of unsuccessful attempts they hit the cap and are silenced from enrollment outreach for the full 30 days. The deferral reason on the cohort dashboard (`cm_outreach_cap_exceeded`) looks legitimate; the silencing is invisible.

  3. **The blast radius in 4.7 is enrollment-conversation-specific, which is more consequential than 4.4-4.6's routine outreach.** The recipe explicitly says: *"The enrollment conversation is the highest-priority interaction in chapter 4 and should not be routinely deferred for adherence reminders."* A counter-leak that defers enrollment conversations for the cohorts the program needs most is the chapter's most consequential reconciliation gap.

  4. **The pseudocode is what readers copy.** A TODO that says "fix this in implementation" is not the same as fixing it in the pseudocode the recipe presents as the architectural pattern. The 4.4, 4.5, and 4.6 reviews flagged this as HIGH; the gap has propagated through four recipes. The chapter editor should treat this as a chapter-wide blocker and land all four fixes together.

- **Fix:** Implement the reconciliation in the pseudocode. Add to `record_outreach_attempt`:

  ```
  CASE "unreachable":
      IF attempt_result.attempt_count >= POLICY.max_outreach_attempts:
          outreach.state = "unreachable_terminal"
          // Decrement the 4.7-specific counter to release the slot for
          // a future enrollment outreach attempt. The counter must not
          // go below zero.
          DynamoDB.UpdateItem("patient-profile",
              key = (outreach.patient_id),
              UpdateExpression = "ADD cm_outreach_recent_30d_count :neg_one",
              ConditionExpression = "cm_outreach_recent_30d_count > :zero",
              ExpressionAttributeValues = {
                  ":neg_one": -1,
                  ":zero":     0
              })
          emit_metric("cm_outreach_terminal_decrement", value=1, dimensions={
              outcome: "unreachable_terminal",
              cohort:  outreach.cohort_features
          })

  CASE "declined":
      // Decrement: a declined outreach consumed a slot but the slot
      // should not block the patient from a future enrollment
      // conversation if circumstances change (e.g., patient declines
      // initial outreach for HF program but later becomes interested
      // after a hospitalization).
      DynamoDB.UpdateItem(...)  // same pattern as above
  ```

  Add a stale-pending sweep Lambda (hourly): for outreach-state rows where `state == "queued"` or `state == "outreach_in_progress"` and `created_at` > 7 days ago with no engagement-event activity, mark `state = "stale_no_activity"` and decrement the counter. The 7-day threshold matches the typical care management outreach SLA (most plans require initial outreach within 7 business days of recommendation).

  Add a paragraph to the architecture pattern naming the invariant: *"The `cm_outreach_recent_30d_count` counter must reflect successful or recently-attempted enrollment-conversation outreach, not optimistic increments. Every increment in `dispatch_outreach` must have a matching decrement on terminal-unreachable, declined, deferred-to-future-cycle, or stale-pending outcomes. A reconciliation invariant test (per-patient counter equals the count of in-progress or successful outreach attempts within the trailing 30 days) runs nightly; divergence is alarmed. Coordinate the implementation with the parallel 4.4, 4.5, and 4.6 fixes; the chapter editor should land all four together."*

### Finding A2: `data_quality_flag` Is Computed and Propagated but Never Gates Downstream Decisions (Chapter-Wide Pattern, Sharper in 4.7)

- **Severity:** HIGH
- **Expert:** Architecture (correctness, fairness, civil-rights implications)
- **Location:** Step 1 pseudocode: `data_quality_flag: assess_source_completeness(patient_id, program)` with values `complete`, `sparse_history`, `recent_plan_change`, `cross_provider_fragmentation`; Steps 2-6 pseudocode: no gate on this flag; "Where it struggles" first bullet: *"The `data_quality_flag` exposes this; downstream consumers (specifically the disenrollment evaluator) should gate harder when quality is low."*
- **Problem:** Same High finding as 4.5 Finding A2 and 4.6 Finding A2, propagated forward unresolved. The recipe acknowledges in prose that the data-quality flag must be gated on, then never gates on it in the pseudocode. The flag is computed in Step 1, persisted to `patient-program-state`, and never read by any downstream component.

  Care-management-specific reasons this is materially WORSE in 4.7 than in 4.5 or 4.6:

  1. **The disenrollment evaluator's decisions have civil-rights implications.** The recipe's own framing in production-gaps says: *"Disenrollment-for-cause decisions have member-experience implications and may have civil-rights implications if they concentrate in protected populations."* The patients most affected by data fragmentation (mobile populations, recent plan-changers, patients seen across multiple practices, patients with multiple insurance changes) correlate strongly with the cohorts the equity floors are trying to protect. A disenrollment-for-no-engagement evaluation that operates on `cross_provider_fragmentation` data will systematically over-disenroll those cohorts because the engagement profile appears worse than it actually is (the patient is engaging through encounters the recommender's data feed doesn't see). Civil-rights consequences follow.

  2. **Six distinct downstream gates are missing**, more than in 4.5 or 4.6:
     - **Step 2 (per-program response enrichment):** doesn't downweight or skip uplift estimation for non-`complete` patients; the response model trained on `complete` data may not generalize to `cross_provider_fragmentation` data.
     - **Step 3 (enrollment-decision orchestrator):** doesn't route low-quality patients to a verification-first stage before allocating a slot.
     - **Step 4 (outreach-and-enrollment workflow):** doesn't open the enrollment briefing with a verification-first framing for low-quality patients.
     - **Step 5 (engagement-and-retention tracking):** doesn't widen confidence intervals on engagement scoring when the patient's engagement data is fragmented (the patient may be engaging through channels the tracker doesn't see).
     - **Step 6 (disenrollment-decision evaluator):** the most consequential gate; the policy rule `count_failed_retention_attempts >= POLICY.max_retention_attempts AND days_since_last_engagement >= POLICY.disenroll_no_engagement_days` doesn't distinguish "the patient has stopped engaging" from "the patient is engaging through a channel we can't see."
     - **Step 6 (cross-program transition recommender):** doesn't apply higher uncertainty to transition recommendations for fragmented-data patients.

  3. **The "we don't see the engagement" failure mode is the recipe's most consequential blind spot.** A patient enrolled in HF program through Plan A, then attributed to a different practice mid-program because they switched insurance products, then re-attributed back, has engagement data that's fragmented across the EHR feed, the case-management system, and the patient's own self-report. The closure-tracker analog from 4.6 (canonical-source-per-measure rules) is missing in 4.7's engagement scoring; the engagement profile is built from data sources that may not capture the patient's actual interaction with the program. Gating on `data_quality_flag` is the architectural primitive that would prevent the disenrollment evaluator from confidently declaring the patient has not engaged when actually the engagement data is fragmented.

  4. **The pseudocode says it should gate, then doesn't.** The "Where it struggles" first bullet names the disenrollment evaluator specifically as the consumer that should "gate harder when quality is low." The disenrollment evaluator's pseudocode (`evaluate_disenrollment` in Step 5) shows no such gating.

- **Fix:** Add explicit gating throughout the pipeline. Six places:

  1. **Per-program response enrichment (Step 2):** widen confidence intervals on uplift estimates for non-`complete` patients; mark predictions as `quality_caveat` for downstream consumers.

     ```
     IF candidate.data_quality_flag != "complete":
         uplift.ci_low  -= QUALITY_DAMPING[candidate.data_quality_flag]
         uplift.ci_high += QUALITY_DAMPING[candidate.data_quality_flag]
         priority_components.uplift_uncertainty *= QUALITY_PENALTY[candidate.data_quality_flag]
     ```

  2. **Enrollment-decision orchestrator (Step 3):** route `cross_provider_fragmentation` and `multi_source_disagreement` patients to a verification-first stage that confirms current engagement status with the patient via a low-friction portal/SMS prompt before allocating an enrollment slot.

  3. **Enrollment briefing (Step 4):** the briefing context for non-`complete` patients includes a `data_quality_caveat` field that the briefing prompt is required to surface in the briefing's `confidence_notes`. The validator enforces this.

  4. **Engagement scoring (Step 5):** widen confidence intervals on the engagement score for non-`complete` patients; the `is_at_risk` flag requires both a below-threshold score AND consistent engagement-decline signals across multiple data sources (not just one).

  5. **Disenrollment evaluator (Step 5):** the most important gate. Replace:

     ```
     IF engagement.is_at_risk AND
        count_failed_retention_attempts >= POLICY.max_retention_attempts AND
        days_since_last_engagement >= POLICY.disenroll_no_engagement_days:
         recommended_action = "disenroll_for_no_engagement"
     ```

     with:

     ```
     IF gap.data_quality_flag in ["multi_source_disagreement",
                                    "cross_provider_fragmentation"]:
         // Verification-first: do not disenroll for no engagement until
         // the engagement-data fragmentation has been resolved by direct
         // verification with the patient. Route to verification queue
         // rather than disenrollment recommendation.
         recommended_action = "verify_engagement_first"
     ELSE IF engagement.is_at_risk AND
              count_failed_retention_attempts >= POLICY.max_retention_attempts AND
              days_since_last_engagement >= POLICY.disenroll_no_engagement_days:
         recommended_action = "disenroll_for_no_engagement"
     ```

  6. **Cross-program transition recommender (Step 6):** apply a confidence cap on transitions for fragmented-data patients; flag the recommendation with `data_quality_caveat: "engagement_data_fragmented"` so the human reviewer sees the caveat.

  Add a paragraph to the architecture pattern naming the gate explicitly: *"The `data_quality_flag` is not metadata; it is an input to every downstream stage. The response enrichment widens uncertainty on non-`complete` cases. The orchestrator routes fragmented-data patients through a verification-first stage. The briefing surfaces the caveat. The engagement scorer dampens confidence. The disenrollment evaluator routes to verification rather than disenrollment for fragmented-data patients. The cross-program transition recommender flags the caveat. A 'patient is not engaging' label on a `cross_provider_fragmentation` patient is much less reliable than the same label on a `complete`-quality patient, and the architecture must encode that explicitly because the disenrollment-for-no-engagement recommendation has civil-rights implications when it concentrates in cohorts whose data is structurally more fragmented."*

  Reference 4.5 Finding A2 and 4.6 Finding A2 as the chapter-wide pattern; the chapter editor should land all three fixes together.


### Finding A3: `human_review_pending` Workflow Has No SLA, No Escalation, No Default Action; Patients Stuck Indefinitely

- **Severity:** HIGH
- **Expert:** Architecture (correctness, operational integrity, equity)
- **Location:** Step 5 pseudocode (`evaluate_disenrollment`), the `human_review_pending: true` field on persisted disenrollment-decisions; Step 6 pseudocode (`process_disenrollment_decision`), no logic for handling pending-but-unreviewed decisions; Step 6 pseudocode (`recommend_cross_program_transitions`), the `human_review_pending: true` field on cross-program-transitions; production-gaps section's *Disenrollment governance and review* paragraph mentions a "monthly disenrollment-review cadence" as governance review, but no SLA on individual decisions.
- **Problem:** The architecture has two human-in-the-loop decision points that are both correctly designed as decision-supported (not autonomous) but have no SLA, no escalation, and no default action when the human review is delayed:

  1. **Disenrollment-decision review.** When `evaluate_disenrollment` recommends `disenroll_for_no_engagement`, `disenroll_did_not_complete`, `transition_to_higher_acuity`, `extend_or_transition`, or `graduate`, the decision is persisted with `human_review_pending: true` and a clinical lead reviews the recommendation before applying the action. The pseudocode shows no logic for what happens if the clinical lead does not review within X days. Three pathological outcomes are possible:
     - **Patient remains enrolled indefinitely.** The patient is in `at_risk` state with a disenrollment recommendation pending; no review happens; the patient continues to consume a program slot for weeks or months while not engaging. The slot could have served a different patient who would engage.
     - **Patient is silently disenrolled when stale review happens.** The clinical lead reviews two months later, the engagement data is now stale, the rationale's countervailing factors are out of date, and the disenrollment is approved against a snapshot of the patient that no longer reflects their current state.
     - **The pattern concentrates in cohorts the equity floors are trying to protect.** Clinical leads with high case-load tend to triage to easy-to-resolve cases first; complex cases (which correlate with the cohorts the equity floors protect) sit longer in the pending queue. The disparate-impact instrumentation on disenrollment outcomes (named in production-gaps) won't catch this pattern because the disparate impact is in the review-latency dimension, not the eventual-outcome dimension.

  2. **Cross-program transition recommendation review.** Same pathology: the recommendation sits in `human_review_pending: true` with no SLA. A graduated HF patient whose recommended next step is enrollment in a maintenance pathway sits unattended; meanwhile post-graduation observation may detect relapse signals; the recommended cross-program transition is overtaken by an escalation to higher-acuity, but the original transition recommendation is still pending. Two recommendations on the same patient with no clear resolution.

  3. **The recipe's own framing requires this to be solved.** The Honest Take says: *"Most care management programs spend 90 percent of their attention on the enrollment funnel and 10 percent on what happens after graduation. ... A program with a tight observation-to-re-enrollment loop catches them; a program with no observation pathway watches them go through the same hospitalization, gets re-eligible, and starts the funnel from scratch."* The same logic applies to the human-review pathway: a tight review-SLA-with-escalation loop produces program decisions; no SLA produces a queue of stale pending decisions that operationally degrade the program.

  4. **The pattern is 4.7-specific.** Recipes 4.4, 4.5, and 4.6 have human-in-the-loop steps (clinician override, chase-team disposition, etc.) but the human action is invoked by an active clinical workflow (the clinician is at the visit; the chase team is on the call). 4.7 is the first recipe in Chapter 4 where the human review is asynchronous to the active workflow; the clinical lead reviews the disenrollment queue on their own cadence, not in response to a triggering event. This makes the SLA gap unique to 4.7.

- **Fix:** Architect the SLA-and-escalation pathway explicitly. Add to the architecture pattern:

  ```
  Decision-pending SLA and escalation: Both human-review queues
  (disenrollment-decisions and cross-program-transitions) operate under
  a documented SLA. Defaults:

  - Disenrollment-for-no-engagement: 7-day review SLA; if no review,
    the recommendation is auto-deferred (NOT auto-approved) for 7 more
    days with a notification escalation to the program manager. After
    14 days with no review, the decision auto-defaults to "extend_for_review"
    (the patient stays enrolled, retention attempts continue, the next
    evaluation cycle re-evaluates with current data).
  - Disenrollment-did-not-complete (program duration met): 14-day
    review SLA; if no review, auto-defaults to "graduate_with_partial_credit"
    (the patient is graduated; the partial-credit metadata captures the
    incomplete components; the equity dashboard logs).
  - Transition-to-higher-acuity (deterioration during enrollment):
    72-hour review SLA; clinical urgency drives the tighter SLA. If no
    review within 72 hours, escalation to the medical director and an
    automatic transition recommendation is surfaced as urgent in the
    care management queue.
  - Cross-program transition (graduation context): 14-day review SLA;
    if no review, auto-expires; the transition recommendation is logged
    but does not result in enrollment. Patient is re-evaluated for
    cross-program candidacy in the next eligibility cycle.
  - Cross-program transition (relapse context): 7-day review SLA; if
    no review, escalation to program manager.

  All defaults err toward the patient retaining program access, not
  toward disenrollment, because the equity consequences of erroneous
  disenrollment are larger than the equity consequences of erroneous
  retention.

  The SLA dashboard is monitored daily; per-cohort review-latency
  metrics are tracked alongside per-cohort disenrollment-rate metrics
  in the equity instrumentation. Disparities in review latency are
  treated as fairness signals just like disparities in eventual outcome.
  ```

  Also add the SLA logic to the pseudocode:

  ```
  FUNCTION sweep_pending_decisions(run_date):
      pending_disenrollments = DynamoDB.Query(
          "disenrollment-decisions",
          filter = "human_review_pending = :true"
      )
      FOR each decision in pending_disenrollments:
          age_days = run_date - decision.recommended_at
          sla_days = SLA[decision.recommended_action]
          IF age_days >= sla_days:
              apply_default_action(decision)
              emit_metric("disenrollment_sla_breach", value=1, dimensions={
                  recommended_action: decision.recommended_action,
                  cohort:             decision.rationale_context.patient_summary.cohort,
                  age_days:           age_days
              })

      // Same for cross-program-transitions
  ```

  Reference Recipe 4.6's data_quality flag finding for the parallel "patient stuck in pending" pattern (the `human_review_pending` queue is structurally similar to the verification-first queue 4.6 needs but doesn't have either).

### Finding A4: Per-Patient Cohort-Feature Lookup Repeats N Times Per Patient (Same Pattern as 4.4 / 4.5 / 4.6)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 2 pseudocode (`enrich_eligible_candidates`), the `cohort_features = lookup_cohort_features(candidate.patient_id)` call inside the per-(patient, program) loop; Step 3 pseudocode (`allocate_enrollments`), the `cohort_features = candidate.cohort_features` reference inside the per-stage loops.
- **Problem:** Same finding as 4.4 Finding 13, 4.5 Finding A4, 4.6 Finding A4. The enrichment loop's per-(patient, program) cohort-feature lookup repeats for every candidate on the same patient. With 4-7 programs per patient and 18,000 eligible patients, the gap multiplies redundant DynamoDB reads.

  Additional consistency concern (carried forward from prior recipes): a process that updates `patient-profile.sdoh_cohort` between two reads in the same enrichment run produces inconsistent cohort assignments across the same patient's program candidates. Equity-floor allocator decisions depend on consistent assignment.

- **Fix:** Hoist the cohort-feature cache out of the per-(patient, program) loop. Build it once per unique patient before the enrichment walk. Reference 4.4 Finding 13, 4.5 Finding A4, 4.6 Finding A4 as the chapter-wide pattern; the chapter editor should consolidate into a chapter-4 preface.

### Finding A5: 15 Model Artifacts (3 Families × 5 Programs) Without Coordinated Promotion, Cohort-Calibration Gate, or Versioning Semantics

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Architecture diagram's `M1[SageMaker Training\nperiodic retrain]` node with arrows to `H2`, `H3`, `H4` (uplift, likelihood, engagement Batch Transforms); "Why These Services" section lists three model families per program; existing TODO acknowledging the model-promotion gap.
- **Problem:** Same chapter-wide pattern as 4.4-4.6, sharper here because the model count is materially larger. Three model families × 5 programs = 15 model artifacts per portfolio refresh cycle. Care-management-specific reasons this matters more than in prior recipes:

  1. **Coordination across families is non-trivial.** A new uplift model for the HF program changes the response landscape for HF; the enrollment-likelihood model trained on the prior uplift model's recommendations may no longer be calibrated. The promotion path needs to handle bulk family promotions (all three HF models replaced together) versus single-family promotions (just the HF uplift, not likelihood or engagement) with explicit documented rationale for why the chosen mode is safe.

  2. **The clinical-validation gate matters more than in prior recipes.** A misranked uplift score for a complex-care candidate doesn't just put the wrong gap on a visit agenda (4.6); it allocates a multi-month, multi-thousand-dollar slot to the wrong patient and excludes a patient who would have benefited. The clinical-validation suite must include cohort-stratified ranking comparisons (does the new uplift model produce different rankings for the cohorts the equity floors protect?), calibration plots (is the new model well-calibrated against held-out historical-randomized cohorts?), and propensity-matched difference-in-differences validation (does the new model's predictions agree with the gold-standard causal estimate within tolerance?).

  3. **The Obermeyer scenario is the canonical concern.** Per the Honest Take: *"A response model trained on observational enrollment data, where enrollment was historically allocated by clinician referral and patient engagement responsiveness, will encode the demographic and access patterns of who got referred and who got reached."* The promotion path's cohort-calibration gate is the architectural primitive that prevents an Obermeyer-style failure from being deployed quietly.

  4. **Rollback semantics are operationally critical.** An uplift model that's deployed and discovered to under-rank a protected cohort needs to be reverted within hours, not days. The rollback should be an alias-pointer change in SageMaker Model Registry, not a redeploy. The architecture diagram doesn't show this primitive.

- **Fix:** Same as 4.4-4.6 Finding A8. Add a paragraph specifying the promotion path with the cohort-calibration gate as a hard gate (not a warning):

  ```
  Model promotion: SageMaker Model Registry tracks all 15 model artifacts
  in pending_review state after training. A canary Batch Transform job
  runs the new artifact against a frozen evaluation cohort in parallel
  with production. Outputs are compared on: rank correlation, top-K
  agreement, cohort-stratified calibration error (per-cohort within
  tolerance), and propensity-matched DiD agreement (within stated CI).
  Promotion fails if cohort-calibration error exceeds threshold for any
  monitored cohort (language, SDOH cohort, age band, race/ethnicity
  where lawfully usable). This is a hard gate, not a warning.
  Promotion is per-family per-program by default (HF uplift can be
  promoted independent of HF likelihood); coordinated bulk promotion
  is available with explicit documented rationale. Rollback is a
  one-click alias-pointer change in Model Registry.
  ```

  Reference Recipe 7.x for the deeper treatment.

### Finding A6: `operational_feasible`, `cross_recipe_conflicts`, and `clinical_deterioration_detected` Are Referenced but Undefined

- **Severity:** MEDIUM
- **Expert:** Architecture (specification gap)
- **Location:** Step 3 pseudocode (`allocate_stage`): `IF NOT operational_feasible(candidate, program)` and `IF cross_recipe_conflicts(candidate, program)`; Step 5 pseudocode (`evaluate_disenrollment`): `IF clinical_deterioration_detected(patient_id, program_id)`.
- **Problem:** Three filter functions are central to the allocation, cross-recipe coordination, and mid-program escalation logic, and all three are referenced without specification. Each carries non-trivial business logic and equity implications:

  1. **`operational_feasible(candidate, program)`** decides whether the patient's program assignment is structurally viable: language match with available care-manager staffing, geographic feasibility (some programs are regional), modality compatibility (in-person versus telephonic versus video), and any program-specific operational requirements. A naive implementation can systematically exclude rural patients (no local CM staffing), non-English speakers (no language match in the assigned care-manager pool that day), or members in regions with limited program coverage. Equity instrumentation should track operational-feasibility-driven exclusions per cohort; without spec'ing the function, the equity dashboard can't sample the right inputs.

  2. **`cross_recipe_conflicts(candidate, program)`** is the gate that prevents over-enrollment across Recipes 4.4, 4.5, 4.6, 4.7. The recipe says some combinations should not be enrolled simultaneously, but doesn't specify which: should a patient currently in a high-touch wellness program (4.4) be excluded from complex-care enrollment? Should a patient with active adherence intervention (4.5) be excluded from polypharmacy add-on (which is structurally a more intensive version of the same intervention)? Should a patient with multiple high-urgency open care gaps (4.6) be excluded from disease-specific enrollment if the gaps suggest complex-care fit instead? These are policy decisions that the chapter-level cross-recipe coordination policy should specify.

  3. **`clinical_deterioration_detected(patient_id, program_id)`** is the trigger for mid-program escalation to higher-acuity programs. The function's definition determines whether escalation happens too aggressively (false positives consume complex-care slots) or too conservatively (false negatives miss patients who need escalation). The recipe's prose mentions specific signals (admissions during the program window, ED visits, sharp lab changes) but doesn't specify thresholds, time windows, or per-program escalation criteria.

- **Fix:** Either inline the specifications (sketch is fine) or add explicit TODO references to a forthcoming chapter-level filter specification:

  ```
  // operational_feasible(candidate, program):
  //   Returns false when any of the following conditions hold:
  //     - patient.preferred_language NOT IN program.supported_languages
  //         AND program does not support interpreter-mediated outreach
  //     - patient.region NOT IN program.supported_regions
  //         AND program does not support remote-only delivery for that region
  //     - patient.preferred_modality NOT IN program.supported_modalities
  //         AND program does not support modality-flexibility
  //     - patient has documented mobility/access constraint that conflicts
  //         with program's required visit modality
  //   Equity instrumentation: track operational-feasibility exclusions per
  //   cohort; high exclusion rates in protected cohorts trigger committee
  //   review.

  // cross_recipe_conflicts(candidate, program):
  //   Returns true when any of the following hold (per chapter-level
  //   cross-recipe coordination policy):
  //     - patient is currently enrolled in a high-touch program from 4.4
  //         that conflicts with the proposed primary program
  //     - patient is in active adherence intervention (4.5) AND the
  //         proposed program is polypharmacy (structural duplication)
  //     - patient has 5+ open high-urgency care gaps (4.6) suggesting
  //         complex-care fit; do not allocate disease-specific
  //   Reference: chapter-level cross-recipe coordination spec.

  // clinical_deterioration_detected(patient_id, program_id):
  //   Per-program escalation thresholds:
  //     - HF program: 1+ HF-related admission OR 2+ HF-related ED visits
  //         during the enrollment window; OR weight-trend reaches
  //         pre-decompensation threshold; OR BNP doubles from baseline
  //     - Diabetes management: A1c rises >1.0% from baseline; OR new
  //         hypoglycemic-event admission
  //     - Complex-care: 2+ admissions in any 6-month period during enrollment;
  //         OR new behavioral-health crisis
  //     - Polypharmacy: severe medication-related adverse event
  //   Returns the most-acute deterioration signal; null if none.
  ```

  These don't need to be production-grade specifications but they should be concrete enough that a reader can implement them and an equity reviewer can audit them.

### Finding A7: `engagement_scoring_function` and `engagement_scoring_profile` Are Referenced as Registry Attributes but the Pseudocode Implies Executable Code

- **Severity:** MEDIUM
- **Expert:** Architecture (specification gap)
- **Location:** Step 5 pseudocode (`score_engagement`): `engagement_score = program.engagement_scoring_function(profile)`; the recipe describes engagement profiles as program-specific (HF: weekly check-in attendance + weight-monitoring submission rate; complex-care: monthly visit attendance + care-plan-goal progress; polypharmacy: session attendance + prescriber-action follow-through).
- **Problem:** The recipe stores the engagement scoring function as a program-registry attribute, implying the registry contains executable code (or a reference to executable code). Real registries are typically JSON or YAML; storing executable code is impractical and a security exposure (registry mutation can change scoring behavior without code review).

  The Python companion's review noted this as Finding 7 ("`score_engagement` Accepts `program_lookup` But Does Not Use the Program Object") and confirmed the implementation hard-codes scoring into a module-level table rather than reading from registry. The recipe pseudocode and the implementation diverge.

- **Fix:** Two reasonable patterns:

  1. **Registry stores configuration, not code.** The registry's `engagement_scoring_profile` field is a declarative structure: a list of engagement metrics (`scheduled_contact_attendance_rate`, `self_reported_data_submission_rate`, etc.), per-metric weights, and a thresholding function specification (e.g., `linear_combination` or `geometric_mean`). The deployed engagement-scoring service reads the configuration and applies the named function (which is implemented in code, version-controlled). The function name is a registry-validated allowlist; new function names require a code change and review.

  2. **Registry references a versioned function module.** `engagement_scoring_function: "hf_program_v3"` references a function in a versioned module (`engagement_scoring/hf_program_v3.py`). The function's behavior is code-reviewed; the registry only points to it. Function-version transitions are explicit and require both the registry update and the code deployment.

  Either pattern is acceptable; the recipe should pick one and specify it. The current pseudocode's `program.engagement_scoring_function(profile)` syntax is misleading because it implies the function lives in the registry payload itself.

### Finding A8: Linda's Vignette Mentions Bluetooth Scale as Program-Provided Equipment but Architecture Doesn't Address Equipment Provisioning

- **Severity:** MEDIUM
- **Expert:** Architecture (operational completeness)
- **Location:** Step 4 sample briefing JSON: *"Uncertainty about whether he can do daily weights reliably (no scale at home; the program covers a Bluetooth scale)."* (Note: the sample briefing is for a different patient, "Mr. Garcia," not Linda; minor consistency issue worth flagging separately.)
- **Problem:** The recipe's sample briefing mentions program-provided equipment (a Bluetooth scale for the HF program) as a barrier-resolution strategy, and the recipe's prose elsewhere references self-reported weight monitoring. But the architecture has no component for equipment provisioning, supply-chain tracking, equipment-data ingestion, or equipment-failure handling. For programs that depend on connected-device data (Bluetooth scales, glucometers, BP cuffs, pulse oximeters for COPD programs), the equipment is a first-class operational component:

  1. **Equipment ordering and shipping.** Once a patient enrolls, the equipment needs to ship; the equipment vendor's order-fulfillment SLA determines how quickly the program can begin meaningful monitoring; delays in equipment delivery delay the program's effective start.

  2. **Equipment-data ingestion.** The Bluetooth scale's readings flow into the engagement profile via the equipment vendor's data feed (cellular-connected devices) or the patient's app sync (Bluetooth-only devices). The data feed is a separate ingestion path that needs reliability monitoring.

  3. **Equipment-failure handling.** When the scale stops syncing, the engagement-scoring system can't distinguish "patient stopped weighing themselves" from "scale battery died" from "data feed broke." Without an equipment-health signal, the engagement-scorer's "patient is at risk" flag misclassifies equipment failures as patient disengagement, triggering retention attempts that are inappropriate.

  4. **Equipment-return logistics.** Programs typically request equipment return after graduation or disenrollment; the operational component for this is missing from the architecture.

  5. **Reused-equipment fairness.** Equipment is expensive; some programs reuse equipment across patients (refurbished returns). A patient receiving refurbished equipment may have a different reliability profile than one with new equipment; the engagement-scoring should account for this.

  This isn't a critical gap because not every care-management program involves equipment, but the recipe explicitly mentions the Bluetooth scale and the architecture should address it briefly.

- **Fix:** Add a paragraph to the architecture pattern or to Variations and Extensions:

  *"Connected-device equipment provisioning: For programs that depend on connected-device data (HF programs with Bluetooth scales, diabetes programs with glucometers, COPD programs with pulse oximeters), the architecture extends to include an equipment-fulfillment workflow (orchestrated via Step Functions, integrated with the equipment vendor's order API), an equipment-data ingestion path (vendor cellular feed or patient-app sync, separate from the case-management-system event feed), an equipment-health signal (last-sync timestamp; battery level if reported; data-quality flags), and an equipment-return workflow on disenrollment or graduation. Equipment-health signals must be incorporated into engagement scoring so that equipment failures (battery, sync break, vendor outage) are not misclassified as patient disengagement."*

  Also fix the consistency issue: the sample briefing mentions "Mr. Garcia" but the opening vignette is "Linda." Rename to a single patient consistently throughout the Expected Results samples.

### Finding A9: Chained-Enrollment Sequencing (e.g., HF Program → Maintenance Pathway, TCM → Disease-Specific) Mentioned Conceptually but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** "Where This Sits in the Chapter" section mentions cross-program transitions and the engagement tracker; Variations and Extensions mentions sequencing; Step 6 pseudocode (`recommend_cross_program_transitions`) handles single-step transitions but not multi-step chains.
- **Problem:** Care management programs frequently chain in operationally-meaningful ways:
  - **TCM → disease-specific:** A patient enrolled in TCM after discharge can transition to disease-specific (HF program) for ongoing management once the 30-day TCM episode completes.
  - **Disease-specific → maintenance:** A patient who completes the 12-week HF program transitions to a light-touch maintenance pathway (monthly check-in, automated weight monitoring) for the next 6-12 months.
  - **Disease-specific → complex-care:** A patient who deteriorates during the disease-specific program transitions to complex-care for longer-term coordination.
  - **Disease-specific → re-enrollment:** A patient who graduated 6 months ago and shows relapse signals re-enrolls in the same program with adjusted intensity.

  The pseudocode's `recommend_cross_program_transitions` handles a single transition step (prior_program → recommended_program) but doesn't show:
  - **Multi-step chain tracking** (the patient is in a "TCM → HF program → maintenance" chain; chain ID and chain position are needed in the recommendation log).
  - **Predecessor-successor linkage** (the maintenance pathway was triggered by HF program graduation; the linkage matters for outcome attribution).
  - **Chain-level outcome evaluation** (the propensity-matched DiD comparison for "the chain" rather than for any single step).

  Without these primitives, the longitudinal narrative of a patient's care management journey is fragmented across single-step records, and the outcome evaluation can't compute chain-level value (which is the operationally-relevant unit for ROI calculations).

- **Fix:** Same as 4.6 Finding A6 with care-management extensions. Add a small subsection (200-300 words) to the architecture pattern:

  ```
  Chain-aware longitudinal tracking: The recommendation log adds
  chain_id (UUID), chain_position (1, 2, 3...), chain_total (length
  if known), and predecessor_recommendation_id (nullable). The
  enrollment-decision orchestrator initializes a chain when a patient
  is allocated to a primary program for the first time in their
  current journey; subsequent transitions, re-enrollments, and
  maintenance-pathway transitions inherit the chain_id. The
  outcome-evaluation pipeline aggregates by chain_id rather than by
  single-step; the propensity-matched DiD is computed for the chain's
  trajectory versus the matched-control trajectory. The chain
  terminates when the patient has been disenrolled or graduated with
  no successor recommendation for the chain's defined cool-down
  window.
  ```

  Reference Recipe 14.x for full multi-stage stochastic-program treatment.

### Finding A10: Linda Vignette Internally Consistent but Missing Acknowledgment of CMS-Specific Documentation Requirements That Constrain Architecture

- **Severity:** MEDIUM
- **Expert:** Architecture (regulatory, vendor-agnostic versus regulatory-specific)
- **Location:** "What Counts as a Care Management Program" subsection mentions CMS reimburses TCM under specific structures; "Why This Isn't Production-Ready" section mentions annual and contractual reporting requirements; the Linda vignette describes the four programs and their costs but does not address the CCM, PCM, TCM CPT-code documentation requirements that constrain how the engagement events must be captured.
- **Problem:** CMS Chronic Care Management (CCM, CPT 99490, 99491, 99437, 99439), Principal Care Management (PCM, CPT 99424-99427), and Transitional Care Management (TCM, CPT 99495, 99496) have specific documentation requirements that operationally constrain the architecture:

  1. **Time-tracking for CCM is per-calendar-month, with minimums and increments.** CCM 99490 requires 20 minutes of clinical staff time per month; 99491 requires 30 minutes of physician time; 99437/99439 are add-on codes for additional time. The engagement-event stream must capture per-event start and end timestamps with sufficient granularity to support time-aggregation for billing. This isn't optional; the CMS documentation requirements are a precondition for billing.

  2. **TCM 99495/99496 requires a face-to-face visit within 7 or 14 days of discharge.** The engagement-event stream must distinguish telephonic outreach from in-person visit from televisit; only the qualifying interaction satisfies the CMS requirement.

  3. **Patient consent for CCM/PCM is annual and program-specific.** The recipe's consent pseudocode mentions consent capture but doesn't differentiate the regulatory requirements for CMS-billable programs (where consent format is prescribed) from non-billable programs (where consent format is plan-determined).

  4. **The "complex-care" program archetype is regulatory-flexible.** Complex-care can be billed under CCM (chronic conditions plus 20+ minutes/month) or under value-based contract terms (risk-sharing arrangement with the plan); the architecture's complex-care implementation should declare which regulatory frame applies because the documentation requirements differ.

  The recipe's vendor-neutral framing is largely correct (CMS billing is mentioned as a wrinkle), but the architectural implications of CMS documentation requirements are under-developed. A team building this without addressing the time-tracking-and-documentation constraints will discover at first billing cycle that the engagement-event payload doesn't have the fields the CMS billing process requires.

- **Fix:** Add a paragraph to the architecture pattern:

  *"CMS billing-readiness: Engagement events must capture per-event start and end timestamps (clinical-staff time tracking for CCM 99490; physician time for 99491; add-on time increments for 99437/99439); the modality of the interaction (telephonic, video, face-to-face) for TCM qualifying-visit determination; and the patient-consent linkage (annual CCM consent; per-episode TCM authorization). The engagement-event schema includes the CMS-billing-relevant fields as first-class attributes; the billing pipeline aggregates them per-month per-patient per-CPT-code. Programs operating under value-based contracts have different documentation patterns (typically lighter than CMS fee-for-service); the architecture supports both modes via per-program billing-frame configuration in the registry. Plans pursuing CMS-billable care management should engage CMS billing experts during architecture review; the documentation requirements are detail-heavy and audit-exposed."*


---

## Networking Expert Review

### What's Done Well

- VPC endpoint list is comprehensive: *"VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis, Firehose, KMS, CloudWatch Logs, SageMaker Runtime, Step Functions (`states`), EventBridge (`events`), Glue, Athena, STS, SES, Pinpoint, Connect, HealthLake."*
- Vendor-data-feed connectivity properly addressed: *"EHR FHIR feeds typically arrive via PrivateLink, Direct Connect, or SFTP-over-VPN. Care management system integrations vary by vendor; PrivateLink or VPN preferred."*
- Encryption in transit specified throughout. VPC Flow Logs enabled.
- Amazon Connect HIPAA-eligible call recording explicitly addressed.

### Finding N1: `0.0.0.0/0` Egress Disallow Not Stated Explicitly (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row.
- **Problem:** Same finding as 4.1-4.6. The VPC row says "restrict egress with security groups" but doesn't explicitly disallow `0.0.0.0/0` egress on Lambda subnets.
- **Fix:** Add chapter-wide language: *"No `0.0.0.0/0` egress from any Lambda subnet. NAT egress restricted by security group to specific IP ranges or hostnames (case-management vendor APIs without PrivateLink, equipment-vendor APIs, telephony providers if applicable). All other outbound traffic must go through VPC endpoints."*

### Finding N2: Care-Management-Vendor Integration Credential Posture Not Specified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Architecture diagram's `A8[Care Management System Events]` source; "Why These Services" section, Connect mention; "Why This Isn't Production-Ready" *Multi-source state-machine reconciliation* paragraph.
- **Problem:** Many plans run a mix of in-house care management (built on Connect) and vendor-delivered care management (Optum, Evolent, AmeriHealth Caritas, etc.). Each vendor has its own integration pattern: some expose REST APIs with OAuth client credentials; some require event-driven webhooks with HMAC-signed payloads; some use SFTP-based batch event drops; some have proprietary middleware. The credential and connectivity posture varies widely.

  Care-management-specific reasons this matters:

  1. **Cross-vendor data-feed reliability is a chronic problem.** The recipe's "Where it struggles" section names *"Cross-program coordination across vendor and in-house programs"* as a known pain point: cross-vendor visibility into engagement and outcomes can be poor, and the recommender's view of program state can diverge from the vendor's actual record. Contractual data-feed requirements are the durable fix, but the network/credential posture has to support the contractual SLAs.

  2. **Vendor-care-management data is PHI under HIPAA and additionally constrained by BAA and downstream subcontractor agreements.** Plans operating value-based contracts often have their care-management vendor as a subcontractor; the data-flow has BAA implications.

  3. **Some vendor integrations require dedicated network paths.** Some vendors require site-to-site VPN with their data center; some require AWS PrivateLink endpoints in their VPC; some require dual-direction TLS with mutual certificate authentication.

- **Fix:** Add a paragraph to the production-gaps section or to the architecture description:

  *"Care-management-vendor connectivity: Vendor integration patterns vary widely. REST API patterns require OAuth client credentials managed in Secrets Manager with KMS encryption and rotation policies; webhook patterns require HMAC verification on inbound events; SFTP patterns require key-managed file drops. Each vendor's BAA establishes the data-flow boundary; the integration layer enforces the boundary. For vendors that require dedicated network paths (site-to-site VPN, PrivateLink, mutual TLS), establish the connection during onboarding; budget realistic onboarding-time for vendor connectivity (often 4-8 weeks). Cross-vendor program-state reconciliation is operationally important; design the recommender's view to be reconciliation-tolerant rather than strict-source-of-truth."*

### Finding N3: HealthLake Mentioned as Optional but FHIR API Encryption / mTLS Posture Not Specified (Same Pattern as 4.6 Finding N3)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** "Why These Services" *AWS HealthLake* paragraph; existing TODO on HealthLake pricing / HIPAA eligibility.
- **Problem:** Same finding as 4.6 Finding N3. The recipe correctly flags HealthLake as optional for fine-grained FHIR clinical data but neither pattern's network posture is fully specified.
- **Fix:** Same as 4.6 Finding N3. Add the TLS / mTLS / PrivateLink / Direct Connect language to the HealthLake paragraph.

---

## Voice Reviewer

### What's Done Well

- Linda's vignette is the chapter's strongest opening. The clinical specificity (HFrEF EF 35%, T2DM A1c 8.4%, CKD 3b eGFR 38, AFib on apixaban), the operational specificity (240,000 members, 18,000 eligible, 1,400 slots, top 8% by predicted admission risk, 41% 12-month admission probability), the social context (lives alone in fourth-floor walkup with temperamental elevator, daughter at 90 minutes' distance, two specific recent admissions with the in-retrospect signals, the metformin-not-adjusted-for-eGFR detail in the lucky-version closing), and the explicit unlucky-versus-lucky contrast is the most directly contrarian opening in the chapter.
- *"Both versions of Linda's story are real. The first version is, regrettably, more common."* The dual-narrative-with-acknowledgment closing is the chapter's clearest articulation of the gap between dashboard-success and outcome-success.
- Six wrinkles framing is the recipe's central pedagogical structure: program slots are limited and expensive, programs have theories of change, response prediction is harder than risk prediction, ROI math is regulatory and contractual, care management is rationing, enrollment is not one-time. The numbered-wrinkles structure is heavy but works because each wrinkle is genuinely distinct and cumulative.
- *"The recommender picks. The LLM packages."* Same single-line framing as 4.5 and 4.6, applied to the highest-stakes packaging surface in the chapter.
- *"The thing that surprises people coming from generic ML backgrounds is how much of the work is operational, not modeling. ... A program with an excellent uplift model and poor operations under-delivers. A program with mediocre modeling and excellent operations over-delivers. The order of investment is operations first, modeling second."* The 25/75 framing is the chapter's clearest articulation of where care-management programs actually spend their time.
- *"The thing I'd do differently the second time: invest in the post-graduation observation pathway before the initial enrollment optimization."* The personal-confession-with-explicit-ordering framing is exactly the CC voice the chapter rewards.
- *"Last point, because it's specific to this use case: care management is rationing, and rationing decisions in healthcare deserve more rigor than retail recommendation decisions."* The closing explicit-ethics paragraph is the chapter's most direct ethics framing yet.
- The "we'll do randomization later" trap explicitly named: *"Two years later they still haven't randomized. ... Don't accept 'no randomization' as the durable state; it's the worst version of the program's measurement."* This is operational-veteran framing.
- The "highest-risk-first" reflex under capacity contraction explicitly diagnosed: *"The mathematical reality is that under capacity constraint, the patients you should prioritize are the ones with highest uplift, which is not necessarily the highest-risk patients. ... Have it explicitly, with the math, with the cohort instrumentation."* This is the kind of mathematical-versus-political framing that distinguishes the recipe.
- Em dash check: 0 (verified). En dash check: 0 (verified). 70/30 vendor balance: clean. Marketing-language scan: two borderline "high-leverage" hits (lines 818 and 1798), both colloquial uses meaning "leverage point," consistent with 4.6's voice.

### Finding V1: Closing "Build the Second One" Paragraph Is the Chapter's Strongest Single Paragraph; Preserve Verbatim

- **Severity:** N/A (call-out)
- **Expert:** Voice
- **Location:** Honest Take, final paragraph: *"A program that optimizes for the easiest-to-enroll, easiest-to-retain, easiest-to-graduate cohort produces a beautiful dashboard and quietly rations away from the cohorts the program was supposed to serve. A program that optimizes thoughtfully, with explicit equity instrumentation and randomized validation, may have a less impressive dashboard and produce more durable value over time. The two are not the same. Build the second one."*
- **Problem:** Not a finding. Worth flagging to the editor: this paragraph synthesizes the recipe's central tension (rationing decisions versus dashboard performance) into four sentences that work as both a concrete operational directive and a values statement. The "Build the second one" closing is the chapter's most direct call-to-action.
- **Fix:** None. Note for the editor: keep verbatim.

### Finding V2: Sample Briefing in Expected Results References "Mr. Garcia" but Opening Vignette Is Linda

- **Severity:** LOW
- **Expert:** Voice (continuity)
- **Location:** Expected Results, "Sample care manager enrollment briefing" JSON: `"headline": "..."` and `"lead_with": "Mr. Garcia was admitted in February for HF decompensation..."`. The opening vignette establishes Linda as the running example.
- **Problem:** Minor continuity break. The opening vignette uses Linda; the closing samples switch to Mr. Garcia. A reader following the recipe end-to-end loses the through-line. The patient-state JSON also uses `pat-002148` as the patient_id without consistent naming across samples.
- **Fix:** Either (a) rename Mr. Garcia to Linda throughout the Expected Results, with consistent details that map to the opening vignette (HFrEF decompensation in February starting with the furosemide gap, etc.), or (b) introduce Mr. Garcia explicitly earlier in the recipe as a second example. Option (a) is lighter; option (b) is more thorough but requires more text.

### Finding V3: "High-Leverage" Phrasing Twice; Defensible as Colloquial

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Step 3 pseudocode comment: *"the first 7-14 days post-discharge are the highest-leverage window"*; Variations and Extensions: *"reducing the time-to-outreach from days to hours captures more of the high-leverage early window."*
- **Problem:** Same colloquial-versus-corporate-marketing tension as 4.6 Finding V2. Both uses are "leverage point" sense, not "leverage AWS services" verb. Acceptable in context. If the editor's pass tightens marketing-adjacent terminology generally, these are the candidates.
- **Fix:** Optional. If changed: *"the highest-impact window"* or *"the most consequential window"* preserves the meaning.


---

## Stage 2: Expert Discussion

**Overlap: Architecture A1 (counter reconciliation) and the chapter-wide pattern.** Counter reconciliation has now appeared as a HIGH finding in 4.4, 4.5, 4.6, and 4.7 with the same fix specification each time. The 4.7 counter is recipe-specific (`cm_outreach_recent_30d_count` rather than the cross-recipe `outreach_recent_total_30d_count`), but the pathology is identical: optimistic increment without delivery-failure or stale-pending decrement, with disparate-impact consequences for cohorts whose contact information is most likely to bounce. The chapter editor should treat this as a chapter-wide blocker and land all four fixes together with a chapter-4 preface that names the cross-recipe contract.

**Overlap: Architecture A2 (`data_quality_flag` not gating), Security S1 (identity boundary checks), Architecture A6 (undefined filter functions), Architecture A7 (engagement scoring function semantics).** Four findings touch the question of "what does the system do when an input signal is unreliable or unspecified." A2 is unreliable-source-data; S1 is unverified-event-attribution; A6 is unspecified-filter-behavior; A7 is unspecified-registry-attribute-semantics. The architectural pattern is the same in all four: defensive validation should be explicit in pseudocode rather than implicit, and unspecified semantics in the recipe propagate into mis-specified or unsafe implementations. Resolution: in all four cases, the pseudocode should show the defensive check or the explicit specification rather than referencing functions whose behavior is left to implementers.

**Overlap: Architecture A3 (`human_review_pending` SLA) and Architecture A9 (chained-enrollment sequencing).** Both touch longitudinal state management for human-driven decisions. A3 is "what happens when a human review is delayed"; A9 is "how does the system track multi-step program journeys for outcome attribution and re-enrollment evaluation." Resolution: A3 needs an SLA-and-escalation primitive (with cohort-stratified review-latency monitoring as part of equity instrumentation); A9 needs a chain-tracking primitive (chain_id, predecessor_recommendation_id, chain-level outcome aggregation). Both are missing and both are 4.7-specific.

**Overlap: Architecture A5 (model promotion path) and the chapter-wide pattern.** Same as 4.4-4.6, sharper here because the model count is materially larger (15 model artifacts versus 4-5 in prior recipes). The cohort-calibration-as-hard-gate language in the fix is consistent with 4.6 Finding A8.

**Overlap: Architecture A8 (Bluetooth scale equipment provisioning) is uniquely 4.7.** No prior chapter recipe has involved equipment; 4.7 is the first. The architectural primitives for equipment fulfillment, equipment-data ingestion, equipment-health signal incorporation, and equipment-return logistics are all genuinely new and worth a brief paragraph in the architecture pattern.

**Overlap: Architecture A10 (CMS billing-readiness) is uniquely 4.7.** No prior chapter recipe has been CMS-billable in the same way (4.5's adherence work is medication-management adjacent but not CMS-billable as a primary; 4.6's care-gap work is HEDIS-relevant but not directly billable). 4.7 is the first chapter recipe where the architecture is operationally constrained by CMS CPT-code documentation requirements; the engagement-event schema must reflect this.

**Cross-recipe overlap: chapter-wide hardening patterns.** Tracking-ID privacy (S2 here, 4.4 Finding 2, 4.5 Finding S2, 4.6 Finding S2), validator specification (S3 here, 4.4 Finding 3, 4.5 Finding S3, 4.6 Finding S3 / A7), SDOH cohort PHI promotion (S4 here, 4.4 Finding 6, 4.5 Finding S4, 4.6 Finding S4), IAM ARN scoping (S5 here, 4.4 Finding 5, 4.5 Finding S5, 4.6 Finding S5), `0.0.0.0/0` egress (N1 here, 4.4 Finding 15, 4.5 Finding N1, 4.6 Finding N1), counter windowing (implicit in A1 here, 4.4 Code Review NOTE 9, 4.5 Finding A5, 4.6 Finding A5), counter reconciliation (A1 here, 4.4 Finding 9, 4.5 Finding A1, 4.6 Finding A1), cohort-feature dedup (A4 here, 4.4 Finding 13, 4.5 Finding A4, 4.6 Finding A4), `data_quality_flag` not gating (A2 here, 4.5 Finding A2, 4.6 Finding A2), model-promotion path (A5 here, 4.4 / 4.5 / 4.6). Ten chapter-wide patterns repeating. The chapter editor should consolidate these into a chapter-4 preface or shared "Chapter 4 production-hardening" section that all recipes reference; each per-recipe review is currently re-litigating the same gaps without resolution propagating across recipes.

Positive cross-recipe progress: the `patient-program-state` table's "highly inferential PHI" framing is the chapter's sharpest articulation. The high-sensitivity-program (behavioral-health, substance-use, palliative-care, HIV-related) tighter-controls treatment is more developed than 4.6's mental-health/substance-use mention. The multi-stage allocator's program-semantic staging is novel architectural content that's not in 4.4-4.6. The post-graduation observation pathway is novel architectural content. The Honest Take's articulation of the Obermeyer scenario, the operations-versus-modeling 75/25 ratio, and the closing rationing-ethics paragraph collectively make this the chapter's strongest Honest Take.

**No major conflicts among experts.** Security and Architecture both want stronger constraints on signal-quality, identity verification, and downstream gating, and these align. Networking is about endpoint topology and credentials. Voice is cosmetic. Priority alignment is clean.

**Priority alignment.** Three HIGH findings (A1 counter reconciliation, A2 `data_quality_flag` not gating, A3 human-review SLA) are the must-fix-before-publication items. A1 and A2 are chapter-wide patterns propagated forward; A3 is genuinely 4.7-specific. Eight MEDIUM findings (S1 identity boundary, S2 tracking-ID privacy, S3 validator specification, A4 cohort-feature dedup, A5 model promotion, A6 undefined filter functions, A7 engagement-scoring-function semantics, A8 equipment provisioning, A9 chained-enrollment sequencing, A10 CMS billing-readiness) are production-hardening that the editor or the next pipeline pass should address. The six LOW findings are cosmetic, edge-case, or chapter-pattern items.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

Zero CRITICAL findings. Three HIGH findings, at the > 3 = FAIL threshold (3 is not more than 3). PASS by a narrow margin.

The three HIGH findings are correctness gaps with localized fixes:

- **Finding A1 (counter reconciliation)** is acknowledged via existing TODO. The pseudocode does not yet implement the reconciliation. The 4.7-specific counter (`cm_outreach_recent_30d_count`) makes the fix recipe-local, but the pattern is the same chapter-wide pattern that has propagated unresolved through 4.4-4.6. Fix is local to `record_outreach_attempt`'s terminal-unreachable / declined / deferred branches plus a stale-pending sweep Lambda.
- **Finding A2 (`data_quality_flag` not gating)** is the recipe-internal inconsistency: the prose names the gate as necessary in "Where it struggles" with explicit reference to the disenrollment evaluator, the pseudocode never gates. Fix is local to Steps 2, 3, 4, 5, and 6: widen response-enrichment uncertainty on non-`complete` cases, route fragmented-data patients through verification-first allocation, surface data-quality caveats in briefings, dampen engagement-scoring confidence, and route `cross_provider_fragmentation` patients to verification rather than disenrollment.
- **Finding A3 (`human_review_pending` SLA)** is genuinely 4.7-specific. The disenrollment-decisions and cross-program-transitions queues both have human-review-pending state without SLA or escalation, allowing patients to remain stuck indefinitely or be silently disenrolled when stale review eventually happens. Fix is an SLA-and-escalation specification with per-action defaults that err toward retention rather than disenrollment, and per-cohort review-latency monitoring as part of equity instrumentation.

The teaching arc (the Linda vignette, the seven-component architecture, the multi-stage allocator with program-semantic staging, the per-program response stack with causal-inference-aware modeling, the longitudinal state machine, the engagement-decline taxonomy, the post-graduation observation pathway, the cross-program transition logic, the cohort-stratified outcome evaluation, the rationing-ethics closing) is solid and publishable. The HIGH findings should be addressed in the main text before the editor finalizes; the chapter-wide hardening MEDIUM and LOW findings are best resolved at chapter level rather than re-litigated per recipe.

The recipe's security and architectural posture continues the chapter-wide trajectory: prior reviewers' chapter-pattern gaps are increasingly resolved in main text (HealthLake VPC endpoint, EHR FHIR feed private connectivity, sharper inferential-PHI framing for high-sensitivity programs, enrollment-briefings table named as PHI), and the remaining gaps are explicit TODOs rather than silent omissions. The Honest Take is the strongest in Chapter 4, the Linda vignette is the strongest opening, and the closing "Build the second one" sentence is the editorial stance the chapter has been collecting.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| A1 | HIGH | Architecture | Step 4 / `record_outreach_attempt` pseudocode | Optimistic `cm_outreach_recent_30d_count` increment with no decrement on terminal-unreachable, declined, deferred outcomes; chapter-wide pattern propagated unresolved through 4.4-4.7 |
| A2 | HIGH | Architecture | Steps 1, 2, 3, 4, 5, 6 / "Where it struggles" | `data_quality_flag` is computed and propagated but never gates response enrichment, allocation, briefing, engagement scoring, disenrollment evaluation, or cross-program transitions; civil-rights implications when it concentrates in protected cohorts |
| A3 | HIGH | Architecture | Steps 5, 6 pseudocode | `human_review_pending` workflow on disenrollment-decisions and cross-program-transitions has no SLA, no escalation, no default action; patients stuck indefinitely or silently disenrolled when stale review eventually happens |
| S1 | MEDIUM | Security | Step 6 pseudocode | `process_disenrollment_decision` and `recommend_cross_program_transitions` have no patient-identity boundary checks; chapter pattern from 4.4-4.6 missing on these consumer paths |
| S2 | MEDIUM | Security | Sample briefing_id, transition_id; production-gaps TODO | Briefing-ID, decision-ID, and transition-ID embed patient_id and program_id in plain text; sharper here for high-sensitivity programs (behavioral health, substance use, palliative care, HIV-related) |
| S3 | MEDIUM | Security | Step 4 / Step 5 pseudocode / production-gaps | `validate_briefing` and `validate_rationale` named with inline TODOs but four-layer validator structure not specified; high-sensitivity program restrictions not specified; failure-handling differs (briefing falls back; rationale must defer) |
| A4 | MEDIUM | Architecture | Step 2 pseudocode | Cohort-feature lookup repeats per (patient, program) instead of per patient; chapter-wide pattern from 4.4-4.6 |
| A5 | MEDIUM | Architecture | Architecture diagram / production-gaps | 15 model artifacts (3 families × 5 programs) without coordinated promotion path, cohort-calibration hard gate, or rollback semantics specified |
| A6 | MEDIUM | Architecture | Step 3, Step 5 pseudocode | `operational_feasible`, `cross_recipe_conflicts`, `clinical_deterioration_detected` referenced but undefined; equity-instrumentation implications |
| A7 | MEDIUM | Architecture | Step 5 pseudocode | `engagement_scoring_function` referenced as registry attribute but pseudocode implies executable code; specify configuration-vs-versioned-function pattern |
| A8 | MEDIUM | Architecture | Step 4 sample briefing | Bluetooth scale and connected-device equipment mentioned but architecture lacks equipment provisioning, equipment-data ingestion, equipment-health signaling, equipment-return logistics |
| A9 | MEDIUM | Architecture | Step 6 / Variations and Extensions | Chained-enrollment sequencing (TCM→disease-specific, disease-specific→maintenance, disease-specific→complex-care) mentioned but not architected; chain_id and chain-level outcome aggregation missing |
| A10 | MEDIUM | Architecture | "What Counts as a Care Management Program" / production-gaps | CMS CCM/PCM/TCM CPT-code documentation requirements (time-tracking, modality, consent format) are operationally binding but engagement-event schema does not reflect them |
| S4 | LOW | Security | Production-gaps TODO | SDOH cohort PHI sensitivity in TODO; promote into main Privacy paragraph (chapter-wide pattern) |
| S5 | LOW | Security | Prerequisites IAM row | "Never *" stated but scoped ARN examples not shown (chapter-wide pattern) |
| N1 | LOW | Networking | Prerequisites VPC row | `0.0.0.0/0` egress disallow not stated explicitly (chapter-wide pattern) |
| N2 | LOW | Networking | Architecture description / production-gaps | Care-management-vendor integration credential posture (REST, webhook, SFTP, mTLS) not specified |
| N3 | LOW | Networking | HealthLake paragraph | FHIR API encryption / mTLS posture not specified for HealthLake or direct FHIR-to-S3 patterns (same as 4.6 N3) |
| V1 | N/A | Voice | Honest Take closing paragraph | Not a finding; note for editor: "Build the second one" closing is the chapter's strongest call-to-action; preserve verbatim |
| V2 | LOW | Voice | Expected Results sample briefing | Sample briefing references "Mr. Garcia" but opening vignette is Linda; rename or introduce Mr. Garcia earlier |
| V3 | LOW | Voice | Step 3 / Variations | "High-leverage" phrasing twice; colloquial sense; defensible; optional editor tightening |

---

## Recommended Actions (Priority Order)

1. **Implement the contact-counter reconciliation path** (Finding A1): add explicit decrement clauses to `record_outreach_attempt` for terminal-unreachable, declined, and deferred outcomes; add a stale-pending sweep Lambda for outreach-state rows older than 7 days with no engagement-event activity; add a paragraph to the architecture pattern naming the per-patient counter invariant. Coordinate with the parallel 4.4, 4.5, 4.6 fixes; the chapter editor should land all four together with a chapter-4 preface that names the cross-recipe contact-budget contract.

2. **Add `data_quality_flag` gating throughout the pipeline** (Finding A2): widen response-enrichment uncertainty on non-`complete` cases (Step 2); route `cross_provider_fragmentation` patients through verification-first allocation (Step 3); surface data-quality caveats in enrollment briefings (Step 4); dampen engagement-scoring confidence (Step 5); replace the disenrollment-for-no-engagement rule for fragmented-data patients with a `verify_engagement_first` action (Step 5); flag cross-program transitions with data-quality caveats (Step 6). Add a paragraph to the architecture pattern naming the gate explicitly with the civil-rights framing. The recipe's own prose says the gate is needed; the pseudocode should show it.

3. **Architect the `human_review_pending` SLA-and-escalation pathway** (Finding A3): per-action review SLAs (7 days for disenrollment-for-no-engagement, 14 days for did-not-complete, 72 hours for transition-to-higher-acuity, 14 days for graduation transition, 7 days for relapse transition); per-action defaults that err toward retention; per-cohort review-latency monitoring as part of equity instrumentation; pseudocode for the daily `sweep_pending_decisions` function. Without this, the chapter-wide equity dashboard misses a key disparate-impact dimension (review latency).

4. **Add patient-identity boundary checks** (Finding S1): in `process_disenrollment_decision`, validate that `human_decision.decision_id` matches the stored decision and that the reviewer attribution is non-null; in `recommend_cross_program_transitions`, validate that the `patient_id` parameter matches the prior_program_id's recorded patient. Reference 4.4-4.6 chapter pattern.

5. **Replace string-concatenation tracking IDs with opaque identifiers** (Finding S2): briefing_id, decision_id (already UUID), transition_id should not embed patient_id or program_id in plain text. For high-sensitivity programs, the opaque-identifier requirement is non-negotiable; document this explicitly in the privacy paragraph. Update Expected Results samples accordingly.

6. **Specify the four-layer validator template** (Finding S3): inline the template once; specialize per validator (briefing falls back to templated, rationale must defer); add high-sensitivity-program overlay restrictions; specify failure-handling per validator.

7. **Specify the model-promotion path with cohort-calibration hard gate** (Finding A5): SageMaker Model Registry pending_review state; canary Batch Transform against frozen evaluation cohort; per-family per-program promotion granularity with bulk-promotion option; cohort-calibration-error threshold as hard gate; rollback as alias-pointer change. Reference Recipe 7.x.

8. **Specify `operational_feasible`, `cross_recipe_conflicts`, `clinical_deterioration_detected`** (Finding A6): inline the specifications or add explicit TODO references to a forthcoming chapter-level filter specification. Equity instrumentation should track operational-feasibility-driven exclusions per cohort.

9. **Specify the `engagement_scoring_function` registry semantics** (Finding A7): pick configuration-driven (declarative metrics + named functions) or versioned-function-reference (registry references a versioned module); specify which.

10. **Architect the chained-enrollment sequencing** (Finding A9): chain_id, chain_position, chain_total, predecessor_recommendation_id in the recommendation log; chain-level outcome aggregation; reference Recipe 14.x for full multi-stage stochastic-program treatment.

11. **Add equipment-provisioning architecture** (Finding A8): equipment-fulfillment workflow (Step Functions integration with vendor order API); equipment-data ingestion (vendor cellular feed or patient-app sync); equipment-health signal in engagement scoring; equipment-return workflow on disenrollment or graduation.

12. **Add CMS billing-readiness specification** (Finding A10): per-event timestamp granularity for CCM time-tracking; modality differentiation for TCM qualifying-visit determination; per-program billing-frame configuration in the registry; engagement-event schema includes CMS-billing-relevant fields as first-class attributes.

13. **Deduplicate cohort-feature lookups by patient** (Finding A4): hoist the cache out of the per-(patient, program) loop. Chapter-wide pattern.

14. **Promote SDOH cohort PHI paragraph from TODO into main Privacy paragraph** (Finding S4); chapter-wide pattern.

15. **Add scoped IAM ARN examples for highest-stakes actions** (Finding S5); chapter-wide pattern.

16. **Disallow `0.0.0.0/0` egress on Lambda subnets explicitly** (Finding N1); chapter-wide pattern.

17. **Specify care-management-vendor integration credential posture** (Finding N2): REST/webhook/SFTP/mTLS variations; Secrets Manager + KMS + rotation; vendor-specific dedicated network paths.

18. **Specify FHIR API encryption / mTLS posture for HealthLake and direct FHIR-to-S3 patterns** (Finding N3); same as 4.6.

19. **Resolve "Mr. Garcia" vs. Linda continuity** (Finding V2): rename samples to Linda or introduce Mr. Garcia as a second example earlier in the recipe.

20. **Optional voice polish** (Findings V3); not blocking.

---

## Notes for Editor

- The recipe runs long (~18,755 words including the architecture diagram, code blocks, and Expected Results JSON). Length is earned: the Linda vignette, the seven-component architecture, the per-program response stack with causal-inference framing, the multi-stage allocator with program semantics, the longitudinal state machine, the engagement-decline taxonomy, the post-graduation observation pathway, the cross-program transition logic, the disenrollment-decision-support flow, and the closing rationing-ethics paragraph are all pedagogically essential. Do not trim any of them.
- The recipe carries forward 4.4 / 4.5 / 4.6 chapter-wide hardening progress and adds care-management-specific sharpenings: the `patient-program-state` "highly inferential PHI" framing is the sharpest in the chapter; the high-sensitivity-program tighter-controls discussion is more developed than 4.6's; the multi-stage allocator with program-semantic staging is the chapter's most distinctive piece of architecture; the multi-program response stack (uplift + likelihood + engagement) with per-program scoring is novel; the post-graduation observation pathway is novel; the disenrollment-decision-support flow with LLM-generated rationale is the chapter's most consequential decision-support surface. The teaching density is high.
- Several `<!-- TODO -->` markers are present and appropriate: SageMaker Batch Transform HIPAA eligibility, Bedrock per-model HIPAA eligibility and service terms, IAM ARN examples (chapter-wide), SES/Pinpoint HIPAA scope, Connect HIPAA scope, AWS HealthLake pricing and HIPAA eligibility, Cost Estimate validation, validate_briefing four-layer specification, validate_rationale specification, model-promotion path, contact-cap reconciliation paths, tracking-ID privacy, cross-recipe orchestration with 4.7-specific exception, DLQ coverage, SDOH cohort PHI promotion, NCQA / CMS / aws-samples URL verification. These are realistic verification tasks and not blockers.
- The Cost Estimate range ($5,000-$12,000/month for a 250K-member plan, before staff/telephony/vendor contracts) is reasonable for the architecture described; the per-line items are realistic.
- The Related Recipes section forward-references future recipes (4.8, 7.x, 8.x, 12.x, 13.x, 14.x, 15.x). Standard practice for the book.
- The Footer link to Recipe 4.8 (Treatment Response Prediction) references a future recipe that doesn't exist yet. Standard placeholder.
- All external links are appropriately hedged with TODOs where verification is needed: NCQA HEDIS landing page, CMS CCM / TCM landing pages (URLs change frequently), AWS docs, AWS HIPAA Eligible Services list, EconML, DoWhy, Obermeyer 2019 (canonical and verified DOI), Synthea. The aws-samples repo references are appropriately hedged with TODOs.
- Cross-recipe coherence with 4.1-4.6 is strong: the patient-profile store (now extended with `program_eligibility`, `program_state`, `program_history`, `engagement_history_per_program`, `cross_program_coordination_state`), engagement-event bus with new event types, channel optimizer integration, contact-frequency cap with the documented 4.7 exception, cohort dashboard infrastructure, Bedrock / DynamoDB / Kinesis / SageMaker primitives, and the structural progression from 4.4's wellness through 4.5's adherence through 4.6's care-gap to 4.7's care-management are all visible. The "Where This Sits in the Chapter" framing is accurate and helps the chapter narrative.
- The Python code review (`reviews/chapter04.07-code-review.md`) returned FAIL with two ERRORs (invalid `ADD state_history :history_event` UpdateExpression syntax; missing `:zero` placeholder in `record_outreach_attempt` decrement path), one WARNING, six NOTEs. ERROR 1 (state_history pattern) is a chapter-wide DynamoDB usage bug that the code-review notes affects 4.6 as well; the fix is `SET state_history = list_append(if_not_exists(state_history, :empty), :history_event)`. ERROR 2 (`:zero` placeholder + `ExpressionAttributeNames=None`) intersects with this review's HIGH Finding A1 (counter reconciliation): both fixes coordinate around the counter-decrement path. The Python code review and this expert review together name a coordinated set of fixes spanning recipe text, pseudocode, and Python implementation.
- Voice and 70/30 vendor balance: clean. Em dash count: 0 (verified). En dash count: 0 (verified). Recipe is publishable on voice grounds without any additional fixes.
- The closing "Build the second one" sentence (Finding V1) is the strongest call-to-action in the recipe and arguably in the chapter so far. Preserve verbatim.

---

*Review complete. Findings prioritized; PASS verdict with three HIGH findings at (not over) the > 3 = FAIL threshold. The three HIGH findings are correctness gaps with localized fixes that should be closed in the main recipe text before final editing; chapter-wide hardening progress (HealthLake VPC endpoint, EHR FHIR private connectivity, sharper inferential-PHI framing for high-sensitivity programs, enrollment-briefings PHI handling) continues to mature from prior recipes' TODOs into this recipe's main text. The Linda vignette and the closing rationing-ethics paragraph make this the chapter's strongest recipe on voice grounds; the multi-stage allocator with program-semantic staging makes it the chapter's strongest on architectural-distinctiveness grounds.*
