# Expert Review: Recipe 4.5 - Medication Adherence Intervention Targeting

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-16
**Recipe file:** `chapter04.05-medication-adherence-intervention-targeting.md`

---

## Overall Assessment

This recipe takes the uplift-and-allocation scaffolding from Recipe 4.4 and applies it to medication adherence, which is the harder problem class for two specific reasons the recipe correctly identifies up front: the catalog of interventions is heterogeneous (a text reminder and a clinical pharmacist consult are not interchangeable; they cost cents versus tens of dollars and address fundamentally different barriers), and the underlying signal (PDC computed from pharmacy claims) is messier than the wellness-program eligibility data because of fill cadence carry-forward, mail-order versus retail timing, therapeutic substitution, and cash-pay invisibility. The Maria-with-three-barriers opening is one of the strongest vignettes in Chapter 4 so far, and the central diagnostic claim ("the data tells you the *what*; the hard work is identifying the *why*") earns the recipe's length.

The core teaching is solid: PDC done correctly with carry-forward and lag-aware computation, a six-category barrier taxonomy with rule-based plus supervised plus LLM-second-opinion staging, heterogeneous-intervention scoring with explicit need / barrier-fit / engagement / uplift components, capacity-aware allocation with multi-intervention-per-patient and equity floors, and a multi-horizon feedback architecture that distinguishes engagement signals from adherence change from clinical outcomes. Several of the chapter-wide hardening patterns from earlier reviews have continued to mature into the main text rather than being relegated to "Why This Isn't Production-Ready":

- The recommendation log and barrier-classifications table are explicitly named as PHI ("highly inferential PHI"), with customer-managed KMS, CloudTrail data events, narrow IAM read scopes, and a defined retention period (90 to 180 days for individually-attributed; longer only after de-identification).
- Engagement event integrity check is enforced: `process_adherence_event` validates `event.patient_id != rec.patient_id` and drops mismatches.
- Bedrock data-retention posture is stated explicitly with a TODO to verify per-model coverage.
- VPC endpoint list is comprehensive and has correctly added Glue, Athena, Firehose, SageMaker Runtime, Step Functions, EventBridge, STS, SES, and Pinpoint that earlier recipes were missing.
- The TODO markers in the Why This Isn't Production-Ready section explicitly enumerate DLQ coverage across Step Functions, Kinesis attribution, and Batch Transform job failures.
- The SDOH-cohort PHI sensitivity guidance is present (as a TODO).
- The cost-effectiveness term in the priority math is documented and explained ("stops a $0.05 reminder from being crowded out by a $80 pharmacist consult on every candidate") with a clear policy-versioning expectation.
- The Star Ratings cut-point distortion ethical trap gets explicit treatment in The Honest Take rather than being elided.
- The contact-cap reconciliation gap is acknowledged in a `<!-- TODO -->` marker with the right level of specificity, naming the asymmetric-silencing failure mode.

That said, several gaps need attention before publication. Most are correctness and operational items at the production-design level, not fundamental design flaws.

The two HIGH findings are correctness gaps the editor should resolve in main-text rather than punting:

1. **Step 6 allocator's equity-floor accounting is incomplete and the second-pass top-up is described but not implemented in pseudocode.** The pseudocode increments `equity_remaining[intervention_id][floor_cohort]` only when a candidate that matches the floor is allocated through the primary greedy walk. The "second pass to fill any unfilled equity floors" calls a `top_up_from_cohort(...)` helper without specifying its semantics. A reader implementing this literally will either skip the second pass (floors stay unfilled) or implement it inconsistently with the primary pass (floors fill but with candidates that don't respect the per-patient caps). The 4.4 review's Finding 9 (optimistic counter no reconciliation) and 4.4 architecture finding on greedy-allocator path-dependence both apply structurally here as well, but the specific incompleteness is the unspecified `top_up_from_cohort` semantics.

2. **The Step 7 contact-cap reconciliation gap is acknowledged in a TODO but the reconciliation is not implemented in pseudocode.** The TODO comment names the right failure mode ("members with flaky channels accumulate phantom contact-cap consumption and get systematically excluded from future allocations they should still be eligible for") and is the same pattern flagged in 4.4. Since the gap is explicit in a TODO marker, this could arguably be MEDIUM, but the asymmetric-cohort silencing impact is structural and the recipe's equity story (equity floors, cohort dashboards, fairness instrumentation) is undermined by leaving the reconciliation unimplemented. The recipe also specifies a parallel governance gap (DLQ coverage, idempotency keys, Star Ratings governance, global contact cap, SDOH PHI promotion, validator pseudocode, training trigger / model promotion) all as TODO markers without resolution. That cluster of unresolved TODOs at the end of "Why This Isn't Production-Ready" is fine individually but cumulatively suggests the section has become a holding pen for unresolved chapter-wide patterns. The editor should consolidate into main text where the patterns are mature (DLQ coverage, idempotency keys, Star Ratings governance) and leave the genuinely-research items (validator approved-claims list mechanism, pharmacist-elicited barrier dataset standards) as TODOs.

Several MEDIUM findings round out the production-hardening pattern: cohort-cycle calendar awareness is mentioned but not architected, the Star Ratings 75-79 cohort policy weight is named as an ethical trap but no architectural floor is specified for the high-need / low-PDC cohort, the PCP override path has no pre-send hold-time semantics for higher-stakes medications (anticoagulants, antiretrovirals, chemotherapy compliance), the cost-assistance cascade is named as a Variations item but should be in the main intervention-catalog discussion because it's actually how cost-assistance works in practice, and the global cross-recipe contact cap is described as a TODO rather than as an architectural pattern with a shared counter design.

A handful of LOW findings round out the review: the IAM-ARN-scoping pattern repeats from 4.1 / 4.2 / 4.3 / 4.4, the tracking-ID PHI-leakage pattern repeats from 4.4 (acknowledged in the TODO but the Expected Results sample still uses the readable form), the Athena and Glue VPC endpoints should be checked for Pinpoint, Connect, and SageMaker Feature Store online store endpoints, the cross-recipe contact-cap counter naming is inconsistent (`outreach_recent_30d_count` here versus `outreach_recent_wellness_count` in 4.4 with no shared counter pattern), and the cohort-feature lookup-deduplication pattern from 4.4 isn't applied here either.

Voice and 70/30 vendor balance: clean. Em dash count: 0. En dash count: 0 (verified at the byte level). The Honest Take's closing point ("medication non-adherence is often *rational* from the patient's perspective. ...These patients are not failing. They are coping. The right response to non-adherence is rarely 'remind harder.' It's 'find out what's going on, and address that.'") is the strongest paragraph in the chapter so far and worth flagging to the editor as the kind of contrarian-but-correct stance the chapter has been collecting.

Priority breakdown: 0 critical, 2 high, 8 medium, 6 low.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA called out explicitly with HIPAA-eligibility TODOs for SageMaker Batch Transform, SageMaker Feature Store, Bedrock per-model, SES, and Pinpoint. The recipe doesn't pretend any of these are static.
- Customer-managed KMS keys for every PHI-containing store: DynamoDB tables (patient-profile, intervention-catalog, recommendation-log, barrier-classifications, engagement-events, pcp-overrides), S3 buckets (especially the pharmacy-claims bucket with explicit "raw fill data is highly sensitive" language), Kinesis and Firehose (server-side encryption), SageMaker training and inference (VPC-only, KMS keys for model artifacts and Feature Store offline storage), Lambda log groups KMS-encrypted.
- Recommendation log and barrier-classifications explicitly named as PHI: *"The recommendation log contains (patient_id, intervention_id, medication_class, barrier) tuples that are highly inferential; treat as PHI from day one."* The barrier-classifications table is called out separately: *"A row indicating 'patient has a cost barrier on diabetes medication' is sensitive in ways that go beyond clinical PHI: it implies socioeconomic distress."* This is the chapter-wide PHI-as-inference pattern correctly scaled up for the adherence domain.
- Retention policy stated: *"defined retention (90 to 180 days for individually-attributed records; longer retention only after de-identification), and explicit deletion jobs with alarming."*
- CloudTrail data events on patient-profile, intervention-catalog, recommendation-log, barrier-classifications, and engagement-events tables; data events on the S3 buckets containing pharmacy claims, per-patient feature snapshots, and recommendation outputs.
- The Bedrock paragraph explicitly says: *"Confirm in service terms that prompts and completions are not used to train the underlying foundation models."* Continues the chapter pattern.
- LLM prompt construction pseudocode in Step 7 explicitly excludes raw identifiers: *"Identifiers are stripped before LLM calls; PHI is re-attached after."*
- The Honest Take flags the inferential-PHI risk of the barrier-classifications table beyond the recommendation log: *"It implies socioeconomic distress."* This is a more sophisticated read than the prior recipes have offered.
- The pharmacy claims data ingestion path explicitly notes that PBM feeds typically arrive over Direct Connect or PrivateLink rather than the public internet, which is the right architectural posture for raw fill data.

### Finding 1: Outreach-Message Validator and Pharmacist-Brief Validator Mentioned but Not Specified

- **Severity:** MEDIUM
- **Expert:** Security (regulatory)
- **Location:** Step 7 pseudocode, the `validate_reminder(tailored, intervention)` and `validate_pharmacist_brief(brief)` calls; "Why This Isn't Production-Ready," the *Outreach-message governance for adherence content* paragraph and the validator-shape TODO marker.
- **Problem:** The recipe references three distinct validators in Step 7 (`validate_reminder`, `validate_pharmacist_brief`, and implicitly the PCP-briefing validator) without specifying any of them, and the production-gaps section has a TODO that names the four-layer validator shape (schema, required disclosures, prohibited claims, approved-claims-only) without writing it as pseudocode. The same gap was flagged in the 4.4 review (Finding 3) and acknowledged here, but the 4.5-specific reality is more constrained:

  1. **Adherence reminders are a regulated communication category.** State boards of pharmacy have varying rules about who can send reminders for what medications, and what disclosures are required. The recipe correctly says so but doesn't specify the validator that enforces it.
  2. **Manufacturer-funded reminder programs raise anti-kickback considerations.** A reminder for a specific brand drug paid for by the manufacturer is a different regulatory animal than a reminder for a generic statin paid for by the plan. The validator should know which interventions are manufacturer-funded (the catalog can carry a `funding_source` attribute) and apply the appropriate disclosures and prohibited-claims rules.
  3. **The pharmacist-brief validator is a different problem from the reminder validator.** The reminder is patient-facing and externally-regulated; the pharmacist brief is staff-facing and primarily a clinical-accuracy concern (no fabricated clinical context, no contraindications missed). Conflating the two will leave both under-specified.

- **Fix:** Two changes.

  1. Specify the validator pseudocode shape for the reminder validator (matching the 4.4 review's Finding 3 fix):

     ```
     FUNCTION validate_reminder(tailored, intervention):
         IF NOT matches_schema(tailored, REMINDER_SCHEMA):
             RETURN ValidationResult(passed=false, reason="schema_violation")
         IF len(tailored.body) > MAX_BODY_LENGTH:
             RETURN ValidationResult(passed=false, reason="body_too_long")

         FOR each required_disclosure in intervention.required_disclosures:
             IF required_disclosure NOT IN tailored.body AND
                required_disclosure NOT IN tailored.call_to_action:
                 RETURN ValidationResult(passed=false, reason="missing_disclosure",
                                          detail=required_disclosure)

         IF intervention.funding_source == "manufacturer":
             // Manufacturer-funded reminders require additional disclosures and
             // are bound by the manufacturer's approved-claims artifact, not
             // the plan's general approved-claims list.
             IF NOT tailored.contains_manufacturer_disclosure:
                 RETURN ValidationResult(passed=false, reason="manufacturer_disclosure_missing")
             approved_claims = intervention.manufacturer_approved_claims
         ELSE:
             approved_claims = intervention.approved_claims

         FOR each clinical_claim in extract_clinical_claims(tailored):
             IF clinical_claim NOT IN approved_claims:
                 RETURN ValidationResult(passed=false, reason="unapproved_clinical_claim",
                                          detail=clinical_claim)

         FOR each prohibited_pattern in PROHIBITED_CLAIMS_LIST:
             IF prohibited_pattern matches tailored.body:
                 RETURN ValidationResult(passed=false, reason="prohibited_claim",
                                          detail=prohibited_pattern.label)

         RETURN ValidationResult(passed=true)
     ```

  2. Specify a separate `validate_pharmacist_brief` shape with different concerns (no fabricated clinical context, contraindications listed are genuine, suggested talking points reference observed data, no instructions to do something the pharmacist isn't licensed to do without prescriber involvement). The pharmacist-brief validator is staff-facing, so the regulatory exposure is lower, but the clinical-accuracy stakes are higher because the pharmacist will be reading and acting on it during a real call.

  3. Specify the failure-handling: schema and length failures fall back to `intervention.default_template`; clinical-claim or prohibited-claims failures defer the outreach with reason `validator_failed:<reason>` and flag for human review. The pharmacist brief on validator-fail does not fall back to a default template (the brief is the staff's pre-call work; falling back to a generic brief would defeat the purpose); instead it should flag for clinical-pharmacist-lead review and fall back to the structured medication-history view that the pharmacist would have seen anyway.

  Add a sentence: *"Manufacturer-funded reminder interventions carry a `funding_source: 'manufacturer'` field on the catalog record and bind to the manufacturer's approved-claims artifact, not the plan's general list. The plan's compliance counsel reviews each manufacturer-funded campaign and signs off on the approved-claims artifact before launch."*

### Finding 2: Tracking ID Embeds Patient ID and Therapeutic Class in Plain Text Across the Pipeline

- **Severity:** MEDIUM
- **Expert:** Security (PHI minimization)
- **Location:** Step 7 pseudocode, multiple `tracking_id = build_tracking_id(row, run_date)` calls; "Expected Results" sample showing `"tracking_id": "adherence-2026-05-04-pat-000482-statins-cost-assist-001"` and `"adherence-2026-05-04-pat-000915-ras-reminder-002"`; the TODO at the bottom of "Why This Isn't Production-Ready" *"Replace the string-concatenation tracking_id with an opaque, non-reversible identifier..."*.
- **Problem:** Same pattern as 4.4 Finding 2. The recipe acknowledges the gap in a TODO marker, but the Expected Results samples and the orchestration pseudocode still show plain-text patient_id, therapeutic_class, and intervention_id concatenated into the tracking_id. The tracking_id then flows into:

  1. The Kinesis engagement-event stream (`adherence_intervention_recommended` event payload).
  2. The recommendation log in DynamoDB.
  3. The Bedrock InvokeModel request body indirectly via the orchestrator.
  4. Email open-tracking pixels and SMS click-through links rendered by the channel optimizer.
  5. Vendor outreach platforms if the orchestrator hands off to one.
  6. CloudWatch logs every time any Lambda logs the tracking_id at INFO level.

  The 4.5-specific concern that's worse than 4.4 is that the therapeutic_class is *more* sensitive than 4.4's program_id. A program_id like `dpp-001` reveals "this member is being targeted for a wellness program"; a tracking_id with `statins` or `ras` or `oral-diabetes` in plain text reveals the medication class the member is non-adherent to, which directly implies a chronic condition (cardiovascular disease, hypertension, diabetes). That's PHI in the strictest sense, not just inferential PHI.

  The TODO acknowledges the fix; the Expected Results samples should not be allowed to teach the wrong pattern.

- **Fix:** Two changes.

  1. Replace the Expected Results sample tracking_ids with opaque identifiers:

     ```json
     "tracking_id": "rec-7f3b2c8e-4a91-4d12-9ce4-1f8a3b5d2e7c"
     ```

  2. Promote the TODO into the main Step 7 pseudocode:

     ```
     // Use an opaque, non-reversible tracking_id. The (patient_id,
     // therapeutic_class, intervention_id) mapping is recovered only
     // from the recommendation-log via the tracking_id.
     tracking_id = secure_random_uuid()
     // OR: HMAC-SHA256 over (run_date, patient_id, therapeutic_class,
     // intervention_id) with a per-environment secret if you need
     // determinism for replay/idempotency.
     ```

  Add a sentence to the Privacy paragraph in "Why This Isn't Production-Ready": *"A tracking_id with therapeutic_class in plain text is more sensitive than a tracking_id with program_id in plain text. 'statins' implies cardiovascular disease; 'ras' implies hypertension; 'oral-diabetes' is unambiguous. Treat the tracking_id PHI exposure as one tier higher than the equivalent in the wellness recipe."*

### Finding 3: Wellness/Adherence Consent and Pharmacy-Specific State-Board-of-Pharmacy Rules Not Addressed

- **Severity:** MEDIUM
- **Expert:** Security (compliance accuracy)
- **Location:** No section currently addresses consent for adherence outreach. The closest is the "Equity Governance" row in Prerequisites, which addresses policy-weight governance but not patient-facing-outreach consent.
- **Problem:** Adherence outreach has its own consent regime that's distinct from wellness-program consent (4.4 Finding 1). Three frameworks unavoidable in production:

  1. **State boards of pharmacy.** Several states (Texas, California, New York, Florida among others) have specific rules about pharmacy-affiliated reminders and counseling. A health-plan-sponsored reminder is regulated differently from a pharmacy-sponsored reminder; a manufacturer-funded reminder is regulated more strictly than either. The state-by-state patchwork is the same kind of legal-engineering work as 4.4's ADA/GINA/state consent regime, but the regulators are different.
  2. **TCPA (Telephone Consumer Protection Act).** Adherence outreach via SMS or automated voice falls under TCPA's "express written consent" requirements unless the contact is treatment-related (a defined exception under HHS guidance). The recipe's intervention catalog includes "automated voice" reminders, which trigger TCPA whether or not the plan considers them treatment. Pinpoint and Connect deployments need their consent posture documented.
  3. **Cost-assistance programs and HIPAA's marketing rules.** When the plan facilitates a manufacturer copay-card application, the activity may be classified as "marketing" under 45 CFR 164.501 unless it qualifies as a treatment-related communication. If marketing, an authorization is required; if treatment-related, it isn't. This is a real legal-engineering question that affects the cost-assistance intervention type and the Bedrock-tailored copay-card outreach.

  The recipe currently treats all interventions as if consent and regulatory authority were uniform across types. They aren't.

- **Fix:** Add a "Consent and Regulatory Posture" subsection to "Why This Isn't Production-Ready" or to the eligibility-filter prose:

  *"Adherence outreach consent is multi-dimensional. State boards of pharmacy regulate pharmacy-affiliated reminders state-by-state, with rules that vary on disclosure requirements, frequency caps, and approved-claims content. TCPA governs SMS and automated-voice outreach unless the contact qualifies as treatment-related under HHS guidance, which is a fact-specific determination. HIPAA marketing rules at 45 CFR 164.501 may apply to manufacturer-funded interventions and to cost-assistance navigation if the plan's facilitation is classified as marketing. The intervention catalog should carry per-intervention consent metadata (treatment-related vs marketing, channel-specific TCPA scope, state-specific applicability), and the eligibility filter should consult the metadata before allowing the intervention to flow to the candidate set. Engage your privacy officer and pharmacy compliance lead on the consent model for each intervention type before launch; do not collapse to a single `outreach_consent` boolean."*

  Add a corresponding eligibility-filter pseudocode line in Step 3:

  ```
  IF NOT member_consent.applies_to(intervention.consent_classification, member.state):
      CONTINUE
  ```

### Finding 4: PCP Override Path Has No Pre-Send Hold-Time Semantics for High-Stakes Medications

- **Severity:** MEDIUM
- **Expert:** Security (clinical workflow safety)
- **Location:** Step 7 pseudocode, the orchestration paths; "Why This Isn't Production-Ready," no paragraph on PCP-review-policy.
- **Problem:** Same pattern as 4.4 Finding 4. The recipe describes PCP alerts as a parallel notification (the orchestrator queues the outreach via the channel optimizer, and *also* generates a PCP briefing for `regimen_simplification` interventions). For most adherence interventions this parallel-notification pattern is fine: a reminder for a statin is low-stakes, the PCP can endorse retroactively, and a member who got an irrelevant reminder ignores it.

  For higher-stakes medication classes the calculus is different:

  - **Anticoagulants.** A patient on warfarin or a DOAC who has a non-trivial reason for a missed dose (planned procedure, bleeding event, prescriber-mediated hold) should not get an automated reminder. A reminder during a planned anticoagulant hold can produce serious clinical harm if the patient resumes dosing thinking the system is correcting an oversight.
  - **Anti-rejection medications.** Transplant patients on tacrolimus or cyclosporine have therapeutic windows so narrow that adherence interventions touching them require a transplant-team-aware workflow, not a generic recommender.
  - **Oral chemotherapy and HIV antiretrovirals.** Both have specialized counseling requirements and prescriber-team workflows that supersede a population-health adherence pipeline.
  - **Insulin and other titrated medications.** A patient whose dose was recently reduced is "non-adherent" relative to the old dose but adherent to the new dose; the recommender's PDC computation may not have caught up. A reminder for the old dose is wrong.

  Production adherence systems differentiate medication classes by PCP-review-required vs PCP-notify-only. The recipe doesn't make this distinction; the intervention catalog has no `pcp_review_policy` field analogous to the `program.pcp_alert_enabled` flag from 4.4.

- **Fix:** Add a `pcp_review_policy` field to the intervention catalog:

  - `none`: no PCP notification (low-stakes interventions like a statin reminder).
  - `notify_parallel`: PCP gets a briefing at the same time as the patient outreach (current behavior, appropriate for moderate-stakes interventions).
  - `review_required_24h`: outreach is held for 24 hours; PCP can decline before send; default to send if no response.
  - `review_required_72h_specialist_team`: outreach is held until the specialist team (transplant, oncology, hematology) confirms; default to *not* send if no response.

  Add a `medication_class_review_policy` lookup that overrides the per-intervention default for specific therapeutic classes (anticoagulants, anti-rejection, oral chemo, antiretrovirals, insulin during dose-adjustment periods). The medication-class policy supersedes the per-intervention policy.

  Update the Step 7 orchestration to respect the policy:

  ```
  effective_policy = medication_class_review_policy.get(row.therapeutic_class,
                                                        intervention.pcp_review_policy)
  IF effective_policy == "review_required_24h":
      CareTeamInbox.PostNote(...)
      schedule_outreach_with_delay(row, 24_hours, conditional_on_no_pcp_decline)
  ELSE IF effective_policy == "review_required_72h_specialist_team":
      SpecialistTeamInbox.PostNote(...)
      schedule_outreach_with_delay(row, 72_hours, conditional_on_specialist_endorse)
  ELSE IF effective_policy == "notify_parallel":
      ChannelOptimizer.QueueOutreach(...)
      CareTeamInbox.PostNote(...)
  ELSE:
      ChannelOptimizer.QueueOutreach(...)
  ```

  Add a paragraph in "Why This Isn't Production-Ready" naming the high-stakes medication classes and recommending the specialist-team-aware workflow for them: *"Anticoagulants, anti-rejection medications, oral chemotherapy, antiretrovirals, and insulin during dose-adjustment all have specialized clinical workflows that the population-health adherence pipeline should defer to rather than override. The medication-class review policy is the architectural seam where deferral happens; the policy is owned by the medical director and reviewed quarterly."*

### Finding 5: SDOH-Cohort PHI Sensitivity Should Be Promoted From TODO Into Main Privacy Paragraph

- **Severity:** LOW
- **Expert:** Security
- **Location:** TODO at the bottom of "Why This Isn't Production-Ready": *"Add a paragraph on the SDOH-cohort PHI boundary in the cohort_features attribute..."*
- **Problem:** Same pattern as 4.4 Finding 6. Not a finding against the content; a finding against the placement. The SDOH-cohort PHI consideration is even more sensitive in the adherence domain than in 4.4 because the recommendation log here joins (patient, therapeutic_class, barrier) with cohort labels. A row indicating "patient with SDOH cohort=low_food_security has cost barrier on diabetes medication" is the kind of inference that, in a small geographic cohort, is reidentifying. Promote the TODO content into the main *Privacy in the recommendation log and barrier classifications* paragraph.
- **Fix:** Move the TODO content inline into the main Privacy paragraph. Add: *"Apply the minimum-necessary principle to cohort axes themselves. Only carry cohort attributes through to the engagement event that the equity dashboard actually consumes; a new cohort axis added 'because it might be useful someday' is a privacy expansion that should be reviewed."*

### Finding 6: IAM "Never `*`" Stated Without Scoped ARN Examples (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites, "IAM Permissions" row.
- **Problem:** Same finding as 4.1, 4.2, 4.3, 4.4. The TODO already in the recipe acknowledges the chapter-wide pattern. The fix is to either (a) put one or two scoped resource ARN examples inline, or (b) consolidate into a chapter preface section that all recipes reference.
- **Fix:** Pair each action with one example ARN. Examples: `sagemaker:CreateTransformJob` on `arn:aws:sagemaker:{region}:{account}:transform-job/adherence-*`; `dynamodb:GetItem` on `arn:aws:dynamodb:{region}:{account}:table/patient-profile`; `bedrock:InvokeModel` on `arn:aws:bedrock:{region}::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0`; `kinesis:PutRecord` on `arn:aws:kinesis:{region}:{account}:stream/engagement-stream`. A coordinated chapter-wide fix would be more durable.

---

## Architecture Expert Review

### What's Done Well

- The five-component pipeline (pharmacy-data ingestion, barrier classification, intervention-catalog ingestion, batch recommendation, feedback) is the right shape for the problem, and the explicit separation between continuous ingestion (pharmacy data) and batch recommendation (weekly with exception triggers) reflects production reality.
- PDC computation methodology is correct: carry-forward days-supply, therapeutic-class-level (not NDC-level) computation, lag-aware (settled vs. best-effort current), data-quality-flag attribute that gates downstream confidence. The `data_quality_flag` propagating through to the recommendation log is the right architectural choice.
- The barrier taxonomy (cost, forgetfulness, beliefs, side effects, complexity, access) is the canonical six-category split that the field has converged on. The three-stage classifier (rule-based + supervised + LLM-second-opinion-on-high-stakes) is the right staging pattern, with LLM gated to high-stakes cases rather than running for everyone.
- The barrier-fit dot product is the right scoring abstraction for matching heterogeneous interventions to multi-label barrier predictions: *"if patient barriers are [cost: 0.72, beliefs: 0.21] and intervention 'cost-assistance navigation' supports {cost: 1.0, beliefs: 0.0}, barrier_fit = 0.72."*
- The cost-effectiveness term in the priority math is documented, normalized within intervention type, and named for what it is: *"stops a $0.05 reminder from being crowded out by a $80 pharmacist consult on every candidate."*
- Multi-intervention-per-patient and intervention-sequencing are correctly framed as advances over 4.4: a patient can get cost-assistance navigation for the SGLT2 plus a belief-conversation pharmacist call for the statin, with explicit `max_interventions_per_patient_per_run` and `max_high_touch_per_patient_per_run` policy caps.
- The cross-intervention exclusion logic (a pharmacist consult on a medication absorbs the lower-touch reminder for that medication) is the right pattern.
- LLM scope is kept tight: barrier-classification second opinion (with structured output and explicit confidence), outreach message tailoring (validated before send), pharmacist pre-call brief generation, PCP briefing for regimen simplification. The "the recommender picks; the LLM packages" framing from 4.4 carries through.
- Multi-horizon feedback correctly partitioned: short-horizon engagement (text opened, call scheduled, copay-card application started), medium-horizon adherence change (90-day post-intervention PDC versus matched controls), long-horizon clinical outcomes (HbA1c, BP, LDL, ED visits, hospitalizations). Star Ratings impact tracked separately because business consequences are distinct from clinical impact.
- The barrier-elicited engagement event from pharmacist consults is correctly identified as "gold-label data for the supervised barrier classifier." The architectural seam (engagement stream → attribution Lambda → barrier-classifier training data) is correct.
- The pharmacy-data ingestion pattern explicitly addresses cash-pay and discount-card invisibility, multi-pharmacy fragmentation, therapeutic substitution, and 90-day mail-order timing. The architectural decision (`data_quality_flag` per (patient, class)) is the right way to expose ingestion incompleteness to downstream consumers.
- Specialty pharmacy is correctly identified as needing a separate pipeline, and "Where it struggles" calls it out explicitly: *"Most plans treat specialty as a separate adherence program with its own intervention catalog and its own measurement methodology."*
- Newly-prescribed medications are correctly identified as needing a "primary adherence" pathway distinct from PDC-driven targeting.
- Star Ratings cycle awareness gets explicit treatment with the right ethical framing in The Honest Take. The recommendation that the cross-functional review committee owns the policy weights is the right governance structure.

### Finding 7: Step 6 Equity-Floor Top-Up Pass Is Specified But Not Implemented; `top_up_from_cohort` Is Undefined

- **Severity:** HIGH
- **Expert:** Architecture (correctness)
- **Location:** Step 6 pseudocode (`allocate_heterogeneous`), the second-pass equity-floor top-up block at the end of the function.
- **Problem:** The primary greedy walk in Step 6 decrements `equity_remaining[intervention_id][floor_cohort]` only when a candidate matching the floor cohort is encountered and slots are available. The "Second pass to fill any unfilled equity floors" calls `top_up_from_cohort(allocated, intervention_id, floor_cohort, floor_remaining, prioritized, patient_intervention_count, patient_high_touch_count)` without specifying the helper's semantics:

  ```
  // Second pass to fill any unfilled equity floors.
  FOR intervention_id, floor_remaining_per_cohort in equity_remaining:
      FOR floor_cohort, floor_remaining in floor_remaining_per_cohort:
          IF floor_remaining > 0:
              top_up_from_cohort(allocated, intervention_id, floor_cohort,
                                 floor_remaining, prioritized,
                                 patient_intervention_count, patient_high_touch_count)
  ```

  Critical questions the pseudocode doesn't answer:

  1. Does `top_up_from_cohort` walk the prioritized list a second time looking for cohort matches? If so, does it re-check the same caps (per-intervention capacity, per-patient caps, contact caps, cross-intervention exclusions) that the primary pass enforced?
  2. Does it bypass the global capacity cap (`capacity_remaining[intervention_id] <= 0` already returned in the primary walk) on the theory that the equity floor reserves slots that the primary walk shouldn't have consumed?
  3. If a member already received an intervention in the primary pass and is the highest-priority cohort match for the top-up, does the per-patient cap still apply?
  4. What happens if no cohort-matching candidate exists below the priority threshold the primary pass walked? Does the floor go unfilled, or does the function reach lower-priority candidates that wouldn't have been allocated anyway?

  The 4.4 review's allocator finding noted that "the two-pass allocator (greedy primary plus equity-floor top-up) is the right shape for the starter," but 4.4's pseudocode actually implements the top-up pass inline rather than punting to an undefined helper. The 4.5 pseudocode regresses on this: the function signature suggests the helper does the work, but a reader implementing the pseudocode literally has no way to write the helper correctly.

  The architectural failure mode is significant: a reader implementing this allocator and shipping it will see equity-floor metrics that look reasonable in the dashboard (the primary walk fills floors when the priority sort happens to surface cohort matches early) but fail in production when the priority sort doesn't surface cohort matches early (which is the exact scenario the floors were designed to protect against). The dashboard says "equity floor utilization 95%" because the primary pass consumed 95% of the slots organically, but the 5% that needed the top-up never gets filled because the helper is a no-op.

- **Fix:** Inline the second-pass logic in pseudocode, with explicit semantics:

  ```
  // Second pass: fill any unfilled equity floors by walking prioritized
  // candidates that match the floor cohort, applying the same caps as
  // the primary pass except that the per-intervention global capacity
  // is bypassed (the equity floor's reserved slots come out of the
  // global capacity allocation; the primary pass over-counted by
  // allocating from the global pool to non-cohort candidates).
  FOR intervention_id, floor_remaining_per_cohort in equity_remaining:
      FOR floor_cohort, floor_remaining in floor_remaining_per_cohort:
          IF floor_remaining <= 0:
              CONTINUE
          // Find prioritized candidates for this intervention whose cohort
          // matches the floor and who haven't been allocated yet.
          floor_candidates = [c for c in candidates_sorted
                              if c.intervention_id == intervention_id
                              AND lookup_cohort_features(c.patient_id) matches floor_cohort
                              AND c not in allocated]
          FOR candidate in floor_candidates:
              IF floor_remaining <= 0:
                  BREAK
              // Re-apply per-patient caps but bypass global capacity.
              IF patient_intervention_count.get(candidate.patient_id, 0) >= policy.max_interventions_per_patient_per_run:
                  CONTINUE
              IF intervention.is_high_touch AND
                 patient_high_touch_count.get(candidate.patient_id, 0) >= policy.max_high_touch_per_patient_per_run:
                  CONTINUE
              IF intervention.generates_patient_contact AND
                 (existing_contacts + new_contacts_this_run) >= policy.max_contacts_per_patient_30d:
                  CONTINUE
              IF already_allocated_conflicting(allocated, candidate):
                  CONTINUE

              floor_remaining -= 1
              patient_intervention_count[candidate.patient_id] += 1
              IF intervention.is_high_touch:
                  patient_high_touch_count[candidate.patient_id] += 1
              IF intervention.generates_patient_contact:
                  patient_contact_count_30d[candidate.patient_id] += 1

              allocated.append({
                  ...
                  allocation_reason: "equity_floor:" + floor_cohort,
              })
  ```

  Add a paragraph: *"The primary greedy walk consumes capacity from the global pool; the second pass for equity floors is the corrective. If the primary pass exhausts global capacity before all floors are filled, the floor's reserved slots have already been over-allocated to non-cohort candidates and the floor cannot be filled retroactively. The fix is either (a) reserve floor slots up front by reducing global capacity by the floor count before the primary pass starts, or (b) accept that the primary pass may leave floors unfilled in over-subscribed runs and surface that in the cohort dashboard. Pick (a) for stability and (b) for tightness; document the choice."*

  Reference Recipe 14.x: *"For plans where the greedy two-pass allocator's path-dependence becomes a fairness liability (the same member ends up in different programs across runs depending on priority drift), the integer-programming allocator with explicit fairness constraints is the graduation path."*

### Finding 8: Step 7 Contact-Cap Reconciliation Gap Is TODO; Same Asymmetric Silencing Failure as 4.4

- **Severity:** HIGH
- **Expert:** Architecture (fairness, correctness)
- **Location:** Step 7 pseudocode, the optimistic `DynamoDB.UpdateItem` increment on `outreach_recent_30d_count`; the explicit TODO marker after Step 7 calling out the reconciliation gap; Step 8 pseudocode, no decrement on `intervention_outreach_failed` events.
- **Problem:** Same pattern as 4.4 Finding 9, acknowledged here in a TODO marker. The TODO is explicit and correct: *"Without these, members with flaky channels accumulate phantom contact-cap consumption and get systematically excluded from future allocations they should still be eligible for. The asymmetry compounds across cohorts: members with reliable channels stay at the cap floor, members with flaky channels silently move past the cap floor and lose access to the program."*

  The 4.5-specific failure mode is more harmful than the 4.4 version. In 4.4, a wellness-program flaky-channel silencing means members miss out on a wellness recommendation. In 4.5, the silencing means members miss out on adherence interventions for chronic medications they're already non-adherent to. The clinical risk of the silencing is structural rather than aspirational: the population that gets silenced is, on average, the population with worse adherence outcomes, worse SDOH, and higher clinical risk from continued non-adherence.

  The Code Review (Finding 1) caught a related boto3 bug in the Python companion: the contact-cap reconciliation Python code references a `:zero` placeholder that's never declared, so the reconciliation throws a ValidationException at runtime and gets silently swallowed by a broad except clause. The pseudocode here doesn't have the syntax bug because pseudocode doesn't have boto3 syntax, but the underlying issue (reconciliation acknowledged but not implemented) is the same problem at the architecture level that the code review found at the implementation level.

  This finding is HIGH because (a) the TODO marker promises the reconciliation but the pseudocode doesn't deliver, (b) the failure mode is documented but unmitigated, (c) the equity story the recipe is trying to tell is undermined by leaving the reconciliation unimplemented, and (d) the Code Review found the same gap and FAIL'd the Python companion for it.

- **Fix:** Implement the reconciliation explicitly in Step 8 pseudocode, matching the 4.4 review's Finding 9 fix. Add a delivery-failure clause to `process_adherence_event`:

  ```
  IF event.event_type in ["intervention_outreach_failed",
                           "intervention_outreach_bounced",
                           "intervention_outreach_undeliverable"]:
      // Delivery never reached the patient; release the optimistic cap slot.
      DynamoDB.UpdateItem(
          "patient-profile",
          event.patient_id,
          "ADD outreach_recent_30d_count :neg_one",
          condition = "outreach_recent_30d_count > :zero",
          values = { ":neg_one": -1, ":zero": 0 }
      )
      emit_metric("outreach_delivery_failure_decrement", value=1, dimensions={
          event_type: event.event_type,
          intervention_type: rec.intervention_type,
          channel: event.channel
      })
      RETURN
  ```

  Add a stale-pending sweep Lambda that runs on a 24-hour delay and reconciles tracking_ids with no engagement-stream activity:

  ```
  FUNCTION reconcile_silent_recommendations(run_date_threshold):
      silent_rows = recommendation-log.scan(
          run_date < run_date_threshold,
          NO matching event in engagement-events
      )
      FOR each row in silent_rows:
          DynamoDB.UpdateItem("patient-profile", row.patient_id,
              "ADD outreach_recent_30d_count :neg_one",
              condition = "outreach_recent_30d_count > :zero")
          emit_metric("silent_outreach_reconciled", value=1)
  ```

  Promote the TODO content into a paragraph in The Honest Take: *"Optimistic counter increments without a reconciliation path silence members whose outreach doesn't reach them. The reconciliation has two halves: a delivery-failure event from the channel layer that decrements the counter, and a stale-pending sweep that catches the cases where no event arrives at all. Both are needed; either alone leaves the asymmetric cohort-silencing in place. This is one of the failure modes that surfaces six months in, when the equity dashboard starts trending in a direction nobody expected."*

### Finding 9: Star Ratings 75-79 PDC Cohort Allocation Floor Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (clinical-vs-business policy)
- **Location:** TODO at the bottom of "Why This Isn't Production-Ready": *"Add a paragraph clarifying the Star Ratings ethics. The documented temptation is to over-target the 75-79 PDC band..."*; The Honest Take's substantive paragraph on the trap.
- **Problem:** The recipe correctly identifies the Star Ratings cut-point distortion as one of the most common ethical failure modes in production adherence programs. The Honest Take treats the ethics seriously: *"The patient at PDC 35 percent has more clinical room to improve, and the population health benefit of moving them to PDC 65 is much larger than moving the 78-percent patient to 81 percent. The plan-revenue benefit is the opposite. Both can't win when capacity is finite."*

  The TODO marker names the architectural fix (an explicit allocation floor for the high-clinical-need / low-PDC cohort regardless of Star Ratings impact, owned by the cross-functional review committee, documented in policy version notes) but doesn't write it as architecture.

  The architectural seam exists: equity floors are already first-class in the allocator. A `clinical_need_floor` that reserves capacity for patients in the 30-50 PDC band on Star-Ratings-tracked classes is the same shape as an equity floor for an SDOH cohort. The catalog and policy already support per-(intervention, cohort) reservations. The recipe should write the pattern explicitly so a reader implementing the recipe doesn't quietly skip it.

  This finding is MEDIUM because the recipe acknowledges the ethics extensively in The Honest Take, but the architectural fix is named in a TODO rather than implemented. A reader who skips The Honest Take and implements the architecture will not have the floor.

- **Fix:** Promote the TODO content into a Step 6 architectural paragraph and a policy-config example:

  ```
  // Star Ratings cohort floor: capacity reserved for patients in the
  // 30-50 PDC band on Star-Ratings-tracked therapeutic classes
  // (statins, RAS antagonists, oral diabetes). The floor protects the
  // high-clinical-need cohort from being crowded out by the optimization's
  // attraction to the 75-79 PDC band.
  EQUITY_FLOORS = {
      "pharmacist-consult-001": {
          "clinical_need_high_pdc_low": 50,        // 50 slots/run for PDC 30-50 cohort
          "engagement_history_q1": 30,             // existing equity floor
      },
      "cost-assist-001": {
          "clinical_need_high_pdc_low": 100,
          "lis_eligible_unenrolled": 75,
      },
      ...
  }

  // Cohort definition: a patient is in the clinical_need_high_pdc_low
  // cohort if PDC for any Star-Ratings-tracked class is in [0.30, 0.50]
  // and the medication is currently active.
  ```

  Add a paragraph to the Step 6 prose: *"Star Ratings cohort floors are the explicit architectural answer to the optimization-pulls-toward-cut-point problem. A floor that reserves N slots for the high-clinical-need / low-PDC cohort means the optimization cannot allocate 100% of pharmacist capacity to the 75-79 band even when the priority math says it should. The floor is policy: the cross-functional review committee picks N based on clinical-vs-business trade-off, documents the rationale in the policy version, and reviews quarterly. The dashboard shows floor utilization separately from primary allocation so the committee can see whether the floor is binding (it should be most weeks) or empty (a sign the priority math has shifted away from the high-need cohort and the floor isn't accomplishing what it was designed to)."*

### Finding 10: Cross-Recipe Contact-Cap Counter Naming Is Inconsistent and No Shared Counter Is Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (cross-recipe coherence)
- **Location:** Step 7 pseudocode (`outreach_recent_30d_count`); 4.4 used `outreach_recent_wellness_count`; the TODO at the bottom of "Why This Isn't Production-Ready" calling out the cross-recipe orchestration gap.
- **Problem:** The TODO marker correctly names the cross-recipe orchestration problem: *"A patient on a wellness program (DPP) and an adherence-targeting program (statin reminder) and a care-management program (high-risk diabetes) can easily get four to seven outreach contacts per month from the plan's various optimizations, which is too many."* The TODO proposes the right fix (a single `outreach_recent_total_30d_count` shared across all recipes, with per-recipe sub-counters for cohort attribution), but the Step 7 pseudocode here uses `outreach_recent_30d_count`, which is inconsistent with 4.4's `outreach_recent_wellness_count` and doesn't reflect the shared-counter pattern.

  Three concrete problems:

  1. **The recipe-level counter `outreach_recent_30d_count` is ambiguous.** Is it adherence-only? Is it total? The name suggests total, but the pseudocode increments it only on adherence outreach. The 4.4 counter is `outreach_recent_wellness_count`, suggesting wellness-only. Neither uses a clearly-named total counter.
  2. **No shared cap is enforced.** If 4.4 enforces a wellness cap of 2/month and 4.5 enforces an adherence cap of 3/month and 4.7 (future) enforces a care-management cap of 1/month, the patient can get 6 contacts/month. The recipe's named cap (`max_contacts_per_patient_30d`) is per-recipe.
  3. **Counter reconciliation is harder cross-recipe.** A delivery failure for a wellness reminder needs to decrement the wellness counter; for an adherence reminder, the adherence counter; for the shared total, both. Without a clear naming and contract, reconciliation logic gets duplicated.

- **Fix:** Promote the TODO content into a Step 7 architectural paragraph and specify the shared-counter design:

  *"The patient-profile table carries a single canonical counter `outreach_recent_total_30d_count` that all recipes (4.1, 4.2, 4.4, 4.5, 4.6, 4.7) update. Per-recipe sub-counters (`outreach_recent_wellness_30d_count`, `outreach_recent_adherence_30d_count`, `outreach_recent_care_mgmt_30d_count`) are maintained for cohort attribution and per-recipe cap enforcement. The Step 7 pseudocode here updates both the shared total and the adherence sub-counter atomically:*

  ```
  DynamoDB.UpdateItem(
      "patient-profile",
      row.patient_id,
      "ADD outreach_recent_adherence_30d_count :one,
            outreach_recent_total_30d_count :one",
      values = { ":one": 1 }
  )
  ```

  *The cap policy is bi-level: at most N per recipe per 30 days, plus at most M total per 30 days. The orchestrator reads both counters and defers when either cap is reached. The deferral reason names which cap was binding (`adherence_cap_exceeded` versus `total_cap_exceeded`) for cohort-dashboard attribution. Same reconciliation pattern applies on delivery-failure: decrement both the recipe sub-counter and the shared total."*

  Add a chapter-wide note: *"The shared-counter design is owned by Recipe 4.1 (the chapter's contact-frequency-cap originator) and consumed by all subsequent recipes. Cross-recipe coherence requires that no recipe in this chapter introduce its own private counter without participating in the shared scheme."*

### Finding 11: Cohort-Cycle Calendar Awareness Mentioned but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (operational reality)
- **Location:** "Why This Isn't Production-Ready" Star Ratings cycle awareness paragraph; the 4.4 review's Finding 11 (cohort-cycle calendar integration mentioned but not architected) applies here too.
- **Problem:** The recipe says the recommender should know where in the Star Ratings measurement cycle each target patient sits, *"which affects the urgency of intervention and the appropriate intervention choice (a patient with 60 days remaining and a PDC of 73 percent has a different math problem than the same patient on day 1 of the year)."* The architectural fix (encode the cycle in the policy) is named but not written.

  The Star-Ratings-cycle awareness has different operational semantics than 4.4's cohort-cycle calendar. 4.4's cohort cycle is per-program (DPP starts the first Monday of the month; smoking cessation rolls weekly). The Star Ratings cycle is per-measurement-year, calendar-aligned, with cut points published in the spring for the prior measurement year. Both need to be encoded, but they're different scheduling primitives.

- **Fix:** Add a Step 0 (or a Step 5 sub-section on policy) that specifies the cycle-aware policy:

  ```
  // Star Ratings measurement-year context, refreshed daily from a
  // CMS-cycle-aware config. The recommender uses these to adjust
  // urgency and intervention selection for Star-Ratings-tracked classes.
  STAR_RATINGS_CONTEXT = {
      "measurement_year_start": "2026-01-01",
      "measurement_year_end":   "2026-12-31",
      "current_day":            current_date,
      "days_remaining":         (measurement_year_end - current_date).days,
      "tracked_classes":        ["statins", "ras_antagonists", "oral_diabetes"],
      "cut_point_methodology":  "tukey_outlier_method",  // verify per cycle
      "current_cut_points":     { ... }                  // published periodically
  }

  // Per-patient days-remaining-to-recover calculation.
  FOR patient in target_set:
      FOR therapeutic_class in patient.regimen INTERSECT tracked_classes:
          days_remaining = STAR_RATINGS_CONTEXT.days_remaining
          current_pdc = patient.pdc[therapeutic_class]
          // Days needed at full coverage to reach PDC 0.80:
          days_to_recover = compute_days_to_recover(current_pdc, days_remaining)
          IF days_to_recover > days_remaining:
              recoverable_this_cycle[patient][therapeutic_class] = false
          ELSE:
              recoverable_this_cycle[patient][therapeutic_class] = true
              urgency_factor = (days_to_recover / days_remaining)
  ```

  Add a paragraph: *"The cycle-aware policy is read by the priority combiner (Step 5) as an additional weight on the need score for tracked classes, attenuated by the recoverable-this-cycle gate. A patient who cannot mathematically recover to PDC 0.80 in the remaining days of the measurement year should not be targeted for Star-Ratings-driven urgency; they should be targeted for clinical-need-driven urgency, which is a different intervention selection. Encoding the gate explicitly prevents the optimization from spending capacity on Star-Ratings-impossible cohorts."*

### Finding 12: SageMaker Training-Job Trigger and Model-Promotion Path Are Named in TODO But Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (MLOps)
- **Location:** TODO marker in "Why This Isn't Production-Ready": *"Specify the SageMaker training-job trigger mechanism and model-promotion path from training to inference."*
- **Problem:** Same pattern as 4.4. The architecture diagram shows "Periodic retrain" arrows from `M1[SageMaker Training]` to the four model families (`H1`, `H2`, `H3`, `BC3`) without specifying the trigger or the promotion path. A reader implementing this will either skip retraining (model staleness drifts indefinitely) or implement an ad-hoc cron schedule that doesn't survive contact with model-quality regressions.

  The 4.5 reality is more demanding than 4.4: there are four model families (need, engagement, uplift, supervised barrier classifier), each potentially per-intervention-type or per-therapeutic-class, leading to ~20-30 model artifacts in production. Retraining cadence and promotion governance for that many artifacts requires explicit architecture, not a one-line "periodic retrain" arrow.

- **Fix:** Promote the TODO content into a Step 4 or Step 5 sub-section:

  *"Per-model retrain cadence, trigger, and promotion path:*

  - *Trigger: weekly EventBridge schedule for routine retraining; CloudWatch metric alarm on model-quality regression (calibration drift, AUC degradation in shadow eval) for ad-hoc retraining.*
  - *Training data cutoff: rolling 12-month window for engagement and uplift models; rolling 6-month window for the supervised barrier classifier (label freshness matters more here because pharmacist consult labels accumulate).*
  - *Promotion path: SageMaker Model Registry. Trained models register as candidate version; an automated shadow eval runs against the prior version on a held-out 7-day window; if shadow eval passes (calibration drift below threshold, AUC within tolerance, fairness metrics non-degraded), the model promotes to `Approved` status and the next batch run uses it. If shadow eval fails, the candidate stays as `PendingManualApproval` and a CloudWatch alarm fires to the model-ops team.*
  - *Rollback: any production model that triggers a quality alarm in production rolls back to the prior `Approved` version automatically; the failing version moves to `Rejected` and the model-ops team investigates."*

  Update the architecture diagram caption: *"`M1[SageMaker Training]` writes to the SageMaker Model Registry. The batch-recommendation Step Functions reads the current `Approved` version of each model at the start of each run; the version is recorded in the recommendation log for reproducibility."*

### Finding 13: DLQ Coverage and Idempotency-Key Semantics Are Named in TODOs But Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (operational reliability)
- **Location:** Two TODO markers in "Why This Isn't Production-Ready," one on DLQ coverage and one implicit in the *Idempotency and retry semantics* paragraph.
- **Problem:** Same pattern as 4.4 Finding 10 (idempotency) and 4.4's pre-existing DLQ-coverage TODO. The recipe acknowledges both gaps but doesn't write the architecture. A reader implementing the recipe will hit the same bugs the prior reviewers cataloged.

  The 4.5-specific reality is harder than 4.4 because the pipeline has more stages (eight in 4.5 versus eight in 4.4) and more event types (the engagement stream here carries `pharmacy_fill_observed`, `refill_gap_detected`, `barrier_elicited`, plus all the standard intervention-lifecycle events; 4.4 had a smaller event vocabulary). The blast radius of a silently-dropped event in 4.5 is bigger.

- **Fix:** Same fix as 4.4 Finding 10. Specify the per-stage idempotency keys: (run_date, patient_id, therapeutic_class, intervention_id) for the (Step 5/6/7) chain; (run_date, patient_id, therapeutic_class) for barrier classifications; (event_id, derived from tracking_id + event_type + timestamp) for engagement events. Specify the conditional-write pattern. Specify the DLQ topology: Step Functions Catch on each Lambda task with destination SQS keyed on (run_date, stage, failure_reason); Kinesis attribution Lambda OnFailure destination; Batch Transform job failure handling via Step Functions Catch; CloudWatch alarms on DLQ depth.

### Finding 14: Cohort-Feature Lookup Deduplication Pattern from 4.4 Is Not Applied Here

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 6 pseudocode (`allocate_heterogeneous`), the `lookup_cohort_features(candidate.patient_id)` call inside the per-candidate loop.
- **Problem:** Same pattern as 4.4 Finding 13 and Code Review Finding 5. The allocator's candidate-iteration loop calls `lookup_cohort_features(candidate.patient_id)` once per (patient, intervention, medication) tuple. A patient ranked across 5 interventions for 2 medications produces up to 10 cohort-feature lookups for the same patient. At 80K target patients and average ~4 candidates per patient, that's 320K lookups versus 80K.

  Two impacts (same as 4.4):

  1. DynamoDB throughput cost.
  2. Cohort-feature consistency (concurrent updates can produce different cohort labels for the same patient's recommendations within the same run).

- **Fix:** Same fix as 4.4 Finding 13. Build a per-patient cohort-feature cache once at the top of the allocator and reference it per-candidate:

  ```
  // Build the cohort-feature cache once per patient.
  member_cohort_cache = {}
  unique_patients = set([row.patient_id for row in candidates_sorted])
  FOR each patient_id in unique_patients:
      member_cohort_cache[patient_id] = lookup_cohort_features(patient_id)

  // Then per candidate, read from the cache.
  cohort_features = member_cohort_cache[candidate.patient_id]
  ```

  Add a comment: *"Cohort features are looked up once per patient, not once per (patient, intervention, medication) tuple. A patient ranked across N candidates would otherwise produce N redundant DynamoDB reads, and a concurrent update to patient-profile.sdoh_cohort during the run could produce inconsistent cohort assignments for the same patient's recommendations. Coordinates with Code Review Finding 5."*

---

## Networking Expert Review

### What's Done Well

- Lambdas in VPC with VPC Flow Logs enabled.
- SageMaker training, Batch Transform, and Feature Store online store run in VPC.
- VPC endpoint list is the most comprehensive in the chapter so far, and includes endpoints that earlier recipes missed: DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis, Firehose, KMS, CloudWatch Logs, SageMaker Runtime, Step Functions (`states`), EventBridge (`events`), Glue, Athena, STS, SES, Pinpoint, Connect.
- NAT Gateway scoped explicitly to "external services without VPC endpoints (e.g., a manufacturer copay-card vendor portal); restrict egress with security groups."
- PBM claims feeds explicitly addressed: *"PBM claims feeds typically arrive via SFTP over a Direct Connect tunnel or PrivateLink connection rather than over the public internet."* This is the right architectural posture for raw fill data, and is a noticeable maturation from 4.3's external-SaaS handling.
- TLS in transit specified (implicit in the VPC endpoint and SSE-KMS choices).

### Finding 15: Missing VPC Endpoint for SageMaker Feature Store API and Possibly SageMaker Feature Store Online Store

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites, "VPC" row.
- **Problem:** The VPC endpoint list includes "SageMaker Runtime" but does not explicitly call out the SageMaker Feature Store API (`com.amazonaws.{region}.sagemaker.api`) or the Feature Store Online Store endpoint. The Feature Store has separate API surfaces from SageMaker Runtime, and the online store's PutRecord / GetRecord traffic flows through the Feature Store API endpoint, not the Runtime endpoint.

  Minor risk: control-plane calls to Feature Store traverse public DNS without the dedicated endpoint, which adds a public-DNS dependency the otherwise-clean private architecture didn't need.

- **Fix:** Update the VPC endpoint list to be more explicit:

  *"VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis (`kinesis-streams`), Firehose, KMS, CloudWatch Logs, SageMaker API (`api.sagemaker`), SageMaker Runtime, SageMaker Feature Store Runtime (`featurestore-runtime.sagemaker`), Step Functions (`states`), EventBridge (`events`), Glue, Athena, STS, SES, Pinpoint, Connect."*

### Finding 16: `0.0.0.0/0` Egress Disallow Not Stated Explicitly (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites, "VPC" row.
- **Problem:** Same low-severity finding as 4.1, 4.3, 4.4. The VPC row says "restrict egress with security groups" but doesn't explicitly disallow `0.0.0.0/0` egress on Lambda subnets.
- **Fix:** Add: *"No `0.0.0.0/0` egress from any Lambda subnet. NAT egress restricted by security group to specific IP ranges or hostnames (manufacturer copay-card vendor portal, partner pharmacy API endpoints, foundation-grant program endpoints if applicable). All other outbound traffic must go through VPC endpoints."*

### Finding 17: Vendor Outreach and Partner Pharmacy Credential Posture Not Specified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** "Why These Services," the Amazon SES, Pinpoint, Connect, and PartnerPharmacyAPI paragraphs.
- **Problem:** The recipe mentions multiple external integrations (manufacturer copay-card vendor portals, foundation-grant program portals, partner pharmacy APIs for med-sync enrollment, vendor pharmacist services if used) without specifying credential management. A wellness-program orchestrator that calls a third-party API needs (a) credentials in Secrets Manager with KMS encryption, (b) per-environment isolation, (c) rotation policy. None of this is recipe-4.5-specific, but a sentence pointing to it would help readers who skip prior recipes.
- **Fix:** Add a sentence to the Why These Services section: *"All vendor and partner integrations (manufacturer copay-card portals, foundation-grant programs, partner pharmacy APIs, vendor pharmacist services, the channel-optimizer's downstream SMS gateway) credential through AWS Secrets Manager with KMS encryption and a per-environment rotation policy. Plain-text vendor API keys in Lambda environment variables are not acceptable. Cross-account access for vendor or partner integrations uses scoped IAM roles with a vendor-specific external ID."*

---

## Voice Reviewer

### What's Done Well

- The Maria opening vignette is one of the strongest in the chapter so far. The three-barrier setup (belief barrier on the statin, cost barrier on the SGLT2, communication-with-prescriber barrier underlying both) is clinically realistic and operationally specific in a way that captures why generic reminders fail. The line *"The text arrives. Maria does not have the medication. She has not had it for five months. The text is irrelevant. Worse, the text is mildly insulting"* is the kind of one-paragraph indictment of dumb adherence programs that the chapter has been collecting.
- *"What the data does not tell you is *why*"* is the central thesis stated cleanly, and the recipe's structure earns it: PDC measurement (Stage 1) gives you the *what*; barrier classification (Stage 2) is the *why*; intervention scoring (Stage 3) is the matching of *why* to *which*. The arc is pedagogically clean.
- *"The plan logs it as 'delivered' and 'no response,' which counts as a successful outreach in the operations dashboard, and counts as nothing in the actual world where Maria still has uncontrolled cholesterol"* is the kind of dashboard-vs-reality contrast that distinguishes a CC voice from a documentation voice.
- *"A blanket reminder campaign for everyone with a PDC under 80 percent will produce reminders for thousands of Marias, most of which are irrelevant to the actual barrier, and the program will report a 2 to 4 percent improvement in PDC in the cohort that did get a behavior change, while the other 96 to 98 percent of the campaign was at best wasted effort and at worst counterproductive"* is harsh, specific, and correct. The 2-4% number is the right ballpark for blanket-reminder programs.
- The four-wrinkle setup (heterogeneous interventions, Star Ratings cut-point pressure, pharmacy data messiness, multi-barrier patients) is structurally tight and prepares the reader for each subsequent section.
- *"Reminders work for forgetfulness. They do not work for cost barriers or belief barriers or side-effect concerns or 'the medication makes me dizzy and I haven't told anyone.'"* The cadence of the four-element list landing on the surprising fourth ("haven't told anyone") is the kind of sentence-construction that lifts the prose.
- The Star Ratings ethics paragraph in The Honest Take is the strongest treatment of the cut-point distortion I've seen in any wellness/adherence write-up. The framing *"both can't win when capacity is finite"* and *"'we are optimizing primarily for Star Ratings' is a defensible answer if it's said out loud and reviewed, while 'we are not thinking about it' is not"* makes the ethics conversation tractable.
- The closing of The Honest Take (*"medication non-adherence is often *rational* from the patient's perspective. ...These patients are not failing. They are coping. The right response to non-adherence is rarely 'remind harder.' It's 'find out what's going on, and address that.'"*) is the strongest paragraph in Chapter 4 so far. The *"Build the system to listen; don't build it to nag"* closing is the kind of one-line aphorism the chapter has been collecting.
- *"Some plans count completed consults as the success metric and report 95 percent success rates. The honest metric is..."* is the right framing for the operational-metric-vs-success-metric distinction.
- The capacity-as-staff-not-targeting framing (*"how much of adherence is about *staff capacity*, not patient targeting"*) is a contrarian-but-correct insight that distinguishes this recipe from generic recommender write-ups.
- Em dash check: scanned for U+2014 (em dash). Zero present. Pass.
- En dash check: scanned for U+2013 (en dash) at the byte level. Zero present in prose; the apparent matches in earlier diagnostic sweeps were box-drawing characters in the architecture-diagram fence (▼, U+25BC), confirmed by reading the file with explicit UTF-8 encoding. Pass.
- 70/30 vendor balance: The Problem, The Technology (with sub-sections on Adherence Measurement, Barrier Classification, Heterogeneous Intervention Scoring, Allocation, and Where LLMs Fit), and General Architecture Pattern sections are vendor-neutral. AWS service names appear in the AWS Implementation section and stay there. Clean.
- Marketing-language scan: scanned for "leverage," "seamlessly," "robust," "cutting-edge," "state-of-the-art," "industry-leading," "empower," "unleash," "game-changing," "paradigm," "holistic," "synergy," "best-in-class." Two "robust" hits, both technical and legitimate. No marketing creep.
- "Your mileage may vary" appears in the Expected Results header *"illustrative, your mileage varies"*, used in the right colloquial way.

### Finding 18: One Stretch in "The Technology: Adherence Measurement, Barrier Classification, and Heterogeneous Intervention Uplift" Has the Most Generic Sub-Heading in the Chapter

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Section heading: `## The Technology: Adherence Measurement, Barrier Classification, and Heterogeneous Intervention Uplift`
- **Problem:** Not blocking. The sub-heading is the most generic in the chapter so far; it lists three things rather than committing to a framing. Compare 4.4's `## The Technology: Uplift Modeling, Allocation Under Capacity, and the Engagement-Outcome Distinction` which is also long but commits to a thesis (the engagement-outcome distinction). 4.5's heading reads more like a table of contents.
- **Fix:** Optional editor's pass to commit to a framing. Candidate: *"The Technology: PDC, Barriers, and the Heterogeneous-Intervention Match"* or *"The Technology: Measurement, Why-Classification, and Intervention-Selection Done Honestly"*. Not blocking; the body earns the heading.

### Finding 19: "Build the System to Listen; Don't Build it to Nag" Is the Best Sentence in the Recipe

- **Severity:** N/A (call-out)
- **Expert:** Voice
- **Location:** The Honest Take, last paragraph, last sentence.
- **Problem:** Not a finding. Worth flagging to the editor: this is the sentence that lands the recipe's thesis. The cadence (three-word imperative, semicolon, three-word counter-imperative) is the kind of construction the chapter has been earning. It belongs as the final sentence of The Honest Take and should not be moved or trimmed.
- **Fix:** None. Note for the editor: keep the sentence verbatim; preserve its position as the closing.

### Finding 20: One Cohort-Operations Paragraph in The Honest Take Is the Most Operationally-Honest Treatment of Capacity-as-Constraint in the Chapter

- **Severity:** N/A (call-out)
- **Expert:** Voice
- **Location:** The Honest Take, the paragraph beginning *"The thing that surprises people coming from retail recommendation backgrounds is how much of adherence is about *staff capacity*, not patient targeting"*.
- **Problem:** Not a finding. Worth flagging: this paragraph captures something most recommender write-ups miss. *"A model that perfectly predicts who would benefit from a pharmacist consult is useless if the pharmacist queue has been at capacity for three months"* is the kind of sentence that distinguishes a healthcare-domain recommender from a retail-domain recommender. Editor should preserve it verbatim.
- **Fix:** None. Note for the editor: the paragraph earns its length.

---

## Stage 2: Expert Discussion

**Overlap: Architecture Finding 7 (top-up pass unspecified) and Architecture Finding 8 (contact-cap reconciliation gap).** Both are correctness gaps in the allocator/orchestration layer where the recipe acknowledges the issue (Finding 8 in a TODO; Finding 7 by punting to an undefined helper) but doesn't write the architecture. Both have the same structural failure mode: equity intentions stated in dashboards/policy that the implementation silently doesn't deliver. Resolution: write both fixes inline in the pseudocode rather than as TODOs. The two fixes are independent but compound; either alone leaves the equity story half-built.

**Overlap: Architecture Finding 8 (contact-cap reconciliation) and Code Review Finding 1 (boto3 ConditionExpression `:zero` syntax bug).** Same root failure mode through architecture and implementation paths. The code review caught that the Python implementation fails at runtime with a ValidationException; this review catches that the architecture itself wasn't specified. Both must be fixed: the architecture needs the reconciliation logic specified in pseudocode, and the Python implementation needs the boto3 placeholder declared correctly. Either fix alone leaves a known bug in production.

**Overlap: Security Finding 3 (consent regime multi-dimensional) and Security Finding 4 (PCP review hold-time for high-stakes medications).** Both touch the question of "when is the right moment to send adherence outreach to a particular patient-medication pair," which the current architecture treats as instantaneous after allocation. Resolution: address them as two layers of the same pre-send gate (consent verification + medication-class-aware PCP review), implemented in the orchestrator state machine. Reference the same architectural seam as 4.4's parallel findings.

**Overlap: Architecture Finding 9 (Star Ratings cohort floor not architected) and Voice Finding 19/20 (Honest Take ethics treatment is strong).** The Honest Take treats the Star Ratings ethics with the right honesty, but the architecture doesn't follow through on the floor. Resolution: promote the TODO into a Step 6 architectural paragraph and a policy-config example, with the Honest Take's ethical framing as the rationale for the architectural fix. The strength of the Honest Take is what makes the architectural gap notable: the ethics conversation is mature enough to deserve an architectural answer, not another TODO.

**Overlap: Architecture Finding 10 (cross-recipe contact-cap counter naming) and Architecture Finding 12 (training trigger / model promotion path) and Architecture Finding 13 (DLQ coverage / idempotency keys).** All three are chapter-wide patterns that have been TODO'd in 4.4 and re-TODO'd here. Resolution: consolidate into a chapter-4 preface section on shared production-hardening guidance to stop re-litigating per recipe. Suggested chapter-preface scope: shared-counter design, model registry and promotion path, per-stage idempotency keys, DLQ topology, IAM ARN scoping pattern, `0.0.0.0/0` egress disallow.

**Cross-recipe overlap: chapter-wide hardening patterns.** IAM ARN scoping (Finding 6 here; Finding 5 in 4.1 / 4.2 / 4.3 / 4.4), `0.0.0.0/0` egress (Finding 16 here; same in 4.1, 4.3, 4.4), SDOH-cohort PHI sensitivity (Finding 5 here; same in 4.4), tracking-ID PHI leakage (Finding 2 here; same in 4.4), cohort-feature lookup deduplication (Finding 14 here; same in 4.4), DLQ coverage (Finding 13 here; same in 4.4), training trigger / model promotion (Finding 12 here; same in 4.4), consent regime (Finding 3 here; 4.4 had ADA/GINA/state; 4.5 has state pharmacy boards/TCPA/HIPAA marketing). The cross-recipe progress: SES BAA scope, SageMaker Feature Store HIPAA eligibility, Bedrock per-model eligibility, comprehensive VPC endpoints, recommendation-log retention, engagement-event identity check, Bedrock data-retention posture, Direct Connect / PrivateLink for vendor data feeds, customer-managed KMS posture across all PHI-containing stores have all matured into the main text in 4.5.

**No major conflicts among experts.** Security and Architecture both want stronger pre-send gates (consent multi-dimensional, validator specified, PCP-review-policy for high-stakes medications, optimistic counter reconciled), and these align. Networking is about endpoint topology and credentials. Voice is cosmetic with two call-outs to preserve strong sentences.

**Priority alignment.** Two HIGH findings (allocator top-up pass unspecified; contact-cap reconciliation gap) are the must-fix-before-publication correctness items. Eight MEDIUM findings are production-hardening that the editor or the next pipeline pass should address; several of them are chapter-wide patterns that would benefit from consolidation rather than per-recipe re-litigation. Six LOW findings are cosmetic, edge-case, or chapter-pattern items.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

Zero CRITICAL findings. Two HIGH findings (Findings 7 and 8), which is below the FAIL threshold (more than 3 = FAIL).

The two HIGH findings are correctness gaps where the recipe names the problem but doesn't deliver the fix in pseudocode:

- **Finding 7** (allocator equity-floor top-up pass calls an undefined helper): the second-pass logic is mentioned but punted to a `top_up_from_cohort(...)` helper whose semantics the pseudocode doesn't specify. A reader implementing the pseudocode literally will either skip the second pass or implement it inconsistently with the primary pass. The fix is to inline the second-pass logic with explicit semantics for cap re-application and global-capacity reservation.

- **Finding 8** (contact-cap reconciliation gap is acknowledged in a TODO but the reconciliation is not implemented): same pattern as 4.4 Finding 9, and the Code Review caught the corresponding boto3 implementation bug at the syntax level (the `:zero` placeholder is never declared, so the runtime swallows the ValidationException and the counter never decrements). The architectural fix is to add an `intervention_outreach_failed` clause to `process_adherence_event` and a stale-pending sweep Lambda; the implementation fix is in the Python companion (the code-reviewer's job, but the boto3 syntax issue is downstream of the architectural gap).

The eight MEDIUM findings are production-hardening items: validator pseudocode shape (Finding 1), tracking-ID PHI leakage in Expected Results samples (Finding 2), consent regime multi-dimensional (Finding 3), PCP review hold-time for high-stakes medications (Finding 4), Star Ratings cohort floor (Finding 9), cross-recipe contact-cap counter naming (Finding 10), cohort-cycle calendar awareness (Finding 11), training trigger / model promotion path (Finding 12), DLQ coverage and idempotency keys (Finding 13), cohort-feature lookup deduplication (Finding 14). Several of these are chapter-wide patterns that have now been TODO'd in 4.4 and 4.5 and would benefit from consolidation into a chapter preface rather than per-recipe re-litigation.

The six LOW findings are cosmetic, edge-case, or chapter-pattern items: SDOH-cohort PHI promotion (Finding 5), IAM ARN scoping (Finding 6), Feature Store VPC endpoint (Finding 15), `0.0.0.0/0` egress (Finding 16), vendor credential posture (Finding 17), and the section-heading sub-thesis polish (Finding 18). Plus two voice call-outs to preserve strong sentences (Findings 19 and 20).

The recipe's teaching arc (PDC done correctly, six-category barrier taxonomy with rule + supervised + LLM staging, heterogeneous-intervention scoring with explicit cost-effectiveness, capacity-aware allocation with multi-intervention-per-patient, Star Ratings ethics, multi-horizon feedback, randomized-pilots-from-day-one) is solid and publishable. The HIGH findings should be addressed in the main text before the editor finalizes; the MEDIUM findings can be addressed inline or consolidated into a chapter preface as the editor sees fit.

The recipe's voice is the chapter's strongest so far. The Maria opening, the Star Ratings ethics paragraph in The Honest Take, the capacity-as-staff-not-targeting framing, and the "Build the system to listen; don't build it to nag" closing are all worth preserving verbatim. The recipe earns its length.

The chapter-wide hardening trajectory continues to mature: this recipe resolves into the main text the SES BAA scope, the Direct Connect / PrivateLink posture for vendor data feeds, the comprehensive VPC endpoint list (now with Glue, Athena, Firehose, STS, Pinpoint, Connect), the recommendation-log retention and CloudTrail data events, the engagement-event identity check, and the Bedrock data-retention posture. The remaining TODO markers cluster around chapter-wide patterns that would benefit from consolidation rather than per-recipe re-litigation.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| 7 | HIGH | Architecture | Step 6 pseudocode | Equity-floor top-up pass calls undefined `top_up_from_cohort` helper; reader will skip or mis-implement |
| 8 | HIGH | Architecture | Step 7 pseudocode + TODO | Contact-cap reconciliation acknowledged in TODO but not implemented; same asymmetric-silencing failure as 4.4 |
| 1 | MEDIUM | Security | Step 7 pseudocode | Reminder validator and pharmacist-brief validator named but not specified; manufacturer-funded interventions need separate approved-claims artifacts |
| 2 | MEDIUM | Security | Step 7 pseudocode + Expected Results | Tracking ID embeds patient_id and therapeutic_class in plain text (more sensitive than 4.4's program_id) |
| 3 | MEDIUM | Security | No section currently | Adherence consent regime not addressed: state pharmacy boards, TCPA for SMS/voice, HIPAA marketing rules for manufacturer-funded interventions |
| 4 | MEDIUM | Security | Step 7 pseudocode | PCP review path has no pre-send hold-time semantics for high-stakes medication classes (anticoagulants, anti-rejection, oral chemo, antiretrovirals, insulin during dose adjustment) |
| 9 | MEDIUM | Architecture | Step 6 + Honest Take | Star Ratings cohort allocation floor named in TODO but not architected as a first-class equity floor |
| 10 | MEDIUM | Architecture | Step 7 pseudocode | Cross-recipe contact-cap counter naming inconsistent with 4.4; no shared counter pattern specified |
| 11 | MEDIUM | Architecture | Production-gaps section | Cohort-cycle calendar awareness mentioned but not architected; per-patient days-to-recover gate not specified |
| 12 | MEDIUM | Architecture | Production-gaps TODO | SageMaker training trigger and model promotion path named but not architected (chapter-wide pattern) |
| 13 | MEDIUM | Architecture | Production-gaps TODOs | DLQ coverage and idempotency-key semantics named but not architected (chapter-wide pattern) |
| 14 | MEDIUM | Architecture | Step 6 pseudocode | Cohort-feature lookup repeats per (patient, intervention, medication) tuple instead of per patient |
| 5 | LOW | Security | Production-gaps TODO | SDOH cohort PHI paragraph in TODO; should promote into main Privacy paragraph |
| 6 | LOW | Security | Prerequisites IAM row | "Never *" stated but scoped ARN examples not shown (chapter-wide pattern) |
| 15 | LOW | Networking | Prerequisites VPC row | VPC endpoint list could be more explicit on SageMaker API + Feature Store Runtime separation |
| 16 | LOW | Networking | Prerequisites VPC row | `0.0.0.0/0` egress disallow not stated explicitly (chapter-wide pattern) |
| 17 | LOW | Networking | Why These Services | Vendor and partner credential posture not specified (Secrets Manager + KMS + rotation) |
| 18 | LOW | Voice | Section heading | "The Technology: ..." sub-heading is generic; doesn't commit to a framing |
| 19 | N/A | Voice | Honest Take closing | Not a finding; note for editor: "Build the system to listen; don't build it to nag" is best closing in chapter, preserve verbatim |
| 20 | N/A | Voice | Honest Take | Not a finding; note for editor: capacity-as-staff-not-targeting paragraph is strongest operational-reality treatment in chapter, preserve verbatim |

---

## Recommended Actions (Priority Order)

1. **Inline the equity-floor top-up pass logic in Step 6** (Finding 7): replace the `top_up_from_cohort(...)` call with explicit pseudocode that re-applies per-patient caps and bypasses global capacity (or alternatively, reserves floor slots up front by reducing global capacity before the primary pass starts). Document the choice between strategies and the trade-off.

2. **Implement the contact-cap reconciliation in Step 8** (Finding 8): add an `intervention_outreach_failed` / `intervention_outreach_bounced` / `intervention_outreach_undeliverable` clause to `process_adherence_event` that decrements `outreach_recent_30d_count` (and the shared total counter; see Finding 10) with a `ConditionExpression` guard against under-zero. Specify the channel-optimizer integration contract that emits delivery-failure events. Add a stale-pending sweep Lambda for tracking_ids with no engagement-stream activity in 24 hours. Promote the TODO content into The Honest Take as a six-months-in failure mode. Pair with the Code Review's Finding 1 fix (the boto3 `:zero` placeholder declaration).

3. **Specify the reminder validator and pharmacist-brief validator pseudocode** (Finding 1): four-layer validator for the reminder (schema, required disclosures, prohibited claims, approved-claims-only), separate validator for the pharmacist brief (clinical accuracy, no fabricated context, contraindications referenced are genuine). Specify failure-handling for each. Add the `funding_source` catalog field for manufacturer-funded reminders.

4. **Replace plain-text tracking_ids in Expected Results samples with opaque identifiers** (Finding 2): UUID or HMAC; promote the TODO into Step 7 pseudocode. Add a sentence noting that therapeutic_class-in-tracking-id is more sensitive than program_id-in-tracking-id was in 4.4.

5. **Add an Adherence Consent and Regulatory Posture sub-section** (Finding 3): state pharmacy boards, TCPA for SMS/voice, HIPAA marketing rules for manufacturer-funded interventions and cost-assistance navigation. Add a per-intervention `consent_classification` catalog field and an eligibility-filter line that consults it.

6. **Add medication-class PCP review policy** (Finding 4): `pcp_review_policy` field on the intervention catalog with `none`, `notify_parallel`, `review_required_24h`, `review_required_72h_specialist_team` values; `medication_class_review_policy` lookup that overrides per-intervention defaults for high-stakes classes (anticoagulants, anti-rejection, oral chemo, antiretrovirals, insulin during dose adjustment). Update Step 7 orchestration to respect the policy.

7. **Architect the Star Ratings cohort allocation floor as a first-class equity floor** (Finding 9): promote the TODO into Step 6. Add a `clinical_need_high_pdc_low` cohort definition (PDC 0.30-0.50 on Star-Ratings-tracked classes) and reserve capacity for it across pharmacist-consult and cost-assistance interventions. Document the cross-functional review committee's policy ownership and quarterly review cadence.

8. **Specify the shared cross-recipe contact-cap counter design** (Finding 10): `outreach_recent_total_30d_count` shared across all recipes plus `outreach_recent_adherence_30d_count` sub-counter; bi-level cap policy; reconciliation pattern for delivery failures. Add a chapter-wide note that the design is owned by Recipe 4.1 and consumed by all subsequent recipes.

9. **Architect the cohort-cycle calendar awareness** (Finding 11): `STAR_RATINGS_CONTEXT` policy config refreshed daily; per-patient `days_to_recover` gate that prevents the optimization from spending capacity on Star-Ratings-impossible cohorts.

10. **Specify the SageMaker training trigger and model-promotion path** (Finding 12): EventBridge weekly schedule + CloudWatch metric alarms for trigger; SageMaker Model Registry with shadow eval for promotion; rollback semantics. Coordinate with the chapter-wide pattern; consider promoting into a chapter preface section.

11. **Specify per-stage idempotency keys and DLQ topology** (Finding 13): same fix as 4.4 Finding 10. Coordinate with the chapter-wide pattern.

12. **Deduplicate cohort-feature lookups by patient** (Finding 14): same fix as 4.4 Finding 13. Coordinates with Code Review Finding 5 from 4.4.

13. **Promote SDOH cohort PHI paragraph from TODO into main Privacy paragraph** (Finding 5).

14. **Add scoped IAM ARN examples** (Finding 6): chapter-wide pattern.

15. **Refine VPC endpoint list** (Finding 15): split SageMaker API from SageMaker Runtime; add SageMaker Feature Store Runtime explicitly.

16. **Disallow `0.0.0.0/0` egress on Lambda subnets explicitly** (Finding 16): chapter-wide pattern.

17. **Specify vendor and partner credential posture** (Finding 17): Secrets Manager + KMS + rotation, with cross-account scoped roles and external IDs.

18. **Optional voice polish** (Finding 18): commit to a sub-thesis in The Technology heading.

19. **Preserve the closing sentence and the capacity-as-staff paragraph verbatim** (Findings 19, 20). Editor's note.

---

## Notes for Editor

- The recipe runs long (~10,000 words including footer). Length is earned: the four-wrinkle setup, the PDC-correctness sub-section, the six-barrier taxonomy with three-stage classifier, the heterogeneous-scoring sub-section with explicit cost-effectiveness math, the multi-intervention-per-patient and intervention-sequencing discussion, the Where LLMs Fit sub-section, the Why This Isn't Production-Ready section, The Honest Take, and the Variations and Extensions are all pedagogically essential. Do not trim any of them.
- The recipe has 14 `<!-- TODO -->` markers (10 inline confirmation/verification TODOs, 4 architectural-pattern TODOs at the bottom of "Why This Isn't Production-Ready"). The 10 inline TODOs are realistic verification tasks (PQA measure specifications confirmation, Bedrock service terms, SageMaker Batch Transform HIPAA, Pinpoint and Connect HIPAA configurations, IAM ARN examples, Cost Estimate validation, blog/repo URL verification, CMS PQA URL, generic AWS-blog pointers replaced with verified URLs); these are not blockers. The 4 architectural-pattern TODOs at the end (training trigger / model promotion, contact-cap reconciliation, Star Ratings governance, SDOH cohort PHI promotion) overlap with the MEDIUM and HIGH findings here; resolving the findings will close those TODOs.
- The Cost Estimate is reasonable but on the higher end for Bedrock. Reviewing the per-call cost for Haiku-class at 30K calls/week yields a lower number than the $300-600/month claim. Verify when finalizing.
- The Related Recipes section forward-references future recipes (4.6, 4.7, 4.10, 7.x, 8.x, 11.x, 14.x) that haven't been written yet. Standard practice for the book.
- The footer link to Recipe 4.6 references a future recipe that doesn't exist yet. Standard placeholder.
- All external links in Additional Resources are real and verified at the surface level (PQA, CMS, econml, causalml, Obermeyer 2019, Synthea, AWS docs); the TODOs flagging URL volatility are appropriate.
- The aws-samples repo references (`amazon-sagemaker-examples`, `amazon-sagemaker-feature-store-end-to-end-workshop`, `amazon-bedrock-workshop`) are appropriately hedged with a TODO. Appropriate.
- Cross-recipe coherence with 4.1 through 4.4 is strong: the patient-profile store, engagement-event bus, channel optimizer integration, contact-frequency cap (with the gap noted in Finding 10), cohort dashboard infrastructure, and Bedrock / DynamoDB / Kinesis primitives are all reused consistently. The "Where This Sits in the Chapter" section's framing of 4.5 as the recipe that adds barrier classification, heterogeneous intervention scoring, and pharmacy-data-aware adherence measurement onto the personalization scaffold is accurate and helps the chapter narrative.
- The Code Review (`reviews/chapter04.05-code-review.md`) found one ERROR (the boto3 ConditionExpression `:zero` placeholder bug in the contact-cap reconciliation) and seven NOTEs, returning a FAIL verdict. The ERROR is implementation-level and downstream of this review's HIGH Finding 8 (architecture-level reconciliation gap). Both must be resolved.
- Voice and 70/30 vendor balance: clean. Em dash count: 0. En dash count: 0 (verified at the byte level with explicit UTF-8 encoding; earlier diagnostic sweeps that reported en dashes were misreading box-drawing characters in the architecture diagram). Recipe is publishable on voice grounds without any additional fixes.
- The "Build the system to listen; don't build it to nag" closing of The Honest Take is the strongest closing line in the chapter so far. Preserve verbatim and as the final sentence.
- The capacity-as-staff-not-targeting paragraph (Finding 20) is the strongest operational-reality treatment in the chapter. Preserve verbatim.
- The Maria opening vignette is the strongest in the chapter. The three-barrier setup is clinically realistic and operationally specific. Preserve verbatim.
- Several findings here repeat patterns from the 4.4 review (Findings 7, 8, 10, 12, 13, 14 here align with 4.4 Findings 9, 13, etc.). The chapter editor should consider whether a chapter-4 production-hardening preface section would close these once chapter-wide rather than recipe-by-recipe. The shared-counter design, the model registry pattern, the per-stage idempotency keys, the DLQ topology, the IAM ARN scoping, and the `0.0.0.0/0` egress disallow would all benefit.

---

*Review complete. Findings prioritized; PASS verdict at threshold (2 HIGH, well below the FAIL threshold of more than 3). The two HIGH findings are correctness gaps where the recipe acknowledges the problem but doesn't deliver the fix; both are local edits to Step 6 and Step 7/8 pseudocode. Chapter-wide hardening progress (recommendation-log retention, engagement-event identity check, Bedrock data-retention posture, comprehensive VPC endpoints, Direct Connect / PrivateLink for vendor data feeds, customer-managed KMS for all PHI-containing stores) continues to mature from prior recipes' TODOs into this recipe's main text. The Maria opening vignette, the Star Ratings ethics paragraph, the capacity-as-staff-not-targeting framing, and the "Build the system to listen; don't build it to nag" closing are the strongest voice contributions to Chapter 4 so far and should be preserved verbatim.*
