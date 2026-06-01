# Recipe 14.10: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the network design optimization from Recipe 14.10. It demonstrates the mathematical formulation, solver invocation, and result interpretation using a small synthetic health system. It is not production-ready. A real network design model would have thousands of variables, validated demand forecasts, and calibrated gravity model parameters. Think of this as the sketch on the whiteboard that shows you the shape of the problem. A starting point, not a destination.

---

## Setup

You'll need PuLP (a Python linear programming library that wraps open-source solvers) and boto3 for the AWS integration pieces:

```bash
pip install pulp boto3 numpy
```

PuLP ships with the CBC solver (COIN-OR Branch and Cut), which handles mixed-integer programs out of the box. For larger problems, you'd swap in HiGHS or Gurobi, but CBC is fine for learning the formulation.

Your environment needs AWS credentials configured if you want to run the S3 storage and SageMaker pieces. For just the optimization logic, you only need PuLP and numpy.

---

## Config and Constants

Before we get to the optimization logic, here's the problem data. In a real system, this comes from your data warehouse (patient origin analysis, financial models, demographic projections). Here we define a small synthetic health system so you can actually run this and see results.

```python
import numpy as np
from pulp import (
    LpProblem, LpMaximize, LpVariable, LpBinary, LpContinuous,
    LpInteger, lpSum, PULP_CBC_CMD, value
)
import json
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

# --- SYNTHETIC HEALTH SYSTEM ---
# A small system with 3 existing facilities, 2 candidate new sites,
# 8 demand zones, and 3 service lines. Small enough to solve instantly,
# large enough to show the formulation patterns.

FACILITIES = {
    "main_campus": {
        "name": "Main Campus Downtown",
        "type": "existing",
        "lat": 39.95, "lon": -75.17,
        "current_services": ["primary_care", "cardiology", "orthopedics"],
    },
    "suburban_east": {
        "name": "Suburban Campus East",
        "type": "existing",
        "lat": 39.98, "lon": -75.05,
        "current_services": ["primary_care"],
    },
    "community_north": {
        "name": "Community Hospital North",
        "type": "existing",
        "lat": 40.05, "lon": -75.15,
        "current_services": ["primary_care", "orthopedics"],
    },
    "candidate_south": {
        "name": "Candidate Site South",
        "type": "candidate",  # not yet built
        "lat": 39.88, "lon": -75.20,
        "current_services": [],
    },
    "candidate_west": {
        "name": "Candidate Site West",
        "type": "candidate",
        "lat": 39.95, "lon": -75.30,
        "current_services": [],
    },
}

SERVICE_LINES = {
    "primary_care": {
        "revenue_per_case": 250,
        "min_volume_threshold": 500,   # need at least 500 visits/year to justify
        "fixed_annual_cost": 800000,   # staff, space, overhead
    },
    "cardiology": {
        "revenue_per_case": 4500,
        "min_volume_threshold": 200,   # accreditation requires minimum volume
        "fixed_annual_cost": 5000000,
    },
    "orthopedics": {
        "revenue_per_case": 6000,
        "min_volume_threshold": 150,
        "fixed_annual_cost": 4000000,
    },
}

# Demand zones: geographic areas with projected annual demand by service line.
# In reality these come from patient origin analysis + demographic projections.
DEMAND_ZONES = {
    "zone_downtown": {"lat": 39.95, "lon": -75.16, "demand": {"primary_care": 3000, "cardiology": 400, "orthopedics": 300}},
    "zone_northeast": {"lat": 40.02, "lon": -75.05, "demand": {"primary_care": 2500, "cardiology": 250, "orthopedics": 200}},
    "zone_north": {"lat": 40.06, "lon": -75.14, "demand": {"primary_care": 2000, "cardiology": 180, "orthopedics": 250}},
    "zone_south": {"lat": 39.87, "lon": -75.18, "demand": {"primary_care": 2800, "cardiology": 320, "orthopedics": 280}},
    "zone_west": {"lat": 39.94, "lon": -75.32, "demand": {"primary_care": 1800, "cardiology": 150, "orthopedics": 180}},
    "zone_southeast": {"lat": 39.90, "lon": -75.08, "demand": {"primary_care": 2200, "cardiology": 200, "orthopedics": 190}},
    "zone_northwest": {"lat": 40.03, "lon": -75.28, "demand": {"primary_care": 1500, "cardiology": 120, "orthopedics": 130}},
    "zone_central": {"lat": 39.97, "lon": -75.20, "demand": {"primary_care": 2600, "cardiology": 280, "orthopedics": 220}},
}

# Capital costs for opening new facilities or adding service lines.
# Existing facilities adding a new service line still incur capital costs
# (renovations, equipment, recruitment).
CAPITAL_COSTS = {
    "new_facility_base": 25000000,       # base cost to open a candidate site
    "add_primary_care": 2000000,         # add primary care to any site
    "add_cardiology": 15000000,          # cath lab, equipment, recruitment
    "add_orthopedics": 12000000,         # OR suites, imaging, recruitment
}

TOTAL_BUDGET = 60000000  # $60M capital budget for this planning cycle

# Capacity limits (annual cases) per facility per service line.
CAPACITY_PER_FACILITY = {
    "primary_care": 4000,
    "cardiology": 600,
    "orthopedics": 500,
}

# Distance sensitivity by service line (higher = patients less willing to travel).
# These would normally come from gravity model calibration.
DISTANCE_BETA = {
    "primary_care": 0.8,   # patients strongly prefer nearby primary care
    "cardiology": 0.3,     # patients will travel for cardiac care
    "orthopedics": 0.4,    # moderate willingness to travel
}
```

---

## Step 1: Compute Travel Times

*The main recipe's Step 2 estimates a gravity model from historical patient flows. Here we use a simplified distance-based utility model. The math is the same; we just skip the parameter estimation step since we don't have historical data to calibrate against.*

```python
def compute_travel_time(zone: dict, facility: dict) -> float:
    """
    Compute approximate travel time in minutes between a demand zone
    and a facility using straight-line distance with a road-network multiplier.

    In production, you'd use a real routing API (Google Maps, HERE, OSRM)
    to get actual drive times. Straight-line distance with a 1.4x multiplier
    is a common approximation for planning purposes.
    """
    # Haversine-lite: at these latitudes, 1 degree lat ~ 69 miles, 1 degree lon ~ 53 miles
    lat_diff = abs(zone["lat"] - facility["lat"]) * 69
    lon_diff = abs(zone["lon"] - facility["lon"]) * 53
    straight_line_miles = np.sqrt(lat_diff**2 + lon_diff**2)

    # Road network multiplier: roads aren't straight lines
    road_miles = straight_line_miles * 1.4

    # Assume average 30 mph in urban/suburban setting
    travel_minutes = (road_miles / 30) * 60

    return travel_minutes


def compute_choice_probabilities(zones: dict, facilities: dict, service_line: str) -> dict:
    """
    Compute patient choice probabilities using a gravity model.

    The gravity model says: probability of choosing facility f from zone z
    is proportional to exp(-beta * travel_time(z, f)).

    Facilities that don't offer the service line get zero probability.
    This function returns probabilities assuming ALL facilities offer the service;
    the optimizer will zero out flows to facilities that don't.
    """
    beta = DISTANCE_BETA[service_line]
    probabilities = {}

    for zone_id, zone_data in zones.items():
        utilities = {}
        for fac_id, fac_data in facilities.items():
            travel = compute_travel_time(zone_data, fac_data)
            # Gravity model: utility decays exponentially with travel time
            utilities[fac_id] = np.exp(-beta * travel / 60)  # normalize to hours

        # Convert utilities to probabilities (softmax-style normalization)
        total_utility = sum(utilities.values())
        probabilities[zone_id] = {
            fac_id: util / total_utility
            for fac_id, util in utilities.items()
        }

    return probabilities
```

---

## Step 2: Formulate the Optimization Model

*This is the core of Recipe 14.10. We translate the network design problem into a mixed-integer program. Binary variables represent open/close and service offering decisions. Continuous variables represent patient flows. Constraints enforce budget, capacity, minimum volume, and demand satisfaction.*

```python
def formulate_network_model(
    facilities: dict,
    zones: dict,
    service_lines: dict,
    budget: float,
) -> LpProblem:
    """
    Build the mixed-integer programming model for health system network design.

    Decision variables:
    - offer[f][s]: binary, 1 if facility f offers service line s
    - open[f]: binary, 1 if candidate facility f is opened
    - flow[z][f][s]: continuous, patient volume from zone z to facility f for service s

    Objective: maximize net contribution margin (revenue minus fixed costs minus capital amortization)

    Constraints: budget, capacity, demand satisfaction, minimum volume, gravity model consistency
    """
    model = LpProblem("HealthSystemNetworkDesign", LpMaximize)

    facility_ids = list(facilities.keys())
    zone_ids = list(zones.keys())
    service_ids = list(service_lines.keys())

    # --- DECISION VARIABLES ---

    # Binary: does facility f offer service line s?
    offer = {
        f: {s: LpVariable(f"offer_{f}_{s}", cat=LpBinary) for s in service_ids}
        for f in facility_ids
    }

    # Binary: is candidate facility f opened?
    open_fac = {
        f: LpVariable(f"open_{f}", cat=LpBinary)
        for f in facility_ids
        if facilities[f]["type"] == "candidate"
    }

    # Continuous: patient flow from zone z to facility f for service s
    flow = {
        z: {
            f: {s: LpVariable(f"flow_{z}_{f}_{s}", lowBound=0, cat=LpContinuous) for s in service_ids}
            for f in facility_ids
        }
        for z in zone_ids
    }

    # --- PRECOMPUTE CHOICE PROBABILITIES ---
    # These cap how much flow can go from each zone to each facility
    # (patients won't all drive past a closer facility to reach a farther one)
    choice_probs = {
        s: compute_choice_probabilities(zones, facilities, s)
        for s in service_ids
    }

    # --- OBJECTIVE FUNCTION ---
    # Maximize: total revenue - fixed costs - annualized capital costs
    # Capital is amortized over 10 years for this simplified model.

    revenue = lpSum(
        service_lines[s]["revenue_per_case"] * flow[z][f][s]
        for z in zone_ids
        for f in facility_ids
        for s in service_ids
    )

    fixed_costs = lpSum(
        service_lines[s]["fixed_annual_cost"] * offer[f][s]
        for f in facility_ids
        for s in service_ids
    )

    # Capital amortization (10-year straight-line)
    capital_annual = LpVariable("capital_annual", lowBound=0, cat=LpContinuous)

    model += revenue - fixed_costs - capital_annual, "NetContributionMargin"

    # --- CONSTRAINTS ---

    # 1. Budget constraint: total capital spend cannot exceed budget
    capital_expr = []
    for f in facility_ids:
        if facilities[f]["type"] == "candidate":
            capital_expr.append(CAPITAL_COSTS["new_facility_base"] * open_fac[f])
        for s in service_ids:
            if s not in facilities[f]["current_services"]:
                cost_key = f"add_{s}"
                if cost_key in CAPITAL_COSTS:
                    capital_expr.append(CAPITAL_COSTS[cost_key] * offer[f][s])

    model += lpSum(capital_expr) <= budget, "BudgetLimit"
    model += capital_annual == lpSum(capital_expr) / 10, "CapitalAmortization"

    # 2. Capacity constraints: volume at each facility cannot exceed capacity
    for f in facility_ids:
        for s in service_ids:
            model += (
                lpSum(flow[z][f][s] for z in zone_ids) <= CAPACITY_PER_FACILITY[s] * offer[f][s],
                f"Capacity_{f}_{s}"
            )

    # 3. Demand satisfaction: all demand must be assigned
    #    (in this simplified model, we allow "leakage" by not requiring 100% capture)
    for z in zone_ids:
        for s in service_ids:
            model += (
                lpSum(flow[z][f][s] for f in facility_ids) <= zones[z]["demand"][s],
                f"DemandCap_{z}_{s}"
            )

    # 4. Gravity model consistency: flow cannot exceed what the choice model predicts
    #    Patients won't all choose a distant facility over a nearby one.
    for z in zone_ids:
        for f in facility_ids:
            for s in service_ids:
                max_flow = zones[z]["demand"][s] * choice_probs[s][z][f]
                model += (
                    flow[z][f][s] <= max_flow,
                    f"GravityBound_{z}_{f}_{s}"
                )

    # 5. Minimum volume: if you offer a service, you must hit minimum volume
    #    (quality and accreditation requirement)
    for f in facility_ids:
        for s in service_ids:
            model += (
                lpSum(flow[z][f][s] for z in zone_ids) >= service_lines[s]["min_volume_threshold"] * offer[f][s],
                f"MinVolume_{f}_{s}"
            )

    # 6. Candidate facilities: can only offer services if the facility is opened
    for f in facility_ids:
        if facilities[f]["type"] == "candidate":
            for s in service_ids:
                model += (
                    offer[f][s] <= open_fac[f],
                    f"MustBeOpen_{f}_{s}"
                )

    # 7. Existing services: facilities already offering a service must continue
    #    (closing an existing service is a separate, politically charged decision)
    for f in facility_ids:
        for s in facilities[f]["current_services"]:
            model += offer[f][s] == 1, f"KeepExisting_{f}_{s}"

    return model, offer, open_fac, flow
```

---

## Step 3: Solve and Extract Results

*Once the model is formulated, we hand it to the solver. PuLP's interface makes this a single function call. The interesting part is interpreting the solution: which facilities should offer which services, and how do patient flows redistribute?*

```python
def solve_model(model: LpProblem) -> dict:
    """
    Invoke the MIP solver and return solve metadata.

    CBC (the default PuLP solver) uses branch-and-bound with cutting planes.
    For this small problem it solves in under a second. For production-scale
    problems (50K+ variables), you'd use Gurobi or HiGHS and set a time limit.
    """
    solver = PULP_CBC_CMD(
        msg=1,           # show solver output (set to 0 for silent)
        timeLimit=300,   # 5-minute time limit (generous for this size)
        gapRel=0.02,     # accept solutions within 2% of proven optimal
    )

    model.solve(solver)

    return {
        "status": model.status,
        "status_text": model.sol_status[model.status] if hasattr(model, 'sol_status') else str(model.status),
        "objective_value": value(model.objective) if model.status == 1 else None,
    }


def extract_solution(
    facilities: dict,
    zones: dict,
    service_lines: dict,
    offer: dict,
    open_fac: dict,
    flow: dict,
) -> dict:
    """
    Pull the optimal decisions out of the solved model variables.

    This is where the math becomes actionable recommendations:
    which facilities to open, which services to add, and how patients
    are expected to flow through the network.
    """
    facility_ids = list(facilities.keys())
    zone_ids = list(zones.keys())
    service_ids = list(service_lines.keys())

    # Extract facility opening decisions
    new_facilities = []
    for f in facility_ids:
        if facilities[f]["type"] == "candidate" and value(open_fac[f]) > 0.5:
            new_facilities.append({"facility": f, "name": facilities[f]["name"]})

    # Extract service line decisions
    service_decisions = []
    for f in facility_ids:
        for s in service_ids:
            if value(offer[f][s]) > 0.5 and s not in facilities[f]["current_services"]:
                service_decisions.append({
                    "facility": f,
                    "facility_name": facilities[f]["name"],
                    "service_line": s,
                    "action": "ADD_SERVICE_LINE",
                })

    # Extract patient flow summary
    flow_summary = {}
    for f in facility_ids:
        for s in service_ids:
            total_flow = sum(value(flow[z][f][s]) for z in zone_ids)
            if total_flow > 1:  # ignore negligible flows
                key = f"{f}_{s}"
                flow_summary[key] = {
                    "facility": facilities[f]["name"],
                    "service_line": s,
                    "projected_annual_volume": round(total_flow),
                    "capacity_utilization": round(total_flow / CAPACITY_PER_FACILITY[s] * 100, 1),
                }

    # Compute total capital required
    total_capital = 0
    for f in facility_ids:
        if facilities[f]["type"] == "candidate" and value(open_fac[f]) > 0.5:
            total_capital += CAPITAL_COSTS["new_facility_base"]
        for s in service_ids:
            if value(offer[f][s]) > 0.5 and s not in facilities[f]["current_services"]:
                cost_key = f"add_{s}"
                if cost_key in CAPITAL_COSTS:
                    total_capital += CAPITAL_COSTS[cost_key]

    return {
        "new_facilities_opened": new_facilities,
        "service_line_additions": service_decisions,
        "patient_flow_summary": flow_summary,
        "total_capital_required": total_capital,
        "budget_remaining": TOTAL_BUDGET - total_capital,
    }
```

---

## Step 4: Scenario Analysis

*The main recipe emphasizes that no single demand forecast is reliable. This step runs the optimization under multiple demand scenarios and identifies robust versus contingent decisions.*

```python
def create_scenarios(base_zones: dict) -> dict:
    """
    Define demand scenarios for sensitivity analysis.

    Each scenario modifies the base demand by applying multipliers.
    In production, these come from demographic models and market analysis.
    """
    scenarios = {
        "base_case": {s: 1.0 for s in SERVICE_LINES},
        "high_growth": {s: 1.2 for s in SERVICE_LINES},
        "low_growth": {s: 0.85 for s in SERVICE_LINES},
        "cardiology_surge": {"primary_care": 1.0, "cardiology": 1.4, "orthopedics": 1.0},
        "competitor_entry": {s: 0.75 for s in SERVICE_LINES},  # lose 25% market share
    }
    return scenarios


def run_scenario(
    facilities: dict,
    base_zones: dict,
    service_lines: dict,
    budget: float,
    demand_multipliers: dict,
) -> dict:
    """
    Run the optimization under a single demand scenario.

    Applies demand multipliers to the base zones, formulates, solves,
    and returns the solution.
    """
    # Apply demand multipliers to create scenario-specific zones
    scenario_zones = {}
    for z_id, z_data in base_zones.items():
        scenario_zones[z_id] = {
            "lat": z_data["lat"],
            "lon": z_data["lon"],
            "demand": {
                s: int(z_data["demand"][s] * demand_multipliers.get(s, 1.0))
                for s in z_data["demand"]
            },
        }

    model, offer, open_fac, flow = formulate_network_model(
        facilities, scenario_zones, service_lines, budget
    )

    solve_result = solve_model(model)

    if solve_result["status"] != 1:
        return {"status": "infeasible", "solve_result": solve_result}

    solution = extract_solution(
        facilities, scenario_zones, service_lines, offer, open_fac, flow
    )
    solution["objective_value"] = solve_result["objective_value"]
    return solution


def identify_robust_decisions(scenario_results: dict) -> dict:
    """
    Compare solutions across scenarios to find decisions that are
    consistent (robust) versus those that change (contingent).

    A robust decision appears in every scenario's optimal solution.
    A contingent decision only appears in some scenarios.
    """
    # Collect all service line additions across scenarios
    all_additions = {}
    for scenario_name, result in scenario_results.items():
        if result.get("status") == "infeasible":
            continue
        for addition in result.get("service_line_additions", []):
            key = f"{addition['facility']}_{addition['service_line']}"
            if key not in all_additions:
                all_additions[key] = {"decision": addition, "scenarios": []}
            all_additions[key]["scenarios"].append(scenario_name)

    feasible_count = sum(
        1 for r in scenario_results.values() if r.get("status") != "infeasible"
    )

    robust = []
    contingent = []
    for key, data in all_additions.items():
        if len(data["scenarios"]) == feasible_count:
            robust.append(data["decision"])
        else:
            contingent.append({
                **data["decision"],
                "appears_in_scenarios": data["scenarios"],
                "frequency": f"{len(data['scenarios'])}/{feasible_count}",
            })

    return {"robust_decisions": robust, "contingent_decisions": contingent}
```

---

## Step 5: Store Results to S3

*The optimization results need to land somewhere durable for the executive dashboard (QuickSight) to pick up. S3 is the natural landing zone.*

```python
import boto3
from botocore.config import Config
import datetime
from datetime import timezone

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

RESULTS_BUCKET = "health-system-network-optimization"
# Replace with your actual bucket name. Must have SSE-KMS encryption enabled.


def store_optimization_results(run_id: str, results: dict) -> str:
    """
    Write optimization results to S3 as JSON for downstream consumption.

    The QuickSight dashboard reads from this location. Step Functions
    triggers a SPICE refresh after this write completes.
    """
    key = f"optimization-runs/{run_id}/results.json"

    output = {
        "run_id": run_id,
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "results": results,
    }

    s3_client.put_object(
        Bucket=RESULTS_BUCKET,
        Key=key,
        Body=json.dumps(output, indent=2, default=str),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        # In production, specify your KMS key ID with SSEKMSKeyId parameter
    )

    logger.info("Results stored to s3://%s/%s", RESULTS_BUCKET, key)
    return f"s3://{RESULTS_BUCKET}/{key}"
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. This is what your Step Functions workflow would invoke via a SageMaker Processing Job.

```python
def run_network_design_optimization() -> dict:
    """
    Execute the full health system network design optimization pipeline.

    Steps:
    1. Compute travel times and choice probabilities
    2. Formulate the base optimization model
    3. Solve under multiple demand scenarios
    4. Identify robust vs. contingent decisions
    5. Store results for dashboard consumption
    """
    logger.info("=== Health System Network Design Optimization ===")

    # Step 1-2: Formulate and solve base case
    logger.info("Step 1: Formulating base case model...")
    model, offer, open_fac, flow = formulate_network_model(
        FACILITIES, DEMAND_ZONES, SERVICE_LINES, TOTAL_BUDGET
    )
    logger.info("  Model has %d variables, %d constraints",
                model.numVariables(), model.numConstraints())

    logger.info("Step 2: Solving base case...")
    base_result = solve_model(model)
    logger.info("  Solver status: %s", base_result)

    if base_result["status"] != 1:
        logger.error("Base case infeasible or unbounded. Check constraints.")
        return {"error": "Base case did not solve optimally", "details": base_result}

    base_solution = extract_solution(
        FACILITIES, DEMAND_ZONES, SERVICE_LINES, offer, open_fac, flow
    )
    base_solution["objective_value"] = base_result["objective_value"]
    logger.info("  Base case objective: $%s annual net margin",
                f"{base_result['objective_value']:,.0f}")

    # Step 3: Run scenario analysis
    logger.info("Step 3: Running scenario analysis...")
    scenarios = create_scenarios(DEMAND_ZONES)
    scenario_results = {}

    for scenario_name, multipliers in scenarios.items():
        logger.info("  Solving scenario: %s", scenario_name)
        result = run_scenario(
            FACILITIES, DEMAND_ZONES, SERVICE_LINES, TOTAL_BUDGET, multipliers
        )
        scenario_results[scenario_name] = result
        obj = result.get("objective_value", "N/A")
        if obj != "N/A":
            logger.info("    Objective: $%s", f"{obj:,.0f}")

    # Step 4: Identify robust decisions
    logger.info("Step 4: Identifying robust vs. contingent decisions...")
    robustness = identify_robust_decisions(scenario_results)
    logger.info("  Robust decisions: %d", len(robustness["robust_decisions"]))
    logger.info("  Contingent decisions: %d", len(robustness["contingent_decisions"]))

    # Assemble final output
    final_output = {
        "base_case_solution": base_solution,
        "scenario_results": {
            name: {
                "objective_value": r.get("objective_value"),
                "new_facilities": r.get("new_facilities_opened", []),
                "service_additions": r.get("service_line_additions", []),
                "capital_required": r.get("total_capital_required", 0),
            }
            for name, r in scenario_results.items()
            if r.get("status") != "infeasible"
        },
        "robustness_analysis": robustness,
    }

    # Step 5: Store results (uncomment when you have the S3 bucket configured)
    # run_id = f"net-design-{datetime.datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    # store_optimization_results(run_id, final_output)

    logger.info("=== Optimization Complete ===")
    return final_output


# Run the pipeline
if __name__ == "__main__":
    results = run_network_design_optimization()

    print("\n" + "=" * 60)
    print("OPTIMIZATION RESULTS SUMMARY")
    print("=" * 60)

    base = results["base_case_solution"]
    print(f"\nBase Case Annual Net Margin: ${base['objective_value']:,.0f}")
    print(f"Total Capital Required: ${base['total_capital_required']:,.0f}")
    print(f"Budget Remaining: ${base['budget_remaining']:,.0f}")

    if base["new_facilities_opened"]:
        print("\nNew Facilities to Open:")
        for fac in base["new_facilities_opened"]:
            print(f"  - {fac['name']}")

    if base["service_line_additions"]:
        print("\nService Line Additions:")
        for add in base["service_line_additions"]:
            print(f"  - {add['facility_name']}: add {add['service_line']}")

    print("\nPatient Flow Summary:")
    for key, flow_data in base["patient_flow_summary"].items():
        print(f"  {flow_data['facility']} / {flow_data['service_line']}: "
              f"{flow_data['projected_annual_volume']} cases "
              f"({flow_data['capacity_utilization']}% utilization)")

    robust = results["robustness_analysis"]
    print(f"\nRobust Decisions (same in all scenarios): {len(robust['robust_decisions'])}")
    for d in robust["robust_decisions"]:
        print(f"  - {d['facility_name']}: add {d['service_line']}")

    print(f"\nContingent Decisions (scenario-dependent): {len(robust['contingent_decisions'])}")
    for d in robust["contingent_decisions"]:
        print(f"  - {d['facility_name']}: add {d['service_line']} "
              f"(appears in {d['frequency']} scenarios)")
```

---

## The Gap Between This and Production

This example runs. It formulates a real MIP, solves it, and produces actionable network design recommendations. But there's a significant distance between this teaching example and something you'd use to inform $200M capital decisions. Here's where that gap lives:

**Demand model calibration.** The synthetic demand numbers here are made up. A real system needs patient origin analysis from your EHR (where do patients come from?), state discharge databases for total market sizing, and demographic projections from census data. Budget 3-6 months just for demand model development and validation.

**Gravity model estimation.** We used fixed distance-decay parameters. In production, you'd estimate these from historical patient flow data using maximum likelihood (conditional logit model). The parameters vary by service line, payer, and patient demographics. A miscalibrated gravity model produces confidently wrong recommendations.

**Solver selection.** CBC works for this toy problem. For a real health system (50+ facilities, 20+ service lines, 2000+ demand zones), you need Gurobi or CPLEX. The solve time difference is 10x-100x. Budget $10K-$50K/year for a commercial solver license. It's trivial relative to the capital decisions being informed.

**Stochastic optimization.** Our scenario analysis runs deterministic optimizations under different assumptions and compares results. True stochastic programming optimizes expected performance across probability-weighted scenarios simultaneously. This produces solutions that are explicitly hedged against uncertainty, but requires specialized formulation techniques and longer solve times.

**Service line dependencies.** We didn't model dependencies (e.g., you can't offer cardiac surgery without a cardiac ICU, you can't offer orthopedic surgery without post-acute rehab access). These are critical constraints that prevent the optimizer from recommending infeasible configurations.

**Multi-period staging.** This model makes all decisions simultaneously. Real capital planning is staged: build X in year 1, expand Y in year 3. A multi-period formulation adds time-indexed variables and linking constraints. Significantly more complex but captures the reality that early decisions constrain later ones.

**Error handling and retries.** No try/except blocks, no handling of solver timeouts, no graceful degradation if the model is infeasible. Production code needs all of this, plus structured logging of solver progress for debugging.

**IAM least-privilege.** The S3 write uses whatever credentials are in the environment. Production uses a role scoped to exactly `s3:PutObject` on the specific results bucket, `sagemaker:CreateProcessingJob` for solver execution, and nothing else.

**VPC and encryption.** Patient-level data (even aggregated utilization data) is PHI-adjacent. Production runs in a VPC with private subnets, VPC endpoints for S3, and KMS customer-managed keys for all data at rest.

**Model validation.** Before trusting any recommendation, you need to validate that the model reproduces current utilization patterns. If it can't explain today, it has no business predicting tomorrow. Backtest against historical facility openings and closings.

**Stakeholder interface.** Executives don't read JSON. The QuickSight dashboard needs interactive maps showing proposed network configurations, side-by-side scenario comparisons, and sensitivity sliders that let decision-makers explore "what if we constrain this facility to stay open?" The dashboard is half the work.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 14.10](chapter14.10-health-system-network-design) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
