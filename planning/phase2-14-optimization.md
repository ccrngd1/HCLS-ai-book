# Category 14: Optimization / Operations Research

**Healthcare Use Cases — Simple → Complex**

---

## 14.1 Appointment Slot Optimization (Simple)

**What:** Optimize appointment slot templates — duration by visit type, buffer times, overbooking levels — to maximize throughput while maintaining quality.

**Why simple:** Well-defined constraints. Historical data for parameter estimation. Incremental improvements measurable. Low risk of catastrophic failure.

---

## 14.2 Patient-Provider Assignment (Simple)

**What:** Optimally assign patients to providers based on continuity preferences, panel size targets, and provider capacity.

**Why simple:** Clear objective function. Constraints are explicit. Batch assignment acceptable. Supports panel management and new patient distribution.

---

## 14.3 Inventory Reorder Optimization (Simple-Medium)

**What:** Optimize reorder points and quantities for medical supplies balancing holding costs, stockout risk, and order costs.

**Why this complexity:** Must handle demand uncertainty. Lead time variability. Some items are critical (stockout unacceptable). Expiration dates for some products.

---

## 14.4 Nurse Staffing Optimization (Medium)

**What:** Generate optimal nurse schedules that meet coverage requirements while respecting labor rules, preferences, and skill mix.

**Why medium:** Complex constraints (union rules, certifications, preferences). Multiple objectives (cost, fairness, coverage). Must handle call-offs and adjust. Highly visible to staff.

---

## 14.5 Operating Room Block Scheduling (Medium)

**What:** Allocate OR block time to surgical services optimizing utilization, surgeon access, and case mix.

**Why medium:** Scarce resource with high fixed costs. Competing priorities across services. Historical utilization vs. block allocation. Political dynamics.

---

## 14.6 Patient Flow / Bed Assignment (Medium-Complex)

**What:** Real-time optimization of patient-to-bed assignments across units considering acuity, isolation needs, anticipated discharges, and staffing.

**Why this complexity:** Dynamic environment — state changes constantly. Must balance multiple constraints simultaneously. Integration with ADT systems. Decisions visible hospital-wide.

---

## 14.7 OR Case Sequencing (Medium-Complex)

**What:** Optimize daily OR case sequences to minimize turnover time, accommodate surgeon preferences, and maximize room utilization.

**Why this complexity:** Uncertainty in case durations. Dependencies (equipment, staff). Cancellations and add-ons disrupt plans. Real-time replanning needed.

---

## 14.8 Ambulance Routing and Dispatch (Complex)

**What:** Optimize ambulance dispatch decisions and routing considering location, patient acuity, hospital capacity, and traffic.

**Why complex:** Real-time decisions with life-safety stakes. Uncertainty in patient condition and transport time. Must coordinate across agencies. Destination hospital selection adds complexity.

---

## 14.9 Chemotherapy Scheduling (Complex)

**What:** Schedule chemotherapy infusion appointments optimizing chair utilization, nursing workload, pharmacy prep time, and patient preferences.

**Why complex:** Variable infusion durations. Nursing skill requirements. Pharmacy lead times. Patient treatment plans drive timing constraints. High-stakes for patients.

---

## 14.10 Health System Network Design (Complex)

**What:** Optimize service line placement, facility locations, and capacity allocation across a health system network.

**Why complex:** Long-term strategic decisions. Capital investment implications. Demand forecasting uncertainty. Competitive dynamics. Multiple stakeholder objectives. Regulatory constraints (CON).

---

## Complexity Factors Summary

| Factor | Impact on Complexity |
|--------|---------------------|
| Constraint complexity | More rules = harder feasibility |
| Dynamic replanning | Real-time harder than batch |
| Stakeholder objectives | Multiple objectives = trade-offs |
| Uncertainty handling | Stochastic optimization is advanced |
| Time horizon | Strategic decisions have more unknowns |
| Human factors | Staff acceptance affects adoption |

---

*Category 14 complete. Next: Category 15 (Reinforcement Learning)*
