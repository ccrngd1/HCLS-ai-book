# Recipe 14.2: Patient-Provider Assignment

**Complexity:** Moderate · **Phase:** MVP · **Estimated Cost:** ~$30-150/month compute

---

## The Problem

A physician leaves your practice. Maybe they retired, maybe they moved across the country, maybe they burned out (it happens more than anyone admits). Whatever the reason, their panel of 1,800 patients just became orphaned. Every one of those patients needs a new primary care provider. Today.

The scheduler opens a spreadsheet. They start manually assigning patients based on... what, exactly? Alphabetical order? Whoever has the most open slots? The provider who happens to be in the office that day? There's no systematic way to match patients to providers based on clinical needs, language preferences, visit frequency, or panel composition goals.

So what happens? The complex diabetic with CKD who needs monthly visits gets assigned to the part-time NP who's already over target. The Mandarin-speaking patient gets assigned to a provider who doesn't speak Mandarin, adding interpreter costs to every visit and reducing the quality of the therapeutic relationship. The patient with CHF and COPD who was seeing an internist gets reassigned to a family medicine doc who's great but has never managed that combination of conditions.

This isn't just an administrative headache. It's a clinical quality problem. Patients who get poorly matched to providers are more likely to no-show, more likely to leave the practice entirely, and less likely to achieve their care goals. The first 90 days after a provider transition are when patients are most vulnerable to falling through the cracks.

And it's not just provider departures. New patients calling to establish care need a PCP assigned. Panel rebalancing happens quarterly. Providers change their FTE status. Every one of these events triggers the same question: which patients should go to which providers?

---

## The Technology: Constrained Optimization for Assignment Problems

### What Is an Assignment Problem?

The patient-provider assignment problem is a variant of a classic in operations research: the assignment problem. You have a set of agents (patients) and a set of tasks (provider slots), and you want to find the matching that maximizes some measure of quality while respecting constraints.

More formally: you have N patients and M providers. Each patient-provider pair has a "preference score" that captures how good that match would be (based on language, complexity, capacity, continuity, and other factors). You want to assign every patient to exactly one provider such that the total preference score across all assignments is maximized, subject to constraints like panel capacity limits and provider availability.

This is a binary integer program. The decision variables are binary (patient i is either assigned to provider j, or they're not; there's no "half assigned"). The objective is linear (sum of scores times assignment indicators). The constraints are linear (sum of assignments per provider must not exceed capacity). Linear solvers eat this for breakfast.

### Why This Is Harder Than It Sounds

The mathematical formulation is clean. The real-world complexity lives in three places:

**Scoring is subjective.** How much does language concordance matter relative to panel balance? Is a gender preference match worth more than clinical complexity alignment? These weights encode organizational values, and different stakeholders will disagree. Your medical director cares about complexity matching. Your operations team cares about panel balance. Your patient experience team cares about language and gender preferences. The optimization framework forces you to make these tradeoffs explicit and quantifiable, which is uncomfortable but ultimately healthy.

**Capacity isn't uniform.** A patient who visits biweekly consumes 26 appointment slots per year. A patient who comes annually consumes 1. Assigning five biweekly patients to a provider is not the same as assigning five annual patients, even though the raw patient count is identical. Your capacity constraints need to account for visit frequency, which means you're really optimizing weighted panel load, not just headcount.

**The problem recurs.** This isn't a one-time optimization. Patients join and leave. Providers change availability. Panel targets shift. You need both a batch mode (reassign 500 patients from a departing provider) and an incremental mode (assign one new patient who just called). The batch mode uses the full optimizer. The incremental mode can use a simplified greedy approach (pick the highest-scoring available provider) but must respect the same constraints and scoring logic.

### Solver Selection

For healthcare panel assignment at typical scales (hundreds of patients, dozens of providers), open-source solvers handle the problem easily:

**CBC (Coin-or Branch and Cut).** Ships with PuLP, the most popular Python optimization modeling library. Handles binary integer programs with tens of thousands of variables in seconds. No license required. This is the right choice for most healthcare organizations starting out.

**HiGHS.** A newer open-source solver that's faster than CBC on larger problems. Good if you're scaling to thousands of patients across hundreds of providers.

**Gurobi / CPLEX.** Commercial solvers that are faster still, but the free tier has variable limits and the commercial license is expensive. Overkill for panel assignment unless you're a massive health system running this across 10,000+ providers.

For the problem sizes typical in primary care (a departing provider's panel of 500-2,000 patients distributed across 10-50 remaining providers), CBC solves optimally in under 5 seconds. You don't need a commercial solver.

### Batch vs. Incremental Assignment

Two modes, same scoring logic:

**Batch assignment** runs when a large event triggers many reassignments: provider departure, panel rebalancing, practice merger. The full optimizer runs, considers all patients simultaneously, and produces a globally optimal assignment. This is the mode we focus on in this recipe.

**Incremental assignment** runs when a single new patient needs a PCP. The optimizer is overkill for one patient. Instead, compute the preference score for that patient against all accepting providers, and assign to the highest-scoring one with available capacity. This is a greedy approach that's suboptimal globally but fast and good enough for single-patient decisions.

Both modes must use the same scoring function and respect the same constraints. If your batch optimizer says language concordance is worth 30 points, your incremental assigner should too. Otherwise you get inconsistent panel compositions depending on whether patients arrived in a batch or one at a time.

---

## General Architecture Pattern

```
[Patient & Provider Data] → [Preference Scoring] → [Constraint Optimization] → [Validation] → [Human Review] → [EHR Write-back]
```

**Data Collection.** Pull current panel rosters, provider attributes (languages, specialty, FTE, panel targets), and patient attributes (demographics, conditions, visit frequency, preferences) from your EHR and scheduling systems. For batch reassignment, also pull the departing provider's panel list.

**Preference Scoring.** For every patient-provider pair, compute a match quality score. The scoring function combines multiple factors with configurable weights: language concordance, gender preference, clinical complexity alignment, panel balance (how far is this provider from their target?), and continuity (was this provider on the same care team as the patient's previous PCP?). The output is a score matrix: patients on one axis, providers on the other, scores in the cells.

**Constraint Optimization.** Feed the score matrix and constraints into a solver. Constraints include: each patient assigned to exactly one provider, no provider exceeds their panel maximum (weighted by visit frequency), and providers who've closed their panels get zero new assignments. The solver finds the assignment that maximizes total match quality while respecting all constraints.

**Validation.** After the solver runs, verify the solution makes clinical sense. Check that all patients are assigned, no capacity limits are violated, and the distribution across providers is reasonable (flag if one provider gets more than 60% of new assignments). Generate human-readable rationale for each assignment explaining why that match was chosen.

**Human Review.** Present proposed assignments to the panel management team with scores, rationale, and distribution summaries. They approve, reject, or override individual assignments. This step is non-negotiable in healthcare. Optimization suggests; humans decide.

**EHR Write-back.** After approval, update the EHR's panel attribution. This is typically an HL7 FHIR CareTeam resource update or a proprietary API call. Handle failures gracefully. A failed write-back should not leave your assignment table and the EHR out of sync.

<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Add a subsection or paragraph explaining how batch and incremental assignment modes coexist architecturally. The incremental case (single new patient, needs PCP immediately) uses a simplified greedy approach with the same scoring function. Discuss latency requirements (seconds vs. minutes) and how both modes share constraint/scoring logic. -->

<!-- TODO (TechWriter): Expert review A4 (MEDIUM). Add a "Fairness and Bias" subsection (in Honest Take or Variations). At minimum: log all assignments with patient demographics, run periodic statistical tests (chi-square on distributions by race/ethnicity/language), alert if any provider's panel demographics deviate significantly from the practice's overall patient demographics. -->

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter14.02-architecture). The Python example is linked from there.

## The Honest Take

The optimization part is the easy part. Seriously. Formulating the integer program, running the solver, getting an optimal solution: that's a weekend project for anyone who's taken an OR class. The hard parts are everything around it.

**Getting the weights right is a political problem, not a technical one.** Your medical director wants complexity matching weighted at 50%. Your operations VP wants panel balance at 50%. Your patient experience officer wants language concordance at 50%. They can't all be 50%. The optimization framework forces this conversation into the open, which is valuable but uncomfortable. Expect the first three months to be mostly weight-tuning based on stakeholder feedback on the assignments produced.

**The scoring function encodes bias whether you intend it or not.** If language concordance is weighted heavily and your Mandarin-speaking providers happen to be your most junior, you'll systematically assign Mandarin-speaking patients to junior providers. That might be fine (language concordance genuinely matters for outcomes) or it might perpetuate a disparity you'd rather address by hiring more senior Mandarin-speaking providers. Monitor assignment patterns by patient demographics. Run chi-square tests quarterly. Build alerts for statistical anomalies.

**Providers will override your optimizer.** And that's fine. The optimizer suggests; humans decide. But track the override rate. If it's above 20%, your scoring function doesn't match clinical judgment and needs recalibration. If it's below 5%, you might be able to auto-approve low-risk assignments (healthy patients to providers with ample capacity) and only route complex cases to human review.

**The incremental case is where you'll spend most of your engineering time.** The batch optimizer runs weekly or on-demand. The incremental assigner runs every time a new patient calls. It needs sub-second latency, which means you can't spin up a SageMaker job for each patient. Pre-compute provider scores and cache them. Update the cache when panel counts change. The architecture for incremental assignment is fundamentally different from batch, even though the scoring logic is shared.

---

## Related Recipes

- **Recipe 14.1: Appointment Slot Optimization** - Optimizes the template structure; this recipe optimizes who fills those slots
- **Recipe 14.3: Nurse Scheduling** - Similar constraint optimization but with shift-based temporal constraints
- **Recipe 14.6: Real-Time Resource Allocation** - The real-time counterpart to this batch optimization

---
