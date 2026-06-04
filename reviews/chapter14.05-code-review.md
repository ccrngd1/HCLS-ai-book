# Code Review: Recipe 14.5 - Operating Room Block Scheduling

## Summary

The Python companion is a well-structured teaching implementation of OR block scheduling using PuLP and the CBC solver. The code correctly formulates binary decision variables, hard constraints (room capability, surgeon availability, one-service-per-block), a fairness floor constraint, and a multi-objective function balancing utilization, disruption, and equity. The S3 integration uses correct boto3 calls with server-side encryption. The infeasible case is handled gracefully with early return and structured output. Comments are thorough and explain optimization concepts clearly. The logical flow progresses naturally from data loading through model formulation to solution analysis.

---

## Verdict: **PASS**

---

## Findings

### Finding 1: Floating-point comparison for binary variable extraction is fragile

- **Severity:** WARNING
- **Location:** Python companion, Step 4, `solve_model()`, solution extraction loop
- **What's wrong:** The code uses exact equality to check binary variable values:
  ```python
  if pulp.value(x[sid][bid]) == 1:
      schedule[bid] = sid
  ```
  PuLP's `pulp.value()` returns a float. Due to floating-point representation, a solved binary variable may return `0.9999999` or `1.0000001` rather than exactly `1`. While CBC typically returns clean integers for binary variables, other solvers (or models with numerical issues) may not.
- **Impact:** On the provided sample data with CBC, this will work correctly. A reader switching to a different solver (as the text suggests with HiGHS or Gurobi) might encounter missed assignments.
- **Fix:** Use a tolerance-based check:
  ```python
  if pulp.value(x[sid][bid]) >= 0.5:
      schedule[bid] = sid
  ```
  Or use PuLP's built-in rounding: `if round(pulp.value(x[sid][bid])) == 1:`

### Finding 2: `solve_model` does not handle the "Not Solved" or timeout status

- **Severity:** WARNING
- **Location:** Python companion, Step 4, `solve_model()`
- **What's wrong:** The code checks for "Infeasible" status but falls through to solution extraction for any other status, including "Not Solved" (solver did not run) and "Undefined" (timeout with no feasible solution found). PuLP status codes include: "Optimal", "Not Solved", "Infeasible", "Unbounded", and "Undefined". If the solver times out without finding any feasible solution, `model.status` will be `0` ("Not Solved") and attempting to extract variable values will return `None`, causing the `== 1` comparison to fail silently (returning an empty schedule with an "Optimal"-looking status string).
- **Impact:** The code would return `{"status": "NOT SOLVED", "schedule": {}}` without any error indication, which could confuse a reader. The `objective_value` would be `None` and the downstream `print(f"Objective value: {solution['objective_value']:.2f}")` would raise a `TypeError`.
- **Fix:** Add handling for non-optimal, non-infeasible statuses:
  ```python
  if status not in ("Optimal", "Feasible"):
      logger.warning("Solver did not find a feasible solution: %s", status)
      return {
          "status": status.upper(),
          "schedule": {},
          "objective_value": None,
          "solve_seconds": solve_seconds,
      }
  ```
  And guard the format string in `run_block_optimization`:
  ```python
  if solution["objective_value"] is not None:
      print(f"  Objective value: {solution['objective_value']:.2f}")
  ```

### Finding 3: Disruption penalty counts assignments to non-current-owners even when block was previously unassigned

- **Severity:** NOTE
- **Location:** Python companion, Step 3, `formulate_model()`, disruption penalty section
- **What's wrong:** The code applies a disruption penalty when `current_owner and current_owner != sid`:
  ```python
  current_owner = current_allocation.get(bid)
  if current_owner and current_owner != sid:
      disruption_penalty.append(x[sid][bid])
  ```
  This correctly skips blocks not in `current_allocation` (newly available blocks). However, it penalizes assigning ANY other service to a currently-owned block, even if that block's current owner doesn't actually want it (e.g., they are over-allocated). The pseudocode describes disruption as "every block that changes hands," which this implements faithfully. This is a design choice, not a bug, but worth noting for readers who might want asymmetric disruption (penalizing taking blocks away more than giving them to new services).
- **Impact:** None for correctness. The model works as described.
- **Fix:** No fix needed. Could add a comment noting the symmetric disruption assumption.

### Finding 4: `analyze_solution` has a division-by-zero risk in `expected_util` when `new_hours > 0`

- **Severity:** NOTE
- **Location:** Python companion, Step 5, `analyze_solution()`
- **What's wrong:** The utilization calculation:
  ```python
  expected_util = needed / new_hours if new_hours > 0 else 0.0
  ```
  When `new_hours > 0` but is very small relative to `needed`, `expected_util` could be extremely large before the `min(..., 1.0)` cap. This is mathematically correct (it means the service is heavily under-allocated) but the capping at 1.0 makes the metric misleading: a service getting 4 hours when it needs 20 would show `expected_utilization: 1.0`, suggesting perfect utilization when in reality the service is severely under-served.
- **Impact:** The metric conflates "fully utilized" with "severely under-allocated." However, the `allocated_hours` and `weekly_demand_hours` fields in the same output make the true situation clear. For a teaching example, this is acceptable.
- **Fix:** Add a comment explaining that `expected_utilization = 1.0` means "every allocated hour will be used" not "the service has enough hours":
  ```python
  # expected_utilization = demand / allocation, capped at 1.0.
  # A value of 1.0 means all allocated time will be used (100% busy),
  # NOT that the service has sufficient allocation. Check change_hours for that.
  ```

### Finding 5: S3 key construction does not have leading slashes

- **Severity:** NOTE
- **Location:** Python companion, Steps 1 and 6
- **What's wrong:** This is actually correct. Confirming:
  ```python
  Key=f"{prefix}/{key}"          # Step 1: "inputs/2026-Q3/blocks.json"
  Key=f"{output_prefix}/{key}",  # Step 6: "optimization-results/opt-xxx/schedule.json"
  ```
  No leading slashes. Correct S3 key construction.
- **Impact:** None. This is a positive finding.
- **Fix:** None needed.

---

## Pseudocode-to-Python Consistency

| Main Recipe Pseudocode Step | Python Implementation | Consistent? |
|---|---|---|
| `extract_optimization_inputs(lookback_months)` | `load_optimization_inputs(bucket, prefix)` | Yes (simplified: pre-assembled inputs from S3 vs. raw data lake query) |
| `estimate_demand(case_history, known_changes)` | `estimate_demand(services)` | Yes (simplified: pre-calculated demand in input file vs. computed from history) |
| `formulate_model(...)` | `formulate_model(...)` | Yes (see notes below) |
| `solve_and_extract(model, solver_config)` | `solve_model(model, x, blocks, services)` | Mostly (missing IIS computation for infeasible case) |
| `analyze_solution(...)` | `analyze_solution(...)` | Yes |
| `store_and_notify(...)` | `store_results(...)` | Yes (notification omitted, reasonable for teaching) |

**Formulation differences from pseudocode:**
- The pseudocode uses `abs(allocated - demand)` in the utilization objective. The Python companion uses a simpler linear reward (just `allocated`). This is noted in the code comments and the Gap to Production section explains linearization. Acceptable simplification.
- The pseudocode includes a minimum block size constraint. The Python companion omits this since all blocks are uniform 4-hour slots in the sample data. Reasonable for the toy problem.
- The pseudocode's `solve_and_extract` computes an irreducible infeasible set (IIS) when the model is infeasible. The Python companion logs an error and returns empty. The Gap to Production section notes this. Acceptable.

---

## AWS SDK Accuracy

- **`s3_client.get_object(Bucket, Key)`:** Correct parameter names. Response parsed via `response["Body"].read()`. ✓
- **`s3_client.put_object(Bucket, Key, Body, ContentType, ServerSideEncryption)`:** All parameters correct. `ServerSideEncryption="aws:kms"` is the correct value for SSE-KMS. ✓
- **No `KMSMasterKeyId` specified:** When `ServerSideEncryption="aws:kms"` is used without `SSEKMSKeyId`, S3 uses the AWS-managed key (`aws/s3`). This is fine for a teaching example. Production would use a CMK, as noted in the Gap to Production section. ✓
- **boto3 `Config(retries=...)`:** Correct usage with `max_attempts` and `mode` keys. ✓
- **S3 key format:** No leading slashes. ✓
- **No DynamoDB usage:** The code doesn't use DynamoDB (constraints are in S3 JSON files), so no Decimal/float issue applies. ✓

---

## Comment Quality

Comments are strong throughout:
- Explain *why* PuLP is chosen (clean modeling API, solver-agnostic, CBC ships free)
- Explain *why* the optimizer doesn't talk to the EHR directly (separation of concerns, ETL pipeline)
- Explain *why* weights encode value judgments (no mathematically "correct" answer)
- Explain *why* the one-service-per-block constraint uses `<=` not `==` (blocks can be unassigned)
- Explain *why* the disruption penalty exists (human acceptance of schedule changes)
- Explain *why* the fairness bonus targets underserved services specifically
- The Gap to Production section is exceptionally thorough, covering solver choice, error handling, input validation, linearization, scenario management, containerization, logging, IAM, VPC, and testing
- The sample input data section with the "demand equals supply" note helps readers understand why this is a tight optimization problem

---

## Overall Assessment

This is a solid teaching implementation that correctly demonstrates mixed-integer programming for healthcare OR scheduling. PuLP's modeling interface is used correctly: binary variables, linear constraints, and a weighted objective function. The model formulation is sound and the constraint structure prevents invalid assignments. The two WARNING findings (fragile float comparison and missing timeout handling) are edge cases that won't manifest on the provided sample data with CBC, but could trip up readers who scale or swap solvers. Neither produces incorrect results for the demonstrated scenario. The code reads well top-to-bottom, the progressive complexity is pedagogically sound, and the Gap to Production section honestly addresses every shortcut taken.
