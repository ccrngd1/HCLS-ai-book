# Recipe 15.6: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the RL concepts from Recipe 15.6. It demonstrates the shape of an ICU glucose control RL system: environment definition, state construction, reward shaping, offline policy learning, safety constraint enforcement, and clinical decision support integration. It is not production-ready. Real offline RL for insulin dosing requires extensive retrospective validation, simulation testing, IRB approval, and prospective clinical trials before any patient-facing deployment. Consider this a learning tool, not a deployment artifact.

---

## Setup

You'll need the following packages:

```bash
pip install boto3 numpy
```

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs `sagemaker:InvokeEndpoint`, `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:Query`, `s3:GetObject`, `s3:PutObject`, and `sagemaker:CreateTrainingJob`.

---

## Config and Constants

Before the logic, here's the configuration that defines the clinical domain. These constants encode medical knowledge about ICU glucose management: what glucose ranges are safe, how to score outcomes, and what actions are never acceptable. In a real system, these would be developed with intensivists and endocrinologists, validated against clinical guidelines, and reviewed by your institution's pharmacy and therapeutics committee.

```python
import numpy as np
import json
import logging
import time
from decimal import Decimal
from typing import Optional

import boto3
from botocore.config import Config

# Structured logging. In production, use JSON format for CloudWatch Logs Insights.
# Never log actual patient identifiers or PHI values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS calls. Adaptive mode handles throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Glucose Target Range ---
# These define what "good control" means. The target range is 80-180 mg/dL,
# with the sweet spot at 120-140 mg/dL. These numbers come from the NICE-SUGAR
# trial and subsequent guidelines that backed off from aggressive tight control
# (which caused too much hypoglycemia) toward a more moderate target.
GLUCOSE_TARGET_LOW = 80       # mg/dL: below this is concerning
GLUCOSE_TARGET_HIGH = 180     # mg/dL: above this is hyperglycemic
GLUCOSE_SWEET_SPOT = 130      # mg/dL: ideal center of target range
GLUCOSE_HYPO_THRESHOLD = 70   # mg/dL: below this is hypoglycemia (dangerous)
GLUCOSE_SEVERE_HYPO = 40      # mg/dL: below this is severe hypoglycemia (life-threatening)
GLUCOSE_SEVERE_HYPER = 250    # mg/dL: above this risks osmotic complications

# --- Action Space ---
# Discretized insulin doses in units. The agent picks one of these.
# In practice, you might use a continuous action space (actor-critic methods),
# but discrete actions are simpler to implement and easier to constrain.
# These bins cover the typical range of subcutaneous insulin doses in an ICU.
ACTION_SPACE = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20]
NUM_ACTIONS = len(ACTION_SPACE)

# --- State Features ---
# The state vector captures everything the RL agent needs to make a dosing decision.
# Each feature has a name, expected range (for normalization), and a description
# of why it matters for insulin dosing.
STATE_FEATURES = [
    # Current glucose and recent history
    {"name": "glucose_current", "min": 30, "max": 500,
     "why": "The primary measurement driving the decision"},
    {"name": "glucose_prev_1", "min": 30, "max": 500,
     "why": "Previous reading (4h ago) for trend calculation"},
    {"name": "glucose_prev_2", "min": 30, "max": 500,
     "why": "Two readings ago (8h ago) for acceleration detection"},
    {"name": "glucose_velocity", "min": -60, "max": 60,
     "why": "Rate of change in mg/dL per hour; negative means dropping"},
    # Insulin state
    {"name": "insulin_on_board", "min": 0, "max": 40,
     "why": "Total insulin given in last 4h; still pharmacologically active"},
    {"name": "insulin_infusion_rate", "min": 0, "max": 20,
     "why": "Current drip rate (units/hr); 0 if subcutaneous only"},
    # Nutrition (major glucose driver)
    {"name": "nutrition_rate", "min": 0, "max": 100,
     "why": "Enteral/parenteral nutrition in mL/hr; directly raises glucose"},
    # Medications that affect insulin sensitivity
    {"name": "vasopressor_dose", "min": 0, "max": 1.0,
     "why": "Norepinephrine equivalent (mcg/kg/min); high doses impair sensitivity"},
    {"name": "steroid_flag", "min": 0, "max": 1,
     "why": "Binary: corticosteroids dramatically increase insulin resistance"},
    # Patient factors
    {"name": "creatinine", "min": 0.3, "max": 10.0,
     "why": "Renal function; impaired kidneys clear insulin more slowly"},
    {"name": "bmi", "min": 15, "max": 60,
     "why": "Body mass index; higher BMI generally means more insulin resistance"},
    {"name": "apache_score", "min": 0, "max": 50,
     "why": "Illness severity; sicker patients have more erratic glucose dynamics"},
]

NUM_STATE_FEATURES = len(STATE_FEATURES)

# --- Safety Constraints ---
# Hard limits that override the RL policy. These are non-negotiable.
SAFETY_CONSTRAINTS = {
    "max_single_dose": 20,              # units: absolute cap on any single dose
    "no_insulin_threshold": 100,        # mg/dL: no insulin if glucose below this
    "rapid_decline_threshold": -30,     # mg/dL/hr: halve dose if dropping this fast
    "max_dose_change": 5,               # units: max change from previous dose
    "renal_impairment_threshold": 3.0,  # mg/dL creatinine: reduce dose by 30%
}

# --- Reward Function Parameters ---
# These weights define the asymmetric penalty structure.
# Hypoglycemia is penalized much more heavily than hyperglycemia because
# it's immediately dangerous (seizures, brain damage) vs. gradually harmful.
REWARD_PARAMS = {
    "severe_hypo_penalty": -100,    # glucose < 40: catastrophic
    "hypo_penalty_scale": -50,      # glucose 40-70: scaled by severity
    "below_target_penalty": -5,     # glucose 70-80: mild concern
    "in_range_max_reward": 10,      # glucose 80-180: positive, peaks at center
    "mild_hyper_scale": -2,         # glucose 180-250: scaled penalty
    "severe_hyper_base": -10,       # glucose > 250: base penalty plus scaled
}

# --- AWS Resource Names ---
# In production, pull these from environment variables or SSM Parameter Store.
SAGEMAKER_ENDPOINT = "glucose-rl-policy-v2"
DYNAMODB_TABLE = "patient-glucose-state"
S3_TRAINING_BUCKET = "glucose-rl-training-episodes"
S3_EPISODE_PREFIX = "episodes/v3/"
```

---

## Step 1: Reward Function

*Maps to pseudocode Step 2 in the main recipe. This is the most consequential design decision in the system. The reward function encodes what "good glucose control" means numerically, with asymmetric penalties reflecting the clinical reality that hypoglycemia kills faster than hyperglycemia.*

```python
def compute_reward(glucose_mg_dl: float) -> float:
    """
    Compute the reward signal for a given glucose outcome.

    The reward function is asymmetric by design:
    - Hypoglycemia (< 70 mg/dL) gets steep penalties because it's immediately dangerous.
      A glucose of 50 can cause seizures. A glucose of 35 can cause brain damage.
    - Hyperglycemia (> 180 mg/dL) gets milder penalties because it's harmful over hours,
      not minutes. You have time to correct it.
    - The target range (80-180 mg/dL) gets positive reward, peaking at the sweet spot
      of ~130 mg/dL.

    This shape was informed by the NICE-SUGAR trial results: aggressive glucose targets
    increased mortality because protocols caused too much hypoglycemia. The reward
    function must make the agent deeply afraid of lows while still encouraging
    reasonable control of highs.

    Args:
        glucose_mg_dl: The glucose measurement following the insulin action.

    Returns:
        A float reward value. Negative is bad, positive is good.
    """
    if glucose_mg_dl < GLUCOSE_SEVERE_HYPO:
        # Severe hypoglycemia. Seizures, brain damage, death.
        # Maximum penalty. If your agent ever causes this, something is very wrong.
        return REWARD_PARAMS["severe_hypo_penalty"]

    elif glucose_mg_dl < GLUCOSE_HYPO_THRESHOLD:
        # Hypoglycemia. Dangerous. Requires immediate intervention (dextrose push).
        # Penalty scales with severity: glucose of 45 is worse than glucose of 65.
        severity_fraction = (GLUCOSE_HYPO_THRESHOLD - glucose_mg_dl) / (
            GLUCOSE_HYPO_THRESHOLD - GLUCOSE_SEVERE_HYPO
        )
        return REWARD_PARAMS["hypo_penalty_scale"] * severity_fraction

    elif glucose_mg_dl < GLUCOSE_TARGET_LOW:
        # Below target but not hypoglycemic. The "yellow zone."
        # Mild penalty to discourage the agent from riding the edge.
        return REWARD_PARAMS["below_target_penalty"]

    elif glucose_mg_dl <= GLUCOSE_TARGET_HIGH:
        # Target range. This is where we want to be.
        # Reward peaks at the sweet spot (130 mg/dL) and tapers toward edges.
        distance_from_center = abs(glucose_mg_dl - GLUCOSE_SWEET_SPOT)
        max_distance = max(
            GLUCOSE_SWEET_SPOT - GLUCOSE_TARGET_LOW,
            GLUCOSE_TARGET_HIGH - GLUCOSE_SWEET_SPOT,
        )
        # Linear taper from max reward at center to ~half reward at edges
        return REWARD_PARAMS["in_range_max_reward"] * (
            1.0 - 0.5 * distance_from_center / max_distance
        )

    elif glucose_mg_dl <= GLUCOSE_SEVERE_HYPER:
        # Mild hyperglycemia. Harmful over time but not acutely dangerous.
        # Linear penalty scaling with how far above target.
        overshoot = glucose_mg_dl - GLUCOSE_TARGET_HIGH
        range_width = GLUCOSE_SEVERE_HYPER - GLUCOSE_TARGET_HIGH
        return REWARD_PARAMS["mild_hyper_scale"] * (overshoot / range_width)

    else:
        # Severe hyperglycemia. Osmotic complications, DKA risk.
        # Base penalty plus additional scaling for extreme values.
        extra = (glucose_mg_dl - GLUCOSE_SEVERE_HYPER) / 50.0
        return REWARD_PARAMS["severe_hyper_base"] - extra
```

---

## Step 2: State Construction

*Maps to pseudocode Step 1 in the main recipe. Transforms raw clinical data from DynamoDB into a normalized state vector suitable for the RL model.*

```python
def normalize_feature(value: float, feature_def: dict) -> float:
    """
    Normalize a raw clinical value to [0, 1] range using the feature's defined bounds.

    Why normalize? Neural network-based RL algorithms work better when all inputs
    are on similar scales. Without normalization, a glucose of 200 would dominate
    a vasopressor dose of 0.3 simply because of magnitude differences.

    Args:
        value: The raw clinical measurement.
        feature_def: Dict with 'min' and 'max' defining the expected range.

    Returns:
        Value scaled to [0, 1], clipped to bounds.
    """
    min_val = feature_def["min"]
    max_val = feature_def["max"]

    # Clip to expected range. Values outside bounds are physiologically extreme.
    clipped = max(min_val, min(max_val, value))

    if max_val == min_val:
        return 0.5
    return (clipped - min_val) / (max_val - min_val)


def construct_state_vector(patient_data: dict) -> np.ndarray:
    """
    Build a normalized state vector from raw patient data.

    The input is a dictionary of current clinical values keyed by feature name.
    Missing values are imputed as the midpoint (0.5 after normalization). In
    production, you'd forward-fill from the last known value and include a
    "staleness" feature so the model can learn to be uncertain about old data.

    Args:
        patient_data: Dict mapping feature names to current values.
                      Example: {"glucose_current": 195, "insulin_on_board": 4.0, ...}

    Returns:
        numpy array of shape (NUM_STATE_FEATURES,) with values in [0, 1].
    """
    state = np.zeros(NUM_STATE_FEATURES, dtype=np.float32)

    for i, feature_def in enumerate(STATE_FEATURES):
        name = feature_def["name"]

        if name in patient_data and patient_data[name] is not None:
            state[i] = normalize_feature(patient_data[name], feature_def)
        else:
            # Missing value: midpoint imputation. Naive but functional.
            # Production systems should forward-fill and flag staleness.
            state[i] = 0.5
            logger.warning("Missing feature '%s', using midpoint imputation", name)

    return state
```

---

## Step 3: Safety Constraint Layer

*Maps to pseudocode Step 5 in the main recipe. This is the last line of defense. Regardless of what the RL policy recommends, certain actions are never allowed. The safety layer encodes decades of clinical knowledge about what's dangerous.*

```python
def apply_safety_constraints(
    recommended_dose: float,
    patient_data: dict,
    previous_dose: float,
) -> dict:
    """
    Apply hard safety constraints to the RL policy's recommended dose.

    Think of this as a safety envelope around the policy. The RL agent operates
    freely within the envelope; anything outside gets clipped. These constraints
    are non-negotiable clinical rules that should never be violated, even if the
    data-driven policy disagrees.

    The honest truth: a simple PID controller with good safety constraints can
    outperform a sophisticated RL policy with weak constraints. The constraints
    encode what keeps patients alive. The RL policy adds value at the margins.

    Args:
        recommended_dose: What the RL policy wants to give (units of insulin).
        patient_data: Current clinical state (raw values, not normalized).
        previous_dose: The dose given at the last decision point (units).

    Returns:
        Dict with final_dose, original_recommendation, and list of activated constraints.
    """
    safe_dose = recommended_dose
    activated = []

    # Constraint 1: Absolute maximum dose cap.
    # No single dose should ever exceed this, period.
    # Clinical rationale: prevents catastrophic hypoglycemia from a single error.
    max_dose = SAFETY_CONSTRAINTS["max_single_dose"]
    if safe_dose > max_dose:
        safe_dose = max_dose
        activated.append(f"max_dose_cap: {recommended_dose:.1f} -> {safe_dose:.1f}")

    # Constraint 2: No insulin if glucose is already low.
    # If glucose is below 100 mg/dL, giving insulin is reckless.
    # The patient needs carbs, not more insulin.
    glucose = patient_data.get("glucose_current")
    if glucose is not None and glucose < SAFETY_CONSTRAINTS["no_insulin_threshold"]:
        safe_dose = 0
        activated.append(f"hypo_prevention_hold: glucose={glucose:.0f}, dose zeroed")

    # Constraint 3: Halve dose if glucose is dropping rapidly.
    # Insulin already on board will continue lowering glucose for hours.
    # A rapid decline means the previous dose is still working.
    velocity = patient_data.get("glucose_velocity")
    if velocity is not None and velocity < SAFETY_CONSTRAINTS["rapid_decline_threshold"]:
        safe_dose = safe_dose * 0.5
        activated.append(
            f"rapid_decline_reduction: velocity={velocity:.1f} mg/dL/hr, dose halved"
        )

    # Constraint 4: Maximum dose change between intervals.
    # Prevents wild swings in dosing that confuse the patient's physiology.
    max_change = SAFETY_CONSTRAINTS["max_dose_change"]
    if abs(safe_dose - previous_dose) > max_change:
        direction = 1 if safe_dose > previous_dose else -1
        safe_dose = previous_dose + direction * max_change
        activated.append(
            f"max_change_cap: limited to {max_change} unit change from previous"
        )

    # Constraint 5: Renal dose adjustment.
    # Kidneys clear insulin. Impaired kidneys mean insulin hangs around longer.
    # Reduce dose by 30% if creatinine is elevated.
    creatinine = patient_data.get("creatinine")
    if creatinine is not None and creatinine > SAFETY_CONSTRAINTS["renal_impairment_threshold"]:
        safe_dose = safe_dose * 0.7
        activated.append(
            f"renal_adjustment: creatinine={creatinine:.1f}, dose reduced 30%"
        )

    # Floor at zero. You can't give negative insulin.
    safe_dose = max(0.0, safe_dose)

    return {
        "final_dose": round(safe_dose, 1),
        "original_recommendation": recommended_dose,
        "constraints_activated": activated,
    }
```

---

## Step 4: Episode Construction

*Maps to pseudocode Step 1 in the main recipe. Transforms raw EHR data into RL episodes (sequences of state-action-reward tuples) suitable for offline training. This is where 70% of the engineering effort lives in practice.*

```python
def build_episode_from_icu_stay(icu_stay_data: dict, timestep_hours: int = 4) -> list:
    """
    Convert a single ICU stay's data into an RL episode.

    An episode is a sequence of (state, action, reward, next_state) tuples,
    one per decision interval. The decision interval is typically 4 hours,
    matching the frequency of glucose checks in most ICU protocols.

    The hard part here (which this simplified version glosses over) is temporal
    alignment. In real EHR data:
    - Glucose measurements arrive at irregular intervals
    - Insulin orders don't always match administration times
    - Nutrition changes happen asynchronously
    - Lab values update every 4-12 hours

    You need to bin everything into consistent time windows and handle missing
    data gracefully. This function assumes the data has already been cleaned
    and aligned into regular intervals.

    Args:
        icu_stay_data: Dict with keys:
            - "glucose_readings": list of (timestamp, value) tuples
            - "insulin_doses": list of (timestamp, units) tuples
            - "nutrition_rates": list of (timestamp, ml_per_hr) tuples
            - "medications": dict of current medication states per interval
            - "labs": dict of lab values per interval
            - "patient_info": static patient demographics (BMI, etc.)
        timestep_hours: Decision interval length in hours.

    Returns:
        List of dicts, each containing: state, action, reward, next_state.
    """
    episode = []
    readings = icu_stay_data["glucose_readings"]
    insulin = icu_stay_data["insulin_doses"]
    patient_info = icu_stay_data["patient_info"]

    # We need at least 3 readings to compute velocity and have a next_state.
    if len(readings) < 3:
        return episode

    for i in range(2, len(readings) - 1):
        # Current and historical glucose values
        glucose_current = readings[i][1]
        glucose_prev_1 = readings[i - 1][1]
        glucose_prev_2 = readings[i - 2][1]
        glucose_next = readings[i + 1][1]  # outcome of the action

        # Glucose velocity: rate of change in mg/dL per hour
        velocity = (glucose_current - glucose_prev_1) / timestep_hours

        # Insulin given during this interval (the action the clinician took)
        interval_insulin = _get_insulin_in_interval(insulin, readings[i][0], timestep_hours)

        # Build state dict
        state_data = {
            "glucose_current": glucose_current,
            "glucose_prev_1": glucose_prev_1,
            "glucose_prev_2": glucose_prev_2,
            "glucose_velocity": velocity,
            "insulin_on_board": _get_recent_insulin(insulin, readings[i][0], hours=4),
            "insulin_infusion_rate": icu_stay_data.get("infusion_rate", {}).get(i, 0),
            "nutrition_rate": _get_nutrition_at_time(
                icu_stay_data["nutrition_rates"], readings[i][0]
            ),
            "vasopressor_dose": icu_stay_data.get("medications", {}).get(
                "vasopressor_dose", {}).get(i, 0),
            "steroid_flag": icu_stay_data.get("medications", {}).get(
                "steroid_flag", {}).get(i, 0),
            "creatinine": icu_stay_data.get("labs", {}).get("creatinine", {}).get(i, 1.0),
            "bmi": patient_info.get("bmi", 25),
            "apache_score": patient_info.get("apache_score", 15),
        }

        state_vector = construct_state_vector(state_data)

        # Discretize the action: find the closest bin in ACTION_SPACE
        action_index = _discretize_dose(interval_insulin)

        # Reward: based on the glucose outcome at the next interval
        reward = compute_reward(glucose_next)

        # Next state (for Bellman backup during training)
        next_velocity = (glucose_next - glucose_current) / timestep_hours
        next_state_data = {
            **state_data,
            "glucose_current": glucose_next,
            "glucose_prev_1": glucose_current,
            "glucose_prev_2": glucose_prev_1,
            "glucose_velocity": next_velocity,
            "insulin_on_board": interval_insulin + state_data["insulin_on_board"] * 0.5,
        }
        next_state_vector = construct_state_vector(next_state_data)

        episode.append({
            "state": state_vector.tolist(),
            "action": action_index,
            "reward": reward,
            "next_state": next_state_vector.tolist(),
        })

    return episode


def _discretize_dose(dose_units: float) -> int:
    """Map a continuous dose to the nearest discrete action index."""
    distances = [abs(dose_units - a) for a in ACTION_SPACE]
    return int(np.argmin(distances))


def _get_insulin_in_interval(
    insulin_records: list, interval_start: float, hours: int
) -> float:
    """Sum insulin doses within the interval. Simplified: assumes aligned data."""
    # In production, this handles timestamp math and partial overlaps.
    # Here we assume pre-aligned interval totals.
    total = 0.0
    for ts, units in insulin_records:
        if interval_start <= ts < interval_start + hours * 3600:
            total += units
    return total


def _get_recent_insulin(insulin_records: list, current_time: float, hours: int) -> float:
    """Sum insulin given in the last N hours (insulin on board)."""
    cutoff = current_time - hours * 3600
    return sum(units for ts, units in insulin_records if ts >= cutoff)


def _get_nutrition_at_time(nutrition_records: list, current_time: float) -> float:
    """Get the most recent nutrition rate before current_time."""
    latest = 0.0
    for ts, rate in nutrition_records:
        if ts <= current_time:
            latest = rate
    return latest
```

---

## Step 5: Offline RL Training (Conservative Q-Learning)

*Maps to pseudocode Step 3 in the main recipe. This implements a simplified version of Conservative Q-Learning (CQL), which learns a policy from historical data while penalizing actions that deviate too far from what clinicians actually did. The conservatism penalty is what prevents the agent from recommending untested, potentially dangerous doses.*

```python
def train_cql_policy(
    episodes: list,
    num_iterations: int = 10000,
    batch_size: int = 256,
    discount: float = 0.99,
    cql_alpha: float = 1.0,
    learning_rate: float = 1e-3,
) -> dict:
    """
    Train a Conservative Q-Learning policy from historical episodes.

    CQL addresses the core challenge of offline RL: distributional shift. If
    historical clinicians never gave 20 units to a patient with glucose of 150,
    a naive Q-learning agent might still recommend it because the Q-function
    extrapolates incorrectly into unseen state-action regions.

    CQL fixes this by adding a penalty that pushes down Q-values for actions
    NOT observed in the training data. The result is a policy that stays close
    to historical behavior (conservative) while still improving where the data
    supports it.

    The alpha parameter controls how conservative the policy is:
    - High alpha (2-5): stays very close to historical clinician behavior
    - Low alpha (0.1-0.5): more willing to deviate (potentially better but riskier)
    - For safety-critical applications like insulin dosing, start conservative.

    Args:
        episodes: List of episode dicts from build_episode_from_icu_stay.
        num_iterations: Training iterations.
        batch_size: Transitions per training batch.
        discount: Future reward discount factor (gamma).
        cql_alpha: Conservatism penalty weight.
        learning_rate: Optimizer step size.

    Returns:
        Dict containing the trained Q-table (for this simplified tabular version).
        In production, this would be a neural network saved as a SageMaker model artifact.
    """
    # Flatten all episodes into a single replay buffer of transitions.
    # Each transition is (state, action, reward, next_state).
    replay_buffer = []
    for ep in episodes:
        for transition in ep:
            replay_buffer.append(transition)

    if not replay_buffer:
        raise ValueError("No transitions in replay buffer. Check episode construction.")

    logger.info(
        "Training CQL policy: %d transitions, %d iterations, alpha=%.2f",
        len(replay_buffer), num_iterations, cql_alpha,
    )

    # For this illustrative example, we use a tabular Q-function.
    # We discretize the state space into bins. In production, you'd use a neural
    # network Q-function (e.g., 2-layer MLP with 256 hidden units).
    #
    # State discretization: bin each normalized feature into N_BINS levels.
    # This is crude but makes the example self-contained without PyTorch/TensorFlow.
    N_BINS = 10
    q_table = np.zeros((N_BINS ** 3, NUM_ACTIONS))  # simplified: use 3 key features
    visit_counts = np.zeros_like(q_table)

    for iteration in range(num_iterations):
        # Sample a random batch of transitions
        indices = np.random.randint(0, len(replay_buffer), size=batch_size)
        batch = [replay_buffer[i] for i in indices]

        for transition in batch:
            state = np.array(transition["state"])
            action = transition["action"]
            reward = transition["reward"]
            next_state = np.array(transition["next_state"])

            # Discretize state to table index (using first 3 features: glucose, prev, velocity)
            state_idx = _state_to_index(state, N_BINS)
            next_state_idx = _state_to_index(next_state, N_BINS)

            # Standard Q-learning target: r + gamma * max_a' Q(s', a')
            next_q_max = np.max(q_table[next_state_idx])
            td_target = reward + discount * next_q_max

            # CQL penalty: push down Q-values for actions not taken.
            # For the action that WAS taken, update toward the TD target.
            # For all other actions at this state, push Q-values down slightly.
            visit_counts[state_idx, action] += 1
            lr = learning_rate / (1 + 0.001 * visit_counts[state_idx, action])

            # Update Q-value for the observed action (standard Bellman backup)
            q_table[state_idx, action] += lr * (td_target - q_table[state_idx, action])

            # CQL penalty: reduce Q-values for unobserved actions at this state.
            # This is the key insight: make the agent pessimistic about actions
            # it hasn't seen data for.
            for a in range(NUM_ACTIONS):
                if a != action:
                    q_table[state_idx, a] -= lr * cql_alpha * q_table[state_idx, a]

    logger.info("Training complete. Q-table shape: %s", q_table.shape)

    return {"q_table": q_table, "n_bins": N_BINS}


def _state_to_index(state_vector: np.ndarray, n_bins: int) -> int:
    """
    Discretize a normalized state vector into a table index.

    Uses the first 3 features (glucose_current, glucose_prev_1, glucose_velocity)
    as the key state dimensions. This is a massive simplification; real systems
    use all features via neural network function approximation.
    """
    # Bin each of the 3 key features into n_bins levels
    bins = np.clip((state_vector[:3] * n_bins).astype(int), 0, n_bins - 1)
    # Convert to a single index (base-N encoding)
    return int(bins[0] * n_bins * n_bins + bins[1] * n_bins + bins[2])
```

---

## Step 6: Off-Policy Evaluation

*Maps to pseudocode Step 4 in the main recipe. Before deploying any learned policy, you need to estimate how it would have performed on historical patients. This is off-policy evaluation (OPE): the best tool available for safety validation without live experimentation.*

```python
def evaluate_policy_offline(
    policy: dict,
    test_episodes: list,
    discount: float = 0.99,
    clip_ratio: float = 100.0,
) -> dict:
    """
    Estimate how the learned policy would have performed using importance sampling.

    The core idea: if the learned policy would have recommended the same action
    the clinician took, we can directly use the observed outcome. If it would
    have recommended a different action, we reweight the observation.

    OPE is imperfect. It has high variance (especially when the learned policy
    disagrees with clinicians frequently) and relies on overlap between policies.
    But it's the best tool available for safety validation without live experimentation.

    Args:
        policy: Trained policy dict from train_cql_policy.
        test_episodes: Held-out episodes NOT used for training.
        discount: Reward discount factor.
        clip_ratio: Maximum importance weight (variance reduction).

    Returns:
        Dict with estimated policy value, time-in-range, and hypoglycemia rate.
    """
    q_table = policy["q_table"]
    n_bins = policy["n_bins"]

    weighted_returns = []
    weights = []

    # Track clinical metrics
    total_readings = 0
    in_range_count = 0
    hypo_count = 0

    for ep in test_episodes:
        cumulative_weight = 1.0
        episode_return = 0.0

        for t, transition in enumerate(ep):
            state = np.array(transition["state"])
            action_taken = transition["action"]
            reward = transition["reward"]

            # What would the learned policy have done?
            state_idx = _state_to_index(state, n_bins)
            policy_action = int(np.argmax(q_table[state_idx]))

            # Importance ratio: how much does the learned policy agree with
            # what the clinician actually did?
            # Simplified: if policy agrees, ratio = 1. If disagrees, ratio is small.
            # In production, you'd estimate actual probabilities from both policies.
            if policy_action == action_taken:
                ratio = 1.0
            else:
                # The learned policy would have done something different.
                # Assign a small probability to the clinician's action under our policy.
                q_values = q_table[state_idx]
                # Softmax probability of the taken action under learned policy
                exp_q = np.exp(q_values - np.max(q_values))
                probs = exp_q / exp_q.sum()
                pi_prob = max(probs[action_taken], 1e-6)
                # Assume uniform behavior policy (crude approximation)
                mu_prob = 1.0 / NUM_ACTIONS
                ratio = pi_prob / mu_prob

            ratio = min(ratio, clip_ratio)
            cumulative_weight *= ratio
            episode_return += (discount ** t) * reward

            # Track glucose metrics from the reward (reverse-engineer glucose range)
            total_readings += 1
            if reward >= REWARD_PARAMS["in_range_max_reward"] * 0.5:
                in_range_count += 1
            if reward <= REWARD_PARAMS["hypo_penalty_scale"] * 0.1:
                hypo_count += 1

        weighted_returns.append(cumulative_weight * episode_return)
        weights.append(cumulative_weight)

    # Self-normalized importance sampling estimate
    total_weight = sum(weights)
    if total_weight == 0:
        estimated_value = 0.0
    else:
        estimated_value = sum(weighted_returns) / total_weight

    return {
        "estimated_policy_value": round(estimated_value, 3),
        "estimated_time_in_range": round(in_range_count / max(total_readings, 1), 3),
        "estimated_hypo_rate": round(hypo_count / max(total_readings, 1), 4),
        "num_test_episodes": len(test_episodes),
        "num_transitions": total_readings,
    }
```

---

## Step 7: Clinical Decision Support (Real-Time Inference)

*Maps to pseudocode Step 6 in the main recipe. This is the integration point: when a nurse enters a new glucose reading, the system constructs the current state, queries the policy, applies safety constraints, and returns a recommendation for clinician review.*

```python
# AWS clients (created once, reused across invocations in Lambda)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
state_table = dynamodb.Table(DYNAMODB_TABLE)


def fetch_patient_state(patient_id: str) -> dict:
    """
    Retrieve the patient's recent glucose history and clinical state from DynamoDB.

    The state table stores the last N readings and current clinical context
    for each active ICU patient. Updated every time a new glucose reading arrives.

    Args:
        patient_id: Unique patient identifier (e.g., "ICU-2026-04821").

    Returns:
        Dict with recent glucose readings, insulin history, and clinical context.
    """
    response = state_table.get_item(Key={"patient_id": patient_id})

    if "Item" not in response:
        logger.warning("No state found for patient %s", patient_id)
        return {}

    item = response["Item"]

    # DynamoDB stores numbers as Decimal. Convert to float for numpy compatibility.
    return {
        "glucose_current": float(item.get("glucose_current", 0)),
        "glucose_prev_1": float(item.get("glucose_prev_1", 0)),
        "glucose_prev_2": float(item.get("glucose_prev_2", 0)),
        "glucose_velocity": float(item.get("glucose_velocity", 0)),
        "insulin_on_board": float(item.get("insulin_on_board", 0)),
        "insulin_infusion_rate": float(item.get("insulin_infusion_rate", 0)),
        "nutrition_rate": float(item.get("nutrition_rate", 0)),
        "vasopressor_dose": float(item.get("vasopressor_dose", 0)),
        "steroid_flag": float(item.get("steroid_flag", 0)),
        "creatinine": float(item.get("creatinine", 1.0)),
        "bmi": float(item.get("bmi", 25)),
        "apache_score": float(item.get("apache_score", 15)),
        "previous_dose": float(item.get("previous_dose", 0)),
    }


def update_patient_state(patient_id: str, new_glucose: float, patient_data: dict):
    """
    Update the patient's state in DynamoDB with the new glucose reading.

    Shifts the glucose history forward and recomputes velocity.
    """
    # Shift history: current becomes prev_1, prev_1 becomes prev_2
    prev_1 = patient_data.get("glucose_current", new_glucose)
    prev_2 = patient_data.get("glucose_prev_1", prev_1)

    # Velocity: rate of change in mg/dL per hour (assuming 4-hour intervals)
    velocity = (new_glucose - prev_1) / 4.0 if prev_1 > 0 else 0.0

    state_table.put_item(
        Item={
            "patient_id": patient_id,
            "glucose_current": Decimal(str(round(new_glucose, 1))),
            "glucose_prev_1": Decimal(str(round(prev_1, 1))),
            "glucose_prev_2": Decimal(str(round(prev_2, 1))),
            "glucose_velocity": Decimal(str(round(velocity, 2))),
            "insulin_on_board": Decimal(str(round(
                patient_data.get("insulin_on_board", 0), 1
            ))),
            "insulin_infusion_rate": Decimal(str(round(
                patient_data.get("insulin_infusion_rate", 0), 1
            ))),
            "nutrition_rate": Decimal(str(round(
                patient_data.get("nutrition_rate", 0), 1
            ))),
            "vasopressor_dose": Decimal(str(round(
                patient_data.get("vasopressor_dose", 0), 3
            ))),
            "steroid_flag": Decimal(str(int(patient_data.get("steroid_flag", 0)))),
            "creatinine": Decimal(str(round(patient_data.get("creatinine", 1.0), 1))),
            "bmi": Decimal(str(round(patient_data.get("bmi", 25), 1))),
            "apache_score": Decimal(str(int(patient_data.get("apache_score", 15)))),
            "previous_dose": Decimal(str(round(
                patient_data.get("previous_dose", 0), 1
            ))),
            "updated_at": Decimal(str(int(time.time()))),
        }
    )


def get_policy_recommendation(state_vector: np.ndarray) -> dict:
    """
    Call the SageMaker endpoint to get the RL policy's recommended dose.

    The endpoint hosts the trained CQL model. It takes a state vector and
    returns Q-values for each action, from which we pick the best.

    Args:
        state_vector: Normalized state array from construct_state_vector.

    Returns:
        Dict with recommended_dose (units) and confidence score.
    """
    payload = json.dumps({"state": state_vector.tolist()})

    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=payload,
    )

    result = json.loads(response["Body"].read().decode("utf-8"))

    # The endpoint returns Q-values for each discrete action
    q_values = np.array(result["q_values"])
    best_action_idx = int(np.argmax(q_values))
    recommended_dose = ACTION_SPACE[best_action_idx]

    # Confidence: how much better is the best action vs. the second best?
    # Large gap = high confidence. Small gap = uncertain.
    sorted_q = np.sort(q_values)[::-1]
    if len(sorted_q) > 1 and sorted_q[0] != 0:
        confidence = min(1.0, (sorted_q[0] - sorted_q[1]) / abs(sorted_q[0]))
    else:
        confidence = 0.5

    return {
        "recommended_dose": recommended_dose,
        "action_index": best_action_idx,
        "confidence": round(confidence, 3),
        "q_values": q_values.tolist(),
    }
```

---

## Full Pipeline: Generate Recommendation

This assembles all the steps into a single callable function. In production, this would be the Lambda handler invoked when a new glucose reading arrives from the EHR integration.

```python
def generate_insulin_recommendation(patient_id: str, new_glucose: float) -> dict:
    """
    End-to-end pipeline: new glucose reading in, insulin recommendation out.

    This is the function that gets called when a nurse enters a new glucose
    measurement. It:
    1. Fetches the patient's recent history
    2. Updates state with the new reading
    3. Constructs the RL state vector
    4. Gets the policy's recommendation
    5. Applies safety constraints
    6. Returns a recommendation for clinician review

    The clinician always has the final say. This is decision support, not
    autonomous control.

    Args:
        patient_id: Unique patient identifier.
        new_glucose: The new glucose reading in mg/dL.

    Returns:
        Dict with the recommendation, reasoning, and safety information.
    """
    print(f"\n{'='*60}")
    print(f"GLUCOSE CONTROL RL: New reading for {patient_id}")
    print(f"{'='*60}")

    # Step 1: Fetch current patient state
    print("\n[1/5] Fetching patient state from DynamoDB...")
    patient_data = fetch_patient_state(patient_id)
    if not patient_data:
        print("  WARNING: No prior state found. Using defaults.")
        patient_data = {"glucose_current": new_glucose, "previous_dose": 0}

    # Step 2: Update state with new reading
    print(f"[2/5] Updating state: new glucose = {new_glucose} mg/dL")
    update_patient_state(patient_id, new_glucose, patient_data)

    # Refresh patient_data with the new glucose as current
    patient_data["glucose_prev_2"] = patient_data.get("glucose_prev_1", new_glucose)
    patient_data["glucose_prev_1"] = patient_data.get("glucose_current", new_glucose)
    patient_data["glucose_current"] = new_glucose
    patient_data["glucose_velocity"] = (
        (new_glucose - patient_data["glucose_prev_1"]) / 4.0
    )

    # Step 3: Construct state vector
    print("[3/5] Constructing state vector...")
    state_vector = construct_state_vector(patient_data)
    print(f"  State vector (first 4 features): {state_vector[:4]}")

    # Step 4: Get policy recommendation
    print("[4/5] Querying RL policy endpoint...")
    policy_result = get_policy_recommendation(state_vector)
    raw_dose = policy_result["recommended_dose"]
    print(f"  Raw recommendation: {raw_dose} units (confidence: {policy_result['confidence']})")

    # Step 5: Apply safety constraints
    print("[5/5] Applying safety constraints...")
    previous_dose = patient_data.get("previous_dose", 0)
    safe_result = apply_safety_constraints(raw_dose, patient_data, previous_dose)

    if safe_result["constraints_activated"]:
        for constraint in safe_result["constraints_activated"]:
            print(f"  CONSTRAINT: {constraint}")
    else:
        print("  No constraints activated.")

    final_dose = safe_result["final_dose"]
    print(f"\n  FINAL RECOMMENDATION: {final_dose} units insulin")

    # Package the recommendation
    recommendation = {
        "patient_id": patient_id,
        "timestamp": int(time.time()),
        "glucose_reading": new_glucose,
        "recommended_dose": final_dose,
        "dose_units": "units insulin (regular)",
        "confidence": policy_result["confidence"],
        "reasoning": {
            "current_glucose": new_glucose,
            "glucose_trend": round(patient_data["glucose_velocity"], 1),
            "insulin_on_board": patient_data.get("insulin_on_board", 0),
            "raw_policy_dose": raw_dose,
            "constraints_activated": safe_result["constraints_activated"],
        },
        "clinician_action": "PENDING",
    }

    print(f"\n  Recommendation packaged. Awaiting clinician decision.")
    print(f"{'='*60}\n")

    return recommendation


# --- Example usage ---
if __name__ == "__main__":
    # Simulate a sequence of glucose readings for a patient
    # In production, each call would be triggered by an EHR event.
    print("=" * 60)
    print("DEMO: Simulating glucose control recommendations")
    print("=" * 60)

    # Note: This will fail without actual AWS resources configured.
    # It's here to show the calling pattern.
    try:
        result = generate_insulin_recommendation("ICU-2026-04821", 195.0)
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(f"\nExpected error (no AWS resources): {e}")
        print("In production, this connects to real DynamoDB and SageMaker endpoints.")
```

---

## Gap to Production

This example demonstrates the shape of an RL-based glucose control system. Here's the distance between this code and something you'd deploy in an ICU:

**Data pipeline (the real 70% of the work):**
- EHR integration via HL7 FHIR or proprietary APIs to pull glucose, insulin, nutrition, and medication data in real time
- Temporal alignment of irregularly-sampled clinical data into consistent decision intervals
- Handling of missing data (forward-fill, learned imputation, staleness flags)
- Data validation: reject physiologically impossible values (glucose of 5000 is a meter error, not a reading)
- De-identification pipeline for training data; BAA-covered access for production inference

**Model training:**
- Replace the tabular Q-function with a neural network (2-layer MLP with 256 hidden units is standard)
- Use a proper CQL implementation (e.g., d3rlpy library or custom PyTorch)
- Hyperparameter tuning: CQL alpha, discount factor, network architecture, batch size
- Train on thousands of ICU stays (this example works with toy data)
- Cross-validation across patient subpopulations (surgical, medical, cardiac)

**Safety and validation:**
- Extensive off-policy evaluation on held-out data with confidence intervals
- Physiological simulator testing (glucose-insulin dynamics models)
- Comparison against existing sliding scale protocols on retrospective data
- Formal safety analysis: worst-case hypoglycemia rates under the learned policy
- IRB approval for any prospective evaluation
- FDA regulatory pathway assessment (likely Class II medical device)

**Deployment:**
- Shadow mode: run the system in parallel with existing protocols for months, logging recommendations without displaying them, to validate against actual clinician decisions
- Clinician education and trust-building before any recommendations are shown
- Gradual rollout: start with a single ICU, expand after demonstrating safety
- Real-time monitoring: alert on recommendation patterns that deviate from expected distributions
- Drift detection: retrain when patient population or clinical practice changes
- Override logging and analysis: learn from clinician disagreements

**Infrastructure hardening:**
- Error handling and retries for all AWS API calls (already partially shown)
- Input validation: reject malformed glucose readings, out-of-range values
- Structured JSON logging with correlation IDs (never log PHI values)
- IAM least-privilege: separate roles for training vs. inference vs. state management
- VPC with VPC endpoints for S3, DynamoDB, SageMaker Runtime, and CloudWatch
- KMS customer-managed keys for all PHI-containing resources
- DynamoDB point-in-time recovery and S3 versioning for audit trail
- Load testing: ensure the inference path completes within the clinical workflow timeout (< 5 seconds)

**The honest gap:** This example is maybe 5% of a production system. The RL algorithm is the intellectually interesting part, but the data pipeline, safety validation, regulatory pathway, and clinician trust-building are what determine whether this ever helps a patient. Plan for 12-18 months from "working prototype" to "shadow mode in one ICU."

---

| [← Recipe 15.6: Glucose Control in ICU](chapter15.06-glucose-control-icu) | [Chapter 15 Index](chapter15-preface) | [15.7: Chronic Disease Treatment Personalization →](chapter15.07-chronic-disease-treatment-personalization) |
|:---|:---:|---:|
