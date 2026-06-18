# Recipe 14.5: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 14.5. It demonstrates how to formulate and solve an OR block scheduling optimization problem using Python and an open-source solver. It is not production-ready. The optimization model here is intentionally small-scale so you can trace what's happening at each step. A real hospital implementation would have more constraints, messier data, and significantly more political complexity. Consider it a starting point, not a destination.

---

## Setup

You'll need the following packages installed:

```bash
pip install boto3 pulp
```

PuLP is a Python linear programming library that provides a clean modeling interface and ships with the CBC (COIN-OR Branch and Cut) solver built in. For larger problems, you can swap in HiGHS (free, faster) or Gurobi (commercial, fastest) without changing your model code. PuLP abstracts the solver choice behind a common API.

Your environment needs AWS credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role needs `s3:GetObject`, `s3:PutObject`, `dynamodb:GetItem`, `dynamodb:Query`, and `dynamodb:Scan` scoped to the relevant resources.

---

## Configuration and Constants

Before we get to the optimization logic, here's the configuration that drives the model. In a real system, most of this comes from DynamoDB or your scheduling system. Here we define it inline so you can see exactly what the optimizer is working with.

```python
import json
import logging
from datetime import datetime, timezone
from typing import Any

import boto3
import pulp
from botocore.config import Config

# Structured logging. Never log PHI (surgeon names linked to patient procedures
# count as PHI under HIPAA when combined with schedule data).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Optimization Configuration ---

# Weights for the multi-objective function.
# These encode value judgments. Adjust based on what your block committee cares about.
# Higher utilization weight = optimizer aggressively reshuffles for efficiency.
# Higher disruption weight = optimizer preserves the current schedule (conservative).
WEIGHTS = {
    "utilization": 1.0,      # reward for matching allocated hours to demand
    "disruption": 0.3,       # penalty for changing a block from its current owner
    "fairness_bonus": 0.5,   # reward for giving underserved services more time
}

# Solver configuration.
SOLVER_CONFIG = {
    "solver": "CBC",          # ships with PuLP, no extra install needed
    "max_seconds": 300,       # 5 minute time limit (more than enough for this scale)
    "gap_tolerance": 0.01,    # accept solutions within 1% of proven optimum
}

# Block schedule resolution: each block is a half-day slot (4 hours).
BLOCK_DURATION_HOURS = 4.0

# Minimum utilization ratio below which a service is considered "underserved"
# and gets a fairness bonus in the objective.
FAIRNESS_THRESHOLD = 0.7
```

---

## Step 1: Load Input Data

*The pseudocode calls this `extract_optimization_inputs`. In production, this pulls from your data lake and DynamoDB. Here we load from S3 where a preprocessing step has already assembled the inputs as JSON.*

```python
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

def load_optimization_inputs(bucket: str, prefix: str) -> dict:
    """
    Load the pre-assembled optimization inputs from S3.

    In a real system, a separate ETL pipeline aggregates data from the EHR's
    surgical scheduling module into these JSON files. The optimizer doesn't
    talk to the EHR directly.

    Args:
        bucket: S3 bucket containing optimization inputs
        prefix: S3 prefix (folder path) for this optimization run

    Returns:
        Dictionary containing all inputs the model needs.
    """

    def read_json(key: str) -> Any:
        response = s3_client.get_object(Bucket=bucket, Key=f"{prefix}/{key}")
        return json.loads(response["Body"].read().decode("utf-8"))

    # Available blocks: each block is a room + day + time slot.
    # Example: {"block_id": "OR3-MON-AM", "room": "OR3", "day": "Monday",
    #           "slot": "AM", "duration_hours": 4.0}
    blocks = read_json("blocks.json")

    # Services requesting block time, with their demand profiles.
    # Example: {"service_id": "ortho", "name": "Orthopedics",
    #           "weekly_hours_needed": 45, "compatible_rooms": ["OR1","OR2","OR3"],
    #           "operating_days": ["Monday","Tuesday","Wednesday","Thursday","Friday"]}
    services = read_json("services.json")

    # Current block allocation (what the schedule looks like today).
    # Example: {"OR3-MON-AM": "ortho", "OR3-MON-PM": "cardiac", ...}
    current_allocation = read_json("current_allocation.json")

    logger.info(
        "Loaded inputs: %d blocks, %d services, %d current allocations",
        len(blocks), len(services), len(current_allocation),
    )

    return {
        "blocks": blocks,
        "services": services,
        "current_allocation": current_allocation,
    }
```

---

## Step 2: Estimate Demand

*The pseudocode calls this `estimate_demand`. For this example, demand is pre-calculated and included in the service profiles (the `weekly_hours_needed` field). In production, you'd run a time series model or trailing average over 6-12 months of case history.*

```python
def estimate_demand(services: list[dict]) -> dict:
    """
    Build demand profiles from service data.

    In production, this would query historical case logs and compute:
    - Trailing average weekly OR-hours per service
    - Growth/decline trends
    - Seasonal adjustments
    - Known future changes (new surgeon starting, retirements)

    Here we use the pre-calculated values from the input file.

    Returns:
        Map of service_id to demand profile dict.
    """
    demand = {}
    for svc in services:
        demand[svc["service_id"]] = {
            "weekly_hours_needed": svc["weekly_hours_needed"],
            "compatible_rooms": svc["compatible_rooms"],
            "operating_days": svc["operating_days"],
            # Minimum useful block allocation: at least 70% of stated need.
            "min_hours": svc["weekly_hours_needed"] * FAIRNESS_THRESHOLD,
        }
    return demand
```

---

## Step 3: Formulate the Optimization Model

*The pseudocode calls this `formulate_model`. This is the core of the recipe: defining decision variables, constraints, and the objective function using PuLP's modeling language.*

```python
def formulate_model(
    blocks: list[dict],
    services: list[dict],
    demand: dict,
    current_allocation: dict,
) -> pulp.LpProblem:
    """
    Build the mixed-integer programming model for block scheduling.

    Decision: which service gets which block?
    Objective: maximize utilization match + fairness, minimize disruption.
    Constraints: room capability, surgeon availability, one service per block.

    This returns a PuLP model object ready to be solved.
    """

    # Create the optimization problem. We're maximizing (utilization - disruption).
    model = pulp.LpProblem("OR_Block_Scheduling", pulp.LpMaximize)

    # --- DECISION VARIABLES ---
    # x[service_id][block_id] = 1 if that service is assigned that block, else 0.
    # PuLP creates these as binary (0/1) variables.
    x = {}
    for svc in services:
        x[svc["service_id"]] = {}
        for block in blocks:
            var_name = f"assign_{svc['service_id']}_{block['block_id']}"
            x[svc["service_id"]][block["block_id"]] = pulp.LpVariable(
                var_name, cat=pulp.LpBinary
            )

    # --- HARD CONSTRAINTS ---

    # Constraint 1: Each block assigned to at most one service.
    # (A block can also be unassigned, which is fine. Not every slot needs filling.)
    for block in blocks:
        model += (
            pulp.lpSum(
                x[svc["service_id"]][block["block_id"]] for svc in services
            )
            <= 1,
            f"one_service_per_block_{block['block_id']}",
        )

    # Constraint 2: Room capability. A service can only use rooms it's qualified for.
    # If Cardiac needs bypass infrastructure and OR3 doesn't have it, x[cardiac][OR3-*] = 0.
    for svc in services:
        sid = svc["service_id"]
        compatible = set(demand[sid]["compatible_rooms"])
        for block in blocks:
            if block["room"] not in compatible:
                model += (
                    x[sid][block["block_id"]] == 0,
                    f"room_cap_{sid}_{block['block_id']}",
                )

    # Constraint 3: Surgeon availability. Services can only use blocks on days
    # their surgeons operate.
    for svc in services:
        sid = svc["service_id"]
        avail_days = set(demand[sid]["operating_days"])
        for block in blocks:
            if block["day"] not in avail_days:
                model += (
                    x[sid][block["block_id"]] == 0,
                    f"avail_{sid}_{block['block_id']}",
                )

    # Constraint 4: Minimum allocation (fairness floor).
    # Each service gets at least min_hours of block time.
    for svc in services:
        sid = svc["service_id"]
        min_hrs = demand[sid]["min_hours"]
        model += (
            pulp.lpSum(
                x[sid][b["block_id"]] * b["duration_hours"] for b in blocks
            )
            >= min_hrs,
            f"min_alloc_{sid}",
        )

    # --- OBJECTIVE FUNCTION ---

    # Component 1: Utilization match.
    # Reward allocations that closely match demand. We penalize the gap between
    # what a service needs and what it gets using auxiliary variables.
    # (PuLP can't do abs() directly, so we use a linear approximation:
    #  reward = allocated_hours, capped at demand. Over-allocation gets no extra credit.)
    utilization_score = []
    for svc in services:
        sid = svc["service_id"]
        needed = demand[sid]["weekly_hours_needed"]
        allocated = pulp.lpSum(
            x[sid][b["block_id"]] * b["duration_hours"] for b in blocks
        )
        # Simple linear reward: each hour allocated toward need is valuable.
        # Hours beyond need are wasted (but we don't penalize, just don't reward).
        # We cap the reward at the demand level using a min constraint trick.
        # For simplicity here, just use allocated hours directly. The constraint
        # that limits total blocks to <= actual capacity prevents gross over-allocation.
        utilization_score.append(allocated)

    # Component 2: Disruption penalty.
    # Every block that changes hands from the current schedule costs us.
    disruption_penalty = []
    for svc in services:
        sid = svc["service_id"]
        for block in blocks:
            bid = block["block_id"]
            current_owner = current_allocation.get(bid)
            if current_owner and current_owner != sid:
                # Assigning this block to a service that doesn't currently own it
                # incurs a disruption cost.
                disruption_penalty.append(x[sid][bid])

    # Component 3: Fairness bonus.
    # Services currently below the fairness threshold get a bonus for each
    # additional hour they receive. This tilts the optimizer toward equity.
    fairness_bonus = []
    for svc in services:
        sid = svc["service_id"]
        needed = demand[sid]["weekly_hours_needed"]
        current_hours = sum(
            b["duration_hours"]
            for b in blocks
            if current_allocation.get(b["block_id"]) == sid
        )
        if current_hours < needed * FAIRNESS_THRESHOLD:
            # This service is underserved. Bonus for allocating to them.
            allocated = pulp.lpSum(
                x[sid][b["block_id"]] * b["duration_hours"] for b in blocks
            )
            fairness_bonus.append(allocated)

    # Combine into the final objective.
    model += (
        WEIGHTS["utilization"] * pulp.lpSum(utilization_score)
        - WEIGHTS["disruption"] * pulp.lpSum(disruption_penalty)
        + WEIGHTS["fairness_bonus"] * pulp.lpSum(fairness_bonus)
    )

    logger.info(
        "Model formulated: %d variables, %d constraints",
        model.numVariables(),
        model.numConstraints(),
    )

    return model, x
```

---

## Step 4: Solve and Extract Solution

*The pseudocode calls this `solve_and_extract`. We invoke the solver and pull out the block assignments from the solution.*

```python
def solve_model(
    model: pulp.LpProblem,
    x: dict,
    blocks: list[dict],
    services: list[dict],
) -> dict:
    """
    Solve the optimization model and extract the block schedule.

    Returns:
        Dictionary with status, schedule (block_id -> service_id mapping),
        objective value, and solve time.
    """

    # Configure and invoke the solver.
    # CBC ships with PuLP. For better performance on large instances,
    # swap to HiGHS: solver = pulp.HiGHS_CMD(timeLimit=SOLVER_CONFIG["max_seconds"])
    solver = pulp.PULP_CBC_CMD(
        msg=0,  # suppress solver console output
        timeLimit=SOLVER_CONFIG["max_seconds"],
        gapRel=SOLVER_CONFIG["gap_tolerance"],
    )

    start_time = datetime.now(timezone.utc)
    model.solve(solver)
    solve_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()

    status = pulp.LpStatus[model.status]
    logger.info("Solver finished: status=%s, time=%.1fs", status, solve_seconds)

    if status == "Infeasible":
        # The constraints are contradictory. No valid schedule exists.
        # In production, you'd identify which constraints conflict.
        logger.error("Model is infeasible. Check constraint compatibility.")
        return {
            "status": "INFEASIBLE",
            "schedule": {},
            "objective_value": None,
            "solve_seconds": solve_seconds,
        }

    # Extract the solution: which service got which block?
    schedule = {}
    for svc in services:
        sid = svc["service_id"]
        for block in blocks:
            bid = block["block_id"]
            if pulp.value(x[sid][bid]) == 1:
                schedule[bid] = sid

    return {
        "status": status.upper(),
        "schedule": schedule,
        "objective_value": pulp.value(model.objective),
        "solve_seconds": solve_seconds,
    }
```

---

## Step 5: Analyze the Solution

*The pseudocode calls this `analyze_solution`. Compare the new schedule against the current one and compute metrics the block committee cares about.*

```python
def analyze_solution(
    schedule: dict,
    blocks: list[dict],
    services: list[dict],
    demand: dict,
    current_allocation: dict,
) -> dict:
    """
    Compute per-service and aggregate metrics for the proposed schedule.

    This is what the block committee actually looks at: who gains time,
    who loses time, and what the expected utilization improvement is.
    """

    # Build a lookup for block durations.
    block_hours = {b["block_id"]: b["duration_hours"] for b in blocks}

    analysis = {}
    for svc in services:
        sid = svc["service_id"]

        # Hours under the new schedule.
        new_hours = sum(
            block_hours[bid] for bid, owner in schedule.items() if owner == sid
        )

        # Hours under the current schedule.
        current_hours = sum(
            block_hours[bid]
            for bid, owner in current_allocation.items()
            if owner == sid
        )

        needed = demand[sid]["weekly_hours_needed"]
        # Expected utilization: ratio of demand to allocation.
        # >1.0 means under-allocated (demand exceeds supply).
        # <1.0 means over-allocated (some time will sit empty).
        expected_util = needed / new_hours if new_hours > 0 else 0.0

        analysis[sid] = {
            "service_name": svc["name"],
            "allocated_hours": new_hours,
            "previous_hours": current_hours,
            "change_hours": new_hours - current_hours,
            "weekly_demand_hours": needed,
            "expected_utilization": round(min(expected_util, 1.0), 2),
        }

    # Aggregate metrics.
    total_allocated = sum(a["allocated_hours"] for a in analysis.values())
    total_demand = sum(a["weekly_demand_hours"] for a in analysis.values())
    blocks_changed = sum(
        1
        for bid, new_owner in schedule.items()
        if current_allocation.get(bid) != new_owner
    )
    total_blocks = len(blocks)

    # Fairness: the worst-off service's allocation ratio.
    fairness_ratios = [
        a["allocated_hours"] / a["weekly_demand_hours"]
        for a in analysis.values()
        if a["weekly_demand_hours"] > 0
    ]
    min_fairness = round(min(fairness_ratios), 2) if fairness_ratios else 0.0

    summary = {
        "total_expected_utilization": round(total_demand / total_allocated, 2)
        if total_allocated > 0
        else 0.0,
        "blocks_changed": blocks_changed,
        "total_blocks": total_blocks,
        "disruption_pct": round(100 * blocks_changed / total_blocks, 1)
        if total_blocks > 0
        else 0.0,
        "fairness_min_ratio": min_fairness,
    }

    return {"per_service": analysis, "summary": summary}
```

---

## Step 6: Store Results

*The pseudocode calls this `store_and_notify`. Write the optimized schedule and analysis to S3 for the dashboard and committee review.*

```python
def store_results(
    bucket: str,
    run_id: str,
    solution: dict,
    analysis: dict,
) -> str:
    """
    Write optimization results to S3 for downstream consumption
    (QuickSight dashboards, committee review tools).

    Returns:
        The S3 prefix where results were stored.
    """
    output_prefix = f"optimization-results/{run_id}"

    def write_json(key: str, data: Any) -> None:
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{output_prefix}/{key}",
            Body=json.dumps(data, indent=2, default=str).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="aws:kms",
        )

    # The optimized block schedule.
    write_json("schedule.json", solution["schedule"])

    # Per-service analysis and summary metrics.
    write_json("analysis.json", analysis)

    # Run metadata for audit trail.
    metadata = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": solution["status"],
        "objective_value": solution["objective_value"],
        "solve_seconds": solution["solve_seconds"],
        "solver": SOLVER_CONFIG["solver"],
    }
    write_json("metadata.json", metadata)

    logger.info("Results stored at s3://%s/%s/", bucket, output_prefix)
    return f"s3://{bucket}/{output_prefix}/"
```

---

## Full Pipeline

Assembles all steps into a single callable function. Run this to see the full optimization flow end-to-end.

```python
def run_block_optimization(
    bucket: str,
    input_prefix: str,
    run_id: str | None = None,
) -> dict:
    """
    Execute the full OR block scheduling optimization pipeline.

    Args:
        bucket: S3 bucket for inputs and outputs
        input_prefix: S3 prefix containing the input JSON files
        run_id: Optional run identifier (generated if not provided)

    Returns:
        Complete results including schedule, analysis, and metadata.
    """
    if run_id is None:
        run_id = f"opt-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    print(f"=== OR Block Scheduling Optimization: {run_id} ===\n")

    # Step 1: Load inputs.
    print("Step 1: Loading optimization inputs from S3...")
    inputs = load_optimization_inputs(bucket, input_prefix)
    print(f"  Loaded {len(inputs['blocks'])} blocks, {len(inputs['services'])} services\n")

    # Step 2: Estimate demand.
    print("Step 2: Building demand profiles...")
    demand = estimate_demand(inputs["services"])
    for sid, profile in demand.items():
        print(f"  {sid}: needs {profile['weekly_hours_needed']}h/week, "
              f"min {profile['min_hours']:.0f}h")
    print()

    # Step 3: Formulate the model.
    print("Step 3: Formulating optimization model...")
    model, x = formulate_model(
        inputs["blocks"],
        inputs["services"],
        demand,
        inputs["current_allocation"],
    )
    print(f"  Variables: {model.numVariables()}, Constraints: {model.numConstraints()}\n")

    # Step 4: Solve.
    print("Step 4: Solving (this may take a few seconds)...")
    solution = solve_model(model, x, inputs["blocks"], inputs["services"])
    print(f"  Status: {solution['status']}")
    print(f"  Objective value: {solution['objective_value']:.2f}")
    print(f"  Solve time: {solution['solve_seconds']:.1f}s\n")

    if solution["status"] == "INFEASIBLE":
        print("ERROR: No feasible schedule exists under current constraints.")
        print("Review room capabilities and minimum allocation requirements.")
        return solution

    # Step 5: Analyze the solution.
    print("Step 5: Analyzing solution...")
    analysis = analyze_solution(
        solution["schedule"],
        inputs["blocks"],
        inputs["services"],
        demand,
        inputs["current_allocation"],
    )
    print(f"  Expected utilization: {analysis['summary']['total_expected_utilization']}")
    print(f"  Blocks changed: {analysis['summary']['blocks_changed']}/{analysis['summary']['total_blocks']} "
          f"({analysis['summary']['disruption_pct']}%)")
    print(f"  Fairness floor: {analysis['summary']['fairness_min_ratio']}")
    print()
    print("  Per-service breakdown:")
    for sid, metrics in analysis["per_service"].items():
        change = metrics["change_hours"]
        direction = "+" if change >= 0 else ""
        print(f"    {metrics['service_name']}: {metrics['allocated_hours']}h "
              f"({direction}{change}h), util={metrics['expected_utilization']}")
    print()

    # Step 6: Store results.
    print("Step 6: Storing results to S3...")
    output_path = store_results(bucket, run_id, solution, analysis)
    print(f"  Results at: {output_path}\n")

    print("=== Optimization complete ===")
    return {
        "run_id": run_id,
        "solution": solution,
        "analysis": analysis,
        "output_path": output_path,
    }

# --- Entry point for local testing ---
if __name__ == "__main__":
    # Point this at your S3 bucket with the sample input files.
    result = run_block_optimization(
        bucket="my-hospital-optimization",
        input_prefix="inputs/2026-Q3",
    )
    print("\n--- Final Output ---")
    print(json.dumps(result["analysis"]["summary"], indent=2))
```

---

## Sample Input Files

To run this example, you need three JSON files in your S3 input prefix. Here's what they look like for a small 4-OR, 5-service hospital:

**blocks.json** (the available time slots):

```json
[
  {"block_id": "OR1-MON-AM", "room": "OR1", "day": "Monday", "slot": "AM", "duration_hours": 4.0},
  {"block_id": "OR1-MON-PM", "room": "OR1", "day": "Monday", "slot": "PM", "duration_hours": 4.0},
  {"block_id": "OR1-TUE-AM", "room": "OR1", "day": "Tuesday", "slot": "AM", "duration_hours": 4.0},
  {"block_id": "OR1-TUE-PM", "room": "OR1", "day": "Tuesday", "slot": "PM", "duration_hours": 4.0},
  {"block_id": "OR2-MON-AM", "room": "OR2", "day": "Monday", "slot": "AM", "duration_hours": 4.0},
  {"block_id": "OR2-MON-PM", "room": "OR2", "day": "Monday", "slot": "PM", "duration_hours": 4.0},
  {"block_id": "OR2-TUE-AM", "room": "OR2", "day": "Tuesday", "slot": "AM", "duration_hours": 4.0},
  {"block_id": "OR2-TUE-PM", "room": "OR2", "day": "Tuesday", "slot": "PM", "duration_hours": 4.0},
  {"block_id": "OR3-MON-AM", "room": "OR3", "day": "Monday", "slot": "AM", "duration_hours": 4.0},
  {"block_id": "OR3-MON-PM", "room": "OR3", "day": "Monday", "slot": "PM", "duration_hours": 4.0},
  {"block_id": "OR3-TUE-AM", "room": "OR3", "day": "Tuesday", "slot": "AM", "duration_hours": 4.0},
  {"block_id": "OR3-TUE-PM", "room": "OR3", "day": "Tuesday", "slot": "PM", "duration_hours": 4.0},
  {"block_id": "OR4-MON-AM", "room": "OR4", "day": "Monday", "slot": "AM", "duration_hours": 4.0},
  {"block_id": "OR4-MON-PM", "room": "OR4", "day": "Monday", "slot": "PM", "duration_hours": 4.0},
  {"block_id": "OR4-TUE-AM", "room": "OR4", "day": "Tuesday", "slot": "AM", "duration_hours": 4.0},
  {"block_id": "OR4-TUE-PM", "room": "OR4", "day": "Tuesday", "slot": "PM", "duration_hours": 4.0}
]
```

**services.json** (surgical services requesting time):

```json
[
  {
    "service_id": "ortho",
    "name": "Orthopedics",
    "weekly_hours_needed": 20,
    "compatible_rooms": ["OR1", "OR2", "OR3", "OR4"],
    "operating_days": ["Monday", "Tuesday"]
  },
  {
    "service_id": "cardiac",
    "name": "Cardiac Surgery",
    "weekly_hours_needed": 16,
    "compatible_rooms": ["OR3", "OR4"],
    "operating_days": ["Monday", "Tuesday"]
  },
  {
    "service_id": "general",
    "name": "General Surgery",
    "weekly_hours_needed": 12,
    "compatible_rooms": ["OR1", "OR2", "OR3", "OR4"],
    "operating_days": ["Monday", "Tuesday"]
  },
  {
    "service_id": "neuro",
    "name": "Neurosurgery",
    "weekly_hours_needed": 8,
    "compatible_rooms": ["OR1", "OR2"],
    "operating_days": ["Monday", "Tuesday"]
  },
  {
    "service_id": "uro",
    "name": "Urology",
    "weekly_hours_needed": 8,
    "compatible_rooms": ["OR1", "OR2", "OR3"],
    "operating_days": ["Monday", "Tuesday"]
  }
]
```

**current_allocation.json** (the existing schedule to compare against):

```json
{
  "OR1-MON-AM": "ortho",
  "OR1-MON-PM": "ortho",
  "OR1-TUE-AM": "ortho",
  "OR1-TUE-PM": "general",
  "OR2-MON-AM": "general",
  "OR2-MON-PM": "general",
  "OR2-TUE-AM": "neuro",
  "OR2-TUE-PM": "neuro",
  "OR3-MON-AM": "cardiac",
  "OR3-MON-PM": "cardiac",
  "OR3-TUE-AM": "ortho",
  "OR3-TUE-PM": "uro",
  "OR4-MON-AM": "cardiac",
  "OR4-MON-PM": "ortho",
  "OR4-TUE-AM": "uro",
  "OR4-TUE-PM": "general"
}
```

Note: Total available hours = 16 blocks x 4 hours = 64 hours. Total demand = 20 + 16 + 12 + 8 + 8 = 64 hours. This is a tight problem where the optimizer really matters because demand equals supply exactly.

---

## The Gap Between This and Production

This example demonstrates a working optimization pipeline. PuLP formulates the model correctly, CBC solves it, and you get a valid block schedule out. But the distance between this and a system you'd deploy at a hospital is significant. Here's where that gap lives:

**Solver choice for scale.** CBC is fine for our 16-block, 5-service toy problem. A real hospital with 60+ blocks (15 ORs x 10 half-day slots per week) and 20 services creates a model with 1,200+ binary variables. CBC will still solve it, but may take minutes where HiGHS or Gurobi would take seconds. For production, install HiGHS (`pip install highspy`) and use `pulp.HiGHS_CMD()` as your solver. The model code stays identical.

**Error handling.** If S3 is unreachable, if the input JSON is malformed, if the solver times out without finding a feasible solution, this code crashes. Production wraps every external call in try/except, retries transient failures, and has clear error reporting for each failure mode (bad input data vs. infeasible model vs. solver timeout).

**Input validation.** This code trusts its input files completely. Production validates that every block references a room that exists, every service references compatible rooms that are in the blocks list, demand values are positive, and the current allocation references real block IDs. Bad input data is the most common reason real optimization pipelines produce garbage.

**Linearization.** The objective function here uses a simplified linear approximation. The pseudocode mentions penalizing both over-allocation and under-allocation, which requires absolute value (non-linear). Production implementations use standard MIP linearization tricks: introduce auxiliary variables and piecewise constraints to model abs(). PuLP supports this but it adds complexity.

**Scenario management.** The block committee will want to run 5-10 scenarios: "lock Cardiac's Monday morning, re-optimize everything else." Production systems support constraint locking (set `x[cardiac][OR3-MON-AM] == 1` as a fixed constraint) and batch scenario execution. This example solves a single scenario.

**SageMaker containerization.** In the AWS architecture, this code runs inside a SageMaker Processing Job with a custom Docker container that includes the solver. The container handles input/output path conventions, health checks, and graceful shutdown. The Lambda orchestrator triggers the Processing Job via the SageMaker API and polls for completion.

**Logging and observability.** Production logs every optimization run with: input fingerprint (hash of input data), model statistics (variables, constraints), solver progress, solution quality metrics, and wall-clock time. CloudWatch dashboards track solve time trends and solution quality over successive runs.

**IAM and encryption.** The SageMaker Processing Job needs a tightly scoped execution role: `s3:GetObject` on the input prefix, `s3:PutObject` on the output prefix, `kms:Decrypt` and `kms:GenerateDataKey` for the encryption keys. Volume encryption must be enabled on the Processing Job. All S3 writes use SSE-KMS.

**VPC and network.** Production runs in a private subnet with VPC endpoints for S3. The solver never needs internet access. If your EHR data feed is on-premises, the Lambda orchestrator may need a VPN or Direct Connect path.

**Testing.** This example has no tests. Production includes: unit tests for the model formulation (known inputs produce expected variable/constraint counts), solver tests against known-optimal small instances, integration tests that exercise the full S3 pipeline with synthetic data, and regression tests that verify the model doesn't become infeasible when new constraints are added.

**The human layer.** The code produces a schedule. The hard part that no code solves is getting the block committee to accept it. Build a QuickSight dashboard (or similar) that lets committee members interactively explore the proposed schedule, compare it against the current one, and run what-if scenarios without touching the optimization code. The tool succeeds or fails based on whether humans trust its output.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 14.5](chapter14.05-operating-room-block-scheduling) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
