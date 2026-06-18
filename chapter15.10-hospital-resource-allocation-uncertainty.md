# Recipe 15.10: Hospital Resource Allocation Under Uncertainty

**Complexity:** Complex · **Phase:** Research/Pilot · **Estimated Cost:** ~$3,000-$12,000/month (simulation + training infrastructure)

---

## The Problem

Every hospital administrator has lived this nightmare: it's Tuesday afternoon, your ICU is at 94% capacity, three trauma cases just came through the ED, two OR cases are running long, and your charge nurse is calling to ask where you're putting the post-surgical patients who were supposed to transfer to med-surg but can't because med-surg is full because three discharges got delayed because transport is backed up because... you get the idea.

Hospital resource allocation is a cascading constraint satisfaction problem that changes every hour. Beds, nurses, respiratory therapists, ventilators, OR time, transport staff, isolation rooms, telemetry monitors. Every resource is finite. Every decision affects every other decision downstream. And the demand is fundamentally uncertain: you don't know when the next trauma will arrive, which patient will deteriorate, or which discharge will get delayed by a pending lab result.

The current approach at most hospitals is reactive. Charge nurses and bed coordinators make real-time decisions based on experience, gut feel, and whoever is yelling loudest. They're remarkably good at it (humans are excellent at rapid heuristic decision-making under pressure), but they're also burning out. They can't see the whole system simultaneously. They can't model the probabilistic consequences of today's bed assignment on tomorrow's surgical schedule. They optimize locally because they have to act now.

The scale of the problem is staggering. A 500-bed hospital makes hundreds of resource allocation decisions per day. Each decision interacts with dozens of constraints: patient acuity, staffing ratios, infection control requirements, equipment availability, physician preferences, regulatory requirements. A bed isn't just a bed. It's a bed in a specific unit, with specific monitoring capabilities, specific nurse-to-patient ratios, specific isolation status. Putting a patient in the "wrong" bed cascades: you might need a 1:1 sitter, a portable monitor from another unit, or a nurse floating from a department that's now short-staffed.

The financial impact is measurable. ED boarding (patients waiting in the ED for an inpatient bed) costs hospitals millions annually in lost throughput, increased length of stay, and worse outcomes. Surgical cancellations due to bed unavailability cost $10,000-$50,000 per cancelled case in lost revenue. Staff overtime from poor allocation planning adds up fast. And patient outcomes suffer: studies have shown that ICU patients who experience delayed transfer to step-down units have longer overall stays.

This is where reinforcement learning gets interesting. Resource allocation under uncertainty is a sequential decision problem with delayed rewards. Today's bed assignment affects tomorrow's flexibility. Holding an ICU bed open "just in case" has a cost (the patient who needs it now), but so does filling it (the patient who needs it at 3 AM). The optimal policy depends on the current state of the entire hospital, the time of day, the day of the week, the season, and the specific patient mix. No static rulebook handles this well.

---

## The Technology: Reinforcement Learning for Dynamic Resource Management

### Why RL Fits This Problem

Resource allocation under uncertainty has three properties that make it a natural RL problem:

**Sequential decisions with delayed consequences.** Assigning a patient to a bed right now constrains what you can do in four hours. Calling in an extra nurse costs money but prevents a potential safety issue tonight. These temporal dependencies are exactly what RL handles well. Unlike greedy optimization (which picks the best action right now), RL learns policies that balance immediate costs against future flexibility.

**Stochastic environment.** Demand is unpredictable. Patient arrivals follow non-stationary distributions (more traumas on weekends, more elective admissions Monday through Wednesday, seasonal respiratory surges in winter). Patient length of stay is uncertain. Complications happen. RL is designed for stochastic environments. It learns to make decisions that are robust to uncertainty, not just optimal for the expected case.

**High-dimensional state space.** The "state" of a hospital at any moment includes hundreds of variables: census by unit, acuity levels, staffing levels, pending admissions, pending discharges, OR schedule, equipment availability. Classical optimization (linear programming, mixed-integer programming) struggles with this dimensionality when combined with uncertainty. Deep RL can learn value functions over high-dimensional state spaces using neural network function approximators.

### The MDP Formulation

To apply RL, you formalize the hospital as a Markov Decision Process:

**State (what the agent observes):**

The state vector captures a snapshot of hospital operations. A realistic formulation might include:

- Current census by unit (ICU, step-down, med-surg, telemetry, ED, OR)
- Bed availability by type (standard, isolation, negative pressure, bariatric)
- Patient acuity distribution per unit
- Staffing levels by role (RN, RT, CNA, transport) vs. scheduled
- Pending admissions (ED boarders, direct admits, surgical cases in OR)
- Pending discharges (confirmed, probable, unlikely today)
- OR schedule remaining for the day
- Time features (hour, day of week, month, holiday flag)
- Equipment inventory (ventilators available, monitors, pumps)
- Historical demand patterns for this time window

This easily reaches 200-500 continuous features. Dimensionality reduction helps (aggregating individual patients into unit-level statistics), but you need enough resolution to make useful decisions.

**Actions (what the agent decides):**

Actions operate at multiple time scales:

- Immediate: assign specific patient to specific bed/unit
- Short-term: request staff float (move nurse from one unit to another)
- Short-term: activate overflow capacity (open a closed unit section)
- Medium-term: adjust elective admission targets for tomorrow
- Medium-term: pre-position equipment to anticipated high-demand units

For tractability, most implementations use a discrete action space with 10-50 actions representing common allocation decisions. Continuous action spaces (specifying exact resource quantities) are possible but harder to validate and explain.

**Reward (what defines success):**

The reward function must balance multiple competing objectives:

```text
reward = -w1 * ed_boarding_hours
         - w2 * surgical_cancellations
         - w3 * staffing_ratio_violations
         - w4 * patient_transfers (moves between units)
         - w5 * overtime_hours
         + w6 * discharge_before_noon_rate
         + w7 * unit_census_balance
```

Each weight reflects organizational priorities. A safety-net hospital might weight ED boarding heavily. A surgical center might weight OR cancellations. The weights are not learned; they're set by hospital leadership and represent policy choices.

The tricky part: some rewards are immediate (a staffing ratio violation is observable now) while others are delayed (a surgical cancellation tomorrow because you filled too many beds today). RL handles this temporal credit assignment through its value function, but the delay makes learning slower and evaluation harder.

**Transition dynamics (how the hospital state evolves):**

The hospital state transitions according to:
- Patient arrivals (stochastic, modeled from historical data)
- Patient discharges (semi-predictable, conditioned on diagnosis and LOS)
- Patient deterioration/improvement (stochastic, acuity-dependent)
- Staff shift changes (deterministic schedule plus stochastic callouts)
- OR case completions (semi-predictable from schedule and case type)

These dynamics are what you build into the simulation environment. The fidelity of your simulator determines the quality of your learned policy.

### Offline vs. Online Learning: The Critical Tradeoff

**You cannot do online RL in a live hospital.** Full stop. You cannot explore suboptimal resource allocation strategies on real patients to gather training data. The exploration component of RL (trying things to see what happens) is incompatible with patient safety and operational requirements.

This means all training happens offline, using one of two approaches:

**Approach 1: Offline RL from historical data.** You collect historical operational data (who was placed where, what happened next, what the outcomes were) and learn a policy that would have performed better than the observed decisions. This uses offline RL algorithms (Conservative Q-Learning, Implicit Q-Learning, Decision Transformer) that learn from a fixed dataset without online interaction.

The challenge: distribution shift. Your learned policy will recommend actions that weren't taken in the historical data. You have no ground truth for what would have happened if those actions had been taken. Offline RL algorithms address this with conservatism (staying close to the behavior policy), but it limits how much improvement you can achieve.

**Approach 2: Simulator-based training.** You build a discrete-event simulation of hospital operations, calibrated to your hospital's historical data. The RL agent trains in this simulator, exploring freely without risk. The simulator captures arrival patterns, length-of-stay distributions, staffing models, and resource constraints.

The challenge: sim-to-real gap. Your simulator is a model of reality, not reality itself. If it's miscalibrated (patient arrivals don't match, LOS distributions are wrong, it doesn't capture seasonal effects), the policy you learn will be optimized for the wrong world. Domain randomization (training across a range of simulator parameters) helps make the policy robust to miscalibration.

In practice, you want both. Train primarily in simulation. Validate against historical data (would this policy have performed better on last month's actual patient flow?). Deploy with extensive guardrails and human oversight.

### Safety Constraints in Hospital RL

Unlike some RL domains where constraint violations are just suboptimal, hospital resource allocation has hard constraints that cannot be violated:

- Minimum staffing ratios (regulatory, not negotiable)
- Isolation requirements (infection control, patient safety)
- Equipment compatibility (a patient on a ventilator needs a bed with ventilator hookups)
- Scope of practice (cannot assign tasks outside a provider's credential)
- Maximum capacity limits (fire code, licensing)

These must be enforced at action selection time, not just penalized in the reward. The architecture needs a constraint checker that vetoes any action violating hard constraints, regardless of what the policy network outputs. The policy learns over time not to propose infeasible actions (because they never result in reward), but the hard constraint layer is the safety guarantee.

### Constrained Markov Decision Processes (CMDPs)

The formal framework for RL with constraints is the Constrained MDP. In a CMDP, you have the standard MDP objective (maximize cumulative reward) plus constraint functions that must stay below specified thresholds:

```text
maximize: E[Σ γ^t * r(s_t, a_t)]
subject to: E[Σ γ^t * c_i(s_t, a_t)] ≤ d_i   for all i
```

Where c_i are constraint cost functions and d_i are maximum allowable costs. For hospital RL:
- c_1 might be "minutes any patient spends without adequate nurse coverage"
- c_2 might be "number of times ICU census exceeds safe capacity"
- c_3 might be "ED boarding hours exceeding 4-hour threshold"

Algorithms like Constrained Policy Optimization (CPO) and Lagrangian relaxation methods solve CMDPs by jointly optimizing the objective and satisfying constraints. In practice, you combine CMDP training with a hard constraint action mask for absolute safety limits.

---

## General Architecture Pattern

The architecture has four major components: data ingestion, simulation environment, RL training pipeline, and decision support interface.

```text
[Real-time Hospital Data] → [State Aggregator] → [Current State Vector]
                                                         ↓
[Historical Data] → [Simulator Calibration] → [Hospital Simulator]
                                                         ↓
                                               [RL Training Loop]
                                                         ↓
                                               [Trained Policy]
                                                         ↓
[Current State Vector] → [Policy Inference] → [Constraint Checker] → [Recommendations]
                                                                            ↓
                                                                   [Human Decision-Maker]
```

**Data ingestion** pulls real-time operational data from ADT (Admit-Discharge-Transfer) systems, nurse staffing platforms, OR scheduling systems, and equipment tracking. This feeds the state vector for inference and the historical dataset for simulator calibration.

**The simulation environment** is a discrete-event simulation of hospital operations. Patients arrive according to learned distributions. They move through the hospital (ED to inpatient, OR to PACU to floor). Length of stay follows diagnosis-specific distributions. Staff shift according to schedules. The simulator must be fast enough to run thousands of episodes for training.

**The RL training pipeline** trains the policy network against the simulator. Training happens offline (batch), not in real-time. You retrain periodically (weekly or monthly) as hospital patterns change. The training loop includes constraint enforcement, reward shaping, and domain randomization.

**The decision support interface** presents the trained policy's recommendations to human operators (charge nurses, bed coordinators, capacity managers). This is explicitly a decision support system, not an autonomous controller. Humans see the recommendation, the reasoning (which constraints are tight, what the model predicts about future demand), and decide whether to accept it.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and implementation details, see the [Architecture and Implementation companion](chapter15.10-architecture). The Python example is linked from there.

## Code: Pseudocode Walkthrough

### Step 1: Define the Hospital State Vector

Every decision starts with knowing where you are. The state aggregator collects real-time data from multiple source systems and assembles a single vector representing the current hospital state.

If you skip this step (or do it poorly), the policy makes decisions based on stale or incomplete information. A resource allocation recommendation based on two-hour-old census data is useless during a surge.

```pseudocode
FUNCTION build_state_vector(hospital_id, timestamp):
    // Pull current census from each unit
    census = GET_CENSUS_BY_UNIT(hospital_id)
    // Returns: {icu: 18/20, stepdown: 22/24, medsurg: 85/100, ...}

    // Pull current staffing vs. scheduled
    staffing = GET_STAFFING_LEVELS(hospital_id, timestamp)
    // Returns: {icu_rn: 6/6, medsurg_rn: 12/14, rt: 3/4, ...}

    // Pull pending movements
    pending_admits = GET_PENDING_ADMISSIONS(hospital_id)
    // ED boarders waiting, direct admits confirmed, OR cases finishing
    pending_discharges = GET_PENDING_DISCHARGES(hospital_id)
    // Confirmed (transport ordered), probable (awaiting labs), unlikely today

    // Pull equipment availability
    equipment = GET_EQUIPMENT_STATUS(hospital_id)
    // Ventilators, monitors, pumps, isolation carts

    // Build time features
    time_features = {
        hour: EXTRACT_HOUR(timestamp),
        day_of_week: EXTRACT_DOW(timestamp),
        month: EXTRACT_MONTH(timestamp),
        is_holiday: CHECK_HOLIDAY(timestamp),
        minutes_until_shift_change: CALC_SHIFT_MINUTES(timestamp)
    }

    // Assemble into normalized vector
    state = CONCATENATE(
        NORMALIZE(census),
        NORMALIZE(staffing),
        NORMALIZE(pending_admits),
        NORMALIZE(pending_discharges),
        NORMALIZE(equipment),
        ENCODE(time_features)
    )

    RETURN state  // Shape: [1, state_dim] where state_dim ~ 200-500
```

### Step 2: Build the Hospital Simulation Environment

The simulator is the heart of the system. It models hospital operations with enough fidelity to produce useful policies, but fast enough to run thousands of episodes during training.

If your simulator is miscalibrated (arrival rates are wrong, LOS distributions don't match reality), you'll learn a policy optimized for a hospital that doesn't exist.

```pseudocode
CLASS HospitalSimulator:
    FUNCTION __init__(config):
        // Load hospital-specific parameters
        self.units = config.units  // [{name, capacity, type, staffing_ratio}, ...]
        self.arrival_model = LOAD_ARRIVAL_MODEL(config.arrival_params)
        self.los_model = LOAD_LOS_MODEL(config.los_params)
        self.staff_schedule = LOAD_STAFF_SCHEDULE(config.staff_params)

        // Initialize state
        self.clock = 0
        self.patients = []  // Active patients with unit, acuity, los_remaining
        self.event_queue = PRIORITY_QUEUE()  // Upcoming events sorted by time

    FUNCTION reset():
        // Start a new episode with random initial conditions
        // Sample initial census from historical distribution
        self.clock = SAMPLE_START_TIME()
        self.patients = SAMPLE_INITIAL_CENSUS(self.clock)
        self.event_queue = GENERATE_INITIAL_EVENTS(self.clock)
        RETURN self.get_state()

    FUNCTION step(action):
        // Execute action (e.g., assign patient X to unit Y)
        constraint_violation = CHECK_HARD_CONSTRAINTS(action, self.state)
        IF constraint_violation:
            RETURN self.get_state(), LARGE_NEGATIVE_REWARD, False, {violation: True}

        APPLY_ACTION(action)

        // Advance simulation to next decision point
        WHILE NOT DECISION_POINT_REACHED():
            event = self.event_queue.pop()
            self.clock = event.time
            PROCESS_EVENT(event)
            // Events: patient arrival, discharge, deterioration, shift change

        // Calculate reward
        reward = COMPUTE_REWARD(self.state, action)

        // Check if episode is done (e.g., 24-hour horizon)
        done = (self.clock >= self.episode_end)

        RETURN self.get_state(), reward, done, {}

    FUNCTION compute_reward(state, action):
        reward = 0
        reward -= W_BOARDING * COUNT_ED_BOARDERS(state)
        reward -= W_CANCEL * COUNT_SURGICAL_CANCELLATIONS(state)
        reward -= W_RATIO * COUNT_STAFFING_VIOLATIONS(state)
        reward -= W_TRANSFER * COUNT_PATIENT_MOVES(state)
        reward -= W_OVERTIME * CALC_OVERTIME_HOURS(state)
        reward += W_BALANCE * CALC_CENSUS_BALANCE(state)
        RETURN reward
```

### Step 3: Train the RL Policy with Safety Constraints

Training uses Proximal Policy Optimization (PPO) with Lagrangian constraint handling. PPO is stable, well-understood, and works well with discrete action spaces. The Lagrangian approach converts hard constraints into adaptive penalty terms that the optimizer balances against the reward objective.

If you skip constraint handling, the policy will find clever ways to game the reward (e.g., never admitting patients achieves zero boarding, but zero throughput).

```pseudocode
FUNCTION train_policy(simulator, config):
    // Initialize policy and value networks
    policy_net = NEURAL_NETWORK(input_dim=STATE_DIM, output_dim=ACTION_DIM)
    value_net = NEURAL_NETWORK(input_dim=STATE_DIM, output_dim=1)

    // Initialize Lagrange multipliers for constraints
    lambda_staffing = 1.0
    lambda_capacity = 1.0
    lambda_boarding = 1.0

    FOR episode IN RANGE(config.num_episodes):
        // Domain randomization: vary simulator parameters each episode
        sim_params = SAMPLE_DOMAIN_RANDOMIZATION(config.domain_rand_range)
        simulator.configure(sim_params)

        state = simulator.reset()
        episode_reward = 0
        episode_constraints = {staffing: 0, capacity: 0, boarding: 0}
        trajectory = []

        WHILE NOT done:
            // Get action from policy (with exploration noise during training)
            action_probs = policy_net(state)
            action = SAMPLE_FROM(action_probs)

            // Apply action mask for hard constraints
            feasible_actions = GET_FEASIBLE_ACTIONS(state)
            action = MASK_AND_RESAMPLE(action_probs, feasible_actions)

            next_state, reward, done, info = simulator.step(action)

            // Track constraint costs
            episode_constraints.staffing += STAFFING_COST(state, action)
            episode_constraints.capacity += CAPACITY_COST(state, action)
            episode_constraints.boarding += BOARDING_COST(state, action)

            // Compute augmented reward with Lagrangian penalties
            augmented_reward = reward
                - lambda_staffing * STAFFING_COST(state, action)
                - lambda_capacity * CAPACITY_COST(state, action)
                - lambda_boarding * BOARDING_COST(state, action)

            trajectory.append({state, action, augmented_reward, next_state, done})
            state = next_state
            episode_reward += reward

        // Update policy using PPO
        UPDATE_PPO(policy_net, value_net, trajectory)

        // Update Lagrange multipliers (dual gradient ascent)
        lambda_staffing += LR_DUAL * (episode_constraints.staffing - THRESHOLD_STAFFING)
        lambda_capacity += LR_DUAL * (episode_constraints.capacity - THRESHOLD_CAPACITY)
        lambda_boarding += LR_DUAL * (episode_constraints.boarding - THRESHOLD_BOARDING)

        // Clamp multipliers to prevent instability
        lambda_staffing = MAX(0, lambda_staffing)
        lambda_capacity = MAX(0, lambda_capacity)
        lambda_boarding = MAX(0, lambda_boarding)

    RETURN policy_net
```

### Step 4: Offline Policy Evaluation

Before deploying any learned policy, you must evaluate it against historical data. This tells you whether the policy would have performed better than actual human decisions on real scenarios.

If you skip evaluation, you're deploying a policy trained in simulation without any evidence it works in reality.

```pseudocode
FUNCTION evaluate_policy_offline(policy, historical_episodes):
    // Importance-weighted evaluation (off-policy)
    results = []

    FOR episode IN historical_episodes:
        cumulative_reward_policy = 0
        cumulative_reward_actual = 0
        importance_weights = []

        FOR (state, actual_action, actual_reward) IN episode.transitions:
            // What would our policy have done?
            policy_action_probs = policy(state)
            policy_action = ARGMAX(policy_action_probs)

            // Importance weight for off-policy correction
            // (only needed for full OPE; simplified here)
            weight = policy_action_probs[actual_action] / behavior_policy_prob(actual_action)
            importance_weights.append(weight)

            cumulative_reward_actual += actual_reward

        // Estimate policy value using weighted importance sampling
        policy_value_estimate = WEIGHTED_IS_ESTIMATE(episode, importance_weights)

        results.append({
            actual_reward: cumulative_reward_actual,
            estimated_policy_reward: policy_value_estimate,
            improvement: policy_value_estimate - cumulative_reward_actual
        })

    // Aggregate results
    avg_improvement = MEAN([r.improvement FOR r IN results])
    confidence_interval = BOOTSTRAP_CI(results, alpha=0.05)

    RETURN {
        avg_improvement: avg_improvement,
        ci_lower: confidence_interval.lower,
        ci_upper: confidence_interval.upper,
        episodes_evaluated: LEN(results),
        pass_threshold: avg_improvement > MIN_IMPROVEMENT AND ci_lower > 0
    }
```

### Step 5: Deploy as Decision Support with Human Override

The trained policy produces recommendations, not commands. A human operator sees the recommendation, the reasoning, and decides whether to follow it.

If you skip the human-in-the-loop layer, you've built an autonomous hospital controller. Nobody wants that. Nobody should want that.

```pseudocode
FUNCTION generate_recommendation(hospital_id):
    // Build current state
    state = build_state_vector(hospital_id, NOW())

    // Load latest approved policy
    // TODO (TechWriter): Expert review S3 (LOW). Note model artifact integrity verification here: hash check at load time, SageMaker Model Registry lineage tracking.
    policy = LOAD_MODEL(model_registry, stage="approved")

    // Get policy recommendation
    action_probs = policy(state)
    top_actions = TOP_K(action_probs, k=3)

    // Check hard constraints on each recommendation
    feasible_recommendations = []
    FOR action IN top_actions:
        violations = CHECK_HARD_CONSTRAINTS(action, state)
        IF NOT violations:
            explanation = GENERATE_EXPLANATION(action, state)
            feasible_recommendations.append({
                action: action,
                confidence: action_probs[action],
                explanation: explanation,
                predicted_impact: ESTIMATE_IMPACT(action, state)
            })

    // Log for audit and future training
    LOG_RECOMMENDATION({
        timestamp: NOW(),
        state: state,
        recommendations: feasible_recommendations,
        model_version: policy.version
    })

    RETURN feasible_recommendations

FUNCTION handle_human_decision(recommendation_id, decision):
    // Record whether human accepted, modified, or rejected
    LOG_DECISION({
        recommendation_id: recommendation_id,
        decision: decision,  // "accepted", "modified", "rejected"
        modification_details: decision.details IF decision == "modified",
        reason: decision.reason IF decision == "rejected"
    })
    // This data feeds back into training to improve policy alignment
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter15.10-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

## Expected Results

### Sample Recommendation Output

```json
{
  "timestamp": "2026-03-15T14:30:00Z",
  "hospital_state_summary": {
    "icu_census": "18/20 (90%)",
    "ed_boarders": 3,
    "pending_or_cases": 2,
    "medsurg_available": 8,
    "staffing_status": "adequate"
  },
  "recommendations": [
    {
      "action": "assign_ed_boarder_patient_to_medsurg_4B",
      "confidence": 0.82,
      "explanation": "Patient acuity compatible with med-surg. Moving now prevents cascade: 2 OR cases completing in 90 min will need recovery beds. Holding ED boarder delays next ED-to-inpatient by estimated 2.3 hours.",
      "predicted_impact": {
        "ed_boarding_reduction_hours": 2.3,
        "surgical_cancellation_risk_change": -0.15,
        "staffing_ratio_impact": "within_limits"
      }
    },
    {
      "action": "float_rn_from_5east_to_icu",
      "confidence": 0.67,
      "explanation": "ICU approaching capacity with 2 pending admits. 5-East has lowest acuity and 1 nurse above minimum ratio. Floating now provides buffer for anticipated admissions.",
      "predicted_impact": {
        "icu_capacity_buffer": "+1 bed equivalent",
        "5east_staffing": "at minimum ratio (safe)",
        "overtime_risk_change": -0.08
      }
    }
  ],
  "model_version": "v2.4.1",
  "constraint_status": "all_satisfied"
}
```

### Performance Benchmarks

| Metric | Baseline (Human Only) | RL-Assisted (Simulation Results) | Notes |
|--------|----------------------|----------------------------------|-------|
| Average ED boarding hours/day | 28.5 | 19.2 (-33%) | Simulated on 6 months of historical data |
| Surgical cancellations/month | 12.3 | 8.1 (-34%) | Due to bed availability improvements |
| Staffing ratio violations/day | 4.2 | 1.8 (-57%) | Proactive floating recommendations |
| Patient transfers between units | 18.7/day | 14.3/day (-24%) | Better initial placement |
| Recommendation acceptance rate | N/A | 62% | Early pilot data typical for decision support |
| Recommendation latency | N/A | <800ms | Cold start serverless function |

**Important caveat:** These are simulation-based estimates validated against historical data using offline policy evaluation. Real-world performance will differ. Pilot deployment with careful A/B evaluation is required before claiming these improvements.

### Where It Struggles

- **Unprecedented events.** A mass casualty incident creates states the policy has never seen. The system should detect out-of-distribution states and defer entirely to human judgment.
- **Soft constraints.** "Dr. Smith prefers patients on 4-West" is not a hard constraint but ignoring it creates friction. Capturing preferences without overfitting to them is difficult.
- **Multi-site coordination.** If your system operates across campuses with patient transfers between them, the state space explodes.
- **Behavioral dynamics.** Staff respond to recommendations. If the system always floats nurses from 5-East, 5-East morale drops. These second-order effects aren't in the simulator.

---

## The Honest Take

Let me be direct about where this stands in 2026.

**Hospital resource allocation RL is research-grade.** There are published papers, simulation studies, and a handful of pilot deployments. There is not, to my knowledge, a fully autonomous RL-based resource allocator running in production at a major hospital system. The technology works in simulation. The operational integration is where it gets hard.

**The simulator is 80% of the work.** Building a hospital simulator that's faithful enough to produce useful policies is an enormous engineering effort. You need accurate arrival models, realistic length-of-stay distributions, staff behavior modeling, and equipment logistics. Most teams underestimate this. The RL algorithm is the easy part.

**Human acceptance is the real bottleneck.** Even if your policy is provably better in simulation, charge nurses have 20 years of experience and strong opinions. A system that says "move patient from ICU 4 to step-down 2B" without compelling justification will be ignored. Explainability is not optional; it's the difference between a tool that gets used and expensive shelfware.

**The reward function is a political document.** When you set weights for ED boarding vs. surgical cancellations vs. overtime, you're making resource allocation tradeoffs that have winners and losers. The ED director wants boarding weighted heavily. The surgeon wants OR cancellations weighted heavily. The CFO wants overtime weighted heavily. Getting alignment on the reward function requires executive sponsorship, not just engineering effort.

**Offline evaluation is necessary but insufficient.** You can estimate policy performance using importance sampling and historical data, but these estimates have wide confidence intervals. The only way to truly validate is a careful pilot deployment with concurrent controls (randomized by time block or unit).

What I'd do differently if starting over: spend the first 6 months on the simulator and data pipeline. Don't touch RL until you have a simulator that hospital operations staff look at and say "yeah, that's roughly how it works." Then start simple (a contextual bandit for bed assignment) and grow toward full RL as you build trust.

---

## Related Recipes

- **Recipe 14.6: Patient Flow / Bed Assignment** - Deterministic optimization approach to the same problem. Useful comparison: optimization handles the known schedule well; RL handles the uncertainty better. In practice, you might use optimization for the base plan and RL for real-time adjustments.
- **Recipe 12.5: Hospital Census Forecasting** - Provides demand predictions that feed into the state vector and enable look-ahead planning.
- **Recipe 12.3: ED Arrival Forecasting** - Predicts incoming demand, critical for anticipatory resource positioning.
- **Recipe 14.4: Nurse Staffing Optimization** - Handles the staffing component in isolation. RL integrates staffing with bed management and equipment allocation jointly.
- **Recipe 15.1: Alert Threshold Optimization** - Simpler RL application in healthcare. Good starting point before tackling resource allocation.

---

## Tags

`reinforcement-learning` `resource-allocation` `hospital-operations` `capacity-management` `decision-support` `simulation` `offline-rl` `constrained-mdp` `bed-management` `staffing`

---

| [← 15.9: Radiation Therapy Adaptive Planning](chapter15.09-radiation-therapy-adaptive-planning) | [Chapter 15 Index](chapter15-preface) | |
