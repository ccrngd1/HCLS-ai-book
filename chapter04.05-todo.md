# Open TODOs — Recipe 4.5: Medication Adherence Intervention Targeting ⭐⭐

> Auto-extracted 2026-06-18 from inline source comments (35 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter04.05-medication-adherence-intervention-targeting.md`

- **L37** — TODO: confirm the current CMS Star Ratings cut-point methodology and the exact list of Part D adherence measures at the time of publication; CMS has revised this regularly and the 2023 Tukey-outlier change moved the cut points materially.
- **L60** — TODO: confirm the current CMS PQA (Pharmacy Quality Alliance) measure specifications and class definitions for the three Part D adherence measures at the time of publication.
- **L121** — TODO (TechWriter): Expert review chaining (MEDIUM). The cost-assistance to reminder chain is the recipe's primary example, but the architecture doesn't show how chaining is tracked. Add a small subsection (200-300 words) showing the state-machine version concretely: `predecessor_intervention_id` and `successor_intervention_id` fields on the catalog, `chain_position` and `chain_id` on the recommendation log, and an `intervention_completed` handler in Step 8 that triggers chain continuation. The simpler sequence version can be a one-paragraph alternative. Without this, the chain pattern stays a nice idea instead of an implemented feature.

## architecture — `chapter04.05-architecture.md`

- **L11** — TODO: confirm SageMaker Batch Transform's current HIPAA eligibility and the appropriate instance types for the model sizes implied here.
- **L33** — TODO: confirm current Bedrock service terms and the eligible-model list at the time of build; the BAA-covered model list has been evolving.
- **L37** — TODO (TechWriter): Expert review N17 (LOW). All vendor and partner integrations (manufacturer copay-card portals, foundation-grant programs, partner pharmacy APIs for med-sync, vendor pharmacist services, the channel-optimizer's downstream SMS gateway) credential through AWS Secrets Manager with KMS encryption and a per-environment rotation policy. Plain-text vendor API keys in Lambda environment variables are not acceptable. Cross-account access for vendor or partner integrations uses scoped IAM roles with a vendor-specific external ID.
- **L39** — TODO: confirm SES HIPAA eligibility and BAA scope at the time of build; verify Pinpoint SMS eligibility.
- **L139** — TODO (TechWriter): Expert review S6 (LOW). Pair these actions with one or two scoped Resource ARN examples so a reader copying into an IAM policy doesn't default to `Resource: *`. Same chapter-wide pattern flagged in 4.1, 4.2, 4.3, 4.4 reviews. Examples: `sagemaker:CreateTransformJob` on `arn:aws:sagemaker:{region}:{account}:transform-job/adherence-*`; `dynamodb:GetItem` on `arn:aws:dynamodb:{region}:{account}:table/patient-profile`; `bedrock:InvokeModel` on `arn:aws:bedrock:{region}::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0`; `kinesis:PutRecord` on `arn:aws:kinesis:{region}:{account}:stream/engagement-stream`.
- **L140** — TODO: confirm Bedrock + selected models are eligible at the time of build; verify Pinpoint and Connect HIPAA-eligible configurations; verify SageMaker Feature Store eligibility.
- **L142** — TODO (TechWriter): Expert review N15 (LOW). The endpoint list could be more explicit about SageMaker API surfaces: split `api.sagemaker` (control plane) from `runtime.sagemaker` (inference) and add `featurestore-runtime.sagemaker` for Feature Store online-store traffic. The Feature Store API has a separate surface from SageMaker Runtime, and online-store PutRecord / GetRecord traffic flows through it, not through Runtime.
- **L142** — TODO (TechWriter): Expert review N16 (LOW). State the egress posture explicitly: no `0.0.0.0/0` egress from any Lambda subnet. NAT egress restricted by security group to specific IP ranges or hostnames (manufacturer copay-card vendor portal, partner pharmacy API endpoints, foundation-grant program endpoints if applicable). All other outbound traffic must go through VPC endpoints. Same chapter-wide pattern flagged in 4.1, 4.3, 4.4 reviews.
- **L146** — TODO: replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator.
- **L180** — TODO: confirm the current names and locations of these aws-samples repos.
- **L271** — TODO (TechWriter): Expert review S5 (LOW) + Step 1 data quality gating (MEDIUM). The `data_quality_flag` is computed in Step 1 and propagated through the barrier-classifications table and engagement events, but no downstream component gates on it. The "Where it struggles" section names the gate as necessary, but the pseudocode in Steps 2, 3, 5, and 7 does not implement it. A reader copying the pseudocode literally produces confidently-wrong adherence labels for the cohorts most affected by data fragmentation (cash-pay, multi-pharmacy, recent plan change). Add explicit gating: cap barrier-classifier confidence on non-`complete` cases (Step 2), route low-quality cases to verification-first interventions or downweight (Step 3 or 5), and tailor patient-facing messages to acknowledge uncertainty rather than confidently asserting non-adherence (Step 7). Add a paragraph to the architecture pattern section naming the gate explicitly.
- **L356** — TODO (TechWriter): Expert review S1 (MEDIUM). Specify validate_barrier_review's
                // four-layer structure: (1) schema and taxonomy check,
                // (2) rationale length/structure, (3) rationale must cite
                // observable data points whose values match observed_data
                // within tolerance (the meaningful and non-trivial layer:
                // a substring match between rationale and serialized data
                // produces both false positives and false negatives), and
                // (4) prohibited content (PHI, prescriber names) in
                // rationale. Specify failure-handling: validator failure
                // means the LLM second opinion is dropped from the blended
                // classification, the failure is logged for prompt-
                // engineering review, and the case is flagged for
                // pharmacist-review queue with the LLM output included
                // for diagnostic purposes (not as a decision input).
- **L422** — TODO (TechWriter): Expert review S3 (MEDIUM). Adherence
            // outreach consent is multi-dimensional and the eligibility
            // filter should consult per-intervention consent metadata
            // before allowing an intervention to flow to the candidate
            // set. Three regulatory frameworks unavoidable in production:
            // (1) state boards of pharmacy regulate pharmacy-affiliated
            // reminders state-by-state with rules on disclosure
            // requirements, frequency caps, and approved-claims content;
            // (2) TCPA governs SMS and automated-voice outreach unless
            // the contact qualifies as treatment-related under HHS
            // guidance; (3) HIPAA marketing rules at 45 CFR 164.501 may
            // apply to manufacturer-funded interventions and to
            // cost-assistance navigation if the plan's facilitation is
            // classified as marketing. Add per-intervention consent
            // metadata to the catalog (treatment-related vs marketing,
            // channel-specific TCPA scope, state-specific applicability),
            // and consult the metadata in the eligibility filter:
            //   IF NOT member_consent.applies_to(
            //          intervention.consent_classification, member.state):
            //       CONTINUE
            // Engage privacy officer and pharmacy compliance lead on the
            // consent model for each intervention type before launch; do
            // not collapse to a single `outreach_consent` boolean.
- **L648** — TODO (TechWriter): Expert review A8 + A10 (HIGH/MEDIUM). The "30d" in the name implies a
            // rolling 30-day window, but the counter as implemented in
            // Step 7 increments forward without decay. After three
            // months of weekly runs, the counter no longer reflects
            // recent contact frequency, and the contact-cap deferral
            // becomes a lifetime-of-program filter rather than a 30-day
            // window. Pick a rolling-window pattern (DynamoDB TTL on
            // per-event rows, daily-bucket aggregation, or scheduled
            // decay Lambda) and document it. Coordinate with the
            // cross-recipe global counter TODO in Why This Isn't
            // Production-Ready.
- **L671** — TODO (TechWriter): Expert review A14 (MEDIUM). Same chapter-wide pattern as 4.4
            // Finding 13. The cohort-feature lookup runs per-(patient,
            // intervention) inside this loop; for a patient with N
            // candidate triples it repeats N times. Hoist the cache out
            // of the per-candidate loop and build it once per unique
            // patient_id before the allocation walk.
- **L707** — TODO (TechWriter): Expert review A7 (HIGH). The `top_up_from_cohort`
    // helper is referenced but its semantics are not specified. A reader
    // implementing this literally will either skip the second pass (floors
    // stay unfilled) or implement it inconsistently with the primary pass
    // (floors fill but with candidates that don't respect the per-patient
    // caps). Inline the second-pass logic with explicit semantics: re-walk
    // prioritized candidates filtered to the floor cohort, re-apply the
    // per-patient caps and cross-intervention exclusions, but bypass the
    // global capacity cap (the floor's reserved slots come out of global
    // capacity that the primary pass over-allocated to non-cohort
    // candidates). Document the trade-off between (a) reserving floor
    // slots up front by reducing global capacity before the primary pass
    // starts and (b) accepting that the primary pass may leave floors
    // unfilled in over-subscribed runs and surfacing that on the cohort
    // dashboard.
- **L846** — TODO (TechWriter): Expert review S4 (MEDIUM). regimen_simplification has no
                // PCP-review hold-time semantics. Unlike a text reminder
                // (which is parallel-track safe) or a pharmacist consult
                // (which sorts itself out at the consult), this
                // intervention requires the prescriber to act, and any
                // simultaneous patient-facing message creates the same
                // backfire pattern as 4.4 Finding 4 named for behavioral
                // health. Add a `pcp_review_policy` field to the
                // intervention catalog (`none`, `notify_parallel`,
                // `review_required_24h`, `review_required_72h_then_hold`)
                // and default regimen_simplification to
                // `review_required_72h_then_hold`. Update the orchestrator
                // to schedule the patient-facing message conditional on
                // PCP endorsement when the policy requires review. The
                // same field should override per-intervention defaults
                // for high-stakes therapeutic classes (anticoagulants,
                // anti-rejection medications, oral chemotherapy,
                // antiretrovirals, insulin during dose adjustment) via a
                // `medication_class_review_policy` lookup.
- **L892** — TODO (TechWriter): Expert review A8 (HIGH). The optimistic increment in Step 7 has the same reconciliation gap flagged in Recipe 4.4 Step 6. Add the matching reconciliation paths to Step 8: an `intervention_outreach_failed` / `intervention_outreach_bounced` clause that decrements `outreach_recent_30d_count`, plus a stale-pending sweep for tracking_ids with no engagement-stream activity within 24 hours. Without these, members with flaky channels accumulate phantom contact-cap consumption and get systematically excluded from future allocations they should still be eligible for. The asymmetry compounds across cohorts: members with reliable channels stay at the cap floor, members with flaky channels silently move past the cap floor and lose access to the program. Coordinates with Code Review Finding 1 (the boto3 ConditionExpression `:zero` placeholder bug in the Python companion).
- **L1117** — TODO: the benchmarks above are illustrative ranges informed by published adherence-program literature; replace with measured results from your deployment, or with citations once verified. Be wary of vendor-published numbers that conflate engagement metrics with adherence change, or that report aggregate uplift without confidence intervals.
- **L1137** — TODO: confirm the current PQA measure specifications and the link to the CMS Star Ratings methodology at the time of build.
- **L1141** — TODO: link to a published barrier-elicitation framework once verified; the field is converging on a few common taxonomies.
- **L1145** — TODO (TechWriter): Expert review A12 (MEDIUM). Specify the SageMaker training-job trigger mechanism and model-promotion path from training to inference. The architecture diagram shows "Periodic retrain" without an explicit trigger or promotion path; mirror the pattern flagged in 4.4 (EventBridge schedule or CloudWatch metric threshold for trigger; SageMaker Model Registry with canary run for promotion).
- **L1151** — TODO (TechWriter): Expert review A9 + A11 (MEDIUM). Add a paragraph clarifying the Star Ratings ethics. The documented temptation is to over-target the 75-79 PDC band because of the threshold-effect on Star Ratings. The recipe has called this out in The Honest Take, but the production deployment needs an explicit governance decision: how much of the allocator's capacity is reserved for the high-clinical-need / low-PDC cohort, regardless of Star Ratings impact, and how is that policy reviewed? Without an explicit floor, the optimization quietly drifts toward the financially-attractive band and the clinically-attractive band gets under-served. The cross-functional review committee owns this decision; document it in the policy version notes. Architect the floor as a first-class equity floor in the allocator: a `clinical_need_high_pdc_low` cohort definition (PDC 0.30-0.50 on Star-Ratings-tracked classes) with reserved capacity across pharmacist-consult and cost-assistance interventions. Additionally, show where the cycle plugs into the architecture: (1) need-score features (does the model take "months remaining in measurement year" as a feature, or does the cycle weighting live in the priority combiner?), (2) priority-combiner weights as a function of (PDC band, months-remaining), and (3) equity floors that reserve capacity for high-clinical-need cohorts independent of cycle. Add a per-patient `days_to_recover` gate that prevents the optimization from spending capacity on Star-Ratings-impossible cohorts. Reference Recipe 14.x for the LP version.
- **L1155** — TODO (TechWriter): Expert review A10 (MEDIUM). Add a paragraph on the global contact-cap reconciliation across recipes. The patient-profile table currently has separate counters per recipe (`outreach_recent_wellness_count` from 4.4; `outreach_recent_30d_count` here). Production: define a single `outreach_recent_total_30d_count` that all recipes update, plus per-recipe sub-counters for cohort attribution. Specify the policy: at most N total contacts per 30 days, of which at most M are high-touch, with priority-based eviction when caps would be exceeded. The shared-counter design is owned by Recipe 4.1 and consumed by 4.2, 4.4, 4.5, 4.6, and 4.7; no recipe should introduce a private counter without participating in the shared scheme. Reference the cross-recipe orchestration discussed in 4.4's variations.
- **L1159** — TODO (TechWriter): Expert review S1 (MEDIUM). Specify the validator's pseudocode shape (four layers: schema, required disclosures and identifications, prohibited-claims regex/blocklist, approved-claims-only check against a per-medication approved-claims artifact). Specify the failure-handling: schema/length failures fall back to `intervention.default_template`; clinical-claim or prohibited-claims failures defer the outreach with reason `validator_failed:<reason>` and flag for human review. Add a `funding_source` catalog field for manufacturer-funded reminders, with manufacturer-funded interventions binding to the manufacturer's approved-claims artifact rather than the plan's general list. Specify a separate `validate_pharmacist_brief` validator with different concerns (clinical accuracy, no fabricated context, contraindications referenced are genuine, no instructions outside pharmacist licensure). Reference 4.4's parallel governance discussion.
- **L1163** — TODO (TechWriter): Expert review S5 (LOW). Add a paragraph on the SDOH-cohort PHI boundary in the cohort_features attribute. Cohort labels like "low_food_security" and "moderate_food_security" are PHI-equivalent and should follow the minimum-necessary principle. Engagement events should carry only the cohort axes the equity dashboard actually consumes, with narrower IAM scope than for general engagement data. A new cohort axis added "for future use" is a privacy expansion that needs review. The 4.5-specific concern is that the recommendation log here joins (patient, therapeutic_class, barrier) with cohort labels; in a small geographic cohort, that join is reidentifying. Mirror the language flagged in 4.4.
- **L1167** — TODO (TechWriter): Expert review S2 (MEDIUM). Replace the string-concatenation tracking_id with an opaque, non-reversible identifier (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plain-text patient_ids and therapeutic_classes embedded in tracking IDs (carried in email open-tracking pixels, SMS click-through links, vendor outreach platform handoffs) are PHI leakage. Therapeutic_class in tracking_id is more sensitive than program_id was in 4.4: 'statins' implies cardiovascular disease, 'ras' implies hypertension, 'oral-diabetes' is unambiguous. Treat the tracking_id PHI exposure as one tier higher than the equivalent in the wellness recipe. Mirror the language from 4.4. Update the Expected Results sample tracking_ids accordingly.
- **L1169** — TODO (TechWriter): Expert review A13 (MEDIUM). Specify DLQ coverage on all Lambda paths in the architecture, none of which the diagram currently shows: (a) Step Functions to Lambda allocator: Catch on each Lambda task pointing to an SQS failure queue keyed on (run_date, stage, failure_reason); (b) Kinesis to attribution Lambda: configure an OnFailure destination on the event source mapping pointing to SQS or SNS, with a CloudWatch alarm on DLQ depth; (c) Batch Transform job failures: SageMaker doesn't surface failures via DLQ; wire the Step Functions Catch to handle TransformJob failed states explicitly. Specify per-stage idempotency keys: (run_date, patient_id, therapeutic_class, intervention_id) for the (Step 5/6/7) chain; (run_date, patient_id, therapeutic_class) for barrier classifications; (event_id, derived from tracking_id + event_type + timestamp) for engagement events with conditional-write semantics. A silently-dropped pharmacy_fill_observed event leaves the uplift training data wrong and the dashboards misleading, with no observable symptom until a quarterly evaluation regresses. Mirror the language from 4.4.
- **L1224** — TODO: confirm the current names and locations of the aws-samples repos above; aws-samples and aws-solutions-library-samples have been reorganizing.
- **L1231** — TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs.
- **L1234** — TODO: confirm the current PQA landing page and specification access path at the time of publication.
- **L1235** — TODO: confirm the most current CMS landing page; the URL has moved repeatedly.
