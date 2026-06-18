# Open TODOs — Recipe 4.6: Care Gap Prioritization ⭐⭐

> Auto-extracted 2026-06-18 from inline source comments (35 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter04.06-care-gap-prioritization.md`

- **L168** — TODO (TechWriter, MEDIUM per Expert Review A9): Three clinical-loosenesses in this vignette. (1) Pneumococcal: ACIP has indicated pneumococcal vaccination (PPSV23 historically; PCV15/PCV20 under current simplified recommendations) for adults 19-64 with diabetes for years. David's gap is not "newly indicated at 64"; it has been open for most of a decade. Reframe as a long-standing gap. (2) Diabetic foot exam: the parent HEDIS CDC measure was retired (see HEDIS naming TODO above) and the foot-exam component did not survive the split. Foot exams remain ADA-recommended but no current HEDIS or Star measure tracks them. Either reframe as a guideline-recommended (ADA) gap that the practice's internal quality dashboard tracks, or remove the "quality dashboard shows it red" framing. (3) Colon cancer family history: a paternal CRC diagnosis at 71 generally does NOT trigger elevated-risk surveillance under NCCN/ACG/USMSTF criteria (those trigger when a first-degree relative is diagnosed at <60). Either strengthen the family history to genuinely trigger elevated-risk screening, or drop the "earlier and more frequent" elevated-risk framing and treat David as average-risk where the gap is "the 10-year interval has elapsed." This last cleanup also requires fixing the matching "his colonoscopy that's six years overdue" line in the unlucky-version paragraph below: David is 64 with a normal colonoscopy at 54, so under average-risk guidance he is at-due, not six years overdue. Coordinate all three fixes in a single 30-minute clinical-informatics review pass.
- **L210** — TODO (TechWriter, HIGH per Expert Review A3): NCQA retired the parent Comprehensive Diabetes Care (CDC) measure beginning HEDIS MY 2022 and split it into EED (Eye Exam for Patients with Diabetes), KED (Kidney Health Evaluation for Patients With Diabetes), GSD (Glycemic Status Assessment for Patients With Diabetes), and BPD (Blood Pressure Control for Patients With Diabetes). Replace "HEDIS Comprehensive Diabetes Care eye exam" with "HEDIS Eye Exam for Patients with Diabetes (EED)" and add a parenthetical note explaining the CDC retirement and the EED/KED/GSD/BPD split. Coordinate with the Expected Results sample (`measure_id: hedis-cdc-eye-exam` should become `hedis-eed`) and with the Python companion's synthetic registry (Code Review Finding 1). Also confirm current HEDIS, CMS Star Ratings, and major ACO measure specification sources at the time of build.
- **L475** — TODO (TechWriter, HIGH per Expert Review A2): Add a paragraph here naming the data_quality_flag gate explicitly. The flag is computed and persisted in Step 1 of the architecture companion (chapter04.06-architecture.md), then never gates downstream decisions. The "Where it struggles" section in the architecture companion says explicitly that downstream consumers should gate on it; the pseudocode does not. Five places in the architecture companion need the gate: (a) Step 2 dampens urgency confidence on non-`complete` cases, (b) Step 3 suppresses low-quality gaps from the in-visit agenda, (c) Step 4 routes low-quality cases to a verification-first pathway before any closure-pathway-specific outreach, (d) Step 5 tightens (or relaxes, for `cross_provider_fragmentation`) the canonical-source rule, (e) Step 4 chase brief opens with verification framing when data quality is in doubt. The "calling a patient about a colonoscopy they had last week" failure mode the Honest Take warns against is exactly what `cross_provider_fragmentation` flags; not gating on it produces precisely that failure. Frame as: "the data_quality_flag is not metadata; it's an input to every downstream stage."
- **L504** — TODO: confirm a published reference for the audit cadence; quality-measure programs vary in their formal review processes.

## architecture — `chapter04.06-architecture.md`

- **L24** — TODO: confirm SageMaker Batch Transform's current HIPAA eligibility and the appropriate instance types for the model sizes implied here.
- **L48** — TODO: confirm current Bedrock service terms and the eligible-model list at the time of build; the BAA-covered model list has been evolving.
- **L54** — TODO: confirm SES HIPAA eligibility and BAA scope at the time of build; verify Pinpoint SMS eligibility.
- **L58** — TODO: confirm AWS HealthLake's current pricing and HIPAA eligibility at the time of build; consider whether HealthLake is the right fit relative to direct FHIR-to-S3 patterns for the implementing team.
- **L152** — TODO: pair these actions with one or two scoped Resource ARN examples so a reader copying into an IAM policy doesn't default to `Resource: *`. Same chapter-wide pattern flagged in 4.1, 4.2, 4.3, 4.4, 4.5 reviews.
- **L153** — TODO: confirm Bedrock + selected models are eligible at the time of build; verify Pinpoint and Connect HIPAA-eligible configurations; verify HealthLake eligibility.
- **L159** — TODO: replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator.
- **L194** — TODO: confirm the current names and locations of these aws-samples repos.
- **L317** — TODO (TechWriter): Specify validate_candidate_gaps's
            // four-layer structure mirroring 4.5 Step 2: (1) schema and
            // taxonomy check, (2) rationale length/structure, (3)
            // rationale must cite observable data points whose values
            // match observed_data within tolerance, (4) prohibited
            // content (PHI not in source, prescriber names) in
            // rationale. Specify failure handling: validator failure
            // means the candidate is dropped from the review queue and
            // the failure is logged for prompt-engineering review.
- **L569** — TODO (TechWriter): Specify validate_briefing's
            // four-layer structure: (1) schema and length, (2) every
            // referenced agenda item must appear in observed_agenda
            // (the LLM cannot hallucinate gaps that aren't on the
            // deterministic agenda), (3) prohibited content (PHI
            // not in source, prescriber names other than the visit
            // provider's, suggestions that override the deterministic
            // ranker's choices), (4) required disclaimers ("subject
            // to clinical judgment", briefings are advisory, etc.).
            // Specify failure handling: validator failure means the
            // briefing is replaced with a templated fallback that
            // simply lists the in_visit_agenda items without LLM
            // narration; the failure is logged for prompt-engineering
            // review.
- **L653** — TODO (TechWriter, MEDIUM per Code Review WARNING 3): When
        //      best_pathway == "in_visit" but the patient has no upcoming
        //      visit on the visit-context-ranker horizon, the current
        //      pseudocode silently allocates the gap to a no-op (no
        //      outreach is sent, no chase queue is populated, no PCP
        //      inbox note is filed). The gap is registered as "surfaced"
        //      but never acted on. Add an explicit fall-through to
        //      second_best_pathway when chosen_pathway == "in_visit" AND
        //      candidate.patient_id NOT IN visited_or_planned. The visit-
        //      context ranker is the only place in_visit gaps should be
        //      surfaced; the async orchestrator should never see them.
- **L816** — TODO (TechWriter): Same reconciliation gap as 4.5. The optimistic
increment of `outreach_recent_total_30d_count` happens before send
confirmation. Add to Step 5 the matching `closure_outreach_failed` /
`closure_outreach_bounced` clauses that decrement the counter, plus a
stale-pending sweep for tracking_ids with no engagement-stream
activity within 24 hours. The cross-recipe global counter makes this
even more important: a phantom contact recorded in this recipe
suppresses outreach for the patient in 4.4, 4.5, and 4.7 too.
- **L828** — TODO (TechWriter, MEDIUM per Expert Review A10): The current state machine
mutates state per-event; this is brittle in the face of out-of-order arrival,
retroactive corrections, late-arriving exclusions, and source-side restatements
that the prose names explicitly as production concerns. Add a paragraph naming
the event-replay pattern: events are stored in a per-(patient, gap) event log
ordered by event.timestamp; current state is computed by replaying the log
under the canonical-source rules from the registry; new events re-trigger
replay rather than mutating state directly. This guarantees out-of-order
arrivals produce the same final state regardless of receipt order, retroactive
corrections work via superseding markers, late-arriving exclusions can override
prior closures, and duplicate events are no-ops. The replay cost is small in
practice (most gaps have <10 events).
- **L940** — TODO (TechWriter, MEDIUM per Expert Review S1): Add identity-boundary
    //      checks here, mirroring the chapter pattern from 4.2/4.3/4.4/4.5.
    //      An override event arriving with mismatched (event.patient_id,
    //      event.measure_id) versus (rec.patient_id, rec.measure_id) should
    //      be dropped with an `override_identity_mismatch` metric, not written
    //      to the override audit trail under the event's claimed patient_id.
    //      Three downstream effects depend on this check: clinician-overrides
    //      is part of the audit trail; apply_suppression denies outreach for
    //      30-180 days; update_training_label feeds the urgency-model retrain
    //      pipeline. A patient-id mismatch contaminates all three.
- **L1029** — TODO (TechWriter, HIGH per Expert Review A3): Update `measure_id` from
`hedis-cdc-eye-exam` to `hedis-eed` (current NCQA naming after the CDC
parent measure was retired and split into EED/KED/GSD/BPD beginning HEDIS
MY 2022). Coordinate with the matching fix in The Technology section and
the Python companion's synthetic registry.
- **L1166** — TODO: the benchmarks above are illustrative ranges informed by published care gap and HEDIS-program literature; replace with measured results from your deployment, or with citations once verified. Be wary of vendor-published numbers that conflate gap-list generation with gap closure, or that report HEDIS impact without baseline comparison.
- **L1186** — TODO: confirm the current NCQA HEDIS update cadence and the CMS Stars technical-notes release pattern at the time of build.
- **L1194** — TODO (TechWriter): Specify the SageMaker training-job trigger mechanism and model-promotion path from training to inference. The architecture diagram shows "Periodic retrain" without an explicit trigger or promotion path; mirror the pattern flagged in 4.4 and 4.5 (EventBridge schedule or CloudWatch metric threshold for trigger; SageMaker Model Registry with canary run for promotion).
- **L1202** — TODO (TechWriter): Replace the string-concatenation tracking_id and briefing_id with opaque, non-reversible identifiers (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plain-text patient_ids and provider_ids embedded in tracking IDs (carried in email open-tracking pixels, SMS click-through links, EHR inbox URLs) are PHI leakage. Mirror the language from 4.4 and 4.5. Update the Expected Results sample tracking_ids accordingly.
- **L1206** — TODO (TechWriter): Add a paragraph specifying the cross-recipe priority arbitration. When 4.4, 4.5, 4.6, 4.7 all want to message the same patient and the global cap allows only one, what wins? Default proposal: weighted priority across recipes with a clinical-urgency tiebreaker, with explicit documentation that the operationally-attractive recipes (4.5 adherence reminders, 4.6 quality-measure-driven gaps near window close) cannot crowd out the high-clinical-urgency cohorts from 4.4 (DPP for newly diagnosed diabetes) or 4.6 (rising eGFR with no CKD conversation). Reference the cross-recipe orchestration discussed in 4.4 and 4.5.
- **L1210** — TODO (TechWriter): Specify the validator's pseudocode shape (four layers: schema, required disclosures and identifications, prohibited-claims regex/blocklist, approved-claims-only check against a per-measure approved-claims artifact). Specify failure handling: schema/length failures fall back to a templated default; clinical-claim or prohibited-claims failures defer the outreach with reason `validator_failed:<reason>` and flag for human review. Reference 4.4's and 4.5's parallel governance discussion.
- **L1214** — TODO (TechWriter): Add a paragraph on the SDOH-cohort PHI boundary in the cohort_features attribute. Cohort labels like "transportation_barrier" and "low_food_security" are PHI-equivalent and should follow the minimum-necessary principle. Engagement events should carry only the cohort axes the equity dashboard actually consumes, with narrower IAM scope than for general engagement data. Mirror the language flagged in 4.4 and 4.5.
- **L1220** — TODO (TechWriter): Specify DLQ coverage on all Lambda paths in the architecture, none of which the diagram currently shows: (a) Step Functions to Lambda pipeline: Catch on each Lambda task pointing to an SQS failure queue keyed on (run_date, stage, failure_reason); (b) Kinesis to closure-tracker Lambda: configure an OnFailure destination on the event source mapping pointing to SQS or SNS, with a CloudWatch alarm on DLQ depth; (c) Batch Transform job failures: SageMaker doesn't surface failures via DLQ; wire the Step Functions Catch to handle TransformJob failed states explicitly. A silently-dropped closure event is operationally damaging in this recipe (the chase team calls a patient who already closed the gap), so the DLQ coverage matters more here than in some prior recipes. Mirror the language from 4.4 and 4.5.
- **L1226** — TODO (TechWriter, MEDIUM per Expert Review A11): The `chase_period_weight_overrides` block is named here but not architected. Add a concrete schema sketch (start_date, end_date, weight_overrides, weight_caps, equity_floor_multipliers, monitoring_cadence_days) so a team building this recipe has the architectural primitive to implement. Without the primitive, year-end policy changes happen in a config-management process separate from the recommender, which means the year-end equity-monitoring tightening doesn't happen and the equity floors don't shift; both gaps produce the failure mode the Honest Take warns about. Specify that seasonal overrides go through the same governance review as base policy changes, and that equity floors should expand (not contract) during chase periods because chase periods disproportionately benefit operationally-easy cohorts.
- **L1244** — TODO: cite literature on outreach bundling effectiveness; the practice is widespread but published evidence is mixed.
- **L1248** — TODO (TechWriter, MEDIUM per Expert Review A6): The specialist-coordination
workflow named in this Variation requires a chained-closure state machine
that the core architecture doesn't show. Add the architectural primitive to
this file's Walkthrough (or a new subsection here): `recommendation-log` adds
chain_id (UUID), chain_position, chain_total, predecessor_recommendation_id.
Step 4 emits the first link of the chain (e.g., referral_generation) with
chain_position = 1; later links are not allocated until the predecessor
completes. Step 5 adds an intermediate-event handler: events that match a
chain link without closing the gap (e.g., referral_scheduled, referral_attended)
advance the chain_position and trigger the next link's allocation. Only the
final qualifying event (per the registry's numerator definition) closes the
gap. Reference Recipe 14.x for the full multi-stage stochastic-program version.
Same pattern flagged in 4.5 Finding A7.
- **L1296** — TODO: confirm the current names and locations of the aws-samples repos above; aws-samples and aws-solutions-library-samples have been reorganizing.
- **L1303** — TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs.
- **L1306** — TODO: confirm the current NCQA HEDIS landing page and access path at the time of publication.
- **L1307** — TODO: confirm the most current CMS landing page; the URL has moved repeatedly.

## python-example — `chapter04.06-python-example.md`

- **L3019** — TODO: confirm the current NCQA HEDIS update cadence and the CMS Stars technical-notes release pattern at the time of build.
