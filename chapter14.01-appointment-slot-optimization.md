# Recipe 14.1: Appointment Slot Optimization

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$50-200/month compute

---

## The Problem

Here's a scene that plays out at every outpatient clinic in the country: a scheduler stares at a template that says "30-minute slots, 8am to 5pm" and tries to fit a complex diabetic follow-up, a quick blood pressure recheck, and a new patient evaluation into the same rigid grid. The diabetic follow-up runs 45 minutes. The blood pressure recheck takes 10. The new patient needs a full hour. But the template doesn't care. Every slot is 30 minutes. So the follow-up runs over, the recheck patient waits 20 minutes for a 10-minute visit, and the new patient gets rushed.

This is not a scheduling problem. It's a template design problem.

Most clinics build their appointment templates once, based on gut feel and historical convention, and then never touch them again. "Dr. Martinez does 30-minute slots" becomes organizational gospel. Nobody asks whether 30 minutes is actually optimal for Dr. Martinez's patient mix, which skews heavily toward complex chronic disease management. Nobody models whether overbooking the 9am slots by one patient would recover the revenue lost to no-shows without creating unacceptable wait times.

The numbers are genuinely painful. The average physician loses 14-18% of scheduled slots to no-shows and late cancellations. Clinics that don't overbook absorb that loss directly. Clinics that overbook uniformly create unpredictable wait times that drive patient dissatisfaction. Neither approach is optimal because neither approach uses data.

Appointment slot optimization is the practice of using historical visit data, no-show patterns, and mathematical optimization to design templates that maximize throughput (patients seen per session) while respecting constraints on wait time, provider fatigue, and visit quality. It's one of the cleanest optimization problems in healthcare operations because the constraints are well-defined, the objective is measurable, and the data already exists in your scheduling system.

---

## The Technology: Constraint Optimization for Scheduling Templates

### What Is Optimization?

Mathematical optimization is the discipline of finding the best solution from a set of feasible solutions, subject to constraints. In plain terms: you have a goal (maximize patients seen), you have rules you can't break (no visit shorter than its clinical minimum, no provider working past 6pm, no patient waiting more than 20 minutes), and you want the configuration that achieves the best goal while respecting all the rules.

The three components of any optimization problem:

1. **Decision variables.** What you're choosing. In our case: slot durations by visit type, buffer times between slots, overbooking levels by time-of-day, and session start/end times.

2. **Objective function.** What you're maximizing or minimizing. Here: maximize weighted throughput (patients seen, weighted by visit revenue or clinical priority) while minimizing expected patient wait time. These two objectives conflict, which makes it interesting.

3. **Constraints.** Rules that cannot be violated. Clinical minimums per visit type. Maximum session length. Maximum acceptable wait time. Overbooking limits. Break requirements.

### Why This Is a Good Starter Optimization Problem

Appointment slot optimization sits in the sweet spot of operations research: complex enough to benefit from mathematical modeling, simple enough that a basic formulation produces meaningful results.

The decision space is small. You're choosing maybe 5-8 slot durations (one per visit type), 2-3 buffer configurations, and an overbooking percentage per hour block. That's maybe 30-50 decision variables. Compare that to nurse scheduling (thousands of variables) or OR block allocation (hundreds of competing constraints). A modern solver handles this in seconds.

The data requirements are modest. You need historical visit durations by type (your EHR has this), no-show rates by time-of-day and day-of-week (your scheduling system has this), and patient arrival patterns (check-in timestamps). Most health systems have years of this data sitting unused.

The feedback loop is fast. You change a template, run it for two weeks, and measure the impact on throughput, wait times, and provider satisfaction. Unlike strategic decisions that take months to evaluate, template changes produce measurable results quickly.

### The Formulation

Let me walk through how you'd actually set this up mathematically. The notation may feel dense, but the concepts are straightforward.

**Decision variables:**
- `d[t]` = slot duration for visit type `t` (in minutes)
- `b[i]` = buffer time after slot `i` (in minutes)
- `o[h]` = overbooking level for hour block `h` (number of extra patients)

**Objective (simplified):**
```text
Maximize: sum over all slots of (probability_patient_shows_up * revenue_weight[t])
Minimize: expected_wait_time across all patients

Combined: Maximize throughput - lambda * expected_wait_time
```

The `lambda` parameter controls the tradeoff. Higher lambda means you care more about wait times; lower lambda means you prioritize throughput. This is a dial your operations team tunes based on organizational priorities.

**Constraints:**
```text
d[t] >= clinical_minimum[t]           // can't rush a complex visit
d[t] <= clinical_maximum[t]           // don't over-allocate simple visits
sum(d[i] + b[i]) <= session_length    // everything fits in the day
o[h] <= max_overbook[h]              // overbooking caps per hour
expected_wait[i] <= max_wait          // no patient waits too long
```

**The wait time calculation** is where it gets interesting. Expected wait time depends on the probability that previous patients' visits run long, which depends on the variance in visit duration, not just the mean. A visit type with mean 20 minutes and standard deviation 15 minutes creates much more downstream disruption than one with mean 25 minutes and standard deviation 3 minutes. Your model needs to account for this variance, which means you need the distribution of visit durations, not just the average.

### Solver Selection

For a problem this size, you have several options:

**Linear Programming (LP) / Mixed-Integer Programming (MIP).** If you can linearize your constraints and objective (or approximate them as linear), commercial solvers like Gurobi or CPLEX, or open-source solvers like CBC or HiGHS, will find the global optimum in milliseconds. The catch: wait time calculations involve probability distributions, which aren't naturally linear. You can approximate them with piecewise linear functions or scenario-based approaches.

**Constraint Programming (CP).** Better for problems with complex logical constraints ("if visit type is new patient AND provider is part-time, then slot must be at least 45 minutes"). Google's OR-Tools CP-SAT solver is excellent and free.

**Simulation-based optimization.** Run a discrete-event simulation of the clinic day thousands of times with different template configurations, and pick the one that performs best on average. This handles stochastic elements (no-shows, variable durations) naturally but is computationally heavier. Good for validation even if you use an analytical solver for the initial solution.

**Heuristic approaches.** For a first pass, even a grid search over reasonable parameter ranges (slot durations in 5-minute increments, overbooking from 0-3 per hour) can find good solutions. Not optimal, but fast to implement and often good enough for an MVP.

For most healthcare organizations starting out, I'd recommend: use a MIP solver for the core template optimization (it's fast and gives provably optimal solutions for the linearized problem), then validate the top 3-5 solutions with a simulation to account for stochastic effects the linear model approximates.

### Batch vs. Real-Time

This is a batch optimization problem. You're not optimizing in real-time as patients arrive (that's a different problem, closer to Recipe 14.6). You're designing the template that will be used for the next scheduling period (typically 2-4 weeks out).

The optimization runs periodically (weekly is the sweet spot for most clinics; monthly if your patient mix is stable). Each run produces a new template configuration. A human reviews and approves it before it goes live. This human-in-the-loop step is important: optimization can produce technically optimal but operationally bizarre templates (like a 7-minute slot followed by a 52-minute slot) that providers would reject.

---

## General Architecture Pattern

```text
[Historical Data] → [Feature Engineering] → [Optimization Model] → [Simulation Validation] → [Template Output] → [Human Review] → [EHR Template Update]
```

**Historical Data Collection.** Pull visit duration actuals (check-in to checkout), no-show rates, cancellation rates, and patient arrival patterns from your scheduling and EHR systems. You need at least 6 months of data per provider to capture seasonal patterns. Group by visit type, provider, day-of-week, and time-of-day.

**Feature Engineering.** Compute the statistics your model needs: mean and variance of visit duration per type, no-show probability by time slot, late arrival distribution, and provider-specific patterns. Some providers consistently run 5 minutes over; others consistently finish early. Your model should account for provider-specific behavior, not just system-wide averages.

**Optimization Model.** Formulate and solve the mathematical program. Inputs: statistical features from the previous step plus organizational constraints (session hours, break requirements, overbooking policies). Output: optimal slot durations, buffer times, and overbooking levels.

**Simulation Validation.** Take the proposed template and simulate 1,000+ clinic days using historical arrival and duration distributions. Measure expected throughput, wait times, overtime probability, and provider idle time. Compare against the current template using the same simulation. If the proposed template doesn't meaningfully outperform the current one, don't change it. Change fatigue is real.

Note: the simulation assumes provider behavior remains constant under the new template. In practice, providers may adjust their pace in response to shorter or longer slots. Treat simulation results as directional estimates, not guarantees. The post-deployment monitoring loop is what validates whether the template actually performs as predicted.

**Human Review.** Present the proposed template alongside the simulation results to the operations team and affected providers. Show the tradeoffs explicitly: "This template sees 2 more patients per day but increases average wait time by 3 minutes." Let humans make the final call.

**EHR Integration.** Push the approved template into your scheduling system. Most EHRs support template APIs or bulk configuration. The integration is usually the least interesting technical piece but the most operationally painful one.

<!-- TODO (TechWriter): Expert review A1 (HIGH). Add a dedicated paragraph describing the post-deployment monitoring feedback loop: compare actual throughput, wait times, and overtime against simulation predictions for 1-2 weeks after go-live. If actual performance deviates beyond a threshold (e.g., wait times 50% higher than predicted), alert operations and trigger rollback to the previous template version. Keep vendor-agnostic here; place AWS-specific rollback mechanism (e.g., DynamoDB versioning) in the architecture companion. -->

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter14.01-architecture). The Python example is linked from there.

## The Honest Take

This is one of those problems where the math is the easy part. The hard part is getting people to trust the output.

I've seen optimization projects produce templates that are objectively better by every metric, and then watched them die because a provider said "I don't like having 10-minute slots, it feels rushed." The feeling matters. If a provider feels rushed, they'll run over regardless of what the template says, and your optimization is worthless. Build provider preferences into your constraints, not as an afterthought.

The overbooking piece is politically sensitive. "The computer says we should double-book the 9am slot" is a hard sell to a provider who remembers the last time they were double-booked and ran 45 minutes behind all morning. Present it as "the data shows that 9am has a 25% no-show rate, so booking one extra patient at 9am results in the expected panel size, not an overload." Framing matters enormously.

The biggest surprise: the variance in visit duration matters more than the mean. A provider whose visits are consistently 22 minutes (low variance) can be scheduled much more tightly than one whose visits range from 8 to 55 minutes (high variance), even if both have the same average. Most scheduling systems ignore variance entirely. That's where the biggest gains hide.

Start with one willing provider. Show results. Let word spread. Mandating optimized templates across a department without buy-in is a recipe for passive resistance.

---

## Related Recipes

- **Recipe 7.1 (Appointment No-Show Prediction):** Provides the no-show probability estimates that feed into the overbooking optimization
- **Recipe 12.1 (Appointment Volume Forecasting):** Forecasts demand by visit type, informing how many slots of each type to include in the template
- **Recipe 14.4 (Nurse Staffing Optimization):** Extends the single-provider model to shared resource constraints across multiple providers
- **Recipe 14.7 (OR Case Sequencing):** Applies similar sequencing optimization to surgical cases, a more complex variant of the same pattern

---

## Tags

`optimization` · `operations-research` · `scheduling` · `appointment-template` · `constraint-programming` · `mixed-integer-programming` · `simulation` · `sagemaker` · `step-functions` · `simple` · `mvp` · `hipaa`

---

*← [Chapter 14 Index](chapter14-preface) · [Next: Recipe 14.2 - Patient-Provider Assignment →](chapter14.02-patient-provider-assignment)*
