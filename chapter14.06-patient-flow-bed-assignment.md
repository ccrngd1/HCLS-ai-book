# Recipe 14.6: Patient Flow and Bed Assignment

**Complexity:** Medium-Complex · **Phase:** Production · **Estimated Cost:** ~$500-1,500/month (solver compute + real-time infrastructure)

---

## The Problem

It's 2 PM on a Tuesday and the emergency department has 14 patients waiting for inpatient beds. The charge nurse on 4-West has two discharges "pending" (the doctors signed the orders an hour ago, but transport hasn't moved the patients yet). The telemetry unit is full, but three of those patients could step down to med-surg if anyone had time to reassess them. A patient in the ICU is ready to transfer out, but the only open step-down bed is on a unit that doesn't have the right nursing skill mix for their drip. Meanwhile, a direct admission from a clinic is arriving in 45 minutes and nobody has figured out where to put them.

This is patient flow. And in most hospitals, it's managed by a combination of phone calls, whiteboards, gut instinct, and a bed management coordinator who somehow keeps the whole thing in their head.

The cost of getting this wrong is enormous. ED boarding (patients waiting in the ED for inpatient beds) is one of the most studied problems in hospital operations. Boarded patients experience longer total lengths of stay, higher complication rates, and worse outcomes. The ED itself becomes gridlocked: when beds are full of boarders, new patients can't be seen, ambulances get diverted, and the whole system degrades. Studies have consistently shown that ED boarding correlates with increased mortality for both the boarding patients and the new arrivals who can't get timely care.

The financial impact is equally brutal. Every hour a patient boards in the ED costs the hospital revenue (they're occupying an ED bed but generating inpatient-level charges that often aren't fully reimbursed at ED rates). Delayed discharges mean beds aren't turning over, which means elective surgical cases get cancelled (there's your OR utilization problem from Recipe 14.5, cascading downstream). A 400-bed hospital losing even 30 minutes of unnecessary boarding per patient per day is leaving millions on the table annually.

And here's the thing that makes this problem genuinely hard: it's not a static assignment problem. It's dynamic. The state changes constantly. Patients arrive unpredictably. Discharges happen (or don't happen) on their own timeline. Acuity levels shift. Isolation requirements appear when a lab result comes back positive. A nurse calls in sick and suddenly a unit's capacity drops. You can't solve this once and walk away. You need to re-solve it continuously.

This is where optimization gets interesting. Not the quarterly batch optimization of OR blocks (Recipe 14.5), but something closer to real-time: a system that continuously evaluates the current state of the hospital and recommends the best patient-to-bed assignments given everything it knows right now.

---

## The Technology: Real-Time Assignment Optimization

### The Assignment Problem

At its mathematical core, bed assignment is a variant of the classic assignment problem: you have N patients who need beds and M available beds, and you want to find the best matching. In the simplest version (the "linear assignment problem"), you have a cost matrix where entry (i, j) represents the cost (or negative benefit) of assigning patient i to bed j, and you want to minimize total cost.

The Hungarian algorithm solves the basic linear assignment problem in polynomial time. It's elegant, fast, and completely insufficient for real hospital bed assignment. Why? Because the real problem has constraints that the basic formulation can't express, multiple objectives that conflict, and a dynamic element that means the "optimal" solution changes every few minutes.

### Constraint Formulation

The constraints in bed assignment fall into categories that range from absolute (violating them is unsafe) to preferential (violating them is suboptimal but acceptable):

**Hard constraints (patient safety):**
- Isolation requirements: patients with airborne infections (TB, COVID, measles) must go to negative-pressure rooms. Contact isolation patients need private rooms or cohorting with same-organism patients only.
- Gender separation: in semi-private rooms, patients must be same gender (with exceptions for pediatrics and some cultural contexts).
- Acuity-to-unit matching: an ICU-level patient cannot go to a med-surg floor. A telemetry patient needs a monitored bed.
- Age-appropriate placement: pediatric patients go to pediatric units. Behavioral health patients go to secured units.
- Equipment requirements: patients on certain drips, ventilators, or monitoring need beds with the right infrastructure.

**Operational constraints:**
- Unit staffing: a unit might have physical beds available but not enough nurses to safely staff them. The nurse-to-patient ratio is a real capacity limit.
- Skill mix: a patient on a complex cardiac drip needs a nurse certified to manage it. Not every nurse on every unit has every certification.
- Anticipated discharges: a bed that's "available in 2 hours" is different from one that's available now. Do you hold it or assign someone else?
- Cleaning turnaround: after discharge, a bed needs terminal cleaning (30-60 minutes typically). It's not instantly available.

**Preference constraints (soft):**
- Continuity of care: if a patient was on 4-West last admission, there's value in placing them there again (familiar staff, existing relationships).
- Geographic clustering: patients of the same attending physician ideally land on the same unit for rounding efficiency.
- Noise and environment: post-surgical patients benefit from quieter rooms. Patients with delirium risk should be near the nursing station.
- Anticipated length of stay: putting a patient expected to stay 1 day in a bed that a 7-day patient will need tomorrow is suboptimal.
- Discharge timing: placing patients in beds that facilitate morning discharge flow (near elevators, near discharge lounges) can improve throughput.

### Multi-Objective Optimization

The real challenge isn't any single constraint. It's that you're optimizing multiple objectives simultaneously, and they conflict:

1. **Minimize ED boarding time.** Get patients out of the ED and into beds as fast as possible.
2. **Maximize clinical appropriateness.** Put patients in the right unit with the right level of care.
3. **Balance unit workload.** Don't overload one unit while another sits half-empty.
4. **Minimize transfers.** Every intra-hospital transfer is a safety risk (medication errors, communication failures, patient falls during transport).
5. **Maximize throughput.** Optimize for the flow of patients through the system, not just the current snapshot.

You can't maximize all of these simultaneously. Minimizing ED boarding time might mean putting a patient on a less-than-ideal unit. Balancing workload might mean sending a patient to a unit farther from their physician. The optimization needs to encode these tradeoffs explicitly through objective weights or constraint hierarchies.

A common approach is **lexicographic optimization**: satisfy the most important objective first (safety constraints), then optimize the second objective (ED boarding) subject to the first being satisfied, then the third, and so on. Alternatively, you can use a **weighted sum** approach where each objective gets a numerical weight reflecting its relative importance. The weights are policy decisions that hospital leadership must make explicitly.

### Solver Selection for Real-Time Problems

The solver choice for bed assignment is different from batch scheduling (Recipe 14.5) because of the time constraint. You need solutions in seconds, not minutes or hours.

**Mixed-Integer Programming (MIP):** Still works for bed assignment, but you need to be careful about problem size. A 400-bed hospital with 30 pending assignments is a manageable MIP (hundreds of binary variables, not thousands). Modern solvers (Gurobi, OR-Tools) can solve this in under a second. But if you're re-solving every 5 minutes with a warm start, you want the solver to be fast and deterministic.

**Constraint Programming (CP):** Particularly well-suited for bed assignment because the constraint structure is complex and heterogeneous. CP solvers (Google OR-Tools CP-SAT, IBM CP Optimizer) handle "if-then" constraints naturally. "If patient has airborne isolation, then room must have negative pressure" is awkward in MIP (requires big-M formulations) but natural in CP.

**Greedy heuristics with local search:** For the real-time component, sometimes a fast heuristic that produces a "good enough" solution in milliseconds is better than an optimal solution that takes 30 seconds. A priority-queue approach (assign the highest-acuity, longest-waiting patient first, to the best available bed) with local search improvements (swap two assignments if it improves the objective) can be surprisingly effective.

**Hybrid approaches:** The most practical systems use a tiered strategy. A fast heuristic provides an immediate recommendation (within 1-2 seconds of a state change). A more thorough optimization runs every 5-15 minutes and may revise the heuristic's suggestions. The strategic layer runs daily to set parameters like unit target census levels and staffing plans.

### Real-Time vs. Batch: The Temporal Dimension

This is the fundamental architectural decision for bed assignment systems. You have three temporal modes:

**Event-driven (real-time):** Every time the state changes (new admission, discharge, transfer, acuity change), re-evaluate all pending assignments. This gives the freshest recommendations but requires low-latency infrastructure and careful handling of rapid state changes (you don't want to thrash between solutions).

**Periodic batch (every N minutes):** Run the optimizer on a fixed schedule (every 5, 10, or 15 minutes). Simpler to implement, easier to reason about, and avoids thrashing. The downside: a patient who arrives 1 minute after the last run waits up to N minutes for a recommendation.

**Hybrid (event-triggered with debouncing):** State changes trigger a timer. If no additional changes arrive within a short window (30-60 seconds), run the optimizer. If more changes arrive, reset the timer. This batches rapid-fire changes (like a cluster of discharges at 11 AM) while still responding quickly to isolated events.

Most production systems use the hybrid approach. Pure real-time is architecturally complex and often unnecessary (a 60-second delay in bed assignment rarely matters clinically). Pure batch with long intervals creates visible delays that frustrate staff.

### The State Estimation Problem

Here's something that isn't obvious until you try to build this: the "current state" of the hospital is surprisingly hard to know accurately.

The ADT (Admit-Discharge-Transfer) system is the source of truth, but it lags reality. A discharge order might be signed at 10 AM, but the patient doesn't physically leave until 2 PM. The bed shows as "occupied" in the ADT system until someone clicks "discharge complete." A transfer order is entered, but the patient hasn't moved yet. A bed is "available" in the system but physically has a patient's belongings still in it because transport is backed up.

Your optimization is only as good as your state data. If you're optimizing against stale state, you'll make recommendations that are already wrong by the time a human sees them. This means you need:

- Real-time ADT event feeds (HL7 or FHIR messages), not periodic database polls
- Predicted discharge times (not just "discharge order signed"), which is itself a prediction problem (see Recipe 7.7: Length of Stay Prediction)
- Bed turnaround time estimates (cleaning, inspection, readiness)
- A concept of "soft availability": beds that aren't available now but will be within a predictable window

The state estimation layer is often more work than the optimization layer itself. Getting the data right is the hard part. The math is comparatively straightforward once you have accurate inputs.

---

## General Architecture Pattern

The system has five logical layers:

```text
[State Ingestion] → [State Model] → [Optimization Engine] → [Recommendation Service] → [Staff Interface]
```

**State Ingestion:** Consumes real-time events from ADT systems, nurse call systems, bed tracking sensors (if available), and staffing systems. Transforms raw events into a coherent current-state representation. Handles out-of-order events, duplicates, and corrections.

**State Model:** Maintains a live representation of the hospital's bed state: which beds are occupied, by whom, with what constraints; which beds are available, pending cleaning, or expected to become available; which patients are waiting for beds, with what requirements and priority. This is the "digital twin" of the hospital's physical bed state.

**Optimization Engine:** Takes the current state model as input and produces recommended assignments. Runs on a hybrid schedule (event-triggered with debouncing). Supports multiple scenarios ("what if we open the overflow unit?") and constraint relaxation ("what if we allow one gender exception on 3-East?").

**Recommendation Service:** Presents optimization results to bed management staff. Includes confidence levels, constraint explanations ("Patient A assigned to 4W-12 because: negative pressure required, telemetry available, nurse certified for cardiac drip"), and alternative options ranked by quality.

**Staff Interface:** The human-facing layer. Bed management coordinators see recommendations, accept or override them, and provide feedback that improves future recommendations. Charge nurses see incoming patients and can flag constraints the system doesn't know about ("that room has a plumbing issue, don't assign it").

The feedback loop is critical. Every time a human overrides the system's recommendation, that's a learning signal. Either the system missed a constraint (add it to the model) or the human is applying a preference the system doesn't encode (consider adding it as a soft constraint).

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter14.06-architecture). The Python example is linked from there.

## The Honest Take

Here's what I've learned about bed assignment optimization that the vendor demos won't tell you:

**The data problem is 80% of the work.** Getting accurate, real-time bed state is brutally hard. ADT systems lag reality. Cleaning times are unpredictable. Staffing changes mid-shift. You'll spend most of your implementation time on the state ingestion layer, not the optimizer. The math is the easy part.

**Staff trust takes 6-12 months to build.** Bed coordinators have been doing this job with their brains and their phones for decades. They're good at it. They know things the system doesn't (that nurse is having a bad day, that room has a broken call light, that patient's family is difficult). The first few months, acceptance rates will be low (40-50%). That's normal. Every accepted recommendation builds trust. Every good override teaches the system something.

**You will never eliminate overrides, and you shouldn't try.** A 75-85% acceptance rate is excellent. The remaining 15-25% represents legitimate human judgment that the model can't capture. If you're at 95%+ acceptance, you're probably not being aggressive enough with your recommendations (playing it too safe).

**The political dimension is real.** Unit charge nurses sometimes resist accepting patients because they're "already busy." The optimizer might say their unit has capacity, but the nurse's lived experience says otherwise. Sometimes the nurse is right (the acuity mix is high even if the census is low). Sometimes it's territorial behavior. Your system needs to surface the data transparently without being accusatory.

**Start with a decision-support tool, not an automated system.** The temptation is to build full automation: patient arrives, system assigns bed, done. Don't. Start with recommendations that humans accept or reject. Build trust. Understand the override patterns. Only automate the obvious cases (straightforward med-surg admits with no special requirements) after you've proven the model works.

**Cleaning time is the hidden bottleneck.** Everyone focuses on discharge prediction, but the time between "patient leaves bed" and "bed is ready for next patient" is often 45-90 minutes and highly variable. Environmental services (EVS) staffing, terminal vs. standard cleaning protocols, and simple communication delays all contribute. Some hospitals have cut boarding times more by optimizing cleaning workflows than by optimizing assignments.

---

## Related Recipes

- **Recipe 7.7: Length of Stay Prediction** provides the discharge time estimates that feed this optimizer's "anticipated availability" calculations.
- **Recipe 12.3: ED Arrival Forecasting** predicts incoming demand, enabling proactive capacity management.
- **Recipe 12.5: Hospital Census Forecasting** gives the broader demand context for staffing and capacity planning.
- **Recipe 14.4: Nurse Staffing Optimization** determines the staffed capacity constraints that limit bed availability.
- **Recipe 14.5: Operating Room Block Scheduling** is the upstream optimization whose output (surgical cases) drives downstream bed demand.

---

## Tags

`optimization` `operations-research` `patient-flow` `bed-management` `real-time` `constraint-programming` `mixed-integer-programming` `hospital-operations` `capacity-management` `ED-boarding`

---

| [← 14.5: Operating Room Block Scheduling](chapter14.05-operating-room-block-scheduling) | [Chapter 14 Index](chapter14-preface) | [14.7: OR Case Sequencing →](chapter14.07-or-case-sequencing) |
