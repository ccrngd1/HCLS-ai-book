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

Recipes 4.1 through 4.3 built the personalization infrastructure: patient profile store, engagement event pipeline, content recommendation patterns, fairness re-ranking. Recipe 4.4 reuses all of it and adds three new capabilities: uplift modeling, capacity-aware allocation, and longitudinal outcome tracking. The patient-profile store from 4.1 is the same store. The engagement-event stream is the same stream (with new event types added: `program_recommended`, `program_enrolled`, `program_session_attended`, `program_completed`, `program_dropped_out`). The cohort dashboards are the same dashboards (with new metrics added: per-program enrollment rate, completion rate, uplift estimate by cohort).

Looking forward, Recipes 4.5 (Medication Adherence Intervention Targeting) and 4.7 (Care Management Program Enrollment) reuse the uplift-and-allocation pattern almost wholesale. The uplift-modeling investment you make in 4.4 is reusable infrastructure for the rest of the chapter. The capacity allocator becomes more sophisticated in 4.7 and graduates to formal optimization in Chapter 14, but the bones are the same.

---

## General Architecture Pattern

The pipeline has four logical components: a member-feature ingestion path that prepares per-member uplift inputs, a program-catalog ingestion path that maintains the slate of available programs and their capacities, a batch recommendation path that runs periodically to produce the (member, program) allocation, and a feedback path that captures engagement and outcome signals to refine the models.

```text
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

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter04.04-architecture). The Python example is linked from there.

## The Honest Take

Wellness program recommendation is one of those problems where the data science is the easiest part. The hard parts are everything around it: the cross-functional governance of the allocation policy, the long-horizon outcome evaluation that's the only honest measure of whether the programs are working, the equity instrumentation that prevents the optimization from quietly redistributing opportunity to the easiest-to-help cohorts. A team that gets gravitationally pulled toward "let's tune the uplift model more" while the outcome evaluation is still ad hoc is solving the wrong problem.

The thing that surprises people coming from retail recommendation backgrounds is how much of this depends on human-in-the-loop work that doesn't show up in any architecture diagram. The medical director who reads a sample of tailored outreach messages each week and flags the ones that overstate program benefits. The equity committee that watches the cohort dashboards and asks why the SDOH-low cohort's completion rate dropped this quarter. The vendor manager who sees the outcome evaluation and starts a contract conversation with the DPP vendor about price-per-completion. None of those people are users of the system in the SaaS sense; all of them are part of the system in the operational sense. Build for them.

The thing I'd do differently the second time: invest in randomized hold-outs from day one. The temptation, on day one, is to recommend to everyone who's eligible because "we have a program and we want it utilized." That's the moment you can least afford to forgo a randomized control. Six months later, when the medical director asks "is the program working," you have a beautiful dashboard of completion rates and no causal evidence. With a randomized hold-out (10 to 20 percent of eligibles randomly assigned to no-recommendation), you'll have an answer in 12 to 18 months. Without it, you may never have one. The political conversation about "but those members are eligible, they should get the program" is real; the conversation about "we ran the program for three years and we still don't know if it works" is also real, and worse.

The trap worth flagging: confusing engagement metrics with outcome metrics. A wellness recommender that drives more enrollments is not necessarily a better recommender. A wellness recommender that produces members who complete programs is not necessarily a better recommender. The actual metric that matters is whether the members the recommender targeted, who engaged, are healthier (or the costs of caring for them are lower) than they would have been without the targeting. Track engagement, by all means, because it's the only fast feedback loop you have. Just don't optimize purely against it. The recommender will happily over-target sure things and call that success.

Another trap: treating uplift modeling as a magic ingredient. Uplift models are honest about a hard question (what's the causal effect) but they have honest weaknesses (they're noisy, they need substantial data, they're sensitive to confounding). A model that says "this member has an uplift of 0.04" with a 95% confidence interval of [-0.01, 0.09] is telling you something useful: the effect is probably small and you can't be sure it's not zero. Acting on point estimates without considering the intervals is how teams ship recommenders that overconfidently rank members on noise. Always pass the uncertainty through to the allocator. Always show the uncertainty in the dashboards.

One more piece of personal opinion. The wellness-program domain has a long history of vendors with thin evidence, ROI claims that don't survive independent evaluation, and a general sense that "we sent emails and people enrolled" counts as program success. The recipe in this chapter is built for plans that want to do better than that. The architecture supports honest evaluation; whether the team commits to running the honest evaluation is a cultural choice, not a technical one. If your organization's wellness program is fundamentally a check-the-box exercise rather than an investment in member outcomes, this recipe will produce more rigorous reports of the same fundamental disappointment, and that may be its most useful contribution. At minimum, you'll know.

Last point, because it's specific to this use case: members are people, and wellness outreach can feel intrusive even when it's well-targeted. A member who gets recommended to DPP, smoking cessation, and stress reduction in the same month may correctly conclude that the plan thinks they're a mess, even if each recommendation was clinically defensible in isolation. The contact-frequency cap and the per-member single-program-per-run rule exist for this reason. Be more conservative than you think you need to be. The cost of an over-targeted member opting out of all wellness communications is high; you can't easily get them back. Default to fewer touches with higher tailoring quality. The members who want more will tell you.

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

## Tags

`personalization` · `recommendation` · `uplift-modeling` · `causal-inference` · `capacity-allocation` · `wellness` · `behavior-change` · `equity` · `cohort-analysis` · `bedrock` · `sagemaker` · `feature-store` · `dynamodb` · `step-functions` · `lambda` · `medium` · `production` · `hipaa`

---

*← [Recipe 4.3: Provider Directory Search Optimization](chapter04.03-provider-directory-search-optimization) · [Chapter 4 Preface](chapter04-preface) · [Next: Recipe 4.5 - Medication Adherence Intervention Targeting →](chapter04.05-medication-adherence-intervention-targeting)*
