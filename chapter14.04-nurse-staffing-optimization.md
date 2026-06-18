# Recipe 14.4: Nurse Staffing Optimization

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$100-200/month (solver compute)

---

## The Problem

It's 3 PM on a Thursday. The nurse manager for a 36-bed medical-surgical unit is building next week's schedule. She has 42 nurses on staff across full-time, part-time, and per-diem pools. She needs to fill 21 shifts per day (three 12-hour shifts across seven days) while respecting: union-mandated rest periods, certification requirements for charge nurse coverage, individual PTO requests, weekend rotation fairness, overtime limits, float pool availability, and the fact that three nurses just called in their two-week notice.

She's been doing this in Excel for six years. It takes her 8-12 hours every two weeks. The result is never optimal. Someone always gets shorted on their weekend rotation. Someone always ends up with back-to-back night shifts they didn't want. And when a nurse calls off sick at 5 AM, the scramble to find coverage is pure chaos: a phone tree, text messages, and whoever answers first gets voluntold.

This is not a scheduling problem. It's a constraint satisfaction problem with multiple competing objectives, and it's one of the most well-studied problems in operations research. Hospitals spend billions annually on agency and travel nurses to fill gaps that better scheduling could prevent. The American Hospital Association estimates that labor costs represent over 50% of hospital operating expenses, and nursing is the largest single component. Even a 5% improvement in schedule efficiency translates to millions in savings for a mid-size health system.

The math is genuinely hard. But the solvers are genuinely good now. Let's talk about how this works.

---

## The Technology: Constraint Optimization for Workforce Scheduling

### What Is Constraint Optimization?

At its core, nurse scheduling is a combinatorial optimization problem. You have a set of decision variables (which nurse works which shift on which day), a set of constraints (rules that must be satisfied), and one or more objective functions (things you want to maximize or minimize).

The decision variables are binary: nurse N either works shift S on day D, or she doesn't. That's a 1 or a 0. For 42 nurses across 21 shifts over 14 days, you have 42 x 21 x 14 = 12,348 binary decision variables. Each combination of assignments is a potential schedule. The number of possible schedules is 2^12,348, which is a number so large it has no physical meaning. You cannot enumerate them. You need a solver.

### Constraints: Hard vs. Soft

Constraints come in two flavors, and the distinction matters enormously for solver behavior:

**Hard constraints** are inviolable. The schedule is infeasible (illegal, unsafe, or contractually impossible) if any hard constraint is violated. Examples:

- A nurse cannot work two shifts on the same day
- Minimum 11 hours between consecutive shifts (union rule)
- At least one RN with ICU certification on every ICU shift
- No more than 60 hours per week (labor law)
- Approved PTO days are blocked

**Soft constraints** are preferences. You want to satisfy them, but violating them doesn't make the schedule illegal. Instead, each violation incurs a penalty in the objective function. Examples:

- Nurses prefer not to work more than 3 consecutive days
- Weekend shifts should be distributed fairly across staff
- Nurses prefer their historical shift pattern (days vs. nights)
- Minimize split weekends (working Saturday but not Sunday or vice versa)

The art of nurse scheduling is in the formulation: deciding which constraints are hard (non-negotiable) and which are soft (penalized), and calibrating the penalty weights so the solver produces schedules that humans actually accept.

### The Objective Function

What are you optimizing for? This is where it gets political. Common objectives include:

- **Minimize cost:** Prefer regular staff over overtime, overtime over agency
- **Maximize fairness:** Distribute undesirable shifts (nights, weekends, holidays) equitably
- **Maximize preference satisfaction:** Give nurses the shifts they want
- **Minimize understaffing risk:** Build in buffer for expected call-offs

These objectives conflict. The cheapest schedule is rarely the fairest. The fairest schedule rarely maximizes individual preferences. You need a weighted combination, and those weights encode organizational values. Getting stakeholders to agree on weights is often harder than building the solver.

### Solver Technologies

Three main approaches exist for this class of problem:

**Mixed-Integer Programming (MIP).** The gold standard for constraint optimization. You formulate the problem as a linear (or integer) program and hand it to a solver like CPLEX, Gurobi, or the open-source CBC/HiGHS. MIP solvers use branch-and-bound algorithms with sophisticated cutting planes and heuristics. For nurse scheduling problems of typical hospital size (50-200 nurses, 2-4 week horizons), modern MIP solvers find near-optimal solutions in seconds to minutes. The advantage: you get a provable optimality gap (the solver tells you how close to optimal your solution is). The disadvantage: formulating the problem correctly requires expertise, and some constraint types (like "fairness over a rolling 6-month window") are hard to express linearly.

**Constraint Programming (CP).** An alternative paradigm that's particularly good at feasibility problems (finding any valid schedule) and problems with complex logical constraints. CP solvers like Google OR-Tools' CP-SAT use propagation and search techniques that handle "if-then" constraints more naturally than MIP. For nurse scheduling, CP shines when you have many hard constraints and just need a feasible schedule quickly. It's less natural for optimizing a weighted objective, but modern CP solvers (especially CP-SAT) handle optimization well.

**Metaheuristics.** Simulated annealing, genetic algorithms, tabu search. These don't guarantee optimality but can handle problem formulations that are difficult to express mathematically. They're useful when the constraint structure is too complex for MIP/CP, or when you need to incorporate custom evaluation functions. The downside: no optimality guarantee, and tuning the metaheuristic parameters is its own art.

For most hospital nurse scheduling problems, MIP or CP-SAT is the right choice. The problems are well-structured enough to formulate cleanly, and the solvers are fast enough for interactive use.

### Batch vs. Real-Time Optimization

Nurse scheduling has two distinct operational modes:

**Batch scheduling** generates the baseline schedule 2-4 weeks in advance. This is the "build the schedule" problem. You have time (minutes to hours of solver runtime are acceptable), full information about staff availability, and the luxury of human review before publishing. Batch scheduling runs once per scheduling period.

**Real-time reoptimization** handles disruptions: call-offs, census spikes, patient acuity changes. A nurse calls in sick at 5 AM. You need to find coverage within minutes, not hours. The solver needs to run in seconds, respect the existing schedule as much as possible (minimize disruption), and produce actionable recommendations (who to call, in what order). Real-time mode is harder because the solution space is smaller (most nurses are already committed) and the time budget is tighter.

A production system needs both. The batch solver builds the plan. The real-time solver adapts it.

### Why This Is Hard in Healthcare Specifically

Generic workforce scheduling is a solved problem in many industries (airlines, retail, call centers). Healthcare adds layers:

**Skill mix requirements.** It's not enough to have "a nurse" on every shift. You need specific certifications: charge nurse capability, IV certification, telemetry competency, specific unit experience. The constraint isn't just "fill the slot" but "fill the slot with someone qualified for what that slot requires."

**Patient acuity variability.** The number of nurses you need isn't fixed. It depends on patient census and acuity. A unit with 30 patients at acuity level 2 needs different staffing than 30 patients at acuity level 4. Staffing ratios (mandated in some states like California) add hard constraints that vary by unit type.

**Union and labor rules.** Healthcare unions have detailed collective bargaining agreements governing scheduling: mandatory rest periods, overtime rules, weekend rotation requirements, seniority-based shift selection, mandatory low-census days. These rules are complex, vary by facility, and are non-negotiable.

**Human factors.** Nurses are not interchangeable resources. They have relationships with patients, familiarity with unit workflows, and preferences that affect retention. A mathematically optimal schedule that ignores human factors will drive turnover, which costs far more than the optimization saved.

---

## General Architecture Pattern

The conceptual pipeline for nurse staffing optimization:

```text
[Data Collection] → [Demand Forecasting] → [Constraint Formulation] → [Solver Execution] → [Schedule Publication] → [Real-Time Adjustment]
```

**Data Collection.** Gather the inputs: staff roster (names, certifications, FTE status, contract hours), availability (PTO, restrictions, preferences), historical patterns (typical call-off rates, seasonal volume), and unit requirements (minimum staffing by shift, skill mix needs). This data lives across multiple systems: HR/payroll, the EHR (for census/acuity), time-and-attendance, and often a separate scheduling application. Staff preference data (which may include sensitive personal information like medical restrictions or childcare constraints) should be stored with tighter access controls than the general roster and treated as ephemeral: delete assembled problem definitions containing preferences after the solver completes.

**Demand Forecasting.** Predict how many nurses you'll need per unit per shift. This combines historical census patterns, known admissions (scheduled surgeries), seasonal trends, and day-of-week effects. The forecast drives the "demand" side of the optimization. See Recipe 12.5 (Hospital Census Forecasting) for the forecasting component. If the forecasting service is unavailable (or during initial deployment before sufficient history exists), fall back to a static staffing matrix based on unit type and historical averages (e.g., "med-surg 36-bed unit: 7 day / 6 evening / 5 night as baseline"). Store this fallback as configuration.

**Constraint Formulation.** Translate business rules, labor agreements, and preferences into mathematical constraints. This is the intellectual core of the system. Each rule becomes an equation or inequality that the solver must respect. The formulation must be maintained as rules change (new union contract, new state regulation, new unit opening).

**Solver Execution.** Feed the formulated problem to an optimization engine. For batch scheduling, allow minutes of runtime and aim for near-optimal solutions. For real-time adjustments, constrain runtime to seconds and accept good-enough solutions.

**Schedule Publication.** Present the generated schedule to the nurse manager for review, allow manual adjustments (the solver doesn't know about the interpersonal conflict between Nurse A and Nurse B), and publish to staff. Track which adjustments were made manually; these are signals for improving the model. Manual overrides should flow through the same event bus as automated assignments, with a distinct event type capturing who made the change, what was changed, and the stated reason.

**Real-Time Adjustment.** When disruptions occur (call-offs, census spikes, patient transfers), re-run the solver with the current state as a starting point. Minimize changes to the existing schedule. Produce ranked recommendations for coverage (who to call, in what order). Use concurrency control (optimistic locking or transactions) to prevent race conditions when multiple disruptions arrive simultaneously.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter14.04-architecture). The Python example is linked from there.

## The Honest Take

Here's what surprised me about nurse scheduling optimization in practice:

The math is the easy part. Seriously. Formulating the model and running the solver is maybe 20% of the effort. The other 80% is data integration (getting accurate, timely staff availability from three different systems that don't talk to each other), change management (convincing nurse managers to trust a computer's schedule over their own judgment), and constraint maintenance (updating the model every time the union contract changes or a new state regulation takes effect).

The fairness objective is where you'll spend the most political capital. "Fair" means different things to different people. Is it fair that the new hire gets more weekends because senior nurses have seniority preference? Is it fair that part-time nurses get proportionally fewer undesirable shifts? You'll need a governance process for objective weight decisions, and you'll need to be transparent about how the weights work.

The solver will sometimes produce schedules that are mathematically optimal but humanly unacceptable. Two nurses who don't work well together assigned to the same shift. A nurse assigned to a unit she technically has credentials for but hasn't worked in two years. The model doesn't know about interpersonal dynamics or practical competency decay. Build a manual override mechanism and track overrides as training data for future model improvements.

Real-time reoptimization is where the value really shows up. The batch schedule is nice, but every hospital already has some scheduling process (even if it's Excel). The killer feature is the 5 AM call-off response: ranked candidates, automatic notifications, acceptance tracking. That's where you save the nurse manager from the phone tree and the agency nurse call.

Start with a single unit. Prove it works. Then expand. Trying to optimize across an entire hospital on day one is a recipe for a failed project.

---

## Related Recipes

- **Recipe 12.5 (Hospital Census Forecasting):** Provides the demand forecast that drives staffing requirements
- **Recipe 14.1 (Appointment Slot Optimization):** Uses similar constraint optimization techniques for a simpler scheduling domain
- **Recipe 14.5 (Operating Room Block Scheduling):** Another resource allocation problem with competing stakeholders and complex constraints
- **Recipe 14.6 (Patient Flow / Bed Assignment):** Real-time optimization that interacts with staffing (census changes drive staffing needs)
- **Recipe 7.7 (Length of Stay Prediction):** Feeds discharge predictions that affect next-day staffing requirements

---

## Tags

`optimization` · `operations-research` · `constraint-programming` · `nurse-scheduling` · `workforce-management` · `mixed-integer-programming` · `real-time` · `sagemaker` · `lambda` · `dynamodb` · `eventbridge` · `medium` · `hipaa`

---

*← [Recipe 14.3: Inventory Reorder Optimization](chapter14.03-inventory-reorder-optimization) · [Chapter 14 Index](chapter14-preface) · [Next: Recipe 14.5 - Operating Room Block Scheduling →](chapter14.05-operating-room-block-scheduling)*
