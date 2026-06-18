# Recipe 14.5: Operating Room Block Scheduling

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$200-800/month (solver compute)

---

## The Problem

Every Monday morning, the OR scheduling office is a war room. Orthopedics wants more block time because their cases keep bumping into the afternoon. Cardiothoracic is furious because their allocated blocks sit empty on Thursdays (their surgeons are in clinic). General surgery says they can fill any open slot but never gets allocated enough. The chief of surgery wants overall utilization above 75%. The CFO wants contribution margin maximized. The nurses want predictable shift patterns. Everyone has a spreadsheet proving they deserve more time.

Operating room block scheduling is the process of allocating fixed time blocks (typically half-day or full-day segments) to surgical services or individual surgeons on a repeating weekly or monthly template. Each OR in a hospital might have 10-12 blocks per week. A 20-OR hospital has 200+ blocks to assign. The allocation determines who gets access to the most expensive real estate in the hospital.

Here's why this is such a painful problem: ORs cost $30-100 per minute to operate (depending on the facility), and they sit idle roughly 20-30% of scheduled time at most hospitals. That's millions of dollars evaporating annually because the block schedule doesn't match actual demand. Meanwhile, surgeons with insufficient block time are sending cases to competitors. Under-allocated services create access bottlenecks for patients. Over-allocated services produce empty rooms that still require staffed teams on standby.

The traditional approach is a committee meeting every 6-12 months where department chairs negotiate block allocations based on historical volume, political leverage, and how loudly they complain. The result is a schedule that's outdated by the time it's implemented, unfair in ways nobody can articulate precisely, and resistant to change because any adjustment creates a loser.

This is a mathematical optimization problem pretending to be a political one. Let's make it a mathematical one for real.

---

## The Technology: Constrained Optimization for Resource Allocation

### What Is Block Scheduling Optimization?

At its core, block scheduling is a resource allocation problem. You have a fixed supply of resources (OR rooms multiplied by time blocks) and competing demand from multiple services. Each allocation decision has downstream consequences: staffing requirements, equipment availability, patient access, and financial performance. The goal is to find an allocation that satisfies a set of hard constraints (things that must be true) while optimizing one or more objectives (things we want to maximize or minimize).

This is the domain of operations research, specifically mixed-integer programming (MIP) and constraint programming (CP). These aren't machine learning techniques. They're mathematical optimization methods that have been solving logistics, scheduling, and allocation problems for decades. Airlines use them to assign crews to flights. Factories use them to schedule production runs. Hospitals should be using them for OR scheduling, but most still rely on spreadsheets and committee meetings.

### The Mathematical Formulation

Let's get concrete about what we're optimizing. The decision variables are binary: does service S get block B in room R? Yes or no. That gives us a three-dimensional assignment matrix.

**Decision variables:**

```text
x[s, r, b] = 1 if service s is assigned to room r in block b
             0 otherwise
```

**Hard constraints** (must be satisfied, no exceptions):

- Each block in each room is assigned to at most one service
- Each service gets at least its minimum guaranteed blocks (contractual obligations)
- No service exceeds its maximum capacity (staffing limits)
- Equipment-heavy specialties (cardiac, neuro) only go in equipped rooms
- Certain services cannot be adjacent (infection control: orthopedic implants and general contaminated cases in the same room on the same day is a problem)

**Soft constraints** (preferences, weighted in the objective):

- Services prefer consistent rooms (familiarity, equipment setup)
- Surgeons prefer specific days (aligned with clinic schedules)
- Back-to-back blocks for the same service reduce turnover time

**Objective function** (what we're maximizing):

```text
maximize: w1 * predicted_utilization + w2 * access_score + w3 * contribution_margin - w4 * changeover_penalty
```

Where the weights (w1, w2, w3, w4) represent institutional priorities. A hospital focused on throughput weights utilization heavily. One focused on revenue weights contribution margin. These weights are the policy decisions that leadership makes; the optimizer finds the best schedule given those priorities.

### Why This Is Hard

The naive approach (try all possible allocations, pick the best one) is computationally impossible. With 20 rooms, 10 blocks per room, and 15 services, you have 15^200 possible assignments. That's more combinations than atoms in the universe. Brute force is not an option.

Modern solvers handle this through branch-and-bound algorithms: they systematically explore the solution space while pruning branches that can't lead to better solutions than the best one found so far. A good formulation (tight constraints, strong relaxations) makes the solver converge in seconds or minutes. A bad formulation can run for hours without finding a provably optimal solution.

The other hard part isn't mathematical. It's data. To predict utilization, you need historical case volumes by service, case duration distributions, cancellation rates, and seasonality patterns. Garbage data produces a "mathematically optimal" schedule that performs terribly in practice.

### Solver Selection

There are two main families of solvers for this kind of problem:

**Mixed-Integer Programming (MIP) solvers:** Gurobi, CPLEX, COIN-OR CBC, HiGHS. These handle linear and quadratic objectives with integer variables. They provide optimality guarantees (you know how close to optimal your solution is). Commercial solvers (Gurobi, CPLEX) are dramatically faster than open-source alternatives for large problems, but the open-source options (CBC, HiGHS) work fine for most hospital-scale instances.

**Constraint Programming (CP) solvers:** Google OR-Tools CP-SAT, IBM CP Optimizer. These excel at feasibility problems (finding any solution that satisfies all constraints) and scheduling problems with complex temporal relationships. CP-SAT is particularly good for scheduling and is free.

For OR block scheduling, MIP is usually the better fit because the objective function is naturally linear (weighted sum of utilization, revenue, access scores) and the constraints are mostly linear inequalities. CP shines more for the daily case sequencing problem (Recipe 14.7) where temporal ordering matters.

### Batch vs. Real-Time Optimization

Block scheduling is fundamentally a batch problem. You're generating a template that repeats weekly or monthly, then adjusting it periodically (quarterly, or when triggered by utilization reviews). The optimization runs once, produces a schedule, and humans review and approve it.

But there's a real-time component: block release. When a surgeon doesn't fill their allocated block by a release deadline (typically 72 hours before the slot), the block becomes available to other services. Optimizing which service gets the released block requires a faster, simpler decision that runs on-demand. This is a much smaller optimization (one block, many candidates) and can use greedy heuristics or a simplified model.

The architecture needs to handle both: a heavyweight batch solver for quarterly schedule generation, and a lightweight real-time engine for daily block release decisions.

### General Architecture Pattern

```text
[Historical Data] → [Demand Forecasting] → [Constraint Builder] → [Solver] → [Schedule Output]
                                                                       ↑
                                                               [Policy Weights]
                                                               [Room Constraints]
                                                               [Service Minimums]

[Real-time Events] → [Block Release Engine] → [Assignment Decision]
```

The batch path: historical surgical volume, case duration data, and cancellation rates feed a demand forecasting module. Those forecasts, combined with institutional constraints and policy weights, feed the solver. The solver produces a proposed block template. A human reviews and approves it.

The real-time path: when a block is released (surgeon didn't fill it by deadline), a lightweight engine evaluates candidates and assigns the released time. This might use the same model with fewer variables, or a simpler rule-based approach.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter14.05-architecture). The Python example is linked from there.

## The Honest Take

Here's what nobody tells you about OR block scheduling optimization: the math is the easy part. The solver will happily produce an optimal schedule in 10 minutes. Getting institutional buy-in to actually implement it takes 6-12 months.

The utilization data will reveal uncomfortable truths. Some surgeons are using 40% of their allocated time and have been for years. Some services have blocks on days when their surgeons are in clinic and literally cannot operate. Surfacing these facts creates conflict, and the optimization project gets blamed for the conflict rather than credited for revealing the inefficiency.

My advice: start with a "what-if" tool, not a mandate. Let department chairs explore scenarios: "What happens if we move cardiothoracic from Thursday to Tuesday?" "What if we add a block for robotics?" Let them discover the tradeoffs themselves. Once they trust the model, they'll ask it to suggest the optimal schedule. That transition from "tool" to "authority" is the real deployment milestone.

The block release engine is the quick win. It's non-controversial (nobody loses their allocated blocks), immediately improves utilization, and builds trust in the optimization system. Deploy that first, measure the improvement, then use those results to justify the full scheduling overhaul.

One more thing: the 75% utilization target that every hospital uses as a benchmark is somewhat arbitrary. The "right" utilization depends on your case mix, turnover times, and tolerance for overtime. A 90% utilized OR with frequent overtime cases is not better than a 75% utilized OR that finishes on time every day. Include a utilization ceiling in your constraints, not just a floor.

**Things I'd build next if I had another quarter:**

- **Surgeon preference modeling.** The pseudocode treats services as monolithic units. In reality, individual surgeons within a service have specific day preferences (Dr. Smith operates Tuesday/Thursday; Dr. Jones does Monday/Wednesday/Friday). A production system needs surgeon-level preference data and may need to decompose the problem into service-level block allocation followed by surgeon-level assignment within blocks.
- **Seasonality handling.** Surgical volumes aren't constant. Orthopedics spikes in winter (ski injuries) and summer (elective joint replacements when people can recover before fall). A production forecasting model needs seasonal decomposition, not just rolling averages.
- **Change management workflow.** An optimization output that shows a service losing blocks requires a structured approval workflow: notification to the affected department chair, appeal period, executive sign-off. The technical system needs to integrate with your institutional governance process.
- **Integration with the scheduling system.** The block template must flow into whatever surgical scheduling application your institution uses (Epic OpTime, Cerner SurgiNet, etc.). That integration is institution-specific and often the hardest part of the project. For on-premises EHRs, deploy a private API Gateway endpoint accessible via Direct Connect or Site-to-Site VPN. For cloud-hosted EHRs, consider VPC peering with a PrivateLink endpoint.
- **Utilization drift monitoring.** Deploy a CloudWatch dashboard comparing predicted vs. actual utilization weekly. Alert if any service's actual utilization falls more than 15 percentage points below prediction for two consecutive weeks. This early-warning system lets you investigate and consider mid-quarter adjustments rather than waiting for the next quarterly review.

---

## Related Recipes

- **Recipe 14.4 (Nurse Staffing Optimization):** The block schedule drives staffing requirements; these two models should be coupled (OR schedule determines how many nurses and what specialties are needed per shift)
- **Recipe 14.7 (OR Case Sequencing):** Once blocks are allocated, sequencing individual cases within each block is the next optimization layer
- **Recipe 12.5 (Hospital Census Forecasting):** Census predictions inform whether you have enough downstream beds for your surgical volume
- **Recipe 14.1 (Appointment Slot Optimization):** Same optimization framework applied to outpatient slots rather than OR blocks

---

## Tags

`optimization` `operations-research` `mixed-integer-programming` `scheduling` `operating-room` `block-scheduling` `resource-allocation` `aws-batch` `dynamodb` `sagemaker` `eventbridge` `hipaa` `medium-complexity`

---

*← [Recipe 14.4: Nurse Staffing Optimization](chapter14.04-nurse-staffing-optimization) · [Chapter 14 Index](chapter14-preface) · [Next: Recipe 14.6: Patient Flow / Bed Assignment →](chapter14.06-patient-flow-bed-assignment)*
