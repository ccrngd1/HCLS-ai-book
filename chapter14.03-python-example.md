# Recipe 14.3: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the inventory reorder optimization from Recipe 14.3. It demonstrates the core concepts (problem formulation, constraint definition, solver invocation, solution interpretation) using an open-source MIP solver. It is not production-ready. The item catalog is tiny, the demand model is static, and there's no ERP integration. Think of it as the whiteboard sketch that helps you understand the shape of the real system. A starting point, not a destination.
>
> The main recipe uses ECS Fargate for the solver and SageMaker for demand forecasting. This example runs everything locally with the HiGHS solver (via the `highspy` Python bindings) and hardcoded demand parameters. The optimization math is identical; the infrastructure is stripped away so you can focus on the model.

---

## Setup

You'll need the optimization solver and AWS SDK installed:

```bash
pip install boto3 highspy
```

`highspy` is the Python interface to HiGHS, an open-source linear and mixed-integer programming solver. It's fast, well-maintained, and handles the problem sizes typical of hospital inventory optimization (thousands of items) without a commercial license.

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `dynamodb:PutItem`
- `dynamodb:GetItem`
- `dynamodb:Query`
- `s3:PutObject`
- `s3:GetObject`

For the full pipeline (with demand forecasting), you'd also need `sagemaker:InvokeEndpoint`, but this example uses hardcoded demand parameters to keep the focus on the optimization itself.

---

## Configuration and Constants

```python
import math
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
import highspy
from botocore.config import Config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Service level targets by criticality tier.
# These represent the probability of NOT stocking out during a replenishment cycle.
# Critical items (crash cart meds, blood products): 99.5% fill rate.
# Essential items (surgical supplies, common meds): 98%.
# Standard items (office supplies, non-urgent consumables): 95%.
SERVICE_LEVELS = {
    "critical": 0.995,
    "essential": 0.98,
    "standard": 0.95,
}

# Z-scores from the standard normal distribution corresponding to each service level.
# safety_stock = z * standard_deviation_of_demand_during_lead_time
Z_SCORES = {
    0.995: 2.576,
    0.98: 2.054,
    0.95: 1.645,
}

# Annual holding cost rate: percentage of unit cost per year to hold one unit in inventory.
# 25% is typical for healthcare (capital cost + storage + insurance + obsolescence).
ANNUAL_HOLDING_RATE = 0.25

# Fixed cost per purchase order (administrative processing, receiving, etc.).
ORDERING_COST_PER_ORDER = 50.00

# Solver time limit in seconds. For large catalogs, the solver may not prove
# optimality within this window but will return the best solution found.
SOLVER_TIME_LIMIT_SECONDS = 300

# Policy change threshold: flag items where the reorder point changes by more than this ratio.
CHANGE_THRESHOLD = 2.0

# DynamoDB table name for storing reorder policies.
POLICIES_TABLE_NAME = "reorder-policies"
```

---

## Step 1: Build the Item Catalog (Simulated Inventory Snapshot)

*In production, this data comes from your ERP or materials management system via API. Here we hardcode a representative set of items spanning different criticality tiers, lead times, and shelf lives to demonstrate how the optimizer handles heterogeneous constraints.*

```python
def build_sample_catalog() -> list[dict]:
    """
    Build a sample item catalog representing a hospital supply subset.

    Each item has the parameters the optimizer needs:
    - demand characteristics (mean daily demand, standard deviation)
    - supply characteristics (lead time, lead time variability)
    - cost parameters (unit cost, minimum order quantity)
    - constraints (criticality tier, shelf life, storage volume)

    In production, these come from your ERP snapshot + demand forecasting model.
    """
    catalog = [
        {
            "item_id": "SKU-04821-CATH-KIT",
            "description": "Central Line Catheter Kit, 7Fr Triple Lumen",
            "daily_demand_mean": 6.0,
            "daily_demand_stddev": 2.5,
            "lead_time_days": 3.0,
            "lead_time_stddev": 1.0,
            "unit_cost": 45.00,
            "min_order_qty": 10,
            "criticality": "critical",
            "shelf_life_days": None,  # non-perishable
            "storage_volume_cuft": 0.3,
        },
        {
            "item_id": "SKU-11002-IV-NS",
            "description": "Normal Saline 1000mL IV Bag",
            "daily_demand_mean": 80.0,
            "daily_demand_stddev": 20.0,
            "lead_time_days": 2.0,
            "lead_time_stddev": 0.5,
            "unit_cost": 3.50,
            "min_order_qty": 48,
            "criticality": "critical",
            "shelf_life_days": 730,  # 2 years
            "storage_volume_cuft": 0.08,
        },
        {
            "item_id": "SKU-07330-SURG-GLOVE",
            "description": "Sterile Surgical Gloves, Size 7.5 (box/50)",
            "daily_demand_mean": 12.0,
            "daily_demand_stddev": 4.0,
            "lead_time_days": 5.0,
            "lead_time_stddev": 2.0,
            "unit_cost": 28.00,
            "min_order_qty": 5,
            "criticality": "essential",
            "shelf_life_days": 1825,  # 5 years
            "storage_volume_cuft": 0.5,
        },
        {
            "item_id": "SKU-09100-REAGENT-A",
            "description": "Chemistry Analyzer Reagent Pack A",
            "daily_demand_mean": 2.0,
            "daily_demand_stddev": 0.8,
            "lead_time_days": 7.0,
            "lead_time_stddev": 3.0,
            "unit_cost": 120.00,
            "min_order_qty": 2,
            "criticality": "essential",
            "shelf_life_days": 90,  # short shelf life
            "storage_volume_cuft": 0.4,
        },
        {
            "item_id": "SKU-15500-PAPER-TOWEL",
            "description": "Paper Towel Roll, Industrial (case/12)",
            "daily_demand_mean": 5.0,
            "daily_demand_stddev": 1.5,
            "lead_time_days": 4.0,
            "lead_time_stddev": 1.0,
            "unit_cost": 8.00,
            "min_order_qty": 10,
            "criticality": "standard",
            "shelf_life_days": None,
            "storage_volume_cuft": 1.2,
        },
    ]
    return catalog
```

---

## Step 2: Estimate Optimization Parameters

*This step transforms raw item data into the specific parameters the MIP solver needs. The key calculation is safety stock: how much buffer to hold based on demand uncertainty, lead time uncertainty, and the service level target for each item's criticality tier.*

```python
def estimate_parameters(catalog: list[dict]) -> list[dict]:
    """
    Calculate solver-ready parameters for each item.

    The critical formula here is safety stock:
        safety_stock = z * sqrt(LT * sigma_d^2 + d^2 * sigma_LT^2)

    Where:
        z = z-score for the target service level
        LT = average lead time (days)
        sigma_d = standard deviation of daily demand
        d = mean daily demand
        sigma_LT = standard deviation of lead time (days)

    This accounts for BOTH demand variability and lead time variability.
    If you only use demand variability (ignoring lead time uncertainty),
    you'll underestimate safety stock for items with unreliable suppliers.
    """
    parameters = []

    for item in catalog:
        service_level = SERVICE_LEVELS[item["criticality"]]
        z = Z_SCORES[service_level]

        # Demand during lead time: expected consumption while waiting for delivery.
        demand_during_lt_mean = item["daily_demand_mean"] * item["lead_time_days"]

        # Combined uncertainty: demand variability + lead time variability.
        # This is the standard formula for the standard deviation of demand
        # during a stochastic lead time with stochastic demand.
        demand_during_lt_stddev = math.sqrt(
            item["lead_time_days"] * (item["daily_demand_stddev"] ** 2)
            + (item["daily_demand_mean"] ** 2) * (item["lead_time_stddev"] ** 2)
        )

        safety_stock = z * demand_during_lt_stddev

        # Daily holding cost per unit.
        daily_holding_cost = item["unit_cost"] * ANNUAL_HOLDING_RATE / 365.0

        # Annual demand estimate (for ordering cost calculation).
        annual_demand = item["daily_demand_mean"] * 365.0

        params = {
            "item_id": item["item_id"],
            "description": item["description"],
            "demand_during_lt_mean": demand_during_lt_mean,
            "demand_during_lt_stddev": demand_during_lt_stddev,
            "safety_stock": safety_stock,
            "daily_holding_cost": daily_holding_cost,
            "annual_demand": annual_demand,
            "unit_cost": item["unit_cost"],
            "min_order_qty": item["min_order_qty"],
            "shelf_life_days": item["shelf_life_days"],
            "daily_demand_mean": item["daily_demand_mean"],
            "storage_volume_cuft": item["storage_volume_cuft"],
            "criticality": item["criticality"],
            "service_level": service_level,
        }
        parameters.append(params)

        logger.info(
            "  %s: demand_during_LT=%.1f, safety_stock=%.1f, service_level=%.3f",
            item["item_id"],
            demand_during_lt_mean,
            safety_stock,
            service_level,
        )

    return parameters
```

---

## Step 3: Formulate and Solve the MIP

*This is the core of the recipe. We build a Mixed-Integer Program with HiGHS: define decision variables (reorder point and order quantity per item), set the objective (minimize total cost), and add constraints (budget, storage, shelf life). The solver finds the globally optimal solution (or the best it can within the time limit).*

```python
def solve_inventory_optimization(
    parameters: list[dict],
    total_budget: float = 500_000.0,
    total_storage_cuft: float = 2000.0,
) -> dict:
    """
    Solve the constrained inventory optimization using HiGHS MIP solver.

    Decision variables per item:
        r_i = reorder point (integer, units)
        Q_i = order quantity (integer, units)

    Objective: minimize sum over all items of:
        holding_cost_i = (Q_i / 2 + safety_stock_i) * daily_holding_cost_i * 365
        ordering_cost_i = (annual_demand_i / Q_i) * ordering_cost_per_order

    Constraints:
        1. Budget: sum(r_i * unit_cost_i) <= total_budget
        2. Storage: sum(r_i * storage_volume_i) <= total_storage_cuft
        3. Shelf life: Q_i <= daily_demand_i * shelf_life_days * 0.8 (perishables only)
        4. Minimum order: Q_i >= min_order_qty_i
        5. Minimum reorder point: r_i >= safety_stock_i

    Note on linearization: The ordering cost term (annual_demand / Q) is non-linear.
    For this example, we approximate it by fixing Q at the EOQ estimate and only
    optimizing reorder points under the shared constraints. This is a common
    practical simplification. A full non-linear formulation would use piecewise
    linearization or a non-linear solver.

    Args:
        parameters: list of item parameter dicts from estimate_parameters
        total_budget: maximum total inventory value in dollars
        total_storage_cuft: maximum storage capacity in cubic feet

    Returns:
        Dict with solver status, objective value, and per-item policies.
    """
    n = len(parameters)

    # Pre-compute EOQ for each item to use as the order quantity.
    # EOQ = sqrt(2 * annual_demand * ordering_cost / (daily_holding_cost * 365))
    # We then enforce min_order_qty and shelf life constraints on top.
    eoq_values = []
    for item in parameters:
        annual_holding = item["daily_holding_cost"] * 365.0
        if annual_holding > 0:
            eoq = math.sqrt(
                2.0 * item["annual_demand"] * ORDERING_COST_PER_ORDER / annual_holding
            )
        else:
            eoq = float(item["min_order_qty"])

        # Enforce minimum order quantity.
        eoq = max(eoq, item["min_order_qty"])

        # Enforce shelf life constraint for perishable items.
        if item["shelf_life_days"] is not None:
            max_before_expiry = item["daily_demand_mean"] * item["shelf_life_days"] * 0.8
            eoq = min(eoq, max_before_expiry)

        eoq_values.append(int(math.ceil(eoq)))

    # Build the HiGHS model.
    # We optimize reorder points (r_i) subject to budget and storage constraints.
    # The reorder point must be at least safety_stock (to maintain service level).
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)  # suppress solver output
    h.setOptionValue("time_limit", float(SOLVER_TIME_LIMIT_SECONDS))

    # Add one integer variable per item: the reorder point.
    # Lower bound = ceiling of safety stock (minimum to maintain service level).
    # Upper bound = generous upper limit (10x safety stock; solver will find optimal).
    col_indices = []
    for i, item in enumerate(parameters):
        lb = int(math.ceil(item["safety_stock"]))
        ub = max(lb * 10, 100)  # generous upper bound; floor of 100 prevents zero-range for low-variability items
        # Objective coefficient: holding cost for the reorder point portion.
        # Total holding cost = (Q/2 + r) * daily_holding * 365, but Q is fixed,
        # so the variable part is r * daily_holding * 365.
        obj_coeff = item["daily_holding_cost"] * 365.0

        h.addVar(lb, ub)
        col_indices.append(i)

    # Set variable types to integer.
    for i in range(n):
        h.changeColIntegrality(i, highspy.HighsIntegrality.kInteger)

    # Set objective (minimize).
    h.changeObjectiveSense(highspy.ObjSense.kMinimize)
    for i, item in enumerate(parameters):
        obj_coeff = item["daily_holding_cost"] * 365.0
        h.changeColCost(i, obj_coeff)

    # Constraint 1: Budget. sum(r_i * unit_cost_i) <= total_budget.
    budget_indices = list(range(n))
    budget_coeffs = [item["unit_cost"] for item in parameters]
    h.addRow(
        -highspy.kHighsInf,  # no lower bound
        total_budget,
        len(budget_indices),
        budget_indices,
        budget_coeffs,
    )

    # Constraint 2: Storage. sum(r_i * storage_volume_i) <= total_storage_cuft.
    storage_indices = list(range(n))
    storage_coeffs = [item["storage_volume_cuft"] for item in parameters]
    h.addRow(
        -highspy.kHighsInf,
        total_storage_cuft,
        len(storage_indices),
        storage_indices,
        storage_coeffs,
    )

    # Solve.
    h.run()

    status = h.getModelStatus()

    if status == highspy.HighsModelStatus.kInfeasible:
        logger.warning("Model is infeasible. Constraints are too tight.")
        return {"status": "infeasible", "policies": []}

    # Guard against non-solution states (solver errors, unbounded, etc.).
    if status not in (
        highspy.HighsModelStatus.kOptimal,
        highspy.HighsModelStatus.kObjectiveBound,
        highspy.HighsModelStatus.kTimeLimit,
    ):
        logger.warning("Solver failed: status=%s", status)
        return {"status": "error", "solver_status": str(status), "policies": []}

    # Extract solution.
    solution = h.getSolution()
    col_values = solution.col_value

    policies = []
    total_holding_cost = 0.0
    total_ordering_cost = 0.0

    for i, item in enumerate(parameters):
        reorder_point = int(round(col_values[i]))
        order_quantity = eoq_values[i]

        # Calculate costs for reporting.
        avg_inventory = order_quantity / 2.0 + item["safety_stock"]
        annual_holding = avg_inventory * item["daily_holding_cost"] * 365.0
        annual_ordering = (
            (item["annual_demand"] / order_quantity) * ORDERING_COST_PER_ORDER
            if order_quantity > 0
            else 0.0
        )

        total_holding_cost += annual_holding
        total_ordering_cost += annual_ordering

        policy = {
            "item_id": item["item_id"],
            "description": item["description"],
            "reorder_point": reorder_point,
            "order_quantity": order_quantity,
            "safety_stock": int(math.ceil(item["safety_stock"])),
            "service_level": item["service_level"],
            "criticality": item["criticality"],
            "expected_annual_holding_cost": round(annual_holding, 2),
            "expected_annual_ordering_cost": round(annual_ordering, 2),
        }
        policies.append(policy)

    solver_status = "optimal" if status == highspy.HighsModelStatus.kOptimal else "time_limit"

    result = {
        "status": solver_status,
        "total_annual_cost": round(total_holding_cost + total_ordering_cost, 2),
        "total_holding_cost": round(total_holding_cost, 2),
        "total_ordering_cost": round(total_ordering_cost, 2),
        "item_count": n,
        "policies": policies,
    }

    logger.info(
        "Solver finished: status=%s, total_cost=$%.2f",
        solver_status,
        result["total_annual_cost"],
    )
    return result
```

---

## Step 4: Validate Policies Against Current State

*Before pushing new policies to the operational store, compare them against existing policies and flag dramatic changes. A reorder point that doubled overnight usually means a data issue, not a genuine demand shift.*

```python
def validate_policies(
    new_policies: list[dict],
    current_policies: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Validate new policies against current ones and flag dramatic changes.

    Args:
        new_policies: list of policy dicts from the solver
        current_policies: dict of item_id -> current policy (None if first run)

    Returns:
        Tuple of (validated_policies, flagged_for_review).
        Flagged items still get the new policy; the flag is informational.
    """
    if current_policies is None:
        current_policies = {}

    validated = []
    flagged = []

    for policy in new_policies:
        item_id = policy["item_id"]
        current = current_policies.get(item_id)

        if current is not None:
            old_rp = current.get("reorder_point", 0)
            new_rp = policy["reorder_point"]

            if old_rp > 0:
                change_ratio = new_rp / old_rp
                if change_ratio > CHANGE_THRESHOLD or change_ratio < (1.0 / CHANGE_THRESHOLD):
                    flagged.append({
                        "item_id": item_id,
                        "old_reorder_point": old_rp,
                        "new_reorder_point": new_rp,
                        "change_ratio": round(change_ratio, 2),
                        "reason": "reorder point changed by more than 100%",
                    })

        validated.append(policy)

    if flagged:
        logger.warning("  %d item(s) flagged for review due to large policy changes", len(flagged))
    return validated, flagged
```

---

## Step 5: Store Policies in DynamoDB

*The policy store is the bridge between the batch optimization (runs nightly) and the real-time execution engine (checks inventory levels continuously). DynamoDB gives us low-latency point lookups by item ID.*

```python
def store_policies(policies: list[dict], solver_run_id: str) -> int:
    """
    Write validated policies to DynamoDB with version tracking.

    Each policy is stored with the solver run ID so you can trace any
    operational decision back to the specific optimization run that produced it.

    Args:
        policies: validated policy list from validate_policies
        solver_run_id: unique identifier for this optimization run

    Returns:
        Number of policies stored.
    """
    table = dynamodb.Table(POLICIES_TABLE_NAME)
    timestamp = datetime.datetime.now(timezone.utc).isoformat()

    for policy in policies:
        item = {
            "item_id": policy["item_id"],
            "version": timestamp,
            "reorder_point": policy["reorder_point"],
            "order_quantity": policy["order_quantity"],
            "safety_stock": policy["safety_stock"],
            "service_level": Decimal(str(policy["service_level"])),
            "criticality": policy["criticality"],
            "expected_annual_holding_cost": Decimal(str(policy["expected_annual_holding_cost"])),
            "expected_annual_ordering_cost": Decimal(str(policy["expected_annual_ordering_cost"])),
            "solver_run_id": solver_run_id,
            "status": "active",
        }
        table.put_item(Item=item)

    logger.info("  Stored %d policies to DynamoDB", len(policies))
    return len(policies)
```

---

## Step 6: Execute Reorder Decisions

*The execution engine is deliberately simple. All the intelligence lives in the policy calculation. This function just compares current inventory against the reorder point and generates an order if needed.*

```python
def check_and_reorder(
    item_id: str,
    current_on_hand: int,
    current_on_order: int,
    policy: dict,
) -> dict:
    """
    Check whether an item needs reordering based on its active policy.

    Effective inventory = on_hand + on_order. If this drops to or below
    the reorder point, generate a purchase order for the policy's order quantity.

    For critical items that have dropped below safety stock, escalate to urgent.

    Args:
        item_id: SKU identifier
        current_on_hand: units physically in stock
        current_on_order: units ordered but not yet received
        policy: active policy dict for this item

    Returns:
        Dict describing the action taken (order_placed or none).
    """
    effective_inventory = current_on_hand + current_on_order

    if effective_inventory <= policy["reorder_point"]:
        priority = "standard"

        # Escalate if we're below safety stock on a critical item.
        if current_on_hand < policy["safety_stock"] and policy["service_level"] >= 0.99:
            priority = "urgent"

        order = {
            "action": "order_placed",
            "item_id": item_id,
            "quantity": policy["order_quantity"],
            "priority": priority,
            "triggered_by": "automated_reorder",
            "effective_inventory_at_trigger": effective_inventory,
            "reorder_point": policy["reorder_point"],
        }
        logger.info(
            "  ORDER: %s qty=%d priority=%s (effective_inv=%d <= reorder_point=%d)",
            item_id,
            policy["order_quantity"],
            priority,
            effective_inventory,
            policy["reorder_point"],
        )
        return order

    return {
        "action": "none",
        "item_id": item_id,
        "reason": f"effective_inventory ({effective_inventory}) > reorder_point ({policy['reorder_point']})",
    }
```

---

## Putting It All Together

```python
def run_optimization_pipeline() -> dict:
    """
    Run the full inventory reorder optimization pipeline.

    Steps:
      1. Build item catalog (simulated ERP snapshot)
      2. Estimate optimization parameters (safety stock, holding costs)
      3. Solve the constrained MIP
      4. Validate policies
      5. Store to DynamoDB (commented out for local testing)
      6. Demonstrate execution logic with sample inventory levels

    Returns:
        The solver result with policies and cost breakdown.
    """
    solver_run_id = f"opt-{datetime.datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')}"
    print(f"=== Inventory Reorder Optimization Run: {solver_run_id} ===\n")

    # Step 1: Get item catalog.
    print("Step 1: Building item catalog...")
    catalog = build_sample_catalog()
    print(f"  {len(catalog)} items in catalog\n")

    # Step 2: Estimate parameters.
    print("Step 2: Estimating optimization parameters...")
    parameters = estimate_parameters(catalog)
    print()

    # Step 3: Solve.
    print("Step 3: Solving constrained optimization...")
    result = solve_inventory_optimization(
        parameters,
        total_budget=200_000.0,   # $200K max inventory value
        total_storage_cuft=500.0,  # 500 cubic feet storage
    )
    print(f"  Status: {result['status']}")
    print(f"  Total annual cost: ${result['total_annual_cost']:,.2f}")
    print(f"    Holding: ${result['total_holding_cost']:,.2f}")
    print(f"    Ordering: ${result['total_ordering_cost']:,.2f}")
    print()

    # Step 4: Validate.
    print("Step 4: Validating policies...")
    validated, flagged = validate_policies(result["policies"], current_policies=None)
    print(f"  {len(validated)} validated, {len(flagged)} flagged\n")

    # Step 5: Store (uncomment for real DynamoDB writes).
    # print("Step 5: Storing policies to DynamoDB...")
    # store_policies(validated, solver_run_id)
    print("Step 5: [Skipped] Would store policies to DynamoDB\n")

    # Print the policies.
    print("=== Optimized Reorder Policies ===\n")
    for policy in result["policies"]:
        print(f"  {policy['item_id']} ({policy['description']})")
        print(f"    Reorder point: {policy['reorder_point']} units")
        print(f"    Order quantity: {policy['order_quantity']} units")
        print(f"    Safety stock: {policy['safety_stock']} units")
        print(f"    Service level: {policy['service_level']:.1%}")
        print(f"    Annual cost: ${policy['expected_annual_holding_cost'] + policy['expected_annual_ordering_cost']:,.2f}")
        print()

    # Step 6: Demonstrate execution logic.
    print("=== Step 6: Execution Engine Demo ===\n")
    # Simulate some inventory levels to show the reorder logic in action.
    test_scenarios = [
        ("SKU-04821-CATH-KIT", 15, 0),   # below reorder point, nothing on order
        ("SKU-11002-IV-NS", 200, 100),    # above reorder point with pending order
        ("SKU-09100-REAGENT-A", 5, 0),    # critical low, below safety stock
    ]

    policy_lookup = {p["item_id"]: p for p in result["policies"]}

    for item_id, on_hand, on_order in test_scenarios:
        if item_id in policy_lookup:
            decision = check_and_reorder(item_id, on_hand, on_order, policy_lookup[item_id])
            print(f"  {item_id}: on_hand={on_hand}, on_order={on_order}")
            print(f"    -> {decision['action']}")
            if decision["action"] == "order_placed":
                print(f"       qty={decision['quantity']}, priority={decision['priority']}")
            print()

    return result


if __name__ == "__main__":
    result = run_optimization_pipeline()

    # Dump full result as JSON for inspection.
    print("\n=== Full Result (JSON) ===\n")
    print(json.dumps(result, indent=2))
```

---

## The Gap Between This and Production

This example solves a real optimization problem with a real solver. The math is correct. The distance to production is in the surrounding infrastructure and data quality.

**Demand forecasting is hardcoded.** The example uses static `daily_demand_mean` and `daily_demand_stddev` values. A production system feeds these from a trained time series model (SageMaker DeepAR, Prophet, or similar) that updates daily with fresh consumption data. The forecast quality directly determines safety stock accuracy: overestimate variance and you hold too much inventory; underestimate it and you get stockouts. Recipe 12.2 covers the forecasting component in detail.

**The linearization simplification.** The true objective function has a `1/Q` term (ordering cost = annual_demand / Q * cost_per_order) which is non-linear. This example fixes Q at the EOQ value and only optimizes reorder points under shared constraints. A production system either uses piecewise linearization to approximate the non-linear term within the MIP, or solves iteratively (optimize Q given r, then optimize r given Q, repeat until convergence). The simplification is reasonable for a first implementation but leaves money on the table for items where the EOQ doesn't account for cross-item budget competition.

**No ERP integration.** The execution engine here is a standalone function. In production, it's triggered by inventory-level-change events from your ERP (via EventBridge or a polling integration). The purchase order submission goes back to the ERP's procurement module. This bidirectional integration is typically the longest implementation phase because ERP APIs are... what they are.

**No order consolidation.** Items from the same distributor should be grouped into a single purchase order to reduce per-order costs and potentially hit volume discount breakpoints. This example optimizes each item independently. Adding order consolidation (grouping items by vendor, timing orders to align) can double cost savings but requires a second optimization layer on top of the per-item policies.

**No multi-location logic.** A health system with multiple facilities could redistribute excess inventory from one site to another instead of ordering new stock. This adds transfer costs and inter-facility logistics but reduces system-wide inventory investment. The solver becomes a network flow problem.

**Solver scalability.** HiGHS handles thousands of items well for this problem structure. If you're optimizing 10,000+ items with complex cross-item constraints (volume discounts, vendor minimums across item groups), you may need a commercial solver (Gurobi, CPLEX) or problem decomposition (solve by department, then reconcile at the system level).

**DynamoDB Decimal handling.** Every numeric value written to DynamoDB uses `Decimal(str(value))`. This example does it correctly in `store_policies`. If you add new numeric fields later, they need the same treatment. A raw Python float in a `put_item` call raises `TypeError` at runtime.

**Audit trail and rollback.** The example stores policies with a version timestamp, which enables history queries. A production system also stores the full solver input (parameters, constraints) alongside the output so you can reproduce any historical optimization run. When a new policy produces unexpected ordering behavior, you need to trace back to the inputs that produced it.

**Monitoring and alerting.** No CloudWatch metrics here. A production system tracks: solver status per run, solve time, optimality gap, number of items where constraints are binding, stockout events post-deployment, and actual vs. predicted demand accuracy. The last one is your feedback loop: if actual demand consistently exceeds forecasts, your safety stock calculations are systematically too low.

**VPC and encryption.** Production Lambda and ECS tasks run in a VPC with private subnets. DynamoDB encryption at rest. S3 SSE-KMS for the data lake. All API calls over TLS. If inventory data links to patient procedures (surgical supply consumption tied to case records), it's PHI-adjacent and needs the full HIPAA treatment.

**Testing.** Build unit tests for the parameter estimation (known inputs should produce known safety stock values). Build integration tests with a small catalog that has a known optimal solution (verify the solver finds it). Build regression tests that compare new solver versions against baseline results. The optimization math is deterministic given fixed inputs, so reproducibility testing is straightforward.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 14.3: Inventory Reorder Optimization](chapter14.03-inventory-reorder-optimization) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
