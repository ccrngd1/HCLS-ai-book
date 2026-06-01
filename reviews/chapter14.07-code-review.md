# Code Review: Recipe 14.7 - OR Case Sequencing

## Summary

The Python companion is a well-structured teaching implementation of OR case sequencing using Google OR-Tools CP-SAT solver. The code correctly demonstrates optional interval variables for room assignment, no-overlap constraints, equipment conflict resolution via disjunctive ordering, staff availability windows, and makespan minimization. DynamoDB storage uses proper Decimal conversion via `json.loads(json.dumps(...), parse_float=Decimal)`. The infeasible case returns None with clear logging rather than crashing. Comments are excellent throughout, explaining both the optimization concepts and the clinical reasoning. The logical flow builds progressively from data modeling through constraint formulation to solution extraction and replanning.

---

## Verdict: **PASS**

---

## Findings

### Finding 1: Turnover time between cases is not actually enforced

- **Severity:** WARNING
- **Location:** Python companion, Step 2, `build_or_sequencing_model()`, "No overlap within each room" section
- **What's wrong:** The code comment says "Since we included buffer in duration, this ensures minimum spacing" but this conflates two different concepts. The `buffer_min` field represents duration uncertainty padding (the ~90th percentile of how long the case itself might take), NOT turnover time between cases. The `TURNOVER_TIMES` dict and `get_turnover_time()` function are defined but never actually used in the constraint model.

  The `AddNoOverlap` constraint only prevents temporal overlap of the intervals. It does not enforce a gap between them. Two cases could be scheduled back-to-back (end of case A = start of case B) with zero turnover time. The `buffer_min` padding makes this less likely to cause real-world problems (there's slack in each case's interval), but it doesn't guarantee the 25-40 minute turnover that the constants define.

  The main recipe's pseudocode explicitly includes `turnover_time(case_a, case_b)` in the no-overlap constraint formulation.
- **Impact:** A reader implementing this pattern would get schedules with insufficient turnover time between cases. The `get_turnover_time()` function and `TURNOVER_TIMES` dict are dead code, which is confusing pedagogically.
- **Fix:** Either inflate each interval's size by the minimum turnover time (simple approach noted in the comment but not implemented), or add pairwise ordering constraints with turnover gaps similar to the equipment conflict pattern. The simplest fix for a teaching example:
  ```python
  # Inflate duration to include minimum turnover after the case.
  duration = case["expected_duration_min"] + case["buffer_min"] + DEFAULT_TURNOVER_MINUTES
  ```
  And note in a comment that variable turnover (based on contamination class) would require pairwise constraints in production.

### Finding 2: `replan_schedule` adds `earliest_start` constraint AFTER building the model, but the model's start variable domain already constrains the range

- **Severity:** WARNING
- **Location:** Python companion, Step 6, `replan_schedule()`, lines adding earliest_start constraints
- **What's wrong:** The function first builds the model (which creates start variables with domain `[0, BLOCK_DURATION_MINUTES - duration]`), then adds `earliest_start` constraints:
  ```python
  model, case_vars = build_or_sequencing_model(remaining_cases, rooms, staff)
  for case in remaining_cases:
      earliest = case.get("constraints", {}).get("earliest_start", 0)
      if earliest > 0:
          case_id = case["case_id"]
          if case_id in case_vars:
              model.add(case_vars[case_id]["start"] >= earliest)
  ```
  This works correctly because CP-SAT allows adding constraints that further restrict variable domains after creation. However, the `build_or_sequencing_model` function also reads `case["constraints"]` for `first_case` and `before_noon`. Since `replan_schedule` mutates the case dicts by adding `earliest_start` before calling `build_or_sequencing_model`, but then adds the constraint AFTER the model is built, there's an inconsistency in where constraints are applied. The `first_case` constraint (which sets `start == 0`) would conflict with `earliest_start > 0` if both are present on the same case.

  The code guards against this with `if not case["constraints"].get("first_case")`, so it won't set `earliest_start` on first-case cases. But the pattern is fragile and confusing for a reader.
- **Impact:** The code produces correct results for the sample data. But the split constraint application (some in `build_or_sequencing_model`, some after) is a misleading pattern. A reader extending this might add constraints in the wrong place.
- **Fix:** Move the `earliest_start` handling into `build_or_sequencing_model` alongside the other constraint checks:
  ```python
  # In build_or_sequencing_model, after the "before_noon" block:
  for case in cases:
      earliest = case.get("constraints", {}).get("earliest_start", 0)
      if earliest > 0:
          case_id = case["case_id"]
          model.add(case_vars[case_id]["start"] >= earliest)
  ```

### Finding 3: `model.proto.variables.__len__()` is not the idiomatic way to get model statistics

- **Severity:** NOTE
- **Location:** Python companion, "Putting It All Together" section
- **What's wrong:** The code uses:
  ```python
  model.proto.variables.__len__(),
  model.proto.constraints.__len__(),
  ```
  The `__len__` dunder method should be called via `len()`, not directly. More importantly, accessing `model.proto` exposes the internal protobuf representation, which is an implementation detail of OR-Tools. The idiomatic approach would be `len(model.proto.variables)` or simply logging the number of cases and rooms (which is what the reader actually cares about).
- **Impact:** The code works, but teaches a non-idiomatic Python pattern and couples to OR-Tools internals.
- **Fix:** Use `len(model.proto.variables)` and `len(model.proto.constraints)`, or better yet, just log the problem dimensions:
  ```python
  logger.info("  %d cases, %d rooms, %d staff constraints", len(cases), len(rooms), len(staff))
  ```

### Finding 4: `PENALTY_WEIGHTS` dict is defined but never used

- **Severity:** NOTE
- **Location:** Python companion, Configuration and Constants section
- **What's wrong:** The `PENALTY_WEIGHTS` dictionary defines weights for overtime, idle gaps, preference violations, and late starts. However, the objective function in `build_or_sequencing_model` only minimizes makespan. None of the penalty weights are referenced anywhere in the code.
- **Impact:** A reader sees these constants and expects them to be used in the objective function. Their presence without usage is confusing. The main recipe's pseudocode uses a weighted multi-objective, so the Python companion appears incomplete.
- **Fix:** Either remove `PENALTY_WEIGHTS` (since the simplified objective is just makespan), or add a comment explaining that the full weighted objective is described in the main recipe and this example uses makespan as a simpler proxy. The current comment in the objective section partially explains this but doesn't reference the unused constants.

### Finding 5: `store_schedule` comment mentions conditional write but doesn't implement it

- **Severity:** NOTE
- **Location:** Python companion, Step 5, `store_schedule()`
- **What's wrong:** The comment says:
  ```python
  # Conditional write: only succeed if this is the first schedule for today
  # or if we're explicitly replanning (handled by incrementing version).
  table.put_item(Item=record)
  ```
  But the actual `put_item` call has no `ConditionExpression`. The comment describes a production pattern (optimistic locking via version number) but the code doesn't implement it.
- **Impact:** Misleading comment. A reader might think conditional writes are happening when they're not. The Gap to Production section mentions concurrency control, so this is a known simplification, but the inline comment should match the code.
- **Fix:** Either add the condition expression:
  ```python
  table.put_item(
      Item=record,
      ConditionExpression="attribute_not_exists(schedule_date) OR version < :v",
      ExpressionAttributeValues={":v": record["version"]},
  )
  ```
  Or change the comment to: `# In production, use a ConditionExpression for optimistic locking. Simplified here.`

---

## Pseudocode-to-Python Consistency

| Main Recipe Pseudocode Step | Python Implementation | Consistent? |
|---|---|---|
| `enrich_case_list(raw_cases)` | Hardcoded `CASES` list with inline enrichment | Yes (simplified, noted) |
| `build_constraint_model(cases, rooms, staff)` | `build_or_sequencing_model()` | Mostly yes, but missing turnover time in no-overlap (Finding 1) |
| `solve_schedule(model, mode)` | `solve_schedule()` | Yes |
| `handle_or_event(event)` | `replan_schedule()` | Yes (event routing simplified) |
| `publish_schedule(schedule)` | `store_schedule()` + logger output | Yes (notification simplified) |

The pseudocode's turnover time in the no-overlap constraint is the most significant gap. The Python companion defines the turnover infrastructure (`get_turnover_time`, `TURNOVER_TIMES`) but doesn't wire it into the model.

---

## AWS SDK Accuracy

- **DynamoDB `put_item()`:** Correct usage via `table.put_item(Item=record)`. ✓
- **Float-to-Decimal conversion:** Uses `json.loads(json.dumps(schedule["rooms"]), parse_float=Decimal)` which correctly converts all nested floats. Also uses `Decimal(str(...))` for top-level fields. ✓
- **boto3 Config for retries:** Correct usage of `Config(retries={"max_attempts": 3, "mode": "adaptive"})`. ✓
- **DynamoDB resource:** Uses `boto3.resource("dynamodb")` which is appropriate for the Table abstraction. ✓
- **S3 paths:** No S3 operations. N/A.
- **No leading slashes in paths:** N/A (no S3 usage).

---

## Comment Quality

Comments are strong throughout:
- Explain *why* CP-SAT's optional intervals are the key trick for room assignment (not just what they do)
- Explain *why* buffer_min exists (90th percentile duration padding)
- Explain *why* equipment conflicts use disjunctive ordering (either A before B or B before A)
- Explain *why* first-case preferences are treated as hard constraints ("surgeons tend to revolt")
- Explain *why* 8 search workers is a good default (4-core machine parallelism)
- The `get_turnover_time()` function has clear docstring explaining contamination class transitions
- The Gap to Production section is thorough and covers duration prediction, EHR integration, concurrency, audit trails, VPC, and IAM least-privilege

---

## Overall Assessment

This is a solid teaching implementation that correctly demonstrates constraint programming for surgical scheduling. The OR-Tools CP-SAT formulation is sound: optional interval variables for room assignment, `AddNoOverlap` for room exclusivity, disjunctive constraints for shared equipment, and conditional constraints for staff availability windows. The infeasible case is handled gracefully. DynamoDB integration uses correct Decimal handling throughout.

The primary gap (Finding 1: turnover time not enforced) is a WARNING because it means the defined `TURNOVER_TIMES` infrastructure is dead code and the model doesn't match the main recipe's pseudocode. However, the buffer padding provides implicit spacing, the code runs correctly on the sample data, and the Gap to Production section explicitly calls out turnover modeling as a simplification. Combined with Finding 2 (split constraint application in replanning), there are 2 WARNINGs total, which is within the PASS threshold of 3 or fewer.
