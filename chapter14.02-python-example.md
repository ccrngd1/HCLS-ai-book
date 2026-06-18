# Recipe 14.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 14.2. It shows one way you could translate patient-provider assignment concepts into working Python code using PuLP (an open-source linear programming library). It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to your panel management system on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need a few Python packages:

```bash
pip install pulp boto3
```

PuLP is a modeling library for linear and mixed-integer programming. It ships with the CBC solver (open-source, no license required), which handles assignment problems with hundreds of patients and dozens of providers in seconds.

Your environment needs AWS credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, and `dynamodb:GetItem`.

---

## Config and Constants

Before we get to the optimization logic, here's the configuration that defines the problem. These constants represent a typical primary care practice with multiple providers. In production, you'd pull these from your EHR panel management data rather than hardcoding them.

```python
import json
from dataclasses import dataclass
from decimal import Decimal

# Provider definitions: who's available and what's their capacity?
# Panel size targets come from your medical director. They vary by provider type,
# FTE status, and whether the provider is ramping up (new hire) or winding down (retiring).

PROVIDERS = {
    "DR-CHEN": {
        "name": "Dr. Sarah Chen",
        "specialty": "family_medicine",
        "panel_target": 1800,      # ideal active patient count
        "panel_max": 2000,         # hard cap: beyond this, quality suffers
        "panel_current": 1650,     # how many patients they have today
        "fte": 1.0,               # full-time
        "accepting_new": True,
        "languages": ["en", "zh"],
        "gender": "F",
    },
    "DR-MARTINEZ": {
        "name": "Dr. Carlos Martinez",
        "specialty": "family_medicine",
        "panel_target": 1800,
        "panel_max": 2000,
        "panel_current": 1920,     # over target, approaching max
        "fte": 1.0,
        "accepting_new": False,    # panel is nearly full
        "languages": ["en", "es"],
        "gender": "M",
    },
    "DR-PATEL": {
        "name": "Dr. Priya Patel",
        "specialty": "internal_medicine",
        "panel_target": 1600,      # internists often have smaller panels (sicker patients)
        "panel_max": 1800,
        "panel_current": 1200,     # new provider, ramping up
        "fte": 1.0,
        "accepting_new": True,
        "languages": ["en", "hi", "gu"],
        "gender": "F",
    },
    "NP-JOHNSON": {
        "name": "Taylor Johnson, NP",
        "specialty": "family_medicine",
        "panel_target": 1200,      # NPs typically have smaller panels
        "panel_max": 1400,
        "panel_current": 950,
        "fte": 0.8,               # 4 days per week
        "accepting_new": True,
        "languages": ["en"],
        "gender": "NB",
    },
}

# Patients needing assignment. In production, this comes from a query:
# "patients without a PCP" or "patients whose PCP left the practice."
# Each patient has attributes that influence the match quality.

PATIENTS_TO_ASSIGN = [
    {
        "patient_id": "PAT-001",
        "age": 72,
        "conditions": ["diabetes", "hypertension", "ckd"],
        "complexity": "high",
        "language_preference": "en",
        "gender_preference": None,       # no preference
        "previous_provider": "DR-SMITH", # left the practice
        "visit_frequency": "monthly",    # how often they come in
    },
    {
        "patient_id": "PAT-002",
        "age": 34,
        "conditions": [],
        "complexity": "low",
        "language_preference": "es",
        "gender_preference": "F",
        "previous_provider": None,       # new to practice
        "visit_frequency": "annual",
    },
    {
        "patient_id": "PAT-003",
        "age": 55,
        "conditions": ["diabetes", "depression"],
        "complexity": "medium",
        "language_preference": "zh",
        "gender_preference": None,
        "previous_provider": "DR-SMITH",
        "visit_frequency": "quarterly",
    },
    {
        "patient_id": "PAT-004",
        "age": 28,
        "conditions": ["asthma"],
        "complexity": "low",
        "language_preference": "en",
        "gender_preference": None,
        "previous_provider": None,
        "visit_frequency": "biannual",
    },
    {
        "patient_id": "PAT-005",
        "age": 65,
        "conditions": ["chf", "copd", "diabetes"],
        "complexity": "high",
        "language_preference": "hi",
        "gender_preference": "F",
        "previous_provider": "DR-SMITH",
        "visit_frequency": "biweekly",
    },
    {
        "patient_id": "PAT-006",
        "age": 8,
        "conditions": [],
        "complexity": "low",
        "language_preference": "en",
        "gender_preference": None,
        "previous_provider": None,
        "visit_frequency": "annual",
    },
    {
        "patient_id": "PAT-007",
        "age": 45,
        "conditions": ["hypertension"],
        "complexity": "medium",
        "language_preference": "gu",
        "gender_preference": "F",
        "previous_provider": None,
        "visit_frequency": "quarterly",
    },
]

# Scoring weights: how much does each factor matter in the assignment?
# These are tunable. Your medical director and ops team should agree on these.
# Higher weight = more influence on the assignment decision.

WEIGHTS = {
    "language_match": 30,        # speaking the patient's language is huge
    "gender_preference": 20,     # respecting stated preference
    "complexity_match": 25,      # complex patients to experienced providers
    "panel_balance": 15,         # distribute evenly relative to targets
    "continuity_bonus": 10,      # keep patients with same-team providers if possible
}

# Continuity mapping: when a provider leaves, which remaining providers
# were on the same care team? Patients of DR-SMITH get a small bonus
# for being assigned to someone who already knows their case from huddles.
CONTINUITY_MAP = {
    "DR-SMITH": ["DR-CHEN", "DR-MARTINEZ"],  # Smith's care team partners
}

# Visit frequency weights: high-frequency patients consume more panel capacity.
# A patient who comes monthly uses roughly 12x the appointment slots of an annual patient.
FREQUENCY_WEIGHTS = {
    "biweekly": 26,
    "monthly": 12,
    "quarterly": 4,
    "biannual": 2,
    "annual": 1,
}
```

---

## Step 1: Compute Preference Scores

*The pseudocode calls this `compute_preferences(patients, providers)`. It builds a score matrix where each cell represents how good a particular patient-provider pairing would be. Higher scores mean better matches.*

```python
def compute_preference_score(patient: dict, provider_id: str, provider: dict) -> float:
    """
    Compute a match quality score for a single patient-provider pair.

    This is the heart of the assignment problem. The score combines multiple
    factors (language, gender preference, clinical complexity, panel balance)
    into a single number that the optimizer can maximize.

    The score is NOT a probability. It's a weighted sum of match indicators.
    A perfect match might score 100; a terrible match might score 0 or negative.

    Args:
        patient: Patient record with attributes
        provider_id: Provider identifier
        provider: Provider record with capacity and attributes

    Returns:
        Float score. Higher = better match.
    """
    score = 0.0

    # --- Language match ---
    # If the patient has a language preference and the provider speaks it,
    # that's a major quality signal. Concordant language improves outcomes,
    # reduces interpreter costs, and increases patient satisfaction.
    if patient["language_preference"]:
        if patient["language_preference"] in provider["languages"]:
            score += WEIGHTS["language_match"]
        # No penalty for mismatch; just no bonus. Every practice has interpreter services.

    # --- Gender preference ---
    # If the patient stated a gender preference and the provider matches, bonus.
    # If they stated a preference and it doesn't match, penalty (we'd rather not assign here).
    if patient["gender_preference"]:
        if patient["gender_preference"] == provider["gender"]:
            score += WEIGHTS["gender_preference"]
        else:
            score -= WEIGHTS["gender_preference"] * 0.5  # soft penalty, not a hard block

    # --- Complexity match ---
    # High-complexity patients (multiple chronic conditions, frequent visits) should
    # go to experienced physicians rather than new NPs still building their practice.
    # This isn't about capability; it's about panel composition balance.
    if patient["complexity"] == "high":
        if provider["specialty"] == "internal_medicine":
            score += WEIGHTS["complexity_match"]  # internists handle complex patients well
        elif provider["specialty"] == "family_medicine" and provider["fte"] == 1.0:
            score += WEIGHTS["complexity_match"] * 0.7  # full-time FM docs can handle it
        else:
            score += WEIGHTS["complexity_match"] * 0.3  # part-time or NP: less ideal for complex
    elif patient["complexity"] == "low":
        # Low-complexity patients are great for providers ramping up their panels
        remaining_capacity = provider["panel_max"] - provider["panel_current"]
        if remaining_capacity > 400:  # lots of room
            score += WEIGHTS["complexity_match"] * 0.5

    # --- Panel balance ---
    # Prefer providers who are further from their target. This naturally distributes
    # patients toward providers with more capacity.
    remaining_to_target = provider["panel_target"] - provider["panel_current"]
    if remaining_to_target > 0:
        # Provider is below target: good candidate for new patients
        # Scale the bonus by how far below target they are (normalized to 0-1)
        balance_ratio = min(1.0, remaining_to_target / 500)
        score += WEIGHTS["panel_balance"] * balance_ratio
    else:
        # Provider is at or above target: penalize proportionally
        over_ratio = min(1.0, abs(remaining_to_target) / 200)
        score -= WEIGHTS["panel_balance"] * over_ratio

    # --- Continuity bonus ---
    # If the patient's previous provider left and this provider was on the same
    # care team, there's a continuity benefit. They've discussed this patient in
    # huddles, they know the care plan, the transition is smoother.
    if patient["previous_provider"] and patient["previous_provider"] in CONTINUITY_MAP:
        if provider_id in CONTINUITY_MAP[patient["previous_provider"]]:
            score += WEIGHTS["continuity_bonus"]

    return score

def build_preference_matrix(patients: list, providers: dict) -> dict:
    """
    Build the full preference score matrix for all patient-provider pairs.

    Returns a nested dict: scores[patient_id][provider_id] = score
    """
    scores = {}
    for patient in patients:
        pid = patient["patient_id"]
        scores[pid] = {}
        for prov_id, prov_data in providers.items():
            scores[pid][prov_id] = compute_preference_score(patient, prov_id, prov_data)

    return scores
```

---

## Step 2: Formulate and Solve the Assignment Problem

*The pseudocode calls this `solve_assignment(preferences, constraints)`. We use PuLP to formulate a binary integer program where each decision variable represents whether a specific patient is assigned to a specific provider.*

```python
import pulp

def solve_assignment(
    patients: list,
    providers: dict,
    preference_scores: dict,
) -> dict:
    """
    Formulate and solve the patient-provider assignment optimization.

    This is a variant of the assignment problem (a classic in operations research).
    Each patient must be assigned to exactly one provider. The objective is to
    maximize total preference score (match quality) subject to capacity constraints.

    Decision variables:
        x[i][j] = 1 if patient i is assigned to provider j, 0 otherwise

    Objective:
        Maximize sum of (preference_score[i][j] * x[i][j]) for all i, j

    Constraints:
        1. Each patient assigned to exactly one provider
        2. No provider exceeds their panel maximum
        3. Providers not accepting new patients get zero new assignments
        4. Weighted capacity: high-frequency patients count more against panel limits

    Args:
        patients: List of patient records
        providers: Dict of provider records
        preference_scores: Nested dict of scores[patient_id][provider_id]

    Returns:
        Dict with assignments, objective value, and solver status.
    """

    patient_ids = [p["patient_id"] for p in patients]
    provider_ids = list(providers.keys())

    # Create the optimization model
    model = pulp.LpProblem("PatientProviderAssignment", pulp.LpMaximize)

    # --- Decision Variables ---
    # x[i][j] = 1 if patient i is assigned to provider j, 0 otherwise.
    # These are binary (0 or 1) because a patient can't be "half assigned" to someone.
    x = {}
    for pid in patient_ids:
        x[pid] = {}
        for prov_id in provider_ids:
            x[pid][prov_id] = pulp.LpVariable(
                f"assign_{pid}_{prov_id}",
                cat="Binary",  # 0 or 1 only
            )

    # --- Objective Function ---
    # Maximize total match quality across all assignments.
    # This is the sum of preference scores for the assignments we actually make.
    model += pulp.lpSum(
        preference_scores[pid][prov_id] * x[pid][prov_id]
        for pid in patient_ids
        for prov_id in provider_ids
    ), "TotalMatchQuality"

    # --- Constraint 1: Each patient assigned to exactly one provider ---
    # No patient left unassigned, no patient assigned to multiple providers.
    for pid in patient_ids:
        model += (
            pulp.lpSum(x[pid][prov_id] for prov_id in provider_ids) == 1,
            f"one_provider_{pid}",
        )

    # --- Constraint 2: Panel capacity limits ---
    # The number of new patients assigned to each provider, weighted by visit
    # frequency, must not push them over their panel maximum.
    # We use frequency weights because a biweekly patient consumes far more
    # appointment capacity than an annual wellness visit patient.
    patient_freq_map = {p["patient_id"]: p["visit_frequency"] for p in patients}

    for prov_id, prov_data in providers.items():
        remaining_capacity = prov_data["panel_max"] - prov_data["panel_current"]

        # Weighted new patient load for this provider
        # Each assigned patient contributes their frequency weight to the load.
        weighted_load = pulp.lpSum(
            FREQUENCY_WEIGHTS.get(patient_freq_map[pid], 1) * x[pid][prov_id]
            for pid in patient_ids
        )

        # The weighted load of new assignments must fit within remaining capacity.
        # Each patient's frequency weight is measured in annual visits.
        # Remaining capacity is in patient slots. We multiply remaining capacity
        # by the average frequency weight to convert both sides to the same unit
        # (weighted visit equivalents).
        avg_freq_weight = sum(FREQUENCY_WEIGHTS.values()) / len(FREQUENCY_WEIGHTS)
        model += (
            weighted_load <= remaining_capacity * avg_freq_weight,
            f"capacity_{prov_id}",
        )

    # --- Constraint 3: Not accepting new patients ---
    # If a provider has closed their panel, they get zero new assignments.
    for prov_id, prov_data in providers.items():
        if not prov_data["accepting_new"]:
            for pid in patient_ids:
                model += (
                    x[pid][prov_id] == 0,
                    f"closed_panel_{prov_id}_{pid}",
                )

    # --- Solve ---
    solver = pulp.PULP_CBC_CMD(msg=0)  # suppress solver output
    model.solve(solver)

    # --- Extract Results ---
    if model.status != pulp.constants.LpStatusOptimal:
        raise RuntimeError(
            f"Solver did not find optimal solution. Status: {pulp.LpStatus[model.status]}"
        )

    # Build the assignment map
    assignments = {}
    for pid in patient_ids:
        for prov_id in provider_ids:
            if pulp.value(x[pid][prov_id]) > 0.5:  # binary, so > 0.5 means assigned
                assignments[pid] = prov_id
                break

    return {
        "assignments": assignments,
        "objective_value": round(pulp.value(model.objective), 2),
        "solver_status": pulp.LpStatus[model.status],
    }
```

---

## Step 3: Interpret and Validate Results

*The pseudocode calls this `validate_assignments(solution, patients, providers)`. After the solver runs, we need to verify the solution makes clinical sense and produce human-readable output for the panel management team.*

```python
def interpret_assignments(
    assignments: dict,
    patients: list,
    providers: dict,
    preference_scores: dict,
) -> list:
    """
    Convert raw solver output into human-readable assignment records
    with explanations of why each match was made.

    The panel management team needs to review these before they go live.
    They want to see: who got assigned where, why, and whether any assignments
    look questionable.

    Returns:
        List of assignment records with patient info, provider info, score,
        and a plain-English rationale.
    """
    patient_map = {p["patient_id"]: p for p in patients}
    results = []

    for pid, prov_id in assignments.items():
        patient = patient_map[pid]
        provider = providers[prov_id]
        score = preference_scores[pid][prov_id]

        # Build a rationale explaining the key factors in this assignment
        rationale = []

        if patient["language_preference"] in provider["languages"]:
            rationale.append(
                f"Language match: provider speaks {patient['language_preference']}"
            )

        if patient["gender_preference"] and patient["gender_preference"] == provider["gender"]:
            rationale.append("Gender preference matched")

        remaining = provider["panel_target"] - provider["panel_current"]
        if remaining > 0:
            rationale.append(f"Provider has capacity ({remaining} below target)")

        if patient["previous_provider"] and patient["previous_provider"] in CONTINUITY_MAP:
            if prov_id in CONTINUITY_MAP[patient["previous_provider"]]:
                rationale.append("Care team continuity with previous provider")

        if patient["complexity"] == "high" and provider["specialty"] == "internal_medicine":
            rationale.append("Complex patient matched to internist")

        results.append({
            "patient_id": pid,
            "patient_age": patient["age"],
            "patient_complexity": patient["complexity"],
            "assigned_provider": prov_id,
            "provider_name": provider["name"],
            "match_score": round(score, 1),
            "rationale": rationale if rationale else ["Best available match given constraints"],
        })

    return results

def validate_assignments(assignments: dict, patients: list, providers: dict) -> dict:
    """
    Run validation checks on the proposed assignments.

    Checks for:
    - All patients assigned
    - No provider over capacity
    - No assignments to closed panels
    - Distribution fairness across providers

    Returns:
        Validation report with pass/fail status and any warnings.
    """
    patient_map = {p["patient_id"]: p for p in patients}
    warnings = []
    errors = []

    # Check 1: All patients assigned
    unassigned = [p["patient_id"] for p in patients if p["patient_id"] not in assignments]
    if unassigned:
        errors.append(f"Unassigned patients: {unassigned}")

    # Check 2: No assignments to closed panels
    for pid, prov_id in assignments.items():
        if not providers[prov_id]["accepting_new"]:
            errors.append(f"{pid} assigned to {prov_id} which is not accepting new patients")

    # Check 3: Post-assignment panel sizes
    new_counts = {}
    for prov_id in providers:
        new_counts[prov_id] = 0
    for pid, prov_id in assignments.items():
        new_counts[prov_id] += 1

    for prov_id, count in new_counts.items():
        new_total = providers[prov_id]["panel_current"] + count
        if new_total > providers[prov_id]["panel_max"]:
            errors.append(
                f"{prov_id} would exceed panel max: {new_total} > {providers[prov_id]['panel_max']}"
            )
        elif new_total > providers[prov_id]["panel_target"]:
            warnings.append(
                f"{prov_id} would exceed target: {new_total} > {providers[prov_id]['panel_target']}"
            )

    # Check 4: Distribution fairness
    # Flag if any single provider gets more than 60% of the new patients
    total_assigned = len(assignments)
    for prov_id, count in new_counts.items():
        if total_assigned > 0 and count / total_assigned > 0.6:
            warnings.append(
                f"{prov_id} receiving {count}/{total_assigned} "
                f"({count/total_assigned*100:.0f}%) of new assignments"
            )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "distribution": new_counts,
    }
```

---

## Step 4: Store Results

*The pseudocode calls this `store_assignments(results)`. It writes the proposed assignments to DynamoDB for the panel management team to review and approve.*

```python
import datetime
from datetime import timezone
import boto3
from botocore.config import Config

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

TABLE_NAME = "patient-provider-assignments"

def store_assignments(
    assignment_records: list,
    validation: dict,
    objective_value: float,
) -> dict:
    """
    Write proposed assignments to DynamoDB for human review.

    Each assignment gets its own record with status='proposed'. The panel
    management team reviews these in a dashboard and either approves (triggering
    the EHR update) or overrides with a manual assignment.

    Args:
        assignment_records: List of interpreted assignment records
        validation: Validation report
        objective_value: Solver's objective function value

    Returns:
        Metadata about the stored batch.
    """
    table = dynamodb.Table(TABLE_NAME)
    timestamp = datetime.datetime.now(timezone.utc).isoformat()
    batch_id = f"BATCH-{datetime.datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    with table.batch_writer() as batch:
        for record in assignment_records:
            item = {
                "pk": record["patient_id"],
                "sk": f"ASSIGNMENT#{batch_id}",
                "batch_id": batch_id,
                "patient_id": record["patient_id"],
                "assigned_provider": record["assigned_provider"],
                "provider_name": record["provider_name"],
                "match_score": Decimal(str(record["match_score"])),
                "rationale": record["rationale"],
                "patient_complexity": record["patient_complexity"],
                "status": "proposed",  # awaiting human review
                "created_at": timestamp,
                "objective_value": Decimal(str(objective_value)),
                "validation_passed": validation["valid"],
            }
            batch.put_item(Item=item)

    return {
        "batch_id": batch_id,
        "records_written": len(assignment_records),
        "timestamp": timestamp,
    }
```

---

## Full Pipeline

Here's the full pipeline assembled into a single callable function. This is what your Step Functions workflow or scheduled Lambda would invoke when new patients need assignment.

```python
def run_assignment_pipeline() -> dict:
    """
    Run the complete patient-provider assignment pipeline.

    1. Compute preference scores for all patient-provider pairs
    2. Solve the optimization model
    3. Interpret and validate results
    4. Store proposed assignments for human review

    Returns:
        Full results including assignments, validation, and storage metadata.
    """

    print("=== Patient-Provider Assignment Optimization ===\n")

    # Step 1: Build the preference matrix
    print("Step 1: Computing preference scores...")
    scores = build_preference_matrix(PATIENTS_TO_ASSIGN, PROVIDERS)

    # Show a sample of the score matrix
    print(f"  Score matrix: {len(PATIENTS_TO_ASSIGN)} patients x {len(PROVIDERS)} providers")
    sample_pid = PATIENTS_TO_ASSIGN[0]["patient_id"]
    print(f"  Sample scores for {sample_pid}:")
    for prov_id, score in scores[sample_pid].items():
        print(f"    {prov_id}: {score:.1f}")

    # Step 2: Solve the assignment problem
    print("\nStep 2: Solving assignment optimization...")
    solution = solve_assignment(PATIENTS_TO_ASSIGN, PROVIDERS, scores)
    print(f"  Solver status: {solution['solver_status']}")
    print(f"  Objective value: {solution['objective_value']}")
    print(f"  Assignments: {solution['assignments']}")

    # Step 3: Interpret and validate
    print("\nStep 3: Interpreting and validating assignments...")
    records = interpret_assignments(
        solution["assignments"], PATIENTS_TO_ASSIGN, PROVIDERS, scores
    )
    validation = validate_assignments(solution["assignments"], PATIENTS_TO_ASSIGN, PROVIDERS)

    print(f"  Validation passed: {validation['valid']}")
    if validation["warnings"]:
        for w in validation["warnings"]:
            print(f"  WARNING: {w}")
    if validation["errors"]:
        for e in validation["errors"]:
            print(f"  ERROR: {e}")

    print(f"\n  Distribution across providers:")
    for prov_id, count in validation["distribution"].items():
        print(f"    {prov_id}: {count} new patients")

    print("\n  Assignment details:")
    for rec in records:
        print(f"    {rec['patient_id']} -> {rec['provider_name']} "
              f"(score: {rec['match_score']}, rationale: {'; '.join(rec['rationale'])})")

    # Step 4: Store results
    print("\nStep 4: Storing proposed assignments...")
    try:
        storage = store_assignments(records, validation, solution["objective_value"])
        print(f"  Batch ID: {storage['batch_id']}")
        print(f"  Records written: {storage['records_written']}")
    except Exception as e:
        print(f"  Skipping DynamoDB store (table may not exist): {e}")
        print("  In production, this writes to DynamoDB for the review workflow.")
        storage = {"batch_id": "LOCAL-RUN", "records_written": 0}

    print("\nDone. Assignments ready for panel management team review.")

    return {
        "assignments": records,
        "validation": validation,
        "objective_value": solution["objective_value"],
        "storage": storage,
    }

# Run the pipeline
if __name__ == "__main__":
    result = run_assignment_pipeline()
    print("\n\nFull output:")
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example works. Run it and it will produce optimal patient-provider assignments with validation and rationale. But there's meaningful distance between "works in a script" and "runs weekly managing panels for a 50-provider practice." Here's where that gap lives:

**Real data integration.** This example uses hardcoded patient and provider data. A production system pulls from your EHR's panel management tables (Epic's Empanelment module, Cerner's Panel Management, or your custom attribution logic). That extraction involves complex SQL against scheduling, encounter, and demographics tables. You also need real-time panel counts, not stale snapshots.

**Scale considerations.** Seven patients and four providers is trivial for CBC. A real batch might be 500 patients (from a departing provider's panel) assigned across 30 providers. The problem is still tractable for CBC at that scale (binary integer programs with ~15,000 variables solve in seconds), but you should test with realistic sizes. If you hit thousands of patients and hundreds of providers, consider decomposition strategies or the HiGHS solver.

**Preference model sophistication.** The scoring function here uses simple rules. A production system might incorporate: historical visit patterns (does this patient prefer morning appointments? does this provider have morning availability?), geographic proximity (drive time from patient home to provider's clinic location), insurance network matching (is this provider in-network for this patient's plan?), and clinical program enrollment (is the patient in a diabetes management program that requires a specific provider type?).

**Incremental vs. batch assignment.** This example runs as a batch: "here are 7 patients, assign them all at once." In practice, you need both batch (provider departure, panel rebalancing) and incremental (single new patient calls to schedule, assign them a PCP on the spot). The incremental case is simpler (one patient, pick the best provider) but must respect the same constraints.

**Human override workflow.** The panel management team will override some assignments. Your system needs to handle: approvals, rejections with reason codes, manual reassignments, and partial approvals (approve 45 of 50, override 5). The DynamoDB records need status transitions: proposed, approved, rejected, overridden. Step Functions orchestrates this with a human approval task.

**EHR integration.** After approval, the assignment must be written back to the EHR. This typically means an HL7 FHIR CareTeam resource update or a proprietary API call (Epic's SetPrimaryProvider, for example). These integrations are fragile, rate-limited, and require careful error handling. A failed EHR write should not leave your assignment table and the EHR out of sync.

**Error handling and retries.** The DynamoDB writes have no retry logic for throttling, no conditional writes to prevent duplicate batches, and no dead-letter queue for failed records. Production code wraps every external call in try/except with exponential backoff and alerts on repeated failures.

**IAM least-privilege.** The IAM role for this pipeline should have exactly: `dynamodb:PutItem` and `dynamodb:BatchWriteItem` on the assignments table, `dynamodb:GetItem` for reading current panel data, and `s3:GetObject` if you're reading patient/provider data from S3. Not `dynamodb:*`.

**VPC and encryption.** Patient demographics and provider panel data are PHI. In production, Lambda or SageMaker Processing jobs run in a VPC with no internet access, using VPC endpoints for DynamoDB and S3. All data at rest is encrypted with KMS customer-managed keys. The assignment rationale text (which mentions patient conditions) is also PHI.

**Fairness monitoring.** After running assignments for several months, audit the results for unintended bias. Are patients of certain demographics systematically assigned to less experienced providers? Are language-concordant assignments actually happening at the rates you'd expect? Build dashboards that track assignment patterns by patient demographics and flag statistical anomalies.

**Testing.** There are no tests here. A production pipeline has unit tests for the scoring function (does a language match actually produce the expected bonus?), constraint tests (does a closed panel actually block assignments?), integration tests for the solver (does it find feasible solutions for edge cases like "more patients than total capacity"?), and regression tests that verify known-good assignments still score optimally after code changes.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 14.2](chapter14.02-patient-provider-assignment) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
