# Recipe 14.8: Ambulance Routing and Dispatch

**Complexity:** Complex · **Phase:** Production · **Estimated Cost:** ~$2,000-8,000/month depending on fleet size and call volume

---

## The Problem

A 911 call comes in. Chest pain, 67-year-old male, residential address on the east side of town. The dispatcher has maybe 30 seconds to make a decision that could determine whether this person lives or dies. Which ambulance do you send? The closest one by straight-line distance? The one that's actually closest by road, accounting for the construction on Main Street? The one that's already en route back from a hospital drop-off and will be available in 90 seconds? The one with a paramedic certified in cardiac interventions versus the BLS unit that's technically closer?

And once you've picked the ambulance, which hospital do you route them to? The nearest ED? The one with a cath lab that's not currently on diversion? The one that's 4 minutes farther but has an open bed in the cardiac unit?

This is not a simple "find the nearest vehicle" problem. It's a multi-objective, real-time optimization problem with life-safety stakes, incomplete information, and decisions that cascade. Every minute of response time in a cardiac event correlates with measurably worse outcomes. The National Association of EMS Physicians targets under 8 minutes for urban response to life-threatening calls. Many systems struggle to hit that consistently, not because they lack ambulances, but because they lack the optimization infrastructure to deploy them intelligently.

Most dispatch systems today still rely on a combination of CAD (Computer-Aided Dispatch) software that does basic proximity matching and human dispatchers making judgment calls based on experience. The dispatchers are often excellent. But they're making decisions with incomplete information, under time pressure, across a fleet that might span dozens of units. They can't simultaneously evaluate 15 possible assignments against 8 constraints in real time. A computer can.

The optimization opportunity here is enormous. Studies in operations research have shown that intelligent dispatch and positioning can reduce average response times by 1 to 3 minutes without adding a single ambulance to the fleet. In cardiac arrest, that's the difference between a 30% survival rate and a 50% survival rate.

Let's talk about how to build this.

---

## The Technology: Vehicle Routing and Real-Time Dispatch Optimization

### The Vehicle Routing Problem (VRP)

At its core, ambulance dispatch is a variant of the Vehicle Routing Problem, one of the most studied problems in operations research. The classic VRP asks: given a set of vehicles at various locations and a set of requests to serve, what's the optimal assignment and routing? The ambulance version adds several twists that make it significantly harder.

The standard VRP is already NP-hard (meaning there's no known algorithm that solves it optimally in polynomial time for large instances). The ambulance variant adds:

- **Dynamic arrivals.** Calls arrive unpredictably. You can't batch them and solve once. Every new call potentially invalidates your current plan.
- **Stochastic travel times.** Traffic changes minute to minute. The 6-minute route at 2 PM might be 12 minutes at 5 PM.
- **Heterogeneous vehicles.** ALS (Advanced Life Support) units carry paramedics and cardiac equipment. BLS (Basic Life Support) units have EMTs. You can't send a BLS unit to a STEMI.
- **Preemption.** A higher-priority call might need to reassign a unit that's currently responding to a lower-priority call.
- **Redeployment.** When you send Unit 7 to the east side, you've created a coverage gap. Should you reposition Unit 3 to cover that gap? This is the "move-up" or "system status management" problem.
- **Destination selection.** Unlike package delivery, the "destination" (hospital) is itself a decision variable, not a given.

### Constraint Formulation

The mathematical formulation looks something like this (simplified for readability):

**Decision variables:**
- Which unit responds to which call (assignment)
- Which route each unit takes (routing)
- Which hospital receives the patient (destination)
- Which idle units reposition to cover gaps (redeployment)

**Objective function (what we're minimizing):**
- Primary: Response time to the highest-acuity calls
- Secondary: Average response time across all calls
- Tertiary: Coverage equity (no neighborhood consistently underserved)

**Hard constraints (must be satisfied):**
- Every call gets a response (no call left unassigned)
- Unit capability matches call acuity (ALS for ALS-required calls)
- Hospital capability matches patient needs (trauma center for trauma, cath lab for STEMI)
- Hospital not on diversion status
- Unit availability (can't assign a unit that's already transporting)

**Soft constraints (prefer to satisfy, but can violate with penalty):**
- Response time under 8 minutes for Priority 1 calls
- Maintain minimum coverage levels in each zone
- Minimize total fleet miles (fuel, wear)
- Respect crew hour limits and shift boundaries

### Solver Selection

For real-time dispatch (decisions needed in seconds), you have a few solver categories:

**Heuristic dispatchers.** The simplest approach: send the closest available, capable unit. Fast (milliseconds), but ignores system-level effects. Sending the closest unit to a low-priority call might leave a high-demand zone uncovered. Most legacy CAD systems work this way.

**Greedy with lookahead.** Evaluate the top N candidate units, score each assignment against multiple criteria (response time, coverage impact, unit fatigue), pick the best. Still fast (tens of milliseconds), much better than pure proximity. This is the sweet spot for most real-time dispatch decisions.

**Mixed-Integer Programming (MIP).** Formulate the full problem mathematically and solve with a commercial solver (CPLEX, Gurobi) or open-source solver (SCIP, HiGHS, OR-Tools). Gives provably optimal or near-optimal solutions. The catch: solve times range from seconds to minutes depending on problem size. Works well for the redeployment/repositioning problem (which is less time-critical) but may be too slow for immediate dispatch of a Priority 1 call.

**Metaheuristics.** Genetic algorithms, simulated annealing, tabu search. Good for large instances where MIP is too slow but you want better-than-greedy solutions. Solve times are tunable (you decide how long to search). Common for shift-level fleet positioning plans.

**Reinforcement learning.** Train a policy that maps system state to dispatch decisions. Fast at inference time (milliseconds). Requires extensive simulation and training. Promising for the redeployment problem where the action space is large and the reward signal (future response times) is delayed. Still emerging in production EMS systems.

### Real-Time vs. Batch Optimization

The ambulance problem actually has two optimization layers that operate on different timescales:

**Real-time dispatch (seconds).** A call comes in, you need an assignment now. The solver must return a decision in under 5 seconds (ideally under 1 second). This favors heuristics or pre-computed lookup tables. You're optimizing a single assignment given the current system state.

**Batch repositioning (minutes).** Every few minutes, or whenever the system state changes significantly (a unit becomes available, a call is completed), you re-solve the positioning problem: given current demand patterns and unit locations, where should idle units be stationed to minimize expected future response times? This can tolerate 30 to 60 seconds of solve time because it's not blocking an active emergency.

**Strategic planning (hours/days).** Where should stations be located? How many units per shift? What's the optimal shift schedule? These are solved offline with full MIP or simulation-based optimization. Not real-time at all, but they set the parameters that the real-time system operates within.

The architecture needs to support all three layers, with the real-time layer being the most latency-sensitive.

### The Coverage Problem

One concept that's central to EMS optimization and not obvious until you dig in: the "coverage" problem. Coverage means: for any point in the service area, is there at least one available unit that can reach it within the target response time?

When you dispatch Unit 7 to a call on the east side, you've potentially reduced coverage on the east side. If another call comes in nearby before Unit 7 is available again, response time will be longer. System Status Management (SSM) is the practice of dynamically repositioning idle units to maintain coverage as the fleet state changes.

The coverage calculation requires:
- A travel time model (how long from point A to point B, right now, accounting for traffic)
- A demand model (where are calls likely to come from in the next 30 minutes?)
- A threshold (what response time defines "covered"?)

This is where the batch optimization layer lives. It's constantly asking: "Given where our units are right now and where calls are likely to come from, are there coverage gaps? If so, which unit should move where?"

### Travel Time Estimation

You cannot do ambulance routing with straight-line distance. You need actual road-network travel times, and ideally real-time traffic-adjusted travel times. An ambulance 2 miles away across a river with no bridge is not "close." An ambulance 4 miles away on an open highway might arrive in 3 minutes.

Travel time estimation approaches:
- **Static road network.** Pre-compute shortest paths on the road graph. Fast lookup, but doesn't account for traffic. Acceptable for rural areas with predictable travel times.
- **Historical traffic patterns.** Adjust travel times by time-of-day and day-of-week based on historical data. Much better for urban areas. "This road is 3 minutes at 2 AM but 12 minutes at 5 PM."
- **Real-time traffic.** Integrate live traffic feeds to get current conditions. Best accuracy, but adds a dependency on an external data source and introduces latency in the lookup.
- **Emergency vehicle adjustments.** Ambulances with lights and sirens don't obey the same traffic patterns as civilian vehicles. They're faster on open roads but still constrained by congestion, intersections, and physical barriers. A common approach: apply a speed multiplier (1.2x to 1.5x) to civilian travel times for emergency responses. This is a rough heuristic. Some systems build separate EMS-specific travel time models from GPS traces of actual ambulance runs.

---

## General Architecture Pattern

```text
[Call Intake] → [Demand Classifier] → [Dispatch Optimizer] → [Unit Assignment]
                                              ↑
                                    [Fleet State Tracker]
                                              ↑
                        [GPS Feeds] + [Hospital Status] + [Traffic Data]

[Background: Repositioning Optimizer] → [Move-Up Commands]
                     ↑
          [Demand Forecast Model] + [Coverage Calculator]
```

**Call intake.** 911 call arrives, gets triaged (MPDS or similar protocol), produces a structured dispatch request: location, priority level, required capability (ALS/BLS), nature of call.

**Fleet state tracker.** Maintains real-time state of every unit: location (GPS), status (available, en route, on scene, transporting, at hospital), capability level, crew certifications, time on shift.

**Dispatch optimizer.** Takes the dispatch request plus current fleet state, evaluates candidate assignments, returns the optimal unit and route. For Priority 1 calls, this must complete in under 2 seconds.

**Repositioning optimizer.** Runs continuously in the background. Monitors coverage levels across the service area. When coverage drops below threshold in a zone, identifies the best idle unit to reposition and issues a move-up command.

**Hospital selection.** Evaluates destination hospitals based on: patient needs (trauma center, cath lab, stroke center), hospital capacity (ED census, diversion status), transport time, and patient/family preference when clinically appropriate.

**Demand forecast.** Predicts call volume and spatial distribution for the next 1 to 4 hours based on historical patterns, time of day, day of week, weather, and special events. Feeds the repositioning optimizer.

The key architectural insight: separate the real-time dispatch decision (latency-critical, simple scoring) from the background optimization (latency-tolerant, complex solver). They share state but operate on different timescales.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter14.08-architecture). The Python example is linked from there.

## The Honest Take

Here's what I'd tell you over coffee about building this system:

The dispatch scoring function is the easy part. Seriously. You can get a working "score candidates by travel time plus coverage impact" prototype in a week. The hard parts are everything around it.

**Data integration is 70% of the project.** Getting real-time GPS from every unit in a consistent format. Getting hospital diversion status (which is often communicated by fax or phone call, not API). Getting traffic data that's actually current. Getting CAD system integration that doesn't add 10 seconds of latency. Each of these integrations is its own multi-month project.

**The travel time model makes or breaks you.** If your travel times are wrong by 2 minutes on average, your "optimal" dispatch is no better than proximity-based. And travel times for emergency vehicles are genuinely hard to model. Lights-and-sirens driving doesn't follow civilian traffic patterns. The only reliable approach is to build your model from actual GPS traces of your own fleet's historical runs. That requires months of data collection before you can even start optimizing.

**Dispatchers will resist.** Not because they're Luddites, but because they've been doing this job for 20 years and they're good at it. They know things the model doesn't: that Unit 7's crew is having a bad day, that the bridge on Oak Street floods when it rains, that the nursing home on Elm always has a 5-minute delay getting the patient to the ambulance bay. Build the system as a recommendation engine, not an override. Let dispatchers accept or reject suggestions. Track acceptance rates. Improve the model based on rejections.

**The coverage model is where the real value lives.** Ironically, the biggest response time improvements don't come from smarter dispatch (picking the right unit for a given call). They come from smarter positioning (having units in the right places before calls happen). The repositioning optimizer is less glamorous than the real-time dispatch engine, but it delivers more impact. Invest there.

**You will need a simulation environment.** You cannot test dispatch optimization changes in production. "Let's see if this new scoring function works better" is not something you try on live 911 calls. Build a discrete-event simulator that replays historical call patterns against your fleet model. Run thousands of simulated days. Compare response time distributions. Only then deploy to production.

---

## Related Recipes

- **Recipe 14.4 (Nurse Staffing Optimization):** Similar constraint-based scheduling, different domain. The solver patterns and constraint formulation techniques transfer directly.
- **Recipe 14.6 (Patient Flow / Bed Assignment):** The hospital capacity data used for destination selection here is the same data that drives bed assignment optimization. These systems should share a hospital status feed.
- **Recipe 14.7 (OR Case Sequencing):** Another real-time optimization problem with dynamic replanning. The architecture pattern of "fast heuristic for immediate decisions, heavier solver for background optimization" applies to both.
- **Recipe 12.3 (ED Arrival Forecasting):** The demand forecasting component here is closely related to ED arrival prediction. Similar features, similar models, different spatial granularity.
- **Recipe 7.4 (ED Visit Prediction):** Predicting which patients will need emergency services feeds into the demand model for ambulance positioning.

---

**Tags:** `optimization` · `vehicle-routing` · `real-time` · `ems` · `dispatch` · `geospatial` · `operations-research` · `coverage` · `fleet-management`

---

| [← 14.7: OR Case Sequencing](chapter14.07-or-case-sequencing) | [Chapter 14 Index](chapter14-preface) | [14.9: Chemotherapy Scheduling →](chapter14.09-chemotherapy-scheduling) |
