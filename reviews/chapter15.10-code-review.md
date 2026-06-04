# Code Review: Recipe 15.10

## Summary

The Python companion for Hospital Resource Allocation Under Uncertainty is a well-structured pedagogical implementation that demonstrates the full RL pipeline shape: environment definition, state construction, reward shaping, constrained policy optimization, and decision support output. The code builds understanding progressively, handles DynamoDB Decimal conversion correctly, uses proper boto3 retry configuration, and honestly acknowledges that the numpy-only policy network doesn't actually learn (no backpropagation). The hard constraint enforcement layer correctly vetoes infeasible actions before execution. There are a few issues: a runtime bug in the time-to-shift-change calculation, some state vector dimension inconsistencies between the simulator and the configuration, and a pedagogically misleading pattern in the offline evaluation section. None prevent the overall teaching goal from being achieved, but one would cause a runtime error.

---

## Verdict: FAIL

One ERROR finding (runtime crash in `_get_state`) plus two WARNING findings.

---

## Issues

### Issue 1: `mins_to_shift` Calculation Will Raise ValueError

- **File:** `chapter15.10-python-example.md`
- **Location:** Step 2 (`HospitalSimulator._get_state`), near end of method
- **Severity:** ERROR (code won't work)
- **Description:** The line computing minutes to next shift change uses a generator expression inside `min()` that produces incorrect results and can go negative:
  ```python
  shift_hours = [7, 15, 23]
  mins_to_shift = min((sh - self.hour) % 24 * 60 - self.minute for sh in shift_hours)
  ```
  The operator precedence is wrong. `(sh - self.hour) % 24 * 60` is evaluated as `((sh - self.hour) % 24) * 60` which is correct for the hours part, but then subtracting `self.minute` can produce a value like `0 * 60 - 30 = -30` when you're 30 minutes past a shift change hour. The `min()` will pick the most negative value. Then `max(0, mins_to_shift)` on the next line rescues it to 0, but the result is semantically wrong (it should be the time to the *next* shift, not zero). A reader implementing this in production would get consistently wrong time-to-shift features.
  
  Additionally, if `self.minute` is 0 and `self.hour` equals one of the shift hours, the expression yields `min(0, ...)` which is correct by accident but for the wrong reason.
- **Suggested fix:**
  ```python
  shift_hours = [7, 15, 23]
  current_total_minutes = self.hour * 60 + self.minute
  shift_minutes = [sh * 60 for sh in shift_hours]
  # Find the next shift change (wrapping around midnight)
  mins_to_shift = min(
      (sm - current_total_minutes) % (24 * 60) for sm in shift_minutes
  )
  features.append(mins_to_shift / 720.0)
  ```

---

### Issue 2: State Vector Dimension Mismatch Between Simulator and Config

- **File:** `chapter15.10-python-example.md`
- **Location:** Step 2 (`HospitalSimulator._get_state`) vs. Config section (`STATE_FEATURES`)
- **Severity:** WARNING (misleading)
- **Description:** The `STATE_FEATURES` config defines 24 features (6 census + 5 staffing + 5 pending + 2 equipment + 4 time cyclical + 1 weekend + 1 shift). However, `_get_state()` in the simulator produces a different number of features:
  - 6 census occupancies (one per UNIT, UNITS has 6 entries)
  - 6 staffing ratios (one per UNIT, but STATE_FEATURES only lists 5 staffing features because it collapses medsurg_a and medsurg_b into one)
  - 5 pending values
  - 2 equipment values
  - 6 time features (sin, cos hour, sin cos dow, is_weekend, shift)
  
  That's 25 features from the simulator vs. 24 in STATE_FEATURES. The `NUM_STATE_FEATURES = len(STATE_FEATURES)` constant is 24, but the actual vector from `_get_state()` has 25 elements (because it emits a staffing ratio for each of the 6 units, while STATE_FEATURES only lists 5 staffing features). The `PolicyNetwork` is initialized with `state_dim=NUM_STATE_FEATURES` (24), so `state @ self.w1` will fail with a shape mismatch when used with the simulator's 25-element output.

  A reader tracing through the code would notice the shape mismatch when `build_state_vector` (24 features, used for production inference) disagrees with `_get_state()` (25 features, used for training). This undermines the teaching goal of showing how training and inference use the same state representation.
- **Suggested fix:** Either:
  1. Add a 6th staffing feature to STATE_FEATURES (e.g., `ed_staff_ratio` is already there, but `medsurg_b_staff_ratio` is missing), making it 25, or
  2. Combine medsurg_a and medsurg_b staffing into one average in `_get_state()`, keeping it at 24.

---

### Issue 3: Offline Evaluation Uses Flawed OPE Logic

- **File:** `chapter15.10-python-example.md`
- **Location:** Step 4 (`evaluate_policy_offline`), reward estimation loop
- **Severity:** WARNING (misleading pattern)
- **Description:** The OPE logic applies a blanket 0.9 discount when the policy action differs from the historical action:
  ```python
  if policy_action == actual_action:
      policy_reward_estimate += discount * step_reward
  else:
      policy_reward_estimate += discount * step_reward * 0.9
  ```
  This is not a valid off-policy evaluation method. It systematically biases toward policies that agree with the historical behavior (since disagreeing always gets a 10% penalty). A reader might carry this pattern into production and conclude their policy is worse than it actually is (conservative bias) or fail to detect a genuinely bad policy that happens to agree with historical actions.

  The comment says "Conservative estimate: assume policy action gets similar reward" but doesn't explain why 0.9 or acknowledge that this isn't importance-weighted evaluation. The pseudocode in the main recipe explicitly describes importance weighting, but the Python implements something different without explaining the deviation.
- **Suggested fix:** Add a prominent comment explaining this is a placeholder:
  ```python
  # WARNING: This is NOT a valid OPE estimator. It's a placeholder that
  # shows where evaluation logic goes. Real OPE requires either:
  # 1. Importance Sampling (needs behavior policy probabilities logged)
  # 2. Fitted Q-Evaluation (needs a learned Q-function)
  # 3. Doubly-robust methods (combines 1 and 2)
  # The 0.9 multiplier is arbitrary and would produce misleading results.
  # See the main recipe's pseudocode (Step 4) for the correct structure.
  ```

---

### Issue 4: `_summarize_state` Indexes Into Normalized State But Displays as Raw Values

- **File:** `chapter15.10-python-example.md`
- **Location:** Step 5 (`_summarize_state`)
- **Severity:** NOTE (pedagogical gap)
- **Description:** The function `_summarize_state(state)` formats `state[0]` as a percentage (e.g., "85%") and `state[11]` as an integer count. But the state vector from `build_state_vector` is min-max normalized to [0,1]. So `state[0]` being 0.7 doesn't mean 70% occupancy; it means 70% of the normalized range between `feat_min` and `feat_max`. For `icu_occupancy` with min=0.0 and max=1.2, a raw value of 0.9 (90% occupied) normalizes to 0.75. Displaying 0.75 as "75%" would confuse the bed coordinator.

  Similarly, `int(state[11])` where state[11] is `ed_boarders_waiting` normalized between 0 and 15 will always be 0 or 1 (since the normalized value is 0-1). The display would show "0" or "1" boarders regardless of actual count.
- **Suggested fix:** Add a comment noting that production would use the raw (unnormalized) state for display:
  ```python
  # NOTE: In production, the dashboard displays raw values from the state
  # store, not the normalized values used by the policy network. This
  # function is simplified for illustration. A real implementation would
  # query the raw state alongside the normalized policy input.
  ```

---

### Issue 5: `generate_recommendation` Creates Unused HospitalSimulator Instance

- **File:** `chapter15.10-python-example.md`
- **Location:** Step 5 (`generate_recommendation`), line `sim = HospitalSimulator()`
- **Severity:** NOTE (confusing pattern)
- **Description:** The function creates a `HospitalSimulator()` instance with a comment saying it's "temporary, just for constraint checking structure" but then never uses it. The feasibility mask is set to all ones (`np.ones(NUM_ACTIONS)`) with a comment saying "In production, you'd check actual constraints against real state." This leaves a dead code object that confuses readers about how constraint checking connects to the inference path. A reader might think you need a simulator running in production for constraint checking.
- **Suggested fix:** Remove the unused simulator instantiation and clarify:
  ```python
  # In production, the feasibility mask comes from a constraint checker
  # that evaluates current hospital state against hard limits (capacity,
  # staffing ratios, isolation requirements). The constraint checker does
  # NOT use the training simulator; it queries real operational state.
  feasible_mask = np.ones(NUM_ACTIONS)  # placeholder: all actions feasible
  ```

---

### Issue 6: `_generate_explanation` References Normalized Feature Indices Without Context

- **File:** `chapter15.10-python-example.md`
- **Location:** Step 5 (`_generate_explanation`)
- **Severity:** NOTE (pedagogical gap)
- **Description:** The function uses `state[0]` for ICU occupancy and `state[11]` for ED boarders. These magic indices correspond to the STATE_FEATURES ordering, but there's no mapping or constant that makes this obvious. A reader modifying STATE_FEATURES (adding a feature, reordering) would silently break the explanation function. In a teaching context, using named constants or a comment mapping would help readers understand the coupling.
- **Suggested fix:** Add a brief mapping comment:
  ```python
  # Feature indices (from STATE_FEATURES ordering):
  # 0 = icu_occupancy, 11 = ed_boarders_waiting
  icu_occ = state[0] if len(state) > 0 else 0
  ```

---
