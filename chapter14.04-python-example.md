# Recipe 14.4: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the nurse staffing optimization from Recipe 14.4. It demonstrates the core concepts (problem formulation, constraint definition, solver invocation, schedule extraction, and real-time call-off handling) using Google OR-Tools' CP-SAT solver. It is not production-ready. The staff roster is tiny, the demand is static, and there's no integration with HR systems or mobile notifications. Think of it as the whiteboard sketch that helps you understand the shape of the real system. A starting point, not a destination.
>
> The main recipe uses SageMaker for solver hosting and EventBridge for real-time events. This example runs everything locally with OR-Tools and writes results to DynamoDB. The optimization math is identical; the infrastructure is stripped away so you can focus on the model.

---

## Setup

You'll need the constraint programming solver and AWS SDK installed:

```bash
pip install boto3 ortools
```

`ortools` is Google's open-source optimization suite. The CP-SAT solver inside it handles the binary decision variables and complex constraints of nurse scheduling extremely well. It's free, actively maintained, and fast enough for hospital-scale problems (50-200 nurses, 2-4 week horizons) without a commercial license.

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `dynamodb:PutItem`
- `dynamodb:GetItem`
- `dynamodb:Query`
- `dynamodb:Scan`

For the full pipeline (with SageMaker hosting and EventBridge routing), you'd also need `sagemaker:InvokeEndpoint`, `events:PutEvents`, and `sns:Publish`, but this example keeps the focus on the optimization itself.

---

## Configuration and Constants

```python
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config
from ortools.sat.python import cp_model

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Table where we store published schedules.
SCHEDULE_TABLE_NAME = "nurse-schedules"

# Shift definitions. Each shift has a name, start hour, end hour, and duration.
# 12-hour shifts are standard for inpatient nursing.
SHIFTS = {
    "day":   {"start": 7, "end": 19, "duration_hours": 12},
    "night": {"start": 19, "end": 7, "duration_hours": 12},
}

# Minimum hours between consecutive shifts (union/labor rule).
# A nurse finishing a night shift at 7 AM cannot start a day shift at 7 AM.
MIN_REST_HOURS = 11

# Maximum hours per week before overtime triggers.
MAX_HOURS_PER_WEEK = 60

# Maximum consecutive days a nurse can work (soft constraint).
MAX_CONSECUTIVE_DAYS = 5

# Penalty weights for soft constraints in the objective function.
# Higher weight = solver tries harder to avoid violating that constraint.
PENALTY_WEIGHTS = {
    "overtime": 10,          # each overtime shift costs this much in the objective
    "fairness": 8,           # penalty per unit of weekend deviation from average
    "consecutive_days": 5,   # penalty for exceeding MAX_CONSECUTIVE_DAYS
    "preference_violation": 3,  # penalty per violated shift preference
}

# Solver time limit. For batch scheduling (2-week horizon, ~40 nurses),
# 120 seconds is usually enough to get within 2-3% of optimal.
SOLVER_TIME_LIMIT_SECONDS = 120
```

---

## Sample Data: Staff Roster and Demand

In production, this comes from HR systems, the EHR, and a demand forecasting model. Here we hardcode a small example so you can see the data structures the solver expects.

```python
# Staff roster: each nurse has an ID, name, FTE status, certifications,
# and shift preferences. Certifications determine which units they can cover.
# Preferences are soft constraints (the solver tries to honor them but won't
# violate hard constraints to do so).

STAFF_ROSTER = [
    {
        "id": "RN-001", "name": "Sarah Chen", "fte": 1.0,
        "certifications": ["med-surg", "charge"],
        "preference": "day",  # prefers day shifts
        "max_hours_per_period": 72,  # 3 x 12-hour shifts per week x 2 weeks = 72 target
    },
    {
        "id": "RN-002", "name": "Marcus Johnson", "fte": 1.0,
        "certifications": ["med-surg", "tele"],
        "preference": "night",
        "max_hours_per_period": 72,
    },
    {
        "id": "RN-003", "name": "Priya Patel", "fte": 0.75,
        "certifications": ["med-surg", "charge", "tele"],
        "preference": "day",
        "max_hours_per_period": 54,  # 0.75 FTE
    },
    {
        "id": "RN-004", "name": "James Wilson", "fte": 1.0,
        "certifications": ["med-surg"],
        "preference": "night",
        "max_hours_per_period": 72,
    },
    {
        "id": "RN-005", "name": "Maria Garcia", "fte": 1.0,
        "certifications": ["med-surg", "charge"],
        "preference": "day",
        "max_hours_per_period": 72,
    },
    {
        "id": "RN-006", "name": "David Kim", "fte": 0.5,
        "certifications": ["med-surg", "tele"],
        "preference": "night",
        "max_hours_per_period": 36,  # 0.5 FTE
    },
    {
        "id": "RN-007", "name": "Lisa Thompson", "fte": 1.0,
        "certifications": ["med-surg"],
        "preference": "day",
        "max_hours_per_period": 72,
    },
    {
        "id": "RN-008", "name": "Robert Brown", "fte": 1.0,
        "certifications": ["med-surg", "charge", "tele"],
        "preference": "night",
        "max_hours_per_period": 72,
    },
]

# Demand: how many nurses are needed per shift per day.
# In production, this comes from a census forecasting model (Recipe 12.5).
# For this small example roster (8 nurses), we use reduced demand.
# A real 36-bed med-surg unit would need 5 day / 4 night with 40+ nurses.
DEMAND = {
    "day": 3,
    "night": 2,
}

# At least one charge-certified nurse must be on every shift.
CHARGE_REQUIRED_PER_SHIFT = 1

# PTO blocks: nurses who are unavailable on specific days (0-indexed from period start).
PTO_BLOCKS = {
    "RN-003": [2, 3, 4],       # Priya is off days 2-4
    "RN-006": [0, 1, 5, 6],   # David is off days 0-1 and 5-6
}

# Schedule period: 7 days (one week). Production would typically be 14 days.
NUM_DAYS = 7
```

---

## Step 1: Assemble the Optimization Problem

*The pseudocode calls this `assemble_scheduling_problem(schedule_period)`. It gathers all inputs into a single problem definition the solver can consume.*

```python
def assemble_problem(staff, demand, num_days, pto_blocks):
    """
    Package all scheduling inputs into a structured problem definition.

    In production, this function would pull from HR APIs, the demand forecasting
    service, and the constraint configuration store. Here we just organize the
    hardcoded data into the shape the solver expects.

    Args:
        staff:      List of nurse dictionaries (roster)
        demand:     Dict of shift_name -> required headcount
        num_days:   Number of days in the scheduling period
        pto_blocks: Dict of nurse_id -> list of unavailable day indices

    Returns:
        A problem dict containing everything the solver needs.
    """
    problem = {
        "staff": staff,
        "demand": demand,
        "num_days": num_days,
        "shifts": list(SHIFTS.keys()),
        "pto_blocks": pto_blocks,
        "hard_constraints": {
            "min_rest_hours": MIN_REST_HOURS,
            "max_hours_per_week": MAX_HOURS_PER_WEEK,
            "charge_required_per_shift": CHARGE_REQUIRED_PER_SHIFT,
        },
        "soft_constraints": {
            "max_consecutive_days": MAX_CONSECUTIVE_DAYS,
            "penalty_weights": PENALTY_WEIGHTS,
        },
    }

    logger.info(
        "Problem assembled: %d nurses, %d days, %d shifts/day, %d total slots to fill",
        len(staff), num_days, len(SHIFTS), sum(demand.values()) * num_days,
    )
    return problem
```

---

## Step 2: Formulate the CP-SAT Model

*The pseudocode calls this `formulate_optimization_model(problem)`. This is the intellectual core: translating business rules into mathematical constraints that the solver can reason about.*

```python
def formulate_model(problem):
    """
    Build the CP-SAT model with decision variables, hard constraints,
    soft constraints, and the objective function.

    The CP-SAT solver works with integer variables and linear constraints.
    Each nurse-shift-day combination is a boolean variable (0 or 1).
    Constraints are linear inequalities over those variables.
    The objective is a weighted sum of penalty terms we want to minimize.

    Returns:
        Tuple of (model, variables_dict) where variables_dict maps
        (nurse_id, shift, day) -> BoolVar for solution extraction.
    """
    model = cp_model.CpModel()
    staff = problem["staff"]
    shifts = problem["shifts"]
    num_days = problem["num_days"]
    pto_blocks = problem["pto_blocks"]

    # ---------------------------------------------------------------
    # DECISION VARIABLES
    # x[(nurse_id, shift, day)] = 1 if nurse works that shift on that day
    # ---------------------------------------------------------------
    x = {}
    for nurse in staff:
        for shift in shifts:
            for day in range(num_days):
                var_name = f"x_{nurse['id']}_{shift}_{day}"
                x[(nurse["id"], shift, day)] = model.NewBoolVar(var_name)

    # ---------------------------------------------------------------
    # HARD CONSTRAINTS
    # ---------------------------------------------------------------

    # 1. Each nurse works at most one shift per day.
    #    You can't be on days AND nights simultaneously.
    for nurse in staff:
        for day in range(num_days):
            model.Add(
                sum(x[(nurse["id"], shift, day)] for shift in shifts) <= 1
            )

    # 2. Minimum rest between shifts.
    #    Night shift ends at 7 AM. Day shift starts at 7 AM.
    #    Gap is 0 hours, which violates the 11-hour minimum.
    #    So: if you work night on day D, you cannot work day on day D+1.
    for nurse in staff:
        for day in range(num_days - 1):
            # Night shift on day D conflicts with day shift on day D+1
            model.Add(
                x[(nurse["id"], "night", day)] + x[(nurse["id"], "day", day + 1)] <= 1
            )

    # 3. Demand coverage: enough nurses on every shift.
    for shift in shifts:
        for day in range(num_days):
            model.Add(
                sum(x[(nurse["id"], shift, day)] for nurse in staff)
                >= problem["demand"][shift]
            )

    # 4. Charge nurse coverage: at least one charge-certified nurse per shift.
    charge_nurses = [n for n in staff if "charge" in n["certifications"]]
    for shift in shifts:
        for day in range(num_days):
            model.Add(
                sum(x[(n["id"], shift, day)] for n in charge_nurses)
                >= problem["hard_constraints"]["charge_required_per_shift"]
            )

    # 5. PTO blocks: nurse is unavailable on approved days.
    for nurse_id, blocked_days in pto_blocks.items():
        for day in blocked_days:
            if day < num_days:
                for shift in shifts:
                    model.Add(x[(nurse_id, shift, day)] == 0)

    # 6. Maximum hours per scheduling period (based on FTE).
    for nurse in staff:
        total_shifts = sum(
            x[(nurse["id"], shift, day)]
            for shift in shifts
            for day in range(num_days)
        )
        # Each shift is 12 hours. Max shifts = max_hours / 12.
        max_shifts = nurse["max_hours_per_period"] // 12
        model.Add(total_shifts <= max_shifts)

    # ---------------------------------------------------------------
    # SOFT CONSTRAINTS (penalized in objective)
    # ---------------------------------------------------------------

    penalties = []

    # Overtime penalty: shifts beyond the contracted target.
    # Target shifts = FTE * days_in_period / 2 (since each shift covers half a day).
    # Anything above target incurs a penalty.
    for nurse in staff:
        target_shifts = int(nurse["fte"] * num_days * 12 / 24)  # expected shifts
        total_shifts = sum(
            x[(nurse["id"], shift, day)]
            for shift in shifts
            for day in range(num_days)
        )
        # Create an auxiliary variable for overtime (shifts above target)
        overtime = model.NewIntVar(0, num_days, f"overtime_{nurse['id']}")
        model.Add(overtime >= total_shifts - target_shifts)
        # Note: overtime >= 0 is already enforced by the variable's lower bound (0).
        penalties.append(overtime * PENALTY_WEIGHTS["overtime"])

    # Weekend fairness: penalize deviation from average weekend shifts.
    # Identify weekend days (assuming day 5 = Saturday, day 6 = Sunday for a
    # Mon-start period). Adjust indices for your actual start day.
    weekend_days = [d for d in range(num_days) if d % 7 >= 5]

    if weekend_days:
        weekend_shifts_per_nurse = []
        for nurse in staff:
            ws = sum(
                x[(nurse["id"], shift, day)]
                for shift in shifts
                for day in weekend_days
            )
            weekend_shifts_per_nurse.append(ws)

        # Penalize each nurse's deviation from the minimum weekend count.
        # This encourages equitable distribution.
        min_weekends = model.NewIntVar(0, len(weekend_days) * 2, "min_weekends")
        model.AddMinEquality(min_weekends, weekend_shifts_per_nurse)

        for i, nurse in enumerate(staff):
            deviation = model.NewIntVar(0, len(weekend_days) * 2, f"wknd_dev_{nurse['id']}")
            model.Add(deviation >= weekend_shifts_per_nurse[i] - min_weekends)
            penalties.append(deviation * PENALTY_WEIGHTS["fairness"])

    # Preference violation: penalize assignments that don't match preferred shift.
    for nurse in staff:
        preferred = nurse.get("preference")
        if preferred and preferred in shifts:
            non_preferred = [s for s in shifts if s != preferred]
            for shift in non_preferred:
                for day in range(num_days):
                    # Each assignment to a non-preferred shift incurs a penalty
                    penalties.append(
                        x[(nurse["id"], shift, day)] * PENALTY_WEIGHTS["preference_violation"]
                    )

    # Consecutive days penalty: penalize stretches longer than MAX_CONSECUTIVE_DAYS.
    for nurse in staff:
        for start_day in range(num_days - MAX_CONSECUTIVE_DAYS):
            # If a nurse works MAX_CONSECUTIVE_DAYS+1 consecutive days, penalize.
            window = MAX_CONSECUTIVE_DAYS + 1
            if start_day + window <= num_days:
                days_worked_in_window = sum(
                    x[(nurse["id"], shift, day)]
                    for shift in shifts
                    for day in range(start_day, start_day + window)
                )
                # If all days in the window are worked, that's a violation.
                excess = model.NewIntVar(0, window, f"consec_{nurse['id']}_{start_day}")
                model.Add(excess >= days_worked_in_window - MAX_CONSECUTIVE_DAYS)
                penalties.append(excess * PENALTY_WEIGHTS["consecutive_days"])

    # ---------------------------------------------------------------
    # OBJECTIVE: minimize total penalty
    # ---------------------------------------------------------------
    model.Minimize(sum(penalties))

    logger.info(
        "Model formulated: %d variables, constraints added for %d nurses over %d days",
        len(x), len(staff), num_days,
    )
    return model, x
```

---

## Step 3: Solve and Extract the Schedule

*The pseudocode calls this `solve_and_extract(model, time_limit_seconds)`. We hand the model to CP-SAT and translate the solution back into a human-readable schedule.*

```python
def solve_and_extract(model, x, problem):
    """
    Run the CP-SAT solver and extract the schedule from variable assignments.

    The solver explores the solution space using propagation and search.
    It progressively finds better solutions until it proves optimality or
    hits the time limit. CP-SAT is particularly good at feasibility (finding
    any valid schedule) and handles the complex logical constraints of nurse
    scheduling naturally.

    Returns:
        Dict with status, schedule assignments, and quality metrics.
    """
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_SECONDS
    # Use multiple threads for parallel search (if available).
    solver.parameters.num_search_workers = 4

    logger.info("Solving (time limit: %ds)...", SOLVER_TIME_LIMIT_SECONDS)
    status = solver.Solve(model)

    # Check solver status
    if status == cp_model.INFEASIBLE:
        logger.warning("Problem is INFEASIBLE. Constraints conflict.")
        return {
            "status": "infeasible",
            "message": "No valid schedule exists with current constraints. "
                       "Consider relaxing demand, adding staff, or removing PTO blocks.",
        }

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.error("Solver returned unexpected status: %s", status)
        return {"status": "error", "message": f"Solver status: {status}"}

    # Extract assignments from the solved model
    staff = problem["staff"]
    shifts = problem["shifts"]
    num_days = problem["num_days"]

    schedule = []
    for nurse in staff:
        nurse_shifts = []
        for day in range(num_days):
            for shift in shifts:
                if solver.Value(x[(nurse["id"], shift, day)]) == 1:
                    nurse_shifts.append({
                        "day": day,
                        "shift": shift,
                        "duration_hours": SHIFTS[shift]["duration_hours"],
                    })
        if nurse_shifts:
            schedule.append({
                "nurse_id": nurse["id"],
                "nurse_name": nurse["name"],
                "assignments": nurse_shifts,
                "total_hours": sum(a["duration_hours"] for a in nurse_shifts),
                "total_shifts": len(nurse_shifts),
            })

    # Compute quality metrics
    total_hours = sum(entry["total_hours"] for entry in schedule)
    target_hours = sum(n["max_hours_per_period"] for n in staff)

    # Weekend shift distribution
    weekend_days = [d for d in range(num_days) if d % 7 >= 5]
    weekend_counts = []
    for nurse in staff:
        count = sum(
            1 for day in weekend_days for shift in shifts
            if solver.Value(x[(nurse["id"], shift, day)]) == 1
        )
        weekend_counts.append(count)

    fairness_score = 0.0
    if weekend_counts and max(weekend_counts) > 0:
        # Fairness: 1.0 means perfectly equal, lower means less fair
        fairness_score = 1.0 - (max(weekend_counts) - min(weekend_counts)) / max(max(weekend_counts), 1)

    metrics = {
        "solver_status": "optimal" if status == cp_model.OPTIMAL else "feasible",
        "objective_value": solver.ObjectiveValue(),
        "solve_time_seconds": round(solver.WallTime(), 2),
        "total_shifts_assigned": sum(entry["total_shifts"] for entry in schedule),
        "total_shifts_required": sum(problem["demand"].values()) * num_days,
        "coverage_rate": (
            sum(entry["total_shifts"] for entry in schedule)
            / (sum(problem["demand"].values()) * num_days)
        ),
        "total_hours_assigned": total_hours,
        "fairness_score": round(fairness_score, 3),
        "weekend_shift_range": f"{min(weekend_counts)}-{max(weekend_counts)}" if weekend_counts else "n/a",
    }

    logger.info(
        "Solved in %.1fs. Status: %s. Objective: %.1f. Coverage: %.0f%%",
        metrics["solve_time_seconds"],
        metrics["solver_status"],
        metrics["objective_value"],
        metrics["coverage_rate"] * 100,
    )

    return {
        "status": "solved",
        "schedule": schedule,
        "metrics": metrics,
    }
```

---

## Step 4: Handle Real-Time Call-Offs

*The pseudocode calls this `handle_calloff(calloff_event)`. When a nurse calls in sick, find the best available replacement fast.*

```python
def handle_calloff(calloff_event, current_schedule, staff, pto_blocks):
    """
    Find ranked coverage candidates when a nurse calls off.

    This doesn't re-run the full solver. Instead, it filters the staff roster
    to find eligible replacements and scores them by desirability (cost,
    fairness impact, historical patterns). In production, you'd also factor
    in historical acceptance rates and distance from the facility.

    Args:
        calloff_event: Dict with nurse_id, day, shift of the gap.
        current_schedule: The solved schedule (list of nurse assignment dicts).
        staff: Full staff roster.
        pto_blocks: Current PTO blocks.

    Returns:
        Dict with gap details and ranked candidate list.
    """
    gap_nurse = calloff_event["nurse_id"]
    gap_day = calloff_event["day"]
    gap_shift = calloff_event["shift"]

    logger.info(
        "Call-off: %s on day %d, %s shift. Finding coverage...",
        gap_nurse, gap_day, gap_shift,
    )

    # Build a lookup of who's already working on the gap day
    scheduled_on_gap_day = set()
    nurse_total_shifts = {}
    for entry in current_schedule:
        nurse_total_shifts[entry["nurse_id"]] = entry["total_shifts"]
        for assignment in entry["assignments"]:
            if assignment["day"] == gap_day:
                scheduled_on_gap_day.add(entry["nurse_id"])

    # Also check the day before for rest-rule conflicts
    scheduled_night_before = set()
    if gap_shift == "day" and gap_day > 0:
        for entry in current_schedule:
            for assignment in entry["assignments"]:
                if assignment["day"] == gap_day - 1 and assignment["shift"] == "night":
                    scheduled_night_before.add(entry["nurse_id"])

    # Find eligible candidates
    candidates = []
    for nurse in staff:
        nid = nurse["id"]

        # Skip the nurse who called off
        if nid == gap_nurse:
            continue

        # Skip if already scheduled that day
        if nid in scheduled_on_gap_day:
            continue

        # Skip if on PTO
        if gap_day in pto_blocks.get(nid, []):
            continue

        # Skip if rest rule would be violated (worked night before a day gap)
        if gap_shift == "day" and nid in scheduled_night_before:
            continue

        # Skip if at max hours
        current_shifts = nurse_total_shifts.get(nid, 0)
        max_shifts = nurse["max_hours_per_period"] // 12
        if current_shifts >= max_shifts:
            continue

        # Score the candidate (lower is better for cost; we'll negate for ranking)
        is_overtime = current_shifts >= int(nurse["fte"] * 7 * 12 / 24)
        prefers_this_shift = nurse.get("preference") == gap_shift

        # Simple scoring: prefer non-overtime, prefer matching preference,
        # prefer nurses with fewer total shifts (fairness).
        score = 0
        if not is_overtime:
            score += 50  # strong preference for non-overtime
        if prefers_this_shift:
            score += 20  # bonus for matching preference
        score += max(0, 30 - current_shifts * 5)  # fewer shifts = higher score (fairness)

        candidates.append({
            "nurse_id": nid,
            "nurse_name": nurse["name"],
            "score": score,
            "is_overtime": is_overtime,
            "current_shifts": current_shifts,
            "prefers_this_shift": prefers_this_shift,
        })

    # Sort by score descending (best candidates first)
    candidates.sort(key=lambda c: c["score"], reverse=True)

    logger.info("Found %d eligible candidates for coverage.", len(candidates))

    return {
        "gap": {
            "nurse_id": gap_nurse,
            "day": gap_day,
            "shift": gap_shift,
        },
        "candidates": candidates[:10],  # top 10
        "total_eligible": len(candidates),
    }
```

---

## Step 5: Store the Schedule in DynamoDB

*The pseudocode calls this `publish_schedule(schedule, schedule_type)`. Write the solved schedule to DynamoDB for downstream consumption.*

```python
def store_schedule(result, schedule_period_start):
    """
    Write the solved schedule to DynamoDB.

    Each assignment becomes a separate item, keyed by day and shift+nurse_id.
    This supports the two primary access patterns:
    - "Who's working on day X?" (query by partition key = day)
    - "What's nurse Y's schedule?" (scan with filter, or GSI on nurse_id)

    Args:
        result: The output of solve_and_extract (contains schedule and metrics).
        schedule_period_start: ISO date string for the period start (e.g., "2026-06-08").

    Returns:
        Count of items written.
    """
    if result["status"] != "solved":
        logger.warning("Cannot store schedule with status: %s", result["status"])
        return 0

    table = dynamodb.Table(SCHEDULE_TABLE_NAME)
    items_written = 0
    published_at = datetime.datetime.now(timezone.utc).isoformat()

    for entry in result["schedule"]:
        for assignment in entry["assignments"]:
            # Compute the actual date from the period start + day offset
            start_date = datetime.date.fromisoformat(schedule_period_start)
            actual_date = (start_date + datetime.timedelta(days=assignment["day"])).isoformat()

            item = {
                # Partition key: the date (enables "who's working today?" queries)
                "schedule_date": actual_date,
                # Sort key: shift + nurse_id (unique per assignment)
                "shift_nurse": f"{assignment['shift']}#{entry['nurse_id']}",
                "nurse_id": entry["nurse_id"],
                "nurse_name": entry["nurse_name"],
                "shift": assignment["shift"],
                "duration_hours": assignment["duration_hours"],
                "published_at": published_at,
                "schedule_type": "batch",
                "period_start": schedule_period_start,
            }

            # DynamoDB requires Decimal for numbers, not float.
            table.put_item(Item=item)
            items_written += 1

    # Store the metrics as a summary record
    metrics_item = {
        "schedule_date": f"METRICS#{schedule_period_start}",
        "shift_nurse": "SUMMARY",
        "metrics": json.loads(json.dumps(result["metrics"]), parse_float=Decimal),
        "published_at": published_at,
    }
    table.put_item(Item=metrics_item)
    items_written += 1

    logger.info("Stored %d items in DynamoDB for period starting %s.", items_written, schedule_period_start)
    return items_written
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Lambda handler (or batch job) would call.

```python
def generate_schedule(schedule_period_start="2026-06-08"):
    """
    Run the full nurse staffing optimization pipeline.

    1. Assemble the problem (gather inputs)
    2. Formulate the CP-SAT model (translate to math)
    3. Solve and extract the schedule
    4. Store results in DynamoDB

    Args:
        schedule_period_start: ISO date string for the first day of the period.

    Returns:
        The solver result dict (status, schedule, metrics).
    """
    print(f"=== Nurse Staffing Optimization ===")
    print(f"Period start: {schedule_period_start}")
    print(f"Staff: {len(STAFF_ROSTER)} nurses")
    print(f"Demand: {DEMAND}")
    print()

    # Step 1: Assemble the problem
    print("Step 1: Assembling problem definition...")
    problem = assemble_problem(STAFF_ROSTER, DEMAND, NUM_DAYS, PTO_BLOCKS)
    print(f"  Total slots to fill: {sum(DEMAND.values()) * NUM_DAYS}")
    print()

    # Step 2: Formulate the model
    print("Step 2: Formulating CP-SAT model...")
    model, variables = formulate_model(problem)
    print(f"  Variables: {len(variables)}")
    print()

    # Step 3: Solve
    print(f"Step 3: Solving (time limit: {SOLVER_TIME_LIMIT_SECONDS}s)...")
    result = solve_and_extract(model, variables, problem)
    print(f"  Status: {result['status']}")
    if result["status"] == "solved":
        m = result["metrics"]
        print(f"  Solve time: {m['solve_time_seconds']}s")
        print(f"  Objective value: {m['objective_value']}")
        print(f"  Coverage: {m['coverage_rate'] * 100:.0f}%")
        print(f"  Fairness score: {m['fairness_score']}")
        print(f"  Weekend shift range: {m['weekend_shift_range']}")
        print()

        # Print the schedule in a readable format
        print("  Schedule:")
        for entry in result["schedule"]:
            shifts_str = ", ".join(
                f"D{a['day']}-{a['shift']}" for a in entry["assignments"]
            )
            print(f"    {entry['nurse_name']:20s} ({entry['total_hours']}h): {shifts_str}")
        print()

    # Step 4: Store in DynamoDB
    print("Step 4: Storing schedule in DynamoDB...")
    items = store_schedule(result, schedule_period_start)
    print(f"  Wrote {items} items.")
    print()

    return result


def demo_calloff(result):
    """
    Demonstrate the real-time call-off handling.
    Simulates RN-001 calling off on day 1, day shift.
    """
    if result["status"] != "solved":
        print("No schedule to demonstrate call-off against.")
        return

    print("=== Real-Time Call-Off Demo ===")
    print("Scenario: Sarah Chen (RN-001) calls off on day 1, day shift.")
    print()

    calloff = {"nurse_id": "RN-001", "day": 1, "shift": "day"}
    coverage = handle_calloff(calloff, result["schedule"], STAFF_ROSTER, PTO_BLOCKS)

    print(f"  Gap: {coverage['gap']}")
    print(f"  Eligible candidates: {coverage['total_eligible']}")
    print()
    print("  Ranked candidates:")
    for i, c in enumerate(coverage["candidates"][:5], 1):
        ot_flag = " [OT]" if c["is_overtime"] else ""
        pref_flag = " [prefers this shift]" if c["prefers_this_shift"] else ""
        print(f"    {i}. {c['nurse_name']:20s} score={c['score']}{ot_flag}{pref_flag}")
    print()


# Entry point
if __name__ == "__main__":
    result = generate_schedule("2026-06-08")
    demo_calloff(result)
```

---

## The Gap Between This and Production

This example works. Run it and it will produce a valid nurse schedule that respects hard constraints and optimizes soft objectives. But there's a meaningful distance between "works in a script" and "runs at a hospital managing real staff." Here's where that gap lives:

**Data integration.** This example hardcodes the staff roster and demand. A production system pulls from HR/payroll (Workday, Kronos, API feeds), the EHR for census and acuity data, and a demand forecasting model. Those integrations are fragile, require transformation logic, and need monitoring for data freshness. Stale availability data produces schedules that violate reality.

**Constraint configuration management.** Hard constraints change when union contracts are renegotiated, state staffing ratios update, or hospital policy evolves. These rules should live in a configuration store (DynamoDB, Parameter Store), not in code. Version them. Audit changes. Test new constraint sets against historical data before deploying.

**Solver hosting.** This runs locally. Production wraps the solver in a SageMaker endpoint (or ECS task) with auto-scaling. Batch scheduling can tolerate minutes of runtime. Real-time call-off handling needs sub-10-second responses. Size your instances accordingly (ml.m5.large is usually sufficient for single-unit problems).

**Multi-unit and multi-facility.** This example optimizes one unit. Real hospitals have 20+ units with shared float pools. The problem scales quadratically with staff size. You may need to decompose into sub-problems (optimize each unit independently, then resolve float pool conflicts) or use a hierarchical approach.

**Manual override tracking.** Nurse managers will override the solver's output. That's expected and healthy. Track every override: which assignment was changed, who changed it, why. These overrides are training data for improving the model (maybe you're missing a constraint the manager knows about implicitly).

**Fairness over time.** This example optimizes fairness within a single period. Real fairness requires tracking weekend and holiday assignments over months. A nurse who worked Christmas last year shouldn't work it again this year. That rolling history needs to feed into the constraint formulation.

**Error handling and retries.** If the solver times out or returns infeasible, the system needs graceful degradation: relax soft constraints progressively, alert the manager, suggest which constraints to relax. Never leave a unit without a schedule.

**Notification delivery.** The call-off handler produces a ranked list. Production sends actual SMS/push notifications via SNS, tracks delivery and response (accepted, declined, no response within 15 minutes), and escalates to the next candidate automatically.

**IAM least-privilege.** The Lambda orchestrating this needs exactly: `sagemaker:InvokeEndpoint` on the solver endpoint, `dynamodb:PutItem/Query` on the schedule table, `events:PutEvents` on the scheduling event bus, `sns:Publish` on the notification topic. Not `*`. Not `AdministratorAccess`.

**Testing.** Validate the solver against known-good historical schedules. If the optimizer produces a schedule that's worse than what the nurse manager built manually, something is wrong with your constraint formulation. Build a regression test suite of scheduling scenarios (understaffed, holiday week, mass PTO) and verify the solver handles each correctly.

**DynamoDB data types.** Any numeric value going into DynamoDB must be wrapped in `Decimal`. This example handles it in `store_schedule`, but be vigilant when adding new numeric fields. The `boto3` DynamoDB resource layer raises a `TypeError` on raw floats.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 14.4](chapter14.04-nurse-staffing-optimization.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
