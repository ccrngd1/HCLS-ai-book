# Code Review: Recipe 14.8 - Ambulance Routing and Dispatch

## Summary

The Python companion is an excellent pedagogical implementation of the ambulance dispatch and repositioning optimization. The code correctly uses OR-Tools for the coverage optimization, demonstrates proper DynamoDB Decimal handling, builds understanding progressively from fleet state through scoring to the full solver, and includes generous comments explaining the "why" behind EMS-specific decisions. The scoring function faithfully implements the pseudocode's multi-criteria approach, and the repositioning solver is correctly formulated as a set-covering assignment problem. The code would run without errors given the stated prerequisites.

---

## Verdict: **PASS**

---

## Findings

### Finding 1: `normalize_value` used inconsistently with pseudocode's `normalize(travel_time, max=20)`

- **Severity:** WARNING
- **Location:** Python companion, Step 3, `score_candidates()`, the composite score calculation
- **What's wrong:** The pseudocode normalizes travel time with `normalize(travel_time, max=20)` (implying 20 minutes = 1200 seconds as the max). The Python code uses `normalize_value(travel_time, 1200)` which is consistent in absolute terms (1200 seconds = 20 minutes). However, the pseudocode's Priority 1 override uses `0.90 * normalize(travel_time, max=20)` while the Python code uses the `PRIORITY_1_WEIGHTS` dict with `normalize_value(travel_time, 1200)`. The Python implementation applies all four weight components even for Priority 1 (fatigue weight is 0.0, workload weight is 0.0), which is functionally equivalent but structurally different from the pseudocode's two-term formula. This is fine pedagogically but worth noting for readers comparing the two.
- **Impact:** No functional difference. The zero-weighted terms contribute nothing. A reader carefully comparing pseudocode to Python might be momentarily confused.
- **Fix:** No fix needed. Could add a brief comment: `# Zero-weighted terms included for code uniformity; equivalent to pseudocode's two-term formula`

### Finding 2: `compute_coverage_impact` uses float accumulation for `other_units_in_zone`

- **Severity:** NOTE
- **Location:** Python companion, Step 3, `compute_coverage_impact()`, line `other_units_in_zone += 0.5`
- **What's wrong:** The variable `other_units_in_zone` starts as an integer (0) and then gets 0.5 added for adjacent units, making it a float. The subsequent comparisons (`>= 2`, `>= 1`) work correctly with floats in Python, but the mixed int/float accumulation is slightly surprising for learners. The threshold logic means an adjacent unit (0.5 credit) alone doesn't count as "one backup" (needs >= 1), which is the intended behavior.
- **Impact:** Purely pedagogical. The logic is correct. A learner might wonder why the variable is sometimes int and sometimes float.
- **Fix:** Could initialize as `other_units_in_zone = 0.0` to make the float nature explicit from the start, or add a comment explaining the partial-credit approach.

### Finding 3: Hospital selection scoring differs slightly from pseudocode

- **Severity:** WARNING
- **Location:** Python companion, Step 4, `select_hospital()`, the `dest_score` calculation
- **What's wrong:** The pseudocode's hospital scoring uses:
  ```
  0.50 * normalize(transport_time, max=30)
  + 0.35 * capacity_score
  + 0.15 * (1.0 IF hospital.has_specialty_bed ELSE 0.5)
  ```
  The Python implementation uses:
  ```python
  0.50 * normalize_value(transport_seconds, 1800)  # 30 min max
  + 0.35 * capacity_ratio
  + 0.15 * (0.0 if len(hospital["capabilities"]) > 3 else 0.3)
  ```
  Two differences: (1) The pseudocode's third term rewards specialty bed availability (higher score = worse, so 1.0 for no bed, 0.5 for has bed), while the Python uses number of capabilities as a proxy (0.0 for many capabilities = better, 0.3 for fewer). The directionality is inverted from the pseudocode. (2) The pseudocode's third term ranges 0.5-1.0 while the Python ranges 0.0-0.3, changing the effective weight.
- **Impact:** The Python version slightly favors hospitals with more capabilities (lower score = better), which is reasonable but doesn't match the pseudocode's "specialty bed" concept. A reader implementing from the pseudocode would get different behavior. The overall ranking is unlikely to change dramatically since the third term has only 15% weight.
- **Fix:** Add a comment explaining the simplification: `# Simplified from pseudocode's specialty_bed check; using capability count as proxy since our synthetic data doesn't model individual bed availability`

### Finding 4: `store_dispatch_decision` is defined but never called in the main flow

- **Severity:** NOTE
- **Location:** Python companion, Step 6 and "Putting It All Together" section
- **What's wrong:** The `store_dispatch_decision()` function is defined in Step 6 and correctly handles Decimal conversion for DynamoDB. However, the `dispatch_ambulance()` function in the final section never calls it. The function returns the decision dict but doesn't persist it. The `if __name__ == "__main__"` block also doesn't call it.
- **Impact:** A reader following the code top-to-bottom might expect the audit trail write to happen automatically. The function is correctly implemented and would work if called, but the integration is left as an exercise. This is acceptable for a teaching example (avoids requiring a real DynamoDB table to run the demo), but could be made more explicit.
- **Fix:** Add a commented-out call in `dispatch_ambulance()`:
  ```python
  # In production, persist the decision for audit trail:
  # store_dispatch_decision(decision)
  ```

### Finding 5: Solver infeasibility handling is correct but could be more informative

- **Severity:** NOTE
- **Location:** Python companion, Step 5, `optimize_repositioning()`, solver status check
- **What's wrong:** The code correctly checks for `OPTIMAL` or `FEASIBLE` status and returns an empty list if the solver fails. This is the right behavior (graceful degradation). However, the warning message doesn't distinguish between INFEASIBLE (constraints are contradictory) and other failure modes (time limit, numerical issues). For a teaching example, it would help learners understand why a solver might fail.
- **Impact:** Minor. The code handles failure correctly. A learner debugging a modified version might not understand why the solver returned no solution.
- **Fix:** Could expand the warning:
  ```python
  if status == pywraplp.Solver.INFEASIBLE:
      logger.warning("Repositioning problem is infeasible (constraints too tight).")
  elif status == pywraplp.Solver.NOT_SOLVED:
      logger.warning("Solver did not run. Check problem formulation.")
  else:
      logger.warning("Solver returned status %d (not optimal/feasible).", status)
  ```

### Finding 6: DynamoDB Decimal handling is correct

- **Severity:** NOTE (positive)
- **Location:** Python companion, Step 6, `store_dispatch_decision()`
- **What's wrong:** Nothing. The code correctly uses `json.loads(json.dumps(decision), parse_float=Decimal)` to convert all float values to Decimal before writing to DynamoDB. This is the standard pattern and avoids the `TypeError: Float types are not supported` that catches many developers.
- **Impact:** Positive. Good teaching of a common boto3 gotcha.
- **Fix:** None needed.

### Finding 7: OR-Tools solver creation uses string-based backend selection

- **Severity:** NOTE
- **Location:** Python companion, Step 5, `optimize_repositioning()`, `pywraplp.Solver.CreateSolver("SCIP")`
- **What's wrong:** Nothing incorrect. The code correctly creates a SCIP solver instance and checks for `None` return (which happens if SCIP is not available in the OR-Tools installation). The error handling is appropriate. SCIP is bundled with the standard `ortools` pip package, so this will work for any reader who follows the setup instructions.
- **Impact:** None. Correct usage.
- **Fix:** None needed.
