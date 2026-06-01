# Recipe 14.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 14.1. It shows one way you could translate appointment slot optimization concepts into working Python code using PuLP (an open-source linear programming library) and SimPy (a discrete-event simulation library). It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to your scheduling system on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need a few Python packages:

```bash
pip install pulp simpy numpy boto3
```

PuLP is a modeling library for linear and mixed-integer programming. It ships with the CBC solver (open-source, no license required), which is more than sufficient for a problem this size. SimPy handles the discrete-event simulation for validation. NumPy provides the statistical distributions.

Your environment needs AWS credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs `s3:GetObject`, `s3:PutObject`, and `dynamodb:PutItem`.

---

## Config and Constants

Before we get to the optimization logic, here's the configuration that defines the problem. These constants represent a typical family medicine clinic session. In production, you'd pull these from your EHR data warehouse rather than hardcoding them.

```python
import numpy as np
from dataclasses import dataclass

# Visit type definitions: clinical minimums, maximums, and revenue weights.
# These come from your medical director and billing team.
# Duration bounds are in minutes. Revenue weight is relative (used in the objective).

VISIT_TYPES = {
    "new_patient": {
        "min_duration": 30,    # clinical minimum: can't do a proper new patient in less
        "max_duration": 60,    # don't allocate more than an hour
        "revenue_weight": 3.0, # highest revenue per visit
    },
    "follow_up_complex": {
        "min_duration": 20,
        "max_duration": 40,
        "revenue_weight": 2.0,
    },
    "follow_up_simple": {
        "min_duration": 10,
        "max_duration": 25,
        "revenue_weight": 1.0,
    },
    "procedure": {
        "min_duration": 20,
        "max_duration": 45,
        "revenue_weight": 2.5,
    },
    "bp_recheck": {
        "min_duration": 5,
        "max_duration": 15,
        "revenue_weight": 0.5,
    },
    "telehealth": {
        "min_duration": 10,
        "max_duration": 25,
        "revenue_weight": 1.2,
    },
}

# Session constraints: when does the provider work?
SESSION_START_HOUR = 8    # 8:00 AM
SESSION_END_HOUR = 17     # 5:00 PM
LUNCH_START_HOUR = 12     # noon
LUNCH_DURATION_MIN = 60   # one hour lunch break
SESSION_MINUTES = (SESSION_END_HOUR - SESSION_START_HOUR) * 60 - LUNCH_DURATION_MIN  # 480 total

# Overbooking constraints
MAX_OVERBOOK_PER_HOUR = 2  # never more than 2 extra patients in any hour block

# Wait time constraint
MAX_ACCEPTABLE_WAIT_MIN = 20  # patients should not wait more than 20 minutes on average

# Tradeoff parameter: how much do we penalize wait time relative to throughput?
# Higher lambda = more wait-averse. Start at 0.5 and tune based on organizational priorities.
WAIT_PENALTY_LAMBDA = 0.5

# Expected visit type mix for this provider (fraction of total visits).
# This comes from historical scheduling data. Must sum to 1.0.
VISIT_TYPE_MIX = {
    "new_patient": 0.10,
    "follow_up_complex": 0.30,
    "follow_up_simple": 0.25,
    "procedure": 0.10,
    "bp_recheck": 0.15,
    "telehealth": 0.10,
}
```

---

## Historical Data: Duration and No-Show Statistics

In production, you'd compute these from your EHR data warehouse. Here we define them directly to keep the example self-contained. These numbers represent what you'd get from 6+ months of historical visit data for a single provider.

```python
# Historical visit duration statistics (mean and standard deviation in minutes).
# Computed from actual check-in to checkout times, NOT scheduled durations.
# The standard deviation matters enormously: high-variance visit types create
# cascading delays that ripple through the entire session.

DURATION_STATS = {
    "new_patient":        {"mean": 42.0, "std": 12.0},
    "follow_up_complex":  {"mean": 27.0, "std": 8.0},
    "follow_up_simple":   {"mean": 16.0, "std": 5.0},
    "procedure":          {"mean": 32.0, "std": 10.0},
    "bp_recheck":         {"mean": 9.0,  "std": 3.0},
    "telehealth":         {"mean": 14.0, "std": 4.0},
}

# No-show rates by hour block. Computed from historical data.
# Morning slots tend to have lower no-show rates; late afternoon is worst.
# These drive the overbooking optimization: if 9am has 20% no-shows,
# overbooking by 1 patient at 9am just gets you back to expected panel size.

NOSHOW_RATES = {
    8:  0.08,   # early birds show up
    9:  0.12,
    10: 0.15,
    11: 0.14,
    13: 0.18,   # post-lunch is rough
    14: 0.20,
    15: 0.22,
    16: 0.25,   # late afternoon: highest no-show rate
}
```

---

## Step 1: Formulate and Solve the Optimization Model

*The pseudocode calls this `optimize_template(features, constraints)`. We use PuLP to formulate a mixed-integer program that finds optimal slot durations and overbooking levels.*

```python
import pulp


def optimize_template() -> dict:
    """
    Formulate and solve the appointment slot optimization problem.

    Decision variables:
    - d[t]: slot duration for each visit type t (continuous, in minutes)
    - o[h]: overbooking count for each hour block h (integer)
    - b: buffer time between slots (continuous, in minutes)

    Objective: maximize expected throughput (weighted by revenue) minus
    a penalty for expected wait time.

    Returns a dictionary with optimal slot durations, buffer, and overbooking levels.
    """

    # Create the optimization model.
    # "Maximize" because our objective is throughput minus wait penalty.
    model = pulp.LpProblem("AppointmentSlotOptimization", pulp.LpMaximize)

    # --- Decision Variables ---

    # Slot duration for each visit type (continuous variable, bounded by clinical limits)
    d = {}
    for vtype, config in VISIT_TYPES.items():
        d[vtype] = pulp.LpVariable(
            f"duration_{vtype}",
            lowBound=config["min_duration"],
            upBound=config["max_duration"],
            cat="Continuous",
        )

    # Buffer time between slots (continuous, 0 to 15 minutes)
    b = pulp.LpVariable("buffer", lowBound=0, upBound=15, cat="Continuous")

    # Overbooking count per hour block (integer, 0 to max)
    o = {}
    for hour in NOSHOW_RATES.keys():
        o[hour] = pulp.LpVariable(
            f"overbook_{hour}",
            lowBound=0,
            upBound=MAX_OVERBOOK_PER_HOUR,
            cat="Integer",
        )

    # --- Compute expected slots per session ---
    # The weighted average slot duration (including buffer) determines how many
    # patients fit in a session.
    weighted_avg_duration = pulp.lpSum(
        VISIT_TYPE_MIX[vtype] * (d[vtype] + b) for vtype in VISIT_TYPES
    )

    # Total overbooked patients across all hour blocks
    total_overbook = pulp.lpSum(o[hour] for hour in NOSHOW_RATES)

    # Base slots: session minutes divided by average slot duration.
    # PuLP can't do division directly in the objective, so we linearize:
    # Instead of maximizing SESSION_MINUTES / weighted_avg_duration,
    # we minimize weighted_avg_duration (which maximizes slots per session).
    # We also add the overbooking benefit weighted by show probability.

    # --- Objective Function ---
    # We want to:
    # 1. Minimize average slot duration (more patients fit)
    # 2. Benefit from overbooking (weighted by probability patients actually show)
    # 3. Penalize for expected wait time (approximated by duration variance)

    # Throughput component: shorter slots = more patients.
    # We negate weighted_avg_duration because we're maximizing.
    throughput_term = -weighted_avg_duration

    # Overbooking benefit: each overbooked slot has value proportional to
    # the probability the patient shows up (1 - noshow_rate for that hour).
    overbook_benefit = pulp.lpSum(
        o[hour] * (1 - NOSHOW_RATES[hour]) * 1.0  # revenue weight of 1.0 for overbooks
        for hour in NOSHOW_RATES
    )

    # Wait time penalty: approximated by the variance contribution of each visit type.
    # Higher variance = more downstream waiting. This is a linearized approximation
    # of the Pollaczek-Khinchine formula. In production, you'd validate with simulation.
    wait_penalty = pulp.lpSum(
        VISIT_TYPE_MIX[vtype] * DURATION_STATS[vtype]["std"]
        for vtype in VISIT_TYPES
    )

    # Combined objective
    model += throughput_term + overbook_benefit - WAIT_PENALTY_LAMBDA * wait_penalty

    # --- Constraints ---

    # The weighted average slot duration must allow at least some minimum number
    # of patients per session. We require at least 12 patients fit in a session.
    # SESSION_MINUTES / weighted_avg_duration >= 12
    # Linearized: weighted_avg_duration <= SESSION_MINUTES / 12
    model += weighted_avg_duration <= SESSION_MINUTES / 12, "min_patients_constraint"

    # Maximum session utilization: don't pack so tight that there's zero slack.
    # Require at least 30 minutes of slack in the session for unexpected overruns.
    # This means: 12 * weighted_avg_duration <= SESSION_MINUTES - 30
    # (assuming ~12 base patients)
    model += 12 * weighted_avg_duration <= SESSION_MINUTES - 30, "slack_constraint"

    # --- Solve ---
    # CBC is the default solver bundled with PuLP. No external license needed.
    # For a problem this small (< 50 variables), it solves in milliseconds.
    solver = pulp.PULP_CBC_CMD(msg=0)  # msg=0 suppresses solver output
    model.solve(solver)

    # --- Extract Results ---
    if model.status != pulp.constants.LpStatusOptimal:
        raise RuntimeError(
            f"Solver did not find optimal solution. Status: {pulp.LpStatus[model.status]}"
        )

    result = {
        "slot_durations": {
            vtype: round(pulp.value(d[vtype]), 1) for vtype in VISIT_TYPES
        },
        "buffer_minutes": round(pulp.value(b), 1),
        "overbooking": {
            str(hour): int(pulp.value(o[hour])) for hour in NOSHOW_RATES
        },
        "objective_value": round(pulp.value(model.objective), 3),
        "solver_status": pulp.LpStatus[model.status],
    }

    return result
```

---

## Step 2: Simulate a Clinic Day

*The pseudocode calls this `simulate_clinic_day(template, features, num_replications)`. We use SimPy to run a discrete-event simulation that tests the proposed template against realistic patient behavior.*

```python
import simpy


def build_schedule_from_template(template: dict) -> list:
    """
    Generate a day's schedule from the optimized template.

    Creates a sequence of appointment slots based on the visit type mix
    and optimized durations. Returns a list of slot dictionaries with
    scheduled times and visit types.
    """
    slots = []
    current_time = SESSION_START_HOUR * 60  # convert to minutes from midnight
    session_end = SESSION_END_HOUR * 60
    lunch_start = LUNCH_START_HOUR * 60
    lunch_end = lunch_start + LUNCH_DURATION_MIN

    # Build the schedule by filling time with slots according to the visit type mix.
    # In production, you'd use the actual appointment requests. Here we simulate
    # a representative day using the expected mix.
    visit_types_list = list(VISIT_TYPE_MIX.keys())
    mix_weights = [VISIT_TYPE_MIX[vt] for vt in visit_types_list]

    slot_id = 0
    while current_time < session_end:
        # Skip lunch
        if lunch_start <= current_time < lunch_end:
            current_time = lunch_end
            continue

        # Pick a visit type based on the expected mix
        vtype = np.random.choice(visit_types_list, p=mix_weights)
        duration = template["slot_durations"][vtype]
        buffer = template["buffer_minutes"]

        # Check if this slot fits before session end (or lunch)
        slot_end = current_time + duration + buffer
        if current_time < lunch_start and slot_end > lunch_start:
            current_time = lunch_end
            continue
        if slot_end > session_end:
            break

        slots.append({
            "id": slot_id,
            "scheduled_time": current_time,
            "visit_type": vtype,
            "scheduled_duration": duration,
        })

        current_time += duration + buffer
        slot_id += 1

    # Add overbooked patients to appropriate hour blocks
    for hour_str, overbook_count in template["overbooking"].items():
        hour = int(hour_str)
        hour_start = hour * 60
        for i in range(overbook_count):
            vtype = np.random.choice(visit_types_list, p=mix_weights)
            slots.append({
                "id": slot_id,
                "scheduled_time": hour_start + 15 * i,  # stagger within the hour
                "visit_type": vtype,
                "scheduled_duration": template["slot_durations"][vtype],
                "is_overbook": True,
            })
            slot_id += 1

    # Sort by scheduled time
    slots.sort(key=lambda s: s["scheduled_time"])
    return slots


def simulate_single_day(template: dict, rng: np.random.Generator) -> dict:
    """
    Simulate one clinic day using the proposed template.

    Models patient arrivals, no-shows, variable visit durations, and
    tracks wait times, throughput, and overtime.

    Args:
        template: The optimized template (slot durations, buffer, overbooking)
        rng: NumPy random generator for reproducibility

    Returns:
        Dictionary with day-level metrics: patients_seen, avg_wait, max_wait,
        overtime_minutes, idle_minutes.
    """
    schedule = build_schedule_from_template(template)

    # Track metrics
    wait_times = []
    provider_free_at = SESSION_START_HOUR * 60  # provider starts available at session start

    patients_seen = 0

    for slot in schedule:
        hour = slot["scheduled_time"] // 60
        # Clamp hour to valid range for noshow lookup
        noshow_hour = max(8, min(16, hour))

        # Determine if patient shows up
        if rng.random() < NOSHOW_RATES.get(noshow_hour, 0.15):
            continue  # no-show: skip this patient entirely

        # Patient showed up. Draw actual visit duration from historical distribution.
        vtype = slot["visit_type"]
        actual_duration = max(
            VISIT_TYPES[vtype]["min_duration"],  # floor at clinical minimum
            rng.normal(
                DURATION_STATS[vtype]["mean"],
                DURATION_STATS[vtype]["std"],
            ),
        )

        # Patient wait = how long after their scheduled time until provider is free
        patient_wait = max(0, provider_free_at - slot["scheduled_time"])
        wait_times.append(patient_wait)

        # Provider starts seeing this patient at the later of:
        # their scheduled time or when the provider becomes free
        visit_start = max(slot["scheduled_time"], provider_free_at)
        provider_free_at = visit_start + actual_duration

        patients_seen += 1

    session_end = SESSION_END_HOUR * 60
    overtime = max(0, provider_free_at - session_end)

    # Idle time: gaps where provider was free but no patient was scheduled
    # (simplified: total session time minus time spent with patients minus wait-caused delays)
    total_clinical_time = provider_free_at - SESSION_START_HOUR * 60 - LUNCH_DURATION_MIN
    idle_time = max(0, SESSION_MINUTES - total_clinical_time) if overtime == 0 else 0

    return {
        "patients_seen": patients_seen,
        "avg_wait": np.mean(wait_times) if wait_times else 0.0,
        "max_wait": np.max(wait_times) if wait_times else 0.0,
        "overtime_minutes": overtime,
        "idle_minutes": idle_time,
    }


def run_simulation(template: dict, num_replications: int = 1000, seed: int = 42) -> dict:
    """
    Run multiple simulation replications and aggregate results.

    This is the validation step: we test the proposed template against
    realistic stochastic patient behavior to see how it actually performs
    across many possible days.

    Args:
        template: The optimized template to test
        num_replications: How many random days to simulate (1000 is a good default)
        seed: Random seed for reproducibility

    Returns:
        Aggregated statistics across all replications.
    """
    rng = np.random.default_rng(seed)

    results = []
    for _ in range(num_replications):
        day_result = simulate_single_day(template, rng)
        results.append(day_result)

    # Aggregate across replications
    patients_seen = [r["patients_seen"] for r in results]
    avg_waits = [r["avg_wait"] for r in results]
    max_waits = [r["max_wait"] for r in results]
    overtimes = [r["overtime_minutes"] for r in results]
    idles = [r["idle_minutes"] for r in results]

    return {
        "mean_throughput": round(np.mean(patients_seen), 1),
        "std_throughput": round(np.std(patients_seen), 1),
        "mean_avg_wait": round(np.mean(avg_waits), 1),
        "p95_avg_wait": round(np.percentile(avg_waits, 95), 1),
        "mean_max_wait": round(np.mean(max_waits), 1),
        "overtime_probability": round(np.mean([o > 0 for o in overtimes]), 3),
        "mean_overtime_minutes": round(np.mean(overtimes), 1),
        "mean_idle_minutes": round(np.mean(idles), 1),
        "num_replications": num_replications,
    }
```

---

## Step 3: Compare Against Current Template

*This step runs the simulation for both the current (baseline) template and the proposed (optimized) template, then computes the improvement.*

```python
def create_baseline_template() -> dict:
    """
    Represent the current "one-size-fits-all" template that most clinics use.

    This is the thing we're trying to beat: uniform 30-minute slots,
    no overbooking, no buffer optimization. The scheduling equivalent of
    "we've always done it this way."
    """
    return {
        "slot_durations": {
            "new_patient": 30,
            "follow_up_complex": 30,
            "follow_up_simple": 30,
            "procedure": 30,
            "bp_recheck": 30,
            "telehealth": 30,
        },
        "buffer_minutes": 0,
        "overbooking": {str(h): 0 for h in NOSHOW_RATES.keys()},
    }


def compare_templates(baseline: dict, proposed: dict) -> dict:
    """
    Run simulation on both templates and compute the improvement.

    Returns a comparison dictionary showing before/after metrics
    and the delta for each.
    """
    print("Simulating baseline template (1000 replications)...")
    baseline_results = run_simulation(baseline, num_replications=1000, seed=42)

    print("Simulating proposed template (1000 replications)...")
    proposed_results = run_simulation(proposed, num_replications=1000, seed=42)

    comparison = {
        "baseline": baseline_results,
        "proposed": proposed_results,
        "improvement": {
            "throughput_delta": round(
                proposed_results["mean_throughput"] - baseline_results["mean_throughput"], 1
            ),
            "wait_delta": round(
                proposed_results["mean_avg_wait"] - baseline_results["mean_avg_wait"], 1
            ),
            "overtime_delta": round(
                proposed_results["overtime_probability"] - baseline_results["overtime_probability"], 3
            ),
        },
    }

    return comparison
```

---

## Step 4: Store Results to DynamoDB

*The pseudocode calls this `store_and_notify(...)`. We write the proposed template and simulation comparison to DynamoDB for the review workflow.*

```python
import json
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

TABLE_NAME = "template-store"


def convert_floats_to_decimal(obj):
    """
    Recursively convert floats to Decimal for DynamoDB compatibility.

    DynamoDB does not accept Python floats. You must wrap numeric values
    in Decimal or put_item will raise a TypeError. This helper handles
    nested structures so you don't have to think about it at every call site.
    """
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(item) for item in obj]
    return obj


def store_proposed_template(
    provider_id: str,
    template: dict,
    comparison: dict,
) -> dict:
    """
    Write the proposed template and simulation results to DynamoDB.

    The record includes the full template configuration, simulation results
    for both baseline and proposed, and the computed improvement metrics.
    Status starts as "proposed" and moves to "approved" or "rejected"
    after human review.

    Args:
        provider_id: Identifier for the provider (e.g., "DR-MARTINEZ-FM")
        template: The optimized template (slot durations, buffer, overbooking)
        comparison: Simulation comparison results (baseline vs. proposed)

    Returns:
        The record that was written to DynamoDB.
    """
    table = dynamodb.Table(TABLE_NAME)

    record = {
        "provider_id": provider_id,
        "created_at": datetime.datetime.now(timezone.utc).isoformat(),
        "status": "proposed",
        "template": template,
        "simulation_baseline": comparison["baseline"],
        "simulation_proposed": comparison["proposed"],
        "improvement": comparison["improvement"],
    }

    # Convert all floats to Decimal before writing
    dynamo_record = convert_floats_to_decimal(record)

    table.put_item(Item=dynamo_record)

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. This is what your Step Functions workflow or SageMaker Processing job would invoke.

```python
def run_optimization_pipeline(provider_id: str = "DR-MARTINEZ-FM") -> dict:
    """
    Run the complete appointment slot optimization pipeline.

    1. Solve the optimization model to find the best template
    2. Simulate both baseline and proposed templates
    3. Compare results and compute improvement
    4. Store the proposed template for human review

    Args:
        provider_id: Which provider to optimize for

    Returns:
        The full comparison results including the proposed template.
    """

    # Step 1: Run the optimizer
    print(f"=== Appointment Slot Optimization for {provider_id} ===\n")
    print("Step 1: Solving optimization model...")
    proposed_template = optimize_template()
    print(f"  Solver status: {proposed_template['solver_status']}")
    print(f"  Optimal slot durations: {proposed_template['slot_durations']}")
    print(f"  Buffer: {proposed_template['buffer_minutes']} min")
    print(f"  Overbooking: {proposed_template['overbooking']}")

    # Step 2: Create baseline for comparison
    print("\nStep 2: Building baseline template for comparison...")
    baseline = create_baseline_template()

    # Step 3: Run simulation comparison
    print("\nStep 3: Running simulation comparison...")
    comparison = compare_templates(baseline, proposed_template)

    print(f"\n--- Results ---")
    print(f"  Baseline throughput:  {comparison['baseline']['mean_throughput']} patients/day")
    print(f"  Proposed throughput:  {comparison['proposed']['mean_throughput']} patients/day")
    print(f"  Throughput delta:     {comparison['improvement']['throughput_delta']:+.1f}")
    print(f"  Baseline avg wait:   {comparison['baseline']['mean_avg_wait']} min")
    print(f"  Proposed avg wait:   {comparison['proposed']['mean_avg_wait']} min")
    print(f"  Wait delta:          {comparison['improvement']['wait_delta']:+.1f} min")
    print(f"  Baseline overtime:   {comparison['baseline']['overtime_probability']*100:.1f}%")
    print(f"  Proposed overtime:   {comparison['proposed']['overtime_probability']*100:.1f}%")

    # Step 4: Store results (only if DynamoDB table exists)
    print("\nStep 4: Storing proposed template...")
    try:
        store_proposed_template(provider_id, proposed_template, comparison)
        print(f"  Stored to DynamoDB table '{TABLE_NAME}' with status='proposed'")
    except Exception as e:
        print(f"  Skipping DynamoDB store (table may not exist): {e}")
        print("  In production, this writes to DynamoDB for the review workflow.")

    print("\nDone. Template ready for human review.")
    return {
        "provider_id": provider_id,
        "template": proposed_template,
        "comparison": comparison,
    }


# Run the pipeline
if __name__ == "__main__":
    result = run_optimization_pipeline()
    print("\n\nFull output:")
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example works. Run it and it will produce an optimized template with simulation validation. But there's meaningful distance between "works in a script" and "runs weekly optimizing templates for 200 providers." Here's where that gap lives:

**Real data integration.** This example uses hardcoded duration statistics and no-show rates. A production system pulls these from your EHR data warehouse (Epic Clarity, Cerner HealtheIntent, or whatever reporting database you have). That extraction step involves SQL queries against scheduling tables, data quality checks (are durations reasonable? are there outliers from data entry errors?), and handling of edge cases (providers who started mid-year, visit types that were recently added).

**Provider-specific models.** Each provider has different patterns. Dr. Martinez runs 5 minutes over on complex visits; Dr. Chen finishes 3 minutes early. The optimization should run per-provider with provider-specific duration distributions. This example uses one set of statistics for illustration.

**Solver selection for larger problems.** CBC (the solver bundled with PuLP) handles this single-provider problem easily. If you're optimizing across multiple providers with shared resources (MAs, rooms, equipment), you may need a more powerful solver. Google OR-Tools CP-SAT handles complex constraint problems well. For very large instances, commercial solvers like Gurobi or CPLEX offer better performance (but require licenses).

**Simulation fidelity.** The simulation here models patient arrivals and visit durations but ignores several real-world factors: late arrivals (patients who show up 10 minutes after their slot), early arrivals who want to be seen sooner, walk-ins, same-day add-ons, and shared resource contention (one MA supporting two providers). A production simulation should model these.

**Error handling and retries.** The DynamoDB write has no retry logic, no error handling for conditional check failures, and no dead-letter queue for failed writes. Production code wraps every external call in try/except with specific handling for throttling, service unavailability, and validation errors.

**IAM least-privilege.** The IAM role for this pipeline should have exactly: `s3:GetObject` on the features bucket, `s3:PutObject` on the results bucket, `dynamodb:PutItem` on the template-store table, and `dynamodb:GetItem` for reading current templates. Not `s3:*`. Not `dynamodb:*`.

**VPC and encryption.** Scheduling data contains patient names and visit reasons (PHI). In production, SageMaker Processing jobs run in a VPC with no internet access, using VPC endpoints for S3 and DynamoDB. All data at rest is encrypted with KMS customer-managed keys.

**Template change management.** This example produces a proposed template but doesn't handle the approval workflow, rollback if a new template underperforms, or gradual rollout (try the new template for one week, compare actual vs. simulated performance, then decide whether to keep it). That workflow lives in Step Functions with human approval steps.

**Monitoring and drift detection.** After deploying a new template, you need to monitor whether actual performance matches the simulation predictions. If the template was optimized on summer data and flu season arrives, the patient mix shifts and the template may underperform. Build in automated re-optimization triggers when actual metrics deviate from predicted by more than a threshold.

**Testing.** There are no tests here. A production pipeline has unit tests for the optimization formulation (does it respect constraints?), integration tests for the simulation (does it produce reasonable distributions?), and regression tests that verify known-good templates still score well after code changes.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 14.1](chapter14.01-appointment-slot-optimization) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
