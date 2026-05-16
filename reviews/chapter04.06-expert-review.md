# Expert Review: Recipe 4.6 - Care Gap Prioritization

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-16
**Recipe file:** `chapter04.06-care-gap-prioritization.md`

---

## Overall Assessment

This recipe takes the uplift-and-allocation pattern from 4.4 and the barrier-classification pattern from 4.5 and graduates them to the harder problem class: care gap prioritization where the catalog of gaps is enormous and heterogeneous (HEDIS, Stars, USPSTF, ADA, KDIGO, ACO, contract-specific, plus patient-specific clinical gaps), the urgency function decomposes into clinical urgency vs. operational/window urgency that can diverge, the closure pathways are structurally different (in-visit vs. patient-driven vs. specialist-referral), and visit-time is the binding constraint rather than population-level outreach capacity. The opening David vignette is the strongest opening in Chapter 4: eleven open gaps, twenty-five visit minutes, two of them addressable, and the dashboard pushing toward the diabetic eye exam while the rising creatinine trajectory pushes toward the kidney conversation. A reader who has worked in HEDIS operations will recognize the scenario; a reader who hasn't will understand why "close the most overdue HEDIS measure first" is not the same recommender as "address the highest-clinical-urgency gap."

The recipe carries forward the chapter-wide hardening progress visible in 4.4 and 4.5. The `patient-gaps` table is explicitly named as PHI ("the per-gap state plus reasoning is highly inferential PHI"), customer-managed KMS is specified for every PHI store, the VPC endpoint list is comprehensive (including HealthLake), the Bedrock data-retention posture is flagged with TODOs, and there are explicit production-gap TODOs for tracking-ID privacy, DLQ coverage, validator specification, SDOH-cohort PHI minimization, IAM ARN scoping, cross-recipe orchestration, model-promotion path, and patient-facing message governance. Those TODOs match the chapter-wide pattern; the recipe is honest about which gaps it isn't closing in this pass.

The Honest Take is unusually strong even by chapter-4 standards. Five observations stand out:

1. The David scenario from the opening is referenced through to the Honest Take, naming the operational-vs-clinical divergence explicitly: *"The clinically obvious answer (the second one, where the kidney decline gets named and acted on) and the operationally rewarded answer (the first one, where the visible HEDIS measure closes within the measurement window) are not the same answer."* This is the chapter's clearest articulation of dashboard-driven prioritization failure.
2. The "build the closure tracker before the urgency model" framing is the right operational sequencing advice: *"A program that calls patients about colonoscopies they had last week earns a level of operator-distrust that's hard to recover from, and it's all closure-tracking failure, not modeling failure."*
3. The LLM scope discipline is the chapter's tightest: *"The recommender picks. The LLM packages."* The candidate-gap surfacer is correctly framed as a discovery tool gated by a clinical-informatics review queue, not a direct decision input.
4. The override-rate distribution analysis (8-15 percent healthy, breakdown by reason matters more than aggregate, `previously_addressed_outside_record` is closure-tracker failure, `out_of_scope_for_visit` is visit-fit-ranker failure) is the kind of operational signal-routing that distinguishes a senior recommender architect from a junior one.
5. The closing "care gaps are not the same as care needs" paragraph is the chapter's most direct ethics framing: *"The dashboard is the dashboard. The patient is the patient. They are not the same thing."*

That said, three correctness gaps need attention before publication, and the medium and low items round out the review:

1. **The optimistic contact-counter increment in Step 4 has no reconciliation path implemented in the pseudocode.** The recipe carries an explicit TechWriter TODO acknowledging the gap and pointing back to 4.4 Step 6 and 4.5 Step 7. This is the same High finding from the 4.4 and 4.5 reviews, propagated forward unresolved. The `outreach_recent_total_30d_count` counter is a *cross-recipe global counter* shared with 4.4, 4.5, and 4.7, which makes the reconciliation gap structurally worse here than in either prior recipe: a phantom contact recorded in 4.6 silently suppresses outreach for the same patient in 4.4, 4.5, and 4.7. The members most affected (members with flaky channels in cohorts the equity floors are trying to protect) accumulate phantom global cap consumption every time a reminder bounces and get systematically excluded across the entire chapter's outreach surface.

2. **The `data_quality_flag` is computed and propagated but never gates downstream decisions.** Step 1 computes flags with values `complete`, `sparse_history`, `multi_source_disagreement`, `recent_plan_change`, `cross_provider_fragmentation`, persists them to the `patient-gaps` table, and the "Where it struggles" section says explicitly: *"The `data_quality_flag` exposes this, but downstream consumers (chase team, dashboards) need to gate on it. A 'gap open' label on a patient with `cross_provider_fragmentation` data quality is much less reliable than the same label on a patient with `complete` data quality."* The pseudocode never gates on it. The urgency model (Step 2) doesn't downweight low-quality cases; the visit-context ranker (Step 3) doesn't suppress low-quality gaps from the agenda; the async orchestrator (Step 4) doesn't route to a verification-first pathway; the closure tracker (Step 5) doesn't tighten the canonical-source rule. The flag is informational metadata that no downstream component consumes. This is the same Finding A2 from 4.5 propagated forward unresolved, and in 4.6 it's *worse* because the chase-team-calls-patient-about-colonoscopy-they-had-last-week failure mode the recipe explicitly worries about is exactly what `cross_provider_fragmentation` flags. A reader copying the pseudocode literally will produce confidently-open-gap labels for the very cohorts the recipe says are most affected by data fragmentation.

3. **The HEDIS Comprehensive Diabetes Care (CDC) measure name used in The Technology section is retired.** The Technology subsection lists *"HEDIS Comprehensive Diabetes Care eye exam"* as an example of a quality-measure-defined gap. NCQA retired the Comprehensive Diabetes Care (CDC) parent measure starting in HEDIS Measurement Year 2022 and finalized the split into separate measures by MY 2024: EED (Eye Exam for Patients with Diabetes), KED (Kidney Health Evaluation for Patients With Diabetes), GSD (Glycemic Status Assessment for Patients With Diabetes), and BPD (Blood Pressure Control for Patients With Diabetes). A healthcare reader checking the NCQA HEDIS specifications for "CDC eye exam" will find a deprecated reference and lose trust in the recipe's other HEDIS claims. The recipe's Expected Results sample uses `"measure_id": "hedis-cdc-eye-exam"` which compounds the issue. The Code Review for the Python companion uses the same outdated naming throughout the synthetic registry, so the fix needs to land in both files in tandem.

A handful of medium and low findings round out the review. The pneumococcal-vaccine-newly-indicated-at-64 framing in the David vignette is clinically loose (PPSV23 has been indicated for adults 19-64 with diabetes for years; a 9-year diabetic should already have had it). The colon-cancer family-history urgency framing is overstated (father with CRC at 71 is generally not "elevated risk" by NCCN/USPSTF criteria, which trigger earlier screening for first-degree relatives diagnosed before 60). Four named-but-unspecified validators (`validate_candidate_gaps`, `validate_briefing`, `validate_clinical_message`, `validate_chase_brief`) inherit the chapter-wide pattern. The cohort-features lookup repeats per (patient, gap) pair (same as 4.4 / 4.5). The `outreach_recent_total_30d_count` counter has no decay or windowing mechanism (same as 4.4 / 4.5). The `process_clinician_override` flow has no `event.patient_id != rec.patient_id` identity check (regression from the 4.4 / 4.5 engagement-event check pattern). The chapter-wide IAM ARN scoping, `0.0.0.0/0` egress disallow, and SDOH cohort PHI promotion-from-TODO patterns repeat. State immunization-registry credential posture is not specified.

Voice is clean. Em dash count: 0 (verified). En dash count: 0 (verified). 70/30 vendor balance is maintained: The Problem, The Technology, and General Architecture Pattern stay vendor-neutral; AWS service names enter only in The AWS Implementation. Marketing-language scan turned up one borderline hit ("high-leverage" in Variations and Extensions, used colloquially as "leverage point" rather than as the corporate-marketing verb). The David vignette and the Honest Take are exactly the CC voice the chapter has been collecting.

Priority breakdown: 0 critical, 3 high, 9 medium, 6 low.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA called out explicitly with HIPAA-eligibility TODOs for SageMaker Batch Transform, Bedrock per-model coverage, SES, Pinpoint, Connect, and HealthLake. The recipe doesn't pretend any of these are static.
- Customer-managed KMS keys for every PHI store: DynamoDB tables (especially the `patient-gaps` table with the explicit "the per-gap state plus reasoning is highly inferential PHI" framing), S3 (SSE-KMS bucket-level keys), Kinesis and Firehose (server-side encryption), SageMaker training/Batch Transform/Feature Store (VPC-only with KMS keys for model artifacts and offline storage), Lambda log groups KMS-encrypted, and explicit acknowledgment that the `clinician-briefings` table contains PHI ("the briefing text contains diagnostic and risk-related content").
- The `patient-gaps` table is named as inferential PHI in language stronger than 4.4 or 4.5: *"A row indicating 'patient has open mental-health-follow-up gap with high urgency' is much more sensitive than a row indicating 'patient has open flu-shot gap.'"* The recommendation that high-sensitivity measures (mental health, substance use, HIV-related, reproductive health) get tighter controls (narrower IAM read scopes, optional separate-table partitioning, additional CloudTrail data event capture, documented minimum-necessary access policy) is correct and earns its place in the production-gaps section.
- CloudTrail data events on `patient-gaps`, `measure-registry`, `clinician-briefings`, `clinician-overrides`, `recommendation-log`, `patient-profile`, and the relevant S3 buckets. Comprehensive.
- LLM prompt construction explicitly de-identifies before the Bedrock call: *"Identifiers are stripped before LLM calls; PHI is re-attached after."* Step 3's `de_identified_context` block (with `redact_identifiers(in_visit_agenda)` and `redact_identifiers(async_queue[:5])`) is the explicit place this happens. Continues the chapter pattern from 4.4 and 4.5.
- Bedrock paragraph: *"Confirm in service terms that prompts and completions are not used to train the underlying foundation models."* Continues the chapter pattern.
- Patient-facing message governance flagged as a regulated communication category with state-by-state pharmacy board variation, CMS guidance for Medicare Advantage member communications, and state-specific consumer-protection rules for cancer-screening and depression-screening prompts. Explicit TODO to engage compliance counsel on per-measure messaging before launch.
- Production-gaps section names tracking-ID privacy, DLQ coverage, validator specification, SDOH-cohort PHI minimization, IAM ARN scoping, model-promotion path, cross-recipe orchestration, and patient-facing message governance as TODOs. The chapter-wide hardening pattern is preserved.

### Finding S1: `process_clinician_override` Has No Patient-Identity Boundary Check

- **Severity:** MEDIUM
- **Expert:** Security (PHI integrity boundary)
- **Location:** Step 6 pseudocode, the `process_clinician_override` function: `rec = lookup_recommendation_by_briefing_id(event.briefing_id)` followed by `DynamoDB.PutItem("clinician-overrides", { ..., patient_id: event.patient_id, ... })` with no comparison between `event.patient_id` and `rec.patient_id`.
- **Problem:** The chapter pattern from 4.2, 4.3, 4.4, and 4.5 enforces an identity-boundary check on engagement-event consumers: when an event references a recommendation by `tracking_id` or `briefing_id`, the consumer reads the recommendation and validates that `event.patient_id == rec.patient_id` before applying any state change. The 4.4 finding's framing (an out-of-band event for tracking_id A should not update a recommendation for tracking_id B) applies directly here: an override event arriving with mismatched patient_id and briefing_id should be rejected, not written to the override audit trail under the event's claimed patient_id.

  The override path is the most security-sensitive consumer in this recipe because:
  1. **It writes to `clinician-overrides`**, which is part of the audit trail that gets read back during incident response and quality investigations. A malformed event with a mismatched patient_id contaminates the audit trail in a way that's hard to detect after the fact.
  2. **It triggers `apply_suppression`** which marks the gap suppressed for 30-180 days based on the reason. A patient-id-mismatched event would suppress the wrong patient's gap, denying that patient outreach they should have received.
  3. **It feeds the urgency-model retraining pipeline as a structured label** via `update_training_label(event)`. Mismatched events poison the training dataset.

  The closure-event handler in Step 5 has a related but different shape (the closure event isn't joined to a specific recommendation; it's matched to the gap state directly via `event.patient_id`), so the canonical 4.4/4.5 identity check doesn't apply identically there. But the override path is structurally identical to the 4.4/4.5 engagement-event consumer and should carry the same check.

- **Fix:** Add the identity check immediately after the recommendation lookup:

  ```
  rec = lookup_recommendation_by_briefing_id(event.briefing_id)
  IF rec is null:
      LOG("override event with no matched briefing: " + str(event))
      RETURN
  IF event.patient_id != rec.patient_id:
      LOG("override event patient_id mismatch with briefing; dropping",
          event_patient = event.patient_id,
          briefing_patient = rec.patient_id,
          briefing_id = event.briefing_id)
      emit_metric("override_identity_mismatch", value = 1)
      RETURN
  IF event.measure_id != rec.measure_id:
      LOG("override event measure_id mismatch with briefing; dropping",
          event_measure = event.measure_id,
          briefing_measure = rec.measure_id,
          briefing_id = event.briefing_id)
      emit_metric("override_identity_mismatch", value = 1)
      RETURN
  ```

  Add the same check to the `process_closure_event` flow as a defense-in-depth measure, even though the closure event isn't joined to a specific recommendation: validate that the event's `patient_id` exists in the patient-profile store before any state machine mutation. A closure event for a non-existent patient should be logged and dropped rather than creating a phantom `patient-gaps` row.

### Finding S2: Tracking ID Format Embeds Patient ID, Measure ID, and Pathway in Plain Text (Chapter-Wide Pattern, Already TODO'd)

- **Severity:** MEDIUM
- **Expert:** Security (PHI minimization)
- **Location:** Sample `tracking_id` values in Expected Results: `"gap-2026-05-04-pat-000915-pneumo-pharmacy-001"`; sample `briefing_id`: `"brief-2026-05-05-prov-014-pat-000482"`; `build_tracking_id(...)` and `build_briefing_id(...)` calls throughout Steps 3 and 4; existing TechWriter TODO in production-gaps.
- **Problem:** Same finding as 4.4 Finding 2 and 4.5 Finding S2. The recipe acknowledges the gap with a TODO that mirrors the 4.4 and 4.5 fix language. The TODO is appropriate and the fix is clear; this finding is the cross-recipe restatement so the editor sees the same pattern across the chapter.

  Care-gap-specific sharpening: the tracking_id here embeds `patient_id`, `measure_id`, *and* `chosen_pathway`. The briefing_id embeds `provider_id` (via `build_briefing_id(encounter, run_date)` → `"brief-2026-05-05-prov-014-pat-000482"`) plus `patient_id`. A leaked tracking_id reveals not just patient identity but also the gap category (pneumococcal vaccine, colorectal screening, mental-health follow-up, substance-use follow-up) and the closure pathway being attempted. For high-sensitivity measures the recipe explicitly flags (mental health, substance use, HIV-related, reproductive health), the tracking_id leakage is *more* sensitive than for adherence (4.5) because the gap category itself is the sensitive disclosure: a tracking_id like `"gap-2026-05-04-pat-000915-fuh-chase-001"` reveals that the patient was hospitalized for mental illness, which is more inferential than the equivalent adherence tracking_id.

- **Fix:** The TODO already names the fix correctly: replace the string-concatenation with an opaque UUID or HMAC-SHA256 over the composite. Update the Expected Results sample tracking_ids and briefing_id accordingly. The fix is mechanical once the TODO is actioned. Consider adding a paragraph specifying that high-sensitivity measure types (mental health, substance use, HIV, reproductive health) must use opaque identifiers without exception, and that the cohort-features serialization (`cohort_features.engagement_history_quartile`, etc.) carried in engagement events must be reviewed for the same minimum-necessary principle.

### Finding S3: Four Validators (`validate_candidate_gaps`, `validate_briefing`, `validate_clinical_message`, `validate_chase_brief`) Named but Not Specified

- **Severity:** MEDIUM
- **Expert:** Security (regulatory, hallucination guardrails)
- **Location:** Step 1 pseudocode: `validate_candidate_gaps(candidates, patient_id, observed_data = chart_context)`; Step 3 pseudocode: `validate_briefing(briefing_parsed, observed_agenda = in_visit_agenda)`; Step 4 pseudocode (in `CASE "patient_driven_pharmacy"`): `validate_clinical_message(tailored, row.measure_id)`; Step 4 pseudocode (in `CASE "chase_team_call"`): `validate_chase_brief(brief)`. Existing TechWriter TODOs partially specify the validators inline in Steps 1 and 3.
- **Problem:** Four LLM-output validators are named in the pseudocode. Two of them (`validate_candidate_gaps` in Step 1 and `validate_briefing` in Step 3) have inline TechWriter TODOs that begin to specify the four-layer structure (schema, length/structure, observed-data citation, prohibited content). Two of them (`validate_clinical_message` in Step 4 and `validate_chase_brief` in Step 4) are named without any specification at all. The chapter-wide pattern from 4.4 and 4.5 is to specify all validators with the same four-layer shape, with failure-handling behavior explicit (fall-back-to-default vs. defer-with-reason vs. drop-from-pipeline).

  Care-gap-specific reasons this matters more here than in 4.4 or 4.5:

  1. **Four distinct validator surfaces** in one recipe is the largest validator footprint in Chapter 4. Each surface has a different output shape (a list of candidate-gap proposals; a one-paragraph clinician briefing; a patient-facing message; a chase-agent brief), a different prohibited-content list (the briefing must not invent gaps not on the deterministic agenda; the patient message must not make unapproved clinical claims about screening efficacy; the chase brief must not contain PHI in the opening greeting), and a different failure-handling mode. Specifying all four with one shared four-layer template is essential for the team building this pipeline.

  2. **Briefing validator is the highest-stakes validator in the chapter so far.** The clinician reads the briefing in three seconds before walking into the room. A briefing that hallucinates a gap not on the deterministic agenda misleads clinical decision-making at the moment of patient care. The TechWriter TODO in Step 3 is correct that the validator must enforce *"every referenced agenda item must appear in observed_agenda (the LLM cannot hallucinate gaps that aren't on the deterministic agenda)."* That check is the meaningful one, and the implementation is non-trivial: substring matching produces false positives; structured extraction produces false negatives when the LLM paraphrases. The validator's failure-handling (the existing TODO says "fall back to a templated fallback that simply lists the in_visit_agenda items without LLM narration") is the right disposition; specify it.

  3. **Patient-facing message governance for care gap content has per-state regulatory variation.** The recipe's production-gaps section names this. The validator must be configurable per state for the patient's resident state and per measure (cancer screening prompts have different consent rules than vaccination prompts in some states). The TODO acknowledges the gap; the implementation needs to land.

  4. **Chase brief validator has a "no PHI in greeting" check that's specific to telephonic outreach.** When a chase-team agent reads a brief and dials a patient, the agent's opening greeting can leak PHI if the brief contains identifying information formatted in a way that prompts the agent to read it aloud. The validator should enforce that PHI fields appear in the brief only when the agent has confirmed the patient's identity by callback verification. This is a workflow-aware constraint that the chase-brief validator is the right place to enforce.

- **Fix:** Specify the four-layer validator shape once in a shared paragraph, then specialize per validator:

  ```
  // Shared four-layer template:
  // Layer 1: schema and length
  // Layer 2: required disclosures and identifications (per-message-type)
  // Layer 3: prohibited content (PHI not in source, prescriber names other than the
  //          visit provider's, suggestions that override the deterministic ranker)
  // Layer 4: required references (briefing items must trace to observed_agenda;
  //          message claims must trace to approved-claims-per-measure list)

  FUNCTION validate_briefing(briefing_parsed, observed_agenda):
      // Layer 1
      IF briefing_parsed.headline length > MAX_HEADLINE_LENGTH:
          RETURN ValidationResult(passed=false, reason="headline_length")
      IF briefing_parsed.suggested_focus length > MAX_FOCUS_LENGTH:
          RETURN ValidationResult(passed=false, reason="focus_length")
      // Layer 2
      IF "subject to clinical judgment" NOT IN briefing_parsed.confidence_notes:
          RETURN ValidationResult(passed=false, reason="missing_advisory_disclosure")
      // Layer 3
      IF contains_pii_outside_visit(briefing_parsed):
          RETURN ValidationResult(passed=false, reason="pii_outside_visit")
      // Layer 4
      FOR each agenda_item in briefing_parsed.in_visit_agenda:
          IF agenda_item.measure_id NOT IN observed_agenda.measure_ids:
              RETURN ValidationResult(passed=false, reason="hallucinated_agenda_item",
                                       detail=agenda_item.measure_id)
      RETURN ValidationResult(passed=true)
  ```

  Specify failure-handling per validator:
  - **`validate_candidate_gaps`**: failure drops the candidate from the review queue (the candidate is not surfaced to clinical informatics); failure logged for prompt-engineering review.
  - **`validate_briefing`**: failure replaces the briefing with a templated fallback that lists `in_visit_agenda` items without LLM narration; failure logged.
  - **`validate_clinical_message`**: failure defers the outreach with reason `validator_failed:<reason>` and flags for human review; failure does *not* fall back to a default template silently because the failure mode is "the LLM said something the validator wouldn't approve" and a silent fallback hides the signal that the prompt or model needs adjustment.
  - **`validate_chase_brief`**: failure routes the gap to a "manual brief" queue where a chase-team supervisor writes the brief by hand; failure logged with the LLM output for diagnostic review.

  Reference the chapter-wide validator pattern from 4.4 Finding 3 and 4.5 Finding S3.

### Finding S4: SDOH-Cohort PHI Sensitivity TODO Should Be Promoted to Main Privacy Paragraph (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** TechWriter TODO at the bottom of Why This Isn't Production-Ready, mirroring 4.4 Finding 6 and 4.5 Finding S4.
- **Problem:** Same finding as 4.4 Finding 6 and 4.5 Finding S4. The substance is correct: SDOH cohort labels carried in the engagement-event payload, the recommendation log, and the per-(patient, gap) state are reidentifying for small cohorts in specific geographies. The minimum-necessary principle says only carry the cohort axes the equity dashboard actually consumes; access scope should be narrower than for general engagement data. In 4.6 the cohort_features attribute is referenced explicitly in `priority_components` and in the Step 5 metric dimensions (`engagement_history_quartile`, `language`, `sdoh_cohort`), making the gap especially visible.
- **Fix:** Promote the TODO content into the main *Privacy in the gap state and recommendation log* paragraph. Add a sentence: *"A new cohort axis added 'for future use' is a privacy expansion, not a feature. Review additions like new code."*

### Finding S5: IAM "Never `*`" Stated Without Scoped ARN Examples (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites IAM Permissions row.
- **Problem:** Same finding as 4.1 / 4.2 / 4.3 / 4.4 / 4.5. The TODO acknowledges the chapter-wide pattern.
- **Fix:** Either inline one or two scoped resource ARN examples for the highest-stakes actions (`dynamodb:UpdateItem` on `patient-gaps`, `bedrock:InvokeModel` on the briefing model ARN, `connect:*` on the chase-team contact flow), or consolidate into a chapter-4 preface that all recipes reference.


---

## Architecture Expert Review

### What's Done Well

- The six-component architecture (measure registry, gap evaluation, gap enrichment, visit-context ranking, asynchronous outreach orchestration, closure tracking) is the right shape for the problem class. The framing of *"the measure registry is governance, not engineering"* is correct: the registry is a structured, versioned catalog owned by clinical informatics; the engineering pipeline consumes it generically. New measures and annual revisions land as registry entries rather than code changes. This is the correct architectural separation and resolves a class of maintenance failures that plague hand-coded HEDIS engines.
- Three reasonable definitions of "what counts as a gap" (quality-measure-defined, guideline-recommended, patient-specific clinical) and the reconciliation pattern (deduplicate, merge LLM-surfaced candidates against measure-defined gaps) is the correct framing. The candidate-gap surfacer pattern (LLM proposes; clinical informatics curates; durable patterns get encoded into the deterministic registry; the LLM is a discovery tool, not a source of truth) is the chapter's tightest example of LLM scope discipline.
- The state machine for closure tracking (open → provisionally_closed → confirmed_closed → reopened → excluded) with canonical-source rules per measure is the right abstraction. The recipe correctly identifies that the canonical source varies by measure (HEDIS uses claims-and-supplemental-data with strict source-of-truth rules; the practice's quality dashboard may treat the EHR as canonical; the public-health immunization registry is canonical in some states for vaccines and not in others). A patient who got a flu shot at the pharmacy should be marked `provisionally_closed` on Monday and `confirmed_closed` when the canonical source confirms; the chase team should respect the provisional state.
- Visit-context ranking is the most operationally distinctive piece in the chapter so far and is well-architected: pulls tomorrow's schedule, looks up enriched gap lists, applies visit-fit filters (closure pathway compatible with visit type and time), produces a per-encounter ranked agenda with a hard cap on size and cumulative time cost. The split into "in-visit agenda (3-5 items)" plus "asynchronous closure queue (the rest)" is the right output shape for a clinician about to walk into a 9:15 visit.
- The clinician-briefing pattern (structured input goes in, structured paragraph comes out, the briefing references only the deterministic ranker's choices) is correctly framed: *"The LLM is composing the briefing, not picking the gaps. The picks are from the deterministic ranker. The LLM's only job is making the picks readable in three seconds."* This is the cleanest example of the chapter's "the recommender picks; the LLM packages" framing.
- Multi-source closure reconciliation: claims (slow, canonical for HEDIS), EHR (fast, canonical for the practice), lab feeds (fast, canonical for lab-based gaps), pharmacy (fast, canonical for some immunizations), immunization registries (medium speed, canonical in some states), and patient self-report (fast, low confidence, valuable for suppression of unnecessary outreach). The state machine reconciling these and gating downstream consumers (chase teams, dashboards, billing) on the appropriate confidence level is correct. The HEDIS-measure-won't-credit-a-self-report / chase-team-should-still-suppress-outreach-when-one-arrives pattern is a senior-level operational insight.
- The clinician-override taxonomy (`appropriate_decline`, `previously_addressed`, `clinical_judgment`, `patient_refusal`, `out_of_scope_for_visit`, `exclusion_documented`, `other`) with reason-specific suppression policies is the right design. The Honest Take's analysis of override-rate distribution (under 5 percent suspicious, 8-15 percent healthy, over 25 percent misalignment) and the breakdown-by-reason analysis (high `previously_addressed_outside_record` is closure-tracker failure; high `out_of_scope_for_visit` is visit-fit-ranker failure; high `clinical_judgment_defer` is healthy clinical pushback that should retrain the urgency model) is the kind of operational signal-routing that distinguishes a senior recommender from a junior one.
- LLM scope kept tight: candidate-gap surfacing (review-gated), pre-visit clinician briefings, patient-facing closure messaging, chase-agent briefs. Not picking the gaps. Not deciding to escalate. *"The recommender picks. The LLM packages."* Same one-line framing as 4.5.
- DLQ coverage flagged in production-gaps with the right level of specificity and an even sharper failure-mode framing than 4.5: *"A silently-dropped closure event is operationally damaging in this recipe (the chase team calls a patient who already closed the gap), so the DLQ coverage matters more here than in some prior recipes."* The framing is correct.
- Cross-recipe sequencing: forward-references to 4.7 (Care Management) and to Chapters 7, 8, 12, 13, 14 are appropriate. The "Where This Sits in the Chapter" section's framing of 4.6 as building directly on 4.4 and 4.5 with three new pieces (per-(patient, gap) clinical urgency model, visit-context-aware ranking, multi-source closure tracking) is a clean chapter narrative.

### Finding A1: Optimistic Contact-Counter Increment Has No Reconciliation Path; Counter Is Cross-Recipe Global

- **Severity:** HIGH
- **Expert:** Architecture (fairness, correctness, cross-recipe coordination)
- **Location:** Step 4 pseudocode (`orchestrate_async_closures`), the `DynamoDB.UpdateItem ... ADD outreach_recent_total_30d_count :one` block; Step 5 pseudocode (`process_closure_event`), no decrement on `closure_outreach_failed` / `closure_outreach_bounced` / `closure_outreach_undeliverable` events; existing TechWriter TODO immediately following Step 4.
- **Problem:** Same High finding as 4.4 Finding 9 and 4.5 Finding A1, propagated forward. The TechWriter TODO directly under Step 4 names the gap and points back to the 4.4 / 4.5 fix language:

  > *"Same reconciliation gap as 4.5. The optimistic increment of `outreach_recent_total_30d_count` happens before send confirmation. Add to Step 5 the matching `closure_outreach_failed` / `closure_outreach_bounced` clauses that decrement the counter, plus a stale-pending sweep for tracking_ids with no engagement-stream activity within 24 hours. The cross-recipe global counter makes this even more important: a phantom contact recorded in this recipe suppresses outreach for the patient in 4.4, 4.5, and 4.7 too."*

  The TODO is correct and complete. The pseudocode does not yet implement what the TODO promises.

  Two reasons this finding is HIGH despite being TODO'd, and *worse* in 4.6 than in 4.4 or 4.5:

  1. **The counter is now explicitly named as a *cross-recipe global counter* shared with 4.4, 4.5, and 4.7.** A phantom contact recorded in 4.6 silently suppresses outreach for the same patient in *all four* recipes. The blast radius is four times larger than in the prior recipes. The Honest Take's argument for cross-recipe coordination (a patient with multiple care gaps, multiple non-adherent medications, and a wellness program enrollment recommendation can easily exceed any reasonable contact-frequency budget if each recipe orchestrates independently) is the correct framing; the counter is the foundation; the foundation has a leak.

  2. **The members most affected (members with flaky channels in cohorts the equity floors are trying to protect) accumulate phantom global cap consumption every time *any* recipe's outreach bounces.** After 2-3 weeks of bounces across recipes, they hit the global cap and get silenced across the entire chapter's outreach surface. The deferral reason (`contact_cap_exceeded`) looks legitimate on the cohort dashboard. The cohorts the equity floors protect for the *first* recommendation get silently silenced for the *second through Nth* recommendation; the silencing is invisible in standard dashboards because the deferral reason is the same one a healthy member would get.

  Why this is HIGH despite being TODO'd:

  1. The pseudocode is what readers copy. A TODO that says "fix this in implementation" is not the same as fixing it in the pseudocode the recipe presents as the architectural pattern.
  2. The 4.4 review flagged this as HIGH; the 4.5 review flagged this as HIGH; both gaps propagated forward unresolved. The chapter editor should treat this as a blocker for 4.4, 4.5, and 4.6 in tandem rather than letting the gap accumulate further.
  3. The cross-recipe global-counter framing in 4.6 makes the existing 4.4/4.5 fix specification *insufficient* for this recipe; the reconciliation must also include a global-counter-consistency invariant (the global counter and the per-recipe counters must reconcile to the same value).

- **Fix:** Same as 4.4 Finding 9 and 4.5 Finding A1, with the cross-recipe extension. Implement the reconciliation in the pseudocode:

  ```
  // In process_closure_event (or in a separate process_outreach_delivery_event handler), add:
  IF event.event_type in ["closure_outreach_failed",
                           "closure_outreach_bounced",
                           "closure_outreach_undeliverable"]:
      DynamoDB.UpdateItem(
          "patient-profile",
          event.patient_id,
          "ADD outreach_recent_total_30d_count :neg_one",
          ConditionExpression = "outreach_recent_total_30d_count > :zero",
          ExpressionAttributeValues = {
              ":neg_one": -1,
              ":zero":     0
          }
      )
      emit_metric("outreach_delivery_failure_decrement", value=1, dimensions={
          event_type: event.event_type,
          recipe: "4.6",
          chosen_pathway: rec.chosen_pathway,
          channel: event.channel
      })
      RETURN

  // Stale-pending sweep, runs hourly:
  FUNCTION reconcile_silent_recommendations(threshold_hours = 24):
      silent_rows = recommendation-log.scan(
          run_date < (now() - threshold_hours),
          generates_patient_contact = true,
          recipe = "4.6",
          NO matching event in engagement-events
      )
      FOR each row in silent_rows:
          DynamoDB.UpdateItem("patient-profile", row.patient_id,
              "ADD outreach_recent_total_30d_count :neg_one",
              ConditionExpression = "outreach_recent_total_30d_count > :zero",
              ExpressionAttributeValues = { ":neg_one": -1, ":zero": 0 })
          emit_metric("silent_outreach_reconciled", value=1, dimensions={recipe: "4.6"})
  ```

  Add a paragraph to the architecture pattern section naming the cross-recipe invariant: *"The `outreach_recent_total_30d_count` counter is a chapter-wide global counter shared with 4.4, 4.5, and 4.7. Every increment in any recipe must have a matching decrement on delivery failure and a stale-pending sweep. A reconciliation invariant test (the global counter equals the sum of recipe-specific counters within tolerance) runs nightly; divergence is alarmed."* Resolve the TODO once the pseudocode reflects this. Coordinate with the 4.4 and 4.5 fixes; the chapter editor should land all three together.

### Finding A2: `data_quality_flag` Is Computed and Propagated but Never Gates Downstream Decisions

- **Severity:** HIGH
- **Expert:** Architecture (correctness, fairness, chase-team trust)
- **Location:** Step 1 pseudocode: `data_quality_flag: assess_source_completeness(patient_id, measure)` with values `complete`, `sparse_history`, `multi_source_disagreement`, `recent_plan_change`, `cross_provider_fragmentation`; Step 2 / 3 / 4 pseudocode: no gate on this flag; "Where it struggles" first bullet: *"The `data_quality_flag` exposes this, but downstream consumers (chase team, dashboards) need to gate on it. A 'gap open' label on a patient with `cross_provider_fragmentation` data quality is much less reliable than the same label on a patient with `complete` data quality."*
- **Problem:** Same High finding as 4.5 Finding A2, propagated forward. The recipe acknowledges in prose that the data-quality flag must be gated on, then never gates on it in the pseudocode. The flag is computed in Step 1, persisted to the `patient-gaps` table, and ... never read by any downstream component.

  Care-gap-specific reasons this is *worse* in 4.6 than in 4.5:

  1. **The "calling a patient about a colonoscopy they had last week" failure mode is the recipe's most prominently worried-about failure mode.** The Honest Take says: *"A program that calls patients about colonoscopies they had last week earns a level of operator-distrust that's hard to recover from, and it's all closure-tracking failure, not modeling failure."* The `cross_provider_fragmentation` flag is exactly the signal that flags this risk for a specific patient. Not gating on it produces precisely the failure mode the Honest Take warns against.

  2. **Five distinct downstream gates are missing**, more than in 4.5:
     - **Step 2 (clinical urgency scoring):** doesn't downweight or skip patients with non-`complete` quality flags.
     - **Step 3 (visit-context ranking):** doesn't suppress low-quality gaps from the in-visit agenda or briefing.
     - **Step 4 (async orchestration):** doesn't route low-quality cases to a verification-first pathway.
     - **Step 5 (closure tracker):** doesn't tighten the canonical-source rule for low-quality cases.
     - **Step 6 (override handler):** doesn't apply different suppression policies based on data quality.

  3. **The cohorts most affected by data fragmentation correlate with mobility, plan changes, and access barriers.** Patients seen across multiple practices, patients who recently switched plans, patients who use retail clinics for screenings, patients who use home test kits without electronic result return. These cohorts disproportionately overlap with the populations the recipe's equity floors are trying to protect.

  4. **The chase-team workflow has a documented operational consequence.** The recipe says: *"chase teams should respect the provisional state to avoid the 'we just called you about the colonoscopy you had last week' failure mode."* The chase-team queue is populated in Step 4's `CASE "chase_team_call"` block. There is no gate on data quality before the chase brief is generated; a `cross_provider_fragmentation` patient who actually closed the gap at an out-of-network gastroenterologist gets a chase-team call asking them to schedule a colonoscopy they already had.

- **Fix:** Add explicit gating throughout the pipeline. Five places:

  1. **Clinical urgency scoring (Step 2):** Cap the rule-based and supervised urgency confidences to reflect genuine uncertainty when data quality is non-`complete`:

     ```
     IF gap.data_quality_flag != "complete":
         urgency.confidence_interval = widen_by_quality_factor(
             urgency.confidence_interval, gap.data_quality_flag)
         priority_components.urgency_contrib *= QUALITY_DAMPING[gap.data_quality_flag]
     ```

  2. **Visit-context ranking (Step 3):** Suppress low-quality gaps from the in-visit agenda; route them to a "verify first" pathway in the async queue:

     ```
     IF gap.data_quality_flag in ["multi_source_disagreement",
                                   "cross_provider_fragmentation"]:
         row.visit_fit.pathway_compatibility = 0  // forces async deferral
         row.async_routing_hint = "verify_first"
     ```

  3. **Async orchestrator (Step 4):** Route low-quality cases to a verification-first pathway (member-portal or chase-team verification call confirming whether the gap was already closed at an out-of-network provider) *before* any closure-pathway-specific outreach:

     ```
     IF candidate.data_quality_flag in ["multi_source_disagreement",
                                         "cross_provider_fragmentation"] AND
        candidate.async_routing_hint == "verify_first":
         chosen_pathway = "verification_first"
         // Routes to a low-friction "did you have this done?" portal/SMS prompt;
         // chase-team call only if no response in 7 days.
     ```

  4. **Closure tracker (Step 5):** For low-quality patients, treat any qualifying event as `confirmed_closed` regardless of canonical source (the patient's actual closure happened; the data fragmentation is the program's data problem, not the patient's adherence problem):

     ```
     IF gap.data_quality_flag == "cross_provider_fragmentation":
         // Patient self-report or any non-canonical source closes the gap
         // because the canonical source is structurally not going to confirm.
         new_state = "confirmed_closed"
     ```

  5. **Chase-team brief generation (Step 4 `CASE "chase_team_call"`):** Always include the data-quality flag and the verification-first opening if applicable:

     ```
     brief = Bedrock.InvokeModel(
         model_id = CHASE_BRIEF_MODEL_ID,
         body     = build_chase_brief_prompt(row, include_verification_opening=true
                                              if row.data_quality_flag != "complete"
                                              else false)
     )
     ```

  Add a paragraph to the architecture pattern section naming the gate explicitly: *"The `data_quality_flag` is not metadata; it's an input to every downstream stage. The urgency model dampens confidence on non-`complete` cases. The visit-context ranker suppresses low-quality gaps from the in-visit agenda. The async orchestrator routes low-quality cases through a verification-first pathway. The closure tracker tightens canonical-source rules for fragmented data. The chase-team brief generator opens with verification when data quality is in doubt. A 'gap open' label on a `cross_provider_fragmentation` patient is much less reliable than the same label on a `complete`-quality patient, and the architecture must encode that explicitly."*


### Finding A3: HEDIS Comprehensive Diabetes Care (CDC) Measure Name Is Retired; Recipe Uses Outdated Naming

- **Severity:** HIGH
- **Expert:** Architecture (clinical accuracy, HEDIS specification accuracy)
- **Location:** "The Technology / What a Care Gap Actually Is" subsection, the quality-measure-defined gaps bullet: *"HEDIS Comprehensive Diabetes Care eye exam"*; "The Problem" paragraph 4: *"Eye Exam for Patients with Diabetes is a HEDIS Stars bonus measure"*; Expected Results sample: `"measure_id": "hedis-cdc-eye-exam"`; sample patient gap state's measure version `"2026-v1"`. The Code Review's Finding 1 confirms the synthetic registry in the Python companion uses the same outdated naming.
- **Problem:** NCQA retired the parent Comprehensive Diabetes Care (CDC) measure starting in HEDIS Measurement Year 2022 and finalized the split into separate measures by MY 2024. The current measures are:

  - **EED**: Eye Exam for Patients with Diabetes (formerly CDC's eye-exam component)
  - **KED**: Kidney Health Evaluation for Patients With Diabetes (introduced MY 2020 to replace the CDC nephropathy attention component; the recipe's `ada-uacr-annual-diabetes` patient-specific gap maps to KED rather than to a free-standing ADA measure)
  - **GSD**: Glycemic Status Assessment for Patients With Diabetes (formerly CDC's HbA1c poor control measure, broadened in MY 2024 to include CGM-derived glucose management indicators)
  - **BPD**: Blood Pressure Control for Patients With Diabetes (formerly CDC's blood pressure component)

  A healthcare reader who looks up "HEDIS Comprehensive Diabetes Care eye exam" or `hedis-cdc-eye-exam` in current NCQA HEDIS specifications will not find them; they will find EED with a separate measure ID. The recipe's framing makes the cookbook look out of date with current NCQA practice.

  Why this is HIGH:

  1. **Clinical-accuracy credibility.** A reader who catches one HEDIS naming mistake will doubt the others. The Honest Take's argument for the measure registry is that the registry must be maintained continuously: *"A registry that drifts out of sync with NCQA's published HEDIS specs produces gap lists that don't match the plan's reported HEDIS performance, which is a credibility-destroying problem that takes months to recover from."* The recipe's own example registry references a retired measure name. The recipe is, by its own definition, drifting.

  2. **The "diabetic foot exam" reference is potentially also stale.** The recipe says *"He is overdue for his diabetic foot exam (last documented one was 19 months ago; the practice's quality dashboard shows it red)."* The HEDIS measure for diabetic foot exam (formerly CDC's foot-exam component) was retired entirely from HEDIS at the CDC split; foot exams are still clinically recommended (ADA Standards of Care) but are not currently a HEDIS or Star Ratings measure. The recipe's assertion that the practice's quality dashboard "shows it red" implies a HEDIS-equivalent measure that does not exist. The clinical urgency framing remains valid (ADA recommends annual comprehensive foot exam for adults with diabetes), but the HEDIS framing is wrong.

  3. **The CMS Star Ratings claim about diabetic eye exam being a "HEDIS Stars bonus measure" is technically correct for EED.** EED is in the Part C Star Ratings as one of the diabetes care measures. The recipe's framing isn't wrong on the Stars-bonus point; it's wrong on the underlying measure name. Easy fix.

  4. **The Python companion's synthetic registry uses `hedis-cdc-eye-exam` and `hedis-cdc-foot-exam` as `measure_id` values throughout.** The Code Review's Finding 1 references this naming in the demo runner. The recipe and Python fix need to land together; otherwise the recipe text uses one measure name and the Python uses another.

- **Fix:** Three coordinated text changes plus a Python-companion follow-up:

  1. **Replace the CDC reference in The Technology section.** *"HEDIS Comprehensive Diabetes Care eye exam"* should become: *"HEDIS Eye Exam for Patients with Diabetes (EED)"*. Add a parenthetical note: *"NCQA retired the parent Comprehensive Diabetes Care (CDC) measure beginning HEDIS MY 2022 and split it into EED, KED (Kidney Health Evaluation), GSD (Glycemic Status Assessment), and BPD (Blood Pressure Control). Recipes that reference older HEDIS measure-set documentation should re-validate against the current MY measure spec."*

  2. **Update the Expected Results sample.** Change `"measure_id": "hedis-cdc-eye-exam"` to `"measure_id": "hedis-eed"` (or whatever convention the registry uses for EED).

  3. **Fix the diabetic foot exam framing in The Problem.** Either remove the "practice's quality dashboard shows it red" reference (ADA recommends the foot exam clinically; no current HEDIS or Star measure tracks it) or replace it with a "patient-specific clinical gap" framing consistent with the recipe's own three-source taxonomy: the foot exam is a guideline-recommended (ADA) gap that's not a current HEDIS measure; it's red on the practice's quality dashboard because the practice's quality program tracks ADA guidelines internally, not because a HEDIS-equivalent dashboard does.

  4. **Coordinate with the Python companion's synthetic registry.** The Code Review's Finding 1 already flags an issue with the demo runner; the fix should also update the registry's `measure_id` values from `hedis-cdc-*` to current EED / GSD / KED / BPD naming. <!-- TODO (TechWriter): coordinate with the Python companion fix; both files need consistent measure naming. -->

### Finding A4: Per-Patient Cohort-Feature Lookup Repeats N Times Per Patient (Same Pattern as 4.4 Finding 13 and 4.5 Finding A4)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 2 pseudocode (`enrich_open_gaps`), the `cohort_features = lookup_cohort_features(gap.patient_id)` call inside the per-gap loop; Step 4 pseudocode (`orchestrate_async_closures`), the `cohort_features = candidate.cohort_features` reference and the `applicable_floor_cohorts(cohort_features, ...)` use.
- **Problem:** Same finding as 4.4 Finding 13 and 4.5 Finding A4. The enrichment loop's per-gap cohort-feature lookup repeats for every gap on the same patient; a patient with 11 open gaps (David from the opening) produces 11 cohort-feature lookups for the same patient. At 250K eligible patients with on average 3-7 open gaps each, the gap count is 750K-1.75M; the redundant cohort lookups multiply DynamoDB reads accordingly.

  Additional consistency concern (carried forward from 4.5): a process that updates `patient-profile.sdoh_cohort` between two reads in the same enrichment run produces inconsistent cohort assignments across the same patient's gaps. Equity-floor allocator decisions depend on consistent assignment.

- **Fix:** Hoist the cohort-feature cache out of the per-gap loop. Build it once per unique patient before the enrichment walk:

  ```
  // Build once per unique patient
  patient_cohort_cache = {}
  unique_patients = set([g.patient_id for g in open_gaps])
  FOR each patient_id in unique_patients:
      patient_cohort_cache[patient_id] = lookup_cohort_features(patient_id)

  // Then attach the cached value inside the per-gap loop
  FOR each gap in open_gaps:
      cohort_features = patient_cohort_cache[gap.patient_id]
      ...
  ```

  Reference the chapter-wide pattern from 4.4 Finding 13 and 4.5 Finding A4. The chapter editor should consider consolidating into a chapter-4 preface.

### Finding A5: `outreach_recent_total_30d_count` Counter Has No Decay or Windowing Mechanism (Same Pattern as 4.4 / 4.5)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 4 pseudocode, the `existing_contacts = member.outreach_recent_total_30d_count` read and the `ADD outreach_recent_total_30d_count :one` increment; no decay logic shown anywhere in this recipe or in the cross-recipe orchestration TODO.
- **Problem:** Same pattern as 4.4 Code Review Finding 9 and 4.5 Finding A5. The counter increments forward but never decays. The "30d" in the name implies a rolling 30-day window; the implementation is a monotonically-increasing counter.

  Care-gap-specific sharpening: this counter is now explicitly a *cross-recipe global counter* shared with 4.4, 4.5, and 4.7. Without windowing, every recipe contributes increments that never decay; a member who got contacts across all four recipes over six months has a counter value that no longer reflects 30-day frequency by any reasonable interpretation. The deferral reason (`contact_cap_exceeded`) on the cohort dashboard becomes meaningless, just as it does in 4.5, but at four times the scale.

  This compounds with Finding A1 (no decrement on delivery failure): both gaps push members into the deferred bucket and neither has a way to release them. With four recipes contributing, the cumulative effect is much worse than in any single recipe.

- **Fix:** Pick a rolling-window pattern and document it as a chapter-wide convention, not a per-recipe fix. Three reasonable options (same as 4.5 Finding A5):

  1. **DynamoDB TTL on per-event rows.** Each outreach increments a per-event row keyed on (patient_id, event_id, recipe) with a TTL of 30 days; the counter is computed on read by aggregating TTL-live rows. Auto-decays without scheduled jobs. Naturally cross-recipe.
  2. **Daily-bucket counters.** Counter is split into 30 daily buckets per patient (e.g., `outreach_count_2026_05_04`, `outreach_count_2026_05_05`, ...). Reads sum across the trailing 30 buckets. A scheduled cleanup deletes buckets older than 30 days.
  3. **Scheduled decay Lambda.** Hourly or daily Lambda decrements the counter by the count of events that aged past the 30-day threshold. Requires the per-event log to compute the decrement set.

  Document the chosen pattern in the architecture and coordinate with the cross-recipe TODO. The 4.4, 4.5, and 4.6 fixes should land together as a chapter-wide hardening pass.

### Finding A6: No Sequencing State Machine for Chained Care Gap Closures (Same Pattern as 4.5 Finding A7)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** "Variations and Extensions" mentions specialist-coordination workflows and outreach bundling, but the core architecture and Steps 2-4 pseudocode do not show any chain-aware allocation; the "Why This Isn't Production-Ready" section does not explicitly call out chained closures (in contrast, 4.5 explicitly named the cost-assistance → reminder chain pattern).
- **Problem:** Care gaps frequently chain in ways that match the 4.5 pattern. Examples:
  - **Specialist referral workflow:** referral generated → patient schedules → patient attends → result returned to PCP → gap confirmed-closed. Each link has its own probability and is conditional on the previous link.
  - **Verification-first pattern:** verification-first prompt → patient confirms previously-closed → gap excluded; or patient confirms not-closed → standard outreach triggered.
  - **Bowel-prep + colonoscopy:** prep instructions sent → prep confirmed → procedure attended → result returned. The recommender's job is to track all four links.
  - **Cost-help-first then closure:** patient identified with cost barrier on a referral-required gap → cost-assistance navigation completes → patient now has financial means to attend the appointment → standard referral flow.

  The pseudocode does not show how chained interventions are tracked. The Step 4 `CASE "specialist_referral"` block enqueues a referral and stops. The 4.5 finding was about the absence of a chain-aware allocator; in 4.6 the same gap exists, *plus* the additional referral-chain links (scheduling, attendance, result return, PCP notification) that are core to specialist-driven gap closures.

  The "Variations and Extensions" section names "Specialist-coordination workflows" as a thing the architecture *should* support, but doesn't show the architectural primitive (chain_id, chain_position, predecessor/successor linkage in the recommendation log). Without these primitives, the closure-tracker can confirm a colonoscopy was performed (claims event) but cannot reason about the intermediate steps the chase team was managing; the chase team's attendance-confirmation event has no explicit place to be recorded against the chain.

- **Fix:** Same as 4.5 Finding A7, with care-gap-specific extensions. Add a small subsection (200-300 words) showing the state-machine version concretely:

  - `recommendation-log` adds `chain_id` (UUID), `chain_position` (1, 2, 3...), `chain_total` (length), and `predecessor_recommendation_id` (nullable).
  - The async orchestrator emits the first link of the chain (e.g., referral_generation) with `chain_id = uuid()` and `chain_position = 1`. Later links are not allocated until the predecessor completes.
  - Step 5's `process_closure_event` adds an intermediate-event handler: events that match a chain link without closing the gap (e.g., `referral_scheduled`, `referral_attended`) advance the chain_position and trigger the next link's allocation. Only the final qualifying event (per the registry's numerator definition) closes the gap.
  - For specialist-referral chains specifically, the architecture diagram needs an explicit "referral management workflow" component that owns the intermediate links between the recommender's referral generation and the final result return.

  Reference Recipe 14.x as the place where chain-aware allocation under capacity constraints becomes a formal multi-stage stochastic program. The starter is the state-machine version shown here.

### Finding A7: Step 1 Candidate-Gap Surfacer Validator Is the Same Validator Pattern as 4.5; Specify in Tandem

- **Severity:** MEDIUM
- **Expert:** Architecture (LLM safety, candidate review queue integrity)
- **Location:** Step 1 pseudocode (in `evaluate_measures`), the `validate_candidate_gaps(candidates, patient_id, observed_data = chart_context)` call with an inline TechWriter TODO partially specifying the four-layer structure.
- **Problem:** Same finding as 4.5 Finding A6 (the `validate_barrier_review` validator). The validator is named in pseudocode and the TODO begins to specify the four-layer structure, but the implementation isn't fully specified. The candidate-gap surfacer is one of the chapter's tightest LLM-scope examples (the LLM proposes; clinical informatics curates; durable patterns get encoded into the registry; the LLM is a discovery tool, not a source of truth) and the validator is what protects the integrity of that pipeline. An unenforced or naively-implemented validator pollutes the clinical-informatics review queue with hallucinated candidate gaps, which wastes clinical-informatics time and erodes the discovery mechanism's value.

  The TODO already names the four-layer structure: schema and taxonomy check, rationale length/structure, rationale must cite observable data points whose values match observed_data within tolerance, prohibited content (PHI not in source, prescriber names) in rationale. The structure is correct. What's missing is:

  1. **Tolerance specification for the "cited values match observed_data within tolerance" check.** What's the tolerance? Numeric values exact-match (an HbA1c of 7.8 cited as 7.8 is correct; cited as 7.5 is hallucination)? Date values within 7 days? The tolerance must be specified per data-type.

  2. **The "supporting_chart_excerpts" field in the candidate output schema.** The candidate output is `{ candidate_gap_label, rationale, suggested_evidence_to_check, confidence, supporting_chart_excerpts }`. The supporting_chart_excerpts field is the LLM's quotation from the chart. The validator must verify these excerpts actually appear in the chart context as of the prompt's timestamp; an LLM that hallucinates a quote is a major prompt-engineering failure that the validator must catch.

  3. **The taxonomy of allowed candidate-gap labels.** The candidate-gap surfacer can propose patterns the deterministic registry doesn't catch. The taxonomy must be open (otherwise the surfacer can't actually surface novel patterns) but bounded (otherwise the LLM proposes anything). The right pattern is a *category* taxonomy (the proposed gap must fit into one of N categories: monitoring-gap, screening-gap, conversation-gap, medication-titration-gap, etc.), with the specific within-category label free-form. Specify the category taxonomy.

- **Fix:** Specify the four-layer validator with the three additions above:

  ```
  FUNCTION validate_candidate_gaps(candidates, patient_id, observed_data):
      validated = []
      FOR each candidate in candidates:
          // Layer 1: schema and taxonomy
          IF candidate.category NOT IN ALLOWED_CANDIDATE_CATEGORIES:
              LOG("invalid candidate category", candidate=candidate)
              CONTINUE
          IF candidate.confidence NOT IN [0.0, 1.0]:
              LOG("confidence out of range", candidate=candidate)
              CONTINUE

          // Layer 2: rationale length and structure
          IF len(candidate.rationale) < MIN_LENGTH OR
             len(candidate.rationale) > MAX_LENGTH:
              LOG("rationale length out of bounds", candidate=candidate)
              CONTINUE

          // Layer 3: cited values match observed data within tolerance,
          // and supporting_chart_excerpts actually appear in chart context
          cited_values = extract_cited_values(candidate.rationale)
          FOR each cited in cited_values:
              IF NOT matches_observed(cited, observed_data, tolerance_for_type(cited)):
                  LOG("hallucinated value", cited=cited)
                  CONTINUE outer
          FOR each excerpt in candidate.supporting_chart_excerpts:
              IF excerpt NOT IN observed_data.chart_text:
                  LOG("hallucinated excerpt", excerpt=excerpt)
                  CONTINUE outer

          // Layer 4: prohibited content
          IF contains_pii_outside_patient(candidate.rationale, patient_id):
              LOG("rationale contains PII outside patient", candidate=candidate)
              CONTINUE
          IF contains_prescriber_name(candidate.rationale):
              LOG("rationale contains prescriber name", candidate=candidate)
              CONTINUE

          validated.append(candidate)

      RETURN validated
  ```

  Specify failure-handling: validator failure means the candidate is dropped from the review queue and the failure is logged for prompt-engineering review. Reference 4.5 Finding A6's parallel `validate_barrier_review` specification; the two validators share most of their structure.


### Finding A8: SageMaker Training-Job Promotion Path Not Specified (Same Pattern as 4.4 / 4.5)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Architecture diagram's `M1[SageMaker Training\nperiodic retrain]` node with arrows to `H2` (urgency Batch Transform) and `H3` (engagement Batch Transform); Why This Isn't Production-Ready *Clinical-urgency model training data* paragraph mentions training data preparation but doesn't address promotion path; existing TechWriter TODO acknowledges the gap.
- **Problem:** Same finding as 4.4 and 4.5 (mirrored TODO acknowledged). The architecture diagram shows training feeding inference but doesn't show the trigger mechanism (EventBridge schedule? Drift threshold? Manual?), the promotion path (SageMaker Model Registry? Approval workflow?), or the canary/parallel-evaluation step before a new model version replaces the production model.

  Care-gap-specific reasons this matters more than in 4.5:

  1. **Three model families per gap-type-bucket.** The recipe says: *"Three model families live here: the per-gap-type clinical urgency model ... the per-pathway engagement and completion-probability models ... and an optional per-gap-type uplift model."* Each family has many models (per gap type, per pathway). The promotion path needs to handle bulk promotions across families coherently (a new urgency model for one gap type shouldn't be promoted while the engagement model for the same gap-pathway pair stays on the old version, unless the team has explicitly decided that's safe).

  2. **The clinical urgency model directly affects clinical decisions.** A misranked urgency score puts the wrong gap on the visit agenda. The promotion path needs a clinical-validation gate: a new urgency model version must pass a clinical-validation suite (sample of N high-urgency cases reviewed by clinical informatics, ranking-correlation against a ground-truth set) before promotion. The "Why This Isn't Production-Ready" *clinical-rule audit on a quarterly cadence* paragraph names the audit cadence for rule-based urgency; the parallel cadence for supervised urgency is unspecified.

  3. **Cohort-specific calibration audits must be part of promotion.** The "Where it struggles" section names *"Cohort fairness in the urgency model"* as a known gap. The promotion path should require cohort-level calibration evaluation before promotion, not as a post-hoc dashboard check.

- **Fix:** Add a paragraph specifying the promotion path:

  ```
  - **Trigger:** EventBridge schedule (monthly retrain) + CloudWatch metric threshold
    (drift > X percent triggers off-cycle retrain).
  - **Promotion:** SageMaker Model Registry tracks all training-job artifacts;
    a new model version is registered as `pending_review`. A canary Batch
    Transform job runs the new version against a frozen evaluation set in
    parallel with the current production version. Outputs are compared:
    rank correlation, cohort-level calibration, top-K agreement on high-urgency
    cases. A clinical-informatics review approves or rejects within a defined
    SLA. Approved versions move to `approved`; production inference reads from
    the latest `approved` version.
  - **Rollback:** A model version can be reverted by changing the model alias
    pointer in the inference pipeline; rollback is a one-click operation, not
    a redeploy.
  - **Cohort calibration gate:** Promotion fails if cohort-level calibration
    error exceeds a documented threshold for any monitored cohort (language,
    SDOH cohort, age band). This is a hard gate, not a warning.
  ```

  Reference Recipe 7.x (Predictive Analytics) where the promotion-path discipline gets covered in more depth. Resolve the existing TODO once this is specified.

### Finding A9: Pneumococcal Vaccine "Newly Indicated at 64" and Family-History Colon Cancer Urgency Are Clinically Loose

- **Severity:** MEDIUM
- **Expert:** Architecture (clinical accuracy, vignette credibility)
- **Location:** "The Problem" paragraph 3: *"He has not had the pneumococcal vaccine that became indicated when he turned 64 in February."*; "The Problem" paragraph 3 (continuing): *"He is overdue for his colonoscopy (last one was at 54, ten years ago, when normal-result recommendations were every ten years; the current USPSTF guidance starts at 45 and his family history flags him for earlier and more frequent screening)."*
- **Problem:** Two clinical claims in the David vignette that don't quite hold up.

  **Pneumococcal vaccine at 64:** The CDC and ACIP recommendations for pneumococcal vaccination in adults are:
  1. **All adults aged 65+** should receive pneumococcal vaccination (PCV20 alone, or PCV15 followed by PPSV23 ≥1 year later).
  2. **Adults aged 19-64 with certain chronic conditions** (including diabetes mellitus) have indications for PPSV23 well before age 65.

  Diabetes is one of the chronic conditions that triggers PPSV23 indication for adults 19-64. David has had diabetes for nine years. Under the prior PPSV23-for-diabetics-19-64 guidance, he should have received PPSV23 in his 50s. Under current ACIP guidance (PCV15/PCV20 with simplified recommendations for adults with chronic conditions), he should have received the higher-valent vaccine well before age 65.

  The recipe's framing *"the pneumococcal vaccine that became indicated when he turned 64 in February"* implies the indication arrived at age 64, which is not how the CDC/ACIP recommendations work for diabetics. A more accurate framing: *"He has not had the pneumococcal vaccine. He turned 64 in February; current ACIP guidance recommends pneumococcal vaccination for all adults 19-64 with diabetes (PPSV23 historically; PCV15/PCV20 under current simplified recommendations) and the practice's quality dashboard flagged this gap years ago, but it never got addressed at a visit."* This framing keeps the vignette's tension (the gap has been open) without misstating ACIP.

  **Colon cancer family history:** The recipe's framing *"his family history flags him for earlier and more frequent screening"* is overstated for the specific family history described (father died of colon cancer at 71). The current NCCN, ACG, and U.S. Multi-Society Task Force guidelines for elevated-risk screening trigger when:
  - First-degree relative diagnosed with CRC at age <60 (start screening at age 40 or 10 years before earliest case, every 5 years)
  - Two or more first-degree relatives with CRC at any age
  - Polyposis syndromes
  - Inflammatory bowel disease

  A father diagnosed at age 71 (i.e., not <60) generally does *not* qualify for the elevated-risk screening protocol; the patient is treated as average-risk under most guidelines. (Some guidelines suggest screening "10 years before the earliest case" which would mean age 61 for David, which he has now passed; he's overdue under that variant. But the broader "earlier *and* more frequent screening" framing is the elevated-risk protocol that this family history doesn't trigger.)

  David is *unambiguously overdue under any guideline*: his last colonoscopy was at age 54, ten years ago, and current USPSTF recommends screening starting at age 45 (but the relevant fact for David at age 64 is that he had the screening at 54 with a normal result and the next interval is 10 years, so he's basically right at the recommended interval — actually 64-54 = 10 years, so he's *exactly at* the next-due date, not "six years overdue"). The Honest Take's reference to *"his colonoscopy that's six years overdue"* is mathematically inconsistent with the vignette's own setup of "last one was at 54, ten years ago" (David is 64; the gap window opened when he turned 64; the colonoscopy is now due, not "six years overdue"). The "six years overdue" framing only makes sense if David is treated as elevated-risk and the surveillance interval is 5 years, not 10; but the family history doesn't strongly support that.

- **Fix:** Two small text changes:

  1. **Pneumococcal vaccine framing.** Replace *"the pneumococcal vaccine that became indicated when he turned 64 in February"* with *"the pneumococcal vaccine. ACIP has recommended pneumococcal vaccination for adults with diabetes for years; David's gap has been open for most of a decade."* Adjust subsequent text accordingly.

  2. **Colonoscopy framing.** Two options:
     - **Tighten the family-history claim.** Either describe a stronger family history (a paternal diagnosis at <60, or a maternal-side diagnosis as well) that genuinely triggers elevated-risk screening, or drop the "earlier and more frequent" elevated-risk framing and treat David as average-risk where the gap is "the 10-year interval has elapsed" rather than "elevated-risk surveillance is overdue."
     - **Fix the "six years overdue" math in the Honest Take.** If David is at age 64 with a normal colonoscopy at age 54, the next average-risk colonoscopy is due now, not six years ago. The Honest Take's *"his colonoscopy that's six years overdue"* should become *"his colonoscopy that's overdue under both average-risk USPSTF guidance and any elevated-risk family-history protocol."*

  These are minor accuracy issues that don't change the recipe's architectural points, but the David vignette is meant to be the recipe's strongest opening, and a healthcare reader will catch these inconsistencies. Worth a 30-minute clinical-informatics review pass on the entire vignette.

### Finding A10: Closure Tracker State Machine Has No Defense Against Out-of-Order Event Arrival

- **Severity:** MEDIUM
- **Expert:** Architecture (eventual consistency, idempotency)
- **Location:** Step 5 pseudocode (`process_closure_event`), the state-machine update logic; "Why This Isn't Production-Ready" *Multi-source closure reconciliation engineering* paragraph mentions out-of-order arrival as a known concern but doesn't show how the architecture handles it.
- **Problem:** The recipe's prose acknowledges the problem: *"The reconciliation logic needs to handle: events arriving out of chronological order, partially-redacted events from registries with patient-consent restrictions, retroactive corrections, and events from sources that periodically restate."* The pseudocode does not reflect this. The state-machine logic is:

  ```
  IF event.source == measure.canonical_source:
      new_state = "confirmed_closed"
  ELSE:
      IF gap.state == "open":
          new_state = "provisionally_closed"
      ELSE:
          new_state = gap.state  // already provisional; no change
  ```

  This logic is not robust to out-of-order event arrival. Consider:

  1. **Patient closes gap on day 1; canonical claims event arrives day 14; non-canonical EHR event arrives day 21 (delayed by EHR sync).** Day 14: state transitions to `confirmed_closed`. Day 21: the non-canonical event arrives; the pseudocode says `IF gap.state == "open"... ELSE new_state = gap.state` so the confirmed_closed state is preserved. Correct.

  2. **Patient closes gap on day 1; non-canonical EHR event arrives day 2; canonical claims event arrives day 14.** Day 2: state transitions to `provisionally_closed`. Day 14: state transitions to `confirmed_closed`. Correct.

  3. **Patient closes gap on day 1; non-canonical EHR event arrives day 14; canonical claims event arrives day 2 (out of order on receipt).** Day 2: state transitions to `confirmed_closed`. Day 14: the non-canonical event arrives; pseudocode says state stays `confirmed_closed`. Correct.

  4. **The dangerous case: retroactive correction.** Patient closed on day 1; canonical event arrives day 14 with a typo on the procedure code; recipient marks `confirmed_closed`. Day 21, a corrected canonical event arrives with the correct code. Day 30, an *uncorrection* event arrives (the registry submits a void/correction for the original entry). The pseudocode has no concept of "this event invalidates a prior event"; the state machine cannot un-confirm a confirmed close.

  5. **Late-arriving exclusion.** Patient was in the denominator on day 1; closure event arrived day 14 marking `confirmed_closed`; on day 30, an exclusion event arrives (the patient was actually in palliative care for the entire measurement year, which retroactively excludes them). The pseudocode does not show how the state transitions back to `excluded` when the exclusion arrives later than the closure.

  The fix is to make the state machine idempotent over event timestamps: every event carries a `source_timestamp`, the state machine evaluates the *current state given all events received to date* rather than the *delta from the previous state*, and a corrections handler can mark events as superseded.

- **Fix:** Add a paragraph to the architecture pattern naming the event-stream-as-source-of-truth pattern:

  ```
  Closure-tracker idempotency: Events are stored in a per-(patient, gap)
  event log, ordered by event.timestamp. The current gap state is computed
  by replaying the event log under the canonical-source rules from the
  registry. A new event re-triggers the replay rather than mutating the
  state directly. This guarantees:

  - Out-of-order arrivals produce the same final state regardless of receipt order.
  - Retroactive corrections can mark prior events as superseded; the replay
    skips superseded events and recomputes from the remaining ones.
  - Late-arriving exclusions can override prior closures without state-machine
    surgery: the exclusion is just another event; the replay produces "excluded"
    as the result.
  - Idempotent retries: a duplicate event matched by event_id is a no-op.
  ```

  The trade-off (replaying is more compute than mutation) is small in practice (most gaps have <10 events in their event log) and the correctness benefit is substantial. The current pseudocode's mutation-based pattern is brittle in the exact failure modes the prose names as concerns.

### Finding A11: Year-End Push "Chase Period Weight Overrides" Is Mentioned but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** "Why This Isn't Production-Ready" *Quality-measure year-end push handling* paragraph: *"Build the seasonality into the policy explicitly (e.g., a `chase_period_weight_overrides` block that activates between specific dates), document it, and put the cohort-equity dashboard on a shorter monitoring cycle during the chase."*
- **Problem:** The Honest Take warns at length about the year-end push trap: *"every quality program has a year-end period where chase activity ramps up and the dashboards turn green by sheer brute force ... the trap is treating year-end as the operating model rather than as a seasonal exception."* This is the recipe's most significant clinical-vs-operational tension, and the architectural primitive that supports the right operating posture (seasonal weight overrides with stricter equity monitoring during chase periods) is named but not architected.

  Specifically:
  1. **The policy weights are documented as `policy.weights.{clinical_urgency, closure_probability, measure_value, window_urgency}` with default values 0.40 / 0.20 / 0.20 / 0.20.** The architecture doesn't show how these flex by date.
  2. **The cohort-equity dashboard's monitoring cadence is defined once.** The architecture doesn't show how it tightens during chase periods.
  3. **The capacity-aware allocator's equity floors are defined once.** The architecture doesn't show how they shift during chase periods (the right pattern: equity floors *increase* during chase periods because the chase period disproportionately benefits operationally-easy cohorts; the equity floors compensate).

  Without the architectural primitive, a team building this recipe will end up with year-end policy changes happening in a config-management process that's separate from the recommender, which means the year-end equity-monitoring tightening doesn't happen and the year-end equity floors don't shift; both gaps produce the failure mode the Honest Take warns about.

- **Fix:** Add a paragraph (200 words) to the architecture pattern showing the seasonality plug-in:

  ```
  Seasonal policy overrides: The policy table in DynamoDB has a base policy
  (active year-round) and zero or more seasonal overrides keyed on
  (start_date, end_date, override_block). At policy resolution time, the
  effective policy is the base policy with the active seasonal override(s)
  merged in. A typical override block:

  {
    "name": "year_end_chase_2026",
    "start_date": "2026-10-01",
    "end_date":   "2026-12-31",
    "weight_overrides": { "window_urgency": 0.35 },  // up from 0.20
    "weight_caps":      { "window_urgency": 0.40 },  // hard cap
    "equity_floor_multipliers": {
        "transportation_barrier_cohort": 1.5,        // floors expand during chase
        "language_es_cohort":            1.3
    },
    "monitoring_cadence_days": 7  // down from 30
  }

  Seasonal overrides go through the same governance review as base policy
  changes (medical director, quality lead, equity lead, data science,
  operations). The cross-functional committee approves the override before
  it activates; the override deactivates automatically at end_date.
  Auto-activation without committee review is a process failure.
  ```

  This makes the chase-period seasonality a first-class architectural feature and ensures the equity-floor expansion the Honest Take recommends actually happens. Without this, the equity-floor expansion stays a "we should do that" rather than a default operating posture.


---

## Networking Expert Review

### What's Done Well

- VPC endpoint list is comprehensive and includes the new services this recipe introduces: *"VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis, Firehose, KMS, CloudWatch Logs, SageMaker Runtime, Step Functions (`states`), EventBridge (`events`), Glue, Athena, STS, SES, Pinpoint, Connect, HealthLake."* HealthLake's inclusion is correct for FHIR-based EHR ingestion.
- NAT Gateway scoped explicitly: *"NAT Gateway only for external services without VPC endpoints (e.g., a state immunization registry that does not support PrivateLink); restrict egress with security groups."* The state-immunization-registry example is a concrete, recipe-specific scenario that resolves a real-world question.
- EHR FHIR feed connectivity: *"EHR FHIR feeds typically arrive via PrivateLink, Direct Connect, or SFTP-over-VPN."* Correct posture for vendor data ingestion; continues the chapter pattern from 4.5's PBM-data-feed framing.
- Encryption in transit specified throughout. VPC Flow Logs enabled.

### Finding N1: `0.0.0.0/0` Egress Disallow Not Stated Explicitly (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row.
- **Problem:** Same finding as 4.1 / 4.3 / 4.4 / 4.5. The VPC row says "restrict egress with security groups" but doesn't explicitly disallow `0.0.0.0/0` egress on Lambda subnets. Worth capturing once chapter-wide.
- **Fix:** Add: *"No `0.0.0.0/0` egress from any Lambda subnet. NAT egress restricted by security group to specific IP ranges or hostnames (state immunization registries, foundation-grant vendor portals if applicable, EHR vendor APIs without PrivateLink). All other outbound traffic must go through VPC endpoints."*

### Finding N2: State Immunization-Registry Credential Posture Not Specified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Architecture diagram's `A5[Immunization Registry]` source; "Why These Services" section, Glue ETL mention; closure tracker's multi-source ingestion.
- **Problem:** State immunization registries (IIS, Immunization Information Systems) are state-government-operated systems with widely varying integration patterns. Some expose HL7v2 messages over VPN; some expose FHIR APIs with state-specific OAuth flows; some require SFTP submissions and pull-based polling for response files; some have no programmatic interface at all and require manual login through state-operated portals.

  Care-gap-specific reasons this matters:

  1. **The closure tracker treats immunization-registry events as canonical for vaccine measures in some states and not others.** The recipe says: *"the public-health immunization registry is canonical in some states for vaccines and not in others."* The credential posture has to support state-by-state configuration; a single shared credential approach won't work.

  2. **State IIS data is PHI under HIPAA and additionally regulated under state public-health statutes.** Several states have specific rules about who can read which data fields and under what consent regimes. The credential management must support per-state access scopes.

  3. **Some state IIS systems require VPN tunnels rather than supporting AWS PrivateLink.** The infrastructure pattern needs to accommodate site-to-site VPN per state, with the VPN concentrators isolated from general internet egress.

- **Fix:** Add a paragraph to the production-gaps section or the closure-tracking architecture description:

  *"State immunization-registry connectivity is per-state. Some states expose FHIR-over-OAuth APIs with state-specific identity providers. Others require HL7v2 messages over site-to-site VPN. Others require SFTP submission and asynchronous response-file pickup. Credentials live in Secrets Manager with KMS encryption and per-state rotation policies. State-specific access scopes (which data fields the program is authorized to read) are enforced in the integration layer; a state's restrictions on, e.g., adolescent vaccination records or HIV-related vaccinations may be tighter than the program's general access pattern, and the integration must respect those restrictions. Plan for per-state integration engineering effort that grows with the number of states the program operates in; a 50-state program will spend more on state-IIS integration than on most other source systems combined."*

### Finding N3: HealthLake Mentioned as Optional but FHIR API Encryption / mTLS Posture Not Specified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** "Why These Services" *AWS HealthLake* paragraph; existing TODO on HealthLake pricing / HIPAA eligibility.
- **Problem:** The recipe correctly flags HealthLake as optional and offers the lighter "direct FHIR API integration with bulk export to S3" alternative. Neither pattern's network posture is fully specified:

  - **HealthLake pattern:** The recipe says VPC endpoints for HealthLake are required. The encryption-in-transit posture (TLS 1.2+ between the EHR and HealthLake; HealthLake-to-S3 traffic over the VPC endpoint) is implied but not stated. Some EHR FHIR servers require mTLS; HealthLake's support for client certificates as a connection authentication method is not addressed.
  - **Direct FHIR-to-S3 pattern:** Where does the FHIR client run? If in Lambda, the Lambda is in the VPC; if the EHR FHIR server is on-premises, the connection goes over Direct Connect or VPN; if the EHR FHIR server is in another cloud, the connection goes through cross-cloud connectivity. None of these are specified.

- **Fix:** Add a sentence to the HealthLake paragraph:

  *"FHIR ingestion encryption: TLS 1.2+ on all FHIR connections. EHR FHIR servers that require mTLS authenticate the integration layer with client certificates managed through ACM Private CA; the certificate's private key never leaves the integration layer's KMS-encrypted store. Direct FHIR-to-S3 patterns route through PrivateLink to AWS or Direct Connect for on-premises EHRs; public-internet FHIR endpoints are not acceptable for PHI in the architecture."*

---

## Voice Reviewer

### What's Done Well

- The David vignette is the strongest opening in Chapter 4. The eleven gaps with their specific clinical and operational details (gap windows, lookback periods, HEDIS Stars bonus measure status, prior decline notes), the 25-minute visit broken into "five minutes reviewing the chart, ten minutes on the visit, ten minutes on documentation," the explicit "best case three gaps, more realistically two" scoping, the contrast between the unlucky-version-where-the-dashboard-wins and the lucky-version-where-the-PCP-knows-him-well, and the closing "which version of David's care is better" is the most directly contrarian opening in the chapter.
- *"The clinically obvious answer (the second one, where the kidney decline gets named and acted on) and the operationally rewarded answer (the first one, where the visible HEDIS measure closes within the measurement window) are not the same answer."* The op-vs-clin divergence is the recipe's central thesis stated in one sentence.
- *"A dashboard that's doing population health by sorting on the dimension easiest to report. The recommender in this recipe is trying to do population health by sorting on what's most likely to actually improve the patient's prognosis. They overlap a lot ... and they diverge in important places. The divergences are where the work happens."* The "divergences are where the work happens" framing is the cleanest articulation of why this recipe is worth building.
- *"The thing that surprises people coming from generic ML backgrounds is how much of the work is data engineering, not modeling."* The 80/20 framing for data engineering vs. modeling is the chapter's clearest articulation of where care gap programs actually spend their time.
- *"The thing I'd do differently the second time: invest in the closure tracker before the urgency model. ... Build the multi-source closure tracker first. Build the urgency model second. Build the visit ranker third."* The personal-confession framing with explicit ordering recommendations is exactly the CC voice the chapter rewards.
- *"The thing about the LLM components: they earn their keep on packaging, not picking."* Single-line synthesis of the chapter's LLM scope discipline.
- *"An override rate under 5 percent suggests either the recommender is exquisitely tuned (rare) or the clinicians aren't bothering to override and the briefings are being ignored (common)."* The under-5-percent-is-suspicious framing is non-obvious operational signal-routing.
- *"a beautiful optimization for an intermediate metric"* and *"non-adherent" is what the dashboard called Maria* (from 4.5) compose into a cross-recipe theme that this recipe extends correctly: *"A program that hill-climbs against closure rates for two years without ever validating against outcomes has built a beautiful optimization for an intermediate metric."* Same shape, sharpened for care gaps.
- The closing paragraph: *"The dashboard is the dashboard. The patient is the patient. They are not the same thing."* Distills the recipe's central tension into three short sentences. Don't trim it.
- Em dash check: 0 (verified via Unicode-explicit byte read). Pass.
- En dash check: 0 (verified via Unicode-explicit byte read). Pass.
- 70/30 vendor balance: The Problem, The Technology, and General Architecture Pattern stay vendor-neutral. AWS service names appear only in The AWS Implementation. Clean.
- Marketing-language scan: scanned for "leverage," "seamlessly," "robust," "cutting-edge," "state-of-the-art," "industry-leading," "empower," "unleash," "game-changing," "paradigm," "holistic," "synergy," "best-in-class." One borderline hit: *"high-leverage"* in Variations and Extensions ("pushing it from hours to minutes is high-leverage"). This is the colloquial "leverage point" sense rather than the corporate-marketing "leverage AWS services" sense; it reads voiceful in context. Acceptable as written.

### Finding V1: "Care Gaps Are Not the Same as Care Needs" Closing Paragraph Is the Strongest Single Paragraph in the Chapter So Far

- **Severity:** N/A (call-out)
- **Expert:** Voice
- **Location:** Honest Take, final paragraph.
- **Problem:** Not a finding. Worth flagging to the editor: this paragraph is the recipe's most distinctively-voiced moment. The "care gaps are not the same as care needs" framing, the inventory of what the recommender's narrow scope does and doesn't see ("a recently-onset symptom that hasn't been worked up; a deteriorating clinical trajectory that hasn't crossed any threshold; a social problem that no measure tracks"), the explicit "the PCP sees the whole patient. The recommender helps with one slice of the visit's preventive-and-quality work. Don't let the dashboard stand in for the clinician's judgment, and don't let the empty dashboard reassure you that everything is fine," and the closing "The dashboard is the dashboard. The patient is the patient. They are not the same thing" are exactly the editorial stance the chapter rewards.
- **Fix:** None. Note for the editor: keep verbatim.

### Finding V2: Variations and Extensions "High-Leverage" Phrasing Is Borderline; Defensible as Colloquial Use

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Variations and Extensions, *Real-time gap-closure suppression triggers* paragraph: *"pushing it from hours to minutes is high-leverage."*
- **Problem:** Not a fix request. The phrase reads as the colloquial "this is a leverage point" sense rather than the corporate-marketing "leverage AWS services" verb. In context with the surrounding voice (*"Patients who got the flu shot at the pharmacy on Saturday should not receive a Monday morning robocall"*), the phrase lands voicefully. If the editor's pass tightens marketing-adjacent terminology generally, this is the candidate; otherwise it stays as-is.
- **Fix:** Optional. If changed: *"pushing it from hours to minutes is the highest-impact change you can make"* preserves the meaning without the "leverage" word at all.

### Finding V3: Mermaid Architecture Diagram Has Many Nodes; Consider Pruning for Readability

- **Severity:** LOW
- **Expert:** Voice
- **Location:** "The AWS Implementation / Architecture Diagram" Mermaid block.
- **Problem:** Not a fix request. The Mermaid diagram has roughly 30 named nodes connected by approximately 40 edges, plus the ASCII art diagram in General Architecture Pattern (which is also dense). Both diagrams are accurate; both are at the upper end of "complex but legible." Readers consuming this in a typical Markdown renderer (GitHub, GitBook) will see the diagram render correctly but visually busy. The editor may want to consider:
  1. Splitting the Mermaid diagram into two: a "primary daily pipeline" diagram and a "real-time visit-context plus closure-tracking" diagram.
  2. Or adding a one-paragraph reading guide before the Mermaid that names the four main flows (gap evaluation, gap enrichment, visit-context ranking, closure tracking) so the reader has anchor points.
- **Fix:** Optional. The current diagram is correct and readable; the suggestion is purely cosmetic.


---

## Stage 2: Expert Discussion

**Overlap: Architecture A1 (optimistic counter no reconciliation) and Architecture A5 (counters not windowed).** Same underlying pattern as 4.4 and 4.5: counters increment without delivery-failure reconciliation AND without rolling-window decay. Either gap alone produces the asymmetric-silencing failure mode; both gaps together compound it. In 4.6 the cross-recipe global-counter framing makes both gaps four times worse: a phantom or unwindowed contact in any recipe silences the patient in every recipe. Resolution: pick one rolling-window pattern (DynamoDB TTL on per-event rows, daily-bucket aggregation, or scheduled decay Lambda) AND specify the reconciliation path on delivery failure AND coordinate with the chapter-wide cross-recipe contact-cap reconciliation TODO. All three are necessary; any one alone leaves the asymmetry in place.

**Overlap: Architecture A2 (`data_quality_flag` not gating) and Security S1 (override identity check) and Architecture A10 (out-of-order event handling).** Three findings touch the question of "what does the system do when an input signal is unreliable." The data-quality flag is unreliable-signal-from-source-data; the missing identity check on overrides is unverified-signal-attribution; the out-of-order event handling is unreliable-event-ordering. Resolution: in all three cases, the pseudocode should show defensive validation explicitly (downweight, defer, drop, or replay) rather than letting the unreliable signal flow through to a confident decision. The architectural pattern is the same; the implementations are different.

**Overlap: Architecture A3 (CDC measure name retired) and Architecture A9 (clinical loose framing in vignette).** Both touch clinical/measure accuracy. The first is a HEDIS-naming fix in the prose; the second is multiple clinical-claim cleanups in the David vignette. Both are correctable in a single 30-minute clinical-informatics review pass. The Code Review's Finding 1 already names the demo runner's measure-naming consequence; the recipe-text fix and Python-companion fix should land together.

**Overlap: Security S3 (four validators unspecified) and Architecture A7 (candidate-gap validator).** Same pattern as 4.5: validators named without specification. In 4.6 there are four validators where 4.5 had three (`validate_barrier_review`, `validate_reminder`, `validate_pharmacist_brief`). The chapter editor should consolidate the validator-pattern guidance into a chapter-4 preface that all recipes reference, with per-recipe specializations only where genuinely different.

**Overlap: Architecture A6 (no chained-closure state machine) and the recipe's own "Specialist-coordination workflows" Variation.** The Variations section names specialist-coordination workflows as a thing the architecture should support; the architecture proper doesn't show the chain primitive. Resolution: add the chain primitive (chain_id, chain_position, chain_total, predecessor_recommendation_id) to the recommendation-log schema; show the intermediate-event handler in Step 5; reference Recipe 14.x for the full multi-stage stochastic-program version.

**Overlap: Architecture A8 (model promotion path) and Architecture A11 (year-end policy overrides).** Both touch the question of how production-policy changes flow through governance. The model-promotion path is an artifact-deployment process; the seasonal policy override is a configuration-deployment process. Both should go through the same governance (cross-functional review committee), the same approval mechanism (a versioned config change with a documented rationale), and the same auditability (CloudTrail + change log + automated activation/deactivation). Resolution: a single paragraph in the architecture pattern naming the unified governance flow for both kinds of change.

**Cross-recipe overlap: chapter-wide hardening patterns.** Tracking-ID privacy (S2 here, 4.4 Finding 2, 4.5 Finding S2), validator specification (S3 / A7 here, 4.4 Finding 3, 4.5 Finding S3 / A6), SDOH cohort PHI promotion (S4 here, 4.4 Finding 6, 4.5 Finding S4), IAM ARN scoping (S5 here, 4.4 Finding 5, 4.5 Finding S5), `0.0.0.0/0` egress (N1 here, 4.4 Finding 15, 4.5 Finding N1), counter windowing (A5 here, 4.4 Code Review NOTE 9, 4.5 Finding A5), counter reconciliation (A1 here, 4.4 Finding 9, 4.5 Finding A1), cohort-feature dedup (A4 here, 4.4 Finding 13, 4.5 Finding A4), `data_quality_flag` not gating (A2 here, 4.5 Finding A2), model-promotion path (A8 here, 4.4 / 4.5). Ten chapter-wide patterns repeating. The chapter editor should consolidate these into a chapter-4 preface or shared "Chapter 4 production-hardening" section that all recipes reference; each per-recipe review is currently re-litigating the same gaps without resolution propagating across recipes.

Positive cross-recipe progress: the `patient-gaps` table's "highly inferential PHI" framing is the sharpest in the chapter (acknowledging that mental-health-follow-up gap status is more sensitive than flu-shot-gap status). The visit-context ranker's structured-input/structured-output briefing pattern is the cleanest LLM scope discipline in the chapter. The closure-tracker's multi-source canonical-source-rule pattern is novel architectural content that's not in 4.4 or 4.5. The Honest Take's David scenario synthesizes the chapter's clinical-vs-operational tension better than 4.4 or 4.5.

**No major conflicts among experts.** Security and Architecture both want stronger constraints on signal-quality and downstream gating (data-quality flag gating, validator specification, identity boundary checks, out-of-order event handling, chained-closure state machine), and these align. Networking is about endpoint topology and credentials. Voice is cosmetic. Priority alignment is clean.

**Priority alignment.** Three HIGH findings (A1 contact-counter reconciliation, A2 data_quality_flag not gating, A3 CDC measure name retired) are the must-fix-before-publication items. Eight MEDIUM findings are production-hardening that the editor or the next pipeline pass should address. The six LOW findings are cosmetic, edge-case, or chapter-pattern items.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

Zero CRITICAL findings. Three HIGH findings, at the > 3 = FAIL threshold (3 is not more than 3). PASS by a narrow margin.

The three HIGH findings are correctness gaps with localized fixes:

- **Finding A1 (contact-counter reconciliation)** is acknowledged via TechWriter TODO that mirrors the 4.4 / 4.5 fix language. The pseudocode does not yet implement the reconciliation. The cross-recipe global-counter framing makes the fix more important here than in either prior recipe. Fix is local to Step 5's `process_closure_event` (add the `closure_outreach_failed` / `closure_outreach_bounced` clause) plus a stale-pending sweep Lambda, plus a reconciliation invariant test that runs nightly.
- **Finding A2 (`data_quality_flag` not gating)** is the recipe-internal inconsistency: the prose names the gate as necessary in two places, the pseudocode never gates. Fix is local to Steps 2, 3, 4, 5, and 6: dampen urgency confidence on non-`complete` cases, suppress low-quality gaps from in-visit agendas, route low-quality cases to verification-first pathways, tighten canonical-source rules for fragmented data, and open chase-team briefs with verification when data quality is in doubt.
- **Finding A3 (HEDIS CDC measure name retired)** is a clinical-accuracy issue with two coordinated text changes (Technology section and Expected Results sample) plus a Python-companion follow-up. The fix is mechanical once clinical informatics confirms the current EED / GSD / KED / BPD naming.

The teaching arc (the David vignette, the three sources of gaps with deduplication and reconciliation, the per-(patient, gap) clinical urgency model independent of quality-measure status, the visit-context ranking with hard caps on agenda size and time cost, the multi-source closure tracking with canonical-source-per-measure rules, the override-rate-distribution analysis, the year-end-push-as-seasonal-exception framing) is solid and publishable. The HIGH findings should be addressed in the main text before the editor finalizes; the chapter-wide hardening MEDIUM and LOW findings are best resolved at chapter level rather than re-litigated per recipe.

The recipe's security and architectural posture continues the chapter-wide trajectory: prior reviewers' chapter-pattern gaps are increasingly resolved in main text (HealthLake VPC endpoint, EHR FHIR feed private connectivity, sharper PHI framing for high-sensitivity measures, clinician-briefings table named as PHI), and the remaining gaps are explicit TODOs rather than silent omissions. The Honest Take is the strongest in Chapter 4 so far, the David vignette is the strongest opening in Chapter 4 so far, and the closing "The dashboard is the dashboard. The patient is the patient. They are not the same thing." is the editorial stance the chapter rewards.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| A1 | HIGH | Architecture | Step 4 / Step 5 pseudocode | Optimistic contact-counter increment with no reconciliation path; counter is now cross-recipe global (worse than 4.4/4.5); TODO acknowledges but pseudocode doesn't implement |
| A2 | HIGH | Architecture | Steps 1, 2, 3, 4, 5, 6 / "Where it struggles" | `data_quality_flag` is computed and propagated but never gates urgency scoring, visit ranking, async orchestration, closure tracking, or chase-brief generation |
| A3 | HIGH | Architecture | The Technology / Expected Results / Code Review coordination | HEDIS Comprehensive Diabetes Care (CDC) measure name retired by NCQA; recipe uses outdated "hedis-cdc-eye-exam" naming; current measures are EED, GSD, KED, BPD |
| S1 | MEDIUM | Security | Step 6 pseudocode | `process_clinician_override` has no `event.patient_id != rec.patient_id` identity check (regression from 4.4/4.5 chapter pattern); audit trail and suppression both at risk |
| S2 | MEDIUM | Security | Sample tracking_ids; production-gaps TODO | Tracking ID and briefing ID embed patient_id, measure_id, pathway, provider_id in plain text (chapter-wide; sharper here for high-sensitivity measures) |
| S3 | MEDIUM | Security | Steps 1, 3, 4 pseudocode / production-gaps | Four validators (`validate_candidate_gaps`, `validate_briefing`, `validate_clinical_message`, `validate_chase_brief`) named but not all specified; per-state regulatory variation |
| A4 | MEDIUM | Architecture | Step 2 pseudocode | Cohort-feature lookup repeats per (patient, gap) instead of per patient (chapter-wide pattern from 4.4 / 4.5) |
| A5 | MEDIUM | Architecture | Step 4 / Step 5 pseudocode | `outreach_recent_total_30d_count` cross-recipe global counter has no decay or windowing mechanism (chapter-wide pattern from 4.4 / 4.5) |
| A6 | MEDIUM | Architecture | Variations vs. core architecture | No chained-closure state machine (referral → schedule → attend → result-return); architectural primitives (chain_id, predecessor_recommendation_id) missing |
| A7 | MEDIUM | Architecture | Step 1 pseudocode | `validate_candidate_gaps` named with partial TODO; specify alongside 4.5's `validate_barrier_review` for shared four-layer template |
| A8 | MEDIUM | Architecture | Architecture diagram / production-gaps | SageMaker model-promotion path not specified (trigger, canary, registry, rollback, cohort-calibration gate) |
| A9 | MEDIUM | Architecture | David vignette in The Problem | Pneumococcal "newly indicated at 64" loose (PPSV23 indicated for diabetics 19-64); colon-cancer family-history "elevated risk" overstated; "six years overdue" math inconsistent |
| A10 | MEDIUM | Architecture | Step 5 pseudocode | Closure-tracker state machine has no defense against out-of-order event arrival, retroactive corrections, or late-arriving exclusions |
| A11 | MEDIUM | Architecture | Production-gaps year-end paragraph | `chase_period_weight_overrides` mentioned but not architected; equity-floor expansion during chase periods not shown |
| S4 | LOW | Security | Production-gaps TODO | SDOH cohort PHI sensitivity in TODO; promote into main Privacy paragraph (chapter-wide pattern) |
| S5 | LOW | Security | Prerequisites IAM row | "Never *" stated but scoped ARN examples not shown (chapter-wide pattern) |
| N1 | LOW | Networking | Prerequisites VPC row | `0.0.0.0/0` egress disallow not stated explicitly (chapter-wide pattern) |
| N2 | LOW | Networking | Closure tracker / immunization registry | State immunization-registry credential posture not specified (per-state OAuth, VPN, SFTP variations) |
| N3 | LOW | Networking | HealthLake paragraph | FHIR API encryption / mTLS posture not specified for HealthLake or direct FHIR-to-S3 patterns |
| V1 | N/A | Voice | Honest Take closing paragraph | Not a finding; note for editor: best paragraph in the chapter so far, do not trim |
| V2 | LOW | Voice | Variations and Extensions | "High-leverage" phrasing borderline; defensible as colloquial; optional editor tightening |
| V3 | LOW | Voice | Architecture diagram | Mermaid diagram visually busy at ~30 nodes; optional split or reading-guide paragraph |

---

## Recommended Actions (Priority Order)

1. **Implement the contact-frequency reconciliation path with cross-recipe scope** (Finding A1): add `closure_outreach_failed` / `closure_outreach_bounced` / `closure_outreach_undeliverable` clause to Step 5 with `ConditionExpression` guarding against under-zero; add stale-pending sweep Lambda for tracking_ids with no engagement-stream activity within 24 hours; add a nightly reconciliation invariant test (global counter equals sum of recipe-specific counters within tolerance). Coordinate with the parallel 4.4 and 4.5 fixes; the chapter editor should land all three together with a chapter-4 preface that names the cross-recipe contract.

2. **Add `data_quality_flag` gating throughout the pipeline** (Finding A2): dampen urgency confidence on non-`complete` cases (Step 2); suppress low-quality gaps from in-visit agendas (Step 3); route low-quality cases to a verification-first pathway in async orchestration (Step 4); tighten canonical-source rules for fragmented data in the closure tracker (Step 5); open chase-team briefs with verification framing when data quality is in doubt (Step 4 chase brief). Add a paragraph to the architecture pattern naming the gate explicitly. The recipe's own prose says the gate is needed; the pseudocode should show it.

3. **Fix the HEDIS measure naming** (Finding A3): replace "HEDIS Comprehensive Diabetes Care eye exam" with "HEDIS Eye Exam for Patients with Diabetes (EED)" in The Technology section; add a parenthetical note about NCQA's CDC retirement and the EED/GSD/KED/BPD split; update the Expected Results sample's `measure_id` from `hedis-cdc-eye-exam` to `hedis-eed`; coordinate with the Python companion's synthetic registry. Address the diabetic foot exam framing (no current HEDIS or Star measure tracks it; clinical urgency framing remains valid via ADA Standards of Care). 30-minute clinical-informatics review pass on the entire David vignette including the pneumococcal-vaccine-at-64 and colon-cancer-family-history claims (Finding A9 covers these).

4. **Add the patient-identity boundary check on the override path** (Finding S1): immediately after `lookup_recommendation_by_briefing_id`, validate `event.patient_id == rec.patient_id` and `event.measure_id == rec.measure_id`; mismatches log and drop with a metric. Add an analogous defensive check on the closure-event path (validate that the event's `patient_id` exists in the patient-profile store before any state machine mutation).

5. **Replace string-concatenation tracking_id and briefing_id with opaque identifiers** (Finding S2): UUID or HMAC; identifier-to-patient mapping lives in the recommendation log only. Update Expected Results samples accordingly. Resolve the existing TODO. For high-sensitivity measure types (mental health, substance use, HIV-related, reproductive health), the opaque-identifier requirement is non-negotiable.

6. **Specify all four LLM-output validators** (Finding S3 plus Finding A7): four-layer validator template (schema, required disclosures, prohibited content, required references); per-validator specialization (briefing must trace to deterministic agenda; candidate-gap rationale must cite observable data; patient message must not make unapproved clinical claims; chase brief must use verification opening when data quality is uncertain). Specify failure-handling per validator (drop / replace-with-template / defer-with-reason / route-to-manual-queue).

7. **Architect the chained-closure state machine** (Finding A6): add `chain_id`, `chain_position`, `chain_total`, `predecessor_recommendation_id` to the recommendation-log schema; add an intermediate-event handler in Step 5 that advances chain_position on `referral_scheduled` / `referral_attended` events; reference Recipe 14.x for the full multi-stage stochastic-program version. Build together with Finding A7 if the candidate-gap surfacer's review queue is itself chain-aware (a candidate becomes a measure registry entry, which becomes a gap, which becomes a recommendation, which becomes a closure).

8. **Make the closure-tracker state machine event-replay-based rather than mutation-based** (Finding A10): events are stored in a per-(patient, gap) event log; current state is computed by replay; corrections and out-of-order arrivals produce the same final state regardless of receipt order. The replay cost is small in practice; the correctness benefit handles the failure modes the prose names as concerns.

9. **Architect the seasonal policy overrides** (Finding A11): policy table supports base policy + zero or more seasonal override blocks; effective policy is the merged result; seasonal overrides go through the same governance review; equity floors expand during chase periods; cohort-equity dashboard cadence tightens during chase periods. Without this primitive, the year-end-push trap the Honest Take warns about reasserts itself by default.

10. **Specify the SageMaker model-promotion path** (Finding A8): trigger (EventBridge schedule + drift threshold), canary (parallel Batch Transform against frozen evaluation set), registry (SageMaker Model Registry with `pending_review` / `approved` states), rollback (alias-pointer change), cohort-calibration gate (hard fail on cohort-level calibration error). Reference Recipe 7.x for depth.

11. **Deduplicate cohort-feature lookups by patient** (Finding A4): hoist the cache out of the per-gap loop; build once per unique patient. Reference 4.4 Finding 13 and 4.5 Finding A4 as the chapter-wide pattern.

12. **Pick a rolling-window pattern for the cross-recipe global counter** (Finding A5): DynamoDB TTL on per-event rows (preferred, naturally cross-recipe), daily-bucket aggregation, or scheduled decay Lambda. Document as a chapter-wide convention; coordinate with the Finding A1 reconciliation.

13. **Fix the David vignette clinical claims** (Finding A9): pneumococcal vaccine framing (PPSV23 indicated for diabetics 19-64 for years; David's gap is decade-old, not month-old); colon cancer family history framing (paternal CRC at 71 doesn't trigger elevated-risk surveillance; either strengthen the family history or drop the elevated-risk framing); fix the "six years overdue" math in the Honest Take to be consistent with the vignette's setup.

14. **Promote SDOH cohort PHI paragraph from TODO into main Privacy paragraph** (Finding S4); chapter-wide pattern.

15. **Add scoped IAM ARN examples for highest-stakes actions** (Finding S5); chapter-wide pattern.

16. **Disallow `0.0.0.0/0` egress on Lambda subnets explicitly** (Finding N1); chapter-wide pattern.

17. **Specify state immunization-registry credential posture** (Finding N2): per-state OAuth, VPN, SFTP variations; Secrets Manager + KMS + per-state rotation; per-state access scopes enforced in the integration layer.

18. **Specify FHIR API encryption / mTLS posture for HealthLake and direct FHIR-to-S3 patterns** (Finding N3): TLS 1.2+ baseline; mTLS via ACM Private CA where required; PrivateLink or Direct Connect for on-premises EHRs.

19. **Optional voice polish** (Findings V2, V3); not blocking.

---

## Notes for Editor

- The recipe runs long (~18,500 words including the architecture diagram, code blocks, and Expected Results JSON). Length is earned: the David vignette, the six-stage logical breakdown, the three-sources-of-gaps subsection, the visit-context-ranking discussion, the multi-source closure-tracking discussion, the override-rate distribution analysis, and the closing "care gaps are not the same as care needs" paragraph are all pedagogically essential. Do not trim any of them.
- The recipe carries forward 4.4 / 4.5's chapter-wide hardening progress and adds care-gap-specific sharpenings: the `patient-gaps` table's "highly inferential PHI" framing, the high-sensitivity measure (mental health, substance use, HIV, reproductive health) tighter-controls discussion, the visit-context ranker's structured-input/structured-output briefing pattern, the multi-source closure-tracking with canonical-source-per-measure rules, the override-rate-distribution analysis, the year-end-push seasonality framing. The teaching density is high.
- Several `<!-- TODO -->` markers are present and appropriate: HEDIS / CMS Stars / ACO measure specification sources, Bedrock per-model HIPAA eligibility, SageMaker Batch Transform HIPAA eligibility, AWS HealthLake pricing and HIPAA eligibility, IAM ARN examples (chapter-wide), Cost Estimate validation, model-promotion path, contact-cap reconciliation paths, SDOH cohort PHI promotion, validator specification, cross-recipe orchestration, DLQ coverage, tracking-ID privacy, SES / Pinpoint HIPAA scope, NCQA / CMS / aws-samples URL verification. These are realistic verification tasks and not blockers.
- The Cost Estimate range ($2,500-$6,000/month for a 400K-member plan) is reasonable for the architecture described; the per-line items sum to roughly $2,180-$5,750 at low and high ends. Acceptable.
- The Related Recipes section forward-references future recipes (4.7, 7.x, 8.x, 12.x, 13.x, 14.x). Standard practice for the book.
- The Footer link to Recipe 4.7 (Care Management Program Enrollment) references a future recipe that doesn't exist yet. Standard placeholder.
- All external links are real: NCQA HEDIS landing page (with TODO to verify path; HEDIS-spec URLs change with measurement years), CMS Medicare Star Ratings Technical Notes (with TODO; CMS URLs have moved repeatedly), USPSTF, ADA Standards of Care, KDIGO, CDC immunization schedules, econml, Obermeyer 2019, Synthea, AWS docs (SageMaker, Bedrock, Step Functions, EventBridge Scheduler, HealthLake, SES, Pinpoint, Connect, QuickSight), AWS HIPAA Eligible Services list, Architecting for HIPAA whitepaper.
- The aws-samples repo references (`amazon-sagemaker-examples`, `amazon-sagemaker-feature-store-end-to-end-workshop`, `amazon-bedrock-workshop`) are appropriately hedged with TODOs. Same as 4.4 and 4.5. Appropriate.
- Cross-recipe coherence with 4.1, 4.2, 4.3, 4.4, 4.5 is strong: the patient-profile store, engagement-event bus, channel optimizer integration, contact-frequency cap, cohort dashboard infrastructure, Bedrock / DynamoDB / Kinesis primitives, and the structural progression from 4.4's wellness-program allocation through 4.5's adherence-intervention allocation to 4.6's gap-closure allocation are all visible. The "Where This Sits in the Chapter" framing is accurate and helps the chapter narrative.
- The Python code review (`reviews/chapter04.06-code-review.md`) returned PASS with three WARNINGs and six NOTEs. WARNING 1 (demo closure event targets out-of-denominator patient) intersects with this review's HIGH Finding A3 (HEDIS measure naming): both fixes coordinate around the synthetic registry. WARNING 2 (Scan + FilterExpression where Query would do) is a Python-specific code-quality issue. WARNING 3 (`in_visit` pathway silently dispatched as no-op) is a fall-through-pathway gap that mirrors the spirit of this review's Finding A2 (low-data-quality cases need an explicit fall-through). Both reviews together name a coordinated set of fixes.
- Voice and 70/30 vendor balance: clean. Em dash count: 0 (verified via UTF-8 byte-level read). En dash count: 0 (verified). Recipe is publishable on voice grounds without any additional fixes.
- The closing "The dashboard is the dashboard. The patient is the patient. They are not the same thing." sentence is the strongest single line in the recipe (Finding V1). The editor should preserve it verbatim.

---

*Review complete. Findings prioritized; PASS verdict with three HIGH findings at (not over) the > 3 = FAIL threshold. The three HIGH findings are correctness gaps with localized fixes that should be closed in the main recipe text before final editing; chapter-wide hardening progress (HealthLake VPC endpoint, EHR FHIR private connectivity, sharper inferential-PHI framing for high-sensitivity measures, clinician-briefings PHI handling) continues to mature from prior recipes' TODOs into this recipe's main text.*
