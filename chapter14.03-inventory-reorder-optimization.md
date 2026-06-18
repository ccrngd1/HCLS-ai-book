# Recipe 14.3: Inventory Reorder Optimization

**Complexity:** Simple-Medium · **Phase:** Production · **Estimated Cost:** ~$50-200/month (batch optimization for mid-size hospital)

---

## The Problem

There's a supply closet on every hospital floor. Inside it, someone has taped a handwritten note to the shelf: "Reorder when down to 2 boxes." That note was written by a nurse who got burned once by running out of IV start kits on a Friday night. The reorder point is based on gut feel, not math. The order quantity is whatever fits in the cabinet.

Now multiply that across 3,000 to 15,000 SKUs in a typical hospital's supply chain. Surgical gloves, catheter kits, contrast dye, implantable devices, medications with 90-day shelf lives, reagents that expire in 30 days. Each item has different demand patterns, different lead times from distributors, different costs, and wildly different consequences for running out.

The financial stakes are real. Healthcare supply chain costs represent 30-40% of a hospital's operating budget (second only to labor). Overstocking ties up capital and creates waste through expiration. Understocking creates clinical risk: a stockout of a critical surgical supply can delay procedures, extend patient stays, or force expensive emergency orders at premium pricing. The sweet spot between "too much" and "not enough" is narrow, and it shifts constantly with patient volume, seasonal patterns, and supply chain disruptions.

Most health systems today use one of two approaches: min/max levels set manually by materials managers (the "gut feel plus spreadsheet" method), or basic ERP reorder points that treat every item identically. Neither accounts for demand uncertainty, lead time variability, item criticality, or the interactions between items that are often ordered together.

This is a textbook optimization problem. You have an objective (minimize total cost), constraints (budget limits, storage capacity, minimum service levels), and decision variables (when to order, how much to order). The math has been solved for decades in other industries. Healthcare is just late to applying it rigorously.

---

## The Technology: Inventory Optimization from First Principles

### The Classic Inventory Problem

Inventory optimization is one of the oldest problems in operations research. The fundamental tension is simple: holding inventory costs money (storage, capital, expiration risk), but not having inventory also costs money (stockouts, emergency orders, clinical disruption). The goal is to find the ordering policy that minimizes total cost while maintaining acceptable service levels.

The two core decisions for each item are:

1. **When to reorder** (the reorder point): At what inventory level should you trigger a new order?
2. **How much to order** (the order quantity): When you do order, how many units?

The simplest model is the Economic Order Quantity (EOQ), which dates back to 1913. EOQ assumes constant demand, fixed lead times, and no stockouts. It gives you a closed-form formula for the optimal order quantity. It's elegant, it's wrong for healthcare, and it's a useful starting point for understanding why the real problem is harder.

### Why Healthcare Makes This Hard

**Demand uncertainty.** Patient volume fluctuates. Flu season spikes demand for respiratory supplies. A new surgeon joining the practice changes implant consumption patterns overnight. Demand for most medical supplies is not constant; it's stochastic (random with a probability distribution). Your model needs to handle this uncertainty explicitly, not assume it away.

**Lead time variability.** Your distributor says "2-3 business days." In practice, it's 1 day for commodity items and 3 weeks for specialty implants during a supply chain disruption. Lead time uncertainty compounds demand uncertainty: if you don't know exactly when your order will arrive, you need more safety stock to cover the gap.

**Item criticality.** Running out of paper towels is annoying. Running out of blood products is a patient safety event. Your optimization model needs to treat these differently. A 95% service level might be acceptable for office supplies but catastrophically inadequate for crash cart medications. This means different items get different constraints, and the model must respect those constraints absolutely.

**Expiration and shelf life.** Many medical supplies expire. Medications, reagents, blood products, some sterile supplies. Ordering too much doesn't just tie up capital; it creates waste when items expire before use. This adds a time dimension to the problem that standard inventory models often ignore.

**Bundled ordering and volume discounts.** Distributors offer price breaks at quantity thresholds. Group purchasing organizations (GPOs) negotiate contracts with minimum volume commitments. Your optimization needs to consider these non-linear cost structures, not just per-unit pricing.

**Storage constraints.** Hospital storage is finite and expensive (per-square-foot costs in a hospital are dramatically higher than in a warehouse). You can't just order more of everything. Total inventory across all items must fit within physical and budgetary limits.

### Formulating the Optimization

The mathematical formulation looks like this:

**Objective function:** Minimize total cost = holding costs + ordering costs + stockout costs + waste costs (expiration)

**Decision variables:**
- Reorder point (r_i) for each item i
- Order quantity (Q_i) for each item i

**Constraints:**
- Service level: P(stockout) ≤ threshold_i for each item (varies by criticality)
- Budget: Total inventory value ≤ budget limit
- Storage: Total volume ≤ storage capacity
- Minimum order quantities: Q_i ≥ MOQ_i (distributor minimums)
- Maximum shelf life: Expected time-to-use ≤ expiration window

This is a constrained optimization problem. For simple cases (independent items, known distributions), you can solve it analytically. For realistic cases (correlated demand, volume discounts, shared constraints across items), you need a numerical solver.

### Solver Selection

The choice of solver depends on problem structure:

**Linear Programming (LP):** If your objective and constraints are all linear (no "if-then" logic, no integer requirements), LP solvers are fast and scale well. Pure inventory problems rarely stay linear because of integer order quantities and volume discount breakpoints.

**Mixed-Integer Programming (MIP):** When you need integer order quantities, binary decisions (order or don't order), or piecewise-linear cost functions (volume discounts), MIP is the standard approach. Modern MIP solvers (CPLEX, Gurobi, open-source CBC/HiGHS) can handle thousands of items with reasonable solve times for batch optimization.

**Stochastic Programming:** When you want to explicitly model demand uncertainty (not just use safety stock as a buffer), stochastic programming formulates the problem across multiple demand scenarios. More accurate but computationally expensive. Practical for strategic decisions (setting base policies), less practical for daily operational adjustments.

**Heuristic/Metaheuristic approaches:** For very large problems or when the mathematical structure doesn't fit neatly into LP/MIP (complex business rules, non-convex costs), genetic algorithms, simulated annealing, or other metaheuristics can find good-enough solutions. You sacrifice optimality guarantees for tractability.

For most healthcare inventory problems, MIP with stochastic demand parameters (using safety stock formulas derived from demand distributions) hits the right balance: mathematically rigorous, computationally tractable, and expressive enough to capture real-world constraints.

### Batch vs. Real-Time Optimization

**Batch optimization** (nightly or weekly): Recalculate optimal reorder points and quantities for all items based on updated demand forecasts, current inventory levels, and lead time estimates. This is the standard approach for setting inventory policies. It's computationally feasible for large item catalogs and doesn't require real-time infrastructure.

**Real-time adjustment:** Monitor inventory levels continuously and trigger orders when thresholds are crossed. The thresholds themselves come from the batch optimization. Real-time logic is simple (compare current level to reorder point); the intelligence lives in how those points were calculated.

**Event-driven recalculation:** Rerun optimization for specific items when significant events occur: a supply chain disruption announcement, a sudden demand spike (pandemic), a new contract with different pricing. This is a middle ground between nightly batch and continuous optimization.

The practical architecture for most health systems: batch optimization sets the policies, real-time monitoring executes them, and event-driven triggers force recalculation when the world changes faster than your batch cycle.

### The General Architecture Pattern

```
[Demand Forecasting] → [Parameter Estimation] → [Optimization Solver] → [Policy Store] → [Execution Engine]
                                                                                              ↓
[Inventory Monitoring] ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← [Order Generation]
```

**Demand Forecasting:** Predict future demand for each item using historical consumption data. Time series models, seasonal decomposition, or ML-based forecasters. The output is a demand distribution (mean and variance), not just a point estimate. Recipe 12.2 covers supply inventory forecasting in detail.

**Parameter Estimation:** From the demand forecast, estimate the parameters the optimizer needs: expected demand during lead time, demand variance, lead time distribution, holding cost per unit per day, ordering cost per order, and stockout cost (often modeled as a service level constraint rather than a dollar cost, because putting a dollar value on "we ran out of blood products" is a conversation nobody wants to have).

**Optimization Solver:** Takes the parameters and constraints, solves for optimal reorder points and order quantities. Outputs a policy for each item: "reorder when inventory drops to X units; order Y units."

**Policy Store:** Persists the calculated policies in a queryable format. The execution engine reads from here. Policies are versioned so you can track changes and roll back if a new optimization run produces unexpected results.

**Execution Engine:** Monitors current inventory levels (from ERP/inventory management system), compares against policies, and generates purchase orders when reorder points are crossed. This is the operational layer that turns optimization outputs into actual orders.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter14.03-architecture). The Python example is linked from there.

## The Honest Take

The math here is well-understood. Inventory optimization has been a solved problem in manufacturing and retail for decades. The hard part in healthcare isn't the solver; it's the data.

Your ERP's inventory levels are probably wrong. Not dramatically wrong, but off by enough to matter. Supplies get consumed without being scanned. Items move between departments informally. Par levels get adjusted manually without updating the system. The optimization model will faithfully produce optimal policies for the inventory levels it sees, which may not match reality. Garbage in, garbage out, but with a veneer of mathematical rigor that makes it harder to spot.

The criticality classification is where politics enters. Everyone thinks their department's supplies are "critical." You need clinical leadership to define and enforce the tiers, because the optimizer will allocate more budget and space to critical items at the expense of standard ones. That's a resource allocation decision disguised as a technical parameter.

Expiration management is the sleeper complexity. The model above handles it as a constraint (don't order more than you can use before expiry), but real expiration management requires FIFO tracking, rotation policies, and redistribution logic for items approaching their date. That's a separate operational system that the optimizer needs to integrate with, not replace.

The thing that surprised me most: the biggest savings often come not from optimizing individual item policies, but from consolidating orders across items to hit volume discount breakpoints. A model that optimizes items independently misses these cross-item synergies. Adding order consolidation logic (grouping items by distributor, timing orders to hit price breaks) can double the cost savings, but it also doubles the model complexity.

Start with the basic model. Get the data pipeline right. Prove value on a subset of items. Then add sophistication.

---

## Related Recipes

- **Recipe 12.2 (Supply Inventory Forecasting):** Provides the demand forecasting component that feeds into this optimization. Use 12.2's output as input to Step 2 here.
- **Recipe 14.1 (Appointment Slot Optimization):** Demonstrates the same constrained optimization pattern applied to a different healthcare resource (time slots vs. physical inventory).
- **Recipe 14.4 (Nurse Staffing Optimization):** Shows how MIP handles complex labor constraints; similar solver architecture with different domain constraints.
- **Recipe 3.4 (Medication Dispensing Anomalies):** Detects unusual consumption patterns that could indicate data quality issues affecting your demand forecasts.

---

## Tags

`optimization` · `operations-research` · `inventory` · `supply-chain` · `mip` · `mixed-integer-programming` · `demand-forecasting` · `sagemaker` · `step-functions` · `ecs` · `dynamodb` · `healthcare-operations` · `simple-medium`

---

*← [Recipe 14.2: Patient-Provider Assignment](chapter14.02-patient-provider-assignment) · [Chapter 14 Index](chapter14-preface) · [Next: Recipe 14.4 - Nurse Staffing Optimization →](chapter14.04-nurse-staffing-optimization)*
