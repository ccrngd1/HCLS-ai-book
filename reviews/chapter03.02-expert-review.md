# Expert Review: Recipe 3.2 - Patient No-Show Pattern Detection

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-15
**Recipe file:** `chapter03.02-patient-no-show-pattern-detection.md`

---

## Overall Assessment

**Verdict: PASS**

This is a strong second recipe for the Anomaly Detection chapter and the cleanest treatment of patient no-show modeling in the cookbook so far. The Tuesday-morning vignette (a multispecialty group with seventy-two providers across fourteen clinics, roughly 1,100 daily visits, 140-200 expected no-shows, the coordinator who cannot answer "which 140 to 200" before 9 a.m.) lands the operational reality in two paragraphs. The five-part taxonomy of what a no-show actually is (the patient who forgot, the patient who couldn't come, the patient who ghosts, the patient who tried to cancel and couldn't, the habitual no-show whose pattern reflects life circumstances rather than a clinical failing) is the kind of dense-and-specific framing that turns a generic prediction problem into a thing the reader recognizes from their own organization. The "is this prediction or anomaly detection or both" framing at the head of the Technology section is publication-ready voice on a topic where most current writing is sloppy: pure prediction with a population-level threshold versus per-patient deviation from baseline are different operational tools, the recipe argues for the hybrid, and the entire downstream design follows from that framing. The features taxonomy (historical no-show behavior, appointment characteristics, patient context, access and engagement signals, social determinants, weather/environment) is correctly ordered by predictive value and includes the right warning that "most of the win comes from the historical behavior features plus lead time. If you get those two feature families clean, you're already at 60-70% of the lift." The four-bullet treatment of the label problem (late arrivals, same-day cancellations, reschedules, no-show-then-walk-in) is hard-won-experience teaching that a working analytics director would write. The fairness section is the most substantive in Chapter 3 to date, and the right framing ("a high-risk score is a signal to invest more in keeping the appointment, not less") is exactly the operational reframing this domain needs. The four-stage architecture (feature assembly, risk scoring, baseline-and-deviation, routing-and-intervention) plus a feedback loop is the architecturally correct factoring; the diagram and the walkthrough match each other (no diagram-vs-walkthrough drift, unlike Recipe 3.1). The Honest Take is publication-ready: the four lessons (feature engineering matters more than the model, the intervention is the product, the anomaly framing matters more than it looks, the portal-login-recency anecdote, the "build outcome capture and label pipeline first" lesson) land the right teaching priorities and the closing warning ("do not optimize the model to minimize no-shows if your operational response is to double-book... the patients you flag as high-risk get systematically worse service") is the kind of authentic operations-engineer voice the cookbook is built on.

Style hygiene is clean. Zero em dashes (direct U+2014 character check: zero matches across approximately 740 lines). Eleven en dashes, all in numeric ranges (cost figures, AUC ranges, performance benchmark percentages, implementation-time tiers), consistent with Chapter 1 published precedent and Recipe 3.1. No marketing language. No documentation-voice. The 70/30 vendor balance is preserved cleanly: the conceptual sections (Problem, Technology, General Architecture Pattern) are vendor-neutral and a reader on GCP or Azure could substitute their cloud's primitives without rewriting any of the teaching; AWS service names enter at the AWS Implementation section and stay there. HTML-comment TODOs (six total) are all forward-placeholder for industry-figure verification (no-show reduction percentage, transportation intervention effectiveness) or aws-samples/blog-post citations, which is the chapter-2-and-3 settled discipline.

The most consequential finding is a feedback-loop correctness bug that mirrors a problem the recipe correctly diagnoses for the model and then fails to address for the patient baseline. The retrain query in Step 5 explicitly excludes intervened appointments (`intervention_count = 0`) to avoid the counterfactual selection bias the recipe correctly warns about ("the model learns that high-risk appointments actually show up fine, and it will progressively downweight the features that got them flagged in the first place"). But the patient baseline update in `on_appointment_outcome` is unconditional: every outcome event flows into the rolling exponential moving average regardless of whether an intervention was applied. The consequence is that when interventions succeed (the patient shows up because the care coordinator called), the baseline drifts downward toward the intervention-adjusted rate, which is below the patient's true underlying rate. Over months of operation, baselines for high-risk patients who consistently get intervened on will collapse toward population averages, the deviation calculation will stop firing for them, and the "investigate" queue (whose entire value proposition is surfacing reliable patients with anomalously elevated risk for a specific appointment) will progressively lose the very signal it was designed to surface. This is the same selection-bias pattern the recipe correctly addresses for the model, applied to the baseline, missed in the implementation. It is HIGH because (a) it silently degrades the central design hypothesis of the recipe (the deviation framing is what differentiates this recipe from a pure-prediction approach), (b) the bug is in the canonical pseudocode the reader is meant to copy, and (c) the Python companion implements the same pattern (per the existing code review at `reviews/chapter03.02-code-review.md`).

A second HIGH cluster sits on baseline mathematics. The pseudocode references `MIN_BASELINE_OBSERVATIONS` as a threshold ("IF baseline is not null AND baseline.observation_count >= MIN_BASELINE_OBSERVATIONS") but never defines the constant, while the prose promises Bayesian smoothing with a Beta-distribution prior ("a Beta distribution with a population-derived prior is the usual tool; you get a baseline for every patient including brand-new ones") that is not implemented anywhere in the walkthrough. What the pseudocode actually does is initialize new baselines at zero and rely on a hard cutoff (the undefined constant) to fall back to the cold-start branch, which produces a multi-quarter cold-start period during which deviation calculations are unreliable and the prose-vs-code gap leaves the reader without the smoothing implementation the prose recommends.

Several MEDIUM findings cluster on the recurring cookbook patterns and on architectural completeness: outcome-event idempotency for the EventBridge-to-Lambda outcome-joiner path (recurring trigger-idempotency pattern across Chapters 2 and 3); no DLQ or poison-message handling for the outcome-joiner Lambda; PHI minimization in Pinpoint outreach payloads where high-stigma specialty disclosure is still possible; subgroup-data governance not specified at the infrastructure level; temporal validation not addressed in the retrain pipeline; feature_contributions in the sample output misrepresents how a logistic regression score decomposes.

LOW findings are editorial and operational polish: VPC endpoint precision (CloudWatch monitoring vs Logs, EventBridge events vs Scheduler, SageMaker api vs runtime); sample-output future timestamp; alpha=0.05 default not motivated for non-ML readers; HTML-comment TODOs for industry-figure verification.

Priority breakdown: 0 CRITICAL, 2 HIGH, 6 MEDIUM, 6 LOW.

The risk profile is similar to Recipe 3.1 (no LLM in the core path, no clinical-recommendation surface, no FDA medical-device exposure), with one important addition: the fairness surface area is substantially larger here. No-show prediction has well-documented disparate-impact pitfalls when the operational response to a high-risk score is exclusionary (double-booking, deprioritized rescheduling). The recipe correctly reframes the operational response ("invest more in keeping the appointment, not less"), but readers will deploy this against varied operational policies, and the architectural artifacts that make subgroup monitoring binding (rather than aspirational) are the right discipline to enforce in the recipe.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review

#### What's Done Well

- BAA posture is explicit. "AWS BAA signed. Every service listed is HIPAA-eligible under the BAA when configured correctly. Pinpoint requires specific configuration (SMS carrier routing, voice channel setup) to remain HIPAA-compliant; review the AWS HIPAA Eligible Services reference before production." Naming Pinpoint's special configuration requirement is the discipline most messaging-architecture writeups skip.
- Encryption coverage is complete across every PHI-carrying store. S3 SSE-KMS with customer-managed keys; DynamoDB encryption at rest with customer-managed KMS; SageMaker KMS on training volumes, endpoint volumes, model artifacts, and Feature Store offline/online stores; Redshift KMS cluster encryption; TLS in transit everywhere. The Feature Store online-store specific KMS callout is correct (a common omission).
- IAM is least-privilege per role with concrete examples per function: Glue job role, Batch Transform role, routing Lambda, outcome Lambda, training job role each get specific actions on specific resource ARNs with the explicit "No `*` permissions in production" closer. Same scope-every-action-to-specific-resource-ARNs discipline that Chapter 2 and Recipe 3.1 settled on.
- CloudTrail data events on the patient-baselines, intervention-queue, investigation-queue, intervention-log tables and the labels S3 bucket are required, with the framing that "Audit logs must capture every model prediction, every intervention decision, and every outcome event." This is the audit trail a HIPAA auditor actually uses.
- Retention posture is correct: HIPAA baseline is 6 years for PHI records, S3 lifecycle policies and DynamoDB point-in-time recovery are named explicitly. The fairness-monitoring data row in the prerequisites correctly identifies the protected-characteristic data dependency and the need to coordinate with the health equity team.
- Synthetic data discipline is explicit: Synthea is named with a verified GitHub link, and "Never use real PHI in development" is stated. The HTML-comment TODO acknowledging that a direct aws-samples repo for no-show prediction has not been confirmed is the correct discipline (no invented URLs).
- The "PHI handling in the outreach messages" subsection in "Why This Isn't Production-Ready" correctly identifies that the reminder content (provider, clinic, visit type, date) is clinical PHI and the messaging infrastructure (SMS carrier, voice telephony provider, email sender) all need to be under a BAA.
- The Pinpoint VPC limitation is correctly noted: "Pinpoint does not run in a VPC (it's a managed edge service); ensure that data flowing to Pinpoint is minimized to what's strictly needed for the message (appointment time, location, provider name)." This is the right discipline for the one PHI-egress vector in the architecture.

#### Finding S1: Pinpoint Outreach Payload PHI Minimization Misses High-Stigma Specialty Disclosure

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Step 4 `execute_outreach`, the Pinpoint message construction (`build_sms_reminder(intervention)`, `build_voice_script(intervention)`, `build_email_reminder(intervention)`); Prerequisites VPC row ("ensure that data flowing to Pinpoint is minimized to what's strictly needed for the message (appointment time, location, provider name)").
- **Problem:** The recipe's PHI-minimization guidance for Pinpoint says "appointment time, location, provider name" is the minimum-necessary set for a reminder. For most appointments this is correct. For appointments at high-stigma specialties (behavioral health, addiction medicine, OB/GYN, infectious disease/sexual health, oncology), the clinic name itself is a diagnostic disclosure. A reminder text reading "Reminder: 9:00 AM appointment with Dr. Smith at Mountain View Behavioral Health on May 14" exposes the patient's specialty even if no diagnosis or procedure is named. SMS messages traverse carrier networks, may be visible on lock screens to anyone with eyes-on access to the phone, and can show up in shared family-plan billing logs depending on carrier configuration. For high-stigma specialties, the standard discipline is to use generic clinic identifiers in patient-facing reminders ("Reminder: 9:00 AM appointment on May 14. Reply YES to confirm.") and only include the specialty name when the patient has explicitly opted into specialty-disclosing reminder content.
- **Fix:** Add a paragraph to the "PHI handling in the outreach messages" subsection in "Why This Isn't Production-Ready" that addresses high-stigma specialty disclosure: "For high-stigma specialties (behavioral health, addiction medicine, OB/GYN, infectious disease, oncology), the clinic name itself is a diagnostic disclosure. SMS messages can be visible on lock screens, on shared family devices, or in carrier billing logs. The minimum-necessary message for these specialties is typically the time and a generic identifier; the specialty name is included only when the patient has explicitly opted into specialty-disclosing reminders. Maintain a per-clinic 'reminder content sensitivity' flag in the patient preference store and gate the message-template selection on it." Same minimum-necessary-inside-the-BAA discipline as Recipes 2.7-2.10 S1 and Recipe 3.1 S1, with a new surface (patient-facing message content rather than internal serialized prompt context or examiner free text).

#### Finding S2: Subgroup Data Governance Not Specified at the Infrastructure Level

- **Severity:** MEDIUM
- **Expert:** Security / Compliance
- **Location:** Prerequisites table, Fairness Monitoring Data row ("Coordinate with the health equity team on what data is captured, how it's joined to the model outputs for monitoring, and who has access to the dashboard"); Step 5 `retrain_monthly`, the subgroup evaluation block (`FOR each subgroup in ["age_band", "insurance_type", "preferred_language", "race_ethnicity"]`).
- **Problem:** The recipe correctly identifies that subgroup performance evaluation requires access to protected-characteristic data (race, ethnicity, preferred language, insurance type, age band). It correctly defers the "what data is captured" question to the health equity team. But the architectural artifacts that make subgroup monitoring binding rather than aspirational are not specified: where this data lives, who has read access, how it's joined to predictions, what the audit trail for subgroup queries looks like. Race and ethnicity data has different governance from PHI in some regulatory regimes (some state laws restrict secondary use of self-reported race data more tightly than HIPAA restricts PHI), and the join from prediction archive to subgroup attributes typically happens in the analytics warehouse outside the model-serving pipeline. The retrain query as written has direct access to all four subgroup attributes and produces subgroup metrics in the training output, which means the training job role needs read access to the demographic attributes. That's not currently in the IAM section.
- **Fix:** Add a "Subgroup data access" row or paragraph to Prerequisites: "Subgroup performance evaluation requires read access to protected-characteristic attributes (race, ethnicity, preferred language, insurance type, age band). These attributes are governed differently from PHI in some regulatory regimes; restrict read access to the demographic store to the training job role and the QuickSight dashboard role, and audit subgroup queries via CloudTrail data events. The QuickSight dashboard backed by Athena should query an aggregated subgroup-metrics table, not the raw demographic-joined prediction archive, so that dashboard-user access does not require row-level read on the subgroup attributes." Also add a one-line IAM scope: the training job role gets `glue:GetTable` and `s3:GetObject` only on the demographic-joined view, not on the underlying patient-level demographic store.

#### Finding S3: PHI Linkage in DynamoDB Queue Tables Without Access Boundary Discussion

- **Severity:** LOW
- **Expert:** Security
- **Location:** Step 3 `route_scored_appointments`, the `intervention-queue`, `investigation-queue`, and `intervention-log` DynamoDB tables; Prerequisites IAM row.
- **Problem:** The intervention-queue, investigation-queue, and intervention-log DynamoDB tables contain `patient_id`, `appointment_id`, `risk_score`, `baseline_rate`, `deviation`, scheduled time, provider ID, clinic ID, and visit type. These are PHI-linkable per-record. The recipe correctly specifies KMS encryption at rest and CloudTrail data events. The recipe does not discuss IAM access scoping for these tables: Pinpoint workflow needs read on the intervention-queue, care coordinator workstation needs read/write on the investigation-queue, intervention execution writes to the intervention-log, and the outcome-joiner Lambda reads the intervention-log to attribute outcomes to interventions. Each consumer should have a separate IAM role scoped to specific actions on specific tables, not a shared "Lambda execution role" with broad DynamoDB access.
- **Fix:** Strengthen the IAM row in Prerequisites with per-consumer scoping: "Pinpoint outreach role: `dynamodb:Query` on `intervention-queue` only; `dynamodb:PutItem` on `intervention-log` only. Care coordinator workstation role: `dynamodb:Query` and `dynamodb:UpdateItem` on `investigation-queue` only; `dynamodb:PutItem` on `intervention-log` only. Outcome-joiner Lambda role: `dynamodb:Query` on `intervention-log` `appointment_id_index` only; `dynamodb:UpdateItem` on `patient-baselines` only. Routing Lambda role: `dynamodb:PutItem` on `intervention-queue` and `investigation-queue` only; `dynamodb:BatchGetItem` on `patient-baselines` only." Same minimum-necessary-DynamoDB-scoping discipline as Recipe 3.1 finding S5.

#### Finding S4: Real-Time Scoring Variation Inherits Pinpoint Egress Vector Without Reframing

- **Severity:** LOW
- **Expert:** Security
- **Location:** Variations and Extensions, "Real-time scoring at booking time" and "Patient-self-reschedule prompting"; Prerequisites Pinpoint VPC discussion.
- **Problem:** The Variations subsection promotes real-time scoring at booking and patient-self-reschedule prompting in the patient portal or reminder message itself. Both extensions move PHI through additional egress paths: the real-time scoring API receives the booking request synchronously from the scheduling system (which may be on-premises behind a corporate firewall, requiring VPC-to-on-premises connectivity), and the self-serve reschedule prompt embedded in an SMS or email reminder includes a deep-link with embedded appointment context. The Variations section presents both extensions without addressing the new PHI-handling surface they introduce. The deep-link URL in particular is a non-trivial concern: URLs can be logged by carriers, by URL-shortener services, by web-server access logs, by analytics tools embedded in the patient portal. A deep-link that encodes appointment context in the URL path or query string ("?aid=APT-2026-0050123&pid=PAT-00441297") leaks PHI through every system that touches it.
- **Fix:** Add a one-paragraph note to each extension: for real-time scoring, "the real-time scoring API receives the booking request synchronously from the scheduling system; if the scheduling system is on-premises, ensure the connection uses AWS Site-to-Site VPN or AWS Direct Connect, not a public-internet API; SageMaker endpoints in a VPC with VPC endpoints for SageMaker Runtime should be the discipline." For patient-self-reschedule, "The deep-link should encode an opaque token that resolves server-side to the appointment context, not the appointment context itself; URLs traverse carrier networks, URL-shortener services, and analytics tools that should not see PHI."

### Architecture Expert Review

#### What's Done Well

- The four-stage pipeline (feature assembly, risk scoring, baseline-and-deviation, routing) plus a feedback loop is the architecturally correct factoring for this problem class. The pipeline is clean, the stages have clear responsibilities, and the diagram and the walkthrough align with each other (no diagram-vs-walkthrough drift unlike Recipe 3.1).
- The decision to separate the population-level risk model from the per-patient baseline (with deviation as the residual) is the right factoring for a hybrid prediction-plus-anomaly system. The "two flags are useful: high absolute risk and high deviation from this patient's baseline. Either can drive intervention routing, and they capture different things" framing is correct.
- The Feature Store recommendation is the right architectural call and is correctly motivated: "the same feature code, no drift between training and inference. HIPAA-eligible." This is the piece most teams skip and then desperately wish they had six months later, and the recipe says so.
- Batch Transform vs real-time endpoint trade-off is correctly framed. "Start with batch, upgrade to real-time only if operational requirements demand it." Most teams over-engineer the inference path; the recipe says the right thing.
- The DynamoDB choice for patient baselines and intervention queues is correct: single-digit-millisecond latency point lookups by patient ID partition key, which is exactly what the routing Lambda needs.
- Step Functions for nightly orchestration is correctly framed: "the alternative (cron + Lambda + hope) works until it doesn't." Visibility into each stage, retries on transient failures, and a workflow history that helps debugging is what production operations teams actually need.
- The cost estimate is defensible and correctly framed against the recovered revenue from no-show reduction. "All-in model infrastructure ~$100-300/month fixed plus $500-2000/month variable on outreach, offset against the recovered revenue from reduced no-shows. No-show reduction of 2-5 percentage points on a 20% baseline is a realistic target and easily pays for the infrastructure." The HTML-comment TODO acknowledging that the 2-5 percentage points figure should be verified against a recent published case study is the right discipline.
- The "Why This Isn't Production-Ready" section is dense and architecturally substantive: scheduling system integration, feature engineering scope, patient preference storage, threshold tuning, subgroup monitoring as non-optional, intervention effect measurement as a separate analysis problem, data retention for labels, model monitoring and drift detection, governance review, PHI handling in outreach messages, appeal and override workflow. Eleven substantive bullets each tied to a real operational concern.
- The Honest Take is publication-ready. The four lessons (feature engineering matters more than the model, the intervention is the product, the anomaly framing matters more, the portal-login-recency anecdote and the "build outcome capture first" ordering lesson) are exactly the right teaching priorities. The closing warning ("do not optimize the model to minimize no-shows if your operational response is to double-book") is the kind of operations-engineer voice that distinguishes the cookbook from documentation-style writeups.
- Variations and Extensions covers the right adjacent patterns at the right depth: real-time scoring at booking, patient-self-reschedule prompting, transportation-specific intervention routing, group-scheduling optimization, cross-clinic learning, bandit-based intervention selection. Each is one to two paragraphs with enough scope to start a conversation but not so much that it crowds the main recipe. The bandit-based intervention selection extension's hand-off to Recipe 4.1 is the right cross-recipe coordination posture.
- Implementation-time tiers (4-6 weeks Basic, 3-5 months Production-ready, 4-8 months beyond for Variations) are realistic and resist optimism bias.


#### Finding A1: Patient Baseline Updates Are Not Counterfactual-Aware, Producing Baseline Collapse for Successfully Intervened High-Risk Patients

- **Severity:** HIGH
- **Expert:** Architecture / Domain Accuracy
- **Location:** Step 5 `on_appointment_outcome`, the baseline update block:
  ```
  baseline.rolling_no_show_rate = (
      (1 - alpha) * baseline.rolling_no_show_rate +
      alpha * (1 if is_no_show_or_late else 0)
  )
  baseline.observation_count += 1
  baseline.last_updated_at    = NOW()

  DynamoDB.PutItem("patient-baselines", baseline)
  ```
  Compare with Step 5 `retrain_monthly`, which correctly excludes intervened appointments from the model training pull:
  ```
  WHERE scored_at >= current_date - interval '365' day
    AND intervention_count = 0       -- exclude intervened appointments from primary training
  ```
- **Problem:** The recipe correctly diagnoses the counterfactual selection-bias problem in "The Feedback Loop" subsection: "If the model flags an appointment as high-risk and you intervene successfully (the patient shows up because you called them), that's a counterfactual problem: the label for that appointment is now 'showed up,' but it would have been 'no-show' without the intervention. Train on it naively and the model learns that high-risk appointments actually show up fine, and it will progressively downweight the features that got them flagged in the first place." The retrain query in Step 5 acts on this diagnosis and excludes intervened appointments from the training pull. The patient baseline update in `on_appointment_outcome` does not. Every outcome event flows into the rolling exponential moving average regardless of whether an intervention was applied.

  The functional consequence is the same selection-bias pattern the recipe correctly addresses for the model, applied to the baseline, missed in the implementation. When interventions succeed (the high-risk patient shows up because the care coordinator called), the outcome is "showed," `is_no_show_or_late = False`, and the baseline rolling_no_show_rate drifts downward by `alpha * (0 - current_baseline)`. Over months of operation, baselines for patients who consistently get intervened on will collapse toward population averages. This degrades the deviation calculation in two ways:

  1. The "investigate" queue's value proposition is surfacing reliable patients with anomalously elevated risk for a specific appointment. Once a patient's baseline has collapsed below the intervention-threshold band, the deviation from baseline is artificially inflated for routine appointments and artificially deflated for the genuinely-elevated-risk appointments the queue is supposed to surface. The patient is repeatedly flagged for investigation when the appointment looks normal, and missed when the appointment is genuinely anomalous. Both directions of the queue's signal degrade.

  2. For a high-risk patient who has been receiving consistent interventions for several months, the baseline approaches the post-intervention show rate (which by design is lower than the no-intervention rate). When intervention capacity is exceeded on a particular night and the patient lands in the standard-reminder bucket, the model's appointment-specific risk score (which knows the patient's high-risk feature profile) and the baseline (which has collapsed toward intervention-adjusted rate) disagree by a large amount. The deviation flag fires. The patient is added to the investigation queue when what should have happened is they should have stayed in the outreach queue. The architectural correction is in the wrong place, on the wrong patient.

  This is HIGH severity for three reasons: (a) it silently degrades the central design hypothesis of the recipe (the deviation framing is what differentiates this recipe from a pure-prediction approach, and the investigate-queue example in Expected Results is the recipe's most-quotable demonstration of why the deviation framing matters); (b) the bug is in the canonical pseudocode the reader is meant to copy; (c) the existing code review at `reviews/chapter03.02-code-review.md` confirms the Python companion implements the same unconditional update pattern (the Python `_update_patient_baseline` function applies the moving-average update without checking intervention status). A reader who deploys the recipe verbatim will see the deviation signal degrade over the first 6-12 months of operation as the baseline corrupts, and will not have the diagnostic vocabulary to attribute the degradation to the feedback loop.

- **Fix:** Three options, in increasing order of completeness:

  1. **Update the baseline only with outcomes where no intervention was applied.** The smallest change. After the Athena query in retrain that joins to the intervention log, add a similar conditional gate in `on_appointment_outcome`:
     ```
     interventions = DynamoDB.Query(
         table = "intervention-log",
         index = "appointment_id_index",
         key   = { appointment_id: event.appointment_id }
     )
     ...
     // Only update the baseline from non-intervened outcomes; intervened outcomes
     // are counterfactually corrupted (they reflect "what happened with intervention,"
     // not "what would have happened without intervention").
     IF length(interventions) == 0:
         baseline.rolling_no_show_rate = (
             (1 - alpha) * baseline.rolling_no_show_rate +
             alpha * (1 if is_no_show_or_late else 0)
         )
         baseline.observation_count += 1
         baseline.last_updated_at    = NOW()
         DynamoDB.PutItem("patient-baselines", baseline)
     ELSE:
         // Intervened: track the count and outcome separately for analysis,
         // but do not update the baseline.
         baseline.intervened_observation_count += 1
         baseline.last_updated_at = NOW()
         DynamoDB.PutItem("patient-baselines", baseline)
     ```
     This preserves the baseline as a counterfactual (it represents the no-intervention rate, which is what the deviation should be measured against). The trade-off is that for high-frequency intervened patients, the baseline updates more slowly. The trade-off is acceptable because the baseline is supposed to be slow-moving: it's the patient's underlying-rate signal, not a per-appointment risk estimate.

  2. **Compute the baseline from observed outcomes prior to the intervention program's deployment as a stable counterfactual.** Snapshot the baseline at program go-live; freeze it as the per-patient prior; update it only with no-intervention outcomes thereafter. This is more conservative than option 1 and is the cleanest interpretation of "what would the patient have done without our program," but it requires a one-time snapshot operation and creates a dependency on the program-launch date.

  3. **Use propensity-weighted updates: weight each outcome by an estimated probability of having been intervened on.** This is the formal counterfactual-inference solution and it requires a separately-modeled propensity score (the probability of intervention given features). Most teams do not invest in this level of rigor for a no-show baseline; option 1 captures most of the benefit at much lower implementation cost.

  Option 1 is the right starting point and should be applied immediately. Add a paragraph to "The Feedback Loop" subsection explaining that the same exclusion discipline applies to the baseline as to the model retrain, with the framing: "The patient baseline is a counterfactual signal: it should represent the patient's no-show rate without intervention, not the observed rate including intervention effects. The baseline update logic must exclude intervened outcomes for the same reason the model retrain query excludes them." Coordinate with the Python companion to keep pseudocode-to-Python parity.

#### Finding A2: Bayesian Smoothing Promised in Prose Is Not Implemented in Pseudocode; MIN_BASELINE_OBSERVATIONS Constant Is Undefined

- **Severity:** HIGH
- **Expert:** Architecture / Domain Accuracy
- **Location:** "Establishing a Patient-Level Baseline" prose ("The standard fix is Bayesian smoothing: start with a prior distribution based on cohort features and update toward the patient's observed rate as you accumulate observations. A Beta distribution with a population-derived prior is the usual tool; you get a baseline for every patient including brand-new ones, and it converges to the patient-specific rate as history accumulates."); Step 3 `route_scored_appointments` (`IF baseline is not null AND baseline.observation_count >= MIN_BASELINE_OBSERVATIONS`); Step 5 `on_appointment_outcome` (`baseline = DynamoDB.GetItem("patient-baselines", ...) OR empty_baseline(prediction.patient_id)`).
- **Problem:** Three connected gaps:

  1. The prose recommends Bayesian smoothing with a Beta-distribution prior as the "standard fix" for the cold-start problem. The pseudocode does not implement Bayesian smoothing anywhere. The baseline is initialized to zero (`empty_baseline()` returns a record with `rolling_no_show_rate = 0`), and updated with a naive exponential moving average. New patients with one observation have a baseline of either 0 (showed) or 0.05 (no-showed, after the alpha=0.05 update from zero). Neither value is a useful baseline; both will produce distorted deviation calculations.

  2. The cold-start fallback in Step 3 references `MIN_BASELINE_OBSERVATIONS` as a threshold but the constant is never defined. A reader implementing the recipe has to invent the value: 5? 20? 50? 100? The implication of getting it wrong is significant: too low (e.g., 5) and the deviation calculation fires for patients whose baseline is dominated by noise; too high (e.g., 100) and a substantial fraction of the patient panel never gets a meaningful deviation signal even after a year of operation.

  3. The relationship between the cold-start branch (deviation = 0) and the Bayesian-smoothing prior (which would give every patient a baseline from observation 1) is the gap the prose is supposed to fill. The reader is told "Bayesian smoothing handles cold start" and then sees a hard cutoff that essentially says "no deviation calculation until you have enough observations." The recipe's own framing is contradicted by its own pseudocode.

  This is HIGH severity because (a) the gap is between two artifacts the reader treats as authoritative (prose and pseudocode), (b) the missing implementation is the recipe's stated solution to the cold-start problem (which is the most common operational issue a first-deployment team will hit), and (c) the undefined constant is a literal "TODO: pick a number" that the reader is forced to make up.
- **Fix:** Two parts:

  1. Define `MIN_BASELINE_OBSERVATIONS` as a constant in Step 3 alongside the existing thresholds, with a default value and motivation:
     ```
     // Placeholder thresholds. Tune against your own ROC curve and intervention capacity.
     HIGH_RISK_THRESHOLD           = 0.35
     DEVIATION_FLAG_THRESHOLD      = 0.25
     INTERVENTION_CAPACITY_PER_DAY = 120
     MIN_BASELINE_OBSERVATIONS     = 8     // patient needs ~8 prior appointments
                                           // (about 2-3 years of routine care)
                                           // before deviation calculation is reliable
     ```
     Eight is a reasonable default for a no-show baseline (roughly 2-3 years of routine primary care for an adult patient, or one quarter of frequent specialty care). The right number depends on the population mix, and the recipe should say so explicitly: "Tune the threshold against your patient panel; specialties with high visit frequency (dialysis, oncology) reach reliable baselines in a few months, primary care typically requires 1-2 years."

  2. Replace the empty_baseline initialization with a Bayesian-prior initialization that matches the prose:
     ```
     FUNCTION empty_baseline(patient_id, cohort_features = null):
         // Bayesian prior: start with a Beta distribution shape derived from the
         // patient's cohort (or population if cohort_features unavailable).
         // alpha_prior + beta_prior is the "effective sample size" of the prior;
         // a value of ~10 is a reasonable starting weight (the prior dominates
         // the first ~5 observations, then the patient's own data takes over).

         IF cohort_features is not null:
             cohort_no_show_rate = lookup_cohort_rate(cohort_features)
                                   // by age band, insurance type, etc.
         ELSE:
             cohort_no_show_rate = POPULATION_NO_SHOW_RATE

         alpha_prior = 10.0 * cohort_no_show_rate
         beta_prior  = 10.0 * (1 - cohort_no_show_rate)

         RETURN {
             patient_id:                 patient_id,
             rolling_no_show_rate:       cohort_no_show_rate,
             alpha_prior:                alpha_prior,
             beta_prior:                 beta_prior,
             observation_count:          0,
             intervened_observation_count: 0,
             last_updated_at:            NOW()
         }
     ```
     And update the moving-average update to be Bayesian (alpha_posterior = alpha_prior + observed_no_shows, beta_posterior = beta_prior + observed_completed; rolling_no_show_rate = alpha_posterior / (alpha_posterior + beta_posterior)) rather than naive EMA. This matches what the prose promises.

  Coordinate with the Python companion to keep pseudocode-to-Python parity. Add a one-paragraph note to "Establishing a Patient-Level Baseline" prose acknowledging the implementation: "The pseudocode below uses a Beta-distribution prior with effective sample size 10, weighted by cohort no-show rate. The prior dominates predictions for the first few appointments, then converges to the patient-specific rate as observations accumulate. For cold-start patients with no cohort data, the population mean is the fallback."

#### Finding A3: Outcome Event Idempotency Not Modeled at the Outcome-Joiner Lambda

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 5 `on_appointment_outcome` (consumed by the `outcome-joiner` Lambda from EventBridge); architecture diagram (`Z[EventBridge\nappointment-events] --> N[AWS Lambda\noutcome-joiner]`).
- **Problem:** The architecture is event-driven from the EHR's appointment-outcome events to the outcome-joiner Lambda via EventBridge. EventBridge guarantees at-least-once delivery; Lambda asynchronous invocation also retries on failure. If EventBridge redelivers an event (the Lambda's first attempt timed out or returned a transient error), the outcome-joiner runs twice on the same outcome. The current pseudocode has no idempotency guard. Each run:

  1. Writes a fresh training row to `labels-parquet` with a UUID-keyed S3 path. The S3 PutObject is "idempotent" only in the sense that two writes don't conflict, but the resulting two training rows for the same outcome will be picked up by the next month's retrain. This biases the training data toward the doubled outcome (no-show or showed) for that specific appointment.

  2. Updates the patient baseline twice. Each update applies `(1 - alpha) * baseline + alpha * outcome`, so two updates apply the smoothing twice. For alpha = 0.05, the duplicate update biases the baseline by an additional ~2.5% of the outcome difference per duplicate event. For a patient with several thousand appointments over a career, accumulating duplicate events from EventBridge retries silently corrupts the baseline.

  3. Emits duplicate `outcome_recorded` and `intervention_outcome` CloudWatch metrics, double-counting the outcome in operational dashboards.

  This is the same trigger-idempotency pattern flagged across Recipes 2.4-2.10 expert reviews and Recipe 3.1 finding A2, surfacing here in a new form (EventBridge bus → Lambda async, with both label-write and baseline-update being non-idempotent). The fix template is the same: deterministic event-key derivation, conditional-write enforcement at the outcome-joiner.
- **Fix:** Two-part fix:

  1. Derive a deterministic event key from `appointment_id` plus the outcome type, and use it as a write-once guard in DynamoDB. Before writing the label and updating the baseline, check a `processed-outcomes` table:
     ```
     event_key = appointment_id + "|" + event.outcome
     try:
         DynamoDB.PutItem(
             table = "processed-outcomes",
             item = { event_key: event_key, processed_at: NOW() },
             condition = "attribute_not_exists(event_key)"
         )
     except ConditionalCheckFailedException:
         // Already processed this exact outcome event; drop silently.
         emit_metric("outcome_event_duplicate_dropped", 1)
         RETURN
     ```
     This prevents both the label write and the baseline update from running twice. The `processed-outcomes` table can have a TTL of 90 days (most retries happen within minutes; 90 days is conservative).

  2. Add a "Trigger idempotency" bullet to "Why This Isn't Production-Ready," with a forward reference to Recipe 3.1's same finding (since both recipes are now in Chapter 3 and a chapter-wide appendix on trigger idempotency is overdue).

  This recurring pattern is now flagged across eight consecutive recipes (2.4-2.10, 3.1, 3.2). The cookbook editor should seriously consider a chapter-wide or cookbook-wide appendix on trigger idempotency that consolidates the patterns once (S3 events with conditional DynamoDB writes, EventBridge bus → Lambda async with deterministic event keys, EventBridge Scheduler with deterministic Step Functions execution names, Kinesis with idempotent consumers, SQS with deduplication tokens). Each subsequent recipe could reference the appendix rather than repeat the discipline.


#### Finding A4: No DLQ or Poison-Message Handling for the Outcome-Joiner Lambda

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Architecture Diagram (`Z[EventBridge\nappointment-events] --> N[AWS Lambda\noutcome-joiner]`); Prerequisites table.
- **Problem:** The outcome-joiner Lambda has no Dead Letter Queue or `OnFailure` destination configured. The recipe's own "Why This Isn't Production-Ready" implicitly acknowledges that outcome events are operationally critical ("Outcome labels are small, long-lived records and they're essential for retraining. Don't let them age out of your primary data store quietly"), but the architectural artifacts that make a missed outcome event detectable are not present.

  When the outcome-joiner fails on a malformed event (the EHR emits an unexpected outcome code, a referenced appointment_id is not in the predictions archive due to clock skew between systems, the intervention-log query times out due to a hot partition), Lambda's default async retry behavior is two retries over six hours and then drop. The dropped event is lost: the label is never written, the baseline is not updated, the prediction-vs-outcome join for that appointment is silently broken. The retraining pipeline runs a month later on a training set that's missing some of the highest-signal outcome data (the failed events tend to cluster in operationally interesting cases: edge cases the EHR's outcome coder didn't anticipate, appointments rescheduled across system boundaries, cross-clinic transfers).

  The same pattern applies to the routing Lambda and the deviation-calc Lambda: any of them can fail, and any failure silently breaks the night's pipeline for the affected appointments.
- **Fix:** Add to the architecture diagram a `outcome-joiner-dlq` SQS queue receiving the outcome-joiner's `OnFailure` destination, plus equivalent DLQs for `routing-lambda-dlq` and `deviation-calc-dlq`. Add a one-line Prerequisites note: "Configure each Lambda's `OnFailure` destination to a dedicated SQS DLQ. Outcome events that exhaust retries become first-class operational artifacts, monitored with a CloudWatch alarm on queue depth. Replay the DLQ after fixing the root cause." Add a "DLQ and replay" bullet to "Why This Isn't Production-Ready" that ties the DLQ discipline to the recipe's existing label-retention discussion: "Lost outcome events are lost labels. The DLQ is the safety net for the retraining pipeline."

#### Finding A5: Temporal Validation Not Addressed in the Retrain Pipeline

- **Severity:** MEDIUM
- **Expert:** Architecture / Domain Accuracy
- **Location:** Step 5 `retrain_monthly`, the train/val split (`X_train, X_val, y_train, y_val = patient_stratified_split(X, y, patients = training_df.patient_id)`).
- **Problem:** The retrain function uses patient-stratified split, which prevents same-patient leakage across train and validation. This is correct for one class of leakage. But appointments have a strong temporal component (seasonality, operational changes, model drift in the active features), and the recipe's prose explicitly acknowledges seasonality as a failure mode in "Where it Struggles": "Flu season, holiday weeks, back-to-school. If the training window doesn't include the current seasonal pattern, the model underperforms."

  Patient-stratified split with random sampling does not prevent temporal leakage. A model trained on patient-stratified random splits over a 12-month window can have appointments from May 2026 in the training set and appointments from January 2026 in the validation set; this is the wrong direction for evaluating "does the model generalize forward in time?" For a binary classifier on temporally-ordered events, the standard practice is time-based holdout: train on a window ending some N days before the validation period begins (e.g., train on day 1-330, validate on day 331-365). The validation period should be after the training period in calendar time, and ideally should be representative of the deployment period the new model will run against.

  Patient-stratified split is correct for preventing patient-level leakage; time-based split is correct for preventing temporal leakage. Production pipelines typically do both: patient-stratified within a time-based split (validation = appointments in the last 30 days, restricted to patients not in training; training = appointments in the prior 11 months, restricted to patients not in validation).

  This is MEDIUM because the recipe's prose elsewhere identifies the right concept (point-in-time correctness of features) but the validation strategy doesn't enforce the corresponding time-based discipline. A model deployed from this pipeline can have undetected seasonal overfitting; the operations team will notice the model degrade in the first quarter after deployment if the training window straddled a seasonal transition.
- **Fix:** Update the retrain pseudocode to do a time-based split first, then patient-stratified within each side:
  ```
  // Time-based split: validation = most recent 30 days; training = the prior 11 months.
  validation_cutoff = current_date - interval '30' day
  training_cutoff   = current_date - interval '395' day   // 365 + 30

  training_df = Athena.query("""
      SELECT features_at_scoring, label, risk_score_at_scoring, scorer_version,
             intervention_count, patient_id, scored_at
      FROM labels_parquet
      WHERE scored_at >= :training_cutoff AND scored_at < :validation_cutoff
        AND intervention_count = 0
  """)
  validation_df = Athena.query("""
      SELECT features_at_scoring, label, risk_score_at_scoring, scorer_version,
             intervention_count, patient_id, scored_at
      FROM labels_parquet
      WHERE scored_at >= :validation_cutoff
        AND intervention_count = 0
  """)

  // Patient-stratified within each side: drop validation patients from training.
  validation_patients = unique(validation_df.patient_id)
  training_df = training_df WHERE patient_id NOT IN validation_patients
  ```
  Add a one-paragraph note to "The Feedback Loop" or "What Kind of Model to Use" subsection: "Validation strategy: time-based split (validation = most recent 30 days) prevents seasonal leakage; patient-stratified within each side (validation patients excluded from training) prevents same-patient leakage. Both are necessary."

#### Finding A6: Sample Output's `feature_contributions` Misrepresents Logistic Regression Score Decomposition

- **Severity:** MEDIUM
- **Expert:** Architecture / Domain Accuracy
- **Location:** Expected Results, sample intervention-queue record:
  ```json
  "feature_contributions": {
      "lead_time_days":                0.09,
      "prior_no_shows_12m":            0.11,
      "hour_of_day":                   0.06,
      "rolling_no_show_rate":          0.08,
      ...
  }
  ```
  And the relationship to `"risk_score": 0.52`.
- **Problem:** The sample output's `feature_contributions` map is presented as a per-feature decomposition of the risk score: eight named features with values (0.09, 0.11, 0.06, 0.08, 0.07, 0.05, 0.03, 0.03) that sum to 0.52, matching the `risk_score`. This presentation implies that feature contributions are additive in probability space and sum to the predicted probability. They are not.

  For a logistic regression model, the natural feature decomposition is in log-odds space: `score = sigmoid(intercept + sum(beta_i * x_i))`. Per-feature contributions are `beta_i * x_i` (log-odds contributions), and they sum to the pre-sigmoid logit, not the post-sigmoid probability. Translating to probability space requires the sigmoid, which is non-linear, so the per-feature contributions in probability space do not sum to the predicted probability.

  For a tree-based model (XGBoost) explained via SHAP, the SHAP values do additively decompose the model's raw output, but for a binary classifier the output is again log-odds, not probability, and the additive decomposition is in log-odds space. The sample output's "contributions sum to the probability" presentation is technically incorrect for either of the modeling approaches the recipe recommends (logistic regression or gradient-boosted trees).

  This matters because (a) the recipe is teaching ML concepts to a mixed audience, and a non-ML reader who copies this format and presents it to an operational stakeholder is teaching the stakeholder something false about how the model produces its score; (b) the operational team will sometimes ask "why is this score 0.52?" and "what would change the score?", and the answers depend on whether the contributions are in probability space or log-odds space; (c) the recipe's prose ("SHAP values give you explainability that is good enough for most operational contexts, though less clean than linear coefficients") correctly notes that SHAP for tree models is the right tool for this explanability need, but the sample output's format does not match what SHAP actually produces.
- **Fix:** Two reasonable resolutions:
  1. **Reframe as log-odds contributions.** Change the field to `feature_log_odds_contributions` and update the values to actual log-odds contributions (which can be negative for risk-reducing features). Add a one-line explanation: `// log-odds contributions; sum to the pre-sigmoid logit, not the probability`. Update the sample so the values sum to a plausible logit (e.g., ~0.08 for a 0.52 probability).
  2. **Reframe as normalized importances rather than contributions.** Change the field to `feature_importance` and present values as a percent of total absolute contribution (e.g., 0.21 for the top feature, summing to 1.0). This is what most operational dashboards actually display, and it sidesteps the log-odds-vs-probability question. A reader can implement this from either logistic-regression coefficients (with input scaling) or tree-model SHAP values.

  Option 2 is the more pragmatic choice for a recipe targeting a mixed audience; it's what most production systems actually surface to operations teams. Update the sample output and add a one-line note: "Feature importance values are normalized contributions (sum to 1.0). Values are derived from absolute SHAP values for tree models or scaled coefficients for linear models. Importance is not the same as direction; consult the model's per-feature direction to see whether a feature increases or decreases risk."

### Networking Expert Review

#### What's Done Well

- VPC posture is named explicitly and substantively: "Production: Glue jobs and SageMaker jobs in a VPC with VPC endpoints for S3, DynamoDB, SageMaker Runtime, Athena/Redshift, CloudWatch Logs, and KMS." Six interface and gateway endpoints named is more than most healthcare ML recipes specify.
- Pinpoint's VPC limitation is correctly called out ("Pinpoint does not run in a VPC (it's a managed edge service)"), which is the discipline most messaging-architecture writeups skip. The recommendation to "ensure that data flowing to Pinpoint is minimized to what's strictly needed for the message" is the right backstop for the unavoidable-egress vector.
- Gateway endpoints (S3, DynamoDB) are mixed correctly with interface endpoints; the recipe doesn't accidentally suggest a NAT Gateway in the path of PHI traffic.
- TLS in transit is named everywhere; the encryption row covers it.

#### Finding N1: VPC Endpoint Inventory Misses CloudWatch Monitoring, EventBridge Scheduler, and SageMaker API/Runtime Distinction

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row.
- **Problem:** Three precision gaps:

  1. **CloudWatch monitoring (PutMetricData) endpoint not distinguished from CloudWatch Logs.** The pipeline emits custom metrics throughout (Step 3's `emit_metric("intervention_queued", 1, ...)`, `emit_metric("investigation_flagged", 1)`, `emit_metric("standard_reminder", 1)`; Step 5's `emit_metric("outcome_recorded", 1, ...)` and `emit_metric("intervention_outcome", 1, ...)`). CloudWatch Logs uses `com.amazonaws.{region}.logs`; CloudWatch monitoring (PutMetricData) uses `com.amazonaws.{region}.monitoring`. They are distinct interface endpoints. A Lambda in a private subnet without the `monitoring` endpoint will succeed at writing logs but silently fail to publish custom metrics, which produces a metrics-coverage gap in operational dashboards. Same observation as the recurring Chapter 2 finding (Recipe 2.7-2.10) and Recipe 3.1 finding N1.

  2. **EventBridge bus vs Scheduler endpoints not distinguished.** The architecture uses both: EventBridge for outcome events (`Z[EventBridge\nappointment-events]`) and EventBridge Scheduler for the monthly retrain trigger (`P[EventBridge Scheduler\nmonthly]`). The bus uses `com.amazonaws.{region}.events`; Scheduler uses `com.amazonaws.{region}.scheduler`. The VPC row says "EventBridge" without distinguishing. Same as Recipe 3.1 finding N2.

  3. **SageMaker api vs runtime endpoints not distinguished.** SageMaker has multiple service endpoints: `api` (`com.amazonaws.{region}.sagemaker.api`) for control-plane operations like creating training jobs and Batch Transform jobs, `runtime` (`com.amazonaws.{region}.sagemaker.runtime`) for invoking real-time endpoints, and `featurestore-runtime` (`com.amazonaws.{region}.sagemaker.featurestore-runtime`) for online feature retrieval. The architecture uses all three: training and Batch Transform are control-plane (api), feature retrieval at scoring time is featurestore-runtime, and a real-time endpoint variation would use runtime.
- **Fix:** Update the VPC row in Prerequisites to:
  > "Production: Glue jobs and SageMaker jobs in a VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), SageMaker (`api` for control-plane training and Batch Transform, `runtime` for real-time inference if used, `featurestore-runtime` for online feature retrieval), Athena/Redshift, CloudWatch Logs (`logs`) and CloudWatch (`monitoring` for `PutMetricData`), EventBridge (`events` bus and `scheduler` for retrain cadence), KMS, and Pinpoint API where applicable. Pinpoint does not run in a VPC (it's a managed edge service); ensure that data flowing to Pinpoint is minimized to what's strictly needed for the message (appointment time, location, provider name)."

#### Finding N2: Glue and Step Functions VPC Endpoints Not Specified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row.
- **Problem:** AWS Glue jobs run in customer VPCs but the Glue control plane has its own interface endpoint (`com.amazonaws.{region}.glue`) for `StartJobRun`, `GetJobRun`, and similar control-plane operations called from the Step Functions state machine. Step Functions has its own interface endpoint (`com.amazonaws.{region}.states`) for invocation from a private subnet. Neither is in the VPC row's endpoint list. A Step Functions state machine running in a private VPC and orchestrating Glue jobs without these endpoints will hit timeouts on the control-plane calls.
- **Fix:** Add to the VPC row: "Glue (`glue` for control-plane), Step Functions (`states` for state-machine invocation)." Both are minor additions that complete the endpoint inventory for this recipe's specific service mix.


### Voice Reviewer

#### What's Done Well

- The Tuesday-morning vignette is publication-ready voice. "Picture a Tuesday morning at a mid-sized multispecialty group. The scheduling coordinator is looking at today's grid. Seventy-two providers across fourteen clinics, about 1,100 scheduled visits. By the end of the day, somewhere between 140 and 200 of those slots will go empty. The coordinator already knows this because she does this math every Tuesday. The question she cannot answer before 9 a.m. is which 140 to 200." The specificity (seventy-two providers, fourteen clinics, 1,100 visits, 140-200 no-shows, the Tuesday math) signals a writer who has been in this work, and the framing ("she cannot answer which 140 to 200") makes the analytics gap visceral in a single sentence.
- The five-part taxonomy of what a no-show actually is (forgot, couldn't come, ghosted, tried-to-cancel, habitual) is the kind of dense-and-specific framing that turns a generic prediction problem into something the reader recognizes. Each subtype gets a one-paragraph treatment with operational consequences and a hint at what the right intervention would be. This is the recipe's most-quotable section after the Honest Take and is the conceptual scaffolding the rest of the recipe is built on.
- The "is this prediction or anomaly detection or both" framing is the right teaching anchor for the technology section. The prose is honest: "it's both, and which framing you reach for drives very different design choices." The decision to "build the hybrid pattern, leaning into the anomaly framing since that's what puts it in Chapter 3" is publication-ready voice on a topic where most current writing is sloppy.
- The features taxonomy is correctly ordered by predictive value and includes the right warning that "most of the win comes from the historical behavior features plus lead time. If you get those two feature families clean, you're already at 60-70% of the lift." The warning that "the temptation to engineer exotic features" is what distracts most teams is the right operations-engineer voice.
- The label problem subsection (late arrivals, same-day cancellations, reschedules, no-show-then-walk-in) is hard-won-experience teaching. The closing posture ("Every team that has built this model has debated these questions for two weeks, landed on a working definition, documented it, and moved on. The specific answer matters less than having a clear, stable definition that everyone in the organization agrees on") is exactly the operational truth a working analytics director would say.
- The fairness section is the most substantive in Chapter 3 to date. The framing that "a high-risk score is a signal to invest more in keeping the appointment, not less" is exactly the operational reframing this domain needs. The closing posture ("The fairness concern doesn't disappear, but it shifts from 'is the model biased against group X?' to 'does our intervention budget disproportionately flow toward or away from group X?' Subgroup monitoring of intervention outcomes (not just model scores) is what you need to track, and it's a required part of the operational dashboard, not a nice-to-have") is the right operational discipline and is binding rather than hortatory.
- The Honest Take is publication-ready. The four lessons (feature engineering matters more than the model, the intervention is the product, the anomaly framing matters more than it looks, the portal-login-recency anecdote with its closing "the features you don't think of are probably the most predictive ones," the "build outcome capture and label pipeline first" ordering lesson with its closing "that ordering makes the project feel slower for the first month but dramatically faster for the six months after," and the closing trap warning "do not optimize the model to minimize no-shows if your operational response is to double-book") land the right teaching priorities. The warning is the kind of authentic operations-engineer voice that distinguishes the cookbook from documentation-style writeups.
- Variations and Extensions covers the right adjacent patterns at the right depth. Each is one to two paragraphs with enough scope to start a conversation.
- Zero em dashes (direct U+2014 character check: zero matches across approximately 740 lines). Eleven en dashes, all in numeric ranges (cost figures, AUC ranges, performance benchmark percentages, implementation-time tiers), consistent with Chapter 1 and Recipe 3.1 published precedent. No marketing language ("leverage," "seamless," "unlock," "transform," "empower," "revolutionize" all absent). No documentation-voice ("This recipe demonstrates," "leveraging the power of," "industry-leading" all absent). The 70/30 vendor balance is preserved cleanly: the conceptual sections are vendor-neutral; AWS service names enter at the AWS Implementation section and stay there.
- HTML-comment TODO discipline is correct. Six TODOs total, all forward-placeholder for industry-figure verification (no-show reduction percentage, transportation intervention effectiveness) or aws-samples/blog-post citations. No bracket-style visible TODOs that would render in published output.

#### Finding V1: Sample Output's Timestamps Use a Future Date That Will Age Awkwardly

- **Severity:** LOW
- **Expert:** Voice / Publication Readiness
- **Location:** Expected Results, sample intervention-queue record (`"scheduled_time": "2026-05-14T09:00:00"`, `"scored_at": "2026-05-12T02:16:04Z"`); sample investigation-queue record (`"scheduled_time": "2026-05-14T16:30:00"`, `"scored_at": "2026-05-12T02:16:04Z"`); various pseudocode example timestamps (`s3://features-bucket/nightly/YYYY-MM-DD/features.jsonl` — already a placeholder, good).
- **Problem:** The recipe is being drafted in May 2026 and the sample output uses 2026-05-12 and 2026-05-14 timestamps, which are current at draft time but will become a backdated example as the book ages. By publication (likely Q3 2026 or later), the timestamps will read as suspiciously specific and oddly precise. Same observation as Recipe 3.1 finding V1.
- **Fix:** Either (a) replace the specific dates with placeholder patterns ("`2025-01-15T...`" or "`<draft-time>`" with an HTML-comment note) or (b) keep the dates but add an HTML-comment disclaimer at the top of the Expected Results block: "Sample timestamps are illustrative and reflect the draft date; production output uses real ISO-8601 timestamps from the scoring time."

#### Finding V2: Alpha=0.05 Default for Exponential Decay Is Not Motivated for Non-ML Readers

- **Severity:** LOW
- **Expert:** Voice / Pedagogy
- **Location:** Step 5 `on_appointment_outcome`, the baseline update block:
  ```
  alpha = 0.05   // exponential decay factor; tune based on how fast you want the
                 // baseline to respond to new behavior.
  ```
- **Problem:** The recipe targets a mixed audience (executives, architects, engineers, product managers; "main recipes accessible to non-coders" per the project brief). The pseudocode comment for alpha says "tune based on how fast you want the baseline to respond to new behavior," which is correct guidance for a reader who already understands exponential moving averages. For a non-ML reader (and even for many ML practitioners who haven't worked with EMA-based baselines), the right intuition isn't conveyed: alpha = 0.05 means each new observation contributes 5% of the new baseline value; the baseline reaches half of its eventual value after roughly `log(0.5) / log(0.95) ≈ 13.5` observations and ~95% of its value after `log(0.05) / log(0.95) ≈ 60` observations. For a once-quarterly primary care patient, that's 15 years of observation before the baseline reflects 95% of their behavior. For a weekly-dialysis patient, it's a year. The choice of alpha has substantial implications for how fast the baseline responds, and the recipe doesn't give the reader the tool to choose appropriately.
- **Fix:** Expand the comment to give the intuition: "alpha = 0.05 is a slow-moving exponential decay; each new observation contributes 5% of the new baseline. The baseline reaches roughly 50% of its eventual value after ~14 observations and ~95% after ~60 observations. For high-frequency-visit patients (dialysis, oncology), 60 observations is about a year; for once-quarterly primary care patients, it's 15 years. Tune alpha to the visit-frequency profile of your panel: alpha=0.1 (~30 observations to converge) for high-frequency specialties, alpha=0.02 (~150 observations) for slow-frequency primary care. Or use a Bayesian update with a population prior, which gives you a meaningful baseline from observation 1 (see the Establishing a Patient-Level Baseline section)."

#### Finding V3: HTML-Comment TODOs for Industry-Figure Verification

- **Severity:** LOW
- **Expert:** Voice / Publication Readiness
- **Location:** Cost Estimate row in Prerequisites (no-show reduction percentage); "transportation-specific intervention routing" Variation (transportation intervention effectiveness); aws-samples and AWS blog post forward placeholders; "Performance benchmarks" table.
- **Problem:** Six HTML-comment TODOs are present, all forward-placeholder. Two should be resolved before publication:
  1. Cost Estimate: "No-show reduction of 2-5 percentage points on a 20% baseline is a realistic target." TODO requests verification against a recent published case study. The 2-5 percentage points range is directionally accurate based on commonly-cited published targeted-intervention studies, but the recipe should cite a specific source before publication.
  2. Performance benchmarks table: "these benchmark ranges are directional and drawn from typical published ranges for no-show prediction projects." Same posture: directionally correct but worth tightening to a specific citation.
  3. Transportation intervention effectiveness: "Several health systems have reported that transportation interventions produce disproportionately large reductions in the specific subset of no-shows they address." TODO requests verification of a specific published source.

  The aws-samples and AWS blog post forward placeholders read cleanly in published output and can remain as-is.
- **Fix:** Resolve the three industry-figure TODOs before publication. Reasonable sources: Health Affairs and AHRQ have published on no-show intervention programs; PCORI-funded studies on patient engagement frequently include intervention-effect estimates; the Robert Wood Johnson Foundation's transportation-as-a-determinant work is the natural citation for the transportation intervention extension. The aws-samples and blog-post TODOs can remain as forward placeholders; the HTML-comment form is the chapter-2-and-3-settled posture and reads cleanly.

---

## Stage 2: Expert Discussion

**Pattern: A1 and A2 are mirror findings on the patient-baseline subsystem.** A1 is the missing intervention-aware filter on baseline updates (the same selection-bias problem the recipe correctly addresses for the model retrain, missed for the baseline). A2 is the missing Bayesian-smoothing prior the prose recommends and the pseudocode does not implement, plus the undefined `MIN_BASELINE_OBSERVATIONS` constant. Both findings point to the same architectural seam: the patient-baseline subsystem was specified at the prose level but the pseudocode pass produced a simpler implementation that's missing two specific pieces. A coordinated fix is more efficient than two separate edits: in a single editorial pass, replace the `empty_baseline()` initialization with a Bayesian-prior initialization (A2 fix), gate the baseline update on intervention status (A1 fix), define `MIN_BASELINE_OBSERVATIONS` (A2 fix), and update the prose in "Establishing a Patient-Level Baseline" to match what the pseudocode now does. The Python companion update follows the same coordinated pass.

**Pattern: A3 is the now-recurring trigger-idempotency finding, surfacing in Chapter 3 for the second consecutive recipe.** Recipe 3.1's A2 was S3 ObjectCreated → async Lambda fan-out without idempotency. Recipe 3.2's A3 is EventBridge bus → outcome-joiner Lambda without idempotency. Same fix template (deterministic event-key derivation, conditional-write enforcement at the orchestration layer), different specific event source. The cookbook editor should now seriously consider a chapter-wide or cookbook-wide appendix on trigger idempotency that consolidates the patterns once. With this finding now flagged across eight consecutive recipes (2.4-2.10, 3.1, 3.2), the per-recipe-edit posture is producing diminishing returns.

**Pattern: S1 is the now-recurring PHI-minimization-inside-the-BAA pattern.** Chapter 2's recurring S1 was about minimum-necessary on serialized prompt contexts (LLM input). Recipe 3.1's S1 was about minimum-necessary on examiner free-text reasoning fields (human input). Recipe 3.2's S1 is about minimum-necessary on patient-facing reminder content for high-stigma specialties (patient-facing message output). The underlying discipline is identical (don't carry identifying or specialty-disclosing information through stores or messages you don't need it in), but the surface has shifted again. A cookbook-wide PHI-minimization appendix would cover all three surfaces (LLM prompt construction, human-input free text, patient-facing message content) with one teaching pass. This is the sixth Chapter-2-or-3 expert review with a PHI-minimization finding; the pattern has fully stabilized.

**Pattern: A6 (feature_contributions misrepresentation) is a teaching-fidelity issue distinct from the recurring patterns.** It's the first finding in Chapter 3 about how the recipe's sample output presents model internals to the reader. The fix is a small reformatting of the sample output, but the underlying concern (the recipe is teaching ML concepts to a mixed audience and a non-ML reader will copy what they see) is worth flagging as a category of finding for future recipes that include explainability outputs. SHAP-style sample outputs in particular need to be presented in a way that doesn't mislead readers about what the values mean.

**Pattern: A5 (temporal validation) and the prose's seasonality discussion are connected.** The prose correctly identifies seasonality as a failure mode in "Where it Struggles" but the validation strategy doesn't enforce a time-based discipline. The fix is small (a one-paragraph addition to the retrain pseudocode), but the connection between prose and pseudocode is the same kind of teaching-fidelity gap as A6: the prose makes a claim ("seasonality is a real problem") and the pseudocode doesn't reflect the right discipline for catching it.

**Non-conflict: A4 (DLQ), N1 and N2 (VPC endpoint detail), V1, V2, V3 (publication-readiness polish).** All operational-completeness findings independent of the safety/correctness findings.

**Coordination with the existing code review (`reviews/chapter03.02-code-review.md`):** The code review PASSed-with-reservations on three WARNINGs in the Python companion. WARNING 1 (the broken `assert` guard on `PINPOINT_APPLICATION_ID`) is a Python-companion-only issue. WARNING 2 (S3 `put_object` without `SSEKMSKeyId`) is a Python-companion implementation issue that doesn't surface in the pseudocode. WARNING 3 (silent-success on unrecognized channel preference) is a Python-companion implementation issue. None of the WARNINGs in the code review overlap with the HIGH or MEDIUM findings in this expert review. However, the A1 and A2 fixes (counterfactual-aware baseline updates and Bayesian-smoothing initialization) must propagate to the Python companion's `_update_patient_baseline` and `_load_or_create_baseline` functions in the same editorial pass, because the Python implementation currently mirrors the broken pseudocode pattern. A re-review of the Python companion after the A1/A2 fixes would also pick up the WARNINGs from the original code review, so a single coordinated pass on both files is more efficient than two passes.

**Pattern observation: the recipe is fundamentally sound; the highest-risk findings are correctness bugs in the patient-baseline subsystem.** Like Recipe 3.1 and the strongest Chapter 2 recipes, this one's teaching density and voice are publication-ready. The two HIGH findings (A1 baseline counterfactual gap, A2 Bayesian-smoothing implementation gap) are both in the same subsystem and have a coordinated fix path. The MEDIUM findings cluster on architectural completeness (DLQ, idempotency, temporal validation, output presentation) and PHI minimization. There is no validation-retry safety bypass (no LLM in the core path), no FDA medical-device exposure, no clinical-recommendation safety surface. The Chapter 2 framing of "the architecture is built to prevent missed contraindications and missed interactions" does not apply here; the stakes are domain correctness in the baseline subsystem, operational completeness in the feedback loop, and access-equity in the intervention routing. The fairness surface area is materially larger than Recipe 3.1's (no-show prediction has well-documented disparate-impact pitfalls), and the recipe correctly addresses the framing-level concern; the architectural artifacts that make subgroup monitoring binding are S2's concern.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

Two HIGH findings (below the "more than 3 HIGH = FAIL" threshold) and zero CRITICAL findings. The recipe is teaching-strong, voice-clean, and architecturally sound at the conceptual level. The Tuesday-morning vignette, the five-part taxonomy of no-shows, the prediction-vs-anomaly-detection framing, the features taxonomy, the label-problem subsection, the fairness section, and the Honest Take are all publication-ready. Style hygiene is clean (zero em dashes, eleven en dashes restricted to numeric ranges per Chapter 1 and Recipe 3.1 precedent, no marketing language, no documentation-voice, 70/30 vendor balance preserved, HTML-comment TODOs only).

The two HIGH findings are both in the patient-baseline subsystem and have a coordinated fix path:
- **A1** Patient baseline updates are not counterfactual-aware. The same selection-bias problem the recipe correctly addresses for the model retrain (excluding intervened appointments from training data) is missed for the baseline updates (every outcome event flows into the rolling EMA regardless of intervention status). Successfully intervened high-risk patients see their baselines collapse over time, degrading the deviation calculation that is the recipe's central design hypothesis.
- **A2** Bayesian smoothing promised in prose is not implemented in pseudocode. The `MIN_BASELINE_OBSERVATIONS` constant referenced in Step 3 is never defined. New baselines are initialized to zero rather than the population or cohort prior the prose recommends.

Both findings are fixable in a coordinated single editorial pass on the baseline subsystem; the prose-vs-pseudocode gap closes when the baseline initialization becomes Bayesian (with the prior matching the prose) and the update logic becomes intervention-aware (matching the model retrain's discipline). The Python companion update follows the same pass.

The six MEDIUM findings cluster on architectural completeness, recurring patterns, and output presentation:
- **A3** Outcome event idempotency for the EventBridge → outcome-joiner Lambda path (recurring trigger-idempotency pattern across Recipes 2.4-2.10 and 3.1; chapter-wide appendix candidate)
- **A4** No DLQ or poison-message handling for the outcome-joiner, routing, or deviation-calc Lambdas (architectural gap; one-line Prerequisites note plus diagram additions)
- **A5** Temporal validation not addressed in the retrain pipeline (patient-stratified split is present, time-based split is not; seasonality is a stated failure mode in prose)
- **A6** Sample output's `feature_contributions` misrepresents how a logistic regression score decomposes (additive in probability space is incorrect; reframe as feature importance or log-odds contributions)
- **S1** Pinpoint outreach payload PHI minimization misses high-stigma specialty disclosure (recurring minimum-necessary-inside-the-BAA pattern with a new surface: patient-facing message content)
- **S2** Subgroup data governance not specified at the infrastructure level (the architectural artifacts that make subgroup monitoring binding rather than aspirational)

The six LOW findings are operational and editorial polish:
- **S3** Per-consumer IAM scoping for queue-table access not specified
- **S4** Real-time scoring and self-reschedule extensions inherit Pinpoint egress without reframing PHI-handling
- **N1** VPC endpoint precision (CloudWatch monitoring vs Logs, EventBridge events vs Scheduler, SageMaker api/runtime/featurestore-runtime distinction)
- **N2** Glue and Step Functions VPC endpoints not specified
- **V1** Sample output future-dated timestamps (same as Recipe 3.1 V1)
- **V2** alpha=0.05 default for exponential decay not motivated for non-ML readers
- **V3** Industry-figure HTML-comment TODOs to resolve before publication

With the A1/A2 coordinated fix applied (and the Python companion update in lockstep), the MEDIUM findings addressed, and the LOW polish completed, this recipe sits at the same publication-ready quality bar as Recipe 3.1 and the strongest Chapter 2 recipes. The risk profile is similar to Recipe 3.1 (no LLM, no clinical-recommendation surface, no FDA exposure) with one important addition: the fairness surface area is materially larger here. The recipe's framing-level treatment of fairness is excellent; the architectural artifacts (S2's subgroup-data governance, A6's correct presentation of model contributions) are the right operational backstops.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| A1 | HIGH | Architecture / Domain Accuracy | Step 5 `on_appointment_outcome`, baseline update block (unconditional moving-average update regardless of intervention status) | The same selection-bias problem the recipe correctly addresses for the model retrain (`intervention_count = 0` exclusion) is missed for the patient baseline updates. Successfully intervened high-risk patients see their baselines collapse over months of operation toward the intervention-adjusted rate, degrading the deviation calculation that is the recipe's central design hypothesis. The "investigate" queue progressively loses the signal it is supposed to surface (reliable patients with anomalously elevated risk for a specific appointment). Fix: gate the baseline update on intervention status; only update the baseline when no intervention was applied; track intervened-observation count separately for analysis. |
| A2 | HIGH | Architecture / Domain Accuracy | "Establishing a Patient-Level Baseline" prose vs Step 3 `route_scored_appointments` and Step 5 `on_appointment_outcome` pseudocode | Bayesian smoothing with a Beta-distribution prior is recommended in prose ("a Beta distribution with a population-derived prior is the usual tool; you get a baseline for every patient including brand-new ones") but not implemented in the pseudocode (which initializes to zero and uses naive EMA). The cold-start fallback in Step 3 references `MIN_BASELINE_OBSERVATIONS` as a threshold but the constant is never defined. Reader is told "Bayesian smoothing handles cold start" and then sees a hard cutoff with an undefined constant. Fix: define `MIN_BASELINE_OBSERVATIONS` (default ~8 with motivation); replace `empty_baseline()` with Bayesian-prior initialization using cohort-derived (or population) Beta prior with effective sample size ~10. |
| A3 | MEDIUM | Architecture | Step 5 `on_appointment_outcome` (consumed via EventBridge by the outcome-joiner Lambda) | EventBridge → Lambda async is at-least-once; pseudocode has no idempotency guard. A redelivered outcome event writes a duplicate label row, updates the patient baseline twice (compounding the moving-average update), and double-emits CloudWatch metrics. Same recurring trigger-idempotency pattern as Recipes 2.4-2.10 and 3.1, with a new surface (EventBridge bus → Lambda with both label-write and baseline-update being non-idempotent). Fix: deterministic event-key derivation (`appointment_id + outcome`); conditional DynamoDB write to `processed-outcomes` table before label and baseline operations. Strongly recommend a chapter-wide trigger-idempotency appendix. |
| A4 | MEDIUM | Architecture | Architecture Diagram (no DLQs configured); Prerequisites table | No Dead Letter Queue or `OnFailure` destination configured for the outcome-joiner, routing, or deviation-calc Lambdas. Lambda's default async retry behavior (two retries, then drop) silently loses outcome events that exhaust retries; the retraining pipeline runs a month later on a training set missing some of the highest-signal outcome data. Fix: add `outcome-joiner-dlq`, `routing-lambda-dlq`, `deviation-calc-dlq` SQS queues with `OnFailure` destinations configured; add a one-line Prerequisites note tying DLQ discipline to the recipe's existing label-retention discussion. |
| A5 | MEDIUM | Architecture / Domain Accuracy | Step 5 `retrain_monthly`, the train/val split (`patient_stratified_split`) | Patient-stratified split prevents same-patient leakage but does not prevent temporal leakage. Recipe's prose elsewhere identifies seasonality as a failure mode ("If the training window doesn't include the current seasonal pattern, the model underperforms"), but the validation strategy doesn't enforce a time-based discipline. A model deployed from this pipeline can have undetected seasonal overfitting. Fix: time-based split first (validation = most recent 30 days), patient-stratified within each side. |
| A6 | MEDIUM | Architecture / Domain Accuracy | Expected Results sample, `feature_contributions` map summing to risk_score | Sample output presents per-feature contributions as additive in probability space, summing to the predicted probability. This is technically incorrect for both modeling approaches the recipe recommends: logistic regression decomposes additively in log-odds space (not probability), and SHAP for tree models also decomposes in raw-score (log-odds) space. A non-ML reader who copies this format teaches operational stakeholders something false about how the model produces its score. Fix: reframe as `feature_importance` (normalized to sum to 1.0) or as `feature_log_odds_contributions` with explanatory comment. |
| S1 | MEDIUM | Security | Step 4 `execute_outreach`, Pinpoint message construction; Prerequisites VPC row Pinpoint discussion | Recipe's PHI-minimization guidance for Pinpoint (appointment time, location, provider name) is correct for most appointments but misses high-stigma specialty disclosure: for behavioral health, addiction medicine, OB/GYN, infectious disease/sexual health, oncology clinics, the clinic name itself is a diagnostic disclosure. SMS messages traverse carrier networks, are visible on lock screens, can show in shared family-plan billing logs. Same minimum-necessary pattern as Recipes 2.7-2.10 S1 and Recipe 3.1 S1, with a new surface (patient-facing message content). Fix: add a paragraph to the "PHI handling in the outreach messages" subsection addressing high-stigma specialty disclosure; recommend per-clinic "reminder content sensitivity" flag in patient preference store; gate message-template selection on it. |
| S2 | MEDIUM | Security / Compliance | Prerequisites Fairness Monitoring Data row; Step 5 `retrain_monthly` subgroup evaluation block | Recipe correctly identifies that subgroup performance evaluation requires access to protected-characteristic data and defers "what data is captured" to the health equity team, but the architectural artifacts that make subgroup monitoring binding are not specified: where data lives, who has read access, how it joins to predictions, audit trail for subgroup queries, IAM scope for the training job role's read access to demographic attributes. Race/ethnicity data has different governance from PHI in some regulatory regimes. Fix: add a Subgroup data access row to Prerequisites; restrict read access to demographic store to training-job role and dashboard role; CloudTrail data events on subgroup queries; QuickSight queries against an aggregated subgroup-metrics table rather than the raw demographic-joined prediction archive. |
| S3 | LOW | Security | Step 3 `route_scored_appointments`, intervention-queue/investigation-queue/intervention-log DynamoDB tables; Prerequisites IAM row | Per-consumer IAM scoping for queue-table access not specified; the recipe gives generic least-privilege framing but doesn't break out per-consumer roles (Pinpoint, care coordinator, intervention executor, outcome-joiner). Fix: per-consumer IAM scope examples in Prerequisites IAM row; same minimum-necessary-DynamoDB-scoping discipline as Recipe 3.1 finding S5. |
| S4 | LOW | Security | Variations and Extensions, "Real-time scoring at booking time" and "Patient-self-reschedule prompting" | Both extensions move PHI through additional egress paths (synchronous API from scheduling system; deep-links in SMS/email reminders). Real-time scoring may require Site-to-Site VPN or Direct Connect from on-premises EHRs. Self-reschedule deep-links should encode opaque tokens, not appointment context, because URLs traverse carrier networks, URL-shortener services, and analytics tools. |
| N1 | LOW | Networking | Prerequisites VPC row | CloudWatch monitoring (PutMetricData) endpoint not distinguished from Logs (recurring finding from Recipes 2.7-2.10 and 3.1 N1). EventBridge bus (`events`) vs Scheduler (`scheduler`) endpoints not distinguished (same as Recipe 3.1 N2). SageMaker `api`, `runtime`, `featurestore-runtime` endpoints not distinguished. |
| N2 | LOW | Networking | Prerequisites VPC row | Glue (`glue`) and Step Functions (`states`) interface endpoints not specified; both are required for the recipe's specific service mix when running in a private VPC. |
| V1 | LOW | Voice / Publication Readiness | Expected Results sample timestamps (`2026-05-12`, `2026-05-14`) | Future-dated timestamps will age awkwardly post-publication. Same observation as Recipe 3.1 V1. Fix: replace with placeholder pattern or add HTML-comment disclaimer. |
| V2 | LOW | Voice / Pedagogy | Step 5 baseline update, alpha=0.05 EMA decay factor comment | Decay-factor intuition not conveyed for non-ML readers. alpha=0.05 means ~14 observations to reach 50% of new value, ~60 observations to reach 95%. For once-quarterly primary care patients, ~15 years to converge. The choice of alpha has substantial implications and the recipe doesn't give the reader the tool to choose appropriately. Fix: expand the comment to give the half-life intuition and recommend alpha values per visit-frequency profile. |
| V3 | LOW | Voice / Publication Readiness | Cost Estimate row, Performance benchmarks table, transportation intervention extension (HTML-comment TODOs) | Industry-figure TODOs (no-show reduction percentage, transportation intervention effectiveness) should be resolved before publication. The aws-samples and AWS blog post forward placeholders read cleanly and can remain. |

---

## Recommended Actions (Priority Order)

1. **Fix the patient-baseline subsystem in a single coordinated pass** (Findings A1 and A2). Both findings are in the same subsystem and have a shared fix path:
   - Define `MIN_BASELINE_OBSERVATIONS` as a constant in Step 3 with default ~8 and visit-frequency-aware motivation.
   - Replace `empty_baseline()` with a Bayesian-prior initialization using a cohort-derived (or population) Beta prior with effective sample size ~10. Update the rolling-rate computation to be the Bayesian posterior rather than naive EMA.
   - Gate the baseline update in `on_appointment_outcome` on intervention status: only update the baseline when no intervention was applied; track intervened-observation count separately for analysis.
   - Update the prose in "Establishing a Patient-Level Baseline" to match what the pseudocode now does.
   - Coordinate with the Python companion to keep pseudocode-to-Python parity.

   This is the highest-priority fix because it addresses the only HIGH findings in the recipe, both in the same subsystem, and the central design hypothesis (the deviation framing) depends on the baseline subsystem being correct.

2. **Add outcome event idempotency to the outcome-joiner Lambda** (Finding A3). Derive a deterministic event key (`appointment_id + outcome`); conditional DynamoDB write to a `processed-outcomes` table before label and baseline operations. Add a "Trigger idempotency" bullet to "Why This Isn't Production-Ready." Strongly recommend a chapter-wide trigger-idempotency appendix to consolidate this recurring pattern (now eight recipes deep across Chapters 2 and 3).

3. **Add DLQ / poison-message handling for the outcome-joiner, routing, and deviation-calc Lambdas** (Finding A4). Add three SQS DLQs to the Architecture Diagram with `OnFailure` destinations configured. Add a one-line Prerequisites note tying DLQ discipline to the recipe's existing label-retention discussion.

4. **Add temporal validation to the retrain pipeline** (Finding A5). Time-based split first (validation = most recent 30 days), patient-stratified within each side. Add a one-paragraph note connecting the validation strategy to the seasonality failure mode the prose already identifies.

5. **Reframe the sample output's feature decomposition** (Finding A6). Either reframe as normalized feature importance (sums to 1.0) or as log-odds contributions with explanatory comment. Match what production explainability outputs typically look like.

6. **Add high-stigma specialty PHI minimization to outreach guidance** (Finding S1). Add a paragraph to the "PHI handling in the outreach messages" subsection addressing specialty-disclosure risk for SMS/voice/email reminders. Recommend per-clinic "reminder content sensitivity" flag in the patient preference store.

7. **Specify subgroup data governance at the infrastructure level** (Finding S2). Add a Subgroup data access row to Prerequisites; restrict read access to demographic store to specific roles; QuickSight queries against an aggregated subgroup-metrics table.

8. **Close the LOW security and networking findings** (S3, S4, N1, N2). Per-consumer IAM scoping examples; Variations subsection PHI-handling notes for real-time scoring and deep-links; VPC endpoint precision (CloudWatch monitoring, EventBridge bus vs Scheduler, SageMaker api/runtime/featurestore-runtime, Glue, Step Functions).

9. **Close the LOW voice findings** (V1, V2, V3). Replace future-dated timestamps with placeholders or add disclaimer. Expand the alpha=0.05 comment with the half-life intuition. Resolve the no-show reduction percentage and transportation intervention effectiveness HTML-comment TODOs before publication; the aws-samples and blog-post forward placeholders can remain.

---

## Notes for Editor

- Findings A1 and A2 are the only HIGH findings, both in the patient-baseline subsystem, and have a coordinated fix path. A single editorial pass on the `Establishing a Patient-Level Baseline` prose, the Step 3 routing pseudocode, the Step 5 outcome-handler pseudocode, and the corresponding Python companion functions (`_load_or_create_baseline`, `_update_patient_baseline`) addresses both findings together. The prose-vs-pseudocode gap closes when the baseline subsystem implements what the prose recommends.

- Coordinate with the existing code review (`reviews/chapter03.02-code-review.md`). The code review PASSed-with-reservations on three WARNINGs, none of which overlap with the HIGH or MEDIUM findings here. However, the A1 and A2 fixes must propagate to the Python companion in the same editorial pass because the Python implementation currently mirrors the broken pseudocode pattern. A re-review of the Python companion after the A1/A2 fixes would also pick up the original code-review WARNINGs (broken `assert` guard, missing `SSEKMSKeyId`, silent-success on unrecognized channel preference); a single coordinated pass on both files is more efficient than two passes.

- Finding A3 is the now-recurring trigger-idempotency pattern. With this finding flagged across eight consecutive recipes (2.4-2.10, 3.1, 3.2), the cookbook would benefit substantially from a shared appendix that covers the patterns once (S3 events with conditional DynamoDB writes, EventBridge bus → Lambda async with deterministic event keys, EventBridge Scheduler with deterministic Step Functions execution names, Kinesis with idempotent consumers, SQS with deduplication tokens). Each subsequent recipe could reference the appendix rather than repeat the discipline. A trigger-idempotency appendix is now the highest-leverage cookbook-wide editorial investment.

- Finding S1 is the now-recurring PHI-minimization-inside-the-BAA pattern, with the third distinct surface across the cookbook (Chapter 2: serialized prompt context; Recipe 3.1: examiner free-text reasoning; Recipe 3.2: patient-facing reminder content). A cookbook-wide PHI-minimization appendix would consolidate all three surfaces with one teaching pass.

- The Honest Take section is publication-ready and should be preserved verbatim in any editorial pass. The four-paragraph structure (feature engineering matters more than the model, the intervention is the product, the anomaly framing matters more than it looks, the portal-login-recency anecdote, the "build outcome capture first" ordering lesson, the closing trap warning about double-booking) is the kind of operations-engineer voice the cookbook is built on. The closing posture ("the intervention side of the pipeline is not a separate concern from the model; they have to be designed together") lands the right final tone.

- The Tuesday-morning vignette is the densest scheduling-operations writing in the cookbook to date and should not be shortened. The "seventy-two providers across fourteen clinics," "1,100 scheduled visits," "140 to 200 of those slots will go empty," and "she does this math every Tuesday" specificity is what establishes the recipe's authority. The five-part taxonomy (forgot, couldn't come, ghosted, tried-to-cancel, habitual) maps to real patient subtypes any clinic operations director would recognize and is the conceptual scaffolding the rest of the recipe is built on.

- The fairness section is the most substantive in Chapter 3 to date and the framing-level treatment ("a high-risk score is a signal to invest more in keeping the appointment, not less") is exactly the operational reframing this domain needs. The architectural artifacts that make subgroup monitoring binding (Finding S2) are the right operational backstop on the framing-level treatment.

- The risk profile of this recipe is similar to Recipe 3.1 (no LLM, no clinical-recommendation surface, no FDA exposure), with one addition: the fairness surface area is materially larger here. No-show prediction has well-documented disparate-impact pitfalls when the operational response to a high-risk score is exclusionary. The recipe correctly addresses the framing-level concern; readers will deploy this against varied operational policies, and the architectural artifacts that make subgroup monitoring binding (S2) are the right discipline to enforce.

- Style hygiene is clean: zero em dashes (direct U+2014 character check), eleven en dashes restricted to numeric ranges (consistent with Chapter 1 published precedent and Recipe 3.1). No marketing language, no documentation-voice. The 70/30 vendor balance is preserved: a reader on GCP or Azure could substitute their cloud's primitives without rewriting the conceptual sections.

- The HTML-comment TODO discipline is correct (six TODOs total, all forward-placeholder, no bracket-style visible TODOs). The no-show reduction percentage, performance benchmarks, and transportation intervention effectiveness TODOs should be resolved before publication; the aws-samples-repo and AWS-blog-post forward placeholders read cleanly in published output and can remain.
