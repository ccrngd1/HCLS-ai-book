# Expert Review: Recipe 4.4 - Wellness Program Recommendations

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-16
**Recipe file:** `chapter04.04-wellness-program-recommendations.md`

---

## Overall Assessment

This recipe takes the personalization scaffolding established in Recipes 4.1 through 4.3 and graduates it to the harder problem class: causal recommendation under capacity constraints with multi-month feedback loops. The teaching is genuinely strong on the things teams most often get wrong. The eight-stage pipeline (eligibility → need → engagement → uplift → ranking → allocation → orchestration → feedback) is the right shape for a wellness recommender, the persuadables/sure-things/lost-causes/sleeping-dogs framing is the correct uplift mental model, and the equity discussion (engagement-prediction bias, outcome-prediction bias, capacity allocation as rationing) is more honest than most production wellness systems achieve in their first three years.

Several of the chapter-level production-hardening gaps the panel flagged across 4.1, 4.2, and 4.3 have been resolved in the main text rather than punted to "Why This Isn't Production-Ready":

- The recommendation log and engagement events are explicitly named as PHI ("a (member_id, program_id, score) row implicitly reveals clinical context"), with customer-managed KMS, CloudTrail data events, narrow IAM read scopes, and a defined retention period (90-180 days for individually-attributed; longer only after de-identification). That resolves 4.1 Finding 3, 4.3 Finding 1, and the chapter-wide PHI-in-personalization-records pattern.
- Engagement event integrity is enforced: `process_engagement_event` validates `event.member_id != rec.member_id` and drops mismatches. That resolves 4.2 Finding 3 and 4.3 Finding's identity-boundary pattern.
- Bedrock data-retention posture is stated explicitly, with a TODO to verify per-model coverage. That resolves 4.2 Finding 4.
- VPC endpoint list is thorough: DynamoDB, S3, Bedrock, Kinesis, KMS, CloudWatch Logs, SageMaker Runtime, Step Functions (`states`), EventBridge (`events`), STS, SES.
- A dedicated TODO in the Why This Isn't Production-Ready section enumerates DLQ coverage across Step Functions, Kinesis attribution, and Batch Transform job failures. That captures 4.1 Finding 6, 4.2 Finding 6, and 4.3's DLQ pattern as a chapter-wide concern rather than re-litigating it inline.
- The SDOH-cohort PHI sensitivity paragraph (TODO at the bottom) addresses one of the chapter-wide issues: cohort labels like `low_food_security` are derived from screening data and reveal sensitive life circumstances that, in small cohorts within specific geographies, are reidentifying.
- SES BAA scope, SageMaker Feature Store HIPAA eligibility, and Bedrock per-model eligibility are all flagged with appropriate TODO markers rather than asserted.

That said, three correctness gaps need attention before publication, and the medium and low items round out the review:

1. **The recipe consistently calls the diabetes prevention program "12-week" and claims it "follows the CDC curriculum."** The canonical CDC National DPP is a 12-month program (16 weekly core sessions plus 6 monthly post-core sessions, ~22-26 sessions total over a year). 12-week DPP variants exist in the market, but they are not "the CDC curriculum." This factual mischaracterization runs through The Problem, The Technology, the architecture discussion, and the medium-horizon evaluation discussion, and a healthcare reader will spot it immediately.

2. **The pseudocode for `score_eligible_population` serializes scoring across programs.** The outer `FOR each program in programs:` loop creates three Batch Transform jobs and then calls `wait_for_jobs([need_job, engagement_job, uplift_job])` before the next program starts. With 6 programs in the recipe's stated scale and ~10-15 minutes per Batch Transform job, this is a 60-90 minute pipeline that should finish in 10-15 minutes if programs are fanned out in parallel. The architecture diagram suggests parallel scoring per program, but the pseudocode reads serial; a reader following the pseudocode will ship a slow pipeline that doesn't match the prerequisites table's "30-90 minutes" claim.

3. **The optimistic contact-frequency counter is incremented at outreach send time but the reconciliation path on send failure is named without being specified.** The `tailor_and_dispatch` step calls `DynamoDB.UpdateItem(... ADD outreach_recent_wellness_count :one ...)` and the prose says "Update the contact-frequency counter optimistically. The actual send may fail; reconcile in the engagement-attribution step." Step 7 (`process_engagement_event`) does not show a decrement on `program_outreach_failed` or on bounce events. Members whose outreach never reached them still consume a slot in their cap, eventually pushing them past `MAX_WELLNESS_PER_MONTH` and excluding them from future outreach for outreach they never received. Compounded over months, this systematically silences members whose channel preferences are flaky (the same members whose outreach is hardest to deliver, often the same members the equity floors are trying to protect).

A handful of medium and low findings round out the review: the wellness consent regime doesn't address state-by-state and ADA/GINA-specific requirements, the tracking_id format embeds member_id in plain text, the outreach validator's approved-claims and prohibited-claims lists are mentioned but not specified, the VPC endpoint list misses Athena and Glue, the Step Functions retry semantics on partial Batch Transform completion aren't addressed, the PCP override has no pre-send hold-time semantics for higher-risk recommendations, and the chapter-wide IAM-ARN-scoping and `0.0.0.0/0`-egress patterns are repeated.

The voice is clean throughout: zero em dashes (verified), zero en dashes (verified), 70/30 vendor balance maintained, no marketing-language creep ("robust" appears three times, all technical: "robust, interpretable" describing causal forests, "doubly-robust estimation" as a real causal-inference term, and "robust to alternative matching specifications"). The Honest Take's "the data science is the easiest part" framing and the "wellness-program domain has a long history of vendors with thin evidence" closing are exactly the contrarian-but-correct CC tone the chapter has been collecting.

Priority breakdown: 0 critical, 3 high, 7 medium, 6 low.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA called out explicitly with HIPAA-eligibility TODOs for SageMaker Feature Store, SES, Bedrock per-model. The recipe doesn't pretend any of these are static.
- Customer-managed KMS keys for every PHI-containing store: DynamoDB tables (patient-profile, program-catalog, recommendation-log, engagement-events, pcp-overrides, program-outcome-evaluations), S3 (SSE-KMS bucket-level keys), Kinesis and Firehose (server-side encryption), SageMaker training and inference (VPC-only, KMS keys for model artifacts and Feature Store offline storage), Lambda log groups KMS-encrypted.
- Recommendation log and engagement events explicitly named as PHI: *"The recommendation log and engagement events are PHI: a (member_id, program_id) row implicitly reveals clinical context (the member meets DPP eligibility, the member is being targeted for a behavioral health program). Treat as PHI from day one."* That is the chapter-wide pattern from 4.1 (reminder decisions), 4.2 (education recommendations), and 4.3 (search log) applied at the right point.
- Retention policy stated: *"Define explicit retention periods (90-180 days for individually-attributed recommendation logs; longer retention only after de-identification). Add a CloudWatch alarm on the deletion job and a documented re-attestation cadence."*
- Engagement-event integrity check: `IF event.member_id != rec.member_id: LOG("event member_id mismatch with recommendation; dropping")`. Same pattern as 4.3's resolution.
- CloudTrail data events on the patient-profile, program-catalog, recommendation-log, and engagement-events tables, plus the S3 buckets for feature snapshots and recommendation outputs.
- The Bedrock paragraph explicitly says: *"Confirm in your service terms that prompts and completions are not used to train the underlying foundation models and are not retained beyond the request lifecycle."* That continues the 4.3 resolution.
- LLM prompt construction pseudocode explicitly excludes raw identifiers: *"pass cohort and clinical attributes the model needs to tailor, but do not pass raw identifiers (member_id, name, phone) into the LLM. The LLM gets de-identified context; identifiers are reattached after."* Strong pattern.
- SDOH-cohort PHI sensitivity is acknowledged in the production-gaps TODO with appropriate "limit cohort axes to the minimum needed" guidance.
- The Honest Take flags FDA attention on hallucinated clinical claims in patient-facing outreach: *"Hallucinated clinical claims in patient-facing outreach are an FDA-attention failure mode; treat the validator as production-critical, not a nice-to-have."*

### Finding 1: Wellness Consent Regime Doesn't Address State-Specific and Federal Wellness-Program Statutory Requirements

- **Severity:** MEDIUM
- **Expert:** Security (compliance accuracy)
- **Location:** Stage 1 (Eligibility) prose: *"must have given consent for outreach if your jurisdiction or plan policy requires explicit consent"*; Step 5 pseudocode (`enforce_outreach_caps`), the consent verification block; "Why This Isn't Production-Ready," no paragraph on consent regime.
- **Problem:** The recipe acknowledges consent requirements vary by jurisdiction but does not name the relevant federal frameworks that govern employer-sponsored wellness programs and health-plan-sponsored wellness outreach. Three frameworks are unavoidable in production:

  1. **ADA (Americans with Disabilities Act) wellness program rules.** Voluntary participation is a regulatory requirement; outreach that is perceived as coercive (e.g., financial penalties for non-participation, repeated unsolicited contact) crosses ADA lines. The EEOC has been actively litigating in this space.
  2. **GINA (Genetic Information Nondiscrimination Act).** Wellness programs that incorporate family-history information (which the eligibility criteria often do for DPP: "family history of diabetes") must handle genetic information separately, with explicit GINA-compliant authorizations. The recipe's eligibility criteria reference family history without addressing GINA's separate-consent requirement.
  3. **State-specific consent regimes.** California (CCPA/CPRA wellness program provisions), Washington (My Health My Data Act, which regulates consumer health data outside HIPAA), and several other states have wellness-program-specific provisions that require explicit, granular consent and the right to withdraw without penalty.

  The recipe correctly notes that consent verification happens in Step 5 (`enforce_outreach_caps`) but treats it as a single boolean (`member_profile.wellness_consent.active`). Production wellness consent is multi-dimensional: ADA voluntary-participation, GINA-specific authorization for family-history use, state-specific opt-in vs opt-out, channel-specific consent (email vs SMS vs telephonic), and program-specific consent (a member who consented to weight management has not consented to behavioral health outreach). Collapsing all of this into one flag is the kind of thing that produces an EEOC complaint two years after launch.

- **Fix:** Two changes.

  1. Replace the single `wellness_consent.active` check with a multi-dimensional consent model. Pseudocode example:

     ```
     IF NOT member_profile.consent.ada_voluntary_participation:
         deferred.append({ row, reason: "ada_voluntary_participation_not_confirmed" })
         CONTINUE
     IF program.uses_family_history AND NOT member_profile.consent.gina_authorization:
         deferred.append({ row, reason: "gina_authorization_required" })
         CONTINUE
     IF NOT member_profile.consent.programs.get(row.program_id, default=False):
         deferred.append({ row, reason: "program_specific_consent_missing" })
         CONTINUE
     IF NOT member_profile.consent.channels.get(channel_for_member, default=False):
         deferred.append({ row, reason: "channel_consent_missing" })
         CONTINUE
     ```

  2. Add a paragraph in "Why This Isn't Production-Ready" naming the consent regime explicitly: *"Wellness consent is not a single flag. ADA voluntary-participation, GINA family-history authorization where applicable, state-specific consent regimes (California CCPA/CPRA, Washington My Health My Data, others), program-specific consent, and channel-specific consent are each their own field. Collapsing them into one boolean produces an EEOC or state-AG enforcement risk that may not surface until two years after launch. Engage employee benefits counsel and your privacy officer on the consent model before the first run."*

### Finding 2: Tracking ID Embeds Member ID in Plain Text Across the Entire Pipeline

- **Severity:** MEDIUM
- **Expert:** Security (PHI minimization)
- **Location:** Step 6 (`tailor_and_dispatch`): `tracking_id = "wellness-" + row.run_date + "-" + row.member_id + "-" + row.program_id`; "Expected Results" sample showing `"tracking_id": "wellness-2026-05-04-mem-000482-prog-dpp"`.
- **Problem:** The tracking_id is constructed by string-concatenating `run_date`, `member_id`, and `program_id`. It then flows into:

  1. The Kinesis engagement-event stream (`program_recommended` event payload).
  2. The recommendation log in DynamoDB.
  3. The CareTeamInbox PostNote call (`tracking_id = "wellness-pcp-" + ...`).
  4. The Bedrock InvokeModel request body, indirectly via the orchestrator's `tracking_id` parameter being passed through.
  5. Email open-tracking pixels and SMS click-through links rendered by the channel optimizer (Recipe 4.1's territory but the tracking_id flows through it).
  6. Vendor outreach platforms if the orchestrator hands off to one.
  7. CloudWatch logs every time any of those Lambdas log the tracking_id during processing.

  Member_id in plain text inside a tracking string used across systems is a PHI-leakage path. Three failure modes:

  - **Email open-tracking pixels.** Tracking pixels are loaded by member email clients with the tracking_id in the URL. The email-vendor's analytics, the member's email client, any intermediary email-security or email-tagging tool sees the URL. If the vendor isn't BAA-covered for the analytics path, that's a PHI exposure.
  - **SMS click-through links.** Same problem; many SMS gateways log redirect URLs.
  - **Vendor outreach platform handoff.** If the channel optimizer hands off to a vendor outreach platform that isn't BAA-covered for the tracking_id field, the member_id leaks.
  - **CloudWatch logs.** Every Lambda that logs the tracking_id at INFO level (the default for "request received" boilerplate) creates a log entry with member_id in the message body. The "Don't log member_id with clinical context" guidance the recipe gives elsewhere is undone by the tracking_id design.

  The cleaner pattern is an opaque tracking_id (a UUID or HMAC of the composite) that maps to (member_id, run_date, program_id) via a join in the recommendation log. The tracking_id stays opaque on the wire; only systems with read access to the recommendation log can resolve it back to member identity.

- **Fix:** Replace the string-concatenation tracking_id with an opaque identifier.

  ```
  tracking_id = secure_random_uuid()         // or HMAC-SHA256 over (run_date, member_id, program_id) with a per-environment secret
  recommendation_log.put({
      tracking_id: tracking_id,
      run_date:    row.run_date,
      member_id:   row.member_id,
      program_id:  row.program_id,
      ...
  })
  ```

  Update the Expected Results sample: `"tracking_id": "rec-7f3b2c8e-4a91-4d12-9ce4-1f8a3b5d2e7c"` rather than `"wellness-2026-05-04-mem-000482-prog-dpp"`. Add a sentence in the security walkthrough: *"Use opaque, non-reversible tracking identifiers on outbound channels and engagement events. Member identity is reattached only inside systems with read access to the recommendation log. Plain-text member identifiers in URLs, SMS payloads, and vendor handoffs are PHI leakage even when the surrounding context is innocuous."*

### Finding 3: Outreach-Message Validator Approved-Claims and Prohibited-Claims Lists Mentioned but Not Specified

- **Severity:** MEDIUM
- **Expert:** Security (regulatory)
- **Location:** Step 6 pseudocode (`tailor_and_dispatch`): `validate_outreach_message(tailored, program)`; "Why This Isn't Production-Ready," the *Outreach-message governance* paragraph.
- **Problem:** The pseudocode calls `validate_outreach_message(tailored, program)` and the prose says *"check the schema, check that required disclosures are present, check that the message doesn't contain any clinical claims that weren't in the prompt."* The Why This Isn't Production-Ready section names the gap: *"the validation needs a list of approved program claims, an explicit prohibited-claims list (e.g., no curative-language overstatement, no implicit guarantees of outcome), and a sampling-and-review process."* Acknowledging the gap is appropriate, but the validator is the FDA-attention surface the Honest Take itself flags, and the recipe leaves it as a black box.

  Three production realities the recipe should specify:

  1. **What "schema check" means specifically.** JSON shape conformance is one layer; semantic checks (subject_line under 78 characters for email-client compatibility, opening_line non-empty, language code matches `preferred_language`) are another layer; clinical-content checks (no medication names, no dosing, no diagnostic claims, no "this program will cure your X" language) are the safety-relevant layer.
  2. **Where the approved-claims list lives.** A reader will assume it's hardcoded in the validator Lambda; production reality is that the list is owned by clinical/compliance and stored as a versioned artifact (S3 with object versioning, DynamoDB with version attributes, or a Git-managed config baked into a Lambda layer). The validator reads the current version per request.
  3. **What happens on validator-fail.** The pseudocode just calls `validate_outreach_message(tailored, program)` with no return-handling. Three reasonable behaviors: fall back to `program.default_template`, defer the outreach (similar to cap deferral with `reason: "validator_failed"`), or human-review queue. Each has different operational implications and the recipe should pick one.

  This is MEDIUM rather than HIGH because the Why This Isn't Production-Ready section names the gap. But the validator is described as production-critical (correctly), and the recipe should at least specify the validator's pseudocode shape.

- **Fix:** Two changes.

  1. Expand the validator into its own pseudocode block:

     ```
     FUNCTION validate_outreach_message(tailored, program):
         // Layer 1: schema and shape checks
         IF NOT matches_schema(tailored, OUTREACH_SCHEMA):
             RETURN ValidationResult(passed=false, reason="schema_violation")
         IF len(tailored.subject_line) > 78 OR len(tailored.subject_line) == 0:
             RETURN ValidationResult(passed=false, reason="subject_line_length")

         // Layer 2: required disclosures
         FOR each required_disclosure in program.required_disclosures:
             IF required_disclosure NOT IN tailored.closing_call_to_action:
                 RETURN ValidationResult(passed=false, reason="missing_disclosure",
                                          detail=required_disclosure)

         // Layer 3: prohibited-claims check (approved-claims list owned by compliance,
         // versioned, loaded at function init from a config store)
         FOR each prohibited_pattern in PROHIBITED_CLAIMS_LIST:
             IF prohibited_pattern matches tailored.program_pitch:
                 RETURN ValidationResult(passed=false, reason="prohibited_claim",
                                          detail=prohibited_pattern.label)

         // Layer 4: hallucinated-clinical-claims check
         FOR each clinical_claim_in_message in extract_clinical_claims(tailored):
             IF clinical_claim_in_message NOT IN program.approved_clinical_claims:
                 RETURN ValidationResult(passed=false, reason="unapproved_clinical_claim",
                                          detail=clinical_claim_in_message)

         RETURN ValidationResult(passed=true)
     ```

  2. Specify the failure-handling behavior:

     ```
     validation = validate_outreach_message(tailored, program)
     IF NOT validation.passed:
         emit_metric("outreach_validation_failed", value=1, dimensions={
             reason: validation.reason,
             program_id: row.program_id
         })
         IF validation.reason in ["schema_violation", "subject_line_length"]:
             tailored = render_default_template(program, prompt_context)   // safe fallback
         ELSE:
             // Clinical or prohibited-claims failure: defer and flag for review
             deferred.append({ row, reason: "validator_failed:" + validation.reason })
             continue_to_next_row()
     ```

  Add a sentence to the production-gaps section: *"The approved-claims and prohibited-claims lists are versioned artifacts owned by clinical and compliance, stored in a config store (S3 with object versioning is sufficient), and loaded at validator-init from the current version. A change to the lists triggers a re-validation pass over the most recent N days of outreach to catch any messages that would now fail; manually-approved exceptions are logged for audit."*

### Finding 4: PCP Override Path Has No Pre-Send Hold-Time Semantics for Higher-Risk Recommendations

- **Severity:** MEDIUM
- **Expert:** Security (clinical workflow safety)
- **Location:** Step 6 pseudocode (`tailor_and_dispatch`), the PCP-briefing path; "Why This Isn't Production-Ready," the *PCP-override workflow integration* paragraph.
- **Problem:** The recipe describes PCP alerts as a parallel notification: the orchestrator queues the outreach via the channel optimizer, and *also* generates a PCP briefing if `program.pcp_alert_enabled`. The two go out simultaneously. The PCP override is a feedback signal that flows back through the engagement stream; if the PCP declines after the member outreach already went, the harm is already partially done.

  For lower-stakes programs (sleep improvement, nutrition coaching) this is fine: the PCP can endorse retroactively, and a member who got an outreach for a program their PCP didn't think was right just ignores it. For higher-stakes programs the calculus is different:

  - **Behavioral health programs** for a member managing fragile mental health (the recipe's own "sleeping dogs" example): an outreach for a stress-reduction program to a member whose PCP knows is in acute crisis can backfire seriously.
  - **Smoking cessation in pregnancy.** Varenicline-class smoking cessation messaging without PCP context can lead to drug-interaction confusion or distress.
  - **Weight management programs** for a member with a history of disordered eating, where their PCP knows the eating-disorder context but the recommender doesn't.

  Production wellness systems often differentiate program tiers by PCP-review-required vs PCP-notify-only. The recipe doesn't make this distinction. The catalog has `program.pcp_alert_enabled` (notify only), but no `program.pcp_review_required_before_send` (hold for N days awaiting PCP approval before outreach goes).

- **Fix:** Two changes.

  1. Add a `pcp_review_policy` field to the program catalog with values:

     - `none`: no PCP notification (low-stakes programs)
     - `notify_parallel`: PCP gets a briefing at the same time as the member outreach (current behavior, appropriate for moderate-stakes programs)
     - `review_required_24h`: outreach is held for 24 hours; PCP can decline before send; default to send if no response
     - `review_required_72h_then_hold`: outreach is held for 72 hours; if PCP doesn't respond, escalate to care team rather than auto-sending

  2. Update the orchestration pseudocode to respect the policy:

     ```
     IF program.pcp_review_policy == "review_required_24h":
         CareTeamInbox.PostNote(...)
         schedule_outreach_with_delay(row, 24_hours, conditional_on_no_pcp_decline)
     ELSE IF program.pcp_review_policy == "review_required_72h_then_hold":
         CareTeamInbox.PostNote(...)
         schedule_outreach_with_delay(row, 72_hours, conditional_on_pcp_endorse)
     ELSE IF program.pcp_review_policy == "notify_parallel":
         ChannelOptimizer.QueueOutreach(...)
         CareTeamInbox.PostNote(...)
     ELSE:
         ChannelOptimizer.QueueOutreach(...)
     ```

  Add a paragraph to the production-gaps section identifying which programs typically warrant which policy. Reference Recipe 4.10 (Dynamic Treatment Regime Recommendation) as the place where pre-send PCP-approval workflows graduate to a more formal state-machine.

### Finding 5: IAM "Never `*`" Stated Without Scoped ARN Examples (Chapter-Wide)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites, "IAM Permissions" row.
- **Problem:** Same finding as 4.1 Finding 5, 4.2 Finding 5, 4.3 Finding 5. The TODO already in the recipe acknowledges the chapter-wide pattern. The fix is to either (a) put one or two scoped resource ARN examples inline, or (b) consolidate into a chapter preface section that all recipes reference.
- **Fix:** Pair each action with one example ARN. Examples: `sagemaker:CreateTransformJob` on `arn:aws:sagemaker:{region}:{account}:transform-job/wellness-*`; `dynamodb:GetItem` on `arn:aws:dynamodb:{region}:{account}:table/patient-profile`; `bedrock:InvokeModel` on `arn:aws:bedrock:{region}::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0`; `kinesis:PutRecord` on `arn:aws:kinesis:{region}:{account}:stream/engagement-stream`. A coordinated chapter-wide fix would be more durable.

### Finding 6: SDOH-Cohort PHI Sensitivity TODO Should Be Promoted Into Main Text

- **Severity:** LOW
- **Expert:** Security
- **Location:** TODO at the bottom of "Why This Isn't Production-Ready": *"Add a paragraph clarifying the SDOH-cohort PHI boundary specifically..."*
- **Problem:** Not a finding against the content; a finding against the placement. The SDOH-cohort PHI consideration is the strongest example in this recipe of "cohort labels are PHI even when stripped of direct identifiers." It belongs in the main Privacy paragraph, not as a TODO. The substance of the TODO is correct and complete: cohort labels like `low_food_security` are derived from screening data, are reidentifying for small cohorts in specific geographies, should be limited to the minimum needed for fairness monitoring, and access should be narrower than for general engagement data. Promote the TODO content into the main *Privacy in the recommendation log and engagement events* paragraph.
- **Fix:** Move the TODO content inline into the *Privacy in the recommendation log and engagement events* paragraph. Optionally add: *"Apply the minimum-necessary principle to cohort axes themselves: only carry cohort attributes through to the engagement event that the equity dashboard actually consumes. A new cohort axis added because 'it might be useful someday' is a privacy expansion that should be reviewed."*

---

## Architecture Expert Review

### What's Done Well

- The eight-stage pipeline (eligibility → need → engagement → uplift → ranking → allocation → orchestration → feedback) is the right shape for the problem class. The eligibility-vs-optimization split is articulated as a correctness boundary, not a feature.
- Hard filters (clinical eligibility, plan active, consent, prior-state exclusions) applied BEFORE scoring. Same correct ordering as 4.1, 4.2, 4.3.
- The persuadables / sure-things / lost-causes / sleeping-dogs framing is the correct uplift mental model and the recipe is honest about how teams confuse engagement prediction with uplift.
- The capacity-aware allocation discussion correctly frames the problem as a constrained optimization with greedy as the starter and integer programming as the graduation path (Recipe 14.x territory). The two-pass allocator (greedy primary plus equity-floor top-up) is the right shape for the starter.
- Equity floors framed as a policy lever, not a hyperparameter: *"At least N percent of seats reserved for members in the lowest-engagement-history quartile. Document the policy. Audit it."* Same pattern as 4.3's structural-fairness framing.
- LLM scope kept tight: tailoring outreach text and PCP talking-point generation. Not picking the program. Not making clinical decisions. The architecture-pattern sentence *"the recommender picks the program. The LLM packages it"* is the right one-line framing.
- Multi-horizon feedback correctly partitioned: short-horizon (engagement) feeds engagement-prediction model, medium-horizon (completion) feeds uplift model, long-horizon (clinical outcomes) feeds program-level ROI. Each on a different cadence.
- DLQ coverage flagged in production-gaps TODO with the right level of specificity: Step Functions task-level Catch to SQS keyed on `(run_date, stage, failure_reason)`; Kinesis attribution Lambda OnFailure destination; Batch Transform failure modes routed via Step Functions Catch. The "silently-dropped engagement event leaves training data incomplete with no observable symptom until quarterly evaluation regresses" framing is the right insight.
- SageMaker Batch Transform chosen over real-time endpoint with the right rationale (cost, batch nature of the workload). The training-vs-inference split is clean.
- Reusing the patient-profile, engagement bus, and feature store from 4.1 / 4.2 / 4.3 keeps the chapter cohesive and reduces operational footprint.
- Cross-recipe sequencing: forward-references to 4.5 (adherence) and 4.7 (care management) explicitly state that the uplift-and-allocation pattern transfers, with 4.7 graduating the allocator to LP-based optimization. Good chapter-level architecture story.

### Finding 7: DPP Duration Consistently Misrepresented as 12 Weeks Instead of 12 Months

- **Severity:** HIGH
- **Expert:** Architecture (clinical accuracy)
- **Location:** "The Problem" paragraph 1 (*"a 12-week diabetes prevention program (DPP) that follows the CDC curriculum"*); "The Problem" paragraph 2 (*"By week eight, 95 people are still active. By week twelve, 47 people complete the program"*); "The Technology" paragraph 4 (*"A patient enrolling in a 12-week DPP, attending sessions, losing weight, and... not progressing to type 2 diabetes within three years"*); "Capacity Constraints" subsection (*"12-week cohorts starting on a fixed schedule"*); "Feedback is multi-horizon" paragraph (*"Medium-horizon completion data (12 weeks for DPP, 6 to 12 months for smoking cessation outcomes)"*).
- **Problem:** The CDC National Diabetes Prevention Program (CDC NDPP, also known as PreventT2) is a [12-month lifestyle change program](https://www.cdc.gov/diabetes-prevention/php/lifestyle-change-resources/about-preventt2-curriculum.html), not a 12-week one. The standard CDC NDPP structure is 16 weekly core sessions in months 1-6, followed by 6 monthly post-core sessions in months 7-12, for a total of approximately 22-26 sessions over a year. CDC recognition standards explicitly require the 12-month duration; a 12-week program cannot earn CDC recognition for full DPP delivery.

  The recipe's framing is internally inconsistent in a way that compounds the problem: it says the program *"follows the CDC curriculum"* AND *"is 12 weeks"* AND *"completion rate is in the 40 to 50 percent range of starters."* The 40-50% completion benchmark the recipe cites is from CDC NDPP retention literature, which measures retention over 12 months, not 12 weeks. Splicing the 12-week duration onto the 12-month completion benchmark misrepresents both.

  Real-world DPP variants do exist (Omada Health, Livongo, Solera, Noom Health, and others have abbreviated and modular variants), but they are NOT "the CDC curriculum"; they are vendor curricula that claim DPP-equivalence with varying degrees of CDC recognition. The distinction matters for plans contracting with vendors based on CDC recognition status (which has implications for Medicare DPP coverage and many state DPP coverage rules).

  The downstream architectural impact: the recipe's "Medium-horizon completion data" feedback discussion implies the uplift model gets retraining signals every 12 weeks per cohort. If the actual completion horizon is 12 months, the uplift retraining cadence is 4x slower than the recipe implies. That's a material architectural difference for retraining infrastructure capacity planning and for the "by the time you have evidence the program isn't working it's been running for a year" framing in the production-gaps section (which is actually right at 12 months but conflicts with the 12-week framing elsewhere).

  This is HIGH because (a) a healthcare reader will spot the error immediately and lose trust in the rest of the recipe, (b) the misrepresentation is consistent across the recipe rather than an isolated typo, (c) the 12-week duration is woven into the architectural feedback-loop discussion in a way that affects the recipe's claims about retraining cadences and ROI evaluation timelines, and (d) the recipe explicitly cites the CDC NDPP as the canonical reference in Additional Resources, so the inconsistency is not innocuous.

- **Fix:** Three changes.

  1. **Replace every "12-week DPP" reference with "12-month DPP"** (or just "DPP" without a duration where the duration isn't load-bearing). The Problem section's vignette should change to: *"a 12-month diabetes prevention program (DPP) that follows the CDC curriculum (16 weekly core sessions plus monthly post-core sessions)"*.

  2. **Update the completion-rate vignette.** The "by week eight, 95 people active. By week twelve, 47 complete" text should reflect the actual 12-month structure: *"By month three, 95 people are still active. By month twelve, 47 people complete the program."* The 40-50% completion rate at 12 months is the CDC NDPP retention benchmark; preserve that.

  3. **Fix the medium-horizon feedback-cadence claim.** Change *"Medium-horizon completion data (12 weeks for DPP, 6 to 12 months for smoking cessation outcomes)"* to *"Medium-horizon completion data (12 months for DPP completion, 6 to 12 months for smoking cessation quit-status)."* If the recipe wants to call out an earlier intermediate signal, note that DPP retention at month 6 (end of core phase) is a useful intermediate proxy for ultimate completion.

  4. **Add a note** on the vendor-vs-CDC-curriculum distinction. *"Several vendors offer DPP-style programs of shorter duration. The CDC's National DPP recognition standards require 12-month delivery; abbreviated variants are not 'the CDC curriculum' even when they cite it. The architecture in this recipe is duration-agnostic; align the catalog's `cohort_cadence` field with whichever curriculum your contracted vendor delivers, and align the medium-horizon feedback cadence with that vendor's actual completion window."*

  5. **Update the cohort-cadence discussion** elsewhere: *"Many programs (DPP especially) are cohort-based: 12-week cohorts"* should become *"Many programs (DPP especially) are cohort-based: cohorts that span the program's full duration (12 months for CDC-recognized DPP)."* The cohort-start-cadence point (members joining month 3 of a cohort either wait or get routed elsewhere) survives intact; the cohort *length* is what changes.

### Finding 8: `score_eligible_population` Pseudocode Serializes Across Programs; Architecture Diagram Implies Parallel Fan-Out

- **Severity:** HIGH
- **Expert:** Architecture (correctness, performance)
- **Location:** Step 2 pseudocode (`score_eligible_population`):

  ```
  FOR each program in programs:
      ...
      need_job = SageMaker.CreateTransformJob(...)
      engagement_job = SageMaker.CreateTransformJob(...)
      uplift_job = SageMaker.CreateTransformJob(...)
      wait_for_jobs([need_job, engagement_job, uplift_job])
  ```

  Architecture diagram shows three Batch Transform jobs (`need-scorer`, `engagement-predictor`, `uplift-estimator`) fanning out from the eligible-members S3 prefix in parallel.
- **Problem:** The pseudocode's outer `FOR each program in programs:` loop creates 3 jobs and then waits for all 3 before continuing to the next program. Programs are scored serially. With 6 programs at ~10-15 minutes per Batch Transform job (the recipe's stated `ml.m5.large` and `ml.m5.xlarge` instances on ~80K members, with the uplift estimator being heavier), this is 60-90 minutes of serialized execution.

  The architecture diagram (and the prerequisites table's "30-90 minutes end-to-end" claim) imply parallel fan-out across programs. If a reader follows the pseudocode literally and wires this up in Step Functions as a sequential `Map` iteration with `MaxConcurrency=1`, they get a slow pipeline that costs the same as the parallel version (Batch Transform pricing is per-instance-hour regardless of parallelism) but takes 6x longer.

  Two failure modes:

  1. **Pipeline runs hit the cohort-cycle calendar window.** The recipe says cohort cadence drives the schedule (DPP cohort starts the first Monday of the month; smoking cessation rolls weekly). If a weekly run on Sunday night takes 6 hours instead of 1, allocations may not be ready for Monday morning's outreach send.
  2. **Failure of one program's uplift job stalls the rest.** A `wait_for_jobs([...])` failure for program 1's uplift means programs 2-6 don't even start. The Step Functions Catch flagged in the production-gaps TODO would handle this, but the pseudocode doesn't show it; a reader implementing the pseudocode literally and adding error handling later may miss the cross-program isolation.

  This is HIGH because (a) the pseudocode disagrees with the architecture diagram, (b) the runtime claim in the prerequisites table is plausible only with parallel execution, and (c) the bug is subtle enough that a reader implementing the pseudocode literally will not realize they shipped a 6x-slow pipeline.

- **Fix:** Restructure Step 2 to parallelize across programs. Two implementation options to document:

  1. **Step Functions Map state with parallel iteration.** The outer iteration over programs runs as a Map with `MaxConcurrency=N` (where N is the program count, typically 6-10). Each iteration creates 3 Batch Transform jobs in parallel via a parallel sub-state. All 3*N jobs run concurrently subject to the Map's concurrency cap.

  2. **Fanned-out invocation with single consolidation.** All 3*N jobs are submitted up front; a single `wait_for_all_jobs` polls them concurrently; consolidation runs once after all complete.

  Updated pseudocode shape:

  ```
  FUNCTION score_eligible_population(programs, run_date):
      // Submit all jobs in parallel, do not wait between programs
      job_handles = []
      FOR each program in programs:
          eligible_path = ...
          job_handles.append(SageMaker.CreateTransformJob(NEED model, ...))
          job_handles.append(SageMaker.CreateTransformJob(ENGAGEMENT model, ...))
          job_handles.append(SageMaker.CreateTransformJob(UPLIFT model, ...))

      // Wait for all 3 * N jobs in a single concurrent poll
      wait_for_jobs(job_handles)

      // After all programs scored, consolidate
      consolidate_scores(programs, run_date)
  ```

  Add a sentence: *"Submit all per-program jobs in parallel. The total wall-clock time is bounded by the slowest single Batch Transform job, not the sum across programs. Step Functions Map with concurrency or a parallel-state fan-out are both reasonable implementations; the wrong implementation is the sequential outer-loop one."*

  Update the architecture-diagram caption or the Step Functions paragraph to reinforce: *"Each program's three scoring jobs are submitted in parallel; programs do not block each other."*

### Finding 9: Optimistic Counter Increment Has No Reconciliation Path; Members Who Never Receive Outreach Still Burn Cap Slots

- **Severity:** HIGH
- **Expert:** Architecture (fairness, correctness)
- **Location:** Step 6 pseudocode (`tailor_and_dispatch`), the `DynamoDB.UpdateItem ... ADD outreach_recent_wellness_count :one` block; Step 7 pseudocode (`process_engagement_event`), no decrement on send-failure events.
- **Problem:** The counter increment in Step 6 happens optimistically, before the channel optimizer actually delivers anything:

  ```
  // Update the contact-frequency counter optimistically. The actual
  // send may fail; reconcile in the engagement-attribution step.
  DynamoDB.UpdateItem("patient-profile", row.member_id,
      "ADD outreach_recent_wellness_count :one, ...")
  ```

  The reconciliation in Step 7 is described in the comment but not implemented. `process_engagement_event` handles `program_outreach_opened`, `program_outreach_clicked`, `program_enrolled`, `program_completed`, `program_dropped_out`, and `pcp_override`. It does NOT handle `program_outreach_failed`, `program_outreach_bounced`, `program_outreach_undeliverable`, or any decrement-on-failure path.

  Compounded across weekly runs:

  1. A member with a flaky email address (typo on the registration form, full inbox, spam-filter quarantine) accumulates `outreach_recent_wellness_count` every run even though zero outreach reached them.
  2. After 2 weeks of failed deliveries, they hit `MAX_WELLNESS_PER_MONTH = 2`. The next run's `enforce_outreach_caps` defers them with `wellness_cap_exceeded`.
  3. The deferral persists indefinitely (the recipe also has the windowing issue flagged separately by the code review: counters never decay).

  The fairness impact is structural and asymmetric: members with reliable email/SMS infrastructure (typically members in higher-resource cohorts) get a normal number of outreach contacts; members with flaky infrastructure (typically members in under-resourced cohorts the equity floor is trying to protect) get systematically silenced. The equity floor protects the *first* recommendation but not the *second*, and the silencing is invisible in the dashboards because the deferral reason (`wellness_cap_exceeded`) looks legitimate.

  The Honest Take's closing point is: *"The cost of an over-targeted member opting out of all wellness communications is high; you can't easily get them back. Default to fewer touches with higher tailoring quality."* The optimistic-counter design produces the opposite of "fewer touches with higher tailoring quality": it produces "the same number of attempted touches regardless of delivery success, and the cap silences members whose touches don't reach them."

  This is HIGH because (a) the recipe explicitly says "reconcile in attribution" but the reconciliation isn't implemented, (b) the failure mode is systemic and asymmetric across cohorts in a way that undoes the equity floor for repeat outreach, and (c) the symptom is invisible in standard cohort dashboards because the deferral looks legitimate.

- **Fix:** Three changes.

  1. **Implement the reconciliation path explicitly.** Add to `process_engagement_event` a clause for delivery-failure events:

     ```
     IF event.event_type in ["program_outreach_failed", "program_outreach_bounced",
                              "program_outreach_undeliverable"]:
         // Delivery never reached the member; release the optimistic cap slot.
         DynamoDB.UpdateItem(
             "patient-profile",
             event.member_id,
             "ADD outreach_recent_wellness_count :neg_one, outreach_recent_total_count :neg_one",
             values = { ":neg_one": -1 }
         )
         emit_metric("outreach_delivery_failure_decrement", value=1, dimensions={
             event_type: event.event_type,
             program_id: event.program_id,
             channel: event.channel
         })
         RETURN
     ```

  2. **Add the channel-optimizer integration contract.** The channel optimizer (Recipe 4.1) already produces delivery events; the contract here is that wellness-attributed outreach failures emit `program_outreach_failed` (or similar) into the engagement stream with the `tracking_id` so attribution can decrement.

  3. **Add a stale-pending sweep for outreach that never produces any signal.** A Lambda that runs on a 24-hour delay scans `recommendation-log` rows whose engagement-stream activity is empty (no opened, no clicked, no failed, no bounced) and either decrements the counter (assume silently dropped delivery) or escalates to the operations team. Pseudocode:

     ```
     FUNCTION reconcile_silent_recommendations(run_date_threshold):
         // Find recommendations from ≥ 24 hours ago with no engagement events.
         silent_rows = recommendation-log.scan(
             run_date < run_date_threshold,
             NO matching event in engagement-events
         )
         FOR each row in silent_rows:
             // Decrement the cap slot; the outreach effectively did not happen.
             DynamoDB.UpdateItem("patient-profile", row.member_id,
                 "ADD outreach_recent_wellness_count :neg_one, ...")
             emit_metric("silent_outreach_reconciled", value=1)
     ```

  Add a paragraph to the Honest Take or Why This Isn't Production-Ready section: *"Optimistic counter increments without a reconciliation path silence members whose outreach doesn't reach them. The reconciliation has two halves: a delivery-failure event from the channel layer that decrements the counter, and a stale-pending sweep that catches the cases where no event arrives at all. Both are needed; either alone leaves the asymmetry in place. This is one of the failure modes that surfaces six months in, when the equity dashboard starts trending in a direction nobody expected."*

### Finding 10: Step Functions Retry Semantics on Partial Batch Transform Completion Are Not Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (idempotency)
- **Location:** "Why These Services," AWS Step Functions paragraph; "Why This Isn't Production-Ready," DLQ-coverage TODO.
- **Problem:** Step Functions handles per-stage retry with backoff cleanly, but the recipe doesn't address what happens when a stage partially succeeds. Concretely:

  1. **Need scoring for programs 1-4 succeeds, program 5 fails.** Step Functions catches the failure. The retry kicks in. Does it re-run all 6 programs (idempotent but wasteful) or only program 5 (cheap but requires careful state tracking)? The recipe's pseudocode appears to recompute every run from scratch, but the production design likely needs incremental retry.
  2. **Engagement scoring succeeds for all 6 programs, uplift scoring partially fails.** The ranking step combines the three scores; running it with incomplete uplift produces a ranker output that mixes "real uplift" with "fallback uplift = 0" silently.
  3. **Allocation succeeds and writes to recommendation-log, then orchestrator fails.** Step Functions retries the orchestrator. Does it skip rows that already have a `program_recommended` event in the engagement stream, or does it re-emit and double-send?

  The recipe doesn't specify the idempotency keys (run_date + program_id + member_id seems natural but isn't named), the conditional-write pattern for "skip if already done," or the per-stage commit-point semantics. A reader following the pseudocode and naively wiring up Step Functions retry will hit double-sends in production.

- **Fix:** Add a paragraph to the Step Functions section or the Why This Isn't Production-Ready section:

  *"Each stage of the pipeline must be idempotent at the (run_date, program_id, member_id) granularity. Step 1 (eligibility) writes to a per-run S3 prefix that is fully recreated on retry. Step 2 (scoring) job names embed the run_date so a retry is a no-op if the job already exists in `Completed` state. Step 3 (ranking) writes to a per-run S3 prefix. Steps 4-5 (allocation, cap enforcement) write to DynamoDB with conditional-put on a composite key (run_date + member_id + program_id); a retry that re-attempts an already-written row is a no-op. Step 6 (orchestration) checks the recommendation-log for an existing `program_recommended` engagement event before queueing outreach; idempotency on the orchestration boundary prevents double-sends. The Step Functions Catch should distinguish Retryable (transient infra failure) from Terminal (logic error) and route Terminal failures to the DLQ rather than retrying."*

  Add explicit idempotency-key documentation to the recommendation-log schema description: *"primary key: (run_date, member_id, program_id) composite; conditional-put on `attribute_not_exists(run_date)` ensures retry-safety."*

### Finding 11: Cohort-Cycle Calendar Integration Mentioned but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** "Why This Isn't Production-Ready," the *Cohort-cycle calendar integration* paragraph.
- **Problem:** The recipe says programs have heterogeneous cohort cadences (DPP monthly, smoking cessation weekly, stress reduction quarterly) and that the orchestration layer should align each program's allocation pass with its cohort cycle. The current architecture, with a single weekly batch run via EventBridge, doesn't reflect this. The production-gaps section names the problem but doesn't propose an architecture.

  Two concrete consequences:

  1. **DPP allocations made in week 1 of a 4-week cohort cycle.** Members allocated in week 1 are 3 weeks early for the cohort start. They receive outreach, may click "interested" on the link, and then either lose interest before the cohort starts or get a "we'll be in touch in 3 weeks" delay that kills momentum.
  2. **Quarterly programs allocated weekly.** Stress reduction has 1 cohort per quarter. Allocating 1/13th of capacity weekly produces small allocation batches that struggle to fill the quarterly cohort to its minimum-enrollment threshold.

  Production wellness systems typically have per-program allocation schedules: weekly for rolling-enrollment programs, monthly for monthly-cohort programs, quarterly for quarterly programs. The recipe's "single weekly batch run" architecture doesn't model this.

- **Fix:** Promote the production-gaps text into an architecture paragraph and propose a scheduler design.

  *"In production, replace the single weekly EventBridge schedule with per-program schedules driven by each program's cohort cadence. EventBridge Scheduler supports per-rule cron expressions; one EventBridge rule per program triggers that program's slice of the pipeline (eligibility filter, scoring, allocation, orchestration) on its own cadence. Programs with the same cadence can share a rule. The cohort-start window for each program (e.g., DPP allocates members 7 to 14 days before cohort start) lives as program-catalog metadata and parameterizes the scheduler."*

  Reference Recipe 14.x: *"For plans with many programs and overlapping cohort calendars, this scheduler problem itself becomes an optimization concern (Recipe 14.x territory): which member to allocate to which program in which cycle, given that the same member may be eligible for multiple programs with overlapping cohort calendars. The recipe's per-program-per-cycle scheduling is the starter."*

### Finding 12: Allocator's Members-Already-Allocated Constraint Can Lock a Member into Their Second-Best Program

- **Severity:** MEDIUM
- **Expert:** Architecture (allocation correctness)
- **Location:** Step 4 pseudocode (`allocate_capacity`), the `members_already_allocated` set.
- **Problem:** The greedy allocator walks `candidates_sorted` (all (member, program) pairs sorted by global priority descending) and assigns each member to whichever program-pair appears first in the list. A member appears in `candidates_sorted` once per program they're eligible for. The first time the allocator encounters that member, they get assigned to whatever program that pair is for; the `members_already_allocated` set then suppresses all subsequent pairs for that member.

  The failure mode: imagine member A is eligible for DPP and smoking cessation. Their priority for DPP is 0.78; their priority for smoking cessation is 0.81. In a global priority sort, the smoking cessation pair appears first. The allocator assigns member A to smoking cessation. So far so good.

  But now imagine that the smoking cessation cohort has only 3 slots left when the allocator hits member A's smoking-cessation pair, and 100 other members rank higher. The allocator passes those 100 first. By the time it reaches member A's smoking-cessation pair, capacity is exhausted. The allocator skips it. Then the allocator reaches member A's DPP pair (priority 0.78). DPP still has capacity. Member A gets DPP.

  In this case the "skip if capacity full" behavior produces a reasonable outcome (member A ranks for both, gets one). But the recipe's pseudocode is:

  ```
  IF candidate.member_id in members_already_allocated:
      CONTINUE
  IF capacity_remaining[candidate.program_id] <= 0:
      CONTINUE
  ```

  The `members_already_allocated` check happens BEFORE the `capacity_remaining` check. That's fine in this example but produces a subtle bug in a different ordering: imagine member A's smoking-cessation pair has priority 0.81 and is processed first. The allocator successfully assigns member A to smoking cessation (3 slots left, A gets one). Now member A is in `members_already_allocated`. Later, the allocator reaches member A's DPP pair (priority 0.78). It hits the `members_already_allocated` check first, skips. Fine. But notice that the allocator made a hard choice for member A based on a 0.03 priority difference, and member A was probably a stronger DPP candidate than smoking cessation candidate by clinical-need-only metrics (the recipe even uses this as an example: "a smoker with prediabetes is eligible for both"). The recipe's policy weights blend clinical need with engagement and uplift, and a small uplift difference can shift the program.

  The recipe acknowledges this in the "Where it struggles" bullet: *"Members with multiple compelling program matches. The recommender currently allocates each member to at most one program per run."* But the architectural framing doesn't acknowledge that the allocator's *choice* between two programs is sensitive to a global ordering that may not be deterministic across runs (priorities can change weekly with feature drift), and that a member may flip between programs across runs in ways that are confusing to outreach orchestration.

- **Fix:** Two paragraphs.

  1. **Acknowledge the allocator's path-dependence.** Add a note: *"The greedy allocator's per-member program choice depends on the global priority ordering. Two members eligible for the same two programs may be assigned different programs depending on which pair appears first in the sort. Re-running the allocator with slightly different priorities (a feature refresh, a model retrain) may flip a member's assigned program. This is the greedy allocator's intrinsic instability and is one of the reasons graduating to integer programming (Recipe 14.x) is worth the investment when the slate has more than 3-4 programs with overlapping eligibility."*

  2. **Add a per-member best-program pre-pass option.** *"For plans where allocation stability across runs is operationally important (orchestration teams find member-program flipping confusing, the channel optimizer struggles to maintain context across program switches), a pre-pass can pre-commit each member to their top-priority program before the global greedy walk. The pre-pass loses some optimization tightness in exchange for stability. The choice is policy."*

### Finding 13: Per-Member Cohort-Feature Lookup Repeats N Times Per Member (Architecture-Level Counterpart of Code Review Finding 5)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 4 pseudocode (`allocate_capacity`), the `lookup_cohort_features(member)` call inside the `FOR each member, programs_for_member in per_member_rankings:` loop.
- **Problem:** The allocator's candidate-build loop calls `lookup_cohort_features(member)` for every (member, program) pair. A member ranked across 5 programs produces 5 cohort-feature lookups for the same member. At 80K members and 5-6 programs, that's 400K-480K lookups vs ~80K. The Code Review caught the same issue on the Python side (Finding 5). This is the architecture-level counterpart: the pseudocode doesn't deduplicate either.

  Two impacts:

  1. **DynamoDB throughput.** Each lookup is a `GetItem` against `patient-profile`. Per-search runtime cost.
  2. **Cohort-feature consistency.** If lookup 1 sees one cohort assignment and lookup 5 sees another (because some other process updated `patient-profile.sdoh_cohort` between the two reads), the allocator may emit inconsistent cohort assignments for the same member's recommendations. Fairness floors that key on cohort features rely on consistent assignment.

- **Fix:** Restructure the candidate-build loop to deduplicate by member before the per-program iteration:

  ```
  // Build the cohort-feature cache once per member.
  member_cohort_cache = {}
  unique_members = set([row.member_id for row in per_member_rankings])
  FOR each member_id in unique_members:
      member_cohort_cache[member_id] = lookup_cohort_features(member_id)

  // Then build candidates, attaching the cached cohort features.
  candidates = []
  FOR each member, programs_for_member in per_member_rankings:
      FOR each p in programs_for_member:
          candidates.append({
              ...
              cohort_features: member_cohort_cache[member]
          })
  ```

  Add a comment: *"Cohort features are looked up once per member, not once per (member, program) pair. A member ranked across N programs would otherwise produce N redundant DynamoDB reads, and a reader of the patient-profile that updates between reads could produce inconsistent cohort assignments across the same member's recommendations."*

---

## Networking Expert Review

### What's Done Well

- Lambdas in VPC with Flow Logs enabled.
- SageMaker training jobs, Batch Transform jobs, and Feature Store online store run in VPC.
- VPC endpoint list is comprehensive: DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis, KMS, CloudWatch Logs, SageMaker Runtime, Step Functions (`states`), EventBridge (`events`), STS, SES.
- NAT Gateway scoped explicitly to "external services without VPC endpoints (e.g., a vendor's outreach platform); restrict egress with security groups."
- Vendor program-catalog feeds addressed correctly: *"Vendor program-catalog feeds may need a Direct Connect tunnel or PrivateLink connection rather than NAT egress."* Same correct posture as 4.3's external SaaS credentialing handling.
- TLS in transit specified.

### Finding 14: VPC Endpoint List Misses Athena and Glue

- **Severity:** MEDIUM
- **Expert:** Networking
- **Location:** Prerequisites, "VPC" row.
- **Problem:** The architecture explicitly uses Glue for the eligibility-filter ETL and the outcome-evaluation pipelines, and Athena for the cohort dashboards and program-level ROI queries. Both have AWS PrivateLink VPC endpoints (`com.amazonaws.{region}.glue` and `com.amazonaws.{region}.athena`). Without these endpoints, control-plane calls to start Glue jobs and to issue Athena queries traverse public DNS, even though the data path (S3) is endpoint-covered.

  The Glue and Athena control-plane calls don't carry PHI in their payloads (job names, query text), but the absence of the endpoints means control traffic exits the VPC, may be subject to NAT egress security-group rules, and adds a public-DNS dependency that the otherwise-clean private architecture didn't need.

- **Fix:** Add Athena and Glue to the VPC endpoint list. Updated row text: *"VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis, KMS, CloudWatch Logs, SageMaker Runtime, Step Functions (`states`), EventBridge (`events`), Glue (`glue`), Athena (`athena`), STS, SES."*

  Optional: add Firehose (`firehose`) since Kinesis Firehose appears in the architecture as the engagement-event-to-S3 lander.

### Finding 15: `0.0.0.0/0` Egress Disallow Not Stated Explicitly (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites, "VPC" row.
- **Problem:** Same low-severity finding as 4.1 Finding 14, 4.3 Finding 15. The VPC row says "restrict egress with security groups" but doesn't explicitly disallow `0.0.0.0/0` egress on Lambda subnets. Worth capturing once chapter-wide.
- **Fix:** Add: *"No `0.0.0.0/0` egress from any Lambda subnet. NAT egress restricted by security group to specific IP ranges or hostnames (vendor outreach platform, vendor program-catalog feed if applicable). All other outbound traffic must go through VPC endpoints."*

### Finding 16: Vendor Outreach Platform Credentialing Posture Not Specified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** "Why These Services," Amazon SES paragraph: *"For SMS, push, or in-portal nudges, the orchestrator hands off to whatever channels Recipe 4.1 already integrated with."*
- **Problem:** The recipe correctly punts to Recipe 4.1 for SMS / push / in-portal channels but doesn't note the security-of-credentials posture for the vendor handoff. A wellness-program orchestrator that calls a third-party SMS gateway, push-notification provider, or in-portal nudge service needs (a) credentials stored in Secrets Manager with KMS encryption, (b) per-environment isolation, (c) rotation policy. None of this is recipe-4.4-specific, but a sentence pointing to it would help readers who skip 4.1.
- **Fix:** Add a sentence to the SES paragraph or the production-gaps section: *"Vendor channel integrations (SMS gateway, push provider, vendor outreach platform) credential through Secrets Manager with KMS encryption and a per-environment rotation policy. See Recipe 4.1's channel-optimizer credential pattern for the chapter-wide approach. Plain-text vendor API keys in Lambda environment variables are not acceptable."*

---

## Voice Reviewer

### What's Done Well

- The opening vignette is one of the strongest in the chapter. The "80,000 outreach emails... 1,400 clicks... 380 enrollments... 220 first-session attendees... 95 active by week eight... 47 completers" funnel makes the wellness-recommender problem visceral in a way no abstract framing could.
- *"The members who needed the program most (the highest-risk diabetics, the heaviest smokers) are mostly not in the 47. The ones who completed were the ones who would have made the lifestyle change anyway, with or without a program."* Direct, in CC's voice, lands the central tension before the technology section even starts.
- *"The system did not see her, in any meaningful sense."* One-line landing of the human cost. Excellent.
- *"It's not 'find the people who match the eligibility criteria'; that's a SQL query, and it doesn't scale to outcomes."* The kind of contrarian one-liner the chapter has been collecting.
- The persuadables / sure-things / lost-causes / sleeping-dogs framing is the canonical uplift mental model and the recipe presents it cleanly.
- *"A wellness recommender that drives more enrollments is not necessarily a better recommender. A wellness recommender that produces members who complete programs is not necessarily a better recommender."* Cadence is right; doubles down without padding.
- *"The wellness-program domain has a long history of vendors with thin evidence, ROI claims that don't survive independent evaluation, and a general sense that 'we sent emails and people enrolled' counts as program success."* Honest in a way that the wellness-industry-publications usually aren't.
- *"At minimum, you'll know."* Single-sentence closing of a paragraph that delivers harsh truth without cynicism. Strong.
- *"The thing I'd do differently the second time: invest in randomized hold-outs from day one."* The exact kind of post-mortem confession that sets the chapter's tone.
- *"Members are people, and wellness outreach can feel intrusive even when it's well-targeted. A member who gets recommended to DPP, smoking cessation, and stress reduction in the same month may correctly conclude that the plan thinks they're a mess."* Voice and content both excellent.
- Em dash check: scanned for U+2014 (em dash). Zero present. Pass.
- En dash check: scanned for U+2013 (en dash). Zero present. Pass.
- 70/30 vendor balance: The Problem, The Technology, and General Architecture Pattern sections are vendor-neutral. AWS service names appear in the AWS Implementation section and stay there. Clean.
- Marketing-language scan: scanned for "leverage," "seamlessly," "robust," "cutting-edge," "state-of-the-art," "industry-leading," "empower," "unleash," "game-changing," "paradigm," "holistic," "synergy," "best-in-class." Three "robust" hits, all technical: *"robust, interpretable in the same ways tree models always are"* (causal forests), *"doubly-robust estimation gives tighter intervals"* (a real causal-inference term), *"how robust are the conclusions to alternative matching specifications"* (sensitivity analysis). All legitimate technical use. Pass.

### Finding 17: "Multi-Objective Balance" Section Heading Reads Slightly Doc-Voice

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Section: *"### Where LLMs Fit (and Don't)"* and the parenthetical structural framing in the body of "The Logical Stages."
- **Problem:** Not a fix request. Worth flagging that the recipe's section headings are uniformly clean except for one or two structural-framing parentheticals like "(and Don't)" that read fine in a CC voice but tip toward doc-voice in isolation. Compare to 4.3's *"The Technology: Search Plus Ranking, with a Compliance Spine"* which the prior reviewer flagged as similar.
- **Fix:** None. Note for the editor: leave the headings; the body earns them.

### Finding 18: One Stretch in "Stage 4: Uplift Modeling" Has Drier Tone Than the Rest of the Recipe

- **Severity:** LOW
- **Expert:** Voice
- **Location:** "Uplift Modeling, Briefly" subsection, the T-learner/S-learner/Causal forests bullets.
- **Problem:** The recipe's voice is consistent throughout except for this one technical-primer block, where the bullets read more like a textbook summary than CC explaining causal inference at the whiteboard. Compare the narrative voice in *"The standard predictive modeling question is..."* (good) versus the bullet-list characterizations of T-learner / S-learner / Causal forests (functional but flat).

  The bullets are accurate and pedagogically sound. They just lose the conversational thread for a paragraph. Easy editor's pass to add a sentence of context per technique (*"T-learner is what you build when you have a Wednesday afternoon and a CSV"*; *"causal forests are the ones to graduate to when you stop trusting your own intuition about treatment-effect heterogeneity"*) would restore the voice without losing content.

- **Fix:** Optional editor's pass to inject one CC-voice sentence per technique. Not blocking.

### Finding 19: "Sleeping Dogs" Description Is the Best Sentence in the Recipe

- **Severity:** N/A (call-out)
- **Expert:** Voice
- **Location:** "Stage 4: Uplift Modeling" → Sleeping dogs bullet: *"Members whose outcome is negatively affected by the recommendation. Surprisingly real; an aggressive smoking cessation pitch to a member already managing fragile mental health stability can backfire."*
- **Problem:** Not a finding. Worth flagging to the editor: this is the sentence that distinguishes this recipe's voice from generic uplift-modeling explanations. Anyone who has actually run a wellness program for a population that includes patients with serious mental illness has seen this. The "surprisingly real" framing earns its place. Don't trim it.
- **Fix:** None. Note for the editor: keep it singular and verbatim.

---

## Stage 2: Expert Discussion

**Overlap: Architecture Finding 9 (optimistic counter no reconciliation) and Code Review Finding 9 (counters not windowed).** Same fairness-failure-mode through two paths. The code review caught that counters never decay; this review catches that counters increment optimistically without rolling back on send-failure. Both gaps compound: a member with delivery problems accumulates phantom-counter increments that never decay. Resolution: pick one rolling-window pattern (DynamoDB TTL + per-event row aggregated on read; scheduled decay Lambda; or per-day-bucket counter summed over 30 days) AND specify the reconciliation path on delivery failure. Both fixes are necessary; either alone leaves the asymmetric silencing in place.

**Overlap: Security Finding 1 (consent regime multi-dimensional) and Security Finding 4 (PCP review hold-time for higher-risk programs).** Both touch the question of "when is the right moment to send outreach to a particular member-program pair," which the current architecture treats as instantaneous after allocation. Resolution: address them as two layers of the same pre-send gate (consent verification + PCP-review hold), implemented in the orchestrator state machine.

**Overlap: Architecture Finding 8 (per-program serialization) and Architecture Finding 10 (Step Functions partial-completion retry).** Both touch the orchestration architecture for the per-program scoring stage. The pseudocode-to-architecture-diagram mismatch flagged in Finding 8 is exacerbated by the unaddressed retry semantics in Finding 10: a partial completion of one program's three jobs becomes a more painful debugging exercise if programs are serialized than if they're parallelized with explicit per-program isolation. Resolution: the parallel-fanout fix in Finding 8 should be paired with the idempotency-key documentation in Finding 10 so a reader can wire up Step Functions retry correctly.

**Overlap: Security Finding 3 (validator unspecified) and Architecture Finding 7 (DPP duration misrepresented).** Both touch the question of "what claims about programs are accurate." The DPP-duration error is a specific factual claim made in the recipe text; the validator-not-specified gap is about preventing the same kind of error from being made by the LLM-tailored outreach. Resolution: fixing Finding 7 in the recipe text and specifying the validator's approved-claims list mechanism in Finding 3 are independent but complementary: the validator's approved-claims list for DPP would ideally enforce *exactly* the kind of factual accuracy the recipe text itself currently fails on.

**Cross-recipe overlap: chapter-wide hardening patterns.** IAM ARN scoping (Finding 5 here, Finding 5 in 4.1, 4.2, 4.3), `0.0.0.0/0` egress disallow (Finding 15 here, Finding 14 in 4.1, Finding 15 in 4.3), and the SDOH-cohort PHI sensitivity TODO (Finding 6 here) all repeat. Worth consolidating into a chapter-4 preface section on shared production-hardening guidance to stop re-litigating per recipe. Positive cross-recipe progress: the recommendation-log retention period, the engagement-event identity-boundary check, the Bedrock data-retention posture, the multi-stage DLQ coverage, and the comprehensive VPC endpoint list have all matured from "TODO in 4.1" to "in main text in 4.4."

**No major conflicts among experts.** Security and Architecture both want stronger constraints on outreach delivery (consent multi-dimensional, validator specified, optimistic counter reconciled, PCP hold-time policy), and these align. Networking is about endpoint topology and credentials. Voice is cosmetic. Priority alignment is clean.

**Priority alignment.** Three HIGH findings (DPP duration / clinical accuracy, per-program serialization architecture-vs-pseudocode mismatch, optimistic counter without reconciliation path) are the must-fix-before-publication items. Seven MEDIUM findings are production-hardening that the editor or the next pipeline pass should address. The six LOW findings are cosmetic, edge-case, or chapter-pattern items.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

Zero CRITICAL findings. Three HIGH findings (Findings 7, 8, 9), which is at the threshold (more than 3 = FAIL, exactly 3 is acceptable).

The three HIGH findings are correctness gaps, not fundamental design flaws:

- Finding 7 (DPP duration) is a factual error woven through the recipe text that's easy to fix mechanically (replace "12-week" with "12-month" in five places, reframe the vignette numbers to month-based intervals, update the medium-horizon feedback paragraph, and add a vendor-vs-CDC distinguishing note).
- Finding 8 (per-program serialization) is a pseudocode-to-architecture mismatch that's also easy to fix mechanically (restructure the outer loop to submit jobs in parallel rather than waiting per-program).
- Finding 9 (optimistic counter without reconciliation) is the genuinely architectural one and requires adding a reconciliation clause to `process_engagement_event`, an explicit channel-optimizer integration contract, and a stale-pending sweep. The fix is local but the design implications matter for the equity story the recipe is trying to tell.

The teaching arc (eight-stage pipeline, eligibility-vs-optimization split, persuadables framing, capacity-aware allocation with equity floors, multi-horizon feedback, randomized-pilots-from-day-one) is solid and publishable. The HIGH findings should be addressed in the main text before the editor finalizes the recipe.

The recipe's security and architectural posture continues the chapter-wide trajectory of resolving prior reviewers' chapter-pattern gaps in the main text rather than punting to "Why This Isn't Production-Ready." That progression is worth flagging to the chapter editor as a positive signal: the chapter pipeline is converging, not diverging.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| 7 | HIGH | Architecture | Throughout (5 locations) | DPP consistently described as "12-week"; CDC NDPP is canonically 12 months |
| 8 | HIGH | Architecture | Step 2 pseudocode | `score_eligible_population` serializes across programs; architecture diagram implies parallel fan-out |
| 9 | HIGH | Architecture | Step 6 / Step 7 pseudocode | Optimistic counter increment with no reconciliation path; members with delivery failures are systemically silenced |
| 1 | MEDIUM | Security | Stage 1 prose, Step 5 pseudocode | Wellness consent treated as single boolean; doesn't address ADA, GINA, or state-specific regimes |
| 2 | MEDIUM | Security | Step 6 pseudocode, sample tracking_id | Tracking ID embeds member_id in plain text; flows into tracking pixels, vendor handoffs, logs |
| 3 | MEDIUM | Security | Step 6 pseudocode, production-gaps | Outreach validator approved-claims and prohibited-claims lists mentioned but not specified |
| 4 | MEDIUM | Security | Step 6 pseudocode, production-gaps | PCP-review path has no pre-send hold-time semantics for higher-risk programs |
| 10 | MEDIUM | Architecture | Step Functions paragraph, production-gaps | Retry semantics on partial Batch Transform completion not specified; idempotency keys not documented |
| 11 | MEDIUM | Architecture | Production-gaps section | Cohort-cycle calendar integration mentioned but not architected |
| 12 | MEDIUM | Architecture | Step 4 pseudocode | Greedy allocator's `members_already_allocated` produces path-dependent program assignment |
| 13 | MEDIUM | Architecture | Step 4 pseudocode | Cohort-feature lookup repeats per (member, program) pair instead of per member |
| 14 | MEDIUM | Networking | Prerequisites VPC row | VPC endpoint list missing Athena and Glue |
| 5 | LOW | Security | Prerequisites IAM row | "Never *" stated but scoped ARN examples not shown (chapter-wide pattern) |
| 6 | LOW | Security | Production-gaps TODO | SDOH cohort PHI paragraph lives in TODO; should be promoted into main Privacy paragraph |
| 15 | LOW | Networking | Prerequisites VPC row | `0.0.0.0/0` egress disallow not stated explicitly |
| 16 | LOW | Networking | SES paragraph | Vendor channel-integration credential posture not specified (Secrets Manager + KMS + rotation) |
| 17 | LOW | Voice | Section heading | Minor doc-voice in one section heading; optional |
| 18 | LOW | Voice | Uplift Modeling, Briefly | T-learner / S-learner / Causal forests bullets read drier than rest of recipe; optional editor's pass |
| 19 | N/A | Voice | Sleeping dogs bullet | Not a finding; note for editor: best sentence in the recipe, do not trim |

---

## Recommended Actions (Priority Order)

1. **Fix DPP duration throughout the recipe** (Finding 7): replace "12-week" with "12-month" in The Problem (twice), The Technology, the cohort-cadence subsection, and the medium-horizon feedback paragraph. Update the vignette's "by week eight... by week twelve" to month-based intervals. Add a sentence distinguishing CDC-recognized DPP (12 months) from vendor variants of shorter duration.
2. **Restructure Step 2 to parallelize across programs** (Finding 8): move the `wait_for_jobs` call out of the outer loop; submit all 3*N jobs first, then wait once. Update the Step Functions paragraph to mention Map-state with concurrency or parallel-state fan-out as the implementation options.
3. **Implement the contact-frequency reconciliation path** (Finding 9): add a `program_outreach_failed` clause to `process_engagement_event` that decrements the counter; specify the channel-optimizer integration contract that emits delivery-failure events; add a stale-pending sweep Lambda for outreach that produces no engagement signal at all. Note this in the Honest Take as a six-months-in failure mode.
4. **Replace single-boolean wellness consent with multi-dimensional consent** (Finding 1): ADA voluntary-participation, GINA family-history authorization, program-specific consent, channel-specific consent, state-specific regimes. Add a paragraph in production-gaps naming the regulatory frameworks.
5. **Replace string-concatenation tracking_id with opaque identifier** (Finding 2): UUID or HMAC; identifier-to-member mapping lives in the recommendation-log only. Update the Expected Results sample.
6. **Specify the outreach validator's pseudocode and approved-claims list mechanism** (Finding 3): four-layer validator (schema, required disclosures, prohibited claims, hallucinated clinical claims); approved-claims list as versioned config artifact owned by clinical/compliance; explicit failure-handling behavior on validator-fail.
7. **Add PCP-review-policy field to program catalog with hold-time options** (Finding 4): `none`, `notify_parallel`, `review_required_24h`, `review_required_72h_then_hold`. Update the orchestration pseudocode to respect the policy. Reference Recipe 4.10 for the formal-state-machine version.
8. **Specify Step Functions retry idempotency semantics** (Finding 10): per-stage idempotency keys (run_date + program_id + member_id where applicable); conditional-put on recommendation-log; orchestration boundary check for existing `program_recommended` event before queueing outreach.
9. **Architect the cohort-cycle calendar integration** (Finding 11): per-program EventBridge schedules driven by program-catalog metadata; reference Recipe 14.x for the cross-program scheduling-as-optimization version.
10. **Acknowledge greedy allocator path-dependence** (Finding 12): add a paragraph on instability across runs; offer a per-member-best-program pre-pass option for plans that need stability.
11. **Deduplicate cohort-feature lookups by member** (Finding 13): pseudocode-level fix; coordinates with Code Review Finding 5.
12. **Add Athena and Glue to the VPC endpoint list** (Finding 14); optionally Firehose.
13. **Add scoped IAM ARN examples** (Finding 5); chapter-wide pattern.
14. **Promote SDOH cohort PHI paragraph from TODO into main text** (Finding 6).
15. **Disallow `0.0.0.0/0` egress on Lambda subnets explicitly** (Finding 15); chapter-wide pattern.
16. **Specify vendor channel-integration credential posture** (Finding 16): Secrets Manager + KMS + rotation.
17. **Optional voice polish** (Findings 17, 18); none blocking.

---

## Notes for Editor

- The recipe runs long (~7,500 words before the footer). Length is earned: the Problem section's vignette, the eight-stage logical breakdown, the uplift primer, the engagement-vs-uplift distinction, the capacity-constraints discussion, the equity-considerations section, and the multi-horizon feedback architecture are all pedagogically essential. Do not trim any of them.
- Several `<!-- TODO -->` markers are present and appropriate: SageMaker Batch Transform HIPAA confirmation, Bedrock service terms verification, SES HIPAA scope, IAM ARN examples (chapter-wide), Cost Estimate validation, SageMaker model-promotion path, SDOH cohort PHI paragraph, DLQ coverage paragraph, aws-samples repo names, CDC NDPP URL, uplift-survey reference, generic AWS-blog pointers. These are realistic verification tasks and not blockers.
- The DPP-duration finding (Finding 7) intersects with the CDC NDPP URL TODO; verifying the URL will surface the canonical 12-month duration which makes the Finding 7 fix self-evident.
- The Cost Estimate's $200-400/month for Bedrock at 10K outreach messages/week is somewhat overstated for Haiku-class. Revising that downward to ~$15-30/month is reasonable when the editor verifies pricing. Total monthly estimate revises to $500-1,500/month range.
- The Related Recipes section forward-references future recipes (4.5, 4.6, 4.7, 4.10, 7.x, 11.x, 14.x) that haven't been written yet. Standard practice for the book.
- The Footer link to Recipe 4.5 references a future recipe that doesn't exist yet. Standard placeholder.
- All external links are real and verified: Synthea, econml, causalml, Obermeyer 2019 (Science), CDC NDPP (with TODO to verify current URL), AWS docs (SageMaker, Bedrock, Step Functions, EventBridge Scheduler, SES, QuickSight), AWS HIPAA Eligible Services list, Architecting for HIPAA whitepaper. The arxiv survey reference has an appropriate TODO acknowledging the field's continued development.
- The aws-samples repo references (`amazon-sagemaker-examples`, `amazon-sagemaker-feature-store-end-to-end-workshop`, `amazon-bedrock-workshop`) are appropriately hedged with a TODO. Appropriate.
- Cross-recipe coherence with 4.1, 4.2, 4.3 is strong: the patient-profile store, engagement-event bus, channel optimizer integration, contact-frequency cap, cohort dashboard infrastructure, and Bedrock / DynamoDB / Kinesis primitives are all reused consistently. The "Where This Sits in the Chapter" section's framing of 4.4 as the recipe that adds uplift-modeling, capacity-aware allocation, and longitudinal outcome tracking onto the personalization scaffold is accurate and helps the chapter narrative.
- The Python code review (`reviews/chapter04.04-code-review.md`) passed with one WARNING and eight NOTEs, which is below the FAIL threshold. The WARNING (SageMaker Batch Transform `wellness:run_date` tag extracts day-of-month not full date) is independent of this review's findings; the Code Review NOTE 9 (counters never windowed) shares root cause with this review's HIGH Finding 9 (counters not reconciled).
- Voice and 70/30 vendor balance: clean. Em dash count: 0. En dash count: 0. Recipe is publishable on voice grounds without any additional fixes.
- The "Sleeping dogs" sentence (Finding 19) is the best single sentence in the recipe. The editor should preserve it verbatim.

---

*Review complete. Findings prioritized; PASS verdict at threshold. The three HIGH findings are correctness gaps to close in the main recipe text before final editing; chapter-wide hardening progress (recommendation-log retention, engagement-event identity check, Bedrock data-retention posture, multi-stage DLQ coverage, comprehensive VPC endpoints) continues to mature from prior recipes' TODOs into this recipe's main text.*
