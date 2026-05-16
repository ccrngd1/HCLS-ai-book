# Recipe 4.4: Wellness Program Recommendations ⭐⭐

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$0.005-0.02 per recommendation (depends on uplift model serving and LLM tailoring)

---

## The Problem

Open enrollment season just ended at a mid-sized self-insured employer. The benefits team, working with the health plan's wellness arm, has stood up a slate of programs: a smoking cessation program with telephonic coaching, a 12-month diabetes prevention program (DPP) that follows the CDC curriculum (16 weekly core sessions plus 6 monthly post-core sessions), a weight-management program with an app and weekly group sessions, a stress-reduction program built on cognitive behavioral therapy techniques, and a sleep-improvement pilot. Each program has a per-participant cost the plan negotiated with the vendor, a minimum enrollment to keep the per-person cost reasonable, and a finite number of seats per cohort.

The plan's analytics team runs the obvious query against the member population: who has clinical risk factors that match each program? Out comes a list. 12,800 members have a smoking-related diagnosis or self-reported smoking status. 31,000 have a BMI over 30. 14,400 have prediabetes (HbA1c 5.7 to 6.4). 22,000 have a behavioral health diagnosis or have filled an antidepressant in the last year. The team feels good about the list. They run a campaign. They send 80,000 outreach emails over the next two weeks. The "interested" link gets clicked by 1,400 people. 380 people fill out the enrollment form. 220 people show up to the first session. By month three, 95 people are still active. By month twelve, 47 people complete the program.

The benefits team writes up the results. The "completion rate" looks fine, in context: most published DPP completion rates are in the 40 to 50 percent range of starters, and they're at about 50 percent. The vendor invoices for everyone who attended at least one session (220 people times the per-participant rate). The plan paid for outreach to 80,000 people. The members who needed the program most (the highest-risk diabetics, the heaviest smokers) are mostly not in the 47. The ones who completed were the ones who would have made the lifestyle change anyway, with or without a program. The ones who really would have benefited never opened the email, or opened it and decided it wasn't for them, or signed up and didn't show up, or showed up once and never came back.

Meanwhile, in another folder of the plan's data warehouse, there's a 56-year-old member with prediabetes, a recent quit-smoking attempt that didn't stick, mild depression, a sleep complaint, and a job that requires a 90-minute commute. The campaign sent her four separate program emails over two weeks, each from a different vendor portal, each pitched as if she had nothing else going on in her life. She deleted all four. She did not enroll in anything. She is the entire reason the wellness budget exists. The system did not see her, in any meaningful sense.

This is what wellness program recommendation actually looks like in practice. It's not "find the people who match the eligibility criteria"; that's a SQL query, and it doesn't scale to outcomes. It's "of the people who match, who is actually likely to engage, complete, and benefit, given everything else we know about them, and what's the right program at the right time pitched in the right way?" That's a recommender problem, and it's a multi-objective one: clinical fit, predicted engagement, capacity awareness, equity, and (the one nobody likes to talk about) plan ROI. Mess up the multi-objective balance and you get the campaign above. Get it right and you get programs that change member outcomes and pay for themselves.

A second wrinkle that makes wellness recommendation distinct from anything in Recipes 4.1, 4.2, or 4.3: the unit of "success" is months long. A patient confirming an appointment (4.1) is a same-day signal. A patient clicking on an education article (4.2) is a same-day signal. A patient choosing a provider (4.3) is a same-week signal. A patient enrolling in a 12-month DPP, attending sessions, losing weight, and (the actual outcome you cared about) not progressing to type 2 diabetes within three years, is a multi-year signal. The recommender has to make decisions every day with feedback loops measured in months and quarters. That changes the architecture, the evaluation strategy, and the kinds of mistakes you can afford to make.

The third wrinkle: capacity. Each program has a maximum number of slots per cohort, often a minimum to be financially viable, and a fixed cohort start cadence (every quarter, every month). A great recommender that nominates 5,000 high-fit members for a 200-seat smoking cessation cohort is not actually a great recommender; it's an allocation problem disguised as a relevance problem. The system needs to balance who is most likely to benefit against who is most likely to engage against who has been allocated a slot already, with a capacity-aware re-ranker that respects the real constraints.

So the problem statement, again, is deceptively simple: given a member with a rich health profile, a slate of available wellness programs each with their own eligibility criteria and capacity, and a body of historical engagement data, decide which programs to surface to this member, in what order, with what messaging, at what time. Not the same email blast for everyone with prediabetes. The right small set of programs, targeted to the members most likely to engage and benefit, allocated under real-world capacity constraints.

We're going to build the recommender. We're also going to spend a lot of this recipe on the parts that are easy to skip: uplift modeling (predicting who will benefit from being recommended a program, not just who will engage), capacity-aware allocation, longitudinal engagement tracking, and the equity considerations that come with deciding which members get an outreach email and which don't. Because the difference between a wellness recommender that works and one that doesn't is mostly in those parts.

Let's get into how you build it.

---

## The Technology: Uplift Modeling Plus Capacity-Aware Allocation

### What Kind of Recommendation Problem Is This, Really?

Recipes 4.2 and 4.3 were classic recommendation problems: pick relevant items from a catalog. This one looks like the same problem but it's structurally different in three ways:

- **The "item" is an intervention, not a piece of content.** A wellness program does something to the member's life: takes their time, asks them to change behavior, costs the plan money. Recommending it has a real cost regardless of whether they engage. So the question isn't "what would this member like?" It's "what intervention would actually change this member's trajectory, given everything we know about them?"
- **The objective is causal, not correlational.** A member who would have quit smoking on their own does not need a smoking cessation program. A member who would never quit no matter what you offer is not helped by one either. The recommender wants to find the members in the middle: people whose outcome is *changed* by being offered the program. This is a counterfactual question, and answering it well requires uplift modeling, not standard predictive modeling.
- **The supply is constrained.** The catalog has finite slots. Recommending program X to a member is committing capacity that another member can't have. The recommender is implicitly making allocation decisions even when nobody told it to.

Put those together and you get a problem where the math under the hood is different from a content recommender. You're not just predicting "will this member click"; you're predicting "if we offer this member program X versus program Y versus nothing, which produces the best outcome, and how much capacity does that consume?" The answer involves uplift, multi-armed allocation, and a fairness layer that prevents the optimization from concentrating opportunity on the easiest-to-help members at the expense of the hardest-to-help.

### The Logical Stages

Most wellness program recommenders, regardless of vendor, end up with a stack that looks like this:

**Stage 1: Eligibility filters.** Hard "shall not recommend" rules. The member must meet the program's clinical criteria (BMI threshold, HbA1c range, smoking status, behavioral health diagnosis), must be active on the plan, must have given consent for outreach if your jurisdiction or plan policy requires explicit consent, must not have completed or recently disenrolled from the same program. Eligibility is not a relevance feature; it's a correctness boundary, and it lives at the top of the stack.

**Stage 2: Need scoring.** For each eligible (member, program) pair, compute a clinical-need score: how strongly does the member's profile suggest this program would be clinically useful? A member with HbA1c of 6.3, a BMI of 32, and a family history of diabetes scores higher for DPP than a member with HbA1c of 5.8 and a BMI of 27. This is classic predictive modeling: a logistic regression or gradient-boosted model trained on historical "would have benefited from program" labels. It does not by itself tell you whether to recommend the program; it tells you whether the member's clinical picture is consistent with the program's intended population.

**Stage 3: Engagement prediction.** For each (member, program) pair, predict the probability the member will engage if recommended. A 28-year-old with a smartphone-native health app history is more likely to engage with the app-based weight management program than a 72-year-old who has never used the patient portal. Engagement prediction is what turns "eligible and clinically appropriate" into "actually likely to enroll, attend, and persist." Trained on historical (recommendation, response) data.

**Stage 4: Uplift modeling.** This is the part most wellness programs skip and shouldn't. For each (member, program) pair, estimate the *causal* effect of recommending the program: how much does the recommendation change the member's probability of a good outcome, compared to not recommending? Uplift partitions members into rough segments:

- **Persuadables.** Members whose outcome is positively changed by the recommendation. These are the ones you want to target.
- **Sure things.** Members who will have the good outcome with or without the recommendation. Targeting them looks great in your enrollment numbers and adds zero incremental value.
- **Lost causes.** Members who won't have the good outcome regardless. Targeting them wastes outreach capacity.
- **Sleeping dogs.** Members whose outcome is *negatively* affected by the recommendation. Surprisingly real; an aggressive smoking cessation pitch to a member already managing fragile mental health stability can backfire.

A recommender that ranks by predicted engagement alone is going to over-target sure things (they enroll, they complete, they look great in the dashboard) and under-target persuadables (the ones for whom the program actually moves the needle). Uplift ranking explicitly inverts that bias.

The standard techniques for uplift estimation are well-documented and increasingly accessible: T-learner, S-learner, X-learner, R-learner, causal forests, and deep counterfactual networks. For a starter implementation, an X-learner or causal forest on top of well-engineered features works fine and is auditable. Save the deep counterfactual networks for when you have a dedicated causal-inference team and the data volume to support them.

**Stage 5: Multi-program ranking.** A member might be eligible for multiple programs: a smoker with prediabetes is eligible for both smoking cessation and DPP. The ranker combines the need score, engagement prediction, and uplift estimate per program and produces a per-member ranked list. The combination function is a policy decision, not a model decision: do you weight clinical need higher than engagement likelihood (more equity-oriented), or weight engagement higher (more conversion-oriented)? Both are defensible, and the recipe shouldn't pretend one is "right." Make the policy explicit and reviewable.

**Stage 6: Capacity-aware allocation.** Now combine across members. The DPP cohort has 200 seats. There are 1,400 members where DPP is the top-ranked recommendation. The allocator has to pick the 200 (or fewer, leaving headroom for late additions and equity adjustments). This is a constrained-optimization problem: maximize total expected uplift across the allocation, subject to per-program capacity and any minimum-cohort-size constraints. In practice, a greedy allocator (sort by uplift, assign top members to slots until capacity is reached) works well as a starter; graduate to integer programming (Recipe 14.x territory) when the constraints multiply.

**Stage 7: Outreach orchestration.** The allocation produces a list of (member, program, recommended_action) triples. The outreach orchestrator turns those into actual contacts: an email through the channel optimizer (Recipe 4.1), an in-portal nudge, a primary-care-team alert with talking points, a flag in the next telephonic outreach call list. The orchestrator respects member-stated preferences and contact-frequency caps so the same member doesn't get four wellness outreach touches in two weeks.

**Stage 8: Engagement tracking and longitudinal evaluation.** Outreach goes out. Members open it, ignore it, click through, enroll, attend, drop out, complete. Each event flows back into the system. Short-horizon engagement metrics (open, click, enrollment) feed the engagement-prediction model. Medium-horizon metrics (program completion) feed the uplift model. Long-horizon metrics (clinical outcomes 6-12 months out, downstream cost) feed the program-level ROI evaluation that informs which programs the plan keeps in its slate next year.

### Uplift Modeling, Briefly

A primer, because uplift gets used as a buzzword and the actual mechanics matter.

The standard predictive modeling question is: given features X, what is the probability that outcome Y occurs? `P(Y | X)`. Standard machine learning techniques solve this well.

The uplift question is different: given features X and a treatment T (the recommendation, the program, the intervention), what is the *change* in probability of Y caused by T? `P(Y | X, T=1) - P(Y | X, T=0)`. The sneaky part: you can never observe both `Y | T=1` and `Y | T=0` for the same person; the person either got the treatment or they didn't. So you have to estimate the counterfactual.

Three common practical approaches:

**T-learner (two-model approach).** Train one model on the treated cohort (`P(Y | X, T=1)`), train a second model on the untreated cohort (`P(Y | X, T=0)`). Predict both for any new member, subtract. Simple. Works fine when the treated and untreated cohorts are roughly balanced. Suffers when one cohort is small or when treatment assignment was strongly confounded.

**S-learner (single-model approach).** Train a single model on all data with treatment as a feature. To predict uplift, predict `Y` with `T=1` and with `T=0`, subtract. Sometimes better than T-learner when treatment effects are subtle and the model can borrow strength across cohorts. Sometimes worse, because the model can underweight the treatment feature.

**Causal forests.** A random-forest variant explicitly designed to estimate heterogeneous treatment effects. Implemented in mature libraries (`econml` from Microsoft, `causalml` from Uber, `grf` in R). Robust, interpretable in the same ways tree models always are, and a sensible production starting point.

The hard part of uplift modeling is not the algorithm; it's the data. You need historical data where some people got the treatment and some didn't. Ideally that assignment was randomized, because then the comparison is causally clean. In practice, wellness program recommendations are rarely randomized: members opted in or were targeted by some prior rule, which means treatment assignment is confounded with the very features you'd want to use as predictors. Three ways to handle this honestly:

- **Run randomized pilots.** Carve out a few thousand members who match a program's eligibility, randomly assign half to receive the recommendation and half to a control arm, and let the experiment run. Gold standard for uplift training data, expensive in member experience and program capacity, but worth it for the calibration value.
- **Use propensity-score matching or weighting.** Estimate each member's probability of having received the treatment historically given their features (the propensity score), and reweight or match treated and untreated cohorts so the comparison is balanced on observables. Doesn't fix unobserved confounding, but materially helps.
- **Be honest about the floor.** Without either of the above, your "uplift" estimates may largely reflect engagement propensity rather than true causal lift, and you should not treat the model as more reliable than it is. Flag this in evaluation. Plan a randomized pilot for the next program cycle.

### Engagement Prediction Versus Uplift: The Difference Matters

Worth its own paragraph because teams confuse these constantly. **Engagement prediction** answers "if we recommend this, will the member click and enroll?" It's a behavioral question. **Uplift** answers "if we recommend this, will the member's clinical outcome be better than if we hadn't?" It's a causal question.

A member who routinely enrolls in every wellness program offered, completes them at high rates, and would have made the lifestyle change without the program (a "sure thing") has high engagement probability and low uplift. A skeptical member with high clinical need who would actually quit smoking if given the right structured support, but only opens emails 30 percent of the time, has medium engagement probability and high uplift. The first member is the easy enrollment that pads your numbers. The second member is the one the program exists to help.

A recommender that uses engagement prediction alone, without uplift, will systematically over-target the first member and under-target the second. That's not a subtle bias; it's the central failure mode of wellness recommenders that don't think causally.

### Capacity Constraints Are a First-Class Concern

You'll see capacity treated as an afterthought in a lot of personalization writeups. In wellness recommendation, it's structural. Three reasons:

- **Program economics.** Vendors quote per-participant rates with floors and ceilings. Below the minimum cohort size, the per-person cost is unviable. Above the maximum, quality of facilitation degrades (group sessions become unwieldy, telephonic coaches' caseloads exceed their bandwidth).
- **Cohort-based start cadences.** Many programs (DPP especially) are cohort-based: cohorts that span the program's full duration (12 months for CDC-recognized DPP, with weekly meetings for the first six months and monthly meetings after that). A member you decide to recommend in week 3 of the cohort cycle either waits for the next cycle (and may lose interest) or gets routed to a less-preferred alternative. Allocation has to respect the cycle. Several vendors offer DPP-style programs of shorter duration; the CDC's National DPP recognition standards require 12-month delivery, so abbreviated variants are not "the CDC curriculum" even when they cite it. The architecture in this recipe is duration-agnostic; align the catalog's cohort cadence with whichever curriculum your contracted vendor delivers.
- **Outreach throughput limits.** Telephonic outreach has finite caller capacity. Email has fewer hard limits, but contact-frequency caps (no more than N wellness touches per member per quarter) act as a soft capacity constraint that the allocator has to respect.

A capacity-aware allocator turns the per-member ranking problem into a population-level optimization: given the slate of programs with their per-program capacities and the member-program ranked lists, maximize the population-level expected uplift subject to the constraints. For a starter implementation, a greedy allocator (sort all member-program pairs by uplift, assign top pairs to capacity until exhausted) is fine. The fancy version is integer programming; Recipe 14.x covers that family.

### Equity Is Structural Here, Too

Like Recipe 4.3, this recipe has equity considerations baked into the architecture. Three patterns to watch for:

**Engagement-prediction bias.** Engagement-prediction models trained on historical data will tend to score members from previously-engaged populations higher and members from historically-underserved populations lower, because that's what the data reflects. A capacity-aware allocator that ranks purely by predicted enrollment will systematically under-target the populations that most need the wellness investment. Mitigations: train uplift, not engagement, as the primary signal; reserve a portion of capacity for high-need under-engaged cohorts; monitor enrollment distributions by cohort.

**Outcome-prediction bias.** Outcome models trained on prior cohorts will reflect whatever bias was in those cohorts. If your DPP completion data over-represents one demographic group, the model will treat outcomes for under-represented groups as more uncertain or more pessimistic. Stratified evaluation (`AUC by cohort`, `calibration by cohort`) catches this. Bias-corrected training (reweighting, fairness-constrained losses) addresses it.

**Capacity allocation as rationing.** When you have 200 DPP slots and 1,400 high-fit members, the allocation is a rationing decision. "Maximize expected uplift" sounds technocratic and is, in practice, a value statement. If the high-fit members are concentrated in a small cohort, that cohort gets the allocation; the other cohorts wait. Many plans require explicit equity floors in the allocator: "at least N percent of seats reserved for members in the lowest-engagement-history quartile." Document the policy. Audit it.

### Where LLMs Fit (and Don't)

Same answer as 4.2 and 4.3, with a wellness-specific twist:

- **Eligibility filtering, need scoring, engagement prediction, uplift estimation, capacity allocation.** Not the LLM's job. These are deterministic or model-driven and need to be auditable.
- **Outreach message tailoring.** A member with prediabetes whose recommended program is DPP gets a personalized message that draws on their context: a sentence acknowledging their recent lab result, a sentence explaining what DPP is in plain language, a sentence framing the time commitment realistically. An LLM is great at producing that text from a structured input. Keep the LLM on the presentation layer.
- **Care-team talking points.** When the system flags a member's wellness recommendation to their primary care team, an LLM can generate a one-paragraph briefing for the clinician: the member's relevant context, why this program was selected, suggested talking points for the next visit. Same pattern as 4.2's clinical-note-summarization adjacency.
- **Member-facing conversational interfaces.** A chatbot that helps a member understand the program, ask questions, and complete enrollment is a Recipe 11.x problem; the recommender feeds it the structured recommendation, the chatbot does the conversation.

What the LLM does not do: pick the program. The recommender picks the program. The LLM packages it.

### Where This Sits in the Chapter

Recipes 4.1 through 4.3 built the personalization infrastructure: patient profile store, engagement event pipeline, content recommendation patterns, fairness re-ranking. Recipe 4.4 reuses all of it and adds three new capabilities: uplift modeling, capacity-aware allocation, and longitudinal outcome tracking. The patient-profile DynamoDB table from 4.1 is the same table. The engagement-event Kinesis stream is the same stream (with new event types added: `program_recommended`, `program_enrolled`, `program_session_attended`, `program_completed`, `program_dropped_out`). The cohort dashboards are the same dashboards (with new metrics added: per-program enrollment rate, completion rate, uplift estimate by cohort).

Looking forward, Recipes 4.5 (Medication Adherence Intervention Targeting) and 4.7 (Care Management Program Enrollment) reuse the uplift-and-allocation pattern almost wholesale. The uplift-modeling investment you make in 4.4 is reusable infrastructure for the rest of the chapter. The capacity allocator becomes more sophisticated in 4.7 and graduates to formal optimization in Chapter 14, but the bones are the same.

---

## General Architecture Pattern

The pipeline has four logical components: a member-feature ingestion path that prepares per-member uplift inputs, a program-catalog ingestion path that maintains the slate of available programs and their capacities, a batch recommendation path that runs periodically to produce the (member, program) allocation, and a feedback path that captures engagement and outcome signals to refine the models.

```
┌──────── MEMBER FEATURE INGESTION (continuous) ────────────┐
│                                                            │
│  [EHR / Claims / HRA]   [Engagement History]   [SDOH]      │
│            │                    │                  │       │
│            └─────────┬──────────┴──────────┬───────┘       │
│                      ▼                     ▼               │
│            [Build per-member feature vector:               │
│             clinical risk, behavioral history,             │
│             prior program engagement, preferences]         │
│                      │                                     │
│                      ▼                                     │
│            [Persist to feature store keyed on member_id]   │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌──────── PROGRAM CATALOG INGESTION (low cadence) ──────────┐
│                                                            │
│  [Vendor Portal Integrations]   [Plan Configuration]       │
│            │                            │                  │
│            └─────────────┬──────────────┘                  │
│                          ▼                                 │
│            [Program record: clinical eligibility,          │
│             cost, capacity, cohort cadence,                │
│             outcome metrics, exclusion rules]              │
│                          │                                 │
│                          ▼                                 │
│            [Persist to program-catalog store]              │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌──────── BATCH RECOMMENDATION RUN (e.g., weekly) ──────────┐
│                                                            │
│  [Trigger: scheduled job + cohort calendar]                │
│           │                                                │
│           ▼                                                │
│  [Stage 1: eligibility filters                             │
│   (clinical criteria, plan active, consent,                │
│    not currently enrolled, not recently disenrolled)]      │
│           │                                                │
│           ▼                                                │
│  [Stage 2: need scoring                                    │
│   (clinical-need model per (member, program))]             │
│           │                                                │
│           ▼                                                │
│  [Stage 3: engagement prediction                           │
│   (P(enroll | recommended) per (member, program))]         │
│           │                                                │
│           ▼                                                │
│  [Stage 4: uplift estimation                               │
│   (causal forest / X-learner per program)]                 │
│           │                                                │
│           ▼                                                │
│  [Stage 5: per-member ranking                              │
│   (combine need + engagement + uplift                      │
│    per documented policy weights)]                         │
│           │                                                │
│           ▼                                                │
│  [Stage 6: capacity-aware allocation                       │
│   (greedy or LP-based, with equity floors                  │
│    and contact-frequency caps)]                            │
│           │                                                │
│           ▼                                                │
│  [Stage 7: outreach orchestration                          │
│   (channel optimizer, message tailoring,                   │
│    care-team alerts, contact-cap accounting)]              │
│           │                                                │
└───────────┼────────────────────────────────────────────────┘
            │
            ▼
     [Member Receives Outreach / Engages / Enrolls]
            │
┌───────────┼────────────────────────────────────────────────┐
│           ▼                                                │
│  [Engagement events: opened, clicked, enrolled,            │
│   attended, dropped_out, completed]                        │
│           │                                                │
│           ▼                                                │
│  [Short-horizon: feed engagement-prediction model]         │
│           │                                                │
│           ▼                                                │
│  [Medium-horizon (months): feed uplift training            │
│   data, including matched control via                      │
│   propensity-score adjustment or pilot RCT arms]           │
│           │                                                │
│           ▼                                                │
│  [Long-horizon (months-years): feed program-level          │
│   ROI and clinical-outcome evaluation]                     │
│           │                                                │
│           ▼                                                │
│  [Cohort dashboards: enrollment by cohort,                 │
│   completion by cohort, uplift estimates by                │
│   cohort, capacity utilization]                            │
│                                                            │
└──────────────────── FEEDBACK PATH ─────────────────────────┘
```

**Member feature ingestion is continuous and broad.** The per-member feature vector pulls from many sources: claims (diagnoses, utilization, medications), EHR (problem lists, vitals, labs if available), the health risk assessment if the member has filled one out, prior wellness program participation, channel-engagement history (the same data 4.1 builds on), and SDOH features (geographic, socioeconomic, transportation) where available. The features land in a feature store keyed on member_id so the batch recommendation run can pull them in bulk without re-deriving. Feature freshness varies by source: claims arrive on a 24-48 hour lag, HRA data is annual, channel-engagement is near-real-time. The batch run pulls the latest available value per feature.

**Program catalog ingestion is low cadence and human-curated.** Programs change quarterly or seasonally, not hourly. The program record captures everything the recommender needs: clinical eligibility (exact criteria), capacity (slots per cohort, minimum enrollment, cycle cadence), cost (per-participant rate), exclusion rules (e.g., not eligible if currently in another behavioral health program), outcome metrics (what the program is trying to achieve, what the historical completion rate looks like). New programs go through a clinical and contracting review before appearing in the catalog. Programs that get retired stay in the catalog with a `status: retired` flag so historical engagement data can still be joined.

**Batch recommendation is periodic, not real-time.** Wellness recommendations don't need sub-second latency. A weekly batch run that produces the next week's outreach list is fine. A monthly run is also fine for some programs. The cohort calendar (DPP cohort starts the first Monday of each month, smoking cessation is a rolling enrollment with a per-week intake limit) drives the run schedule. The batch nature of the run is a feature, not a limitation: it lets the allocator see all members at once and make capacity-aware decisions, rather than serving real-time requests in isolation.

**Outreach orchestration ties this recipe to Recipe 4.1.** The recommender produces (member, program, message_template, urgency) triples. The channel optimizer from 4.1 picks the right channel and timing per member. The message-tailoring step (an LLM call with a structured prompt) renders the per-member message text. The contact-frequency cap (a "no more than 2 wellness touches per member per month" rule) lives between the recommender and the orchestrator, and trims the outreach list down to what's allowed.

**Feedback is multi-horizon.** Short-horizon engagement events (opened, clicked, enrolled) feed the engagement-prediction model and can be incorporated into the next weekly batch run. Medium-horizon completion data (12 months for DPP completion, 6 to 12 months for smoking cessation quit-status; DPP retention at month 6, the end of the core phase, is a useful intermediate proxy) feeds the uplift model and is incorporated on a slower retraining cadence. Long-horizon clinical outcomes (HbA1c trajectory over 18 months, not progressing to diabetes diagnosis over 3 years, smoking-related healthcare cost trajectory) feed program-level ROI evaluation, run annually or semi-annually, and inform whether a program stays in the slate.

**Equity instrumentation is built in.** Every batch run produces cohort-sliced metrics: who got recommended, who didn't, by demographic and engagement-history cohorts. Dashboards highlight drift in those distributions. Equity floors in the allocator (capacity reserved for under-engaged cohorts, capacity reserved for highest-clinical-need members regardless of engagement prediction) are configurable policy levers that the operations team can tune.

**Care-team integration is a parallel feedback loop.** Some plans want the primary care team to know about wellness recommendations: "your patient was recommended for DPP this week; here's the structured talking points." The recommender writes those alerts into the EHR's inbox or care-team dashboard. The PCP's response (endorsed, declined, deferred) is itself a signal that flows back to refine the recommender; a PCP override on a recommendation is a strong negative label that should be respected and learned from.

---

## The AWS Implementation

### Why These Services

**Amazon SageMaker for the model training and serving stack.** Three models live here: the clinical-need scorer (gradient-boosted, multi-output), the engagement predictor (gradient-boosted binary classifier), and the uplift estimator (causal forest or X-learner). SageMaker Training Jobs handle the periodic retraining. For inference, the batch nature of the recommendation run favors SageMaker Batch Transform (run a job, score the entire eligible population, write results back to S3) over a real-time endpoint. Batch Transform is dramatically cheaper for this workload because you don't pay for an idle endpoint between batch runs. SageMaker is HIPAA-eligible under BAA. <!-- TODO: confirm SageMaker Batch Transform's current HIPAA eligibility and the specific instance types appropriate for the model sizes implied here. -->

**Amazon SageMaker Feature Store for the per-member feature vector.** The recommender consumes a few hundred features per member: clinical risk indicators, prior engagement aggregates, channel preferences, SDOH proxies, recent activity. SageMaker Feature Store is designed for exactly this: an offline store backed by S3 + Glue (for batch training and batch inference) and an optional online store backed by DynamoDB (for real-time lookups by other systems that need the features). The batch run reads from the offline store. Recipe 4.7 (Care Management Enrollment) and Recipe 4.5 (Adherence Targeting) reuse the same feature definitions, which is the whole point of a feature store: features defined once, consumed many times.

**Amazon DynamoDB for the program catalog and the recommendation log.** The program catalog is a small set of records (tens to low hundreds of programs across the slate), accessed by program_id. DynamoDB is overkill in scale terms but right in operational terms: HIPAA-eligible, encryption at rest with customer-managed KMS, point-in-time recovery, low operational burden. The recommendation log captures each (member, program, run_date, scores, allocated) row from each batch run, and is the join point for downstream engagement attribution.

**Amazon DynamoDB for the patient profile and engagement history.** Same `patient-profile` table from Recipe 4.1. New attributes added on the existing schema: `prior_program_participation` (a list of past program enrollments with outcomes), `wellness_outreach_recent` (a count of outreach touches in the last 30 days, used by the contact-frequency cap), and `wellness_consent` (an explicit flag for whether the member has opted in to wellness outreach where applicable).

**Amazon S3 for the data lake and recommendation outputs.** The batch recommendation run reads features from S3 (the offline feature store), reads the eligible-member list from S3 (precomputed by an upstream Glue job), and writes the (member, program, score) recommendation table to S3. The outreach orchestrator reads from this same S3 location. Engagement events accumulate in S3 (via Kinesis Firehose) for long-horizon evaluation.

**AWS Glue and Amazon Athena for the eligibility-filter and outcome-evaluation pipelines.** Eligibility filtering is a SQL-shaped problem: "members where HbA1c is between 5.7 and 6.4 in the last 12 months and BMI is over 25 and not currently enrolled in DPP." Glue jobs query the data lake on the batch schedule and produce the per-program eligible-member list. Athena powers the cohort dashboards and the program-level ROI queries. Both services support encryption at rest with KMS and IAM-controlled access.

**AWS Step Functions for the batch orchestration.** The eight-stage batch pipeline is a natural Step Functions workflow: trigger on schedule, run eligibility (Glue), run scoring (SageMaker Batch Transform jobs in parallel for each program; either a Map state with concurrency or a parallel-state fan-out, never a sequential outer loop), run uplift (separate Batch Transform), run allocation (Lambda), write outreach list (Lambda), trigger orchestrator (Lambda invoking 4.1's APIs). Step Functions gives you visibility into per-stage failures, automatic retry with backoff, and a clean DLQ for runs that fail mid-pipeline.

**Amazon EventBridge for run scheduling and program-catalog change events.** EventBridge schedules the weekly batch run. EventBridge rules route program-catalog change events (a vendor adjusting capacity, a program pausing for a quarter) to the appropriate Lambda for catalog updates. EventBridge also routes care-team override events (a PCP declining a recommendation) into the engagement-event pipeline.

**Amazon Kinesis Data Streams for engagement events.** Same engagement-event bus from 4.1 and 4.2 and 4.3. New event types: `program_recommended`, `program_outreach_sent`, `program_outreach_opened`, `program_enrolled`, `program_session_attended`, `program_completed`, `program_dropped_out`, `pcp_override`. The attribution Lambda picks up wellness-related events, joins them to the recommendation log in DynamoDB, persists the joined record into the engagement table, and emits cohort-sliced metrics.

**Amazon Bedrock for outreach message tailoring and PCP talking-point generation.** A small LLM call (Claude Haiku, Nova Lite, or Llama-class) takes a structured input (the recommendation, the member's relevant context, the program's pitch) and produces a personalized outreach message in the member's preferred language. A second prompt template, fed the same structured input, produces a PCP talking-point briefing that goes into the EHR inbox or care-team dashboard. Bedrock is HIPAA-eligible under BAA. Confirm in your service terms that prompts and completions are not used to train the underlying foundation models and are not retained beyond the request lifecycle. <!-- TODO: confirm Bedrock service terms and per-model data-handling guarantees at the time of build; the eligible-model list and BAA coverage have been evolving. -->

**AWS Lambda for the per-stage glue logic.** The allocator (Stage 6), the orchestrator (Stage 7), the engagement-attribution worker, and the contact-cap enforcer all run as Lambdas. The allocator is the only Lambda where size is a real concern: integer-programming libraries are bulky. For the greedy allocator described in this recipe, a pandas-and-numpy implementation fits comfortably under the Lambda 250 MB layer ceiling. Graduate to a containerized Lambda (10 GB image limit) when you move to the LP-based allocator in Recipe 14.x.

**Amazon SES (or a contracted outreach platform) for member-facing email.** Email is the most common outreach channel for wellness programs. SES under BAA handles the bulk send with deliverability monitoring. For SMS, push, or in-portal nudges, the orchestrator hands off to whatever channels Recipe 4.1 already integrated with. <!-- TODO: confirm SES HIPAA eligibility and BAA scope at the time of build; SES has been HIPAA-eligible but verify. -->

**Amazon QuickSight for the operations dashboards.** Cohort-sliced enrollment, completion, and uplift metrics need to be visible to the wellness operations team, the medical director, and the equity committee. QuickSight on Athena gives them a managed dashboard tier with row-level security so the same dashboards can be filtered to a specific cohort or program without rebuilding.

**AWS KMS for encryption, CloudTrail for audit, CloudWatch for operations.** Same PHI infrastructure pattern as previous recipes. Customer-managed keys per data store. CloudTrail data events on the patient-profile and engagement tables. CloudWatch alarms on batch-run failures, DLQ depth, and per-cohort metric drift.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Sources
      A1[Claims and EHR]
      A2[Health Risk Assessment]
      A3[Engagement History]
      A4[SDOH Sources]
      A5[Vendor Catalog Feeds]
    end

    A1 -->|Daily ETL| B1[Glue Jobs]
    A2 -->|Annual| B1
    A3 -->|Streaming| B1
    A4 -->|Periodic| B1
    A5 -->|Catalog updates| C1[Lambda\ncatalog-sync]

    B1 --> D1[SageMaker Feature Store\noffline + online]
    C1 --> D2[DynamoDB\nprogram-catalog]

    E1[EventBridge\nweekly schedule] --> F1[Step Functions\nbatch-recommendation]

    F1 --> G1[Glue\neligibility filter]
    G1 --> G2[S3\neligible-members]
    G2 --> H1[SageMaker Batch Transform\nneed-scorer]
    G2 --> H2[SageMaker Batch Transform\nengagement-predictor]
    G2 --> H3[SageMaker Batch Transform\nuplift-estimator]
    H1 --> I1[Lambda\nper-member-rank]
    H2 --> I1
    H3 --> I1
    I1 --> I2[Lambda\nallocator]
    I2 --> I3[DynamoDB\nrecommendation-log]
    I2 --> I4[Lambda\norchestrator]

    I4 --> J1[Bedrock\nmessage-tailoring]
    I4 --> J2[DynamoDB\npatient-profile]
    I4 --> J3[Recipe 4.1\nchannel-optimizer]
    J3 --> K1[SES / SMS / Portal]
    I4 --> K2[EHR Care-Team Inbox]
    J1 --> K1
    J1 --> K2

    K1 -.Engagement events.-> L1[Kinesis\nengagement-stream]
    K2 -.PCP override events.-> L1
    L1 --> L2[Lambda\nattribution]
    L2 --> L3[DynamoDB\nengagement-events]
    L2 --> L4[Kinesis Firehose]
    L4 --> L5[S3\ndata-lake]
    L5 --> L6[Glue + Athena\noutcome-evaluation]
    L5 --> L7[QuickSight\ndashboards]
    L3 --> M1[SageMaker Training\nperiodic retrain]
    M1 --> H1
    M1 --> H2
    M1 --> H3

    style D1 fill:#9ff,stroke:#333
    style D2 fill:#9ff,stroke:#333
    style I3 fill:#9ff,stroke:#333
    style J2 fill:#9ff,stroke:#333
    style L3 fill:#9ff,stroke:#333
    style L5 fill:#cfc,stroke:#333
    style L1 fill:#f9f,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon SageMaker (Training, Batch Transform, Feature Store), Amazon DynamoDB, Amazon S3, AWS Glue, Amazon Athena, AWS Step Functions, Amazon EventBridge, Amazon Kinesis Data Streams, Amazon Kinesis Data Firehose, AWS Lambda, Amazon Bedrock, Amazon SES, Amazon QuickSight, AWS KMS, Amazon CloudWatch, AWS CloudTrail. |
| **IAM Permissions** | Per-Lambda least-privilege: `sagemaker:CreateTransformJob` and `sagemaker:DescribeTransformJob` scoped to specific model ARNs; `dynamodb:GetItem` / `BatchWriteItem` / `UpdateItem` scoped to specific tables; `bedrock:InvokeModel` on specific foundation-model ARNs; `s3:GetObject` / `PutObject` scoped to feature and recommendation buckets; `kinesis:PutRecord` on the engagement stream; `ses:SendEmail` scoped to the BAA-covered identity. Never `*`. <!-- TODO: pair these actions with one or two scoped Resource ARN examples so a reader copying into an IAM policy doesn't default to `Resource: *`. Same chapter-wide pattern flagged in 4.1, 4.2, 4.3 reviews. --> |
| **BAA** | AWS BAA signed. All services in the architecture must be HIPAA-eligible: SageMaker (including Feature Store and Batch Transform), DynamoDB, S3, Glue, Athena, Step Functions, EventBridge, Kinesis, Firehose, Lambda, Bedrock, SES, KMS are on the HIPAA Eligible Services list. <!-- TODO: confirm Bedrock + the specific LLM models you select are eligible at the time of build; verify SES eligibility entry; confirm SageMaker Feature Store eligibility. --> |
| **Encryption** | DynamoDB: customer-managed KMS at rest. S3: SSE-KMS with bucket-level keys. Kinesis and Firehose: server-side encryption. SageMaker training and inference: VPC-only, with KMS keys for model artifacts and Feature Store offline storage. All Lambda log groups KMS-encrypted. The recommendation log and engagement events are PHI: a (member_id, program_id, score) row implicitly reveals clinical context (the member meets DPP eligibility, the member is being targeted for a behavioral health program). Treat as PHI from day one. |
| **VPC** | Production: Lambdas in VPC. SageMaker training jobs, Batch Transform jobs, and Feature Store online store run in VPC. VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis, Firehose, KMS, CloudWatch Logs, SageMaker Runtime, Step Functions (`states`), EventBridge (`events`), Glue, Athena, STS, SES. NAT Gateway only if calling external services without VPC endpoints (e.g., a vendor's outreach platform); restrict egress with security groups (no `0.0.0.0/0` egress on Lambda subnets). VPC Flow Logs enabled. Vendor program-catalog feeds may need a Direct Connect tunnel or PrivateLink connection rather than NAT egress. |
| **CloudTrail** | Enabled with data events on the patient-profile table, program-catalog table, recommendation-log table, and engagement-events table. Data events on the S3 buckets containing per-member feature snapshots and recommendation outputs. |
| **Equity Governance** | Document the allocator's policy weights (need vs. engagement vs. uplift trade-off), the equity floors (capacity reserved for under-engaged cohorts, capacity reserved for highest-clinical-need members), and the cohort-monitoring thresholds before launch. The cross-functional review committee (medical director, equity lead, data science, vendor management, member services) signs off on the policy and reviews quarterly. |
| **Sample Data** | A starter set of (synthetic) members with realistic clinical profiles ([Synthea](https://github.com/synthetichealth/synthea) for synthetic patient encounters), a small program catalog (3-5 programs spanning smoking cessation, weight management, DPP), and historical engagement data (synthetic or de-identified from prior cohorts). For uplift training, a randomized pilot cohort is the gold standard; in development, simulated treatment-effect data lets you validate the modeling pipeline before running real members through it. |
| **Cost Estimate** | At a 400,000-member health plan with a slate of 6 programs and a weekly batch run touching ~80,000 eligible members per run: SageMaker Batch Transform (3 models per run, ~80K rows per run, weekly): roughly $50-150/month at modest instance sizes. SageMaker Feature Store offline store: $50-100/month. SageMaker training (monthly retraining of 3 models): $50-150/month. DynamoDB on-demand: $50-150/month. Lambda + Step Functions: $50-100/month. Bedrock message tailoring (~10K outreach messages per week, Haiku-class): $200-400/month. SES (~40K emails per week with BAA): $20-40/month. S3 + Glue + Athena: $100-300/month. QuickSight: $50/user/month for authors plus reader fees. Estimated total: $700-1,800/month range for a regional plan, before vendor program costs. <!-- TODO: replace with verified, current pricing once the implementing team can validate against the AWS Pricing Calculator. --> |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon SageMaker** | Hosts the clinical-need scorer, engagement predictor, and uplift estimator; runs training and Batch Transform jobs |
| **Amazon SageMaker Feature Store** | Per-member feature vector reused across this recipe and Recipes 4.5 and 4.7 |
| **Amazon DynamoDB** | Stores the program catalog, recommendation log, patient profiles (extended from Recipe 4.1), and engagement aggregates |
| **Amazon S3** | Hosts the offline feature store, eligible-member lists, recommendation outputs, training data, and engagement data lake |
| **AWS Glue** | Eligibility-filter ETL, feature aggregation, and outcome-evaluation jobs |
| **Amazon Athena** | SQL access to the data lake; powers cohort dashboards and program-level ROI queries |
| **AWS Step Functions** | Orchestrates the weekly batch recommendation pipeline with retry, DLQ, and per-stage visibility |
| **Amazon EventBridge** | Schedules the batch run; routes program-catalog change events and PCP override events |
| **Amazon Kinesis Data Streams** | Carries engagement events (recommended, opened, enrolled, attended, completed, dropped, override) into attribution |
| **Amazon Kinesis Data Firehose** | Lands engagement events into S3 Parquet for long-horizon evaluation and ranker training data prep |
| **AWS Lambda** | Runs the allocator, orchestrator, attribution worker, and contact-cap enforcer |
| **Amazon Bedrock** | Hosts the LLM for member-facing message tailoring and PCP talking-point generation |
| **Amazon SES** | Bulk email delivery under BAA for wellness outreach |
| **Amazon QuickSight** | Operational dashboards for wellness operations team, medical director, and equity committee |
| **AWS KMS** | Customer-managed encryption keys for all PHI-containing stores |
| **Amazon CloudWatch** | Operational metrics, cohort-sliced enrollment and completion dashboards, alarms |
| **AWS CloudTrail** | Audit logging for all PHI-related API calls |

---

### Code

> **Reference implementations:** Useful aws-samples patterns for this recipe:
> - [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): XGBoost and SageMaker Batch Transform notebooks that mirror the per-program scoring pattern used here.
> - [`amazon-sagemaker-feature-store-end-to-end-workshop`](https://github.com/aws-samples/amazon-sagemaker-feature-store-end-to-end-workshop): End-to-end Feature Store usage that maps directly onto the per-member feature pipeline.
> - [`amazon-bedrock-workshop`](https://github.com/aws-samples/amazon-bedrock-workshop): Demonstrates structured-output prompting with Claude Haiku and equivalents, applicable to the message-tailoring step.
> <!-- TODO: confirm the current names and locations of these aws-samples repos. The list of SageMaker and Bedrock related repos has been reorganizing. -->

#### Walkthrough

**Step 1: Build the eligible-member list per program.** Eligibility is a SQL-shaped filter applied to the data lake. For each program in the catalog, a Glue job pulls members who satisfy the program's clinical criteria, are active on the plan, have given consent for outreach if required, and are not currently enrolled or recently disenrolled. The result is written back to S3 as a per-program eligible-member list. Skip this and you'll waste downstream model inference on members who can't ever be allocated.

```
FUNCTION build_eligible_member_lists(programs, run_date):
    FOR each program in programs:
        // Pull the program's eligibility criteria from the catalog. Each
        // program's record contains the structured criteria the Glue job
        // can compile into a parameterized SQL query.
        criteria = program.eligibility_criteria
            // e.g., { hba1c_min: 5.7, hba1c_max: 6.4, hba1c_window_days: 365,
            //         bmi_min: 25, smoking_status: null, age_min: 18, age_max: 75 }

        // Compile to SQL against the Glue Data Catalog. The data lake has
        // member-level tables for diagnoses, labs, vitals, claims, and
        // engagement aggregates that this query joins.
        eligible_query = build_eligibility_sql(criteria, program.exclusion_rules)
            // - clinical inclusion: HbA1c, BMI, smoking, behavioral health flags
            // - eligibility hygiene: plan_active = true, consent_for_wellness = true
            // - prior-state exclusions: not currently enrolled in this program,
            //   not enrolled in conflicting program, not recently disenrolled
            //   (typical exclusion: 6 months since last touch)
            // - capacity-feasibility: cohort starts within recommendation horizon

        results = Athena.StartQueryExecution(query = eligible_query,
                                              output_location = S3_ELIGIBLE_BUCKET)
        wait_for_query(results.query_id)

        // Persist the eligible-member list as a per-program S3 object,
        // partitioned by run_date for traceability.
        S3.put(
            bucket = "wellness-eligible-members",
            key    = "run_date=" + run_date + "/program=" + program.program_id + "/members.parquet",
            body   = athena_to_parquet(results)
        )

        emit_metric("eligibility_filter_applied", value = count(results), dimensions = {
            program_id: program.program_id,
            run_date:   run_date
        })
```

**Step 2: Score clinical need, engagement, and uplift per (member, program) pair.** Three SageMaker Batch Transform jobs run in parallel for each program: the clinical-need model, the engagement-prediction model, and the uplift estimator. Each consumes the eligible-member list and the per-member feature vector, and writes per-program scores back to S3. The need model says "is the member in the program's intended population." The engagement model says "if recommended, will the member enroll." The uplift model says "would the program change the member's outcome." Skip the uplift and you ship a recommender that targets sure things. Submit all per-program jobs in parallel; total wall-clock time is bounded by the slowest single Batch Transform job, not the sum across programs.

```
FUNCTION score_eligible_population(programs, run_date):
    // Submit all jobs in parallel; do not wait between programs.
    // Step Functions Map with concurrency, or a parallel-state fan-out,
    // are both reasonable implementations. The wrong implementation is
    // the sequential outer-loop one.
    job_handles = []

    FOR each program in programs:
        eligible_path = "s3://wellness-eligible-members/run_date=" + run_date +
                        "/program=" + program.program_id + "/members.parquet"

        // Need score. Single multi-output model trained across programs;
        // input is the per-member feature vector, output is one score per
        // program. We slice to this program's column.
        need_job = SageMaker.CreateTransformJob(
            transform_job_name = "need-" + program.program_id + "-" + run_date,
            model_name         = NEED_MODEL_NAME,
            transform_input    = eligible_path,
            transform_output   = "s3://wellness-scores/run_date=" + run_date +
                                "/program=" + program.program_id + "/need/",
            instance_type      = "ml.m5.large",
            instance_count     = 1
        )
        job_handles.append(need_job)

        // Engagement prediction. Per-program model: the features predicting
        // engagement with DPP differ from features predicting engagement
        // with smoking cessation, so each program has its own engagement model.
        engagement_job = SageMaker.CreateTransformJob(
            transform_job_name = "eng-" + program.program_id + "-" + run_date,
            model_name         = ENGAGEMENT_MODEL_NAMES[program.program_id],
            transform_input    = eligible_path,
            transform_output   = "s3://wellness-scores/run_date=" + run_date +
                                "/program=" + program.program_id + "/engagement/",
            instance_type      = "ml.m5.large",
            instance_count     = 1
        )
        job_handles.append(engagement_job)

        // Uplift estimate. The uplift model is the most subtle of the three
        // and the hardest to train: it requires either a randomized historical
        // sample (members who were randomly assigned to "recommend" or "control"
        // in a prior cycle) or a propensity-adjusted observational sample.
        // For the X-learner pattern, the model predicts the conditional
        // average treatment effect (CATE) per member.
        uplift_job = SageMaker.CreateTransformJob(
            transform_job_name = "uplift-" + program.program_id + "-" + run_date,
            model_name         = UPLIFT_MODEL_NAMES[program.program_id],
            transform_input    = eligible_path,
            transform_output   = "s3://wellness-scores/run_date=" + run_date +
                                "/program=" + program.program_id + "/uplift/",
            instance_type      = "ml.m5.xlarge",  // causal forest is heavier
            instance_count     = 1
        )
        job_handles.append(uplift_job)

    // Wait once for all 3 * N jobs to finish. Programs do not block each other.
    wait_for_jobs(job_handles)

    // After all programs scored, concatenate into a single per-member,
    // per-program scoring table for the ranking step.
    consolidate_scores(programs, run_date)
        // produces s3://wellness-scores/run_date=<run_date>/all-scores.parquet
        // with columns: member_id, program_id, need_score, engagement_prob,
        //               uplift_estimate
```

**Step 3: Combine scores into a per-member ranked list.** The ranking step consumes the consolidated scoring table and combines the three scores into a per-(member, program) priority. The combination weights are policy: documented, reviewable, and version-controlled. Skip the explicit policy and the weights drift silently, with no record of why one cohort started getting more or fewer recommendations.

```
FUNCTION rank_per_member(scores, policy):
    // policy.weights might be:
    // { need: 0.3, engagement: 0.2, uplift: 0.5 }
    // The weights live in a versioned config file, not in code, so the
    // policy is auditable and can be changed without a deploy.

    // Normalize each score to [0, 1] within its program. Z-scores would
    // also be reasonable; pick one and document.
    scores_normalized = normalize_within_program(scores)

    // Compute combined priority per (member, program).
    FOR each row in scores_normalized:
        row.priority = (policy.weights.need        * row.need_score +
                        policy.weights.engagement  * row.engagement_prob +
                        policy.weights.uplift      * row.uplift_estimate)

        // Capture the per-component contribution for explainability and
        // for downstream auditing of why a particular row was prioritized.
        row.priority_components = {
            need_contrib:       policy.weights.need       * row.need_score,
            engagement_contrib: policy.weights.engagement * row.engagement_prob,
            uplift_contrib:     policy.weights.uplift     * row.uplift_estimate
        }

    // Group by member and rank programs within each member.
    per_member_rankings = group_by(scores_normalized, key = "member_id")
    FOR each member, programs_for_member in per_member_rankings:
        sorted_programs = sort programs_for_member by priority DESC
        FOR rank_pos, p in enumerate(sorted_programs):
            p.member_rank = rank_pos + 1

    // Persist ranked output.
    write_ranking_table(per_member_rankings, policy.policy_version, run_date)
    RETURN per_member_rankings
```

**Step 4: Allocate slots under capacity constraints with equity floors.** The allocator turns per-member rankings into population-level allocations. Greedy by uplift is the starter version. Equity floors prevent the allocator from concentrating opportunity on the easiest-to-help cohorts. Skip the floors and you ship a system that quietly under-targets the populations that most need wellness investment.

```
FUNCTION allocate_capacity(per_member_rankings, programs, policy):
    // Build a flat list of (member, program, priority) tuples, sorted by
    // priority descending. The allocator walks this list and assigns slots.
    candidates = []
    FOR each member, programs_for_member in per_member_rankings:
        FOR each p in programs_for_member:
            candidates.append({
                member_id:     member,
                program_id:    p.program_id,
                priority:      p.priority,
                priority_components: p.priority_components,
                member_rank:   p.member_rank,
                cohort_features: lookup_cohort_features(member)
                    // e.g., engagement-history quartile, language, geography,
                    //       SDOH cohort
            })
    candidates_sorted = sort candidates by priority DESC

    // Initialize per-program capacity counters and equity-floor counters.
    capacity_remaining = {}
    equity_remaining = {}
    FOR each program in programs:
        capacity_remaining[program.program_id] = program.capacity
        equity_remaining[program.program_id] = {}
        FOR floor_cohort, floor_count in policy.equity_floors[program.program_id]:
            equity_remaining[program.program_id][floor_cohort] = floor_count

    // Walk the candidate list. Each member gets at most one program assigned
    // per run (avoid recommending two programs to the same member in one
    // outreach cycle). Each program respects its capacity and its equity
    // floors.
    allocated = []
    members_already_allocated = set()
    FOR candidate in candidates_sorted:
        IF candidate.member_id in members_already_allocated:
            CONTINUE
        IF capacity_remaining[candidate.program_id] <= 0:
            CONTINUE

        // Equity-floor check: if this candidate's cohort still has
        // reserved slots in the floor, prefer them; if the cohort's floor
        // is filled, the candidate competes for general capacity.
        // The floor reserves capacity for cohorts that would otherwise
        // be under-allocated by uplift-only optimization.
        candidate_cohort_floors = applicable_floors(candidate.cohort_features,
                                                    policy.equity_floors[candidate.program_id])
        IF len(candidate_cohort_floors) > 0:
            // Use a floor slot if any apply.
            FOR floor_cohort in candidate_cohort_floors:
                IF equity_remaining[candidate.program_id][floor_cohort] > 0:
                    equity_remaining[candidate.program_id][floor_cohort] -= 1
                    BREAK

        capacity_remaining[candidate.program_id] -= 1
        members_already_allocated.add(candidate.member_id)
        allocated.append({
            member_id:           candidate.member_id,
            program_id:          candidate.program_id,
            priority:            candidate.priority,
            priority_components: candidate.priority_components,
            allocation_reason:   reason_string(candidate, candidate_cohort_floors),
            run_date:            run_date
        })

    // After greedy pass, run a second pass to fill any unfilled equity floors
    // by relaxing the uplift threshold for cohorts whose floor wasn't met.
    FOR program in programs:
        FOR floor_cohort, floor_remaining in equity_remaining[program.program_id]:
            IF floor_remaining > 0:
                top_up_from_cohort(allocated, program, floor_cohort, floor_remaining,
                                   per_member_rankings, members_already_allocated)

    // Persist the allocation as the recommendation log row(s) for this run.
    DynamoDB.BatchWriteItem("recommendation-log", allocated)

    emit_metric("allocations_made", value = len(allocated), dimensions = {
        run_date:       run_date,
        policy_version: policy.policy_version
    })
    RETURN allocated
```

**Step 5: Apply contact-frequency caps and consent verification.** Before outreach goes out, a final pass verifies that each allocated member is within their contact-frequency cap and that consent is current. Skip this and a member who got two wellness emails last week and a billing email yesterday gets a third wellness email today, which is the most common reason members opt out entirely.

```
FUNCTION enforce_outreach_caps(allocated, run_date, policy):
    outreach_list = []
    deferred = []
    FOR row in allocated:
        member_profile = DynamoDB.GetItem("patient-profile", row.member_id)

        // Contact-frequency cap. Pull recent outreach count from the profile
        // (maintained by the orchestrator across all outreach types: 4.1
        // reminders, 4.2 education recommendations, 4.4 wellness, 4.5
        // adherence). Cap is policy: typical defaults are 2 wellness touches
        // per month, 4 total touches per month.
        recent_wellness = member_profile.outreach_recent_wellness_count
        recent_total    = member_profile.outreach_recent_total_count

        IF recent_wellness >= policy.max_wellness_per_month:
            deferred.append({
                row:    row,
                reason: "wellness_cap_exceeded"
            })
            CONTINUE

        IF recent_total >= policy.max_total_per_month:
            deferred.append({
                row:    row,
                reason: "total_cap_exceeded"
            })
            CONTINUE

        // Consent verification. Wellness consent may be implicit
        // (an enrollment-time opt-in to "wellness communications") or
        // explicit (a per-program consent the member acted on). Check both.
        IF NOT member_profile.wellness_consent.active:
            deferred.append({
                row:    row,
                reason: "no_active_wellness_consent"
            })
            CONTINUE

        IF row.program_id in member_profile.opt_outs.programs:
            deferred.append({
                row:    row,
                reason: "member_opted_out_of_program"
            })
            CONTINUE

        outreach_list.append(row)

    // Persist deferred reasons for transparency. Members who get repeatedly
    // deferred for cap reasons are signal: either the cap is too tight or
    // the recommender is over-targeting them.
    persist_deferred(deferred, run_date)
    RETURN outreach_list
```

**Step 6: Tailor outreach messages with an LLM and dispatch through the channel optimizer.** The outreach list goes to a per-member message-tailoring step (Bedrock), then to Recipe 4.1's channel optimizer, which decides whether to send via email, SMS, portal nudge, or care-team alert. Skip the LLM tailoring and you send the same template to every member, which is fine but leaves the easiest engagement gain on the table.

```
FUNCTION tailor_and_dispatch(outreach_list, programs):
    FOR row in outreach_list:
        program = lookup_program(row.program_id, programs)
        member  = DynamoDB.GetItem("patient-profile", row.member_id)

        // Build the structured prompt input. Note: pass cohort and clinical
        // attributes the model needs to tailor, but do not pass raw
        // identifiers (member_id, name, phone) into the LLM. The LLM gets
        // de-identified context; identifiers are reattached after.
        prompt_context = {
            program_name:        program.display_name,
            program_summary:     program.public_summary,
            program_time_commit: program.time_commitment,
            relevant_clinical:   summarize_clinical_for_outreach(member, program),
                // e.g., "Member's recent A1c is in the prediabetes range"
            preferred_language:  member.preferred_language,
            tone:                policy.outreach_tone   // e.g., "supportive, non-alarming"
        }

        // Generate the tailored message. Bedrock model selection is policy:
        // Haiku-class for cost, Sonnet-class for quality, Nova for both.
        message_response = Bedrock.InvokeModel(
            model_id = OUTREACH_TAILORING_MODEL_ID,
            body     = build_tailoring_prompt(prompt_context, OUTREACH_SCHEMA)
        )
        tailored = parse_json(message_response.completion)
            // { subject_line, opening_line, program_pitch, closing_call_to_action }

        // Validate the LLM output: check the schema, check that required
        // disclosures are present, check that the message doesn't contain
        // any clinical claims that weren't in the prompt (the most common
        // hallucination failure mode in this kind of generation).
        validate_outreach_message(tailored, program)

        // Hand to Recipe 4.1's channel optimizer. The optimizer decides
        // which channel and what time. The orchestrator passes the
        // structured message; the channel optimizer renders it for the
        // specific channel format (subject + body for email, short for SMS).
        ChannelOptimizer.QueueOutreach(
            member_id    = row.member_id,
            content_type = "wellness_program_recommendation",
            payload      = {
                program_id:     row.program_id,
                tailored:       tailored,
                fallback_template: program.default_template
                    // Used if the channel optimizer downgrades to a channel
                    // that doesn't fit the tailored format (e.g., SMS
                    // truncation), or if a downstream system rejects the
                    // tailored copy.
            },
            urgency      = derive_urgency(row.priority, program.cohort_start_date),
            tracking_id  = "wellness-" + row.run_date + "-" + row.member_id + "-" + row.program_id
        )

        // Update the contact-frequency counter optimistically. The actual
        // send may fail; reconcile in the engagement-attribution step.
        DynamoDB.UpdateItem(
            "patient-profile",
            row.member_id,
            "ADD outreach_recent_wellness_count :one, outreach_recent_total_count :one",
            values = { ":one": 1 }
        )

        // Optionally generate a parallel PCP talking-point briefing.
        IF program.pcp_alert_enabled:
            pcp_briefing = generate_pcp_briefing(prompt_context, member, program)
            CareTeamInbox.PostNote(
                patient_id = row.member_id,
                briefing   = pcp_briefing,
                source     = "wellness-recommender",
                tracking_id = "wellness-pcp-" + row.run_date + "-" + row.member_id
            )

        // Emit a 'program_recommended' engagement event so downstream
        // attribution can match outcomes back to this recommendation.
        Kinesis.PutRecord(stream = "engagement-stream", record = {
            event_type:        "program_recommended",
            tracking_id:       "wellness-" + row.run_date + "-" + row.member_id + "-" + row.program_id,
            member_id:         row.member_id,
            program_id:        row.program_id,
            run_date:          row.run_date,
            priority_components: row.priority_components,
            allocation_reason: row.allocation_reason,
            timestamp:         current UTC timestamp
        })
```

<!-- TODO (TechWriter): The contact-frequency counter increment in Step 6 is optimistic, but Step 7 (`process_engagement_event` below) does not implement the reconciliation path the comment promises. Add a `program_outreach_failed` / `program_outreach_bounced` / `program_outreach_undeliverable` clause that decrements `outreach_recent_wellness_count` and `outreach_recent_total_count` by 1, plus a stale-pending sweep Lambda on a 24-hour delay that scans recommendation-log rows whose tracking_id has no engagement-stream activity at all and either decrements the counter or escalates to operations. Without these two halves of reconciliation, members whose outreach silently fails to deliver still consume cap slots, accumulate phantom counter increments that eventually push them past MAX_WELLNESS_PER_MONTH, and are silenced from future outreach for outreach they never received. The asymmetry is invisible in standard cohort dashboards (the deferral reason `wellness_cap_exceeded` looks legitimate) and compounds across cohorts: members with reliable channels get normal contact, members with flaky channels get systematically silenced. The equity floor protects the first recommendation but not the second, undoing the floor's intent over time. See expert review Finding 9 for the full reconciliation pseudocode. -->

**Step 7: Capture engagement events and update short-, medium-, and long-horizon training data.** Members open the email, ignore it, click through, enroll, attend, drop out, complete. Each event flows into the engagement stream, gets joined to the recommendation log, and feeds back into the appropriate model on the appropriate cadence. A PCP override (the doctor declined the recommendation) is also a signal and gets the same treatment. Skip this and the models stop learning, the dashboards stop reflecting reality, and the program-level ROI evaluation has nothing to evaluate against.

```
FUNCTION process_engagement_event(event):
    // Look up the originating recommendation by tracking_id.
    rec = DynamoDB.GetItem("recommendation-log", key_from_tracking_id(event.tracking_id))
    IF rec is null:
        LOG("engagement event for unknown tracking_id: " + event.tracking_id)
        RETURN

    // Validate member_id matches; if not, this event was misrouted and
    // should be dropped to prevent data poisoning.
    IF event.member_id != rec.member_id:
        LOG("event member_id mismatch with recommendation; dropping")
        RETURN

    // Persist to the engagement table.
    DynamoDB.PutItem("engagement-events", {
        event_id:      new UUID,
        tracking_id:   event.tracking_id,
        member_id:     event.member_id,
        program_id:    event.program_id,
        event_type:    event.event_type,
        timestamp:     event.timestamp,
        run_date:      rec.run_date,
        priority:      rec.priority,
        priority_components: rec.priority_components,
        allocation_reason:   rec.allocation_reason,
        cohort_features: lookup_cohort_features(event.member_id)
    })

    // Short-horizon: open, click, enroll. Update the engagement-prediction
    // training data and the per-member outreach-history features the next
    // run will consume.
    IF event.event_type in ["program_outreach_opened", "program_outreach_clicked",
                             "program_enrolled"]:
        update_engagement_training_label(rec, event)

    // Medium-horizon: program_completed, program_dropped_out. Update the
    // uplift training data, with a treated-cohort label or a control-cohort
    // label depending on whether this member was in the recommendation arm.
    IF event.event_type in ["program_completed", "program_dropped_out"]:
        update_uplift_training_label(rec, event)

    // PCP override: the primary care team declined the recommendation.
    // This is a strong negative label and is also signal that the
    // recommender's clinical-need scoring may be miscalibrated for this
    // patient's situation.
    IF event.event_type == "pcp_override":
        DynamoDB.PutItem("pcp-overrides", {
            override_id:    new UUID,
            tracking_id:    event.tracking_id,
            member_id:      event.member_id,
            program_id:     event.program_id,
            pcp_reason:     event.reason,
            timestamp:      event.timestamp
        })
        flag_for_clinical_review(event)
        emit_metric("pcp_override", value = 1, dimensions = {
            program_id: event.program_id,
            reason:     event.reason
        })

    // Cohort-sliced metrics for the equity dashboard. Track enrollment,
    // completion, and override rates by cohort so subgroup drift is visible.
    emit_metric("wellness_engagement",
                value = 1,
                dimensions = {
                    event_type:              event.event_type,
                    program_id:              event.program_id,
                    engagement_history_quartile: rec.cohort_features.engagement_history_quartile,
                    language:                rec.cohort_features.language,
                    sdoh_cohort:             rec.cohort_features.sdoh_cohort
                })
```

**Step 8: Run long-horizon outcome evaluation periodically.** Independent of the weekly batch run, a quarterly or semi-annual outcome-evaluation job compares the clinical and cost trajectories of recommended-and-engaged members against matched controls. The output drives the medical director's program-renewal decisions and surfaces evidence (or counter-evidence) for whether each program is actually moving the needle. Skip this and you can't honestly answer the question of whether the wellness investment is paying off.

```
FUNCTION run_outcome_evaluation(programs, evaluation_window):
    // For each program, build a treated cohort (members who were recommended
    // and engaged within the window) and a control cohort (matched members
    // who were not recommended, drawn either from a randomized hold-out or
    // from propensity-matched non-recommended members).
    FOR each program in programs:
        treated = pull_treated_cohort(program, evaluation_window)
        control = pull_matched_control(program, evaluation_window)
            // - if the program has a randomized hold-out arm, prefer that
            // - otherwise propensity-match on pre-recommendation features

        // For each cohort, compute the program's primary outcomes:
        // typically a clinical metric (HbA1c trajectory, BMI trajectory,
        // smoking quit-status at 6 and 12 months) and a cost metric
        // (downstream utilization, total cost of care).
        treated_outcomes = compute_outcomes(treated, program.outcome_definitions, evaluation_window)
        control_outcomes = compute_outcomes(control, program.outcome_definitions, evaluation_window)

        // Estimate the average treatment effect with confidence intervals.
        // For a randomized arm, this is a straightforward difference-in-means.
        // For propensity-matched, doubly-robust estimation gives tighter
        // intervals.
        ate = estimate_ate(treated_outcomes, control_outcomes, method = program.eval_method)

        // Stratify by cohort to surface heterogeneous effects. The aggregate
        // ATE may be positive while one cohort experiences null or negative
        // effect; equity-relevant signal that must surface.
        ate_by_cohort = stratified_ate(treated_outcomes, control_outcomes, cohort_axes = ["sdoh_cohort", "language", "age_band"])

        // Persist the evaluation. The medical director, equity lead, and
        // vendor management consume this when deciding whether to renew
        // the program for the next cycle.
        DynamoDB.PutItem("program-outcome-evaluations", {
            evaluation_id:      new UUID,
            program_id:         program.program_id,
            evaluation_window:  evaluation_window,
            ate:                ate,
            ate_by_cohort:      ate_by_cohort,
            sample_size_treated: len(treated),
            sample_size_control: len(control),
            method:             program.eval_method,
            run_date:           current UTC date
        })

        // Emit metrics to QuickSight and CloudWatch dashboards.
        emit_outcome_metrics(program, ate, ate_by_cohort)
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter04.04-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample recommendation log entry (per-(member, program) row):**

```json
{
  "tracking_id": "wellness-2026-05-04-mem-000482-prog-dpp",
  "run_date": "2026-05-04",
  "member_id": "mem-000482",
  "program_id": "prog-dpp",
  "priority": 0.78,
  "priority_components": {
    "need_contrib": 0.27,
    "engagement_contrib": 0.13,
    "uplift_contrib": 0.38
  },
  "allocation_reason": "top_uplift_general_capacity",
  "policy_version": "wellness-policy-v0.4",
  "model_versions": {
    "need_model": "need-v3",
    "engagement_model_dpp": "eng-dpp-v5",
    "uplift_model_dpp": "uplift-dpp-v2"
  },
  "cohort_features": {
    "engagement_history_quartile": "q2",
    "language": "es",
    "sdoh_cohort": "low_food_security",
    "age_band": "55-64"
  }
}
```

**Sample tailored outreach payload (passed to channel optimizer):**

```json
{
  "tracking_id": "wellness-2026-05-04-mem-000482-prog-dpp",
  "tailored": {
    "subject_line": "Una opción de prevención que puede ayudarle",
    "opening_line": "Hola Maria, queríamos compartirle un programa que podría apoyarle con sus resultados recientes.",
    "program_pitch": "El Programa de Prevención de Diabetes (DPP) es un programa de 12 meses con apoyo de un coach. Los participantes a menudo bajan algo de peso y mejoran sus números de A1c.",
    "closing_call_to_action": "¿Le gustaría saber más? Responda 'SÍ' a este mensaje o llame al número de su plan."
  },
  "fallback_template": "dpp-default-es",
  "urgency": "standard",
  "preferred_language": "es"
}
```

**Sample quarterly outcome evaluation:**

```json
{
  "evaluation_id": "eval-2026Q1-prog-dpp",
  "program_id": "prog-dpp",
  "evaluation_window": "2025-04-01_to_2026-03-31",
  "method": "propensity_matched_difference_in_differences",
  "ate": {
    "primary_outcome": "hba1c_change_at_12_months",
    "estimate": -0.34,
    "ci_95_low": -0.48,
    "ci_95_high": -0.20,
    "p_value": 0.002,
    "interpretation": "Treated members reduced HbA1c by ~0.34 more than matched controls over 12 months."
  },
  "ate_by_cohort": [
    { "cohort": "language=en", "estimate": -0.36, "ci_95_low": -0.52, "ci_95_high": -0.20 },
    { "cohort": "language=es", "estimate": -0.28, "ci_95_low": -0.51, "ci_95_high": -0.05 },
    { "cohort": "sdoh_cohort=low_food_security", "estimate": -0.18, "ci_95_low": -0.41, "ci_95_high": 0.05 }
  ],
  "sample_size_treated": 312,
  "sample_size_control": 312
}
```

**Performance benchmarks (illustrative, your mileage varies):**

| Metric | Eligibility-only baseline | Recipe pipeline |
|--------|---------------------------|-----------------|
| Outreach-to-enrollment rate | 0.5-1.5% | 4-8% |
| Enrollment-to-completion rate | 30-45% | 45-65% |
| Members allocated per cohort cycle | (manual list, often over-targeting) | (programmatic, capacity-aware) |
| Population uplift (treated vs matched control) | not measured | quantified per evaluation cycle |
| Equity floor utilization | n/a | 80-100% (configurable target) |
| End-to-end batch run time (400K members, 6 programs) | n/a | 30-90 minutes |

<!-- TODO: the benchmarks above are illustrative and have not been measured for this specific pipeline. Replace with measured results from your deployment, or with citations to published wellness-program targeting deployments when available. Be wary of vendor-published numbers that don't disclose their evaluation methodology. -->

**Where it struggles:**

- **Programs with new or rapidly-changing slates.** The uplift model needs historical (treated, control) data to estimate effects. A brand-new program has none. For new programs, plan a randomized pilot for the first 1-2 cohorts (random recommendation among matched eligibles) to bootstrap the uplift training data; until that's available, fall back to need-and-engagement scoring with explicit "we are calibrating" disclosures in the recommendation log.
- **Members whose clinical picture changes faster than the feature pipeline.** The feature store has a refresh lag (claims arrive on a 24-48 hour delay). A member whose A1c just jumped because of an acute illness may not show up as DPP-eligible until the next refresh. The recommender will be a step behind clinically-acute changes; the care-team workflow has to be the catch.
- **Members with multiple compelling program matches.** The recommender currently allocates each member to at most one program per run. A member who is genuinely a strong match for two programs (a smoker with prediabetes) gets program A this run and (if still eligible) program B in a subsequent run. Some plans extend the per-member rule to allow concurrent multi-program allocation, but the orchestration cost (contact-frequency caps multiply, cross-program engagement metrics get tangled) is real and worth scoping deliberately.
- **Cohorts where engagement-history features are sparse.** Newly-enrolled members, members switching plans, members with low historical engagement: the engagement-prediction model is a guess for these. The equity floor and the explicit cohort-level fallbacks help, but the system is more uncertain about these members than about long-tenured members. Treat the uncertainty as visible state rather than letting the recommender pretend it knows.
- **PCP override mismatch.** Sometimes the recommender flags a member that the PCP, who knows the patient, knows is a bad fit (the patient just lost a parent and is in no shape for behavior-change work; the patient has an acute issue that takes precedence). PCP overrides are signal, but they also create a feedback loop where the recommender learns to under-recommend members whose PCPs are skeptical. Track override rates by PCP to distinguish legitimate clinical override from PCP skepticism toward wellness programs in general.
- **Data lag in long-horizon outcomes.** The outcome evaluation runs on quarterly or semi-annual cadences and reflects programs as they were configured 12-18 months ago. By the time you have evidence that a program isn't working, it's been running for a year. Plan parallel intermediate-outcome dashboards (3-month, 6-month leading indicators) so you can flag concerns earlier, while accepting that final evidence is necessarily delayed.

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment needs to close several gaps that are intentionally out of scope for a recipe.

**Uplift training data.** The recipe assumes you have historical (recommended, response) data with enough variation in treatment assignment to train an uplift model. Most plans don't, on day one. The honest path: ship the pipeline with engagement-and-need scoring only, run a small randomized pilot for each program for one or two cohort cycles to generate training data, then turn on uplift scoring as the pilot data accrues. Document explicitly that the early runs are calibrating, not optimized.

**Propensity-score modeling for observational uplift.** When a randomized pilot isn't feasible, the recipe leans on propensity-score adjustment. Production-grade propensity modeling is its own engineering investment: the propensity model has to be trained, calibrated, and audited; the sensitivity of the uplift estimates to propensity-model misspecification has to be characterized. Plan for this work and engage with a causal-inference specialist if your team doesn't have one.

**Capacity-floor calibration.** The equity floor is a policy lever. Setting the per-cohort floor percentages is a cross-functional decision (medical director, equity lead, vendor management, member services), not a data-science decision. A floor that's too tight starves the optimization of room to optimize; a floor that's too loose lets concentration drift back in. Plan to recalibrate quarterly with stratified outcome data.

<!-- TODO (TechWriter): Specify the SageMaker training-job trigger mechanism (EventBridge schedule, Step Functions on a cron, or CloudWatch metric threshold) and the model-promotion path from training to inference (Batch Transform model package update via SageMaker Model Registry, or in-place model artifact swap with a canary run). The architecture diagram currently shows "Periodic retrain" without an explicit trigger node, and there's no path shown for promoting a newly-trained model into the next batch run. -->

**Cohort-cycle calendar integration.** The recipe assumes a single weekly batch run. In practice, different programs have different cohort-cycle cadences (DPP starts monthly, smoking cessation rolls weekly, stress reduction quarterly). The orchestration layer should align each program's allocation pass with its cohort cycle so members are recommended at the right moment relative to the next intake. This is calendar logic, not ML, but the calendar bugs are some of the most painful production failures.

<!-- TODO (TechWriter): Replace the single weekly EventBridge schedule with per-program EventBridge Scheduler rules driven by each program's cohort cadence stored in the program-catalog metadata. One rule per program (or per cadence-group) triggers that program's slice of the pipeline on its own cron. The cohort-start window for each program (e.g., DPP allocates members 7 to 14 days before cohort start) lives as a program-catalog field and parameterizes the scheduler. Reference Recipe 14.x for the cross-program scheduling-as-optimization version when slates have many programs with overlapping cohort calendars. -->

**Multi-program orchestration policy.** The recipe allocates one program per member per run. Plans with rich slates often want to recommend a sequence of programs over time (smoking cessation first, then DPP six months later when the member has stabilized). The orchestration to plan a member's wellness journey across multiple programs is an extension worth scoping deliberately. It looks like Recipe 4.10 (Dynamic Treatment Regime Recommendation), with all the regulatory and complexity considerations that implies.

<!-- TODO (TechWriter): Add a paragraph on the greedy allocator's path-dependence. The per-member program choice depends on the global priority ordering: two members eligible for the same two programs may be assigned different programs depending on which (member, program) pair appears first in the sort. Re-running the allocator with slightly different priorities (a feature refresh, a model retrain) may flip a member's assigned program across runs. This is the greedy allocator's intrinsic instability and is one of the reasons graduating to integer programming (Recipe 14.x) is worth the investment when the slate has more than 3-4 programs with overlapping eligibility. For plans where allocation stability across runs is operationally important, a per-member best-program pre-pass can pre-commit each member to their top-priority program before the global greedy walk; the pre-pass loses some optimization tightness in exchange for stability, and the choice is policy. -->

**Outreach-message governance.** The LLM-tailored outreach passes through a validation step in the pseudocode. Production: the validation needs a list of approved program claims, an explicit prohibited-claims list (e.g., no curative-language overstatement, no implicit guarantees of outcome), and a sampling-and-review process where a human reads a sample of generated messages each week. Hallucinated clinical claims in patient-facing outreach are an FDA-attention failure mode; treat the validator as production-critical, not a nice-to-have.

<!-- TODO (TechWriter): Specify the validator's pseudocode shape (four layers: schema and shape, required disclosures, prohibited-claims regex/blocklist, hallucinated-clinical-claims check against an approved-claims list per program). Specify where the approved-claims and prohibited-claims lists live (versioned config artifact owned by clinical/compliance, S3 with object versioning is sufficient, loaded at validator-init from the current version). Specify the failure-handling behavior (schema/length failures fall back to `program.default_template`; clinical or prohibited-claims failures defer the outreach with reason `validator_failed:<reason>` and flag for human review). A change to the lists should trigger a re-validation pass over the most recent N days of outreach to catch any messages that would now fail; manually-approved exceptions are logged for audit. See expert review Finding 3 for the validator pseudocode. -->

**PCP-override workflow integration.** The recipe references a PCP override path. Real implementations need explicit EHR integration: the recommendation appears in the PCP inbox as a structured task, the PCP acts on it (endorse, decline-with-reason, defer), the action flows back into the engagement stream and the model retraining. Each EHR has its own integration surface (Epic, Cerner / Oracle Health, Athena, Veradigm); the orchestration layer needs purpose-built adapters per EHR, and the EHR teams need to be partners in the rollout.

<!-- TODO (TechWriter): For higher-stakes programs, replace the parallel PCP-notify pattern with a pre-send PCP-review hold. Add a `pcp_review_policy` field to the program catalog with values: `none` (no PCP notification), `notify_parallel` (current behavior, appropriate for moderate-stakes programs), `review_required_24h` (outreach is held for 24 hours; PCP can decline before send; default to send if no response), `review_required_72h_then_hold` (outreach held for 72 hours; if PCP doesn't respond, escalate to care team rather than auto-sending). Behavioral health for fragile mental-health stability, smoking cessation in pregnancy, and weight management for members with eating-disorder history are the canonical "review required" cases. Reference Recipe 4.10 for the formal-state-machine version. See expert review Finding 4 for the orchestration pseudocode. -->

**Wellness consent regime.** Wellness consent is not a single boolean. ADA voluntary-participation, GINA family-history authorization where applicable (DPP eligibility uses family history of diabetes), state-specific consent regimes (California CCPA/CPRA, Washington My Health My Data, others), program-specific consent (a member who consented to weight management has not consented to behavioral health outreach), and channel-specific consent (email vs SMS vs telephonic) are each their own field. Collapsing them into one flag produces an EEOC or state-AG enforcement risk that may not surface until two years after launch. Engage employee benefits counsel and your privacy officer on the consent model before the first run.

<!-- TODO (TechWriter): Replace the single `wellness_consent.active` check in `enforce_outreach_caps` (Step 5) with a multi-dimensional consent verification: ADA voluntary-participation, GINA authorization (only checked when the program's eligibility uses family-history features), program-specific consent map keyed on program_id, channel-specific consent map keyed on the channel the orchestrator will use. Each consent dimension that fails produces its own deferral reason (e.g., `ada_voluntary_participation_not_confirmed`, `gina_authorization_required`, `program_specific_consent_missing`, `channel_consent_missing`). See expert review Finding 1 for the verification pseudocode. -->

**Vendor reporting alignment.** Wellness program vendors typically supply enrollment, attendance, and completion data on their own cadence and formats. The engagement events in this recipe assume a normalized stream; in reality, the data engineering to ingest each vendor's reporting (CSVs in SFTP, vendor portal exports, sometimes flat files emailed to a shared inbox) is real work. Build a vendor-feed ingestion layer per vendor with explicit schema validation and reconciliation against the recommendation log.

<!-- TODO (TechWriter): Replace the string-concatenation tracking_id (`"wellness-" + run_date + "-" + member_id + "-" + program_id`) with an opaque, non-reversible identifier (a UUID, or HMAC-SHA256 over the composite with a per-environment secret). The opaque tracking_id flows on outbound channels (email open-tracking pixels, SMS click-through links, vendor outreach platform handoffs) and inbound engagement events; member identity is reattached only inside systems with read access to the recommendation log. Plain-text member_ids embedded in URLs and SMS payloads are PHI leakage even when the surrounding context looks innocuous (tracking pixel domains, vendor analytics paths, CloudWatch logs at INFO level). Update the Expected Results sample tracking_id accordingly. See expert review Finding 2. -->

**Idempotency and retry semantics.** Step Functions handles per-stage retry with backoff cleanly, but the recipe doesn't specify what happens on partial completion. Each stage of the pipeline must be idempotent at the (run_date, program_id, member_id) granularity. Step 1 (eligibility) writes to a per-run S3 prefix that is fully recreated on retry. Step 2 (scoring) job names embed the run_date so a retry is a no-op if the job already exists in `Completed` state. Step 3 (ranking) writes to a per-run S3 prefix. Steps 4 and 5 (allocation, cap enforcement) write to DynamoDB with conditional-put on a composite key (run_date + member_id + program_id); a retry that re-attempts an already-written row is a no-op. Step 6 (orchestration) checks the recommendation-log for an existing `program_recommended` engagement event before queueing outreach; idempotency on the orchestration boundary prevents double-sends. The Step Functions Catch should distinguish Retryable (transient infra failure) from Terminal (logic error) and route Terminal failures to the DLQ rather than retrying.

**Long-horizon evaluation methodology.** The outcome evaluation in the recipe references propensity-matched difference-in-differences. Production: the methodology needs explicit pre-registration (define the analysis before you run it, to avoid p-hacking), explicit sensitivity analyses (how robust are the conclusions to alternative matching specifications), and a statistical reviewer who is not the team running the recommender. Without those guardrails, the evaluation becomes a marketing artifact rather than an honest assessment.

**Privacy in the recommendation log and engagement events.** The recommendation-log table joins member_id to program_id, scores, and cohort attributes. That join is sensitive: a row indicating "member is being targeted for a behavioral health program" or "member is in the SDOH 'low food security' cohort" is inferentially identifying and revealing. Apply the same controls as the patient profile: customer-managed KMS, CloudTrail data events, narrow IAM read scopes, defined retention. Define explicit retention periods (90-180 days for individually-attributed recommendation logs; longer retention only after de-identification). Add a CloudWatch alarm on the deletion job and a documented re-attestation cadence.

<!-- TODO (TechWriter): Add a paragraph clarifying the SDOH-cohort PHI boundary specifically. Cohort labels like "low_food_security" are derived from screening data and reveal sensitive information about a member's life circumstances. Treat these labels as PHI even when stripped of direct identifiers (a small SDOH cohort in a specific geography is reidentifiable). The cohort_features attribute on engagement events should be limited to the minimum cohort axes needed for fairness monitoring, and access should be narrower than for general engagement data. Apply the minimum-necessary principle to cohort axes themselves: only carry cohort attributes through to the engagement event that the equity dashboard actually consumes. A new cohort axis added because "it might be useful someday" is a privacy expansion that should be reviewed. -->

**Cohort fairness review process.** The architecture emits cohort-sliced metrics, but a dashboard nobody reads is useless. Establish a quarterly review with a cross-functional committee (data science, equity lead, medical director, vendor management, member services). Watch for: cohorts with consistently lower enrollment-to-completion conversion (signaling poor fit or systematic exclusion), outcome differences by cohort that are not explained by clinical factors, persistent under-utilization of equity floors. Each finding should produce an action item with an owner.

<!-- TODO (TechWriter): Deduplicate cohort-feature lookups in `allocate_capacity` (Step 4). Today the candidate-build loop calls `lookup_cohort_features(member)` once per (member, program) pair; a member ranked across N programs produces N redundant DynamoDB reads, and a reader that updates between reads can produce inconsistent cohort assignments across the same member's recommendations. Build a per-member cohort cache before the candidate-build loop. See expert review Finding 13 and code review Finding 5. -->

<!-- TODO (TechWriter): Add a paragraph on DLQ coverage on all Lambda paths in the architecture, none of which the diagram currently shows:
       (a) Step Functions -> Lambda allocator: Catch on each Lambda task pointing to an SQS failure queue keyed on (run_date, stage, failure_reason);
       (b) Kinesis -> attribution Lambda: configure an OnFailure destination on the event source mapping pointing to SQS or SNS, with a CloudWatch alarm on DLQ depth;
       (c) Batch Transform job failures: SageMaker doesn't surface failures via DLQ; wire the Step Functions Catch to handle TransformJob failed states explicitly.
     A silently-dropped engagement event during attribution leaves the model training data incomplete and the dashboards wrong, with no observable symptom until a quarterly evaluation regresses. -->

**Cost-per-recommended-and-engaged tracking.** The cost numbers in the prerequisites table cover infrastructure. Production reporting needs to ladder up to per-program total cost (infrastructure plus vendor invoices plus internal staff time) divided by engaged-and-completed members. That number is what gets compared to expected long-horizon savings. The data engineering to track this end-to-end is its own project.

---

## The Honest Take

Wellness program recommendation is one of those problems where the data science is the easiest part. The hard parts are everything around it: the cross-functional governance of the allocation policy, the long-horizon outcome evaluation that's the only honest measure of whether the programs are working, the equity instrumentation that prevents the optimization from quietly redistributing opportunity to the easiest-to-help cohorts. A team that gets gravitationally pulled toward "let's tune the uplift model more" while the outcome evaluation is still ad hoc is solving the wrong problem.

The thing that surprises people coming from retail recommendation backgrounds is how much of this depends on human-in-the-loop work that doesn't show up in any architecture diagram. The medical director who reads a sample of tailored outreach messages each week and flags the ones that overstate program benefits. The equity committee that watches the cohort dashboards and asks why the SDOH-low cohort's completion rate dropped this quarter. The vendor manager who sees the outcome evaluation and starts a contract conversation with the DPP vendor about price-per-completion. None of those people are users of the system in the SaaS sense; all of them are part of the system in the operational sense. Build for them.

The thing I'd do differently the second time: invest in randomized hold-outs from day one. The temptation, on day one, is to recommend to everyone who's eligible because "we have a program and we want it utilized." That's the moment you can least afford to forgo a randomized control. Six months later, when the medical director asks "is the program working," you have a beautiful dashboard of completion rates and no causal evidence. With a randomized hold-out (10 to 20 percent of eligibles randomly assigned to no-recommendation), you'll have an answer in 12 to 18 months. Without it, you may never have one. The political conversation about "but those members are eligible, they should get the program" is real; the conversation about "we ran the program for three years and we still don't know if it works" is also real, and worse.

The trap worth flagging: confusing engagement metrics with outcome metrics. A wellness recommender that drives more enrollments is not necessarily a better recommender. A wellness recommender that produces members who complete programs is not necessarily a better recommender. The actual metric that matters is whether the members the recommender targeted, who engaged, are healthier (or the costs of caring for them are lower) than they would have been without the targeting. Track engagement, by all means, because it's the only fast feedback loop you have. Just don't optimize purely against it. The recommender will happily over-target sure things and call that success.

Another trap: treating uplift modeling as a magic ingredient. Uplift models are honest about a hard question (what's the causal effect) but they have honest weaknesses (they're noisy, they need substantial data, they're sensitive to confounding). A model that says "this member has an uplift of 0.04" with a 95% confidence interval of [-0.01, 0.09] is telling you something useful: the effect is probably small and you can't be sure it's not zero. Acting on point estimates without considering the intervals is how teams ship recommenders that overconfidently rank members on noise. Always pass the uncertainty through to the allocator. Always show the uncertainty in the dashboards.

One more piece of personal opinion. The wellness-program domain has a long history of vendors with thin evidence, ROI claims that don't survive independent evaluation, and a general sense that "we sent emails and people enrolled" counts as program success. The recipe in this chapter is built for plans that want to do better than that. The architecture supports honest evaluation; whether the team commits to running the honest evaluation is a cultural choice, not a technical one. If your organization's wellness program is fundamentally a check-the-box exercise rather than an investment in member outcomes, this recipe will produce more rigorous reports of the same fundamental disappointment, and that may be its most useful contribution. At minimum, you'll know.

Last point, because it's specific to this use case: members are people, and wellness outreach can feel intrusive even when it's well-targeted. A member who gets recommended to DPP, smoking cessation, and stress reduction in the same month may correctly conclude that the plan thinks they're a mess, even if each recommendation was clinically defensible in isolation. The contact-frequency cap and the per-member single-program-per-run rule exist for this reason. Be more conservative than you think you need to be. The cost of an over-targeted member opting out of all wellness communications is high; you can't easily get them back. Default to fewer touches with higher tailoring quality. The members who want more will tell you.

---

## Variations and Extensions

**Sequential program recommendation.** Instead of one program per member per run, plan a member's wellness journey as a sequence: the right first program, the right next program once the first completes, the right pause window between programs. This is a small step toward Recipe 4.10 (Dynamic Treatment Regime Recommendation). Implementation is a state-machine layer above the recommender that tracks each member's program history and applies sequencing rules (e.g., "stress reduction is more effective if completed before DPP for members with moderate-to-high anxiety"). Document the sequencing logic as policy, not as model output.

**Risk-based program intensity.** Many wellness programs come in tiers (light-touch app-based vs. coach-led vs. intensive group). The recommender can additionally select intensity tier, not just program: a high-clinical-need member with prediabetes and low engagement-history gets recommended to coach-led DPP rather than app-based DPP, even though both are options. Adds a categorical decision to the allocator. Worth it when the cost differential between tiers is meaningful and the data supports differentiated outcomes.

**Closed-loop care-team integration.** Beyond the PCP-alert pattern in the recipe, integrate the recommendation into the care manager's outreach workflow: the care manager seeing a high-risk member can pull up the system's wellness recommendations as part of their care-plan conversation. The care manager's response (member endorsed, member declined, member needs different program) is structured back into the engagement stream. Turns the recommender from a member-facing channel into a care-team productivity tool with the member-facing channel as a fallback.

**Member-stated preferences as hard constraints.** A member who explicitly says "I'm not interested in weight management programs, please don't suggest them again" should never see another weight management recommendation. The opt-out flow lives in member-facing portals; the orchestrator respects it as a hard filter. Track opt-outs as their own metric (high opt-out rates per program signal poor program-market fit, not just member preference).

**Cross-recipe orchestration with Recipe 4.5 (Adherence Targeting).** A member with prediabetes who is non-adherent to a diabetes prevention medication is a candidate for both DPP (lifestyle change) and an adherence intervention (medication-focused). The cross-recipe orchestrator avoids duplication: typically the adherence intervention precedes or runs alongside the lifestyle program, not in competition. Define explicit interaction rules between recommendations from different chapters and recipes.

**LLM-generated longitudinal motivational messaging.** Beyond the initial outreach message, the LLM can generate context-aware progress messages during the program ("you've attended 4 of 6 sessions; here's a thought from your coach about momentum"). This crosses into Chapter 11 conversational AI territory, but the structured input from the recommender (program state, attendance history, last clinical update) is a great fit for short, personalized motivational text. Treat as enhancement, not replacement, for human coach engagement.

**Cohort-level program-mix optimization.** Beyond per-member allocation, the population-level question of "what's the right mix of programs to offer next year" is itself an optimization problem. Given member-population characteristics, available program options, and projected outcome estimates, which slate of programs maximizes expected population health improvement subject to the budget? This is a Recipe 14.x problem, but the inputs come from this recipe's outcome evaluations.

---

## Related Recipes

- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Provides the channel optimizer that this recipe's orchestrator hands off to. The contact-frequency cap is shared infrastructure between the two recipes.
- **Recipe 4.2 (Patient Education Content Matching):** The recommender pattern is similar; the engagement-event pipeline is the same. Where 4.2 recommends a piece of content, 4.4 recommends a multi-week intervention with capacity constraints.
- **Recipe 4.3 (Provider Directory Search Optimization):** Shares the fairness-instrumentation pattern (cohort-sliced metrics, equity floors). The patient-profile and engagement-stream infrastructure overlaps directly.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Reuses the uplift-and-allocation pattern from this recipe. The adherence interventions catalog is structurally similar to the wellness program catalog.
- **Recipe 4.6 (Care Gap Prioritization):** Uses the per-member-need scoring pattern from this recipe to prioritize among multiple care gaps for a single patient. Shares the clinical-need model infrastructure.
- **Recipe 4.7 (Care Management Program Enrollment):** Extends this recipe's allocator with more sophisticated optimization (LP-based, multiple resource constraints) and higher clinical stakes. The uplift modeling investment in 4.4 transfers directly.
- **Recipe 4.10 (Dynamic Treatment Regime Recommendation):** The sequential-recommendation extension above is a small step toward this recipe; both share the multi-time-step decision pattern.
- **Recipe 7.x (Predictive Analytics / Risk Scoring):** The clinical-need model in this recipe is structurally a risk-scoring problem; Chapter 7's risk-scoring patterns and validation methodology apply directly.
- **Recipe 11.x (Conversational AI / Virtual Assistants):** Member-facing assistants can call this recommender to surface program options conversationally when a member asks "what programs am I eligible for?"
- **Recipe 14.x (Optimization / Operations Research):** The capacity-aware allocator graduates to integer programming when constraints multiply; Chapter 14 covers the formal optimization techniques.

---

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon SageMaker Batch Transform](https://docs.aws.amazon.com/sagemaker/latest/dg/batch-transform.html)
- [Amazon SageMaker Feature Store](https://docs.aws.amazon.com/sagemaker/latest/dg/feature-store.html)
- [Amazon SageMaker XGBoost Built-in Algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/xgboost.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon Bedrock structured output and function calling](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-call-tools.html)
- [Amazon EventBridge Scheduler](https://docs.aws.amazon.com/scheduler/latest/UserGuide/what-is-scheduler.html)
- [Amazon SES Developer Guide](https://docs.aws.amazon.com/ses/latest/dg/Welcome.html)
- [Amazon QuickSight User Guide](https://docs.aws.amazon.com/quicksight/latest/user/welcome.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS (Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)

**AWS Sample Repos:**
- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Reference notebooks for XGBoost, Batch Transform, and end-to-end ML pipelines applicable to the per-program scoring stack
- [`amazon-sagemaker-feature-store-end-to-end-workshop`](https://github.com/aws-samples/amazon-sagemaker-feature-store-end-to-end-workshop): End-to-end Feature Store usage that maps directly to the per-member feature pipeline
- [`amazon-bedrock-workshop`](https://github.com/aws-samples/amazon-bedrock-workshop): Hands-on labs covering structured-output prompting that informs the message-tailoring step

<!-- TODO: confirm the current names and locations of the aws-samples repos above; aws-samples and aws-solutions-library-samples have been reorganizing. -->

**AWS Solutions and Blogs:**
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter AI/ML and Healthcare): browse for personalization and recommender reference architectures
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "uplift modeling," "causal inference," "SageMaker Batch Transform," and "personalization" for relevant deep-dives
- [AWS Architecture Blog](https://aws.amazon.com/blogs/architecture/): search "recommendation system" and "ML pipeline" for end-to-end reference architectures

<!-- TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs. -->

**External References (Conceptual and Methodological):**
- [Centers for Disease Control National Diabetes Prevention Program](https://www.cdc.gov/diabetes-prevention/about/index.html): canonical reference for the DPP curriculum, eligibility criteria, and outcome metrics referenced throughout this recipe <!-- TODO: confirm the current CDC NDPP landing-page URL at the time of publication; the site has been reorganized. -->
- [`econml`](https://github.com/py-why/EconML): Microsoft Research's library for heterogeneous treatment effect estimation, directly applicable to the uplift-modeling step
- [`causalml`](https://github.com/uber/causalml): Uber's causal-inference and uplift-modeling library, mature production library with multiple uplift estimators
- [Uplift Modeling, brief survey](https://arxiv.org/abs/2308.09385): contemporary survey of uplift-modeling techniques and their tradeoffs <!-- TODO: confirm this is the most appropriate, up-to-date reference; the field has continued to develop. -->
- [Obermeyer et al. 2019, Dissecting Racial Bias in an Algorithm Used to Manage the Health of Populations](https://www.science.org/doi/10.1126/science.aax2342): widely-cited example of how proxy outcomes encode disparities in healthcare predictive models; foundational context for the equity discussion in this recipe
- [Synthea](https://github.com/synthetichealth/synthea): synthetic patient data generator for non-PHI development

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Eligibility filtering + need scoring + simple engagement prediction + greedy allocation + email outreach via Recipe 4.1's channel optimizer + minimal cohort dashboard | 8-10 weeks |
| Production-ready | Full pipeline: Feature Store + per-program models + uplift estimation (engagement-only on day one, randomized pilots feeding uplift training over the first cohort cycles) + capacity-aware allocator with equity floors + LLM-tailored messaging + PCP override workflow + outcome evaluation pipeline + cohort dashboards + audit log channel | 6-9 months |
| With variations | Add sequential program recommendation, intensity-tier selection, closed-loop care-manager integration, cross-recipe orchestration with Recipe 4.5, LLM-generated longitudinal messaging | 6-12 months beyond production-ready |

---

## Tags

`personalization` · `recommendation` · `uplift-modeling` · `causal-inference` · `capacity-allocation` · `wellness` · `behavior-change` · `equity` · `cohort-analysis` · `bedrock` · `sagemaker` · `feature-store` · `dynamodb` · `step-functions` · `lambda` · `medium` · `production` · `hipaa`

---

*← [Recipe 4.3: Provider Directory Search Optimization](chapter04.03-provider-directory-search-optimization) · [Chapter 4 Preface](chapter04-preface) · [Next: Recipe 4.5 - Medication Adherence Intervention Targeting →](chapter04.05-medication-adherence-intervention-targeting)*
