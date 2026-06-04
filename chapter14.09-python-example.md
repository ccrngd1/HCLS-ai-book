# Recipe 14.9: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the chemotherapy scheduling optimization from Recipe 14.9. It demonstrates the core concepts (resource modeling, constraint formulation, solver invocation, pharmacy coordination, and real-time disruption handling) using Google OR-Tools CP-SAT solver and boto3 for schedule persistence. It is not production-ready. The infusion center is small, durations are synthetic, and there's no real EHR integration or pharmacy system connection. Think of it as the whiteboard sketch that helps you understand how the constraint model and multi-resource scheduling actually work under the hood. A starting point, not a destination.
>
> The main recipe uses SageMaker for duration prediction, Step Functions for workflow orchestration, and EventBridge for disruption routing. This example runs the optimization locally with hardcoded patient data and a simple duration estimator. The constraint math is identical; the infrastructure is stripped away so you can focus on the scheduling logic.

---

## Setup

You'll need the optimization solver and AWS SDK installed:

```bash
pip install boto3 ortools
```

`ortools` is Google's open-source optimization suite. We use the CP-SAT (Constraint Programming with Satisfiability) solver, which is purpose-built for scheduling problems with complex constraints. It handles the scale of a typical infusion center (30-50 chairs, 40-80 patients/day) in seconds. Free, actively maintained, and battle-tested on scheduling problems far larger than ours.

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `dynamodb:PutItem`
- `dynamodb:GetItem`
- `dynamodb:Query`
- `dynamodb:UpdateItem`

For the full pipeline (with SageMaker duration prediction, Step Functions orchestration, EventBridge disruption routing, and API Gateway for the staff dashboard), you'd need additional permissions. This example keeps the focus on the optimization logic itself.

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

# Table where we store the published schedule.
SCHEDULE_TABLE_NAME = "chemo-schedules"

# Operating hours in minutes from midnight. Most infusion centers run
# 7 AM to 6 PM, though some extend to 7 PM for long regimens.
DAY_START_MINUTES = 7 * 60   # 07:00
DAY_END_MINUTES = 18 * 60    # 18:00

# Time granularity for the model. We discretize the day into 15-minute
# periods for nursing capacity tracking. Finer granularity = more accurate
# workload leveling but slower solve times. 15 minutes is the sweet spot
# for most centers.
PERIOD_LENGTH_MINUTES = 15

# Buffer between patients in the same chair. Covers cleaning, linen change,
# and pump reset. 15 minutes is standard; some centers use 20 for isolation chairs.
TURNOVER_BUFFER_MINUTES = 15

# Nursing ratio constraints. These come from your state's nurse practice act
# and your center's internal policies. The numbers below are representative;
# your center's may differ.
MAX_PATIENTS_PER_NURSE_GENERAL = 5    # stable patients, mid-infusion
MAX_PATIENTS_PER_NURSE_FIRST_DOSE = 2  # first dose = higher monitoring
MAX_PATIENTS_PER_NURSE_PREMEDICATION = 3  # pre-med phase needs attention

# Pharmacy constraints. How many bags can pharmacy prep per hour?
# This depends on hood count, staffing, and verification bottlenecks.
MAX_PHARMACY_PREPS_PER_HOUR = 8

# Objective function weights. These encode your center's priorities.
# Tune these based on what leadership cares about most.
# Note: This simplified example only implements utilization and preference
# objectives in the solver. The full weight structure is documented here
# to show the production objective described in the main recipe's pseudocode.
WEIGHTS = {
    "utilization": 0.35,       # fill those chairs
    "wait_time": 0.25,         # don't make patients sit in the lobby
    "workload_leveling": 0.25, # even nursing demand across the day
    "preferences": 0.15,       # respect patient time preferences
}
```

---

## Treatment Protocol Definitions

Before we get to the optimizer, we need to define what chemotherapy regimens look like from a scheduling perspective. Each regimen has phases with different durations and nursing requirements. In production, these come from your EHR's protocol library. Here we hardcode a representative set.

```python
# Each protocol defines the phases of a patient visit and their characteristics.
# duration_minutes: how long this phase takes
# nursing_attention: fraction of a nurse's attention required (1.0 = dedicated nurse)
# phase_type: categorization for constraint grouping
#
# These are simplified. Real protocols have dose-dependent durations,
# patient-weight adjustments, and conditional phases (e.g., "if reaction,
# add 60 min observation"). The optimizer handles variable durations through
# the predicted_duration field on each scheduling request.

PROTOCOLS = {
    "FOLFOX": {
        "name": "FOLFOX (Colorectal)",
        "phases": [
            {"type": "pre_medication", "duration_minutes": 30, "nursing_attention": 0.33},
            {"type": "oxaliplatin", "duration_minutes": 120, "nursing_attention": 0.25},
            {"type": "5fu_bolus", "duration_minutes": 5, "nursing_attention": 0.50},
            {"type": "leucovorin", "duration_minutes": 120, "nursing_attention": 0.20},
            {"type": "observation", "duration_minutes": 15, "nursing_attention": 0.20},
        ],
        "pharmacy_prep_minutes": 45,
        "drug_stability_hours": 4,
    },
    "AC_TAXOL": {
        "name": "AC-Taxol (Breast)",
        "phases": [
            {"type": "pre_medication", "duration_minutes": 30, "nursing_attention": 0.33},
            {"type": "doxorubicin", "duration_minutes": 15, "nursing_attention": 0.50},
            {"type": "cyclophosphamide", "duration_minutes": 30, "nursing_attention": 0.25},
            {"type": "observation", "duration_minutes": 30, "nursing_attention": 0.20},
        ],
        "pharmacy_prep_minutes": 30,
        "drug_stability_hours": 6,
    },
    "HERCEPTIN": {
        "name": "Herceptin (Breast, maintenance)",
        "phases": [
            {"type": "infusion", "duration_minutes": 30, "nursing_attention": 0.20},
            {"type": "observation", "duration_minutes": 15, "nursing_attention": 0.20},
        ],
        "pharmacy_prep_minutes": 15,
        "drug_stability_hours": 24,
    },
    "PEMBROLIZUMAB": {
        "name": "Pembrolizumab (Immunotherapy)",
        "phases": [
            {"type": "pre_medication", "duration_minutes": 15, "nursing_attention": 0.33},
            {"type": "infusion", "duration_minutes": 30, "nursing_attention": 0.25},
            {"type": "observation", "duration_minutes": 30, "nursing_attention": 0.20},
        ],
        "pharmacy_prep_minutes": 20,
        "drug_stability_hours": 6,
    },
    "RCHOP": {
        "name": "R-CHOP (Lymphoma)",
        "phases": [
            {"type": "pre_medication", "duration_minutes": 30, "nursing_attention": 0.33},
            {"type": "rituximab", "duration_minutes": 180, "nursing_attention": 0.25},
            {"type": "chop_drugs", "duration_minutes": 60, "nursing_attention": 0.25},
            {"type": "observation", "duration_minutes": 30, "nursing_attention": 0.20},
        ],
        "pharmacy_prep_minutes": 60,
        "drug_stability_hours": 4,
    },
}


def get_total_duration(protocol_key: str) -> int:
    """Sum all phase durations for a protocol. Returns total minutes in chair."""
    protocol = PROTOCOLS[protocol_key]
    return sum(phase["duration_minutes"] for phase in protocol["phases"])


def get_nursing_demand_at_offset(protocol_key: str, offset_minutes: int) -> float:
    """
    Given a protocol and a time offset from the start of the visit,
    return the nursing attention demand at that moment.

    This is the key function for workload leveling. At any point in time,
    we can ask "how much nursing attention does this patient need right now?"
    and sum across all patients to get total demand for that time period.

    Note: This function is not used in the simplified optimizer below, which
    uses average attention per protocol as an approximation. A production
    implementation would call this function for each patient-period combination
    to get phase-specific demand, enabling more accurate workload leveling.
    """
    protocol = PROTOCOLS[protocol_key]
    elapsed = 0
    for phase in protocol["phases"]:
        if elapsed <= offset_minutes < elapsed + phase["duration_minutes"]:
            return phase["nursing_attention"]
        elapsed += phase["duration_minutes"]
    return 0.0  # past end of visit
```

---

## Step 1: Build Scheduling Requests

*Maps to pseudocode Step 1 (Ingest Treatment Orders) and Step 2 (Predict Durations). In production, these come from the EHR and a SageMaker duration prediction model. Here we use synthetic data with realistic distributions.*

```python
def build_scheduling_requests(target_date: str) -> list[dict]:
    """
    Build the list of patients who need scheduling for a given date.

    In production, this pulls from the EHR's pending treatment orders,
    enriches with protocol details, and calls the duration prediction model.
    Here we generate a realistic synthetic workload for a 20-chair center.

    Each request contains everything the optimizer needs:
    - Who (patient ID, cycle info)
    - What (protocol, phases, durations)
    - When (time window constraints)
    - How much (nursing demand, pharmacy prep needs)
    - Preferences (soft constraints the optimizer tries to satisfy)
    """
    # Synthetic patient list. In production, this comes from:
    # query_ehr_orders(status="pending_scheduling", date=target_date)
    patients = [
        {"id": "PT-001", "protocol": "FOLFOX", "cycle": 4, "is_first_dose": False,
         "preferred_start": "08:00", "preferred_window_hours": 1},
        {"id": "PT-002", "protocol": "RCHOP", "cycle": 1, "is_first_dose": True,
         "preferred_start": "08:00", "preferred_window_hours": 2},
        {"id": "PT-003", "protocol": "HERCEPTIN", "cycle": 12, "is_first_dose": False,
         "preferred_start": "09:00", "preferred_window_hours": 2},
        {"id": "PT-004", "protocol": "AC_TAXOL", "cycle": 2, "is_first_dose": False,
         "preferred_start": "08:30", "preferred_window_hours": 1},
        {"id": "PT-005", "protocol": "PEMBROLIZUMAB", "cycle": 6, "is_first_dose": False,
         "preferred_start": "10:00", "preferred_window_hours": 2},
        {"id": "PT-006", "protocol": "FOLFOX", "cycle": 8, "is_first_dose": False,
         "preferred_start": "07:00", "preferred_window_hours": 1},
        {"id": "PT-007", "protocol": "HERCEPTIN", "cycle": 8, "is_first_dose": False,
         "preferred_start": "11:00", "preferred_window_hours": 3},
        {"id": "PT-008", "protocol": "RCHOP", "cycle": 3, "is_first_dose": False,
         "preferred_start": "08:00", "preferred_window_hours": 1},
        {"id": "PT-009", "protocol": "AC_TAXOL", "cycle": 1, "is_first_dose": True,
         "preferred_start": "09:00", "preferred_window_hours": 2},
        {"id": "PT-010", "protocol": "PEMBROLIZUMAB", "cycle": 2, "is_first_dose": False,
         "preferred_start": "13:00", "preferred_window_hours": 2},
        {"id": "PT-011", "protocol": "FOLFOX", "cycle": 6, "is_first_dose": False,
         "preferred_start": "07:30", "preferred_window_hours": 1},
        {"id": "PT-012", "protocol": "HERCEPTIN", "cycle": 15, "is_first_dose": False,
         "preferred_start": "14:00", "preferred_window_hours": 3},
    ]

    requests = []
    for patient in patients:
        protocol = PROTOCOLS[patient["protocol"]]
        total_duration = get_total_duration(patient["protocol"])

        # Parse preferred start into minutes from midnight
        pref_hour, pref_min = map(int, patient["preferred_start"].split(":"))
        preferred_start_minutes = pref_hour * 60 + pref_min
        window_minutes = patient["preferred_window_hours"] * 60

        requests.append({
            "patient_id": patient["id"],
            "protocol_key": patient["protocol"],
            "protocol_name": protocol["name"],
            "cycle": patient["cycle"],
            "is_first_dose": patient["is_first_dose"],
            "total_duration_minutes": total_duration,
            "pharmacy_prep_minutes": protocol["pharmacy_prep_minutes"],
            "drug_stability_hours": protocol["drug_stability_hours"],
            "preferred_start_minutes": preferred_start_minutes,
            "preferred_window_minutes": window_minutes,
            # Hard constraints: earliest and latest possible start
            "earliest_start": DAY_START_MINUTES,
            "latest_start": DAY_END_MINUTES - total_duration,
        })

    print(f"Built {len(requests)} scheduling requests for {target_date}")
    for req in requests:
        print(f"  {req['patient_id']}: {req['protocol_name']} "
              f"(cycle {req['cycle']}, {req['total_duration_minutes']} min)")

    return requests
```

---

## Step 2: Build Resource Model

*Maps to pseudocode Step 3 (Build Resource Model). Defines what the infusion center has available: chairs, nursing capacity, and pharmacy prep slots.*

```python
def build_resource_model(num_chairs: int = 20, num_nurses: int = 6) -> dict:
    """
    Assemble the resource model for the infusion center.

    In production, this queries the staffing system (who's working today,
    what shift, what certifications) and the facilities system (which chairs
    are active, any maintenance). Here we define a simple static model.

    The key insight: resources aren't just counts. They're time-varying
    capacities. A nurse working 7 AM to 3 PM contributes differently than
    one working 10 AM to 6 PM. The model must capture this.
    """
    # Calculate time periods for the day
    num_periods = (DAY_END_MINUTES - DAY_START_MINUTES) // PERIOD_LENGTH_MINUTES

    # Nursing capacity per period. In this simplified model, all nurses
    # work the full day. In production, you'd have shift patterns:
    # early shift (7-3), late shift (10-6), mid shift (9-5), etc.
    # Each nurse provides 1.0 "attention units" per period.
    nursing_capacity_per_period = float(num_nurses)

    # Pharmacy prep capacity per hour. Constant here; in production it
    # might vary (fewer techs in early morning, peak at mid-morning).
    pharmacy_hours = (DAY_END_MINUTES - DAY_START_MINUTES) // 60
    pharmacy_capacity = [MAX_PHARMACY_PREPS_PER_HOUR] * pharmacy_hours

    model = {
        "num_chairs": num_chairs,
        "num_nurses": num_nurses,
        "num_periods": num_periods,
        "nursing_capacity_per_period": nursing_capacity_per_period,
        "pharmacy_capacity_per_hour": pharmacy_capacity,
        "day_start": DAY_START_MINUTES,
        "day_end": DAY_END_MINUTES,
        "period_length": PERIOD_LENGTH_MINUTES,
    }

    print(f"Resource model: {num_chairs} chairs, {num_nurses} nurses, "
          f"{num_periods} periods ({PERIOD_LENGTH_MINUTES}-min each)")
    print(f"  Operating hours: {DAY_START_MINUTES // 60}:00 - {DAY_END_MINUTES // 60}:00")
    print(f"  Pharmacy capacity: {MAX_PHARMACY_PREPS_PER_HOUR} preps/hour")

    return model
```

---

## Step 3: Run the Optimizer

*Maps to pseudocode Step 4 (Run the Optimizer). This is the core of the recipe. We formulate the scheduling problem as a constraint programming model and solve it with CP-SAT.*

```python
def optimize_schedule(requests: list[dict], resource_model: dict) -> dict:
    """
    The main optimization function. Takes patient requests and resource
    constraints, returns an optimized schedule.

    The formulation:
    - Decision variables: start time and chair assignment for each patient
    - Hard constraints: no chair overlap, nursing capacity, pharmacy capacity,
      drug stability windows, operating hours
    - Soft constraints (in objective): patient preferences, workload leveling
    - Objective: weighted combination of utilization, wait time, leveling, preferences

    CP-SAT works by exploring the space of feasible assignments, pruning
    branches that violate constraints, and optimizing the objective. For
    our problem size (12 patients, 20 chairs), it finds optimal solutions
    in under a second. For 80 patients and 50 chairs, expect 10-60 seconds.
    """
    model = cp_model.CpModel()
    num_patients = len(requests)
    num_chairs = resource_model["num_chairs"]
    num_periods = resource_model["num_periods"]
    day_start = resource_model["day_start"]
    day_end = resource_model["day_end"]
    period_length = resource_model["period_length"]

    # --- Decision Variables ---

    # start_vars[i]: the start time (in minutes from midnight) for patient i
    start_vars = []
    for i, req in enumerate(requests):
        start_vars.append(model.NewIntVar(
            req["earliest_start"],
            req["latest_start"],
            f"start_{req['patient_id']}"
        ))

    # chair_vars[i]: which chair (0 to num_chairs-1) patient i is assigned to
    chair_vars = []
    for i, req in enumerate(requests):
        chair_vars.append(model.NewIntVar(
            0, num_chairs - 1,
            f"chair_{req['patient_id']}"
        ))

    # --- Hard Constraints ---

    # Constraint 1: No two patients overlap in the same chair.
    # We use CP-SAT's conditional constraints with proper full reification.
    # For each pair of patients: if they share a chair, one must finish
    # (including turnover buffer) before the other starts.

    for i in range(num_patients):
        for j in range(i + 1, num_patients):
            duration_i = requests[i]["total_duration_minutes"] + TURNOVER_BUFFER_MINUTES
            duration_j = requests[j]["total_duration_minutes"] + TURNOVER_BUFFER_MINUTES

            # Boolean: are patients i and j in the same chair?
            same_chair = model.NewBoolVar(f"same_chair_{i}_{j}")
            model.Add(chair_vars[i] == chair_vars[j]).OnlyEnforceIf(same_chair)
            model.Add(chair_vars[i] != chair_vars[j]).OnlyEnforceIf(same_chair.Not())

            # If same chair, enforce temporal ordering (i before j OR j before i).
            # We use a single boolean to represent the ordering direction.
            i_before_j = model.NewBoolVar(f"order_{i}_{j}")

            # If same_chair AND i_before_j: i finishes before j starts
            model.Add(
                start_vars[i] + duration_i <= start_vars[j]
            ).OnlyEnforceIf(same_chair, i_before_j)

            # If same_chair AND NOT i_before_j: j finishes before i starts
            model.Add(
                start_vars[j] + duration_j <= start_vars[i]
            ).OnlyEnforceIf(same_chair, i_before_j.Not())

    # Constraint 2: Nursing capacity per time period.
    # For each 15-minute period, the total nursing demand from all patients
    # whose visit overlaps that period must not exceed available nurses.
    #
    # This is the trickiest constraint because nursing demand varies by phase.
    # We linearize it: for each patient and period, compute a boolean "is this
    # patient in this period?" and multiply by their nursing demand at that offset.

    # We approximate nursing demand using the maximum attention per patient
    # as a simplification. A full implementation would track phase-specific
    # demand, but that makes the model significantly more complex.
    # For this example, we use average nursing attention across the visit.

    for period_idx in range(num_periods):
        period_start = day_start + period_idx * period_length
        period_end = period_start + period_length

        # For each patient, determine if they overlap this period
        # and what their nursing demand would be.
        period_demand_terms = []

        for i, req in enumerate(requests):
            duration = req["total_duration_minutes"]

            # Boolean: does patient i overlap this period?
            # Patient i overlaps if: start_i < period_end AND start_i + duration > period_start
            # We need full channeling: overlaps must be True when the patient
            # is actually present, and False otherwise. Half-reification alone
            # would let the solver set overlaps=False even when the patient is
            # present, making the capacity constraint a no-op.
            overlaps = model.NewBoolVar(f"overlaps_{i}_p{period_idx}")

            # Forward: if overlaps, then both conditions hold
            model.Add(start_vars[i] < period_end).OnlyEnforceIf(overlaps)
            model.Add(start_vars[i] + duration > period_start).OnlyEnforceIf(overlaps)

            # Reverse: if NOT overlaps, then at least one condition is violated
            # (patient ends before period starts, OR patient starts after period ends)
            ends_before = model.NewBoolVar(f"ends_before_{i}_p{period_idx}")
            starts_after = model.NewBoolVar(f"starts_after_{i}_p{period_idx}")
            model.Add(start_vars[i] + duration <= period_start).OnlyEnforceIf(ends_before)
            model.Add(start_vars[i] >= period_end).OnlyEnforceIf(starts_after)
            model.AddBoolOr([ends_before, starts_after]).OnlyEnforceIf(overlaps.Not())

            # Compute average nursing attention for this protocol
            protocol = PROTOCOLS[req["protocol_key"]]
            total_attention = sum(
                p["nursing_attention"] * p["duration_minutes"]
                for p in protocol["phases"]
            )
            avg_attention = total_attention / duration

            # Scale to integer (CP-SAT works with integers).
            # Multiply by 100 to preserve two decimal places.
            attention_scaled = int(avg_attention * 100)
            period_demand_terms.append((overlaps, attention_scaled))

        # Sum of nursing demand in this period <= capacity (scaled)
        capacity_scaled = int(resource_model["nursing_capacity_per_period"] * 100)
        model.Add(
            sum(attention_scaled * overlaps
                for overlaps, attention_scaled in period_demand_terms)
            <= capacity_scaled
        )

    # Constraint 3: Pharmacy prep capacity per hour.
    # Each patient's prep must start pharmacy_prep_minutes before their
    # chair start time. No more than MAX_PHARMACY_PREPS_PER_HOUR can
    # start in any given hour.
    # Note: pharmacy operating hours may extend before center opening
    # (e.g., pharmacy starts at 6 AM for 7 AM patients). This model only
    # counts preps within center hours. Production systems would model
    # pharmacy capacity on its own timeline.

    for hour_idx in range(len(resource_model["pharmacy_capacity_per_hour"])):
        hour_start = day_start + hour_idx * 60
        hour_end = hour_start + 60

        preps_in_hour = []
        for i, req in enumerate(requests):
            # Pharmacy prep starts this many minutes before the patient's chair time
            prep_offset = req["pharmacy_prep_minutes"]

            # Boolean: does this patient's prep fall in this hour?
            # Prep start = start_vars[i] - prep_offset
            # Full channeling: prep_in_hour must be True iff prep is in [hour_start, hour_end)
            prep_in_hour = model.NewBoolVar(f"prep_{i}_hour{hour_idx}")

            # Forward: if prep_in_hour, prep start is within this hour
            model.Add(
                start_vars[i] - prep_offset >= hour_start
            ).OnlyEnforceIf(prep_in_hour)
            model.Add(
                start_vars[i] - prep_offset < hour_end
            ).OnlyEnforceIf(prep_in_hour)

            # Reverse: if NOT prep_in_hour, prep is outside this hour
            before_hour = model.NewBoolVar(f"prep_before_{i}_h{hour_idx}")
            after_hour = model.NewBoolVar(f"prep_after_{i}_h{hour_idx}")
            model.Add(start_vars[i] - prep_offset < hour_start).OnlyEnforceIf(before_hour)
            model.Add(start_vars[i] - prep_offset >= hour_end).OnlyEnforceIf(after_hour)
            model.AddBoolOr([before_hour, after_hour]).OnlyEnforceIf(prep_in_hour.Not())

            preps_in_hour.append(prep_in_hour)

        # At most MAX_PHARMACY_PREPS_PER_HOUR preps start in this hour
        model.Add(sum(preps_in_hour) <= resource_model["pharmacy_capacity_per_hour"][hour_idx])

    # Constraint 4: Drug stability window.
    # The time from pharmacy prep completion to infusion start must not
    # exceed the drug's beyond-use date (BUD).
    # Since prep completes at (start_time - prep_minutes + prep_minutes) = start_time,
    # and the drug is administered at start_time, this is automatically satisfied
    # in our simplified model. In production, you'd track actual prep completion
    # time separately (pharmacy might prep early if they have capacity).
    # The real drug stability risk is reactive: when a patient is delayed after
    # prep is complete, check whether the drug will expire before the new start time.

    # --- Objective Function ---

    # We combine multiple objectives into a single weighted score.
    # CP-SAT maximizes, so we formulate all terms as "higher is better."
    #
    # Note: The WEIGHTS dict defined at module level captures the intended
    # multi-objective balance (utilization, wait time, leveling, preferences).
    # This simplified example only implements utilization (earliness) and
    # preference satisfaction. A production implementation would add workload
    # leveling (minimax nursing demand) and explicit wait-time minimization.
    # The WEIGHTS dict is retained as documentation of the full objective
    # structure described in the main recipe's pseudocode.

    objective_terms = []

    # Objective 1: Minimize total schedule span (proxy for utilization).
    # Earlier starts = more compact schedule = higher utilization.
    # We minimize the sum of start times (scaled by weight).
    max_possible_start = day_end
    for i in range(num_patients):
        # "Earliness bonus": how much earlier than latest possible
        earliness = model.NewIntVar(0, max_possible_start, f"earliness_{i}")
        model.Add(earliness == requests[i]["latest_start"] - start_vars[i])
        objective_terms.append(earliness)  # higher earliness = better utilization

    # Objective 2: Patient preference satisfaction.
    # Bonus for scheduling within the patient's preferred window.
    # We need full channeling so the solver can't claim preference is met
    # when the patient is actually scheduled outside their window.
    preference_bonuses = []
    for i, req in enumerate(requests):
        pref_start = req["preferred_start_minutes"]
        pref_end = pref_start + req["preferred_window_minutes"]

        in_window = model.NewBoolVar(f"in_pref_{i}")

        # Forward: if in_window, start is within [pref_start, pref_end]
        model.Add(start_vars[i] >= pref_start).OnlyEnforceIf(in_window)
        model.Add(start_vars[i] <= pref_end).OnlyEnforceIf(in_window)

        # Reverse: if NOT in_window, start is outside the window
        # (before pref_start OR after pref_end)
        too_early = model.NewBoolVar(f"too_early_{i}")
        too_late = model.NewBoolVar(f"too_late_{i}")
        model.Add(start_vars[i] < pref_start).OnlyEnforceIf(too_early)
        model.Add(start_vars[i] > pref_end).OnlyEnforceIf(too_late)
        model.AddBoolOr([too_early, too_late]).OnlyEnforceIf(in_window.Not())

        # Bonus of 100 points for being in the preferred window
        preference_bonuses.append(in_window)

    # Objective 3: Workload leveling.
    # Minimize the maximum nursing demand across all periods.
    # A full implementation would track demand per period and use a minimax
    # formulation (minimize the peak). This is complex with conditional
    # variables in CP-SAT, so this simplified example relies on the nursing
    # capacity constraint (Constraint 2) to prevent overload, and uses
    # earliness + preferences as the optimization objectives.

    # Combine objectives
    model.Maximize(
        sum(objective_terms)  # earliness terms (utilization proxy)
        + 100 * sum(preference_bonuses)  # preference bonus
    )

    # --- Solve ---

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0  # time limit for large instances
    solver.parameters.num_search_workers = 4       # parallel search threads

    print("\nSolving schedule optimization...")
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        status_name = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        print(f"  Solution found: {status_name}")
        print(f"  Objective value: {solver.ObjectiveValue()}")
        print(f"  Solve time: {solver.WallTime():.2f} seconds")

        # Extract the solution
        assignments = []
        for i, req in enumerate(requests):
            start_time = solver.Value(start_vars[i])
            chair = solver.Value(chair_vars[i])
            end_time = start_time + req["total_duration_minutes"]
            prep_start = start_time - req["pharmacy_prep_minutes"]

            # Check if preference was met
            pref_met = (req["preferred_start_minutes"] <= start_time <=
                        req["preferred_start_minutes"] + req["preferred_window_minutes"])

            assignments.append({
                "patient_id": req["patient_id"],
                "protocol": req["protocol_key"],
                "cycle": req["cycle"],
                "chair_id": f"C-{chair + 1:02d}",
                "start_time_minutes": start_time,
                "start_time_display": f"{start_time // 60:02d}:{start_time % 60:02d}",
                "end_time_minutes": end_time,
                "end_time_display": f"{end_time // 60:02d}:{end_time % 60:02d}",
                "duration_minutes": req["total_duration_minutes"],
                "pharmacy_prep_start": f"{prep_start // 60:02d}:{prep_start % 60:02d}",
                "preference_met": pref_met,
                "is_first_dose": req["is_first_dose"],
            })

        # Sort by start time for readability
        assignments.sort(key=lambda a: a["start_time_minutes"])

        # Calculate summary metrics
        total_chair_minutes = sum(a["duration_minutes"] for a in assignments)
        available_chair_minutes = resource_model["num_chairs"] * (day_end - day_start)
        utilization = total_chair_minutes / available_chair_minutes
        preferences_met = sum(1 for a in assignments if a["preference_met"])

        schedule = {
            "status": status_name,
            "solve_time_seconds": round(solver.WallTime(), 2),
            "objective_value": solver.ObjectiveValue(),
            "assignments": assignments,
            "summary": {
                "total_patients": num_patients,
                "total_chair_minutes": total_chair_minutes,
                "utilization_rate": round(utilization, 3),
                "preferences_met": preferences_met,
                "preferences_total": num_patients,
                "preference_rate": round(preferences_met / num_patients, 2),
            },
        }

        return schedule

    else:
        print(f"  No solution found. Status: {solver.StatusName(status)}")
        print("  This usually means constraints are too tight.")
        print("  Try: adding chairs, relaxing time windows, or reducing patient count.")
        return {"status": "INFEASIBLE", "assignments": [], "summary": {}}
```

---

## Step 4: Build Pharmacy Prep Sequence

*Maps to the pharmacy coordination piece of pseudocode Step 5 (Validate and Publish). Once we have the schedule, we derive the pharmacy prep order so the pharmacy knows exactly when to start mixing each patient's drugs.*

```python
def build_pharmacy_sequence(schedule: dict) -> list[dict]:
    """
    Convert the optimized schedule into a pharmacy prep sequence.

    Pharmacy needs to know: which patient's drugs to prep, when to start,
    and the deadline (when the patient will be in the chair and ready).
    The sequence is ordered by prep start time so pharmacy can work
    through it chronologically.

    The drug stability constraint is critical here. If pharmacy preps too
    early, the drug expires before administration. If too late, the patient
    waits in the chair while pharmacy scrambles. The optimizer already
    accounts for this, but we make it explicit in the prep sequence.
    """
    if not schedule.get("assignments"):
        return []

    prep_sequence = []
    for assignment in schedule["assignments"]:
        protocol = PROTOCOLS[assignment["protocol"]]
        prep_start_minutes = (assignment["start_time_minutes"]
                              - protocol["pharmacy_prep_minutes"])
        stability_deadline_minutes = (assignment["start_time_minutes"]
                                      + protocol["drug_stability_hours"] * 60)

        prep_sequence.append({
            "patient_id": assignment["patient_id"],
            "protocol": assignment["protocol"],
            "prep_start_time": f"{prep_start_minutes // 60:02d}:{prep_start_minutes % 60:02d}",
            "prep_start_minutes": prep_start_minutes,
            "prep_duration_minutes": protocol["pharmacy_prep_minutes"],
            "patient_chair_time": assignment["start_time_display"],
            "drug_stability_deadline": f"{stability_deadline_minutes // 60:02d}:{stability_deadline_minutes % 60:02d}",
            "chair_id": assignment["chair_id"],
        })

    # Sort by prep start time (pharmacy works chronologically)
    prep_sequence.sort(key=lambda p: p["prep_start_minutes"])

    print(f"\nPharmacy prep sequence ({len(prep_sequence)} bags):")
    print(f"  {'Time':<8} {'Patient':<8} {'Protocol':<15} {'Chair Time':<12} {'Deadline'}")
    print(f"  {'-'*8} {'-'*8} {'-'*15} {'-'*12} {'-'*10}")
    for prep in prep_sequence:
        print(f"  {prep['prep_start_time']:<8} {prep['patient_id']:<8} "
              f"{prep['protocol']:<15} {prep['patient_chair_time']:<12} "
              f"{prep['drug_stability_deadline']}")

    return prep_sequence
```

---

## Step 5: Store Schedule to DynamoDB

*Maps to the persistence piece of pseudocode Step 5. The published schedule goes to DynamoDB where the staff dashboard, patient portal, and pharmacy system can read it.*

```python
def store_schedule(schedule: dict, target_date: str) -> str:
    """
    Write the optimized schedule to DynamoDB.

    The schedule record serves multiple consumers:
    - Staff dashboard: shows today's assignments, chair map, timeline view
    - Patient portal: shows confirmed appointment time
    - Pharmacy system: reads prep sequence and timing
    - Audit trail: records what was scheduled and why (objective value, solve time)

    We store the full schedule as a single item. For larger centers, you might
    partition by time block or chair group, but for most infusion centers
    a single item per day works fine (DynamoDB items can be up to 400 KB).
    """
    table = dynamodb.Table(SCHEDULE_TABLE_NAME)

    schedule_id = f"SCH-{target_date}-INF"
    now = datetime.datetime.now(timezone.utc).isoformat()

    # Convert floats to Decimals for DynamoDB
    def decimal_safe(obj):
        if isinstance(obj, float):
            return Decimal(str(round(obj, 4)))
        if isinstance(obj, dict):
            return {k: decimal_safe(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [decimal_safe(item) for item in obj]
        return obj

    record = {
        "schedule_id": schedule_id,
        "target_date": target_date,
        "created_at": now,
        "status": schedule.get("status", "UNKNOWN"),
        "solve_time_seconds": Decimal(str(schedule.get("solve_time_seconds", 0))),
        "summary": decimal_safe(schedule.get("summary", {})),
        "assignments": decimal_safe(schedule.get("assignments", [])),
    }

    table.put_item(Item=record)

    print(f"\nSchedule stored: {schedule_id}")
    print(f"  DynamoDB table: {SCHEDULE_TABLE_NAME}")
    print(f"  Patients scheduled: {schedule['summary'].get('total_patients', 0)}")
    print(f"  Utilization: {schedule['summary'].get('utilization_rate', 0):.1%}")

    return schedule_id
```

---

## Step 6: Handle Real-Time Disruptions

*Maps to pseudocode Step 6 (Handle Real-Time Adjustments). When reality diverges from the plan, this function finds the least-disruptive adjustment.*

```python
def handle_disruption(
    disruption_type: str,
    patient_id: str,
    schedule: dict,
    resource_model: dict,
    extra_minutes: int = 0,
) -> dict:
    """
    Handle a day-of disruption with minimal schedule impact.

    In production, disruptions arrive as EventBridge events and trigger
    a Lambda function. Here we demonstrate the decision logic for the
    three most common disruption types:

    1. Patient late: shift their start time, check for cascading conflicts
    2. Patient cancelled: free the slot, check waitlist
    3. Extended duration: patient needs more time than scheduled

    The key principle: minimize the number of other patients affected.
    A disruption to one patient should not cascade into rescheduling
    the entire day. Use buffers, swap chairs, or shift adjacent patients
    only when absolutely necessary.

    Note: This function mutates the schedule dict in place for simplicity.
    Production code would work on a copy and only commit changes after
    validation, enabling rollback if the adjustment creates new conflicts.
    """
    assignments = schedule.get("assignments", [])
    affected = next((a for a in assignments if a["patient_id"] == patient_id), None)

    if not affected:
        print(f"  Patient {patient_id} not found in schedule.")
        return schedule

    print(f"\nHandling disruption: {disruption_type} for {patient_id}")
    print(f"  Current assignment: Chair {affected['chair_id']}, "
          f"{affected['start_time_display']} - {affected['end_time_display']}")

    if disruption_type == "patient_late":
        # Can we absorb the delay in the turnover buffer?
        new_start = affected["start_time_minutes"] + extra_minutes
        new_end = new_start + affected["duration_minutes"]

        # Check if the new end time conflicts with the next patient in this chair
        same_chair = [a for a in assignments
                      if a["chair_id"] == affected["chair_id"]
                      and a["start_time_minutes"] > affected["start_time_minutes"]]
        same_chair.sort(key=lambda a: a["start_time_minutes"])

        if same_chair:
            next_patient = same_chair[0]
            gap = next_patient["start_time_minutes"] - new_end
            if gap >= TURNOVER_BUFFER_MINUTES:
                # Delay fits within existing gap. Just shift this patient.
                affected["start_time_minutes"] = new_start
                affected["start_time_display"] = f"{new_start // 60:02d}:{new_start % 60:02d}"
                affected["end_time_minutes"] = new_end
                affected["end_time_display"] = f"{new_end // 60:02d}:{new_end % 60:02d}"
                print(f"  Absorbed delay. New time: {affected['start_time_display']} - "
                      f"{affected['end_time_display']}")
            else:
                # Conflict. Try to move the late patient to an empty chair.
                used_chairs = {a["chair_id"] for a in assignments
                               if a["start_time_minutes"] < new_end
                               and a["end_time_minutes"] > new_start}
                all_chairs = {f"C-{i+1:02d}" for i in range(resource_model["num_chairs"])}
                free_chairs = all_chairs - used_chairs

                if free_chairs:
                    new_chair = sorted(free_chairs)[0]
                    affected["chair_id"] = new_chair
                    affected["start_time_minutes"] = new_start
                    affected["start_time_display"] = f"{new_start // 60:02d}:{new_start % 60:02d}"
                    affected["end_time_minutes"] = new_end
                    affected["end_time_display"] = f"{new_end // 60:02d}:{new_end % 60:02d}"
                    print(f"  Moved to {new_chair}. New time: "
                          f"{affected['start_time_display']} - {affected['end_time_display']}")
                else:
                    print(f"  WARNING: No resolution found. Manual intervention needed.")
        else:
            # No one after this patient in this chair. Just shift.
            affected["start_time_minutes"] = new_start
            affected["start_time_display"] = f"{new_start // 60:02d}:{new_start % 60:02d}"
            affected["end_time_minutes"] = new_end
            affected["end_time_display"] = f"{new_end // 60:02d}:{new_end % 60:02d}"
            print(f"  No conflict. Shifted to: {affected['start_time_display']} - "
                  f"{affected['end_time_display']}")

    elif disruption_type == "patient_cancelled":
        # Remove from schedule, note the freed slot
        assignments.remove(affected)
        print(f"  Removed {patient_id}. Chair {affected['chair_id']} free "
              f"{affected['start_time_display']} - {affected['end_time_display']}")
        print(f"  Check waitlist for patients needing ~{affected['duration_minutes']} min slot.")
        # In production: query waitlist, offer slot, notify pharmacy to cancel prep

    elif disruption_type == "extended_duration":
        # Patient needs more time. Check for conflicts.
        new_end = affected["end_time_minutes"] + extra_minutes
        affected["end_time_minutes"] = new_end
        affected["end_time_display"] = f"{new_end // 60:02d}:{new_end % 60:02d}"
        affected["duration_minutes"] += extra_minutes

        # Check if this conflicts with next patient in same chair
        same_chair = [a for a in assignments
                      if a["chair_id"] == affected["chair_id"]
                      and a["patient_id"] != patient_id
                      and a["start_time_minutes"] > affected["start_time_minutes"]]
        same_chair.sort(key=lambda a: a["start_time_minutes"])

        if same_chair:
            next_patient = same_chair[0]
            if new_end + TURNOVER_BUFFER_MINUTES > next_patient["start_time_minutes"]:
                print(f"  CONFLICT with {next_patient['patient_id']} at "
                      f"{next_patient['start_time_display']}. Needs reassignment.")
                # In production: trigger reoptimization for affected patients
            else:
                print(f"  Extended to {affected['end_time_display']}. No conflict.")
        else:
            print(f"  Extended to {affected['end_time_display']}. No conflict.")

    schedule["assignments"] = assignments
    return schedule
```

---

## Full Pipeline

Assembles all steps into a single callable function so you can see the end-to-end flow.

```python
def run_scheduling_pipeline(target_date: str = "2026-06-02") -> dict:
    """
    Run the complete chemotherapy scheduling pipeline for a target date.

    Steps:
    1. Build scheduling requests (from EHR orders + duration predictions)
    2. Build resource model (chairs, nurses, pharmacy capacity)
    3. Run the optimizer (CP-SAT constraint programming)
    4. Build pharmacy prep sequence
    5. Store the schedule to DynamoDB
    6. Print the final schedule for review

    In production, this runs as a Step Functions workflow triggered nightly
    by an EventBridge scheduled rule. Each step is a separate Lambda function
    with error handling and retry logic.
    """
    print("=" * 70)
    print(f"CHEMOTHERAPY SCHEDULING OPTIMIZATION")
    print(f"Target date: {target_date}")
    print("=" * 70)

    # Step 1: Build requests
    requests = build_scheduling_requests(target_date)

    # Step 2: Build resource model
    resource_model = build_resource_model(num_chairs=20, num_nurses=6)

    # Step 3: Optimize
    schedule = optimize_schedule(requests, resource_model)

    if schedule["status"] == "INFEASIBLE":
        print("\nSchedule optimization failed. Cannot proceed.")
        return schedule

    # Step 4: Pharmacy prep sequence
    pharmacy_sequence = build_pharmacy_sequence(schedule)
    schedule["pharmacy_sequence"] = pharmacy_sequence

    # Step 5: Store (uncomment when you have the DynamoDB table created)
    # schedule_id = store_schedule(schedule, target_date)

    # Print the final schedule
    print(f"\n{'=' * 70}")
    print(f"OPTIMIZED SCHEDULE")
    print(f"{'=' * 70}")
    print(f"\n{'Patient':<8} {'Protocol':<15} {'Chair':<7} {'Start':<7} "
          f"{'End':<7} {'Duration':<10} {'Pref Met'}")
    print(f"{'-'*8} {'-'*15} {'-'*7} {'-'*7} {'-'*7} {'-'*10} {'-'*8}")

    for a in schedule["assignments"]:
        pref = "Yes" if a["preference_met"] else "No"
        first = " [1st]" if a["is_first_dose"] else ""
        print(f"{a['patient_id']:<8} {a['protocol']:<15} {a['chair_id']:<7} "
              f"{a['start_time_display']:<7} {a['end_time_display']:<7} "
              f"{a['duration_minutes']:<10} {pref}{first}")

    summary = schedule["summary"]
    print(f"\nSummary:")
    print(f"  Patients scheduled: {summary['total_patients']}")
    print(f"  Chair utilization: {summary['utilization_rate']:.1%}")
    print(f"  Preferences met: {summary['preferences_met']}/{summary['preferences_total']} "
          f"({summary['preference_rate']:.0%})")
    print(f"  Solve time: {schedule['solve_time_seconds']}s")

    # Demonstrate disruption handling
    print(f"\n{'=' * 70}")
    print(f"DISRUPTION HANDLING DEMO")
    print(f"{'=' * 70}")

    # Simulate: PT-003 is 20 minutes late
    schedule = handle_disruption("patient_late", "PT-003", schedule, resource_model,
                                 extra_minutes=20)

    # Simulate: PT-005 cancelled
    schedule = handle_disruption("patient_cancelled", "PT-005", schedule, resource_model)

    # Simulate: PT-001 needs 30 extra minutes
    schedule = handle_disruption("extended_duration", "PT-001", schedule, resource_model,
                                 extra_minutes=30)

    return schedule


# Entry point
if __name__ == "__main__":
    result = run_scheduling_pipeline("2026-06-02")
```

---

## Gap to Production

This example demonstrates the optimization logic, but a production deployment needs significantly more. Here's the distance between this sketch and something you'd deploy to an infusion center:

**EHR integration.** Real treatment orders come from Epic, Cerner, or your oncology information system (like Aria or MOSAIQ). You need HL7 FHIR or ADT feeds, not hardcoded patient lists. The integration must handle order modifications, holds, and cancellations in real-time.

**Duration prediction model.** We used protocol-defined durations. Production systems train ML models on historical infusion data to predict actual durations per patient. Features include: regimen, cycle number, patient BMI, prior infusion times, day of week, and time of day. A SageMaker endpoint serves predictions with confidence intervals. The scheduler uses the upper bound of the CI for buffer calculation.

**Shift-aware nursing model.** Our model assumes all nurses work all day. Reality has overlapping shifts, lunch breaks, certifications (some nurses can't administer certain drugs), and patient continuity preferences. The resource model needs to be time-varying and nurse-specific.

**Pharmacy system integration.** Real pharmacy coordination requires bidirectional communication. The scheduler tells pharmacy when to prep; pharmacy tells the scheduler when prep is actually complete (or delayed). This feedback loop catches the case where pharmacy falls behind and patient start times need adjustment.

**Error handling and retries.** Every external call (EHR query, DynamoDB write, SageMaker invocation) can fail. Production code needs exponential backoff, circuit breakers, and graceful degradation. If the optimizer fails, fall back to the previous day's template rather than leaving staff with no schedule.

**Input validation.** Validate all incoming data: treatment orders must have valid regimen codes, dates must be in the future, patient IDs must exist in the system. Reject malformed inputs early rather than letting them corrupt the optimization.

**Structured logging.** Every scheduling decision needs an audit trail. Log the inputs (which patients, what constraints), the solver output (objective value, solve time, any relaxed constraints), and the published schedule. Use JSON-formatted logs for CloudWatch Logs Insights queries. Never log patient names or diagnosis information in plain text.

**IAM least-privilege.** The Lambda functions need only the specific DynamoDB actions on the specific table, the specific SageMaker endpoint invoke permission, and the specific S3 paths. Use resource-level policies, not wildcards.

**VPC and VPC endpoints.** Production deployment runs in a VPC with no internet access. Use VPC endpoints for DynamoDB, S3, SageMaker, and Step Functions. This prevents PHI from traversing the public internet.

**KMS customer-managed keys.** Encrypt DynamoDB tables and S3 buckets with CMKs you control. This gives you key rotation, access logging, and the ability to revoke access by disabling the key.

**Testing.** Unit tests for each constraint (does the no-overlap constraint actually prevent overlaps?). Integration tests with synthetic schedules of known optimal solutions. Load tests with 80+ patients to verify solve times stay under your SLA. Regression tests against historical schedules to ensure the optimizer doesn't degrade.

**Monitoring and alerting.** CloudWatch alarms on: solve time exceeding threshold, infeasible solutions (constraints too tight), schedule not published by deadline (e.g., 5 AM for same-day), and DynamoDB throttling. Dashboard showing daily utilization trends, preference satisfaction rates, and pharmacy waste metrics.

**Staff override workflow.** The optimizer's output is a recommendation, not a mandate. Staff need the ability to override any assignment with a reason code. Track overrides to identify systematic issues (if nurses always override a certain pattern, the constraint model is missing something).

---

[← Recipe 14.9: Chemotherapy Scheduling](chapter14.09-chemotherapy-scheduling) | [Chapter 14 Index](chapter14-preface) | [Recipe 14.10: Health System Network Design →](chapter14.10-health-system-network-design)
