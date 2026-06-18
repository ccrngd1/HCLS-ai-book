# Recipe 15.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the adaptive randomization system from Recipe 15.3. It demonstrates Thompson Sampling for clinical trial allocation using boto3 for AWS integration. This is not production-ready. A real adaptive trial system requires validated statistical software, regulatory review, and months of simulation studies. Think of this as a learning tool, not something you'd submit to the FDA.

---

## Setup

```bash
pip install boto3 numpy
```

Your environment needs credentials configured with permissions for `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `s3:GetObject`, `s3:PutObject`, and `sagemaker:CreateProcessingJob`. You'll also need a signed BAA if working with any real trial data (which you shouldn't be in development, but the infrastructure should assume it).

---

## Configuration and Constants

These define the trial parameters. In a real system, these would be locked into the protocol before the first patient enrolls. Changing them mid-trial requires a protocol amendment and regulatory approval.

```python
import json
import time
import uuid
from decimal import Decimal

import boto3
import numpy as np

# ============================================================================
# TRIAL CONFIGURATION
# ============================================================================
# These parameters define the adaptive design. They're set during the design
# phase (after simulation studies confirm operating characteristics) and locked
# before enrollment begins. Treat them as immutable during the trial.

TRIAL_CONFIG = {
    "trial_id": "TRIAL-2026-001",
    "arms": ["Control", "Treatment_A", "Treatment_B"],
    "endpoint_type": "binary",  # response vs. no response

    # Prior distributions: Beta(alpha, beta) for each arm.
    # Beta(1, 1) is a uniform prior: "we have no information about this arm's
    # response rate." This is the standard uninformative prior for binary endpoints.
    # If you have historical data (e.g., known control rate from prior trials),
    # you could use an informative prior like Beta(30, 70) for a 30% historical rate.
    "priors": {
        "Control":     {"alpha": 1, "beta": 1},
        "Treatment_A": {"alpha": 1, "beta": 1},
        "Treatment_B": {"alpha": 1, "beta": 1},
    },

    # Allocation constraints prevent the algorithm from going to extremes.
    # min_allocation: no arm drops below this. Ensures we always collect some data
    #   on every arm, which is critical for valid statistical inference at trial end.
    # max_allocation: no arm exceeds this. Prevents premature convergence before
    #   we have enough data to be confident.
    "min_allocation": 0.10,
    "max_allocation": 0.80,

    # Burn-in: the first N patients get equal randomization (no adaptation).
    # This gives the algorithm a baseline of data before it starts shifting.
    # Rule of thumb: at least 10 patients per arm before adaptation begins.
    "burn_in_patients": 30,

    # Thompson Sampling simulations: more = more stable allocation probabilities,
    # but diminishing returns past ~10,000.
    "num_thompson_samples": 10000,
}

# AWS resource names
ALLOCATION_STATE_TABLE = "adaptive-trial-allocation-state"
ASSIGNMENT_AUDIT_TABLE = "adaptive-trial-assignment-audit"
OUTCOMES_BUCKET = "adaptive-trial-outcomes"

# DynamoDB requires Decimal instead of float. This is a known gotcha.
# We handle the conversion explicitly rather than letting it blow up at runtime.
```

---

## Step 1: Initialize Trial State

This creates the initial allocation state in DynamoDB. You run this once, before the first patient enrolls. It sets up the prior distributions and equal allocation probabilities.

```python
def initialize_trial(config):
    """
    Create the initial trial state in DynamoDB.

    This is a one-time setup step. After this runs, the randomization service
    can start accepting enrollment requests (which will use equal allocation
    until the burn-in period completes).
    """
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(ALLOCATION_STATE_TABLE)

    # Start with equal allocation across all arms
    num_arms = len(config["arms"])
    equal_prob = Decimal(str(round(1.0 / num_arms, 4)))

    initial_state = {
        "trial_id": config["trial_id"],
        "posteriors": {
            arm: {
                "alpha": Decimal(str(params["alpha"])),
                "beta": Decimal(str(params["beta"])),
            }
            for arm, params in config["priors"].items()
        },
        "allocation_probs": {
            arm: equal_prob for arm in config["arms"]
        },
        "total_enrolled": 0,
        "enrollment_paused": False,
        "trial_stopped": False,
        "last_update": "initialization",
        "version": 0,
    }

    table.put_item(Item=initial_state)
    print(f"Trial {config['trial_id']} initialized with {num_arms} arms")
    print(f"Burn-in period: first {config['burn_in_patients']} patients get equal randomization")
    return initial_state
```

---

## Step 2: Posterior Update Engine

This is the Bayesian learning component. When new outcomes arrive, it updates the Beta distribution parameters for each arm and recomputes allocation probabilities using Thompson Sampling. In production, this runs as a SageMaker Processing Job triggered by Step Functions.

```python
def update_posteriors(trial_id, new_outcomes):
    """
    Update posterior distributions based on newly confirmed outcomes.

    Parameters
    ----------
    trial_id : str
        The trial identifier.
    new_outcomes : list of dict
        Each dict has {"patient_id": str, "arm": str, "outcome": str}
        where outcome is "response" or "no_response".

    This function:
    1. Reads current state from DynamoDB
    2. Updates Beta posteriors with new data (conjugate update)
    3. Recomputes Thompson Sampling allocation probabilities
    4. Writes updated state back to DynamoDB with optimistic locking
    """
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(ALLOCATION_STATE_TABLE)

    # Read current state
    response = table.get_item(Key={"trial_id": trial_id})
    state = response["Item"]

    if state.get("trial_stopped"):
        print("Trial is stopped. No further updates.")
        return None

    # Count successes and failures per arm in the new batch
    for outcome in new_outcomes:
        arm = outcome["arm"]
        if arm not in state["posteriors"]:
            # Arm was dropped by DSMB; skip this outcome for allocation purposes
            # (still recorded in audit log for final analysis)
            continue

        if outcome["outcome"] == "response":
            state["posteriors"][arm]["alpha"] += 1
        else:
            state["posteriors"][arm]["beta"] += 1

    # Recompute allocation probabilities using Thompson Sampling
    # Only adapt if we're past the burn-in period
    total_enrolled = int(state["total_enrolled"])
    if total_enrolled >= TRIAL_CONFIG["burn_in_patients"]:
        new_probs = compute_thompson_allocation(
            posteriors=state["posteriors"],
            min_alloc=TRIAL_CONFIG["min_allocation"],
            max_alloc=TRIAL_CONFIG["max_allocation"],
            num_samples=TRIAL_CONFIG["num_thompson_samples"],
        )
        state["allocation_probs"] = new_probs

    # Update metadata
    state["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["version"] = int(state["version"]) + 1

    # Write back with optimistic locking (condition on version)
    # If another process updated the state between our read and write,
    # this will fail and we retry. Prevents lost updates.
    try:
        table.put_item(
            Item=state,
            ConditionExpression="version = :expected_version",
            ExpressionAttributeValues={
                ":expected_version": state["version"] - 1,
            },
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        # Another process updated state. In production, retry with backoff.
        print("Concurrent update detected. Retry needed.")
        raise

    print(f"Posteriors updated. New allocation: {state['allocation_probs']}")
    return state
```

---

## Step 3: Thompson Sampling Allocation

The core RL logic. We draw samples from each arm's posterior distribution many times and count how often each arm "wins" (produces the highest sample). The win frequency becomes the allocation probability.

```python
def compute_thompson_allocation(posteriors, min_alloc, max_alloc, num_samples=10000):
    """
    Compute allocation probabilities using Thompson Sampling.

    For each simulation:
      1. Draw a random sample from each arm's Beta posterior
      2. The arm with the highest sample "wins"
    
    The allocation probability for each arm = fraction of simulations it won.
    Then we clip to [min_alloc, max_alloc] and renormalize.

    Why Thompson Sampling works for clinical trials:
    - Arms with high posterior means win often (exploitation)
    - Arms with wide posteriors (high uncertainty) occasionally win (exploration)
    - No tuning parameters needed (unlike epsilon-greedy or UCB)
    - The randomization is inherent (important for regulatory acceptance)
    """
    arms = list(posteriors.keys())
    num_arms = len(arms)

    # Convert Decimal to float for numpy (DynamoDB stores as Decimal)
    alphas = [float(posteriors[arm]["alpha"]) for arm in arms]
    betas = [float(posteriors[arm]["beta"]) for arm in arms]

    # Draw num_samples samples from each arm's Beta distribution
    # Shape: (num_samples, num_arms)
    samples = np.column_stack([
        np.random.beta(a, b, size=num_samples)
        for a, b in zip(alphas, betas)
    ])

    # For each simulation, find which arm had the highest sample
    winners = np.argmax(samples, axis=1)

    # Count wins per arm
    win_counts = np.bincount(winners, minlength=num_arms)
    raw_probs = win_counts / num_samples

    # Apply constraints and renormalize
    constrained = np.clip(raw_probs, min_alloc, max_alloc)
    constrained = constrained / constrained.sum()

    # Convert back to Decimal for DynamoDB storage
    result = {
        arm: Decimal(str(round(float(prob), 4)))
        for arm, prob in zip(arms, constrained)
    }
    return result
```

---

## Step 4: Randomization Service

This is the Lambda function that sites call when enrolling a patient. It reads the current allocation probabilities and performs a weighted random draw. Speed matters here: sites are waiting on the phone.

```python
def randomize_patient(trial_id, patient_id, stratification_factors=None):
    """
    Assign a patient to a treatment arm.

    This function is the core of the randomization service (runs in Lambda).
    It must be:
    - Fast (sub-second; sites are waiting)
    - Auditable (every input and output is logged)
    - Deterministic given inputs (for reproducibility)

    Parameters
    ----------
    trial_id : str
        Trial identifier.
    patient_id : str
        Unique patient identifier.
    stratification_factors : dict, optional
        Patient characteristics for stratified randomization (e.g., site, biomarker).
        Not used in this simple implementation but included for completeness.

    Returns
    -------
    str
        The assigned arm name.
    """
    dynamodb = boto3.resource("dynamodb")
    state_table = dynamodb.Table(ALLOCATION_STATE_TABLE)
    audit_table = dynamodb.Table(ASSIGNMENT_AUDIT_TABLE)

    # Read current allocation state
    response = state_table.get_item(Key={"trial_id": trial_id})
    state = response["Item"]

    # Check if enrollment is allowed
    if state.get("trial_stopped"):
        raise ValueError("Trial has been stopped. No further enrollment.")
    if state.get("enrollment_paused"):
        raise ValueError("Enrollment is paused by DSMB. Contact trial coordinator.")

    # Determine allocation probabilities
    total_enrolled = int(state["total_enrolled"])
    if total_enrolled < TRIAL_CONFIG["burn_in_patients"]:
        # During burn-in: equal randomization
        arms = TRIAL_CONFIG["arms"]
        probs = [1.0 / len(arms)] * len(arms)
    else:
        # After burn-in: use adaptive allocation
        arms = list(state["allocation_probs"].keys())
        probs = [float(state["allocation_probs"][arm]) for arm in arms]

    # Generate assignment using numpy's weighted choice
    # In production, use a cryptographically secure RNG for regulatory compliance.
    # numpy's default RNG is fine for illustration but not for a real trial.
    random_seed = int.from_bytes(uuid.uuid4().bytes[:8], "big")
    rng = np.random.default_rng(random_seed)
    assigned_arm = rng.choice(arms, p=probs)

    # Log the complete assignment record
    # This audit trail is critical for regulatory compliance (21 CFR Part 11)
    # and for reproducing the randomization sequence if challenged.
    assignment_record = {
        "assignment_id": str(uuid.uuid4()),
        "trial_id": trial_id,
        "patient_id": patient_id,
        "assigned_arm": assigned_arm,
        "allocation_probs": {arm: str(p) for arm, p in zip(arms, probs)},  # Stored as strings for human readability in audit log
        "random_seed": str(random_seed),
        "state_version": int(state["version"]),
        "stratification": stratification_factors or {},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_enrolled_at_time": total_enrolled,
    }
    audit_table.put_item(Item=assignment_record)

    # Increment enrollment counter atomically
    state_table.update_item(
        Key={"trial_id": trial_id},
        UpdateExpression="SET total_enrolled = total_enrolled + :inc",
        ExpressionAttributeValues={":inc": 1},
    )

    print(f"Patient {patient_id} assigned to {assigned_arm} "
          f"(probs: {dict(zip(arms, probs))})")
    return assigned_arm
```

---

## Step 5: DSMB Override Support

The Data Safety Monitoring Board can override the algorithm at any time. These are human decisions with regulatory authority. The system must support them cleanly.

```python
def apply_dsmb_override(trial_id, override_type, parameters, authorized_by):
    """
    Apply a DSMB decision that overrides the adaptive algorithm.

    The DSMB operates independently and has authority to:
    - Drop an arm (futility or safety)
    - Pause enrollment
    - Stop the trial entirely

    These decisions are logged as part of the audit trail and take
    immediate effect on the randomization service.
    """
    dynamodb = boto3.resource("dynamodb")
    state_table = dynamodb.Table(ALLOCATION_STATE_TABLE)
    audit_table = dynamodb.Table(ASSIGNMENT_AUDIT_TABLE)

    response = state_table.get_item(Key={"trial_id": trial_id})
    state = response["Item"]

    if override_type == "DROP_ARM":
        arm_to_drop = parameters["arm"]
        if arm_to_drop not in state["allocation_probs"]:
            raise ValueError(f"Arm {arm_to_drop} not found or already dropped.")

        # Remove the arm from allocation
        del state["allocation_probs"][arm_to_drop]
        del state["posteriors"][arm_to_drop]

        # Renormalize remaining probabilities
        remaining_total = sum(
            float(p) for p in state["allocation_probs"].values()
        )
        state["allocation_probs"] = {
            arm: Decimal(str(round(float(p) / remaining_total, 4)))
            for arm, p in state["allocation_probs"].items()
        }
        print(f"Arm {arm_to_drop} dropped. Remaining: {state['allocation_probs']}")

    elif override_type == "PAUSE_ENROLLMENT":
        state["enrollment_paused"] = True
        print("Enrollment paused by DSMB.")

    elif override_type == "RESUME_ENROLLMENT":
        state["enrollment_paused"] = False
        print("Enrollment resumed by DSMB.")

    elif override_type == "STOP_TRIAL":
        state["trial_stopped"] = True
        print("Trial stopped by DSMB.")

    else:
        raise ValueError(f"Unknown override type: {override_type}")

    # Update state with optimistic locking (same pattern as update_posteriors).
    # In production, DSMB overrides should also use conditional writes to prevent
    # a concurrent posterior update from silently overwriting the override.
    state["version"] = int(state["version"]) + 1
    # TODO (TechWriter): Code review Issue 1 (WARNING). Add ConditionExpression here to match update_posteriors pattern. Currently simplified for readability.
    state_table.put_item(Item=state)

    # Log the override in the audit trail
    override_record = {
        "assignment_id": str(uuid.uuid4()),
        "trial_id": trial_id,
        "patient_id": "DSMB_OVERRIDE",
        "assigned_arm": "N/A",
        "override_type": override_type,
        "override_parameters": parameters,
        "authorized_by": authorized_by,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "state_version": int(state["version"]),
    }
    audit_table.put_item(Item=override_record)
```

---

## Full Pipeline: Simulated Trial Run

This assembles all the pieces into a simulated trial execution. It generates synthetic patient outcomes and demonstrates how the allocation shifts over time. You'd use something like this during the design phase to validate operating characteristics.

```python
def run_simulated_trial(config, true_response_rates, total_patients=150):
    """
    Simulate a complete adaptive trial to demonstrate the system.

    Parameters
    ----------
    config : dict
        Trial configuration (TRIAL_CONFIG).
    true_response_rates : dict
        The actual (unknown to the algorithm) response rates per arm.
        e.g., {"Control": 0.30, "Treatment_A": 0.45, "Treatment_B": 0.25}
    total_patients : int
        Total patients to enroll in the simulation.

    This function does NOT call AWS services. It runs the Thompson Sampling
    logic locally to demonstrate how allocation evolves. In production,
    each step would hit DynamoDB/Lambda/SageMaker as shown above.
    """
    print("=" * 60)
    print(f"SIMULATED ADAPTIVE TRIAL: {config['trial_id']}")
    print(f"True response rates: {true_response_rates}")
    print(f"Total patients: {total_patients}")
    print("=" * 60)

    # Initialize local state (mirrors what DynamoDB would hold)
    posteriors = {
        arm: {"alpha": float(p["alpha"]), "beta": float(p["beta"])}
        for arm, p in config["priors"].items()
    }
    arms = config["arms"]
    num_arms = len(arms)
    enrolled_per_arm = {arm: 0 for arm in arms}
    responses_per_arm = {arm: 0 for arm in arms}

    # Track allocation history for visualization
    allocation_history = []

    # Enroll patients one at a time
    for patient_num in range(1, total_patients + 1):
        # Determine allocation probabilities
        if patient_num <= config["burn_in_patients"]:
            probs = [1.0 / num_arms] * num_arms
        else:
            # Thompson Sampling
            probs_dict = compute_thompson_allocation_local(
                posteriors,
                config["min_allocation"],
                config["max_allocation"],
                config["num_thompson_samples"],
            )
            probs = [probs_dict[arm] for arm in arms]

        # Randomize this patient
        assigned_arm = np.random.choice(arms, p=probs)
        enrolled_per_arm[assigned_arm] += 1

        # Simulate outcome based on true response rate
        true_rate = true_response_rates[assigned_arm]
        responded = np.random.random() < true_rate

        if responded:
            responses_per_arm[assigned_arm] += 1
            posteriors[assigned_arm]["alpha"] += 1
        else:
            posteriors[assigned_arm]["beta"] += 1

        # Log progress at intervals
        if patient_num % 25 == 0 or patient_num == total_patients:
            print(f"\n--- After {patient_num} patients ---")
            print(f"  Allocation: {dict(zip(arms, [f'{p:.2f}' for p in probs]))}")
            print(f"  Enrolled:   {enrolled_per_arm}")
            print(f"  Responses:  {responses_per_arm}")
            for arm in arms:
                n = enrolled_per_arm[arm]
                r = responses_per_arm[arm]
                obs_rate = r / n if n > 0 else 0
                post_mean = posteriors[arm]["alpha"] / (
                    posteriors[arm]["alpha"] + posteriors[arm]["beta"]
                )
                print(f"  {arm}: {r}/{n} = {obs_rate:.1%} observed, "
                      f"posterior mean = {post_mean:.3f}")

        allocation_history.append(dict(zip(arms, probs)))

    # Final summary
    print("\n" + "=" * 60)
    print("TRIAL COMPLETE")
    print("=" * 60)
    print(f"Total enrolled: {total_patients}")
    print(f"Per-arm enrollment: {enrolled_per_arm}")
    print(f"Per-arm responses:  {responses_per_arm}")
    print(f"\nCompare to fixed randomization (equal allocation):")
    fixed_per_arm = total_patients // num_arms
    for arm in arms:
        rate = true_response_rates[arm]
        expected_fixed = int(fixed_per_arm * rate)
        actual = responses_per_arm[arm]
        print(f"  {arm}: fixed would expect ~{expected_fixed} responses "
              f"from {fixed_per_arm} patients; adaptive got {actual} "
              f"from {enrolled_per_arm[arm]} patients")

    total_responses = sum(responses_per_arm.values())
    expected_fixed_total = sum(
        int(fixed_per_arm * true_response_rates[arm]) for arm in arms
    )
    print(f"\nTotal responses: {total_responses} (adaptive) vs "
          f"~{expected_fixed_total} (fixed)")
    improvement = (total_responses - expected_fixed_total) / expected_fixed_total * 100
    print(f"Improvement: ~{improvement:.1f}% more patients received effective treatment")

def compute_thompson_allocation_local(posteriors, min_alloc, max_alloc, num_samples):
    """
    Local version of Thompson Sampling (no DynamoDB Decimal conversion).
    Used for simulation only.
    """
    arms = list(posteriors.keys())
    alphas = [posteriors[arm]["alpha"] for arm in arms]
    betas = [posteriors[arm]["beta"] for arm in arms]

    samples = np.column_stack([
        np.random.beta(a, b, size=num_samples)
        for a, b in zip(alphas, betas)
    ])

    winners = np.argmax(samples, axis=1)
    win_counts = np.bincount(winners, minlength=len(arms))
    raw_probs = win_counts / num_samples

    constrained = np.clip(raw_probs, min_alloc, max_alloc)
    constrained = constrained / constrained.sum()

    return dict(zip(arms, constrained))

# Run the simulation
if __name__ == "__main__":
    run_simulated_trial(
        config=TRIAL_CONFIG,
        true_response_rates={
            "Control": 0.30,
            "Treatment_A": 0.45,
            "Treatment_B": 0.25,
        },
        total_patients=150,
    )
```

---

## Gap to Production

This example demonstrates the core logic, but a real adaptive trial system needs substantially more:

**Statistical validation.** Before running a real trial, you need thousands of simulation runs under different scenarios (null hypothesis, various alternatives, different enrollment rates, dropout patterns) to verify Type I error control and characterize power. This is months of biostatistician work, not a weekend project. The simulation framework above is a starting point, but production simulations need to account for delayed outcomes, interim analyses, and the specific test statistic you'll use for the final analysis.

**Cryptographic randomization.** The `numpy` RNG is fine for simulation but not for a real trial. Production systems need a cryptographically secure random number generator (e.g., `secrets.SystemRandom()` or hardware RNG) with the seed logged for reproducibility. Some regulatory frameworks require the randomization algorithm to be validated as a medical device.

**Delayed outcome handling.** Real trials have outcomes that take weeks or months to confirm. The posterior update engine needs to distinguish between "no outcome yet" (patient still being followed) and "treatment failure" (confirmed negative outcome). The current implementation assumes immediate outcomes, which is unrealistic for most trials.

**Error handling and retries.** DynamoDB conditional writes can fail under concurrent access. The Lambda function needs retry logic with exponential backoff. The Step Functions workflow needs error states and dead-letter queues. Network failures between the EDC system and the randomization service need graceful handling (what happens if the site doesn't receive the assignment response?).

**Input validation.** Every API call needs validation: Is this patient already enrolled? Is this trial still active? Is the patient eligible based on inclusion/exclusion criteria? Are the stratification factors valid? The randomization service should reject invalid requests with clear error messages.

**Structured logging and monitoring.** CloudWatch metrics on randomization latency, allocation drift, posterior convergence, and enrollment rate. Alarms if the randomization service becomes unavailable or if allocation probabilities change unexpectedly fast (could indicate a data quality issue).

**IAM least-privilege.** The Lambda function should only have `dynamodb:GetItem` on the state table and `dynamodb:PutItem` on the audit table. The SageMaker Processing Job needs broader access but should be scoped to specific S3 prefixes and DynamoDB tables. No wildcards.

**VPC and network isolation.** Production: Lambda and SageMaker in a VPC with VPC endpoints for DynamoDB, S3, and CloudWatch Logs. No internet access needed. The API Gateway endpoint should use mutual TLS or API keys for site authentication.

**KMS encryption.** All data at rest encrypted with customer-managed KMS keys. DynamoDB tables with encryption enabled. S3 buckets with SSE-KMS. Lambda environment variables encrypted. Key rotation policy in place.

**21 CFR Part 11 compliance.** If this is an FDA-regulated trial: electronic records need audit trails (covered by DynamoDB + CloudTrail), access controls (IAM), and electronic signatures (not covered here; you'd need an additional authentication layer for DSMB overrides).

**Testing.** Unit tests for the Thompson Sampling logic (deterministic given a seed). Integration tests for the DynamoDB read/write path. Load tests to verify sub-second randomization under concurrent enrollment. Chaos testing to verify behavior when DynamoDB is throttled or Lambda cold-starts.

**Multi-site coordination.** Real trials have dozens of sites enrolling simultaneously. The DynamoDB atomic counter handles concurrent enrollment, but you also need to handle the case where two sites call the randomization service at the exact same moment and both read the same state version. The current optimistic locking approach works but needs retry logic on the client side.

---

| [← Recipe 15.3: Clinical Trial Adaptive Randomization](chapter15.03-clinical-trial-adaptive-randomization) | [Chapter 15 Index](chapter15-preface) | [Recipe 15.4: Sepsis Treatment Optimization →](chapter15.04-sepsis-treatment-optimization) |
|:---|:---:|---:|
