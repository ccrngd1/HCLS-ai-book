# Recipe 14.8: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the ambulance routing and dispatch optimization from Recipe 14.8. It demonstrates the core concepts (fleet state management, candidate scoring with coverage awareness, hospital destination selection, and background repositioning optimization) using a combination of boto3 and Google OR-Tools. It is not production-ready. The fleet is tiny, travel times are synthetic, and there's no real GPS stream or CAD integration. Think of it as the whiteboard sketch that helps you understand how the dispatch scoring and coverage optimization actually work under the hood. A starting point, not a destination.
>
> The main recipe uses Kinesis for GPS ingestion, ElastiCache for travel time caching, and SageMaker for demand forecasting. This example runs everything locally with in-memory state and a simple grid-based coverage model. The optimization math is identical; the infrastructure is stripped away so you can focus on the decision logic.

---

## Setup

You'll need the optimization solver and AWS SDK installed:

```bash
pip install boto3 ortools
```

`ortools` is Google's open-source optimization suite. We use the linear solver (SCIP backend) for the repositioning coverage problem, which is formulated as a set-covering assignment. It's free, actively maintained, and handles the scale of a typical metro EMS fleet (20-60 units, 50-200 demand zones) in seconds.

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `dynamodb:PutItem`
- `dynamodb:GetItem`
- `dynamodb:Query`
- `geo:CalculateRouteMatrix` (if you swap in real Location Service calls)

For the full pipeline (with Kinesis GPS ingestion, ElastiCache, SageMaker demand forecasting, and Step Functions orchestration), you'd need additional permissions, but this example keeps the focus on the dispatch and coverage optimization logic.

---

## Configuration and Constants

```python
import json
import math
import logging
import datetime
from datetime import timezone
from decimal import Decimal
from typing import Optional

import boto3
from botocore.config import Config
from ortools.linear_solver import pywraplp

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Table where we store dispatch decisions for audit trail.
DISPATCH_TABLE_NAME = "ems-dispatch-decisions"

# Response time targets (seconds). These come from NFPA 1710 and local
# medical direction protocols. Priority 1 = life-threatening emergency.
RESPONSE_TIME_TARGETS = {
    1: 480,   # 8 minutes for Priority 1 (cardiac arrest, major trauma)
    2: 600,   # 10 minutes for Priority 2 (chest pain, difficulty breathing)
    3: 900,   # 15 minutes for Priority 3 (falls, minor injuries)
    4: 1200,  # 20 minutes for Priority 4 (non-emergency transports)
    5: 1800,  # 30 minutes for Priority 5 (scheduled transfers)
}

# Unit capability levels. ALS units carry paramedics with cardiac monitors,
# intubation equipment, and IV medications. BLS units have EMTs with basic
# interventions. You cannot send a BLS unit to an ALS-required call.
CAPABILITY_LEVELS = {
    "ALS": 2,  # Advanced Life Support (paramedic)
    "BLS": 1,  # Basic Life Support (EMT)
}

# Scoring weights for the dispatch optimizer. These control the trade-off
# between "send the fastest unit" and "preserve system coverage."
# Tuned per system based on historical performance analysis.
DISPATCH_WEIGHTS = {
    "response_time": 0.60,   # dominant factor: get there fast
    "coverage_impact": 0.25, # don't leave zones uncovered
    "fatigue": 0.10,         # crew welfare (hours on shift)
    "workload": 0.05,        # balance calls across crews
}

# For Priority 1 calls, we override the weights to prioritize pure speed.
# Coverage concerns take a back seat when someone is dying.
PRIORITY_1_WEIGHTS = {
    "response_time": 0.90,
    "coverage_impact": 0.10,
    "fatigue": 0.0,
    "workload": 0.0,
}

# Coverage threshold: a zone is "covered" if at least one available unit
# can reach its centroid within this many seconds.
COVERAGE_THRESHOLD_SECONDS = 480  # 8 minutes

# Maximum repositioning moves per optimization cycle. Moving too many units
# at once creates chaos and dispatcher confusion.
MAX_REPOSITION_MOVES = 3

# Average ambulance speed for travel time estimation (km/h).
# Emergency response (lights and sirens) vs. non-emergency.
SPEED_EMERGENCY_KMH = 55   # urban average with L&S
SPEED_NORMAL_KMH = 35      # urban average without L&S
```

---

## Step 1: Fleet State Management

*The pseudocode calls this `process_gps_update`. In production, GPS events flow through Kinesis into a Lambda that updates DynamoDB. Here we model the fleet state in memory and show how you'd write it to DynamoDB for persistence.*

```python
def build_initial_fleet():
    """
    Create a synthetic fleet for demonstration. In production, this state
    lives in DynamoDB and is updated by the GPS ingestion pipeline.

    Each unit has:
    - unit_id: unique identifier (matches the MDT/radio callsign)
    - capability: ALS or BLS
    - latitude/longitude: current GPS position
    - status: AVAILABLE, DISPATCHED, EN_ROUTE, ON_SCENE, TRANSPORTING, AT_HOSPITAL
    - zone: which coverage zone the unit is currently in
    - shift_start: when this crew's shift began (for fatigue scoring)
    - calls_today: how many calls this crew has run (for workload balancing)
    """
    fleet = [
        {
            "unit_id": "MEDIC-1",
            "capability": "ALS",
            "latitude": 38.9072,
            "longitude": -77.0369,
            "status": "AVAILABLE",
            "zone": "ZONE-A",
            "shift_start": "2026-06-01T06:00:00Z",
            "calls_today": 3,
        },
        {
            "unit_id": "MEDIC-3",
            "capability": "ALS",
            "latitude": 38.9200,
            "longitude": -77.0200,
            "status": "AVAILABLE",
            "zone": "ZONE-B",
            "shift_start": "2026-06-01T06:00:00Z",
            "calls_today": 5,
        },
        {
            "unit_id": "MEDIC-5",
            "capability": "ALS",
            "latitude": 38.8950,
            "longitude": -77.0500,
            "status": "EN_ROUTE",
            "zone": "ZONE-C",
            "shift_start": "2026-06-01T06:00:00Z",
            "calls_today": 4,
        },
        {
            "unit_id": "BLS-2",
            "capability": "BLS",
            "latitude": 38.9100,
            "longitude": -77.0450,
            "status": "AVAILABLE",
            "zone": "ZONE-A",
            "shift_start": "2026-06-01T18:00:00Z",
            "calls_today": 1,
        },
        {
            "unit_id": "BLS-4",
            "capability": "BLS",
            "latitude": 38.9300,
            "longitude": -77.0100,
            "status": "AVAILABLE",
            "zone": "ZONE-D",
            "shift_start": "2026-06-01T18:00:00Z",
            "calls_today": 2,
        },
    ]
    return fleet


def get_available_units(fleet, required_capability="BLS"):
    """
    Filter fleet to units that are available and meet the capability requirement.

    ALS units can handle both ALS and BLS calls (paramedics can do everything
    EMTs can do, plus more). BLS units can only handle BLS calls.
    """
    available = []
    for unit in fleet:
        if unit["status"] != "AVAILABLE":
            continue
        # ALS units satisfy any capability requirement.
        # BLS units only satisfy BLS requirements.
        unit_level = CAPABILITY_LEVELS[unit["capability"]]
        required_level = CAPABILITY_LEVELS[required_capability]
        if unit_level >= required_level:
            available.append(unit)
    return available
```

---

## Step 2: Travel Time Estimation

*The main recipe uses Amazon Location Service for real road-network travel times with traffic. Here we use the Haversine formula with a speed estimate as a stand-in. In production, you'd call Location Service's CalculateRouteMatrix API and cache results in ElastiCache.*

```python
def haversine_distance_km(lat1, lon1, lat2, lon2):
    """
    Calculate straight-line distance between two GPS coordinates in kilometers.
    This is the "as the crow flies" distance. Real road distance is typically
    1.3x to 1.6x longer in urban areas (the "circuity factor").
    """
    R = 6371  # Earth's radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def estimate_travel_time_seconds(origin_lat, origin_lon, dest_lat, dest_lon,
                                  emergency=True):
    """
    Estimate travel time in seconds between two points.

    In production, replace this with a call to Amazon Location Service:
        client.calculate_route(
            CalculatorName="ems-router",
            DeparturePosition=[origin_lon, origin_lat],
            DestinationPosition=[dest_lon, dest_lat],
            TravelMode="Car",
            DepartNow=True
        )

    The Location Service response includes DurationSeconds accounting for
    real-time traffic. You'd then apply an emergency vehicle multiplier
    (typically 0.7x to 0.8x of civilian travel time for L&S response).

    For this example, we use Haversine distance with a circuity factor
    and speed estimate. It's wrong, but it's wrong in a predictable way
    that lets you see the optimization logic clearly.
    """
    straight_line_km = haversine_distance_km(
        origin_lat, origin_lon, dest_lat, dest_lon
    )

    # Urban circuity factor: roads aren't straight lines.
    # 1.4 is typical for grid-pattern cities. Winding suburbs might be 1.6+.
    road_distance_km = straight_line_km * 1.4

    speed_kmh = SPEED_EMERGENCY_KMH if emergency else SPEED_NORMAL_KMH
    travel_time_hours = road_distance_km / speed_kmh
    travel_time_seconds = travel_time_hours * 3600

    return travel_time_seconds
```

---

## Step 3: Dispatch Scoring

*The pseudocode calls this `score_candidates`. This is the heart of the system: evaluating each available unit against a call and producing a ranked list. The scoring function balances response time against system-level concerns like coverage preservation and crew welfare.*

```python
def compute_coverage_impact(unit, fleet, demand_zones):
    """
    Estimate how much system coverage degrades if we dispatch this unit.

    The idea: if this unit is the only one covering its zone, removing it
    creates a critical gap. If three other units can also cover that zone,
    removing this one barely matters.

    Returns a score from 0.0 (no impact) to 1.0 (critical gap created).
    """
    zone = unit["zone"]

    # Count how many other available units can cover this zone
    other_units_in_zone = 0
    for other in fleet:
        if other["unit_id"] == unit["unit_id"]:
            continue
        if other["status"] != "AVAILABLE":
            continue
        if other["zone"] == zone:
            other_units_in_zone += 1

    # Also check adjacent units that could reach this zone within threshold
    # (simplified: in production, use actual travel times to zone centroid)
    zone_centroid = demand_zones.get(zone, {}).get("centroid")
    if zone_centroid:
        for other in fleet:
            if other["unit_id"] == unit["unit_id"]:
                continue
            if other["status"] != "AVAILABLE":
                continue
            if other["zone"] == zone:
                continue  # already counted
            travel = estimate_travel_time_seconds(
                other["latitude"], other["longitude"],
                zone_centroid[0], zone_centroid[1],
                emergency=True,
            )
            if travel <= COVERAGE_THRESHOLD_SECONDS:
                other_units_in_zone += 0.5  # partial credit for adjacent coverage

    # Convert to impact score: fewer backup units = higher impact
    if other_units_in_zone >= 2:
        return 0.1  # well-covered zone, minimal impact
    elif other_units_in_zone >= 1:
        return 0.4  # one backup, moderate concern
    else:
        return 0.9  # no backup, critical gap if we send this unit


def normalize_value(value, max_value):
    """Normalize a value to 0.0-1.0 range. Clamps at 1.0."""
    return min(value / max_value, 1.0)


def score_candidates(call, fleet, demand_zones):
    """
    Score all available, capable units for a given call.

    Args:
        call: dict with location, priority, required_capability, nature_code
        fleet: list of all unit dicts (current fleet state)
        demand_zones: dict of zone_id -> {centroid, demand_weight}

    Returns:
        List of candidate dicts sorted by score (ascending = best first).
        Each candidate includes unit_id, travel_time, score, and coverage_impact.
    """
    required_cap = call.get("required_capability", "BLS")
    available = get_available_units(fleet, required_cap)

    if not available:
        logger.warning("No available units meet capability requirement: %s", required_cap)
        return []

    # Select weight profile based on call priority
    weights = PRIORITY_1_WEIGHTS if call["priority"] == 1 else DISPATCH_WEIGHTS

    candidates = []
    now = datetime.datetime.now(timezone.utc)

    for unit in available:
        # Travel time from unit's current position to call location
        travel_time = estimate_travel_time_seconds(
            unit["latitude"], unit["longitude"],
            call["location"]["lat"], call["location"]["lng"],
            emergency=True,
        )

        # Coverage impact: what happens to system coverage if we send this unit?
        coverage_impact = compute_coverage_impact(unit, fleet, demand_zones)

        # Fatigue: hours on shift. Slight penalty after 10 hours.
        shift_start = datetime.datetime.fromisoformat(
            unit["shift_start"].replace("Z", "+00:00")
        )
        hours_on_shift = (now - shift_start).total_seconds() / 3600
        fatigue_penalty = max(0.0, (hours_on_shift - 10) * 0.1)

        # Workload: calls run today, normalized against a reasonable max
        workload_score = normalize_value(unit["calls_today"], 10)

        # Composite score (lower is better)
        score = (
            weights["response_time"] * normalize_value(travel_time, 1200)
            + weights["coverage_impact"] * coverage_impact
            + weights["fatigue"] * normalize_value(fatigue_penalty, 1.0)
            + weights["workload"] * workload_score
        )

        candidates.append({
            "unit_id": unit["unit_id"],
            "capability": unit["capability"],
            "travel_time_seconds": round(travel_time),
            "coverage_impact": round(coverage_impact, 2),
            "score": round(score, 4),
        })

    # Sort by score ascending (best candidate first)
    candidates.sort(key=lambda c: c["score"])
    return candidates
```

---

## Step 4: Hospital Destination Selection

*The pseudocode calls this `select_hospital`. After the unit arrives on scene and assesses the patient, the system recommends the best destination hospital based on clinical needs, transport time, and current capacity.*

```python
def build_hospital_status():
    """
    Synthetic hospital status data. In production, this comes from hospital
    systems via EventBridge (diversion status, ED census, bed availability)
    and is stored in DynamoDB for fast lookup.
    """
    hospitals = [
        {
            "hospital_id": "HOSP-GWU",
            "name": "GW University Hospital",
            "location": {"lat": 38.9007, "lng": -77.0508},
            "capabilities": ["cath_lab", "interventional_cardiology",
                             "level_1_trauma", "stroke_center"],
            "ed_capacity": 45,
            "current_ed_census": 24,
            "diversion_status": "OPEN",  # OPEN, CONDITIONAL, FULL_DIVERSION
        },
        {
            "hospital_id": "HOSP-MEDSTAR",
            "name": "MedStar Washington Hospital Center",
            "location": {"lat": 38.9296, "lng": -77.0164},
            "capabilities": ["cath_lab", "interventional_cardiology",
                             "level_1_trauma", "stroke_center", "burn_center"],
            "ed_capacity": 60,
            "current_ed_census": 52,
            "diversion_status": "CONDITIONAL",
        },
        {
            "hospital_id": "HOSP-SIBLEY",
            "name": "Sibley Memorial Hospital",
            "location": {"lat": 38.9378, "lng": -77.1052},
            "capabilities": ["stroke_center", "general_surgery"],
            "ed_capacity": 30,
            "current_ed_census": 12,
            "diversion_status": "OPEN",
        },
    ]
    return hospitals


def select_hospital(patient_needs, unit_location, hospitals):
    """
    Recommend the best destination hospital for a patient.

    Args:
        patient_needs: dict with required_capabilities (list), acuity_level (1-5)
        unit_location: dict with lat, lng (ambulance's current position)
        hospitals: list of hospital status dicts

    Returns:
        Best hospital dict with transport_time and score, or None if no
        eligible hospital found (which would be a serious system failure
        in a real deployment).
    """
    eligible = []

    for hospital in hospitals:
        # Hard filter: must have all required capabilities
        has_all_caps = all(
            cap in hospital["capabilities"]
            for cap in patient_needs["required_capabilities"]
        )
        if not has_all_caps:
            continue

        # Hard filter: diversion status
        if hospital["diversion_status"] == "FULL_DIVERSION":
            continue
        if (hospital["diversion_status"] == "CONDITIONAL"
                and patient_needs["acuity_level"] > 2):
            # Conditional diversion: only accepting critical patients (acuity 1-2)
            continue

        # Transport time from unit's current location to hospital
        transport_seconds = estimate_travel_time_seconds(
            unit_location["lat"], unit_location["lng"],
            hospital["location"]["lat"], hospital["location"]["lng"],
            emergency=True,
        )

        # Capacity score: how full is the ED? (0.0 = empty, 1.0 = at capacity)
        capacity_ratio = hospital["current_ed_census"] / hospital["ed_capacity"]

        # Composite destination score (lower is better)
        dest_score = (
            0.50 * normalize_value(transport_seconds, 1800)  # transport time
            + 0.35 * capacity_ratio                           # ED crowding
            + 0.15 * (0.0 if len(hospital["capabilities"]) > 3 else 0.3)
            # slight preference for higher-capability hospitals
        )

        eligible.append({
            **hospital,
            "transport_time_seconds": round(transport_seconds),
            "transport_time_minutes": round(transport_seconds / 60, 1),
            "capacity_ratio": round(capacity_ratio, 2),
            "score": round(dest_score, 4),
        })

    if not eligible:
        logger.error("No eligible hospitals found for patient needs: %s",
                     patient_needs)
        return None

    # Sort by score ascending (best destination first)
    eligible.sort(key=lambda h: h["score"])
    return eligible[0]
```

---

## Step 5: Coverage Optimization (Repositioning)

*The pseudocode calls this `optimize_repositioning`. This is the background solver that runs every few minutes. It identifies coverage gaps (zones where no available unit can respond within the target time) and computes optimal unit repositioning moves to close those gaps. This is where OR-Tools earns its keep.*

```python
def build_demand_zones():
    """
    Define coverage zones with centroids and demand weights.
    In production, these come from the demand forecast model (SageMaker endpoint)
    which predicts call probability per zone for the next 30 minutes.
    """
    zones = {
        "ZONE-A": {"centroid": (38.9072, -77.0369), "demand_weight": 0.30},
        "ZONE-B": {"centroid": (38.9200, -77.0200), "demand_weight": 0.25},
        "ZONE-C": {"centroid": (38.8950, -77.0500), "demand_weight": 0.20},
        "ZONE-D": {"centroid": (38.9300, -77.0100), "demand_weight": 0.15},
        "ZONE-E": {"centroid": (38.8800, -77.0300), "demand_weight": 0.10},
    }
    return zones


def identify_coverage_gaps(fleet, demand_zones):
    """
    Find zones where no available unit can respond within the coverage threshold.

    Returns a list of gap dicts: zone_id, centroid, best_current_time, demand_weight.
    These are the zones the repositioning optimizer needs to fix.
    """
    available_units = [u for u in fleet if u["status"] == "AVAILABLE"]
    gaps = []

    for zone_id, zone_info in demand_zones.items():
        # Skip very low demand zones (not worth repositioning for)
        if zone_info["demand_weight"] < 0.05:
            continue

        centroid = zone_info["centroid"]

        # Find the fastest available unit that could reach this zone
        best_time = float("inf")
        for unit in available_units:
            travel = estimate_travel_time_seconds(
                unit["latitude"], unit["longitude"],
                centroid[0], centroid[1],
                emergency=True,
            )
            best_time = min(best_time, travel)

        if best_time > COVERAGE_THRESHOLD_SECONDS:
            gaps.append({
                "zone_id": zone_id,
                "centroid": centroid,
                "best_current_time": round(best_time),
                "demand_weight": zone_info["demand_weight"],
            })

    return gaps


def optimize_repositioning(fleet, demand_zones):
    """
    Solve the repositioning problem: which idle units should move where
    to close coverage gaps?

    This is formulated as a weighted set-covering assignment problem:
    - Decision variables: binary (assign unit i to gap j, yes/no)
    - Objective: minimize total repositioning cost weighted by coverage priority
    - Constraints: each gap covered by at most one unit, total moves <= MAX

    Uses OR-Tools' linear solver (SCIP backend) which handles this scale
    (5-50 units, 5-200 zones) in milliseconds.
    """
    gaps = identify_coverage_gaps(fleet, demand_zones)

    if not gaps:
        logger.info("Coverage is adequate. No repositioning needed.")
        return []

    available_units = [u for u in fleet if u["status"] == "AVAILABLE"]

    if not available_units:
        logger.warning("No available units for repositioning.")
        return []

    logger.info("Found %d coverage gaps. %d units available for repositioning.",
                len(gaps), len(available_units))

    # Create the solver
    solver = pywraplp.Solver.CreateSolver("SCIP")
    if not solver:
        logger.error("Could not create SCIP solver. Is OR-Tools installed correctly?")
        return []

    # Decision variables: x[i][j] = 1 if unit i is assigned to cover gap j
    x = {}
    for i, unit in enumerate(available_units):
        for j, gap in enumerate(gaps):
            x[i, j] = solver.IntVar(0, 1, f"x_{i}_{j}")

    # Constraint: each unit can be assigned to at most one gap
    for i in range(len(available_units)):
        solver.Add(
            sum(x[i, j] for j in range(len(gaps))) <= 1
        )

    # Constraint: each gap gets at most one unit assigned
    for j in range(len(gaps)):
        solver.Add(
            sum(x[i, j] for i in range(len(available_units))) <= 1
        )

    # Constraint: total moves limited
    solver.Add(
        sum(x[i, j]
            for i in range(len(available_units))
            for j in range(len(gaps)))
        <= MAX_REPOSITION_MOVES
    )

    # Objective: minimize repositioning cost, weighted by gap priority.
    # Cost = travel time to reach the gap's centroid.
    # Priority = demand weight of the uncovered zone (higher demand = more important to cover).
    objective = solver.Objective()
    for i, unit in enumerate(available_units):
        for j, gap in enumerate(gaps):
            travel = estimate_travel_time_seconds(
                unit["latitude"], unit["longitude"],
                gap["centroid"][0], gap["centroid"][1],
                emergency=False,  # repositioning is non-emergency driving
            )
            # Cost coefficient: travel time penalized, but reduced for high-demand gaps
            # (we're willing to drive farther to cover a high-demand zone)
            cost = travel * (1.0 - 0.5 * gap["demand_weight"])
            objective.SetCoefficient(x[i, j], cost)

    objective.SetMinimization()

    # Solve
    status = solver.Solve()

    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        logger.warning("Repositioning solver did not find a feasible solution.")
        return []

    # Extract solution: which units move where?
    moves = []
    for i, unit in enumerate(available_units):
        for j, gap in enumerate(gaps):
            if x[i, j].solution_value() > 0.5:
                travel = estimate_travel_time_seconds(
                    unit["latitude"], unit["longitude"],
                    gap["centroid"][0], gap["centroid"][1],
                    emergency=False,
                )
                moves.append({
                    "unit_id": unit["unit_id"],
                    "from_zone": unit["zone"],
                    "to_zone": gap["zone_id"],
                    "target_position": {
                        "lat": gap["centroid"][0],
                        "lng": gap["centroid"][1],
                    },
                    "repositioning_time_seconds": round(travel),
                    "gap_demand_weight": gap["demand_weight"],
                    "reason": f"Coverage gap in {gap['zone_id']} "
                              f"(best current response: {gap['best_current_time']}s, "
                              f"threshold: {COVERAGE_THRESHOLD_SECONDS}s)",
                })

    logger.info("Repositioning solution: %d moves.", len(moves))
    return moves
```

---

## Step 6: Store Dispatch Decision

*Every dispatch decision is written to DynamoDB for the audit trail. In EMS, every decision is reviewable. Medical directors, quality assurance teams, and legal proceedings all need to understand why a particular unit was sent to a particular call.*

```python
def store_dispatch_decision(decision):
    """
    Write a dispatch decision record to DynamoDB.

    This is the audit trail. Every field matters for post-incident review:
    - Which unit was assigned and why?
    - What were the alternatives?
    - What was the estimated response time?
    - What hospital was recommended?

    In production, this table has a TTL for old records (retain 7 years
    per state EMS record retention requirements) and is encrypted with
    a KMS CMK.
    """
    table = dynamodb.Table(DISPATCH_TABLE_NAME)

    # DynamoDB requires Decimal for numeric values, not float.
    # This is a known boto3 gotcha that will raise TypeError if you forget.
    record = json.loads(json.dumps(decision), parse_float=Decimal)

    table.put_item(Item=record)
    logger.info("Stored dispatch decision: %s", decision.get("call_id", "unknown"))
    return record
```

---

## Putting It All Together

Here's the full dispatch pipeline assembled into a single callable function. This is what your Lambda handler would invoke when a 911 call arrives from the CAD system.

```python
def dispatch_ambulance(call):
    """
    Run the full dispatch optimization for a single incoming call.

    Args:
        call: dict with:
            - call_id: unique identifier from CAD system
            - location: {lat, lng}
            - priority: 1-5 (1 = life-threatening)
            - required_capability: "ALS" or "BLS"
            - nature_code: e.g., "CHEST_PAIN", "FALL", "MVA"
            - patient_age: (optional) for clinical context

    Returns:
        Complete dispatch decision dict with assigned unit, recommended hospital,
        coverage impact assessment, and all candidates considered.
    """
    logger.info("=" * 60)
    logger.info("DISPATCH REQUEST: %s", call["call_id"])
    logger.info("  Priority: %d | Nature: %s | Capability: %s",
                call["priority"], call["nature_code"], call["required_capability"])
    logger.info("  Location: (%.4f, %.4f)",
                call["location"]["lat"], call["location"]["lng"])

    # Load current fleet state (in production: read from DynamoDB)
    fleet = build_initial_fleet()
    demand_zones = build_demand_zones()

    # Score all available, capable units
    candidates = score_candidates(call, fleet, demand_zones)

    if not candidates:
        logger.error("NO AVAILABLE UNITS. Call %s cannot be assigned.", call["call_id"])
        return {"call_id": call["call_id"], "status": "UNASSIGNED", "reason": "no_units"}

    # Best candidate is first in the sorted list
    assigned = candidates[0]
    logger.info("  Assigned: %s (travel: %ds, score: %.4f)",
                assigned["unit_id"], assigned["travel_time_seconds"], assigned["score"])

    # Select destination hospital based on call nature
    # (In reality, hospital selection happens after on-scene assessment,
    # but we compute a preliminary recommendation at dispatch time)
    patient_needs = _infer_patient_needs(call)
    hospitals = build_hospital_status()

    # Use call location as proxy for unit location (unit hasn't arrived yet)
    recommended_hospital = select_hospital(
        patient_needs, call["location"], hospitals
    )

    if recommended_hospital:
        logger.info("  Hospital: %s (transport: %.1f min, capacity: %d%%)",
                    recommended_hospital["name"],
                    recommended_hospital["transport_time_minutes"],
                    int(recommended_hospital["capacity_ratio"] * 100))

    # Build the complete dispatch decision record
    decision = {
        "call_id": call["call_id"],
        "call_priority": call["priority"],
        "call_location": call["location"],
        "nature_code": call["nature_code"],
        "assigned_unit": {
            "unit_id": assigned["unit_id"],
            "capability": assigned["capability"],
            "estimated_response_time_seconds": assigned["travel_time_seconds"],
        },
        "recommended_hospital": {
            "hospital_id": recommended_hospital["hospital_id"],
            "name": recommended_hospital["name"],
            "transport_time_minutes": recommended_hospital["transport_time_minutes"],
            "capacity_ratio": recommended_hospital["capacity_ratio"],
        } if recommended_hospital else None,
        "coverage_impact": {
            "assigned_unit_impact": assigned["coverage_impact"],
            "backup_available": assigned["coverage_impact"] < 0.5,
        },
        "candidates_evaluated": len(candidates),
        "all_candidates": candidates[:5],  # top 5 for audit trail
        "decision_timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "target_response_time_seconds": RESPONSE_TIME_TARGETS[call["priority"]],
        "meets_target": (
            assigned["travel_time_seconds"]
            <= RESPONSE_TIME_TARGETS[call["priority"]]
        ),
    }

    logger.info("  Meets target: %s (%ds vs %ds threshold)",
                decision["meets_target"],
                assigned["travel_time_seconds"],
                RESPONSE_TIME_TARGETS[call["priority"]])
    logger.info("=" * 60)

    return decision


def _infer_patient_needs(call):
    """
    Map call nature codes to hospital capability requirements.
    In production, this mapping comes from medical direction protocols
    and is maintained by the EMS medical director.
    """
    nature_to_capabilities = {
        "CHEST_PAIN": {"required_capabilities": ["cath_lab"], "acuity_level": 1},
        "STEMI": {"required_capabilities": ["cath_lab", "interventional_cardiology"],
                  "acuity_level": 1},
        "STROKE": {"required_capabilities": ["stroke_center"], "acuity_level": 1},
        "TRAUMA_MAJOR": {"required_capabilities": ["level_1_trauma"], "acuity_level": 1},
        "FALL": {"required_capabilities": [], "acuity_level": 3},
        "MVA": {"required_capabilities": ["general_surgery"], "acuity_level": 2},
        "DIFFICULTY_BREATHING": {"required_capabilities": [], "acuity_level": 2},
    }
    return nature_to_capabilities.get(
        call["nature_code"],
        {"required_capabilities": [], "acuity_level": 3},
    )


# --- Run the full example ---
if __name__ == "__main__":
    # Simulate an incoming Priority 1 cardiac call
    incoming_call = {
        "call_id": "CAD-2026-0601-1847",
        "location": {"lat": 38.9100, "lng": -77.0350},
        "priority": 1,
        "required_capability": "ALS",
        "nature_code": "CHEST_PAIN",
        "patient_age": 67,
    }

    # Run dispatch optimization
    decision = dispatch_ambulance(incoming_call)
    print("\n--- DISPATCH DECISION ---")
    print(json.dumps(decision, indent=2, default=str))

    # Run background repositioning optimization
    print("\n--- REPOSITIONING OPTIMIZATION ---")
    fleet = build_initial_fleet()
    demand_zones = build_demand_zones()
    moves = optimize_repositioning(fleet, demand_zones)
    for move in moves:
        print(f"  MOVE: {move['unit_id']} -> {move['to_zone']} "
              f"({move['repositioning_time_seconds']}s) | {move['reason']}")
    if not moves:
        print("  No repositioning needed. Coverage is adequate.")
```

---

## The Gap Between This and Production

This example works. Run it and you'll get a scored dispatch decision and repositioning recommendations. But there's a meaningful distance between "works in a script" and "handles real 911 calls." Here's where that gap lives:

**Real travel times.** The Haversine approximation is wildly inaccurate for urban routing. A point 1 km away across a river with no bridge might be 15 minutes by road. Production requires Amazon Location Service (or equivalent) with real-time traffic data. You'd call `calculate_route_matrix` to get many-to-many travel times for all candidate units simultaneously, then cache results in ElastiCache with a 2-3 minute TTL.

**GPS streaming pipeline.** This example uses static fleet positions. Production ingests GPS updates every 5-15 seconds from every unit via Kinesis Data Streams. A Lambda consumer updates DynamoDB on each fix. You need conditional writes (only accept newer timestamps) to handle out-of-order delivery, and you need to detect GPS staleness (unit hasn't reported in 60 seconds = position is unreliable).

**Demand forecasting.** The static demand weights here are a placeholder. Production trains a time-series model on historical call data (time of day, day of week, weather, events) and hosts it on a SageMaker endpoint. The repositioning optimizer queries this model every cycle to get current demand predictions. Even a simple model (gradient-boosted trees on temporal features) dramatically outperforms static weights.

**Hospital status integration.** Hospital diversion status, ED census, and bed availability change constantly. Production subscribes to hospital system feeds (HL7 ADT messages, proprietary APIs, or even manual updates from hospital liaisons) via EventBridge. The hospital status table in DynamoDB must have a "last updated" timestamp so you can detect stale data and fall back to conservative assumptions.

**CAD system integration.** The dispatch decision needs to flow back to the Computer-Aided Dispatch system that dispatchers use. This is typically a proprietary system (Tyler New World, Hexagon, Motorola PremierOne) with its own API or HL7 interface. Integration testing with the CAD vendor is a multi-month effort.

**Latency budget.** A Priority 1 dispatch must complete in under 2 seconds end-to-end. That means: API Gateway receives the request (50ms), Lambda cold start (eliminated with provisioned concurrency), DynamoDB reads (single-digit ms), travel time lookups (cache hit: 1ms, cache miss with Location Service: 200-500ms), scoring computation (10-50ms), DynamoDB write (single-digit ms). Every millisecond matters. Profile relentlessly.

**Error handling and fallback.** If the Location Service is down, fall back to cached travel times (even if stale). If DynamoDB is unreachable, fall back to an in-memory snapshot. If the scoring function throws an exception, fall back to pure proximity dispatch. The system must always produce an answer. "Sorry, the optimizer crashed" is not acceptable when someone is having a heart attack.

**Simulation and backtesting.** Before deploying any change to the scoring weights or coverage model, replay 6 months of historical calls through the new logic and compare response time distributions against the old logic. Build a discrete-event simulator that models unit state transitions, travel times, on-scene times, and hospital turnaround times. This is your safety net.

**Dispatcher override tracking.** Dispatchers will (and should) override the system's recommendations. Track every override: which unit was recommended, which was actually sent, and why. This data is gold for improving the model. If dispatchers consistently override in a specific scenario, the model is missing something.

**Multi-casualty incident (MCI) mode.** The optimization model assumes independent, sequential calls. An MCI (bus crash, building collapse) generates 5-20 simultaneous patients and requires a completely different allocation strategy. Production needs an MCI detection trigger that switches the system from normal optimization to MCI protocols (triage-based allocation, staging areas, transport coordination).

**Audit and compliance.** Every dispatch decision is a medical record. Retain for 7+ years per state EMS regulations. Encrypt at rest with KMS CMK. Enable CloudTrail for all API calls. The DynamoDB table needs point-in-time recovery enabled. Consider DynamoDB export to S3 for long-term archival.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 14.8](chapter14.08-ambulance-routing-dispatch) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
