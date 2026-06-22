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
- **FDA SaMD guidance has evolved.** Predetermined change control plans, Good Machine Learning Practice principles, and the ongoing regulatory science work have produced a clearer (though still evolving) framework for AI/ML-based clinical decision support. Treatment-regime tools that materially shape sequential clinical decisions are squarely in the SaMD scope. 
- **Federated and consortium work.** OHDSI, PCORnet, and the Sentinel network have produced multi-institution sequential treatment studies with privacy-preserving methods. These pooled analyses address the small-sample problem at single institutions and produce reference policies that can serve as priors or benchmarks for institution-specific work.
- **Patient-engagement research.** Work on how patients understand and respond to policy-based recommendations is appearing more frequently in the literature. The findings are nuanced: patients do not always prefer the policy that maximizes the expected clinical outcome. They prefer policies that respect their stated values, that explain their reasoning, and that allow for meaningful patient input. This shapes the user-experience layer of the recipe; a policy presented as a directive performs worse, on engagement and on outcomes, than a policy presented as a structured recommendation with patient-aligned reasoning.

### Where LLMs Fit (and Don't)

Same pattern as Recipes 4.5 through 4.9, with regime-specific notes:

- **Policy estimation, off-policy evaluation, regime selection.** Not the LLM's job. Statistical methods (Q-learning, A-learning, offline RL, target trial emulation) trained on validated cohorts.
- **Clinician-facing regime briefings.** Yes. A structured-output prompt takes the policy's recommended action at the current decision point, the alternative actions and their estimated values, the patient's state summary, the off-policy evaluation confidence intervals, and the regime version, and produces the paragraph the clinician reads. The briefing surfaces the recommendation, the comparison to alternatives, the uncertainty, the data-quality flags, and the explicit "the regime suggests, the clinician decides" framing.
- **Patient-facing regime explanations** (when the clinician chooses to share). Yes, with the same validator pattern as prior recipes. The patient version uses lay-language equivalents, with reading-level matched and approved-claim language enforced. Patient-facing regime communication is harder than patient-facing single-decision communication because the regime's logic is path-dependent; the explanation must convey "this is the recommendation now because of how things have gone, and we will reassess next time."
- **Free-form clinical reasoning about which regime to follow.** No. The LLM does not pick; it packages. The line is the same line as in 4.7 and 4.8. Treatment regimes are the highest-stakes recipe in this chapter, so the line is even more important.
- **Why-this-action narrative.** Yes, when the system surfaces feature contributions, similar-trajectory examples, and guideline references alongside the policy's recommendation. The LLM packages a structured rationale; the underlying contributors come from the regime model and the clinical-content layer, not from the LLM's own knowledge.

---

## General Architecture Pattern

The pipeline has seven logical components: a regime catalog component that maintains the structured representation of regimes in scope (state definitions, action catalogs, reward functions, decision-point cadences, eligibility predicates, governance metadata); a trajectory pipeline component that constructs longitudinal trajectories from source clinical data; a sequential-causal-modeling component that estimates regimes (Q-learning, offline RL, target trial emulation) with uncertainty; an off-policy-evaluation component that estimates regime value with confidence intervals; a regime-serving component that produces recommendations at decision points; a clinician-facing decision-support component that packages recommendations with rationale, alternatives, and uncertainty; and a feedback and surveillance component that captures actual trajectories and drives retraining, calibration monitoring, and post-deployment surveillance.

```text
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

**The trajectory pipeline is where the data substrate is built.** Each patient's clinical history is represented as a sequence of (state, action, reward, next_state) tuples, with state at each decision point computed from the feature store and the recent observation history, action labeled from the medication, encounter, or procedure record, and reward computed from the outcomes that accumulated between decision points. The trajectory record is the working artifact for everything downstream; quality issues here propagate to every model. Censoring handling (when patients leave the system, change insurers, or are lost to follow-up) is non-trivial and must be done explicitly with appropriate inverse-probability-of-censoring weights. Out-of-catalog actions (the clinician picked something not in the regime's action catalog) are recorded as such; trajectories with high out-of-catalog rates are surfaced to the catalog-governance committee as a signal that the catalog may need expansion.

**The sequential causal modeling stack is the methodological core.** The protocol mirrors a target trial: specify the regime, eligibility, treatment strategies, outcome definition, censoring, and analytic dataset construction. Multiple estimators (Q-learning as the workhorse, offline RL where the state-action space is high-dimensional, A-learning or outcome-weighted learning as cross-validation) produce candidate regimes. The behavior policy is estimated separately and validated for calibration; a poorly-calibrated behavior policy produces poor importance weights downstream. Disagreements among estimators trigger investigation; agreement is the signal of regime robustness. The training pipeline runs on a scheduled cadence (typically quarterly to annually depending on data drift); each training run produces a candidate regime version that goes through OPE before promotion.

**Off-policy evaluation produces the value estimate that drives deployment decisions.** Multiple OPE estimators (doubly-robust as the workhorse, importance sampling and FQE as complements) produce a value estimate with confidence intervals. Cohort-stratified OPE is non-negotiable: a regime that has a high overall value but a much lower value (or wider intervals) for some cohorts is a regime with a fairness problem before deployment. Sensitivity analysis (E-value, Rosenbaum bounds) bounds how much unmeasured confounding could change the conclusion. The OPE results are the artifact the governance committee reviews; a candidate regime with a confidence interval that does not exclude the prior regime's value is not promoted. The pattern that fails is rushing OPE; the resulting deployment decisions are made on point estimates without the uncertainty discipline that the data demands.

**The regime serving layer produces the recommendation at the patient's decision point.** State construction (from the feature store and trajectory store), eligibility check, OOD check (does the patient's state fall within the support of the training trajectories?), policy evaluation (the regime's recommended action and the alternatives), similar-trajectory retrieval (a small cohort of historical trajectories most similar to the patient's state, with their actions and outcomes), and recommendation persistence. The OOD check is critical and often overlooked; a regime applied to a patient whose state is far from the training distribution produces a recommendation that is extrapolation, not interpolation. Such recommendations should be flagged with explicit OOD warnings or suppressed entirely depending on the regime's risk tier.

**The clinician-facing decision support is the interface where the regime meets the clinician.** A structured comparison view (recommended action, alternatives with estimated values and uncertainty, OOD flag, regime version, similar trajectories, guideline references, contraindication checks) precedes the LLM-generated narrative. The narrative explains the recommendation, the alternatives, the uncertainty, and the basis, without crossing into prescriptive recommendation language. The validator pattern from Recipe 4.8 applies with stricter rules; regimes that recommend specific treatments are higher-stakes than single-decision treatment-effect estimates. The override and patient-share workflows capture the clinician's actual decision and rationale, which feed back into the surveillance layer.

**Feedback and surveillance close the loop.** Action-taken events, outcome events, adverse events, and patient feedback append to the patient's trajectory record. Regime adherence tracking shows how often clinicians follow the recommendation, by area, cohort, and recommendation strength; low adherence to high-confidence recommendations is a signal of clinician disagreement that merits review. Outcome surveillance compares observed outcomes against the OPE-estimated regime value; calibration drift is the signal that the regime is no longer optimal for the current population. Cohort-stratified surveillance covers outcome trajectories, regime adherence, and OOD rates by cohort; disparities trigger committee review. Periodic retraining accumulates new trajectories into refresh windows; new regime versions are re-evaluated against the current version with OPE before promotion. The surveillance pipeline is where Recipe 4.10 either becomes a living regime or becomes a static artifact that ages out of relevance.

**Reward-function governance is a first-class architectural concern, not a paragraph in production-gaps.** The reward function is the most consequential policy artifact in the regime catalog. Changes to the reward function change what the regime optimizes, which changes what it recommends. The multi-stage reward-change process works as follows. First, a proposal with documented rationale: who is proposing the change, why, what clinical or operational evidence motivates it, what the expected impact on recommended actions is. Second, parallel-evaluation shadow training under both the current and proposed reward: the candidate regime is trained under both rewards, and the resulting policies are compared. The diff surface shows per-patient changes in recommended action (for a sample of representative patients) and per-cohort distributional shift in action mix (does the new reward concentrate recommendations differently across cohorts?). Third, committee review and approval: the governance committee reviews the diff surface, the rationale, and the expected impact, then approves or rejects the change. Fourth, post-promotion audit: after the new reward goes live, structured monitoring including PROMs sampling and qualitative clinician feedback checks for reward-driven unintended optimization (outcomes that improve the reward while worsening unmeasured aspects of patient experience). The `reward_function_version` is persisted separately on every recommendation record so the audit trail can attribute observed changes in recommendation patterns correctly. The required-content validator layer includes reward-version disclosure in the clinician narrative. The governance SLA pattern from Recipe 4.7 and the burden-threshold-as-policy from Recipe 4.9 apply.

**Out-of-catalog rate governance defines when the action catalog is insufficient.** The action catalog is finite; clinicians regularly choose actions not in the catalog. Out-of-catalog rate thresholds drive escalation: an overall out-of-catalog rate exceeding 15 percent triggers a structured catalog-expansion proposal artifact reviewed by the catalog-governance committee (specify the candidate actions, the evidence for inclusion, the training-data requirements, and the projected timeline); a per-cohort out-of-catalog rate exceeding 25 percent triggers an equity-review cycle in addition to the catalog-governance cycle (why is this cohort's treatment pattern systematically outside the catalog?); a growth-rate exceeding 5 percentage points per quarter triggers an investigation regardless of the absolute rate (something in practice is shifting away from the catalog). Response cadence follows the governance-task SLA pattern from Recipe 4.7.

**Horizon-versus-OPE-confidence is an explicit deployment constraint.** The evaluation horizon (how far into the future the OPE estimates the regime's value) and the deployment-relevant horizon (how far into the future the clinical program actually cares about) may diverge. OPE variance grows with horizon length; a deployment-relevant horizon of five years may be OPE-evaluable only to two years with acceptable confidence intervals. The committee's resolution at scoping must be documented. Three responses are available when they diverge: deploy with horizon truncation and explicit narrative disclosure ("the regime's value estimate covers the next two years of decisions; longer-term value is extrapolated"); escalate to advanced OPE methods that mitigate variance growth (per-decision importance sampling, weighted importance sampling, or model-based simulation OPE) at the cost of additional methodological complexity; or defer deployment until additional data accumulates. The `evaluation_horizon` is persisted separately on recommendation records so the audit trail attributes OPE confidence correctly.

**SDOH-cohort PHI sensitivity is explicit, not implicit.** Cohort attributes carried through OPE stratification, surveillance metric dimensions, and similar-trajectory retrieval are PHI-promoting: a combination of race/ethnicity, language preference, age band, insurance type, and geography can identify individuals even without a direct identifier. Specify minimum-necessary cohort attributes per surface: OPE stratification may require the full set for methodological rigor, but the similar-trajectory retrieval surface exposed to clinicians should carry only the attributes necessary for clinical relevance (condition profile, medication history, key labs), not the full SDOH profile. The trajectory store uses separate-table partitioning-by-sensitivity-tier: SDOH-enriched trajectory tables carry elevated audit posture (narrower IAM read scopes, additional CloudTrail data-event capture, shorter data-retention windows for non-essential SDOH fields). The pattern mirrors 4.4 through 4.9 at chapter depth.

**Equity instrumentation is built in, not bolted on.** Regime value parity across cohorts, regime adherence parity, OOD-rate parity, outcome-trajectory parity. Each axis is monitored, with thresholds that trigger committee review when crossed. The Obermeyer pattern applies particularly sharply here: a regime that was estimated on data reflecting historical access and prescribing disparities will encode those disparities into the recommended actions. Sara, who has stable insurance and a primary-care relationship, is in the data; the patients who look like Sara but were lost to follow-up after one missed appointment are not in the data, or are in the data with different (and confounded) outcomes. Regime estimation that does not surface and address the data-driven disparities produces a policy that perpetuates them.

**Regulatory posture is set early and reviewed often.** Most production deployments of dynamic treatment regime tools fall within the FDA's SaMD definition and do not meet the criteria for the Cures Act non-device exemption when the clinician cannot independently review the basis of the recommendation. The model risk classification, the predetermined change control plan, and the post-deployment surveillance plan are deliverables of the project, not afterthoughts. The clinical-leadership-and-regulatory-legal review is a recurring meeting, not a one-time gate. 

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter04.10-architecture). The Python example is linked from there.

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

The thing about regulatory framing: a regime tool that materially shapes sequential clinical decisions is harder to keep outside the FDA SaMD definition than a single-decision treatment-effect estimator. The Cures Act CDS exemption requires that the clinician can independently review the basis of the recommendation; the test for "independently review" is fact-specific and depends on the form of the recommendation, the underlying evidence, and the clinician's ability to understand and override. A regime presented as "the model says do X" without a clear basis review path is more likely to be regulated than a regime presented as "for patients in your patient's cohort, the historical data suggests action X with a moderate confidence interval; here are the alternatives with their estimated values; the basis is the following features and the following similar trajectories." Design the surface for review-ability, not just for picking the right answer. The regulatory analysis is fact-specific; engage legal early, document the deployment posture explicitly, and revisit the analysis when the deployment posture changes. 

The thing about patient communication: a policy recommendation explained to a patient as "the algorithm picked this" produces compliance without engagement, which is the wrong outcome. A policy recommendation explained as "your care team and the regime together think this is the most promising next step given how things have gone, and we will check in to see how it goes" produces engagement and partnership. The framing is the work; iterate it with patient advocates, clinical educators, and (ideally) actual patients. The first version of the patient-facing narrative is the version that needs the most work; ship cautiously, gather feedback, and improve.

Last point, because it is specific to this use case: dynamic treatment regime recommendation is the recipe in Chapter 4 where the system most directly takes on the responsibility of a clinical reasoner. Every recipe in this chapter affects clinical decisions, but Recipe 4.10 is the one where the system is producing a recommendation that synthesizes a path through future decisions, with a value estimate that the clinician will weigh against their own reasoning. The seriousness with which the team treats that responsibility is the difference between a regime that earns clinician trust and one that erodes it. The methodology has to be right. The OPE has to be honest. The cohort fairness has to be explicit. The narrative has to convey uncertainty and alternatives. The override has to be encouraged and structured. The surveillance has to be active. The governance has to be ongoing. The patient communication has to be respectful. The system that gets these right does not produce a wow; it produces a quiet "this is helpful" that, applied across thousands of decision points across thousands of patients, is the version of decision support that healthcare has been trying to build for decades. Build for that.

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

## Tags

`personalization` · `dynamic-treatment-regime` · `sequential-decision-making` · `reinforcement-learning` · `offline-rl` · `q-learning` · `causal-inference` · `target-trial-emulation` · `off-policy-evaluation` · `clinical-decision-support` · `samd` · `equity` · `cohort-analysis` · `fhir` · `smart-on-fhir` · `bedrock` · `sagemaker` · `dynamodb` · `feature-store` · `step-functions` · `lambda` · `healthlake` · `complex` · `research-to-production` · `hipaa`

---

*← [Recipe 4.9: Personalized Care Plan Generation](chapter04.09-personalized-care-plan-generation) · [Chapter 4 Preface](chapter04-preface) · Chapter 4 Complete · [Next: Chapter 5 - Entity Resolution / Record Linkage →](chapter05-preface)*
