# Recipe 4.10: Dynamic Treatment Regime Recommendation ⭐⭐⭐⭐⭐

**Complexity:** Complex · **Phase:** Research-to-Production · **Estimated Cost:** ~$0.05-0.25 per-patient regime evaluation (depends on horizon length, number of decision points, off-policy evaluation cost, and clinician-facing rationale generation)


---

## The Problem

Sara is 52. She was diagnosed with stage 3 chronic kidney disease four years ago, type 2 diabetes nine years ago, and hypertension some time before either of those (the chart says 2009; her own memory says "earlier than that, but who's keeping track"). Over the last three years her A1c has been a moving target: 7.4 to 8.1 to 7.6 to 8.9 to 7.9 to 8.4. Her eGFR has drifted from 52 to 41 over the same period. Her blood pressure has been mostly controlled on a thiazide and an ACE inhibitor, except for the six months her ACE was held while her potassium was running high after the SGLT2 was started, and except for the three months last year when she stopped one of the medications because she was traveling for her daughter's wedding and the pharmacy was a hassle. Her endocrinologist added a GLP-1 last spring; her cardiologist asked about adding a beta blocker after she had an episode of chest tightness in August that turned out to be musculoskeletal but felt cardiac in the moment. Her nephrologist has been gently raising the topic of whether she should start preparing for renal-replacement-therapy planning, which Sara has been gently changing the subject about. She takes seven medications, sees four specialists, and works full-time as a paralegal. The next decision point in her care is in two weeks, when she sees her PCP for a quarterly review. The decision involves her diabetes regimen, her blood pressure regimen, and possibly her renal-protection strategy. The decision is one of, conservatively, two dozen plausible combinations.

What Sara actually wants, what her PCP wants, and what nobody has at the visit, is a recommendation that says: "given everything we know about Sara so far, given how she has responded to past adjustments, given her labs over the next twelve weeks, given her tolerance and adherence patterns, here is the *sequence* of adjustments that, on average, leads to the best long-term outcome for patients like her, and here is the next adjustment in that sequence." Not a single treatment. A sequence. A *policy* that says what to do at each decision point, conditional on the patient's state at that point, with the recognition that the right answer at decision point three depends on what happened at decision points one and two.

This is qualitatively different from the question Recipe 4.8 (Treatment Response Prediction) answers. 4.8 estimates the effect of a treatment compared to a comparator at a single decision point; the patient's covariates go in, the per-treatment expected outcome differences come out, the clinician picks. That framing is right when each decision is independent. It is wrong when decisions are sequential and the right choice now depends on what you plan to do next, what you have already done, and how the patient has responded along the way. Sara's care is a sequence: this quarter's medication adjustment depends on her response to the last one and pre-positions her for the next one. Adding a GLP-1 now versus an SGLT2 now is not just a one-time comparison; it is a choice about which path through future decisions you are committing to. The patient who starts on the SGLT2 and ends up needing a GLP-1 six months later is in a different place than the patient who started on the GLP-1 and never needed the SGLT2. Both arrive at "on a GLP-1." The path matters.

Recipe 4.10 is about producing recommendations for the path. Not the next step in isolation. The next step *as part of a coherent sequence* that has been evaluated for long-term outcome. The technical name is *dynamic treatment regime* (DTR), and the field that produces it has been quietly maturing in academic settings for two decades while production healthcare ML has mostly ignored it. The reasons for the neglect are reasonable: dynamic treatment regimes are harder to estimate than single-decision treatment effects, the data requirements are heavier (you need longitudinal observational data with multiple decision points), the methodological discipline is more demanding (counterfactual reasoning across sequences instead of just across treatments), and the regulatory framing is more fraught (the regime is a clinical decision-making artifact whose use crosses into FDA-regulated territory in many implementations). The combination has kept dynamic treatment regimes in the research literature longer than they belong there.

The reasons it's worth doing anyway are also reasonable: chronic disease management is sequential. The prevailing model of "pick a treatment, see how it goes, pick the next one" is sequential decision-making with no formal optimization across the sequence. The sequence is mostly being assembled in clinician minds, with whatever heuristics and biases come along, and the hold-out evaluation of "did the sequence as a whole work" rarely happens. A patient like Sara is on her third or fourth regime adjustment. There is, somewhere in the data, an answer to "for patients like Sara, what is the sequence of adjustments that historically produced the best outcome?" That answer is not the same as "what is the best treatment to add now?" The path-dependence is the whole point. Treating dynamic treatment regimes as out of scope means leaving on the table the entire question of what the right *plan* is, while answering, repeatedly, the smaller question of what the right *next* thing is.

The other reason to take it seriously is that several specific clinical contexts have produced dynamic-treatment-regime work that is no longer hypothetical. SMART (Sequential Multiple Assignment Randomized Trial) designs have produced randomized data on treatment sequences in oncology, depression, ADHD, addiction medicine, and HIV care over the past fifteen years. The MIMIC database has been used for off-policy evaluation of sepsis treatment policies, mechanical ventilation policies, and ICU sedation policies. The work has been peer-reviewed, replicated, and (in a few cases) prospectively tested. The methodological scaffolding is real. What has been missing is the production engineering: how to take a research-grade dynamic-treatment-regime analysis and turn it into a system that can run on real patients, in real clinical workflows, with appropriate guardrails. That is what this recipe is about.

The reason this is the last recipe in Chapter 4, and a five-star Complex one, is that it is the most demanding recipe in the chapter on every axis. The methodology is the heaviest (offline reinforcement learning and sequential causal inference). The data requirements are the largest (longitudinal observations with treatment changes and outcomes spanning months to years). The validation discipline is the strictest (off-policy evaluation, sensitivity analysis, and prospective surveillance). The regulatory posture is the firmest (decision support that materially shapes a sequence of clinical decisions is harder to keep outside the SaMD definition than single-decision support). The clinical engagement requirements are the deepest (clinicians need to understand what a policy is, what off-policy evaluation gives them, and where the recommendation should and should not be trusted). And the recipe has the most upstream dependencies in the chapter: it builds on the per-treatment CATE infrastructure from 4.8, the personalization and burden-aware planning from 4.9, the care-management and adherence infrastructure from 4.5 and 4.7, the cohort modeling from 4.6, and the engagement and channel infrastructure from 4.1 and 4.2. If you read this recipe and think "this is a lot," you are not wrong. The recipes that come before it have laid the groundwork. This recipe puts the cap on it.

We are going to build the architecture for this. The hard parts are not the AWS services. The hard parts are the methodology, the regulatory framing, and the operational discipline. The recipe takes all of them seriously.

Let's get into how you build it.

---

## The Technology: Sequential Decision-Making, Off-Policy Evaluation, and the Reinforcement-Learning Connection

### What a Dynamic Treatment Regime Actually Is

Strip the jargon back. A *dynamic treatment regime* is a function. The function takes the patient's *state* at a decision point as input and returns the *action* (treatment, dose, intervention, or "wait and see") that should be taken at that point. Apply the function at decision point one, then update the state based on what happened, then apply the function again at decision point two, and so on through the patient's care horizon. The function is *dynamic* in the sense that the recommended action depends on the current state, not just on a fixed treatment plan written at the start. The function is a *regime* in the sense that it covers an entire sequence of decisions across the care horizon, not just a single one.

In reinforcement-learning terminology (the field that has formalized this most rigorously), the regime is a *policy*: a mapping from states to actions. The patient's care episode is a *trajectory* through the state space, with rewards (clinical outcomes) accumulating along the way. The goal is to find a policy that maximizes the expected cumulative reward. In a clinical setting, the reward is some combination of clinical effectiveness (A1c control, blood pressure control, eGFR stability), absence of harm (no severe hypoglycemia, no acute kidney injury, no hospitalization), and patient-centered outcomes (preserved functional status, low therapeutic burden, alignment with stated goals).

The key distinction from Recipe 4.8 is the temporal structure. 4.8 estimates a CATE at a single decision point. Recipe 4.10 estimates the value of a *policy*: how well a function from states to actions performs *over a sequence of decisions*. Estimating policy value requires considering how the action at decision point one influences the state at decision point two, which influences the action at decision point two, which influences the state at decision point three, and so on. The path-dependence is the whole point.

Several practical primitives organize the work:

**State.** The patient's condition at a decision point, summarized as a vector or structured representation. For Sara, the state at the next decision point includes her current A1c, her current eGFR, her current blood pressure trajectory, her current medication list, her recent labs, her recent encounters, her stated preferences, her social situation, and any new diagnoses since the last decision. The state must be rich enough to support the *Markov property* (the future depends on the past only through the current state). In practice, the strict Markov property is rarely true; what we have is a state representation that approximates it well enough for the policy to be useful, and we accept that as a working assumption.

**Action.** The intervention chosen at the decision point. For Sara, actions include "add a second-line oral diabetes agent," "switch the GLP-1 to a different formulation," "add a beta blocker," "increase the SGLT2 dose," "schedule a nephrology consult," "do nothing this quarter and re-evaluate in three months." Actions are drawn from a *catalog* (the same kind of treatment catalog as Recipe 4.8, extended to include non-medication actions and "wait" as an explicit choice). The catalog is governed by clinical leadership. The catalog version is recorded as part of every decision the policy makes.

**Reward.** The outcome that accrues between decision points and at the end of the horizon. Rewards are typically a weighted combination of multiple outcomes (clinical effectiveness, harm avoidance, burden, cost), with the weights reflecting the program's goals. In oncology, the reward might be progression-free survival; in HIV care, it might be sustained viral suppression; in chronic disease management, it might be a composite of disease-control metrics minus penalties for adverse events. The choice of reward is a clinical-leadership decision, not an engineering one. A poorly-chosen reward function produces a policy that optimizes the wrong thing; that is an alignment problem with downstream clinical consequences.

**Horizon.** How far into the future the policy's value is evaluated. Horizons in chronic disease management are months to years. Horizons in acute care (sepsis policies in the ICU, mechanical-ventilation weaning) are hours to days. The longer the horizon, the harder the off-policy evaluation, because the further into the future you project counterfactual trajectories, the more compounding error you accumulate. Most production deployments use *finite-horizon* formulations with explicit truncation; *infinite-horizon* formulations (with discount factors that down-weight far-future rewards) are also common and have similar tradeoffs.

**Decision points.** When the policy is consulted. In chronic disease management, decision points are typically aligned with clinical encounters or scheduled review intervals (every visit, every quarter, every year). In acute care, decision points can be every shift, every hour, or even every minute. The granularity of decision points affects everything downstream: the data volume, the action space at each point, the temporal resolution of the state representation, and the operational integration with the clinical workflow.

**Policy.** The function that maps from state to action at a decision point. Policies can be deterministic (always pick the same action for a given state) or stochastic (pick actions with probabilities that sum to one, given the state). Stochastic policies are sometimes useful for exploration in the training data; deterministic policies are typically what gets deployed because they are easier to explain and audit.

**Behavior policy versus target policy.** The historical data was generated by clinicians making decisions; that is the *behavior policy*. The policy we are trying to evaluate or improve is the *target policy*. Off-policy evaluation is the technical work of estimating the target policy's value using data generated by the behavior policy. This is harder than evaluating the behavior policy itself (which you could do by just looking at historical outcomes) because the trajectories under the target policy differ from those under the behavior policy, and the data does not contain those trajectories directly.

### Why It Is Hard

Dynamic treatment regime estimation is harder than single-decision treatment effect estimation for several reasons that compound:

**The action space is exponentially large.** A single decision point with five actions has five options. Two decision points have 25 sequences. Five decision points have 3,125 sequences. Twenty decision points across a multi-year chronic-disease horizon have over 95 trillion sequences. Most sequences are never observed in the historical data; the policy needs to generalize across them, not enumerate them.

**Confounding compounds across decisions.** Every confounding pattern that affects single-decision causal inference (Recipe 4.8) compounds across decisions. The clinician's decision at point three is influenced by what happened between points two and three, which is influenced by the action at point two, which is influenced by what happened between points one and two, which is influenced by the action at point one. The dependence chain produces *time-varying confounding* that classical methods (regression adjustment, propensity scoring at a single time point) handle poorly. Specialized methods (G-methods: G-computation, G-estimation, marginal structural models with inverse probability of treatment weighting) are required.

**Off-policy evaluation has high variance.** Most off-policy evaluation methods (importance sampling, doubly-robust estimators, fitted Q evaluation) have variance that grows with the horizon and with the divergence between the behavior policy and the target policy. A target policy that recommends actions very different from what clinicians historically did will have very wide confidence intervals on its estimated value, because the data does not contain trajectories that look much like what the target policy proposes. The honest output reports those wide intervals; the dishonest output reports a point estimate as if it were precise.

**Distributional shift across the horizon.** Patients who reach decision point ten differ from patients who started at decision point one (some had bad outcomes and dropped out, some had good outcomes and stopped needing care, some changed insurers, some moved). The training data at later decision points is a non-random subset of the training data at earlier decision points. Naive off-policy evaluation that ignores this attrition produces optimistic value estimates; methods that account for it (inverse-probability-of-censoring weighting, formal selection-bias correction) produce more honest estimates with wider intervals.

**Reward specification is high-stakes and contested.** A reward function that combines clinical effectiveness, harm avoidance, burden, and cost requires picking weights. The weights encode a clinical and operational policy: how much hypoglycemia risk are we willing to trade for A1c reduction? How much burden are we willing to add for incremental disease-control benefit? How much do we down-weight outcomes for older patients with limited life expectancy? Different reasonable people pick different weights. The system needs to make those weights explicit, surface the implications (this policy aggressively prefers GLP-1 over SGLT2 for Sara because the reward function we picked weights weight loss heavily), and allow the clinical-leadership review process to revisit the weights as outcomes accumulate.

**Distribution shift over time.** The historical data spans years. Practice patterns change. Drug formulations change. Outcome definitions evolve as guidelines update. Cohort demographics shift. A policy estimated on data from 2018-2022 may be optimal for the population in 2018-2022 and no longer optimal for the population in 2026-2027. Continuous re-evaluation against newer data is required, and the cadence of re-evaluation must be set against the rate of underlying drift.

**Safety and exploration limits.** In classical reinforcement learning, the agent learns by acting and observing rewards, including from suboptimal actions. In healthcare, deliberately taking suboptimal actions to learn is unethical. The system must learn from existing observational data (offline reinforcement learning) without generating new trajectories through experimental treatment. This restricts the methods to those that can produce safe and reliable estimates from observed data alone, with the conservatism that implies.

**The clinician's role is non-negotiable.** A dynamic treatment regime that is presented to clinicians as "the system says do X next" without the underlying reasoning, the evidence base, the alternative actions, and the uncertainty has missed the point. The clinician is the decision-maker; the system is decision support. The interface design, the explanation layer, and the override workflow are as important as the estimator. A high-performing policy that clinicians do not engage with is, operationally, a policy that does not exist.

### Methods for Dynamic Treatment Regime Estimation

Several method families have matured to the point where they can be used in production with appropriate discipline:

**Q-learning for sequential treatments.** Backward-induction estimation of the optimal action-value function. Start at the last decision point and estimate the optimal action given the state at that point. Move to the second-to-last decision point and estimate the optimal action assuming the optimal policy will be followed at the last decision point. Continue back to the first decision point. Q-learning gives an explicit policy (pick the action with the highest estimated Q-value at each decision point) and an estimate of policy value. The original Watkins formulation generalizes; the SMART-trial-tailored work of Susan Murphy and her collaborators (Q-learning with regression at each stage, with carefully-chosen models) is the canonical statistical-medical-literature reference.

**A-learning.** A semiparametric alternative to Q-learning that focuses on the contrast between treatments at each decision point rather than the absolute value of each treatment. A-learning is more robust to misspecification of the outcome model, at some cost in efficiency. Robins's structural-nested-mean-models framework is the underlying theory. Implementation tooling is less polished than Q-learning's; the methodological literature is rich.

**Outcome-weighted learning.** Direct estimation of the optimal regime by reframing the problem as a weighted classification problem. Each historical trajectory is classified by its outcome; trajectories with better outcomes contribute more to the classifier; the classifier directly produces the recommended action at each decision point as a function of state. The Yingqi Zhao et al. work and subsequent extensions are the canonical references. Outcome-weighted learning sidesteps some of the misspecification concerns of Q-learning, with its own tradeoffs around feasibility-set restrictions.

**Marginal structural models with IPTW.** A class of models that uses inverse probability of treatment weighting to construct a pseudo-population in which treatment is unconfounded by the time-varying confounders, then estimates the effect of a hypothetical regime in that pseudo-population. Marginal structural models are well-suited to estimating the population-level value of a candidate regime; they are less well-suited to estimating the optimal regime directly. Often used as a complement to Q-learning or A-learning rather than as the primary estimator.

**Offline reinforcement learning.** A growing family of methods (Conservative Q-Learning, Behavior-Regularized Actor-Critic, Implicit Q-Learning, Decision Transformer, and others) that learn policies from offline trajectories with explicit constraints on how far the learned policy can drift from the behavior policy. These methods come from the machine-learning literature and are increasingly being applied to medical sequential-decision problems with appropriate causal-inference grounding. The literature on offline RL for sepsis, mechanical ventilation, and ICU care is the canonical applied corpus; Komorowski et al. on the AI Clinician for sepsis is the most cited and most controversial example, with a lively follow-up literature on what was and was not validated about the resulting policy.

**Deep G-computation and causal transformers.** Deep-learning-based estimators that combine G-computation (Monte Carlo simulation of trajectories under a candidate regime) with neural network function approximators. These methods scale to high-dimensional state representations and complex action spaces at the cost of more demanding model selection, validation, and interpretability work. Useful for problems where the state representation is high-dimensional (raw EHR sequences, imaging features, genomic profiles); often overkill for problems where a curated feature set captures the relevant state.

**Target trial emulation, sequential edition.** Hernán and Robins's framework extended to the sequential-decision setting. Specify the sequence of hypothetical treatment strategies, then construct the analytic dataset to emulate the sequential trial. The methodological discipline is the same as in Recipe 4.8: protocol specification, careful eligibility and censoring, conservative sensitivity analysis. Sequential target trial emulation is more demanding than single-decision target trial emulation but produces estimates with much better correspondence to randomized-trial benchmarks where they exist.

A production system uses multiple methods, compares results, and is conservative when the methods disagree. Q-learning is typically the workhorse because it produces an explicit policy and is well-understood; the other methods serve as validators and sensitivity tools. The pattern that fails is treating the chosen method as authoritative; the pattern that works is treating the *agreement among methods* as the signal of regime robustness, with disagreement triaged for further investigation.

### Off-Policy Evaluation: How You Know the Regime Is Good

The hardest part of dynamic treatment regime work is not training the policy. It is *evaluating* the policy without deploying it. You have a candidate policy. You want to know: if we deployed this policy across the patient population, what would the average outcome be? The answer cannot come from a forward-looking experiment (you cannot ethically run a randomized trial of a learned policy versus standard care without significant additional groundwork). The answer has to come from the historical data, with appropriate methods.

Several off-policy evaluation methods are commonly used:

**Importance sampling.** Reweight historical trajectories by the ratio of the target-policy probability of the action taken to the behavior-policy probability of the action taken. The weighted average outcome is an unbiased estimator of the target policy's value. The catch is variance: if the target policy frequently picks actions the behavior policy rarely picked, the weights are huge and the estimator is unstable. Self-normalized importance sampling (weighting by the average weight) and weighted importance sampling reduce variance at some cost in bias.

**Doubly-robust off-policy evaluation.** Combine importance sampling with a fitted Q model. The estimator is consistent if either the importance weights or the Q model is correctly specified. Doubly-robust estimators are the workhorse of modern off-policy evaluation because they have better variance properties than pure importance sampling and better robustness to misspecification than pure Q-evaluation.

**Fitted Q evaluation (FQE).** A direct method that fits an action-value function for the target policy and estimates the policy's value as the average of the fitted Q-values across the starting states. FQE is biased toward the Q model's misspecifications but has much lower variance than importance sampling. Often used as a complement to importance sampling.

**Per-decision and weighted importance sampling variants.** Variants that decompose the importance weights across decision points to reduce the compounding-variance problem. Useful for long horizons; the tradeoff is bias-variance and method complexity.

**Behavior policy estimation.** Off-policy evaluation requires the behavior policy's action probabilities (the propensity of the historical clinician to choose each action given the patient's state). These are not observed and must be estimated. A poorly-estimated behavior policy produces poor importance weights and poor evaluations. The behavior-policy estimator is itself a model that requires validation, calibration, and monitoring.

The numerical output of off-policy evaluation is a value estimate with a confidence interval (or a Bayesian posterior). The confidence interval is what the clinician and the governance committee actually care about. A point estimate of "policy value 0.85" without an interval is not actionable; a "policy value 0.85 with 95 percent CI 0.72 to 0.91" is actionable, and a "policy value 0.85 with 95 percent CI 0.45 to 1.05" is a signal that the policy's value is poorly identified by the data and should not be deployed without more evidence.

### Where the Field Has Moved

A few years' worth of progress that matters for production:

- **Methodological convergence.** The statistical, biostatistical, and machine-learning communities have substantially converged on the basic framework: counterfactual reasoning across sequences, careful handling of time-varying confounding, off-policy evaluation with doubly-robust methods, and explicit uncertainty quantification. The framework that dominates production-ready work is target trial emulation extended to the sequential setting, with offline reinforcement learning or Q-learning for the policy estimation.
- **Tooling has matured.** Libraries for offline reinforcement learning (d3rlpy, RLlib's offline RL support), causal inference (DoWhy, EconML, CausalML), and target trial emulation (the TargetTrialEmulation R package and related Python tooling) have stabilized. The barrier to running a methodologically defensible pipeline is now operational and clinical, not statistical.
- **Empirical validation against randomized data.** Several papers in the last few years have estimated policies from observational data and validated them against randomized-trial benchmarks, with mixed but instructive results. The HIV-care policy work, the diabetes-stepwise-therapy work, and the sepsis-ICU work have produced both successes and cautionary tales. The cautionary tales are arguably more valuable than the successes because they show concretely what the methods miss.
- **FDA SaMD guidance has evolved.** Predetermined change control plans, Good Machine Learning Practice principles, and the ongoing regulatory science work have produced a clearer (though still evolving) framework for AI/ML-based clinical decision support. Treatment-regime tools that materially shape sequential clinical decisions are squarely in the SaMD scope. <!-- TODO: confirm current FDA SaMD guidance, the Predetermined Change Control Plan policy, and the Good Machine Learning Practice principles at the time of build. -->
- **Federated and consortium work.** OHDSI, PCORnet, and the Sentinel network have produced multi-institution sequential treatment studies with privacy-preserving methods. These pooled analyses address the small-sample problem at single institutions and produce reference policies that can serve as priors or benchmarks for institution-specific work.
- **Patient-engagement research.** Work on how patients understand and respond to policy-based recommendations is appearing more frequently in the literature. The findings are nuanced: patients do not always prefer the policy that maximizes the expected clinical outcome. They prefer policies that respect their stated values, that explain their reasoning, and that allow for meaningful patient input. This shapes the user-experience layer of the recipe; a policy presented as a directive performs worse, on engagement and on outcomes, than a policy presented as a structured recommendation with patient-aligned reasoning.

### Where LLMs Fit (and Don't)

Same pattern as Recipes 4.5 through 4.9, with regime-specific notes:

- **Policy estimation, off-policy evaluation, regime selection.** Not the LLM's job. Statistical methods (Q-learning, A-learning, offline RL, target trial emulation) trained on validated cohorts.
- **Clinician-facing regime briefings.** Yes. A structured-output prompt takes the policy's recommended action at the current decision point, the alternative actions and their estimated values, the patient's state summary, the off-policy evaluation confidence intervals, and the regime version, and produces the paragraph the clinician reads. The briefing surfaces the recommendation, the comparison to alternatives, the uncertainty, the data-quality flags, and the explicit "the regime suggests, the clinician decides" framing.
- **Patient-facing regime explanations** (when the clinician chooses to share). Yes, with the same validator pattern as prior recipes. The patient version uses lay-language equivalents, with reading-level matched and approved-claim language enforced. Patient-facing regime communication is harder than patient-facing single-decision communication because the regime's logic is path-dependent; the explanation must convey "this is the recommendation now because of how things have gone, and we will reassess next time."
- **Free-form clinical reasoning about which regime to follow.** No. The LLM does not pick; it packages. The line is the same line as in 4.7 and 4.8. Treatment regimes are the highest-stakes recipe in this chapter, so the line is even more important.
- **Why-this-action narrative.** Yes, when the system surfaces feature contributions, similar-trajectory examples, and guideline references alongside the policy's recommendation. The LLM packages a structured rationale; the underlying contributors come from the regime model and the clinical-content layer, not from the LLM's own knowledge.

### Where This Sits in the Chapter

This is the synthesis-extension recipe of Chapter 4. Recipe 4.9 produces a personalized care plan at a point in time; Recipe 4.10 produces sequences of plan adjustments over time, optimized against long-horizon outcomes. The infrastructure compounds heavily: the patient-feature pipeline from 4.5 through 4.9, the cohort modeling from 4.6 through 4.9, the per-treatment CATE infrastructure from 4.8, the validator pattern from 4.5 through 4.9, the equity instrumentation from 4.4 through 4.9. The new architectural pieces are the trajectory store (longitudinal observation of state, action, and outcome triples), the sequential-causal-modeling stack, the off-policy evaluation pipeline, the regime serving layer that produces the recommendation at a decision point, the regime governance layer (model risk classification, change control plan, surveillance), and the post-decision feedback loop (the actual trajectory compared to the predicted trajectory, fed into model retraining and drift detection).

The clinical stakes are at the top of the chapter. The regulatory posture is the strictest. The validation discipline is the most demanding. Most organizations should build to Recipe 4.9 first and treat 4.10 as a deliberate extension undertaken with clinical leadership engagement, regulatory legal involvement, and conservative scoping. Pick a clinical area with strong sequential-decision needs (chronic disease management with frequent decision points, oncology with line-of-therapy decisions, ICU sedation and weaning), build the regime carefully, validate it thoroughly, deploy it with conservative use restrictions, and expand from there. The pattern that fails is treating Recipe 4.10 as just-another-ML-model and shipping a policy that has not been validated to the standard the clinical use requires.

---

## General Architecture Pattern

The pipeline has seven logical components: a regime catalog component that maintains the structured representation of regimes in scope (state definitions, action catalogs, reward functions, decision-point cadences, eligibility predicates, governance metadata); a trajectory pipeline component that constructs longitudinal trajectories from source clinical data; a sequential-causal-modeling component that estimates regimes (Q-learning, offline RL, target trial emulation) with uncertainty; an off-policy-evaluation component that estimates regime value with confidence intervals; a regime-serving component that produces recommendations at decision points; a clinician-facing decision-support component that packages recommendations with rationale, alternatives, and uncertainty; and a feedback and surveillance component that captures actual trajectories and drives retraining, calibration monitoring, and post-deployment surveillance.

```
┌───────── REGIME CATALOG (governance-controlled) ──────────────┐
│                                                                │
│  [Pharmacy / Therapeutics]   [Clinical informatics]            │
│  [Outcomes research]   [Compliance / Regulatory]               │
│  [Patient-advisory representation]                             │
│           │                       │                  │         │
│           └──────────┬────────────┴────────┬─────────┘         │
│                      ▼                     ▼                   │
│         [Regime spec: regime_id, clinical_area,                │
│          state_definition, action_catalog,                     │
│          reward_function (with weights and rationale),         │
│          decision_point_cadence, eligibility_predicates,       │
│          horizon, evidence_level, model_risk_tier,             │
│          cleared_for_decision_support_use,                     │
│          version, effective_dates, change_control_plan]        │
│                      │                                         │
│                      ▼                                         │
│         [Persist to regime-catalog store; versioned;           │
│          governance approval required for new regimes,         │
│          tier promotions, and reward-function changes]         │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── TRAJECTORY PIPELINE (batch, scheduled) ──────────────┐
│                                                                │
│  [EHR / FHIR]  [Claims]  [Pharmacy]  [Lab]  [Vitals]           │
│  [SDOH]  [PROMs]  [Patient registries]  [Mortality]            │
│                          │                                     │
│                          ▼                                     │
│              [Phenotype computation: condition flags,          │
│               severity scores, comorbidity profile,            │
│               trajectory features]                             │
│                          │                                     │
│                          ▼                                     │
│              [Decision point identification: alignment to      │
│               clinical encounters, scheduled reviews, or       │
│               regime-defined intervals]                        │
│                          │                                     │
│                          ▼                                     │
│              [State construction at each decision point:       │
│               patient features summary, recent labs,           │
│               recent encounters, current medications,          │
│               prior regime actions]                            │
│                          │                                     │
│                          ▼                                     │
│              [Action labeling: which regime action              │
│               (or out-of-catalog) was actually taken           │
│               at each decision point]                          │
│                          │                                     │
│                          ▼                                     │
│              [Reward computation: between-decision-point        │
│               outcome accumulation; censoring handling]        │
│                          │                                     │
│                          ▼                                     │
│              [Trajectory persistence: per-patient sequence     │
│               of (state, action, reward, next_state)           │
│               tuples, plus metadata]                           │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── SEQUENTIAL CAUSAL MODELING (offline, scheduled) ─────┐
│                                                                │
│  [Trajectories]  [Regime catalog]                              │
│           │                │                                   │
│           └──────────┬─────┘                                   │
│                      ▼                                         │
│         [Stage A: sequential target trial emulation per         │
│          regime: protocol specification, eligibility,          │
│          treatment strategies, outcome definition,             │
│          censoring]                                            │
│                      │                                         │
│                      ▼                                         │
│         [Stage B: behavior policy estimation (the propensity   │
│          of the historical clinician to choose each action     │
│          given the state); validate calibration]               │
│                      │                                         │
│                      ▼                                         │
│         [Stage C: regime estimation. Multiple methods:         │
│          - Q-learning with backward induction                  │
│          - Offline reinforcement learning (CQL, IQL,           │
│            BCQ as appropriate)                                 │
│          - A-learning or outcome-weighted learning             │
│            as cross-validation                                 │
│          - Marginal structural models for population-level     │
│            policy value comparisons]                           │
│                      │                                         │
│                      ▼                                         │
│         [Stage D: persist regime models, version metadata,     │
│          and behavior policy estimators]                       │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── OFF-POLICY EVALUATION (offline) ─────────────────────┐
│                                                                │
│  [Regime models]  [Behavior policy]  [Trajectories]            │
│           │                │                  │                │
│           └──────────┬─────┴────────┬─────────┘                │
│                      ▼              ▼                          │
│         [Multiple OPE estimators:                              │
│          - Importance sampling (with self-normalization)       │
│          - Doubly-robust off-policy evaluation                 │
│          - Fitted Q evaluation (FQE)                           │
│          - Per-decision and weighted IS variants]              │
│                      │                                         │
│                      ▼                                         │
│         [Compute confidence intervals via bootstrap or         │
│          analytic estimators]                                  │
│                      │                                         │
│                      ▼                                         │
│         [Cohort-stratified OPE: compute regime value in        │
│          subgroups (race, ethnicity, language, age,            │
│          comorbidity tier, geographic region) to surface       │
│          equity-relevant performance disparities]              │
│                      │                                         │
│                      ▼                                         │
│         [Sensitivity analysis: how strong would unmeasured     │
│          confounding need to be to change the conclusion?      │
│          (E-value, Rosenbaum bounds, simulation)]              │
│                      │                                         │
│                      ▼                                         │
│         [Persist OPE results and confidence intervals;         │
│          version-tagged; surfaced to governance committee]     │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── REGIME SERVING (on-demand at decision points) ───────┐
│                                                                │
│  [Decision-point trigger]  [Patient identifier]                │
│           │                                                    │
│           ▼                                                    │
│         [Construct the patient's current state from the         │
│          feature store, the trajectory store (prior            │
│          regime actions), and any recent observations]         │
│           │                                                    │
│           ▼                                                    │
│         [Eligibility check: is this patient eligible for the    │
│          regime at this decision point per the regime's        │
│          eligibility predicates?]                              │
│           │                                                    │
│           ▼                                                    │
│         [Out-of-distribution check: does the patient's state   │
│          fall within the support of the training trajectories? │
│          If not, flag for clinician with the OOD warning]     │
│           │                                                    │
│           ▼                                                    │
│         [Policy evaluation: invoke the regime's policy at      │
│          the patient's state; produce the recommended action,  │
│          the value estimates of alternative actions, the       │
│          per-action confidence intervals]                      │
│           │                                                    │
│           ▼                                                    │
│         [Similar-trajectory retrieval: surface a small         │
│          cohort of historical trajectories most similar to     │
│          the patient's current state, with their actions       │
│          and outcomes, for clinician-visible evidence]         │
│           │                                                    │
│           ▼                                                    │
│         [Persist recommendation_record with rationale,         │
│          alternatives, OOD flag, similar trajectories,         │
│          regime version, model risk tier]                      │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── CLINICIAN-FACING DECISION SUPPORT ───────────────────┐
│                                                                │
│  [Recommendation record]                                       │
│           │                                                    │
│           ▼                                                    │
│         [Structured comparison view: recommended action,       │
│          alternatives with estimated values, uncertainty,      │
│          OOD flag, regime version, similar trajectories,       │
│          guideline references, contraindication checks]       │
│           │                                                    │
│           ▼                                                    │
│         [LLM-generated narrative summary, validator-           │
│          protected: explains the recommendation, the           │
│          alternatives, the uncertainty, and the basis,         │
│          without crossing into prescriptive recommendation     │
│          language]                                             │
│           │                                                    │
│           ▼                                                    │
│         [Override / acknowledgment / patient-share workflow:    │
│          clinician picks an action (which may be the regime's  │
│          recommendation, an alternative, or out-of-catalog),   │
│          captures the rationale if overriding, optionally      │
│          shares the patient-facing summary]                    │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── FEEDBACK AND SURVEILLANCE ───────────────────────────┐
│                                                                │
│  [Action taken events]  [Outcome events]  [Adverse events]     │
│  [Patient-reported feedback]                                    │
│                          │                                     │
│                          ▼                                     │
│              [Trajectory continuation: append the new state,   │
│               action, and accumulated reward to the patient's  │
│               trajectory record]                               │
│                          │                                     │
│                          ▼                                     │
│              [Regime adherence tracking: how often did the     │
│               clinician follow the regime's recommendation,    │
│               by clinical area, by patient cohort, by          │
│               recommendation strength]                         │
│                          │                                     │
│                          ▼                                     │
│              [Outcome surveillance: are observed outcomes      │
│               consistent with the OPE-estimated regime value?  │
│               Drift detection on the calibration of the        │
│               regime's predictions versus realized outcomes]   │
│                          │                                     │
│                          ▼                                     │
│              [Cohort-stratified surveillance: outcome          │
│               trajectories by cohort, regime adherence by      │
│               cohort, OOD-flag rates by cohort. Equity         │
│               disparities trigger committee review]            │
│                          │                                     │
│                          ▼                                     │
│              [Periodic retraining: trajectories accumulate     │
│               into refresh windows; new regime versions are    │
│               re-evaluated against the current version with    │
│               OPE before promotion]                            │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**The regime catalog is governance, not engineering.** The state definition, the action catalog, the reward function, the decision-point cadence, and the eligibility predicates are clinical-program decisions that the regime-governance committee (clinical informatics, P&T, outcomes research, compliance, ideally with patient-advisory representation) authors and approves. The reward function is the most consequential and most contested item in the catalog, because it encodes the program's tradeoffs (clinical effectiveness versus harm versus burden versus cost). The committee documents the reward weights, the evidence basis for them, and the alternatives considered. Reward changes require a formal review with parallel evaluation against the prior reward to surface what the change implies for the policy's recommendations. The pattern that fails is treating the reward as an engineering parameter; the resulting policy optimizes whatever the engineer's intuition encoded, which is rarely what the clinical program wants.

<!-- TODO (TechWriter): Expert review A2 (HIGH). Promote reward-function governance from a paragraph in production-gaps to a first-class architectural subsection (300-500 words) specifying: the multi-stage reward-change process (proposal with documented rationale, parallel-evaluation shadow training under both rewards, diff surface showing per-patient changes in recommended action and per-cohort distributional shift in action mix, committee review and approval, post-promotion audit including PROMs sampling and qualitative feedback for reward-driven unintended optimization). Specify reward_function_version persisted separately on every recommendation record so the audit trail can attribute observed changes correctly. Specify required-content validator layer including reward-version disclosure in the clinician narrative. Reference 4.7 governance SLA and 4.9 burden-threshold-as-policy. -->

**The trajectory pipeline is where the data substrate is built.** Each patient's clinical history is represented as a sequence of (state, action, reward, next_state) tuples, with state at each decision point computed from the feature store and the recent observation history, action labeled from the medication, encounter, or procedure record, and reward computed from the outcomes that accumulated between decision points. The trajectory record is the working artifact for everything downstream; quality issues here propagate to every model. Censoring handling (when patients leave the system, change insurers, or are lost to follow-up) is non-trivial and must be done explicitly with appropriate inverse-probability-of-censoring weights. Out-of-catalog actions (the clinician picked something not in the regime's action catalog) are recorded as such; trajectories with high out-of-catalog rates are surfaced to the catalog-governance committee as a signal that the catalog may need expansion.

<!-- TODO (TechWriter): Expert review A5 (MEDIUM). Specify out-of-catalog rate thresholds (overall, per-cohort, growth-rate) and the escalation policy: catalog inadequacy at the overall threshold triggers a structured catalog-expansion proposal artifact reviewed by the catalog-governance committee; cohort-specific gaps trigger an equity-review cycle in addition to the catalog-governance cycle. Reference 4.7 governance-task SLA pattern for response cadence. -->

**The sequential causal modeling stack is the methodological core.** The protocol mirrors a target trial: specify the regime, eligibility, treatment strategies, outcome definition, censoring, and analytic dataset construction. Multiple estimators (Q-learning as the workhorse, offline RL where the state-action space is high-dimensional, A-learning or outcome-weighted learning as cross-validation) produce candidate regimes. The behavior policy is estimated separately and validated for calibration; a poorly-calibrated behavior policy produces poor importance weights downstream. Disagreements among estimators trigger investigation; agreement is the signal of regime robustness. The training pipeline runs on a scheduled cadence (typically quarterly to annually depending on data drift); each training run produces a candidate regime version that goes through OPE before promotion.

**Off-policy evaluation produces the value estimate that drives deployment decisions.** Multiple OPE estimators (doubly-robust as the workhorse, importance sampling and FQE as complements) produce a value estimate with confidence intervals. Cohort-stratified OPE is non-negotiable: a regime that has a high overall value but a much lower value (or wider intervals) for some cohorts is a regime with a fairness problem before deployment. Sensitivity analysis (E-value, Rosenbaum bounds) bounds how much unmeasured confounding could change the conclusion. The OPE results are the artifact the governance committee reviews; a candidate regime with a confidence interval that does not exclude the prior regime's value is not promoted. The pattern that fails is rushing OPE; the resulting deployment decisions are made on point estimates without the uncertainty discipline that the data demands.

<!-- TODO (TechWriter): Expert review A6 (MEDIUM). Specify horizon-versus-OPE-confidence as an explicit deployment constraint. Document the committee's resolution at scoping (deployment-relevant horizon vs OPE-evaluable horizon), the three-response choice when they diverge (deploy with horizon truncation and explicit narrative disclosure; escalate to per-decision IS, weighted IS, or model-based simulation OPE; defer deployment), and persist evaluation_horizon separately on recommendation records so the audit trail attributes OPE confidence correctly. -->

**The regime serving layer produces the recommendation at the patient's decision point.** State construction (from the feature store and trajectory store), eligibility check, OOD check (does the patient's state fall within the support of the training trajectories?), policy evaluation (the regime's recommended action and the alternatives), similar-trajectory retrieval (a small cohort of historical trajectories most similar to the patient's state, with their actions and outcomes), and recommendation persistence. The OOD check is critical and often overlooked; a regime applied to a patient whose state is far from the training distribution produces a recommendation that is extrapolation, not interpolation. Such recommendations should be flagged with explicit OOD warnings or suppressed entirely depending on the regime's risk tier.

**The clinician-facing decision support is the interface where the regime meets the clinician.** A structured comparison view (recommended action, alternatives with estimated values and uncertainty, OOD flag, regime version, similar trajectories, guideline references, contraindication checks) precedes the LLM-generated narrative. The narrative explains the recommendation, the alternatives, the uncertainty, and the basis, without crossing into prescriptive recommendation language. The validator pattern from Recipe 4.8 applies with stricter rules; regimes that recommend specific treatments are higher-stakes than single-decision treatment-effect estimates. The override and patient-share workflows capture the clinician's actual decision and rationale, which feed back into the surveillance layer.

**Feedback and surveillance close the loop.** Action-taken events, outcome events, adverse events, and patient feedback append to the patient's trajectory record. Regime adherence tracking shows how often clinicians follow the recommendation, by area, cohort, and recommendation strength; low adherence to high-confidence recommendations is a signal of clinician disagreement that merits review. Outcome surveillance compares observed outcomes against the OPE-estimated regime value; calibration drift is the signal that the regime is no longer optimal for the current population. Cohort-stratified surveillance covers outcome trajectories, regime adherence, and OOD rates by cohort; disparities trigger committee review. Periodic retraining accumulates new trajectories into refresh windows; new regime versions are re-evaluated against the current version with OPE before promotion. The surveillance pipeline is where Recipe 4.10 either becomes a living regime or becomes a static artifact that ages out of relevance.

**Equity instrumentation is built in, not bolted on.** Regime value parity across cohorts, regime adherence parity, OOD-rate parity, outcome-trajectory parity. Each axis is monitored, with thresholds that trigger committee review when crossed. The Obermeyer pattern applies particularly sharply here: a regime that was estimated on data reflecting historical access and prescribing disparities will encode those disparities into the recommended actions. Sara, who has stable insurance and a primary-care relationship, is in the data; the patients who look like Sara but were lost to follow-up after one missed appointment are not in the data, or are in the data with different (and confounded) outcomes. Regime estimation that does not surface and address the data-driven disparities produces a policy that perpetuates them.

<!-- TODO (TechWriter): Expert review S4 (LOW). Promote SDOH-cohort PHI sensitivity from implicit to explicit in the privacy paragraph. Cohort attributes carried through OPE stratification, surveillance metric dimensions, and similar-trajectory retrieval are PHI-promoting; specify minimum-necessary cohort attributes per surface and the elevated audit posture for trajectory-store separate-table-partitioning-by-sensitivity-tier. Reference 4.4-4.9 chapter pattern. -->

**Regulatory posture is set early and reviewed often.** Most production deployments of dynamic treatment regime tools fall within the FDA's SaMD definition and do not meet the criteria for the Cures Act non-device exemption when the clinician cannot independently review the basis of the recommendation. The model risk classification, the predetermined change control plan, and the post-deployment surveillance plan are deliverables of the project, not afterthoughts. The clinical-leadership-and-regulatory-legal review is a recurring meeting, not a one-time gate. <!-- TODO: confirm current FDA SaMD framework, the Predetermined Change Control Plan policy, the 21st Century Cures Act CDS exemption criteria, and the Good Machine Learning Practice principles at the time of build. The regulatory landscape is evolving and the analysis is fact-specific. -->

---

## The AWS Implementation

### Why These Services

**Amazon DynamoDB for the regime catalog, trajectory metadata, recommendation records, and surveillance metadata.** Several new tables: `regime-catalog` keyed on `(regime_id, version)` with state definition, action catalog, reward function, eligibility predicates, model risk tier, and clearance status; `trajectory-metadata` keyed on `(patient_id, regime_id)` storing pointers to S3 trajectory blobs and per-patient metadata (start date, current decision-point index, current state hash, censoring status); `recommendation-records` keyed on `(patient_id, regime_id, decision_point_id)` storing each served recommendation with rationale, alternatives, OOD flag, similar trajectories, regime version, and clinician's eventual action; `regime-versions` keyed on `(regime_id, version)` with the registered model artifacts, OPE results, governance-approval status, and effective dates; `surveillance-metrics` keyed on `(regime_id, surveillance_window)` for the operational metrics. DynamoDB is HIPAA-eligible under BAA. The full trajectory data lives in S3; DynamoDB carries the metadata and operational hot path.

**Amazon S3 for trajectory storage, OPE outputs, and the data lake.** Per-patient trajectory records (the sequence of state, action, reward, next_state tuples) are stored as Parquet in S3 with partitioning by patient cohort and regime. Source data feeds (claims, EHR via HealthLake, lab, pharmacy, vitals, PROMs, mortality) land in S3 via Kinesis Firehose and Glue. OPE outputs (the value estimates, confidence intervals, cohort-stratified results, sensitivity analyses) are stored in S3 with version-tagged paths so the governance committee can review historical OPE alongside the model artifacts. The S3 trajectory archive is the system of record for audit; the DynamoDB metadata is the operational store.

**Amazon SageMaker for regime training, model registry, and serving.** SageMaker Training Jobs run the sequential causal modeling stack (Q-learning, offline RL, target trial emulation). The choice of algorithms depends on the clinical area: Q-learning with regression at each stage for chronic-disease management with curated state representations; offline RL (Conservative Q-Learning, Implicit Q-Learning) for high-dimensional state spaces or acute-care problems; A-learning or outcome-weighted learning as cross-validation. The SageMaker Model Registry holds candidate regime versions with their OPE results, governance-approval status, and clearance-for-decision-support metadata. SageMaker Endpoints serve the active regime model for on-demand recommendation generation; the endpoint configuration is multi-model so the same endpoint can serve different regimes by clinical area.

**Amazon SageMaker Feature Store for patient features.** The same feature store from prior recipes is reused. The online store provides low-latency access at the decision point; the offline store powers trajectory construction and cohort analytics. Feature Store's point-in-time-correct retrieval is essential for trajectory construction; the state at decision point three must reflect what was known at decision point three, not what is known today.

**AWS HealthLake for FHIR-native clinical data.** Treatment regimes benefit from FHIR-native storage for the same reasons Recipe 4.9 did: condition lists, medication lists, observation history, encounter history feed directly into trajectory construction. Recommendation outputs map to FHIR `Task` and `ServiceRequest` resources with regime-specific extensions, supporting interoperability across care settings. <!-- TODO: confirm AWS HealthLake's current pricing, HIPAA eligibility, and FHIR specification version support. -->

**Amazon Bedrock for the clinician-facing narrative, with strict validator enforcement.** Two distinct LLM use cases:

1. **Clinician-facing regime briefing.** A structured-output prompt takes the recommendation record (recommended action, alternatives with values and uncertainty, OOD flag, similar trajectories, regime version) and produces a paragraph the clinician reads at the decision point. The briefing surfaces the recommendation, the comparison to alternatives, the uncertainty, the data-quality flags, and the explicit "the regime suggests, the clinician decides" framing.

2. **Patient-facing regime summary** (when the clinician chooses to share). Tailored to reading level, language, and channel preferences. Lay-language equivalents for probabilities and confidence intervals; explicit "this is the next step in your overall plan" framing that connects to Recipe 4.9's care plan.

The validator is a four-layer check applied to every narrative: schema and length, fact grounding (every clinical claim traces to a structured element of the recommendation record or the regime catalog), prohibited-language patterns (no recommendation language for treatments not in the regime's action catalog, no probabilistic claims framed as guarantees, no policy-as-directive framing), and required content (uncertainty disclosure, regime-version reference, override-encouragement framing for the clinician narrative; care-plan-linkage and contact-for-questions for the patient narrative). Failed validations regenerate with feedback or fall back to a templated narrative.

<!-- TODO (TechWriter): Expert review S3 (MEDIUM). Specify the four-layer validator at chapter pattern depth. Inline the regime-narrative-specific prohibited-language pattern set (must include patterns like \bthe regime requires\b, \byou are required to\b, \bmust\s+(?:start|use|prescribe|add|stop)\b plus the chapter-wide \bguaranteed\b and \b100%\s+(?:effective|safe)\b). Specify the required-content rule that the clinician narrative must contain language equivalent to "the regime suggests, the clinician decides" and an explicit override-encouragement clause. Specify the fact-grounding rule that every numeric value cited (recommended_action_value, CIs, alternative values, OOD score) must trace byte-for-byte to a corresponding field. Specify the patient-narrative path-dependence framing rule ("this is the next step given how things have gone, and we will reassess next time") and reading-level enforcement. Reference 4.4-4.9 chapter pattern. -->

<!-- TODO (TechWriter): Expert review A8 (MEDIUM). Promote multi-language patient-narrative architecture from the production-gaps brief mention to a first-class architectural concern: per-language reading-level scoring, per-language approved-claim language, per-language templated fallback, per-language validator dispatch. The path-dependence framing is harder to translate well than single-decision framing; the per-language work is correspondingly more demanding. Reference 4.9 A10 chapter pattern. -->

Bedrock is HIPAA-eligible under BAA. <!-- TODO: confirm current Bedrock service terms, the eligible-model list, and the data-handling guarantees at the time of build. --> <!-- TODO (TechWriter): Expert review N2 (LOW). Note Bedrock cross-region inference profile implications for data residency and BAA scope: cross-region inference may route prompts and completions through regions outside the institution's BAA scope or PHI residency requirements; verify the BAA covers all candidate regions or pin invocations to on-region inference. -->

**AWS Step Functions for training and serving orchestration.** Three workflows: a training workflow (trajectory pipeline, sequential causal modeling, OPE, governance review packaging); a serving workflow (recommendation generation at a decision point); a surveillance workflow (regime adherence, outcome surveillance, drift detection, cohort-stratified monitoring). Step Functions provides the per-stage retry, timeout, and DLQ semantics; all executions are logged to S3 and surfaced in the operational dashboards.

**AWS Lambda for per-stage logic.** The trajectory builder, the behavior-policy estimator, the OPE runner, the eligibility checker, the OOD detector, the policy evaluator, the similar-trajectory retriever, the narrative generator, the validator, the recommendation persister, the action-taken-tracker, the surveillance computer, and the drift detector all run as Lambdas. Each Lambda is in VPC with VPC endpoints for downstream services.

**Amazon EventBridge for scheduling and event-driven triggers.** EventBridge schedules the periodic training cycles and the surveillance computations. Event-driven triggers handle decision-point arrivals: a clinical encounter scheduled for a patient eligible for a regime triggers a recommendation-generation event so the recommendation is ready when the encounter starts.

**Amazon Kinesis Data Streams for the trajectory event bus.** Event types: `decision_point_arrived`, `recommendation_generated`, `action_taken`, `outcome_observed`, `adverse_event_recorded`, `regime_adherence_evaluated`, `regime_version_promoted`, `surveillance_alert_raised`. The stream feeds the state-machine worker that updates the trajectory store, the recommendation records, and the surveillance metrics.

**Amazon API Gateway and Amazon Cognito for the recommendation API.** The clinician-facing recommendation surface is exposed as an authenticated API consumed by the EHR integration (typically a SMART on FHIR app). API Gateway provides the endpoint, Cognito (or the institution's identity provider via SAML or OIDC) provides authentication, and per-clinician audit logs go to CloudTrail. The API supports both pull (clinician requests a recommendation for a patient at the visit) and push (recommendation generated proactively before a scheduled visit and rendered on the EHR's pre-visit screen).

**Amazon QuickSight for governance and operational dashboards.** Per-cohort regime value, regime adherence, OOD-flag rates, and outcome-trajectory dashboards (the equity instrumentation). Per-regime OPE result dashboards (the value estimates and confidence intervals over training runs). Calibration-drift dashboards (predicted versus realized outcomes over surveillance windows). Override-pattern dashboards (which recommendations are clinicians overriding, in which cohorts, with what stated rationales). QuickSight on Athena, with row-level security for cohort-specific access.

**AWS KMS, CloudTrail, CloudWatch.** Same PHI infrastructure pattern as prior recipes, with elevated controls for the regime artifacts. Customer-managed keys, CloudTrail data events on the recommendation tables and trajectory storage, CloudWatch alarms on training failure rates, OPE-confidence-interval-violation rates, OOD-flag rates, and cohort fairness threshold crossings. Recommendation records are sensitive enough that the audit posture is closer to clinical-record audit than typical analytics audit.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Sources
      A1[Claims Feed]
      A2[EHR / FHIR via HealthLake]
      A3[Lab Results]
      A4[Pharmacy / Adherence]
      A5[Vitals and PROMs]
      A6[Mortality / Outcomes]
      A7[CATE from 4.8]
      A8[Care Plan from 4.9]
    end

    A1 -->|Streaming| B1[Kinesis Firehose\ndtr-source-events]
    A2 -->|FHIR| HL1[AWS HealthLake]
    HL1 -->|Export| B1
    A3 -->|Streaming| B1
    A4 -->|Daily| B1
    A5 -->|Streaming| B1
    A6 -->|Periodic| B1
    A7 -->|On change| B1
    A8 -->|On change| B1

    B1 --> S1[S3\ndtr-data-lake]
    S1 --> F1[SageMaker Feature Store\npatient features]

    PR1[Lambda\ncatalog-sync] --> D1[DynamoDB\nregime-catalog]

    EB1[EventBridge\nperiodic train trigger] --> SF1[Step Functions\ntraining]
    SF1 --> L1[Lambda\ntrajectory-builder]
    F1 --> L1
    HL1 --> L1
    S1 --> L1
    L1 --> S2[S3\ntrajectories]

    SF1 --> L2[Lambda\nbehavior-policy-estimator]
    S2 --> L2
    L2 --> S3[S3\nbehavior-policy]

    SF1 --> SM1[SageMaker Training\nQ-learning / offline RL /\nA-learning]
    S2 --> SM1
    S3 --> SM1
    D1 --> SM1
    SM1 --> MR1[SageMaker Model Registry\ncandidate regimes]

    SF1 --> L3[Lambda\nope-runner]
    S2 --> L3
    S3 --> L3
    MR1 --> L3
    L3 --> S4[S3\nope-outputs]

    L3 --> L4[Lambda\ngovernance-package-builder]
    S4 --> L4
    L4 --> S5[S3\ngovernance-packages]

    EB2[EventBridge\ndecision-point trigger] --> SF2[Step Functions\nrecommendation]
    SF2 --> L5[Lambda\nstate-builder]
    F1 --> L5
    D2[DynamoDB\ntrajectory-metadata] --> L5
    L5 --> L6[Lambda\neligibility-and-ood]
    L6 --> EP1[SageMaker Endpoint\nactive regime model]
    EP1 --> L6
    L6 --> L7[Lambda\nsimilar-trajectory-retriever]
    S2 --> L7
    L7 --> L8[Lambda\nnarrative-generator]
    L8 --> BD1[Bedrock\nclinician + patient]
    BD1 --> VL1[Lambda\nvalidator]
    VL1 --> R1[DynamoDB\nrecommendation-records]
    VL1 --> S6[S3\nrecommendation-archives]

    R1 --> AG1[API Gateway\nrecommendation API]
    AG1 --> AU1[Cognito or IdP]
    AU1 --> EHR1[EHR via SMART on FHIR\nclinician decision support]

    EHR1 -.Action taken.-> KS1[Kinesis\ndtr-events]
    KS1 --> SM2[Lambda\nstate-machine-worker]
    SM2 --> R1
    SM2 --> D2

    EB3[EventBridge\nsurveillance schedule] --> SF3[Step Functions\nsurveillance]
    SF3 --> L9[Lambda\nadherence-tracker]
    SF3 --> L10[Lambda\noutcome-surveillance]
    SF3 --> L11[Lambda\ndrift-detector]
    SF3 --> L12[Lambda\ncohort-equity-monitor]
    R1 --> L9
    S6 --> L9
    S2 --> L10
    S2 --> L11
    S4 --> L11
    S2 --> L12
    L9 --> S7[S3\nsurveillance-outputs]
    L10 --> S7
    L11 --> S7
    L12 --> S7

    KS1 --> KF1[Kinesis Firehose]
    KF1 --> S8[S3\ndtr-event-lake]
    S8 --> QS1[QuickSight\ndashboards]
    S7 --> QS1
    S4 --> QS1

    style F1 fill:#9ff,stroke:#333
    style D1 fill:#9ff,stroke:#333
    style D2 fill:#9ff,stroke:#333
    style R1 fill:#9ff,stroke:#333
    style S1 fill:#cfc,stroke:#333
    style S2 fill:#cfc,stroke:#333
    style S4 fill:#cfc,stroke:#333
    style S6 fill:#cfc,stroke:#333
    style S7 fill:#cfc,stroke:#333
    style KS1 fill:#f9f,stroke:#333
    style HL1 fill:#fc9,stroke:#333
    style BD1 fill:#fc9,stroke:#333
    style MR1 fill:#fc9,stroke:#333
    style EP1 fill:#fc9,stroke:#333
    style SM1 fill:#fc9,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon DynamoDB, Amazon SageMaker (Training, Model Registry, Feature Store, Endpoints), AWS HealthLake, Amazon S3, AWS Glue, Amazon Athena, AWS Step Functions, Amazon EventBridge, Amazon Kinesis Data Streams, Amazon Kinesis Data Firehose, AWS Lambda, Amazon Bedrock, Amazon API Gateway, Amazon Cognito, Amazon QuickSight, AWS KMS, Amazon CloudWatch, AWS CloudTrail. |
| **IAM Permissions** | Per-Lambda least-privilege: `dynamodb:GetItem` / `BatchWriteItem` / `UpdateItem` scoped to specific tables (especially `recommendation-records`, `regime-catalog`, `trajectory-metadata`); `bedrock:InvokeModel` on specific foundation-model ARNs; `s3:GetObject` / `PutObject` scoped to trajectory, OPE, recommendation-archive, and surveillance-output buckets; `kinesis:PutRecord` on the dtr-events stream; `sagemaker:InvokeEndpoint` on the regime-serving endpoint ARN; `sagemaker:CreateTrainingJob` and Model Registry actions for training-stage Lambdas; `healthlake:SearchWithGet` and related read actions scoped to the relevant data store. Never `*`. <!-- TODO: pair these actions with one or two scoped Resource ARN examples; mirror the chapter-wide pattern. --> |
| **BAA** | AWS BAA signed. All services in the architecture must be HIPAA-eligible: DynamoDB, SageMaker, HealthLake, S3, Glue, Athena, Step Functions, EventBridge, Kinesis, Firehose, Lambda, Bedrock, API Gateway, Cognito, QuickSight, KMS. <!-- TODO: confirm Bedrock + selected models, HealthLake, SageMaker components, and any EHR-integration components at the time of build. --> |
| **Encryption** | DynamoDB: customer-managed KMS at rest (especially `recommendation-records`, `regime-catalog`, `trajectory-metadata`; the recommendation is a clinical decision-support artifact). S3: SSE-KMS with bucket-level keys. Kinesis and Firehose: server-side encryption. SageMaker Feature Store and Model Registry: KMS keys. SageMaker Endpoints: KMS for storage and TLS for inference traffic. HealthLake: KMS-encrypted at rest, TLS in transit. Lambda log groups KMS-encrypted. Recommendation rationale text in DynamoDB is PHI-adjacent; treat with full clinical-record encryption posture. |
| **VPC** | Production: Lambdas in VPC. SageMaker Feature Store online store and Endpoints run in VPC. VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis, Firehose, KMS, CloudWatch Logs, Step Functions, EventBridge, Glue, Athena, STS, HealthLake, API Gateway, SageMaker. NAT Gateway only for external services without VPC endpoints; restrict egress with security groups. EHR integration typically arrives via PrivateLink, Direct Connect, or the institution's existing private network. VPC Flow Logs enabled. <!-- TODO (TechWriter): Expert review N1 / N3 (LOW). State explicitly "no `0.0.0.0/0` egress rules; egress destinations are explicit per AWS service prefix list or per VPC endpoint; outbound DNS scoped to AWS-internal resolvers." Add API Gateway resource policy posture for the recommendation API: private API with VPC endpoint resource policy restricting access to the EHR integration's VPC, AWS WAF rules for SQL injection / command injection / per-principal rate limiting, optional mTLS where the EHR supports it; no public REST endpoint. --> |
| **CloudTrail** | Enabled with data events on the `regime-catalog`, `trajectory-metadata`, `recommendation-records`, `regime-versions`, and `surveillance-metrics` tables. Data events on the S3 buckets containing source feeds, trajectories, OPE outputs, recommendation archives, and surveillance outputs. Recommendation API invocations logged at the API Gateway and Lambda layers. SageMaker training and inference invocations logged. The audit posture for recommendation artifacts approaches clinical-record audit standards. |
| **Regime Governance** | Regime governance committee charter (clinical informatics, P&T, outcomes research, compliance, regulatory legal, ideally with patient-advisory representation). Documented model risk classification process. Documented predetermined change control plan. Documented OPE-result review and approval policy. Documented retraining cadence and re-evaluation gating policy. Documented model monitoring and drift-response protocol. Cleared-for-decision-support clearance gate that no recommendation is served to clinicians without committee approval. |
| **Sample Data** | A starter set of synthetic longitudinal patient trajectories with realistic multi-decision-point clinical histories (Synthea-derived multi-year trajectories, augmented with explicit decision points, action labels, and outcome events). A starter regime catalog covering one or two clinical areas with strong sequential-decision patterns (chronic disease management for diabetes / CKD / hypertension; depression treatment selection; HIV care). For OPE work, a held-out subset of trajectories used as the validation cohort; a randomized subset (where available, e.g., from SMART trials in the literature) used as the gold-standard benchmark. |
| **Cost Estimate** | At a multi-specialty health system with ~500,000 active patients and ~50,000 patients in active regimes (10 percent in regime-eligible chronic-disease cohorts), with quarterly decision points and monthly surveillance: DynamoDB on-demand: $300-900/month. SageMaker Feature Store: $200-500/month. SageMaker Training (quarterly retraining cycles per regime, ~5 regimes): $1,500-5,000/month. SageMaker Endpoints (multi-model, 4-8 ml.m5 instances): $800-2,000/month. HealthLake: $1,500-5,000/month depending on data volume. Lambda + Step Functions: $400-1,200/month. Bedrock for narratives (~50,000 recommendations per month average across clinician and patient narratives, Sonnet-class for clinician, Haiku-class for patient): $4,000-12,000/month. API Gateway + Cognito: $200-500/month. S3 + Glue + Athena: $600-1,800/month. QuickSight: $50/user/month authors plus reader fees. Estimated infrastructure total: $9,500-29,000/month for a regional system, before staff time, EHR integration, and the (substantial) regime-curation, OPE-validation, and governance costs that dominate this recipe. <!-- TODO: replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator. --> |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon DynamoDB** | Stores the regime catalog, trajectory metadata, recommendation records, regime version registry, and surveillance metrics |
| **Amazon SageMaker (Training)** | Runs the sequential causal modeling pipeline (Q-learning, offline RL, A-learning, target trial emulation) |
| **Amazon SageMaker (Model Registry)** | Holds candidate and approved regime versions with OPE results and clearance status |
| **Amazon SageMaker (Endpoints)** | Serves the active regime models for on-demand recommendation generation |
| **Amazon SageMaker Feature Store** | Per-patient features feeding state construction; offline store powers trajectory construction and cohort analytics |
| **AWS HealthLake** | FHIR-native clinical data store powering condition, medication, observation, encounter, and care-team aggregation; persists recommendation outputs as FHIR `Task` and `ServiceRequest` resources |
| **Amazon S3** | Hosts the dtr-data-lake, trajectories, OPE outputs, recommendation archives, surveillance outputs, and event lake; the immutable trajectory and recommendation archives are the audit system of record |
| **AWS Glue** | Cohort analytics over the trajectory and recommendation data; longitudinal regime-effectiveness ETL |
| **Amazon Athena** | SQL access to the trajectory and recommendation data lake; powers cohort-stratified surveillance and OPE-result review |
| **AWS Step Functions** | Orchestrates training, recommendation, and surveillance workflows |
| **Amazon EventBridge** | Schedules periodic training cycles and surveillance computations; routes decision-point-arrival events |
| **Amazon Kinesis Data Streams** | Carries decision-point, recommendation, action-taken, outcome, and surveillance events |
| **Amazon Kinesis Data Firehose** | Lands trajectory events into S3 Parquet for long-horizon analysis |
| **AWS Lambda** | Runs the trajectory builder, behavior-policy estimator, OPE runner, eligibility checker, OOD detector, similar-trajectory retriever, narrative generator, validator, recommendation persister, action-taken tracker, surveillance computer, and drift detector |
| **Amazon Bedrock** | Hosts the LLM for clinician-facing regime briefings and patient-facing summaries |
| **Amazon API Gateway** | Exposes the recommendation API consumed by the EHR integration layer (SMART on FHIR app) |
| **Amazon Cognito** | Authenticates clinical-team access to the recommendation API; integrates with the institution's identity provider via SAML or OIDC |
| **Amazon QuickSight** | Governance, OPE, surveillance, equity, and override-pattern dashboards |
| **AWS KMS** | Customer-managed encryption keys for all PHI-containing stores |
| **Amazon CloudWatch** | Operational metrics, training-failure alarms, OPE-confidence-interval-violation alarms, OOD-rate alarms, fairness-threshold alarms, drift alarms |
| **AWS CloudTrail** | Audit logging for all PHI-related API calls, recommendation API invocations, regime-version promotions, and SageMaker training and inference invocations |

---

### Code

> **Reference implementations:** Useful aws-samples and open-source patterns for this recipe:
> - [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): SageMaker Training, Model Registry, and Endpoints patterns applicable to regime training and serving.
> - [`amazon-sagemaker-feature-store-end-to-end-workshop`](https://github.com/aws-samples/amazon-sagemaker-feature-store-end-to-end-workshop): Feature Store usage applicable to point-in-time-correct state construction.
> - [`amazon-bedrock-workshop`](https://github.com/aws-samples/amazon-bedrock-workshop): Structured-output prompting applicable to clinician-facing regime briefings and patient-facing summaries.
> <!-- TODO: confirm the current names and locations of the aws-samples repos. -->

#### Walkthrough

**Step 1: Build longitudinal trajectories from source clinical data.** Trajectories are the substrate of dynamic-treatment-regime work; quality issues here propagate to every downstream model. Skip the careful identification of decision points, the precise state construction at each point, and the explicit handling of censoring, and the resulting trajectories produce policies that look defensible and are not.

```
FUNCTION build_trajectories(refresh_window):
    // refresh_window includes the start_date, end_date, and the
    // patient cohorts in scope for this trajectory build.
    eligible_patients = identify_regime_eligible_patients(refresh_window)
        // returns the patient_ids whose clinical histories within
        // the refresh window meet the regime's eligibility criteria
        // (active condition, sufficient longitudinal data, no
        // exclusion criteria).

    FOR each patient_id in eligible_patients:
        // Step 1A: identify decision points. The cadence is regime-
        // specific (typically aligned to clinical encounters,
        // scheduled reviews, or regime-defined intervals).
        decision_points = identify_decision_points(patient_id, refresh_window)
        IF len(decision_points) < MIN_TRAJECTORY_LENGTH:
            // Patients with too few decision points contribute
            // limited signal; record but flag for exclusion from
            // training.
            log_short_trajectory(patient_id, len(decision_points))
            CONTINUE

        trajectory = []
        FOR i, dp in enumerate(decision_points):
            // Step 1B: construct the state at this decision point.
            // The state is built from the feature store (point-in-
            // time-correct retrieval), the trajectory store (prior
            // regime actions), and recent observations.
            state = build_state_at_time(patient_id, dp.timestamp)
                // state schema is regime-defined; typically
                // includes clinical features (severity, comorbidity,
                // recent labs, recent encounters), prior actions
                // taken under the regime, time since last
                // decision point, and any state-relevant patient
                // characteristics.

            // Step 1C: label the action taken at this decision point.
            // The action catalog is regime-defined; out-of-catalog
            // actions are recorded as such.
            action = label_action_at_time(patient_id, dp.timestamp)
            IF action.kind == "out_of_catalog":
                trajectory.append({
                    decision_point_index: i,
                    timestamp: dp.timestamp,
                    state: state,
                    action: action,
                    out_of_catalog: true,
                    out_of_catalog_detail: action.detail
                })
                // Trajectories with high out-of-catalog rates
                // signal catalog inadequacy; surveillance will
                // pick this up.
                CONTINUE

            // Step 1D: compute the reward accumulated between this
            // decision point and the next (or to the end of the
            // horizon). The reward is a weighted combination of
            // outcomes per the regime's reward function.
            next_dp_or_horizon = decision_points[i+1] if i+1 < len(decision_points) else refresh_window.end_date
            reward = compute_reward(patient_id,
                                     dp.timestamp,
                                     next_dp_or_horizon,
                                     reward_function = regime.reward_function)
                // reward_function is a structured spec: per-outcome
                // weights, censoring rules, time-discounting (if
                // any), and adverse-event penalties.

            // Step 1E: handle censoring. If the patient is censored
            // (lost to follow-up, changed insurer, died) before the
            // next decision point or horizon, the trajectory is
            // censored at the censoring time and the censoring
            // weight is computed for IPCW-based estimators.
            censoring = check_censoring(patient_id, dp.timestamp, next_dp_or_horizon)
            IF censoring.censored:
                trajectory.append({
                    decision_point_index: i,
                    timestamp: dp.timestamp,
                    state: state,
                    action: action,
                    reward_to_censoring: reward,
                    censored: true,
                    censoring_reason: censoring.reason,
                    censoring_weight: censoring.weight
                })
                BREAK

            trajectory.append({
                decision_point_index: i,
                timestamp: dp.timestamp,
                state: state,
                action: action,
                reward: reward,
                next_state_timestamp: next_dp_or_horizon,
                censored: false
            })

        // Step 1F: persist the trajectory. The full trajectory is
        // written to S3 as Parquet; metadata (last decision point,
        // censoring status, current state hash) is written to
        // DynamoDB for the operational hot path.
        write_parquet(trajectory,
                      "s3://dtr-trajectories/" + regime.regime_id +
                      "/" + patient_id + "/trajectory.parquet")
        DynamoDB.PutItem("trajectory-metadata", {
            patient_id: patient_id,
            regime_id: regime.regime_id,
            last_decision_point_index: len(trajectory) - 1,
            current_state_hash: hash(trajectory[-1].state),
            censoring_status: trajectory[-1].censored,
            last_updated: current UTC timestamp,
            trajectory_uri: "s3://dtr-trajectories/" + regime.regime_id +
                            "/" + patient_id + "/trajectory.parquet"
        })

    RETURN { eligible_patient_count: len(eligible_patients),
             trajectory_count: count_persisted_trajectories(refresh_window) }
```

**Step 2: Estimate the behavior policy.** Off-policy evaluation requires the propensity of the historical clinician to choose each action given the state. A poorly-estimated behavior policy produces poor importance weights and poor evaluations. The behavior policy is a model in its own right that requires validation, calibration, and monitoring; skip its discipline and the OPE results are not trustworthy.

```
FUNCTION estimate_behavior_policy(trajectories, regime):
    // Step 2A: assemble the behavior-policy training data: pairs of
    // (state, action) from across the trajectories.
    training_data = []
    FOR each trajectory in trajectories:
        FOR each step in trajectory:
            IF step.censored OR step.out_of_catalog:
                CONTINUE
            training_data.append({
                state: step.state,
                action: step.action.action_id,
                cohort: extract_cohort_features(step.state)
            })

    // Step 2B: fit the behavior-policy estimator. Multinomial
    // logistic regression for small action spaces; gradient-boosted
    // trees or a small neural network for larger action spaces or
    // richer state representations.
    behavior_policy_model = fit_behavior_policy_estimator(
        training_data,
        action_catalog = regime.action_catalog,
        method = regime.behavior_policy_method)

    // Step 2C: validate calibration. The behavior policy's predicted
    // action probabilities should match the empirical action
    // frequencies in held-out data, both overall and within
    // cohorts. Miscalibration produces biased importance weights.
    held_out = sample_held_out(training_data, fraction = 0.2)
    calibration_results = compute_calibration_metrics(
        behavior_policy_model, held_out,
        cohort_axes = ["race_ethnicity", "language", "age_band",
                        "comorbidity_tier", "geographic_region"])
    IF calibration_results.overall_ece > BEHAVIOR_POLICY_ECE_THRESHOLD:
        // Calibration failure on the overall metric is a blocker.
        log_calibration_failure(calibration_results)
        RAISE BehaviorPolicyCalibrationFailure
    FOR each axis, axis_results in calibration_results.cohort_axes:
        IF axis_results.worst_cohort_ece > BEHAVIOR_POLICY_COHORT_ECE_THRESHOLD:
            // Cohort-specific calibration failure is also a blocker;
            // OPE on a regime trained on miscalibrated importance
            // weights produces misleading equity assessments.
            log_calibration_failure_cohort(axis, axis_results)
            RAISE BehaviorPolicyCohortCalibrationFailure

    // Step 2D: persist the behavior-policy model. Version-tagged so
    // OPE results trace to the specific behavior-policy model used.
    behavior_policy_version = next_behavior_policy_version(regime.regime_id)
    write_pickle(behavior_policy_model,
                  "s3://dtr-behavior-policy/" + regime.regime_id +
                  "/" + behavior_policy_version + "/model.pkl")

    RETURN { behavior_policy_model: behavior_policy_model,
             behavior_policy_version: behavior_policy_version,
             calibration_results: calibration_results }
```

**Step 3: Train the regime with multiple methods, with sequential target trial emulation as the protocol.** Method diversity is the discipline; using only one estimator and shipping it produces a regime that has not been cross-validated against the alternative methodological choices. Skip the multi-method approach and the resulting regime is no more reliable than a single-method ML model.

```
FUNCTION train_regime(trajectories, behavior_policy, regime):
    candidate_regimes = []

    // Step 3A: target trial emulation specification. The hypothetical
    // sequential trial protocol must be specified before training
    // begins: eligibility, treatment strategies under comparison,
    // outcome definition, censoring, follow-up. The protocol is
    // documented in the regime catalog so the OPE results can be
    // interpreted against an explicit hypothetical experiment.
    protocol = build_sequential_target_trial_protocol(regime,
                                                       trajectories)
    write_json(protocol,
                "s3://dtr-protocols/" + regime.regime_id +
                "/protocol_v" + protocol.version + ".json")

    // Step 3B: Q-learning with backward induction. The workhorse
    // method.
    q_model = train_q_learning(
        trajectories,
        regime = regime,
        protocol = protocol,
        function_class = regime.q_function_class,
            // typical: gradient-boosted trees or a small neural
            // network depending on state dimensionality
        backward_induction = true)
    candidate_regimes.append({
        method: "q_learning",
        model: q_model,
        version: next_model_version(regime.regime_id, "q_learning")
    })

    // Step 3C: offline RL where the action space is large or the
    // state representation is high-dimensional. Conservative Q-
    // Learning (CQL) and Implicit Q-Learning (IQL) are typical
    // choices because they constrain the learned policy to stay
    // close to the behavior policy, which limits the extrapolation
    // problem.
    IF regime.use_offline_rl:
        offline_rl_model = train_offline_rl(
            trajectories,
            regime = regime,
            protocol = protocol,
            algorithm = regime.offline_rl_algorithm,
                // CQL, IQL, BCQ, or similar
            behavior_constraint = regime.behavior_constraint_strength)
        candidate_regimes.append({
            method: regime.offline_rl_algorithm,
            model: offline_rl_model,
            version: next_model_version(regime.regime_id,
                                          regime.offline_rl_algorithm)
        })

    // Step 3D: A-learning or outcome-weighted learning as
    // cross-validation. Different bias-variance tradeoffs from
    // Q-learning; agreement among methods is the robustness signal.
    IF regime.use_a_learning:
        a_learning_model = train_a_learning(
            trajectories,
            regime = regime,
            protocol = protocol)
        candidate_regimes.append({
            method: "a_learning",
            model: a_learning_model,
            version: next_model_version(regime.regime_id, "a_learning")
        })

    // Step 3E: marginal structural model with IPTW for population-
    // level policy value comparison. Used as a complement, not as
    // the primary estimator, because MSMs estimate the value of a
    // candidate regime rather than the optimal regime directly.
    IF regime.use_msm:
        msm_results = estimate_msm_policy_values(
            trajectories,
            behavior_policy = behavior_policy,
            candidate_policies = [c.model.policy for c in candidate_regimes],
            regime = regime)
        write_json(msm_results,
                    "s3://dtr-msm/" + regime.regime_id + "/msm_v" +
                    next_msm_version(regime.regime_id) + ".json")

    // Step 3F: register all candidate regimes in the SageMaker Model
    // Registry. Each candidate carries its method, training data
    // window, behavior-policy version, and protocol version.
    FOR each candidate in candidate_regimes:
        SageMaker.ModelRegistry.RegisterModel(
            ModelPackageGroupName = regime.regime_id,
            ModelData = candidate.model.s3_uri,
            ModelMetadata = {
                method: candidate.method,
                version: candidate.version,
                training_window: refresh_window,
                behavior_policy_version: behavior_policy.version,
                protocol_version: protocol.version,
                governance_status: "pending_ope"
            })

    RETURN candidate_regimes
```

**Step 4: Run off-policy evaluation with multiple estimators and sensitivity analysis, including cohort-stratified results.** OPE is the gate that determines whether a candidate regime can be deployed. Skip the multi-estimator approach and you have a single point estimate without the cross-validation discipline; skip the sensitivity analysis and you have not asked how robust the conclusion is to the unmeasured confounding the data cannot rule out; skip the cohort stratification and you can ship a regime whose overall value is high while its value for some cohorts is much lower or much more uncertain. Each omission produces a regime whose deployment risk is higher than the OPE results suggest.

```
FUNCTION run_ope(candidate_regimes, behavior_policy, trajectories, regime):
    ope_results = []

    FOR each candidate in candidate_regimes:
        // Step 4A: doubly-robust off-policy evaluation. The workhorse
        // estimator. Combines importance sampling weights from the
        // behavior policy with a fitted Q model for the candidate
        // policy. Consistent if either the IS weights or the Q model
        // is correctly specified.
        dr_value, dr_ci = doubly_robust_ope(
            trajectories,
            target_policy = candidate.model.policy,
            behavior_policy = behavior_policy.model,
            q_model = fit_q_for_target(trajectories, candidate.model.policy),
            bootstrap_iterations = OPE_BOOTSTRAP_ITERATIONS)

        // Step 4B: importance sampling (self-normalized) for
        // comparison. Higher variance than DR but less reliant on
        // the Q model's specification.
        is_value, is_ci = self_normalized_importance_sampling(
            trajectories,
            target_policy = candidate.model.policy,
            behavior_policy = behavior_policy.model,
            bootstrap_iterations = OPE_BOOTSTRAP_ITERATIONS)

        // Step 4C: fitted Q evaluation. Lower variance than IS, more
        // reliant on the Q model's specification.
        fqe_value, fqe_ci = fitted_q_evaluation(
            trajectories,
            target_policy = candidate.model.policy,
            q_model_fitter = OPE_FQE_MODEL_FITTER)

        // Step 4D: cohort-stratified OPE. The same estimators applied
        // to within-cohort subsets. The cohort axes are the same
        // ones used throughout Chapter 4 (race, ethnicity, language,
        // age, comorbidity tier, geographic region) plus regime-
        // specific cohorts (e.g., diabetes-only versus diabetes-plus-
        // CKD for a diabetes regime).
        cohort_results = []
        FOR each axis in COHORT_AXES:
            FOR each cohort_value in get_cohort_values(axis):
                cohort_trajectories = filter_to_cohort(trajectories,
                                                         axis, cohort_value)
                IF len(cohort_trajectories) < MIN_COHORT_SAMPLE:
                    // Insufficient data is itself an equity signal:
                    // a cohort that is systematically underrepresented
                    // cannot be evaluated and should be flagged
                    // rather than silently dropped.
                    cohort_results.append({
                        axis: axis,
                        cohort_value: cohort_value,
                        sample_size: len(cohort_trajectories),
                        evaluable: false,
                        flag: "insufficient_data"
                    })
                    CONTINUE
                cohort_dr_value, cohort_dr_ci = doubly_robust_ope(
                    cohort_trajectories,
                    target_policy = candidate.model.policy,
                    behavior_policy = behavior_policy.model,
                    q_model = fit_q_for_target(cohort_trajectories,
                                                  candidate.model.policy),
                    bootstrap_iterations = OPE_BOOTSTRAP_ITERATIONS)
                cohort_results.append({
                    axis: axis,
                    cohort_value: cohort_value,
                    sample_size: len(cohort_trajectories),
                    dr_value: cohort_dr_value,
                    dr_ci: cohort_dr_ci,
                    evaluable: true
                })

        // Step 4E: sensitivity analysis. Bound the impact of
        // unmeasured confounding on the OPE conclusion. E-value
        // and Rosenbaum bounds are typical; simulation-based
        // perturbation of the propensity model is more flexible.
        sensitivity_results = run_sensitivity_analysis(
            trajectories,
            target_policy = candidate.model.policy,
            behavior_policy = behavior_policy.model,
            method = "e_value_and_simulation")

        ope_results.append({
            candidate_method: candidate.method,
            candidate_version: candidate.version,
            dr_value: dr_value, dr_ci: dr_ci,
            is_value: is_value, is_ci: is_ci,
            fqe_value: fqe_value, fqe_ci: fqe_ci,
            method_agreement_score: compute_agreement([dr_value, is_value, fqe_value]),
            cohort_results: cohort_results,
            sensitivity_results: sensitivity_results,
            ope_run_at: current UTC timestamp
        })

    // Step 4F: persist OPE results for governance review.
    write_json(ope_results,
                "s3://dtr-ope/" + regime.regime_id + "/ope_run_" +
                next_ope_run_id(regime.regime_id) + ".json")

    // Step 4G: build the governance package. The committee reviews
    // the OPE results, the cohort-stratified results, the sensitivity
    // analysis, and the calibration of the behavior policy before
    // approving any candidate for deployment. The package is the
    // artifact the committee approves; the committee's decision is
    // recorded with the package.
    governance_package = build_governance_package(
        regime = regime,
        candidate_regimes = candidate_regimes,
        ope_results = ope_results,
        behavior_policy = behavior_policy,
        protocol = protocol)
    write_json(governance_package,
                "s3://dtr-governance/" + regime.regime_id +
                "/package_" + governance_package.package_id + ".json")

    RETURN ope_results
```

**Step 5: Serve recommendations at decision points with eligibility, OOD detection, similar-trajectory retrieval, and validator-protected narrative generation.** The serving path is where the regime meets the patient. Skip the eligibility check and the regime is applied to patients it was not designed for; skip the OOD check and recommendations become extrapolation rather than interpolation; skip the similar-trajectory retrieval and clinicians have no concrete evidence behind the recommendation; skip the validator and the LLM is allowed to drift from the structured recommendation into territory the regime does not support.

```
FUNCTION serve_recommendation(patient_id, regime_id, decision_point_id):
    regime = DynamoDB.GetItem("regime-catalog", regime_id, latest_version = true)

    // Step 5A: build the patient's current state.
    state = build_state_at_time(patient_id, current UTC timestamp)
    trajectory_metadata = DynamoDB.GetItem("trajectory-metadata",
                                              patient_id, regime_id)

    // Step 5B: identity-boundary checks. The recommendation API is
    // called by an authenticated EHR session. Validate that the
    // calling clinician has a treatment relationship to the patient,
    // that the patient is an active member of the regime's eligible
    // population, and that the decision_point_id is consistent with
    // the patient's trajectory state.
    treatment_relationship_check(calling_clinician_id, patient_id)
    consistency_check(decision_point_id, trajectory_metadata)
    // TODO (TechWriter): Expert review S1 (HIGH). Specify the
    // identity-boundary check policy and rejection semantics at the
    // chapter pattern level: failure modes (clinician_not_authorized,
    // patient_not_active_in_regime, decision_point_inconsistent),
    // metric emission on each violation, and the served_to_clinician_id
    // capture that record_action_taken needs. Mirror 4.4-4.9 chapter
    // pattern; sharper here because trajectory contamination is a
    // propagating harm into the next training cycle.

    // Step 5C: eligibility check. The regime's eligibility predicates
    // are evaluated against the current state. Patients who fail
    // eligibility receive an explicit "not eligible" response with
    // the failing predicate identified, not silently no recommendation.
    eligibility = evaluate_eligibility(state, regime.eligibility_predicates)
    IF NOT eligibility.eligible:
        recommendation_record = {
            recommendation_id: new UUID,
            patient_id: patient_id,
            regime_id: regime_id,
            regime_version: regime.version,
            decision_point_id: decision_point_id,
            outcome: "not_eligible",
            failing_predicate: eligibility.failing_predicate,
            generated_at: current UTC timestamp
        }
        DynamoDB.PutItem("recommendation-records", recommendation_record)
        Kinesis.PutRecord(stream = "dtr-events", record = {
            event_type: "recommendation_not_eligible",
            patient_id: patient_id,
            regime_id: regime_id,
            decision_point_id: decision_point_id,
            timestamp: current UTC timestamp
        })
        RETURN recommendation_record

    // Step 5D: out-of-distribution check. Does the patient's state
    // fall within the support of the training trajectories? Several
    // signals: density estimation in the state space, propensity
    // score near 0 or 1 for any action, large extrapolation distance
    // by k-NN.
    ood_check = run_ood_check(state, regime.ood_detector,
                                regime.ood_thresholds)
    // The OOD flag is information, not necessarily a stop. The
    // regime risk tier determines whether OOD-flagged patients still
    // receive a recommendation, receive one with explicit warnings,
    // or are blocked.
    // TODO (TechWriter): Expert review A3 (HIGH). Specify the OOD
    // severity bands (NONE/LOW/MODERATE/HIGH thresholds), the routing
    // policy by regime risk tier (which severity bands serve, warn,
    // or suppress at each tier), the override semantics (whether a
    // clinician can request "show recommendation anyway" and how that
    // event is captured), and the suppressed-for-OOD outcome on the
    // recommendation record so the audit trail captures the
    // suppression. Without these the clinical-safety posture is
    // implementation-defined.

    // Step 5E: invoke the regime's policy.
    endpoint_response = SageMaker.InvokeEndpoint(
        EndpointName = regime.serving_endpoint,
        Body = serialize({
            state: state,
            regime_id: regime_id,
            regime_version: regime.version
        }))
    policy_output = parse(endpoint_response)
    // policy_output schema: {
    //   recommended_action_id, recommended_action_value,
    //   recommended_action_ci_low, recommended_action_ci_high,
    //   alternative_actions: [{ action_id, value, ci_low, ci_high }, ...],
    //   feature_contributions: [{ feature, contribution }, ...],
    //   regime_version, behavior_policy_version,
    //   evaluation_method
    // }

    // Step 5F: similar-trajectory retrieval. A small cohort (typically
    // 5 to 20) of historical trajectories most similar to the
    // patient's current state, with their actions and outcomes. The
    // similarity metric is regime-defined; a learned embedding from
    // the regime model is typical. The retrieval is privacy-aware
    // (de-identified, k-anonymity-checked, and aggregate-only when
    // the cohort is too small to share individual examples without
    // re-identification risk).
    similar_trajectories = retrieve_similar_trajectories(
        state, regime,
        n = SIMILAR_TRAJECTORY_COUNT,
        privacy_check = true)

    // Step 5G: build the recommendation record.
    recommendation_record = {
        recommendation_id: new UUID,
        patient_id: patient_id,
        regime_id: regime_id,
        regime_version: regime.version,
        decision_point_id: decision_point_id,
        outcome: "served",
        state: state,
        eligibility: eligibility,
        ood_flag: ood_check.flagged,
        ood_detail: ood_check.detail,
        recommended_action: policy_output.recommended_action_id,
        recommended_action_value: policy_output.recommended_action_value,
        recommended_action_ci: [policy_output.recommended_action_ci_low,
                                  policy_output.recommended_action_ci_high],
        alternative_actions: policy_output.alternative_actions,
        feature_contributions: policy_output.feature_contributions,
        similar_trajectories: similar_trajectories,
        guideline_references: lookup_guideline_references(regime,
                                                           policy_output.recommended_action_id),
        contraindication_checks: run_contraindication_checks(state,
                                                              policy_output.recommended_action_id,
                                                              policy_output.alternative_actions),
        generated_at: current UTC timestamp
    }

    // Step 5H: generate the clinician-facing narrative with validator
    // enforcement. Same pattern as Recipes 4.5 through 4.9; the
    // regime-specific prohibited-language patterns are stricter
    // (no policy-as-directive framing, no recommendation language
    // that elides the alternatives, no probabilistic claims framed
    // as guarantees, explicit override-encouragement framing).
    narrative = generate_clinician_narrative(recommendation_record, regime)
        // The validator is layered the same way as in Recipe 4.9:
        // schema and length, fact grounding (every clinical claim
        // traces to the recommendation_record or the regime catalog),
        // prohibited-language patterns, required content (uncertainty
        // disclosure, regime version, override-encouragement,
        // similar-trajectory reference). Failed validations
        // regenerate or fall back to a templated narrative.
    recommendation_record.clinician_narrative = narrative

    // Step 5I: persist and emit.
    DynamoDB.PutItem("recommendation-records", recommendation_record)
    write_json(recommendation_record,
                "s3://dtr-recommendation-archives/" +
                recommendation_record.recommendation_id + ".json")
    Kinesis.PutRecord(stream = "dtr-events", record = {
        event_type: "recommendation_generated",
        patient_id: patient_id,
        regime_id: regime_id,
        regime_version: regime.version,
        decision_point_id: decision_point_id,
        recommended_action: policy_output.recommended_action_id,
        ood_flagged: ood_check.flagged,
        timestamp: current UTC timestamp
    })

    RETURN recommendation_record
```

**Step 6: Capture the clinician's eventual action, the patient outcomes, and run the surveillance pipeline.** The feedback loop is what turns the regime from a static artifact into a living one. Skip the action-taken capture and you cannot tell whether clinicians follow the recommendations; skip the outcome surveillance and you cannot tell whether the regime is performing as the OPE estimated; skip the cohort-stratified surveillance and you cannot tell whether equity disparities have emerged in production. Each omission converts the regime back into a research artifact.

```
FUNCTION record_action_taken(recommendation_id, action_taken_payload):
    // action_taken_payload includes:
    //   - action_id (the action the clinician picked, which may be
    //     the regime's recommendation, an alternative, or out-of-
    //     catalog)
    //   - clinician_id (from the authenticated session)
    //   - rationale (free text or structured, especially when
    //     overriding the recommendation)
    //   - patient_share_decision (whether the clinician shared the
    //     recommendation with the patient and what level of detail)
    rec = DynamoDB.GetItem("recommendation-records", recommendation_id)

    // Identity-boundary check: the clinician_id must match the
    // session that received the recommendation; mismatch is logged
    // and rejected.
    IF action_taken_payload.clinician_id != rec.served_to_clinician_id:
        log_security_violation(...)
        REJECT
    // TODO (TechWriter): Expert review S1 (HIGH). Specify the
    // rejection semantics in chapter pattern style: validate that
    // action_id is in the recommendation's known action set
    // (recommended_action plus alternatives, or explicit out-of-
    // catalog), enforce idempotency on replay (rec.action_taken
    // already set means treat as replay rather than double-mutate),
    // and emit metric action_taken_identity_mismatch on rejection.
    // Trajectory poisoning from a misrouted action-taken event
    // propagates into the next training cycle; the boundary must
    // hold.

    DynamoDB.UpdateItem("recommendation-records", recommendation_id, {
        action_taken: action_taken_payload.action_id,
        action_taken_kind: classify_action(action_taken_payload.action_id, rec),
            // returns one of: "followed_recommendation",
            // "chose_alternative", "out_of_catalog"
        action_rationale: action_taken_payload.rationale,
        patient_share_decision: action_taken_payload.patient_share_decision,
        action_recorded_at: current UTC timestamp
    })

    // Append to the patient's trajectory record. This is the same
    // trajectory record that powers training; the in-production
    // trajectories continuously feed the next training cycle.
    append_to_trajectory(rec.patient_id, rec.regime_id, {
        decision_point_id: rec.decision_point_id,
        timestamp: current UTC timestamp,
        state: rec.state,
        action: action_taken_payload.action_id,
        recommendation_id: recommendation_id,
        followed_regime: classify_action(...) == "followed_recommendation"
    })

    Kinesis.PutRecord(stream = "dtr-events", record = {
        event_type: "action_taken",
        patient_id: rec.patient_id,
        regime_id: rec.regime_id,
        recommendation_id: recommendation_id,
        followed_regime: classify_action(...) == "followed_recommendation",
        timestamp: current UTC timestamp
    })


FUNCTION run_surveillance(regime_id, surveillance_window):
    regime = DynamoDB.GetItem("regime-catalog", regime_id, latest_version = true)

    // Step 6A: regime adherence tracking. How often did clinicians
    // follow the regime's recommendation, by clinical area, by
    // patient cohort, by recommendation strength. Low adherence
    // to high-confidence recommendations is a signal of clinician
    // disagreement that merits review.
    adherence_metrics = compute_adherence_metrics(regime_id, surveillance_window)

    // Step 6B: outcome surveillance. Compare observed outcomes
    // against the OPE-estimated regime value. Calibration drift
    // (predicted versus realized outcomes diverging) is the signal
    // that the regime is no longer optimal for the current
    // population.
    outcome_metrics = compute_outcome_metrics(regime_id, surveillance_window)
    drift_results = detect_calibration_drift(regime_id, surveillance_window,
                                              ope_baseline = lookup_ope_baseline(regime_id))
    // TODO (TechWriter): Expert review A4 (HIGH). Specify the
    // prediction-versus-outcome pairing: identify recommendations
    // whose outcome window has closed within the surveillance
    // window (regime.outcome_window_days), join action-taken events
    // to observed outcomes computed against the regime's reward
    // function (matching weights), apply IPCW for patients censored
    // before the outcome window closed, and compute per-cohort
    // residuals. Drift severity = |mean residual| / OPE baseline CI
    // half-width. The implementation must avoid the failure mode of
    // averaging predicted Q-values across recommendations and
    // calling that "observed reward"; that signal detects
    // population-mix drift, not calibration drift, and the
    // RETRAINING_TRIGGER_THRESHOLD fires on the wrong axis.

    // Step 6C: cohort-stratified surveillance. Outcome trajectories
    // by cohort, regime adherence by cohort, OOD-flag rates by
    // cohort. Disparities trigger committee review.
    cohort_metrics = compute_cohort_stratified_metrics(regime_id, surveillance_window,
                                                        cohort_axes = COHORT_AXES)
    FOR each axis, axis_metrics in cohort_metrics:
        IF axis_metrics.disparity >= COHORT_DISPARITY_ALERT_THRESHOLD:
            DynamoDB.PutItem("surveillance-alerts", {
                alert_id: new UUID,
                alert_type: "regime_cohort_disparity",
                regime_id: regime_id,
                axis: axis,
                axis_metrics: axis_metrics,
                triggered_at: current UTC timestamp,
                review_status: "pending"
            })
    // TODO (TechWriter): Expert review A1 (HIGH). Specify the
    // cohort-disparity thresholds (REGIME_VALUE_DISPARITY_THRESHOLD,
    // REGIME_ADHERENCE_DISPARITY_THRESHOLD, OOD_RATE_DISPARITY_THRESHOLD,
    // OUTCOME_TRAJECTORY_DISPARITY_THRESHOLD) and the per-axis-per-
    // metric override mechanism. Specify how each disparity is
    // computed (e.g., regime value disparity = ratio of mean DR-OPE
    // value worst-cohort vs best-cohort; adherence disparity =
    // difference in follow-recommendation rate by recommendation
    // strength tier). Specify MIN_SURVEILLANCE_COHORT_SAMPLE and
    // chronic-suppression-as-fairness-signal pattern: a cohort whose
    // sample size is structurally low across windows is itself an
    // under-representation alert, not silently absorbed into the
    // disparity calculation. Specify the relationship between the
    // OPE-stage MIN_COHORT_SAMPLE and the surveillance-stage minimum.
    // Reference Obermeyer 2019 and the chapter siblings 4.8 A4 / 4.9 A2.

    // Step 6D: drift-driven retraining trigger. If calibration drift
    // exceeds threshold, trigger a retraining cycle ahead of the
    // scheduled cadence. The retraining produces a new candidate
    // regime that goes through OPE before promotion.
    IF drift_results.severity >= RETRAINING_TRIGGER_THRESHOLD:
        EventBridge.PutEvents([{
            source: "dtr-surveillance",
            detail_type: "retraining_triggered",
            detail: { regime_id: regime_id,
                      reason: "calibration_drift",
                      drift_results: drift_results }
        }])

    // Step 6E: persist surveillance metrics for the dashboards.
    DynamoDB.PutItem("surveillance-metrics", {
        regime_id: regime_id,
        surveillance_window: surveillance_window,
        adherence_metrics: adherence_metrics,
        outcome_metrics: outcome_metrics,
        drift_results: drift_results,
        cohort_metrics: cohort_metrics,
        run_at: current UTC timestamp
    })
    write_json({
        regime_id: regime_id,
        surveillance_window: surveillance_window,
        adherence_metrics: adherence_metrics,
        outcome_metrics: outcome_metrics,
        drift_results: drift_results,
        cohort_metrics: cohort_metrics
    }, "s3://dtr-surveillance/" + regime_id + "/window_" +
        surveillance_window.id + ".json")
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter04.10-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample recommendation record (truncated for readability):**

```json
{
  "recommendation_id": "rec-2026-04-22-pat-009315-dp-014",
  "patient_id": "pat-009315",
  "regime_id": "diabetes_ckd_stepwise_v3",
  "regime_version": "3.2.1",
  "decision_point_id": "dp-2026-04-22-pat-009315-014",
  "outcome": "served",
  "state": {
    "current_a1c": 8.4,
    "current_egfr": 41,
    "current_acr": 78,
    "current_systolic_bp": 134,
    "current_medications": ["metformin_2000_mg",
                              "lisinopril_20_mg",
                              "hydrochlorothiazide_25_mg",
                              "semaglutide_1_mg_weekly"],
    "decision_point_index": 14,
    "time_since_last_decision_point_days": 91,
    "prior_actions_under_regime": ["add_glp1", "increase_glp1",
                                     "no_change", "no_change"],
    "comorbidities": ["t2dm", "ckd_3b", "htn"],
    "comorbidity_tier": 3,
    "age_band": "50_to_59",
    "polypharmacy_count": 7
  },
  "eligibility": {
    "eligible": true,
    "predicate_evaluations": {
      "active_t2dm": true,
      "egfr_above_30": true,
      "no_active_pregnancy": true,
      "regime_consent_on_file": true
    }
  },
  "ood_flag": false,
  "ood_detail": {
    "density_score": 0.83,
    "propensity_min": 0.06,
    "propensity_max": 0.91,
    "knn_extrapolation_distance": 1.4
  },
  "recommended_action": "add_sglt2_dapagliflozin_10_mg_daily",
  "recommended_action_value": 0.78,
  "recommended_action_ci": [0.71, 0.84],
  "alternative_actions": [
    {"action_id": "increase_semaglutide_to_2_mg_weekly",
      "value": 0.74,
      "ci": [0.66, 0.81]},
    {"action_id": "add_basal_insulin_glargine",
      "value": 0.61,
      "ci": [0.52, 0.69]},
    {"action_id": "no_change_with_lifestyle_intensification",
      "value": 0.58,
      "ci": [0.49, 0.66]},
    {"action_id": "add_dpp4_sitagliptin_100_mg_daily",
      "value": 0.55,
      "ci": [0.47, 0.63]}
  ],
  "feature_contributions": [
    {"feature": "current_egfr", "contribution": 0.18,
      "direction": "favors_sglt2_for_renal_protection"},
    {"feature": "current_acr", "contribution": 0.12,
      "direction": "favors_sglt2_for_albuminuria"},
    {"feature": "comorbidity_tier", "contribution": 0.07,
      "direction": "favors_sglt2_for_cv_protection"},
    {"feature": "current_a1c", "contribution": 0.05,
      "direction": "modest_benefit_either_way"},
    {"feature": "polypharmacy_count", "contribution": -0.04,
      "direction": "modest_caution_with_more_medications"}
  ],
  "similar_trajectories": [
    {"trajectory_id": "anonymized_001",
      "starting_state_summary": "a1c_8.5_egfr_43_glp1_on_board",
      "action_taken": "add_sglt2",
      "12_month_outcome": "a1c_7.4_egfr_42_no_aki",
      "discontinuation": false,
      "k_anonymity_passed": true},
    {"trajectory_id": "anonymized_002",
      "starting_state_summary": "a1c_8.6_egfr_39_glp1_on_board",
      "action_taken": "add_sglt2",
      "12_month_outcome": "a1c_7.6_egfr_40_no_aki",
      "discontinuation": false,
      "k_anonymity_passed": true},
    {"trajectory_id": "anonymized_003",
      "starting_state_summary": "a1c_8.3_egfr_40_glp1_on_board",
      "action_taken": "increase_glp1",
      "12_month_outcome": "a1c_7.8_egfr_38_no_aki",
      "discontinuation": false,
      "k_anonymity_passed": true}
  ],
  "guideline_references": [
    {"source": "ADA_Standards_of_Care_2026",
      "section": "diabetes_with_ckd",
      "recommendation_text": "in_t2dm_with_egfr_under_60_or_albuminuria_prefer_sglt2_or_glp1_with_proven_kidney_benefit"},
    {"source": "KDIGO_2022_diabetes_in_ckd",
      "section": "first_line_after_metformin",
      "recommendation_text": "sglt2_inhibitor_with_proven_kidney_outcome_benefit_strongly_recommended"}
  ],
  "contraindication_checks": {
    "drug_drug": "no_severe_interactions",
    "drug_disease": "no_active_drug_disease_contraindications",
    "drug_allergy": "no_known_allergies",
    "renal_dosing": "dapagliflozin_appropriate_at_egfr_41"
  },
  "clinician_narrative": {
    "headline": "For this patient, the regime suggests adding an SGLT2 inhibitor (dapagliflozin 10 mg daily). The estimated benefit is modestly higher than increasing the GLP-1 dose. Confidence intervals overlap; the clinician's judgment should incorporate factors not in the model.",
    "rationale": "The state-level features driving this recommendation are eGFR 41 and ACR 78 (both favor SGLT2 for renal protection), current cardiovascular risk profile, and the patient already being on metformin and a GLP-1. Three similar historical trajectories with comparable starting states all received SGLT2 with stable eGFR and improved A1c at twelve months. Two alternative actions have overlapping confidence intervals; this regime is not strongly discriminating between SGLT2 addition and GLP-1 dose increase.",
    "uncertainty": "The OPE confidence interval is [0.71, 0.84]. Cohort-stratified estimates for this patient's combined cohort (T2DM with CKD 3b on GLP-1) are consistent with the overall estimate. The OOD score does not flag this patient as out-of-distribution.",
    "alternatives_callout": "Increasing the GLP-1 dose to 2 mg weekly has an estimated value of 0.74 [0.66, 0.81]; the difference from the recommended action is small relative to the confidence intervals. Either action is defensible from the regime's perspective; the choice may reasonably depend on patient preferences (oral SGLT2 versus injectable GLP-1 dose increase), formulary status, and expected tolerability.",
    "regime_version_disclosure": "Regime version 3.2.1, trained on data through 2026-Q1, last governance approval 2026-03-15.",
    "override_encouragement": "If clinical judgment or patient preference points to a different action, document the rationale; the regime is decision support, not a directive."
  },
  "generated_at": "2026-04-22T15:08:42Z"
}
```

**Sample governance package OPE summary (truncated):**

```json
{
  "regime_id": "diabetes_ckd_stepwise_v3",
  "candidate_version": "3.3.0",
  "training_window": "2022-01-01_to_2026-01-31",
  "behavior_policy_version": "diabetes_ckd_bp_v7",
  "protocol_version": "2.1",
  "sample_size": 47832,
  "decision_points_per_trajectory_median": 8,
  "ope_results": {
    "doubly_robust": {"value": 0.79, "ci": [0.74, 0.83]},
    "self_normalized_is": {"value": 0.77, "ci": [0.69, 0.85]},
    "fitted_q_evaluation": {"value": 0.80, "ci": [0.76, 0.83]},
    "method_agreement": "high",
    "current_regime_value": {"value": 0.71, "ci": [0.66, 0.75]},
    "value_lift": "candidate exceeds current regime CI lower bound; promotion candidate"
  },
  "cohort_results": [
    {"axis": "race_ethnicity", "cohort": "white_non_hispanic",
      "sample_size": 28115, "dr_value": 0.80, "dr_ci": [0.74, 0.85]},
    {"axis": "race_ethnicity", "cohort": "black_non_hispanic",
      "sample_size": 9842, "dr_value": 0.74, "dr_ci": [0.67, 0.81]},
    {"axis": "race_ethnicity", "cohort": "hispanic",
      "sample_size": 7251, "dr_value": 0.76, "dr_ci": [0.69, 0.83]},
    {"axis": "race_ethnicity", "cohort": "asian",
      "sample_size": 1834, "dr_value": 0.78, "dr_ci": [0.66, 0.88]},
    {"axis": "race_ethnicity", "cohort": "other_or_unknown",
      "sample_size": 790, "dr_value": null, "dr_ci": null,
      "evaluable": false, "flag": "insufficient_data"},
    {"axis": "language", "cohort": "english", "sample_size": 41512,
      "dr_value": 0.80, "dr_ci": [0.75, 0.84]},
    {"axis": "language", "cohort": "spanish", "sample_size": 4318,
      "dr_value": 0.74, "dr_ci": [0.66, 0.82]},
    {"axis": "language", "cohort": "other", "sample_size": 2002,
      "dr_value": 0.71, "dr_ci": [0.59, 0.81], "flag": "wide_ci"}
  ],
  "sensitivity_analysis": {
    "e_value_for_main_effect": 1.62,
    "e_value_for_lower_ci": 1.34,
    "interpretation": "moderate_robustness_to_unmeasured_confounding"
  },
  "governance_recommendation": "approve_for_pilot_deployment_with_cohort_specific_monitoring",
  "blocking_concerns": [],
  "non_blocking_concerns": [
    "other_or_unknown_race_ethnicity_cohort_insufficient_data",
    "other_language_cohort_wide_ci"
  ]
}
```

**Performance benchmarks (illustrative, your mileage varies):**

| Metric | Status quo (clinician unaided) | Recipe pipeline |
|--------|---------------------------------|-----------------|
| Regime-coverage of multi-decision chronic-disease care | <5% (mostly ad-hoc) | 70-90% in supported regimes |
| Per-recommendation evidence depth (similar-trajectory N) | 0 (none surfaced) | 5-20 anonymized trajectories |
| Per-recommendation uncertainty quantification | not surfaced | 95% CI on every value |
| OPE-validated regime value lift over status quo | not measured | 5-15% on the chosen reward |
| Clinician follow-rate of high-confidence recommendations | n/a | 60-80% |
| Clinician follow-rate of borderline recommendations | n/a | 40-55% (which is appropriate; low confidence should not auto-follow) |
| Cohort regime-value parity (worst cohort vs best cohort) | unknown | 0.85-0.95 after cohort-stratified retraining |
| Validator first-attempt pass rate (clinician narrative) | n/a | 88-95% |
| Validator fallback-to-templated rate | n/a | 1-4% |
| End-to-end recommendation latency (95th percentile) | n/a | 1-3 seconds |
| Calibration drift detection time-to-alert | n/a | 30-90 days from drift onset |
| Time from drift alert to retraining completion | n/a | 7-21 days |
| OOD-flag rate (patients outside training distribution) | not measured | 3-8% in supported cohorts |

<!-- TODO: the benchmarks above are illustrative; replace with measured results from your deployment. Be wary of vendor-published claims about "AI-driven sequential decision support"; the headline metric (recommendations per minute or accuracy versus a single-decision benchmark) is the wrong metric, and the substantive metrics (OPE confidence, cohort fairness, calibration drift, override patterns over time) are rarely reported. -->

**Where it struggles:**

- **Sparse decision points or short trajectories.** Some regimes' clinical areas have decision points spaced months apart with only a handful per patient. Q-learning and offline RL benefit from longer trajectories and denser decision points; sparse trajectories produce wider OPE confidence intervals and less stable policies. Surface this as part of the OPE result; do not promote regimes whose CIs do not exclude the current regime's value.
- **Action catalog gaps.** The action catalog is a finite list; clinicians regularly choose actions that are not in the catalog (a non-formulary medication, an unusual dose, a combination not previously considered). High out-of-catalog rates degrade the regime's coverage and produce trajectories that train on incomplete history. Surveillance should track out-of-catalog rate per cohort; persistent gaps should drive catalog expansion.
- **Behavior-policy estimation in low-decision-density cohorts.** A cohort where every patient gets the same action has a degenerate behavior policy (probability 1 for one action, 0 for others), which produces infinite or zero importance weights. Cohorts with very homogeneous historical practice cannot be evaluated with importance-sampling-based OPE; alternative methods (FQE, model-based simulation) are needed and produce wider intervals.
- **Long horizons.** Off-policy evaluation variance grows with horizon length. Multi-year chronic-disease horizons with annual or semiannual decision points produce CIs wide enough that the OPE often cannot discriminate between candidate regimes. Either shorten the evaluation horizon (with explicit acknowledgement that the policy's long-term value is uncertain), or invest in advanced techniques (per-decision IS, model-based OPE) that mitigate the variance growth.
- **Clinician disengagement.** Clinicians who do not understand the regime's logic, the OPE confidence intervals, or the OOD flag will skim the narrative and either reflexively follow or reflexively ignore the recommendation. Both modes are failures of decision support. Invest in clinician education before launch and in continuous engagement after; track follow-rates by clinician and surface disengagement patterns to clinical leadership.
- **Calibration drift in evolving practice.** A regime trained on 2022-2025 data optimizes for the prescribing patterns and patient mix of that era. As newer drug classes enter standard practice, as new outcomes data updates the guidelines, and as the patient mix shifts, the regime's recommendations age. Calibration drift detection should flag this within months; the retraining cadence should respond. The pattern that fails is treating the regime as static; it ages out and starts producing recommendations the current literature would not endorse.
- **Cohort-stratified OPE with insufficient data.** Smaller cohorts (less-represented racial groups, less-represented languages, rare comorbidity profiles) produce OPE results with intervals so wide they are not actionable. The honest response is "we cannot tell whether the regime works for this cohort with the data we have"; the dishonest response is to report the point estimate as if it were trustworthy. The architecture surfaces the insufficient-data flag explicitly; the governance committee decides whether to deploy the regime to that cohort with explicit warnings, restrict deployment to cohorts with adequate data, or invest in cohort-specific data acquisition.
- **Reward-function gaming and unintended optimization.** A reward function that weights A1c reduction heavily may push the regime toward aggressive medication intensification, producing improvements in A1c at the cost of more hypoglycemia, more weight gain, and more medication burden than the intended balance. The reward function is a policy decision that the governance committee must revisit as outcomes accumulate; outcomes that improve the reward but worsen unmeasured aspects of patient experience are a structural feature of any reward-driven system, and the system needs an audit mechanism (PROMs, qualitative feedback, periodic clinical review) for catching them.
- **Patient communication of policy logic.** When the clinician shares the recommendation with the patient, the patient often wants to know "why this and not that?" The patient-facing narrative must convey the path-dependence ("this is the next step given how things have gone") and the uncertainty ("the model is more confident about A than about B for patients in your situation") without crossing into prescriptive language. Patient-facing regime communication is iterative work; the first version is rarely the version that lands.
- **Override pattern interpretation.** Clinicians override recommendations for many reasons: patient preference, formulary issues, supply constraints, unspecified clinical judgment, simple disagreement with the model. Distinguishing "override because the model is right but the patient said no" from "override because the model is wrong for this patient profile" requires structured rationale capture and periodic clinical review of the rationales. Without that discipline, override patterns become noise rather than signal.
- **Regulatory shift mid-deployment.** FDA SaMD policy is evolving. The Predetermined Change Control Plan policy has matured and may continue to mature; state-level regulations are also evolving. A regime that is below the SaMD threshold today may not be below it next year if the policy changes or if the regime's deployment posture (clinician-mediated versus more direct) changes. Maintain the regulatory analysis as an active document, not a one-time deliverable. <!-- TODO: confirm current FDA SaMD framework, the Predetermined Change Control Plan policy, and the 21st Century Cures Act CDS exemption criteria at the time of build. -->

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment needs to close several gaps that are intentionally out of scope for a recipe.

**Methodology validation against randomized-trial benchmarks.** Where SMART-trial data is available (the canonical sequential-randomized-trial design that grounded much of the dynamic-treatment-regime literature), the regime's OPE estimates should be benchmarked against the trial's primary analysis. Closeness to the randomized-trial point estimate, with overlapping confidence intervals, is the signal of methodological validity. The benchmark exercises require a methodologically sophisticated team (biostatistician with sequential-causal-inference experience, ML engineer with offline RL background); plan for at least 1.0 to 2.0 FTE during the methodology-validation phase.

**Behavior policy validation depth.** The behavior policy is a model whose miscalibration silently corrupts every downstream OPE result. Calibration validation is necessary but not sufficient. Sensitivity analysis to behavior-policy misspecification (perturbing the propensity model and observing the OPE result) is a discipline that the methodology-validation phase should establish as ongoing practice, not a one-time check.

**Reward-function governance and revision.** The reward function is the most contested artifact in the catalog. Establish an explicit policy: who can propose a reward change, what evidence is required, how is the proposed change evaluated (parallel-evaluation against the prior reward, surface what changes in the recommended actions), what cohort-specific impact analysis must accompany the proposal, and what review cadence (quarterly, annually) does the governance committee maintain on the reward as outcomes accumulate. Reward-function changes are policy changes; the engineering process should treat them with the seriousness that implies.

**Patient consent posture.** Dynamic treatment regime recommendations use the patient's longitudinal trajectory data, including prior actions, outcomes, and (in many implementations) similar-trajectory cohorts of other patients. The consent framing should make this explicit: "your care recommendations are informed by your own past care and outcomes and by the patterns observed in similar patients' care; we use this information with care and you can opt out." The institution's existing consent infrastructure typically does not have all of these granularities; expect to extend it. Consent revocation requires a defined data-handling pathway: revoking patients' contributions to training data, re-training without their data on the next cycle, removing them from similar-trajectory retrieval pools.

<!-- TODO (TechWriter): Expert review A10 (MEDIUM). Specify the consent-data-flow pattern: explicit consent capture, consent versioning, consent-revocation handling, audit-trail of consent state at the time of regime training and recommendation generation. Add the regime-specific similar-trajectory-pool consent layer (distinct from "use my data to train the regime"): a patient may consent to training but not to having their de-identified trajectory surfaced as a similar-trajectory example to other clinicians for other patients. Mirror the language from 4.5 through 4.9. -->

**Operational privacy in trajectory storage and similar-trajectory retrieval.** The trajectory store is highly sensitive: per-patient sequences of (state, action, reward) tuples encode rich clinical journeys. The similar-trajectory retrieval surface returns information about other patients (de-identified, k-anonymity-checked, but still derived from real PHI). Apply tighter controls than for engagement data: narrower IAM read scopes, separate-table partitioning by sensitivity tier, additional CloudTrail data event capture, and a documented minimum-necessary access policy. The k-anonymity threshold for similar-trajectory retrieval should be regime-specific and revisited as the data accumulates.

<!-- TODO (TechWriter): Expert review S2 (MEDIUM). Replace the string-concatenation recommendation_id, decision_point_id, trajectory_id with opaque, non-reversible identifiers (UUID or HMAC-SHA256 over the composite with a per-environment secret). Trajectory IDs that encode patient identifiers or decision sequences are PHI leakage in URLs, logs, and event payloads; the decision-point index further reveals the patient's place in the regime's horizon, which is itself inferential about chronic-condition duration. Update the Expected Results sample identifiers accordingly. Mirror the language flagged in 4.4 through 4.9. -->

**FDA SaMD framework integration as an ongoing program.** Treat the regulatory analysis as a continuous deliverable. Model risk classification at scoping; predetermined change control plan as part of the initial submission (where SaMD applies); post-deployment surveillance with structured outcome tracking; regulatory legal review at every regime version promotion that includes a substantive change to the action catalog, the reward function, or the deployment posture. The Good Machine Learning Practice principles are a useful checklist; map your operational practices against them and identify the gaps. <!-- TODO: confirm current FDA SaMD framework, the Predetermined Change Control Plan policy, the 21st Century Cures Act CDS exemption criteria, and the Good Machine Learning Practice principles at the time of build. -->

**Idempotency and retry semantics.** Recommendation generation is multi-stage; each stage's outputs are addressed by deterministic keys (recommendation_id, decision_point_id) and writes are conditional, so a Step Functions retry is a no-op rather than a duplicate. SageMaker endpoint invocations should be idempotent at the recommendation_id level. Action-taken events use deterministic event keys for at-most-once trajectory updates. Step Functions Catch should distinguish retryable infrastructure failures from terminal logic failures and route terminal failures to the DLQ.

<!-- TODO (TechWriter): Expert review A11 (MEDIUM). Specify DLQ coverage on all Lambda paths: Step Functions task failures route to a per-stage SQS DLQ keyed on (recommendation_id, stage); Kinesis to state-machine-worker Lambda configures an OnFailure destination; recommendation-generation failures fall back to a "no recommendation available; clinician should proceed with judgment" response rather than a partial or invalid recommendation. The recommendation path must fail safely. Mirror 4.4 through 4.9. -->

**Cross-recipe orchestration with Recipes 4.5 through 4.9.** Dynamic treatment regimes depend on signals from prior Chapter 4 recipes: the per-treatment CATE estimates from 4.8 inform the action-catalog and the similar-trajectory retrieval; the personalized care plan from 4.9 is the broader plan in which the regime's recommendation is one component; the adherence and engagement signals from 4.5 and 4.7 affect the state representation. The integration points must be reliable, idempotent, and consistent. Document the integration patterns and the failure-mode handling.

<!-- TODO (TechWriter): Expert review A7 (MEDIUM). Architect cross-recipe orchestration explicitly: the freshness contract for 4.8 CATE estimates consulted at serving time (e.g., flag estimates older than 30 days on the recommendation record), the conflict-detection and reconciliation policy for 4.10 recommendations that conflict with the patient's active 4.9 care plan (surface the conflict to the clinician; do not silently override either system), and the independent-fetch-with-defaults failure mode for 4.5 and 4.7 signals (missing signals recorded as such rather than failing the recommendation). Reference 4.9 cross-recipe-orchestration framing as the chapter pattern. -->

**Regime-deprecation and patient-impact handling.** When a regime version is deprecated (replaced by a newer version, retired due to drift, withdrawn after surveillance findings), the patients with active recommendations under the old version need clear handling: re-recommend under the new version at the next decision point, surface the change to the clinician with the rationale, and avoid silent regime swaps. The deprecation policy is part of the change control plan and should be reviewed by the governance committee.

<!-- TODO (TechWriter): Expert review A9 (MEDIUM). Architect the deprecation flow explicitly: regime-version continuity in the recommendation record (decision-point N under v3.2.1, decision-point N+1 under v3.3.0 must be visible in the audit trail and in the clinician narrative); version-tagged surveillance partitioning so deprecated-regime outcomes do not silently roll forward into the new regime's surveillance metrics; and the patient-impact-communication pattern when a regime is withdrawn for safety reasons (the institutional analog of FDA-mandated post-market action notifications). Reference 4.9 A9 (clinical-content versioning) for the chapter pattern. -->

**Cost-aware narrative generation.** Bedrock calls per recommendation (one clinician-facing always, one patient-facing when shared) add up at scale. Tiering the model selection (Sonnet for clinician, Haiku for patient where reading-level allows) substantially reduces cost. Caching narrative fragments for repeated content (regime-version-disclosure boilerplate, override-encouragement blocks) reduces token volume. Production deployments should rationalize the narrative-generation topology against actual usage patterns and cost, with the cost monitoring built into the dashboard from day one.

**Operational dashboards and runbooks.** Drift alarms, OOD-rate alarms, and cohort fairness alarms require runbooks that designate the responding teams (clinical leadership, data science, regulatory, operations) and the response protocols. A drift alarm without a runbook is an alarm that gets acknowledged and ignored. The runbooks are operational deliverables, not engineering ones; the regime is in production only when the runbooks exist and the response teams have rehearsed them.

---

## The Honest Take

Dynamic treatment regime recommendation is the recipe in Chapter 4 where the gap between "the system produces recommendations" and "the system produces recommendations that meaningfully shape sequential clinical decisions in a way patients and clinicians trust" is the widest. The methodological literature has been mature for two decades. The applied production work has lagged because the gap is not primarily a methods gap. It is an alignment gap (between what the regime optimizes and what the program actually wants), an engagement gap (between what clinicians need to act on a recommendation and what the system surfaces), an evaluation gap (between what OPE can tell you and what you really want to know about future deployment), and a governance gap (between what the regulators require and what most engineering teams are prepared to deliver). The architecture in this recipe addresses each of these gaps deliberately. Most of the addressing is not AWS-specific. Most of it is methodological discipline applied seriously, governance applied seriously, clinician engagement designed deliberately, and patient communication taken seriously. The cloud infrastructure is comparatively easy.

The trap most specific to this domain is treating the policy estimation as the work. A team that trains an offline RL model, runs a single OPE estimator, gets a value-lift number, and ships will produce a regime that is overconfident on every axis: overconfident on the value (because one OPE estimator can be wrong in a way the agreement among multiple estimators would have caught), overconfident on the cohort generalization (because a single overall OPE result hides the cohort-specific variation), overconfident on the methodological robustness (because the unmeasured-confounding sensitivity analysis was skipped), and overconfident on the deployment posture (because the OOD detection was not built into serving). The discipline is to triangulate. Q-learning plus offline RL plus A-learning. DR-OPE plus IS-OPE plus FQE. Cohort-stratified plus overall. Sensitivity analysis plus point estimates. Each method by itself can mislead; the agreement among methods is the trustworthy signal.

A trap I keep seeing fresh teams fall into: choosing the reward function casually. The reward function is the most consequential decision in the regime catalog. A reward function that combines A1c reduction, hypoglycemia avoidance, weight change, and CKD progression with arbitrary weights produces a policy that optimizes against those weights. The weights encode a clinical-leadership decision about tradeoffs. Picking weights based on engineering convenience or "let's make A1c the primary outcome because it is what the literature reports" produces a policy that recommends actions that the clinical program does not actually want. The fix is to treat reward selection as a clinical-leadership-and-patient-advisory exercise: explicit deliberation about what the program is trying to achieve, what tradeoffs are acceptable, what the patient population values, and how the resulting weights affect the policy. The output is a documented reward function with a stated rationale, parallel-evaluated against alternative weightings to make the implications visible. Then it goes to training. Skipping this step produces regimes that are technically sound and clinically wrong.

Another trap: over-relying on offline reinforcement learning for problems that classical sequential-causal-inference methods would handle better. Offline RL has gotten popular in the last several years and there are now production-grade libraries that make it accessible. The accessibility is a mixed blessing. For problems with curated state representations, modest action spaces, and decades of biostatistical methodology behind them (chronic disease management, line-of-therapy decisions in oncology, treatment selection in depression), Q-learning with regression at each stage is well-understood, validated against the literature, and produces interpretable policies. Offline RL can match it but does not always beat it, and the methodological barrier to validating an offline RL policy is higher. Pick the method that fits the problem. The problems that genuinely need offline RL (high-dimensional state representations, complex action spaces, problems where the function class matters) are real but smaller than the offline RL hype suggests.

The thing that surprises people coming from forward-looking ML backgrounds is the centrality of off-policy evaluation. In supervised ML, you train on training data and evaluate on test data; the train-test split is the discipline. In offline RL and dynamic treatment regime estimation, the test data does not contain trajectories under the policy you want to evaluate, because that policy was not the behavior policy. The OPE machinery is what gives you a test-data-equivalent estimate of the target policy's value. OPE is not a sanity check; it is the load-bearing inference. A team that under-invests in OPE (uses one estimator, skips cohort stratification, omits sensitivity analysis) is shipping policies whose deployment risk they cannot accurately characterize. Plan for the OPE infrastructure to take a substantial fraction of the project's engineering and statistical time.

The thing about LLMs specifically: the four-layer validator from Recipes 4.5 through 4.9 carries forward, with stricter rules. The clinician-facing narrative for a regime recommendation is more dangerous than the clinician-facing narrative for a single-decision treatment-effect estimate, because the narrative has to convey the path-dependence ("this is the next step in a sequence the regime is suggesting") without crossing into prescriptive language ("the regime recommends this and you should follow it"). The line is "the regime suggests, the clinician decides," and the validator should enforce that line aggressively. Patient-facing narratives are even harder; explaining a policy to a patient without inducing either learned helplessness ("the algorithm picked, just do it") or rejection ("the algorithm doesn't know me, I'll do my own thing") requires careful copywriting, patient-advisory review, and iterative testing. This is content design work, not just engineering.

The thing I would do differently the second time: invest more heavily in the clinician engagement work before launch, not after. Clinicians who do not understand what a policy is, what off-policy evaluation gives them, what an OOD flag means, and how to interpret a confidence interval will either reflexively follow or reflexively ignore the recommendation. Both modes produce poor outcomes. The pattern that works is investing in clinician education during the build (not at launch): structured rounds, journal-club-style sessions on the methodology papers, hands-on walkthroughs of the recommendation surface with simulated cases, and clinician-feedback loops that produce iteration on the surface design. The engineering team will resist this on the grounds that it is not engineering; the project should override that resistance, because engagement is the difference between a regime that changes care and a regime that does not.

A trap worth flagging: the difference between a regime that performs well on OPE and a regime that performs well in deployment. OPE estimates the average outcome under the target policy assuming the deployed policy matches the policy that was evaluated. Real-world deployment introduces deviations: clinicians override recommendations at rates that vary by cohort and recommendation strength; patients reject some actions for reasons not in the model; integration failures cause some recommendations to be missed entirely; the population the regime is applied to drifts from the population it was trained on. The deployed regime's actual value is some function of the OPE-estimated value and the deployment dynamics. Surveillance closes the gap; without surveillance, the OPE estimate is a hypothesis that has not been confirmed by deployment data. Build the surveillance pipeline as a first-class component, with the same engineering quality as the training pipeline, and treat the calibration of OPE estimates against observed outcomes as a central quality metric.

The thing about cohort fairness: regime value parity is the headline metric, and it is necessary but far from sufficient. Even a regime with cohort-fair OPE-estimated value can produce systematically different outcomes if the underlying access, support, and engagement infrastructure differs across cohorts. A regime that recommends an SGLT2 for a patient who cannot afford the copay is making a recommendation the patient will not act on. A regime that recommends a behavioral intervention for a patient whose health system does not have the program in their language is making a recommendation that the system cannot deliver. Cohort fairness extends past the regime's recommendations to the operational follow-through: per-cohort fill rates, per-cohort program-enrollment success, per-cohort outcome trajectories, per-cohort patient-reported satisfaction. The fairness analysis must be longitudinal and operational, not point-in-time and statistical.

A trap specific to this recipe: treating the regime as a one-time-build artifact. A regime trained on data through 2026 is optimal for the prescribing patterns and patient mix of 2022-2026; by 2028, the practice patterns have shifted, the drug formulations have evolved, the guidelines have updated, and the cohort demographics have moved. A regime that is not retrained on a defensible cadence becomes a recommendation system that ages out of relevance. The retraining cadence should be tied to drift detection and to the rate of underlying practice change; quarterly is typical for chronic disease management, annually may suffice for slower-evolving areas, and faster cadences are needed for areas with rapid practice evolution. Plan the retraining cadence as part of the deployment, not as something to figure out later.

The thing about regulatory framing: a regime tool that materially shapes sequential clinical decisions is harder to keep outside the FDA SaMD definition than a single-decision treatment-effect estimator. The Cures Act CDS exemption requires that the clinician can independently review the basis of the recommendation; the test for "independently review" is fact-specific and depends on the form of the recommendation, the underlying evidence, and the clinician's ability to understand and override. A regime presented as "the model says do X" without a clear basis review path is more likely to be regulated than a regime presented as "for patients in your patient's cohort, the historical data suggests action X with a moderate confidence interval; here are the alternatives with their estimated values; the basis is the following features and the following similar trajectories." Design the surface for review-ability, not just for picking the right answer. The regulatory analysis is fact-specific; engage legal early, document the deployment posture explicitly, and revisit the analysis when the deployment posture changes. <!-- TODO: confirm current FDA SaMD framework, the Predetermined Change Control Plan policy, the 21st Century Cures Act CDS exemption criteria, and the Good Machine Learning Practice principles at the time of build. -->

The thing about patient communication: a policy recommendation explained to a patient as "the algorithm picked this" produces compliance without engagement, which is the wrong outcome. A policy recommendation explained as "your care team and the regime together think this is the most promising next step given how things have gone, and we will check in to see how it goes" produces engagement and partnership. The framing is the work; iterate it with patient advocates, clinical educators, and (ideally) actual patients. The first version of the patient-facing narrative is the version that needs the most work; ship cautiously, gather feedback, and improve.

Last point, because it is specific to this use case: dynamic treatment regime recommendation is the recipe in Chapter 4 where the system most directly takes on the responsibility of a clinical reasoner. Every recipe in this chapter affects clinical decisions, but Recipe 4.10 is the one where the system is producing a recommendation that synthesizes a path through future decisions, with a value estimate that the clinician will weigh against their own reasoning. The seriousness with which the team treats that responsibility is the difference between a regime that earns clinician trust and one that erodes it. The methodology has to be right. The OPE has to be honest. The cohort fairness has to be explicit. The narrative has to convey uncertainty and alternatives. The override has to be encouraged and structured. The surveillance has to be active. The governance has to be ongoing. The patient communication has to be respectful. The system that gets these right does not produce a wow; it produces a quiet "this is helpful" that, applied across thousands of decision points across thousands of patients, is the version of decision support that healthcare has been trying to build for decades. Build for that.

---

## Variations and Extensions

**Multi-objective regimes with explicit Pareto-frontier exploration.** Some clinical areas have multiple outcomes that resist combination into a single reward (clinical effectiveness, harm avoidance, burden, cost, patient-reported quality of life). Multi-objective offline RL produces a Pareto frontier of policies, each optimizing a different weighting of the objectives. The clinician-facing surface presents the patient's recommended action under each weighting alongside the implications, and the clinician (with the patient) picks among the weightings rather than picking among the actions directly. This is methodologically more demanding and operationally harder to explain; pilot in a clinical area where the multi-objective tradeoffs are explicit and patient-driven (oncology line-of-therapy, end-of-life care planning).

**Patient-driven reward weighting.** A specialization of the multi-objective approach: the patient's stated values are translated into reward weights at the point of recommendation. A patient who has elected comfort-focused care has a reward weighting that down-weights aggressive disease control and up-weights symptom burden; a patient who has elected aggressive disease control has the opposite weighting. The regime serves a recommendation whose policy is calibrated to the patient's reward, not the population-average reward. This requires per-patient policy evaluation rather than a single shared policy and increases serving complexity; the payoff is recommendations that actually reflect what each patient values.

**Federated and consortium-based regime estimation.** Single-institution data is rarely enough for adequate cohort coverage in less-common scenarios (rare comorbidity profiles, less-represented racial groups, less-represented languages). Federated approaches across multiple healthcare systems (OHDSI, PCORnet, Sentinel) produce pooled regimes with broader cohort coverage. The institution-specific regime serves as a fine-tune of the federated baseline; the federated baseline serves as the prior or anchor when local data is sparse. Privacy-preserving methods (secure aggregation, differential privacy) protect individual-institution data; the methodological work to combine federated and local estimation is non-trivial and worth the investment for cohorts where local data is insufficient.

**Real-time RPM-driven decision points.** When a patient is enrolled in remote patient monitoring (continuous glucose monitor, blood pressure cuff, weight scale, pulse oximetry), the decision points can be event-driven rather than visit-aligned: a sustained glucose excursion triggers a regime evaluation; a weight trend triggers a regime evaluation; a sustained blood pressure pattern triggers a regime evaluation. The regime in this variant has higher decision-point density, smaller per-decision actions (titration adjustments rather than regime changes), and tighter integration with the operational workflow. The regulatory framing tightens; closer-to-real-time recommendations are more likely to be regulated as SaMD.

**Consultation-mode regime advice.** Rather than producing a recommendation at a decision point, the regime produces a "what would this regime do?" estimate at any time. The clinician asks the system "if Sara stays on her current regimen for another quarter and then we add an SGLT2, what does the regime estimate?" and the system returns a value estimate with confidence intervals. Consultation mode supports clinical reasoning without committing to a specific recommendation cadence; it is also useful for shared decision-making with patients who want to explore alternatives.

**Multi-regime composition.** A patient may be eligible for multiple regimes (a diabetes regime, a CHF regime, a depression regime). The regimes' recommended actions may interact (an SGLT2 from the diabetes regime affects the CHF regime; an SSRI from the depression regime affects the CHF regime through QT prolongation considerations). Multi-regime composition requires a meta-policy that reconciles the per-regime recommendations into a coherent action set, similar to the multi-condition reconciliation in Recipe 4.9. The reconciliation is not just multi-condition (which 4.9 handles); it is multi-regime, where each regime is itself a policy. This is a research-frontier problem with limited applied work; pilot cautiously.

**Reinforcement-learning-informed clinical-trial design.** The methodology that produces a dynamic treatment regime can also produce hypotheses for prospective sequential-randomized trials. A regime that performs well in OPE but with wide intervals is a candidate for a SMART-style trial that would tighten the intervals with prospective randomized data. The recipe's infrastructure becomes a hypothesis-generating engine for clinical research, with appropriate ethics-board review and pre-registration.

**Causal-discovery-informed state representation.** The state representation in the regime is, by default, a curated feature set. Causal discovery methods (PC algorithm, FCI, neural causal inference) can suggest features that are causally relevant to the outcomes that are not obvious from clinical reasoning alone. The discovered features, after expert review, can enrich the state representation and improve the regime's value. This is methodologically advanced and requires careful causal-inference expertise; the discovered features should not enter the state representation without expert review for confounding and clinical plausibility.

**Counterfactual-explanation surfaces.** Beyond the recommended action and its alternatives, the surface can present counterfactuals: "if the patient's eGFR were 50 instead of 41, the regime would recommend X instead of Y." Counterfactual explanations are useful for clinician understanding of the policy's logic and for patient education. The work to produce counterfactuals well (with attention to causal validity rather than just feature perturbation) is substantial; pilot in a clinical area where counterfactual reasoning is high-value (oncology line-of-therapy, ICU sedation policies).

**Online value-of-information evaluation.** Some recommendations may benefit from additional data before commitment: "the regime recommends X with moderate confidence; if we get a recent A1c and an updated eGFR before the next visit, the confidence interval will narrow substantially." The system surfaces value-of-information analyses that suggest which additional measurements would most improve the recommendation's confidence. This connects to ordering and lab-utilization workflows that were out of scope for the base recipe.

**Prospective regime-versus-current-care comparison studies.** Once a regime has been deployed in some clinical contexts and not others (a phased rollout), a quasi-experimental comparison of outcomes between deployed and non-deployed contexts produces real-world evidence on the regime's value. The methodology requires careful design (interrupted time series, difference-in-differences, regression discontinuity if a clear deployment threshold exists) and prospective registration of the analysis plan. The output is a publishable, peer-reviewable assessment of the regime's real-world performance, complementing the OPE-based pre-deployment estimates.

---

## Related Recipes

- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Adherence signals from 4.5 inform the state representation in 4.10 and the value of adherence-supportive actions in the catalog.
- **Recipe 4.6 (Care Gap Prioritization):** The care gap inventory from 4.6 contributes actions to the regime's catalog (care-gap-closure as a possible action at decision points).
- **Recipe 4.7 (Care Management Program Enrollment):** Care management enrollment from 4.7 informs the action catalog and the state representation; the care manager's involvement is a contextual factor in many regime recommendations.
- **Recipe 4.8 (Treatment Response Prediction):** 4.8's per-treatment CATE estimates are the single-decision-point analog of 4.10's regime-level value estimates. The infrastructure compounds heavily: the trajectory store, the cohort fairness instrumentation, the validator pattern, and the regulatory framing all carry forward.
- **Recipe 4.9 (Personalized Care Plan Generation):** 4.9 produces the broader plan in which a 4.10 recommendation is one component. The regime's recommendation flows back into the care plan as an action; the care plan provides the context (goals-of-care, patient preferences, social determinants) that the regime's state representation may not fully capture.
- **Recipe 2.x (LLM / Generative AI):** The narrative generation and validator pattern uses techniques developed across Chapter 2; the validator pattern from 2.5 (After-Visit Summary) and 2.9 (Clinical Decision Support Synthesis) applies directly with stricter rules for regime narratives.
- **Recipe 7.x (Predictive Analytics / Risk Scoring):** Risk-stratification scores from Chapter 7 may inform regime eligibility, decision-point cadence, and the reward function's harm-avoidance weighting.
- **Recipe 12.x (Time Series Analysis / Forecasting):** Disease-trajectory forecasting from Chapter 12 is methodologically related; trajectory-state evolution prediction informs the regime's state-transition modeling.
- **Recipe 13.x (Knowledge Graphs):** Clinical-content knowledge graphs (action catalogs with relationships, contraindications, guideline references) provide structure for the regime catalog at higher sophistication levels.
- **Recipe 15.x (Reinforcement Learning):** Recipe 4.10 is, methodologically, an applied reinforcement learning recipe specialized to healthcare with offline-only training and clinical-grade governance. Chapter 15 covers the general RL foundations; Recipe 4.10 is one application area.

---

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon SageMaker Model Registry](https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html)
- [Amazon SageMaker Feature Store](https://docs.aws.amazon.com/sagemaker/latest/dg/feature-store.html)
- [Amazon DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html)
- [AWS HealthLake Developer Guide](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [Amazon EventBridge User Guide](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html)
- [Amazon Kinesis Data Streams Developer Guide](https://docs.aws.amazon.com/streams/latest/dev/introduction.html)
- [Amazon API Gateway Developer Guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html)
- [Amazon Cognito Developer Guide](https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html)
- [Amazon QuickSight User Guide](https://docs.aws.amazon.com/quicksight/latest/user/welcome.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS (Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)

**AWS Sample Repos:**
- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): SageMaker Training, Model Registry, and Endpoints patterns applicable to regime training and serving
- [`amazon-sagemaker-feature-store-end-to-end-workshop`](https://github.com/aws-samples/amazon-sagemaker-feature-store-end-to-end-workshop): Feature Store usage applicable to point-in-time-correct state construction at decision points
- [`amazon-bedrock-workshop`](https://github.com/aws-samples/amazon-bedrock-workshop): Hands-on labs covering structured-output prompting that informs clinician-facing regime briefings and patient-facing summaries
- [`fhir-works-on-aws-deployment`](https://github.com/awslabs/fhir-works-on-aws-deployment): FHIR-native API patterns applicable to persisting regime recommendations as FHIR `Task` and `ServiceRequest` resources

<!-- TODO: confirm the current names and locations of the aws-samples repos; they have been reorganizing. -->

**AWS Solutions and Blogs:**
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter AI/ML and Healthcare): browse for healthcare ML, sequential-decision-support, and population health reference architectures
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "reinforcement learning," "causal inference," and "FHIR" for relevant deep-dives
- [AWS for Industries Blog](https://aws.amazon.com/blogs/industries/) (Healthcare and Life Sciences): search "decision support," "treatment recommendation," and "value-based care" for end-to-end customer architectures

<!-- TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs. -->

**External References (Methodology):**
- [Hernán M., Robins J. *Causal Inference: What If*](https://www.hsph.harvard.edu/miguel-hernan/causal-inference-book/): the canonical reference on causal inference from observational data, including target trial emulation and G-methods <!-- TODO: confirm the current edition and URL at time of build. -->
- [Murphy S. *Optimal Dynamic Treatment Regimes*](https://www.jstor.org/stable/3647538): the foundational statistical paper on dynamic treatment regimes <!-- TODO: confirm reference at the time of build. -->
- [Chakraborty B., Moodie E. *Statistical Methods for Dynamic Treatment Regimes*](https://link.springer.com/book/10.1007/978-1-4614-7428-9): textbook reference on dynamic treatment regime methodology
- [Kosorok M., Laber E. *Precision Medicine*](https://www.annualreviews.org/doi/10.1146/annurev-statistics-031017-100753): annual-review-style overview of precision medicine methodology including dynamic treatment regimes
- [Komorowski M. et al. *The AI Clinician learns optimal treatment strategies for sepsis in intensive care*](https://www.nature.com/articles/s41591-018-0213-5): canonical applied paper on offline RL for ICU treatment policies, with extensive subsequent commentary <!-- TODO: confirm reference at time of build. -->
- [Levine S., Kumar A., Tucker G., Fu J. *Offline Reinforcement Learning: Tutorial, Review, and Perspectives on Open Problems*](https://arxiv.org/abs/2005.01643): comprehensive review of offline RL methods with applicability to healthcare problems

**External References (Tooling):**
- [d3rlpy](https://github.com/takuseno/d3rlpy): production-grade offline RL library
- [DoWhy](https://github.com/py-why/dowhy): causal inference library with sequential-treatment support
- [EconML](https://github.com/py-why/EconML): meta-learners and causal forests for treatment effect estimation
- [CausalML](https://github.com/uber/causalml): treatment effect and uplift modeling library

**External References (Regulatory and Standards):**
- [FDA Software as a Medical Device (SaMD) framework](https://www.fda.gov/medical-devices/software-medical-device-samd) <!-- TODO: confirm the current FDA SaMD framework documents at the time of build. -->
- [FDA Predetermined Change Control Plan guidance for AI/ML SaMD](https://www.fda.gov/medical-devices/software-medical-device-samd/marketing-submission-recommendations-predetermined-change-control-plan-artificial-intelligence) <!-- TODO: confirm the current PCCP guidance at the time of build. -->
- [FDA-Health Canada-MHRA Good Machine Learning Practice (GMLP) for Medical Device Development](https://www.fda.gov/medical-devices/software-medical-device-samd/good-machine-learning-practice-medical-device-development-guiding-principles) <!-- TODO: confirm the current GMLP principles at the time of build. -->
- [FDA Clinical Decision Support Software guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software) <!-- TODO: confirm the current FDA CDS guidance and the 21st Century Cures Act exemption criteria at the time of build. -->

**External References (Clinical Content):**
- [Obermeyer Z. et al. 2019, *Dissecting Racial Bias in an Algorithm Used to Manage the Health of Populations*](https://www.science.org/doi/10.1126/science.aax2342): the canonical cautionary tale for fairness failures in healthcare AI; required reading for anyone building dynamic treatment regimes
- [HL7 FHIR `Task` Resource](https://www.hl7.org/fhir/task.html): the FHIR specification for action assignment and tracking
- [HL7 FHIR `ServiceRequest` Resource](https://www.hl7.org/fhir/servicerequest.html): the FHIR specification for service requests including treatments and procedures
- [USPSTF Recommendations](https://www.uspreventiveservicestaskforce.org/uspstf/): preventive-care recommendations relevant to action catalogs in preventive-care regimes
- [HEDIS Measures](https://www.ncqa.org/hedis/): healthcare-quality measures relevant to reward function specifications

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | One clinical area (e.g., diabetes stepwise therapy) + curated state representation + small action catalog (5-8 actions) + Q-learning policy estimation + doubly-robust OPE with overall and 2-3 cohort axes + sensitivity analysis + clinician-facing recommendation API with structured comparison + LLM narrative with validator + manual override workflow + basic surveillance (adherence and outcome tracking) | 8-12 months |
| Production-ready | Full pipeline: 2-3 clinical areas with complete trajectory pipelines + behavior policy estimation with cohort calibration + multi-method regime estimation (Q-learning + offline RL + A-learning) + comprehensive OPE with multiple estimators, cohort stratification across all standard axes, and sensitivity analysis + governance package generation + SageMaker Model Registry integration + recommendation API via SMART on FHIR + clinician-facing narrative with strict four-layer validator + patient-facing narrative variant + EHR integration with override capture + cross-recipe orchestration with 4.5 through 4.9 + drift detection and retraining automation + cohort-stratified surveillance dashboards + regime-deprecation handling + complete regulatory documentation + clinician engagement program | 36-54 months |
| With variations | Add multi-objective regimes, patient-driven reward weighting, federated and consortium estimation, real-time RPM-driven decision points, consultation-mode advice, multi-regime composition, counterfactual explanation surfaces, value-of-information analysis, prospective comparison studies | 18-36 months beyond production-ready |

---

## Tags

`personalization` · `dynamic-treatment-regime` · `sequential-decision-making` · `reinforcement-learning` · `offline-rl` · `q-learning` · `causal-inference` · `target-trial-emulation` · `off-policy-evaluation` · `clinical-decision-support` · `samd` · `equity` · `cohort-analysis` · `fhir` · `smart-on-fhir` · `bedrock` · `sagemaker` · `dynamodb` · `feature-store` · `step-functions` · `lambda` · `healthlake` · `complex` · `research-to-production` · `hipaa`

---

*← [Recipe 4.9: Personalized Care Plan Generation](chapter04.09-personalized-care-plan-generation) · [Chapter 4 Preface](chapter04-preface) · Chapter 4 Complete · [Next: Chapter 5 - Entity Resolution / Record Linkage →](chapter05-preface)*
