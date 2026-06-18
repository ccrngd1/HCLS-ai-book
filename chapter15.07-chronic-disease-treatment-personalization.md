# Recipe 15.7: Chronic Disease Treatment Personalization

**Complexity:** Complex · **Phase:** Research/Early Pilot · **Estimated Cost:** ~$1,500–4,000/month (training infrastructure + inference)

---

## The Problem

A patient with type 2 diabetes walks into their quarterly endocrinology visit. Their HbA1c is 8.4%, up from 7.9% three months ago. They're on metformin monotherapy. The clinician has a decision to make: add a second agent? Which one? An SGLT2 inhibitor for the cardiovascular benefit? A GLP-1 agonist for the weight loss? A DPP-4 inhibitor because it's well-tolerated and the patient already struggles with medication adherence?

The "right" answer depends on a dozen factors that interact in ways no static guideline can capture. This patient's kidney function is declining (eGFR 52, down from 65 last year). They have a history of one severe hypoglycemic episode two years ago. Their medication adherence hovers around 70%. They're 68 years old with heart failure. And their insurance just changed, which may affect formulary access.

Clinical practice guidelines (like the ADA Standards of Care) provide decision trees, but they're designed for the "average" patient at each branch point. They say "consider SGLT2 inhibitors for patients with heart failure" but don't tell you whether this specific patient, with this specific combination of declining renal function, borderline adherence, and hypoglycemia history, will actually benefit more from an SGLT2 inhibitor versus a GLP-1 agonist versus simply addressing the adherence problem first.

The scale of this problem is staggering. Over 37 million Americans have diabetes. Each one has a quarterly treatment decision. Each decision has consequences that unfold over months and years: microvascular complications, cardiovascular events, quality of life, treatment burden. The difference between "good enough" treatment and truly personalized treatment compounds over a decade of disease management. And the clinician making that decision has 15 minutes per visit, a dozen other patients waiting, and guidelines that were last updated 18 months ago.

This is the kind of problem where reinforcement learning shines: sequential decisions under uncertainty, delayed rewards, individual variation that matters, and a rich history of prior decisions and outcomes to learn from.

---

## The Technology: Reinforcement Learning for Long-Horizon Treatment Optimization

### What Reinforcement Learning Brings to Chronic Disease

Reinforcement learning (RL) is a framework for learning optimal sequential decision-making from experience. The agent observes a state, takes an action, receives a reward, and transitions to a new state. Over many interactions, it learns a policy: a mapping from states to actions that maximizes cumulative long-term reward.

For chronic disease management, the mapping is natural:

**State.** The patient's current clinical picture: lab values (HbA1c, eGFR, lipids), current medications, treatment duration, adherence metrics, comorbidities, demographics, and trend information (is HbA1c improving or worsening?).

**Action.** The treatment regimen to prescribe. For type 2 diabetes, this is a discrete set of escalation levels: lifestyle only, metformin monotherapy, various dual therapies, triple therapy, basal insulin, intensive insulin.

**Reward.** A multi-objective signal reflecting glycemic control (HbA1c at target), safety (no hypoglycemia), treatment burden (simpler is better), and appropriateness (don't escalate when adherence is the real problem).

**Policy.** The learned mapping: given this patient's full clinical state, what treatment regimen maximizes their long-term outcomes?

The key difference from acute care RL (like ICU glucose control in Recipe 15.6): the time horizon is years, not hours. A treatment decision made today won't show its full effect for 3 months (the time it takes HbA1c to reflect a change). The consequences of good or bad treatment compound over a decade. And the patient is a full participant: their adherence, lifestyle choices, and preferences are part of the system dynamics.

### Why This Is Harder Than It Sounds

**You cannot explore.** In a video game, the RL agent tries random actions to discover what works. In chronic disease, "let's try a random treatment and see what happens over the next year" is unethical. Every action affects a real patient's health trajectory. This means you must learn entirely from historical treatment records (offline RL).

**Offline RL has distributional shift.** When you learn from historical data, you're learning from the actions clinicians actually took. If your learned policy recommends an action that clinicians rarely chose in a given situation, you have no data to evaluate whether that action is actually good. You're extrapolating beyond your training distribution. For chronic disease, where outcomes take months to observe, this extrapolation is especially dangerous.

**Rewards are severely delayed.** The consequence of a treatment change at a January visit isn't fully apparent until the April visit (when the next HbA1c is measured). If the patient also changed their diet, started exercising, or missed doses, attributing the outcome to the treatment decision is confounded. This temporal credit assignment problem is much harder than in acute care settings.

**Multiple objectives compete.** You can't just optimize HbA1c. A patient controlled at 6.5% through aggressive insulin therapy who has frequent hypoglycemia and takes 4 injections daily is worse off than a patient at 7.2% on a single oral medication with no side effects. The reward function must balance glycemic control, safety, treatment burden, and quality of life.

**Patient heterogeneity is the whole point.** Two patients with identical HbA1c values may need completely different treatments based on their kidney function, cardiovascular risk, age, adherence patterns, and treatment history. The policy must learn to personalize, not just find the "best average treatment."

### Batch-Constrained Q-Learning: The Right Tool for This Job

For chronic disease treatment personalization, Batch-Constrained Q-Learning (BCQ) is particularly appropriate:

1. **Small discrete action space.** Type 2 diabetes has roughly 8 treatment escalation levels. This is small enough for tabular methods during prototyping and well-suited to constrained discrete-action algorithms.

2. **Conservative by design.** BCQ restricts the learned policy to only recommend actions that clinicians have actually taken in similar states. It won't recommend an untested treatment combination just because the Q-function extrapolates optimistically.

3. **Respects clinical expertise.** The BCQ threshold parameter controls how much the policy can deviate from historical clinician behavior. A high threshold means "only recommend what clinicians usually do here." A low threshold means "willing to try less common choices if the data supports them." For chronic disease, starting conservative is wise: clinicians have decades of experience encoded in their treatment patterns.

4. **Handles the offline constraint naturally.** BCQ was designed specifically for the offline RL setting where you cannot collect new data. It addresses distributional shift by construction rather than as an afterthought.

### The General Architecture Pattern

```
[EHR Longitudinal Records] → [Episode Construction] → [Offline Policy Learning (BCQ)]
                                                                    ↓
[Off-Policy Evaluation] → [Safety Constraint Layer] → [Clinical Decision Support]
                                                                    ↓
                                                    [Clinician Accept/Override + Audit]
```

**Episode construction.** Transform years of patient treatment history into RL episodes. Each quarterly visit becomes a transition: state (clinical picture at the visit), action (treatment the clinician chose), reward (outcome observed at the next visit 3 months later), next state (clinical picture at the next visit).

**Offline policy learning.** Train a BCQ agent on the historical episodes. The agent learns which treatment decisions led to good outcomes (HbA1c at target, no hypoglycemia, minimal treatment burden) for patients in similar clinical states.

**Off-policy evaluation.** Estimate how the learned policy would have performed on held-out patient histories. Compare agreement rates with clinicians, estimated HbA1c distributions, and estimated hypoglycemia rates.

**Safety constraint layer.** Hard rules that override the policy regardless of what it recommends: maximum escalation speed, minimum treatment duration before changes, renal contraindications, adherence gating, and age-based insulin avoidance.

**Clinical decision support.** At a quarterly visit, the system constructs the patient's current state, queries the policy, applies safety constraints, and presents a recommendation for the clinician to accept, modify, or reject. Every interaction is logged.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter15.07-architecture). The Python example is linked from there.

## The Honest Take

Here's what becomes clear once you actually try to build this: the RL algorithm is maybe 10% of the work. The other 90% is data engineering, clinical validation, and trust-building.

The data pipeline is brutal. EHR medication records are a mess. Patients switch providers, change insurance, fill prescriptions at different pharmacies. Mapping free-text prescriptions to standardized treatment levels requires medication reconciliation logic that handles brand names, generics, combination pills, and dose ranges. Adherence estimation from pharmacy claims (proportion of days covered) is a rough proxy at best. And temporal alignment of irregularly-spaced visits into consistent quarterly decision points requires judgment calls about what counts as "close enough to 3 months."

The reward function is where clinical and ML expertise must collaborate intensely. I've seen teams optimize HbA1c aggressively, only to realize their policy was recommending insulin for patients who would have done fine on oral medications with better adherence support. The "adherence mismatch" penalty in the reward function exists because of this exact failure mode. Always decompose your reward into components and track each one separately. A single aggregate number hides dangerous trade-offs.

The safety constraint layer often matters more than the RL policy itself. A simple "follow ADA guidelines" algorithm with good safety constraints can outperform a sophisticated RL policy with weak constraints. The constraints encode decades of clinical trial evidence. The RL policy adds value at the margins: better personalization for patients who don't fit neatly into guideline categories, better anticipation of trends, better handling of competing comorbidities. But the constraints keep patients safe.

The biggest surprise: clinician agreement rate is actually a feature, not a bug. When your BCQ policy agrees with clinicians 75% of the time, that's good. It means the policy learned that clinicians are mostly right. The interesting 25% is where the policy disagrees, and those disagreements need careful case-by-case review before you trust them. Some will be genuine improvements (the policy noticed a trend the clinician missed). Some will be artifacts of limited training data. You can't tell which is which without clinical review.

Plan for 3-5 years from "working prototype" to "influencing treatment decisions in one clinic." That's not pessimism; that's the reality of clinical AI deployment for treatment recommendations.

---

## Related Recipes

- **Recipe 15.6 (Glucose Control in ICU):** Uses the same offline RL framework for acute care insulin dosing. Shares the safety constraint and OPE patterns but operates on a much shorter time horizon (hours vs. months).
- **Recipe 15.4 (Sepsis Treatment Optimization):** Another offline RL application with safety constraints. Similar architecture, different clinical domain.
- **Recipe 4.3 (Treatment Pathway Recommendations):** A simpler, non-RL approach to treatment personalization using collaborative filtering. Good comparison point for when RL is overkill.
- **Recipe 7.2 (Disease Progression Modeling):** The patient state trajectory modeling used here builds on disease progression concepts.
- **Recipe 15.1 (Alert Threshold Optimization):** A simpler RL application that shares the offline learning pattern in a lower-stakes setting. Good starting point before tackling treatment personalization.

---
