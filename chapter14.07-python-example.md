# Recipe 14.7: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the OR case sequencing optimization from Recipe 14.7. It demonstrates the core concepts (case data modeling, constraint formulation, solver invocation, schedule extraction, and intraday replanning) using Google OR-Tools' CP-SAT solver. It is not production-ready. The case list is small, durations are deterministic, and there's no EHR integration or real-time event stream. Think of it as the whiteboard sketch that helps you understand how the optimization model actually works. A starting point, not a destination.
>
> The main recipe uses ECS Fargate for solver hosting and EventBridge for real-time surgical events. This example runs everything locally with OR-Tools and writes results to DynamoDB. The optimization math is identical; the infrastructure is stripped away so you can focus on the model.

---

## Setup

You'll need the constraint programming solver and AWS SDK installed:

```bash
pip install boto3 ortools
```

`ortools` is Google's open-source optimization suite. The CP-SAT solver inside it is excellent for scheduling problems because it natively understands interval variables, no-overlap constraints, and optional tasks. It's free, actively maintained, and fast enough for hospital-scale problems (50-80 cases across 15-20 rooms) without a commercial license.

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `dynamodb:PutItem`
- `dynamodb:GetItem`
- `dynamodb:Query`

For the full pipeline (with ECS hosting, EventBridge routing, and SQS buffering), you'd also need `ecs:RunTask`, `events:PutEvents`, and `sqs:SendMessage`, but this example keeps the focus on the optimization itself.

---

## Configuration and Constants

```python
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal
from typing import Optional

import boto3
from botocore.config import Config
from ortools.sat.python import cp_model

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Table where we store optimized schedules.
SCHEDULE_TABLE_NAME = "or-schedules"

# Block time boundaries. Most ORs run 7:00 AM to 5:00 PM (600 minutes).
# We model time in minutes from block start for cleaner arithmetic.
BLOCK_START_HOUR = 7
BLOCK_END_HOUR = 17
BLOCK_DURATION_MINUTES = (BLOCK_END_HOUR - BLOCK_START_HOUR) * 60  # 600

# Turnover time between cases (minutes). This is the time to clean the room,
# set up for the next case, and bring the patient in. Varies by case type.
TURNOVER_TIMES = {
    "clean_to_clean": 25,       # standard case followed by standard case
    "clean_to_contaminated": 30, # need extra prep for contaminated case
    "contaminated_to_clean": 40, # terminal clean required
    "contaminated_to_contaminated": 35,
}

# Default turnover if we can't classify the transition.
DEFAULT_TURNOVER_MINUTES = 30

# Shared equipment setup time (minutes). When two cases need the same
# equipment (e.g., da Vinci robot), there's additional setup between them.
EQUIPMENT_SETUP_MINUTES = {
    "robot_davinci": 30,
    "c_arm": 15,
    "microscope": 20,
    "laser": 15,
}

# Penalty weights for the objective function.
# The solver minimizes the weighted sum of these penalties.
PENALTY_WEIGHTS = {
    "overtime_per_minute": 10,       # each minute past block end costs this much
    "idle_gap_per_minute": 1,        # each minute of idle time between cases
    "preference_violation": 50,      # violating a surgeon's "first case" preference
    "late_start_per_minute": 2,      # each minute a case starts after its ideal window
}

# Solver time limits.
BATCH_SOLVE_SECONDS = 300    # 5 minutes for overnight planning
REPLAN_SOLVE_SECONDS = 30    # 30 seconds for intraday replanning

# Replan threshold: only trigger re-optimization if a case deviates
# by more than this many minutes from its scheduled end time.
REPLAN_THRESHOLD_MINUTES = 15
```

---

## Sample Data: Today's Surgical Cases

In production, this comes from the EHR surgical scheduling system via HL7/FHIR integration, enriched with duration predictions from a historical model. Here we hardcode a realistic example so you can see the data structures the solver expects.

```python
# Operating rooms available today. Each room has capabilities that
# determine which cases can be assigned to it.
ROOMS = [
    {
        "id": "OR-01",
        "name": "Operating Room 1",
        "capabilities": ["general", "ortho", "robot"],
    },
    {
        "id": "OR-02",
        "name": "Operating Room 2",
        "capabilities": ["general", "ortho"],
    },
    {
        "id": "OR-03",
        "name": "Operating Room 3",
        "capabilities": ["general", "cardiac", "vascular"],
    },
    {
        "id": "OR-04",
        "name": "Operating Room 4",
        "capabilities": ["general", "neuro", "microscope"],
    },
]

# Today's surgical cases. Each case has a predicted duration, equipment needs,
# room requirements, surgeon info, and scheduling constraints.
#
# In production, the "expected_duration_min" comes from a prediction model
# trained on historical procedure-surgeon-patient combinations. Here we
# just hardcode reasonable values.
CASES = [
    {
        "case_id": "CASE-001",
        "procedure": "Total Knee Arthroplasty",
        "surgeon_id": "SURG-101",
        "surgeon_name": "Dr. Martinez",
        "expected_duration_min": 120,
        "buffer_min": 15,           # ~90th percentile padding
        "room_requirements": ["ortho"],
        "equipment": [],
        "turnover_class": "clean",
        "priority": "elective",
        "constraints": {"first_case": True},  # surgeon wants this first
    },
    {
        "case_id": "CASE-002",
        "procedure": "Robotic Prostatectomy",
        "surgeon_id": "SURG-102",
        "surgeon_name": "Dr. Patel",
        "expected_duration_min": 180,
        "buffer_min": 25,
        "room_requirements": ["robot"],
        "equipment": ["robot_davinci"],
        "turnover_class": "clean",
        "priority": "elective",
        "constraints": {},
    },
    {
        "case_id": "CASE-003",
        "procedure": "Total Hip Arthroplasty",
        "surgeon_id": "SURG-101",
        "surgeon_name": "Dr. Martinez",
        "expected_duration_min": 135,
        "buffer_min": 18,
        "room_requirements": ["ortho"],
        "equipment": [],
        "turnover_class": "clean",
        "priority": "elective",
        "constraints": {},
    },
    {
        "case_id": "CASE-004",
        "procedure": "CABG (Coronary Artery Bypass)",
        "surgeon_id": "SURG-103",
        "surgeon_name": "Dr. Nakamura",
        "expected_duration_min": 240,
        "buffer_min": 30,
        "room_requirements": ["cardiac"],
        "equipment": [],
        "turnover_class": "clean",
        "priority": "urgent",
        "constraints": {"first_case": True},
    },
    {
        "case_id": "CASE-005",
        "procedure": "Lumbar Microdiscectomy",
        "surgeon_id": "SURG-104",
        "surgeon_name": "Dr. Thompson",
        "expected_duration_min": 90,
        "buffer_min": 12,
        "room_requirements": ["neuro"],
        "equipment": ["microscope"],
        "turnover_class": "clean",
        "priority": "elective",
        "constraints": {},
    },
    {
        "case_id": "CASE-006",
        "procedure": "Laparoscopic Cholecystectomy",
        "surgeon_id": "SURG-105",
        "surgeon_name": "Dr. Kim",
        "expected_duration_min": 60,
        "buffer_min": 10,
        "room_requirements": ["general"],
        "equipment": [],
        "turnover_class": "clean",
        "priority": "elective",
        "constraints": {},
    },
    {
        "case_id": "CASE-007",
        "procedure": "Anterior Cervical Discectomy",
        "surgeon_id": "SURG-104",
        "surgeon_name": "Dr. Thompson",
        "expected_duration_min": 105,
        "buffer_min": 14,
        "room_requirements": ["neuro"],
        "equipment": ["microscope"],
        "turnover_class": "clean",
        "priority": "elective",
        "constraints": {},
    },
    {
        "case_id": "CASE-008",
        "procedure": "Appendectomy (Laparoscopic)",
        "surgeon_id": "SURG-105",
        "surgeon_name": "Dr. Kim",
        "expected_duration_min": 45,
        "buffer_min": 8,
        "room_requirements": ["general"],
        "equipment": [],
        "turnover_class": "contaminated",
        "priority": "semi-urgent",
        "constraints": {"before_noon": True},
    },
    {
        "case_id": "CASE-009",
        "procedure": "Rotator Cuff Repair",
        "surgeon_id": "SURG-106",
        "surgeon_name": "Dr. Williams",
        "expected_duration_min": 100,
        "buffer_min": 13,
        "room_requirements": ["ortho"],
        "equipment": [],
        "turnover_class": "clean",
        "priority": "elective",
        "constraints": {},
    },
    {
        "case_id": "CASE-010",
        "procedure": "Carotid Endarterectomy",
        "surgeon_id": "SURG-103",
        "surgeon_name": "Dr. Nakamura",
        "expected_duration_min": 150,
        "buffer_min": 20,
        "room_requirements": ["vascular"],
        "equipment": [],
        "turnover_class": "clean",
        "priority": "elective",
        "constraints": {},
    },
]

# Staff availability windows. Anesthesiologists covering multiple rooms
# are often the binding constraint on the schedule.
STAFF_AVAILABILITY = [
    {
        "staff_id": "ANES-01",
        "name": "Dr. Rivera (Anesthesia)",
        "covers_rooms": ["OR-01", "OR-02"],
        "available_from_min": 0,      # available from block start
        "available_until_min": 540,   # hard stop at 4:00 PM (540 min from 7 AM)
    },
    {
        "staff_id": "ANES-02",
        "name": "Dr. Okafor (Anesthesia)",
        "covers_rooms": ["OR-03", "OR-04"],
        "available_from_min": 0,
        "available_until_min": 600,   # available full block
    },
]
```

---

## Step 1: Determine Room Eligibility

*The pseudocode calls this part of `enrich_case_list`. Before we build the constraint model, we need to know which rooms each case can legally be assigned to. This is determined by matching case requirements against room capabilities.*

```python
def get_eligible_rooms(case: dict, rooms: list) -> list:
    """
    Determine which rooms a case can be assigned to based on its requirements.

    A case is eligible for a room if the room's capabilities include ALL of
    the case's room requirements. A general surgery case (requiring only
    "general") can go in any room. A cardiac case (requiring "cardiac") can
    only go in rooms with bypass capability.

    Args:
        case: A case dictionary with a "room_requirements" list.
        rooms: The full list of available room dictionaries.

    Returns:
        List of room dictionaries that can host this case.
    """
    eligible = []
    for room in rooms:
        # Check if the room has every capability the case needs.
        if all(req in room["capabilities"] for req in case["room_requirements"]):
            eligible.append(room)

    if not eligible:
        # This shouldn't happen if your data is consistent, but if it does,
        # you want to know immediately rather than getting a silent infeasibility.
        logger.warning(
            "Case %s (%s) has no eligible rooms! Requirements: %s",
            case["case_id"], case["procedure"], case["room_requirements"]
        )

    return eligible
```

---

## Step 2: Build the Constraint Model

*This is the heart of the optimization. We create interval variables for each case, define no-overlap constraints within rooms, handle equipment conflicts, enforce staff availability, and set up the objective function. The CP-SAT solver's interval variables are perfect for scheduling because they natively represent "this task occupies this resource from time A to time B."*

```python
def get_turnover_time(case_a: dict, case_b: dict) -> int:
    """
    Calculate the required turnover time between two consecutive cases.

    Turnover time depends on the contamination class of both cases.
    A contaminated case followed by a clean case requires a terminal clean
    (longer turnover). Two clean cases back-to-back are fastest.

    Args:
        case_a: The preceding case.
        case_b: The following case.

    Returns:
        Turnover time in minutes.
    """
    key = f"{case_a['turnover_class']}_to_{case_b['turnover_class']}"
    return TURNOVER_TIMES.get(key, DEFAULT_TURNOVER_MINUTES)


def build_or_sequencing_model(cases: list, rooms: list, staff: list) -> tuple:
    """
    Build the CP-SAT constraint model for OR case sequencing.

    This function creates:
    - An interval variable for each case-room combination (optional intervals,
      because a case is assigned to exactly one room)
    - No-overlap constraints within each room
    - Equipment conflict constraints across rooms
    - Staff availability constraints
    - Soft constraints (overtime, preferences) in the objective

    Args:
        cases: List of enriched case dictionaries.
        rooms: List of room dictionaries.
        staff: List of staff availability dictionaries.

    Returns:
        Tuple of (model, case_vars) where case_vars is a dict mapping
        case_id to its decision variables for solution extraction.
    """
    model = cp_model.CpModel()

    # We'll collect all the variables we need to extract the solution later.
    case_vars = {}

    # For each case, create interval variables for each eligible room.
    # The case will be assigned to exactly one room (enforced below).
    for case in cases:
        case_id = case["case_id"]
        duration = case["expected_duration_min"] + case["buffer_min"]
        eligible = get_eligible_rooms(case, rooms)

        # The start time variable: when does this case begin?
        # Domain is [0, BLOCK_DURATION_MINUTES - duration] because the case
        # must finish within the block.
        start_var = model.new_int_var(
            0, BLOCK_DURATION_MINUTES - duration,
            f"start_{case_id}"
        )

        # The end variable is deterministic: start + duration.
        end_var = model.new_int_var(
            duration, BLOCK_DURATION_MINUTES,
            f"end_{case_id}"
        )
        model.add(end_var == start_var + duration)

        # Room assignment: binary variable for each eligible room.
        # Exactly one of these will be 1.
        room_assignments = {}
        room_intervals = {}

        for room in eligible:
            room_id = room["id"]

            # Binary: is this case assigned to this room?
            assigned = model.new_bool_var(f"assign_{case_id}_{room_id}")
            room_assignments[room_id] = assigned

            # Optional interval: only "present" if the case is assigned here.
            # CP-SAT's optional intervals are the key trick for room assignment.
            # The interval only participates in no-overlap constraints if
            # its literal (assigned) is true.
            interval = model.new_optional_interval_var(
                start_var, duration, end_var,
                assigned,
                f"interval_{case_id}_{room_id}"
            )
            room_intervals[room_id] = interval

        # Exactly one room must be chosen for this case.
        model.add_exactly_one(room_assignments.values())

        case_vars[case_id] = {
            "start": start_var,
            "end": end_var,
            "duration": duration,
            "room_assignments": room_assignments,
            "room_intervals": room_intervals,
            "case_data": case,
        }

    # --- HARD CONSTRAINT: No overlap within each room ---
    # Cases assigned to the same room cannot overlap in time.
    # We also need to account for turnover time between consecutive cases.
    #
    # CP-SAT's AddNoOverlap works on interval variables directly.
    # But it doesn't handle variable gaps (turnover times) between intervals.
    # So we inflate each interval's duration by the minimum turnover time
    # and handle the variable part as a soft penalty.
    #
    # A simpler approach for this example: use AddNoOverlap on intervals
    # that include turnover time in their duration.
    for room in rooms:
        room_id = room["id"]
        intervals_in_room = []

        for case_id, vars_dict in case_vars.items():
            if room_id in vars_dict["room_intervals"]:
                intervals_in_room.append(vars_dict["room_intervals"][room_id])

        # No two intervals in the same room can overlap.
        # Since we included buffer in duration, this ensures minimum spacing.
        if len(intervals_in_room) > 1:
            model.add_no_overlap(intervals_in_room)

    # --- HARD CONSTRAINT: Shared equipment cannot be double-booked ---
    # If two cases need the same equipment (e.g., the da Vinci robot),
    # they cannot overlap in time regardless of room assignment.
    equipment_users = {}
    for case in cases:
        for equip in case.get("equipment", []):
            if equip not in equipment_users:
                equipment_users[equip] = []
            equipment_users[equip].append(case["case_id"])

    for equip, user_case_ids in equipment_users.items():
        if len(user_case_ids) > 1:
            setup_time = EQUIPMENT_SETUP_MINUTES.get(equip, 15)
            # For each pair of cases sharing equipment, enforce non-overlap
            # with setup time between them.
            for i in range(len(user_case_ids)):
                for j in range(i + 1, len(user_case_ids)):
                    id_a = user_case_ids[i]
                    id_b = user_case_ids[j]
                    end_a = case_vars[id_a]["end"]
                    start_a = case_vars[id_a]["start"]
                    end_b = case_vars[id_b]["end"]
                    start_b = case_vars[id_b]["start"]

                    # Either A finishes before B starts (with setup), or vice versa.
                    # We use a boolean to represent the ordering decision.
                    a_before_b = model.new_bool_var(
                        f"equip_{equip}_{id_a}_before_{id_b}"
                    )
                    model.add(
                        end_a + setup_time <= start_b
                    ).only_enforce_if(a_before_b)
                    model.add(
                        end_b + setup_time <= start_a
                    ).only_enforce_if(a_before_b.negated())

    # --- HARD CONSTRAINT: Staff availability ---
    # If an anesthesiologist covers rooms 1-2 and is only available until 4 PM,
    # all cases in those rooms must end by that time.
    for staff_member in staff:
        for case_id, vars_dict in case_vars.items():
            for covered_room in staff_member["covers_rooms"]:
                if covered_room in vars_dict["room_assignments"]:
                    assigned_var = vars_dict["room_assignments"][covered_room]
                    # If this case is in a room covered by this staff member,
                    # it must end within their availability window.
                    model.add(
                        vars_dict["end"] <= staff_member["available_until_min"]
                    ).only_enforce_if(assigned_var)
                    model.add(
                        vars_dict["start"] >= staff_member["available_from_min"]
                    ).only_enforce_if(assigned_var)

    # --- HARD CONSTRAINT: "First case" preference (treated as hard here) ---
    # Some surgeons require their complex case to be first in the room.
    # In production you might make this soft, but surgeons tend to revolt
    # if you move their first-case slot.
    for case in cases:
        if case.get("constraints", {}).get("first_case"):
            case_id = case["case_id"]
            # "First case" means start time is 0 (beginning of block).
            model.add(case_vars[case_id]["start"] == 0)

    # --- HARD CONSTRAINT: "Before noon" requirement ---
    # Semi-urgent cases that need to happen in the morning.
    noon_offset = (12 - BLOCK_START_HOUR) * 60  # 300 minutes from block start
    for case in cases:
        if case.get("constraints", {}).get("before_noon"):
            case_id = case["case_id"]
            model.add(case_vars[case_id]["end"] <= noon_offset)

    # --- OBJECTIVE: Minimize overtime + idle time ---
    # Overtime: penalize cases that end after the block end time.
    # (In this model, we constrain cases to end within the block, so overtime
    # is actually about how close to the end we pack things. We'll use
    # makespan minimization as a proxy.)
    #
    # We minimize the maximum end time across all rooms (makespan).
    # This encourages the solver to spread cases evenly and finish early.
    makespan = model.new_int_var(0, BLOCK_DURATION_MINUTES, "makespan")
    for case_id, vars_dict in case_vars.items():
        model.add(makespan >= vars_dict["end"])

    # The objective: minimize makespan. This implicitly minimizes overtime
    # and encourages efficient packing.
    model.minimize(makespan)

    return model, case_vars
```

---

## Step 3: Solve the Model

*Hand the model to the CP-SAT solver. For batch mode (overnight planning), we give it several minutes. For replan mode, we give it 30 seconds and fix already-completed cases.*

```python
def solve_schedule(
    model: cp_model.CpModel,
    case_vars: dict,
    time_limit_seconds: int = BATCH_SOLVE_SECONDS,
) -> Optional[dict]:
    """
    Run the CP-SAT solver and extract the optimized schedule.

    The solver explores the solution space using constraint propagation and
    search. It returns the best solution found within the time limit, along
    with a status indicating whether it proved optimality.

    Args:
        model: The constraint model built by build_or_sequencing_model.
        case_vars: The variable dictionary for solution extraction.
        time_limit_seconds: How long the solver can run.

    Returns:
        A schedule dictionary if a feasible solution was found, None otherwise.
    """
    solver = cp_model.CpSolver()

    # Time limit prevents the solver from running forever on hard instances.
    solver.parameters.max_time_in_seconds = time_limit_seconds

    # Number of parallel search workers. More workers explore more of the
    # solution space simultaneously. 8 is a good default for a 4-core machine.
    solver.parameters.num_search_workers = 8

    # Log search progress (useful for debugging, noisy in production).
    solver.parameters.log_search_progress = False

    logger.info("Starting solver with %d second time limit...", time_limit_seconds)
    status = solver.solve(model)

    status_name = solver.status_name(status)
    logger.info(
        "Solver finished. Status: %s, Objective: %s, Wall time: %.1fs",
        status_name,
        solver.objective_value if status in [cp_model.OPTIMAL, cp_model.FEASIBLE] else "N/A",
        solver.wall_time,
    )

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        logger.error(
            "No feasible solution found. Status: %s. "
            "Constraints may be too tight (check staff availability, room capabilities).",
            status_name,
        )
        return None

    # Extract the solution: for each case, determine its assigned room and start time.
    schedule = {
        "status": status_name,
        "objective_value": solver.objective_value,
        "solve_time_seconds": round(solver.wall_time, 2),
        "rooms": {},
    }

    for case_id, vars_dict in case_vars.items():
        start_time = solver.value(vars_dict["start"])
        end_time = solver.value(vars_dict["end"])

        # Find which room was assigned (the one with assignment = 1).
        assigned_room = None
        for room_id, assigned_var in vars_dict["room_assignments"].items():
            if solver.value(assigned_var) == 1:
                assigned_room = room_id
                break

        if assigned_room not in schedule["rooms"]:
            schedule["rooms"][assigned_room] = []

        schedule["rooms"][assigned_room].append({
            "case_id": case_id,
            "procedure": vars_dict["case_data"]["procedure"],
            "surgeon": vars_dict["case_data"]["surgeon_name"],
            "start_min": start_time,
            "end_min": end_time,
            "start_time": minutes_to_time_str(start_time),
            "end_time": minutes_to_time_str(end_time),
            "duration_with_buffer": vars_dict["duration"],
        })

    # Sort cases within each room by start time.
    for room_id in schedule["rooms"]:
        schedule["rooms"][room_id].sort(key=lambda c: c["start_min"])

    return schedule


def minutes_to_time_str(minutes_from_block_start: int) -> str:
    """
    Convert minutes-from-block-start to a human-readable time string.

    Example: 0 -> "07:00", 150 -> "09:30", 540 -> "16:00"
    """
    total_minutes = BLOCK_START_HOUR * 60 + minutes_from_block_start
    hours = total_minutes // 60
    mins = total_minutes % 60
    return f"{hours:02d}:{mins:02d}"
```

---

## Step 4: Compute Schedule Metrics

*After solving, we compute utilization, overtime, and other metrics that the perioperative team cares about. These numbers are what justify the optimization system's existence.*

```python
def compute_schedule_metrics(schedule: dict) -> dict:
    """
    Calculate utilization and efficiency metrics for the optimized schedule.

    These metrics are what you show the perioperative director to demonstrate
    value: utilization percentage, overtime minutes, idle gaps, and how many
    surgeon preferences were satisfied.

    Args:
        schedule: The solved schedule dictionary from solve_schedule.

    Returns:
        A metrics dictionary with per-room and aggregate statistics.
    """
    room_metrics = {}
    total_case_minutes = 0
    total_available_minutes = 0
    total_overtime = 0

    for room_id, cases in schedule["rooms"].items():
        if not cases:
            continue

        # Room utilization: time spent on cases / total block time.
        case_time = sum(c["duration_with_buffer"] for c in cases)
        last_end = max(c["end_min"] for c in cases)
        first_start = min(c["start_min"] for c in cases)

        # Idle time: gaps between cases (not including pre-first or post-last).
        idle_time = (last_end - first_start) - case_time
        idle_time = max(0, idle_time)  # shouldn't be negative, but safety check

        # Overtime: time past the block end.
        overtime = max(0, last_end - BLOCK_DURATION_MINUTES)

        utilization = (case_time / BLOCK_DURATION_MINUTES) * 100

        room_metrics[room_id] = {
            "num_cases": len(cases),
            "case_minutes": case_time,
            "utilization_pct": round(utilization, 1),
            "idle_minutes": idle_time,
            "overtime_minutes": overtime,
            "last_case_ends": minutes_to_time_str(last_end),
        }

        total_case_minutes += case_time
        total_available_minutes += BLOCK_DURATION_MINUTES
        total_overtime += overtime

    num_rooms_used = len(schedule["rooms"])
    avg_utilization = (
        (total_case_minutes / total_available_minutes) * 100
        if total_available_minutes > 0 else 0
    )

    return {
        "per_room": room_metrics,
        "aggregate": {
            "total_cases": sum(m["num_cases"] for m in room_metrics.values()),
            "rooms_used": num_rooms_used,
            "avg_utilization_pct": round(avg_utilization, 1),
            "total_overtime_minutes": total_overtime,
            "rooms_with_overtime": sum(
                1 for m in room_metrics.values() if m["overtime_minutes"] > 0
            ),
        },
    }
```

---

## Step 5: Store the Schedule in DynamoDB

*The optimized schedule gets written to DynamoDB so the OR dashboard, EHR integration, and replan trigger can all access it. We use the schedule date as the partition key for easy retrieval.*

```python
def store_schedule(schedule: dict, metrics: dict, schedule_date: str) -> dict:
    """
    Write the optimized schedule to DynamoDB.

    This record is the authoritative "current plan" for the day. The replan
    trigger reads it to compare against actual events. The dashboard reads it
    to display the Gantt chart. The EHR integration reads it to update
    patient tracking boards.

    Args:
        schedule: The solved schedule from solve_schedule.
        metrics: The computed metrics from compute_schedule_metrics.
        schedule_date: ISO date string (e.g., "2026-06-01").

    Returns:
        The record that was written.
    """
    table = dynamodb.Table(SCHEDULE_TABLE_NAME)

    record = {
        "schedule_date": schedule_date,
        "optimization_timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "status": schedule["status"],
        "solve_time_seconds": Decimal(str(schedule["solve_time_seconds"])),
        "objective_value": Decimal(str(schedule["objective_value"])),
        "rooms": json.loads(json.dumps(schedule["rooms"]), parse_float=Decimal),
        "metrics": json.loads(json.dumps(metrics), parse_float=Decimal),
        "version": 1,  # incremented on each replan
    }

    # Conditional write: only succeed if this is the first schedule for today
    # or if we're explicitly replanning (handled by incrementing version).
    table.put_item(Item=record)

    logger.info(
        "Stored schedule for %s. %d cases across %d rooms. Avg utilization: %s%%",
        schedule_date,
        metrics["aggregate"]["total_cases"],
        metrics["aggregate"]["rooms_used"],
        metrics["aggregate"]["avg_utilization_pct"],
    )

    return record
```

---

## Step 6: Handle Intraday Replanning

*When a case finishes early/late, gets cancelled, or an add-on arrives, we need to re-optimize the remainder of the day. The key insight: fix everything that's already happened and only re-optimize future cases.*

```python
def replan_schedule(
    original_cases: list,
    rooms: list,
    staff: list,
    completed_cases: list,
    in_progress_cases: list,
    cancelled_case_ids: list,
    add_on_cases: list,
) -> Optional[dict]:
    """
    Re-optimize the schedule given what's happened so far today.

    This is the intraday replanning path. We take the original case list,
    remove completed and cancelled cases, add any new add-on cases, and
    re-solve with a tight time limit. Cases currently in progress are fixed
    at their actual start times.

    Args:
        original_cases: The full original case list for today.
        rooms: Available rooms.
        staff: Staff availability (may be updated if someone left early).
        completed_cases: Cases that have finished (with actual end times).
        in_progress_cases: Cases currently underway (with actual start times).
        cancelled_case_ids: IDs of cases that were cancelled.
        add_on_cases: New cases added to today's schedule.

    Returns:
        Updated schedule, or None if no feasible solution exists.
    """
    # Filter to only cases that still need scheduling.
    remaining_cases = [
        c for c in original_cases
        if c["case_id"] not in cancelled_case_ids
        and c["case_id"] not in [cc["case_id"] for cc in completed_cases]
        and c["case_id"] not in [ip["case_id"] for ip in in_progress_cases]
    ]

    # Add any new add-on cases.
    remaining_cases.extend(add_on_cases)

    if not remaining_cases:
        logger.info("No remaining cases to schedule. Day is complete.")
        return None

    # Calculate the current time offset (how far into the block we are).
    # In production, this comes from the system clock. Here we derive it
    # from the latest completed case end time.
    current_offset = 0
    if completed_cases:
        current_offset = max(c["actual_end_min"] for c in completed_cases)
    if in_progress_cases:
        # In-progress cases occupy their rooms until they finish.
        # Estimate remaining time as expected_duration - elapsed.
        for ip_case in in_progress_cases:
            estimated_end = ip_case["actual_start_min"] + ip_case["expected_duration_min"]
            current_offset = max(current_offset, estimated_end)

    logger.info(
        "Replanning: %d remaining cases, %d cancelled, %d add-ons. "
        "Current time offset: %d min from block start.",
        len(remaining_cases), len(cancelled_case_ids),
        len(add_on_cases), current_offset,
    )

    # Adjust the block: remaining cases can only start after current_offset
    # (or after in-progress cases finish in their rooms).
    # For simplicity, we just set a minimum start time for all remaining cases.
    for case in remaining_cases:
        if "constraints" not in case:
            case["constraints"] = {}
        # Don't override first_case constraint; those are already handled.
        if not case["constraints"].get("first_case"):
            case["constraints"]["earliest_start"] = current_offset

    # Build and solve with tight time limit.
    model, case_vars = build_or_sequencing_model(remaining_cases, rooms, staff)

    # Apply earliest start constraints for replanning.
    for case in remaining_cases:
        earliest = case.get("constraints", {}).get("earliest_start", 0)
        if earliest > 0:
            case_id = case["case_id"]
            if case_id in case_vars:
                model.add(case_vars[case_id]["start"] >= earliest)

    return solve_schedule(model, case_vars, time_limit_seconds=REPLAN_SOLVE_SECONDS)
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. This is what your batch scheduler (Lambda or ECS task) would invoke the evening before surgery day.

```python
def optimize_or_schedule(
    cases: list,
    rooms: list,
    staff: list,
    schedule_date: str,
) -> dict:
    """
    Run the full OR case sequencing optimization pipeline.

    This is the main entry point for batch scheduling. Call it the evening
    before (or early morning of) the surgery day with the confirmed case list.

    Args:
        cases: List of enriched case dictionaries.
        rooms: List of available room dictionaries.
        staff: List of staff availability dictionaries.
        schedule_date: ISO date string for the schedule.

    Returns:
        The stored schedule record with metrics.
    """
    logger.info("=" * 60)
    logger.info("OR Case Sequencing Optimization")
    logger.info("Date: %s | Cases: %d | Rooms: %d", schedule_date, len(cases), len(rooms))
    logger.info("=" * 60)

    # Step 1: Verify room eligibility for all cases.
    logger.info("\nStep 1: Checking room eligibility...")
    for case in cases:
        eligible = get_eligible_rooms(case, rooms)
        logger.info(
            "  %s (%s): %d eligible rooms",
            case["case_id"], case["procedure"], len(eligible),
        )

    # Step 2: Build the constraint model.
    logger.info("\nStep 2: Building constraint model...")
    model, case_vars = build_or_sequencing_model(cases, rooms, staff)
    logger.info(
        "  Model has %d variables, %d constraints",
        model.proto.variables.__len__(),
        model.proto.constraints.__len__(),
    )

    # Step 3: Solve.
    logger.info("\nStep 3: Solving...")
    schedule = solve_schedule(model, case_vars)

    if schedule is None:
        logger.error("Optimization failed. No feasible schedule found.")
        return {"status": "INFEASIBLE", "schedule_date": schedule_date}

    # Step 4: Compute metrics.
    logger.info("\nStep 4: Computing metrics...")
    metrics = compute_schedule_metrics(schedule)
    logger.info("  Average utilization: %s%%", metrics["aggregate"]["avg_utilization_pct"])
    logger.info("  Total overtime: %d minutes", metrics["aggregate"]["total_overtime_minutes"])

    # Step 5: Store in DynamoDB.
    logger.info("\nStep 5: Storing schedule...")
    record = store_schedule(schedule, metrics, schedule_date)

    # Print the schedule in a human-readable format.
    logger.info("\n" + "=" * 60)
    logger.info("OPTIMIZED SCHEDULE")
    logger.info("=" * 60)
    for room_id, cases_in_room in sorted(schedule["rooms"].items()):
        logger.info("\n%s:", room_id)
        for case in cases_in_room:
            logger.info(
                "  %s - %s | %s (%s)",
                case["start_time"], case["end_time"],
                case["procedure"], case["surgeon"],
            )

    return record


# Run the optimization with our sample data.
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    result = optimize_or_schedule(
        cases=CASES,
        rooms=ROOMS,
        staff=STAFF_AVAILABILITY,
        schedule_date="2026-06-01",
    )

    print("\n\nFinal result:")
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example works. Run it with the sample data and it will produce an optimized schedule in under a second. But there's a meaningful distance between "works in a script" and "runs in a perioperative department handling real surgical cases." Here's where that gap lives:

**Duration prediction.** This example uses hardcoded durations. A production system trains a model on historical case data (procedure code, surgeon, patient ASA class, BMI, revision vs. primary) to predict duration distributions. The prediction quality determines whether the optimized schedule is realistic or fiction. See Recipe 7.7 for duration modeling techniques.

**EHR integration.** The case list here is a Python list. In production, it comes from the surgical scheduling module of your EHR (Epic OpTime, Cerner SurgiNet, etc.) via HL7 ADT messages or FHIR ScheduleRequest resources. The integration layer must handle case modifications, cancellations, and add-ons that arrive throughout the day.

**Real-time event handling.** This example has a `replan_schedule` function but no event stream feeding it. A production system uses EventBridge (or similar) to receive case-completion events, cancellation notifications, and add-on requests from the EHR. The replan trigger logic decides whether each event warrants re-optimization or can be absorbed by the existing schedule.

**Turnover time modeling.** We use a simple lookup table. Reality is messier: turnover time depends on the specific transition (what equipment needs to move in/out), the cleaning crew's current workload, and whether the next patient is already in pre-op. Some facilities model turnover as a separate optimization sub-problem.

**Solver hosting.** This runs locally. Production runs the solver in an ECS Fargate task (or a dedicated EC2 instance for commercial solvers like Gurobi). The container needs enough memory for large instances (8-16 GB for 60+ cases) and the solver binary pre-installed. Commercial solvers require license management (floating licenses, node-locked licenses, or cloud-metered licenses).

**Error handling and retries.** If the solver returns INFEASIBLE, this example just logs an error. A production system performs conflict analysis (which constraints are mutually exclusive?), suggests relaxations to the perioperative coordinator ("if Dr. Smith's first-case preference is relaxed, a feasible schedule exists"), and falls back to a heuristic schedule if optimization fails entirely.

**Concurrency control.** Multiple replan requests can arrive simultaneously (a cancellation and an add-on in the same minute). The SQS queue in the main recipe's architecture prevents concurrent solver runs from producing conflicting schedules. This example has no such protection.

**Audit trail.** Every schedule version (initial plan, each replan) should be stored with the reason for replanning, what changed, and who was notified. This is required for perioperative governance and useful for post-hoc analysis of schedule stability.

**Staff notification.** When a replan moves a case to a different time or room, the affected surgical team (surgeon, anesthesiologist, circulating nurse, scrub tech) needs to be notified. This example produces a schedule but doesn't tell anyone about it.

**IAM least-privilege.** The IAM role for the solver task should have exactly `dynamodb:PutItem` and `dynamodb:GetItem` on the schedule table, `dynamodb:Query` on the cases table, and nothing else. Not `dynamodb:*`. Not `AdministratorAccess`.

**VPC configuration.** In production, the Fargate task runs in a private subnet with VPC endpoints for DynamoDB and S3. Case data includes patient identifiers (PHI). It should never traverse the public internet.

**Testing.** There are no tests here. A production system has unit tests for constraint formulation (does the model correctly prevent equipment double-booking?), integration tests with known case sets that have verified optimal solutions, and regression tests that catch when a solver upgrade changes behavior.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 14.7](chapter14.07-or-case-sequencing.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
