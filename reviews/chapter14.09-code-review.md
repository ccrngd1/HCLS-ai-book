# Code Review: Recipe 14.9 - Chemotherapy Scheduling

## Summary

The Python companion is a well-structured teaching implementation of chemotherapy infusion scheduling using Google OR-Tools CP-SAT solver. It demonstrates multi-resource constraint formulation (chairs, nursing capacity, pharmacy prep), a weighted multi-objective function, DynamoDB persistence with proper Decimal conversion, and real-time disruption handling. The code builds progressively from protocol definitions through constraint modeling to solution extraction and day-of adjustments. Comments are excellent throughout, explaining both the optimization math and the clinical reasoning. The infeasible case returns a clear status dict rather than crashing.

However, the no-overlap constraint formulation has a significant logical error that would produce incorrect results, and the nursing capacity overlap detection has a half-reification issue that makes it incomplete.

---

## Verdict: **FAIL**

---

## Findings

### Finding 1: No-overlap constraint formulation is logically incorrect

- **Severity:** ERROR
- **Location:** Python companion, Step 3, `optimize_schedule()`, "Constraint 1: No two patients overlap in the same chair" section
- **What's wrong:** The code attempts to enforce no-overlap for patients in the same chair but the logic is broken in multiple ways:

  1. The code defines `no_overlap_ij` and `no_overlap_ij.Not()` as an ordering pair, then immediately redefines `i_before_j` and `j_before_i` as separate boolean variables that duplicate the same intent. The first pair (`no_overlap_ij` / `no_overlap_ij.Not()`) enforces that EITHER i finishes before j starts OR j finishes before i starts, but it does so unconditionally (not gated on `same_chair`). This means even patients in different chairs get ordering constraints applied.

  2. The `AddBoolOr([no_overlap_ij, no_overlap_ij.Not()]).OnlyEnforceIf(same_chair)` line is a tautology. `x OR NOT x` is always true. This constraint does nothing.

  3. The second pair (`i_before_j`, `j_before_i`) adds the correct conditional constraints but only enforces them with `OnlyEnforceIf` in one direction. The variables are created and constrained with `OnlyEnforceIf(i_before_j)` and `OnlyEnforceIf(j_before_i)`, but there's no constraint saying these must be false when the condition doesn't hold. CP-SAT's half-reification means `Add(X).OnlyEnforceIf(B)` enforces X when B is true, but says nothing when B is false. Without the negation side, the solver can set `i_before_j = False` and `j_before_i = False` simultaneously, satisfying `AddBoolOr([i_before_j, j_before_i]).OnlyEnforceIf(same_chair)` only if `same_chair` is false. But `same_chair` is itself only half-reified.

  The net effect: the solver may assign two patients to the same chair with overlapping times because the constraints don't fully enforce the disjunction.

- **Impact:** A reader implementing this pattern would get schedules with chair double-bookings. This is the core constraint of the entire optimization and it's broken.
- **Fix:** Use CP-SAT's interval variables with `AddNoOverlap` per chair (the idiomatic approach), or use the simpler pairwise formulation with proper full reification:
  ```python
  for i in range(num_patients):
      for j in range(i + 1, num_patients):
          duration_i = requests[i]["total_duration_minutes"] + TURNOVER_BUFFER_MINUTES
          duration_j = requests[j]["total_duration_minutes"] + TURNOVER_BUFFER_MINUTES

          same_chair = model.NewBoolVar(f"same_chair_{i}_{j}")
          model.Add(chair_vars[i] == chair_vars[j]).OnlyEnforceIf(same_chair)
          model.Add(chair_vars[i] != chair_vars[j]).OnlyEnforceIf(same_chair.Not())

          # If same chair, i must finish before j starts OR j must finish before i starts
          i_before_j = model.NewBoolVar(f"order_{i}_{j}")
          model.Add(start_vars[i] + duration_i <= start_vars[j]).OnlyEnforceIf(same_chair, i_before_j)
          model.Add(start_vars[j] + duration_j <= start_vars[i]).OnlyEnforceIf(same_chair, i_before_j.Not())
  ```
  Or better yet for a teaching example, use optional interval variables per chair with `AddNoOverlap`, which is the canonical CP-SAT pattern for this problem.

### Finding 2: Nursing capacity overlap detection is incomplete due to half-reification

- **Severity:** ERROR
- **Location:** Python companion, Step 3, `optimize_schedule()`, "Constraint 2: Nursing capacity per time period" section
- **What's wrong:** The overlap detection uses:
  ```python
  overlaps = model.NewBoolVar(f"overlaps_{i}_p{period_idx}")
  model.Add(start_vars[i] < period_end).OnlyEnforceIf(overlaps)
  model.Add(start_vars[i] + duration > period_start).OnlyEnforceIf(overlaps)
  model.Add(start_vars[i] >= period_end).OnlyEnforceIf(overlaps.Not())
  ```

  This is incomplete. `OnlyEnforceIf(overlaps)` means "if overlaps is true, then these constraints hold." But it does NOT mean "if these constraints hold, then overlaps must be true." The solver can freely set `overlaps = False` even when the patient actually does overlap the period, because half-reification doesn't enforce the reverse implication.

  Additionally, the `OnlyEnforceIf(overlaps.Not())` line only constrains `start_vars[i] >= period_end`, but a patient could also not overlap if `start_vars[i] + duration <= period_start`. The negation side is missing the second disjunct.

  The result: the nursing capacity constraint is not actually enforced. The solver can set all `overlaps` variables to False and trivially satisfy the capacity constraint with zero demand in every period.

- **Impact:** A reader would get schedules that appear to respect nursing capacity but actually don't. The constraint is effectively a no-op.
- **Fix:** Use proper channeling constraints to force `overlaps` to be true when the patient actually overlaps:
  ```python
  # Patient overlaps period if: start < period_end AND start + duration > period_start
  # Equivalently: NOT overlaps => (start >= period_end OR start + duration <= period_start)
  cond1 = model.NewBoolVar(f"after_period_{i}_{period_idx}")
  cond2 = model.NewBoolVar(f"before_period_{i}_{period_idx}")
  model.Add(start_vars[i] >= period_end).OnlyEnforceIf(cond1)
  model.Add(start_vars[i] + duration <= period_start).OnlyEnforceIf(cond2)
  model.AddBoolOr([cond1, cond2]).OnlyEnforceIf(overlaps.Not())
  model.Add(start_vars[i] < period_end).OnlyEnforceIf(overlaps)
  model.Add(start_vars[i] + duration > period_start).OnlyEnforceIf(overlaps)
  ```

### Finding 3: Pharmacy prep constraint has same half-reification problem and missing negation case

- **Severity:** WARNING
- **Location:** Python companion, Step 3, `optimize_schedule()`, "Constraint 3: Pharmacy prep capacity per hour" section
- **What's wrong:** The pharmacy constraint uses:
  ```python
  prep_in_hour = model.NewBoolVar(f"prep_{i}_hour{hour_idx}")
  model.Add(start_vars[i] - prep_offset >= hour_start).OnlyEnforceIf(prep_in_hour)
  model.Add(start_vars[i] - prep_offset < hour_end).OnlyEnforceIf(prep_in_hour)
  model.Add(start_vars[i] - prep_offset < hour_start).OnlyEnforceIf(prep_in_hour.Not())
  ```

  Same half-reification issue as Finding 2: the solver can set `prep_in_hour = False` even when the prep actually falls in that hour. Additionally, the negation side only checks `< hour_start` but not `>= hour_end`. A prep that starts after the hour would also not be in the hour, but this case isn't covered in the negation.

  Unlike Finding 2, this is less catastrophic because pharmacy capacity is typically not the binding constraint in the sample data (8 preps/hour with 12 patients spread across 11 hours). But the pattern is still incorrect and misleading.

- **Impact:** Pharmacy capacity constraint is not reliably enforced. For the sample data this likely doesn't cause visible problems, but a reader scaling to a real center (40+ patients) would get schedules that overload pharmacy.
- **Fix:** Same channeling pattern as Finding 2. Force the boolean to be true when the condition actually holds.

### Finding 4: `WEIGHTS` dict is defined but never used in the objective function

- **Severity:** WARNING
- **Location:** Python companion, Configuration and Constants section + Step 3 objective function
- **What's wrong:** The `WEIGHTS` dictionary defines weights for utilization (0.35), wait_time (0.25), workload_leveling (0.25), and preferences (0.15). However, the actual `model.Maximize()` call uses:
  ```python
  model.Maximize(
      sum(objective_terms)  # earliness terms
      + 100 * sum(preference_bonuses)  # preference bonus
  )
  ```
  The weights are never referenced. The `100` multiplier on preferences is a magic number unrelated to the defined weights. The workload leveling objective (`max_demand` variable) is created but never added to the objective. The wait_time objective is not implemented at all.

  The main recipe's pseudocode explicitly shows a weighted combination of all four objectives.

- **Impact:** A reader would define weights thinking they control the optimization behavior, but they have no effect. The actual objective is just "schedule early + respect preferences" with an arbitrary 100x multiplier on preferences.
- **Fix:** Either use the weights in the objective formulation, or remove the `WEIGHTS` dict and explain in a comment that the simplified example only optimizes for earliness and preferences. The latter is more honest for a teaching example.

### Finding 5: Preference satisfaction check in objective uses incomplete half-reification

- **Severity:** WARNING
- **Location:** Python companion, Step 3, Objective 2 section
- **What's wrong:** The preference window check:
  ```python
  in_window = model.NewBoolVar(f"in_pref_{i}")
  model.Add(start_vars[i] >= pref_start).OnlyEnforceIf(in_window)
  model.Add(start_vars[i] <= pref_end).OnlyEnforceIf(in_window)
  model.Add(start_vars[i] < pref_start).OnlyEnforceIf(in_window.Not())
  ```

  The negation side only checks `start < pref_start`. A patient scheduled AFTER the preference window (`start > pref_end`) would not trigger `in_window.Not()` to be enforced. The solver could set `in_window = True` for a patient scheduled after their window, inflating the preference bonus.

  More critically, since `in_window` appears in the objective (maximized), the solver is incentivized to set it to True whenever possible. Without proper channeling, the solver will set `in_window = True` for all patients regardless of actual scheduling, making the preference bonus a constant that doesn't influence the schedule.

- **Impact:** The preference satisfaction metric in the objective is unreliable. The solver gets "free" preference points without actually scheduling patients in their preferred windows.
- **Fix:** Add the missing negation case and proper channeling:
  ```python
  model.Add(start_vars[i] > pref_end).OnlyEnforceIf(in_window.Not())
  # Or use AddBoolOr for the disjunction on the negation side
  ```

### Finding 6: `get_nursing_demand_at_offset` is defined but never called

- **Severity:** NOTE
- **Location:** Python companion, Treatment Protocol Definitions section
- **What's wrong:** The function `get_nursing_demand_at_offset()` is defined with a clear docstring explaining it's "the key function for workload leveling." However, it's never called anywhere in the code. The nursing constraint in Step 3 computes average attention inline instead of using this function. The main recipe's pseudocode references per-phase nursing demand at specific time offsets.
- **Impact:** Dead code that confuses readers. They might expect it to be used in the constraint model and wonder why it isn't.
- **Fix:** Either use it in the constraint formulation (more accurate but more complex) or remove it and note that the simplified example uses average attention as an approximation.

### Finding 7: Disruption handler mutates the schedule dict in place without copy

- **Severity:** NOTE
- **Location:** Python companion, Step 6, `handle_disruption()`
- **What's wrong:** The function modifies `schedule["assignments"]` in place (e.g., `assignments.remove(affected)` for cancellations, direct mutation of `affected` dict fields for delays). The function also returns the schedule, suggesting it might be used functionally. A reader calling `handle_disruption` multiple times (as the demo does) accumulates mutations on the same object, which works but is a pattern that leads to bugs in production (no ability to roll back a disruption response).
- **Impact:** Minor for a teaching example, but the pattern is worth noting since the main recipe discusses the importance of audit trails and rollback capability.
- **Fix:** Add a brief comment noting that production code would work on a copy and only commit changes after validation.

### Finding 8: Pharmacy prep time could go negative (before day start)

- **Severity:** NOTE
- **Location:** Python companion, Step 3 solution extraction and Step 4 `build_pharmacy_sequence()`
- **What's wrong:** For patients scheduled at 07:00 (DAY_START_MINUTES = 420) with a 45-minute pharmacy prep, the prep start time would be 06:15 (375 minutes). The display code `f"{prep_start_minutes // 60:02d}:{prep_start_minutes % 60:02d}"` handles this correctly (shows "06:15"), but the pharmacy constraint in the optimizer doesn't account for this. The `hour_idx` loop starts at `day_start`, so preps that need to start before 07:00 aren't counted against any pharmacy capacity hour.

  This is realistic (pharmacy often starts before the center opens to patients), but it's worth a comment explaining that pharmacy operating hours differ from patient-facing hours.
- **Impact:** Minor. The constraint model slightly under-counts pharmacy load for early-morning preps. A comment would help readers understand the intentional gap.
- **Fix:** Add a comment in the pharmacy constraint section noting that pharmacy hours extend before center opening and that production systems would model pharmacy capacity separately.

---

## Overall Assessment

The code is pedagogically well-structured with excellent comments explaining the clinical reasoning behind each constraint. The protocol definitions, resource modeling, pharmacy coordination, and disruption handling sections are all strong. However, the core constraint formulation (Findings 1 and 2) contains fundamental errors in CP-SAT half-reification that would produce incorrect schedules. These aren't subtle edge cases; they're structural issues where the constraints are effectively unenforced. A reader implementing this pattern would get schedules with chair double-bookings and nursing capacity violations.

The fix is straightforward (proper channeling constraints or using CP-SAT's built-in interval/NoOverlap primitives), and the rest of the code is solid. But as written, the optimization core doesn't actually optimize correctly.
