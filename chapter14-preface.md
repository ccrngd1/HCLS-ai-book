# Chapter 14 Preface — When "Good Enough" Scheduling Costs Lives

Every hospital I've ever worked with has a whiteboard somewhere. Usually in a charge nurse's office, or tucked behind the OR front desk, or taped to the wall in a supply closet that doubles as a staffing coordination room. On that whiteboard is a schedule. And that schedule was built by a human being who spent hours juggling constraints in their head, making trade-offs they couldn't fully articulate, and arriving at a solution that is technically feasible but almost certainly not optimal.

Here's what gets me about this: the math to do it better has existed since the 1940s. Linear programming, constraint satisfaction, integer optimization. These aren't new ideas. George Dantzig published the simplex method in 1947. The operations research community has been solving scheduling, routing, and allocation problems for decades. Airlines use it. Logistics companies use it. Manufacturing plants use it.

Healthcare, by and large, does not.

And the cost of that gap isn't just inefficiency. It's a nurse working her sixth consecutive night shift because the scheduler couldn't find a feasible alternative. It's an OR sitting empty for 90 minutes between cases because nobody optimized the sequencing. It's an ambulance dispatched to the wrong hospital because the dispatcher didn't have real-time capacity visibility. It's a cancer patient waiting three extra days for chemo because the infusion chair schedule couldn't accommodate their protocol timing.

This chapter is about closing that gap.

---

## What Operations Research Actually Is

Operations research (OR) is the discipline of using mathematical models to make better decisions about how to allocate scarce resources. That's it. Strip away the academic jargon and OR is just: "given these constraints and this objective, what's the best thing to do?"

The "operations" part comes from its military origins (it was literally developed to optimize military operations in World War II), but the "research" part is slightly misleading. This isn't research in the academic sense of "we're exploring unknowns." It's research in the engineering sense of "we're rigorously analyzing a system to find the best configuration." Think of it as applied mathematics for decision-making.

In healthcare, the decisions OR helps with are things like:

- **Scheduling:** Who works when? Which patient gets which appointment slot? What order do we run OR cases?
- **Assignment:** Which nurse covers which patients? Which bed does this admission go to? Which provider takes new patients?
- **Routing:** Which ambulance responds to this call? What's the fastest path considering traffic? Which hospital should we transport to?
- **Inventory:** When do we reorder supplies? How much safety stock do we hold? How do we handle items that expire?
- **Network design:** Where should we build a new clinic? Which service lines belong at which facilities? How do we allocate capacity across a system?

The common thread: all of these involve choosing from a large (often astronomically large) set of possible solutions, subject to constraints that must be satisfied, while trying to maximize or minimize some objective.

---

## Why Healthcare Is Both Perfect and Terrible for Optimization

Healthcare is a perfect candidate for optimization because it's drowning in constrained resource allocation problems. Every day, every hospital makes thousands of decisions about who gets what resource, when, and in what order. The constraints are real and hard: you can't schedule a nurse for more than X consecutive hours; you can't put an isolation patient in a shared room; you can't run a case without the right equipment sterilized and available.

Healthcare is a terrible candidate for optimization because the data is messy, the constraints are often unwritten, the objectives are politically contested, and the humans in the loop have strong opinions about how things should work.

Let me unpack that tension, because it's the central challenge of every recipe in this chapter.

### The Data Problem

Optimization models need parameters: how long does a knee replacement take? What's the demand for infusion chairs on Tuesdays? How many nurses with ICU certification are available next week? In theory, your EHR and scheduling systems have this data. In practice, it's scattered across systems, inconsistently recorded, and often wrong. Case duration estimates are notoriously optimistic. Demand forecasts assume last year's patterns hold. Staff availability changes daily with call-offs and float requests.

Every optimization system in healthcare needs a robust data pipeline feeding it, and that pipeline needs to handle uncertainty gracefully. You're not optimizing against perfect information; you're optimizing against noisy estimates. The models that work in production are the ones that acknowledge this explicitly.

### The Unwritten Constraints Problem

Here's something that will bite you if you're not careful: the formal constraints (labor laws, certification requirements, room capabilities) are only half the story. The other half is informal constraints that nobody wrote down but everyone knows. Dr. Smith always operates on Tuesdays. The night shift nurses on 4 West don't like being split across pods. The OR charge nurse always keeps Room 7 open for emergencies even though there's no policy requiring it.

If your optimization model produces a "mathematically optimal" schedule that violates these unwritten rules, it will be rejected immediately. Not because it's wrong, but because it doesn't account for the full constraint set. The most successful implementations I've seen spend as much time on constraint discovery (talking to the humans who currently make these decisions) as they do on model building.

### The Multi-Objective Problem

"Optimize the schedule" sounds simple until someone asks: optimize for what? Minimize cost? Maximize throughput? Minimize wait times? Maximize staff satisfaction? Ensure equitable workload distribution? These objectives frequently conflict. The cheapest schedule might burn out your best nurses. The highest-throughput OR schedule might leave no buffer for emergencies. The most equitable assignment might not match patients to the best-qualified providers.

Real healthcare optimization is almost always multi-objective, which means you're not finding "the answer." You're finding a set of trade-offs and helping decision-makers choose among them. This is a fundamentally different user experience than "the computer tells you what to do." It's "the computer shows you three good options and explains what you're giving up with each one."

---

## The Solver Landscape (A Quick Tour)

If you're new to optimization, the landscape of solution approaches can feel overwhelming. Here's a practical taxonomy of what you'll encounter in this chapter, ordered roughly from simplest to most complex.

### Linear Programming (LP)

The workhorse. You have a linear objective function (minimize cost, maximize utilization) subject to linear constraints (total hours ≤ 40, demand ≥ supply). The simplex method or interior-point methods solve these efficiently, even at large scale. If your problem can be formulated as an LP, you're in good shape: solutions are fast, provably optimal, and well-understood.

Healthcare examples: basic staffing models, simple resource allocation, diet optimization (yes, really, that's one of the original LP applications).

### Integer Programming (IP) and Mixed-Integer Programming (MIP)

The real world is full of discrete decisions: you either assign a nurse to a shift or you don't. You can't assign 0.7 of a nurse. Integer programming handles these binary and integer decision variables. The trade-off: IP problems are NP-hard in general, meaning solve times can explode as problem size grows. Modern solvers (Gurobi, CPLEX, open-source alternatives like HiGHS and SCIP) are remarkably good at finding optimal or near-optimal solutions for practical problem sizes, but you need to be aware of computational limits.

Healthcare examples: nurse scheduling, OR block allocation, patient-to-bed assignment.

### Constraint Programming (CP)

Instead of optimizing an objective, constraint programming focuses on finding any feasible solution that satisfies all constraints. It's particularly good at problems with complex logical constraints ("if nurse A works Monday, she can't work Tuesday" or "these two patients can't share a room"). CP solvers use techniques like backtracking and constraint propagation that are different from LP/IP solvers but complementary.

Healthcare examples: complex scheduling with many logical rules, resource allocation with compatibility constraints.

### Metaheuristics

When your problem is too large or too complex for exact solvers to handle in reasonable time, metaheuristics offer approximate solutions. These include genetic algorithms, simulated annealing, tabu search, and ant colony optimization. They don't guarantee optimality, but they find good solutions quickly. The trade-off is tuning: metaheuristics have parameters (population size, cooling schedule, tabu tenure) that require experimentation.

Healthcare examples: large-scale nurse rostering, ambulance fleet positioning, network design problems.

### Simulation-Based Optimization

Some healthcare problems have too much stochasticity (randomness) to model analytically. How long will this surgery actually take? Will that patient show up? Will we get three admissions or thirty in the next hour? Simulation-based approaches run thousands of scenarios, evaluate candidate solutions against the distribution of outcomes, and iteratively improve. Discrete-event simulation paired with optimization is particularly powerful for healthcare operations.

Healthcare examples: ED staffing under demand uncertainty, OR scheduling with variable case durations, capacity planning.

---

## Why This Is Getting Practical Now

If the math has existed since the 1940s, why is healthcare optimization becoming practical now? A few converging factors:

**Cloud compute makes solvers accessible.** Running a large MIP model used to require expensive on-premises hardware and commercial solver licenses that cost tens of thousands of dollars per year. Now you can spin up a compute instance, run an optimization, and tear it down. Open-source solvers have gotten dramatically better. You don't need a PhD in operations research to formulate and solve practical problems anymore.

**Data integration is (slowly) improving.** EHR systems, scheduling platforms, and workforce management tools are increasingly exposable via APIs. The data pipeline problem hasn't gone away, but it's more tractable than it was a decade ago. FHIR is helping on the clinical side. Modern data platforms make it easier to aggregate the inputs that optimization models need.

**Decision-makers are ready.** COVID broke a lot of healthcare operations teams' confidence in manual scheduling and allocation. When your census swings wildly, your staff is calling off unpredictably, and your supply chain is disrupted, the whiteboard approach doesn't scale. There's genuine appetite for tools that can reoptimize quickly as conditions change.

**The "good enough" bar has risen.** Healthcare margins are thin and getting thinner. The difference between 70% OR utilization and 82% OR utilization is millions of dollars annually for a mid-size hospital. The difference between optimal and suboptimal nurse scheduling is burnout, turnover, and agency spend. The financial case for optimization has never been stronger.

---

## What This Chapter Covers

The recipes in this chapter progress from simple, well-bounded optimization problems to complex, multi-stakeholder network design challenges. Here's the arc:

**Recipes 14.1-14.2** start with straightforward assignment and allocation problems. Appointment slot optimization and patient-provider assignment have clean objective functions, manageable constraint sets, and can deliver value quickly. These are your "prove the concept" implementations.

**Recipes 14.3-14.5** move into medium-complexity territory. Inventory optimization introduces uncertainty (demand variability, lead times). Nurse staffing adds complex labor constraints and fairness objectives. OR block scheduling brings political dynamics and competing stakeholder interests. These are the problems where you'll spend as much time on change management as on model building.

**Recipes 14.6-14.7** tackle dynamic, real-time optimization. Patient flow and OR case sequencing require models that reoptimize as conditions change throughout the day. The state space is large, decisions are time-sensitive, and the system never reaches steady state. This is where simulation-optimization hybrids shine.

**Recipes 14.8-14.9** address complex operational problems with life-safety implications. Ambulance routing involves real-time decisions under uncertainty with direct patient impact. Chemotherapy scheduling layers clinical protocol constraints on top of operational optimization. The stakes are higher and the tolerance for suboptimal solutions is lower.

**Recipe 14.10** is the capstone: health system network design. This is strategic optimization over a multi-year horizon, involving capital allocation, demand forecasting, competitive dynamics, and regulatory constraints. It's the hardest problem in the chapter and the one with the longest payback period.

---

## The Honest Setup

I want to be upfront about something: optimization in healthcare is as much a people problem as a math problem. The best model in the world is worthless if the charge nurse ignores its output. The most elegant formulation fails if it doesn't capture the constraints that actually matter to the humans making decisions.

Every recipe in this chapter includes a section on adoption and change management, because I've seen too many technically brilliant optimization projects die on the vine because they were built by people who understood solvers but didn't understand how healthcare operations actually work.

The other thing I'll be honest about: not every problem in this chapter needs a sophisticated solver. Sometimes a well-designed heuristic (a set of rules that produces good-enough solutions quickly) outperforms an optimal solver that takes too long to run or requires data you don't have. I'll call out where simpler approaches might be the right starting point, and where the full optimization machinery is genuinely worth the investment.

Let's start with the simplest version of the problem: making appointment slots work better.

---

*→ [Recipe 14.1 — Appointment Slot Optimization](chapter14.01-appointment-slot-optimization)*

## Further Reading

- [Introduction to Linear Optimization](https://www.athenasc.com/linoptbook.html) by Bertsimas and Tsitsiklis — the standard graduate text on LP and its extensions
- [HiGHS](https://highs.dev/) — high-performance open-source solver for LP, MIP, and QP problems
- [Google OR-Tools](https://developers.google.com/optimization) — open-source optimization toolkit with constraint programming, routing, and scheduling solvers
- [INFORMS Healthcare](https://www.informs.org/Explore/Healthcare) — the professional society for operations research, with a dedicated healthcare applications community
