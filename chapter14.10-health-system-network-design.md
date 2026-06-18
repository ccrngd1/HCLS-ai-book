# Recipe 14.10: Health System Network Design

**Complexity:** Complex · **Phase:** Strategic Planning · **Estimated Cost:** ~$2,000–$15,000 per optimization run (compute-intensive)

---

## The Problem

A health system CEO is staring at a map with 14 hospitals, 47 ambulatory clinics, and a $400 million capital budget for the next five years. The board wants to know: Where should we build the next cancer center? Should we close the underperforming rural hospital or convert it to an urgent care? If we add cardiac surgery at the suburban campus, does that cannibalize volume from the flagship downtown, or does it capture patients currently driving to the competitor across town?

These are not questions you can answer with a spreadsheet and good intentions. They involve hundreds of interacting variables: patient travel patterns, competitor locations, demographic shifts, payer mix projections, regulatory constraints, physician recruitment pipelines, and capital depreciation schedules. Get it wrong and you've spent $200 million on a facility that never reaches volume targets. Or worse, you've closed a community hospital that was the only access point for a vulnerable population, and now you're explaining that decision to a state attorney general.

Health system network design is the problem of deciding what services to offer, where to offer them, and how much capacity to allocate at each location. It's a facility location problem, a capacity allocation problem, and a demand assignment problem all rolled into one. And it operates on a time horizon of 5 to 20 years, which means every input is uncertain.

Most health systems today make these decisions through a combination of market analysis reports, consultant recommendations, physician lobbying, and executive intuition. The results are predictably inconsistent. Some systems over-invest in competitive markets and under-invest in growth corridors. Others chase service lines with high reimbursement without considering whether they have the referral network to sustain volume. None of this replaces the judgment calls. It just makes sure those judgment calls happen on the actual tradeoffs instead of getting lost in a fog of competing anecdotes.

This is one of the hardest problems in this entire book. The solution space is enormous, the constraints are politically charged, and the objective function is genuinely multi-dimensional. Let's dig in.

---

## The Technology: Facility Location and Network Optimization

### The Core Problem Class

Health system network design belongs to a family of problems in operations research called facility location problems. The classic version: given a set of potential locations and a set of demand points, choose which locations to open and how to assign demand to them, minimizing total cost (or maximizing some coverage metric) subject to capacity constraints.

The healthcare version is considerably messier than the textbook version, but the mathematical foundation is the same. You're choosing from a discrete set of options (open this facility, close that one, add this service line, expand that capacity) subject to constraints (budget, regulatory, workforce, minimum volume thresholds) while optimizing an objective (maximize access, maximize margin, minimize patient travel, some weighted combination).

### Mixed-Integer Programming (MIP)

The workhorse technique for facility location problems is mixed-integer programming. "Mixed-integer" means the model contains both continuous variables (how much capacity to allocate, what fraction of demand to serve) and integer variables (open or closed, build or don't build). The integer variables are what make the problem hard. A continuous optimization problem with linear constraints can be solved efficiently. Add integer constraints and the problem becomes NP-hard in the general case.

In practice, modern MIP solvers (CPLEX, Gurobi, HiGHS, SCIP) use branch-and-bound algorithms with sophisticated cutting planes and heuristics that can solve problems with thousands of integer variables in reasonable time. "Reasonable" here means minutes to hours, not days. The key is formulating the problem tightly: the better your formulation (fewer unnecessary variables, tighter constraint bounds), the faster the solver converges.

For network design, the typical formulation looks something like:

**Decision variables:**
- Binary: open/close each facility, offer/don't offer each service line at each location
- Integer: capacity level at each location (often discretized into tiers)
- Continuous: patient flow from each demand zone to each facility

**Objective function:**
- Maximize net revenue (volume times margin minus fixed costs)
- Or minimize total patient travel time subject to financial viability
- Or maximize population coverage within a drive-time threshold
- Usually a weighted combination of multiple objectives

**Constraints:**
- Budget: total capital expenditure cannot exceed available funds
- Capacity: patient volume at each facility cannot exceed its capacity
- Demand: all demand must be served (or explicitly modeled as "leakage" to competitors)
- Regulatory: Certificate of Need (CON) requirements in applicable states
- Minimum volume: certain service lines require minimum annual volume to maintain quality and accreditation
- Workforce: physician and nursing availability limits what you can staff
- Network integrity: certain services require supporting services (you can't offer cardiac surgery without a cardiac ICU)

### Demand Modeling

The optimization model needs a demand forecast: how many patients of each type will seek care in each geographic zone over the planning horizon? This is where the uncertainty lives.

Demand modeling for network design typically combines:
- **Demographic projections:** Population growth, aging, migration patterns by ZIP code or census tract
- **Epidemiological trends:** Disease prevalence changes (e.g., diabetes rates rising, smoking rates falling)
- **Market share modeling:** What fraction of demand in each zone does your system capture today, and how does that change with facility placement?
- **Gravity models:** Patient choice models where the probability of choosing a facility decreases with distance and increases with facility attractiveness (reputation, service breadth, wait times)

The gravity model is particularly important. Patients don't just go to the nearest hospital. They make choices based on perceived quality, physician relationships, insurance networks, and convenience. A gravity model captures this by assigning a "utility" to each facility-patient pair and computing choice probabilities. The parameters are estimated from historical utilization data.

### Scenario Analysis and Stochastic Optimization

Because the planning horizon is long (5-20 years), point estimates of demand are unreliable. The standard approach is scenario-based optimization:

1. Define a set of plausible future scenarios (high growth, low growth, competitor entry, regulatory change)
2. Solve the optimization under each scenario
3. Identify decisions that are robust across scenarios (good in most futures) versus decisions that are scenario-dependent (great in one future, terrible in another)

More sophisticated approaches use stochastic programming, where uncertainty is modeled explicitly in the optimization formulation. The solver finds a solution that optimizes expected performance across the probability-weighted scenarios. This is computationally expensive but produces solutions that are explicitly hedged against uncertainty.

### Multi-Objective Optimization

Health system network design almost never has a single objective. The CFO wants to maximize margin. The CMO wants to maximize clinical quality (which requires minimum volumes). The community benefit officer wants to maximize access for underserved populations. The board wants to minimize competitive vulnerability.

Multi-objective optimization handles this through:
- **Weighted sum:** Combine objectives into a single score with weights reflecting priorities. Simple but requires agreeing on weights upfront.
- **Pareto frontier:** Find the set of solutions where no objective can be improved without worsening another. Present the frontier to decision-makers and let them choose. More informative but harder to compute and harder to explain.
- **Constraint-based:** Optimize one objective while constraining others to acceptable levels ("maximize margin subject to no community losing access within 30 minutes").

In practice, the constraint-based approach works best for healthcare because it maps to how decisions are actually made: "We need to hit these financial targets AND maintain these access standards AND comply with these regulations."

### Solver Selection

The choice of solver matters enormously for problems at health-system scale:

- **Commercial solvers (Gurobi, CPLEX):** Fastest for large MIP problems. Gurobi is generally considered the performance leader for mixed-integer problems. Licensing costs are significant ($10K-$50K/year) but trivial relative to the capital decisions being informed.
- **Open-source solvers (HiGHS, SCIP, CBC):** HiGHS has improved dramatically and handles many practical problems well. SCIP is strong for non-linear constraints. CBC (COIN-OR) is mature but slower on large instances.
- **Metaheuristics (genetic algorithms, simulated annealing):** Useful when the problem is too large or too non-linear for exact solvers. You give up optimality guarantees but can handle more complex objective functions and constraints. Good for initial solution exploration before refining with exact methods.

For a typical health system network design problem (50-200 potential facility-service combinations, 500-2000 demand zones, 3-5 scenarios), a commercial solver will find a near-optimal solution in 10-60 minutes. An open-source solver might take 2-6 hours for the same problem. Both are acceptable for a strategic planning exercise that runs quarterly.

### The General Architecture Pattern

```
[Data Integration] → [Demand Forecasting] → [Model Formulation] → [Optimization] → [Scenario Analysis] → [Decision Support Dashboard]
```

**Data Integration:** Pull together the inputs: current facility inventory, service line volumes, financial performance, patient origin data, demographic projections, competitor intelligence, workforce availability, capital budget constraints.

**Demand Forecasting:** Project future demand by service line and geography. This is typically a separate modeling exercise (see Chapter 12 on time series forecasting) whose outputs feed the optimizer.

**Model Formulation:** Translate the business problem into mathematical constraints and objectives. This is the intellectual core of the work and requires both OR expertise and deep healthcare domain knowledge.

**Optimization:** Feed the formulated model to a solver. Run multiple scenarios. Collect solutions.

**Scenario Analysis:** Compare solutions across scenarios. Identify robust decisions versus contingent ones. Compute sensitivity of the solution to key assumptions.

**Decision Support Dashboard:** Present results to executives in a format that supports decision-making. Maps showing proposed network configurations. Financial projections under each scenario. Access impact analysis. Comparison of alternatives.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter14.10-architecture). The Python example is linked from there.

## The Honest Take

This is the most complex recipe in this chapter, and possibly in the entire book. The mathematical formulation is the easy part. The hard parts are:

1. **Getting the data right.** Patient origin analysis requires linking claims, encounters, and geographic data across systems that were never designed to talk to each other. Budget 3-6 months just for data preparation.

2. **Calibrating the gravity model.** If your choice model doesn't match observed behavior, the optimizer will confidently recommend the wrong network configuration. Spend serious time on model validation before trusting the outputs.

3. **Managing the politics.** Every facility has a constituency. Every service line has a physician champion. The optimizer doesn't know about the board member whose family donated the land for the rural hospital. Build the tool to support "what-if" exploration, not to deliver ultimatums.

4. **Dealing with uncertainty honestly.** A 10-year demand forecast is a guess dressed up in statistics. The scenario analysis approach helps, but executives need to understand that "optimal" means "best given these assumptions," not "guaranteed to work."

The part that surprised me most: the minimum volume constraints are often the binding ones. The optimizer wants to spread services across many locations for access, but quality and accreditation requirements force concentration. This tension between access and quality is the fundamental tradeoff in network design, and no amount of optimization eliminates it. It just makes it visible.

One more thing: don't try to solve the whole problem at once on your first iteration. Start with a single service line (e.g., "where should we put our next orthopedic surgery center?") and build confidence in the approach before tackling the full multi-service network design. The single-service version is a useful deliverable on its own and teaches you where your data gaps are.

---

## Related Recipes

- **Recipe 12.5 (Hospital Census Forecasting):** Provides the demand forecasting methodology that feeds the network design optimizer
- **Recipe 14.1 (Appointment Slot Optimization):** Simpler facility-level optimization that can validate your optimization infrastructure before tackling network-scale problems
- **Recipe 14.4 (Nurse Staffing Optimization):** Workforce constraints in network design depend on staffing models; this recipe provides the staffing optimization that informs workforce availability assumptions
- **Recipe 14.6 (Patient Flow / Bed Assignment):** Operational-level optimization that runs within the network the strategic model designs
- **Recipe 7.6 (Rising Risk Identification):** Population health risk models inform demand projections for high-acuity services

---

## Tags

`optimization` · `facility-location` · `network-design` · `mixed-integer-programming` · `strategic-planning` · `capital-allocation` · `demand-forecasting` · `gravity-model` · `scenario-analysis` · `sagemaker` · `step-functions` · `quicksight` · `complex` · `hipaa`

---

*← [Recipe 14.9: Chemotherapy Scheduling](chapter14.09-chemotherapy-scheduling) · [Chapter 14 Index](chapter14-preface) · [Next: Chapter 15 →](chapter15-preface)*
