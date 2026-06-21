# Open TODOs: Recipe 4.7: Care Management Program Enrollment ⭐⭐⭐

> Auto-extracted 2026-06-18 from inline source comments (33 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter04.07-care-management-program-enrollment.md`

- **L161** — TODO: confirm current CMS TCM CPT code definitions and documentation requirements at the time of build.

## architecture — `chapter04.07-architecture.md`

- **L11** — TODO: confirm SageMaker Batch Transform's current HIPAA eligibility and the appropriate instance types for the model sizes implied here.
- **L37** — TODO: confirm current Bedrock service terms and the eligible-model list at the time of build.
- **L43** — TODO: confirm SES HIPAA eligibility and BAA scope at the time of build; verify Pinpoint SMS eligibility.
- **L47** — TODO: confirm AWS HealthLake's current pricing and HIPAA eligibility at the time of build.
- **L146** — TODO: pair these actions with one or two scoped Resource ARN examples. Same chapter-wide pattern flagged in 4.1 through 4.6 reviews.
- **L147** — TODO: confirm Bedrock + selected models, Pinpoint, Connect, and HealthLake eligibility at the time of build.
- **L153** — TODO: replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator.
- **L188** — TODO: confirm the current names and locations of these aws-samples repos.
- **L652** — TODO (TechWriter): Specify validate_briefing's
            // four-layer structure: (1) schema and length, (2) every
            // referenced clinical fact must appear in observed_context
            // (the LLM cannot hallucinate diagnoses or events), (3)
            // prohibited content (PHI not in source, prescriber names
            // other than the patient's, suggestions that override the
            // deterministic program assignment), (4) required notes
            // ("subject to clinical judgment", briefing is advisory,
            // patient consent required for enrollment). Failure
            // handling: replace with templated fallback that lists
            // the structured context without LLM narration; log for
            // prompt-engineering review.
- **L721** — TODO (TechWriter): Expert Review HIGH A1 (chapter-wide
    // pattern propagated unresolved through 4.4-4.7). Add a counter
    // decrement on the patient-profile attribute
    // cm_outreach_recent_30d_count for the terminal-unreachable,
    // declined, and deferred outcomes; otherwise the 4.7-specific
    // outreach budget accumulates phantom counter consumption that
    // silences the patient from future enrollment outreach for 30
    // days when the original outreach never reached the patient.
    // The pathology disproportionately affects cohorts with flaky
    // channels (transient housing, prepaid phones with intermittent
    // service, language-mismatch with assigned care manager) which
    // correlate with the cohorts the equity floors are trying to
    // protect. Coordinate the implementation with the parallel 4.4,
    // 4.5, 4.6 fixes; the chapter editor should land all four
    // together. The Python companion's record_outreach_attempt
    // unreachable-terminal branch already attempts the decrement but
    // currently fails (Code Review ERROR 2: missing :zero placeholder
    // and ExpressionAttributeNames=None); fix both at once. Also add
    // a stale-pending sweep Lambda (hourly): for outreach-state rows
    // where state == "queued" or state == "outreach_in_progress" and
    // created_at > 7 days ago with no engagement-event activity, mark
    // state = "stale_no_activity" and decrement the counter.
- **L943** — TODO (TechWriter): Expert Review HIGH A2. The
    // data_quality_flag is computed in Step 1, persisted to
    // patient-program-state, and named in Where It Struggles as a
    // signal that "downstream consumers (specifically the
    // disenrollment evaluator) should gate harder when quality is
    // low." The pseudocode below does not gate. For
    // cross_provider_fragmentation and multi_source_disagreement
    // patients, the engagement profile may appear worse than it
    // actually is because the patient is engaging through encounters
    // the recommender's data feed does not see; a
    // disenroll_for_no_engagement recommendation against fragmented
    // data has civil-rights implications when it concentrates in
    // protected cohorts (mobile populations, recent plan-changers,
    // patients seen across multiple practices). Add a
    // verify_engagement_first action that runs before
    // disenroll_for_no_engagement when state.data_quality_flag is in
    // {"cross_provider_fragmentation", "multi_source_disagreement"}.
    // Mirror the gating language at five additional sites: Step 2
    // response enrichment (widen uplift CI on non-complete cases),
    // Step 3 orchestrator (route fragmented-data patients through
    // verification-first allocation), Step 4 briefing
    // (data_quality_caveat in confidence_notes), Step 5 engagement
    // scoring (widen CI on the score; require multi-source
    // consistency for is_at_risk = true), and Step 6 cross-program
    // transition recommender (flag the recommendation with
    // data_quality_caveat). Same chapter-wide pattern as 4.5
    // Finding A2 and 4.6 Finding A2; the chapter editor should land
    // all three together.
- **L1028** — TODO (TechWriter): Specify validate_rationale layers
            // mirroring the chapter-wide validator pattern. Failures
            // fall back to a templated rationale that lists the
            // policy-rule trigger and the engagement-history evidence
            // without LLM narration.
- **L1302** — TODO (TechWriter): the briefing's social-context details (Medicare donut hole, grandchildren-care responsibilities, no home scale, Spanish-preferred written materials) are additive context not present in the opening vignette of Linda. Either fold the corresponding details into the vignette so the briefing reads as a faithful synthesis, or add a one-line note in The Problem section that the briefing in Expected Results includes care-management-relevant context surfaced from the patient profile beyond what the vignette establishes. Editor renamed Mr. Garcia to Linda for continuity (per expert review V2); the social-context reconciliation is the remaining piece.
- **L1403** — TODO: the benchmarks above are illustrative ranges informed by published care management and HEDIS-program literature; replace with measured results from your deployment. Be wary of vendor-published numbers that report "X% reduction in admissions" without matched-control comparison and without confidence intervals.
- **L1427** — TODO (TechWriter): Specify the SageMaker training-job trigger mechanism and model-promotion path for the response, enrollment-likelihood, and engagement-prediction models. With 3 model families × 5 programs = 15 model artifacts, the model registry and promotion automation matter more here than in earlier recipes. Mirror the EventBridge-trigger plus SageMaker-Model-Registry-with-canary-run pattern flagged in 4.4 through 4.6.
- **L1435** — TODO (TechWriter): Replace the string-concatenation tracking_id, briefing_id, decision_id with opaque, non-reversible identifiers (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plain-text patient_ids embedded in identifiers carried in care-manager queues, EHR inboxes, and engagement events are PHI leakage. Mirror the language flagged in 4.4, 4.5, 4.6. Update Expected Results sample identifiers accordingly.
- **L1439** — TODO (TechWriter): Add a paragraph specifying the cross-recipe priority arbitration for 4.7 specifically. Default proposal: 4.7 enrollment outreach has a separate contact budget from 4.4-4.6 routine outreach, with a hard cap on combined contacts within a rolling 30 days. The enrollment conversation is the highest-priority interaction in chapter 4 and should not be routinely deferred for adherence reminders. Document the cross-recipe arbitration in shared chapter-level config.
- **L1443** — TODO (TechWriter): Expert Review HIGH A3 (uniquely 4.7-specific).
The disenrollment-decisions and cross-program-transitions queues both
hold rows with human_review_pending: true and no SLA, no escalation,
no default action. Three pathologies follow: (a) patient remains
enrolled indefinitely while the disenrollment recommendation sits
unreviewed, consuming a slot another patient could use; (b) patient
is silently disenrolled when stale review eventually happens against
out-of-date engagement and clinical-event data; (c) clinical leads
with high case-load triage easy cases first, so complex cases (which
correlate with the cohorts the equity floors protect) sit longer in
the pending queue, producing disparate review-latency that the
disenrollment-rate equity dashboard does not catch. Add SLA-and-
escalation specification with per-action defaults that err toward
retention rather than disenrollment: 7-day review SLA for
disenroll_for_no_engagement (auto-defer 7 more days then
auto-default to extend_for_review with current data); 14-day review
SLA for disenroll_did_not_complete (auto-default to
graduate_with_partial_credit); 72-hour review SLA for
transition_to_higher_acuity (clinical-urgency driven; escalate to
medical director on miss); 14-day SLA for graduation transitions
(auto-expire); 7-day SLA for relapse transitions (escalate to
program manager on miss). Per-cohort review-latency monitoring goes
into the equity instrumentation alongside per-cohort disenrollment-
rate metrics; disparities in review latency are fairness signals
just like disparities in eventual outcome. Specify in the
architecture pattern; add the sweep_pending_decisions Lambda to
the pseudocode as a daily run.
- **L1473** — TODO (TechWriter): Add a paragraph on the SDOH-cohort PHI boundary. Cohort labels like "transportation_barrier" and "low_food_security" are PHI-equivalent and should follow the minimum-necessary principle. Engagement events should carry only the cohort axes the equity dashboard actually consumes, with narrower IAM scope than for general engagement data. Mirror the language flagged in 4.4 through 4.6.
- **L1479** — TODO (TechWriter): Code Review ERROR 1 (chapter-wide pattern in
the Python companion files for 4.6 and 4.7). The pseudocode
state_history.append(...) semantics are correct, but the
straightforward DynamoDB translation is *not* "ADD state_history
:history_event" because the ADD action only supports Number and Set
data types, not List. The correct UpdateExpression is
"SET state_history = list_append(if_not_exists(state_history, :empty),
:history_event)" with :empty defined as []. Update the Python
companion (chapter04.07-python-example.md) for all ten state-
transition update_item call sites; propagate the same fix to 4.6's
Python example. Add a one-line note here in the recipe's
Idempotency paragraph (or in a dedicated DynamoDB-gotchas paragraph)
warning readers who copy the pseudocode pattern that the literal
"append to history list" idiom requires the list_append +
if_not_exists pattern, not ADD.
- **L1495** — TODO (TechWriter): Specify DLQ coverage on all Lambda paths in the architecture. (a) Step Functions to Lambda pipeline: Catch on each Lambda task pointing to an SQS failure queue keyed on (run_date, stage, failure_reason); (b) Kinesis to state-machine-worker Lambda: configure an OnFailure destination on the event source mapping pointing to SQS or SNS, with a CloudWatch alarm on DLQ depth; (c) Batch Transform job failures: SageMaker doesn't surface failures via DLQ; wire the Step Functions Catch to handle TransformJob failed states explicitly. A silently-dropped state-transition event is operationally damaging in this recipe (a missed program_at_risk event delays retention; a missed program_enrolled event leaves the engagement scorer unarmed), so DLQ coverage matters substantively. Mirror the language from 4.4 through 4.6.
- **L1503** — TODO: cite published care-management caseload-and-burnout literature; the ratios vary by acuity but the patterns are consistent.
- **L1523** — TODO: cite published literature on predictive disenrollment-prevention; the patterns are documented in some plan publications but the evidence base is mixed.
- **L1562** — TODO: confirm the current names and locations of the aws-samples repos above; aws-samples and aws-solutions-library-samples have been reorganizing.
- **L1569** — TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs.
- **L1576** — TODO: confirm current CMS landing page; CMS reorganizes URLs frequently.
- **L1577** — TODO: confirm the current published-document URL at the time of build.
- **L1580** — TODO: confirm the current URL at the time of build; the alliance has rebranded multiple times.

## python-example — `chapter04.07-python-example.md`

- **L3752** — TODO: confirm the typical NCQA care management accreditation review cadence and the CMS care-management billing-code update cadence at the time of build.
- **L3754** — TODO: cite the EconML and DoWhy current versions and the appropriate CATE estimator for each program family.
- **L3782** — TODO: cross-reference the cross-recipe shared config object once it exists; mirror language from 4.4-4.6 reviews.
- **L3794** — TODO: confirm current CMS CCM and PCM CPT code definitions and TCM CPT codes 99495/99496 documentation requirements at the time of build.
