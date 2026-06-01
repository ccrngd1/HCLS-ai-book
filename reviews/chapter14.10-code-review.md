# Code Review: Recipe 14.10 - Health System Network Design

## Summary

The Python companion is an excellent teaching implementation of health system network design using PuLP for mixed-integer programming. The code correctly formulates a facility location problem with binary open/offer variables, continuous patient flow variables, and appropriate constraints (budget, capacity, minimum volume, gravity model consistency, candidate facility linking, existing service preservation). The scenario analysis and robustness identification logic is sound. The S3 storage uses SSE-KMS encryption. Comments are pedagogically strong throughout, explaining both the optimization concepts and the healthcare domain reasoning. The logical flow builds progressively from data setup through formulation, solving, scenario analysis, and result storage.

---

## Verdict: **PASS**

---

## Findings

### Finding 1: `solve_model` references non-existent `model.sol_status` attribute

- **Severity:** WARNING
- **Location:** Python companion, Step 3, `solve_model()`, status_text line
- **What's wrong:** The code uses:
  ```python
  "status_text": model.sol_status[model.status] if hasattr(model, 'sol_status') else str(model.status),
  ```
  PuLP's `LpProblem` does not have a `sol_status` attribute. The `hasattr` guard prevents a crash, so the fallback `str(model.status)` will always execute. However, this is misleading to a reader who might think `sol_status` is a real PuLP feature. The correct way to get a human-readable status in PuLP is `pulp.LpStatus[model.status]` (a module-level dict mapping status codes to strings like "Optimal", "Infeasible", etc.).
- **Impact:** The code runs without error (the `hasattr` guard catches it), but a reader copying this pattern won't get meaningful status text. They'll get the integer status code as a string instead of "Optimal" or "Infeasible".
- **Fix:** Replace with:
  ```python
  from pulp import LpStatus
  "status_text": LpStatus[model.status],
  ```

### Finding 2: Demand constraint uses `<=` (allows under-serving) but `identify_robust_decisions` doesn't account for infeasible scenarios in new-facility analysis

- **Severity:** NOTE
- **Location:** Python companion, Step 2, constraint 3 ("Demand satisfaction") and Step 4, `identify_robust_decisions()`
- **What's wrong:** The demand constraint uses `<=` (allowing partial demand capture, which the comment correctly notes as "leakage"). This is a valid modeling choice. However, in `identify_robust_decisions()`, the robustness check only looks at `service_line_additions`. It does not check `new_facilities_opened`. A facility opening decision could be robust (appears in all scenarios) or contingent, but only service line additions are classified.

  The main recipe's pseudocode Step 4 says "Identify robust decisions: same in all (or most) scenarios" and includes both facility opening and service line decisions in the robustness analysis.
- **Impact:** A reader gets robustness analysis for service line additions but not for facility opening decisions. The output includes `new_facilities_opened` in each scenario result, but the robustness classification only covers service additions.
- **Fix:** Add a parallel analysis for facility opening decisions:
  ```python
  all_openings = {}
  for scenario_name, result in scenario_results.items():
      if result.get("status") == "infeasible":
          continue
      for fac in result.get("new_facilities_opened", []):
          key = fac["facility"]
          if key not in all_openings:
              all_openings[key] = {"decision": fac, "scenarios": []}
          all_openings[key]["scenarios"].append(scenario_name)
  ```

### Finding 3: `compute_choice_probabilities` computes probabilities for ALL facilities regardless of whether they offer the service

- **Severity:** NOTE
- **Location:** Python companion, Step 1, `compute_choice_probabilities()`, docstring and implementation
- **What's wrong:** The docstring correctly states: "This function returns probabilities assuming ALL facilities offer the service; the optimizer will zero out flows to facilities that don't." This is a valid approach because the `offer[f][s]` variable in the capacity constraint (`<= CAPACITY_PER_FACILITY[s] * offer[f][s]`) will force flow to zero when `offer[f][s] = 0`. However, the gravity model bound constraint:
  ```python
  flow[z][f][s] <= max_flow  # where max_flow = demand * choice_prob
  ```
  allows non-zero flow to facilities that don't offer the service (the gravity bound is positive for all facilities). The capacity constraint is what actually prevents this flow. This is correct but could confuse a reader who expects the gravity bound alone to enforce service availability.
- **Impact:** No correctness issue (the capacity constraint handles it), but the interaction between gravity bounds and capacity constraints is subtle and not explained in comments.
- **Fix:** Add a brief comment in the gravity bound constraint section:
  ```python
  # Note: This bound is positive even for facilities not offering the service.
  # The capacity constraint (which multiplies by offer[f][s]) is what actually
  # prevents flow to facilities that don't offer the service.
  ```

### Finding 4: S3 key path does not have a leading slash (correct), but bucket name is hardcoded

- **Severity:** NOTE
- **Location:** Python companion, Step 5, `store_optimization_results()`
- **What's wrong:** The S3 key `f"optimization-runs/{run_id}/results.json"` correctly has no leading slash. The bucket name `RESULTS_BUCKET = "health-system-network-optimization"` is hardcoded as a constant with a comment saying "Replace with your actual bucket name." This is fine for a teaching example, but the comment could note that in production this would come from environment variables or SSM Parameter Store.
- **Impact:** Minor. The pattern is clear and the comment tells the reader to replace it.
- **Fix:** No change needed. The existing comment is sufficient for a teaching example.

### Finding 5: `run_network_design_optimization` logs `model.numVariables()` and `model.numConstraints()` which are correct PuLP API calls

- **Severity:** NOTE (positive observation)
- **Location:** Python companion, "Putting It All Together" section
- **What's wrong:** Nothing wrong. Unlike the OR-Tools proto access pattern seen in other recipes, this code correctly uses PuLP's public API methods `numVariables()` and `numConstraints()` for model statistics. This is the idiomatic approach.
- **Impact:** Good teaching pattern.
- **Fix:** None needed.

---

## Pseudocode-to-Python Consistency

| Main Recipe Pseudocode Step | Python Implementation | Consistent? |
|---|---|---|
| Step 1: `build_demand_zones()` | Hardcoded `DEMAND_ZONES` dict | Yes (simplified, noted in intro) |
| Step 2: `estimate_gravity_model()` | `compute_choice_probabilities()` with fixed beta params | Yes (simplified, noted in Step 1 header comment) |
| Step 3: `formulate_network_model()` | `formulate_network_model()` | Yes, with minor differences (see below) |
| Step 4: `run_scenario_analysis()` | `create_scenarios()` + `run_scenario()` + `identify_robust_decisions()` | Mostly yes (Finding 2: missing facility robustness) |
| Step 5: `compute_sensitivity_and_present()` | `store_optimization_results()` | Partial (stores results but no sensitivity sweep) |

**Step 3 differences from pseudocode:**
- Pseudocode includes workforce constraints and CON constraints; Python omits these (reasonable simplification for a teaching example with synthetic data).
- Pseudocode uses `demand == total_demand` (equality); Python uses `<= demand` (allows leakage). The Python approach is noted in comments and is actually more realistic.
- Pseudocode includes capacity tiers (integer variable); Python uses a simpler binary offer * fixed capacity. Reasonable simplification.
- Pseudocode includes service line dependencies; Python omits these. Noted in the Gap to Production section.

**Step 5 differences from pseudocode:**
- Pseudocode includes parameter sensitivity sweeps (vary each parameter +/- 20%); Python only does scenario analysis (discrete scenarios with demand multipliers). The scenario analysis is the more important piece for teaching; sensitivity sweeps are mentioned in the Gap to Production section.

All simplifications are either noted in comments or covered in the Gap to Production section. No silent omissions.

---

## AWS SDK Accuracy

- **`s3_client.put_object()`:** Correct parameters: `Bucket`, `Key`, `Body`, `ContentType`, `ServerSideEncryption`. ✓
- **`ServerSideEncryption="aws:kms"`:** Correct value for KMS encryption. ✓
- **Comment about `SSEKMSKeyId`:** Correctly notes this should be specified in production. ✓
- **boto3 Config for retries:** `Config(retries={"max_attempts": 3, "mode": "adaptive"})` is correct. ✓
- **S3 key path:** `optimization-runs/{run_id}/results.json` has no leading slash. ✓
- **No DynamoDB usage:** N/A (no Decimal concerns).
- **`datetime.datetime.now(timezone.utc).isoformat()`:** Correct timezone-aware timestamp generation. ✓

---

## Comment Quality

Comments are strong throughout:
- Explain *why* PuLP/CBC is chosen (ships with PuLP, no license needed for learning)
- Explain *why* the gravity model uses exponential distance decay (patients won't all drive past closer facilities)
- Explain *why* minimum volume constraints exist (quality and accreditation, not just economics)
- Explain *why* existing services are forced to stay open (politically charged closure decisions are separate)
- Explain *why* the capital amortization uses 10-year straight-line (simplified for teaching)
- Explain *why* the road network multiplier is 1.4x (roads aren't straight lines)
- The Gap to Production section is exceptionally thorough: covers demand model calibration, gravity model estimation, solver selection, stochastic optimization, service line dependencies, multi-period staging, error handling, IAM, VPC/encryption, model validation, and stakeholder interface
- The intro paragraph sets expectations clearly ("sketch on the whiteboard... starting point, not a destination")

---

## Overall Assessment

This is a well-crafted teaching implementation of a complex optimization problem. The MIP formulation is mathematically correct: binary variables for facility/service decisions, continuous variables for patient flows, and the constraint set properly enforces budget limits, capacity bounds, minimum volume thresholds, gravity model consistency, and facility-service linking. The solver invocation is clean with appropriate parameters (time limit, gap tolerance). The scenario analysis correctly identifies robust versus contingent decisions.

The primary gap (Finding 1: `sol_status` attribute) is a WARNING because it produces misleading output (integer status code instead of human-readable string), though the code doesn't crash. Finding 2 (incomplete robustness analysis for facility openings) is a NOTE because the data is available in the output, just not classified. With only 1 WARNING, this is well within the PASS threshold.

The code would actually run end-to-end on the synthetic data (minus the S3 storage which is commented out in the main function). The optimization formulation is tight, the constraints are correctly linked, and the infeasible case is handled gracefully (returns error dict with details rather than crashing).
