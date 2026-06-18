# Recipe 14.7: OR Case Sequencing

**Complexity:** Medium-Complex · **Phase:** Production · **Estimated Cost:** ~$200-800/month (solver compute)

---

## The Problem

It's 5:45 AM at a 20-OR hospital. The charge nurse is staring at today's surgical schedule: 47 cases across 12 rooms. The orthopedic surgeon wants his total knee first because "the patient needs to be in recovery by noon." The cardiac team needs Room 4 because it's the only one with the perfusion setup. Two cases need the same robotic system. The anesthesiologist covering rooms 6 through 9 has a hard stop at 3 PM. And someone just called in a semi-urgent appendectomy that needs to fit somewhere before lunch.

This is OR case sequencing: deciding not just which cases happen today, but in what order, in which rooms, and at what times. It's a puzzle that perioperative teams solve manually every single day, usually starting at 4 AM, usually with a whiteboard and a lot of phone calls.

The cost of getting it wrong is real. A poorly sequenced day means turnover gaps where rooms sit empty between cases (each minute of unused OR time costs $30-60 depending on the facility). It means the 3 PM case that was supposed to be a 90-minute procedure starts at 4:15 because everything upstream ran long, and now you're paying overtime for the entire surgical team. It means the equipment conflict nobody caught until the patient was already prepped.

Most hospitals run their ORs at 60-70% utilization. The theoretical ceiling with perfect sequencing is closer to 80-85% (you can't hit 100% because of mandatory turnover time and inherent duration uncertainty). That gap between actual and achievable utilization represents millions in lost revenue annually for a mid-size hospital. Not because the cases aren't there, but because the sequence is suboptimal.

The manual approach works. It has worked for decades. But it works the way a human playing chess works: by pattern recognition and heuristics, not by evaluating all possible arrangements. A 12-room, 47-case day has a combinatorial space that no human can fully explore. Optimization can.

---

## The Technology: Combinatorial Optimization for Scheduling

### What Is Combinatorial Optimization?

At its core, OR case sequencing is a constrained scheduling problem. You have a set of jobs (surgical cases), a set of machines (operating rooms), and a set of constraints (equipment availability, staff schedules, surgeon preferences, patient medical requirements). You want to find an assignment and ordering that optimizes some objective (minimize total idle time, minimize overtime, maximize throughput, or some weighted combination).

This falls squarely into the domain of combinatorial optimization, specifically a variant of the job-shop scheduling problem. The "combinatorial" part means the number of possible solutions grows factorially with the number of cases. Ten cases in one room have 10! = 3.6 million possible orderings. Forty-seven cases across twelve rooms? The solution space is astronomically large.

### How Solvers Work

You don't enumerate all possibilities. Instead, you formulate the problem mathematically and hand it to a solver, a piece of software designed to find optimal (or near-optimal) solutions to these kinds of problems efficiently.

There are two main families of solvers:

**Mixed-Integer Programming (MIP) solvers.** These formulate the problem as a set of linear equations with some variables constrained to be integers (typically 0 or 1, representing "yes this case goes in this slot" or "no it doesn't"). The solver uses branch-and-bound algorithms to systematically explore the solution space, pruning branches that can't possibly beat the best solution found so far. Commercial MIP solvers (Gurobi, CPLEX) are remarkably good at this. They can prove optimality: "this is the best possible solution given your constraints." Open-source options (COIN-OR CBC, HiGHS, SCIP) are capable but slower on large instances.

**Constraint Programming (CP) solvers.** These are particularly well-suited to scheduling problems because they natively understand concepts like "this task must come before that task" and "these two tasks can't overlap on the same resource." CP solvers use propagation and search: they infer consequences of partial assignments (if case A is in room 3 at 8 AM, then case B can't be in room 3 until at least 10:30 AM) and use those inferences to prune the search space. Google's OR-Tools CP-SAT solver is excellent and free.

**Metaheuristics.** For very large instances or when you need a good solution fast (real-time replanning), metaheuristics like simulated annealing, genetic algorithms, or large neighborhood search can find high-quality solutions without guaranteeing optimality. They're the "good enough in 5 seconds" option when the MIP solver would take 20 minutes.

### The Constraint Formulation

The art of OR case sequencing isn't choosing a solver. It's formulating the constraints correctly. Here's what a typical formulation includes:

**Decision variables:**
- Which room is each case assigned to?
- What position in the sequence does each case occupy within its room?
- What is the start time of each case?

**Hard constraints (must be satisfied):**
- No two cases overlap in the same room
- Turnover time between consecutive cases in the same room (typically 20-45 minutes depending on case type)
- Equipment availability: if two cases need the same robot, they can't overlap
- Staff availability windows: the anesthesiologist covering rooms 6-9 is only available until 3 PM
- Room capability: cardiac cases can only go in rooms with bypass capability
- Patient medical constraints: "this patient must be first case of the day" (NPO requirements, pediatric cases, immunocompromised patients needing sterile-first rooms)

**Soft constraints (preferences, penalized if violated):**
- Surgeon sequence preferences ("I want my complex case first while I'm fresh")
- Minimize total overtime across all rooms
- Minimize maximum overtime in any single room (fairness)
- Group similar cases to reduce turnover time (two knee replacements back-to-back need less room reconfiguration than a knee followed by a craniotomy)
- Minimize patient wait time from scheduled arrival to OR entry

**Objective function:** Typically a weighted sum of soft constraint violations plus utilization metrics. The weights encode institutional priorities: "we care more about avoiding overtime than about surgeon preferences" or vice versa.

### Duration Uncertainty: The Hard Part

Here's where OR case sequencing gets genuinely difficult. Case durations are uncertain. A "90-minute" total knee replacement might take 70 minutes or 130 minutes depending on patient anatomy, complications, and how the surgeon's morning is going. This uncertainty propagates through the sequence: if case 1 runs 30 minutes long, every subsequent case in that room shifts.

There are three approaches to handling this:

**Deterministic with buffers.** Use expected durations plus a safety margin. Simple, but either too conservative (wasted time) or too aggressive (frequent overruns). Most manual scheduling works this way.

**Stochastic optimization.** Model durations as probability distributions (typically lognormal for surgical cases) and optimize the expected value of the objective. More sophisticated, but computationally expensive and requires good historical data to fit the distributions.

**Robust optimization.** Find a schedule that performs well across a range of duration scenarios, not just the expected case. This is the "minimax regret" approach: minimize the worst-case outcome. Conservative but resilient.

For most implementations, deterministic with intelligent buffers (based on historical variance per procedure type and surgeon) is the pragmatic starting point. Graduate to stochastic methods once you have solid duration prediction models (see Recipe 7.7: Length of Stay Prediction for related techniques).

### Batch vs. Real-Time Optimization

Two distinct operational modes:

**Batch (overnight planning).** Run the full optimization the evening before or early morning. Takes the confirmed case list, applies all constraints, and produces the day's schedule. Can afford to run for minutes because there's no one waiting. This is where MIP solvers shine: give them 5-10 minutes and they'll find a provably optimal or near-optimal solution.

**Real-time (intraday replanning).** A case cancels at 9 AM. An emergency add-on arrives at 11 AM. A case runs 45 minutes over. The morning's optimal schedule is now suboptimal or infeasible. You need a new plan in seconds, not minutes. This is where metaheuristics or warm-started CP solvers earn their keep: take the current state, fix what's already happened, and re-optimize the remainder.

Most production systems need both: batch for the initial plan, real-time for adjustments throughout the day.

---

## General Architecture Pattern

```
[Case Data] → [Constraint Builder] → [Solver Engine] → [Schedule Output]
     ↑                                                        ↓
[Duration Models] ← [Historical Data]              [Visualization / Alerts]
     ↑                                                        ↓
[Real-time Events] → [Replan Trigger] → [Warm-start Solver] → [Updated Schedule]
```

**Data ingestion layer.** Pulls the case list from the surgical scheduling system (typically via HL7 or FHIR integration with the EHR). Enriches each case with: estimated duration (from historical models), equipment requirements (from preference cards), staff assignments, room constraints, and patient-specific requirements.

**Constraint builder.** Translates business rules into mathematical constraints. This is the layer that encodes "Dr. Smith only operates in rooms 1-4" and "the da Vinci robot needs 30 minutes of setup between cases" into the solver's language. Separating constraint definition from the solver itself is critical: business rules change frequently, and you don't want to rewrite solver code every time a new surgeon joins.

**Solver engine.** The optimization core. Accepts the constraint model and produces an optimal or near-optimal schedule. Should support both batch mode (full optimization from scratch) and warm-start mode (fix completed cases, re-optimize the rest).

**Schedule output and visualization.** The optimized schedule needs to be consumable by humans (perioperative coordinators, charge nurses, surgeons) and by systems (EHR, patient tracking boards, equipment management). A Gantt-style visualization showing rooms on the Y-axis and time on the X-axis is the standard display.

**Replan trigger.** Monitors real-time events (case completions, cancellations, add-ons, duration overruns) and decides when to trigger re-optimization. Not every event needs a full replan. A case finishing 5 minutes early doesn't warrant disruption. A case finishing 45 minutes late, or a cancellation that frees a room, does.

**Human override layer.** Any production scheduling system must support manual overrides. Charge nurses and surgeons need the ability to lock a case to a specific room or time slot, swap two cases within a room, or exclude a room from re-optimization entirely. Overrides are stored as hard constraints that the solver respects on subsequent runs. The dashboard should visually distinguish optimizer-assigned slots from manually-locked slots, and an audit trail records who overrode what and when.

<!-- TODO (TechWriter): Expert review A3 (HIGH). Expand human override into a full subsection in the Code walkthrough showing how overrides are stored as fixed constraints in DynamoDB and read by the solver. Include role-based permissions (charge nurse can override, random staff cannot). -->

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter14.07-architecture). The Python example is linked from there.

## The Honest Take

The optimization itself is the easy part. Getting a solver to produce a good schedule from well-formulated constraints is a solved problem in operations research. The hard parts are everything around it.

**Duration prediction is where you live or die.** If your predicted durations are systematically wrong (and they will be, initially), the optimized schedule is fiction. Invest heavily in duration modeling before you invest in fancy solver techniques. A simple heuristic scheduler with accurate durations will outperform an optimal solver with bad duration estimates every time.

**Surgeon buy-in is non-negotiable.** Surgeons who feel the system is dictating their schedule will simply ignore it. The successful implementations I've seen treat surgeon preferences as near-hard constraints initially, then gradually demonstrate value by showing "your cases finished 30 minutes earlier because we sequenced them better." Start by optimizing within their preferences, not against them.

**The replan frequency tradeoff is real.** Replan too often and the schedule feels unstable (staff hate constant changes). Replan too rarely and you're running a suboptimal schedule all afternoon because of a morning disruption. Most teams settle on replanning only when deviation exceeds 15-20 minutes or when a cancellation/add-on occurs.

**Turnover time is where the real gains hide.** Most people focus on case duration optimization, but the 25-45 minutes between cases is where utilization is actually lost. Sequencing similar cases back-to-back (same equipment, same setup) can shave 5-10 minutes per turnover. Over a 6-case room day, that's 30-60 minutes of recovered time.

**Failure handling matters more than optimality.** When the solver fails (and it will: infeasible constraints, OOM on large instances, network timeouts), the system must fall back gracefully to the previous valid schedule and alert the perioperative coordinator. A DLQ on the replan queue with a CloudWatch alarm ensures that silent failures don't leave the OR running on a stale schedule all day.

The thing that surprised me most: the constraint that causes the most infeasibility isn't equipment or rooms. It's anesthesia coverage. When one anesthesiologist covers multiple rooms, their availability window becomes the binding constraint on the entire schedule. Model this carefully.

---

## Related Recipes

- **Recipe 14.4 (Nurse Staffing Optimization):** The staff schedules that constrain OR sequencing are themselves an optimization output
- **Recipe 14.5 (OR Block Scheduling):** Block allocation determines which services have access to which rooms; sequencing operates within those blocks
- **Recipe 14.6 (Patient Flow / Bed Assignment):** Downstream bed availability constrains OR throughput; these systems should communicate
- **Recipe 7.7 (Length of Stay Prediction):** Duration prediction techniques applicable to surgical case duration modeling
- **Recipe 12.5 (Hospital Census Forecasting):** Census forecasts inform whether add-on cases can be accommodated

---

## Tags

`optimization` · `operations-research` · `scheduling` · `constraint-programming` · `mixed-integer-programming` · `operating-room` · `surgical` · `real-time` · `ecs-fargate` · `eventbridge` · `dynamodb` · `hipaa`

---

*← [Recipe 14.6: Patient Flow / Bed Assignment](chapter14.06-patient-flow-bed-assignment) · [Chapter 14 Index](chapter14-preface) · [Next: Recipe 14.8: Ambulance Routing and Dispatch →](chapter14.08-ambulance-routing-dispatch)*
