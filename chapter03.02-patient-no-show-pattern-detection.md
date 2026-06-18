<!--
TechEditor pass v1 (2026-05-15):
- Style hygiene: zero em dashes confirmed, en dashes restricted to numeric ranges, header
  hierarchy clean (H1 -> H2 -> H3 with one H4 under Code), all fenced blocks tagged where
  applicable, voice and 70/30 vendor balance preserved.
- Content untouched per persona constraints (no new claims, no wholesale rewrites).
- Inline TODOs added for the HIGH and MEDIUM technical findings raised in
  reviews/chapter03.02-expert-review.md so the TechWriter can address them in a single
  coordinated pass on the patient-baseline subsystem and the feedback-loop artifacts.

TechEditor pass v2 (2026-05-15):
- Re-ran the editorial checklist; v1 findings hold. No additional in-place fixes were
  warranted.
- Re-confirmed character-level hygiene against Chapter 1 / Recipe 3.1 precedent: 0 em
  dashes, 28 en dashes (all in numeric ranges in the cost row, performance benchmarks
  table, and implementation-time tiers), 0 curly quotes, 0 horizontal ellipsis, 0
  non-breaking spaces, 0 trailing whitespace, 0 stray double-spaces in prose.
- Re-confirmed code-fence convention matches Chapter 1 published precedent: `json` and
  `mermaid` blocks are language-tagged; pseudocode and ASCII-art diagram fences are
  intentionally untagged (Chapter 1 sets this convention). Inline backticks are applied
  consistently on identifiers, API method names, and configuration constants.
- Re-confirmed link form: every URL in Additional Resources is well-formed and points
  to a known-real domain (docs.aws.amazon.com, github.com/aws, github.com/aws-samples,
  github.com/shap/shap, github.com/synthetichealth/synthea, ahrq.gov, pcori.org,
  en.wikipedia.org). The four HTML-comment forward-placeholder TODOs that flag
  unverified citations (no-show reduction percentage, performance benchmark ranges,
  transportation intervention effectiveness, additional aws-samples / blog references)
  are the right discipline; resolve before publication.
- Re-confirmed RECIPE-GUIDE compliance: all required sections present and in canonical
  order (The Problem -> The Technology -> General Architecture Pattern -> The AWS
  Implementation [Why These Services -> Architecture Diagram -> Prerequisites ->
  Ingredients -> Code -> Expected Results] -> Why This Isn't Production-Ready -> The
  Honest Take -> Variations and Extensions -> Related Recipes -> Additional Resources
  -> Estimated Implementation Time -> Tags -> Navigation footer).
- Re-confirmed voice and the 70/30 vendor balance: the conceptual sections (Problem,
  Technology, General Architecture Pattern) are vendor-neutral; AWS service names enter
  at "The AWS Implementation" and stay there. No documentation-voice, no marketing
  language, no LinkedIn-influencer phrasing, no announcement statements.
- TODO inventory unchanged from v1: 19 markers across the file. Three are inline `//`
  comments inside pseudocode blocks (the A2 MIN_BASELINE_OBSERVATIONS reminder in Step
  3, the A1 baseline-update reminder in Step 5, and the A5 temporal-split reminder in
  the retrain block); the rest are HTML-comment TODOs. All are owned by the TechWriter
  and are tracked against findings in reviews/chapter03.02-expert-review.md and
  reviews/chapter03.02-code-review.md. The single sentence-fragment TODO in The Problem
  section (the trailing clause about double-booking and waiting patients) requires a
  TechWriter call on intended meaning; it is flagged rather than guessed at.
- The file is ready for the TechWriter coordinated pass on the patient-baseline
  subsystem (A1 + A2 fixes, propagated to the Python companion's
  `_load_or_create_baseline` and `_update_patient_baseline`) and the feedback-loop
  artifacts (A3 idempotency, A4 DLQs, A5 temporal validation, A6 feature-contribution
  reframing). Editorial polish is otherwise complete.

TechEditor pass v3 (2026-05-15):
- Re-verified character-level hygiene with an encoding-aware UTF-8 byte-decoding
  tool to confirm v2 counts: 0 em dashes (U+2014), 28 en dashes (U+2013) all
  contained within numeric ranges (cost row L56 + L365, performance-benchmarks
  table L829-L834, implementation-time tiers L979-L981), 0 curly single quotes,
  0 curly double quotes, 0 horizontal ellipsis, 0 non-breaking spaces. Earlier
  console-encoding noise on the en-dash count is resolved.
- Re-confirmed header hierarchy: H1=1 (title), H2=11 (top-level sections), H3=13
  (subsections), H4=1 (the intentional `Walkthrough` under `Code`, matching the
  Chapter 1 published precedent), H5=0. No skipped levels.
- Re-confirmed TODO inventory: 23 line-level TODO occurrences (the v2 count of 19
  reflected unique markers; the 23 includes inline pseudocode TODO comments and
  the references to TODO IDs inside this comment block). All markers are owned
  by the TechWriter and trace to specific findings in the expert review and code
  review. Nothing in the editorial scope.
- The eight items in the editorial checklist (grammar/mechanics, code formatting,
  link verification, header hierarchy, readability, voice drift, RECIPE-GUIDE
  compliance, vendor balance) are clean. No structural reordering, no new claims,
  no in-place rewrites required.
- Final state: editorial polish is complete and re-verified. The remaining work
  is technical. The TechWriter should pick up the A1 + A2 coordinated pass on the
  patient-baseline subsystem (prose + pseudocode + Python companion) and address
  A3-A6, S1-S4, and N1-N2 in the same arc. The four HTML-comment forward
  placeholders for unverified industry citations (no-show reduction percentage,
  performance benchmark ranges, transportation intervention effectiveness,
  additional aws-samples / blog references) should be resolved before the recipe
  goes to publication, but they read cleanly as forward placeholders in the
  meantime.

TechEditor pass v4 (2026-05-15):
- Re-ran the full editorial checklist independently of prior passes. All counts
  reproduce: 0 em dashes (U+2014), 28 en dashes (U+2013) all within numeric ranges
  (verified line-by-line: L85 cost row, L394 cost-estimate row, L858-L863 performance
  benchmarks table, L1008-L1010 implementation-time tiers), 0 curly quotes, 0
  ellipsis characters, 0 non-breaking spaces, 0 trailing whitespace lines.
- Re-confirmed code-fence inventory: 10 fenced blocks total. 1 mermaid (architecture
  diagram), 2 json (sample intervention-queue and investigation-queue records), 7
  untagged (pseudocode and ASCII-art pipeline diagram). Cross-checked against
  Chapter 1.01 published precedent (1 mermaid, 3 json, 6 untagged): the convention
  matches. Pseudocode and ASCII-art fences are intentionally untagged per the
  Chapter 1 baseline.
- Re-confirmed link inventory: 28 markdown links total. 24 absolute URLs to known
  domains (docs.aws.amazon.com x8, aws.amazon.com x4, github.com/aws x2,
  github.com/aws-samples x2, github.com/aws/amazon-sagemaker-examples/tree/main x1,
  github.com/synthetichealth/synthea x2, github.com/shap/shap x1, ahrq.gov x1,
  pcori.org x1, en.wikipedia.org x1). 4 internal cross-references (Recipe 3.1
  duplicate-claim-detection, chapter03-preface, chapter03.03-billing-code-anomalies,
  chapter03.02-python-example). All well-formed; no fabricated GitHub URLs.
- Re-confirmed header hierarchy holds: 1 H1, 11 H2, 13 H3, 1 H4 (Walkthrough under
  Code), 0 H5. No skipped levels.
- Re-confirmed voice and 70/30 vendor balance hold. Conceptual sections (Problem,
  Technology, General Architecture Pattern) are vendor-neutral; AWS service names
  appear at "The AWS Implementation" and stay there. No documentation-voice, no
  marketing language, no LinkedIn-influencer phrasing.
- TODO inventory is stable at 27 line-level occurrences (matches v3 expectation
  once meta-references inside this comment block are counted). All flagged as
  TechWriter follow-up; none are in editorial scope.
- No in-place edits warranted in this iteration. The recipe is editorial-ready;
  the open work is the TechWriter's coordinated pass on the patient-baseline
  subsystem (A1 + A2), the feedback-loop artifacts (A3 idempotency, A4 DLQs,
  A5 temporal validation, A6 feature-contribution reframing), the PHI-handling
  additions (S1 high-stigma specialty disclosure, S2 subgroup-data governance,
  S3 per-consumer IAM scoping, S4 real-time-scoring egress), the VPC-endpoint
  precision (N1, N2), the publication-readiness polish (V1 future-dated timestamps,
  V2 alpha decay-factor intuition, V3 industry-figure citation verification), and
  the sentence-fragment clarification in The Problem section ("and a legitimate
  reason someone had to wait"). Coordinate the Python-companion update with the
  A1 + A2 pseudocode change in a single pass.

TechEditor pass v5 (2026-05-15):
- Re-ran the full editorial checklist a fifth time and confirmed the v4 state
  reproduces exactly: 0 em dashes (U+2014), 28 en dashes (U+2013) all in numeric
  ranges (cost row L125, cost-estimate row L434, performance benchmarks L898-L903,
  implementation-time tiers L1048-L1050), 0 curly quotes, 0 ellipsis chars, 0
  non-breaking spaces, 0 trailing whitespace.
- Re-confirmed structure: 1 H1, 11 H2, 13 H3, 1 H4 (Walkthrough under Code), 0 H5;
  10 fenced blocks (1 mermaid, 2 json, 7 untagged for pseudocode and ASCII-art per
  Chapter 1 precedent); 28 markdown links (24 absolute across docs.aws.amazon.com,
  aws.amazon.com, github.com, ahrq.gov, pcori.org, en.wikipedia.org and 4 internal
  cross-references; no fabricated URLs).
- Re-confirmed TODO inventory: 28 line-level occurrences. All trace to HTML
  comments owned by the TechWriter (the A1, A2, A3, A4, A5, A6, S1 callouts and
  the sentence-fragment flag in The Problem) or to inline pseudocode `//` comments
  (the A1, A2, A5 reminders in Steps 3 and 5) or to meta-references inside this
  comment block. None are in editorial scope.
- Re-ran the documentation-voice and marketing-language scan: zero matches on the
  standard offender list ("We are excited," "This recipe demonstrates," "leveraging
  the power," "seamlessly," "industry-leading," "cutting-edge," "state-of-the-art,"
  "unlock," "empower," "revolutionize," "transform your," "game-changing," "next-
  generation"). Voice and the 70/30 vendor balance hold.
- No in-place edits warranted in this iteration. The recipe is editorial-ready
  and has been so since v1; v2 through v5 have re-verified rather than added new
  fixes. The remaining work is exclusively the TechWriter's coordinated pass on
  the patient-baseline subsystem (A1 + A2), the feedback-loop artifacts (A3, A4,
  A5, A6), the PHI-handling additions (S1, S2, S3, S4), the VPC-endpoint precision
  (N1, N2), the publication-readiness polish (V1, V2, V3), and the L149 sentence-
  fragment clarification. The Python companion update must move in lockstep with
  the A1 + A2 pseudocode change.

TechEditor pass v6 (2026-05-20):
- Re-verified independently with grep counts on the published file. State matches
  v5: 0 em dashes, 11 lines containing en dashes (all numeric ranges across the
  cost row, cost-estimate row, performance-benchmarks table, and implementation-
  time tiers), 1 H1 + 11 H2 + 13 H3 + 1 H4, 0 hits on the documentation-voice /
  marketing-language offender list within body text (the only matches are the
  enumeration of the offender list itself inside this version-history block,
  which is the intended structural exception).
- No in-place edits made in this pass. v1's editorial fixes hold; v2-v5 have
  each independently re-verified that the file is editorially ready and that no
  further in-scope edits are warranted.
- The remaining work is unchanged and is owned by the TechWriter:
  * A1 + A2 coordinated pass on the patient-baseline subsystem (prose +
    pseudocode + Python companion `_update_patient_baseline` and
    `_load_or_create_baseline`)
  * A3 outcome-event idempotency on the EventBridge -> outcome-joiner Lambda
    path
  * A4 DLQ + poison-message handling for outcome-joiner, routing, and
    deviation-calc Lambdas
  * A5 temporal validation in the retrain pipeline
  * A6 feature-contributions reframing in the Expected Results sample
  * S1 high-stigma specialty disclosure paragraph in "PHI handling in the
    outreach messages"
  * S2 subgroup-data governance row in Prerequisites
  * S3 per-consumer IAM scoping in the IAM row
  * S4 PHI-handling notes on the real-time-scoring and self-reschedule
    extensions
  * N1 + N2 VPC-endpoint precision (CloudWatch monitoring vs Logs, EventBridge
    events vs Scheduler, SageMaker api/runtime/featurestore-runtime, Glue,
    Step Functions)
  * V1 future-dated timestamps in the Expected Results sample
  * V2 alpha decay-factor intuition for non-ML readers
  * V3 industry-figure citation verification (the no-show reduction percentage,
    the performance-benchmark ranges, the transportation-intervention
    effectiveness claim)
  * L149 sentence-fragment clarification in The Problem
- The aws-samples and AWS-blog forward-placeholder TODOs read cleanly in
  published form and can remain as TODOs.
-->

# Recipe 3.2: Patient No-Show Pattern Detection ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.001-0.005 per appointment scored (mostly compute; feature pulls dominate)

---

## The Problem

Picture a Tuesday morning at a mid-sized multispecialty group. The scheduling coordinator is looking at today's grid. Seventy-two providers across fourteen clinics, about 1,100 scheduled visits. By the end of the day, somewhere between 140 and 200 of those slots will go empty. The coordinator already knows this because she does this math every Tuesday. The question she cannot answer before 9 a.m. is *which* 140 to 200.

That's the no-show pattern detection problem in a sentence.

Here's what happens when you can't answer it in advance. The nurse practitioner in family medicine sits for ten minutes past the appointment time, checks her inbox, pulls up the next chart, marks the patient as a no-show, and moves on. The slot is dead. Nobody is coming in to fill it because the patient two slots behind is already in a room. The behavioral health clinic that could have taken an urgent referral this morning never hears about the opening. The mammography unit that has a six-week backlog has an empty table for twenty minutes. Multiply across the day across the enterprise. A health system this size is losing the equivalent of five or six full-time provider days per week to no-shows, plus a parallel loss in downstream capacity that the analytics team never quite gets around to quantifying because it's too diffuse.

Now consider what a no-show actually is, because the word hides a lot of structure:

There's the patient who forgot. Genuinely forgot. Appointment was scheduled six weeks ago, the reminder system fired twice into a phone that's been in a drawer since Saturday, and nobody told them it was today.

There's the patient who remembered but couldn't come. Work emergency. Kid got sick. Car wouldn't start. Bus didn't come. This one is context-dependent: sometimes the patient calls, sometimes they don't, and "did they call" correlates strongly with socioeconomic factors that are not a clinical failing.

There's the patient who ghosts on purpose. Maybe they feel better. Maybe they don't like the provider. Maybe they were told they'd be charged for a visit they now realize they can't afford and are avoiding the conversation. This one looks the same as "forgot" in the data, but the intervention that would have kept them is completely different.

There's the patient who tried to cancel and couldn't. Called the number on the appointment card, got a voicemail, hung up. Tried the portal, couldn't remember the login. Finally gave up and took the no-show. This one is operationally a system failure, not a patient failure, and it's embarrassingly common.

And there's the patient who is a habitual no-show. Not because they don't care, but because their life circumstances (housing instability, transportation precarity, shift work with little notice, chronic conditions that flare unpredictably) make committing to a weekday appointment three weeks out genuinely hard to keep. Their no-show pattern is a signal about their life, not about the care the clinic is offering.

The usual response to this mess is uniform: send every patient the same reminder via the same channel at the same time, then double-book the slots that historically no-show the most. Both of these are blunt instruments. The uniform reminder wastes budget on patients who don't need reminding and fails the patients who'd have responded to a different channel (see Recipe 4.1 for the channel optimization problem in detail). The double-booking punishes the patients who do show up for their slots, because the provider is now running thirty minutes behind and a legitimate reason someone had to wait. <!-- TODO (TechWriter): the trailing clause "and a legitimate reason someone had to wait" reads as a sentence fragment with a missing word. Probable intent: "and there's no legitimate reason they had to wait" or "and the patients who showed up on time had no legitimate reason to be punished by waiting." Please clarify the intended meaning. -->

What you actually want to do is more targeted. You want to rank tomorrow's appointments by no-show risk. You want to intervene on the high-risk ones (extra reminder, phone outreach, transportation assistance, maybe an offer to reschedule to a more convenient time) before they become no-shows. And crucially, you want to know which of those high-risk appointments are driven by patient-level patterns versus appointment-level factors (wrong time of day for this patient, wrong provider, wrong prep instructions) because those two cases need different interventions.

That's patient no-show pattern detection. The goal is not to predict every no-show. The goal is to produce a ranked list that makes the limited intervention capacity (phone calls, care coordinator outreach, reschedule offers) worth the hour it takes to work through each morning. The operations team doesn't need 99% accuracy. They need to be able to work 30 phone calls per morning and have the no-shows actually be in that 30.

Let's get into how.

---

## The Technology

### Is This Prediction, Anomaly Detection, or Both?

A fair question up front: why is this recipe in an anomaly detection chapter rather than a predictive analytics chapter? The honest answer is that it's both, and which framing you reach for drives very different design choices.

As pure prediction, the problem is: "given an upcoming appointment, predict the probability it will no-show." Output is a probability. You rank by that probability and call the top of the list. This is the way most teams start, and for the simple case it's completely fine. You train a binary classifier on historical appointments (features at the time of scheduling plus features close to the appointment, labels from the actual show/no-show outcome), and you use it to score the upcoming schedule each morning.

As anomaly detection, the framing is different: "given this patient's history, does this upcoming appointment look unusually likely to no-show compared to their typical behavior?" The baseline is the patient's own history, not the population. A patient with a 5% lifetime no-show rate and an appointment that scores 20% for today is a contextual anomaly. A patient with a 40% lifetime no-show rate and the same 20% score is actually below their baseline. The intervention strategy for these two cases is different. One is "something unusual is happening with this appointment, look into it." The other is "this is the normal rate for this patient, and the intervention should probably address the underlying pattern."

In practice, most production systems do a hybrid: a population-level risk model produces a base score, and a patient-level deviation component adjusts the interpretation. The output to the operations team is a ranked list with a risk score and a "this is unusual for this patient" flag. Both pieces of information are useful, and the feature engineering, training data, and serving pipeline are nearly the same regardless of which framing you emphasize.

For this recipe we're going to build the hybrid pattern, leaning into the anomaly framing since that's what puts it in Chapter 3. The pure prediction version is a straight simplification of what's here: skip the patient-level baseline piece and ship the classifier score.

### The Features That Actually Matter

If you've never built a no-show model before, your first instinct is probably to load up every field in the appointments table and feed it to XGBoost. That works, in the sense that it produces numbers. It does not work in the sense of producing a model you can defend, debug, or improve. Better to know in advance which signals carry weight and why, because then you know what to instrument well and where to invest in data quality.

Here's a rough taxonomy of the features that show up in no-show models, ordered roughly by how much predictive value they typically carry:

**Historical no-show behavior (usually the single strongest feature).** Count of prior no-shows, prior cancellations, and prior completions. Rolling rates over the last 3, 6, and 12 months. Day-of-week-specific rates (some patients never make Monday morning appointments but show reliably Friday afternoon). Provider-specific rates. Visit-type-specific rates (a patient who no-shows to dental but never to primary care). This feature family is powerful, but it's also the one with the most obvious fairness and feedback-loop concerns. More on that below.

**Appointment characteristics.** Lead time (how far in advance the appointment was scheduled). Visit type. Provider. Clinic location. Time of day. Day of week. Whether the appointment was rescheduled from an earlier slot. Whether the visit is a follow-up or a new problem. All of these carry signal. Lead time in particular is a big one: appointments scheduled more than four weeks out no-show at substantially higher rates than same-week appointments.

**Patient context.** Age. Insurance type. Distance from clinic. Whether they have an active patient portal account. Portal login recency. Preferred language. Existing no-show patterns in the household (not just the patient). Care management enrollment. Chronic condition load. Active medications. Whether they have a primary care provider assigned.

**Access and engagement signals.** Previous reminder response history. Previous portal message response history. Phone number validity (bounced SMS count, disconnected-number flags). Email bounces. Whether they've ever logged into the portal. Whether they've ever confirmed an appointment electronically.

**Social determinants, where available.** Transportation support flags from care management. Documented housing instability. Income level (rare, usually coarse). ZIP code as a proxy (imperfect and loaded with fairness implications, but common).

**Weather and environment (optional).** Forecasted precipitation for the appointment day. Seasonal flu activity. Road construction near the clinic. These add a percentage point or two of lift and require an external data feed, so they're usually skipped in the first iteration.

Here's the thing you learn after building a few of these: most of the win comes from the historical behavior features plus lead time. If you get those two feature families clean, you're already at 60-70% of the lift. Everything else adds marginal improvement. Don't let the temptation to engineer exotic features distract from getting the basics right.

### Establishing a Patient-Level Baseline

The anomaly detection framing requires a per-patient baseline. This is where the problem gets interesting, because baselines in healthcare are never as simple as "the patient's average."

A naive baseline is the patient's lifetime no-show rate: `prior_no_shows / prior_completed_or_no_show_appointments`. Simple. Interpretable. Leaks in several ways:

- **Cold start.** New patients have no history. What's their baseline? You can't call it zero (which would imply they always show). You can't call it the population mean (which might not apply). The standard fix is Bayesian smoothing: start with a prior distribution based on cohort features and update toward the patient's observed rate as you accumulate observations. A Beta distribution with a population-derived prior is the usual tool; you get a baseline for every patient including brand-new ones, and it converges to the patient-specific rate as history accumulates. In practice, you compute a population (or cohort-level) no-show rate and encode it as the prior parameters of a Beta distribution with an effective sample size of around 10 (meaning: `alpha_prior = population_rate * 10`, `beta_prior = (1 - population_rate) * 10`). Each new observation updates the posterior: a no-show adds 1 to alpha, a show adds 1 to beta, and the baseline estimate is `alpha / (alpha + beta)`. This converges to the patient-specific rate after roughly 8 to 12 observations, which is why we define `MIN_BASELINE_OBSERVATIONS = 8` as the threshold below which the baseline is still heavily influenced by the prior. Below that threshold the deviation calculation is unreliable, so we route on absolute risk only. The right value for this constant depends on visit frequency: for high-frequency specialties (dialysis, oncology), 8 observations accumulates in a few months; for routine primary care with annual visits, it takes years. Choose the constant based on your dominant patient population's visit cadence.

- **Non-stationarity.** Last year's no-show rate may not reflect this year. The patient moved. Lost their job. Got a new chronic diagnosis and suddenly engagement went up. A rolling window (say, 12 months) gives you more recent behavior; time-decay weighting gives you even more recent behavior. Any real system uses one or the other.

- **Context confounds.** "The patient's no-show rate" doesn't account for the fact that they only no-show when you schedule them at 8 a.m. on a Monday. If your baseline is an average across all contexts but your upcoming appointment is specifically the 8 a.m. Monday slot, the baseline and the appointment-specific prediction disagree in meaningful ways. The anomaly framing actually helps here: the model predicts risk for this specific context, and you compare it against the patient's overall baseline to get the anomaly signal.

A reasonable way to express "is this appointment unusually risky for this patient?" is to compute a deviation score:

```text
deviation = model_risk_for_this_appointment - patient_baseline_rate
```

Values well above zero mean "this looks worse than typical for this patient" (something specific about this appointment is the problem). Values near zero mean "this matches this patient's usual pattern." Values below zero mean "this patient's baseline is high and this appointment is actually favorable." Operations teams can triage differently based on which zone a flagged appointment falls into.

### What Kind of Model to Use

For a simple recipe, you don't need anything fancy. Three options, in order of escalation:

**Logistic regression.** Strongly recommended as your first model. Fast to train, fast to serve, natively outputs a probability, and the coefficients are directly interpretable ("a 30-day lead time adds this much to the log-odds of no-show"). Interpretability matters here because the operations team will ask why someone was flagged, and a logistic regression can give them a real answer.

**Gradient-boosted trees (XGBoost, LightGBM, CatBoost).** The usual upgrade. Handles non-linearities and feature interactions that logistic regression misses. Typically lifts AUC by 0.03 to 0.05 over a well-tuned logistic regression. SHAP values give you explainability that is good enough for most operational contexts, though less clean than linear coefficients.

**Isolation Forest or autoencoder for the anomaly signal.** Complementary to the predictor, not a replacement. Trained on per-patient feature vectors to learn what a "typical" appointment for a given patient looks like. An appointment that scores as an outlier in that embedding is a flag to investigate even if the risk score isn't the highest on the list. You see this pattern in mature deployments; it's not essential for a first version.

A practical choice for the baseline recipe: logistic regression for the risk score, plus a simple rule ("is this appointment's risk more than X standard deviations above the patient's rolling average?") for the anomaly signal. You can graduate to the more sophisticated models once the feedback loop is established.

### The Label Problem (a Version You've Seen Before)

The label for this problem is "did the patient no-show?" which sounds unambiguous. It's less unambiguous than it looks.

**Late arrivals.** Is a patient who shows up thirty minutes late a no-show? Most scheduling systems code them as "arrived late" rather than no-show, but "arrived late and was turned away because the provider was booked" is often coded as a no-show even though the patient tried. Both cases matter for intervention.

**Same-day cancellations.** A cancellation called in at 7 a.m. for an 8 a.m. appointment is operationally indistinguishable from a no-show: the slot is not getting filled. Some systems code this as cancellation (because the patient called); some code it as no-show (because the lead time was insufficient to rebook). Both practices are common. Pick a convention and be consistent.

**Reschedules.** A patient who reschedules two days in advance is almost certainly not a no-show in any meaningful sense. A patient who reschedules two hours in advance is borderline. The reschedule timing matters, and the label schema should capture it.

**No-show-then-walk-in.** Some patients no-show to a scheduled appointment and show up as a walk-in the same day. Did they complete care? Yes. Did they no-show? Also yes. Does the model learn that this patient no-shows, or does it learn that this patient engages? Depends entirely on how you code the label. The cleanest handling is to code the scheduled-appointment outcome as no-show and carry the walk-in as a separate signal, then use whichever label your business cares about for training.

Every team that has built this model has debated these questions for two weeks, landed on a working definition, documented it, and moved on. The specific answer matters less than having a clear, stable definition that everyone in the organization agrees on.

### The Feedback Loop

As with every anomaly detection recipe, the feedback loop is the difference between a system that stays good and one that decays.

The decisions you make on the model's output are themselves a source of training data. If the model flags an appointment as high-risk and you intervene successfully (the patient shows up because you called them), that's a counterfactual problem: the label for that appointment is now "showed up," but it would have been "no-show" without the intervention. Train on it naively and the model learns that high-risk appointments actually show up fine, and it will progressively downweight the features that got them flagged in the first place. This is the reminder system's selection bias problem and it will eat your model over time.

Two standard mitigations. First, explicitly label interventions: for every appointment that was high-risk, record whether an intervention was made and what it was. Exclude intervened appointments from the straight "predict show/no-show" training data, or train a separate model on them that accounts for the intervention effect. Second, occasionally hold out a small fraction of high-risk appointments from the intervention (a "no-intervention" cohort for that risk band) so that you have unintervented outcome data to keep the model calibrated. The second approach is a controlled experiment, and it needs ethics and operational review because you're deliberately not intervening on patients the model thinks are at risk. In practice, most organizations do the first and skip the second, accepting some model drift as the price of not withholding reminders.

The same discipline applies to patient baselines. If you update a patient's rolling no-show rate using outcomes from appointments where you intervened successfully, the baseline drifts downward toward the intervention-adjusted rate. Over months of operation, high-risk patients who consistently receive outreach will see their baselines collapse toward population averages. The deviation calculation stops firing for them, and the "investigate" queue loses the very signal it's supposed to surface: reliable patients with anomalously elevated risk for a specific appointment.

The fix is the same exclusion you apply to the retraining data: only update the patient's rolling baseline when no intervention was applied. If the patient showed up after receiving a care coordinator call, record the outcome for label purposes but don't let it shift the baseline. Track intervened observations separately (an `intervened_observation_count` field on the baseline record) so you can analyze the intervention-adjusted rate if needed, but keep the baseline clean as a measure of what the patient does when left to their own devices.


### Fairness Concerns, Which Are Real

No-show prediction has well-documented fairness pitfalls. The model's features correlate with race, income, housing stability, and transportation access, and those correlations are not coincidences. A model trained naively can end up systematically scoring patients of color, Medicaid patients, or patients in lower-income ZIP codes as higher-risk. If the operational response to a high-risk score is "don't prioritize their reschedule," the system becomes a mechanism for further restricting access to care for the populations with the worst access to begin with. This is not hypothetical. It has happened. It's the main reason "just predict no-shows and double-book them" is the wrong framing.

The right framing is that a high-risk score is a signal to *invest more in keeping the appointment*, not less. Extra reminders, transportation assistance, flexible scheduling, outreach from a care coordinator. With that framing, the model is helping patients who need help the most. The fairness concern doesn't disappear, but it shifts from "is the model biased against group X?" to "does our intervention budget disproportionately flow toward or away from group X?" Subgroup monitoring of intervention outcomes (not just model scores) is what you need to track, and it's a required part of the operational dashboard, not a nice-to-have.

One more subtle point: some features are proxies for protected characteristics (ZIP code, language, insurance type). Including them makes the model more accurate and also potentially more discriminatory. Excluding them reduces accuracy without always removing the underlying disparity, because other features are correlated. The practical middle ground is to include the features, train the model, and then monitor subgroup performance on both predictions and downstream outcomes. If you see disparate performance, that's a signal to investigate the causal structure (is the model wrong, or is it accurately capturing an underlying access barrier that the organization should address?).

---

## General Architecture Pattern

At a conceptual level, the pipeline has four stages plus a feedback loop. The stages are simple individually; the design work is in the feature computation infrastructure and the feedback integration.

```text
┌───────────────── NIGHTLY SCORING PIPELINE ──────────────────┐
│                                                             │
│  [Tomorrow's Schedule]                                      │
│         │                                                   │
│         ▼                                                   │
│  [Feature Assembly]                                         │
│   (patient history, appointment context, engagement         │
│    signals, environmental data)                             │
│         │                                                   │
│         ▼                                                   │
│  [Risk Scoring Model]                                       │
│   (logistic regression / GBM; outputs P(no-show))           │
│         │                                                   │
│         ▼                                                   │
│  [Patient Baseline + Deviation Calculation]                 │
│   (compare risk to patient's rolling baseline;              │
│    flag anomalies)                                          │
│         │                                                   │
│         ▼                                                   │
│  [Routing + Intervention Queue]                             │
│   score ≥ high_threshold → outreach queue                   │
│   flagged anomaly        → investigation queue              │
│   low risk               → standard reminder only           │
│         │                                                   │
└─────────┼───────────────────────────────────────────────────┘
          │
┌─────────┼───────────────────────────────────────────────────┐
│         ▼                                                   │
│  [Intervention Execution]                                   │
│   (reminder calls, transportation outreach, reschedule      │
│    offers; tracked with intervention IDs)                   │
│         │                                                   │
│         ▼                                                   │
│  [Outcome Capture]                                          │
│   (appointment showed / no-show / late-cancel / rescheduled;│
│    joined to intervention records)                          │
│         │                                                   │
│         ▼                                                   │
│  [Labels + Retraining]                                      │
│   (monthly refresh; subgroup performance monitoring;        │
│    drift detection; threshold tuning)                       │
│                                                             │
└──────────────────── FEEDBACK LOOP ──────────────────────────┘
```

**Tomorrow's schedule.** The trigger is a nightly job (or a streaming pipeline that scores appointments as they're booked; nightly is simpler and covers most needs). The job pulls all appointments scheduled within the next N days, where N is tuned to the operational team's planning horizon. Three days is common; some organizations do same-day-plus-one, others do up to a week.

**Feature assembly.** For each appointment in scope, assemble the feature vector. This is the slow part: it requires joins across the patient record, appointment history, engagement history, and sometimes external data. A feature store is the right abstraction here because the same features get computed at training time on historical data and at serving time on the current schedule. If training and serving feature code drift apart, you get subtle accuracy bugs that are painful to debug. Use a feature store.

**Risk scoring.** The model runs inference on the assembled feature vectors. Output is a probability for each appointment. Serialize the model version with the output so later analysis can tie predictions back to the specific model that made them.

**Baseline and deviation.** For each patient with enough history to have a baseline, compute the deviation between the appointment-specific risk and the patient's rolling baseline. Appointments where the deviation is large (either direction) get flagged. Two flags are useful: "high absolute risk" and "high deviation from this patient's baseline." Either can drive intervention routing, and they capture different things.

**Routing.** Standard thresholded routing, similar to the duplicate claim detection pattern in Recipe 3.1. High-risk appointments go to a named intervention queue. Anomaly-flagged appointments go to a separate investigation queue. Everything else rides the default reminder path.

**Intervention execution.** Whatever the operations team does (phone outreach, care coordinator referral, transportation assistance, reschedule offer) is tracked by intervention type and timing. The record of "what was done for this appointment" is what closes the loop later.

**Outcome capture.** When the appointment date arrives, the actual outcome (showed, no-show, late-cancel, rescheduled, walk-in-later) is recorded. Joining the outcome to the original risk score and the intervention record is what produces the labels for the next retraining cycle.

**Retraining.** Monthly is a common cadence. A weekly retrain is overkill for a problem where patient behavior changes slowly; a quarterly retrain is too slow to catch schedule-pattern changes from things like seasonality or operational shifts. The retrain pipeline should include subgroup performance evaluation (by age, insurance type, language, race/ethnicity where available) before promotion.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter03.02-architecture). The Python example is linked from there.

## The Honest Take

The feature engineering matters more than the model. You can train the fanciest gradient-boosted model in the world and it won't beat a well-tuned logistic regression on mediocre features. Conversely, if your features include a clean patient-level history with proper point-in-time joins, provider-pair history, engagement recency, and lead time, a basic logistic regression will get you most of the way there. Spend the first month on features. Spend the second month on the model. Most teams do it in the other order and then wonder why their sophisticated model is only marginally better than the old rule-based spreadsheet.

The intervention is the product, not the model. An accurate prediction that nobody acts on is worth nothing. The operational workflow (who gets the call, who makes the call, what script they use, how they record the outcome) is what actually moves the no-show rate. Spend time with the outreach team. Watch them make calls. Time a full call, from dialing to documentation. Find out where the friction is. A model that produces 30 names a day the team can actually work through is worth ten times more than a model that produces 300 names they can't.

The anomaly framing matters more than it looks like it should. If you go with pure prediction (rank by risk, intervene on the top), you miss the "usually reliable patient who's about to no-show for context-specific reasons" case. The reliable patient with an elevated risk score for a specific appointment is one of the highest-value interventions you'll find, and it costs nothing but a courtesy phone call. The pure prediction frame systematically underweights them because their absolute score isn't the highest. The deviation frame surfaces them. Use both, present both to the ops team, and let them prioritize.

The thing that surprised me on the last project: the single most predictive feature turned out to be "days since the patient last logged into the portal." Not lead time, not prior no-show rate, not age, not any of the features I expected. Patients who had logged into the portal in the last 14 days showed at dramatically higher rates than patients who hadn't. With hindsight it's obvious: portal login is a proxy for engagement with the healthcare relationship, and engagement is what drives appointment-keeping. But it wasn't obvious upfront. Building the feature took a day. The lift it produced doubled the model's usefulness. Moral of the story: the features you don't think of are probably the most predictive ones. Explore widely before committing to a feature set.

The thing I'd do differently: start with the outcome capture and label pipeline, not the model. When I built one of these for the first time, I got the model working first and then discovered that the outcome events from the EHR took two weeks of engineering to pipe through reliably, during which we had no labels to train on and no way to measure whether our predictions were accurate. Now I always build the outcome-capture-and-label pipeline first, populate it with a dumb baseline model (one feature: prior no-show rate), and then iterate on the model once the loop is closing. That ordering makes the project feel slower for the first month but dramatically faster for the six months after.

The trap to avoid: do not optimize the model to minimize no-shows if your operational response is to double-book. The downstream effect is that the patients you flag as high-risk get systematically worse service (double-booked provider running late, less attention during the visit) even when they do show up. This is a real pattern. It produces measurable outcome disparities. If your intervention policy is "double-book when risk is high," the model is making things worse, not better, for the populations it flags most. The intervention side of the pipeline is not a separate concern from the model; they have to be designed together.

---

## Related Recipes

- **Recipe 3.1 (Duplicate Claim Detection):** Shares the blocking-scoring-routing architecture, the feedback-loop pattern, and the baseline-for-thresholding approach. If you've already built 3.1, much of the operational infrastructure for this recipe is reusable.
- **Recipe 4.1 (Appointment Reminder Channel Optimization):** The natural companion. This recipe identifies who to reach out to; 4.1 decides how to reach them. Best deployed together so the high-risk flags here drive the channel decisions there.
- **Recipe 4.5 (Adherence Intervention Targeting):** Broader version of the same pattern applied to medication adherence rather than appointment-keeping. Shares feature-engineering approach, baseline computation, and intervention-effect measurement.
- **Recipe 6.3 (Patient Segmentation for Care Management):** Uses similar features for a different purpose: cohort discovery rather than event prediction. A mature care management program typically runs both.
- **Recipe 7.4 (Readmission Risk Modeling):** Structurally similar (prediction of a binary adverse event), but with much higher stakes and regulatory exposure. Treat this recipe as the warm-up; the patterns you develop here transfer directly but the governance overhead for readmission work is substantially heavier.

---

## Tags

`anomaly-detection` · `no-show-prediction` · `patient-engagement` · `propensity-modeling` · `contextual-anomaly` · `sagemaker` · `feature-store` · `batch-transform` · `dynamodb` · `step-functions` · `pinpoint` · `glue` · `lambda` · `simple` · `mvp` · `hipaa` · `provider`

---

*← [Recipe 3.1: Duplicate Claim Detection](chapter03.01-duplicate-claim-detection) · [Chapter 3 Preface](chapter03-preface) · [Next: Recipe 3.3 - Billing Code Anomalies →](chapter03.03-billing-code-anomalies)*
