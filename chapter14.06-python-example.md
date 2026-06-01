# Recipe 14.6: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the patient flow and bed assignment optimization from Recipe 14.6. It demonstrates the core concepts (state modeling, constraint formulation, multi-objective optimization, and recommendation generation) using Google OR-Tools' CP-SAT solver. It is not production-ready. The hospital is tiny, the state is static, and there's no real-time event ingestion or WebSocket push. Think of it as the whiteboard sketch that helps you understand the shape of the real system. A starting point, not a destination.
>
> The main recipe uses Kinesis for event ingestion, ElastiCache for working state, and Step Functions for pipeline orchestration. This example runs everything locally with OR-Tools and writes results to DynamoDB. The optimization math is identical; the infrastructure is stripped away so you can focus on the model.

---

## Setup

You'll need the constraint programming solver and AWS SDK installed:

```bash
pip install boto3 ortools
```

`ortools` is Google's open-source optimization suite. The CP-SAT solver handles the binary decision variables, hard safety constraints, and weighted soft objectives of bed assignment naturally. It's free, actively maintained, and solves hospital-scale problems (400+ beds, 30-40 pending patients) in 1-3 seconds without a commercial license.

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `dynamodb:PutItem`
- `dynamodb:GetItem`
- `dynamodb:Query`
- `dynamodb:UpdateItem`

For the full pipeline (with Kinesis ingestion, ElastiCache state, and WebSocket notifications), you'd also need `kinesis:GetRecords`, `elasticache:Connect`, `execute-api:ManageConnections`, and `states:StartExecution`, but this example keeps the focus on the optimization itself.

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

# Table where we store bed assignment recommendations.
RECOMMENDATIONS_TABLE_NAME = "bed-assignment-recommendations"

# Table where we store the live bed state (in production, this is updated
# by the Kinesis event processor in real-time).
BED_STATE_TABLE_NAME = "bed-state"

# Objective function weights. These encode hospital policy decisions about
# what matters most. Higher weight = solver prioritizes that objective more.
# These are the knobs that hospital leadership tunes over time.
OBJECTIVE_WEIGHTS = {
    "assignment_priority": 100,   # base reward for assigning any patient (vs. leaving them waiting)
    "clinical_fit": 50,           # bonus for clinically appropriate placement
    "workload_balance": 30,       # penalty for overloading busy units
    "continuity_of_care": 20,     # bonus for placing patient on their previous unit
    "wait_time_urgency": 10,      # per-minute bonus for longer-waiting patients
}

# Solver time limit in seconds. For a 400-bed hospital with 30 pending
# patients, CP-SAT typically finds optimal in under 2 seconds. The 10-second
# limit is generous headroom for larger or more constrained problems.
SOLVER_TIME_LIMIT_SECONDS = 10

# Acuity levels and which unit types can accept them.
# This is a hard constraint: violating it is clinically unsafe.
ACUITY_UNIT_COMPATIBILITY = {
    "ICU":       ["ICU"],
    "STEP_DOWN": ["STEP_DOWN", "ICU"],  # step-down patients can go to ICU (overqualified but safe)
    "TELEMETRY": ["TELEMETRY", "STEP_DOWN"],
    "MED_SURG":  ["MED_SURG", "TELEMETRY"],  # med-surg can go to tele (monitored, safe)
}

# Room types that satisfy isolation requirements.
ISOLATION_ROOM_REQUIREMENTS = {
    "AIRBORNE":  ["NEGATIVE_PRESSURE"],          # TB, COVID, measles
    "CONTACT":   ["PRIVATE", "NEGATIVE_PRESSURE"],  # MRSA, C. diff
    "DROPLET":   ["PRIVATE", "NEGATIVE_PRESSURE"],
    "NONE":      ["PRIVATE", "SEMI_PRIVATE", "NEGATIVE_PRESSURE"],  # any room works
}
```

---

## Sample Data: Hospital Bed Inventory and Pending Patients

In production, this comes from the ADT event stream (via Kinesis) and the live DynamoDB state table. Here we hardcode a small hospital so you can see the data structures the solver expects.

```python
# Bed inventory: each bed has an ID, unit, room type, capabilities,
# current status, and (if occupied) the current patient's gender.
# This represents the "digital twin" of the hospital's physical bed state.

BED_INVENTORY = [
    # 4-West Step-Down Unit
    {"bed_id": "4W-301A", "unit": "4-WEST", "unit_type": "STEP_DOWN", "room_type": "SEMI_PRIVATE",
     "status": "AVAILABLE", "roommate_gender": "M", "capabilities": ["telemetry", "cardiac_drip"]},
    {"bed_id": "4W-301B", "unit": "4-WEST", "unit_type": "STEP_DOWN", "room_type": "SEMI_PRIVATE",
     "status": "OCCUPIED", "roommate_gender": None, "capabilities": ["telemetry", "cardiac_drip"]},
    {"bed_id": "4W-312A", "unit": "4-WEST", "unit_type": "STEP_DOWN", "room_type": "PRIVATE",
     "status": "AVAILABLE", "roommate_gender": None, "capabilities": ["telemetry", "cardiac_drip"]},
    {"bed_id": "4W-315A", "unit": "4-WEST", "unit_type": "STEP_DOWN", "room_type": "NEGATIVE_PRESSURE",
     "status": "AVAILABLE", "roommate_gender": None, "capabilities": ["telemetry", "cardiac_drip", "isolation"]},

    # 3-East Med-Surg Unit
    {"bed_id": "3E-201A", "unit": "3-EAST", "unit_type": "MED_SURG", "room_type": "SEMI_PRIVATE",
     "status": "AVAILABLE", "roommate_gender": "F", "capabilities": []},
    {"bed_id": "3E-201B", "unit": "3-EAST", "unit_type": "MED_SURG", "room_type": "SEMI_PRIVATE",
     "status": "AVAILABLE", "roommate_gender": None, "capabilities": []},
    {"bed_id": "3E-205A", "unit": "3-EAST", "unit_type": "MED_SURG", "room_type": "PRIVATE",
     "status": "AVAILABLE", "roommate_gender": None, "capabilities": []},
    {"bed_id": "3E-210A", "unit": "3-EAST", "unit_type": "MED_SURG", "room_type": "SEMI_PRIVATE",
     "status": "CLEANING", "roommate_gender": None, "capabilities": [],
     "estimated_available_minutes": 25},

    # 5-North Telemetry Unit
    {"bed_id": "5N-401A", "unit": "5-NORTH", "unit_type": "TELEMETRY", "room_type": "PRIVATE",
     "status": "AVAILABLE", "roommate_gender": None, "capabilities": ["telemetry"]},
    {"bed_id": "5N-402A", "unit": "5-NORTH", "unit_type": "TELEMETRY", "room_type": "SEMI_PRIVATE",
     "status": "AVAILABLE", "roommate_gender": "M", "capabilities": ["telemetry"]},

    # ICU
    {"bed_id": "ICU-101", "unit": "ICU", "unit_type": "ICU", "room_type": "PRIVATE",
     "status": "AVAILABLE", "roommate_gender": None, "capabilities": ["ventilator", "cardiac_drip", "telemetry"]},
]

# Unit staffing state: current census vs. staffed capacity.
# Staffed capacity is the number of patients the current nursing staff
# can safely manage (based on nurse-to-patient ratios and certifications).
UNIT_STAFFING = {
    "4-WEST":  {"current_census": 18, "staffed_capacity": 24, "has_cardiac_drip_nurse": True},
    "3-EAST":  {"current_census": 22, "staffed_capacity": 28, "has_cardiac_drip_nurse": False},
    "5-NORTH": {"current_census": 14, "staffed_capacity": 18, "has_cardiac_drip_nurse": True},
    "ICU":     {"current_census": 8,  "staffed_capacity": 10, "has_cardiac_drip_nurse": True},
}

# Patients waiting for beds. Each has requirements, priority, and context.
# In production, this queue is populated by ADT "pending admit" events.
PENDING_PATIENTS = [
    {
        "patient_id": "PAT-88291",
        "gender": "M",
        "acuity": "STEP_DOWN",
        "isolation": "NONE",
        "requires_cardiac_drip": True,
        "previous_unit": "4-WEST",  # was here last admission
        "waiting_since_minutes": 135,
        "priority_score": 8.5,  # composite of acuity + wait time + clinical urgency
    },
    {
        "patient_id": "PAT-90112",
        "gender": "F",
        "acuity": "MED_SURG",
        "isolation": "AIRBORNE",  # needs negative-pressure room
        "requires_cardiac_drip": False,
        "previous_unit": None,
        "waiting_since_minutes": 90,
        "priority_score": 9.0,  # isolation bumps priority (infection control urgency)
    },
    {
        "patient_id": "PAT-91003",
        "gender": "F",
        "acuity": "MED_SURG",
        "isolation": "NONE",
        "requires_cardiac_drip": False,
        "previous_unit": "3-EAST",
        "waiting_since_minutes": 45,
        "priority_score": 5.0,
    },
    {
        "patient_id": "PAT-91455",
        "gender": "M",
        "acuity": "TELEMETRY",
        "isolation": "CONTACT",  # needs private room
        "requires_cardiac_drip": False,
        "previous_unit": None,
        "waiting_since_minutes": 60,
        "priority_score": 7.0,
    },
    {
        "patient_id": "PAT-92001",
        "gender": "M",
        "acuity": "STEP_DOWN",
        "isolation": "NONE",
        "requires_cardiac_drip": False,
        "previous_unit": None,
        "waiting_since_minutes": 20,
        "priority_score": 6.0,
    },
]
```

---

## Step 1: Build the Available Bed List

*The pseudocode calls this part of `get_current_hospital_state()`. We filter the bed inventory to only beds that are actually assignable right now (or within a short window for beds in cleaning).*

```python
def get_available_beds(bed_inventory: list, include_cleaning_within_minutes: int = 30) -> list:
    """
    Filter bed inventory to beds that can accept a patient now or very soon.

    We include beds currently in cleaning if they'll be ready within the
    specified window. This prevents the optimizer from ignoring a bed that
    will be available in 10 minutes while a patient waits 15 minutes for
    the next optimization run.

    Args:
        bed_inventory: Full list of bed records from the state table.
        include_cleaning_within_minutes: Include cleaning beds if they'll
            be ready within this many minutes.

    Returns:
        List of bed records that are candidates for assignment.
    """
    available = []

    for bed in bed_inventory:
        if bed["status"] == "AVAILABLE":
            available.append(bed)
        elif bed["status"] == "CLEANING":
            # Include beds that will be ready soon. The optimizer can assign
            # a patient to a bed that's 20 minutes from ready if that patient
            # would otherwise wait 45 minutes for the next run.
            est_minutes = bed.get("estimated_available_minutes", 999)
            if est_minutes <= include_cleaning_within_minutes:
                available.append(bed)

    return available
```

---

## Step 2: Check Feasibility (Can This Patient Go in This Bed?)

*The pseudocode encodes these as hard constraints in the model. Here we pre-compute a feasibility matrix: for each (patient, bed) pair, is the assignment even allowed? This keeps the constraint logic readable and testable independently of the solver.*

```python
def is_feasible_assignment(patient: dict, bed: dict, unit_staffing: dict) -> bool:
    """
    Check whether assigning this patient to this bed violates any hard constraint.

    Hard constraints are non-negotiable safety rules. If this function returns
    False, the solver will never consider this assignment. Period.

    This is separate from the objective function (which handles preferences
    and soft constraints). Feasibility is binary: safe or not safe.
    """
    unit = bed["unit"]
    unit_type = bed["unit_type"]
    staffing = unit_staffing.get(unit, {})

    # 1. Acuity-to-unit matching.
    # A step-down patient cannot go to a med-surg floor. An ICU patient
    # cannot go anywhere but ICU. This is the most fundamental safety check.
    compatible_units = ACUITY_UNIT_COMPATIBILITY.get(patient["acuity"], [])
    if unit_type not in compatible_units:
        return False

    # 2. Isolation requirements.
    # Airborne isolation (TB, COVID) requires negative-pressure rooms.
    # Contact isolation requires at minimum a private room.
    required_room_types = ISOLATION_ROOM_REQUIREMENTS.get(patient["isolation"], [])
    if bed["room_type"] not in required_room_types:
        return False

    # 3. Gender matching for semi-private rooms.
    # If the room already has an occupant, the new patient must be same gender.
    if bed["room_type"] == "SEMI_PRIVATE" and bed["roommate_gender"] is not None:
        if patient["gender"] != bed["roommate_gender"]:
            return False

    # 4. Staffing capacity.
    # Even if a physical bed exists, the unit might not have enough nurses
    # to safely staff another patient. This is a real capacity limit.
    if staffing.get("current_census", 0) >= staffing.get("staffed_capacity", 0):
        return False

    # 5. Special equipment/certification requirements.
    # A patient on a cardiac drip needs a nurse certified to manage it.
    if patient.get("requires_cardiac_drip") and not staffing.get("has_cardiac_drip_nurse"):
        return False

    return True
```

---

## Step 3: Formulate the Optimization Model

*The pseudocode calls this `build_assignment_model(state)`. This is the heart of the system: translating the bed assignment problem into a mathematical model that the CP-SAT solver can optimize.*

```python
def build_optimization_model(
    patients: list,
    beds: list,
    unit_staffing: dict,
) -> tuple:
    """
    Formulate the bed assignment problem as a constraint programming model.

    The model has:
    - Binary decision variables: x[p][b] = 1 if patient p is assigned to bed b
    - Hard constraints: encoded via the feasibility matrix (infeasible pairs excluded)
    - Soft objectives: weighted sum of clinical fit, workload balance, continuity, etc.

    Returns:
        Tuple of (model, variables_dict, patients, beds) for the solver step.
    """
    model = cp_model.CpModel()

    # Create binary decision variables.
    # x[(p_idx, b_idx)] = 1 means patient p_idx is assigned to bed b_idx.
    x = {}
    for p_idx, patient in enumerate(patients):
        for b_idx, bed in enumerate(beds):
            # Only create a variable if the assignment is feasible.
            # This pre-filters the search space: the solver never even
            # considers infeasible assignments.
            if is_feasible_assignment(patient, bed, unit_staffing):
                x[(p_idx, b_idx)] = model.NewBoolVar(f"assign_p{p_idx}_b{b_idx}")

    # CONSTRAINT: Each patient assigned to at most one bed.
    # (We allow zero assignments: if no feasible bed exists, the patient
    # stays in the queue rather than getting an unsafe placement.)
    for p_idx in range(len(patients)):
        patient_vars = [x[(p_idx, b_idx)] for b_idx in range(len(beds))
                        if (p_idx, b_idx) in x]
        if patient_vars:
            model.Add(sum(patient_vars) <= 1)

    # CONSTRAINT: Each bed assigned to at most one patient.
    for b_idx in range(len(beds)):
        bed_vars = [x[(p_idx, b_idx)] for p_idx in range(len(patients))
                    if (p_idx, b_idx) in x]
        if bed_vars:
            model.Add(sum(bed_vars) <= 1)

    # OBJECTIVE FUNCTION: weighted multi-objective.
    # We maximize a composite score that rewards good assignments and
    # penalizes suboptimal ones.
    objective_terms = []

    for p_idx, patient in enumerate(patients):
        for b_idx, bed in enumerate(beds):
            if (p_idx, b_idx) not in x:
                continue

            var = x[(p_idx, b_idx)]
            score = 0

            # Base reward: assigning any patient is better than leaving them waiting.
            # Weighted by priority score so sicker/longer-waiting patients get placed first.
            score += int(OBJECTIVE_WEIGHTS["assignment_priority"] * patient["priority_score"])

            # Wait time urgency: longer-waiting patients get a per-minute bonus.
            score += int(OBJECTIVE_WEIGHTS["wait_time_urgency"] * patient["waiting_since_minutes"])

            # Clinical fit: bonus for placing patient on the ideal unit type
            # (vs. an acceptable-but-not-ideal unit).
            ideal_units = ACUITY_UNIT_COMPATIBILITY.get(patient["acuity"], [])
            if ideal_units and bed["unit_type"] == ideal_units[0]:
                score += OBJECTIVE_WEIGHTS["clinical_fit"]

            # Workload balance: penalize assignments to already-busy units.
            # The penalty scales with how full the unit is.
            staffing = unit_staffing.get(bed["unit"], {})
            capacity = staffing.get("staffed_capacity", 1)
            census = staffing.get("current_census", 0)
            load_fraction = census / capacity  # 0.0 to 1.0
            score -= int(OBJECTIVE_WEIGHTS["workload_balance"] * load_fraction * 10)

            # Continuity of care: bonus if patient was previously on this unit.
            if patient.get("previous_unit") == bed["unit"]:
                score += OBJECTIVE_WEIGHTS["continuity_of_care"]

            # Add this term to the objective.
            # CP-SAT works with integers, so we've kept everything as ints above.
            objective_terms.append(score * var)

    model.Maximize(sum(objective_terms))

    return model, x, patients, beds
```

---

## Step 4: Solve and Extract Recommendations

*The pseudocode calls this `solve_and_recommend(model, state, solve_time_limit_seconds)`. Run the solver, check the result status, and translate the mathematical solution back into human-readable bed assignments.*

```python
def solve_assignment(model, x, patients, beds) -> dict:
    """
    Run the CP-SAT solver and extract the recommended assignments.

    The solver explores the space of valid assignments and finds the one
    that maximizes our weighted objective. For typical hospital sizes
    (20-40 pending patients, 50-100 available beds), this takes 1-3 seconds.

    Returns:
        Dictionary with solve status, recommendations, and unassigned patients.
    """
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_SECONDS

    # Solve the model.
    status = solver.Solve(model)

    # Interpret the solver status.
    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",       # found a solution but may not be optimal (hit time limit)
        cp_model.INFEASIBLE: "INFEASIBLE",   # no valid assignment exists
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, "UNKNOWN")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": status_name,
            "solve_time_ms": int(solver.WallTime() * 1000),
            "recommendations": [],
            "unassigned_patients": [p["patient_id"] for p in patients],
            "message": "No feasible assignment found. Check constraint feasibility.",
        }

    # Extract assignments from the solution.
    recommendations = []
    assigned_patient_indices = set()

    for p_idx, patient in enumerate(patients):
        for b_idx, bed in enumerate(beds):
            if (p_idx, b_idx) in x and solver.Value(x[(p_idx, b_idx)]) == 1:
                assigned_patient_indices.add(p_idx)

                # Build the reasoning explanation.
                reasoning = build_reasoning(patient, bed)

                recommendations.append({
                    "patient_id": patient["patient_id"],
                    "recommended_bed": bed["bed_id"],
                    "unit": bed["unit"],
                    "reasoning": reasoning,
                    "wait_minutes": patient["waiting_since_minutes"],
                    "acuity": patient["acuity"],
                    "isolation": patient["isolation"],
                })

    # Identify patients who couldn't be assigned.
    unassigned = []
    for p_idx, patient in enumerate(patients):
        if p_idx not in assigned_patient_indices:
            unassigned.append({
                "patient_id": patient["patient_id"],
                "reason": explain_unassignment(patient, beds),
            })

    return {
        "status": status_name,
        "solve_time_ms": int(solver.WallTime() * 1000),
        "objective_value": solver.ObjectiveValue(),
        "recommendations": recommendations,
        "unassigned_patients": unassigned,
    }


def build_reasoning(patient: dict, bed: dict) -> list:
    """
    Generate human-readable explanations for why this bed was chosen.
    Bed coordinators need to understand the recommendation to trust it.
    """
    reasons = []

    # Acuity match
    ideal_units = ACUITY_UNIT_COMPATIBILITY.get(patient["acuity"], [])
    if ideal_units and bed["unit_type"] == ideal_units[0]:
        reasons.append(f"{patient['acuity']} acuity matches {bed['unit']} level of care")
    else:
        reasons.append(f"{bed['unit']} is acceptable for {patient['acuity']} acuity (not primary match)")

    # Continuity
    if patient.get("previous_unit") == bed["unit"]:
        reasons.append(f"Patient previously on {bed['unit']} (continuity bonus)")

    # Isolation
    if patient["isolation"] != "NONE":
        reasons.append(f"{patient['isolation']} isolation satisfied by {bed['room_type']} room")

    # Workload
    reasons.append(f"Unit at {UNIT_STAFFING[bed['unit']]['current_census']}/{UNIT_STAFFING[bed['unit']]['staffed_capacity']} staffed capacity")

    return reasons


def explain_unassignment(patient: dict, beds: list) -> str:
    """
    Explain why a patient couldn't be assigned. This helps bed coordinators
    take manual action (open overflow, expedite a discharge, etc.).
    """
    # Check what's blocking this patient.
    if patient["isolation"] == "AIRBORNE":
        neg_pressure_available = any(
            b["room_type"] == "NEGATIVE_PRESSURE" and b["status"] == "AVAILABLE"
            for b in beds
        )
        if not neg_pressure_available:
            return "No negative-pressure bed available. Required for airborne isolation."

    compatible_units = ACUITY_UNIT_COMPATIBILITY.get(patient["acuity"], [])
    available_in_compatible = any(
        b["unit_type"] in compatible_units and b["status"] == "AVAILABLE"
        for b in beds
    )
    if not available_in_compatible:
        return f"No available bed in compatible unit types: {compatible_units}"

    return "All compatible beds assigned to higher-priority patients."
```

---

## Step 5: Store Recommendations in DynamoDB

*The pseudocode calls this `publish_recommendations(recommendations)`. In production, this also pushes WebSocket notifications to the bed management dashboard. Here we just persist to DynamoDB.*

```python
def store_recommendations(result: dict) -> None:
    """
    Write optimization results to DynamoDB for the bed management UI to read.

    Each recommendation gets its own record with a TTL so stale recommendations
    auto-expire. In production, you'd also push these via WebSocket to the
    coordinator's screen in real-time.
    """
    table = dynamodb.Table(RECOMMENDATIONS_TABLE_NAME)
    now = datetime.datetime.now(timezone.utc)
    run_id = f"opt-{now.strftime('%Y%m%d-%H%M%S')}"

    # Store each recommendation as a separate item.
    # Partition key: patient_id (so you can query "what's the current recommendation for this patient?")
    # Sort key: run_id (so you can see recommendation history)
    for rec in result["recommendations"]:
        item = {
            "patient_id": rec["patient_id"],
            "run_id": run_id,
            "recommended_bed": rec["recommended_bed"],
            "unit": rec["unit"],
            "reasoning": rec["reasoning"],
            "status": "PENDING",  # PENDING -> ACCEPTED | OVERRIDDEN | EXPIRED
            "created_at": now.isoformat(),
            "expires_at": (now + datetime.timedelta(minutes=15)).isoformat(),
            "ttl": int((now + datetime.timedelta(hours=24)).timestamp()),
            "solve_status": result["status"],
            "solve_time_ms": Decimal(str(result["solve_time_ms"])),
        }
        table.put_item(Item=item)
        logger.info(f"Stored recommendation: {rec['patient_id']} -> {rec['recommended_bed']}")

    # Store unassigned patients so the UI can show them with explanations.
    for unassigned in result["unassigned_patients"]:
        item = {
            "patient_id": unassigned["patient_id"],
            "run_id": run_id,
            "recommended_bed": "NONE",
            "unit": "UNASSIGNED",
            "reasoning": [unassigned["reason"]],
            "status": "NO_BED_AVAILABLE",
            "created_at": now.isoformat(),
            "ttl": int((now + datetime.timedelta(hours=24)).timestamp()),
        }
        table.put_item(Item=item)
        logger.info(f"Stored unassigned: {unassigned['patient_id']} - {unassigned['reason']}")
```

---

## Full Pipeline: End-to-End Optimization Run

This assembles all the steps into a single callable function. In production, this would be triggered by Step Functions on a hybrid schedule (event-triggered with debouncing). Here you can just call it directly.

```python
def run_bed_assignment_optimization():
    """
    Execute a complete bed assignment optimization cycle.

    In production, this runs every time the debounce timer fires (typically
    60 seconds after the last state change, or every 5 minutes regardless).
    Each run takes a fresh snapshot of hospital state and produces new
    recommendations.
    """
    print("=" * 60)
    print("PATIENT FLOW BED ASSIGNMENT OPTIMIZATION")
    print("=" * 60)

    # Step 1: Get available beds from current state.
    print("\n[Step 1] Gathering available beds...")
    available_beds = get_available_beds(BED_INVENTORY)
    print(f"  Found {len(available_beds)} available/soon-available beds")
    for bed in available_beds:
        print(f"    {bed['bed_id']} ({bed['unit']}, {bed['room_type']}, {bed['status']})")

    # Step 2: Get pending patients.
    print(f"\n[Step 2] {len(PENDING_PATIENTS)} patients waiting for beds:")
    for patient in PENDING_PATIENTS:
        print(f"    {patient['patient_id']}: {patient['acuity']}, "
              f"isolation={patient['isolation']}, waiting {patient['waiting_since_minutes']}min")

    # Step 3: Build the optimization model.
    print("\n[Step 3] Building optimization model...")
    model, x, patients, beds = build_optimization_model(
        PENDING_PATIENTS, available_beds, UNIT_STAFFING
    )
    num_variables = len(x)
    print(f"  Created {num_variables} decision variables (feasible patient-bed pairs)")
    print(f"  Infeasible pairs excluded: {len(patients) * len(beds) - num_variables}")

    # Step 4: Solve.
    print(f"\n[Step 4] Solving (time limit: {SOLVER_TIME_LIMIT_SECONDS}s)...")
    result = solve_assignment(model, x, patients, beds)
    print(f"  Status: {result['status']}")
    print(f"  Solve time: {result['solve_time_ms']}ms")
    if "objective_value" in result:
        print(f"  Objective value: {result['objective_value']}")

    # Step 5: Display recommendations.
    print(f"\n[Step 5] Recommendations ({len(result['recommendations'])} assignments):")
    print("-" * 60)
    for rec in result["recommendations"]:
        print(f"\n  Patient: {rec['patient_id']}")
        print(f"  Assign to: {rec['recommended_bed']} ({rec['unit']})")
        print(f"  Acuity: {rec['acuity']} | Isolation: {rec['isolation']}")
        print(f"  Wait time: {rec['wait_minutes']} minutes")
        print(f"  Reasoning:")
        for reason in rec["reasoning"]:
            print(f"    - {reason}")

    if result["unassigned_patients"]:
        print(f"\n  UNASSIGNED ({len(result['unassigned_patients'])} patients):")
        for unassigned in result["unassigned_patients"]:
            print(f"    {unassigned['patient_id']}: {unassigned['reason']}")

    # Step 6: Store results (uncomment when DynamoDB table exists).
    # print("\n[Step 6] Storing recommendations to DynamoDB...")
    # store_recommendations(result)
    # print("  Done.")

    print("\n" + "=" * 60)
    print("OPTIMIZATION COMPLETE")
    print("=" * 60)

    return result


# Run it.
if __name__ == "__main__":
    run_bed_assignment_optimization()
```

---

## Gap to Production

This example demonstrates the optimization math. Here's what you'd need to add for a real deployment:

**Real-time state ingestion.** Replace the hardcoded `BED_INVENTORY` and `PENDING_PATIENTS` with a Kinesis consumer that processes ADT events (HL7 A01/A02/A03/A08 messages) and maintains the DynamoDB state table in real-time. Every admit, discharge, and transfer updates the state within seconds.

**Debounced triggering.** Instead of running on demand, use EventBridge + ElastiCache Redis to implement the hybrid trigger: state changes start a 60-second debounce timer in Redis. When the timer fires (no new changes for 60 seconds), it triggers the Step Functions workflow that runs the optimizer. A separate EventBridge rule triggers every 5 minutes regardless as a baseline.

**WebSocket push notifications.** When new recommendations are generated, push them to connected bed coordinators via API Gateway WebSocket. The coordinator sees the recommendation appear on their screen within seconds of the optimization completing. No polling, no refresh button.

**Override tracking and feedback loop.** When a coordinator accepts or overrides a recommendation, log the decision with a reason code. Aggregate override patterns weekly. If the system is consistently overridden for a specific constraint (e.g., "that room has a broken call light"), add that constraint to the model. This is how the system gets smarter over time.

**Error handling and retries.** The solver can fail (model invalid, timeout with no feasible solution). Step Functions handles retries with exponential backoff. If the solver consistently fails, alert the on-call engineer and fall back to a simple priority-queue heuristic (assign highest-priority patient to first available compatible bed).

**Input validation.** Validate all state data before feeding it to the optimizer. A corrupted bed record (missing unit type, null status) can make the model infeasible or produce nonsensical recommendations. Validate early, fail loudly.

**Structured logging.** Every optimization run should log: input state summary (how many beds, how many patients, constraint counts), solve time, solution quality (objective gap), and recommendation count. Use JSON-formatted logs for CloudWatch Logs Insights queries. Never log patient names or identifiers in plain text.

**IAM least-privilege.** The Lambda running the optimizer needs read access to the state table and write access to the recommendations table. It does not need access to the raw ADT event stream, patient demographics, or clinical data beyond what's in the state model. Scope the IAM policy tightly.

**VPC configuration.** In production, the optimizer Lambda runs in a VPC to access ElastiCache Redis (which is VPC-only). Configure VPC endpoints for DynamoDB and CloudWatch to avoid routing that traffic through a NAT gateway. The EHR integration (ADT event source) likely requires VPC connectivity via Direct Connect or VPN.

**KMS encryption.** Use customer-managed KMS keys for DynamoDB encryption at rest. The state table contains patient identifiers and clinical attributes (acuity, isolation status). Enable in-transit encryption for ElastiCache. All API Gateway endpoints use TLS.

**Testing.** Unit test the feasibility function exhaustively (every constraint combination). Integration test the full pipeline with synthetic ADT event sequences. Load test with realistic hospital sizes (400+ beds, 30+ pending patients) to verify solve times stay under your SLA. Test the infeasible case (more patients than beds, conflicting constraints) to ensure graceful degradation.

**DynamoDB Decimal handling.** Note that we already use `Decimal(str(...))` for numeric values stored in DynamoDB. The boto3 DynamoDB resource does not accept Python floats. If you skip this conversion, `put_item` raises a `TypeError`. This is a common gotcha that catches people on their first DynamoDB project.

**Solver warm-starting.** For the periodic re-optimization (every 5 minutes), you can warm-start the solver with the previous solution as a hint. This often cuts solve time by 50-70% because the new problem is usually similar to the previous one (only a few state changes between runs). OR-Tools CP-SAT supports solution hints via `model.AddHint()`.

---

| [← 14.6: Patient Flow / Bed Assignment](chapter14.06-patient-flow-bed-assignment) | [Chapter 14 Index](chapter14-index) | [14.7: OR Case Sequencing →](chapter14.07-or-case-sequencing) |
